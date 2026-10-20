from datetime import timedelta
from hashlib import sha256
import json
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from django.utils import timezone

from . import competitor_metadata as metadata


class CompetitorMetadataTests(SimpleTestCase):
    def observe(self, body=b"<p>No selected metadata</p>", **changes):
        return metadata.observe_static_metadata(body=body, body_complete=True, url="https://competitor.example.invalid/article",
            observed_at=timezone.now().isoformat(timespec="microseconds"), **changes)

    def test_original_byte_integrity_date_minimized_metadata_counts_and_no_io(self):
        body = (b'\xef\xbb\xbf<title> Public &amp;\n Topic </title><meta name="description" content="Original &quot;summary&quot;">'
            b'<h1>Unretained heading</h1><h2>Other</h2><a href="https://private.invalid/?secret=x">Contact</a>'
            b'<script type="application/ld+json">{"email":"private@example.invalid","@type":"Person"}</script>'
            b'<p>Unretained contact text</p>')
        with patch("socket.create_connection", side_effect=AssertionError("No egress")):
            result = self.observe(body)
        self.assertEqual(result["metadata"], {"title": "Public & Topic", "description": 'Original "summary"',
            "title_truncated": False, "description_truncated": False})
        self.assertEqual(result["counts"], {"h1": 1, "h2": 1, "h3": 0, "h4": 0, "h5": 0, "h6": 0, "href_anchors": 1, "json_ld_blocks": 1})
        self.assertEqual(result["body_sha256"], sha256(body).hexdigest())
        self.assertEqual(result["body_size_bytes"], len(body))
        for value in ("private@", "Unretained", "secret=x", "Person", "Contact"):
            self.assertNotIn(value, json.dumps(result))
        content = metadata.encode_metadata(result)
        self.assertLessEqual(len(content), 8192)
        self.assertEqual(metadata.parse_metadata(content), result)

    def test_inert_foreign_rawtext_descendants_excluded_and_empty_is_observed_absence(self):
        body = b'<template><title>Hidden</title><h1>x</h1><a href="x">x</a></template><svg><meta name="description" content="Hidden"></svg>'
        result = self.observe(body)
        self.assertEqual(result["state"], "observed")
        self.assertEqual(result["metadata"]["title"], "")
        self.assertEqual(result["metadata"]["description"], "")
        self.assertEqual(sum(result["counts"].values()), 0)
        for container in ("script", "style", "noscript", "textarea", "xmp", "iframe", "noembed", "noframes", "math"):
            with self.subTest(container=container):
                result = self.observe(f'<{container}><title>Hidden</title><h1>x</h1></{container}>'.encode())
                self.assertEqual(result["metadata"]["title"], "")
                self.assertEqual(sum(result["counts"].values()), 0)

    def test_ambiguity_duplicates_unclosed_and_limits_are_unavailable_not_zero(self):
        for body in (b"<title>A</title><title>B</title>", b"<title>Open", b"</title>",
            b'<meta name="description" content="a"><meta name="description" content="b">',
            b'<meta name="description" content="a" content="b">', b'<a href="a" href="b">',
            b'<script type="application/ld+json" type="text/plain"></script>', b"<template/>", b"<title/>",
            b"<template><svg></template></svg>", b"<p><!--incomplete", b"<", b"<h1>" * 1001, b"<template>" * 101):
            with self.subTest(body=body):
                result = self.observe(body)
                self.assertEqual(result["state"], "unavailable")
                self.assertIsNone(result["metadata"])
                self.assertTrue(all(value is None for value in result["counts"].values()))
        self.assertEqual(self.observe(b"<h1>" * 1000)["counts"]["h1"], 1000)
        # The pinned stdlib preserves title RCDATA; markup-looking text remains inert literal text.
        self.assertEqual(self.observe(b"<title>A<b>B</b></title>")["metadata"]["title"], "A<b>B</b>")

    def test_exact_original_body_complete_utf8_url_date_and_real_types_required(self):
        base = {"body": b"<title>Valid</title>", "body_complete": True, "url": "https://competitor.example.invalid/",
            "observed_at": timezone.now().isoformat(timespec="microseconds")}
        changes = [{"body": value} for value in (None, "<html>", b"", b"\xff", b"a\x00", b"x" * (metadata.MAX_BODY_BYTES + 1))]
        changes += [{"body_complete": value} for value in (False, 1, None)]
        changes += [{"url": value} for value in (True, "https://competitor.example.invalid", "https://competitor.example.invalid:443/",
            "https://user:secret@competitor.example.invalid/", "https://competitor.example.invalid/?", "https://competitor.example.invalid/#",
            "https://competitor.example.invalid/%0a", "https://competitor.example.invalid/a b", "ftp://competitor.example.invalid/", "x" * 1025)]
        changes += [{"observed_at": value} for value in (None, True, "2026-01-01", "2026-01-01T00:00:00Z",
            (timezone.now() + timedelta(days=1)).isoformat(timespec="microseconds"))]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValidationError): metadata.observe_static_metadata(**(base | change))
        self.assertEqual(metadata.observe_static_metadata(**(base | {"url": "http://competitor.example.invalid/"}))["state"], "observed")

    def test_unicode_bounds_truncation_byte_ceiling_and_fresh_objects(self):
        result = self.observe(("<title>" + "😀" * 501 + '</title><meta name="description" content="' + "😀" * 1001 + '">').encode())
        self.assertEqual(len(result["metadata"]["title"]), 500)
        self.assertEqual(len(result["metadata"]["description"]), 1000)
        self.assertTrue(result["metadata"]["title_truncated"])
        self.assertTrue(result["metadata"]["description_truncated"])
        content = metadata.encode_metadata(result)
        self.assertLessEqual(len(content), metadata.MAX_RESULT_BYTES)
        stored = metadata.parse_metadata(content)
        stored["counts"]["h1"] = 99
        self.assertEqual(result["counts"]["h1"], 0)
        self.assertEqual(metadata.parse_metadata(content)["counts"]["h1"], 0)
        boundary = self.observe(("<title>" + "x" * 499 + " y</title>").encode())
        self.assertEqual(boundary["metadata"]["title"], "x" * 499)
        self.assertTrue(boundary["metadata"]["title_truncated"])

    def test_strict_readback_shapes_nonfinite_duplicates_overflow_null_and_boolean_counts(self):
        original = self.observe()
        variants = []
        for key, value in (("raw_html", "secret"), ("method_version", "foreign"), ("body_size_bytes", True), ("body_sha256", "A" * 64),
            ("counts", {**original["counts"], "h1": True}), ("counts", dict.fromkeys(metadata.COUNTS, 1000)),
            ("metadata", {**original["metadata"], "title_truncated": 1}), ("metadata", {**original["metadata"], "title_truncated": True}),
            ("metadata", {**original["metadata"], "title": "bad\x01"}), ("reason", "raw failure"), ("excluded_containers", [])):
            variants.append(original | {key: value})
        unavailable = self.observe(b"<title>Open")
        variants += [unavailable | {"counts": original["counts"]}, unavailable | {"metadata": original["metadata"]}]
        for variant in variants:
            with self.subTest(variant=variant), self.assertRaises(ValidationError): metadata.encode_metadata(variant)
        content = metadata.encode_metadata(original)
        for value in (b'\xff', b'{"a":1,"a":2}', b'{"a":NaN}', b"null", b"[]", b"x" * 8193,
            content.replace(b'"state":"observed"', b'"state":"observed","state":"observed"')):
            with self.subTest(value=value), self.assertRaises(ValidationError): metadata.parse_metadata(value)
