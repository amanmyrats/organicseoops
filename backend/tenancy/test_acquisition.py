from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from unittest.mock import patch

from config.test_foundations import TEST_STORAGES
from jobs import test_action_review as action_fixtures
from jobs.models import IntentClusterReview

from tenancy.models import AuditEvent, AuditEventType, Organization, OrganizationMembership, Project, ProjectConfiguration
from tenancy.services import create_organization, create_project

from .acquisition import acquisition_milestones


@override_settings(STAFF_MFA_REQUIRED=False)
class AcquisitionMilestoneTests(TestCase):
    def test_only_retained_authoritative_milestones_are_derivable(self):
        users = get_user_model().objects
        owner = users.create_user("self-service@example.invalid", "Test passphrase 99!")
        EmailAddress.objects.create(user=owner, email=owner.email, verified=True, primary=True)
        users.filter(pk=owner.pk).update(registration_origin="self_service", first_email_verified_at=timezone.now())
        organization = create_organization(user=owner, name="Synthetic trial")
        invited = users.create_user("invited@example.invalid", "Test passphrase 99!")
        EmailAddress.objects.create(user=invited, email=invited.email, verified=True, primary=True)
        milestones = acquisition_milestones()["milestones"]
        self.assertEqual(milestones["registration_succeeded"]["count"], 1)
        self.assertEqual(milestones["email_verified"]["count"], 1)
        self.assertEqual(milestones["trial_activated"]["count"], 1)
        self.assertEqual(milestones["first_import_succeeded"]["count"], 0)
        self.assertEqual(milestones["first_action_accepted"], {"grain": "organization", "count": 0, "state": "derivable"})
        self.assertEqual(milestones["checkout_initiated"], {"grain": "checkout_attempt", "count": 0, "state": "derivable"})
        self.assertEqual(milestones["paid_activation_confirmed"], {"grain": "organization", "count": 0, "state": "derivable"})
        self.assertEqual(milestones["first_audit_succeeded"], {"grain": "organization", "count": 0, "state": "derivable"})
        for event in ("public_page_view", "public_cta_selected"):
            self.assertEqual(milestones[event], {"count": None, "state": "unavailable"})
        AuditEvent.objects.filter(organization=organization, event_type=AuditEventType.TRIAL_GRANTED).delete()
        self.assertEqual(acquisition_milestones()["milestones"]["trial_activated"]["count"], 0)

    def test_staff_mfa_read_only_boundary_exposes_no_operational_ids(self):
        users = get_user_model().objects
        staff = users.create_superuser("staff@example.invalid", "Test passphrase 99!")
        customer = users.create_user("customer@example.invalid", "Test passphrase 99!")
        url = "/api/platform/acquisition/milestones/"
        client = Client()
        self.assertEqual(client.get(url).status_code, 401)
        client.force_login(customer)
        self.assertEqual(client.get(url).status_code, 403)
        client.force_login(staff)
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response.json()["dictionary_version"], "acquisition-v1")
        self.assertFalse(response.json()["funnel_rates_available"])
        self.assertNotIn("staff@example.invalid", str(response.json()))
        self.assertNotIn("customer@example.invalid", str(response.json()))
        self.assertNotIn("organization_id", str(response.json()))
        self.assertEqual(client.post(url).status_code, 405)
        with override_settings(STAFF_MFA_REQUIRED=True):
            self.assertEqual(client.get(url).status_code, 403)


@override_settings(STORAGES=TEST_STORAGES, STAFF_MFA_REQUIRED=False)
class RetainedActionMilestoneTests(TransactionTestCase):
    setUp = action_fixtures.HumanActionTests.setUp
    event = action_fixtures.HumanActionTests.event

    def count(self):
        return acquisition_milestones()["milestones"]["first_action_accepted"]["count"]

    def test_actual_human_acceptance_is_once_per_retained_organization_not_latest_state_project_or_revision(self):
        from jobs.action_review import record_action
        from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        proposed = self.event()
        self.assertEqual(self.count(), 0)
        with self.assertRaises(PermissionDenied):
            self.event(request_key="milestone-member-denied", action_id=proposed.action_id, expected_revision=1,
                state="accepted", actor=self.member)
        self.assertEqual(self.count(), 0)
        approved = self.event(request_key="milestone-accepted", action_id=proposed.action_id, expected_revision=1, state="accepted")
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.event(request_key="milestone-accepted", action_id=proposed.action_id, expected_revision=1, state="accepted").pk, approved.pk)
        progressing = self.event(request_key="milestone-progress", action_id=proposed.action_id, expected_revision=2,
            state="in_progress", actor=self.member)
        self.event(request_key="milestone-dismissed", action_id=proposed.action_id, expected_revision=progressing.revision, state="dismissed")
        reopened = self.event(request_key="milestone-reopened", action_id=proposed.action_id, expected_revision=4, state="proposed")
        self.event(request_key="milestone-reaccepted", action_id=proposed.action_id, expected_revision=reopened.revision, state="accepted")
        self.assertEqual(self.count(), 1)

        # A second genuine project and another organization get independent manual sources/decisions.
        other_org = create_organization(user=self.outsider, name="Synthetic other milestone organization")
        other_project = create_project(organization=other_org, user=self.outsider, name="Other milestone project",
            canonical_origin="https://other-action.example.invalid")
        sibling = Project.objects.create(organization=self.project.organization, name="Synthetic sibling fixture",
            canonical_origin="https://sibling-action.example.invalid")
        for project, actor, accepted in ((sibling, self.owner, True), (other_project, self.outsider, False)):
            ProjectConfiguration.objects.create(project=project, seed_topics=["service questions"])
            source = IntentClusterReview.objects.create(project=project, actor=actor, request_key="milestone-source",
                label="Human source", manual_topics=["service questions"], market="Turkey", language="en", intent="mixed",
                page_kind="existing_unverified", preferred_page=project.canonical_origin + "/services", reason="Unmeasured human intent.",
                proposed_action="refresh", action_reason="Review usefulness separately.")
            data = dict(project=project, actor=actor, source_id=source.pk, assignee_id=actor.pk,
                acceptance_criteria="Inspect the selected page.", reason="Human decision.")
            proposal = record_action(**data, request_key="milestone-other-proposal", state="proposed")
            if accepted:
                record_action(**data, request_key="milestone-other-accepted", state="accepted", action_id=proposal.action_id, expected_revision=1)
            else:
                record_action(**data, request_key="milestone-other-dismissed", state="dismissed", action_id=proposal.action_id, expected_revision=1)
                self.assertEqual(self.count(), 1)
                proposal = record_action(**data, request_key="milestone-other-reopened", state="proposed", action_id=proposal.action_id, expected_revision=2)
                record_action(**data, request_key="milestone-other-accepted", state="accepted", action_id=proposal.action_id, expected_revision=3)
        self.assertEqual(self.count(), 2)
        ProjectConfiguration.objects.filter(project=self.project).update(seed_topics=[])
        OrganizationMembership.objects.filter(organization=self.project.organization, user=self.owner).update(role="viewer")
        self.assertEqual(self.count(), 2)  # Earlier historical acceptance is not current-use authority or a site outcome.
        staff = get_user_model().objects.create_superuser("milestone-staff@example.invalid", "Test passphrase 99!")
        self.client.force_login(staff)
        with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            result = self.client.get("/api/platform/acquisition/milestones/")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result["Cache-Control"], "private, no-store")
        self.assertEqual(result.json()["milestones"]["first_action_accepted"], {"count": 2, "grain": "organization", "state": "derivable"})
        self.assertFalse(any(row["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"} for row in queries))
        for private in ("organization_id", "project_id", "action_id", "created_at", "services", "milestone-source", self.owner.email):
            self.assertNotIn(private, result.content.decode())
        Organization.objects.filter(pk=self.project.organization_id).update(is_suspended=True, closed_at=timezone.now())
        self.assertEqual(self.count(), 2)  # Retained source records still exist until actual erasure.
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.project.organization))
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertEqual(self.count(), 1)
