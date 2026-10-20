import json
import ssl
from datetime import datetime, UTC
from unittest import TestCase
from unittest.mock import Mock, patch

from django.core.exceptions import PermissionDenied
from django.test import TestCase as DatabaseTestCase
from django.utils import timezone

from tenancy.models import ProjectOriginVerification
from .crawling import CrawlScope, FetchDenied, FetchError, FetchLimitExceeded, SafeFetcher
from . import passive_redirect_source as source
from . import test_passive_header_transport as transport_fixtures
from . import test_passive_header_source as source_fixtures


class PassiveRedirectTransportTests(TestCase):
    URL = transport_fixtures.PassiveHeaderTransportTests.URL
    transport = transport_fixtures.PassiveHeaderTransportTests.transport

    def observe(self, fetcher, **kwargs):
        return fetcher.fetch(self.URL, observe_redirects=True, before_request=Mock(), before_send=Mock(), **kwargs)

    def test_original_multi_value_minimized_capture_default_validated_pins_no_raw_body_or_family_union(self):
        fetcher, connection, response, factory, resolver = self.transport(
            b"HTTP/1.1 302 Found\r\nLocation: http://private.invalid/?secret=value\r\n"
            b"Set-Cookie: private=secret\r\nContent-Security-Policy: nonce-private\r\n\r\nprivate body")
        before, send = Mock(), Mock(); start = timezone.now()
        with patch("socket.create_connection", side_effect=AssertionError("No actual egress")):
            result = fetcher.fetch(self.URL, observe_redirects=True, before_request=before, before_send=send)
        info = result.redirect_observation; self.assertEqual(info["method_version"], "passive-redirect-response-v1")
        stamp = datetime.fromisoformat(info["observed_at"])
        self.assertTrue(start <= stamp <= timezone.now()); self.assertEqual(stamp.isoformat(timespec="microseconds"), info["observed_at"])
        self.assertEqual(stamp.tzinfo, UTC)
        self.assertEqual((info["response_location"]["response_status"], info["response_location"]["target_scheme"], info["response_location"]["same_origin"]), (302, "http", False))
        self.assertEqual((result.url, result.status, result.headers, result.body, result.redirects), (self.URL, 302, {}, b"", ()))
        self.assertIsNone(result.header_observation); self.assertIsNone(result.resource_observation)
        for raw in ("private", "secret", "location_url", "digest", "headers", "cookies"):
            self.assertNotIn(raw, json.dumps(info))
        self.assertEqual(before.call_count, 2); self.assertEqual(send.call_count, 2)
        factory.assert_called_once(); resolver.assert_called_once()
        self.assertEqual(factory.call_args.args[:4], ("https", "93.184.216.34", "example.com", 443))
        connection.request.assert_called_once(); self.assertEqual(connection.request.call_args.args, ("GET", "/public"))
        response.read.assert_not_called(); connection.close.assert_called_once(); self.assertTrue(response.closed)

    def test_first_only_duplicate_absent_empty_unsupported_and_nonredirect_metadata_not_target_success(self):
        for status in (200, 201, 301, 302, 303, 307, 308, 404):
            for fields, expected in ((b"", "absent"), (b"Location: \t\r\n", "present_empty"),
                (b"Location: /one\r\nLocation: /two\r\n", "multiple_fields"), (b"Location: https://[::1\r\n", "single_unclassified"),
                (b"Location: http://169.254.169.254/\r\n", "single_classified")):
                fetcher, connection, response, factory, resolver = self.transport(f"HTTP/1.1 {status} Example\r\n".encode() + fields + b"\r\n")
                result = self.observe(fetcher)
                self.assertEqual(result.redirect_observation["response_location"]["location_state"], expected)
                self.assertEqual(result.status, status); factory.assert_called_once(); resolver.assert_called_once()
                response.read.assert_not_called(); connection.request.assert_called_once()
                self.assertNotIn("169.254", json.dumps(result.redirect_observation))

    def test_exact_input_mutually_exclusive_modes_and_both_callbacks_required_before_dns(self):
        for options in ({"url": "http://example.com/public"}, {"url": "https://example.com"}, {"url": self.URL + "?"},
            {"url": self.URL + "#"}, {"url": "https://example.com:443/public"}, {"url": "https://user:secret@example.com/public"},
            {"request_headers": {}}, {"before_request": None}, {"before_send": None}, {"observe_redirects": 1},
            {"observe_headers": True}, {"observe_resources": True}):
            fetcher, connection, response, factory, resolver = self.transport()
            arguments = {"url": self.URL, "observe_redirects": True, "before_request": Mock(), "before_send": Mock(), **options}
            with self.assertRaises(FetchDenied): fetcher.fetch(**arguments)
            resolver.assert_not_called(); factory.assert_not_called()

    def test_current_authority_loss_before_dns_after_dns_connected_and_completion_closes_without_follow(self):
        for boundary in ("before_dns", "after_dns", "connected", "completion"):
            fetcher, connection, response, factory, resolver = self.transport(b"HTTP/1.1 302 Found\r\nLocation: /next\r\n\r\n")
            before = Mock(side_effect=PermissionDenied if boundary == "before_dns" else [None, PermissionDenied] if boundary == "completion" else None)
            send = Mock(side_effect=PermissionDenied if boundary == "after_dns" else [None, PermissionDenied] if boundary == "connected" else None)
            with self.assertRaises(PermissionDenied): fetcher.fetch(self.URL, observe_redirects=True, before_request=before, before_send=send)
            if boundary != "completion": connection.request.assert_not_called()
            if boundary == "before_dns": resolver.assert_not_called()
            if boundary in {"connected", "completion"}: connection.close.assert_called_once()
            response.read.assert_not_called()

    def test_original_header_defects_status_and_complete_bounds_fail_categorically(self):
        for wire in (b"HTTP/1.1 302 Found\r\nmalformed original header\r\n\r\n", b"HTTP/1.1 302 Found\r\nX: private\x00\r\n\r\n",
            b"HTTP/1.1 600 Unknown\r\n\r\n", b"HTTP/1.1 302 Found\r\n" + b"X: private\r\n" * 101 + b"\r\n",
            b"HTTP/1.1 302 Found\r\nLocation: " + b"x" * 8193 + b"\r\n\r\n"):
            # stdlib refuses >100 fields itself; inject after original parsing for the parser bound.
            if wire.count(b"X: private") == 101:
                fetcher, connection, response, factory, resolver = self.transport()
                response.getheaders = Mock(return_value=[("X", "private")] * 101)
            else: fetcher, connection, response, factory, resolver = self.transport(wire)
            with self.assertRaises(FetchError): self.observe(fetcher)
            connection.close.assert_called_once(); response.read.assert_not_called()

    def test_connected_completion_deadlines_and_strict_tls_failure_never_send_or_retry_unverified(self):
        for boundary in ("connected", "completion"):
            clock = Mock(return_value=0); fetcher, connection, response, factory, resolver = self.transport(clock=clock)
            calls = 0
            def expire(_url):
                nonlocal calls
                calls += 1
                if calls == 2: clock.return_value = 11
            before = expire if boundary == "completion" else Mock()
            send = expire if boundary == "connected" else Mock()
            with self.assertRaises(FetchLimitExceeded):
                fetcher.fetch(self.URL, observe_redirects=True, before_request=before, before_send=send)
            if boundary == "connected": connection.request.assert_not_called()
            response.read.assert_not_called(); connection.close.assert_called_once()
        fetcher, connection, response, factory, resolver = self.transport()
        connection.connect.side_effect = ssl.SSLCertVerificationError("fixture")
        with self.assertRaises(FetchError): self.observe(fetcher)
        connection.request.assert_not_called(); factory.assert_called_once(); connection.close.assert_called_once()


class GenuinePassiveRedirectTransportTests(DatabaseTestCase):
    setUp = source_fixtures.PassiveHeaderSourceTests.setUp
    verified = source_fixtures.PassiveHeaderSourceTests.verified

    def test_original_verifier_named_source_actual_response_and_final_late_revocation(self):
        self.verified(); data = {"url": self.project.canonical_origin + "/public", "observations": ["response_location"], "collection_permission": True}
        original = source.passive_redirect_source(project=self.project, actor=self.owner, data=data)
        response_case = PassiveRedirectTransportTests(); self.addCleanup(response_case.doCleanups)
        _fetcher, connection, response, _factory, _resolver = response_case.transport(b"HTTP/1.1 302 Found\r\nLocation: /relative?secret=value\r\n\r\n")
        fetcher = SafeFetcher(CrawlScope(frozenset({"security.example.com"})), resolver=lambda *args: ["93.184.216.34"], connection_factory=lambda *args: connection)
        def current(url):
            if url != data["url"] or source.passive_redirect_source(project=self.project, actor=self.owner, data=data) != original: raise PermissionDenied
        with patch("socket.create_connection", side_effect=AssertionError("No actual egress")):
            result = fetcher.fetch(data["url"], observe_redirects=True, before_request=current, before_send=current)
        self.assertTrue(result.redirect_observation["response_location"]["same_origin"])
        self.assertGreaterEqual(datetime.fromisoformat(result.redirect_observation["observed_at"]), datetime.fromisoformat(original["verified_at"]))
        self.assertIsNone(result.header_observation); response.read.assert_not_called()
        # A fresh original response cannot be returned once hidden original verification drifts.
        _fetcher, connection, response, _factory, _resolver = response_case.transport()
        fetcher = SafeFetcher(CrawlScope(frozenset({"security.example.com"})), resolver=lambda *args: ["93.184.216.34"], connection_factory=lambda *args: connection)
        response.getheaders = Mock(side_effect=lambda: (ProjectOriginVerification.objects.filter(pk=original["verification_id"]).update(challenge_digest="a" * 64), [])[1])
        with self.assertRaises(PermissionDenied): fetcher.fetch(data["url"], observe_redirects=True, before_request=current, before_send=current)
        connection.request.assert_called_once(); response.read.assert_not_called(); connection.close.assert_called_once()
