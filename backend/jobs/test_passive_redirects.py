import copy
import http.client
import io
import json
from unittest import TestCase
from unittest.mock import Mock, patch

from django.core.exceptions import ValidationError

from .passive_headers import MAX_BYTES, MAX_FIELDS
from .passive_redirects import MAX_REFERENCE, observe_response_location, observe_http_response_location


class PassiveRedirectTests(TestCase):
    URL = "https://security.example.invalid/public"

    def observe(self, fields, status=302, source_url=None):
        return observe_response_location(source_url=source_url or self.URL, status=status, fields=fields)

    def test_original_response_duplicate_fields_are_not_collapsed_or_followed_and_raw_data_is_not_copied(self):
        wire = (b"HTTP/1.1 302 Found\r\nLocation: http://private.invalid/?secret=value#private\r\n"
            b"lOcAtIoN: https://private.invalid/second\r\nSet-Cookie: private=secret\r\n\r\nprivate body")
        sock = Mock(); sock.makefile.return_value = io.BytesIO(wire)
        with http.client.HTTPResponse(sock) as response:
            response.begin(); fields = response.getheaders(); original = copy.deepcopy(fields)
            with patch("socket.create_connection", side_effect=AssertionError("No request")), patch("socket.getaddrinfo", side_effect=AssertionError("No DNS")):
                result = self.observe(fields, response.status)
            self.assertEqual(fields, original)
            self.assertEqual((result["response_status"], result["redirect_status"], result["location_state"]), (302, True, "multiple_fields"))
            self.assertEqual((result["target_scheme"], result["same_origin"]), (None, None))
            self.assertFalse(response.isclosed())  # No response body read.
        for raw in ("private", "secret", self.URL, "security.example.invalid", "digest"):
            self.assertNotIn(raw, json.dumps(result))
        self.assertIn("not_followed_chain", result["interpretation"])

    def test_unavailable_absent_empty_and_duplicate_remain_distinct_on_all_supported_statuses(self):
        for status in (200, 201, 300, 301, 302, 303, 304, 305, 306, 307, 308, 404, 599):
            for fields, state in ((None, None), ([], "absent"), ([("Location", " \t")], "present_empty"),
                ([("Location", ""), ("location", "")], "multiple_fields")):
                result = self.observe(fields, status)
                self.assertEqual(result["response_status"], status)
                self.assertEqual(result["redirect_status"], status in {301, 302, 303, 307, 308})
                self.assertEqual(result["location_state"], state)
                self.assertEqual(result["state"], "unavailable" if fields is None else "observed")
                self.assertIsNone(result["target_scheme"]); self.assertIsNone(result["same_origin"])
        location = self.observe([("Location", "/created")], 201)
        self.assertEqual((location["redirect_status"], location["location_state"], location["same_origin"]), (False, "single_classified", True))

    def test_transient_relative_network_path_scheme_and_origin_port_categories_never_grant_target_authority(self):
        for location, scheme, same in (("../other?secret=value#private", "https", True), ("?secret=value", "https", True),
            ("#private", "https", True), ("//security.example.invalid:443/", "https", True),
            ("HTTPS://SECURITY.EXAMPLE.INVALID/private", "https", True), ("https://security.example.invalid:444/", "https", False),
            ("//foreign.example.invalid/", "https", False), ("http://security.example.invalid/", "http", False),
            ("http://169.254.169.254/", "http", False), ("https://[::1]/", "https", False)):
            result = self.observe([("Location", location)])
            self.assertEqual((result["location_state"], result["target_scheme"], result["same_origin"]), ("single_classified", scheme, same), location)
            self.assertNotIn(location, json.dumps(result)); self.assertNotIn("secret", json.dumps(result))

    def test_unsupported_ambiguous_credentials_controls_bad_ports_and_percent_syntax_are_unclassified_null(self):
        for location in ("javascript:evil()", "data:text/html,private", "mailto:private@invalid", "https:/private", "https:private",
            "http:private", "///foreign.invalid/path", "//", "https://user:secret@foreign.invalid/", "https://@foreign.invalid/",
            "https://foreign.invalid:0/", "https://foreign.invalid:99999/", "https://foreign.invalid:/", "https://[::1",
            "https://bad host.invalid/", "https://foreign.invalid/with space", "https://foreign.invalid\\private",
            "https://foreign.invalid/%00", "/%0a", "/%5cprivate", "/%ZZ", "/%", "caf\xe9", "x\tx", "x" * (MAX_REFERENCE + 1)):
            result = self.observe([("Location", location)])
            self.assertEqual((result["location_state"], result["target_scheme"], result["same_origin"]), ("single_unclassified", None, None), location)
        self.assertEqual(self.observe([("Location", "/caf%C3%A9%20path")])["location_state"], "single_classified")
        for location in ('/<img>', '/"private"', '/{private}', '/private|x', '/^private', '/`private', '/[private]', '/?x=[private]', '/#[]'):
            self.assertEqual(self.observe([("Location", location)])["location_state"], "single_unclassified", location)

    def test_complete_original_header_syntax_status_and_source_boundaries_fail_without_raw_error_disclosure(self):
        for fields in ({"Location": "/private"}, iter([]), "private", [None], [("Location",)], [("Bad Name", "private")],
            [("Location", True)], [("Location", "x\r\nprivate")], [("X", "\x00")], [("X", "\x7f")], [("X", "\u2603")]):
            with self.assertRaises(ValidationError) as raised: self.observe(fields)
            self.assertNotIn("private", str(raised.exception))
        for status in (True, "302", None, 302.0, 199, 600):
            with self.assertRaises(ValidationError): self.observe([], status)
        for source_url in ("http://security.example.invalid/public", self.URL + "?", self.URL + "#", "https://user:secret@security.example.invalid/",
            "https://security.example.invalid:443/", "https://security.example.invalid", "https://security.example.invalid:444/"):
            with self.assertRaises(ValidationError): self.observe([], source_url=source_url)

    def test_exact_original_field_byte_and_reference_bounds_are_never_silent_truncation(self):
        self.assertEqual(self.observe([("X", "")] * MAX_FIELDS)["location_state"], "absent")
        with self.assertRaises(ValidationError): self.observe([("X", "")] * (MAX_FIELDS + 1))
        fields = [("X", "a" * 8192)] * 3
        remaining = MAX_BYTES - 3 * (8192 + 5) - 5
        self.assertEqual(self.observe([*fields, ("X", "a" * remaining)])["state"], "observed")
        with self.assertRaises(ValidationError): self.observe([*fields, ("X", "a" * (remaining + 1))])
        with self.assertRaises(ValidationError): self.observe([("Location", "x" * 8193)])
        self.assertEqual(self.observe([("Location", "/" + "a" * (MAX_REFERENCE - 1))])["location_state"], "single_classified")
        self.assertEqual(self.observe([("Location", "/" + "a" * MAX_REFERENCE)])["location_state"], "single_unclassified")


class PassiveHTTPRedirectTests(TestCase):
    URL = "http://security.example.invalid/public"

    def observe(self, fields, status=301, source_url=None):
        return observe_http_response_location(source_url=source_url or self.URL, status=status, fields=fields)

    def test_original_http_response_same_hostname_https_reference_never_follows_or_exposes_raw_metadata(self):
        wire = (b"HTTP/1.1 301 Moved Permanently\r\nLocation: https://security.example.invalid:443/private?secret=value#private\r\n"
            b"Set-Cookie: personal=secret\r\n\r\nprivate body")
        sock = Mock(); sock.makefile.return_value = io.BytesIO(wire)
        with http.client.HTTPResponse(sock) as response:
            response.begin(); fields = response.getheaders(); original = copy.deepcopy(fields)
            with patch("socket.create_connection", side_effect=AssertionError("No network")), patch("socket.getaddrinfo", side_effect=AssertionError("No DNS")):
                result = self.observe(fields, response.status)
            self.assertEqual(fields, original); self.assertFalse(response.isclosed())
        self.assertEqual(result["method_version"], "passive-http-response-location-v1")
        self.assertEqual((result["redirect_status"], result["target_scheme"], result["same_origin"], result["same_hostname_default_https"]), (True, "https", False, True))
        for raw in ("secret", "personal", "private", "security.example.invalid", "digest", self.URL): self.assertNotIn(raw, json.dumps(result))
        self.assertIn("not_observed_https_followed_upgrade", result["interpretation"])
        result["same_hostname_default_https"] = False
        self.assertTrue(self.observe(fields)["same_hostname_default_https"])

    def test_http_original_scheme_origin_default_https_reference_and_status_are_independent(self):
        for reference, scheme, origin, counterpart in (("/relative", "http", True, False), ("//security.example.invalid:80/", "http", True, False),
            ("http://security.example.invalid:80/", "http", True, False), ("http://security.example.invalid:8080/", "http", False, False),
            ("https://security.example.invalid/", "https", False, True), ("HTTPS://SECURITY.EXAMPLE.INVALID:443/", "https", False, True),
            ("https://security.example.invalid:444/", "https", False, False), ("https://other.example.invalid/", "https", False, False),
            ("https://169.254.169.254/", "https", False, False), ("https://[::1]/", "https", False, False)):
            for status in (200, 301, 302, 303, 304, 307, 308, 404, 599):
                result = self.observe([("Location", reference)], status)
                self.assertEqual((result["target_scheme"], result["same_origin"], result["same_hostname_default_https"]), (scheme, origin, counterpart), reference)
                self.assertEqual(result["redirect_status"], status in {301, 302, 303, 307, 308})
                self.assertNotIn(reference, json.dumps(result))

    def test_http_missing_duplicate_unclassified_and_exact_original_bounds_never_become_zero_upgrade_proof(self):
        for fields, state in ((None, None), ([], "absent"), ([("Location", " \t")], "present_empty"),
            ([("Location", "https://security.example.invalid/"), ("LOCATION", "/other")], "multiple_fields"),
            ([("Location", "https://user:secret@security.example.invalid/")], "single_unclassified"),
            ([("Location", "//")], "single_unclassified"), ([("Location", "/%ZZ")], "single_unclassified"),
            ([("Location", "x" * (MAX_REFERENCE + 1))], "single_unclassified")):
            result = self.observe(fields)
            self.assertEqual(result["location_state"], state)
            self.assertEqual((result["target_scheme"], result["same_origin"], result["same_hostname_default_https"]), (None, None, None))
            self.assertEqual(result["state"], "unavailable" if fields is None else "observed")
        self.assertEqual(self.observe([("X", "")] * MAX_FIELDS)["location_state"], "absent")
        with self.assertRaises(ValidationError): self.observe([("X", "")] * (MAX_FIELDS + 1))
        maximum = "http://security.example.invalid/"; maximum += "x" * (1024 - len(maximum))
        self.assertEqual(self.observe([], source_url=maximum)["state"], "observed")
        with self.assertRaises(ValidationError): self.observe([], source_url=maximum + "x")

    def test_http_source_canonical_and_original_types_fail_generically_while_https_entrypoint_keeps_http_denial(self):
        for url in ("https://security.example.invalid/", "HTTP://security.example.invalid/", "http://SECURITY.EXAMPLE.INVALID/", "http://security.example.invalid",
            "http://security.example.invalid:80/", "http://security.example.invalid:443/", "http://security.example.invalid:8080/",
            "http://user:secret@security.example.invalid/", self.URL + "?", self.URL + "#", self.URL + "?secret=value", self.URL + " ", self.URL + "\\x"):
            with self.subTest(url=url), self.assertRaises(ValidationError) as raised: self.observe([], source_url=url)
            self.assertNotIn("secret", str(raised.exception))
        for value in (None, True, 123, [], {}):
            with self.assertRaises(ValidationError): observe_http_response_location(source_url=value, status=301, fields=[])
        for fields in ({"Location": "/secret"}, iter([]), [("Location", "x\r\nsecret")], [("Location", True)], [("X", "\u2603")]):
            with self.assertRaises(ValidationError): self.observe(fields)
        for status in (True, "301", None, 301.0, 199, 600):
            with self.assertRaises(ValidationError): self.observe([], status)
        with self.assertRaises(ValidationError): observe_response_location(source_url=self.URL, status=301, fields=[])
