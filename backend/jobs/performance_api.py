import json
from http import HTTPStatus

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from providers.performance_key import google_performance_key
from tenancy.models import Project
from tenancy.services import Action, require_project_action

from .models import JobRun, PerformanceObservationSnapshot
from .performance import compare_crux_history
from .performance_job import queue_performance_audit
from .services import cancel_job
from .usage import UsageLimitError


def _response(data, status=HTTPStatus.OK):
    response = JsonResponse(data, status=status)
    response["Cache-Control"] = "private, no-store"
    return response


def _error(message, status, *, code=None):
    error = {"message": message}
    if code:
        error["code"] = code
    return _response({"errors": [error]}, status)


def _project(request, organization_id, project_id):
    return Project.objects.for_user(request.user).filter(pk=project_id, organization_id=organization_id).first()


def _job_payload(job):
    return {"id": job.pk, "status": job.status, "error_category": job.error_category or job.dispatch_error,
            "target": job.input_snapshot["target"], "grain": job.input_snapshot["grain"],
            "strategy": job.input_snapshot["strategy"], "sources": job.input_snapshot["sources"],
            "requests_attempted": job.output.get("requests_attempted", 0),
            "sources_recorded": job.output.get("sources_recorded", 0),
            "lab": job.output.get("lab", "unavailable"), "field": job.output.get("field", "unavailable"),
            "coverage": job.output.get("coverage", "unknown"), "created_at": job.created_at.isoformat()}


def _available(project):
    try:
        google_performance_key(organization=project.organization)
        return True
    except ValidationError:
        return False


@require_http_methods(["GET", "POST"])
def project_performance_audits(request, organization_id, project_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _error("Project not found.", HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user,
                               action=Action.LAUNCH_JOB if request.method == "POST" else Action.VIEW_PROJECT)
    except PermissionDenied:
        return _error("Project performance evidence is unavailable.", HTTPStatus.FORBIDDEN)
    if request.method == "GET":
        jobs = list(JobRun.objects.filter(project=project, handler="audit_performance")
                    .order_by("-created_at", "-pk")[:21])
        return _response({"project_id": project.pk, "credential_available": _available(project),
                          "jobs": [_job_payload(job) for job in jobs[:20]], "has_more": len(jobs) > 20})
    if not ratelimit.consume(request, action="performance_audit", user=request.user):
        return _error("Performance audit requests are temporarily limited.", HTTPStatus.TOO_MANY_REQUESTS)
    try:
        if len(request.body) > 4096:
            raise ValidationError("Choose a bounded audit.")
        data = json.loads(request.body)
        if type(data) is not dict or set(data) != {"target", "grain", "strategy", "sources", "idempotency_key"}:
            raise ValidationError("Choose a bounded audit.")
        if not _available(project):
            return _error("A project-eligible performance key is not configured.", HTTPStatus.SERVICE_UNAVAILABLE)
        job = queue_performance_audit(project=project, actor=request.user, target=data["target"],
            grain=data["grain"], strategy=data["strategy"], sources=data["sources"],
            idempotency_key=data["idempotency_key"])
    except UsageLimitError as exc:
        return _error("Trial or internal audit capacity is unavailable.",
                      HTTPStatus.FORBIDDEN if exc.category == "trial_unavailable" else HTTPStatus.TOO_MANY_REQUESTS,
                      code=exc.category)
    except (PermissionDenied, ValidationError, TypeError, ValueError, UnicodeError, KeyError):
        return _error("Choose a current exact project target and bounded source selection.", HTTPStatus.CONFLICT)
    return _response({"project_id": project.pk, "job": _job_payload(job),
                      "max_requests": job.usage.reserved_units}, HTTPStatus.ACCEPTED)


def _job(request, organization_id, project_id, job_id, action):
    if not request.user.is_authenticated or not request.user.is_active:
        return None, _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return None, _error("Project not found.", HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=action)
    except PermissionDenied:
        return None, _error("Project performance evidence is unavailable.", HTTPStatus.FORBIDDEN)
    job = JobRun.objects.filter(pk=job_id, project=project, handler="audit_performance").first()
    if job is None:
        return None, _error("Audit not found.", HTTPStatus.NOT_FOUND)
    return job, None


@require_GET
def project_performance_audit_detail(request, organization_id, project_id, job_id):
    job, error = _job(request, organization_id, project_id, job_id, Action.VIEW_PROJECT)
    if error is not None:
        return error
    evidence = list(PerformanceObservationSnapshot.objects.filter(job=job, project=job.project).order_by("source")[:4])
    def parsed(item):
        if item.source != PerformanceObservationSnapshot.Source.CRUX_HISTORY:
            return item.output
        return {**item.output, "regressions": [compare_crux_history(item.output, metric)
                                                for metric in ("LCP", "INP", "CLS")]}
    return _response({"project_id": job.project_id, "job": _job_payload(job),
                      "observations": [{"id": item.pk, "source": item.source,
                                        "collected_at": item.collected_at.isoformat(), "result": parsed(item)}
                                       for item in evidence[:3]]})


@require_POST
def project_performance_audit_cancel(request, organization_id, project_id, job_id):
    job, error = _job(request, organization_id, project_id, job_id, Action.LAUNCH_JOB)
    if error is not None:
        return error
    try:
        if json.loads(request.body) != {}:
            raise ValidationError("Invalid cancellation request.")
        job, _changed, requested = cancel_job(job=job, actor=request.user)
    except (PermissionDenied, ValidationError, ValueError, TypeError, UnicodeError):
        return _error("This audit cannot be cancelled.", HTTPStatus.CONFLICT)
    return _response({"project_id": job.project_id, "job": _job_payload(job),
                      "cancel_requested": requested}, HTTPStatus.ACCEPTED if requested else HTTPStatus.OK)
