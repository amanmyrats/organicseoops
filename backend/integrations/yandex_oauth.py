"""Project-bound read-only Yandex consent; tokens never pass through the browser."""
import base64
from datetime import timedelta
from hashlib import sha256
import json
import re
import secrets
from urllib.parse import urlencode, urlsplit

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from tenancy.models import AuditEvent, AuditEventType, Organization, Project, normalize_origin
from tenancy.services import Action, project_has_origin, require_project_action
from .oauth import _verified
from .yandex_models import YandexOAuthApplication, YandexOAuthGrant, YandexOAuthIntent
from .yandex_transport import YandexError, yandex_json

CALLBACK = "/api/integrations/yandex/oauth/callback/"
SCOPE = "webmaster:hostinfo"
LIFETIME = timedelta(minutes=10)


@sensitive_variables()
def credential(value, *, limit=4096):
    if type(value) is not str or not 1 <= len(value) <= limit or not re.fullmatch(r"[\x21-\x7e]+", value):
        raise ValidationError("Yandex credential unavailable.")
    return value


@sensitive_variables()
def _cipher():
    keys = settings.YANDEX_OAUTH_ENCRYPTION_KEYS
    if not 1 <= len(keys) <= 5:
        raise YandexError("credential_unavailable")
    try:
        return MultiFernet([Fernet(key.encode()) for key in keys])
    except (TypeError, ValueError):
        raise YandexError("credential_unavailable") from None


@sensitive_variables()
def seal(kind, value):
    return "v1:" + _cipher().encrypt(json.dumps({"kind": kind, "value": value}, separators=(",", ":")).encode()).decode()


@sensitive_variables()
def unseal(kind, value):
    if type(value) is not str or not value.startswith("v1:") or len(value) > 16384:
        raise YandexError("credential_unavailable")
    try:
        payload = json.loads(_cipher().decrypt(value[3:].encode()))
        if type(payload) is not dict or set(payload) != {"kind", "value"} or payload["kind"] != kind:
            raise ValueError
        return payload["value"]
    except (InvalidToken, ValueError, TypeError, UnicodeError, RecursionError):
        raise YandexError("credential_unavailable") from None


def callback_uri(value):
    try:
        parts = urlsplit(value)
        secure = parts.scheme == "https" and bool(parts.hostname) and parts.port in {None, 443}
        local = settings.DEBUG and parts.scheme == "http" and parts.hostname in {"localhost", "127.0.0.1"} and parts.port in {None, 80, 4200, 18000}
        if (type(value) is not str or len(value) > 512 or not (secure or local) or parts.username or parts.password
            or parts.path != CALLBACK or parts.query or parts.fragment):
            raise ValueError
    except (TypeError, ValueError):
        raise ValidationError("Configure the exact Yandex callback URL.") from None
    return value


def lock_application():
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [1740174331])


def _session(session_key):
    if type(session_key) is not str or not 16 <= len(session_key) <= 128 or not session_key.isascii():
        raise PermissionDenied
    return sha256(("yandex-session-v1:" + session_key).encode()).hexdigest()


def _authority(project_id, actor, origin):
    project = Project.objects.select_related("organization").get(pk=project_id)
    require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
    if not _verified(actor) or not project_has_origin(project, origin):
        raise PermissionDenied
    return project


def _application(pk=None):
    app = YandexOAuthApplication.objects.filter(pk=pk).first() if pk else YandexOAuthApplication.objects.filter(key="primary").first()
    if app is None:
        raise YandexError("application_unconfigured")
    callback_uri(app.redirect_uri)
    return app


@sensitive_variables()
def begin_consent(*, project, actor, origin, session_key):
    origin = normalize_origin(origin)
    session_digest = _session(session_key)
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    with transaction.atomic():
        lock_application()
        app = _application()
        Organization.objects.select_for_update().get(pk=project.organization_id)
        Project.objects.select_for_update().get(pk=project.pk, organization_id=project.organization_id)
        project = _authority(project.pk, actor, origin)
        now = timezone.now()
        if YandexOAuthGrant.objects.filter(project=project, origin=origin).exclude(state="revoked").exists():
            raise ValidationError("Disconnect the existing grant for this origin before reconnecting.")
        if YandexOAuthIntent.objects.filter(project=project, origin=origin, status="consumed",
                yandexoauthgrant__isnull=True, user_reported_revoked_at__isnull=True).exists():
            raise ValidationError("Resolve the unknown token exchange before starting fresh consent.")
        YandexOAuthIntent.objects.filter(project=project, actor=actor, status="pending").update(
            status="denied", used_at=now, encrypted_verifier="")
        intent = YandexOAuthIntent.objects.create(organization_id=project.organization_id, project=project, actor=actor,
            application=app, app_revision=app.revision, origin=origin, state_digest=sha256(state.encode()).hexdigest(),
            session_digest=session_digest, encrypted_verifier=seal("pkce", verifier), expires_at=now + LIFETIME)
    challenge = base64.urlsafe_b64encode(sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return "https://oauth.yandex.ru/authorize?" + urlencode({"response_type": "code", "client_id": app.client_id,
        "redirect_uri": app.redirect_uri, "scope": SCOPE, "force_confirm": "yes", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256", "device_id": str(intent.device_id),
        "device_name": "OrganicSEOOps project connection"})


def _exchange_checkpoint(intent, actor):
    project = _authority(intent.project_id, actor, intent.origin)
    app = _application(intent.application_id)
    if (project.organization_id != intent.organization_id or app.revision != intent.app_revision
        or timezone.now() >= intent.expires_at
        or not YandexOAuthIntent.objects.filter(pk=intent.pk, status="consumed", actor=actor).exists()):
        raise PermissionDenied


@sensitive_variables()
def _tokens(payload):
    if (type(payload) is not dict or str(payload.get("token_type", "")).lower() != "bearer"
        or type(payload.get("expires_in")) is not int or not 1 <= payload["expires_in"] <= 315360000):
        raise YandexError("malformed_response")
    access = credential(payload.get("access_token"))
    refresh = credential(payload["refresh_token"]) if payload.get("refresh_token") else None
    scope = payload.get("scope")
    if scope is not None and (type(scope) is not str or set(scope.split()) != {SCOPE}):
        raise YandexError("scope_unavailable")
    return {"access_token": access, "refresh_token": refresh}, timezone.now() + timedelta(seconds=payload["expires_in"])


def verified_host(payload, *, origin):
    if type(payload) is not dict or type(payload.get("hosts")) is not list or len(payload["hosts"]) > 500:
        raise YandexError("malformed_response")
    matches = []
    for item in payload["hosts"]:
        if type(item) is not dict or item.get("verified") is not True:
            continue
        try:
            host_origin = normalize_origin(item.get("ascii_host_url"))
        except ValidationError:
            continue
        if host_origin != origin:
            continue
        host_id = credential(item.get("host_id"), limit=512)
        parts = urlsplit(origin)
        if host_id != f"{parts.scheme}:{parts.hostname}:{parts.port or (443 if parts.scheme == 'https' else 80)}":
            raise YandexError("property_unavailable")
        # A mirror does not authorize exposing or querying a different origin.
        mirror = item.get("main_mirror")
        if mirror and (type(mirror) is not dict or normalize_origin(mirror.get("ascii_host_url")) != origin):
            raise YandexError("property_unavailable")
        matches.append(host_id)
    if len(matches) != 1:
        raise YandexError("verified_property_unavailable")
    return matches[0]


@sensitive_variables()
def complete_consent(*, actor, session_key, state, callback_url, code=None, denied=False):
    if type(state) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", state):
        raise ValidationError("Yandex consent is invalid or expired.")
    digest = sha256(state.encode()).hexdigest()
    identity = YandexOAuthIntent.objects.filter(state_digest=digest).values("organization_id", "project_id", "application_id").first()
    if identity is None:
        raise PermissionDenied
    if not denied:
        code = credential(code, limit=2048)
    with transaction.atomic():
        lock_application()
        app = _application(identity["application_id"])
        Organization.objects.select_for_update().get(pk=identity["organization_id"])
        Project.objects.select_for_update().get(pk=identity["project_id"])
        intent = YandexOAuthIntent.objects.select_for_update().get(state_digest=digest)
        if (intent.actor_id != actor.pk or intent.session_digest != _session(session_key) or intent.status != "pending"
            or callback_url != app.redirect_uri or app.revision != intent.app_revision):
            raise PermissionDenied
        expired = timezone.now() >= intent.expires_at
        try:
            _authority(intent.project_id, actor, intent.origin)
            authorized = True
        except PermissionDenied:
            authorized = False
        verifier = unseal("pkce", intent.encrypted_verifier) if not denied and not expired and authorized else None
        client_secret = credential(unseal("application", app.encrypted_secret)) if verifier else None
        intent.status = "consumed" if verifier else "denied"
        intent.used_at = timezone.now()
        intent.encrypted_verifier = ""
        intent.save(update_fields=["status", "used_at", "encrypted_verifier"])
    if verifier is None:
        raise YandexError("consent_denied_or_expired")
    checkpoint = lambda: _exchange_checkpoint(intent, actor)
    payload = yandex_json("/token", form={"grant_type": "authorization_code", "code": code,
        "client_id": app.client_id, "client_secret": client_secret,
        "redirect_uri": app.redirect_uri, "code_verifier": verifier, "device_id": str(intent.device_id),
        "device_name": "OrganicSEOOps project connection"}, checkpoint=checkpoint, limit=16384)
    # Retain every issued credential before any permission or property operation can fail.
    raw_access = credential(payload.get("access_token"))
    try:
        raw_refresh = credential(payload["refresh_token"]) if payload.get("refresh_token") else None
    except ValidationError:
        raw_refresh = None  # Retain the issued access token so malformed responses remain revocable.
    encrypted = seal("tokens", {"access_token": raw_access, "refresh_token": raw_refresh})
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=intent.organization_id)
        Project.objects.select_for_update().get(pk=intent.project_id)
        if YandexOAuthIntent.objects.filter(pk=intent.pk, user_reported_revoked_at__isnull=False).exists():
            raise PermissionDenied
        grant = YandexOAuthGrant.objects.create(organization_id=intent.organization_id, project_id=intent.project_id,
            actor_id=intent.actor_id, intent=intent, application_id=intent.application_id, origin=intent.origin,
            encrypted_tokens=encrypted, expires_at=timezone.now(), state="revocation_pending")
    tokens, expiry = _tokens(payload)
    user = yandex_json("/v4/user", token=tokens["access_token"], checkpoint=checkpoint, limit=4096)
    user_id = user.get("user_id")
    if type(user_id) is not int or not 1 <= user_id <= 9223372036854775807:
        raise YandexError("malformed_response")
    hosts = yandex_json(f"/v4/user/{user_id}/hosts", token=tokens["access_token"], checkpoint=checkpoint)
    host_id = verified_host(hosts, origin=intent.origin)
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=intent.organization_id)
        Project.objects.select_for_update().get(pk=intent.project_id)
        current = YandexOAuthGrant.objects.select_for_update().get(pk=grant.pk)
        checkpoint()
        if current.state != "revocation_pending" or current.revision != 0:
            raise PermissionDenied
        if YandexOAuthGrant.objects.filter(project_id=intent.project_id, origin=intent.origin, state="active").exclude(pk=current.pk).exists():
            raise ValidationError("This origin already has an active grant; disconnect the duplicate pending grant.")
        current.user_id, current.host_id = str(user_id), host_id
        current.expires_at, current.state = expiry, "active"
        current.revision += 1
        current.save(update_fields=["user_id", "host_id", "expires_at", "state", "revision", "updated_at"])
        AuditEvent.objects.create(organization_id=intent.organization_id, project_id=intent.project_id, actor=actor,
            event_type=AuditEventType.INTEGRATION_CREDENTIAL_UPDATED, details={"kind": "yandex_oauth_connected", "grant_id": current.pk})
    return current


@sensitive_variables()
def revoke_grant(*, grant_id, actor=None, expected_revision=None, closed=False):
    grant = YandexOAuthGrant.objects.get(pk=grant_id)
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=grant.organization_id)
        project = Project.objects.select_for_update().select_related("organization").get(pk=grant.project_id)
        current = YandexOAuthGrant.objects.select_for_update().get(pk=grant_id)
        if closed:
            from tenancy.closure_grants import _revocation_authorized
            if not _revocation_authorized(organization):
                raise PermissionDenied
        else:
            require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
            if type(expected_revision) is not int or current.revision != expected_revision:
                raise ValidationError("Yandex grant changed; refresh before disconnecting.")
        if current.state == "revoked":
            return current
        if current.refresh_started_at:
            raise ValidationError("Resolve the unknown refresh through explicit completed remote-revocation reporting.")
        if current.state != "revocation_pending":
            current.state = "revocation_pending"
            current.revision += 1
            current.save(update_fields=["state", "revision", "updated_at"])
        if current.connection_id:
            from .models import IntegrationConnection
            IntegrationConnection.objects.filter(pk=current.connection_id, project_id=current.project_id).update(
                state="disconnected", updated_at=timezone.now())
        revision, encrypted = current.revision, current.encrypted_tokens
    app = _application(current.application_id)
    def checkpoint():
        if not YandexOAuthGrant.objects.filter(pk=grant_id, state="revocation_pending", revision=revision, encrypted_tokens=encrypted).exists():
            raise PermissionDenied
    tokens = unseal("tokens", encrypted)
    response = yandex_json("/revoke_token", form={"access_token": credential(tokens["access_token"]),
        "client_id": app.client_id, "client_secret": credential(unseal("application", app.encrypted_secret))}, checkpoint=checkpoint, limit=4096)
    if response != {"status": "ok"}:
        raise YandexError("revocation_unconfirmed")
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=current.organization_id)
        current = YandexOAuthGrant.objects.select_for_update().get(pk=grant_id)
        checkpoint()
        current.state, current.encrypted_tokens, current.user_id, current.host_id = "revoked", "", "", ""
        current.revoked_at = timezone.now()
        current.revision += 1
        current.save(update_fields=["state", "encrypted_tokens", "user_id", "host_id", "revoked_at", "revision", "updated_at"])
        AuditEvent.objects.create(organization_id=current.organization_id, project_id=current.project_id,
            actor=actor or current.actor, event_type=AuditEventType.INTEGRATION_CREDENTIAL_REVOKED,
            details={"kind": "yandex_oauth_revoked", "grant_id": current.pk})
    return current


def report_unknown_exchange_revoked(*, intent_id, actor):
    intent = YandexOAuthIntent.objects.get(pk=intent_id)
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=intent.organization_id)
        project = Project.objects.select_for_update().select_related("organization").get(pk=intent.project_id)
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        if not _verified(actor):
            raise PermissionDenied
        current = YandexOAuthIntent.objects.select_for_update().get(pk=intent_id)
        if (current.status != "consumed" or YandexOAuthGrant.objects.filter(intent=current).exists()
            or current.used_at > timezone.now() - LIFETIME):
            raise ValidationError("Wait for the token exchange to finish and inspect current status.")
        if current.user_reported_revoked_at is None:
            YandexOAuthIntent.objects.filter(pk=current.pk, user_reported_revoked_at__isnull=True).update(user_reported_revoked_at=timezone.now())
            AuditEvent.objects.create(organization_id=current.organization_id, project_id=current.project_id, actor=actor,
                event_type=AuditEventType.INTEGRATION_CREDENTIAL_REVOKED,
                details={"kind": "yandex_unknown_exchange_user_reported_revoked", "intent_id": current.pk,
                    "evidence": "human_attestation_not_provider_verification"})
