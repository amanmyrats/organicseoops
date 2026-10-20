import json
from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from . import test_paddle_activation as activation_fixtures
from . import test_paddle_reconcile as fixtures
from .models import AuditEvent, AuditEventType, Organization, OrganizationMembership, PaddleCheckoutAttempt, PaddleFirstActiveObservation
from .paddle_activation import inspect_first_active_observation
from .paddle_checkout import mark_paddle_checkout_sending, reserve_paddle_checkout
from .paddle_jobs import execute_paddle_receipt
from .services import approve_organization_trial, create_organization, extend_organization_trial
from .test_paddle_attempt import catalog
from .test_paddle_webhooks import NOW
from .test_trial_corrections import staff_trial_request
from .trial_activation import inspect_trial_activation
from .trial_paid_window import WINDOW, inspect_trial_paid_window


@override_settings(**fixtures.SignedPaymentEvidenceTests._overridden_settings, DEBUG=True)
class OriginalTrialPaidWindowTests(TestCase):
    provider_response = fixtures.SignedPaymentEvidenceTests.provider_response
    subscription_receipt = fixtures.SignedPaymentEvidenceTests.subscription_receipt
    current = activation_fixtures.PaidActivationSourceTests.current
    signed = activation_fixtures.FirstActiveObservationTests.signed

    def setUp(self):
        # Actual service writes use one synthetic original clock; no historical source backfill/tamper.
        with patch("django.utils.timezone.now", return_value=NOW):
            fixtures.SignedPaymentEvidenceTests.setUp(self)
        self.started = self.organization.trial.started_at

    def subscription_response(self):
        now = timezone.now()
        return fixtures.SignedPaymentEvidenceTests.subscription_response(self, current_billing_period={
            "starts_at": (now - timedelta(days=1)).isoformat(), "ends_at": (now + timedelta(days=29)).isoformat()})

    def inspect(self, at=None, **changes):
        with patch("django.utils.timezone.now", return_value=at or self.started + WINDOW):
            return inspect_trial_paid_window(**{**dict(organization=self.organization, actor=self.owner), **changes})

    def test_actual_unobserved_tracking_matures_only_at_fixed_end_and_inspection_never_writes_or_contacts_provider(self):
        end = self.started + WINDOW
        before = self.inspect(end - timedelta(microseconds=1))
        self.assertEqual((before["state"], before["outcome"]), ("immature", None))
        with patch("socket.create_connection", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            result = self.inspect(end)
        self.assertEqual((result["state"], result["outcome"], result["window_days"]), ("mature", "not_observed_within_window", 37))
        self.assertEqual(result["window_ends_at"], end.isoformat())
        self.assertEqual(result["assessed_at"], end.isoformat())
        self.assertIsNone(result["paid_observed_at"])
        self.assertIsNone(result["paid_source_digest"])
        self.assertRegex(result["source_digest"], r"^[a-f0-9]{64}$")
        self.assertFalse(any(row["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"} for row in queries))
        self.assertNotRegex(json.dumps(result), "organization_id|actor_id|attempt_id|provider_occurred_at|reason|currency|rate\":")
        self.assertEqual(PaddleFirstActiveObservation.objects.count(), 0)

    def test_genuine_early_signed_payment_is_not_a_mature_outcome_and_extension_renewal_current_loss_do_not_reset_window(self):
        with patch("django.utils.timezone.now", return_value=self.started + timedelta(days=1)):
            extend_organization_trial(organization=self.organization, actor=self.staff, reason="Synthetic window extension", request=staff_trial_request(self.staff))
            self.current()
        immature = self.inspect(self.started + timedelta(days=2))
        self.assertEqual((immature["state"], immature["outcome"]), ("immature", None))
        assessed = self.started + WINDOW
        original = self.inspect(assessed)
        self.assertEqual(original["outcome"], "observed_within_window")
        self.assertEqual(original["paid_observed_at"], (self.started + timedelta(days=1)).isoformat())
        with patch("django.utils.timezone.now", return_value=assessed):
            later = self.signed("z")
            self.assertEqual(execute_paddle_receipt(later.pk, subscription_get=lambda **_: self.subscription_response()), "succeeded")
        with override_settings(PADDLE_ENVIRONMENT="live", PADDLE_ENCRYPTION_KEYS=()):
            self.assertEqual(self.inspect(assessed), original)
        self.assertEqual(PaddleFirstActiveObservation.objects.count(), 1)

    def test_actual_first_observation_one_microsecond_before_exact_end_or_later_preserves_half_open_boundary(self):
        with patch("django.utils.timezone.now", return_value=self.started + WINDOW - timedelta(microseconds=1)):
            self.current()
        self.assertEqual(self.inspect()["outcome"], "observed_within_window")

    def test_actual_exact_end_first_observation_is_outside_without_inferred_provider_activation_or_lifetime_absence(self):
        end = self.started + WINDOW
        with patch("django.utils.timezone.now", return_value=end):
            self.current()
        result = self.inspect(end + timedelta(days=1))
        self.assertEqual(result["outcome"], "not_observed_within_window")
        self.assertEqual(result["paid_observed_at"], end.isoformat())
        self.assertRegex(result["paid_source_digest"], r"^[a-f0-9]{64}$")
        self.assertIn("not_provider_activation_or_conversion_rate", result["interpretation"])

    def test_actual_later_first_observation_stays_outside_and_assessment_is_frozen_when_read_crosses_maturity(self):
        end = self.started + WINDOW
        calls = 0
        def advancing_clock():
            nonlocal calls
            calls += 1
            return end - timedelta(microseconds=1) if calls == 1 else end + timedelta(microseconds=1)
        with patch("django.utils.timezone.now", side_effect=advancing_clock):
            result = inspect_trial_paid_window(organization=self.organization, actor=self.owner)
        self.assertEqual((result["state"], result["outcome"], result["assessed_at"]),
                         ("immature", None, (end - timedelta(microseconds=1)).isoformat()))
        with patch("django.utils.timezone.now", return_value=end + timedelta(microseconds=1)):
            self.current()
        result = self.inspect(end + timedelta(days=1))
        self.assertEqual(result["outcome"], "not_observed_within_window")
        self.assertEqual(result["paid_observed_at"], (end + timedelta(microseconds=1)).isoformat())

    def test_actual_staff_approval_starts_its_own_window_and_pending_unknown_sources_have_no_outcome_or_original_fields(self):
        with patch("django.utils.timezone.now", return_value=self.started + timedelta(days=4)):
            later = create_organization(user=self.owner, name="Synthetic later window")
        fields = ("trial_started_at", "window_ends_at", "paid_observed_at", "trial_source_digest", "paid_source_digest", "source_digest", "outcome")
        pending = self.inspect(organization=later)
        self.assertEqual(pending["state"], "unknown")
        self.assertTrue(all(pending[key] is None for key in fields))
        with patch("django.utils.timezone.now", return_value=self.started + timedelta(days=5)):
            approved = approve_organization_trial(organization=later, actor=self.staff, reason="Synthetic later start", request=staff_trial_request(self.staff))
        result = self.inspect(approved.started_at + WINDOW - timedelta(microseconds=1), organization=later)
        self.assertEqual(result["state"], "immature")
        self.assertEqual(result["window_ends_at"], (approved.started_at + WINDOW).isoformat())
        self.assertEqual(self.inspect(approved.started_at + WINDOW, organization=later)["state"], "mature")
        Organization.objects.filter(pk=later.pk).update(paid_activation_tracking=None)
        unknown = self.inspect(approved.started_at + WINDOW, organization=later)
        self.assertEqual(unknown["state"], "unknown")
        self.assertTrue(all(unknown[key] is None for key in fields))
        self.assertEqual(PaddleFirstActiveObservation.objects.count(), 0)
        # Genuine staff approval then signed paid reconciliation uses the later start, not organization birth.
        from .paddle_activation import OBSERVATION_METHOD
        Organization.objects.filter(pk=later.pk).update(paid_activation_tracking=OBSERVATION_METHOD)
        PaddleCheckoutAttempt.objects.filter(pk=self.attempt.pk).update(transaction_id="txn_" + "z" * 26)
        self.organization = later
        with patch("django.utils.timezone.now", return_value=approved.started_at + timedelta(days=1)):
            self.attempt = reserve_paddle_checkout(organization=later, actor=self.owner, request_key="staff-window-paid-001")
            mark_paddle_checkout_sending(attempt=self.attempt, actor=self.owner, catalog_response=catalog())
            PaddleCheckoutAttempt.objects.filter(pk=self.attempt.pk).update(state="ready", transaction_id="txn_" + "c" * 26)
            self.current()
        result = self.inspect(approved.started_at + WINDOW)
        self.assertEqual(result["trial_started_at"], approved.started_at.isoformat())
        self.assertEqual(result["outcome"], "observed_within_window")

    def test_foreign_tamper_and_mid_read_trial_paid_or_owner_loss_deny_without_returning_stale_mature_outcomes(self):
        with self.assertRaises(PermissionDenied):
            self.inspect(organization=Organization.objects.create(name="Synthetic foreign window"))
        with patch("django.utils.timezone.now", return_value=self.started + timedelta(days=1)):
            self.current()
        saved = PaddleFirstActiveObservation.objects.get(organization=self.organization)
        PaddleFirstActiveObservation.objects.filter(pk=saved.pk).update(observed_at=self.started - timedelta(microseconds=1))
        with self.assertRaises(ValidationError): self.inspect()
        PaddleFirstActiveObservation.objects.filter(pk=saved.pk).update(observed_at=saved.observed_at)
        def paid_then_change(**kwargs):
            result = inspect_first_active_observation(**kwargs)
            PaddleFirstActiveObservation.objects.filter(pk=saved.pk).update(observed_at=saved.observed_at + timedelta(microseconds=1))
            return result
        with patch("tenancy.trial_paid_window.inspect_first_active_observation", side_effect=paid_then_change):
            with self.assertRaises(ValidationError): self.inspect()
        PaddleFirstActiveObservation.objects.filter(pk=saved.pk).update(observed_at=saved.observed_at)
        def trial_then_revoke(**kwargs):
            result = inspect_trial_activation(**kwargs)
            OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="admin")
            return result
        with patch("tenancy.trial_paid_window.inspect_trial_activation", side_effect=trial_then_revoke):
            with self.assertRaises(PermissionDenied): self.inspect()
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="owner")
        def trial_then_remove(**kwargs):
            result = inspect_trial_activation(**kwargs)
            AuditEvent.objects.filter(organization=self.organization, event_type=AuditEventType.TRIAL_GRANTED).delete()
            return result
        with patch("tenancy.trial_paid_window.inspect_trial_activation", side_effect=trial_then_remove):
            with self.assertRaises(PermissionDenied): self.inspect()

    def test_actual_fixed_owner_window_get_is_strict_read_only_minimized_and_role_scoped(self):
        cache.clear()
        path = f"/api/organizations/{self.organization.pk}/billing/first-paid/trial-window/"
        self.assertEqual(self.client.get(path).status_code, 401)
        assessed = self.started + WINDOW
        with patch("django.utils.timezone.now", return_value=assessed):
            self.client.force_login(self.owner)
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"organization_id": self.organization.pk, "window": self.inspect(assessed)})
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertFalse(any(row["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"} for row in queries))
        self.assertNotIn(self.owner.email, response.content.decode())
        for status, result in (
            (400, self.client.get(path + "?history_kind=paid_timing")),
            (400, self.client.generic("GET", path, data=b"{}", content_type="application/json")),
            (400, self.client.get("/api/organizations/9007199254740992/billing/first-paid/trial-window/")),
            (405, self.client.post(path)),
        ):
            self.assertEqual(result.status_code, status)
            self.assertEqual(result["Cache-Control"], "private, no-store")
            self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(path).status_code, 404)
        self.client.force_login(self.owner)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="admin")
        self.assertEqual(self.client.get(path).status_code, 403)

    def test_window_shares_actual_history_read_budget_and_unknown_or_tampered_originals_never_become_false_outcomes(self):
        cache.clear()
        self.client.force_login(self.owner)
        prefix = f"/api/organizations/{self.organization.pk}/billing/"
        paths = [prefix + "trial/activation/", prefix + "first-paid/timing/", prefix + "first-paid/trial-timing/", prefix + "first-paid/trial-window/"]
        for index in range(60):
            self.assertEqual(self.client.get(paths[index % 4]).status_code, 200)
        for path in paths:
            self.assertEqual(self.client.get(path).status_code, 429)
        cache.clear()
        Organization.objects.filter(pk=self.organization.pk).update(paid_activation_tracking=None)
        response = self.client.get(paths[-1])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["window"]["state"], "unknown")
        self.assertIsNone(response.json()["window"]["outcome"])
        AuditEvent.objects.filter(organization=self.organization, event_type=AuditEventType.TRIAL_GRANTED).update(details={"reason": "PRIVATE_WINDOW_SOURCE"})
        response = self.client.get(paths[-1])
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("PRIVATE_WINDOW_SOURCE", response.content.decode())
        self.assertEqual(response["Cache-Control"], "private, no-store")
