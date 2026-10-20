from datetime import datetime
from http import HTTPStatus

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.views.decorators.http import require_http_methods

from tenancy.services import Action, require_project_action

from .action_review import _opportunity_source, _source, record_action
from .findings_api import _error, _payload, _project, _response
from .models import ActionReview


def _project_access(request, organization_id, project_id, *, edit=False):
    if not request.user.is_authenticated or not request.user.is_active:
        return None, _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return None, _error("Project not found.", HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user,
                               action=Action.LAUNCH_JOB if edit else Action.VIEW_PROJECT)
    except PermissionDenied:
        return None, _error("Action history is unavailable.", HTTPStatus.FORBIDDEN)
    return project, None


def _serialize(project, actor, review):
    source_type = "intent" if review.intent_cluster_id else "opportunity"
    source_id = review.intent_cluster_id or review.opportunity_id
    try:
        if source_type == "intent":
            _source(project, source_id)
        else:
            _opportunity_source(project, actor, source_id, review.action_kind,
                                review.affected_urls[-1] if len(review.affected_urls) == 2
                                or review.action_kind == "create" else "")
        source_current = True
    except (PermissionDenied, ValidationError):
        source_current = False
    return {"action_id": str(review.action_id), "revision": review.revision,
            "source_type": source_type, "source_id": source_id, "source_current": source_current,
            "state": review.state, "action_kind": review.action_kind,
            "affected_urls": review.affected_urls, "assignee_id": review.assignee_id,
            "acceptance_criteria": review.acceptance_criteria, "reason": review.reason,
            "change_summary": review.change_summary, "verification_note": review.verification_note,
            "outcome_note": review.outcome_note,
            "implemented_at": review.implemented_at.isoformat() if review.implemented_at else None,
            "verified_at": review.verified_at.isoformat() if review.verified_at else None,
            "outcome_reviewed_at": review.outcome_reviewed_at.isoformat() if review.outcome_reviewed_at else None,
            "actor_id": review.actor_id, "recorded_at": review.created_at.isoformat(),
            "execution": "human_only_no_website_change"}


def _decision(request, project, *, action_id=None):
    if not ratelimit.consume(request, action="action_review", user=request.user):
        return _error("Too many action reviews. Try again later.", HTTPStatus.TOO_MANY_REQUESTS)
    keys = {"request_key", "source_type", "source_id", "state", "action_kind", "destination_page",
            "assignee_id", "acceptance_criteria", "reason", "implemented_at", "change_summary",
            "verification_note", "outcome_note"}
    if action_id:
        keys.add("expected_revision")
    try:
        data = _payload(request, keys)
        timestamp = data.pop("implemented_at")
        if timestamp is not None:
            if type(timestamp) is not str or len(timestamp) > 40:
                raise ValidationError("Use a UTC implementation timestamp.")
            try:
                timestamp = datetime.fromisoformat(timestamp)
            except ValueError:
                raise ValidationError("Use a UTC implementation timestamp.") from None
        review = record_action(project=project, actor=request.user, action_id=action_id,
                               implemented_at=timestamp, **data)
    except PermissionDenied:
        return _error("Action source or assignee is unavailable.", HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _error("Action revision, source or stage is unavailable; refresh first.", HTTPStatus.CONFLICT)
    return _response({"project_id": project.pk, "action": _serialize(project, request.user, review)},
                     HTTPStatus.CREATED if not action_id else HTTPStatus.OK)


@require_http_methods(["GET", "POST"])
def project_actions(request, organization_id, project_id):
    project, error = _project_access(request, organization_id, project_id, edit=request.method == "POST")
    if error:
        return error
    if request.method == "POST":
        return _decision(request, project)
    rows = list(ActionReview.objects.filter(project=project)
                .order_by("action_id", "-revision").distinct("action_id")[:51])
    return _response({"project_id": project.pk, "current_user_id": request.user.pk,
                      "actions": [_serialize(project, request.user, row) for row in rows[:50]],
                      "has_more": len(rows) > 50})


@require_http_methods(["GET", "POST"])
def project_action(request, organization_id, project_id, action_id):
    project, error = _project_access(request, organization_id, project_id, edit=request.method == "POST")
    if error:
        return error
    rows = ActionReview.objects.filter(project=project, action_id=action_id)
    if not rows.exists():
        return _error("Action not found.", HTTPStatus.NOT_FOUND)
    if request.method == "POST":
        return _decision(request, project, action_id=action_id)
    history = list(rows.order_by("-revision")[:21])
    return _response({"project_id": project.pk, "current_user_id": request.user.pk,
                      "history": [_serialize(project, request.user, row)
                                                       for row in history[:20]], "has_more": len(history) > 20})
