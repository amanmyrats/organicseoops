from datetime import timedelta
from unittest.mock import patch

from allauth.account.models import EmailAddress
from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import TransactionTestCase, override_settings
from kombu.exceptions import OperationalError

from config.test_foundations import TEST_STORAGES
from tenancy.models import OrganizationMembership
from . import alert_digest_schedule as schedule, test_alert_digest_delivery as fixtures
from .alert_digest_source import _day
from .alert_preferences import set_project_alert_preference
from .models import ProjectAlertDelivery, ProjectAlertEpisodeClaim, ProjectAlertPreference
from .tasks import scan_daily_alert_digests_task, send_daily_alert_digest_task


@override_settings(STORAGES=TEST_STORAGES, ALERT_DIGEST_DELIVERY_ENABLED=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", GOOGLE_OAUTH_CLIENT_ID="fixture-client",
    GOOGLE_OAUTH_CLIENT_SECRET="fixture-secret", GOOGLE_OAUTH_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),))
class DailyDigestScheduleTests(TransactionTestCase):
    captureOnCommitCallbacks = fixtures.DailyDigestDeliveryTests.captureOnCommitCallbacks
    failed = fixtures.DailyDigestDeliveryTests.failed
    deny = fixtures.DailyDigestDeliveryTests.deny
    enable = fixtures.DailyDigestDeliveryTests.enable

    def setUp(self):
        fixtures.DailyDigestDeliveryTests.setUp(self)

    def reader(self, index):
        user = get_user_model().objects.create_user(f"digest-page-{index}@example.invalid")
        EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
        OrganizationMembership.objects.create(organization=self.organization, user=user, role="viewer")
        # Original intent precedes the genuine source records, not a backfilled delivery.
        with patch("django.utils.timezone.now", return_value=self.intent_at):
            set_project_alert_preference(project=self.project, actor=user, frequency="daily",
                source_families=["crawl_failure", "integration_health"], expected_revision=0)
        return user

    def test_default_off_no_queries_or_broker_smtp_and_actual_task_routes_limits(self):
        with override_settings(ALERT_DIGEST_DELIVERY_ENABLED=False), self.assertNumQueries(0), \
                patch.object(send_daily_alert_digest_task, "apply_async", side_effect=AssertionError("broker")), \
                patch("jobs.alert_digest_delivery.send_mail", side_effect=AssertionError("SMTP")):
            self.assertEqual(scan_daily_alert_digests_task()["state"], "disabled")
            self.assertEqual(send_daily_alert_digest_task(999), "disabled")
        for task in (scan_daily_alert_digests_task, send_daily_alert_digest_task):
            self.assertEqual(settings.CELERY_TASK_ROUTES[task.name], {"queue": "default"})
            self.assertTrue(task.acks_late); self.assertTrue(task.reject_on_worker_lost)
            self.assertEqual(task.max_retries, 0)
            self.assertLess(task.soft_time_limit, task.time_limit)
        self.assertEqual(settings.CELERY_BEAT_SCHEDULE["optional-daily-alert-digests"],
            {"task": scan_daily_alert_digests_task.name, "schedule": 3600.0, "options": {"queue": "default"}})

    def test_denied_prefix_fair_continuation_high_water_and_later_fresh_scan(self):
        EmailAddress.objects.filter(user=self.user).update(verified=False)
        for index in range(19):
            EmailAddress.objects.filter(user=self.reader(index)).update(verified=False)
        eligible = self.reader(20)
        through = ProjectAlertPreference.objects.latest("pk").pk
        with patch.object(scan_daily_alert_digests_task, "apply_async", side_effect=OperationalError("synthetic continuation outage")):
            self.assertEqual(scan_daily_alert_digests_task()["dispatch_failures"], 1)
        self.assertFalse(ProjectAlertDelivery.objects.exists())
        with patch.object(scan_daily_alert_digests_task, "apply_async") as continuation, \
                patch.object(send_daily_alert_digest_task, "apply_async") as dispatch, \
                patch("jobs.alert_digest_delivery.send_mail", side_effect=AssertionError("discovery SMTP")):
            first = scan_daily_alert_digests_task()
            self.assertEqual(first["inspected"], 20); self.assertTrue(first["has_more"])
            self.assertEqual(first["eligible_queued"], 0); self.assertFalse(dispatch.called)
            args = continuation.call_args.kwargs["args"]
            self.assertEqual(args[1:], [through, _day()[0].date().isoformat()])
            later = self.reader(21)
            second = scan_daily_alert_digests_task(*args)
            self.assertEqual(second["inspected"], 1); self.assertFalse(second["has_more"])
            row = ProjectAlertDelivery.objects.get()
            self.assertEqual(row.recipient_id, eligible.pk)
            self.assertFalse(ProjectAlertDelivery.objects.filter(recipient=later).exists())
            self.assertEqual(dispatch.call_args.kwargs["args"], [row.pk])
            self.assertEqual(dispatch.call_args.kwargs["queue"], "default")
            self.assertFalse(dispatch.call_args.kwargs["retry"])
            scan_daily_alert_digests_task()
            scan_daily_alert_digests_task(*continuation.call_args.kwargs["args"])
            self.assertEqual(ProjectAlertDelivery.objects.count(), 2)
            self.assertEqual(ProjectAlertEpisodeClaim.objects.count(), 4)

    def test_after_commit_only_rollback_outage_recovery_and_real_wrapper_never_replays(self):
        with patch.object(send_daily_alert_digest_task, "apply_async") as dispatch:
            with transaction.atomic():
                scan_daily_alert_digests_task()
                self.assertFalse(dispatch.called)
                self.assertTrue(ProjectAlertDelivery.objects.exists())
                transaction.set_rollback(True)
            self.assertFalse(dispatch.called)
            self.assertFalse(ProjectAlertDelivery.objects.exists())
            self.assertFalse(ProjectAlertEpisodeClaim.objects.exists())
        with patch.object(send_daily_alert_digest_task, "apply_async", side_effect=OperationalError("synthetic broker outage")):
            self.assertEqual(scan_daily_alert_digests_task()["dispatch_failures"], 1)
        row = ProjectAlertDelivery.objects.get()
        self.assertEqual(row.state, "queued")
        with patch.object(send_daily_alert_digest_task, "apply_async") as dispatch:
            self.assertEqual(scan_daily_alert_digests_task()["eligible_queued"], 1)
            self.assertEqual(dispatch.call_count, 1)
        with patch("jobs.alert_digest_delivery.send_mail", side_effect=OSError("synthetic SMTP uncertain")) as smtp:
            self.assertEqual(send_daily_alert_digest_task(row.pk), "unknown")
            self.assertEqual(send_daily_alert_digest_task(row.pk), "unknown")
            self.assertEqual(smtp.call_count, 1)
        with patch.object(send_daily_alert_digest_task, "apply_async") as dispatch:
            self.assertEqual(scan_daily_alert_digests_task()["eligible_queued"], 0)
            self.assertFalse(dispatch.called)

    def test_obsolete_day_invalid_internal_cursor_and_after_commit_midnight_cancel(self):
        through = ProjectAlertPreference.objects.latest("pk").pk
        day = _day()[0].date().isoformat()
        with patch.object(send_daily_alert_digest_task, "apply_async", side_effect=AssertionError("broker")), \
                patch("jobs.alert_digest_schedule.reserve_daily_alert_digest", side_effect=AssertionError("source")):
            with patch("django.utils.timezone.now", return_value=self.assessed + timedelta(days=1)):
                self.assertEqual(scan_daily_alert_digests_task(0, through, day)["state"], "obsolete_day")
            for args in ((True, through, day), (-1, through, day), (1, 0, day), (0, True, day),
                         (0, through, None), (0, None, day), (0, 2**63, day)):
                with self.assertRaises(ValidationError): scan_daily_alert_digests_task(*args)
        with patch.object(send_daily_alert_digest_task, "apply_async") as dispatch:
            clock = patch("django.utils.timezone.now", return_value=self.assessed + timedelta(days=1))
            try:
                with transaction.atomic():
                    status = scan_daily_alert_digests_task()
                    # Keep the shifted clock active through the actual outer commit.
                    clock.start()
            finally:
                clock.stop()
            self.assertEqual(status["state"], "obsolete_day")
            self.assertFalse(dispatch.called)
            self.assertEqual(ProjectAlertDelivery.objects.get().state, "queued")
