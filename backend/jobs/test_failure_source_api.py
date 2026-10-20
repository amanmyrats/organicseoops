from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from config.test_foundations import TEST_STORAGES
from tenancy.models import Organization, OrganizationMembership, Project
from . import failure_source, test_failure_source as fixtures
from .models import JobRun


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "crawl-failure-api"}})
class CrawlFailureApiTests(TransactionTestCase):
    queue = fixtures.RetainedCrawlFailureTests.queue
    failed = fixtures.RetainedCrawlFailureTests.failed

    def setUp(self):
        cache.clear()
        fixtures.RetainedCrawlFailureTests.setUp(self)
        self.job = self.failed()
        self.path = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/crawl-failures/"
        self.client.force_login(self.owner)

    def test_actual_worker_failure_private_get_is_scoped_bounded_input_free_and_read_only(self):
        self.assertEqual(Client().get(self.path).status_code, 401)
        with CaptureQueriesContext(connection) as queries, patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("jobs.tasks.execute_crawl_job_task.apply_async", side_effect=AssertionError("dispatch")), \
                patch("jobs.summary_delivery.send_mail", side_effect=AssertionError("SMTP")):
            result = self.client.get(self.path)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result["Cache-Control"], "private, no-store")
        self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual([row["job_id"] for row in result.json()["rows"]], [self.job.pk])
        self.assertFalse(any(q["sql"].lstrip().split()[0] in {"INSERT", "UPDATE", "DELETE"} for q in queries))
        for private in (self.owner.email, self.project.canonical_origin, "input_snapshot", "output", "actor_id", "secret"):
            self.assertNotIn(private, result.content.decode())
        for query in ("?job_id=1", "?assessed_at=2020-01-01", "?recipient_id=1", "?after_id=1"):
            self.assertEqual(self.client.get(self.path + query).status_code, 400)
        self.assertEqual(self.client.generic("GET", self.path, "{}", content_type="application/json").status_code, 400)
        for method in ("POST", "PUT", "PATCH", "DELETE", "HEAD"):
            response = self.client.generic(method, self.path)
            self.assertEqual(response.status_code, 405); self.assertEqual(response["Allow"], "GET")
        other = get_user_model().objects.create_user("other-failure-api@example.invalid", "test-password")
        client = Client(); client.force_login(other)
        self.assertEqual(client.get(self.path).status_code, 404)
        OrganizationMembership.objects.create(organization=self.organization, user=other, role="viewer")
        self.assertEqual(client.get(self.path).json()["rows"], result.json()["rows"])
        foreign = self.path.replace(f"organizations/{self.organization.pk}/", f"organizations/{self.organization.pk + 999}/")
        self.assertEqual(self.client.get(foreign).status_code, 404)
        project = Project.objects.create(organization=self.organization, name="Other failure API project",
            canonical_origin="https://other-failure-api.example.invalid")
        self.assertEqual(self.client.get(self.path.replace(f"projects/{self.project.pk}/", f"projects/{project.pk}/")).json()["rows"], [])

    @override_settings(ACCOUNT_RATE_LIMITS={"crawl_failure_read": "1/m/user,100/m/ip", "summary_history_read": "100/m/user,100/m/ip"})
    def test_actual_user_ip_limits_and_independent_history_budget(self):
        self.assertEqual(self.client.get(self.path).status_code, 200)
        result = self.client.get(self.path)
        self.assertEqual(result.status_code, 429)
        self.assertEqual(result["Cache-Control"], "private, no-store")
        self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(self.client.get(self.path.replace("crawl-failures", "summary-deliveries")).status_code, 200)
        cache.clear()
        other = get_user_model().objects.create_user("ip-failure-api@example.invalid", "test-password")
        OrganizationMembership.objects.create(organization=self.organization, user=other, role="viewer")
        client = Client(); client.force_login(other)
        with override_settings(ACCOUNT_RATE_LIMITS={"crawl_failure_read": "100/m/user,1/m/ip"}):
            self.assertEqual(self.client.get(self.path).status_code, 200)
            self.assertEqual(client.get(self.path).status_code, 429)
            self.assertEqual(client.get(self.path, REMOTE_ADDR="192.0.2.11").status_code, 200)

    def test_final_reader_source_loss_and_untrusted_category_projection_never_disclose_stale_or_free_text(self):
        original = failure_source._row
        for change, status in ((lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True), 403),
            (lambda: JobRun.objects.filter(pk=self.job.pk).update(error_category="changed secret error"), 409)):
            with transaction.atomic():
                def project_then_change(row, assessed):
                    result = original(row, assessed); change(); return result
                with patch("jobs.failure_source._row", side_effect=project_then_change):
                    result = self.client.get(self.path)
                self.assertEqual(result.status_code, status)
                self.assertNotIn("rows", result.json()); self.assertNotIn("secret", result.content.decode())
                self.assertEqual(result["Cache-Control"], "private, no-store")
                transaction.set_rollback(True)
        JobRun.objects.filter(pk=self.job.pk).update(error_category="private provider error")
        result = self.client.get(self.path)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["rows"][0]["failure_category"], "unclassified_failure")
        self.assertNotIn("private provider error", result.content.decode())
        JobRun.objects.filter(pk=self.job.pk).update(created_at=self.job.updated_at + timedelta(microseconds=1))
        result = self.client.get(self.path)
        self.assertEqual(result.status_code, 409); self.assertNotIn("rows", result.json())
