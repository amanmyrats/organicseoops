from http import HTTPStatus

from allauth.account import app_settings as account_settings
from allauth.core.internal import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError

from .health_source import integration_health_metadata
from .oauth_views import _project, _response


def project_integration_health(request, organization_id, project_id):
    if request.method != "GET":
        response = _response({"message": "Inspect integration metadata with GET."}, HTTPStatus.METHOD_NOT_ALLOWED)
        response["Allow"] = "GET"
        return response
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    if request.GET or request.body or not all(1 <= value < 2**53 for value in (organization_id, project_id)):
        return _response({"message": "Choose one exact project without additional input."}, HTTPStatus.BAD_REQUEST)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _response({"message": "Project integration metadata unavailable."}, HTTPStatus.NOT_FOUND)
    if ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True,
                         action="integration_health_read", user=request.user) is None:
        return _response({"message": "Too many integration inspections."}, HTTPStatus.TOO_MANY_REQUESTS)
    try:
        result = integration_health_metadata(project=project, actor=request.user)
    except PermissionDenied:
        return _response({"message": "Current project integration metadata unavailable."}, HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _response({"message": "Integration metadata needs review."}, HTTPStatus.CONFLICT)
    return _response(result)
