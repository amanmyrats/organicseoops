import json
from http import HTTPStatus

from allauth.core import ratelimit
from allauth.account import app_settings as account_settings
from allauth.core.internal import ratelimit as history_ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.views.decorators.debug import sensitive_post_parameters

from integrations.google_tokens import _reject_constant, _unique_object
from .findings_api import _project
from .first_audit_api import _response
from .summary_preferences import project_summary_preference, set_project_summary_preference
from .crux_alert_preferences import project_crux_alert_preference, set_project_crux_alert_preference


def project_summary_preferences(request, organization_id, project_id):
    return _project_preferences(request, organization_id, project_id, material_crux=False)


def project_crux_alert_preferences(request, organization_id, project_id):
    return _project_preferences(request, organization_id, project_id, material_crux=True)


@sensitive_post_parameters()
def _project_preferences(request, organization_id, project_id, *, material_crux):
    if request.method not in {"GET", "POST"}:
        response = _response({"message": "Use GET or POST for your own preference."}, HTTPStatus.METHOD_NOT_ALLOWED)
        response["Allow"] = "GET, POST"
        return response
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    if request.GET or not all(1 <= value < 2**53 for value in (organization_id, project_id)):
        return _response({"message": "Choose one exact project preference."}, HTTPStatus.BAD_REQUEST)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _response({"message": "Project not found."}, HTTPStatus.NOT_FOUND)
    allowed = (history_ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True,
                action="crux_preference_read" if material_crux else "summary_preference_read", user=request.user) is not None if request.method == "GET"
               else ratelimit.consume(request, action="crux_preference_write" if material_crux else "summary_preference_write", user=request.user))
    if not allowed:
        return _response({"message": "Too many preference requests."}, HTTPStatus.TOO_MANY_REQUESTS)
    try:
        if request.method == "GET":
            if request.body:
                raise ValidationError("No GET body.")
            reader = project_crux_alert_preference if material_crux else project_summary_preference
            preference = reader(project=project, actor=request.user)
        else:
            if len(request.body) > 1024:
                raise ValidationError("Bounded preference input required.")
            body = json.loads(request.body, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            if type(body) is not dict or set(body) != {"frequency", "expected_revision"}:
                raise ValidationError("Exact own preference fields required.")
            saver = set_project_crux_alert_preference if material_crux else set_project_summary_preference
            preference = saver(project=project, actor=request.user, **body)
    except PermissionDenied:
        return _response({"message": "Current project preference access is unavailable."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, ValueError, UnicodeError, TypeError, RecursionError):
        return _response({"message": "Preference not saved. Refresh your current project preference."}, HTTPStatus.CONFLICT)
    return _response({"project_id": project.pk, "preference": preference})
