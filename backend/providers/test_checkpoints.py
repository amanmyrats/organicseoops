import ssl
from unittest.mock import Mock

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import SimpleTestCase

from .adapters import ProviderRequestError, post_json
from .models import AIProvider
from .test_adapters import FakeHTTPResponse, GuardedConnection


class ProviderCheckpointTests(SimpleTestCase):
    def request(self, *, checkpoint, response=None, on_dns=None, on_connect=None, on_body=None, clock=None):
        self.events, self.connections = [], []
        response = response or FakeHTTPResponse(200, {"status": "completed"}, {"x-request-id": "req_safe"})
        original_read = response.read

        def read(amount):
            result = original_read(amount)
            if on_body:
                on_body()
            return result

        response.read = read

        def resolver(*_args):
            self.events.append(("dns",))
            if on_dns:
                on_dns()
            return ["8.8.8.8"]

        def factory(*args):
            connection = GuardedConnection(response, self.events, *args)
            connect = connection.connect

            def connected():
                connect()
                if on_connect:
                    on_connect()

            connection.connect = connected
            self.connections.append(connection)
            return connection

        return post_json(endpoint="https://api.openai.com/v1/responses", body=b'{"input":"private-source"}',
            secret="runtime-secret", timeout=10, egress_policy=AIProvider.EgressPolicy.OFFICIAL_OPENAI,
            checkpoint=checkpoint, resolver=resolver, connection_factory=factory,
            **({"clock": clock} if clock else {}))

    def test_current_checks_surround_dns_pinned_tls_send_and_body_without_arguments(self):
        def guard():
            self.events.append(("guard",))

        result = self.request(checkpoint=guard)
        self.assertEqual(result[:2], (200, "req_safe"))
        self.assertEqual([event[0] for event in self.events],
            ["guard", "dns", "guard", "connection", "connect", "guard", "request", "guard"])
        self.assertEqual(self.events[3][1:5], ("https", "8.8.8.8", "api.openai.com", 443))
        self.assertTrue(self.connections[0].closed)

    def test_lost_authority_before_dns_after_dns_connected_and_body_never_delivers_or_replays(self):
        for boundary in ("entry", "dns", "connected", "body"):
            for status in (200, 429):
                with self.subTest(boundary=boundary, status=status):
                    current = [boundary != "entry"]

                    def guard():
                        if not current[0]:
                            raise PermissionDenied

                    def revoke():
                        current[0] = False

                    options = {} if boundary == "entry" else {
                        "on_" + {"connected": "connect", "dns": "dns", "body": "body"}[boundary]: revoke}
                    with self.assertRaises(PermissionDenied):
                        self.request(checkpoint=guard,
                            response=FakeHTTPResponse(status, {"error": "private-provider-body"}), **options)
                    self.assertEqual(sum(event[0] == "request" for event in self.events), int(boundary == "body"))
                    self.assertTrue(all(connection.closed for connection in self.connections))
                    self.assertEqual(len(self.connections), int(boundary in {"connected", "body"}))

    def test_slow_guards_and_connection_share_deadline_and_never_send_late(self):
        for boundary in ("entry", "dns", "connected", "body", "handshake"):
            with self.subTest(boundary=boundary):
                now, guards = [0], [0]
                target = {"entry": 1, "dns": 2, "connected": 3, "body": 4, "handshake": 0}[boundary]

                def guard():
                    guards[0] += 1
                    if guards[0] == target:
                        now[0] = 11

                def expire():
                    now[0] = 11

                with self.assertRaises(ProviderRequestError) as raised:
                    self.request(checkpoint=guard, clock=lambda: now[0],
                        on_connect=expire if boundary == "handshake" else None)
                self.assertEqual(raised.exception.category, "timeout")
                self.assertEqual(sum(event[0] == "request" for event in self.events), int(boundary == "body"))
                self.assertTrue(all(connection.closed for connection in self.connections))

    def test_invalid_guard_and_failed_tls_cannot_resolve_send_or_disclose_secrets(self):
        for invalid in (False, 1, "guard", {}):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                self.request(checkpoint=invalid)
            self.assertEqual(self.events, [])

        def tls_failure():
            raise ssl.SSLCertVerificationError(1, "private-certificate-text")

        with self.assertRaises(ProviderRequestError) as raised:
            self.request(checkpoint=Mock(), on_connect=tls_failure)
        self.assertEqual((raised.exception.category, raised.exception.retryable), ("tls_verification_failed", False))
        self.assertNotIn("private", str(raised.exception))
        self.assertFalse(any(event[0] == "request" for event in self.events))
        self.assertTrue(self.connections[0].closed)
