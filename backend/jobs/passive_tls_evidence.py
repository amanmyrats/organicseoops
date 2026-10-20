"""Strict minimized original evidence, not current source or capture authority."""
import json
import re
from datetime import UTC, datetime, timedelta

from django.core.exceptions import ValidationError

from integrations.google_tokens import _reject_constant, _unique_object
from tenancy.support_requests import _safe_id
from .passive_certificate import observe_peer_certificate_dates
from .passive_tls_source import METHOD as SOURCE_METHOD, validate_input


METHOD = "passive-tls-evidence-v1"
MAX_RESULT_BYTES = 8192
INTERPRETATION = "one_validated_handshake_not_all_supported_tls_configuration_revocation_or_exploitability"
TRANSPORT_FIELDS = {"method_version", "origin", "observed_at", "certificate_dates", "negotiated_tls", "coverage", "interpretation"}
TRANSPORT_FIXED = {"method_version": "passive-tls-handshake-v1",
    "coverage": "one_default_context_hostname_chain_validated_handshake_only",
    "interpretation": "negotiated_parameters_not_all_supported_configuration_revocation_or_exploitability"}


def _deny():
    raise ValidationError("Original minimized certificate/TLS evidence is unavailable.")


def _date(value, *, future=False, microseconds=True):
    try:
        if type(value) is not str or len(value) > 40: raise ValueError
        stamp = datetime.fromisoformat(value)
        canonical = stamp.isoformat(timespec="microseconds") if microseconds else stamp.isoformat()
        if stamp.utcoffset() != timedelta(0) or canonical != value or not future and stamp > datetime.now(UTC):
            raise ValueError
    except (ValueError, OverflowError):
        _deny()
    return stamp


def _binding(binding):
    if (type(binding) is not dict or set(binding) != {"method_version", "organization_id", "project_id", "actor_id",
        "origin", "observations", "collection_permission", "verification_id", "verified_at", "source_digest", "interpretation"}
        or binding["method_version"] != SOURCE_METHOD
        or binding["interpretation"] != "current_source_binding_not_network_job_commercial_reservation_or_observation_authority"
        or type(binding["source_digest"]) is not str or not re.fullmatch(r"[a-f0-9]{64}", binding["source_digest"])):
        _deny()
    validate_input({key: binding[key] for key in ("origin", "observations", "collection_permission")})
    for key in ("organization_id", "project_id", "actor_id", "verification_id"): _safe_id(binding[key])
    return _date(binding["verified_at"], microseconds=False)


def _transport(observation, binding):
    verified = _binding(binding)
    if (type(observation) is not dict or set(observation) != TRANSPORT_FIELDS
        or any(observation[key] != value for key, value in TRANSPORT_FIXED.items())
        or observation["origin"] != binding["origin"]):
        _deny()
    observed = _date(observation["observed_at"])
    if observed < verified: _deny()
    dates = observation["certificate_dates"]
    template = observe_peer_certificate_dates(None, observed_at=observed)
    if (type(dates) is not dict or set(dates) != set(template)
        or any(dates[key] != template[key] for key in ("method_version", "coverage", "interpretation", "observed_at"))):
        _deny()
    if dates["state"] == "unavailable":
        if any(dates[key] is not None for key in ("not_before", "not_after", "position", "remaining_microseconds")): _deny()
    elif dates["state"] == "observed":
        start, end = (_date(dates[key], future=True) for key in ("not_before", "not_after"))
        if start.microsecond or end.microsecond or start > end: _deny()
        position = "before_reported_window" if observed < start else "after_reported_window" if observed > end else "within_reported_window"
        if (dates["position"] != position or type(dates["remaining_microseconds"]) is not str
            or dates["remaining_microseconds"] != str((end - observed) // timedelta(microseconds=1))): _deny()
    else: _deny()
    negotiated = observation["negotiated_tls"]
    if (type(negotiated) is not dict or set(negotiated) != {"version", "cipher"}
        or negotiated["version"] is not None and (type(negotiated["version"]) is not str
            or negotiated["version"] not in {"TLSv1", "TLSv1.1", "TLSv1.2", "TLSv1.3"})):
        _deny()
    cipher = negotiated["cipher"]
    if cipher is not None and (type(cipher) is not dict or set(cipher) != {"name", "secret_bits"}
        or type(cipher["name"]) is not str or not 1 <= len(cipher["name"]) <= 128
        or not re.fullmatch(r"[A-Za-z0-9_-]+", cipher["name"])
        or type(cipher["secret_bits"]) is not int or not 1 <= cipher["secret_bits"] <= 512):
        _deny()


def _encode(result):
    try: content = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError): _deny()
    if len(content) > MAX_RESULT_BYTES: _deny()
    return content


def validate_tls_evidence(result, *, binding):
    if (type(binding) is not dict or type(result) is not dict or set(result) != {"method", "origin", "observed_at", "evidence", "interpretation"}
        or result["method"] != METHOD or result["origin"] != binding.get("origin")
        or result["interpretation"] != INTERPRETATION or type(result["evidence"]) is not dict
        or result["observed_at"] != result["evidence"].get("observed_at")):
        _deny()
    _transport(result["evidence"], binding)
    _encode(result)
    return result


def minimized_tls_evidence(observation, *, binding):
    _transport(observation, binding)
    result = {"method": METHOD, "origin": observation["origin"], "observed_at": observation["observed_at"],
              "evidence": observation, "interpretation": INTERPRETATION}
    # Fresh JSON objects prevent a caller's later transport-dict mutation from altering retained evidence.
    return json.loads(_encode(result))


def encode_tls_evidence(result, *, binding):
    return _encode(validate_tls_evidence(result, binding=binding))


def parse_tls_evidence(content, *, binding):
    if type(content) is not bytes or not 1 <= len(content) <= MAX_RESULT_BYTES: _deny()
    try:
        result = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError): _deny()
    return validate_tls_evidence(result, binding=binding)
