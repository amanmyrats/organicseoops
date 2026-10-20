import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event
from unittest.mock import patch
from zipfile import ZipFile

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from kombu.exceptions import OperationalError

from config.artifacts import ArtifactNotFound
from config.test_foundations import TEST_STORAGES
from tenancy.artifacts import delete_project_artifact, read_project_artifact, save_project_artifact
from tenancy.models import Organization, OrganizationMembership, OrganizationTrial, ProjectConfiguration
from . import competitor_collection as lifecycle, competitor_page_dates_collection as collection
from . import test_competitor_collection as fixtures
from .models import Artifact, CrawlRun, Finding, JobCancellation, JobRun, JobStep, UsageReservation
from .recovery import reconcile_stuck_competitor_roots
from .services import cancel_job, dispatch_pending, execute_job, queue_job, retry_job
from .usage import UsageLimitError, reconcile_usage


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}))
class CompetitorPageDatesCollectionTests(TransactionTestCase):
    def setUp(self):
        fixtures.CompetitorCollectionTests.setUp(self)
        self.data["url"] = self.data["origin"] + "/selected/article"
    transport = fixtures.CompetitorCollectionTests.transport
    revoke = fixtures.CompetitorCollectionTests.revoke
    HTML = (b'<title>Public selected page</title><meta property="article:published_time" content="2099-01-01">'
        b'<meta property="article:modified_time" content="Unverified update"><p>private-contact@example.invalid</p>')


    def queue(self, key="page-request", **changes):
        with patch("jobs.tasks.execute_competitor_page_dates_collection_task.apply_async") as task:
            job = collection.queue_competitor_page_dates_collection(**{**dict(project=self.project, actor=self.owner,
                data=self.data, idempotency_key=key), **changes})
        self.dispatch = task
        return job

    def fetcher(self, **kwargs):
        return fixtures.CompetitorCollectionTests.fetcher(self, **{"body": self.HTML, **kwargs})

    def read(self, job, *, actor=None):
        return collection.read_competitor_page_dates_observation(project=self.project, actor=actor or self.owner, job_id=job.pk)

    def test_genuine_protected_once_only_original_page_private_reader_and_closed_old_consumers(self):
        job = self.queue()
        self.dispatch.assert_called_once_with(args=[job.pk], queue="crawl", task_id=f"job-{job.pk}", retry=False)
        self.assertEqual((job.method_version, job.usage.provider, job.usage.reserved_units), (collection.METHOD, "competitor_source", 1))
        self.assertEqual(self.queue().pk, job.pk); self.dispatch.assert_not_called()
        with patch("socket.create_connection", side_effect=AssertionError("No actual egress")):
            self.assertTrue(collection.execute_competitor_page_dates_collection(job.pk, fetcher=self.fetcher()))
        job.refresh_from_db(); self.assertEqual(job.status, "succeeded")
        result = self.read(job, actor=self.admin)
        self.assertEqual(self.read(job), result)
        self.assertEqual(result["collection"]["evidence"]["declarations"], [
            {"property": "article:published_time", "value": "2099-01-01", "truncated": False},
            {"property": "article:modified_time", "value": "Unverified update", "truncated": False}])
        self.assertEqual(result["collection"]["requested_url"], self.data["url"])
        self.assertEqual([conn.request.call_args.args for conn in self.connections], [("GET", "/robots.txt"), ("GET", "/selected/article")])
        content = read_project_artifact(project=self.project, key=job.artifacts.get().key)
        self.assertEqual(json.loads(content), result["collection"])
        self.assertNotIn(b"private", content)
        self.assertEqual((job.steps.get().name, job.usage.actual_units, job.usage.state), (collection.STAGE, 1, "settled"))
        self.assertEqual(len(self.connections), 2)
        self.assertTrue(all(conn.request.call_count == 1 for conn in self.connections))
        self.assertFalse(CrawlRun.objects.exists()); self.assertFalse(Finding.objects.exists())
        with self.assertRaises(PermissionDenied): lifecycle.read_competitor_observation(project=self.project, actor=self.owner, job_id=job.pk)
        with self.assertRaises(ValidationError): lifecycle.validate_result(result["collection"], job.config_snapshot["binding"])
        from .competitor_schema_collection import read_competitor_schema_observation, validate_result as validate_schema_result
        with self.assertRaises(PermissionDenied): read_competitor_schema_observation(project=self.project, actor=self.owner, job_id=job.pk)
        with self.assertRaises(ValidationError): validate_schema_result(result["collection"], job.config_snapshot["binding"])
        from .competitor_links_collection import read_competitor_links_observation, validate_result as validate_links_result
        with self.assertRaises(PermissionDenied): read_competitor_links_observation(project=self.project, actor=self.owner, job_id=job.pk)
        with self.assertRaises(ValidationError): validate_links_result(result["collection"], job.config_snapshot["binding"])
        from .competitor_page_collection import read_competitor_page_observation, validate_result as validate_page_result
        with self.assertRaises(PermissionDenied): read_competitor_page_observation(project=self.project, actor=self.owner, job_id=job.pk)
        with self.assertRaises(ValidationError): validate_page_result(result["collection"], job.config_snapshot["binding"])
        from .competitor_page_headings_collection import read_competitor_page_headings_observation, validate_result as validate_headings_result
        with self.assertRaises(PermissionDenied): read_competitor_page_headings_observation(project=self.project, actor=self.owner, job_id=job.pk)
        with self.assertRaises(ValidationError): validate_headings_result(result["collection"], job.config_snapshot["binding"])
        from .competitor_page_destinations_collection import read_competitor_page_destinations_observation, validate_result as validate_destinations_result
        with self.assertRaises(PermissionDenied): read_competitor_page_destinations_observation(project=self.project, actor=self.owner, job_id=job.pk)
        with self.assertRaises(ValidationError): validate_destinations_result(result["collection"], job.config_snapshot["binding"])
        from .api import _job_payload
        self.assertFalse({"output", "steps", "citations", "artifacts"} & set(_job_payload(job, detailed=True)))
        job.output = {**job.output, "raw_body": "private"}
        with self.assertRaises(ValidationError): job.save()
        job.refresh_from_db()
        step = job.steps.get(); step.output = {"href": "private"}
        with self.assertRaises(ValidationError): step.save()
        artifact = job.artifacts.get(); artifact.content_type = "text/html"
        with self.assertRaises(ValidationError): artifact.save()
        self.assertFalse(lifecycle.execute_competitor_collection(job.pk, fetcher=self.fetcher()))
        with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No replay")):
            self.assertFalse(execute_job(job.pk))

    def test_exact_independent_rights_original_method_models_manual_outer_atomic_and_expired_queue(self):
        for key in ("collection_permission", "use_permission", "storage_permission"):
            for value in (False, 1, "true", None):
                with self.subTest(key=key, value=value), self.assertRaises(ValidationError): self.queue(data={**self.data, key: value})
        with self.assertRaises(PermissionDenied): self.queue(actor=self.foreign)
        config = collection.selection_snapshot(self.project, self.owner, self.data)
        with self.assertRaises(ValidationError):
            queue_job(project=self.project, actor=self.owner, handler=collection.HANDLER, input_snapshot=self.data,
                config_snapshot={**config, "method": lifecycle.METHOD}, idempotency_key="old")
        job = self.queue()
        with transaction.atomic(), self.assertRaises(ValidationError): collection.execute_competitor_page_dates_collection(job.pk, fetcher=self.fetcher())
        self.assertFalse(job.steps.exists())
        with self.assertRaises(ValidationError):
            JobRun.objects.create(project=self.project, organization=self.organization, actor=self.owner,
                handler=collection.HANDLER, method_version=collection.METHOD, input_snapshot=self.data,
                config_snapshot=config, scheduled_for=timezone.now())
        for url in (self.data["origin"] + "/", self.data["origin"] + "/selected/article?secret=value", "https://foreign.example.invalid/page"):
            with self.subTest(url=url), self.assertRaises((ValidationError, PermissionDenied)): self.queue("invalid-uri", data={**self.data, "url": url})
        with self.assertRaises(ValidationError): self.queue("missing-uri", data={key: value for key, value in self.data.items() if key != "url"})
        with self.assertRaises((ValidationError, PermissionDenied)): self.queue(data={**self.data, "url": self.data["origin"] + "/other"})
        changed = {**config, "binding": {**config["binding"], "url": self.data["origin"] + "/other"}}
        with self.assertRaises((ValidationError, PermissionDenied)):
            queue_job(project=self.project, actor=self.owner, handler=collection.HANDLER, input_snapshot=self.data,
                config_snapshot=changed, idempotency_key="mismatched-url")
        now = timezone.now()
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now-timedelta(days=31), ends_at=now-timedelta(days=1))
        with self.assertRaises(UsageLimitError): self.queue("expired")

    def test_empty_and_unavailable_are_original_evidence_not_page_identity_or_zero(self):
        for state, body in (("observed", b"<p>No selected metadata</p>"), ("unavailable", b"<title>Unclosed")):
            job = self.queue("availability-" + state)
            self.assertTrue(collection.execute_competitor_page_dates_collection(job.pk, fetcher=self.fetcher(body=body)))
            job.refresh_from_db(); self.assertEqual(job.status, "succeeded")
            evidence = self.read(job)["collection"]["evidence"]
            self.assertEqual(evidence["state"], state)
            self.assertEqual(evidence["declarations"], [] if state == "observed" else None)

    def test_actual_corrupt_missing_storage_receipts_rollback_private_rows_cleanup_once_only_one_unit(self):
        for state in ("corrupt", "missing"):
            job = self.queue("receipt-" + state); keys = []
            def save(**kwargs):
                key = save_project_artifact(**{**kwargs, **({"content": b"{}"} if state == "corrupt" else {})})
                keys.append(key)
                if state == "missing": delete_project_artifact(project=kwargs["project"], key=key)
                return key
            with patch.object(lifecycle, "save_project_artifact", side_effect=save):
                collection.execute_competitor_page_dates_collection(job.pk, fetcher=self.fetcher())
            job.refresh_from_db(); self.assertEqual(job.status, "failed")
            self.assertFalse(job.output); self.assertFalse(job.artifacts.exists()); self.assertFalse(job.citations.exists())
            self.assertEqual((job.usage.actual_units, job.usage.state), (1, "settled"))
            self.assertEqual(len(keys), 1)
            with self.assertRaises(ArtifactNotFound): read_project_artifact(project=self.project, key=keys[0])
            self.assertFalse(collection.execute_competitor_page_dates_collection(job.pk, fetcher=self.fetcher()))

    def test_original_source_reservation_cancel_and_natural_expiry_during_connected_send_never_request(self):
        for loss in ("actor", "configuration", "usage", "cancel", "expiry"):
            job = self.queue("connected-" + loss); reservation = job.usage
            now = [timezone.now()]; ends = now[0] + timedelta(seconds=20)
            if loss == "expiry": OrganizationTrial.objects.filter(organization=self.organization).update(started_at=ends-timedelta(days=30), ends_at=ends)
            def mutate():
                if loss == "actor": self.revoke()
                elif loss == "configuration": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)
                elif loss == "usage": UsageReservation.objects.filter(job=job).update(period_start=reservation.period_start.replace(year=reservation.period_start.year-1))
                elif loss == "cancel": cancel_job(job=job, actor=self.owner)
                else: now[0] = ends
            with patch("jobs.usage.timezone.now", side_effect=lambda: now[0]):
                collection.execute_competitor_page_dates_collection(job.pk, fetcher=self.fetcher(boundary="connected", mutate=mutate))
            job.refresh_from_db(); self.assertEqual(job.status, "cancelled", loss)
            self.assertEqual(job.usage.actual_units, 1); self.assertFalse(job.output)
            self.assertTrue(all(conn.request.call_count == 0 for conn in self.connections))
            OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="owner")
            ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=1)

    def test_final_settled_rows_and_actual_byte_read_fence_original_actor_independent_reader_and_metadata(self):
        job = self.queue(); collection.execute_competitor_page_dates_collection(job.pk, fetcher=self.fetcher())
        job.refresh_from_db(); expected = self.read(job, actor=self.admin)
        for mutate in (self.revoke,
            lambda: OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="owner"),
            lambda: ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[self.data["origin"]]),
            lambda: JobCancellation.objects.create(job=job, requested_by=self.owner),
            lambda: Artifact.objects.filter(job=job).update(created_at=timezone.now()+timedelta(days=1)),
            lambda: UsageReservation.objects.filter(job=job).update(actual_units=2)):
            with transaction.atomic():
                def read_changed(**kwargs):
                    content = read_project_artifact(**kwargs); mutate(); return content
                with patch.object(lifecycle, "read_project_artifact", side_effect=read_changed), self.assertRaises((PermissionDenied, ValidationError)):
                    self.read(job, actor=self.admin)
                transaction.set_rollback(True)
        self.assertEqual(self.read(job, actor=self.admin), expected)
        late = self.queue("late-settlement")
        original = lifecycle.settle_usage
        def changed(**kwargs):
            result = original(**kwargs)
            if kwargs["job"].status == "succeeded": JobStep.objects.filter(job=late).update(error_category="private replacement")
            return result
        with patch.object(lifecycle, "settle_usage", side_effect=changed): collection.execute_competitor_page_dates_collection(late.pk, fetcher=self.fetcher())
        late.refresh_from_db(); self.assertEqual(late.status, "failed"); self.assertFalse(late.output); self.assertFalse(late.artifacts.exists())
        self.assertEqual(late.usage.actual_units, 1)

    def test_broker_recovery_committed_unknown_cancel_task_and_usage_never_replay(self):
        job = self.queue(); JobRun.objects.filter(pk=job.pk).update(dispatched_at=None)
        with patch("jobs.tasks.execute_competitor_page_dates_collection_task.apply_async", side_effect=OperationalError("Fixture broker")):
            self.assertFalse(dispatch_pending(job.pk))
        with patch("jobs.tasks.execute_competitor_page_dates_collection_task.apply_async") as task:
            self.assertTrue(dispatch_pending(job.pk)); self.assertFalse(dispatch_pending(job.pk)); task.assert_called_once()
        job.status = "running"; job.save(update_fields=["status", "updated_at"])
        JobStep.objects.create(job=job, sequence=1, name=collection.STAGE, status="running", output={"method": collection.METHOD, "state": "attempted"})
        JobRun.objects.filter(pk=job.pk).update(updated_at=timezone.now()-timedelta(seconds=120))
        with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No uncertain replay")):
            self.assertEqual(reconcile_stuck_competitor_roots(), 1); self.assertEqual(reconcile_stuck_competitor_roots(), 0)
            self.assertFalse(execute_job(job.pk))
        job.refresh_from_db(); self.assertEqual((job.error_category, job.usage.actual_units), ("request_outcome_unknown", 1))
        with self.assertRaises(ValidationError): retry_job(job=job, actor=self.owner, idempotency_key="retry")
        UsageReservation.objects.filter(job=job).update(state="reserved", actual_units=0, settled_at=None)
        self.assertEqual(reconcile_usage(), 1); job.refresh_from_db(); self.assertEqual(job.usage.actual_units, 1)
        cancelled = self.queue("cancel"); cancel_job(job=cancelled, actor=self.admin)
        self.assertFalse(collection.execute_competitor_page_dates_collection(cancelled.pk, fetcher=self.fetcher()))
        cancelled.refresh_from_db(); self.assertEqual(cancelled.usage.actual_units, 0)
        from .tasks import execute_competitor_page_dates_collection_task
        with patch.object(collection, "execute_competitor_page_dates_collection", return_value=False) as handler:
            self.assertFalse(execute_competitor_page_dates_collection_task.run(job.pk)); handler.assert_called_once_with(job.pk)
        self.assertEqual(execute_competitor_page_dates_collection_task.max_retries, 0)

    def test_last_unchanged_metadata_after_actual_private_read_fences_capture_and_independent_delivery(self):
        from contextlib import nullcontext
        for phase in ("delivery", "capture"):
            losses = ("actor", "configuration", "cancel", "organization", "expiry") + (("caller",) if phase == "delivery" else ())
            for loss in losses:
                with self.subTest(phase=phase, loss=loss):
                    job = self.queue("last-" + phase + "-" + loss)
                    if phase == "delivery": collection.execute_competitor_page_dates_collection(job.pk, fetcher=self.fetcher())
                    job.refresh_from_db()
                    actual_now = timezone.now
                    now = [None]; ends = actual_now() + timedelta(seconds=20)
                    OrganizationTrial.objects.filter(organization=self.organization).update(started_at=ends-timedelta(days=30), ends_at=ends)
                    original, reader = lifecycle._read_metadata, lifecycle.read_competitor_observation
                    calls, read_done, injected = [0], [False], [False]
                    def actual_reader(**kwargs):
                        result = reader(**kwargs); read_done[0] = True; return result
                    def changed(job_id):
                        result = original(job_id); calls[0] += 1
                        if not injected[0] and (calls[0] == 2 if phase == "delivery" else read_done[0]):
                            self.assertEqual(result, original(job_id))
                            injected[0] = True
                            if loss == "actor": self.revoke()
                            elif loss == "caller": OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="owner")
                            elif loss == "configuration": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[self.data["origin"]])
                            elif loss == "cancel": JobCancellation.objects.create(job=job, requested_by=self.owner)
                            elif loss == "organization": Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True)
                            else: now[0] = ends
                        return result
                    with (transaction.atomic() if phase == "delivery" else nullcontext()), patch.object(lifecycle, "_read_metadata", side_effect=changed), patch.object(lifecycle, "read_competitor_observation", side_effect=actual_reader), patch("jobs.usage.timezone.now", side_effect=lambda: now[0] or actual_now()):
                        if phase == "delivery":
                            with self.assertRaises((PermissionDenied, ValidationError, UsageLimitError)): self.read(job, actor=self.admin)
                            transaction.set_rollback(True)
                        else:
                            collection.execute_competitor_page_dates_collection(job.pk, fetcher=self.fetcher())
                            job.refresh_from_db(); self.assertEqual(job.status, "cancelled" if loss == "expiry" else "failed")
                            self.assertFalse(job.output); self.assertFalse(job.artifacts.exists())
                            self.assertEqual(job.usage.actual_units, 1)
                    self.assertTrue(injected[0])

    def test_two_connection_queue_once_and_live_advisory_recovery_cannot_repeat_original_attempt(self):
        barrier = Barrier(2)
        def queue():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return collection.queue_competitor_page_dates_collection(project=self.project, actor=self.owner,
                    data=self.data, idempotency_key="concurrent").pk
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool: ids = list(pool.map(lambda _: queue(), range(2)))
        self.assertEqual(ids[0], ids[1]); job = JobRun.objects.get(pk=ids[0])
        started, release = Event(), Event()
        def wait():
            started.set()
            if not release.wait(timeout=15): raise AssertionError("Duplicate did not release")
        fetcher = self.fetcher(boundary="completion", mutate=wait)
        def execute():
            close_old_connections()
            try: return collection.execute_competitor_page_dates_collection(job.pk, fetcher=fetcher)
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(execute)
            try:
                self.assertTrue(started.wait(timeout=15))
                JobRun.objects.filter(pk=job.pk).update(updated_at=timezone.now()-timedelta(seconds=120))
                self.assertEqual(reconcile_stuck_competitor_roots(), 0)
                self.assertFalse(collection.execute_competitor_page_dates_collection(job.pk, fetcher=fetcher))
            finally: release.set()
            self.assertTrue(future.result(timeout=20))
        job.refresh_from_db(); self.assertEqual(job.status, "succeeded")
        self.assertTrue(all(conn.request.call_count == 1 for conn in self.connections))

    def test_genuine_customer_historical_bounded_stored_sequential_retention_and_child_first_erasure(self):
        from tenancy.customer_export import complete_bounded_customer_archive
        from tenancy.customer_inventory import CUSTOMER
        from tenancy.customer_snapshot import reserve_bounded_customer_snapshot, capture_reserved_customer_snapshot, private_snapshot_part
        from tenancy.customer_source_parts import capture_source_stage
        from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        job = self.queue(); collection.execute_competitor_page_dates_collection(job.pk, fetcher=self.fetcher())
        job.refresh_from_db(); artifact = job.artifacts.get()
        content = read_project_artifact(project=self.project, key=artifact.key)
        with ZipFile(io.BytesIO(complete_bounded_customer_archive(organization=self.organization, actor=self.owner))) as archive:
            row = next(row for row in json.loads(archive.read("records/jobs/JobRun.json")) if row["id"] == job.pk)
            self.assertEqual(row["output"], job.output)
            self.assertEqual(row["scope"], "historical_selected_static_article_date_declarations_not_validated_publication_change_age_freshness_or_current_use_permission")
            self.assertIn(content, [archive.read(name) for name in archive.namelist()])
        bounded = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner, request_key="a"*32)
        self.assertTrue(capture_reserved_customer_snapshot(bounded.pk))
        retained, _ = private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=bounded.pk, position=0)
        ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[])
        with self.assertRaises((PermissionDenied, ValidationError)): self.read(job)
        self.assertEqual(private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=bounded.pk, position=0)[0], retained)
        sequential = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner, request_key="b"*32, format="source-parts-v2")
        for _ in range(len(CUSTOMER)*2+10):
            sequential.refresh_from_db()
            if sequential.state != sequential.State.PREPARING: break
            self.assertTrue(capture_source_stage(sequential.pk, sequential.progress.get("step", 0)))
        sequential.refresh_from_db(); self.assertEqual(sequential.state, sequential.State.READY)
        part = sequential.parts.filter(source__model="jobs.JobRun").first()
        data, _ = private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=sequential.pk, position=part.position)
        with ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(next(row for row in json.loads(archive.read("data")) if row["id"] == job.pk)["output"], job.output)
        now = timezone.now()
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now-timedelta(days=121), ends_at=now-timedelta(days=91))
        with self.assertRaises(PermissionDenied): private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=bounded.pk, position=0)
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=now)
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.organization))
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(JobRun.objects.filter(pk=job.pk).exists()); self.assertFalse(Artifact.objects.filter(pk=artifact.pk).exists())

    def test_actual_date_jobs_are_not_any_original_pair_or_root_heading_ai_source_model_authority(self):
        from .competitor_comparison import compare_competitor_roots
        from .competitor_page_comparison import compare_competitor_pages
        from .competitor_schema_comparison import compare_competitor_schema_roots
        from .competitor_links_comparison import compare_competitor_links_roots
        from .competitor_headings_comparison import compare_competitor_page_headings
        from .competitor_destinations_comparison import compare_competitor_page_destinations
        from .competitor_headings_synthesis import read_competitor_headings_synthesis_source
        from .competitor_headings_synthesis_selection import selection_snapshot as heading_selection
        from .competitor_synthesis import read_competitor_synthesis_source
        from .competitor_synthesis_job import selection_snapshot
        before = self.queue("closed-before")
        after = self.queue("closed-after")
        for job in (before, after):
            self.assertTrue(collection.execute_competitor_page_dates_collection(job.pk, fetcher=self.fetcher()))
        pair = dict(project=self.project, actor=self.owner, previous_job_id=before.pk, current_job_id=after.pk)
        with patch.object(lifecycle, "read_project_artifact", side_effect=AssertionError("No other-family artifact")):
            for compare in (compare_competitor_roots, compare_competitor_pages, compare_competitor_schema_roots, compare_competitor_links_roots, compare_competitor_page_headings, compare_competitor_page_destinations):
                with self.subTest(compare=compare.__name__), self.assertRaises(PermissionDenied): compare(**pair)
            with self.assertRaises(PermissionDenied): read_competitor_synthesis_source(**pair, ai_processing_permission=True)
            with self.assertRaises(PermissionDenied): read_competitor_headings_synthesis_source(**pair, ai_processing_permission=True)
            with self.assertRaises(PermissionDenied):
                selection_snapshot(self.project, self.owner, dict(previous_job_id=before.pk, current_job_id=after.pk,
                    ai_processing_permission=True, model_id=1, account_id=1, max_output_tokens=128,
                    max_cost_usd="1", allow_free=False))
            with self.assertRaises(PermissionDenied):
                heading_selection(self.project, self.owner, dict(previous_job_id=before.pk, current_job_id=after.pk,
                    ai_processing_permission=True, model_id=1, account_id=1, max_output_tokens=128,
                    max_cost_usd="1", allow_free=False))
