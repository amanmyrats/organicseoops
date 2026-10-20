from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from config.test_foundations import TEST_STORAGES
from tenancy.models import Organization, OrganizationMembership, Project

from . import crux_threshold_policy as policy, test_crux_threshold_policy as fixtures
from .models import PerformanceObservationSnapshot


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}),
    GOOGLE_PERFORMANCE_API_KEY="fixture_key_with_32_placeholder_chars",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "crux-material-api"}})
class MaterialCruxApiTests(TransactionTestCase):
    date_part = staticmethod(fixtures.MaterialCruxSourceTests.date_part)
    history = fixtures.MaterialCruxSourceTests.history
    collect = fixtures.MaterialCruxSourceTests.collect
    all_metrics = fixtures.MaterialCruxSourceTests.all_metrics

    def setUp(self):
        cache.clear()
        fixtures.MaterialCruxSourceTests.setUp(self)
        self.row = self.collect(self.all_metrics())
        self.original_path = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/crux-history/{self.row.pk}/"
        self.path = self.original_path + "material-policy/"
        self.client.force_login(self.owner)

    def test_genuine_private_exact_policy_get_own_viewer_foreign_inputs_methods_and_legacy(self):
        self.assertEqual(Client().get(self.path).status_code, 401)
        with CaptureQueriesContext(connection) as queries, \
                patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("jobs.tasks.execute_performance_task.apply_async", side_effect=AssertionError("dispatch")), \
                patch("jobs.alert_digest_delivery.send_mail", side_effect=AssertionError("SMTP")):
            response = self.client.get(self.path)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual([row["state"] for row in response.json()["rows"]], ["material_threshold_worsening_candidate"] * 3)
        self.assertFalse(any(query["sql"].lstrip().split()[0] in {"INSERT", "UPDATE", "DELETE"} for query in queries))
        for private in (self.target, self.owner.email, self.row.raw_artifact.key, "performance_credential", "actor_id"):
            self.assertNotIn(private, response.content.decode())
        for query in ("?relative_floor=0", "?material_policy=false", "?recipient_id=1", "?assessed_at=2020-01-01"):
            self.assertEqual(self.client.get(self.path + query).status_code, 400)
        self.assertEqual(self.client.generic("GET", self.path, "{}", content_type="application/json").status_code, 400)
        for method in ("POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
            response = self.client.generic(method, self.path)
            self.assertEqual(response.status_code, 405); self.assertEqual(response["Allow"], "GET")
        for value in (0, 2**53):
            self.assertEqual(self.client.get(self.path.replace(f"crux-history/{self.row.pk}/", f"crux-history/{value}/")).status_code, 400)
        other = get_user_model().objects.create_user("crux-material-reader@example.invalid", password="fixture-password")
        client = Client(); client.force_login(other)
        self.assertEqual(client.get(self.path).status_code, 404)
        OrganizationMembership.objects.create(organization=self.organization, user=other, role="viewer")
        self.assertEqual(client.get(self.path).json()["source_fingerprint"], self.client.get(self.path).json()["source_fingerprint"])
        foreign = Project.objects.create(organization=self.organization, name="Foreign policy route",
            canonical_origin="https://foreign-policy.example.invalid")
        self.assertEqual(self.client.get(self.path.replace(f"projects/{self.project.pk}/", f"projects/{foreign.pk}/")).status_code, 403)
        self.assertEqual(self.client.get(self.path.replace(f"organizations/{self.organization.pk}/", "organizations/999999/")).status_code, 404)
        PerformanceObservationSnapshot.objects.filter(pk=self.row.pk).update(raw_sha256=None)
        with patch("jobs.crux_history_source.read_private_artifact", side_effect=AssertionError("legacy read")):
            result = self.client.get(self.path).json()
        self.assertEqual(result["state"], "unknown_original_raw_integrity"); self.assertEqual(result["rows"], [])

    @override_settings(ACCOUNT_RATE_LIMITS={"crux_threshold_policy_read": "1/m/user,100/m/ip",
                                          "crux_history_source_read": "100/m/user,100/m/ip"})
    def test_maintained_independent_private_user_and_ip_budgets(self):
        self.assertEqual(self.client.get(self.path).status_code, 200)
        response = self.client.get(self.path)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(self.client.get(self.original_path).status_code, 200)
        cache.clear()
        with override_settings(ACCOUNT_RATE_LIMITS={"crux_threshold_policy_read": "100/m/user,1/m/ip"}):
            other = get_user_model().objects.create_user("crux-material-ip@example.invalid", password="fixture-password")
            OrganizationMembership.objects.create(organization=self.organization, user=other, role="viewer")
            client = Client(); client.force_login(other)
            self.assertEqual(self.client.get(self.path).status_code, 200)
            self.assertEqual(client.get(self.path).status_code, 429)
            self.assertEqual(client.get(self.path, REMOTE_ADDR="192.0.2.12").status_code, 200)

    def test_private_generic_source_and_final_reader_loss_after_actual_policy_projection(self):
        original = policy._rows
        for mutate in (lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True),
                       lambda: PerformanceObservationSnapshot.objects.filter(pk=self.row.pk).update(raw_sha256=None)):
            with transaction.atomic():
                def changed(source):
                    result = original(source); mutate(); return result
                with patch("jobs.crux_threshold_policy._rows", side_effect=changed):
                    response = self.client.get(self.path)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(set(response.json()), {"message"})
                self.assertEqual(response["Cache-Control"], "private, no-store")
                self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
                transaction.set_rollback(True)
        with patch("jobs.crux_history_source.read_private_artifact", return_value=b"PRIVATE corrupted body"):
            response = self.client.get(self.path)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(set(response.json()), {"message"})
        self.assertNotIn("PRIVATE", response.content.decode())
