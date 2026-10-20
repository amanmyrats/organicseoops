import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone as django_timezone

from .models import AuditEvent, AuditEventType, PaddleWebhookReceipt
from .paddle_seller import set_paddle_seller
from .paddle_webhooks import record_paddle_notification, verify_paddle_webhook
from .test_paddle_attempt import PRICE, PRODUCT
from .test_paddle_seller import SANDBOX_KEY, SANDBOX_TOKEN


NOW = datetime(2026, 9, 28, 10, tzinfo=timezone.utc)
SECRET = "fixture-webhook-secret"


def notification(*, event_id="evt_" + "a" * 26, event_type="transaction.completed"):
    return json.dumps({"event_id": event_id, "notification_id": "ntf_" + "b" * 26,
        "event_type": event_type, "occurred_at": NOW.isoformat(),
        "data": {"id": "txn_" + "c" * 26, "customer_email": "not-for-the-database@example.com"}},
        separators=(",", ":")).encode()


def header(raw, *, when=NOW, secret=SECRET):
    stamp = str(int(when.timestamp()))
    digest = hmac.new(secret.encode(), stamp.encode() + b":" + raw, hashlib.sha256).hexdigest()
    return f"ts={stamp};h1={digest}"


class WebhookSignatureTests(SimpleTestCase):
    def test_exact_bytes_multiple_signatures_and_strict_clock(self):
        raw = notification()
        result = verify_paddle_webhook(raw_body=raw, signature="ts=" + str(int(NOW.timestamp()))
            + ";h1=" + "0" * 64 + ";h1=" + header(raw).split("h1=")[1], secret=SECRET, now=NOW)
        self.assertEqual((result["entity_id"], result["state"]), ("txn_" + "c" * 26, "pending"))
        self.assertNotIn("customer_email", result)
        for body, signed, moment in (
            (raw + b" ", header(raw), NOW), (raw, header(raw, secret="different-signing-secret"), NOW),
            (raw, header(raw), NOW + timedelta(seconds=6)), (raw, header(raw), NOW - timedelta(seconds=6)),
            (raw, "ts=123;h1=" + "0" * 64, NOW), (raw, header(raw) + ";ts=123", NOW),
            (raw, "", NOW), (raw, header(raw) + ";foo=bar", NOW),
            (b"x" * (64 * 1024 + 1), header(raw), NOW),
        ):
            with self.subTest(signed=signed), self.assertRaises(ValidationError):
                verify_paddle_webhook(raw_body=body, signature=signed, secret=SECRET, now=moment)

    def test_signed_malformed_or_duplicate_key_cannot_be_received(self):
        for raw in (b'{"event_id":"one","event_id":"two"}',
                    notification().replace(NOW.isoformat().encode(), b"0"),
                    notification().replace(b'transaction.completed', b'subscription.created')):
            with self.subTest(raw=raw[:20]), self.assertRaises(ValidationError):
                verify_paddle_webhook(raw_body=raw, signature=header(raw), secret=SECRET, now=NOW)


@override_settings(PADDLE_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),))
class WebhookReceiptTests(TestCase):
    def setUp(self):
        staff = get_user_model().objects.create_superuser("webhook-operator@example.com", "password")
        self.staff = staff
        set_paddle_seller(actor=staff, environment="sandbox", api_key=SANDBOX_KEY,
            webhook_secret=SECRET, client_token=SANDBOX_TOKEN, product_id=PRODUCT, price_id=PRICE,
            currency="USD", amount="14900", interval="month", frequency=1)

    def test_verified_duplicate_event_is_one_digest_only_receipt(self):
        raw = notification()
        row, created = record_paddle_notification(environment="sandbox", raw_body=raw,
                                                   signature=header(raw), now=NOW)
        self.assertTrue(created)
        self.assertEqual(row.state, PaddleWebhookReceipt.State.PENDING)
        self.assertEqual(row.raw_digest, hashlib.sha256(raw).hexdigest())
        self.assertNotIn("not-for-the-database", str(list(PaddleWebhookReceipt.objects.values())))
        same, created = record_paddle_notification(environment="sandbox", raw_body=raw,
                                                     signature=header(raw), now=NOW)
        self.assertEqual((same.pk, created), (row.pk, False))
        changed = notification(event_type="transaction.paid")
        with self.assertRaises(ValidationError):
            record_paddle_notification(environment="sandbox", raw_body=changed,
                                        signature=header(changed), now=NOW)
        self.assertEqual(PaddleWebhookReceipt.objects.count(), 1)

    @override_settings(PADDLE_ENVIRONMENT="sandbox", STAFF_MFA_REQUIRED=False)
    def test_mfa_staff_retry_requeues_terminal_receipt_without_replaying_body(self):
        raw = notification()
        receipt, _ = record_paddle_notification(environment="sandbox", raw_body=raw,
                                                signature=header(raw), now=NOW)
        PaddleWebhookReceipt.objects.filter(pk=receipt.pk).update(state="failed", attempts=3,
            claimed_at=django_timezone.now(), error_category="provider_unavailable")
        path = f"/api/platform/billing/paddle/receipts/{receipt.pk}/retry/"
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.staff)
        browser.get("/_allauth/browser/v1/auth/session")
        payload = json.dumps({"reason": "Provider recovered"})
        self.assertEqual(browser.post(path, data=payload, content_type="application/json").status_code, 403)
        headers = {"HTTP_X_CSRFTOKEN": browser.cookies["csrftoken"].value}
        with override_settings(STAFF_MFA_REQUIRED=True):
            self.assertEqual(browser.post(path, data=payload, content_type="application/json",
                                           **headers).status_code, 403)
        from .test_trial_corrections import staff_trial_request
        staff_trial_request(self.staff, browser)
        with patch("tenancy.paddle_seller_api.dispatch_paddle_receipt") as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                response = browser.post(path, data=payload, content_type="application/json", **headers)
            self.assertEqual(response.status_code, 202)
            dispatch.assert_called_once_with(receipt.pk)
        receipt.refresh_from_db()
        self.assertEqual((receipt.state, receipt.attempts, receipt.retry_after), ("pending", 0, None))
        event = AuditEvent.objects.get(event_type=AuditEventType.BILLING_RECONCILIATION_RETRY)
        self.assertEqual(event.details["receipt_id"], receipt.pk)
        self.assertNotIn("customer_email", json.dumps(event.details))

    def test_wrong_environment_or_secret_does_not_create_receipt(self):
        raw = notification()
        with self.assertRaises(ValidationError):
            record_paddle_notification(environment="live", raw_body=raw, signature=header(raw), now=NOW)
        with self.assertRaises(ValidationError):
            record_paddle_notification(environment="sandbox", raw_body=raw,
                                       signature=header(raw, secret="other-signing-secret"), now=NOW)
        self.assertFalse(PaddleWebhookReceipt.objects.exists())

    @override_settings(PADDLE_ENVIRONMENT="sandbox")
    def test_public_webhook_accepts_only_signed_raw_delivery_once_without_csrf_cookie(self):
        browser = Client(enforce_csrf_checks=True)
        url = "/api/billing/paddle/webhooks/sandbox/"
        raw = notification()
        with patch("tenancy.paddle_webhooks.timezone.now", return_value=NOW):
            self.assertEqual(browser.get(url).status_code, 405)
            self.assertEqual(browser.post("/api/billing/paddle/webhooks/live/", data=raw,
                content_type="application/json", HTTP_PADDLE_SIGNATURE=header(raw)).status_code, 404)
            self.assertEqual(browser.post(url, data=raw, content_type="text/plain",
                HTTP_PADDLE_SIGNATURE=header(raw)).status_code, 415)
            self.assertEqual(browser.post(url, data=raw + b" ", content_type="application/json",
                HTTP_PADDLE_SIGNATURE=header(raw)).status_code, 400)
            self.assertEqual(browser.post(url, data=raw, content_type="application/json").status_code, 400)
            with patch("tenancy.paddle_webhook_api.dispatch_paddle_receipt") as dispatch:
                with self.captureOnCommitCallbacks(execute=True):
                    response = browser.post(url, data=raw, content_type="application/json",
                                            HTTP_PADDLE_SIGNATURE=header(raw))
                    self.assertEqual(response.status_code, 200, response.content)
                    self.assertEqual(response["Cache-Control"], "no-store")
                    self.assertEqual(browser.post(url, data=raw, content_type="application/json",
                        HTTP_PADDLE_SIGNATURE=header(raw)).status_code, 200)
                dispatch.assert_called_once_with(PaddleWebhookReceipt.objects.get().pk)
            self.assertEqual(browser.post(url, data=b"x" * (64 * 1024 + 1), content_type="application/json",
                HTTP_PADDLE_SIGNATURE=header(raw)).status_code, 413)
        self.assertEqual(PaddleWebhookReceipt.objects.count(), 1)
