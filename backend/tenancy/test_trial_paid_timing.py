import json
from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from .models import AuditEvent, AuditEventType, Organization, OrganizationMembership, PaddleCheckoutAttempt, PaddleFirstActiveObservation
from .paddle_checkout import mark_paddle_checkout_sending, reserve_paddle_checkout
from .paddle_jobs import execute_paddle_receipt
from .services import approve_organization_trial, create_organization, extend_organization_trial
from .trial_activation import inspect_trial_activation
from .trial_paid_timing import inspect_trial_paid_timing
from . import test_paddle_activation as activation_fixtures
from . import test_paddle_reconcile as fixtures
from .test_paddle_attempt import catalog
from .test_trial_corrections import staff_trial_request


@override_settings(**fixtures.SignedPaymentEvidenceTests._overridden_settings, DEBUG=True)
class TrialPaidTimingTests(TestCase):
    setUp = fixtures.SignedPaymentEvidenceTests.setUp
    provider_response = fixtures.SignedPaymentEvidenceTests.provider_response
    subscription_receipt = fixtures.SignedPaymentEvidenceTests.subscription_receipt
    subscription_response = fixtures.SignedPaymentEvidenceTests.subscription_response
    current = activation_fixtures.PaidActivationSourceTests.current
    signed = activation_fixtures.FirstActiveObservationTests.signed

    def inspect(self, **changes):
        return inspect_trial_paid_timing(**{**dict(organization=self.organization, actor=self.owner), **changes})

    def test_actual_trial_and_signed_worker_original_dates_digests_read_only_and_stable_after_renewal(self):
        trial = inspect_trial_activation(organization=self.organization, actor=self.owner)
        extend_organization_trial(organization=self.organization, actor=self.staff, reason="Synthetic extension before payment", request=staff_trial_request(self.staff))
        self.current()
        saved = PaddleFirstActiveObservation.objects.get(organization=self.organization)
        with patch("tenancy.paddle_transport.paddle_transaction_get", side_effect=AssertionError("No provider GET")), \
             patch("tenancy.paddle_transport.paddle_subscription_get", side_effect=AssertionError("No provider GET")), \
             CaptureQueriesContext(connection) as queries:
            result = self.inspect()
        self.assertEqual(result["state"], "recorded")
        self.assertEqual(result["trial_started_at"], trial["activation"]["started_at"])
        self.assertEqual(result["trial_source_digest"], trial["activation"]["source_digest"])
        self.assertEqual(result["paid_source_digest"], saved.source_digest)
        self.assertEqual(result["observed_at"], saved.observed_at.isoformat())
        self.assertEqual(result["elapsed_milliseconds"], (saved.observed_at - self.organization.trial.started_at) // timedelta(microseconds=1) // 1000)
        self.assertRegex(result["source_digest"], r"^[a-f0-9]{64}$")
        self.assertFalse(any(row["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"} for row in queries))
        self.assertNotRegex(json.dumps(result), "organization_id|actor_id|attempt_id|provider_occurred_at|ends_at|reason|customer_id")
        later = self.signed("z")
        self.assertEqual(execute_paddle_receipt(later.pk, subscription_get=lambda **_: self.subscription_response()), "succeeded")
        with override_settings(PADDLE_ENVIRONMENT="live", PADDLE_ENCRYPTION_KEYS=()):
            self.assertEqual(self.inspect(), result)
        self.assertEqual(PaddleFirstActiveObservation.objects.count(), 1)

    def test_genuine_later_staff_trial_approval_and_signed_worker_keep_the_actual_later_start(self):
        PaddleCheckoutAttempt.objects.filter(pk=self.attempt.pk).update(transaction_id="txn_" + "z" * 26)
        self.organization = create_organization(user=self.owner, name="Synthetic staff trial-paid timing")
        approved = approve_organization_trial(organization=self.organization, actor=self.staff, reason="Synthetic later organization", request=staff_trial_request(self.staff))
        self.attempt = reserve_paddle_checkout(organization=self.organization, actor=self.owner, request_key="staff-trial-paid-001")
        mark_paddle_checkout_sending(attempt=self.attempt, actor=self.owner, catalog_response=catalog())
        PaddleCheckoutAttempt.objects.filter(pk=self.attempt.pk).update(state="ready", transaction_id="txn_" + "c" * 26)
        self.current()
        result = self.inspect()
        self.assertEqual(result["state"], "recorded")
        self.assertEqual(result["activation_method"], "staff_approved")
        self.assertEqual(result["trial_started_at"], approved.started_at.isoformat())
        self.assertNotEqual(result["trial_started_at"], self.organization.created_at.isoformat())

    def test_unknown_pending_unobserved_sources_have_all_null_timing_and_never_capture(self):
        self.assertEqual(self.inspect()["state"], "not_observed")
        Organization.objects.filter(pk=self.organization.pk).update(paid_activation_tracking=None)
        self.assertEqual(self.inspect()["state"], "unknown")
        pending = create_organization(user=self.owner, name="Synthetic pending trial timing")
        result = self.inspect(organization=pending)
        self.assertEqual(result["state"], "unknown")
        for key in ("trial_started_at", "observed_at", "activation_method", "trial_source_digest", "paid_source_digest", "source_digest", "elapsed_milliseconds"):
            self.assertIsNone(result[key])
        self.assertEqual(PaddleFirstActiveObservation.objects.count(), 0)
        with self.assertRaises(PermissionDenied): self.inspect(organization=Organization.objects.create(name="Synthetic foreign timing"))

    def test_original_trial_or_paid_tamper_and_mid_read_owner_or_source_loss_deny(self):
        self.current()
        saved = PaddleFirstActiveObservation.objects.get(organization=self.organization)
        PaddleFirstActiveObservation.objects.filter(pk=saved.pk).update(observed_at=timezone.now() + timedelta(days=1))
        with self.assertRaises(ValidationError): self.inspect()
        PaddleFirstActiveObservation.objects.filter(pk=saved.pk).update(observed_at=saved.observed_at)
        def revoke(**kwargs):
            result = inspect_trial_activation(**kwargs)
            OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
            return result
        with patch("tenancy.trial_paid_timing.inspect_trial_activation", side_effect=revoke):
            with self.assertRaises(PermissionDenied): self.inspect()
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="owner")
        def remove(**kwargs):
            result = inspect_trial_activation(**kwargs)
            AuditEvent.objects.filter(organization=self.organization, event_type=AuditEventType.TRIAL_GRANTED).delete()
            return result
        with patch("tenancy.trial_paid_timing.inspect_trial_activation", side_effect=remove):
            with self.assertRaises(PermissionDenied): self.inspect()
        unknown = self.inspect()
        self.assertEqual(unknown["state"], "unknown")
        self.assertIsNone(unknown["elapsed_milliseconds"])

    def test_actual_owner_gets_original_trial_and_paid_timing_strictly_without_writes_or_identifiers(self):
        cache.clear()
        prefix = f"/api/organizations/{self.organization.pk}/billing/"
        trial_path, timing_path = prefix + "trial/activation/", prefix + "first-paid/trial-timing/"
        self.assertEqual(self.client.get(trial_path).status_code, 401)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(timing_path).json()["timing"]["state"], "not_observed")
        self.current()
        for path, key, expected in ((trial_path, "trial_activation", inspect_trial_activation(organization=self.organization, actor=self.owner)),
                                   (timing_path, "timing", self.inspect())):
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"organization_id": self.organization.pk, key: expected})
            self.assertEqual(response["Cache-Control"], "private, no-store")
            self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
            self.assertFalse(any(row["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"} for row in queries))
            self.assertEqual(self.client.get(path + "?history_kind=paid_timing").status_code, 400)
            self.assertEqual(self.client.generic("GET", path, data=b"{}", content_type="application/json").status_code, 400)
            denied = self.client.post(path)
            self.assertEqual(denied.status_code, 405)
            self.assertEqual(denied["Cache-Control"], "private, no-store")
            self.assertEqual(denied["X-Robots-Tag"], "noindex, nofollow")
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(trial_path).status_code, 404)
        self.assertEqual(self.client.get(timing_path).status_code, 404)
        self.client.force_login(self.owner)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="admin")
        self.assertEqual(self.client.get(trial_path).status_code, 403)
        self.assertEqual(self.client.get(timing_path).status_code, 403)

    def test_original_trial_and_both_paid_timing_reads_share_existing_read_budget_and_tamper_returns_generic_review(self):
        cache.clear()
        self.current()
        self.client.force_login(self.owner)
        prefix = f"/api/organizations/{self.organization.pk}/billing/"
        paths = [prefix + "trial/activation/", prefix + "first-paid/trial-timing/", prefix + "first-paid/timing/"]
        for index in range(60):
            self.assertEqual(self.client.get(paths[index % 3]).status_code, 200)
        for path in paths:
            self.assertEqual(self.client.get(path).status_code, 429)
        cache.clear()
        AuditEvent.objects.filter(organization=self.organization, event_type=AuditEventType.TRIAL_GRANTED).update(details={"reason": "PRIVATE_TRIAL_SOURCE"})
        for path in paths[:2]:
            result = self.client.get(path)
            self.assertEqual(result.status_code, 409)
            self.assertNotIn("PRIVATE_TRIAL_SOURCE", result.content.decode())
            self.assertEqual(result["Cache-Control"], "private, no-store")
