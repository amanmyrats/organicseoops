"""Strict original plaintext HTTP metadata; never authenticated identity or HTTPS upgrade proof."""
import json
import re

from django.core.exceptions import ValidationError

from integrations.google_tokens import _reject_constant, _unique_object
from tenancy.support_requests import _safe_id
from .crawling import FetchResponse, REDIRECT_STATUSES
from .passive_http_redirect_source import METHOD as SOURCE_METHOD, validate_input
from .passive_redirect_evidence import MAX_RESULT_BYTES, _date, _deny, _encode
from .passive_redirects import observe_http_response_location


METHOD = "passive-http-redirect-evidence-v1"
INTERPRETATION = "plaintext_http_location_metadata_not_authenticated_identity_observed_https_followed_upgrade_browser_behavior_or_target_authority"
TRANSPORT_FIXED = {"method_version": "passive-http-redirect-response-v1",
    "coverage": "one_original_first_http_response_only", "interpretation": INTERPRETATION}


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
    """Pure original HTTP metadata validation, never first-response source permission."""
    template = observe_http_response_location(source_url=source_url, status=status, fields=[])
    if (type(location) is not dict or set(location) != set(template)
        or any(location[key] != template[key] for key in ("method_version", "state", "coverage", "interpretation"))
        or type(location["response_status"]) is not int or location["response_status"] != status
        or type(location["redirect_status"]) is not bool or location["redirect_status"] != (status in REDIRECT_STATUSES)):
        _deny()
    if location["location_state"] == "single_classified":
        if (type(location["target_scheme"]) is not str or location["target_scheme"] not in {"http", "https"}
            or type(location["same_origin"]) is not bool or type(location["same_hostname_default_https"]) is not bool
            or location["target_scheme"] == "http" and location["same_hostname_default_https"]
            or location["target_scheme"] == "https" and location["same_origin"]):
            _deny()
    elif (type(location["location_state"]) is not str
        or location["location_state"] not in {"absent", "present_empty", "multiple_fields", "single_unclassified"}
        or any(location[key] is not None for key in ("target_scheme", "same_origin", "same_hostname_default_https"))):
        _deny()


def validate_http_redirect_evidence(result, *, binding):
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


def minimized_http_redirect_evidence(response, *, binding):
    if (type(response) is not FetchResponse or type(response.headers) is not dict or response.headers != {}
        or type(response.body) is not bytes or response.body != b"" or type(response.redirects) is not tuple or response.redirects != ()
        or response.header_observation is not None or response.resource_observation is not None or response.observed_at is not None
        or type(response.redirect_observation) is not dict):
        _deny()
    result = {"method": METHOD, "url": response.url, "status": response.status,
        "observed_at": response.redirect_observation.get("observed_at"), "evidence": response.redirect_observation,
        "interpretation": INTERPRETATION}
    return json.loads(encode_http_redirect_evidence(result, binding=binding))


def encode_http_redirect_evidence(result, *, binding):
    return _encode(validate_http_redirect_evidence(result, binding=binding))


def parse_http_redirect_evidence(content, *, binding):
    if type(content) is not bytes or not 1 <= len(content) <= MAX_RESULT_BYTES: _deny()
    try:
        result = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError): _deny()
    return validate_http_redirect_evidence(result, binding=binding)
