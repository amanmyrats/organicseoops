from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import OrganizationMembership, OrganizationTrial, ProjectConfiguration
from . import competitor_collection as lifecycle, competitor_page_destinations_collection as references
from . import competitor_reference_structure as structure
from . import test_competitor_page_destinations_collection as fixtures
from .crawling import CrawlScope
from .models import Artifact, JobCancellation, JobRun, UsageReservation
from .usage import UsageLimitError


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}))
class CompetitorReferenceStructureTests(TransactionTestCase):
    setUp = fixtures.CompetitorPageDestinationsCollectionTests.setUp
    transport = fixtures.CompetitorPageDestinationsCollectionTests.transport
    fetcher = fixtures.CompetitorPageDestinationsCollectionTests.fetcher
    HTML = fixtures.CompetitorPageDestinationsCollectionTests.HTML

    def collected(self, path, body, key, origin=None):
        selected_origin = origin or self.data["origin"]
        with patch("socket.create_connection", side_effect=AssertionError("No actual site")):
            job = references.queue_competitor_page_destinations_collection(project=self.project, actor=self.owner,
                data={**self.data, "origin": selected_origin, "url": selected_origin + path}, idempotency_key=key)
            fetcher = self.fetcher(body=body)
            if origin: fetcher.scope = CrawlScope.for_project(self.project, competitor_origin=selected_origin)
            self.assertTrue(references.execute_competitor_page_destinations_collection(job.pk, fetcher=fetcher))
        job.refresh_from_db(); self.assertEqual(job.status, "succeeded", job.error_category)
        return job

    def pair(self):
        return (self.collected("/selected/a", b'<a href="/selected/b">B</a><a href="/selected/b">Again</a>'
            b'<a href="/selected/b/">Trailing slash</a><a href="/selected/%62">Encoded</a>', "structure-a"),
            self.collected("/selected/b", b'<a href="/selected/a">A</a>', "structure-b"))

    def read(self, first, second, actor=None):
        return structure.read_competitor_reference_structure(project=self.project, actor=actor or self.admin,
            first_job_id=first.pk, second_job_id=second.pk)

    def test_genuine_current_independent_reader_original_order_exact_duplicates_no_writes_or_network_and_fresh_packet(self):
        first, second = self.pair()
        connection.queries_log.clear()
        with patch("socket.create_connection", side_effect=AssertionError("No new fetch")), CaptureQueriesContext(connection) as queries:
            result = self.read(first, second)
        self.assertTrue(queries.captured_queries)
        self.assertLess(len(connection.queries_log), connection.queries_limit)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual(result["selected_uri_reference_occurrences"], [[0, 2], [1, 0]])
        self.assertEqual(result["pages"][0]["collection"]["evidence"]["destinations"],
            [self.data["origin"] + path for path in ("/selected/b", "/selected/b", "/selected/b/", "/selected/%62")])
        self.assertEqual([row["job_id"] for row in result["pages"]], [first.pk, second.pk])
        self.assertEqual(result["pages"][0]["collection"], {key:value for key,value in first.output.items() if key not in {"artifact_id", "derived_sha256"}})
        self.assertEqual(result["pages"][1]["collection"], {key:value for key,value in second.output.items() if key not in {"artifact_id", "derived_sha256"}})
        self.assertEqual(self.read(first, second, self.owner), result)
        self.assertEqual(result["method_version"], structure.METHOD)
        self.assertLessEqual(len(lifecycle._encode(result)), structure.MAX_RESULT_BYTES)
        result["pages"][0]["collection"]["evidence"]["destinations"].clear()
        result["selected_uri_reference_occurrences"][0][1] = 0
        self.assertEqual(self.read(first, second)["selected_uri_reference_occurrences"], [[0, 2], [1, 0]])

    def test_original_empty_row_is_zero_unavailable_row_null_without_target_health_or_global_graph(self):
        first = self.collected("/selected/empty", b"<p>Empty</p>", "structure-empty")
        second = self.collected("/selected/unavailable", b"<title>Unclosed", "structure-unavailable")
        result = self.read(first, second)
        self.assertEqual(result["selected_uri_reference_occurrences"], [[0, 0], [None, None]])
        self.assertEqual([row["collection"]["evidence"]["state"] for row in result["pages"]], ["observed", "unavailable"])
        self.assertIn("not_unique_pages_target_health", result["interpretation"])

    def test_safe_distinct_actual_fixed_jobs_foreign_caller_and_same_uri_rejected(self):
        first, second = self.pair()
        for key in (True, 0, -1, "1", 1.0, 2**53):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                structure.read_competitor_reference_structure(project=self.project, actor=self.admin,
                    first_job_id=key, second_job_id=second.pk)
        with self.assertRaises(ValidationError): self.read(first, first)
        with self.assertRaises(PermissionDenied): self.read(first, second, self.foreign)
        same = self.collected("/selected/a", b"<p>Other dated sample</p>", "structure-same-uri")
        with self.assertRaises(ValidationError): self.read(first, same)
        root = lifecycle.queue_competitor_collection(project=self.project, actor=self.owner,
            data={key:value for key,value in self.data.items() if key != "url"}, idempotency_key="structure-root")
        self.assertTrue(lifecycle.execute_competitor_collection(root.pk, fetcher=self.fetcher(body=b"<p>Root</p>")))
        with self.assertRaises(PermissionDenied): self.read(first, root)

    def test_two_genuine_approved_origins_cannot_be_combined_and_packet_cap_is_closed(self):
        first, second = self.pair()
        other = self.collected("/selected/other", b"<p>Other approved origin</p>", "structure-other-origin", origin="https://second.example.invalid")
        with self.assertRaises(ValidationError): self.read(first, other)
        with patch.object(structure, "MAX_RESULT_BYTES", 1), self.assertRaises(ValidationError):
            self.read(first, second)

    def test_private_integrity_and_late_first_metadata_actor_caller_configuration_cancel_or_expiry_withhold(self):
        first, second = self.pair(); read = lifecycle.read_project_artifact
        for loss in ("bytes", "metadata", "actor", "caller", "configuration", "first-cancel", "second-cancel", "expiry"):
            with self.subTest(loss=loss), transaction.atomic():
                calls = 0
                def late(**kwargs):
                    nonlocal calls
                    content = read(**kwargs); calls += 1
                    if calls != 2: return content
                    if loss == "bytes": return content + b" "
                    if loss == "metadata": Artifact.objects.filter(job=first).update(size_bytes=1)
                    elif loss == "actor": OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
                    elif loss == "caller": OrganizationMembership.objects.filter(organization=self.organization, user=self.admin).update(role="viewer")
                    elif loss == "configuration": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)
                    elif loss in ("first-cancel", "second-cancel"):
                        JobCancellation.objects.create(job=first if loss == "first-cancel" else second, requested_by=self.owner)
                    else:
                        now = timezone.now()
                        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now-timedelta(days=31), ends_at=now-timedelta(seconds=1))
                    return content
                with patch.object(lifecycle, "read_project_artifact", side_effect=late), self.assertRaises((PermissionDenied, ValidationError, UsageLimitError)):
                    self.read(first, second)
                transaction.set_rollback(True)
        self.assertEqual(self.read(first, second)["selected_uri_reference_occurrences"], [[0, 2], [1, 0]])

    def test_first_cancellation_during_last_unchanged_metadata_denies_after_both_sources(self):
        first, second = self.pair(); metadata = lifecycle._read_metadata; calls = 0
        def late(key):
            nonlocal calls
            value = metadata(key)
            if key == second.pk:
                calls += 1
                # Freeze, private reader before/after, then this source's final metadata.
                if calls == 4: JobCancellation.objects.create(job=first, requested_by=self.owner)
            return value
        with patch.object(lifecycle, "_read_metadata", side_effect=late), self.assertRaises(PermissionDenied):
            self.read(first, second)
        self.assertTrue(JobCancellation.objects.filter(job=first).exists())

    def test_last_private_observation_source_metadata_status_usage_and_cancellation_losses_withhold(self):
        first, _second = self.pair(); source = lifecycle._read_source
        expected = references.read_competitor_page_destinations_observation(project=self.project, actor=self.admin, job_id=first.pk)
        for loss in ("artifact", "status", "usage", "cancel"):
            with self.subTest(loss=loss), transaction.atomic():
                calls = 0
                def last(job, project, actor):
                    nonlocal calls
                    result = source(job, project, actor); calls += 1
                    if calls == 3:
                        if loss == "artifact": Artifact.objects.filter(job=first).update(size_bytes=1)
                        elif loss == "status": JobRun.objects.filter(pk=first.pk).update(status="failed")
                        elif loss == "usage": UsageReservation.objects.filter(job=first).update(actual_units=2)
                        else: JobCancellation.objects.create(job=first, requested_by=self.owner)
                    return result
                with patch.object(lifecycle, "_read_source", side_effect=last), self.assertRaises(PermissionDenied):
                    references.read_competitor_page_destinations_observation(project=self.project, actor=self.admin, job_id=first.pk)
                self.assertEqual(calls, 3)
                transaction.set_rollback(True)
        self.assertEqual(references.read_competitor_page_destinations_observation(project=self.project, actor=self.admin, job_id=first.pk), expected)

    def test_last_reference_pair_source_first_metadata_status_usage_and_both_cancellations_withhold(self):
        first, second = self.pair(); source = structure._read_pair_sources
        expected = self.read(first, second)
        for loss in ("artifact", "status", "usage", "first-cancel", "second-cancel"):
            with self.subTest(loss=loss), transaction.atomic():
                calls = 0
                def last(*args):
                    nonlocal calls
                    result = source(*args); calls += 1
                    if calls == 2:
                        if loss == "artifact": Artifact.objects.filter(job=first).update(size_bytes=1)
                        elif loss == "status": JobRun.objects.filter(pk=first.pk).update(status="failed")
                        elif loss == "usage": UsageReservation.objects.filter(job=first).update(actual_units=2)
                        else: JobCancellation.objects.create(job=first if loss == "first-cancel" else second, requested_by=self.owner)
                    return result
                with patch.object(structure, "_read_pair_sources", side_effect=last), self.assertRaises(PermissionDenied):
                    self.read(first, second)
                self.assertEqual(calls, 2)
                transaction.set_rollback(True)
        self.assertEqual(self.read(first, second), expected)
