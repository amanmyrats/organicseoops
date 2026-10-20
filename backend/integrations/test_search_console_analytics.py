from datetime import date
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from jobs.models import JobCancellation, JobRun, JobStatus
from tenancy.models import Project, ProjectOriginVerification
from tenancy.services import create_organization, create_project, update_project

from .google_tokens import SCOPE
from .models import GoogleOAuthGrant, IntegrationConnection, SearchAnalyticsPageSnapshot
from .search_console_analytics import parse_search_analytics_page, parse_search_analytics_query_page, record_search_analytics_page
from .services import create_connection


class FinalSearchAnalyticsPageTests(SimpleTestCase):
    day = date(2026, 9, 20)
    property_origin = "https://owned.example"

    def parse(self, rows, *, dimension="query", start_row=0, **extra):
        return parse_search_analytics_page(
            response={"rows": rows, "responseAggregationType": "byPage" if dimension == "page" else "byProperty", **extra},
            day=self.day, dimension=dimension, property_origin=self.property_origin, start_row=start_row,
        )

    def test_final_top_rows_preserve_source_semantics_and_unknown_coverage(self):
        row = {"keys": ["actual query"], "clicks": 2.0, "impressions": 8, "ctr": .25, "position": 4.125}
        result = self.parse([row])
        self.assertEqual(result["observations"], [{"key": "actual query", "clicks": 2,
                                                    "impressions": 8, "ctr": "0.25", "position": "4.125"}])
        self.assertEqual((result["source_coverage"], result["next_start_row"], result["truncated"]),
                         ("top_rows_only", None, False))
        full = self.parse([{"keys": [str(index)], "clicks": 0, "impressions": 1,
                            "ctr": 0, "position": 0} for index in range(100)])
        self.assertEqual(full["next_start_row"], 100)
        self.assertTrue(self.parse([{"keys": [str(index)], "clicks": 0, "impressions": 1,
                                    "ctr": 0, "position": 0} for index in range(100)], start_row=100)["truncated"])
        self.assertEqual(self.parse([], dimension="date")["observations"], [])

    def test_page_queries_and_foreign_properties_are_omitted_without_leaking_secrets(self):
        rows = [{"keys": [url], "clicks": 1, "impressions": 2, "ctr": .5, "position": 1}
                for url in ("https://owned.example/known", "https://owned.example/?code=PRIVATE_SECRET",
                            "https://other.example/", "https://owned.example/reset#fragment")]
        result = self.parse(rows, dimension="page")
        self.assertEqual(result["omitted_pages"], 3)
        self.assertEqual([item["key"] for item in result["observations"]], ["https://owned.example/known"])
        self.assertNotIn("PRIVATE_SECRET", str(result))
        self.assertEqual(result["source_coverage"], "top_rows_only")

    def test_malformed_or_nonfinal_metrics_and_aggregation_fail_closed(self):
        row = {"keys": ["query"], "clicks": 1, "impressions": 2, "ctr": .5, "position": 3}
        for override in ({"clicks": True}, {"clicks": -1}, {"clicks": 3}, {"ctr": float("nan")},
                         {"position": float("inf")}, {"impressions": 1.5}, {"keys": ["query", "page"]}):
            with self.subTest(override=override), self.assertRaises(ValidationError):
                self.parse([{**row, **override}])
        for extras in ({"responseAggregationType": "byPage"}, {"metadata": {"first_incomplete_date": "2026-09-20"}}):
            with self.subTest(extras=extras), self.assertRaises(ValidationError):
                self.parse([row], **extras)
        with self.assertRaises(ValidationError):
            self.parse([row, row])
        with self.assertRaises(ValidationError):
            self.parse([{**row, "keys": ["2026-09-19"]}], dimension="date")


    def test_domain_pages_only_use_explicit_exact_origins_and_never_store_sibling_urls(self):
        rows = [{"keys": [url], "clicks": 1, "impressions": 2, "ctr": .5, "position": 3}
                for url in ("https://owned.example/page", "https://www.owned.example/sibling",
                            "http://owned.example/other-protocol", "https://owned.example.evil/outside",
                            "https://owned.example/?code=PRIVATE_SECRET")]
        response = {"responseAggregationType": "byPage", "rows": rows}
        result = parse_search_analytics_page(response=response, day=self.day, dimension="page",
                                             property_origin="sc-domain:owned.example", start_row=0,
                                             approved_origins=["https://owned.example"])
        self.assertEqual(result["approved_origins"], ["https://owned.example"])
        self.assertEqual(result["source_coverage"], "top_rows_only_domain_page_filtered")
        self.assertEqual((result["rows_returned"], result["omitted_pages"], result["truncated"]), (1, None, None))
        self.assertIsNone(result["next_start_row"])
        self.assertEqual([row["key"] for row in result["observations"]], ["https://owned.example/page"])
        self.assertNotIn("PRIVATE_SECRET", str(result))
        self.assertNotIn("www.owned.example", str(result))
        for dimension in ("date", "query"):
            with self.subTest(dimension=dimension), self.assertRaises(ValidationError):
                parse_search_analytics_page(response=response, day=self.day, dimension=dimension,
                                             property_origin="sc-domain:owned.example", start_row=0,
                                             approved_origins=["https://owned.example"])
        for invalid in (None, [], ["https://unrelated.example"], ["https://owned.example.evil"]):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                parse_search_analytics_page(response=response, day=self.day, dimension="page",
                                             property_origin="sc-domain:owned.example", start_row=0,
                                              approved_origins=invalid)
        with self.assertRaises(ValidationError):
            parse_search_analytics_page(response=response, day=self.day, dimension="page",
                                        property_origin="sc-domain:owned.example", start_row=100,
                                        approved_origins=["https://owned.example"])


class PairedSearchAnalyticsDecoderTests(SimpleTestCase):
    day = date(2026, 9, 20)
    origin = "https://owned.example"

    def row(self, query="Actual query", page="https://owned.example/service", **changes):
        return {**{"keys": [query, page], "clicks": 2.0, "impressions": 8, "ctr": .25, "position": 4.125}, **changes}

    def parse(self, rows, **changes):
        return parse_search_analytics_query_page(**{**dict(response={"rows": rows, "responseAggregationType": "byPage"},
            day=self.day, property_origin=self.origin, start_row=0), **changes})

    def test_actual_pairs_preserve_query_case_origin_metrics_and_honest_limits_without_network(self):
        with patch("socket.create_connection", side_effect=AssertionError("No network")):
            result = self.parse([self.row(), self.row(page=self.origin + "/other"), self.row(query="actual query"),
                self.row(query="Özgün Türkçe sorgu", clicks=0, impressions=0, ctr=0, position=0)])
        self.assertEqual(result["dimensions"], ["query", "page"])
        self.assertEqual(result["response_aggregation"], "byPage")
        self.assertEqual(result["requested_aggregation"], "auto")
        self.assertEqual(result["observations"][0], {"query": "Actual query", "page": self.origin + "/service",
            "clicks": 2, "impressions": 8, "ctr": "0.25", "position": "4.125"})
        self.assertEqual([row["query"] for row in result["observations"]], ["Actual query", "Actual query", "actual query", "Özgün Türkçe sorgu"])
        self.assertEqual((result["timezone"], result["provider_completeness"], result["hidden_queries"]),
            ("America/Los_Angeles", "not_established", "unknown"))
        self.assertIn("not_proven_cannibalization", result["interpretation"])

    def test_unsafe_foreign_page_keys_are_omitted_without_retaining_their_query_or_url(self):
        rows = [self.row("omit-private-query", page) for page in (
            "https://other.example/private", "http://owned.example/service", "https://owned.example.evil/service",
            "https://owned.example/reset?code=PRIVATE_SECRET", "https://owned.example/reset#PRIVATE_FRAGMENT",
            "https://user:password@owned.example/service", "https://owned.example:444/service")]
        result = self.parse([self.row(), *rows])
        self.assertEqual(result["omitted_pages"], 7)
        self.assertEqual(result["rows_returned"], 8)
        self.assertEqual(len(result["observations"]), 1)
        for secret in ("omit-private-query", "PRIVATE_SECRET", "PRIVATE_FRAGMENT", "password", "other.example", "owned.example.evil"):
            self.assertNotIn(secret, str(result))
        for property_id in ("sc-domain:owned.example", "https://owned.example/", "https://owned.example/path"):
            with self.subTest(property_id=property_id), self.assertRaises(ValidationError):
                self.parse([self.row()], property_origin=property_id)

    def test_wrong_grain_aggregation_nonfinite_metrics_duplicates_and_byte_bounds_fail_closed(self):
        for changes in ({"keys": ["query"]}, {"keys": ["query", self.origin, "device"]}, {"keys": [True, self.origin]},
            {"keys": ["", self.origin]}, {"keys": ["x" * 1001, self.origin]}, {"keys": ["query\nidentity", self.origin]},
            {"clicks": True}, {"clicks": -1}, {"clicks": 10}, {"impressions": 1.5}, {"ctr": float("nan")},
            {"position": float("inf")}, {"ctr": 1.1}, {"position": -1}, {"impressions": 2**63}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.parse([self.row(**changes)])
        for response in ({"rows": [self.row()]}, {"rows": [self.row()], "responseAggregationType": "byProperty"},
            {"rows": [self.row()], "responseAggregationType": "auto"},
            {"rows": [self.row()], "responseAggregationType": "byPage", "metadata": {"first_incomplete_date": self.day.isoformat()}},
            {"rows": [self.row()], "responseAggregationType": "byPage", "metadata": []},
            {"rows": [self.row()], "responseAggregationType": "byPage", "extra": "x" * (256 * 1024)}):
            with self.subTest(response_type=type(response)), self.assertRaises(ValidationError):
                self.parse([], response=response)
        with self.assertRaises(ValidationError):
            self.parse([self.row(), self.row()])
        with self.assertRaises(ValidationError):
            self.parse([self.row(str(index)) for index in range(101)])
        for bad in (True, -1, 1, 200, "100"):
            with self.subTest(start_row=bad), self.assertRaises(ValidationError):
                self.parse([], start_row=bad)
        with self.assertRaises(ValidationError):
            self.parse([], day=self.day.isoformat())

    def test_bounded_paging_and_empty_results_never_assert_complete_search_or_zero_demand(self):
        rows = [self.row(str(index)) for index in range(100)]
        first = self.parse(rows)
        self.assertEqual(first["next_start_row"], 100)
        second = self.parse(rows, start_row=100)
        self.assertTrue(second["truncated"])
        self.assertIsNone(second["next_start_row"])
        empty = self.parse([], response={})
        self.assertEqual(empty["observations"], [])
        self.assertIsNone(empty["response_aggregation"])
        self.assertEqual(empty["provider_completeness"], "not_established")
        self.assertEqual(self.parse([self.row(str(index)) for index in range(99)], start_row=100)["hidden_queries"], "unknown")


class SearchAnalyticsEvidenceTests(TestCase):
    day = date(2026, 9, 20)

    def setUp(self):
        self.user = get_user_model().objects.create_user("evidence@example.com", password="test-password")
        EmailAddress.objects.create(user=self.user, email=self.user.email, primary=True, verified=True)
        org = create_organization(user=self.user, name="Evidence organization")
        self.project = create_project(organization=org, user=self.user, name="Evidence project",
                                      canonical_origin="https://evidence.example")
        self.connection = create_connection(
            project=self.project, user=self.user, provider="google_search_console",
            external_property_id="https://evidence.example/", capabilities=["api_sync", "query_metrics"],
            available_dimensions=["query"], source_semantics="search_console_performance",
            source_semantics_version="gsc-performance-v1", timezone="America/Los_Angeles",
        )
        self.grant = GoogleOAuthGrant.objects.create(
            organization=org, project=self.project, actor=self.user, encrypted_refresh_token="v1:fixture-only",
            scope=SCOPE, state=GoogleOAuthGrant.State.ACTIVE, verified_at=timezone.now(),
            selected_property_id=self.connection.external_property_id, selected_site_url="https://evidence.example/",
        )
        self.connection.credential_reference = self.grant.credential_reference
        self.connection.save()
        self.job = JobRun.objects.create(
            organization=org, project=self.project, actor=self.user, handler="sync_search_console",
            method_version="search-console-api-v1",
            input_snapshot={"connection_id": self.connection.pk, "grant_id": self.grant.pk,
                            "day": self.day.isoformat(), "dimensions": ["query"]},
            config_snapshot={"grant_revision": 0, "property_id": self.connection.external_property_id},
        )
        self.job.status = JobStatus.RUNNING
        self.job.save(update_fields=["status", "updated_at"])
        self.response = {"responseAggregationType": "byProperty", "rows": [
            {"keys": ["owned query"], "clicks": 2, "impressions": 4, "ctr": 0.5, "position": 3},
        ]}

    def record(self, **overrides):
        return record_search_analytics_page(**{
            "job": self.job, "connection": self.connection, "grant": self.grant, "day": self.day,
            "dimension": "query", "start_row": 0, "response": self.response, **overrides,
        })

    def test_committed_api_page_is_immutable_and_same_job_replay_only(self):
        page = self.record()
        self.assertEqual(self.record().pk, page.pk)
        self.assertEqual(SearchAnalyticsPageSnapshot.objects.count(), 1)
        self.assertEqual(page.result["source_coverage"], "top_rows_only")
        self.assertEqual(page.result["observations"][0]["key"], "owned query")
        self.assertEqual(page.external_property_id, self.connection.external_property_id)
        with self.assertRaises(ValidationError):
            self.record(response={"responseAggregationType": "byProperty", "rows": []})
        with self.assertRaises(ValidationError):
            page.save()
        with self.assertRaises(ValidationError):
            self.record(day=date(2026, 9, 19))

    def test_revoked_scope_cancellation_and_foreign_grant_cannot_commit(self):
        other = Project.objects.create(
            organization=self.project.organization, name="Other", canonical_origin="https://other-evidence.example",
        )
        foreign_grant = GoogleOAuthGrant.objects.create(
            organization=other.organization, project=other, actor=self.user, scope=SCOPE,
            encrypted_refresh_token="v1:fixture-only", verified_at=timezone.now(),
        )
        with self.assertRaises(GoogleOAuthGrant.DoesNotExist):
            self.record(grant=foreign_grant)
        JobCancellation.objects.create(job=self.job, requested_by=self.user)
        with self.assertRaises(PermissionDenied):
            self.record()
        JobCancellation.objects.filter(job=self.job).delete()
        update_project(project=self.project, user=self.user, canonical_origin="https://new-evidence.example")
        with self.assertRaises(ValidationError):
            self.record()
        self.assertFalse(SearchAnalyticsPageSnapshot.objects.exists())

    def test_domain_page_snapshot_filters_sibling_urls_and_stops_after_origin_revoke(self):
        verification = ProjectOriginVerification.objects.create(
            organization=self.project.organization, project=self.project, origin=self.project.canonical_origin,
            challenge_digest="a" * 64, state=ProjectOriginVerification.State.VERIFIED,
            verified_at=timezone.now(),
        )
        domain = "sc-domain:evidence.example"
        grant = GoogleOAuthGrant.objects.create(
            organization=self.project.organization, project=self.project, actor=self.user, scope=SCOPE,
            encrypted_refresh_token="v1:fixture-only", state=GoogleOAuthGrant.State.ACTIVE,
            verified_at=timezone.now(), selected_property_id=domain, selected_site_url=domain,
            selected_origins=[self.project.canonical_origin],
        )
        connection = IntegrationConnection(
            project=self.project, provider="google_search_console", external_property_id=domain,
            credential_reference=grant.credential_reference, capabilities=["api_sync", "page_metrics"],
            available_dimensions=["page"], source_semantics="search_console_domain_pages",
            source_semantics_version="gsc-domain-page-v1", timezone="America/Los_Angeles",
        )
        connection.save()
        job = JobRun.objects.create(
            organization=self.project.organization, project=self.project, actor=self.user,
            handler="sync_search_console", method_version="search-console-api-v1",
            input_snapshot={"connection_id": connection.pk, "grant_id": grant.pk, "day": self.day.isoformat(),
                            "dimensions": ["page"]},
            config_snapshot={"grant_revision": grant.revision, "property_id": domain,
                             "approved_origins": [self.project.canonical_origin],
                             "scope_strategy": "domain-page-v1"},
        )
        job.status = JobStatus.RUNNING
        job.save(update_fields=["status", "updated_at"])
        response = {"responseAggregationType": "byPage", "rows": [
            {"keys": [url], "clicks": 1, "impressions": 2, "ctr": .5, "position": 3}
            for url in ("https://evidence.example/owned", "https://m.evidence.example/sibling")
        ]}
        page = record_search_analytics_page(job=job, connection=connection, grant=grant, day=self.day,
                                            dimension="page", start_row=0, response=response)
        self.assertEqual(page.result["observations"][0]["key"], "https://evidence.example/owned")
        self.assertEqual((page.result["omitted_pages"], page.result["source_coverage"]),
                         (None, "top_rows_only_domain_page_filtered"))
        self.assertNotIn("m.evidence.example", str(page.result))
        ProjectOriginVerification.objects.filter(pk=verification.pk).update(
            state=ProjectOriginVerification.State.REVOKED, revoked_at=timezone.now())
        with self.assertRaises(ValidationError):
            record_search_analytics_page(job=job, connection=connection, grant=grant, day=self.day,
                                         dimension="page", start_row=100, response=response)
        self.assertEqual(SearchAnalyticsPageSnapshot.objects.filter(job=job).count(), 1)
