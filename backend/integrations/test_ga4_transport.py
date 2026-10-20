import json
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from django.utils import timezone

from .ga4_transport import (ga4_admin_property_get, ga4_admin_streams_list,
                            ga4_check_landing_compatibility, ga4_landing_report)
from .search_console_transport import SearchConsoleTransportError
from .test_search_console_transport import FakeConnection, FakeResponse


class GA4TransportTests(SimpleTestCase):
    def fake(self, *, body=b"{}", status=200, addresses=("8.8.8.8",)):
        connection = FakeConnection(FakeResponse(body, status))
        seen = {}

        def resolve(host, port, timeout):
            seen["dns"] = host
            return addresses

        def factory(scheme, address, hostname, port, deadline, clock):
            seen["tls"] = (scheme, address, hostname, port)
            return connection

        return resolve, factory, connection, seen

    def test_property_and_stream_requests_are_admin_host_only_and_fail_on_pagination(self):
        resolve, factory, connection, seen = self.fake(body=b'{"name":"properties/12345"}')
        self.assertEqual(ga4_admin_property_get(property_id="12345", access_token="SECRET",
                         resolver=resolve, connection_factory=factory)["name"], "properties/12345")
        self.assertEqual(seen["tls"], ("https", "8.8.8.8", "analyticsadmin.googleapis.com", 443))
        self.assertEqual(connection.requests[0][0:2], ("GET", "/v1beta/properties/12345"))
        self.assertNotIn("SECRET", connection.requests[0][1])
        resolve, factory, connection, _ = self.fake(body=b'{"dataStreams":[]}')
        ga4_admin_streams_list(property_id="12345", access_token="SECRET", resolver=resolve,
                               connection_factory=factory)
        self.assertEqual(connection.requests[0][1], "/v1beta/properties/12345/dataStreams?pageSize=50")
        resolve, factory, _, _ = self.fake(body=b'{"nextPageToken":"private","dataStreams":[]}')
        with self.assertRaises(ValidationError):
            ga4_admin_streams_list(property_id="12345", access_token="SECRET", resolver=resolve,
                                   connection_factory=factory)

    def test_landing_request_is_hostname_filtered_bounded_and_never_uses_bearer_in_url(self):
        day = timezone.now().date() - timedelta(days=4)
        resolve, factory, connection, seen = self.fake(body=b'{"rows":[]}')
        ga4_landing_report(property_id="12345", approved_origin="https://site.example", day=day,
                           offset=0, access_token="SECRET", resolver=resolve, connection_factory=factory)
        self.assertEqual(seen["tls"], ("https", "8.8.8.8", "analyticsdata.googleapis.com", 443))
        method, path, headers, raw = connection.requests[0]
        self.assertEqual((method, path), ("POST", "/v1beta/properties/12345:runReport"))
        self.assertEqual(headers["Authorization"], "Bearer SECRET")
        self.assertNotIn("SECRET", path + raw.decode())
        body = json.loads(raw)
        self.assertEqual(body["dimensionFilter"]["filter"], {"fieldName": "hostName",
            "stringFilter": {"matchType": "EXACT", "value": "site.example", "caseSensitive": True}})
        self.assertEqual((body["limit"], body["offset"]), ("100", "0"))
        self.assertEqual(body["dimensions"], [{"name": "hostName"}, {"name": "landingPagePlusQueryString"}])
        with self.assertRaises(ValidationError):
            ga4_landing_report(property_id="../../other", approved_origin="https://site.example", day=day,
                offset=0, access_token="SECRET", resolver=resolve, connection_factory=factory)
        with self.assertRaises(ValidationError):
            ga4_landing_report(property_id="12345", approved_origin="https://site.example/path", day=day,
                offset=0, access_token="SECRET", resolver=resolve, connection_factory=factory)
        with self.assertRaises(ValidationError):
            ga4_landing_report(property_id="12345", approved_origin="https://site.example", day=day,
                offset=0, property_timezone="Not/A_Zone", access_token="SECRET",
                resolver=resolve, connection_factory=factory)

    def test_remote_denials_and_unsafe_dns_are_sanitized(self):
        for status, category in ((302, "redirect_denied"), (403, "authorization_unavailable"),
                                 (429, "quota_limited"), (503, "provider_unavailable")):
            resolve, factory, connection, _ = self.fake(body=b'{"error":"SECRET"}', status=status)
            with self.subTest(status=status), self.assertRaises(SearchConsoleTransportError) as error:
                ga4_admin_property_get(property_id="12345", access_token="SECRET",
                                       resolver=resolve, connection_factory=factory)
            self.assertEqual(error.exception.category, category)
            self.assertNotIn("SECRET", str(error.exception))
            self.assertTrue(connection.closed)
        resolve, factory, _, _ = self.fake(addresses=("127.0.0.1",))
        with self.assertRaises(SearchConsoleTransportError) as error:
            ga4_admin_property_get(property_id="12345", access_token="SECRET",
                                   resolver=resolve, connection_factory=factory)
        self.assertEqual(error.exception.category, "egress_denied")

    def test_property_scoped_compatibility_requires_every_expected_column_and_exact_host_filter(self):
        response = {"dimensionCompatibilities": [
            {"dimensionMetadata": {"apiName": name}, "compatibility": "COMPATIBLE"}
            for name in ("hostName", "landingPagePlusQueryString")],
            "metricCompatibilities": [
                {"metricMetadata": {"apiName": name}, "compatibility": "COMPATIBLE"}
                for name in ("sessions", "keyEvents", "totalRevenue")]}
        resolve, factory, connection, _ = self.fake(body=json.dumps(response).encode())
        self.assertTrue(ga4_check_landing_compatibility(property_id="12345", approved_origin="https://site.example",
            access_token="SECRET", resolver=resolve, connection_factory=factory))
        method, path, headers, raw = connection.requests[0]
        self.assertEqual((method, path), ("POST", "/v1beta/properties/12345:checkCompatibility"))
        self.assertNotIn("SECRET", path + raw.decode())
        self.assertEqual(json.loads(raw)["dimensionFilter"]["filter"]["stringFilter"]["value"], "site.example")
        self.assertEqual(headers["Authorization"], "Bearer SECRET")
        for bad in ([], response["metricCompatibilities"][:-1],
                    [{**response["metricCompatibilities"][0], "compatibility": "INCOMPATIBLE"},
                     *response["metricCompatibilities"][1:]]):
            resolve, factory, _, _ = self.fake(body=json.dumps({**response, "metricCompatibilities": bad}).encode())
            with self.assertRaises(ValidationError):
                ga4_check_landing_compatibility(property_id="12345", approved_origin="https://site.example",
                    access_token="SECRET", resolver=resolve, connection_factory=factory)

    def test_organic_channel_request_uses_same_exact_filter_for_compatibility_and_report(self):
        response = {"dimensionCompatibilities": [{"dimensionMetadata": {"apiName": name},
            "compatibility": "COMPATIBLE"} for name in (
                "hostName", "landingPagePlusQueryString", "sessionDefaultChannelGroup")],
            "metricCompatibilities": [{"metricMetadata": {"apiName": name},
                "compatibility": "COMPATIBLE"} for name in ("sessions", "keyEvents", "totalRevenue")]}
        resolver, factory, checked, _ = self.fake(body=json.dumps(response).encode())
        self.assertTrue(ga4_check_landing_compatibility(property_id="12345", approved_origin="https://site.example",
            report_kind="organic_search", access_token="SECRET", resolver=resolver, connection_factory=factory))
        chosen = json.loads(checked.requests[0][3])
        self.assertEqual(chosen["dimensionFilter"]["andGroup"]["expressions"][1], {"filter": {
            "fieldName": "sessionDefaultChannelGroup", "stringFilter": {
                "matchType": "EXACT", "value": "Organic Search", "caseSensitive": True}}})
        resolver, factory, reporting, _ = self.fake()
        ga4_landing_report(property_id="12345", approved_origin="https://site.example",
            report_kind="organic_search", day=timezone.now().date() - timedelta(days=5), offset=0,
            access_token="SECRET", resolver=resolver, connection_factory=factory)
        body = json.loads(reporting.requests[0][3])
        self.assertEqual(body["dimensionFilter"], chosen["dimensionFilter"])
        self.assertEqual(body["dimensions"], chosen["dimensions"])
