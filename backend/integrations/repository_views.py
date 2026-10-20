from datetime import timedelta
from hashlib import sha256
import hmac
from http import HTTPStatus
import json
import re

from allauth.core import ratelimit
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_GET, require_POST

from tenancy.models import AuditEvent, AuditEventType, Organization
from tenancy.services import Action, _recent_authentication, require_project_action
from .oauth_views import _project, _response, _redirect
from .repository_models import RepositoryApplication, RepositoryConsent, RepositoryGrant
from .repository_oauth import (application, begin_consent, complete_consent, grant_current, lock_application,
    report_grant_revoked, report_unknown_revoked, revoke_grant, unseal)
from .repository_transport import RepositoryError
from .search_console_transport import _reject_constant, _unique_object


def _body(request, fields):
    if request.content_type != "application/json" or len(request.body) > 4096:
        raise ValidationError("Use a bounded JSON command.")
    value = json.loads(request.body, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    if type(value) is not dict or set(value) != fields:
        raise ValidationError("Use exact repository command fields.")
    return value


@require_GET
def repository_connections(request, organization_id, project_id):
    from jobs.repository_analysis_api import available
    project = _project(request, organization_id, project_id)
    if project is None:
        return _response({"error": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.VIEW_PROJECT)
        try:
            require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
            can_manage = True
        except PermissionDenied:
            can_manage = False
        if set(request.GET) - {"before"} or any(len(values) != 1 for _, values in request.GET.lists()):
            raise ValidationError("Use a bounded connection cursor.")
        query = RepositoryGrant.objects.filter(project=project, organization_id=organization_id).select_related("actor", "consent")
        before = request.GET.get("before")
        if before is not None:
            if not re.fullmatch(r"[1-9][0-9]{0,15}", before):
                raise ValidationError("Use an actual connection cursor.")
            query = query.filter(pk__lt=int(before))
        rows = list(query.order_by("-pk")[:21])
        unknown = list(RepositoryConsent.objects.filter(project=project, organization_id=organization_id, status="consumed",
            repositorygrant__isnull=True, user_reported_revoked_at__isnull=True).order_by("-pk")[:21])
        return _response({"project_id": project.pk, "method": "github-readonly-consent-v1", "can_manage": can_manage,
            "application_configured": RepositoryApplication.objects.exists(), "analysis_available": available(),
            "connections": [{"id": row.pk, "project_id": row.project_id, "repository": row.repository,
                "repository_id": row.repository_id, "commit_sha": row.commit_sha, "state": row.state, "revision": row.revision,
                "expires_at": row.expires_at.isoformat(), "source_current": grant_current(row),
                "revocation_evidence": row.revocation_evidence,
                "can_report_revoked": row.state == "revocation_pending" and row.created_at <= timezone.now() - timedelta(minutes=10),
                "created_at": row.created_at.isoformat(), "permissions": {"contents": "read", "metadata": "read"}} for row in rows[:20]],
            "next_before": rows[19].pk if len(rows) > 20 else None,
            "unknown_exchanges": [{"id": row.pk, "repository": row.repository, "repository_id": row.repository_id,
                "commit_sha": row.commit_sha, "can_report_revoked": row.used_at <= timezone.now() - timedelta(minutes=10)} for row in unknown[:20]],
            "has_more_unknown": len(unknown) > 20})
    except PermissionDenied:
        return _response({"error": "Current project access unavailable."}, HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _response({"error": "Use a bounded connection cursor."}, HTTPStatus.BAD_REQUEST)


@require_POST
def repository_command(request, organization_id, project_id, grant_id=None, consent_id=None, reported=False):
    project = _project(request, organization_id, project_id)
    if project is None:
        return _response({"error": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
        if not ratelimit.consume(request, action="repository_consent", user=request.user):
            return _response({"error": "Too many repository decisions."}, HTTPStatus.TOO_MANY_REQUESTS)
        if grant_id:
            RepositoryGrant.objects.get(pk=grant_id, project=project, organization_id=organization_id)
            if reported:
                _recent_authentication(request, request.user)
                if _body(request, {"remote_revocation_completed"})["remote_revocation_completed"] is not True:
                    raise ValidationError("Record actual completed remote revocation.")
                grant = report_grant_revoked(grant_id=grant_id, actor=request.user)
            else:
                data = _body(request, {"revision"})
                grant = revoke_grant(grant_id=grant_id, actor=request.user, expected_revision=data["revision"])
            return _response({"project_id": project.pk, "grant_id": grant.pk, "state": grant.state,
                "revocation_evidence": grant.revocation_evidence})
        if consent_id:
            _recent_authentication(request, request.user)
            data = _body(request, {"remote_revocation_completed"})
            if data["remote_revocation_completed"] is not True:
                raise ValidationError("Record remote revocation you actually completed.")
            RepositoryConsent.objects.get(pk=consent_id, project=project, organization_id=organization_id)
            report_unknown_revoked(consent_id=consent_id, actor=request.user)
            return _response({"project_id": project.pk, "state": "user_reported_revoked_not_provider_verified"})
        data = _body(request, {"repository", "repository_id", "commit_sha", "acknowledge_read_only_access"})
        url = begin_consent(project=project, actor=request.user, session_key=request.session.session_key, **data)
        return _response({"project_id": project.pk, "authorization_url": url})
    except (PermissionDenied, ObjectDoesNotExist):
        return _response({"error": "Current verified project management access is required."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, RepositoryError, IntegrityError, ValueError, TypeError, UnicodeError, RecursionError):
        return _response({"error": "Repository decision unconfirmed. Refresh connections and resolve existing/pending consent before another attempt."}, HTTPStatus.CONFLICT)


@require_GET
@sensitive_variables("code", "state")
def repository_callback(request):
    if not request.user.is_authenticated or not request.user.is_active:
        return _redirect("/account/login")
    try:
        if (set(request.GET) - {"code", "state", "error", "error_description", "error_uri", "repository_id"}
            or any(len(values) != 1 for _, values in request.GET.lists())
            or not ratelimit.consume(request, action="repository_callback", user=request.user)):
            raise ValidationError("Invalid repository consent response.")
        grant = complete_consent(actor=request.user, session_key=request.session.session_key, state=request.GET.get("state"),
            callback_url=request.build_absolute_uri(request.path), code=request.GET.get("code"), denied="error" in request.GET)
        return _redirect(f"/app/repositories/{grant.organization_id}/{grant.project_id}")
    except (PermissionDenied, ObjectDoesNotExist, ValidationError, RepositoryError, IntegrityError):
        return _redirect("/app")


@csrf_exempt
@require_POST
@sensitive_variables()
def repository_webhook(request):
    """Signed revocations only; neither repository text nor events can grant local authority."""
    try:
        if request.content_type != "application/json" or len(request.body) > 65536:
            raise ValueError
        app = application()
        secret = unseal("application", app.encrypted_secrets)["webhook_secret"]
        expected = "sha256=" + hmac.new(secret.encode(), request.body, sha256).hexdigest()
        if not hmac.compare_digest(expected, request.headers.get("X-Hub-Signature-256", "")):
            raise PermissionDenied
        event = request.headers.get("X-GitHub-Event")
        data = json.loads(request.body, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        if type(data) is not dict:
            raise ValueError
        if event == "ping":
            return _response({"received": True})
        if event == "github_app_authorization" and data.get("action") == "revoked":
            user_id = data.get("sender", {}).get("id")
            if type(user_id) is not int or not 0 < user_id < 2**53:
                raise ValueError
            filters = {"github_user_id": user_id}
        elif event == "installation" and data.get("action") in {"deleted", "suspend", "new_permissions_accepted"}:
            installation = data.get("installation", {})
            if installation.get("app_id") != app.app_id or type(installation.get("id")) is not int:
                raise ValueError
            filters = {"installation_id": installation["id"]}
        elif event == "installation_repositories" and data.get("action") == "removed":
            removed = data.get("repositories_removed")
            if type(removed) is not list or len(removed) > 100 or any(type(row) is not dict or type(row.get("id")) is not int for row in removed):
                raise ValueError
            filters = {"repository_id__in": [row["id"] for row in removed]}
        else:
            return _response({"received": True})
        with transaction.atomic():
            lock_application()
            if application(app.pk).revision != app.revision:
                raise PermissionDenied
            identities = list(RepositoryGrant.objects.filter(application=app, **filters).exclude(state="revoked")
                .values_list("pk", "organization_id").order_by("organization_id", "pk"))
            for pk, organization_id in identities:
                Organization.objects.select_for_update().get(pk=organization_id)
                grant = RepositoryGrant.objects.select_for_update().get(pk=pk)
                if grant.state == "revoked":
                    continue
                # Installation changes revoke local use, but do not prove a user OAuth token was remotely deleted.
                confirmed = event == "github_app_authorization"
                grant.state, grant.revision = "revoked" if confirmed else "revocation_pending", grant.revision + 1
                if confirmed:
                    grant.encrypted_tokens, grant.revoked_at = "", timezone.now()
                    grant.revocation_evidence = "provider_confirmed"
                grant.save()
                AuditEvent.objects.create(organization_id=organization_id, project_id=grant.project_id, actor=grant.actor,
                    event_type=AuditEventType.INTEGRATION_CREDENTIAL_REVOKED,
                    details={"kind": "repository_provider_revocation_event", "grant_id": pk, "provider_confirmed": confirmed})
        return _response({"received": True})
    except (PermissionDenied, RepositoryError, ObjectDoesNotExist, ValidationError, ValueError, TypeError, AttributeError, UnicodeError, RecursionError):
        return _response({"error": "Webhook unavailable."}, HTTPStatus.BAD_REQUEST)
