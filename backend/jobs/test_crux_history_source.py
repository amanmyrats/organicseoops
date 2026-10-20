from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.artifacts import read_private_artifact
from config.test_foundations import TEST_STORAGES
from providers.models import OrganizationPerformanceKey
from tenancy.models import DomainAlias, OrganizationMembership

from . import crux_history_source as source
from .models import Artifact, JobRun, JobStep, PerformanceObservationSnapshot
from .performance_job import execute_performance_audit
from . import test_performance_job as fixtures


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}),
                   GOOGLE_PERFORMANCE_API_KEY="fixture_key_with_32_placeholder_chars")
class CruxHistorySourceTests(TransactionTestCase):
    setUp = fixtures.PerformanceSnapshotTests.setUp
    date_part = staticmethod(fixtures.PerformanceSnapshotTests.date_part)

    def history(self, values=(2400, 2400, 4001), *, count=3):
        end = timezone.now().date() - timedelta(days=2)
        def period(last):
            return {"firstDate": self.date_part(last - timedelta(days=27)), "lastDate": self.date_part(last)}
        return {"record": {"key": {"url": self.target, "formFactor": "PHONE"},
            "collectionPeriods": [period(end - timedelta(days=7 * (count - index - 1))) for index in range(count)],
            "metrics": {"largest_contentful_paint": {"percentilesTimeseries": {"p75s": list(values)}},
                        "interaction_to_next_paint": {"percentilesTimeseries": {"p75s": [200] * count}},
                        "cumulative_layout_shift": {"percentilesTimeseries": {"p75s": ["0.10"] * count}}}}}

    def collect(self, payload=None, *, key="source-fixture", strategy="mobile", grain="page"):
        from .performance_job import queue_performance_audit
        with patch("jobs.services.dispatch_pending"):
            job = queue_performance_audit(project=self.project, actor=self.owner,
                target=self.target if grain == "page" else self.project.canonical_origin,
                grain=grain, strategy=strategy, sources=["crux_history"], idempotency_key=key)
        self.assertTrue(execute_performance_audit(job.pk, fetch=lambda **_: payload or self.history()))
        return PerformanceObservationSnapshot.objects.select_related("raw_artifact").get(job=job)

    def inspect(self, row):
        return source.current_crux_history_source(project=self.project, actor=self.owner, observation_id=row.pk)

    def test_genuine_worker_last_two_original_periods_privacy_and_read_only(self):
        row = self.collect()
        with CaptureQueriesContext(connection) as queries, \
                patch("http.client.HTTPSConnection.request", side_effect=AssertionError("source network")):
            result = self.inspect(row)
        self.assertFalse(any(query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for query in queries))
        self.assertEqual(result["state"], "available_original_field_history")
        self.assertEqual(result["raw_sha256"], row.raw_sha256)
        lcp, inp, cls = result["comparisons"]
        self.assertEqual([item["state"] for item in (lcp, inp, cls)],
                         ["threshold_worsening_candidate", "no_threshold_worsening_observed", "no_threshold_worsening_observed"])
        self.assertEqual([item["calendar_days"] for item in (entry["period"] for entry in lcp["observations"])], [28, 28])
        self.assertEqual(lcp["overlap_calendar_days"], 21)
        self.assertEqual(lcp["sample_count"], "unknown")
        self.assertTrue(all(entry["period"]["eligible_days"] == "unknown" for entry in lcp["observations"]))
        for private in (self.target, self.owner.email, row.raw_artifact.key, "performance_credential", "TTFB"):
            self.assertNotIn(private, json.dumps(result))
        self.assertNotIn("rolling_windows_overlap", result)

    def test_missing_latest_no_older_fallback_one_period_and_grade_edges(self):
        for index, (values, state) in enumerate([
                ((2400, 4001, None), "unknown_insufficient_eligible_periods"),
                ((2400, "NaN", 4001), "unknown_insufficient_eligible_periods"),
                ((2500,), "unknown_insufficient_eligible_periods"),
                ((2400, 2500, 4000), "threshold_worsening_candidate"),
                ((2400, 4000, 4000), "no_threshold_worsening_observed"),
                ((2400, 4001, 4000), "no_threshold_worsening_observed")]):
            with self.subTest(values=values):
                row = self.collect(self.history(values, count=len(values)), key=f"period-{index}")
                comparison = self.inspect(row)["comparisons"][0]
                self.assertEqual(comparison["state"], state)
                self.assertEqual(len(comparison["observations"]), min(2, len(values)))
        self.assertEqual(PerformanceObservationSnapshot.objects.count(), 6)

    def test_actual_nonstandard_windows_do_not_borrow_historical_overlap_label(self):
        for index, (length, cadence) in enumerate(((27, 7), (28, 28), (28, 8))):
            payload = self.history((2400, 4001), count=2)
            last = timezone.now().date() - timedelta(days=2)
            payload["record"]["collectionPeriods"] = [{
                "firstDate": self.date_part(end - timedelta(days=length - 1)), "lastDate": self.date_part(end)}
                for end in (last - timedelta(days=cadence), last)]
            row = self.collect(payload, key=f"nonstandard-{index}")
            self.assertTrue(row.output["rolling_windows_overlap"])
            comparison = self.inspect(row)["comparisons"][0]
            self.assertEqual(comparison["state"], "incomparable_source_periods")
            self.assertEqual(comparison["overlap_calendar_days"], max(0, length - cadence))
            self.assertEqual(comparison["observations"][0]["period"]["calendar_days"], length)
        future = self.history((2400, 4001), count=2)
        end = timezone.now().date() + timedelta(days=1)
        future["record"]["collectionPeriods"] = [{"firstDate": self.date_part(last - timedelta(days=27)),
            "lastDate": self.date_part(last)} for last in (end - timedelta(days=7), end)]
        row = self.collect(future, key="future-original-period")
        with self.assertRaises(ValidationError):
            self.inspect(row)

    def test_dimensions_origin_fallback_desktop_and_origin_request(self):
        for index, (strategy, grain, observed) in enumerate([
                ("mobile", "page", "origin"), ("desktop", "page", "url"), ("tablet", "origin", "origin")]):
            payload = self.history()
            payload["record"]["key"] = {observed: self.project.canonical_origin if observed == "origin" else self.target,
                "formFactor": {"mobile": "PHONE", "desktop": "DESKTOP", "tablet": "TABLET"}[strategy]}
            row = self.collect(payload, key=f"dimensions-{index}", strategy=strategy, grain=grain)
            result = self.inspect(row)
            self.assertEqual(result["form_factor"], payload["record"]["key"]["formFactor"])
            self.assertEqual(result["origin_fallback"], grain == "page" and observed == "origin")
            self.assertEqual(result["observed_grain"], "origin" if observed == "origin" else "page")

    def test_legacy_unknown_no_raw_read_and_exact_foreign_or_invalid_selection_denial(self):
        row = self.collect()
        PerformanceObservationSnapshot.objects.filter(pk=row.pk).update(raw_sha256=None)
        with patch("jobs.crux_history_source.read_private_artifact", side_effect=AssertionError("legacy reconstruction")):
            self.assertEqual(self.inspect(row)["state"], "unknown_original_raw_integrity")
        self.assertIsNone(PerformanceObservationSnapshot.objects.get(pk=row.pk).raw_sha256)
        for invalid in (True, 0, -1, "1", 2**53):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                source.current_crux_history_source(project=self.project, actor=self.owner, observation_id=invalid)
        with self.assertRaises(PermissionDenied):
            source.current_crux_history_source(project=self.project, actor=self.owner, observation_id=row.pk + 10000)
        outsider = get_user_model().objects.create_user("crux-outsider@example.invalid", password="fixture-password")
        with self.assertRaises(PermissionDenied):
            source.current_crux_history_source(project=self.project, actor=outsider, observation_id=row.pk)

    def test_original_raw_tamper_and_strict_canonical_decode_typed_output(self):
        row = self.collect()
        raw = read_private_artifact(row.raw_artifact.key)
        with patch("jobs.crux_history_source.read_private_artifact", return_value=raw.replace(b"4001", b"4002")), \
                self.assertRaises(ValidationError):
            self.inspect(row)
        malformed = [b'{"record":{},"record":{}}', b'{"value":NaN}', b'{"value":1e999}', b'\xff',
                     b'{"deep":' + b'[' * 1100 + b'0' + b']' * 1100 + b'}', b' ' + raw]
        for data in malformed:
            # Explicit corruption fixtures bypass capture to exercise strict decode beyond SHA/size checks.
            with self.subTest(data=data[:20]), transaction.atomic():
                Artifact.objects.filter(pk=row.raw_artifact_id).update(size_bytes=len(data))
                PerformanceObservationSnapshot.objects.filter(pk=row.pk).update(raw_sha256=sha256(data).hexdigest())
                with patch("jobs.crux_history_source.read_private_artifact", return_value=data), self.assertRaises(ValidationError):
                    self.inspect(row)
                transaction.set_rollback(True)
        output = deepcopy(row.output)
        output["origin_fallback"] = 0  # Python equality alone would let false == 0 borrow original output.
        PerformanceObservationSnapshot.objects.filter(pk=row.pk).update(output=output)
        with self.assertRaises(ValidationError):
            self.inspect(row)

    def test_final_complete_source_and_reader_fence_after_private_io_or_projection(self):
        row = self.collect()
        original = source.read_private_artifact
        mutations = [
            lambda: JobStep.objects.filter(job_id=row.job_id).update(progress_percent=1),
            lambda: JobRun.objects.filter(pk=row.job_id).update(config_snapshot={**row.job.config_snapshot, "extra": "drift"}),
            lambda: DomainAlias.objects.create(project=self.project, organization=self.organization, origin="https://alias.measured.example"),
            lambda: get_user_model().objects.filter(pk=self.owner.pk).update(is_active=False),
            lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer"),
            lambda: OrganizationPerformanceKey.objects.create(organization=self.organization, state="revoked",
                encrypted_secret="", rotated_at=timezone.now()),
            lambda: PerformanceObservationSnapshot.objects.filter(pk=row.pk).update(raw_sha256=None),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate), transaction.atomic():
                def changed(key):
                    data = original(key); mutate(); return data
                with patch("jobs.crux_history_source.read_private_artifact", side_effect=changed), \
                        self.assertRaises((PermissionDenied, ValidationError)):
                    self.inspect(row)
                transaction.set_rollback(True)
        comparisons = source._comparisons
        with transaction.atomic():
            def changed_projection(output):
                result = comparisons(output)
                Artifact.objects.filter(pk=row.raw_artifact_id).update(created_at=row.raw_artifact.created_at + timedelta(microseconds=1))
                return result
            with patch("jobs.crux_history_source._comparisons", side_effect=changed_projection), \
                    self.assertRaises((PermissionDenied, ValidationError)):
                self.inspect(row)
            transaction.set_rollback(True)

    def test_foreign_project_original_actor_credential_step_and_artifact_binding(self):
        from allauth.account.models import EmailAddress
        from tenancy.models import OrganizationTrial
        from tenancy.services import create_organization, create_project
        row = self.collect()
        viewer = get_user_model().objects.create_user("crux-reader@example.invalid", password="fixture-password")
        EmailAddress.objects.create(user=viewer, email=viewer.email, verified=True, primary=True)
        other_org = create_organization(user=viewer, name="Other source scope")
        other_project = create_project(organization=other_org, user=viewer, name="Other exact scope",
                                       canonical_origin="https://other-crux.example.invalid")
        with self.assertRaises(PermissionDenied):
            source.current_crux_history_source(project=other_project, actor=viewer, observation_id=row.pk)
        OrganizationMembership.objects.create(organization=self.organization, user=viewer, role="viewer")
        trial = OrganizationTrial.objects.get(organization=self.organization)
        OrganizationTrial.objects.filter(pk=trial.pk).update(ends_at=trial.started_at + timedelta(microseconds=1))
        self.assertEqual(source.current_crux_history_source(project=self.project, actor=viewer,
            observation_id=row.pk)["state"], "available_original_field_history")  # Read-only source, no paid work.
        mutations = [
            lambda: JobStep.objects.filter(job_id=row.job_id).update(output={"source": "crux_history", "state": "recorded", "snapshot_id": True}),
            lambda: Artifact.objects.filter(pk=row.raw_artifact_id).update(project_id=other_project.pk),
            lambda: Artifact.objects.filter(pk=row.raw_artifact_id).update(size_bytes=0),
            lambda: JobRun.objects.filter(pk=row.job_id).update(config_snapshot=[]),
            lambda: JobRun.objects.filter(pk=row.job_id).update(method_version="unsupported"),
            lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer"),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate), transaction.atomic():
                mutate()
                with self.assertRaises((PermissionDenied, ValidationError)):
                    source.current_crux_history_source(project=self.project, actor=viewer, observation_id=row.pk)
                transaction.set_rollback(True)
