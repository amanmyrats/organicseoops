from datetime import timedelta
from unittest.mock import patch

from allauth.account.models import EmailAddress
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from jobs.models import JobRun, JobStatus, JobStep, UsageReservation
from jobs.recovery import reconcile_stuck_search_console_coverage
from tenancy.models import Project, ProjectOriginVerification
from tenancy.services import create_organization, create_project

from .google_tokens import GoogleTokens, SCOPE
from .models import GoogleOAuthGrant, IntegrationConnection, SearchConsoleCoverageObservation
from .search_console_coverage_job import execute_search_console_coverage, queue_search_console_coverage
from .search_console_transport import SearchConsoleTransportError


@override_settings(GOOGLE_OAUTH_CLIENT_ID="fixture-client", GOOGLE_OAUTH_CLIENT_SECRET="fixture-secret",
                   GOOGLE_OAUTH_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),))
class SearchConsoleCoverageJobTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user("coverage-owner@example.com", "test-password")
        self.foreign_user = users.create_user("coverage-other@example.com", "test-password")
        for user in (self.owner, self.foreign_user):
            EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
        self.organization = create_organization(user=self.owner, name="Coverage org")
        self.project = create_project(organization=self.organization, user=self.owner,
                                      name="Coverage project", canonical_origin="https://coverage.example")
        self.verification = ProjectOriginVerification.objects.create(
            organization=self.organization, project=self.project, origin=self.project.canonical_origin,
            challenge_digest="a" * 64, state=ProjectOriginVerification.State.VERIFIED,
            verified_at=timezone.now(),
        )
        self.property_id = "sc-domain:coverage.example"
        self.grant = GoogleOAuthGrant.objects.create(
            organization=self.organization, project=self.project, actor=self.owner, scope=SCOPE,
            verified_at=timezone.now(), encrypted_refresh_token="v1:fixture-only",
            state=GoogleOAuthGrant.State.ACTIVE, selected_property_id=self.property_id,
            selected_site_url=self.property_id, selected_origins=[self.project.canonical_origin],
        )
        self.connection = IntegrationConnection(
            project=self.project, provider="google_search_console", external_property_id=self.property_id,
            credential_reference=self.grant.credential_reference,
            capabilities=["api_sync", "page_metrics", "indexing_status", "sitemaps"],
            available_dimensions=["page"], source_semantics="search_console_domain_pages",
            source_semantics_version="gsc-domain-page-v1", timezone="America/Los_Angeles",
        )
        self.connection.save()
        self.page_url = "https://coverage.example/owned"
        self.refresh = lambda **_kwargs: GoogleTokens(
            "ACCESS_SECRET", None, timezone.now() + timedelta(minutes=15))
        self.site = lambda **_kwargs: {"siteUrl": self.property_id, "permissionLevel": "siteOwner"}
        self.sitemaps = lambda **_kwargs: {"sitemap": [
            {"path": "https://coverage.example/sitemap.xml", "contents": [{"indexed": "9000"}]},
            {"path": "https://m.coverage.example/foreign.xml"},
        ]}
        self.inspection = lambda **_kwargs: {"inspectionResult": {"indexStatusResult": {
            "verdict": "PASS", "googleCanonical": "https://m.coverage.example/foreign",
            "userCanonical": self.page_url,
        }}}

    def queue(self, *, key="coverage-1", project=None, user=None, url=None, expect_dispatch=True):
        with patch("jobs.services.dispatch_pending") as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                job = queue_search_console_coverage(
                    project=project or self.project, actor=user or self.owner,
                    connection=self.connection, grant=self.grant,
                    inspection_url=url or self.page_url, idempotency_key=key)
            if expect_dispatch:
                dispatch.assert_called_once_with(job.pk)
            else:
                dispatch.assert_not_called()
        return job

    def execute(self, job, *, site=None, sitemaps=None, inspection=None):
        return execute_search_console_coverage(
            job.pk, refresh=self.refresh, verify_site=site or self.site,
            list_sitemaps=sitemaps or self.sitemaps, inspect=inspection or self.inspection)

    def test_domain_evidence_is_exact_project_owned_and_one_attempt_each(self):
        for url in ("https://m.coverage.example/private", "http://coverage.example/page",
                    "https://coverage.example/?code=PRIVATE_SECRET"):
            with self.subTest(url=url), self.assertRaises(ValidationError):
                self.queue(key="unsafe", url=url)
        self.assertFalse(JobRun.objects.exists())
        job = self.queue()
        self.assertEqual(job.usage.reserved_units, 3)
        self.assertEqual(self.queue(expect_dispatch=False).pk, job.pk)
        self.assertTrue(self.execute(job))
        job.refresh_from_db()
        self.assertEqual((job.status, job.usage.actual_units, job.output["requests_attempted"]),
                         (JobStatus.SUCCEEDED, 3, 3))
        self.assertEqual(set(job.output["sources_recorded"]), {"inspection", "sitemaps"})
        sitemap = SearchConsoleCoverageObservation.objects.get(job=job, source="sitemaps")
        inspected = SearchConsoleCoverageObservation.objects.get(job=job, source="inspection")
        self.assertEqual(sitemap.result["sitemaps"], [{"url": "https://coverage.example/sitemap.xml"}])
        self.assertIsNone(sitemap.result["indexed_url_counts"])
        self.assertIsNone(inspected.result["google_canonical"])
        self.assertEqual(inspected.result["indexed_state"], "reported_indexed")
        self.assertNotIn("ACCESS_SECRET", str(job.output) + str(sitemap.result) + str(inspected.result))
        self.assertFalse(self.execute(job))
        self.assertEqual(SearchConsoleCoverageObservation.objects.filter(job=job).count(), 2)

    def test_outage_keeps_partial_sitemap_evidence_and_no_retry(self):
        job = self.queue(key="partial")
        calls = []

        def inspection(**kwargs):
            calls.append(kwargs["inspection_url"])
            raise SearchConsoleTransportError("quota_limited", retryable=True)

        self.assertTrue(self.execute(job, inspection=inspection))
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category, job.usage.actual_units),
                         (JobStatus.PARTIALLY_SUCCEEDED, "quota_limited", 3))
        self.assertEqual(calls, [self.page_url])
        self.assertEqual(list(SearchConsoleCoverageObservation.objects.filter(job=job).values_list("source", flat=True)),
                         ["sitemaps"])
        self.assertFalse(self.execute(job, inspection=inspection))
        self.assertEqual(calls, [self.page_url])

    def test_invalid_provider_sitemap_shape_is_unknown_not_scope_revocation(self):
        job = self.queue(key="bad-sitemaps")
        self.assertTrue(self.execute(job, sitemaps=lambda **_kw: {"sitemap": "unsafe"},
                                     inspection=lambda **_kw: self.fail("malformed result must stop work")))
        job.refresh_from_db()
        self.grant.refresh_from_db()
        self.assertEqual((job.status, job.error_category, job.usage.actual_units),
                         (JobStatus.FAILED, "malformed_response", 2))
        self.assertEqual(self.grant.state, GoogleOAuthGrant.State.ACTIVE)
        self.assertFalse(SearchConsoleCoverageObservation.objects.filter(job=job).exists())

    def test_scope_revoked_during_sitemap_request_does_not_store_or_disconnect_google(self):
        job = self.queue(key="scope-revoked")
        calls = []

        def sitemaps(**_kwargs):
            ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(
                state=ProjectOriginVerification.State.REVOKED, revoked_at=timezone.now())
            return self.sitemaps()

        def inspect(**_kwargs):
            calls.append("unexpected")
            return self.inspection()

        self.assertTrue(self.execute(job, sitemaps=sitemaps, inspection=inspect))
        job.refresh_from_db()
        self.grant.refresh_from_db()
        self.assertEqual((job.status, job.usage.actual_units, job.error_category),
                         (JobStatus.CANCELLED, 2, "source_revoked"))
        self.assertEqual(self.grant.state, GoogleOAuthGrant.State.ACTIVE)
        self.assertFalse(SearchConsoleCoverageObservation.objects.filter(job=job).exists())
        self.assertFalse(calls)

    def test_stale_uncertain_sitemap_request_is_never_replayed(self):
        job = self.queue(key="lost-worker")

        def lost(**_kwargs):
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            self.execute(job, sitemaps=lost)
        JobRun.objects.filter(pk=job.pk).update(updated_at=timezone.now() - timedelta(minutes=4))
        with patch("jobs.tasks.collect_search_console_coverage_task.apply_async") as republish:
            self.assertEqual(reconcile_stuck_search_console_coverage(), 1)
            republish.assert_called_once_with(args=[job.pk], queue="default", task_id=f"job-{job.pk}", retry=False)
        called = []
        self.assertTrue(self.execute(job, sitemaps=lambda **_kw: called.append("replayed")))
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category, job.usage.actual_units),
                         (JobStatus.FAILED, "request_outcome_unknown", 2))
        self.assertFalse(called)
        self.assertEqual(JobStep.objects.filter(job=job).count(), 2)

    def test_foreign_user_project_and_unconfigured_capability_fail_before_queue(self):
        with self.assertRaises(PermissionDenied):
            self.queue(key="foreign-actor", user=self.foreign_user)
        sibling = Project.objects.create(organization=self.organization, name="Sibling",
                                         canonical_origin="https://sibling.example")
        with self.assertRaises(IntegrationConnection.DoesNotExist):
            self.queue(key="foreign-project", project=sibling)
        self.connection.capabilities = ["api_sync", "page_metrics"]
        self.connection.save()
        with self.assertRaises(ValidationError):
            self.queue(key="unsupported")
        self.assertFalse(JobRun.objects.exists())
