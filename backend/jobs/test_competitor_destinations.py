from copy import deepcopy
from hashlib import sha256
import json
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from django.utils import timezone

from . import competitor_destinations as destinations, competitor_links as links, competitor_metadata as metadata


class CompetitorDestinationTests(SimpleTestCase):
    origin = "https://competitor.example.invalid"

    def observe(self, body=b"<p>No anchors</p>", **changes):
        return destinations.observe_static_destinations(**({"body": body, "body_complete": True,
            "url": self.origin + "/section/article", "observed_at": timezone.now().isoformat(timespec="microseconds")} | changes))

    def test_original_order_duplicates_counts_privacy_no_io_and_fresh_closed_readback(self):
        body = (b'\xef\xbb\xbf<title>Unretained title</title><a data-private="secret" href="../first">Anchor prose</a>'
            b'<a href="//competitor.example.invalid/second">Second</a><a href="/first">Repeated</a>'
            b'<a href="https://other.example.invalid/private">External</a><a href="/search?token=secret">Query</a>'
            b'<a href="mailto:private@example.invalid">Contact</a><a>No href</a><p>Private body</p>')
        with patch("socket.getaddrinfo", side_effect=AssertionError("No DNS")), patch("builtins.open", side_effect=AssertionError("No files")):
            result = self.observe(body)
        self.assertEqual(result["destinations"], [self.origin + "/first", self.origin + "/second", self.origin + "/first"])
        self.assertEqual(result["counts"], {"href_anchors": 6, "same_origin_http": 3, "other_origin_http": 1, "unsupported": 2})
        self.assertEqual((result["body_sha256"], result["body_size_bytes"]), (sha256(body).hexdigest(), len(body)))
        for value in ("Unretained title", "Anchor prose", "secret", "data-private", "other.example", "private@", "Private body", "mailto"):
            self.assertNotIn(value, json.dumps(result))
        content = destinations.encode_destinations(result)
        stored = destinations.parse_destinations(content); stored["destinations"].clear(); stored["counts"].clear()
        self.assertEqual(destinations.parse_destinations(content), result)
        old = links.observe_static_links(body=body, body_complete=True, url=result["url"], observed_at=result["observed_at"])
        self.assertEqual(old["counts"], result["counts"]); self.assertNotIn("destinations", old)
        with self.assertRaises(ValidationError): links.parse_links(content)

    def test_supported_uri_join_only_same_exact_origin_and_unsupported_denominators(self):
        for href, path in (("./relative", "/section/relative"), ("../parent", "/parent"), ("../../root", "/root"),
            ("/path", "/path"), ("//competitor.example.invalid/path", "/path"),
            (self.origin, "/"), (self.origin + "/section/../path", "/section/../path"),
            ("/a&amp;b", "/a&b"), ("/%E2%82%AC", "/%E2%82%AC"), ("/%FF", "/%FF"),
            ("/%EF%BB%BF", "/%EF%BB%BF"), ("/%2520", "/%2520"), (self.origin + "/%2e%2e/raw", "/%2e%2e/raw")):
            with self.subTest(href=href):
                self.assertEqual(self.observe(f'<a href="{href}">x</a>'.encode())["destinations"], [self.origin + path])
        for href in ("", "#fragment", "?secret=x", "/path?", "/path#", "https:relative", "http:/broken", "//",
            "///other.invalid/path", self.origin + ":443/path", "https://UPPER.invalid/path", "https://user:secret@other.invalid/path",
            "ftp://other.invalid/path", "javascript:alert(1)", "data:text/plain,secret", "//[invalid]/path", "/back\\slash",
            "/has space", "/%0A", "/%5c", "/%7f", "/%20", "/bad%ZZ", "/bad%", "x" * 1025):
            with self.subTest(href=href):
                result = self.observe(f'<a href="{href}">x</a>'.encode())
                self.assertEqual((result["destinations"], result["counts"]["unsupported"]), ([], 1))
        for href in ("http://competitor.example.invalid/", "https://child.competitor.example.invalid/", "https://other.invalid/"):
            result = self.observe(f'<a href="{href}">x</a>'.encode())
            self.assertEqual((result["destinations"], result["counts"]["other_origin_http"]), ([], 1))

    def test_all_inert_rawtext_foreign_exclusions_and_observed_empty_preserve_uncertainty(self):
        self.assertEqual((self.observe()["state"], self.observe()["destinations"]), ("observed", []))
        for tag in (*sorted(metadata.EXCLUDED), "title"):
            with self.subTest(tag=tag):
                result = self.observe(f'<{tag}><base><a href="/hidden">hidden</a></{tag}><a href="/seen">seen</a>'.encode())
                if tag == "plaintext":
                    self.assertIsNone(result["destinations"])
                else:
                    self.assertEqual(result["destinations"], [self.origin + "/seen"])
        result = self.observe(b'<a href="/outer"><template><a href="/hidden">Hidden</a></template>Outer</a>')
        self.assertEqual(result["destinations"], [self.origin + "/outer"])
        result = self.observe(b'<a href="/search?query=secret">x</a><a href="https://other.invalid/">y</a>')
        self.assertEqual((result["state"], result["destinations"], result["counts"]),
            ("observed", [], {"href_anchors": 2, "same_origin_http": 0, "other_origin_http": 1, "unsupported": 1}))

    def test_ambiguous_base_and_original_element_limits_withhold_whole_inventory(self):
        for body in (b'<base><a href="/seen">x</a>', b'<a href="/seen">x</a><base/>', b'<a href="/a" href="/b">x</a>',
            b'<a href="/a"><a href="/b">nested</a></a>', b'<a href="/a">open', b'</a>', b'<a href="/a"/>',
            b'<a href="/a">x</a><!--incomplete', b'<template/>', b'<h1>' * 1000 + b'<a href="/a">x</a>',
            b'<a href="https://other.invalid/">x</a>' * 1001):
            with self.subTest(body=body):
                result = self.observe(body)
                self.assertEqual(result["state"], "unavailable"); self.assertIn(result["reason"], destinations.REASONS)
                self.assertIsNone(result["destinations"]); self.assertTrue(all(value is None for value in result["counts"].values()))
        result = self.observe(b'<a href="https://other.invalid/">x</a>' * 1000)
        self.assertEqual((result["destinations"], result["counts"]["other_origin_http"]), ([], 1000))

    def test_occurrence_and_actual_result_byte_limits_never_return_partial_success(self):
        self.assertEqual(len(self.observe(b'<a href="/same">x</a>' * 10)["destinations"]), 10)
        cases = ((b'<a href="/same">x</a>' * 11, "destination_limit"),
            ((b'<a href="/' + b'x' * 970 + b'">x</a>') * 10, "result_limit"))
        for body, reason in cases:
            result = self.observe(body)
            self.assertEqual((result["state"], result["reason"]), ("unavailable", reason))
            self.assertIsNone(result["destinations"]); self.assertTrue(all(value is None for value in result["counts"].values()))
        result = self.observe(b'<title>' + b'x' * 501 + b'</title><a href="/seen">x</a>')
        self.assertEqual(result["destinations"], [self.origin + "/seen"])

    def test_original_complete_body_canonical_uri_and_date_are_required(self):
        for change in ({"body_complete": False}, {"body_complete": 1}, {"body": "<p>text"}, {"body": b""},
            {"body": b"x" * 131073}, {"body": b"\xff"}, {"body": b"x\x00"}, {"url": self.origin + "/?token=private"},
            {"url": self.origin + ":443/"}, {"observed_at": "2026-02-30T00:00:00.000001+00:00"}):
            with self.subTest(change=change), self.assertRaises(ValidationError): self.observe(**change)

    def test_closed_readback_same_origin_list_count_null_type_and_json_invariants(self):
        original = self.observe(b'<a href="/seen">x</a>')
        mutations = [lambda v: v.update(raw_body="secret"), lambda v: v.update(method_version=links.METHOD),
            lambda v: v.update(coverage="whole_site"), lambda v: v.update(interpretation="fetched_destinations"),
            lambda v: v.update(excluded_containers=[]), lambda v: v.update(body_size_bytes=True), lambda v: v.update(body_sha256=None),
            lambda v: v.update(url=None), lambda v: v.update(reason="private"), lambda v: v.update(destinations=None),
            lambda v: v.update(destinations=()), lambda v: v.update(destinations=[self.origin + "/seen"] * 11),
            lambda v: v.update(destinations=[True]), lambda v: v.update(destinations=["/relative"]),
            lambda v: v.update(destinations=["https://other.invalid/seen"]), lambda v: v.update(destinations=[self.origin]),
            lambda v: v.update(destinations=[self.origin + "/?secret=x"]), lambda v: v["counts"].update(same_origin_http=0),
            lambda v: v["counts"].update(same_origin_http=True), lambda v: v["counts"].update(unsupported=-1),
            lambda v: v.update(state="unavailable", reason="destination_limit")]
        for mutate in mutations:
            value = deepcopy(original); mutate(value)
            with self.assertRaises(ValidationError): destinations.encode_destinations(value)
        unknown = self.observe(b"<base>")
        for changes in ({"reason": "secret"}, {"destinations": []}, {"counts": original["counts"]}):
            with self.assertRaises(ValidationError): destinations.encode_destinations(unknown | changes)
        content = destinations.encode_destinations(original)
        for value in (b"\xff", b'{"x":1,"x":2}', b'{"x":NaN}', b"null", b"[]", b"x" * 8193,
            content.replace(b'"state":"observed"', b'"state":"observed","state":"observed"')):
            with self.assertRaises(ValidationError): destinations.parse_destinations(value)
