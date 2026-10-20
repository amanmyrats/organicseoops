import json
import ssl
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tenancy.models import ProjectOriginVerification
from .crawling import CrawlScope, FetchDenied, FetchError, FetchLimitExceeded, SafeFetcher
from . import passive_redirect_chain_source as source
from . import test_passive_header_transport as response_fixtures
from . import test_passive_redirect_chain_source as source_fixtures


class PassiveRedirectChainTransportTests(SimpleTestCase):
    HTTP = "http://example.com/public"
    HTTPS = "https://example.com/public"
    OTHER = "https://www.example.com/public"
    response_fixture = response_fixtures.PassiveHeaderTransportTests.transport

    def selection(self, **changes):
        return {"url": self.HTTP, "target_urls": [self.HTTPS, self.OTHER], "observations": ["redirect_chain"],
            "collection_permission": True, **changes}

    def transport(self, *wires, resolver=None, clock=None, max_redirects=5):
        pairs = [self.response_fixture(wire)[1:3] for wire in wires]
        connections, responses = [pair[0] for pair in pairs], [pair[1] for pair in pairs]
        factory = Mock(side_effect=connections)
        resolver = resolver or Mock(return_value=["93.184.216.34"])
        fetcher = SafeFetcher(CrawlScope(frozenset({"example.com", "www.example.com"})),
            connection_factory=factory, resolver=resolver, clock=clock or time.monotonic,
            max_redirects=max_redirects)
        return fetcher, connections, responses, factory, resolver

    def observe(self, fetcher, **changes):
        return fetcher.fetch(**{**dict(url=self.HTTP, redirect_chain_selection=self.selection(),
            before_request=Mock(), before_send=Mock()), **changes})

    def test_three_original_selected_responses_public_pins_each_gate_dates_minimized_no_body_or_raw_target(self):
        wires = (b"HTTP/1.1 301 Moved\r\nLocation: https://example.com:443/public\r\nSet-Cookie: personal=secret\r\n\r\nprivate body",
            b"HTTP/1.1 302 Found\r\nLocation: https://www.example.com/public\r\n\r\n",
            b"HTTP/1.1 200 OK\r\nServer: private\r\nContent-Length: 999999999\r\n\r\nprivate body")
        fetcher, connections, responses, factory, resolver = self.transport(*wires)
        before, send = Mock(), Mock(); start = timezone.now()
        with patch("socket.create_connection", side_effect=AssertionError("No actual egress")):
            result = self.observe(fetcher, before_request=before, before_send=send)
        info = result.redirect_observation
        self.assertEqual(info["method_version"], "passive-exact-redirect-chain-response-v1")
        self.assertEqual(info["state"], "terminal_response")
        self.assertEqual([hop["url"] for hop in info["hops"]], [self.HTTP, self.HTTPS, self.OTHER])
        self.assertEqual([hop["status"] for hop in info["hops"]], [301, 302, 200])
        self.assertEqual([hop["target_state"] for hop in info["hops"]], ["permitted_target", "permitted_target", "terminal_response"])
        dates = [datetime.fromisoformat(hop["observed_at"]) for hop in info["hops"]]
        self.assertEqual(dates, sorted(dates))
        for hop, date in zip(info["hops"], dates):
            self.assertEqual(date.tzinfo, UTC); self.assertTrue(start <= date <= timezone.now())
            self.assertEqual(date.isoformat(timespec="microseconds"), hop["observed_at"])
        self.assertEqual((result.url, result.status, result.headers, result.body, result.redirects), (self.OTHER, 200, {}, b"", ()))
        self.assertIsNone(result.header_observation); self.assertIsNone(result.resource_observation); self.assertIsNone(result.observed_at)
        self.assertEqual((before.call_count, send.call_count, factory.call_count, resolver.call_count), (6, 6, 3, 3))
        self.assertEqual([call.args[:4] for call in factory.call_args_list], [("http", "93.184.216.34", "example.com", 80),
            ("https", "93.184.216.34", "example.com", 443), ("https", "93.184.216.34", "www.example.com", 443)])
        for conn, response in zip(connections, responses):
            conn.request.assert_called_once(); self.assertEqual(conn.request.call_args.args, ("GET", "/public"))
            self.assertEqual(set(conn.request.call_args.kwargs["headers"]), {"Host", "User-Agent", "Accept", "Accept-Encoding", "Connection"})
            conn.connect.assert_called_once(); conn.close.assert_called_once(); response.read.assert_not_called(); self.assertTrue(response.closed)
        for raw in ("personal", "secret", "private", ":443", "digest", "next_url"):
            self.assertNotIn(raw, json.dumps(info))

    def test_unknown_ambiguous_outside_unsupported_nonredirect_and_loop_stop_before_another_request(self):
        cases = ((b"", "location_unavailable"), (b"Location: \t\r\n", "location_unavailable"),
            (b"Location: /one\r\nLOCATION: /two\r\n", "location_unavailable"),
            (b"Location: /%ZZ\r\n", "location_unavailable"),
            (b"Location: http://169.254.169.254/private\r\n", "outside_exact_target_allowlist"),
            (b"Location: https://example.com/unselected\r\n", "outside_exact_target_allowlist"),
            (b"Location: https://example.com:444/public\r\n", "unsupported_target"),
            (b"Location: https://example.com/public?\r\n", "unsupported_target"),
            (b"Location: /public\r\n", "redirect_loop"))
        for fields, expected in cases:
            fetcher, connections, responses, factory, resolver = self.transport(b"HTTP/1.1 301 Moved\r\n" + fields + b"\r\n")
            info = self.observe(fetcher).redirect_observation
            self.assertEqual(info["state"], expected); self.assertEqual(len(info["hops"]), 1)
            factory.assert_called_once(); resolver.assert_called_once(); responses[0].read.assert_not_called()
            self.assertNotIn("169.254", json.dumps(info)); self.assertNotIn("private", json.dumps(info))
        fetcher, connections, responses, factory, resolver = self.transport(b"HTTP/1.1 200 OK\r\nLocation: https://example.com/public\r\n\r\n")
        self.assertEqual(self.observe(fetcher).redirect_observation["state"], "terminal_response"); factory.assert_called_once()
        fetcher, connections, responses, factory, resolver = self.transport(
            b"HTTP/1.1 301 Moved\r\nLocation: https://example.com/public\r\n\r\n",
            b"HTTP/1.1 302 Found\r\nLocation: http://example.com/public\r\n\r\n")
        self.assertEqual(self.observe(fetcher).redirect_observation["state"], "redirect_loop"); self.assertEqual(factory.call_count, 2)

    def test_original_smaller_budget_and_hard_six_response_bound_never_reissue_a_request(self):
        wires = (b"HTTP/1.1 301 Moved\r\nLocation: https://example.com/public\r\n\r\n",
            b"HTTP/1.1 302 Found\r\nLocation: https://www.example.com/public\r\n\r\n")
        for budget in (0, 1):
            fetcher, connections, responses, factory, resolver = self.transport(*wires, max_redirects=budget)
            info = self.observe(fetcher).redirect_observation
            self.assertEqual(info["state"], "redirect_limit"); self.assertEqual(len(info["hops"]), budget + 1)
            self.assertEqual(factory.call_count, budget + 1)
        targets = [f"https://example.com/page-{index}" for index in range(5)]
        wires = [f"HTTP/1.1 301 Moved\r\nLocation: {target}\r\n\r\n".encode() for target in targets]
        wires.append(b"HTTP/1.1 301 Moved\r\nLocation: http://example.com/public\r\n\r\n")
        fetcher, connections, responses, factory, resolver = self.transport(*wires, max_redirects=100)
        info = self.observe(fetcher, redirect_chain_selection=self.selection(target_urls=targets)).redirect_observation
        self.assertEqual(info["state"], "redirect_loop"); self.assertEqual(len(info["hops"]), 6); self.assertEqual(factory.call_count, 6)
        for conn in connections: conn.request.assert_called_once(); conn.close.assert_called_once()

    def test_strict_original_selection_callbacks_mode_unions_and_all_selected_scope_deny_before_dns(self):
        for options in ({"redirect_chain_selection": {}}, {"redirect_chain_selection": True}, {"url": self.HTTPS},
            {"redirect_chain_selection": self.selection(collection_permission=1)}, {"redirect_chain_selection": self.selection(target_urls=["https://foreign.invalid/public"])},
            {"request_headers": {}}, {"before_request": None}, {"before_send": None}, {"before_send": True},
            {"observe_headers": True}, {"observe_resources": True}, {"observe_redirects": True}, {"observe_http_redirects": True},
            {"static_document_type": "text/html"}):
            fetcher, connections, responses, factory, resolver = self.transport(b"HTTP/1.1 200 OK\r\n\r\n")
            with self.subTest(options=options), self.assertRaises(FetchDenied): self.observe(fetcher, **options)
            resolver.assert_not_called(); factory.assert_not_called()

    def test_current_loss_at_every_boundary_of_each_actual_hop_denies_delivery_or_next_send_and_closes(self):
        self.boundary_loss(expiry=False)

    def test_one_deadline_includes_slow_guards_at_every_boundary_of_each_actual_hop(self):
        self.boundary_loss(expiry=True)

    def boundary_loss(self, *, expiry):
        wires = (b"HTTP/1.1 301 Moved\r\nLocation: https://example.com/public\r\n\r\n", b"HTTP/1.1 200 OK\r\n\r\n")
        for hop in (self.HTTP, self.HTTPS):
            for boundary in ("before_dns", "after_dns", "connected", "completion"):
                clock = Mock(return_value=0)
                fetcher, connections, responses, factory, resolver = self.transport(*wires, clock=clock)
                counts = {}
                def guard(kind, url):
                    key = kind, url; counts[key] = counts.get(key, 0) + 1
                    expected = ("before", 1) if boundary == "before_dns" else ("send", 1) if boundary == "after_dns" else ("send", 2) if boundary == "connected" else ("before", 2)
                    if url == hop and (kind, counts[key]) == expected:
                        if expiry: clock.return_value = 11
                        else: raise PermissionDenied
                with self.subTest(hop=hop, boundary=boundary, expiry=expiry), self.assertRaises(FetchLimitExceeded if expiry else PermissionDenied):
                    self.observe(fetcher, before_request=lambda url: guard("before", url), before_send=lambda url: guard("send", url))
                index = 0 if hop == self.HTTP else 1
                if boundary != "completion": connections[index].request.assert_not_called()
                if boundary in {"connected", "completion"}: connections[index].close.assert_called_once()
                if index: connections[0].request.assert_called_once(); connections[0].close.assert_called_once()
                self.assertEqual(factory.call_count, index + (boundary in {"connected", "completion"}))
                for response in responses: response.read.assert_not_called()

    def test_each_hop_dns_rebind_and_strict_tls_failure_are_categorical_without_unverified_retry(self):
        wires = (b"HTTP/1.1 301 Moved\r\nLocation: https://example.com/public\r\n\r\n", b"HTTP/1.1 200 OK\r\n\r\n")
        fetcher, connections, responses, factory, resolver = self.transport(*wires,
            resolver=Mock(side_effect=[["93.184.216.34"], ["93.184.216.34", "127.0.0.1"]]))
        with self.assertRaises(FetchDenied): self.observe(fetcher)
        factory.assert_called_once(); self.assertEqual(resolver.call_count, 2); connections[1].request.assert_not_called()
        fetcher, connections, responses, factory, resolver = self.transport(*wires)
        connections[1].connect.side_effect = ssl.SSLCertVerificationError("private certificate")
        with self.assertRaisesRegex(FetchError, "^network_error$"): self.observe(fetcher)
        self.assertEqual(factory.call_count, 2); connections[1].request.assert_not_called(); connections[1].close.assert_called_once()
        connections[0].close.assert_called_once()
        for response in responses: response.read.assert_not_called()

    def test_defective_status_or_original_header_bounds_fail_without_body_raw_error_or_first_response_promotion(self):
        for wire in (b"HTTP/1.1 600 Unknown\r\n\r\n", b"HTTP/1.1 301 Moved\r\nmalformed private\r\n\r\n",
            b"HTTP/1.1 301 Moved\r\nX: private\x00\r\n\r\n", b"HTTP/1.1 301 Moved\r\nLocation: " + b"x" * 8193 + b"\r\n\r\n"):
            fetcher, connections, responses, factory, resolver = self.transport(wire)
            with self.assertRaisesRegex(FetchError, "^response_headers_unavailable$"): self.observe(fetcher)
            responses[0].read.assert_not_called(); connections[0].close.assert_called_once()
        fetcher, connections, responses, factory, resolver = self.transport(b"HTTP/1.1 301 Moved\r\n\r\n")
        responses[0].getheaders = Mock(return_value=[("X", "private")] * 101)
        with self.assertRaises(FetchError): self.observe(fetcher)
        from .passive_redirect_evidence import minimized_redirect_evidence
        from .passive_http_redirect_evidence import minimized_http_redirect_evidence
        from . import test_passive_redirect_evidence, test_passive_http_redirect_evidence
        fetcher, connections, responses, factory, resolver = self.transport(b"HTTP/1.1 200 OK\r\n\r\n")
        result = self.observe(fetcher)
        for projector, binding in ((minimized_redirect_evidence, test_passive_redirect_evidence.PassiveRedirectEvidenceTests.BINDING),
            (minimized_http_redirect_evidence, test_passive_http_redirect_evidence.PassiveHTTPRedirectEvidenceTests.BINDING)):
            with self.assertRaises(ValidationError): projector(replace(result, url=binding["url"]), binding=binding)


class GenuinePassiveRedirectChainTransportTests(TestCase):
    setUp = source_fixtures.PassiveRedirectChainSourceTests.setUp
    verified = source_fixtures.PassiveRedirectChainSourceTests.verified

    def test_genuine_independent_verified_origins_current_full_source_and_commercial_loss_during_second_hop(self):
        http, https = self.verified(self.http), self.verified(self.https)
        data = {"url": self.http + "/public", "target_urls": [self.https + "/public"],
            "observations": ["redirect_chain"], "collection_permission": True}
        original = source.passive_redirect_chain_source(project=self.project, actor=self.owner, data=data)
        case = PassiveRedirectChainTransportTests(); self.addCleanup(case.doCleanups)
        wires = (f"HTTP/1.1 301 Moved\r\nLocation: {data['target_urls'][0]}\r\n\r\n".encode(), b"HTTP/1.1 200 OK\r\n\r\n")
        from .usage import require_billable_access
        for boundary in (None, "connected", "completion", "commercial"):
            with transaction.atomic():
                _fetcher, connections, responses, factory, resolver = case.transport(*wires)
                fetcher = SafeFetcher(CrawlScope(frozenset({"security.example.com"})), connection_factory=factory, resolver=resolver)
                def current(url):
                    if url not in [data["url"], *data["target_urls"]] or source.passive_redirect_chain_source(project=self.project, actor=self.owner, data=data) != original:
                        raise PermissionDenied
                    require_billable_access(organization=self.organization)
                def drift():
                    if boundary == "commercial":
                        trial = self.organization.trial
                        trial.started_at = timezone.now() - timedelta(days=31); trial.ends_at = timezone.now() - timedelta(days=1)
                        trial.save(update_fields=["started_at", "ends_at"])
                    else: ProjectOriginVerification.objects.filter(pk=http.pk).update(challenge_digest="a" * 64)
                if boundary in {"connected", "commercial"}: connections[1].connect.side_effect = drift
                if boundary == "completion":
                    original_fields = responses[1].getheaders
                    responses[1].getheaders = Mock(side_effect=lambda: (drift(), original_fields())[1])
                with patch("socket.create_connection", side_effect=AssertionError("No actual egress")):
                    if boundary:
                        with self.assertRaises((PermissionDenied, ValidationError)):
                            fetcher.fetch(data["url"], redirect_chain_selection=data, before_request=current, before_send=current)
                    else:
                        with CaptureQueriesContext(connection) as queries:
                            result = fetcher.fetch(data["url"], redirect_chain_selection=data, before_request=current, before_send=current)
                        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
                        self.assertEqual(result.redirect_observation["state"], "terminal_response")
                        for hop, row in zip(result.redirect_observation["hops"], (http, https)):
                            self.assertGreaterEqual(datetime.fromisoformat(hop["observed_at"]), row.verified_at)
                connections[0].request.assert_called_once(); connections[0].close.assert_called_once(); connections[1].close.assert_called_once()
                if boundary in {"connected", "commercial"}: connections[1].request.assert_not_called()
                for response in responses: response.read.assert_not_called()
                transaction.set_rollback(True)
