import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.test import Client, RequestFactory, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from . import test_paddle_reconcile as fixtures
from .models import (AuditEvent, AuditEventType, Organization, OrganizationMembership,
                     PaddleCheckoutAttempt, PaddleFirstActiveObservation,
                     PaddleSellerConfiguration, PaddleSubscription, PaddleWebhookReceipt)
from .paddle_activation import _current_active_source, paid_activation_source
from .paddle_jobs import execute_paddle_receipt
from .test_paddle_seller import SANDBOX_KEY


@override_settings(**fixtures.SignedPaymentEvidenceTests._overridden_settings, DEBUG=True)
class PaidActivationSourceTests(TestCase):
    setUp = fixtures.SignedPaymentEvidenceTests.setUp
    provider_response = fixtures.SignedPaymentEvidenceTests.provider_response
    subscription_receipt = fixtures.SignedPaymentEvidenceTests.subscription_receipt
    subscription_response = fixtures.SignedPaymentEvidenceTests.subscription_response

    def current(self):
        self.assertEqual(execute_paddle_receipt(self.receipt.pk, transaction_get=lambda **_: self.provider_response()), "succeeded")
        receipt = self.subscription_receipt()
        self.assertEqual(execute_paddle_receipt(receipt.pk, subscription_get=lambda **_: self.subscription_response()), "succeeded")
        return receipt

    def source(self, receipt, **changes):
        return paid_activation_source(**{**dict(organization=self.organization, actor=self.owner,
            attempt_id=self.attempt.pk, receipt_id=receipt.pk), **changes})

    def test_real_successful_signed_worker_source_is_read_only_current_eligibility_not_first_ever_activation(self):
        receipt = self.current()
        with patch("tenancy.paddle_transport.paddle_transaction_get", side_effect=AssertionError("No provider GET")), patch(
            "tenancy.paddle_transport.paddle_subscription_get", side_effect=AssertionError("No subscription GET")), patch(
            "tenancy.paddle_transport.paddle_transaction_create", side_effect=AssertionError("No provider POST")), CaptureQueriesContext(connection) as queries:
            source = self.source(receipt)
        self.assertFalse(any(row["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"} for row in queries))
        self.assertEqual(source["attempt_id"], self.attempt.pk)
        self.assertEqual(source["subscription_receipt"]["id"], receipt.pk)
        self.assertEqual(source["payment_receipt"]["id"], self.receipt.pk)
        self.assertFalse(source["first_paid_activation_confirmed"])
        self.assertIn("not_first_ever", source["interpretation"])
        self.assertNotIn(SANDBOX_KEY, json.dumps(source))
        for private in ("client_token", "raw_body", "encrypted_api_key", "proof"):
            self.assertNotIn(private, source)
        self.assertNotEqual(source["subscription_verified_at"], source["subscription_receipt"]["occurred_at"])
        from .acquisition import acquisition_milestones
        self.assertEqual(acquisition_milestones()["milestones"]["paid_activation_confirmed"], {"grain": "organization", "count": 1, "state": "derivable"})
        for value in (True, 0, 2**53, "1"):
            for field in ("attempt_id", "receipt_id"):
                with self.assertRaises(ValidationError): self.source(receipt, **{field: value})
        with self.assertRaises(PermissionDenied): self.source(receipt, receipt_id=self.receipt.pk)
        admin = get_user_model().objects.create_user("activation-admin@example.invalid", "test-password")
        OrganizationMembership.objects.create(organization=self.organization, user=admin, role="admin")
        with self.assertRaises(PermissionDenied): self.source(receipt, actor=admin)
        with self.assertRaises(PermissionDenied): self.source(receipt, actor=self.staff)
        foreign = Organization.objects.create(name="Foreign synthetic payer")
        with self.assertRaises(PermissionDenied): self.source(receipt, organization=foreign)
        with override_settings(PADDLE_ENVIRONMENT="live"), self.assertRaises(PermissionDenied): self.source(receipt)
        with override_settings(PADDLE_ENCRYPTION_KEYS=()), self.assertRaises(PermissionDenied): self.source(receipt)

    def test_unpaid_unsucceeded_stale_audit_identity_catalog_adverse_date_and_current_role_loss_are_denied(self):
        receipt = self.subscription_receipt()
        with self.assertRaises(PermissionDenied): self.source(receipt)
        self.assertEqual(execute_paddle_receipt(self.receipt.pk, transaction_get=lambda **_: self.provider_response()), "succeeded")
        self.assertEqual(execute_paddle_receipt(receipt.pk, subscription_get=lambda **_: self.subscription_response()), "succeeded")
        subscription = PaddleSubscription.objects.get(organization=self.organization)
        seller = PaddleSellerConfiguration.objects.get(environment="sandbox")
        changes = [
            (PaddleSubscription, subscription.pk, {"status": "past_due"}),
            (PaddleSubscription, subscription.pk, {"refunded_at": timezone.now()}),
            (PaddleSubscription, subscription.pk, {"disputed_at": timezone.now()}),
            (PaddleSubscription, subscription.pk, {"period_ends_at": timezone.now() - timedelta(hours=1)}),
            (PaddleSubscription, subscription.pk, {"customer_id": "ctm_" + "z" * 26}),
            (PaddleSubscription, subscription.pk, {"verified_at": timezone.now() + timedelta(hours=1)}),
            (PaddleSellerConfiguration, seller.pk, {"price_id": "pri_" + "z" * 26}),
            (PaddleSellerConfiguration, seller.pk, {"rotated_at": timezone.now() + timedelta(hours=1)}),
            (PaddleWebhookReceipt, receipt.pk, {"state": "failed", "error_category": "identity_review"}),
            (PaddleWebhookReceipt, self.receipt.pk, {"state": "failed", "error_category": "identity_review"}),
            (PaddleWebhookReceipt, receipt.pk, {"processed_at": timezone.now() + timedelta(hours=1)}),
            (PaddleCheckoutAttempt, self.attempt.pk, {"paid_subscription_id": "sub_" + "z" * 26}),
        ]
        for model, pk, update in changes:
            original = model.objects.get(pk=pk)
            model.objects.filter(pk=pk).update(**update)
            with self.assertRaises((PermissionDenied, ValidationError)): self.source(receipt)
            model.objects.filter(pk=pk).update(**{field: getattr(original, field) for field in update})
        audit = AuditEvent.objects.get(organization=self.organization, event_type=AuditEventType.BILLING_SUBSCRIPTION_RECONCILED)
        AuditEvent.objects.filter(pk=audit.pk).update(details={**audit.details, "event_id": "evt_" + "z" * 26})
        with self.assertRaises(PermissionDenied): self.source(receipt)
        AuditEvent.objects.filter(pk=audit.pk).update(details=audit.details)
        def source_then_revoke(**kwargs):
            source = _current_active_source(**kwargs)
            OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="admin")
            return source
        with patch("tenancy.paddle_activation._current_active_source", side_effect=source_then_revoke), self.assertRaises(PermissionDenied): self.source(receipt)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="owner")
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=timezone.now())
        with self.assertRaises(PermissionDenied): self.source(receipt)

    def test_actual_later_subscription_reconciliation_displaces_old_source_and_pending_signed_adverse_denies_current(self):
        from .paddle_webhooks import record_paddle_notification
        from .test_paddle_webhooks import NOW, header
        original = self.current()
        raw = json.dumps({"event_id": "evt_" + "z" * 26, "notification_id": "ntf_" + "z" * 26,
            "event_type": "subscription.updated", "occurred_at": NOW.isoformat(),
            "data": {"id": "sub_" + "e" * 26}}, separators=(",", ":")).encode()
        latest, _ = record_paddle_notification(environment="sandbox", raw_body=raw, signature=header(raw), now=NOW)
        self.assertEqual(execute_paddle_receipt(latest.pk, subscription_get=lambda **_: self.subscription_response()), "succeeded")
        with self.assertRaises(PermissionDenied): self.source(original)
        source = self.source(latest)
        self.assertEqual(source["subscription_receipt"]["id"], latest.pk)
        self.assertFalse(source["first_paid_activation_confirmed"])
        raw = json.dumps({"event_id": "evt_" + "h" * 26, "notification_id": "ntf_" + "h" * 26,
            "event_type": "transaction.payment_failed", "occurred_at": NOW.isoformat(),
            "data": {"id": "txn_" + "h" * 26, "subscription_id": "sub_" + "e" * 26,
                     "customer_id": "ctm_" + "d" * 26}}, separators=(",", ":")).encode()
        adverse, _ = record_paddle_notification(environment="sandbox", raw_body=raw, signature=header(raw), now=NOW)
        self.assertEqual(adverse.state, "pending")
        with self.assertRaises(PermissionDenied): self.source(latest)


@override_settings(**fixtures.SignedPaymentEvidenceTests._overridden_settings, DEBUG=True)
class FirstActiveObservationTests(TransactionTestCase):
    setUp = fixtures.SignedPaymentEvidenceTests.setUp
    provider_response = fixtures.SignedPaymentEvidenceTests.provider_response
    subscription_receipt = fixtures.SignedPaymentEvidenceTests.subscription_receipt
    subscription_response = fixtures.SignedPaymentEvidenceTests.subscription_response
    current = PaidActivationSourceTests.current

    def signed(self, letter, event_type="subscription.updated", entity_id=None, **data):
        from .paddle_webhooks import record_paddle_notification
        from .test_paddle_webhooks import NOW, header
        raw = json.dumps({"event_id": "evt_" + letter * 26, "notification_id": "ntf_" + letter * 26,
            "event_type": event_type, "occurred_at": (NOW - timedelta(days=2)).isoformat(),
            "data": {"id": entity_id or "sub_" + "e" * 26, **data}}, separators=(",", ":")).encode()
        return record_paddle_notification(environment="sandbox", raw_body=raw, signature=header(raw), now=NOW)[0]

    def paid(self):
        self.assertEqual(execute_paddle_receipt(self.receipt.pk, transaction_get=lambda **_: self.provider_response()), "succeeded")

    def test_birth_only_and_atomic_signed_worker_set_once_server_time_with_original_provider_dates(self):
        from .paddle_checkout_delivery import checkout_source_digest
        receipt = self.current()
        observation = PaddleFirstActiveObservation.objects.get(organization=self.organization)
        receipt.refresh_from_db()
        self.assertEqual(observation.observed_at, receipt.processed_at)
        self.assertEqual(observation.receipt_id, receipt.pk)
        self.assertEqual(observation.source_digest, checkout_source_digest(observation.source))
        self.assertNotEqual(observation.source["reconciliation_receipt"]["occurred_at"], observation.observed_at.isoformat())
        self.assertEqual(observation.source["tracking_started_at"], self.organization.created_at.isoformat())
        self.assertEqual(observation.source["payment_receipt"]["id"], self.receipt.pk)
        self.assertNotIn(SANDBOX_KEY, json.dumps(observation.source))
        with self.assertRaises(ValidationError): observation.save()
        with patch("tenancy.paddle_transport.paddle_subscription_get", side_effect=AssertionError("No replay")):
            self.assertEqual(execute_paddle_receipt(receipt.pk), "succeeded")
        later = self.signed("z")  # Earlier provider occurrence never rewrites first committed server observation.
        self.assertEqual(execute_paddle_receipt(later.pk, subscription_get=lambda **_: self.subscription_response()), "succeeded")
        observation.refresh_from_db()
        self.assertEqual(observation.receipt_id, receipt.pk)
        self.assertEqual(PaddleFirstActiveObservation.objects.count(), 1)
        legacy = Organization.objects.create(name="Unknown manager-created organization")
        self.assertIsNone(legacy.paid_activation_tracking)
        legacy.paid_activation_tracking = "first-active-observation-v1"
        with self.assertRaises(ValidationError): legacy.save()

    def test_legacy_null_and_unfenced_prior_active_stay_unknown_after_real_later_worker(self):
        from .paddle_reconcile import record_current_subscription_receipt
        self.paid()
        receipt = self.subscription_receipt()
        record_current_subscription_receipt(receipt=receipt, provider_response=self.subscription_response())
        self.organization.refresh_from_db()
        self.assertIsNone(self.organization.paid_activation_tracking)
        self.assertEqual(execute_paddle_receipt(receipt.pk, subscription_get=lambda **_: self.subscription_response()), "succeeded")
        later = self.signed("z")
        self.assertEqual(execute_paddle_receipt(later.pk, subscription_get=lambda **_: self.subscription_response()), "succeeded")
        self.assertFalse(PaddleFirstActiveObservation.objects.exists())

    def test_failed_atomic_capture_rolls_back_subscription_audit_and_success_and_read_retry_can_capture(self):
        self.paid()
        receipt = self.subscription_receipt()
        with patch("tenancy.paddle_activation.PaddleFirstActiveObservation.objects.create",
                   side_effect=ValidationError("Synthetic failed atomic persistence")):
            self.assertEqual(execute_paddle_receipt(receipt.pk, subscription_get=lambda **_: self.subscription_response()), "failed")
        receipt.refresh_from_db()
        self.assertEqual(receipt.state, "failed")
        self.assertIsNone(receipt.processed_at)
        self.assertFalse(PaddleSubscription.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.BILLING_SUBSCRIPTION_RECONCILED).exists())
        self.assertFalse(PaddleFirstActiveObservation.objects.exists())
        PaddleWebhookReceipt.objects.filter(pk=receipt.pk).update(retry_after=timezone.now() - timedelta(seconds=1))
        self.assertEqual(execute_paddle_receipt(receipt.pk, subscription_get=lambda **_: self.subscription_response()), "succeeded")
        self.assertEqual(PaddleFirstActiveObservation.objects.get().receipt_id, receipt.pk)

    def test_lost_claim_same_attempt_count_new_claim_time_cannot_mutate_subscription_or_finalize_new_worker(self):
        self.paid()
        receipt = self.subscription_receipt()
        def replace_claim(**_):
            PaddleWebhookReceipt.objects.filter(pk=receipt.pk).update(claimed_at=timezone.now() + timedelta(seconds=1))
            return self.subscription_response()
        self.assertEqual(execute_paddle_receipt(receipt.pk, subscription_get=replace_claim), "unavailable")
        self.assertFalse(PaddleSubscription.objects.exists())
        self.assertFalse(PaddleFirstActiveObservation.objects.exists())
        receipt.refresh_from_db()
        self.assertEqual((receipt.state, receipt.attempts), ("processing", 1))

    def test_unpaid_foreign_nonactive_and_expired_results_never_capture_or_allow_later_reconstruction(self):
        receipt = self.subscription_receipt()
        self.assertEqual(execute_paddle_receipt(receipt.pk, subscription_get=lambda **_: self.subscription_response()), "failed")
        self.paid()  # Genuine payment requeues the waiting dependency.
        response = self.subscription_response(customer_id="ctm_" + "z" * 26)
        self.assertEqual(execute_paddle_receipt(receipt.pk, subscription_get=lambda **_: response), "failed")
        self.assertFalse(PaddleFirstActiveObservation.objects.exists())
        PaddleWebhookReceipt.objects.filter(pk=receipt.pk).update(retry_after=timezone.now() - timedelta(seconds=1))
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="admin")
        self.assertEqual(execute_paddle_receipt(receipt.pk, subscription_get=lambda **_: self.subscription_response(status="past_due")), "succeeded")
        self.assertFalse(PaddleFirstActiveObservation.objects.exists())
        expired = self.signed("x")
        response = self.subscription_response(current_billing_period={
            "starts_at": (timezone.now() - timedelta(days=40)).isoformat(),
            "ends_at": (timezone.now() - timedelta(days=10)).isoformat()})
        self.assertEqual(execute_paddle_receipt(expired.pk, subscription_get=lambda **_: response), "succeeded")
        self.assertFalse(PaddleFirstActiveObservation.objects.exists())
        recovered = self.signed("y")
        self.assertEqual(execute_paddle_receipt(recovered.pk, subscription_get=lambda **_: self.subscription_response()), "succeeded")
        self.assertFalse(PaddleFirstActiveObservation.objects.exists())
        self.assertIsNone(Organization.objects.get(pk=self.organization.pk).paid_activation_tracking)
        from .billing_state import paid_access_state
        self.assertEqual(paid_access_state(PaddleSubscription.objects.get()), "paid_active")

    def test_prior_active_without_capture_from_old_worker_cutover_remains_unknown_on_later_current_worker(self):
        self.paid()
        receipt = self.subscription_receipt()
        with patch("tenancy.paddle_activation.capture_first_active_observation", return_value=None):
            self.assertEqual(execute_paddle_receipt(receipt.pk, subscription_get=lambda **_: self.subscription_response()), "succeeded")
        self.assertFalse(PaddleFirstActiveObservation.objects.exists())
        later = self.signed("z")
        self.assertEqual(execute_paddle_receipt(later.pk, subscription_get=lambda **_: self.subscription_response()), "succeeded")
        self.assertFalse(PaddleFirstActiveObservation.objects.exists())
        self.assertIsNone(Organization.objects.get(pk=self.organization.pk).paid_activation_tracking)

    def test_current_role_loss_does_not_gate_atomic_server_active_observation_or_change_entitlement(self):
        self.paid()
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="admin")
        receipt = self.subscription_receipt()
        self.assertEqual(execute_paddle_receipt(receipt.pk, subscription_get=lambda **_: self.subscription_response()), "succeeded")
        self.assertEqual(PaddleFirstActiveObservation.objects.get().receipt_id, receipt.pk)

    def test_genuine_renewal_failure_recovery_and_new_period_do_not_reset_observation(self):
        self.current()
        before = PaddleFirstActiveObservation.objects.get()
        fixtures.SignedPaymentEvidenceTests.test_signed_renewal_failure_and_recovery_use_current_provider_state(self)
        after = PaddleFirstActiveObservation.objects.get()
        self.assertEqual((after.pk, after.source, after.observed_at), (before.pk, before.source, before.observed_at))

    def test_genuine_recurring_reconciliation_can_supply_first_active_observation_after_initial_past_due(self):
        from .test_paddle_attempt import PRICE, PRODUCT
        self.paid()
        receipt = self.subscription_receipt()
        self.assertEqual(execute_paddle_receipt(receipt.pk,
            subscription_get=lambda **_: self.subscription_response(status="past_due")), "succeeded")
        self.assertFalse(PaddleFirstActiveObservation.objects.exists())
        recovered = self.signed("x", "transaction.completed", "txn_" + "x" * 26,
            subscription_id="sub_" + "e" * 26, customer_id="ctm_" + "d" * 26)
        renewal = {"data": {"id": recovered.entity_id, "status": "completed", "origin": "subscription_recurring",
            "subscription_id": "sub_" + "e" * 26, "customer_id": "ctm_" + "d" * 26,
            "currency_code": "USD", "collection_mode": "automatic",
            "items": [{"quantity": 1, "price": {"id": PRICE, "product_id": PRODUCT}}]}}
        self.assertEqual(execute_paddle_receipt(recovered.pk, transaction_get=lambda **_: renewal,
            subscription_get=lambda **_: self.subscription_response()), "succeeded")
        saved = PaddleFirstActiveObservation.objects.get()
        self.assertEqual(saved.receipt_id, recovered.pk)
        self.assertEqual(saved.source["reconciliation_receipt"]["event_type"], "transaction.completed")

    def test_historical_null_worker_remains_unknown(self):
        self.paid()
        Organization.objects.filter(pk=self.organization.pk).update(paid_activation_tracking=None)
        receipt = self.subscription_receipt()
        self.assertEqual(execute_paddle_receipt(receipt.pk, subscription_get=lambda **_: self.subscription_response()), "succeeded")
        self.assertFalse(PaddleFirstActiveObservation.objects.exists())
        self.assertIsNone(Organization.objects.get(pk=self.organization.pk).paid_activation_tracking)

    def test_missing_payment_proof_leaves_billing_active_but_uncaptured_coverage_unknown(self):
        self.paid()
        audit = AuditEvent.objects.get(event_type=AuditEventType.BILLING_PAYMENT_VERIFIED)
        AuditEvent.objects.filter(pk=audit.pk).update(details={**audit.details, "event_id": "evt_" + "z" * 26})
        receipt = self.subscription_receipt()
        self.assertEqual(execute_paddle_receipt(receipt.pk, subscription_get=lambda **_: self.subscription_response()), "succeeded")
        self.assertFalse(PaddleFirstActiveObservation.objects.exists())
        self.assertIsNone(Organization.objects.get(pk=self.organization.pk).paid_activation_tracking)
        self.assertEqual(PaddleSubscription.objects.get().status, "active")
        AuditEvent.objects.filter(pk=audit.pk).update(details=audit.details)
        later = self.signed("y")
        self.assertEqual(execute_paddle_receipt(later.pk, subscription_get=lambda **_: self.subscription_response()), "succeeded")
        self.assertFalse(PaddleFirstActiveObservation.objects.exists())

    def test_current_catalog_loss_during_provider_get_never_alters_billing_to_make_a_conversion(self):
        self.paid()
        receipt = self.subscription_receipt()
        def rotate_catalog(**_):
            PaddleSellerConfiguration.objects.filter(environment="sandbox").update(price_id="pri_" + "z" * 26)
            return self.subscription_response()
        self.assertEqual(execute_paddle_receipt(receipt.pk, subscription_get=rotate_catalog), "succeeded")
        self.assertFalse(PaddleFirstActiveObservation.objects.exists())
        self.assertIsNone(Organization.objects.get(pk=self.organization.pk).paid_activation_tracking)
        self.assertEqual(PaddleSubscription.objects.get().status, "active")

    @patch("tenancy.services.did_recently_authenticate", return_value=True)
    def test_real_closure_customer_erasure_retains_restricted_immutable_observation_and_audits(self, _reauth):
        from config.test_foundations import TEST_STORAGES
        from .closure import close_organization_locally
        from .customer_inventory import CUSTOMER, RESTRICTED, inventory_customer_data
        from .deletion import delete_customer_database_records, prepare_customer_data_deletion, sweep_customer_artifact_versions
        from .services import create_project
        project = create_project(organization=self.organization, user=self.owner, name="Synthetic paid retention",
            canonical_origin="https://paid-retention.example.invalid")
        self.current()
        before = PaddleFirstActiveObservation.objects.get()
        self.assertNotIn("tenancy.PaddleFirstActiveObservation", CUSTOMER)
        self.assertEqual(RESTRICTED["tenancy.PaddleFirstActiveObservation"], "organization_id")
        inventory = inventory_customer_data(organization=self.organization, actor=self.owner)
        self.assertEqual(next(row["count"] for row in inventory["restricted"] if row["model"] == "tenancy.PaddleFirstActiveObservation"), 1)
        canceled = self.signed("v", "subscription.canceled")
        self.assertEqual(execute_paddle_receipt(canceled.pk, subscription_get=lambda **_: self.subscription_response(
            status="canceled", canceled_at=timezone.now().isoformat(), current_billing_period=None)), "succeeded")
        request = RequestFactory().post("/api/organizations/close/")
        request.user = self.owner
        with override_settings(STORAGES=TEST_STORAGES):
            close_organization_locally(organization=self.organization, actor=self.owner, request=request)
            run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.organization))
            self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(project.__class__.objects.filter(pk=project.pk).exists())
        after = PaddleFirstActiveObservation.objects.get()
        self.assertEqual((after.pk, after.source, after.observed_at), (before.pk, before.source, before.observed_at))
        self.assertTrue(AuditEvent.objects.filter(pk=after.source["subscription_audit_id"]).exists())
        from .acquisition import acquisition_milestones
        self.assertEqual(acquisition_milestones()["milestones"]["paid_activation_confirmed"]["count"], 1)

    def test_genuine_cancellation_recheckout_and_archived_out_of_order_source_do_not_reset_observation(self):
        self.current()
        before = PaddleFirstActiveObservation.objects.get()
        fixtures.SignedPaymentEvidenceTests.test_fully_canceled_current_subscription_allows_new_paid_checkout_with_history(self)
        after = PaddleFirstActiveObservation.objects.get()
        self.assertEqual((after.pk, after.source, after.observed_at), (before.pk, before.source, before.observed_at))


@override_settings(**fixtures.SignedPaymentEvidenceTests._overridden_settings, DEBUG=True)
class FirstActiveObservationRaceTests(TransactionTestCase):
    setUp = fixtures.SignedPaymentEvidenceTests.setUp
    provider_response = fixtures.SignedPaymentEvidenceTests.provider_response
    subscription_receipt = fixtures.SignedPaymentEvidenceTests.subscription_receipt
    subscription_response = fixtures.SignedPaymentEvidenceTests.subscription_response
    signed = FirstActiveObservationTests.signed

    def test_two_actual_worker_claims_commit_one_first_observation_with_their_own_success_atomically(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import close_old_connections
        self.assertEqual(execute_paddle_receipt(self.receipt.pk, transaction_get=lambda **_: self.provider_response()), "succeeded")
        first, second = self.subscription_receipt(), self.signed("z")
        barrier = Barrier(2)
        def run(pk):
            close_old_connections()
            try:
                def provider(**_):
                    barrier.wait(timeout=15)
                    return self.subscription_response()
                return execute_paddle_receipt(pk, subscription_get=provider)
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(run, [first.pk, second.pk])), ["succeeded", "succeeded"])
        observation = PaddleFirstActiveObservation.objects.get(organization=self.organization)
        saved = PaddleWebhookReceipt.objects.get(pk=observation.receipt_id)
        self.assertIn(saved.pk, {first.pk, second.pk})
        self.assertEqual(observation.observed_at, saved.processed_at)
        self.assertEqual(PaddleFirstActiveObservation.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.BILLING_SUBSCRIPTION_RECONCILED).count(), 2)


@override_settings(**fixtures.SignedPaymentEvidenceTests._overridden_settings, DEBUG=True, STAFF_MFA_REQUIRED=False)
class FirstActiveObservationReadTests(TestCase):
    setUp = fixtures.SignedPaymentEvidenceTests.setUp
    provider_response = fixtures.SignedPaymentEvidenceTests.provider_response
    subscription_receipt = fixtures.SignedPaymentEvidenceTests.subscription_receipt
    subscription_response = fixtures.SignedPaymentEvidenceTests.subscription_response
    current = PaidActivationSourceTests.current
    signed = FirstActiveObservationTests.signed

    def test_actual_owner_history_is_private_read_only_minimized_and_stays_original_after_current_source_loss(self):
        path = f"/api/organizations/{self.organization.pk}/billing/checkout/"
        self.assertEqual(self.client.get(path).status_code, 401)
        self.client.force_login(self.owner)
        pending = self.client.get(path)
        self.assertEqual(pending.json()["first_paid_observation"]["state"], "not_observed")
        self.current()
        before = PaddleFirstActiveObservation.objects.get()
        from .paddle_activation import inspect_first_active_observation
        with patch("tenancy.paddle_transport.paddle_subscription_get", side_effect=AssertionError("No provider read")), patch(
            "tenancy.paddle_transport.paddle_transaction_create", side_effect=AssertionError("No provider POST")), CaptureQueriesContext(connection) as queries:
            response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        result = response.json()["first_paid_observation"]
        self.assertEqual(result["observation"]["observed_at"], before.observed_at.isoformat())
        self.assertEqual(result["observation"]["attempt_id"], self.attempt.pk)
        self.assertFalse(any(row["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"} for row in queries))
        for private in ("customer_id", "subscription_id", "event_id", "raw_digest", "request_actor_id", "source\"", SANDBOX_KEY):
            self.assertNotIn(private, json.dumps(result))
        PaddleSellerConfiguration.objects.filter(environment="sandbox").update(price_id="pri_" + "z" * 26)
        PaddleSubscription.objects.filter(organization=self.organization).update(status="past_due")
        with override_settings(PADDLE_ENVIRONMENT="live", PADDLE_ENCRYPTION_KEYS=()):
            self.assertEqual(inspect_first_active_observation(organization=self.organization, actor=self.owner), result)
        self.assertEqual(self.client.get(path).json()["first_paid_observation"], result)
        saved_source = before.source
        PaddleFirstActiveObservation.objects.filter(pk=before.pk).update(source={**saved_source, "organization_id": self.organization.pk + 1})
        self.assertEqual(self.client.get(path).status_code, 409)
        PaddleFirstActiveObservation.objects.filter(pk=before.pk).update(source=saved_source)
        from .paddle_activation import first_active_observation_result
        def read_then_revoke(saved):
            result = first_active_observation_result(saved)
            OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="admin")
            return result
        with patch("tenancy.paddle_activation.first_active_observation_result", side_effect=read_then_revoke):
            self.assertEqual(self.client.get(path).status_code, 403)
        foreign = Client()
        foreign.force_login(self.staff)
        self.assertEqual(foreign.get(path).status_code, 404)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="owner")
        Organization.objects.filter(pk=self.organization.pk).update(closed_at=timezone.now(), is_suspended=True)
        self.assertEqual(self.client.get(path).status_code, 404)

    def test_actual_later_subscription_and_recheckout_private_history_remains_exact_first_original_source(self):
        self.current()
        from .paddle_activation import inspect_first_active_observation
        before = inspect_first_active_observation(organization=self.organization, actor=self.owner)
        fixtures.SignedPaymentEvidenceTests.test_fully_canceled_current_subscription_allows_new_paid_checkout_with_history(self)
        self.assertEqual(inspect_first_active_observation(organization=self.organization, actor=self.owner), before)

    def test_history_rejects_persisted_observation_loss_after_original_validation(self):
        from .paddle_activation import first_active_observation_result, inspect_first_active_observation
        self.current()
        def result_then_change(saved):
            result = first_active_observation_result(saved)
            PaddleFirstActiveObservation.objects.filter(pk=saved.pk).update(observed_at=saved.observed_at + timedelta(microseconds=1))
            return result
        with patch("tenancy.paddle_activation.first_active_observation_result", side_effect=result_then_change), self.assertRaises((PermissionDenied, ValidationError)):
            inspect_first_active_observation(organization=self.organization, actor=self.owner)

    def test_history_rechecks_full_capture_references_and_birth_tracking_without_writes(self):
        from django.db import transaction
        from .paddle_activation import first_active_observation_result, inspect_first_active_observation
        from .paddle_checkout_delivery import checkout_source_digest
        self.current()
        saved = PaddleFirstActiveObservation.objects.get(organization=self.organization)
        original = inspect_first_active_observation(organization=self.organization, actor=self.owner)
        def changed_source():
            source = {**saved.source, "price_id": "pri_" + "z" * 26}
            PaddleFirstActiveObservation.objects.filter(pk=saved.pk).update(source=source, source_digest=checkout_source_digest(source))
        mutations = (changed_source,
            lambda: PaddleFirstActiveObservation.objects.filter(pk=saved.pk).update(id=2**52),
            lambda: Organization.objects.filter(pk=self.organization.pk).update(created_at=self.organization.created_at - timedelta(microseconds=1)),
            lambda: Organization.objects.filter(pk=self.organization.pk).update(paid_activation_tracking=None),
            lambda: PaddleWebhookReceipt.objects.filter(pk=saved.receipt_id).update(raw_digest="a" * 64),
            lambda: AuditEvent.objects.filter(pk=saved.source["payment_audit_id"]).update(details={}),
            lambda: PaddleCheckoutAttempt.objects.filter(pk=saved.attempt_id).update(paid_customer_id="ctm_" + "z" * 26))
        for mutate in mutations:
            for when in (1, 2):
                with self.subTest(mutation=mutations.index(mutate), validation=when), transaction.atomic():
                    calls = 0
                    def result_then_change(row):
                        nonlocal calls
                        result = first_active_observation_result(row); calls += 1
                        if calls == when: mutate()
                        return result
                    with patch("tenancy.paddle_activation.first_active_observation_result", side_effect=result_then_change), self.assertRaises(ValidationError):
                        inspect_first_active_observation(organization=self.organization, actor=self.owner)
                    transaction.set_rollback(True)
        with CaptureQueriesContext(connection) as queries, patch("socket.create_connection", side_effect=AssertionError("network")):
            self.assertEqual(inspect_first_active_observation(organization=self.organization, actor=self.owner), original)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))

    def test_two_actual_organizations_staff_retained_count_is_read_only_identifier_free_and_current_mfa_scoped(self):
        from allauth.account.models import EmailAddress
        from .paddle_checkout import mark_paddle_checkout_sending, reserve_paddle_checkout
        from .services import create_organization
        from .test_paddle_attempt import catalog
        self.current()
        fixtures.SignedPaymentEvidenceTests.test_fully_canceled_current_subscription_allows_new_paid_checkout_with_history(self)
        other_owner = get_user_model().objects.create_user("other-paid@example.invalid", "test-password")
        EmailAddress.objects.create(user=other_owner, email=other_owner.email, verified=True, primary=True)
        other = create_organization(user=other_owner, name="Other synthetic paid organization")
        attempt = reserve_paddle_checkout(organization=other, actor=other_owner, request_key="other-paid-fixture")
        mark_paddle_checkout_sending(attempt=attempt, actor=other_owner, catalog_response=catalog())
        PaddleCheckoutAttempt.objects.filter(pk=attempt.pk).update(state="ready", transaction_id="txn_" + "z" * 26)
        payment = self.signed("z", "transaction.completed", "txn_" + "z" * 26)
        custom = {"organization_id": str(other.pk), "checkout_attempt_id": str(attempt.pk), "offer_version": "agency-launch-v1"}
        provider = self.provider_response()
        provider["data"].update(id=payment.entity_id, customer_id="ctm_" + "z" * 26,
                                subscription_id="sub_" + "z" * 26, custom_data=custom)
        self.assertEqual(execute_paddle_receipt(payment.pk, transaction_get=lambda **_: provider), "succeeded")
        subscription = self.signed("q", "subscription.created", "sub_" + "z" * 26)
        provider = self.subscription_response(id="sub_" + "z" * 26, customer_id="ctm_" + "z" * 26, custom_data=custom)
        self.assertEqual(execute_paddle_receipt(subscription.pk, subscription_get=lambda **_: provider), "succeeded")
        self.assertEqual(PaddleFirstActiveObservation.objects.count(), 2)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="admin")
        PaddleSellerConfiguration.objects.filter(environment="sandbox").update(price_id="pri_" + "h" * 26)
        self.client.force_login(self.staff)
        path = "/api/platform/acquisition/milestones/"
        with patch("tenancy.paddle_transport.paddle_transaction_get", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response.json()["milestones"]["paid_activation_confirmed"], {"grain": "organization", "count": 2, "state": "derivable"})
        self.assertFalse(any(row["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"} for row in queries))
        for private in ("organization_id", "attempt_id", "source_digest", "observed_at", "occurred_at", "customer_id", "subscription_id", self.owner.email, other_owner.email):
            self.assertNotIn(private, response.content.decode())
        with override_settings(STAFF_MFA_REQUIRED=True): self.assertEqual(self.client.get(path).status_code, 403)
