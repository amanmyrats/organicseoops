from http import HTTPStatus
from datetime import timedelta
import json

from allauth.core import ratelimit
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_GET, require_POST

from tenancy.models import Organization, Project
from tenancy.services import Action, require_project_action, _recent_authentication
from .oauth_views import _project, _response, _redirect
from .yandex_models import YandexOAuthApplication, YandexOAuthGrant, YandexOAuthIntent
from .yandex_oauth import begin_consent, complete_consent, revoke_grant, report_unknown_exchange_revoked
from .yandex_transport import YandexError


def _body(request, fields):
    if request.content_type != "application/json" or len(request.body) > 2048:
        raise ValidationError("Use a bounded JSON request.")
    try:
        value = json.loads(request.body)
    except (ValueError, UnicodeError):
        raise ValidationError("Use valid JSON.") from None
    if type(value) is not dict or set(value) != fields:
        raise ValidationError("Check request fields.")
    return value


@require_GET
def yandex_grants(request, organization_id, project_id):
    project = _project(request, organization_id, project_id)
    if project is None:
        return _response({"error": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=organization_id)
            require_project_action(project=project, user=request.user, action=Action.VIEW_PROJECT)
            try:
                require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
                can_manage = True
            except PermissionDenied:
                can_manage = False
            rows = list(YandexOAuthGrant.objects.filter(organization_id=organization_id, project=project).exclude(state="revoked").order_by("-pk")[:21])
            unknown = list(YandexOAuthIntent.objects.filter(organization_id=organization_id, project=project,
                status="consumed", yandexoauthgrant__isnull=True, user_reported_revoked_at__isnull=True).order_by("-pk")[:20])
            from .models import SyncCursor
            cursors = {row.connection_id: row for row in SyncCursor.objects.filter(project=project,
                connection_id__in=[grant.connection_id for grant in rows if grant.connection_id])}
            today = timezone.now().date()
            def sync_metadata(grant):
                cursor = cursors.get(grant.connection_id)
                start = cursor.position.get("next_start") if cursor else None
                start = start or (today - timedelta(days=7)).isoformat()
                from datetime import date
                end = min(date.fromisoformat(start) + timedelta(days=30), today - timedelta(days=1))
                return {"suggested_start": start, "suggested_end": end.isoformat(),
                    "cursor": None if cursor is None else {"status": cursor.status, "error_category": cursor.error_category,
                        "quota_state": cursor.quota_state, "retry_after": cursor.retry_after.isoformat() if cursor.retry_after else None,
                        "anchor_start": cursor.position.get("anchor_start"), "next_start": cursor.position.get("next_start"),
                        "contiguous_reported_through": cursor.fresh_through.isoformat() if cursor.fresh_through else None,
                        "last_attempt_at": cursor.last_attempt_at.isoformat() if cursor.last_attempt_at else None}}
            return _response({"project_id": project.pk, "can_manage": can_manage,
                "application_configured": YandexOAuthApplication.objects.exists(), "has_more": len(rows) > 20,
                "unknown_exchanges": [{"id": row.pk, "origin": row.origin, "created_at": row.created_at.isoformat(),
                    "can_report_revoked": row.used_at <= timezone.now() - timedelta(minutes=10)} for row in unknown],
                "grants": [{"id": row.pk, "origin": row.origin, "state": row.state, "revision": row.revision,
                    "expires_at": row.expires_at.isoformat(), "scope": row.scope,
                    "refresh_unknown": row.refresh_started_at is not None,
                    "can_report_refresh_revoked": bool(row.refresh_started_at and row.refresh_started_at <= timezone.now() - timedelta(minutes=10)),
                    **sync_metadata(row)} for row in rows[:20]]})
    except (PermissionDenied, ObjectDoesNotExist):
        return _response({"error": "Current project access unavailable."}, HTTPStatus.FORBIDDEN)


@require_POST
def yandex_oauth_start(request, organization_id, project_id):
    project = _project(request, organization_id, project_id)
    if project is None:
        return _response({"error": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        if not ratelimit.consume(request, action="yandex_oauth_start", user=request.user):
            return _response({"error": "Too many consent attempts."}, HTTPStatus.TOO_MANY_REQUESTS)
        body = _body(request, {"origin"})
        if not request.session.session_key:
            raise PermissionDenied
        url = begin_consent(project=project, actor=request.user, origin=body["origin"], session_key=request.session.session_key)
        return _response({"authorization_url": url})
    except (PermissionDenied, ObjectDoesNotExist):
        return _response({"error": "Current manager access and verified account are required."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, YandexError, IntegrityError):
        return _response({"error": "Configure Yandex consent and encryption, check the origin or disconnect its existing grant first."}, HTTPStatus.CONFLICT)


@require_GET
@sensitive_variables("code", "state")
def yandex_oauth_callback(request):
    if not request.user.is_authenticated or not request.user.is_active:
        return _redirect("/account/login")
    try:
        if (set(request.GET) - {"code", "state", "error", "error_description", "cid"}
            or any(len(request.GET.getlist(key)) != 1 for key in request.GET)
            or not ratelimit.consume(request, action="yandex_oauth_callback", user=request.user)):
            raise ValidationError("Invalid consent response.")
        code, state = request.GET.get("code"), request.GET.get("state")
        grant = complete_consent(actor=request.user, session_key=request.session.session_key, state=state,
            callback_url=request.build_absolute_uri(request.path), code=code, denied="error" in request.GET)
        return _redirect(f"/app/yandex/{grant.organization_id}/{grant.project_id}")
    except (PermissionDenied, ObjectDoesNotExist, ValidationError, YandexError, IntegrityError):
        return _redirect("/app")


@require_POST
def yandex_oauth_revoke(request, organization_id, project_id, grant_id):
    project = _project(request, organization_id, project_id)
    if project is None:
        return _response({"error": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
        if not ratelimit.consume(request, action="yandex_oauth_revoke", user=request.user):
            return _response({"error": "Too many disconnect requests."}, HTTPStatus.TOO_MANY_REQUESTS)
        body = _body(request, {"revision"})
        if not YandexOAuthGrant.objects.filter(pk=grant_id, project=project, organization_id=organization_id).exists():
            raise PermissionDenied
        grant = revoke_grant(grant_id=grant_id, actor=request.user, expected_revision=body["revision"])
        return _response({"project_id": project.pk, "grant_id": grant.pk, "state": grant.state})
    except (PermissionDenied, ObjectDoesNotExist):
        return _response({"error": "Current grant management unavailable."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, YandexError):
        return _response({"error": "Disconnect is unconfirmed. Local use is disabled once revocation is pending; refresh and retry that grant."}, HTTPStatus.CONFLICT)


@require_POST
def yandex_unknown_revoked(request, organization_id, project_id, intent_id):
    project = _project(request, organization_id, project_id)
    if project is None:
        return _response({"error": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        _recent_authentication(request, request.user)
        require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
        if not ratelimit.consume(request, action="yandex_oauth_revoke", user=request.user):
            return _response({"error": "Too many requests."}, HTTPStatus.TOO_MANY_REQUESTS)
        if _body(request, {"remote_revocation_completed"})["remote_revocation_completed"] is not True:
            raise ValidationError("Record actual remote revocation first.")
        if not YandexOAuthIntent.objects.filter(pk=intent_id, organization_id=organization_id, project=project).exists():
            raise PermissionDenied
        report_unknown_exchange_revoked(intent_id=intent_id, actor=request.user)
        return _response({"project_id": project.pk, "state": "user_reported_revoked_not_provider_verified"})
    except (PermissionDenied, ObjectDoesNotExist):
        return _response({"error": "Reauthenticate and use current project management access."}, HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _response({"error": "Wait for the exchange to settle; record only remote revocation you actually completed."}, HTTPStatus.CONFLICT)
