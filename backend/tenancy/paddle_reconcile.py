"""Pure, scoped provider identity checks before subscription or payment writes."""

import re
from datetime import datetime, timedelta

from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import (AuditEvent, AuditEventType, Organization, PaddleCheckoutAttempt,
                     PaddleStatus, PaddleSubscription, PaddleSubscriptionHistory, PaddleWebhookReceipt)
from .services import TRIAL_OFFER_VERSION


def parse_paid_checkout_transaction(*, attempt, response):
    """A provider GET alone is not payment authorization without a signed receipt."""
    if type(response) is not dict or type(response.get("data")) is not dict:
        raise ValidationError("Provider transaction is unavailable.")
    row = response["data"]
    transaction_id, customer_id, subscription_id = (row.get(key) for key in
                                                     ("id", "customer_id", "subscription_id"))
    items, custom_data = row.get("items"), row.get("custom_data")
    if (type(transaction_id) is not str or not re.fullmatch(r"txn_[a-z0-9]{26}", transaction_id)
        or type(customer_id) is not str or not re.fullmatch(r"ctm_[a-z0-9]{26}", customer_id)
        or (subscription_id is not None and
            (type(subscription_id) is not str or not re.fullmatch(r"sub_[a-z0-9]{26}", subscription_id)))
        or attempt.state not in {PaddleCheckoutAttempt.State.SENDING, PaddleCheckoutAttempt.State.READY,
                                 PaddleCheckoutAttempt.State.UNKNOWN}
        or (attempt.transaction_id and attempt.transaction_id != transaction_id)
        or row.get("status") not in {"paid", "completed"} or row.get("collection_mode") != "automatic"
        or row.get("origin") != "api" or type(row.get("currency_code")) is not str
        or not re.fullmatch(r"[A-Z]{3}", row["currency_code"])
        or type(custom_data) is not dict or custom_data.get("organization_id") != str(attempt.organization_id)
        or custom_data.get("checkout_attempt_id") != str(attempt.pk)
        or custom_data.get("offer_version") != TRIAL_OFFER_VERSION
        or type(items) is not list or len(items) != 1 or type(items[0]) is not dict
        or type(items[0].get("price")) is not dict or items[0]["price"].get("id") != attempt.price_id
        or items[0]["price"].get("product_id") != attempt.product_id
        or type(items[0].get("quantity")) is not int or items[0]["quantity"] != 1
        or type(items[0]["price"].get("billing_cycle")) is not dict
        or items[0]["price"]["billing_cycle"].get("interval") != "month"
        or type(items[0]["price"]["billing_cycle"].get("frequency")) is not int
        or items[0]["price"]["billing_cycle"]["frequency"] != 1
        or items[0]["price"].get("trial_period", False) is not None):
        raise ValidationError("Provider transaction does not match the authorized checkout.")
    return {"transaction_id": transaction_id, "customer_id": customer_id,
            "subscription_id": subscription_id or "", "currency_code": row["currency_code"]}


def _check_worker_claim(signed, worker_claim):
    if worker_claim is not None and (signed.state != signed.State.PROCESSING
        or (signed.attempts, signed.claimed_at) != worker_claim):
        raise ValidationError("Billing worker claim is no longer current.")


def _finish_worker_receipt(signed, worker_claim):
    if worker_claim is not None:
        _check_worker_claim(signed, worker_claim)
        signed.state = signed.State.SUCCEEDED
        signed.processed_at = timezone.now()
        signed.save(update_fields=["state", "processed_at"])


def _finish_subscription_observation(organization, attempt, signed, worker_claim, *, capture=True):
    _finish_worker_receipt(signed, worker_claim)
    if capture:
        from .paddle_activation import capture_first_active_observation
        capture_first_active_observation(organization=organization, attempt=attempt, receipt=signed,
                                         worker_confirmed=worker_claim is not None)


def record_paid_checkout_receipt(*, receipt, provider_response, worker_claim=None):
    """Called only after a signed receipt and authenticated current provider transaction GET."""
    row = provider_response.get("data") if type(provider_response) is dict else None
    custom = row.get("custom_data") if type(row) is dict else None
    candidate = custom.get("checkout_attempt_id") if type(custom) is dict else None
    if type(candidate) is not str or not re.fullmatch(r"[1-9][0-9]{0,17}", candidate):
        raise ValidationError("Provider checkout cannot be attributed to a local attempt.")
    attempt = PaddleCheckoutAttempt.objects.filter(pk=int(candidate), environment=receipt.environment).first()
    if attempt is None:
        raise ValidationError("Provider checkout cannot be attributed to a local attempt.")
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=attempt.organization_id)
        current = PaddleCheckoutAttempt.objects.select_for_update().get(pk=attempt.pk, organization=organization)
        signed = PaddleWebhookReceipt.objects.select_for_update().get(pk=receipt.pk)
        _check_worker_claim(signed, worker_claim)
        if (signed.environment != current.environment or signed.entity_id != row.get("id")
            or signed.event_type not in {"transaction.paid", "transaction.completed"}
            or signed.state not in {PaddleWebhookReceipt.State.PENDING, PaddleWebhookReceipt.State.PROCESSING,
                                     PaddleWebhookReceipt.State.SUCCEEDED}):
            raise ValidationError("Signed event cannot verify this payment.")
        parsed = parse_paid_checkout_transaction(attempt=current, response=provider_response)
        if current.paid_verified_at is not None:
            if ((current.transaction_id, current.paid_customer_id) !=
                (parsed["transaction_id"], parsed["customer_id"]) or current.paid_subscription_id not in
                {"", parsed["subscription_id"]}):
                raise ValidationError("Provider checkout identity changed.")
            if not current.paid_subscription_id and parsed["subscription_id"]:
                current.paid_subscription_id = parsed["subscription_id"]
                current.save(update_fields=["paid_subscription_id", "updated_at"])
            _finish_worker_receipt(signed, worker_claim)
            return current
        existing = PaddleSubscription.objects.filter(organization=organization).first()
        if existing and not (existing.status == PaddleStatus.CANCELED
            and existing.verified_at is not None and existing.canceled_at is not None
            and existing.canceled_at <= timezone.now() and existing.environment == current.environment
            and PaddleCheckoutAttempt.objects.filter(organization=organization,
                paid_customer_id=existing.customer_id, paid_subscription_id=existing.subscription_id,
                paid_verified_at__isnull=False, state=PaddleCheckoutAttempt.State.SETTLED).exists()):
            raise ValidationError("Another subscription is linked to this organization.")
        current.state = PaddleCheckoutAttempt.State.READY
        current.transaction_id = parsed["transaction_id"]
        current.paid_customer_id = parsed["customer_id"]
        current.paid_subscription_id = parsed["subscription_id"]
        current.paid_verified_at = timezone.now()
        current.save(update_fields=["state", "transaction_id", "paid_customer_id", "paid_subscription_id",
                                    "paid_verified_at", "updated_at"])
        AuditEvent.objects.create(organization=organization, actor=current.actor,
            event_type=AuditEventType.BILLING_PAYMENT_VERIFIED,
            details={"checkout_attempt_id": current.pk, "environment": current.environment,
                     "event_id": signed.event_id})
        waiting = PaddleWebhookReceipt.objects.select_for_update().filter(
            environment=current.environment, state=PaddleWebhookReceipt.State.FAILED,
            error_category="identity_review", received_at__gte=timezone.now() - timedelta(days=30),
            event_type__startswith="subscription.")
        if parsed["subscription_id"]:
            waiting = waiting.filter(entity_id=parsed["subscription_id"])
        for pending in waiting.order_by("pk")[:20]:
            pending.state = PaddleWebhookReceipt.State.PENDING
            pending.attempts = 0
            pending.claimed_at = pending.retry_after = pending.processed_at = None
            pending.error_category = ""
            pending.save(update_fields=["state", "attempts", "claimed_at", "retry_after", "processed_at", "error_category"])
        _finish_worker_receipt(signed, worker_claim)
        return current


def _provider_datetime(value, *, nullable=False):
    if nullable and value is None:
        return None
    if type(value) is not str or not 20 <= len(value) <= 40:
        raise ValidationError("Provider billing period is unavailable.")
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValidationError("Provider billing period is unavailable.") from None
    if timezone.is_naive(date):
        raise ValidationError("Provider billing period is unavailable.")
    return date


def parse_current_subscription(*, attempt, response):
    if type(response) is not dict or type(response.get("data")) is not dict:
        raise ValidationError("Provider subscription is unavailable.")
    row = response["data"]
    identity = row.get("custom_data")
    items = row.get("items")
    cycle = row.get("billing_cycle")
    status = row.get("status")
    sub_id = row.get("id")
    if (type(sub_id) is not str or not re.fullmatch(r"sub_[a-z0-9]{26}", sub_id)
        or (attempt.paid_subscription_id and attempt.paid_subscription_id != sub_id)
        or attempt.paid_verified_at is None or row.get("customer_id") != attempt.paid_customer_id
        or status not in PaddleStatus.values or row.get("collection_mode") != "automatic"
        or type(row.get("currency_code")) is not str or not re.fullmatch(r"[A-Z]{3}", row["currency_code"])
        or type(identity) is not dict or identity.get("organization_id") != str(attempt.organization_id)
        or identity.get("checkout_attempt_id") != str(attempt.pk)
        or identity.get("offer_version") != TRIAL_OFFER_VERSION
        or type(items) is not list or len(items) != 1 or type(items[0]) is not dict
        or type(items[0].get("price")) is not dict or items[0]["price"].get("id") != attempt.price_id
        or items[0]["price"].get("product_id") != attempt.product_id
        or type(items[0].get("quantity")) is not int or items[0]["quantity"] != 1
        or type(cycle) is not dict or cycle.get("interval") != "month"
        or type(cycle.get("frequency")) is not int or cycle["frequency"] != 1):
        raise ValidationError("Provider subscription does not match the paid checkout.")
    period = row.get("current_billing_period")
    if status in {PaddleStatus.ACTIVE, PaddleStatus.PAST_DUE}:
        if type(period) is not dict:
            raise ValidationError("Provider billing period is unavailable.")
        starts_at = _provider_datetime(period.get("starts_at"))
        ends_at = _provider_datetime(period.get("ends_at"))
        if not starts_at < ends_at:
            raise ValidationError("Provider billing period is unavailable.")
    else:
        starts_at = ends_at = None
    schedule = row.get("scheduled_change")
    if schedule is None:
        scheduled_cancel_at = None
    elif type(schedule) is dict and schedule.get("action") == "cancel":
        scheduled_cancel_at = _provider_datetime(schedule.get("effective_at"))
    else:
        scheduled_cancel_at = None
    canceled_at = _provider_datetime(row.get("canceled_at"), nullable=True)
    if status == PaddleStatus.CANCELED and canceled_at is None:
        raise ValidationError("Provider cancellation time is unavailable.")
    if status != PaddleStatus.CANCELED and canceled_at is not None:
        raise ValidationError("Provider subscription status conflicts with its cancellation time.")
    return {"subscription_id": sub_id, "customer_id": attempt.paid_customer_id,
            "status": status, "currency_code": row["currency_code"],
            "period_starts_at": starts_at, "period_ends_at": ends_at,
            "scheduled_cancel_at": scheduled_cancel_at, "canceled_at": canceled_at}


def _reconciled_usage_start(previous, fields, occurred_at):
    start = previous.grace_usage_starts_at
    if fields["status"] == PaddleStatus.PAST_DUE:
        if previous.status == PaddleStatus.PAST_DUE:
            return start
        if (previous.status == PaddleStatus.ACTIVE and previous.verified_at is not None
            and previous.period_starts_at is not None and previous.period_ends_at is not None
            and previous.period_starts_at <= occurred_at <= previous.period_ends_at + timedelta(days=7)
            and fields["period_starts_at"] is not None
            and previous.period_starts_at <= fields["period_starts_at"] <= previous.period_ends_at):
            return previous.period_starts_at
        return None
    if fields["status"] == PaddleStatus.ACTIVE and start:
        if previous.status == PaddleStatus.PAST_DUE and fields["period_starts_at"] > start:
            return start  # Recovery does not reset spent units in the failed monthly cycle.
        if previous.status == PaddleStatus.ACTIVE and fields["period_starts_at"] == previous.period_starts_at:
            return start
    return None


def record_current_subscription_receipt(*, receipt, provider_response, worker_claim=None):
    row = provider_response.get("data") if type(provider_response) is dict else None
    identity = row.get("custom_data") if type(row) is dict else None
    candidate = identity.get("checkout_attempt_id") if type(identity) is dict else None
    if type(candidate) is not str or not re.fullmatch(r"[1-9][0-9]{0,17}", candidate):
        raise ValidationError("Provider subscription lacks a paid checkout reference.")
    attempt = PaddleCheckoutAttempt.objects.filter(pk=int(candidate), environment=receipt.environment).first()
    if attempt is None:
        raise ValidationError("Provider subscription lacks a paid checkout reference.")
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=attempt.organization_id)
        current = PaddleCheckoutAttempt.objects.select_for_update().get(pk=attempt.pk, organization=organization)
        signed = PaddleWebhookReceipt.objects.select_for_update().get(pk=receipt.pk)
        _check_worker_claim(signed, worker_claim)
        if (signed.environment != current.environment or signed.entity_id != row.get("id")
            or not signed.event_type.startswith("subscription.")
            or signed.state not in {PaddleWebhookReceipt.State.PENDING, PaddleWebhookReceipt.State.PROCESSING,
                                     PaddleWebhookReceipt.State.SUCCEEDED}):
            raise ValidationError("Signed event cannot reconcile this subscription.")
        fields = parse_current_subscription(attempt=current, response=provider_response)
        existing = PaddleSubscription.objects.select_for_update().filter(organization=organization).first()
        replacing = bool(existing and (existing.environment, existing.customer_id, existing.subscription_id) != (
            current.environment, fields["customer_id"], fields["subscription_id"]))
        if replacing and not (existing.status == PaddleStatus.CANCELED and existing.verified_at is not None
            and existing.canceled_at is not None and existing.canceled_at <= timezone.now()
            and existing.environment == current.environment
            and PaddleCheckoutAttempt.objects.filter(organization=organization, state=PaddleCheckoutAttempt.State.SETTLED,
                paid_customer_id=existing.customer_id, paid_subscription_id=existing.subscription_id).exists()):
            raise ValidationError("Another subscription belongs to this organization.")
        if (PaddleSubscriptionHistory.objects.filter(environment=current.environment,
            customer_id=fields["customer_id"]).exclude(organization=organization).exists()
            or PaddleSubscriptionHistory.objects.filter(environment=current.environment,
                subscription_id=fields["subscription_id"]).exists()
            or PaddleSubscription.objects.filter(environment=current.environment,
                customer_id=fields["customer_id"]).exclude(organization=organization).exists()):
            raise ValidationError("Provider customer was owned by a different organization.")
        if existing and existing.status == PaddleStatus.CANCELED and not replacing:
            raise ValidationError("Canceled subscriptions require a new provider subscription ID.")
        if AuditEvent.objects.filter(organization=organization,
            event_type=AuditEventType.BILLING_SUBSCRIPTION_RECONCILED,
            details__event_id=signed.event_id).exists():
            _finish_subscription_observation(organization, current, signed, worker_claim, capture=False)
            return existing
        if existing is None:
            existing = PaddleSubscription(organization=organization, environment=current.environment,
                customer_id=fields["customer_id"], subscription_id=fields["subscription_id"])
        elif replacing:
            PaddleSubscriptionHistory.objects.create(organization=organization, environment=existing.environment,
                customer_id=existing.customer_id, subscription_id=existing.subscription_id,
                status=existing.status, verified_at=existing.verified_at, canceled_at=existing.canceled_at,
                refunded_at=existing.refunded_at, disputed_at=existing.disputed_at)
            existing.customer_id = fields["customer_id"]
            existing.subscription_id = fields["subscription_id"]
            existing.refunded_at = existing.disputed_at = None
        usage_start = _reconciled_usage_start(existing, fields, signed.occurred_at)
        for name in ("status", "currency_code", "period_starts_at", "period_ends_at",
                     "scheduled_cancel_at", "canceled_at"):
            setattr(existing, name, fields[name])
        existing.verified_at = timezone.now()
        existing.failed_at = (existing.failed_at if existing.status == PaddleStatus.PAST_DUE else None)
        existing.grace_usage_starts_at = usage_start
        existing.save()
        if not current.paid_subscription_id:
            current.paid_subscription_id = fields["subscription_id"]
            current.save(update_fields=["paid_subscription_id", "updated_at"])
        AuditEvent.objects.create(organization=organization, actor=current.actor,
            event_type=AuditEventType.BILLING_SUBSCRIPTION_RECONCILED,
            details={"event_id": signed.event_id, "environment": current.environment,
                      "subscription_id": fields["subscription_id"], "state": fields["status"]})
        _finish_subscription_observation(organization, current, signed, worker_claim)
        return existing


def record_renewal_transaction_receipt(*, receipt, transaction_response, subscription_response, worker_claim=None):
    """Signed renewal failure/recovery is reconciled against current transaction AND subscription."""
    row = transaction_response.get("data") if type(transaction_response) is dict else None
    if type(row) is not dict:
        raise ValidationError("Provider renewal transaction is unavailable.")
    sub_id, customer_id = row.get("subscription_id"), row.get("customer_id")
    if (row.get("id") != receipt.entity_id or receipt.event_type not in {
            "transaction.payment_failed", "transaction.past_due", "transaction.paid", "transaction.completed"}
        or row.get("origin") != "subscription_recurring" or row.get("collection_mode") != "automatic"
        or type(sub_id) is not str or not re.fullmatch(r"sub_[a-z0-9]{26}", sub_id)
        or type(customer_id) is not str or not re.fullmatch(r"ctm_[a-z0-9]{26}", customer_id)
        or (receipt.event_type in {"transaction.payment_failed", "transaction.past_due"}
            and row.get("status") not in {"past_due", "paid", "completed"})
        or (receipt.event_type in {"transaction.paid", "transaction.completed"}
            and row.get("status") not in {"paid", "completed"})):
        raise ValidationError("Provider renewal does not match the signed event.")
    linked = PaddleSubscription.objects.filter(environment=receipt.environment, subscription_id=sub_id,
                                               customer_id=customer_id).first()
    if linked is None:
        raise ValidationError("Renewal is not linked to a reconciled subscription.")
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=linked.organization_id)
        current = PaddleSubscription.objects.select_for_update().get(pk=linked.pk, organization=organization)
        signed = PaddleWebhookReceipt.objects.select_for_update().get(pk=receipt.pk)
        _check_worker_claim(signed, worker_claim)
        attempt = PaddleCheckoutAttempt.objects.select_for_update().filter(
            organization=organization, environment=current.environment, paid_verified_at__isnull=False,
            paid_customer_id=customer_id, paid_subscription_id=sub_id).first()
        if (signed.environment != current.environment or signed.entity_id != row["id"]
            or signed.event_type != receipt.event_type or signed.state not in {
                PaddleWebhookReceipt.State.PENDING, PaddleWebhookReceipt.State.PROCESSING,
                PaddleWebhookReceipt.State.SUCCEEDED}
            or attempt is None or current.verified_at is None):
            raise ValidationError("Signed renewal is not authorized for this organization.")
        items = row.get("items")
        if (type(items) is not list or len(items) != 1 or type(items[0]) is not dict
            or type(items[0].get("price")) is not dict
            or (items[0]["price"].get("id"), items[0]["price"].get("product_id")) !=
               (attempt.price_id, attempt.product_id)
            or type(items[0].get("quantity")) is not int or items[0]["quantity"] != 1):
            raise ValidationError("Renewal price does not match the accepted offer.")
        fields = parse_current_subscription(attempt=attempt, response=subscription_response)
        if ((fields["customer_id"], fields["subscription_id"]) != (customer_id, sub_id)
            or row.get("currency_code") != fields["currency_code"]):
            raise ValidationError("Renewal currency or identity changed.")
        if AuditEvent.objects.filter(organization=organization,
            event_type=AuditEventType.BILLING_SUBSCRIPTION_RECONCILED,
            details__event_id=signed.event_id).exists():
            _finish_subscription_observation(organization, attempt, signed, worker_claim, capture=False)
            return current
        usage_start = _reconciled_usage_start(current, fields, signed.occurred_at)
        for name in ("status", "currency_code", "period_starts_at", "period_ends_at",
                     "scheduled_cancel_at", "canceled_at"):
            setattr(current, name, fields[name])
        current.verified_at = timezone.now()
        if current.status == PaddleStatus.PAST_DUE and row.get("status") == "past_due" and signed.event_type in {
            "transaction.payment_failed", "transaction.past_due"}:
            current.failed_at = current.failed_at or signed.occurred_at
        elif current.status != PaddleStatus.PAST_DUE:
            current.failed_at = None
        current.grace_usage_starts_at = usage_start
        current.save()
        AuditEvent.objects.create(organization=organization, actor=attempt.actor,
            event_type=AuditEventType.BILLING_SUBSCRIPTION_RECONCILED,
            details={"event_id": signed.event_id, "environment": current.environment,
                      "subscription_id": sub_id, "state": current.status})
        _finish_subscription_observation(organization, attempt, signed, worker_claim)
        return current
