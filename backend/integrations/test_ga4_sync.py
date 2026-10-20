from datetime import timedelta
from urllib.parse import urlsplit
from unittest.mock import patch

from allauth.account.models import EmailAddress
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from jobs.models import JobCancellation, JobStatus
from jobs.models import JobStep
from jobs.services import create_job, dispatch_pending, retry_job
from jobs.recovery import reconcile_stuck_ga4_jobs
from jobs.usage import reserve_usage
from tenancy.models import Project
from tenancy.models import AuditEvent, AuditEventType
from tenancy.services import create_organization, create_project, update_project

from .ga4_oauth import SCOPE, encrypt_ga4_refresh_token
from .ga4_sync import METHOD, GA4OriginAttributionUnavailable, record_ga4_landing_page, queue_ga4_landing_sync
from .ga4_sync import execute_ga4_landing_sync
from .google_tokens import GoogleTokens
from .google_tokens import GoogleTokenError
from .search_console_transport import SearchConsoleTransportError
from .models import GA4LandingPageSnapshot, GA4OAuthGrant, IntegrationConnection, SyncCursor
from providers.google_app import GoogleOAuthClient


@override_settings(GOOGLE_ANALYTICS_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),))
class GA4EvidenceTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("ga4-evidence@example.test", password="test-password")
        EmailAddress.objects.create(user=self.owner, email=self.owner.email, primary=True, verified=True)
        organization = create_organization(user=self.owner, name="GA4 evidence fixture")
        self.project = create_project(organization=organization, user=self.owner,
            name="GA4 property", canonical_origin="https://report.example")
        self.grant = GA4OAuthGrant.objects.create(organization=organization, project=self.project, actor=self.owner,
            encrypted_refresh_token=encrypt_ga4_refresh_token("REFRESH_SECRET"), scope=SCOPE,
            property_id="12345", selected_origins=[self.project.canonical_origin],
            state=GA4OAuthGrant.State.ACTIVE, verified_at=timezone.now())
        self.connection = IntegrationConnection.objects.create(project=self.project,
            provider="google_analytics_4", external_property_id="12345",
            credential_reference=self.grant.credential_reference, capabilities=["api_sync", "landing_metrics"],
            available_dimensions=["hostname", "landing_page"], source_semantics="ga4_landing_pages",
            source_semantics_version="ga4-data-v1", timezone="Europe/Istanbul", currency="USD")
        self.day = timezone.now().date() - timedelta(days=5)
        hostname = urlsplit(self.project.canonical_origin).hostname
        self.job = create_job(project=self.project, actor=self.owner, handler="sync_ga4_landing",
            input_snapshot={"connection_id": self.connection.pk, "grant_id": self.grant.pk,
                            "day": self.day.isoformat(), "hostname": hostname, "report_kind": "all_channels"},
            config_snapshot={"grant_revision": self.grant.revision, "property_id": "12345",
                             "origin": self.project.canonical_origin, "currency": "USD", "timezone": "Europe/Istanbul"})
        reserve_usage(job=self.job, provider="google_analytics_4", units=5)
        self.job.status = JobStatus.RUNNING
        self.job.save(update_fields=["status", "updated_at"])
        # Exercise the worker contract with hypothetical exact-origin proof; production has no such proof yet.
        attribution = patch("integrations.ga4_sync._require_exact_origin_reporting")
        attribution.start()
        self.addCleanup(attribution.stop)

    def test_hostname_only_same_host_scheme_or_port_never_queues_or_records(self):
        with patch("integrations.ga4_sync._require_exact_origin_reporting", side_effect=GA4OriginAttributionUnavailable(
            "Exact-origin attribution unavailable.")), patch("integrations.ga4_sync.google_analytics_oauth_client",
            return_value=GoogleOAuthClient("fixture-id", "fixture-secret", "")):
            with self.assertRaises(GA4OriginAttributionUnavailable):
                queue_ga4_landing_sync(project=self.project, actor=self.owner, connection=self.connection,
                    grant=self.grant, day=self.day, idempotency_key="same-host-other-scheme")
            with self.assertRaises(GA4OriginAttributionUnavailable):
                self.record()
            self.assertTrue(self.execute(report=lambda **_: self.fail("No ambiguous provider report allowed")))
        self.job.refresh_from_db()
        self.assertEqual((self.job.status, self.job.error_category, self.job.usage.actual_units),
                         (JobStatus.CANCELLED, "origin_attribution_unavailable", 0))
        self.assertFalse(GA4LandingPageSnapshot.objects.exists())

    def test_historical_hostname_only_pages_are_never_returned_to_browser(self):
        from django.test import Client
        row = self.record()
        browser = Client()
        browser.force_login(self.owner)
        response = browser.get(f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}"
                               f"/analytics/sources/{self.connection.pk}/sync/status/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["report_availability"], "exact_origin_attribution_unavailable")
        self.assertEqual(response.json()["pages"], [])
        self.assertFalse(response.json()["source_current"])
        self.assertNotIn(str(row.result["rows"]), response.content.decode())

    def response(self, path="/landing", *, currency="USD"):
        return {"kind": "analyticsData#runReport", "dimensionHeaders": [
            {"name": "hostName"}, {"name": "landingPagePlusQueryString"}],
            "metricHeaders": [{"name": "sessions"}, {"name": "keyEvents"}, {"name": "totalRevenue"}],
            "rows": [{"dimensionValues": [{"value": "report.example"}, {"value": path}],
                      "metricValues": [{"value": "3"}, {"value": "0"}, {"value": "0"}]}],
            "rowCount": 1, "metadata": {"currencyCode": currency, "timeZone": "Europe/Istanbul"}}

    def record(self, **changes):
        data = {"job": self.job, "connection": self.connection, "grant": self.grant,
                "day": self.day, "origin": self.project.canonical_origin, "offset": 0,
                "response": self.response()}
        data.update(changes)
        return record_ga4_landing_page(**data)

    def test_immutable_page_replay_preserves_source_and_unknown_coverage(self):
        row = self.record()
        self.assertEqual(self.record().pk, row.pk)
        self.assertEqual((row.project_id, row.connection_id, row.grant_id, row.job_id),
                         (self.project.pk, self.connection.pk, self.grant.pk, self.job.pk))
        self.assertEqual(row.result["coverage"]["full_activity_coverage"], "unknown")
        self.assertEqual(row.result["coverage"]["conversion_definition"], "unverified_key_events")
        self.assertNotIn("REFRESH_SECRET", str(row.result))
        with self.assertRaises(ValidationError):
            self.record(response=self.response("/other"))
        with self.assertRaises(ValidationError):
            self.record(response=self.response(currency="EUR"))
        with self.assertRaises(ValidationError):
            row.save()

    def test_cancel_scope_revocation_and_foreign_project_cannot_record(self):
        other = Project.objects.create(organization=self.project.organization,
            canonical_origin="https://other.example", name="Foreign")
        with self.assertRaises(ValidationError):
            GA4LandingPageSnapshot(project=other, connection=self.connection, grant=self.grant,
                job=self.job, property_id="12345", hostname="report.example", day=self.day,
                offset=0, result={}).full_clean()
        JobCancellation.objects.create(job=self.job, requested_by=self.owner)
        with self.assertRaises(PermissionDenied):
            self.record()
        JobCancellation.objects.all().delete()
        update_project(project=self.project, user=self.owner, canonical_origin="https://moved.example")
        with self.assertRaises((PermissionDenied, ValidationError)):
            self.record()

    def execute(self, **overrides):
        stream = {"dataStreams": [{"name": "properties/12345/dataStreams/10", "type": "WEB_DATA_STREAM",
                                   "webStreamData": {"defaultUri": "https://report.example"}}]}
        options = dict(refresh=lambda **_: GoogleTokens("ACCESS_SECRET", None, timezone.now()),
            get_property=lambda **_: {"name": "properties/12345", "timeZone": "Europe/Istanbul",
                                      "currencyCode": "USD"},
            list_streams=lambda **_: stream, check_compatibility=lambda **_: True,
            report=lambda **_: self.response())
        options.update(overrides)
        with patch("integrations.ga4_sync.google_analytics_oauth_client", return_value=GoogleOAuthClient(
            "fixture-id", "fixture-secret", "")):
            return execute_ga4_landing_sync(self.job.pk, **options)

    def test_budgeted_worker_records_one_page_and_settles_actual_attempts(self):
        self.assertTrue(self.execute())
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, JobStatus.SUCCEEDED)
        self.assertEqual(self.job.output["requests_attempted"], 4)
        self.assertEqual(self.job.output["pages_recorded"], 1)
        self.assertEqual(GA4LandingPageSnapshot.objects.filter(job=self.job).count(), 1)
        self.assertEqual(self.job.usage.actual_units, 4)
        cursor = SyncCursor.objects.get(connection=self.connection)
        self.assertEqual((cursor.status, cursor.fresh_through), (SyncCursor.Status.SUCCEEDED, self.day))
        self.assertFalse(self.execute())

    def test_quota_after_first_page_retains_partial_and_durable_retry_time(self):
        def report(*, offset, **_):
            if offset == 100:
                raise SearchConsoleTransportError("quota_limited", retryable=True)
            response = self.response()
            response["rowCount"] = 101
            return response
        self.assertTrue(self.execute(report=report))
        self.job.refresh_from_db()
        self.assertEqual((self.job.status, self.job.error_category),
                         (JobStatus.PARTIALLY_SUCCEEDED, "quota_limited"))
        self.assertEqual(self.job.output["requests_attempted"], 5)
        self.assertEqual(self.job.usage.actual_units, 5)
        self.assertEqual(GA4LandingPageSnapshot.objects.filter(job=self.job).count(), 1)
        cursor = SyncCursor.objects.get(connection=self.connection)
        self.assertEqual(cursor.status, SyncCursor.Status.WAITING_PROVIDER)
        self.assertGreater(cursor.retry_after, timezone.now())

    def test_two_page_cap_never_claims_complete_when_provider_reports_more(self):
        def report(*, offset, **_):
            response = self.response("/landing" if offset == 0 else "/other")
            response["rowCount"] = 201
            return response
        self.assertTrue(self.execute(report=report))
        self.job.refresh_from_db()
        self.assertEqual((self.job.status, self.job.error_category, self.job.output["pages_recorded"]),
                         (JobStatus.PARTIALLY_SUCCEEDED, "report_coverage_limited", 2))
        self.assertIsNone(SyncCursor.objects.get(connection=self.connection).fresh_through)

    def test_organic_session_acquisition_is_separate_and_never_infers_gsc_clicks(self):
        from jobs.models import JobRun
        JobRun.objects.filter(pk=self.job.pk).update(input_snapshot={**self.job.input_snapshot,
            "report_kind": "organic_search"})
        self.job.refresh_from_db()
        def report(**kwargs):
            self.assertEqual(kwargs["report_kind"], "organic_search")
            self.assertEqual(kwargs["property_timezone"], "Europe/Istanbul")
            response = self.response()
            response["dimensionHeaders"].append({"name": "sessionDefaultChannelGroup"})
            response["rows"][0]["dimensionValues"].append({"value": "Organic Search"})
            return response
        self.assertTrue(self.execute(report=report, check_compatibility=lambda **kwargs: kwargs["report_kind"] == "organic_search"))
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, JobStatus.SUCCEEDED)
        page = GA4LandingPageSnapshot.objects.get(job=self.job)
        self.assertEqual(page.report_kind, "organic_search")
        self.assertEqual(page.result["rows"][0]["session_default_channel_group"], "Organic Search")
        self.assertEqual(page.result["coverage"]["search_clicks"], "not_reported")
        self.assertFalse(page.result["coverage"]["instrumentation_verified"])

    def test_stale_attempt_is_not_resent_and_cancelled_job_releases_unattempted_units(self):
        JobStep.objects.create(job=self.job, sequence=1, name="GA4 property check",
                               status=JobStep.Status.RUNNING, output={"state": "attempted"})
        self.assertTrue(self.execute(get_property=lambda **_: self.fail("uncertain request must not repeat")))
        self.job.refresh_from_db()
        self.assertEqual((self.job.status, self.job.error_category),
                         (JobStatus.FAILED, "request_outcome_unknown"))
        self.assertEqual(self.job.usage.actual_units, 1)

    def test_definitive_refresh_denial_disconnects_only_this_source(self):
        def invalid(**_):
            raise GoogleTokenError("authorization_rejected")
        self.assertTrue(self.execute(refresh=invalid))
        self.job.refresh_from_db()
        self.connection.refresh_from_db()
        self.grant.refresh_from_db()
        self.assertEqual((self.job.status, self.job.error_category), (JobStatus.CANCELLED, "authorization_rejected"))
        self.assertEqual((self.connection.state, self.grant.state),
                         (IntegrationConnection.State.DISCONNECTED, GA4OAuthGrant.State.RECONNECT_REQUIRED))
        self.assertEqual(self.job.usage.actual_units, 0)
        self.assertEqual(AuditEvent.objects.filter(project=self.project,
            event_type=AuditEventType.GA4_RECONNECT_REQUIRED).count(), 1)

    def test_actor_scope_removed_after_provider_attempt_stops_next_step(self):
        def changed(**_):
            update_project(project=self.project, user=self.owner, canonical_origin="https://moved.example")
            return {"name": "properties/12345", "timeZone": "Europe/Istanbul", "currencyCode": "USD"}
        self.assertTrue(self.execute(get_property=changed, list_streams=lambda **_: self.fail("no second request")))
        self.job.refresh_from_db()
        self.assertEqual((self.job.status, self.job.error_category), (JobStatus.CANCELLED, "source_revoked"))
        self.assertEqual(self.job.usage.actual_units, 1)
        self.assertFalse(GA4LandingPageSnapshot.objects.filter(job=self.job).exists())

    def test_stale_running_is_republished_once_but_does_not_repeat_uncertain_request(self):
        JobStep.objects.create(job=self.job, sequence=1, name="GA4 property check",
                               status=JobStep.Status.RUNNING, output={"state": "attempted"})
        from jobs.models import JobRun
        JobRun.objects.filter(pk=self.job.pk).update(updated_at=timezone.now() - timedelta(minutes=4))
        with patch("jobs.tasks.sync_ga4_landing_task.apply_async") as publish:
            self.assertEqual(reconcile_stuck_ga4_jobs(limit=1, stale_seconds=120), 1)
            self.assertEqual(reconcile_stuck_ga4_jobs(limit=1, stale_seconds=120), 0)
        self.assertEqual(publish.call_count, 1)
        self.assertTrue(self.execute(get_property=lambda **_: self.fail("uncertain provider call not repeated")))
        self.assertEqual(JobRun.objects.get(pk=self.job.pk).error_category, "request_outcome_unknown")

    def test_dispatch_uses_only_dedicated_default_task_and_generic_retry_is_denied(self):
        from jobs.models import JobRun
        JobRun.objects.filter(pk=self.job.pk).update(status=JobStatus.QUEUED)
        with patch("jobs.tasks.sync_ga4_landing_task.apply_async") as publish:
            self.assertTrue(dispatch_pending(self.job.pk))
            self.assertFalse(dispatch_pending(self.job.pk))
        publish.assert_called_once_with(args=[self.job.pk], queue="default", task_id=f"job-{self.job.pk}", retry=False)
        JobRun.objects.filter(pk=self.job.pk).update(status=JobStatus.FAILED)
        with self.assertRaises(ValidationError):
            retry_job(job=JobRun.objects.get(pk=self.job.pk), actor=self.owner, idempotency_key="not-replayed")
