import json

from cryptography.fernet import Fernet
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings

from .admin import PaddleSellerConfigurationAdmin
from .models import AuditEvent, Organization, PaddleSellerConfiguration, PaddleSubscription
from .paddle_seller import paddle_seller_secrets
from .paddle_seller import rotate_paddle_api_key


KEY = Fernet.generate_key().decode()
SANDBOX_KEY = "pdl_sdbx_apikey_" + "a" * 26 + "_" + "b" * 22 + "_cde"
LIVE_KEY = "pdl_live_apikey_" + "a" * 26 + "_" + "b" * 22 + "_cde"
SANDBOX_TOKEN = "test_" + "a" * 27
LIVE_TOKEN = "live_" + "b" * 27


@override_settings(PADDLE_ENCRYPTION_KEYS=(KEY,), STAFF_MFA_REQUIRED=False,
                   CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class SellerConfigurationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.staff = get_user_model().objects.create_superuser("paddle-staff@example.com", "test-password")
        self.customer = get_user_model().objects.create_user("paddle-customer@example.com", "test-password")

    def browser(self, user):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(user)
        browser.get("/_allauth/browser/v1/auth/session")
        return browser

    def request(self, browser, method, environment="sandbox", data=None, csrf=True):
        headers = {"HTTP_X_CSRFTOKEN": browser.cookies["csrftoken"].value,
                   "HTTP_REFERER": "http://testserver/"} if csrf else {}
        return getattr(browser, method)(f"/api/platform/billing/paddle/{environment}/",
                                        data=json.dumps(data) if data is not None else {},
                                        content_type="application/json", **headers)

    @staticmethod
    def payload(key=SANDBOX_KEY, token=SANDBOX_TOKEN):
        return {"api_key": key, "webhook_secret": "fixture-webhook-secret", "client_token": token,
                "product_id": "pro_" + "a" * 26, "price_id": "pri_" + "b" * 26,
                "currency": "USD", "amount": "14900", "interval": "month", "frequency": 1}

    def test_operator_config_is_write_only_environment_scoped_and_revocable(self):
        staff = self.browser(self.staff)
        customer = self.browser(self.customer)
        self.assertEqual(self.request(customer, "post", data=self.payload()).status_code, 403)
        self.assertEqual(self.request(staff, "post", data=self.payload(), csrf=False).status_code, 403)
        with override_settings(STAFF_MFA_REQUIRED=True):
            self.assertEqual(self.request(staff, "post", data=self.payload()).status_code, 403)
        result = self.request(staff, "post", data=self.payload())
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(result.json(), {"configured": True, "catalog_verified": False})
        row = PaddleSellerConfiguration.objects.get(environment="sandbox")
        self.assertNotIn(SANDBOX_KEY, row.encrypted_api_key)
        self.assertEqual(row.client_token, SANDBOX_TOKEN)
        self.assertNotIn("fixture-webhook-secret", row.encrypted_webhook_secret)
        self.assertNotIn("encrypted_api_key", PaddleSellerConfigurationAdmin(
            PaddleSellerConfiguration, admin.site).get_fields(None, row))
        self.assertNotIn("fixture-webhook-secret", json.dumps(list(AuditEvent.objects.values("details"))))
        self.assertEqual(paddle_seller_secrets("sandbox"),
                         (SANDBOX_KEY, "fixture-webhook-secret"))
        with self.assertRaises(ValidationError):
            paddle_seller_secrets("live")
        status = self.request(staff, "get")
        self.assertEqual(status.json()["catalog_verified"], False)
        self.assertNotIn("fixture", status.content.decode())
        self.assertEqual(status["Cache-Control"], "private, no-store")
        self.assertEqual(self.request(customer, "get").status_code, 403)
        self.assertEqual(self.request(staff, "post", "live", self.payload(SANDBOX_KEY)).status_code, 409)
        self.assertEqual(self.request(staff, "post", "live", self.payload(LIVE_KEY, LIVE_TOKEN)).status_code, 200)
        self.assertEqual(self.request(staff, "delete").json(), {"revoked": True})
        self.assertEqual(PaddleSellerConfiguration.objects.get(environment="sandbox").client_token, "")
        with self.assertRaises(ValidationError):
            paddle_seller_secrets("sandbox")
        self.assertEqual(paddle_seller_secrets("live")[0], LIVE_KEY)

    def test_invalid_catalog_and_absent_bootstrap_do_not_mutate(self):
        staff = self.browser(self.staff)
        for field, value in (("price_id", "pri_unsafe"), ("client_token", LIVE_TOKEN), ("amount", "14901"),
                             ("interval", "year"), ("api_key", "short"), ("frequency", True)):
            with self.subTest(field=field):
                cache.clear()
                data = self.payload()
                data[field] = value
                self.assertEqual(self.request(staff, "post", data=data).status_code, 409)
        cache.clear()
        with override_settings(PADDLE_ENCRYPTION_KEYS=()):
            self.assertEqual(self.request(staff, "post", data=self.payload()).status_code, 409)
        self.assertFalse(PaddleSellerConfiguration.objects.exists())
        self.assertFalse(AuditEvent.objects.exists())

    def test_linked_identity_blocks_unsafe_secret_rotation_and_scrub(self):
        staff = self.browser(self.staff)
        self.assertEqual(self.request(staff, "post", data=self.payload()).status_code, 200)
        organization = Organization.objects.create(name="Existing payer")
        PaddleSubscription.objects.create(organization=organization, environment="sandbox",
            customer_id="ctm_" + "a" * 26, subscription_id="sub_" + "b" * 26, status="active")
        self.assertEqual(self.request(staff, "post", data=self.payload(SANDBOX_KEY)).status_code, 409)
        self.assertEqual(self.request(staff, "delete").status_code, 409)
        self.assertEqual(paddle_seller_secrets("sandbox")[0], SANDBOX_KEY)
        path = "/api/platform/billing/paddle/sandbox/api-key/"
        next_key = SANDBOX_KEY[:-3] + "fgh"
        headers = {"HTTP_X_CSRFTOKEN": staff.cookies["csrftoken"].value,
                   "HTTP_REFERER": "http://testserver/"}
        self.assertEqual(staff.post(path, data=json.dumps({"api_key": next_key}),
                                    content_type="application/json").status_code, 403)
        with override_settings(STAFF_MFA_REQUIRED=True):
            self.assertEqual(staff.post(path, data=json.dumps({"api_key": next_key}),
                                        content_type="application/json", **headers).status_code, 403)
        self.assertEqual(staff.post(path, data=json.dumps({"api_key": next_key}),
                                    content_type="application/json", **headers).status_code, 200)
        self.assertEqual(paddle_seller_secrets("sandbox"), (next_key, "fixture-webhook-secret"))
        self.assertNotIn(next_key, json.dumps(list(AuditEvent.objects.values("details"))))

    def test_api_rotation_rewraps_webhook_and_rejects_unreadable_old_key_without_audit(self):
        staff = self.browser(self.staff)
        self.assertEqual(self.request(staff, "post", data=self.payload()).status_code, 200)
        replacement = SANDBOX_KEY[:-3] + "xyz"
        new_key = Fernet.generate_key().decode()
        old_audit_count = AuditEvent.objects.count()
        original = PaddleSellerConfiguration.objects.get(environment="sandbox")
        with override_settings(PADDLE_ENCRYPTION_KEYS=(new_key,)):
            with self.assertRaises(ValidationError):
                rotate_paddle_api_key(actor=self.staff, environment="sandbox", api_key=replacement)
        original.refresh_from_db()
        self.assertEqual(AuditEvent.objects.count(), old_audit_count)
        self.assertEqual(paddle_seller_secrets("sandbox"), (SANDBOX_KEY, "fixture-webhook-secret"))
        with override_settings(PADDLE_ENCRYPTION_KEYS=(new_key, KEY)):
            rotate_paddle_api_key(actor=self.staff, environment="sandbox", api_key=replacement)
        with override_settings(PADDLE_ENCRYPTION_KEYS=(new_key,)):
            self.assertEqual(paddle_seller_secrets("sandbox"), (replacement, "fixture-webhook-secret"))
        self.assertEqual(AuditEvent.objects.count(), old_audit_count + 1)
