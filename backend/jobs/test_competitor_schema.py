from copy import deepcopy
from hashlib import sha256
import json
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from django.utils import timezone

from . import competitor_metadata as metadata, competitor_schema as schema


class CompetitorSchemaTests(SimpleTestCase):
    def observe(self, body=b"<p>Original static page</p>", **changes):
        return schema.observe_static_schema(**({"body": body, "body_complete": True,
            "url": "https://competitor.example.invalid/", "observed_at": timezone.now().isoformat(timespec="microseconds")} | changes))

    def block(self, value):
        return b'<script type="application/ld+json">' + json.dumps(value).encode() + b'</script>'

    def test_original_types_nested_graph_privacy_roundtrip_and_no_io(self):
        body = self.block({"@context": "https://secret.invalid/context", "@graph": [{"@type": ["Article", "https://schema.org/WebPage"],
            "headline": "Secret headline", "author": {"@type": "Person", "email": "private@example.invalid"}},
            {"@type": "http://schema.org/Product"}, {"@type": "SecretIdentifier"}, {"@type": "schema:Article"}]})
        with patch("socket.getaddrinfo", side_effect=AssertionError("No DNS")), patch("builtins.open", side_effect=AssertionError("No files")):
            result = self.observe(body)
        self.assertEqual(result["summary"], {"json_ld_blocks": 1, "typed_nodes": 5,
            "types": ["Article", "Person", "Product", "WebPage"], "unrecognized_type_count": 2})
        self.assertEqual(result["body_sha256"], sha256(body).hexdigest())
        self.assertEqual(result["body_size_bytes"], len(body))
        for value in ("private@", "Secret", "secret.invalid", "schema:Article", "headline", "@context"):
            self.assertNotIn(value, json.dumps(result))
        content = schema.encode_schema(result)
        self.assertLessEqual(len(content), 8192)
        stored = schema.parse_schema(content)
        stored["summary"]["types"].clear()
        self.assertEqual(schema.parse_schema(content), result)
        # v1 still retains only the original block count, not any new schema facts.
        original = metadata.observe_static_metadata(body=body, body_complete=True, url=result["url"], observed_at=result["observed_at"])
        self.assertEqual(original["counts"]["json_ld_blocks"], 1)
        self.assertNotIn("summary", original)

    def test_observed_empty_unrecognized_only_and_inert_rawtext_exclusions(self):
        empty = {"json_ld_blocks": 0, "typed_nodes": 0, "types": [], "unrecognized_type_count": 0}
        self.assertEqual(self.observe()["summary"], empty)
        for tag in ("template", "svg", "math", "noscript", "style", "textarea", "title", "xmp", "iframe", "noembed", "noframes"):
            with self.subTest(tag=tag):
                self.assertEqual(self.observe(b"<" + tag.encode() + b">" + self.block({"@type": "Article"}) + b"</" + tag.encode() + b">")["summary"], empty)
        self.assertEqual(self.observe(self.block({}))["summary"]["typed_nodes"], 0)
        result = self.observe(self.block({"@type": ["https://schema.org/Article/", "schema:Product", "Unknown"]}))
        self.assertEqual(result["summary"]["types"], [])
        self.assertEqual(result["summary"]["unrecognized_type_count"], 3)

    def test_invalid_json_type_shape_and_ambiguous_markup_are_wholly_unavailable(self):
        bad_json = [b"", b"{", b'{"@type":"Article","@type":"Product"}', b'{"x":NaN}', b'{"x":Infinity}', b'"scalar"']
        bodies = [b'<script type="application/ld+json">' + value + b'</script>' for value in bad_json]
        bodies += [self.block({"@type": value}) for value in (None, True, 1, [], {}, ["Article", 1], "bad\x01", "", "two words", "x" * 513)]
        bodies += [b'<script type="application/ld+json" type="text/plain">{}</script>', b'<script type="application/ld+json">{}',
            b'<script type="application/ld+json" src="https://private.invalid/">{}</script>', b'<template/>']
        for body in bodies:
            with self.subTest(body=body):
                result = self.observe(self.block({"@type": "Article"}) + body)
                self.assertEqual(result["state"], "unavailable")
                self.assertIsNone(result["summary"])
                self.assertIn(result["reason"], schema.REASONS)
        self.assertEqual(self.observe(b'<script type="application/ld+json">{"x":1e999}</script>')["reason"], "shape_limit")

    def test_exact_block_byte_node_depth_and_typed_node_limits(self):
        self.assertEqual(self.observe(self.block({}) * 20)["summary"]["json_ld_blocks"], 20)
        self.assertEqual(self.observe(self.block({}) * 21)["reason"], "block_limit")
        for size in (16384, 16385):
            result = self.observe(b'<script type="application/ld+json">{}' + b" " * (size - 2) + b'</script>')
            self.assertEqual(result["state"], "observed" if size == 16384 else "unavailable")
        for nodes in (999, 1000):
            result = self.observe(self.block([None] * nodes))
            self.assertEqual(result["state"], "observed" if nodes == 999 else "unavailable")
        for depth in (20, 21):
            value = None
            for _ in range(depth): value = [value]
            self.assertEqual(self.observe(self.block(value))["state"], "observed" if depth == 20 else "unavailable")
        unit = self.block([{"@type": "Article"}] * 250)
        self.assertEqual(self.observe(unit * 2)["summary"]["typed_nodes"], 500)
        self.assertEqual(self.observe(unit * 2 + self.block({"@type": "Article"}))["reason"], "shape_limit")
        self.assertEqual(self.observe(self.block({"@type": ["Article"] * 20}))["state"], "observed")
        self.assertEqual(self.observe(self.block({"@type": ["Article"] * 21}))["reason"], "type_shape")

    def test_original_complete_bytes_utf8_url_and_date_required(self):
        for change in ({"body_complete": 1}, {"body_complete": False}, {"body": b"\xff"}, {"body": b"x\x00"},
            {"body": b""}, {"body": b"x" * 131073}, {"url": "https://competitor.example.invalid/?secret=x"},
            {"observed_at": "2026-01-01T00:00:00Z"}):
            with self.subTest(change=change), self.assertRaises(ValidationError): self.observe(**change)

    def test_strict_closed_readback_types_null_counts_duplicates_and_nonfinite(self):
        original = self.observe(self.block({"@type": "Article"}))
        for key, value in (("raw_json", "secret"), ("method_version", metadata.METHOD), ("body_size_bytes", True),
            ("summary", {}), ("state", "partial"), ("reason", "raw error"), ("excluded_containers", [])):
            with self.subTest(key=key), self.assertRaises(ValidationError): schema.encode_schema(original | {key: value})
        for key, value in (("typed_nodes", True), ("typed_nodes", 501), ("typed_nodes", 0), ("json_ld_blocks", 0),
            ("json_ld_blocks", 21), ("types", ["Article", "Article"]), ("types", ["SecretIdentifier"]),
            ("types", [True]), ("unrecognized_type_count", -1), ("unrecognized_type_count", 21)):
            result = deepcopy(original)
            result["summary"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValidationError): schema.encode_schema(result)
        unavailable = self.observe(b"<template/>")
        with self.assertRaises(ValidationError): schema.encode_schema(unavailable | {"summary": original["summary"]})
        content = schema.encode_schema(original)
        for raw in (b"null", b"[]", b"\xff", b'{"x":NaN}', b"x" * 8193,
            content.replace(b'"state":"observed"', b'"state":"observed","state":"observed"')):
            with self.subTest(raw=raw), self.assertRaises(ValidationError): schema.parse_schema(raw)
