from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.db import connection, transaction
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from config.test_foundations import TEST_STORAGES
from tenancy.models import Organization, OrganizationMembership, Project
from . import support_job_reference as reference, test_support_job_reference as fixtures
from .models import JobRun


@override_settings(DEBUG=True, STORAGES=TEST_STORAGES,
                   CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "support-reference-api"}})
class SupportJobReferenceApiTests(TestCase):
    queue = fixtures.SupportJobReferenceTests.queue

    def setUp(self):
        cache.clear(); fixtures.SupportJobReferenceTests.setUp(self)
        self.job = self.queue(); self.client = Client(); self.client.force_login(self.owner)
        self.path = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/support-job-reference/{self.job.pk}/"

    def test_genuine_minimized_private_get_strict_input_roles_scope_and_no_effect(self):
        self.assertEqual(Client().get(self.path).status_code, 401)
        with override_settings(DEBUG=False), CaptureQueriesContext(connection) as queries, \
                patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("jobs.services.dispatch_pending", side_effect=AssertionError("dispatch")):
            response = self.client.get(self.path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["method_version"], reference.METHOD)
        self.assertEqual(response.json()["job"]["id"], self.job.pk)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))
        for value in (self.owner.email, self.project.canonical_origin, "actor_id", "output", "error_category"):
            self.assertNotIn(value, response.content.decode())
        for extra in ("?actor_id=1", "?include_output=1", "?job_id=1", "?at=2026-10-04"):
            self.assertEqual(self.client.get(self.path + extra).status_code, 400)
        self.assertEqual(self.client.generic("GET", self.path, "{}", content_type="application/json").status_code, 400)
        for method in ("POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"):
            result = self.client.generic(method, self.path)
            self.assertEqual(result.status_code, 405); self.assertEqual(result["Allow"], "GET")
            self.assertEqual(result["Cache-Control"], "private, no-store")
        for key, value in (("organizations", self.organization.pk), ("projects", self.project.pk), ("support-job-reference", self.job.pk)):
            for invalid in (0, 2**53):
                self.assertEqual(self.client.get(self.path.replace(f"{key}/{value}/", f"{key}/{invalid}/")).status_code, 400)
        other = Client(); other.force_login(self.outsider)
        self.assertEqual(other.get(self.path).status_code, 404)
        OrganizationMembership.objects.create(organization=self.organization, user=self.outsider, role="viewer")
        self.assertEqual(other.get(self.path).status_code, 200)
        with transaction.atomic():
            Project.objects.filter(pk=self.project.pk).update(access_restricted=True)
            self.assertEqual(other.get(self.path).status_code, 404)
            transaction.set_rollback(True)
        wrong = self.path.replace(f"organizations/{self.organization.pk}/", f"organizations/{self.other_org.pk}/")
        self.assertEqual(self.client.get(wrong).status_code, 404)
        missing = self.client.get(self.path.replace(f"reference/{self.job.pk}/", f"reference/{self.job.pk + 9999}/"))
        foreign = other.get(self.path.replace(f"organizations/{self.organization.pk}/projects/{self.project.pk}/",
                                             f"organizations/{self.other_org.pk}/projects/{self.other_project.pk}/"))
        self.assertEqual(missing.status_code, 200); self.assertEqual(foreign.status_code, 200)
        self.assertEqual(missing.json()["job"], foreign.json()["job"])
        self.assertEqual(missing.json()["state"], foreign.json()["state"])

    @override_settings(ACCOUNT_RATE_LIMITS={"support_job_reference_read": "1/m/user,100/m/ip",
                                          "crux_delivery_history_read": "100/m/user,100/m/ip"})
    def test_actual_get_user_ip_limit_and_independent_crux_history_budget(self):
        self.assertEqual(self.client.get(self.path).status_code, 200)
        result = self.client.get(self.path)
        self.assertEqual(result.status_code, 429); self.assertEqual(result["Cache-Control"], "private, no-store")
        self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")
        other_path = self.path.replace(f"support-job-reference/{self.job.pk}", "crux-alert-deliveries")
        self.assertEqual(self.client.get(other_path).status_code, 200)
        cache.clear(); OrganizationMembership.objects.create(organization=self.organization, user=self.outsider, role="viewer")
        other = Client(); other.force_login(self.outsider)
        with override_settings(ACCOUNT_RATE_LIMITS={"support_job_reference_read": "100/m/user,1/m/ip"}):
            self.assertEqual(self.client.get(self.path).status_code, 200)
            self.assertEqual(other.get(self.path).status_code, 429)
            self.assertEqual(other.get(self.path, REMOTE_ADDR="192.0.2.11").status_code, 200)

    def test_final_current_reader_source_or_date_loss_has_only_generic_private_errors(self):
        original = reference._row
        for change, status in ((lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True), 403),
                (lambda: JobRun.objects.filter(pk=self.job.pk).update(status="cancelled"), 409)):
            with transaction.atomic():
                def mutate(row, assessed):
                    result = original(row, assessed); change(); return result
                with patch("jobs.support_job_reference._row", side_effect=mutate): response = self.client.get(self.path)
                self.assertEqual(response.status_code, status); self.assertNotIn("job", response.json())
                self.assertEqual(response["Cache-Control"], "private, no-store")
                transaction.set_rollback(True)
        JobRun.objects.filter(pk=self.job.pk).update(updated_at=self.job.created_at - timedelta(microseconds=1))
        response = self.client.get(self.path)
        self.assertEqual(response.status_code, 409); self.assertNotIn("job", response.json())
        self.assertNotIn(self.owner.email, response.content.decode())
