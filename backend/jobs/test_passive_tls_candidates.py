from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from unittest import TestCase
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TransactionTestCase, override_settings

from config.test_foundations import TEST_STORAGES
from . import passive_header_collection as lifecycle
from . import passive_tls_collection as collector
from . import test_passive_tls_collection as fixtures
from . import test_passive_tls_evidence as evidence_fixtures
from .models import Finding, Opportunity, Recommendation
from .passive_certificate import observe_peer_certificate_dates
from .passive_tls_candidates import tls_review_candidates
from .passive_tls_evidence import minimized_tls_evidence


class TLSReviewCandidateTests(TestCase):
    def setUp(self):
        self.binding = deepcopy(evidence_fixtures.PassiveTLSEvidenceTests.BINDING)

    def collection(self, observed=datetime(2025, 1, 1, tzinfo=UTC), version="TLSv1.3", dates=True):
        observation = evidence_fixtures.PassiveTLSEvidenceTests().observation()
        observation["observed_at"] = observed.isoformat(timespec="microseconds")
        observation["certificate_dates"] = observe_peer_certificate_dates(
            {"notBefore": "Jan  1 00:00:00 2024 GMT", "notAfter": "Jan  1 00:00:00 2025 GMT"} if dates else None,
            observed_at=observed)
        observation["negotiated_tls"]["version"] = version
        return minimized_tls_evidence(observation, binding=self.binding)

    def test_exact_inclusive_original_window_and_signed_microseconds_have_no_warning_threshold(self):
        start = datetime(2024, 1, 1, tzinfo=UTC); end = datetime(2025, 1, 1, tzinfo=UTC)
        self.binding["verified_at"] = "2023-01-01T00:00:00+00:00"
        for observed, position in ((start - timedelta(microseconds=1), "before_reported_window"),
            (start, "within_reported_window"), (end - timedelta(microseconds=1), "within_reported_window"),
            (end, "within_reported_window"), (end + timedelta(microseconds=1), "after_reported_window")):
            with self.subTest(observed=observed):
                collection = self.collection(observed)
                report = tls_review_candidates(collection, binding=self.binding)
                self.assertEqual(report["collection"]["observed_at"], observed.isoformat(timespec="microseconds"))
                if position == "within_reported_window":
                    self.assertEqual(report["candidates"], [])
                else:
                    self.assertEqual(report["candidates"], [{"detector": "reported_certificate_date_outside_window_candidate",
                        "evidence": {"not_before": start.isoformat(timespec="microseconds"), "not_after": end.isoformat(timespec="microseconds"),
                            "position": position, "remaining_microseconds": str((end - observed) // timedelta(microseconds=1))}}])

    def test_actual_literal_versions_and_independent_nullable_date_version_availability(self):
        for dates in (True, False):
            for version in (None, "TLSv1", "TLSv1.1", "TLSv1.2", "TLSv1.3"):
                for cipher in (None, {"name": "TLS_AES_256_GCM_SHA384", "secret_bits": 256}):
                    with self.subTest(dates=dates, version=version, cipher=cipher):
                        collection = self.collection(version=version, dates=dates)
                        collection["evidence"]["negotiated_tls"]["cipher"] = cipher
                        report = tls_review_candidates(collection, binding=self.binding)
                        self.assertEqual(report["availability"], {"certificate_dates": "observed" if dates else "unavailable",
                            "negotiated_version": "unavailable" if version is None else "observed"})
                        self.assertEqual(report["candidates"], [{"detector": "negotiated_tlsv1_or_tlsv1_1_candidate", "evidence": {"version": version}}]
                            if version in {"TLSv1", "TLSv1.1"} else [])
                        if not dates:
                            self.assertTrue(all(report["collection"]["evidence"]["certificate_dates"][key] is None
                                for key in ("not_before", "not_after", "position", "remaining_microseconds")))

    def test_full_original_family_scope_shape_date_and_parameter_validation_fails_closed(self):
        collection = self.collection()
        for changes in ({"method_version": "passive-header-source-v1"}, {"collection_permission": 1}, {"actor_id": True},
            {"source_digest": "bad"}, {"origin": "https://foreign.example.invalid"}, {"observations": ["response_headers"]},
            {"raw": "private"}, {"verified_at": "2026-02-30T00:00:00+00:00"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                tls_review_candidates(collection, binding={**self.binding, **changes})
        mutations = (
            lambda row: row.update(status=200), lambda row: row.update(method="passive-resource-evidence-v1"),
            lambda row: row.update(observed_at="2025-01-01T00:00:00.000000Z"),
            lambda row: row["evidence"].update(observed_at="2025-01-01T00:00:00.000001+00:00"),
            lambda row: row["evidence"]["certificate_dates"].update(position="after_reported_window"),
            lambda row: row["evidence"]["certificate_dates"].update(remaining_microseconds=0),
            lambda row: row["evidence"]["certificate_dates"].update(remaining_microseconds="-0"),
            lambda row: row["evidence"]["certificate_dates"].update(not_after="2025-01-01T00:00:00.000001+00:00"),
            lambda row: row["evidence"]["certificate_dates"].update(state="unavailable"),
            lambda row: row["evidence"]["negotiated_tls"].update(version=True),
            lambda row: row["evidence"]["negotiated_tls"].update(version="SSLv3"),
            lambda row: row["evidence"]["negotiated_tls"]["cipher"].update(protocol="TLSv1"),
            lambda row: row["evidence"]["negotiated_tls"]["cipher"].update(secret_bits=True),
            lambda row: row["evidence"].update(subject="private"),
        )
        for mutate in mutations:
            row = deepcopy(collection); mutate(row)
            with self.subTest(mutate=mutate), self.assertRaises(ValidationError): tls_review_candidates(row, binding=self.binding)
        for value in (None, [], "private", {}):
            with self.assertRaises(ValidationError): tls_review_candidates(value, binding=self.binding)
            with self.assertRaises(ValidationError): tls_review_candidates(collection, binding=value)

    def test_two_literal_facts_preserve_fresh_originals_privacy_and_no_current_authority(self):
        collection = self.collection(datetime(2025, 1, 1, 0, 0, 0, 1, tzinfo=UTC), "TLSv1.1")
        original = deepcopy((collection, self.binding))
        with patch("socket.create_connection", side_effect=AssertionError("No network")), patch.object(
            lifecycle, "read_project_artifact", side_effect=AssertionError("No private I/O")):
            report = tls_review_candidates(collection, binding=self.binding)
        self.assertEqual(len(report["candidates"]), 2)
        self.assertEqual(report["candidates"][0]["evidence"]["remaining_microseconds"], "-1")
        self.assertFalse({"job_id", "source_current", "severity", "priority", "score"} & set(report))
        for private in ("OCSP", "subject", "serial", "raw_certificate", "private", "http://127.0.0.1"):
            self.assertNotIn(private, json.dumps(report))
        report["candidates"][0]["evidence"]["remaining_microseconds"] = "0"
        report["candidates"][1]["evidence"]["version"] = "TLSv1.3"
        report["collection"]["evidence"]["negotiated_tls"]["version"] = "changed"
        report["binding"]["observations"].append("raw")
        self.assertEqual((collection, self.binding), original)


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json"}))
class OriginalTLSReviewCandidateTests(TransactionTestCase):
    setUp = fixtures.PassiveTLSCollectionTests.setUp
    verified = fixtures.PassiveTLSCollectionTests.verified
    queue = fixtures.PassiveTLSCollectionTests.queue
    transport = fixtures.PassiveTLSCollectionTests.transport

    def test_genuine_original_verifier_handshake_private_readback_to_pure_no_io_projection(self):
        job = self.queue()
        fetcher = self.transport()
        # Literal version fixture; no real obsolete-protocol connection or relaxed validation.
        self.connection.sock.version.return_value = "TLSv1.1"
        with patch("socket.create_connection", side_effect=AssertionError("No real network")):
            self.assertTrue(collector.execute_passive_tls_collection(job.pk, fetcher=fetcher))
        job.refresh_from_db()
        source = collector.read_passive_tls_observation(project=self.project, actor=self.owner, job_id=job.pk)
        original = deepcopy(source)
        with self.assertNumQueries(0), patch.object(lifecycle, "read_project_artifact", side_effect=AssertionError("No I/O")), patch(
            "socket.create_connection", side_effect=AssertionError("No network")):
            report = tls_review_candidates(source["collection"], binding=job.config_snapshot["binding"])
        self.assertEqual(source, original)
        self.assertEqual(report["collection"]["observed_at"], job.output["observed_at"])
        self.assertEqual(report["candidates"], [{"detector": "negotiated_tlsv1_or_tlsv1_1_candidate", "evidence": {"version": "TLSv1.1"}}])
        self.assertEqual(report["binding"], job.config_snapshot["binding"])
        for private in (self.challenge, self.verification.challenge_digest, self.owner.email, "private"):
            self.assertNotIn(private, json.dumps(report))
        self.assertEqual((Finding.objects.count(), Opportunity.objects.count(), Recommendation.objects.count()), (0, 0, 0))
        self.connection.connect.assert_called_once(); self.connection.request.assert_not_called()
