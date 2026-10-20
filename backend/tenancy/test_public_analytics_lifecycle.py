from datetime import timedelta
from hashlib import sha256
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from kombu.exceptions import OperationalError

from .models import PublicAnalyticsConsentEpoch, PublicAnalyticsObservation
from .public_analytics import (drain_expired_public_analytics_epochs, issue_public_analytics_epoch,
                               public_analytics_cleanup_status, record_public_observation,
                               retained_public_observation_counts, withdraw_public_analytics_epoch)
from .tasks import purge_public_analytics_task
from .test_public_analytics import CONFIG, PIN, configure_policy
from .test_public_analytics_source import candidate
from .public_analytics_source import CONSENT_VERSION


@override_settings(**CONFIG, STAFF_MFA_REQUIRED=False,
                   CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class PublicAnalyticsLifecycleTests(TestCase):
    def setUp(self):
        configure_policy(self)
        cache.clear()

    def issue(self):
        return issue_public_analytics_epoch(allowed=True, consent_version=CONSENT_VERSION)

    def test_actual_multi_batch_hourly_expiry_drain_even_policy_off_and_deadline_alert(self):
        live = self.issue()
        record_public_observation(receipt_proof=live["receipt_proof"], candidate=candidate())
        born = timezone.now() - timedelta(minutes=76)
        PublicAnalyticsConsentEpoch.objects.bulk_create([
            PublicAnalyticsConsentEpoch(proof_digest=sha256(str(i).encode()).hexdigest(), policy_digest=PIN,
                created_at=born, expires_at=born + timedelta(minutes=15)) for i in range(501)])
        self.assertEqual(public_analytics_cleanup_status(), {"expired_pending": True, "deadline_missed": True})
        with override_settings(PUBLIC_ANALYTICS_ENABLED=False), self.assertLogs("tenancy.public_analytics", level="ERROR") as logs:
            self.assertEqual(drain_expired_public_analytics_epochs(), {"expired_pending": False, "deadline_missed": False})
        self.assertIn("public_analytics.cleanup_overdue", logs.output[0])
        self.assertEqual(PublicAnalyticsConsentEpoch.objects.count(), 1)
        self.assertEqual(PublicAnalyticsObservation.objects.count(), 1)
        self.assertEqual(settings.CELERY_BEAT_SCHEDULE["public-analytics-expiry"]["schedule"], 3600.0)
        self.assertEqual(settings.CELERY_BEAT_SCHEDULE["public-analytics-expiry"]["options"], {"queue": "default"})

    def test_bounded_timeout_remaining_backlog_continuation_and_failed_broker_monitoring(self):
        self.issue(); epoch = PublicAnalyticsConsentEpoch.objects.get()
        with patch("tenancy.public_analytics.timezone.now", return_value=epoch.expires_at), \
             patch("tenancy.public_analytics.purge_expired_public_analytics_epochs", return_value=1) as purge, \
             patch("tenancy.public_analytics.monotonic", side_effect=[0, 26]), \
             patch.object(purge_public_analytics_task, "apply_async") as dispatch:
            status = purge_public_analytics_task.run()
        self.assertTrue(status["expired_pending"]); self.assertEqual(purge.call_count, 1)
        dispatch.assert_called_once_with(args=[], queue="default", countdown=1, retry=False)
        with patch("tenancy.public_analytics.drain_expired_public_analytics_epochs", return_value=status), \
             patch.object(purge_public_analytics_task, "apply_async", side_effect=OperationalError), \
             self.assertLogs("tenancy.tasks", level="ERROR") as logs:
            purge_public_analytics_task.run()
        self.assertIn("public_analytics.cleanup_dispatch_failed", logs.output[0])
        self.assertEqual(PublicAnalyticsConsentEpoch.objects.count(), 1)

    def test_separate_staff_mfa_current_unexpired_count_no_operational_ids_and_withdrawal_decrease(self):
        grant, other = self.issue(), self.issue()
        for issued in (grant, other):
            record_public_observation(receipt_proof=issued["receipt_proof"], candidate=candidate())
        record_public_observation(receipt_proof=grant["receipt_proof"], candidate={**candidate(),
            "event_id": "public_cta_selected", "cta_id": "public_trial_cta"})
        url = "/api/platform/acquisition/public-observations/"
        self.assertEqual(self.client.get(url).status_code, 401)
        users = get_user_model().objects
        customer = users.create_user("public-count-customer@example.invalid", "Test passphrase 99!")
        self.client.force_login(customer); self.assertEqual(self.client.get(url).status_code, 403)
        staff = users.create_superuser("public-count-staff@example.invalid", "Test passphrase 99!")
        self.client.force_login(staff)
        with CaptureQueriesContext(connection) as queries:
            result = self.client.get(url)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result["Cache-Control"], "private, no-store")
        self.assertEqual(result.json()["milestones"]["public_page_view"]["count"], 2)
        self.assertEqual(result.json()["milestones"]["public_cta_selected"]["count"], 1)
        self.assertFalse(any(row["sql"].lstrip().split()[0] in {"INSERT", "UPDATE", "DELETE"} for row in queries))
        for secret in ("registration_succeeded", "organization_id", "project_id", "receipt_proof", "policy_digest",
                       "occurred_at", "HOME", "public_trial_cta", staff.email, grant["receipt_proof"]):
            self.assertNotIn(secret, result.content.decode())
        with override_settings(STAFF_MFA_REQUIRED=True):
            denied = self.client.get(url)
            self.assertEqual(denied.status_code, 403); self.assertEqual(denied["Cache-Control"], "private, no-store")
        self.assertEqual(self.client.post(url).status_code, 405)
        self.assertEqual(self.client.get(url + "?extra=1").status_code, 400)
        withdraw_public_analytics_epoch(receipt_proof=grant["receipt_proof"])
        self.assertEqual(retained_public_observation_counts()["milestones"]["public_page_view"]["count"], 1)
        epoch = PublicAnalyticsConsentEpoch.objects.get(proof_digest=sha256(other["receipt_proof"].encode()).hexdigest())
        with patch("tenancy.public_analytics.timezone.now", return_value=epoch.expires_at):
            self.assertEqual(retained_public_observation_counts()["milestones"]["public_page_view"]["count"], 0)
        with override_settings(PUBLIC_ANALYTICS_ENABLED=False):
            self.assertIsNone(retained_public_observation_counts()["milestones"]["public_page_view"]["count"])
