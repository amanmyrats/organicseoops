"""Separate GA4 browser intent and refresh-token boundary; Search Console consent is never reused."""

import hashlib
import secrets
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from tenancy.models import AuditEvent, AuditEventType, Organization, Project
from tenancy.services import Action, require_project_action

from .google_tokens import (GoogleTokenError, GoogleTokens, _credential,
                            _parse_tokens, post_google_revoke_form, post_google_token_form)
from .models import GA4OAuthGrant, GA4OAuthIntent, IntegrationConnection
from .oauth import INTENT_LIFETIME, OAuthStateError, _STATE, _verified, _session_digest
from .ga4_properties import eligible_ga4_property
from .ga4_transport import (ga4_admin_property_get, ga4_admin_streams_list,
                            ga4_check_landing_compatibility)


CALLBACK_PATH = "/api/integrations/google-analytics/oauth/callback/"
SCOPE = "https://www.googleapis.com/auth/analytics.readonly"


def configured_ga4_redirect_uri(value=None):
    if value is None:
        from providers.models import GoogleOAuthApplication
        if GoogleOAuthApplication.objects.filter(key="analytics").exists():
            from providers.google_app import google_analytics_oauth_client
            value = google_analytics_oauth_client().redirect_uri
        else:
            value = getattr(settings, "GOOGLE_ANALYTICS_REDIRECT_URI", "")
    if type(value) is not str or len(value) > 512:
        raise ValidationError("GA4 OAuth callback is unavailable.")
    try:
        parsed = urlsplit(value)
        valid_host = (parsed.scheme == "https" and bool(parsed.hostname) and parsed.port in {None, 443}) or (
            settings.DEBUG and parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
            and parsed.port in {None, 80, 4200, 18000})
    except ValueError:
        valid_host = False
    if (not valid_host or parsed.username or parsed.password or parsed.path != CALLBACK_PATH
        or parsed.query or parsed.fragment):
        raise ValidationError("GA4 OAuth callback is unavailable.")
    return value


def begin_ga4_oauth_intent(*, project, user, session_key):
    digest = _session_digest(session_key)
    state = secrets.token_urlsafe(32)
    now = timezone.now()
    with transaction.atomic():
        from providers.google_app import lock_google_application
        lock_google_application()
        redirect_uri = configured_ga4_redirect_uri()
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        require_project_action(project=project, user=user, action=Action.MANAGE_PROJECT)
        if not _verified(user):
            raise PermissionDenied
        GA4OAuthIntent.objects.filter(project=project, actor=user, status=GA4OAuthIntent.Status.PENDING).update(
            status=GA4OAuthIntent.Status.DENIED, used_at=now)
        intent = GA4OAuthIntent.objects.create(organization=organization, project=project, actor=user,
            state_digest=hashlib.sha256(state.encode()).hexdigest(), session_digest=digest,
            redirect_uri=redirect_uri, expires_at=now + INTENT_LIFETIME)
    return intent, state


def consume_ga4_oauth_intent(*, user, session_key, state, callback_url, provider_denied=False):
    if (type(state) is not str or not _STATE.fullmatch(state)
        or type(provider_denied) is not bool or callback_url != configured_ga4_redirect_uri()):
        raise OAuthStateError("GA4 OAuth state is invalid or expired.")
    digest = hashlib.sha256(state.encode()).hexdigest()
    identity = GA4OAuthIntent.objects.filter(state_digest=digest).values_list("organization_id", "project_id").first()
    if identity is None:
        raise OAuthStateError("GA4 OAuth state is invalid or expired.")
    session_digest = _session_digest(session_key)
    outcome = ""
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=identity[0])
        project = Project.objects.select_for_update().get(pk=identity[1], organization=organization)
        intent = GA4OAuthIntent.objects.select_for_update().get(state_digest=digest, project=project,
                                                                 organization=organization)
        if intent.actor_id != getattr(user, "pk", None) or intent.session_digest != session_digest:
            raise PermissionDenied
        if intent.status != GA4OAuthIntent.Status.PENDING:
            raise OAuthStateError("GA4 OAuth state is invalid or expired.")
        now = timezone.now()
        if intent.expires_at <= now or intent.redirect_uri != configured_ga4_redirect_uri():
            outcome = "expired"
        else:
            try:
                require_project_action(project=project, user=user, action=Action.MANAGE_PROJECT)
                if not _verified(user):
                    raise PermissionDenied
            except PermissionDenied:
                outcome = "access_revoked"
        intent.status = GA4OAuthIntent.Status.DENIED if outcome or provider_denied else GA4OAuthIntent.Status.CONSUMED
        intent.used_at = now
        intent.save(update_fields=["status", "used_at"])
    if outcome:
        raise OAuthStateError("GA4 OAuth state is invalid or expired.")
    return intent


def _cipher():
    keys = getattr(settings, "GOOGLE_ANALYTICS_ENCRYPTION_KEYS", ())
    if type(keys) not in {tuple, list} or not 1 <= len(keys) <= 5:
        raise GoogleTokenError("credential_unavailable")
    try:
        return MultiFernet([Fernet(key.encode()) for key in keys])
    except (ValueError, TypeError, AttributeError):
        raise GoogleTokenError("credential_unavailable") from None


def encrypt_ga4_refresh_token(token):
    _credential(token)
    return "v1:" + _cipher().encrypt(token.encode()).decode()


def decrypt_ga4_refresh_token(encrypted):
    if type(encrypted) is not str or not encrypted.startswith("v1:") or len(encrypted) > 8192:
        raise GoogleTokenError("credential_unavailable")
    try:
        return _cipher().decrypt(encrypted[3:].encode()).decode()
    except (InvalidToken, ValueError, UnicodeError):
        raise GoogleTokenError("credential_unavailable") from None


def complete_ga4_oauth(*, user, session_key, state, callback_url, code, client_id, client_secret,
                       transport=post_google_token_form):
    intent = consume_ga4_oauth_intent(user=user, session_key=session_key, state=state, callback_url=callback_url)
    _credential(code, limit=2048)
    _credential(client_id, limit=512)
    _credential(client_secret, limit=512)
    tokens = _parse_tokens(transport(form={"code": code, "client_id": client_id,
        "client_secret": client_secret, "grant_type": "authorization_code",
        "redirect_uri": intent.redirect_uri}), needs_refresh=True, expected_scope=SCOPE)
    if not isinstance(tokens, GoogleTokens) or tokens.refresh_token is None:
        raise GoogleTokenError("reauthorization_required")
    encrypted = encrypt_ga4_refresh_token(tokens.refresh_token)
    with transaction.atomic():
        from providers.google_app import lock_google_application
        from providers.models import GoogleOAuthApplication
        lock_google_application()
        app_revoked = GoogleOAuthApplication.objects.filter(
            key="analytics", state=GoogleOAuthApplication.State.REVOKED).exists()
        organization = Organization.objects.select_for_update().get(pk=intent.organization_id)
        project = Project.objects.select_for_update().get(pk=intent.project_id, organization=organization)
        try:
            require_project_action(project=project, user=user, action=Action.MANAGE_PROJECT)
            allowed = _verified(user)
        except PermissionDenied:
            allowed = False
        return GA4OAuthGrant.objects.create(organization=organization, project=project, actor_id=intent.actor_id,
            encrypted_refresh_token=encrypted, scope=SCOPE, verified_at=timezone.now(),
            state=GA4OAuthGrant.State.PENDING_SELECTION if allowed and not app_revoked else GA4OAuthGrant.State.REVOCATION_PENDING)


def refresh_ga4_tokens(*, encrypted_refresh, client_id, client_secret, transport=post_google_token_form):
    _credential(client_id, limit=512)
    _credential(client_secret, limit=512)
    return _parse_tokens(transport(form={"refresh_token": decrypt_ga4_refresh_token(encrypted_refresh),
        "client_id": client_id, "client_secret": client_secret, "grant_type": "refresh_token"}),
        needs_refresh=False, expected_scope=SCOPE)


def select_ga4_property(*, grant, user, property_id, origin, expected_revision, client_id, client_secret,
                        refresh=refresh_ga4_tokens, get_property=ga4_admin_property_get,
                        list_streams=ga4_admin_streams_list, check_compatibility=ga4_check_landing_compatibility):
    if (type(expected_revision) is not int or expected_revision < 0 or type(origin) is not str
        or type(property_id) is not str or len(property_id) > 20):
        raise ValidationError("Choose a current GA4 grant, origin and property.")
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=grant.organization_id)
        project = Project.objects.select_for_update().get(pk=grant.project_id, organization=organization)
        require_project_action(project=project, user=user, action=Action.MANAGE_PROJECT)
        current = GA4OAuthGrant.objects.select_for_update().get(pk=grant.pk, project=project, organization=organization)
        if (current.revision != expected_revision or current.state != GA4OAuthGrant.State.PENDING_SELECTION
            or current.property_id or current.verified_at < timezone.now() - INTENT_LIFETIME or not _verified(user)):
            raise ValidationError("GA4 consent or selection changed.")
        encrypted = current.encrypted_refresh_token
    tokens = refresh(encrypted_refresh=encrypted, client_id=client_id, client_secret=client_secret)
    if not isinstance(tokens, GoogleTokens):
        raise GoogleTokenError("malformed_response")
    property_response = get_property(property_id=property_id, access_token=tokens.access_token)
    streams_response = list_streams(property_id=property_id, access_token=tokens.access_token)
    candidates = eligible_ga4_property(project=project, user=user, property_id=property_id,
        property_response=property_response, streams_response=streams_response)
    if origin not in candidates["matched_origins"] or not check_compatibility(
        property_id=property_id, approved_origin=origin, access_token=tokens.access_token):
        raise ValidationError("Choose an exact GA4 web origin with compatible reporting columns.")
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=grant.organization_id)
        project = Project.objects.select_for_update().get(pk=grant.project_id, organization=organization)
        require_project_action(project=project, user=user, action=Action.MANAGE_PROJECT)
        current = GA4OAuthGrant.objects.select_for_update().get(pk=grant.pk, project=project, organization=organization)
        if (current.revision != expected_revision or current.state != GA4OAuthGrant.State.PENDING_SELECTION
            or current.property_id or current.encrypted_refresh_token != encrypted or not _verified(user)):
            raise ValidationError("GA4 consent or property selection changed.")
        rechecked = eligible_ga4_property(project=project, user=user, property_id=property_id,
            property_response=property_response, streams_response=streams_response)
        if origin not in rechecked["matched_origins"]:
            raise ValidationError("GA4 web origin changed while validating the property.")
        current.property_id = property_id
        current.selected_origins = [origin]
        current.revision += 1
        current.save(update_fields=["property_id", "selected_origins", "revision", "updated_at"])
        AuditEvent.objects.create(organization=organization, project=project, actor=user,
            event_type=AuditEventType.GA4_PROPERTY_SELECTED,
            details={"grant_id": current.pk, "property_id": property_id, "origin": origin})
        # Remains disabled until a GA4-only source connection is linked and the scope is rechecked.
        return current


def link_ga4_source(*, grant, user, expected_revision, client_id, client_secret,
                    refresh=refresh_ga4_tokens, get_property=ga4_admin_property_get,
                    list_streams=ga4_admin_streams_list, check_compatibility=ga4_check_landing_compatibility):
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValidationError("Choose a current GA4 grant revision.")
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=grant.organization_id)
        project = Project.objects.select_for_update().get(pk=grant.project_id, organization=organization)
        require_project_action(project=project, user=user, action=Action.MANAGE_PROJECT)
        current = GA4OAuthGrant.objects.select_for_update().get(pk=grant.pk, project=project, organization=organization)
        if (current.state != GA4OAuthGrant.State.PENDING_SELECTION or current.revision != expected_revision
            or not current.property_id or len(current.selected_origins) != 1 or not _verified(user)):
            raise ValidationError("Choose one consent-selected GA4 web origin.")
        property_id, origin, encrypted = current.property_id, current.selected_origins[0], current.encrypted_refresh_token
    tokens = refresh(encrypted_refresh=encrypted, client_id=client_id, client_secret=client_secret)
    if not isinstance(tokens, GoogleTokens):
        raise GoogleTokenError("malformed_response")
    property_response = get_property(property_id=property_id, access_token=tokens.access_token)
    streams_response = list_streams(property_id=property_id, access_token=tokens.access_token)
    candidate = eligible_ga4_property(project=project, user=user, property_id=property_id,
        property_response=property_response, streams_response=streams_response)
    if origin not in candidate["matched_origins"] or not check_compatibility(
        property_id=property_id, approved_origin=origin, access_token=tokens.access_token):
        raise ValidationError("The Analytics property is no longer scoped to this origin.")
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=grant.organization_id)
        project = Project.objects.select_for_update().get(pk=grant.project_id, organization=organization)
        require_project_action(project=project, user=user, action=Action.MANAGE_PROJECT)
        current = GA4OAuthGrant.objects.select_for_update().get(pk=grant.pk, project=project, organization=organization)
        if (current.state != GA4OAuthGrant.State.PENDING_SELECTION or current.revision != expected_revision
            or current.property_id != property_id or current.selected_origins != [origin]
            or current.encrypted_refresh_token != encrypted or not _verified(user)):
            raise ValidationError("GA4 property selection changed before source linking.")
        candidate = eligible_ga4_property(project=project, user=user, property_id=property_id,
            property_response=property_response, streams_response=streams_response)
        if origin not in candidate["matched_origins"]:
            raise ValidationError("GA4 project web scope changed before source linking.")
        connection = IntegrationConnection.objects.select_for_update().filter(
            project=project, provider="google_analytics_4", external_property_id=property_id).first()
        if connection is not None and connection.credential_reference != current.credential_reference:
            previous = GA4OAuthGrant.objects.select_for_update().filter(
                project=project, organization=organization,
                credential_reference=connection.credential_reference).first()
            if (connection.state != IntegrationConnection.State.DISCONNECTED or previous is None
                or previous.state != GA4OAuthGrant.State.REVOKED or previous.encrypted_refresh_token
                or previous.property_id or previous.selected_origins):
                raise ValidationError("Disconnect and finish revoking the previous Analytics grant first.")
        current.state = GA4OAuthGrant.State.ACTIVE
        current.revision += 1
        current.save(update_fields=["state", "revision", "updated_at"])
        if connection is None:
            connection = IntegrationConnection(project=project, provider="google_analytics_4",
                external_property_id=property_id, credential_reference=current.credential_reference,
                capabilities=["api_sync", "landing_metrics"], available_dimensions=["hostname", "landing_page"],
                source_semantics="ga4_landing_pages", source_semantics_version="ga4-data-v1",
                timezone=candidate["timezone"], currency=candidate["currency"], backfill_limit_days=90)
        elif connection.timezone != candidate["timezone"] or connection.currency != candidate["currency"]:
            raise ValidationError("GA4 reporting timezone or currency changed; reconnect before linking.")
        else:
            connection.credential_reference = current.credential_reference
            connection.state = IntegrationConnection.State.ACTIVE
        connection.save()
        AuditEvent.objects.create(organization=organization, project=project, actor=user,
            event_type=AuditEventType.GA4_SOURCE_CONNECTED,
            details={"grant_id": current.pk, "connection_id": connection.pk,
                     "property_id": property_id, "origin": origin})
        return current, connection


def revoke_ga4_grant(*, grant, user, revoke=post_google_revoke_form):
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=grant.organization_id)
        project = Project.objects.select_for_update().get(pk=grant.project_id, organization=organization)
        require_project_action(project=project, user=user, action=Action.MANAGE_PROJECT)
        current = GA4OAuthGrant.objects.select_for_update().get(pk=grant.pk, project=project, organization=organization)
        if current.state == GA4OAuthGrant.State.REVOKED:
            return current
        if current.state != GA4OAuthGrant.State.REVOCATION_PENDING:
            current.state = GA4OAuthGrant.State.REVOCATION_PENDING
            current.revision += 1
            current.save(update_fields=["state", "revision", "updated_at"])
            AuditEvent.objects.create(organization=organization, project=project, actor=user,
                event_type=AuditEventType.GA4_REVOCATION_REQUESTED,
                details={"grant_id": current.pk, "property_id": current.property_id})
        IntegrationConnection.objects.filter(project=project, provider="google_analytics_4",
            credential_reference=current.credential_reference).exclude(state=IntegrationConnection.State.DISCONNECTED).update(
            state=IntegrationConnection.State.DISCONNECTED, updated_at=timezone.now())
        encrypted = current.encrypted_refresh_token
        revision = current.revision
    token = decrypt_ga4_refresh_token(encrypted)
    if revoke(token=token) is not True:
        raise GoogleTokenError("revocation_unconfirmed", retryable=True)
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=grant.organization_id)
        project = Project.objects.select_for_update().get(pk=grant.project_id, organization=organization)
        require_project_action(project=project, user=user, action=Action.MANAGE_PROJECT)
        current = GA4OAuthGrant.objects.select_for_update().get(pk=grant.pk, project=project, organization=organization)
        if current.state != GA4OAuthGrant.State.REVOCATION_PENDING or current.revision != revision:
            raise ValidationError("GA4 grant changed while revocation was confirmed.")
        current.encrypted_refresh_token = ""
        current.property_id = ""
        current.selected_origins = []
        current.state = GA4OAuthGrant.State.REVOKED
        current.revoked_at = timezone.now()
        current.revision += 1
        current.save(update_fields=["encrypted_refresh_token", "property_id", "selected_origins",
                                    "state", "revoked_at", "revision", "updated_at"])
        AuditEvent.objects.create(organization=organization, project=project, actor=user,
            event_type=AuditEventType.GA4_REVOKED, details={"grant_id": current.pk})
        return current
