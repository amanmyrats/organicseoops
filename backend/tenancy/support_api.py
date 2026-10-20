import json
from http import HTTPStatus

from allauth.account import app_settings as account_settings
from allauth.core.internal import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables

from integrations.google_tokens import _reject_constant, _unique_object
from jobs.findings_api import _project
from jobs.first_audit_api import _response
from .support_requests import create_support_request, own_support_requests


@sensitive_variables()
@sensitive_post_parameters()
def project_support_requests(request, organization_id, project_id, request_id=None):
    methods = {"GET"} if request_id is not None else {"GET", "POST"}
    if request.method not in methods:
        response = _response({"message": "Use the supported support request method."}, HTTPStatus.METHOD_NOT_ALLOWED)
        response["Allow"] = ", ".join(sorted(methods)); return response
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    if (request.GET or not all(1 <= value < 2**53 for value in (organization_id, project_id))
        or request_id is not None and not 1 <= request_id < 2**53):
        return _response({"message": "Choose one exact support scope."}, HTTPStatus.BAD_REQUEST)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _response({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    action = "support_request_read" if request.method == "GET" else "support_request_create"
    if ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True, action=action, user=request.user) is None:
        return _response({"message": "Too many support requests."}, HTTPStatus.TOO_MANY_REQUESTS)
    try:
        if request.method == "GET":
            if request.body: raise ValidationError("No GET body.")
            result = own_support_requests(project=project, actor=request.user, request_id=request_id)
        else:
            if request.content_type != "application/json" or len(request.body) > 16 * 1024:
                raise ValidationError("Bounded JSON required.")
            command = json.loads(request.body, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            if type(command) is not dict or type(command.get("expected_actor_id")) is not int:
                raise ValidationError("Exact current actor required.")
            if command.pop("expected_actor_id") != request.user.pk:
                raise PermissionDenied
            result = create_support_request(project=project, actor=request.user, command=command)
    except PermissionDenied:
        return _response({"message": "Current support access is unavailable."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, ValueError, UnicodeError, TypeError, RecursionError):
        return _response({"message": "Support request needs review. Refresh current history before any explicit retry."}, HTTPStatus.CONFLICT)
    return _response(result)
