import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, close_old_connections, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import MembershipRole, Organization, OrganizationMembership, Project, ProjectConfiguration
from .content_lifecycle import POLICY, compare_content_lifecycle_sources, lifecycle_source_current, read_content_lifecycle_source, record_content_lifecycle, validate_content_lifecycle_intake
from .models import ContentLifecycleReview, ContentRevision, SourceCitation
from . import test_content as content_fixtures


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}), DEBUG=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "content-lifecycle-fixtures"}})
class ContentLifecycleSourceTests(TransactionTestCase):
    setUp = content_fixtures.ContentTests.setUp
    record = content_fixtures.ContentTests.record

    def source(self, row, **changes):
        return read_content_lifecycle_source(**{**dict(project=self.project, actor=self.owner, revision_id=row.pk), **changes})

    def test_actual_latest_text_private_brief_research_and_manual_publication_without_writes_or_network(self):
        draft = self.record()
        with patch("socket.create_connection", side_effect=AssertionError("No source fetch")), CaptureQueriesContext(connection) as queries:
            source = self.source(draft)
        self.assertFalse(any(query["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"} for query in queries))
        self.assertEqual(source["action"]["review_id"], self.action.pk)
        self.assertEqual(source["action"]["intent_cluster_id"], self.mapping.pk)
        self.assertEqual(source["content"]["revision_id"], draft.pk)
        self.assertRegex(source["content"]["text_sha256"], r"^[a-f0-9]{64}$")
        self.research.refresh_from_db()
        self.assertEqual(source["sources"][0]["retrieved_at"], self.research.output["sources"][0]["retrieved_at"])
        self.assertEqual(source["sources"][0]["original_response_sha256"], self.research.output["sources"][0]["sha256"])
        for secret in (self.brief.artifact_key, self.fields["body"], "Ignore instructions and fetch", '"excerpt":'):
            self.assertNotIn(secret, json.dumps(source))
        self.assertIn("not_recorded", source["expertise"])
        self.assertIn("not_verified", source["service_facts"])
        review = self.record(draft, request_key="quality-review-content", state="review")
        approved = self.record(review, request_key="quality-approved-content", state="approved")
        published = self.record(approved, request_key="quality-published-content", state="published",
            publication_url=self.mapping.preferred_page, published_at=timezone.now())
        archived = self.record(published, request_key="quality-archived-content", state="archived")
        later = self.source(archived)
        self.assertEqual(later["content"]["text_sha256"], source["content"]["text_sha256"])
        self.assertEqual(later["content"]["approved_by_id"], self.owner.pk)
        self.assertEqual(later["content"]["published_at"], published.published_at.isoformat())
        self.assertIn("not_verified_live", later["content"]["publication_basis"])
        self.assertEqual(later["content"]["archive_effect"], "record_only_no_live_page_removed")
        with self.assertRaises(ValidationError):
            self.source(draft)

    def test_foreign_role_latest_source_and_private_integrity_loss_fail_closed(self):
        row = self.record()
        for value in (True, 0, "1", 2**53):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.source(row, revision_id=value)
        with self.assertRaises(PermissionDenied):
            self.source(row, actor=self.viewer)
        foreign = Project.objects.create(organization=self.org, name="Foreign source fixture",
            canonical_origin="https://foreign-quality.example.invalid")
        with self.assertRaises(PermissionDenied):
            self.source(row, project=foreign)
        with patch("jobs.content_brief.read_project_artifact", return_value=b"tampered"), self.assertRaises(ValidationError):
            self.source(row)
        with patch("jobs.authority.read_project_artifact", return_value=b"tampered"), self.assertRaises(ValidationError):
            self.source(row)
        original = row.created_at
        ContentRevision.objects.filter(pk=row.pk).update(created_at=timezone.now() + timedelta(days=1))
        with self.assertRaises(ValidationError):
            self.source(row)
        ContentRevision.objects.filter(pk=row.pk).update(created_at=original)
        config = ProjectConfiguration.objects.get(project=self.project)
        config.seed_topics = []; config.save(update_fields=["seed_topics"])
        with self.assertRaises(ValidationError):
            self.source(row)

    def test_private_read_cannot_outlive_current_actor_configuration_or_latest_selection(self):
        from tenancy.artifacts import read_project_artifact
        row = self.record()
        membership = OrganizationMembership.objects.get(organization=self.org, user=self.owner)

        def revoke(**kwargs):
            content = read_project_artifact(**kwargs)
            OrganizationMembership.objects.filter(pk=membership.pk).update(role=MembershipRole.VIEWER)
            return content

        with patch("jobs.authority.read_project_artifact", side_effect=revoke), self.assertRaises(PermissionDenied):
            self.source(row)
        OrganizationMembership.objects.filter(pk=membership.pk).update(role=MembershipRole.OWNER)

        def edit(**kwargs):
            content = read_project_artifact(**kwargs)
            self.record(row, request_key="quality-late-text-edit", body="Edited during private readback")
            return content

        with patch("jobs.authority.read_project_artifact", side_effect=edit), self.assertRaises(ValidationError):
            self.source(row)
        latest = ContentRevision.objects.get(item_id=row.item_id, revision=2)

        def configure(**kwargs):
            content = read_project_artifact(**kwargs)
            ProjectConfiguration.objects.filter(project=self.project).update(revision=100)
            return content

        with patch("jobs.authority.read_project_artifact", side_effect=configure), self.assertRaises(ValidationError):
            self.source(latest)

    def test_current_mapping_action_and_origin_are_rechecked_after_private_reads(self):
        from tenancy.artifacts import read_project_artifact
        from .action_review import record_action
        row = self.record()

        def change_origin(**kwargs):
            content = read_project_artifact(**kwargs)
            Project.objects.filter(pk=self.project.pk).update(canonical_origin="https://changed-quality.example.invalid")
            return content

        with patch("jobs.authority.read_project_artifact", side_effect=change_origin), self.assertRaises(ValidationError):
            self.source(row)
        Project.objects.filter(pk=self.project.pk).update(canonical_origin=self.project.canonical_origin)

        def change_action(**kwargs):
            content = read_project_artifact(**kwargs)
            record_action(project=self.project, actor=self.owner, request_key="quality-action-superseded",
                source_id=self.mapping.pk, state="in_progress", assignee_id=self.owner.pk,
                acceptance_criteria=self.action.acceptance_criteria, reason="Actual later action transition.",
                action_id=self.action.action_id, expected_revision=self.action.revision)
            return content

        with patch("jobs.authority.read_project_artifact", side_effect=change_action), self.assertRaises(ValidationError):
            self.source(row)


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}), DEBUG=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "content-quality-intake-fixtures"}})
class ContentLifecycleIntakeTests(TransactionTestCase):
    record = content_fixtures.ContentTests.record

    def setUp(self):
        content_fixtures.ContentTests.setUp(self)
        self.row = self.record()
        self.evidence = read_content_lifecycle_source(project=self.project, actor=self.owner, revision_id=self.row.pk)
        self.intake = {"policy": POLICY, "content_revision_id": self.row.pk,
            "text_sha256": self.evidence["content"]["text_sha256"], "reviewed_at": timezone.now().isoformat(),
            "judgment": "thin_coverage", "substantive_basis": "business_expertise_review",
            "quote": "Actual details require human verification.",
            "evidence_note": "Human review: saved text omits first-hand service limitations and customer questions.",
            "expertise_note": "Business reviewer reports missing first-hand operating details; this is a human declaration.",
            "service_fact_note": "", "facts_checked_at": "", "proposed_action": "refresh",
            "rationale": "Ask the business reviewer to supply useful original details before drafting.",
            "destination_url": "", "destination_review": "", "user_impact": "Retain useful history and answer actual reader questions.",
            "use_permission": True, "storage_permission": True, "not_restricted_copy": True, "no_personal_payload": True}

    def validate(self, **changes):
        return validate_content_lifecycle_intake({**self.intake, **changes}, project=self.project, revision=self.row, evidence=self.evidence)

    def test_actual_exact_quote_substantive_manual_proposal_and_separate_replacement_without_writes(self):
        with patch("socket.create_connection", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            result = self.validate()
            replacement = self.validate(proposed_action="consolidate", destination_url=self.project.canonical_origin + "/replacement",
                destination_review="Human reviewed destination usefulness and preservation of source-page reader needs.")
            unchecked = self.validate(judgment="not_checked", substantive_basis="unreviewed", quote="", evidence_note="",
                proposed_action="unselected", rationale="", user_impact="")
        self.assertFalse(any(query["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"} for query in queries))
        self.assertEqual(result, self.intake)
        self.assertIsNot(result, self.intake)
        self.assertEqual(replacement["proposed_action"], "consolidate")
        self.assertEqual(unchecked["judgment"], "not_checked")
        self.assertNotIn("approval", result)
        self.assertEqual(self.validate(judgment="service_detail_changed", service_fact_note="Original business reviewer reports an obsolete service detail.",
            facts_checked_at=self.row.created_at.isoformat())["judgment"], "service_detail_changed")

    def test_exact_fields_rights_dates_quotes_scope_and_substantive_destructive_guards(self):
        invalid = [{"content_revision_id": True}, {"content_revision_id": 2**53}, {"text_sha256": "0" * 64},
            {"policy": "unknown"}, {"use_permission": False}, {"storage_permission": 1}, {"not_restricted_copy": False},
            {"no_personal_payload": False}, {"quote": "Not in the actual saved draft"}, {"evidence_note": ""},
            {"expertise_note": ""}, {"substantive_basis": "word_count"}, {"traffic": 0}, {"word_count": 2},
            {"judgment": "verified_thin_live_page"}, {"judgment": "service_detail_changed"},
            {"reviewed_at": "2026-10-02T10:00:00"}, {"reviewed_at": (self.row.created_at - timedelta(seconds=1)).isoformat()},
            {"reviewed_at": (timezone.now() + timedelta(days=1)).isoformat()}, {"service_fact_note": "A fact without its review date"},
            {"facts_checked_at": self.row.created_at.isoformat()}, {"service_fact_note": "A fact", "facts_checked_at": "not-a-date"},
            {"service_fact_note": "A fact", "facts_checked_at": (timezone.now() + timedelta(days=1)).isoformat()},
            {"proposed_action": "delete"}, {"proposed_action": "unselected"}, {"proposed_action": "redirect"},
            {"rationale": ""}, {"user_impact": ""}, {"destination_url": self.project.canonical_origin + "/other"},
            {"quote": "\ud800"}, {"evidence_note": "\u0000"},
            {"expertise_note": "😀" * 1000, "evidence_note": "😀" * 1000, "service_fact_note": "😀" * 1000,
             "facts_checked_at": self.row.created_at.isoformat(), "rationale": "😀" * 500, "user_impact": "😀" * 500,
             "destination_review": "😀" * 500}]
        for changes in invalid:
            with self.subTest(fields=list(changes)), self.assertRaises(ValidationError):
                self.validate(**changes)
        for destination in (self.mapping.preferred_page, "https://foreign-quality.example.invalid/replacement",
            self.project.canonical_origin + "/replacement?secret=value", "javascript:evil()"):
            with self.subTest(destination=destination), self.assertRaises(ValidationError):
                self.validate(proposed_action="retire", destination_url=destination, destination_review="A proposed replacement review.")


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}), DEBUG=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "content-comparison-fixtures"}})
class ContentLifecycleComparisonTests(TransactionTestCase):
    record = content_fixtures.ContentTests.record

    def setUp(self):
        import os
        from providers.adapters import ProviderResponse
        from tenancy.services import create_organization, create_project, update_project_configuration
        from .action_review import record_action
        from .content import record_content
        from .content_brief import create_content_brief
        from .models import IntentClusterReview
        from .research import execute_research, queue_research
        content_fixtures.ContentTests.setUp(self)
        self.left = self.record()
        self.second_org = create_organization(user=self.other, name="Independent comparison fixture")
        OrganizationMembership.objects.create(organization=self.second_org, user=self.owner, role=MembershipRole.ADMIN)
        self.second = create_project(organization=self.second_org, user=self.other, name="Independent comparison project",
            canonical_origin="https://comparison-project.example.invalid")
        update_project_configuration(project=self.second, user=self.other, expected_revision=0,
            changes={"target_country": "Türkiye", "target_languages": ["en"], "seed_topics": ["human-selected source topic"],
                "research_allowed_origins": ["https://research-source.example.invalid"]})
        mapping = IntentClusterReview.objects.create(project=self.second, actor=self.owner, request_key="compare-mapping-1",
            label="human-selected source topic", manual_topics=["human-selected source topic"], market="Türkiye", language="en",
            intent="informational", page_kind="existing_unverified", preferred_page=self.second.canonical_origin + "/service",
            reason="Independent human selection.", proposed_action="refresh", action_reason="Review genuine usefulness.")
        proposed = record_action(project=self.second, actor=self.owner, request_key="compare-action-1", source_id=mapping.pk,
            state="proposed", assignee_id=self.owner.pk, acceptance_criteria="Review original service evidence.", reason="Independent proposal.")
        action = record_action(project=self.second, actor=self.owner, request_key="compare-action-2", source_id=mapping.pk,
            state="accepted", assignee_id=self.owner.pk, acceptance_criteria=proposed.acceptance_criteria,
            reason="Human page-action acceptance.", action_id=proposed.action_id, expected_revision=1)
        with patch("jobs.services.dispatch_pending"):
            research = queue_research(project=self.second, actor=self.owner, data={**self.data, "mapping_id": mapping.pk},
                idempotency_key="compare-research-1")
        output = {"summary": "Independent interpretation for review.", "claims": [
            {"text": "Review actual source usefulness.", "source_index": 0, "quote": "Evidence useful."}]}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-not-real"}):
            self.assertTrue(execute_research(research.pk, fetcher=self.fixture.fetcher(self), request=lambda **_: ProviderResponse(
                json.dumps(output), output, (), "req_fixture_compare", "resp_fixture_compare", 30, 20)))
        brief = create_content_brief(project=self.second, actor=self.owner, request_key="compare-brief-1", research_job_id=research.pk,
            action_id=action.action_id, title_options=["Independent service question"], angle="Independent business evidence review.",
            outline=["Actual service detail", "Reader questions"], questions=["What needs human verification?"])
        self.right = record_content(project=self.second, actor=self.owner, request_key="compare-content-1", brief_id=brief.pk,
            kind="service", title="Independent native title", body=self.left.body, meta_description="Unverified other service description",
            state="draft", reason="Separately authored fixture text; no automatic copy operation.")
        self.api_path = f"/api/organizations/{self.org.pk}/projects/{self.project.pk}/content-lifecycle/comparison/"
        self.params = {"content_revision_id": self.left.pk, "other_organization_id": self.second_org.pk,
            "other_project_id": self.second.pk, "other_content_revision_id": self.right.pk}

    def compare(self, **changes):
        return compare_content_lifecycle_sources(**{**dict(project=self.project, other_project=self.second, actor=self.owner,
            revision_id=self.left.pk, other_revision_id=self.right.pk), **changes})

    def test_actual_two_project_text_and_private_sources_without_writes_network_or_duplication_claim(self):
        with patch("socket.create_connection", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            result = self.compare()
        self.assertFalse(any(query["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"} for query in queries))
        self.assertEqual(result["left"]["organization_id"], self.org.pk)
        self.assertEqual(result["right"]["organization_id"], self.second_org.pk)
        self.assertEqual(result["left"]["text"]["body"], self.left.body)
        self.assertEqual(result["right"]["text"]["body"], self.right.body)
        self.assertTrue(result["same_native_body"])
        self.assertNotEqual(result["left"]["source"]["content"]["text_sha256"], result["right"]["source"]["content"]["text_sha256"])
        self.assertIn("not_live_duplicate", result["interpretation"])
        self.assertEqual(ContentRevision.objects.count(), 2)
        self.assertEqual(ContentLifecycleReview.objects.count(), 0)
        for secret in (self.brief.artifact_key, '"excerpt":', '"storage_key":'):
            self.assertNotIn(secret, json.dumps(result))
        with self.assertRaises(PermissionDenied):
            self.compare(actor=self.viewer)
        with self.assertRaises(PermissionDenied):
            self.compare(actor=self.other)
        with self.assertRaises(PermissionDenied):
            self.compare(other_revision_id=self.left.pk + 10000)
        with self.assertRaises(ValidationError):
            self.compare(other_revision_id=self.left.pk)
        with patch("jobs.authority.read_project_artifact", return_value=b"tampered"), self.assertRaises(ValidationError):
            self.compare()

    def test_later_other_private_read_cannot_outlive_first_project_role_or_latest_content(self):
        from tenancy.artifacts import read_project_artifact
        membership = OrganizationMembership.objects.get(organization=self.org, user=self.owner)

        def revoke(**kwargs):
            body = read_project_artifact(**kwargs)
            if kwargs["project"].pk == self.second.pk:
                OrganizationMembership.objects.filter(pk=membership.pk).update(role=MembershipRole.VIEWER)
            return body

        with patch("jobs.authority.read_project_artifact", side_effect=revoke), self.assertRaises(PermissionDenied):
            self.compare()
        OrganizationMembership.objects.filter(pk=membership.pk).update(role=MembershipRole.OWNER)

        def lose_citation(**kwargs):
            body = read_project_artifact(**kwargs)
            if kwargs["project"].pk == self.second.pk:
                SourceCitation.objects.filter(job=self.research).delete()
            return body

        with transaction.atomic():
            with patch("jobs.authority.read_project_artifact", side_effect=lose_citation), self.assertRaises(ValidationError):
                self.compare()
            transaction.set_rollback(True)

        def edit(**kwargs):
            body = read_project_artifact(**kwargs)
            if kwargs["project"].pk == self.second.pk:
                self.record(self.left, request_key="compare-late-first-content", body="A later first-project correction.")
            return body

        with patch("jobs.authority.read_project_artifact", side_effect=edit), self.assertRaises(ValidationError):
            self.compare()

    def test_private_get_exact_fields_each_project_authority_and_no_write_contract(self):
        client = Client(); client.force_login(self.owner)
        with patch("socket.create_connection", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            response = client.get(self.api_path, self.params)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertFalse(any(query["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"} for query in queries))
        self.assertEqual(response.json()["comparison"]["right"]["project_id"], self.second.pk)
        for bad in ({}, {**self.params, "extra": 1}, {**self.params, "other_project_id": True},
            {**self.params, "other_project_id": 2**53}, {**self.params, "content_revision_id": "01"},
            {**self.params, "content_revision_id": [self.left.pk, self.left.pk]}):
            self.assertEqual(client.get(self.api_path, bad).status_code, 400)
        self.assertEqual(client.post(self.api_path, self.params).status_code, 405)
        denied = client.get(self.api_path, {**self.params, "other_organization_id": self.org.pk})
        self.assertEqual(denied.status_code, 404)
        OrganizationMembership.objects.filter(organization=self.second_org, user=self.owner).update(role=MembershipRole.VIEWER)
        self.assertEqual(client.get(self.api_path, self.params).status_code, 403)
        self.assertEqual(ContentLifecycleReview.objects.count(), 0)


class LifecycleReviewFixture:
    setUp = ContentLifecycleIntakeTests.setUp
    record = content_fixtures.ContentTests.record

    def decision(self, previous=None, **changes):
        values = dict(project=self.project, actor=self.owner, request_key="quality-" + uuid4().hex,
            intake=self.intake, assignee_id=self.owner.pk, state="draft", reason="Actual human content judgment and proposal.")
        if previous:
            values.update(review_id=previous.review_id, expected_revision=previous.revision)
        return record_content_lifecycle(**{**values, **changes})


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "application/zip"}),
    ARTIFACT_MAX_BYTES=32 * 1024 * 1024, DEBUG=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "quality-review-fixtures"}})
class ContentLifecycleReviewTests(LifecycleReviewFixture, TransactionTestCase):
    def test_exact_approval_manual_handoff_corrections_dismissal_idempotency_and_no_site_change(self):
        key = "quality-idempotent-draft"
        draft = self.decision(request_key=key)
        self.assertEqual(self.decision(request_key=key).pk, draft.pk)
        with self.assertRaises(ValidationError):
            self.decision(draft, state="approved")
        review = self.decision(draft, state="review")
        with self.assertRaises(ValidationError):
            self.decision(review, state="approved", intake={**self.intake, "evidence_note": "Changed after review"})
        approved = self.decision(review, state="approved")
        self.assertEqual(approved.reviewed_revision_id, review.pk)
        with self.assertRaises(ValidationError):
            self.decision(review, state="approved")
        reported = self.decision(approved, state="reported", executed_at=timezone.now(),
            execution_note="Human handed the proposal to the separately approved page-action workflow; no site execution claimed.")
        self.assertEqual(reported.approved_at, approved.approved_at)
        changed = self.decision(reported, intake={**self.intake, "evidence_note": "A fresh human correction."})
        self.assertIsNone(changed.approved_at)
        self.assertIsNone(changed.executed_at)
        dismissed = self.decision(changed, state="dismissed", intake=changed.intake)
        reopened = self.decision(dismissed, intake=changed.intake)
        self.assertEqual(reopened.state, "draft")
        self.action.refresh_from_db(); self.row.refresh_from_db()
        self.assertEqual(self.action.state, "accepted")
        self.assertEqual(self.row.state, "draft")
        with self.assertRaises(ValidationError):
            approved.save()

    def test_direct_model_foreign_state_stale_approval_current_roles_and_source_loss(self):
        draft = self.decision()
        direct = {field.attname: getattr(draft, field.attname) for field in draft._meta.concrete_fields
                  if field.attname not in {"id", "created_at"}}
        direct.update(request_key="quality-direct-bypass", state="review", revision=3)
        with self.assertRaises(ValidationError):
            ContentLifecycleReview.objects.create(**direct)
        with self.assertRaises(PermissionDenied):
            self.decision(draft, actor=self.viewer, state="review")
        with self.assertRaises(PermissionDenied):
            self.decision(draft, assignee_id=self.viewer.pk, state="review")
        foreign = Project.objects.create(organization=self.org, name="Foreign quality review",
            canonical_origin="https://foreign-review.example.invalid")
        with self.assertRaises((PermissionDenied, ValidationError)):
            self.decision(project=foreign)
        review = self.decision(draft, state="review")
        approved = self.decision(review, state="approved")
        direct.update(state="approved", revision=4, reviewed_revision_id=review.pk,
            approved_by_id=self.owner.pk, approved_at=approved.approved_at)
        with self.assertRaises(ValidationError):
            ContentLifecycleReview.objects.create(**direct)
        SourceCitation.objects.filter(job=self.research).delete()
        self.assertFalse(lifecycle_source_current(approved))
        with self.assertRaises(ValidationError):
            self.decision(approved, state="reported", executed_at=timezone.now(), execution_note="Must not authorize stale handoff")

    def test_actual_bounded_stored_sequential_export_source_loss_closure_and_child_first_deletion(self):
        from tenancy.customer_export import complete_bounded_customer_archive
        from tenancy.customer_inventory import CUSTOMER
        from tenancy.customer_snapshot import reserve_bounded_customer_snapshot, capture_reserved_customer_snapshot, private_snapshot_part
        from tenancy.customer_source_parts import capture_source_stage
        from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        approved = self.decision(self.decision(self.decision(), state="review"), state="approved")
        label = "records/jobs/ContentLifecycleReview.json"
        with ZipFile(BytesIO(complete_bounded_customer_archive(organization=self.org, actor=self.owner))) as archive:
            row = json.loads(archive.read(label))[-1]
            self.assertTrue(row["source_current_at_capture"])
            self.assertEqual(row["intake"], approved.intake)
            self.assertNotIn("request_key", row)
            self.assertIn("not_live_quality", row["scope"])
        with patch("tenancy.tasks.capture_customer_snapshot_task.apply_async"):
            bounded = reserve_bounded_customer_snapshot(organization=self.org, actor=self.owner, request_key="c" * 32)
            self.assertTrue(capture_reserved_customer_snapshot(bounded.pk))
            data, _ = private_snapshot_part(organization=self.org, actor=self.owner, snapshot_id=bounded.pk, position=0)
            with ZipFile(BytesIO(data)) as archive:
                self.assertEqual(json.loads(archive.read(label))[-1]["intake"], approved.intake)
            SourceCitation.objects.filter(job=self.research).delete()
            self.assertFalse(lifecycle_source_current(approved))
            self.assertEqual(private_snapshot_part(organization=self.org, actor=self.owner, snapshot_id=bounded.pk, position=0)[0], data)
            sequential = reserve_bounded_customer_snapshot(organization=self.org, actor=self.owner, request_key="d" * 32, format="source-parts-v2")
            for _ in range(len(CUSTOMER) * 2 + 10):
                sequential.refresh_from_db()
                if sequential.state != sequential.State.PREPARING:
                    break
                self.assertTrue(capture_source_stage(sequential.pk, sequential.progress.get("step", 0)))
            sequential.refresh_from_db(); self.assertEqual(sequential.state, sequential.State.READY)
            part = sequential.parts.get(source__model="jobs.ContentLifecycleReview")
            data, _ = private_snapshot_part(organization=self.org, actor=self.owner, snapshot_id=sequential.pk, position=part.position)
            with ZipFile(BytesIO(data)) as archive:
                self.assertFalse(json.loads(archive.read("data"))[-1]["source_current_at_capture"])
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
        with self.assertRaises(PermissionDenied):
            self.decision()
        with self.assertRaises(PermissionDenied):
            private_snapshot_part(organization=self.org, actor=self.owner, snapshot_id=bounded.pk, position=0)
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.org))
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(ContentLifecycleReview.objects.exists())
        self.assertFalse(ContentRevision.objects.filter(project=self.project).exists())


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}), DEBUG=True)
class ContentLifecycleConcurrencyTests(LifecycleReviewFixture, TransactionTestCase):
    def test_two_postgresql_connections_cannot_overwrite_exact_review_revision(self):
        draft = self.decision()
        barrier = Barrier(2)

        def write(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    return self.decision(draft, state="review", request_key=f"quality-race-{index}").revision
                except ValidationError:
                    return "conflict"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(write, (1, 2))), [2, "conflict"])
        self.assertEqual(ContentLifecycleReview.objects.filter(review_id=draft.review_id).count(), 2)


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}), DEBUG=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "quality-api-fixtures"}})
class ContentLifecycleAPITests(LifecycleReviewFixture, TransactionTestCase):
    def api_path(self):
        return f"/api/organizations/{self.org.pk}/projects/{self.project.pk}/content-lifecycle/"

    def payload(self, **changes):
        return {**dict(request_key="quality-api-draft", intake=self.intake, assignee_id=self.owner.pk,
            state="draft", reason="Human quality proposal, not site approval.", executed_at=None, execution_note=""), **changes}

    def test_actual_private_no_write_selections_csrf_exact_human_commands_history_and_reconciliation(self):
        path = self.api_path()
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.get(path).status_code, 401)
        client.force_login(self.owner)
        with patch("socket.create_connection", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            info = client.get(path)
        self.assertFalse(any(query["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"} for query in queries))
        self.assertEqual(info.status_code, 200, info.content)
        self.assertEqual(info["Cache-Control"], "private, no-store")
        self.assertEqual(info.json()["sources"], [self.evidence])
        self.assertEqual(info.json()["assignees"], [{"id": self.owner.pk}])
        self.assertNotIn(self.brief.artifact_key.encode(), info.content)
        self.assertFalse(ContentLifecycleReview.objects.exists())
        self.assertEqual(client.post(path, json.dumps(self.payload()), content_type="application/json").status_code, 403)
        client.get("/_allauth/browser/v1/auth/session")
        headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value}

        def post(url, **changes):
            return client.post(url, json.dumps(self.payload(**changes)), content_type="application/json", **headers)

        response = post(path); self.assertEqual(response.status_code, 201, response.content)
        saved = response.json()["review"]
        self.assertEqual(post(path).json()["review"]["id"], saved["id"])
        self.assertEqual(client.get(path, {"request_key": "quality-api-draft"}).json()["lookup"], "found")
        history = path + saved["review_id"] + "/"
        response = post(history, state="review", expected_revision=1, request_key="quality-api-review")
        self.assertEqual(response.status_code, 200, response.content)
        response = post(history, state="approved", expected_revision=2, request_key="quality-api-approved")
        self.assertTrue(response.json()["review"]["effective_approval"])
        self.assertEqual(len(client.get(history).json()["reviews"]), 3)
        self.assertFalse(client.get(path, {"request_key": "quality-api-draft"}).json()["reviews"][0]["is_latest"])
        SourceCitation.objects.filter(job=self.research).delete()
        stale = client.get(path).json()
        self.assertEqual(stale["sources"], [])
        self.assertFalse(stale["reviews"][0]["source_current"])
        self.assertFalse(stale["reviews"][0]["effective_approval"])
        self.assertEqual(post(history, state="reported", expected_revision=3, request_key="quality-api-stale-report",
            executed_at=timezone.now().isoformat(), execution_note="Stale manual handoff must fail.").status_code, 409)

    def test_foreign_viewer_strict_json_lookup_role_and_mid_private_read_delivery_loss(self):
        path = self.api_path()
        self.client.force_login(self.owner)
        for body in ('{"state":"draft","state":"approved"}', '{"value":NaN}', '[]', '{}', 'x' * (24 * 1024 + 1)):
            self.assertEqual(self.client.post(path, body, content_type="application/json").status_code, 409)
        for query in ("request_key=quality-one&request_key=quality-two", "request_key=bad", "extra=1"):
            self.assertEqual(self.client.get(path + "?" + query).status_code, 400)
        self.assertEqual(self.client.post(path + "?extra=1", json.dumps(self.payload()), content_type="application/json").status_code, 400)
        self.assertEqual(self.client.get(path + str(uuid4()) + "/").status_code, 404)
        self.client.force_login(self.viewer)
        self.assertFalse(self.client.get(path).json()["can_review"])
        self.assertEqual(self.client.get(path).json()["sources"], [])
        self.assertEqual(self.client.post(path, json.dumps(self.payload()), content_type="application/json").status_code, 403)
        self.client.force_login(self.other); self.assertEqual(self.client.get(path).status_code, 404)
        self.client.force_login(self.owner)
        from tenancy.artifacts import read_project_artifact

        def revoke(**kwargs):
            content = read_project_artifact(**kwargs)
            OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role=MembershipRole.VIEWER)
            return content

        with patch("jobs.authority.read_project_artifact", side_effect=revoke):
            self.assertEqual(self.client.get(path).status_code, 403)
        self.assertFalse(ContentLifecycleReview.objects.exists())
