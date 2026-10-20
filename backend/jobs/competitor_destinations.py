"""Original same-origin static references; never destination or crawl authority."""
import json
from urllib.parse import urljoin, urlsplit

from django.core.exceptions import ValidationError

from integrations.google_tokens import _reject_constant, _unique_object
from . import competitor_links as links, competitor_metadata as metadata


METHOD = "competitor-static-destinations-v1"
COVERAGE = "one_complete_returned_static_document_non_inert_same_origin_href_occurrences_no_base_stdlib_join_in_original_order"
INTERPRETATION = "resolved_static_same_origin_references_not_unique_pages_fetched_destinations_link_health_crawl_authority_browser_visibility_topics_or_whole_site_structure"
COUNTS = links.COUNTS
MAX_DESTINATIONS = 10
REASONS = links.REASONS | {"destination_limit", "result_limit"}


class _Destinations(links._Links):
    def __init__(self, source_url):
        super().__init__(source_url)
        self.destinations = []

    def handle_starttag(self, tag, attrs):
        active = not self.hidden and self.title is None
        super().handle_starttag(tag, attrs)
        if active and tag == "a":
            value = dict(attrs).get("href")
            if links._category(value, self.source_url) == "same_origin_http":
                if len(self.destinations) >= MAX_DESTINATIONS: raise metadata._Unavailable("destination_limit")
                resolved = urljoin(self.source_url, value)
                self.destinations.append(resolved if urlsplit(resolved).path else resolved + "/")


def _deny():
    raise ValidationError("Original bounded same-origin static competitor references are unavailable.")


def validate_destinations(result):
    if (type(result) is not dict or set(result) != {"method_version", "url", "observed_at", "body_sha256", "body_size_bytes",
        "state", "reason", "destinations", "counts", "coverage", "excluded_containers", "interpretation"}
        or result["method_version"] != METHOD or result["coverage"] != COVERAGE or result["interpretation"] != INTERPRETATION): _deny()
    if result["state"] == "unavailable":
        if type(result["reason"]) is not str or result["reason"] not in REASONS or result["destinations"] is not None: _deny()
    elif result["state"] == "observed":
        if type(result["destinations"]) is not list or len(result["destinations"]) > MAX_DESTINATIONS: _deny()
    else: _deny()
    # Reuse the closed original byte/date/category proof; extended unavailable reasons
    # supply no positive observation to the original parser's contract.
    links.validate_links({key: value for key, value in result.items() if key != "destinations"} | {
        "method_version": links.METHOD, "coverage": links.COVERAGE, "interpretation": links.INTERPRETATION,
        "reason": "ambiguous_markup" if result["state"] == "unavailable" else result["reason"]})
    if result["state"] == "observed":
        if len(result["destinations"]) != result["counts"]["same_origin_http"]: _deny()
        for url in result["destinations"]:
            metadata.validate_url(url)
            if links._category(url, result["url"]) != "same_origin_http": _deny()
    return result


def encode_destinations(result):
    validate_destinations(result)
    try: content = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError): _deny()
    if len(content) > metadata.MAX_RESULT_BYTES: _deny()
    return content


def parse_destinations(content):
    if type(content) is not bytes or not 1 <= len(content) <= metadata.MAX_RESULT_BYTES: _deny()
    try: result = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError): _deny()
    encode_destinations(result)
    return result


def observe_static_destinations(*, body, body_complete, url, observed_at):
    original = links.observe_static_links(body=body, body_complete=body_complete, url=url, observed_at=observed_at)
    result = original | {"method_version": METHOD, "coverage": COVERAGE, "interpretation": INTERPRETATION, "destinations": None}
    if original["state"] == "observed":
        try:
            parser = _Destinations(url)
            parser.feed(body.decode("utf-8-sig"))
            if parser.anchor_open: raise metadata._Unavailable("ambiguous_markup")
            parser.close()
        except metadata._Unavailable as error:
            result.update(state="unavailable", reason=str(error), counts=dict.fromkeys(COUNTS))
        else:
            result["destinations"] = parser.destinations
            if len(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")) > metadata.MAX_RESULT_BYTES:
                result.update(state="unavailable", reason="result_limit", destinations=None, counts=dict.fromkeys(COUNTS))
    return parse_destinations(encode_destinations(result))
