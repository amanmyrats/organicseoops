from copy import deepcopy
from html import escape
import json
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from . import competitor_date_candidates as candidates, competitor_dates as dates


class CompetitorDateCandidateTests(SimpleTestCase):
    def original(self, values=(), **changes):
        body = b'<p>private-contact@example.invalid</p>' + ''.join(
            f'<meta property="article:{"published_time" if index % 2 == 0 else "modified_time"}" content="{escape(value, quote=True)}">'
            for index, value in enumerate(values)).encode()
        return dates.observe_static_dates(**{**dict(body=body, body_complete=True, url="https://competitor.example.invalid/article",
            observed_at="2026-01-01T00:00:00.000001+00:00"), **changes})

    def read(self, values):
        return candidates.article_date_literal_candidates(self.original(values))

    def test_original_order_duplicates_properties_integrity_fresh_copy_private_and_no_io(self):
        original = self.original(["2024-02-29", "2024-02-29", "2026-01-01T00:00:00.000001Z"])
        before = deepcopy(original)
        with patch("socket.getaddrinfo", side_effect=AssertionError("No DNS")), patch("builtins.open", side_effect=AssertionError("No files")):
            result = candidates.article_date_literal_candidates(original)
        self.assertEqual(set(result), {"method_version", "evidence", "candidates", "interpretation"})
        self.assertEqual(result["method_version"], candidates.METHOD); self.assertEqual(result["interpretation"], candidates.INTERPRETATION)
        self.assertEqual(result["evidence"], original); self.assertEqual(original, before)
        self.assertEqual([item["declaration_index"] for item in result["candidates"]], [0, 1, 2])
        self.assertEqual([item["state"] for item in result["candidates"]], ["calendar_literal", "calendar_literal", "offset_literal"])
        self.assertFalse(result["candidates"][2]["after_observation"])
        self.assertNotIn("private-contact", json.dumps(result)); self.assertIn("not_validated_publication_change_age_freshness", result["interpretation"])
        result["evidence"]["declarations"].clear(); result["candidates"][0]["calendar_date"] = "2099-01-01"
        self.assertEqual(original, before); self.assertEqual(candidates.article_date_literal_candidates(original)["candidates"][0]["calendar_date"], "2024-02-29")
        self.assertEqual(dates.parse_dates(dates.encode_dates(original)), before)

    def test_known_offsets_rollover_lossless_microseconds_and_literal_after_observation_only(self):
        result = self.read(["2026-01-01T03:00:00.000001+03:00", "2025-12-31T19:00:00.000001-05:00",
            "2026-01-01T00:00:00.000002Z", "2026-01-01T00:00:00+00:00", "2026-01-01T01:30:00.1+01:30"])
        self.assertEqual([item["utc_instant"] for item in result["candidates"]], [
            "2026-01-01T00:00:00.000001+00:00", "2026-01-01T00:00:00.000001+00:00",
            "2026-01-01T00:00:00.000002+00:00", "2026-01-01T00:00:00.000000+00:00", "2026-01-01T00:00:00.100000+00:00"])
        self.assertEqual([item["after_observation"] for item in result["candidates"]], [False, False, True, False, True])
        self.assertTrue(all(item["calendar_date"] is None for item in result["candidates"]))

    def test_calendar_only_never_infers_instant_timezone_future_or_publishing_truth(self):
        result = self.read(["2024-02-29", "2099-01-01"])
        for item, value in zip(result["candidates"], ("2024-02-29", "2099-01-01")):
            self.assertEqual(item["state"], "calendar_literal"); self.assertEqual(item["calendar_date"], value)
            self.assertIsNone(item["utc_instant"]); self.assertIsNone(item["after_observation"])
            self.assertEqual(set(item), {"declaration_index", "state", "calendar_date", "utc_instant", "after_observation"})

    def test_invalid_unsupported_naive_unknown_offset_leap_second_truncated_and_overflow_are_unknown(self):
        values = ["", "2025-02-29", "2026-13-01", "0000-01-01", "2026-01-01T24:00:00Z", "2026-01-01T00:60:00Z",
            "2026-01-01T00:00:60Z", "2026-01-01T00:00:00+01:60", "2026-01-01T00:00:00+24:00",
            "2026-01-01T00:00:00-00:00", "2026-01-01T00:00:00", "2026-01-01t00:00:00z",
            "2026-01-01T00:00:00.1234567Z", "2026-W01-1", "20260101", "Tomorrow & not verified",
            "9999-12-31T23:59:59-01:00", "0001-01-01T00:00:00+01:00"]
        for value in values:
            with self.subTest(value=value):
                row = self.read([value])["candidates"][0]
                self.assertEqual(row["state"], "unsupported_literal")
                self.assertTrue(all(row[key] is None for key in ("calendar_date", "utc_instant", "after_observation")))
        original = self.original(["2026-01-01"]); original["declarations"][0]["truncated"] = True
        self.assertEqual(candidates.article_date_literal_candidates(original)["candidates"][0],
            {"declaration_index": 0, "state": "truncated_literal", "calendar_date": None, "utc_instant": None, "after_observation": None})
        self.assertEqual(self.read(["2026-01-01" + "x" * 80])["candidates"][0]["state"], "truncated_literal")

    def test_observed_empty_and_whole_unavailable_preserve_original_zero_vs_unknown_and_bounded_packet(self):
        self.assertEqual(self.read([])["candidates"], [])
        original = self.original(body=b"<title>Unclosed")
        result = candidates.article_date_literal_candidates(original)
        self.assertIsNone(result["candidates"]); self.assertEqual(result["evidence"], original)
        original = self.original(["2026-01-01T00:00:00.123456Z"] * 10)
        self.assertEqual(len(candidates.article_date_literal_candidates(original)["candidates"]), 10)
        self.assertLessEqual(len(json.dumps(candidates.article_date_literal_candidates(original)).encode()), candidates.MAX_RESULT_BYTES)
        with patch.object(candidates, "MAX_RESULT_BYTES", 1), self.assertRaises(ValidationError): candidates.article_date_literal_candidates(original)

    def test_strict_original_family_private_fields_types_unknown_and_corrupt_source_rejected(self):
        original = self.original(["2026-01-01"])
        for mutate in (lambda v: v.update(raw_body="private"), lambda v: v.update(method_version=candidates.METHOD),
            lambda v: v.update(body_size_bytes=True), lambda v: v.update(declarations=None),
            lambda v: v["declarations"][0].update(truncated=1), lambda v: v["declarations"][0].update(value=1),
            lambda v: v["declarations"][0].update(property="datePublished")):
            value = deepcopy(original); mutate(value)
            with self.assertRaises(ValidationError): candidates.article_date_literal_candidates(value)
