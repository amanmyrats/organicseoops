import json
from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.db import connection, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import OrganizationMembership, OrganizationTrial, Project, ProjectMembership, ProjectOriginVerification
from . import passive_header_api as api
from . import passive_resource_collection as collector
from . import test_passive_resource_api as fixtures
from . import test_passive_header_findings_api as header_checks
from .models import Artifact, Finding, JobCancellation, JobRun, JobStep, Opportunity, Recommendation, SourceCitation, UsageReservation


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "resource-findings-api"}})
class ResourceFindingApiTests(TransactionTestCase):
    setUp = fixtures.PassiveResourceApiTests.setUp
    verified = fixtures.PassiveResourceApiTests.verified
    transport = fixtures.PassiveResourceApiTests.transport
    post = fixtures.PassiveResourceApiTests.post
    command = fixtures.PassiveResourceApiTests.command

    def collected(self, body=None, key="resource-finding-api"):
        job_id = self.post(data=self.command(key)).json()["job"]["id"]
        self.assertTrue(collector.execute_passive_resource_collection(job_id, fetcher=self.transport(body=body)))
        self.suffix = f"{job_id}/findings/"; self.path = self.base + self.suffix
        return job_id

    def save(self, digest):
        return self.post(self.suffix, {"candidate_digest": digest})

    test_methods_csrf_strict_json_digest_query_and_scope = header_checks.HeaderFindingApiTests.test_methods_csrf_strict_json_digest_query_and_scope
    test_natural_exact_expiry_after_serialization_rolls_back_post = header_checks.HeaderFindingApiTests.test_natural_exact_expiry_after_serialization_rolls_back_post

    def test_original_resource_get_is_private_read_only_and_sha_post_saves_one_idempotent_fact_without_new_work(self):
        job_id = self.collected()
        with patch("socket.create_connection", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            result = self.client.get(self.path, secure=True)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        initial = result.json(); expected = api._digest(initial["candidates"])
        self.assertEqual(initial["candidate_digest"], expected)
        self.assertEqual(initial["finding_set"]["state"], "no_retained_materialized_findings")
        self.assertEqual(initial["candidates"]["candidates"][0]["evidence"]["counts"]["http_absolute"], 1)
        counts = (JobRun.objects.count(), UsageReservation.objects.count())
        saved = self.save(expected); self.assertEqual(saved.status_code, 200, saved.content)
        self.assertEqual(self.save(expected).json(), saved.json()); self.assertEqual(self.client.get(self.path, secure=True).json(), saved.json())
        self.assertEqual(len(saved.json()["finding_set"]["findings"]), 1)
        self.assertEqual(saved.json()["finding_set"]["findings"][0]["source_passive_resource_id"], job_id)
        self.assertEqual((JobRun.objects.count(), UsageReservation.objects.count()), counts)
        self.assertEqual((Opportunity.objects.count(), Recommendation.objects.count()), (0, 0))
        self.assertEqual(result["Cache-Control"], "private, no-store"); self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")
        for raw in (b"private.invalid", b"secret", self.challenge.encode(), self.owner.email.encode()): self.assertNotIn(raw, saved.content)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        self.client.force_login(self.member); self.assertEqual(self.save(expected).json(), saved.json())
        self.assertEqual(set(Finding.objects.values_list("actor_id", flat=True)), {self.owner.pk})
        self.connection.request.assert_called_once()

    def test_fixed_original_family_roles_failed_sources_and_observed_empty_vs_lexical_null(self):
        job_id = self.collected()
        for actor, status in ((self.member, 403), (self.outsider, 404)):
            client = Client(); client.force_login(actor); self.assertEqual(client.get(self.path, secure=True).status_code, status)
        self.assertEqual(self.client.get(self.path.replace("passive-resources", "passive-headers"), secure=True).status_code, 403)
        for changes, status in (({"handler": "collect_passive_headers"}, 403), ({"handler": "collect_passive_tls"}, 403),
            ({"handler": "collect_passive_redirects"}, 403), ({"status": "failed"}, 403), ({"output": {}}, 409)):
            with transaction.atomic():
                JobRun.objects.filter(pk=job_id).update(**changes); self.assertEqual(self.client.get(self.path, secure=True).status_code, status)
                transaction.set_rollback(True)
        for key, body, state in (("empty", b"", "original_lexical_review_candidates"),
            ("null", b'<img src="x" src="y">', "original_lexical_evaluation_unavailable")):
            self.collected(body=body, key="resource-" + key)
            initial = self.client.get(self.path, secure=True).json()
            self.assertEqual((initial["candidates"]["state"], initial["candidates"]["candidates"]), (state, []))
            self.assertEqual(initial["finding_set"]["state"], "no_retained_materialized_findings")
            self.assertEqual(self.save(initial["candidate_digest"]).json(), initial)
        self.assertFalse(Finding.objects.exists())

    def test_independent_resource_finding_read_write_user_ip_budgets_do_not_consume_header_or_resource_capture_budgets(self):
        self.collected(); expected = self.client.get(self.path, secure=True).json()["candidate_digest"]
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        other = Client(); other.force_login(self.member)
        for limit in ("1/m/user", "1/m/ip"):
            cache.clear()
            with override_settings(ACCOUNT_RATE_LIMITS={action: limit for action in ("passive_resource_findings_read", "passive_resource_findings_write")}):
                self.assertEqual(self.client.get(self.path, secure=True).status_code, 200)
                self.assertEqual(self.client.get(self.path, secure=True).status_code, 429)
                self.assertEqual(self.save(expected).status_code, 200); self.assertEqual(self.save(expected).status_code, 429)
                self.assertEqual(self.client.get(self.base, secure=True).status_code, 200)
                self.assertEqual(self.client.get(self.base.replace("passive-resources", "passive-headers"), secure=True).status_code, 200)
                self.assertEqual(self.post("selection/").status_code, 200)
                if limit.endswith("ip"):
                    self.assertEqual(other.get(self.path, secure=True).status_code, 429)
                    self.assertEqual(other.post(self.path, json.dumps({"candidate_digest": expected}), content_type="application/json", secure=True).status_code, 429)

    def test_restricted_original_scope_requires_independent_current_project_grant(self):
        Project.objects.filter(pk=self.project.pk).update(access_restricted=True)
        job_id = self.collected(); expected = self.client.get(self.path, secure=True).json()["candidate_digest"]
        membership = OrganizationMembership.objects.get(organization=self.organization, user=self.member)
        OrganizationMembership.objects.filter(pk=membership.pk).update(role="admin")
        client = Client(); client.force_login(self.member)
        self.assertEqual(client.get(self.path, secure=True).status_code, 404)
        ProjectMembership.objects.create(project=self.project, organization_membership=membership)
        self.assertEqual(client.get(self.path, secure=True).status_code, 200)
        self.assertEqual(self.save(expected).status_code, 200)
        Finding.objects.filter(source_passive_resource_id=job_id).update(actor=self.member)
        ProjectMembership.objects.filter(project=self.project, organization_membership=membership).delete()
        self.assertEqual(self.client.get(self.path, secure=True).status_code, 403)

    def test_post_serialization_full_source_rows_materializer_late_caller_and_cancel_loss_rollback(self):
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
            lambda: Finding.objects.filter(source_passive_resource_id=job_id).update(actor=self.owner),
            lambda: Finding.objects.filter(source_passive_resource_id=job_id).update(detected_at=timezone.now()),
            lambda: Finding.objects.filter(source_passive_resource_id=job_id).update(confidence="high"),
            lambda: Finding.objects.filter(source_passive_resource_id=job_id).delete())
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
        # Retained materializer loss is independent of the original source owner and delivery caller.
        self.client.force_login(self.owner)
        def demoted_materializer(data, *args, **kwargs):
            result = response(data, *args, **kwargs)
            if "finding_set" in data:
                OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="member")
            return result
        with patch.object(api, "_response", side_effect=demoted_materializer):
            self.assertEqual(self.client.get(self.path, secure=True).status_code, 403)
