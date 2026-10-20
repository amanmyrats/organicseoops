"""Frozen current lab source and credential reference; no credential resolution or request."""
from hashlib import sha256
import json

from django.core.exceptions import PermissionDenied, ValidationError

from providers.performance_key import performance_key_reference
from .competitor_lab_source import current_competitor_lab_source, validate_input
from .passive_tls_evidence import _date


METHOD = "competitor-lighthouse-selection-v1"
INTERPRETATION = "current_source_and_credential_configuration_reference_not_key_validity_provider_access_quota_network_commercial_or_observed_lab_authority"
MAX_RESULT_BYTES = 8192


def _validate_reference(value):
    if (type(value) is not dict or set(value) != {"source", "revision", "state"}
        or type(value["source"]) is not str or value["source"] not in {"organization", "platform", "environment"}):
        raise ValidationError("Current performance credential reference is unavailable.")
    if value["source"] == "environment":
        if value["revision"] != "" or value["state"] != "unverified":
            raise ValidationError("Current performance credential reference is unavailable.")
    else:
        _date(value["revision"], microseconds=False)
        if value["state"] != "active": raise ValidationError("Current performance credential is unavailable.")
    return dict(value)


def _reference(organization):
    return _validate_reference(performance_key_reference(organization=organization))


def selection_snapshot(*, project, actor, data):
    data = validate_input(data)
    source = current_competitor_lab_source(project=project, actor=actor, data=data)
    credential = _reference(project.organization)
    result = {"method_version": METHOD, "source": source, "performance_credential": credential,
        "interpretation": INTERPRETATION}
    try:
        content = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ValidationError("Current Lighthouse selection is unavailable.") from None
    if len(content) > MAX_RESULT_BYTES: raise ValidationError("Current Lighthouse selection exceeds its bounded limit.")
    result["selection_sha256"] = sha256(content).hexdigest()
    if _reference(project.organization) != credential: raise PermissionDenied
    if current_competitor_lab_source(project=project, actor=actor, data=data) != source: raise PermissionDenied
    return result
