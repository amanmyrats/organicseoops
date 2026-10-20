import json
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
from tenancy.email_feedback import record_ses_feedback
from tenancy.models import Organization, OrganizationMembership, OrganizationTrial, Project
from . import alert_delivery_source, test_crawler as fixtures
from .alert_delivery_source import current_daily_crawl_alert_source
from .alert_preferences import set_project_alert_preference
from .crawler import execute_crawl_job
from .models import JobRun, JobSchedule, JobStatus, ProjectAlertPreference
from .services import cancel_job, retry_job


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True)
class DailyCrawlAlertSourceTests(TransactionTestCase):
    def setUp(self):
        self.assessed = timezone.now()
        self.day_end = self.assessed.replace(hour=0, minute=0, second=0, microsecond=0)
        self.day_start = self.day_end - timedelta(days=1)
        self.intent_time = self.day_start - timedelta(hours=1)
        with patch("django.utils.timezone.now", return_value=self.intent_time - timedelta(hours=1)):
            fixtures.CrawlerTests.setUp(self)

    def enable(self, families=None):
        with patch("django.utils.timezone.now", return_value=self.intent_time):
            return set_project_alert_preference(project=self.project, actor=self.owner, frequency="daily",
                source_families=families or ["crawl_failure"], expected_revision=0)

    def failed(self, key="daily-failure", *, created=None, updated=None):
        with patch("jobs.crawler.timezone.now", return_value=created or self.day_start):
            job = fixtures.CrawlerTests.queue(self, key=key, page_limit=1)
        def fail(_scope):
            raise OSError("private fixture provider/customer payload")
        with patch("jobs.crawler.timezone.now", return_value=updated or self.day_start + timedelta(hours=1)):
            self.assertTrue(execute_crawl_job(job.pk, fetcher_factory=fail, sleep=lambda _: None))
        job.refresh_from_db(); self.assertEqual(job.status, JobStatus.FAILED)
        return job

    def inspect(self, project=None):
        with patch("jobs.alert_delivery_source.timezone.now", return_value=self.assessed):
            return current_daily_crawl_alert_source(project=project or self.project, recipient=self.owner)

    def test_default_and_other_family_do_not_read_jobs_then_genuine_source_is_minimized_read_only(self):
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(self.inspect()["state"], "unavailable_crawl_alert_intent")
        self.assertFalse(any('"jobs_jobrun"' in q["sql"] for q in queries))
        self.enable(["integration_health"])
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(self.inspect()["state"], "unavailable_crawl_alert_intent")
        self.assertFalse(any('"jobs_jobrun"' in q["sql"] for q in queries))
        with patch("django.utils.timezone.now", return_value=self.intent_time):
            set_project_alert_preference(project=self.project, actor=self.owner, frequency="daily",
                source_families=["crawl_failure", "integration_health"], expected_revision=1)
        self.assertEqual(self.inspect()["state"], "unavailable_no_failure_candidates")
        job = self.failed()
        with CaptureQueriesContext(connection) as queries, patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("django.core.mail.send_mail", side_effect=AssertionError("SMTP")), \
                patch("jobs.tasks.execute_crawl_job_task.apply_async", side_effect=AssertionError("dispatch")):
            result = self.inspect()
        self.assertFalse(any(q["sql"].lstrip().split()[0] in {"INSERT", "UPDATE", "DELETE"} for q in queries))
        self.assertEqual(result["state"], "available_failure_candidates_not_sent")
        self.assertEqual(result["preference_revision"], 2)
        self.assertEqual(result["intent_updated_at"], self.intent_time.isoformat())
        self.assertEqual((result["day_start"], result["day_end"]), (self.day_start.isoformat(), self.day_end.isoformat()))
        self.assertEqual(result["rows"], [{"job_id": job.pk, "source_method": "crawl-http-v2",
            "created_at": job.created_at.isoformat(), "status_updated_at": job.updated_at.isoformat(), "failure_category": "handler_failed"}])
        for private in (self.owner.email, "provider/customer", self.project.canonical_origin, "primary_address", "user_id"):
            self.assertNotIn(private, json.dumps(result))

    def test_genuine_half_open_day_and_saved_intent_boundaries_no_backlog_or_foreign_source(self):
        self.enable()
        before_day = self.failed("before-day", created=self.intent_time, updated=self.day_start - timedelta(microseconds=1))
        start = self.failed("at-start", created=self.intent_time, updated=self.day_start)
        near_end = self.failed("near-end", updated=self.day_end - timedelta(microseconds=1))
        at_end = self.failed("at-end", updated=self.day_end)
        before_intent = self.failed("before-intent", created=self.intent_time - timedelta(microseconds=1))
        self.assertEqual([row["job_id"] for row in self.inspect()["rows"]], [near_end.pk, start.pk])
        foreign = Project.objects.create(organization=self.organization, name="Foreign fixture",
                                        canonical_origin="https://foreign-alert.example.invalid")
        self.assertEqual(self.inspect(project=foreign)["state"], "unavailable_crawl_alert_intent")
        # Explicit corruption/state negatives only; positives above are real queued worker failures.
        for fields in ({"status": JobStatus.SUCCEEDED}, {"status": JobStatus.PARTIALLY_SUCCEEDED},
                       {"method_version": "unsupported-fixture"}, {"handler": "diagnostic_probe"},
                       {"project": foreign}):
            with transaction.atomic():
                JobRun.objects.filter(pk__in=[start.pk, near_end.pk]).update(**fields)
                self.assertEqual(self.inspect()["state"], "unavailable_no_failure_candidates")
                transaction.set_rollback(True)
        self.assertFalse({before_day.pk, at_end.pk, before_intent.pk} & {row["job_id"] for row in self.inspect()["rows"]})

    def test_actual_retry_lineage_suppresses_root_and_retry_not_another_candidate(self):
        self.enable(); job = self.failed()
        with patch("jobs.tasks.execute_crawl_job_task.apply_async"), \
                patch("jobs.crawler.timezone.now", return_value=self.day_start + timedelta(hours=2)):
            retried = retry_job(job=job, actor=self.owner, idempotency_key="daily-retry")
        self.assertEqual(retried.retry_of_id, job.pk)
        def fail(_scope): raise OSError("private fixture retry error")
        with patch("jobs.crawler.timezone.now", return_value=self.day_start + timedelta(hours=3)):
            self.assertTrue(execute_crawl_job(retried.pk, fetcher_factory=fail, sleep=lambda _: None))
        retried.refresh_from_db(); self.assertEqual(retried.status, JobStatus.FAILED)
        self.assertEqual(self.inspect()["state"], "unavailable_no_failure_candidates")
        with patch("jobs.crawler.timezone.now", return_value=self.day_start):
            cancelled = fixtures.CrawlerTests.queue(self, key="daily-cancel", page_limit=1)
            cancel_job(job=cancelled, actor=self.owner)
        self.assertEqual(self.inspect()["rows"], [])

    def test_final_preference_primary_suppression_reader_expiry_or_source_loss_denies(self):
        self.enable(); job = self.failed()
        trial = OrganizationTrial.objects.get(organization=self.organization)
        original = alert_delivery_source._row
        def off_on():
            set_project_alert_preference(project=self.project, actor=self.owner, frequency="off",
                source_families=["crawl_failure"], expected_revision=1)
            set_project_alert_preference(project=self.project, actor=self.owner, frequency="daily",
                source_families=["crawl_failure"], expected_revision=2)
        def change_primary():
            EmailAddress.objects.filter(user=self.owner).update(primary=False)
            get_user_model().objects.filter(pk=self.owner.pk).update(email="new-alert@example.invalid")
            EmailAddress.objects.create(user=self.owner, email="new-alert@example.invalid", primary=True, verified=True)
        changes = [off_on, change_primary,
            lambda: ProjectAlertPreference.objects.filter(user=self.owner).update(crawl_failure=False, integration_health=True, revision=2),
            lambda: record_ses_feedback(("daily-alert-complaint-001", "complaint", (self.owner.email,))),
            lambda: EmailAddress.objects.filter(user=self.owner).update(verified=False),
            lambda: OrganizationMembership.objects.filter(user=self.owner, organization=self.organization).delete(),
            lambda: get_user_model().objects.filter(pk=self.owner.pk).update(is_active=False),
            lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True),
            lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=self.assessed),
            lambda: OrganizationTrial.objects.filter(pk=trial.pk).update(ends_at=trial.started_at + timedelta(microseconds=1)),
            lambda: JobRun.objects.filter(pk=job.pk).update(error_category="crawl_deadline"),
            lambda: JobRun.objects.filter(pk=job.pk).update(status=JobStatus.SUCCEEDED)]
        for change in changes:
            with self.subTest(change=change), transaction.atomic():
                def project_then_change(row, assessed):
                    result = original(row, assessed); change(); return result
                with patch("jobs.alert_delivery_source._row", side_effect=project_then_change), \
                        self.assertRaises((PermissionDenied, ValidationError)):
                    self.inspect()
                transaction.set_rollback(True)

    def test_initial_and_natural_exact_expiry_deny_with_fresh_clock(self):
        self.enable(); self.failed()
        trial = OrganizationTrial.objects.get(organization=self.organization)
        expired = False
        original = alert_delivery_source._row
        def project_then_delay(row, assessed):
            nonlocal expired
            result = original(row, assessed); expired = True; return result
        def clock(): return trial.ends_at if expired else trial.ends_at - timedelta(microseconds=1)
        # Shift the genuine original job+intent dates into the day before the real trial end;
        # only clock/record dates are fixtures, not fabricated successful worker results.
        end = trial.ends_at.replace(hour=0, minute=0, second=0, microsecond=0)
        JobRun.objects.filter(project=self.project).update(created_at=end - timedelta(hours=23), updated_at=end - timedelta(hours=22))
        ProjectAlertPreference.objects.filter(user=self.owner).update(updated_at=end - timedelta(hours=24))
        with patch("jobs.alert_delivery_source.timezone.now", side_effect=clock), \
                patch("jobs.alert_delivery_source._row", side_effect=project_then_delay), self.assertRaises(ValidationError):
            current_daily_crawl_alert_source(project=self.project, recipient=self.owner)
        self.assertTrue(expired)
        with patch("jobs.alert_delivery_source.timezone.now", return_value=trial.ends_at), self.assertRaises(ValidationError):
            current_daily_crawl_alert_source(project=self.project, recipient=self.owner)

    def test_explicit_synthetic_cap_order_and_unclassified_category_only(self):
        self.enable()
        jobs = JobRun.objects.bulk_create([JobRun(organization=self.organization, project=self.project, actor=self.owner,
            handler="crawl_site", method_version="crawl-http-v2", status=JobStatus.FAILED,
            error_category="private provider error") for _ in range(21)])
        JobRun.objects.filter(pk__in=[job.pk for job in jobs]).update(created_at=self.day_start, updated_at=self.day_start + timedelta(hours=1))
        result = self.inspect(); self.assertTrue(result["has_more"])
        self.assertEqual([row["job_id"] for row in result["rows"]], sorted([job.pk for job in jobs], reverse=True)[:20])
        self.assertEqual({row["failure_category"] for row in result["rows"]}, {"unclassified_failure"})
        self.assertNotIn("private provider error", json.dumps(result))
        schedule = JobSchedule.objects.create(organization=self.organization, project=self.project,
            actor=self.owner, handler="crawl_site")
        # Synthetic schedule-binding negative only, not a claimed scheduled crawl producer.
        JobRun.objects.filter(pk=jobs[-1].pk).update(schedule=schedule, scheduled_for=self.day_start)
        self.assertFalse(self.inspect()["has_more"])
        self.assertEqual(len(self.inspect()["rows"]), 20)
        ProjectAlertPreference.objects.filter(user=self.owner).update(updated_at=self.assessed + timedelta(microseconds=1))
        with self.assertRaises(ValidationError): self.inspect()
