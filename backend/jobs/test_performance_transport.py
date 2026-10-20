import io
import json

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from tenancy.services import create_organization, create_project
from tenancy.models import Project

from .performance_transport import PerformanceTransportError, collect_performance, google_performance_request


class FakeResponse:
    def __init__(self, body=b"{}", *, status=200, content_type="application/json"):
        self.status = status
        self.content_type = content_type
        self.stream = io.BytesIO(body)

    def getheaders(self):
        return [("Content-Type", self.content_type), ("Content-Length", str(len(self.stream.getvalue())))]

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


class PerformanceTransportTests(TestCase):
    key = "fixture_key_with_32_placeholder_chars"

    def setUp(self):
        owner = get_user_model().objects.create_user("performance-transport@example.com", password="test-password")
        EmailAddress.objects.create(user=owner, email=owner.email, verified=True, primary=True)
        organization = create_organization(user=owner, name="Performance transport")
        self.project = create_project(organization=organization, user=owner, name="Site",
                                      canonical_origin="https://performance-transport.example")

    def transport(self, kind, response, *, addresses=("8.8.8.8",)):
        observed = {}
        connection = FakeConnection(response)

        def resolver(host, port, timeout):
            observed["resolution"] = (host, port)
            return addresses

        def factory(scheme, address, server_hostname, port, deadline, clock):
            observed["connection"] = (scheme, address, server_hostname, port)
            return connection

        def call(*, target="https://performance-transport.example/page", strategy="mobile", grain="page"):
            return google_performance_request(
                project=self.project, kind=kind, target=target, strategy=strategy, grain=grain, api_key=self.key,
                resolver=resolver, connection_factory=factory,
            )

        return call, observed, connection

    def test_crux_api_key_is_header_only_and_host_is_pinned(self):
        call, observed, connection = self.transport("crux_current", FakeResponse(b'{"record":{}}'))
        self.assertEqual(call(), {"record": {}})
        self.assertEqual(observed["resolution"], ("chromeuxreport.googleapis.com", 443))
        self.assertEqual(observed["connection"], ("https", "8.8.8.8", "chromeuxreport.googleapis.com", 443))
        method, path, body, headers = connection.requests[0]
        self.assertEqual((method, path), ("POST", "/v1/records:queryRecord"))
        self.assertEqual(headers["X-goog-api-key"], self.key)
        self.assertNotIn(self.key, path)
        self.assertEqual(json.loads(body)["formFactor"], "PHONE")
        self.assertEqual(json.loads(body)["url"], "https://performance-transport.example/page")
        self.assertTrue(connection.closed)

        history, _observed, connection = self.transport("crux_history", FakeResponse())
        history(grain="origin", target="https://performance-transport.example", strategy="desktop")
        request = json.loads(connection.requests[0][2])
        self.assertEqual((request["origin"], request["formFactor"], request["collectionPeriodCount"]),
                         ("https://performance-transport.example", "DESKTOP", 40))

    def test_pagespeed_uses_fixed_get_without_a_key_in_url(self):
        call, observed, connection = self.transport("psi_lab", FakeResponse())
        call()
        method, path, body, headers = connection.requests[0]
        self.assertEqual(method, "GET")
        self.assertIsNone(body)
        self.assertTrue(path.startswith("/pagespeedonline/v5/runPagespeed?"))
        self.assertIn("strategy=mobile", path)
        self.assertNotIn(self.key, path)
        self.assertEqual(observed["connection"][2], "pagespeedonline.googleapis.com")
        with self.assertRaises(ValidationError):
            call(strategy="tablet")

    def test_denied_network_quota_missing_data_and_malformed_bodies(self):
        for status, category, retryable in ((302, "redirect_denied", False), (404, "field_data_unavailable", False),
                                            (429, "quota_limited", True), (503, "provider_unavailable", True)):
            call, _observed, connection = self.transport("crux_current", FakeResponse(status=status))
            with self.subTest(status=status), self.assertRaises(PerformanceTransportError) as raised:
                call()
            self.assertEqual((raised.exception.category, raised.exception.retryable), (category, retryable))
            self.assertTrue(connection.closed)
        for body in (b'not-json', b'{"foo":NaN}', b'{"record":1,"record":2}', b'x' * (256 * 1024 + 1)):
            call, _observed, connection = self.transport("crux_current", FakeResponse(body))
            with self.subTest(size=len(body)), self.assertRaises(PerformanceTransportError) as raised:
                call()
            self.assertEqual(raised.exception.category, "response_too_large" if len(body) > 256 * 1024 else "malformed_response")
            self.assertTrue(connection.closed)
        for addresses in (("127.0.0.1",), ("8.8.8.8", "10.0.0.1")):
            call, _observed, _connection = self.transport("crux_current", FakeResponse(), addresses=addresses)
            with self.assertRaises(PerformanceTransportError) as raised:
                call()
            self.assertEqual(raised.exception.category, "egress_denied")

    def test_current_project_scope_and_missing_key_fail_before_transport(self):
        with self.assertRaises(ValidationError):
            collect_performance(project=self.project, target="https://other.example/page", kind="crux_current",
                                strategy="mobile", grain="page", api_key=self.key, transport=lambda **_args: {})
        with self.assertRaises(PerformanceTransportError) as raised:
            google_performance_request(kind="crux_current", target="https://performance-transport.example/page",
                                       project=self.project, strategy="mobile", grain="page", api_key="")
        self.assertEqual(raised.exception.category, "credential_unavailable")
        call, observed, _connection = self.transport("crux_current", FakeResponse())
        with self.assertRaises(ValidationError):
            call(target="https://other.example/page")
        self.assertEqual(observed, {})
        Project.objects.filter(pk=self.project.pk).update(canonical_origin="https://changed.example")
        with self.assertRaises(ValidationError):
            call()
        self.assertEqual(observed, {})
