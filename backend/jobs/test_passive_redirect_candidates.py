from copy import deepcopy
from datetime import datetime, timedelta
import json
from unittest import TestCase
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TransactionTestCase, override_settings

from config.test_foundations import TEST_STORAGES
from . import passive_header_collection as lifecycle
from . import passive_redirect_collection as collector
from . import test_passive_redirect_collection as fixtures
from . import test_passive_redirect_evidence as evidence_fixtures
from .models import Finding, Opportunity, Recommendation
from .passive_redirect_candidates import redirect_review_candidates


class RedirectReviewCandidateTests(TestCase):
    def setUp(self):
        self.binding = deepcopy(evidence_fixtures.PassiveRedirectEvidenceTests.BINDING)
        self.original = evidence_fixtures.PassiveRedirectEvidenceTests()
        self.addCleanup(self.original.doCleanups)

    def collection(self, status=302, fields=b"Location: http://private.invalid/?secret=value\r\n"):
        return self.original.result(f"HTTP/1.1 {status} Example\r\n".encode() + fields + b"\r\n")

    def test_literal_http_reference_preserves_actual_status_without_inventing_followed_redirection(self):
        for status in (200, 201, 300, 301, 302, 303, 304, 307, 308, 404, 599):
            with self.subTest(status=status):
                collection = self.collection(status)
                report = redirect_review_candidates(collection, binding=self.binding)
                self.assertEqual(report["candidates"], [{"detector": "http_scheme_location_reference_candidate", "evidence": {
                    "response_status": status, "redirect_status": status in {301, 302, 303, 307, 308},
                    "location_state": "single_classified", "target_scheme": "http", "same_origin": False}}])
                self.assertEqual(report["availability"], {"target_metadata": "observed"})
                self.assertEqual(report["collection"]["observed_at"], collection["observed_at"])

    def test_absent_empty_multiple_unclassified_null_are_not_classified_https_or_secure(self):
        for fields, state, scheme, same in ((b"", "absent", None, None), (b"Location: \t\r\n", "present_empty", None, None),
            (b"Location: /one\r\nLocation: /two\r\n", "multiple_fields", None, None),
            (b"Location: javascript:private\r\n", "single_unclassified", None, None),
            (b"Location: /relative?secret=value\r\n", "single_classified", "https", True),
            (b"Location: https://foreign.invalid/\r\n", "single_classified", "https", False)):
            with self.subTest(state=state, same=same):
                report = redirect_review_candidates(self.collection(fields=fields), binding=self.binding)
                self.assertEqual(report["candidates"], [])
                self.assertEqual(report["availability"], {"target_metadata": "observed" if scheme else "unavailable"})
                location = report["collection"]["evidence"]["response_location"]
                self.assertEqual((location["location_state"], location["target_scheme"], location["same_origin"]), (state, scheme, same))

    def test_full_original_scope_family_shape_dates_real_booleans_and_null_agreement_fail_closed(self):
        collection = self.collection()
        for changes in ({"method_version": "passive-header-source-v1"}, {"collection_permission": 1}, {"actor_id": True},
            {"observations": ["response_headers"]}, {"origin": "https://foreign.invalid"}, {"source_digest": "bad"},
            {"url": self.binding["url"] + "/other"}, {"verified_at": "2026-02-30T00:00:00+00:00"}, {"raw": "private"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                redirect_review_candidates(collection, binding={**self.binding, **changes})
        mutations = (
            lambda row: row.update(method="passive-resource-evidence-v1"), lambda row: row.update(status=True),
            lambda row: row.update(observed_at="2025-01-01T00:00:00.000000Z"),
            lambda row: row["evidence"].update(observed_at="2025-01-01T00:00:00.000000+00:00"),
            lambda row: row["evidence"].update(coverage="whole_chain"), lambda row: row["evidence"].update(raw_location="private"),
            lambda row: row["evidence"]["response_location"].update(response_status=200),
            lambda row: row["evidence"]["response_location"].update(redirect_status=1),
            lambda row: row["evidence"]["response_location"].update(redirect_status=False),
            lambda row: row["evidence"]["response_location"].update(same_origin=True),
            lambda row: row["evidence"]["response_location"].update(same_origin=0),
            lambda row: row["evidence"]["response_location"].update(location_state="single_unclassified"),
            lambda row: row["evidence"]["response_location"].update(target_scheme=None),
        )
        for mutate in mutations:
            broken = deepcopy(collection); mutate(broken)
            with self.subTest(mutate=mutate), self.assertRaises(ValidationError): redirect_review_candidates(broken, binding=self.binding)
        for value in (None, [], "private", {}):
            with self.assertRaises(ValidationError): redirect_review_candidates(value, binding=self.binding)
            with self.assertRaises(ValidationError): redirect_review_candidates(collection, binding=value)
        observed = datetime.fromisoformat(collection["observed_at"])
        for delta, valid in ((timedelta(0), True), (timedelta(microseconds=-1), True), (timedelta(microseconds=1), False)):
            binding = {**self.binding, "verified_at": (observed + delta).isoformat()}
            if valid: self.assertEqual(redirect_review_candidates(collection, binding=binding)["collection"], collection)
            else:
                with self.assertRaises(ValidationError): redirect_review_candidates(collection, binding=binding)

    def test_fresh_original_objects_privacy_and_no_current_authority_network_or_private_io(self):
        collection = self.collection(); original = deepcopy((collection, self.binding))
        with patch("socket.create_connection", side_effect=AssertionError("No network")), patch.object(
            lifecycle, "read_project_artifact", side_effect=AssertionError("No private I/O")):
            report = redirect_review_candidates(collection, binding=self.binding)
        self.assertFalse({"job_id", "source_current", "severity", "priority", "score"} & set(report))
        for private in ("private.invalid", "secret=value", "raw_location", "target_url", "raw_body", "derived_sha256"):
            self.assertNotIn(private, json.dumps(report))
        report["candidates"][0]["evidence"]["target_scheme"] = "https"
        report["collection"]["evidence"]["response_location"]["target_scheme"] = "changed"
        report["binding"]["observations"].append("raw")
        self.assertEqual((collection, self.binding), original)


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json"}))
class OriginalRedirectReviewCandidateTests(TransactionTestCase):
    setUp = fixtures.PassiveRedirectCollectionTests.setUp
    verified = fixtures.PassiveRedirectCollectionTests.verified
    queue = fixtures.PassiveRedirectCollectionTests.queue
    transport = fixtures.PassiveRedirectCollectionTests.transport
    WIRE = fixtures.PassiveRedirectCollectionTests.WIRE

    def test_genuine_original_verifier_first_response_private_readback_to_pure_no_io_projection(self):
        job = self.queue(); fetcher = self.transport(wire=self.WIRE)
        with patch("socket.create_connection", side_effect=AssertionError("No real network")):
            self.assertTrue(collector.execute_passive_redirect_collection(job.pk, fetcher=fetcher))
        job.refresh_from_db()
        source = collector.read_passive_redirect_observation(project=self.project, actor=self.owner, job_id=job.pk)
        original = deepcopy(source)
        with self.assertNumQueries(0), patch.object(lifecycle, "read_project_artifact", side_effect=AssertionError("No private I/O")), patch(
            "socket.create_connection", side_effect=AssertionError("No network")):
            report = redirect_review_candidates(source["collection"], binding=job.config_snapshot["binding"])
        self.assertEqual(source, original); self.assertEqual(report["binding"], job.config_snapshot["binding"])
        self.assertEqual(report["collection"]["observed_at"], job.output["observed_at"])
        self.assertEqual(report["candidates"][0]["evidence"], {"response_status": 302, "redirect_status": True,
            "location_state": "single_classified", "target_scheme": "http", "same_origin": False})
        for private in (self.challenge, self.verification.challenge_digest, self.owner.email, "private", "secret=value"):
            self.assertNotIn(private, json.dumps(report))
        self.assertEqual((Finding.objects.count(), Opportunity.objects.count(), Recommendation.objects.count()), (0, 0, 0))
        self.connection.request.assert_called_once()
