import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from config.test_foundations import TEST_STORAGES
from tenancy.models import Organization, OrganizationMembership, Project

from . import crux_history_source as source, test_crux_history_source as fixtures
from .models import Artifact, JobStep, PerformanceObservationSnapshot


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}),
    GOOGLE_PERFORMANCE_API_KEY="fixture_key_with_32_placeholder_chars",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "crux-source-api"}})
class CruxHistorySourceApiTests(TransactionTestCase):
    date_part = staticmethod(fixtures.CruxHistorySourceTests.date_part)
    history = fixtures.CruxHistorySourceTests.history
    collect = fixtures.CruxHistorySourceTests.collect

    def setUp(self):
        cache.clear()
        fixtures.CruxHistorySourceTests.setUp(self)
        self.row = self.collect()
        self.path = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/crux-history/{self.row.pk}/"
        self.client.force_login(self.owner)

    def test_actual_worker_exact_private_read_input_methods_scope_and_legacy(self):
        self.assertEqual(Client().get(self.path).status_code, 401)
        with CaptureQueriesContext(connection) as queries, \
                patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("jobs.tasks.execute_performance_task.apply_async", side_effect=AssertionError("dispatch")), \
                patch("jobs.alert_digest_delivery.send_mail", side_effect=AssertionError("SMTP")):
            response = self.client.get(self.path)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(response.json()["comparisons"][0]["state"], "threshold_worsening_candidate")
        self.assertFalse(any(q["sql"].lstrip().split()[0] in {"INSERT", "UPDATE", "DELETE"} for q in queries))
        for private in (self.target, self.owner.email, self.row.raw_artifact.key, "performance_credential", "actor_id"):
            self.assertNotIn(private, response.content.decode())
        for query in ("?observation_id=1", "?assessed_at=2020-01-01", "?recipient_id=1", "?after_id=1"):
            self.assertEqual(self.client.get(self.path + query).status_code, 400)
        self.assertEqual(self.client.generic("GET", self.path, "{}", content_type="application/json").status_code, 400)
        for method in ("POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
            response = self.client.generic(method, self.path)
            self.assertEqual(response.status_code, 405); self.assertEqual(response["Allow"], "GET")
        for value in (0, 2**53):
            self.assertEqual(self.client.get(self.path.replace(f"crux-history/{self.row.pk}/", f"crux-history/{value}/")).status_code, 400)
        other = get_user_model().objects.create_user("crux-api-other@example.invalid", password="fixture-password")
        client = Client(); client.force_login(other)
        self.assertEqual(client.get(self.path).status_code, 404)
        OrganizationMembership.objects.create(organization=self.organization, user=other, role="viewer")
        self.assertEqual(client.get(self.path).json()["comparisons"], self.client.get(self.path).json()["comparisons"])
        # Explicit independent scope fixture; the selected real source cannot be borrowed by another project.
        foreign = Project.objects.create(organization=self.organization, name="Foreign source route",
            canonical_origin="https://foreign-crux-api.example.invalid")
        self.assertEqual(self.client.get(self.path.replace(f"projects/{self.project.pk}/", f"projects/{foreign.pk}/")).status_code, 403)
        self.assertEqual(self.client.get(self.path.replace(f"organizations/{self.organization.pk}/", "organizations/999999/")).status_code, 404)
        PerformanceObservationSnapshot.objects.filter(pk=self.row.pk).update(raw_sha256=None)
        with patch("jobs.crux_history_source.read_private_artifact", side_effect=AssertionError("legacy reconstruction")):
            self.assertEqual(self.client.get(self.path).json()["state"], "unknown_original_raw_integrity")

    @override_settings(ACCOUNT_RATE_LIMITS={"crux_history_source_read": "1/m/user,100/m/ip", "alert_history_read": "100/m/user,100/m/ip"})
    def test_maintained_private_user_ip_and_independent_read_budget(self):
        self.assertEqual(self.client.get(self.path).status_code, 200)
        response = self.client.get(self.path)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        history = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/alert-deliveries/"
        self.assertEqual(self.client.get(history).status_code, 200)
        cache.clear()
        other = get_user_model().objects.create_user("crux-ip-reader@example.invalid", password="fixture-password")
        OrganizationMembership.objects.create(organization=self.organization, user=other, role="viewer")
        client = Client(); client.force_login(other)
        with override_settings(ACCOUNT_RATE_LIMITS={"crux_history_source_read": "100/m/user,1/m/ip"}):
            self.assertEqual(self.client.get(self.path).status_code, 200)
            self.assertEqual(client.get(self.path).status_code, 429)
            self.assertEqual(client.get(self.path, REMOTE_ADDR="192.0.2.11").status_code, 200)

    def test_generic_errors_after_raw_source_or_final_reader_loss(self):
        original = source.read_private_artifact
        for mutate, status in ((lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True), 403),
                (lambda: JobStep.objects.filter(job_id=self.row.job_id).update(progress_percent=1), 403),
                (lambda: Artifact.objects.filter(pk=self.row.raw_artifact_id).update(size_bytes=0), 409)):
            with transaction.atomic():
                def changed(key):
                    raw = original(key); mutate(); return raw
                with patch("jobs.crux_history_source.read_private_artifact", side_effect=changed):
                    response = self.client.get(self.path)
                self.assertEqual(response.status_code, status, response.content)
                self.assertNotIn("comparisons", response.json())
                self.assertEqual(response["Cache-Control"], "private, no-store")
                self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
                transaction.set_rollback(True)
        output = dict(self.row.output); output["origin_fallback"] = 0
        PerformanceObservationSnapshot.objects.filter(pk=self.row.pk).update(output=output)
        response = self.client.get(self.path)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(set(response.json()), {"message"})
        self.assertNotIn(self.target, json.dumps(response.json()))
