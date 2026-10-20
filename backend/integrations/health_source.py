"""Current retained sync metadata, never provider readiness or alert authority."""
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.utils import timezone

from tenancy.models import Project
from tenancy.services import Action, require_project_action
from .models import GoogleOAuthGrant, IntegrationConnection, SyncCursor, normalize_external_property, verified_domain_origins


METHOD = "integration-health-metadata-v1"
SCOPE = "bounded_connection_sync_metadata_not_readiness_staleness_regression_or_delivery_authority"
_CATEGORIES = {"quota_limited", "partial_coverage", "handler_failed", "request_outcome_unknown",
               "authorization_unavailable", "property_unavailable", "authorization_rejected",
               "reauthorization_required", "source_revoked", "cancelled", "malformed_response"}
_CONNECTION_FIELDS = ("id", "project_id", "provider", "external_property_id", "credential_reference",
    "capabilities", "available_dimensions", "state", "source_semantics", "source_semantics_version",
    "timezone", "currency", "backfill_limit_days", "created_at", "updated_at")
_GRANT_FIELDS = ("id", "organization_id", "project_id", "credential_reference", "scope", "state", "revision",
                 "selected_property_id", "selected_site_url", "selected_origins", "updated_at")
_CURSOR_FIELDS = ("id", "project_id", "connection_id", "revision", "status", "quota_state",
                  "last_attempt_at", "last_success_at", "fresh_through", "error_category", "retry_after",
                  "coverage_start", "coverage_end", "created_at", "updated_at")


def _snapshot(project):
    current = Project.objects.get(pk=project.pk, organization_id=project.organization_id)
    origins = sorted({current.canonical_origin, *current.domain_aliases.values_list("origin", flat=True)})
    connections = list(IntegrationConnection.objects.filter(project=current).order_by("pk").values(
        *_CONNECTION_FIELDS)[:51])
    grants = {grant["credential_reference"]: grant for grant in GoogleOAuthGrant.objects.filter(
        project=current, organization_id=current.organization_id,
        credential_reference__in=[item["credential_reference"] for item in connections if item["credential_reference"]]
    ).values(*_GRANT_FIELDS)}
    cursors = {cursor["connection_id"]: cursor for cursor in SyncCursor.objects.filter(
        connection_id__in=[item["id"] for item in connections]).values(*_CURSOR_FIELDS)}
    from .yandex_models import YandexOAuthGrant
    yandex = {row["connection_id"]: row for row in YandexOAuthGrant.objects.filter(
        project=current, organization_id=current.organization_id, connection_id__in=[item["id"] for item in connections]
    ).exclude(state="revoked").values("id", "connection_id", "state", "revision", "origin", "refresh_started_at", "updated_at")}
    records = []
    for connection in connections:
        grant = grants.get(connection["credential_reference"]) if connection["provider"] == "google_search_console" else None
        if connection["provider"] == "yandex_webmaster":
            grant = yandex.get(connection["id"])
        cursor = cursors.get(connection["id"])
        domain = connection["provider"] == "google_search_console" and connection["external_property_id"].startswith("sc-domain:")
        approved = verified_domain_origins(current, connection["external_property_id"]) if domain else []
        records.append((connection, grant, cursor, approved))
    return origins, records


def _source_state(connection, grant, origins, approved):
    if connection["provider"] == "google_analytics_4":
        return "exact_origin_attribution_unavailable"
    if connection["provider"] == "yandex_webmaster":
        if connection["state"] != "active":
            return connection["state"]
        if connection["external_property_id"] not in origins:
            return "scope_unavailable"
        return "api_sync_metadata" if grant and grant["state"] == "active" and not grant["refresh_started_at"] else "authorization_unavailable"
    if grant and grant["state"] == GoogleOAuthGrant.State.RECONNECT_REQUIRED:
        return "reconnect_required"
    if connection["state"] != IntegrationConnection.State.ACTIVE:
        return connection["state"]
    scoped = bool(set(approved) & set(grant["selected_origins"])) if approved and grant else (
        connection["external_property_id"] in origins)
    if not scoped:
        return "scope_unavailable"
    if "api_sync" not in connection["capabilities"]:
        return "csv_only"
    try:
        authorized = (grant and grant["state"] == GoogleOAuthGrant.State.ACTIVE
            and grant["selected_property_id"] == connection["external_property_id"]
            and normalize_external_property("google_search_console", grant["selected_site_url"]) == connection["external_property_id"])
    except ValidationError:
        authorized = False
    return "api_sync_metadata" if authorized else "authorization_unavailable"


def _row(record, origins, assessed):
    connection, grant, cursor, approved = record
    if (not 1 <= connection["id"] < 2**53 or connection["provider"] not in {"google_search_console", "google_analytics_4", "yandex_webmaster"}
        or connection["state"] not in IntegrationConnection.State.values
        or type(connection["capabilities"]) is not list
        or any(type(item) is not str for item in connection["capabilities"])
        or grant and connection["provider"] == "google_search_console" and (type(grant["selected_origins"]) is not list
                      or any(type(item) is not str for item in grant["selected_origins"]))):
        raise ValidationError("Integration metadata needs review.")
    sync = None
    # Hypothetical or legacy hostname-only GA4 cursors cannot become project reporting evidence.
    if cursor and connection["provider"] in {"google_search_console", "yandex_webmaster"}:
        if (cursor["project_id"] != connection["project_id"] or "api_sync" not in connection["capabilities"]
            or cursor["status"] not in SyncCursor.Status.values or cursor["quota_state"] not in SyncCursor.QuotaState.values
            or cursor["revision"] < 0):
            raise ValidationError("Integration metadata needs review.")
        for field in ("last_attempt_at", "last_success_at", "created_at", "updated_at"):
            value = cursor[field]
            if value is not None and (timezone.is_naive(value) or value > assessed):
                raise ValidationError("Integration metadata needs review.")
        if cursor["created_at"] > cursor["updated_at"]:
            raise ValidationError("Integration metadata needs review.")
        try:
            today = assessed.date() if connection["provider"] == "yandex_webmaster" else assessed.astimezone(ZoneInfo(connection["timezone"])).date()
        except (ValueError, ZoneInfoNotFoundError):
            raise ValidationError("Integration metadata needs review.") from None
        if cursor["fresh_through"] and cursor["fresh_through"] > today:
            raise ValidationError("Integration metadata needs review.")
        sync = {"status": cursor["status"], "quota_state": cursor["quota_state"],
                "last_attempt_at": cursor["last_attempt_at"].isoformat() if cursor["last_attempt_at"] else None,
                "last_success_at": cursor["last_success_at"].isoformat() if cursor["last_success_at"] else None,
                "fresh_through": cursor["fresh_through"].isoformat() if cursor["fresh_through"] else None,
                "error_category": (cursor["error_category"] if cursor["error_category"] in _CATEGORIES else
                                   "unclassified_failure" if cursor["error_category"] else "")}
    return {"connection_id": connection["id"], "provider": connection["provider"],
            "connection_state": connection["state"], "source_state": _source_state(connection, grant, origins, approved),
            "sync": sync}


def integration_health_metadata(*, project, actor):
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    assessed = timezone.now()
    original = _snapshot(project)
    origins, records = original
    result = {"method_version": METHOD, "project_id": project.pk, "scope": SCOPE,
              "assessed_at": assessed.isoformat(), "rows": [_row(record, origins, assessed) for record in records[:50]],
              "has_more": len(records) > 50}
    if _snapshot(project) != original:
        raise ValidationError("Integration metadata changed during inspection.")
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    return result
