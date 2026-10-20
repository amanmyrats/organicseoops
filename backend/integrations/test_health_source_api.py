from datetime import timedelta
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection, transaction
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tenancy.models import Organization, OrganizationMembership, Project
from . import health_source, test_health_source as fixtures
from .models import SyncCursor


@override_settings(GOOGLE_OAUTH_CLIENT_ID="fixture-client", GOOGLE_OAUTH_CLIENT_SECRET="fixture-secret",
    GOOGLE_OAUTH_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),),
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "integration-health-api"}})
class IntegrationHealthApiTests(TestCase):
    queue = fixtures.IntegrationHealthSourceTests.queue
    execute = fixtures.IntegrationHealthSourceTests.execute

    def setUp(self):
        cache.clear()
        fixtures.IntegrationHealthSourceTests.setUp(self)
        self.execute()
        self.path = f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}/integration-health/"
        self.client.force_login(self.user)

    def test_genuine_worker_private_get_scope_input_and_no_side_effects(self):
        self.assertEqual(Client().get(self.path).status_code, 401)
        with CaptureQueriesContext(connection) as queries, \
                patch("integrations.google_tokens.http.client.HTTPSConnection", side_effect=AssertionError("network")), \
                patch("jobs.services.dispatch_pending", side_effect=AssertionError("dispatch")), \
                patch("jobs.summary_delivery.send_mail", side_effect=AssertionError("SMTP")):
            result = self.client.get(self.path)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result["Cache-Control"], "private, no-store")
        self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")
        self.assertFalse(any(q["sql"].lstrip().split()[0] in {"INSERT", "UPDATE", "DELETE"} for q in queries))
        self.assertEqual(result.json()["rows"][0]["sync"]["status"], "succeeded")
        self.assertEqual(result.json()["rows"][0]["connection_id"], self.connection.pk)
        for private in ("credential_reference", "selected_property", "encrypted", "position", self.user.email,
                        self.project.canonical_origin, "fixture-secret", "fixture-ciphertext"):
            self.assertNotIn(private, result.content.decode())
        for query in ("?connection_id=1", "?grant_id=1", "?recipient_id=1", "?assessed_at=2020-01-01"):
            self.assertEqual(self.client.get(self.path + query).status_code, 400)
        self.assertEqual(self.client.generic("GET", self.path, "{}", content_type="application/json").status_code, 400)
        for method in ("POST", "PUT", "PATCH", "DELETE", "HEAD"):
            response = self.client.generic(method, self.path)
            self.assertEqual(response.status_code, 405); self.assertEqual(response["Allow"], "GET")
        foreign = self.path.replace(f"organizations/{self.project.organization_id}/",
            f"organizations/{self.project.organization_id + 999}/")
        self.assertEqual(self.client.get(foreign).status_code, 404)
        other = get_user_model().objects.create_user("other-health-api@example.invalid", "test-password")
        client = Client(); client.force_login(other)
        self.assertEqual(client.get(self.path).status_code, 404)
        OrganizationMembership.objects.create(organization=self.project.organization, user=other, role="viewer")
        self.assertEqual(client.get(self.path).json()["rows"], result.json()["rows"])
        project = Project.objects.create(organization=self.project.organization, name="Other health API",
            canonical_origin="https://other-health-api.example.invalid")
        self.assertEqual(self.client.get(self.path.replace(f"projects/{self.project.pk}/", f"projects/{project.pk}/")).json()["rows"], [])
        Project.objects.filter(pk=self.project.pk).update(access_restricted=True)
        self.assertEqual(client.get(self.path).status_code, 404)

    @override_settings(ACCOUNT_RATE_LIMITS={"integration_health_read": "1/m/user,100/m/ip",
                                          "summary_history_read": "100/m/user,100/m/ip"})
    def test_actual_user_and_ip_limits_and_independent_existing_history_budget(self):
        self.assertEqual(self.client.get(self.path).status_code, 200)
        result = self.client.get(self.path)
        self.assertEqual(result.status_code, 429)
        self.assertEqual(result["Cache-Control"], "private, no-store")
        self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(self.client.get(self.path.replace("integration-health", "summary-deliveries")).status_code, 200)
        cache.clear()
        other = get_user_model().objects.create_user("ip-health-api@example.invalid", "test-password")
        OrganizationMembership.objects.create(organization=self.project.organization, user=other, role="viewer")
        client = Client(); client.force_login(other)
        with override_settings(ACCOUNT_RATE_LIMITS={"integration_health_read": "100/m/user,1/m/ip"}):
            self.assertEqual(self.client.get(self.path).status_code, 200)
            self.assertEqual(client.get(self.path).status_code, 429)
            self.assertEqual(client.get(self.path, REMOTE_ADDR="192.0.2.11").status_code, 200)

    def test_final_reader_source_loss_dates_and_unknown_errors_remain_generic_private(self):
        original = health_source._row
        for change, status in (
            (lambda: Organization.objects.filter(pk=self.project.organization_id).update(is_suspended=True), 403),
            (lambda: SyncCursor.objects.filter(connection=self.connection).update(error_category="", revision=999), 409)):
            with transaction.atomic():
                def mutate(record, origins, assessed):
                    result = original(record, origins, assessed); change(); return result
                with patch("integrations.health_source._row", side_effect=mutate):
                    result = self.client.get(self.path)
                self.assertEqual(result.status_code, status)
                self.assertNotIn("rows", result.json())
                self.assertEqual(result["Cache-Control"], "private, no-store")
                self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")
                transaction.set_rollback(True)
        SyncCursor.objects.filter(connection=self.connection).update(status="failed", error_category="private raw error")
        result = self.client.get(self.path)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["rows"][0]["sync"]["error_category"], "unclassified_failure")
        self.assertNotIn("private raw error", result.content.decode())
        SyncCursor.objects.filter(connection=self.connection).update(last_attempt_at=timezone.now() + timedelta(days=1))
        result = self.client.get(self.path)
        self.assertEqual(result.status_code, 409); self.assertNotIn("rows", result.json())
