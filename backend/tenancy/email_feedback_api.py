import json
from http import HTTPStatus

from allauth.core import ratelimit
from allauth.account import app_settings as account_settings
from allauth.core.internal import ratelimit as access_ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from accounts.staff_access import require_staff_permissions
from integrations.google_tokens import _reject_constant, _unique_object

from .email_feedback import clear_email_suppression
from .models import EmailSuppression
from .staff_feedback_investigation import inspect_staff_email_feedback, require_email_feedback_staff, require_staff_email_feedback_delivery


def _response(payload, status=HTTPStatus.OK):
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


@require_http_methods(["GET"])
def platform_email_suppressions(request):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    if not request.user.is_staff or not request.user.has_perm("tenancy.view_emailsuppression"):
        return _response({"message": "Staff email permission required."}, HTTPStatus.FORBIDDEN)
    return _response({"message": "Global suppression discovery is retired. Use explicit exact scoped investigation."}, HTTPStatus.GONE)


@sensitive_variables()
@sensitive_post_parameters()
def platform_inspect_email_feedback(request):
    if request.method != "POST":
        response = _response({"message": "Use an explicit feedback inspection POST."}, HTTPStatus.METHOD_NOT_ALLOWED)
        response["Allow"] = "POST"; return response
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    try:
        require_email_feedback_staff(request)
        if request.GET or request.content_type != "application/json" or len(request.body) > 512:
            raise ValidationError("Exact bounded JSON required.")
        scope = json.loads(request.body, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        if type(scope) is not dict or set(scope) != {"user_id", "email_address_id", "suppression_id", "reason"}:
            raise ValidationError("Exact scope required.")
        if access_ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True,
            action="staff_email_feedback_access", user=request.user) is None:
            return _response({"message": "Too many feedback investigations."}, HTTPStatus.TOO_MANY_REQUESTS)
        result = inspect_staff_email_feedback(request=request, **scope)
        response = _response(result)
        require_staff_email_feedback_delivery(request=request, original=result)
        return response
    except PermissionDenied:
        return _response({"message": "Current scoped feedback access is unavailable."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, ValueError, TypeError, UnicodeError, RecursionError):
        return _response({"message": "Retained feedback history needs review. Inspect the exact scope again."}, HTTPStatus.CONFLICT)


@require_http_methods(["POST"])
def platform_clear_email_suppression(request, suppression_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    try:
        actor = require_staff_permissions(request, permissions=("tenancy.delete_emailsuppression",))
    except PermissionDenied:
        return _response({"message": "Staff email permission required."}, HTTPStatus.FORBIDDEN)
    if not ratelimit.consume(request, action="platform_provider_secret", user=request.user):
        return _response({"message": "Too many email changes."}, HTTPStatus.TOO_MANY_REQUESTS)
    row = EmailSuppression.objects.filter(pk=suppression_id).first()
    if row is None:
        return _response({"message": "Suppression not found."}, HTTPStatus.NOT_FOUND)
    try:
        if len(request.body) > 512:
            raise ValueError
        data = json.loads(request.body)
        if type(data) is not dict or set(data) != {"reason", "confirm_review"} or data["confirm_review"] is not True:
            raise ValueError
        clear_email_suppression(suppression=row, actor=actor, reason=data["reason"], request=request)
    except PermissionDenied:
        return _response({"message": "Staff email permission required."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, ValueError, TypeError, UnicodeError):
        return _response({"message": "Review this address before clearing its suppression."}, HTTPStatus.CONFLICT)
    return _response({"cleared": True})
