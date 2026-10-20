"""Separate read-only certificate/TLS source; header permission grants no TLS authority."""
import hashlib
import json
from urllib.parse import urlsplit

from django.core.exceptions import PermissionDenied, ValidationError

from tenancy.models import normalize_origin
from tenancy.support_requests import _safe_id
from . import passive_header_source as verified_source


METHOD = "passive-tls-source-v1"
OBSERVATIONS = ("certificate_dates", "negotiated_tls")


def validate_input(data):
    if (type(data) is not dict or set(data) != {"origin", "observations", "collection_permission"}
        or data["collection_permission"] is not True or type(data["observations"]) is not list
        or data["observations"] != list(OBSERVATIONS) or type(data["origin"]) is not str
        or not 1 <= len(data["origin"]) <= 255):
        raise ValidationError("Choose one exact HTTPS origin and explicitly authorize certificate/TLS observation.")
    try:
        origin = normalize_origin(data["origin"])
        if origin != data["origin"] or not origin.startswith("https://") or urlsplit(origin).port is not None:
            raise ValueError
    except (ValidationError, ValueError):
        raise ValidationError("Choose a canonical exact HTTPS origin without path, credentials, query, fragment or explicit port.") from None
    return {"origin": origin, "observations": list(OBSERVATIONS), "collection_permission": True}


def passive_tls_source(*, project, actor, data):
    data = validate_input(data)
    for value in (project.pk, project.organization_id, actor.pk):
        _safe_id(value)
    original = verified_source._source(project.pk, project.organization_id, actor, data["origin"])
    digest = hashlib.sha256(json.dumps(original, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False).encode()).hexdigest()
    result = {"method_version": METHOD, "organization_id": project.organization_id, "project_id": project.pk,
        "actor_id": actor.pk, **data, "verification_id": original["verification"]["id"],
        "verified_at": original["verification"]["verified_at"].isoformat(), "source_digest": digest,
        "interpretation": "current_source_binding_not_network_job_commercial_reservation_or_observation_authority"}
    if verified_source._source(project.pk, project.organization_id, actor, data["origin"]) != original:
        raise PermissionDenied
    return result
