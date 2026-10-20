import json
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings

from tenancy.models import AuditEvent

from .admin import PerformanceAPIKeyAdmin
from .models import PerformanceAPIKey
from .performance_key import google_performance_key


KEY = Fernet.generate_key().decode()
VALID = "fixture_key_with_32_placeholder_chars"


@override_settings(PERFORMANCE_ENCRYPTION_KEYS=(KEY,), GOOGLE_PERFORMANCE_API_KEY="",
                   STAFF_MFA_REQUIRED=False, SECURE_SSL_REDIRECT=False,
                   CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class PerformanceCredentialTests(TestCase):
    path = "/api/platform/integrations/performance-key/"

    def setUp(self):
        cache.clear()
        self.operator = get_user_model().objects.create_superuser("performance-operator@example.com", "test-password")
        self.customer = get_user_model().objects.create_user("performance-customer@example.com", "test-password")

    def browser(self, user):
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        client.get("/_allauth/browser/v1/auth/session", secure=True)
        return client

    def submit(self, browser, value, *, csrf=True):
        headers = ({"HTTP_X_CSRFTOKEN": browser.cookies["csrftoken"].value,
                    "HTTP_REFERER": "https://testserver/"} if csrf else {})
        return browser.post(self.path, data=json.dumps({"api_key": value}),
                            content_type="application/json", secure=True, **headers)

    def test_operator_key_is_write_only_rotatable_and_revocation_overrides_env(self):
        staff = self.browser(self.operator)
        self.assertEqual(staff.get(self.path, secure=True).json(), {"state": "unconfigured"})
        self.assertEqual(self.submit(staff, VALID, csrf=False).status_code, 403)
        response = self.submit(staff, VALID)
        self.assertEqual((response.status_code, response.json()), (200, {"configured": True}))
        record = PerformanceAPIKey.objects.get(key="primary")
        self.assertNotIn(VALID, record.encrypted_secret)
        self.assertTrue(record.encrypted_secret.startswith("v1:"))
        self.assertEqual(google_performance_key(), VALID)
        self.assertNotIn("encrypted_secret", PerformanceAPIKeyAdmin(PerformanceAPIKey, admin.site).get_fields(None, record))
        self.assertNotIn(VALID, response.content.decode() + staff.get(self.path, secure=True).content.decode()
                         + json.dumps(list(AuditEvent.objects.values("details"))))
        self.assertEqual(response["Cache-Control"], "private, no-store")

        new = "fixture_new_key_with_32_placeholder_chars"
        with override_settings(PERFORMANCE_ENCRYPTION_KEYS=(Fernet.generate_key().decode(), KEY)):
            self.assertEqual(google_performance_key(), VALID)
            self.assertEqual(self.submit(staff, new).status_code, 200)
            self.assertEqual(google_performance_key(), new)
        with override_settings(PERFORMANCE_ENCRYPTION_KEYS=(KEY,)):
            with self.assertRaises(ValidationError):
                google_performance_key()
        headers = {"HTTP_X_CSRFTOKEN": staff.cookies["csrftoken"].value,
                   "HTTP_REFERER": "https://testserver/"}
        self.assertEqual(staff.delete(self.path, secure=True, **headers).json(), {"revoked": True})
        with override_settings(GOOGLE_PERFORMANCE_API_KEY=VALID):
            with self.assertRaises(ValidationError):
                google_performance_key()
        record.refresh_from_db()
        self.assertEqual(record.encrypted_secret, "")

    def test_wrong_role_invalid_key_and_absent_bootstrap_fail_closed(self):
        customer = self.browser(self.customer)
        self.assertEqual(self.submit(customer, VALID).status_code, 403)
        self.assertEqual(customer.get(self.path, secure=True).status_code, 403)
        staff = self.browser(self.operator)
        self.assertEqual(self.submit(staff, "bad\nkey").status_code, 409)
        with override_settings(PERFORMANCE_ENCRYPTION_KEYS=()):
            self.assertEqual(self.submit(staff, VALID).status_code, 409)
        self.assertFalse(PerformanceAPIKey.objects.exists())
        with patch("providers.performance_key._cipher", side_effect=ValidationError("Unavailable")):
            self.assertEqual(self.submit(staff, VALID).status_code, 409)
        self.assertFalse(PerformanceAPIKey.objects.exists())

    def test_platform_performance_key_write_requires_staff_mfa_when_enforced(self):
        staff = self.browser(self.operator)
        with override_settings(STAFF_MFA_REQUIRED=True):
            response = self.submit(staff, VALID)
        self.assertEqual((response.status_code, response.json()["errors"][0]["code"]), (403, "mfa_required"))
        self.assertFalse(PerformanceAPIKey.objects.exists())
