from hashlib import sha256
import json
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from tenancy.models import ProjectConfiguration
from . import competitor_fetch as collector, competitor_schema as schema, test_competitor_fetch as fixtures
from .competitor_collection import validate_result
from .competitor_source import current_competitor_source
from .crawling import FetchError
from .models import CrawlRun, JobRun


class CompetitorSchemaFetchTests(TestCase):
    setUp = fixtures.CompetitorFetchTests.setUp
    transport = fixtures.CompetitorFetchTests.transport
    document = fixtures.CompetitorFetchTests.document
    robots = fixtures.CompetitorFetchTests.robots
    revoke = fixtures.CompetitorFetchTests.revoke
    HTML = (b'<title>Private transient title</title><script type="application/ld+json">'
        b'{"@context":"https://private.invalid/context","@type":"Article","email":"private@example.invalid"}</script>')

    def collect(self, *args, **kwargs):
        return fixtures.CompetitorFetchTests.collect(self, *args, producer=collector.collect_competitor_schema, **kwargs)

    def test_genuine_current_binding_pinned_complete_original_schema_private_no_write_network_and_old_denial(self):
        with patch("jobs.crawling._system_resolver", side_effect=AssertionError("No real DNS")), CaptureQueriesContext(connection) as queries:
            result = self.collect()
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual(result["method_version"], collector.SCHEMA_METHOD)
        self.assertEqual(result["state"], "collected")
        self.assertEqual(result["evidence"]["method_version"], schema.METHOD)
        self.assertEqual(result["evidence"]["summary"], {"json_ld_blocks": 1, "typed_nodes": 1,
            "types": ["Article"], "unrecognized_type_count": 0})
        self.assertEqual(result["observed_at"], result["evidence"]["observed_at"])
        self.assertEqual(result["evidence"]["body_sha256"], sha256(self.HTML).hexdigest())
        self.assertEqual(self.waits, [1])
        self.assertEqual([args for args, _ in self.connections], [("https", "93.184.216.34", "competitor.example.invalid", 443)] * 2)
        for _args, conn in self.connections: conn.close.assert_called_once()
        self.assertNotIn("private", json.dumps(result))
        self.assertFalse(JobRun.objects.exists()); self.assertFalse(CrawlRun.objects.exists())
        binding = current_competitor_source(project=self.project, actor=self.owner,
            data={"origin": fixtures.COMPETITOR, "collection_permission": True})
        with self.assertRaises(ValidationError): validate_result(result, binding)

    def test_genuine_robots_restrictions_missing_status_no_follow_and_bad_framing(self):
        for body in (b"User-agent: *\nDisallow: /", b"User-agent: *\nDisallow: /*", b"User-agent: *\nRequest-rate : 1/60", b"unknown"):
            with self.subTest(body=body):
                result = self.collect([self.robots(body)])
                self.assertEqual(result["state"], "unavailable"); self.assertEqual(len(self.connections), 1)
                self.assertNotIn("evidence", result)
        for status in ("404 Not Found", "410 Gone"):
            self.assertEqual(self.collect([self.robots(status=status), self.document()])["state"], "collected")
        result = self.collect([self.robots(), self.document(status="302 Found", fields=b"Location: https://private.invalid/\r\n")])
        self.assertEqual(result["error_category"], "competitor_document_http_status")
        self.assertEqual(len(self.connections), 2)
        for fields in (b"Content-Type: text/html; charset=utf-8\r\n",
            f"Content-Length: {len(self.HTML) + 1}\r\nContent-Type: text/html; charset=utf-8\r\n".encode()):
            self.assertEqual(self.collect([self.robots(), self.document(fields=fields)])["state"], "unavailable")
        result = self.collect([self.robots(), self.document(b'<script type="application/ld+json">{"@type":</script>')])
        self.assertEqual(result["state"], "collected"); self.assertEqual(result["evidence"]["state"], "unavailable")
        self.assertIsNone(result["evidence"]["summary"])

    def test_original_role_config_binding_loss_at_dns_connection_body_pacing_projection_never_delivers(self):
        for hook in ({"resolver_effect": lambda _count: self.revoke()}, {"connected": lambda _count: self.revoke()},
            {"read": lambda count: self.revoke() if count == 2 else None}, {"sleep_effect": self.revoke},
            {"connected": lambda _count: ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)}):
            with self.subTest(hook=hook), transaction.atomic():
                with self.assertRaises(PermissionDenied): self.collect(**hook)
                transaction.set_rollback(True)
        original = collector.observe_static_schema
        def changed(**kwargs):
            result = original(**kwargs)
            ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[fixtures.COMPETITOR])
            return result
        with patch.object(collector, "observe_static_schema", side_effect=changed), self.assertRaises(PermissionDenied): self.collect()

    def test_owning_commercial_cancel_guards_and_exact_deadline_after_projection(self):
        for boundary in ("connected", "completion", "pacing", "projection"):
            active = [True]
            def deny():
                if not active[0]: raise PermissionDenied
            change = lambda *_: active.__setitem__(0, False)
            original = collector.observe_static_schema
            def projected(**kwargs):
                result = original(**kwargs); change(); return result
            hooks = {"connected": change} if boundary == "connected" else {"read": change} if boundary == "completion" else {"sleep_effect": change} if boundary == "pacing" else {}
            with self.subTest(boundary=boundary), patch.object(collector, "observe_static_schema", side_effect=projected if boundary == "projection" else original), self.assertRaises(PermissionDenied):
                self.collect(checkpoint=deny, **hooks)
        stamps = []
        def late(**kwargs):
            stamps.append(kwargs["observed_at"])
            result = original(**kwargs); self.now = 30; return result
        with patch.object(collector, "observe_static_schema", side_effect=late): result = self.collect()
        self.assertEqual(result, {"method_version": collector.SCHEMA_METHOD, "state": "unavailable", "error_category": "competitor_document_deadline"})
        self.assertEqual(len(stamps), 1)
        self.assertEqual(len(self.connections), 2)

    def test_frozen_binding_and_original_http_source_do_not_reconstruct_or_cross_scheme(self):
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

    def test_unknown_transport_error_remains_fixed_private_category_no_raw_payload(self):
        def failed(_count): raise FetchError("private-fixture-contact@example.invalid")
        self.assertEqual(self.collect(connected=failed), {"method_version": collector.SCHEMA_METHOD,
            "state": "unavailable", "error_category": "competitor_document_failed"})
        self.connections[0][1].request.assert_not_called()
