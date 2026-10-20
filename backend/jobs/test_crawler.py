from tenancy.customer_artifact_barrier import project_artifact_barrier
from contextlib import nullcontext
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.storage import storages
from django.utils import timezone
from django.db import close_old_connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings

from config.test_foundations import TEST_STORAGES
from tenancy.artifacts import project_artifact_scope
from tenancy.models import DomainAlias
from tenancy.services import create_organization, create_project, update_project_configuration

from .crawler import PageParser, execute_crawl_job, queue_crawl, snapshotted_url_parameter_policy
from .crawling import CrawlScope, FetchResponse
from .models import CrawlPageSnapshot, CrawlRun, JobCancellation, JobStatus, UsageReservation
from .recovery import reconcile_stuck_crawls
from .services import dispatch_pending, transition


class FakeFetcher:
    max_bytes = 2 * 1024 * 1024

    def __init__(self, scope, responses):
        self.scope = scope
        self.responses = {url: list(items) for url, items in responses.items()}
        self.calls = []

    def fetch(self, url, *, request_headers=None, before_request=None, before_send=None, deadline=None):
        url = self.scope.validate_url(url)
        if before_request:
            before_request(url)
        if before_send:
            before_send(url)
        self.calls.append((url, request_headers or {}))
        response = self.responses[url].pop(0)
        if callable(response):
            response = response()
        if isinstance(response, BaseException):
            raise response
        return response


def response(url, *, status=200, body=b"", headers=None):
    return FetchResponse(url=url, status=status, headers=headers or {}, body=body)


@override_settings(
    STORAGES=TEST_STORAGES,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "text/csv", "text/html", "text/plain"}),
)
class CrawlerTests(TransactionTestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("crawler@example.com", password="test-password")
        EmailAddress.objects.create(user=self.owner, email=self.owner.email, verified=True, primary=True)
        self.organization = create_organization(user=self.owner, name="Crawler org")
        self.project = create_project(
            organization=self.organization,
            user=self.owner,
            name="Crawler project",
            canonical_origin="https://crawl.example.com",
        )

    def queue(self, *, key="crawl-1", page_limit=3):
        with patch("jobs.tasks.execute_crawl_job_task.apply_async") as send:
            with self.captureOnCommitCallbacks(execute=True) if isinstance(self, TestCase) else nullcontext():
                job = queue_crawl(
                    project=self.project,
                    actor=self.owner,
                    seeds=[],
                    page_limit=page_limit,
                    idempotency_key=key,
                )
        send.assert_called_once_with(args=[job.pk], queue="crawl", task_id=f"job-{job.pk}", retry=False)
        self.assertEqual(job.usage.provider, "crawler")
        self.assertEqual(job.usage.reserved_units, page_limit)
        return job

    def test_json_ld_parser_distinguishes_invalid_and_capacity_limits(self):
        parser = PageParser()
        parser.feed(
            '<script type="application/ld+json">{"@type":</script>'
            + "".join(
                f'<script type="application/ld+json">{{"@type":"Thing{number}"}}</script>'
                for number in range(21)
            )
        )
        parsed, _links = parser.result(
            base_url=self.project.canonical_origin,
            scope=CrawlScope.for_project(self.project),
        )
        self.assertEqual(len(parsed["structured_data"]), 19)
        self.assertEqual(parsed["structured_data_errors"], [
            {"block": 1, "category": "invalid_json"},
            {"block": 21, "category": "block_limit"},
        ])

    def test_crawl_persists_bounded_observations_artifacts_and_links(self):
        root = "https://crawl.example.com/"
        mapped = "https://crawl.example.com/from-map"
        next_url = "https://crawl.example.com/next"
        canonical = "https://crawl.example.com/canonical"
        html = b"""<html><head><title> Example page </title>
            <meta name="description" content="Evidence page">
            <meta name="robots" content="index,follow">
            <link rel="canonical" href="/canonical">
            <link rel="alternate" hreflang="tr" href="/tr/page">
            <script type="application/ld+json">{"@type":"Article"}</script></head>
            <script type="application/ld+json">{"@type":</script>
            <body><h1>Main heading</h1><a href="/next">Next</a>
            <a href="https://outside.example/path">External</a>
            <a href="http://127.0.0.1/private">Recorded only</a></body></html>"""
        responses = {
            "https://crawl.example.com/robots.txt": [response(
                "https://crawl.example.com/robots.txt",
                body=b"User-agent: *\nAllow: /\nSitemap: /sitemap.xml\n",
            )],
            "https://crawl.example.com/sitemap.xml": [response(
                "https://crawl.example.com/sitemap.xml",
                body=f"<urlset><url><loc>{mapped}</loc></url></urlset>".encode(),
            )],
            root: [response(root, body=html, headers={"content-type": "text/html; charset=utf-8", "etag": '"v1"'})],
            mapped: [response(mapped, body=b"<title>Mapped</title>", headers={"content-type": "text/html"})],
            next_url: [response(next_url, status=404, body=b"<title>Missing</title>", headers={"content-type": "text/html"})],
            canonical: [response(canonical, body=b"<title>Canonical</title>", headers={"content-type": "text/html"})],
        }
        fake = FakeFetcher(None, {})

        def factory(scope):
            fake.scope = scope
            fake.responses = {url: list(items) for url, items in responses.items()}
            return fake

        now = [0.0]

        def sleep(seconds):
            now[0] += seconds

        job = self.queue(page_limit=4)
        self.assertTrue(execute_crawl_job(job.pk, fetcher_factory=factory, clock=lambda: now[0], sleep=sleep))
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.SUCCEEDED)
        self.assertEqual(job.output["pages_attempted"], 4)
        self.assertEqual(job.usage.actual_units, 4)
        pages = list(job.crawl_run.pages.select_related("raw_artifact"))
        self.assertEqual([page.requested_url for page in pages], [root, mapped, next_url, canonical])
        self.assertEqual(job.crawl_run.discovery["sitemap_urls"], [mapped])
        page = pages[0]
        self.assertEqual(page.title, "Example page")
        self.assertEqual(page.headings, [{"level": "h1", "text": "Main heading"}])
        self.assertEqual(page.canonical_url, "https://crawl.example.com/canonical")
        self.assertEqual(page.structured_data, [{"@type": "Article"}])
        self.assertEqual(page.structured_data_errors, [{"block": 2, "category": "invalid_json"}])
        self.assertTrue(page.raw_artifact.key.endswith(".html"))
        self.assertIn({"url": "https://outside.example/path", "internal": False}, page.links)
        self.assertIn({"url": "http://127.0.0.1/private", "internal": False}, page.links)
        self.assertNotIn("https://outside.example/path", [call[0] for call in fake.calls])
        self.assertGreaterEqual(now[0], 4)
        with self.assertRaises(ValidationError):
            page.save()

    def test_crawl_applies_snapshotted_parameter_identity_and_per_path_cap(self):
        update_project_configuration(
            project=self.project,
            user=self.owner,
            expected_revision=0,
            changes={
                "ignored_query_parameters": ["utm_source"],
                "pagination_query_parameters": ["page"],
                "facet_query_parameters": ["color"],
                "query_variant_limit": 2,
            },
        )
        root = "https://crawl.example.com/"
        products_a = "https://crawl.example.com/products?utm_source=a"
        products_b = "https://crawl.example.com/products?utm_source=b"
        products_upper = "https://crawl.example.com/products?UTM_SOURCE=b"
        pages = [f"https://crawl.example.com/listing?page={number}" for number in range(1, 4)]
        unknown = [f"https://crawl.example.com/search?sort={value}" for value in ("price", "rating")]
        links = "".join(
            f'<a href="{url}">link</a>' for url in [products_a, products_b, products_upper, *pages, *unknown]
        ).encode()
        responses = {
            "https://crawl.example.com/robots.txt": [response("https://crawl.example.com/robots.txt", status=404)],
            "https://crawl.example.com/sitemap.xml": [response("https://crawl.example.com/sitemap.xml", status=404)],
            root: [response(root, body=links, headers={"content-type": "text/html"})],
            products_a: [response(products_a, body=b"products", headers={"content-type": "text/html"})],
            products_upper: [response(products_upper, body=b"products upper", headers={"content-type": "text/html"})],
            pages[0]: [response(pages[0], body=b"page1", headers={"content-type": "text/html"})],
            pages[1]: [response(pages[1], body=b"page2", headers={"content-type": "text/html"})],
            unknown[0]: [response(unknown[0], body=b"sort1", headers={"content-type": "text/html"})],
            unknown[1]: [response(unknown[1], body=b"sort2", headers={"content-type": "text/html"})],
        }
        fake = FakeFetcher(None, {})

        def factory(scope):
            fake.scope = scope
            fake.responses = {url: list(items) for url, items in responses.items()}
            return fake

        job = self.queue(key="parameter-rules", page_limit=10)
        self.assertEqual(job.method_version, "crawl-http-v2")
        self.assertEqual(job.config_snapshot["url_parameter_policy"], {
            "ignored": ["utm_source"], "pagination": ["page"], "facet": ["color"], "variant_limit": 2,
        })
        update_project_configuration(
            project=self.project,
            user=self.owner,
            expected_revision=1,
            changes={
                "ignored_query_parameters": ["campaign"],
                "pagination_query_parameters": [],
                "facet_query_parameters": [],
                "query_variant_limit": 25,
            },
        )
        self.assertTrue(execute_crawl_job(job.pk, fetcher_factory=factory, sleep=lambda _seconds: None))
        job.refresh_from_db()
        fetched = [url for url, _headers in fake.calls]
        self.assertEqual(job.status, JobStatus.PARTIALLY_SUCCEEDED)
        self.assertEqual(job.error_category, "partial_coverage")
        self.assertIn(products_a, fetched)
        self.assertNotIn(products_b, fetched)
        self.assertIn(products_upper, fetched)
        self.assertEqual([url for url in pages if url in fetched], pages[:2])
        self.assertEqual([url for url in unknown if url in fetched], unknown)
        self.assertEqual(job.crawl_run.discovery["skipped_parameter_variants"], 1)
        self.assertEqual(job.output["skipped_parameter_variants"], 1)
        configured, legacy_policy = snapshotted_url_parameter_policy(SimpleNamespace(
            config_snapshot={"host_delay_seconds": 1}, method_version="crawl-http-v1",
        ))
        self.assertFalse(configured)
        self.assertEqual(legacy_policy["variant_limit"], 25)

    def test_conditional_response_reuses_same_project_content(self):
        root = "https://crawl.example.com/"

        def run(job, page_response):
            responses = {
                "https://crawl.example.com/robots.txt": [response("https://crawl.example.com/robots.txt", status=404)],
                "https://crawl.example.com/sitemap.xml": [response("https://crawl.example.com/sitemap.xml", status=404)],
                root: [page_response],
            }
            fake = FakeFetcher(None, {})

            def factory(scope):
                fake.scope = scope
                fake.responses = responses
                return fake

            execute_crawl_job(job.pk, fetcher_factory=factory, sleep=lambda _seconds: None)
            return fake

        first = self.queue(key="first", page_limit=1)
        run(first, response(root, body=b"<title>Original</title>", headers={
            "content-type": "text/html", "etag": '"version-1"', "last-modified": "Wed, 01 Jan 2025 00:00:00 GMT",
        }))
        original = first.crawl_run.pages.get()

        second = self.queue(key="second", page_limit=1)
        fake = run(second, response(root, status=304))
        reused = second.crawl_run.pages.get()
        self.assertEqual(reused.status_code, 304)
        self.assertEqual(reused.reused_from, original)
        self.assertEqual(reused.raw_artifact, original.raw_artifact)
        self.assertEqual(reused.content_hash, original.content_hash)
        page_call = next(call for call in fake.calls if call[0] == root)
        self.assertEqual(page_call[1], {
            "If-None-Match": '"version-1"',
            "If-Modified-Since": "Wed, 01 Jan 2025 00:00:00 GMT",
        })

        empty = self.queue(key="empty", page_limit=1)
        run(empty, response(root, headers={"etag": '"empty"'}))
        empty_page = empty.crawl_run.pages.get()
        self.assertEqual(empty_page.content_hash, hashlib.sha256(b"").hexdigest())
        empty_recheck = self.queue(key="empty-recheck", page_limit=1)
        run(empty_recheck, response(root, status=304))
        self.assertEqual(empty_recheck.crawl_run.pages.get().reused_from, empty_page)

    def test_worker_redelivery_resumes_without_duplicate_snapshots(self):
        root = "https://crawl.example.com/"
        next_url = "https://crawl.example.com/next"
        job = self.queue(key="resume", page_limit=2)
        first_responses = {
            "https://crawl.example.com/robots.txt": [response("https://crawl.example.com/robots.txt", status=404)],
            "https://crawl.example.com/sitemap.xml": [response("https://crawl.example.com/sitemap.xml", status=404)],
            root: [response(root, body=b'<a href="/next">Next</a>', headers={"content-type": "text/html"})],
            next_url: [SystemExit("worker lost")],
        }
        first = FakeFetcher(None, {})

        def first_factory(scope):
            first.scope = scope
            first.responses = first_responses
            return first

        with self.assertRaises(SystemExit):
            execute_crawl_job(job.pk, fetcher_factory=first_factory, sleep=lambda _seconds: None)
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.RUNNING)
        self.assertEqual(job.crawl_run.pages.count(), 1)

        second_responses = {
            "https://crawl.example.com/robots.txt": [response("https://crawl.example.com/robots.txt", status=404)],
            next_url: [response(next_url, body=b"<title>Resumed</title>", headers={"content-type": "text/html"})],
        }
        second = FakeFetcher(None, {})

        def second_factory(scope):
            second.scope = scope
            second.responses = second_responses
            return second

        self.assertTrue(execute_crawl_job(job.pk, fetcher_factory=second_factory, sleep=lambda _seconds: None))
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.SUCCEEDED)
        self.assertEqual(job.crawl_run.pages.count(), 2)
        self.assertEqual(set(job.crawl_run.pages.values_list("requested_url", flat=True)), {root, next_url})
        self.assertNotIn(root, [call[0] for call in second.calls])

    def test_cross_project_reuse_and_out_of_scope_seeds_fail(self):
        other_owner = get_user_model().objects.create_user("other-crawler@example.com", password="test-password")
        EmailAddress.objects.create(user=other_owner, email=other_owner.email, verified=True, primary=True)
        other_org = create_organization(user=other_owner, name="Other crawler org")
        other_project = create_project(
            organization=other_org,
            user=other_owner,
            name="Other crawler project",
            canonical_origin="https://other.example.com",
        )
        with self.assertRaises(ValidationError):
            queue_crawl(
                project=self.project,
                actor=self.owner,
                seeds=[other_project.canonical_origin],
                page_limit=1,
                idempotency_key="outside",
            )

        job = self.queue(key="scope", page_limit=1)
        run = CrawlRun.objects.create(
            job=job,
            organization=self.organization,
            project=self.project,
            page_limit=1,
        )
        with self.assertRaises(ValidationError):
            CrawlPageSnapshot(
                crawl_run=run,
                project=other_project,
                requested_url=other_project.canonical_origin,
            ).full_clean()

    def test_discovery_stops_on_cancellation_and_start_denials_are_truthful(self):
        from .crawling import SafeFetcher
        from .test_crawling import FakeConnection, FakeResponse
        for phase in ("dns", "tls"):
            with self.subTest(phase=phase):
                delayed = self.queue(key=f"cancel-during-{phase}", page_limit=1)
                def revoke():
                    JobCancellation.objects.get_or_create(job=delayed, defaults={"requested_by": self.owner})
                def resolver(*_args):
                    if phase == "dns":
                        revoke()
                    return ["93.184.216.34"]
                def connection(*_args):
                    self.assertEqual(phase, "tls", "DNS cancellation must stop before connecting")
                    result = FakeConnection(FakeResponse())
                    result.connect = revoke
                    result.request = lambda *_args, **_kwargs: self.fail("Cancellation must stop before sending GET")
                    return result
                self.assertTrue(execute_crawl_job(delayed.pk,
                    fetcher_factory=lambda scope: SafeFetcher(scope, resolver=resolver, connection_factory=connection),
                    sleep=lambda _seconds: None))
                delayed.refresh_from_db()
                self.assertEqual((delayed.status, delayed.error_category), (JobStatus.CANCELLED, "cancelled"))
                self.assertEqual(delayed.usage.state, UsageReservation.State.RELEASED)
                self.assertEqual(delayed.crawl_run.pages.count(), 0)
        root = "https://crawl.example.com/"
        cancelled = self.queue(key="cancel-discovery", page_limit=1)
        fake = FakeFetcher(None, {})
        responses = {
            "https://crawl.example.com/robots.txt": [response("https://crawl.example.com/robots.txt", status=404)],
        }

        def factory(scope):
            fake.scope = scope
            fake.responses = responses
            return fake

        now = [0.0]

        def cancel_during_pacing(seconds):
            JobCancellation.objects.create(job=cancelled, requested_by=self.owner)
            now[0] += seconds

        self.assertTrue(execute_crawl_job(
            cancelled.pk,
            fetcher_factory=factory,
            clock=lambda: now[0],
            sleep=cancel_during_pacing,
        ))
        cancelled.refresh_from_db()
        self.assertEqual((cancelled.status, cancelled.error_category), (JobStatus.CANCELLED, "cancelled"))
        self.assertEqual([call[0] for call in fake.calls], ["https://crawl.example.com/robots.txt"])
        self.assertEqual(cancelled.usage.state, UsageReservation.State.RELEASED)

        revoked = self.queue(key="revoked", page_limit=1)
        self.organization.is_suspended = True
        self.organization.save(update_fields=["is_suspended"])
        self.assertTrue(execute_crawl_job(revoked.pk, fetcher_factory=lambda _scope: self.fail("must not fetch")))
        revoked.refresh_from_db()
        self.assertEqual((revoked.status, revoked.error_category), (JobStatus.CANCELLED, "actor_revoked"))

        self.organization.is_suspended = False
        self.organization.save(update_fields=["is_suspended"])
        limited = self.queue(key="limited", page_limit=1)
        limited.usage.state = UsageReservation.State.RELEASED
        limited.usage.settled_at = timezone.now()
        limited.usage.save(update_fields=["state", "settled_at"])
        self.assertTrue(execute_crawl_job(limited.pk, fetcher_factory=lambda _scope: self.fail("must not fetch")))
        limited.refresh_from_db()
        self.assertEqual((limited.status, limited.error_category), (JobStatus.CANCELLED, "usage_unreserved"))

        missing = self.queue(key="missing-reservation", page_limit=1)
        missing.usage.delete()
        self.assertTrue(execute_crawl_job(missing.pk, fetcher_factory=lambda _scope: self.fail("must not fetch")))
        missing.refresh_from_db()
        self.assertEqual((missing.status, missing.error_category), (JobStatus.CANCELLED, "usage_unreserved"))

    def test_trial_expiry_after_dispatch_stops_before_fetching(self):
        job = self.queue(key="expired-after-dispatch", page_limit=1)
        transition(job, JobStatus.RUNNING)
        trial = job.organization.trial
        trial.started_at = timezone.now() - timedelta(days=31)
        trial.ends_at = timezone.now() - timedelta(days=1)
        trial.save(update_fields=["started_at", "ends_at"])

        self.assertTrue(execute_crawl_job(job.pk, fetcher_factory=lambda _scope: self.fail("must not fetch")))
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category), (JobStatus.CANCELLED, "trial_unavailable"))
        self.assertEqual(job.usage.state, UsageReservation.State.RELEASED)

    def test_removed_alias_stops_before_the_next_remote_request(self):
        alias = DomainAlias.objects.create(
            organization=self.organization,
            project=self.project,
            origin="https://alias.example.com",
        )
        root = "https://crawl.example.com/"
        alias_page = "https://alias.example.com/page"
        with patch("jobs.tasks.execute_crawl_job_task.apply_async"):
            job = queue_crawl(
                project=self.project,
                actor=self.owner,
                seeds=[alias_page],
                page_limit=2,
                idempotency_key="scope-change",
            )
        fake = FakeFetcher(None, {})

        def remove_alias():
            alias.delete()
            return response(root)

        def factory(scope):
            fake.scope = scope
            fake.responses = {
                "https://crawl.example.com/robots.txt": [response("https://crawl.example.com/robots.txt", status=404)],
                "https://crawl.example.com/sitemap.xml": [response("https://crawl.example.com/sitemap.xml", status=404)],
                root: [remove_alias],
            }
            return fake

        self.assertTrue(execute_crawl_job(job.pk, fetcher_factory=factory, sleep=lambda _seconds: None))
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category), (JobStatus.CANCELLED, "scope_revoked"))
        self.assertEqual(job.crawl_run.pages.count(), 1)
        self.assertNotIn("https://alias.example.com/robots.txt", [call[0] for call in fake.calls])

    def test_deadline_and_hostile_markup_finish_with_bounded_evidence(self):
        root = "https://crawl.example.com/"
        deadline = self.queue(key="deadline", page_limit=1)
        fake = FakeFetcher(None, {})

        def factory(scope):
            fake.scope = scope
            fake.responses = {
                "https://crawl.example.com/robots.txt": [response("https://crawl.example.com/robots.txt", status=404)],
            }
            return fake

        now = [0.0]
        with patch("jobs.crawler.CRAWL_DEADLINE_SECONDS", 1):
            self.assertTrue(execute_crawl_job(
                deadline.pk,
                fetcher_factory=factory,
                clock=lambda: now[0],
                sleep=lambda seconds: now.__setitem__(0, now[0] + seconds),
            ))
        deadline.refresh_from_db()
        self.assertEqual((deadline.status, deadline.error_category), (JobStatus.FAILED, "crawl_deadline"))

        hostile = self.queue(key="hostile", page_limit=1)
        deep = "[" * 30 + "0" + "]" * 30
        body = f'<script type="application/ld+json">NaN</script><script type="application/ld+json">{deep}</script>'.encode()
        hostile_fake = FakeFetcher(None, {})

        def hostile_factory(scope):
            hostile_fake.scope = scope
            hostile_fake.responses = {
                "https://crawl.example.com/robots.txt": [response("https://crawl.example.com/robots.txt", status=404)],
                "https://crawl.example.com/sitemap.xml": [response("https://crawl.example.com/sitemap.xml", status=404)],
                root: [response(root, body=body, headers={"content-type": "text/html; charset=utf-8"})],
            }
            return hostile_fake

        self.assertTrue(execute_crawl_job(hostile.pk, fetcher_factory=hostile_factory, sleep=lambda _seconds: None))
        self.assertEqual(hostile.crawl_run.pages.get().structured_data, [])

        invalid_encoding = self.queue(key="invalid-encoding", page_limit=1)
        encoding_fake = FakeFetcher(None, {})

        def encoding_factory(scope):
            encoding_fake.scope = scope
            encoding_fake.responses = {
                "https://crawl.example.com/robots.txt": [response("https://crawl.example.com/robots.txt", status=404)],
                "https://crawl.example.com/sitemap.xml": [response("https://crawl.example.com/sitemap.xml", status=404)],
                root: [response(root, body=b"\xff", headers={"content-type": "text/html; charset=utf-8"})],
            }
            return encoding_fake

        self.assertTrue(execute_crawl_job(invalid_encoding.pk, fetcher_factory=encoding_factory, sleep=lambda _seconds: None))
        invalid_encoding.refresh_from_db()
        self.assertEqual((invalid_encoding.status, invalid_encoding.error_category), (JobStatus.FAILED, "crawl_incomplete"))
        self.assertEqual(invalid_encoding.crawl_run.pages.get().error_category, "invalid_html_encoding")

    def test_discovery_and_robots_gaps_are_truthful_terminal_results(self):
        root = "https://crawl.example.com/"

        def run(key, responses):
            job = self.queue(key=key, page_limit=1)
            fake = FakeFetcher(None, {})

            def factory(scope):
                fake.scope = scope
                fake.responses = responses
                return fake

            self.assertTrue(execute_crawl_job(job.pk, fetcher_factory=factory, sleep=lambda _seconds: None))
            job.refresh_from_db()
            return job

        partial = run("sitemap-partial", {
            "https://crawl.example.com/robots.txt": [response(
                "https://crawl.example.com/robots.txt",
                body=b"User-agent: *\nAllow: /\nSitemap: /sitemap.xml\n",
            )],
            "https://crawl.example.com/sitemap.xml": [response("https://crawl.example.com/sitemap.xml", status=500)],
            root: [response(root)],
        })
        self.assertEqual((partial.status, partial.error_category), (JobStatus.PARTIALLY_SUCCEEDED, "partial_coverage"))
        self.assertEqual(partial.output["sitemap_failures"], 1)

        blocked = run("robots-blocked", {
            "https://crawl.example.com/robots.txt": [response(
                "https://crawl.example.com/robots.txt",
                body=b"User-agent: *\nDisallow: /\n",
            )],
            "https://crawl.example.com/sitemap.xml": [response("https://crawl.example.com/sitemap.xml", status=404)],
        })
        self.assertEqual((blocked.status, blocked.error_category), (JobStatus.FAILED, "crawl_incomplete"))
        self.assertEqual((blocked.output["pages_attempted"], blocked.output["skipped_robots"]), (0, 1))

    def test_artifact_is_reused_after_loss_before_snapshot_commit(self):
        root = "https://crawl.example.com/"
        body = b"<title>Durable</title>"
        job = self.queue(key="artifact-resume", page_limit=1)

        def factory(responses):
            fake = FakeFetcher(None, {})

            def build(scope):
                fake.scope = scope
                fake.responses = responses
                return fake

            return build

        first = {
            "https://crawl.example.com/robots.txt": [response("https://crawl.example.com/robots.txt", status=404)],
            "https://crawl.example.com/sitemap.xml": [response("https://crawl.example.com/sitemap.xml", status=404)],
            root: [response(root, body=body, headers={"content-type": "text/html"})],
        }
        with patch.object(CrawlPageSnapshot.objects, "create", side_effect=SystemExit("worker lost")):
            with self.assertRaises(SystemExit):
                execute_crawl_job(job.pk, fetcher_factory=factory(first), sleep=lambda _seconds: None)
        self.assertEqual(job.artifacts.count(), 0)
        self.assertEqual(job.crawl_run.pages.count(), 0)
        old_key = f"{project_artifact_scope(self.project)}/jobs/{job.pk}/{hashlib.sha256(body).hexdigest()[:32]}.html"
        self.assertTrue(storages["artifacts"].exists(old_key))

        changed_body = b"<title>Changed after loss</title>"
        second = {
            "https://crawl.example.com/robots.txt": [response("https://crawl.example.com/robots.txt", status=404)],
            root: [response(root, body=changed_body, headers={"content-type": "text/html"})],
        }
        self.assertTrue(execute_crawl_job(job.pk, fetcher_factory=factory(second), sleep=lambda _seconds: None))
        self.assertEqual(job.artifacts.count(), 1)
        self.assertEqual(job.crawl_run.pages.count(), 1)
        self.assertFalse(storages["artifacts"].exists(old_key))

    def test_committed_snapshots_control_cancelled_usage_and_dispatch_release(self):
        root = "https://crawl.example.com/"
        next_url = "https://crawl.example.com/next"
        job = self.queue(key="durable-usage", page_limit=2)
        fake = FakeFetcher(None, {})

        def factory(scope):
            fake.scope = scope
            fake.responses = {
                "https://crawl.example.com/robots.txt": [response("https://crawl.example.com/robots.txt", status=404)],
                "https://crawl.example.com/sitemap.xml": [response("https://crawl.example.com/sitemap.xml", status=404)],
                root: [response(root, body=b'<a href="/next">Next</a>', headers={"content-type": "text/html"})],
                next_url: [SystemExit("worker lost")],
            }
            return fake

        with self.assertRaises(SystemExit):
            execute_crawl_job(job.pk, fetcher_factory=factory, sleep=lambda _seconds: None)
        CrawlRun.objects.filter(job=job).update(pages_attempted=0, pages_observed=0)
        JobCancellation.objects.create(job=job, requested_by=self.owner)
        self.assertTrue(execute_crawl_job(job.pk, fetcher_factory=lambda _scope: self.fail("must not fetch")))
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.CANCELLED)
        self.assertEqual((job.usage.state, job.usage.actual_units), (UsageReservation.State.SETTLED, 1))

        unreserved = self.queue(key="durable-unreserved", page_limit=2)
        with self.assertRaises(SystemExit):
            execute_crawl_job(unreserved.pk, fetcher_factory=factory, sleep=lambda _seconds: None)
        unreserved.usage.state = UsageReservation.State.RELEASED
        unreserved.usage.settled_at = timezone.now()
        unreserved.usage.save(update_fields=["state", "settled_at"])
        self.assertTrue(execute_crawl_job(
            unreserved.pk,
            fetcher_factory=lambda _scope: self.fail("must not fetch"),
        ))
        unreserved.refresh_from_db()
        unreserved.usage.refresh_from_db()
        self.assertEqual((unreserved.status, unreserved.error_category), (JobStatus.CANCELLED, "usage_unreserved"))
        self.assertEqual((unreserved.usage.state, unreserved.usage.actual_units), (UsageReservation.State.RELEASED, 0))

        undispatched = self.queue(key="dispatch-capacity", page_limit=1)
        type(undispatched).objects.filter(pk=undispatched.pk).update(dispatched_at=None)
        with patch("jobs.usage.usage_denial", return_value="internal_capacity"):
            self.assertFalse(dispatch_pending(undispatched.pk))
        undispatched.refresh_from_db()
        self.assertEqual((undispatched.status, undispatched.error_category), (JobStatus.CANCELLED, "internal_capacity"))
        self.assertEqual(undispatched.usage.state, UsageReservation.State.RELEASED)

    def test_denied_recovery_cleanup_waits_for_enclosing_commit_and_survives_rollback(self):
        from config.artifacts import save_private_artifact
        from .models import JobRun
        job = self.queue(key="recovery-commit-cleanup", page_limit=1)
        transition(job, JobStatus.RUNNING)
        CrawlRun.objects.create(job=job, organization=self.organization, project=self.project, page_limit=1)
        with project_artifact_barrier(self.project.organization_id, shared=True):
            key = save_private_artifact(scope=f"{project_artifact_scope(self.project)}/jobs/{job.pk}",
                content=b'{"uncommitted":true}', content_type="application/json")
        JobRun.objects.filter(pk=job.pk).update(updated_at=timezone.now() - timedelta(minutes=3))
        self.organization.is_suspended = True
        self.organization.save(update_fields=["is_suspended"])
        with transaction.atomic():
            self.assertEqual(reconcile_stuck_crawls(), 0)
            job.refresh_from_db()
            self.assertEqual(job.status, JobStatus.CANCELLED)
            self.assertTrue(storages["artifacts"].exists(key))
            transaction.set_rollback(True)
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.RUNNING)
        self.assertTrue(storages["artifacts"].exists(key))
        self.assertEqual(reconcile_stuck_crawls(), 0)
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.CANCELLED)
        self.assertFalse(storages["artifacts"].exists(key))


@override_settings(
    STORAGES=TEST_STORAGES,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "text/csv", "text/html", "text/plain"}),
)
class CrawlerConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("crawler-concurrency@example.com", password="test-password")
        EmailAddress.objects.create(user=self.owner, email=self.owner.email, verified=True, primary=True)
        self.organization = create_organization(user=self.owner, name="Crawler concurrency org")
        self.project = create_project(
            organization=self.organization,
            user=self.owner,
            name="Crawler concurrency project",
            canonical_origin="https://concurrent.example.com",
        )

    def queue(self, key):
        with patch("jobs.tasks.execute_crawl_job_task.apply_async"):
            return queue_crawl(
                project=self.project,
                actor=self.owner,
                seeds=[],
                page_limit=1,
                idempotency_key=key,
            )

    def test_live_duplicate_exits_and_stale_running_crawl_is_republished(self):
        root = "https://concurrent.example.com/"
        job = self.queue("concurrent")
        entered = Event()
        release = Event()
        fake = FakeFetcher(None, {})

        def factory(scope):
            fake.scope = scope
            fake.responses = {
                "https://concurrent.example.com/robots.txt": [response("https://concurrent.example.com/robots.txt", status=404)],
                "https://concurrent.example.com/sitemap.xml": [response("https://concurrent.example.com/sitemap.xml", status=404)],
                root: [response(root)],
            }
            original = fake.fetch

            def blocking_fetch(url, **kwargs):
                if not entered.is_set():
                    entered.set()
                    if not release.wait(timeout=10):
                        raise RuntimeError("test worker was not released")
                return original(url, **kwargs)

            fake.fetch = blocking_fetch
            return fake

        def worker():
            close_old_connections()
            try:
                return execute_crawl_job(job.pk, fetcher_factory=factory, sleep=lambda _seconds: None)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(worker)
            try:
                self.assertTrue(entered.wait(timeout=10))
                self.assertFalse(execute_crawl_job(job.pk, fetcher_factory=lambda _scope: self.fail("must not fetch")))
            finally:
                release.set()
            self.assertTrue(future.result(timeout=10))
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.SUCCEEDED)
        self.assertEqual(job.crawl_run.pages.count(), 1)

        stale = self.queue("stale")
        type(stale).objects.filter(pk=stale.pk).update(
            status=JobStatus.RUNNING,
            updated_at=timezone.now() - timedelta(minutes=2),
        )
        with patch("jobs.tasks.execute_crawl_job_task.apply_async") as send:
            self.assertEqual(reconcile_stuck_crawls(stale_seconds=60), 1)
        send.assert_called_once_with(args=[stale.pk], queue="crawl", task_id=f"job-{stale.pk}", retry=False)

        expired = self.queue("stale-expired")
        CrawlRun.objects.create(
            job=expired,
            organization=self.organization,
            project=self.project,
            page_limit=1,
        )
        type(expired).objects.filter(pk=expired.pk).update(
            status=JobStatus.RUNNING,
            updated_at=timezone.now() - timedelta(minutes=2),
        )
        trial = self.organization.trial
        trial.started_at = timezone.now() - timedelta(days=31)
        trial.ends_at = timezone.now() - timedelta(days=1)
        trial.save(update_fields=["started_at", "ends_at"])
        with patch("jobs.tasks.execute_crawl_job_task.apply_async") as send:
            self.assertEqual(reconcile_stuck_crawls(stale_seconds=60), 0)
        send.assert_not_called()
        expired.refresh_from_db()
        expired.usage.refresh_from_db()
        self.assertEqual((expired.status, expired.error_category), (JobStatus.CANCELLED, "trial_unavailable"))
        self.assertEqual(expired.usage.state, UsageReservation.State.RELEASED)
