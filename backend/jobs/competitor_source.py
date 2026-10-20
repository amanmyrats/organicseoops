"""Current customer-selected public competitor scope; no collection or observation authority."""
from datetime import datetime
from hashlib import sha256
import json
from urllib.parse import urlsplit

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from integrations.oauth import _verified
from tenancy.models import DomainAlias, Project, normalize_origin
from tenancy.services import Action, require_project_action
from tenancy.support_requests import _safe_id
from .crawling import CrawlScope, FetchDenied


METHOD = "competitor-source-v1"
INTERPRETATION = "customer_selected_public_host_not_ownership_approval_time_network_commercial_or_observation_authority"


def _origin(value):
    if (type(value) is not str or not 1 <= len(value) <= 240 or "?" in value or "#" in value
        or "\\" in value or any(ord(char) < 33 for char in value) or normalize_origin(value) != value):
        raise ValidationError("Choose one canonical configured HTTP or HTTPS origin.")
    try:
        # Reuse the actual crawl port/scheme policy, without DNS or fetching.
        hostname = urlsplit(value).hostname
        if CrawlScope(frozenset({hostname})).validate_url(value) != value + "/": raise ValueError
    except (ValueError, FetchDenied):
        raise ValidationError("Choose a configured default-port public crawl origin.") from None
    return hostname


def _source(project_id, organization_id, actor, origin):
    project = Project.objects.select_related("organization", "configuration").filter(
        pk=project_id, organization_id=organization_id).first()
    if project is None: raise PermissionDenied
    membership = require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
    if not _verified(actor): raise PermissionDenied
    try:
        configuration = project.configuration
    except AttributeError:
        raise PermissionDenied from None
    configured = configuration.competitor_origins
    if (type(configured) is not list or not 1 <= len(configured) <= 50
        or any(type(value) is not str for value in configured) or len(set(configured)) != len(configured)
        or type(configuration.revision) is not int or configuration.revision < 1
        or configuration.source_choice not in configuration.SourceChoice.values
        or configuration.source_choice == configuration.SourceChoice.SYNTHETIC_DEMO):
        raise ValidationError("Current competitor configuration needs review.")
    for value in configured: _origin(value)
    if origin not in configured: raise PermissionDenied
    aliases = list(DomainAlias.objects.filter(project_id=project_id, organization_id=organization_id).order_by("pk").values(
        "id", "organization_id", "project_id", "origin"))
    own_hosts = {urlsplit(normalize_origin(value)).hostname for value in [project.canonical_origin, *[row["origin"] for row in aliases]]}
    scope = CrawlScope.for_project(project, competitor_origin=origin)
    if scope.kind != "competitor" or len(scope.hosts) != 1 or scope.hosts & own_hosts: raise PermissionDenied
    organization = project.organization
    dates = (organization.created_at, project.created_at, configuration.created_at, configuration.updated_at)
    if (any(not isinstance(value, datetime) or timezone.is_naive(value) or value > timezone.now() for value in dates)
        or list(dates) != sorted(dates) or type(project.access_restricted) is not bool):
        raise ValidationError("Current competitor configuration dates need review.")
    for value in (configuration.pk, membership.pk, project.pk, organization.pk, *[row["id"] for row in aliases]): _safe_id(value)
    return {"method_version": METHOD, "origin": origin, "hostname": next(iter(scope.hosts)),
        "organization": {"id": organization.pk, "is_suspended": organization.is_suspended, "closed_at": organization.closed_at,
            "created_at": organization.created_at},
        "project": {"id": project.pk, "organization_id": project.organization_id, "canonical_origin": project.canonical_origin,
            "access_restricted": project.access_restricted, "created_at": project.created_at},
        "configuration": {"id": configuration.pk, "project_id": configuration.project_id, "competitor_origins": configured,
            "source_choice": configuration.source_choice, "revision": configuration.revision,
            "created_at": configuration.created_at, "updated_at": configuration.updated_at},
        "aliases": aliases, "actor": {"id": actor.pk, "membership_id": membership.pk, "role": membership.role}}


def current_competitor_source(*, project, actor, data):
    if type(data) is not dict or set(data) != {"origin", "collection_permission"} or data["collection_permission"] is not True:
        raise ValidationError("Explicitly select one configured public competitor and confirm collection permission.")
    _origin(data["origin"])
    for value in (project.pk, project.organization_id, actor.pk): _safe_id(value)
    original = _source(project.pk, project.organization_id, actor, data["origin"])
    result = {"method_version": METHOD, "organization_id": project.organization_id, "project_id": project.pk,
        "actor_id": actor.pk, "origin": data["origin"], "hostname": original["hostname"],
        "scope_kind": "selected_competitor_hostname_default_http_https_only", "collection_permission": True,
        "configuration_revision": original["configuration"]["revision"],
        "configuration_updated_at": original["configuration"]["updated_at"].isoformat(),
        "source_sha256": sha256(json.dumps(original, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False).encode()).hexdigest(),
        "interpretation": INTERPRETATION}
    if _source(project.pk, project.organization_id, actor, data["origin"]) != original: raise PermissionDenied
    return result
