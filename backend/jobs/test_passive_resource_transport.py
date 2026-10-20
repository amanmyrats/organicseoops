import gzip
import http.client
import io
import json
import ssl
from datetime import UTC, datetime
from unittest import TestCase
from unittest.mock import Mock, patch

from django.core.exceptions import PermissionDenied
from django.test import TestCase as DatabaseTestCase
from django.utils import timezone

from .crawling import CrawlScope, FetchDenied, FetchError, FetchLimitExceeded, SafeFetcher
from .passive_resources import MAX_BODY_BYTES
from . import passive_resource_source as source
from . import test_passive_header_source as source_fixtures


class _SplitBody(io.BytesIO):
    def read1(self, amount=-1):
        return super().read1(min(amount, 7))


class PassiveResourceTransportTests(TestCase):
    URL = "https://example.com/public"
    HTML = b'<img src="http://private.invalid/p?secret=value"><script src="https://private.invalid/a"></script>'

    def transport(self, body=None, *, fields=None, status="200 OK", clock=None, max_bytes=2 * MAX_BODY_BYTES):
        body = self.HTML if body is None else body
        fields = fields if fields is not None else f"Content-Length: {len(body)}\r\nContent-Type: text/html; charset=utf-8\r\n".encode()
        sock = Mock()
        sock.makefile.return_value = _SplitBody(b"HTTP/1.1 " + status.encode() + b"\r\n" + fields + b"\r\n" + body)
        response = http.client.HTTPResponse(sock, method="GET")
        response.begin()
        self.addCleanup(response.close)
        original = response.read1
        response.read1 = Mock(wraps=original)
        response.read = Mock(side_effect=AssertionError("Use bounded incremental reads"))
        connection = Mock()
        connection.getresponse.return_value = response
        factory, resolver = Mock(return_value=connection), Mock(return_value=["93.184.216.34"])
        options = {"clock": clock} if clock else {}
        fetcher = SafeFetcher(CrawlScope(frozenset({"example.com", "www.example.com"})), max_bytes=max_bytes,
            resolver=resolver, connection_factory=factory, **options)
        return fetcher, connection, response, factory, resolver

    def observe(self, fetcher, **changes):
        return fetcher.fetch(**{"url": self.URL, "observe_resources": True,
            "before_request": Mock(), "before_send": Mock(), **changes})

    def test_original_split_length_identity_gzip_privacy_and_exact_capture_date(self):
        for encoding in ("identity", "gzip"):
            body = self.HTML if encoding == "identity" else gzip.compress(self.HTML)
            fields = (f"Content-Length: {len(body)}\r\nContent-Type: TEXT/HTML ; Charset=\"UTF-8\"\r\n"
                f"Content-Encoding: {encoding}\r\nSet-Cookie: secret=private\r\nETag: private-digest\r\n").encode()
            with self.subTest(encoding=encoding):
                fetcher, connection, response, factory, resolver = self.transport(body, fields=fields)
                before, send = Mock(), Mock()
                start = datetime.now(UTC)
                with patch("jobs.crawling.socket.create_connection", side_effect=AssertionError("No real egress")):
                    result = self.observe(fetcher, before_request=before, before_send=send)
                self.assertEqual((result.url, result.status, result.headers, result.body, result.redirects, result.header_observation),
                    (self.URL, 200, {}, b"", (), None))
                observation = result.resource_observation
                stamp = datetime.fromisoformat(observation["observed_at"])
                self.assertLessEqual(start, stamp); self.assertLessEqual(stamp, datetime.now(UTC))
                self.assertEqual(stamp.isoformat(timespec="microseconds"), observation["observed_at"])
                self.assertEqual(observation["resource_references"]["counts"],
                    {"inspected_attributes": 2, "http_absolute": 1, "https_absolute": 1, "unclassified": 0})
                for private in ("private", "secret", "value", "digest", "invalid", "src="):
                    self.assertNotIn(private, json.dumps(observation))
                self.assertEqual(before.call_count, 2); self.assertEqual(send.call_count, 2)
                factory.assert_called_once(); resolver.assert_called_once()
                self.assertEqual(factory.call_args.args[:4], ("https", "93.184.216.34", "example.com", 443))
                self.assertEqual(connection.request.call_args.args, ("GET", "/public"))
                self.assertEqual(connection.request.call_args.kwargs["headers"], {"Host": "example.com",
                    "User-Agent": "OrganicSEOOpsBot/1.0", "Accept": "text/html", "Accept-Encoding": "gzip", "Connection": "close"})
                self.assertGreater(response.read1.call_count, 2)
                self.assertTrue(response.closed); connection.close.assert_called_once()

    def test_duplicate_ambiguous_unsupported_metadata_never_reads_body_or_follows(self):
        base = f"Content-Length: {len(self.HTML)}\r\nContent-Type: text/html; charset=utf-8\r\n".encode()
        cases = [base + extra for extra in (b"Content-Length: 0\r\n", b"Content-Length: " + str(len(self.HTML)).encode() + b"\r\n",
            b"Content-Type: text/html; charset=utf-8\r\n", b"Content-Encoding: gzip\r\nContent-Encoding: gzip\r\n",
            b"Transfer-Encoding: chunked\r\n", b"Transfer-Encoding: identity\r\n", b"Trailer: other\r\n",
            b"Content-Range: bytes 0-1/99\r\n", b"Bad Name: secret\r\n", b"Server: secret\x00\r\n",
            b"Server: secret\r\nbroken\r\n", b"Server: " + b"s" * 8193 + b"\r\n")]
        cases += [b"Content-Length: " + value + b"\r\nContent-Type: text/html; charset=utf-8\r\n"
            for value in (b"-1", b"+1", b"1, 1", b"12345678901", b"", b"1x")]
        cases += [b"Content-Length: 1\r\nContent-Type: " + value + b"\r\n" for value in
            (b"text/html", b"text/plain; charset=utf-8", b"text/html; charset=latin-1", b"text/html; charset=utf-8; charset=utf-8")]
        cases += [b"Content-Type: text/html; charset=utf-8\r\n", base + b"Content-Encoding: br\r\n"]
        for fields in cases:
            with self.subTest(fields=fields[:100]):
                fetcher, connection, response, factory, _ = self.transport(fields=fields)
                with self.assertRaises(FetchError): self.observe(fetcher)
                response.read1.assert_not_called(); factory.assert_called_once(); connection.close.assert_called_once()
        for status in ("302 Found", "304 Not Modified", "206 Partial Content", "204 No Content", "403 Forbidden", "101 Upgrade"):
            with self.subTest(status=status):
                fetcher, connection, response, factory, resolver = self.transport(status=status,
                    fields=base + b"Location: http://169.254.169.254/secret\r\n")
                with self.assertRaises(FetchError): self.observe(fetcher)
                response.read1.assert_not_called(); factory.assert_called_once(); resolver.assert_called_once()
                connection.close.assert_called_once()

    def test_silent_length_truncation_gzip_incompleteness_corruption_and_extra_members_fail(self):
        compressed = gzip.compress(self.HTML)
        cases = [(self.HTML, len(self.HTML) + 1, "identity"), (compressed, len(compressed) + 1, "gzip"),
            (compressed[:-1], len(compressed) - 1, "gzip"), (compressed + b"tail", len(compressed) + 4, "gzip"),
            (compressed + gzip.compress(b"<img src='http://other.invalid/'>"),
                len(compressed) + len(gzip.compress(b"<img src='http://other.invalid/'>")), "gzip"),
            (compressed[:-8] + b"broken!!", len(compressed), "gzip")]
        for body, length, encoding in cases:
            with self.subTest(length=length, encoding=encoding):
                fetcher, connection, response, *_ = self.transport(body,
                    fields=f"Content-Length: {length}\r\nContent-Type: text/html; charset=utf-8\r\nContent-Encoding: {encoding}\r\n".encode())
                with self.assertRaises(FetchError): self.observe(fetcher)
                self.assertTrue(response.closed); connection.close.assert_called_once()

    def test_wire_decoded_ceiling_exact_boundary_utf8_and_lexical_null_semantics(self):
        for body in (b" " * MAX_BODY_BYTES, b"", b"<img src='http://example.invalid/'>"):
            fetcher, _, _, *_ = self.transport(body)
            self.assertEqual(self.observe(fetcher).resource_observation["resource_references"]["state"], "observed")
        body = gzip.compress(b" " * MAX_BODY_BYTES)
        fetcher, _, _, *_ = self.transport(body, fields=f"Content-Length: {len(body)}\r\nContent-Type: text/html; charset=utf-8\r\nContent-Encoding: gzip\r\n".encode())
        self.assertEqual(self.observe(fetcher).resource_observation["resource_references"]["counts"]["inspected_attributes"], 0)
        for body, encoding, max_bytes in ((b"x" * (MAX_BODY_BYTES + 1), "identity", 2 * MAX_BODY_BYTES),
            (gzip.compress(b"x" * (MAX_BODY_BYTES + 1)), "gzip", 2 * MAX_BODY_BYTES), (self.HTML, "identity", 16)):
            fetcher, connection, response, *_ = self.transport(body, max_bytes=max_bytes,
                fields=f"Content-Length: {len(body)}\r\nContent-Type: text/html; charset=utf-8\r\nContent-Encoding: {encoding}\r\n".encode())
            with self.assertRaises(FetchLimitExceeded): self.observe(fetcher)
            connection.close.assert_called_once()
        fetcher, _, _, *_ = self.transport(b"\xff<img src='http://example.invalid/'>")
        with self.assertRaisesRegex(FetchError, "resource_body_unavailable"): self.observe(fetcher)
        fetcher, _, _, *_ = self.transport(b"<img src='http://example.invalid/' src='other'>")
        result = self.observe(fetcher).resource_observation["resource_references"]
        self.assertEqual(result["state"], "unavailable"); self.assertTrue(all(value is None for value in result["counts"].values()))

    def test_exact_inputs_independent_mode_and_all_current_gates(self):
        for changes in ({"url": "http://example.com/public"}, {"url": "https://example.com"},
            {"url": self.URL + "?"}, {"url": self.URL + "#"}, {"url": "https://example.com:443/public"},
            {"request_headers": {}}, {"observe_resources": 1}, {"observe_headers": True},
            {"before_request": None}, {"before_send": None}):
            fetcher, _, _, factory, resolver = self.transport()
            with self.subTest(changes=changes), self.assertRaises(FetchDenied): self.observe(fetcher, **changes)
            resolver.assert_not_called(); factory.assert_not_called()
        for boundary in ("before_dns", "after_dns", "connected", "completion"):
            fetcher, connection, _, factory, resolver = self.transport()
            before = Mock(side_effect=PermissionDenied if boundary == "before_dns" else [None, PermissionDenied] if boundary == "completion" else None)
            send = Mock(side_effect=PermissionDenied if boundary == "after_dns" else [None, PermissionDenied] if boundary == "connected" else None)
            with self.subTest(boundary=boundary), self.assertRaises(PermissionDenied):
                self.observe(fetcher, before_request=before, before_send=send)
            if boundary == "before_dns": resolver.assert_not_called()
            if boundary in {"before_dns", "after_dns"}: factory.assert_not_called()
            else: connection.close.assert_called_once()
            if boundary != "completion": connection.request.assert_not_called()

    def test_deadline_nonpublic_dns_and_default_tls_failure_do_not_retry(self):
        now = [0]
        fetcher, connection, response, *_ = self.transport(clock=lambda: now[0])
        original = response.read1
        def slow_read(amount):
            chunk = original(amount)
            now[0] += 3
            return chunk
        response.read1 = slow_read
        with self.assertRaisesRegex(FetchLimitExceeded, "timeout"): self.observe(fetcher)
        connection.close.assert_called_once()
        for boundary in ("connected", "completion"):
            now = [0]
            fetcher, connection, _, *_ = self.transport(clock=lambda: now[0])
            count = [0]
            def expires(_url):
                count[0] += 1
                if count[0] == 2: now[0] = 11
            options = {"before_send" if boundary == "connected" else "before_request": expires}
            with self.subTest(boundary=boundary), self.assertRaisesRegex(FetchLimitExceeded, "timeout"):
                self.observe(fetcher, **options)
            if boundary == "connected": connection.request.assert_not_called()
            connection.close.assert_called_once()
        fetcher, _, _, factory, resolver = self.transport()
        resolver.return_value = ["93.184.216.34", "127.0.0.1"]
        with self.assertRaises(FetchDenied): self.observe(fetcher)
        factory.assert_not_called()
        fetcher, connection, _, factory, resolver = self.transport()
        connection.connect.side_effect = ssl.SSLCertVerificationError("invalid certificate")
        with self.assertRaises(FetchError): self.observe(fetcher)
        factory.assert_called_once(); resolver.assert_called_once(); connection.request.assert_not_called()
        connection.close.assert_called_once()

    def test_general_fetch_cannot_claim_resource_completeness(self):
        fetcher, _, _, *_ = self.transport(fields=b"Content-Length: 999\r\nContent-Type: text/html; charset=utf-8\r\n")
        result = fetcher.fetch(self.URL)
        self.assertEqual(result.body, self.HTML)
        self.assertIsNone(result.resource_observation)


class OriginalResourceTransportSourceTests(DatabaseTestCase):
    setUp = source_fixtures.PassiveHeaderSourceTests.setUp
    verified = source_fixtures.PassiveHeaderSourceTests.verified
    transport = PassiveResourceTransportTests.transport
    HTML = PassiveResourceTransportTests.HTML

    def test_original_verified_independent_binding_then_complete_capture_and_late_revocation(self):
        row = self.verified()
        data = {"url": self.project.canonical_origin + "/public", "observations": ["static_resource_references"],
            "collection_permission": True}
        binding = source.passive_resource_source(project=self.project, actor=self.owner, data=data)
        def current(url):
            self.assertEqual(url, binding["url"])
            if source.passive_resource_source(project=self.project, actor=self.owner, data=data) != binding:
                raise PermissionDenied
        fetcher, connection, response, *_ = self.transport()
        fetcher.scope = CrawlScope(frozenset({self.project.canonical_origin.split("//")[1]}))
        result = fetcher.fetch(data["url"], observe_resources=True, before_request=current, before_send=current)
        self.assertGreaterEqual(datetime.fromisoformat(result.resource_observation["observed_at"]), row.verified_at)
        self.assertEqual(result.resource_observation["resource_references"]["counts"]["http_absolute"], 1)
        fetcher, connection, response, *_ = self.transport()
        fetcher.scope = CrawlScope(frozenset({self.project.canonical_origin.split("//")[1]}))
        original = response.read1
        def revoked(amount):
            row.__class__.objects.filter(pk=row.pk).update(state="revoked", revoked_at=timezone.now())
            return original(amount)
        response.read1 = revoked
        with self.assertRaises(PermissionDenied):
            fetcher.fetch(data["url"], observe_resources=True, before_request=current, before_send=current)
        self.assertTrue(response.closed); connection.close.assert_called_once()
