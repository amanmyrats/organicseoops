"""Literal article date declarations; no verified dates, age or collection authority."""
import json

from django.core.exceptions import ValidationError

from integrations.google_tokens import _reject_constant, _unique_object
from . import competitor_metadata as metadata


METHOD = "competitor-static-dates-v1"
COVERAGE = "one_complete_returned_static_document_two_exact_article_meta_properties_only"
INTERPRETATION = "literal_meta_declarations_not_validated_dates_page_identity_publication_change_age_freshness_publishing_cadence_or_whole_site"
PROPERTIES = frozenset({"article:published_time", "article:modified_time"})
MAX_DECLARATIONS = 10
MAX_VALUE = 80
REASONS = frozenset({"ambiguous_markup", "element_limit", "declaration_limit", "result_limit"})


class _Dates(metadata._Metadata):
    def __init__(self):
        super().__init__()
        self.declarations = []

    def handle_starttag(self, tag, attrs):
        selected = (not self.hidden and self.title is None and tag == "meta"
            and any(name == "property" and value in PROPERTIES for name, value in attrs))
        super().handle_starttag(tag, attrs)
        if selected:
            names = [name for name, _value in attrs]
            values = dict(attrs)
            if names.count("property") != 1 or names.count("content") != 1 or values["content"] is None:
                raise metadata._Unavailable("ambiguous_markup")
            if len(self.declarations) >= MAX_DECLARATIONS:
                raise metadata._Unavailable("declaration_limit")
            value = " ".join(values["content"].split())
            self.declarations.append({"property": values["property"], "value": value[:MAX_VALUE].rstrip(),
                "truncated": len(value) > MAX_VALUE})


def _deny():
    raise ValidationError("Original bounded article date declarations are unavailable.")


def validate_dates(result):
    if (type(result) is not dict or set(result) != {"method_version", "url", "observed_at", "body_sha256", "body_size_bytes",
        "state", "reason", "declarations", "coverage", "excluded_containers", "interpretation"}
        or result["method_version"] != METHOD or result["coverage"] != COVERAGE
        or result["interpretation"] != INTERPRETATION or result["excluded_containers"] != sorted(metadata.EXCLUDED)):
        _deny()
    metadata.validate_metadata({**{key: result[key] for key in ("url", "observed_at", "body_sha256", "body_size_bytes")},
        "method_version": metadata.METHOD, "state": "unavailable", "reason": "ambiguous_markup", "metadata": None,
        "counts": dict.fromkeys(metadata.COUNTS), "coverage": metadata.COVERAGE,
        "excluded_containers": sorted(metadata.EXCLUDED), "interpretation": metadata.INTERPRETATION})
    if result["state"] == "unavailable":
        if type(result["reason"]) is not str or result["reason"] not in REASONS or result["declarations"] is not None:
            _deny()
    elif result["state"] == "observed":
        if (result["reason"] != "" or type(result["declarations"]) is not list
            or len(result["declarations"]) > MAX_DECLARATIONS): _deny()
        for item in result["declarations"]:
            if (type(item) is not dict or set(item) != {"property", "value", "truncated"}
                or type(item["property"]) is not str or item["property"] not in PROPERTIES
                or type(item["truncated"]) is not bool or item["truncated"] and not item["value"]): _deny()
            metadata._text(item["value"], MAX_VALUE)
    else: _deny()
    return result


def encode_dates(result):
    validate_dates(result)
    try: content = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError): _deny()
    if len(content) > metadata.MAX_RESULT_BYTES: _deny()
    return content


def parse_dates(content):
    if type(content) is not bytes or not 1 <= len(content) <= metadata.MAX_RESULT_BYTES: _deny()
    try: result = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError): _deny()
    encode_dates(result)
    return result


def observe_static_dates(*, body, body_complete, url, observed_at):
    original = metadata.observe_static_metadata(body=body, body_complete=body_complete, url=url, observed_at=observed_at)
    result = {key: original[key] for key in ("url", "observed_at", "body_sha256", "body_size_bytes", "state", "reason", "excluded_containers")}
    result.update(method_version=METHOD, declarations=None, coverage=COVERAGE, interpretation=INTERPRETATION)
    if original["state"] == "observed":
        try:
            parser = _Dates()
            parser.feed(body.decode("utf-8-sig"))
            parser.close()
        except metadata._Unavailable as error:
            result.update(state="unavailable", reason=str(error))
        else:
            result["declarations"] = parser.declarations
            if len(json.dumps(result, separators=(",", ":"), ensure_ascii=False).encode("utf-8")) > metadata.MAX_RESULT_BYTES:
                result.update(state="unavailable", reason="result_limit", declarations=None)
    return parse_dates(encode_dates(result))
