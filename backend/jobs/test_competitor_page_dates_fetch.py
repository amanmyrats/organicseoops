import gzip
from hashlib import sha256
import json
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from tenancy.models import ProjectConfiguration
from . import competitor_fetch as collector, test_competitor_fetch as fixtures
from . import competitor_collection, competitor_schema_collection, competitor_links_collection, competitor_page_collection
from . import competitor_page_headings_collection, competitor_page_destinations_collection
from .competitor_page_source import current_competitor_page_source
from .competitor_source import current_competitor_source
from .crawling import FetchError
from .models import CrawlRun, JobRun, UsageReservation


class CompetitorPageDatesFetchTests(TestCase):
    setUp = fixtures.CompetitorFetchTests.setUp
    transport = fixtures.CompetitorFetchTests.transport
    document = fixtures.CompetitorFetchTests.document
    robots = fixtures.CompetitorFetchTests.robots
    revoke = fixtures.CompetitorFetchTests.revoke
    HTML = (b'<title>Unretained title</title><meta property="article:published_time" content="2099-01-01">'
        b'<meta property="article:modified_time" content="Unknown &amp; unverified">'
        b'<meta property="article:modified_time" content="Unknown &amp; unverified"><p>private-contact@example.invalid</p>')
    PATH = "/selected/article"

    def binding(self, origin=fixtures.COMPETITOR):
        return current_competitor_page_source(project=self.project, actor=self.owner,
            data={"origin": origin, "url": origin + self.PATH, "collection_permission": True})

    def collect(self, *args, binding=None, origin=fixtures.COMPETITOR, **kwargs):
        return fixtures.CompetitorFetchTests.collect(self, *args, binding=binding or self.binding(origin), origin=origin,
            producer=collector.collect_competitor_page_dates, **kwargs)

    def test_genuine_pinned_identity_gzip_original_declarations_date_uri_integrity_privacy_and_no_write(self):
        for encoding in ("identity", "gzip"):
            body = self.HTML if encoding == "identity" else gzip.compress(self.HTML)
            document = self.document(body, fields=f"Content-Length: {len(body)}\r\nContent-Type: text/html; charset=utf-8\r\nContent-Encoding: {encoding}\r\nSet-Cookie: private=secret\r\n".encode())
            with self.subTest(encoding=encoding), patch("jobs.crawling._system_resolver", side_effect=AssertionError("No real DNS")), CaptureQueriesContext(connection) as queries:
                result = self.collect([self.robots(), document])
            self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
            self.assertEqual((result["method_version"], result["state"], result["interpretation"]), (collector.PAGE_DATES_METHOD, "collected", collector.PAGE_INTERPRETATION))
            self.assertEqual(result["requested_url"], fixtures.COMPETITOR + self.PATH)
            self.assertEqual(result["url"], result["evidence"]["url"]); self.assertEqual(result["observed_at"], result["evidence"]["observed_at"])
            self.assertEqual(result["source_sha256"], self.binding()["source_sha256"])
            self.assertEqual(result["evidence"]["declarations"], [
                {"property": "article:published_time", "value": "2099-01-01", "truncated": False},
                {"property": "article:modified_time", "value": "Unknown & unverified", "truncated": False},
                {"property": "article:modified_time", "value": "Unknown & unverified", "truncated": False}])
            self.assertEqual((result["evidence"]["body_sha256"], result["evidence"]["body_size_bytes"]), (sha256(self.HTML).hexdigest(), len(self.HTML)))
            self.assertEqual([args for args, _ in self.connections], [("https", "93.184.216.34", "competitor.example.invalid", 443)] * 2)
            self.assertEqual([conn.request.call_args.args for _, conn in self.connections], [("GET", "/robots.txt"), ("GET", self.PATH)])
            for _, conn in self.connections: conn.close.assert_called_once()
            self.assertEqual(self.waits, [1]); self.assertLessEqual(len(json.dumps(result).encode()), 8192)
            for value in ("private-contact", "Set-Cookie", "secret", "Unretained title", "age_days", "published_at"):
                self.assertNotIn(value, json.dumps(result))
            for family in (competitor_collection, competitor_schema_collection, competitor_links_collection, competitor_page_collection,
                competitor_page_headings_collection, competitor_page_destinations_collection):
                with self.assertRaises(ValidationError): family.validate_result(result, self.binding())
            self.assertFalse(JobRun.objects.exists()); self.assertFalse(CrawlRun.objects.exists()); self.assertFalse(UsageReservation.objects.exists())

    def test_robots_denied_unknown_status_framing_and_no_redirect_root_fallback_or_date_inference(self):
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
        unknown = self.collect([self.robots(), self.document(b'<meta property="article:modified_time">')])
        self.assertEqual(unknown["state"], "collected"); self.assertIsNone(unknown["evidence"]["declarations"])
        empty = self.collect([self.robots(), self.document(b"<p>No declarations</p>")])
        self.assertEqual(empty["evidence"]["state"], "observed"); self.assertEqual(empty["evidence"]["declarations"], [])

    def test_full_source_and_owning_loss_at_dns_connected_completion_pacing_projection_and_source_read_withhold(self):
        for hook in ({"resolver_effect": lambda _count: self.revoke()}, {"connected": lambda _count: self.revoke()},
            {"read": lambda count: self.revoke() if count == 2 else None}, {"sleep_effect": self.revoke},
            {"connected": lambda _count: ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)}):
            with self.subTest(hook=hook), transaction.atomic():
                with self.assertRaises(PermissionDenied): self.collect(**hook)
                transaction.set_rollback(True)
        original = collector.observe_static_dates
        def projected(**kwargs):
            result = original(**kwargs)
            ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[fixtures.COMPETITOR])
            return result
        with transaction.atomic():
            with patch.object(collector, "observe_static_dates", side_effect=projected), self.assertRaises(PermissionDenied): self.collect()
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
            with self.subTest(boundary=boundary), patch.object(collector, "current_competitor_page_source", side_effect=during_read if boundary == "source_read" else reader), patch.object(collector, "observe_static_dates", side_effect=project if boundary == "projection" else original), self.assertRaises(PermissionDenied):
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

    def test_capture_date_projection_delay_deadline_and_fixed_unknown_error_preserve_original_or_withhold(self):
        original = collector.observe_static_dates; stamps = []
        def delayed(**kwargs):
            stamps.append(kwargs["observed_at"]); result = original(**kwargs); self.now = 4; return result
        with patch.object(collector, "observe_static_dates", side_effect=delayed): result = self.collect()
        self.assertEqual(result["observed_at"], stamps[0])
        def late(**kwargs):
            result = original(**kwargs); self.now = 30; return result
        with patch.object(collector, "observe_static_dates", side_effect=late): result = self.collect()
        self.assertEqual(result, {"method_version": collector.PAGE_DATES_METHOD, "state": "unavailable", "error_category": "competitor_document_deadline"})
        result = self.collect(sleep_effect=lambda: setattr(self, "now", 31))
        self.assertEqual(result["error_category"], "competitor_document_deadline"); self.assertEqual(len(self.connections), 1)
        def failed(_count): raise FetchError("private-contact@example.invalid")
        self.assertEqual(self.collect(connected=failed), {"method_version": collector.PAGE_DATES_METHOD, "state": "unavailable", "error_category": "competitor_document_failed"})
        self.connections[0][1].request.assert_not_called()

    def test_whole_declaration_and_producer_limits_have_distinct_unknown_without_partial_success(self):
        tag = b'<meta property="article:published_time" content="2020-01-01">'
        limited = self.collect([self.robots(), self.document(tag * 11)])
        self.assertEqual((limited["state"], limited["evidence"]["reason"]), ("collected", "declaration_limit"))
        self.assertIsNone(limited["evidence"]["declarations"])
        body = ('<meta property="article:modified_time" content="' + "🙂" * 80 + '">').encode() * 10
        cap = len(json.dumps(self.binding()).encode()) + 200
        with patch.object(collector, "MAX_RESULT_BYTES", cap):
            limited = self.collect([self.robots(), self.document(body)])
        self.assertEqual(limited, {"method_version": collector.PAGE_DATES_METHOD, "state": "unavailable", "error_category": "competitor_document_result_limit"})
