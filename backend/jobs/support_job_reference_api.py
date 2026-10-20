from http import HTTPStatus

from allauth.account import app_settings as account_settings
from allauth.core.internal import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError

from .findings_api import _project
from .first_audit_api import _response
from .support_job_reference import retained_project_job_reference


def project_support_job_reference(request, organization_id, project_id, job_id):
    if request.method != "GET":
        response = _response({"message": "Inspect a retained project job reference with GET."}, HTTPStatus.METHOD_NOT_ALLOWED)
        response["Allow"] = "GET"
        return response
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    if request.GET or request.body or not all(1 <= value < 2**53 for value in (organization_id, project_id, job_id)):
        return _response({"message": "Choose one exact project job without additional input."}, HTTPStatus.BAD_REQUEST)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _response({"message": "Project reference unavailable."}, HTTPStatus.NOT_FOUND)
    if ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True,
                         action="support_job_reference_read", user=request.user) is None:
        return _response({"message": "Too many reference inspections."}, HTTPStatus.TOO_MANY_REQUESTS)
    try:
        result = retained_project_job_reference(project=project, actor=request.user, job_id=job_id)
    except PermissionDenied:
        return _response({"message": "Current project reference unavailable."}, HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _response({"message": "Retained job reference needs review."}, HTTPStatus.CONFLICT)
    return _response(result)
