import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import close_old_connections, connection, IntegrityError, transaction
from django.test import RequestFactory, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.artifacts import read_project_artifact
from tenancy.email_feedback import record_ses_feedback
from tenancy.models import Organization, OrganizationMembership, OrganizationTrial, Project
from tenancy.services import create_organization, create_project
from . import test_weekly_summary as fixtures
from .models import ProjectReportSnapshot, ProjectSummaryDelivery, ProjectSummaryPreference
from .summary_delivery import deliver_weekly_summary, recover_weekly_summaries, reserve_weekly_summary
from .summary_preferences import set_project_summary_preference


@override_settings(STORAGES=TEST_STORAGES, WEEKLY_SUMMARY_DELIVERY_ENABLED=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/csv", "application/json"}),
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "weekly-delivery"}})
class WeeklyDeliveryTests(TransactionTestCase):
    create_report = fixtures.WeeklyReportSourceTests.create_report

    def setUp(self):
        fixtures.WeeklyReportSourceTests.setUp(self)
        self.org = self.project.organization
        set_project_summary_preference(project=self.project, actor=self.owner, frequency="weekly", expected_revision=0)

    def reserve(self):
        return reserve_weekly_summary(project=self.project, recipient=self.owner)

    def parallel(self, function):
        barrier = Barrier(2)
        def run():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return function()
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = [pool.submit(run) for _ in range(2)]
            return [item.result(timeout=30) for item in pending]

    def test_rollout_off_no_private_io_reservation_mail_or_intent_change(self):
        with override_settings(WEEKLY_SUMMARY_DELIVERY_ENABLED=False), \
                patch("jobs.summary_delivery.current_weekly_delivery_source", side_effect=AssertionError("private I/O")), \
                patch("jobs.summary_delivery.send_mail", side_effect=AssertionError("SMTP")):
            self.assertIsNone(self.reserve())
            self.assertEqual(deliver_weekly_summary(999), "disabled")
            self.assertEqual(recover_weekly_summaries(), [])
        self.assertEqual(ProjectSummaryDelivery.objects.count(), 0)
        self.assertEqual(ProjectSummaryPreference.objects.get().frequency, "weekly")

    @override_settings(DEBUG=True)
    def test_current_recipient_gets_private_turkish_draft_without_changing_source_or_replay(self):
        row_id = self.reserve()
        row = ProjectSummaryDelivery.objects.get(pk=row_id)
        original_source = (row.source_metadata, row.source_fingerprint)
        # Preference changes after queue reservation are read from the locked recipient at send time.
        get_user_model().objects.filter(pk=self.owner.pk).update(product_language="tr")
        with patch("jobs.summary_delivery.send_mail", return_value=1) as smtp, \
                patch("socket.create_connection", side_effect=AssertionError("network")):
            self.assertEqual(deliver_weekly_summary(row_id), "sent")
            self.assertEqual(deliver_weekly_summary(row_id), "sent")
        smtp.assert_called_once()
        subject, body, sender, addresses = smtp.call_args.args
        self.assertEqual(addresses, [self.owner.email])
        self.assertIn("Türkçe taslak", subject)
        for text in ('İsteğe bağlı haftalık rapor özeti', 'seçilmiş bulgu', 'tam sağlayıcı kapsamı', 'yeni analiz çalıştırılmadı'):
            self.assertIn(text, subject + body)
        self.assertIn(f"/app/reports/{self.project.organization_id}/{self.project.pk}", body)
        for private in (self.report.artifact_key, self.finding.subject, self.action.acceptance_criteria, "/shared/"):
            self.assertNotIn(private, subject + body)
        row.refresh_from_db()
        self.assertEqual((row.source_metadata, row.source_fingerprint), original_source)

    @override_settings(DEBUG=False)
    def test_genuine_concurrent_reservation_sql_dedupe_and_concurrent_transport_acceptance(self):
        get_user_model().objects.filter(pk=self.owner.pk).update(product_language="tr")
        identities = self.parallel(self.reserve)
        self.assertEqual(identities[0], identities[1])
        row = ProjectSummaryDelivery.objects.get()
        self.assertEqual(row.week_start, (self.week_end - timedelta(days=7)).date())
        self.assertEqual(row.report_id, self.report.pk)
        self.assertEqual(row.preference_revision, 1)
        serialized = json.dumps(row.source_metadata)
        for private in (self.owner.email, self.report.artifact_key, self.finding.subject, self.action.acceptance_criteria, '"rows"'):
            self.assertNotIn(private, serialized)
        with transaction.atomic(), self.assertRaises(IntegrityError):
            ProjectSummaryDelivery.objects.create(project=self.project, recipient=self.owner, preference=row.preference,
                preference_revision=3, primary_address_id=row.primary_address_id, report=row.report,
                week_start=row.week_start, source_metadata=row.source_metadata, source_fingerprint=row.source_fingerprint)
        for change in ({"state": "invalid"}, {"preference_revision": 0}, {"state": "sent"}):
            with transaction.atomic(), self.assertRaises(IntegrityError):
                ProjectSummaryDelivery.objects.filter(pk=row.pk).update(**change)
        def accepted(subject, body, sender, addresses, **kwargs):
            self.assertEqual(addresses, [self.owner.email])
            self.assertEqual(ProjectSummaryDelivery.objects.get(pk=row.pk).state, "sending")
            self.assertIn(f"/app/reports/{self.org.pk}/{self.project.pk}", body)
            self.assertIn("not complete provider coverage", body)
            self.assertIn("No new analysis", body)
            for private in (self.report.artifact_key, self.finding.subject, self.action.acceptance_criteria, "/shared/"):
                self.assertNotIn(private, subject + body)
            return 1
        with patch("jobs.summary_delivery.send_mail", side_effect=accepted) as smtp, \
                patch("socket.create_connection", side_effect=AssertionError("network")):
            states = self.parallel(lambda: deliver_weekly_summary(row.pk))
            self.assertIn("sent", states)
            self.assertLessEqual(set(states), {"sent", "sending"})
        self.assertEqual(smtp.call_count, 1)
        row.refresh_from_db(); self.assertIsNotNone(row.sent_at)
        self.assertEqual(recover_weekly_summaries(), [])
        # New report and off/on intent cannot create another delivery for the original week.
        with patch("jobs.weekly_summary.timezone.now", return_value=self.report_time + timedelta(hours=1)):
            self.create_report("weekly-new-after-send-001")
        set_project_summary_preference(project=self.project, actor=self.owner, frequency="off", expected_revision=1)
        set_project_summary_preference(project=self.project, actor=self.owner, frequency="weekly", expected_revision=2)
        self.assertEqual(self.reserve(), row.pk)
        self.assertEqual(ProjectSummaryDelivery.objects.count(), 1)
        self.assertEqual(ProjectSummaryDelivery.objects.get().preference_revision, 1)

    def test_smtp_uncertainty_and_post_send_process_crash_never_replay_committed_claim(self):
        row_id = self.reserve()
        with transaction.atomic(), patch("jobs.summary_delivery.send_mail", side_effect=AssertionError("SMTP")):
            with self.assertRaises(RuntimeError): deliver_weekly_summary(row_id)
        self.assertEqual(ProjectSummaryDelivery.objects.get().state, "queued")
        # Even a rollback after SMTP does not restore queued. Another DB connection sees committed sending.
        def send_then_crash(*args, **kwargs):
            with ThreadPoolExecutor(max_workers=1) as pool:
                def observed():
                    close_old_connections()
                    try: return ProjectSummaryDelivery.objects.get(pk=row_id).state
                    finally: connection.close()
                self.assertEqual(pool.submit(observed).result(timeout=10), "sending")
            raise SystemExit("synthetic worker termination after transport attempt")
        with patch("jobs.summary_delivery.send_mail", side_effect=send_then_crash) as smtp:
            with self.assertRaises(SystemExit): deliver_weekly_summary(row_id)
            self.assertEqual(smtp.call_count, 1)
        self.assertEqual(ProjectSummaryDelivery.objects.get().state, "sending")
        with patch("jobs.summary_delivery.timezone.now", return_value=timezone.now() + timedelta(minutes=3)):
            self.assertEqual(recover_weekly_summaries(), [])
        self.assertEqual(ProjectSummaryDelivery.objects.get().state, "unknown")
        with patch("jobs.summary_delivery.send_mail", side_effect=AssertionError("replay")):
            self.assertEqual(deliver_weekly_summary(row_id), "unknown")
            self.assertEqual(recover_weekly_summaries(), [])
            self.assertEqual(self.reserve(), row_id)

    def test_zero_and_exception_are_unknown_without_exception_text_or_automatic_replay(self):
        for outcome in (0, OSError("synthetic private provider error")):
            with self.subTest(outcome=type(outcome)):
                row_id = self.reserve()
                with patch("jobs.summary_delivery.send_mail", side_effect=outcome if isinstance(outcome, Exception) else None,
                           return_value=outcome) as smtp:
                    self.assertEqual(deliver_weekly_summary(row_id), "unknown")
                    self.assertEqual(deliver_weekly_summary(row_id), "unknown")
                    self.assertEqual(smtp.call_count, 1)
                row = ProjectSummaryDelivery.objects.get()
                self.assertEqual(row.error_category, "delivery_uncertain")
                self.assertIsNone(row.sent_at)
                ProjectSummaryDelivery.objects.all().delete()  # Separate synthetic transport case only.

    def test_original_source_preference_primary_and_current_authority_loss_skip_without_replay(self):
        def off_on():
            set_project_summary_preference(project=self.project, actor=self.owner, frequency="off", expected_revision=1)
            set_project_summary_preference(project=self.project, actor=self.owner, frequency="weekly", expected_revision=2)
        def primary():
            EmailAddress.objects.filter(user=self.owner).update(primary=False)
            get_user_model().objects.filter(pk=self.owner.pk).update(email="new-weekly@example.invalid")
            EmailAddress.objects.create(user=self.owner, email="new-weekly@example.invalid", verified=True, primary=True)
        changes = (off_on, primary,
            lambda: EmailAddress.objects.filter(user=self.owner).update(verified=False),
            lambda: record_ses_feedback(("weekly-kernel-complaint-001", "complaint", (self.owner.email,))),
            lambda: OrganizationMembership.objects.filter(user=self.owner, organization=self.org).delete(),
            lambda: Organization.objects.filter(pk=self.org.pk).update(is_suspended=True),
            lambda: Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now()),
            lambda: OrganizationTrial.objects.filter(organization=self.org).update(
                ends_at=OrganizationTrial.objects.get(organization=self.org).started_at + timedelta(microseconds=1)),
            lambda: ProjectReportSnapshot.objects.filter(pk=self.report.pk).update(content_sha256="0" * 64),
            lambda: ProjectReportSnapshot.objects.filter(pk=self.report.pk).update(created_at=self.report_time + timedelta(seconds=1)))
        # Apply loss after the second source read (sending already durably committed).
        from .summary_delivery import _message
        for index, change in enumerate(changes):
            def message_then_change(*args):
                result = _message(*args); change(); return result
            row_id = self.reserve()
            with self.subTest(change_index=index), patch("jobs.summary_delivery._message", side_effect=message_then_change), \
                    patch("jobs.summary_delivery.send_mail", side_effect=AssertionError("SMTP")):
                self.assertEqual(deliver_weekly_summary(row_id), "skipped")
            self.assertEqual(ProjectSummaryDelivery.objects.get().state, "skipped")
            # Restore fixture authority/source between independently committed negative cases.
            self._fixture_teardown(); self._fixture_setup(); self.setUp()

    def test_reservation_mid_io_and_after_insert_loss_roll_back_and_later_week_never_backlogs(self):
        def revoke(**kwargs):
            data = read_project_artifact(**kwargs)
            EmailAddress.objects.filter(user=self.owner).update(verified=False)
            return data
        with transaction.atomic():
            with patch("jobs.reporting.read_project_artifact", side_effect=revoke), self.assertRaises(PermissionDenied):
                self.reserve()
            self.assertFalse(ProjectSummaryDelivery.objects.exists())
            transaction.set_rollback(True)
        save = ProjectSummaryDelivery.save
        def insert_then_revoke(row, *args, **kwargs):
            save(row, *args, **kwargs)
            ProjectSummaryPreference.objects.filter(user=self.owner).update(frequency="off", revision=2)
        with patch.object(ProjectSummaryDelivery, "save", insert_then_revoke), \
                self.assertRaises(PermissionDenied): self.reserve()
        self.assertFalse(ProjectSummaryDelivery.objects.exists())
        self.assertEqual(ProjectSummaryPreference.objects.get().frequency, "weekly")
        row_id = self.reserve()
        with patch("jobs.summary_delivery.timezone.now", return_value=self.week_end + timedelta(days=7)), \
                patch("jobs.summary_delivery.send_mail", side_effect=AssertionError("old week replay")):
            self.assertEqual(deliver_weekly_summary(row_id), "skipped")
            self.assertIsNone(self.reserve())

    def test_actual_scoped_customer_export_child_first_erasure_and_personal_close(self):
        from accounts.closure import close_personal_access
        from tenancy.customer_inventory import require_complete_ownership_map
        from tenancy.customer_export import project_customer_rows
        from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        row_id = self.reserve()
        other_org = create_organization(user=self.other, name="Other delivery org")
        other_project = create_project(organization=other_org, user=self.other, name="Other delivery site",
                                      canonical_origin="https://other-weekly.example.invalid")
        # Genuine second recipient in the same original project; no fabricated delivery source.
        OrganizationMembership.objects.create(organization=self.org, user=self.other, role="viewer")
        set_project_summary_preference(project=self.project, actor=self.other, frequency="weekly", expected_revision=0)
        other_id = reserve_weekly_summary(project=self.project, recipient=self.other)
        require_complete_ownership_map()
        exported = project_customer_rows(organization=self.org, actor=self.owner, model_label="jobs.ProjectSummaryDelivery",
                                        after_id=0, through_id=other_id)
        self.assertEqual({row["recipient_id"] for row in exported["rows"]}, {self.owner.pk, self.other.pk})
        self.assertNotIn(self.owner.email, json.dumps(exported, cls=DjangoJSONEncoder))
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
        request = RequestFactory().post("/api/account/close/"); request.user = self.owner
        with transaction.atomic():
            with patch("tenancy.services.did_recently_authenticate", return_value=True):
                close_personal_access(actor=self.owner, request=request)
            self.assertFalse(ProjectSummaryDelivery.objects.filter(pk=row_id).exists())
            self.assertTrue(ProjectSummaryDelivery.objects.filter(pk=other_id).exists())
            self.assertFalse(ProjectSummaryPreference.objects.filter(user=self.owner).exists())
            transaction.set_rollback(True)
        self.assertTrue(ProjectSummaryDelivery.objects.filter(pk=row_id).exists())
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.org))
        delete_customer_database_records(run=run)
        self.assertFalse(ProjectSummaryDelivery.objects.filter(project_id=self.project.pk).exists())
        self.assertTrue(Project.objects.filter(pk=other_project.pk).exists())
