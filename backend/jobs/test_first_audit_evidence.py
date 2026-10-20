"""Actual marked API→existing injected worker, never real remote/customer observations."""
import hashlib
import json
from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.cache import cache
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from config.artifacts import ArtifactNotFound
from config.test_foundations import TEST_STORAGES
from tenancy.artifacts import read_project_artifact
from tenancy.models import Organization, OrganizationMembership, Project, ProjectConfiguration
from tenancy.services import update_project_configuration
from .crawler import execute_crawl_job, queue_crawl
from .first_audit_evidence import first_audit_completion_source
from .models import Artifact, CrawlPageSnapshot, CrawlRun, FirstBoundedAuditCompletion, JobRun, JobStatus, JobStep, UsageReservation
from .test_crawler import FakeFetcher, response


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "text/html", "text/plain"}),
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "audit-evidence"}})
class FirstAuditEvidenceTests(TransactionTestCase):
    def setUp(self):
        from .test_first_audit import FirstAuditTests
        FirstAuditTests.setUp(self)
        cache.clear()
        self.client.force_login(self.owner)

    def crawl(self, key, *, body=b"<title>Synthetic audit body</title>", status=200, robots_status=200, marked=True):
        with patch("jobs.services.dispatch_pending"):
            if marked:
                requested = self.client.post(self.path, json.dumps({"page_limit": 1, "idempotency_key": key}),
                                             content_type="application/json")
                self.assertEqual(requested.status_code, 202, requested.content)
                job = JobRun.objects.get(pk=requested.json()["job"]["id"])
            else:
                job = queue_crawl(project=self.project, actor=self.owner, seeds=[], page_limit=1, idempotency_key=key)
        root = self.project.canonical_origin + "/"
        robots = self.project.canonical_origin + "/robots.txt"
        sitemap = self.project.canonical_origin + "/sitemap.xml"
        responses = {robots: [response(robots, status=robots_status, body=b"User-agent: *\nAllow: /\n")],
                     sitemap: [response(sitemap, status=404)],
                     root: [response(root, status=status, body=body, headers={"content-type": "text/html"})]}
        self.assertTrue(execute_crawl_job(job.pk, fetcher_factory=lambda scope: FakeFetcher(scope, responses),
                                        sleep=lambda _seconds: None))
        job.refresh_from_db()
        return job

    def source(self, job, **changes):
        return first_audit_completion_source(**{"project": self.project, "actor": self.owner, "job_id": job.pk, **changes})

    def test_actual_worker_private_body_original_dates_read_only_and_not_first_value(self):
        job = self.crawl("actual-marked-audit")
        self.assertEqual(job.status, JobStatus.SUCCEEDED)
        page = job.crawl_run.pages.get()

        def read_only(execute, sql, params, many, context):
            self.assertEqual(sql.lstrip().split()[0].upper(), "SELECT", sql)
            return execute(sql, params, many, context)

        with connection.execute_wrapper(read_only), patch("socket.getaddrinfo", side_effect=AssertionError("network")), \
            patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("site fetch")):
            source = self.source(job)
            self.assertEqual(source, self.source(job))
        self.assertEqual(source["actor_id"], self.owner.pk)
        self.assertEqual(source["run_completed_at"], job.crawl_run.completed_at.isoformat())
        self.assertEqual(source["job_updated_at"], job.updated_at.isoformat())
        self.assertEqual(source["pages"][0]["observed_at"], page.observed_at.isoformat())
        self.assertEqual(source["successful_html"][0]["sha256"], hashlib.sha256(b"<title>Synthetic audit body</title>").hexdigest())
        self.assertEqual(source["actual_units"], 1)
        self.assertEqual(source["first_ever_completion"], "not_established")
        self.assertEqual(source["first_value"], "not_established")
        self.assertEqual(source["discovery"]["sitemaps_fetched"], 1)
        self.assertEqual(source["discovery"]["sitemap_failures"], 0)
        self.assertNotIn("key", source["successful_html"][0])
        self.assertNotIn("Synthetic audit body", json.dumps(source))
        # Read permission is independent from the original actor's current launch authority.
        self.assertEqual(self.source(job, actor=self.viewer), source)
        from tenancy.acquisition import acquisition_milestones
        self.assertEqual(acquisition_milestones()["milestones"]["first_audit_succeeded"], {"count": 0, "grain": "organization", "state": "derivable"})

    def test_real_ordinary_partial_failed_and_http_failure_jobs_are_ineligible(self):
        ordinary = self.crawl("ordinary-audit-source", marked=False)
        partial = self.crawl("partial-audit-source", body=b'<a href="/next">Synthetic pending page</a>')
        failed = self.crawl("failed-audit-source", robots_status=503)
        missing = self.crawl("missing-audit-source", status=404)
        self.assertEqual(partial.status, JobStatus.PARTIALLY_SUCCEEDED)
        self.assertEqual(failed.status, JobStatus.FAILED)
        for job in (ordinary, partial, failed, missing):
            with self.subTest(job=job.pk), self.assertRaises((PermissionDenied, ValidationError)):
                self.source(job)

    def test_actual_conditional_reuse_does_not_supply_same_job_successful_html(self):
        self.crawl("original-audit-source")
        reused = self.crawl("reused-audit-source", status=304, body=b"")
        self.assertEqual(reused.status, JobStatus.SUCCEEDED)
        self.assertIsNotNone(reused.crawl_run.pages.get().reused_from_id)
        with self.assertRaises(ValidationError):
            self.source(reused)

    def test_foreign_invalid_original_actor_current_mode_and_origin_deny_before_private_read(self):
        job = self.crawl("scoped-audit-source")
        other = Project.objects.create(organization=self.org, name="Other fixture",
                                       canonical_origin="https://other-audit.example.invalid")
        with patch("jobs.first_audit_evidence.read_project_artifact", side_effect=AssertionError("private read")):
            for value in (True, 0, -1, "1", 2**53):
                with self.subTest(value=value), self.assertRaises(ValidationError):
                    self.source(job, job_id=value)
            for changes in ({"actor": self.foreign}, {"project": other}, {"job_id": job.pk + 9999}):
                with self.subTest(changes=changes), self.assertRaises(PermissionDenied):
                    self.source(job, **changes)
            OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role="viewer")
            with self.assertRaises(PermissionDenied):
                self.source(job, actor=self.viewer)
            OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role="owner")
            config = update_project_configuration(project=self.project, user=self.owner, expected_revision=0,
                                                  changes={"source_choice": "synthetic_demo"})
            with self.assertRaises(ValidationError):
                self.source(job)
            ProjectConfiguration.objects.filter(pk=config.pk).update(source_choice="skip")
            Project.objects.filter(pk=self.project.pk).update(canonical_origin="https://changed-audit.example.invalid")
            with self.assertRaises(ValidationError):
                self.source(job)  # Cached project cannot authorize old origin.

    def test_body_missing_tamper_scope_usage_steps_counts_and_dates_are_not_evidence(self):
        job = self.crawl("integrity-audit-source")
        page = job.crawl_run.pages.get()
        with patch("jobs.first_audit_evidence.read_project_artifact", return_value=b"different body"):
            with self.assertRaises(ValidationError):
                self.source(job)
        with patch("jobs.first_audit_evidence.read_project_artifact", side_effect=ArtifactNotFound):
            with self.assertRaises(ValidationError):
                self.source(job)
        mutations = [
            (CrawlRun, job.crawl_run.pk, {"completed_at": None}),
            (CrawlRun, job.crawl_run.pk, {"pages_observed": 0}),
            (JobRun, job.pk, {"updated_at": timezone.now() + timedelta(days=1)}),
            (JobStep, job.steps.get(sequence=2).pk, {"status": "failed"}),
            (UsageReservation, job.usage.pk, {"actual_units": 2}),
            (CrawlPageSnapshot, page.pk, {"content_hash": "f" * 64}),
            (CrawlPageSnapshot, page.pk, {"final_url": "http://first-audit.example.invalid/"}),
            (CrawlPageSnapshot, page.pk, {"observed_at": job.created_at - timedelta(seconds=1)}),
            (Artifact, page.raw_artifact_id, {"key": "organizations/999/projects/999/jobs/999/" + "a" * 32 + ".html"}),
        ]
        # Deliberate SQL tamper bypasses immutable model saves to exercise read-side integrity.
        for model, pk, fields in mutations:
            with self.subTest(model=model.__name__, fields=fields):
                rows = model.objects.filter(pk=pk)
                original = rows.values(*fields).get()
                rows.update(**fields)
                with self.assertRaises((PermissionDenied, ValidationError)):
                    self.source(job)
                rows.update(**original)
        ordinary = self.crawl("foreign-artifact-job", marked=False)
        Artifact.objects.filter(pk=page.raw_artifact_id).update(job_id=ordinary.pk)
        with self.assertRaises(ValidationError):
            self.source(job)

    def test_fresh_authority_and_exact_source_rechecked_after_private_body_read(self):
        job = self.crawl("mid-read-audit-source")
        config = update_project_configuration(project=self.project, user=self.owner, expected_revision=0,
                                              changes={"source_choice": "skip"})
        mutations = [
            (OrganizationMembership.objects.filter(organization=self.org, user=self.owner), {"role": "viewer"}),
            (OrganizationMembership.objects.filter(pk=OrganizationMembership.objects.get(
                organization=self.org, user=self.viewer).pk), {"user_id": self.foreign.pk}),
            (ProjectConfiguration.objects.filter(pk=config.pk), {"source_choice": "synthetic_demo"}),
            (Project.objects.filter(pk=self.project.pk), {"canonical_origin": "https://moved-audit.example.invalid"}),
            (Artifact.objects.filter(pk=job.crawl_run.pages.get().raw_artifact_id), {"size_bytes": 1}),
            (JobStep.objects.filter(job=job, sequence=2), {"status": "failed"}),
        ]
        for rows, fields in mutations:
            original = rows.values(*fields).get()
            def change_after_read(**kwargs):
                body = read_project_artifact(**kwargs)
                rows.update(**fields)
                return body
            with self.subTest(fields=fields), patch("jobs.first_audit_evidence.read_project_artifact", side_effect=change_after_read):
                with self.assertRaises((PermissionDenied, ValidationError)):
                    self.source(job, actor=self.viewer)
            rows.update(**original)


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "text/html", "text/plain"}),
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "audit-completion"}})
class FirstAuditCompletionTests(TransactionTestCase):
    setUp = FirstAuditEvidenceTests.setUp
    crawl = FirstAuditEvidenceTests.crawl

    def test_actual_original_completion_is_atomic_immutable_once_per_org_and_not_a_metric(self):
        from .first_audit_evidence import COMPLETION_METHOD, completion_source_digest
        job = self.crawl("atomic-first-completion")
        saved = FirstBoundedAuditCompletion.objects.get(organization=self.org)
        self.assertEqual(saved.job_id, job.pk)
        self.assertEqual(saved.project_id, self.project.pk)
        self.assertEqual(saved.observed_at, job.crawl_run.completed_at)
        self.assertEqual(saved.source["method"], COMPLETION_METHOD)
        self.assertEqual(saved.source["tracking_started_at"], self.org.created_at.isoformat())
        self.assertEqual(saved.source["evidence"]["actor_id"], self.owner.pk)
        self.assertEqual(saved.source_digest, completion_source_digest(saved.source))
        with self.assertRaises(ValidationError):
            saved.save()
        self.assertFalse(execute_crawl_job(job.pk, fetcher_factory=lambda _scope: self.fail("redelivery fetch")))
        later = self.crawl("later-completion")
        self.assertEqual(later.status, JobStatus.SUCCEEDED)
        self.assertEqual(FirstBoundedAuditCompletion.objects.get().source, saved.source)
        from tenancy.acquisition import acquisition_milestones
        self.assertEqual(acquisition_milestones()["milestones"]["first_audit_succeeded"], {"count": 0, "grain": "organization", "state": "derivable"})

    def test_old_null_and_manager_birth_cannot_be_backfilled(self):
        legacy = Organization.objects.create(name="Synthetic untracked manager birth")
        self.assertIsNone(legacy.first_audit_tracking)
        legacy.first_audit_tracking = "bounded-first-audit-completion-v1"
        with self.assertRaises(ValidationError):
            legacy.save()
        Organization.objects.filter(pk=self.org.pk).update(first_audit_tracking=None)
        self.crawl("old-null-completion")
        self.assertFalse(FirstBoundedAuditCompletion.objects.exists())
        self.assertIsNone(Organization.objects.get(pk=self.org.pk).first_audit_tracking)

    def test_genuine_old_worker_success_gap_never_reconstructed(self):
        with patch("jobs.first_audit_evidence.capture_bounded_completion"):
            old = self.crawl("old-worker-completion")
        self.assertEqual(old.status, JobStatus.SUCCEEDED)
        self.assertFalse(FirstBoundedAuditCompletion.objects.exists())
        from .first_audit_evidence import bounded_completion_capture_source
        with self.assertRaises(ValidationError):
            bounded_completion_capture_source(job=JobRun.objects.get(pk=old.pk))
        self.crawl("new-worker-after-gap")
        self.assertFalse(FirstBoundedAuditCompletion.objects.exists())

    def test_original_actor_loss_during_private_capture_never_creates_later_history(self):
        def revoke_after_read(**kwargs):
            body = read_project_artifact(**kwargs)
            OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role="viewer")
            return body
        with patch("jobs.first_audit_evidence.read_project_artifact", side_effect=revoke_after_read):
            job = self.crawl("lost-capture-authority")
        self.assertEqual(job.status, JobStatus.SUCCEEDED)
        self.assertFalse(FirstBoundedAuditCompletion.objects.exists())
        self.assertIsNone(Organization.objects.get(pk=self.org.pk).first_audit_tracking)
        OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role="owner")
        self.crawl("authority-restored-after-gap")
        self.assertFalse(FirstBoundedAuditCompletion.objects.exists())
        self.assertIsNone(Organization.objects.get(pk=self.org.pk).first_audit_tracking)

    def test_success_without_accepted_html_proof_invalidates_uncaptured_coverage(self):
        missing = self.crawl("no-html-completion", status=404)
        self.assertEqual(missing.status, JobStatus.SUCCEEDED)
        self.assertIsNone(Organization.objects.get(pk=self.org.pk).first_audit_tracking)
        self.crawl("html-after-gap")
        self.assertFalse(FirstBoundedAuditCompletion.objects.exists())

    def test_failed_partial_ordinary_work_does_not_consume_first_bounded_completion(self):
        self.crawl("ordinary-completion", marked=False)
        self.crawl("partial-before-completion", body=b'<a href="/next">Pending</a>')
        self.crawl("failed-before-completion", robots_status=503)
        first = self.crawl("successful-after-failure")
        self.assertEqual(FirstBoundedAuditCompletion.objects.get().job_id, first.pk)

    def test_capture_failure_rolls_back_original_success_usage_then_real_retry_can_capture(self):
        def fail_capture(**kwargs):
            job = kwargs["job"]
            self.assertEqual(JobRun.objects.get(pk=job.pk).status, JobStatus.SUCCEEDED)
            self.assertEqual(job.usage.state, "settled")
            raise RuntimeError("synthetic crash in original finalization")
        with patch("jobs.first_audit_evidence.FirstBoundedAuditCompletion.objects.create", side_effect=fail_capture):
            failed = self.crawl("rollback-completion")
        self.assertEqual(failed.status, JobStatus.PARTIALLY_SUCCEEDED)
        self.assertEqual(failed.error_category, "handler_failed")
        self.assertFalse(FirstBoundedAuditCompletion.objects.exists())
        self.assertIsNotNone(Organization.objects.get(pk=self.org.pk).first_audit_tracking)
        from .services import retry_job
        with patch("jobs.services.dispatch_pending"):
            retried = retry_job(job=failed, actor=self.owner, idempotency_key="genuine-completion-retry")
        root = self.project.canonical_origin + "/"
        responses = {self.project.canonical_origin + "/robots.txt": [response(self.project.canonical_origin + "/robots.txt", status=404)],
            self.project.canonical_origin + "/sitemap.xml": [response(self.project.canonical_origin + "/sitemap.xml", status=404)],
            root: [response(root, body=b"<title>Retry evidence</title>", headers={"content-type": "text/html"})]}
        self.assertTrue(execute_crawl_job(retried.pk, fetcher_factory=lambda scope: FakeFetcher(scope, responses),
                                        sleep=lambda _seconds: None))
        saved = FirstBoundedAuditCompletion.objects.get()
        self.assertEqual(saved.job_id, retried.pk)
        self.assertEqual(saved.source["evidence"]["retry_of_id"], failed.pk)
        self.assertEqual(UsageReservation.objects.get(job=failed).actual_units, 1)
        self.assertEqual(UsageReservation.objects.get(job=retried).actual_units, 1)

    def test_actual_customer_export_closure_and_deletion_remove_completion_not_restricted_history(self):
        from django.test import RequestFactory
        from tenancy.customer_inventory import CUSTOMER, RESTRICTED, require_complete_ownership_map
        from tenancy.customer_export import project_customer_rows
        from tenancy.closure import close_organization_locally
        from tenancy.deletion import (_customer_deletion_order, prepare_customer_data_deletion,
                                     sweep_customer_artifact_versions, delete_customer_database_records)
        saved_job = self.crawl("lifecycle-completion")
        label = "jobs.FirstBoundedAuditCompletion"
        self.assertEqual(CUSTOMER[label], "organization_id")
        self.assertNotIn(label, RESTRICTED)
        require_complete_ownership_map()
        order = [model._meta.label for model, _lookup in _customer_deletion_order()]
        self.assertLess(order.index(label), order.index("jobs.JobRun"))
        exported = project_customer_rows(organization=self.org, actor=self.owner, model_label=label,
            after_id=0, through_id=FirstBoundedAuditCompletion.objects.get().pk)
        self.assertEqual(exported["rows"][0]["job_id"], saved_job.pk)
        request = RequestFactory().post("/synthetic-close/"); request.user = self.owner
        with patch("tenancy.services.did_recently_authenticate", return_value=True):
            close_organization_locally(organization=self.org, actor=self.owner, request=request)
        self.assertEqual(FirstBoundedAuditCompletion.objects.count(), 1)
        run = prepare_customer_data_deletion(organization=self.org)
        run = sweep_customer_artifact_versions(run=run)
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(FirstBoundedAuditCompletion.objects.exists())
        self.assertTrue(Organization.objects.filter(pk=self.org.pk).exists())

    def test_historical_readback_is_minimized_read_only_and_independent_of_original_actor_current_role(self):
        from .first_audit_evidence import inspect_bounded_completion
        job = self.crawl("historical-readback")
        def read_only(execute, sql, params, many, context):
            self.assertEqual(sql.lstrip().split()[0].upper(), "SELECT", sql)
            return execute(sql, params, many, context)
        with connection.execute_wrapper(read_only), patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("site fetch")):
            history = inspect_bounded_completion(project=self.project, actor=self.viewer)
            self.assertEqual(history, inspect_bounded_completion(project=self.project, actor=self.viewer))
        self.assertEqual(history["state"], "recorded")
        self.assertEqual(history["observed_at"], job.crawl_run.completed_at.isoformat())
        self.assertEqual(history["pages_observed"], 1)
        self.assertNotIn("https://", json.dumps(history))
        self.assertNotIn("Synthetic audit body", json.dumps(history))
        OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role="viewer")
        self.assertEqual(inspect_bounded_completion(project=self.project, actor=self.viewer), history)
        with self.assertRaises(PermissionDenied):
            first_audit_completion_source(project=self.project, actor=self.viewer, job_id=job.pk)
        other = Project.objects.create(organization=self.org, name="Different historical scope",
                                       canonical_origin="https://other-history.example.invalid")
        other_history = inspect_bounded_completion(project=other, actor=self.viewer)
        self.assertEqual(other_history["state"], "not_observed_for_project")
        self.assertNotIn("job_id", other_history)
        with self.assertRaises(PermissionDenied):
            inspect_bounded_completion(project=self.project, actor=self.foreign)

    def test_historical_private_body_and_saved_source_tamper_and_final_current_reader_loss_deny(self):
        from .first_audit_evidence import inspect_bounded_completion, completion_source_digest
        self.crawl("historical-integrity")
        saved = FirstBoundedAuditCompletion.objects.get()
        with patch("jobs.first_audit_evidence.read_project_artifact", return_value=b"changed body"):
            with self.assertRaises(ValidationError):
                inspect_bounded_completion(project=self.project, actor=self.viewer)
        changed = {**saved.source, "evidence": {**saved.source["evidence"], "project_id": self.project.pk + 1}}
        FirstBoundedAuditCompletion.objects.filter(pk=saved.pk).update(source=changed, source_digest=completion_source_digest(changed))
        with self.assertRaises(ValidationError):
            inspect_bounded_completion(project=self.project, actor=self.viewer)
        FirstBoundedAuditCompletion.objects.filter(pk=saved.pk).update(source=saved.source, source_digest=saved.source_digest)
        def remove_reader(**kwargs):
            body = read_project_artifact(**kwargs)
            OrganizationMembership.objects.filter(organization=self.org, user=self.viewer).update(user_id=self.foreign.pk)
            return body
        with patch("jobs.first_audit_evidence.read_project_artifact", side_effect=remove_reader), self.assertRaises(PermissionDenied):
            inspect_bounded_completion(project=self.project, actor=self.viewer)


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "text/html", "text/plain"}))
class FirstAuditCompletionRaceTests(TransactionTestCase):
    def test_two_actual_marked_workers_capture_once_under_organization_serialization(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import close_old_connections
        from .first_audit import queue_first_audit
        from .test_crawler import CrawlerConcurrencyTests
        CrawlerConcurrencyTests.setUp(self)
        with patch("jobs.services.dispatch_pending"):
            jobs = [queue_first_audit(project=self.project, actor=self.owner, page_limit=1,
                                      idempotency_key=f"racing-first-completion-{index}") for index in (1, 2)]
        barrier = Barrier(2)
        root = self.project.canonical_origin + "/"
        def factory(scope):
            def page():
                barrier.wait(timeout=15)
                return response(root, body=b"<title>Concurrent completion</title>", headers={"content-type": "text/html"})
            return FakeFetcher(scope, {self.project.canonical_origin + "/robots.txt": [response(
                self.project.canonical_origin + "/robots.txt", status=404)],
                self.project.canonical_origin + "/sitemap.xml": [response(self.project.canonical_origin + "/sitemap.xml", status=404)],
                root: [page]})
        def worker(job):
            close_old_connections()
            try:
                return execute_crawl_job(job.pk, fetcher_factory=factory, sleep=lambda _seconds: None)
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(worker, jobs)), [True, True])
        completed = list(JobRun.objects.filter(pk__in=[job.pk for job in jobs]))
        self.assertTrue(all(job.status == JobStatus.SUCCEEDED for job in completed))
        saved = FirstBoundedAuditCompletion.objects.get(organization=self.organization)
        self.assertEqual(saved.observed_at, min(job.crawl_run.completed_at for job in completed))
        self.assertEqual(UsageReservation.objects.filter(job__in=completed, state="settled", actual_units=1).count(), 2)


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "text/html", "text/plain"}),
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "audit-history-api"}})
class FirstAuditCompletionApiTests(TransactionTestCase):
    setUp = FirstAuditEvidenceTests.setUp
    crawl = FirstAuditEvidenceTests.crawl

    def test_actual_saved_worker_history_is_private_read_only_minimized_and_exact_project(self):
        from .first_audit_evidence import inspect_bounded_completion
        job = self.crawl("private-history-api")
        path = self.path + "completion/"
        self.client.force_login(self.viewer)
        def read_only(execute, sql, params, many, context):
            self.assertEqual(sql.lstrip().split()[0].upper(), "SELECT", sql)
            return execute(sql, params, many, context)
        with connection.execute_wrapper(read_only), patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("site fetch")):
            result = self.client.get(path)
            self.assertEqual(result.status_code, 200, result.content)
            self.assertEqual(result.json(), inspect_bounded_completion(project=self.project, actor=self.viewer))
        self.assertEqual(result.json()["job_id"], job.pk)
        self.assertEqual(result["Cache-Control"], "private, no-store")
        self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")
        self.assertNotIn("https://", result.content.decode())
        self.assertNotIn("Synthetic audit body", result.content.decode())
        other = Project.objects.create(organization=self.org, name="Other private history",
            canonical_origin="https://other-private-history.example.invalid")
        different = self.client.get(path.replace(f"projects/{self.project.pk}/", f"projects/{other.pk}/"))
        self.assertEqual(different.json()["state"], "not_observed_for_project")
        self.assertNotIn("job_id", different.json())
        self.client.force_login(self.foreign)
        self.assertEqual(self.client.get(path).status_code, 404)
        self.client.logout()
        anonymous = self.client.get(path)
        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(anonymous["Cache-Control"], "private, no-store")

    def test_strict_get_unknown_demo_and_real_read_throttle(self):
        path = self.path + "completion/"
        self.assertEqual(self.client.get(path).json()["state"], "not_observed_for_project")
        Organization.objects.filter(pk=self.org.pk).update(first_audit_tracking=None)
        self.assertEqual(self.client.get(path).json()["state"], "unknown")
        for method in ("post", "put", "patch", "delete", "head", "options"):
            result = getattr(self.client, method)(path)
            self.assertEqual(result.status_code, 405)
            self.assertEqual(result["Allow"], "GET")
            self.assertEqual(result["Cache-Control"], "private, no-store")
        for suffix in ("?job_id=1", "?job_id=1&job_id=2", "?capture=true"):
            self.assertEqual(self.client.get(path + suffix).status_code, 400)
        self.assertEqual(self.client.generic("GET", path, data=b"{}", content_type="application/json").status_code, 400)
        self.assertEqual(self.client.get(path.replace(f"projects/{self.project.pk}", f"projects/{2**53}")).status_code, 400)
        configuration = update_project_configuration(project=self.project, user=self.owner, expected_revision=0,
            changes={"source_choice": "synthetic_demo"})
        self.assertEqual(self.client.get(path).status_code, 409)
        ProjectConfiguration.objects.filter(pk=configuration.pk).update(source_choice="skip")
        cache.clear()
        for _ in range(30):
            self.assertEqual(self.client.get(path).status_code, 200)
        limited = self.client.get(path)
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited["Cache-Control"], "private, no-store")
        self.assertFalse(FirstBoundedAuditCompletion.objects.exists())
        self.assertFalse(JobRun.objects.exists())

    def test_saved_source_loss_and_final_reader_or_demo_loss_never_deliver_history(self):
        job = self.crawl("private-history-loss")
        path = self.path + "completion/"
        self.client.force_login(self.viewer)
        with patch("jobs.first_audit_evidence.read_project_artifact", side_effect=ArtifactNotFound):
            result = self.client.get(path)
            self.assertEqual(result.status_code, 409)
            self.assertEqual(result.json(), {"message": "Saved bounded completion needs review."})
        configuration = update_project_configuration(project=self.project, user=self.owner, expected_revision=0,
            changes={"source_choice": "skip"})
        def switch_demo(**kwargs):
            body = read_project_artifact(**kwargs)
            ProjectConfiguration.objects.filter(pk=configuration.pk).update(source_choice="synthetic_demo")
            return body
        with patch("jobs.first_audit_evidence.read_project_artifact", side_effect=switch_demo):
            self.assertEqual(self.client.get(path).status_code, 409)
        ProjectConfiguration.objects.filter(pk=configuration.pk).update(source_choice="skip")
        def revoke_reader(**kwargs):
            body = read_project_artifact(**kwargs)
            OrganizationMembership.objects.filter(organization=self.org, user=self.viewer).delete()
            return body
        with patch("jobs.first_audit_evidence.read_project_artifact", side_effect=revoke_reader):
            self.assertEqual(self.client.get(path).status_code, 403)
        self.client.force_login(self.owner)
        CrawlPageSnapshot.objects.filter(crawl_run__job=job).delete()
        CrawlRun.objects.filter(job=job).delete()
        self.assertEqual(self.client.get(path).status_code, 409)
