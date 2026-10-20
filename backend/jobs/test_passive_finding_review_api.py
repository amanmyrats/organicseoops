from datetime import timedelta
import json
from unittest.mock import patch

from django.core.cache import cache
from django.db import connection, reset_queries, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import OrganizationMembership, OrganizationTrial, Project, ProjectMembership, ProjectOriginVerification
from . import passive_finding_review_api as api
from . import test_passive_finding_reviews as fixtures
from .models import Finding, JobCancellation, JobRun, JobStep, Opportunity, UsageReservation


class PriorityApiChecks:
    def prepared(self):
        cache.clear()
        job = self.collected(); finding = self.record(job)[0]
        self.client = Client(enforce_csrf_checks=True); self.client.force_login(self.owner)
        self.client.get("/_allauth/browser/v1/auth/session", secure=True)
        self.csrf = self.client.cookies["csrftoken"].value
        self.path = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/{self.prefix}/{job.pk}/findings/{finding.pk}/priority/"
        self.body = dict(source_sha256=self.review_source(job, finding)["source_sha256"], expected_revision=0,
            priority="unprioritized", estimated_effort="unknown", business_relevance="unknown", reason="Inspect this dated literal fact")
        return job, finding

    def post_priority(self, **changes):
        return self.client.post(self.path, json.dumps({**self.body, **changes}), content_type="application/json", secure=True,
            HTTP_X_CSRFTOKEN=self.csrf, HTTP_REFERER="https://testserver/")

    def test_genuine_read_only_no_decision_is_not_human_unprioritized_exact_revision_replay_correction(self):
        job, finding = self.prepared(); counts = (JobRun.objects.count(), UsageReservation.objects.count(), Finding.objects.count())
        reset_queries()
        query_count = 0; writes = []
        def capture(execute, sql, params, many, context):
            nonlocal query_count
            query_count += 1
            if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")): writes.append(1)
            return execute(sql, params, many, context)
        # Inspect every statement even when Django's bounded debug query log fills.
        with patch("socket.create_connection", side_effect=AssertionError("No real egress")), connection.execute_wrapper(capture):
            initial = self.client.get(self.path, secure=True)
        self.assertEqual(initial.status_code, 200, initial.content)
        self.assertGreater(query_count, 0); self.assertEqual(writes, [])
        self.assertIsNone(initial.json()["prioritization"]["decision"])
        saved = self.post_priority(); self.assertEqual(saved.status_code, 200, saved.content)
        self.assertEqual(saved.json()["prioritization"]["decision"]["priority"], "unprioritized")
        self.assertEqual(self.post_priority().json(), saved.json())
        self.assertEqual(self.client.get(self.path, secure=True).json(), saved.json())
        self.assertEqual(self.post_priority(priority="high").status_code, 409)
        corrected = self.post_priority(expected_revision=1, priority="high")
        self.assertEqual(corrected.status_code, 200, corrected.content)
        self.assertEqual(corrected.json()["prioritization"]["decision"]["revision"], 2)
        self.assertEqual((JobRun.objects.count(), UsageReservation.objects.count(), Finding.objects.count()), counts)
        self.assertEqual(Opportunity.objects.count(), 2)
        self.assertEqual(saved["Cache-Control"], "private, no-store"); self.assertIn("noindex", saved["X-Robots-Tag"])
        for private in (self.challenge.encode(), self.owner.email.encode(), b"nonce-private", b"secret=value"):
            self.assertNotIn(private, saved.content)
        self.assertEqual(saved.json()["prioritization"]["source"]["finding"]["evidence"], finding.evidence)

    def test_methods_csrf_exact_json_digest_revision_roles_tenants_and_fixed_family(self):
        job, finding = self.prepared()
        self.assertEqual(Client().get(self.path, secure=True).status_code, 401)
        self.assertEqual(self.client.post(self.path, json.dumps(self.body), content_type="application/json", secure=True).status_code, 403)
        for method in ("HEAD", "PUT", "PATCH", "DELETE", "OPTIONS"):
            result = self.client.generic(method, self.path, b"{}", content_type="application/json", secure=True,
                HTTP_X_CSRFTOKEN=self.csrf, HTTP_REFERER="https://testserver/")
            self.assertEqual((result.status_code, result["Allow"]), (405, "GET, POST"))
        self.assertEqual(self.client.get(self.path + "?family=tls", secure=True).status_code, 400)
        self.assertEqual(self.client.generic("GET", self.path, b"{}", content_type="application/json", secure=True).status_code, 400)
        for body in ("{", "[]", "null", '{"source_sha256":NaN}', '{"source_sha256":"a","source_sha256":"b"}',
            json.dumps({**self.body, "actor_id": self.owner.pk}), " " * 2049):
            response = self.client.post(self.path, body, content_type="application/json", secure=True,
                HTTP_X_CSRFTOKEN=self.csrf, HTTP_REFERER="https://testserver/")
            self.assertEqual(response.status_code, 409, response.content)
        for changes in ({"source_sha256": True}, {"expected_revision": True}, {"priority": []}, {"reason": " "}):
            self.assertEqual(self.post_priority(**changes).status_code, 409)
        self.assertEqual(self.post_priority(source_sha256="a" * 64).status_code, 403)
        for actor, expected in ((self.member, 403), (self.outsider, 404)):
            client = Client(); client.force_login(actor)
            self.assertEqual(client.get(self.path, secure=True).status_code, expected)
        for prefix in ("passive-headers", "passive-resources", "passive-tls", "passive-redirects", "passive-redirect-chain"):
            if prefix != self.prefix:
                self.assertEqual(self.client.get(self.path.replace(self.prefix, prefix), secure=True).status_code, 403)
        other = Project.objects.create(organization=self.organization, name="Other", canonical_origin="https://other.example.invalid")
        self.assertEqual(self.client.get(self.path.replace(f"projects/{self.project.pk}/", f"projects/{other.pk}/"), secure=True).status_code, 403)
        self.assertEqual(self.client.get(self.path.replace(f"findings/{finding.pk}/", "findings/9007199254740991/"), secure=True).status_code, 403)
        self.assertFalse(Opportunity.objects.exists())

    def test_restricted_independent_admin_needs_current_grant_on_genuine_restricted_source(self):
        Project.objects.filter(pk=self.project.pk).update(access_restricted=True); self.project.refresh_from_db()
        job, finding = self.prepared()
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        client = Client(); client.force_login(self.member)
        self.assertEqual(client.get(self.path, secure=True).status_code, 404)
        membership = OrganizationMembership.objects.get(organization=self.organization, user=self.member)
        ProjectMembership.objects.create(project=self.project, organization_membership=membership)
        self.assertEqual(client.get(self.path, secure=True).status_code, 200)
        ProjectMembership.objects.filter(project=self.project, organization_membership=membership).delete()
        self.assertEqual(client.get(self.path, secure=True).status_code, 404)
        self.assertFalse(Opportunity.objects.exists())

    def test_maintained_independent_read_write_user_shared_ip_and_other_family_budgets(self):
        self.prepared(); OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        other = Client(); other.force_login(self.member)
        actions = (f"passive_{self.family}_priority_read", f"passive_{self.family}_priority_write")
        # Keep the low-cap window stable across genuine source validation, not wall-clock fixture speed.
        for limit in ("1/h/user", "1/h/ip"):
            cache.clear()
            with override_settings(ACCOUNT_RATE_LIMITS={name: limit for name in actions}):
                self.assertEqual(self.client.get(self.path, secure=True).status_code, 200)
                self.assertEqual(self.client.get(self.path, secure=True).status_code, 429)
                self.assertEqual(self.post_priority().status_code, 200)
                self.assertEqual(self.post_priority().status_code, 429)
                self.assertEqual(self.client.get(self.path.split("findings/")[0] + "findings/", secure=True).status_code, 200)
                wrong = "passive-tls" if self.prefix != "passive-tls" else "passive-headers"
                self.assertEqual(self.client.get(self.path.replace(self.prefix, wrong), secure=True).status_code, 403)
                if limit.endswith("ip"):
                    self.assertEqual(other.get(self.path, secure=True).status_code, 429)
                    self.assertEqual(other.post(self.path, json.dumps(self.body), content_type="application/json", secure=True).status_code, 429)

    def test_full_source_latest_rows_and_independent_reviewer_after_serialization_deny_and_rollback(self):
        job, finding = self.prepared(); original_response = api._response
        changes = (
            lambda: Opportunity.objects.filter(finding=finding).update(review_reason="Changed during serialization"),
            lambda: Opportunity.objects.filter(finding=finding).update(created_at=timezone.now()),
            lambda: Finding.objects.filter(pk=finding.pk).update(detected_at=timezone.now()),
            lambda: JobStep.objects.filter(job=job).update(created_at=timezone.now()),
            lambda: JobCancellation.objects.create(job=job, requested_by=self.owner),
            lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member"))
        for method in ("POST", "GET"):
            if method == "GET": self.assertEqual(self.post_priority().status_code, 200)
            for mutate in changes:
                def serialized(data, *args, **kwargs):
                    result = original_response(data, *args, **kwargs)
                    if "prioritization" in data: mutate()
                    return result
                with self.subTest(method=method, mutation=mutate), transaction.atomic():
                    with patch.object(api, "_response", side_effect=serialized):
                        response = self.post_priority() if method == "POST" else self.client.get(self.path, secure=True)
                    self.assertIn(response.status_code, (403, 409), response.content)
                    self.assertNotIn(b"collection_sha256", response.content)
                    if method == "POST": self.assertFalse(Opportunity.objects.exists())
                    transaction.set_rollback(True)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        Opportunity.objects.filter(finding=finding).update(actor=self.member)
        def reviewer_lost(data, *args, **kwargs):
            result = original_response(data, *args, **kwargs)
            if "prioritization" in data:
                OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="viewer")
            return result
        with patch.object(api, "_response", side_effect=reviewer_lost):
            self.assertEqual(self.client.get(self.path, secure=True).status_code, 403)

    def test_natural_exact_expiry_after_serialization_is_not_prior_authority(self):
        self.prepared(); ends = timezone.now() + timedelta(seconds=5)
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=ends - timedelta(days=30), ends_at=ends)
        original_response = api._response
        for method in ("POST", "GET"):
            serialized = False
            def response(data, *args, **kwargs):
                nonlocal serialized
                result = original_response(data, *args, **kwargs)
                if "prioritization" in data: serialized = True
                return result
            with patch.object(api, "_response", side_effect=response), patch("jobs.usage.timezone.now",
                side_effect=lambda: ends if serialized else ends - timedelta(microseconds=1)):
                result = self.post_priority() if method == "POST" else self.client.get(self.path, secure=True)
            self.assertTrue(serialized); self.assertIn(result.status_code, (403, 409))
            self.assertFalse(Opportunity.objects.exists())


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json"}),
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "passive-priority-api"}})
class HeaderPriorityApiTests(PriorityApiChecks, TransactionTestCase):
    setUp = fixtures.HeaderPriorityTests.setUp
    verified = fixtures.HeaderPriorityTests.verified
    queue = fixtures.HeaderPriorityTests.queue
    transport = fixtures.HeaderPriorityTests.transport
    collected = fixtures.HeaderPriorityTests.collected
    record = fixtures.HeaderPriorityTests.record
    review_source = fixtures.HeaderPriorityTests.review_source
    source = staticmethod(fixtures.HeaderPriorityTests.source)
    family = "header"; prefix = "passive-headers"


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json"}),
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "passive-priority-api"}})
class ResourcePriorityApiTests(PriorityApiChecks, TransactionTestCase):
    setUp = fixtures.ResourcePriorityTests.setUp
    verified = fixtures.ResourcePriorityTests.verified
    queue = fixtures.ResourcePriorityTests.queue
    transport = fixtures.ResourcePriorityTests.transport
    collected = fixtures.ResourcePriorityTests.collected
    record = fixtures.ResourcePriorityTests.record
    review_source = fixtures.ResourcePriorityTests.review_source
    source = staticmethod(fixtures.ResourcePriorityTests.source)
    family = "resource"; prefix = "passive-resources"


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json"}),
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "passive-priority-api"}})
class TLSPriorityApiTests(PriorityApiChecks, TransactionTestCase):
    setUp = fixtures.TLSPriorityTests.setUp
    verified = fixtures.TLSPriorityTests.verified
    queue = fixtures.TLSPriorityTests.queue
    transport = fixtures.TLSPriorityTests.transport
    collected = fixtures.TLSPriorityTests.collected
    record = fixtures.TLSPriorityTests.record
    review_source = fixtures.TLSPriorityTests.review_source
    source = staticmethod(fixtures.TLSPriorityTests.source)
    family = "tls"; prefix = "passive-tls"


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json"}),
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "passive-priority-api"}})
class RedirectPriorityApiTests(PriorityApiChecks, TransactionTestCase):
    setUp = fixtures.RedirectPriorityTests.setUp
    verified = fixtures.RedirectPriorityTests.verified
    queue = fixtures.RedirectPriorityTests.queue
    transport = fixtures.RedirectPriorityTests.transport
    collected = fixtures.RedirectPriorityTests.collected
    record = fixtures.RedirectPriorityTests.record
    review_source = fixtures.RedirectPriorityTests.review_source
    source = staticmethod(fixtures.RedirectPriorityTests.source)
    WIRE = fixtures.RedirectPriorityTests.WIRE
    family = "redirect"; prefix = "passive-redirects"


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json"}),
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "passive-priority-api"}})
class RedirectChainPriorityApiTests(PriorityApiChecks, TransactionTestCase):
    setUp = fixtures.RedirectChainPriorityTests.setUp
    verified = fixtures.RedirectChainPriorityTests.verified
    queue = fixtures.RedirectChainPriorityTests.queue
    collected = fixtures.RedirectChainPriorityTests.collected
    record = fixtures.RedirectChainPriorityTests.record
    review_source = fixtures.RedirectChainPriorityTests.review_source
    source = staticmethod(fixtures.RedirectChainPriorityTests.source)
    family = "redirect_chain"; prefix = "passive-redirect-chain"

    def test_every_original_origin_including_unvisited_and_private_bytes_after_serialization_roll_back(self):
        from . import passive_header_collection as lifecycle
        unvisited = self.verified("https://www.security.example.com")
        self.data["target_urls"].append(unvisited.origin + "/unvisited")
        with patch.object(self, "collected", side_effect=lambda: fixtures.RedirectChainPriorityTests.collected(self,
            fields=f"Location: {self.data['url']}\r\n".encode())):
            job, finding = self.prepared()
        self.assertEqual((finding.evidence["availability"]["selected_urls"], finding.evidence["availability"]["observed_hops"]), (3, 1))
        original_response = api._response; read_bytes = lifecycle.read_project_artifact
        for method in ("POST", "GET"):
            if method == "GET": self.assertEqual(self.post_priority().status_code, 200)
            for verification in (self.https_verification, self.http_verification, unvisited, None):
                with self.subTest(method=method, origin=None if verification is None else verification.origin), transaction.atomic():
                    before = list(Opportunity.objects.order_by("pk").values()); serialized = False
                    def response(data, *args, **kwargs):
                        nonlocal serialized
                        result = original_response(data, *args, **kwargs)
                        if "prioritization" in data:
                            serialized = True
                            if verification is not None:
                                ProjectOriginVerification.objects.filter(pk=verification.pk).update(updated_at=timezone.now())
                        return result
                    def late_bytes(**kwargs): return b"{}" if serialized and verification is None else read_bytes(**kwargs)
                    with patch.object(api, "_response", side_effect=response), patch.object(lifecycle, "read_project_artifact", side_effect=late_bytes):
                        result = self.post_priority() if method == "POST" else self.client.get(self.path, secure=True)
                    self.assertTrue(serialized); self.assertIn(result.status_code, (403, 409), result.content)
                    self.assertNotIn(b"collection_sha256", result.content)
                    if method == "POST": self.assertEqual(list(Opportunity.objects.order_by("pk").values()), before)
                    transaction.set_rollback(True)
