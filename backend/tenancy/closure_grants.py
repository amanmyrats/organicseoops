"""Provider-specific remote token revocation for already closed organizations."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from integrations.ga4_oauth import decrypt_ga4_refresh_token
from integrations.google_tokens import GoogleTokenError, post_google_revoke_form, revoke_google_tokens
from integrations.models import GA4OAuthGrant, GoogleOAuthGrant, IntegrationConnection

from .models import (AuditEvent, AuditEventType, Organization, OrganizationDeletionRun,
                     retained_content_window)


def revoke_closed_business_grant(*, grant_id, revoke=None, invoked_by=None):
    from integrations.business_profile_oauth import finish_business_grant_revocation
    from integrations.business_profile_tokens import revoke_business_tokens
    from integrations.models import BusinessProfileOAuthGrant
    grant = BusinessProfileOAuthGrant.objects.filter(pk=grant_id).first()
    if grant is None:
        raise PermissionDenied
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=grant.organization_id)
        grant = BusinessProfileOAuthGrant.objects.select_for_update().get(pk=grant_id, organization=organization)
        if not _revocation_authorized(organization):
            raise PermissionDenied
        if grant.state == "revoked":
            return grant
        if grant.state != "revocation_pending":
            raise ValidationError("Closure business grant is not ready for remote revocation.")
    try:
        return finish_business_grant_revocation(grant=grant, revoke=revoke or revoke_business_tokens)
    except GoogleTokenError:
        return grant  # Keep pending material and deletion blocker until confirmed.


def _revocation_authorized(organization):
    if organization.closed_at is not None and organization.is_suspended:
        return True
    if organization.closed_at is not None or organization.is_suspended:
        return False
    return (OrganizationDeletionRun.objects.filter(organization=organization,
        state__in=[OrganizationDeletionRun.State.PENDING, OrganizationDeletionRun.State.STORAGE_CLEARED],
        eligible_at__lte=timezone.now()).exists()
        and not Organization.objects.filter(pk=organization.pk).filter(retained_content_window()).exists())


def revoke_closed_search_console_grant(*, grant_id, revoke=revoke_google_tokens, invoked_by=None):
    grant = GoogleOAuthGrant.objects.filter(pk=grant_id).first()
    if grant is None:
        raise PermissionDenied
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=grant.organization_id)
        grant = GoogleOAuthGrant.objects.select_for_update().get(pk=grant_id, organization=organization)
        if not _revocation_authorized(organization):
            raise PermissionDenied
        if grant.state == grant.State.REVOKED:
            return grant
        if grant.state != grant.State.REVOCATION_PENDING or not grant.encrypted_refresh_token:
            raise ValidationError("Closure grant is not ready for remote revocation.")
        encrypted, revision = grant.encrypted_refresh_token, grant.revision
    try:
        if revoke(encrypted_refresh=encrypted) is not True:
            return grant
    except GoogleTokenError:
        return grant  # Retain encrypted credential and a pending review/retry state.
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=grant.organization_id)
        grant = GoogleOAuthGrant.objects.select_for_update().get(pk=grant_id, organization=organization)
        if grant.state == grant.State.REVOKED:
            return grant
        if (not _revocation_authorized(organization) or grant.state != grant.State.REVOCATION_PENDING
            or grant.revision != revision or grant.encrypted_refresh_token != encrypted):
            raise ValidationError("Closure grant changed during provider revocation.")
        IntegrationConnection.objects.filter(project_id=grant.project_id,
            credential_reference=grant.credential_reference).update(
            state=IntegrationConnection.State.DISCONNECTED, credential_reference=None, updated_at=timezone.now())
        grant.state = grant.State.REVOKED
        grant.encrypted_refresh_token = ""
        grant.selectable_sites = []
        grant.selected_property_id = ""
        grant.selected_site_url = ""
        grant.selected_origins = []
        grant.revoked_at = timezone.now()
        grant.revision += 1
        grant.save(update_fields=["state", "encrypted_refresh_token", "selectable_sites", "selected_property_id",
                                  "selected_site_url", "selected_origins", "revoked_at", "revision", "updated_at"])
        AuditEvent.objects.create(organization=organization, project_id=grant.project_id,
                                  actor=invoked_by or grant.actor,
                                  event_type=AuditEventType.GOOGLE_OAUTH_REVOKED,
                                  details={"grant_id": grant.pk, "closure": True})
        return grant


def revoke_closed_analytics_grant(*, grant_id, revoke=post_google_revoke_form, invoked_by=None):
    grant = GA4OAuthGrant.objects.filter(pk=grant_id).first()
    if grant is None:
        raise PermissionDenied
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=grant.organization_id)
        grant = GA4OAuthGrant.objects.select_for_update().get(pk=grant_id, organization=organization)
        if not _revocation_authorized(organization):
            raise PermissionDenied
        if grant.state == grant.State.REVOKED:
            return grant
        if grant.state != grant.State.REVOCATION_PENDING or not grant.encrypted_refresh_token:
            raise ValidationError("Closure grant is not ready for remote revocation.")
        encrypted, revision = grant.encrypted_refresh_token, grant.revision
    try:
        if revoke(token=decrypt_ga4_refresh_token(encrypted)) is not True:
            return grant
    except (GoogleTokenError, ValidationError):
        return grant  # Never scrub unconfirmed or undecipherable provider material.
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=grant.organization_id)
        grant = GA4OAuthGrant.objects.select_for_update().get(pk=grant_id, organization=organization)
        if grant.state == grant.State.REVOKED:
            return grant
        if (not _revocation_authorized(organization) or grant.state != grant.State.REVOCATION_PENDING
            or grant.revision != revision or grant.encrypted_refresh_token != encrypted):
            raise ValidationError("Closure grant changed during provider revocation.")
        grant.state = grant.State.REVOKED
        grant.encrypted_refresh_token = ""
        grant.property_id = ""
        grant.selected_origins = []
        grant.revoked_at = timezone.now()
        grant.revision += 1
        grant.save(update_fields=["state", "encrypted_refresh_token", "property_id", "selected_origins",
                                  "revoked_at", "revision", "updated_at"])
        AuditEvent.objects.create(organization=organization, project_id=grant.project_id,
                                  actor=invoked_by or grant.actor,
                                  event_type=AuditEventType.GA4_REVOKED,
                                  details={"grant_id": grant.pk, "closure": True})
        return grant


def revoke_closed_yandex_grant(*, grant_id, invoked_by=None):
    from integrations.yandex_oauth import revoke_grant
    from integrations.yandex_models import YandexOAuthGrant
    from integrations.yandex_transport import YandexError
    try:
        return revoke_grant(grant_id=grant_id, actor=invoked_by, closed=True)
    except YandexError:
        return YandexOAuthGrant.objects.get(pk=grant_id)  # Retain pending tokens until provider confirmation.


def revoke_closed_repository_grant(*, grant_id, invoked_by=None):
    from integrations.repository_oauth import revoke_grant
    from integrations.repository_models import RepositoryGrant
    from integrations.repository_transport import RepositoryError
    try:
        return revoke_grant(grant_id=grant_id, actor=invoked_by, closed=True)
    except RepositoryError:
        return RepositoryGrant.objects.get(pk=grant_id)
