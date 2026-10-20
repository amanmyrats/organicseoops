"""Exact retained canceled-identity copy, not complete billing history or paid authority."""
import hashlib
import json
import re

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.staff_access import require_staff_permissions
from .models import AuditEvent, AuditEventType, Organization, PaddleEnvironment, PaddleStatus, PaddleSubscriptionHistory
from .staff_subscription_investigation import _date
from .support_requests import _safe_id


METHOD = "exact-staff-retained-archived-subscription-v1"
SCOPE = "recorded_canceled_identity_copy_not_complete_lifetime_history_current_paid_access_or_cancellation_authority"
REASONS = {"customer_request", "investigation"}
FIELDS = ("id", "organization_id", "environment", "customer_id", "subscription_id", "status",
          "verified_at", "canceled_at", "refunded_at", "disputed_at", "archived_at")
DATES = tuple(field for field in FIELDS if field.endswith("_at"))


def require_subscription_history_staff(request):
    return require_staff_permissions(request, permissions=("tenancy.view_organization", "tenancy.view_paddlesubscriptionhistory"))


def _source(organization_id, history_id):
    history = PaddleSubscriptionHistory.objects.filter(pk=history_id, organization_id=organization_id).values(*FIELDS).first()
    organization = Organization.objects.filter(pk=organization_id).order_by("pk").values("id", "is_suspended", "closed_at", "created_at").first()
    if history is None or organization is None: raise PermissionDenied
    return {"history": history, "organization": organization}


def _record(source, assessed):
    row, org = source["history"], source["organization"]
    for identity in (row["id"], row["organization_id"], org["id"]): _safe_id(identity)
    if (row["organization_id"] != org["id"] or type(org["is_suspended"]) is not bool
        or not _date(org["created_at"]) or org["created_at"] > assessed
        or org["closed_at"] is not None and (not _date(org["closed_at"]) or not org["is_suspended"]
            or not org["created_at"] <= org["closed_at"] <= assessed)
        or row["environment"] not in PaddleEnvironment.values or row["status"] != PaddleStatus.CANCELED
        or any(type(row[key]) is not str or not re.fullmatch(pattern, row[key]) for key, pattern in (
            ("customer_id", r"ctm_[a-z0-9]{26}"), ("subscription_id", r"sub_[a-z0-9]{26}")))
        or any(not _date(row[key]) for key in ("verified_at", "canceled_at", "archived_at"))
        or any(row[key] is not None and not _date(row[key]) for key in ("refunded_at", "disputed_at"))):
        raise ValidationError("Retained archived subscription needs review.")
    if not (row["verified_at"] <= row["archived_at"] <= assessed and row["canceled_at"] <= row["archived_at"]):
        raise ValidationError("Recorded archive dates need review.")
    return {key: row[key].isoformat() if key in DATES and row[key] is not None else row[key]
            for key in FIELDS if key not in {"organization_id", "customer_id", "subscription_id"}}


def _projection(organization_id, history_id):
    original = _source(organization_id, history_id)
    history = _record(original, timezone.now())
    digest = hashlib.sha256(json.dumps(original, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False).encode()).hexdigest()
    result = {"method_version": METHOD, "organization_id": organization_id, "scope": SCOPE,
              "history": history, "source_digest": digest}
    if _source(organization_id, history_id) != original:
        raise ValidationError("Retained archived subscription changed during inspection.")
    return result


def require_staff_subscription_history_delivery(*, request, original):
    require_subscription_history_staff(request)
    if _projection(original["organization_id"], original["history"]["id"]) != original:
        raise ValidationError("Retained archived subscription changed before delivery.")
    require_subscription_history_staff(request)


def inspect_staff_subscription_history(*, request, organization_id, history_id, reason):
    for identity in (organization_id, history_id): _safe_id(identity)
    if type(reason) is not str or reason not in REASONS:
        raise ValidationError("Choose a categorical archived subscription investigation reason.")
    actor = require_subscription_history_staff(request)
    with transaction.atomic():
        if not Organization.objects.select_for_update().filter(pk=organization_id).order_by("pk").values_list("pk", flat=True).first():
            raise PermissionDenied
        result = _projection(organization_id, history_id)
        AuditEvent.objects.create(organization_id=organization_id, actor=actor, event_type=AuditEventType.STAFF_SUBSCRIPTION_HISTORY_INSPECTED,
            details={"history_id": history_id, "reason": reason, "status": result["history"]["status"]})
        require_staff_subscription_history_delivery(request=request, original=result)
        return result
