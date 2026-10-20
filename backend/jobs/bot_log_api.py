from datetime import datetime
from http import HTTPStatus
import re

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.views.decorators.http import require_http_methods

from tenancy.models import ProjectOriginVerification
from tenancy.services import Action, require_project_action
from .api import _error, _project, _response
from .bot_logs import BotLogError, LIMITS, MAX_BYTES, METHOD
from .bot_log_import import HANDLER, queue_bot_log_import, source_current, source_snapshot
from .models import IndexationEvidenceSnapshot, JobCancellation, JobRun
from .services import cancel_job
from .usage import UsageLimitError


def job_payload(job):
    current = source_current(job)
    return {"id": job.pk, "project_id": job.project_id, "status": job.status,
        "created_at": job.created_at.isoformat(), "updated_at": job.updated_at.isoformat(),
        "error_category": job.error_category or job.dispatch_error, "source_current": current,
        "cancel_requested": JobCancellation.objects.filter(job=job).exists(), "estimate_units": 1,
        "inventory_id": job.config_snapshot["inventory_id"] if current else None,
        "crawl_run_id": job.config_snapshot["crawl_run_id"] if current else None,
        "evidence": job.output if current and job.status == "succeeded" else None}


@require_http_methods(["GET", "POST"])
def project_bot_logs(request, organization_id, project_id, job_id=None):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _error("Project unavailable.", HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.VIEW_PROJECT)
        try:
            require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
            can_manage = True
        except PermissionDenied:
            can_manage = False
        job = JobRun.objects.filter(project=project, pk=job_id, handler=HANDLER).first() if job_id else None
        if job_id and job is None:
            return _error("Import unavailable.", HTTPStatus.NOT_FOUND)
        if request.method == "POST":
            if not can_manage:
                raise PermissionDenied
            if not ratelimit.consume(request, action="bot_log_import", user=request.user):
                return _error("Too many logfile requests.", HTTPStatus.TOO_MANY_REQUESTS)
            if job:
                if request.body != b"{}":
                    raise ValidationError("Check the cancellation request.")
                job, _changed, _pending = cancel_job(job=job, actor=request.user)
            else:
                # An opaque raw body avoids Django multipart handlers/temp files.
                # Metadata has no file name or browser-supplied inventory URLs.
                length = request.META.get("CONTENT_LENGTH", "")
                if (request.content_type != "application/x-ndjson" or not re.fullmatch(r"[0-9]{1,7}", length)
                    or not 1 <= int(length) <= MAX_BYTES or request.headers.get("X-Log-Authorization") != "true"):
                    raise ValidationError("Choose a bounded JSONL export and explicitly authorize its use.")
                inventory = request.headers.get("X-Log-Inventory", "")
                if not re.fullmatch(r"[1-9][0-9]{0,18}", inventory):
                    raise ValidationError("Select a current inventory.")
                origin = request.headers.get("X-Log-Origin", "")
                source_snapshot(project, request.user, origin=origin, inventory_id=int(inventory))
                content = request.read(MAX_BYTES + 1)
                if len(content) != int(length):
                    raise ValidationError("Logfile size changed.")
                job = queue_bot_log_import(project=project, actor=request.user, content=content, origin=origin,
                    inventory_id=int(inventory), window_start=datetime.fromisoformat(request.headers.get("X-Log-Start", "")),
                    window_end=datetime.fromisoformat(request.headers.get("X-Log-End", "")), authorize_logfile=True,
                    idempotency_key=request.headers.get("X-Log-Request", ""))
            return _response({"project_id": project.pk, "job": job_payload(job)}, HTTPStatus.OK if job_id else HTTPStatus.ACCEPTED)
        if job:
            return _response({"project_id": project.pk, "job": job_payload(job)})
        before = request.GET.get("before")
        if set(request.GET) - {"before"} or before is not None and not re.fullmatch(r"[1-9][0-9]{0,18}", before):
            raise ValidationError("Choose a valid history cursor.")
        queryset = JobRun.objects.filter(project=project, handler=HANDLER)
        if before:
            queryset = queryset.filter(pk__lt=int(before))
        rows = list(queryset.order_by("-pk")[:21])
        origins = []
        inventories = []
        if can_manage:
            for verification in ProjectOriginVerification.objects.filter(project=project, state="verified", revoked_at__isnull=True)[:20]:
                from tenancy.services import project_has_origin
                if project_has_origin(project, verification.origin):
                    origins.append(verification.origin)
            for snapshot in IndexationEvidenceSnapshot.objects.filter(project=project).order_by("-pk")[:20]:
                supported = []
                for origin in origins:
                    try:
                        _config, urls = source_snapshot(project, request.user, origin=origin, inventory_id=snapshot.pk)
                        supported.append({"origin": origin, "url_count": len(urls)})
                    except (PermissionDenied, ValidationError):
                        continue
                if supported:
                    inventories.append({"id": snapshot.pk, "crawl_run_id": snapshot.crawl_run_id,
                        "observed_at": snapshot.observed_at.isoformat(), "origins": supported})
        return _response({"project_id": project.pk, "method": METHOD, "can_manage": can_manage,
            "origins": origins, "inventories": inventories, "jobs": [job_payload(row) for row in rows[:20]],
            "next_before": rows[19].pk if len(rows) > 20 else None, "limits": LIMITS,
            "coverage": "partial_customer_supplied_logs", "identity": "user_agent_only_unverified", "estimate_units": 1})
    except PermissionDenied:
        return _error("Current project role, verified origin or inventory authority unavailable.", HTTPStatus.FORBIDDEN)
    except UsageLimitError as error:
        return _error("Import allowance unavailable.", HTTPStatus.TOO_MANY_REQUESTS, code=error.category)
    except (ValidationError, BotLogError, ValueError, TypeError, IntegrityError):
        return _error("Check JSONL format, bounded coverage, current source and unique import request.", HTTPStatus.CONFLICT)
