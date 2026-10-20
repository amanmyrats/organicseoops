"""Original static href occurrence categories; no destination or collection authority."""
import json
import re
from urllib.parse import unquote, urljoin, urlsplit

from django.core.exceptions import ValidationError

from integrations.google_tokens import _reject_constant, _unique_object
from . import competitor_metadata as metadata


METHOD = "competitor-static-link-categories-v1"
COVERAGE = "one_complete_returned_static_document_non_inert_html_decoded_href_occurrences_no_base_stdlib_uri_join_only"
INTERPRETATION = "static_reference_categories_not_unique_pages_browser_visibility_link_health_inbound_links_or_whole_site_structure"
COUNTS = ("href_anchors", "same_origin_http", "other_origin_http", "unsupported")
REASONS = frozenset({"ambiguous_markup", "element_limit", "base_dependent_references"})


def _category(value, source_url):
    if (type(value) is not str or not 1 <= len(value) <= 1024 or "?" in value or "#" in value
        or re.search(r"%(?![a-fA-F0-9]{2})", value)
        or any(char.isspace() or ord(char) < 33 or ord(char) == 127 or char == "\\" for char in unquote(value))):
        return "unsupported"
    try:
        reference = urlsplit(value)
        if (reference.scheme and (reference.scheme not in {"http", "https"} or not reference.netloc)
            or value.startswith("//") and not reference.netloc):
            return "unsupported"
        resolved = urljoin(source_url, value)
        parts = urlsplit(resolved)
        if not parts.path: resolved += "/"
        metadata.validate_url(resolved)
        original = urlsplit(source_url)
        return "same_origin_http" if (parts.scheme, parts.netloc) == (original.scheme, original.netloc) else "other_origin_http"
    except (ValidationError, ValueError, UnicodeError):
        return "unsupported"


class _Links(metadata._Metadata):
    def __init__(self, source_url):
        super().__init__()
        self.source_url = source_url
        self.link_counts = dict.fromkeys(COUNTS, 0)
        self.anchor_open = False

    def handle_starttag(self, tag, attrs):
        active = not self.hidden and self.title is None
        super().handle_starttag(tag, attrs)
        if not active: return
        if tag == "base": raise metadata._Unavailable("base_dependent_references")
        if tag == "a":
            if self.anchor_open: raise metadata._Unavailable("ambiguous_markup")
            self.anchor_open = True
            values = dict(attrs)
            if "href" in values:
                self.link_counts["href_anchors"] += 1
                self.link_counts[_category(values["href"], self.source_url)] += 1

    def handle_endtag(self, tag):
        if not self.hidden and self.title is None and tag == "a":
            if not self.anchor_open: raise metadata._Unavailable("ambiguous_markup")
            self.anchor_open = False
        super().handle_endtag(tag)

    def handle_startendtag(self, tag, attrs):
        if not self.hidden and self.title is None and tag == "a": raise metadata._Unavailable("ambiguous_markup")
        super().handle_startendtag(tag, attrs)


def _deny():
    raise ValidationError("Original bounded static competitor link categories are unavailable.")


def validate_links(result):
    if (type(result) is not dict or set(result) != {"method_version", "url", "observed_at", "body_sha256", "body_size_bytes",
        "state", "reason", "counts", "coverage", "excluded_containers", "interpretation"}
        or result["method_version"] != METHOD or result["coverage"] != COVERAGE
        or result["interpretation"] != INTERPRETATION or result["excluded_containers"] != sorted(metadata.EXCLUDED)
        or type(result["counts"]) is not dict or set(result["counts"]) != set(COUNTS)):
        _deny()
    metadata.validate_metadata({**{key: result[key] for key in ("url", "observed_at", "body_sha256", "body_size_bytes")},
        "method_version": metadata.METHOD, "state": "unavailable", "reason": "ambiguous_markup", "metadata": None,
        "counts": dict.fromkeys(metadata.COUNTS), "coverage": metadata.COVERAGE,
        "excluded_containers": sorted(metadata.EXCLUDED), "interpretation": metadata.INTERPRETATION})
    counts = result["counts"]
    if result["state"] == "unavailable":
        if (type(result["reason"]) is not str or result["reason"] not in REASONS
            or any(value is not None for value in counts.values())): _deny()
    elif result["state"] == "observed":
        if (result["reason"] != "" or any(type(value) is not int or not 0 <= value <= metadata.MAX_ELEMENTS for value in counts.values())
            or sum(counts[key] for key in COUNTS[1:]) != counts["href_anchors"]): _deny()
    else: _deny()
    return result


def encode_links(result):
    validate_links(result)
    try: content = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError): _deny()
    if len(content) > metadata.MAX_RESULT_BYTES: _deny()
    return content


def parse_links(content):
    if type(content) is not bytes or not 1 <= len(content) <= metadata.MAX_RESULT_BYTES: _deny()
    try: result = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError): _deny()
    encode_links(result)
    return result


def observe_static_links(*, body, body_complete, url, observed_at):
    original = metadata.observe_static_metadata(body=body, body_complete=body_complete, url=url, observed_at=observed_at)
    result = {key: original[key] for key in ("url", "observed_at", "body_sha256", "body_size_bytes", "state", "reason", "excluded_containers")}
    result.update(method_version=METHOD, counts=dict.fromkeys(COUNTS), coverage=COVERAGE, interpretation=INTERPRETATION)
    if original["state"] == "observed":
        try:
            parser = _Links(url)
            parser.feed(body.decode("utf-8-sig"))
            if parser.anchor_open: raise metadata._Unavailable("ambiguous_markup")
            parser.close()
        except metadata._Unavailable as error:
            result.update(state="unavailable", reason=str(error))
        else:
            result["counts"] = parser.link_counts
    return parse_links(encode_links(result))
