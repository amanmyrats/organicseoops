from datetime import timedelta
from http import HTTPStatus
import re

from allauth.core import ratelimit
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from jobs.models import JobCancellation, JobRun, JobStatus
from jobs.services import cancel_job
from jobs.usage import UsageLimitError
from tenancy.models import AuditEvent, AuditEventType, Organization, Project
from tenancy.services import Action, _recent_authentication, require_project_action
from .models import IntegrationConnection
from .oauth_views import _project, _response
from .yandex_models import YandexOAuthGrant
from .yandex_oauth import _verified
from .yandex_oauth_views import _body
from .yandex_sync import HANDLER, METHOD, queue_sync, source_current


def job_payload(job, *, detailed=False):
    current = source_current(job)
    return {"id": job.pk, "project_id": job.project_id, "status": job.status,
        "created_at": job.created_at.isoformat(), "error_category": job.error_category or job.dispatch_error,
        "grant_id": job.input_snapshot["grant_id"], "date_start": job.input_snapshot["date_start"],
        "date_end": job.input_snapshot["date_end"], "source_current": current,
        "cancel_requested": JobCancellation.objects.filter(job=job).exists(),
        "evidence": job.output if detailed and current and job.status in {JobStatus.SUCCEEDED, JobStatus.PARTIALLY_SUCCEEDED} else None}


@require_http_methods(["GET", "POST"])
def yandex_syncs(request, organization_id, project_id, job_id=None):
    project = _project(request, organization_id, project_id)
    if project is None:
        return _response({"error": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.VIEW_PROJECT)
        if request.method == "POST":
            require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
            if not ratelimit.consume(request, action="yandex_sync", user=request.user):
                return _response({"error": "Too many Yandex requests."}, HTTPStatus.TOO_MANY_REQUESTS)
            if job_id:
                if _body(request, set()) != {}:
                    raise ValidationError("Use an empty cancellation request.")
                job = JobRun.objects.get(pk=job_id, project=project, organization_id=organization_id, handler=HANDLER)
                job, _changed, _pending = cancel_job(job=job, actor=request.user)
            else:
                data = _body(request, {"grant_id", "revision", "date_start", "date_end", "request_key"})
                job = queue_sync(project=project, actor=request.user, grant_id=data["grant_id"], expected_revision=data["revision"],
                    date_start=data["date_start"], date_end=data["date_end"], idempotency_key=data["request_key"])
            return _response({"project_id": project.pk, "job": job_payload(job)}, HTTPStatus.OK if job_id else HTTPStatus.ACCEPTED)
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=organization_id)
            Project.objects.select_for_update().get(pk=project_id, organization_id=organization_id)
            require_project_action(project=project, user=request.user, action=Action.VIEW_PROJECT)
            if job_id:
                job = JobRun.objects.get(pk=job_id, project=project, organization_id=organization_id, handler=HANDLER)
                return _response({"project_id": project.pk, "job": job_payload(job, detailed=True)})
            before = request.GET.get("before")
            if set(request.GET) - {"before"} or before is not None and not re.fullmatch(r"[1-9][0-9]{0,18}", before):
                raise ValidationError("Choose a valid history cursor.")
            records = JobRun.objects.filter(project=project, organization_id=organization_id, handler=HANDLER)
            if before:
                records = records.filter(pk__lt=int(before))
            rows = list(records.order_by("-pk")[:21])
            return _response({"project_id": project.pk, "method": METHOD, "jobs": [job_payload(row) for row in rows[:20]],
                "next_before": rows[19].pk if len(rows) > 20 else None, "max_window_days": 31,
                "local_backfill_days": 90, "estimate_units": 1, "provider_history_guaranteed": False})
    except (PermissionDenied, ObjectDoesNotExist):
        return _response({"error": "Current project/source access unavailable."}, HTTPStatus.FORBIDDEN)
    except UsageLimitError as error:
        return _response({"error": "Sync allowance unavailable.", "code": error.category}, HTTPStatus.TOO_MANY_REQUESTS)
    except (ValidationError, IntegrityError, TypeError, ValueError):
        return _response({"error": "Refresh the grant and check dates, unfinished work, request key and source retry interval."}, HTTPStatus.CONFLICT)


@require_POST
def yandex_refresh_reported_revoked(request, organization_id, project_id, grant_id):
    project = _project(request, organization_id, project_id)
    if project is None:
        return _response({"error": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        _recent_authentication(request, request.user)
        require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
        if not _verified(request.user):
            raise PermissionDenied
        if not ratelimit.consume(request, action="yandex_oauth_revoke", user=request.user):
            return _response({"error": "Too many requests."}, HTTPStatus.TOO_MANY_REQUESTS)
        if _body(request, {"remote_revocation_completed"})["remote_revocation_completed"] is not True:
            raise ValidationError("Record only actual completed revocation.")
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=organization_id)
            grant = YandexOAuthGrant.objects.select_for_update().get(pk=grant_id, project=project, organization_id=organization_id)
            require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
            if not grant.refresh_started_at or grant.refresh_started_at > timezone.now() - timedelta(minutes=10):
                raise ValidationError("Wait for this unknown refresh to settle.")
            if grant.connection_id:
                IntegrationConnection.objects.filter(pk=grant.connection_id, project=project).update(
                    state="disconnected", credential_reference=None, updated_at=timezone.now())
            grant.state, grant.encrypted_tokens, grant.user_id, grant.host_id = "revoked", "", "", ""
            grant.revoked_at, grant.refresh_started_at = timezone.now(), None
            grant.revision += 1
            grant.save(update_fields=["state", "encrypted_tokens", "user_id", "host_id", "revoked_at", "refresh_started_at", "revision", "updated_at"])
            AuditEvent.objects.create(organization_id=organization_id, project=project, actor=request.user,
                event_type=AuditEventType.INTEGRATION_CREDENTIAL_REVOKED,
                details={"kind": "yandex_unknown_refresh_user_reported_revoked", "grant_id": grant.pk,
                    "evidence": "human_attestation_not_provider_verification"})
        return _response({"project_id": project.pk, "state": "user_reported_revoked_not_provider_verified"})
    except (PermissionDenied, ObjectDoesNotExist):
        return _response({"error": "Reauthenticate with current verified manager access."}, HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _response({"error": "Wait for the unknown refresh; record only remote revocation you actually completed."}, HTTPStatus.CONFLICT)
