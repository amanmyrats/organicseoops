from http import HTTPStatus

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.views.decorators.http import require_http_methods

from tenancy.services import Action, require_project_action

from .findings_api import _error, _payload, _project, _response
from .models import ActionTechnicalOutcomeSnapshot
from .technical_outcome import record_action_crawl_observations


def _serialize(snapshot):
    return {"id": snapshot.pk, "action_id": str(snapshot.action_review.action_id),
            "action_revision": snapshot.action_review.revision,
            "actor_id": snapshot.actor_id, "recorded_at": snapshot.created_at.isoformat(),
            "report": snapshot.report}


@require_http_methods(["GET", "POST"])
def project_action_technical_outcomes(request, organization_id, project_id, action_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _error("Project not found.", HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user,
            action=Action.MANAGE_PROJECT if request.method == "POST" else Action.VIEW_PROJECT)
    except PermissionDenied:
        return _error("Technical evidence is unavailable.", HTTPStatus.FORBIDDEN)
    if request.method == "GET":
        rows = list(ActionTechnicalOutcomeSnapshot.objects.filter(project=project, action_review__action_id=action_id)
                    .select_related("action_review").order_by("-action_review__revision")[:21])
        return _response({"project_id": project.pk, "snapshots": [_serialize(row) for row in rows[:20]],
                          "has_more": len(rows) > 20, "state": "recorded_crawl_observations" if rows else "not_checked"})
    if not ratelimit.consume(request, action="outcome_review", user=request.user):
        return _error("Too many outcome checks. Try again later.", HTTPStatus.TOO_MANY_REQUESTS)
    try:
        details = _payload(request, {"previous_crawl_id", "current_crawl_id"})
        if any(type(value) is not int or value < 1 for value in details.values()):
            raise ValidationError("Choose two bounded project crawl runs.")
        result = record_action_crawl_observations(project=project, actor=request.user,
                                                  action_id=action_id, **details)
    except PermissionDenied:
        return _error("Action or crawl source not found.", HTTPStatus.NOT_FOUND)
    except ValidationError:
        return _error("Comparable crawl observations are unavailable or changed.", HTTPStatus.CONFLICT)
    return _response({"project_id": project.pk, "snapshot": _serialize(result)}, HTTPStatus.CREATED)
