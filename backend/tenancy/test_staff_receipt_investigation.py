import copy
import json
from datetime import timedelta
from unittest.mock import patch

from allauth.account.internal.flows.login import AUTHENTICATION_METHODS_SESSION_KEY
from allauth.mfa.models import Authenticator
from cryptography.fernet import Fernet
from django.contrib.auth import HASH_SESSION_KEY
from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from accounts.models import User
from . import staff_receipt_investigation as staff
from .models import AuditEvent, AuditEventType, PaddleCheckoutAttempt, PaddleWebhookReceipt
from .paddle_jobs import execute_paddle_receipt, recover_paddle_receipts
from .paddle_reconcile import record_paid_checkout_receipt
from .paddle_seller import rotate_paddle_api_key
from .paddle_transport import PaddleTransportError
from .paddle_webhooks import record_paddle_notification, requeue_paddle_receipt
from . import test_paddle_reconcile as paid_fixtures
from .test_paddle_webhooks import NOW, header, notification
from .test_paddle_seller import SANDBOX_KEY
from .test_trial_corrections import staff_trial_request


@override_settings(PADDLE_ENVIRONMENT="sandbox", PADDLE_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),))
class StaffReceiptInvestigationTests(TestCase):
    provider_response = paid_fixtures.SignedPaymentEvidenceTests.provider_response
    subscription_response = paid_fixtures.SignedPaymentEvidenceTests.subscription_response
    subscription_receipt = paid_fixtures.SignedPaymentEvidenceTests.subscription_receipt

    def setUp(self):
        paid_fixtures.SignedPaymentEvidenceTests.setUp(self)
        self.inspector = User.objects.create_user("receipt-inspector@example.invalid", "fixture-password", is_staff=True)
        self.permission = Permission.objects.get(content_type__app_label="tenancy", codename="view_paddlewebhookreceipt")
        self.inspector.user_permissions.add(self.permission)
        self.browser = Client()
        self.browser.force_login(self.inspector)
        self.request = staff_trial_request(self.inspector, self.browser)

    def inspect(self, **changes):
        return staff.inspect_staff_receipt(**{**dict(request=self.request, receipt_id=self.receipt.pk, reason="investigation"), **changes})

    def events(self):
        return AuditEvent.objects.filter(event_type=AuditEventType.STAFF_BILLING_RECEIPT_INSPECTED)

    def fail(self, receipt=None, category="provider_unavailable"):
        def unavailable(**_): raise PaddleTransportError(category)
        self.assertEqual(execute_paddle_receipt((receipt or self.receipt).pk, transaction_get=unavailable,
            subscription_get=unavailable), "failed")

    def test_genuine_signature_pending_ignored_duplicate_and_retained_environment_dates(self):
        first = self.inspect()
        self.assertEqual(first["receipt"], {"id": self.receipt.pk, "environment": "sandbox", "state": "pending", "attempts": 0,
            "error_category": None, "received_at": self.receipt.received_at.isoformat(), "claimed_at": None,
            "retry_after": None, "processed_at": None})
        record_paddle_notification(environment="sandbox", raw_body=notification(), signature=header(notification()), now=NOW)
        self.assertEqual(self.inspect(), first)
        body = json.loads(notification(event_id="evt_" + "z" * 26, event_type="transaction.draft"))
        moment = timezone.now(); body["occurred_at"] = (moment + timedelta(minutes=4)).isoformat()
        raw = json.dumps(body).encode()
        ignored, _ = record_paddle_notification(environment="sandbox", raw_body=raw, signature=header(raw, when=moment), now=moment)
        self.assertEqual(self.inspect(receipt_id=ignored.pk)["receipt"]["state"], "ignored")
        PaddleWebhookReceipt.objects.filter(pk=self.receipt.pk).update(received_at=timezone.now() - timedelta(days=100))
        with override_settings(PADDLE_ENVIRONMENT="live"):
            self.assertEqual(self.inspect()["receipt"]["state"], "pending")
        for event in self.events():
            self.assertIsNone(event.organization_id); self.assertIsNone(event.project_id); self.assertIsNone(event.subject_user_id)
            self.assertEqual(set(event.details), {"receipt_id", "reason", "state"})

    def test_genuine_worker_processing_future_retry_success_and_settled_noop(self):
        def unavailable(**_):
            active = self.inspect()["receipt"]
            self.assertEqual((active["state"], active["attempts"], active["error_category"]), ("processing", 1, None))
            raise PaddleTransportError("timeout")
        self.assertEqual(execute_paddle_receipt(self.receipt.pk, transaction_get=unavailable), "failed")
        failed = self.inspect()["receipt"]
        self.assertEqual((failed["state"], failed["error_category"]), ("failed", "timeout"))
        self.assertGreater(failed["retry_after"], timezone.now().isoformat())
        self.assertIsNone(PaddleCheckoutAttempt.objects.get(pk=self.attempt.pk).paid_verified_at)
        PaddleWebhookReceipt.objects.filter(pk=self.receipt.pk).update(retry_after=timezone.now())
        self.assertEqual(execute_paddle_receipt(self.receipt.pk, transaction_get=lambda **_: self.provider_response()), "succeeded")
        successful = self.inspect()["receipt"]
        self.assertEqual((successful["state"], successful["attempts"], successful["error_category"]), ("succeeded", 2, None))
        self.assertIsNotNone(successful["processed_at"])
        PaddleCheckoutAttempt.objects.filter(pk=self.attempt.pk).update(state="settled")
        raw = notification(event_id="evt_" + "y" * 26)
        noop, _ = record_paddle_notification(environment="sandbox", raw_body=raw, signature=header(raw), now=NOW)
        with patch("tenancy.paddle_jobs.paddle_transaction_get", side_effect=AssertionError("provider")):
            self.assertEqual(execute_paddle_receipt(noop.pk), "succeeded")
        self.assertEqual(self.inspect(receipt_id=noop.pk)["receipt"]["state"], "succeeded")

    def test_genuine_recovery_manual_payment_dependency_and_rotation_reset_current_counter(self):
        self.fail()
        self.receipt.refresh_from_db()
        claim = timezone.now() - timedelta(minutes=4)
        PaddleWebhookReceipt.objects.filter(pk=self.receipt.pk).update(state="processing", claimed_at=claim,
            retry_after=None, error_category="", received_at=claim - timedelta(minutes=1))
        with patch("tenancy.tasks.reconcile_paddle_receipt_task.apply_async"):
            recover_paddle_receipts(limit=2)
        self.assertEqual(self.inspect()["receipt"]["error_category"], "worker_lost")
        self.receipt.refresh_from_db()
        requeue_paddle_receipt(receipt=self.receipt, actor=self.staff, reason="Fixture recovery", request=staff_trial_request(self.staff))
        reset = self.inspect()["receipt"]
        self.assertEqual((reset["state"], reset["attempts"], reset["claimed_at"], reset["retry_after"]), ("pending", 0, None, None))
        subscribed = self.subscription_receipt()
        self.assertEqual(execute_paddle_receipt(subscribed.pk, subscription_get=lambda **_: self.subscription_response()), "failed")
        self.assertEqual(self.inspect(receipt_id=subscribed.pk)["receipt"]["error_category"], "identity_review")
        record_paid_checkout_receipt(receipt=self.receipt, provider_response=self.provider_response())
        self.assertEqual(self.inspect(receipt_id=subscribed.pk)["receipt"]["attempts"], 0)
        self.fail(subscribed, "authorization_unavailable")
        self.assertIsNone(self.inspect(receipt_id=subscribed.pk)["receipt"]["retry_after"])
        rotate_paddle_api_key(actor=self.staff, environment="sandbox", api_key=SANDBOX_KEY)
        self.assertEqual(self.inspect(receipt_id=subscribed.pk)["receipt"]["state"], "pending")

    def test_scalar_privacy_audit_only_unknown_category_and_no_tenant_provider_queue(self):
        self.fail()
        PaddleWebhookReceipt.objects.filter(pk=self.receipt.pk).update(error_category="private-provider-secret-marker")
        with CaptureQueriesContext(connection) as queries, patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("tenancy.paddle_jobs.dispatch_paddle_receipt", side_effect=AssertionError("dispatch")), \
                patch("tenancy.paddle_webhooks.requeue_paddle_receipt", side_effect=AssertionError("retry")):
            result = self.inspect()
        self.assertEqual(result["receipt"]["error_category"], "unclassified_failure")
        text = json.dumps(result) + json.dumps(self.events().get().details)
        for private in (self.receipt.event_id, self.receipt.notification_id, self.receipt.entity_id, self.receipt.raw_digest,
                self.owner.email, "private-provider-secret-marker", "occurred_at", "organization_id"):
            self.assertNotIn(private, text)
        for query in queries:
            if query["sql"].lstrip().upper().startswith("SELECT"):
                for table in ("tenancy_organization", "tenancy_paddlesubscription", "tenancy_paddlecheckout", "providers_", "integrations_", "jobs_"):
                    self.assertNotIn(table, query["sql"])
        writes = [q["sql"] for q in queries if q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
        self.assertEqual(len(writes), 1); self.assertIn("tenancy_auditevent", writes[0])

    def test_exact_input_current_view_only_staff_permission_session_hash_factor(self):
        for changes in ({"receipt_id": True}, {"receipt_id": 0}, {"receipt_id": 2**53}, {"reason": []}, {"reason": "private prose"}):
            with self.assertRaises(ValidationError): self.inspect(**changes)
        with self.assertRaises(PermissionDenied): self.inspect(receipt_id=self.receipt.pk + 999999)
        self.assertFalse(self.inspector.has_perm("tenancy.change_paddlewebhookreceipt"))
        for mutate in (lambda: self.inspector.user_permissions.clear(),
                lambda: User.objects.filter(pk=self.inspector.pk).update(is_active=False),
                lambda: User.objects.filter(pk=self.inspector.pk).update(is_staff=False),
                lambda: Authenticator.objects.filter(user=self.inspector).delete(),
                lambda: Session.objects.filter(session_key=self.request.session.session_key).delete()):
            with transaction.atomic():
                mutate()
                with patch.object(staff, "_projection", side_effect=AssertionError("source before assurance")), self.assertRaises(PermissionDenied): self.inspect()
                transaction.set_rollback(True)
        session = self.browser.session; session[HASH_SESSION_KEY] = "invalid"; session.save()
        with self.assertRaises(PermissionDenied): self.inspect()
        session[HASH_SESSION_KEY] = self.inspector.get_session_auth_hash()
        session[AUTHENTICATION_METHODS_SESSION_KEY] = [{"method": "password", "at": timezone.now().timestamp()}]; session.save()
        with self.assertRaises(PermissionDenied): self.inspect()
        self.assertFalse(self.events().exists())

    def test_post_audit_every_scalar_actor_loss_and_audit_failure_roll_back(self):
        create = AuditEvent.objects.create
        mutations = [{"environment": "live"}, {"event_id": "evt_" + "x" * 26}, {"notification_id": "ntf_" + "x" * 26},
            {"event_type": "transaction.paid"}, {"entity_id": "txn_" + "x" * 26}, {"raw_digest": "b" * 64},
            {"subscription_id": "sub_" + "x" * 26, "customer_id": "ctm_" + "x" * 26},
            {"occurred_at": self.receipt.occurred_at + timedelta(microseconds=1)},
            {"received_at": self.receipt.received_at - timedelta(microseconds=1)}, {"state": "ignored"}]
        for mutate, error in [(lambda changes=changes: PaddleWebhookReceipt.objects.filter(pk=self.receipt.pk).update(**changes), ValidationError)
                for changes in mutations] + [(lambda: self.inspector.user_permissions.clear(), PermissionDenied),
                (lambda: Session.objects.filter(session_key=self.request.session.session_key).delete(), PermissionDenied),
                (lambda: User.objects.filter(pk=self.inspector.pk).update(session_version="invalidated"), PermissionDenied)]:
            self.request.session = self.browser.session
            def changed(**kwargs):
                result = create(**kwargs); mutate(); return result
            with patch.object(staff.AuditEvent.objects, "create", side_effect=changed), self.assertRaises(error): self.inspect()
            self.assertFalse(self.events().exists())
            self.assertEqual(staff._row(self.receipt.pk)["raw_digest"], self.receipt.raw_digest)
        with patch.object(staff.AuditEvent.objects, "create", side_effect=RuntimeError("audit unavailable")), self.assertRaises(RuntimeError): self.inspect()
        self.assertFalse(self.events().exists())

        self.fail(); failed = staff._row(self.receipt.pk)
        for changes in ({"attempts": 2}, {"error_category": "timeout"}, {"retry_after": failed["retry_after"] + timedelta(microseconds=1)},
                {"claimed_at": failed["claimed_at"] + timedelta(microseconds=1)}, {"processed_at": timezone.now()},
                {"subscription_id": "sub_" + "y" * 26, "customer_id": "ctm_" + "x" * 26}):
            def changed(**kwargs):
                result = create(**kwargs)
                PaddleWebhookReceipt.objects.filter(pk=self.receipt.pk).update(**changes)
                return result
            with patch.object(staff.AuditEvent.objects, "create", side_effect=changed), self.assertRaises(ValidationError): self.inspect()
            self.assertEqual(staff._row(self.receipt.pk), failed)
            self.assertFalse(self.events().exists())

    def test_original_scalar_state_date_shapes_and_mid_projection_hidden_drift(self):
        original = staff._row(self.receipt.pk); now = timezone.now()
        for changes in ({"id": True}, {"environment": "other"}, {"attempts": True}, {"attempts": 4},
                {"state": "unknown"}, {"event_type": "private prose"}, {"entity_id": "sub_" + "x" * 26},
                {"raw_digest": "A" * 64}, {"customer_id": "ctm_" + "x" * 26}, {"error_category": []},
                {"received_at": now + timedelta(seconds=1)}, {"occurred_at": NOW.replace(tzinfo=None)},
                {"claimed_at": now}, {"retry_after": now}, {"processed_at": now},
                {"state": "processing", "attempts": 1, "claimed_at": now, "error_category": "timeout"},
                {"state": "failed", "attempts": 1, "claimed_at": now, "retry_after": now - timedelta(microseconds=1)},
                {"state": "succeeded", "attempts": 1, "claimed_at": now, "processed_at": None},
                {"state": "succeeded", "attempts": 1, "claimed_at": now, "processed_at": now + timedelta(microseconds=1)}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError): staff._record({**copy.deepcopy(original), **changes}, now)
        project = staff._record
        def changed(row, assessed):
            result = project(row, assessed)
            PaddleWebhookReceipt.objects.filter(pk=self.receipt.pk).update(raw_digest="c" * 64)
            return result
        with patch.object(staff, "_record", side_effect=changed), self.assertRaises(ValidationError): self.inspect()
        self.assertFalse(self.events().exists())
