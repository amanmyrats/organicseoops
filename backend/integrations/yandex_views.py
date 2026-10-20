from http import HTTPStatus
import re

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.views.decorators.http import require_http_methods

from jobs.models import JobCancellation, JobRun, JobStatus
from jobs.services import cancel_job
from jobs.usage import UsageLimitError
from tenancy.models import DomainAlias, Organization, Project
from tenancy.services import Action, require_project_action
from .oauth_views import _project, _response
from .yandex_webmaster import HANDLER, MAX_BYTES, MAX_ROWS, METHOD, queue_import, source_current, validate_job


def job_payload(job, *, detailed=False):
    current = source_current(job)
    data = {"id": job.pk, "project_id": job.project_id, "handler": HANDLER, "status": job.status,
        "created_at": job.created_at.isoformat(), "updated_at": job.updated_at.isoformat(),
        "error_category": job.error_category or job.dispatch_error, "source_current": current,
        "cancel_requested": JobCancellation.objects.filter(job=job).exists(), "estimate_units": 1,
        "evidence": None}
    if current and detailed and job.status == JobStatus.SUCCEEDED:
        validate_job(job)
        data["evidence"] = job.input_snapshot["evidence"]
    return data


@require_http_methods(["GET", "POST"])
def project_yandex(request, organization_id, project_id, job_id=None):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"error": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _response({"error": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.VIEW_PROJECT)
        try:
            require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
            require_project_action(project=project, user=request.user, action=Action.LAUNCH_JOB)
            can_import = True
        except PermissionDenied:
            can_import = False
        job = JobRun.objects.filter(pk=job_id, project=project, organization_id=organization_id, handler=HANDLER).first() if job_id else None
        if job_id and job is None:
            return _response({"error": "Import unavailable."}, HTTPStatus.NOT_FOUND)
        if request.method == "POST":
            if not ratelimit.consume(request, action="yandex_csv_import", user=request.user):
                return _response({"error": "Too many import requests."}, HTTPStatus.TOO_MANY_REQUESTS)
            if job:
                require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
                if request.content_type != "application/json" or request.META.get("CONTENT_LENGTH") != "2" or request.read(3) != b"{}":
                    raise ValidationError("Use an empty cancellation request.")
                job, _changed, _pending = cancel_job(job=job, actor=request.user)
            else:
                if not can_import:
                    raise PermissionDenied
                length = request.META.get("CONTENT_LENGTH", "")
                if (request.content_type != "text/csv" or request.headers.get("Content-Encoding")
                    or not re.fullmatch(r"[0-9]{1,7}", length) or not 1 <= int(length) <= MAX_BYTES
                    or request.headers.get("X-Yandex-Authorization") != "true"):
                    raise ValidationError("Authorize a bounded UTF-8 CSV export.")
                content = request.read(MAX_BYTES + 1)
                if len(content) != int(length):
                    raise ValidationError("Upload size changed.")
                job = queue_import(project=project, actor=request.user, content=content,
                    origin=request.headers.get("X-Yandex-Origin", ""), date_start=request.headers.get("X-Yandex-Start", ""),
                    date_end=request.headers.get("X-Yandex-End", ""), idempotency_key=request.headers.get("X-Yandex-Request", ""))
            return _response({"project_id": project.pk, "job": job_payload(job)}, HTTPStatus.OK if job_id else HTTPStatus.ACCEPTED)
        # Serialize current project/source authorization with membership/origin changes.
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=organization_id)
            project = Project.objects.select_for_update().select_related("organization").get(pk=project_id, organization_id=organization_id)
            require_project_action(project=project, user=request.user, action=Action.VIEW_PROJECT)
            if job:
                return _response({"project_id": project.pk, "job": job_payload(job, detailed=True)})
            before = request.GET.get("before")
            if set(request.GET) - {"before"} or before is not None and not re.fullmatch(r"[1-9][0-9]{0,18}", before):
                raise ValidationError("Use a valid history cursor.")
            queryset = JobRun.objects.filter(project=project, organization_id=organization_id, handler=HANDLER)
            if before:
                queryset = queryset.filter(pk__lt=int(before))
            rows = list(queryset.order_by("-pk")[:21])
            origins = [project.canonical_origin, *DomainAlias.objects.filter(project=project, organization_id=organization_id).values_list("origin", flat=True)[:99]]
            return _response({"project_id": project.pk, "method": METHOD, "can_import": can_import,
                "origins": list(dict.fromkeys(origins)), "jobs": [job_payload(row) for row in rows[:20]],
                "next_before": rows[19].pk if len(rows) > 20 else None, "max_bytes": MAX_BYTES,
                "max_rows": MAX_ROWS, "max_evidence_bytes": 24576, "estimate_units": 1,
                "capabilities": ["csv_import", "query_page_region_metrics"], "timezone": "unspecified_by_export"})
    except PermissionDenied:
        return _response({"error": "Current project access, origin or import authority unavailable."}, HTTPStatus.FORBIDDEN)
    except UsageLimitError as error:
        return _response({"error": "Import allowance unavailable.", "code": error.category}, HTTPStatus.TOO_MANY_REQUESTS)
    except (ValidationError, IntegrityError, ValueError, TypeError):
        return _response({"error": "Check the official CSV format, exact origin, declared dates, limits and request key. No partial rows imported."}, HTTPStatus.CONFLICT)
