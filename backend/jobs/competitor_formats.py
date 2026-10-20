"""Literal static content-element counts; no rendered format or source authority."""
import json

from django.core.exceptions import ValidationError

from integrations.google_tokens import _reject_constant, _unique_object
from . import competitor_metadata as metadata


METHOD = "competitor-static-content-elements-v1"
COUNTS = ("p", "ul", "ol", "table", "img", "picture", "video", "audio")
COVERAGE = "one_complete_returned_static_document_non_inert_selected_start_tag_occurrences_only"
INTERPRETATION = "literal_start_tags_not_rendered_content_formats_page_types_loaded_media_accessibility_search_result_features_topics_freshness_or_whole_site"


class _Formats(metadata._Metadata):
    def __init__(self):
        super().__init__()
        self.element_counts = dict.fromkeys(COUNTS, 0)

    def handle_starttag(self, tag, attrs):
        active = not self.hidden and self.title is None
        super().handle_starttag(tag, attrs)
        if active and tag in COUNTS:
            if sum(self.element_counts.values()) >= metadata.MAX_ELEMENTS:
                raise metadata._Unavailable("element_limit")
            self.element_counts[tag] += 1


def _deny():
    raise ValidationError("Original bounded static content-element counts are unavailable.")


def validate_formats(result):
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
        if (type(result["reason"]) is not str or result["reason"] not in {"ambiguous_markup", "element_limit"}
            or any(value is not None for value in counts.values())):
            _deny()
    elif result["state"] == "observed":
        if (result["reason"] != "" or any(type(value) is not int or not 0 <= value <= metadata.MAX_ELEMENTS for value in counts.values())
            or sum(counts.values()) > metadata.MAX_ELEMENTS):
            _deny()
    else:
        _deny()
    return result


def encode_formats(result):
    validate_formats(result)
    try:
        content = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _deny()
    if len(content) > metadata.MAX_RESULT_BYTES:
        _deny()
    return content


def parse_formats(content):
    if type(content) is not bytes or not 1 <= len(content) <= metadata.MAX_RESULT_BYTES:
        _deny()
    try:
        result = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError):
        _deny()
    encode_formats(result)
    return result


def observe_static_formats(*, body, body_complete, url, observed_at):
    original = metadata.observe_static_metadata(body=body, body_complete=body_complete, url=url, observed_at=observed_at)
    result = {key: original[key] for key in ("url", "observed_at", "body_sha256", "body_size_bytes", "state", "reason", "excluded_containers")}
    result.update(method_version=METHOD, counts=dict.fromkeys(COUNTS), coverage=COVERAGE, interpretation=INTERPRETATION)
    if original["state"] == "observed":
        try:
            parser = _Formats()
            parser.feed(body.decode("utf-8-sig"))
            if parser.rawdata or parser.hidden or parser.title is not None:
                raise metadata._Unavailable("ambiguous_markup")
            parser.close()
        except metadata._Unavailable as error:
            result.update(state="unavailable", reason=str(error))
        except (ValueError, AssertionError, RecursionError):
            result.update(state="unavailable", reason="ambiguous_markup")
        else:
            result["counts"] = parser.element_counts
    return parse_formats(encode_formats(result))
