from http import HTTPStatus

from allauth.account import app_settings as account_settings
from allauth.core.internal import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError

from .crux_history_source import current_crux_history_source
from .crux_threshold_policy import current_material_crux_source
from .findings_api import _project
from .first_audit_api import _response


def project_crux_history_source(request, organization_id, project_id, observation_id):
    return _project_crux_source(request, organization_id, project_id, observation_id, material_policy=False)


def project_material_crux_source(request, organization_id, project_id, observation_id):
    return _project_crux_source(request, organization_id, project_id, observation_id, material_policy=True)


def _project_crux_source(request, organization_id, project_id, observation_id, *, material_policy):
    if request.method != "GET":
        response = _response({"message": "Inspect original CrUX candidates with GET."}, HTTPStatus.METHOD_NOT_ALLOWED)
        response["Allow"] = "GET"
        return response
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    if request.GET or request.body or not all(1 <= value < 2**53 for value in (organization_id, project_id, observation_id)):
        return _response({"message": "Choose one exact project observation without additional input."}, HTTPStatus.BAD_REQUEST)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _response({"message": "Project source unavailable."}, HTTPStatus.NOT_FOUND)
    if ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True,
                         action="crux_threshold_policy_read" if material_policy else "crux_history_source_read",
                         user=request.user) is None:
        return _response({"message": "Too many source inspections."}, HTTPStatus.TOO_MANY_REQUESTS)
    try:
        reader = current_material_crux_source if material_policy else current_crux_history_source
        result = reader(project=project, actor=request.user, observation_id=observation_id)
    except PermissionDenied:
        return _response({"message": "Current project source unavailable."}, HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _response({"message": "Original source needs review."}, HTTPStatus.CONFLICT)
    return _response(result)
