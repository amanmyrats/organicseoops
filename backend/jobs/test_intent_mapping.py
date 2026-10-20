from unittest.mock import patch
import json
from datetime import timedelta
from zoneinfo import ZoneInfo

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from integrations.models import ImportRun, IntegrationConnection
from integrations.search_console import queue_search_console_csv_import
from integrations.services import create_connection
from tenancy.models import MembershipRole, OrganizationMembership, ProjectConfiguration
from tenancy.services import create_organization, create_project

from .findings import record_csv_findings
from .intent_mapping import review_intent_cluster
from .models import IntentClusterReview
from .services import execute_job


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/csv"}),
                   CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                                       "LOCATION": "intent-map-fixtures"}})
class IntentMappingTests(TransactionTestCase):
    def setUp(self):
        dispatch = patch("jobs.services.dispatch_pending", return_value=False)
        self.addCleanup(dispatch.stop)
        dispatch.start()
        cache.clear()
        users = get_user_model().objects
        self.owner = users.create_user("map-owner@example.invalid", "Test passphrase 99!")
        self.foreign = users.create_user("map-foreign@example.invalid", "Test passphrase 99!")
        for user in (self.owner, self.foreign):
            EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
        organization = create_organization(user=self.owner, name="Synthetic map")
        self.project = create_project(organization=organization, user=self.owner,
                                      name="Synthetic site", canonical_origin="https://map.example.invalid")
        config, _ = ProjectConfiguration.objects.get_or_create(project=self.project)
        config.target_country = "Turkey"
        config.target_languages = ["en"]
        config.save(update_fields=["target_country", "target_languages"])
        self.connection = create_connection(project=self.project, user=self.owner, provider="google_search_console",
            external_property_id="https://map.example.invalid/", capabilities=["csv_import", "query_metrics"],
            available_dimensions=["query"], source_semantics="search_console_performance",
            source_semantics_version="csv-v1", timezone="America/Los_Angeles")
        day = timezone.now().astimezone(ZoneInfo("America/Los_Angeles")).date() - timedelta(days=3)
        job = queue_search_console_csv_import(connection=self.connection, user=self.owner,
            content=b"Top queries,Clicks,Impressions,CTR,Position\nexample query,2,200,1%,10\n"
                    b"other topic,2,150,1%,9\n", date_start=day - timedelta(days=6), date_end=day)
        self.assertTrue(execute_job(job.pk))
        run = ImportRun.objects.get(job=job)
        self.findings = record_csv_findings(project=self.project, actor=self.owner,
                                            connection=self.connection, import_id=run.pk)[0]

    def decision(self, **changes):
        values = dict(project=self.project, actor=self.owner, request_key="intent-req-001",
                      label="Agency service questions", source_finding_ids=[self.findings[0].pk,
                        next(item.pk for item in self.findings if item.source_metric_id != self.findings[0].source_metric_id)],
                      intent="mixed", page_kind="existing_unverified",
                      preferred_page="https://map.example.invalid/services", language="en",
                      reason="Human selected a possible existing page; CSV exports have no query-page join.")
        values.update(changes)
        return review_intent_cluster(**values)

    def test_human_cluster_revision_is_scoped_idempotent_and_never_claims_query_page_attribution(self):
        first = self.decision()
        self.assertEqual(first.market, "Turkey")
        self.assertEqual(first.revision, 1)
        self.assertEqual(first.page_kind, "existing_unverified")
        self.assertEqual(self.decision().pk, first.pk)
        later = self.decision(request_key="intent-req-002", cluster_id=first.cluster_id,
                              expected_revision=1, intent="informational", page_kind="proposed",
                              preferred_page="https://map.example.invalid/new-resource")
        self.assertEqual(later.revision, 2)
        self.assertEqual(IntentClusterReview.objects.filter(project=self.project, cluster_id=first.cluster_id).count(), 2)
        with self.assertRaises(ValidationError):
            self.decision()  # A lost reply to revision 1 cannot masquerade as the latest correction.
        with self.assertRaises(ValidationError):
            self.decision(request_key="intent-req-003", cluster_id=first.cluster_id, expected_revision=1)
        with self.assertRaises(ValidationError):
            first.save()

    def test_foreign_actor_page_and_revoked_source_cannot_create_or_correct_cluster(self):
        with self.assertRaises(PermissionDenied):
            self.decision(actor=self.foreign)
        for url in ("https://outside.example.invalid/", "https://map.example.invalid/?token=bad",
                    "https://map.example.invalid/path#fragment"):
            with self.subTest(url=url), self.assertRaises(ValidationError):
                self.decision(preferred_page=url)
        with self.assertRaises(ValidationError):
            self.decision(language="tr")
        with self.assertRaises(ValidationError):
            self.decision(source_finding_ids=[self.findings[0].pk, self.findings[0].pk])
        IntegrationConnection.objects.filter(pk=self.connection.pk).update(state="disconnected")
        with self.assertRaises((PermissionDenied, ValidationError)):
            self.decision()

    def test_manual_seed_topics_are_explicitly_unmeasured_and_stale_after_configuration_change(self):
        config = ProjectConfiguration.objects.get(project=self.project)
        config.seed_topics = ["airport service questions", "transport options"]
        config.save(update_fields=["seed_topics"])
        review = self.decision(request_key="intent-manual-001", source_finding_ids=[],
                               manual_topics=["airport service questions"], page_kind="proposed",
                               preferred_page="https://map.example.invalid/new-guide")
        self.assertEqual(review.source_finding_ids, [])
        self.assertEqual(review.manual_topics, ["airport service questions"])
        path = f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}/intent-clusters/{review.cluster_id}/"
        client = Client()
        client.force_login(self.owner)
        source = client.get(path).json()["history"][0]
        self.assertEqual(source["source_kind"], "manual_seed_no_search_observation")
        self.assertTrue(source["source_current"])
        config.seed_topics = []
        config.save(update_fields=["seed_topics"])
        self.assertFalse(client.get(path).json()["history"][0]["source_current"])
        with self.assertRaises(ValidationError):
            self.decision(request_key="intent-manual-002", source_finding_ids=[],
                          manual_topics=["airport service questions"])

    def test_unapproved_page_actions_need_explicit_matching_source_and_destination(self):
        for action in ("keep", "refresh", "retire"):
            with self.subTest(action=action):
                review = self.decision(request_key=f"intent-{action}-001", proposed_action=action,
                    action_reason="Human review proposes this only; no live page will be changed.")
                self.assertEqual(review.proposed_action, action)
                self.assertEqual(review.affected_page, "")
        for action in ("merge", "redirect"):
            review = self.decision(request_key=f"intent-{action}-001", proposed_action=action,
                affected_page="https://map.example.invalid/old", action_reason="Review source and destination before approval.")
            self.assertNotEqual(review.affected_page, review.preferred_page)
            with self.assertRaises(ValidationError):
                self.decision(request_key=f"intent-{action}-bad", proposed_action=action,
                    affected_page="https://outside.example.invalid/old", action_reason="Not enough evidence.")
        created = self.decision(request_key="intent-create-001", proposed_action="create",
            page_kind="proposed", preferred_page="https://map.example.invalid/new-guide",
            action_reason="A human proposed a possible page, not a published result.")
        self.assertEqual(created.page_kind, "proposed")
        for changes in ({"proposed_action": "retire", "action_reason": ""},
                        {"proposed_action": "create", "action_reason": "Not a proposed page."},
                        {"proposed_action": "redirect", "action_reason": "Same URL.",
                         "affected_page": "https://map.example.invalid/services"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.decision(request_key="intent-invalid-001", **changes)

    def test_api_enforces_project_scope_csrf_history_and_source_revocation(self):
        viewer = get_user_model().objects.create_user("map-viewer@example.invalid", "Test passphrase 99!")
        EmailAddress.objects.create(user=viewer, email=viewer.email, primary=True, verified=True)
        OrganizationMembership.objects.create(organization=self.project.organization, user=viewer,
                                              role=MembershipRole.VIEWER)
        prefix = f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}/intent-clusters/"
        data = {"request_key": "intent-api-001", "label": "Human review", "language": "en",
                "source_finding_ids": [self.findings[0].pk], "manual_topics": [], "intent": "mixed",
                "page_kind": "existing_unverified", "preferred_page": "https://map.example.invalid/services",
                "reason": "Review the existing page; no query-page evidence exists.",
                "proposed_action": "unselected", "action_reason": "", "affected_page": ""}
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        client.get("/_allauth/browser/v1/auth/session")
        self.assertEqual(client.post(prefix, data=json.dumps(data), content_type="application/json").status_code, 403)
        headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value}
        def post(url, payload):
            return client.post(url, data=json.dumps(payload), content_type="application/json", **headers)
        created = post(prefix, data)
        self.assertEqual(created.status_code, 201, created.content)
        cluster = created.json()["cluster"]
        self.assertTrue(cluster["source_current"])
        self.assertEqual(cluster["page_attribution"], "human_selected_no_joint_query_page_evidence")
        self.assertEqual(cluster["proposal_state"], "unapproved_human_proposal")
        self.assertEqual(post(prefix, data).json()["cluster"]["cluster_id"], cluster["cluster_id"])
        correction = {**data, "request_key": "intent-api-002", "expected_revision": 1,
                      "page_kind": "proposed", "preferred_page": "https://map.example.invalid/new"}
        path = prefix + cluster["cluster_id"] + "/"
        self.assertEqual(post(path, correction).json()["cluster"]["revision"], 2)
        self.assertEqual(post(path, {**correction, "request_key": "intent-api-003"}).status_code, 409)
        self.assertEqual([row["revision"] for row in client.get(path).json()["history"]], [2, 1])
        viewer_client = Client()
        viewer_client.force_login(viewer)
        self.assertEqual(viewer_client.get(path).status_code, 200)
        self.assertEqual(viewer_client.post(path, data=json.dumps(correction), content_type="application/json").status_code, 403)
        foreign_client = Client()
        foreign_client.force_login(self.foreign)
        self.assertEqual(foreign_client.get(path).status_code, 404)
        IntegrationConnection.objects.filter(pk=self.connection.pk).update(state="disconnected")
        history = client.get(path)
        self.assertFalse(history.json()["history"][0]["source_current"])
        self.assertEqual(post(path, {**correction, "request_key": "intent-api-004", "expected_revision": 2}).status_code, 409)
