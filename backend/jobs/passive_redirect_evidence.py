"""Strict original minimized Location evidence; no current source or capture authority."""
import json
import re

from django.core.exceptions import ValidationError

from integrations.google_tokens import _reject_constant, _unique_object
from tenancy.support_requests import _safe_id
from .crawling import FetchResponse, REDIRECT_STATUSES
from .passive_redirect_source import METHOD as SOURCE_METHOD, validate_input
from .passive_redirects import observe_response_location
from .passive_tls_evidence import _date as _original_date


METHOD = "passive-redirect-evidence-v1"
MAX_RESULT_BYTES = 8192
INTERPRETATION = "one_response_location_metadata_not_followed_chain_https_upgrade_browser_behavior_or_target_authority"
TRANSPORT_FIXED = {"method_version": "passive-redirect-response-v1",
    "coverage": "one_original_first_https_response_only",
    "interpretation": "location_metadata_not_followed_chain_https_upgrade_browser_behavior_or_target_authority"}


def _deny():
    raise ValidationError("Original minimized Location evidence is unavailable.")


def _date(value, *, microseconds=True):
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


def _observation(observation, binding, status):
    verified = _binding(binding)
    if (type(observation) is not dict or set(observation) != set(TRANSPORT_FIXED) | {"observed_at", "response_location"}
        or any(observation[key] != value for key, value in TRANSPORT_FIXED.items())):
        _deny()
    if _date(observation["observed_at"]) < verified: _deny()
    _location(observation["response_location"], source_url=binding["url"], status=status)


def _location(location, *, source_url, status):
    """Pure original metadata validation, independent of source/capture permission."""
    template = observe_response_location(source_url=source_url, status=status, fields=[])
    if (type(location) is not dict or set(location) != set(template)
        or any(location[key] != template[key] for key in ("method_version", "state", "coverage", "interpretation"))
        or type(location["response_status"]) is not int or location["response_status"] != status
        or type(location["redirect_status"]) is not bool or location["redirect_status"] != (status in REDIRECT_STATUSES)):
        _deny()
    if location["location_state"] == "single_classified":
        if (type(location["target_scheme"]) is not str or location["target_scheme"] not in {"http", "https"}
            or type(location["same_origin"]) is not bool or location["target_scheme"] == "http" and location["same_origin"]):
            _deny()
    elif (type(location["location_state"]) is not str
        or location["location_state"] not in {"absent", "present_empty", "multiple_fields", "single_unclassified"}
        or location["target_scheme"] is not None or location["same_origin"] is not None):
        _deny()


def _encode(result):
    try: content = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError): _deny()
    if len(content) > MAX_RESULT_BYTES: _deny()
    return content


def validate_redirect_evidence(result, *, binding):
    if (type(binding) is not dict or type(result) is not dict
        or set(result) != {"method", "url", "status", "observed_at", "evidence", "interpretation"}
        or result["method"] != METHOD or result["url"] != binding.get("url")
        or type(result["status"]) is not int or not 200 <= result["status"] <= 599
        or result["interpretation"] != INTERPRETATION or type(result["evidence"]) is not dict
        or result["observed_at"] != result["evidence"].get("observed_at")):
        _deny()
    _observation(result["evidence"], binding, result["status"])
    _encode(result)
    return result


def minimized_redirect_evidence(response, *, binding):
    if (type(response) is not FetchResponse or type(response.headers) is not dict or response.headers != {}
        or type(response.body) is not bytes or response.body != b"" or type(response.redirects) is not tuple or response.redirects != ()
        or response.header_observation is not None or response.resource_observation is not None or type(response.redirect_observation) is not dict):
        _deny()
    result = {"method": METHOD, "url": response.url, "status": response.status,
        "observed_at": response.redirect_observation.get("observed_at"), "evidence": response.redirect_observation,
        "interpretation": INTERPRETATION}
    return json.loads(encode_redirect_evidence(result, binding=binding))


def encode_redirect_evidence(result, *, binding):
    return _encode(validate_redirect_evidence(result, binding=binding))


def parse_redirect_evidence(content, *, binding):
    if type(content) is not bytes or not 1 <= len(content) <= MAX_RESULT_BYTES: _deny()
    try:
        result = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError): _deny()
    return validate_redirect_evidence(result, binding=binding)
