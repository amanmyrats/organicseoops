from copy import deepcopy
import json
from urllib.parse import parse_qs, urlsplit

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from .test_performance_transport import FakeConnection, FakeResponse
from .youtube import parse_youtube_search, youtube_request_path, youtube_search_request, youtube_video_url, YouTubeSourceError


class YouTubeSourceTests(TransactionTestCase):
    def setUp(self):
        from .test_topic_discovery import TopicDiscoveryTests
        from tenancy.services import update_project_configuration
        self.feed = TopicDiscoveryTests.feed; self.other_feed = TopicDiscoveryTests.other_feed
        TopicDiscoveryTests.setUp(self)
        update_project_configuration(project=self.project, user=self.owner, expected_revision=1,
            changes={"seed_topics": ["service news"], "target_languages": ["en"]})
        self.selection = {"phrase": "service news", "region_code": "TR", "relevance_language": "en", "days": 7}
        self.as_of = timezone.now()
        self.key = "fixture_youtube_key_not_a_real_secret"
        self.page = {"kind": "youtube#searchListResponse", "regionCode": "US", "nextPageToken": "bounded-next-token", "items": [
            {"kind": "youtube#searchResult", "id": {"kind": "youtube#video", "videoId": "video_12345"},
             "snippet": {"publishedAt": "2026-09-30T01:02:03Z", "channelId": "UC" + "x" * 22,
                "title": "Unchanged <script> title &amp; text", "channelTitle": "Original channel title"}}]}

    def transport(self, response=None, *, addresses=("8.8.8.8",), during=None, actor=None, checkpoint=None):
        connection = FakeConnection(response or FakeResponse(json.dumps(self.page).encode()))
        observed = []
        def resolver(host, port, timeout):
            observed.append((host, port)); return addresses
        def factory(scheme, address, host, port, deadline, clock):
            observed.append((scheme, address, host, port))
            if during:
                during()
            return connection
        def call():
            return youtube_search_request(project=self.project, actor=actor or self.owner, selection=self.selection,
                as_of=self.as_of, api_key=self.key, resolver=resolver, connection_factory=factory, checkpoint=checkpoint)
        return call, connection, observed

    def test_public_search_keeps_metadata_order_actual_region_and_header_only_key(self):
        call, connection, observed = self.transport()
        self.assertEqual(call(), self.page)
        self.assertTrue(connection.closed)
        self.assertEqual(observed, [("www.googleapis.com", 443), ("https", "8.8.8.8", "www.googleapis.com", 443)])
        method, path, _body, headers = connection.requests[0]
        self.assertEqual(method, "GET")
        self.assertNotIn(self.key, path)
        self.assertEqual(headers["X-goog-api-key"], self.key)
        query = parse_qs(urlsplit(path).query)
        self.assertEqual((query["q"], query["regionCode"], query["maxResults"], query["type"]), (["service news"], ["TR"], ["20"], ["video"]))
        self.assertEqual(self.page["regionCode"], "US")  # Returned viewability region is not the requested market.
        self.assertEqual(youtube_video_url("video_12345"), "https://www.youtube.com/watch?v=video_12345")

    def test_malformed_or_over_cap_pages_are_rejected_never_filtered_or_scored(self):
        cases = []
        for edit in (lambda row: row["items"][0]["id"].update(kind="youtube#channel"),
                     lambda row: row["items"][0]["id"].update(videoId="bad/?token=secret"),
                     lambda row: row["items"][0]["snippet"].update(publishedAt="2026-01-01"),
                     lambda row: row["items"][0]["snippet"].update(title="x" * 513),
                     lambda row: row.update(items=row["items"] * 21),
                     lambda row: row.update(items=row["items"] * 2),
                     lambda row: row.update(regionCode="unsafe")):
            page = deepcopy(self.page); edit(page); cases.append(page)
        for page in cases:
            with self.subTest(page=page["regionCode"]), self.assertRaises(YouTubeSourceError):
                parse_youtube_search(page)
        empty = {"kind": "youtube#searchListResponse", "regionCode": "TR", "items": []}
        self.assertEqual(parse_youtube_search(empty), empty)
        with self.assertRaises(ValidationError):
            youtube_video_url("https://outside.example/")

    def test_endpoint_errors_private_dns_and_invalid_json_do_not_echo_key_or_provider_body(self):
        for status in (302, 403, 429, 500):
            call, connection, _ = self.transport(FakeResponse(b'provider secret details', status=status))
            with self.subTest(status=status), self.assertRaises(YouTubeSourceError) as error:
                call()
            self.assertNotIn("secret", str(error.exception)); self.assertNotIn(self.key, str(error.exception))
            self.assertTrue(connection.closed); self.assertEqual(len(connection.requests), 1)
        for body in (b'{"items":[],"items":[]}', b'{"items":NaN}', b'not JSON', b'x' * (128 * 1024 + 1)):
            call, connection, _ = self.transport(FakeResponse(body))
            with self.subTest(size=len(body)), self.assertRaises(YouTubeSourceError):
                call()
            self.assertTrue(connection.closed)
        call, connection, _ = self.transport(addresses=("8.8.8.8", "127.0.0.1"))
        with self.assertRaises(YouTubeSourceError) as error:
            call()
        self.assertEqual(error.exception.category, "egress_denied")
        self.assertEqual(connection.requests, [])

    def test_foreign_actor_source_change_and_checkpoint_stop_before_secret_delivery(self):
        from tenancy.models import ProjectConfiguration
        call, connection, observed = self.transport(actor=self.outsider)
        with self.assertRaises(PermissionDenied):
            call()
        self.assertEqual(observed, [])
        call, connection, _ = self.transport(during=lambda: ProjectConfiguration.objects.filter(project=self.project).update(seed_topics=[]))
        with self.assertRaises(PermissionDenied):
            call()
        self.assertEqual(connection.requests, []); self.assertTrue(connection.closed)
        with self.assertRaises(ValidationError):
            youtube_request_path({**self.selection, "phrase": "query|operator"}, self.as_of)
