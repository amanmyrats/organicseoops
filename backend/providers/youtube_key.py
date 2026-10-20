from cryptography.fernet import InvalidToken
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from jobs.performance_transport import _API_KEY
from tenancy.models import AuditEvent, AuditEventType
from .models import YouTubeAPIKey
from .services import _provider_cipher, _require_permission


@sensitive_variables()
def set_youtube_key(*, actor, value, api_project, daily_limit):
    if (type(value) is not str or not _API_KEY.fullmatch(value)
        or type(api_project) is not str or type(daily_limit) is not int or not 1 <= daily_limit <= 100):
        raise ValidationError("Provide a dedicated YouTube key, client API project and bounded daily ceiling.")
    with transaction.atomic():
        record = YouTubeAPIKey.objects.select_for_update().filter(key="primary").first()
        actor = _require_permission(actor, "providers.change_youtubeapikey" if record else "providers.add_youtubeapikey")
        if record is None:
            record = YouTubeAPIKey(key="primary", api_project=api_project)
        if record.api_project != api_project:
            raise ValidationError("Keep this API Client's original Google API project.")
        record.encrypted_secret = "v1:" + _provider_cipher().encrypt(value.encode()).decode()
        record.state = "active"
        record.daily_limit = daily_limit
        record.rotated_at = timezone.now()
        record.save()
        AuditEvent.objects.create(organization=None, actor=actor,
            event_type=AuditEventType.PLATFORM_CREDENTIAL_UPDATED, details={"kind": "youtube_search_api"})
    return record


def revoke_youtube_key(*, actor):
    with transaction.atomic():
        actor = _require_permission(actor, "providers.change_youtubeapikey")
        record = YouTubeAPIKey.objects.select_for_update().filter(key="primary").first()
        if record is None:
            raise ValidationError("YouTube credential is not configured.")
        changed = record.state != "revoked"
        if changed:
            record.state = "revoked"
            record.encrypted_secret = ""
            record.rotated_at = timezone.now()
            record.save(update_fields=["state", "encrypted_secret", "rotated_at"])
            AuditEvent.objects.create(organization=None, actor=actor,
                event_type=AuditEventType.PLATFORM_CREDENTIAL_REVOKED, details={"kind": "youtube_search_api"})
        return record, changed


@sensitive_variables()
def youtube_key(expected_revision):
    record = YouTubeAPIKey.objects.filter(key="primary", state="active").first()
    if record is None or record.rotated_at.isoformat() != expected_revision:
        raise ValidationError("YouTube credential is unavailable or changed.")
    try:
        if not record.encrypted_secret.startswith("v1:") or len(record.encrypted_secret) > 8192:
            raise ValueError
        value = _provider_cipher().decrypt(record.encrypted_secret[3:].encode()).decode()
        if not _API_KEY.fullmatch(value):
            raise ValueError
        return value
    except (InvalidToken, ValueError, UnicodeError):
        raise ValidationError("YouTube credential is unavailable.") from None
