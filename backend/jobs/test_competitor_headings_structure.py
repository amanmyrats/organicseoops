from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import Organization, OrganizationMembership, OrganizationTrial, ProjectConfiguration
from . import competitor_collection as lifecycle, competitor_headings_structure as structure
from . import competitor_reference_structure as kernel, competitor_page_headings_collection as elements
from . import test_competitor_page_headings_collection as fixtures
from .competitor_headings import COUNTS
from .crawling import CrawlScope
from .models import Artifact, JobCancellation, JobRun, JobStep, SourceCitation, UsageReservation
from .usage import UsageLimitError


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}))
class CompetitorHeadingsStructureTests(TransactionTestCase):
    setUp = fixtures.CompetitorPageHeadingsCollectionTests.setUp
    transport = fixtures.CompetitorPageHeadingsCollectionTests.transport
    fetcher = fixtures.CompetitorPageHeadingsCollectionTests.fetcher
    HTML = fixtures.CompetitorPageHeadingsCollectionTests.HTML

    def collected(self, path, body, key, origin=None):
        selected_origin = origin or self.data["origin"]
        with patch("socket.create_connection", side_effect=AssertionError("No actual site")):
            job = elements.queue_competitor_page_headings_collection(project=self.project, actor=self.owner,
                data={**self.data, "origin": selected_origin, "url": selected_origin + path}, idempotency_key=key)
            fetcher = self.fetcher(body=body)
            if origin: fetcher.scope = CrawlScope.for_project(self.project, competitor_origin=selected_origin)
            self.assertTrue(elements.execute_competitor_page_headings_collection(job.pk, fetcher=fetcher))
        job.refresh_from_db(); self.assertEqual(job.status, "succeeded", job.error_category)
        return job

    def pair(self):
        return (self.collected("/selected/a", b'<h1>First</h1><h2>Same</h2><h2>Same</h2><p>private-contact@example.invalid</p>', "elements-a"),
            self.collected("/selected/b", b'<h6>' + b'x' * 81 + b'</h6>', "elements-b"))

    def read(self, first, second, actor=None):
        return structure.read_competitor_headings_structure(project=self.project, actor=actor or self.admin,
            first_job_id=first.pk, second_job_id=second.pk)

    def test_genuine_original_six_columns_order_private_independent_reader_no_writes_network_or_new_work(self):
        first, second = self.pair(); counts = [model.objects.count() for model in (JobRun, Artifact, UsageReservation)]
        connection.queries_log.clear()
        with patch("socket.create_connection", side_effect=AssertionError("No new fetch")), CaptureQueriesContext(connection) as queries:
            result = self.read(first, second)
        self.assertTrue(queries.captured_queries); self.assertLess(len(queries), connection.queries_log.maxlen)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual(set(result), {"method_version", "organization_id", "project_id", "source_current", "pages",
            "heading_levels", "selected_heading_occurrences", "all_rows_observed", "interpretation"})
        self.assertEqual(result["heading_levels"], list(COUNTS))
        self.assertEqual(result["selected_heading_occurrences"], [[1, 2, 0, 0, 0, 0], [0, 0, 0, 0, 0, 1]])
        self.assertEqual(result["method_version"], structure.METHOD)
        self.assertEqual(result["interpretation"], structure.INTERPRETATION)
        self.assertTrue(result["source_current"]); self.assertTrue(result["all_rows_observed"])
        self.assertTrue(result["pages"][1]["collection"]["evidence"]["headings"][0]["truncated"])
        self.assertEqual(result["pages"][0]["collection"]["evidence"]["headings"][1:], [{"level": 2, "text": "Same", "truncated": False}] * 2)
        for job, page in zip((first, second), result["pages"]):
            self.assertEqual(page, elements.read_competitor_page_headings_observation(project=self.project, actor=self.admin, job_id=job.pk))
            self.assertEqual(page["collection"], {key: value for key, value in job.output.items() if key not in {"artifact_id", "derived_sha256"}})
        self.assertEqual(self.read(first, second, self.owner), result)
        reverse = self.read(second, first)
        self.assertEqual(reverse["pages"], list(reversed(result["pages"])))
        self.assertEqual(reverse["selected_heading_occurrences"], list(reversed(result["selected_heading_occurrences"])))
        for private in ("private-contact", self.owner.email, "Private customer prose"):
            self.assertNotIn(private, lifecycle._encode(result).decode())
        self.assertEqual([model.objects.count() for model in (JobRun, Artifact, UsageReservation)], counts)
        result["heading_levels"].clear(); result["pages"][0]["collection"]["evidence"]["counts"]["h1"] = 99
        result["selected_heading_occurrences"][0][0] = 99
        self.assertEqual(self.read(first, second)["selected_heading_occurrences"][0][0], 1)

    def test_observed_empty_zero_and_entire_unknown_rows_preserve_two_sample_only_coverage(self):
        empty = self.collected("/selected/empty", b"<p>Empty</p>", "elements-empty")
        unavailable = self.collected("/selected/unavailable", b"<title>Unclosed", "elements-unavailable")
        unknown = self.collected("/selected/unknown", b"<title>Unclosed", "elements-unknown")
        result = self.read(empty, unavailable)
        self.assertEqual(result["selected_heading_occurrences"], [[0] * 6, [None] * 6])
        self.assertFalse(result["all_rows_observed"])
        self.assertEqual(self.read(unavailable, unknown)["selected_heading_occurrences"], [[None] * 6, [None] * 6])
        self.assertIn("not_rendered_semantic_outline", result["interpretation"])
        self.assertIn("site_totals_whole_site", result["interpretation"])

    def test_safe_distinct_fixed_jobs_current_tenant_scope_uri_origin_and_other_families_rejected(self):
        first, second = self.pair()
        for key in (True, 0, -1, "1", 1.0, 2**53):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                structure.read_competitor_headings_structure(project=self.project, actor=self.admin,
                    first_job_id=key, second_job_id=second.pk)
        with self.assertRaises(ValidationError): self.read(first, first)
        with self.assertRaises(PermissionDenied): self.read(first, second, self.foreign)
        same = self.collected("/selected/a", b"<p>Later sample</p>", "elements-same")
        other = self.collected("/selected/other", b"<p>Other origin</p>", "elements-other", origin="https://second.example.invalid")
        for job in (same, other):
            with self.assertRaises(ValidationError): self.read(first, job)
        with self.assertRaises(PermissionDenied):
            kernel.read_competitor_reference_structure(project=self.project, actor=self.admin,
                first_job_id=first.pk, second_job_id=second.pk)
        root = lifecycle.queue_competitor_collection(project=self.project, actor=self.owner,
            data={key: value for key, value in self.data.items() if key != "url"}, idempotency_key="elements-root")
        self.assertTrue(lifecycle.execute_competitor_collection(root.pk, fetcher=self.fetcher(body=b"<p>Root</p>")))
        with self.assertRaises(PermissionDenied): self.read(first, root)

    def test_closed_packet_cap_and_actual_private_integrity_loss_withhold(self):
        first, second = self.pair()
        with patch.object(kernel, "MAX_RESULT_BYTES", 1), self.assertRaises(ValidationError): self.read(first, second)
        reader = lifecycle.read_project_artifact
        with patch.object(lifecycle, "read_project_artifact", side_effect=lambda **kwargs: reader(**kwargs) + b" "), self.assertRaises(ValidationError):
            self.read(first, second)
        self.assertLessEqual(len(lifecycle._encode(self.read(first, second))), structure.MAX_RESULT_BYTES)

    def test_post_projection_original_metadata_actor_caller_configuration_cancel_organization_and_expiry_withhold(self):
        first, second = self.pair(); encode = lifecycle._encode
        expected = self.read(first, second)
        for loss in ("artifact", "step", "citation", "usage", "actor", "caller", "configuration", "first-cancel", "second-cancel", "organization", "expiry"):
            with self.subTest(loss=loss), transaction.atomic():
                injected = []
                def late(value):
                    content = encode(value)
                    if value.get("method_version") == structure.METHOD:
                        injected.append(loss)
                        if loss == "artifact": Artifact.objects.filter(job=first).update(size_bytes=1)
                        elif loss == "step": JobStep.objects.filter(job=first).update(error_category="replacement")
                        elif loss == "citation": SourceCitation.objects.filter(job=first).update(source_title="replacement")
                        elif loss == "usage": UsageReservation.objects.filter(job=first).update(actual_units=2)
                        elif loss in ("actor", "caller"):
                            OrganizationMembership.objects.filter(organization=self.organization,
                                user=self.owner if loss == "actor" else self.admin).update(role="viewer")
                        elif loss == "configuration": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)
                        elif loss in ("first-cancel", "second-cancel"):
                            JobCancellation.objects.create(job=first if loss == "first-cancel" else second, requested_by=self.owner)
                        elif loss == "organization": Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True)
                        else:
                            now = timezone.now()
                            OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now-timedelta(days=31), ends_at=now-timedelta(seconds=1))
                    return content
                with patch.object(lifecycle, "_encode", side_effect=late), self.assertRaises((PermissionDenied, ValidationError, UsageLimitError)):
                    self.read(first, second)
                self.assertEqual(injected, [loss])
                transaction.set_rollback(True)
        self.assertEqual(self.read(first, second), expected)

    def test_last_fresh_pair_source_original_metadata_status_usage_and_both_cancellations_withhold(self):
        first, second = self.pair(); source = kernel._read_pair_sources
        expected = self.read(first, second)
        for loss in ("artifact", "status", "usage", "first-cancel", "second-cancel"):
            with self.subTest(loss=loss), transaction.atomic():
                calls = []
                def late(*args):
                    result = source(*args); calls.append(result)
                    if len(calls) == 2:
                        if loss == "artifact": Artifact.objects.filter(job=first).update(size_bytes=1)
                        elif loss == "status": JobRun.objects.filter(pk=first.pk).update(status="failed")
                        elif loss == "usage": UsageReservation.objects.filter(job=first).update(actual_units=2)
                        else: JobCancellation.objects.create(job=first if loss == "first-cancel" else second, requested_by=self.owner)
                    return result
                with patch.object(kernel, "_read_pair_sources", side_effect=late), self.assertRaises(PermissionDenied):
                    self.read(first, second)
                self.assertEqual(len(calls), 2)
                transaction.set_rollback(True)
        self.assertEqual(self.read(first, second), expected)
