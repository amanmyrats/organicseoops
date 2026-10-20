from datetime import timedelta
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import (AuditEvent, AuditEventType, Organization, OrganizationBillingCancellation,
                     PaddleStatus, PaddleSubscription)
from .paddle_cancellation import (execute_billing_cancellation, prepare_billing_cancellation,
                                  reconcile_billing_cancellation)
from .paddle_transport import PaddleTransportError
from .services import create_organization
from .test_paddle_seller import SANDBOX_KEY


@override_settings(PADDLE_ENVIRONMENT="sandbox")
class ClosureBillingCancellationTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("billing-closure@example.invalid", password="test-password")
        EmailAddress.objects.create(user=self.owner, email=self.owner.email, primary=True, verified=True)
        self.organization = create_organization(user=self.owner, name="Closure billing fixture")
        now = timezone.now()
        self.subscription = PaddleSubscription.objects.create(organization=self.organization,
            environment="sandbox", customer_id="ctm_" + "a" * 26, subscription_id="sub_" + "b" * 26,
            status=PaddleStatus.ACTIVE, verified_at=now - timedelta(days=1),
            period_starts_at=now - timedelta(days=1), period_ends_at=now + timedelta(days=29),
            currency_code="USD")

    def _close_fixture(self):
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=timezone.now())

    def _observed(self):
        return {"data": {"id": self.subscription.subscription_id, "customer_id": self.subscription.customer_id,
                         "status": "canceled", "canceled_at": timezone.now().isoformat()}}

    @patch("tenancy.paddle_cancellation.paddle_seller_secrets", return_value=(SANDBOX_KEY, "unused"))
    def test_immediate_cancel_marks_one_attempt_before_post_and_does_not_replay(self, _secrets):
        prepared = prepare_billing_cancellation(organization=self.organization, actor=self.owner)
        self.assertEqual(prepare_billing_cancellation(organization=self.organization, actor=self.owner).pk, prepared.pk)
        self.assertEqual(prepared.state, prepared.State.RESERVED)
        self.assertEqual(AuditEvent.objects.filter(organization=self.organization,
            event_type=AuditEventType.BILLING_CANCELLATION_PREPARED).count(), 1)
        self.assertEqual(execute_billing_cancellation(prepared, cancel=lambda **_: self.fail("Cannot call before closure")).state,
                         prepared.State.RESERVED)
        self._close_fixture()
        seen = []

        def cancel(*, attempt, api_key):
            attempt.refresh_from_db()
            seen.append((attempt.state, attempt.attempted_at is not None, api_key))
            return self._observed()

        confirmed = execute_billing_cancellation(prepared, cancel=cancel)
        self.assertEqual(confirmed.state, confirmed.State.CONFIRMED)
        self.assertEqual(seen, [(prepared.State.SENDING, True, SANDBOX_KEY)])
        self.assertEqual(execute_billing_cancellation(prepared,
            cancel=lambda **_: self.fail("Never re-POST after provider attempt")).state, prepared.State.CONFIRMED)
        self.assertEqual(OrganizationBillingCancellation.objects.count(), 1)
        for event in (AuditEventType.BILLING_CANCELLATION_ATTEMPTED,
                      AuditEventType.BILLING_CANCELLATION_CONFIRMED):
            self.assertEqual(AuditEvent.objects.filter(organization=self.organization, event_type=event).count(), 1)
        self.assertNotIn(SANDBOX_KEY, str(list(AuditEvent.objects.filter(organization=self.organization)
                                              .values_list("details", flat=True))))

    @patch("tenancy.paddle_cancellation.paddle_seller_secrets", return_value=(SANDBOX_KEY, "unused"))
    def test_unknown_outcome_requires_get_and_never_reposts(self, _secrets):
        attempt = prepare_billing_cancellation(organization=self.organization, actor=self.owner)
        self._close_fixture()

        def timeout(**_):
            raise PaddleTransportError("timeout")

        unknown = execute_billing_cancellation(attempt, cancel=timeout)
        self.assertEqual((unknown.state, unknown.error_category), (unknown.State.UNKNOWN, "timeout"))
        self.assertEqual(execute_billing_cancellation(unknown,
            cancel=lambda **_: self.fail("No automatic retry after timeout")).state, unknown.State.UNKNOWN)
        unresolved = reconcile_billing_cancellation(unknown, subscription_get=lambda **_: {"data": {
            "id": self.subscription.subscription_id, "customer_id": self.subscription.customer_id,
            "status": "active", "canceled_at": None}})
        self.assertEqual(unresolved.state, unresolved.State.UNKNOWN)
        foreign = reconcile_billing_cancellation(unknown, subscription_get=lambda **_: {"data": {
            **self._observed()["data"], "customer_id": "ctm_" + "z" * 26}})
        self.assertEqual(foreign.state, foreign.State.UNKNOWN)
        confirmed = reconcile_billing_cancellation(unknown, subscription_get=lambda **_: self._observed())
        self.assertEqual(confirmed.state, confirmed.State.CONFIRMED)
        self.assertEqual(reconcile_billing_cancellation(attempt,
            subscription_get=lambda **_: self.fail("No network after confirmation")).state, confirmed.State.CONFIRMED)
        self.assertEqual(AuditEvent.objects.filter(organization=self.organization,
            event_type=AuditEventType.BILLING_CANCELLATION_ATTEMPTED).count(), 1)

    @patch("tenancy.paddle_cancellation.paddle_seller_secrets", side_effect=ValidationError("Unavailable"))
    def test_missing_seller_does_not_create_attempt_or_close_customer(self, _secrets):
        with self.assertRaises(ValidationError):
            prepare_billing_cancellation(organization=self.organization, actor=self.owner)
        self.assertFalse(OrganizationBillingCancellation.objects.exists())
        self.organization.refresh_from_db()
        self.assertIsNone(self.organization.closed_at)

    def test_tenant_subscription_and_state_constraints_are_database_backed(self):
        second = get_user_model().objects.create_user("second-closure@example.invalid", password="test-password")
        EmailAddress.objects.create(user=second, email=second.email, primary=True, verified=True)
        other_org = create_organization(user=second, name="Independent fixture")
        with self.assertRaises(ValidationError):
            OrganizationBillingCancellation.objects.create(organization=other_org, subscription=self.subscription,
                actor=second, environment="sandbox", customer_id=self.subscription.customer_id,
                provider_subscription_id=self.subscription.subscription_id)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OrganizationBillingCancellation.objects.bulk_create([OrganizationBillingCancellation(
                    organization=self.organization, subscription=self.subscription, actor=self.owner,
                    environment="sandbox", customer_id=self.subscription.customer_id,
                    provider_subscription_id=self.subscription.subscription_id, state="confirmed")])
