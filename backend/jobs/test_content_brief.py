import json
import os
from hashlib import sha256
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import ProjectConfiguration
from tenancy.models import Organization
from tenancy.services import create_organization, create_project
from tenancy.deletion import delete_customer_database_records, prepare_customer_data_deletion, sweep_customer_artifact_versions
from .action_review import record_action
from .content_brief import create_content_brief, read_content_brief
from .models import ContentBriefSnapshot, IntentClusterReview
from .research import execute_research, queue_research


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}), DEBUG=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "brief-fixtures"}})
class ContentBriefTests(TransactionTestCase):
    def setUp(self):
        from .test_research import ResearchTests
        self.fixture = ResearchTests
        self.url = ResearchTests.url
        ResearchTests.setUp(self)
        config = ProjectConfiguration.objects.get(project=self.project)
        config.seed_topics = ["human-selected source topic"]
        config.save(update_fields=["seed_topics"])
        self.mapping = IntentClusterReview.objects.create(project=self.project, actor=self.owner,
            request_key="brief-intent-001", label="Human-selected source topic",
            manual_topics=["human-selected source topic"], market="Türkiye", language="en",
            intent="informational", page_kind="existing_unverified",
            preferred_page="https://research-project.example.invalid/service", reason="Review existing page first.",
            proposed_action="refresh", action_reason="Check whether the page helps users.")
        proposed = record_action(project=self.project, actor=self.owner, request_key="brief-action-001",
            source_id=self.mapping.pk, state="proposed", assignee_id=self.owner.pk,
            acceptance_criteria="Review original service details and evidence.", reason="Human proposal.")
        self.action = record_action(project=self.project, actor=self.owner, request_key="brief-action-002",
            source_id=self.mapping.pk, state="accepted", assignee_id=self.owner.pk,
            acceptance_criteria=proposed.acceptance_criteria, reason="Human approval.",
            action_id=proposed.action_id, expected_revision=1)
        with patch("jobs.services.dispatch_pending"):
            self.research = queue_research(project=self.project, actor=self.owner,
                data={**self.data, "mapping_id": self.mapping.pk}, idempotency_key="brief-research-001")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-not-real"}):
            self.assertTrue(execute_research(self.research.pk, fetcher=self.fixture.fetcher(self),
                                              request=self.fixture.response.__get__(self)))

    def create(self, **changes):
        data = dict(project=self.project, actor=self.owner, request_key="brief-request-001",
            research_job_id=self.research.pk, action_id=self.action.action_id,
            title_options=["Human-selected service question"], angle="Review the existing page with business owners.",
            outline=["Existing service details", "User questions"], questions=["Which details need verification?"])
        data.update(changes)
        return create_content_brief(**data)

    def test_exact_action_source_and_private_immutable_brief_readback(self):
        brief = self.create()
        body = read_content_brief(project=self.project, actor=self.owner, brief=brief)
        self.assertEqual(body["research_job_id"], self.research.pk)
        self.assertEqual(body["action_review_id"], self.action.pk)
        self.assertEqual(body["relevant_internal_links"], self.action.affected_urls)
        self.assertEqual(body["claims_to_verify"][0]["quote"], "Evidence useful.")
        self.assertEqual(body["approval"], "draft_human_review_required_no_site_change")
        self.assertEqual(self.create().pk, brief.pk)
        with self.assertRaises(ValidationError):
            self.create(title_options=["Different draft"])
        path = f"/api/organizations/{self.org.pk}/projects/{self.project.pk}/briefs/"
        client = Client(enforce_csrf_checks=True); client.force_login(self.owner)
        self.assertEqual(client.post(path, json.dumps({"request_key": "another-brief", "research_job_id": self.research.pk,
            "action_id": str(self.action.action_id), "title_options": ["A title"], "angle": "A review angle",
            "outline": ["A heading"], "questions": []}), content_type="application/json").status_code, 403)
        client.get("/_allauth/browser/v1/auth/session")
        headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value}
        response = client.post(path, json.dumps({"request_key": "another-brief", "research_job_id": self.research.pk,
            "action_id": str(self.action.action_id), "title_options": ["A title"], "angle": "A review angle",
            "outline": ["A heading"], "questions": []}), content_type="application/json", **headers)
        self.assertEqual(response.status_code, 201, response.content)
        detail = client.get(f"{path}{brief.pk}/")
        self.assertEqual(detail.status_code, 200, detail.content)
        self.assertEqual(detail.json()["draft"]["title_options"], ["Human-selected service question"])
        self.assertNotIn(brief.artifact_key.encode(), detail.content)
        download = client.get(f"{path}{brief.pk}/download/")
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download["X-Content-SHA256"], sha256(download.content).hexdigest())
        self.assertEqual(json.loads(download.content)["approval"], "draft_human_review_required_no_site_change")
        other = Client(); other.force_login(self.other)
        self.assertEqual(other.get(f"{path}{brief.pk}/").status_code, 404)
        organization = create_organization(user=self.other, name="Foreign brief")
        project = create_project(organization=organization, user=self.other, name="Foreign brief project",
                                 canonical_origin="https://foreign-brief.example.invalid")
        with self.assertRaises(PermissionDenied):
            read_content_brief(project=project, actor=self.other, brief=brief)
        with patch("jobs.content_brief.read_project_artifact", return_value=b"modified"):
            self.assertEqual(client.get(f"{path}{brief.pk}/").status_code, 503)
            self.assertEqual(client.get(f"{path}{brief.pk}/download/").status_code, 503)

    def test_reject_stale_mapping_action_or_unsupported_research_without_artifact(self):
        from tenancy.models import ProjectArtifactMutationAttempt
        from tenancy.customer_coherent_parts import coherent_customer_row_pages
        with self.assertRaises(PermissionDenied):
            self.create(actor=self.other)
        with self.assertRaises(ValidationError):
            self.create(action_id="invalid")
        IntentClusterReview.objects.create(project=self.project, actor=self.owner,
            request_key="brief-intent-002", cluster_id=self.mapping.cluster_id, revision=2,
            label=self.mapping.label, manual_topics=self.mapping.manual_topics, market=self.mapping.market,
            language=self.mapping.language, intent=self.mapping.intent, page_kind=self.mapping.page_kind,
            preferred_page=self.mapping.preferred_page, reason="Correction to existing human mapping.",
            proposed_action=self.mapping.proposed_action, action_reason=self.mapping.action_reason)
        with self.assertRaises(ValidationError):
            self.create()
        self.assertFalse(ContentBriefSnapshot.objects.filter(project=self.project).exists())
        self.assertFalse(ProjectArtifactMutationAttempt.objects.filter(organization=self.org).exists())
        self.assertTrue(list(coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk)))

    def test_brief_active_storage_and_metadata_are_removed_by_scoped_retention_runner(self):
        brief = self.create()
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
        run = prepare_customer_data_deletion(organization=self.org)
        while run.state == run.State.PENDING:
            run = sweep_customer_artifact_versions(run=run)
        self.assertEqual(run.state, run.State.STORAGE_CLEARED)
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(ContentBriefSnapshot.objects.filter(pk=brief.pk).exists())
