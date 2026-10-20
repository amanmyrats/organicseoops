from tenancy.customer_artifact_barrier import project_artifact_barrier
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from io import BytesIO
from threading import Barrier
from zipfile import ZipFile
from unittest.mock import patch
import json
import re

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connection
from django.test import Client, SimpleTestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.artifacts import project_artifact_scope
from config.artifacts import save_private_artifact
from tenancy.models import OrganizationMembership, Project, ProjectConfiguration
from tenancy.services import create_origin_verification, revoke_origin_verification, update_project_configuration
from .authority_links import MAX_BYTES, METHOD, POLICY, SOURCE, link_review_source_current, own_target_evidence, record_authority_link, recovery_action_evidence, validate_link_intake
from .crawler import execute_crawl_job, queue_crawl
from .crawling import FetchError, FetchResponse, RedirectHop
from .models import Artifact, CrawlPageSnapshot, CrawlRun, JobRun
from .security import execute_origin_verification, queue_origin_verification
from . import test_crawler as crawl_fixtures
from .test_crawler import FakeFetcher, response


def intake(**changes):
    target = "https://crawl.example.com/target"
    return {**dict(policy=POLICY, source_kind=SOURCE, configuration_revision=0, origin="https://crawl.example.com",
        crawl_page_id=1, observation_reference="manual-link-1", source_url="https://publisher.example.invalid/article",
        target_url=target, observed_at=(timezone.now() - timedelta(hours=1)).isoformat(), status="observed",
        coverage="partial_page", surface="html_document", href=target, anchor_text="Human observed anchor",
        rel="nofollow", evidence_note="Customer report only; independent source/link validity unverified.",
        use_permission=True, storage_permission=True, not_restricted_provider_copy=True, no_personal_payload=True), **changes}


class HumanLinkIntakeTests(SimpleTestCase):
    def test_preserves_original_scalars_dates_and_complete_declared_absence_without_inference(self):
        data = intake(observed_at="2026-01-01T01:00:00+01:00", anchor_text="Untrusted <b>literal</b>")
        stored = validate_link_intake(data)
        self.assertEqual(stored, data)
        self.assertIsNot(stored, data)
        for changes in (dict(status="not_seen_in_inspected_page", href="", anchor_text="", rel="",
                             coverage="complete_document_customer_reported"),
                        dict(status="unavailable", href="", anchor_text="", rel="", coverage="unavailable", surface="unknown")):
            result = validate_link_intake(intake(**changes))
            self.assertEqual(result["href"], "")
            self.assertNotIn("lost_link", result)

    def test_rejects_provider_identity_objects_unsafe_urls_unaffirmed_rights_and_invalid_numbers(self):
        for changes in ({"provider_response": {}}, {"contact_email": "fixture@example.invalid"}, {"source_url": {}},
            {"configuration_revision": True}, {"crawl_page_id": True}, {"crawl_page_id": 2**53},
            {"storage_permission": 1}, {"use_permission": False}, {"not_restricted_provider_copy": False},
            {"no_personal_payload": False}, {"observation_reference": "contains contact text"},
            {"source_url": "https://crawl.example.com/external"}, {"source_url": "http://publisher.example.invalid/page"},
            {"source_url": "https://publisher.example.invalid:444/page"}, {"source_url": "https://user:secret@publisher.example.invalid/page"},
            {"source_url": "https://publisher.example.invalid/page?secret=x"}, {"source_url": "https://publisher.example.invalid/page#fragment"},
            {"source_url": "https://publisher.example.invalid/\npage"}, {"target_url": "https://crawl.example.com.evil.invalid/target"},
            {"target_url": "https://crawl.example.com/target?tracking=x"}, {"evidence_note": "bad\ud800"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                validate_link_intake(intake(**changes))

    def test_rejects_relative_href_inferred_loss_contradictory_coverage_naive_future_and_overflow(self):
        for changes in ({"href": "/target"}, {"href": "https://crawl.example.com/other"},
            {"status": "lost"}, {"status": ["observed"]}, {"coverage": "complete_web"},
            {"status": "not_seen_in_inspected_page"}, {"coverage": "unavailable"}, {"surface": "unknown"},
            {"status": "unavailable", "href": "", "anchor_text": "", "rel": "", "coverage": "partial_page", "surface": "unknown"},
            {"observed_at": "2026-01-01T01:00:00"}, {"observed_at": "invalid"},
            {"observed_at": (timezone.now() + timedelta(days=1)).isoformat()}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                validate_link_intake(intake(**changes))
        # JSON's default escaping is the actual serialized ceiling used by persistence.
        large = intake(source_url="https://publisher.example.invalid/" + "界" * 900,
            target_url="https://crawl.example.com/" + "界" * 900, href="https://crawl.example.com/" + "界" * 900,
            evidence_note="界" * 500, anchor_text="界" * 240)
        self.assertGreater(len(json.dumps(large).encode()), MAX_BYTES)
        with self.assertRaises(ValidationError): validate_link_intake(large)


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json"}), DEBUG=True)
class OwnTargetEvidenceTests(TransactionTestCase):
    queue = crawl_fixtures.CrawlerTests.queue

    def setUp(self):
        crawl_fixtures.CrawlerTests.setUp(self)
        update_project_configuration(project=self.project, user=self.owner, expected_revision=0, changes={"seed_topics": ["Human recovery review"]})
        self.target = self.project.canonical_origin + "/target"
        self.verification, challenge = create_origin_verification(project=self.project, user=self.owner, origin=self.project.canonical_origin)
        with patch("jobs.tasks.verify_project_origin_task.apply_async"):
            job = queue_origin_verification(verification=self.verification, actor=self.owner, idempotency_key="authority-target-verification")
        class VerificationFetcher:
            def fetch(inner, url, *, before_request):
                before_request(url)
                return FetchResponse(url=url, status=200, headers={"content-type": "text/plain"}, body=challenge.encode())
        self.assertTrue(execute_origin_verification(job.pk, fetcher_factory=lambda _scope: VerificationFetcher()))
        self.page = self.crawl("authority-target-first")
        self.data = intake(crawl_page_id=self.page.pk, configuration_revision=1)

    def crawl(self, key, target_response=None):
        root = self.project.canonical_origin + "/"
        target_response = target_response if target_response is not None else response(self.target,
            status=404, body=b"<title>Missing destination</title>", headers={"content-type": "text/html", "etag": '"missing-v1"'})
        responses = {self.project.canonical_origin + "/robots.txt": [response(self.project.canonical_origin + "/robots.txt", status=404)],
            self.project.canonical_origin + "/sitemap.xml": [response(self.project.canonical_origin + "/sitemap.xml", status=404)],
            root: [response(root, body=b'<a href="/target">Target</a>', headers={"content-type": "text/html"})],
            self.target: [target_response]}
        job = self.queue(key=key, page_limit=2)
        self.assertTrue(execute_crawl_job(job.pk, fetcher_factory=lambda scope: FakeFetcher(scope, responses), sleep=lambda _seconds: None))
        return job.crawl_run.pages.get(requested_url=self.target)

    def evidence(self, **changes):
        return own_target_evidence(**{**dict(project=self.project, actor=self.owner, intake=self.data), **changes})[2]

    def test_actual_http_body_readback_is_separate_from_human_link_no_write_or_network(self):
        counts = [model.objects.count() for model in (Artifact, JobRun, CrawlRun, CrawlPageSnapshot)]
        with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            result = self.evidence()
        self.assertFalse(any(re.match(r"\s*(INSERT|UPDATE|DELETE)\b", row["sql"], re.I) for row in queries))
        self.assertEqual(counts, [model.objects.count() for model in (Artifact, JobRun, CrawlRun, CrawlPageSnapshot)])
        self.assertEqual(result["method"], METHOD)
        self.assertEqual(result["state"], "dated_http_missing_destination_candidate")
        self.assertEqual(result["raw_body_readback"], "checked")
        self.assertEqual(result["external_source"], "customer_reported_not_independently_verified")
        self.assertEqual(result["unlinked_or_lost_link"], "not_established")
        absent = {**self.data, "status": "not_seen_in_inspected_page", "href": "", "anchor_text": "", "rel": "",
            "coverage": "complete_document_customer_reported"}
        self.assertEqual(self.evidence(intake=absent)["unlinked_or_lost_link"], "not_established")
        self.assertEqual(result["coverage"]["whole_site"], "not_established")

    def test_foreign_removed_project_viewer_email_source_actor_origin_and_alias_denials(self):
        other = get_user_model().objects.create_user("authority-target-other@example.invalid")
        EmailAddress.objects.create(user=other, email=other.email, primary=True, verified=True)
        membership = OrganizationMembership.objects.create(organization=self.organization, user=other, role="viewer")
        with self.assertRaises(PermissionDenied): self.evidence(actor=other)
        membership.role = "admin"; membership.save()
        self.evidence(actor=other)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
        with self.assertRaises(PermissionDenied): self.evidence(actor=other)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="owner")
        EmailAddress.objects.filter(user=self.owner).update(verified=False)
        with self.assertRaises(PermissionDenied): self.evidence(actor=other)
        EmailAddress.objects.filter(user=self.owner).update(verified=True)
        foreign = Project.objects.create(organization=self.organization, name="Synthetic foreign target", canonical_origin="https://foreign.example.invalid")
        with self.assertRaises(PermissionDenied): self.evidence(project=foreign)
        with self.assertRaises(PermissionDenied): self.evidence(intake={**self.data, "crawl_page_id": self.page.pk + 10000})
        from tenancy.models import DomainAlias
        DomainAlias.objects.create(organization=self.organization, project=self.project, origin="http://alias.example.invalid")
        with self.assertRaises(ValidationError): self.evidence(intake={**self.data, "source_url": "https://alias.example.invalid/page"})
        with self.assertRaises(PermissionDenied): self.evidence(project=Project(pk=self.project.pk + 10000, organization=self.organization))
        revoke_origin_verification(verification=self.verification, user=self.owner)
        with self.assertRaises(PermissionDenied): self.evidence()

    def test_private_body_tamper_foreign_artifact_and_changed_configuration_deny_use(self):
        artifact = self.page.raw_artifact
        original = artifact.key, artifact.size_bytes
        with project_artifact_barrier(self.project.organization_id, shared=True):
            key = save_private_artifact(scope=f"{project_artifact_scope(self.project)}/jobs/{artifact.job_id}",
                content=b"Different retained body", content_type="text/html")
        Artifact.objects.filter(pk=artifact.pk).update(key=key, size_bytes=len(b"Different retained body"))
        with self.assertRaises(ValidationError): self.evidence()
        Artifact.objects.filter(pk=artifact.pk).update(key=original[0], size_bytes=original[1])
        foreign = Project.objects.create(organization=self.organization, name="Synthetic foreign body", canonical_origin="https://body.example.invalid")
        Artifact.objects.filter(pk=artifact.pk).update(project=foreign)
        with self.assertRaises(ValidationError): self.evidence()
        Artifact.objects.filter(pk=artifact.pk).update(project=self.project)
        update_project_configuration(project=self.project, user=self.owner, expected_revision=1, changes={"ignored_query_parameters": ["utm_source"]})
        with self.assertRaises(ValidationError): self.evidence()
        with self.assertRaises(ValidationError): self.evidence(intake={**self.data, "configuration_revision": 2})
        ProjectConfiguration.objects.filter(project=self.project).delete()
        with self.assertRaises(ValidationError): self.evidence()

    def test_304_reuses_actual_older_body_without_claiming_success_or_recovery(self):
        second = self.crawl("authority-target-recheck", response(self.target, status=304))
        result = self.evidence(intake={**self.data, "crawl_page_id": second.pk})
        self.assertEqual(result["status_code"], 304)
        self.assertEqual(result["state"], "not_modified_reused_body_not_new_success_status")
        self.assertEqual(result["content_observed_at"], self.page.observed_at.isoformat())
        self.assertEqual(result["reused_from_id"], self.page.pk)
        self.assertEqual(result["raw_body_readback"], "checked")
        CrawlPageSnapshot.objects.filter(pk=second.pk).update(reused_from=None)
        with self.assertRaises(ValidationError): self.evidence(intake={**self.data, "crawl_page_id": second.pk})

    def test_terminal_partial_errors_redirects_and_newer_success_keep_dated_unknowns(self):
        error = self.crawl("authority-target-error", FetchError("timeout"))
        result = self.evidence(intake={**self.data, "crawl_page_id": error.pk})
        self.assertEqual(result["state"], "fetch_failed_or_unavailable_not_broken_proof")
        self.assertIsNone(result["status_code"])
        self.assertEqual(result["raw_body_readback"], "not_retained")
        self.assertEqual(result["coverage"]["crawl_status"], "partially_succeeded")
        destination = self.project.canonical_origin + "/restored"
        success = self.crawl("authority-target-success", FetchResponse(url=destination, status=200,
            body=b"<title>Restored</title>", headers={"content-type": "text/html"}, redirects=(RedirectHop(self.target, 301),)))
        result = self.evidence(intake={**self.data, "crawl_page_id": success.pk})
        self.assertEqual(result["state"], "dated_http_success_not_usefulness_or_link_recovery_proof")
        self.assertEqual(result["final_url"], destination)
        self.assertEqual(result["redirect_chain"], [{"url": self.target, "status": 301}])
        CrawlPageSnapshot.objects.filter(pk=success.pk).update(final_url="https://foreign.example.invalid/target")
        with self.assertRaises(ValidationError): self.evidence(intake={**self.data, "crawl_page_id": success.pk})
        CrawlRun.objects.filter(pk=self.page.crawl_run_id).update(completed_at=None)
        with self.assertRaises(ValidationError): self.evidence()

    def recovery_action(self):
        from .action_review import record_action
        from .diagnostics import build_technical_diagnostics
        from .findings import record_technical_findings, review_finding
        source = build_technical_diagnostics(self.page.crawl_run_id)
        findings, _truncated = record_technical_findings(project=self.project, actor=self.owner, diagnostics_id=source.pk)
        finding = next(row for row in findings if row.detector == "observed_http_error_candidate" and row.subject == self.target)
        opportunity = review_finding(project=self.project, actor=self.owner, finding_id=finding.pk, expected_revision=0,
            priority="high", estimated_effort="small", business_relevance="high", reason="Human selected useful target recovery.")
        return record_action(project=self.project, actor=self.owner, request_key="authority-target-action-proposed",
            source_type="opportunity", source_id=opportunity.pk, action_kind="refresh", state="proposed",
            assignee_id=self.owner.pk, acceptance_criteria="Restore the useful exact target; inspect actual HTTP evidence.",
            reason="Independent own-site page proposal; no external outreach approval.")

    def test_genuine_diagnostic_finding_opportunity_page_action_and_manual_crawl_followup_stay_separate(self):
        from .action_review import record_action
        from .models import ActionReview, Finding, Opportunity
        from .technical_outcome import compare_action_crawls
        action = self.recovery_action()
        counts = [model.objects.count() for model in (ActionReview, Finding, Opportunity, Artifact, JobRun)]
        with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No network")):
            result = recovery_action_evidence(project=self.project, actor=self.owner, intake=self.data, action_review_id=action.pk)
        self.assertEqual(counts, [model.objects.count() for model in (ActionReview, Finding, Opportunity, Artifact, JobRun)])
        self.assertEqual(result["action_review_id"], action.pk)
        self.assertIsNone(result["site_approval_review_id"])
        self.assertIsNone(result["implemented_at"])
        for state in ("accepted", "in_progress", "implemented"):
            action = record_action(project=self.project, actor=self.owner, request_key=f"authority-target-action-{state}",
                source_type="opportunity", source_id=action.opportunity_id, action_kind="refresh", state=state,
                assignee_id=self.owner.pk, acceptance_criteria=action.acceptance_criteria, reason="Separate human website action.",
                action_id=action.action_id, expected_revision=action.revision,
                implemented_at=timezone.now() if state == "implemented" else None,
                change_summary="Actual manual implementation report, not external link verification." if state == "implemented" else "")
        result = recovery_action_evidence(project=self.project, actor=self.owner, intake=self.data, action_review_id=action.pk)
        self.assertIsNotNone(result["site_approval_review_id"])
        self.assertEqual(result["implemented_at"], action.implemented_at.isoformat())
        after = self.crawl("authority-target-after-implementation", response(self.target, status=200,
            body=b"<title>Useful target restored</title>", headers={"content-type": "text/html"}))
        followup = compare_action_crawls(project=self.project, actor=self.owner, action_id=action.action_id,
            previous_crawl_id=self.page.crawl_run_id, current_crawl_id=after.crawl_run_id)
        self.assertEqual(followup["urls"][0]["changes"]["status_code"], {"previous": 404, "current": 200})
        self.assertIn("not_automatic_verification", followup["interpretation"])
        self.assertEqual(result["target_evidence"]["unlinked_or_lost_link"], "not_established")

    def test_recovery_rejects_wrong_page_source_actor_loss_edited_opportunity_and_stale_action(self):
        from .action_review import record_action
        from .findings import review_finding
        from .models import Finding
        action = self.recovery_action()
        def evidence(**changes):
            return recovery_action_evidence(**{**dict(project=self.project, actor=self.owner,
                intake=self.data, action_review_id=action.pk), **changes})
        with self.assertRaises(ValidationError): evidence(action_review_id=True)
        with self.assertRaises(PermissionDenied): evidence(action_review_id=action.pk + 10000)
        absent = {**self.data, "status": "not_seen_in_inspected_page", "href": "", "anchor_text": "", "rel": ""}
        with self.assertRaises(ValidationError): evidence(intake=absent)
        details = action.opportunity.finding.evidence
        Finding.objects.filter(pk=action.opportunity.finding_id).update(evidence={**details,
            "details": {**details["details"], "crawl_page_id": self.page.pk + 10000}})
        with self.assertRaises(ValidationError): evidence()
        Finding.objects.filter(pk=action.opportunity.finding_id).update(evidence=details)
        accepted = record_action(project=self.project, actor=self.owner, request_key="authority-target-accepted-negative",
            source_type="opportunity", source_id=action.opportunity_id, action_kind="refresh", state="accepted",
            assignee_id=self.owner.pk, acceptance_criteria=action.acceptance_criteria, reason="Separate exact website approval.",
            action_id=action.action_id, expected_revision=action.revision)
        with self.assertRaises(ValidationError): evidence()
        evidence(action_review_id=accepted.pk)
        review_finding(project=self.project, actor=self.owner, finding_id=action.opportunity.finding_id, expected_revision=1,
            priority="medium", estimated_effort="small", business_relevance="high", reason="New human opportunity revision.")
        with self.assertRaises(ValidationError): evidence(action_review_id=accepted.pk)


class LinkReviewFixture:
    setUp = OwnTargetEvidenceTests.setUp
    crawl = OwnTargetEvidenceTests.crawl
    recovery_action = OwnTargetEvidenceTests.recovery_action

    def queue(self, *, key, page_limit):
        with patch("jobs.tasks.execute_crawl_job_task.apply_async"):
            return queue_crawl(project=self.project, actor=self.owner, seeds=[], page_limit=page_limit, idempotency_key=key)

    def record(self, **changes):
        return record_authority_link(**{**dict(project=self.project, actor=self.owner, request_key="human-link-draft-1",
            intake=self.data, proposal={"action": "verify_source", "relevance": "Human relevant useful source/destination.",
                "draft_text": "Inspect the actual source separately; no claimed recovered link.", "outreach_permission": False},
            assignee_id=self.owner.pk, state="draft", reason="Independent human activity decision."), **changes})

    def transition(self, row, state, **changes):
        return self.record(**{**dict(link_id=row.link_id, expected_revision=row.revision, request_key=f"link-{row.link_id.hex[:16]}-{state}-{row.revision}",
            intake=row.intake, proposal=row.proposal, assignee_id=row.assignee_id, recovery_action_review_id=row.recovery_action_review_id,
            state=state), **changes})


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}), DEBUG=True)
class HumanLinkReviewTests(LinkReviewFixture, TransactionTestCase):
    def test_exact_source_review_approval_separate_manual_report_and_reset_with_no_external_effect(self):
        draft = self.record()
        self.assertEqual(self.record().pk, draft.pk)
        with self.assertRaises(ValidationError): self.transition(draft, "approved")
        review = self.transition(draft, "review")
        for changes in ({"proposal": {**review.proposal, "draft_text": "Changed exact text"}},
                        {"intake": {**review.intake, "anchor_text": "Changed original report"}}):
            with self.assertRaises(ValidationError): self.transition(review, "approved", **changes)
        approved = self.transition(review, "approved")
        self.assertEqual(approved.reviewed_revision_id, review.pk)
        self.assertIsNone(approved.executed_at)
        with self.assertRaises(ValidationError):
            self.transition(approved, "reported", executed_at=approved.approved_at - timedelta(seconds=1), execution_note="Before approval")
        counts = [model.objects.count() for model in (Artifact, JobRun, CrawlRun, CrawlPageSnapshot)]
        with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No network")):
            reported = self.transition(approved, "reported", executed_at=timezone.now(), execution_note="Actual separate manual inspection report, unverified externally.")
        self.assertEqual(counts, [model.objects.count() for model in (Artifact, JobRun, CrawlRun, CrawlPageSnapshot)])
        with self.assertRaises(ValidationError): reported.save()
        corrected = self.transition(reported, "draft", proposal={**reported.proposal, "draft_text": "Fresh unapproved human text."})
        self.assertIsNone(corrected.reviewed_revision_id)
        dismissed = self.transition(corrected, "dismissed")
        self.assertEqual(self.transition(dismissed, "draft").state, "draft")
        with self.assertRaises(ValidationError): self.transition(draft, "review", request_key="stale-human-link-1")

    def test_current_actors_assignee_source_roles_rights_foreign_revision_and_direct_model_denial(self):
        from .models import AuthorityLinkReview
        draft = self.record()
        other = get_user_model().objects.create_user("human-link-admin@example.invalid")
        EmailAddress.objects.create(user=other, email=other.email, primary=True, verified=True)
        membership = OrganizationMembership.objects.create(organization=self.organization, user=other, role="admin")
        review = self.transition(draft, "review", actor=other)
        approved = self.transition(review, "approved", actor=other)
        membership.role = "viewer"; membership.save()
        self.assertFalse(link_review_source_current(approved))
        with self.assertRaises(PermissionDenied): self.transition(approved, "reported", executed_at=timezone.now(), execution_note="Actor lost role")
        with self.assertRaises(PermissionDenied): self.record(actor=other, request_key="human-link-viewer")
        with self.assertRaises(PermissionDenied): self.record(assignee_id=other.pk, request_key="human-link-viewer-assignee")
        with self.assertRaises(PermissionDenied): self.record(link_id="00000000-0000-0000-0000-000000000000", expected_revision=1)
        with self.assertRaises(ValidationError): self.record(intake={**self.data, "use_permission": False})
        kwargs = {field.attname: getattr(draft, field.attname) for field in AuthorityLinkReview._meta.concrete_fields
                  if field.attname not in {"id", "created_at"}}
        kwargs.update(link_id="00000000-0000-0000-0000-000000000001", request_key="direct-human-link", intake={**self.data, "href": "/invented"})
        with self.assertRaises(ValidationError): AuthorityLinkReview.objects.create(**kwargs)
        revoke_origin_verification(verification=self.verification, user=self.owner)
        self.assertFalse(link_review_source_current(draft))
        with self.assertRaises(PermissionDenied): self.transition(draft, "draft", request_key="human-link-revoked")

    def test_source_correction_needs_separate_outreach_and_recovery_handoff_never_approves_site_action(self):
        from .models import ActionReview
        proposal = {"action": "request_source_correction", "relevance": "Human source correction judgment.",
            "draft_text": "Human unchanged request text.", "outreach_permission": False}
        draft = self.record(proposal=proposal)
        with self.assertRaises(ValidationError): self.transition(draft, "review")
        correction = self.transition(draft, "draft", proposal={**proposal, "outreach_permission": True})
        self.assertEqual(self.transition(correction, "review").state, "review")
        page_action = self.recovery_action()
        recovery = self.record(request_key="human-link-recovery-draft", proposal={**proposal,
            "action": "review_target_recovery", "outreach_permission": False}, recovery_action_review_id=page_action.pk)
        approved = self.transition(self.transition(recovery, "review"), "approved")
        self.assertIsNone(approved.recovery_evidence["site_approval_review_id"])
        self.assertEqual(ActionReview.objects.get(pk=page_action.pk).state, "proposed")
        self.transition(approved, "reported", executed_at=timezone.now(), execution_note="Human recovery review/handoff only; no website execution.")
        self.assertEqual(ActionReview.objects.filter(action_id=page_action.action_id).count(), 1)

    def test_actual_bounded_stored_sequential_export_retention_closure_and_newest_first_deletion(self):
        from tenancy.customer_export import complete_bounded_customer_archive
        from tenancy.customer_inventory import CUSTOMER
        from tenancy.customer_snapshot import reserve_bounded_customer_snapshot, capture_reserved_customer_snapshot, private_snapshot_part
        from tenancy.customer_source_parts import capture_source_stage
        from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        from tenancy.models import Organization, OrganizationTrial
        from .models import AuthorityLinkReview
        approved = self.transition(self.transition(self.record(), "review"), "approved")
        with ZipFile(BytesIO(complete_bounded_customer_archive(organization=self.organization, actor=self.owner))) as archive:
            row = json.loads(archive.read("records/jobs/AuthorityLinkReview.json"))[-1]
            self.assertTrue(row["source_current_at_capture"])
            self.assertEqual(row["intake"], approved.intake)
            self.assertNotIn("request_key", row)
        with patch("tenancy.tasks.capture_customer_snapshot_task.apply_async"):
            bounded = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner, request_key="c" * 32)
            self.assertTrue(capture_reserved_customer_snapshot(bounded.pk))
            data, _ = private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=bounded.pk, position=0)
            revoke_origin_verification(verification=self.verification, user=self.owner)
            self.assertFalse(link_review_source_current(approved))
            self.assertEqual(private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=bounded.pk, position=0)[0], data)
            sequential = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner, request_key="d" * 32, format="source-parts-v2")
            for _ in range(len(CUSTOMER) * 2 + 10):
                sequential.refresh_from_db()
                if sequential.state != sequential.State.PREPARING: break
                self.assertTrue(capture_source_stage(sequential.pk, sequential.progress.get("step", 0)))
            sequential.refresh_from_db()
            self.assertEqual(sequential.state, sequential.State.READY)
            part = sequential.parts.filter(source__model="jobs.AuthorityLinkReview").first()
            data, _ = private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=sequential.pk, position=part.position)
            with ZipFile(BytesIO(data)) as archive:
                self.assertFalse(json.loads(archive.read("data"))[-1]["source_current_at_capture"])
        now = timezone.now()
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now - timedelta(days=121), ends_at=now - timedelta(days=91))
        with self.assertRaises(PermissionDenied): self.transition(approved, "draft", request_key="human-link-cutoff")
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=now)
        with self.assertRaises(PermissionDenied): self.record(request_key="human-link-closed")
        with self.assertRaises(PermissionDenied):
            private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=bounded.pk, position=0)
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.organization))
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(AuthorityLinkReview.objects.exists())


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json"}), DEBUG=True)
class HumanLinkConcurrencyTests(LinkReviewFixture, TransactionTestCase):
    def test_two_postgresql_connections_cannot_overwrite_the_exact_draft(self):
        from .models import AuthorityLinkReview
        draft = self.record()
        barrier = Barrier(2)
        def write(key):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try: return self.transition(draft, "review", request_key=key).revision
                except ValidationError: return "conflict"
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write, ["human-link-concurrent-1", "human-link-concurrent-2"]))
        self.assertCountEqual(results, [2, "conflict"])
        self.assertEqual(AuthorityLinkReview.objects.filter(link_id=draft.link_id).count(), 2)


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json"}), DEBUG=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "authority-link-api"}})
class HumanLinkApiTests(LinkReviewFixture, TransactionTestCase):
    def payload(self, **changes):
        return {**dict(request_key="link-api-draft-1", intake=self.data, proposal={"action": "verify_source",
            "relevance": "Human judgment, not independent link verification.", "draft_text": "Inspect original source manually.",
            "outreach_permission": False}, assignee_id=self.owner.pk, recovery_action_review_id=None,
            state="draft", reason="Human exact review", executed_at=None, execution_note=""), **changes}

    @property
    def url(self):
        return f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/authority-links/"

    def test_real_get_candidates_no_manufactured_report_or_write_and_csrf_exact_manual_lifecycle(self):
        from .models import ActionReview, AuthorityLinkReview, Finding, Opportunity
        action = self.recovery_action()
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.get(self.url).status_code, 401)
        client.force_login(self.owner)
        counts = [model.objects.count() for model in (AuthorityLinkReview, ActionReview, Finding, Opportunity, Artifact, JobRun)]
        with patch("jobs.authority_links.validate_link_intake", side_effect=AssertionError("GET must not invent human intake")), \
             patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            info = client.get(self.url)
        self.assertEqual(info.status_code, 200, info.content)
        self.assertFalse(any(re.match(r"\s*(INSERT|UPDATE|DELETE)\b", row["sql"], re.I) for row in queries))
        self.assertEqual(counts, [model.objects.count() for model in (AuthorityLinkReview, ActionReview, Finding, Opportunity, Artifact, JobRun)])
        self.assertEqual(info["Cache-Control"], "private, no-store")
        self.assertEqual(info.json()["targets"][0]["verification_id"], self.verification.pk)
        self.assertEqual(info.json()["recovery_actions"][0]["action_review_id"], action.pk)
        self.assertIsNone(info.json()["recovery_actions"][0]["site_approval_review_id"])
        self.assertEqual(info.json()["assignees"], [{"id": self.owner.pk}])
        self.assertEqual(client.post(self.url, json.dumps(self.payload()), content_type="application/json").status_code, 403)
        client.get("/_allauth/browser/v1/auth/session")
        headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value}
        def post(path, data):
            return client.post(path, json.dumps(data), content_type="application/json", **headers)
        payload = self.payload()
        response = post(self.url, payload)
        self.assertEqual(response.status_code, 201, response.content)
        row = response.json()["review"]
        self.assertEqual(post(self.url, payload).json()["review"]["id"], row["id"])
        self.assertEqual(client.get(self.url + "?request_key=link-api-draft-1").json()["lookup"], "found")
        self.assertEqual(client.get(self.url + "?request_key=link-api-unknown").json()["lookup"], "not_found")
        history = self.url + row["link_id"] + "/"
        for revision, state in enumerate(("review", "approved", "reported"), start=1):
            payload = self.payload(request_key=f"link-api-{state}", expected_revision=revision, state=state,
                executed_at=timezone.now().isoformat() if state == "reported" else None,
                execution_note="Actual manual inspection; no independent verification." if state == "reported" else "")
            response = post(history, payload)
            self.assertEqual(response.status_code, 200, response.content)
        info = client.get(history).json()
        self.assertEqual(len(info["reviews"]), 4)
        self.assertTrue(info["reviews"][0]["effective_approval"])
        self.assertEqual(info["reviews"][0]["execution_state"], "customer_reported_manual_activity_not_verified")
        self.assertFalse(client.get(self.url + "?request_key=link-api-draft-1").json()["reviews"][0]["is_latest"])
        self.assertEqual(ActionReview.objects.filter(action_id=action.action_id).count(), 1)

    def test_foreign_viewer_strict_json_own_rate_and_source_loss_keep_history_private(self):
        from .models import AuthorityLinkReview
        self.client.force_login(self.owner)
        for body, content_type in (("{}", "text/plain"), ('{"state":"draft","state":"approved"}', "application/json"),
            ('{"value":NaN}', "application/json"), ('{"value":Infinity}', "application/json"), ('[]', "application/json"),
            ('{}', "application/json"), ('x' * (32 * 1024 + 1), "application/json"), ('{"x":' + '[' * 1500, "application/json")):
            self.assertEqual(self.client.post(self.url, body, content_type=content_type).status_code, 409)
        for query in ("?request_key=link-api-none&request_key=link-api-other", "?foreign_scope=1", "?request_key=bad"):
            self.assertEqual(self.client.get(self.url + query).status_code, 400)
        self.assertEqual(self.client.get(self.url + "00000000-0000-0000-0000-000000000000/").status_code, 404)
        with patch("jobs.authority_links_api.ratelimit.consume", return_value=False) as limiter:
            self.assertEqual(self.client.post(self.url, json.dumps(self.payload()), content_type="application/json").status_code, 429)
            self.assertEqual(limiter.call_args.kwargs["action"], "authority_link_review")
        self.assertEqual(AuthorityLinkReview.objects.count(), 0)
        draft = self.record()
        outsider = get_user_model().objects.create_user("link-api-outsider@example.invalid")
        EmailAddress.objects.create(user=outsider, email=outsider.email, primary=True, verified=True)
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        OrganizationMembership.objects.create(organization=self.organization, user=outsider, role="viewer")
        self.assertFalse(self.client.get(self.url).json()["can_review"])
        self.assertEqual(self.client.get(self.url).json()["targets"], [])
        self.assertEqual(self.client.post(self.url, json.dumps(self.payload()), content_type="application/json").status_code, 403)
        self.client.force_login(self.owner)
        foreign = Project.objects.create(organization=self.organization, name="Synthetic foreign API", canonical_origin="https://foreign.example.invalid")
        foreign_url = f"/api/organizations/{self.organization.pk}/projects/{foreign.pk}/authority-links/"
        self.assertEqual(self.client.get(foreign_url + str(draft.link_id) + "/").status_code, 404)
        self.assertEqual(self.client.post(foreign_url, json.dumps(self.payload()), content_type="application/json").status_code, 403)
        revoke_origin_verification(verification=self.verification, user=self.owner)
        info = self.client.get(self.url).json()
        self.assertEqual(info["targets"], [])
        self.assertFalse(info["reviews"][0]["source_current"])
        self.assertEqual(self.client.post(self.url + str(draft.link_id) + "/", json.dumps(self.payload(
            state="review", expected_revision=1, request_key="link-api-source-loss")), content_type="application/json").status_code, 403)

    def test_genuine_recovery_candidate_and_command_deny_stale_action_or_source_actor(self):
        from .action_review import record_action
        self.client.force_login(self.owner)
        action = self.recovery_action()
        payload = self.payload(proposal={"action": "review_target_recovery", "relevance": "Useful human destination handoff.",
            "draft_text": "Review separately approved website action.", "outreach_permission": False}, recovery_action_review_id=action.pk)
        draft = self.client.post(self.url, json.dumps(payload), content_type="application/json")
        self.assertEqual(draft.status_code, 201, draft.content)
        accepted = record_action(project=self.project, actor=self.owner, request_key="link-api-site-accepted",
            source_type="opportunity", source_id=action.opportunity_id, action_kind="refresh", state="accepted",
            assignee_id=self.owner.pk, acceptance_criteria=action.acceptance_criteria, reason="Separate exact site approval",
            action_id=action.action_id, expected_revision=action.revision)
        info = self.client.get(self.url).json()
        self.assertEqual(info["recovery_actions"][0]["action_review_id"], accepted.pk)
        self.assertFalse(info["reviews"][0]["source_current"])
        history = self.url + draft.json()["review"]["link_id"] + "/"
        self.assertEqual(self.client.post(history, json.dumps({**payload, "state": "review", "expected_revision": 1,
            "request_key": "link-api-stale-recovery"}), content_type="application/json").status_code, 409)
        admin = get_user_model().objects.create_user("link-api-admin@example.invalid")
        EmailAddress.objects.create(user=admin, email=admin.email, primary=True, verified=True)
        OrganizationMembership.objects.create(organization=self.organization, user=admin, role="admin")
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
        self.client.force_login(admin)
        self.assertEqual(self.client.get(self.url).json()["targets"], [])
        self.assertEqual(self.client.get(self.url).json()["recovery_actions"], [])
