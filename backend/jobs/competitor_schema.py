"""Original lexical JSON-LD labels only; no context resolution or collection authority."""
import json
import math

from django.core.exceptions import ValidationError

from integrations.google_tokens import _reject_constant, _unique_object
from . import competitor_metadata as metadata


METHOD = "competitor-static-schema-types-v1"
COVERAGE = "one_complete_returned_static_document_non_inert_json_ld_fixed_type_labels_only"
INTERPRETATION = "lexical_declarations_not_resolved_schema_validity_actual_page_type_rich_results_visible_consistency_or_whole_site"
TYPES = frozenset({"Article", "NewsArticle", "BlogPosting", "WebPage", "AboutPage", "ContactPage", "CollectionPage",
    "FAQPage", "QAPage", "Product", "Service", "Organization", "LocalBusiness", "BreadcrumbList", "ItemList",
    "VideoObject", "ImageObject", "HowTo", "Event", "Recipe", "Person"})
REASONS = frozenset({"ambiguous_markup", "element_limit", "block_limit", "size_limit", "invalid_json", "shape_limit", "type_shape"})
MAX_BLOCKS = 20
MAX_BLOCK_BYTES = 16384
MAX_TYPED_NODES = 500


class _Schema(metadata._Metadata):
    def __init__(self):
        super().__init__()
        self.parts = None
        self.blocks = 0
        self.typed_nodes = 0
        self.types = set()
        self.unrecognized = 0

    def handle_starttag(self, tag, attrs):
        selected = (not self.hidden and tag == "script"
            and (dict(attrs).get("type") or "").split(";", 1)[0].strip().lower() == "application/ld+json")
        super().handle_starttag(tag, attrs)
        if selected:
            if any(name == "src" for name, _value in attrs): raise metadata._Unavailable("ambiguous_markup")
            self.blocks += 1
            if self.blocks > MAX_BLOCKS: raise metadata._Unavailable("block_limit")
            self.parts = []

    def handle_data(self, value):
        if self.parts is not None: self.parts.append(value)
        else: super().handle_data(value)

    def handle_endtag(self, tag):
        if tag == "script" and self.parts is not None:
            raw = "".join(self.parts)
            self.parts = None
            if len(raw.encode("utf-8")) > MAX_BLOCK_BYTES: raise metadata._Unavailable("size_limit")
            try: value = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            except (ValueError, RecursionError): raise metadata._Unavailable("invalid_json") from None
            if type(value) not in {dict, list}: raise metadata._Unavailable("shape_limit")
            self.inspect(value)
        super().handle_endtag(tag)

    def inspect(self, value):
        pending = [(value, 0)]
        nodes = 0
        while pending:
            item, depth = pending.pop()
            nodes += 1
            if depth > 20 or nodes > 1000 or type(item) is float and not math.isfinite(item):
                raise metadata._Unavailable("shape_limit")
            if type(item) is dict:
                pending.extend((nested, depth + 1) for nested in item.values())
                if "@type" in item:
                    self.typed_nodes += 1
                    if self.typed_nodes > MAX_TYPED_NODES: raise metadata._Unavailable("shape_limit")
                    values = [item["@type"]] if type(item["@type"]) is str else item["@type"]
                    if (type(values) is not list or not 1 <= len(values) <= 20
                        or any(type(label) is not str or not 1 <= len(label) <= 512
                            or any(ord(char) < 33 or ord(char) == 127 for char in label) for label in values)):
                        raise metadata._Unavailable("type_shape")
                    for label in values:
                        # No @context expansion. Only these exact lexical forms are retained.
                        for prefix in ("https://schema.org/", "http://schema.org/"):
                            if label.startswith(prefix):
                                label = label[len(prefix):]
                                break
                        if label in TYPES: self.types.add(label)
                        else: self.unrecognized += 1
            elif type(item) is list:
                pending.extend((nested, depth + 1) for nested in item)


def _deny():
    raise ValidationError("Original bounded static competitor schema labels are unavailable.")


def validate_schema(result):
    if (type(result) is not dict or set(result) != {"method_version", "url", "observed_at", "body_sha256", "body_size_bytes",
        "state", "reason", "summary", "coverage", "excluded_containers", "interpretation"}
        or result["method_version"] != METHOD or result["coverage"] != COVERAGE
        or result["interpretation"] != INTERPRETATION or result["excluded_containers"] != sorted(metadata.EXCLUDED)):
        _deny()
    # Reuse the exact original URL/date/digest/size contract, without extending v1's shape.
    metadata.validate_metadata({**{key: result[key] for key in ("url", "observed_at", "body_sha256", "body_size_bytes")},
        "method_version": metadata.METHOD, "state": "unavailable", "reason": "ambiguous_markup", "metadata": None,
        "counts": dict.fromkeys(metadata.COUNTS), "coverage": metadata.COVERAGE,
        "excluded_containers": sorted(metadata.EXCLUDED), "interpretation": metadata.INTERPRETATION})
    summary = result["summary"]
    if result["state"] == "unavailable":
        if type(result["reason"]) is not str or result["reason"] not in REASONS or summary is not None: _deny()
    elif result["state"] == "observed":
        if (result["reason"] != "" or type(summary) is not dict
            or set(summary) != {"json_ld_blocks", "typed_nodes", "types", "unrecognized_type_count"}
            or any(type(summary[key]) is not int or not 0 <= summary[key] <= limit for key, limit in (
                ("json_ld_blocks", MAX_BLOCKS), ("typed_nodes", MAX_TYPED_NODES), ("unrecognized_type_count", MAX_TYPED_NODES * 20)))
            or type(summary["types"]) is not list or len(summary["types"]) > len(TYPES)
            or any(type(label) is not str or label not in TYPES for label in summary["types"])
            or summary["types"] != sorted(set(summary["types"]))
            or summary["unrecognized_type_count"] + len(summary["types"]) > summary["typed_nodes"] * 20
            or not summary["json_ld_blocks"] and summary["typed_nodes"]): _deny()
    else: _deny()
    return result


def encode_schema(result):
    validate_schema(result)
    try: content = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError): _deny()
    if len(content) > metadata.MAX_RESULT_BYTES: _deny()
    return content


def parse_schema(content):
    if type(content) is not bytes or not 1 <= len(content) <= metadata.MAX_RESULT_BYTES: _deny()
    try: result = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError): _deny()
    encode_schema(result)
    return result


def observe_static_schema(*, body, body_complete, url, observed_at):
    original = metadata.observe_static_metadata(body=body, body_complete=body_complete, url=url, observed_at=observed_at)
    result = {key: original[key] for key in ("url", "observed_at", "body_sha256", "body_size_bytes", "state", "reason", "excluded_containers")}
    result.update(method_version=METHOD, summary=None, coverage=COVERAGE, interpretation=INTERPRETATION)
    if original["state"] == "observed":
        try:
            parser = _Schema()
            parser.feed(body.decode("utf-8-sig"))
            parser.close()
        except metadata._Unavailable as error:
            result.update(state="unavailable", reason=str(error))
        else:
            result["summary"] = {"json_ld_blocks": parser.blocks, "typed_nodes": parser.typed_nodes,
                "types": sorted(parser.types), "unrecognized_type_count": parser.unrecognized}
    return parse_schema(encode_schema(result))
