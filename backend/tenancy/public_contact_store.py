"""CONTACT persistence; receipt scope is independent of account identity."""
from datetime import timedelta
from hashlib import sha256
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import PublicContactRequest
from .public_contact import FIELDS, validate_contact_command


ERROR = "Contact receipt unavailable."


def browser_key_hash(browser_key):
    if type(browser_key) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{43}", browser_key):
        raise ValidationError(ERROR)
    return sha256(browser_key.encode("ascii")).hexdigest()


def _receipt(row):
    row.clean()
    if row.expires_at <= timezone.now():
        raise ValidationError(ERROR)
    return {"request_key": row.request_key, "status": "received", "created_at": row.created_at.isoformat(),
            "expires_at": row.expires_at.isoformat(), "scope": "stored_contact_not_email_delivery_or_staff_response"}


def own_contact_receipt(*, browser_key, request_key):
    digest = browser_key_hash(browser_key)
    if type(request_key) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", request_key):
        raise ValidationError(ERROR)
    row = PublicContactRequest.objects.filter(browser_key_hash=digest, request_key=request_key,
                                              expires_at__gt=timezone.now()).first()
    return _receipt(row) if row else None


def create_contact_request(*, browser_key, command):
    digest = browser_key_hash(browser_key)
    command = validate_contact_command(command)
    days = getattr(settings, "PUBLIC_CONTACT_RETENTION_DAYS", None)
    if type(days) is not int or not 1 <= days <= 365:
        raise ValidationError("Configure reviewed contact retention before intake.")
    assessed = timezone.now()
    with transaction.atomic():
        row, _ = PublicContactRequest.objects.get_or_create(browser_key_hash=digest, request_key=command["request_key"],
            defaults={**{name: command[name] for name in FIELDS if name != "request_key"},
                      "created_at": assessed, "expires_at": assessed + timedelta(days=days)})
        if row.expires_at <= assessed or {name: getattr(row, name) for name in FIELDS} != command:
            raise ValidationError(ERROR)
        return _receipt(row)


@transaction.atomic
def purge_expired_contact_requests():
    assessed = timezone.now()
    identities = list(PublicContactRequest.objects.select_for_update(skip_locked=True).filter(expires_at__lte=assessed)
                      .order_by("expires_at", "pk").values_list("pk", flat=True)[:100])
    deleted, _ = PublicContactRequest.objects.filter(pk__in=identities, expires_at__lte=assessed).delete()
    return deleted
