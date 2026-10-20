import json
from http import HTTPStatus

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.db.models import Exists, OuterRef
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from tenancy.models import Project
from tenancy.services import Action, require_project_action

from .models import JobCancellation, JobRun, JobSchedule, JobStatus
from .services import cancel_job, queue_job, retry_job
from .schedules import create_schedule, set_schedule_enabled
from .usage import UsageLimitError


def _response(data, status=HTTPStatus.OK):
    response = JsonResponse(data, status=status)
    response["Cache-Control"] = "private, no-store"
    return response


def _error(message, status=HTTPStatus.BAD_REQUEST, *, code=None):
    error = {"message": message}
    if code:
        error["code"] = code
    return _response({"errors": [error]}, status)


def _usage_error(error):
    if error.category == "trial_unavailable":
        return _error("Active trial access is required for this work.", HTTPStatus.FORBIDDEN, code=error.category)
    if error.category == "trial_units_exhausted":
        return _error("Trial unit allowance reached.", HTTPStatus.TOO_MANY_REQUESTS, code=error.category)
    return _error(
        "Internal job budget or concurrency ceiling reached. Try again after active work settles.",
        HTTPStatus.TOO_MANY_REQUESTS,
        code=error.category,
    )


def _project(request, organization_id, project_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return None
    return Project.objects.for_user(request.user).filter(
        pk=project_id, organization_id=organization_id,
    ).first()


def _payload(request, fields, required=()):
    try:
        value = json.loads(request.body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValidationError("Enter valid JSON.") from None
    if not isinstance(value, dict) or set(value) - fields or not set(required) <= set(value):
        raise ValidationError("Check the submitted fields.")
    return value


def _job_payload(job, *, detailed=False):
    if job.handler == "analyze_repository":
        from .repository_analysis_api import job_payload
        return job_payload(job)
    if job.handler == "collect_serp":
        from .serp_api import job_payload
        return job_payload(job)
    if job.handler == "sync_yandex_webmaster":
        from integrations.yandex_sync_views import job_payload
        return job_payload(job)
    if job.handler == "import_yandex_webmaster_csv":
        from integrations.yandex_views import job_payload
        return job_payload(job)
    if job.handler == "import_bot_logs":
        from .bot_log_api import job_payload
        return job_payload(job)
    data = {
        "id": job.pk, "project_id": job.project_id, "handler": job.handler,
        "status": job.status, "retry_of": job.retry_of_id,
        "progress_percent": 0, "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(), "estimate": {"diagnostic_units_max": 0},
        "error_category": job.error_category or job.dispatch_error,
        "cancel_requested": getattr(job, "_cancel_requested", None) if hasattr(job, "_cancel_requested")
        else JobCancellation.objects.filter(job=job).exists(),
    }
    # D132 observations require exact current-source/private readback delivery.
    # Generic diagnostic status never discloses their output, citations or artifacts.
    if job.handler in {"classify_competitor_heading_topics", "synthesize_competitor_pair", "synthesize_competitor_headings_pair"}:
        data["estimate"] = {"internal_operation_units_max": 1, "provider_charge": "separate_ai_usage_observation"}
        return data
    if job.handler == "collect_competitor_lighthouse":
        data["estimate"] = {"internal_operation_units_max": 1, "provider_charge": "separate_google_provider_quota_not_estimated"}
        return data
    if job.handler in {"collect_competitor_root", "collect_competitor_schema_root", "collect_competitor_links_root", "collect_competitor_page", "collect_competitor_page_headings", "collect_competitor_page_destinations", "collect_competitor_page_dates", "collect_competitor_page_formats", "collect_passive_headers", "collect_passive_tls", "collect_passive_resources", "collect_passive_redirects", "collect_passive_http_redirects", "collect_passive_redirect_chain", "verify_authority_link_source"}:
        data["estimate"] = {"internal_operation_units_max": 1, "provider_charge": "not_applicable"}
        return data
    if detailed:
        steps = list(job.steps.order_by("sequence")[:101])
        citations = list(job.citations.order_by("id")[:101])
        artifacts = list(job.artifacts.order_by("id")[:101])
        data.update({
            "progress_percent": steps[-1].progress_percent if steps else 0,
            "output": job.output,
            "steps": [{"sequence": step.sequence, "name": step.name, "status": step.status,
                       "progress_percent": step.progress_percent, "output": step.output,
                       "error_category": step.error_category} for step in steps[:100]],
            "citations": [{"id": item.pk, "source_title": item.source_title,
                           "source_url": item.source_url, "observed_at": item.observed_at.isoformat()}
                          for item in citations[:100]],
            "artifacts": [{"id": item.pk, "content_type": item.content_type, "size_bytes": item.size_bytes}
                          for item in artifacts[:100]],
            "has_more": any(len(items) > 100 for items in (steps, citations, artifacts)),
        })
    return data


@require_http_methods(["GET", "POST"])
def jobs(request, organization_id, project_id):
    if not settings.DEBUG:
        return _error("Not found.", HTTPStatus.NOT_FOUND)
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _error("Project not found.", HTTPStatus.NOT_FOUND)
    if request.method == "GET":
        records = list(JobRun.objects.filter(project=project).annotate(
            _cancel_requested=Exists(JobCancellation.objects.filter(job_id=OuterRef("pk")))
        ).order_by("-created_at", "-id")[:101])
        return _response({"jobs": [_job_payload(job) for job in records[:100]], "has_more": len(records) > 100})
    try:
        require_project_action(project=project, user=request.user, action=Action.LAUNCH_JOB)
        payload = _payload(request, {"handler", "input", "idempotency_key"}, {"handler", "input", "idempotency_key"})
        if payload["handler"] != "diagnostic_probe":
            raise ValidationError("Unsupported diagnostic handler.")
        job = queue_job(project=project, actor=request.user, handler="diagnostic_probe",
                        input_snapshot=payload["input"], idempotency_key=payload["idempotency_key"])
    except PermissionDenied:
        return _error("You cannot launch jobs for this project.", HTTPStatus.FORBIDDEN)
    except UsageLimitError as error:
        return _usage_error(error)
    except (ValidationError, IntegrityError, TypeError):
        return _error("Check the diagnostic input and idempotency key.")
    return _response({"job": _job_payload(job)}, HTTPStatus.ACCEPTED)


@require_http_methods(["GET"])
def job_detail(request, organization_id, project_id, job_id):
    if not settings.DEBUG:
        return _error("Not found.", HTTPStatus.NOT_FOUND)
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _error("Project not found.", HTTPStatus.NOT_FOUND)
    job = JobRun.objects.filter(pk=job_id, project=project).annotate(
        _cancel_requested=Exists(JobCancellation.objects.filter(job_id=OuterRef("pk")))
    ).first()
    if job is None:
        return _error("Job not found.", HTTPStatus.NOT_FOUND)
    return _response({"job": _job_payload(job, detailed=True)})


@require_http_methods(["POST"])
def job_cancel(request, organization_id, project_id, job_id):
    if not settings.DEBUG:
        return _error("Not found.", HTTPStatus.NOT_FOUND)
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _error("Project not found.", HTTPStatus.NOT_FOUND)
    job = JobRun.objects.filter(pk=job_id, project=project).first()
    if job is None:
        return _error("Job not found.", HTTPStatus.NOT_FOUND)
    try:
        _payload(request, set())
    except ValidationError:
        return _error("Check the cancellation request.")
    try:
        job, changed, requested = cancel_job(job=job, actor=request.user)
    except PermissionDenied:
        return _error("You cannot cancel this job.", HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _error("This job cannot be cancelled.", HTTPStatus.CONFLICT)
    return _response({"job": _job_payload(job), "cancelled": changed and not requested,
                      "cancel_requested": requested}, HTTPStatus.ACCEPTED if requested else HTTPStatus.OK)


@require_http_methods(["POST"])
def job_retry(request, organization_id, project_id, job_id):
    if not settings.DEBUG:
        return _error("Not found.", HTTPStatus.NOT_FOUND)
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _error("Project not found.", HTTPStatus.NOT_FOUND)
    job = JobRun.objects.filter(pk=job_id, project=project).first()
    if job is None:
        return _error("Job not found.", HTTPStatus.NOT_FOUND)
    try:
        payload = _payload(request, {"idempotency_key"}, {"idempotency_key"})
        retried = retry_job(job=job, actor=request.user, idempotency_key=payload["idempotency_key"])
    except PermissionDenied:
        return _error("You cannot retry this job.", HTTPStatus.FORBIDDEN)
    except UsageLimitError as error:
        return _usage_error(error)
    except (ValidationError, IntegrityError, TypeError):
        return _error("This job is not retryable or the idempotency key is invalid.", HTTPStatus.CONFLICT)
    return _response({"job": _job_payload(retried)}, HTTPStatus.ACCEPTED)


def _schedule_payload(schedule):
    return {
        "id": schedule.pk, "project_id": schedule.project_id, "enabled": schedule.enabled,
        "interval_minutes": schedule.interval_minutes,
        "next_run_at": schedule.next_run_at.isoformat() if schedule.next_run_at else None,
        "last_run_at": schedule.last_run_at.isoformat() if schedule.last_run_at else None,
        "skipped_occurrences": schedule.skipped_occurrences,
        "last_error_category": schedule.last_error_category,
    }


@require_http_methods(["GET", "POST"])
def schedules(request, organization_id, project_id):
    if not settings.DEBUG:
        return _error("Not found.", HTTPStatus.NOT_FOUND)
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _error("Project not found.", HTTPStatus.NOT_FOUND)
    if request.method == "GET":
        rows = list(JobSchedule.objects.filter(project=project, handler="diagnostic_probe").order_by("-created_at", "-id")[:101])
        return _response({"schedules": [_schedule_payload(row) for row in rows[:100]], "has_more": len(rows) > 100})
    try:
        payload = _payload(request, {"input", "interval_minutes", "idempotency_key"},
                           {"input", "interval_minutes", "idempotency_key"})
        if not isinstance(payload["idempotency_key"], str) or not payload["idempotency_key"]:
            raise ValidationError("A schedule idempotency key is required.")
        schedule = create_schedule(project=project, actor=request.user, input_snapshot=payload["input"],
                                   interval_minutes=payload["interval_minutes"], idempotency_key=payload["idempotency_key"])
    except PermissionDenied:
        return _error("You cannot schedule diagnostic work for this project.", HTTPStatus.FORBIDDEN)
    except (ValidationError, TypeError):
        return _error("Check the diagnostic input and schedule interval.")
    return _response({"schedule": _schedule_payload(schedule)}, HTTPStatus.CREATED)


@require_http_methods(["PATCH"])
def schedule_detail(request, organization_id, project_id, schedule_id):
    if not settings.DEBUG:
        return _error("Not found.", HTTPStatus.NOT_FOUND)
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _error("Project not found.", HTTPStatus.NOT_FOUND)
    schedule = JobSchedule.objects.filter(project=project, pk=schedule_id, handler="diagnostic_probe").first()
    if schedule is None:
        return _error("Schedule not found.", HTTPStatus.NOT_FOUND)
    try:
        payload = _payload(request, {"enabled"}, {"enabled"})
        schedule = set_schedule_enabled(schedule=schedule, actor=request.user, enabled=payload["enabled"])
    except PermissionDenied:
        return _error("You cannot change this schedule.", HTTPStatus.FORBIDDEN)
    except (ValidationError, TypeError):
        return _error("Choose a valid schedule state.")
    return _response({"schedule": _schedule_payload(schedule)})
