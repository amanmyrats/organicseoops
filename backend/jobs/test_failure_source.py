from datetime import timedelta
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import Organization, OrganizationMembership, OrganizationTrial, Project
from tenancy.services import create_organization
from . import failure_source, test_crawler as fixtures
from .crawler import execute_crawl_job
from .failure_source import retained_crawl_failures
from .models import JobRun, JobStatus
from .services import cancel_job, create_job


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True)
class RetainedCrawlFailureTests(TransactionTestCase):
    def setUp(self):
        fixtures.CrawlerTests.setUp(self)

    def queue(self, key="failure", page_limit=1):
        return fixtures.CrawlerTests.queue(self, key=key, page_limit=page_limit)

    def failed(self, key="failure"):
        job = self.queue(key)
        def fail(_scope):
            raise OSError("synthetic secret provider/customer payload")
        self.assertTrue(execute_crawl_job(job.pk, fetcher_factory=fail, sleep=lambda _: None))
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category), (JobStatus.FAILED, "handler_failed"))
        return job

    def inspect(self, project=None, actor=None):
        return retained_crawl_failures(project=project or self.project, actor=actor or self.owner)

    def test_actual_worker_failure_is_minimized_and_not_success_cancel_partial_or_debug_failure(self):
        self.assertEqual(self.inspect()["rows"], [])
        failed = self.failed()
        success = self.queue("success")
        root = self.project.canonical_origin + "/"
        def factory(scope):
            return fixtures.FakeFetcher(scope, {
                root + "robots.txt": [fixtures.response(root + "robots.txt", status=404)],
                root + "sitemap.xml": [fixtures.response(root + "sitemap.xml", status=404)],
                root: [fixtures.response(root, body=b"<title>synthetic fixture</title>", headers={"content-type": "text/html"})],
            })
        self.assertTrue(execute_crawl_job(success.pk, fetcher_factory=factory, sleep=lambda _: None))
        success.refresh_from_db(); self.assertEqual(success.status, JobStatus.SUCCEEDED)
        cancelled = self.queue("cancel"); cancel_job(job=cancelled, actor=self.owner)
        self.assertFalse(execute_crawl_job(cancelled.pk, fetcher_factory=lambda _: self.fail("cancelled fetch")))
        debug = create_job(project=self.project, actor=self.owner, handler="diagnostic_probe",
            input_snapshot={"sample": "private fixture", "simulate_partial": False})
        # Explicit synthetic negative retained states only; positive source above uses the real worker.
        JobRun.objects.filter(pk=debug.pk).update(status=JobStatus.FAILED, error_category="handler_failed")
        partial = self.queue("partial-negative")
        JobRun.objects.filter(pk=partial.pk).update(status=JobStatus.PARTIALLY_SUCCEEDED)
        with CaptureQueriesContext(connection) as queries, \
                patch("jobs.crawler.SafeFetcher.__init__", side_effect=AssertionError("network")), \
                patch("jobs.summary_delivery.send_mail", side_effect=AssertionError("SMTP")), \
                patch("jobs.tasks.execute_crawl_job_task.apply_async", side_effect=AssertionError("dispatch")):
            result = self.inspect()
        self.assertFalse(any(q["sql"].lstrip().split()[0] in {"INSERT", "UPDATE", "DELETE"} for q in queries))
        self.assertEqual(result["rows"], [{"job_id": failed.pk, "source_method": "crawl-http-v2",
            "created_at": failed.created_at.isoformat(), "status_updated_at": failed.updated_at.isoformat(),
            "failure_category": "handler_failed"}])
        self.assertFalse(result["has_more"])
        self.assertEqual(result["scope"], failure_source.SCOPE)
        self.assertNotIn("secret", str(result)); self.assertNotIn(root, str(result))
        for category in ("crawl_deadline", "robots_unavailable", "crawl_incomplete", "", "private free error text"):
            JobRun.objects.filter(pk=failed.pk).update(error_category=category)
            self.assertEqual(self.inspect()["rows"][0]["failure_category"],
                category if category in failure_source._CATEGORIES else "unclassified_failure")

    def test_foreign_project_and_original_actor_loss_do_not_grant_or_erase_current_reader_history(self):
        failed = self.failed()
        other = Project.objects.create(organization=self.organization, name="Other crawl source",
            canonical_origin="https://other-crawl-source.example.invalid")
        self.assertEqual(self.inspect(project=other)["rows"], [])
        reader = get_user_model().objects.create_user("failure-reader@example.invalid", "test-password")
        OrganizationMembership.objects.create(organization=self.organization, user=reader, role="viewer")
        OrganizationTrial.objects.filter(organization=self.organization).update(state="expired")
        EmailAddress.objects.filter(user=self.owner).update(verified=False)
        OrganizationMembership.objects.filter(user=self.owner).delete()
        self.assertEqual(self.inspect(actor=reader)["rows"][0]["job_id"], failed.pk)
        with self.assertRaises(PermissionDenied): self.inspect()
        Project.objects.filter(pk=self.project.pk).update(access_restricted=True)
        with self.assertRaises(PermissionDenied): self.inspect(actor=reader)

    def test_final_source_or_reader_mutation_and_invalid_dates_deny_without_stale_rows(self):
        failed = self.failed()
        original = failure_source._row
        changes = [lambda: JobRun.objects.filter(pk=failed.pk).update(error_category="crawl_deadline"),
                   lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True),
                   lambda: get_user_model().objects.filter(pk=self.owner.pk).update(is_active=False),
                   lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=timezone.now()),
                   lambda: OrganizationMembership.objects.filter(user=self.owner).delete()]
        for change in changes:
            with transaction.atomic():
                def project_then_change(row, assessed):
                    result = original(row, assessed); change(); return result
                with patch("jobs.failure_source._row", side_effect=project_then_change), \
                        self.assertRaises((PermissionDenied, ValidationError)):
                    self.inspect()
                transaction.set_rollback(True)
        JobRun.objects.filter(pk=failed.pk).update(created_at=failed.updated_at + timedelta(microseconds=1))
        with self.assertRaises(ValidationError): self.inspect()

    def test_explicit_synthetic_retained_cap_tied_order_and_method_scope_fences(self):
        # Synthetic metadata only for bounds/order; never presented as real crawl collection.
        now = timezone.now()
        jobs = JobRun.objects.bulk_create([JobRun(organization=self.organization, project=self.project, actor=self.owner,
            handler="crawl_site", method_version="crawl-http-v2", status=JobStatus.FAILED, error_category="crawl_incomplete")
            for _ in range(21)])
        JobRun.objects.filter(pk__in=[job.pk for job in jobs]).update(updated_at=now + timedelta(seconds=1))
        with patch("jobs.failure_source.timezone.now", return_value=now + timedelta(seconds=2)):
            result = self.inspect()
        self.assertTrue(result["has_more"])
        self.assertEqual([row["job_id"] for row in result["rows"]], sorted([job.pk for job in jobs], reverse=True)[:20])
        JobRun.objects.filter(pk=jobs[-1].pk).update(method_version="unsupported-fixture")
        with patch("jobs.failure_source.timezone.now", return_value=now + timedelta(seconds=2)):
            self.assertFalse(self.inspect()["has_more"])
        # Corrupt legacy cross-organization binding is not a project-owned failure source.
        other_org = create_organization(user=self.owner, name="Other failure organization")
        JobRun.objects.filter(pk=jobs[-2].pk).update(organization=other_org)
        with patch("jobs.failure_source.timezone.now", return_value=now + timedelta(seconds=2)):
            self.assertEqual(len(self.inspect()["rows"]), 19)
