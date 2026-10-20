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

from .crawling import CrawlScope
from .passive_http_redirect_evidence import (MAX_RESULT_BYTES, encode_http_redirect_evidence, minimized_http_redirect_evidence,
    parse_http_redirect_evidence, validate_http_redirect_evidence)
from .passive_http_redirect_source import passive_http_redirect_source
from . import test_passive_http_redirect_source as source_fixtures
from . import test_passive_http_redirect_transport as transport_fixtures


class PassiveHTTPRedirectEvidenceTests(TestCase):
    BINDING = {"method_version": "passive-http-redirect-source-v1", "organization_id": 1, "project_id": 2, "actor_id": 3,
        "origin": "http://example.com", "url": "http://example.com/public", "observations": ["http_response_location"],
        "collection_permission": True, "verification_id": 4, "verified_at": "2024-01-01T00:00:00+00:00",
        "source_digest": "a" * 64, "interpretation": "current_source_binding_not_network_job_commercial_reservation_or_observation_authority"}
    WIRE = b"HTTP/1.1 301 Moved\r\nLocation: https://example.com:443/private?secret=value\r\nSet-Cookie: private=secret\r\n\r\nprivate body"
    URL = transport_fixtures.PassiveHTTPRedirectTransportTests.URL
    transport = transport_fixtures.PassiveHTTPRedirectTransportTests.transport
    observe = transport_fixtures.PassiveHTTPRedirectTransportTests.observe

    def response(self, wire=None):
        fetcher, *_ = self.transport(self.WIRE if wire is None else wire)
        return self.observe(fetcher)

    def result(self, wire=None):
        return minimized_http_redirect_evidence(self.response(wire), binding=self.BINDING)

    def test_original_native_http_roundtrip_privacy_and_fresh_objects_preserve_plaintext_meaning(self):
        response = self.response(); original = copy.deepcopy(response.redirect_observation)
        with patch("socket.create_connection", side_effect=AssertionError("No network")), patch("hashlib.sha256", side_effect=AssertionError("No raw digest")):
            result = minimized_http_redirect_evidence(response, binding=self.BINDING)
            content = encode_http_redirect_evidence(result, binding=self.BINDING)
            parsed = parse_http_redirect_evidence(content, binding=self.BINDING)
        self.assertEqual(parsed, result); self.assertEqual(result["observed_at"], original["observed_at"])
        for private in (b"private", b"secret", b"source_digest", b"location_url", b"headers", b"raw_body"): self.assertNotIn(private, content)
        self.assertIn("not_authenticated_identity_observed_https_followed_upgrade", result["interpretation"])
        response.redirect_observation["response_location"]["same_hostname_default_https"] = False
        parsed["evidence"]["response_location"]["same_hostname_default_https"] = False
        self.assertTrue(result["evidence"]["response_location"]["same_hostname_default_https"])

    def test_native_status_independent_target_categories_unknown_null_and_strict_real_boolean_agreement(self):
        for status in (200, 201, 301, 302, 303, 304, 307, 308, 404, 599):
            for fields, state, scheme, same, counterpart in ((b"", "absent", None, None, None),
                (b"Location: \t\r\n", "present_empty", None, None, None), (b"Location: /one\r\nLocation: /two\r\n", "multiple_fields", None, None, None),
                (b"Location: javascript:private\r\n", "single_unclassified", None, None, None),
                (b"Location: /relative\r\n", "single_classified", "http", True, False),
                (b"Location: http://example.com:8080/\r\n", "single_classified", "http", False, False),
                (b"Location: https://example.com/\r\n", "single_classified", "https", False, True),
                (b"Location: https://example.com:444/\r\n", "single_classified", "https", False, False)):
                result = self.result(f"HTTP/1.1 {status} Example\r\n".encode() + fields + b"\r\n")
                location = result["evidence"]["response_location"]
                self.assertEqual((location["location_state"], location["target_scheme"], location["same_origin"], location["same_hostname_default_https"]), (state, scheme, same, counterpart))
                self.assertEqual(location["redirect_status"], status in {301, 302, 303, 307, 308})
                self.assertEqual(parse_http_redirect_evidence(encode_http_redirect_evidence(result, binding=self.BINDING), binding=self.BINDING), result)
        for changes in ({"response_status": True}, {"response_status": 302}, {"redirect_status": 1}, {"redirect_status": False},
            {"target_scheme": "http"}, {"target_scheme": None}, {"target_scheme": []}, {"same_origin": True}, {"same_origin": 0},
            {"same_hostname_default_https": 1}, {"same_hostname_default_https": None}, {"location_state": "absent"},
            {"state": "unavailable"}, {"raw_location": "private"}):
            result = self.result(); result["evidence"]["response_location"].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValidationError): validate_http_redirect_evidence(result, binding=self.BINDING)
        for state in ("absent", "present_empty", "multiple_fields", "single_unclassified"):
            result = self.result(b"HTTP/1.1 200 OK\r\n\r\n"); result["evidence"]["response_location"]["location_state"] = state
            for key, value in (("target_scheme", "https"), ("same_origin", False), ("same_hostname_default_https", False)):
                broken = copy.deepcopy(result); broken["evidence"]["response_location"][key] = value
                with self.assertRaises(ValidationError): validate_http_redirect_evidence(broken, binding=self.BINDING)

    def test_original_capture_dates_exact_verification_microsecond_boundary_and_no_duplicate_date_rewrite(self):
        result = self.result(); observed = datetime.fromisoformat(result["observed_at"])
        for delta, valid in ((timedelta(0), True), (timedelta(microseconds=-1), True), (timedelta(microseconds=1), False)):
            binding = {**self.BINDING, "verified_at": (observed + delta).isoformat()}
            if valid: self.assertEqual(validate_http_redirect_evidence(result, binding=binding), result)
            else:
                with self.assertRaises(ValidationError): validate_http_redirect_evidence(result, binding=binding)
        for date in ("2023-01-01T00:00:00.000000+00:00", "2025-01-01T00:00:00Z", "2025-01-01T00:00:00+00:00",
            "2025-01-01T00:00:00.000000+01:00", "9999-01-01T00:00:00.000000+00:00", "2025-02-30T00:00:00.000000+00:00", None):
            broken = copy.deepcopy(result); broken["observed_at"] = broken["evidence"]["observed_at"] = date
            with self.assertRaises(ValidationError): validate_http_redirect_evidence(broken, binding=self.BINDING)
        result["observed_at"] = "2025-01-01T00:00:00.000000+00:00"
        with self.assertRaises(ValidationError): validate_http_redirect_evidence(result, binding=self.BINDING)

    def test_independent_binding_transport_method_and_other_family_metadata_fail_closed(self):
        response = self.response()
        for changes in ({"headers": {"server": "private"}}, {"body": b"private"}, {"body": ""}, {"redirects": []},
            {"header_observation": {}}, {"resource_observation": {}}, {"status": True}, {"status": 199}, {"status": 600},
            {"url": "https://example.com/public"}, {"redirect_observation": None}, {"observed_at": response.redirect_observation["observed_at"]}):
            with self.assertRaises(ValidationError): minimized_http_redirect_evidence(replace(response, **changes), binding=self.BINDING)
        for changes in ({"collection_permission": 1}, {"observations": ["response_location"]}, {"method_version": "passive-redirect-source-v1"},
            {"url": "https://example.com/public", "origin": "https://example.com"}, {"source_digest": "private"}, {"actor_id": True}, {"raw": "private"}):
            with self.assertRaises(ValidationError): minimized_http_redirect_evidence(response, binding={**self.BINDING, **changes})
        for path, value in ((["method"], "passive-redirect-evidence-v1"), (["evidence", "method_version"], "passive-redirect-response-v1"),
            (["evidence", "coverage"], "one_original_first_https_response_only"), (["evidence", "response_location", "method_version"], "passive-response-location-v1")):
            result = self.result(); node = result
            for key in path[:-1]: node = node[key]
            node[path[-1]] = value
            with self.assertRaises(ValidationError): validate_http_redirect_evidence(result, binding=self.BINDING)

    def test_exact_utf8_duplicate_nonfinite_byte_bounds_and_all_missing_extra_fields_are_denied(self):
        result = self.result(); content = encode_http_redirect_evidence(result, binding=self.BINDING)
        for data in (None, {}, "private", b"", b"\xff", b"null", b"[]", b"{}", b"NaN", b'{"private":Infinity}',
            b'{"method":"private",' + content[1:], b"[" * 1000, content + b" " * (MAX_RESULT_BYTES + 1 - len(content))):
            with self.assertRaises(ValidationError) as raised: parse_http_redirect_evidence(data, binding=self.BINDING)
            self.assertNotIn("private", str(raised.exception))
        self.assertEqual(parse_http_redirect_evidence(content + b" " * (MAX_RESULT_BYTES - len(content)), binding=self.BINDING), result)
        for path in ([], ["evidence"], ["evidence", "response_location"]):
            node = result
            for key in path: node = node[key]
            for key in node:
                broken = copy.deepcopy(result); target = broken
                for part in path: target = target[part]
                del target[key]
                with self.assertRaises(ValidationError): validate_http_redirect_evidence(broken, binding=self.BINDING)
            broken = copy.deepcopy(result); target = broken
            for part in path: target = target[part]
            target["private"] = "secret"
            with self.assertRaises(ValidationError): validate_http_redirect_evidence(broken, binding=self.BINDING)


class OriginalHTTPRedirectEvidenceTests(DatabaseTestCase):
    setUp = source_fixtures.PassiveHTTPRedirectSourceTests.setUp
    verified = source_fixtures.PassiveHTTPRedirectSourceTests.verified

    def test_genuine_configured_http_verifier_source_native_capture_byte_roundtrip_read_only_original_date(self):
        row = self.verified(); data = {"url": self.project.canonical_origin + "/public", "observations": ["http_response_location"], "collection_permission": True}
        binding = passive_http_redirect_source(project=self.project, actor=self.owner, data=data)
        transport = PassiveHTTPRedirectEvidenceTests(); self.addCleanup(transport.doCleanups)
        fetcher, connection_mock, response_mock, factory, resolver = transport.transport(transport.WIRE)
        fetcher.scope = CrawlScope(frozenset({urlsplit(binding["url"]).hostname}))
        def current(url):
            self.assertEqual(url, binding["url"]); self.assertEqual(passive_http_redirect_source(project=self.project, actor=self.owner, data=data), binding)
        with patch("socket.create_connection", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            response = fetcher.fetch(binding["url"], observe_http_redirects=True, before_request=current, before_send=current)
            result = minimized_http_redirect_evidence(response, binding=binding)
            self.assertEqual(parse_http_redirect_evidence(encode_http_redirect_evidence(result, binding=binding), binding=binding), result)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual(result["observed_at"], response.redirect_observation["observed_at"])
        self.assertNotIn(self.challenge, json.dumps(result)); self.assertEqual(binding["verification_id"], row.pk)
        factory.assert_called_once(); resolver.assert_called_once(); response_mock.read.assert_not_called(); connection_mock.request.assert_called_once()
