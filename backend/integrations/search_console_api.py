import json

from django.core.exceptions import ValidationError

from tenancy.models import Project, ProjectOriginVerification
from tenancy.services import Action, require_project_action

from .models import _domain_site, normalize_external_property, verified_domain_origins


_PERMISSIONS = {"siteOwner": 3, "siteFullUser": 2, "siteRestrictedUser": 1}
def exact_scope_search_console_sites(*, project, user, response):
    project = Project.objects.get(pk=project.pk, organization_id=project.organization_id)
    require_project_action(project=project, user=user, action=Action.MANAGE_PROJECT)
    if type(response) is not dict:
        raise ValidationError("Search Console sites response is invalid.")
    try:
        encoded = json.dumps(response, allow_nan=False, separators=(",", ":")).encode()
    except (TypeError, ValueError, RecursionError):
        raise ValidationError("Search Console sites response is invalid.") from None
    entries = response.get("siteEntry", [])
    if len(encoded) > 256 * 1024 or type(entries) is not list or len(entries) > 500:
        raise ValidationError("Search Console sites response exceeds its safe bound.")
    origins = {project.canonical_origin, *project.domain_aliases.values_list("origin", flat=True)}
    verified_origins = set(ProjectOriginVerification.objects.filter(
        project=project, organization_id=project.organization_id, origin__in=origins,
        state=ProjectOriginVerification.State.VERIFIED, verified_at__isnull=False, revoked_at__isnull=True,
    ).values_list("origin", flat=True))
    selected = {}
    skipped = {"domain_wide": 0, "path_prefix_or_invalid": 0, "foreign_scope": 0,
               "unverified_or_unknown_permission": 0, "duplicate_property": 0}
    for entry in entries:
        if type(entry) is not dict or not isinstance(entry.get("siteUrl"), str) or not isinstance(entry.get("permissionLevel"), str):
            raise ValidationError("Search Console sites response contains an invalid entry.")
        site_url = entry["siteUrl"]
        permission = entry["permissionLevel"]
        if len(site_url) > 512 or site_url != site_url.strip():
            skipped["path_prefix_or_invalid"] += 1
            continue
        if site_url.startswith("sc-domain:"):
            try:
                _domain_site(site_url)
            except ValidationError:
                skipped["path_prefix_or_invalid"] += 1
                continue
            approved = verified_domain_origins(project, site_url, verified_origins=verified_origins)
            if not approved or permission not in _PERMISSIONS:
                skipped["domain_wide"] += 1
                continue
            if site_url in selected:
                skipped["duplicate_property"] += 1
                if _PERMISSIONS[permission] <= _PERMISSIONS[selected[site_url]["permission_level"]]:
                    continue
            selected[site_url] = {
                "external_property_id": site_url, "google_site_url": site_url,
                "permission_level": permission, "scope": "verified_domain_page_only",
                "approved_origins": approved, "available_dimensions": ["page"],
                "access_evidence": "sites_list_and_verified_exact_origins_not_verified_sync",
            }
            continue
        try:
            identity = normalize_external_property("google_search_console", site_url)
        except ValidationError:
            skipped["path_prefix_or_invalid"] += 1
            continue
        if identity not in origins:
            skipped["foreign_scope"] += 1
            continue
        if permission not in _PERMISSIONS:
            skipped["unverified_or_unknown_permission"] += 1
            continue
        if identity in selected:
            skipped["duplicate_property"] += 1
            if _PERMISSIONS[permission] <= _PERMISSIONS[selected[identity]["permission_level"]]:
                continue
        selected[identity] = {
            "external_property_id": identity,
            "google_site_url": site_url,
            "permission_level": permission,
            "scope": "exact_origin_url_prefix",
            "access_evidence": "sites_list_only_not_verified_sync",
        }
    return {"provider": "google_search_console", "project_id": project.pk,
            "sites": [selected[key] for key in sorted(selected)], "skipped": skipped,
            "result_state": ("scoped_properties_listed" if any(
                item["scope"] == "verified_domain_page_only" for item in selected.values()) else "exact_scopes_listed")
            if selected else "no_accessible_exact_scope_property",
            "api_sync_status": "not_verified"}
