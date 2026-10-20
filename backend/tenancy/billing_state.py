"""Deterministic access projection; only reconciled provider records may count as paid."""

from datetime import timedelta

from django.utils import timezone

from .models import PaddleStatus, PaddleWebhookReceipt


def paid_access_state(subscription, *, now=None):
    """UI/policy state, never proof that a fixture identity was verified by Paddle."""
    if subscription is None or subscription.verified_at is None:
        return "unverified"
    now = now or timezone.now()
    if (timezone.is_naive(subscription.verified_at) or subscription.verified_at > now
        or not isinstance(subscription.currency_code, str) or len(subscription.currency_code) != 3):
        return "unavailable"
    if (getattr(subscription, "organization_id", None) is not None
        and PaddleWebhookReceipt.objects.filter(
            environment=subscription.environment, subscription_id=subscription.subscription_id,
            customer_id=subscription.customer_id,
            event_type__in=["transaction.payment_failed", "transaction.past_due",
                            "adjustment.created", "adjustment.updated"],
            state__in=[PaddleWebhookReceipt.State.PENDING, PaddleWebhookReceipt.State.PROCESSING,
                       PaddleWebhookReceipt.State.FAILED]).exists()):
        return "billing_review_hold"
    refund = getattr(subscription, "refunded_at", None)
    dispute = getattr(subscription, "disputed_at", None)
    if refund is not None:
        return ("retained_read_only" if timezone.is_aware(refund) and refund <= now < refund + timedelta(days=90)
                else "retention_elapsed")
    if dispute is not None:
        return "read_only"
    if subscription.status == PaddleStatus.CANCELED:
        return ("retained_read_only" if subscription.canceled_at is not None
                and timezone.is_aware(subscription.canceled_at)
                and subscription.canceled_at <= now < subscription.canceled_at + timedelta(days=90)
                else "retention_elapsed")
    if subscription.status in {PaddleStatus.PAUSED, PaddleStatus.TRIALING}:
        return "read_only"
    start, end = subscription.period_starts_at, subscription.period_ends_at
    if not start or not end or timezone.is_naive(start) or timezone.is_naive(end) or not start < end:
        return "unavailable"
    if subscription.status == PaddleStatus.ACTIVE:
        if subscription.failed_at is not None or not start <= now < end:
            return "read_only"
        cancel = subscription.scheduled_cancel_at
        if cancel is not None:
            if timezone.is_naive(cancel) or not now < cancel <= end:
                return "read_only"
            return "cancellation_scheduled"
        return "paid_active"
    if subscription.status == PaddleStatus.PAST_DUE:
        failure = subscription.failed_at
        grace_start = getattr(subscription, "grace_usage_starts_at", None)
        if (failure is None or timezone.is_naive(failure) or failure > subscription.verified_at
            or grace_start is None or timezone.is_naive(grace_start) or grace_start > failure
            or subscription.scheduled_cancel_at is not None):
            return "read_only"
        return "payment_grace" if failure <= now < failure + timedelta(days=7) else "read_only"
    return "unavailable"


def paid_work_available(subscription, *, now=None):
    return paid_access_state(subscription, now=now) in {"paid_active", "cancellation_scheduled", "payment_grace"}
