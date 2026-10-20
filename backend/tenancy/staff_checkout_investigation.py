"""Exact retained checkout scalars, never payment/link/cancellation or replay authority."""
import hashlib
import json
import re

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.staff_access import require_staff_permissions
from .models import AuditEvent, AuditEventType, Organization, PaddleCheckoutAttempt, PaddleEnvironment
from .staff_subscription_investigation import _date
from .support_requests import _safe_id


METHOD = "exact-staff-retained-checkout-attempt-v1"
SCOPE = "recorded_checkout_attempt_not_current_paid_access_first_payment_cancellation_link_delivery_or_retry_authority"
REASONS = {"customer_request", "investigation"}
FIELDS = ("id", "organization_id", "actor_id", "environment", "offer_version", "product_id", "price_id",
          "request_key", "state", "transaction_id", "sent_at", "paid_verified_at", "paid_customer_id",
          "paid_subscription_id", "created_at", "updated_at")
DATES = ("created_at", "updated_at", "sent_at", "paid_verified_at")


def require_checkout_staff(request):
    return require_staff_permissions(request, permissions=("tenancy.view_organization", "tenancy.view_paddlecheckoutattempt"))


def _source(organization_id, attempt_id):
    attempt = PaddleCheckoutAttempt.objects.filter(pk=attempt_id, organization_id=organization_id).values(*FIELDS).first()
    organization = Organization.objects.filter(pk=organization_id).order_by("pk").values("id", "is_suspended", "closed_at", "created_at").first()
    if attempt is None or organization is None: raise PermissionDenied
    return {"attempt": attempt, "organization": organization}


def _record(source, assessed):
    row, org = source["attempt"], source["organization"]
    for identity in (row["id"], row["organization_id"], row["actor_id"], org["id"]): _safe_id(identity)
    if (row["organization_id"] != org["id"] or type(org["is_suspended"]) is not bool
        or not _date(org["created_at"]) or org["created_at"] > assessed
        or org["closed_at"] is not None and (not _date(org["closed_at"]) or not org["is_suspended"]
            or not org["created_at"] <= org["closed_at"] <= assessed)
        or row["environment"] not in PaddleEnvironment.values or row["state"] not in PaddleCheckoutAttempt.State.values
        or row["offer_version"] != "agency-launch-v1"
        or any(type(row[key]) is not str or not re.fullmatch(pattern, row[key]) for key, pattern in (
            ("product_id", r"pro_[a-z0-9]{26}"), ("price_id", r"pri_[a-z0-9]{26}"),
            ("request_key", r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}"), ("transaction_id", r"(?:txn_[a-z0-9]{26})?"),
            ("paid_customer_id", r"(?:ctm_[a-z0-9]{26})?"), ("paid_subscription_id", r"(?:sub_[a-z0-9]{26})?")))
        or any(not _date(row[key]) for key in ("created_at", "updated_at"))
        or any(row[key] is not None and not _date(row[key]) for key in ("sent_at", "paid_verified_at"))):
        raise ValidationError("Retained checkout attempt needs review.")
    state, sent, paid = (row[key] for key in ("state", "sent_at", "paid_verified_at"))
    if (not row["created_at"] <= row["updated_at"] <= assessed
        or sent is not None and not row["created_at"] <= sent <= assessed
        or paid is not None and (sent is None or not sent <= paid <= assessed)
        or state == "reserved" and sent is not None
        or state in {"sending", "unknown", "ready", "settled"} and sent is None
        or (state in {"ready", "settled"}) != bool(row["transaction_id"])
        or state == "settled" and paid is None
        or paid is None and (row["paid_customer_id"] or row["paid_subscription_id"])
        or paid is not None and (state not in {"ready", "settled"} or not row["paid_customer_id"])):
        raise ValidationError("Recorded checkout dates and state need review.")
    # Queryset closure rejection/partial saves need not advance updated_at; it is not a transition clock.
    return {"id": row["id"], "environment": row["environment"], "offer_version": row["offer_version"], "state": state,
            **{key: row[key].isoformat() if row[key] is not None else None for key in DATES}}


def _projection(organization_id, attempt_id):
    original = _source(organization_id, attempt_id)
    attempt = _record(original, timezone.now())
    digest = hashlib.sha256(json.dumps(original, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False).encode()).hexdigest()
    result = {"method_version": METHOD, "organization_id": organization_id, "scope": SCOPE,
              "attempt": attempt, "source_digest": digest}
    if _source(organization_id, attempt_id) != original:
        raise ValidationError("Retained checkout attempt changed during inspection.")
    return result


def require_staff_checkout_delivery(*, request, original):
    require_checkout_staff(request)
    if _projection(original["organization_id"], original["attempt"]["id"]) != original:
        raise ValidationError("Retained checkout attempt changed before delivery.")
    require_checkout_staff(request)


def inspect_staff_checkout(*, request, organization_id, attempt_id, reason):
    for identity in (organization_id, attempt_id): _safe_id(identity)
    if type(reason) is not str or reason not in REASONS:
        raise ValidationError("Choose a categorical checkout investigation reason.")
    actor = require_checkout_staff(request)
    with transaction.atomic():
        if not Organization.objects.select_for_update().filter(pk=organization_id).order_by("pk").values_list("pk", flat=True).first():
            raise PermissionDenied
        result = _projection(organization_id, attempt_id)
        AuditEvent.objects.create(organization_id=organization_id, actor=actor, event_type=AuditEventType.STAFF_CHECKOUT_INSPECTED,
            details={"attempt_id": attempt_id, "reason": reason, "state": result["attempt"]["state"]})
        require_staff_checkout_delivery(request=request, original=result)
        return result
