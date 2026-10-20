import json
from unittest.mock import patch

from django.core.cache import cache
from django.db import connection, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from config.test_foundations import TEST_STORAGES
from tenancy.models import Organization, OrganizationMembership
from . import test_summary_history as fixtures
from .models import ProjectSummaryDelivery
from .summary_delivery import reserve_weekly_summary
from .summary_history import _row


@override_settings(STORAGES=TEST_STORAGES, WEEKLY_SUMMARY_DELIVERY_ENABLED=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/csv", "application/json"}),
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "weekly-history-api"}})
class WeeklyHistoryApiTests(TransactionTestCase):
    create_report = fixtures.WeeklyHistoryTests.create_report

    def setUp(self):
        cache.clear()
        fixtures.WeeklyHistoryTests.setUp(self)
        self.path = f"/api/organizations/{self.org.pk}/projects/{self.project.pk}/summary-deliveries/"
        self.client = Client(); self.client.force_login(self.owner)
        self.row_id = reserve_weekly_summary(project=self.project, recipient=self.owner)

    def test_actual_own_private_get_minimizes_history_and_denies_posted_or_foreign_authority(self):
        self.assertEqual(Client().get(self.path).status_code, 401)
        with CaptureQueriesContext(connection) as queries, patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("jobs.summary_delivery.send_mail", side_effect=AssertionError("SMTP")):
            response = self.client.get(self.path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual([row["id"] for row in response.json()["rows"]], [self.row_id])
        self.assertFalse(any(query["sql"].lstrip().split()[0] in {"INSERT", "UPDATE", "DELETE"} for query in queries))
        for private in (self.owner.email, self.report.artifact_key, self.finding.subject, "recipient_id", "source_metadata"):
            self.assertNotIn(private, response.content.decode())
        for query in ("?recipient_id=1", "?week_start=2020-01-01", "?after_id=1"):
            self.assertEqual(self.client.get(self.path + query).status_code, 400)
        self.assertEqual(self.client.generic("GET", self.path, "{}", content_type="application/json").status_code, 400)
        for method in ("POST", "PUT", "DELETE", "PATCH", "HEAD"):
            result = self.client.generic(method, self.path)
            self.assertEqual(result.status_code, 405)
            self.assertEqual(result["Allow"], "GET")
            self.assertEqual(result["Cache-Control"], "private, no-store")
        other = Client(); other.force_login(self.other)
        self.assertEqual(other.get(self.path).status_code, 404)
        OrganizationMembership.objects.create(organization=self.org, user=self.other, role="viewer")
        self.assertEqual(other.get(self.path).json()["rows"], [])
        foreign = self.path.replace(f"organizations/{self.org.pk}/", f"organizations/{self.org.pk + 999}/")
        self.assertEqual(self.client.get(foreign).status_code, 404)

    @override_settings(ACCOUNT_RATE_LIMITS={"summary_history_read": "1/m/user,100/m/ip",
                                          "summary_preference_read": "100/m/user,100/m/ip"})
    def test_actual_independent_user_and_shared_ip_get_budgets_enforce_private_429(self):
        self.assertEqual(self.client.get(self.path).status_code, 200)
        response = self.client.get(self.path)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(self.client.get(self.path.replace("summary-deliveries", "summary-preference")).status_code, 200)
        cache.clear()
        OrganizationMembership.objects.create(organization=self.org, user=self.other, role="viewer")
        other = Client(); other.force_login(self.other)
        with override_settings(ACCOUNT_RATE_LIMITS={"summary_history_read": "100/m/user,1/m/ip"}):
            self.assertEqual(self.client.get(self.path).status_code, 200)
            self.assertEqual(other.get(self.path).status_code, 429)
            self.assertEqual(other.get(self.path, REMOTE_ADDR="192.0.2.11").status_code, 200)

    def test_actual_mid_projection_current_reader_loss_and_untrusted_category_never_return_rows(self):
        def project_then_suspend(row):
            result = _row(row)
            Organization.objects.filter(pk=self.org.pk).update(is_suspended=True)
            return result
        with transaction.atomic():
            with patch("jobs.summary_history._row", side_effect=project_then_suspend):
                response = self.client.get(self.path)
            self.assertEqual(response.status_code, 403)
            self.assertNotIn("rows", response.json())
            transaction.set_rollback(True)
        ProjectSummaryDelivery.objects.filter(pk=self.row_id).update(error_category="private exception body")
        response = self.client.get(self.path)
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("private exception body", response.content.decode())
        self.assertNotIn("rows", response.json())
