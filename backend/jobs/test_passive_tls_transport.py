import json
import ssl
from unittest import TestCase
from unittest.mock import Mock, call, patch

from django.core.exceptions import PermissionDenied

from .crawling import CrawlScope, FetchDenied, FetchError, FetchLimitExceeded, SafeFetcher, _PinnedHTTPSConnection


class PassiveTLSTransportTests(TestCase):
    ORIGIN = "https://example.com"

    def transport(self, *, clock=None, resolver=None):
        sock = Mock()
        sock.getpeercert.return_value = {"notBefore": "Jan  1 00:00:00 2024 GMT", "notAfter": "Jan  1 00:00:00 2030 GMT",
            "subject": "private", "issuer": "private", "subjectAltName": (("DNS", "private.example.invalid"),),
            "OCSP": ("http://169.254.169.254/private",)}
        sock.version.return_value = "TLSv1.3"
        sock.cipher.return_value = ("TLS_AES_256_GCM_SHA384", "TLSv1.2", 256)
        connection = Mock(sock=sock)
        factory = Mock(return_value=connection)
        resolver = resolver or Mock(return_value=["93.184.216.34"])
        options = {"clock": clock} if clock else {}
        fetcher = SafeFetcher(CrawlScope(frozenset({"example.com"})), resolver=resolver, connection_factory=factory, **options)
        return fetcher, connection, sock, factory, resolver

    def observe(self, fetcher, **changes):
        return fetcher.observe_tls(**{"origin": self.ORIGIN, "before_request": Mock(), "before_send": Mock(), **changes})

    def test_one_original_handshake_metadata_no_http_raw_identity_digest_or_probe(self):
        fetcher, connection, sock, factory, resolver = self.transport()
        before, connected = Mock(), Mock()
        with patch("socket.create_connection", side_effect=AssertionError("real egress")), \
            patch("hashlib.sha256", side_effect=AssertionError("raw digest")):
            result = self.observe(fetcher, before_request=before, before_send=connected)
        self.assertEqual(result["origin"], self.ORIGIN)
        self.assertEqual(result["negotiated_tls"], {"version": "TLSv1.3", "cipher": {"name": "TLS_AES_256_GCM_SHA384", "secret_bits": 256}})
        self.assertEqual(result["certificate_dates"]["state"], "observed")
        self.assertEqual(result["observed_at"], result["certificate_dates"]["observed_at"])
        self.assertNotIn("private", json.dumps(result))
        self.assertIn("not_all_supported_configuration_revocation", result["interpretation"])
        self.assertEqual(before.call_args_list, [call(self.ORIGIN), call(self.ORIGIN)])
        self.assertEqual(connected.call_args_list, [call(self.ORIGIN), call(self.ORIGIN)])
        factory.assert_called_once(); resolver.assert_called_once()
        self.assertEqual(factory.call_args.args[:4], ("https", "93.184.216.34", "example.com", 443))
        connection.connect.assert_called_once(); connection.close.assert_called_once()
        connection.request.assert_not_called(); connection.getresponse.assert_not_called()
        sock.getpeercert.assert_called_once_with(); sock.version.assert_called_once_with(); sock.cipher.assert_called_once_with()
        sock.sendall.assert_not_called(); sock.recv_into.assert_not_called(); sock.get_verified_chain.assert_not_called()

    def test_exact_https_origin_and_both_callbacks_are_required_before_dns(self):
        for changes in ({"origin": "http://example.com"}, {"origin": self.ORIGIN + "/"}, {"origin": self.ORIGIN + "/private"},
            {"origin": self.ORIGIN + ":443"}, {"origin": self.ORIGIN + ":8443"}, {"origin": self.ORIGIN + "?"},
            {"origin": "https://user:private@example.com"}, {"origin": self.ORIGIN + "#private"}, {"origin": None},
            {"origin": "HTTPS://EXAMPLE.COM"}, {"origin": "https://outside.example"},
            {"before_request": None}, {"before_send": None}):
            with self.subTest(changes=changes):
                fetcher, connection, sock, factory, resolver = self.transport()
                with self.assertRaises(FetchDenied): self.observe(fetcher, **changes)
                resolver.assert_not_called(); factory.assert_not_called()

    def test_current_loss_before_dns_after_dns_connected_and_completion_denies(self):
        for boundary in ("before_dns", "after_dns", "connected", "completion"):
            fetcher, connection, sock, factory, resolver = self.transport()
            before = Mock(side_effect=PermissionDenied if boundary == "before_dns" else [None, PermissionDenied] if boundary == "completion" else None)
            connected = Mock(side_effect=PermissionDenied if boundary == "after_dns" else [None, PermissionDenied] if boundary == "connected" else None)
            with self.assertRaises(PermissionDenied): self.observe(fetcher, before_request=before, before_send=connected)
            if boundary == "before_dns": resolver.assert_not_called()
            if boundary in {"before_dns", "after_dns"}: factory.assert_not_called()
            else: connection.close.assert_called_once()
            if boundary != "completion": sock.getpeercert.assert_not_called()
            connection.request.assert_not_called()

    def test_unavailable_metadata_is_null_and_cipher_definition_does_not_invent_version(self):
        fetcher, connection, sock, *_ = self.transport()
        for certificate in (None, {}, {"notBefore": "invalid-private", "notAfter": "invalid-private"}):
            sock.getpeercert.return_value = certificate
            sock.version.return_value = "unknown-private"
            sock.cipher.return_value = ("valid-cipher", "TLSv1.3", 128)
            result = self.observe(fetcher)
            self.assertEqual(result["certificate_dates"]["state"], "unavailable")
            self.assertIsNone(result["certificate_dates"]["remaining_microseconds"])
            self.assertIsNone(result["negotiated_tls"]["version"])
            self.assertNotIn("private", json.dumps(result))
        for cipher in (None, [], ("x", 128), ("private\n", "TLSv1.3", 128), ("x" * 129, "TLSv1.3", 128),
            ("cipher", "TLSv1.3", True), ("cipher", "TLSv1.3", 0), ("cipher", "TLSv1.3", 513)):
            sock.cipher.return_value = cipher
            self.assertIsNone(self.observe(fetcher)["negotiated_tls"]["cipher"])

    def test_failed_handshake_or_metadata_is_categorical_without_retry_or_http(self):
        for method in ("connect", "getpeercert", "version", "cipher"):
            fetcher, connection, sock, factory, resolver = self.transport()
            target = connection if method == "connect" else sock
            getattr(target, method).side_effect = ssl.SSLCertVerificationError("private-certificate")
            with self.assertRaisesRegex(FetchError, "^tls_observation_failed$"): self.observe(fetcher)
            connection.close.assert_called_once(); factory.assert_called_once(); connection.request.assert_not_called()
            if method == "connect": sock.getpeercert.assert_not_called()

    def test_private_dns_and_monotonic_expiry_at_connected_metadata_and_completion_deny(self):
        fetcher, connection, sock, factory, resolver = self.transport(resolver=Mock(return_value=["93.184.216.34", "127.0.0.1"]))
        with self.assertRaisesRegex(FetchDenied, "non_public_address"): self.observe(fetcher)
        factory.assert_not_called()
        for boundary in ("connect", "metadata", "completion"):
            now = [0]
            fetcher, connection, sock, factory, resolver = self.transport(clock=lambda: now[0])
            late = lambda *args: now.__setitem__(0, 11)
            before = Mock(side_effect=[None, None])
            if boundary == "connect": connection.connect.side_effect = late
            elif boundary == "metadata": sock.cipher.side_effect = lambda: (late(), ("cipher", "TLSv1.3", 128))[1]
            else: before.side_effect = lambda *args: late() if sock.cipher.called else None
            with self.assertRaisesRegex(FetchLimitExceeded, "timeout"): self.observe(fetcher, before_request=before)
            connection.close.assert_called_once(); connection.request.assert_not_called()

    def test_actual_pinned_connection_retains_default_context_hostname_and_failure_cleanup(self):
        default = ssl.create_default_context()
        self.assertEqual(default.verify_mode, ssl.CERT_REQUIRED); self.assertTrue(default.check_hostname)
        for boundary in ("wrap", "handshake", "timeout", "success"):
            raw, wrapped, context = Mock(), Mock(), Mock()
            context.wrap_socket.return_value = wrapped
            now = [0]
            if boundary == "wrap": context.wrap_socket.side_effect = ssl.SSLError("private")
            if boundary == "handshake": wrapped.do_handshake.side_effect = ssl.SSLCertVerificationError("private")
            if boundary == "timeout": wrapped.do_handshake.side_effect = lambda: now.__setitem__(0, 11)
            with patch("jobs.crawling.ssl.create_default_context", return_value=context), \
                patch("jobs.crawling.socket.create_connection", return_value=raw) as tcp:
                connection = _PinnedHTTPSConnection("93.184.216.34", 443, server_hostname="example.com", deadline=10, clock=lambda: now[0])
                if boundary == "success":
                    connection.connect(); self.assertIs(connection.sock._sock, wrapped)
                else:
                    with self.assertRaises((ssl.SSLError, FetchLimitExceeded)): connection.connect()
                    self.assertIsNone(connection.sock)
            tcp.assert_called_once_with(("93.184.216.34", 443), 10, None)
            context.wrap_socket.assert_called_once_with(raw, server_hostname="example.com", do_handshake_on_connect=False)
            if boundary == "wrap": raw.close.assert_called_once(); wrapped.close.assert_not_called()
            elif boundary != "success": wrapped.close.assert_called_once()
            else: wrapped.close.assert_not_called(); connection.close()

    def test_actual_ready_nonblocking_handshake_still_obeys_total_deadline(self):
        raw, wrapped, context = Mock(), Mock(), Mock()
        context.wrap_socket.return_value = wrapped
        now = [0]
        def needs_io():
            now[0] += 1
            raise ssl.SSLWantReadError
        wrapped.do_handshake.side_effect = needs_io
        with patch("jobs.crawling.ssl.create_default_context", return_value=context), \
            patch("jobs.crawling.socket.create_connection", return_value=raw), \
            patch("jobs.crawling.select.select", return_value=([wrapped], [], [])):
            connection = _PinnedHTTPSConnection("93.184.216.34", 443, server_hostname="example.com", deadline=2, clock=lambda: now[0])
            with self.assertRaisesRegex(FetchLimitExceeded, "timeout"): connection.connect()
        self.assertEqual(wrapped.do_handshake.call_count, 2)
        wrapped.close.assert_called_once(); self.assertIsNone(connection.sock)
