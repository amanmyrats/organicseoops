from hashlib import sha256
import json
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from django.utils import timezone

from . import competitor_links as links, competitor_metadata as metadata


class CompetitorLinkTests(SimpleTestCase):
    def observe(self, body=b"<p>No anchors</p>", **changes):
        return links.observe_static_links(**({"body": body, "body_complete": True,
            "url": "https://competitor.example.invalid/section/article",
            "observed_at": timezone.now().isoformat(timespec="microseconds")} | changes))

    def test_original_categories_occurrences_bytes_privacy_no_io_and_old_v1_unchanged(self):
        body = (b'\xef\xbb\xbf<a href="/private-contact">Unretained contact</a><a href="../other">Relative</a>'
            b'<a href="//competitor.example.invalid/same">Same</a><a href="/private-contact">Repeated</a>'
            b'<a href="https://external.example.invalid">External</a>'
            b'<a href="http://competitor.example.invalid/">Different scheme</a>'
            b'<a href="https://child.competitor.example.invalid/">Different host</a>'
            b'<a href="/search?secret=private">Unretained query</a><a href="mailto:private@example.invalid">Mail</a>'
            b'<a href>Missing value</a><a>No href attribute</a><p>secret body</p>')
        with patch("socket.getaddrinfo", side_effect=AssertionError("No DNS")), patch("builtins.open", side_effect=AssertionError("No files")):
            result = self.observe(body)
        self.assertEqual(result["counts"], {"href_anchors": 10, "same_origin_http": 4, "other_origin_http": 3, "unsupported": 3})
        self.assertEqual(result["body_sha256"], sha256(body).hexdigest())
        self.assertEqual(result["body_size_bytes"], len(body))
        for value in ("private-contact", "contact", "Relative", "secret", "external.example", "child.competitor", "mailto", "private@"):
            self.assertNotIn(value, json.dumps(result))
        content = links.encode_links(result)
        self.assertLessEqual(len(content), 8192)
        parsed = links.parse_links(content)
        parsed["counts"]["unsupported"] = 99
        self.assertEqual(links.parse_links(content), result)
        original = metadata.observe_static_metadata(body=body, body_complete=True, url=result["url"], observed_at=result["observed_at"])
        self.assertEqual(original["counts"]["href_anchors"], 10)
        self.assertEqual(original["method_version"], metadata.METHOD)
        self.assertNotIn("same_origin_http", original["counts"])
        with self.assertRaises(ValidationError): metadata.parse_metadata(content)

    def test_uri_join_is_explicit_no_browser_repair_and_all_unsupported_remain_in_denominator(self):
        for href in ("./relative", "../parent", "../../root", "/path", "//competitor.example.invalid/path",
            "https://competitor.example.invalid/section/../path", "/a&amp;b", "/%E2%82%AC"):
            with self.subTest(href=href):
                self.assertEqual(self.observe(f'<a href="{href}">x</a>'.encode())["counts"],
                    {"href_anchors": 1, "same_origin_http": 1, "other_origin_http": 0, "unsupported": 0})
        for href in ("", "#fragment", "?secret=x", "/path?", "/path#", "https:relative", "http:/broken", "//", "///external.invalid/path",
            "https://competitor.example.invalid:443/path", "https://external.invalid:444/path", "https://UPPER.invalid/path",
            "https://user:secret@external.invalid/path", "ftp://external.invalid/path", "javascript:alert(1)", "data:text/plain,secret",
            "//[invalid]/path", "/back\\slash", "/has space", "/%0A", "/%5c", "/%7f", "/%20", "/bad%ZZ", "/bad%", "x" * 1025,
            "/path&#10;value"):
            with self.subTest(href=href):
                self.assertEqual(self.observe(f'<a href="{href}">x</a>'.encode())["counts"],
                    {"href_anchors": 1, "same_origin_http": 0, "other_origin_http": 0, "unsupported": 1})
        # The existing stdlib HTML character-reference decoder omits invalid numeric DEL;
        # this is decoded static attribute syntax, never the literal bytes or browser visibility.
        self.assertEqual(self.observe(b'<a href="/path&#127;value">x</a>')["counts"]["same_origin_http"], 1)
        result = self.observe(b'<a href="//competitor.example.invalid/">x</a><a href="https://competitor.example.invalid/">y</a>',
            url="http://competitor.example.invalid/")
        self.assertEqual(result["counts"]["same_origin_http"], 1)
        self.assertEqual(result["counts"]["other_origin_http"], 1)

    def test_inert_foreign_rawtext_exclusions_and_empty_observed_absence(self):
        empty = dict.fromkeys(links.COUNTS, 0)
        self.assertEqual(self.observe()["counts"], empty)
        for tag in (*sorted(metadata.EXCLUDED - {"plaintext"}), "title"):
            with self.subTest(tag=tag):
                result = self.observe(f'<{tag}><base href="https://other.invalid/"><a href="/hidden">hidden</a></{tag}>'.encode())
                self.assertEqual(result["state"], "observed")
                self.assertEqual(result["counts"], empty)
        # plaintext has no closing-tag interpretation in the shared strict parser.
        self.assertEqual(self.observe(b'<plaintext><a href="/hidden">x</a></plaintext>')["state"], "unavailable")
        self.assertEqual(self.observe(b'<a href="/outside"><template><a href="/hidden">Hidden</a></template>Outside</a>')["counts"]["same_origin_http"], 1)

    def test_base_anywhere_ambiguous_anchor_markup_and_whole_document_limits_are_null(self):
        for body in (b'<base href="https://other.invalid/"><a href="/path">x</a>', b'<a href="/path">x</a><base>',
            b'<base/>', b'<a href="/a" href="/b">x</a>', b'<a href="/a"><a href="/b">nested</a></a>',
            b'<a>Open without href', b'<a href="/a">Open', b'</a>', b'<a href="/a"/>', b'<template/>',
            b'<template><svg></template></svg>', b'<a href="/a">x</a><!--incomplete', b'<title>Open',
            b'<h1>' * 1000 + b'<a href="/a">x</a>', b'<a href="/a">x</a>' * 1001):
            with self.subTest(body=body):
                result = self.observe(body)
                self.assertEqual(result["state"], "unavailable")
                self.assertIn(result["reason"], links.REASONS)
                self.assertTrue(all(value is None for value in result["counts"].values()))
        self.assertEqual(self.observe(b'<a href="/a">x</a>' * 1000)["counts"]["href_anchors"], 1000)
        self.assertEqual(self.observe(b'<h1>' * 999 + b'<a href="/a">x</a>')["counts"]["href_anchors"], 1)

    def test_original_complete_body_and_strict_closed_readback(self):
        for change in ({"body_complete": 1}, {"body_complete": False}, {"body": b"\xff"}, {"body": b"x\x00"},
            {"body": b""}, {"body": b"x" * 131073}, {"body": "<p>text"}, {"url": "https://competitor.example.invalid/?secret=x"},
            {"observed_at": "2026-01-01T00:00:00Z"}):
            with self.subTest(change=change), self.assertRaises(ValidationError): self.observe(**change)
        original = self.observe(b'<a href="/path">x</a>')
        unavailable = self.observe(b"<base>")
        for key, value in (("raw_href", "secret"), ("method_version", metadata.METHOD), ("body_size_bytes", True),
            ("body_sha256", "A" * 64), ("counts", {}), ("counts", original["counts"] | {"same_origin_http": True}),
            ("counts", original["counts"] | {"same_origin_http": 0}), ("counts", original["counts"] | {"unsupported": -1}),
            ("counts", {"href_anchors": 1001, "same_origin_http": 1001, "other_origin_http": 0, "unsupported": 0}),
            ("counts", dict.fromkeys(links.COUNTS)), ("reason", "private failure"), ("coverage", "whole site"),
            ("interpretation", "healthy links"), ("excluded_containers", [])):
            with self.subTest(key=key, value=value), self.assertRaises(ValidationError): links.encode_links(original | {key: value})
        with self.assertRaises(ValidationError): links.encode_links(unavailable | {"counts": original["counts"]})
        with self.assertRaises(ValidationError): links.encode_links(unavailable | {"reason": "private error"})
        content = links.encode_links(original)
        for value in (b"\xff", b'{"a":1,"a":2}', b'{"a":NaN}', b"null", b"[]", b"x" * 8193,
            content.replace(b'"state":"observed"', b'"state":"observed","state":"observed"')):
            with self.subTest(value=value), self.assertRaises(ValidationError): links.parse_links(value)
