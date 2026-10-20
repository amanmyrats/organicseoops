from http import HTTPStatus

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.views.decorators.http import require_http_methods

from tenancy.models import ProjectConfiguration
from tenancy.services import Action, require_project_action
from .ai_text_api import _payload, _project
from .intent_api import _serialize as serialize_intent
from .models import AIVisibilityPromptSet, IntentClusterReview
from .research_api import _result
from .visibility_prompts import METHOD, current_prompt_set, review_prompt_set


def _row(project, actor, row):
    try:
        current_prompt_set(project=project, actor=actor, row=row)
        current = True
    except (ValidationError, PermissionDenied):
        current = False
    return {"id": row.pk, "set_id": str(row.set_id), "revision": row.revision, "project_id": row.project_id,
        "label": row.label, "language": row.language, "market": row.market, "prompts": row.prompts,
        "context": row.context, "policy": row.policy, "review_note": row.review_note,
        "created_at": row.created_at.isoformat(), "source_current": current, "collection_available": True}


@require_http_methods(["GET", "POST"])
def project_visibility_prompts(request, organization_id, project_id, set_id=None):
    if not request.user.is_authenticated or not request.user.is_active:
        return _result({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _result({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user,
            action=Action.MANAGE_PROJECT if request.method == "POST" else Action.VIEW_PROJECT)
        if set_id and not AIVisibilityPromptSet.objects.filter(project=project, set_id=set_id).exists():
            return _result({"message": "Prompt set unavailable."}, HTTPStatus.NOT_FOUND)
        if request.method == "POST":
            if not ratelimit.consume(request, action="intent_review", user=request.user):
                return _result({"message": "Too many methodology reviews."}, HTTPStatus.TOO_MANY_REQUESTS)
            fields = {"request_key", "label", "language", "prompts", "review_note", "max_output_tokens", "max_cost_usd", "acknowledge_api_limits"}
            if set_id:
                fields.add("expected_revision")
            data = _payload(request, fields)
            row = review_prompt_set(project=project, actor=request.user, set_id=set_id, **data)
            return _result({"project_id": project.pk, "prompt_set": _row(project, request.user, row)}, HTTPStatus.CREATED)
        config = ProjectConfiguration.objects.filter(project=project).first()
        rows = AIVisibilityPromptSet.objects.filter(project=project)
        if set_id:
            selected = list(rows.filter(set_id=set_id).order_by("-revision")[:21])
        else:
            selected = list(rows.order_by("set_id", "-revision").distinct("set_id")[:21])
        mappings = list(IntentClusterReview.objects.filter(project=project).order_by("cluster_id", "-revision").distinct("cluster_id")[:50])
        return _result({"project_id": project.pk, "method": METHOD,
            "prompt_sets": [_row(project, request.user, row) for row in selected[:20]], "has_more": len(selected) > 20,
            "languages": config.target_languages if config else [], "brand_aliases": config.brand_aliases if config else [],
            "market": config.target_country if config else "",
            "intent_reviews": [serialize_intent(project, row) for row in mappings],
            "collection_available": True, "live_verified": False})
    except PermissionDenied:
        return _result({"message": "Current project role or intent source unavailable."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, ValueError, TypeError, UnicodeError, IntegrityError):
        return _result({"message": "Review bounded neutral/branded prompts, current intent coverage, API limits and latest revision."}, HTTPStatus.CONFLICT)
