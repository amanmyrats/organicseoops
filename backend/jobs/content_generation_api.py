from http import HTTPStatus

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.views.decorators.http import require_http_methods

from tenancy.services import Action, require_project_action
from .ai_text_api import _job as _ai_job, _payload, _project
from .content_generation import PLATFORMS, _context, queue_content_generation
from .models import JobRun
from .research_api import _result
from .services import cancel_job
from .usage import UsageLimitError


def _job(job):
    result = _ai_job(job)
    try:
        source_current = _context(job.project, job.actor, job.input_snapshot)[0] == job.config_snapshot.get("content_context")
    except (PermissionDenied, ValidationError, KeyError, TypeError):
        source_current = False
    return {**result, "brief_id": job.input_snapshot["brief_id"], "kind": job.input_snapshot["kind"],
        "platform": job.input_snapshot["platform"], "source_revision_id": job.input_snapshot["source_revision_id"],
        "estimate_units": 1, "source_current": source_current, "draft": job.output or None}


@require_http_methods(["GET", "POST"])
def project_content_generation(request, organization_id, project_id, job_id=None):
    if not request.user.is_authenticated or not request.user.is_active:
        return _result({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _result({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.VIEW_PROJECT)
    except PermissionDenied:
        return _result({"message": "Project content unavailable."}, HTTPStatus.FORBIDDEN)
    job = JobRun.objects.filter(pk=job_id, project=project, handler="generate_content").first() if job_id else None
    if job_id and job is None:
        return _result({"message": "Draft job unavailable."}, HTTPStatus.NOT_FOUND)
    if request.method == "POST":
        if not ratelimit.consume(request, action="ai_text_request", user=request.user):
            return _result({"message": "Too many draft requests."}, HTTPStatus.TOO_MANY_REQUESTS)
        try:
            if job:
                _payload(request, set())
                job, _changed, _pending = cancel_job(job=job, actor=request.user)
            else:
                data = _payload(request, {"brief_id", "source_revision_id", "kind", "platform", "model_id", "account_id",
                    "max_output_tokens", "max_cost_usd", "allow_free", "idempotency_key"})
                key = data.pop("idempotency_key")
                job = queue_content_generation(project=project, actor=request.user, data=data, idempotency_key=key)
        except PermissionDenied:
            return _result({"message": "Content source or role unavailable."}, HTTPStatus.FORBIDDEN)
        except UsageLimitError as error:
            return _result({"message": "Draft allowance unavailable.", "code": error.category}, HTTPStatus.TOO_MANY_REQUESTS)
        except (ValidationError, ValueError, TypeError, UnicodeError, IntegrityError):
            return _result({"message": "Choose exact-current evidence and a capable model with a bounded budget."}, HTTPStatus.CONFLICT)
        return _result({"project_id": project.pk, "job": _job(job)}, HTTPStatus.OK if job_id else HTTPStatus.ACCEPTED)
    if job:
        return _result({"project_id": project.pk, "job": _job(job)})
    rows = list(JobRun.objects.filter(project=project, handler="generate_content").order_by("-pk")[:21])
    return _result({"project_id": project.pk, "jobs": [_job(row) for row in rows[:20]], "has_more": len(rows) > 20,
        "platforms": list(PLATFORMS), "scope": "unverified_drafts_manual_export_only", "estimate_units": 1})
