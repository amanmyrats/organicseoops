"""Exact current account-mail record linkage, never original recipient or replay authority."""
import hashlib
import json
from datetime import datetime

from allauth.account.models import EmailAddress
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from tenancy.models import AuditEvent, AuditEventType
from tenancy.support_requests import _safe_id
from .models import AccountEmailDelivery, EmailDeliveryState, User
from .staff_access import require_staff_permissions


METHOD = "scoped-staff-current-account-mail-v1"
SCOPE = "current_record_linkage_not_original_recipient_purpose_inbox_current_suppression_or_resend_authority"
REASONS = {"customer_request", "investigation"}
FIELDS = ("id", "address_id", "state", "attempted_at", "finished_at")


def require_account_mail_staff(request):
    return require_staff_permissions(request, permissions=("accounts.view_user", "accounts.view_accountemaildelivery"))


def _date(value, assessed):
    return isinstance(value, datetime) and not timezone.is_naive(value) and value <= assessed


def _delivery(row, assessed):
    for key in ("id", "address_id"): _safe_id(row[key])
    if (row["state"] not in EmailDeliveryState.values or not _date(row["attempted_at"], assessed)
        or (row["state"] == EmailDeliveryState.ATTEMPTED) != (row["finished_at"] is None)
        or row["finished_at"] is not None and (
            not _date(row["finished_at"], assessed) or row["finished_at"] < row["attempted_at"])):
        raise ValidationError("Recorded account-mail history needs review.")
    return {key: row[key].isoformat() if key.endswith("_at") and row[key] else row[key]
            for key in ("id", "state", "attempted_at", "finished_at")}


def _rows(user_id, email_address_id, delivery_id):
    user = User.objects.filter(pk=user_id).values("id", "is_active", "closed_at").first()
    address = EmailAddress.objects.filter(pk=email_address_id, user_id=user_id).values("id", "user_id").first()
    delivery = AccountEmailDelivery.objects.filter(pk=delivery_id, address_id=email_address_id).values(*FIELDS).first()
    if user is None or address is None or delivery is None: raise PermissionDenied
    return {"user": user, "address": address, "delivery": delivery}


def _projection(user_id, email_address_id, delivery_id):
    original = _rows(user_id, email_address_id, delivery_id)
    assessed = timezone.now()
    user = original["user"]
    if (type(user["is_active"]) is not bool or user["closed_at"] is not None and (
            user["is_active"] or not _date(user["closed_at"], assessed))):
        raise ValidationError("Retained account state needs review.")
    delivery = _delivery(original["delivery"], assessed)
    digest = hashlib.sha256(json.dumps(original, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False).encode()).hexdigest()
    result = {"method_version": METHOD, "user_id": user_id, "email_address_id": email_address_id,
              "scope": SCOPE, "delivery": delivery, "source_digest": digest}
    if _rows(user_id, email_address_id, delivery_id) != original:
        raise ValidationError("Recorded account-mail linkage changed during inspection.")
    return result


def require_staff_account_mail_delivery(*, request, original):
    require_account_mail_staff(request)
    if _projection(original["user_id"], original["email_address_id"], original["delivery"]["id"]) != original:
        raise ValidationError("Recorded account-mail linkage changed before delivery.")
    require_account_mail_staff(request)


def inspect_staff_account_mail(*, request, user_id, email_address_id, delivery_id, reason):
    for identity in (user_id, email_address_id, delivery_id): _safe_id(identity)
    if type(reason) is not str or reason not in REASONS:
        raise ValidationError("Choose a categorical account-mail investigation reason.")
    actor = require_account_mail_staff(request)
    with transaction.atomic():
        if not User.objects.select_for_update().filter(pk=user_id).values_list("pk", flat=True).first():
            raise PermissionDenied
        result = _projection(user_id, email_address_id, delivery_id)
        AuditEvent.objects.create(actor=actor, subject_user_id=user_id,
            event_type=AuditEventType.STAFF_ACCOUNT_MAIL_INSPECTED,
            details={"email_address_id": email_address_id, "delivery_id": delivery_id,
                     "reason": reason, "state": result["delivery"]["state"]})
        require_staff_account_mail_delivery(request=request, original=result)
        return result
