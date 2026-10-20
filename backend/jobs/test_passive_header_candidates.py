from copy import deepcopy
from datetime import timedelta
import json
from unittest import TestCase
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from . import passive_header_collection as collector
from . import test_passive_header_collection as original_fixtures
from .passive_header_candidates import SECURITY_HEADERS, response_header_candidates
from .passive_headers import observe_response_headers


class ResponseHeaderCandidateTests(TestCase):
    def setUp(self):
        verified = (timezone.now() - timedelta(seconds=1)).isoformat()
        self.binding = {"method_version": "passive-header-source-v1", "organization_id": 1, "project_id": 2,
            "actor_id": 3, "origin": "https://security.example.com", "url": "https://security.example.com/",
            "observations": ["response_headers"], "collection_permission": True, "verification_id": 4,
            "verified_at": verified, "source_digest": "a" * 64,
            "interpretation": "current_source_binding_not_network_job_commercial_reservation_or_observation_authority"}

    def evaluate(self, fields):
        collection = {"method": collector.METHOD, "url": self.binding["url"], "status": 200,
            "observed_at": timezone.now().isoformat(), "evidence": observe_response_headers(fields),
            "interpretation": collector.INTERPRETATION}
        return response_header_candidates(collection, binding=self.binding)

    def test_absent_empty_and_report_only_are_factual_separate_enforcement_categories(self):
        report = self.evaluate([("X-Frame-Options", " \t"),
            ("Content-Security-Policy-Report-Only", "default-src 'nonce-private'")])
        by_header = {item["evidence"]["header"]: item for item in report["candidates"]}
        self.assertEqual(set(by_header), set(SECURITY_HEADERS))
        self.assertEqual(by_header["x-frame-options"]["evidence"]["state"], "present_empty")
        self.assertEqual(by_header["content-security-policy"]["evidence"], {
            "header": "content-security-policy", "state": "absent", "report_only_state": "present_nonempty"})
        self.assertNotIn("private", json.dumps(report))

    def test_multiple_fields_never_prove_invalidity_or_nonemptiness_and_present_is_not_effectiveness(self):
        fields = [(name, "uninterpreted private policy") for name in SECURITY_HEADERS]
        report = self.evaluate(fields + [("Content-Security-Policy", ""), ("Server", ""), ("Server", ""),
            ("X-Powered-By", " \t")])
        self.assertEqual(report["candidates"], [])
        self.assertEqual(report["collection"]["evidence"]["headers"]["content-security-policy"], "multiple_fields")
        self.assertEqual(report["collection"]["evidence"]["headers"]["server"], "multiple_fields")
        self.assertIn("not_severity_policy_effectiveness", report["interpretation"])
        report = self.evaluate(fields + [("Server", "private-software/1"), ("X-Powered-By", "private-framework")])
        self.assertEqual({item["detector"] for item in report["candidates"]}, {
            "response_server_disclosure_candidate", "response_x_powered_by_disclosure_candidate"})
        self.assertNotIn("private", json.dumps(report))

    def test_only_explicit_parsed_cookie_subset_contributes_missing_flags(self):
        report = self.evaluate([("Set-Cookie", "safe=private; Secure; HttpOnly; SameSite=Lax"),
            ("Set-Cookie", "missing=private; SameSite=unknown"), ("Set-Cookie", "unknown=private; Secure=1")])
        flags = [item for item in report["candidates"] if "flag" in item["evidence"]]
        self.assertEqual(len(flags), 3)
        for item in flags:
            self.assertEqual({key: value for key, value in item["evidence"].items() if key != "flag"},
                {"count": 1, "parsed_fields": 2, "observed_fields": 3, "unclassified_fields": 1})
        unknown = self.evaluate([("Set-Cookie", "unknown=private; Secure=1")])
        self.assertFalse(any("flag" in item["evidence"] for item in unknown["candidates"]))
        self.assertEqual(unknown["collection"]["evidence"]["cookies"]["unclassified_fields"], 1)

    def test_original_status_date_full_shapes_and_counts_are_validated_with_fresh_object_ownership(self):
        report = self.evaluate([])
        collection = report["collection"]
        original = deepcopy((collection, self.binding))
        with patch("socket.create_connection", side_effect=AssertionError("No network")):
            first = response_header_candidates(collection, binding=self.binding)
            second = response_header_candidates(collection, binding=self.binding)
        self.assertEqual(first, second)
        self.assertEqual((collection, self.binding), original)
        first["collection"]["evidence"]["headers"]["server"] = "present_nonempty"
        first["binding"]["observations"].append("raw")
        first["candidates"][0]["evidence"]["state"] = "changed"
        self.assertEqual(second, response_header_candidates(collection, binding=self.binding))
        for changes in ({"status": True}, {"status": 199}, {"observed_at": "unavailable"},
            {"observed_at": (timezone.now() + timedelta(days=1)).isoformat()},
            {"observed_at": (timezone.now() - timedelta(days=1)).isoformat()},
            {"method": "passive-redirect-evidence-v1"}, {"raw_headers": "private"},
            {"evidence": observe_response_headers(None)}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                response_header_candidates({**collection, **changes}, binding=self.binding)
        for changes in ({"actor_id": True}, {"source_digest": "unknown"}, {"origin": "https://other.example"},
            {"method_version": "passive-tls-source-v1"}, {"observations": ["response_location"]},
            {"collection_permission": False}, {"raw": "private"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                response_header_candidates(collection, binding={**self.binding, **changes})
        for changes in ({"without_secure": True}, {"parsed_fields": 101}, {"without_secure": 1},
            {"observed_fields": 1}, {"unclassified_fields": -1}):
            invalid = deepcopy(collection)
            invalid["evidence"]["cookies"].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                response_header_candidates(invalid, binding=self.binding)
        for status in (200, 302, 404, 599):
            dated = {**collection, "status": status, "observed_at": self.binding["verified_at"]}
            self.assertEqual(response_header_candidates(dated, binding=self.binding)["collection"], dated)


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json"}))
class OriginalHeaderCandidateTests(TransactionTestCase):
    setUp = original_fixtures.PassiveHeaderCollectionTests.setUp
    verified = original_fixtures.PassiveHeaderCollectionTests.verified
    queue = original_fixtures.PassiveHeaderCollectionTests.queue
    transport = original_fixtures.PassiveHeaderCollectionTests.transport

    def test_genuine_verification_transport_private_readback_to_pure_minimized_candidates(self):
        job = self.queue()
        with patch("socket.create_connection", side_effect=AssertionError("No actual egress")):
            self.assertTrue(collector.execute_passive_header_collection(job.pk, fetcher=self.transport()))
        job.refresh_from_db()
        source = collector.read_passive_header_observation(project=self.project, actor=self.owner, job_id=job.pk)
        original = deepcopy(source)
        with self.assertNumQueries(0), patch.object(collector, "read_project_artifact", side_effect=AssertionError("No I/O")):
            report = response_header_candidates(source["collection"], binding=job.config_snapshot["binding"])
        self.assertEqual(source, original)
        self.assertEqual(report["collection"], source["collection"])
        self.assertEqual(report["binding"], job.config_snapshot["binding"])
        self.assertEqual({item["evidence"]["flag"] for item in report["candidates"] if "flag" in item["evidence"]},
            {"without_secure", "without_httponly", "without_recognized_samesite"})
        self.assertNotIn("response_content_security_policy_absent_candidate", {item["detector"] for item in report["candidates"]})
        for private in ("nonce-private", "secret", "private body", self.challenge):
            self.assertNotIn(private, json.dumps(report))
        from .models import Finding, Opportunity, Recommendation
        self.assertEqual((Finding.objects.count(), Opportunity.objects.count(), Recommendation.objects.count()), (0, 0, 0))
