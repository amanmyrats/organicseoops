import copy
import json
from datetime import UTC, datetime, timedelta
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase as DjangoTestCase
from django.test.utils import CaptureQueriesContext

from .crawling import CrawlScope, SafeFetcher
from .passive_certificate import observe_peer_certificate_dates
from .passive_tls_evidence import MAX_RESULT_BYTES, encode_tls_evidence, minimized_tls_evidence, parse_tls_evidence, validate_tls_evidence
from .passive_tls_source import passive_tls_source
from . import test_passive_header_source as source_fixtures


class PassiveTLSEvidenceTests(TestCase):
    ORIGIN = "https://example.com"
    BINDING = {"method_version": "passive-tls-source-v1", "organization_id": 1, "project_id": 2, "actor_id": 3,
        "origin": ORIGIN, "observations": ["certificate_dates", "negotiated_tls"], "collection_permission": True,
        "verification_id": 4, "verified_at": "2024-01-01T00:00:00+00:00", "source_digest": "a" * 64,
        "interpretation": "current_source_binding_not_network_job_commercial_reservation_or_observation_authority"}

    def observation(self):
        # Actual h observer: only transport is injected; no fabricated stored job/capture provenance.
        sock = Mock()
        sock.getpeercert.return_value = {"notBefore": "Jan  1 00:00:00 2024 GMT", "notAfter": "Jan  1 00:00:00 2030 GMT",
                                       "subject": "private-customer", "OCSP": ("http://127.0.0.1/private",)}
        sock.version.return_value = "TLSv1.3"; sock.cipher.return_value = ("TLS_AES_256_GCM_SHA384", "TLSv1.2", 256)
        connection = Mock(sock=sock)
        fetcher = SafeFetcher(CrawlScope(frozenset({urlsplit(self.ORIGIN).hostname})), resolver=lambda *args: ["93.184.216.34"],
            connection_factory=lambda *args: connection)
        observation = fetcher.observe_tls(self.ORIGIN, before_request=Mock(), before_send=Mock())
        connection.request.assert_not_called()
        return observation

    def result(self):
        return minimized_tls_evidence(self.observation(), binding=self.BINDING)

    def test_actual_transport_to_strict_private_roundtrip_preserves_original_time_and_fresh_objects(self):
        observation = self.observation(); original = copy.deepcopy(observation)
        with patch("socket.create_connection", side_effect=AssertionError("network")), \
            patch("hashlib.sha256", side_effect=AssertionError("raw certificate digest")):
            result = minimized_tls_evidence(observation, binding=self.BINDING)
            content = encode_tls_evidence(result, binding=self.BINDING)
            self.assertEqual(parse_tls_evidence(content, binding=self.BINDING), result)
        self.assertEqual(observation, original)
        self.assertEqual(result["observed_at"], original["observed_at"])
        self.assertLess(len(content), MAX_RESULT_BYTES)
        self.assertNotIn(b"private", content)
        self.assertNotIn(b"source_digest", content)
        observation["negotiated_tls"]["version"] = "private"
        self.assertEqual(result["evidence"]["negotiated_tls"]["version"], "TLSv1.3")

    def test_exact_original_dates_inclusive_microseconds_and_nulls_cannot_be_recast(self):
        observed = datetime(2025, 1, 1, tzinfo=UTC)
        for offset, expected in ((-1, "1"), (0, "0"), (1, "-1")):
            observation = self.observation()
            date = observed + timedelta(microseconds=offset)
            observation["observed_at"] = date.isoformat(timespec="microseconds")
            observation["certificate_dates"] = observe_peer_certificate_dates(
                {"notBefore": "Jan  1 00:00:00 2024 GMT", "notAfter": "Jan  1 00:00:00 2025 GMT"}, observed_at=date)
            result = minimized_tls_evidence(observation, binding=self.BINDING)
            self.assertEqual(result["evidence"]["certificate_dates"]["remaining_microseconds"], expected)
            for value in (0, "-0", "0.0", "000", "1" if expected != "1" else "2"):
                broken = copy.deepcopy(result); broken["evidence"]["certificate_dates"]["remaining_microseconds"] = value
                with self.assertRaises(ValidationError): validate_tls_evidence(broken, binding=self.BINDING)
        observation = self.observation()
        observation["certificate_dates"] = observe_peer_certificate_dates(None, observed_at=datetime.fromisoformat(observation["observed_at"]))
        observation["negotiated_tls"] = {"version": None, "cipher": None}
        result = minimized_tls_evidence(observation, binding=self.BINDING)
        self.assertIsNone(parse_tls_evidence(encode_tls_evidence(result, binding=self.BINDING), binding=self.BINDING)["evidence"]["certificate_dates"]["not_after"])
        result["evidence"]["certificate_dates"]["remaining_microseconds"] = "0"
        with self.assertRaises(ValidationError): validate_tls_evidence(result, binding=self.BINDING)

    def test_full_shapes_scope_original_time_bounds_and_parameter_types_fail_closed(self):
        result = self.result()
        def change(path, value):
            broken = copy.deepcopy(result); target = broken
            for key in path[:-1]: target = target[key]
            target[path[-1]] = value
            return broken
        invalid = ((["origin"], "https://foreign.example"), (["method"], "unknown"), (["raw"], "private"),
            (["evidence", "subject"], "private"), (["evidence", "certificate_dates", "serial"], "private"),
            (["evidence", "negotiated_tls", "cipher", "protocol"], "TLSv1.2"),
            (["evidence", "negotiated_tls", "cipher", "secret_bits"], True),
            (["evidence", "negotiated_tls", "cipher", "name"], "private\n"),
            (["evidence", "negotiated_tls", "version"], "unknown"),
            (["evidence", "certificate_dates", "not_after"], "2030-02-30T00:00:00.000000+00:00"),
            (["evidence", "certificate_dates", "not_before"], "2031-01-01T00:00:00.000000+00:00"),
            (["evidence", "certificate_dates", "not_after"], "2030-01-01T00:00:00.000001+00:00"),
            (["evidence", "certificate_dates", "position"], "after_reported_window"),
            (["observed_at"], "2023-01-01T00:00:00.000000+00:00"), (["observed_at"], "2025-01-01T00:00:00Z"))
        for path, value in invalid:
            with self.subTest(path=path), self.assertRaises(ValidationError): validate_tls_evidence(change(path, value), binding=self.BINDING)
        for date in ("2023-01-01T00:00:00.000000+00:00", "2025-01-01T00:00:00.000000+01:00",
                     "9999-01-01T00:00:00.000000+00:00", "2025-01-01T00:00:00+00:00"):
            observation = self.observation(); observation["observed_at"] = date
            observation["certificate_dates"]["observed_at"] = date
            with self.assertRaises(ValidationError): minimized_tls_evidence(observation, binding=self.BINDING)
        for changes in ({"collection_permission": 1}, {"observations": ["response_headers"]}, {"source_digest": "private"},
            {"actor_id": True}, {"verified_at": "9999-01-01T00:00:00+00:00"}, {"private": "extra"}):
            with self.assertRaises(ValidationError): validate_tls_evidence(result, binding={**self.BINDING, **changes})

    def test_original_bounded_utf8_json_duplicate_nonfinite_extra_and_malformed_inputs_are_rejected(self):
        result = self.result(); content = encode_tls_evidence(result, binding=self.BINDING)
        for binding in (None, [], "private"):
            with self.assertRaises(ValidationError): validate_tls_evidence(result, binding=binding)
            with self.assertRaises(ValidationError): minimized_tls_evidence(self.observation(), binding=binding)
        duplicate = b'{"method":"private",' + content[1:]
        for data in (None, {}, "private", b"", b"\xff", b"null", b"NaN", b"[]", b"{}", duplicate,
            b'{"private":Infinity}', b"[" * 1000, content + b" " * (MAX_RESULT_BYTES + 1 - len(content))):
            with self.assertRaises(ValidationError) as raised: parse_tls_evidence(data, binding=self.BINDING)
            self.assertNotIn("private", str(raised.exception))
        padded = content + b" " * (MAX_RESULT_BYTES - len(content))
        self.assertEqual(parse_tls_evidence(padded, binding=self.BINDING), result)
        for key in result:
            broken = {name: value for name, value in result.items() if name != key}
            with self.assertRaises(ValidationError): validate_tls_evidence(broken, binding=self.BINDING)


class PassiveTLSEvidenceBindingTests(DjangoTestCase):
    setUp = source_fixtures.PassiveHeaderSourceTests.setUp
    verified = source_fixtures.PassiveHeaderSourceTests.verified

    def test_genuine_http_file_source_to_actual_handshake_projection_readback_without_writes(self):
        verified = self.verified()
        binding = passive_tls_source(project=self.project, actor=self.owner,
            data={"origin": self.project.canonical_origin, "observations": ["certificate_dates", "negotiated_tls"], "collection_permission": True})
        transport = PassiveTLSEvidenceTests(); transport.ORIGIN = self.project.canonical_origin
        with patch("socket.create_connection", side_effect=AssertionError("network")), CaptureQueriesContext(connection) as queries:
            original = transport.observation()
            result = minimized_tls_evidence(original, binding=binding)
            self.assertEqual(parse_tls_evidence(encode_tls_evidence(result, binding=binding), binding=binding), result)
        self.assertGreaterEqual(datetime.fromisoformat(result["observed_at"]), verified.verified_at)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertNotIn(self.challenge, json.dumps(result))
