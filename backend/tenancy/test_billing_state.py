from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase

from .billing_state import paid_access_state, paid_work_available
from .models import Organization, PaddleSubscription


NOW = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)


class BillingAccessTests(SimpleTestCase):
    def subscription(self, **changes):
        return SimpleNamespace(**{**{
            "status": "active", "verified_at": NOW - timedelta(minutes=1), "currency_code": "USD",
            "period_starts_at": NOW - timedelta(days=10), "period_ends_at": NOW + timedelta(days=20),
            "failed_at": None, "scheduled_cancel_at": None, "canceled_at": None,
        }, **changes})

    def test_paid_period_and_period_end_cancel_stay_bounded_by_verified_time(self):
        active = self.subscription()
        self.assertEqual(paid_access_state(active, now=NOW), "paid_active")
        self.assertTrue(paid_work_available(active, now=NOW))
        cancel = self.subscription(scheduled_cancel_at=NOW + timedelta(days=20))
        self.assertEqual(paid_access_state(cancel, now=NOW), "cancellation_scheduled")
        self.assertFalse(paid_work_available(cancel, now=NOW + timedelta(days=20)))
        self.assertEqual(paid_access_state(self.subscription(verified_at=None), now=NOW), "unverified")
        self.assertEqual(paid_access_state(self.subscription(verified_at=NOW + timedelta(seconds=1)), now=NOW), "unavailable")
        self.assertFalse(paid_work_available(self.subscription(period_ends_at=NOW), now=NOW))

    def test_failure_grace_requires_verified_occurrence_and_expires_at_seven_days(self):
        failure = NOW - timedelta(days=2)
        past_due = self.subscription(status="past_due", failed_at=failure,
                                     grace_usage_starts_at=NOW - timedelta(days=10))
        self.assertEqual(paid_access_state(past_due, now=NOW), "payment_grace")
        self.assertTrue(paid_work_available(past_due, now=NOW))
        self.assertEqual(paid_access_state(past_due, now=failure + timedelta(days=7)), "read_only")
        for row in (self.subscription(status="past_due", failed_at=None),
                    self.subscription(status="past_due", failed_at=NOW),
                    self.subscription(status="past_due", failed_at=failure, verified_at=None)):
            self.assertFalse(paid_work_available(row, now=NOW))

    def test_canceled_and_paused_never_grant_new_work(self):
        canceled = self.subscription(status="canceled", canceled_at=NOW - timedelta(days=1))
        self.assertEqual(paid_access_state(canceled, now=NOW), "retained_read_only")
        self.assertEqual(paid_access_state(canceled, now=NOW + timedelta(days=89)), "retention_elapsed")
        for status in ("paused", "trialing"):
            self.assertFalse(paid_work_available(self.subscription(status=status), now=NOW))


class BillingSnapshotConstraints(TestCase):
    def test_inert_link_cannot_gain_partial_verified_timestamp_without_currency(self):
        organization = Organization.objects.create(name="Billing fixture")
        link = PaddleSubscription.objects.create(organization=organization, environment="sandbox",
            customer_id="ctm_" + "a" * 26, subscription_id="sub_" + "b" * 26, status="active")
        self.assertEqual(paid_access_state(link, now=NOW), "unverified")
        with self.assertRaises(IntegrityError), transaction.atomic():
            PaddleSubscription.objects.filter(pk=link.pk).update(verified_at=NOW, period_starts_at=NOW,
                period_ends_at=NOW + timedelta(days=30))
        self.assertIsNone(PaddleSubscription.objects.get(pk=link.pk).verified_at)
