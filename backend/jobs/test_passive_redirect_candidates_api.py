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
from . import passive_redirect_collection as collector
from . import test_passive_redirect_api as fixtures
from .models import Artifact, Finding, JobCancellation, JobRun, JobStep, SourceCitation, UsageReservation


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "redirect-candidates-api"}})
class RedirectCandidateApiTests(TransactionTestCase):
    setUp = fixtures.PassiveRedirectApiTests.setUp
    verified = fixtures.PassiveRedirectApiTests.verified
    transport = fixtures.PassiveRedirectApiTests.transport
    post = fixtures.PassiveRedirectApiTests.post
    command = fixtures.PassiveRedirectApiTests.command
    WIRE = fixtures.PassiveRedirectApiTests.WIRE

    def collected(self, key="redirect-candidate-api", *, wire=None):
        queued = self.post(data=self.command(key)); self.assertEqual(queued.status_code, 202, queued.content)
        job_id = queued.json()["job"]["id"]; fetcher = self.transport(wire=self.WIRE if wire is None else wire)
        with patch("socket.create_connection", side_effect=AssertionError("No real network")):
            self.assertTrue(collector.execute_passive_redirect_collection(job_id, fetcher=fetcher))
        self.path = self.base + f"{job_id}/candidates/"
        return job_id

    def test_genuine_current_original_get_is_read_only_private_no_follow_or_materialization(self):
        job_id = self.collected()
        with patch("socket.create_connection", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            result = self.client.get(self.path, secure=True)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        report = result.json()["candidates"]
        self.assertEqual((report["job_id"], report["source_current"]), (job_id, True))
        self.assertEqual(report["collection"]["observed_at"], JobRun.objects.get(pk=job_id).output["observed_at"])
        self.assertEqual(report["candidates"], [{"detector": "http_scheme_location_reference_candidate", "evidence": {
            "response_status": 302, "redirect_status": True, "location_state": "single_classified", "target_scheme": "http", "same_origin": False}}])
        self.assertFalse(Finding.objects.exists()); self.connection.request.assert_called_once()
        for raw in (b"private.invalid", b"secret=value", b"raw_location", self.challenge.encode(), self.owner.email.encode()): self.assertNotIn(raw, result.content)
        self.assertEqual(result["Cache-Control"], "private, no-store"); self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")

    def test_original_target_unknowns_and_classified_https_eligible_empty_remain_distinct(self):
        for key, fields, state, scheme in (("absent", b"", "absent", None), ("empty", b"Location: \t\r\n", "present_empty", None),
            ("multiple", b"Location: /one\r\nLocation: /two\r\n", "multiple_fields", None),
            ("unknown", b"Location: javascript:private\r\n", "single_unclassified", None),
            ("https", b"Location: /relative\r\n", "single_classified", "https")):
            self.collected("location-" + key, wire=b"HTTP/1.1 200 OK\r\n" + fields + b"\r\n")
            result = self.client.get(self.path, secure=True); self.assertEqual(result.status_code, 200, result.content)
            report = result.json()["candidates"]
            self.assertEqual(report["candidates"], []); self.assertEqual(report["availability"], {"target_metadata": "observed" if scheme else "unavailable"})
            location = report["collection"]["evidence"]["response_location"]
            self.assertEqual((location["location_state"], location["target_scheme"]), (state, scheme))
            if scheme is None: self.assertIsNone(location["same_origin"])

    def test_fixed_method_input_roles_tenant_family_and_failed_originals_deny(self):
        job_id = self.collected()
        self.assertEqual(Client().get(self.path, secure=True).status_code, 401)
        for query in ("?family=tls", "?job_id=1", "?extra=x"):
            self.assertEqual(self.client.get(self.path + query, secure=True).status_code, 400)
        self.assertEqual(self.client.generic("GET", self.path, b"{}", content_type="application/json", secure=True).status_code, 400)
        self.assertEqual(self.post(f"{job_id}/candidates/", {}).status_code, 405); self.assertEqual(self.client.head(self.path, secure=True).status_code, 405)
        for actor, status in ((self.member, 403), (self.outsider, 404)):
            client = Client(); client.force_login(actor); self.assertEqual(client.get(self.path, secure=True).status_code, status)
        for changes, status in (({"status": "failed"}, 403), ({"handler": "collect_passive_headers"}, 403),
            ({"handler": "collect_passive_resources"}, 403), ({"handler": "collect_passive_tls"}, 403), ({"output": {}}, 409)):
            with transaction.atomic():
                JobRun.objects.filter(pk=job_id).update(**changes)
                self.assertEqual(self.client.get(self.path, secure=True).status_code, status); transaction.set_rollback(True)
        for family in ("headers", "resources", "tls"):
            self.assertEqual(self.client.get(self.path.replace("passive-redirects", f"passive-{family}"), secure=True).status_code, 403)
        self.assertEqual(self.client.get(self.path.replace(f"projects/{self.project.pk}/", "projects/9007199254740991/"), secure=True).status_code, 404)

    def test_original_location_read_user_ip_budget_is_shared_with_history_not_other_families_or_selection(self):
        self.collected(); OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        other = Client(); other.force_login(self.member)
        for limit in ("1/m/user", "1/m/ip"):
            cache.clear()
            with override_settings(ACCOUNT_RATE_LIMITS={"passive_redirect_read": limit}):
                self.assertEqual(self.client.get(self.path, secure=True).status_code, 200)
                self.assertEqual(self.client.get(self.base, secure=True).status_code, 429); self.assertEqual(self.client.get(self.path, secure=True).status_code, 429)
                if limit.endswith("ip"): self.assertEqual(other.get(self.path, secure=True).status_code, 429)
                for family in ("headers", "resources", "tls"):
                    self.assertEqual(self.client.get(self.base.replace("passive-redirects", f"passive-{family}"), secure=True).status_code, 200)
                self.assertEqual(self.post("selection/").status_code, 200)

    def test_post_serialization_complete_metadata_source_actor_independent_caller_commercial_cancel_expiry_withhold(self):
        job_id = self.collected(); response = api._response
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin"); self.client.force_login(self.member)
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
                self.assertEqual(result.status_code, 403, result.content); self.assertNotIn(b"http_scheme_location_reference_candidate", result.content)
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
        self.assertTrue(finished); self.assertEqual(result.status_code, 403); self.assertNotIn(b"http_scheme_location_reference_candidate", result.content)
