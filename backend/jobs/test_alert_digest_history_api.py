from unittest.mock import patch

from cryptography.fernet import Fernet
from django.core.cache import cache
from django.db import connection, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import Organization, OrganizationMembership
from . import alert_digest_history as history, test_alert_digest_history as fixtures
from .alert_digest_delivery import reserve_daily_alert_digest
from .models import ProjectAlertDelivery


@override_settings(STORAGES=TEST_STORAGES, ALERT_DIGEST_DELIVERY_ENABLED=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", GOOGLE_OAUTH_CLIENT_ID="fixture-client",
    GOOGLE_OAUTH_CLIENT_SECRET="fixture-secret", GOOGLE_OAUTH_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),),
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "daily-history-api"}})
class DailyDigestHistoryApiTests(TransactionTestCase):
    captureOnCommitCallbacks = fixtures.DailyDigestHistoryTests.captureOnCommitCallbacks
    failed = fixtures.DailyDigestHistoryTests.failed
    deny = fixtures.DailyDigestHistoryTests.deny
    enable = fixtures.DailyDigestHistoryTests.enable
    other_recipient = fixtures.DailyDigestHistoryTests.other_recipient

    def setUp(self):
        cache.clear()
        fixtures.DailyDigestHistoryTests.setUp(self)
        self.path = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/alert-deliveries/"
        self.client = Client(); self.client.force_login(self.user)
        self.row_id = reserve_daily_alert_digest(project=self.project, recipient=self.user)

    def test_genuine_private_own_get_no_recipient_input_or_foreign_authority_or_effect(self):
        self.assertEqual(Client().get(self.path).status_code, 401)
        with CaptureQueriesContext(connection) as queries, patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("jobs.alert_digest_delivery.send_mail", side_effect=AssertionError("SMTP")):
            response = self.client.get(self.path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual([row["id"] for row in response.json()["rows"]], [self.row_id])
        self.assertFalse(any(q["sql"].lstrip().split()[0] in {"INSERT", "UPDATE", "DELETE"} for q in queries))
        for private in (self.user.email, self.project.canonical_origin, "recipient_id", "source_metadata", "claimed_episodes"):
            self.assertNotIn(private, response.content.decode())
        for query in ("?recipient_id=1", "?day_start=2020-01-01", "?after_id=1"):
            self.assertEqual(self.client.get(self.path + query).status_code, 400)
        self.assertEqual(self.client.generic("GET", self.path, "{}", content_type="application/json").status_code, 400)
        for method in ("POST", "PUT", "DELETE", "PATCH", "HEAD"):
            result = self.client.generic(method, self.path)
            self.assertEqual(result.status_code, 405)
            self.assertEqual(result["Allow"], "GET")
            self.assertEqual(result["Cache-Control"], "private, no-store")
        other, other_id = self.other_recipient()
        second = Client(); second.force_login(other)
        self.assertEqual([row["id"] for row in second.get(self.path).json()["rows"]], [other_id])
        OrganizationMembership.objects.filter(user=other, organization=self.organization).delete()
        self.assertEqual(second.get(self.path).status_code, 404)
        foreign = self.path.replace(f"organizations/{self.organization.pk}/", f"organizations/{self.organization.pk + 999}/")
        self.assertEqual(self.client.get(foreign).status_code, 404)

    @override_settings(ACCOUNT_RATE_LIMITS={"alert_history_read": "1/m/user,100/m/ip",
                                           "alert_preference_read": "100/m/user,100/m/ip"})
    def test_actual_user_shared_ip_get_limit_and_independent_preference_read(self):
        self.assertEqual(self.client.get(self.path).status_code, 200)
        response = self.client.get(self.path)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(self.client.get(self.path.replace("alert-deliveries", "alert-preference")).status_code, 200)
        cache.clear()
        other, _other_id = self.other_recipient()
        second = Client(); second.force_login(other)
        with override_settings(ACCOUNT_RATE_LIMITS={"alert_history_read": "100/m/user,1/m/ip"}):
            self.assertEqual(self.client.get(self.path).status_code, 200)
            self.assertEqual(second.get(self.path).status_code, 429)
            self.assertEqual(second.get(self.path, REMOTE_ADDR="192.0.2.11").status_code, 200)

    def test_final_source_reader_or_corrupt_category_date_has_only_generic_private_errors(self):
        original = history._row
        with transaction.atomic():
            def suspend(row, assessed):
                result = original(row, assessed)
                Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True)
                return result
            with patch("jobs.alert_digest_history._row", side_effect=suspend):
                response = self.client.get(self.path)
            self.assertEqual(response.status_code, 403)
            self.assertNotIn("rows", response.json())
            transaction.set_rollback(True)
        for fields in ({"error_category": "private exception body"}, {"day_start": timezone.now().date()}):
            with transaction.atomic():
                ProjectAlertDelivery.objects.filter(pk=self.row_id).update(**fields)
                response = self.client.get(self.path)
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response["Cache-Control"], "private, no-store")
                self.assertNotIn("private exception body", response.content.decode())
                self.assertNotIn("rows", response.json())
                transaction.set_rollback(True)
