from datetime import timedelta
import json
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from .crawling import FetchResponse
from .news import ATTRIBUTION, collect_project_news, news_request_url
from config.test_foundations import TEST_STORAGES


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "news-api-fixtures"}})
class NewsSourceTests(TransactionTestCase):
    def setUp(self):
        from .test_topic_discovery import TopicDiscoveryTests
        self.feed = TopicDiscoveryTests.feed
        self.other_feed = TopicDiscoveryTests.other_feed
        TopicDiscoveryTests.setUp(self)
        from tenancy.services import update_project_configuration
        update_project_configuration(project=self.project, user=self.owner, expected_revision=1,
            changes={"seed_topics": ["local service news"]})
        self.selection = {"phrase": "local service news", "publisher_origin": "https://feeds.example", "days": 7}
        self.as_of = timezone.now() - timedelta(minutes=1)
        self.body = b'<rss><channel><item><title>Untrusted &lt;script&gt; title</title><link>https://feeds.example/story</link></item></channel></rss>'

    def collect(self, *, body=None, status=200, during=None, response_url=None, content_type="application/rss+xml"):
        selected_body = self.body if body is None else body
        class Fetcher:
            def fetch(inner, url, *, before_request):
                before_request(url)
                if during:
                    during()
                return FetchResponse(url=response_url or url, status=status, headers={"content-type": content_type}, body=selected_body)
        return collect_project_news(project=self.project, actor=self.owner, selection=self.selection, as_of=self.as_of, fetcher=Fetcher())

    def test_fixed_bounded_request_and_inert_metadata_never_fetch_publisher(self):
        url = news_request_url(self.selection, self.as_of)
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query["query"], ['"local service news" domainis:feeds.example'])
        self.assertEqual(query["format"], ["rss"])
        self.assertEqual(query["maxrecords"], ["20"])
        result = self.collect()
        self.assertEqual(result["attribution_url"], ATTRIBUTION)
        self.assertEqual(result["items"][0]["title"], "Untrusted <script> title")
        self.assertEqual(result["items"][0]["url"], "https://feeds.example/story")
        self.assertEqual(result["market_language"], "not_verified_english_translingual_search")
        self.assertEqual(result["publisher_content"], "not_fetched_not_licensed")
        with self.assertRaises(PermissionDenied):
            collect_project_news(project=self.project, actor=self.outsider, selection=self.selection, as_of=self.as_of)
        for changes in ({"phrase": 'bad" OR topic'}, {"phrase": "not configured"}, {"days": True}, {"days": 30},
                        {"publisher_origin": "https://feeds.example/path"}, {"publisher_origin": "https://other.example"}):
            with self.subTest(changes=changes), self.assertRaises((ValidationError, PermissionDenied)):
                collect_project_news(project=self.project, actor=self.owner, selection={**self.selection, **changes}, as_of=self.as_of)

    def test_metadata_caps_unsafe_xml_links_and_failed_sources_are_not_zero_demand(self):
        item = '<item><title>News {}</title><link>https://feeds.example/story{}</link></item>'
        body = ('<rss><channel>' + ''.join(item.format(i, i) for i in range(21)) + '</channel></rss>').encode()
        result = self.collect(body=body)
        self.assertEqual((result["state"], len(result["items"]), result["truncated"]), ("partial", 20, True))
        unsafe = b'<rss><channel><item><title>Unsafe</title><link>https://feeds.example/story?token=bad</link></item></channel></rss>'
        self.assertEqual((self.collect(body=unsafe)["state"], self.collect(body=unsafe)["items"]), ("partial", []))
        self.assertEqual(self.collect(status=429)["error"], "news_rate_limited")
        self.assertEqual(self.collect(content_type="text/html")["state"], "failed")
        self.assertEqual(self.collect(body=b'<!DOCTYPE rss><rss/>')["error"], "unsafe_xml")
        self.assertEqual(self.collect(response_url="https://outside.example/")["error"], "news_endpoint_denied")

    def test_inflight_source_or_actor_revocation_discards_metadata(self):
        from tenancy.models import ProjectConfiguration
        with self.assertRaises(PermissionDenied):
            self.collect(during=lambda: ProjectConfiguration.objects.filter(project=self.project).update(research_blocked_origins=["https://feeds.example"]))
        ProjectConfiguration.objects.filter(project=self.project).update(research_blocked_origins=[])
        with self.assertRaises(PermissionDenied):
            self.collect(during=lambda: type(self.owner).objects.filter(pk=self.owner.pk).update(is_active=False))

    def test_optional_news_failure_preserves_independent_feed_and_accounts_attempts(self):
        from .topic_discovery import execute_topic_discovery, queue_topic_discovery
        with patch("jobs.services.dispatch_pending"):
            job = queue_topic_discovery(project=self.project, actor=self.owner, feeds=[self.feed], news=self.selection,
                idempotency_key="news-partial-first")
        self.assertEqual(job.usage.reserved_units, 2)
        body = self.body
        class Fetcher:
            def fetch(inner, url, *, before_request):
                before_request(url)
                return FetchResponse(url=url, status=429 if url.startswith("https://api.gdeltproject.org/") else 200,
                    headers={"content-type": "application/rss+xml"}, body=body)
        self.assertTrue(execute_topic_discovery(job.pk, fetcher_factory=lambda _: Fetcher()))
        job.refresh_from_db()
        self.assertEqual(job.status, "partially_succeeded")
        self.assertEqual(job.usage.actual_units, 2)
        self.assertEqual(job.topic_candidates.output["news"]["error"], "news_rate_limited")
        self.assertEqual(job.topic_candidates.output["candidates"][0]["kind"], "public_feed_item")
        self.assertFalse(execute_topic_discovery(job.pk, fetcher_factory=lambda _: self.fail("No terminal replay")))

    def test_news_candidates_are_reviewable_with_current_provenance_and_cancelled_attempts_keep_usage(self):
        from tenancy.models import ProjectConfiguration
        from .models import JobCancellation
        from .topic_discovery import execute_topic_discovery, queue_topic_discovery
        from .topic_review import current_topic_candidate, HUMAN_COMPONENTS, review_topic
        from .services import retry_job
        with patch("jobs.services.dispatch_pending"):
            job = queue_topic_discovery(project=self.project, actor=self.owner, feeds=[], news=self.selection,
                idempotency_key="news-success-first")
        body = self.body
        class Fetcher:
            def fetch(inner, url, *, before_request):
                before_request(url)
                return FetchResponse(url=url, status=200, headers={"content-type": "application/rss+xml"}, body=body)
        self.assertTrue(execute_topic_discovery(job.pk, fetcher_factory=lambda _: Fetcher()))
        job.refresh_from_db()
        self.assertEqual(job.method_version, "topic-discovery-v2")
        candidate = job.topic_candidates.output["candidates"][0]
        self.assertEqual(candidate["kind"], "provider_news_article")
        self.assertEqual(candidate["news_as_of"], job.created_at.isoformat())
        self.assertEqual(job.usage.actual_units, 1)
        review = review_topic(project=self.project, actor=self.owner, snapshot_id=job.topic_candidates.pk,
            candidate_index=0, expected_revision=0, request_key="news-human-review", label="Human news hypothesis", classification="unknown",
            language="tr", intent_review_id=None, judgments={name: {"score": None, "note": ""} for name in HUMAN_COMPONENTS}, reason="Review bounded provider metadata.")
        self.assertEqual(review.report["demand_volume"], "unavailable_not_zero")
        with self.assertRaises(ValidationError):
            retry_job(job=job, actor=self.owner, idempotency_key="no-generic-news-retry")
        with patch("jobs.services.dispatch_pending"):
            cancelled = queue_topic_discovery(project=self.project, actor=self.owner, feeds=[], news=self.selection,
                idempotency_key="news-cancel-second")
        class CancellingFetcher:
            def fetch(inner, url, *, before_request):
                before_request(url)
                JobCancellation.objects.create(job=cancelled, requested_by=self.owner)
                return FetchResponse(url=url, status=200, headers={"content-type": "application/rss+xml"}, body=body)
        self.assertTrue(execute_topic_discovery(cancelled.pk, fetcher_factory=lambda _: CancellingFetcher()))
        cancelled.refresh_from_db()
        self.assertEqual((cancelled.status, cancelled.usage.actual_units), ("cancelled", 1))
        self.assertFalse(hasattr(cancelled, "topic_candidates"))
        ProjectConfiguration.objects.filter(project=self.project).update(research_blocked_origins=[self.selection["publisher_origin"]])
        with self.assertRaises(PermissionDenied):
            current_topic_candidate(project=self.project, actor=self.owner, snapshot_id=job.topic_candidates.pk, candidate_index=0)

    def test_news_api_requires_configured_scoped_choice_csrf_and_one_reserved_unit(self):
        root = f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}/topics/"
        payload = {"feeds": [], "connection_id": None, "previous_import_id": None, "current_import_id": None,
            "news": self.selection, "idempotency_key": "news-api-selection"}
        client = Client(enforce_csrf_checks=True); client.force_login(self.owner)
        self.assertEqual(client.get(root).json()["news"]["phrases"], ["local service news"])
        self.assertEqual(client.post(root, json.dumps(payload), content_type="application/json").status_code, 403)
        client.get("/_allauth/browser/v1/auth/session")
        def post(data):
            with patch("jobs.services.dispatch_pending"):
                return client.post(root, json.dumps(data), content_type="application/json", HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        response = post(payload)
        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(response.json()["estimated_units"], 1)
        self.assertEqual(post(payload).json()["job_id"], response.json()["job_id"])
        self.assertEqual(post({**payload, "news": {**self.selection, "publisher_origin": "https://foreign.example"}}).status_code, 403)
        self.assertEqual(post({**payload, "news": {**self.selection, "phrase": 'bad" OR scope'}}).status_code, 409)
        other = Client(); other.force_login(self.outsider)
        self.assertEqual(other.get(root).status_code, 404)

    def test_legacy_v1_feed_delivery_keeps_its_original_snapshot_method(self):
        from .models import JobRun
        from .topic_discovery import execute_topic_discovery, queue_topic_discovery
        with patch("jobs.services.dispatch_pending"):
            job = queue_topic_discovery(project=self.project, actor=self.owner, feeds=[self.feed], idempotency_key="legacy-topic-feed")
        JobRun.objects.filter(pk=job.pk).update(method_version="topic-discovery-v1")
        body = self.body
        class Fetcher:
            def fetch(inner, url, *, before_request):
                before_request(url)
                return FetchResponse(url=url, status=200, headers={"content-type": "application/rss+xml"}, body=body)
        self.assertTrue(execute_topic_discovery(job.pk, fetcher_factory=lambda _: Fetcher()))
        job.refresh_from_db()
        self.assertEqual(job.topic_candidates.method_version, "topic-discovery-v1")
        self.assertEqual(job.output["snapshot_method"], "topic-discovery-v1")
        self.assertNotIn("news", job.topic_candidates.output)
