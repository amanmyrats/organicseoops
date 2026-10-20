"""Public signed Paddle delivery boundary; no customer cookie is trusted here."""

from http import HTTPStatus

from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import PaddleEnvironment
from .paddle_seller import paddle_seller_secrets
from .paddle_webhooks import record_paddle_notification
from .paddle_jobs import dispatch_paddle_receipt
from django.db import transaction


def _response(status):
    response = JsonResponse({"accepted": status == HTTPStatus.OK}, status=status)
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


@csrf_exempt
@require_POST
def paddle_webhook(request, environment):
    if environment not in PaddleEnvironment.values or environment != settings.PADDLE_ENVIRONMENT:
        return _response(HTTPStatus.NOT_FOUND)
    if request.content_type != "application/json":
        return _response(HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
    try:
        paddle_seller_secrets(environment)
    except ValidationError:
        return _response(HTTPStatus.SERVICE_UNAVAILABLE)
    try:
        if int(request.META.get("CONTENT_LENGTH") or 0) > 64 * 1024:
            return _response(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        raw_body = request.read(64 * 1024 + 1)
        if not 1 <= len(raw_body) <= 64 * 1024:
            return _response(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        receipt, _created = record_paddle_notification(environment=environment, raw_body=raw_body,
                                   signature=request.headers.get("Paddle-Signature", ""))
        if _created and receipt.state == receipt.State.PENDING:
            transaction.on_commit(lambda: dispatch_paddle_receipt(receipt.pk))
    except (ValidationError, ValueError, TypeError, UnicodeError):
        return _response(HTTPStatus.BAD_REQUEST)
    # The unique receipt is committed. Processing/recovery never relies on this response alone.
    return _response(HTTPStatus.OK)
