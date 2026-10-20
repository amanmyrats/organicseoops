"""Bounded current-provider reads for signed receipts; no payment POST or event-body replay."""

from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import PaddleCheckoutAttempt, PaddleEnvironment, PaddleSubscriptionHistory, PaddleWebhookReceipt
from .paddle_adjustments import record_current_adjustment_receipt
from .paddle_reconcile import (record_current_subscription_receipt, record_paid_checkout_receipt,
                               record_renewal_transaction_receipt)
from .paddle_seller import paddle_seller_secrets
from .paddle_transport import (PaddleTransportError, paddle_adjustment_get, paddle_subscription_get,
                               paddle_transaction_get)


def execute_paddle_receipt(receipt_id, *, transaction_get=None, subscription_get=None, adjustment_get=None):
    with transaction.atomic():
        receipt = PaddleWebhookReceipt.objects.select_for_update().filter(pk=receipt_id).first()
        if receipt is None or receipt.environment != settings.PADDLE_ENVIRONMENT:
            return "unavailable"
        if receipt.state in {receipt.State.SUCCEEDED, receipt.State.IGNORED, receipt.State.PROCESSING}:
            return receipt.state
        if (receipt.attempts >= 3 or receipt.state == receipt.State.FAILED and
            (receipt.retry_after is None or receipt.retry_after > timezone.now())):
            return receipt.state
        receipt.state = receipt.State.PROCESSING
        receipt.attempts += 1
        receipt.claimed_at = timezone.now()
        receipt.retry_after = None
        receipt.error_category = ""
        receipt.save(update_fields=["state", "attempts", "claimed_at", "retry_after", "error_category"])
    worker_claim = (receipt.attempts, receipt.claimed_at)
    try:
        api_key, _secret = paddle_seller_secrets(receipt.environment)
        if receipt.event_type.startswith("transaction."):
            if not PaddleCheckoutAttempt.objects.filter(environment=receipt.environment,
                transaction_id=receipt.entity_id, state=PaddleCheckoutAttempt.State.SETTLED).exists():
                provider = (transaction_get or paddle_transaction_get)(environment=receipt.environment,
                    transaction_id=receipt.entity_id, api_key=api_key)
                row = provider.get("data") if type(provider) is dict else None
                if type(row) is dict and row.get("origin") == "subscription_recurring":
                    sub_id = row.get("subscription_id")
                    if type(sub_id) is not str:
                        raise ValidationError("Renewal subscription ID is unavailable.")
                    if not PaddleSubscriptionHistory.objects.filter(environment=receipt.environment,
                                                                      subscription_id=sub_id).exists():
                        current_sub = (subscription_get or paddle_subscription_get)(environment=receipt.environment,
                            subscription_id=sub_id, api_key=api_key)
                        record_renewal_transaction_receipt(receipt=receipt, transaction_response=provider,
                                                           subscription_response=current_sub, worker_claim=worker_claim)
                elif receipt.event_type in {"transaction.paid", "transaction.completed"}:
                    record_paid_checkout_receipt(receipt=receipt, provider_response=provider, worker_claim=worker_claim)
                else:
                    raise ValidationError("Failed payment lacks a current recurring subscription.")
        elif receipt.event_type.startswith("subscription."):
            if not PaddleSubscriptionHistory.objects.filter(environment=receipt.environment,
                                                               subscription_id=receipt.entity_id).exists():
                provider = (subscription_get or paddle_subscription_get)(environment=receipt.environment,
                    subscription_id=receipt.entity_id, api_key=api_key)
                record_current_subscription_receipt(receipt=receipt, provider_response=provider, worker_claim=worker_claim)
        elif receipt.event_type in {"adjustment.created", "adjustment.updated"}:
            provider = (adjustment_get or paddle_adjustment_get)(environment=receipt.environment,
                adjustment_id=receipt.entity_id, api_key=api_key)
            record_current_adjustment_receipt(receipt=receipt, provider_response=provider, worker_claim=worker_claim)
        else:
            raise ValidationError("Billing event requires an independent reconciliation handler.")
    except (ValidationError, PaddleTransportError, TimeoutError, OSError) as error:
        category = (error.category if isinstance(error, PaddleTransportError)
                    else "identity_review" if isinstance(error, ValidationError) else "provider_unavailable")
        with transaction.atomic():
            current = PaddleWebhookReceipt.objects.select_for_update().get(pk=receipt.pk)
            if current.state != current.State.PROCESSING or (current.attempts, current.claimed_at) != worker_claim:
                return "unavailable"
            current.state = current.State.FAILED
            current.error_category = category if category in {"quota_limited", "provider_unavailable",
                "timeout", "network_error", "dns_error", "identity_review", "authorization_unavailable"} else "provider_unavailable"
            current.retry_after = (timezone.now() + timedelta(seconds=60 * current.attempts)
                                   if current.attempts < 3 and current.error_category != "authorization_unavailable"
                                   else None)
            current.save(update_fields=["state", "error_category", "retry_after"])
        return "failed"
    with transaction.atomic():
        current = PaddleWebhookReceipt.objects.select_for_update().get(pk=receipt.pk)
        if current.state == current.State.SUCCEEDED and (current.attempts, current.claimed_at) == worker_claim:
            return "succeeded"  # Subscription/payment reconciliation already committed success atomically.
        if current.state != current.State.PROCESSING or (current.attempts, current.claimed_at) != worker_claim:
            return "unavailable"
        current.state = current.State.SUCCEEDED
        current.processed_at = timezone.now()
        current.save(update_fields=["state", "processed_at"])
    return "succeeded"


def dispatch_paddle_receipt(receipt_id):
    from .tasks import reconcile_paddle_receipt_task

    reconcile_paddle_receipt_task.apply_async(args=[receipt_id], queue="default",
                                              task_id=f"paddle-receipt-{receipt_id}", retry=False)


def recover_paddle_receipts(*, limit=10):
    from .tasks import reconcile_paddle_receipt_task

    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValidationError("Choose a bounded billing recovery size.")
    if settings.PADDLE_ENVIRONMENT not in PaddleEnvironment.values:
        return 0
    now = timezone.now()
    waiting = list(PaddleWebhookReceipt.objects.filter(
        environment=settings.PADDLE_ENVIRONMENT, state=PaddleWebhookReceipt.State.PENDING,
        received_at__lte=now - timedelta(seconds=20)
    ).order_by("pk").values_list("pk", flat=True)[:limit])
    stale = list(PaddleWebhookReceipt.objects.filter(
        environment=settings.PADDLE_ENVIRONMENT, state=PaddleWebhookReceipt.State.PROCESSING,
        claimed_at__lte=now - timedelta(minutes=3)
    ).order_by("pk").values_list("pk", flat=True)[:limit])
    for pk in stale:
        with transaction.atomic():
            row = PaddleWebhookReceipt.objects.select_for_update().get(pk=pk)
            if row.state != row.State.PROCESSING or row.claimed_at > now - timedelta(minutes=3):
                continue
            row.state = row.State.FAILED
            row.error_category = "worker_lost"
            row.retry_after = now if row.attempts < 3 else None
            row.save(update_fields=["state", "error_category", "retry_after"])
    retry = list(PaddleWebhookReceipt.objects.filter(
        environment=settings.PADDLE_ENVIRONMENT, state=PaddleWebhookReceipt.State.FAILED,
        retry_after__lte=now, attempts__lt=3
    ).order_by("pk").values_list("pk", flat=True)[:limit])
    for pk in set(waiting + retry):
        reconcile_paddle_receipt_task.apply_async(args=[pk], queue="default",
                                                  task_id=f"paddle-receipt-{pk}", retry=False)
    return len(set(waiting + retry))
