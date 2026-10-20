"""Operator-only Paddle seller configuration; catalog terms require provider verification before release."""

import re
from datetime import timedelta

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (AuditEvent, AuditEventType, PaddleCheckoutAttempt, PaddleEnvironment,
                     PaddleSellerConfiguration, PaddleSubscription, PaddleWebhookReceipt)


def _cipher():
    keys = settings.PADDLE_ENCRYPTION_KEYS
    if type(keys) not in (tuple, list) or not 1 <= len(keys) <= 5:
        raise ValidationError("Paddle encryption is unavailable.")
    try:
        return MultiFernet([Fernet(key.encode()) for key in keys])
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("Paddle encryption is unavailable.") from None


def _staff(actor, permission):
    actor = get_user_model().objects.filter(pk=getattr(actor, "pk", None), is_staff=True, is_active=True).first()
    if actor is None or not actor.has_perm(permission):
        raise PermissionDenied
    return actor


def _secret(value):
    if type(value) is not str or not 16 <= len(value) <= 512 or any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise ValidationError("Provide a bounded seller credential.")
    return value


def _catalog_id(value, prefix):
    if type(value) is not str or not re.fullmatch(prefix + r"_[a-z0-9]{26}", value):
        raise ValidationError("Provide a configured catalog identifier.")
    return value


def _api_key(value, environment):
    _secret(value)
    prefix = "sdbx" if environment == PaddleEnvironment.SANDBOX else "live"
    if not re.fullmatch(rf"pdl_{prefix}_apikey_[a-z0-9]{{26}}_[A-Za-z0-9]{{22}}_[A-Za-z0-9]{{3}}", value):
        raise ValidationError("Seller key does not match the environment.")
    return value


def set_paddle_seller(*, actor, environment, api_key, webhook_secret, client_token, product_id, price_id,
                      currency, amount, interval, frequency):
    if environment not in PaddleEnvironment.values:
        raise ValidationError("Choose a Paddle environment.")
    api_key, webhook_secret = _api_key(api_key, environment), _secret(webhook_secret)
    expected_prefix = "test" if environment == PaddleEnvironment.SANDBOX else "live"
    if type(client_token) is not str or not re.fullmatch(rf"{expected_prefix}_[A-Za-z0-9]{{27}}", client_token):
        raise ValidationError("Paddle client token does not match the environment.")
    _catalog_id(product_id, "pro")
    _catalog_id(price_id, "pri")
    if (currency, amount, interval) != ("USD", "14900", "month") or type(frequency) is not int or frequency != 1:
        raise ValidationError("Catalog must be attested as the accepted monthly Agency offer.")
    cipher = _cipher()
    with transaction.atomic():
        # Unique environment locks existing records; no payment can use an unconfigured environment.
        record = PaddleSellerConfiguration.objects.select_for_update().filter(environment=environment).first()
        actor = _staff(actor, "tenancy.change_paddlesellerconfiguration" if record else
                       "tenancy.add_paddlesellerconfiguration")
        if record and (PaddleSubscription.objects.filter(environment=environment).exists()
                       or PaddleCheckoutAttempt.objects.filter(environment=environment).exclude(
                           state=PaddleCheckoutAttempt.State.REJECTED).exists()):
            raise ValidationError("Existing subscriptions require reconciled credential rotation.")
        if record is None:
            record = PaddleSellerConfiguration(environment=environment)
        record.product_id, record.price_id = product_id, price_id
        record.client_token = client_token
        record.encrypted_api_key = "v1:" + cipher.encrypt(api_key.encode()).decode()
        record.encrypted_webhook_secret = "v1:" + cipher.encrypt(webhook_secret.encode()).decode()
        record.state = PaddleSellerConfiguration.State.ACTIVE
        record.rotated_at = timezone.now()
        record.save()
        AuditEvent.objects.create(actor=actor, event_type=AuditEventType.PLATFORM_CREDENTIAL_UPDATED,
                                  details={"kind": "paddle_seller", "environment": environment})
    return record


def revoke_paddle_seller(*, actor, environment):
    if environment not in PaddleEnvironment.values:
        raise ValidationError("Choose a Paddle environment.")
    with transaction.atomic():
        actor = _staff(actor, "tenancy.change_paddlesellerconfiguration")
        record = PaddleSellerConfiguration.objects.select_for_update().filter(environment=environment).first()
        if record is None:
            raise ValidationError("Seller is not configured.")
        if record.state == PaddleSellerConfiguration.State.REVOKED:
            return False
        if (PaddleSubscription.objects.filter(environment=environment).exists()
            or PaddleCheckoutAttempt.objects.filter(environment=environment).exclude(
                state=PaddleCheckoutAttempt.State.REJECTED).exists()):
            raise ValidationError("Existing subscriptions require reconciled credential revocation.")
        record.state = PaddleSellerConfiguration.State.REVOKED
        record.encrypted_api_key = record.encrypted_webhook_secret = ""
        record.client_token = ""
        record.rotated_at = timezone.now()
        record.save(update_fields=["state", "encrypted_api_key", "encrypted_webhook_secret", "client_token", "rotated_at"])
        AuditEvent.objects.create(actor=actor, event_type=AuditEventType.PLATFORM_CREDENTIAL_REVOKED,
                                  details={"kind": "paddle_seller", "environment": environment})
    return True


def rotate_paddle_api_key(*, actor, environment, api_key):
    if environment not in PaddleEnvironment.values:
        raise ValidationError("Choose a Paddle environment.")
    api_key = _api_key(api_key, environment)
    with transaction.atomic():
        actor = _staff(actor, "tenancy.change_paddlesellerconfiguration")
        record = PaddleSellerConfiguration.objects.select_for_update().filter(
            environment=environment, state=PaddleSellerConfiguration.State.ACTIVE).first()
        if record is None:
            raise ValidationError("Seller is not configured.")
        cipher = _cipher()
        try:
            for value in (record.encrypted_api_key, record.encrypted_webhook_secret):
                if not value.startswith("v1:") or len(value) > 8192:
                    raise ValueError
            cipher.decrypt(record.encrypted_api_key[3:].encode())
            webhook_secret = cipher.decrypt(record.encrypted_webhook_secret[3:].encode())
        except (InvalidToken, ValueError, UnicodeError):
            raise ValidationError("Seller credentials are unavailable for rotation.") from None
        record.encrypted_api_key = "v1:" + cipher.encrypt(api_key.encode()).decode()
        record.encrypted_webhook_secret = "v1:" + cipher.encrypt(webhook_secret).decode()
        record.rotated_at = timezone.now()
        record.save(update_fields=["encrypted_api_key", "encrypted_webhook_secret", "rotated_at"])
        AuditEvent.objects.create(actor=actor, event_type=AuditEventType.PLATFORM_CREDENTIAL_UPDATED,
                                  details={"kind": "paddle_seller_api_key", "environment": environment})
        for receipt in PaddleWebhookReceipt.objects.select_for_update().filter(
            environment=environment, state=PaddleWebhookReceipt.State.FAILED,
            error_category="authorization_unavailable",
            received_at__gte=timezone.now() - timedelta(days=30)).order_by("pk")[:20]:
            receipt.state = PaddleWebhookReceipt.State.PENDING
            receipt.attempts = 0
            receipt.claimed_at = receipt.retry_after = receipt.processed_at = None
            receipt.error_category = ""
            receipt.save(update_fields=["state", "attempts", "claimed_at", "retry_after", "processed_at", "error_category"])
    return record


def paddle_seller_secrets(environment):
    """Server-side only; caller must choose the configured environment, never derive it from customer input."""
    record = PaddleSellerConfiguration.objects.filter(environment=environment,
                                                        state=PaddleSellerConfiguration.State.ACTIVE).first()
    if record is None:
        raise ValidationError("Seller is unavailable.")
    try:
        cipher = _cipher()
        return tuple(cipher.decrypt(value[3:].encode()).decode() for value in
                     (record.encrypted_api_key, record.encrypted_webhook_secret))
    except (InvalidToken, UnicodeError, ValueError):
        raise ValidationError("Seller is unavailable.") from None
