import json
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from config.test_foundations import TEST_STORAGES
from tenancy.models import Project, ProjectConfiguration
from . import competitor_collection as lifecycle, competitor_schema_collection as collection
from . import competitor_schema_comparison as comparison
from . import test_competitor_collection as root_fixtures
from . import test_competitor_comparison as pair_fixtures
from . import test_competitor_schema_collection as fixtures
from .competitor_comparison import compare_competitor_roots
from .competitor_page_comparison import compare_competitor_pages
from .competitor_synthesis import read_competitor_synthesis_source


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}))
class CompetitorSchemaComparisonTests(TransactionTestCase):
    setUp = fixtures.CompetitorSchemaCollectionTests.setUp
    queue = fixtures.CompetitorSchemaCollectionTests.queue
    transport = fixtures.CompetitorSchemaCollectionTests.transport

    def collected(self, key, body=b'<script type="application/ld+json">{"@type":["Article","PrivateUnknown"]}</script>', **changes):
        job = self.queue(key, **changes)
        fetcher = root_fixtures.CompetitorCollectionTests.fetcher(self, body=body)
        with patch("socket.create_connection", side_effect=AssertionError("No actual egress")):
            self.assertTrue(collection.execute_competitor_schema_collection(job.pk, fetcher=fetcher))
        job.refresh_from_db(); self.assertEqual(job.status, "succeeded", job.error_category)
        return job

    def compare(self, before, after, **changes):
        return comparison.compare_competitor_schema_roots(**{**dict(project=self.project, actor=self.owner,
            previous_job_id=before.pk, current_job_id=after.pk), **changes})

    def test_genuine_private_dated_lexical_labels_counts_independent_reader_no_write_network_or_raw_content(self):
        before = self.collected("schema-before")
        after = self.collected("schema-after", b'<script type="application/ld+json">{"@type":["https://schema.org/WebPage","VideoObject"],"email":"private@example.invalid"}</script><title>Private title</title>')
        with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No comparison fetch")), CaptureQueriesContext(connection) as queries:
            result = self.compare(before, after, actor=self.admin)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual((result["method_version"], result["collection_method"], result["interpretation"]),
            (comparison.METHOD, collection.METHOD, comparison.INTERPRETATION))
        self.assertEqual(result["state"], "comparable_original_static_schema_labels")
        self.assertTrue(result["comparable"]); self.assertTrue(result["body_changed"])
        self.assertEqual(result["type_changes"], {"added": ["VideoObject", "WebPage"], "removed": ["Article"]})
        self.assertEqual(result["count_deltas"], {"json_ld_blocks": 0, "typed_nodes": 0, "unrecognized_type_count": -1})
        self.assertNotIn("metadata_changed", result)
        self.assertEqual(result["previous"]["evidence"], before.output["evidence"])
        self.assertEqual(result["current"]["evidence"], after.output["evidence"])
        self.assertEqual(result["source_sha256"], before.config_snapshot["binding"]["source_sha256"])
        for private in ("private@example", "PrivateUnknown", "Private title", self.owner.email, "artifact_id", "Private customer prose"):
            self.assertNotIn(private, json.dumps(result))
        result["previous"]["evidence"]["summary"]["types"].clear()
        self.assertEqual(self.compare(before, after)["previous"]["evidence"]["summary"]["types"], ["Article"])
        identical = self.collected("schema-identical")
        self.assertFalse(self.compare(before, identical)["body_changed"])

    def test_empty_labels_remain_empty_zero_invalid_labels_null_and_title_truncation_does_not_change_schema_coverage(self):
        before = self.collected("empty-schema", b"<p>No declarations</p>")
        for index, body in enumerate((b"<p>Still empty</p>", b'<script type="application/ld+json">{"@type":</script>',
            b"<title>" + b"x" * 501 + b"</title>", b"<h1>x</h1>" * 1001)):
            result = self.compare(before, self.collected("schema-coverage-" + str(index), body))
            comparable = index in (0, 2)
            self.assertEqual(result["comparable"], comparable)
            if comparable:
                self.assertEqual(result["type_changes"], {"added": [], "removed": []})
                self.assertTrue(all(value == 0 for value in result["count_deltas"].values()))
            else:
                self.assertEqual(result["state"], "incomparable_unavailable_schema_labels")
                self.assertIsNone(result["type_changes"]); self.assertIsNone(result["count_deltas"])

    def test_exact_ids_original_actor_dates_project_source_and_genuine_families_are_required(self):
        before = self.collected("schema-scope-before"); after = self.collected("schema-scope-after")
        for first, second in ((before, before), (after, before)):
            with self.assertRaises(ValidationError): self.compare(first, second)
        for value in (True, 0, -1, 2**53, str(before.pk), None):
            with self.assertRaises(ValidationError): self.compare(before, after, previous_job_id=value)
        with self.assertRaises(PermissionDenied): self.compare(before, after, actor=self.foreign)
        other_project = Project.objects.create(organization=self.organization, name="Other owned project",
            canonical_origin="https://other-owned.example.invalid")
        with self.assertRaises(PermissionDenied): self.compare(before, after, project=other_project)
        other_actor = self.collected("schema-other-actor", actor=self.admin)
        with self.assertRaises(ValidationError): self.compare(before, other_actor)
        for compare in (compare_competitor_roots, compare_competitor_pages):
            with self.assertRaises(PermissionDenied):
                compare(project=self.project, actor=self.owner, previous_job_id=before.pk, current_job_id=after.pk)
        with self.assertRaises(PermissionDenied):
            read_competitor_synthesis_source(project=self.project, actor=self.owner, previous_job_id=before.pk,
                current_job_id=after.pk, ai_processing_permission=True)
        for handler in (value for value in lifecycle.COMPETITOR_HANDLERS if value != collection.HANDLER):
            data = {**self.data, **({"url": self.data["origin"] + "/selected"} if handler in {"collect_competitor_page", "collect_competitor_page_headings", "collect_competitor_page_destinations", "collect_competitor_page_dates", "collect_competitor_page_formats"} else {})}
            other = root_fixtures.CompetitorCollectionTests.queue(self, "actual-schema-" + handler, handler=handler, data=data)
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
