import io
from urllib.parse import parse_qs

from cryptography.fernet import Fernet
from django.test import TestCase, override_settings

from .google_tokens import (
    GoogleTokenError, decrypt_refresh_token, encrypt_refresh_token, exchange_google_code,
    post_google_token_form, post_google_revoke_form, refresh_google_tokens, revoke_google_tokens,
    rotate_refresh_token, SCOPE,
)
from .oauth import CALLBACK_PATH


CALLBACK = f"https://callback.example.com{CALLBACK_PATH}"


class FakeResponse:
    def __init__(self, body=b'{}', status=200):
        self.status = status
        self.stream = io.BytesIO(body)

    def getheaders(self):
        return [("Content-Type", "application/json"), ("Content-Length", str(len(self.stream.getvalue())))]

    def read(self, count):
        return self.stream.read(count)


class FakeConnection:
    def __init__(self, response):
        self.response = response
        self.requests = []
        self.closed = False

    def request(self, method, path, body=None, headers=None):
        self.requests.append((method, path, body, headers))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


@override_settings(GOOGLE_OAUTH_REDIRECT_URI=CALLBACK)
class GoogleTokenTests(TestCase):
    body = {"token_type": "Bearer", "access_token": "ACCESS_SECRET", "refresh_token": "REFRESH_SECRET",
            "scope": SCOPE, "expires_in": 3600}

    def test_code_exchange_validates_exact_scope_and_never_represents_tokens(self):
        calls = []

        def transport(*, form):
            calls.append(form)
            return self.body

        result = exchange_google_code(code="one-use-code", client_id="client-id",
                                      client_secret="client-secret", transport=transport)
        self.assertEqual((result.access_token, result.refresh_token), ("ACCESS_SECRET", "REFRESH_SECRET"))
        self.assertNotIn("SECRET", repr(result))
        self.assertEqual(calls[0]["redirect_uri"], CALLBACK)
        self.assertEqual(calls[0]["grant_type"], "authorization_code")
        with self.assertRaises(GoogleTokenError) as denied:
            exchange_google_code(code="bad\nvalue", client_id="client-id", client_secret="client-secret", transport=transport)
        self.assertEqual(denied.exception.category, "credential_unavailable")
        self.assertEqual(len(calls), 1)
        for invalid, category in (({"scope": SCOPE + " https://www.googleapis.com/auth/webmasters"}, "scope_unavailable"),
                                  ({"refresh_token": None}, "reauthorization_required"),
                                  ({"expires_in": "3600"}, "malformed_response")):
            with self.subTest(invalid=invalid), self.assertRaises(GoogleTokenError) as error:
                exchange_google_code(code="one-use-code", client_id="client-id", client_secret="client-secret",
                                     transport=lambda **_kwargs: {**self.body, **invalid})
            self.assertEqual(error.exception.category, category)
            self.assertNotIn("SECRET", str(error.exception))

    def test_refresh_token_encryption_rotation_and_refresh_response(self):
        old_key, new_key = Fernet.generate_key().decode(), Fernet.generate_key().decode()
        with override_settings(GOOGLE_OAUTH_ENCRYPTION_KEYS=(old_key,)):
            encrypted = encrypt_refresh_token("REFRESH_SECRET")
        self.assertNotIn("REFRESH_SECRET", encrypted)
        with override_settings(GOOGLE_OAUTH_ENCRYPTION_KEYS=(new_key, old_key)):
            self.assertEqual(decrypt_refresh_token(encrypted), "REFRESH_SECRET")
            rotated = rotate_refresh_token(encrypted)
        with override_settings(GOOGLE_OAUTH_ENCRYPTION_KEYS=(new_key,)):
            self.assertEqual(decrypt_refresh_token(rotated), "REFRESH_SECRET")
            with self.assertRaises(GoogleTokenError):
                decrypt_refresh_token(encrypted)
            captured = []

            def transport(*, form):
                captured.append(form)
                return {key: value for key, value in self.body.items() if key != "refresh_token"}

            refreshed = refresh_google_tokens(encrypted_refresh=rotated, client_id="client-id",
                                              client_secret="client-secret", transport=transport)
            self.assertIsNone(refreshed.refresh_token)
            self.assertEqual(captured[0]["refresh_token"], "REFRESH_SECRET")
            self.assertEqual(captured[0]["grant_type"], "refresh_token")
        with override_settings(GOOGLE_OAUTH_ENCRYPTION_KEYS=()):
            with self.assertRaises(GoogleTokenError) as error:
                encrypt_refresh_token("REFRESH_SECRET")
            self.assertEqual(error.exception.category, "credential_unavailable")

    def test_fixed_token_host_pinned_public_dns_redirect_and_secret_safe_errors(self):
        observed = {}
        connection = FakeConnection(FakeResponse(b'{"ok":true}'))

        def resolver(host, port, timeout):
            observed["dns"] = (host, port, timeout)
            return ["8.8.8.8"]

        def factory(scheme, address, hostname, port, deadline, clock):
            observed["connection"] = (scheme, address, hostname, port)
            return connection

        form = {"grant_type": "authorization_code", "code": "one-time-code",
                "client_id": "client-id", "client_secret": "CLIENT_SECRET", "redirect_uri": CALLBACK}
        self.assertEqual(post_google_token_form(form=form, resolver=resolver, connection_factory=factory), {"ok": True})
        self.assertEqual(observed["connection"], ("https", "8.8.8.8", "oauth2.googleapis.com", 443))
        method, path, body, _headers = connection.requests[0]
        self.assertEqual((method, path), ("POST", "/token"))
        self.assertEqual(parse_qs(body.decode())["client_secret"], ["CLIENT_SECRET"])
        self.assertNotIn("CLIENT_SECRET", path)
        self.assertTrue(connection.closed)

        for status, category in ((302, "redirect_denied"), (429, "quota_limited"), (503, "provider_unavailable")):
            candidate = FakeConnection(FakeResponse(b'{"error":"CLIENT_SECRET"}', status))
            with self.subTest(status=status), self.assertRaises(GoogleTokenError) as error:
                post_google_token_form(form=form, resolver=resolver,
                                       connection_factory=lambda *_args: candidate)
            self.assertEqual(error.exception.category, category)
            self.assertNotIn("CLIENT_SECRET", str(error.exception))
            self.assertTrue(candidate.closed)
        for body in (b'{"x":NaN}', b'{"x":1,"x":2}', b'x' * 32769):
            candidate = FakeConnection(FakeResponse(body))
            with self.subTest(size=len(body)), self.assertRaises(GoogleTokenError):
                post_google_token_form(form=form, resolver=resolver, connection_factory=lambda *_args: candidate)
        with self.assertRaises(GoogleTokenError) as denied:
            post_google_token_form(form=form, resolver=lambda *_args: ["127.0.0.1"], connection_factory=factory)
        self.assertEqual(denied.exception.category, "egress_denied")

    def test_revocation_post_is_fixed_host_bounded_and_retryable(self):
        key = Fernet.generate_key().decode()
        connection = FakeConnection(FakeResponse(b""))

        def factory(_scheme, _address, hostname, _port, _deadline, _clock):
            self.assertEqual(hostname, "oauth2.googleapis.com")
            return connection

        with override_settings(GOOGLE_OAUTH_ENCRYPTION_KEYS=(key,)):
            encrypted = encrypt_refresh_token("REFRESH_SECRET")
            self.assertTrue(revoke_google_tokens(encrypted_refresh=encrypted,
                transport=lambda *, token: post_google_revoke_form(
                    token=token, resolver=lambda *_args: ["8.8.8.8"], connection_factory=factory)))
        method, path, body, _headers = connection.requests[0]
        self.assertEqual((method, path), ("POST", "/revoke"))
        self.assertEqual(parse_qs(body.decode())["token"], ["REFRESH_SECRET"])
        self.assertNotIn("REFRESH_SECRET", path)
        self.assertTrue(connection.closed)
        for status, category in ((302, "redirect_denied"), (429, "quota_limited"),
                                 (503, "provider_unavailable"), (400, "revocation_rejected")):
            candidate = FakeConnection(FakeResponse(b"token=REFRESH_SECRET", status))
            with self.subTest(status=status), self.assertRaises(GoogleTokenError) as error:
                post_google_revoke_form(token="REFRESH_SECRET", resolver=lambda *_args: ["8.8.8.8"],
                                        connection_factory=lambda *_args: candidate)
            self.assertEqual(error.exception.category, category)
            self.assertNotIn("REFRESH_SECRET", str(error.exception))
            self.assertTrue(candidate.closed)
