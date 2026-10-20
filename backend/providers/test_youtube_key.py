import json
from unittest.mock import patch

from allauth.mfa.models import Authenticator
from cryptography.fernet import Fernet
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings

from tenancy.models import AuditEvent
from .admin import YouTubeAPIKeyAdmin
from .models import YouTubeAPIKey
from .youtube_key import set_youtube_key, youtube_key, revoke_youtube_key

OLD = Fernet.generate_key().decode()
NEW = Fernet.generate_key().decode()


@override_settings(PROVIDER_ENCRYPTION_KEYS=(OLD,), STAFF_MFA_REQUIRED=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class YouTubeKeyTests(TestCase):
    path = "/api/platform/integrations/youtube-key/"
    def setUp(self):
        cache.clear()
        self.staff = get_user_model().objects.create_superuser("youtube-staff@example.invalid", "test-password")
        self.browser = Client(enforce_csrf_checks=True)
        self.browser.force_login(self.staff)
        self.browser.get("/_allauth/browser/v1/auth/session", secure=True)

    def post(self, *, csrf=True, **changes):
        data = {"api_key": "fixture_youtube_dedicated_key", "api_project": "client-project", "daily_limit": 5, **changes}
        return self.browser.post(self.path, json.dumps(data), content_type="application/json", secure=True,
            **({"HTTP_X_CSRFTOKEN": self.browser.cookies["csrftoken"].value, "HTTP_REFERER": "https://testserver/"} if csrf else {}))

    def test_mfa_csrf_write_only_encryption_rotation_and_revocation_keep_client_quota(self):
        self.assertEqual(self.post(csrf=False).status_code, 403)
        self.assertEqual(self.post().status_code, 403)  # Also enforced in development.
        Authenticator.objects.create(user=self.staff, type=Authenticator.Type.TOTP, data={"secret": "test-only"})
        self.assertEqual(self.post().status_code, 403)  # Enrollment alone is not assurance.
        with patch("allauth.account.authentication.get_authentication_records", return_value=[{"method": "mfa"}]):
            saved = self.post()
            self.assertEqual(saved.status_code, 200, saved.content)
            record = YouTubeAPIKey.objects.get()
            self.assertNotIn("fixture_youtube", record.encrypted_secret)
            self.assertEqual(youtube_key(record.rotated_at.isoformat()), "fixture_youtube_dedicated_key")
            YouTubeAPIKey.objects.filter(pk=record.pk).update(attempted_requests=4)
            self.assertEqual(self.post(api_project="other-project").status_code, 409)
            with override_settings(PROVIDER_ENCRYPTION_KEYS=(NEW, OLD)):
                self.assertEqual(youtube_key(record.rotated_at.isoformat()), "fixture_youtube_dedicated_key")
                self.assertEqual(self.post(api_key="fixture_rotated_youtube_key").status_code, 200)
            record.refresh_from_db()
            self.assertEqual(record.attempted_requests, 4)
            with self.assertRaises(ValidationError):
                youtube_key(record.rotated_at.isoformat())  # Old infrastructure key cannot decrypt rotation.
            with override_settings(PROVIDER_ENCRYPTION_KEYS=(NEW,)):
                self.assertEqual(youtube_key(record.rotated_at.isoformat()), "fixture_rotated_youtube_key")
            listing = self.browser.get(self.path, secure=True)
            self.assertEqual(listing["Cache-Control"], "private, no-store")
            self.assertNotIn("fixture_", listing.content.decode() + json.dumps(list(AuditEvent.objects.values("details"))))
            self.assertNotIn("encrypted_secret", YouTubeAPIKeyAdmin(YouTubeAPIKey, admin.site).get_fields(None, record))
            revoke_youtube_key(actor=self.staff)
            self.assertEqual(self.post().status_code, 200)
            record.refresh_from_db()
            self.assertEqual(record.attempted_requests, 4)

    def test_unconfigured_encryption_and_customer_permissions_fail_closed(self):
        with override_settings(PROVIDER_ENCRYPTION_KEYS=()):
            with self.assertRaises(ValidationError):
                set_youtube_key(actor=self.staff, value="fixture_key_for_youtube", api_project="client-project", daily_limit=5)
        self.assertFalse(YouTubeAPIKey.objects.exists())
        customer = get_user_model().objects.create_user("youtube-customer@example.invalid", "test-password")
        self.browser.force_login(customer)
        self.assertEqual(self.browser.get(self.path).status_code, 403)
