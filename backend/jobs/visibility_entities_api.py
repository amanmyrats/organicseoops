from http import HTTPStatus

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.views.decorators.http import require_http_methods

from tenancy.models import ProjectConfiguration
from tenancy.services import Action, require_project_action
from .ai_text_api import _payload, _project
from .models import AIVisibilityAnswerReview, JobRun
from .research_api import _result
from .visibility_collection import HANDLER
from .visibility_entities import METHOD, answer_for, candidates, entity_context, review_answer, sample_rates


def _review(row):
    return {"id": row.pk, "project_id": row.project_id, "job_id": row.job_id, "revision": row.revision,
        "answer_sha256": row.answer_sha256, "method": row.method_version, "context": row.context,
        "matches": row.matches, "evaluated": row.evaluated, "review_note": row.review_note,
        "factual_notes": row.factual_notes, "created_at": row.created_at.isoformat()}


@require_http_methods(["GET", "POST"])
def project_visibility_entities(request, organization_id, project_id, job_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _result({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _result({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.APPROVE if request.method == "POST" else Action.VIEW_PROJECT)
        job = JobRun.objects.filter(pk=job_id, project=project, handler=HANDLER).first()
        if job is None:
            return _result({"message": "Sample unavailable."}, HTTPStatus.NOT_FOUND)
        if request.method == "POST":
            if not ratelimit.consume(request, action="intent_review", user=request.user):
                return _result({"message": "Too many human reviews."}, HTTPStatus.TOO_MANY_REQUESTS)
            data = _payload(request, {"request_key", "expected_revision", "expected_configuration_revision", "matches", "evaluated", "review_note", "factual_notes"}, max_bytes=32768)
            review_answer(project=project, actor=request.user, job_id=job.pk, **data)
        config = ProjectConfiguration.objects.get(project=project)
        answer = answer_for(job)
        context = entity_context(job, config)
        history = list(AIVisibilityAnswerReview.objects.filter(project=project, job=job).order_by("-revision")[:21])
        return _result({"project_id": project.pk, "job_id": job.pk, "method": METHOD, "context": context,
            "candidates": candidates(answer, context), "history": [_review(row) for row in history[:20]], "history_has_more": len(history) > 20,
            "latest": _review(history[0]) if history else None,
            "collection_eligible": job.status == "succeeded" and job.output.get("collection_eligible") is True,
            "rates": sample_rates(project=project, actor=request.user, prompt_set_id=job.input_snapshot["prompt_set_id"])},
            HTTPStatus.CREATED if request.method == "POST" else HTTPStatus.OK)
    except PermissionDenied:
        return _result({"message": "Current project review role unavailable."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, ValueError, TypeError, UnicodeError, IntegrityError):
        return _result({"message": "Review exact collected answer spans, current entity context and latest correction; unsupported/partial answers cannot become valid negatives."}, HTTPStatus.CONFLICT)
