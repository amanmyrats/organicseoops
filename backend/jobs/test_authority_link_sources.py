from hashlib import sha256
import json
from unittest.mock import patch
import re
from urllib.parse import urlsplit

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from config.test_foundations import TEST_STORAGES
from tenancy.models import OrganizationMembership, Project
from tenancy.services import update_project_configuration
from .authority_link_sources import (MAX_ANCHORS, MAX_BODY_BYTES, MAX_MATCHES, METHOD,
    collect_static_link_source, parse_static_link_source, static_link_source_authority)
from .authority_link_sources import REFERENCE_METHOD, parse_static_link_references
from . import test_authority_links as link_fixtures
from . import test_crawling as transport_fixtures
from .crawling import CrawlScope, SafeFetcher

SOURCE = "https://publisher.example.invalid/article"
TARGET = "https://own.example.invalid/target"
DATE = "2026-01-01T12:00:00+03:00"


class StaticLinkSourceParserTests(SimpleTestCase):
    def parse(self, content, **changes):
        return parse_static_link_source(**{**dict(body=content, source_url=SOURCE, target_url=TARGET, observed_at=DATE), **changes})

    def test_preserves_exact_target_anchor_rel_date_and_original_byte_digest_without_network_or_unrelated_payload(self):
        body = (f'<p>Unrelated identity fixture-contact@example.invalid</p><a href="https://unrelated.example.invalid/private">Other</a>'
                f'<a href="{TARGET}" rel="nofollow sponsored">Human <b>&amp; literal</b> anchor</a>').encode()
        with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No network")):
            result = self.parse(body)
        self.assertEqual(result["method"], METHOD)
        self.assertEqual(result["state"], "observed_absolute_target_in_parsed_html")
        self.assertEqual(result["observed_at"], DATE)
        self.assertEqual(result["body_sha256"], sha256(body).hexdigest())
        self.assertEqual(result["body_size_bytes"], len(body))
        self.assertEqual(result["matching_links"], [{"parsed_href": TARGET, "anchor_text": "Human & literal anchor",
            "anchor_text_truncated": False, "rel": "nofollow sponsored", "rel_truncated": False}])
        encoded = json.dumps(result)
        self.assertNotIn("fixture-contact", encoded)
        self.assertNotIn("unrelated.example.invalid", encoded)
        self.assertNotIn("<b>", encoded)
        self.assertEqual(result["source_authority"], "not_established_by_parser")
        self.assertEqual(result["coverage"]["browser_visibility"], "unknown")

    def test_relative_base_hidden_script_noscript_template_and_lookalikes_never_become_target_links_or_loss(self):
        body = (f'<base href="https://own.example.invalid/"><a href="/target">Relative</a>'
            f'<script>const a = \'<a href="{TARGET}">Script</a>\';</script>'
            f'<template><a href="{TARGET}">Inert</a></template><noscript><a href="{TARGET}">Unknown mode</a></noscript>'
            f'<textarea><a href="{TARGET}">Text</a></textarea><a href="https://own.example.invalid.evil.invalid/target">Other</a>').encode()
        result = self.parse(body)
        self.assertEqual(result["matching_links"], [])
        self.assertEqual(result["state"], "not_observed_in_bounded_static_html_not_link_loss")
        self.assertTrue(result["coverage"]["base_element_seen"])
        self.assertEqual(result["unlinked_or_lost_link"], "not_established")

    def test_character_reference_decoding_is_disclosed_without_url_normalization(self):
        body = f'<a href="https://own.example.invalid/ta&#114;get">Exact parsed attribute</a><a href="{TARGET}/">Different</a>'.encode()
        result = self.parse(body)
        self.assertEqual(len(result["matching_links"]), 1)
        self.assertEqual(result["href_semantics"], "html_character_references_decoded_exact_absolute_href_no_url_resolution")
        empty = self.parse(f'<a href="HTTPS://own.example.invalid/target">Different literal</a>'.encode())
        self.assertEqual(empty["matching_links"], [])

    def test_duplicate_nested_unclosed_and_misclosed_anchors_remain_ambiguous_not_verified(self):
        for body in (f'<a href="{TARGET}" href="https://other.example.invalid/">Duplicate</a>',
            f'<a href="{TARGET}" rel="follow" rel="nofollow">Duplicate</a>',
            f'<a href="{TARGET}">Outer<a href="{TARGET}">Nested</a></a>',
            f'<a href="{TARGET}">Not closed', '<template>Unclosed', '</a>'):
            with self.subTest(body=body):
                result = self.parse(body.encode())
                self.assertEqual(result["state"], "unavailable_ambiguous_markup")
                self.assertTrue(result["coverage"]["structure_uncertain"])
                self.assertEqual(result["unlinked_or_lost_link"], "not_established")

    def test_anchor_inventory_and_matching_evidence_caps_expose_partial_coverage(self):
        body = (('<a href="/other">Other</a>' * MAX_ANCHORS) + f'<a href="{TARGET}">Beyond cap</a>').encode()
        result = self.parse(body)
        self.assertEqual(result["matching_links"], [])
        self.assertTrue(result["coverage"]["anchor_limit_reached"])
        self.assertEqual(result["coverage"]["anchors_inspected"], MAX_ANCHORS)
        self.assertEqual(result["unlinked_or_lost_link"], "not_established")
        matches = self.parse((f'<a href="{TARGET}" rel="nofollow">Anchor</a>' * (MAX_MATCHES + 1)).encode())
        self.assertEqual(len(matches["matching_links"]), MAX_MATCHES)
        self.assertTrue(matches["coverage"]["matches_capped"])

    def test_anchor_rel_truncation_and_body_result_limits_are_explicit(self):
        result = self.parse(f'<a href="{TARGET}" rel="{"r" * 101}">{"x" * 241}</a>'.encode())
        self.assertEqual(len(result["matching_links"][0]["anchor_text"]), 240)
        self.assertTrue(result["matching_links"][0]["anchor_text_truncated"])
        self.assertTrue(result["matching_links"][0]["rel_truncated"])
        with self.assertRaises(ValidationError): self.parse(b"x" * (MAX_BODY_BYTES + 1))
        huge = (f'<a href="{TARGET}" rel="{"界" * 100}">{"界" * 240}</a>' * MAX_MATCHES).encode()
        with self.assertRaises(ValidationError): self.parse(huge)

    def test_invalid_bytes_types_urls_naive_future_and_control_text_fail_closed(self):
        for changes in ({"body": "not bytes"}, {"body": b""}, {"body": b"\xff"}, {"body": b"<p>\x00</p>"},
            {"source_url": "http://publisher.example.invalid/article"}, {"source_url": SOURCE + "?secret=x"},
            {"source_url": "https://user:secret@publisher.example.invalid/article"}, {"source_url": TARGET},
            {"target_url": "https://own.example.invalid:444/target"}, {"target_url": TARGET + "#fragment"},
            {"observed_at": "2026-01-01T12:00:00"}, {"observed_at": "9999-01-01T00:00:00+00:00"}, {"observed_at": True}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError): self.parse(b"<p>Fixture</p>", **changes)


class StaticURIReferenceParserTests(SimpleTestCase):
    def parse(self, content, **changes):
        return parse_static_link_references(**{**dict(body=content, source_url=SOURCE, target_url=TARGET, observed_at=DATE), **changes})

    def test_actual_network_path_reference_uses_final_https_url_canonical_origin_and_no_network_or_unrelated_retention(self):
        body = (f'<p>Unrelated private-contact@example.invalid</p><a href="//OWN.EXAMPLE.INVALID:443/target">Özgün <b>&amp;</b></a>'
                f'<a href="/target">Publisher-relative is not own-target</a><a href="../target">Publisher path</a>').encode()
        with patch("socket.create_connection", side_effect=AssertionError("No network")), patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No fetch")):
            result = self.parse(body)
        self.assertEqual(result["method"], REFERENCE_METHOD)
        self.assertEqual(result["state"], "observed_resolved_target_in_static_uri_references")
        self.assertEqual(result["body_sha256"], sha256(body).hexdigest())
        self.assertEqual(result["matching_links"], [{"parsed_href": TARGET, "anchor_text": "Özgün &",
            "anchor_text_truncated": False, "rel": "", "rel_truncated": False}])
        self.assertEqual(result["coverage"]["unsupported_references"], 0)
        self.assertEqual(result["coverage"]["browser_visibility"], "unknown")
        self.assertEqual(result["source_authority"], "not_established_by_parser")
        self.assertNotIn("private-contact", json.dumps(result))
        # D132 literal v1 still ignores the same network-path reference.
        old = parse_static_link_source(body=body, source_url=SOURCE, target_url=TARGET, observed_at=DATE)
        self.assertEqual(old["method"], METHOD)
        self.assertEqual(old["matching_links"], [])
        self.assertNotIn("unsupported_references", old["coverage"])

    def test_active_base_anywhere_is_unavailable_and_hidden_base_or_anchor_never_supplies_evidence(self):
        for content in (f'<base href="https://own.example.invalid/"><a href="/target">Base-dependent</a>',
            f'<a href="{TARGET}">Literal</a><base href="https://other.example.invalid/">',
            f'<base href="https://own.example.invalid/" href="https://other.example.invalid/"><a href="//own.example.invalid/target">Ambiguous</a>'):
            with self.subTest(content=content):
                result = self.parse(content.encode())
                self.assertEqual(result["matching_links"], [])
                self.assertEqual(result["state"], "unavailable_base_dependent_references")
                self.assertTrue(result["coverage"]["structure_uncertain"])
        for tag in ("script", "template", "noscript", "textarea", "iframe"):
            result = self.parse(f'<{tag}><base href="https://own.example.invalid/"><a href="//own.example.invalid/target">Hidden</a></{tag}>'.encode())
            self.assertEqual(result["matching_links"], [])
            self.assertFalse(result["coverage"]["base_element_seen"])

    def test_unsafe_uri_references_are_omitted_without_private_attributes_and_unsupported_resolution_is_explicit(self):
        unsafe = ("javascript:PRIVATE_SECRET", "//user:password@own.example.invalid/target", "//own.example.invalid/target?code=PRIVATE_SECRET",
            "//own.example.invalid/target#PRIVATE_FRAGMENT", "//own.example.invalid:444/target", "//own.example.invalid/ta%0arget",
            "//own.example.invalid/ta%5crget", "//own.example.invalid/target?", "//own.example.invalid/target#",
            "//own.example.invalid/target&#10;", "//[invalid/target")
        content = ''.join(f'<a href="{href}">Unrelated private identity</a>' for href in unsafe).encode()
        result = self.parse(content)
        self.assertEqual(result["matching_links"], [])
        self.assertEqual(result["coverage"]["unsupported_references"], len(unsafe))
        self.assertEqual(result["unlinked_or_lost_link"], "not_established")
        for secret in ("PRIVATE_SECRET", "PRIVATE_FRAGMENT", "password", "Unrelated private"):
            self.assertNotIn(secret, json.dumps(result))

    def test_reused_syntax_inventory_text_rel_bytes_and_date_limits_keep_partial_unknown_not_loss(self):
        duplicate = self.parse(b'<a href="//own.example.invalid/target" href="//other.example.invalid/">Duplicate</a>')
        self.assertEqual(duplicate["state"], "unavailable_ambiguous_markup")
        matches = self.parse((f'<a href="//own.example.invalid/target" rel="{"r" * 101}">{"x" * 241}</a>' * (MAX_MATCHES + 1)).encode())
        self.assertTrue(matches["coverage"]["matches_capped"])
        self.assertTrue(matches["matching_links"][0]["anchor_text_truncated"])
        self.assertTrue(matches["matching_links"][0]["rel_truncated"])
        limit = self.parse((('<a href="/other">Other</a>' * MAX_ANCHORS) + '<a href="//own.example.invalid/target">Beyond</a>').encode())
        self.assertTrue(limit["coverage"]["anchor_limit_reached"])
        self.assertEqual(limit["matching_links"], [])
        for changes in ({"body": b"x" * (MAX_BODY_BYTES + 1)}, {"body": b"\xff"}, {"observed_at": "2026-01-01T12:00:00"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError): self.parse(b'<p>Fixture</p>', **changes)


class StaticSourceFixture(link_fixtures.LinkReviewFixture):
    def setUp(self):
        super().setUp()
        config = update_project_configuration(project=self.project, user=self.owner, expected_revision=1,
            changes={"research_allowed_origins": ["https://publisher.example.invalid"]})
        self.data["configuration_revision"] = config.revision
        self.draft = self.record()
        self.review = self.transition(self.draft, "review")
        self.approved = self.transition(self.review, "approved")

    def authority(self, **changes):
        return static_link_source_authority(**{**dict(project=self.project, actor=self.owner,
            link_review_id=self.approved.pk, source_collection_permission=True), **changes})


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json"}), DEBUG=True)
class StaticLinkSourceAuthorityTests(StaticSourceFixture, TransactionTestCase):
    def test_actual_unchanged_approved_source_target_actors_rights_have_no_sql_write_or_network(self):
        with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            result = self.authority()
        self.assertFalse(any(re.match(r"\s*(INSERT|UPDATE|DELETE)\b", row["sql"], re.I) for row in queries))
        self.assertEqual(result["link_review_id"], self.approved.pk)
        self.assertEqual(result["source_url"], self.data["source_url"])
        self.assertEqual(result["target_evidence"], self.approved.target_evidence)
        self.assertEqual(result["configuration_revision"], 2)
        self.assertEqual(result["approved_by_id"], self.owner.pk)
        self.assertTrue(all(result["rights"].values()))
        self.assertIn("not_network_authorization", result["interpretation"])

    def test_separate_permission_drafts_wrong_activity_foreign_and_nonlatest_reviews_are_denied(self):
        for permission in (False, None, 1, "true"):
            with self.subTest(permission=permission), self.assertRaises(PermissionDenied):
                self.authority(source_collection_permission=permission)
        for review_id in (self.draft.pk, self.review.pk, True):
            with self.subTest(review_id=review_id), self.assertRaises(ValidationError): self.authority(link_review_id=review_id)
        foreign = Project.objects.create(organization=self.organization, name="Synthetic foreign static source", canonical_origin="https://foreign.example.invalid")
        with self.assertRaises(PermissionDenied): self.authority(project=foreign)
        with self.assertRaises(PermissionDenied): self.authority(link_review_id=self.approved.pk + 100000)
        correction = self.transition(self.approved, "draft", proposal={**self.approved.proposal, "action": "request_source_correction", "outreach_permission": True})
        with self.assertRaises(ValidationError): self.authority()
        approved = self.transition(self.transition(correction, "review"), "approved")
        with self.assertRaises(ValidationError): self.authority(link_review_id=approved.pk)

    def test_source_role_loss_and_exact_current_allow_block_configuration_loss_fail_closed(self):
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
        with self.assertRaises(PermissionDenied): self.authority()
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="owner")
        update_project_configuration(project=self.project, user=self.owner, expected_revision=2,
            changes={"research_allowed_origins": [], "research_blocked_origins": ["https://publisher.example.invalid"]})
        with self.assertRaises(ValidationError): self.authority()
        # A fresh approved human report still cannot authorize a now-blocked source.
        self.data["configuration_revision"] = 3
        draft = self.record(request_key="new-config-static-source")
        approved = self.transition(self.transition(draft, "review"), "approved")
        with self.assertRaises(ValidationError): self.authority(link_review_id=approved.pk)


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json"}), DEBUG=True)
class StaticLinkSourceCollectorTests(StaticSourceFixture, TransactionTestCase):
    def collect(self, responses=None, *, checkpoint=lambda: None, resolver=None, sleep=None, on_request=None):
        self.requests = []
        self.elapsed = 0
        self.waits = []
        binding = self.authority()
        responses = list(responses or [self.robots(), self.html()])

        def factory(scheme, address, hostname, port, _deadline, _clock):
            self.requests.append((scheme, address, hostname, port))
            if on_request:
                on_request(len(self.requests))
            return transport_fixtures.FakeConnection(responses.pop(0))

        def wait(seconds):
            self.waits.append(seconds)
            self.elapsed += seconds
            if sleep:
                sleep()

        transport = SafeFetcher(CrawlScope(frozenset({urlsplit(binding["source_url"]).hostname})),
            max_bytes=MAX_BODY_BYTES, timeout=8, max_redirects=2,
            resolver=resolver or (lambda *_args: ["93.184.216.34"]), connection_factory=factory, clock=lambda: self.elapsed)
        return collect_static_link_source(project=self.project, actor=self.owner, binding=binding,
            before_request=checkpoint, fetcher=transport, clock=lambda: self.elapsed, sleep=wait)

    def robots(self, body=b"User-agent: *\nDisallow:\n", status=200, headers=None):
        return transport_fixtures.FakeResponse(status, body, headers if headers is not None else {"Content-Type": "text/plain"})

    def html(self, body=None, status=200, headers=None):
        body = body if body is not None else (f'<p>Private unrelated fixture-contact@example.invalid</p>'
            f'<a href="{self.data["target_url"]}" rel="nofollow">Literal target</a>').encode()
        return transport_fixtures.FakeResponse(status, body, headers if headers is not None else {"Content-Type": "text/html; charset=utf-8"})

    def test_real_pinned_transport_paces_two_attempts_and_returns_only_minimized_dated_evidence_without_sql_writes(self):
        with patch("jobs.crawling._system_resolver", side_effect=AssertionError("No live DNS")), CaptureQueriesContext(connection) as queries:
            result = self.collect()
        self.assertFalse(any(re.match(r"\s*(INSERT|UPDATE|DELETE)\b", row["sql"], re.I) for row in queries))
        self.assertEqual(result["state"], "collected")
        self.assertEqual(result["requested_url"], self.data["source_url"])
        self.assertEqual(result["evidence"]["matching_links"][0]["anchor_text"], "Literal target")
        self.assertEqual(result["evidence"]["source_url"], result["url"])
        self.assertEqual(result["evidence"]["observed_at"], result["observed_at"])
        self.assertNotIn("fixture-contact", json.dumps(result))
        self.assertEqual(self.waits, [1])
        self.assertEqual(self.requests, [("https", "93.184.216.34", "publisher.example.invalid", 443)] * 2)

    def test_robots_denial_unknown_encoding_types_status_and_limits_never_fetch_source(self):
        for robot in (self.robots(b"User-agent: *\nDisallow: /\n"), self.robots(status=403), self.robots(status=503),
            self.robots(b"\xff"), self.robots(b"Unknown challenge"), self.robots(b"User-agent: *\nDisallow:\nCrawl-delay: 1.5"),
            self.robots(headers={"Content-Type": "text/html"}), self.robots(b"x" * (MAX_BODY_BYTES + 1)),
            self.robots(b"User-agent: *\nDisallow:\nRequest-rate: 1/60"),
            self.robots(b"User-agent: *\nDisallow:\nRequest-rate : 1/60"),
            self.robots(b"User-agent: *\nDisallow:\nCrawl-delay : 1.5")):
            with self.subTest(robot=robot):
                result = self.collect([robot])
                self.assertEqual(result["state"], "unavailable")
                self.assertEqual(len(self.requests), 1)
                self.assertNotIn("evidence", result)
        for rule in ("Disallow: /article$", "Disallow: /*article", "Disallow: /article%24", "Allow: /article*"):
            result = self.collect([self.robots(("User-agent: *\n" + rule).encode())])
            self.assertEqual(result["error_category"], "static_source_robots_unknown")
            self.assertEqual(len(self.requests), 1)
        result = self.collect([self.robots(status=404), self.html()])
        self.assertEqual(result["state"], "collected")
        self.assertEqual(result["robots"], "missing_http_404_or_410")

    def test_redirects_recheck_https_same_origin_and_robots_before_each_actual_request(self):
        for destination in ("http://publisher.example.invalid/down", "https://foreign.example.invalid/",
                            "https://publisher.example.invalid/leak?secret=x", "/denied"):
            with self.subTest(destination=destination):
                result = self.collect([self.robots(b"User-agent: *\nDisallow: /denied"),
                    self.html(status=302, headers={"Location": destination})])
                self.assertEqual(result["state"], "unavailable")
                self.assertEqual(len(self.requests), 2)
        result = self.collect([self.robots(), self.html(status=302, headers={"Location": "/final"}), self.html()])
        self.assertEqual(result["state"], "collected")
        self.assertEqual(result["url"], "https://publisher.example.invalid/final")
        self.assertEqual(result["redirects"], [{"url": self.data["source_url"], "status": 302}])
        self.assertEqual(self.waits, [1, 1])
        result = self.collect([self.robots(status=302, headers={"Location": "http://publisher.example.invalid/robots.txt"})])
        self.assertEqual(result["state"], "unavailable")
        self.assertEqual(len(self.requests), 1)

    def test_private_dns_body_gzip_utf8_content_type_and_missing_markup_fail_honestly_without_replay(self):
        result = self.collect(resolver=lambda *_args: ["93.184.216.34", "127.0.0.1"])
        self.assertEqual(result["error_category"], "non_public_address")
        self.assertEqual(self.requests, [])
        for html in (self.html(b"x" * (MAX_BODY_BYTES + 1)), self.html(b"\xff"), self.html(status=304),
                     self.html(headers={"Content-Type": "application/json"}),
                     self.html(b"bad", headers={"Content-Type": "text/html", "Content-Encoding": "gzip"})):
            with self.subTest(html=html):
                self.assertEqual(self.collect([self.robots(), html])["state"], "unavailable")
                self.assertEqual(len(self.requests), 2)
        result = self.collect([self.robots(), self.html(b"<p>Inspected partial static page</p>")])
        self.assertEqual(result["evidence"]["state"], "not_observed_in_bounded_static_html_not_link_loss")
        self.assertEqual(result["evidence"]["unlinked_or_lost_link"], "not_established")

    def test_source_role_and_budget_cancellation_loss_before_after_request_and_during_pacing_are_not_delivered(self):
        with self.assertRaises(PermissionDenied):
            self.collect(checkpoint=lambda: (_ for _ in ()).throw(PermissionDenied()))
        self.assertEqual(self.requests, [])

        def revoke():
            OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")

        with self.assertRaises(PermissionDenied): self.collect(sleep=revoke)
        self.assertEqual(len(self.requests), 1)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="owner")
        with self.assertRaises(PermissionDenied):
            self.collect(on_request=lambda count: revoke() if count == 2 else None)
        self.assertEqual(len(self.requests), 2)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="owner")
        with self.assertRaises((ValidationError, PermissionDenied)):
            self.collect(on_request=lambda count: update_project_configuration(project=self.project, user=self.owner,
                expected_revision=2, changes={"research_allowed_origins": [], "research_blocked_origins": ["https://publisher.example.invalid"]})
                if count == 1 else None)
        self.assertEqual(len(self.requests), 1)
