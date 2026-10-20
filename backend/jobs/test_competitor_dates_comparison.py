import json
from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import OrganizationMembership, OrganizationTrial, Project, ProjectConfiguration
from tenancy.services import create_organization, create_project
from . import competitor_collection as lifecycle, competitor_page_dates_collection as collection
from . import competitor_dates_comparison as comparison
from . import test_competitor_collection as root_fixtures
from . import test_competitor_comparison as pair_fixtures
from . import test_competitor_page_dates_collection as fixtures
from .competitor_comparison import compare_competitor_roots
from .competitor_synthesis import read_competitor_synthesis_source
from .models import Artifact, JobRun
from .usage import UsageLimitError


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}))
class CompetitorDatesComparisonTests(TransactionTestCase):
    setUp = fixtures.CompetitorPageDatesCollectionTests.setUp
    queue = fixtures.CompetitorPageDatesCollectionTests.queue
    transport = fixtures.CompetitorPageDatesCollectionTests.transport

    def collected(self, key, body=fixtures.CompetitorPageDatesCollectionTests.HTML, **changes):
        job = self.queue(key, **changes)
        fetcher = root_fixtures.CompetitorCollectionTests.fetcher(self, body=body)
        with patch("socket.create_connection", side_effect=AssertionError("No actual egress")):
            self.assertTrue(collection.execute_competitor_page_dates_collection(job.pk, fetcher=fetcher))
        job.refresh_from_db(); self.assertEqual(job.status, "succeeded", job.error_category)
        return job

    def compare(self, before, after, **changes):
        return comparison.compare_competitor_page_dates(**{**dict(project=self.project, actor=self.owner,
            previous_job_id=before.pk, current_job_id=after.pk), **changes})

    def test_genuine_original_date_pair_independent_reader_literal_order_body_integrity_no_write_or_network(self):
        before = self.collected("dates-before")
        after = self.collected("dates-after", b'<meta property="article:modified_time" content="not a calendar date">'
            b'<meta property="article:published_time" content="2099-01-01"><meta property="article:published_time" content="2099-01-01">'
            b'<a href="/private">Link</a><p>private-contact@example.invalid</p>')
        with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No comparison fetch")), CaptureQueriesContext(connection) as queries:
            result = self.compare(before, after, actor=self.admin)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual((result["method_version"], result["collection_method"], result["url"], result["interpretation"]),
            (comparison.METHOD, collection.METHOD, self.data["url"], comparison.INTERPRETATION))
        self.assertEqual(set(result), {"method_version", "organization_id", "project_id", "source_current", "collection_method", "parser_method",
            "url", "source_sha256", "previous", "current", "comparable", "body_changed", "interpretation", "state", "declarations_changed"})
        self.assertTrue(result["comparable"]); self.assertTrue(result["body_changed"]); self.assertTrue(result["declarations_changed"])
        self.assertEqual(result["current"]["evidence"]["declarations"], [
            {"property": "article:modified_time", "value": "not a calendar date", "truncated": False},
            {"property": "article:published_time", "value": "2099-01-01", "truncated": False},
            {"property": "article:published_time", "value": "2099-01-01", "truncated": False}])
        self.assertEqual(result["previous"]["evidence"], before.output["evidence"])
        self.assertEqual(result["current"]["evidence"], after.output["evidence"])
        self.assertEqual(result["source_sha256"], before.config_snapshot["binding"]["source_sha256"])
        for private in ("private-contact", '"/private"', self.owner.email, "artifact_id", "Private customer prose", "parsed_date", "count_deltas"):
            self.assertNotIn(private, json.dumps(result))
        result["previous"]["evidence"]["declarations"][0]["value"] = "changed"
        self.assertEqual(self.compare(before, after)["previous"]["evidence"]["declarations"][0]["value"], "2099-01-01")

    def test_empty_unavailable_truncated_overflow_and_irrelevant_metadata_are_distinct(self):
        before = self.collected("empty-dates", b"<p>Empty</p>")
        for index, (body, comparable) in enumerate(((b"<p>Still empty</p>", True), (b"<template>Unclosed", False),
            (b'<meta property="article:published_time" content="' + b"x" * 81 + b'">', False),
            (b'<meta property="article:published_time" content="x">' * 11, False),
            (b"<title>" + b"x" * 501 + b"</title>", True))):
            result = self.compare(before, self.collected("coverage-dates-" + str(index), body))
            self.assertEqual(result["comparable"], comparable)
            self.assertNotIn("count_deltas", result)
            if comparable:
                self.assertFalse(result["declarations_changed"])
                self.assertEqual(result["state"], "comparable_original_static_article_date_declarations")
            else:
                self.assertIsNone(result["declarations_changed"])
                self.assertEqual(result["state"], "incomparable_unavailable_or_truncated_article_date_declarations")
        empty_value = self.collected("empty-value", b'<meta property="article:published_time" content="">')
        result = self.compare(before, empty_value)
        self.assertTrue(result["comparable"]); self.assertTrue(result["declarations_changed"])
        self.assertEqual(result["current"]["evidence"]["declarations"], [{"property": "article:published_time", "value": "", "truncated": False}])

    def test_order_property_and_literal_text_changes_are_independent_of_returned_body_changes(self):
        body = b'<meta property="article:published_time" content="2099-01-01"><meta property="article:modified_time" content="literal">'
        before = self.collected("ordered-before", body)
        for index, (after, changed, bytes_changed) in enumerate(((body, False, False),
            (b'<meta property="article:modified_time" content="literal"><meta property="article:published_time" content="2099-01-01">', True, True),
            (body.replace(b"2099-01-01", b"not a date"), True, True),
            (body.replace(b"article:modified_time", b"article:published_time"), True, True),
            (body + b"<p>Other unretained bytes</p>", False, True))):
            result = self.compare(before, self.collected("ordered-after-" + str(index), after))
            self.assertTrue(result["comparable"]); self.assertEqual(result["declarations_changed"], changed)
            self.assertEqual(result["body_changed"], bytes_changed)

    def test_status_only_failed_jobs_cannot_be_promoted_to_private_page_comparisons(self):
        transport, calls = self.transport, [0]
        def status_only(body, **kwargs):
            calls[0] += 1
            return transport(body, **{**kwargs, "status": "404 Not Found" if calls[0] % 2 == 0 else "200 OK"})
        with patch.object(self, "transport", side_effect=status_only):
            failed = []
            for key in ("status-page-before", "status-page-after"):
                job = self.queue(key)
                with patch("socket.create_connection", side_effect=AssertionError("No actual egress")):
                    self.assertTrue(collection.execute_competitor_page_dates_collection(job.pk,
                        fetcher=root_fixtures.CompetitorCollectionTests.fetcher(self)))
                job.refresh_from_db(); self.assertEqual(job.status, "failed")
                self.assertEqual(job.error_category, "competitor_document_http_status")
                self.assertFalse(job.output); self.assertFalse(job.artifacts.exists())
                self.assertEqual(job.usage.actual_units, 1)
                failed.append(job)
            before, after = failed
        observed = self.collected("observed-page-after")
        for current in (after, observed):
            with patch.object(lifecycle, "read_project_artifact", side_effect=AssertionError("No failed-job private read")), self.assertRaises(PermissionDenied):
                self.compare(before, current)
        self.assertIsNotNone(observed.output["evidence"]["body_sha256"])

    def test_exact_distinct_ids_uri_original_actor_dates_family_and_current_scope_are_required(self):
        before = self.collected("scope-page-before"); after = self.collected("scope-page-after")
        for first, second in ((before, before), (after, before)):
            with self.assertRaises(ValidationError): self.compare(first, second)
        for value in (True, 0, -1, 2**53, str(before.pk), None):
            with self.assertRaises(ValidationError): self.compare(before, after, previous_job_id=value)
        other_project = Project.objects.create(organization=self.organization,
            name="Other owned project", canonical_origin="https://other-owned.example.invalid")
        other_org = create_organization(user=self.foreign, name="Foreign organization")
        foreign_project = create_project(organization=other_org, user=self.foreign,
            name="Foreign project", canonical_origin="https://foreign-owned.example.invalid")
        for changes in ({"actor": self.foreign}, {"project": other_project}, {"project": foreign_project, "actor": self.foreign}):
            with self.assertRaises(PermissionDenied): self.compare(before, after, **changes)
        other_uri = self.collected("different-uri", data={**self.data, "url": self.data["url"] + "-other"})
        other_actor = self.collected("different-actor", actor=self.admin)
        for other in (other_uri, other_actor):
            with self.assertRaises(ValidationError): self.compare(before, other)
        with self.assertRaises(PermissionDenied):
            compare_competitor_roots(project=self.project, actor=self.owner, previous_job_id=before.pk, current_job_id=after.pk)
        with self.assertRaises(PermissionDenied):
            read_competitor_synthesis_source(project=self.project, actor=self.owner, previous_job_id=before.pk,
                current_job_id=after.pk, ai_processing_permission=True)
        from .competitor_page_comparison import compare_competitor_pages
        from .competitor_schema_comparison import compare_competitor_schema_roots
        from .competitor_links_comparison import compare_competitor_links_roots
        from .competitor_headings_comparison import compare_competitor_page_headings
        from .competitor_destinations_comparison import compare_competitor_page_destinations
        from .competitor_headings_synthesis import read_competitor_headings_synthesis_source
        with self.assertRaises(PermissionDenied):
            read_competitor_headings_synthesis_source(project=self.project, actor=self.owner, previous_job_id=before.pk,
                current_job_id=after.pk, ai_processing_permission=True)
        for old in (compare_competitor_pages, compare_competitor_schema_roots, compare_competitor_links_roots, compare_competitor_page_headings, compare_competitor_page_destinations):
            with self.assertRaises(PermissionDenied): old(project=self.project, actor=self.owner, previous_job_id=before.pk, current_job_id=after.pk)
        for handler in (value for value in lifecycle.COMPETITOR_HANDLERS if value != collection.HANDLER):
            other = root_fixtures.CompetitorCollectionTests.queue(self, "actual-" + handler, handler=handler,
                data=(self.data if handler in {"collect_competitor_page", "collect_competitor_page_headings", "collect_competitor_page_destinations", "collect_competitor_page_dates", "collect_competitor_page_formats"} else
                    {key: value for key, value in self.data.items() if key != "url"}))
            with patch("socket.create_connection", side_effect=AssertionError("No actual egress")):
                self.assertTrue(lifecycle.execute_competitor_collection(other.pk,
                    fetcher=root_fixtures.CompetitorCollectionTests.fetcher(self), handler=handler))
            other.refresh_from_db(); self.assertEqual(other.status, "succeeded")
            with self.assertRaises(PermissionDenied): self.compare(before, other)
        ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[])
        with self.assertRaises((PermissionDenied, ValidationError)): self.compare(before, after)

    def test_late_first_original_artifact_caller_configuration_and_natural_expiry_withhold_both_pages(self):
        before = self.collected("late-page-before"); after = self.collected("late-page-after")
        read = lifecycle.read_project_artifact
        artifact = before.artifacts.get()
        for loss in ("artifact", "caller", "configuration", "expiry"):
            with self.subTest(loss=loss), transaction.atomic():
                calls = [0]
                def late_read(**kwargs):
                    content = read(**kwargs); calls[0] += 1
                    if calls[0] == 2:
                        if loss == "artifact": Artifact.objects.filter(pk=artifact.pk).update(size_bytes=artifact.size_bytes + 1)
                        elif loss == "caller": OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer")
                        elif loss == "configuration": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)
                        else:
                            now = timezone.now(); OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now - timedelta(days=31), ends_at=now - timedelta(days=1))
                    return content
                with patch.object(lifecycle, "read_project_artifact", side_effect=late_read), self.assertRaises((PermissionDenied, ValidationError, UsageLimitError)):
                    self.compare(before, after, actor=self.admin)
                transaction.set_rollback(True)
        self.assertEqual(JobRun.objects.filter(handler=collection.HANDLER).count(), 2)

    test_last_second_metadata_return_fences_both_original_sources_and_independent_caller = pair_fixtures.CompetitorComparisonTests.test_last_second_metadata_return_fences_both_original_sources_and_independent_caller
    test_first_original_cancellation_during_last_second_source_read_withholds_whole_private_pair = pair_fixtures.CompetitorComparisonTests.test_first_original_cancellation_during_last_second_source_read_withholds_whole_private_pair
