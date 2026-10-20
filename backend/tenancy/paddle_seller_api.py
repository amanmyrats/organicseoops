import json
from http import HTTPStatus

from allauth.core import ratelimit
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from accounts.staff_access import require_staff_permissions

from .models import PaddleEnvironment, PaddleSellerConfiguration, PaddleWebhookReceipt
from .paddle_jobs import dispatch_paddle_receipt
from .paddle_seller import revoke_paddle_seller, rotate_paddle_api_key, set_paddle_seller
from .paddle_webhooks import requeue_paddle_receipt


def _response(data, status=HTTPStatus.OK):
    response = JsonResponse(data, status=status)
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


@require_http_methods(["GET", "POST", "DELETE"])
def platform_paddle_seller(request, environment):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    if environment not in PaddleEnvironment.values:
        return _response({"message": "Seller environment not found."}, HTTPStatus.NOT_FOUND)
    record = PaddleSellerConfiguration.objects.filter(environment=environment).first()
    permission = ("tenancy.view_paddlesellerconfiguration" if request.method == "GET" else
                  "tenancy.change_paddlesellerconfiguration" if record or request.method == "DELETE" else
                  "tenancy.add_paddlesellerconfiguration")
    if not request.user.is_staff or not request.user.has_perm(permission):
        return _response({"message": "Staff seller permission required."}, HTTPStatus.FORBIDDEN)
    if request.method == "GET":
        return _response({"environment": environment, "state": record.state if record else "unconfigured",
                          "product_id": record.product_id if record else "",
                          "price_id": record.price_id if record else "",
                          "catalog_verified": False,
                          "client_token_configured": bool(record and record.state == record.State.ACTIVE and record.client_token)})
    if not ratelimit.consume(request, action="platform_provider_secret", user=request.user):
        return _response({"message": "Too many seller changes."}, HTTPStatus.TOO_MANY_REQUESTS)
    try:
        if request.method == "DELETE":
            return _response({"revoked": revoke_paddle_seller(actor=request.user, environment=environment)})
        if len(request.body) > 4096:
            raise ValueError
        data = json.loads(request.body)
        if type(data) is not dict or set(data) != {
            "api_key", "webhook_secret", "client_token", "product_id", "price_id", "currency", "amount", "interval", "frequency"
        }:
            raise ValueError
        set_paddle_seller(actor=request.user, environment=environment, **data)
    except PermissionDenied:
        return _response({"message": "Staff seller permission required."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, ValueError, TypeError, UnicodeError, IntegrityError):
        return _response({"message": "Check the seller catalog and encryption settings."}, HTTPStatus.CONFLICT)
    return _response({"configured": True, "catalog_verified": False})


@require_http_methods(["POST"])
def platform_paddle_api_key(request, environment):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    if environment not in PaddleEnvironment.values:
        return _response({"message": "Seller environment not found."}, HTTPStatus.NOT_FOUND)
    if not request.user.is_staff or not request.user.has_perm("tenancy.change_paddlesellerconfiguration"):
        return _response({"message": "Staff seller permission required."}, HTTPStatus.FORBIDDEN)
    if not ratelimit.consume(request, action="platform_provider_secret", user=request.user):
        return _response({"message": "Too many seller changes."}, HTTPStatus.TOO_MANY_REQUESTS)
    try:
        if len(request.body) > 1024:
            raise ValueError
        data = json.loads(request.body)
        if type(data) is not dict or set(data) != {"api_key"}:
            raise ValueError
        rotate_paddle_api_key(actor=request.user, environment=environment, api_key=data["api_key"])
    except PermissionDenied:
        return _response({"message": "Staff seller permission required."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, ValueError, TypeError, UnicodeError, IntegrityError):
        return _response({"message": "Seller API key rotation is unavailable."}, HTTPStatus.CONFLICT)
    return _response({"rotated": True})


def platform_paddle_receipt_retry(request, receipt_id):
    if request.method != "POST":
        response = _response({"message": "Use an explicit billing retry POST."}, HTTPStatus.METHOD_NOT_ALLOWED)
        response["Allow"] = "POST"
        return response
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    try:
        require_staff_permissions(request, permissions=("tenancy.change_paddlewebhookreceipt",))
    except PermissionDenied:
        return _response({"message": "Staff billing permission required."}, HTTPStatus.FORBIDDEN)
    if not ratelimit.consume(request, action="platform_provider_secret", user=request.user):
        return _response({"message": "Too many billing changes."}, HTTPStatus.TOO_MANY_REQUESTS)
    receipt = PaddleWebhookReceipt.objects.filter(pk=receipt_id, environment=settings.PADDLE_ENVIRONMENT).first()
    if receipt is None:
        return _response({"message": "Receipt not found."}, HTTPStatus.NOT_FOUND)
    try:
        if len(request.body) > 512:
            raise ValueError
        data = json.loads(request.body)
        if type(data) is not dict or set(data) != {"reason"}:
            raise ValueError
        with transaction.atomic():
            requeue_paddle_receipt(receipt=receipt, actor=request.user, reason=data["reason"], request=request)
            transaction.on_commit(lambda: dispatch_paddle_receipt(receipt.pk))
    except PermissionDenied:
        return _response({"message": "Staff billing permission required."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, ValueError, TypeError, UnicodeError):
        return _response({"message": "Receipt requires a billing status review."}, HTTPStatus.CONFLICT)
    return _response({"queued": True}, HTTPStatus.ACCEPTED)
