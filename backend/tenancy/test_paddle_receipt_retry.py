import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from allauth.mfa.models import Authenticator
from django.core.cache import cache
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from . import test_paddle_webhooks as fixtures
from .models import AuditEvent, AuditEventType, PaddleWebhookReceipt
from .paddle_webhooks import record_paddle_notification, requeue_paddle_receipt
from .test_trial_corrections import staff_trial_request


@override_settings(**fixtures.WebhookReceiptTests._overridden_settings, PADDLE_ENVIRONMENT="sandbox", STAFF_MFA_REQUIRED=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "receipt-retry"}})
class ReceiptRetryTests(TestCase):
    def setUp(self):
        cache.clear()
        fixtures.WebhookReceiptTests.setUp(self)
        raw = fixtures.notification()
        self.receipt, _ = record_paddle_notification(environment="sandbox", raw_body=raw,
            signature=fixtures.header(raw), now=fixtures.NOW)
        PaddleWebhookReceipt.objects.filter(pk=self.receipt.pk).update(state="failed", attempts=3,
            claimed_at=timezone.now(), error_category="provider_unavailable")
        self.receipt.refresh_from_db()
        self.browser = Client(enforce_csrf_checks=True); self.browser.force_login(self.staff)
        self.browser.get("/_allauth/browser/v1/auth/session")
        self.path = f"/api/platform/billing/paddle/receipts/{self.receipt.pk}/retry/"

    def post(self):
        return self.browser.post(self.path, data=json.dumps({"reason": "Fixture reviewed provider recovery"}),
            content_type="application/json", HTTP_X_CSRFTOKEN=self.browser.cookies["csrftoken"].value)

    def test_password_only_cannot_retry_signed_receipt_when_development_middleware_is_optional(self):
        with patch("tenancy.paddle_seller_api.dispatch_paddle_receipt") as dispatch, self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.post().status_code, 403)
        dispatch.assert_not_called()
        self.receipt.refresh_from_db(); self.assertEqual((self.receipt.state, self.receipt.attempts), ("failed", 3))
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.BILLING_RECONCILIATION_RETRY).exists())

    def test_method_denial_and_anonymous_managed_errors_remain_private(self):
        for response, status in ((self.browser.get(self.path), 405), (Client().post(self.path), 401)):
            self.assertEqual(response.status_code, status)
            self.assertIn("no-store", response["Cache-Control"])
            self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.BILLING_RECONCILIATION_RETRY).exists())

    def assure(self):
        get_user_model().objects.filter(pk=self.staff.pk).update(is_superuser=False)
        self.staff.refresh_from_db()
        self.permission = Permission.objects.get(content_type__app_label="tenancy", codename="change_paddlewebhookreceipt")
        self.staff.user_permissions.add(self.permission)
        self.request = staff_trial_request(self.staff, self.browser)

    def retry(self, **changes):
        self.request.session = self.browser.session
        return requeue_paddle_receipt(**{**dict(receipt=self.receipt, actor=self.staff, request=self.request,
            reason="Fixture reviewed provider recovery"), **changes})

    def original(self):
        return PaddleWebhookReceipt.objects.filter(pk=self.receipt.pk).values().get()

    def assert_retained(self, original):
        self.assertEqual(self.original(), original)
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.BILLING_RECONCILIATION_RETRY).exists())

    def test_genuine_change_only_mfa_queues_one_id_after_commit_without_provider_or_body_replay(self):
        self.assure()
        original = self.original()
        with override_settings(STAFF_MFA_REQUIRED=True), patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("tenancy.paddle_seller_api.dispatch_paddle_receipt") as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.post(); dispatch.assert_not_called()
            dispatch.assert_called_once_with(self.receipt.pk)
        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(response.json(), {"queued": True}); self.assertIn("no-store", response["Cache-Control"])
        after = self.original()
        self.assertEqual(after, {**original, "state": "pending", "attempts": 0, "claimed_at": None,
            "retry_after": None, "processed_at": None, "error_category": ""})
        event = AuditEvent.objects.get(event_type=AuditEventType.BILLING_RECONCILIATION_RETRY)
        self.assertEqual((event.actor_id, event.organization_id, event.project_id), (self.staff.pk, None, None))
        self.assertEqual(event.details, {"environment": "sandbox", "receipt_id": self.receipt.pk,
            "reason": "Fixture reviewed provider recovery"})
        self.assertNotIn(original["raw_digest"], response.content.decode())
        with patch("tenancy.paddle_seller_api.dispatch_paddle_receipt") as dispatch, self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.post().status_code, 409)
        dispatch.assert_not_called()

    def test_current_actor_permission_request_and_original_identity_are_required(self):
        self.assure()
        original = self.original()
        for reason in ("", " ", "x" * 251, True):
            with self.assertRaises(ValidationError): self.retry(reason=reason)
        with self.assertRaises(PermissionDenied): self.retry(actor=get_user_model().objects.create_user("receipt-other@example.invalid", None))
        self.staff.user_permissions.clear()
        self.staff.user_permissions.add(Permission.objects.get(content_type__app_label="tenancy", codename="view_paddlewebhookreceipt"))
        self.assertEqual(self.post().status_code, 403)
        self.staff.user_permissions.add(self.permission)
        for change in (lambda: get_user_model().objects.filter(pk=self.staff.pk).update(is_staff=False),
                lambda: get_user_model().objects.filter(pk=self.staff.pk).update(session_version="invalidated"),
                lambda: Session.objects.filter(session_key=self.browser.session.session_key).delete()):
            with transaction.atomic():
                change()
                with self.assertRaises(PermissionDenied): self.retry()
                transaction.set_rollback(True)
        with transaction.atomic():
            PaddleWebhookReceipt.objects.filter(pk=self.receipt.pk).update(raw_digest="a" * 64)
            with self.assertRaises(ValidationError): self.retry()
            transaction.set_rollback(True)
        self.assert_retained(original)

    def test_post_audit_signed_identity_state_date_or_session_loss_never_queues_or_audits(self):
        self.assure()
        original = self.original()
        create = AuditEvent.objects.create
        mutations = [lambda: self.staff.user_permissions.clear(),
            lambda: Session.objects.filter(session_key=self.browser.session.session_key).delete(),
            lambda: Authenticator.objects.filter(user=self.staff).delete(),
            lambda: get_user_model().objects.filter(pk=self.staff.pk).update(session_version="invalidated")]
        for changes in ({"event_id": "evt_" + "z" * 26}, {"notification_id": "ntf_" + "z" * 26},
                {"event_type": "transaction.paid"}, {"entity_id": "txn_" + "z" * 26}, {"raw_digest": "a" * 64},
                {"environment": "live"}, {"occurred_at": self.receipt.occurred_at + timedelta(microseconds=1)},
                {"received_at": self.receipt.received_at - timedelta(microseconds=1)},
                {"subscription_id": "sub_" + "z" * 26, "customer_id": "ctm_" + "z" * 26},
                {"processed_at": timezone.now()}, {"error_category": "provider_unavailable"},
                {"state": "processing", "attempts": 1, "claimed_at": timezone.now()}):
            mutations.append(lambda changes=changes: PaddleWebhookReceipt.objects.filter(pk=self.receipt.pk).update(**changes))
        for mutate in mutations:
            def changed(**kwargs):
                event = create(**kwargs); mutate(); return event
            cache.clear()
            with patch("tenancy.paddle_webhooks.AuditEvent.objects.create", side_effect=changed), \
                    patch("tenancy.paddle_seller_api.dispatch_paddle_receipt") as dispatch, self.captureOnCommitCallbacks(execute=True):
                self.assertIn(self.post().status_code, (403, 409))
            dispatch.assert_not_called(); self.assert_retained(original)
        with override_settings(PADDLE_ENVIRONMENT="sandbox"):
            def changed_environment(**kwargs):
                from django.conf import settings
                event = create(**kwargs); settings.PADDLE_ENVIRONMENT = "live"; return event
            with patch("tenancy.paddle_webhooks.AuditEvent.objects.create", side_effect=changed_environment), self.assertRaises(ValidationError):
                self.retry()
        self.assert_retained(original)

    def test_original_environment_age_boundary_future_and_late_expiry_are_fenced(self):
        self.assure()
        original = self.original()
        with override_settings(PADDLE_ENVIRONMENT="live"), self.assertRaises(ValidationError): self.retry()
        for moment in (self.receipt.received_at - timedelta(microseconds=1), self.receipt.received_at + timedelta(days=30, microseconds=1)):
            with patch("django.utils.timezone.now", return_value=moment):
                self.browser.force_login(self.staff); self.request = staff_trial_request(self.staff, self.browser)
                with self.assertRaises(ValidationError): self.retry()
        clock = self.receipt.received_at + timedelta(days=30)
        create = AuditEvent.objects.create
        def expired(**kwargs):
            nonlocal clock
            event = create(**kwargs); clock += timedelta(microseconds=1); return event
        with patch("django.utils.timezone.now", side_effect=lambda: clock):
            self.browser.force_login(self.staff); self.request = staff_trial_request(self.staff, self.browser)
            with patch("tenancy.paddle_webhooks.AuditEvent.objects.create", side_effect=expired), self.assertRaises(ValidationError): self.retry()
        self.assert_retained(original)
        # The pre-existing inclusive30-day boundary itself remains eligible.
        with patch("django.utils.timezone.now", return_value=self.receipt.received_at + timedelta(days=30)):
            self.browser.force_login(self.staff); self.request = staff_trial_request(self.staff, self.browser)
            self.assertEqual(self.retry().state, "pending")

    def test_audit_or_callback_registration_failure_rolls_back_receipt_without_dispatch(self):
        self.assure()
        original = self.original()
        for target in ("tenancy.paddle_webhooks.AuditEvent.objects.create", "tenancy.paddle_seller_api.transaction.on_commit"):
            with patch(target, side_effect=RuntimeError("fixture unavailable")), \
                    patch("tenancy.paddle_seller_api.dispatch_paddle_receipt") as dispatch, self.assertRaises(RuntimeError):
                self.post()
            dispatch.assert_not_called(); self.assert_retained(original)


@override_settings(**ReceiptRetryTests._overridden_settings)
class ReceiptRetryRaceTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        ReceiptRetryTests.setUp(self)
        self.requests = [staff_trial_request(self.staff) for _ in range(2)]

    def test_two_current_mfa_requests_requeue_failed_receipt_once(self):
        barrier = Barrier(2)
        def retry(index):
            close_old_connections()
            try:
                receipt = PaddleWebhookReceipt.objects.get(pk=self.receipt.pk)
                actor = get_user_model().objects.get(pk=self.staff.pk)
                barrier.wait(timeout=5)
                try:
                    requeue_paddle_receipt(receipt=receipt, actor=actor, reason=f"Fixture retry {index}", request=self.requests[index])
                    return "queued"
                except ValidationError:
                    return "not_failed"
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertCountEqual(list(executor.map(retry, range(2))), ["queued", "not_failed"])
        self.receipt.refresh_from_db(); self.assertEqual((self.receipt.state, self.receipt.attempts), ("pending", 0))
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.BILLING_RECONCILIATION_RETRY).count(), 1)
