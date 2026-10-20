"""Retained GLOBAL signed-receipt state, never tenant, paid or retry authority."""
import hashlib
import json
import re
from datetime import datetime

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.staff_access import require_staff_permissions
from .models import AuditEvent, AuditEventType, PaddleEnvironment, PaddleWebhookReceipt
from .support_requests import _safe_id


METHOD = "exact-staff-retained-paddle-receipt-v1"
SCOPE = "retained_global_receipt_not_tenant_paid_truth_lifetime_attempts_or_retry_authority"
REASONS = {"customer_request", "investigation"}
FIELDS = ("id", "environment", "event_id", "notification_id", "event_type", "occurred_at", "entity_id",
          "subscription_id", "customer_id", "raw_digest", "state", "attempts", "error_category",
          "claimed_at", "retry_after", "received_at", "processed_at")
CATEGORIES = {"quota_limited", "provider_unavailable", "timeout", "network_error", "dns_error",
              "identity_review", "authorization_unavailable", "worker_lost"}


def require_receipt_staff(request):
    return require_staff_permissions(request, permissions=("tenancy.view_paddlewebhookreceipt",))


def _date(value):
    return isinstance(value, datetime) and not timezone.is_naive(value)


def _record(row, assessed):
    _safe_id(row["id"])
    for field, pattern in (("event_id", r"evt_[a-z0-9]{26}"), ("notification_id", r"ntf_[a-z0-9]{26}"),
            ("event_type", r"[a-z_]{3,24}\.[a-z_]{2,24}"), ("entity_id", r"[a-z_]{3,16}_[a-z0-9]{26}"),
            ("raw_digest", r"[a-f0-9]{64}")):
        if type(row[field]) is not str or not re.fullmatch(pattern, row[field]):
            raise ValidationError("Retained billing receipt needs review.")
    linked = row["subscription_id"], row["customer_id"]
    if (linked != ("", "") and any(type(value) is not str or not re.fullmatch(pattern, value)
            for value, pattern in zip(linked, (r"sub_[a-z0-9]{26}", r"ctm_[a-z0-9]{26}")))
        or any(row["event_type"].startswith(family + ".") and not row["entity_id"].startswith(prefix)
               for family, prefix in (("transaction", "txn_"), ("subscription", "sub_"), ("adjustment", "adj_")))
        or row["environment"] not in PaddleEnvironment.values
        or row["state"] not in PaddleWebhookReceipt.State.values
        or type(row["attempts"]) is not int or not 0 <= row["attempts"] <= 3
        or type(row["error_category"]) is not str or len(row["error_category"]) > 40
        or not _date(row["occurred_at"]) or not _date(row["received_at"]) or row["received_at"] > assessed):
        raise ValidationError("Retained billing receipt needs review.")
    state, claim, retry, processed = (row[key] for key in ("state", "claimed_at", "retry_after", "processed_at"))
    if (any(value is not None and not _date(value) for value in (claim, retry, processed))
        or state in {"pending", "ignored"} and (row["attempts"] != 0 or any(value is not None for value in (claim, retry, processed)) or row["error_category"])
        or state in {"processing", "failed", "succeeded"} and (row["attempts"] < 1 or claim is None)
        or claim is not None and not row["received_at"] <= claim <= assessed
        or state in {"processing", "succeeded"} and (retry is not None or row["error_category"])
        or state != "succeeded" and processed is not None
        or state == "succeeded" and (processed is None or not claim <= processed <= assessed)
        or retry is not None and (claim is None or retry < claim)):
        raise ValidationError("Retained billing receipt needs review.")
    category = (row["error_category"] if row["error_category"] in CATEGORIES else "unclassified_failure") if state == "failed" else None
    return {"id": row["id"], "environment": row["environment"], "state": state, "attempts": row["attempts"],
            "error_category": category, **{key: row[key].isoformat() if row[key] is not None else None
                for key in ("received_at", "claimed_at", "retry_after", "processed_at")}}


def _row(receipt_id):
    row = PaddleWebhookReceipt.objects.filter(pk=receipt_id).values(*FIELDS).first()
    if row is None:
        raise PermissionDenied
    return row


def _projection(receipt_id):
    original = _row(receipt_id)
    receipt = _record(original, timezone.now())
    digest = hashlib.sha256(json.dumps(original, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False).encode()).hexdigest()
    result = {"method_version": METHOD, "scope": SCOPE, "receipt": receipt, "source_digest": digest}
    if _row(receipt_id) != original:
        raise ValidationError("Retained billing receipt changed during inspection.")
    return result


def require_staff_receipt_delivery(*, request, original):
    require_receipt_staff(request)
    if _projection(original["receipt"]["id"]) != original:
        raise ValidationError("Retained billing receipt changed before delivery.")
    require_receipt_staff(request)


def inspect_staff_receipt(*, request, receipt_id, reason):
    _safe_id(receipt_id)
    if type(reason) is not str or reason not in REASONS:
        raise ValidationError("Choose a categorical billing investigation reason.")
    actor = require_receipt_staff(request)
    with transaction.atomic():
        if not PaddleWebhookReceipt.objects.select_for_update().filter(pk=receipt_id).values_list("pk", flat=True).first():
            raise PermissionDenied
        result = _projection(receipt_id)
        AuditEvent.objects.create(actor=actor, event_type=AuditEventType.STAFF_BILLING_RECEIPT_INSPECTED,
            details={"receipt_id": receipt_id, "reason": reason, "state": result["receipt"]["state"]})
        require_staff_receipt_delivery(request=request, original=result)
        return result
