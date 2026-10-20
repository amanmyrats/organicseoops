from datetime import timedelta
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from kombu.exceptions import OperationalError

from config.test_foundations import TEST_STORAGES
from tenancy.models import OrganizationMembership
from . import test_summary_delivery as fixtures
from .models import ProjectSummaryDelivery, ProjectSummaryPreference
from .summary_delivery import _week_start
from .summary_preferences import set_project_summary_preference
from .tasks import scan_weekly_summaries_task, send_weekly_summary_task


@override_settings(STORAGES=TEST_STORAGES, WEEKLY_SUMMARY_DELIVERY_ENABLED=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/csv", "application/json"}),
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "weekly-schedule"}})
class WeeklyScheduleTests(TransactionTestCase):
    create_report = fixtures.WeeklyDeliveryTests.create_report

    def setUp(self):
        fixtures.WeeklyDeliveryTests.setUp(self)

    def reader(self, index):
        user = get_user_model().objects.create_user(f"weekly-page-{index}@example.invalid")
        EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
        OrganizationMembership.objects.create(organization=self.org, user=user, role="viewer")
        set_project_summary_preference(project=self.project, actor=user, frequency="weekly", expected_revision=0)
        return user

    def test_default_off_task_has_no_queries_dispatch_or_smtp_and_routes_are_default_only(self):
        with override_settings(WEEKLY_SUMMARY_DELIVERY_ENABLED=False), CaptureQueriesContext(connection) as queries, \
                patch.object(send_weekly_summary_task, "apply_async", side_effect=AssertionError("broker")), \
                patch("jobs.summary_delivery.send_mail", side_effect=AssertionError("SMTP")):
            self.assertEqual(scan_weekly_summaries_task()["state"], "disabled")
            self.assertEqual(send_weekly_summary_task(999), "disabled")
        self.assertEqual(len(queries), 0)
        for task in (scan_weekly_summaries_task, send_weekly_summary_task):
            self.assertEqual(settings.CELERY_TASK_ROUTES[task.name], {"queue": "default"})
            self.assertTrue(task.acks_late); self.assertTrue(task.reject_on_worker_lost)
            self.assertEqual(task.max_retries, 0)
            self.assertLess(task.soft_time_limit, task.time_limit)
        self.assertEqual(settings.CELERY_BEAT_SCHEDULE["optional-weekly-summaries"], {
            "task": scan_weekly_summaries_task.name, "schedule": 3600.0, "options": {"queue": "default"}})

    def test_denied_prefix_advances_to_real_later_recipient_with_frozen_high_water(self):
        EmailAddress.objects.filter(user=self.owner).update(verified=False)
        for index in range(19):
            EmailAddress.objects.filter(user=self.reader(index)).update(verified=False)
        eligible = self.reader(20)
        through = ProjectSummaryPreference.objects.latest("pk").pk
        with patch.object(scan_weekly_summaries_task, "apply_async", side_effect=OperationalError("synthetic continuation failure")):
            self.assertEqual(scan_weekly_summaries_task()["dispatch_failures"], 1)
        self.assertFalse(ProjectSummaryDelivery.objects.exists())
        with patch.object(scan_weekly_summaries_task, "apply_async") as continuation, \
                patch.object(send_weekly_summary_task, "apply_async") as dispatch, \
                patch("jobs.summary_delivery.send_mail", side_effect=AssertionError("SMTP in discovery")):
            first = scan_weekly_summaries_task()
            self.assertEqual(first["inspected"], 20)
            self.assertTrue(first["has_more"])
            self.assertEqual(first["eligible_queued"], 0)
            self.assertFalse(dispatch.called)
            args = continuation.call_args.kwargs["args"]
            self.assertEqual(args[1:], [through, _week_start().isoformat()])
            self.assertEqual(continuation.call_args.kwargs["queue"], "default")
            new_reader = self.reader(21)  # Created after scan's frozen candidate high water.
            second = scan_weekly_summaries_task(*args)
            self.assertEqual(second["inspected"], 1)
            self.assertFalse(second["has_more"])
            row = ProjectSummaryDelivery.objects.get()
            self.assertEqual(row.recipient_id, eligible.pk)
            self.assertFalse(ProjectSummaryDelivery.objects.filter(recipient=new_reader).exists())
            self.assertEqual(dispatch.call_args.kwargs["args"], [row.pk])
            self.assertEqual(dispatch.call_args.kwargs["queue"], "default")
            self.assertFalse(dispatch.call_args.kwargs["retry"])
            # Later fresh scan can reach new reader, and does not strand candidates behind denied prefix.
            scan_weekly_summaries_task()
            final = scan_weekly_summaries_task(*continuation.call_args.kwargs["args"])
            self.assertEqual(final["inspected"], 2)
            self.assertEqual(ProjectSummaryDelivery.objects.count(), 2)

    def test_commit_only_dispatch_rollback_broker_failure_queued_recovery_and_wrapper_no_replay(self):
        with patch.object(send_weekly_summary_task, "apply_async") as dispatch:
            with transaction.atomic():
                scan_weekly_summaries_task()
                self.assertFalse(dispatch.called)
                self.assertTrue(ProjectSummaryDelivery.objects.exists())
                transaction.set_rollback(True)
            self.assertFalse(dispatch.called)
            self.assertFalse(ProjectSummaryDelivery.objects.exists())
        with patch.object(send_weekly_summary_task, "apply_async", side_effect=OperationalError("synthetic broker down")):
            self.assertEqual(scan_weekly_summaries_task()["dispatch_failures"], 1)
        row = ProjectSummaryDelivery.objects.get()
        self.assertEqual(row.state, "queued")
        with patch.object(send_weekly_summary_task, "apply_async") as dispatch:
            self.assertEqual(scan_weekly_summaries_task()["eligible_queued"], 1)
            self.assertEqual(dispatch.call_count, 1)
        with patch("jobs.summary_delivery.send_mail", side_effect=OSError("synthetic SMTP uncertain")) as smtp:
            self.assertEqual(send_weekly_summary_task(row.pk), "unknown")
            self.assertEqual(send_weekly_summary_task(row.pk), "unknown")
            self.assertEqual(smtp.call_count, 1)
        with patch.object(send_weekly_summary_task, "apply_async") as dispatch:
            self.assertEqual(scan_weekly_summaries_task()["eligible_queued"], 0)
            self.assertFalse(dispatch.called)

    def test_obsolete_week_and_invalid_internal_cursors_do_not_replay_backlog(self):
        through = ProjectSummaryPreference.objects.latest("pk").pk
        week = _week_start().isoformat()
        with patch.object(send_weekly_summary_task, "apply_async", side_effect=AssertionError("broker")), \
                patch("jobs.summary_schedule.reserve_weekly_summary", side_effect=AssertionError("source")):
            with patch("jobs.summary_schedule._week_start", return_value=_week_start() + timedelta(days=7)):
                self.assertEqual(scan_weekly_summaries_task(0, through, week)["state"], "obsolete_week")
            for args in ((True, through, week), (-1, through, week), (1, 0, week), (0, True, week),
                         (0, through, None), (0, None, week), (0, 2**63, week)):
                with self.subTest(args=args), self.assertRaises(ValidationError): scan_weekly_summaries_task(*args)
        self.assertFalse(ProjectSummaryDelivery.objects.exists())
