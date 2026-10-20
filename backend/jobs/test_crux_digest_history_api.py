from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.db import connection, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from config.test_foundations import TEST_STORAGES
from tenancy.models import Organization, OrganizationMembership, Project
from . import crux_digest_history as history, test_crux_digest_history as fixtures
from .models import ProjectCruxAlertDelivery


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}),
                   GOOGLE_PERFORMANCE_API_KEY="fixture_key_with_32_placeholder_chars", CRUX_ALERT_DELIVERY_ENABLED=True,
                   EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                   CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "crux-history-api"}})
class CruxDigestHistoryApiTests(TransactionTestCase):
    date_part = staticmethod(fixtures.CruxDigestHistoryTests.date_part)
    history = fixtures.CruxDigestHistoryTests.history
    all_metrics = fixtures.CruxDigestHistoryTests.all_metrics
    collect = fixtures.CruxDigestHistoryTests.collect
    enable = fixtures.CruxDigestHistoryTests.enable
    reserve = fixtures.CruxDigestHistoryTests.reserve
    send = fixtures.CruxDigestHistoryTests.send
    other_recipient = fixtures.CruxDigestHistoryTests.other_recipient

    def setUp(self):
        cache.clear(); fixtures.CruxDigestHistoryTests.setUp(self)
        self.path = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/crux-alert-deliveries/"
        self.client = Client(); self.client.force_login(self.owner)
        self.row_id = self.reserve()

    def test_genuine_private_own_get_no_caller_scope_or_foreign_authority_or_effect(self):
        self.assertEqual(Client().get(self.path).status_code, 401)
        with CaptureQueriesContext(connection) as queries, patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("jobs.crux_digest_delivery.send_mail", side_effect=AssertionError("SMTP")):
            response = self.client.get(self.path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(response.json()["method_version"], history.METHOD)
        self.assertEqual([row["id"] for row in response.json()["rows"]], [self.row_id])
        self.assertFalse(any(q["sql"].lstrip().split()[0] in {"INSERT", "UPDATE", "DELETE"} for q in queries))
        for private in (self.owner.email, self.target, "recipient_id", "source_metadata", "claimed_episodes"):
            self.assertNotIn(private, response.content.decode())
        for query in ("?recipient_id=1", "?day_start=2020-01-01", "?after_id=1", "?delivery_id=1"):
            self.assertEqual(self.client.get(self.path + query).status_code, 400)
        self.assertEqual(self.client.generic("GET", self.path, "{}", content_type="application/json").status_code, 400)
        for method in ("POST", "PUT", "DELETE", "PATCH", "HEAD"):
            result = self.client.generic(method, self.path)
            self.assertEqual(result.status_code, 405); self.assertEqual(result["Allow"], "GET")
            self.assertEqual(result["Cache-Control"], "private, no-store")
        for unsafe in (0, 2**53):
            path = self.path.replace(f"projects/{self.project.pk}/", f"projects/{unsafe}/")
            self.assertEqual(self.client.get(path).status_code, 400)
        other, other_id = self.other_recipient()
        second = Client(); second.force_login(other)
        self.assertEqual([row["id"] for row in second.get(self.path).json()["rows"]], [other_id])
        with transaction.atomic():
            Project.objects.filter(pk=self.project.pk).update(access_restricted=True)
            self.assertEqual(second.get(self.path).status_code, 404)
            self.assertEqual(self.client.get(self.path).status_code, 200)
            transaction.set_rollback(True)
        OrganizationMembership.objects.filter(user=other, organization=self.organization).delete()
        self.assertEqual(second.get(self.path).status_code, 404)
        foreign = self.path.replace(f"organizations/{self.organization.pk}/", f"organizations/{self.organization.pk + 999}/")
        self.assertEqual(self.client.get(foreign).status_code, 404)

    @override_settings(ACCOUNT_RATE_LIMITS={"crux_delivery_history_read": "1/m/user,100/m/ip",
        "crux_preference_read": "100/m/user,100/m/ip", "alert_history_read": "100/m/user,100/m/ip"})
    def test_actual_user_ip_get_limit_and_independent_preference_operational_history(self):
        self.assertEqual(self.client.get(self.path).status_code, 200)
        response = self.client.get(self.path)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(self.client.get(self.path.replace("crux-alert-deliveries", "crux-alert-preference")).status_code, 200)
        self.assertEqual(self.client.get(self.path.replace("crux-alert-deliveries", "alert-deliveries")).status_code, 200)
        cache.clear(); other, _ = self.other_recipient()
        second = Client(); second.force_login(other)
        with override_settings(ACCOUNT_RATE_LIMITS={"crux_delivery_history_read": "100/m/user,1/m/ip"}):
            self.assertEqual(self.client.get(self.path).status_code, 200)
            self.assertEqual(second.get(self.path).status_code, 429)
            self.assertEqual(second.get(self.path, REMOTE_ADDR="192.0.2.11").status_code, 200)

    def test_final_source_reader_or_corrupt_category_date_has_only_generic_private_errors(self):
        original = history._row
        for mutate, status in ((lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True), 403),
                (lambda: ProjectCruxAlertDelivery.objects.filter(pk=self.row_id).update(created_at=self.assessed - timedelta(microseconds=1)), 409)):
            with transaction.atomic():
                def changed(row, assessed):
                    result = original(row, assessed); mutate(); return result
                with patch("jobs.crux_digest_history._row", side_effect=changed):
                    response = self.client.get(self.path)
                self.assertEqual(response.status_code, status); self.assertNotIn("rows", response.json())
                transaction.set_rollback(True)
        for fields in ({"error_category": "private exception body"}, {"day_start": self.assessed.date()}):
            with transaction.atomic():
                ProjectCruxAlertDelivery.objects.filter(pk=self.row_id).update(**fields)
                response = self.client.get(self.path)
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response["Cache-Control"], "private, no-store")
                self.assertNotIn("private exception body", response.content.decode()); self.assertNotIn("rows", response.json())
                transaction.set_rollback(True)
