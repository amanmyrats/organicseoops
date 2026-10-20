import copy
import json
from unittest import TestCase
from unittest.mock import patch

from django.core.exceptions import ValidationError

from .passive_headers import MAX_BYTES, MAX_FIELDS, SELECTED_HEADERS, observe_response_headers


class PassiveHeaderTests(TestCase):
    def test_complete_duplicate_headers_and_separate_cookies_are_minimized_without_side_effects(self):
        fields = [("Strict-Transport-Security", "max-age=31536000; includeSubDomains"),
            ("Content-Security-Policy", "default-src 'self'; script-src 'nonce-private-nonce'"),
            ("Content-Security-Policy", "connect-src https://private-report.example.invalid"),
            ("Content-Security-Policy-Report-Only", "report-to private-report"),
            ("Server", "private-software/123"), ("X-Powered-By", "private-framework"),
            ("X-Frame-Options", ""), ("Referrer-Policy", " \t"),
            ("Set-Cookie", "secret-session=private-token; Secure; HttpOnly; SameSite=Lax; Path=/private"),
            ("Set-Cookie", 'quoted="private-second"; Expires=Wed, 21 Oct 2037 07:28:00 GMT'),
            ("X-Private-Customer", "private-customer-value")]
        original = copy.deepcopy(fields)
        with patch("socket.create_connection", side_effect=AssertionError("network")), patch("django.core.mail.send_mail", side_effect=AssertionError("SMTP")):
            result = observe_response_headers(fields)
        self.assertEqual(fields, original)
        self.assertEqual(result["headers"]["content-security-policy"], "multiple_fields")
        self.assertEqual(result["headers"]["content-security-policy-report-only"], "present_nonempty")
        self.assertEqual(result["headers"]["x-frame-options"], "present_empty")
        self.assertEqual(result["headers"]["referrer-policy"], "present_empty")
        self.assertEqual(result["cookies"], {"observed_fields": 2, "parsed_fields": 2, "unclassified_fields": 0,
            "without_secure": 1, "without_httponly": 1, "without_recognized_samesite": 1})
        self.assertNotIn("private", json.dumps(result)); self.assertNotIn("secret-session", json.dumps(result))
        self.assertNotIn("source_digest", result)

    def test_unavailable_is_not_absence_and_collapsed_or_bad_header_inputs_are_rejected(self):
        unavailable = observe_response_headers(None)
        self.assertEqual((unavailable["state"], unavailable["headers"], unavailable["cookies"]), ("unavailable", None, None))
        empty = observe_response_headers([])
        self.assertEqual(empty["state"], "observed")
        self.assertEqual(set(empty["headers"]), set(SELECTED_HEADERS))
        self.assertEqual(set(empty["headers"].values()), {"absent"})
        self.assertEqual(empty["cookies"]["observed_fields"], 0)
        for fields in ({"set-cookie": "secret=one"}, iter([]), "private", [None], [("private",)],
                [("bad name", "value")], [("name:", "value")], [("Name", True)], [("Name", "x\r\nInjected: private")],
                [("Name", "\x00")], [("Name", "\x7f")], [("Name", "☃")]):
            with self.assertRaises(ValidationError) as raised: observe_response_headers(fields)
            self.assertNotIn("private", str(raised.exception))

    def test_exact_complete_field_and_byte_bounds_never_silently_truncate(self):
        self.assertEqual(observe_response_headers([("X", "")] * MAX_FIELDS)["state"], "observed")
        with self.assertRaises(ValidationError): observe_response_headers([("X", "")] * (MAX_FIELDS + 1))
        fields = [("X", "a" * 8192)] * 3
        remaining = MAX_BYTES - 3 * (8192 + 5) - 5
        self.assertEqual(observe_response_headers([*fields, ("X", "a" * remaining)])["state"], "observed")
        with self.assertRaises(ValidationError): observe_response_headers([*fields, ("X", "a" * (remaining + 1))])
        with self.assertRaises(ValidationError): observe_response_headers([("X", "a" * 8193)])

    def test_unknown_folded_duplicate_and_nonflag_cookie_syntax_stays_unclassified(self):
        values = ("", "private", "a=1, b=2", "a=1; b=2", "a=1; Secure=1", "a=1; HttpOnly=false",
            "a=1; Secure; secure", "a=1; SameSite=Lax; SameSite=None", 'a="x;y"', "a=1; unsupported=private")
        result = observe_response_headers([("Set-Cookie", value) for value in values])
        self.assertEqual(result["cookies"], {"observed_fields": len(values), "parsed_fields": 0,
            "unclassified_fields": len(values), "without_secure": 0, "without_httponly": 0, "without_recognized_samesite": 0})

    def test_flag_counts_never_assert_cookie_purpose_acceptance_or_header_effectiveness(self):
        result = observe_response_headers([("Set-Cookie", "__Secure-id=x; sEcUrE; hTtPoNlY; SameSite=nOnE"),
            ("Set-Cookie", "id=x; SameSite=unknown"), ("Content-Security-Policy-Report-Only", "default-src 'none'"),
            ("Strict-Transport-Security", "malformed private policy")])
        self.assertEqual(result["cookies"]["parsed_fields"], 2)
        self.assertEqual(result["cookies"]["without_secure"], 1)
        self.assertEqual(result["cookies"]["without_recognized_samesite"], 1)
        self.assertEqual(result["headers"]["content-security-policy"], "absent")
        self.assertEqual(result["headers"]["strict-transport-security"], "present_nonempty")
        self.assertIn("not_policy_effectiveness", result["interpretation"])
        self.assertNotIn("private", json.dumps(result))
