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
from tenancy.models import OrganizationMembership

from . import crux_threshold_policy as policy, test_crux_history_source as fixtures
from .models import Artifact, PerformanceObservationSnapshot


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}),
                   GOOGLE_PERFORMANCE_API_KEY="fixture_key_with_32_placeholder_chars")
class MaterialCruxSourceTests(TransactionTestCase):
    setUp = fixtures.CruxHistorySourceTests.setUp
    date_part = staticmethod(fixtures.CruxHistorySourceTests.date_part)
    history = fixtures.CruxHistorySourceTests.history
    collect = fixtures.CruxHistorySourceTests.collect

    def inspect(self, row):
        return policy.current_material_crux_source(project=self.project, actor=self.owner, observation_id=row.pk)

    def all_metrics(self, lcp=(2500, 3000), inp=(200, 250), cls=("0.10", "0.15")):
        payload = self.history(lcp, count=2)
        payload["record"]["metrics"]["interaction_to_next_paint"]["percentilesTimeseries"]["p75s"] = list(inp)
        payload["record"]["metrics"]["cumulative_layout_shift"]["percentilesTimeseries"]["p75s"] = list(cls)
        return payload

    def test_actual_worker_all_inclusive_floors_stable_full_source_pin_and_read_only(self):
        row = self.collect(self.all_metrics())
        with CaptureQueriesContext(connection) as queries, patch("http.client.HTTPSConnection.request", side_effect=AssertionError("network")):
            result = self.inspect(row)
        self.assertFalse(any(query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for query in queries))
        self.assertEqual(result["state"], "assessed_original_field_threshold_candidates")
        self.assertEqual([item["state"] for item in result["rows"]], ["material_threshold_worsening_candidate"] * 3)
        self.assertEqual([item["absolute_increase"] for item in result["rows"]], ["500", "50", "0.05"])
        self.assertTrue(all(item["absolute_floor_met"] and item["relative_floor_met"] for item in result["rows"]))
        self.assertEqual(result["source"]["comparisons"][0]["overlap_calendar_days"], 21)
        self.assertEqual(len(result["source_fingerprint"]), 64)
        self.assertEqual(result["source_fingerprint"], self.inspect(row)["source_fingerprint"])
        self.assertTrue(all(item["sample_sufficiency"] == item["statistical_significance"] == "unknown" for item in result["rows"]))
        for private in (self.target, self.owner.email, row.raw_artifact.key, "performance_credential", "TTFB"):
            self.assertNotIn(private, json.dumps(result))
        # Bind even metadata invisible to the minimized rows, without pretending it is immutable.
        Artifact.objects.filter(pk=row.raw_artifact_id).update(created_at=row.raw_artifact.created_at + timedelta(microseconds=1))
        self.assertNotEqual(result["source_fingerprint"], self.inspect(row)["source_fingerprint"])

    def test_absolute_relative_and_grade_gates_do_not_promote_small_crossing_or_large_within_grade_changes(self):
        cases = [((2500, 2999), "below_material_change_floor", False, False),
                 ((4000, 4500), "below_material_change_floor", True, False),
                 ((1000, 2000), "no_threshold_worsening_observed", None, None),
                 ((4001, 8000), "no_threshold_worsening_observed", None, None),
                 ((2400, 4001), "material_threshold_worsening_candidate", True, True)]
        for index, (values, state, absolute, relative) in enumerate(cases):
            with self.subTest(values=values):
                row = self.collect(self.all_metrics(lcp=values), key=f"material-{index}")
                result = self.inspect(row)["rows"][0]
                self.assertEqual(result["state"], state)
                self.assertEqual(result["absolute_floor_met"], absolute)
                self.assertEqual(result["relative_floor_met"], relative)

    def test_exact_cls_edges_zero_baseline_and_bounded_exotic_precision(self):
        cases = [(("0.1", "0.149999999999999999"), "below_material_change_floor"),
                 (("0.1", "0.150000000000000001"), "material_threshold_worsening_candidate"),
                 (("0.25", "0.30"), "material_threshold_worsening_candidate"),
                 (("0.25", "0.299999999999999999"), "below_material_change_floor"),
                 (("0E+999999", "0.15"), "unknown_relative_zero_baseline"),
                 (("1E-100000", "0.15"), "unknown_exact_numeric_precision")]
        for index, (values, state) in enumerate(cases):
            with self.subTest(values=values):
                row = self.collect(self.all_metrics(cls=values), key=f"decimal-{index}")
                self.assertEqual(self.inspect(row)["rows"][2]["state"], state)
        row = self.collect(self.all_metrics(lcp=(0, 4001)), key="integer-zero")
        self.assertEqual(self.inspect(row)["rows"][0]["state"], "unknown_relative_zero_baseline")

    def test_missing_latest_legacy_and_actual_incomparable_periods_never_fallback(self):
        row = self.collect(self.history((2400, 4001, None)), key="missing-latest")
        self.assertEqual(self.inspect(row)["rows"][0]["state"], "unknown_insufficient_eligible_periods")
        payload = self.all_metrics()
        end = timezone.now().date() - timedelta(days=2)
        payload["record"]["collectionPeriods"][1]["firstDate"] = self.date_part(end - timedelta(days=26))
        row = self.collect(payload, key="nonstandard")
        self.assertTrue(row.output["rolling_windows_overlap"])
        self.assertEqual(self.inspect(row)["rows"][0]["state"], "incomparable_source_periods")
        PerformanceObservationSnapshot.objects.filter(pk=row.pk).update(raw_sha256=None)
        with patch("jobs.crux_history_source.read_private_artifact", side_effect=AssertionError("legacy read")):
            result = self.inspect(row)
        self.assertEqual(result["state"], "unknown_original_raw_integrity")
        self.assertEqual(result["rows"], [])
        self.assertIsNone(result["source"]["raw_sha256"])

    def test_current_original_source_reader_and_private_integrity_fences_after_policy_projection(self):
        row = self.collect(self.all_metrics())
        project = deepcopy(self.project)
        project.organization_id += 10000
        with self.assertRaises(PermissionDenied):
            policy.current_material_crux_source(project=project, actor=self.owner, observation_id=row.pk)
        for invalid in (True, 0, -1, "1", 2**53):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                policy.current_material_crux_source(project=self.project, actor=self.owner, observation_id=invalid)
        original = policy._rows
        for mutate in [lambda: Artifact.objects.filter(pk=row.raw_artifact_id).update(created_at=row.raw_artifact.created_at + timedelta(microseconds=1)),
                       lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")]:
            with transaction.atomic():
                def changed(source):
                    result = original(source)
                    mutate()
                    return result
                with patch("jobs.crux_threshold_policy._rows", side_effect=changed), self.assertRaises((PermissionDenied, ValidationError)):
                    self.inspect(row)
                transaction.set_rollback(True)
        with patch("jobs.crux_history_source.read_private_artifact", return_value=b"tampered"), self.assertRaises(ValidationError):
            self.inspect(row)
