import copy
import json
from datetime import UTC, datetime, timedelta, timezone
from unittest import TestCase
from unittest.mock import patch

from django.core.exceptions import ValidationError

from .passive_certificate import observe_peer_certificate_dates


class PassiveCertificateTests(TestCase):
    START = datetime(2024, 2, 29, 12, tzinfo=UTC)
    END = datetime(2024, 3, 1, 12, tzinfo=UTC)
    CERTIFICATE = {"notBefore": "Feb 29 12:00:00 2024 GMT", "notAfter": "Mar  1 12:00:00 2024 GMT"}

    def test_inclusive_original_window_and_exact_signed_microseconds(self):
        for date, position, remaining in (
            (self.START - timedelta(microseconds=1), "before_reported_window", "86400000001"),
            (self.START, "within_reported_window", "86400000000"),
            (self.END - timedelta(microseconds=1), "within_reported_window", "1"),
            (self.END, "within_reported_window", "0"),
            (self.END + timedelta(microseconds=1), "after_reported_window", "-1"),
        ):
            with self.subTest(date=date):
                result = observe_peer_certificate_dates(self.CERTIFICATE, observed_at=date)
                self.assertEqual((result["state"], result["position"], result["remaining_microseconds"]),
                                 ("observed", position, remaining))
                self.assertEqual(result["not_before"], self.START.isoformat(timespec="microseconds"))
                self.assertEqual(result["not_after"], self.END.isoformat(timespec="microseconds"))
        same = {"notBefore": self.CERTIFICATE["notAfter"], "notAfter": self.CERTIFICATE["notAfter"]}
        self.assertEqual(observe_peer_certificate_dates(same, observed_at=self.END)["position"], "within_reported_window")

    def test_timezone_is_normalized_without_rounding_or_local_timezone_dependence(self):
        date = (self.END - timedelta(microseconds=123456)).astimezone(timezone(timedelta(hours=5, minutes=30)))
        result = observe_peer_certificate_dates(self.CERTIFICATE, observed_at=date)
        self.assertEqual(result["remaining_microseconds"], "123456")
        self.assertEqual(result["observed_at"], "2024-03-01T11:59:59.876544+00:00")

    def test_missing_unsupported_reversed_or_impossible_dates_remain_unavailable(self):
        bad_dates = (None, True, 0, b"Feb 29 12:00:00 2024 GMT", "", "private" * 10000,
            "Feb 29 12:00:00 2023 GMT", "Apr 31 12:00:00 2024 GMT", "Mar  0 12:00:00 2024 GMT",
            "Mar 32 12:00:00 2024 GMT", "Mar  1 24:00:00 2024 GMT", "Mar  1 12:60:00 2024 GMT",
            "Mar  1 12:00:60 2024 GMT", "Mar  1 12:00:00 0000 GMT", "Mar 01 12:00:00 2024 GMT",
            "Mar 1 12:00:00 2024 GMT", "mar  1 12:00:00 2024 GMT", "Mar  1 12:00:00 2024 UTC",
            "Mar  1 12:00:00 2024 GMT\n", "Mar  1 12:00:00 2024 GMT\x00", "Mär  1 12:00:00 2024 GMT")
        inputs = [None, {}, [], "private", {"notBefore": self.CERTIFICATE["notAfter"],
            "notAfter": self.CERTIFICATE["notBefore"]}]
        for key in ("notBefore", "notAfter"):
            inputs.extend({**self.CERTIFICATE, key: value} for value in bad_dates)
            inputs.append({name: value for name, value in self.CERTIFICATE.items() if name != key})
        for certificate in inputs:
            with self.subTest(certificate=certificate):
                result = observe_peer_certificate_dates(certificate, observed_at=self.START)
                self.assertEqual(result["state"], "unavailable")
                for key in ("not_before", "not_after", "position", "remaining_microseconds"):
                    self.assertIsNone(result[key])
                self.assertNotIn("private", json.dumps(result))

    def test_extreme_supported_calendar_bounds_do_not_use_float_microseconds(self):
        certificate = {"notBefore": "Jan  1 00:00:00 0001 GMT", "notAfter": "Dec 31 23:59:59 9999 GMT"}
        result = observe_peer_certificate_dates(certificate, observed_at=datetime(1, 1, 1, 0, 0, 0, 1, tzinfo=UTC))
        self.assertEqual(result["state"], "observed")
        self.assertEqual(result["remaining_microseconds"], "315537897598999999")
        with patch("jobs.passive_certificate.ssl.cert_time_to_seconds", side_effect=ValueError("private")):
            self.assertEqual(observe_peer_certificate_dates(self.CERTIFICATE, observed_at=self.START)["state"], "unavailable")
        with patch("jobs.passive_certificate.ssl.cert_time_to_seconds", return_value=0):
            self.assertEqual(observe_peer_certificate_dates(self.CERTIFICATE, observed_at=self.START)["state"], "unavailable")

    def test_bad_or_future_observation_date_is_rejected_with_generic_error(self):
        for date in (None, True, "private", datetime(2024, 1, 1), datetime.now(UTC) + timedelta(days=1)):
            with self.assertRaises(ValidationError) as raised:
                observe_peer_certificate_dates(self.CERTIFICATE, observed_at=date)
            self.assertNotIn("private", str(raised.exception))

    def test_identity_bytes_and_links_are_never_copied_hashed_or_used(self):
        certificate = {**self.CERTIFICATE, "subject": ((('commonName', 'private-customer'),),),
            "issuer": "private-issuer", "subjectAltName": (("DNS", "private.example.invalid"),),
            "serialNumber": "private-serial", "DER": b"private-der", "PEM": "private-pem",
            "OCSP": ("http://127.0.0.1/private",), "crlDistributionPoints": ("http://169.254.169.254/private",),
            "caIssuers": ("https://private.example.invalid",)}
        original = copy.deepcopy(certificate)
        with patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("socket.getaddrinfo", side_effect=AssertionError("DNS")), \
                patch("hashlib.sha256", side_effect=AssertionError("raw digest")):
            result = observe_peer_certificate_dates(certificate, observed_at=self.START)
        self.assertEqual(certificate, original)
        self.assertEqual(set(result), {"method_version", "coverage", "interpretation", "observed_at", "state",
            "not_before", "not_after", "position", "remaining_microseconds"})
        self.assertNotIn("private", json.dumps(result))
        self.assertIn("not_tls_chain_hostname_revocation_validation", result["interpretation"])
