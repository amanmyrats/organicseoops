"""D098 retention eligibility and retryable private-storage deletion progress."""
from datetime import timedelta
from contextlib import ExitStack

from django.apps import apps
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from config.artifacts import ArtifactStorageError, ArtifactValidationError

from .artifacts import (delete_closed_organization_export_batch, delete_closed_project_artifact_batch,
                        organization_export_versions_remain, project_artifact_versions_remain)
from .customer_artifact_barrier import (WRITER_ADMISSION_TIMEOUT_MS, project_artifact_barrier,
                                       require_settled_project_mutations)
from .billing_state import paid_access_state
from .customer_inventory import CUSTOMER, SECRETS, require_complete_ownership_map
from .models import (Organization, OrganizationDeletionRun, OrganizationTrial, PaddleCheckoutAttempt,
                      PaddleStatus, PaddleSubscription, Project, ProjectArtifactMutationAttempt, retained_content_window)
from .paddle_cancellation import require_confirmed_closed_billing


def _eligibility(organization, now):
    if organization.closed_at is not None:
        if not organization.is_suspended:
            raise ValidationError("Organization closure state is inconsistent.")
        if organization.closed_at > now:
            raise PermissionDenied
        return OrganizationDeletionRun.Source.OWNER_CLOSED, organization.closed_at
    if organization.is_suspended:
        raise PermissionDenied  # A staff hold is not an owner deletion request or trial lapse.
    subscription = PaddleSubscription.objects.filter(organization=organization).first()
    if subscription and (subscription.verified_at is None or subscription.verified_at > now):
        raise ValidationError("Reconcile the linked provider subscription before deletion.")
    if subscription and subscription.verified_at is not None:
        if subscription.environment != settings.PADDLE_ENVIRONMENT or paid_access_state(subscription, now=now) == "billing_review_hold":
            raise ValidationError("Reconcile the current paid provider state before deletion.")
        if subscription.refunded_at is not None:
            source, effective = OrganizationDeletionRun.Source.PAID_REFUNDED, subscription.refunded_at
        elif subscription.status == PaddleStatus.CANCELED and subscription.canceled_at is not None:
            source, effective = OrganizationDeletionRun.Source.PAID_CANCELED, subscription.canceled_at
        else:
            raise PermissionDenied
    else:
        if PaddleCheckoutAttempt.objects.filter(organization=organization, state__in=[
            PaddleCheckoutAttempt.State.SENDING, PaddleCheckoutAttempt.State.READY,
            PaddleCheckoutAttempt.State.UNKNOWN]).exists():
            raise ValidationError("Reconcile provider checkout before deleting retained data.")
        trial = OrganizationTrial.objects.filter(organization=organization).first()
        if trial is None or trial.ends_at is None:
            raise PermissionDenied
        source, effective = OrganizationDeletionRun.Source.TRIAL_ELAPSED, trial.ends_at
    eligible = effective + timedelta(days=90)
    if now < eligible or Organization.objects.filter(pk=organization.pk).filter(
        retained_content_window(now=now)
    ).exists():
        raise PermissionDenied
    return source, eligible


def prepare_customer_data_deletion(*, organization, now=None):
    now = now or timezone.now()
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization.pk)
        source, eligible_at = _eligibility(organization, now)
        existing = OrganizationDeletionRun.objects.filter(organization=organization).first()
        if existing:
            if existing.source != source or existing.eligible_at != eligible_at:
                raise ValidationError("Existing deletion scope changed; manual reconciliation required.")
            return existing
        ids = list(Project.objects.filter(organization=organization).order_by("pk").values_list("pk", flat=True))
        run = OrganizationDeletionRun.objects.create(organization=organization, source=source,
            eligible_at=eligible_at, due_at=eligible_at + timedelta(days=30), project_ids=ids)
        if source != OrganizationDeletionRun.Source.OWNER_CLOSED:
            from integrations.models import RepositoryConsent, RepositoryGrant, YandexOAuthGrant, YandexOAuthIntent, BusinessProfileOAuthGrant, BusinessProfileOAuthIntent, GA4OAuthGrant, GoogleOAuthGrant, IntegrationConnection
            from jobs.models import JobSchedule
            from .models import AuditEvent, AuditEventType
            IntegrationConnection.objects.filter(project__organization=organization).exclude(
                state=IntegrationConnection.State.DISCONNECTED).update(
                state=IntegrationConnection.State.DISCONNECTED, updated_at=now)
            BusinessProfileOAuthIntent.objects.filter(organization=organization, status="pending").update(status="denied", used_at=now)
            YandexOAuthIntent.objects.filter(organization=organization, status="pending").update(status="denied", used_at=now, encrypted_verifier="")
            RepositoryConsent.objects.filter(organization=organization, status="pending").update(status="denied", used_at=now, encrypted_verifier="")
            for model in (GoogleOAuthGrant, GA4OAuthGrant, BusinessProfileOAuthGrant, YandexOAuthGrant, RepositoryGrant):
                model.objects.filter(organization=organization).exclude(state__in=[
                    model.State.REVOKED, model.State.REVOCATION_PENDING]).update(
                    state=model.State.REVOCATION_PENDING, revision=F("revision") + 1, updated_at=now)
            JobSchedule.objects.filter(organization=organization, enabled=True).update(
                enabled=False, next_run_at=None, last_error_category="retention_elapsed")
            AuditEvent.objects.create(organization=organization, event_type=AuditEventType.ORGANIZATION_RETENTION_ELAPSED,
                details={"deletion_run_id": run.pk, "source": source, "active_delete_by": run.due_at.isoformat()})
        return run


def sweep_customer_artifact_versions(*, run, limit=100, storage=None, now=None):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValidationError("Choose a bounded deletion batch.")
    now = now or timezone.now()
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=run.organization_id)
        current = OrganizationDeletionRun.objects.select_for_update().get(pk=run.pk, organization=organization)
        _eligibility(organization, now)
        if current.source == current.Source.OWNER_CLOSED:
            require_confirmed_closed_billing(organization)
        if current.state == current.State.STORAGE_CLEARED:
            if current.claimed_at is not None:
                raise ValidationError("Deletion storage claim requires review.")
            if ProjectArtifactMutationAttempt.objects.filter(organization=organization).exists():
                raise ArtifactStorageError("Project artifact mutation is unresolved; deletion cannot complete.")
            for project_id in current.project_ids:
                project = Project.objects.filter(pk=project_id, organization=organization).first()
                if project is None:
                    raise ArtifactValidationError("Deletion project identity changed.")
                if project_artifact_versions_remain(project=project, storage=storage):
                    current.state = current.State.PENDING
                    current.last_error_category = "artifact_reappeared"
                    current.save(update_fields=["state", "last_error_category"])
                    break
            else:
                if organization_export_versions_remain(organization=organization, storage=storage):
                    current.state = current.State.PENDING
                    current.last_error_category = "artifact_reappeared"
                    current.save(update_fields=["state", "last_error_category"])
                else:
                    return current
        if current.state != current.State.PENDING:
            return current
        if current.claimed_at and current.claimed_at > now - timedelta(minutes=15):
            return current
        current.claimed_at = now
        current.attempts += 1
        current.save(update_fields=["claimed_at", "attempts"])
    with ExitStack() as admission:
        removed, complete, error = 0, True, ""
        try:
            admission.enter_context(project_artifact_barrier(organization.pk, shared=True))
            for project_id in current.project_ids:
                project = Project.objects.filter(pk=project_id, organization_id=organization.pk).first()
                if project is None:
                    raise ArtifactValidationError("Deletion project identity changed.")
                count, finished = delete_closed_project_artifact_batch(
                    organization=organization, project=project, limit=limit - removed, storage=storage)
                removed += count
                if not finished or removed >= limit:
                    complete = False
                    break
            if complete and removed < limit:
                count, finished = delete_closed_organization_export_batch(
                    organization=organization, limit=limit - removed, storage=storage)
                removed += count
                if not finished or removed >= limit:
                    complete = False
        except (ArtifactStorageError, ArtifactValidationError):
            error = "artifact_unavailable"
            complete = False
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=organization.pk)
            if complete:
                try:
                    require_settled_project_mutations(organization.pk, exclude_own=True)
                except ArtifactStorageError:
                    error, complete = "artifact_unavailable", False
            current = OrganizationDeletionRun.objects.select_for_update().get(pk=run.pk)
            if current.claimed_at != now or current.state != current.State.PENDING:
                raise ValidationError("Deletion attempt was superseded; re-list storage before retrying.")
            current.claimed_at = None
            current.storage_removed_count += removed  # Observed success only; unknown deletes re-list on retry.
            current.last_error_category = error
            if complete:
                current.state = current.State.STORAGE_CLEARED
            current.save(update_fields=["claimed_at", "storage_removed_count", "last_error_category", "state"])
            return current


def _customer_deletion_order():
    """Children before protected parents; fail closed if a new relation makes a cycle."""
    scope = {**CUSTOMER, **SECRETS,
             "jobs.UsageReservation": "organization_id", "jobs.AIUsageRecord": "organization_id"}
    scope.pop("tenancy.Organization")  # Restricted billing/audit/eligibility retain an anonymized org shell.
    remaining = set(scope)
    ordered = []
    while remaining:
        leaves = sorted(label for label in remaining if not any(
            relation.remote_field.model._meta.label == label
            for other in remaining if other != label
            for relation in apps.get_model(other)._meta.concrete_fields
             if relation.is_relation and (relation.many_to_one or relation.one_to_one)))
        if not leaves:
            raise RuntimeError("Customer deletion dependencies require review.")
        ordered.extend(leaves)
        remaining.difference_update(leaves)
    return [(apps.get_model(label), scope[label]) for label in ordered]


def delete_customer_database_records(*, run, now=None):
    with project_artifact_barrier(run.organization_id, shared=False, timeout_ms=WRITER_ADMISSION_TIMEOUT_MS):
        return _delete_customer_database_records(run=run, now=now)


def _delete_customer_database_records(*, run, now=None):
    now = now or timezone.now()
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=run.organization_id)
        current = OrganizationDeletionRun.objects.select_for_update().get(pk=run.pk, organization=organization)
        _eligibility(organization, now)
        if current.source == current.Source.OWNER_CLOSED:
            require_confirmed_closed_billing(organization)
        if current.state == current.State.COMPLETE:
            return current
        if current.state != current.State.STORAGE_CLEARED or current.claimed_at is not None:
            raise ValidationError("Customer artifact versions must be cleared first.")
        require_complete_ownership_map()
        from integrations.models import RepositoryConsent, RepositoryGrant, YandexOAuthGrant, YandexOAuthIntent, BusinessProfileOAuthGrant, BusinessProfileOAuthIntent, GA4OAuthGrant, GoogleOAuthGrant
        from jobs.models import AuthorityLinkReview, AuthorityProspectReview, ContentLifecycleReview, ContentRevision, CrawlPageSnapshot, JobRun, JobStatus, LocalFeedbackReview, UsageReservation
        if (GoogleOAuthGrant.objects.filter(organization=organization).exclude(
                state=GoogleOAuthGrant.State.REVOKED).exists()
            or GA4OAuthGrant.objects.filter(organization=organization).exclude(
                state=GA4OAuthGrant.State.REVOKED).exists()
            or BusinessProfileOAuthGrant.objects.filter(organization=organization).exclude(state="revoked").exists()
            or YandexOAuthGrant.objects.filter(organization=organization).exclude(state="revoked").exists()
            or RepositoryGrant.objects.filter(organization=organization).exclude(state="revoked").exists()):
            raise ValidationError("Confirm provider grant revocation before deleting customer records.")
        if RepositoryConsent.objects.filter(organization=organization, status="consumed", repositorygrant__isnull=True).filter(
                Q(user_reported_revoked_at__isnull=True) | Q(used_at__gt=now - timedelta(minutes=10))).exists():
            raise ValidationError("Resolve unknown repository authorization before deleting customer records.")
        if YandexOAuthIntent.objects.filter(organization=organization, status="consumed", yandexoauthgrant__isnull=True).filter(
                Q(user_reported_revoked_at__isnull=True) | Q(used_at__gt=now - timedelta(minutes=10))).exists():
            raise ValidationError("Resolve the unknown Yandex token exchange before deleting customer records.")
        if BusinessProfileOAuthIntent.objects.filter(organization=organization, status="consumed",
                used_at__gt=now - timedelta(minutes=10), businessprofileoauthgrant__isnull=True).exists():
            raise ValidationError("Wait for the in-flight business consent exchange before deleting customer records.")
        if (JobRun.objects.filter(organization=organization, status__in=[
            JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.WAITING_PROVIDER]).exists()
            or UsageReservation.objects.filter(organization=organization,
                                               state=UsageReservation.State.RESERVED).exists()):
            raise ValidationError("Finish or cancel customer jobs and usage before deleting records.")
        if list(Project.objects.filter(organization=organization).order_by("pk").values_list(
            "pk", flat=True)) != current.project_ids:
            raise ValidationError("Project scope changed after deletion was prepared.")
        for project_id in current.project_ids:
            project = Project.objects.filter(pk=project_id, organization=organization).first()
            if project is None:
                raise ValidationError("Deletion project identity changed.")
            if project_artifact_versions_remain(project=project):
                raise ValidationError("Project storage changed after the last confirmed deletion pass.")
        if organization_export_versions_remain(organization=organization):
            raise ValidationError("Organization export storage changed after the last confirmed deletion pass.")
        from .models import AuditEvent, AuditEventType
        for event in AuditEvent.objects.filter(organization=organization, event_type__in=[
            AuditEventType.TRIAL_APPROVED, AuditEventType.TRIAL_EXTENDED
        ]).only("pk", "details").iterator():
            if "reason" in event.details:
                AuditEvent.objects.filter(pk=event.pk).update(details={key: value for key, value in event.details.items()
                    if key != "reason"})  # Keep policy history, remove free-text customer content.
        AuditEvent.objects.filter(organization=organization,
            event_type=AuditEventType.ORGANIZATION_EXPORT_ACCESSED, project__isnull=False).update(project=None)
        AuditEvent.objects.filter(organization=organization).exclude(
            Q(event_type__startswith="billing.") | Q(event_type__startswith="trial.")
            | Q(event_type__in=["organization.closed", "organization.retention_elapsed",
                                "organization.export_accessed"])
        ).delete()
        if AuditEvent.objects.filter(organization=organization).filter(
            Q(project__isnull=False) | Q(invitation__isnull=False)).exists():
            raise ValidationError("Restricted audit records still reference customer content.")
        JobRun.objects.filter(organization=organization, retry_of__isnull=False).update(retry_of=None)
        CrawlPageSnapshot.objects.filter(project__organization=organization,
                                          reused_from__isnull=False).update(reused_from=None)
        # Delete newest snapshots first so exact-reviewed self references remain
        # intact until their dependent approval/history snapshots are erased.
        for revision in ContentLifecycleReview.objects.filter(project__organization=organization).order_by("-revision", "-pk").iterator():
            revision.delete()
        for revision in ContentRevision.objects.filter(project__organization=organization).order_by("-revision", "-pk").iterator():
            revision.delete()
        for revision in LocalFeedbackReview.objects.filter(project__organization=organization).order_by("-revision", "-pk").iterator():
            revision.delete()
        for revision in AuthorityProspectReview.objects.filter(project__organization=organization).order_by("-revision", "-pk").iterator():
            revision.delete()
        for revision in AuthorityLinkReview.objects.filter(project__organization=organization).order_by("-revision", "-pk").iterator():
            revision.delete()
        # ponytail: one locked transaction for the existing small-tenant ceiling;
        # use bounded per-model deletion cursors if record volumes grow materially.
        for model, lookup in _customer_deletion_order():
            model.objects.filter(**{lookup: organization.pk}).delete()
        from .models import OrganizationCustomerExport
        OrganizationCustomerExport.objects.filter(organization=organization).delete()
        organization.name = f"Deleted organization {organization.pk}"
        organization.save(update_fields=["name", "updated_at"])
        current.state = current.State.COMPLETE
        current.completed_at = now
        current.last_error_category = ""
        current.save(update_fields=["state", "completed_at", "last_error_category"])
        return current
