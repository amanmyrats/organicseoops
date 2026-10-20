import copy
import http.client
import io
import json
from unittest.mock import Mock, patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from .passive_headers import MAX_BYTES, MAX_FIELDS
from .passive_redirects import MAX_REFERENCE, resolve_permitted_response_location


class PermittedResponseLocationTests(SimpleTestCase):
    HTTP = "http://security.example.invalid/public"
    HTTPS = "https://security.example.invalid/public"

    def selection(self, **changes):
        return {"url": self.HTTP, "target_urls": [self.HTTPS, "https://security.example.invalid/other"],
            "observations": ["redirect_chain"], "collection_permission": True, **changes}

    def resolve(self, fields, **changes):
        return resolve_permitted_response_location(**{**dict(selection=self.selection(), current_url=self.HTTP,
            status=301, fields=fields), **changes})

    def test_original_http_response_exact_selected_next_url_no_body_read_io_raw_header_or_mutation(self):
        wire = (b"HTTP/1.1 301 Moved\r\nLocation: https://security.example.invalid:443/public\r\n"
            b"Set-Cookie: personal=secret\r\nX-Server: private\r\n\r\nprivate body")
        sock = Mock(); sock.makefile.return_value = io.BytesIO(wire)
        with http.client.HTTPResponse(sock) as response:
            response.begin(); fields = response.getheaders(); original = copy.deepcopy(fields); data = self.selection()
            with patch("socket.create_connection", side_effect=AssertionError("No network")), patch("socket.getaddrinfo", side_effect=AssertionError("No DNS")):
                result = self.resolve(fields, status=response.status, selection=data)
            self.assertEqual((result["state"], result["next_url"]), ("permitted_target", self.HTTPS))
            self.assertEqual(result["response_location"]["method_version"], "passive-http-response-location-v1")
            self.assertEqual(fields, original); self.assertEqual(data, self.selection()); self.assertFalse(response.isclosed())
        for private in ("secret", "personal", "private", ":443", "digest", "cookie"):
            self.assertNotIn(private, json.dumps(result))
        self.assertIn("not_verified_target_observed_chain", result["interpretation"])
        result["response_location"]["same_hostname_default_https"] = False
        self.assertTrue(self.resolve(fields)["response_location"]["same_hostname_default_https"])

    def test_relative_default_port_exact_paths_each_scheme_and_original_url_for_later_loop_detection(self):
        for current, reference, expected in ((self.HTTP, "HTTPS://SECURITY.EXAMPLE.INVALID:443/public", self.HTTPS),
            (self.HTTPS, "/other", "https://security.example.invalid/other"),
            (self.HTTPS, "../public", self.HTTPS), (self.HTTPS, "http://security.example.invalid:80/public", self.HTTP),
            (self.HTTPS, "//security.example.invalid:443/public", self.HTTPS),
            ("https://security.example.invalid/other", "public", self.HTTPS)):
            for status in (301, 302, 303, 307, 308):
                with self.subTest(current=current, reference=reference, status=status):
                    result = self.resolve([("Location", reference)], current_url=current, status=status)
                    self.assertEqual((result["state"], result["next_url"]), ("permitted_target", expected))
        for reference in ("/unselected", "https://foreign.example.invalid/private", "http://169.254.169.254/private", "https://[::1]/private"):
            result = self.resolve([("Location", reference)])
            self.assertEqual((result["state"], result["next_url"]), ("outside_exact_target_allowlist", None))
            self.assertNotIn(reference, json.dumps(result))

    def test_missing_ambiguous_unknown_and_nonredirect_responses_do_not_supply_a_next_request(self):
        for fields, state in ((None, None), ([], "absent"), ([("Location", " \t")], "present_empty"),
            ([("Location", "/one"), ("location", "/other")], "multiple_fields"),
            ([("Location", "https://user:secret@security.example.invalid/public")], "single_unclassified"),
            ([("Location", "//")], "single_unclassified")):
            result = self.resolve(fields)
            self.assertEqual((result["state"], result["next_url"], result["response_location"]["location_state"]), ("location_unavailable", None, state))
            self.assertNotIn("secret", json.dumps(result))
        for status in (200, 201, 300, 304, 305, 306, 404, 599):
            result = self.resolve([("Location", self.HTTPS)], status=status)
            self.assertEqual((result["state"], result["next_url"]), ("terminal_response", None))
        self.assertEqual(self.resolve(None, status=200)["state"], "location_unavailable")

    def test_raw_query_fragment_even_empty_custom_ports_and_unsafe_references_cannot_become_permitted_urls(self):
        for reference in (self.HTTPS + "?", self.HTTPS + "#", self.HTTPS + "?secret=value", self.HTTPS + "#private",
            "?", "#", "https://security.example.invalid:444/public", "http://security.example.invalid:8080/public"):
            result = self.resolve([("Location", reference)])
            self.assertEqual((result["state"], result["next_url"]), ("unsupported_target", None), reference)
            self.assertNotIn("secret", json.dumps(result)); self.assertNotIn("private", json.dumps(result))
        for reference in ("///foreign.invalid/public", "https:/private", "/%ZZ", "/%0A", "/%5cprivate", "https://security.example.invalid:/public",
            "https://security.example.invalid:0/public", "https://security.example.invalid:99999/public", "/with space", "\\private",
            "/<private>", "/[private]", "javascript:private()", "private\tvalue", "x" * (MAX_REFERENCE + 1)):
            result = self.resolve([("Location", reference)])
            self.assertEqual((result["state"], result["next_url"]), ("location_unavailable", None), reference)
        data = self.selection(target_urls=["https://security.example.invalid/caf%C3%A9%20path"])
        result = self.resolve([("Location", data["target_urls"][0])], selection=data)
        self.assertEqual(result["next_url"], data["target_urls"][0])

    def test_unselected_current_response_exact_input_and_original_field_status_bounds_fail_generically(self):
        for current in (None, True, self.HTTP + "?", self.HTTPS + "/unselected", "https://foreign.example.invalid/public"):
            with self.assertRaises(ValidationError): self.resolve([], current_url=current)
        for data in (None, {}, self.selection(collection_permission=1), self.selection(observations=["response_location"]),
            self.selection(target_urls=[self.HTTP]), self.selection(target_urls=[self.HTTPS] * 6)):
            with self.assertRaises(ValidationError): self.resolve([], selection=data)
        for fields in ({"Location": self.HTTPS}, iter([]), [None], [("Location", True)], [("X", "private\r\n")],
            [("X", "a" * MAX_BYTES)], [("X", "")] * (MAX_FIELDS + 1)):
            with self.assertRaises(ValidationError) as raised: self.resolve(fields)
            self.assertNotIn("private", str(raised.exception))
        self.assertEqual(self.resolve([("X", "")] * MAX_FIELDS)["state"], "location_unavailable")
        for status in (None, True, "301", 301.0, 199, 600):
            with self.assertRaises(ValidationError): self.resolve([], status=status)
