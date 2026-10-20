import json
from http import HTTPStatus

from allauth.account import app_settings as account_settings
from allauth.core.internal import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables

from integrations.google_tokens import _reject_constant, _unique_object
from .staff_mail_investigation import inspect_staff_account_mail, require_account_mail_staff, require_staff_account_mail_delivery


def _response(payload, status=HTTPStatus.OK):
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


@sensitive_variables()
@sensitive_post_parameters()
def platform_inspect_account_mail(request):
    if request.method != "POST":
        response = _response({"message": "Use an explicit account-mail inspection POST."}, HTTPStatus.METHOD_NOT_ALLOWED)
        response["Allow"] = "POST"; return response
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    try:
        require_account_mail_staff(request)
        if request.GET or request.content_type != "application/json" or len(request.body) > 512:
            raise ValidationError("Exact bounded JSON required.")
        scope = json.loads(request.body, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        if type(scope) is not dict or set(scope) != {"user_id", "email_address_id", "delivery_id", "reason"}:
            raise ValidationError("Exact scope required.")
        if ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True,
            action="staff_account_mail_access", user=request.user) is None:
            return _response({"message": "Too many account-mail investigations."}, HTTPStatus.TOO_MANY_REQUESTS)
        result = inspect_staff_account_mail(request=request, **scope)
        response = _response(result)
        require_staff_account_mail_delivery(request=request, original=result)
        return response
    except PermissionDenied:
        return _response({"message": "Current scoped account-mail access is unavailable."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, ValueError, TypeError, UnicodeError, RecursionError):
        return _response({"message": "Account-mail history needs review. Inspect the exact scope again."}, HTTPStatus.CONFLICT)
