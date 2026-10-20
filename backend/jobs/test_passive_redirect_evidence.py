import copy
import json
from dataclasses import replace
from datetime import datetime, timedelta
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase as DatabaseTestCase
from django.test.utils import CaptureQueriesContext

from .crawling import CrawlScope, FetchResponse
from .passive_redirect_evidence import MAX_RESULT_BYTES, encode_redirect_evidence, minimized_redirect_evidence, parse_redirect_evidence, validate_redirect_evidence
from .passive_redirect_source import passive_redirect_source
from . import test_passive_header_source as source_fixtures
from . import test_passive_redirect_transport as transport_fixtures


class PassiveRedirectEvidenceTests(TestCase):
    BINDING = {"method_version": "passive-redirect-source-v1", "organization_id": 1, "project_id": 2, "actor_id": 3,
        "origin": "https://example.com", "url": "https://example.com/public", "observations": ["response_location"],
        "collection_permission": True, "verification_id": 4, "verified_at": "2024-01-01T00:00:00+00:00",
        "source_digest": "a" * 64, "interpretation": "current_source_binding_not_network_job_commercial_reservation_or_observation_authority"}
    WIRE = b"HTTP/1.1 302 Found\r\nLocation: http://private.invalid/?secret=value\r\nSet-Cookie: private=secret\r\n\r\nprivate body"
    transport = transport_fixtures.PassiveRedirectTransportTests.transport
    observe = transport_fixtures.PassiveRedirectTransportTests.observe
    URL = transport_fixtures.PassiveRedirectTransportTests.URL

    def response(self, wire=None):
        fetcher, *_ = self.transport(self.WIRE if wire is None else wire)
        return self.observe(fetcher)

    def result(self, wire=None):
        return minimized_redirect_evidence(self.response(wire), binding=self.BINDING)

    def test_original_response_roundtrip_capture_privacy_and_fresh_objects(self):
        response = self.response(); original = copy.deepcopy(response.redirect_observation)
        with patch("socket.create_connection", side_effect=AssertionError("No network")), \
            patch("hashlib.sha256", side_effect=AssertionError("No raw digest")):
            result = minimized_redirect_evidence(response, binding=self.BINDING)
            content = encode_redirect_evidence(result, binding=self.BINDING)
            parsed = parse_redirect_evidence(content, binding=self.BINDING)
        self.assertEqual(parsed, result); self.assertEqual(result["observed_at"], original["observed_at"])
        self.assertLess(len(content), MAX_RESULT_BYTES)
        for private in (b"private", b"secret", b"source_digest", b"location_url", b"headers", b"raw_body"):
            self.assertNotIn(private, content)
        response.redirect_observation["response_location"]["target_scheme"] = "https"
        parsed["evidence"]["response_location"]["same_origin"] = True
        self.assertEqual(result["evidence"]["response_location"]["target_scheme"], "http")
        self.assertFalse(result["evidence"]["response_location"]["same_origin"])

    def test_status_cardinality_classification_and_null_agreement_from_original_fields(self):
        for status in (200, 201, 300, 301, 302, 303, 304, 307, 308, 404, 599):
            for fields, state, scheme, same in ((b"", "absent", None, None), (b"Location: \t\r\n", "present_empty", None, None),
                (b"Location: /one\r\nLocation: /two\r\n", "multiple_fields", None, None),
                (b"Location: javascript:private\r\n", "single_unclassified", None, None),
                (b"Location: /relative?secret=value\r\n", "single_classified", "https", True),
                (b"Location: https://other.invalid/\r\n", "single_classified", "https", False),
                (b"Location: http://example.com/public\r\n", "single_classified", "http", False)):
                with self.subTest(status=status, state=state, scheme=scheme):
                    result = self.result(f"HTTP/1.1 {status} Example\r\n".encode() + fields + b"\r\n")
                    location = result["evidence"]["response_location"]
                    self.assertEqual((location["response_status"], location["redirect_status"]), (status, status in {301, 302, 303, 307, 308}))
                    self.assertEqual((location["location_state"], location["target_scheme"], location["same_origin"]), (state, scheme, same))
                    self.assertEqual(parse_redirect_evidence(encode_redirect_evidence(result, binding=self.BINDING), binding=self.BINDING), result)
        for changes in ({"response_status": True}, {"response_status": 301}, {"redirect_status": 1}, {"redirect_status": False},
            {"location_state": None}, {"location_state": "absent"}, {"target_scheme": None}, {"target_scheme": "ftp"},
            {"target_scheme": []}, {"same_origin": 0}, {"same_origin": None}, {"same_origin": True},
            {"state": "unavailable"}, {"raw_location": "private"}):
            result = self.result(); result["evidence"]["response_location"].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValidationError): validate_redirect_evidence(result, binding=self.BINDING)
        for state in ("absent", "present_empty", "multiple_fields", "single_unclassified"):
            result = self.result(b"HTTP/1.1 200 OK\r\n\r\n")
            location = result["evidence"]["response_location"]; location["location_state"] = state
            for key, value in (("target_scheme", "https"), ("same_origin", False)):
                broken = copy.deepcopy(result); broken["evidence"]["response_location"][key] = value
                with self.assertRaises(ValidationError): validate_redirect_evidence(broken, binding=self.BINDING)

    def test_original_dates_exact_verification_boundary_no_completion_rewrite(self):
        result = self.result()
        observed = datetime.fromisoformat(result["observed_at"])
        for delta, valid in ((timedelta(0), True), (timedelta(microseconds=-1), True), (timedelta(microseconds=1), False)):
            binding = {**self.BINDING, "verified_at": (observed + delta).isoformat()}
            if valid: self.assertEqual(validate_redirect_evidence(result, binding=binding), result)
            else:
                with self.assertRaises(ValidationError): validate_redirect_evidence(result, binding=binding)
        for date in ("2023-01-01T00:00:00.000000+00:00", "2025-01-01T00:00:00Z", "2025-01-01T00:00:00+00:00",
            "2025-01-01T00:00:00.000000+01:00", "9999-01-01T00:00:00.000000+00:00", "2025-02-30T00:00:00.000000+00:00", None):
            broken = copy.deepcopy(result); broken["observed_at"] = broken["evidence"]["observed_at"] = date
            with self.subTest(date=date), self.assertRaises(ValidationError): validate_redirect_evidence(broken, binding=self.BINDING)
        result["observed_at"] = "2025-01-01T00:00:00.000000+00:00"
        with self.assertRaises(ValidationError): validate_redirect_evidence(result, binding=self.BINDING)

    def test_exact_independent_binding_and_minimized_transport_shapes_fail_closed(self):
        response = self.response()
        for changes in ({"headers": {"server": "private"}}, {"body": b"private"}, {"body": ""}, {"redirects": []},
            {"redirects": ("private",)}, {"header_observation": {}}, {"resource_observation": {}}, {"status": True},
            {"status": 199}, {"status": 600}, {"status": "302"}, {"url": "https://foreign.invalid/"}, {"redirect_observation": None}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                minimized_redirect_evidence(replace(response, **changes), binding=self.BINDING)
        for changes in ({"collection_permission": 1}, {"observations": ["response_headers"]}, {"observations": ["response_location", "response_headers"]},
            {"method_version": "passive-resource-source-v1"}, {"source_digest": "private"}, {"actor_id": True},
            {"origin": "https://foreign.invalid"}, {"verified_at": "9999-01-01T00:00:00+00:00"}, {"raw": "private"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                minimized_redirect_evidence(response, binding={**self.BINDING, **changes})
        for binding in (None, [], "private"):
            with self.assertRaises(ValidationError): minimized_redirect_evidence(response, binding=binding)
        with self.assertRaises(ValidationError): minimized_redirect_evidence(FetchResponse(self.URL, 302, {}, b""), binding=self.BINDING)
        for path, value in ((["raw_body"], "private"), (["method"], "passive-header-collection-v1"),
            (["evidence", "raw_url"], "private"), (["evidence", "coverage"], "partial"),
            (["evidence", "response_location", "interpretation"], "secure")):
            result = self.result(); node = result
            for key in path[:-1]: node = node[key]
            node[path[-1]] = value
            with self.subTest(path=path), self.assertRaises(ValidationError): validate_redirect_evidence(result, binding=self.BINDING)

    def test_strict_original_bytes_duplicate_nonfinite_missing_and_extra_shapes(self):
        result = self.result(); content = encode_redirect_evidence(result, binding=self.BINDING)
        for data in (None, {}, "private", b"", b"\xff", b"null", b"[]", b"{}", b"NaN", b'{"private":Infinity}',
            b'{"method":"private",' + content[1:], b"[" * 1000,
            content + b" " * (MAX_RESULT_BYTES + 1 - len(content))):
            with self.subTest(kind=type(data)), self.assertRaises(ValidationError) as raised:
                parse_redirect_evidence(data, binding=self.BINDING)
            self.assertNotIn("private", str(raised.exception))
        self.assertEqual(parse_redirect_evidence(content + b" " * (MAX_RESULT_BYTES - len(content)), binding=self.BINDING), result)
        for path in ([], ["evidence"], ["evidence", "response_location"]):
            node = result
            for key in path: node = node[key]
            for key in node:
                broken = copy.deepcopy(result); target = broken
                for part in path: target = target[part]
                del target[key]
                with self.subTest(path=path, key=key), self.assertRaises(ValidationError): validate_redirect_evidence(broken, binding=self.BINDING)
            broken = copy.deepcopy(result); target = broken
            for part in path: target = target[part]
            target["private"] = "secret"
            with self.assertRaises(ValidationError): validate_redirect_evidence(broken, binding=self.BINDING)


class OriginalRedirectEvidenceTests(DatabaseTestCase):
    setUp = source_fixtures.PassiveHeaderSourceTests.setUp
    verified = source_fixtures.PassiveHeaderSourceTests.verified

    def test_original_verifier_source_transport_roundtrip_is_read_only_and_retains_capture(self):
        row = self.verified()
        data = {"url": self.project.canonical_origin + "/public", "observations": ["response_location"], "collection_permission": True}
        binding = passive_redirect_source(project=self.project, actor=self.owner, data=data)
        transport = PassiveRedirectEvidenceTests(); self.addCleanup(transport.doCleanups)
        fetcher, connection_mock, response_mock, factory, resolver = transport.transport(transport.WIRE)
        fetcher.scope = CrawlScope(frozenset({urlsplit(binding["url"]).hostname}))
        def current(url):
            self.assertEqual(url, binding["url"])
            self.assertEqual(passive_redirect_source(project=self.project, actor=self.owner, data=data), binding)
        with patch("socket.create_connection", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            response = fetcher.fetch(binding["url"], observe_redirects=True, before_request=current, before_send=current)
            result = minimized_redirect_evidence(response, binding=binding)
            self.assertEqual(parse_redirect_evidence(encode_redirect_evidence(result, binding=binding), binding=binding), result)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual(result["observed_at"], response.redirect_observation["observed_at"])
        self.assertNotIn(self.challenge, json.dumps(result)); self.assertEqual(binding["verification_id"], row.pk)
        factory.assert_called_once(); resolver.assert_called_once(); response_mock.read.assert_not_called()
        connection_mock.request.assert_called_once()
