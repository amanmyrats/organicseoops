import json
from http import HTTPStatus

from allauth.core import ratelimit
from allauth.account import app_settings as account_settings
from allauth.core.internal import ratelimit as maintained_ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from kombu.exceptions import OperationalError

from .models import OrganizationNotice
from .notices import requeue_unknown_organization_notice
from .tasks import send_organization_notice_task
from integrations.google_tokens import _reject_constant, _unique_object
from .staff_notice_investigation import inspect_staff_notice, require_notice_staff, require_staff_notice_delivery
from accounts.staff_access import require_staff_permissions


def _response(payload, status=HTTPStatus.OK):
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


@require_http_methods(["GET"])
def platform_unknown_notices(request):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    if not request.user.is_staff or not request.user.has_perm("tenancy.view_organizationnotice"):
        return _response({"message": "Staff notice permission required."}, HTTPStatus.FORBIDDEN)
    return _response({"message": "Global notice discovery retired. Inspect one exact organization notice."}, HTTPStatus.GONE)


@sensitive_variables()
@sensitive_post_parameters()
def platform_inspect_notice(request):
    if request.method != "POST":
        response = _response({"message": "Use an explicit notice inspection POST."}, HTTPStatus.METHOD_NOT_ALLOWED)
        response["Allow"] = "POST"; return response
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    try:
        require_notice_staff(request)
        if request.GET or request.content_type != "application/json" or len(request.body) > 512:
            raise ValidationError("Exact bounded JSON required.")
        scope = json.loads(request.body, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        if type(scope) is not dict or set(scope) != {"organization_id", "notice_id", "reason"}:
            raise ValidationError("Exact scope required.")
        if maintained_ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True,
            action="staff_notice_access", user=request.user) is None:
            return _response({"message": "Too many notice investigations."}, HTTPStatus.TOO_MANY_REQUESTS)
        result = inspect_staff_notice(request=request, **scope)
        response = _response(result)
        require_staff_notice_delivery(request=request, organization_id=scope["organization_id"], original=result)
        return response
    except PermissionDenied:
        return _response({"message": "Current scoped notice access is unavailable."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, ValueError, TypeError, UnicodeError, RecursionError):
        return _response({"message": "Notice history needs review. Inspect the exact scope again."}, HTTPStatus.CONFLICT)


@require_http_methods(["POST"])
def platform_unknown_notice_retry(request, notice_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    try:
        actor = require_staff_permissions(request, permissions=("tenancy.change_organizationnotice",))
    except PermissionDenied:
        return _response({"message": "Staff notice permission required."}, HTTPStatus.FORBIDDEN)
    if not ratelimit.consume(request, action="platform_provider_secret", user=request.user):
        return _response({"message": "Too many notice changes."}, HTTPStatus.TOO_MANY_REQUESTS)
    notice = OrganizationNotice.objects.filter(pk=notice_id).first()
    if notice is None:
        return _response({"message": "Notice not found."}, HTTPStatus.NOT_FOUND)
    try:
        if len(request.body) > 512:
            raise ValueError
        data = json.loads(request.body)
        if type(data) is not dict or set(data) != {"reason", "acknowledge_possible_duplicate"} \
                or data["acknowledge_possible_duplicate"] is not True:
            raise ValueError
        requeue_unknown_organization_notice(notice=notice, actor=actor, reason=data["reason"], request=request)
    except PermissionDenied:
        return _response({"message": "Staff notice permission required."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, ValueError, TypeError, UnicodeError):
        return _response({"message": "Review current notice and possible duplicate delivery."}, HTTPStatus.CONFLICT)
    try:
        send_organization_notice_task.apply_async(
            args=[notice.pk], queue="default", task_id=f"organization-notice-{notice.pk}", retry=False,
        )
    except (OperationalError, OSError, TimeoutError):
        # Committed queued state survives a broker outage; hourly discovery will recover it.
        pass
    return _response({"queued": True, "possible_duplicate": True}, HTTPStatus.ACCEPTED)
