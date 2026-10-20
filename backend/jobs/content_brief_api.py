from http import HTTPStatus
import json

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.views.decorators.http import require_GET, require_http_methods
from config.artifacts import ArtifactStorageError

from tenancy.services import Action, require_project_action
from .ai_text_api import _project
from django.http import HttpResponse
from .content_brief import create_content_brief, read_content_brief, read_content_brief_bytes
from .models import ContentBriefSnapshot
from .research_api import _result


def _brief(brief):
    return {"id": brief.pk, "project_id": brief.project_id, "research_job_id": brief.research_job_id,
            "action_review_id": brief.action_review_id, "created_at": brief.created_at.isoformat(),
            "size_bytes": brief.size_bytes, "sha256": brief.content_sha256,
            "review_state": "draft_human_review_required_no_site_change"}


@require_http_methods(["GET", "POST"])
def project_content_briefs(request, organization_id, project_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _result({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _result({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user,
                               action=Action.LAUNCH_JOB if request.method == "POST" else Action.VIEW_PROJECT)
    except PermissionDenied:
        return _result({"message": "Brief access unavailable."}, HTTPStatus.FORBIDDEN)
    if request.method == "GET":
        rows = list(ContentBriefSnapshot.objects.filter(project=project).order_by("-pk")[:21])
        return _result({"project_id": project.pk, "briefs": [_brief(row) for row in rows[:20]],
                        "has_more": len(rows) > 20})
    if not ratelimit.consume(request, action="ai_text_request", user=request.user):
        return _result({"message": "Too many brief requests."}, HTTPStatus.TOO_MANY_REQUESTS)
    try:
        if len(request.body) > 16384:
            raise ValidationError("Choose bounded draft sections.")
        data = json.loads(request.body)
        required = {"request_key", "research_job_id", "action_id", "title_options", "angle", "outline", "questions"}
        if type(data) is not dict or not required <= set(data) or set(data) - required - {"meta_description", "desired_action"}:
            raise ValidationError("Choose exact draft fields.")
        brief = create_content_brief(project=project, actor=request.user, **data)
    except PermissionDenied:
        return _result({"message": "Brief source unavailable."}, HTTPStatus.NOT_FOUND)
    except ArtifactStorageError:
        return _result({"message": "Brief capture is busy or unavailable. Try again later."},
                       HTTPStatus.SERVICE_UNAVAILABLE)
    except (ValidationError, ValueError, TypeError, IntegrityError):
        return _result({"message": "Choose current accepted action and sourced research; review the draft content."},
                       HTTPStatus.CONFLICT)
    return _result({"project_id": project.pk, "brief": _brief(brief)}, HTTPStatus.CREATED)


@require_GET
def project_content_brief(request, organization_id, project_id, brief_id, download=False):
    if not request.user.is_authenticated or not request.user.is_active:
        return _result({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _result({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    brief = ContentBriefSnapshot.objects.filter(pk=brief_id, project=project).first()
    if brief is None:
        return _result({"message": "Private brief unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        body = (read_content_brief_bytes(project=project, actor=request.user, brief=brief) if download
                else read_content_brief(project=project, actor=request.user, brief=brief))
    except PermissionDenied:
        return _result({"message": "Private brief unavailable."}, HTTPStatus.NOT_FOUND)
    except ValidationError:
        return _result({"message": "Private brief integrity is unavailable."}, HTTPStatus.SERVICE_UNAVAILABLE)
    if download:
        response = HttpResponse(body, content_type="application/json")
        response["Content-Disposition"] = f'attachment; filename="project-{project.pk}-brief-{brief.pk}.json"'
        response["Cache-Control"] = "private, no-store"
        response["X-Robots-Tag"] = "noindex, nofollow"
        response["X-Content-Type-Options"] = "nosniff"
        response["Referrer-Policy"] = "no-referrer"
        response["Content-Security-Policy"] = "default-src 'none'"
        response["X-Content-SHA256"] = brief.content_sha256
        return response
    return _result({"project_id": project.pk, "brief": _brief(brief), "draft": body})
