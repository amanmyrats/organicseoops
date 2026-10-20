import copy
import json
from dataclasses import replace
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase as DatabaseTestCase
from django.test.utils import CaptureQueriesContext

from .crawling import CrawlScope, FetchResponse
from .passive_resource_evidence import MAX_RESULT_BYTES, encode_resource_evidence, minimized_resource_evidence, parse_resource_evidence, validate_resource_evidence
from .passive_resource_source import passive_resource_source
from . import test_passive_header_source as source_fixtures
from . import test_passive_resource_transport as transport_fixtures


class PassiveResourceEvidenceTests(TestCase):
    BINDING = {"method_version": "passive-resource-source-v1", "organization_id": 1, "project_id": 2, "actor_id": 3,
        "origin": "https://example.com", "url": "https://example.com/public", "observations": ["static_resource_references"],
        "collection_permission": True, "verification_id": 4, "verified_at": "2024-01-01T00:00:00+00:00",
        "source_digest": "a" * 64, "interpretation": "current_source_binding_not_network_job_commercial_reservation_or_observation_authority"}
    HTML = transport_fixtures.PassiveResourceTransportTests.HTML
    transport = transport_fixtures.PassiveResourceTransportTests.transport
    observe = transport_fixtures.PassiveResourceTransportTests.observe
    URL = transport_fixtures.PassiveResourceTransportTests.URL

    def response(self, body=None):
        fetcher, *_ = self.transport(body)
        return self.observe(fetcher)

    def result(self, body=None):
        return minimized_resource_evidence(self.response(body), binding=self.BINDING)

    def test_independent_redirect_metadata_cannot_be_mixed_into_genuine_resource_response(self):
        response = self.response()
        with self.assertRaises(ValidationError):
            minimized_resource_evidence(replace(response, redirect_observation={"method_version": "passive-redirect-response-v1"}), binding=self.BINDING)

    def test_actual_response_roundtrip_preserves_capture_date_privacy_and_fresh_objects(self):
        response = self.response(); original = copy.deepcopy(response.resource_observation)
        with patch("socket.create_connection", side_effect=AssertionError("No network")), \
            patch("hashlib.sha256", side_effect=AssertionError("No raw digest")):
            result = minimized_resource_evidence(response, binding=self.BINDING)
            content = encode_resource_evidence(result, binding=self.BINDING)
            self.assertEqual(parse_resource_evidence(content, binding=self.BINDING), result)
        self.assertEqual(result["observed_at"], original["observed_at"])
        self.assertLess(len(content), MAX_RESULT_BYTES)
        for private in (b"private", b"secret", b"source_digest", b"src=", b"raw_body"):
            self.assertNotIn(private, content)
        response.resource_observation["resource_references"]["counts"]["http_absolute"] = 999
        self.assertEqual(result["evidence"]["resource_references"]["counts"]["http_absolute"], 1)

    def test_lexical_unavailable_nulls_and_count_sum_ceiling_types_are_exact(self):
        for body, reason in ((b"<img src='http://private.invalid/' src='other'>", "ambiguous_markup"),
            (b"\x00<img src='http://private.invalid/'>", "invalid_body"), (b"<img src='/'>" * 1001, "reference_limit")):
            result = self.result(body)
            resources = result["evidence"]["resource_references"]
            self.assertEqual((resources["state"], resources["reason"]), ("unavailable", reason))
            self.assertTrue(all(value is None for value in resources["counts"].values()))
            resources["counts"]["http_absolute"] = 0
            with self.assertRaises(ValidationError): validate_resource_evidence(result, binding=self.BINDING)
        for value in (True, -1, 1001, "1", 1.0, None):
            result = self.result(); result["evidence"]["resource_references"]["counts"]["http_absolute"] = value
            with self.subTest(value=value), self.assertRaises(ValidationError): validate_resource_evidence(result, binding=self.BINDING)
        result = self.result(); result["evidence"]["resource_references"]["counts"]["inspected_attributes"] += 1
        with self.assertRaises(ValidationError): validate_resource_evidence(result, binding=self.BINDING)
        result = self.result(b"<img src='http://private.invalid/'>" * 1000)
        self.assertEqual(result["evidence"]["resource_references"]["counts"]["inspected_attributes"], 1000)
        self.assertEqual(parse_resource_evidence(encode_resource_evidence(result, binding=self.BINDING), binding=self.BINDING), result)

    def test_full_binding_scope_date_and_minimized_transport_shapes_fail_closed(self):
        response = self.response()
        for changes in ({"headers": {"server": "private"}}, {"body": b"private"}, {"body": ""}, {"redirects": [ ]},
            {"redirects": ("private",)}, {"header_observation": {}}, {"status": True}, {"status": 206},
            {"url": "https://foreign.invalid/"}, {"resource_observation": None}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                minimized_resource_evidence(replace(response, **changes), binding=self.BINDING)
        for date in ("2023-01-01T00:00:00.000000+00:00", "2025-01-01T00:00:00Z", "2025-01-01T00:00:00+00:00",
            "2025-01-01T00:00:00.000000+01:00", "9999-01-01T00:00:00.000000+00:00", "private", None):
            result = self.result(); result["observed_at"] = result["evidence"]["observed_at"] = date
            with self.subTest(date=date), self.assertRaises(ValidationError): validate_resource_evidence(result, binding=self.BINDING)
        for changes in ({"collection_permission": 1}, {"observations": ["response_headers"]}, {"method_version": "passive-header-source-v1"},
            {"source_digest": "private"}, {"actor_id": True}, {"origin": "https://foreign.invalid"},
            {"verified_at": "9999-01-01T00:00:00+00:00"}, {"raw": "private"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                minimized_resource_evidence(response, binding={**self.BINDING, **changes})
        paths = ((["raw_body"], "private"), (["evidence", "raw_url"], "private"),
            (["evidence", "coverage"], "partial"), (["evidence", "resource_references", "reason"], "body_incomplete"),
            (["evidence", "resource_references", "selected_attributes"], ["a/href"]),
            (["evidence", "resource_references", "counts", "raw_url"], "private"))
        for path, value in paths:
            result = self.result(); target = result
            for key in path[:-1]: target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path), self.assertRaises(ValidationError): validate_resource_evidence(result, binding=self.BINDING)
        for binding in (None, [], "private"):
            with self.assertRaises(ValidationError): minimized_resource_evidence(response, binding=binding)
        with self.assertRaises(ValidationError): minimized_resource_evidence(FetchResponse(self.URL, 200, {}, b""), binding=self.BINDING)

    def test_original_utf8_bounded_duplicate_nonfinite_and_missing_shape_json_is_rejected(self):
        result = self.result(); content = encode_resource_evidence(result, binding=self.BINDING)
        for data in (None, {}, "private", b"", b"\xff", b"null", b"[]", b"{}", b"NaN", b'{"private":Infinity}',
            b'{"method":"private",' + content[1:], b"[" * 1000,
            content + b" " * (MAX_RESULT_BYTES + 1 - len(content))):
            with self.subTest(kind=type(data)), self.assertRaises(ValidationError) as raised:
                parse_resource_evidence(data, binding=self.BINDING)
            self.assertNotIn("private", str(raised.exception))
        self.assertEqual(parse_resource_evidence(content + b" " * (MAX_RESULT_BYTES - len(content)), binding=self.BINDING), result)
        for path in ([], ["evidence"], ["evidence", "resource_references"], ["evidence", "resource_references", "counts"]):
            target = result
            for key in path: target = target[key]
            for key in target:
                broken = copy.deepcopy(result); node = broken
                for part in path: node = node[part]
                del node[key]
                with self.subTest(path=path, key=key), self.assertRaises(ValidationError):
                    validate_resource_evidence(broken, binding=self.BINDING)


class OriginalResourceEvidenceTests(DatabaseTestCase):
    setUp = source_fixtures.PassiveHeaderSourceTests.setUp
    verified = source_fixtures.PassiveHeaderSourceTests.verified

    def test_original_verifier_binding_transport_roundtrip_is_read_only_and_never_reconstructs_time(self):
        row = self.verified()
        binding = passive_resource_source(project=self.project, actor=self.owner,
            data={"url": self.project.canonical_origin + "/public", "observations": ["static_resource_references"], "collection_permission": True})
        transport = PassiveResourceEvidenceTests()
        self.addCleanup(transport.doCleanups)
        fetcher, *_ = transport.transport()
        fetcher.scope = CrawlScope(frozenset({urlsplit(binding["url"]).hostname}))
        def current(url):
            self.assertEqual(url, binding["url"])
            self.assertEqual(passive_resource_source(project=self.project, actor=self.owner,
                data={key: binding[key] for key in ("url", "observations", "collection_permission")}), binding)
        with patch("socket.create_connection", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            response = fetcher.fetch(binding["url"], observe_resources=True, before_request=current, before_send=current)
            result = minimized_resource_evidence(response, binding=binding)
            self.assertEqual(parse_resource_evidence(encode_resource_evidence(result, binding=binding), binding=binding), result)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual(result["observed_at"], response.resource_observation["observed_at"])
        self.assertNotIn(self.challenge, json.dumps(result))
        self.assertEqual(binding["verification_id"], row.pk)
