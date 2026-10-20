import json
from dataclasses import replace
from datetime import datetime, UTC
from unittest import TestCase
from unittest.mock import Mock, patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase as DatabaseTestCase
from django.utils import timezone

from tenancy.models import ProjectOriginVerification
from .crawling import CrawlScope, FetchDenied, FetchError, FetchLimitExceeded, SafeFetcher, _PinnedHTTPConnection
from . import passive_http_redirect_source as source
from . import test_passive_header_transport as transport_fixtures
from . import test_passive_http_redirect_source as source_fixtures


class PassiveHTTPRedirectTransportTests(TestCase):
    URL = "http://example.com/public"
    transport = transport_fixtures.PassiveHeaderTransportTests.transport

    def observe(self, fetcher, **changes):
        return fetcher.fetch(**{**dict(url=self.URL, observe_http_redirects=True, before_request=Mock(), before_send=Mock()), **changes})

    def test_original_http_first_response_pinned80_plaintext_date_minimized_and_never_requests_https_counterpart(self):
        fetcher, connection, response, factory, resolver = self.transport(
            b"HTTP/1.1 301 Moved Permanently\r\nLocation: https://example.com:443/private?secret=value\r\n"
            b"Set-Cookie: private=secret\r\nContent-Length: 999999999\r\n\r\nprivate body")
        before, send = Mock(), Mock(); start = timezone.now()
        with patch("socket.create_connection", side_effect=AssertionError("No actual egress")):
            result = self.observe(fetcher, before_request=before, before_send=send)
        info = result.redirect_observation; stamp = datetime.fromisoformat(info["observed_at"])
        self.assertEqual(info["method_version"], "passive-http-redirect-response-v1")
        self.assertEqual(info["coverage"], "one_original_first_http_response_only")
        self.assertIn("plaintext_http", info["interpretation"])
        self.assertTrue(start <= stamp <= timezone.now()); self.assertEqual(stamp.tzinfo, UTC)
        self.assertEqual(stamp.isoformat(timespec="microseconds"), info["observed_at"])
        self.assertEqual((info["response_location"]["response_status"], info["response_location"]["same_origin"],
            info["response_location"]["same_hostname_default_https"]), (301, False, True))
        self.assertEqual((result.url, result.status, result.headers, result.body, result.redirects), (self.URL, 301, {}, b"", ()))
        self.assertIsNone(result.header_observation); self.assertIsNone(result.resource_observation); self.assertIsNone(result.observed_at)
        for raw in ("private", "secret", "example.com", "digest", "cookies", "headers"): self.assertNotIn(raw, json.dumps(info))
        factory.assert_called_once(); resolver.assert_called_once(); self.assertEqual(resolver.call_args.args[:2], ("example.com", 80))
        self.assertEqual(factory.call_args.args[:4], ("http", "93.184.216.34", "example.com", 80))
        self.assertEqual((before.call_count, send.call_count), (2, 2))
        connection.request.assert_called_once(); self.assertEqual(connection.request.call_args.args, ("GET", "/public"))
        self.assertEqual(connection.request.call_args.kwargs["headers"]["Host"], "example.com")
        response.read.assert_not_called(); connection.close.assert_called_once(); self.assertTrue(response.closed)

    def test_original_cardinality_relative_scheme_nonredirect_unknown_and_unsafe_target_metadata_is_not_followed(self):
        for status in (200, 201, 301, 302, 303, 304, 307, 308, 404, 599):
            for fields, state, scheme, same, counterpart in ((b"", "absent", None, None, None),
                (b"Location: \t\r\n", "present_empty", None, None, None),
                (b"Location: /one\r\nLocation: /two\r\n", "multiple_fields", None, None, None),
                (b"Location: https://[::1\r\n", "single_unclassified", None, None, None),
                (b"Location: /relative\r\n", "single_classified", "http", True, False),
                (b"Location: https://example.com/\r\n", "single_classified", "https", False, True),
                (b"Location: http://169.254.169.254/\r\n", "single_classified", "http", False, False)):
                fetcher, connection, response, factory, resolver = self.transport(f"HTTP/1.1 {status} Example\r\n".encode() + fields + b"\r\n")
                info = self.observe(fetcher).redirect_observation["response_location"]
                self.assertEqual((info["location_state"], info["target_scheme"], info["same_origin"], info["same_hostname_default_https"]), (state, scheme, same, counterpart))
                self.assertEqual(info["redirect_status"], status in {301, 302, 303, 307, 308})
                resolver.assert_called_once(); factory.assert_called_once(); response.read.assert_not_called(); connection.request.assert_called_once()

    def test_strict_http_syntax_mandatory_callbacks_and_mode_unions_deny_before_dns_and_old_modes_keep_http_denial(self):
        for options in ({"url": "https://example.com/public"}, {"url": "http://example.com"}, {"url": "http://example.com:80/public"},
            {"url": "http://example.com:8080/public"}, {"url": self.URL + "?"}, {"url": self.URL + "#"},
            {"url": "http://user:secret@example.com/public"}, {"url": self.URL + "/" + "x" * 1024},
            {"request_headers": {}}, {"before_request": None}, {"before_send": None}, {"before_request": True},
            {"observe_http_redirects": 1}, {"observe_headers": True}, {"observe_resources": True}, {"observe_redirects": True},
            {"static_document_type": "text/html"}):
            fetcher, connection, response, factory, resolver = self.transport()
            with self.subTest(options=options), self.assertRaises(FetchDenied): self.observe(fetcher, **options)
            resolver.assert_not_called(); factory.assert_not_called()
        for mode in ("observe_headers", "observe_resources", "observe_redirects"):
            fetcher, connection, response, factory, resolver = self.transport()
            with self.assertRaises(FetchDenied): fetcher.fetch(self.URL, **{mode: True}, before_request=Mock(), before_send=Mock())
            resolver.assert_not_called(); factory.assert_not_called()

    def test_current_source_loss_at_every_transport_boundary_never_sends_or_delivers_after_loss(self):
        for boundary in ("before_dns", "after_dns", "connected", "completion"):
            fetcher, connection, response, factory, resolver = self.transport(b"HTTP/1.1 301 Moved\r\nLocation: https://example.com/\r\n\r\n")
            before = Mock(side_effect=PermissionDenied if boundary == "before_dns" else [None, PermissionDenied] if boundary == "completion" else None)
            send = Mock(side_effect=PermissionDenied if boundary == "after_dns" else [None, PermissionDenied] if boundary == "connected" else None)
            with self.assertRaises(PermissionDenied): self.observe(fetcher, before_request=before, before_send=send)
            if boundary != "completion": connection.request.assert_not_called()
            if boundary == "before_dns": resolver.assert_not_called()
            if boundary in {"before_dns", "after_dns"}: factory.assert_not_called()
            else: connection.close.assert_called_once()
            response.read.assert_not_called()

    def test_slow_guards_dns_connected_completion_and_network_failure_keep_one_deadline_cleanup_no_retry(self):
        for boundary in ("before_dns", "after_dns", "connected", "completion"):
            clock = Mock(return_value=0); fetcher, connection, response, factory, resolver = self.transport(clock=clock)
            calls = 0
            def expire(_url):
                nonlocal calls
                calls += 1
                if calls == (1 if boundary in {"before_dns", "after_dns"} else 2): clock.return_value = 11
            before = expire if boundary in {"before_dns", "completion"} else Mock()
            send = expire if boundary in {"after_dns", "connected"} else Mock()
            with self.assertRaises(FetchLimitExceeded): self.observe(fetcher, before_request=before, before_send=send)
            if boundary != "completion": connection.request.assert_not_called()
            if boundary in {"before_dns", "after_dns"}: factory.assert_not_called()
            else: connection.close.assert_called_once()
            response.read.assert_not_called()
        fetcher, connection, response, factory, resolver = self.transport()
        connection.connect.side_effect = OSError("private")
        with self.assertRaisesRegex(FetchError, "^network_error$"): self.observe(fetcher)
        connection.request.assert_not_called(); factory.assert_called_once(); connection.close.assert_called_once()
        fetcher, connection, response, factory, resolver = self.transport(resolver=Mock(return_value=["93.184.216.34", "127.0.0.1"]))
        with self.assertRaises(FetchDenied): self.observe(fetcher)
        factory.assert_not_called()

    def test_real_pinned_http_connection_uses_selected_public_tcp_address_and_original_deadline_without_tls(self):
        raw = Mock(); clock = Mock(return_value=0)
        connection = _PinnedHTTPConnection("93.184.216.34", 80, deadline=10, clock=clock)
        with patch("socket.create_connection", return_value=raw) as connect, patch("ssl.create_default_context", side_effect=AssertionError("No TLS")):
            connection.connect()
            self.assertEqual(connect.call_args.args[:2], (("93.184.216.34", 80), 10))
            clock.return_value = 11
            with self.assertRaises(FetchLimitExceeded): connection.sock.sendall(b"GET / HTTP/1.1\r\n\r\n")
            raw.sendall.assert_not_called()
        connection.close(); raw.close.assert_called_once()

    def test_original_defects_status_and_header_bounds_deny_without_raw_disclosure_or_body_read(self):
        for wire in (b"HTTP/1.1 301 Moved\r\nmalformed header\r\n\r\n", b"HTTP/1.1 301 Moved\r\nX: private\x00\r\n\r\n",
            b"HTTP/1.1 600 Unknown\r\n\r\n", b"HTTP/1.1 301 Moved\r\nLocation: " + b"x" * 8193 + b"\r\n\r\n"):
            fetcher, connection, response, factory, resolver = self.transport(wire)
            with self.assertRaises(FetchError) as raised: self.observe(fetcher)
            self.assertNotIn("private", str(raised.exception)); connection.close.assert_called_once(); response.read.assert_not_called()
        fetcher, connection, response, factory, resolver = self.transport()
        response.getheaders = Mock(return_value=[("X", "private")] * 101)
        with self.assertRaises(FetchError): self.observe(fetcher)
        response.read.assert_not_called(); connection.close.assert_called_once()

    def test_actual_http_metadata_cannot_be_promoted_to_original_https_private_evidence_even_with_relabelled_url(self):
        from .passive_redirect_evidence import minimized_redirect_evidence
        from .test_passive_redirect_evidence import PassiveRedirectEvidenceTests
        fetcher, *_ = self.transport(b"HTTP/1.1 200 OK\r\nLocation: /relative\r\n\r\n")
        response = self.observe(fetcher)
        binding = PassiveRedirectEvidenceTests.BINDING
        for candidate in (response, replace(response, url=binding["url"])):
            with self.assertRaises(ValidationError): minimized_redirect_evidence(candidate, binding=binding)


class GenuinePassiveHTTPRedirectTransportTests(DatabaseTestCase):
    setUp = source_fixtures.PassiveHTTPRedirectSourceTests.setUp
    verified = source_fixtures.PassiveHTTPRedirectSourceTests.verified

    def test_genuine_configured_http_verifier_source_native_response_and_connected_completion_full_source_drift(self):
        self.verified(); data = {"url": self.project.canonical_origin + "/public", "observations": ["http_response_location"], "collection_permission": True}
        original = source.passive_http_redirect_source(project=self.project, actor=self.owner, data=data)
        response_case = PassiveHTTPRedirectTransportTests(); self.addCleanup(response_case.doCleanups)
        def current(url):
            if url != data["url"] or source.passive_http_redirect_source(project=self.project, actor=self.owner, data=data) != original: raise PermissionDenied
        for boundary in (None, "connected", "completion"):
            with self.subTest(boundary=boundary):
                from django.db import transaction
                with transaction.atomic():
                    _fetcher, connection, response, _factory, _resolver = response_case.transport(b"HTTP/1.1 301 Moved\r\nLocation: https://security.example.com/private\r\n\r\n")
                    fetcher = SafeFetcher(CrawlScope(frozenset({"security.example.com"})), resolver=lambda *args: ["93.184.216.34"], connection_factory=lambda *args: connection)
                    def revoke():
                        ProjectOriginVerification.objects.filter(pk=original["verification_id"]).update(challenge_digest="a" * 64)
                    if boundary == "connected": connection.connect.side_effect = revoke
                    if boundary == "completion": response.getheaders = Mock(side_effect=lambda: (revoke(), [])[1])
                    with patch("socket.create_connection", side_effect=AssertionError("No actual egress")):
                        if boundary:
                            with self.assertRaises((PermissionDenied, ValidationError)): fetcher.fetch(data["url"], observe_http_redirects=True, before_request=current, before_send=current)
                        else:
                            result = fetcher.fetch(data["url"], observe_http_redirects=True, before_request=current, before_send=current)
                            self.assertTrue(result.redirect_observation["response_location"]["same_hostname_default_https"])
                            self.assertGreaterEqual(datetime.fromisoformat(result.redirect_observation["observed_at"]), datetime.fromisoformat(original["verified_at"]))
                    if boundary == "connected": connection.request.assert_not_called()
                    else: connection.request.assert_called_once()
                    response.read.assert_not_called(); connection.close.assert_called_once()
                    transaction.set_rollback(True)
