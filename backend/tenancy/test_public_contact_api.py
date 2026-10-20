import json
from unittest.mock import patch

from django.core import signing
from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from .models import PublicContactRequest
from .public_contact_api import COOKIE, ERROR, PREFIX, SALT
from .public_contact_store import create_contact_request, purge_expired_contact_requests
from . import test_public_contact as fixtures


@override_settings(PUBLIC_CONTACT_ENABLED=True, PUBLIC_CONTACT_RETENTION_DAYS=2,
                   FRONTEND_ORIGIN="https://product.example.invalid",
                   ALLOWED_HOSTS=["product.example.invalid", "api.example.invalid"],
                   SECURE_SSL_REDIRECT=False, CSRF_COOKIE_SECURE=True,
                   CSRF_TRUSTED_ORIGINS=["https://product.example.invalid"],
                   CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class PublicContactApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client(enforce_csrf_checks=True)
        self.headers = {"HTTP_HOST": "product.example.invalid", "HTTP_X_FORWARDED_PROTO": "https",
                        "HTTP_ORIGIN": "https://product.example.invalid", "HTTP_SEC_FETCH_SITE": "same-origin"}
        self.bootstrap(self.client)

    def bootstrap(self, client):
        result = client.get(PREFIX + "csrf/", **self.headers)
        self.assertEqual(result.status_code, 200, result.content)
        self.headers["HTTP_X_CSRFTOKEN"] = result.json()["csrfToken"]
        self.headers["HTTP_X_CONTACT_SCOPE"] = result.json()["scope_hint"]
        return result

    def command(self, **changes):
        return fixtures.PublicContactCommandTests.command(self, **changes)

    def post(self, action, data, client=None, **headers):
        return (client or self.client).post(PREFIX + action + "/", data=json.dumps(data),
            content_type="application/json", **{**self.headers, **headers})

    def assert_private_error(self, result, status):
        self.assertEqual(result.status_code, status, result.content)
        self.assertEqual(result.json(), {"message": ERROR})
        self.assertEqual(result["Cache-Control"], "private, no-store")
        self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")

    def test_anonymous_scoped_cookie_storage_receipt_and_immutable_retry_without_delivery(self):
        cookie = self.client.cookies[COOKIE]
        self.assertTrue(cookie["secure"]); self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["path"], PREFIX); self.assertFalse(cookie["domain"])
        self.assertEqual(cookie["samesite"], "Strict")
        self.assertNotIn("sessionid", self.client.cookies)
        raw = cookie.value
        self.assertNotIn(raw, self.bootstrap(self.client).content.decode())
        self.assertEqual(self.client.cookies[COOKIE].value, raw)
        with patch("django.core.mail.send_mail", side_effect=AssertionError("mail")), \
                patch("socket.create_connection", side_effect=AssertionError("network")):
            first = self.post("create", self.command())
            self.assertEqual(first.status_code, 200, first.content)
            self.assertEqual(self.post("create", self.command()).json(), first.json())
            self.assertEqual(self.post("receipt", {"request_key": first.json()["request_key"]}).json(),
                             {"receipt": first.json()})
            self.assert_private_error(self.post("create", self.command(question="Changed question")), 409)
            original_scope = self.headers["HTTP_X_CONTACT_SCOPE"]
            other = Client(enforce_csrf_checks=True)
            self.bootstrap(other)
            self.assertEqual(self.post("receipt", {"request_key": first.json()["request_key"]}, client=other).json(),
                             {"receipt": None})
            for action, data in (("create", self.command()), ("receipt", {"request_key": first.json()["request_key"]})):
                self.assert_private_error(self.post(action, data, client=other, HTTP_X_CONTACT_SCOPE=original_scope), 409)
        self.assertEqual(PublicContactRequest.objects.count(), 1)
        self.assertNotIn(self.command()["question"], first.content.decode())
        self.assertNotIn(self.command()["reply_email"], first.content.decode())
        self.assertEqual(first["Cache-Control"], "private, no-store")
        self.assertEqual(first["X-Robots-Tag"], "noindex, nofollow")

    def test_origin_csrf_route_and_strict_body_framework_errors_are_generic(self):
        for headers in ({"HTTP_ORIGIN": "https://evil.example.invalid"}, {"HTTP_ORIGIN": ""},
                        {"HTTP_HOST": "api.example.invalid"}, {"HTTP_HOST": "evil.example.invalid"},
                        {"HTTP_SEC_FETCH_SITE": "cross-site"}, {"HTTP_X_CSRFTOKEN": ""}):
            self.assert_private_error(self.post("create", self.command(), **headers), 403)
        self.assert_private_error(self.client.get(PREFIX + "unknown/", **self.headers), 404)
        for method in ("get", "put", "head", "options", "delete"):
            result = getattr(self.client, method)(PREFIX + "create/", **self.headers)
            self.assertEqual(result.status_code, 405)
            self.assertEqual(result["Allow"], "POST")
        for raw, status, kwargs in ((b"{}", 400, {}), (b'{"request_key":"original","request_key":"changed"}', 400, {}),
                                   (b'{"request_key":NaN}', 400, {}), (b"\xff", 400, {}),
                                   (b" " * 16385, 413, {}), (b"{}", 400, {"HTTP_CONTENT_ENCODING": "gzip"})):
            result = self.client.post(PREFIX + "receipt/", data=raw, content_type="application/json",
                                      **self.headers, **kwargs)
            # Missing/extra receipt fields fail before storage, independent of command validation.
            self.assert_private_error(result, status)
        self.assert_private_error(self.post("receipt", {"request_key": self.command()["request_key"], "tenant": 1}), 400)
        self.assert_private_error(self.client.post(PREFIX + "create/?private=question", data=json.dumps(self.command()),
            content_type="application/json", **self.headers), 400)
        self.assert_private_error(self.post("create", {**self.command(), "recipient": "staff@example.invalid"}), 409)
        self.assertFalse(PublicContactRequest.objects.exists())

    def test_disabled_unconfigured_tampered_and_expired_cookie_cannot_replay_after_purge(self):
        for config in ({"PUBLIC_CONTACT_ENABLED": False}, {"PUBLIC_CONTACT_RETENTION_DAYS": None},
                       {"PUBLIC_CONTACT_RETENTION_DAYS": True}):
            with override_settings(**config):
                self.assert_private_error(self.post("create", self.command()), 503)
                self.assert_private_error(self.client.get(PREFIX + "csrf/", **self.headers), 503)
        raw = self.client.cookies[COOKIE].value
        for cookie in (None, "tampered" + raw):
            if cookie is None:
                del self.client.cookies[COOKIE]
            else:
                self.client.cookies[COOKIE] = cookie
            self.assert_private_error(self.post("create", self.command()), 409)
        self.client.cookies[COOKIE] = raw
        self.assertEqual(self.post("create", self.command()).status_code, 200)
        payload = signing.loads(raw, salt=SALT)
        expiration = PublicContactRequest.objects.get().expires_at
        with patch("tenancy.public_contact_store.timezone.now", return_value=expiration):
            self.assertEqual(purge_expired_contact_requests(), 1)
        with patch("tenancy.public_contact_api.time.time", return_value=expiration.timestamp()):
            self.assert_private_error(self.post("create", self.command()), 409)
            self.assert_private_error(self.post("receipt", {"request_key": self.command()["request_key"]}), 409)
            self.assert_private_error(self.client.get(PREFIX + "csrf/", **self.headers), 409)
        self.assertFalse(PublicContactRequest.objects.exists())
        with override_settings(PUBLIC_CONTACT_RETENTION_DAYS=1):
            self.assert_private_error(self.post("create", self.command()), 409)
        with patch("tenancy.public_contact_api.time.time", return_value=payload["expires"]):
            self.assert_private_error(self.post("create", self.command()), 409)

    def test_postcommit_uncertainty_readback_and_framework_debug_never_expose_body(self):
        observed = {}
        def lose_response(**kwargs):
            observed.update(create_contact_request(**kwargs))
            raise RuntimeError("Fixture secret contact error")
        self.client.raise_request_exception = False
        with override_settings(DEBUG=True), patch("tenancy.public_contact_api.create_contact_request", side_effect=lose_response):
            self.assert_private_error(self.post("create", self.command()), 500)
        self.assertEqual(self.post("receipt", {"request_key": self.command()["request_key"]}).json(), {"receipt": observed})
        self.assertEqual(self.post("create", self.command()).json(), observed)
        self.assertEqual(PublicContactRequest.objects.count(), 1)

    def test_actual_separate_ip_budgets_and_cache_failure_fail_closed(self):
        for _ in range(10):
            self.assertEqual(self.post("create", self.command()).status_code, 200)
        self.assert_private_error(self.post("create", self.command()), 429)
        for _ in range(60):
            self.assertEqual(self.post("receipt", {"request_key": self.command()["request_key"]}).status_code, 200)
        self.assert_private_error(self.post("receipt", {"request_key": self.command()["request_key"]}), 429)
        for _ in range(29):
            self.bootstrap(self.client)
        self.assert_private_error(self.client.get(PREFIX + "csrf/", **self.headers), 429)
        with patch("allauth.core.internal.ratelimit.consume", side_effect=RuntimeError("cache")):
            self.assert_private_error(self.post("create", self.command()), 503)
        for rate in (None, " ", "10/h/user", "0/h/ip", "1/0h/ip", "1/nanh/ip", "invalid"):
            with override_settings(ACCOUNT_RATE_LIMITS={"public_contact_create": rate}):
                self.assert_private_error(self.post("create", self.command()), 503)
        self.assertEqual(PublicContactRequest.objects.count(), 1)
