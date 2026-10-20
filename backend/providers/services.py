import os
import re

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from tenancy.models import AuditEvent, AuditEventType, Organization
from tenancy.services import Action, require_organization_action

from .models import AIModel, AIModelCapability, AIProvider, AIProviderAccount, AIProviderSecret


class UnsupportedCapability(ValidationError):
    pass


def _require_permission(actor, permission):
    actor = get_user_model().objects.filter(
        pk=getattr(actor, "pk", None),
        is_active=True,
        is_staff=True,
    ).first()
    if actor is None or not actor.has_perm(permission):
        raise PermissionDenied
    return actor


def create_provider(*, actor, key, name, kind, base_url="", enabled=False):
    if type(enabled) is not bool:
        raise ValidationError("Enabled must be a boolean.")
    with transaction.atomic():
        _require_permission(actor, "providers.add_aiprovider")
        provider = AIProvider(key=key, name=name, kind=kind, base_url=base_url, enabled=enabled)
        provider.save()
    return provider


def create_provider_account(*, actor, provider, label, secret_reference):
    with transaction.atomic():
        actor = _require_permission(actor, "providers.add_aiprovideraccount")
        provider = AIProvider.objects.select_for_update().get(pk=provider.pk)
        account = AIProviderAccount(
            provider=provider,
            label=label,
            secret_reference=secret_reference,
            rotated_at=timezone.now(),
        )
        account.save()
        AuditEvent.objects.create(
            organization=None,
            event_type=AuditEventType.PROVIDER_ACCOUNT_CREATED,
            actor=actor,
            details={"provider_key": provider.key, "provider_account_id": account.pk},
        )
    return account


def rotate_provider_account(*, actor, account, secret_reference):
    with transaction.atomic():
        actor = _require_permission(actor, "providers.change_aiprovideraccount")
        account = AIProviderAccount.objects.select_for_update().select_related("provider").get(pk=account.pk)
        if account.organization_id is not None:
            raise PermissionDenied
        if account.state != AIProviderAccount.State.ACTIVE:
            raise ValidationError("Revoked provider credentials cannot be rotated.")
        account.secret_reference = secret_reference
        account.rotated_at = timezone.now()
        account.save(update_fields=["secret_reference", "rotated_at", "updated_at"])
        AuditEvent.objects.create(
            organization=None,
            event_type=AuditEventType.PROVIDER_ACCOUNT_ROTATED,
            actor=actor,
            details={"provider_key": account.provider.key, "provider_account_id": account.pk},
        )
    return account


def revoke_provider_account(*, actor, account):
    with transaction.atomic():
        actor = _require_permission(actor, "providers.change_aiprovideraccount")
        account = AIProviderAccount.objects.select_for_update().select_related("provider").get(pk=account.pk)
        if account.organization_id is not None:
            raise PermissionDenied
        if account.state == AIProviderAccount.State.REVOKED:
            return account, False
        account.state = AIProviderAccount.State.REVOKED
        account.revoked_at = timezone.now()
        account.save(update_fields=["state", "revoked_at", "updated_at"])
        AIProviderSecret.objects.filter(account=account).delete()
        AuditEvent.objects.create(
            organization=None,
            event_type=AuditEventType.PROVIDER_ACCOUNT_REVOKED,
            actor=actor,
            details={"provider_key": account.provider.key, "provider_account_id": account.pk},
        )
    return account, True


def resolve_provider_secret(account, *, organization=None, expected_revision=None):
    account = AIProviderAccount.objects.select_related("provider").filter(
        pk=account.pk,
        state=AIProviderAccount.State.ACTIVE,
        provider__enabled=True,
    ).first()
    if account is None:
        raise PermissionDenied
    if expected_revision is not None and (account.rotated_at.isoformat() if account.rotated_at else "") != expected_revision:
        raise PermissionDenied
    if account.organization_id is not None and account.organization_id != getattr(organization, "pk", None):
        raise PermissionDenied
    stored = AIProviderSecret.objects.filter(account=account).first()
    if stored is not None:
        try:
            version, separator, ciphertext = stored.ciphertext.partition(":")
            if version != "v1" or not separator:
                raise ValueError
            return _provider_cipher().decrypt(ciphertext.encode()).decode()
        except (InvalidToken, UnicodeError, ValueError):
            raise ValidationError("Provider credential is unavailable.") from None
    if account.secret_reference not in settings_secret_references():
        raise PermissionDenied
    variable = account.secret_reference.removeprefix("env:")
    secret = os.environ.get(variable, "")
    if not secret:
        raise ValidationError("Provider credential is unavailable.")
    return secret


def settings_secret_references():
    return settings.AI_PROVIDER_SECRET_REFERENCES


def _provider_cipher():
    if not settings.PROVIDER_ENCRYPTION_KEYS:
        raise ValidationError("Provider credential encryption is not configured.")
    return MultiFernet([Fernet(key.encode()) for key in settings.PROVIDER_ENCRYPTION_KEYS])


def set_provider_secret(*, actor, account, secret):
    if type(secret) is not str or not re.fullmatch(r"[A-Za-z0-9._~+/-]{8,4096}=*", secret):
        raise ValidationError("Provide a bounded provider credential.")
    with transaction.atomic():
        actor = _require_permission(actor, "providers.change_aiprovideraccount")
        account = AIProviderAccount.objects.select_for_update().select_related("provider").get(pk=account.pk)
        if account.organization_id is not None:
            raise PermissionDenied
        if account.state != AIProviderAccount.State.ACTIVE:
            raise ValidationError("Revoked provider credentials cannot be updated.")
        now = timezone.now()
        AIProviderSecret.objects.update_or_create(
            account=account,
            defaults={"ciphertext": "v1:" + _provider_cipher().encrypt(secret.encode()).decode(), "rotated_at": now},
        )
        account.rotated_at = now
        account.save(update_fields=["rotated_at", "updated_at"])
        AuditEvent.objects.create(organization=None, event_type=AuditEventType.PROVIDER_ACCOUNT_ROTATED,
                                  actor=actor, details={"provider_key": account.provider.key,
                                                        "provider_account_id": account.pk})
    return account


def create_stored_provider_account(*, actor, provider, label, secret):
    with transaction.atomic():
        actor = _require_permission(actor, "providers.add_aiprovideraccount")
        account = AIProviderAccount(provider=AIProvider.objects.select_for_update().get(pk=provider.pk),
                                    label=label, secret_reference="", rotated_at=timezone.now())
        account.save()
        set_provider_secret(actor=actor, account=account, secret=secret)
    return account


def create_organization_provider_account(*, actor, organization, provider, label, secret):
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization.pk)
        require_organization_action(organization=organization, user=actor, action=Action.MANAGE_PROVIDER_CREDENTIAL)
        account = AIProviderAccount(provider=AIProvider.objects.get(pk=provider.pk, enabled=True),
                                    organization=organization, label=label, secret_reference="",
                                    rotated_at=timezone.now())
        account.save()
        set_organization_provider_secret(actor=actor, organization=organization, account=account, secret=secret)
    return account


def set_organization_provider_secret(*, actor, organization, account, secret):
    if type(secret) is not str or not re.fullmatch(r"[A-Za-z0-9._~+/-]{8,4096}=*", secret):
        raise ValidationError("Provide a bounded provider credential.")
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization.pk)
        require_organization_action(organization=organization, user=actor, action=Action.MANAGE_PROVIDER_CREDENTIAL)
        account = AIProviderAccount.objects.select_for_update().select_related("provider").get(
            pk=account.pk, organization=organization)
        if account.state != AIProviderAccount.State.ACTIVE or not account.provider.enabled:
            raise ValidationError("Provider account is unavailable.")
        now = timezone.now()
        AIProviderSecret.objects.update_or_create(
            account=account,
            defaults={"ciphertext": "v1:" + _provider_cipher().encrypt(secret.encode()).decode(), "rotated_at": now},
        )
        account.rotated_at = now
        account.save(update_fields=["rotated_at", "updated_at"])
        AuditEvent.objects.create(organization=organization, event_type=AuditEventType.PROVIDER_ACCOUNT_ROTATED,
                                  actor=actor, details={"provider_key": account.provider.key,
                                                        "provider_account_id": account.pk})
    return account


def revoke_organization_provider_account(*, actor, organization, account):
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization.pk)
        require_organization_action(organization=organization, user=actor, action=Action.MANAGE_PROVIDER_CREDENTIAL)
        account = AIProviderAccount.objects.select_for_update().select_related("provider").get(
            pk=account.pk, organization=organization)
        if account.state == AIProviderAccount.State.REVOKED:
            return account, False
        account.state = AIProviderAccount.State.REVOKED
        account.revoked_at = timezone.now()
        account.save(update_fields=["state", "revoked_at", "updated_at"])
        AIProviderSecret.objects.filter(account=account).delete()
        AuditEvent.objects.create(organization=organization, event_type=AuditEventType.PROVIDER_ACCOUNT_REVOKED,
                                  actor=actor, details={"provider_key": account.provider.key,
                                                        "provider_account_id": account.pk})
    return account, True


def configure_model(
    *, actor, provider, identifier, name, capabilities, context_window=None, max_output_tokens=None,
    capability_source="", capabilities_verified_at=None, enabled=False,
    input_price_usd_per_million=None, output_price_usd_per_million=None, pricing_source="",
    pricing_verified_at=None, access_tier=AIModel.AccessTier.UNKNOWN, privacy_policy_url="",
):
    with transaction.atomic():
        provider = AIProvider.objects.select_for_update().get(pk=provider.pk)
        model = AIModel.objects.select_for_update().filter(provider=provider, identifier=identifier).first()
        permission = "providers.change_aimodel" if model else "providers.add_aimodel"
        _require_permission(actor, permission)
        if model is None:
            model = AIModel(provider=provider, identifier=identifier)
        model.name = name
        model.capabilities = capabilities
        model.context_window = context_window
        model.max_output_tokens = max_output_tokens
        model.capability_source = capability_source
        model.capabilities_verified_at = capabilities_verified_at
        model.input_price_usd_per_million = input_price_usd_per_million
        model.output_price_usd_per_million = output_price_usd_per_million
        model.pricing_source = pricing_source
        model.pricing_verified_at = pricing_verified_at
        model.access_tier = access_tier
        model.privacy_policy_url = privacy_policy_url
        model.enabled = enabled
        model.save()
    return model


def require_model_capabilities(model, required):
    if (
        type(required) not in {set, frozenset, list, tuple}
        or any(not isinstance(item, str) or item not in AIModelCapability.values for item in required)
    ):
        raise ValidationError("Choose supported capability requirements.")
    model = AIModel.objects.select_related("provider").filter(pk=model.pk, enabled=True, provider__enabled=True).first()
    if model is None or not set(required) <= set(model.capabilities):
        raise UnsupportedCapability("The selected model does not support this operation.")
    return model
