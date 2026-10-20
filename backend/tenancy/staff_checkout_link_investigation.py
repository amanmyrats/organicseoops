"""Retained original browser acknowledgment, never current capture or payment authority."""
import hashlib
import json
import re
from urllib.parse import urlsplit

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from accounts.staff_access import require_staff_permissions
from .models import AuditEvent, AuditEventType, Organization, PaddleCheckoutLinkReceipt, PaddleEnvironment
from .paddle_checkout_delivery import checkout_source_digest
from .staff_subscription_investigation import _date
from .support_requests import _safe_id


METHOD = "exact-staff-retained-checkout-link-v1"
SCOPE = "recorded_browser_acknowledgment_not_provider_page_payment_first_conversion_current_link_or_retry_authority"
REASONS = {"customer_request", "investigation"}
FIELDS = ("id", "attempt_id", "actor_id", "source", "source_digest", "acknowledged_at")
SOURCE_FIELDS = {"method", "organization_id", "actor_id", "attempt_id", "request_actor_id", "environment",
    "offer_version", "product_id", "price_id", "transaction_id", "created_at", "sent_at", "seller_id",
    "seller_rotated_at", "checkout_url", "payment_confirmed", "interpretation"}


def require_checkout_link_staff(request):
    return require_staff_permissions(request, permissions=("tenancy.view_organization", "tenancy.view_paddlecheckoutlinkreceipt"))


def _source(organization_id, receipt_id):
    row = PaddleCheckoutLinkReceipt.objects.filter(pk=receipt_id, attempt__organization_id=organization_id).values(
        *FIELDS, "attempt__id", "attempt__organization_id").first()
    org = Organization.objects.filter(pk=organization_id).order_by("pk").values("id", "is_suspended", "closed_at", "created_at").first()
    if row is None or org is None: raise PermissionDenied
    return {"receipt": row, "organization": org}


def _original_date(value):
    try:
        date = parse_datetime(value) if type(value) is str and len(value) <= 40 else None
    except ValueError:
        date = None
    if not _date(date) or date.isoformat() != value:
        raise ValidationError("Original checkout link dates need review.")
    return date


def _record(source, assessed):
    row, org = source["receipt"], source["organization"]
    original = row["source"]
    for key in ("id", "attempt_id", "actor_id", "attempt__id", "attempt__organization_id"): _safe_id(row[key])
    _safe_id(org["id"])
    if (row["attempt_id"] != row["attempt__id"] or row["attempt__organization_id"] != org["id"]
        or type(org["is_suspended"]) is not bool or not _date(org["created_at"]) or org["created_at"] > assessed
        or org["closed_at"] is not None and (not _date(org["closed_at"]) or not org["is_suspended"]
            or not org["created_at"] <= org["closed_at"] <= assessed)
        or not _date(row["acknowledged_at"]) or row["acknowledged_at"] > assessed
        or type(original) is not dict or set(original) != SOURCE_FIELDS):
        raise ValidationError("Retained checkout link acknowledgment needs review.")
    for key in ("organization_id", "actor_id", "attempt_id", "request_actor_id", "seller_id"): _safe_id(original[key])
    if (original["organization_id"] != org["id"] or original["actor_id"] != row["actor_id"]
        or original["attempt_id"] != row["attempt_id"] or original["method"] != "checkout-link-delivery-source-v1"
        or original["interpretation"] != "current_link_receipt_eligibility_not_delivered_link_or_provider_page_or_payment_proof"
        or original["payment_confirmed"] is not False or original["environment"] not in PaddleEnvironment.values
        or original["offer_version"] != "agency-launch-v1"
        or any(type(original[key]) is not str or not re.fullmatch(pattern, original[key]) for key, pattern in (
            ("product_id", r"pro_[a-z0-9]{26}"), ("price_id", r"pri_[a-z0-9]{26}"), ("transaction_id", r"txn_[a-z0-9]{26}")))
        or type(row["source_digest"]) is not str or not re.fullmatch(r"[a-f0-9]{64}", row["source_digest"])
        or row["source_digest"] != checkout_source_digest(original)):
        raise ValidationError("Original checkout link source needs review.")
    created, sent, rotated = (_original_date(original[key]) for key in ("created_at", "sent_at", "seller_rotated_at"))
    if not created <= sent <= row["acknowledged_at"] or rotated > row["acknowledged_at"]:
        raise ValidationError("Recorded checkout link dates need review.")
    try:
        url = original["checkout_url"]
        if type(url) is not str or not 1 <= len(url) <= 4096 or any(ord(char) <= 32 or char == "\\" for char in url): raise ValueError
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or not parsed.path.startswith("/account/") or parsed.fragment or parsed.port == 0
            or parsed.query != "_ptxn=" + original["transaction_id"]): raise ValueError
    except ValueError:
        raise ValidationError("Original application checkout link needs review.") from None
    return {"id": row["id"], "attempt_id": row["attempt_id"], "acknowledged_at": row["acknowledged_at"].isoformat(),
            "original_source_digest": row["source_digest"]}


def _projection(organization_id, receipt_id):
    original = _source(organization_id, receipt_id)
    receipt = _record(original, timezone.now())
    digest = hashlib.sha256(json.dumps(original, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False).encode()).hexdigest()
    result = {"method_version": METHOD, "organization_id": organization_id, "scope": SCOPE,
              "receipt": receipt, "source_digest": digest}
    if _source(organization_id, receipt_id) != original:
        raise ValidationError("Retained checkout link changed during inspection.")
    return result


def require_staff_checkout_link_delivery(*, request, original):
    require_checkout_link_staff(request)
    if _projection(original["organization_id"], original["receipt"]["id"]) != original:
        raise ValidationError("Retained checkout link changed before delivery.")
    require_checkout_link_staff(request)


def inspect_staff_checkout_link(*, request, organization_id, receipt_id, reason):
    for identity in (organization_id, receipt_id): _safe_id(identity)
    if type(reason) is not str or reason not in REASONS:
        raise ValidationError("Choose a categorical checkout link investigation reason.")
    actor = require_checkout_link_staff(request)
    with transaction.atomic():
        if not Organization.objects.select_for_update().filter(pk=organization_id).order_by("pk").values_list("pk", flat=True).first():
            raise PermissionDenied
        result = _projection(organization_id, receipt_id)
        AuditEvent.objects.create(organization_id=organization_id, actor=actor,
            event_type=AuditEventType.STAFF_CHECKOUT_LINK_INSPECTED, details={"receipt_id": receipt_id, "reason": reason})
        require_staff_checkout_link_delivery(request=request, original=result)
        return result
