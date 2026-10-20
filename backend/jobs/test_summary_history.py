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
from tenancy.models import Organization, OrganizationMembership, OrganizationTrial
from tenancy.services import create_organization, create_project
from . import test_summary_delivery as fixtures
from .models import ProjectSummaryDelivery
from .summary_delivery import deliver_weekly_summary, reserve_weekly_summary
from .summary_history import own_weekly_delivery_history, _row
from .summary_preferences import set_project_summary_preference


@override_settings(STORAGES=TEST_STORAGES, WEEKLY_SUMMARY_DELIVERY_ENABLED=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/csv", "application/json"}),
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "weekly-history"}})
class WeeklyHistoryTests(TransactionTestCase):
    create_report = fixtures.WeeklyDeliveryTests.create_report

    def setUp(self):
        fixtures.WeeklyDeliveryTests.setUp(self)

    def history(self, **changes):
        return own_weekly_delivery_history(**{**dict(project=self.project, actor=self.owner), **changes})

    def test_genuine_own_reservation_history_is_minimized_read_only_separate_from_other_recipients_and_eligibility(self):
        self.assertEqual(self.history()["rows"], [])
        row_id = reserve_weekly_summary(project=self.project, recipient=self.owner)
        OrganizationMembership.objects.create(organization=self.org, user=self.other, role="viewer")
        set_project_summary_preference(project=self.project, actor=self.other, frequency="weekly", expected_revision=0)
        other_id = reserve_weekly_summary(project=self.project, recipient=self.other)
        with CaptureQueriesContext(connection) as queries, patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("jobs.summary_delivery.send_mail", side_effect=AssertionError("SMTP")):
            result = self.history()
        self.assertFalse(any(query["sql"].lstrip().split()[0] in {"INSERT", "UPDATE", "DELETE"} for query in queries))
        self.assertEqual([row["id"] for row in result["rows"]], [row_id])
        self.assertEqual([row["id"] for row in self.history(actor=self.other)["rows"]], [other_id])
        self.assertEqual(result["rows"][0]["state"], "queued")
        serialized = json.dumps(result)
        for private in (self.owner.email, self.report.artifact_key, self.finding.subject, self.action.acceptance_criteria,
                        "recipient_id", "report_id", "preference_revision", "source_metadata", "source_fingerprint"):
            self.assertNotIn(private, serialized)
        EmailAddress.objects.filter(user=self.owner).update(verified=False)
        trial = OrganizationTrial.objects.get(organization=self.org)
        OrganizationTrial.objects.filter(pk=trial.pk).update(ends_at=trial.started_at + timedelta(microseconds=1))
        with override_settings(WEEKLY_SUMMARY_DELIVERY_ENABLED=False):
            self.assertEqual(self.history(), result)  # Retained diagnostic reading is not fresh email eligibility.
        foreign_org = create_organization(user=self.other, name="Foreign history")
        foreign = create_project(organization=foreign_org, user=self.other, name="Foreign history site",
                                 canonical_origin="https://foreign-history.example.invalid")
        with self.assertRaises(PermissionDenied): self.history(project=foreign)
        self.assertEqual(self.history(project=foreign, actor=self.other)["rows"], [])

    def test_actual_transport_accepted_and_uncertain_are_not_recipient_delivery_read_or_retry_authority(self):
        row_id = reserve_weekly_summary(project=self.project, recipient=self.owner)
        with patch("jobs.summary_delivery.send_mail", return_value=1):
            self.assertEqual(deliver_weekly_summary(row_id), "sent")
        row = self.history()["rows"][0]
        self.assertEqual(row["state"], "transport_accepted")
        self.assertIsNotNone(row["accepted_at"])
        self.assertIn("not_recipient_delivery_read_or_current_eligibility", self.history()["scope"])
        # A separate genuine recipient can have an uncertain transport without a resend action.
        OrganizationMembership.objects.create(organization=self.org, user=self.other, role="viewer")
        set_project_summary_preference(project=self.project, actor=self.other, frequency="weekly", expected_revision=0)
        other_id = reserve_weekly_summary(project=self.project, recipient=self.other)
        with patch("jobs.summary_delivery.send_mail", side_effect=OSError("private synthetic SMTP error")):
            self.assertEqual(deliver_weekly_summary(other_id), "unknown")
        row = self.history(actor=self.other)["rows"][0]
        self.assertEqual((row["state"], row["error_category"], row["accepted_at"]), ("unknown", "delivery_uncertain", None))
        self.assertNotIn("retry", row)
        ProjectSummaryDelivery.objects.filter(pk=other_id).update(error_category="private SMTP exception body")
        with self.assertRaises(ValidationError): self.history(actor=self.other)

    def test_final_current_reader_and_suspension_loss_denies_projected_own_history(self):
        reserve_weekly_summary(project=self.project, recipient=self.owner)
        for change in (lambda: OrganizationMembership.objects.filter(user=self.owner, organization=self.org).delete(),
                       lambda: get_user_model().objects.filter(pk=self.owner.pk).update(is_active=False),
                       lambda: Organization.objects.filter(pk=self.org.pk).update(is_suspended=True),
                       lambda: Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())):
            def project_then_change(row):
                result = _row(row); change(); return result
            with self.subTest(change=change), transaction.atomic():
                with patch("jobs.summary_history._row", side_effect=project_then_change), self.assertRaises(PermissionDenied):
                    self.history()
                transaction.set_rollback(True)

    def test_explicit_synthetic_historical_rows_only_bound_newest_twenty_not_source_or_delivery_claims(self):
        reserve_weekly_summary(project=self.project, recipient=self.owner)
        original = ProjectSummaryDelivery.objects.get()
        for index in range(1, 21):
            # Index/cap fixture only: these rows do not authorize/replay historical SMTP or certify report sources.
            ProjectSummaryDelivery.objects.create(project=self.project, recipient=self.owner, preference=original.preference,
                preference_revision=original.preference_revision, primary_address_id=original.primary_address_id,
                report=original.report, week_start=original.week_start - timedelta(days=7 * index),
                source_metadata=original.source_metadata, source_fingerprint=original.source_fingerprint)
        result = self.history()
        self.assertTrue(result["has_more"])
        self.assertEqual(len(result["rows"]), 20)
        self.assertEqual(result["rows"][0]["id"], original.pk)
        self.assertEqual([row["week_start"] for row in result["rows"]],
                         [(original.week_start - timedelta(days=7 * index)).isoformat() for index in range(20)])
        with transaction.atomic():
            ProjectSummaryDelivery.objects.filter(pk=original.pk).update(week_start=original.week_start + timedelta(days=1))
            with self.assertRaises(ValidationError): self.history()
            transaction.set_rollback(True)
