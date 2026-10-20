from copy import deepcopy
from hashlib import sha256
import json
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from django.utils import timezone

from . import competitor_dates as dates, competitor_metadata as metadata


class CompetitorDateTests(SimpleTestCase):
    def observe(self, body=b"<p>No retained date declaration</p>", **changes):
        return dates.observe_static_dates(**({"body": body, "body_complete": True,
            "url": "https://competitor.example.invalid/article", "observed_at": timezone.now().isoformat(timespec="microseconds")} | changes))

    def test_original_order_duplicates_literal_values_byte_integrity_privacy_fresh_readback_and_no_io(self):
        body = (b'\xef\xbb\xbf<title>Private title</title><p>private@example.invalid</p>'
            b'<meta property="article:modified_time" content="  Tomorrow &amp;\n not verified  " data-private="secret">'
            b'<meta property="article:published_time" content="2099-01-01T00:00:00Z">'
            b'<meta property="article:modified_time" content="Tomorrow &amp; not verified">')
        with patch("socket.getaddrinfo", side_effect=AssertionError("No DNS")), patch("builtins.open", side_effect=AssertionError("No files")):
            result = self.observe(body)
        self.assertEqual(result["declarations"], [
            {"property": "article:modified_time", "value": "Tomorrow & not verified", "truncated": False},
            {"property": "article:published_time", "value": "2099-01-01T00:00:00Z", "truncated": False},
            {"property": "article:modified_time", "value": "Tomorrow & not verified", "truncated": False}])
        self.assertEqual((result["body_sha256"], result["body_size_bytes"]), (sha256(body).hexdigest(), len(body)))
        for private in ("Private title", "private@", "secret", "data-private", "age_days", "published_at"):
            self.assertNotIn(private, json.dumps(result))
        content = dates.encode_dates(result); stored = dates.parse_dates(content); stored["declarations"].clear()
        self.assertEqual(dates.parse_dates(content), result)
        old = metadata.observe_static_metadata(body=body, body_complete=True, url=result["url"], observed_at=result["observed_at"])
        self.assertNotIn("declarations", old); self.assertEqual(old["metadata"]["title"], "Private title")

    def test_exact_properties_only_inert_rawtext_foreign_exclusions_and_empty_declared_value(self):
        for container in sorted(metadata.EXCLUDED):
            body = f'<{container}><meta property="article:published_time" content="Hidden"></{container}>'.encode()
            result = self.observe(body)
            if container == "plaintext":
                self.assertEqual(result["state"], "unavailable"); self.assertIsNone(result["declarations"])
            else: self.assertEqual(result["declarations"], [], container)
        ignored = self.observe(b'<meta name="article:published_time" content="Hidden"><meta property="og:updated_time" content="Hidden">'
            b'<time datetime="2020-01-01">Hidden</time><script type="application/ld+json">{"datePublished":"Hidden"}</script>')
        self.assertEqual(ignored["state"], "observed"); self.assertEqual(ignored["declarations"], [])
        empty = self.observe(b'<meta property="article:published_time" content="">')
        self.assertEqual(empty["declarations"], [{"property": "article:published_time", "value": "", "truncated": False}])

    def test_duplicate_attributes_missing_content_incomplete_and_shared_ambiguous_markup_are_whole_unknown(self):
        for body in (b'<meta property="article:published_time" property="unknown" content="a">',
            b'<meta property="unknown" property="article:published_time" content="a">',
            b'<meta property="article:published_time" content="a" content="b">', b'<meta property="article:modified_time">',
            b'<meta property="article:modified_time" content>', b'<meta property="article:modified_time" content="a"',
            b'<template><meta property="article:modified_time" content="a">', b'<title>Unclosed', b'<p><!--incomplete'):
            with self.subTest(body=body):
                result = self.observe(body); self.assertEqual((result["state"], result["reason"]), ("unavailable", "ambiguous_markup"))
                self.assertIsNone(result["declarations"]); self.assertEqual(result["body_sha256"], sha256(body).hexdigest())

    def test_exact_occurrence_unicode_value_element_and_result_limits_never_return_partial_declarations(self):
        tag = b'<meta property="article:published_time" content="2020-01-01">'
        self.assertEqual(len(self.observe(tag * 10)["declarations"]), 10)
        for body, reason in ((tag * 11, "declaration_limit"), (b'<a href="/">x</a>' * 1001, "element_limit")):
            result = self.observe(body); self.assertEqual((result["state"], result["reason"]), ("unavailable", reason)); self.assertIsNone(result["declarations"])
        for length in (80, 81):
            result = self.observe(('<meta property="article:modified_time" content="' + "🙂" * length + '">').encode())
            self.assertEqual(result["declarations"], [{"property": "article:modified_time", "value": "🙂" * 80, "truncated": length == 81}])
        body = ('<meta property="article:modified_time" content="' + "🙂" * 80 + '">').encode() * 10
        with patch.object(metadata, "MAX_RESULT_BYTES", 1200): result = self.observe(body)
        self.assertEqual((result["state"], result["reason"]), ("unavailable", "result_limit")); self.assertIsNone(result["declarations"])

    def test_original_complete_utf8_body_canonical_uri_real_types_and_observation_date_required(self):
        for changes in ({"body_complete": False}, {"body_complete": 1}, {"body": "<meta>"}, {"body": b""},
            {"body": b"x" * 131073}, {"body": b"\xff"}, {"body": b"x\x00"}, {"url": "https://user:secret@competitor.example.invalid/"},
            {"url": "https://competitor.example.invalid/?token=private"}, {"observed_at": "2026-02-30T00:00:00.000001+00:00"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError): self.observe(**changes)

    def test_closed_strict_readback_shapes_unknown_null_duplicate_nonfinite_and_byte_limits(self):
        original = self.observe(b'<meta property="article:published_time" content="2020-01-01">')
        mutations = [lambda v: v.update(raw_body="private"), lambda v: v.update(method_version=metadata.METHOD),
            lambda v: v.update(interpretation="verified_freshness"), lambda v: v.update(excluded_containers=[]),
            lambda v: v.update(body_size_bytes=True), lambda v: v.update(declarations=None),
            lambda v: v["declarations"][0].update(property="datePublished"), lambda v: v["declarations"][0].update(property=True),
            lambda v: v["declarations"][0].update(value="x" * 81), lambda v: v["declarations"][0].update(value=" leading"),
            lambda v: v["declarations"][0].update(value="bad\x7f"), lambda v: v["declarations"][0].update(truncated=1),
            lambda v: v["declarations"][0].update(value="", truncated=True), lambda v: v["declarations"][0].update(age=1),
            lambda v: v.update(state="unavailable", reason="declaration_limit")]
        for mutate in mutations:
            value = deepcopy(original); mutate(value)
            with self.assertRaises(ValidationError): dates.encode_dates(value)
        for content in (b'{"state":1,"state":2}', b'{"value":NaN}', b"[]", b"\xff", b"x" * 8193):
            with self.assertRaises(ValidationError): dates.parse_dates(content)
