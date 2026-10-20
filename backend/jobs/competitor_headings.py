"""Original bounded literal heading text/order; no browser, topic or source authority."""
import json

from django.core.exceptions import ValidationError

from integrations.google_tokens import _reject_constant, _unique_object
from . import competitor_metadata as metadata


METHOD = "competitor-static-headings-v1"
COVERAGE = "one_complete_returned_static_document_non_inert_heading_occurrences_in_original_order"
INTERPRETATION = "literal_text_levels_not_browser_visibility_semantic_outline_accessibility_topics_page_identity_publication_age_freshness_or_whole_site"
COUNTS = tuple(f"h{level}" for level in range(1, 7))
MAX_HEADINGS = 10
MAX_TEXT = 80
REASONS = frozenset({"ambiguous_markup", "element_limit", "heading_limit", "result_limit"})


class _Headings(metadata._Metadata):
    def __init__(self):
        super().__init__()
        self.heading = None
        self.parts = []
        self.headings = []

    def handle_starttag(self, tag, attrs):
        active = not self.hidden and self.title is None
        if active and (tag in COUNTS or tag == "title" and self.heading is not None):
            if self.heading is not None: raise metadata._Unavailable("ambiguous_markup")
            if tag in COUNTS:
                if len(self.headings) >= MAX_HEADINGS: raise metadata._Unavailable("heading_limit")
                self.heading = tag
                self.parts = []
        super().handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if not self.hidden and self.title is None and tag in COUNTS:
            if tag != self.heading: raise metadata._Unavailable("ambiguous_markup")
            text = " ".join("".join(self.parts).split())
            self.headings.append({"level": int(tag[1]), "text": text[:MAX_TEXT].rstrip(), "truncated": len(text) > MAX_TEXT})
            self.heading = None
            self.parts = []
        super().handle_endtag(tag)

    def handle_startendtag(self, tag, attrs):
        if not self.hidden and self.title is None and tag in COUNTS: raise metadata._Unavailable("ambiguous_markup")
        super().handle_startendtag(tag, attrs)

    def handle_data(self, value):
        if self.heading is not None and not self.hidden and self.title is None: self.parts.append(value)
        super().handle_data(value)


def _deny():
    raise ValidationError("Original bounded literal competitor headings are unavailable.")


def validate_headings(result):
    if (type(result) is not dict or set(result) != {"method_version", "url", "observed_at", "body_sha256", "body_size_bytes",
        "state", "reason", "headings", "counts", "coverage", "excluded_containers", "interpretation"}
        or result["method_version"] != METHOD or result["coverage"] != COVERAGE
        or result["interpretation"] != INTERPRETATION or result["excluded_containers"] != sorted(metadata.EXCLUDED)
        or type(result["counts"]) is not dict or set(result["counts"]) != set(COUNTS)): _deny()
    metadata.validate_metadata({**{key: result[key] for key in ("url", "observed_at", "body_sha256", "body_size_bytes")},
        "method_version": metadata.METHOD, "state": "unavailable", "reason": "ambiguous_markup", "metadata": None,
        "counts": dict.fromkeys(metadata.COUNTS), "coverage": metadata.COVERAGE,
        "excluded_containers": sorted(metadata.EXCLUDED), "interpretation": metadata.INTERPRETATION})
    if result["state"] == "unavailable":
        if (type(result["reason"]) is not str or result["reason"] not in REASONS or result["headings"] is not None
            or any(value is not None for value in result["counts"].values())): _deny()
    elif result["state"] == "observed":
        if (result["reason"] != "" or type(result["headings"]) is not list or len(result["headings"]) > MAX_HEADINGS): _deny()
        counts = dict.fromkeys(COUNTS, 0)
        for item in result["headings"]:
            if (type(item) is not dict or set(item) != {"level", "text", "truncated"}
                or type(item["level"]) is not int or not 1 <= item["level"] <= 6
                or type(item["truncated"]) is not bool or item["truncated"] and not item["text"]): _deny()
            metadata._text(item["text"], MAX_TEXT)
            counts["h" + str(item["level"])] += 1
        if any(type(value) is not int for value in result["counts"].values()) or result["counts"] != counts: _deny()
    else: _deny()
    return result


def encode_headings(result):
    validate_headings(result)
    try: content = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError): _deny()
    if len(content) > metadata.MAX_RESULT_BYTES: _deny()
    return content


def parse_headings(content):
    if type(content) is not bytes or not 1 <= len(content) <= metadata.MAX_RESULT_BYTES: _deny()
    try: result = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError): _deny()
    encode_headings(result)
    return result


def observe_static_headings(*, body, body_complete, url, observed_at):
    original = metadata.observe_static_metadata(body=body, body_complete=body_complete, url=url, observed_at=observed_at)
    result = {key: original[key] for key in ("url", "observed_at", "body_sha256", "body_size_bytes", "state", "reason", "excluded_containers")}
    result.update(method_version=METHOD, headings=None, counts=dict.fromkeys(COUNTS), coverage=COVERAGE, interpretation=INTERPRETATION)
    if original["state"] == "observed":
        try:
            parser = _Headings()
            parser.feed(body.decode("utf-8-sig"))
            if parser.heading is not None: raise metadata._Unavailable("ambiguous_markup")
            parser.close()
        except metadata._Unavailable as error:
            result.update(state="unavailable", reason=str(error))
        else:
            result.update(headings=parser.headings, counts={key: original["counts"][key] for key in COUNTS})
            if len(json.dumps(result, separators=(",", ":"), ensure_ascii=False).encode("utf-8")) > metadata.MAX_RESULT_BYTES:
                result.update(state="unavailable", reason="result_limit", headings=None, counts=dict.fromkeys(COUNTS))
    return parse_headings(encode_headings(result))
