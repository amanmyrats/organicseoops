from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch
from zoneinfo import ZoneInfo

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from integrations.search_console import queue_search_console_csv_import
from integrations.models import ImportRun
from integrations.services import create_connection
from tenancy.models import Project
from tenancy.services import create_organization, create_project, update_project_configuration

from .crawling import FetchResponse
from .models import JobCancellation, JobRun, JobStatus, JobStep, TopicCandidateSnapshot, UsageReservation
from .recovery import reconcile_stuck_topic_jobs
from .services import execute_job, retry_job
from .topic_discovery import _stop, queue_topic_discovery


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/csv"}))
class TopicDiscoveryTests(TransactionTestCase):
    feed = "https://feeds.example/rss.xml"
    other_feed = "https://feeds.example/other.xml"
    body = (b'<rss version="2.0"><channel><item><title>Local update</title>'
            b'<link>https://feeds.example/story</link></item></channel></rss>')

    def setUp(self):
        dispatch = patch("jobs.services.dispatch_pending", return_value=False)
        self.addCleanup(dispatch.stop)
        dispatch.start()
        users = get_user_model().objects
        self.owner = users.create_user("topic-owner@example.com", password="test-password")
        self.outsider = users.create_user("topic-outsider@example.com", password="test-password")
        for user in (self.owner, self.outsider):
            EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
        organization = create_organization(user=self.owner, name="Topic org")
        self.project = create_project(organization=organization, user=self.owner, name="Topic site",
                                      canonical_origin="https://topic.example")
        update_project_configuration(project=self.project, user=self.owner, expected_revision=0,
                                     changes={"research_allowed_origins": ["https://feeds.example"],
                                              "rss_feed_urls": [self.feed, self.other_feed],
                                              "target_country": "Türkiye", "target_languages": ["tr"]})

    def queue(self, *, feeds=None, key="topic-test", **kwargs):
        return queue_topic_discovery(project=self.project, actor=self.owner, feeds=[self.feed] if feeds is None else feeds,
                                     idempotency_key=key, **kwargs)

    def factory(self, url, *, during=None):
        body = self.body if url == self.feed else b"<html>unsupported</html>"
        content_type = "application/rss+xml" if url == self.feed else "text/html"

        class Fetcher:
            def fetch(self, requested, *, before_request):
                before_request(requested)
                if during:
                    during()
                return FetchResponse(url=requested, status=200, headers={"content-type": content_type}, body=body)

        return Fetcher()

    def test_released_reservation_does_not_rollback_terminal_denial(self):
        job = self.queue()
        JobRun.objects.filter(pk=job.pk).update(status=JobStatus.RUNNING)
        JobStep.objects.create(
            job=job,
            sequence=1,
            name="Collect configured feed",
            status=JobStep.Status.RUNNING,
            output={"state": "attempted"},
        )
        UsageReservation.objects.filter(job=job).update(
            state=UsageReservation.State.RELEASED,
            settled_at=timezone.now(),
        )
        self.assertTrue(_stop(job.pk, category="usage_unreserved", cancelled=True))
        job.refresh_from_db()
        job.usage.refresh_from_db()
        self.assertEqual((job.status, job.error_category), (JobStatus.CANCELLED, "usage_unreserved"))
        self.assertEqual((job.usage.state, job.usage.actual_units), (UsageReservation.State.RELEASED, 0))

    def test_partial_feed_job_has_durable_evidence_usage_and_same_job_deduplication(self):
        job = self.queue(feeds=[self.feed, self.other_feed])
        self.assertEqual(self.queue(feeds=[self.feed, self.other_feed]).pk, job.pk)
        self.assertEqual(job.usage.reserved_units, 2)
        from .topic_discovery import execute_topic_discovery
        self.assertTrue(execute_topic_discovery(job.pk, fetcher_factory=self.factory))
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.PARTIALLY_SUCCEEDED)
        self.assertEqual(job.error_category, "partial_sources")
        self.assertEqual((job.usage.state, job.usage.actual_units), (UsageReservation.State.SETTLED, 2))
        snapshot = TopicCandidateSnapshot.objects.get(job=job)
        self.assertEqual(snapshot.output["candidates"][0]["kind"], "public_feed_item")
        self.assertEqual(snapshot.output["coverage"]["failed_feeds"][0]["category"], "unsupported_feed_type")
        self.assertEqual((snapshot.output["coverage"]["market"], snapshot.output["coverage"]["languages"]),
                         ("Türkiye", ["tr"]))
        self.assertEqual(job.steps.count(), 2)
        self.assertFalse(execute_topic_discovery(job.pk, fetcher_factory=self.factory))
        self.assertEqual(TopicCandidateSnapshot.objects.count(), 1)
        with self.assertRaisesMessage(ValidationError, "immutable"):
            snapshot.save()
        sibling = Project.objects.create(
            organization=self.project.organization, name="Sibling", canonical_origin="https://topic-sibling.example",
        )
        snapshot.project = sibling
        snapshot._state.adding = True
        with self.assertRaisesMessage(ValidationError, "same-project"):
            snapshot.full_clean()
        with self.assertRaisesMessage(ValidationError, "fresh source selection"):
            retry_job(job=job, actor=self.owner, idempotency_key="old-topic-retry")

    def test_revoked_feed_and_actor_block_queue_or_worker(self):
        with self.assertRaises(PermissionDenied):
            queue_topic_discovery(project=self.project, actor=self.outsider, feeds=[self.feed], idempotency_key="denied")
        with self.assertRaises(ValidationError):
            self.queue(feeds=["https://outside.example/rss.xml"], key="outside")
        job = self.queue(key="revoked")
        update_project_configuration(project=self.project, user=self.owner, expected_revision=1,
                                     changes={"rss_feed_urls": []})
        from .topic_discovery import execute_topic_discovery
        self.assertTrue(execute_topic_discovery(job.pk, fetcher_factory=self.factory))
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category), (JobStatus.CANCELLED, "source_scope_changed"))
        self.assertEqual(job.usage.state, UsageReservation.State.RELEASED)
        self.assertFalse(TopicCandidateSnapshot.objects.exists())

    def test_cancellation_after_fetch_settles_attempt_and_leaves_no_snapshot(self):
        job = self.queue(key="cancel")
        from .topic_discovery import execute_topic_discovery
        self.assertTrue(execute_topic_discovery(job.pk, fetcher_factory=lambda url: self.factory(
            url, during=lambda: JobCancellation.objects.create(job_id=job.pk, requested_by=self.owner),
        )))
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.CANCELLED)
        self.assertEqual(job.usage.actual_units, 1)
        self.assertEqual(job.steps.get().status, JobStep.Status.FAILED)
        self.assertFalse(TopicCandidateSnapshot.objects.exists())

    def test_worker_loss_redelivery_and_stale_recovery_reuse_one_running_stage(self):
        job = self.queue(key="worker-loss")
        from .topic_discovery import execute_topic_discovery
        with patch("jobs.topic_discovery.collect_project_feed", side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                execute_topic_discovery(job.pk, fetcher_factory=self.factory)
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.RUNNING)
        self.assertEqual(job.steps.get().status, JobStep.Status.RUNNING)
        JobRun.objects.filter(pk=job.pk).update(updated_at=timezone.now() - timedelta(minutes=3))
        with patch("jobs.tasks.execute_topics_task.apply_async") as publish:
            self.assertEqual(reconcile_stuck_topic_jobs(), 1)
        publish.assert_called_once()
        self.assertTrue(execute_topic_discovery(job.pk, fetcher_factory=self.factory))
        self.assertEqual(job.steps.count(), 1)
        self.assertEqual(TopicCandidateSnapshot.objects.count(), 1)

    def test_unexpected_finalization_failure_preserves_useful_partial_snapshot(self):
        job = self.queue(key="finalization-error")
        from .topic_candidates import normalize_topic_candidates
        from .topic_discovery import execute_topic_discovery
        attempts = 0

        def fail_once(**kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("synthetic failure")
            return normalize_topic_candidates(**kwargs)

        with patch("jobs.topic_discovery.normalize_topic_candidates", side_effect=fail_once):
            self.assertTrue(execute_topic_discovery(job.pk, fetcher_factory=self.factory))
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category), (JobStatus.PARTIALLY_SUCCEEDED, "handler_failed"))
        self.assertEqual(job.topic_candidates.output["candidates"][0]["url"], "https://feeds.example/story")
        self.assertEqual(job.usage.actual_units, 1)

    def test_stale_recovery_denies_revoked_actor_without_republishing(self):
        job = self.queue(key="stalled-revoked")
        from .topic_discovery import execute_topic_discovery
        with patch("jobs.topic_discovery.collect_project_feed", side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                execute_topic_discovery(job.pk, fetcher_factory=self.factory)
        get_user_model().objects.filter(pk=self.owner.pk).update(is_active=False)
        JobRun.objects.filter(pk=job.pk).update(updated_at=timezone.now() - timedelta(minutes=3))
        with patch("jobs.tasks.execute_topics_task.apply_async") as publish:
            self.assertEqual(reconcile_stuck_topic_jobs(), 0)
        publish.assert_not_called()
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category), (JobStatus.CANCELLED, "actor_revoked"))
        self.assertEqual(job.usage.actual_units, 1)
        self.assertEqual(job.steps.get().status, JobStep.Status.FAILED)

    def test_stale_denial_keeps_released_usage_terminal(self):
        job = self.queue(key="stalled-unreserved")
        from .topic_discovery import execute_topic_discovery
        with patch("jobs.topic_discovery.collect_project_feed", side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                execute_topic_discovery(job.pk, fetcher_factory=self.factory)
        UsageReservation.objects.filter(job=job).update(
            state=UsageReservation.State.RELEASED,
            settled_at=timezone.now(),
        )
        JobRun.objects.filter(pk=job.pk).update(updated_at=timezone.now() - timedelta(minutes=3))
        with patch("jobs.tasks.execute_topics_task.apply_async") as publish:
            self.assertEqual(reconcile_stuck_topic_jobs(), 0)
        publish.assert_not_called()
        job.refresh_from_db()
        job.usage.refresh_from_db()
        self.assertEqual((job.status, job.error_category), (JobStatus.CANCELLED, "usage_unreserved"))
        self.assertEqual((job.usage.state, job.usage.actual_units), (UsageReservation.State.RELEASED, 0))

    def test_query_only_job_retains_first_party_window_and_never_fetches(self):
        connection = create_connection(
            project=self.project, user=self.owner, provider="google_search_console",
            external_property_id=self.project.canonical_origin, capabilities=["csv_import", "query_metrics"],
            available_dimensions=["query"], source_semantics="search_console_performance",
            source_semantics_version="csv-v1", timezone="America/Los_Angeles",
        )
        end = timezone.now().astimezone(ZoneInfo("America/Los_Angeles")).date() - timedelta(days=2)
        runs = []
        for start, last, clicks in ((end - timedelta(days=13), end - timedelta(days=7), 2),
                                    (end - timedelta(days=6), end, 5)):
            job = queue_search_console_csv_import(
                connection=connection, user=self.owner,
                content=f"Top queries,Clicks,Impressions,CTR,Position\nobserved topic,{clicks},20,10%,3\n".encode(),
                date_start=start, date_end=last,
            )
            self.assertTrue(execute_job(job.pk))
            runs.append(ImportRun.objects.get(job=job))
        job = self.queue(feeds=[], connection=connection, previous_import_id=runs[0].pk,
                         current_import_id=runs[1].pk, key="query-only")
        from .topic_discovery import execute_topic_discovery
        with patch("jobs.topic_discovery.collect_project_feed", side_effect=AssertionError("unexpected fetch")):
            self.assertTrue(execute_topic_discovery(job.pk))
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.SUCCEEDED)
        self.assertEqual(job.usage.actual_units, 1)
        output = job.topic_candidates.output
        self.assertEqual(output["candidates"][0]["kind"], "first_party_query_growth")
        self.assertEqual(output["candidates"][0]["click_change"], 3)
        self.assertEqual(output["query_source"]["connection_id"], connection.pk)
        self.assertEqual(output["query_source"]["coverage"]["hidden_queries"], "unknown")
        self.assertEqual(output["feeds"], [])

    def test_disconnected_query_source_does_not_block_independent_feed(self):
        connection = create_connection(
            project=self.project, user=self.owner, provider="google_search_console",
            external_property_id=self.project.canonical_origin, capabilities=["csv_import", "query_metrics"],
            available_dimensions=["query"], source_semantics="search_console_performance",
            source_semantics_version="csv-v1", timezone="America/Los_Angeles",
        )
        end = timezone.now().astimezone(ZoneInfo("America/Los_Angeles")).date() - timedelta(days=2)
        runs = []
        for start, last, clicks in ((end - timedelta(days=13), end - timedelta(days=7), 2),
                                    (end - timedelta(days=6), end, 5)):
            import_job = queue_search_console_csv_import(
                connection=connection, user=self.owner,
                content=f"Top queries,Clicks,Impressions,CTR,Position\nquery,{clicks},20,10%,3\n".encode(),
                date_start=start, date_end=last,
            )
            self.assertTrue(execute_job(import_job.pk))
            runs.append(ImportRun.objects.get(job=import_job))
        job = self.queue(feeds=[self.feed], connection=connection, previous_import_id=runs[0].pk,
                         current_import_id=runs[1].pk, key="disconnected-query")
        type(connection).objects.filter(pk=connection.pk).update(state="disconnected")
        from .topic_discovery import execute_topic_discovery
        self.assertTrue(execute_topic_discovery(job.pk, fetcher_factory=self.factory))
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.PARTIALLY_SUCCEEDED)
        self.assertEqual(job.steps.get(sequence=1).output["state"], "not_collected")
        self.assertEqual(job.usage.actual_units, 1)
        self.assertEqual(job.topic_candidates.output["query_source"]["state"], "unavailable")
        self.assertEqual([item["kind"] for item in job.topic_candidates.output["candidates"]], ["public_feed_item"])


class TopicConcurrencyTests(TransactionTestCase):
    def test_duplicate_delivery_during_feed_fetch_is_suppressed(self):
        owner = get_user_model().objects.create_user("topic-concurrent@example.com", password="test-password")
        EmailAddress.objects.create(user=owner, email=owner.email, primary=True, verified=True)
        organization = create_organization(user=owner, name="Concurrent topic org")
        project = create_project(organization=organization, user=owner, name="Site",
                                 canonical_origin="https://concurrent-topic.example")
        url = "https://feeds.example/rss.xml"
        update_project_configuration(project=project, user=owner, expected_revision=0,
                                     changes={"research_allowed_origins": ["https://feeds.example"],
                                              "rss_feed_urls": [url]})
        with patch("jobs.services.dispatch_pending", return_value=False):
            job = queue_topic_discovery(project=project, actor=owner, feeds=[url], idempotency_key="concurrency")
        fetching = Event()
        release = Event()

        class Fetcher:
            def fetch(self, requested, *, before_request):
                before_request(requested)
                fetching.set()
                release.wait(timeout=5)
                return FetchResponse(url=requested, status=200, headers={"content-type": "application/rss+xml"},
                                     body=TopicDiscoveryTests.body)

        from .topic_discovery import execute_topic_discovery

        def execute():
            close_old_connections()
            try:
                return execute_topic_discovery(job.pk, fetcher_factory=lambda _url: Fetcher())
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=1) as executor:
            first = executor.submit(execute)
            self.assertTrue(fetching.wait(timeout=5))
            self.assertFalse(execute())
            release.set()
            self.assertTrue(first.result(timeout=10))
        self.assertEqual(TopicCandidateSnapshot.objects.filter(job=job).count(), 1)
        self.assertEqual(job.steps.count(), 1)
