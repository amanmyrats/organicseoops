from datetime import datetime, timezone as utc

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase

from tenancy.services import create_organization, create_project, update_project_configuration

from .crawling import FetchDenied, FetchResponse
from .feeds import MAX_FEED_BYTES, collect_project_feed, parse_feed
from .topic_candidates import normalize_topic_candidates


class StubFetcher:
    def __init__(self, *, body, url="https://feeds.example/rss.xml", status=200, content_type="application/rss+xml",
                 hop=None, during=None):
        self.body = body
        self.url = url
        self.status = status
        self.content_type = content_type
        self.hop = hop
        self.during = during

    def fetch(self, url, *, before_request):
        before_request(url)
        if self.hop:
            before_request(self.hop)
        if self.during:
            self.during()
        return FetchResponse(url=self.url, status=self.status, headers={"content-type": self.content_type}, body=self.body)


class FeedTests(TestCase):
    feed = "https://feeds.example/rss.xml"
    allowed = {"https://feeds.example"}
    when = datetime(2026, 9, 26, tzinfo=utc.utc)
    body = (b'<rss version="2.0"><channel>'
            b'<item><title>Distinct update</title><link>https://feeds.example/a</link>'
            b'<pubDate>Fri, 25 Sep 2026 10:00:00 GMT</pubDate></item>'
            b'<item><title>Distinct update</title><link>https://feeds.example/b</link>'
            b'<pubDate>Fri, 25 Sep 2026 10:00:00 GMT</pubDate></item>'
            b'</channel></rss>')

    def setUp(self):
        self.owner = get_user_model().objects.create_user("feed-owner@example.com", password="test-password")
        self.outsider = get_user_model().objects.create_user("feed-outsider@example.com", password="test-password")
        for user in (self.owner, self.outsider):
            EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
        organization = create_organization(user=self.owner, name="Feed org")
        self.project = create_project(organization=organization, user=self.owner, name="Site",
                                      canonical_origin="https://project.example")
        update_project_configuration(project=self.project, user=self.owner, expected_revision=0,
                                     changes={"research_allowed_origins": ["https://feeds.example"],
                                              "rss_feed_urls": [self.feed]})

    def test_bounded_feed_parser_preserves_distinct_links_and_rejects_invalid_or_stale_claims(self):
        parsed = parse_feed(body=self.body, feed_url=self.feed, allowed_origins=self.allowed, collected_at=self.when)
        self.assertEqual(parsed["state"], "complete_for_bounded_feed")
        self.assertEqual({item["url"] for item in parsed["items"]}, {"https://feeds.example/a", "https://feeds.example/b"})
        self.assertEqual({item["observation"] for item in parsed["items"]},
                         {"public_feed_item_not_popularity_or_business_relevance"})
        for hostile, error in ((b"<!DOCTYPE rss [<!ENTITY x 'secret'>]><rss/>", "unsafe_xml"),
                               (b"<rss>", "invalid_xml"), (b"\xff", "invalid_xml"),
                               (b"x" * (MAX_FEED_BYTES + 1), "feed_size_or_encoding")):
            with self.subTest(error=error):
                self.assertEqual(parse_feed(body=hostile, feed_url=self.feed,
                                            allowed_origins=self.allowed)["error"], error)
        queried = self.body.replace(b"https://feeds.example/a", b"https://feeds.example/?p=1")
        self.assertEqual(parse_feed(body=queried, feed_url=self.feed,
                                    allowed_origins=self.allowed, collected_at=self.when)["rejected"], 1)
        atom = (b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Atom update</title>'
                b'<link href="https://feeds.example/atom"/><updated>2026-09-25T12:00:00Z</updated></entry></feed>')
        self.assertEqual(parse_feed(body=atom, feed_url=self.feed, allowed_origins=self.allowed,
                                    collected_at=self.when)["items"][0]["freshness"], "recent")
        first_item = b"<item>" + self.body.split(b"<item>", 1)[1].split(b"</item>", 1)[0] + b"</item>"
        repeated = self.body.replace(b"</channel>", first_item + b"</channel>")
        self.assertEqual(len(parse_feed(body=repeated, feed_url=self.feed, allowed_origins=self.allowed,
                                        collected_at=self.when)["items"]), 2)
        stale = self.body.replace(b"Fri, 25 Sep 2026 10:00:00 GMT", b"Thu, 25 Sep 2025 10:00:00 GMT")
        self.assertTrue(all(item["freshness"] == "stale" for item in parse_feed(
            body=stale, feed_url=self.feed, allowed_origins=self.allowed, collected_at=self.when)["items"]))
        future = self.body.replace(b"Fri, 25 Sep 2026 10:00:00 GMT", b"Mon, 25 Sep 2028 10:00:00 GMT")
        self.assertEqual(parse_feed(body=future, feed_url=self.feed, allowed_origins=self.allowed,
                                    collected_at=self.when)["rejected"], 2)

    def test_fetch_hops_scope_current_authorization_and_content_failures(self):
        result = collect_project_feed(project=self.project, user=self.owner, feed_url=self.feed,
                                      fetcher=StubFetcher(body=self.body))
        self.assertEqual(result["state"], "complete_for_bounded_feed")
        self.assertEqual(result["source_feed"], self.feed)
        for hop in ("http://feeds.example/rss.xml", "https://outside.example/rss.xml",
                    "https://feeds.example/rss.xml?key=secret"):
            with self.subTest(hop=hop):
                self.assertEqual(collect_project_feed(
                    project=self.project, user=self.owner, feed_url=self.feed,
                    fetcher=StubFetcher(body=self.body, hop=hop),
                )["error"], "feed_scope_denied")
        self.assertEqual(collect_project_feed(project=self.project, user=self.owner, feed_url=self.feed,
            fetcher=StubFetcher(body=b"<html>wrong type</html>", content_type="text/html"))["error"], "unsupported_feed_type")
        with self.assertRaises(PermissionDenied):
            collect_project_feed(project=self.project, user=self.outsider, feed_url=self.feed,
                                 fetcher=StubFetcher(body=self.body))

        def revoke():
            update_project_configuration(project=self.project, user=self.owner, expected_revision=1,
                                         changes={"rss_feed_urls": []})

        self.assertEqual(collect_project_feed(project=self.project, user=self.owner, feed_url=self.feed,
            fetcher=StubFetcher(body=self.body, during=revoke))["error"], "feed_scope_revoked")

    def test_dedup_preserves_distinct_items_and_source_labels(self):
        first = parse_feed(body=self.body, feed_url=self.feed, allowed_origins=self.allowed, collected_at=self.when)
        first["source_feed"] = self.feed
        second = parse_feed(body=self.body, feed_url="https://feeds.example/other.xml",
                            allowed_origins=self.allowed, collected_at=self.when)
        second["source_feed"] = "https://feeds.example/other.xml"
        normalized = normalize_topic_candidates(feeds=[first, second])
        self.assertEqual(len(normalized["candidates"]), 2)
        self.assertEqual(normalized["candidates"][0]["source_feeds"], [self.feed, "https://feeds.example/other.xml"])
        self.assertEqual(normalized["candidates"][0]["trend_state"], "not_measured")
        second["items"][0]["published_at"] = "2026-09-24T10:00:00+00:00"
        distinct = normalize_topic_candidates(feeds=[first, second])
        self.assertEqual(len(distinct["candidates"]), 3)
        self.assertTrue(distinct["coverage"]["popularity_is_not_business_relevance"])
