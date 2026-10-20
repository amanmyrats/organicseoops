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
from .competitor_collection import validate_result
from .competitor_schema_collection import validate_result as validate_schema_result
from .competitor_links_collection import validate_result as validate_links_result
from .competitor_page_collection import validate_result as validate_page_result
from .competitor_page_headings_collection import validate_result as validate_headings_result
from .competitor_page_source import current_competitor_page_source
from .competitor_source import current_competitor_source
from .crawling import FetchError
from .models import CrawlRun, JobRun, UsageReservation


class CompetitorPageDestinationsFetchTests(TestCase):
    setUp = fixtures.CompetitorFetchTests.setUp
    transport = fixtures.CompetitorFetchTests.transport
    document = fixtures.CompetitorFetchTests.document
    robots = fixtures.CompetitorFetchTests.robots
    revoke = fixtures.CompetitorFetchTests.revoke
    HTML = b'<title>Unretained title</title><a href="../one">One <em>inline</em></a><a href="/two">Two</a><a href="/one">Repeated</a><a href="https://unretained.invalid/">External</a><a href="/search?token=secret">Query</a><p>private-contact@example.invalid</p>'
    PATH = "/selected/article"

    def binding(self, origin=fixtures.COMPETITOR, path=None):
        return current_competitor_page_source(project=self.project, actor=self.owner,
            data={"origin": origin, "url": origin + (path or self.PATH), "collection_permission": True})

    def collect(self, *args, binding=None, origin=fixtures.COMPETITOR, **kwargs):
        return fixtures.CompetitorFetchTests.collect(self, *args, binding=binding or self.binding(origin), origin=origin,
            producer=collector.collect_competitor_page_destinations, **kwargs)

    def test_actual_source_pinned_complete_identity_gzip_original_uri_date_bytes_privacy_and_no_write(self):
        for encoding in ("identity", "gzip"):
            body = self.HTML if encoding == "identity" else gzip.compress(self.HTML)
            document = self.document(body, fields=f"Content-Length: {len(body)}\r\nContent-Type: text/html; charset=utf-8\r\nContent-Encoding: {encoding}\r\nSet-Cookie: private=secret\r\n".encode())
            with self.subTest(encoding=encoding), patch("jobs.crawling._system_resolver", side_effect=AssertionError("No real DNS")), CaptureQueriesContext(connection) as queries:
                result = self.collect([self.robots(), document])
            self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
            self.assertEqual(result["method_version"], collector.PAGE_DESTINATIONS_METHOD)
            self.assertEqual(result["interpretation"], collector.PAGE_INTERPRETATION)
            self.assertEqual(result["state"], "collected")
            self.assertEqual(result["requested_url"], fixtures.COMPETITOR + self.PATH)
            self.assertEqual(result["url"], result["evidence"]["url"])
            self.assertEqual(result["observed_at"], result["evidence"]["observed_at"])
            self.assertEqual(result["source_sha256"], self.binding()["source_sha256"])
            self.assertEqual(result["evidence"]["destinations"], [fixtures.COMPETITOR + "/one", fixtures.COMPETITOR + "/two", fixtures.COMPETITOR + "/one"])
            self.assertEqual(result["evidence"]["counts"], {"href_anchors": 5, "same_origin_http": 3, "other_origin_http": 1, "unsupported": 1})
            self.assertEqual(result["evidence"]["body_sha256"], sha256(self.HTML).hexdigest())
            self.assertEqual(result["evidence"]["body_size_bytes"], len(self.HTML))
            self.assertEqual([args for args, _ in self.connections], [("https", "93.184.216.34", "competitor.example.invalid", 443)] * 2)
            self.assertEqual([conn.request.call_args.args for _, conn in self.connections], [("GET", "/robots.txt"), ("GET", self.PATH)])
            for _, conn in self.connections: conn.close.assert_called_once()
            self.assertEqual(self.waits, [1]); self.assertLessEqual(len(json.dumps(result).encode()), 8192)
            for value in ("private-contact", "Set-Cookie", "secret", "<title>", "Unretained title", "<em>", "One inline", "unretained.invalid", "token="): self.assertNotIn(value, json.dumps(result))
            self.assertFalse(JobRun.objects.exists()); self.assertFalse(CrawlRun.objects.exists()); self.assertFalse(UsageReservation.objects.exists())
            for validator in (validate_result, validate_schema_result, validate_links_result, validate_page_result, validate_headings_result):
                with self.assertRaises(ValidationError): validator(result, self.binding())

    def test_selected_path_robots_no_root_fallback_discovery_redirect_or_unavailable_zero_confusion(self):
        for body in (b"User-agent: *\nDisallow: /selected/", b"User-agent: *\nDisallow: /selected/article", b"User-agent: *\nDisallow: /*", b"unknown"):
            with self.subTest(body=body):
                result = self.collect([self.robots(body)])
                self.assertEqual(result["state"], "unavailable"); self.assertEqual(len(self.connections), 1)
                self.assertNotIn("evidence", result)
        result = self.collect([self.robots(b"User-agent: *\nDisallow: /other\n"), self.document()])
        self.assertEqual(result["state"], "collected")
        for status in ("404 Not Found", "410 Gone"):
            self.assertEqual(self.collect([self.robots(status=status), self.document()])["robots"], "missing_http_404_or_410")
        for destination in ("/", "/other", "http://competitor.example.invalid/selected/article", "https://foreign.example.invalid/"):
            result = self.collect([self.robots(), self.document(status="302 Found", fields=f"Location: {destination}\r\n".encode())])
            self.assertEqual(result["error_category"], "competitor_document_http_status"); self.assertEqual(len(self.connections), 2)
            self.connections[1][1].getresponse.return_value.read1.assert_not_called()
        for fields in (b"Content-Type: text/html; charset=utf-8\r\n", f"Content-Length: {len(self.HTML)+1}\r\nContent-Type: text/html; charset=utf-8\r\n".encode()):
            self.assertEqual(self.collect([self.robots(), self.document(fields=fields)])["state"], "unavailable")
        result = self.collect([self.robots(), self.document(b"<title>Unclosed")])
        self.assertEqual(result["state"], "collected"); self.assertIsNone(result["evidence"]["destinations"])
        self.assertTrue(all(value is None for value in result["evidence"]["counts"].values()))
        result = self.collect([self.robots(), self.document(b"<p>No selected metadata</p>")])
        self.assertEqual(result["evidence"]["state"], "observed")
        self.assertEqual(result["evidence"]["destinations"], [])
        self.assertTrue(all(value == 0 for value in result["evidence"]["counts"].values()))

    def test_current_full_source_loss_at_dns_connected_body_pacing_and_final_projection_withholds_result(self):
        for hook in ({"resolver_effect": lambda _count: self.revoke()}, {"connected": lambda _count: self.revoke()},
            {"read": lambda count: self.revoke() if count == 2 else None}, {"sleep_effect": self.revoke},
            {"connected": lambda _count: ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)}):
            with self.subTest(hook=hook), transaction.atomic():
                with self.assertRaises(PermissionDenied): self.collect(**hook)
                transaction.set_rollback(True)
        original = collector.observe_static_destinations
        def projected(**kwargs):
            result = original(**kwargs)
            ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[fixtures.COMPETITOR])
            return result
        with patch.object(collector, "observe_static_destinations", side_effect=projected), self.assertRaises(PermissionDenied): self.collect()

    def test_owning_commercial_cancel_loss_brackets_source_reads_connected_completion_pacing_projection(self):
        original = collector.observe_static_destinations
        for boundary in ("source_read", "connected", "completion", "pacing", "projection"):
            active = [True]
            def deny():
                if not active[0]: raise PermissionDenied
            change = lambda *_: active.__setitem__(0, False)
            def projected(**kwargs):
                result = original(**kwargs); change(); return result
            reader = collector.current_competitor_page_source
            def during_read(**kwargs):
                result = reader(**kwargs); change(); return result
            hooks = {"connected": change} if boundary == "connected" else {"read": change} if boundary == "completion" else {"sleep_effect": change} if boundary == "pacing" else {}
            with self.subTest(boundary=boundary), patch.object(collector, "current_competitor_page_source", side_effect=during_read if boundary == "source_read" else reader), patch.object(collector, "observe_static_destinations", side_effect=projected if boundary == "projection" else original), self.assertRaises(PermissionDenied):
                self.collect(checkpoint=deny, **hooks)
            if boundary == "source_read": self.assertEqual(self.connections, [])

    def test_frozen_exact_binding_original_http_and_no_root_or_foreign_source_reconstruction(self):
        binding = self.binding(); expected = dict(binding)
        result = self.collect(binding=binding, connected=lambda _count: binding.update(url=fixtures.COMPETITOR + "/unselected", source_sha256="0"*64))
        self.assertEqual(result["source_sha256"], expected["source_sha256"])
        self.assertEqual(result["requested_url"], expected["url"])
        self.assertEqual(self.connections[1][1].request.call_args.args, ("GET", self.PATH))
        for data in (binding, {**expected, "url": fixtures.COMPETITOR + "/other"}, {**expected, "url": "http://competitor.example.invalid/selected/article"},
            current_competitor_source(project=self.project, actor=self.owner, data={"origin": fixtures.COMPETITOR, "collection_permission": True})):
            with self.subTest(data=data), self.assertRaises((PermissionDenied, ValidationError)):
                self.collect(binding=data)
        ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=["http://competitor.example.invalid"])
        result = self.collect(origin="http://competitor.example.invalid")
        self.assertEqual(result["requested_url"], "http://competitor.example.invalid" + self.PATH)
        self.assertEqual([args[0] for args, _ in self.connections], ["http", "http"])

    def test_original_capture_date_deadline_and_fixed_unknown_error_no_private_payload(self):
        original = collector.observe_static_destinations; stamps = []
        def delayed(**kwargs):
            stamps.append(kwargs["observed_at"]); result = original(**kwargs); self.now = 4; return result
        with patch.object(collector, "observe_static_destinations", side_effect=delayed): result = self.collect()
        self.assertEqual(result["observed_at"], stamps[0])
        def late(**kwargs):
            result = original(**kwargs); self.now = 30; return result
        with patch.object(collector, "observe_static_destinations", side_effect=late): result = self.collect()
        self.assertEqual(result, {"method_version": collector.PAGE_DESTINATIONS_METHOD, "state": "unavailable", "error_category": "competitor_document_deadline"})
        result = self.collect(sleep_effect=lambda: setattr(self, "now", 31))
        self.assertEqual(result["error_category"], "competitor_document_deadline"); self.assertEqual(len(self.connections), 1)
        def failed(_count): raise FetchError("private-contact@example.invalid")
        self.assertEqual(self.collect(connected=failed), {"method_version": collector.PAGE_DESTINATIONS_METHOD, "state": "unavailable", "error_category": "competitor_document_failed"})
        self.connections[0][1].request.assert_not_called()

    def test_inventory_limits_and_original_whole_producer_result_cap_preserve_unknown(self):
        for body, reason in ((b'<base><a href="/one">x</a>', "base_dependent_references"),
            (b'<a href="/one">x</a>' * 11, "destination_limit"),
            ((b'<a href="/' + b'x' * 970 + b'">x</a>') * 10, "result_limit")):
            result = self.collect([self.robots(), self.document(body)])
            self.assertEqual(result["state"], "collected")
            self.assertEqual((result["evidence"]["state"], result["evidence"]["reason"]), ("unavailable", reason))
            self.assertIsNone(result["evidence"]["destinations"])
            self.assertTrue(all(value is None for value in result["evidence"]["counts"].values()))
            self.assertEqual(len(self.connections), 2)
        # Complete evidence fits its own cap; the original complete producer envelope
        # independently rejects overflow rather than silently retaining partial URLs.
        result = self.collect([self.robots(), self.document((b'<a href="/' + b'x' * 660 + b'">x</a>') * 10)])
        self.assertEqual(result, {"method_version": collector.PAGE_DESTINATIONS_METHOD,
            "state": "unavailable", "error_category": "competitor_document_result_limit"})
        self.assertEqual(len(self.connections), 2)
