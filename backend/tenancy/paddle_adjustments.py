"""Current provider adjustment scoped to an already reconciled subscription."""

from datetime import timedelta
import re

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (AuditEvent, AuditEventType, Organization, PaddleSubscription, PaddleSubscriptionHistory,
                     PaddleWebhookReceipt)
from .paddle_reconcile import _check_worker_claim, _finish_worker_receipt, _provider_datetime


def record_current_adjustment_receipt(*, receipt, provider_response, worker_claim):
    rows = provider_response.get("data") if type(provider_response) is dict else None
    meta = provider_response.get("meta") if type(provider_response) is dict else None
    pagination = meta.get("pagination") if type(meta) is dict else None
    if (type(rows) is not list or len(rows) != 1 or type(rows[0]) is not dict
        or type(pagination) is not dict or pagination.get("has_more") is not False):
        raise ValidationError("Provider adjustment coverage is incomplete.")
    row = rows[0]
    sub_id, customer_id, transaction_id = (row.get(key) for key in
                                           ("subscription_id", "customer_id", "transaction_id"))
    if (receipt.event_type not in {"adjustment.created", "adjustment.updated"}
        or row.get("id") != receipt.entity_id
        or type(sub_id) is not str or not re.fullmatch(r"sub_[a-z0-9]{26}", sub_id)
        or type(customer_id) is not str or not re.fullmatch(r"ctm_[a-z0-9]{26}", customer_id)
        or type(transaction_id) is not str or not re.fullmatch(r"txn_[a-z0-9]{26}", transaction_id)
        or row.get("action") not in {"refund", "chargeback", "chargeback_warning",
                                    "chargeback_reverse", "chargeback_warning_reverse"}
        or row.get("status") not in {"approved", "pending_approval", "rejected", "reversed"}
        or row.get("type") not in {"full", "partial"}):
        raise ValidationError("Provider adjustment does not match the signed event.")
    linked = PaddleSubscription.objects.filter(environment=receipt.environment, subscription_id=sub_id,
                                               customer_id=customer_id, verified_at__isnull=False).first()
    if linked is None:
        if PaddleSubscriptionHistory.objects.filter(environment=receipt.environment,
            subscription_id=sub_id, customer_id=customer_id).exists():
            return None
        raise ValidationError("Provider adjustment is not linked to verified billing.")
    timestamp = _provider_datetime(row.get("updated_at") if row["action"] == "refund" else row.get("created_at"))
    if timestamp > timezone.now() + timedelta(minutes=5):
        raise ValidationError("Provider adjustment time is invalid.")
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=linked.organization_id)
        current = PaddleSubscription.objects.select_for_update().get(pk=linked.pk, organization=organization)
        signed = PaddleWebhookReceipt.objects.select_for_update().get(pk=receipt.pk)
        _check_worker_claim(signed, worker_claim)
        if (signed.environment != current.environment or signed.entity_id != row["id"]
            or signed.event_type != receipt.event_type or signed.state not in {
                PaddleWebhookReceipt.State.PENDING, PaddleWebhookReceipt.State.PROCESSING,
                PaddleWebhookReceipt.State.SUCCEEDED}
            or (current.subscription_id, current.customer_id) != (sub_id, customer_id)):
            raise ValidationError("Adjustment billing identity changed.")
        if AuditEvent.objects.filter(organization=organization,
            event_type=AuditEventType.BILLING_ADJUSTMENT_REVIEWED,
            details__event_id=signed.event_id).exists():
            _finish_worker_receipt(signed, worker_claim)
            return current
        if row["action"] == "refund" and row["type"] == "full" and row["status"] == "approved":
            current.refunded_at = current.refunded_at or timestamp
            current.save(update_fields=["refunded_at"])
        elif row["action"] in {"chargeback", "chargeback_warning"} and row["status"] in {
            "approved", "pending_approval"}:
            current.disputed_at = current.disputed_at or timestamp
            current.save(update_fields=["disputed_at"])
        # Reversals and partial refunds need review; never silently restore costly work.
        AuditEvent.objects.create(organization=organization, actor=None,
            event_type=AuditEventType.BILLING_ADJUSTMENT_REVIEWED,
            details={"event_id": signed.event_id, "environment": current.environment,
                     "subscription_id": sub_id, "kind": row["action"], "state": row["status"],
                     "scope": row["type"]})
        _finish_worker_receipt(signed, worker_claim)
        return current
