from http import HTTPStatus

from allauth.account import app_settings as account_settings
from allauth.core.internal import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError

from .alert_digest_history import own_daily_alert_delivery_history
from .findings_api import _project
from .first_audit_api import _response


def project_alert_deliveries(request, organization_id, project_id):
    return _history(request, organization_id, project_id, source=own_daily_alert_delivery_history,
                    action="alert_history_read")


def _history(request, organization_id, project_id, *, source, action):
    if request.method != "GET":
        response = _response({"message": "Inspect your own history with GET."}, HTTPStatus.METHOD_NOT_ALLOWED)
        response["Allow"] = "GET"
        return response
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    if request.GET or request.body or not all(1 <= value < 2**53 for value in (organization_id, project_id)):
        return _response({"message": "Choose one exact own project history without additional input."}, HTTPStatus.BAD_REQUEST)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _response({"message": "Project history unavailable."}, HTTPStatus.NOT_FOUND)
    if ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True,
                         action=action, user=request.user) is None:
        return _response({"message": "Too many own history inspections."}, HTTPStatus.TOO_MANY_REQUESTS)
    try:
        history = source(project=project, actor=request.user)
    except PermissionDenied:
        return _response({"message": "Current own project history unavailable."}, HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _response({"message": "Own transport history needs review."}, HTTPStatus.CONFLICT)
    return _response(history)
