"""Retained first-feedback/current-record linkage, never current suppression or clearance authority."""
import hashlib
import json
import re
from datetime import datetime

from allauth.account.models import EmailAddress
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from accounts.staff_access import require_staff_permissions
from .models import AuditEvent, AuditEventType, EmailFeedbackReceipt, EmailSuppression, FeedbackKind
from .support_requests import _safe_id


METHOD = "scoped-staff-retained-email-feedback-v1"
SCOPE = "current_record_first_feedback_not_original_recipient_provider_occurrence_current_applicability_or_clearance_authority"
REASONS = {"customer_request", "investigation"}
SUPPRESSION_FIELDS = ("id", "email_address_id", "address_digest", "reason", "feedback_id", "created_at")
FEEDBACK_FIELDS = ("id", "kind", "addresses_digest", "received_at")


def require_email_feedback_staff(request):
    return require_staff_permissions(request, permissions=("accounts.view_user", "tenancy.view_emailsuppression",
                                                          "tenancy.view_emailfeedbackreceipt"))


def _date(value, assessed):
    return isinstance(value, datetime) and not timezone.is_naive(value) and value <= assessed


def _records(original, assessed):
    user, address, suppression, feedback = (original[key] for key in ("user", "address", "suppression", "feedback"))
    for row, keys in ((user, ("id",)), (address, ("id", "user_id")),
                      (suppression, ("id", "email_address_id", "feedback_id")), (feedback, ("id",))):
        for key in keys: _safe_id(row[key])
    if (type(user["is_active"]) is not bool or user["closed_at"] is not None and (
            user["is_active"] or not _date(user["closed_at"], assessed))
        or address["user_id"] != user["id"] or suppression["email_address_id"] != address["id"]
        or suppression["feedback_id"] != feedback["id"]
        or suppression["reason"] not in FeedbackKind.values or suppression["reason"] != feedback["kind"]
        or not _date(feedback["received_at"], assessed) or not _date(suppression["created_at"], assessed)
        or feedback["received_at"] > suppression["created_at"]
        or any(type(value) is not str or not re.fullmatch(r"[a-f0-9]{64}", value)
               for value in (suppression["address_digest"], feedback["addresses_digest"]))):
        raise ValidationError("Retained feedback history needs review.")
    return ({"id": suppression["id"], "reason": suppression["reason"], "created_at": suppression["created_at"].isoformat()},
            {"id": feedback["id"], "kind": feedback["kind"], "received_at": feedback["received_at"].isoformat()})


def _rows(user_id, email_address_id, suppression_id):
    user = User.objects.filter(pk=user_id).values("id", "is_active", "closed_at").first()
    address = EmailAddress.objects.filter(pk=email_address_id, user_id=user_id).values("id", "user_id").first()
    suppression = EmailSuppression.objects.filter(pk=suppression_id, email_address_id=email_address_id).values(*SUPPRESSION_FIELDS).first()
    if user is None or address is None or suppression is None: raise PermissionDenied
    feedback = EmailFeedbackReceipt.objects.filter(pk=suppression["feedback_id"]).values(*FEEDBACK_FIELDS).first()
    if feedback is None: raise PermissionDenied
    return {"user": user, "address": address, "suppression": suppression, "feedback": feedback}


def _projection(user_id, email_address_id, suppression_id):
    original = _rows(user_id, email_address_id, suppression_id)
    suppression, feedback = _records(original, timezone.now())
    digest = hashlib.sha256(json.dumps(original, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False).encode()).hexdigest()
    result = {"method_version": METHOD, "user_id": user_id, "email_address_id": email_address_id,
              "scope": SCOPE, "suppression": suppression, "feedback": feedback, "source_digest": digest}
    if _rows(user_id, email_address_id, suppression_id) != original:
        raise ValidationError("Retained feedback linkage changed during inspection.")
    return result


def require_staff_email_feedback_delivery(*, request, original):
    require_email_feedback_staff(request)
    if _projection(original["user_id"], original["email_address_id"], original["suppression"]["id"]) != original:
        raise ValidationError("Retained feedback linkage changed before delivery.")
    require_email_feedback_staff(request)


def inspect_staff_email_feedback(*, request, user_id, email_address_id, suppression_id, reason):
    for identity in (user_id, email_address_id, suppression_id): _safe_id(identity)
    if type(reason) is not str or reason not in REASONS:
        raise ValidationError("Choose a categorical feedback investigation reason.")
    actor = require_email_feedback_staff(request)
    with transaction.atomic():
        if not User.objects.select_for_update().filter(pk=user_id).values_list("pk", flat=True).first():
            raise PermissionDenied
        result = _projection(user_id, email_address_id, suppression_id)
        AuditEvent.objects.create(actor=actor, subject_user_id=user_id, event_type=AuditEventType.STAFF_EMAIL_FEEDBACK_INSPECTED,
            details={"email_address_id": email_address_id, "suppression_id": suppression_id,
                     "feedback_id": result["feedback"]["id"], "reason": reason, "kind": result["feedback"]["kind"]})
        require_staff_email_feedback_delivery(request=request, original=result)
        return result
