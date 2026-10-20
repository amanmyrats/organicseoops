"""One-time GBP consent and revocable credentials. No provider content is persisted."""
from copy import deepcopy
import hashlib
import secrets

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from providers.google_app import google_business_oauth_client, lock_google_application
from providers.models import GoogleOAuthApplication
from tenancy.models import AuditEvent, AuditEventType, Organization, Project
from tenancy.services import Action, require_project_action
from .business_profile import POLICY_VERSION, SCOPE, require_business_authority
from .business_profile_tokens import (BusinessTokenRejected, _cipher, decrypt_business_refresh_token,
                                      encrypt_business_refresh_token, exchange_business_code,
                                      refresh_business_tokens, revoke_business_tokens)
from .google_tokens import GoogleTokenError, GoogleTokens
from .models import BusinessProfileOAuthGrant, BusinessProfileOAuthIntent
from .oauth import INTENT_LIFETIME, OAuthStateError, _session_digest, _STATE


def _current_authority(intent, actor):
    if intent.actor_id != getattr(actor, "pk", None):
        raise PermissionDenied
    app = GoogleOAuthApplication.objects.filter(key="business_profile", state="active",
                                                rotated_at=intent.app_revision, redirect_uri=intent.redirect_uri).first()
    if app is None:
        raise PermissionDenied
    _, authority = require_business_authority(project=intent.project, actor=actor, selection=intent.selection)
    if intent.authority != authority or intent.policy_version != POLICY_VERSION:
        raise PermissionDenied
    return google_business_oauth_client()


def begin_business_oauth_intent(*, project, actor, session_key, selection, policy_version):
    if policy_version != POLICY_VERSION:
        raise ValidationError("Accept the current Business Profile response-only policy.")
    digest, state = _session_digest(session_key), secrets.token_urlsafe(32)
    selection = deepcopy(selection)
    with transaction.atomic():
        lock_google_application()
        client = google_business_oauth_client()
        app = GoogleOAuthApplication.objects.get(key="business_profile", state="active")
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        _, authority = require_business_authority(project=project, actor=actor, selection=selection)
        # A replacement consent must never orphan an earlier revocable token.
        if BusinessProfileOAuthGrant.objects.filter(project=project, actor=actor).exclude(state="revoked").exists():
            raise ValidationError("Disconnect and finish revoking the existing Business Profile consent first.")
        now = timezone.now()
        if BusinessProfileOAuthIntent.objects.filter(project=project, actor=actor, status="consumed",
                used_at__gt=now - INTENT_LIFETIME, businessprofileoauthgrant__isnull=True).exists():
            raise ValidationError("The previous consent exchange may still be completing.")
        BusinessProfileOAuthIntent.objects.filter(project=project, actor=actor, status="pending").update(
            status="denied", used_at=now)
        intent = BusinessProfileOAuthIntent.objects.create(organization=organization, project=project, actor=actor,
            state_digest=hashlib.sha256(state.encode()).hexdigest(), session_digest=digest, app_revision=app.rotated_at,
            redirect_uri=client.redirect_uri, selection=selection, authority=authority,
            policy_version=policy_version, expires_at=now + INTENT_LIFETIME)
    return intent, state


def consume_business_oauth_intent(*, actor, session_key, state, callback_url, provider_denied=False):
    if type(state) is not str or not _STATE.fullmatch(state) or type(provider_denied) is not bool:
        raise OAuthStateError("Business Profile consent is invalid or expired.")
    digest, session_digest = hashlib.sha256(state.encode()).hexdigest(), _session_digest(session_key)
    identity = BusinessProfileOAuthIntent.objects.filter(state_digest=digest).values_list(
        "organization_id", "project_id").first()
    if identity is None:
        raise OAuthStateError("Business Profile consent is invalid or expired.")
    allowed, client = True, None
    with transaction.atomic():
        lock_google_application()
        Organization.objects.select_for_update().get(pk=identity[0])
        Project.objects.select_for_update().get(pk=identity[1], organization_id=identity[0])
        intent = BusinessProfileOAuthIntent.objects.select_for_update().get(state_digest=digest)
        if intent.actor_id != getattr(actor, "pk", None) or intent.session_digest != session_digest:
            raise PermissionDenied
        if intent.status != "pending" or callback_url != intent.redirect_uri:
            raise OAuthStateError("Business Profile consent is invalid or expired.")
        try:
            client = _current_authority(intent, actor)
            allowed = intent.expires_at > timezone.now()
        except (PermissionDenied, ValidationError, GoogleTokenError):
            allowed = False
        intent.status = "consumed" if allowed and not provider_denied else "denied"
        intent.used_at = timezone.now()
        intent.save(update_fields=["status", "used_at"])
    if not allowed:
        raise OAuthStateError("Business Profile consent is invalid or expired.")
    return intent, client


@sensitive_variables()
def complete_business_oauth(*, actor, session_key, state, callback_url, code, exchange=exchange_business_code):
    # Fail before issuing material if the infrastructure cannot encrypt it.
    _cipher()
    intent, client = consume_business_oauth_intent(actor=actor, session_key=session_key, state=state,
                                                  callback_url=callback_url)
    rejected = ""
    try:
        tokens = exchange(code=code, client_id=client.client_id, client_secret=client.client_secret,
                          redirect_uri=intent.redirect_uri)
        if not isinstance(tokens, GoogleTokens) or tokens.refresh_token is None:
            raise GoogleTokenError("reauthorization_required")
        material = tokens.refresh_token
    except BusinessTokenRejected as error:
        rejected, material = error.category, error.revocable_token
    encrypted = encrypt_business_refresh_token(material, organization_id=intent.organization_id,
                                               project_id=intent.project_id)
    with transaction.atomic():
        lock_google_application()
        Organization.objects.select_for_update().get(pk=intent.organization_id)
        Project.objects.select_for_update().get(pk=intent.project_id, organization_id=intent.organization_id)
        try:
            _current_authority(intent, actor)
            allowed = True
        except (PermissionDenied, ValidationError, GoogleTokenError):
            allowed = False
        grant = BusinessProfileOAuthGrant.objects.create(organization_id=intent.organization_id,
            project_id=intent.project_id, actor_id=intent.actor_id, intent=intent, scope=SCOPE,
            encrypted_refresh_token=encrypted, state="pending_selection" if allowed and not rejected else "revocation_pending")
        AuditEvent.objects.create(organization_id=grant.organization_id, project_id=grant.project_id, actor_id=grant.actor_id,
            event_type=AuditEventType.INTEGRATION_CREDENTIAL_UPDATED,
            details={"kind": "business_profile", "grant_id": grant.pk, "disabled": True})
    if rejected:
        raise GoogleTokenError(rejected) from None  # Captured material never escapes this private boundary.
    return grant


def require_business_grant(*, grant, actor, expected_revision):
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValidationError("Choose the current Business Profile grant revision.")
    current = BusinessProfileOAuthGrant.objects.select_related("intent", "project").get(
        pk=grant.pk, organization_id=grant.organization_id, project_id=grant.project_id)
    if current.revision != expected_revision or current.state not in {"pending_selection", "active"}:
        raise PermissionDenied
    if current.state == "pending_selection" and current.created_at <= timezone.now() - INTENT_LIFETIME:
        raise PermissionDenied
    return current, _current_authority(current.intent, actor)


@sensitive_variables()
def refresh_business_grant(*, grant, actor, expected_revision, before_request, refresh=refresh_business_tokens):
    current, client = require_business_grant(grant=grant, actor=actor, expected_revision=expected_revision)
    before_request("token_refresh")  # Caller reserves/accounts every request before transport.
    require_business_grant(grant=grant, actor=actor, expected_revision=expected_revision)
    try:
        tokens = refresh(encrypted_refresh=current.encrypted_refresh_token, organization_id=current.organization_id,
            project_id=current.project_id, client_id=client.client_id, client_secret=client.client_secret)
    except BusinessTokenRejected as error:
        _capture_business_cleanup_token(grant=current, token=error.revocable_token)
        raise GoogleTokenError(error.category) from None
    if not isinstance(tokens, GoogleTokens):
        raise GoogleTokenError("malformed_response")
    if tokens.refresh_token is not None and tokens.refresh_token != decrypt_business_refresh_token(
        current.encrypted_refresh_token, organization_id=current.organization_id, project_id=current.project_id):
        # Unexpected replacement material has no supported auto-rotation contract here.
        # Stop reading, preserve both tokens, and require confirmed cleanup/fresh consent.
        _capture_business_cleanup_token(grant=current, token=tokens.refresh_token)
        raise GoogleTokenError("refresh_material_changed")
    require_business_grant(grant=grant, actor=actor, expected_revision=expected_revision)
    return tokens


@sensitive_variables()
def _capture_business_cleanup_token(*, grant, token):
    encrypted = encrypt_business_refresh_token(token, organization_id=grant.organization_id, project_id=grant.project_id)
    with transaction.atomic():
        lock_google_application()
        Organization.objects.select_for_update().get(pk=grant.organization_id)
        current = BusinessProfileOAuthGrant.objects.select_for_update().get(pk=grant.pk,
            organization_id=grant.organization_id, project_id=grant.project_id)
        if not current.encrypted_refresh_token:
            primary, extra = encrypted, ""
        else:
            primary, extra = current.encrypted_refresh_token, current.encrypted_extra_token
            old = decrypt_business_refresh_token(primary, organization_id=current.organization_id, project_id=current.project_id)
            if token != old:
                if extra and decrypt_business_refresh_token(extra, organization_id=current.organization_id,
                        project_id=current.project_id) != token:
                    raise ValidationError("Business token cleanup is already pending.")
                extra = encrypted
        # A concurrent confirmed revoke may precede an in-flight response. Reopen ONLY
        # disabled cleanup with the newly issued material; never resurrect an active grant.
        BusinessProfileOAuthGrant.objects.filter(pk=current.pk).update(state="revocation_pending",
            encrypted_refresh_token=primary, encrypted_extra_token=extra, revoked_at=None,
            revision=current.revision + 1, updated_at=timezone.now())
        AuditEvent.objects.create(organization_id=current.organization_id, project_id=current.project_id,
            actor_id=current.actor_id, event_type=AuditEventType.INTEGRATION_CREDENTIAL_REVOKED,
            details={"kind": "business_profile", "grant_id": current.pk, "remote": "pending"})


def revoke_business_grant(*, grant, actor, revoke=revoke_business_tokens):
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=grant.organization_id)
        project = Project.objects.select_for_update().get(pk=grant.project_id, organization_id=grant.organization_id)
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        current = BusinessProfileOAuthGrant.objects.select_for_update().get(pk=grant.pk, project=project)
        if current.state == "revoked":
            return current
        if current.state != "revocation_pending":
            current.state = "revocation_pending"
            current.revision += 1
            current.save(update_fields=["state", "revision", "updated_at"])
            AuditEvent.objects.create(organization_id=current.organization_id, project=project, actor=actor,
                event_type=AuditEventType.INTEGRATION_CREDENTIAL_REVOKED,
                details={"kind": "business_profile", "grant_id": current.pk, "remote": "pending"})
    return finish_business_grant_revocation(grant=current, revoke=revoke)


def finish_business_grant_revocation(*, grant, revoke=revoke_business_tokens):
    """Internal retry on an already disabled grant; never enables or delivers source data."""
    current = BusinessProfileOAuthGrant.objects.get(pk=grant.pk, organization_id=grant.organization_id)
    if current.state == "revoked":
        return current
    if current.state != "revocation_pending":
        raise PermissionDenied
    tokens = tuple(dict.fromkeys(value for value in (current.encrypted_refresh_token, current.encrypted_extra_token) if value))
    error_category = ""
    for encrypted in tokens:  # At most two; failure of old material must not block usable replacement revocation.
        try:
            if revoke(encrypted_refresh=encrypted, organization_id=grant.organization_id, project_id=grant.project_id) is not True:
                raise GoogleTokenError("revocation_unconfirmed")
        except GoogleTokenError as error:
            error_category = error.category
            continue  # Retain this token, but still attempt the other independently revocable material.
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=grant.organization_id)
            current = BusinessProfileOAuthGrant.objects.select_for_update().get(pk=grant.pk, organization_id=grant.organization_id)
            if current.state == "revoked":
                continue
            if current.state != "revocation_pending":
                raise ValidationError("Business Profile revocation changed; review before retrying.")
            if current.encrypted_refresh_token == encrypted:
                current.encrypted_refresh_token, current.encrypted_extra_token = current.encrypted_extra_token, ""
            elif current.encrypted_extra_token == encrypted:
                current.encrypted_extra_token = ""
            else:
                raise ValidationError("Business Profile revocation material changed; review before retrying.")
            if not current.encrypted_refresh_token:
                current.state, current.revoked_at = "revoked", timezone.now()
            current.revision += 1
            current.save(update_fields=["encrypted_refresh_token", "encrypted_extra_token", "state", "revoked_at", "revision", "updated_at"])
            AuditEvent.objects.create(organization_id=current.organization_id, project_id=current.project_id,
                actor_id=current.actor_id, event_type=AuditEventType.INTEGRATION_CREDENTIAL_REVOKED,
                details={"kind": "business_profile", "grant_id": current.pk, "remote": "confirmed" if current.state == "revoked" else "pending"})
    current = BusinessProfileOAuthGrant.objects.get(pk=grant.pk, organization_id=grant.organization_id)
    if error_category and current.state != "revoked":
        raise GoogleTokenError(error_category) from None
    return current
