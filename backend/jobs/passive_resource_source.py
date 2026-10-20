"""Independent read binding; no body request, retained raw HTML or commercial authority."""
import hashlib
import json

from django.core.exceptions import PermissionDenied, ValidationError

from tenancy.support_requests import _safe_id
from . import passive_header_source as verified_source


METHOD = "passive-resource-source-v1"
OBSERVATIONS = ("static_resource_references",)


def validate_input(data):
    if (type(data) is not dict or set(data) != {"url", "observations", "collection_permission"}
        or data["collection_permission"] is not True or type(data["observations"]) is not list
        or data["observations"] != list(OBSERVATIONS)):
        raise ValidationError("Explicitly authorize only selected static resource references at one exact HTTPS URL.")
    # Reuse pure URL syntax validation, not header permission or capture authority.
    original, origin = verified_source.validate_input({**data, "observations": ["response_headers"]})
    return {**original, "observations": list(OBSERVATIONS)}, origin


def passive_resource_source(*, project, actor, data):
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
