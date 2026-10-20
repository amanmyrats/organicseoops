import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connections
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import MembershipRole, Organization, OrganizationMembership, ProjectConfiguration
from tenancy.services import create_organization, create_project
from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
from .content import record_content
from .models import ContentItem, ContentRevision


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}), DEBUG=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "content-fixtures"}})
class ContentTests(TransactionTestCase):
    def setUp(self):
        from .test_content_brief import ContentBriefTests
        ContentBriefTests.setUp(self)
        self.brief = ContentBriefTests.create(self)
        self.path = f"/api/organizations/{self.org.pk}/projects/{self.project.pk}/content/"
        self.fields = dict(request_key="content-request-001", brief_id=self.brief.pk, kind="refresh",
            title="Human service draft", body="<script>untrusted()</script>\nActual details require human verification.",
            meta_description="Unverified service summary", state="draft", reason="Human authored text, not facts verified.")

    def record(self, previous=None, **changes):
        data = {**self.fields, **changes}
        if previous:
            data.update(item_id=previous.item_id, expected_revision=previous.revision)
        return record_content(project=self.project, actor=self.owner, **data)

    def test_exact_review_approval_edits_publication_archive_and_reopen(self):
        draft = self.record()
        self.assertEqual(self.record().pk, draft.pk)
        with self.assertRaises(ValidationError):
            self.record(draft, request_key="content-direct-approval", state="approved")
        review = self.record(draft, request_key="content-review-001", state="review")
        with self.assertRaises(ValidationError):
            self.record(review, request_key="content-wrong-text", state="approved", body="Changed after review")
        approved = self.record(review, request_key="content-approved-001", state="approved", reason="Verified exact text and facts.")
        self.assertEqual(approved.reviewed_revision_id, review.pk)
        self.assertEqual(approved.approved_by_id, self.owner.pk)
        with self.assertRaises(ValidationError):
            self.record(review, request_key="content-stale-review", state="approved")
        published = self.record(approved, request_key="content-published-001", state="published",
            publication_url="https://research-project.example.invalid/service", published_at=timezone.now())
        archived = self.record(published, request_key="content-archived-001", state="archived")
        self.assertEqual(archived.publication_url, published.publication_url)
        self.assertEqual(archived.published_at, published.published_at)
        reopened = self.record(archived, request_key="content-reopened-001", body="Revised text requires fresh approval.")
        self.assertIsNone(reopened.reviewed_revision_id)
        self.assertIsNone(reopened.approved_at)
        self.assertEqual(reopened.publication_url, published.publication_url)
        draft.refresh_from_db()
        self.assertEqual(draft.body, self.fields["body"])
        with self.assertRaises(ValidationError):
            draft.save()
        self.assertEqual(ContentItem.objects.count(), 1)
        self.assertEqual(ContentRevision.objects.count(), 6)

    def test_roles_csrf_foreign_sources_history_and_text_only_export(self):
        client = Client(enforce_csrf_checks=True); client.force_login(self.owner)
        self.assertEqual(client.post(self.path, json.dumps(self.fields), content_type="application/json").status_code, 403)
        client.get("/_allauth/browser/v1/auth/session")
        headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value}
        response = client.post(self.path, json.dumps(self.fields), content_type="application/json", **headers)
        self.assertEqual(response.status_code, 201, response.content)
        draft = ContentRevision.objects.get(pk=response.json()["revision"]["id"])
        review = self.record(draft, request_key="content-review-api", state="review")
        item_path = f"{self.path}{draft.item_id}/"
        viewer = Client(); viewer.force_login(self.viewer)
        self.assertEqual(viewer.get(item_path).status_code, 200)
        self.assertEqual(viewer.post(item_path, json.dumps({**self.fields, "expected_revision": 2,
            "request_key": "viewer-approval-1", "state": "approved"}), content_type="application/json").status_code, 403)
        OrganizationMembership.objects.filter(organization=self.org, user=self.viewer).update(role=MembershipRole.MEMBER)
        with self.assertRaises(PermissionDenied):
            record_content(project=self.project, actor=self.viewer, **{**self.fields, "state": "approved",
                "request_key": "member-approval-1", "item_id": review.item_id, "expected_revision": 2})
        edited = record_content(project=self.project, actor=self.viewer, **{**self.fields,
            "request_key": "member-edit-0001", "item_id": review.item_id, "expected_revision": 2, "body": "Member draft"})
        self.assertEqual(edited.state, "draft")
        other = Client(); other.force_login(self.other)
        self.assertEqual(other.get(item_path).status_code, 404)
        org = create_organization(user=self.other, name="Foreign content")
        project = create_project(organization=org, user=self.other, name="Foreign project",
                                 canonical_origin="https://foreign-content.example.invalid")
        with self.assertRaises(PermissionDenied):
            record_content(project=project, actor=self.other, **self.fields)
        with self.assertRaises(ValidationError):
            ContentRevision.objects.create(project=project, item=draft.item, brief=self.brief, actor=self.other,
                request_key="foreign-model-reference", revision=4, state="draft", kind="custom", title="Foreign",
                body="Foreign", reason="Must reject cross-project model references.")
        detail = client.get(item_path).json()
        self.assertEqual(detail["current"]["revision"], 3)
        self.assertEqual(detail["history"][-1]["body"], self.fields["body"])
        self.assertNotIn(self.brief.artifact_key, json.dumps(detail))
        exported = client.get(f"{item_path}download/")
        self.assertEqual(exported["Content-Type"], "application/json")
        self.assertIn("no-store", exported["Cache-Control"])
        self.assertEqual(json.loads(exported.content)["revision"]["body"], "Member draft")

    def test_stale_source_integrity_and_closed_tenant_deletion(self):
        draft = self.record()
        review = self.record(draft, request_key="deletion-review-001", state="review")
        approved = self.record(review, request_key="deletion-approval-001", state="approved")
        config = ProjectConfiguration.objects.get(project=self.project)
        config.seed_topics = []; config.save(update_fields=["seed_topics"])
        with self.assertRaises(ValidationError):
            self.record(draft, request_key="stale-source-review", state="review")
        client = Client(); client.force_login(self.owner)
        self.assertEqual(client.get(f"{self.path}{draft.item_id}/").json()["source_state"], "stale_prepare_new_brief_before_review")
        with patch("jobs.content_brief.read_project_artifact", return_value=b"tampered"):
            self.assertEqual(client.get(f"{self.path}{draft.item_id}/").json()["source_state"], "private_brief_unavailable")
        archived = self.record(approved, request_key="stale-source-archive", state="archived")
        self.assertEqual(archived.state, "archived")
        foreign_org = create_organization(user=self.other, name="Retained foreign content")
        foreign_project = create_project(organization=foreign_org, user=self.other, name="Foreign content project",
            canonical_origin="https://retained-foreign.example.invalid")
        foreign_item = ContentItem.objects.create(project=foreign_project, actor=self.other, request_key="retained-foreign-item")
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
        self.assertEqual(client.get(f"{self.path}{draft.item_id}/").status_code, 404)
        run = prepare_customer_data_deletion(organization=self.org)
        while run.state == run.State.PENDING:
            run = sweep_customer_artifact_versions(run=run)
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(ContentRevision.objects.exists())
        self.assertFalse(ContentItem.objects.filter(project=self.project).exists())
        self.assertTrue(ContentItem.objects.filter(pk=foreign_item.pk).exists())


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}), DEBUG=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "content-race-fixtures"}})
class ContentConcurrencyTests(TransactionTestCase):
    setUp = ContentTests.setUp
    record = ContentTests.record

    def test_two_simultaneous_approvals_bind_only_the_current_revision(self):
        draft = self.record()
        review = self.record(draft, request_key="race-content-review", state="review")
        barrier = Barrier(2)

        def approve(index):
            try:
                barrier.wait(timeout=10)
                self.record(review, request_key=f"concurrent-approval-{index}", state="approved")
                return "approved"
            except ValidationError:
                return "conflict"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(approve, (1, 2)))
        self.assertCountEqual(results, ["approved", "conflict"])
        self.assertEqual(ContentRevision.objects.filter(state="approved", reviewed_revision=review).count(), 1)
