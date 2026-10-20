from tenancy.customer_artifact_barrier import project_artifact_barrier
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from threading import Barrier
from zipfile import ZipFile
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.artifacts import save_project_artifact
from tenancy.models import Organization, OrganizationMembership, OrganizationTrial, Project
from tenancy.services import update_project_configuration
from . import test_research as research_fixtures
from .authority import METHOD, POLICY, prospect_source_current, record_authority_prospect, research_authority_source
from .crawling import FetchResponse
from .models import Artifact, AuthorityProspectReview, JobRun, JobStep, SourceCitation
from .research import execute_research, queue_research


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}), DEBUG=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "authority-evidence"}})
class AuthoritySourceTests(TransactionTestCase):
    queue = research_fixtures.ResearchTests.queue
    fetcher = research_fixtures.ResearchTests.fetcher
    response = research_fixtures.ResearchTests.response
    url = research_fixtures.ResearchTests.url

    def setUp(self):
        research_fixtures.ResearchTests.setUp(self)
        self.job = self.queue()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-not-real"}):
            self.assertTrue(execute_research(self.job.pk, fetcher=self.fetcher(), request=self.response))
        self.job.refresh_from_db()

    def source(self, **changes):
        return research_authority_source(**{**dict(project=self.project, actor=self.owner,
            research_job_id=self.job.pk, source_index=0), **changes})

    def test_real_collected_step_citation_private_readback_no_write_fetch_model_or_link_fact(self):
        counts = [model.objects.count() for model in (JobRun, JobStep, Artifact, SourceCitation)]
        with patch("jobs.research.create_response", side_effect=AssertionError("No new AI call")), patch(
            "jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No new network request")):
            evidence = self.source()
        self.assertEqual(evidence["method"], METHOD)
        self.assertEqual(evidence["excerpt"], self.job.output["sources"][0]["excerpt"])
        self.assertEqual(evidence["original_response_sha256"], self.job.output["sources"][0]["sha256"])
        self.assertEqual(evidence["inbound_unlinked_lost_links"], "not_established")
        self.assertEqual(evidence["link_structure"], "unavailable_href_rel_not_retained")
        self.assertIsNone(evidence["publication_time"])
        self.assertEqual(counts, [model.objects.count() for model in (JobRun, JobStep, Artifact, SourceCitation)])

    def test_foreign_viewer_unverified_and_source_actor_loss_deny_existing_evidence_use(self):
        for actor in (self.other, self.viewer):
            with self.assertRaises(PermissionDenied): self.source(actor=actor)
        for changes in ({"research_job_id": True}, {"source_index": True}, {"source_index": 5}, {"source_index": -1}):
            with self.assertRaises(ValidationError): self.source(**changes)
        with self.assertRaises(PermissionDenied): self.source(research_job_id=self.job.pk + 1000)
        removed = Project(organization=self.org, pk=self.project.pk + 9999, canonical_origin="https://missing.example.invalid")
        with self.assertRaises(PermissionDenied): self.source(project=removed)
        membership = OrganizationMembership.objects.get(organization=self.org, user=self.viewer)
        membership.role = "admin"; membership.save()
        self.source(actor=self.viewer)
        OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role="viewer")
        with self.assertRaises(PermissionDenied): self.source(actor=self.viewer)
        OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role="owner")
        EmailAddress.objects.filter(user=self.owner).update(verified=False)
        with self.assertRaises(PermissionDenied): self.source(actor=self.viewer)

    def test_changed_configuration_blocked_source_and_missing_citation_are_not_current(self):
        SourceCitation.objects.filter(job=self.job).delete()
        with self.assertRaises(ValidationError): self.source()
        source = self.job.output["sources"][0]
        from datetime import datetime
        SourceCitation.objects.create(job=self.job, step=self.job.steps.get(sequence=2), source_title=source["title"],
            source_url=source["url"], observed_at=datetime.fromisoformat(source["retrieved_at"]))
        update_project_configuration(project=self.project, user=self.owner, expected_revision=1,
            changes={"research_allowed_origins": [], "research_blocked_origins": ["https://research-source.example.invalid"]})
        with self.assertRaises(ValidationError): self.source()

    def test_real_private_artifact_tampering_foreign_ownership_and_step_mismatch_fail_closed(self):
        source = self.job.output["sources"][0]
        artifact = Artifact.objects.get(pk=source["artifact_id"])
        content = json.dumps({"state": "invented source"}).encode()
        with project_artifact_barrier(self.project.organization_id, shared=True):
            key = save_project_artifact(project=self.project, content=content, content_type="application/json")
        original = (artifact.key, artifact.size_bytes)
        Artifact.objects.filter(pk=artifact.pk).update(key=key, size_bytes=len(content))
        with self.assertRaises(ValidationError): self.source()
        Artifact.objects.filter(pk=artifact.pk).update(key=original[0], size_bytes=original[1])
        foreign = Project.objects.create(organization=self.org, name="Synthetic foreign authority source", canonical_origin="https://foreign-authority.example.invalid")
        Artifact.objects.filter(pk=artifact.pk).update(project=foreign)
        with self.assertRaises(ValidationError): self.source()
        Artifact.objects.filter(pk=artifact.pk).update(project=self.project)
        JobStep.objects.filter(job=self.job, sequence=2).update(output={"state": "collected", "excerpt": "forged"})
        with self.assertRaises(ValidationError): self.source()

    def test_real_partial_truncated_text_source_never_proves_no_link_or_full_coverage(self):
        # The other source fails; no synthesis is needed for a real collected partial source.
        second = queue_research(project=self.project, actor=self.owner,
            data={**self.data, "source_urls": [self.url, "https://research-source.example.invalid/missing"]}, idempotency_key="authority-partial-1")
        class Fetcher:
            def fetch(inner, url, *, before_request):
                before_request(url)
                return FetchResponse(url=url, status=503 if url.endswith("missing") else 200,
                    headers={"content-type": "text/html"}, body=b"<p>Partnership evidence. </p>" * 200)
        def unavailable_synthesis(**_kwargs):
            raise ValidationError("No synthesis")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-not-real"}):
            self.assertTrue(execute_research(second.pk, fetcher=Fetcher(), request=unavailable_synthesis))
        second.refresh_from_db()
        self.assertEqual(second.status, "partially_succeeded")
        evidence = self.source(research_job_id=second.pk)
        self.assertTrue(evidence["excerpt_truncated"])
        self.assertEqual(evidence["coverage"], "selected_bounded_public_page_text_only")
        with self.assertRaises(ValidationError): self.source(research_job_id=second.pk, source_index=1)


class ProspectFixture:
    queue = research_fixtures.ResearchTests.queue
    fetcher = research_fixtures.ResearchTests.fetcher
    response = research_fixtures.ResearchTests.response
    url = research_fixtures.ResearchTests.url

    def setUp(self):
        research_fixtures.ResearchTests.setUp(self)
        self.job = self.queue()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-not-real"}):
            self.assertTrue(execute_research(self.job.pk, fetcher=self.fetcher(), request=self.response))
        self.intake = {"policy": POLICY, "research_job_id": self.job.pk, "source_index": 0,
            "quote": "Evidence useful.", "relevance": "Human-selected relevant relationship; no measured authority.",
            "proposed_action": "partnership", "target_url": self.url, "draft_text": "Human partnership discussion draft.",
            "use_permission": True, "storage_permission": True, "outreach_permission": True}

    def record(self, **changes):
        return record_authority_prospect(**{**dict(project=self.project, actor=self.owner,
            request_key="authority-draft-1", intake=self.intake, assignee_id=self.owner.pk,
            state="draft", reason="Actual human decision over exact source text."), **changes})

    def transition(self, row, state, **changes):
        return self.record(**{**dict(prospect_id=row.prospect_id, expected_revision=row.revision,
            intake=row.intake, assignee_id=row.assignee_id, state=state,
            request_key=f"authority-{state}-{row.revision}"), **changes})


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "application/zip"}), DEBUG=True)
class AuthorityProspectTests(ProspectFixture, TransactionTestCase):
    def test_exact_quote_human_approval_manual_report_dismiss_reopen_without_remote_effect(self):
        counts = [model.objects.count() for model in (JobRun, JobStep, Artifact, SourceCitation)]
        with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No network")), patch(
            "jobs.research.create_response", side_effect=AssertionError("No AI")):
            draft = self.record()
            self.assertEqual(self.record().pk, draft.pk)
            with self.assertRaises(ValidationError): self.transition(draft, "approved")
            review = self.transition(draft, "review")
            approved = self.transition(review, "approved")
            self.assertEqual((approved.reviewed_revision_id, approved.approved_by_id), (review.pk, self.owner.pk))
            self.assertIsNone(approved.executed_at)
            with self.assertRaises(ValidationError):
                self.transition(approved, "reported", executed_at=approved.approved_at - timedelta(seconds=1), execution_note="Too early")
            reported = self.transition(approved, "reported", executed_at=timezone.now(), execution_note="Human reports exact manual discussion.")
            reopened = self.transition(reported, "draft", intake={**reported.intake, "draft_text": "Changed human draft"})
            self.assertIsNone(reopened.approved_by_id)
            self.assertIsNone(reopened.executed_at)
            dismissed = self.transition(reopened, "dismissed")
            self.assertIsNone(dismissed.reviewed_revision_id)
            self.assertEqual(self.transition(dismissed, "draft").state, "draft")
        self.assertEqual(counts, [model.objects.count() for model in (JobRun, JobStep, Artifact, SourceCitation)])
        with self.assertRaises(ValidationError): draft.save()
        with self.assertRaises(ValidationError): self.transition(review, "approved", request_key="authority-old-key")

    def test_exact_scalar_types_quote_rights_target_scope_and_database_approval_guards(self):
        for key, value in (("research_job_id", True), ("source_index", True), ("proposed_action", []),
            ("quote", "Invented link proof"), ("target_url", "https://outside.example.invalid/send"),
            ("storage_permission", False), ("use_permission", 1), ("draft_text", "\ud800"),
            ("relevance", "x" * 501), ("contact_email", "someone@example.invalid")):
            with self.subTest(field=key), self.assertRaises(ValidationError):
                self.record(intake={**self.intake, key: value})
        draft = self.record(intake={**self.intake, "outreach_permission": False, "draft_text": ""})
        with self.assertRaises(ValidationError): self.transition(draft, "review")
        with self.assertRaises(IntegrityError), transaction.atomic():
            AuthorityProspectReview.objects.filter(pk=draft.pk).update(state="approved")
        with self.assertRaises(ValidationError): self.record(state="reported", executed_at=timezone.now(), execution_note="No approval")

    def test_changed_judgment_assignee_source_and_actor_cannot_ride_exact_approval(self):
        OrganizationMembership.objects.filter(organization=self.org, user=self.viewer).update(role="admin")
        review = self.transition(self.record(), "review")
        for key, value in (("quote", "Evidence"), ("relevance", "New relevance"), ("draft_text", "Unreviewed text"),
                           ("proposed_action", "digital_pr")):
            with self.subTest(field=key), self.assertRaises(ValidationError):
                self.transition(review, "approved", intake={**review.intake, key: value})
        with self.assertRaises(ValidationError): self.transition(review, "approved", assignee_id=self.viewer.pk)
        approved = self.transition(review, "approved", actor=self.viewer)
        OrganizationMembership.objects.filter(organization=self.org, user=self.viewer).update(role="viewer")
        self.assertFalse(prospect_source_current(approved))
        with self.assertRaises(PermissionDenied): self.transition(approved, "reported", executed_at=timezone.now(), execution_note="Actor lost")
        with self.assertRaises(PermissionDenied): self.record(actor=self.other, request_key="authority-foreign")
        with self.assertRaises(PermissionDenied): self.record(assignee_id=self.other.pk)
        with self.assertRaises(PermissionDenied): self.record(actor=self.viewer, request_key="authority-viewer")
        with self.assertRaises(PermissionDenied): self.record(prospect_id="00000000-0000-0000-0000-000000000000", expected_revision=1)
        SourceCitation.objects.filter(job=self.job).delete()
        self.assertFalse(prospect_source_current(review))
        with self.assertRaises(ValidationError): self.transition(review, "approved", request_key="authority-missing-source")

    def test_assignee_revocation_and_foreign_job_fail_and_expiry_retains_but_cutoff_denies(self):
        membership = OrganizationMembership.objects.filter(organization=self.org, user=self.viewer)
        membership.update(role="member")
        row = self.record(assignee_id=self.viewer.pk)
        membership.update(role="viewer")
        self.assertFalse(prospect_source_current(row))
        with self.assertRaises(PermissionDenied): self.transition(row, "review")
        foreign = Project.objects.create(organization=self.org, name="Foreign synthetic prospect", canonical_origin="https://foreign-prospect.example.invalid")
        with self.assertRaises(PermissionDenied): self.record(project=foreign)
        now = timezone.now()
        OrganizationTrial.objects.filter(organization=self.org).update(started_at=now - timedelta(days=60), ends_at=now - timedelta(days=30))
        current = self.record(request_key="authority-retained-draft")
        self.assertTrue(prospect_source_current(current))
        OrganizationTrial.objects.filter(organization=self.org).update(started_at=now - timedelta(days=121), ends_at=now - timedelta(days=91))
        with self.assertRaises(PermissionDenied): self.transition(current, "review")

    def test_actual_bounded_stored_sequential_private_exports_and_closed_deletion(self):
        from tenancy.customer_export import complete_bounded_customer_archive
        from tenancy.customer_inventory import CUSTOMER
        from tenancy.customer_snapshot import reserve_bounded_customer_snapshot, capture_reserved_customer_snapshot, private_snapshot_part
        from tenancy.customer_source_parts import capture_source_stage
        from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        approved = self.transition(self.transition(self.record(), "review"), "approved")
        with ZipFile(BytesIO(complete_bounded_customer_archive(organization=self.org, actor=self.owner))) as archive:
            row = json.loads(archive.read("records/jobs/AuthorityProspectReview.json"))[-1]
            self.assertTrue(row["source_current_at_capture"])
            self.assertEqual(row["intake"], approved.intake)
            self.assertNotIn("request_key", row)
            self.assertEqual(row["scope"], "historical_human_prospect_not_link_proof_or_current_use_permission")
        with patch("tenancy.tasks.capture_customer_snapshot_task.apply_async"):
            bounded = reserve_bounded_customer_snapshot(organization=self.org, actor=self.owner, request_key="a" * 32)
            self.assertTrue(capture_reserved_customer_snapshot(bounded.pk))
            data, _ = private_snapshot_part(organization=self.org, actor=self.owner, snapshot_id=bounded.pk, position=0)
            with ZipFile(BytesIO(data)) as archive:
                self.assertEqual(json.loads(archive.read("records/jobs/AuthorityProspectReview.json"))[-1]["intake"], approved.intake)
            SourceCitation.objects.filter(job=self.job).delete()
            self.assertFalse(prospect_source_current(approved))
            self.assertEqual(private_snapshot_part(organization=self.org, actor=self.owner, snapshot_id=bounded.pk, position=0)[0], data)
            sequential = reserve_bounded_customer_snapshot(organization=self.org, actor=self.owner, request_key="b" * 32, format="source-parts-v2")
            for _ in range(len(CUSTOMER) * 2 + 10):
                sequential.refresh_from_db()
                if sequential.state != sequential.State.PREPARING: break
                self.assertTrue(capture_source_stage(sequential.pk, sequential.progress.get("step", 0)))
            sequential.refresh_from_db()
            self.assertEqual(sequential.state, sequential.State.READY)
            part = sequential.parts.filter(source__model="jobs.AuthorityProspectReview").first()
            data, _ = private_snapshot_part(organization=self.org, actor=self.owner, snapshot_id=sequential.pk, position=part.position)
            with ZipFile(BytesIO(data)) as archive:
                self.assertFalse(json.loads(archive.read("data"))[-1]["source_current_at_capture"])
        with self.assertRaises(PermissionDenied):
            private_snapshot_part(organization=self.org, actor=self.other, snapshot_id=bounded.pk, position=0)
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
        with self.assertRaises(PermissionDenied): self.record(request_key="authority-closed")
        with self.assertRaises(PermissionDenied):
            private_snapshot_part(organization=self.org, actor=self.owner, snapshot_id=bounded.pk, position=0)
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.org))
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(AuthorityProspectReview.objects.exists())


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}), DEBUG=True)
class AuthorityProspectConcurrencyTests(ProspectFixture, TransactionTestCase):
    def test_two_postgresql_connections_cannot_overwrite_exact_review(self):
        draft = self.record()
        barrier = Barrier(2)
        def write(key):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    return self.transition(draft, "review", request_key=key).revision
                except ValidationError:
                    return "conflict"
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write, ["authority-concurrent-1", "authority-concurrent-2"]))
        self.assertCountEqual(results, [2, "conflict"])
        self.assertEqual(AuthorityProspectReview.objects.filter(prospect_id=draft.prospect_id).count(), 2)


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}), DEBUG=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "authority-api"}})
class AuthorityProspectApiTests(ProspectFixture, TransactionTestCase):
    def test_authenticated_csrf_exact_decision_reconciliation_current_candidates_and_history(self):
        url = f"/api/organizations/{self.org.pk}/projects/{self.project.pk}/authority-prospects/"
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.get(url).status_code, 401)
        client.force_login(self.owner)
        payload = {"request_key": "authority-api-draft", "intake": self.intake, "assignee_id": self.owner.pk,
                   "state": "draft", "reason": "Exact human decision", "executed_at": None, "execution_note": ""}
        self.assertEqual(client.post(url, json.dumps(payload), content_type="application/json").status_code, 403)
        client.get("/_allauth/browser/v1/auth/session")
        headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value}
        def post(path, data):
            return client.post(path, json.dumps(data), content_type="application/json", **headers)
        response = post(url, payload)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        row = response.json()["review"]
        self.assertEqual(row["intake"], self.intake)
        self.assertEqual(post(url, payload).json()["review"]["id"], row["id"])
        info = client.get(url).json()
        self.assertEqual(info["sources"][0]["research_job_id"], self.job.pk)
        self.assertEqual(info["assignees"], [{"id": self.owner.pk}])
        self.assertEqual(info["link_recovery"], "unavailable_requires_supported_link_evidence")
        self.assertEqual(client.get(url + "?request_key=authority-api-draft").json()["lookup"], "found")
        history = url + row["prospect_id"] + "/"
        response = post(history, {**payload, "expected_revision": 1, "state": "review", "request_key": "authority-api-review"})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(client.get(history).json()["reviews"]), 2)
        self.assertFalse(client.get(url + "?request_key=authority-api-draft").json()["reviews"][0]["is_latest"])
        SourceCitation.objects.filter(job=self.job).delete()
        info = client.get(url).json()
        self.assertFalse(info["reviews"][0]["source_current"])
        self.assertEqual(info["sources"], [])
        self.assertEqual(post(history, {**payload, "expected_revision": 2, "state": "approved", "request_key": "authority-stale-source"}).status_code, 409)

    def test_foreign_viewer_strict_duplicate_nonfinite_and_oversized_commands_fail_closed(self):
        url = f"/api/organizations/{self.org.pk}/projects/{self.project.pk}/authority-prospects/"
        self.client.force_login(self.owner)
        for body in ('{"state":"draft","state":"approved"}', '{"value":NaN}', '[]', '{}', 'x' * (28 * 1024 + 1)):
            self.assertEqual(self.client.post(url, body, content_type="application/json").status_code, 409)
        self.assertEqual(self.client.get(url + "?request_key=authority-none&request_key=authority-other").status_code, 400)
        self.assertEqual(self.client.get(url + "00000000-0000-0000-0000-000000000000/").status_code, 404)
        self.client.force_login(self.viewer)
        self.assertFalse(self.client.get(url).json()["can_review"])
        self.assertEqual(self.client.get(url).json()["sources"], [])
        self.assertEqual(self.client.post(url, '{}', content_type="application/json").status_code, 403)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(AuthorityProspectReview.objects.count(), 0)
