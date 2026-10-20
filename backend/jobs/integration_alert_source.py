"""Read-only current reconnect candidates from mutable retained audits, never send authority."""
from datetime import timedelta, timezone as utc

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from integrations.google_oauth import RECONNECT_METHOD
from integrations.google_tokens import SCOPE as GOOGLE_SCOPE
from integrations.health_source import _snapshot as health_snapshot
from integrations.models import GoogleOAuthGrant, IntegrationConnection, normalize_external_property
from tenancy.models import AuditEvent, AuditEventType
from tenancy.services import Action, require_project_action
from .alert_delivery_source import _binding


METHOD = "optional-daily-reconnect-source-v1"
SCOPE = "first50_connections_newest20_post_intent_reconnect_audits_not_immutable_incidents_or_send_authority"
_REASONS = {"provider_refresh_rejected", "authorization_unavailable", "property_unavailable"}


def _id(value):
    return type(value) is int and 1 <= value < 2**53


def _snapshot(project, start, end, intent_at):
    health = health_snapshot(project)
    grant_ids = [grant["id"] for _connection, grant, _cursor, _approved in health[1][:50] if grant]
    references = {grant["id"]: grant["credential_reference"] for _connection, grant, _cursor, _approved in health[1][:50] if grant}
    audits = list(AuditEvent.objects.filter(organization_id=project.organization_id, project_id=project.pk,
        event_type=AuditEventType.GOOGLE_OAUTH_RECONNECT_REQUIRED, details__grant_id__in=grant_ids,
        created_at__gte=start, created_at__lt=end).filter(created_at__gte=intent_at).order_by(
            "-created_at", "-pk").values("id", "actor_id", "subject_user_id", "invitation_id", "created_at", "details")[:21])
    identities = {}
    for audit in audits:
        details = audit["details"]
        if (type(details) is dict and _id(details.get("grant_id"))
            and type(details.get("grant_revision")) is int and details["grant_revision"] >= 1):
            audit_ids = list(AuditEvent.objects.filter(
                organization_id=project.organization_id, project_id=project.pk,
                event_type=AuditEventType.GOOGLE_OAUTH_RECONNECT_REQUIRED,
                details__grant_id=details["grant_id"], details__grant_revision=details["grant_revision"]
            ).order_by("pk").values_list("pk", flat=True)[:2])
            linked_ids = list(IntegrationConnection.objects.filter(project_id=project.pk,
                credential_reference=references.get(details["grant_id"])).order_by("pk").values_list("pk", flat=True)[:51])
            identities[audit["id"]] = (audit_ids, linked_ids)
    return health, audits, identities


def _row(audit, health, identities, assessed):
    details = audit["details"]
    # Old audits have no prospective identity. Mutable grant.updated_at cannot repair that gap.
    if (type(details) is not dict or details.get("method_version") != RECONNECT_METHOD
        or "grant_revision" not in details):
        return None
    if (set(details) != {"method_version", "grant_id", "grant_revision", "connection_ids", "reason"}
        or not _id(details["grant_id"]) or not _id(details["grant_revision"])
        or type(details["reason"]) is not str or details["reason"] not in _REASONS
        or type(details["connection_ids"]) is not list or not 1 <= len(details["connection_ids"]) <= 50
        or any(not _id(item) for item in details["connection_ids"])
        or len(set(details["connection_ids"])) != len(details["connection_ids"])
        or any(audit[field] is not None for field in ("actor_id", "subject_user_id", "invitation_id"))
        or not _id(audit["id"]) or timezone.is_naive(audit["created_at"]) or audit["created_at"] > assessed):
        raise ValidationError("Reconnect audit metadata needs review.")
    matches = []
    origins, records = health
    audit_ids, linked_ids = identities.get(audit["id"], ([], []))
    selected_ids = {connection["id"] for connection, _grant, _cursor, _approved in records[:50]}
    if set(details["connection_ids"]) != set(linked_ids) or not set(linked_ids) <= selected_ids:
        return None
    for connection, grant, _cursor, approved in records[:50]:
        if not grant or grant["id"] != details["grant_id"]:
            continue
        if (grant["state"] != GoogleOAuthGrant.State.RECONNECT_REQUIRED
            or grant["revision"] != details["grant_revision"] or grant["scope"] != GOOGLE_SCOPE
            or connection["state"] != IntegrationConnection.State.DISCONNECTED
            or connection["id"] not in details["connection_ids"]
            or connection["provider"] != "google_search_console"
            or type(connection["capabilities"]) is not list or "api_sync" not in connection["capabilities"]
            or grant["selected_property_id"] != connection["external_property_id"]):
            continue
        try:
            selected = normalize_external_property("google_search_console", grant["selected_site_url"])
        except ValidationError:
            continue
        if selected != connection["external_property_id"]:
            continue
        if (type(grant["selected_origins"]) is not list
            or any(type(item) is not str for item in grant["selected_origins"])):
            raise ValidationError("Reconnect source scope needs review.")
        if selected.startswith("sc-domain:"):
            scoped = (grant["selected_site_url"] == selected and bool(set(approved) & set(grant["selected_origins"]))
                      and connection["source_semantics"] == "search_console_domain_pages")
        else:
            scoped = (selected in origins and not grant["selected_origins"]
                      and connection["source_semantics"] == "search_console_performance")
        if scoped:
            matches.append(connection["id"])
    if not matches:
        return None
    if len(matches) != 1 or audit_ids != [audit["id"]]:
        raise ValidationError("Reconnect source identity needs review.")
    return {"audit_id": audit["id"], "grant_id": details["grant_id"], "grant_revision": details["grant_revision"],
            "connection_id": matches[0], "source_method": RECONNECT_METHOD,
            "audit_created_at": audit["created_at"].isoformat(), "reason": details["reason"]}


def current_daily_integration_alert_source(*, project, recipient):
    original = _binding(project, recipient, "integration_health")
    result = {"method_version": METHOD, "project_id": project.pk, "scope": SCOPE,
              "state": "unavailable_integration_alert_intent", "preference_revision": None,
              "intent_updated_at": None, "day_start": None, "day_end": None, "assessed_at": None,
              "rows": [], "has_more": False}
    if original is None:
        require_project_action(project=project, user=recipient, action=Action.VIEW_PROJECT)
        return result
    assessed = timezone.now().astimezone(utc.utc)
    end = assessed.replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=1)
    snapshot = _snapshot(project, start, end, original[3])
    health, audits, identities = snapshot
    rows = [row for audit in audits[:20] if (row := _row(audit, health, identities, assessed)) is not None]
    result.update(state="available_reconnect_candidates_not_sent" if rows else "unavailable_no_reconnect_candidates",
        preference_revision=original[1], intent_updated_at=original[3].isoformat(), day_start=start.isoformat(),
        day_end=end.isoformat(), assessed_at=assessed.isoformat(), rows=rows,
        has_more=len(health[1]) > 50 or len(audits) > 20)
    if _snapshot(project, start, end, original[3]) != snapshot:
        raise ValidationError("Current reconnect selection changed during inspection.")
    if _binding(project, recipient, "integration_health") != original:
        raise PermissionDenied
    return result
