"""Reviewed lifetime for newly completed private copies, separate from source retention."""
import re
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError


def reviewed_copy_lifetime():
    reference = settings.CUSTOMER_EXPORT_COPY_POLICY_REFERENCE
    days = settings.CUSTOMER_EXPORT_COPY_LIFETIME_DAYS
    if reference == "" and days == 0:
        return "", None
    if (type(reference) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", reference)
        or type(days) is not int or not 1 <= days <= 36500):
        raise ValidationError("Private copy expiry requires a reviewed policy reference and valid lifetime.")
    return reference, timedelta(days=days)
