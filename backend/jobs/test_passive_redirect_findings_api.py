import json
from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.db import connection, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import OrganizationMembership, Project, ProjectMembership
from . import passive_header_api as api
from . import passive_redirect_collection as collector
from . import test_passive_redirect_api as fixtures
from . import test_passive_header_findings_api as header_checks
from .models import Finding, JobRun, Opportunity, Recommendation, UsageReservation


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "redirect-findings-api"}})
class RedirectFindingApiTests(TransactionTestCase):
    setUp = fixtures.PassiveRedirectApiTests.setUp
    verified = fixtures.PassiveRedirectApiTests.verified
    transport = fixtures.PassiveRedirectApiTests.transport
    post = fixtures.PassiveRedirectApiTests.post
    command = fixtures.PassiveRedirectApiTests.command
    WIRE = fixtures.PassiveRedirectApiTests.WIRE

    def collected(self, *, key="redirect-finding-api", wire=None):
        queued = self.post(data=self.command(key)); self.assertEqual(queued.status_code, 202, queued.content)
        job_id = queued.json()["job"]["id"]; fetcher = self.transport(wire=self.WIRE if wire is None else wire)
        with patch("socket.create_connection", side_effect=AssertionError("No real egress")):
            self.assertTrue(collector.execute_passive_redirect_collection(job_id, fetcher=fetcher))
        self.suffix = f"{job_id}/findings/"; self.path = self.base + self.suffix
        return job_id

    def save(self, digest):
        return self.post(self.suffix, {"candidate_digest": digest})

    test_methods_csrf_strict_json_digest_query_and_scope = header_checks.HeaderFindingApiTests.test_methods_csrf_strict_json_digest_query_and_scope
    test_natural_exact_expiry_after_serialization_rolls_back_post = header_checks.HeaderFindingApiTests.test_natural_exact_expiry_after_serialization_rolls_back_post

    def test_original_get_is_private_read_only_sha_post_saves_one_original_fact_without_new_work(self):
        job_id = self.collected()
        with patch("socket.create_connection", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            result = self.client.get(self.path, secure=True)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        initial = result.json(); expected = api._digest(initial["candidates"])
        self.assertEqual(initial["candidate_digest"], expected)
        self.assertEqual(initial["finding_set"]["state"], "no_retained_materialized_findings")
        self.assertEqual(len(initial["candidates"]["candidates"]), 1)
        counts = (JobRun.objects.count(), UsageReservation.objects.count())
        saved = self.save(expected); self.assertEqual(saved.status_code, 200, saved.content)
        self.assertEqual(self.save(expected).json(), saved.json()); self.assertEqual(self.client.get(self.path, secure=True).json(), saved.json())
        facts = saved.json()["finding_set"]["findings"]
        self.assertEqual(len(facts), 1); self.assertEqual(facts[0]["source_passive_redirect_id"], job_id)
        self.assertEqual(facts[0]["subject"], self.data["url"])
        self.assertEqual((JobRun.objects.count(), UsageReservation.objects.count()), counts)
        self.assertEqual((Opportunity.objects.count(), Recommendation.objects.count()), (0, 0))
        self.assertEqual(result["Cache-Control"], "private, no-store"); self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")
        for raw in (b"raw_location", b"private.invalid", b"secret=value", self.challenge.encode(), self.owner.email.encode()): self.assertNotIn(raw, saved.content)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        self.client.force_login(self.member); self.assertEqual(self.save(expected).json(), saved.json())
        self.assertEqual(set(Finding.objects.values_list("actor_id", flat=True)), {self.owner.pk})
        self.connection.request.assert_called_once()

    def test_fixed_family_roles_failed_sources_and_original_status_classification_empty_nullable_facts(self):
        job_id = self.collected()
        for actor, status in ((self.member, 403), (self.outsider, 404)):
            client = Client(); client.force_login(actor); self.assertEqual(client.get(self.path, secure=True).status_code, status)
        for family in ("passive-headers", "passive-resources", "passive-tls"):
            self.assertEqual(self.client.get(self.path.replace("passive-redirects", family), secure=True).status_code, 403)
        for changes, status in (({"handler": "collect_passive_headers"}, 403), ({"handler": "collect_passive_resources"}, 403),
            ({"handler": "collect_passive_tls"}, 403), ({"status": "failed"}, 403), ({"output": {}}, 409)):
            with transaction.atomic():
                JobRun.objects.filter(pk=job_id).update(**changes); self.assertEqual(self.client.get(self.path, secure=True).status_code, status)
                transaction.set_rollback(True)
        for key, fields, scheme in (("absent", b"", None), ("empty", b"Location: \t\r\n", None),
            ("multiple", b"Location: /one\r\nLocation: /two\r\n", None), ("unknown", b"Location: javascript:private\r\n", None),
            ("https", b"Location: /relative\r\n", "https")):
            self.collected(key="redirect-" + key, wire=b"HTTP/1.1 200 OK\r\n" + fields + b"\r\n")
            initial = self.client.get(self.path, secure=True).json()
            self.assertEqual(initial["candidates"]["candidates"], [])
            self.assertEqual(initial["candidates"]["availability"], {"target_metadata": "observed" if scheme else "unavailable"})
            self.assertEqual(initial["finding_set"]["state"], "no_retained_materialized_findings")
            self.assertEqual(self.save(initial["candidate_digest"]).json(), initial)
        self.assertFalse(Finding.objects.exists())
        self.collected(key="redirect-status200", wire=b"HTTP/1.1 200 OK\r\nLocation: http://foreign.invalid/\r\n\r\n")
        initial = self.client.get(self.path, secure=True).json(); saved = self.save(initial["candidate_digest"])
        self.assertEqual(saved.status_code, 200, saved.content)
        fact = saved.json()["finding_set"]["findings"][0]["evidence"]["fact"]
        self.assertEqual(fact["response_status"], 200); self.assertIs(fact["redirect_status"], False)

    def test_independent_finding_read_write_user_ip_budgets_leave_original_budgets_available(self):
        self.collected(); expected = self.client.get(self.path, secure=True).json()["candidate_digest"]
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        other = Client(); other.force_login(self.member)
        for limit in ("1/m/user", "1/m/ip"):
            cache.clear()
            with override_settings(ACCOUNT_RATE_LIMITS={action: limit for action in ("passive_redirect_findings_read", "passive_redirect_findings_write")}):
                self.assertEqual(self.client.get(self.path, secure=True).status_code, 200)
                self.assertEqual(self.client.get(self.path, secure=True).status_code, 429)
                self.assertEqual(self.save(expected).status_code, 200); self.assertEqual(self.save(expected).status_code, 429)
                for family in ("passive-redirects", "passive-tls", "passive-headers", "passive-resources"):
                    self.assertEqual(self.client.get(self.base.replace("passive-redirects", family), secure=True).status_code, 200)
                self.assertEqual(self.client.get(self.path.replace("findings/", "candidates/"), secure=True).status_code, 200)
                self.assertEqual(self.post("selection/").status_code, 200)
                if limit.endswith("ip"):
                    self.assertEqual(other.get(self.path, secure=True).status_code, 429)
                    self.assertEqual(other.post(self.path, json.dumps({"candidate_digest": expected}), content_type="application/json", secure=True).status_code, 429)

    def test_restricted_scope_requires_current_caller_and_independent_materializer_grant(self):
        Project.objects.filter(pk=self.project.pk).update(access_restricted=True)
        job_id = self.collected(); expected = self.client.get(self.path, secure=True).json()["candidate_digest"]
        membership = OrganizationMembership.objects.get(organization=self.organization, user=self.member)
        OrganizationMembership.objects.filter(pk=membership.pk).update(role="admin")
        client = Client(); client.force_login(self.member)
        self.assertEqual(client.get(self.path, secure=True).status_code, 404)
        ProjectMembership.objects.create(project=self.project, organization_membership=membership)
        self.assertEqual(client.get(self.path, secure=True).status_code, 200)
        self.assertEqual(self.save(expected).status_code, 200)
        Finding.objects.filter(source_passive_redirect_id=job_id).update(actor=self.member)
        ProjectMembership.objects.filter(project=self.project, organization_membership=membership).delete()
        self.assertEqual(self.client.get(self.path, secure=True).status_code, 403)

    def test_post_serialization_full_source_rows_materializer_late_caller_and_cancel_loss_rollback(self):
        from tenancy.models import OrganizationTrial, ProjectOriginVerification
        from .models import Artifact, JobCancellation, JobStep, SourceCitation
        job_id = self.collected(); expected = self.client.get(self.path, secure=True).json()["candidate_digest"]; response = api._response
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        self.client.force_login(self.member)
        changes = (
            lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member"),
            lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="viewer"),
            lambda: ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(challenge_digest="a" * 64),
            lambda: JobRun.objects.filter(pk=job_id).update(idempotency_key="changed-original"),
            lambda: JobStep.objects.filter(job_id=job_id).update(created_at=timezone.now()),
            lambda: Artifact.objects.filter(job_id=job_id).update(created_at=timezone.now()),
            lambda: SourceCitation.objects.filter(job_id=job_id).update(source_title="Changed"),
            lambda: UsageReservation.objects.filter(job_id=job_id).update(period_start=timezone.now().date() - timedelta(days=1)),
            lambda: JobCancellation.objects.create(job_id=job_id, requested_by=self.owner),
            lambda: Finding.objects.filter(source_passive_redirect_id=job_id).update(actor=self.owner),
            lambda: Finding.objects.filter(source_passive_redirect_id=job_id).update(detected_at=timezone.now()),
            lambda: Finding.objects.filter(source_passive_redirect_id=job_id).update(confidence="high"),
            lambda: Finding.objects.filter(source_passive_redirect_id=job_id).delete(),
            lambda: OrganizationTrial.objects.filter(organization=self.organization).update(
                started_at=timezone.now() - timedelta(days=31), ends_at=timezone.now() - timedelta(days=1)))
        for method in ("POST", "GET"):
            if method == "GET": self.assertEqual(self.save(expected).status_code, 200)
            for change in changes:
                with self.subTest(method=method, change=change), transaction.atomic():
                    def serialized(data, *args, **kwargs):
                        result = response(data, *args, **kwargs)
                        if "finding_set" in data: change()
                        return result
                    with patch.object(api, "_response", side_effect=serialized):
                        result = self.save(expected) if method == "POST" else self.client.get(self.path, secure=True)
                    self.assertIn(result.status_code, (403, 409), result.content); self.assertNotIn(b"collection_sha256", result.content)
                    if method == "POST": self.assertFalse(Finding.objects.exists())
                    transaction.set_rollback(True)
        self.client.force_login(self.owner)
        def demoted_materializer(data, *args, **kwargs):
            result = response(data, *args, **kwargs)
            if "finding_set" in data:
                OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="member")
            return result
        with patch.object(api, "_response", side_effect=demoted_materializer):
            self.assertEqual(self.client.get(self.path, secure=True).status_code, 403)
