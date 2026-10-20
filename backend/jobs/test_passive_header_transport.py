import http.client
import io
import json
from unittest import TestCase
from unittest.mock import Mock, patch

from django.core.exceptions import PermissionDenied

from .crawling import CrawlScope, FetchDenied, FetchError, FetchLimitExceeded, SafeFetcher


class PassiveHeaderTransportTests(TestCase):
    URL = "https://example.com/public"

    def transport(self, wire=b"HTTP/1.1 200 OK\r\n\r\n", *, resolver=None, clock=None):
        # Real stdlib parsing preserves duplicate fields and its malformed-header defects.
        sock = Mock()
        sock.makefile.return_value = io.BytesIO(wire)
        response = http.client.HTTPResponse(sock)
        response.begin()
        self.addCleanup(response.close)
        response.read = Mock(side_effect=AssertionError("Header observation must not read the body"))
        connection = Mock()
        connection.getresponse.return_value = response
        factory = Mock(return_value=connection)
        resolver = resolver or Mock(return_value=["93.184.216.34"])
        options = {"clock": clock} if clock else {}
        fetcher = SafeFetcher(CrawlScope(frozenset({"example.com", "www.example.com"})),
            resolver=resolver, connection_factory=factory, **options)
        return fetcher, connection, response, factory, resolver

    def observe(self, fetcher, **kwargs):
        return fetcher.fetch(self.URL, observe_headers=True, before_request=Mock(), before_send=Mock(), **kwargs)

    def test_original_duplicate_fields_are_minimized_without_raw_metadata_or_body(self):
        wire = (b"HTTP/1.1 200 OK\r\nSet-Cookie: session=private; Secure; HttpOnly; SameSite=Lax\r\n"
            b"Set-Cookie: other=secret; Expires=Wed, 09 Jun 2027 10:18:14 GMT\r\n"
            b"Content-Security-Policy: script-src 'nonce-private'\r\n"
            b"Content-Security-Policy: default-src https://private.example\r\n"
            b"Server: private-version\r\nContent-Length: 9999999999\r\nContent-Encoding: invalid\r\n\r\nprivate-body")
        fetcher, connection, response, factory, resolver = self.transport(wire)
        before, send = Mock(), Mock()
        with patch("jobs.crawling.socket.create_connection", side_effect=AssertionError("No real egress")):
            result = fetcher.fetch(self.URL, observe_headers=True, before_request=before, before_send=send)
        self.assertEqual(result.header_observation["cookies"], {"observed_fields": 2, "parsed_fields": 2,
            "unclassified_fields": 0, "without_secure": 1, "without_httponly": 1, "without_recognized_samesite": 1})
        self.assertEqual(result.header_observation["headers"]["content-security-policy"], "multiple_fields")
        self.assertEqual((result.url, result.status, result.headers, result.body, result.redirects), (self.URL, 200, {}, b"", ()))
        self.assertNotIn("private", repr(result))
        self.assertNotIn("secret", json.dumps(result.header_observation))
        self.assertEqual(before.call_count, 2)
        self.assertEqual(send.call_count, 2)
        factory.assert_called_once()
        self.assertEqual(factory.call_args.args[:4], ("https", "93.184.216.34", "example.com", 443))
        self.assertEqual(connection.request.call_args.args, ("GET", "/public"))
        self.assertEqual(set(connection.request.call_args.kwargs["headers"]),
            {"Host", "User-Agent", "Accept", "Accept-Encoding", "Connection"})
        response.read.assert_not_called()
        self.assertTrue(response.closed)
        connection.close.assert_called_once()

    def test_first_redirect_status_is_observed_without_following_or_copying_location(self):
        for location in ("https://www.example.com/", "http://example.com/", "http://169.254.169.254/", "https://[::1"):
            with self.subTest(location=location):
                fetcher, connection, response, factory, resolver = self.transport(
                    b"HTTP/1.1 302 Found\r\nLocation: " + location.encode() + b"\r\n\r\n")
                result = self.observe(fetcher)
                self.assertEqual(result.status, 302)
                self.assertEqual(result.url, self.URL)
                self.assertNotIn(location, repr(result))
                factory.assert_called_once()
                resolver.assert_called_once()
                response.read.assert_not_called()
                connection.close.assert_called_once()

    def test_inputs_require_canonical_https_and_both_current_callbacks_before_dns(self):
        for options in ({"url": "http://example.com/public"}, {"url": "https://example.com"},
            {"url": self.URL + "?"}, {"url": self.URL + "#"}, {"url": "https://example.com:443/public"},
            {"url": "https://user:secret@example.com/public"}, {"request_headers": {}},
            {"before_request": None}, {"before_send": None}, {"observe_headers": 1}):
            with self.subTest(options=options):
                fetcher, connection, response, factory, resolver = self.transport()
                arguments = {"url": self.URL, "observe_headers": True, "before_request": Mock(), "before_send": Mock(), **options}
                with self.assertRaises(FetchDenied): fetcher.fetch(**arguments)
                resolver.assert_not_called()
                factory.assert_not_called()

    def test_current_authority_loss_at_every_boundary_denies_and_closes(self):
        for boundary in ("before_dns", "after_dns", "connected", "completion"):
            with self.subTest(boundary=boundary):
                fetcher, connection, response, factory, resolver = self.transport()
                before = Mock(side_effect=PermissionDenied if boundary == "before_dns" else
                    [None, PermissionDenied] if boundary == "completion" else None)
                send = Mock(side_effect=PermissionDenied if boundary == "after_dns" else
                    [None, PermissionDenied] if boundary == "connected" else None)
                with self.assertRaises(PermissionDenied):
                    fetcher.fetch(self.URL, observe_headers=True, before_request=before, before_send=send)
                if boundary == "before_dns": resolver.assert_not_called()
                if boundary in {"before_dns", "after_dns"}: factory.assert_not_called()
                else:
                    connection.close.assert_called_once()
                    connection.connect.assert_called_once()
                if boundary != "completion": connection.request.assert_not_called()
                response.read.assert_not_called()

    def test_malformed_oversized_or_defective_headers_fail_categorically(self):
        for fields in (b"Bad Name: secret\r\n", b"Server: secret\x00\r\n", b"Server: " + b"s" * 8193 + b"\r\n",
            b"Server: " + b"s" * 8192 + b"\r\n" + (b"Other: " + b"s" * 8192 + b"\r\n") * 3,
            b"Server: secret\r\nbroken-header\r\n"):
            with self.subTest(fields_length=len(fields)):
                fetcher, connection, response, factory, resolver = self.transport(b"HTTP/1.1 200 OK\r\n" + fields + b"\r\n")
                with self.assertRaisesRegex(FetchError, "^response_headers_unavailable$"):
                    self.observe(fetcher)
                response.read.assert_not_called()
                connection.close.assert_called_once()
        fetcher, connection, response, *_ = self.transport(b"HTTP/1.1 101 Switching Protocols\r\n\r\n")
        with self.assertRaisesRegex(FetchError, "^response_headers_unavailable$"): self.observe(fetcher)
        connection.close.assert_called_once()

    def test_deadline_and_nonpublic_dns_never_produce_observation(self):
        fetcher, connection, response, factory, resolver = self.transport(resolver=Mock(return_value=["127.0.0.1"]))
        with self.assertRaisesRegex(FetchDenied, "non_public_address"): self.observe(fetcher)
        factory.assert_not_called()
        now = [0]
        fetcher, connection, response, *_ = self.transport(clock=lambda: now[0])
        original = response.getheaders
        def slow_headers():
            now[0] = 11
            return original()
        response.getheaders = slow_headers
        with self.assertRaisesRegex(FetchLimitExceeded, "timeout"): self.observe(fetcher)
        connection.close.assert_called_once()
        response.read.assert_not_called()
