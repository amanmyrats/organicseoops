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
from . import passive_header_collection as collector
from . import test_passive_header_api as fixtures
from .models import Artifact, JobCancellation, JobRun, JobStep, SourceCitation, UsageReservation


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "header-candidates-api"}})
class HeaderCandidateApiTests(TransactionTestCase):
    setUp = fixtures.PassiveHeaderApiTests.setUp
    verified = fixtures.PassiveHeaderApiTests.verified
    transport = fixtures.PassiveHeaderApiTests.transport
    post = fixtures.PassiveHeaderApiTests.post
    command = fixtures.PassiveHeaderApiTests.command

    def collected(self):
        job_id = self.post(data=self.command()).json()["job"]["id"]
        self.assertTrue(collector.execute_passive_header_collection(job_id, fetcher=self.transport()))
        self.path = self.base + f"{job_id}/candidates/"
        return job_id

    def test_genuine_private_get_preserves_original_facts_without_writes_or_collection(self):
        job_id = self.collected()
        with patch("socket.create_connection", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            result = self.client.get(self.path, secure=True)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        report = result.json()["candidates"]
        self.assertEqual((report["job_id"], report["source_current"]), (job_id, True))
        self.assertEqual(report["collection"]["observed_at"], JobRun.objects.get(pk=job_id).output["observed_at"])
        self.assertTrue(report["candidates"])
        for private in (b"secret", b"nonce-private", self.challenge.encode()): self.assertNotIn(private, result.content)
        self.assertEqual(result["Cache-Control"], "private, no-store")
        self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(self.connection.request.call_count, 1)

    def test_exact_method_input_scope_roles_and_unavailable_originals_are_denied(self):
        job_id = self.collected()
        self.assertEqual(Client().get(self.path, secure=True).status_code, 401)
        self.assertEqual(self.client.get(self.path + "?family=tls", secure=True).status_code, 400)
        self.assertEqual(self.client.generic("GET", self.path, b"{}", content_type="application/json", secure=True).status_code, 400)
        self.assertEqual(self.client.post(self.path, "{}", content_type="application/json", secure=True,
            HTTP_X_CSRFTOKEN=self.csrf, HTTP_REFERER="https://testserver/").status_code, 405)
        self.assertEqual(self.client.head(self.path, secure=True).status_code, 405)
        for actor, status in ((self.member, 403), (self.outsider, 404)):
            client = Client(); client.force_login(actor)
            self.assertEqual(client.get(self.path, secure=True).status_code, status)
        for changes, status in (({"status": "failed"}, 403), ({"handler": "collect_passive_redirects"}, 403), ({"output": {}}, 409)):
            with transaction.atomic():
                JobRun.objects.filter(pk=job_id).update(**changes)
                result = self.client.get(self.path, secure=True)
                self.assertEqual(result.status_code, status, result.content)
                self.assertNotIn(b"cookies", result.content)
                transaction.set_rollback(True)
        foreign_path = self.path.replace(f"projects/{self.project.pk}/", "projects/9007199254740991/")
        self.assertEqual(self.client.get(foreign_path, secure=True).status_code, 404)

    def test_candidate_and_original_read_share_maintained_user_ip_budget_without_consuming_selection(self):
        self.collected()
        for limit in ("1/m/user", "1/m/ip"):
            cache.clear()
            with override_settings(ACCOUNT_RATE_LIMITS={"passive_header_read": limit}):
                self.assertEqual(self.client.get(self.path, secure=True).status_code, 200)
                self.assertEqual(self.client.get(self.base, secure=True).status_code, 429)
                self.assertEqual(self.client.get(self.path, secure=True).status_code, 429)
                self.assertEqual(self.post("selection/").status_code, 200)

    def test_post_serialization_full_original_source_caller_entitlement_and_cancel_loss_withholds_facts(self):
        job_id = self.collected()
        response = api._response
        def expire():
            start = timezone.now() - timedelta(days=31)
            OrganizationTrial.objects.filter(organization=self.organization).update(started_at=start, ends_at=start + timedelta(days=30))
        changes = (
            lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member"),
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
                self.assertEqual(result.status_code, 403, result.content)
                self.assertNotIn(b"cookies", result.content)
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
        self.assertTrue(finished)
        self.assertEqual(result.status_code, 403)
        self.assertNotIn(b"cookies", result.content)
