from datetime import datetime, timezone as utc
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit
from xml.etree import ElementTree

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from tenancy.models import Project, ProjectConfiguration, normalize_origin
from tenancy.services import Action, require_project_action

from .crawling import CrawlScope, FetchDenied, FetchError, SafeFetcher


MAX_FEED_BYTES = 128 * 1024
MAX_FEED_ITEMS = 50
ATOM = "{http://www.w3.org/2005/Atom}"


def _origin(url):
    parsed = urlsplit(url)
    return normalize_origin(urlunsplit((parsed.scheme, parsed.netloc, "", "", "")))


def _safe_link(value, allowed_origins):
    if not value or len(value) > 2048:
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or parsed.port not in (None, 443)
            or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment):
            return None
        if _origin(value) not in allowed_origins:
            return None
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", "", ""))
    except (ValueError, ValidationError, FetchDenied):
        return None


def _published(value):
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00")) if value[0].isdigit() else parsedate_to_datetime(value)
        return moment.astimezone(utc.utc) if moment.tzinfo is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def parse_feed(*, body, feed_url, allowed_origins, collected_at=None):
    collected_at = collected_at or timezone.now()
    if not isinstance(body, bytes) or len(body) > MAX_FEED_BYTES:
        return {"state": "failed", "error": "feed_size_or_encoding", "items": [], "total_seen": 0}
    if any(marker in body.lower() for marker in (b"<!doctype", b"<!entity", b"\x00")):
        return {"state": "failed", "error": "unsafe_xml", "items": [], "total_seen": 0}
    try:
        body.decode("utf-8-sig")
        root = ElementTree.fromstring(body)
    except (ElementTree.ParseError, UnicodeError, ValueError):
        return {"state": "failed", "error": "invalid_xml", "items": [], "total_seen": 0}
    if root.tag == "rss":
        entries = root.findall("./channel/item")
        kind = "rss"
    elif root.tag == ATOM + "feed":
        entries = root.findall(ATOM + "entry")
        kind = "atom"
    else:
        return {"state": "failed", "error": "unsupported_feed", "items": [], "total_seen": 0}
    items = []
    rejected = 0
    seen = set()
    for entry in entries[:MAX_FEED_ITEMS]:
        title = entry.findtext("title") if kind == "rss" else entry.findtext(ATOM + "title")
        link = entry.findtext("link") if kind == "rss" else next(
            (item.get("href") for item in entry.findall(ATOM + "link") if item.get("rel", "alternate") == "alternate"), None,
        )
        date_text = entry.findtext("pubDate") if kind == "rss" else (
            entry.findtext(ATOM + "published") or entry.findtext(ATOM + "updated")
        )
        safe_link = _safe_link(link, allowed_origins)
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 240 or safe_link is None:
            rejected += 1
            continue
        published = _published(date_text)
        if published and published > collected_at:
            rejected += 1
            continue
        key = (safe_link, title.strip().casefold(), published)
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "title": title.strip(), "url": safe_link, "source_feed": feed_url,
            "published_at": published.isoformat() if published else None,
            "freshness": "unknown" if published is None else "stale" if (collected_at - published).days > 90 else "recent",
            "observation": "public_feed_item_not_popularity_or_business_relevance",
        })
    return {
        "state": "partial" if len(entries) > MAX_FEED_ITEMS or rejected else "complete_for_bounded_feed",
        "error": "", "format": kind, "items": items,
        "total_seen": min(len(entries), MAX_FEED_ITEMS), "rejected": rejected,
        "truncated": len(entries) > MAX_FEED_ITEMS,
        "collected_at": collected_at.isoformat(),
    }


def collect_project_feed(*, project, user, feed_url, fetcher=None):
    project = Project.objects.get(pk=project.pk, organization_id=project.organization_id)
    require_project_action(project=project, user=user, action=Action.LAUNCH_JOB)
    config = ProjectConfiguration.objects.filter(project=project).first()
    if not isinstance(feed_url, str) or config is None or feed_url not in config.rss_feed_urls:
        raise PermissionDenied("Feed is not configured for this project.")
    origin = _origin(feed_url)
    if origin not in config.research_allowed_origins or origin in config.research_blocked_origins:
        raise PermissionDenied("Feed origin is not allowed.")

    def same_origin(url):
        try:
            parsed = urlsplit(url)
            allowed = (parsed.scheme == "https" and parsed.port in (None, 443)
                       and not parsed.query and not parsed.fragment and _origin(url) == origin)
        except (ValueError, ValidationError):
            allowed = False
        if not allowed:
            raise FetchDenied("feed_scope_denied")

    same_origin(feed_url)
    fetcher = fetcher or SafeFetcher(
        CrawlScope(frozenset({urlsplit(origin).hostname}), kind="rss"),
        timeout=8, max_redirects=2, max_bytes=MAX_FEED_BYTES,
    )
    try:
        response = fetcher.fetch(feed_url, before_request=same_origin)
        same_origin(response.url)
    except FetchError as error:
        return {"state": "failed", "error": error.code, "items": [], "source_feed": feed_url}
    # A feed may be removed or access revoked while the network operation is in flight.
    project = Project.objects.get(pk=project.pk, organization_id=project.organization_id)
    require_project_action(project=project, user=user, action=Action.LAUNCH_JOB)
    current = ProjectConfiguration.objects.filter(project=project).first()
    if (current is None or feed_url not in current.rss_feed_urls
        or origin not in current.research_allowed_origins or origin in current.research_blocked_origins):
        return {"state": "failed", "error": "feed_scope_revoked", "items": [], "source_feed": feed_url}
    if response.status != 200:
        return {"state": "failed", "error": "feed_http_status", "items": [], "source_feed": feed_url}
    if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() not in {
        "application/rss+xml", "application/atom+xml", "application/xml", "text/xml",
    }:
        return {"state": "failed", "error": "unsupported_feed_type", "items": [], "source_feed": feed_url}
    result = parse_feed(body=response.body, feed_url=feed_url, allowed_origins=set(current.research_allowed_origins))
    return {**result, "source_feed": feed_url}
