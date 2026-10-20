from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import OrganizationMembership, OrganizationTrial, ProjectConfiguration
from . import competitor_collection as lifecycle, competitor_destination_inventory as inventory
from . import test_competitor_reference_structure as fixtures
from .competitor_reference_structure import read_competitor_reference_structure
from .models import Artifact, JobCancellation, JobRun, UsageReservation
from .usage import UsageLimitError


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}))
class CompetitorDestinationInventoryTests(TransactionTestCase):
    setUp = fixtures.CompetitorReferenceStructureTests.setUp
    transport = fixtures.CompetitorReferenceStructureTests.transport
    fetcher = fixtures.CompetitorReferenceStructureTests.fetcher
    collected = fixtures.CompetitorReferenceStructureTests.collected
    HTML = fixtures.CompetitorReferenceStructureTests.HTML

    def pair(self):
        return (self.collected("/selected/a", b'<a href="/selected/b">B</a><a href="/selected/b">Again</a>'
            b'<a href="/selected/b/">Slash</a><a href="/selected/%62">Encoded</a><a href="/selected/B">Case</a>', "inventory-a"),
            self.collected("/selected/b", b'<a href="/selected/a">A</a>', "inventory-b"))

    def read(self, first, second, actor=None):
        return inventory.read_competitor_destination_inventory(project=self.project, actor=actor or self.admin,
            first_job_id=first.pk, second_job_id=second.pk)

    def test_genuine_original_order_literal_variants_duplicate_counts_independent_reader_no_writes_network_or_new_work(self):
        first, second = self.pair(); counts = [model.objects.count() for model in (JobRun, Artifact, UsageReservation)]
        connection.queries_log.clear()
        with patch("socket.create_connection", side_effect=AssertionError("No target fetch")), CaptureQueriesContext(connection) as queries:
            result = self.read(first, second)
        self.assertTrue(queries.captured_queries); self.assertLess(len(queries), connection.queries_log.maxlen)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual(set(result), {"method_version", "organization_id", "project_id", "source_current", "pages",
            "destinations", "destination_reference_occurrences", "all_rows_observed", "interpretation"})
        self.assertEqual(result["destinations"], [self.data["origin"] + path for path in
            ("/selected/b", "/selected/b/", "/selected/%62", "/selected/B", "/selected/a")])
        self.assertEqual(result["destination_reference_occurrences"], [[2, 1, 1, 1, 0], [0, 0, 0, 0, 1]])
        self.assertTrue(result["all_rows_observed"]); self.assertTrue(result["source_current"])
        self.assertEqual(result["method_version"], inventory.METHOD)
        self.assertEqual(result["interpretation"], inventory.INTERPRETATION)
        self.assertIn("exact_stored_resolved_supported_destination_uris", result["interpretation"])
        self.assertEqual(result["pages"], read_competitor_reference_structure(project=self.project, actor=self.admin,
            first_job_id=first.pk, second_job_id=second.pk)["pages"])
        self.assertEqual([page["job_id"] for page in result["pages"]], [first.pk, second.pk])
        self.assertEqual(self.read(first, second, self.owner), result)
        reverse = self.read(second, first)
        self.assertEqual(reverse["destinations"], [self.data["origin"] + path for path in
            ("/selected/a", "/selected/b", "/selected/b/", "/selected/%62", "/selected/B")])
        self.assertEqual(reverse["destination_reference_occurrences"], [[1, 0, 0, 0, 0], [0, 2, 1, 1, 1]])
        self.assertEqual([model.objects.count() for model in (JobRun, Artifact, UsageReservation)], counts)
        result["destinations"].clear(); result["pages"][0]["collection"]["evidence"]["destinations"].clear()
        result["destination_reference_occurrences"][0][0] = 99
        self.assertEqual(self.read(first, second)["destination_reference_occurrences"], [[2, 1, 1, 1, 0], [0, 0, 0, 0, 1]])

    def test_observed_empty_unknown_rows_and_empty_union_preserve_null_without_site_or_target_coverage(self):
        known = self.collected("/selected/known", b'<a href="/not-sampled">Known reference</a>', "inventory-known")
        empty = self.collected("/selected/empty", b"<p>Empty</p>", "inventory-empty")
        unavailable = self.collected("/selected/unavailable", b"<title>Unclosed", "inventory-unavailable")
        unknown = self.collected("/selected/unknown", b"<title>Unclosed", "inventory-unknown")
        result = self.read(known, empty)
        self.assertEqual(result["destinations"], [self.data["origin"] + "/not-sampled"])
        self.assertEqual(result["destination_reference_occurrences"], [[1], [0]])
        self.assertTrue(result["all_rows_observed"])
        self.assertEqual(self.read(known, unavailable)["destination_reference_occurrences"], [[1], None])
        result = self.read(empty, unavailable)
        self.assertEqual(result["destinations"], [])
        self.assertEqual(result["destination_reference_occurrences"], [[], None])
        self.assertFalse(result["all_rows_observed"])
        result = self.read(unavailable, unknown)
        self.assertEqual(result["destinations"], []); self.assertEqual(result["destination_reference_occurrences"], [None, None])
        self.assertFalse(result["all_rows_observed"])
        self.assertIn("not_complete_site_page_or_destination_inventory", result["interpretation"])

    def test_safe_distinct_actual_fixed_jobs_current_scope_and_same_uri_or_other_origin_rejected(self):
        first, second = self.pair()
        for key in (True, 0, -1, "1", 1.0, 2**53):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                inventory.read_competitor_destination_inventory(project=self.project, actor=self.admin,
                    first_job_id=key, second_job_id=second.pk)
        with self.assertRaises(ValidationError): self.read(first, first)
        with self.assertRaises(PermissionDenied): self.read(first, second, self.foreign)
        same = self.collected("/selected/a", b"<p>Another sample</p>", "inventory-same")
        other = self.collected("/selected/other", b"<p>Other origin</p>", "inventory-other", origin="https://second.example.invalid")
        for row in (same, other):
            with self.assertRaises(ValidationError): self.read(first, row)
        root = lifecycle.queue_competitor_collection(project=self.project, actor=self.owner,
            data={key: value for key, value in self.data.items() if key != "url"}, idempotency_key="inventory-root")
        self.assertTrue(lifecycle.execute_competitor_collection(root.pk, fetcher=self.fetcher(body=b"<p>Root</p>")))
        with self.assertRaises(PermissionDenied): self.read(first, root)

    def test_closed_packet_cap_and_original_private_integrity_losses_withhold_inventory(self):
        first, second = self.pair()
        with patch.object(inventory, "MAX_RESULT_BYTES", 1), self.assertRaises(ValidationError): self.read(first, second)
        read = lifecycle.read_project_artifact
        with patch.object(lifecycle, "read_project_artifact", side_effect=lambda **kwargs: read(**kwargs) + b" "), self.assertRaises(ValidationError):
            self.read(first, second)
        self.assertLessEqual(len(lifecycle._encode(self.read(first, second))), inventory.MAX_RESULT_BYTES)

    def test_post_projection_original_metadata_actor_caller_configuration_all_cancellation_and_expiry_losses_withhold(self):
        first, second = self.pair(); encode = lifecycle._encode
        for loss in ("artifact", "status", "usage", "actor", "caller", "configuration", "first-cancel", "second-cancel", "expiry"):
            with self.subTest(loss=loss), transaction.atomic():
                calls = 0
                def late(value):
                    nonlocal calls
                    content = encode(value)
                    if value.get("method_version") == inventory.METHOD:
                        calls += 1
                        if loss == "artifact": Artifact.objects.filter(job=first).update(size_bytes=1)
                        elif loss == "status": JobRun.objects.filter(pk=first.pk).update(status="failed")
                        elif loss == "usage": UsageReservation.objects.filter(job=first).update(actual_units=2)
                        elif loss in ("actor", "caller"):
                            OrganizationMembership.objects.filter(organization=self.organization,
                                user=self.owner if loss == "actor" else self.admin).update(role="viewer")
                        elif loss == "configuration": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)
                        elif loss in ("first-cancel", "second-cancel"):
                            JobCancellation.objects.create(job=first if loss == "first-cancel" else second, requested_by=self.owner)
                        else:
                            now = timezone.now()
                            OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now-timedelta(days=31), ends_at=now-timedelta(seconds=1))
                    return content
                with patch.object(lifecycle, "_encode", side_effect=late), self.assertRaises((PermissionDenied, ValidationError, UsageLimitError)):
                    self.read(first, second)
                self.assertEqual(calls, 1)
                transaction.set_rollback(True)
        self.assertEqual(self.read(first, second)["destination_reference_occurrences"], [[2, 1, 1, 1, 0], [0, 0, 0, 0, 1]])

    def test_last_fresh_pair_source_first_metadata_status_usage_and_both_cancellations_withhold_inventory(self):
        first, second = self.pair(); source = inventory._read_pair_sources
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
                with patch.object(inventory, "_read_pair_sources", side_effect=last), self.assertRaises(PermissionDenied):
                    self.read(first, second)
                self.assertEqual(calls, 2)
                transaction.set_rollback(True)
        self.assertEqual(self.read(first, second), expected)
