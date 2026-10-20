from unittest.mock import patch
import json
from datetime import timedelta
from zoneinfo import ZoneInfo

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from integrations.models import ImportRun, IntegrationConnection
from integrations.search_console import queue_search_console_csv_import
from integrations.services import create_connection
from tenancy.models import MembershipRole, OrganizationMembership, ProjectConfiguration
from tenancy.services import create_organization, create_project

from .action_review import record_action
from .findings import record_csv_findings
from .models import ActionReview, IntentClusterReview, Opportunity
from .services import execute_job


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/csv"}),
                   CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                                       "LOCATION": "action-review-fixtures"}})
class HumanActionTests(TransactionTestCase):
    def setUp(self):
        dispatch = patch("jobs.services.dispatch_pending", return_value=False)
        self.addCleanup(dispatch.stop)
        dispatch.start()
        cache.clear()
        users = get_user_model().objects
        self.owner = users.create_user("action-owner@example.invalid", "Test passphrase 99!")
        self.member = users.create_user("action-member@example.invalid", "Test passphrase 99!")
        self.outsider = users.create_user("action-outsider@example.invalid", "Test passphrase 99!")
        for actor in (self.owner, self.member, self.outsider):
            EmailAddress.objects.create(user=actor, email=actor.email, verified=True, primary=True)
        org = create_organization(user=self.owner, name="Synthetic action")
        OrganizationMembership.objects.create(organization=org, user=self.member, role=MembershipRole.MEMBER)
        self.project = create_project(organization=org, user=self.owner, name="Synthetic website",
                                      canonical_origin="https://actions.example.invalid")
        ProjectConfiguration.objects.create(project=self.project, target_country="Turkey",
                                            target_languages=["en"], seed_topics=["service questions"])
        self.source = IntentClusterReview.objects.create(project=self.project, actor=self.owner,
            request_key="source-action-001", label="Service intent", manual_topics=["service questions"],
            market="Turkey", language="en", intent="mixed", page_kind="existing_unverified",
            preferred_page="https://actions.example.invalid/services", reason="Manually selected source-poor topic.",
            proposed_action="refresh", action_reason="Check whether this existing page answers the topic.")

    def event(self, **changes):
        details = dict(project=self.project, actor=self.owner, request_key="action-review-001",
                       source_id=self.source.pk, state="proposed", assignee_id=self.member.pk,
                       acceptance_criteria="Review the exact page and log the implementation date.",
                       reason="Human action proposal; source topic is unmeasured.")
        details.update(changes)
        return record_action(**details)

    def test_approval_assignment_implementation_verification_and_outcome_are_separate(self):
        proposed = self.event()
        self.assertEqual(proposed.revision, 1)
        self.assertEqual(proposed.state, "proposed")
        self.assertEqual(self.event().pk, proposed.pk)
        accepted = self.event(request_key="action-review-002", action_id=proposed.action_id,
                              expected_revision=1, state="accepted")
        self.assertEqual(accepted.revision, 2)
        assigned = self.event(request_key="action-review-003", action_id=proposed.action_id,
                              expected_revision=2, state="in_progress", actor=self.member)
        self.assertEqual(assigned.state, "in_progress")
        implemented_at = timezone.now() - timedelta(days=1)
        implemented = self.event(request_key="action-review-004", action_id=proposed.action_id,
                                 expected_revision=3, state="implemented", actor=self.member,
                                 implemented_at=implemented_at, change_summary="Updated visible page copy manually.")
        self.assertIsNone(implemented.verified_at)
        verified = self.event(request_key="action-review-005", action_id=proposed.action_id,
                              expected_revision=4, state="verified", implemented_at=implemented_at,
                              change_summary=implemented.change_summary,
                              verification_note="Manually rechecked status and visible title.")
        self.assertIsNone(verified.outcome_reviewed_at)
        outcome = self.event(request_key="action-review-006", action_id=proposed.action_id,
                             expected_revision=5, state="outcome_reviewed", implemented_at=implemented_at,
                             change_summary=implemented.change_summary,
                             verification_note=verified.verification_note,
                             outcome_note="Comparable search outcome unknown; no uplift claim.")
        self.assertEqual(outcome.revision, 6)
        self.assertEqual(ActionReview.objects.filter(action_id=proposed.action_id).count(), 6)
        with self.assertRaises(ValidationError):
            proposed.save()
        with transaction.atomic(), self.assertRaises(IntegrityError):
            ActionReview.objects.filter(pk=proposed.pk).update(state="verified")

    def test_wrong_role_scope_revocation_and_stale_proposals_fail_closed(self):
        proposed = self.event()
        with self.assertRaises(PermissionDenied):
            self.event(request_key="action-review-002", action_id=proposed.action_id,
                       expected_revision=1, state="accepted", actor=self.member)
        with self.assertRaises(PermissionDenied):
            self.event(request_key="action-review-003", action_id=proposed.action_id,
                       expected_revision=1, state="proposed", actor=self.outsider)
        with self.assertRaises(ValidationError):
            self.event(request_key="action-review-004", action_id=proposed.action_id,
                       expected_revision=1, state="implemented", actor=self.member,
                       implemented_at=timezone.now(), change_summary="Cannot skip approval.")
        accepted = self.event(request_key="action-review-005", action_id=proposed.action_id,
                              expected_revision=1, state="accepted")
        with self.assertRaises(ValidationError):
            self.event(request_key="action-review-006", action_id=proposed.action_id,
                       expected_revision=1, state="in_progress", actor=self.member)
        with self.assertRaises(ValidationError):
            self.event(request_key="action-review-007", action_id=proposed.action_id,
                       expected_revision=2, state="in_progress", actor=self.member,
                       acceptance_criteria="Silently changed criteria.")
        OrganizationMembership.objects.filter(organization=self.project.organization, user=self.member).delete()
        with self.assertRaises(PermissionDenied):
            self.event(request_key="action-review-008", action_id=proposed.action_id,
                       expected_revision=2, state="in_progress", actor=self.member)

    def test_page_opportunity_can_propose_but_never_execute_a_scoped_redirect(self):
        connection = create_connection(project=self.project, user=self.owner, provider="google_search_console",
            external_property_id="https://actions.example.invalid/", capabilities=["csv_import", "page_metrics"],
            available_dimensions=["page"], source_semantics="search_console_performance",
            source_semantics_version="csv-v1", timezone="America/Los_Angeles")
        day = timezone.now().astimezone(ZoneInfo("America/Los_Angeles")).date() - timedelta(days=3)
        job = queue_search_console_csv_import(connection=connection, user=self.owner,
            content=b"Top pages,Clicks,Impressions,CTR,Position\n"
                    b"https://actions.example.invalid/old,2,200,1%,10\n",
            date_start=day - timedelta(days=6), date_end=day)
        self.assertTrue(execute_job(job.pk))
        finding = record_csv_findings(project=self.project, actor=self.owner,
                                      connection=connection, import_id=ImportRun.objects.get(job=job).pk)[0][0]
        opportunity = Opportunity.objects.create(project=self.project, finding=finding, actor=self.owner,
            priority="medium", review_reason="Human selected page observation for possible action.")
        values = dict(source_type="opportunity", source_id=opportunity.pk, action_kind="redirect",
                      destination_page="https://actions.example.invalid/new")
        proposed = self.event(request_key="action-page-001", **values)
        self.assertEqual(proposed.affected_urls, ["https://actions.example.invalid/old",
                                                   "https://actions.example.invalid/new"])
        self.assertEqual(proposed.opportunity_id, opportunity.pk)
        self.assertEqual(proposed.state, "proposed")
        with self.assertRaises(ValidationError):
            self.event(request_key="action-page-002", **{**values, "destination_page": "https://outside.example/"})
        IntegrationConnection.objects.filter(pk=connection.pk).update(state="disconnected")
        with self.assertRaises((PermissionDenied, ValidationError)):
            self.event(request_key="action-page-003", **values)

    def test_corrected_source_resets_approval_before_any_new_work(self):
        initial = self.event()
        approved = self.event(request_key="action-reset-002", action_id=initial.action_id,
                              expected_revision=1, state="accepted")
        updated_source = IntentClusterReview.objects.create(project=self.project, actor=self.owner,
            request_key="source-action-002", cluster_id=self.source.cluster_id, revision=2,
            label="Corrected service intent", manual_topics=["service questions"], market="Turkey", language="en",
            intent="mixed", page_kind="existing_unverified",
            preferred_page="https://actions.example.invalid/services",
            reason="Human corrected the proposed source after approval.", proposed_action="refresh",
            action_reason="Review the corrected proposal before accepting again.")
        with self.assertRaises(ValidationError):
            self.event(request_key="action-reset-003", source_id=updated_source.pk,
                       action_id=initial.action_id, expected_revision=2, state="in_progress", actor=self.member)
        reopened = self.event(request_key="action-reset-004", source_id=updated_source.pk,
                              action_id=initial.action_id, expected_revision=2, state="proposed")
        self.assertEqual(reopened.revision, 3)
        self.assertEqual(reopened.state, "proposed")
        self.assertNotEqual(reopened.intent_cluster_id, approved.intent_cluster_id)

    def test_action_api_requires_project_csrf_and_owner_approval_before_member_progress(self):
        prefix = f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}/actions/"
        data = {"request_key": "action-api-001", "source_type": "intent", "source_id": self.source.pk,
                "state": "proposed", "action_kind": "refresh", "destination_page": "",
                "assignee_id": self.member.pk, "acceptance_criteria": "Check a page change and log its date.",
                "reason": "Human review of a source-poor seed topic.", "implemented_at": None,
                "change_summary": "", "verification_note": "", "outcome_note": ""}
        owner = Client(enforce_csrf_checks=True)
        owner.force_login(self.owner)
        owner.get("/_allauth/browser/v1/auth/session")
        self.assertEqual(owner.post(prefix, data=json.dumps(data), content_type="application/json").status_code, 403)
        def post(client, url, payload):
            client.get("/_allauth/browser/v1/auth/session")
            return client.post(url, data=json.dumps(payload), content_type="application/json",
                               HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        created = post(owner, prefix, data)
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(created.json()["action"]["execution"], "human_only_no_website_change")
        action_id = created.json()["action"]["action_id"]
        path = prefix + action_id + "/"
        member = Client(enforce_csrf_checks=True)
        member.force_login(self.member)
        approved = {**data, "request_key": "action-api-002", "expected_revision": 1, "state": "accepted"}
        self.assertEqual(post(member, path, approved).status_code, 403)
        self.assertEqual(post(owner, path, approved).status_code, 200)
        assigned = {**approved, "request_key": "action-api-003", "expected_revision": 2, "state": "in_progress"}
        self.assertEqual(post(member, path, assigned).json()["action"]["state"], "in_progress")
        self.assertEqual(post(member, path, {**assigned, "request_key": "action-api-004"}).status_code, 409)
        self.assertEqual([row["state"] for row in owner.get(path).json()["history"]],
                         ["in_progress", "accepted", "proposed"])
        outsider = Client()
        outsider.force_login(self.outsider)
        self.assertEqual(outsider.get(path).status_code, 404)
        viewer_user = get_user_model().objects.create_user("action-viewer@example.invalid", "Test passphrase 99!")
        EmailAddress.objects.create(user=viewer_user, email=viewer_user.email, verified=True, primary=True)
        OrganizationMembership.objects.create(organization=self.project.organization, user=viewer_user,
                                              role=MembershipRole.VIEWER)
        viewer = Client()
        viewer.force_login(viewer_user)
        self.assertEqual(viewer.get(path).status_code, 200)
        self.assertEqual(viewer.post(path, data=json.dumps(assigned), content_type="application/json").status_code, 403)
        self.assertEqual(ActionReview.objects.filter(project=self.project).count(), 3)
