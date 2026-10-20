"""Explicit reviewed-policy gate and restricted trial identity matching."""
import hashlib
import re
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.crypto import salted_hmac

from .models import RetainedTrialIdentity, UserManager


def retention_key():
    key = settings.PERSONAL_IDENTITY_RETENTION_KEY
    if not isinstance(key, str) or len(key) < 32:
        raise ValidationError("Configure the stable private identity-retention key before cleanup or trial activation.")
    return key, hashlib.sha256(key.encode()).hexdigest()


def reviewed_identity_policy():
    reference = settings.PERSONAL_IDENTITY_ERASURE_POLICY_REFERENCE
    days = settings.PERSONAL_IDENTITY_TRIAL_RETENTION_DAYS
    if (not isinstance(reference, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", reference)
        or type(days) is not int or days <= 0):
        raise ValidationError("Account identity cleanup requires an explicitly configured reviewed policy.")
    try:
        duration = timedelta(days=days)
    except OverflowError as exc:
        raise ValidationError("Identity-retention duration is invalid.") from exc
    key, key_id = retention_key()
    return reference, duration, key, key_id


def identity_digest(email, key):
    return salted_hmac("organicseoops.retained-trial-identity-v1", UserManager.normalize_email(email),
                       secret=key, algorithm="sha256").hexdigest()


def has_retained_trial_identity(email, *, now):
    retained = RetainedTrialIdentity.objects.filter(expires_at__gt=now)
    if not retained.exists():
        return False
    key, key_id = retention_key()
    if retained.exclude(key_id=key_id).exists():
        raise ValidationError("Reconcile retained trial identity keys before automatic activation.")
    return retained.filter(digest=identity_digest(email, key)).exists()
