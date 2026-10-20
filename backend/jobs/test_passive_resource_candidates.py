from copy import deepcopy
from datetime import timedelta
import json
from unittest import TestCase
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from . import passive_resource_collection as collector
from . import test_passive_resource_collection as fixtures
from .passive_resource_candidates import static_resource_candidates
from .passive_resource_evidence import INTERPRETATION, METHOD
from .passive_resources import observe_static_resource_references


class StaticResourceCandidateTests(TestCase):
    def setUp(self):
        self.binding = {"method_version": "passive-resource-source-v1", "organization_id": 1, "project_id": 2, "actor_id": 3,
            "origin": "https://security.example.invalid", "url": "https://security.example.invalid/public",
            "observations": ["static_resource_references"], "collection_permission": True, "verification_id": 4,
            "verified_at": (timezone.now() - timedelta(seconds=1)).isoformat(), "source_digest": "a" * 64,
            "interpretation": "current_source_binding_not_network_job_commercial_reservation_or_observation_authority"}

    def observation(self, body):
        observed = timezone.now().isoformat(timespec="microseconds")
        return {"method": METHOD, "url": self.binding["url"], "status": 200, "observed_at": observed,
            "interpretation": INTERPRETATION, "evidence": {"method_version": "passive-resource-response-v1", "observed_at": observed,
                "coverage": "one_complete_length_framed_utf8_html_response_only",
                "interpretation": "literal_candidates_not_browser_requests_or_whole_page_mixed_content_security",
                "resource_references": observe_static_resource_references(body, body_complete=True)}}

    def test_positive_http_counts_are_one_dated_literal_candidate_with_exact_subset_coverage(self):
        collection = self.observation(b'<img src="http://private.invalid/?secret=value"><script src="https://private.invalid/x"></script>'
            b'<iframe src="relative"></iframe><link rel="stylesheet" href="http://private.invalid/second">'
            b'<a href="http://not-resource.invalid/">navigation</a><template><img src="http://inert.invalid/"></template>')
        report = static_resource_candidates(collection, binding=self.binding)
        self.assertEqual(report["collection"], collection)
        self.assertEqual(report["binding"], self.binding)
        self.assertEqual(report["state"], "original_lexical_review_candidates")
        self.assertEqual(report["reason"], "")
        self.assertEqual(report["candidates"], [{"detector": "literal_http_resource_reference_candidate", "evidence": {
            "counts": {"inspected_attributes": 4, "http_absolute": 2, "https_absolute": 1, "unclassified": 1},
            "selected_attributes": collection["evidence"]["resource_references"]["selected_attributes"],
            "excluded": collection["evidence"]["resource_references"]["excluded"]}}])
        for private in ("secret", "private.invalid", "inert.invalid", "not-resource.invalid", "raw_body", "severity"):
            self.assertNotIn(private, json.dumps(report).replace("_severity_", "_"))

    def test_observed_empty_unclassified_and_lexically_unavailable_are_distinct_not_secure(self):
        for body, count in ((b"", 0), (b'<img src="https://private.invalid/">', 0), (b'<img src="relative"><img src="//private.invalid/x">', 2)):
            report = static_resource_candidates(self.observation(body), binding=self.binding)
            self.assertEqual(report["candidates"], [])
            self.assertEqual(report["state"], "original_lexical_review_candidates")
            self.assertEqual(report["collection"]["evidence"]["resource_references"]["counts"]["unclassified"], count)
        for body, reason in ((b'<img src="x" src="y">', "ambiguous_markup"), (b"\x00", "invalid_body"),
            (b'<img src="http://private.invalid/">' * 1001, "reference_limit")):
            report = static_resource_candidates(self.observation(body), binding=self.binding)
            self.assertEqual((report["state"], report["reason"], report["candidates"]), ("original_lexical_evaluation_unavailable", reason, []))
            self.assertTrue(all(value is None for value in report["collection"]["evidence"]["resource_references"]["counts"].values()))

    def test_exact_full_shapes_original_dates_family_and_counts_are_validated(self):
        collection = self.observation(b'<img src="http://private.invalid/">')
        for change in ({"method_version": "passive-header-source-v1"}, {"collection_permission": 1}, {"actor_id": True},
            {"source_digest": "bad"}, {"origin": "https://other.example.invalid"}, {"observations": ["response_headers"]}, {"raw": "secret"}):
            with self.subTest(change=change), self.assertRaises(ValidationError): static_resource_candidates(collection, binding={**self.binding, **change})
        for change in ({"status": True}, {"status": 302}, {"method": "passive-header-collection-v1"}, {"raw_body": "secret"},
            {"url": "https://other.example.invalid/"}, {"observed_at": "2026-02-30T00:00:00.000000+00:00"},
            {"observed_at": (timezone.now() + timedelta(days=1)).isoformat()}, {"observed_at": self.binding["verified_at"]}):
            bad = {**collection, **change}
            with self.subTest(change=change), self.assertRaises(ValidationError): static_resource_candidates(bad, binding=self.binding)
        for change in ({"http_absolute": True}, {"http_absolute": "1"}, {"http_absolute": -1}, {"http_absolute": 1001},
            {"inspected_attributes": 0}, {"http_absolute": None}, {"raw": 1}):
            bad = deepcopy(collection); bad["evidence"]["resource_references"]["counts"].update(change)
            with self.subTest(change=change), self.assertRaises(ValidationError): static_resource_candidates(bad, binding=self.binding)
        bad = deepcopy(collection); bad["evidence"]["resource_references"]["state"] = "unavailable"
        with self.assertRaises(ValidationError): static_resource_candidates(bad, binding=self.binding)

    def test_fresh_object_ownership_and_full_count_ceiling_do_not_modify_originals(self):
        collection = self.observation(b'<img src="http://private.invalid/">' * 1000)
        original = deepcopy((collection, self.binding))
        report = static_resource_candidates(collection, binding=self.binding)
        self.assertEqual(report["candidates"][0]["evidence"]["counts"]["http_absolute"], 1000)
        report["candidates"][0]["evidence"]["counts"]["http_absolute"] = 0
        report["candidates"][0]["evidence"]["selected_attributes"].append("raw")
        report["collection"]["evidence"]["resource_references"]["counts"]["http_absolute"] = 0
        report["binding"]["observations"].append("raw")
        self.assertEqual((collection, self.binding), original)
        self.assertEqual(static_resource_candidates(collection, binding=self.binding)["candidates"][0]["evidence"]["counts"]["http_absolute"], 1000)


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json"}))
class OriginalStaticResourceCandidateTests(TransactionTestCase):
    setUp = fixtures.PassiveResourceCollectionTests.setUp
    verified = fixtures.PassiveResourceCollectionTests.verified
    queue = fixtures.PassiveResourceCollectionTests.queue
    transport = fixtures.PassiveResourceCollectionTests.transport

    def test_genuine_original_verifier_transport_private_readback_to_pure_factual_projection(self):
        from . import passive_header_collection as lifecycle
        from .models import Finding, Opportunity, Recommendation
        job = self.queue()
        with patch("socket.create_connection", side_effect=AssertionError("No real egress")):
            self.assertTrue(collector.execute_passive_resource_collection(job.pk, fetcher=self.transport()))
        job.refresh_from_db()
        source = collector.read_passive_resource_observation(project=self.project, actor=self.owner, job_id=job.pk)
        original = deepcopy(source)
        with self.assertNumQueries(0), patch.object(lifecycle, "read_project_artifact", side_effect=AssertionError("No I/O")), patch(
            "socket.create_connection", side_effect=AssertionError("No network")):
            report = static_resource_candidates(source["collection"], binding=job.config_snapshot["binding"])
        self.assertEqual(source, original)
        self.assertEqual(report["collection"]["observed_at"], job.output["observed_at"])
        self.assertEqual(report["candidates"][0]["evidence"]["counts"], {"inspected_attributes": 2, "http_absolute": 1, "https_absolute": 1, "unclassified": 0})
        for private in ("secret", "private.invalid", self.challenge): self.assertNotIn(private, json.dumps(report))
        self.assertEqual((Finding.objects.count(), Opportunity.objects.count(), Recommendation.objects.count()), (0, 0, 0))
        self.connection.request.assert_called_once()
