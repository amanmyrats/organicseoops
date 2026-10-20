import json
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, reset_queries
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from config.test_foundations import TEST_STORAGES
from tenancy.models import Project, ProjectConfiguration
from tenancy.services import create_organization, create_project
from . import competitor_collection as lifecycle, competitor_page_formats_collection as collection
from . import competitor_formats_comparison as comparison
from . import test_competitor_collection as root_fixtures
from . import test_competitor_comparison as pair_fixtures
from . import test_competitor_page_formats_collection as fixtures
from .competitor_formats import COUNTS


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}))
class CompetitorFormatsComparisonTests(TransactionTestCase):
    setUp = fixtures.CompetitorPageFormatsCollectionTests.setUp
    queue = fixtures.CompetitorPageFormatsCollectionTests.queue
    transport = fixtures.CompetitorPageFormatsCollectionTests.transport

    def collected(self, key, body=fixtures.CompetitorPageFormatsCollectionTests.HTML, **changes):
        job = self.queue(key, **changes)
        fetcher = root_fixtures.CompetitorCollectionTests.fetcher(self, body=body)
        with patch("socket.create_connection", side_effect=AssertionError("No actual egress")):
            self.assertTrue(collection.execute_competitor_page_formats_collection(job.pk, fetcher=fetcher))
        job.refresh_from_db(); self.assertEqual(job.status, "succeeded", job.error_category)
        return job

    def compare(self, before, after, **changes):
        return comparison.compare_competitor_page_formats(**{**dict(project=self.project, actor=self.owner,
            previous_job_id=before.pk, current_job_id=after.pk), **changes})

    def test_genuine_private_original_signed_counts_independent_reader_no_write_network_or_raw_content(self):
        before = self.collected("elements-before", b'<p>Private customer prose</p><p>x</p><ul></ul><img src="private"/>')
        after = self.collected("elements-after", b'<p>private-contact@example.invalid</p><ol></ol><table></table>'
            b'<picture><img src="unretained"/></picture><img/><video></video><audio></audio>')
        reset_queries()
        with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No comparison fetch")), CaptureQueriesContext(connection) as queries:
            result = self.compare(before, after, actor=self.admin)
        self.assertGreater(len(queries), 0)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual((result["method_version"], result["collection_method"], result["url"], result["interpretation"]),
            (comparison.METHOD, collection.METHOD, self.data["url"], comparison.INTERPRETATION))
        self.assertEqual(set(result), {"method_version", "organization_id", "project_id", "source_current", "collection_method", "parser_method",
            "url", "source_sha256", "previous", "current", "comparable", "body_changed", "interpretation", "state", "count_deltas"})
        self.assertEqual(result["state"], "comparable_original_static_content_element_counts")
        self.assertTrue(result["comparable"]); self.assertTrue(result["body_changed"])
        self.assertEqual(result["count_deltas"], {"p": -1, "ul": -1, "ol": 1, "table": 1, "img": 1, "picture": 1, "video": 1, "audio": 1})
        self.assertEqual(result["previous"]["evidence"], before.output["evidence"])
        self.assertEqual(result["current"]["evidence"], after.output["evidence"])
        self.assertEqual(result["previous"]["robots"], before.output["robots"])
        self.assertEqual(result["source_sha256"], before.config_snapshot["binding"]["source_sha256"])
        for private in ("private-contact", '"unretained"', self.owner.email, "artifact_id", "Private customer prose"):
            self.assertNotIn(private, json.dumps(result))
        result["previous"]["evidence"]["counts"]["p"] = 999
        self.assertEqual(self.compare(before, after)["previous"]["evidence"]["counts"]["p"], 2)
        identical = self.collected("elements-identical", b'<p>Private customer prose</p><p>x</p><ul></ul><img src="private"/>')
        same = self.compare(before, identical)
        self.assertFalse(same["body_changed"]); self.assertEqual(same["count_deltas"], dict.fromkeys(COUNTS, 0))

    def test_observed_empty_zero_unavailable_whole_null_and_irrelevant_metadata_are_distinct(self):
        before = self.collected("empty-elements", b"<title>Empty</title>")
        for index, (body, comparable) in enumerate(((b"<title>Still empty</title>", True),
            (b"<template>Unclosed", False), (b"<p>x</p>" * 1001, False),
            (b"<title>" + b"x" * 501 + b"</title>", True),
            (b"<script><p>hidden</p></script><template><img/></template>", True))):
            result = self.compare(before, self.collected("coverage-elements-" + str(index), body))
            self.assertEqual(result["comparable"], comparable)
            if comparable:
                self.assertEqual(result["count_deltas"], dict.fromkeys(COUNTS, 0))
            else:
                self.assertEqual(result["state"], "incomparable_unavailable_content_element_counts")
                self.assertIsNone(result["count_deltas"])
                self.assertEqual(result["current"]["evidence"]["counts"], dict.fromkeys(COUNTS))
        unavailable = self.collected("unavailable-before", b"<template>Unclosed")
        observed = self.collected("observed-after", b"<p>Observed</p>")
        self.assertIsNone(self.compare(unavailable, observed)["count_deltas"])

    def test_exact_ids_original_actor_uri_dates_current_project_and_closed_other_families(self):
        before = self.collected("scope-elements-before"); after = self.collected("scope-elements-after")
        for first, second in ((before, before), (after, before)):
            with self.assertRaises(ValidationError): self.compare(first, second)
        for value in (True, 0, -1, 2**53, str(before.pk), None):
            with self.assertRaises(ValidationError): self.compare(before, after, previous_job_id=value)
        other_project = Project.objects.create(organization=self.organization, name="Other owned project",
            canonical_origin="https://other-owned.example.invalid")
        other_org = create_organization(user=self.foreign, name="Foreign organization")
        foreign_project = create_project(organization=other_org, user=self.foreign,
            name="Foreign project", canonical_origin="https://foreign-owned.example.invalid")
        for changes in ({"actor": self.foreign}, {"project": other_project}, {"project": foreign_project, "actor": self.foreign}):
            with self.assertRaises(PermissionDenied): self.compare(before, after, **changes)
        for other in (self.collected("different-elements-uri", data={**self.data, "url": self.data["url"] + "-other"}),
            self.collected("different-elements-actor", actor=self.admin)):
            with self.assertRaises(ValidationError): self.compare(before, other)
        from .competitor_comparison import compare_competitor_roots
        from .competitor_page_comparison import compare_competitor_pages
        from .competitor_schema_comparison import compare_competitor_schema_roots
        from .competitor_links_comparison import compare_competitor_links_roots
        from .competitor_headings_comparison import compare_competitor_page_headings
        from .competitor_destinations_comparison import compare_competitor_page_destinations
        from .competitor_dates_comparison import compare_competitor_page_dates
        from .competitor_synthesis import read_competitor_synthesis_source
        from .competitor_headings_synthesis import read_competitor_headings_synthesis_source
        pair = dict(project=self.project, actor=self.owner, previous_job_id=before.pk, current_job_id=after.pk)
        with patch.object(lifecycle, "read_project_artifact", side_effect=AssertionError("No other-family artifact")):
            for compare in (compare_competitor_roots, compare_competitor_pages, compare_competitor_schema_roots,
                compare_competitor_links_roots, compare_competitor_page_headings, compare_competitor_page_destinations, compare_competitor_page_dates):
                with self.assertRaises(PermissionDenied): compare(**pair)
            for source in (read_competitor_synthesis_source, read_competitor_headings_synthesis_source):
                with self.assertRaises(PermissionDenied): source(**pair, ai_processing_permission=True)
        for handler in (value for value in lifecycle.COMPETITOR_HANDLERS if value not in {collection.HANDLER, lifecycle.LIGHTHOUSE_HANDLER}):
            page = handler in {"collect_competitor_page", "collect_competitor_page_headings", "collect_competitor_page_destinations", "collect_competitor_page_dates"}
            other = root_fixtures.CompetitorCollectionTests.queue(self, "actual-elements-" + handler, handler=handler,
                data=self.data if page else {key: value for key, value in self.data.items() if key != "url"})
            with patch("socket.create_connection", side_effect=AssertionError("No actual egress")):
                self.assertTrue(lifecycle.execute_competitor_collection(other.pk,
                    fetcher=root_fixtures.CompetitorCollectionTests.fetcher(self), handler=handler))
            other.refresh_from_db(); self.assertEqual(other.status, "succeeded")
            with patch.object(lifecycle, "read_project_artifact", side_effect=AssertionError("No other-family artifact")), self.assertRaises(PermissionDenied):
                self.compare(before, other)
        ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[])
        with self.assertRaises((PermissionDenied, ValidationError)): self.compare(before, after)

    test_late_first_pair_row_source_caller_or_natural_expiry_during_second_readback_withholds_both = pair_fixtures.CompetitorComparisonTests.test_late_first_pair_row_source_caller_or_natural_expiry_during_second_readback_withholds_both
    test_last_second_metadata_return_fences_both_original_sources_and_independent_caller = pair_fixtures.CompetitorComparisonTests.test_last_second_metadata_return_fences_both_original_sources_and_independent_caller
    test_first_original_cancellation_during_last_second_source_read_withholds_whole_private_pair = pair_fixtures.CompetitorComparisonTests.test_first_original_cancellation_during_last_second_source_read_withholds_whole_private_pair
    test_last_dated_pair_source_first_metadata_status_usage_and_both_cancellations_withhold = pair_fixtures.CompetitorComparisonTests.test_last_dated_pair_source_first_metadata_status_usage_and_both_cancellations_withhold
