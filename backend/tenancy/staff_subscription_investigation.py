"""Retained linked subscription scalars, never current paid or cancellation authority."""
import hashlib
import json
import re
from datetime import datetime

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.staff_access import require_staff_permissions
from .models import AuditEvent, AuditEventType, Organization, PaddleEnvironment, PaddleStatus, PaddleSubscription
from .support_requests import _safe_id


METHOD = "exact-staff-retained-linked-subscription-v1"
SCOPE = "recorded_linked_subscription_not_current_paid_access_lifetime_identity_history_or_cancellation_authority"
REASONS = {"customer_request", "investigation"}
FIELDS = ("id", "organization_id", "environment", "customer_id", "subscription_id", "status", "verified_at",
          "period_starts_at", "period_ends_at", "failed_at", "grace_usage_starts_at", "scheduled_cancel_at",
          "canceled_at", "disputed_at", "refunded_at", "currency_code")
DATES = tuple(field for field in FIELDS if field.endswith("_at"))


def require_subscription_staff(request):
    return require_staff_permissions(request, permissions=("tenancy.view_organization", "tenancy.view_paddlesubscription"))


def _source(organization_id, subscription_id):
    subscription = PaddleSubscription.objects.filter(pk=subscription_id, organization_id=organization_id).values(*FIELDS).first()
    organization = Organization.objects.filter(pk=organization_id).order_by("pk").values("id", "is_suspended", "closed_at", "created_at").first()
    if subscription is None or organization is None: raise PermissionDenied
    return {"subscription": subscription, "organization": organization}


def _date(value):
    return isinstance(value, datetime) and not timezone.is_naive(value)


def _record(source, assessed):
    row, org = source["subscription"], source["organization"]
    for identity in (row["id"], row["organization_id"], org["id"]): _safe_id(identity)
    if (row["organization_id"] != org["id"] or type(org["is_suspended"]) is not bool
        or not _date(org["created_at"]) or org["created_at"] > assessed
        or org["closed_at"] is not None and (not _date(org["closed_at"]) or not org["is_suspended"]
            or not org["created_at"] <= org["closed_at"] <= assessed)
        or row["environment"] not in PaddleEnvironment.values or row["status"] not in PaddleStatus.values
        or any(type(row[key]) is not str or not re.fullmatch(pattern, row[key]) for key, pattern in (
            ("customer_id", r"ctm_[a-z0-9]{26}"), ("subscription_id", r"sub_[a-z0-9]{26}")))
        or any(row[key] is not None and not _date(row[key]) for key in DATES)):
        raise ValidationError("Retained linked subscription needs review.")
    verified = row["verified_at"]
    if verified is None:
        if any(row[key] is not None for key in DATES) or row["currency_code"] != "":
            raise ValidationError("Unverified subscription observation needs review.")
    elif (verified > assessed or type(row["currency_code"]) is not str or not re.fullmatch(r"[A-Z]{3}", row["currency_code"])
        or (row["status"] in {PaddleStatus.ACTIVE, PaddleStatus.PAST_DUE}) != (row["period_starts_at"] is not None and row["period_ends_at"] is not None)
        or (row["period_starts_at"] is None) != (row["period_ends_at"] is None)
        or row["period_starts_at"] is not None and row["period_starts_at"] >= row["period_ends_at"]
        or (row["status"] == PaddleStatus.CANCELED) != (row["canceled_at"] is not None)
        or row["failed_at"] is not None and row["grace_usage_starts_at"] is not None and row["grace_usage_starts_at"] > row["failed_at"]):
        raise ValidationError("Recorded subscription dates need review.")
    return {key: row[key].isoformat() if key in DATES and row[key] is not None else row[key]
            for key in FIELDS if key not in {"organization_id", "customer_id", "subscription_id", "currency_code"}}


def _projection(organization_id, subscription_id):
    original = _source(organization_id, subscription_id)
    subscription = _record(original, timezone.now())
    digest = hashlib.sha256(json.dumps(original, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False).encode()).hexdigest()
    result = {"method_version": METHOD, "organization_id": organization_id, "scope": SCOPE,
              "subscription": subscription, "source_digest": digest}
    if _source(organization_id, subscription_id) != original:
        raise ValidationError("Retained linked subscription changed during inspection.")
    return result


def require_staff_subscription_delivery(*, request, original):
    require_subscription_staff(request)
    if _projection(original["organization_id"], original["subscription"]["id"]) != original:
        raise ValidationError("Retained linked subscription changed before delivery.")
    require_subscription_staff(request)


def inspect_staff_subscription(*, request, organization_id, subscription_id, reason):
    for identity in (organization_id, subscription_id): _safe_id(identity)
    if type(reason) is not str or reason not in REASONS:
        raise ValidationError("Choose a categorical subscription investigation reason.")
    actor = require_subscription_staff(request)
    with transaction.atomic():
        if not Organization.objects.select_for_update().filter(pk=organization_id).order_by("pk").values_list("pk", flat=True).first():
            raise PermissionDenied
        result = _projection(organization_id, subscription_id)
        AuditEvent.objects.create(organization_id=organization_id, actor=actor, event_type=AuditEventType.STAFF_SUBSCRIPTION_INSPECTED,
            details={"subscription_id": subscription_id, "reason": reason, "status": result["subscription"]["status"]})
        require_staff_subscription_delivery(request=request, original=result)
        return result
