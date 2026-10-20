"""Atomic local shutdown; provider revocation and data deletion remain resumable."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from integrations.models import RepositoryConsent, RepositoryGrant, YandexOAuthGrant, YandexOAuthIntent, BusinessProfileOAuthGrant, BusinessProfileOAuthIntent, GA4OAuthGrant, GoogleOAuthGrant, IntegrationConnection
from jobs.models import (JobCancellation, JobRun, JobSchedule, JobStatus,
                         ProjectReportShare, UsageReservation)
from providers.models import AIProviderAccount, AIProviderSecret, OrganizationPerformanceKey

from .models import (AuditEvent, AuditEventType, InvitationState, MembershipRole,
                     Organization, OrganizationBillingCancellation, OrganizationDeletionRun, OrganizationInvitation,
                     OrganizationMembership, PaddleCheckoutAttempt, PaddleStatus, PaddleSubscription)
from .services import Action, _recent_authentication, require_organization_action


def close_organization_locally(*, organization, actor, request, request_id=""):
    """Disable all owned access/work before any external cancellation attempt."""
    _recent_authentication(request, actor)
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization.pk)
        if organization.closed_at is not None:
            if not get_user_model().objects.filter(pk=actor.pk, is_active=True).exists() or not (
                OrganizationMembership.objects.filter(organization=organization, user=actor,
                                                      role=MembershipRole.OWNER).exists()
            ):
                raise PermissionDenied
            return organization
        require_organization_action(organization=organization, user=actor, action=Action.ORGANIZATION_SETTINGS)
        if OrganizationDeletionRun.objects.filter(organization=organization).exists():
            raise ValidationError("Retention deletion is already underway; do not change its source.")
        subscription = PaddleSubscription.objects.select_for_update().filter(organization=organization).first()
        if subscription:
            if subscription.verified_at is None or (
                subscription.status == PaddleStatus.CANCELED and subscription.canceled_at is None
            ):
                raise ValidationError("Reconcile the linked provider subscription before closing.")
            if subscription.status != PaddleStatus.CANCELED:
                attempt = OrganizationBillingCancellation.objects.select_for_update().filter(
                    organization=organization, subscription=subscription, state=OrganizationBillingCancellation.State.RESERVED,
                    environment=subscription.environment, customer_id=subscription.customer_id,
                    provider_subscription_id=subscription.subscription_id).first()
                if attempt is None:
                    raise ValidationError("Prepare a durable current-subscription cancellation first.")
        attempts = PaddleCheckoutAttempt.objects.filter(organization=organization)
        if attempts.filter(Q(state__in=[PaddleCheckoutAttempt.State.SENDING, PaddleCheckoutAttempt.State.UNKNOWN])
            | Q(state=PaddleCheckoutAttempt.State.READY, paid_verified_at__isnull=True)).exists():
            raise ValidationError("Reconcile in-flight checkout before closing.")
        paid_checkouts = attempts.filter(state=PaddleCheckoutAttempt.State.READY, paid_verified_at__isnull=False)
        if paid_checkouts.exists() and (subscription is None or paid_checkouts.exclude(
            environment=subscription.environment, paid_customer_id=subscription.customer_id,
            paid_subscription_id=subscription.subscription_id).exists()):
            raise ValidationError("Reconcile paid checkout with the current subscription before closing.")
        if RepositoryConsent.objects.filter(organization=organization, status="consumed", repositorygrant__isnull=True,
                user_reported_revoked_at__isnull=True).exists():
            raise ValidationError("Resolve the unknown repository authorization in the project before closing.")
        if YandexOAuthGrant.objects.filter(organization=organization, refresh_started_at__isnull=False).exists():
            raise ValidationError("Resolve unknown Yandex token refreshes in the project before closing.")
        if YandexOAuthIntent.objects.filter(organization=organization, status="consumed",
                yandexoauthgrant__isnull=True, user_reported_revoked_at__isnull=True).exists():
            raise ValidationError("Resolve unknown Yandex token exchanges in the project before closing.")
        now = timezone.now()
        PaddleCheckoutAttempt.objects.filter(organization=organization,
            state=PaddleCheckoutAttempt.State.RESERVED).update(state=PaddleCheckoutAttempt.State.REJECTED)
        queued = JobRun.objects.filter(organization=organization, status=JobStatus.QUEUED)
        queued_ids = list(queued.values_list("pk", flat=True))
        queued.update(status=JobStatus.CANCELLED, error_category="organization_closed", updated_at=now)
        UsageReservation.objects.filter(organization=organization, job_id__in=queued_ids,
            state=UsageReservation.State.RESERVED).update(state=UsageReservation.State.RELEASED, settled_at=now)
        running = JobRun.objects.filter(organization=organization,
            status__in=[JobStatus.RUNNING, JobStatus.WAITING_PROVIDER]).exclude(cancellation__isnull=False)
        JobCancellation.objects.bulk_create([JobCancellation(job_id=pk, requested_by=actor)
            for pk in running.values_list("pk", flat=True)])
        schedules = JobSchedule.objects.filter(organization=organization, enabled=True).update(
            enabled=False, next_run_at=None, last_error_category="organization_closed")
        shares = ProjectReportShare.objects.filter(project__organization=organization, revoked_at__isnull=True).update(
            revoked_at=now)
        connections = IntegrationConnection.objects.filter(project__organization=organization).exclude(
            state=IntegrationConnection.State.DISCONNECTED).update(
                state=IntegrationConnection.State.DISCONNECTED, updated_at=now)
        BusinessProfileOAuthIntent.objects.filter(organization=organization, status="pending").update(status="denied", used_at=now)
        YandexOAuthIntent.objects.filter(organization=organization, status="pending").update(status="denied", used_at=now, encrypted_verifier="")
        RepositoryConsent.objects.filter(organization=organization, status="pending").update(status="denied", used_at=now, encrypted_verifier="")
        for model in (GoogleOAuthGrant, GA4OAuthGrant, BusinessProfileOAuthGrant, YandexOAuthGrant, RepositoryGrant):
            model.objects.filter(organization=organization).exclude(state__in=[
                model.State.REVOCATION_PENDING, model.State.REVOKED]).update(
                    state=model.State.REVOCATION_PENDING, revision=F("revision") + 1, updated_at=now)
        provider_accounts = AIProviderAccount.objects.filter(organization=organization).exclude(
            state=AIProviderAccount.State.REVOKED)
        AIProviderSecret.objects.filter(account__in=provider_accounts).delete()
        provider_accounts.update(state=AIProviderAccount.State.REVOKED, revoked_at=now, updated_at=now)
        OrganizationPerformanceKey.objects.filter(organization=organization).update(
            state=OrganizationPerformanceKey.State.REVOKED, encrypted_secret="", rotated_at=now)
        invitations = OrganizationInvitation.objects.filter(organization=organization,
            state=InvitationState.PENDING).update(state=InvitationState.REVOKED, revoked_at=now)
        organization.is_suspended = True
        organization.closed_at = now
        organization.save(update_fields=["is_suspended", "closed_at", "updated_at"])
        AuditEvent.objects.create(organization=organization, actor=actor,
            event_type=AuditEventType.ORGANIZATION_CLOSED, request_id=request_id,
            details={"queued_jobs_cancelled": len(queued_ids), "schedules_disabled": schedules,
                     "live_shares_revoked": shares, "connections_disabled": connections,
                     "invitations_revoked": invitations, "active_data_delete_by": (now + timedelta(days=30)).isoformat(),
                     "provider_cancellation": "pending" if subscription and subscription.status != PaddleStatus.CANCELED
                                              else "not_required"})
        return organization
