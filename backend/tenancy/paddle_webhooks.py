"""Paddle Billing raw-body signature and bounded event identity validation."""

import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta, timezone as utc_timezone

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from integrations.search_console_transport import _reject_constant, _unique_object
from accounts.staff_access import require_staff_permissions

from .models import AuditEvent, AuditEventType, PaddleEnvironment, PaddleWebhookReceipt
from .paddle_seller import paddle_seller_secrets


SUPPORTED_EVENTS = frozenset({
    "transaction.paid", "transaction.completed", "transaction.payment_failed", "transaction.past_due",
    "subscription.created", "subscription.activated", "subscription.updated", "subscription.past_due",
    "subscription.canceled", "subscription.paused", "subscription.resumed",
    "adjustment.created", "adjustment.updated",
})


def verify_paddle_webhook(*, raw_body, signature, secret, now=None):
    """Verify exact received bytes before JSON parsing. No provider content enters exceptions."""
    if (type(raw_body) is not bytes or not 1 <= len(raw_body) <= 64 * 1024
        or type(signature) is not str or not 1 <= len(signature) <= 512
        or type(secret) is not str or not 16 <= len(secret) <= 512):
        raise ValidationError("Invalid Paddle notification.")
    parts = signature.split(";")
    timestamp = None
    signatures = []
    for part in parts:
        key, separator, value = part.partition("=")
        if not separator or (key == "ts" and timestamp is not None):
            raise ValidationError("Invalid Paddle notification.")
        if key == "ts":
            if not re.fullmatch(r"[0-9]{9,11}", value):
                raise ValidationError("Invalid Paddle notification.")
            timestamp = value
        elif key == "h1":
            if not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValidationError("Invalid Paddle notification.")
            signatures.append(value)
        else:
            raise ValidationError("Invalid Paddle notification.")
    if timestamp is None or not 1 <= len(signatures) <= 4:
        raise ValidationError("Invalid Paddle notification.")
    now = now or timezone.now()
    if timezone.is_naive(now) or abs(int(now.timestamp()) - int(timestamp)) > 5:
        raise ValidationError("Invalid Paddle notification.")
    expected = hmac.new(secret.encode(), timestamp.encode() + b":" + raw_body, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, signed) for signed in signatures):
        raise ValidationError("Invalid Paddle notification.")
    try:
        data = json.loads(raw_body, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
        if type(data) is not dict or type(data.get("data")) is not dict:
            raise ValueError
        event_id, notification_id, event_type = (data.get(key) for key in
                                                 ("event_id", "notification_id", "event_type"))
        if (type(event_id) is not str or not re.fullmatch(r"evt_[a-z0-9]{26}", event_id)
            or type(notification_id) is not str or not re.fullmatch(r"ntf_[a-z0-9]{26}", notification_id)
            or type(event_type) is not str or not re.fullmatch(r"[a-z_]{3,24}\.[a-z_]{2,24}", event_type)):
            raise ValueError
        occurred_text = data["occurred_at"]
        if type(occurred_text) is not str or not 20 <= len(occurred_text) <= 40:
            raise ValueError
        occurred_at = datetime.fromisoformat(occurred_text.replace("Z", "+00:00"))
        entity_id = data["data"].get("id")
        subscription_id = data["data"].get("subscription_id")
        customer_id = data["data"].get("customer_id")
        if subscription_id is None and customer_id is None:
            subscription_id = customer_id = ""
        if (timezone.is_naive(occurred_at) or occurred_at > now + timedelta(minutes=5)
            or type(entity_id) is not str or not re.fullmatch(r"[a-z_]{3,16}_[a-z0-9]{26}", entity_id)
            or (event_type.startswith("transaction.") and not entity_id.startswith("txn_"))
            or (event_type.startswith("subscription.") and not entity_id.startswith("sub_"))
            or (event_type.startswith("adjustment.") and not entity_id.startswith("adj_"))):
            raise ValueError
        if (subscription_id, customer_id) != ("", "") and (
            type(subscription_id) is not str or not re.fullmatch(r"sub_[a-z0-9]{26}", subscription_id)
            or type(customer_id) is not str or not re.fullmatch(r"ctm_[a-z0-9]{26}", customer_id)):
            raise ValueError
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        raise ValidationError("Invalid Paddle notification.") from None
    return {"event_id": event_id, "notification_id": notification_id,
            "event_type": event_type, "occurred_at": occurred_at.astimezone(utc_timezone.utc),
            "entity_id": entity_id, "raw_digest": hashlib.sha256(raw_body).hexdigest(),
            "subscription_id": subscription_id, "customer_id": customer_id,
            "state": (PaddleWebhookReceipt.State.PENDING if event_type in SUPPORTED_EVENTS
                       else PaddleWebhookReceipt.State.IGNORED)}


def record_paddle_notification(*, environment, raw_body, signature, now=None):
    if environment not in PaddleEnvironment.values:
        raise ValidationError("Invalid Paddle environment.")
    _api_key, webhook_secret = paddle_seller_secrets(environment)
    event = verify_paddle_webhook(raw_body=raw_body, signature=signature,
                                  secret=webhook_secret, now=now)
    try:
        with transaction.atomic():
            receipt = PaddleWebhookReceipt.objects.select_for_update().filter(
                environment=environment, event_id=event["event_id"]).first()
            if receipt is None:
                return PaddleWebhookReceipt.objects.create(environment=environment, **event), True
    except IntegrityError:
        # Concurrent delivery of the same event must converge on the unique receipt.
        receipt = PaddleWebhookReceipt.objects.get(environment=environment, event_id=event["event_id"])
    if receipt.raw_digest != event["raw_digest"]:
        raise ValidationError("Conflicting Paddle event identifier.")
    return receipt, False


RETRY_IDENTITY_FIELDS = ("environment", "event_id", "notification_id", "event_type", "occurred_at",
    "entity_id", "subscription_id", "customer_id", "raw_digest", "received_at")
RETRY_FIELDS = ("id", *RETRY_IDENTITY_FIELDS, "state", "attempts", "error_category", "claimed_at", "retry_after", "processed_at")
RETRY_RESET = {"state": PaddleWebhookReceipt.State.PENDING, "attempts": 0, "claimed_at": None,
               "retry_after": None, "processed_at": None, "error_category": ""}


def _require_receipt_retry_delivery(*, request, actor, expected):
    if require_staff_permissions(request, permissions=("tenancy.change_paddlewebhookreceipt",)).pk != actor.pk:
        raise PermissionDenied
    now = timezone.now()
    if (PaddleWebhookReceipt.objects.filter(pk=expected["id"]).values(*RETRY_FIELDS).first() != expected
        or settings.PADDLE_ENVIRONMENT != expected["environment"]
        or not now - timedelta(days=30) <= expected["received_at"] <= now):
        raise ValidationError("Billing receipt changed during retry.")
    if require_staff_permissions(request, permissions=("tenancy.change_paddlewebhookreceipt",)).pk != actor.pk:
        raise PermissionDenied


def requeue_paddle_receipt(*, receipt, actor, reason, request):
    """Explicit staff-only recovery after provider uncertainty, without replaying webhook bytes."""
    if type(reason) is not str or not 1 <= len(reason.strip()) <= 250:
        raise ValidationError("Provide a bounded reconciliation reason.")
    with transaction.atomic():
        current_actor = require_staff_permissions(request, permissions=("tenancy.change_paddlewebhookreceipt",))
        if current_actor.pk != actor.pk:
            raise PermissionDenied
        current = PaddleWebhookReceipt.objects.select_for_update().get(pk=receipt.pk)
        expected = {field: getattr(current, field) for field in RETRY_FIELDS}
        now = timezone.now()
        if (current.state != PaddleWebhookReceipt.State.FAILED
            or not now - timedelta(days=30) <= current.received_at <= now
            or current.environment not in PaddleEnvironment.values
            or current.environment != settings.PADDLE_ENVIRONMENT
            or any(getattr(current, field) != getattr(receipt, field) for field in RETRY_IDENTITY_FIELDS)):
            raise ValidationError("Billing receipt is not eligible for retry.")
        for field, value in RETRY_RESET.items(): setattr(current, field, value)
        current.save(update_fields=list(RETRY_RESET))
        expected.update(RETRY_RESET)
        AuditEvent.objects.create(actor=current_actor, event_type=AuditEventType.BILLING_RECONCILIATION_RETRY,
            details={"environment": current.environment, "receipt_id": current.pk, "reason": reason.strip()})
        _require_receipt_retry_delivery(request=request, actor=current_actor, expected=expected)
    return current
