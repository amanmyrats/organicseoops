from datetime import timedelta
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import TransactionTestCase, override_settings
from kombu.exceptions import OperationalError

from config.test_foundations import TEST_STORAGES
from tenancy.models import OrganizationMembership
from . import crux_digest_schedule as schedule, test_crux_digest_delivery as fixtures
from .crux_alert_preferences import set_project_crux_alert_preference
from .models import ProjectCruxAlertDelivery, ProjectCruxEpisodeClaim, ProjectCruxAlertPreference
from .tasks import scan_daily_crux_digests_task, send_daily_crux_digest_task


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}),
                   GOOGLE_PERFORMANCE_API_KEY="fixture_key_with_32_placeholder_chars", CRUX_ALERT_DELIVERY_ENABLED=True,
                   EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class CruxDigestScheduleTests(TransactionTestCase):
    setUp = fixtures.CruxDigestDeliveryTests.setUp
    date_part = staticmethod(fixtures.CruxDigestDeliveryTests.date_part)
    history = fixtures.CruxDigestDeliveryTests.history
    all_metrics = fixtures.CruxDigestDeliveryTests.all_metrics
    collect = fixtures.CruxDigestDeliveryTests.collect
    enable = fixtures.CruxDigestDeliveryTests.enable

    def scan(self, *args):
        with patch("django.utils.timezone.now", return_value=self.assessed):
            return scan_daily_crux_digests_task(*args)

    def reader(self, index):
        user = get_user_model().objects.create_user(f"crux-scan-{index}@example.invalid")
        EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
        OrganizationMembership.objects.create(organization=self.organization, user=user, role="viewer")
        with patch("django.utils.timezone.now", return_value=self.intent_at):
            set_project_crux_alert_preference(project=self.project, actor=user, frequency="daily", expected_revision=0)
        return user

    def test_default_off_no_queries_or_broker_smtp_and_actual_task_routes_limits(self):
        with override_settings(CRUX_ALERT_DELIVERY_ENABLED=False), self.assertNumQueries(0), \
                patch.object(send_daily_crux_digest_task, "apply_async", side_effect=AssertionError("broker")), \
                patch("jobs.crux_digest_delivery.send_mail", side_effect=AssertionError("SMTP")):
            self.assertEqual(self.scan()["state"], "disabled")
            self.assertEqual(send_daily_crux_digest_task(99999), "disabled")
        for task in (scan_daily_crux_digests_task, send_daily_crux_digest_task):
            self.assertEqual(settings.CELERY_TASK_ROUTES[task.name], {"queue": "default"})
            self.assertTrue(task.acks_late); self.assertTrue(task.reject_on_worker_lost)
            self.assertEqual(task.max_retries, 0); self.assertLess(task.soft_time_limit, task.time_limit)
        self.assertEqual(settings.CELERY_BEAT_SCHEDULE["optional-daily-crux-digests"],
                         {"task": scan_daily_crux_digests_task.name, "schedule": 3600.0, "options": {"queue": "default"}})

    def test_denied_prefix_fair_high_water_continuation_outage_and_fresh_scan(self):
        EmailAddress.objects.filter(user=self.owner).update(verified=False)
        for index in range(19):
            EmailAddress.objects.filter(user=self.reader(index)).update(verified=False)
        eligible = self.reader(20); through = ProjectCruxAlertPreference.objects.latest("pk").pk
        with patch.object(scan_daily_crux_digests_task, "apply_async", side_effect=OperationalError("synthetic continuation outage")):
            self.assertEqual(self.scan()["dispatch_failures"], 1)
        self.assertFalse(ProjectCruxAlertDelivery.objects.exists())
        with patch.object(scan_daily_crux_digests_task, "apply_async") as continuation, \
                patch.object(send_daily_crux_digest_task, "apply_async") as dispatch, \
                patch("jobs.crux_digest_delivery.send_mail", side_effect=AssertionError("discovery SMTP")):
            first = self.scan(); self.assertEqual(first["inspected"], 20); self.assertTrue(first["has_more"])
            self.assertEqual(first["eligible_queued"], 0); self.assertFalse(dispatch.called)
            args = continuation.call_args.kwargs["args"]
            self.assertEqual(args[1:], [through, self.start.date().isoformat()])
            later = self.reader(21)
            second = self.scan(*args); self.assertEqual(second["inspected"], 1); self.assertFalse(second["has_more"])
            row = ProjectCruxAlertDelivery.objects.get(); self.assertEqual(row.recipient_id, eligible.pk)
            self.assertFalse(ProjectCruxAlertDelivery.objects.filter(recipient=later).exists())
            self.assertEqual(dispatch.call_args.kwargs["args"], [row.pk]); self.assertFalse(dispatch.call_args.kwargs["retry"])
            self.scan(); self.scan(*continuation.call_args.kwargs["args"])
            self.assertEqual(ProjectCruxAlertDelivery.objects.count(), 2); self.assertEqual(ProjectCruxEpisodeClaim.objects.count(), 6)

    def test_after_commit_rollback_broker_outage_queued_recovery_and_actual_wrapper_no_replay(self):
        with patch.object(send_daily_crux_digest_task, "apply_async") as dispatch:
            with transaction.atomic():
                self.scan(); self.assertFalse(dispatch.called); self.assertTrue(ProjectCruxAlertDelivery.objects.exists())
                transaction.set_rollback(True)
            self.assertFalse(dispatch.called); self.assertFalse(ProjectCruxAlertDelivery.objects.exists())
            self.assertFalse(ProjectCruxEpisodeClaim.objects.exists())
        with patch.object(send_daily_crux_digest_task, "apply_async", side_effect=OperationalError("synthetic broker outage")):
            self.assertEqual(self.scan()["dispatch_failures"], 1)
        row = ProjectCruxAlertDelivery.objects.get(); self.assertEqual(row.state, "queued")
        with patch.object(send_daily_crux_digest_task, "apply_async") as dispatch:
            self.assertEqual(self.scan()["eligible_queued"], 1); self.assertEqual(dispatch.call_count, 1)
        with patch("django.utils.timezone.now", return_value=self.assessed), \
                patch("jobs.crux_digest_delivery.send_mail", side_effect=OSError("synthetic SMTP uncertainty")) as smtp:
            self.assertEqual(send_daily_crux_digest_task(row.pk), "unknown")
            self.assertEqual(send_daily_crux_digest_task(row.pk), "unknown"); self.assertEqual(smtp.call_count, 1)
        with patch.object(send_daily_crux_digest_task, "apply_async") as dispatch:
            self.assertEqual(self.scan()["eligible_queued"], 0); self.assertFalse(dispatch.called)

    def test_obsolete_day_invalid_cursor_and_after_commit_midnight_or_flag_loss(self):
        through = ProjectCruxAlertPreference.objects.latest("pk").pk; day = self.start.date().isoformat()
        with patch.object(send_daily_crux_digest_task, "apply_async", side_effect=AssertionError("broker")), \
                patch("jobs.crux_digest_schedule.reserve_daily_crux_digest", side_effect=AssertionError("source")):
            with patch("django.utils.timezone.now", return_value=self.assessed + timedelta(days=1)):
                self.assertEqual(scan_daily_crux_digests_task(0, through, day)["state"], "obsolete_day")
            for args in ((True, through, day), (-1, through, day), (1, 0, day), (0, True, day),
                         (0, through, None), (0, None, day), (0, 2**63, day)):
                with self.assertRaises(ValidationError): self.scan(*args)
        for loss in (patch("django.utils.timezone.now", return_value=self.assessed + timedelta(days=1)),
                     override_settings(CRUX_ALERT_DELIVERY_ENABLED=False)):
            with patch.object(send_daily_crux_digest_task, "apply_async") as dispatch:
                try:
                    with transaction.atomic():
                        status = self.scan(); loss.__enter__()
                finally: loss.__exit__(None, None, None)
                self.assertIn(status["state"], {"obsolete_day", "disabled"}); self.assertFalse(dispatch.called)
                self.assertEqual(ProjectCruxAlertDelivery.objects.get().state, "queued")
