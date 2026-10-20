import io
import json
from datetime import timedelta
from zoneinfo import ZoneInfo

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from tenancy.models import ProjectOriginVerification
from tenancy.services import create_organization, create_project, update_project

from .google_tokens import SCOPE
from .models import GoogleOAuthGrant, IntegrationConnection
from .search_console_transport import (SearchConsoleTransportError, google_search_analytics_query,
                                       google_site_get, google_sites_list, google_sitemaps_list,
                                        google_url_inspection)
from .search_console_transport import google_search_analytics_query_page
from .services import create_connection


class FakeResponse:
    def __init__(self, body=b"{}", status=200):
        self.stream = io.BytesIO(body)
        self.status = status

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
        self.requests.append((method, path, headers, body))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class SearchConsoleTransportTests(TestCase):
    bearer = "ACCESS_SECRET"

    def transport(self, response, *, addresses=("8.8.8.8",)):
        observed = {}
        connection = FakeConnection(response)

        def resolver(host, port, timeout):
            observed["resolution"] = (host, port, timeout)
            return addresses

        def factory(scheme, address, hostname, port, deadline, clock):
            observed["connection"] = (scheme, address, hostname, port)
            return connection

        return resolver, factory, connection, observed

    def test_sites_list_and_exact_prefix_get_use_fixed_pinned_host_and_header(self):
        resolver, factory, connection, observed = self.transport(FakeResponse(b'{"siteEntry":[]}'))
        self.assertEqual(google_sites_list(access_token=self.bearer, resolver=resolver, connection_factory=factory),
                         {"siteEntry": []})
        self.assertEqual(observed["connection"], ("https", "8.8.8.8", "www.googleapis.com", 443))
        method, path, headers, _body = connection.requests[0]
        self.assertEqual((method, path), ("GET", "/webmasters/v3/sites"))
        self.assertEqual(headers["Authorization"], "Bearer " + self.bearer)
        self.assertNotIn(self.bearer, path)
        self.assertTrue(connection.closed)

        resolver, factory, connection, _ = self.transport(FakeResponse(b'{"siteUrl":"https://site.example/"}'))
        google_site_get(site_url="https://site.example/", access_token=self.bearer,
                         resolver=resolver, connection_factory=factory)
        self.assertEqual(connection.requests[0][1], "/webmasters/v3/sites/https%3A%2F%2Fsite.example%2F")
        resolver, factory, connection, _ = self.transport(FakeResponse(b'{"siteUrl":"sc-domain:site.example"}'))
        google_site_get(site_url="sc-domain:site.example", access_token=self.bearer,
                        resolver=resolver, connection_factory=factory)
        self.assertEqual(connection.requests[0][1], "/webmasters/v3/sites/sc-domain%3Asite.example")
        for site in ("sc-domain:site.example/path", "https://site.example/path/", "https://user@site.example/",
                      "https://site.example/?key=private"):
            with self.subTest(site=site), self.assertRaises(ValidationError):
                google_site_get(site_url=site, access_token=self.bearer,
                                resolver=resolver, connection_factory=factory)

    def test_unsafe_dns_provider_failures_and_malformed_output_do_not_include_bearer(self):
        for addresses in (("127.0.0.1",), ("8.8.8.8", "10.0.0.1")):
            resolver, factory, _connection, _ = self.transport(FakeResponse(), addresses=addresses)
            with self.assertRaises(SearchConsoleTransportError) as error:
                google_sites_list(access_token=self.bearer, resolver=resolver, connection_factory=factory)
            self.assertEqual(error.exception.category, "egress_denied")
        for status, category, retryable in ((302, "redirect_denied", False), (401, "authorization_unavailable", False),
                                            (404, "property_unavailable", False), (429, "quota_limited", True),
                                            (503, "provider_unavailable", True)):
            resolver, factory, connection, _ = self.transport(FakeResponse(b'{"error":"ACCESS_SECRET"}', status=status))
            with self.subTest(status=status), self.assertRaises(SearchConsoleTransportError) as error:
                google_sites_list(access_token=self.bearer, resolver=resolver, connection_factory=factory)
            self.assertEqual((error.exception.category, error.exception.retryable), (category, retryable))
            self.assertNotIn(self.bearer, str(error.exception))
            self.assertTrue(connection.closed)
        for body in (b'{"siteEntry":NaN}', b'{"siteEntry":[],"siteEntry":[]}', b'x' * (256 * 1024 + 1)):
            resolver, factory, connection, _ = self.transport(FakeResponse(body))
            with self.subTest(size=len(body)), self.assertRaises(SearchConsoleTransportError) as error:
                google_sites_list(access_token=self.bearer, resolver=resolver, connection_factory=factory)
            self.assertEqual(error.exception.category, "response_too_large" if len(body) > 256 * 1024 else "malformed_response")
            self.assertTrue(connection.closed)


class SearchAnalyticsTransportTests(TestCase):
    bearer = "ACCESS_SECRET"
    transport = SearchConsoleTransportTests.transport

    def setUp(self):
        self.user = get_user_model().objects.create_user("analytics-owner@example.com", password="test-password")
        EmailAddress.objects.create(user=self.user, email=self.user.email, primary=True, verified=True)
        organization = create_organization(user=self.user, name="Analytics organization")
        self.project = create_project(organization=organization, user=self.user, name="Analytics property",
                                      canonical_origin="https://analytics.example")
        self.connection = create_connection(
            project=self.project, user=self.user, provider="google_search_console",
            external_property_id="https://analytics.example/",
            capabilities=["api_sync", "query_metrics", "page_metrics"],
            available_dimensions=["date", "query", "page"],
            source_semantics="search_console_performance", source_semantics_version="gsc-performance-v1",
            timezone="America/Los_Angeles",
        )
        self.grant = GoogleOAuthGrant.objects.create(
            organization=organization, project=self.project, actor=self.user, scope=SCOPE,
            encrypted_refresh_token="v1:fixture-ciphertext", state=GoogleOAuthGrant.State.ACTIVE,
            selected_property_id=self.connection.external_property_id,
            selected_site_url="https://analytics.example/", verified_at=timezone.now(),
        )
        self.connection.credential_reference = self.grant.credential_reference
        self.connection.save()
        self.day = timezone.now().astimezone(ZoneInfo("America/Los_Angeles")).date() - timedelta(days=5)

    def test_exact_property_daily_final_post_and_offset_bound(self):
        resolver, factory, connection, observed = self.transport(FakeResponse(b'{"rows":[]}'))
        self.assertEqual(google_search_analytics_query(
            connection=self.connection, access_token=self.bearer, day=self.day, dimension="query",
            start_row=100, resolver=resolver, connection_factory=factory,
        ), {"rows": []})
        self.assertEqual(observed["connection"], ("https", "8.8.8.8", "www.googleapis.com", 443))
        method, path, headers, body = connection.requests[0]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/webmasters/v3/sites/https%3A%2F%2Fanalytics.example%2F/searchAnalytics/query")
        self.assertEqual(headers["Authorization"], "Bearer " + self.bearer)
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertNotIn(self.bearer, path + body.decode())
        self.assertEqual(json.loads(body), {"startDate": self.day.isoformat(), "endDate": self.day.isoformat(),
                                             "dimensions": ["query"], "type": "web", "aggregationType": "byProperty",
                                             "dataState": "final", "rowLimit": 100, "startRow": 100})
        self.assertTrue(connection.closed)

    def test_explicit_pair_transport_is_one_fixed_host_final_auto_query_page_request(self):
        resolver, factory, wire, observed = self.transport(FakeResponse(b'{"rows":[]}'))
        self.assertEqual(google_search_analytics_query_page(connection=self.connection, access_token=self.bearer,
            day=self.day, start_row=100, resolver=resolver, connection_factory=factory), {"rows": []})
        self.assertEqual(observed["connection"], ("https", "8.8.8.8", "www.googleapis.com", 443))
        method, path, headers, body = wire.requests[0]
        self.assertEqual((method, path), ("POST", "/webmasters/v3/sites/https%3A%2F%2Fanalytics.example%2F/searchAnalytics/query"))
        self.assertEqual(json.loads(body), {"startDate": self.day.isoformat(), "endDate": self.day.isoformat(),
            "dimensions": ["query", "page"], "type": "web", "aggregationType": "auto", "dataState": "final",
            "rowLimit": 100, "startRow": 100})
        self.assertEqual(headers["Authorization"], "Bearer " + self.bearer)
        self.assertNotIn(self.bearer, path + body.decode())
        for day, offset in ((self.day, True), (self.day, 200), (timezone.now().date(), 0)):
            with self.subTest(day=day, offset=offset), self.assertRaises(ValidationError):
                google_search_analytics_query_page(connection=self.connection, access_token=self.bearer, day=day,
                    start_row=offset, resolver=lambda *_args, **_kwargs: self.fail("Invalid selection must not resolve"))

    def test_domain_property_only_requests_page_aggregation_while_origin_verified(self):
        verification = ProjectOriginVerification.objects.create(
            organization=self.project.organization, project=self.project, origin=self.project.canonical_origin,
            challenge_digest="a" * 64, state=ProjectOriginVerification.State.VERIFIED,
            verified_at=timezone.now(),
        )
        domain = "sc-domain:analytics.example"
        grant = GoogleOAuthGrant.objects.create(
            organization=self.project.organization, project=self.project, actor=self.user, scope=SCOPE,
            encrypted_refresh_token="v1:fixture-only", state=GoogleOAuthGrant.State.ACTIVE,
            verified_at=timezone.now(), selected_property_id=domain, selected_site_url=domain,
            selected_origins=[self.project.canonical_origin],
        )
        scoped = IntegrationConnection(
            project=self.project, provider="google_search_console", external_property_id=domain,
            credential_reference=grant.credential_reference, capabilities=["api_sync", "page_metrics"],
            available_dimensions=["page"], source_semantics="search_console_domain_pages",
            source_semantics_version="gsc-domain-page-v1", timezone="America/Los_Angeles",
        )
        scoped.save()
        resolver, factory, transport, _ = self.transport(FakeResponse(b'{"rows":[]}'))
        for dimension in ("query", "date"):
            with self.subTest(dimension=dimension), self.assertRaises(ValidationError):
                google_search_analytics_query(connection=scoped, access_token=self.bearer, day=self.day,
                                               dimension=dimension, resolver=resolver, connection_factory=factory)
        self.assertFalse(transport.requests)
        with self.assertRaises(ValidationError):
            google_search_analytics_query_page(connection=scoped, access_token=self.bearer, day=self.day,
                resolver=lambda *_args, **_kwargs: self.fail("Domain-wide pairs must not resolve"))
        result = google_search_analytics_query(connection=scoped, access_token=self.bearer, day=self.day,
                                               dimension="page", resolver=resolver, connection_factory=factory)
        self.assertEqual(result, {"rows": []})
        method, path, headers, body = transport.requests[0]
        self.assertEqual((method, path), ("POST", "/webmasters/v3/sites/sc-domain%3Aanalytics.example/searchAnalytics/query"))
        self.assertEqual((json.loads(body)["dimensions"], json.loads(body)["aggregationType"]), (["page"], "byPage"))
        self.assertNotIn(self.bearer, path + body.decode())
        resolver, factory, sitemap_transport, _ = self.transport(FakeResponse(b'{"sitemap":[]}'))
        self.assertEqual(google_sitemaps_list(connection=scoped, access_token=self.bearer,
                                              resolver=resolver, connection_factory=factory), {"sitemap": []})
        self.assertEqual(sitemap_transport.requests[0][1],
                         "/webmasters/v3/sites/sc-domain%3Aanalytics.example/sitemaps")
        resolver, factory, inspection_transport, observed = self.transport(FakeResponse(
            b'{"inspectionResult":{"indexStatusResult":{"verdict":"PASS"}}}'))
        self.assertEqual(google_url_inspection(connection=scoped,
                                               inspection_url="https://analytics.example/owned",
                                               access_token=self.bearer, resolver=resolver,
                                               connection_factory=factory)["inspectionResult"]["indexStatusResult"]["verdict"],
                         "PASS")
        self.assertEqual(observed["connection"], ("https", "8.8.8.8", "searchconsole.googleapis.com", 443))
        method, path, headers, body = inspection_transport.requests[0]
        self.assertEqual((method, path), ("POST", "/v1/urlInspection/index:inspect"))
        self.assertEqual(json.loads(body), {"inspectionUrl": "https://analytics.example/owned",
                                            "siteUrl": "sc-domain:analytics.example"})
        self.assertNotIn(self.bearer, path + body.decode())
        for url in ("https://m.analytics.example/foreign", "https://analytics.example/?key=PRIVATE_SECRET",
                    "https://[invalid", "http://analytics.example/page"):
            with self.subTest(url=url), self.assertRaises(ValidationError):
                google_url_inspection(connection=scoped, inspection_url=url, access_token=self.bearer,
                                      resolver=lambda *_args: self.fail("outside URL must not resolve"),
                                      connection_factory=factory)
        ProjectOriginVerification.objects.filter(pk=verification.pk).update(
            state=ProjectOriginVerification.State.REVOKED, revoked_at=timezone.now())
        with self.assertRaises(ValidationError):
            google_search_analytics_query(connection=scoped, access_token=self.bearer, day=self.day,
                                           dimension="page", resolver=lambda *_args: self.fail("revoked scope must not resolve"),
                                           connection_factory=factory)

    def test_no_request_for_invalid_grant_or_current_scope_and_provider_outage(self):
        for dimension, row in ((["query"], 0), ("page", -1), ("query", 200)):
            with self.subTest(dimension=dimension, row=row), self.assertRaises(ValidationError):
                google_search_analytics_query(connection=self.connection, access_token=self.bearer,
                                              day=self.day, dimension=dimension, start_row=row)
        resolver, factory, connection, _ = self.transport(FakeResponse(b'{"error":"ACCESS_SECRET"}', status=429))
        with self.assertRaises(SearchConsoleTransportError) as error:
            google_search_analytics_query(connection=self.connection, access_token=self.bearer,
                                          day=self.day, dimension="page", resolver=resolver, connection_factory=factory)
        self.assertEqual((error.exception.category, error.exception.retryable), ("quota_limited", True))
        self.assertNotIn(self.bearer, str(error.exception))
        self.assertTrue(connection.closed)
        self.grant.state = GoogleOAuthGrant.State.REVOCATION_PENDING
        self.grant.revision += 1
        self.grant.save()
        with self.assertRaises(ValidationError):
            google_search_analytics_query(connection=self.connection, access_token=self.bearer,
                                          day=self.day, dimension="date", resolver=resolver, connection_factory=factory)
        self.grant.state = GoogleOAuthGrant.State.ACTIVE
        self.grant.revision += 1
        self.grant.save()
        update_project(project=self.project, user=self.user, canonical_origin="https://new-analytics.example")
        with self.assertRaises(ValidationError):
            google_search_analytics_query(connection=self.connection, access_token=self.bearer,
                                          day=self.day, dimension="date", resolver=resolver, connection_factory=factory)
