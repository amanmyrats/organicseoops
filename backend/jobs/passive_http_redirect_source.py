"""Read-only independently verified HTTP source; HTTPS grants never authorize its counterpart."""
import hashlib
import json

from django.core.exceptions import PermissionDenied, ValidationError

from tenancy.support_requests import _safe_id
from . import passive_header_source as verified_source
from .passive_redirects import validate_http_source_url


METHOD = "passive-http-redirect-source-v1"
OBSERVATIONS = ("http_response_location",)


def validate_input(data):
    if (type(data) is not dict or set(data) != {"url", "observations", "collection_permission"}
        or data["collection_permission"] is not True or type(data["observations"]) is not list
        or data["observations"] != list(OBSERVATIONS)):
        raise ValidationError("Independently authorize only first-response HTTP Location metadata at one exact HTTP URL.")
    parts = validate_http_source_url(data["url"])
    return {"url": data["url"], "observations": list(OBSERVATIONS), "collection_permission": True}, parts.scheme + "://" + parts.netloc


def passive_http_redirect_source(*, project, actor, data):
    data, origin = validate_input(data)
    for value in (project.pk, project.organization_id, actor.pk): _safe_id(value)
    original = verified_source._source(project.pk, project.organization_id, actor, origin)
    digest = hashlib.sha256(json.dumps(original, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False).encode()).hexdigest()
    result = {"method_version": METHOD, "organization_id": project.organization_id, "project_id": project.pk,
        "actor_id": actor.pk, "origin": origin, **data, "verification_id": original["verification"]["id"],
        "verified_at": original["verification"]["verified_at"].isoformat(), "source_digest": digest,
        "interpretation": "current_source_binding_not_network_job_commercial_reservation_or_observation_authority"}
    if verified_source._source(project.pk, project.organization_id, actor, origin) != original:
        raise PermissionDenied
    return result
