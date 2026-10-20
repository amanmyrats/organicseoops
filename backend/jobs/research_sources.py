"""Explicit, bounded research URLs only; page text never grants tool authority."""
from hashlib import sha256
from html.parser import HTMLParser
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.utils import timezone

from tenancy.models import normalize_origin
from .crawling import CrawlScope, FetchDenied, FetchError, SafeFetcher

MAX_SOURCE_BYTES = 128 * 1024
MAX_EXCERPT_CHARACTERS = 2048


def source_url(value, configuration):
    if (type(value) is not str or not 1 <= len(value) <= 1024 or "\\" in value
        or any(ord(char) < 32 for char in value)):
        raise ValidationError("Select an approved HTTPS research URL.")
    try:
        parsed = urlsplit(value)
        origin = normalize_origin(f"{parsed.scheme}://{parsed.netloc}")
        if (parsed.scheme != "https" or parsed.port not in (None, 443) or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment or configuration is None
            or origin not in configuration.research_allowed_origins or origin in configuration.research_blocked_origins):
            raise ValueError
        normalized = CrawlScope(frozenset({parsed.hostname}), kind="research").validate_url(value)
    except (ValueError, ValidationError, FetchDenied):
        raise ValidationError("Select an approved HTTPS research URL.") from None
    return normalized


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0
        self.title = False
        self.titles = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "template", "noscript"}:
            self.hidden += 1
        if tag == "title":
            self.title = True

    def handle_endtag(self, tag):
        if tag in {"script", "style", "template", "noscript"}:
            self.hidden = max(0, self.hidden - 1)
        if tag == "title":
            self.title = False

    def handle_data(self, value):
        if not self.hidden:
            self.parts.append(value)
            if self.title:
                self.titles.append(value)


def collect_research_source(*, url, configuration, before_request, fetcher=None):
    url = source_url(url, configuration)
    origin = normalize_origin(f"https://{urlsplit(url).netloc}")

    def checkpoint(target):
        before_request()
        try:
            if (source_url(target, configuration) != target
                or normalize_origin(f"https://{urlsplit(target).netloc}") != origin):
                raise ValueError
        except (ValueError, ValidationError):
            raise FetchDenied("research_redirect_scope") from None

    fetcher = fetcher or SafeFetcher(CrawlScope(frozenset({urlsplit(url).hostname}), kind="research"),
                                    timeout=8, max_redirects=2, max_bytes=MAX_SOURCE_BYTES)
    try:
        response = fetcher.fetch(url, before_request=checkpoint)
        checkpoint(response.url)
        before_request()
        if response.status != 200:
            raise FetchError("source_http_status")
        if type(response.body) is not bytes or not 1 <= len(response.body) <= MAX_SOURCE_BYTES:
            raise FetchError("source_size")
        kind = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if kind not in {"text/html", "text/plain"}:
            raise FetchError("source_content_type")
        text = response.body.decode("utf-8-sig")
        title = "Research source"
        if kind == "text/html":
            parser = _Text()
            parser.feed(text)
            parser.close()
            text = " ".join(parser.parts)
            title = " ".join(" ".join(parser.titles).split())[:240] or title
        text = " ".join(text.split())
        if not text:
            raise FetchError("source_no_text")
        return {"state": "collected", "requested_url": url, "url": response.url,
                "title": title, "retrieved_at": timezone.now().isoformat(),
                "sha256": sha256(response.body).hexdigest(), "size_bytes": len(response.body),
                "excerpt": text[:MAX_EXCERPT_CHARACTERS], "excerpt_truncated": len(text) > MAX_EXCERPT_CHARACTERS,
                "evidence": "public_page_text_not_verified_fact"}
    except FetchError as error:
        return {"state": "unavailable", "requested_url": url, "error_category": error.code,
                "retrieved_at": timezone.now().isoformat()}
    except (UnicodeError, ValueError, RecursionError):
        return {"state": "unavailable", "requested_url": url, "error_category": "source_text_invalid",
                "retrieved_at": timezone.now().isoformat()}
