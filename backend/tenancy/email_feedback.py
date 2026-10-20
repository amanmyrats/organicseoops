"""Deduplicated, current-address-only SES permanent-bounce/complaint suppression."""

import hashlib
import re

from allauth.account.models import EmailAddress
from django.core.exceptions import ValidationError
from django.core.exceptions import PermissionDenied
from django.core.validators import validate_email
from django.db import transaction

from accounts.models import UserManager
from accounts.staff_access import require_staff_permissions

from .models import AuditEvent, AuditEventType, EmailFeedbackReceipt, EmailSuppression, FeedbackKind


def _address_digest(email):
    return hashlib.sha256(email.encode()).hexdigest()


def is_email_suppressed(email):
    email = UserManager.normalize_email(email)
    return EmailSuppression.objects.filter(
        email_address__email=email, email_address__user__email=email,
        email_address__primary=True, email_address__verified=True,
        address_digest=_address_digest(email),
    ).exists()


def record_ses_feedback(event):
    if (type(event) is not tuple or len(event) != 3
        or type(event[0]) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{8,200}", event[0])
        or event[1] not in FeedbackKind.values or type(event[2]) is not tuple
        or not 1 <= len(event[2]) <= 10):
        raise ValidationError("Invalid feedback identity.")
    addresses = []
    for value in event[2]:
        if type(value) is not str or len(value) > 254:
            raise ValidationError("Invalid feedback recipient.")
        validate_email(value)
        addresses.append(UserManager.normalize_email(value))
    digest = hashlib.sha256("\0".join(sorted(set(addresses))).encode()).hexdigest()
    with transaction.atomic():
        receipt, created = EmailFeedbackReceipt.objects.get_or_create(
            event_id=event[0], defaults={"kind": event[1], "addresses_digest": digest},
        )
        if not created:
            if receipt.kind != event[1] or receipt.addresses_digest != digest:
                raise ValidationError("Feedback identifier conflicts with an earlier event.")
            return True
        for email in sorted(set(addresses)):
            rows = EmailAddress.objects.select_for_update().filter(
                email=email,
            ).order_by("pk")[:10]
            for row in rows:
                EmailSuppression.objects.get_or_create(
                    email_address=row, address_digest=_address_digest(email),
                    defaults={"reason": event[1], "feedback": receipt},
                )
    return True


def clear_email_suppression(*, suppression, actor, reason, request):
    current_actor = require_staff_permissions(request, permissions=("tenancy.delete_emailsuppression",))
    if current_actor.pk != actor.pk:
        raise PermissionDenied
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 250:
        raise ValidationError("Provide a review reason.")
    with transaction.atomic():
        if not EmailAddress.objects.select_for_update().filter(pk=suppression.email_address_id).values_list("pk", flat=True).first():
            raise ValidationError("Suppression is no longer current.")
        row = EmailSuppression.objects.select_for_update().filter(pk=suppression.pk, email_address_id=suppression.email_address_id).first()
        if row is None:
            raise ValidationError("Suppression is no longer current.")
        fields = ("id", "email_address_id", "address_digest", "reason", "feedback_id", "created_at")
        if any(getattr(row, field) != getattr(suppression, field) for field in fields):
            raise ValidationError("Suppression changed before review.")

        def source():
            address = EmailAddress.objects.filter(pk=row.email_address_id).values(
                "id", "user_id", "email", "primary", "verified", "user__email", "user__is_active").first()
            original = EmailSuppression.objects.filter(pk=row.pk, email_address_id=row.email_address_id).values(*fields).first()
            if (address is None or original is None or not address["primary"] or not address["verified"]
                or not address["user__is_active"] or address["user__email"] != address["email"]
                or original["address_digest"] != _address_digest(address["email"])):
                raise ValidationError("Suppression is not for a current verified address.")
            return address, original

        original = source()
        AuditEvent.objects.create(
            actor=current_actor, subject_user_id=original[0]["user_id"], event_type=AuditEventType.EMAIL_SUPPRESSION_CLEARED,
            details={"suppression_id": row.pk, "email_address_id": row.email_address_id, "reason": reason.strip()},
        )
        if source() != original:
            raise ValidationError("Suppression changed during review.")
        if require_staff_permissions(request, permissions=("tenancy.delete_emailsuppression",)).pk != current_actor.pk:
            raise PermissionDenied
        row.delete()
        if require_staff_permissions(request, permissions=("tenancy.delete_emailsuppression",)).pk != current_actor.pk:
            raise PermissionDenied
