from unittest.mock import patch
import json
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from integrations.models import ImportRun, IntegrationConnection
from integrations.search_console import queue_search_console_csv_import
from integrations.services import create_connection
from tenancy.models import MembershipRole, OrganizationMembership, ProjectConfiguration
from tenancy.services import create_organization, create_project

from .action_review import record_action
from .models import (ActionOutcomeSnapshot, ActionTechnicalOutcomeSnapshot, CrawlPageSnapshot,
                     CrawlRun, IntentClusterReview, JobRun, JobStatus)
from .outcome_comparison import compare_action_page_windows, record_page_outcome
from .technical_outcome import compare_action_crawls, record_action_crawl_observations
from .services import execute_job, transition


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/csv"}),
                   CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                                       "LOCATION": "outcome-fixtures"}})
class ActionPageOutcomeTests(TransactionTestCase):
    def setUp(self):
        dispatch = patch("jobs.services.dispatch_pending", return_value=False)
        self.addCleanup(dispatch.stop)
        dispatch.start()
        cache.clear()
        user = get_user_model().objects.create_user("outcome-owner@example.invalid", "Test passphrase 99!")
        EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
        self.actor = user
        organization = create_organization(user=user, name="Synthetic action outcome")
        self.project = create_project(organization=organization, user=user, name="Synthetic property",
                                      canonical_origin="https://outcome.example.invalid")
        ProjectConfiguration.objects.create(project=self.project, target_country="Turkey",
                                            target_languages=["en"], seed_topics=["manual source intent"])
        self.source = IntentClusterReview.objects.create(project=self.project, actor=user,
            request_key="outcome-source-001", label="Example page intent", manual_topics=["manual source intent"],
            market="Turkey", language="en", page_kind="existing_unverified",
            preferred_page="https://outcome.example.invalid/services", reason="Human source-poor review.",
            proposed_action="refresh", action_reason="Review the existing page manually.")
        self.implemented_at = timezone.now() - timedelta(days=14)
        first = record_action(project=self.project, actor=user, request_key="outcome-action-001",
            source_id=self.source.pk, state="proposed", assignee_id=user.pk,
            acceptance_criteria="Record any reviewed page change.", reason="Human proposal only.")
        accepted = record_action(project=self.project, actor=user, request_key="outcome-action-002",
            source_id=self.source.pk, state="accepted", assignee_id=user.pk,
            acceptance_criteria=first.acceptance_criteria, reason="Owner approves a manual change.",
            action_id=first.action_id, expected_revision=1)
        running = record_action(project=self.project, actor=user, request_key="outcome-action-003",
            source_id=self.source.pk, state="in_progress", assignee_id=user.pk,
            acceptance_criteria=first.acceptance_criteria, reason="Working on manually approved scope.",
            action_id=first.action_id, expected_revision=2)
        self.action = record_action(project=self.project, actor=user, request_key="outcome-action-004",
            source_id=self.source.pk, state="implemented", assignee_id=user.pk,
            acceptance_criteria=first.acceptance_criteria, reason="Manual implementation logged.",
            change_summary="Title updated by the site owner.", implemented_at=self.implemented_at,
            action_id=first.action_id, expected_revision=3)
        self.connection = create_connection(project=self.project, user=user, provider="google_search_console",
            external_property_id="https://outcome.example.invalid/", capabilities=["csv_import", "page_metrics"],
            available_dimensions=["page"], source_semantics="search_console_performance",
            source_semantics_version="csv-v1", timezone="America/Los_Angeles")
        today = timezone.now().astimezone(ZoneInfo("America/Los_Angeles")).date()
        before_end = today - timedelta(days=20)
        after_end = today - timedelta(days=6)
        self.before = self.import_page(0, 200, "0%", 12, before_end - timedelta(days=6), before_end)
        self.after = self.import_page(4, 250, "1.6%", 9, after_end - timedelta(days=6), after_end)

    def import_page(self, clicks, impressions, ctr, position, start, end):
        content = (f"Top pages,Clicks,Impressions,CTR,Position\n"
                   f"https://outcome.example.invalid/services,{clicks},{impressions},{ctr},{position}\n").encode()
        job = queue_search_console_csv_import(connection=self.connection, user=self.actor,
                                               content=content, date_start=start, date_end=end)
        self.assertTrue(execute_job(job.pk))
        return ImportRun.objects.get(job=job)

    def report(self):
        return compare_action_page_windows(project=self.project, actor=self.actor,
            action_id=self.action.action_id, connection_id=self.connection.pk,
            previous_import_id=self.before.pk, current_import_id=self.after.pk)

    def test_comparison_requires_preexisting_source_and_reports_zero_without_causal_claim(self):
        with self.assertRaises(ValidationError):
            self.report()  # Retroactively imported pre-change data is not a preserved baseline.
        ImportRun.objects.filter(pk=self.before.pk).update(created_at=self.implemented_at - timedelta(days=2))
        report = self.report()
        self.assertEqual(report["method_version"], "gsc-csv-page-outcome-v1")
        self.assertEqual(report["before"]["import_id"], self.before.pk)
        self.assertEqual(report["after"]["import_id"], self.after.pk)
        self.assertEqual(report["search_metrics"]["clicks"]["state"], "zero_baseline")
        self.assertIsNone(report["search_metrics"]["clicks"]["relative_change"])
        self.assertEqual(report["search_metrics"]["impressions"]["absolute_change"], "50")
        self.assertEqual(report["conversion"]["state"], "unavailable_no_exact_origin_ga4_source")
        self.assertIn("not_causal", report["interpretation"])
        with self.assertRaises(ValidationError):
            compare_action_page_windows(project=self.project, actor=self.actor,
                action_id=self.action.action_id, connection_id=self.connection.pk,
                previous_import_id=self.before.pk, current_import_id=self.before.pk)

    def test_immutable_outcome_snapshot_dedupes_and_retains_noncausal_provenance(self):
        ImportRun.objects.filter(pk=self.before.pk).update(created_at=self.implemented_at - timedelta(days=2))
        inputs = dict(project=self.project, actor=self.actor, action_id=self.action.action_id,
                      connection_id=self.connection.pk, previous_import_id=self.before.pk,
                      current_import_id=self.after.pk)
        snapshot = record_page_outcome(**inputs)
        self.assertEqual(record_page_outcome(**inputs).pk, snapshot.pk)
        self.assertEqual(ActionOutcomeSnapshot.objects.count(), 1)
        self.assertEqual(snapshot.report["before"]["observation_id"], self.before.search_metrics.get().pk)
        self.assertIn("not_causal", snapshot.report["interpretation"])
        with self.assertRaises(ValidationError):
            record_page_outcome(**{**inputs, "current_import_id": self.before.pk})
        with self.assertRaises(ValidationError):
            snapshot.save()

    def test_partial_or_incompatible_windows_are_not_comparisons(self):
        ImportRun.objects.filter(pk=self.before.pk).update(created_at=self.implemented_at - timedelta(days=2))
        ImportRun.objects.filter(pk=self.after.pk).update(status=ImportRun.Status.PARTIALLY_SUCCEEDED,
                                                         coverage_state=ImportRun.CoverageState.PARTIAL)
        with self.assertRaises(ValidationError):
            self.report()
        ImportRun.objects.filter(pk=self.after.pk).update(status=ImportRun.Status.SUCCEEDED,
                                                         coverage_state=ImportRun.CoverageState.COMPLETE,
                                                         source_timezone="UTC")
        with self.assertRaises(ValidationError):
            self.report()
        ImportRun.objects.filter(pk=self.after.pk).update(source_timezone="America/Los_Angeles",
                                                         date_start=self.after.date_start + timedelta(days=1))
        with self.assertRaises(ValidationError):
            self.report()

    def test_outcome_api_requires_owner_csrf_and_preserves_historical_source_limits(self):
        ImportRun.objects.filter(pk=self.before.pk).update(created_at=self.implemented_at - timedelta(days=2))
        path = (f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}"
                f"/actions/{self.action.action_id}/outcomes/")
        owner = Client(enforce_csrf_checks=True)
        owner.force_login(self.actor)
        self.assertEqual(owner.get(path).json()["state"], "unavailable_no_comparison")
        details = {"connection_id": self.connection.pk, "previous_import_id": self.before.pk,
                   "current_import_id": self.after.pk}
        self.assertEqual(owner.post(path, data=json.dumps(details), content_type="application/json").status_code, 403)
        owner.get("/_allauth/browser/v1/auth/session")
        headers = {"HTTP_X_CSRFTOKEN": owner.cookies["csrftoken"].value}
        created = owner.post(path, data=json.dumps(details), content_type="application/json", **headers)
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(created.json()["outcome"]["report"]["search_metrics"]["clicks"]["state"], "zero_baseline")
        self.assertEqual(owner.post(path, data=json.dumps(details), content_type="application/json",
                                    **headers).json()["outcome"]["id"], created.json()["outcome"]["id"])
        viewer = get_user_model().objects.create_user("outcome-viewer@example.invalid", "Test passphrase 99!")
        EmailAddress.objects.create(user=viewer, email=viewer.email, verified=True, primary=True)
        OrganizationMembership.objects.create(organization=self.project.organization, user=viewer,
                                              role=MembershipRole.VIEWER)
        reader = Client()
        reader.force_login(viewer)
        self.assertEqual(reader.get(path).status_code, 200)
        self.assertEqual(reader.post(path, data=json.dumps(details), content_type="application/json").status_code, 403)
        IntegrationConnection.objects.filter(pk=self.connection.pk).update(state="disconnected")
        self.assertFalse(owner.get(path).json()["outcomes"][0]["source_current"])

    def test_crawl_technical_observations_require_real_prior_timestamp_and_never_prove_fix(self):
        def crawl(title, completed):
            job = JobRun.objects.create(organization=self.project.organization, project=self.project,
                actor=self.actor, handler="crawl_site", input_snapshot={"synthetic": True},
                method_version="http-crawl-v1")
            transition(job, JobStatus.RUNNING)
            transition(job, JobStatus.SUCCEEDED)
            run = CrawlRun.objects.create(job=job, organization=self.project.organization, project=self.project,
                page_limit=1, pages_attempted=1, pages_observed=1, completed_at=completed)
            page = CrawlPageSnapshot.objects.create(crawl_run=run, project=self.project,
                requested_url="https://outcome.example.invalid/services",
                final_url="https://outcome.example.invalid/services", status_code=200, title=title)
            return job, run, page

        before_job, before_run, before_page = crawl("Before title", self.implemented_at - timedelta(days=1))
        _after_job, after_run, _after_page = crawl("After title", timezone.now())
        args = dict(project=self.project, actor=self.actor, action_id=self.action.action_id,
                    previous_crawl_id=before_run.pk, current_crawl_id=after_run.pk)
        with self.assertRaises(ValidationError):
            compare_action_crawls(**args)
        JobRun.objects.filter(pk=before_job.pk).update(created_at=self.implemented_at - timedelta(days=4))
        CrawlRun.objects.filter(pk=before_run.pk).update(started_at=self.implemented_at - timedelta(days=3))
        CrawlPageSnapshot.objects.filter(pk=before_page.pk).update(observed_at=self.implemented_at - timedelta(days=2))
        report = compare_action_crawls(**args)
        self.assertIn("not_automatic_verification", report["interpretation"])
        self.assertEqual(report["urls"][0]["changes"]["title"],
                         {"previous": "Before title", "current": "After title"})
        snapshot = record_action_crawl_observations(**args)
        self.assertEqual(record_action_crawl_observations(**args).pk, snapshot.pk)
        self.assertEqual(ActionTechnicalOutcomeSnapshot.objects.count(), 1)
        with self.assertRaises(ValidationError):
            snapshot.save()
        path = (f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}"
                f"/actions/{self.action.action_id}/technical-outcomes/")
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.actor)
        self.assertEqual(client.get(path).json()["snapshots"][0]["report"]["method_version"],
                         "action-crawl-observation-v1")
        data = {"previous_crawl_id": before_run.pk, "current_crawl_id": after_run.pk}
        self.assertEqual(client.post(path, data=json.dumps(data), content_type="application/json").status_code, 403)
        client.get("/_allauth/browser/v1/auth/session")
        result = client.post(path, data=json.dumps(data), content_type="application/json",
                             HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.json()["snapshot"]["id"], snapshot.pk)
