from unittest.mock import patch
from datetime import timedelta
from zoneinfo import ZoneInfo

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from jobs.services import execute_job
from tenancy.models import Project
from tenancy.services import create_organization, create_project, update_project_configuration

from .models import ImportRun
from .query_growth import query_growth_signals
from .search_console import queue_search_console_csv_import
from .services import create_connection


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/csv"}))
class QueryGrowthTests(TransactionTestCase):
    def setUp(self):
        dispatch = patch("jobs.services.dispatch_pending", return_value=False)
        self.addCleanup(dispatch.stop)
        dispatch.start()
        users = get_user_model().objects
        self.owner = users.create_user("growth-owner@example.com", password="test-password")
        self.outsider = users.create_user("growth-outsider@example.com", password="test-password")
        for user in (self.owner, self.outsider):
            EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
        organization = create_organization(user=self.owner, name="Growth organization")
        self.project = create_project(organization=organization, user=self.owner, name="Growth site",
                                      canonical_origin="https://growth.example")
        self.connection = create_connection(
            project=self.project, user=self.owner, provider="google_search_console",
            external_property_id="https://growth.example", capabilities=["csv_import", "query_metrics"],
            available_dimensions=["query"], source_semantics="search_console_performance",
            source_semantics_version="csv-v1", timezone="America/Los_Angeles",
        )
        self.end = timezone.now().astimezone(ZoneInfo("America/Los_Angeles")).date() - timedelta(days=2)

    def import_csv(self, content, *, start, end, connection=None):
        job = queue_search_console_csv_import(
            connection=connection or self.connection, user=self.owner, content=content,
            date_start=start, date_end=end,
        )
        self.assertTrue(execute_job(job.pk))
        return ImportRun.objects.get(job=job)

    def test_growth_keeps_windows_property_and_hidden_coverage_explicit(self):
        previous = self.import_csv(
            b"Top queries,Clicks,Impressions,CTR,Position\nknown topic,3,30,10%,3\nzero row,0,10,0%,4\n",
            start=self.end - timedelta(days=13), end=self.end - timedelta(days=7),
        )
        current = self.import_csv(
            b"Top queries,Clicks,Impressions,CTR,Position\nknown topic,6,45,13.3%,2\nzero row,2,12,16.7%,3\nnew topic,2,20,10%,4\n",
            start=self.end - timedelta(days=6), end=self.end,
        )
        update_project_configuration(project=self.project, user=self.owner, expected_revision=0,
                                     changes={"target_country": "Türkiye", "target_languages": ["tr"]})
        result = query_growth_signals(project=self.project, user=self.owner, connection=self.connection,
                                      previous_import_id=previous.pk, current_import_id=current.pk)
        self.assertEqual((result["provider"], result["property"]), ("google_search_console", "https://growth.example"))
        self.assertEqual((result["market"], result["languages"]), ("Türkiye", ["tr"]))
        self.assertEqual(result["coverage"]["hidden_queries"], "unknown")
        self.assertEqual(result["coverage"]["source_completeness"], "provider_export_unknown")
        self.assertEqual((result["coverage"]["missing_previous_queries"], result["coverage"]["ambiguous_zero_rows"]), (1, 1))
        self.assertEqual([item["query"] for item in result["candidates"]], ["known topic"])
        self.assertEqual(result["candidates"][0]["click_relative_change"], 1)
        self.assertEqual(result["candidates"][0]["click_change"], 3)
        self.assertEqual(result["candidates"][0]["previous_observation_id"], previous.search_metrics.get(query="known topic").pk)
        with self.assertRaises(PermissionDenied):
            query_growth_signals(project=self.project, user=self.outsider, connection=self.connection,
                                 previous_import_id=previous.pk, current_import_id=current.pk)

    def test_partial_or_cross_property_exports_cannot_be_compared(self):
        previous = self.import_csv(
            b"Top queries,Clicks,Impressions,CTR,Position\nknown,1,10,10%,3\n",
            start=self.end - timedelta(days=13), end=self.end - timedelta(days=7),
        )
        partial = self.import_csv(
            b"Top queries,Clicks,Impressions,CTR,Position\nknown,2,20,10%,3\nbad,invalid,10,0%,1\n",
            start=self.end - timedelta(days=6), end=self.end,
        )
        with self.assertRaises(ValidationError):
            query_growth_signals(project=self.project, user=self.owner, connection=self.connection,
                                 previous_import_id=previous.pk, current_import_id=partial.pk)
        other_project = Project.objects.create(
            organization=self.project.organization,
            name="Other growth site",
            canonical_origin="https://other-growth.example",
        )
        other_connection = create_connection(
            project=other_project, user=self.owner, provider="google_search_console",
            external_property_id="https://other-growth.example", capabilities=["csv_import", "query_metrics"],
            available_dimensions=["query"], source_semantics="search_console_performance",
            source_semantics_version="csv-v1",
        )
        with self.assertRaises(PermissionDenied):
            query_growth_signals(project=self.project, user=self.owner, connection=other_connection,
                                 previous_import_id=previous.pk, current_import_id=partial.pk)

    def test_observed_changes_exclude_missing_and_zero_and_keep_position_separate(self):
        previous = self.import_csv(
            b"Top queries,Clicks,Impressions,CTR,Position\nsteady,5,100,5%,8\nzero,0,40,0%,5\n",
            start=self.end - timedelta(days=13), end=self.end - timedelta(days=7))
        current = self.import_csv(
            b"Top queries,Clicks,Impressions,CTR,Position\nsteady,3,120,2.5%,11\nzero,2,50,4%,4\nnew,4,60,6.67%,3\n",
            start=self.end - timedelta(days=6), end=self.end)
        report = query_growth_signals(project=self.project, user=self.owner, connection=self.connection,
                                      previous_import_id=previous.pk, current_import_id=current.pk)
        self.assertEqual([(item["metric"], item["direction"]) for item in report["observed_changes"]],
                         [("clicks", "decreased"), ("impressions", "increased"), ("average_position", "worsened")])
        self.assertEqual(report["observed_changes"][0]["previous_observation_id"],
                         previous.search_metrics.get(query="steady").pk)
        self.assertEqual(report["coverage"]["missing_previous_queries"], 1)
        self.assertEqual(report["coverage"]["ambiguous_zero_rows"], 1)
