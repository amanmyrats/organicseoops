from copy import deepcopy
from hashlib import sha256
import json
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from django.utils import timezone

from . import competitor_formats as formats, competitor_metadata as metadata


class CompetitorFormatTests(SimpleTestCase):
    def observe(self, body=b"<h1>No selected content elements</h1>", **changes):
        return formats.observe_static_formats(**({"body": body, "body_complete": True,
            "url": "https://competitor.example.invalid/article", "observed_at": timezone.now().isoformat(timespec="microseconds")} | changes))

    def test_literal_start_counts_void_selfclosing_nested_duplicates_original_provenance_privacy_and_no_io(self):
        body = (b'\xef\xbb\xbf<title>Unretained title</title><p>private@example.invalid</p><p hidden>CSS hidden is still lexical</p>'
            b'<ul><ul></ul></ul><ol></ol><table></table><img src="https://private.invalid/?secret=x">'
            b'<picture><img alt="Unretained"/></picture><video src="secret"></video><audio></audio>')
        with patch("socket.getaddrinfo", side_effect=AssertionError("No DNS")), patch("builtins.open", side_effect=AssertionError("No files")):
            result = self.observe(body)
        self.assertEqual(result["counts"], {"p": 2, "ul": 2, "ol": 1, "table": 1, "img": 2, "picture": 1, "video": 1, "audio": 1})
        self.assertEqual((result["body_sha256"], result["body_size_bytes"]), (sha256(body).hexdigest(), len(body)))
        for private in ("private@", "private.invalid", "secret", "Unretained", "CSS hidden"):
            self.assertNotIn(private, json.dumps(result))
        self.assertEqual(result["interpretation"], formats.INTERPRETATION)
        content = formats.encode_formats(result); self.assertLessEqual(len(content), 8192)
        changed = formats.parse_formats(content); changed["counts"]["p"] = 99
        self.assertEqual(formats.parse_formats(content), result)
        old = metadata.observe_static_metadata(body=body, body_complete=True, url=result["url"], observed_at=result["observed_at"])
        self.assertEqual(old["method_version"], metadata.METHOD); self.assertNotIn("p", old["counts"])

    def test_inert_rawtext_foreign_exclusions_and_known_empty_do_not_claim_rendering(self):
        for container in sorted(metadata.EXCLUDED):
            result = self.observe(f'<{container}><p>Hidden</p><img src="secret"></{container}><p>Counted</p>'.encode())
            if container == "plaintext":
                self.assertEqual(result["state"], "unavailable"); self.assertTrue(all(value is None for value in result["counts"].values()))
            else:
                self.assertEqual(result["counts"]["p"], 1, container); self.assertEqual(result["counts"]["img"], 0, container)
        result = self.observe(b'<title>Literal <img/> title</title>')
        self.assertEqual(result["state"], "observed"); self.assertTrue(all(value == 0 for value in result["counts"].values()))
        self.assertTrue(all(value == 0 for value in self.observe()["counts"].values()))

    def test_ambiguity_incomplete_hidden_and_exact_combined_selected_element_limit_preserve_unknown(self):
        bodies = (b"<title>Open", b"<title>A</title><title>B</title>", b"<template/>", b"<template><svg></template></svg>",
            b"<p><!--incomplete", b"<img", b"<p>" * 501 + b"<img/>" * 500, b"<h1>" * 1001)
        for body in bodies:
            with self.subTest(body=body[:50]):
                result = self.observe(body); self.assertEqual(result["state"], "unavailable")
                self.assertTrue(all(value is None for value in result["counts"].values()))
        exact = self.observe(b"<p>" * 500 + b"<img/>" * 500)
        self.assertEqual((exact["counts"]["p"], exact["counts"]["img"]), (500, 500))
        # Start-tag syntax does not require a valid DOM or paired non-void closing tags.
        self.assertEqual(self.observe(b"<table/><p><p>")["counts"]["p"], 2)

    def test_original_complete_body_real_types_utf8_canonical_uri_and_date_are_required(self):
        for changes in ({"body_complete": False}, {"body_complete": 1}, {"body": "<p>Text</p>"}, {"body": b""},
            {"body": b"x" * 131073}, {"body": b"\xff"}, {"body": b"<p>\x00</p>"}, {"url": "https://user:secret@competitor.example.invalid/"},
            {"url": "https://competitor.example.invalid/?secret=x"}, {"observed_at": "2026-02-30T00:00:00.000001+00:00"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError): self.observe(**changes)
        self.assertEqual(self.observe(b"x" * 131072)["state"], "observed")

    def test_closed_dto_real_integer_counts_sum_null_and_original_meaning_validation(self):
        original = self.observe(b"<p>Original</p>")
        mutations = [lambda v: v.update(raw_body="private"), lambda v: v.update(method_version=metadata.METHOD),
            lambda v: v.update(interpretation="rendered_formats"), lambda v: v.update(excluded_containers=[]),
            lambda v: v.update(body_sha256=None), lambda v: v.update(body_size_bytes=True),
            lambda v: v["counts"].update(p=True), lambda v: v["counts"].update(p=-1), lambda v: v["counts"].update(p=1001),
            lambda v: v["counts"].update(p=1000, ul=1), lambda v: v["counts"].update(p=None),
            lambda v: v["counts"].update(iframe=1), lambda v: v.update(reason="raw failure")]
        for mutate in mutations:
            value = deepcopy(original); mutate(value)
            with self.assertRaises(ValidationError): formats.encode_formats(value)
        unavailable = self.observe(b"<title>Open")
        with self.assertRaises(ValidationError): formats.encode_formats(unavailable | {"counts": original["counts"]})
        with self.assertRaises(ValidationError): formats.encode_formats(unavailable | {"reason": "unknown"})

    def test_duplicate_nonfinite_utf8_byte_ceiling_and_nonbytes_readback_are_rejected(self):
        content = formats.encode_formats(self.observe())
        for value in (b'\xff', b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b"null", b"[]", b"x" * 8193,
            content.decode(), content.replace(b'"state":"observed"', b'"state":"observed","state":"observed"')):
            with self.subTest(value=str(value)[:70]), self.assertRaises(ValidationError): formats.parse_formats(value)
        original = self.observe()
        with patch.object(metadata, "MAX_RESULT_BYTES", 1), self.assertRaises(ValidationError): formats.encode_formats(original)
