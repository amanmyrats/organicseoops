import hashlib
import re
import secrets
from datetime import timedelta
from urllib.parse import urlsplit

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from tenancy.models import Organization, Project
from tenancy.services import Action, require_project_action

from .models import GoogleOAuthIntent


CALLBACK_PATH = "/api/integrations/google-search-console/oauth/callback/"
INTENT_LIFETIME = timedelta(minutes=10)
_STATE = re.compile(r"[A-Za-z0-9_-]{32,128}\Z")


class OAuthStateError(Exception):
    pass


def configured_redirect_uri(value=None):
    if value is None:
        from providers.models import GoogleOAuthApplication
        if GoogleOAuthApplication.objects.filter(key="primary").exists():
            from providers.google_app import google_oauth_client
            value = google_oauth_client().redirect_uri
        else:
            value = settings.GOOGLE_OAUTH_REDIRECT_URI
    if not isinstance(value, str) or len(value) > 512:
        raise ValidationError("Google OAuth callback is not configured.")
    try:
        parsed = urlsplit(value)
        if parsed.scheme == "https":
            valid_host = bool(parsed.hostname) and parsed.port in {None, 443}
        else:
            valid_host = (settings.DEBUG and parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
                          and parsed.port in {None, 80, 4200, 18000})
    except ValueError:
        valid_host = False
    if not valid_host or parsed.username or parsed.password or parsed.path != CALLBACK_PATH or parsed.query or parsed.fragment:
        raise ValidationError("Google OAuth callback is not configured.")
    return value


def _session_digest(session_key):
    if not isinstance(session_key, str) or not 16 <= len(session_key) <= 128 or not session_key.isascii():
        raise PermissionDenied
    return hashlib.sha256(f"google-oauth-session-v1:{session_key}".encode()).hexdigest()


def _verified(user):
    current_email = get_user_model().objects.filter(pk=getattr(user, "pk", None), is_active=True).values_list("email", flat=True).first()
    return bool(current_email and EmailAddress.objects.filter(user_id=user.pk, email=current_email, verified=True).exists())


def begin_google_oauth_intent(*, project, user, session_key):
    session_digest = _session_digest(session_key)
    state = secrets.token_urlsafe(32)
    now = timezone.now()
    with transaction.atomic():
        from providers.google_app import lock_google_application
        lock_google_application()
        redirect_uri = configured_redirect_uri()
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().select_related("organization").get(pk=project.pk, organization=organization)
        require_project_action(project=project, user=user, action=Action.MANAGE_PROJECT)
        if not _verified(user):
            raise PermissionDenied
        # A fresh consent attempt supersedes this actor's older attempt for the same project.
        GoogleOAuthIntent.objects.filter(project=project, actor=user, status=GoogleOAuthIntent.Status.PENDING).update(
            status=GoogleOAuthIntent.Status.DENIED, used_at=now,
        )
        intent = GoogleOAuthIntent.objects.create(
            organization=organization, project=project, actor=user,
            state_digest=hashlib.sha256(state.encode()).hexdigest(), session_digest=session_digest,
            redirect_uri=redirect_uri, expires_at=now + INTENT_LIFETIME,
        )
    return intent, state


def consume_google_oauth_intent(*, user, session_key, state, callback_url, provider_denied=False):
    if not isinstance(state, str) or not _STATE.fullmatch(state):
        raise OAuthStateError("OAuth state is invalid or expired.")
    if callback_url != configured_redirect_uri() or type(provider_denied) is not bool:
        raise OAuthStateError("OAuth state is invalid or expired.")
    session_digest = _session_digest(session_key)
    digest = hashlib.sha256(state.encode()).hexdigest()
    identity = GoogleOAuthIntent.objects.filter(state_digest=digest).values_list("organization_id", "project_id").first()
    if identity is None:
        raise OAuthStateError("OAuth state is invalid or expired.")
    outcome = ""
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=identity[0])
        project = Project.objects.select_for_update().select_related("organization").get(pk=identity[1], organization=organization)
        intent = GoogleOAuthIntent.objects.select_for_update().get(state_digest=digest, organization=organization, project=project)
        if intent.actor_id != getattr(user, "pk", None) or intent.session_digest != session_digest:
            raise PermissionDenied
        if intent.status != GoogleOAuthIntent.Status.PENDING:
            raise OAuthStateError("OAuth state is invalid or expired.")
        now = timezone.now()
        if intent.expires_at <= now or intent.redirect_uri != configured_redirect_uri():
            outcome = "expired"
        else:
            try:
                require_project_action(project=project, user=user, action=Action.MANAGE_PROJECT)
                if not _verified(user):
                    raise PermissionDenied
            except PermissionDenied:
                outcome = "access_revoked"
        intent.status = GoogleOAuthIntent.Status.DENIED if outcome or provider_denied else GoogleOAuthIntent.Status.CONSUMED
        intent.used_at = now
        intent.save(update_fields=["status", "used_at"])
    if outcome:
        raise OAuthStateError("OAuth state is invalid or expired.")
    return intent
