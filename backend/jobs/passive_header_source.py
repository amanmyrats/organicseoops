"""Read-only exact current source selection; no job, commercial reservation or network request."""
import hashlib
import json
import re
from datetime import datetime
from urllib.parse import urlsplit

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from tenancy.models import DomainAlias, Organization, Project, ProjectOriginVerification, normalize_origin
from tenancy.services import require_passive_security_scope
from tenancy.support_requests import _safe_id
from .crawling import CrawlScope, FetchDenied
from .local_feedback import validate_owned_website_url


METHOD = "passive-header-source-v1"
VERIFICATION_FIELDS = ("id", "organization_id", "project_id", "origin", "method", "challenge_digest",
    "state", "verified_at", "revoked_at", "created_at", "updated_at")


def validate_input(data):
    if (type(data) is not dict or set(data) != {"url", "observations", "collection_permission"}
        or data["collection_permission"] is not True or type(data["observations"]) is not list
        or data["observations"] != ["response_headers"] or type(data["url"]) is not str
        or not 1 <= len(data["url"]) <= 1024 or "?" in data["url"] or "#" in data["url"]):
        raise ValidationError("Choose one exact HTTPS URL and explicitly authorize response-header observation.")
    try:
        parts = urlsplit(data["url"])
        origin = normalize_origin(parts.scheme + "://" + parts.netloc)
        validate_owned_website_url(data["url"], approved_origin=origin)
        if CrawlScope(frozenset({parts.hostname})).validate_url(data["url"]) != data["url"]: raise ValueError
    except (ValueError, ValidationError, FetchDenied):
        raise ValidationError("Choose a canonical exact HTTPS source without credentials, query, fragment or custom port.") from None
    return {"url": data["url"], "observations": ["response_headers"], "collection_permission": True}, origin


def _source(project_id, organization_id, actor, origin):
    project = Project.objects.select_related("organization").filter(pk=project_id, organization_id=organization_id).first()
    if project is None: raise PermissionDenied
    verification = require_passive_security_scope(project=project, user=actor, origin=origin)
    original = ProjectOriginVerification.objects.filter(pk=verification.pk, organization_id=organization_id,
        project_id=project_id).values(*VERIFICATION_FIELDS).first()
    scope = Project.objects.filter(pk=project_id, organization_id=organization_id).values(
        "id", "organization_id", "canonical_origin", "access_restricted", "created_at").first()
    org = Organization.objects.filter(pk=organization_id).order_by("pk").values("id", "is_suspended", "closed_at", "created_at").first()
    alias = DomainAlias.objects.filter(project_id=project_id, organization_id=organization_id, origin=origin).values(
        "id", "organization_id", "project_id", "origin").first() if project.canonical_origin != origin else None
    if original is None or scope is None or org is None or scope["canonical_origin"] != origin and alias is None:
        raise PermissionDenied
    for value in (original["id"], original["organization_id"], original["project_id"], scope["id"], org["id"]): _safe_id(value)
    dates = (org["created_at"], scope["created_at"], original["created_at"], original["verified_at"], original["updated_at"])
    if (original["origin"] != origin or original["method"] != "http_file" or original["state"] != "verified"
        or original["revoked_at"] is not None or org["is_suspended"] is not False or org["closed_at"] is not None
        or type(original["challenge_digest"]) is not str or not re.fullmatch(r"[a-f0-9]{64}", original["challenge_digest"])
        or any(not isinstance(value, datetime) or timezone.is_naive(value) or value > timezone.now() for value in dates)
        or tuple(sorted(dates)) != dates):
        raise ValidationError("Original verified passive source needs review.")
    return {"verification": original, "project": scope, "alias": alias, "organization": org}


def passive_header_source(*, project, actor, data):
    data, origin = validate_input(data)
    for value in (project.pk, project.organization_id, actor.pk): _safe_id(value)
    original = _source(project.pk, project.organization_id, actor, origin)
    digest = hashlib.sha256(json.dumps(original, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False).encode()).hexdigest()
    result = {"method_version": METHOD, "organization_id": project.organization_id, "project_id": project.pk,
        "actor_id": actor.pk, "origin": origin, **data, "verification_id": original["verification"]["id"],
        "verified_at": original["verification"]["verified_at"].isoformat(), "source_digest": digest,
        "interpretation": "current_source_binding_not_network_job_commercial_reservation_or_observation_authority"}
    if _source(project.pk, project.organization_id, actor, origin) != original:
        raise PermissionDenied
    return result
