from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from jobs.performance_transport import _API_KEY
from tenancy.models import AuditEvent, AuditEventType, Organization
from tenancy.services import Action, require_organization_action

from .models import OrganizationPerformanceKey, PerformanceAPIKey
from .services import _require_permission


def _cipher():
    keys = settings.PERFORMANCE_ENCRYPTION_KEYS
    if type(keys) not in {tuple, list} or not 1 <= len(keys) <= 5:
        raise ValidationError("Performance credential encryption is unavailable.")
    try:
        return MultiFernet([Fernet(key.encode()) for key in keys])
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("Performance credential encryption is unavailable.") from None


def performance_key_reference(*, organization=None):
    if organization is not None:
        record = OrganizationPerformanceKey.objects.filter(organization_id=organization.pk).first()
        if record is not None:
            return {"source": "organization", "revision": record.rotated_at.isoformat(), "state": record.state}
    record = PerformanceAPIKey.objects.filter(key="primary").first()
    return ({"source": "platform", "revision": record.rotated_at.isoformat(), "state": record.state}
            if record is not None else {"source": "environment", "revision": "", "state": "unverified"})


def google_performance_key(*, organization=None):
    record = (OrganizationPerformanceKey.objects.filter(organization_id=organization.pk).first()
              if organization is not None else None)
    if record is None:
        record = PerformanceAPIKey.objects.filter(key="primary").first()
    if record is None:
        value = settings.GOOGLE_PERFORMANCE_API_KEY
    elif record.state == "active":
        try:
            if not record.encrypted_secret.startswith("v1:") or len(record.encrypted_secret) > 8192:
                raise ValueError
            value = _cipher().decrypt(record.encrypted_secret[3:].encode()).decode()
        except (InvalidToken, ValueError, UnicodeError):
            raise ValidationError("Performance credential is unavailable.") from None
    else:
        raise ValidationError("Performance credential is unavailable.")
    if type(value) is not str or not _API_KEY.fullmatch(value):
        raise ValidationError("Performance credential is unavailable.")
    return value


def set_performance_key(*, actor, value):
    if type(value) is not str or not _API_KEY.fullmatch(value):
        raise ValidationError("Provide a bounded performance API key.")
    with transaction.atomic():
        record = PerformanceAPIKey.objects.select_for_update().filter(key="primary").first()
        permission = "providers.change_performanceapikey" if record else "providers.add_performanceapikey"
        actor = _require_permission(actor, permission)
        if record is None:
            record = PerformanceAPIKey(key="primary")
        record.encrypted_secret = "v1:" + _cipher().encrypt(value.encode()).decode()
        record.state = PerformanceAPIKey.State.ACTIVE
        record.rotated_at = timezone.now()
        record.save()
        AuditEvent.objects.create(organization=None, actor=actor,
                                  event_type=AuditEventType.PLATFORM_CREDENTIAL_UPDATED,
                                  details={"kind": "google_performance_api"})
    return record


def revoke_performance_key(*, actor):
    with transaction.atomic():
        actor = _require_permission(actor, "providers.change_performanceapikey")
        record = PerformanceAPIKey.objects.select_for_update().filter(key="primary").first()
        if record is None:
            raise ValidationError("Performance credential is not configured.")
        if record.state == PerformanceAPIKey.State.REVOKED:
            return record, False
        record.encrypted_secret = ""
        record.state = PerformanceAPIKey.State.REVOKED
        record.rotated_at = timezone.now()
        record.save(update_fields=["encrypted_secret", "state", "rotated_at"])
        AuditEvent.objects.create(organization=None, actor=actor,
                                  event_type=AuditEventType.PLATFORM_CREDENTIAL_REVOKED,
                                  details={"kind": "google_performance_api"})
    return record, True


def set_organization_performance_key(*, actor, organization, value):
    if type(value) is not str or not _API_KEY.fullmatch(value):
        raise ValidationError("Provide a bounded performance API key.")
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization.pk)
        require_organization_action(organization=organization, user=actor, action=Action.MANAGE_PROVIDER_CREDENTIAL)
        record = OrganizationPerformanceKey.objects.select_for_update().filter(organization=organization).first()
        if record is None:
            record = OrganizationPerformanceKey(organization=organization)
        record.encrypted_secret = "v1:" + _cipher().encrypt(value.encode()).decode()
        record.state = OrganizationPerformanceKey.State.ACTIVE
        record.rotated_at = timezone.now()
        record.save()
        AuditEvent.objects.create(organization=organization, actor=actor,
                                  event_type=AuditEventType.INTEGRATION_CREDENTIAL_UPDATED,
                                  details={"kind": "google_performance_api", "ownership": "organization"})
    return record


def revoke_organization_performance_key(*, actor, organization):
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization.pk)
        require_organization_action(organization=organization, user=actor, action=Action.MANAGE_PROVIDER_CREDENTIAL)
        record = OrganizationPerformanceKey.objects.select_for_update().filter(organization=organization).first()
        if record is None:
            raise ValidationError("Organization performance credential is not configured.")
        if record.state == OrganizationPerformanceKey.State.REVOKED:
            return record, False
        record.encrypted_secret = ""
        record.state = OrganizationPerformanceKey.State.REVOKED
        record.rotated_at = timezone.now()
        record.save(update_fields=["encrypted_secret", "state", "rotated_at"])
        AuditEvent.objects.create(organization=organization, actor=actor,
                                  event_type=AuditEventType.INTEGRATION_CREDENTIAL_REVOKED,
                                  details={"kind": "google_performance_api", "ownership": "organization"})
    return record, True
