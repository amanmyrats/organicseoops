import gzip
from hashlib import sha256
import json
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from tenancy.models import ProjectConfiguration
from . import competitor_fetch as collector, competitor_formats_fetch as producer, test_competitor_fetch as fixtures
from . import competitor_collection, competitor_schema_collection, competitor_links_collection, competitor_page_collection
from . import competitor_page_headings_collection, competitor_page_destinations_collection, competitor_page_dates_collection
from .competitor_page_source import current_competitor_page_source
from .competitor_source import current_competitor_source
from .crawling import FetchError
from .models import CrawlRun, JobRun, UsageReservation


class CompetitorFormatsFetchTests(TestCase):
    setUp = fixtures.CompetitorFetchTests.setUp
    transport = fixtures.CompetitorFetchTests.transport
    document = fixtures.CompetitorFetchTests.document
    robots = fixtures.CompetitorFetchTests.robots
    revoke = fixtures.CompetitorFetchTests.revoke
    HTML = b'<title>Unretained title</title><p>private-contact@example.invalid</p><ul><ul></ul></ul><table></table><img src="secret"/><video></video>'
    PATH = "/selected/article"

    def binding(self, origin=fixtures.COMPETITOR):
        return current_competitor_page_source(project=self.project, actor=self.owner,
            data={"origin": origin, "url": origin + self.PATH, "collection_permission": True})

    def collect(self, *args, binding=None, origin=fixtures.COMPETITOR, **kwargs):
        return fixtures.CompetitorFetchTests.collect(self, *args, binding=binding or self.binding(origin), origin=origin,
            producer=producer.collect_competitor_page_formats, **kwargs)

    def test_genuine_pinned_identity_gzip_original_counts_uri_date_integrity_privacy_no_write_and_old_family_separation(self):
        for encoding in ("identity", "gzip"):
            body = self.HTML if encoding == "identity" else gzip.compress(self.HTML)
            document = self.document(body, fields=f"Content-Length: {len(body)}\r\nContent-Type: text/html; charset=utf-8\r\nContent-Encoding: {encoding}\r\nSet-Cookie: private=secret\r\n".encode())
            with self.subTest(encoding=encoding), patch("jobs.crawling._system_resolver", side_effect=AssertionError("No real DNS")), CaptureQueriesContext(connection) as queries:
                result = self.collect([self.robots(), document])
            self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
            self.assertEqual((result["method_version"], result["state"], result["interpretation"]), (producer.METHOD, "collected", collector.PAGE_INTERPRETATION))
            self.assertEqual(result["requested_url"], fixtures.COMPETITOR + self.PATH)
            self.assertEqual(result["url"], result["evidence"]["url"]); self.assertEqual(result["observed_at"], result["evidence"]["observed_at"])
            self.assertEqual(result["source_sha256"], self.binding()["source_sha256"])
            self.assertEqual(result["evidence"]["counts"], {"p": 1, "ul": 2, "ol": 0, "table": 1, "img": 1, "picture": 0, "video": 1, "audio": 0})
            self.assertEqual((result["evidence"]["body_sha256"], result["evidence"]["body_size_bytes"]), (sha256(self.HTML).hexdigest(), len(self.HTML)))
            self.assertEqual([args for args, _ in self.connections], [("https", "93.184.216.34", "competitor.example.invalid", 443)] * 2)
            self.assertEqual([conn.request.call_args.args for _, conn in self.connections], [("GET", "/robots.txt"), ("GET", self.PATH)])
            for _, conn in self.connections: conn.close.assert_called_once()
            self.assertEqual(self.waits, [1]); self.assertLessEqual(len(json.dumps(result).encode()), 8192)
            for value in ("private-contact", "secret", "Unretained title", "Set-Cookie", "rendered_format"):
                self.assertNotIn(value, json.dumps(result))
            for family in (competitor_collection, competitor_schema_collection, competitor_links_collection, competitor_page_collection,
                competitor_page_headings_collection, competitor_page_destinations_collection, competitor_page_dates_collection):
                with self.assertRaises(ValidationError): family.validate_result(result, self.binding())
            self.assertFalse(JobRun.objects.exists()); self.assertFalse(CrawlRun.objects.exists()); self.assertFalse(UsageReservation.objects.exists())

    def test_robots_unknown_denied_status_framing_and_no_redirect_or_root_fallback(self):
        for body in (b"User-agent: *\nDisallow: /selected/", b"User-agent: *\nDisallow: /*", b"unknown"):
            result = self.collect([self.robots(body)]); self.assertEqual(result["state"], "unavailable"); self.assertEqual(len(self.connections), 1)
            self.assertNotIn("evidence", result)
        for status in ("404 Not Found", "410 Gone"):
            self.assertEqual(self.collect([self.robots(status=status), self.document()])["robots"], "missing_http_404_or_410")
        for destination in ("/", "/other", "http://competitor.example.invalid/selected/article", "https://foreign.example.invalid/"):
            result = self.collect([self.robots(), self.document(status="302 Found", fields=f"Location: {destination}\r\n".encode())])
            self.assertEqual(result["error_category"], "competitor_document_http_status"); self.assertEqual(len(self.connections), 2)
            self.connections[1][1].getresponse.return_value.read1.assert_not_called()
        self.assertEqual(self.collect([self.robots(), self.document(fields=b"Content-Type: text/html; charset=utf-8\r\n")])["state"], "unavailable")

    def test_full_source_and_owning_loss_at_dns_connected_completion_pacing_projection_and_source_read_withhold(self):
        for hook in ({"resolver_effect": lambda _count: self.revoke()}, {"connected": lambda _count: self.revoke()},
            {"read": lambda count: self.revoke() if count == 2 else None}, {"sleep_effect": self.revoke},
            {"connected": lambda _count: ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)}):
            with self.subTest(hook=hook), transaction.atomic():
                with self.assertRaises(PermissionDenied): self.collect(**hook)
                transaction.set_rollback(True)
        original = producer.observe_static_formats
        def projected(**kwargs):
            result = original(**kwargs); ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[fixtures.COMPETITOR]); return result
        with transaction.atomic():
            with patch.object(producer, "observe_static_formats", side_effect=projected), self.assertRaises(PermissionDenied): self.collect()
            transaction.set_rollback(True)
        for boundary in ("source_read", "connected", "completion", "pacing", "projection"):
            active = [True]
            def deny():
                if not active[0]: raise PermissionDenied
            def change(*_): active[0] = False
            def project(**kwargs):
                result = original(**kwargs); change(); return result
            reader = collector.current_competitor_page_source
            def during_read(**kwargs):
                result = reader(**kwargs); change(); return result
            hooks = {"connected": change} if boundary == "connected" else {"read": change} if boundary == "completion" else {"sleep_effect": change} if boundary == "pacing" else {}
            with self.subTest(boundary=boundary), patch.object(collector, "current_competitor_page_source", side_effect=during_read if boundary == "source_read" else reader), patch.object(producer, "observe_static_formats", side_effect=project if boundary == "projection" else original), self.assertRaises(PermissionDenied):
                self.collect(checkpoint=deny, **hooks)
            if boundary == "source_read": self.assertEqual(self.connections, [])

    def test_exact_binding_frozen_old_root_foreign_changed_uri_denied_and_http_original_preserved(self):
        binding = self.binding(); original = dict(binding)
        result = self.collect(binding=binding, connected=lambda _count: binding.update(url=fixtures.COMPETITOR + "/other", source_sha256="0" * 64))
        self.assertEqual(result["source_sha256"], original["source_sha256"]); self.assertEqual(result["requested_url"], original["url"])
        for changed in (binding, {**original, "url": fixtures.COMPETITOR + "/other"}, {**original, "url": "http://competitor.example.invalid" + self.PATH},
            current_competitor_source(project=self.project, actor=self.owner, data={"origin": fixtures.COMPETITOR, "collection_permission": True})):
            with self.subTest(changed=changed), self.assertRaises((PermissionDenied, ValidationError)): self.collect(binding=changed)
        ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=["http://competitor.example.invalid"])
        result = self.collect(origin="http://competitor.example.invalid")
        self.assertEqual(result["requested_url"], "http://competitor.example.invalid" + self.PATH)
        self.assertEqual([args[0] for args, _ in self.connections], ["http", "http"])

    def test_original_capture_date_projection_delay_deadline_and_fixed_private_unknown_error(self):
        original = producer.observe_static_formats; stamps = []
        def delayed(**kwargs):
            stamps.append(kwargs["observed_at"]); result = original(**kwargs); self.now = 4; return result
        with patch.object(producer, "observe_static_formats", side_effect=delayed): result = self.collect()
        self.assertEqual(result["observed_at"], stamps[0])
        def late(**kwargs):
            result = original(**kwargs); self.now = 30; return result
        with patch.object(producer, "observe_static_formats", side_effect=late): result = self.collect()
        self.assertEqual(result, {"method_version": producer.METHOD, "state": "unavailable", "error_category": "competitor_document_deadline"})
        result = self.collect(sleep_effect=lambda: setattr(self, "now", 31))
        self.assertEqual(result["error_category"], "competitor_document_deadline"); self.assertEqual(len(self.connections), 1)
        def failed(_count): raise FetchError("private-contact@example.invalid")
        self.assertEqual(self.collect(connected=failed), {"method_version": producer.METHOD, "state": "unavailable", "error_category": "competitor_document_failed"})
        self.connections[0][1].request.assert_not_called()

    def test_known_empty_parser_unknown_existing_metadata_and_result_caps_do_not_become_zero(self):
        empty = self.collect([self.robots(), self.document(b"<h1>No selected elements</h1>")])
        self.assertEqual(empty["evidence"]["state"], "observed"); self.assertTrue(all(value == 0 for value in empty["evidence"]["counts"].values()))
        for body in (b"<p>" * 1001, b"<h1>" * 1001, b"<template><img"):
            result = self.collect([self.robots(), self.document(body)])
            self.assertEqual(result["state"], "collected"); self.assertEqual(result["evidence"]["state"], "unavailable")
            self.assertTrue(all(value is None for value in result["evidence"]["counts"].values()))
        with patch.object(collector, "MAX_RESULT_BYTES", len(json.dumps(self.binding()).encode()) + 100):
            result = self.collect()
        self.assertEqual(result, {"method_version": producer.METHOD, "state": "unavailable", "error_category": "competitor_document_result_limit"})
