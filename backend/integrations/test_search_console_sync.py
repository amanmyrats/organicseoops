from datetime import timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from allauth.account.models import EmailAddress
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from jobs.models import JobRun, JobStatus, JobStep, UsageReservation
from jobs.recovery import reconcile_stuck_search_console_jobs
from tenancy.services import create_organization, create_project, update_project
from tenancy.models import AuditEvent, AuditEventType, Project, ProjectOriginVerification

from .google_tokens import GoogleTokenError, GoogleTokens, SCOPE
from .google_oauth import RECONNECT_METHOD, require_google_reconnect
from .models import GoogleOAuthGrant, IntegrationConnection, SearchAnalyticsPageSnapshot, SyncCursor
from .search_console_sync import _finish, execute_search_console_sync, queue_search_console_sync
from .search_console_transport import SearchConsoleTransportError
from .services import create_connection


@override_settings(GOOGLE_OAUTH_CLIENT_ID="fixture-client", GOOGLE_OAUTH_CLIENT_SECRET="fixture-secret",
                   GOOGLE_OAUTH_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),))
class SearchConsoleSyncTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("sync-owner@example.com", password="test-password")
        EmailAddress.objects.create(user=self.user, email=self.user.email, verified=True, primary=True)
        org = create_organization(user=self.user, name="Sync org")
        self.project = create_project(organization=org, user=self.user, name="Sync project",
                                      canonical_origin="https://sync.example")
        self.connection = create_connection(
            project=self.project, user=self.user, provider="google_search_console",
            external_property_id="https://sync.example/", capabilities=["api_sync", "query_metrics", "page_metrics"],
            available_dimensions=["date", "query", "page"], source_semantics="search_console_performance",
            source_semantics_version="gsc-performance-v1", timezone="America/Los_Angeles",
        )
        self.grant = GoogleOAuthGrant.objects.create(
            organization=org, project=self.project, actor=self.user, scope=SCOPE, verified_at=timezone.now(),
            encrypted_refresh_token="v1:fixture-ciphertext", state=GoogleOAuthGrant.State.ACTIVE,
            selected_property_id=self.connection.external_property_id, selected_site_url="https://sync.example/",
        )
        self.connection.credential_reference = self.grant.credential_reference
        self.connection.save()
        self.day = timezone.now().astimezone(ZoneInfo("America/Los_Angeles")).date() - timedelta(days=5)
        self.refresh = lambda **kwargs: GoogleTokens("fixture-access", None, timezone.now() + timedelta(minutes=20))
        self.site = lambda **kwargs: {"siteUrl": "https://sync.example/", "permissionLevel": "siteOwner"}

    def queue(self, *, dimensions=None, key="fixture-sync"):
        with patch("jobs.services.dispatch_pending"):
            return queue_search_console_sync(project=self.project, actor=self.user, connection=self.connection,
                grant=self.grant, day=self.day, dimensions=dimensions or ["query"], idempotency_key=key)

    def assert_reconnect_audit(self, reason):
        audit = AuditEvent.objects.filter(project=self.project,
            event_type=AuditEventType.GOOGLE_OAUTH_RECONNECT_REQUIRED).latest("pk")
        self.assertEqual(audit.organization_id, self.project.organization_id)
        self.assertIsNone(audit.actor_id)
        self.assertEqual(audit.details, {"grant_id": self.grant.pk, "connection_ids": [self.connection.pk],
            "reason": reason, "method_version": RECONNECT_METHOD, "grant_revision": self.grant.revision})
        return audit

    def test_released_reservation_does_not_rollback_terminal_denial(self):
        job = self.queue()
        JobRun.objects.filter(pk=job.pk).update(status=JobStatus.RUNNING)
        JobStep.objects.create(
            job=job,
            sequence=1,
            name="Verify selected property",
            status=JobStep.Status.RUNNING,
            output={"state": "attempted"},
        )
        UsageReservation.objects.filter(job=job).update(
            state=UsageReservation.State.RELEASED,
            settled_at=timezone.now(),
        )
        self.assertTrue(_finish(job.pk))
        job.refresh_from_db()
        job.usage.refresh_from_db()
        self.assertEqual((job.status, job.error_category), (JobStatus.CANCELLED, "usage_unreserved"))
        self.assertEqual((job.usage.state, job.usage.actual_units), (UsageReservation.State.RELEASED, 0))

    def test_pagination_and_redelivery_preserve_immutable_api_evidence_and_cursor(self):
        job = self.queue()
        self.assertEqual(job.usage.reserved_units, 3)
        self.assertEqual(self.queue().pk, job.pk)
        def query(*, start_row, **kwargs):
            size = 100 if start_row == 0 else 1
            return {"responseAggregationType": "byProperty", "rows": [
                {"keys": [f"term-{start_row + index}"], "clicks": 1, "impressions": 2,
                 "ctr": .5, "position": 3} for index in range(size)]}
        self.assertTrue(execute_search_console_sync(job.pk, refresh=self.refresh, verify_site=self.site, query=query))
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.SUCCEEDED)
        self.assertEqual((job.usage.actual_units, job.output["pages_recorded"], job.output["truncated"]), (3, 2, False))
        self.assertNotIn("fixture-access", str(job.output))
        self.assertEqual(list(SearchAnalyticsPageSnapshot.objects.filter(job=job).values_list("start_row", flat=True)), [0, 100])
        cursor = SyncCursor.objects.get(connection=self.connection)
        self.assertEqual((cursor.status, cursor.fresh_through), (SyncCursor.Status.SUCCEEDED, self.day))
        self.assertFalse(execute_search_console_sync(job.pk, refresh=self.refresh, verify_site=self.site, query=query))
        self.assertEqual(SearchAnalyticsPageSnapshot.objects.filter(job=job).count(), 2)

    def test_older_success_does_not_erase_newer_freshness(self):
        newer = self.day + timedelta(days=1)
        SyncCursor.objects.create(project=self.project, connection=self.connection, fresh_through=newer)
        job = self.queue(key="older-report")
        def query(**_kwargs):
            return {"responseAggregationType": "byProperty", "rows": []}
        self.assertTrue(execute_search_console_sync(job.pk, refresh=self.refresh, verify_site=self.site, query=query))
        cursor = SyncCursor.objects.get(connection=self.connection)
        self.assertEqual((cursor.coverage_end, cursor.fresh_through), (self.day, newer))

    def test_domain_sync_records_only_verified_origin_pages_and_stops_on_revoke(self):
        verification = ProjectOriginVerification.objects.create(
            organization=self.project.organization, project=self.project, origin=self.project.canonical_origin,
            challenge_digest="a" * 64, state=ProjectOriginVerification.State.VERIFIED,
            verified_at=timezone.now(),
        )
        domain = "sc-domain:sync.example"
        grant = GoogleOAuthGrant.objects.create(
            organization=self.project.organization, project=self.project, actor=self.user, scope=SCOPE,
            encrypted_refresh_token="v1:fixture-ciphertext", state=GoogleOAuthGrant.State.ACTIVE,
            verified_at=timezone.now(), selected_property_id=domain, selected_site_url=domain,
            selected_origins=[self.project.canonical_origin],
        )
        connection = IntegrationConnection(
            project=self.project, provider="google_search_console", external_property_id=domain,
            credential_reference=grant.credential_reference, capabilities=["api_sync", "page_metrics"],
            available_dimensions=["page"], source_semantics="search_console_domain_pages",
            source_semantics_version="gsc-domain-page-v1", timezone="America/Los_Angeles",
        )
        connection.save()
        with self.assertRaises(ValidationError):
            queue_search_console_sync(project=self.project, actor=self.user, connection=connection, grant=grant,
                                      day=self.day, dimensions=["query"], idempotency_key="domain-query")
        with patch("jobs.services.dispatch_pending"):
            job = queue_search_console_sync(project=self.project, actor=self.user, connection=connection,
                                            grant=grant, day=self.day, dimensions=["page"], idempotency_key="domain-1")
        self.assertEqual(job.config_snapshot["approved_origins"], ["https://sync.example"])

        def site(**_kwargs):
            return {"siteUrl": domain, "permissionLevel": "siteOwner"}

        def pages(**_kwargs):
            return {"responseAggregationType": "byPage", "rows": [
                {"keys": [url], "clicks": 1, "impressions": 2, "ctr": .5, "position": 3}
                for url in ("https://sync.example/owned", "https://www.sync.example/sibling")
            ]}

        self.assertTrue(execute_search_console_sync(job.pk, refresh=self.refresh, verify_site=site, query=pages))
        job.refresh_from_db()
        self.assertEqual((job.status, job.output["source_coverage"], job.usage.actual_units),
                         (JobStatus.SUCCEEDED, "top_rows_only_domain_page_filtered", 2))
        self.assertIsNone(job.output["truncated"])
        saved = SearchAnalyticsPageSnapshot.objects.get(job=job)
        self.assertEqual([row["key"] for row in saved.result["observations"]], ["https://sync.example/owned"])
        self.assertNotIn("www.sync.example", str(saved.result))

        with patch("jobs.services.dispatch_pending"):
            lost = queue_search_console_sync(project=self.project, actor=self.user, connection=connection,
                                             grant=grant, day=self.day, dimensions=["page"], idempotency_key="domain-2")

        def revoke_during_request(**_kwargs):
            ProjectOriginVerification.objects.filter(pk=verification.pk).update(
                state=ProjectOriginVerification.State.REVOKED, revoked_at=timezone.now())
            return pages()

        self.assertTrue(execute_search_console_sync(lost.pk, refresh=self.refresh, verify_site=site,
                                                    query=revoke_during_request))
        lost.refresh_from_db()
        self.assertEqual((lost.status, lost.usage.actual_units), (JobStatus.CANCELLED, 2))
        self.assertFalse(SearchAnalyticsPageSnapshot.objects.filter(job=lost).exists())

    def test_domain_foreign_row_threshold_does_not_change_attempts_or_public_status(self):
        ProjectOriginVerification.objects.create(
            organization=self.project.organization, project=self.project, origin=self.project.canonical_origin,
            challenge_digest="a" * 64, state=ProjectOriginVerification.State.VERIFIED,
            verified_at=timezone.now(),
        )
        domain = "sc-domain:sync.example"
        grant = GoogleOAuthGrant.objects.create(
            organization=self.project.organization, project=self.project, actor=self.user, scope=SCOPE,
            encrypted_refresh_token="v1:fixture-ciphertext", state=GoogleOAuthGrant.State.ACTIVE,
            verified_at=timezone.now(), selected_property_id=domain, selected_site_url=domain,
            selected_origins=[self.project.canonical_origin],
        )
        connection = IntegrationConnection(
            project=self.project, provider="google_search_console", external_property_id=domain,
            credential_reference=grant.credential_reference, capabilities=["api_sync", "page_metrics"],
            available_dimensions=["page"], source_semantics="search_console_domain_pages",
            source_semantics_version="gsc-domain-page-v1", timezone="America/Los_Angeles",
        )
        connection.save()
        results = []
        self.client.force_login(self.user)
        for size in (99, 100):
            with patch("jobs.services.dispatch_pending"):
                job = queue_search_console_sync(project=self.project, actor=self.user, connection=connection,
                    grant=grant, day=self.day, dimensions=["page"], idempotency_key=f"domain-{size}")
            self.assertEqual(job.usage.reserved_units, 2)
            requested = []
            def query(*, start_row, **_kwargs):
                requested.append(start_row)
                return {"responseAggregationType": "byPage", "rows": [
                    {"keys": [f"https://sibling.sync.example/{index}"], "clicks": 1, "impressions": 2,
                     "ctr": .5, "position": 3} for index in range(size)]}
            self.assertTrue(execute_search_console_sync(job.pk, refresh=self.refresh,
                verify_site=lambda **_kwargs: {"siteUrl": domain, "permissionLevel": "siteOwner"}, query=query))
            job.refresh_from_db()
            status = self.client.get(f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}/sources/{connection.pk}/sync/status/")
            self.assertEqual(status.status_code, 200)
            public = status.json()["job"]
            public.pop("id")
            results.append((requested, job.output, public, job.usage.actual_units,
                            list(SearchAnalyticsPageSnapshot.objects.filter(job=job).values_list("result", flat=True))))
        # Both jobs store the same empty in-scope observations; neither reveals the foreign row threshold.
        self.assertEqual(results[0][0], [0])
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0][3], 2)

    def test_quota_after_first_dimension_keeps_partial_and_settles_attempts(self):
        job = self.queue(dimensions=["query", "page"], key="partial-sync")
        def query(*, dimension, **kwargs):
            if dimension == "page":
                raise SearchConsoleTransportError("quota_limited", retryable=True)
            return {"responseAggregationType": "byProperty", "rows": [{
                "keys": ["owned"], "clicks": 1, "impressions": 2, "ctr": .5, "position": 2}]}
        self.assertTrue(execute_search_console_sync(job.pk, refresh=self.refresh, verify_site=self.site, query=query))
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category, job.usage.actual_units),
                         (JobStatus.PARTIALLY_SUCCEEDED, "quota_limited", 3))
        self.assertEqual(SearchAnalyticsPageSnapshot.objects.filter(job=job).count(), 1)
        cursor = SyncCursor.objects.get(connection=self.connection)
        self.assertEqual((cursor.status, cursor.quota_state, cursor.fresh_through),
                         (SyncCursor.Status.WAITING_PROVIDER, SyncCursor.QuotaState.LIMITED, None))
        self.assertGreater(cursor.retry_after, timezone.now())
        with self.assertRaises(ValidationError):
            self.queue(dimensions=["query"], key="too-soon")

    def test_scope_removed_during_request_discards_result_and_stops(self):
        job = self.queue(key="revoked-sync")
        def query(**kwargs):
            update_project(project=self.project, user=self.user, canonical_origin="https://changed.example")
            return {"responseAggregationType": "byProperty", "rows": []}
        self.assertTrue(execute_search_console_sync(job.pk, refresh=self.refresh, verify_site=self.site, query=query))
        job.refresh_from_db()
        self.assertEqual((job.status, job.usage.actual_units), (JobStatus.CANCELLED, 2))
        self.assertFalse(SearchAnalyticsPageSnapshot.objects.filter(job=job).exists())

    def test_worker_loss_does_not_repeat_an_attempted_provider_request(self):
        job = self.queue(key="worker-lost-sync")
        def lost(**kwargs):
            raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            execute_search_console_sync(job.pk, refresh=self.refresh, verify_site=self.site, query=lost)
        JobRun.objects.filter(pk=job.pk).update(updated_at=timezone.now() - timedelta(minutes=4))
        with patch("jobs.tasks.sync_search_console_task.apply_async") as republish:
            self.assertEqual(reconcile_stuck_search_console_jobs(stale_seconds=150), 1)
            republish.assert_called_once_with(args=[job.pk], queue="default", task_id=f"job-{job.pk}", retry=False)
        calls = []
        def query(**kwargs):
            calls.append(kwargs)
            return {"responseAggregationType": "byProperty", "rows": []}
        self.assertTrue(execute_search_console_sync(job.pk, refresh=self.refresh, verify_site=self.site, query=query))
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category, job.usage.actual_units),
                         (JobStatus.FAILED, "request_outcome_unknown", 2))
        self.assertFalse(calls)

    def test_lost_property_verification_is_not_replayed_or_unaccounted(self):
        job = self.queue(key="lost-site-get")
        def lost(**kwargs):
            raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            execute_search_console_sync(job.pk, refresh=self.refresh, verify_site=lost)
        verified = []
        def site(**kwargs):
            verified.append(kwargs)
            return self.site(**kwargs)
        self.assertTrue(execute_search_console_sync(job.pk, refresh=self.refresh, verify_site=site))
        job.refresh_from_db()
        self.assertEqual((job.status, job.usage.actual_units, job.output["requests_attempted"]),
                         (JobStatus.FAILED, 1, 1))
        self.assertEqual(job.error_category, "request_outcome_unknown")
        self.assertFalse(verified)

    def test_provider_property_denial_disables_authorization_and_stops_requests(self):
        for category in ("authorization_unavailable", "property_unavailable"):
            with self.subTest(category=category):
                job = self.queue(key="site-" + category)
                def denied(**kwargs):
                    raise SearchConsoleTransportError(category)
                self.assertTrue(execute_search_console_sync(job.pk, refresh=self.refresh, verify_site=denied))
                job.refresh_from_db()
                self.grant.refresh_from_db()
                self.connection.refresh_from_db()
                self.assertEqual((job.status, job.error_category, job.usage.actual_units), (JobStatus.CANCELLED, category, 1))
                self.assertEqual(self.grant.state, GoogleOAuthGrant.State.RECONNECT_REQUIRED)
                self.assertEqual(self.connection.state, self.connection.State.DISCONNECTED)
                self.assertEqual(self.grant.encrypted_refresh_token, "v1:fixture-ciphertext")
                self.assert_reconnect_audit(category)
                if category == "authorization_unavailable":
                    # Restore only this fixture between independent error categories.
                    self.grant.state = GoogleOAuthGrant.State.ACTIVE
                    self.grant.revision += 1
                    self.grant.save()
                    self.connection.state = self.connection.State.ACTIVE
                    self.connection.save()

    def test_mid_report_access_loss_stops_pagination_and_retains_partial_evidence(self):
        job = self.queue(key="mid-report-revoke")
        requested = []
        def query(*, start_row, **kwargs):
            requested.append(start_row)
            if start_row == 100:
                raise SearchConsoleTransportError("authorization_unavailable")
            return {"responseAggregationType": "byProperty", "rows": [
                {"keys": [str(index)], "clicks": 1, "impressions": 2, "ctr": .5, "position": 2}
                for index in range(100)]}
        self.assertTrue(execute_search_console_sync(job.pk, refresh=self.refresh, verify_site=self.site, query=query))
        job.refresh_from_db()
        self.grant.refresh_from_db()
        self.connection.refresh_from_db()
        self.assertEqual(requested, [0, 100])
        self.assertEqual((job.status, job.error_category, job.usage.actual_units),
                         (JobStatus.CANCELLED, "authorization_unavailable", 3))
        self.assertEqual(SearchAnalyticsPageSnapshot.objects.filter(job=job).count(), 1)
        self.assertEqual(self.grant.state, GoogleOAuthGrant.State.RECONNECT_REQUIRED)
        self.assertEqual(self.connection.state, self.connection.State.DISCONNECTED)

        self.assert_reconnect_audit("authorization_unavailable")

    def test_provider_reports_selected_site_unverified(self):
        job = self.queue(key="unverified-site")
        def unverified(**kwargs):
            return {"siteUrl": "https://sync.example/", "permissionLevel": "siteUnverifiedUser"}
        self.assertTrue(execute_search_console_sync(job.pk, refresh=self.refresh, verify_site=unverified))
        job.refresh_from_db()
        self.grant.refresh_from_db()
        self.assertEqual((job.error_category, job.usage.actual_units), ("property_unavailable", 1))
        self.assertEqual(self.grant.state, GoogleOAuthGrant.State.RECONNECT_REQUIRED)

        self.assert_reconnect_audit("property_unavailable")

    def test_definitive_refresh_denial_disconnects_and_preserves_revocation_material(self):
        job = self.queue(key="denied-refresh")
        def rejected(**kwargs):
            raise GoogleTokenError("authorization_rejected")
        self.assertTrue(execute_search_console_sync(job.pk, refresh=rejected, verify_site=self.site))
        job.refresh_from_db()
        self.grant.refresh_from_db()
        self.connection.refresh_from_db()
        self.assertEqual(job.status, JobStatus.CANCELLED)
        self.assertEqual(job.usage.actual_units, 0)
        self.assertEqual(self.grant.state, GoogleOAuthGrant.State.RECONNECT_REQUIRED)
        self.assertEqual(self.connection.state, self.connection.State.DISCONNECTED)
        self.assertEqual(self.grant.encrypted_refresh_token, "v1:fixture-ciphertext")
        self.assertEqual(AuditEvent.objects.filter(project=self.project,
            event_type=AuditEventType.GOOGLE_OAUTH_RECONNECT_REQUIRED).count(), 1)
        with self.assertRaises(ValidationError):
            self.queue(key="rejected-again")

        audit = self.assert_reconnect_audit("provider_refresh_rejected")
        original = (audit.created_at, audit.details.copy())
        require_google_reconnect(grant=self.grant)
        audit.refresh_from_db()
        self.assertEqual((audit.created_at, audit.details), original)
        self.assertEqual(AuditEvent.objects.filter(project=self.project,
            event_type=AuditEventType.GOOGLE_OAUTH_RECONNECT_REQUIRED).count(), 1)

    def test_stale_revision_and_ciphertext_do_not_disconnect_or_capture(self):
        stale = GoogleOAuthGrant.objects.get(pk=self.grant.pk)
        self.grant.revision += 1
        self.grant.save()
        require_google_reconnect(grant=stale)
        stale = GoogleOAuthGrant.objects.get(pk=self.grant.pk)
        stale.encrypted_refresh_token = "v1:stale-ciphertext"
        require_google_reconnect(grant=stale)
        self.grant.refresh_from_db()
        self.connection.refresh_from_db()
        self.assertEqual(self.grant.state, GoogleOAuthGrant.State.ACTIVE)
        self.assertEqual(self.connection.state, IntegrationConnection.State.ACTIVE)
        self.assertFalse(AuditEvent.objects.filter(project=self.project,
            event_type=AuditEventType.GOOGLE_OAUTH_RECONNECT_REQUIRED).exists())

    def test_audit_failure_rolls_back_transition_without_backfilling_legacy(self):
        legacy = AuditEvent.objects.create(organization=self.project.organization, project=self.project,
            event_type=AuditEventType.GOOGLE_OAUTH_RECONNECT_REQUIRED,
            details={"grant_id": self.grant.pk, "connection_ids": [self.connection.pk],
                     "reason": "provider_refresh_rejected"})
        original = (legacy.created_at, legacy.details.copy(), self.grant.revision, self.grant.updated_at,
                    self.connection.updated_at)
        with patch("integrations.google_oauth.AuditEvent.objects.create", side_effect=RuntimeError), self.assertRaises(RuntimeError):
            require_google_reconnect(grant=self.grant)
        self.grant.refresh_from_db()
        self.connection.refresh_from_db()
        legacy.refresh_from_db()
        self.assertEqual((self.grant.state, self.connection.state),
                         (GoogleOAuthGrant.State.ACTIVE, IntegrationConnection.State.ACTIVE))
        self.assertEqual((legacy.created_at, legacy.details, self.grant.revision, self.grant.updated_at,
                          self.connection.updated_at), original)
        current = require_google_reconnect(grant=self.grant)
        self.assertEqual(current.revision, original[2] + 1)
        legacy.refresh_from_db()
        self.assertEqual((legacy.created_at, legacy.details), original[:2])

    def test_invalid_selection_or_foreign_grant_never_queues(self):
        with self.assertRaises(ValidationError):
            self.queue(dimensions=["query", "query"])
        other = Project.objects.create(
            organization=self.project.organization, name="Other sync", canonical_origin="https://other-sync.example",
        )
        foreign = GoogleOAuthGrant.objects.create(
            organization=other.organization, project=other, actor=self.user, scope=SCOPE,
            encrypted_refresh_token="v1:fixture-ciphertext", verified_at=timezone.now(),
        )
        with self.assertRaises(GoogleOAuthGrant.DoesNotExist):
            with patch("jobs.services.dispatch_pending"):
                queue_search_console_sync(project=self.project, actor=self.user, connection=self.connection,
                    grant=foreign, day=self.day, dimensions=["query"], idempotency_key="foreign")
