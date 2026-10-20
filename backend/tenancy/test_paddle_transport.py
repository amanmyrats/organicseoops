import json
from types import SimpleNamespace

from django.utils import timezone

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from integrations.test_search_console_transport import FakeConnection, FakeResponse

from .paddle_transport import (PaddleTransportError, paddle_adjustment_get, paddle_portal_create, paddle_price_get,
                                paddle_subscription_cancel, paddle_subscription_get, paddle_transaction_create,
                                paddle_transaction_get)
from .test_paddle_seller import LIVE_KEY, SANDBOX_KEY


class PaddleCatalogTransportTests(SimpleTestCase):
    def fake(self, *, status=200, body=b'{"data":{}}', address="8.8.8.8"):
        connection = FakeConnection(FakeResponse(body, status))
        seen = {}

        def resolve(host, port, timeout):
            seen["host"] = host
            return [address]

        def factory(scheme, address, host, port, deadline, clock):
            seen["tls"] = (scheme, address, host, port)
            return connection

        return resolve, factory, connection, seen

    def test_hosts_and_version_are_environment_fixed(self):
        price_id = "pri_" + "b" * 26
        for environment, key, host in (("sandbox", SANDBOX_KEY, "sandbox-api.paddle.com"),
                                       ("live", LIVE_KEY, "api.paddle.com")):
            resolve, factory, connection, seen = self.fake()
            self.assertEqual(paddle_price_get(environment=environment, price_id=price_id, api_key=key,
                             resolver=resolve, connection_factory=factory), {"data": {}})
            self.assertEqual(seen["tls"], ("https", "8.8.8.8", host, 443))
            method, path, headers, body = connection.requests[0]
            self.assertEqual((method, path, headers["Paddle-Version"]),
                             ("GET", f"/prices/{price_id}?include=product", "1"))
            self.assertEqual(headers["Authorization"], f"Bearer {key}")
            self.assertNotIn(key, path)
        resolve, factory, _, _ = self.fake()
        with self.assertRaises(PaddleTransportError) as error:
            paddle_price_get(environment="live", price_id=price_id, api_key=SANDBOX_KEY,
                             resolver=resolve, connection_factory=factory)
        self.assertEqual(error.exception.category, "credential_unavailable")

    def test_denials_and_unsafe_egress_never_return_provider_body(self):
        for status, category in ((302, "redirect_denied"), (403, "authorization_unavailable"),
                                 (404, "catalog_unavailable"), (429, "quota_limited"),
                                 (500, "provider_unavailable")):
            resolve, factory, connection, _ = self.fake(status=status, body=b'{"secret":"private"}')
            with self.subTest(status=status), self.assertRaises(PaddleTransportError) as error:
                paddle_price_get(environment="sandbox", price_id="pri_" + "a" * 26, api_key=SANDBOX_KEY,
                                 resolver=resolve, connection_factory=factory)
            self.assertEqual(error.exception.category, category)
            self.assertNotIn("private", str(error.exception))
            self.assertTrue(connection.closed)
        resolve, factory, _, _ = self.fake(address="127.0.0.1")
        with self.assertRaises(PaddleTransportError) as error:
            paddle_price_get(environment="sandbox", price_id="pri_" + "a" * 26, api_key=SANDBOX_KEY,
                             resolver=resolve, connection_factory=factory)
        self.assertEqual(error.exception.category, "egress_denied")

    def test_transaction_post_requires_marked_attempt_and_never_retries_or_leaks_key(self):
        from django.utils import timezone

        class Attempt:
            class State:
                SENDING = "sending"
            pk = 19
            state = "sending"
            sent_at = timezone.now()
            organization_id = 17
            price_id = "pri_" + "a" * 26
            environment = "sandbox"

        resolve, factory, connection, seen = self.fake(status=201, body=b'{"data":{"id":"txn_fixture"}}')
        self.assertEqual(paddle_transaction_create(environment="sandbox", api_key=SANDBOX_KEY, attempt=Attempt(),
                         resolver=resolve, connection_factory=factory)["data"]["id"], "txn_fixture")
        method, path, headers, raw = connection.requests[0]
        self.assertEqual((seen["host"], method, path, headers["Paddle-Version"]),
                         ("sandbox-api.paddle.com", "POST", "/transactions", "1"))
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(json.loads(raw)["custom_data"], {
            "organization_id": "17", "offer_version": "agency-launch-v1", "checkout_attempt_id": "19"})
        self.assertNotIn(SANDBOX_KEY, raw.decode() + path)
        resolve, factory, connection, _ = self.fake(status=503, body=b'{"secret":"private"}')
        with self.assertRaises(PaddleTransportError) as error:
            paddle_transaction_create(environment="sandbox", api_key=SANDBOX_KEY, attempt=Attempt(),
                                      resolver=resolve, connection_factory=factory)
        self.assertEqual(error.exception.category, "provider_unavailable")
        self.assertEqual(len(connection.requests), 1)

    def test_subscription_and_portal_are_fixed_paths_without_keys_in_request_body(self):
        customer, subscription = "ctm_" + "a" * 26, "sub_" + "b" * 26
        resolve, factory, connection, _ = self.fake()
        paddle_subscription_get(environment="sandbox", subscription_id=subscription, api_key=SANDBOX_KEY,
                                resolver=resolve, connection_factory=factory)
        self.assertEqual(connection.requests[0][:2], ("GET", f"/subscriptions/{subscription}"))
        resolve, factory, connection, _ = self.fake(status=201)
        paddle_portal_create(environment="sandbox", customer_id=customer, subscription_id=subscription,
                             api_key=SANDBOX_KEY, resolver=resolve, connection_factory=factory)
        method, path, headers, raw = connection.requests[0]
        self.assertEqual((method, path), ("POST", f"/customers/{customer}/portal-sessions"))
        self.assertEqual(json.loads(raw), {"subscription_ids": [subscription]})
        self.assertNotIn(SANDBOX_KEY, path + raw.decode())
        resolve, factory, connection, _ = self.fake()
        paddle_transaction_get(environment="sandbox", transaction_id="txn_" + "c" * 26,
                               api_key=SANDBOX_KEY, resolver=resolve, connection_factory=factory)
        self.assertEqual(connection.requests[0][:2], ("GET", "/transactions/txn_" + "c" * 26))
        resolve, factory, connection, _ = self.fake(body=b'{"data":[],"meta":{"pagination":{"has_more":false}}}')
        paddle_adjustment_get(environment="sandbox", adjustment_id="adj_" + "d" * 26,
                              api_key=SANDBOX_KEY, resolver=resolve, connection_factory=factory)
        self.assertEqual(connection.requests[0][:2], ("GET", "/adjustments?id=adj_" + "d" * 26 + "&per_page=1"))

    def test_closure_cancel_requires_attempt_and_accepts_only_http_200(self):
        subscription = SimpleNamespace(environment="sandbox", customer_id="ctm_" + "a" * 26,
                                       subscription_id="sub_" + "b" * 26)
        attempt = SimpleNamespace(state="sending", State=SimpleNamespace(SENDING="sending"),
            attempted_at=timezone.now(), organization=SimpleNamespace(closed_at=timezone.now(), is_suspended=True),
            environment="sandbox", customer_id=subscription.customer_id,
            provider_subscription_id=subscription.subscription_id, subscription=subscription)
        resolve, factory, connection, _ = self.fake(status=200)
        paddle_subscription_cancel(attempt=attempt, api_key=SANDBOX_KEY,
                                   resolver=resolve, connection_factory=factory)
        method, path, headers, raw = connection.requests[0]
        self.assertEqual((method, path, headers["Paddle-Version"]),
                         ("POST", f"/subscriptions/{subscription.subscription_id}/cancel", "1"))
        self.assertEqual(json.loads(raw), {"effective_from": "immediately"})
        self.assertNotIn(SANDBOX_KEY, path + raw.decode())
        resolve, factory, _, _ = self.fake(status=201)
        with self.assertRaises(PaddleTransportError):
            paddle_subscription_cancel(attempt=attempt, api_key=SANDBOX_KEY,
                                       resolver=resolve, connection_factory=factory)
        attempt.state = "unknown"
        with self.assertRaises(ValidationError):
            paddle_subscription_cancel(attempt=attempt, api_key=SANDBOX_KEY,
                                       resolver=resolve, connection_factory=factory)
