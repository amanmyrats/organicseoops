import gzip
import json
from unittest.mock import Mock, patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tenancy.models import OrganizationMembership, ProjectConfiguration
from . import competitor_fetch as collector
from .competitor_source import current_competitor_source
from .crawling import CrawlScope, FetchDenied, FetchError, SafeFetcher
from .models import CrawlRun, JobRun
from . import test_competitor_source as source_fixtures
from . import test_passive_resource_transport as transport_fixtures

COMPETITOR = source_fixtures.COMPETITOR


class StaticDocumentTransportTests(SimpleTestCase):
    transport = transport_fixtures.PassiveResourceTransportTests.transport
    HTML = b'<title>Fixture</title><p>Private transient document</p>'
    URL = "https://example.com/public"

    def fetch(self, fetcher, **changes):
        return fetcher.fetch(**{"url": self.URL, "static_document_type": "text/html", "before_request": Mock(),
            "before_send": Mock(), **changes})

    def test_original_split_utf8_identity_gzip_capture_minimal_headers_and_default_unchanged(self):
        for encoding in ("identity", "gzip"):
            body = self.HTML if encoding == "identity" else gzip.compress(self.HTML)
            fetcher, conn, response, factory, _ = self.transport(body, fields=(f"Content-Length: {len(body)}\r\n"
                f"Content-Type: text/html; charset=utf-8\r\nContent-Encoding: {encoding}\r\nSet-Cookie: private=secret\r\n").encode())
            before, send = Mock(), Mock()
            start = timezone.now()
            result = self.fetch(fetcher, before_request=before, before_send=send)
            self.assertEqual(result.body, self.HTML)
            self.assertEqual(result.headers, {"content-type": "text/html"})
            self.assertEqual(result.redirects, ())
            self.assertLessEqual(start.isoformat(timespec="microseconds"), result.observed_at)
            self.assertLessEqual(result.observed_at, timezone.now().isoformat(timespec="microseconds"))
            self.assertEqual(before.call_count, 1); self.assertEqual(send.call_count, 3)
            self.assertGreater(response.read1.call_count, 2)
            self.assertEqual(factory.call_args.args[:4], ("https", "93.184.216.34", "example.com", 443))
            conn.close.assert_called_once()
        fetcher, *_ = self.transport()
        ordinary = fetcher.fetch(self.URL)
        self.assertEqual(ordinary.body, self.HTML); self.assertIsNone(ordinary.observed_at)

    def test_robots_plain_utf8_with_optional_charset_and_http_default_port(self):
        for kind in ("text/plain", "text/plain; charset=utf-8", 'TEXT/PLAIN; charset="UTF-8"'):
            body = b"User-agent: *\nDisallow:\n"
            fetcher, _, _, factory, _ = self.transport(body, fields=f"Content-Length: {len(body)}\r\nContent-Type: {kind}\r\n".encode())
            result = self.fetch(fetcher, url="http://example.com/robots.txt", static_document_type="text/plain")
            self.assertEqual(result.body, body); self.assertEqual(result.headers, {"content-type": "text/plain"})
            self.assertEqual(factory.call_args.args[:4], ("http", "93.184.216.34", "example.com", 80))

    def test_non200_status_only_never_reads_follows_or_returns_raw_headers(self):
        for status in ("302 Found", "304 Not Modified", "403 Forbidden", "404 Not Found", "410 Gone", "503 Unavailable"):
            fetcher, conn, response, factory, resolver = self.transport(status=status,
                fields=b"Location: http://169.254.169.254/private\r\nSet-Cookie: private=secret\r\n")
            result = self.fetch(fetcher)
            self.assertEqual((result.body, result.headers, result.redirects), (b"", {}, ()))
            self.assertIsNotNone(result.observed_at)
            response.read1.assert_not_called(); factory.assert_called_once(); resolver.assert_called_once(); conn.close.assert_called_once()

    def test_input_modes_callbacks_and_canonical_urls_deny_before_dns(self):
        for changes in ({"static_document_type": True}, {"static_document_type": []}, {"static_document_type": "application/json"},
            {"observe_headers": True}, {"observe_resources": True}, {"observe_redirects": True}, {"request_headers": {}},
            {"before_request": None}, {"before_send": None}, {"url": self.URL + "?"}, {"url": self.URL + "#"},
            {"url": "https://example.com:443/public"}, {"url": "https://user:secret@example.com/public"}):
            fetcher, _, _, factory, resolver = self.transport()
            with self.subTest(changes=changes), self.assertRaises(FetchDenied): self.fetch(fetcher, **changes)
            factory.assert_not_called(); resolver.assert_not_called()

    def test_strict_framing_utf8_duplicate_headers_single_gzip_and_byte_bounds(self):
        base = f"Content-Length: {len(self.HTML)}\r\nContent-Type: text/html; charset=utf-8\r\n".encode()
        for fields in (base + b"Content-Length: 0\r\n", base + b"Content-Type: text/html; charset=utf-8\r\n",
            base + b"Transfer-Encoding: chunked\r\n", base + b"Trailer: other\r\n", base + b"Content-Range: bytes 0-1/99\r\n",
            b"Content-Type: text/html; charset=utf-8\r\n", b"Content-Length: 1\r\nContent-Type: text/html\r\n",
            b"Content-Length: 1\r\nContent-Type: text/plain; charset=latin-1\r\n"):
            fetcher, conn, response, *_ = self.transport(fields=fields)
            with self.subTest(fields=fields), self.assertRaises(FetchError): self.fetch(fetcher)
            response.read1.assert_not_called(); conn.close.assert_called_once()
        compressed = gzip.compress(self.HTML)
        for body, length, encoding in ((self.HTML, len(self.HTML) + 1, "identity"),
            (compressed[:-1], len(compressed) - 1, "gzip"), (compressed + gzip.compress(b"tail"), len(compressed + gzip.compress(b"tail")), "gzip"),
            (compressed + b"tail", len(compressed) + 4, "gzip"), (gzip.compress(b"x" * 131073), len(gzip.compress(b"x" * 131073)), "gzip"),
            (b"\xff", 1, "identity")):
            fetcher, conn, *_ = self.transport(body, fields=f"Content-Length: {length}\r\nContent-Type: text/html; charset=utf-8\r\nContent-Encoding: {encoding}\r\n".encode())
            with self.subTest(length=length, encoding=encoding), self.assertRaises(FetchError): self.fetch(fetcher)
            conn.close.assert_called_once()

    def test_current_dns_connected_completion_deadline_and_no_retry(self):
        for boundary in ("before_dns", "after_dns", "connected", "completion"):
            fetcher, conn, _, factory, resolver = self.transport()
            before = Mock(side_effect=PermissionDenied if boundary == "before_dns" else None)
            send = Mock(side_effect=PermissionDenied if boundary == "after_dns" else [None, PermissionDenied] if boundary == "connected" else [None, None, PermissionDenied] if boundary == "completion" else None)
            with self.subTest(boundary=boundary), self.assertRaises(PermissionDenied): self.fetch(fetcher, before_request=before, before_send=send)
            if boundary in {"before_dns", "after_dns"}: factory.assert_not_called()
            else: conn.close.assert_called_once()
            if boundary != "completion": conn.request.assert_not_called()
        now, seen = [0], [0]
        def expired(_url):
            seen[0] += 1
            if seen[0] == 2: now[0] = 11
        fetcher, conn, *_ = self.transport(clock=lambda: now[0])
        with self.assertRaises(FetchError): self.fetch(fetcher, before_send=expired)
        conn.request.assert_not_called(); conn.close.assert_called_once()
        fetcher, _, _, factory, resolver = self.transport()
        resolver.return_value = ["93.184.216.34", "127.0.0.1"]
        with self.assertRaises(FetchDenied): self.fetch(fetcher)
        factory.assert_not_called()


class CompetitorFetchTests(TestCase):
    setUp = source_fixtures.CompetitorSourceTests.setUp
    transport = transport_fixtures.PassiveResourceTransportTests.transport
    HTML = b'<title>Public topic</title><meta name="description" content="Bounded description"><p>private-contact@example.invalid</p>'

    def document(self, body=None, *, status="200 OK", kind="text/html; charset=utf-8", fields=None):
        body = self.HTML if body is None else body
        fields = fields if fields is not None else f"Content-Length: {len(body)}\r\nContent-Type: {kind}\r\n".encode()
        _fetcher, conn, response, *_ = self.transport(body, status=status, fields=fields)
        return conn, response

    def robots(self, body=b"User-agent: *\nDisallow:\n", **changes):
        return self.document(body, kind="text/plain", **changes)

    def collect(self, documents=None, *, resolver_effect=None, connected=None, read=None, sleep_effect=None, checkpoint=None, binding=None, origin=COMPETITOR, producer=None):
        binding = binding or current_competitor_source(project=self.project, actor=self.owner, data={"origin": origin, "collection_permission": True})
        documents = documents or [self.robots(), self.document()]
        self.now, self.waits, self.connections = 0, [], []
        pending = list(documents)
        def factory(*args):
            conn, response = pending.pop(0)
            self.connections.append((args[:4], conn))
            if connected: conn.connect.side_effect = lambda: connected(len(self.connections))
            if read:
                original = response.read1
                response.read1 = lambda amount: (read(len(self.connections)), original(amount))[1]
            return conn
        def resolve(*args):
            if resolver_effect: resolver_effect(len(self.connections))
            return ["93.184.216.34"]
        def wait(value):
            self.waits.append(value); self.now += value
            if sleep_effect: sleep_effect()
        fetcher = SafeFetcher(CrawlScope(frozenset({binding["hostname"]}), kind="competitor"), resolver=resolve,
            connection_factory=factory, max_redirects=2, max_bytes=131072, timeout=8, clock=lambda: self.now)
        return (producer or collector.collect_competitor_metadata)(project=self.project, actor=self.owner, binding=binding,
            before_request=checkpoint or (lambda: None), fetcher=fetcher, clock=lambda: self.now, sleep=wait)

    def revoke(self):
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")

    def test_genuine_current_source_real_protected_transport_original_date_minimization_pacing_no_write(self):
        with patch("jobs.crawling._system_resolver", side_effect=AssertionError("No real DNS")), CaptureQueriesContext(connection) as queries:
            result = self.collect()
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual(result["state"], "collected")
        self.assertEqual(result["requested_url"], COMPETITOR + "/")
        self.assertEqual(result["evidence"]["metadata"]["title"], "Public topic")
        self.assertEqual(result["observed_at"], result["evidence"]["observed_at"])
        self.assertEqual(self.waits, [1])
        self.assertEqual([args for args, _ in self.connections], [("https", "93.184.216.34", "competitor.example.invalid", 443)] * 2)
        self.assertNotIn("private-contact", json.dumps(result))
        self.assertFalse(JobRun.objects.exists()); self.assertFalse(CrawlRun.objects.exists())

    def test_robots_unknown_unsupported_denied_never_requests_source_and_missing_404_410_permits(self):
        for body in (b"User-agent: *\nDisallow: /", b"Unknown challenge", b"User-agent: *\nDisallow: /*",
            b"User-agent: *\nDisallow: /%24", b"User-agent: *\nDisallow:\nRequest-rate: 1/60",
            b"User-agent: *\nDisallow:\nCrawl-delay: 1.5", b"User-agent: *\nDisallow:\nCrawl-delay: 11",
            b"User-agent: *\nDisallow:\nRequest-rate : 1/60", b"User-agent: *\nDisallow:\nCrawl-delay : 1.5", b"\xff"):
            with self.subTest(body=body):
                result = self.collect([self.robots(body)])
                self.assertEqual(result["state"], "unavailable"); self.assertEqual(len(self.connections), 1)
                self.assertNotIn("evidence", result)
        for status in ("403 Forbidden", "503 Unavailable", "302 Found"):
            result = self.collect([self.robots(status=status)])
            self.assertEqual(result["state"], "unavailable"); self.assertEqual(len(self.connections), 1)
        for status in ("404 Not Found", "410 Gone"):
            result = self.collect([self.robots(status=status), self.document()])
            self.assertEqual(result["state"], "collected"); self.assertEqual(result["robots"], "missing_http_404_or_410")

    def test_no_redirect_even_same_hostname_scheme_transition_root_status_and_ambiguity_honest(self):
        for destination in ("/final", "http://competitor.example.invalid/", "https://foreign.example.invalid/"):
            result = self.collect([self.robots(), self.document(status="302 Found", fields=f"Location: {destination}\r\n".encode())])
            self.assertEqual(result["error_category"], "competitor_document_http_status")
            self.assertEqual(len(self.connections), 2)
        result = self.collect([self.robots(), self.document(b"<title>Unclosed")])
        self.assertEqual(result["state"], "collected")
        self.assertEqual(result["evidence"]["state"], "unavailable"); self.assertIsNone(result["evidence"]["metadata"])
        ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=["http://competitor.example.invalid"])
        self.assertEqual(self.collect(origin="http://competitor.example.invalid")["state"], "collected")
        self.assertEqual(self.connections[0][0][0], "http")

    def test_current_source_dns_connected_body_projection_and_pacing_loss_never_delivers(self):
        hooks = ({"resolver_effect": lambda _count: self.revoke()}, {"connected": lambda _count: self.revoke()},
            {"read": lambda count: self.revoke() if count == 2 else None}, {"sleep_effect": self.revoke})
        for hook in hooks:
            with self.subTest(hook=hook), transaction.atomic():
                with self.assertRaises(PermissionDenied): self.collect(**hook)
                if "read" not in hook:
                    self.connections[-1][1].request.assert_not_called() if "connected" in hook else None
                transaction.set_rollback(True)
        real = collector.observe_static_metadata
        def during_projection(**kwargs):
            result = real(**kwargs)
            ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[COMPETITOR])
            return result
        with patch.object(collector, "observe_static_metadata", side_effect=during_projection), self.assertRaises(PermissionDenied): self.collect()

    def test_mandatory_owning_budget_cancel_checkpoint_and_pacing_deadline(self):
        for boundary in ("connected", "completion", "pacing"):
            active = [True]
            def deny():
                if not active[0]: raise PermissionDenied
            change = lambda *_: active.__setitem__(0, False)
            hooks = {"connected": change} if boundary == "connected" else {"read": change} if boundary == "completion" else {"sleep_effect": change}
            with self.subTest(boundary=boundary), self.assertRaises(PermissionDenied): self.collect(checkpoint=deny, **hooks)
        result = self.collect(sleep_effect=lambda: setattr(self, "now", 31))
        self.assertEqual(result["error_category"], "competitor_document_deadline")
        self.assertEqual(len(self.connections), 1)
        result = self.collect([self.robots(b"User-agent: *\nDisallow:\nCrawl-delay: 3"), self.document()])
        self.assertEqual(result["state"], "collected"); self.assertEqual(self.waits, [3])

    def test_original_capture_survives_projection_delay_but_overall_deadline_never_returns_success(self):
        original = collector.observe_static_metadata
        stamps = []
        def project(**kwargs):
            stamps.append(kwargs["observed_at"])
            result = original(**kwargs)
            self.now = 4
            return result
        with patch.object(collector, "observe_static_metadata", side_effect=project): result = self.collect()
        self.assertEqual(result["observed_at"], stamps[0])
        def late(**kwargs):
            result = original(**kwargs); self.now = 31; return result
        with patch.object(collector, "observe_static_metadata", side_effect=late): result = self.collect()
        self.assertEqual(result["state"], "unavailable"); self.assertEqual(result["error_category"], "competitor_document_deadline")

    def test_original_binding_is_frozen_and_full_hidden_current_changes_cannot_rebind_it(self):
        binding = current_competitor_source(project=self.project, actor=self.owner,
            data={"origin": COMPETITOR, "collection_permission": True})
        original = dict(binding)
        result = self.collect(binding=binding, connected=lambda _count: binding.update(source_sha256="0" * 64))
        self.assertEqual(result["source_sha256"], original["source_sha256"])
        with self.assertRaises(PermissionDenied): self.collect(binding=binding)
        with self.assertRaises((PermissionDenied, ValidationError)):
            self.collect(binding=original, connected=lambda _count: ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(
                competitor_origins=[COMPETITOR], revision=2))

    def test_unrecognized_transport_error_is_minimized_to_fixed_category_without_raw_error_payload(self):
        def failed(_count):
            raise FetchError("private-fixture-contact@example.invalid")
        result = self.collect(connected=failed)
        self.assertEqual(result, {"method_version": collector.METHOD, "state": "unavailable", "error_category": "competitor_document_failed"})
        self.connections[0][1].request.assert_not_called()
