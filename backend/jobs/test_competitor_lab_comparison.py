import json
from datetime import timedelta
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from providers.models import OrganizationPerformanceKey
from tenancy.models import OrganizationMembership, OrganizationTrial, Project, ProjectConfiguration
from . import competitor_collection as lifecycle, competitor_lab_collection as collection, competitor_lab_comparison as comparison
from . import test_competitor_lab_collection as fixtures, test_competitor_lab as lab_fixtures
from . import test_competitor_comparison as pair_fixtures, test_competitor_collection as root_fixtures
from .competitor_lab import LAB_AUDITS, SCORES
from .models import Artifact, JobCancellation, JobRun, UsageReservation
from .usage import UsageLimitError


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, PERFORMANCE_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),), GOOGLE_PERFORMANCE_API_KEY="",
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}))
class CompetitorLabComparisonTests(TransactionTestCase):
    setUp = fixtures.CompetitorLabCollectionTests.setUp
    queue = fixtures.CompetitorLabCollectionTests.queue
    fetcher = fixtures.CompetitorLabCollectionTests.fetcher
    transport = fixtures.CompetitorLabCollectionTests.transport
    revoke = fixtures.CompetitorLabCollectionTests.revoke

    def collected(self, key, payload=None, **changes):
        job = self.queue(key, **changes)
        original = self.data
        self.data = job.input_snapshot
        try:
            if payload is None:
                self.samples = getattr(self, "samples", 0) + 1
                payload = lab_fixtures.CompetitorLabTests().payload(url=self.data["url"], strategy=self.data["strategy"])
                payload["lighthouseResult"]["fetchTime"] = f"2026-01-01T00:00:{self.samples:02d}Z"
            with patch("socket.create_connection", side_effect=AssertionError("No actual egress")):
                self.assertTrue(collection.execute_competitor_lab_collection(job.pk, fetcher=self.fetcher(payload=payload)))
        finally: self.data = original
        job.refresh_from_db(); self.assertEqual(job.status, "succeeded", job.error_category)
        return job

    def compare(self, before, after, **changes):
        return comparison.compare_competitor_lab(**{**dict(project=self.project, actor=self.owner,
            previous_job_id=before.pk, current_job_id=after.pk), **changes})

    def payload(self):
        payload = lab_fixtures.CompetitorLabTests().payload(url=self.data["url"])
        payload["lighthouseResult"]["fetchTime"] = "2026-01-01T03:00:20+03:00"
        return payload

    def test_genuine_original_pair_independent_reader_nullable_arithmetic_provenance_no_write_or_request(self):
        before = self.collected("before")
        payload = self.payload(); lab = payload["lighthouseResult"]
        lab["categories"]["performance"]["score"] = 0.5
        lab["audits"]["largest-contentful-paint"]["numericValue"] = 2000
        after = self.collected("after", payload)
        connection.queries_log.clear()  # The fixture jobs must not saturate the bounded SQL capture.
        with (patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No fetch")),
              patch("socket.getaddrinfo", side_effect=AssertionError("No DNS")),
              patch("providers.performance_key._cipher", side_effect=AssertionError("No decryption")), CaptureQueriesContext(connection) as queries):
            result = self.compare(before, after, actor=self.admin)
        self.assertGreater(len(queries), 0)
        self.assertLess(len(queries), connection.queries_log.maxlen)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual((result["method_version"], result["interpretation"], result["state"], result["reason"]),
            (comparison.METHOD, comparison.INTERPRETATION, "arithmetic_original_lab_samples", ""))
        self.assertEqual(result["score_deltas"], {"performance": -0.25, "accessibility": 0, "best-practices": None, "seo": None})
        self.assertEqual(result["audit_deltas"]["largest-contentful-paint"], {"value": -1000, "unit": "ms"})
        self.assertEqual(result["audit_deltas"]["total-blocking-time"], {"value": None, "unit": "ms"})
        self.assertEqual(result["previous"]["evidence"], before.output["evidence"])
        self.assertEqual(result["current"]["evidence"], after.output["evidence"])
        self.assertEqual(result["current"]["request_started_at"], after.output["request_started_at"])
        self.assertTrue(result["body_changed"]); self.assertEqual(result["selection_sha256"], before.config_snapshot["binding"]["selection_sha256"])
        self.assertLessEqual(len(lifecycle._encode(result)), comparison.MAX_RESULT_BYTES)
        for secret in ("private", "fixture_org_key", "loadingExperience", "artifact_id", self.owner.email): self.assertNotIn(secret, json.dumps(result))
        result["previous"]["evidence"]["lab"]["scores"]["performance"] = 0
        self.assertEqual(self.compare(before, after)["previous"]["evidence"], before.output["evidence"])

    def test_known_zero_and_individual_missing_values_preserve_units_without_an_aggregate(self):
        payload = self.payload(); payload["lighthouseResult"]["fetchTime"] = "2026-01-01T00:00:01Z"
        payload["lighthouseResult"]["categories"] = {}
        payload["lighthouseResult"]["audits"] = {key: {"numericValue": 0} for key in LAB_AUDITS}
        before = self.collected("zero", payload)
        after = self.collected("nullable", self.payload())
        result = self.compare(before, after)
        self.assertTrue(all(value is None for value in result["score_deltas"].values()))
        self.assertEqual(result["audit_deltas"]["largest-contentful-paint"]["value"], 3000)
        self.assertEqual(result["audit_deltas"]["cumulative-layout-shift"]["value"], 0.15)
        self.assertIsNone(result["audit_deltas"]["speed-index"]["value"])
        self.assertFalse({"grade", "aggregate", "field_data", "statistical_significance"} & set(result))
        self.assertEqual(set(result["score_deltas"]), set(SCORES))

    def test_unavailable_versions_and_nonincreasing_reported_times_retain_originals_with_null_differences(self):
        before = self.collected("original")
        changes = (("runtime", "lab_unavailable"), ("version", "lighthouse_version_unavailable_or_changed"),
            ("unknown", "lighthouse_version_unavailable_or_changed"), ("equal", "provider_report_time_not_increasing"),
            ("older", "provider_report_time_not_increasing"))
        for key, reason in changes:
            payload = self.payload(); lab = payload["lighthouseResult"]
            if key == "runtime": lab["runtimeError"] = {"code": "private", "message": "secret"}
            elif key == "version": lab["lighthouseVersion"] = "13.0.0"
            elif key == "unknown": lab["lighthouseVersion"] = "unknown"
            elif key == "equal": lab["fetchTime"] = "2026-01-01T03:00:01+03:00"
            else: lab["fetchTime"] = "2025-12-31T23:00:00Z"
            after = self.collected(key, payload); result = self.compare(before, after)
            self.assertEqual((result["state"], result["reason"]), ("incomparable_lab_samples", reason))
            self.assertTrue(all(value is None for value in result["score_deltas"].values()))
            self.assertTrue(all(value["value"] is None for value in result["audit_deltas"].values()))
            self.assertEqual(result["current"]["evidence"], after.output["evidence"])

    def test_exact_ids_project_actor_uri_device_and_failed_jobs_cannot_supply_a_pair(self):
        before = self.collected("scope-before"); after = self.collected("scope-after")
        for value in (True, 0, -1, 2**53, str(before.pk), None):
            with self.assertRaises(ValidationError): self.compare(before, after, previous_job_id=value)
        with self.assertRaises(ValidationError): self.compare(before, before)
        with self.assertRaises(ValidationError): self.compare(after, before)
        other_project = Project.objects.create(organization=self.organization, name="Other", canonical_origin="https://other-owned.example.invalid")
        for changes in ({"actor": self.foreign}, {"project": other_project}):
            with self.assertRaises(PermissionDenied): self.compare(before, after, **changes)
        for key, changes in (("device", {"data": {**self.data, "strategy": "desktop"}}),
            ("uri", {"data": {**self.data, "url": self.data["url"] + "-other"}}), ("actor", {"actor": self.admin})):
            different = self.collected(key, **changes)
            with self.assertRaises(ValidationError): self.compare(before, different)
        waiting = self.queue("waiting")
        with patch.object(lifecycle, "read_project_artifact", side_effect=AssertionError("No queued private read")), self.assertRaises(PermissionDenied):
            self.compare(before, waiting)
        ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[])
        with self.assertRaises((PermissionDenied, ValidationError)): self.compare(before, after)

    def test_all_static_pairs_ai_sources_and_actual_static_jobs_are_separate_from_lab_pairs(self):
        before = self.collected("family-before"); after = self.collected("family-after")
        from .competitor_comparison import compare_competitor_roots
        from .competitor_page_comparison import compare_competitor_pages
        from .competitor_schema_comparison import compare_competitor_schema_roots
        from .competitor_links_comparison import compare_competitor_links_roots
        from .competitor_headings_comparison import compare_competitor_page_headings
        from .competitor_destinations_comparison import compare_competitor_page_destinations
        from .competitor_dates_comparison import compare_competitor_page_dates
        from .competitor_synthesis import read_competitor_synthesis_source
        from .competitor_headings_synthesis import read_competitor_headings_synthesis_source
        for read in (compare_competitor_roots, compare_competitor_pages, compare_competitor_schema_roots,
            compare_competitor_links_roots, compare_competitor_page_headings, compare_competitor_page_destinations, compare_competitor_page_dates):
            with self.assertRaises(PermissionDenied): read(project=self.project, actor=self.owner, previous_job_id=before.pk, current_job_id=after.pk)
        for read in (read_competitor_synthesis_source, read_competitor_headings_synthesis_source):
            with self.assertRaises(PermissionDenied): read(project=self.project, actor=self.owner, previous_job_id=before.pk, current_job_id=after.pk, ai_processing_permission=True)
        root_data = {key: value for key, value in self.data.items() if key not in {"url", "strategy", "provider_processing_permission"}}
        for handler in lifecycle.COMPETITOR_HANDLERS:
            data = {**root_data, "url": self.data["url"]} if handler in {"collect_competitor_page", "collect_competitor_page_headings", "collect_competitor_page_destinations", "collect_competitor_page_dates", "collect_competitor_page_formats"} else root_data
            job = root_fixtures.CompetitorCollectionTests.queue(self, handler, handler=handler, data=data)
            with patch("socket.create_connection", side_effect=AssertionError("No actual egress")):
                self.assertTrue(lifecycle.execute_competitor_collection(job.pk, handler=handler, fetcher=root_fixtures.CompetitorCollectionTests.fetcher(self)))
            with self.assertRaises(PermissionDenied): self.compare(before, job)

    def test_late_actual_private_read_original_actor_caller_key_configuration_bytes_and_expiry_withhold_pair(self):
        before = self.collected("late-before"); after = self.collected("late-after")
        reader = lifecycle.read_project_artifact; artifact = before.artifacts.get()
        for loss in ("artifact", "actor", "caller", "key", "configuration", "expiry"):
            with self.subTest(loss=loss), transaction.atomic():
                calls = [0]
                def changed(**kwargs):
                    content = reader(**kwargs); calls[0] += 1
                    if calls[0] == 2:
                        if loss == "artifact": Artifact.objects.filter(pk=artifact.pk).update(size_bytes=artifact.size_bytes + 1)
                        elif loss == "actor": self.revoke()
                        elif loss == "caller": OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer")
                        elif loss == "key": OrganizationPerformanceKey.objects.filter(pk=self.key.pk).update(rotated_at=timezone.now())
                        elif loss == "configuration": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)
                        else:
                            now = timezone.now(); OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now-timedelta(days=31), ends_at=now-timedelta(days=1))
                    return content
                with patch.object(lifecycle, "read_project_artifact", side_effect=changed), self.assertRaises((PermissionDenied, ValidationError, UsageLimitError)):
                    self.compare(before, after, actor=self.admin)
                transaction.set_rollback(True)
        with patch.object(lifecycle, "read_project_artifact", return_value=b"{}"), self.assertRaises(ValidationError): self.compare(before, after)
        self.assertEqual(JobRun.objects.filter(handler=collection.HANDLER).count(), 2)

    test_last_second_metadata_return_fences_both_original_sources_and_independent_caller = pair_fixtures.CompetitorComparisonTests.test_last_second_metadata_return_fences_both_original_sources_and_independent_caller
    test_first_original_cancellation_during_last_second_source_read_withholds_whole_private_pair = pair_fixtures.CompetitorComparisonTests.test_first_original_cancellation_during_last_second_source_read_withholds_whole_private_pair

    def test_last_lab_pair_source_first_metadata_status_usage_and_both_cancellations_withhold(self):
        before = self.collected("terminal-lab-before"); after = self.collected("terminal-lab-after")
        source = comparison._read_pair_sources
        expected = self.compare(before, after, actor=self.admin)
        for loss in ("artifact", "status", "usage", "first-cancel", "second-cancel"):
            with self.subTest(loss=loss), transaction.atomic():
                calls = 0
                def last(*args):
                    nonlocal calls
                    result = source(*args); calls += 1
                    if calls == 2:
                        if loss == "artifact": Artifact.objects.filter(job=before).update(size_bytes=1)
                        elif loss == "status": JobRun.objects.filter(pk=before.pk).update(status="failed")
                        elif loss == "usage": UsageReservation.objects.filter(job=before).update(actual_units=2)
                        else: JobCancellation.objects.create(job=before if loss == "first-cancel" else after, requested_by=self.owner)
                    return result
                with patch.object(comparison, "_read_pair_sources", side_effect=last), self.assertRaises(PermissionDenied):
                    self.compare(before, after, actor=self.admin)
                self.assertEqual(calls, 2)
                transaction.set_rollback(True)
        self.assertEqual(self.compare(before, after, actor=self.admin), expected)
