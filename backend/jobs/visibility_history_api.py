from http import HTTPStatus

from django.core.exceptions import PermissionDenied, ValidationError
from django.views.decorators.http import require_http_methods

from .ai_text_api import _project
from .research_api import _result
from .visibility_history import observation_history


@require_http_methods(["GET"])
def project_visibility_history(request, organization_id, project_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _result({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _result({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        if set(request.GET) - {"before"}:
            raise ValidationError("Unsupported history filter.")
        before = int(request.GET["before"]) if "before" in request.GET else None
        return _result(observation_history(project=project, actor=request.user, before_id=before))
    except PermissionDenied:
        return _result({"message": "Project history access unavailable."}, HTTPStatus.FORBIDDEN)
    except (ValueError, TypeError, ValidationError):
        return _result({"message": "Use the returned bounded history cursor."}, HTTPStatus.BAD_REQUEST)
