from tenancy.customer_artifact_barrier import project_artifact_barrier
from django.test import TransactionTestCase
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from allauth.account.models import EmailAddress
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from config.artifacts import ArtifactNotFound, ArtifactStorageError, read_private_artifact, save_private_artifact
from config.test_foundations import TEST_STORAGES
from integrations.ga4_oauth import encrypt_ga4_refresh_token
from integrations.google_tokens import encrypt_refresh_token
from integrations.models import GA4OAuthGrant, GoogleOAuthGrant

from .artifacts import (list_project_artifact_keys, organization_export_scope, project_artifact_scope,
                        read_project_artifact, save_project_artifact)
from .deletion import delete_customer_database_records, prepare_customer_data_deletion, sweep_customer_artifact_versions
from .closure_grants import revoke_closed_analytics_grant, revoke_closed_search_console_grant
from .models import (AuditEvent, AuditEventType, Organization, OrganizationDeletionRun,
                      OrganizationTrial, OrganizationBillingCancellation, PaddleStatus, PaddleSubscription)
from .paddle_cancellation import reconcile_billing_cancellation
from .services import create_organization, create_project


KEY = Fernet.generate_key().decode()


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}),
                   PADDLE_ENVIRONMENT="sandbox", DEBUG=True,
                   GOOGLE_OAUTH_ENCRYPTION_KEYS=(KEY,), GOOGLE_ANALYTICS_ENCRYPTION_KEYS=(KEY,))
class CustomerDeletionTests(TransactionTestCase):
    def setUp(self):
        dispatch = patch("jobs.services.dispatch_pending", return_value=False)
        self.addCleanup(dispatch.stop)
        dispatch.start()
        users = get_user_model().objects
        self.owner = users.create_user("deletion-owner@example.invalid", password="test-password")
        self.other = users.create_user("deletion-other@example.invalid", password="test-password")
        for actor in (self.owner, self.other):
            EmailAddress.objects.create(user=actor, email=actor.email, primary=True, verified=True)
        self.org = create_organization(user=self.owner, name="Deletion fixture")
        self.project = create_project(organization=self.org, user=self.owner,
                                      name="Own project", canonical_origin="https://deletion.example.invalid")
        self.other_org = create_organization(user=self.other, name="Other deletion fixture")
        self.other_project = create_project(organization=self.other_org, user=self.other,
            name="Other project", canonical_origin="https://other-deletion.example.invalid")

    def test_owner_close_batches_storage_and_does_not_claim_database_deletion(self):
        with project_artifact_barrier(self.project.organization_id, shared=True):
            one = save_project_artifact(project=self.project, content=b'"one"', content_type="application/json")
        with project_artifact_barrier(self.project.organization_id, shared=True):
            two = save_private_artifact(scope=f"{project_artifact_scope(self.project)}/jobs/7",
                                        content=b'"orphan"', content_type="application/json")
        with project_artifact_barrier(self.other_project.organization_id, shared=True):
            foreign = save_project_artifact(project=self.other_project, content=b'"foreign"',
                                            content_type="application/json")
        with self.assertRaises(PermissionDenied):
            prepare_customer_data_deletion(organization=self.org)
        closed_at = timezone.now()
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=closed_at)
        run = prepare_customer_data_deletion(organization=self.org)
        self.assertEqual((run.source, run.project_ids), (run.Source.OWNER_CLOSED, [self.project.pk]))
        self.assertEqual(run.due_at, closed_at + timedelta(days=30))
        self.assertEqual(prepare_customer_data_deletion(organization=self.org).pk, run.pk)
        run = sweep_customer_artifact_versions(run=run, limit=1)
        self.assertEqual(run.state, run.State.PENDING)
        self.assertEqual(run.attempts, 1)
        for _ in range(3):
            run = sweep_customer_artifact_versions(run=run, limit=1)
        self.assertEqual(run.state, run.State.STORAGE_CLEARED)
        self.assertIsNone(run.completed_at)
        self.assertEqual(list_project_artifact_keys(project=self.project), [])
        self.assertEqual(read_project_artifact(project=self.other_project, key=foreign), b'"foreign"')
        self.assertTrue(self.project.__class__.objects.filter(pk=self.project.pk).exists())
        self.assertNotIn(foreign, {one, two})

    def test_uncertain_mutation_blocks_empty_storage_receipt_and_database_erasure(self):
        from django.core.files.storage import storages
        from .models import ProjectArtifactMutationAttempt
        storage = storages["artifacts"]
        with project_artifact_barrier(self.org.pk, shared=True):
            with patch.object(storage, "save", side_effect=TimeoutError("fixture unknown storage")):
                with self.assertRaises(ArtifactStorageError):
                    save_project_artifact(project=self.project, content=b"{}", content_type="application/json")
        attempt = ProjectArtifactMutationAttempt.objects.get(organization=self.org)
        self.assertIsNone(attempt.mutations.get().settled_at)
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
        run = prepare_customer_data_deletion(organization=self.org)
        run = sweep_customer_artifact_versions(run=run)
        self.assertEqual((run.state, run.last_error_category), (run.State.PENDING, "artifact_unavailable"))
        self.assertFalse(list_project_artifact_keys(project=self.project))
        # Even an old storage-cleared receipt plus one empty listing cannot erase the uncertainty.
        OrganizationDeletionRun.objects.filter(pk=run.pk).update(state=run.State.STORAGE_CLEARED)
        with self.assertRaisesRegex(ArtifactStorageError, "mutation is unresolved"):
            sweep_customer_artifact_versions(run=run)
        with self.assertRaisesRegex(ArtifactStorageError, "mutation is unresolved"):
            delete_customer_database_records(run=run)
        self.assertTrue(type(self.project).objects.filter(pk=self.project.pk).exists())
        self.assertTrue(ProjectArtifactMutationAttempt.objects.filter(pk=attempt.pk).exists())
        Organization.objects.filter(pk=self.other_org.pk).update(is_suspended=True, closed_at=timezone.now())
        self.assertEqual(sweep_customer_artifact_versions(
            run=prepare_customer_data_deletion(organization=self.other_org)).state, run.State.STORAGE_CLEARED)

    def test_late_project_artifact_reopens_cleared_storage_before_database_deletion(self):
        with project_artifact_barrier(self.other_project.organization_id, shared=True):
            foreign = save_project_artifact(project=self.other_project, content=b'"foreign"',
                                            content_type="application/json")
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
        run = prepare_customer_data_deletion(organization=self.org)
        run = sweep_customer_artifact_versions(run=run)
        self.assertEqual(run.state, run.State.STORAGE_CLEARED)
        with project_artifact_barrier(self.project.organization_id, shared=True):
            orphan = save_private_artifact(scope=f"{project_artifact_scope(self.project)}/jobs/51",
                                           content=b'"late"', content_type="application/json")
        with self.assertRaises(ValidationError):
            delete_customer_database_records(run=run)
        self.assertEqual(read_project_artifact(project=self.project, key=orphan), b'"late"')
        with self.assertRaises(ValidationError):
            run.state = run.State.PENDING
            run.save(update_fields=["state"])  # No unverified manual reset.
        run.refresh_from_db()
        output = StringIO()
        call_command("process_customer_deletions", "--execute", "--limit", "1", stdout=output)
        self.assertIn("attempted=1 completed=1 blocked=0", output.getvalue())
        self.assertEqual(OrganizationDeletionRun.objects.get(pk=run.pk).state, run.State.COMPLETE)
        self.assertEqual(read_project_artifact(project=self.other_project, key=foreign), b'"foreign"')

    @override_settings(ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "application/zip"}))
    def test_closed_organization_purges_private_export_parts_and_rechecks_late_copy(self):
        from .customer_snapshot import reserve_bounded_customer_snapshot, current_customer_snapshot
        from .tasks import capture_customer_snapshot_task
        from .models import OrganizationCustomerExport
        with patch("tenancy.tasks.capture_customer_snapshot_task.apply_async"):
            snapshot = reserve_bounded_customer_snapshot(organization=self.org, actor=self.owner,
                request_key="a" * 32, format="coherent-parts-v3")
        self.assertTrue(capture_customer_snapshot_task.run(snapshot.pk))
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.state, snapshot.State.READY)
        own = snapshot.parts.order_by("position").first().storage_key
        self.assertEqual(current_customer_snapshot(organization=self.org, actor=self.owner,
            snapshot_id=snapshot.pk).pk, snapshot.pk)
        foreign = save_private_artifact(scope=organization_export_scope(self.other_org) + "/" + "a" * 32,
                                        content=b'"foreign export"', content_type="application/json")
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
        with self.assertRaises(PermissionDenied):
            current_customer_snapshot(organization=self.org, actor=self.owner, snapshot_id=snapshot.pk)
        run = prepare_customer_data_deletion(organization=self.org)
        run = sweep_customer_artifact_versions(run=run, limit=1)
        self.assertEqual(run.state, run.State.PENDING)
        self.assertEqual(run.storage_removed_count, 1)
        with self.assertRaises(ValidationError):
            delete_customer_database_records(run=run)
        run = sweep_customer_artifact_versions(run=run)
        self.assertEqual(run.state, run.State.STORAGE_CLEARED)
        late = save_private_artifact(scope=organization_export_scope(self.org) + "/" + "b" * 32,
                                     content=b'"late copy"', content_type="application/json")
        with self.assertRaises(ValidationError):
            delete_customer_database_records(run=run)
        run = sweep_customer_artifact_versions(run=run)
        self.assertEqual(run.state, run.State.STORAGE_CLEARED)
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(OrganizationCustomerExport.objects.filter(pk=snapshot.pk).exists())
        self.assertFalse(snapshot.parts.exists())
        with self.assertRaises(ArtifactNotFound):
            read_private_artifact(own)
        with self.assertRaises(ArtifactNotFound):
            read_private_artifact(late)
        self.assertEqual(read_private_artifact(foreign), b'"foreign export"')

    def test_storage_failure_is_retryable_and_a_late_paid_reactivation_pauses_lapsed_cleanup(self):
        with project_artifact_barrier(self.project.organization_id, shared=True):
            save_project_artifact(project=self.project, content=b'"safe"', content_type="application/json")
        now = timezone.now()
        OrganizationTrial.objects.filter(organization=self.org).update(
            started_at=now - timedelta(days=121), ends_at=now - timedelta(days=91))
        run = prepare_customer_data_deletion(organization=self.org)
        self.assertEqual(run.source, run.Source.TRIAL_ELAPSED)
        with patch("tenancy.artifacts.delete_project_artifact", side_effect=ArtifactStorageError("unknown outcome")):
            run = sweep_customer_artifact_versions(run=run)
        self.assertEqual((run.state, run.last_error_category, run.attempts),
                         (run.State.PENDING, "artifact_unavailable", 1))
        self.assertEqual(len(list_project_artifact_keys(project=self.project)), 1)
        PaddleSubscription.objects.create(organization=self.org, environment="sandbox",
            customer_id="ctm_" + "a" * 26, subscription_id="sub_" + "b" * 26,
            status=PaddleStatus.ACTIVE, verified_at=now - timedelta(days=1),
            period_starts_at=now - timedelta(days=1), period_ends_at=now + timedelta(days=29),
            currency_code="USD")
        with self.assertRaises(PermissionDenied):
            sweep_customer_artifact_versions(run=run)
        self.assertEqual(OrganizationDeletionRun.objects.get(pk=run.pk).attempts, 1)
        self.assertEqual(len(list_project_artifact_keys(project=self.project)), 1)

    def test_completed_deletion_removes_only_customer_content_and_keeps_restricted_org_history(self):
        from jobs.models import Artifact, JobRun, JobStatus
        from jobs.services import create_job

        job = create_job(project=self.project, actor=self.owner, handler="diagnostic_probe",
                         input_snapshot={"sample": "customer evidence", "simulate_partial": False})
        JobRun.objects.filter(pk=job.pk).update(status=JobStatus.CANCELLED)
        with project_artifact_barrier(self.project.organization_id, shared=True):
            key = save_project_artifact(project=self.project, content=b'"private evidence"',
                                        content_type="application/json")
        Artifact.objects.create(job=job, project=self.project, key=key, content_type="application/json",
                                size_bytes=len(b'"private evidence"'))
        AuditEvent.objects.create(organization=self.org, actor=self.owner,
            event_type=AuditEventType.TRIAL_APPROVED,
            details={"reason": "private.example.invalid", "after": {"state": "active"}})
        with project_artifact_barrier(self.other_project.organization_id, shared=True):
            foreign_key = save_project_artifact(project=self.other_project, content=b'"foreign"',
                                                content_type="application/json")
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
        run = prepare_customer_data_deletion(organization=self.org)
        with self.assertRaises(ValidationError):
            delete_customer_database_records(run=run)
        run = sweep_customer_artifact_versions(run=run)
        self.assertEqual(run.state, run.State.STORAGE_CLEARED)
        run = delete_customer_database_records(run=run)
        self.assertEqual(run.state, run.State.COMPLETE)
        self.assertIsNotNone(run.completed_at)
        self.assertFalse(self.project.__class__.objects.filter(pk=self.project.pk).exists())
        self.assertFalse(JobRun.objects.filter(pk=job.pk).exists())
        self.org.refresh_from_db()
        self.assertEqual(self.org.name, f"Deleted organization {self.org.pk}")
        self.assertTrue(OrganizationTrial.objects.filter(organization=self.org).exists())
        self.assertEqual(AuditEvent.objects.get(organization=self.org,
            event_type=AuditEventType.TRIAL_APPROVED).details, {"after": {"state": "active"}})
        self.assertEqual(read_project_artifact(project=self.other_project, key=foreign_key), b'"foreign"')

    def test_explicit_runner_advances_only_due_tenants_and_reports_safe_counts(self):
        with project_artifact_barrier(self.project.organization_id, shared=True):
            own_key = save_project_artifact(project=self.project, content=b'"private"',
                                            content_type="application/json")
        with project_artifact_barrier(self.other_project.organization_id, shared=True):
            foreign_key = save_project_artifact(project=self.other_project, content=b'"other"',
                                                content_type="application/json")
        with self.assertRaises(CommandError):
            call_command("process_customer_deletions", stdout=StringIO())
        self.assertEqual(read_project_artifact(project=self.project, key=own_key), b'"private"')
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
        output = StringIO()
        call_command("process_customer_deletions", "--execute", "--limit", "1", stdout=output)
        self.assertIn("attempted=1 completed=1 blocked=0", output.getvalue())
        self.assertNotIn(self.org.name, output.getvalue())
        self.assertTrue(OrganizationDeletionRun.objects.get(organization=self.org).completed_at)
        self.assertEqual(read_project_artifact(project=self.other_project, key=foreign_key), b'"other"')

    def test_retention_runner_reaches_eligible_tenant_past_thousand_ineligible_tenants(self):
        Organization.objects.bulk_create([Organization(name=f"Future tenant {number}")
                                          for number in range(1001)], batch_size=200)
        due = Organization.objects.create(name="Eligible tail tenant", is_suspended=True,
                                          closed_at=timezone.now() - timedelta(days=1))
        self.assertEqual(prepare_customer_data_deletion(organization=due).state,
                         OrganizationDeletionRun.State.PENDING)
        output = StringIO()
        call_command("process_customer_deletions", "--execute", "--limit", "1", stdout=output)
        self.assertIn("attempted=1 completed=1 blocked=0", output.getvalue())
        self.assertEqual(OrganizationDeletionRun.objects.get(organization=due).state,
                         OrganizationDeletionRun.State.COMPLETE)

    def test_blocked_paid_closure_does_not_starve_another_due_tenant_next_pass(self):
        now = timezone.now()
        PaddleSubscription.objects.create(organization=self.org, environment="sandbox",
            customer_id="ctm_" + "a" * 26, subscription_id="sub_" + "b" * 26,
            status=PaddleStatus.ACTIVE, verified_at=now - timedelta(minutes=5),
            period_starts_at=now - timedelta(days=1), period_ends_at=now + timedelta(days=29),
            currency_code="USD")
        Organization.objects.filter(pk__in=[self.org.pk, self.other_org.pk]).update(
            is_suspended=True, closed_at=now)
        output = StringIO()
        call_command("process_customer_deletions", "--execute", "--limit", "1", stdout=output)
        self.assertIn("attempted=1 completed=0 blocked=1", output.getvalue())
        blocked = OrganizationDeletionRun.objects.get(organization=self.org)
        self.assertEqual(blocked.attempts, 1)
        self.assertEqual(blocked.state, blocked.State.PENDING)
        output = StringIO()
        call_command("process_customer_deletions", "--execute", "--limit", "1", stdout=output)
        self.assertIn("attempted=1 completed=1 blocked=0", output.getvalue())
        self.assertEqual(OrganizationDeletionRun.objects.get(organization=self.other_org).state,
                         OrganizationDeletionRun.State.COMPLETE)
        self.assertEqual(OrganizationDeletionRun.objects.get(organization=self.org).state,
                         OrganizationDeletionRun.State.PENDING)

    def test_trial_lapse_disables_sources_then_retries_exact_provider_grants_before_deletion(self):
        now = timezone.now()
        google = GoogleOAuthGrant.objects.create(organization=self.org, project=self.project, actor=self.owner,
            encrypted_refresh_token=encrypt_refresh_token("TRIAL-SEARCH"),
            scope="https://www.googleapis.com/auth/webmasters.readonly", verified_at=now)
        analytics = GA4OAuthGrant.objects.create(organization=self.org, project=self.project, actor=self.owner,
            encrypted_refresh_token=encrypt_ga4_refresh_token("TRIAL-ANALYTICS"),
            scope="https://www.googleapis.com/auth/analytics.readonly", verified_at=now)
        OrganizationTrial.objects.filter(organization=self.org).update(
            started_at=now - timedelta(days=121), ends_at=now - timedelta(days=91))
        run = prepare_customer_data_deletion(organization=self.org)
        google.refresh_from_db(); analytics.refresh_from_db()
        self.assertEqual((google.state, analytics.state), (google.State.REVOCATION_PENDING,
                                                         analytics.State.REVOCATION_PENDING))
        self.assertEqual(AuditEvent.objects.filter(organization=self.org,
            event_type=AuditEventType.ORGANIZATION_RETENTION_ELAPSED).count(), 1)
        with self.assertRaises(ValidationError):
            delete_customer_database_records(run=sweep_customer_artifact_versions(run=run))
        self.assertEqual(revoke_closed_search_console_grant(grant_id=google.pk,
            revoke=lambda **_: False).state, google.State.REVOCATION_PENDING)
        self.assertEqual(revoke_closed_search_console_grant(grant_id=google.pk,
            revoke=lambda *, encrypted_refresh: encrypted_refresh.startswith("v1:")).state, google.State.REVOKED)
        self.assertEqual(revoke_closed_analytics_grant(grant_id=analytics.pk,
            revoke=lambda *, token: token == "TRIAL-ANALYTICS").state, analytics.State.REVOKED)
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertTrue(AuditEvent.objects.filter(organization=self.org,
            event_type=AuditEventType.ORGANIZATION_RETENTION_ELAPSED).exists())

    def test_reactivated_paid_tenant_cannot_revoke_a_pending_lapsed_grant(self):
        now = timezone.now()
        grant = GoogleOAuthGrant.objects.create(organization=self.org, project=self.project, actor=self.owner,
            encrypted_refresh_token=encrypt_refresh_token("DO-NOT-REVOKE"),
            scope="https://www.googleapis.com/auth/webmasters.readonly", verified_at=now)
        OrganizationTrial.objects.filter(organization=self.org).update(
            started_at=now - timedelta(days=121), ends_at=now - timedelta(days=91))
        run = prepare_customer_data_deletion(organization=self.org)
        PaddleSubscription.objects.create(organization=self.org, environment="sandbox",
            customer_id="ctm_" + "a" * 26, subscription_id="sub_" + "b" * 26,
            status=PaddleStatus.ACTIVE, verified_at=now - timedelta(hours=1),
            period_starts_at=now - timedelta(hours=1), period_ends_at=now + timedelta(days=30),
            currency_code="USD")
        with self.assertRaises(PermissionDenied):
            revoke_closed_search_console_grant(grant_id=grant.pk,
                revoke=lambda **_: self.fail("No provider request after paid reactivation"))
        self.assertEqual(GoogleOAuthGrant.objects.get(pk=grant.pk).state, grant.State.REVOCATION_PENDING)
        with self.assertRaises(PermissionDenied):
            sweep_customer_artifact_versions(run=run)

    def test_paid_owner_closure_keeps_artifacts_until_exact_provider_cancellation_is_confirmed(self):
        now = timezone.now()
        with project_artifact_barrier(self.project.organization_id, shared=True):
            key = save_project_artifact(project=self.project, content=b'"retain while uncertain"',
                                        content_type="application/json")
        subscription = PaddleSubscription.objects.create(organization=self.org, environment="sandbox",
            customer_id="ctm_" + "a" * 26, subscription_id="sub_" + "b" * 26,
            status=PaddleStatus.ACTIVE, verified_at=now - timedelta(minutes=5),
            period_starts_at=now - timedelta(days=1), period_ends_at=now + timedelta(days=29),
            currency_code="USD")
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=now)
        run = prepare_customer_data_deletion(organization=self.org)
        self.assertEqual(run.state, run.State.PENDING)
        with self.assertRaises(ValidationError):
            sweep_customer_artifact_versions(run=run)
        with self.assertRaises(ValidationError):
            delete_customer_database_records(run=run)
        with self.assertRaises(ValidationError):
            from .artifacts import delete_closed_project_artifact_batch
            delete_closed_project_artifact_batch(organization=self.org, project=self.project)
        attempt = OrganizationBillingCancellation.objects.create(organization=self.org,
            subscription=subscription, actor=self.owner, environment="sandbox", customer_id=subscription.customer_id,
            provider_subscription_id=subscription.subscription_id, state=OrganizationBillingCancellation.State.UNKNOWN,
            attempted_at=now, error_category="network_error")
        with self.assertRaises(ValidationError):
            sweep_customer_artifact_versions(run=run)
        self.assertEqual(read_project_artifact(project=self.project, key=key), b'"retain while uncertain"')
        response = {"data": {"id": subscription.subscription_id, "customer_id": subscription.customer_id,
                             "status": "canceled", "canceled_at": now.isoformat()}}
        with patch("tenancy.paddle_cancellation.paddle_seller_secrets", return_value=("fixture-only", "")):
            confirmed = reconcile_billing_cancellation(attempt, subscription_get=lambda **_: response)
        self.assertEqual(confirmed.state, confirmed.State.CONFIRMED)
        PaddleSubscription.objects.filter(pk=subscription.pk).update(subscription_id="sub_" + "c" * 26)
        with self.assertRaises(ValidationError):
            sweep_customer_artifact_versions(run=run)
        self.assertEqual(read_project_artifact(project=self.project, key=key), b'"retain while uncertain"')
        PaddleSubscription.objects.filter(pk=subscription.pk).update(subscription_id=subscription.subscription_id)
        self.assertEqual(sweep_customer_artifact_versions(run=run).state, run.State.STORAGE_CLEARED)
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
