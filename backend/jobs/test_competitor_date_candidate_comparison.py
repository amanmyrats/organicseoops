from copy import deepcopy
from datetime import timedelta
import json
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import OrganizationMembership, OrganizationTrial, Project, ProjectConfiguration
from . import competitor_collection as lifecycle, competitor_date_candidate_comparison as source
from . import competitor_dates_comparison as original, test_competitor_dates_comparison as fixtures
from .models import Artifact, JobCancellation, JobRun, JobStep, SourceCitation, UsageReservation
from .usage import UsageLimitError


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}))
class CompetitorDateCandidateComparisonTests(TransactionTestCase):
    setUp = fixtures.CompetitorDatesComparisonTests.setUp
    queue = fixtures.CompetitorDatesComparisonTests.queue
    transport = fixtures.CompetitorDatesComparisonTests.transport
    collected = fixtures.CompetitorDatesComparisonTests.collected

    def compare(self, before, after, **changes):
        return source.compare_competitor_date_candidates(**{**dict(project=self.project, actor=self.admin,
            previous_job_id=before.pk, current_job_id=after.pk), **changes})

    def body(self, declarations):
        return ''.join(f'<meta property="article:{prop}_time" content="{value}">' for prop, value in declarations).encode()

    def test_genuine_original_same_uri_pair_independent_reader_exact_intervals_crossproduct_no_writes_or_network(self):
        before = self.collected("before", self.body([("published", "2024-02-28"), ("published", "2024-02-28"),
            ("modified", "2026-01-01T03:00:00.000001+03:00"), ("modified", "not a date")]))
        after = self.collected("after", self.body([("modified", "2026-01-01T00:00:00.000002Z"), ("published", "2024-03-01"),
            ("modified", "2026-01-01T03:00:00.000001+03:00")]))
        counts = (JobRun.objects.count(), Artifact.objects.count(), UsageReservation.objects.count())
        with patch("socket.create_connection", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            result = self.compare(before, after)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual((JobRun.objects.count(), Artifact.objects.count(), UsageReservation.objects.count()), counts)
        self.assertEqual(result["comparison"], original.compare_competitor_page_dates(project=self.project, actor=self.owner,
            previous_job_id=before.pk, current_job_id=after.pk))
        rows = result["declaration_pair_candidates"]
        self.assertEqual([(row["previous_declaration_index"], row["current_declaration_index"]) for row in rows],
            [(0, 1), (1, 1), (2, 0), (2, 2), (3, 0), (3, 2)])
        self.assertEqual([row["calendar_day_delta"] for row in rows], [2, 2, None, None, None, None])
        self.assertEqual([row["utc_microsecond_delta"] for row in rows], [None, None, "1", "0", None, None])
        self.assertEqual([row["state"] for row in rows], ["calendar_candidates"] * 2 + ["offset_candidates"] * 2 + ["incomparable_literal_candidates"] * 2)
        expected = deepcopy(result); result["previous_candidates"].clear(); result["comparison"]["previous"]["evidence"]["declarations"].clear()
        self.assertEqual(self.compare(before, after), expected)
        for value in (self.owner.email, "config_snapshot", "artifact_id", "storage_key"):
            self.assertNotIn(value, json.dumps(expected))

    def test_negative_and_large_exact_microsecond_strings_and_calendar_gaps_do_not_use_observation_gaps(self):
        before = self.collected("large-before", self.body([("published", "9999-12-31T23:59:59.999999Z"), ("modified", "2024-03-01")]))
        after = self.collected("large-after", self.body([("published", "0001-01-01T00:00:00Z"), ("modified", "2024-02-28")]))
        rows = self.compare(before, after)["declaration_pair_candidates"]
        self.assertEqual(rows[0]["utc_microsecond_delta"], "-315537897599999999")
        self.assertEqual(rows[1]["calendar_day_delta"], -2)
        self.assertTrue(int(rows[0]["utc_microsecond_delta"]) < -(2**53))

    def test_calendar_offset_mixed_unsupported_truncated_whole_unknown_and_observed_empty_remain_distinct(self):
        before = self.collected("mixed-before", self.body([("published", "2024-01-01"), ("published", "2024-01-01T00:00:00Z"),
            ("published", "2024-01-01T00:00:00-00:00"), ("published", "x" * 81)]))
        after = self.collected("mixed-after", self.body([("published", "2024-01-02")]))
        result = self.compare(before, after)
        self.assertEqual(result["previous_candidates"][3]["state"], "truncated_literal")
        self.assertEqual([row["state"] for row in result["declaration_pair_candidates"]],
            ["calendar_candidates"] + ["incomparable_literal_candidates"] * 3)
        self.assertFalse(result["comparison"]["comparable"])
        empty = self.collected("empty", b"<p>No date declarations</p>")
        unknown = self.collected("unknown", b"<title>Unclosed")
        self.assertEqual(self.compare(before, empty)["declaration_pair_candidates"], [])
        result = self.compare(empty, unknown)
        self.assertEqual(result["previous_candidates"], []); self.assertIsNone(result["current_candidates"])
        self.assertIsNone(result["declaration_pair_candidates"])

    def test_exact_safe_scope_family_distinct_uri_actor_observation_order_size_and_private_integrity(self):
        before = self.collected("scope-before"); after = self.collected("scope-after")
        for key in (True, 0, -1, 2**53, "1"):
            with self.assertRaises(ValidationError): self.compare(before, after, previous_job_id=key)
        for first, second in ((before, before), (after, before)):
            with self.assertRaises(ValidationError): self.compare(first, second)
        other = Project.objects.create(organization=self.organization, name="Other", canonical_origin="https://other.example.invalid")
        with self.assertRaises(PermissionDenied): self.compare(before, after, project=other)
        with self.assertRaises(PermissionDenied): self.compare(before, after, actor=self.foreign)
        for changes in ({"handler": "collect_competitor_page_formats"}, {"status": "failed"}):
            with transaction.atomic():
                JobRun.objects.filter(pk=after.pk).update(**changes)
                with self.assertRaises(PermissionDenied): self.compare(before, after)
                transaction.set_rollback(True)
        different_uri = self.collected("other-uri", data={**self.data, "url": self.data["url"]+"-other"})
        different_actor = self.collected("other-actor", actor=self.admin)
        for current in (different_uri, different_actor):
            with self.assertRaises(ValidationError): self.compare(before, current)
        with patch.object(source, "MAX_RESULT_BYTES", 10), self.assertRaises(ValidationError): self.compare(before, after)
        with patch.object(lifecycle, "read_project_artifact", return_value=b"{}"), self.assertRaises(ValidationError): self.compare(before, after)

    def test_post_projection_full_originals_actor_caller_source_cancel_and_natural_expiry_withhold(self):
        before = self.collected("late-before"); after = self.collected("late-after")
        projector = source._candidate_rows
        for loss in ("actor", "caller", "configuration", "artifact", "step", "citation", "usage", "cancel", "expiry"):
            with self.subTest(loss=loss), transaction.atomic():
                ends = timezone.now()+timedelta(seconds=20); actual = timezone.now
                OrganizationTrial.objects.filter(organization=self.organization).update(started_at=ends-timedelta(days=30), ends_at=ends)
                done = [False]
                def changed(*args):
                    result = projector(*args); done[0] = True
                    if loss == "actor": OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
                    elif loss == "caller": OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer")
                    elif loss == "configuration": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)
                    elif loss == "artifact": Artifact.objects.filter(job=before).update(created_at=actual())
                    elif loss == "step": JobStep.objects.filter(job=before).update(created_at=actual())
                    elif loss == "citation": SourceCitation.objects.filter(job=before).update(source_title="replacement")
                    elif loss == "usage": UsageReservation.objects.filter(job=before).update(actual_units=2)
                    elif loss == "cancel": JobCancellation.objects.create(job=before, requested_by=self.owner)
                    return result
                with patch.object(source, "_candidate_rows", side_effect=changed), patch("jobs.usage.timezone.now",
                    side_effect=lambda: ends if done[0] and loss == "expiry" else actual()), self.assertRaises((PermissionDenied, ValidationError, UsageLimitError)):
                    self.compare(before, after)
                self.assertTrue(done[0]); transaction.set_rollback(True)

    def test_actual_final_paired_source_loss_of_either_original_metadata_or_cancel_withholds(self):
        before = self.collected("terminal-before"); after = self.collected("terminal-after")
        original_read = source._read_pair_sources
        healthy = self.compare(before, after)
        for loss in ("artifact", "step", "citation", "status", "usage", "first_cancel", "second_cancel"):
            with self.subTest(loss=loss), transaction.atomic():
                calls, injected = [0], [False]
                def changed(*args):
                    result = original_read(*args); calls[0] += 1
                    if calls[0] == 2:
                        injected[0] = True
                        if loss == "artifact": Artifact.objects.filter(job=before).update(created_at=timezone.now())
                        elif loss == "step": JobStep.objects.filter(job=before).update(created_at=timezone.now())
                        elif loss == "citation": SourceCitation.objects.filter(job=before).update(source_title="replacement")
                        elif loss == "status": JobRun.objects.filter(pk=before.pk).update(status="failed")
                        elif loss == "usage": UsageReservation.objects.filter(job=before).update(actual_units=2)
                        else: JobCancellation.objects.create(job=before if loss == "first_cancel" else after, requested_by=self.owner)
                    return result
                with patch.object(source, "_read_pair_sources", side_effect=changed), self.assertRaises((PermissionDenied, ValidationError)):
                    self.compare(before, after)
                self.assertTrue(injected[0]); self.assertEqual(calls[0], 2); transaction.set_rollback(True)
        self.assertEqual(self.compare(before, after), healthy)
