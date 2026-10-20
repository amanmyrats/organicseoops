from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase, TransactionTestCase, override_settings

from config.test_foundations import TEST_STORAGES
from tenancy.models import MembershipRole, OrganizationMembership
from tenancy.services import update_project
from . import test_diagnostics as crawl_fixtures, test_visibility_entities as entity_fixtures, test_content as content_fixtures
from .action_review import record_action
from .diagnostics import build_technical_diagnostics
from .findings import record_technical_findings, review_finding
from .models import ActionReview, Finding, JobRun, Opportunity
from .visibility_discoverability import discoverability_evidence


@override_settings(STORAGES=TEST_STORAGES,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "text/csv"}),
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class DiscoverabilityTests(TestCase):
    page = crawl_fixtures.TechnicalDiagnosticsTests.page

    def setUp(self):
        crawl_fixtures.TechnicalDiagnosticsTests.setUp(self)
        self.page("/", b'<html><script type="application/ld+json">{bad</script><p>Human service facts unknown</p></html>',
            structured_data_errors=[{"block": 1, "category": "invalid_json"}])
        self.job.status = "partially_succeeded"; self.job.save(update_fields=["status"])
        self.source = build_technical_diagnostics(self.run.pk)
        self.path = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/visibility-discoverability/"

    def test_readonly_evidence_unknown_agent_access_then_human_priority_and_separate_action_approval(self):
        before = JobRun.objects.count()
        report = discoverability_evidence(project=self.project, actor=self.owner, diagnostics_id=self.source.pk)
        self.assertEqual(report["proposals"], [])
        self.assertEqual({item["access"] for item in report["provider_agents"]}, {"unavailable_no_agent_specific_robots_evidence"})
        self.assertIn("robots_may_not_apply", report["provider_agents"][2]["purpose"])
        self.assertEqual((Finding.objects.count(), Opportunity.objects.count(), ActionReview.objects.count()), (0, 0, 0))
        findings, _ = record_technical_findings(project=self.project, actor=self.owner, diagnostics_id=self.source.pk)
        finding = next(row for row in findings if row.detector.startswith("schema_"))
        report = discoverability_evidence(project=self.project, actor=self.owner, diagnostics_id=self.source.pk)
        proposal = next(row for row in report["proposals"] if row["id"] == finding.pk)
        self.assertTrue(proposal["source_current"])
        self.assertIn("does not establish", proposal["proposal"])
        self.assertEqual(proposal["evidence"]["snapshot_id"], self.source.pk)
        review = review_finding(project=self.project, actor=self.owner, finding_id=finding.pk,
            expected_revision=0, priority="medium", estimated_effort="small", business_relevance="unknown",
            reason="Review syntax against visible genuine business facts; no AI placement promise.")
        fields = dict(project=self.project, actor=self.owner, source_type="opportunity", source_id=review.pk,
            state="proposed", action_kind="refresh", assignee_id=self.owner.pk,
            acceptance_criteria="Correct syntax with verified visible facts and later check the exact page.",
            reason="Human proposal based on the exact stored snapshot.")
        with self.assertRaises(ValidationError): record_action(**{**fields, "state": "accepted", "request_key": "skip-human-proposal"})
        proposed = record_action(**fields, request_key="discoverability-proposal")
        accepted = record_action(**{**fields, "state": "accepted"}, action_id=proposed.action_id,
            expected_revision=1, request_key="discoverability-accept")
        self.assertEqual(accepted.state, "accepted"); self.assertIsNone(accepted.implemented_at)
        self.assertEqual(JobRun.objects.count(), before)
        update_project(project=self.project, user=self.owner, canonical_origin="https://changed.example.invalid")
        report = discoverability_evidence(project=self.project, actor=self.owner, diagnostics_id=self.source.pk)
        self.assertFalse(any(row["source_current"] for row in report["proposals"]))
        with self.assertRaises(ValidationError):
            review_finding(project=self.project, actor=self.owner, finding_id=finding.pk,
                expected_revision=1, priority="high", estimated_effort="small", business_relevance="unknown", reason="Stale")

    def test_private_get_scope_viewer_foreign_filter_no_mutation_and_source_actor_revocation(self):
        self.assertEqual(Client().get(self.path).status_code, 401)
        reader = get_user_model().objects.create_user("discover-reader@example.invalid", password="test-password")
        browser = Client(); browser.force_login(reader)
        self.assertEqual(browser.get(self.path).status_code, 404)
        membership = OrganizationMembership.objects.create(organization=self.organization, user=reader, role=MembershipRole.VIEWER)
        response = browser.get(self.path + f"?diagnostics={self.source.pk}")
        self.assertEqual(response.status_code, 200); self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(browser.post(self.path, "{}", content_type="application/json").status_code, 405)
        self.assertEqual(browser.get(self.path + "?diagnostics=0").status_code, 400)
        self.assertEqual(browser.get(self.path + "?other=1").status_code, 400)
        self.assertEqual(browser.get(self.path + "?diagnostics=999999").status_code, 404)
        record = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/findings/technical/{self.source.pk}/"
        self.assertEqual(browser.post(record, "{}", content_type="application/json").status_code, 403)
        owner = Client(enforce_csrf_checks=True); owner.force_login(self.owner)
        self.assertEqual(owner.post(record, "{}", content_type="application/json").status_code, 403)
        self.assertFalse(Finding.objects.exists())
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role=MembershipRole.VIEWER)
        response = browser.get(self.path).json(); self.assertFalse(response["diagnostics"][0]["source_current"])
        membership.delete(); self.assertEqual(browser.get(self.path).status_code, 404)
        with self.assertRaises(PermissionDenied): discoverability_evidence(project=self.project, actor=reader)


@override_settings(STORAGES=TEST_STORAGES, CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class DiscoverabilityEntityTests(TestCase):
    fixture_project = entity_fixtures.VisibilityEntityTests.fixture_project
    queue = entity_fixtures.VisibilityEntityTests.queue
    execute = entity_fixtures.VisibilityEntityTests.execute
    sample = entity_fixtures.VisibilityEntityTests.sample

    def test_latest_human_concern_preserves_exact_span_not_verified_fact_or_visit(self):
        entity_fixtures.fixture(self)
        from .visibility_entities import review_answer
        job = self.sample("😀 Synthetic Brand pricing unknown.")
        data = dict(project=self.project, actor=self.owner, job_id=job.pk, expected_configuration_revision=2,
            matches=[], evaluated=False, review_note="Human concern, not verified truth.")
        review_answer(**data, request_key="concern-review-one", expected_revision=0,
            factual_notes=[{"start": 2, "end": 17, "note": "Check original records."}])
        report = discoverability_evidence(project=self.project, actor=self.owner)
        self.assertEqual(report["human_factual_concerns"][0]["text"], "Synthetic Brand")
        self.assertIn("not factual truth", report["human_factual_concerns"][0]["proposal"])
        self.assertIn("approved_business_fact_registry", report["unavailable"])
        review_answer(**data, request_key="concern-review-two", expected_revision=1, factual_notes=[])
        self.assertEqual(discoverability_evidence(project=self.project, actor=self.owner)["human_factual_concerns"], [])


@override_settings(STORAGES=TEST_STORAGES,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "text/csv"}),
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class DiscoverabilityContentTests(TransactionTestCase):
    def test_exact_latest_content_revision_preserves_review_reference_without_quality_claim(self):
        content_fixtures.ContentTests.setUp(self)
        first = content_fixtures.ContentTests.record(self)
        latest = content_fixtures.ContentTests.record(self, first, request_key="content-discoverability-two", title="Revised human draft")
        report = discoverability_evidence(project=self.project, actor=self.owner)
        self.assertEqual([row["revision_id"] for row in report["content_revisions"]], [latest.pk])
        self.assertEqual(report["content_revisions"][0]["brief_id"], self.brief.pk)
        self.assertIsNone(report["content_revisions"][0]["reviewed_revision_id"])
        self.assertIn("not verified live-page quality", report["content_revisions"][0]["proposal"])
