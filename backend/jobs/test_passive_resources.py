import json
from unittest.mock import patch

from django.test import SimpleTestCase

from .crawler import PageParser
from .crawling import CrawlScope
from .passive_resources import MAX_BODY_BYTES, MAX_REFERENCES, observe_static_resource_references


class PassiveResourceTests(SimpleTestCase):
    def observe(self, body, **changes):
        return observe_static_resource_references(body, **{"body_complete": True, **changes})

    def test_original_literal_selected_entity_decoding_no_navigation_raw_payload_hash_write_or_network(self):
        body = (b'<SCRIPT SRC="h&#116;tp://user:private@127.0.0.1/a?token=private"></SCRIPT>'
            b'<iframe src="HTTPS://foreign.example.invalid/private"></iframe><img src="http://metadata.invalid/private">'
            b'<link rel="stylesheet preload" href="https://css.invalid/private"><link rel="modulepreload" href="http://module.invalid/private">'
            b'<link rel="canonical" href="http://navigation.invalid/private"><a href="http://navigation.invalid/private">private</a>')
        with patch("socket.create_connection", side_effect=AssertionError("No network")), \
            patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No fetch")), \
            patch("hashlib.sha256", side_effect=AssertionError("No raw digest")):
            result = self.observe(body)
        self.assertEqual(result["state"], "observed")
        self.assertEqual(result["counts"], {"inspected_attributes": 5, "http_absolute": 3, "https_absolute": 2, "unclassified": 0})
        for private in ("private", "127.0.0.1", "invalid/private", "token", "user:", "body_sha256", "<SCRIPT"):
            self.assertNotIn(private, json.dumps(result))
        self.assertIn("not_browser_requests", result["interpretation"])
        # Actual old crawl parser never retained a complete resource inventory.
        old = PageParser(); old.feed(body.decode()); old.close()
        parsed, _urls = old.result(base_url="https://document.example.invalid/", scope=CrawlScope(frozenset({"document.example.invalid"})))
        self.assertNotIn("resource_references", parsed)
        self.assertEqual(len(parsed["links"]), 1)

    def test_relative_network_path_base_empty_unsupported_and_malformed_refs_remain_unclassified(self):
        values = ("/relative", "//example.invalid/network", "", "data:private", "javascript:private", "http://", "http://[bad/",
            "http://example.invalid:70000/x", "http://example.invalid:0/x", "http://example.invalid/a b", "http://example.invalid/\\x",
            "http://example.invalid/a&#10;b", "http://example.invalid/" + "x" * 1024)
        body = ("<base href='http://private.invalid/' >" + "".join(f'<img src="{value}">' for value in values) + "<img src>").encode()
        result = self.observe(body)
        self.assertEqual(result["counts"], {"inspected_attributes": len(values) + 1, "http_absolute": 0, "https_absolute": 0, "unclassified": len(values) + 1})
        empty = self.observe(b"")
        self.assertEqual(empty["state"], "observed"); self.assertEqual(empty["counts"]["inspected_attributes"], 0)

    def test_inert_rawtext_foreign_comments_css_srcset_media_and_javascript_never_supply_selected_descendants(self):
        hidden = b'<img src="http://private.invalid/">'
        body = b"".join(b"<" + tag + b">" + hidden + b"</" + tag + b">" for tag in
            (b"script", b"style", b"template", b"noscript", b"textarea", b"title", b"xmp", b"iframe", b"noembed", b"noframes", b"svg", b"math"))
        body += b'<!--' + hidden + b'--><img srcset="http://private.invalid/x 1x"><video src="http://private.invalid/x"></video>'
        body += b'<p style="background:url(http://private.invalid/x)">http://private.invalid/plain</p>'
        self.assertEqual(self.observe(body)["counts"]["inspected_attributes"], 0)
        nested = self.observe(b'<template><noscript><img src="http://private.invalid/"></noscript></template><img src="http://one.invalid/"/>')
        self.assertEqual(nested["counts"]["http_absolute"], 1)

    def test_duplicate_selected_attrs_incomplete_or_ambiguous_containers_withhold_all_counts(self):
        good = b'<img src="http://one.invalid/">'
        for malformed in (b'<img src="http://one.invalid/" SRC="https://other.invalid/">', b'<link rel="stylesheet" rel="canonical" href="http://x.invalid/">',
            b'<template>', b'</template>', b'<script src="http://x.invalid/"/>', b'<iframe/>', b'<template><noscript></template></noscript>',
            b'<img src="http://x.invalid/', b'<!-- incomplete', b'<script>unterminated', b'<plaintext>rest'):
            with self.subTest(malformed=malformed):
                result = self.observe(good + malformed)
                self.assertEqual(result["state"], "unavailable"); self.assertTrue(all(value is None for value in result["counts"].values()))

    def test_original_complete_body_type_encoding_byte_bounds_and_exact_inventory_limits(self):
        for body, changes, reason in ((None, {}, "body_unavailable"), ("html", {}, "body_unavailable"), (b"", {"body_complete": False}, "body_incomplete"),
            (b"", {"body_complete": 1}, "body_incomplete"), (b"\xff", {}, "invalid_utf8"), (b"<p>\0</p>", {}, "invalid_body"),
            (b"x" * (MAX_BODY_BYTES + 1), {}, "body_limit"), ("界".encode() * (MAX_BODY_BYTES // 3 + 1), {}, "body_limit")):
            with self.subTest(reason=reason):
                result = self.observe(body, **changes); self.assertEqual(result["reason"], reason)
                self.assertTrue(all(value is None for value in result["counts"].values()))
        self.assertEqual(self.observe(b"x" * MAX_BODY_BYTES)["state"], "observed")
        at_limit = b'<img src="http://x.invalid/">' * MAX_REFERENCES
        self.assertEqual(self.observe(at_limit)["counts"]["http_absolute"], MAX_REFERENCES)
        beyond = self.observe(at_limit + b"<img src>")
        self.assertEqual(beyond["reason"], "reference_limit"); self.assertIsNone(beyond["counts"]["http_absolute"])
        self.assertEqual(self.observe(b'<template>' * 101)["state"], "unavailable")

    def test_no_original_object_mutation_and_no_retained_reference_bodies(self):
        original = b'\xef\xbb\xbf<img src="https://public.invalid/?private=secret">'
        one = self.observe(original); one["counts"]["https_absolute"] = 999
        two = self.observe(original); self.assertEqual(two["counts"]["https_absolute"], 1)
        self.assertNotIn("secret", json.dumps(two)); self.assertEqual(original, b'\xef\xbb\xbf<img src="https://public.invalid/?private=secret">')
