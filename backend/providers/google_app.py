from dataclasses import dataclass
from datetime import timedelta

from cryptography.fernet import InvalidToken
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.db.models import F, Q
from django.utils import timezone

from integrations.google_tokens import GoogleTokenError, _cipher, _credential
from integrations.models import GoogleOAuthGrant, GoogleOAuthIntent
from integrations.oauth import configured_redirect_uri
from tenancy.models import AuditEvent, AuditEventType

from .models import GoogleOAuthApplication
from .services import _require_permission


@dataclass(frozen=True, repr=False)
class GoogleOAuthClient:
    client_id: str
    client_secret: str
    redirect_uri: str


def google_oauth_client(*, require_redirect=True):
    record = GoogleOAuthApplication.objects.filter(key="primary").first()
    if record is None:
        client_id = _credential(settings.GOOGLE_OAUTH_CLIENT_ID, limit=512)
        client_secret = _credential(settings.GOOGLE_OAUTH_CLIENT_SECRET, limit=512)
        redirect_uri = (configured_redirect_uri(value=settings.GOOGLE_OAUTH_REDIRECT_URI)
                        if require_redirect or settings.GOOGLE_OAUTH_REDIRECT_URI else "")
        _cipher()
        return GoogleOAuthClient(client_id, client_secret, redirect_uri)
    if record.state != GoogleOAuthApplication.State.ACTIVE:
        raise GoogleTokenError("credential_unavailable")
    try:
        client_id = _credential(record.client_id, limit=512)
        redirect_uri = configured_redirect_uri(value=record.redirect_uri)
        if not record.encrypted_secret.startswith("v1:") or len(record.encrypted_secret) > 8192:
            raise ValueError
        secret = _cipher().decrypt(record.encrypted_secret[3:].encode()).decode()
        return GoogleOAuthClient(client_id, _credential(secret, limit=512), redirect_uri)
    except (InvalidToken, UnicodeError, ValueError, ValidationError):
        raise GoogleTokenError("credential_unavailable") from None


def google_analytics_oauth_client():
    from integrations.ga4_oauth import _cipher as analytics_cipher, configured_ga4_redirect_uri

    record = GoogleOAuthApplication.objects.filter(key="analytics").first()
    if record is None or record.state != GoogleOAuthApplication.State.ACTIVE:
        raise GoogleTokenError("credential_unavailable")
    try:
        client_id = _credential(record.client_id, limit=512)
        redirect_uri = configured_ga4_redirect_uri(value=record.redirect_uri)
        if not record.encrypted_secret.startswith("v1:") or len(record.encrypted_secret) > 8192:
            raise ValueError
        secret = analytics_cipher().decrypt(record.encrypted_secret[3:].encode()).decode()
        return GoogleOAuthClient(client_id, _credential(secret, limit=512), redirect_uri)
    except (InvalidToken, UnicodeError, ValueError, ValidationError):
        raise GoogleTokenError("credential_unavailable") from None


def _no_active_google_grants(key="primary"):
    if key == "business_profile":
        from integrations.models import BusinessProfileOAuthGrant, BusinessProfileOAuthIntent
        grants = BusinessProfileOAuthGrant.objects.exclude(state=BusinessProfileOAuthGrant.State.REVOKED).exists()
        intents = BusinessProfileOAuthIntent.objects
    elif key == "analytics":
        from integrations.models import GA4OAuthGrant, GA4OAuthIntent
        grants = GA4OAuthGrant.objects.exclude(state=GA4OAuthGrant.State.REVOKED).exists()
        intents = GA4OAuthIntent.objects
    else:
        grants = GoogleOAuthGrant.objects.exclude(state=GoogleOAuthGrant.State.REVOKED).exists()
        intents = GoogleOAuthIntent.objects
    if (grants or intents.filter(
            Q(status=GoogleOAuthIntent.Status.PENDING, expires_at__gt=timezone.now())
            | Q(status=GoogleOAuthIntent.Status.CONSUMED, used_at__gt=timezone.now() - timedelta(minutes=10))
        ).exists()):
        raise ValidationError("Disconnect existing Google grants and finish pending consent first.")


def lock_google_application():
    # Serialize app creation/rotation against new OAuth intents even before a config row exists.
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [1740174327])


def set_google_oauth_application(*, actor, client_id, client_secret, redirect_uri, key="primary"):
    if key not in {"primary", "analytics", "business_profile"}:
        raise ValidationError("Unsupported Google application.")
    if key == "business_profile":
        from integrations.business_profile_tokens import _cipher as app_cipher, configured_business_redirect_uri as callback
    elif key == "analytics":
        from integrations.ga4_oauth import _cipher as app_cipher, configured_ga4_redirect_uri as callback
    else:
        app_cipher, callback = _cipher, configured_redirect_uri
    client_id = _credential(client_id, limit=512)
    client_secret = _credential(client_secret, limit=512)
    redirect_uri = callback(value=redirect_uri)
    with transaction.atomic():
        lock_google_application()
        record = GoogleOAuthApplication.objects.select_for_update().filter(key=key).first()
        permission = "providers.change_googleoauthapplication" if record else "providers.add_googleoauthapplication"
        actor = _require_permission(actor, permission)
        _no_active_google_grants(key)
        if record is None:
            record = GoogleOAuthApplication(key=key)
        record.client_id = client_id
        record.redirect_uri = redirect_uri
        plaintext = "gbp-app-v1:" + client_secret if key == "business_profile" else client_secret
        record.encrypted_secret = "v1:" + app_cipher().encrypt(plaintext.encode()).decode()
        record.state = GoogleOAuthApplication.State.ACTIVE
        record.rotated_at = timezone.now()
        record.save()
        AuditEvent.objects.create(organization=None, actor=actor,
                                  event_type=AuditEventType.PLATFORM_CREDENTIAL_UPDATED,
                                   details={"kind": {"primary": "google_oauth_application",
                                       "analytics": "google_analytics_oauth_application",
                                       "business_profile": "google_business_oauth_application"}[key], "application": key})
    return record


def revoke_google_oauth_application(*, actor, key="primary"):
    if key not in {"primary", "analytics", "business_profile"}:
        raise ValidationError("Unsupported Google application.")
    with transaction.atomic():
        lock_google_application()
        actor = _require_permission(actor, "providers.change_googleoauthapplication")
        record = GoogleOAuthApplication.objects.select_for_update().filter(key=key).first()
        if record is None:
            raise ValidationError("Google OAuth application is not configured.")
        if record.state == GoogleOAuthApplication.State.REVOKED:
            return record, False
        if key == "business_profile":
            from integrations.models import BusinessProfileOAuthGrant, BusinessProfileOAuthIntent
            now = timezone.now()
            BusinessProfileOAuthIntent.objects.filter(status=BusinessProfileOAuthIntent.Status.PENDING).update(
                status=BusinessProfileOAuthIntent.Status.DENIED, used_at=now)
            BusinessProfileOAuthGrant.objects.exclude(state__in=[BusinessProfileOAuthGrant.State.REVOKED,
                BusinessProfileOAuthGrant.State.REVOCATION_PENDING]).update(
                state=BusinessProfileOAuthGrant.State.REVOCATION_PENDING, revision=F("revision") + 1, updated_at=now)
        elif key == "analytics":
            from integrations.models import GA4OAuthGrant, GA4OAuthIntent, IntegrationConnection
            now = timezone.now()
            GA4OAuthIntent.objects.filter(status=GA4OAuthIntent.Status.PENDING).update(
                status=GA4OAuthIntent.Status.DENIED, used_at=now)
            GA4OAuthGrant.objects.exclude(state=GA4OAuthGrant.State.REVOKED).update(
                state=GA4OAuthGrant.State.REVOCATION_PENDING, revision=F("revision") + 1, updated_at=now)
            IntegrationConnection.objects.filter(provider="google_analytics_4").exclude(
                state=IntegrationConnection.State.DISCONNECTED).update(
                    state=IntegrationConnection.State.DISCONNECTED, updated_at=now)
        else:
            _no_active_google_grants(key)
        record.state = GoogleOAuthApplication.State.REVOKED
        record.encrypted_secret = ""
        record.rotated_at = timezone.now()
        record.save(update_fields=["state", "encrypted_secret", "rotated_at"])
        AuditEvent.objects.create(organization=None, actor=actor,
                                  event_type=AuditEventType.PLATFORM_CREDENTIAL_REVOKED,
                                   details={"kind": {"primary": "google_oauth_application",
                                       "analytics": "google_analytics_oauth_application",
                                       "business_profile": "google_business_oauth_application"}[key], "application": key})
    return record, True


def google_business_oauth_client():
    from integrations.business_profile_tokens import _cipher as business_cipher, configured_business_redirect_uri

    record = GoogleOAuthApplication.objects.filter(key="business_profile", state=GoogleOAuthApplication.State.ACTIVE).first()
    if record is None:
        raise GoogleTokenError("credential_unavailable")
    try:
        client_id = _credential(record.client_id, limit=512)
        redirect_uri = configured_business_redirect_uri(record.redirect_uri)
        if not record.encrypted_secret.startswith("v1:") or len(record.encrypted_secret) > 8192:
            raise ValueError
        value = business_cipher().decrypt(record.encrypted_secret[3:].encode()).decode()
        if not value.startswith("gbp-app-v1:"):
            raise ValueError
        return GoogleOAuthClient(client_id, _credential(value[len("gbp-app-v1:"):], limit=512), redirect_uri)
    except (InvalidToken, UnicodeError, ValueError, ValidationError):
        raise GoogleTokenError("credential_unavailable") from None
