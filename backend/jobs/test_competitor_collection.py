from tenancy.customer_artifact_barrier import project_artifact_barrier
import io
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import timedelta
from threading import Barrier, Event
from unittest.mock import patch
from zipfile import ZipFile

from allauth.account.models import EmailAddress
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from kombu.exceptions import OperationalError

from config.artifacts import ArtifactNotFound
from config.test_foundations import TEST_STORAGES
from tenancy.artifacts import delete_project_artifact, read_project_artifact, save_project_artifact
from tenancy.models import Organization, OrganizationMembership, OrganizationTrial, ProjectConfiguration
from . import competitor_collection as collection
from . import test_competitor_source as source_fixtures
from . import test_passive_resource_transport as transport_fixtures
from .crawling import CrawlScope, SafeFetcher
from .models import Artifact, CrawlRun, Finding, JobCancellation, JobRun, JobStep, UsageReservation
from .recovery import reconcile_stuck_competitor_roots
from .services import cancel_job, dispatch_pending, queue_job, retry_job
from .usage import UsageLimitError, reconcile_usage


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}))
class CompetitorCollectionTests(TransactionTestCase):
    transport = transport_fixtures.PassiveResourceTransportTests.transport

    def setUp(self):
        dispatch = patch("celery.app.task.Task.apply_async")
        dispatch.start(); self.addCleanup(dispatch.stop)
        source_fixtures.CompetitorSourceTests.setUp(self)
        self.data = {"origin": source_fixtures.COMPETITOR, "collection_permission": True,
            "use_permission": True, "storage_permission": True}

    def queue(self, key="competitor-request", **changes):
        with patch("jobs.tasks.execute_competitor_collection_task.apply_async") as task:
            job = collection.queue_competitor_collection(**{**dict(project=self.project, actor=self.owner,
                data=self.data, idempotency_key=key), **changes})
        self.dispatch = task
        return job

    def fetcher(self, *, boundary=None, mutate=None, robots=b"User-agent: *\nDisallow:\n", body=None):
        documents = []
        for body, kind in ((robots, "text/plain"),
            (body if body is not None else b'<title>Public fixture</title><h1>Title</h1><p>private-contact@example.invalid</p>', "text/html; charset=utf-8")):
            _, conn, response, *_ = self.transport(body, fields=(f"Content-Length: {len(body)}\r\nContent-Type: {kind}\r\n"
                "Set-Cookie: private=secret\r\n").encode())
            documents.append(conn)
        self.connections = []
        def factory(*args):
            conn = documents[len(self.connections)]
            self.connections.append(conn)
            if boundary == "connected": conn.connect.side_effect = mutate
            if boundary == "completion":
                response = conn.getresponse.return_value
                conn.getresponse.side_effect = lambda: (mutate(), response)[1]
            return conn
        def resolver(*args):
            if boundary == "dns": mutate()
            return ["93.184.216.34"]
        return SafeFetcher(CrawlScope(frozenset({"competitor.example.invalid"}), kind="competitor"),
            resolver=resolver, connection_factory=factory, max_redirects=0, timeout=8, max_bytes=131072)

    def read(self, job, *, actor=None):
        return collection.read_competitor_observation(project=self.project, actor=actor or self.owner, job_id=job.pk)

    def revoke(self):
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")

    def test_genuine_once_only_protected_original_private_evidence_and_independent_admin_reader(self):
        job = self.queue()
        self.dispatch.assert_called_once_with(args=[job.pk], queue="crawl", task_id=f"job-{job.pk}", retry=False)
        self.assertEqual((job.usage.provider, job.usage.reserved_units), ("competitor_source", 1))
        self.assertEqual(self.queue().pk, job.pk); self.dispatch.assert_not_called()
        fetcher = self.fetcher()
        with patch("socket.create_connection", side_effect=AssertionError("No actual egress")):
            self.assertTrue(collection.execute_competitor_collection(job.pk, fetcher=fetcher))
        self.assertFalse(collection.execute_competitor_collection(job.pk, fetcher=fetcher))
        job.refresh_from_db(); self.assertEqual(job.status, "succeeded")
        result = self.read(job)
        self.assertEqual(self.read(job, actor=self.admin), result)  # Original actor SHA is NOT the caller's SHA.
        self.assertEqual((job.usage.actual_units, job.usage.state), (1, "settled"))
        self.assertEqual(result["collection"]["evidence"]["metadata"]["title"], "Public fixture")
        self.assertEqual(len(self.connections), 2)
        self.assertTrue(all(conn.request.call_count == 1 for conn in self.connections))
        content = read_project_artifact(project=self.project, key=job.artifacts.get().key)
        self.assertEqual(json.loads(content), result["collection"])
        for private in (b"private-contact", b"secret", b"raw_headers", b"Private customer prose", self.owner.email.encode()):
            self.assertNotIn(private, content)
        self.assertFalse(CrawlRun.objects.exists()); self.assertFalse(Finding.objects.exists())
        from .api import _job_payload
        self.assertFalse({"output", "steps", "citations", "artifacts"} & set(_job_payload(job, detailed=True)))
        job.output = {**job.output, "raw_headers": "private"}
        with self.assertRaises(ValidationError): job.save()
        step = job.steps.get(); step.output = {"raw_document": "private"}
        with self.assertRaises(ValidationError): step.save()
        artifact = job.artifacts.get(); artifact.content_type = "text/html"
        with self.assertRaises(ValidationError): artifact.save()

    def test_exact_rights_source_retry_schedule_and_commercial_queue_denials(self):
        for key in ("collection_permission", "use_permission", "storage_permission"):
            for value in (False, 1, "true", None):
                with self.subTest(key=key, value=value), self.assertRaises(ValidationError):
                    self.queue(data={**self.data, key: value})
        with self.assertRaises(PermissionDenied): self.queue(actor=self.foreign)
        with self.assertRaises((PermissionDenied, ValidationError)):
            queue_job(project=self.project, actor=self.owner, handler=collection.HANDLER, input_snapshot=self.data,
                config_snapshot={}, idempotency_key="bad-config")
        job = self.queue()
        with self.assertRaises(ValidationError):
            queue_job(project=self.project, actor=self.owner, handler=collection.HANDLER, input_snapshot=self.data,
                config_snapshot=job.config_snapshot, idempotency_key="retry", retry_of=job)
        with self.assertRaises(ValidationError):
            JobRun.objects.create(project=self.project, organization=self.organization, actor=self.owner,
                handler=collection.HANDLER, method_version=collection.METHOD, input_snapshot=self.data,
                config_snapshot=job.config_snapshot, scheduled_for=timezone.now())
        now = timezone.now()
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now - timedelta(days=31), ends_at=now - timedelta(days=1))
        with self.assertRaises(UsageLimitError): self.queue("expired")

    def test_current_dns_connected_completion_and_private_storage_loss_discard_without_replay(self):
        for boundary in ("dns", "connected", "completion", "storage"):
            job = self.queue("loss-" + boundary)
            fetcher = self.fetcher(boundary=boundary, mutate=self.revoke)
            def save_revoke(**kwargs):
                key = save_project_artifact(**kwargs); self.revoke(); return key
            with patch.object(collection, "save_project_artifact", side_effect=save_revoke if boundary == "storage" else save_project_artifact):
                self.assertTrue(collection.execute_competitor_collection(job.pk, fetcher=fetcher))
            job.refresh_from_db()
            self.assertEqual(job.status, "cancelled"); self.assertFalse(job.output); self.assertFalse(job.artifacts.exists())
            self.assertEqual(job.usage.actual_units, 1)
            if boundary in {"dns", "connected"}:
                self.assertTrue(all(conn.request.call_count == 0 for conn in self.connections))
            self.assertFalse(collection.execute_competitor_collection(job.pk, fetcher=fetcher))
            OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="owner")

    def test_broker_unknown_attempt_recovery_cancel_fixed_error_and_usage_do_not_replay(self):
        job = self.queue()
        JobRun.objects.filter(pk=job.pk).update(dispatched_at=None)
        with patch("jobs.tasks.execute_competitor_collection_task.apply_async", side_effect=OperationalError("Fixture broker")):
            self.assertFalse(dispatch_pending(job.pk))
        with patch("jobs.tasks.execute_competitor_collection_task.apply_async") as task:
            self.assertTrue(dispatch_pending(job.pk)); self.assertFalse(dispatch_pending(job.pk)); task.assert_called_once()
        fetcher = self.fetcher(robots=b"User-agent: *\nDisallow: /\n")
        collection.execute_competitor_collection(job.pk, fetcher=fetcher)
        job.refresh_from_db(); self.assertEqual((job.status, job.error_category), ("failed", "static_source_robots_denied"))
        self.assertEqual(len(self.connections), 1)
        with self.assertRaises(ValidationError): retry_job(job=job, actor=self.owner, idempotency_key="retry-failed")
        cancelled = self.queue("cancel")
        cancel_job(job=cancelled, actor=self.owner)
        self.assertFalse(collection.execute_competitor_collection(cancelled.pk, fetcher=self.fetcher()))
        cancelled.refresh_from_db(); self.assertEqual(cancelled.usage.actual_units, 0)
        unknown = self.queue("unknown")
        unknown.status = "running"; unknown.save(update_fields=["status", "updated_at"])
        JobStep.objects.create(job=unknown, sequence=1, name=collection.STAGE, status="running",
            output={"method": collection.METHOD, "state": "attempted"})
        JobRun.objects.filter(pk=unknown.pk).update(updated_at=timezone.now() - timedelta(seconds=120))
        with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No uncertain replay")):
            self.assertEqual(reconcile_stuck_competitor_roots(), 1); self.assertEqual(reconcile_stuck_competitor_roots(), 0)
            self.assertFalse(collection.execute_competitor_collection(unknown.pk))
        unknown.refresh_from_db(); self.assertEqual(unknown.error_category, "request_outcome_unknown")
        self.assertEqual(unknown.usage.actual_units, 1)
        UsageReservation.objects.filter(job=unknown).update(state="reserved", actual_units=0, settled_at=None)
        self.assertEqual(reconcile_usage(), 1); unknown.refresh_from_db(); self.assertEqual(unknown.usage.actual_units, 1)

    def test_current_original_execution_source_cancel_and_natural_trial_deadline(self):
        for boundary in ("source", "usage", "cancel", "expiry"):
            job = self.queue("current-" + boundary)
            reservation = job.usage
            now = [timezone.now()]
            ends = now[0] + timedelta(seconds=20)
            if boundary == "expiry":
                OrganizationTrial.objects.filter(organization=self.organization).update(started_at=ends - timedelta(days=30), ends_at=ends)
            def mutate():
                if boundary == "source": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)
                elif boundary == "usage": UsageReservation.objects.filter(job=job).update(period_start=reservation.period_start.replace(year=reservation.period_start.year - 1))
                elif boundary == "cancel": cancel_job(job=job, actor=self.owner)
                else: now[0] = ends
            with patch("jobs.usage.timezone.now", side_effect=lambda: now[0]):
                collection.execute_competitor_collection(job.pk, fetcher=self.fetcher(boundary="connected", mutate=mutate))
            job.refresh_from_db(); self.assertEqual(job.status, "cancelled", boundary); self.assertEqual(job.usage.actual_units, 1)
            self.assertTrue(all(conn.request.call_count == 0 for conn in self.connections))
            ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=1)

    def test_actual_private_bytes_must_survive_successful_storage_receipt_before_capture(self):
        for state in ("healthy", "corrupt", "missing"):
            with self.subTest(state=state):
                job = self.queue("actual-storage-" + state)
                keys = []
                def save(**kwargs):
                    key = save_project_artifact(**{**kwargs, **({"content": b"{}"} if state == "corrupt" else {})})
                    keys.append(key)
                    if state == "missing": delete_project_artifact(project=kwargs["project"], key=key)
                    return key
                with patch.object(collection, "save_project_artifact", side_effect=save):
                    self.assertTrue(collection.execute_competitor_collection(job.pk, fetcher=self.fetcher()))
                self.assertEqual(len(keys), 1)
                job.refresh_from_db()
                self.assertEqual(job.status, "succeeded" if state == "healthy" else "failed", job.error_category)
                self.assertEqual((job.usage.state, job.usage.actual_units), ("settled", 1))
                if state == "healthy":
                    self.assertEqual(json.loads(read_project_artifact(project=self.project, key=keys[0])), self.read(job)["collection"])
                else:
                    self.assertFalse(job.output); self.assertFalse(job.artifacts.exists()); self.assertFalse(job.citations.exists())
                    with self.assertRaises(ArtifactNotFound): read_project_artifact(project=self.project, key=keys[0])
                with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No replay")):
                    self.assertFalse(collection.execute_competitor_collection(job.pk))

    def test_post_insertion_and_settlement_loss_roll_back_private_capture(self):
        for point in ("step", "settlement", "artifact", "citation", "attempt", "usage"):
            job = self.queue("late-" + point)
            if point == "step":
                original = JobStep.save
                def save_changed(step, *args, **kwargs):
                    result = original(step, *args, **kwargs)
                    if step.job_id == job.pk and step.status == "succeeded": self.revoke()
                    return result
                context = patch.object(JobStep, "save", save_changed)
            else:
                original = collection.settle_usage
                def settle_changed(**kwargs):
                    result = original(**kwargs)
                    if kwargs["job"].status == "succeeded":
                        if point == "settlement": self.revoke()
                        elif point == "artifact": Artifact.objects.filter(job=job).update(created_at=timezone.now() + timedelta(days=1))
                        elif point == "citation": job.citations.update(source_title="untrusted replacement")
                        elif point == "attempt": JobStep.objects.filter(job=job).update(error_category="untrusted replacement")
                        else: UsageReservation.objects.filter(job=job).update(settled_at=timezone.now() + timedelta(days=1))
                    return result
                context = patch.object(collection, "settle_usage", side_effect=settle_changed)
            with context: collection.execute_competitor_collection(job.pk, fetcher=self.fetcher())
            job.refresh_from_db(); self.assertEqual(job.status, "failed")
            self.assertFalse(job.output); self.assertFalse(job.artifacts.exists()); self.assertEqual(job.usage.actual_units, 1)
            self.assertEqual(OrganizationMembership.objects.get(organization=self.organization, user=self.owner).role, "owner")

    def test_private_io_full_metadata_independent_caller_and_original_actor_loss(self):
        job = self.queue(); collection.execute_competitor_collection(job.pk, fetcher=self.fetcher())
        job.refresh_from_db(); expected = self.read(job, actor=self.admin)
        for mutate in (self.revoke,
            lambda: OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer"),
            lambda: OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="owner"),
            lambda: EmailAddress.objects.filter(user=self.admin).update(verified=False),
            lambda: ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[self.data["origin"]]),
            lambda: Artifact.objects.filter(job=job).update(created_at=timezone.now() + timedelta(days=1)),
            lambda: JobStep.objects.filter(job=job).update(created_at=timezone.now() + timedelta(days=1)),
            lambda: UsageReservation.objects.filter(job=job).update(actual_units=2)):
            with transaction.atomic():
                def read_changed(**kwargs):
                    content = read_project_artifact(**kwargs); mutate(); return content
                with patch.object(collection, "read_project_artifact", side_effect=read_changed), self.assertRaises((PermissionDenied, ValidationError)):
                    self.read(job, actor=self.admin)
                transaction.set_rollback(True)
        self.assertEqual(self.read(job, actor=self.admin), expected)
        with self.assertRaises(PermissionDenied): self.read(job, actor=self.foreign)
        with project_artifact_barrier(self.project.organization_id, shared=True):
            key = save_project_artifact(project=self.project, content=b'{"raw_document":"private"}', content_type="application/json")
        Artifact.objects.filter(job=job).update(key=key)
        with self.assertRaises(ValidationError): self.read(job)

    def test_outer_atomic_and_two_connection_queue_once(self):
        job = self.queue()
        with transaction.atomic(), self.assertRaises(ValidationError): collection.execute_competitor_collection(job.pk, fetcher=self.fetcher())
        self.assertFalse(job.steps.exists())
        barrier = Barrier(2)
        def concurrent_queue():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return collection.queue_competitor_collection(project=self.project, actor=self.owner,
                    data=self.data, idempotency_key="concurrent").pk
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: concurrent_queue(), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(JobRun.objects.filter(handler=collection.HANDLER, idempotency_key="concurrent").count(), 1)

    def test_final_unchanged_metadata_fences_current_authority_for_delivery_and_capture(self):
        for phase in ("delivery", "capture"):
            losses = ("actor", "source", "cancel", "organization", "expiry") + (("caller",) if phase == "delivery" else ())
            for loss in losses:
                Organization.objects.filter(pk=self.organization.pk).update(is_suspended=False)
                OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="owner")
                ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=1)
                with self.subTest(phase=phase, loss=loss):
                    job = self.queue("final-metadata-" + phase + "-" + loss)
                    if phase == "delivery": collection.execute_competitor_collection(job.pk, fetcher=self.fetcher())
                    job.refresh_from_db()
                    now = [timezone.now()]
                    ends = now[0] + timedelta(seconds=20)
                    OrganizationTrial.objects.filter(organization=self.organization).update(started_at=ends - timedelta(days=30), ends_at=ends)
                    original, calls = collection._read_metadata, [0]
                    def read_changed(job_id):
                        result = original(job_id)
                        calls[0] += 1
                        if calls[0] == (2 if phase == "delivery" else 1):
                            if loss == "actor": self.revoke()
                            elif loss == "caller": OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer")
                            elif loss == "source": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)
                            elif loss == "cancel": JobCancellation.objects.create(job=job, requested_by=self.owner)
                            elif loss == "organization": Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True)
                            else: now[0] = ends
                        return result
                    with (transaction.atomic() if phase == "delivery" else nullcontext()), patch.object(collection, "_read_metadata", side_effect=read_changed), patch("jobs.usage.timezone.now", side_effect=lambda: now[0]):
                        if phase == "delivery":
                            with self.assertRaises((PermissionDenied, ValidationError, UsageLimitError)): self.read(job, actor=self.admin)
                        else:
                            collection.execute_competitor_collection(job.pk, fetcher=self.fetcher())
                            job.refresh_from_db()
                            self.assertNotEqual(job.status, "succeeded")
                            self.assertFalse(job.output); self.assertFalse(job.artifacts.exists())
                        if phase == "delivery": transaction.set_rollback(True)

    def test_live_duplicate_stale_recovery_and_task_cannot_replay_locked_attempt(self):
        job = self.queue()
        started, release = Event(), Event()
        def wait():
            started.set()
            if not release.wait(timeout=15): raise AssertionError("Fixture duplicate did not release")
        fetcher = self.fetcher(boundary="completion", mutate=wait)
        def execute():
            close_old_connections()
            try: return collection.execute_competitor_collection(job.pk, fetcher=fetcher)
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(execute)
            try:
                self.assertTrue(started.wait(timeout=15))
                JobRun.objects.filter(pk=job.pk).update(updated_at=timezone.now() - timedelta(seconds=120))
                self.assertEqual(reconcile_stuck_competitor_roots(), 0)
                self.assertFalse(collection.execute_competitor_collection(job.pk, fetcher=fetcher))
            finally: release.set()
            self.assertTrue(future.result(timeout=20))
        job.refresh_from_db(); self.assertEqual(job.status, "succeeded")
        self.assertTrue(all(conn.request.call_count == 1 for conn in self.connections))
        from .tasks import execute_competitor_collection_task
        with patch.object(collection, "execute_competitor_collection", return_value=False) as handler:
            self.assertFalse(execute_competitor_collection_task.run(job.pk)); handler.assert_called_once_with(job.pk)
        self.assertEqual(execute_competitor_collection_task.max_retries, 0)

    def test_genuine_customer_bounded_stored_sequential_export_retention_and_child_first_erasure(self):
        from tenancy.customer_export import complete_bounded_customer_archive
        from tenancy.customer_inventory import CUSTOMER
        from tenancy.customer_snapshot import reserve_bounded_customer_snapshot, capture_reserved_customer_snapshot, private_snapshot_part
        from tenancy.customer_source_parts import capture_source_stage
        from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        job = self.queue(); collection.execute_competitor_collection(job.pk, fetcher=self.fetcher())
        job.refresh_from_db(); artifact = job.artifacts.get()
        content = read_project_artifact(project=self.project, key=artifact.key)
        with ZipFile(io.BytesIO(complete_bounded_customer_archive(organization=self.organization, actor=self.owner))) as archive:
            row = next(row for row in json.loads(archive.read("records/jobs/JobRun.json")) if row["id"] == job.pk)
            self.assertEqual(row["output"], job.output)
            self.assertEqual(row["scope"], "historical_selected_static_root_not_current_use_permission_or_whole_site_comparison")
            self.assertIn(content, [archive.read(name) for name in archive.namelist()])
        bounded = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner, request_key="a" * 32)
        self.assertTrue(capture_reserved_customer_snapshot(bounded.pk))
        retained, _ = private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=bounded.pk, position=0)
        ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[])
        with self.assertRaises((PermissionDenied, ValidationError)): self.read(job)
        self.assertEqual(private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=bounded.pk, position=0)[0], retained)
        sequential = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner,
            request_key="b" * 32, format="source-parts-v2")
        for _ in range(len(CUSTOMER) * 2 + 10):
            sequential.refresh_from_db()
            if sequential.state != sequential.State.PREPARING: break
            self.assertTrue(capture_source_stage(sequential.pk, sequential.progress.get("step", 0)))
        sequential.refresh_from_db(); self.assertEqual(sequential.state, sequential.State.READY)
        part = sequential.parts.filter(source__model="jobs.JobRun").first()
        data, _ = private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=sequential.pk, position=part.position)
        with ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(next(row for row in json.loads(archive.read("data")) if row["id"] == job.pk)["output"], job.output)
        now = timezone.now()
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now - timedelta(days=121), ends_at=now - timedelta(days=91))
        with self.assertRaises(PermissionDenied): private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=bounded.pk, position=0)
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=now)
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.organization))
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(JobRun.objects.filter(pk=job.pk).exists()); self.assertFalse(Artifact.objects.filter(pk=artifact.pk).exists())
