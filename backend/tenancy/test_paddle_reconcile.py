import json
from datetime import timedelta
from types import SimpleNamespace

from allauth.account.models import EmailAddress
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from unittest.mock import patch

from .billing_state import paid_access_state
from .models import (AuditEvent, AuditEventType, Organization, PaddleCheckoutAttempt, PaddleSubscription,
                     PaddleSubscriptionHistory, PaddleWebhookReceipt)
from .paddle_checkout import mark_paddle_checkout_sending, reserve_paddle_checkout
from .paddle_jobs import execute_paddle_receipt, recover_paddle_receipts
from .paddle_reconcile import (parse_current_subscription, parse_paid_checkout_transaction,
                                record_current_subscription_receipt, record_paid_checkout_receipt,
                                _reconciled_usage_start)
from .paddle_seller import set_paddle_seller
from .paddle_seller import rotate_paddle_api_key
from .paddle_webhooks import record_paddle_notification
from .paddle_webhooks import requeue_paddle_receipt
from .services import active_trial_for_policy, create_organization
from .test_paddle_attempt import PRICE, PRODUCT, catalog
from .test_paddle_seller import SANDBOX_KEY, SANDBOX_TOKEN
from .test_paddle_webhooks import NOW, SECRET, header, notification
from .paddle_transport import PaddleTransportError


class ScopedProviderTransactionTests(SimpleTestCase):
    def test_second_failed_cycle_uses_latest_paid_period_not_prior_recovery_anchor(self):
        prior = SimpleNamespace(status="active", verified_at=NOW, period_starts_at=NOW,
            period_ends_at=NOW + timedelta(days=30), grace_usage_starts_at=NOW - timedelta(days=30))
        changed = {"status": "past_due", "period_starts_at": NOW + timedelta(days=30)}
        self.assertEqual(_reconciled_usage_start(prior, changed, NOW + timedelta(days=30)), NOW)
        self.assertIsNone(_reconciled_usage_start(prior, changed, NOW + timedelta(days=60)))

    def test_paid_provider_get_must_match_current_attempt_and_offer(self):
        attempt = SimpleNamespace(pk=19, organization_id=17, state="ready", transaction_id="txn_" + "a" * 26,
                                  price_id="pri_" + "b" * 26, product_id="pro_" + "c" * 26)
        row = {"id": attempt.transaction_id, "status": "paid", "origin": "api",
               "customer_id": "ctm_" + "d" * 26, "subscription_id": None,
               "collection_mode": "automatic", "currency_code": "USD",
               "custom_data": {"organization_id": "17", "checkout_attempt_id": "19",
                               "offer_version": "agency-launch-v1"},
               "items": [{"quantity": 1, "price": {"id": attempt.price_id, "product_id": attempt.product_id,
                        "billing_cycle": {"interval": "month", "frequency": 1}, "trial_period": None}}]}
        self.assertEqual(parse_paid_checkout_transaction(attempt=attempt, response={"data": row})["subscription_id"], "")
        for field, value in (("id", "txn_" + "z" * 26), ("status", "ready"), ("origin", "web"),
                             ("customer_id", "ctm_invalid"),
                             ("collection_mode", "manual"),
                             ("custom_data", {**row["custom_data"], "organization_id": "18"}),
                             ("custom_data", {**row["custom_data"], "checkout_attempt_id": "20"}),
                             ("items", [{"quantity": 1, "price": {"id": "pri_" + "z" * 26}}]),
                             ("items", [{**row["items"][0], "quantity": 2}])):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                parse_paid_checkout_transaction(attempt=attempt, response={"data": {**row, field: value}})


@override_settings(PADDLE_ENVIRONMENT="sandbox", PADDLE_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),))
class SignedPaymentEvidenceTests(TestCase):
    def setUp(self):
        users = get_user_model()
        staff = users.objects.create_superuser("payment-staff@example.com", "password")
        self.staff = staff
        self.owner = users.objects.create_user("payment-owner@example.com", "password")
        EmailAddress.objects.create(user=self.owner, email=self.owner.email, verified=True, primary=True)
        self.organization = create_organization(user=self.owner, name="Verified payment org")
        set_paddle_seller(actor=staff, environment="sandbox", api_key=SANDBOX_KEY,
            webhook_secret=SECRET, client_token=SANDBOX_TOKEN, product_id=PRODUCT, price_id=PRICE,
            currency="USD", amount="14900", interval="month", frequency=1)
        self.attempt = reserve_paddle_checkout(organization=self.organization, actor=self.owner,
                                               request_key="paid-checkout-001")
        mark_paddle_checkout_sending(attempt=self.attempt, actor=self.owner, catalog_response=catalog())
        PaddleCheckoutAttempt.objects.filter(pk=self.attempt.pk).update(state="ready", transaction_id="txn_" + "c" * 26)
        raw = notification()
        self.receipt, _ = record_paddle_notification(environment="sandbox", raw_body=raw,
            signature=header(raw), now=NOW)

    def provider_response(self):
        return {"data": {"id": "txn_" + "c" * 26, "status": "completed", "origin": "api",
            "customer_id": "ctm_" + "d" * 26, "subscription_id": "sub_" + "e" * 26,
            "collection_mode": "automatic", "currency_code": "USD",
            "custom_data": {"organization_id": str(self.organization.pk),
                            "checkout_attempt_id": str(self.attempt.pk), "offer_version": "agency-launch-v1"},
            "items": [{"quantity": 1, "price": {"id": PRICE, "product_id": PRODUCT,
                       "billing_cycle": {"interval": "month", "frequency": 1}, "trial_period": None}}]}}

    def test_signed_current_payment_stops_trial_without_creating_paid_subscription(self):
        self.assertIsNotNone(active_trial_for_policy(organization=self.organization))
        row = record_paid_checkout_receipt(receipt=self.receipt, provider_response=self.provider_response())
        self.assertEqual((row.paid_customer_id, row.paid_subscription_id),
                         ("ctm_" + "d" * 26, "sub_" + "e" * 26))
        self.assertIsNotNone(row.paid_verified_at)
        self.assertIsNone(active_trial_for_policy(organization=self.organization))
        self.assertFalse(PaddleSubscription.objects.filter(organization=self.organization).exists())
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.BILLING_PAYMENT_VERIFIED).count(), 1)
        record_paid_checkout_receipt(receipt=self.receipt, provider_response=self.provider_response())
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.BILLING_PAYMENT_VERIFIED).count(), 1)

    def test_foreign_or_unpaid_provider_response_cannot_mark_paid(self):
        for field, value in (("status", "ready"), ("customer_id", "ctm_invalid"),
                             ("custom_data", {"checkout_attempt_id": str(self.attempt.pk),
                                              "organization_id": "999", "offer_version": "agency-launch-v1"})):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                response = self.provider_response()
                response["data"][field] = value
                record_paid_checkout_receipt(receipt=self.receipt, provider_response=response)
        self.assertIsNone(PaddleCheckoutAttempt.objects.get(pk=self.attempt.pk).paid_verified_at)
        self.assertIsNotNone(active_trial_for_policy(organization=self.organization))

    def subscription_receipt(self):
        raw = json.dumps({"event_id": "evt_" + "f" * 26, "notification_id": "ntf_" + "g" * 26,
            "event_type": "subscription.created", "occurred_at": NOW.isoformat(),
            "data": {"id": "sub_" + "e" * 26}}, separators=(",", ":")).encode()
        receipt, _ = record_paddle_notification(environment="sandbox", raw_body=raw,
                                                 signature=header(raw), now=NOW)
        return receipt

    def subscription_response(self, **changes):
        return {"data": {**{
            "id": "sub_" + "e" * 26, "customer_id": "ctm_" + "d" * 26,
            "status": "active", "collection_mode": "automatic", "currency_code": "USD",
            "custom_data": {"organization_id": str(self.organization.pk),
                "checkout_attempt_id": str(self.attempt.pk), "offer_version": "agency-launch-v1"},
            "billing_cycle": {"interval": "month", "frequency": 1},
            "items": [{"quantity": 1, "price": {"id": PRICE, "product_id": PRODUCT}}],
            "current_billing_period": {"starts_at": (NOW - timedelta(days=1)).isoformat(),
                                       "ends_at": (NOW + timedelta(days=29)).isoformat()},
            "scheduled_change": None, "canceled_at": None,
        }, **changes}}

    def test_subscription_requires_signed_receipt_and_prior_verified_payment(self):
        receipt = self.subscription_receipt()
        with self.assertRaises(ValidationError):
            record_current_subscription_receipt(receipt=receipt, provider_response=self.subscription_response())
        self.assertFalse(PaddleSubscription.objects.exists())
        record_paid_checkout_receipt(receipt=self.receipt, provider_response=self.provider_response())
        linked = record_current_subscription_receipt(receipt=receipt, provider_response=self.subscription_response())
        self.assertEqual((linked.customer_id, linked.status, linked.currency_code),
                         ("ctm_" + "d" * 26, "active", "USD"))
        self.assertEqual(paid_access_state(linked), "paid_active")
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.BILLING_SUBSCRIPTION_RECONCILED).count(), 1)
        record_current_subscription_receipt(receipt=receipt, provider_response=self.subscription_response())
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.BILLING_SUBSCRIPTION_RECONCILED).count(), 1)

    def test_foreign_subscription_and_bad_period_never_link(self):
        receipt = self.subscription_receipt()
        record_paid_checkout_receipt(receipt=self.receipt, provider_response=self.provider_response())
        for field, bad in (("customer_id", "ctm_" + "z" * 26),
                           ("custom_data", {"checkout_attempt_id": str(self.attempt.pk),
                                            "organization_id": "999", "offer_version": "agency-launch-v1"}),
                           ("current_billing_period", {"starts_at": NOW.isoformat(),
                                                       "ends_at": (NOW - timedelta(days=1)).isoformat()}),
                           ("canceled_at", NOW.isoformat())):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                response = self.subscription_response(**{field: bad})
                record_current_subscription_receipt(receipt=receipt, provider_response=response)
        self.assertFalse(PaddleSubscription.objects.exists())

    def test_foreign_historical_customer_cannot_claim_current_paid_org(self):
        record_paid_checkout_receipt(receipt=self.receipt, provider_response=self.provider_response())
        foreign = Organization.objects.create(name="Other payer")
        PaddleSubscriptionHistory.objects.create(organization=foreign, environment="sandbox",
            customer_id="ctm_" + "d" * 26, subscription_id="sub_" + "z" * 26,
            status="canceled", verified_at=timezone.now(), canceled_at=timezone.now())
        receipt = self.subscription_receipt()
        with self.assertRaises(ValidationError):
            record_current_subscription_receipt(receipt=receipt,
                                                provider_response=self.subscription_response())
        self.assertFalse(PaddleSubscription.objects.filter(organization=self.organization).exists())

    def test_receipt_worker_retries_only_read_and_converges_on_current_provider(self):
        calls = []

        def unavailable(**_):
            from .paddle_transport import PaddleTransportError
            calls.append("read")
            raise PaddleTransportError("provider_unavailable")

        self.assertEqual(execute_paddle_receipt(self.receipt.pk, transaction_get=unavailable), "failed")
        self.receipt.refresh_from_db()
        self.assertEqual((self.receipt.state, self.receipt.attempts), ("failed", 1))
        self.assertIsNotNone(self.receipt.retry_after)
        self.assertEqual(execute_paddle_receipt(self.receipt.pk, transaction_get=unavailable), "failed")
        self.assertEqual(calls, ["read"])
        self.assertIsNone(PaddleCheckoutAttempt.objects.get(pk=self.attempt.pk).paid_verified_at)
        PaddleWebhookReceipt.objects.filter(pk=self.receipt.pk).update(retry_after=timezone.now() - timedelta(seconds=1))
        self.assertEqual(execute_paddle_receipt(self.receipt.pk,
            transaction_get=lambda **_: self.provider_response()), "succeeded")
        self.receipt.refresh_from_db()
        self.assertEqual((self.receipt.state, self.receipt.attempts), ("succeeded", 2))
        self.assertEqual(execute_paddle_receipt(self.receipt.pk, transaction_get=unavailable), "succeeded")
        self.assertEqual(calls, ["read"])
        self.assertIsNone(active_trial_for_policy(organization=self.organization))

    def test_signed_subscription_worker_and_stale_recovery_are_bounded(self):
        subscribed = self.subscription_receipt()
        self.assertEqual(execute_paddle_receipt(subscribed.pk,
            subscription_get=lambda **_: self.subscription_response()), "failed")
        self.assertFalse(PaddleSubscription.objects.exists())
        self.assertEqual(execute_paddle_receipt(self.receipt.pk,
            transaction_get=lambda **_: self.provider_response()), "succeeded")
        self.assertEqual(PaddleWebhookReceipt.objects.get(pk=subscribed.pk).state, "pending")
        self.assertEqual(execute_paddle_receipt(subscribed.pk,
            subscription_get=lambda **_: self.subscription_response()), "succeeded")
        self.assertEqual(paid_access_state(PaddleSubscription.objects.get(organization=self.organization)), "paid_active")
        PaddleWebhookReceipt.objects.filter(pk=subscribed.pk).update(state="processing", attempts=2,
            claimed_at=timezone.now() - timedelta(minutes=4), processed_at=None)
        with patch("tenancy.tasks.reconcile_paddle_receipt_task.apply_async") as send:
            self.assertEqual(recover_paddle_receipts(limit=2), 1)
        send.assert_called_once_with(args=[subscribed.pk], queue="default",
                                     task_id=f"paddle-receipt-{subscribed.pk}", retry=False)

    def test_signed_renewal_failure_and_recovery_use_current_provider_state(self):
        self.subscription_receipt()
        record_paid_checkout_receipt(receipt=self.receipt, provider_response=self.provider_response())
        subscribed = PaddleWebhookReceipt.objects.get(event_type="subscription.created")
        record_current_subscription_receipt(receipt=subscribed, provider_response=self.subscription_response())
        previous_period_start = PaddleSubscription.objects.get(organization=self.organization).period_starts_at
        observed = timezone.now()
        changed_period = {"starts_at": observed.isoformat(), "ends_at": (observed + timedelta(days=30)).isoformat()}
        raw = json.dumps({"event_id": "evt_" + "u" * 26, "notification_id": "ntf_" + "u" * 26,
            "event_type": "subscription.updated", "occurred_at": observed.isoformat(),
            "data": {"id": "sub_" + "e" * 26}}, separators=(",", ":")).encode()
        pending, _ = record_paddle_notification(environment="sandbox", raw_body=raw,
                                                signature=header(raw, when=observed), now=observed)
        record_current_subscription_receipt(receipt=pending, provider_response=self.subscription_response(
            status="past_due", current_billing_period=changed_period))
        self.assertEqual(PaddleSubscription.objects.get(organization=self.organization).grace_usage_starts_at,
                         previous_period_start)

        def signed(event_id, event_type, transaction_id):
            raw = json.dumps({"event_id": "evt_" + event_id * 26,
                "notification_id": "ntf_" + event_id * 26, "event_type": event_type,
                "occurred_at": observed.isoformat(), "data": {"id": "txn_" + transaction_id * 26}},
                separators=(",", ":")).encode()
            receipt, _ = record_paddle_notification(environment="sandbox", raw_body=raw,
                                                      signature=header(raw, when=observed), now=observed)
            return receipt

        def renewal(transaction_id, status):
            return {"data": {"id": "txn_" + transaction_id * 26, "status": status,
                "origin": "subscription_recurring", "customer_id": "ctm_" + "d" * 26,
                "subscription_id": "sub_" + "e" * 26, "currency_code": "USD",
                "collection_mode": "automatic", "items": [{"quantity": 1,
                    "price": {"id": PRICE, "product_id": PRODUCT}}]}}

        failed = signed("h", "transaction.payment_failed", "x")
        self.assertEqual(execute_paddle_receipt(failed.pk,
            transaction_get=lambda **_: renewal("x", "past_due"),
            subscription_get=lambda **_: self.subscription_response(
                status="past_due", current_billing_period=changed_period)), "succeeded")
        linked = PaddleSubscription.objects.get(organization=self.organization)
        self.assertEqual(paid_access_state(linked), "payment_grace")
        self.assertEqual(linked.failed_at, observed)
        self.assertEqual(linked.grace_usage_starts_at, previous_period_start)
        recovered = signed("i", "transaction.completed", "y")
        self.assertEqual(execute_paddle_receipt(recovered.pk,
            transaction_get=lambda **_: renewal("y", "completed"),
            subscription_get=lambda **_: self.subscription_response(current_billing_period=changed_period)), "succeeded")
        linked.refresh_from_db()
        self.assertEqual(paid_access_state(linked), "paid_active")
        self.assertIsNone(linked.failed_at)
        self.assertEqual(linked.grace_usage_starts_at, previous_period_start)
        late = signed("j", "transaction.payment_failed", "x")
        self.assertEqual(execute_paddle_receipt(late.pk,
            transaction_get=lambda **_: renewal("x", "completed"),
            subscription_get=lambda **_: self.subscription_response(current_billing_period=changed_period)), "succeeded")
        linked.refresh_from_db()
        self.assertEqual(paid_access_state(linked), "paid_active")
        self.assertEqual(linked.grace_usage_starts_at, previous_period_start)
        next_period = {"starts_at": (observed + timedelta(days=30)).isoformat(),
                       "ends_at": (observed + timedelta(days=60)).isoformat()}
        raw = json.dumps({"event_id": "evt_" + "r" * 26, "notification_id": "ntf_" + "r" * 26,
            "event_type": "subscription.updated", "occurred_at": observed.isoformat(),
            "data": {"id": linked.subscription_id}}, separators=(",", ":")).encode()
        new_period_receipt, _ = record_paddle_notification(environment="sandbox", raw_body=raw,
                                                            signature=header(raw, when=observed), now=observed)
        record_current_subscription_receipt(receipt=new_period_receipt,
            provider_response=self.subscription_response(current_billing_period=next_period))
        self.assertIsNone(PaddleSubscription.objects.get(pk=linked.pk).grace_usage_starts_at)

    def test_late_signed_failure_after_expired_prior_period_does_not_reopen_grace(self):
        subscribed = self.subscription_receipt()
        record_paid_checkout_receipt(receipt=self.receipt, provider_response=self.provider_response())
        record_current_subscription_receipt(receipt=subscribed, provider_response=self.subscription_response())
        PaddleSubscription.objects.filter(organization=self.organization).update(
            verified_at=NOW - timedelta(days=50), period_starts_at=NOW - timedelta(days=50),
            period_ends_at=NOW - timedelta(days=20))
        raw = json.dumps({"event_id": "evt_" + "s" * 26, "notification_id": "ntf_" + "s" * 26,
            "event_type": "transaction.payment_failed", "occurred_at": NOW.isoformat(),
            "data": {"id": "txn_" + "s" * 26}}, separators=(",", ":")).encode()
        failed, _ = record_paddle_notification(environment="sandbox", raw_body=raw,
                                               signature=header(raw), now=NOW)
        renewal = {"data": {"id": "txn_" + "s" * 26, "status": "past_due",
            "origin": "subscription_recurring", "customer_id": "ctm_" + "d" * 26,
            "subscription_id": "sub_" + "e" * 26, "currency_code": "USD",
            "collection_mode": "automatic", "items": [{"quantity": 1,
                "price": {"id": PRICE, "product_id": PRODUCT}}]}}
        changed_period = {"starts_at": (NOW - timedelta(days=19)).isoformat(),
                          "ends_at": (NOW + timedelta(days=11)).isoformat()}
        self.assertEqual(execute_paddle_receipt(failed.pk, transaction_get=lambda **_: renewal,
            subscription_get=lambda **_: self.subscription_response(
                status="past_due", current_billing_period=changed_period)), "succeeded")
        linked = PaddleSubscription.objects.get(organization=self.organization)
        self.assertEqual(paid_access_state(linked), "read_only")
        self.assertIsNone(linked.grace_usage_starts_at)

    def test_signed_full_refund_and_chargeback_stop_work_without_reversal_auto_restore(self):
        subscribed = self.subscription_receipt()
        record_paid_checkout_receipt(receipt=self.receipt, provider_response=self.provider_response())
        record_current_subscription_receipt(receipt=subscribed, provider_response=self.subscription_response())

        def receipt_for(letter):
            raw = json.dumps({"event_id": "evt_" + letter * 26, "notification_id": "ntf_" + letter * 26,
                "event_type": "adjustment.updated", "occurred_at": NOW.isoformat(),
                "data": {"id": "adj_" + letter * 26}}, separators=(",", ":")).encode()
            return record_paddle_notification(environment="sandbox", raw_body=raw,
                                              signature=header(raw), now=NOW)[0]

        def adjustment(letter, action, kind, status="approved"):
            return {"data": [{"id": "adj_" + letter * 26, "action": action, "type": kind,
                "status": status, "subscription_id": "sub_" + "e" * 26,
                "customer_id": "ctm_" + "d" * 26, "transaction_id": "txn_" + "c" * 26,
                "created_at": NOW.isoformat(), "updated_at": NOW.isoformat()}],
                "meta": {"pagination": {"has_more": False}}}

        partial = receipt_for("k")
        self.assertEqual(execute_paddle_receipt(partial.pk,
            adjustment_get=lambda **_: adjustment("k", "refund", "partial")), "succeeded")
        linked = PaddleSubscription.objects.get(organization=self.organization)
        self.assertEqual(paid_access_state(linked), "paid_active")
        full = receipt_for("l")

        def replace_claim(**_):
            PaddleWebhookReceipt.objects.filter(pk=full.pk).update(claimed_at=timezone.now() + timedelta(seconds=1))
            return adjustment("l", "refund", "full")

        self.assertEqual(execute_paddle_receipt(full.pk, adjustment_get=replace_claim), "unavailable")
        linked.refresh_from_db()
        self.assertIsNone(linked.refunded_at)
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.BILLING_ADJUSTMENT_REVIEWED,
            details__event_id=full.event_id).exists())
        full.refresh_from_db()
        self.assertEqual((full.state, full.attempts), ("processing", 1))
        self.assertIsNone(full.processed_at)
        PaddleWebhookReceipt.objects.filter(pk=full.pk).update(state="failed", retry_after=timezone.now())
        with patch("tenancy.paddle_adjustments._finish_worker_receipt",
                   side_effect=ValidationError("Synthetic receipt persistence failure")):
            self.assertEqual(execute_paddle_receipt(full.pk,
                adjustment_get=lambda **_: adjustment("l", "refund", "full")), "failed")
        linked.refresh_from_db()
        self.assertIsNone(linked.refunded_at)
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.BILLING_ADJUSTMENT_REVIEWED,
            details__event_id=full.event_id).exists())
        PaddleWebhookReceipt.objects.filter(pk=full.pk).update(retry_after=timezone.now())
        self.assertEqual(execute_paddle_receipt(full.pk,
            adjustment_get=lambda **_: adjustment("l", "refund", "full")), "succeeded")
        full.refresh_from_db()
        self.assertEqual((full.state, full.attempts), ("succeeded", 3))
        self.assertIsNotNone(full.processed_at)
        linked.refresh_from_db()
        self.assertEqual(paid_access_state(linked), "retained_read_only")
        warning = receipt_for("m")
        self.assertEqual(execute_paddle_receipt(warning.pk,
            adjustment_get=lambda **_: adjustment("m", "chargeback_warning", "full", "pending_approval")), "succeeded")
        self.assertIsNotNone(PaddleSubscription.objects.get(pk=linked.pk).disputed_at)
        reversal = receipt_for("n")
        self.assertEqual(execute_paddle_receipt(reversal.pk,
            adjustment_get=lambda **_: adjustment("n", "chargeback_reverse", "full")), "succeeded")
        linked.refresh_from_db()
        self.assertEqual(paid_access_state(linked), "retained_read_only")

    def test_fully_canceled_current_subscription_allows_new_paid_checkout_with_history(self):
        subscribed = self.subscription_receipt()
        record_paid_checkout_receipt(receipt=self.receipt, provider_response=self.provider_response())
        record_current_subscription_receipt(receipt=subscribed, provider_response=self.subscription_response())

        def signed(letter, event_type, entity_id):
            raw = json.dumps({"event_id": "evt_" + letter * 26,
                "notification_id": "ntf_" + letter * 26, "event_type": event_type,
                "occurred_at": NOW.isoformat(), "data": {"id": entity_id}}, separators=(",", ":")).encode()
            return record_paddle_notification(environment="sandbox", raw_body=raw,
                                              signature=header(raw), now=NOW)[0]

        canceled = signed("v", "subscription.canceled", "sub_" + "e" * 26)
        self.assertEqual(execute_paddle_receipt(canceled.pk,
            subscription_get=lambda **_: self.subscription_response(status="canceled",
                canceled_at=NOW.isoformat(), current_billing_period=None)), "succeeded")
        self.assertEqual(paid_access_state(PaddleSubscription.objects.get(organization=self.organization)),
                         "retained_read_only")
        newer = reserve_paddle_checkout(organization=self.organization, actor=self.owner,
                                        request_key="new-paid-checkout-002")
        self.attempt.refresh_from_db()
        self.assertEqual((self.attempt.state, newer.state), ("settled", "reserved"))
        mark_paddle_checkout_sending(attempt=newer, actor=self.owner, catalog_response=catalog())
        PaddleCheckoutAttempt.objects.filter(pk=newer.pk).update(state="ready", transaction_id="txn_" + "w" * 26)
        paid = signed("w", "transaction.paid", "txn_" + "w" * 26)
        response = self.provider_response()
        response["data"].update({"id": "txn_" + "w" * 26, "subscription_id": "sub_" + "f" * 26,
            "custom_data": {"organization_id": str(self.organization.pk),
                "checkout_attempt_id": str(newer.pk), "offer_version": "agency-launch-v1"}})
        self.assertEqual(execute_paddle_receipt(paid.pk, transaction_get=lambda **_: response), "succeeded")
        created = signed("x", "subscription.created", "sub_" + "f" * 26)
        provider = self.subscription_response(id="sub_" + "f" * 26,
            custom_data={"organization_id": str(self.organization.pk),
                "checkout_attempt_id": str(newer.pk), "offer_version": "agency-launch-v1"})
        self.assertEqual(execute_paddle_receipt(created.pk, subscription_get=lambda **_: provider), "succeeded")
        current = PaddleSubscription.objects.get(organization=self.organization)
        history = PaddleSubscriptionHistory.objects.get(organization=self.organization)
        self.assertEqual((current.subscription_id, history.subscription_id),
                         ("sub_" + "f" * 26, "sub_" + "e" * 26))
        self.assertEqual(paid_access_state(current), "paid_active")
        old = signed("y", "subscription.updated", history.subscription_id)
        with patch("tenancy.paddle_transport.paddle_subscription_get") as provider_get:
            self.assertEqual(execute_paddle_receipt(old.pk), "succeeded")
            provider_get.assert_not_called()
        self.assertEqual(PaddleSubscription.objects.get(organization=self.organization).subscription_id,
                         current.subscription_id)

    def test_signed_adverse_receipt_holds_paid_work_even_after_provider_outage_exhausts_retries(self):
        subscribed = self.subscription_receipt()
        record_paid_checkout_receipt(receipt=self.receipt, provider_response=self.provider_response())
        record_current_subscription_receipt(receipt=subscribed, provider_response=self.subscription_response())
        raw = json.dumps({"event_id": "evt_" + "p" * 26, "notification_id": "ntf_" + "p" * 26,
            "event_type": "adjustment.updated", "occurred_at": NOW.isoformat(),
            "data": {"id": "adj_" + "p" * 26, "subscription_id": "sub_" + "e" * 26,
                     "customer_id": "ctm_" + "d" * 26}}, separators=(",", ":")).encode()
        adverse, _ = record_paddle_notification(environment="sandbox", raw_body=raw,
                                                signature=header(raw), now=NOW)
        linked = PaddleSubscription.objects.get(organization=self.organization)
        self.assertEqual(paid_access_state(linked), "billing_review_hold")
        for attempt_number in range(3):
            self.assertEqual(execute_paddle_receipt(adverse.pk,
                adjustment_get=lambda **_: (_ for _ in ()).throw(PaddleTransportError("provider_unavailable"))), "failed")
            adverse.refresh_from_db()
            if attempt_number < 2:
                PaddleWebhookReceipt.objects.filter(pk=adverse.pk).update(retry_after=timezone.now() - timedelta(seconds=1))
        self.assertEqual((adverse.attempts, adverse.retry_after), (3, None))
        self.assertEqual(paid_access_state(linked), "billing_review_hold")
        from .test_trial_corrections import staff_trial_request
        requeue_paddle_receipt(receipt=adverse, actor=self.staff, reason="Provider available after outage",
            request=staff_trial_request(self.staff))
        response = {"data": [{"id": "adj_" + "p" * 26, "action": "refund", "type": "full",
            "status": "approved", "subscription_id": "sub_" + "e" * 26,
            "customer_id": "ctm_" + "d" * 26, "transaction_id": "txn_" + "c" * 26,
            "created_at": NOW.isoformat(), "updated_at": NOW.isoformat()}],
            "meta": {"pagination": {"has_more": False}}}
        self.assertEqual(execute_paddle_receipt(adverse.pk, adjustment_get=lambda **_: response), "succeeded")
        linked.refresh_from_db()
        self.assertEqual(paid_access_state(linked), "retained_read_only")

    def test_payment_requeues_exhausted_subscription_dependency_and_rotation_requeues_auth_failure(self):
        subscribed = self.subscription_receipt()
        for attempt_number in range(3):
            self.assertEqual(execute_paddle_receipt(subscribed.pk,
                subscription_get=lambda **_: self.subscription_response()), "failed")
            if attempt_number < 2:
                PaddleWebhookReceipt.objects.filter(pk=subscribed.pk).update(retry_after=timezone.now() - timedelta(seconds=1))
        subscribed.refresh_from_db()
        self.assertEqual((subscribed.attempts, subscribed.retry_after), (3, None))
        record_paid_checkout_receipt(receipt=self.receipt, provider_response=self.provider_response())
        subscribed.refresh_from_db()
        self.assertEqual((subscribed.state, subscribed.attempts), ("pending", 0))
        self.assertEqual(execute_paddle_receipt(subscribed.pk,
            subscription_get=lambda **_: self.subscription_response()), "succeeded")

        raw = json.dumps({"event_id": "evt_" + "q" * 26, "notification_id": "ntf_" + "q" * 26,
            "event_type": "subscription.updated", "occurred_at": NOW.isoformat(),
            "data": {"id": "sub_" + "e" * 26}}, separators=(",", ":")).encode()
        denied, _ = record_paddle_notification(environment="sandbox", raw_body=raw,
                                               signature=header(raw), now=NOW)
        self.assertEqual(execute_paddle_receipt(denied.pk,
            subscription_get=lambda **_: (_ for _ in ()).throw(PaddleTransportError("authorization_unavailable"))), "failed")
        denied.refresh_from_db()
        self.assertIsNone(denied.retry_after)
        rotate_paddle_api_key(actor=self.staff, environment="sandbox", api_key=SANDBOX_KEY[:-3] + "xyz")
        denied.refresh_from_db()
        self.assertEqual((denied.state, denied.attempts), ("pending", 0))
