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
from tenancy.artifacts import read_project_artifact
from tenancy.email_feedback import record_ses_feedback
from tenancy.models import Organization, OrganizationMembership, OrganizationTrial
from . import test_weekly_summary as source_fixtures
from .models import ProjectReportSnapshot, ProjectSummaryPreference
from .summary_delivery_source import current_weekly_delivery_source
from .summary_preferences import set_project_summary_preference


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/csv", "application/json"}),
                   CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "delivery-source"}})
class WeeklyDeliverySourceTests(TransactionTestCase):
    create_report = source_fixtures.WeeklyReportSourceTests.create_report

    def setUp(self):
        source_fixtures.WeeklyReportSourceTests.setUp(self)

    def enable(self):
        return set_project_summary_preference(project=self.project, actor=self.owner, frequency="weekly", expected_revision=0)

    def inspect(self):
        with patch("jobs.weekly_summary.timezone.now", return_value=self.assessed):
            return current_weekly_delivery_source(project=self.project, recipient=self.owner)

    def test_default_off_avoids_storage_and_genuine_enabled_source_is_read_only_minimized_not_sent(self):
        with patch("jobs.summary_delivery_source.retained_weekly_report_source", side_effect=AssertionError("private I/O")):
            self.assertEqual(self.inspect()["state"], "unavailable_preference_off")
        self.enable()
        with CaptureQueriesContext(connection) as queries, patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("django.core.mail.send_mail", side_effect=AssertionError("mail")):
            result = self.inspect()
        self.assertFalse(any(query["sql"].lstrip().split()[0] in {"INSERT", "UPDATE", "DELETE"} for query in queries))
        self.assertEqual(result["state"], "eligible_current_source_not_sent")
        self.assertEqual(result["preference_revision"], 1)
        self.assertEqual(result["source"]["report_id"], self.report.pk)
        self.assertNotIn(self.owner.email, json.dumps(result))
        self.assertNotIn(self.report.artifact_key, json.dumps(result))
        self.assertNotIn(self.finding.subject, json.dumps(result))
        ProjectReportSnapshot.objects.filter(pk=self.report.pk).delete()
        result = self.inspect()
        self.assertEqual(result["state"], "unavailable_no_report")
        self.assertIsNone(result["source"]["source_counts"])

    def test_initial_suppression_verification_and_expiry_deny_before_private_read(self):
        self.enable()
        trial = OrganizationTrial.objects.get(organization=self.project.organization)
        for change in (lambda: record_ses_feedback(("weekly-bounce-fixture-001", "permanent_bounce", (self.owner.email,))),
                       lambda: EmailAddress.objects.filter(user=self.owner).update(verified=False),
                       lambda: OrganizationTrial.objects.filter(pk=trial.pk).update(ends_at=trial.started_at + timedelta(microseconds=1))):
            with transaction.atomic():
                change()
                with patch("jobs.summary_delivery_source.retained_weekly_report_source", side_effect=AssertionError("private I/O")), \
                        self.assertRaises((PermissionDenied, ValidationError)):
                    self.inspect()
                transaction.set_rollback(True)

    def test_current_preference_primary_suppression_entitlement_and_source_loss_during_io_deny(self):
        self.enable()
        trial = OrganizationTrial.objects.get(organization=self.project.organization)
        def change_primary():
            EmailAddress.objects.filter(user=self.owner).update(primary=False)
            get_user_model().objects.filter(pk=self.owner.pk).update(email="new-weekly@example.invalid")
            EmailAddress.objects.create(user=self.owner, email="new-weekly@example.invalid", primary=True, verified=True)
        def off_then_on():
            set_project_summary_preference(project=self.project, actor=self.owner, frequency="off", expected_revision=1)
            set_project_summary_preference(project=self.project, actor=self.owner, frequency="weekly", expected_revision=2)
        changes = (lambda: ProjectSummaryPreference.objects.filter(user=self.owner).update(frequency="off", revision=2),
                   off_then_on, change_primary,
                   lambda: record_ses_feedback(("weekly-complaint-fixture-001", "complaint", (self.owner.email,))),
                   lambda: EmailAddress.objects.filter(user=self.owner).update(verified=False),
                   lambda: OrganizationMembership.objects.filter(user=self.owner, organization=self.project.organization).delete(),
                   lambda: Organization.objects.filter(pk=self.project.organization_id).update(is_suspended=True),
                   lambda: Organization.objects.filter(pk=self.project.organization_id).update(is_suspended=True, closed_at=self.assessed),
                   lambda: OrganizationTrial.objects.filter(pk=trial.pk).update(ends_at=trial.started_at + timedelta(microseconds=1)),
                   lambda: ProjectReportSnapshot.objects.filter(pk=self.report.pk).update(content_sha256="0" * 64))
        for change in changes:
            def read_then_change(**kwargs):
                data = read_project_artifact(**kwargs)
                change()
                return data
            with self.subTest(change=change), transaction.atomic():
                with patch("jobs.reporting.read_project_artifact", side_effect=read_then_change), \
                        self.assertRaises((PermissionDenied, ValidationError)):
                    self.inspect()
                transaction.set_rollback(True)

    def test_natural_entitlement_expiry_uses_fresh_delivery_clock_after_source_io(self):
        self.enable()
        trial = OrganizationTrial.objects.get(organization=self.project.organization)
        ended = False
        def slow_read(**kwargs):
            nonlocal ended
            data = read_project_artifact(**kwargs)
            ended = True
            return data
        def clock():
            return trial.ends_at if ended else trial.ends_at - timedelta(microseconds=1)
        from datetime import timezone as utc
        assessment = (trial.ends_at - timedelta(microseconds=1)).astimezone(utc.utc)
        end = assessment.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=assessment.weekday())
        with patch("jobs.weekly_summary.timezone.now", return_value=end - timedelta(days=2)):
            self.create_report("weekly-expiry-report-001")
        with patch("jobs.weekly_summary.timezone.now", side_effect=clock), patch("jobs.reporting.read_project_artifact", side_effect=slow_read):
            with self.assertRaises(ValidationError):
                current_weekly_delivery_source(project=self.project, recipient=self.owner)
        self.assertTrue(ended)
