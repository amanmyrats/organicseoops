from http import HTTPStatus

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.views.decorators.http import require_http_methods

from integrations.services import require_connection_capability
from tenancy.services import Action, require_project_action

from .findings_api import _error, _payload, _project, _response
from .models import ActionOutcomeSnapshot
from .outcome_comparison import record_page_outcome


def _result(project, outcome):
    try:
        require_connection_capability(outcome.connection, "page_metrics", dimensions=["page"])
        source_current = True
    except (PermissionDenied, ValidationError):
        source_current = False
    return {"id": outcome.pk, "action_id": str(outcome.action_review.action_id),
            "action_revision": outcome.action_review.revision,
            "source_current": source_current, "actor_id": outcome.actor_id,
            "recorded_at": outcome.created_at.isoformat(), "report": outcome.report}


@require_http_methods(["GET", "POST"])
def project_action_outcomes(request, organization_id, project_id, action_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _error("Project not found.", HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user,
            action=Action.MANAGE_PROJECT if request.method == "POST" else Action.VIEW_PROJECT)
    except PermissionDenied:
        return _error("Outcome evidence is unavailable.", HTTPStatus.FORBIDDEN)
    if request.method == "GET":
        rows = list(ActionOutcomeSnapshot.objects.filter(project=project, action_review__action_id=action_id)
                    .select_related("connection", "action_review").order_by("-action_review__revision")[:21])
        return _response({"project_id": project.pk, "outcomes": [_result(project, row) for row in rows[:20]],
                          "has_more": len(rows) > 20,
                          "state": "recorded_source_limited" if rows else "unavailable_no_comparison"})
    if not ratelimit.consume(request, action="outcome_review", user=request.user):
        return _error("Too many outcome requests. Try again later.", HTTPStatus.TOO_MANY_REQUESTS)
    try:
        details = _payload(request, {"connection_id", "previous_import_id", "current_import_id"})
        if any(type(value) is not int or value < 1 for value in details.values()):
            raise ValidationError("Choose complete project-owned CSV exports.")
        snapshot = record_page_outcome(project=project, actor=request.user,
                                       action_id=action_id, **details)
    except PermissionDenied:
        return _error("Action or source import is unavailable.", HTTPStatus.NOT_FOUND)
    except ValidationError:
        return _error("Compatible before/after evidence is unavailable or changed.", HTTPStatus.CONFLICT)
    return _response({"project_id": project.pk, "outcome": _result(project, snapshot)}, HTTPStatus.CREATED)
