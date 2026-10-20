from tenancy.customer_artifact_barrier import project_artifact_barrier
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

from allauth.account.models import EmailAddress
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import close_old_connections, connection, IntegrityError, transaction
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from integrations.google_oauth import revoke_google_grant
from integrations.models import IntegrationConnection
from tenancy.email_feedback import record_ses_feedback
from tenancy.models import AuditEvent, Organization, OrganizationMembership, OrganizationTrial, Project
from tenancy.services import create_organization, create_project
from . import alert_digest_delivery as delivery
from . import test_alert_digest_source as fixtures, test_summary_delivery as weekly_fixtures
from .alert_preferences import set_project_alert_preference
from .models import JobRun, ProjectAlertDelivery, ProjectAlertEpisodeClaim, ProjectAlertPreference


@override_settings(STORAGES=TEST_STORAGES, ALERT_DIGEST_DELIVERY_ENABLED=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", GOOGLE_OAUTH_CLIENT_ID="fixture-client",
    GOOGLE_OAUTH_CLIENT_SECRET="fixture-secret", GOOGLE_OAUTH_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),))
class DailyDigestDeliveryTests(TransactionTestCase):
    captureOnCommitCallbacks = TestCase.captureOnCommitCallbacks
    parallel = weekly_fixtures.WeeklyDeliveryTests.parallel
    failed = fixtures.DailyDigestSourceTests.failed
    deny = fixtures.DailyDigestSourceTests.deny
    enable = fixtures.DailyDigestSourceTests.enable

    def setUp(self):
        fixtures.DailyDigestSourceTests.setUp(self)
        self.enable()
        self.job, self.audit = self.failed(), self.deny()

    def reserve(self):
        return delivery.reserve_daily_alert_digest(project=self.project, recipient=self.user)

    def test_default_off_does_not_reserve_or_send_or_change_intent(self):
        with override_settings(ALERT_DIGEST_DELIVERY_ENABLED=False), self.assertNumQueries(0), \
                patch("jobs.alert_digest_delivery.send_mail", side_effect=AssertionError("SMTP")):
            self.assertIsNone(self.reserve())
            self.assertEqual(delivery.deliver_daily_alert_digest(999), "disabled")
        with override_settings(ALERT_DIGEST_DELIVERY_ENABLED=False):
            self.assertEqual(delivery.recover_daily_alert_digests(), [])
        self.assertFalse(ProjectAlertDelivery.objects.exists())
        self.assertFalse(ProjectAlertEpisodeClaim.objects.exists())
        self.assertEqual(ProjectAlertPreference.objects.get().frequency, "daily")

    @override_settings(DEBUG=True)
    def test_current_recipient_gets_private_turkish_draft_without_changing_source_or_replay(self):
        row_id = self.reserve()
        row = ProjectAlertDelivery.objects.get(pk=row_id)
        original_source = (row.source_metadata, row.source_fingerprint)
        # Preference changes after queue reservation are read from the locked recipient at send time.
        get_user_model().objects.filter(pk=self.user.pk).update(product_language="tr")
        with patch("jobs.alert_digest_delivery.send_mail", return_value=1) as smtp, \
                patch("socket.create_connection", side_effect=AssertionError("network")):
            self.assertEqual(delivery.deliver_daily_alert_digest(row_id), "sent")
            self.assertEqual(delivery.deliver_daily_alert_digest(row_id), "sent")
        smtp.assert_called_once()
        subject, body, sender, addresses = smtp.call_args.args
        self.assertEqual(addresses, [self.user.email])
        self.assertIn("Türkçe taslak", subject)
        for text in ('İsteğe bağlı günlük işlem özeti', '2 işlem kaynak kaydı', 'değişmez olay zamanları değildir', 'yeni analiz çalıştırılmadı'):
            self.assertIn(text, subject + body)
        self.assertIn(f"/app/reports/{self.project.organization_id}/{self.project.pk}", body)
        for private in (self.project.canonical_origin, self.project.name, "fixture", "/shared/"):
            self.assertNotIn(private, subject + body)
        row.refresh_from_db()
        self.assertEqual((row.source_metadata, row.source_fingerprint), original_source)

    @override_settings(DEBUG=False)
    def test_genuine_concurrent_reservation_sql_claims_and_once_only_transport(self):
        get_user_model().objects.filter(pk=self.user.pk).update(product_language="tr")
        ids = self.parallel(self.reserve)
        self.assertEqual(ids[0], ids[1])
        row = ProjectAlertDelivery.objects.get()
        self.assertEqual(row.day_start, self.start.date())
        self.assertEqual(ProjectAlertEpisodeClaim.objects.count(), 2)
        self.assertEqual(row.source_metadata["claimed_episodes"],
                         [f"crawl:{self.job.pk}", f"reconnect:{self.grant.pk}:{self.grant.revision}"])
        for private in (self.user.email, self.project.canonical_origin, "fixture", "credential_reference", "encrypted"):
            self.assertNotIn(private, json.dumps(row.source_metadata))
        with transaction.atomic(), self.assertRaises(IntegrityError):
            ProjectAlertDelivery.objects.create(project=self.project, recipient=self.user, preference=row.preference,
                preference_revision=1, primary_address_id=row.primary_address_id, day_start=row.day_start,
                source_metadata=row.source_metadata, source_fingerprint=row.source_fingerprint)
        for fields in ({"state": "invalid"}, {"preference_revision": 0}, {"state": "sent"}):
            with transaction.atomic(), self.assertRaises(IntegrityError):
                ProjectAlertDelivery.objects.filter(pk=row.pk).update(**fields)
        for key in (row.source_metadata["claimed_episodes"][0], "private raw error", "crawl:0"):
            with transaction.atomic(), self.assertRaises(IntegrityError):
                ProjectAlertEpisodeClaim.objects.create(project=self.project, recipient=self.user, delivery=row, episode_key=key)
        def accepted(subject, body, sender, addresses, **kwargs):
            self.assertEqual(addresses, [self.user.email])
            self.assertEqual(ProjectAlertDelivery.objects.get(pk=row.pk).state, "sending")
            self.assertIn("selects 2 operational source records", body)
            self.assertIn(f"/app/reports/{self.organization.pk}/{self.project.pk}", body)
            self.assertIn("not immutable incident times", body)
            self.assertIn("No new analysis", body)
            for private in (self.project.canonical_origin, self.project.name, "fixture", "/shared/"):
                self.assertNotIn(private, subject + body)
            return 1
        with patch("jobs.alert_digest_delivery.send_mail", side_effect=accepted) as smtp, \
                patch("socket.create_connection", side_effect=AssertionError("network")):
            states = self.parallel(lambda: delivery.deliver_daily_alert_digest(row.pk))
        self.assertIn("sent", states)
        self.assertLessEqual(set(states), {"sent", "sending"})
        self.assertEqual(smtp.call_count, 1)
        self.assertEqual(self.reserve(), row.pk)
        self.assertEqual(delivery.recover_daily_alert_digests(), [])

    def test_atomic_claim_insertion_loss_rolls_back_entire_reservation(self):
        original = ProjectAlertEpisodeClaim.objects.bulk_create
        def insert_then_disable(rows, *args, **kwargs):
            inserted = original(rows, *args, **kwargs)
            ProjectAlertPreference.objects.filter(user=self.user).update(frequency="off", revision=2)
            return inserted
        with patch.object(ProjectAlertEpisodeClaim.objects, "bulk_create", side_effect=insert_then_disable), \
                self.assertRaises(PermissionDenied): self.reserve()
        self.assertFalse(ProjectAlertDelivery.objects.exists())
        self.assertFalse(ProjectAlertEpisodeClaim.objects.exists())
        self.assertEqual(ProjectAlertPreference.objects.get().revision, 1)
        row_id = self.reserve()
        self.assertEqual(delivery.recover_daily_alert_digests(limit=1), [row_id])
        with self.assertRaises(ValueError): delivery.recover_daily_alert_digests(limit=21)

    def test_committed_sending_survives_crash_and_outer_or_manual_transaction_never_sends(self):
        row_id = self.reserve()
        with transaction.atomic(), self.assertRaises(RuntimeError): delivery.deliver_daily_alert_digest(row_id)
        transaction.set_autocommit(False)
        try:
            with self.assertRaises(RuntimeError): delivery.deliver_daily_alert_digest(row_id)
        finally:
            transaction.rollback(); transaction.set_autocommit(True)
        def crash(*args, **kwargs):
            def observed():
                close_old_connections()
                try: return ProjectAlertDelivery.objects.get(pk=row_id).state
                finally: connection.close()
            with ThreadPoolExecutor(max_workers=1) as pool:
                self.assertEqual(pool.submit(observed).result(timeout=10), "sending")
            raise SystemExit("synthetic termination after external attempt")
        with patch("jobs.alert_digest_delivery.send_mail", side_effect=crash) as smtp:
            with self.assertRaises(SystemExit): delivery.deliver_daily_alert_digest(row_id)
            self.assertEqual(smtp.call_count, 1)
        row = ProjectAlertDelivery.objects.get()
        self.assertEqual(row.state, "sending")
        with patch("django.utils.timezone.now", return_value=row.attempted_at + timedelta(minutes=3)), \
                override_settings(ALERT_DIGEST_DELIVERY_ENABLED=False):
            self.assertEqual(delivery.recover_daily_alert_digests(), [])
        row.refresh_from_db(); self.assertEqual(row.state, "unknown")
        self.assertEqual(row.error_category, "worker_outcome_unknown")
        with patch("jobs.alert_digest_delivery.send_mail", side_effect=AssertionError("replay")):
            self.assertEqual(delivery.deliver_daily_alert_digest(row_id), "unknown")
            self.assertEqual(self.reserve(), row_id)
        self.assertEqual(ProjectAlertEpisodeClaim.objects.count(), 2)

    def test_zero_or_exception_is_unknown_without_private_text_or_replay(self):
        for outcome in (0, OSError("private provider customer failure")):
            row_id = self.reserve()
            with patch("jobs.alert_digest_delivery.send_mail", side_effect=outcome if isinstance(outcome, Exception) else None,
                       return_value=outcome) as smtp:
                self.assertEqual(delivery.deliver_daily_alert_digest(row_id), "unknown")
                self.assertEqual(delivery.deliver_daily_alert_digest(row_id), "unknown")
                self.assertEqual(smtp.call_count, 1)
            row = ProjectAlertDelivery.objects.get()
            self.assertEqual(row.error_category, "delivery_uncertain")
            self.assertIsNone(row.sent_at)
            # Independent synthetic transport case only; normal recovery never releases claims.
            ProjectAlertEpisodeClaim.objects.all().delete(); ProjectAlertDelivery.objects.all().delete()

    def test_moved_source_dates_dedupe_old_episodes_but_allow_one_new_later_day_episode(self):
        row_id = self.reserve()
        with patch("jobs.alert_digest_delivery.send_mail", return_value=0):
            self.assertEqual(delivery.deliver_daily_alert_digest(row_id), "unknown")
        next_assessment = self.assessed + timedelta(days=1)
        with patch("django.utils.timezone.now", return_value=next_assessment):
            self.assertIsNone(self.reserve())  # No older-day fallback.
            JobRun.objects.filter(pk=self.job.pk).update(updated_at=self.end + timedelta(hours=1))
            AuditEvent.objects.filter(pk=self.audit.pk).update(created_at=self.end + timedelta(hours=1))
            self.assertIsNone(self.reserve())  # Same mutable source dates, actual identities already consumed.
            with patch("django.utils.timezone.now", return_value=self.intent_at + timedelta(seconds=1)):
                set_project_alert_preference(project=self.project, actor=self.user, frequency="off",
                    source_families=["crawl_failure", "integration_health"], expected_revision=1)
                set_project_alert_preference(project=self.project, actor=self.user, frequency="daily",
                    source_families=["crawl_failure", "integration_health"], expected_revision=2)
            self.assertIsNone(self.reserve())
            new_job = self.failed("next-day-new-root", created=self.end + timedelta(hours=1), updated=self.end + timedelta(hours=2))
            new_id = self.reserve()
            self.assertNotEqual(new_id, row_id)
            new = ProjectAlertDelivery.objects.get(pk=new_id)
            self.assertEqual(new.source_metadata["claimed_episodes"], [f"crawl:{new_job.pk}"])
            self.assertEqual(ProjectAlertEpisodeClaim.objects.count(), 3)
            with patch("jobs.alert_digest_delivery.send_mail", return_value=1) as smtp:
                self.assertEqual(delivery.deliver_daily_alert_digest(new_id), "sent")
                self.assertEqual(delivery.deliver_daily_alert_digest(new_id), "sent")
            self.assertIn("selects 1 operational source records", smtp.call_args.args[1])
            self.assertEqual(smtp.call_count, 1)

    def test_final_original_source_or_recipient_loss_skips_and_retains_claims(self):
        def off_on():
            set_project_alert_preference(project=self.project, actor=self.user, frequency="off",
                source_families=["crawl_failure", "integration_health"], expected_revision=1)
            set_project_alert_preference(project=self.project, actor=self.user, frequency="daily",
                source_families=["crawl_failure", "integration_health"], expected_revision=2)
        def primary():
            EmailAddress.objects.filter(user=self.user).update(primary=False)
            get_user_model().objects.filter(pk=self.user.pk).update(email="new-digest@example.invalid")
            EmailAddress.objects.create(user=self.user, email="new-digest@example.invalid", verified=True, primary=True)
        changes = [off_on, primary,
            lambda: ProjectAlertPreference.objects.filter(user=self.user).update(crawl_failure=False, revision=2),
            lambda: EmailAddress.objects.filter(user=self.user).update(verified=False),
            lambda: record_ses_feedback(("digest-kernel-complaint-001", "complaint", (self.user.email,))),
            lambda: OrganizationMembership.objects.filter(user=self.user).delete(),
            lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=timezone.now()),
            lambda: OrganizationTrial.objects.filter(organization=self.organization).update(
                ends_at=OrganizationTrial.objects.get(organization=self.organization).started_at + timedelta(microseconds=1)),
            lambda: IntegrationConnection.objects.filter(pk=self.connection.pk).update(currency="TRY"),
            lambda: AuditEvent.objects.filter(pk=self.audit.pk).update(created_at=self.audit.created_at + timedelta(microseconds=1)),
            lambda: ProjectAlertEpisodeClaim.objects.filter(episode_key=f"crawl:{self.job.pk}").update(episode_key="crawl:999999")]
        original = delivery._message
        for index, change in enumerate(changes):
            def message_then_change(*args):
                result = original(*args); change(); return result
            row_id = self.reserve()
            with self.subTest(index=index), patch("jobs.alert_digest_delivery._message", side_effect=message_then_change), \
                    patch("jobs.alert_digest_delivery.send_mail", side_effect=AssertionError("SMTP")):
                self.assertEqual(delivery.deliver_daily_alert_digest(row_id), "skipped")
            self.assertEqual(ProjectAlertEpisodeClaim.objects.count(), 2)
            self.assertEqual(ProjectAlertDelivery.objects.get().error_category, "current_source_or_recipient_changed")
            self._fixture_teardown(); self._fixture_setup(); self.setUp()

    def test_old_day_or_rollout_loss_after_committed_sending_never_falls_back(self):
        row_id = self.reserve()
        with patch("django.utils.timezone.now", return_value=self.assessed + timedelta(days=1)), \
                patch("jobs.alert_digest_delivery.send_mail", side_effect=AssertionError("old-day send")):
            self.assertEqual(delivery.deliver_daily_alert_digest(row_id), "skipped")
        self.assertEqual(ProjectAlertEpisodeClaim.objects.count(), 2)
        self.assertEqual(self.reserve(), row_id)
        self.assertEqual(delivery.deliver_daily_alert_digest(999999), "missing")
        with patch("django.utils.timezone.now", return_value=self.assessed + timedelta(days=1)):
            JobRun.objects.filter(pk=self.job.pk).update(updated_at=self.end + timedelta(hours=1))
            AuditEvent.objects.filter(pk=self.audit.pk).update(created_at=self.end + timedelta(hours=1))
            self.assertIsNone(self.reserve())  # Skipped claims are consumed too.
        self._fixture_teardown(); self._fixture_setup(); self.setUp()
        row_id = self.reserve()
        original = delivery._message
        switch = override_settings(ALERT_DIGEST_DELIVERY_ENABLED=False)
        def disable(*args):
            result = original(*args); switch.enable(); return result
        try:
            with patch("jobs.alert_digest_delivery._message", side_effect=disable), \
                    patch("jobs.alert_digest_delivery.send_mail", side_effect=AssertionError("disabled SMTP")):
                self.assertEqual(delivery.deliver_daily_alert_digest(row_id), "skipped")
        finally:
            switch.disable()

    def test_natural_exact_expiry_after_sending_commit_uses_fresh_entitlement_clock(self):
        trial = OrganizationTrial.objects.get(organization=self.organization)
        end = trial.ends_at.replace(hour=0, minute=0, second=0, microsecond=0)
        JobRun.objects.filter(pk=self.job.pk).update(created_at=end - timedelta(hours=23), updated_at=end - timedelta(hours=22))
        AuditEvent.objects.filter(pk=self.audit.pk).update(created_at=end - timedelta(hours=23))
        ProjectAlertPreference.objects.filter(user=self.user).update(updated_at=end - timedelta(days=1))
        expired = False
        original = delivery._message
        def clock(): return trial.ends_at if expired else trial.ends_at - timedelta(microseconds=1)
        def expire(*args):
            nonlocal expired
            result = original(*args); expired = True; return result
        with patch("django.utils.timezone.now", side_effect=clock):
            row_id = self.reserve()
            with patch("jobs.alert_digest_delivery._message", side_effect=expire), \
                    patch("jobs.alert_digest_delivery.send_mail", side_effect=AssertionError("expired SMTP")):
                self.assertEqual(delivery.deliver_daily_alert_digest(row_id), "skipped")
        self.assertTrue(expired)
        self.assertEqual(ProjectAlertEpisodeClaim.objects.count(), 2)

    def test_actual_customer_export_child_first_erasure_and_own_personal_close(self):
        from accounts.closure import close_personal_access
        from tenancy.customer_export import project_customer_rows, _reviewed_fields
        from tenancy.customer_inventory import require_complete_ownership_map
        from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        own_id = self.reserve()
        other = get_user_model().objects.create_user("other-digest@example.invalid", password="fixture-password")
        EmailAddress.objects.create(user=other, email=other.email, verified=True, primary=True)
        other_org = create_organization(user=other, name="Other digest org")
        other_project = create_project(organization=other_org, user=other, name="Other digest project",
                                       canonical_origin="https://other-digest.example.invalid")
        OrganizationMembership.objects.create(organization=self.organization, user=other, role="viewer")
        with patch("django.utils.timezone.now", return_value=self.intent_at):
            set_project_alert_preference(project=self.project, actor=other, frequency="daily",
                source_families=["crawl_failure", "integration_health"], expected_revision=0)
        other_id = delivery.reserve_daily_alert_digest(project=self.project, recipient=other)
        require_complete_ownership_map()
        for label, through in (("jobs.ProjectAlertDelivery", other_id),
                               ("jobs.ProjectAlertEpisodeClaim", ProjectAlertEpisodeClaim.objects.latest("pk").pk)):
            _reviewed_fields(label)
            exported = project_customer_rows(organization=self.organization, actor=self.user,
                model_label=label, after_id=0, through_id=through)
            self.assertEqual({item["recipient_id"] for item in exported["rows"]}, {self.user.pk, other.pk})
            self.assertNotIn(self.user.email, json.dumps(exported, cls=DjangoJSONEncoder))
        revoke_google_grant(grant=self.grant, user=self.user, expected_revision=self.grant.revision,
                            remote_revoke=lambda **_: True)
        with project_artifact_barrier(self.organization.pk, shared=True), transaction.atomic():
            Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=timezone.now())
            run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.organization))
            delete_customer_database_records(run=run)
            self.assertFalse(ProjectAlertDelivery.objects.filter(project=self.project).exists())
            self.assertFalse(ProjectAlertEpisodeClaim.objects.filter(project=self.project).exists())
            self.assertTrue(Project.objects.filter(pk=other_project.pk).exists())
            transaction.set_rollback(True)
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=timezone.now())
        request = RequestFactory().post("/api/account/close/"); request.user = self.user
        with patch("tenancy.services.did_recently_authenticate", return_value=True):
            close_personal_access(actor=self.user, request=request)
        self.assertFalse(ProjectAlertDelivery.objects.filter(pk=own_id).exists())
        self.assertFalse(ProjectAlertEpisodeClaim.objects.filter(recipient=self.user).exists())
        self.assertTrue(ProjectAlertDelivery.objects.filter(pk=other_id).exists())
        self.assertEqual(ProjectAlertEpisodeClaim.objects.filter(recipient=other).count(), 2)
