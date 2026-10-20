import json
from datetime import timedelta
from hashlib import sha256
from unittest.mock import patch

from django.core.cache import cache
from django.db import connection, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import OrganizationMembership, OrganizationTrial, Project, ProjectMembership, ProjectOriginVerification
from . import passive_header_api as api
from . import passive_header_collection as collector
from . import test_passive_header_api as fixtures
from .models import Artifact, Finding, JobCancellation, JobRun, JobStep, Opportunity, Recommendation, SourceCitation, UsageReservation


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "header-findings-api"}})
class HeaderFindingApiTests(TransactionTestCase):
    setUp = fixtures.PassiveHeaderApiTests.setUp
    verified = fixtures.PassiveHeaderApiTests.verified
    transport = fixtures.PassiveHeaderApiTests.transport
    post = fixtures.PassiveHeaderApiTests.post
    command = fixtures.PassiveHeaderApiTests.command

    def collected(self, wire=None):
        job_id = self.post(data=self.command()).json()["job"]["id"]
        self.assertTrue(collector.execute_passive_header_collection(job_id, fetcher=self.transport(wire=wire)))
        self.suffix = f"{job_id}/findings/"
        self.path = self.base + self.suffix
        return job_id

    def save(self, digest):
        return self.post(self.suffix, {"candidate_digest": digest})

    def test_genuine_get_no_writes_and_exact_digest_post_idempotent_original_set(self):
        job_id = self.collected()
        with patch("socket.create_connection", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            result = self.client.get(self.path, secure=True)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        initial = result.json()
        self.assertEqual(initial["finding_set"]["state"], "no_retained_materialized_findings")
        self.assertTrue(initial["candidates"]["candidates"])
        expected = sha256(collector._encode(initial["candidates"])).hexdigest()
        self.assertEqual(initial["candidate_digest"], expected)
        counts = (JobRun.objects.count(), UsageReservation.objects.count())
        with patch("socket.create_connection", side_effect=AssertionError("No network")):
            saved = self.save(expected); self.assertEqual(saved.status_code, 200, saved.content)
            self.assertEqual(self.save(expected).json(), saved.json())
            self.assertEqual(self.client.get(self.path, secure=True).json(), saved.json())
        self.assertEqual(saved.json()["finding_set"]["state"], "current_materialized_facts")
        self.assertEqual({row["source_passive_header_id"] for row in saved.json()["finding_set"]["findings"]}, {job_id})
        self.assertEqual((JobRun.objects.count(), UsageReservation.objects.count()), counts)
        self.assertEqual((Opportunity.objects.count(), Recommendation.objects.count()), (0, 0))
        self.assertEqual(self.connection.request.call_count, 1)
        self.assertEqual(result["Cache-Control"], "private, no-store")
        self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")
        for secret in (b"secret", b"nonce-private", self.challenge.encode(), self.owner.email.encode()):
            self.assertNotIn(secret, saved.content)
        # A later current admin sees existing facts, never personal materialization attribution.
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        self.client.force_login(self.member)
        self.assertEqual(self.save(expected).json(), saved.json())
        self.assertEqual(set(Finding.objects.values_list("actor_id", flat=True)), {self.owner.pk})

    def test_methods_csrf_strict_json_digest_query_and_scope(self):
        self.collected()
        expected = self.client.get(self.path, secure=True).json()["candidate_digest"]
        self.assertEqual(Client().get(self.path, secure=True).status_code, 401)
        self.assertEqual(self.client.post(self.path, json.dumps({"candidate_digest": expected}), content_type="application/json", secure=True).status_code, 403)
        for method in ("HEAD", "PUT", "PATCH", "DELETE", "OPTIONS"):
            response = self.client.generic(method, self.path, b"{}", content_type="application/json", secure=True,
                HTTP_X_CSRFTOKEN=self.csrf, HTTP_REFERER="https://testserver/")
            self.assertEqual(response.status_code, 405, response.content)
            self.assertEqual(response["Allow"], "GET, POST")
        self.assertEqual(self.client.get(self.path + "?family=tls", secure=True).status_code, 400)
        self.assertEqual(self.post(self.suffix + "?extra=x", {"candidate_digest": expected}).status_code, 400)
        self.assertEqual(self.client.generic("GET", self.path, b"{}", content_type="application/json", secure=True).status_code, 400)
        for body in ('{', '[]', 'null', '{"candidate_digest":NaN}', '{"candidate_digest":"a","candidate_digest":"b"}',
            json.dumps({"candidate_digest": expected, "actor_id": self.owner.pk}), ' ' * 2049):
            response = self.client.post(self.path, body, content_type="application/json", secure=True,
                HTTP_X_CSRFTOKEN=self.csrf, HTTP_REFERER="https://testserver/")
            self.assertEqual(response.status_code, 409, response.content)
        for value, status in ((True, 409), (1, 409), ("A" * 64, 409), ("a" * 64, 403)):
            self.assertEqual(self.save(value).status_code, status)
        self.assertFalse(Finding.objects.exists())
        # Digest of a different inspected report is not authority for the original.
        report = self.client.get(self.path, secure=True).json()["candidates"]
        report["job_id"] += 1
        self.assertEqual(self.save(api._digest(report)).status_code, 403)
        foreign = self.path.replace(f"projects/{self.project.pk}/", "projects/9007199254740991/")
        self.assertEqual(self.client.get(foreign, secure=True).status_code, 404)

    def test_current_roles_restricted_tenants_original_family_and_unavailable_evidence(self):
        Project.objects.filter(pk=self.project.pk).update(access_restricted=True)
        job_id = self.collected()
        for actor, status in ((self.member, 403), (self.outsider, 404)):
            client = Client(); client.force_login(actor)
            self.assertEqual(client.get(self.path, secure=True).status_code, 404)
            self.assertEqual(client.post(self.path, json.dumps({"candidate_digest": "a" * 64}), content_type="application/json", secure=True).status_code, 404)
        other = Project.objects.create(organization=self.organization, name="Other", canonical_origin="https://other.example.invalid")
        self.assertEqual(self.client.get(self.path.replace(f"projects/{self.project.pk}/", f"projects/{other.pk}/"), secure=True).status_code, 403)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        client = Client(); client.force_login(self.member)
        self.assertEqual(client.get(self.path, secure=True).status_code, 404)
        ProjectMembership.objects.create(project=self.project, organization_membership=OrganizationMembership.objects.get(
            organization=self.organization, user=self.member))
        self.assertEqual(client.get(self.path, secure=True).status_code, 200)
        for changes, status in (({"status": "failed"}, 403), ({"handler": "collect_passive_tls"}, 403),
            ({"handler": "collect_passive_resources"}, 403), ({"handler": "collect_passive_redirects"}, 403), ({"output": {}}, 409)):
            with transaction.atomic():
                JobRun.objects.filter(pk=job_id).update(**changes)
                self.assertEqual(self.client.get(self.path, secure=True).status_code, status)
                transaction.set_rollback(True)
        self.assertFalse(Finding.objects.exists())

    def test_independent_maintained_read_write_user_and_shared_ip_budgets(self):
        self.collected()
        expected = self.client.get(self.path, secure=True).json()["candidate_digest"]
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        other = Client(); other.force_login(self.member)
        for limit in ("1/m/user", "1/m/ip"):
            cache.clear()
            with override_settings(ACCOUNT_RATE_LIMITS={action: limit for action in
                ("passive_header_findings_read", "passive_header_findings_write")}):
                self.assertEqual(self.client.get(self.path, secure=True).status_code, 200)
                self.assertEqual(self.client.get(self.path, secure=True).status_code, 429)
                self.assertEqual(self.save(expected).status_code, 200)
                self.assertEqual(self.save(expected).status_code, 429)
                self.assertEqual(self.client.get(self.base, secure=True).status_code, 200)
                self.assertEqual(self.post("selection/").status_code, 200)
                if limit.endswith("ip"):
                    self.assertEqual(other.get(self.path, secure=True).status_code, 429)
                    self.assertEqual(other.post(self.path, json.dumps({"candidate_digest": expected}), content_type="application/json", secure=True).status_code, 429)

    def test_post_serialization_full_source_and_finding_row_loss_denies_and_rolls_back_post(self):
        job_id = self.collected()
        expected = self.client.get(self.path, secure=True).json()["candidate_digest"]
        original_response = api._response
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        changes = (
            lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member"),
            lambda: ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(challenge_digest="a" * 64),
            lambda: JobRun.objects.filter(pk=job_id).update(idempotency_key="changed-original"),
            lambda: JobStep.objects.filter(job_id=job_id).update(created_at=timezone.now()),
            lambda: Artifact.objects.filter(job_id=job_id).update(created_at=timezone.now()),
            lambda: SourceCitation.objects.filter(job_id=job_id).update(source_title="Changed"),
            lambda: UsageReservation.objects.filter(job_id=job_id).update(period_start=timezone.now().date() - timedelta(days=1)),
            lambda: JobCancellation.objects.create(job_id=job_id, requested_by=self.owner),
            lambda: Finding.objects.filter(source_passive_header_id=job_id).update(actor=self.member),
            lambda: Finding.objects.filter(source_passive_header_id=job_id).update(detected_at=timezone.now()),
            lambda: Finding.objects.filter(source_passive_header_id=job_id).update(confidence="high"),
            lambda: Finding.objects.filter(source_passive_header_id=job_id).delete(),
            lambda: OrganizationTrial.objects.filter(organization=self.organization).update(
                started_at=timezone.now() - timedelta(days=31), ends_at=timezone.now() - timedelta(days=1)))
        for method in ("POST", "GET"):
            if method == "GET": self.assertEqual(self.save(expected).status_code, 200)
            for change in changes:
                with self.subTest(method=method, change=change), transaction.atomic():
                    def serialized(data, *args, **kwargs):
                        result = original_response(data, *args, **kwargs)
                        if "finding_set" in data: change()
                        return result
                    with patch.object(api, "_response", side_effect=serialized):
                        result = self.save(expected) if method == "POST" else self.client.get(self.path, secure=True)
                    self.assertIn(result.status_code, (403, 409), result.content)
                    self.assertNotIn(b"collection_sha256", result.content)
                    if method == "POST": self.assertFalse(Finding.objects.exists())
                    transaction.set_rollback(True)
        # Independently check a retained materializer, distinct from the source owner/caller.
        Finding.objects.all().update(actor=self.member)
        def demoted(data, *args, **kwargs):
            result = original_response(data, *args, **kwargs)
            if "finding_set" in data: OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="member")
            return result
        with patch.object(api, "_response", side_effect=demoted):
            self.assertEqual(self.client.get(self.path, secure=True).status_code, 403)

    def test_natural_exact_expiry_after_serialization_rolls_back_post(self):
        self.collected()
        expected = self.client.get(self.path, secure=True).json()["candidate_digest"]
        ends = timezone.now() + timedelta(seconds=5)
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=ends - timedelta(days=30), ends_at=ends)
        response = api._response
        for method in ("POST", "GET"):
            finished = False
            def serialized(data, *args, **kwargs):
                nonlocal finished
                result = response(data, *args, **kwargs)
                if "finding_set" in data: finished = True
                return result
            with patch("jobs.usage.timezone.now", side_effect=lambda: ends if finished else ends - timedelta(seconds=1)), patch.object(
                api, "_response", side_effect=serialized):
                result = self.save(expected) if method == "POST" else self.client.get(self.path, secure=True)
            self.assertTrue(finished)
            self.assertEqual(result.status_code, 403, result.content)
            self.assertFalse(Finding.objects.exists())

    def test_empty_original_candidates_do_not_confirm_noop_or_clean_security_result(self):
        from .passive_header_candidates import SECURITY_HEADERS
        wire = b"HTTP/1.1 200 OK\r\n" + b"".join(name.encode() + b": present\r\n" for name in SECURITY_HEADERS) + b"\r\n"
        self.collected(wire=wire)
        before = self.client.get(self.path, secure=True).json()
        self.assertEqual(before["candidates"]["candidates"], [])
        self.assertEqual(before["finding_set"]["state"], "no_retained_materialized_findings")
        self.assertEqual(self.save(before["candidate_digest"]).json(), before)
        self.assertFalse(Finding.objects.exists())
