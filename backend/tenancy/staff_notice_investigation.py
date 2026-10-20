"""Original organization notice transport history, never mail or retry authority."""
import hashlib
import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.staff_access import require_staff_permissions
from .models import AuditEvent, AuditEventType, NoticeKind, NoticeState, Organization, OrganizationNotice, retained_content_window
from .support_requests import _safe_id


METHOD = "scoped-staff-organization-notice-v1"
SCOPE = "recorded_transport_not_inbox_delivery_current_eligibility_reissue_billing_or_account_mail_authority"
REASONS = {"customer_request", "investigation"}
FIELDS = ("id", "organization_id", "recipient_id", "trial_id", "source_receipt_id", "subscription_id",
          "trial_ends_at", "paid_period_start", "kind", "state", "manual_retries", "created_at", "attempted_at", "sent_at")


def require_notice_staff(request):
    return require_staff_permissions(request, permissions=("tenancy.view_organization", "tenancy.view_organizationnotice"))


def _scope(organization_id):
    if not Organization.objects.filter(pk=organization_id, is_suspended=False, closed_at__isnull=True).filter(
            retained_content_window()).exists():
        raise PermissionDenied


def _notice(row, assessed):
    for key in ("id", "organization_id", "recipient_id"): _safe_id(row[key])
    for key in ("trial_id", "source_receipt_id", "subscription_id"):
        if row[key] is not None: _safe_id(row[key])
    trial = row["kind"] in {NoticeKind.TRIAL_ENDING, NoticeKind.TRIAL_UNITS_EXHAUSTED}
    payment = row["kind"] == NoticeKind.PAYMENT_FAILED
    paid = row["kind"] == NoticeKind.PAID_UNITS_EXHAUSTED
    if (row["kind"] not in NoticeKind.values or row["state"] not in NoticeState.values
        or any((row[key] is not None) != present for key, present in (
            ("trial_id", trial), ("trial_ends_at", trial), ("source_receipt_id", payment),
            ("subscription_id", paid), ("paid_period_start", paid)))
        or type(row["manual_retries"]) is not int or not 0 <= row["manual_retries"] <= 1
        or timezone.is_naive(row["created_at"]) or row["created_at"] > assessed
        or any(row[key] is not None and timezone.is_naive(row[key]) for key in ("trial_ends_at", "paid_period_start", "attempted_at", "sent_at"))
        or (row["state"] == NoticeState.QUEUED) != (row["attempted_at"] is None)
        or (row["state"] == NoticeState.SENT) != (row["sent_at"] is not None)
        or row["attempted_at"] is not None and not row["created_at"] <= row["attempted_at"] <= assessed
        or row["sent_at"] is not None and not row["attempted_at"] <= row["sent_at"] <= assessed):
        raise ValidationError("Recorded notice transport history needs review.")
    return {key: row[key].isoformat() if key.endswith("_at") and row[key] else row[key]
            for key in ("id", "kind", "state", "manual_retries", "created_at", "attempted_at", "sent_at")}


def _projection(organization_id, notice_id):
    rows = OrganizationNotice.objects.filter(pk=notice_id, organization_id=organization_id).values(*FIELDS)
    original = rows.first()
    if original is None: raise PermissionDenied
    notice = _notice(original, timezone.now())
    digest = hashlib.sha256(json.dumps(original, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False).encode()).hexdigest()
    result = {"method_version": METHOD, "organization_id": organization_id, "scope": SCOPE,
              "notice": notice, "source_digest": digest}
    if rows.first() != original:
        raise ValidationError("Recorded notice transport changed during inspection.")
    return result


def require_staff_notice_delivery(*, request, organization_id, original):
    require_notice_staff(request)
    _scope(organization_id)
    if _projection(organization_id, original["notice"]["id"]) != original:
        raise ValidationError("Recorded notice transport changed before delivery.")
    _scope(organization_id)
    require_notice_staff(request)


def inspect_staff_notice(*, request, organization_id, notice_id, reason):
    for identity in (organization_id, notice_id): _safe_id(identity)
    if type(reason) is not str or reason not in REASONS:
        raise ValidationError("Choose a categorical notice investigation reason.")
    actor = require_notice_staff(request)
    _scope(organization_id)
    with transaction.atomic():
        Organization.objects.select_for_update().values_list("pk", flat=True).get(pk=organization_id)
        _scope(organization_id)
        result = _projection(organization_id, notice_id)
        AuditEvent.objects.create(organization_id=organization_id, actor=actor,
            event_type=AuditEventType.STAFF_NOTICE_INSPECTED,
            details={"notice_id": notice_id, "reason": reason, "state": result["notice"]["state"]})
        require_staff_notice_delivery(request=request, organization_id=organization_id, original=result)
        return result
