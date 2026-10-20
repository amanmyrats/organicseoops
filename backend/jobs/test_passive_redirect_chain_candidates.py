from copy import deepcopy
import json
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TransactionTestCase, override_settings

from config.test_foundations import TEST_STORAGES
from . import passive_header_collection as lifecycle
from . import passive_redirect_chain_collection as collector
from . import test_passive_redirect_chain_collection as collector_fixtures
from . import test_passive_redirect_chain_evidence as evidence_fixtures
from .models import Finding, Opportunity, Recommendation
from .passive_redirect_chain_candidates import INTERPRETATION, METHOD, redirect_chain_review_candidates


class RedirectChainCandidateTests(SimpleTestCase):
    def setUp(self):
        self.original = evidence_fixtures.RedirectChainEvidenceTests()
        self.addCleanup(self.original.doCleanups)
        self.binding = deepcopy(self.original.BINDING)

    def result(self, urls, *, fields=None, status=200, max_redirects=5):
        self.binding["url"] = urls[0]
        self.binding["target_urls"] = urls[1:]
        self.binding["origins"] = [{"origin": origin, "verification_id": index, "verified_at": "2024-01-01T00:00:00+00:00"}
            for index, origin in enumerate(dict.fromkeys(url.rsplit("/", 1)[0] for url in urls), 4)]
        wires = [f"HTTP/1.1 302 Found\r\nLocation: {url}\r\n\r\n".encode() for url in urls[1:]]
        wires.append(f"HTTP/1.1 {status} Response\r\n".encode() + (fields or b"") + b"\r\n")
        return self.original.result(binding=self.binding, wires=wires, max_redirects=max_redirects)

    def project(self, result):
        with patch.object(lifecycle, "read_project_artifact", side_effect=AssertionError("No private I/O")), patch(
            "socket.create_connection", side_effect=AssertionError("No network")), patch("socket.getaddrinfo", side_effect=AssertionError("No DNS")):
            return redirect_chain_review_candidates(result, binding=self.binding)

    def test_actual_native_adjacent_captures_only_not_classified_unvisited_reference_or_status_inference(self):
        urls = ["https://example.com/public", "http://example.com/public", "https://example.com/other", "http://example.com/other"]
        for status in (200, 301, 302, 404, 599):
            result = self.result(urls, status=status)
            report = self.project(result)
            self.assertEqual(report["candidates"], [{"detector": "observed_https_to_http_transition_candidate",
                "evidence": {"transitions": [{"from_hop": 0, "to_hop": 1}, {"from_hop": 2, "to_hop": 3}]}}])
            self.assertEqual(report["collection"], result)
            self.assertEqual(report["availability"], {"selected_urls": 4, "observed_hops": 4, "last_target_metadata": "unavailable"})
        result = self.result(urls, max_redirects=0)
        report = self.project(result)
        self.assertEqual(report["candidates"], [{"detector": "redirect_chain_budget_stop_candidate",
            "evidence": {"state": "redirect_limit", "observed_hops": 1, "last_hop": 0}}])
        self.assertEqual(report["availability"], {"selected_urls": 4, "observed_hops": 1, "last_target_metadata": "observed"})

    def test_original_stop_coverage_unknown_outside_unsupported_terminal_and_empty_are_not_clean_results(self):
        for fields, status, state, available, expected in (
            (b"Location: /public\r\n", 302, "redirect_loop", "observed", "redirect_chain_loop_stop_candidate"),
            (b"", 302, "location_unavailable", "unavailable", None),
            (b"Location: \t\r\n", 302, "location_unavailable", "unavailable", None),
            (b"Location: /one\r\nLocation: /two\r\n", 302, "location_unavailable", "unavailable", None),
            (b"Location: javascript:private\r\n", 302, "location_unavailable", "unavailable", None),
            (b"Location: https://example.com/public?\r\n", 302, "unsupported_target", "observed", None),
            (b"Location: http://foreign.invalid/private\r\n", 302, "outside_exact_target_allowlist", "observed", None),
            (b"Location: http://foreign.invalid/private\r\n", 200, "terminal_response", "observed", None),
        ):
            with self.subTest(state=state, fields=fields):
                result = self.result(["https://example.com/public"], fields=fields, status=status)
                report = self.project(result)
                self.assertEqual(report["collection"]["evidence"]["state"], state)
                self.assertEqual(report["availability"]["last_target_metadata"], available)
                self.assertEqual([row["detector"] for row in report["candidates"]], [expected] if expected else [])
                self.assertNotIn("foreign.invalid", json.dumps(report))

    def test_strict_original_binding_shape_family_bool_date_transition_and_stop_are_required_before_projection(self):
        result = self.result(["https://example.com/public", "http://example.com/public"])
        mutations = (lambda r: r.update(method="passive-redirect-evidence-v1"), lambda r: r.update(status=True),
            lambda r: r.update(last_observed_at=r["observed_at"]), lambda r: r["evidence"].update(state="permitted_target"),
            lambda r: r["evidence"]["hops"][0]["response_location"].update(target_scheme="https"),
            lambda r: r["evidence"]["hops"][0]["response_location"].update(redirect_status=1),
            lambda r: r["evidence"]["hops"][1].update(url="http://example.com/unselected"),
            lambda r: r["evidence"]["hops"][1].update(observed_at="2026-02-30T00:00:00.000001+00:00"),
            lambda r: r["evidence"]["hops"][1]["response_location"].update(raw_location="private"))
        for change in mutations:
            broken = deepcopy(result); change(broken)
            with self.assertRaises(ValidationError): self.project(broken)
        for changes in ({"collection_permission": 1}, {"observations": ["response_location"]}, {"source_digest": "bad"},
            {"origins": self.binding["origins"][:1]}, {"actor_id": True}, {"raw": "private"}):
            with self.assertRaises(ValidationError): redirect_chain_review_candidates(result, binding={**self.binding, **changes})
        for value in (None, [], "private", {}):
            with self.assertRaises(ValidationError): redirect_chain_review_candidates(value, binding=self.binding)

    def test_maximum_six_actual_paths_index_facts_privacy_and_fresh_original_objects(self):
        urls = []
        for index in range(6):
            prefix = ("https" if index % 2 == 0 else "http") + "://example.com/"
            urls.append(prefix + str(index) * (1024 - len(prefix)))
        result = self.result(urls, fields=f"Location: {urls[0]}\r\n".encode(), status=302)
        original = deepcopy((result, self.binding)); report = self.project(result)
        self.assertGreater(len(json.dumps(report["collection"]).encode()), 8192)
        self.assertEqual(report["method_version"], METHOD); self.assertEqual(report["interpretation"], INTERPRETATION)
        self.assertEqual(report["candidates"], [
            {"detector": "observed_https_to_http_transition_candidate", "evidence": {"transitions": [
                {"from_hop": 0, "to_hop": 1}, {"from_hop": 2, "to_hop": 3}, {"from_hop": 4, "to_hop": 5}]}},
            {"detector": "redirect_chain_loop_stop_candidate", "evidence": {"state": "redirect_loop", "observed_hops": 6, "last_hop": 5}}])
        self.assertFalse({"job_id", "source_current", "severity", "priority", "score"} & set(report))
        for private in ("raw_location", "raw_body", "cookies", "headers", "private", "secret"):
            self.assertNotIn(private, json.dumps(report))
        report["binding"]["target_urls"].clear(); report["collection"]["evidence"]["hops"].clear()
        report["candidates"][0]["evidence"]["transitions"].clear()
        self.assertEqual((result, self.binding), original)


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json", "application/zip"}))
class OriginalRedirectChainCandidateTests(TransactionTestCase):
    setUp = collector_fixtures.PassiveRedirectChainCollectionTests.setUp
    verified = collector_fixtures.PassiveRedirectChainCollectionTests.verified
    queue = collector_fixtures.PassiveRedirectChainCollectionTests.queue
    transport = collector_fixtures.PassiveRedirectChainCollectionTests.transport
    read = collector_fixtures.PassiveRedirectChainCollectionTests.read

    def test_genuine_verifiers_native_chain_private_readback_to_pure_projection_without_new_authority(self):
        self.data = {**self.data, "url": self.https + "/public", "target_urls": [self.http + "/public"]}
        job = self.queue(); fetcher, connections, responses, *_ = self.transport()
        with patch("socket.create_connection", side_effect=AssertionError("No actual network")):
            self.assertTrue(collector.execute_passive_redirect_chain_collection(job.pk, fetcher=fetcher))
        job.refresh_from_db(); result = self.read(job)["collection"]; original = deepcopy((result, job.config_snapshot))
        with self.assertNumQueries(0), patch.object(lifecycle, "read_project_artifact", side_effect=AssertionError("No private I/O")), patch(
            "socket.create_connection", side_effect=AssertionError("No network")):
            report = redirect_chain_review_candidates(result, binding=job.config_snapshot["binding"])
        self.assertEqual(report["collection"], result); self.assertEqual(report["binding"], job.config_snapshot["binding"])
        self.assertEqual(report["candidates"], [{"detector": "observed_https_to_http_transition_candidate", "evidence": {"transitions": [{"from_hop": 0, "to_hop": 1}]}}])
        self.assertEqual((result, job.config_snapshot), original)
        for private in (self.challenge, self.http_verification.challenge_digest, self.owner.email, "private", "secret"):
            self.assertNotIn(private, json.dumps(report))
        self.assertEqual((Finding.objects.count(), Opportunity.objects.count(), Recommendation.objects.count()), (0, 0, 0))
        for conn, response in zip(connections, responses): conn.request.assert_called_once(); response.read.assert_not_called()
