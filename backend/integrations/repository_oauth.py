"""Project/repository/revision-bound GitHub consent; this module never fetches code."""
import base64
from datetime import timedelta
from hashlib import sha256
import json
import re
import secrets
from urllib.parse import urlencode, urlsplit

from cryptography.fernet import InvalidToken
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from providers.services import _provider_cipher
from tenancy.models import AuditEvent, AuditEventType, Organization, Project
from tenancy.services import Action, require_project_action
from .oauth import _verified
from .repository_models import RepositoryApplication, RepositoryConsent, RepositoryGrant
from .repository_transport import RepositoryError, github_request

CALLBACK = "/api/integrations/repository/oauth/callback/"
LIFETIME = timedelta(minutes=10)
PERMISSIONS = {"contents": "read", "metadata": "read"}


def credential(value, *, limit=4096):
    if type(value) is not str or not re.fullmatch(r"[\x21-\x7e]{1," + str(limit) + "}", value):
        raise ValidationError("Repository credential unavailable.")
    return value


def source_selection(repository, repository_id, commit_sha):
    if (type(repository) is not str or len(repository) > 140
        or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_.-]{1,100}", repository)
        or repository.split("/")[1] in {".", ".."} or type(repository_id) is not int or not 0 < repository_id < 2**53
        or type(commit_sha) is not str or not re.fullmatch(r"[0-9a-f]{40}", commit_sha)):
        raise ValidationError("Select a GitHub owner/repository, numeric repository ID and full lowercase40-character commit SHA.")


def callback_uri(value):
    try:
        parts = urlsplit(value)
        secure = parts.scheme == "https" and parts.hostname and parts.port in {None, 443}
        local = settings.DEBUG and parts.scheme == "http" and parts.hostname in {"localhost", "127.0.0.1"} and parts.port in {None, 80, 4200, 18000}
        if (type(value) is not str or len(value) > 512 or not (secure or local) or parts.username or parts.password
            or parts.path != CALLBACK or parts.query or parts.fragment):
            raise ValueError
    except (TypeError, ValueError):
        raise ValidationError("Configure the exact repository OAuth callback URL.") from None
    return value


@sensitive_variables()
def seal(kind, value):
    return "v1:" + _provider_cipher().encrypt(json.dumps({"kind": kind, "value": value}, separators=(",", ":")).encode()).decode()


@sensitive_variables()
def unseal(kind, value):
    try:
        if type(value) is not str or not value.startswith("v1:") or len(value) > 16384:
            raise ValueError
        payload = json.loads(_provider_cipher().decrypt(value[3:].encode()))
        if type(payload) is not dict or set(payload) != {"kind", "value"} or payload["kind"] != kind:
            raise ValueError
        return payload["value"]
    except (InvalidToken, ValidationError, ValueError, TypeError, UnicodeError, RecursionError):
        raise RepositoryError("credential_unavailable") from None


def lock_application():
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [1740174333])


def application(pk=None):
    app = RepositoryApplication.objects.filter(pk=pk).first() if pk else RepositoryApplication.objects.filter(key="primary").first()
    if app is None:
        raise RepositoryError("application_unconfigured")
    return app


def _session(session_key):
    if type(session_key) is not str or not re.fullmatch(r"[A-Za-z0-9]{16,128}", session_key):
        raise PermissionDenied
    return sha256(("repository-session-v1:" + session_key).encode()).hexdigest()


def _authority(project_id, actor):
    project = Project.objects.select_related("organization").get(pk=project_id)
    require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
    if not _verified(actor):
        raise PermissionDenied
    return project


@sensitive_variables()
def begin_consent(*, project, actor, session_key, repository, repository_id, commit_sha, acknowledge_read_only_access):
    source_selection(repository, repository_id, commit_sha)
    if acknowledge_read_only_access is not True:
        raise ValidationError("Explicitly authorize read-only access to this repository and exact commit.")
    session_digest = _session(session_key)
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    digest = sha256(state.encode()).hexdigest()
    with transaction.atomic():
        lock_application()
        app = application()
        Organization.objects.select_for_update().get(pk=project.organization_id)
        Project.objects.select_for_update().get(pk=project.pk, organization_id=project.organization_id)
        _authority(project.pk, actor)
        now = timezone.now()
        if (RepositoryGrant.objects.filter(project=project, repository_id=repository_id).exclude(state="revoked").exists()
            or RepositoryConsent.objects.filter(project=project, repository_id=repository_id).filter(
                Q(status="pending", expires_at__gt=now) | Q(status="consumed", repositorygrant__isnull=True,
                    user_reported_revoked_at__isnull=True)).exists()):
            raise ValidationError("Resolve the existing repository connection or unknown consent first.")
        unseal("application", app.encrypted_secrets)
        RepositoryConsent.objects.create(organization=project.organization, project=project, actor=actor,
            application=app, app_revision=app.revision, repository=repository, repository_id=repository_id, commit_sha=commit_sha,
            state_digest=digest, session_digest=session_digest, encrypted_verifier=seal("pkce:" + digest, verifier), expires_at=now + LIFETIME)
    challenge = base64.urlsafe_b64encode(sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return "https://github.com/login/oauth/authorize?" + urlencode({"client_id": app.client_id, "redirect_uri": app.redirect_uri,
        "state": state, "scope": "offline_access", "repository_id": repository_id, "code_challenge": challenge,
        "code_challenge_method": "S256", "allow_signup": "false", "prompt": "select_account"})


def _exchange_checkpoint(consent, actor):
    _authority(consent.project_id, actor)
    if (application(consent.application_id).revision != consent.app_revision or timezone.now() >= consent.expires_at
        or not RepositoryConsent.objects.filter(pk=consent.pk, status="consumed", actor=actor,
            user_reported_revoked_at__isnull=True).exists()
        or RepositoryGrant.objects.filter(consent=consent).exclude(state="revocation_pending", revision=0).exists()):
        raise PermissionDenied


def _provider_identity(token, *, consent, checkpoint, request=github_request):
    user = request("/user", token=token, checkpoint=checkpoint)
    repo = request("/repos/" + consent.repository, token=token, checkpoint=checkpoint)
    installs = request("/user/installations?per_page=100", token=token, checkpoint=checkpoint)
    try:
        uid = user["id"]
        if (type(uid) is not int or not 0 < uid < 2**53 or repo.get("id") != consent.repository_id
            or type(repo.get("full_name")) is not str or repo["full_name"].casefold() != consent.repository.casefold()
            or repo.get("disabled") is not False or repo.get("permissions", {}).get("pull") is not True
            or type(installs.get("total_count")) is not int or not 0 <= installs["total_count"] <= 100
            or type(installs.get("installations")) is not list or len(installs["installations"]) != installs["total_count"]):
            raise ValueError
        app = application(consent.application_id)
        matches = []
        for item in installs["installations"]:
            permissions = item.get("permissions")
            if (item.get("app_id") == app.app_id and item.get("account", {}).get("id") == repo["owner"]["id"]
                and item.get("suspended_at") is None and type(permissions) is dict
                and all(permissions.get(key) == value for key, value in PERMISSIONS.items())
                and all(value == "none" for key, value in permissions.items() if key not in PERMISSIONS)
                and type(item.get("id")) is int and 0 < item["id"] < 2**53):
                matches.append(item["id"])
        if len(matches) != 1:
            raise ValueError
        commit = request(f"/repos/{consent.repository}/git/commits/{consent.commit_sha}", token=token, checkpoint=checkpoint)
        if commit.get("sha") != consent.commit_sha:
            raise ValueError
        return uid, matches[0]
    except (KeyError, TypeError, ValueError, AttributeError):
        raise RepositoryError("exact_readonly_repository_unavailable") from None


@sensitive_variables()
def complete_consent(*, actor, session_key, state, callback_url, code=None, denied=False):
    if type(state) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", state):
        raise ValidationError("Consent unavailable.")
    digest = sha256(state.encode()).hexdigest()
    identity = RepositoryConsent.objects.filter(state_digest=digest).values("organization_id", "project_id", "application_id").first()
    if identity is None:
        raise PermissionDenied
    if not denied:
        credential(code, limit=2048)
    with transaction.atomic():
        lock_application()
        app = application(identity["application_id"])
        Organization.objects.select_for_update().get(pk=identity["organization_id"])
        Project.objects.select_for_update().get(pk=identity["project_id"])
        consent = RepositoryConsent.objects.select_for_update().get(state_digest=digest)
        if (consent.actor_id != actor.pk or consent.status != "pending" or consent.session_digest != _session(session_key)
            or app.revision != consent.app_revision or callback_url != app.redirect_uri):
            raise PermissionDenied
        try:
            _authority(consent.project_id, actor)
            allowed = not denied and timezone.now() < consent.expires_at
        except PermissionDenied:
            allowed = False
        verifier = unseal("pkce:" + digest, consent.encrypted_verifier) if allowed else None
        app_secrets = unseal("application", app.encrypted_secrets) if allowed else None
        consent.status, consent.used_at, consent.encrypted_verifier = "consumed" if allowed else "denied", timezone.now(), ""
        consent.save(update_fields=["status", "used_at", "encrypted_verifier"])
    if verifier is None:
        raise RepositoryError("consent_denied_or_expired")
    checkpoint = lambda: _exchange_checkpoint(consent, actor)
    payload = github_request("/login/oauth/access_token", exchange={"client_id": app.client_id,
        "client_secret": credential(app_secrets["client_secret"]), "code": code, "redirect_uri": app.redirect_uri,
        "code_verifier": verifier, "repository_id": consent.repository_id}, checkpoint=checkpoint)
    raw_access = credential(payload.get("access_token"))
    raw_refresh = payload.get("refresh_token")
    raw_refresh = raw_refresh if type(raw_refresh) is str and len(raw_refresh) <= 4096 else None
    encrypted = seal(f"grant:{consent.pk}", {"access_token": raw_access, "refresh_token": raw_refresh})
    # Persist issued material before metadata, expiry or current-authority validation can fail.
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=consent.organization_id)
        Project.objects.select_for_update().get(pk=consent.project_id)
        if RepositoryConsent.objects.filter(pk=consent.pk, user_reported_revoked_at__isnull=False).exists():
            raise PermissionDenied
        grant = RepositoryGrant.objects.create(organization_id=consent.organization_id, project_id=consent.project_id,
            actor_id=consent.actor_id, application_id=consent.application_id, consent=consent,
            repository=consent.repository, repository_id=consent.repository_id, commit_sha=consent.commit_sha,
            encrypted_tokens=encrypted, expires_at=timezone.now())
    if (not re.fullmatch(r"ghu_[A-Za-z0-9_]{8,512}", raw_access) or type(payload.get("token_type")) is not str or payload["token_type"].lower() != "bearer"
        or type(payload.get("expires_in")) is not int or not 1 <= payload["expires_in"] <= 28800):
        raise RepositoryError("expiring_user_token_required")
    expiry = timezone.now() + timedelta(seconds=payload["expires_in"])
    uid, installation = _provider_identity(raw_access, consent=consent, checkpoint=checkpoint)
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=consent.organization_id)
        Project.objects.select_for_update().get(pk=consent.project_id)
        current = RepositoryGrant.objects.select_for_update().get(pk=grant.pk)
        checkpoint()
        if current.state != "revocation_pending" or current.revision != 0:
            raise PermissionDenied
        current.github_user_id, current.installation_id, current.expires_at = uid, installation, expiry
        current.state, current.revision = "active", 1
        current.save()
        AuditEvent.objects.create(organization_id=current.organization_id, project_id=current.project_id, actor=actor,
            event_type=AuditEventType.INTEGRATION_CREDENTIAL_UPDATED, details={"kind": "repository_readonly_connected",
                "grant_id": current.pk, "repository_id": current.repository_id, "commit_sha": current.commit_sha, "permission": "contents_read"})
        return current


def grant_current(grant):
    try:
        _authority(grant.project_id, grant.actor)
        return (grant.state == "active" and timezone.now() < grant.expires_at
            and application(grant.application_id).revision == grant.consent.app_revision)
    except (PermissionDenied, RepositoryError):
        return False


@sensitive_variables()
def verify_grant_source(grant, *, request=github_request, authority_checkpoint=None):
    """Owning future collector must call before code access; no token is sent to an analysis sandbox."""
    revision = grant.revision
    def checkpoint():
        if authority_checkpoint is not None:
            authority_checkpoint()
        current = RepositoryGrant.objects.select_related("actor", "consent").get(pk=grant.pk)
        if current.revision != revision or not grant_current(current):
            raise PermissionDenied
    checkpoint()
    token = unseal(f"grant:{grant.consent_id}", grant.encrypted_tokens)["access_token"]
    uid, installation = _provider_identity(token, consent=grant.consent, checkpoint=checkpoint, request=request)
    checkpoint()
    if (uid, installation) != (grant.github_user_id, grant.installation_id):
        raise RepositoryError("source_identity_changed")
    return {"provider": "github", "repository_id": grant.repository_id, "repository": grant.repository,
        "commit_sha": grant.commit_sha, "grant_id": grant.pk, "grant_revision": revision, "permissions": PERMISSIONS}


@sensitive_variables()
def revoke_grant(*, grant_id, actor=None, expected_revision=None, closed=False):
    grant = RepositoryGrant.objects.get(pk=grant_id)
    with transaction.atomic():
        org = Organization.objects.select_for_update().get(pk=grant.organization_id)
        project = Project.objects.select_for_update().get(pk=grant.project_id)
        current = RepositoryGrant.objects.select_for_update().get(pk=grant_id)
        if closed:
            from tenancy.closure_grants import _revocation_authorized
            if not _revocation_authorized(org):
                raise PermissionDenied
        else:
            require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
            if type(expected_revision) is not int or expected_revision != current.revision:
                raise ValidationError("Repository grant changed; refresh before disconnecting.")
        if current.state == "revoked":
            return current
        if current.revocation_evidence == "access_revoked_refresh_unconfirmed":
            return current
        if current.state != "revocation_pending" or current.revision == 0:
            current.state, current.revision = "revocation_pending", current.revision + 1
            current.save(update_fields=["state", "revision", "updated_at"])
        revision, encrypted = current.revision, current.encrypted_tokens
    app = application(current.application_id)
    def checkpoint():
        if not RepositoryGrant.objects.filter(pk=grant_id, state="revocation_pending", revision=revision, encrypted_tokens=encrypted).exists():
            raise PermissionDenied
    secret = unseal("application", app.encrypted_secrets)
    token = unseal(f"grant:{current.consent_id}", encrypted)["access_token"]
    response = github_request(f"/applications/{app.client_id}/token", revoke=credential(token),
        basic=(app.client_id, credential(secret["client_secret"])), checkpoint=checkpoint)
    if response != {"revoked": True}:
        raise RepositoryError("revocation_unconfirmed")
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=current.organization_id)
        current = RepositoryGrant.objects.select_for_update().get(pk=grant_id)
        if current.state == "revoked":
            return current
        checkpoint()
        # Token-specific deletion does not document refresh-token invalidation; retain pending cleanup.
        current.revocation_evidence = "access_revoked_refresh_unconfirmed"
        current.revision += 1
        current.save()
        AuditEvent.objects.create(organization_id=current.organization_id, project_id=current.project_id, actor=actor or current.actor,
            event_type=AuditEventType.INTEGRATION_CREDENTIAL_REVOKED, details={"kind": "repository_github_access_token_revoked",
                "grant_id": current.pk, "refresh_revocation": "unconfirmed"})
        return current


def report_grant_revoked(*, grant_id, actor, closed=False):
    grant = RepositoryGrant.objects.get(pk=grant_id)
    with transaction.atomic():
        org = Organization.objects.select_for_update().get(pk=grant.organization_id)
        current = RepositoryGrant.objects.select_for_update().get(pk=grant_id)
        if closed:
            from tenancy.closure_grants import _revocation_authorized
            if not _revocation_authorized(org) or not _verified(actor):
                raise PermissionDenied
        else:
            _authority(current.project_id, actor)
        if current.state == "revoked":
            return current
        if current.state != "revocation_pending" or current.created_at > timezone.now() - LIFETIME:
            raise ValidationError("Disable the connection and wait for in-flight authorization before reporting completed remote revocation.")
        current.state, current.encrypted_tokens, current.revoked_at = "revoked", "", timezone.now()
        current.revocation_evidence, current.revision = "human_reported_not_provider_verified", current.revision + 1
        current.save()
        AuditEvent.objects.create(organization_id=current.organization_id, project_id=current.project_id, actor=actor,
            event_type=AuditEventType.INTEGRATION_CREDENTIAL_REVOKED,
            details={"kind": "repository_grant_user_reported_revoked", "grant_id": current.pk,
                "evidence": "human_attestation_not_provider_verification"})
        return current


def report_unknown_revoked(*, consent_id, actor, closed=False):
    consent = RepositoryConsent.objects.get(pk=consent_id)
    with transaction.atomic():
        org = Organization.objects.select_for_update().get(pk=consent.organization_id)
        if closed:
            from tenancy.closure_grants import _revocation_authorized
            if not _revocation_authorized(org) or not _verified(actor):
                raise PermissionDenied
        else:
            _authority(consent.project_id, actor)
        current = RepositoryConsent.objects.select_for_update().get(pk=consent_id)
        if (current.status != "consumed" or RepositoryGrant.objects.filter(consent=current).exists()
            or current.used_at > timezone.now() - LIFETIME):
            raise ValidationError("Wait for the exchange and inspect current status before reporting completed revocation.")
        if current.user_reported_revoked_at is None:
            RepositoryConsent.objects.filter(pk=current.pk).update(user_reported_revoked_at=timezone.now())
            AuditEvent.objects.create(organization_id=current.organization_id, project_id=current.project_id, actor=actor,
                event_type=AuditEventType.INTEGRATION_CREDENTIAL_REVOKED, details={"kind": "repository_unknown_user_reported_revoked",
                    "consent_id": current.pk, "evidence": "human_attestation_not_provider_verification"})
