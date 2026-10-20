from copy import deepcopy
from hashlib import sha256
import json
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from django.utils import timezone

from . import competitor_headings as headings, competitor_metadata as metadata


class CompetitorHeadingTests(SimpleTestCase):
    def observe(self, body=b"<p>Original static page</p>", **changes):
        return headings.observe_static_headings(**({"body": body, "body_complete": True,
            "url": "https://competitor.example.invalid/", "observed_at": timezone.now().isoformat(timespec="microseconds")} | changes))

    def test_original_order_duplicates_decoded_inline_text_levels_privacy_fresh_readback_and_no_io(self):
        body = b'<title>Unretained title</title><h3 data-private="secret"> First <em>inline</em> &amp; literal </h3><p>private@example.invalid</p><h1>Second</h1><h3>First inline &amp; literal</h3>'
        with patch("socket.getaddrinfo", side_effect=AssertionError("No DNS")), patch("builtins.open", side_effect=AssertionError("No files")):
            result = self.observe(body)
        self.assertEqual(result["headings"], [{"level": 3, "text": "First inline & literal", "truncated": False},
            {"level": 1, "text": "Second", "truncated": False}, {"level": 3, "text": "First inline & literal", "truncated": False}])
        self.assertEqual(result["counts"], {"h1": 1, "h2": 0, "h3": 2, "h4": 0, "h5": 0, "h6": 0})
        self.assertEqual((result["body_sha256"], result["body_size_bytes"]), (sha256(body).hexdigest(), len(body)))
        for private in ("private@", "secret", "data-private", "Unretained title", "<em>"):
            self.assertNotIn(private, json.dumps(result))
        content = headings.encode_headings(result); self.assertLessEqual(len(content), 8192)
        stored = headings.parse_headings(content); stored["headings"].clear()
        self.assertEqual(headings.parse_headings(content), result)
        old = metadata.observe_static_metadata(body=body, body_complete=True, url=result["url"], observed_at=result["observed_at"])
        self.assertEqual(old["counts"]["h3"], 2); self.assertNotIn("headings", old)

    def test_all_inert_rawtext_and_foreign_exclusions_empty_observed_and_hidden_inline_text(self):
        for container in sorted(metadata.EXCLUDED):
            result = self.observe(f'<{container}><h1>Hidden</h1></{container}><h2>Observed</h2>'.encode())
            if container == "plaintext":
                self.assertEqual(result["state"], "unavailable"); self.assertIsNone(result["headings"])
                self.assertTrue(all(value is None for value in result["counts"].values()))
            else:
                self.assertEqual(result["headings"], [{"level": 2, "text": "Observed", "truncated": False}], container)
        result = self.observe(b'<h1>Before<script>private-text</script><template><h2>Hidden</h2></template> after</h1><h6></h6>')
        self.assertEqual(result["headings"], [{"level": 1, "text": "Before after", "truncated": False}, {"level": 6, "text": "", "truncated": False}])
        empty = self.observe(); self.assertEqual(empty["state"], "observed"); self.assertEqual(empty["headings"], [])
        self.assertTrue(all(value == 0 for value in empty["counts"].values()))

    def test_nested_mismatched_unclosed_selfclosing_or_incomplete_markup_is_unavailable_null(self):
        for body in (b"<h1>Unclosed", b"<h1>One<h2>Two</h2></h1>", b"<h1>One</h2>", b"</h3>", b"<h4/>",
            b"<h1><title>Ambiguous</title></h1>", b"<template><h1>Unclosed", b"<h1>One</h1><h2"):
            with self.subTest(body=body):
                result = self.observe(body); self.assertEqual((result["state"], result["reason"]), ("unavailable", "ambiguous_markup"))
                self.assertIsNone(result["headings"]); self.assertTrue(all(value is None for value in result["counts"].values()))
                self.assertEqual(result["body_sha256"], sha256(body).hexdigest())

    def test_exact_occurrence_element_and_text_limits_preserve_unicode_truncation_and_empty_vs_unknown(self):
        result = self.observe(b"<h1>Same</h1>" * 10); self.assertEqual(len(result["headings"]), 10)
        for body, reason in ((b"<h1>Same</h1>" * 11, "heading_limit"), (b"<a href='/'>Link</a>" * 1001, "element_limit")):
            result = self.observe(body); self.assertEqual((result["state"], result["reason"]), ("unavailable", reason))
            self.assertIsNone(result["headings"]); self.assertTrue(all(value is None for value in result["counts"].values()))
        for length in (80, 81):
            text = "🙂" * length; result = self.observe(("<h2>" + text + "</h2>").encode())
            self.assertEqual(result["headings"], [{"level": 2, "text": "🙂" * 80, "truncated": length == 81}])
        title = self.observe(b"<title>" + b"x" * 501 + b"</title><h1>Still bounded</h1>")
        self.assertEqual(title["headings"][0]["text"], "Still bounded")

    def test_original_complete_body_utf8_canonical_uri_and_date_are_required(self):
        for changes in ({"body_complete": False}, {"body_complete": 1}, {"body": "<h1>Text</h1>"}, {"body": b""},
            {"body": b"x" * 131073}, {"body": b"\xff"}, {"body": b"<h1>\x00</h1>"}, {"url": "https://user:secret@competitor.example.invalid/"},
            {"url": "https://competitor.example.invalid/?token=private"}, {"observed_at": "2026-02-30T00:00:00.000001+00:00"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError): self.observe(**changes)
        body = b"\xef\xbb\xbf<h1>Original</h1>"
        self.assertEqual(self.observe(body)["body_sha256"], sha256(body).hexdigest())

    def test_strict_closed_readback_level_text_count_boolean_null_duplicate_and_nonfinite_shapes(self):
        original = self.observe(b"<h1>Original</h1>")
        mutations = [lambda v: v.update(raw_body="private"), lambda v: v.update(method_version=metadata.METHOD),
            lambda v: v.update(interpretation="semantic_outline"), lambda v: v.update(excluded_containers=[]),
            lambda v: v.update(body_sha256=None), lambda v: v.update(headings=None), lambda v: v["counts"].update(h1=0),
            lambda v: v["counts"].update(h1=True), lambda v: v["headings"][0].update(level=True),
            lambda v: v["headings"][0].update(level=7), lambda v: v["headings"][0].update(text="x" * 81),
            lambda v: v["headings"][0].update(text=" leading"), lambda v: v["headings"][0].update(text="bad\x7f"),
            lambda v: v["headings"][0].update(truncated=1), lambda v: v["headings"][0].update(text="", truncated=True),
            lambda v: v["headings"][0].update(attributes={}), lambda v: v.update(state="unavailable", reason="heading_limit")]
        for mutate in mutations:
            value = deepcopy(original); mutate(value)
            with self.assertRaises(ValidationError): headings.encode_headings(value)
        for content in (b'{"state":1,"state":2}', b'{"count":NaN}', b"[]", b"\xff", b"x" * 8193):
            with self.assertRaises(ValidationError): headings.parse_headings(content)

    def test_original_result_byte_limit_withholds_complete_heading_list_instead_of_partial_success(self):
        body = ("<h1>" + "🙂" * 80 + "</h1>").encode() * 10
        with patch.object(metadata, "MAX_RESULT_BYTES", 2000):
            result = self.observe(body)
        self.assertEqual((result["state"], result["reason"]), ("unavailable", "result_limit"))
        self.assertIsNone(result["headings"]); self.assertTrue(all(value is None for value in result["counts"].values()))
