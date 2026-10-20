import copy
import json
from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext

from . import passive_redirect_chain_evidence as evidence
from . import passive_redirect_chain_source as source
from . import test_passive_redirect_chain_source as source_fixtures
from . import test_passive_redirect_chain_transport as transport_fixtures
from .crawling import CrawlScope


class RedirectChainEvidenceTests(SimpleTestCase):
    BINDING = {"method_version": source.METHOD, "organization_id": 1, "project_id": 2, "actor_id": 3,
        "url": "http://example.com/public", "target_urls": ["https://example.com/public", "https://www.example.com/public"],
        "observations": ["redirect_chain"], "collection_permission": True,
        "origins": [{"origin": origin, "verification_id": index, "verified_at": "2024-01-01T00:00:00+00:00"}
            for index, origin in enumerate(("http://example.com", "https://example.com", "https://www.example.com"), 4)],
        "source_digest": "a" * 64,
        "interpretation": "explicit_exact_url_allowlist_not_observed_chain_network_job_or_commercial_reservation"}
    WIRES = (b"HTTP/1.1 301 Moved\r\nLocation: https://example.com:443/public\r\nSet-Cookie: personal=secret\r\n\r\nprivate body",
        b"HTTP/1.1 302 Found\r\nLocation: https://www.example.com/public\r\n\r\n", b"HTTP/1.1 200 OK\r\n\r\n")

    def response(self, wires=None, binding=None, max_redirects=5):
        binding = binding or self.BINDING
        case = transport_fixtures.PassiveRedirectChainTransportTests(); self.addCleanup(case.doCleanups)
        fetcher, *_ = case.transport(*(self.WIRES if wires is None else wires), max_redirects=max_redirects)
        data = {key: binding[key] for key in ("url", "target_urls", "observations", "collection_permission")}
        return fetcher.fetch(data["url"], redirect_chain_selection=data, before_request=Mock(), before_send=Mock())

    def result(self, **changes):
        return evidence.minimized_redirect_chain_evidence(self.response(**changes), binding=changes.get("binding", self.BINDING))

    def test_original_native_roundtrip_each_capture_privacy_no_io_and_fresh_objects(self):
        response = self.response(); original = copy.deepcopy(response.redirect_observation)
        with patch("socket.create_connection", side_effect=AssertionError("No network")), patch("socket.getaddrinfo", side_effect=AssertionError("No DNS")), patch("hashlib.sha256", side_effect=AssertionError("No raw digest")):
            result = evidence.minimized_redirect_chain_evidence(response, binding=self.BINDING)
            content = evidence.encode_redirect_chain_evidence(result, binding=self.BINDING)
            parsed = evidence.parse_redirect_chain_evidence(content, binding=self.BINDING)
        self.assertEqual(parsed, result); self.assertEqual(result["evidence"], original)
        self.assertEqual(result["observed_at"], original["hops"][0]["observed_at"])
        self.assertEqual(result["last_observed_at"], original["hops"][-1]["observed_at"])
        self.assertEqual((result["final_url"], result["status"]), (response.url, response.status))
        for private in (b"private", b"secret", b"personal", b"source_digest", b"location_url", b"headers", b"raw_body", b":443"):
            self.assertNotIn(private, content)
        response.redirect_observation["hops"][0]["response_location"]["same_hostname_default_https"] = False
        parsed["evidence"]["hops"].clear()
        self.assertTrue(result["evidence"]["hops"][0]["response_location"]["same_hostname_default_https"])

    def test_genuine_terminal_ambiguous_unsupported_outside_loop_and_smaller_budget_coverage_roundtrip(self):
        for fields, state in ((b"", "location_unavailable"), (b"Location: /one\r\nLocation: /two\r\n", "location_unavailable"),
            (b"Location: /%ZZ\r\n", "location_unavailable"), (b"Location: https://example.com/public?\r\n", "unsupported_target"),
            (b"Location: https://other.invalid/private\r\n", "outside_exact_target_allowlist"),
            (b"Location: /public\r\n", "redirect_loop")):
            result = self.result(wires=[b"HTTP/1.1 301 Moved\r\n" + fields + b"\r\n"])
            self.assertEqual(result["evidence"]["state"], state)
            self.assertEqual(evidence.parse_redirect_chain_evidence(evidence.encode_redirect_chain_evidence(result, binding=self.BINDING), binding=self.BINDING), result)
        for budget in (0, 1):
            result = self.result(max_redirects=budget)
            self.assertEqual(result["evidence"]["state"], "redirect_limit")
        result = self.result(wires=[b"HTTP/1.1 404 Not Found\r\nLocation: https://example.com/public\r\n\r\n"])
        self.assertEqual(result["evidence"]["state"], "terminal_response"); self.assertEqual(result["status"], 404)

    def test_nested_shapes_types_status_family_transition_stop_and_unobserved_paths_fail_closed(self):
        result = self.result()
        paths = [[], ["evidence"]]
        paths += [["evidence", "hops", index] for index in range(3)]
        paths += [["evidence", "hops", index, "response_location"] for index in range(3)]
        for path in paths:
            node = result
            for key in path: node = node[key]
            for missing in node:
                broken = copy.deepcopy(result); target = broken
                for key in path: target = target[key]
                del target[missing]
                with self.subTest(path=path, missing=missing), self.assertRaises(ValidationError):
                    evidence.validate_redirect_chain_evidence(broken, binding=self.BINDING)
            broken = copy.deepcopy(result); target = broken
            for key in path: target = target[key]
            target["private"] = "secret"
            with self.assertRaises(ValidationError): evidence.validate_redirect_chain_evidence(broken, binding=self.BINDING)
        mutations = ((["status"], True), (["status"], 302), (["final_url"], self.BINDING["url"]),
            (["evidence", "state"], []), (["evidence", "state"], "permitted_target"), (["evidence", "state"], "redirect_loop"),
            (["evidence", "hops"], []), (["evidence", "hops", 1, "url"], "https://example.com/unselected"),
            (["evidence", "hops", 1, "url"], self.BINDING["url"]), (["evidence", "hops", 0, "target_state"], "terminal_response"),
            (["evidence", "hops", 0, "status"], True), (["evidence", "hops", 0, "status"], 302),
            (["evidence", "hops", 0, "response_location", "target_scheme"], "http"),
            (["evidence", "hops", 0, "response_location", "same_hostname_default_https"], False),
            (["evidence", "hops", 1, "response_location", "same_origin"], True),
            (["evidence", "hops", 0, "response_location", "redirect_status"], 1),
            (["evidence", "hops", 0, "response_location", "method_version"], "passive-response-location-v1"),
            (["evidence", "hops", 2, "target_state"], "permitted_target"))
        for path, value in mutations:
            broken = copy.deepcopy(result); node = broken
            for key in path[:-1]: node = node[key]
            node[path[-1]] = value
            with self.subTest(path=path, value=value), self.assertRaises(ValidationError):
                evidence.validate_redirect_chain_evidence(broken, binding=self.BINDING)
        loop = self.result(wires=[b"HTTP/1.1 301 Moved\r\nLocation: /public\r\n\r\n"])
        loop["evidence"]["state"] = "redirect_limit"  # No unvisited allowed HTTP syntax matches this purported budget stop.
        with self.assertRaises(ValidationError): evidence.validate_redirect_chain_evidence(loop, binding=self.BINDING)
        budget = self.result(max_redirects=0); budget["evidence"]["state"] = "redirect_loop"
        with self.assertRaises(ValidationError): evidence.validate_redirect_chain_evidence(budget, binding=self.BINDING)

    def test_exact_independent_binding_origin_rows_and_raw_transport_family_shapes_are_required(self):
        response = self.response()
        for changes in ({"headers": {"server": "private"}}, {"body": b"private"}, {"body": ""}, {"redirects": []},
            {"header_observation": {}}, {"resource_observation": {}}, {"observed_at": "private"}, {"status": True},
            {"url": self.BINDING["url"]}, {"redirect_observation": None}):
            with self.assertRaises(ValidationError): evidence.minimized_redirect_chain_evidence(replace(response, **changes), binding=self.BINDING)
        for changes in ({"collection_permission": 1}, {"observations": ["http_response_location"]}, {"method_version": "passive-http-redirect-source-v1"},
            {"source_digest": "private"}, {"actor_id": True}, {"origins": []}, {"origins": tuple(self.BINDING["origins"])}, {"raw": "private"}):
            with self.assertRaises(ValidationError): evidence.minimized_redirect_chain_evidence(response, binding={**self.BINDING, **changes})
        for mutate in (lambda rows: rows.reverse(), lambda rows: rows[1].update(verification_id=rows[0]["verification_id"]),
            lambda rows: rows[1].update(origin="https://foreign.invalid"), lambda rows: rows[1].update(verification_id=True),
            lambda rows: rows[1].update(private="secret")):
            binding = copy.deepcopy(self.BINDING); mutate(binding["origins"])
            with self.assertRaises(ValidationError): evidence.minimized_redirect_chain_evidence(response, binding=binding)

    def test_original_verification_all_origins_non_decreasing_microseconds_and_strict_byte_boundary(self):
        result = self.result(); first = datetime.fromisoformat(result["observed_at"])
        for delta, valid in ((timedelta(0), True), (timedelta(microseconds=-1), True), (timedelta(microseconds=1), False)):
            binding = copy.deepcopy(self.BINDING); binding["origins"][-1]["verified_at"] = (first + delta).isoformat()
            if valid: evidence.validate_redirect_chain_evidence(result, binding=binding)
            else:
                with self.assertRaises(ValidationError): evidence.validate_redirect_chain_evidence(result, binding=binding)
        broken = copy.deepcopy(result); broken["evidence"]["hops"][1]["observed_at"] = (first - timedelta(microseconds=1)).isoformat(timespec="microseconds")
        with self.assertRaises(ValidationError): evidence.validate_redirect_chain_evidence(broken, binding=self.BINDING)
        for date in (None, "2025-01-01T00:00:00Z", "2025-01-01T00:00:00+00:00", "2025-02-30T00:00:00.000000+00:00", "9999-01-01T00:00:00.000000+00:00"):
            broken = copy.deepcopy(result); broken["evidence"]["hops"][0]["observed_at"] = broken["observed_at"] = date
            with self.assertRaises(ValidationError): evidence.validate_redirect_chain_evidence(broken, binding=self.BINDING)
        content = evidence.encode_redirect_chain_evidence(result, binding=self.BINDING)
        self.assertEqual(evidence.parse_redirect_chain_evidence(content + b" " * (evidence.MAX_RESULT_BYTES - len(content)), binding=self.BINDING), result)
        for raw in (None, {}, "private", b"", b"\xff", b"null", b"[]", b"NaN", b'{"private":Infinity}',
            b'{"method":"private",' + content[1:], b"[" * 1000, content + b" " * (evidence.MAX_RESULT_BYTES + 1 - len(content))):
            with self.assertRaises(ValidationError) as raised: evidence.parse_redirect_chain_evidence(raw, binding=self.BINDING)
            self.assertNotIn("private", str(raised.exception))

    def test_six_maximum_length_actual_selected_hops_fit_private_limit_without_truncation(self):
        binding = copy.deepcopy(self.BINDING)
        prefix = "http://example.com/"; binding["url"] = prefix + "x" * (1024 - len(prefix))
        binding["target_urls"] = []
        for index in range(5):
            prefix = f"https://example.com/page-{index}-"
            binding["target_urls"].append(prefix + "x" * (1024 - len(prefix)))
        binding["origins"] = binding["origins"][:2]
        wires = [f"HTTP/1.1 301 Moved\r\nLocation: {url}\r\n\r\n".encode() for url in binding["target_urls"]]
        wires.append(b"HTTP/1.1 200 OK\r\n\r\n")
        result = self.result(wires=wires, binding=binding)
        content = evidence.encode_redirect_chain_evidence(result, binding=binding)
        self.assertEqual(len(result["evidence"]["hops"]), 6); self.assertGreater(len(content), 8192); self.assertLess(len(content), evidence.MAX_RESULT_BYTES)
        self.assertEqual(evidence.parse_redirect_chain_evidence(content, binding=binding), result)


class GenuineRedirectChainEvidenceTests(TestCase):
    setUp = source_fixtures.PassiveRedirectChainSourceTests.setUp
    verified = source_fixtures.PassiveRedirectChainSourceTests.verified

    def test_independent_original_verifiers_native_chain_read_only_roundtrip_and_all_source_dates(self):
        http, https = self.verified(self.http), self.verified(self.https)
        data = {"url": self.http + "/public", "target_urls": [self.https + "/public"],
            "observations": ["redirect_chain"], "collection_permission": True}
        binding = source.passive_redirect_chain_source(project=self.project, actor=self.owner, data=data)
        case = transport_fixtures.PassiveRedirectChainTransportTests(); self.addCleanup(case.doCleanups)
        fetcher, connections, responses, _, _ = case.transport(
            f"HTTP/1.1 301 Moved\r\nLocation: {data['target_urls'][0]}\r\n\r\n".encode(), b"HTTP/1.1 200 OK\r\n\r\n")
        fetcher.scope = CrawlScope(frozenset({"security.example.com"}))
        def current(url):
            self.assertIn(url, [data["url"], *data["target_urls"]])
            self.assertEqual(source.passive_redirect_chain_source(project=self.project, actor=self.owner, data=data), binding)
        with patch("socket.create_connection", side_effect=AssertionError("No actual egress")), CaptureQueriesContext(connection) as queries:
            response = fetcher.fetch(data["url"], redirect_chain_selection=data, before_request=current, before_send=current)
            result = evidence.minimized_redirect_chain_evidence(response, binding=binding)
            content = evidence.encode_redirect_chain_evidence(result, binding=binding)
            self.assertEqual(evidence.parse_redirect_chain_evidence(content, binding=binding), result)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        for private in (self.challenge, http.challenge_digest, https.challenge_digest, self.owner.email, self.project.name): self.assertNotIn(private.encode(), content)
        for hop, row in zip(result["evidence"]["hops"], (http, https)):
            self.assertGreaterEqual(datetime.fromisoformat(hop["observed_at"]), row.verified_at)
        for conn, original_response in zip(connections, responses): conn.request.assert_called_once(); original_response.read.assert_not_called()
