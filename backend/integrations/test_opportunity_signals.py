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
from tenancy.services import create_organization, create_project, update_project, update_project_configuration

from .models import ImportRun
from .opportunity_signals import METHOD, search_opportunity_signals
from .search_console import queue_search_console_csv_import
from .services import create_connection


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/csv"}))
class SearchOpportunitySignalTests(TransactionTestCase):
    def setUp(self):
        dispatch = patch("jobs.services.dispatch_pending", return_value=False)
        self.addCleanup(dispatch.stop)
        dispatch.start()
        users = get_user_model().objects
        self.owner = users.create_user("opportunity-owner@example.com", password="test-password")
        self.foreign = users.create_user("opportunity-foreign@example.com", password="test-password")
        for user in (self.owner, self.foreign):
            EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
        org = create_organization(user=self.owner, name="Candidate org")
        self.project = create_project(organization=org, user=self.owner, name="Candidate project",
                                      canonical_origin="https://candidate.example")
        self.connection = create_connection(project=self.project, user=self.owner, provider="google_search_console",
            external_property_id="https://candidate.example/", capabilities=["csv_import", "query_metrics", "page_metrics"],
            available_dimensions=["query", "page"], source_semantics="search_console_performance",
            source_semantics_version="csv-v1", timezone="America/Los_Angeles")
        self.end = timezone.now().astimezone(ZoneInfo("America/Los_Angeles")).date() - timedelta(days=3)

    def import_csv(self, content):
        job = queue_search_console_csv_import(connection=self.connection, user=self.owner, content=content,
            date_start=self.end - timedelta(days=6), date_end=self.end)
        self.assertTrue(execute_job(job.pk))
        return ImportRun.objects.get(job=job)

    def test_query_and_page_candidates_keep_source_evidence_and_separate_grains(self):
        update_project_configuration(project=self.project, user=self.owner, expected_revision=0,
                                     changes={"target_country": "Türkiye", "target_languages": ["tr"]})
        query = self.import_csv(
            b"Top queries,Clicks,Impressions,CTR,Position\n"
            b"middle query,2,200,1%,10\n"
            b"low ctr query,2,200,1%,25\n"
            b"zero ambiguous,0,200,0%,8\n"
            b"outside position,10,50,20%,21\n")
        result = search_opportunity_signals(project=self.project, user=self.owner, connection=self.connection,
                                            import_id=query.pk)
        self.assertEqual((result["method"], result["property"], result["market"], result["languages"]),
                         (METHOD, "https://candidate.example", "Türkiye", ["tr"]))
        self.assertEqual(result["coverage"]["provider_top_rows"], "incomplete_unknown")
        self.assertEqual(result["coverage"]["omissions"]["ambiguous_zero"], 1)
        self.assertEqual(result["dimension"], "query")
        self.assertEqual({(item["query"], item["detector"]) for item in result["candidates"]}, {
            ("middle query", "web_position_4_to_20_candidate"),
            ("middle query", "web_high_impressions_low_ctr_candidate"),
            ("low ctr query", "web_high_impressions_low_ctr_candidate"),
        })
        self.assertTrue(all(item["page"] is None for item in result["candidates"]))
        self.assertEqual(search_opportunity_signals(project=self.project, user=self.owner,
            connection=self.connection, import_id=query.pk), result)
        self.client.force_login(self.owner)
        path = (f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}"
                f"/sources/{self.connection.pk}/imports/{query.pk}/opportunities/")
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response.json(), result)
        page = self.import_csv(b"Top pages,Clicks,Impressions,CTR,Position\nhttps://candidate.example/page,2,200,1%,8\n")
        page_result = search_opportunity_signals(project=self.project, user=self.owner,
                                                  connection=self.connection, import_id=page.pk)
        self.assertEqual(page_result["dimension"], "page")
        self.assertEqual(page_result["candidates"][0]["page"], "https://candidate.example/page")
        self.assertTrue(all(item["query"] is None for item in page_result["candidates"]))
        self.assertNotEqual(result["window"]["import_id"], page_result["window"]["import_id"])

    def test_partial_import_and_foreign_or_revoked_access_cannot_generate_candidates(self):
        run = self.import_csv(b"Top queries,Clicks,Impressions,CTR,Position\nknown,2,200,1%,8\n")
        with self.assertRaises(PermissionDenied):
            search_opportunity_signals(project=self.project, user=self.foreign,
                                        connection=self.connection, import_id=run.pk)
        self.client.force_login(self.foreign)
        path = (f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}"
                f"/sources/{self.connection.pk}/imports/{run.pk}/opportunities/")
        self.assertEqual(self.client.get(path).status_code, 404)
        bad = self.import_csv(b"Top queries,Clicks,Impressions,CTR,Position\nknown,2,200,1%,8\nbad,nope,200,1%,8\n")
        with self.assertRaises(ValidationError):
            search_opportunity_signals(project=self.project, user=self.owner,
                                        connection=self.connection, import_id=bad.pk)
        self.client.force_login(self.owner)
        bad_path = path.replace(f"/{run.pk}/opportunities/", f"/{bad.pk}/opportunities/")
        self.assertEqual(self.client.get(bad_path).status_code, 409)
        update_project(project=self.project, user=self.owner, canonical_origin="https://changed.example")
        with self.assertRaises((PermissionDenied, ValidationError)):
            search_opportunity_signals(project=self.project, user=self.owner,
                                        connection=self.connection, import_id=run.pk)
