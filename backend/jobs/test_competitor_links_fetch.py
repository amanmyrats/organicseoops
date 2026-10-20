import gzip
from hashlib import sha256
import json
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from tenancy.models import ProjectConfiguration
from . import competitor_fetch as collector, competitor_links as links, test_competitor_fetch as fixtures
from .competitor_collection import validate_result
from .competitor_schema_collection import validate_result as validate_schema_result
from .competitor_source import current_competitor_source
from .crawling import FetchError
from .models import CrawlRun, JobRun


class CompetitorLinksFetchTests(TestCase):
    setUp = fixtures.CompetitorFetchTests.setUp
    transport = fixtures.CompetitorFetchTests.transport
    document = fixtures.CompetitorFetchTests.document
    robots = fixtures.CompetitorFetchTests.robots
    revoke = fixtures.CompetitorFetchTests.revoke
    HTML = (b'<title>Private transient title</title><a href="/private-contact">Unretained text</a>'
        b'<a href="//external.example.invalid/">External</a><a href="mailto:private@example.invalid">Contact</a>')

    def collect(self, *args, **kwargs):
        return fixtures.CompetitorFetchTests.collect(self, *args, producer=collector.collect_competitor_links, **kwargs)

    def test_genuine_original_binding_complete_transport_count_provenance_privacy_no_writes_and_old_contract_denial(self):
        for encoding in ("identity", "gzip"):
            body = self.HTML if encoding == "identity" else gzip.compress(self.HTML)
            document = self.document(body, fields=f"Content-Length: {len(body)}\r\nContent-Type: text/html; charset=utf-8\r\nContent-Encoding: {encoding}\r\nSet-Cookie: private=secret\r\n".encode())
            with self.subTest(encoding=encoding), patch("jobs.crawling._system_resolver", side_effect=AssertionError("No real DNS")), CaptureQueriesContext(connection) as queries:
                result = self.collect([self.robots(), document])
            self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
            self.assertEqual(result["method_version"], collector.LINKS_METHOD)
            self.assertEqual(result["state"], "collected")
            self.assertEqual(result["evidence"]["method_version"], links.METHOD)
            self.assertEqual(result["evidence"]["counts"], {"href_anchors": 3, "same_origin_http": 1, "other_origin_http": 1, "unsupported": 1})
            self.assertEqual(result["observed_at"], result["evidence"]["observed_at"])
            self.assertEqual(result["evidence"]["body_sha256"], sha256(self.HTML).hexdigest())
            self.assertEqual(result["evidence"]["body_size_bytes"], len(self.HTML))
            self.assertEqual(self.waits, [1])
            self.assertEqual([args for args, _ in self.connections], [("https", "93.184.216.34", "competitor.example.invalid", 443)] * 2)
            for _args, conn in self.connections: conn.close.assert_called_once()
            for value in ("private", "External", "external.example", "Contact", "Set-Cookie"):
                self.assertNotIn(value, json.dumps(result))
            self.assertLessEqual(len(json.dumps(result).encode()), 8192)
            self.assertFalse(JobRun.objects.exists()); self.assertFalse(CrawlRun.objects.exists())
            binding = current_competitor_source(project=self.project, actor=self.owner,
                data={"origin": fixtures.COMPETITOR, "collection_permission": True})
            for validator in (validate_result, validate_schema_result):
                with self.assertRaises(ValidationError): validator(result, binding)

    def test_actual_restrictions_missing_robots_no_follow_strict_framing_and_null_versus_empty(self):
        for body in (b"User-agent: *\nDisallow: /", b"User-agent: *\nDisallow: /*", b"User-agent: *\nRequest-rate : 1/60", b"unknown"):
            with self.subTest(body=body):
                result = self.collect([self.robots(body)])
                self.assertEqual(result["state"], "unavailable"); self.assertEqual(len(self.connections), 1)
                self.assertNotIn("evidence", result)
        for status in ("404 Not Found", "410 Gone"):
            self.assertEqual(self.collect([self.robots(status=status), self.document()])["state"], "collected")
        result = self.collect([self.robots(), self.document(status="302 Found", fields=b"Location: http://competitor.example.invalid/\r\n")])
        self.assertEqual(result["error_category"], "competitor_document_http_status")
        self.assertEqual(len(self.connections), 2)
        for fields in (b"Content-Type: text/html; charset=utf-8\r\n",
            f"Content-Length: {len(self.HTML) + 1}\r\nContent-Type: text/html; charset=utf-8\r\n".encode()):
            self.assertEqual(self.collect([self.robots(), self.document(fields=fields)])["state"], "unavailable")
        for body in (b'<a href="/path">x</a><base>', b'<a href="/path">Open'):
            result = self.collect([self.robots(), self.document(body)])
            self.assertEqual(result["state"], "collected"); self.assertEqual(result["evidence"]["state"], "unavailable")
            self.assertTrue(all(value is None for value in result["evidence"]["counts"].values()))
        result = self.collect([self.robots(), self.document(b"<p>No anchors</p>")])
        self.assertEqual(result["evidence"]["state"], "observed")
        self.assertEqual(result["evidence"]["counts"], dict.fromkeys(links.COUNTS, 0))

    def test_current_source_loss_at_dns_connected_body_pacing_and_after_projection_withholds_result(self):
        for hook in ({"resolver_effect": lambda _count: self.revoke()}, {"connected": lambda _count: self.revoke()},
            {"read": lambda count: self.revoke() if count == 2 else None}, {"sleep_effect": self.revoke},
            {"connected": lambda _count: ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)}):
            with self.subTest(hook=hook), transaction.atomic():
                with self.assertRaises(PermissionDenied): self.collect(**hook)
                transaction.set_rollback(True)
        original = collector.observe_static_links
        def changed(**kwargs):
            result = original(**kwargs)
            ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[fixtures.COMPETITOR])
            return result
        with patch.object(collector, "observe_static_links", side_effect=changed), self.assertRaises(PermissionDenied): self.collect()

    def test_owning_commercial_cancel_loss_and_original_capture_deadline_after_projection(self):
        original = collector.observe_static_links
        for boundary in ("connected", "completion", "pacing", "projection"):
            active = [True]
            def deny():
                if not active[0]: raise PermissionDenied
            change = lambda *_: active.__setitem__(0, False)
            def projected(**kwargs):
                result = original(**kwargs); change(); return result
            hooks = {"connected": change} if boundary == "connected" else {"read": change} if boundary == "completion" else {"sleep_effect": change} if boundary == "pacing" else {}
            with self.subTest(boundary=boundary), patch.object(collector, "observe_static_links", side_effect=projected if boundary == "projection" else original), self.assertRaises(PermissionDenied):
                self.collect(checkpoint=deny, **hooks)
        stamps = []
        def delayed(**kwargs):
            stamps.append(kwargs["observed_at"])
            result = original(**kwargs); self.now = 4; return result
        with patch.object(collector, "observe_static_links", side_effect=delayed): result = self.collect()
        self.assertEqual(result["observed_at"], stamps[0])
        def late(**kwargs):
            result = original(**kwargs); self.now = 30; return result
        with patch.object(collector, "observe_static_links", side_effect=late): result = self.collect()
        self.assertEqual(result, {"method_version": collector.LINKS_METHOD, "state": "unavailable", "error_category": "competitor_document_deadline"})

    def test_frozen_binding_exact_http_source_and_fixed_unknown_error_category(self):
        binding = current_competitor_source(project=self.project, actor=self.owner,
            data={"origin": fixtures.COMPETITOR, "collection_permission": True})
        expected = binding["source_sha256"]
        result = self.collect(binding=binding, connected=lambda _count: binding.update(source_sha256="0" * 64))
        self.assertEqual(result["source_sha256"], expected)
        with self.assertRaises(PermissionDenied): self.collect(binding=binding)
        ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=["http://competitor.example.invalid"])
        result = self.collect(origin="http://competitor.example.invalid")
        self.assertEqual(result["state"], "collected")
        self.assertEqual(result["requested_url"], "http://competitor.example.invalid/")
        self.assertEqual([args[0] for args, _ in self.connections], ["http", "http"])
        self.assertEqual(result["evidence"]["counts"]["other_origin_http"], 1)
        def failed(_count): raise FetchError("private-fixture-contact@example.invalid")
        self.assertEqual(self.collect(origin="http://competitor.example.invalid", connected=failed),
            {"method_version": collector.LINKS_METHOD, "state": "unavailable", "error_category": "competitor_document_failed"})
        self.connections[0][1].request.assert_not_called()
