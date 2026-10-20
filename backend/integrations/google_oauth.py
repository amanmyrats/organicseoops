import re
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from tenancy.models import AuditEvent, AuditEventType, Organization, Project
from tenancy.services import Action, require_project_action

from providers.google_app import google_oauth_client

from .google_tokens import GoogleTokenError, GoogleTokens, encrypt_refresh_token, exchange_google_code, refresh_google_tokens, SCOPE
from .models import GoogleOAuthGrant, IntegrationConnection, IntegrationCapability, SourceDimension
from .oauth import _verified, consume_google_oauth_intent
from .search_console_api import exact_scope_search_console_sites
from .search_console_transport import SearchConsoleTransportError, google_sites_list, google_site_get


RECONNECT_METHOD = "google-reconnect-transition-v1"


def _retain_unselected_grant(intent, tokens):
    # Consent can issue a refresh token even when sites.list fails or no property is eligible.
    # Keep it disabled but revocable rather than silently abandoning remote authorization.
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=intent.organization_id)
        project = Project.objects.select_for_update().get(pk=intent.project_id, organization=organization)
        return GoogleOAuthGrant.objects.create(
            organization=organization, project=project, actor_id=intent.actor_id,
            encrypted_refresh_token=encrypt_refresh_token(tokens.refresh_token), scope=SCOPE,
            state=GoogleOAuthGrant.State.REVOCATION_PENDING, verified_at=timezone.now(),
        )


def complete_google_oauth(*, user, session_key, state, callback_url, code,
                          exchange=exchange_google_code, list_sites=google_sites_list):
    client = google_oauth_client()
    intent = consume_google_oauth_intent(user=user, session_key=session_key, state=state, callback_url=callback_url)
    if not isinstance(code, str) or not 1 <= len(code) <= 2048 or not re.fullmatch(r"[\x21-\x7e]+", code):
        raise ValidationError("Check the Google authorization response.")
    tokens = exchange(code=code, client_id=client.client_id, client_secret=client.client_secret)
    if not isinstance(tokens, GoogleTokens) or tokens.refresh_token is None:
        raise GoogleTokenError("reauthorization_required")
    project = Project.objects.get(pk=intent.project_id, organization_id=intent.organization_id)
    try:
        candidates = exact_scope_search_console_sites(project=project, user=user,
                                                        response=list_sites(access_token=tokens.access_token))
    except (SearchConsoleTransportError, GoogleTokenError, PermissionDenied, ValidationError):
        _retain_unselected_grant(intent, tokens)
        raise
    if not candidates["sites"]:
        return _retain_unselected_grant(intent, tokens), candidates
    try:
        with transaction.atomic():
            organization = Organization.objects.select_for_update().get(pk=intent.organization_id)
            project = Project.objects.select_for_update().select_related("organization").get(pk=intent.project_id, organization=organization)
            require_project_action(project=project, user=user, action=Action.MANAGE_PROJECT)
            if not _verified(user):
                raise PermissionDenied
            current = exact_scope_search_console_sites(project=project, user=user,
                                                        response={"siteEntry": [{"siteUrl": item["google_site_url"],
                                                                                  "permissionLevel": item["permission_level"]}
                                                                                 for item in candidates["sites"]]})
            if not current["sites"]:
                return _retain_unselected_grant(intent, tokens), current
            grant = GoogleOAuthGrant.objects.create(
                organization=organization, project=project, actor=user,
                encrypted_refresh_token=encrypt_refresh_token(tokens.refresh_token), scope=SCOPE,
                selectable_sites=current["sites"], verified_at=timezone.now(),
            )
    except (PermissionDenied, ValidationError):
        _retain_unselected_grant(intent, tokens)
        raise
    return grant, current


def select_google_site(*, grant, user, site_url, expected_revision=0,
                       refresh=refresh_google_tokens, verify_site=google_site_get):
    if type(expected_revision) is not int or expected_revision < 0 or not isinstance(site_url, str):
        raise ValidationError("Choose a current Google property and grant revision.")
    client = google_oauth_client()
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=grant.organization_id)
        project = Project.objects.select_for_update().select_related("organization").get(pk=grant.project_id, organization=organization)
        require_project_action(project=project, user=user, action=Action.MANAGE_PROJECT)
        current = GoogleOAuthGrant.objects.select_for_update().get(pk=grant.pk, organization=organization, project=project)
        if current.revision != expected_revision or current.state != GoogleOAuthGrant.State.PENDING_SELECTION:
            raise ValidationError("OAuth property selection changed or expired.")
        if not _verified(user) or current.verified_at < timezone.now() - timedelta(minutes=10):
            raise PermissionDenied
        available = next((item for item in current.selectable_sites if item["google_site_url"] == site_url), None)
        if available is None:
            raise PermissionDenied
        encrypted = current.encrypted_refresh_token
    tokens = refresh(encrypted_refresh=encrypted, client_id=client.client_id, client_secret=client.client_secret)
    if not isinstance(tokens, GoogleTokens):
        raise GoogleTokenError("malformed_response")
    permission_response = verify_site(site_url=site_url, access_token=tokens.access_token)
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=grant.organization_id)
        project = Project.objects.select_for_update().select_related("organization").get(pk=grant.project_id, organization=organization)
        require_project_action(project=project, user=user, action=Action.MANAGE_PROJECT)
        current = GoogleOAuthGrant.objects.select_for_update().get(pk=grant.pk, organization=organization, project=project)
        if (current.revision != expected_revision or current.state != GoogleOAuthGrant.State.PENDING_SELECTION
            or current.verified_at < timezone.now() - timedelta(minutes=10) or not _verified(user)):
            raise ValidationError("OAuth property selection changed or expired.")
        available = next((item for item in current.selectable_sites if item["google_site_url"] == site_url), None)
        if available is None or type(permission_response) is not dict:
            raise PermissionDenied
        listed = exact_scope_search_console_sites(project=project, user=user, response={"siteEntry": [permission_response]})
        if not listed["sites"] or listed["sites"][0]["external_property_id"] != available["external_property_id"]:
            raise PermissionDenied
        is_domain = available.get("scope") == "verified_domain_page_only"
        selected_origins = []
        if is_domain:
            approved = available.get("approved_origins")
            if type(approved) is not list or not approved or type(listed["sites"][0].get("approved_origins")) is not list:
                raise PermissionDenied
            selected_origins = sorted(set(approved) & set(listed["sites"][0]["approved_origins"]))
            if not selected_origins:
                raise PermissionDenied
        elif available.get("scope") != "exact_origin_url_prefix":
            raise PermissionDenied
        existing = IntegrationConnection.objects.select_for_update().filter(
            project=project, provider="google_search_console", external_property_id=available["external_property_id"],
        ).first()
        if existing is not None and existing.credential_reference not in {None, current.credential_reference}:
            raise ValidationError("This property belongs to another authorized connection.")
        if existing is None:
            existing = IntegrationConnection(
                project=project, provider="google_search_console",
                external_property_id=available["external_property_id"],
                capabilities=([IntegrationCapability.API_SYNC, IntegrationCapability.PAGE_METRICS,
                               IntegrationCapability.INDEXING_STATUS, IntegrationCapability.SITEMAPS] if is_domain else
                              [IntegrationCapability.API_SYNC, IntegrationCapability.CSV_IMPORT,
                               IntegrationCapability.QUERY_METRICS, IntegrationCapability.PAGE_METRICS,
                               IntegrationCapability.INDEXING_STATUS, IntegrationCapability.SITEMAPS]),
                available_dimensions=([SourceDimension.PAGE] if is_domain else
                                      [SourceDimension.DATE, SourceDimension.QUERY, SourceDimension.PAGE,
                                       SourceDimension.COUNTRY, SourceDimension.DEVICE,
                                       SourceDimension.SEARCH_TYPE, SourceDimension.SEARCH_APPEARANCE]),
                source_semantics="search_console_domain_pages" if is_domain else "search_console_performance",
                source_semantics_version="gsc-domain-page-v1" if is_domain else "gsc-performance-v1",
                timezone="America/Los_Angeles", backfill_limit_days=90,
            )
        else:
            if is_domain:
                if existing.source_semantics != "search_console_domain_pages":
                    raise PermissionDenied
                existing.capabilities = [IntegrationCapability.API_SYNC, IntegrationCapability.PAGE_METRICS,
                                         IntegrationCapability.INDEXING_STATUS, IntegrationCapability.SITEMAPS]
                existing.available_dimensions = [SourceDimension.PAGE]
            else:
                existing.capabilities = sorted(set(existing.capabilities) | {
                    IntegrationCapability.API_SYNC, IntegrationCapability.QUERY_METRICS, IntegrationCapability.PAGE_METRICS,
                    IntegrationCapability.INDEXING_STATUS, IntegrationCapability.SITEMAPS,
                })
                existing.available_dimensions = sorted(set(existing.available_dimensions) | {
                    SourceDimension.DATE, SourceDimension.QUERY, SourceDimension.PAGE, SourceDimension.COUNTRY,
                    SourceDimension.DEVICE, SourceDimension.SEARCH_TYPE, SourceDimension.SEARCH_APPEARANCE,
                })
            existing.state = IntegrationConnection.State.ACTIVE
        existing.credential_reference = current.credential_reference
        existing.save()
        current.selected_property_id = available["external_property_id"]
        current.selected_site_url = site_url
        current.selected_origins = selected_origins
        if tokens.refresh_token is not None:
            current.encrypted_refresh_token = encrypt_refresh_token(tokens.refresh_token)
        current.state = GoogleOAuthGrant.State.ACTIVE
        current.revision += 1
        current.save(update_fields=["selected_property_id", "selected_site_url", "selected_origins", "encrypted_refresh_token",
                                    "state", "revision", "updated_at"])
        AuditEvent.objects.create(organization=organization, project=project, actor=user,
                                  event_type=AuditEventType.GOOGLE_OAUTH_CONNECTED,
                                  details={"connection_id": existing.pk, "grant_id": current.pk})
    return existing


def revoke_google_grant(*, grant, user, expected_revision, remote_revoke=None):
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValidationError("Choose the current OAuth grant revision.")
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=grant.organization_id)
        project = Project.objects.select_for_update().select_related("organization").get(pk=grant.project_id, organization=organization)
        require_project_action(project=project, user=user, action=Action.MANAGE_PROJECT)
        current = GoogleOAuthGrant.objects.select_for_update().get(pk=grant.pk, organization=organization, project=project)
        if current.revision != expected_revision:
            raise ValidationError("OAuth grant changed in another session.")
        if current.state == GoogleOAuthGrant.State.REVOKED:
            return current
        if current.state != GoogleOAuthGrant.State.REVOCATION_PENDING:
            linked = IntegrationConnection.objects.select_for_update().filter(project=project,
                                                                              credential_reference=current.credential_reference)
            connection_ids = list(linked.values_list("pk", flat=True))
            linked.update(state=IntegrationConnection.State.DISCONNECTED, updated_at=timezone.now())
            current.state = GoogleOAuthGrant.State.REVOCATION_PENDING
            current.revision += 1
            current.save(update_fields=["state", "revision", "updated_at"])
            AuditEvent.objects.create(organization=organization, project=project, actor=user,
                                      event_type=AuditEventType.GOOGLE_OAUTH_REVOCATION_REQUESTED,
                                      details={"grant_id": current.pk, "connection_ids": connection_ids})
        pending_revision = current.revision
        encrypted = current.encrypted_refresh_token
    if remote_revoke is None:
        return current
    if remote_revoke(encrypted_refresh=encrypted) is not True:
        raise GoogleTokenError("revocation_unconfirmed")
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=grant.organization_id)
        project = Project.objects.select_for_update().get(pk=grant.project_id, organization=organization)
        current = GoogleOAuthGrant.objects.select_for_update().get(pk=grant.pk, organization=organization, project=project)
        if current.state == GoogleOAuthGrant.State.REVOKED:
            return current
        if current.state != GoogleOAuthGrant.State.REVOCATION_PENDING or current.revision != pending_revision:
            raise ValidationError("OAuth revocation changed in another session.")
        linked = IntegrationConnection.objects.select_for_update().filter(project=project,
                                                                          credential_reference=current.credential_reference)
        connection_ids = list(linked.values_list("pk", flat=True))
        linked.update(state=IntegrationConnection.State.DISCONNECTED, credential_reference=None, updated_at=timezone.now())
        current.state = GoogleOAuthGrant.State.REVOKED
        current.encrypted_refresh_token = ""
        current.selectable_sites = []
        current.selected_property_id = ""
        current.selected_site_url = ""
        current.selected_origins = []
        current.revoked_at = timezone.now()
        current.revision += 1
        current.save(update_fields=["state", "encrypted_refresh_token", "selectable_sites", "selected_property_id",
                                    "selected_site_url", "selected_origins", "revoked_at", "revision", "updated_at"])
        AuditEvent.objects.create(organization=organization, project=project, actor=user,
                                  event_type=AuditEventType.GOOGLE_OAUTH_REVOKED,
                                  details={"grant_id": current.pk, "connection_ids": connection_ids})
    return current


def require_google_reconnect(*, grant, reason="provider_refresh_rejected"):
    """Disable local API access on a definitive refresh denial, retaining ciphertext for remote revocation."""
    if reason not in {"provider_refresh_rejected", "authorization_unavailable", "property_unavailable"}:
        raise ValidationError("Choose a bounded Google access failure category.")
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=grant.organization_id)
        project = Project.objects.select_for_update().get(pk=grant.project_id, organization=organization)
        current = GoogleOAuthGrant.objects.select_for_update().get(pk=grant.pk, project=project, organization=organization)
        if (current.state != GoogleOAuthGrant.State.ACTIVE or current.revision != grant.revision
            or current.encrypted_refresh_token != grant.encrypted_refresh_token):
            return current
        linked = IntegrationConnection.objects.select_for_update().filter(
            project=project, credential_reference=current.credential_reference)
        connection_ids = list(linked.values_list("pk", flat=True))
        linked.update(state=IntegrationConnection.State.DISCONNECTED, updated_at=timezone.now())
        current.state = GoogleOAuthGrant.State.RECONNECT_REQUIRED
        current.revision += 1
        current.save(update_fields=["state", "revision", "updated_at"])
        AuditEvent.objects.create(organization=organization, project=project, actor=None,
                                  event_type=AuditEventType.GOOGLE_OAUTH_RECONNECT_REQUIRED,
                                  details={"grant_id": current.pk, "connection_ids": connection_ids,
                                           "reason": reason, "method_version": RECONNECT_METHOD,
                                           "grant_revision": current.revision})
        return current
