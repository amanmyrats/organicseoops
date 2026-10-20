"""Original bounded static syntax, without source, transport or storage authority."""
from hashlib import sha256
from html.parser import HTMLParser
import json
import re
from urllib.parse import unquote, urlsplit

from django.core.exceptions import ValidationError

from integrations.google_tokens import _reject_constant, _unique_object
from .competitor_source import _origin
from .crawling import CrawlScope, FetchError
from .passive_resources import EXCLUDED as RESOURCE_EXCLUDED
from .passive_tls_evidence import _date


METHOD = "competitor-static-metadata-v1"
MAX_BODY_BYTES = 128 * 1024
MAX_RESULT_BYTES = 8192
MAX_ELEMENTS = 1000
COUNTS = (*[f"h{level}" for level in range(1, 7)], "href_anchors", "json_ld_blocks")
EXCLUDED = RESOURCE_EXCLUDED - {"title"}
COVERAGE = "one_complete_returned_static_document_selected_lexical_metadata_only"
INTERPRETATION = "static_syntax_not_rendering_schema_validity_topics_publication_age_traffic_rankings_backlinks_or_whole_site"


def _deny():
    raise ValidationError("Original bounded static competitor metadata is unavailable.")


def validate_url(value):
    if (type(value) is not str or not 1 <= len(value) <= 1024 or "?" in value or "#" in value
        or any(ord(char) < 33 or ord(char) == 127 or char == "\\" for char in unquote(value))):
        _deny()
    try:
        parts = urlsplit(value)
        host = _origin(parts.scheme + "://" + parts.netloc)
        if CrawlScope(frozenset({host})).validate_url(value) != value: _deny()
    except (ValueError, UnicodeError, FetchError):
        _deny()
    return value


class _Unavailable(Exception):
    pass


class _Metadata(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = []
        self.title = None
        self.title_seen = False
        self.title_parts = []
        self.description = None
        self.counts = dict.fromkeys(COUNTS, 0)

    def handle_starttag(self, tag, attrs):
        if self.title is not None: raise _Unavailable("ambiguous_markup")
        if not self.hidden:
            names = [name for name, _value in attrs]
            values = dict(attrs)
            if tag == "title":
                if self.title_seen: raise _Unavailable("ambiguous_markup")
                self.title_seen = True
                self.title = True
            elif tag == "meta":
                if names.count("name") > 1 or names.count("content") > 1: raise _Unavailable("ambiguous_markup")
                if (values.get("name") or "").lower() == "description":
                    if self.description is not None: raise _Unavailable("ambiguous_markup")
                    self.description = values.get("content") or ""
            key = tag if tag in COUNTS else None
            if tag == "a":
                if names.count("href") > 1: raise _Unavailable("ambiguous_markup")
                if "href" in names: key = "href_anchors"
            if tag == "script":
                if names.count("type") > 1: raise _Unavailable("ambiguous_markup")
                if (values.get("type") or "").split(";", 1)[0].strip().lower() == "application/ld+json":
                    key = "json_ld_blocks"
            if key:
                if sum(self.counts.values()) >= MAX_ELEMENTS: raise _Unavailable("element_limit")
                self.counts[key] += 1
        if tag in EXCLUDED:
            if len(self.hidden) >= 100: raise _Unavailable("ambiguous_markup")
            self.hidden.append(tag)

    def handle_endtag(self, tag):
        if self.hidden:
            if tag in EXCLUDED:
                if self.hidden[-1] != tag: raise _Unavailable("ambiguous_markup")
                self.hidden.pop()
            return
        if self.title is not None and tag != "title": raise _Unavailable("ambiguous_markup")
        if tag == "title":
            if self.title is None: raise _Unavailable("ambiguous_markup")
            self.title = None
        elif tag in EXCLUDED:
            raise _Unavailable("ambiguous_markup")

    def handle_startendtag(self, tag, attrs):
        if tag in EXCLUDED or tag == "title": raise _Unavailable("ambiguous_markup")
        self.handle_starttag(tag, attrs)

    def handle_data(self, value):
        if self.title is not None: self.title_parts.append(value)


def _text(value, limit):
    if (type(value) is not str or len(value) > limit or value != " ".join(value.split())
        or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        _deny()


def validate_metadata(result):
    if (type(result) is not dict or set(result) != {"method_version", "url", "observed_at", "body_sha256", "body_size_bytes",
        "state", "reason", "metadata", "counts", "coverage", "excluded_containers", "interpretation"}
        or result["method_version"] != METHOD or result["coverage"] != COVERAGE
        or result["interpretation"] != INTERPRETATION or result["excluded_containers"] != sorted(EXCLUDED)
        or type(result["body_sha256"]) is not str or not re.fullmatch(r"[a-f0-9]{64}", result["body_sha256"])
        or type(result["body_size_bytes"]) is not int or not 1 <= result["body_size_bytes"] <= MAX_BODY_BYTES
        or type(result["counts"]) is not dict or set(result["counts"]) != set(COUNTS)):
        _deny()
    validate_url(result["url"])
    _date(result["observed_at"])
    counts = result["counts"]
    if result["state"] == "unavailable":
        if (type(result["reason"]) is not str or result["reason"] not in {"ambiguous_markup", "element_limit"} or result["metadata"] is not None
            or any(value is not None for value in counts.values())): _deny()
    elif result["state"] == "observed":
        metadata = result["metadata"]
        if (result["reason"] != "" or type(metadata) is not dict
            or set(metadata) != {"title", "description", "title_truncated", "description_truncated"}
            or any(type(value) is not int or not 0 <= value <= MAX_ELEMENTS for value in counts.values())
            or sum(counts.values()) > MAX_ELEMENTS): _deny()
        for key, limit in (("title", 500), ("description", 1000)):
            _text(metadata[key], limit)
            if (type(metadata[key + "_truncated"]) is not bool
                or metadata[key + "_truncated"] and not metadata[key]): _deny()
    else: _deny()
    return result


def encode_metadata(result):
    validate_metadata(result)
    try: content = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError): _deny()
    if len(content) > MAX_RESULT_BYTES: _deny()
    return content


def parse_metadata(content):
    if type(content) is not bytes or not 1 <= len(content) <= MAX_RESULT_BYTES: _deny()
    try: result = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError): _deny()
    validate_metadata(result)
    encode_metadata(result)
    return result


def observe_static_metadata(*, body, body_complete, url, observed_at):
    validate_url(url)
    _date(observed_at)
    if body_complete is not True or type(body) is not bytes or not 1 <= len(body) <= MAX_BODY_BYTES: _deny()
    try:
        html = body.decode("utf-8-sig")
        if any(ord(char) < 32 and char not in "\t\r\n" or ord(char) == 127 for char in html): _deny()
    except UnicodeError: _deny()
    result = {"method_version": METHOD, "url": url, "observed_at": observed_at, "body_sha256": sha256(body).hexdigest(),
        "body_size_bytes": len(body), "state": "unavailable", "reason": "ambiguous_markup", "metadata": None,
        "counts": dict.fromkeys(COUNTS), "coverage": COVERAGE, "excluded_containers": sorted(EXCLUDED), "interpretation": INTERPRETATION}
    try:
        parser = _Metadata()
        parser.feed(html)
        if parser.rawdata or parser.hidden or parser.title is not None: raise _Unavailable("ambiguous_markup")
        parser.close()
    except _Unavailable as error:
        result["reason"] = str(error)
    except (ValueError, AssertionError, RecursionError):
        pass
    else:
        title = " ".join("".join(parser.title_parts).split())
        description = " ".join((parser.description or "").split())
        result.update(state="observed", reason="", counts=parser.counts, metadata={"title": title[:500].rstrip(), "description": description[:1000].rstrip(),
            "title_truncated": len(title) > 500, "description_truncated": len(description) > 1000})
    return parse_metadata(encode_metadata(result))
