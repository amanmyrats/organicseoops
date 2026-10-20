"""Strict original minimized evidence; no current source, request or storage authority."""
import json
import re

from django.core.exceptions import ValidationError

from integrations.google_tokens import _reject_constant, _unique_object
from tenancy.support_requests import _safe_id
from .crawling import FetchResponse
from .passive_resource_source import METHOD as SOURCE_METHOD, validate_input
from .passive_resources import COUNTS, MAX_REFERENCES, observe_static_resource_references
from .passive_tls_evidence import _date as _original_date


METHOD = "passive-resource-evidence-v1"
MAX_RESULT_BYTES = 8192
INTERPRETATION = "one_complete_response_literal_candidates_not_browser_requests_or_whole_page_mixed_content_security"
TRANSPORT_FIXED = {"method_version": "passive-resource-response-v1",
    "coverage": "one_complete_length_framed_utf8_html_response_only",
    "interpretation": "literal_candidates_not_browser_requests_or_whole_page_mixed_content_security"}


def _deny():
    raise ValidationError("Original minimized static resource evidence is unavailable.")


def _date(value, *, microseconds=True):
    # Reuse the checked passive UTC/nonfuture/canonical-date predicate, not TLS permission.
    try: return _original_date(value, microseconds=microseconds)
    except ValidationError: _deny()


def _binding(binding):
    if (type(binding) is not dict or set(binding) != {"method_version", "organization_id", "project_id", "actor_id",
        "origin", "url", "observations", "collection_permission", "verification_id", "verified_at", "source_digest", "interpretation"}
        or binding["method_version"] != SOURCE_METHOD
        or binding["interpretation"] != "current_source_binding_not_network_job_commercial_reservation_or_observation_authority"
        or type(binding["source_digest"]) is not str or not re.fullmatch(r"[a-f0-9]{64}", binding["source_digest"])):
        _deny()
    _data, origin = validate_input({key: binding[key] for key in ("url", "observations", "collection_permission")})
    if binding["origin"] != origin: _deny()
    for key in ("organization_id", "project_id", "actor_id", "verification_id"): _safe_id(binding[key])
    return _date(binding["verified_at"], microseconds=False)


def _observation(observation, binding):
    verified = _binding(binding)
    if (type(observation) is not dict or set(observation) != set(TRANSPORT_FIXED) | {"observed_at", "resource_references"}
        or any(observation[key] != value for key, value in TRANSPORT_FIXED.items())):
        _deny()
    if _date(observation["observed_at"]) < verified: _deny()
    resources = observation["resource_references"]
    template = observe_static_resource_references(b"", body_complete=True)
    if (type(resources) is not dict or set(resources) != set(template)
        or any(resources[key] != template[key] for key in ("method_version", "coverage", "selected_attributes", "excluded", "interpretation"))
        or type(resources["counts"]) is not dict or set(resources["counts"]) != set(COUNTS)):
        _deny()
    counts = resources["counts"]
    if resources["state"] == "observed":
        if (resources["reason"] != "" or any(type(value) is not int or not 0 <= value <= MAX_REFERENCES for value in counts.values())
            or counts["inspected_attributes"] != sum(counts[key] for key in ("http_absolute", "https_absolute", "unclassified"))):
            _deny()
    elif resources["state"] == "unavailable":
        if (type(resources["reason"]) is not str or resources["reason"] not in {"invalid_body", "ambiguous_markup", "reference_limit"}
            or any(value is not None for value in counts.values())):
            _deny()
    else: _deny()


def _encode(result):
    try: content = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError): _deny()
    if len(content) > MAX_RESULT_BYTES: _deny()
    return content


def validate_resource_evidence(result, *, binding):
    if (type(binding) is not dict or type(result) is not dict
        or set(result) != {"method", "url", "status", "observed_at", "evidence", "interpretation"}
        or result["method"] != METHOD or result["url"] != binding.get("url")
        or type(result["status"]) is not int or result["status"] != 200
        or result["interpretation"] != INTERPRETATION or type(result["evidence"]) is not dict
        or result["observed_at"] != result["evidence"].get("observed_at")):
        _deny()
    _observation(result["evidence"], binding)
    _encode(result)
    return result


def minimized_resource_evidence(response, *, binding):
    if (type(response) is not FetchResponse or type(response.headers) is not dict or response.headers != {}
        or type(response.body) is not bytes or response.body != b"" or type(response.redirects) is not tuple or response.redirects != ()
        or response.header_observation is not None or response.redirect_observation is not None or type(response.resource_observation) is not dict):
        _deny()
    result = {"method": METHOD, "url": response.url, "status": response.status,
        "observed_at": response.resource_observation.get("observed_at"), "evidence": response.resource_observation,
        "interpretation": INTERPRETATION}
    return json.loads(encode_resource_evidence(result, binding=binding))


def encode_resource_evidence(result, *, binding):
    return _encode(validate_resource_evidence(result, binding=binding))


def parse_resource_evidence(content, *, binding):
    if type(content) is not bytes or not 1 <= len(content) <= MAX_RESULT_BYTES: _deny()
    try:
        result = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError): _deny()
    return validate_resource_evidence(result, binding=binding)
