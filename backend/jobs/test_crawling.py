import gzip
import socket
import subprocess
import threading
import time
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, call, patch

from .crawling import (
    CrawlScope,
    FetchDenied,
    FetchLimitExceeded,
    FetchResponse,
    SafeFetcher,
    _PinnedHTTPConnection,
    _PinnedHTTPSConnection,
    _read_body,
    _system_resolver,
    discover_robots,
    discover_sitemaps,
)


class Aliases:
    def __init__(self, *origins):
        self.origins = origins

    def values_list(self, *_args, **_kwargs):
        return self.origins


class FakeResponse:
    def __init__(self, status=200, body=b"", headers=None, chunk_size=65536):
        self.status = status
        self.body = body
        self.headers = headers or {}
        self.chunk_size = chunk_size
        self.offset = 0

    def getheaders(self):
        return self.headers.items()

    def read(self, amount):
        amount = min(amount, self.chunk_size)
        chunk = self.body[self.offset:self.offset + amount]
        self.offset += len(chunk)
        return chunk


class FakeConnection:
    def __init__(self, response):
        self.response = response
        self.request_data = None
        self.sock = Mock()

    def request(self, method, target, headers):
        self.request_data = method, target, headers

    def connect(self):
        pass

    def getresponse(self):
        return self.response

    def close(self):
        pass


def public_resolver(hostname, port, *_args):
    address = {
        "example.com": "93.184.216.34",
        "www.example.com": "93.184.216.35",
        "competitor.example": "93.184.216.36",
    }[hostname]
    return [address]


class CrawlScopeTests(TestCase):
    def setUp(self):
        self.project = SimpleNamespace(
            canonical_origin="https://example.com",
            domain_aliases=Aliases("https://www.example.com"),
            configuration=SimpleNamespace(competitor_origins=["https://competitor.example"]),
        )

    def test_project_and_competitor_runs_stay_separate(self):
        project_scope = CrawlScope.for_project(self.project)
        self.assertEqual(project_scope.validate_url("HTTP://EXAMPLE.COM:80/a?q=one two"), "http://example.com/a?q=one%20two")
        self.assertEqual(project_scope.validate_url("https://www.example.com/path"), "https://www.example.com/path")
        for denied in (
            "https://competitor.example/",
            "https://user:secret@example.com/",
            "https://example.com:8443/",
            "file:///etc/passwd",
        ):
            with self.assertRaises(FetchDenied):
                project_scope.validate_url(denied)

        competitor_scope = CrawlScope.for_project(
            self.project, competitor_origin="HTTPS://COMPETITOR.EXAMPLE/"
        )
        self.assertEqual(competitor_scope.hosts, frozenset({"competitor.example"}))
        with self.assertRaises(FetchDenied):
            CrawlScope.for_project(self.project, competitor_origin="https://other.example")


class SafeFetcherTests(TestCase):
    def test_resolves_every_hop_pins_public_address_and_blocks_private_redirect(self):
        scope = CrawlScope(frozenset({"example.com", "www.example.com"}))
        responses = [
            FakeResponse(301, headers={"Location": "https://www.example.com/final"}),
            FakeResponse(200, b"ok"),
        ]
        connections = []

        def factory(scheme, address, hostname, port, _deadline, _clock):
            connections.append((scheme, address, hostname, port))
            return FakeConnection(responses.pop(0))

        result = SafeFetcher(scope, resolver=public_resolver, connection_factory=factory).fetch(
            "https://example.com/start"
        )
        self.assertEqual(result.body, b"ok")
        self.assertEqual(len(result.redirects), 1)
        self.assertEqual(
            connections,
            [
                ("https", "93.184.216.34", "example.com", 443),
                ("https", "93.184.216.35", "www.example.com", 443),
            ],
        )

        def rebinding_resolver(hostname, port, *_args):
            address = "93.184.216.34" if hostname == "example.com" else "127.0.0.1"
            return [address]

        responses[:] = [
            FakeResponse(302, headers={"Location": "https://www.example.com/private"})
        ]
        with self.assertRaisesRegex(FetchDenied, "non_public_address"):
            SafeFetcher(scope, resolver=rebinding_resolver, connection_factory=factory).fetch(
                "https://example.com/start"
            )

        calls = 0

        def same_host_rebinding(hostname, port, *_args):
            nonlocal calls
            calls += 1
            address = "93.184.216.34" if calls == 1 else "127.0.0.1"
            return [address]

        responses[:] = [FakeResponse(302, headers={"Location": "/again"})]
        with self.assertRaisesRegex(FetchDenied, "non_public_address"):
            SafeFetcher(scope, resolver=same_host_rebinding, connection_factory=factory).fetch(
                "https://example.com/start"
            )

    def test_blocks_mixed_private_dns_and_alternate_ip_forms(self):
        scope = CrawlScope(frozenset({"example.com"}))
        for addresses in (
            ("93.184.216.34", "10.0.0.1"),
            ("127.0.0.1",),
            ("169.254.169.254",),
            ("fe80::1",),
            ("::1",),
            ("fc00::1",),
            ("::ffff:127.0.0.1",),
            ("ff02::1",),
            ("::",),
        ):
            resolver = lambda _host, _port, _timeout, addresses=addresses: list(addresses)
            with self.assertRaisesRegex(FetchDenied, "non_public_address"):
                SafeFetcher(scope, resolver=resolver, connection_factory=lambda *_args: None).fetch(
                    "https://example.com"
                )

        numeric_scope = CrawlScope(frozenset({"2130706433"}))
        with self.assertRaisesRegex(FetchDenied, "non_public_address"):
            SafeFetcher(
                numeric_scope,
                resolver=lambda *_args: ["127.0.0.1"],
                connection_factory=lambda *_args: None,
            ).fetch("http://2130706433/")

    def test_bounds_wire_and_decompressed_response_sizes(self):
        scope = CrawlScope(frozenset({"example.com"}))

        def run(response, max_bytes=32):
            return SafeFetcher(
                scope,
                max_bytes=max_bytes,
                resolver=public_resolver,
                connection_factory=lambda *_args: FakeConnection(response),
            ).fetch("https://example.com")

        with self.assertRaisesRegex(FetchLimitExceeded, "response_too_large"):
            run(FakeResponse(body=b"x" * 33, chunk_size=5))
        compressed = gzip.compress(b"x" * 1000)
        with self.assertRaisesRegex(FetchLimitExceeded, "response_too_large"):
            run(FakeResponse(body=compressed, headers={"Content-Encoding": "gzip"}), max_bytes=64)
        self.assertEqual(
            run(FakeResponse(body=gzip.compress(b"safe"), headers={"Content-Encoding": "gzip"})).body,
            b"safe",
        )

    def test_enforces_dns_and_stream_elapsed_time(self):
        scope = CrawlScope(frozenset({"example.com"}))

        with patch(
            "jobs.crawling.subprocess.run",
            side_effect=subprocess.TimeoutExpired("resolver", 0.005),
        ):
            with self.assertRaisesRegex(FetchLimitExceeded, "timeout"):
                SafeFetcher(scope, timeout=0.005).fetch("https://example.com")

        ticks = iter((0, 0, 0, 0.4, 1.1))
        response = FakeResponse(body=b"ab", chunk_size=1)
        with self.assertRaisesRegex(FetchLimitExceeded, "timeout"):
            SafeFetcher(
                scope,
                timeout=1,
                resolver=public_resolver,
                connection_factory=lambda *_args: FakeConnection(response),
                clock=lambda: next(ticks),
            ).fetch("https://example.com")

    def test_wall_clock_deadline_stops_loopback_header_and_body_trickles(self):
        def serve(chunks):
            server = socket.socket()
            server.bind(("127.0.0.1", 0))
            server.listen(1)

            def run():
                try:
                    client, _ = server.accept()
                    with client:
                        client.recv(4096)
                        for chunk in chunks:
                            client.sendall(chunk)
                            time.sleep(0.03)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    server.close()

            thread = threading.Thread(target=run, daemon=True)
            thread.start()
            return server.getsockname()[1], thread

        port, thread = serve([bytes([byte]) for byte in b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"])
        deadline = time.monotonic() + 0.08
        connection = _PinnedHTTPConnection("127.0.0.1", port, deadline=deadline, clock=time.monotonic)
        try:
            connection.request("GET", "/", headers={"Host": "example.com"})
            with self.assertRaisesRegex(FetchLimitExceeded, "timeout"):
                connection.getresponse()
        finally:
            connection.close()
            thread.join(0.5)

        headers = b"HTTP/1.1 200 OK\r\nContent-Length: 20\r\n\r\n"
        port, thread = serve([headers, *([b"x"] * 20)])
        deadline = time.monotonic() + 0.08
        connection = _PinnedHTTPConnection("127.0.0.1", port, deadline=deadline, clock=time.monotonic)
        try:
            connection.request("GET", "/", headers={"Host": "example.com"})
            response = connection.getresponse()
            with self.assertRaisesRegex(FetchLimitExceeded, "timeout"):
                _read_body(
                    response,
                    {"content-length": "20"},
                    max_bytes=100,
                    deadline=deadline,
                    clock=time.monotonic,
                    connection=connection,
                )
        finally:
            connection.close()
            thread.join(0.5)

    def test_tls_connects_to_pinned_address_with_original_hostname(self):
        context = Mock()
        wrapped_socket = Mock()
        context.wrap_socket.return_value = wrapped_socket
        wrapped_socket.do_handshake.return_value = None
        raw_socket = Mock()
        with patch("jobs.crawling.ssl.create_default_context", return_value=context), patch(
            "jobs.crawling.socket.create_connection", return_value=raw_socket
        ) as create_connection:
            connection = _PinnedHTTPSConnection(
                "93.184.216.34",
                443,
                server_hostname="example.com",
                deadline=2,
                clock=lambda: 0,
            )
            connection.connect()
        create_connection.assert_called_once_with(("93.184.216.34", 443), 2, None)
        context.wrap_socket.assert_called_once_with(
            raw_socket,
            server_hostname="example.com",
            do_handshake_on_connect=False,
        )
        wrapped_socket.setblocking.assert_has_calls([call(False), call(True)])

    def test_isolated_resolver_parses_only_bounded_address_lists(self):
        completed = subprocess.CompletedProcess([], 0, stdout='["93.184.216.34"]', stderr="")
        with patch("jobs.crawling.subprocess.run", return_value=completed) as run:
            self.assertEqual(_system_resolver("example.com", 443, 2), ["93.184.216.34"])
        self.assertEqual(run.call_args.kwargs["timeout"], 2)
        self.assertEqual(run.call_args.kwargs["env"], {})

    def test_malformed_redirect_is_controlled(self):
        response = FakeResponse(302, headers={"Location": "https://[::1"})
        with self.assertRaisesRegex(FetchDenied, "invalid_url"):
            SafeFetcher(
                CrawlScope(frozenset({"example.com"})),
                resolver=public_resolver,
                connection_factory=lambda *_args: FakeConnection(response),
            ).fetch("https://example.com")
        with self.assertRaisesRegex(FetchDenied, "invalid_url"):
            CrawlScope(frozenset({"example.com"})).validate_url("https://example.com/" + "é" * 1000)

    def test_conditional_headers_are_bounded_and_not_forwarded_after_redirect(self):
        scope = CrawlScope(frozenset({"example.com", "www.example.com"}))
        made = []
        responses = [
            FakeResponse(302, headers={"Location": "https://www.example.com/final"}),
            FakeResponse(304),
        ]

        def factory(*_args):
            connection = FakeConnection(responses.pop(0))
            made.append(connection)
            return connection

        requests = []
        result = SafeFetcher(scope, resolver=public_resolver, connection_factory=factory).fetch(
            "https://example.com/start",
            request_headers={"If-None-Match": '"safe"'},
            before_request=requests.append,
        )
        self.assertEqual(result.status, 304)
        self.assertEqual(requests, ["https://example.com/start", "https://www.example.com/final"])
        self.assertEqual(made[0].request_data[2]["If-None-Match"], '"safe"')
        self.assertNotIn("If-None-Match", made[1].request_data[2])
        for headers in (
            {"Authorization": "secret"},
            {"If-None-Match": "safe\r\nInjected: yes"},
            {"If-Modified-Since": "x" * 501},
        ):
            with self.assertRaises(FetchDenied):
                SafeFetcher(scope, resolver=public_resolver, connection_factory=factory).fetch(
                    "https://example.com", request_headers=headers
                )


class DiscoveryTests(TestCase):
    def setUp(self):
        self.scope = CrawlScope(frozenset({"example.com"}))

    def test_robots_is_fail_closed_and_rejects_off_scope_sitemaps(self):
        body = b"User-agent: *\nDisallow: /private\nSitemap: /sitemap.xml\nSitemap: https://outside.example/map.xml\n"
        fetcher = SimpleNamespace(
            scope=self.scope,
            fetch=lambda url: FetchResponse(url=url, status=200, headers={}, body=body),
        )
        result = discover_robots(fetcher, "https://example.com")
        self.assertEqual(result.status, "available")
        self.assertEqual(result.sitemap_urls, ("https://example.com/sitemap.xml",))
        self.assertEqual(result.denied_sitemaps, 1)
        self.assertFalse(result.allows("https://example.com/private/page"))
        self.assertTrue(result.allows("https://example.com/public"))
        self.assertFalse(result.allows("https://outside.example/"))

        for status, expected, allowed in (
            (400, "failed", False),
            (403, "denied", False),
            (404, "missing", True),
            (408, "failed", False),
            (410, "missing", True),
            (429, "failed", False),
            (451, "denied", False),
            (503, "failed", False),
        ):
            fetcher.fetch = lambda url, status=status: FetchResponse(url=url, status=status, headers={}, body=b"")
            result = discover_robots(fetcher, "https://example.com")
            self.assertEqual(result.status, expected)
            self.assertEqual(result.allows("https://example.com/page"), allowed)

    def test_sitemap_discovery_handles_indexes_loops_malformed_xml_and_limits(self):
        documents = {
            "https://example.com/root.xml": b"""<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                <sitemap><loc>/pages.xml.gz</loc></sitemap>
                <sitemap><loc>/root.xml</loc></sitemap>
                <sitemap><loc>/broken.xml</loc></sitemap>
                <sitemap><loc>https://outside.example/map.xml</loc></sitemap>
            </sitemapindex>""",
            "https://example.com/pages.xml.gz": gzip.compress(b"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                <url><loc>https://example.com/one</loc></url>
                <url><loc>https://example.com/two</loc></url>
                <url><loc>http://127.0.0.1/private</loc></url>
            </urlset>"""),
            "https://example.com/broken.xml": b"<urlset><url>",
        }

        class Fetcher:
            scope = self.scope
            max_bytes = 4096

            def fetch(self, url):
                return FetchResponse(url=url, status=200, headers={}, body=documents[url])

        result = discover_sitemaps(Fetcher(), ["https://example.com/root.xml"])
        self.assertEqual(result.urls, ("https://example.com/one", "https://example.com/two"))
        self.assertEqual(result.denied_urls, 2)
        self.assertEqual([failure.code for failure in result.failures], ["malformed_xml"])
        self.assertFalse(result.truncated)
        self.assertEqual(len(result.sitemap_urls), 3)

        limited = discover_sitemaps(Fetcher(), ["https://example.com/root.xml"], max_sitemaps=1)
        self.assertTrue(limited.truncated)
        self.assertEqual(limited.sitemap_urls, ("https://example.com/root.xml",))

    def test_sitemap_queue_xml_and_references_are_bounded(self):
        children = "".join(
            f"<sitemap><loc>/child-{index}.xml</loc></sitemap>" for index in range(20)
        )
        documents = {
            "https://example.com/root.xml": f"<sitemapindex>{children}<sitemap><loc>https://[::1</loc></sitemap></sitemapindex>".encode(),
            "https://example.com/child-0.xml": b"<urlset><url><loc>https://[::1</loc></url></urlset>",
        }

        class Fetcher:
            scope = self.scope
            max_bytes = 4096

            def fetch(self, url):
                return FetchResponse(url=url, status=200, headers={}, body=documents.get(url, b"<urlset/>"))

        result = discover_sitemaps(Fetcher(), ["https://example.com/root.xml"], max_sitemaps=2)
        self.assertTrue(result.truncated)
        self.assertLessEqual(len(result.sitemap_urls), 2)
        self.assertGreaterEqual(result.denied_urls, 1)

        deduplicated = discover_sitemaps(
            Fetcher(),
            ["https://example.com/root.xml", "HTTPS://EXAMPLE.COM:443/root.xml"],
            max_sitemaps=2,
        )
        self.assertEqual(
            deduplicated.sitemap_urls,
            ("https://example.com/root.xml", "https://example.com/child-0.xml"),
        )

        utf16 = Fetcher()
        utf16.fetch = lambda url: FetchResponse(
            url=url,
            status=200,
            headers={},
            body="<?xml version='1.0'?><urlset/>".encode("utf-16"),
        )
        result = discover_sitemaps(utf16, ["https://example.com/utf16.xml"])
        self.assertEqual(result.failures[0].code, "invalid_xml_encoding")

        unsafe = Fetcher()
        unsafe.fetch = lambda url: FetchResponse(
            url=url,
            status=200,
            headers={},
            body=b"<!DOCTYPE x [<!ENTITY a 'boom'>]><urlset><url><loc>&a;</loc></url></urlset>",
        )
        result = discover_sitemaps(unsafe, ["https://example.com/entity.xml"])
        self.assertEqual(result.failures[0].code, "unsafe_xml")
