from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.db import connection, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import OrganizationMembership, OrganizationTrial, ProjectOriginVerification
from . import passive_header_api as api
from . import passive_resource_collection as collector
from . import test_passive_resource_api as fixtures
from .models import Artifact, Finding, JobCancellation, JobRun, JobStep, SourceCitation, UsageReservation


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "resource-candidates-api"}})
class ResourceCandidateApiTests(TransactionTestCase):
    setUp = fixtures.PassiveResourceApiTests.setUp
    verified = fixtures.PassiveResourceApiTests.verified
    transport = fixtures.PassiveResourceApiTests.transport
    post = fixtures.PassiveResourceApiTests.post
    command = fixtures.PassiveResourceApiTests.command

    def collected(self, key="resource-candidate-api", body=None):
        job_id = self.post(data=self.command("resource-" + key)).json()["job"]["id"]
        self.assertTrue(collector.execute_passive_resource_collection(job_id, fetcher=self.transport(body=body)))
        self.path = self.base + f"{job_id}/candidates/"
        return job_id

    def test_genuine_current_original_get_is_read_only_private_and_no_collection_or_materialization(self):
        job_id = self.collected()
        with patch("socket.create_connection", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            result = self.client.get(self.path, secure=True)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        report = result.json()["candidates"]
        self.assertEqual((report["job_id"], report["source_current"]), (job_id, True))
        self.assertEqual(report["collection"]["observed_at"], JobRun.objects.get(pk=job_id).output["observed_at"])
        self.assertEqual(report["candidates"][0]["evidence"]["counts"]["http_absolute"], 1)
        self.assertFalse(Finding.objects.exists()); self.connection.request.assert_called_once()
        for raw in (b"private.invalid", b"secret", self.challenge.encode(), self.owner.email.encode()): self.assertNotIn(raw, result.content)
        self.assertEqual(result["Cache-Control"], "private, no-store"); self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")

    def test_observed_empty_unclassified_and_original_lexical_null_remain_distinct(self):
        for key, body, state in (("empty", b"", "original_lexical_review_candidates"),
            ("unknown", b'<img src="relative">', "original_lexical_review_candidates"),
            ("lexical", b'<img src="x" src="y">', "original_lexical_evaluation_unavailable")):
            self.collected(key, body)
            result = self.client.get(self.path, secure=True)
            self.assertEqual(result.status_code, 200, result.content)
            report = result.json()["candidates"]
            self.assertEqual((report["state"], report["candidates"]), (state, []))
            if key == "lexical": self.assertEqual(report["reason"], "ambiguous_markup")

    def test_fixed_method_input_roles_tenant_family_and_failed_originals_deny(self):
        job_id = self.collected()
        self.assertEqual(Client().get(self.path, secure=True).status_code, 401)
        for query in ("?family=headers", "?job_id=1", "?extra=x"):
            self.assertEqual(self.client.get(self.path + query, secure=True).status_code, 400)
        self.assertEqual(self.client.generic("GET", self.path, b"{}", content_type="application/json", secure=True).status_code, 400)
        self.assertEqual(self.post(f"{job_id}/candidates/", {}).status_code, 405)
        self.assertEqual(self.client.head(self.path, secure=True).status_code, 405)
        for actor, status in ((self.member, 403), (self.outsider, 404)):
            client = Client(); client.force_login(actor); self.assertEqual(client.get(self.path, secure=True).status_code, status)
        for changes, status in (({"status": "failed"}, 403), ({"handler": "collect_passive_headers"}, 403),
            ({"handler": "collect_passive_tls"}, 403), ({"handler": "collect_passive_redirects"}, 403), ({"output": {}}, 409)):
            with transaction.atomic():
                JobRun.objects.filter(pk=job_id).update(**changes)
                self.assertEqual(self.client.get(self.path, secure=True).status_code, status)
                transaction.set_rollback(True)
        self.assertEqual(self.client.get(self.path.replace("passive-resources", "passive-headers"), secure=True).status_code, 403)
        self.assertEqual(self.client.get(self.path.replace(f"projects/{self.project.pk}/", "projects/9007199254740991/"), secure=True).status_code, 404)

    def test_shared_resource_read_user_ip_budget_is_independent_of_header_read_and_selection(self):
        self.collected()
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        other = Client(); other.force_login(self.member)
        for limit in ("1/m/user", "1/m/ip"):
            cache.clear()
            with override_settings(ACCOUNT_RATE_LIMITS={"passive_resource_read": limit}):
                self.assertEqual(self.client.get(self.path, secure=True).status_code, 200)
                self.assertEqual(self.client.get(self.base, secure=True).status_code, 429)
                self.assertEqual(self.client.get(self.path, secure=True).status_code, 429)
                if limit.endswith("ip"): self.assertEqual(other.get(self.path, secure=True).status_code, 429)
                self.assertEqual(self.client.get(self.base.replace("passive-resources", "passive-headers"), secure=True).status_code, 200)
                self.assertEqual(self.post("selection/").status_code, 200)

    def test_post_serialization_full_source_actor_caller_commercial_cancel_and_natural_expiry_fences(self):
        job_id = self.collected(); response = api._response
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        self.client.force_login(self.member)
        def expire():
            start = timezone.now() - timedelta(days=31)
            OrganizationTrial.objects.filter(organization=self.organization).update(started_at=start, ends_at=start + timedelta(days=30))
        changes = (
            lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member"),
            lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="viewer"),
            lambda: ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(challenge_digest="a" * 64),
            lambda: JobRun.objects.filter(pk=job_id).update(idempotency_key="changed-original"),
            lambda: JobStep.objects.filter(job_id=job_id).update(created_at=timezone.now()),
            lambda: Artifact.objects.filter(job_id=job_id).update(created_at=timezone.now()),
            lambda: SourceCitation.objects.filter(job_id=job_id).update(source_title="Changed"),
            lambda: UsageReservation.objects.filter(job_id=job_id).update(period_start=timezone.now().date() - timedelta(days=1)),
            lambda: JobCancellation.objects.create(job_id=job_id, requested_by=self.owner), expire)
        for change in changes:
            with transaction.atomic():
                def serialized(data, *args, **kwargs):
                    result = response(data, *args, **kwargs)
                    if "candidates" in data: change()
                    return result
                with patch.object(api, "_response", side_effect=serialized): result = self.client.get(self.path, secure=True)
                self.assertEqual(result.status_code, 403, result.content); self.assertNotIn(b"http_absolute", result.content)
                transaction.set_rollback(True)
        ends = timezone.now() + timedelta(seconds=5)
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=ends - timedelta(days=30), ends_at=ends)
        finished = False
        def expiring_response(data, *args, **kwargs):
            nonlocal finished
            result = response(data, *args, **kwargs)
            if "candidates" in data: finished = True
            return result
        with patch("jobs.usage.timezone.now", side_effect=lambda: ends if finished else ends - timedelta(seconds=1)), patch.object(
            api, "_response", side_effect=expiring_response): result = self.client.get(self.path, secure=True)
        self.assertTrue(finished); self.assertEqual(result.status_code, 403); self.assertNotIn(b"http_absolute", result.content)
