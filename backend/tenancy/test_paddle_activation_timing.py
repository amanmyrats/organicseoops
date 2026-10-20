import json
from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from .models import Organization, OrganizationMembership, PaddleFirstActiveObservation, PaddleSubscription
from .paddle_activation import inspect_first_active_observation, inspect_first_active_observation_timing
from . import test_paddle_activation as activation_fixtures
from . import test_paddle_reconcile as fixtures


@override_settings(**fixtures.SignedPaymentEvidenceTests._overridden_settings, DEBUG=True)
class FirstActiveTimingTests(TestCase):
    setUp = fixtures.SignedPaymentEvidenceTests.setUp
    provider_response = fixtures.SignedPaymentEvidenceTests.provider_response
    subscription_receipt = fixtures.SignedPaymentEvidenceTests.subscription_receipt
    subscription_response = fixtures.SignedPaymentEvidenceTests.subscription_response
    current = activation_fixtures.PaidActivationSourceTests.current
    signed = activation_fixtures.FirstActiveObservationTests.signed

    def timing(self, **changes):
        return inspect_first_active_observation_timing(**{**dict(organization=self.organization, actor=self.owner), **changes})

    def test_actual_signed_worker_original_historical_age_is_minimized_read_only_and_stable_after_current_loss(self):
        from .paddle_jobs import execute_paddle_receipt
        self.current()
        saved = PaddleFirstActiveObservation.objects.get(organization=self.organization)
        with patch("tenancy.paddle_transport.paddle_transaction_get", side_effect=AssertionError("No provider GET")), \
             patch("tenancy.paddle_transport.paddle_subscription_get", side_effect=AssertionError("No subscription GET")), \
             CaptureQueriesContext(connection) as queries:
            result = self.timing()
        self.assertFalse(any(row["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"} for row in queries))
        self.assertEqual(result["state"], "recorded")
        self.assertEqual(result["tracking_started_at"], saved.source["tracking_started_at"])
        self.assertEqual(result["observed_at"], saved.observed_at.isoformat())
        self.assertEqual(result["source_digest"], saved.source_digest)
        elapsed_us = (saved.observed_at - self.organization.created_at) // timedelta(microseconds=1)
        self.assertEqual(result["elapsed_milliseconds"], elapsed_us // 1000)
        self.assertNotRegex(json.dumps(result), "organization_id|attempt_id|actor_id|provider_occurred_at|customer_id|currency_code|transaction_id")
        later = self.signed("z")
        self.assertEqual(execute_paddle_receipt(later.pk, subscription_get=lambda **_: self.subscription_response()), "succeeded")
        self.assertEqual(self.timing(), result)
        PaddleSubscription.objects.filter(organization=self.organization).update(status="past_due")
        with override_settings(PADDLE_ENVIRONMENT="live", PADDLE_ENCRYPTION_KEYS=()):
            self.assertEqual(self.timing(), result)  # History grants no current access or reuse.
        self.assertEqual(PaddleFirstActiveObservation.objects.count(), 1)

    def test_unknown_and_unobserved_have_no_duration_foreign_owner_loss_and_original_source_tamper_deny(self):
        before = self.timing()
        self.assertEqual(before["state"], "not_observed")
        self.assertIsNone(before["elapsed_milliseconds"])
        Organization.objects.filter(pk=self.organization.pk).update(paid_activation_tracking=None)
        unknown = self.timing()
        self.assertEqual(unknown["state"], "unknown")
        for key in ("tracking_started_at", "observed_at", "source_digest", "elapsed_milliseconds"):
            self.assertIsNone(unknown[key])
        self.assertEqual(PaddleFirstActiveObservation.objects.count(), 0)
        foreign = Organization.objects.create(name="Foreign synthetic timing")
        with self.assertRaises(PermissionDenied): self.timing(organization=foreign)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="admin")
        with self.assertRaises(PermissionDenied): self.timing()

    def test_actual_historical_tamper_and_owner_revocation_during_read_never_return_timing(self):
        self.current()
        saved = PaddleFirstActiveObservation.objects.get(organization=self.organization)
        PaddleFirstActiveObservation.objects.filter(pk=saved.pk).update(observed_at=timezone.now() + timedelta(hours=1))
        with self.assertRaises(ValidationError): self.timing()
        PaddleFirstActiveObservation.objects.filter(pk=saved.pk).update(observed_at=saved.observed_at)
        def inspect_then_revoke(**kwargs):
            history = inspect_first_active_observation(**kwargs)
            OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
            return history
        with patch("tenancy.paddle_activation.inspect_first_active_observation", side_effect=inspect_then_revoke):
            with self.assertRaises(PermissionDenied): self.timing()

    def test_actual_owner_only_get_original_source_minimization_strict_input_and_shared_read_limit(self):
        cache.clear()
        path = f"/api/organizations/{self.organization.pk}/billing/first-paid/timing/"
        self.assertEqual(self.client.get(path).status_code, 401)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(path).json()["timing"]["state"], "not_observed")
        self.current()
        expected = self.timing()
        with CaptureQueriesContext(connection) as queries:
            result = self.client.get(path)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {"organization_id": self.organization.pk, "timing": expected})
        self.assertEqual(result["Cache-Control"], "private, no-store")
        self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")
        self.assertFalse(any(row["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"} for row in queries))
        self.assertEqual(self.client.get(path + "?extra=1").status_code, 400)
        self.assertEqual(self.client.generic("GET", path, data=b"{}", content_type="application/json").status_code, 400)
        self.assertEqual(self.client.post(path).status_code, 405)
        for _ in range(58): self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(self.client.get(path).status_code, 429)
        cache.clear()
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(path).status_code, 404)
        self.client.force_login(self.owner)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="admin")
        self.assertEqual(self.client.get(path).status_code, 403)
