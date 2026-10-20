from tenancy.customer_artifact_barrier import project_artifact_barrier
import http.client
import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event
from unittest.mock import Mock, patch
from zipfile import ZipFile

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from kombu.exceptions import OperationalError

from config.test_foundations import TEST_STORAGES
from tenancy.artifacts import read_project_artifact, save_project_artifact
from tenancy.models import Organization, OrganizationMembership, OrganizationTrial, ProjectOriginVerification
from . import passive_header_collection as collection
from . import test_passive_header_source as source_fixtures
from . import test_security as verification_fixtures
from .crawling import CrawlScope, SafeFetcher
from .models import Artifact, JobRun, JobStatus, JobStep, SourceCitation, UsageReservation
from .recovery import reconcile_stuck_passive_headers
from .services import cancel_job, dispatch_pending, queue_job, retry_job
from .usage import UsageLimitError, reconcile_usage


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}))
class PassiveHeaderCollectionTests(TransactionTestCase):
    verified = source_fixtures.PassiveHeaderSourceTests.verified

    def setUp(self):
        dispatch = patch("celery.app.task.Task.apply_async")
        dispatch.start(); self.addCleanup(dispatch.stop)
        verification_fixtures.OriginVerificationTests.setUp(self)
        self.verification = self.verified()
        self.data = {"url": self.project.canonical_origin + "/", "observations": ["response_headers"], "collection_permission": True}

    def queue(self, key="header-request", **changes):
        with patch("jobs.tasks.execute_passive_header_collection_task.apply_async") as task:
            job = collection.queue_passive_header_collection(**{**dict(project=self.project, actor=self.owner,
                data=self.data, idempotency_key=key), **changes})
        self.dispatch = task
        return job

    def transport(self, *, wire=None, on_dns=None, on_connect=None, on_response=None):
        wire = wire or (b"HTTP/1.1 200 OK\r\nSet-Cookie: private=secret; Secure; HttpOnly\r\n"
            b"Set-Cookie: second=secret\r\nContent-Security-Policy: default-src 'nonce-private'\r\n\r\nprivate body")
        sock = Mock(); sock.makefile.return_value = io.BytesIO(wire)
        response = http.client.HTTPResponse(sock); response.begin(); self.addCleanup(response.close)
        response.read = Mock(side_effect=AssertionError("No body read"))
        self.connection = Mock()
        self.connection.getresponse.side_effect = lambda: (on_response() if on_response else None, response)[1]
        self.connection.connect.side_effect = on_connect
        def resolver(*args):
            if on_dns: on_dns()
            return ["93.184.216.34"]
        return SafeFetcher(CrawlScope(frozenset({"security.example.com"})), resolver=resolver,
            connection_factory=lambda *args: self.connection)

    def read(self, job):
        return collection.read_passive_header_observation(project=self.project, actor=self.owner, job_id=job.pk)

    def revoke(self):
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member")

    def test_genuine_once_only_minimized_private_response_and_original_step_citation_usage(self):
        job = self.queue()
        self.dispatch.assert_called_once_with(args=[job.pk], queue="audit", task_id=f"job-{job.pk}", retry=False)
        self.assertEqual((job.usage.provider, job.usage.reserved_units), ("passive_security", 1))
        self.assertEqual(self.queue().pk, job.pk); self.dispatch.assert_not_called()
        fetcher = self.transport()
        with patch("socket.create_connection", side_effect=AssertionError("No actual egress")):
            self.assertTrue(collection.execute_passive_header_collection(job.pk, fetcher=fetcher))
        self.assertFalse(collection.execute_passive_header_collection(job.pk, fetcher=fetcher))
        self.connection.request.assert_called_once()
        job.refresh_from_db(); self.assertEqual(job.status, JobStatus.SUCCEEDED)
        result = self.read(job)
        self.assertEqual(result["collection"]["evidence"]["cookies"]["observed_fields"], 2)
        self.assertEqual((job.usage.actual_units, job.usage.state), (1, "settled"))
        content = read_project_artifact(project=self.project, key=job.artifacts.get().key)
        self.assertEqual(json.loads(content), result["collection"])
        for private in (b"secret", b"nonce-private", b"private body", self.challenge.encode()): self.assertNotIn(private, content)
        from .api import _job_payload
        self.assertFalse({"output", "steps", "citations", "artifacts"} & set(_job_payload(job, detailed=True)))
        job.output = {**job.output, "raw_headers": "private"}
        with self.assertRaises(ValidationError): job.save()
        step = job.steps.get(); step.output = {"raw_cookie": "private"}
        with self.assertRaises(ValidationError): step.save()

    def test_exact_permission_source_snapshot_retry_schedule_and_commercial_queue_denials(self):
        for changes in ({"collection_permission": False}, {"observations": ["tls"]}, {"url": "http://security.example.com/"}):
            with self.assertRaises(ValidationError): self.queue(data={**self.data, **changes})
        with self.assertRaises(PermissionDenied): self.queue(actor=self.member)
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
        start = timezone.now() - timedelta(days=31)
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=start, ends_at=start + timedelta(days=30))
        with self.assertRaises(UsageLimitError): self.queue("expired")

    def test_dns_connected_completion_and_private_write_loss_discard_evidence_and_do_not_replay(self):
        for boundary in ("dns", "connected", "completion", "storage"):
            with self.subTest(boundary=boundary):
                job = self.queue("loss-" + boundary)
                fetcher = self.transport(**{key: self.revoke for key, value in
                    (("on_dns", "dns"), ("on_connect", "connected"), ("on_response", "completion")) if value == boundary})
                def save_revoke(**kwargs):
                    key = save_project_artifact(**kwargs); self.revoke(); return key
                with patch.object(collection, "save_project_artifact", side_effect=save_revoke if boundary == "storage" else save_project_artifact):
                    self.assertTrue(collection.execute_passive_header_collection(job.pk, fetcher=fetcher))
                job.refresh_from_db(); self.assertEqual(job.status, JobStatus.CANCELLED)
                self.assertEqual(job.output, {}); self.assertFalse(job.artifacts.exists())
                self.assertEqual(job.usage.actual_units, 1)
                if boundary in {"dns", "connected"}: self.connection.request.assert_not_called()
                else: self.connection.request.assert_called_once()
                self.assertFalse(collection.execute_passive_header_collection(job.pk, fetcher=fetcher))
                OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="owner")

    def test_dispatch_recovery_cancel_expiry_and_unrecognized_failure_are_not_replayed(self):
        job = self.queue()
        JobRun.objects.filter(pk=job.pk).update(dispatched_at=None)
        with patch("jobs.tasks.execute_passive_header_collection_task.apply_async", side_effect=OperationalError("Fixture broker")):
            self.assertFalse(dispatch_pending(job.pk))
        with patch("jobs.tasks.execute_passive_header_collection_task.apply_async") as task:
            self.assertTrue(dispatch_pending(job.pk)); self.assertFalse(dispatch_pending(job.pk)); task.assert_called_once()
        cancelled = self.queue("cancel")
        cancel_job(job=cancelled, actor=self.owner)
        self.assertFalse(collection.execute_passive_header_collection(cancelled.pk, fetcher=self.transport()))
        self.connection.request.assert_not_called(); cancelled.refresh_from_db(); self.assertEqual(cancelled.usage.actual_units, 0)
        fetcher = self.transport(wire=b"HTTP/1.1 200 OK\r\nBad Name: private\r\n\r\n")
        self.assertTrue(collection.execute_passive_header_collection(job.pk, fetcher=fetcher))
        job.refresh_from_db(); self.assertEqual(job.error_category, "response_headers_unavailable")
        with self.assertRaises(ValidationError): retry_job(job=job, actor=self.owner, idempotency_key="retry-failed")
        unknown = self.queue("unknown")
        unknown.status = JobStatus.RUNNING; unknown.save(update_fields=["status", "updated_at"])
        JobStep.objects.create(job=unknown, sequence=1, name=collection.STAGE, status="running",
            output={"method": collection.METHOD, "state": "attempted"})
        JobRun.objects.filter(pk=unknown.pk).update(updated_at=timezone.now() - timedelta(seconds=120))
        with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("Unknown cannot replay")):
            self.assertEqual(reconcile_stuck_passive_headers(), 1); self.assertEqual(reconcile_stuck_passive_headers(), 0)
            self.assertFalse(collection.execute_passive_header_collection(unknown.pk))
        unknown.refresh_from_db(); self.assertEqual(unknown.error_category, "request_outcome_unknown")
        self.assertEqual(unknown.usage.actual_units, 1)
        UsageReservation.objects.filter(job=unknown).update(state="reserved", actual_units=0, settled_at=None)
        self.assertEqual(reconcile_usage(), 1); unknown.refresh_from_db(); self.assertEqual(unknown.usage.actual_units, 1)

    def test_private_read_io_hidden_metadata_and_current_caller_loss_fail_closed(self):
        job = self.queue(); collection.execute_passive_header_collection(job.pk, fetcher=self.transport())
        job.refresh_from_db(); expected = self.read(job)
        for mutate in (self.revoke, lambda: ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(challenge_digest="a" * 64),
            lambda: Artifact.objects.filter(job=job).update(created_at=timezone.now() + timedelta(days=1)),
            lambda: JobStep.objects.filter(job=job).update(created_at=timezone.now() + timedelta(days=1))):
            with transaction.atomic():
                def read_changed(**kwargs):
                    body = read_project_artifact(**kwargs); mutate(); return body
                with patch.object(collection, "read_project_artifact", side_effect=read_changed), self.assertRaises((PermissionDenied, ValidationError)):
                    self.read(job)
                transaction.set_rollback(True)
        self.assertEqual(self.read(job), expected)
        artifact = job.artifacts.get()
        with project_artifact_barrier(self.project.organization_id, shared=True):
            key = save_project_artifact(project=self.project, content=b'{"raw_cookie":"private"}', content_type="application/json")
        Artifact.objects.filter(pk=artifact.pk).update(key=key)
        with self.assertRaises(ValidationError): self.read(job)

    def test_outer_transaction_cannot_rollback_an_attempt_and_two_connections_queue_once(self):
        job = self.queue()
        with transaction.atomic(), self.assertRaises(ValidationError): collection.execute_passive_header_collection(job.pk, fetcher=self.transport())
        self.connection.request.assert_not_called(); self.assertFalse(job.steps.exists())
        barrier = Barrier(2)
        def concurrent_queue():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return collection.queue_passive_header_collection(project=self.project, actor=self.owner,
                    data=self.data, idempotency_key="concurrent").pk
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: concurrent_queue(), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(JobRun.objects.filter(handler=collection.HANDLER, idempotency_key="concurrent").count(), 1)

    def test_original_verification_cancellation_and_natural_trial_deadline_stop_connected_get(self):
        job = self.queue("verification-drift")
        digest = self.verification.challenge_digest
        fetcher = self.transport(on_dns=lambda: ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(challenge_digest="a" * 64))
        collection.execute_passive_header_collection(job.pk, fetcher=fetcher)
        self.connection.request.assert_not_called(); job.refresh_from_db(); self.assertEqual(job.status, "cancelled")
        ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(challenge_digest=digest)
        cancelled = self.queue("inflight-cancel")
        collection.execute_passive_header_collection(cancelled.pk, fetcher=self.transport(
            on_connect=lambda: cancel_job(job=cancelled, actor=self.owner)))
        self.connection.request.assert_not_called(); cancelled.refresh_from_db(); self.assertEqual(cancelled.usage.actual_units, 1)
        ends = timezone.now() + timedelta(seconds=5)
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=ends - timedelta(days=30), ends_at=ends)
        expiring = self.queue("natural-expiry")
        now = [timezone.now()]
        def expire(): now[0] = ends
        with patch("jobs.usage.timezone.now", side_effect=lambda: now[0]):
            collection.execute_passive_header_collection(expiring.pk, fetcher=self.transport(on_connect=expire))
        self.connection.request.assert_not_called(); expiring.refresh_from_db()
        self.assertEqual((expiring.status, expiring.error_category, expiring.usage.actual_units), ("cancelled", "trial_unavailable", 1))

    def test_post_attempt_save_or_settlement_source_loss_rolls_back_private_capture(self):
        for point in ("step", "settlement"):
            job = self.queue("late-" + point)
            digest = self.verification.challenge_digest
            if point == "step":
                original = JobStep.save
                def save_changed(step, *args, **kwargs):
                    result = original(step, *args, **kwargs)
                    if step.job_id == job.pk and step.status == "succeeded":
                        ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(challenge_digest="a" * 64)
                    return result
                context = patch.object(JobStep, "save", save_changed)
            else:
                original = collection.settle_usage
                def settle_changed(**kwargs):
                    result = original(**kwargs)
                    if kwargs["job"].status == "succeeded":
                        ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(challenge_digest="a" * 64)
                    return result
                context = patch.object(collection, "settle_usage", side_effect=settle_changed)
            with context: collection.execute_passive_header_collection(job.pk, fetcher=self.transport())
            job.refresh_from_db(); self.assertEqual(job.status, "failed")
            self.assertFalse(job.output); self.assertFalse(job.artifacts.exists()); self.assertEqual(job.usage.actual_units, 1)
            self.assertEqual(ProjectOriginVerification.objects.get(pk=self.verification.pk).challenge_digest, digest)

    def test_unread_or_corrupted_actual_private_bytes_cannot_commit_successful_capture(self):
        job = self.queue("corrupt-private-readback")
        with patch.object(collection, "read_project_artifact", return_value=b"{}") as read:
            collection.execute_passive_header_collection(job.pk, fetcher=self.transport())
        job.refresh_from_db(); job.usage.refresh_from_db()
        self.assertEqual((job.status, job.output, job.artifacts.count(), job.citations.count(), job.usage.actual_units),
            ("failed", {}, 0, 0, 1))
        read.assert_called_once(); self.connection.request.assert_called_once()
        self.assertFalse(collection.execute_passive_header_collection(job.pk, fetcher=self.transport()))

    def test_natural_expiry_during_final_source_equality_withholds_current_private_bytes(self):
        job = self.queue("slow-source-delivery")
        collection.execute_passive_header_collection(job.pk, fetcher=self.transport())
        job.refresh_from_db(); now = [timezone.now()]; end = self.organization.trial.ends_at
        selection = collection.selection_snapshot; calls = 0
        def slow_selection(*args, **kwargs):
            nonlocal calls
            value = selection(*args, **kwargs); calls += 1
            # Two selections per source pass; expire only after the last original source equality.
            if calls == 4: now[0] = end
            return value
        with patch("jobs.usage.timezone.now", side_effect=lambda: now[0]), patch.object(collection, "selection_snapshot", slow_selection):
            with self.assertRaises((PermissionDenied, ValidationError)): self.read(job)
        self.assertEqual(calls, 4)

    def test_natural_expiry_during_last_private_metadata_read_withholds_delivery(self):
        job = self.queue("slow-metadata-delivery")
        collection.execute_passive_header_collection(job.pk, fetcher=self.transport())
        job.refresh_from_db(); now = [timezone.now()]; end = self.organization.trial.ends_at
        metadata = collection._read_metadata; calls = 0
        def slow_metadata(*args):
            nonlocal calls
            value = metadata(*args); calls += 1
            if calls == 2: now[0] = end
            return value
        with patch("jobs.usage.timezone.now", side_effect=lambda: now[0]), patch.object(collection, "_read_metadata", slow_metadata):
            with self.assertRaises((PermissionDenied, ValidationError)): self.read(job)
        self.assertEqual(calls, 2)

    def test_plausible_original_attempt_and_dispatch_drift_stop_connected_get(self):
        for boundary in ("attempt", "dispatch"):
            with self.subTest(boundary=boundary):
                job = self.queue("original-" + boundary)
                def changed():
                    if boundary == "attempt":
                        step = job.steps.get()
                        JobStep.objects.filter(pk=step.pk).update(created_at=step.created_at - timedelta(microseconds=1))
                    else:
                        current = JobRun.objects.get(pk=job.pk)
                        JobRun.objects.filter(pk=job.pk).update(dispatched_at=current.dispatched_at + timedelta(microseconds=1))
                collection.execute_passive_header_collection(job.pk, fetcher=self.transport(on_connect=changed))
                self.connection.request.assert_not_called()
                job.refresh_from_db()
                self.assertEqual((job.status, job.output, job.artifacts.count(), job.usage.actual_units), ("cancelled", {}, 0, 1))

    def test_plausible_intended_inserted_and_settled_rows_cannot_rebind_success(self):
        for model in (Artifact, SourceCitation, JobStep, UsageReservation):
            with self.subTest(model=model.__name__):
                job = self.queue("intended-" + model.__name__)
                save = model.save
                def changed(row, *args, **kwargs):
                    value = save(row, *args, **kwargs)
                    terminal = model is not JobStep or row.status == "succeeded"
                    settled = model is not UsageReservation or row.state == "settled"
                    if row.job_id == job.pk and terminal and settled:
                        field = "settled_at" if model is UsageReservation else "created_at"
                        model.objects.filter(pk=row.pk).update(**{field: getattr(row, field) - timedelta(microseconds=1)})
                    return value
                with patch.object(model, "save", changed):
                    collection.execute_passive_header_collection(job.pk, fetcher=self.transport())
                job.refresh_from_db()
                self.assertEqual((job.status, job.output, job.artifacts.count(), job.citations.count(), job.usage.actual_units),
                    ("failed", {}, 0, 0, 1))
                self.connection.request.assert_called_once()

    def test_real_minimized_job_bounded_stored_sequential_export_retention_and_scoped_erasure(self):
        from tenancy.customer_export import complete_bounded_customer_archive
        from tenancy.customer_inventory import CUSTOMER
        from tenancy.customer_snapshot import reserve_bounded_customer_snapshot, capture_reserved_customer_snapshot, private_snapshot_part
        from tenancy.customer_source_parts import capture_source_stage
        from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        from tenancy.services import revoke_origin_verification
        job = self.queue(); collection.execute_passive_header_collection(job.pk, fetcher=self.transport())
        job.refresh_from_db(); artifact = job.artifacts.get()
        content = read_project_artifact(project=self.project, key=artifact.key)
        # Generic record exports preserve their existing sensitive-key redaction;
        # the separately scoped private artifact contains only minimized counts.
        exported = {**job.output, "evidence": {**job.output["evidence"], "cookies": "[REDACTED]"}}
        with ZipFile(io.BytesIO(complete_bounded_customer_archive(organization=self.organization, actor=self.owner))) as archive:
            row = next(row for row in json.loads(archive.read("records/jobs/JobRun.json")) if row["id"] == job.pk)
            self.assertEqual(row["output"], exported)
            self.assertIn(content, [archive.read(name) for name in archive.namelist()])
            self.assertNotIn(b"nonce-private", json.dumps(row).encode())
        bounded = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner, request_key="a" * 32)
        self.assertTrue(capture_reserved_customer_snapshot(bounded.pk))
        retained, _ = private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=bounded.pk, position=0)
        revoke_origin_verification(verification=self.verification, user=self.owner)
        with self.assertRaises(PermissionDenied): self.read(job)
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
            self.assertEqual(next(row for row in json.loads(archive.read("data")) if row["id"] == job.pk)["output"], exported)
        now = timezone.now()
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now - timedelta(days=121), ends_at=now - timedelta(days=91))
        with self.assertRaises(PermissionDenied): private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=bounded.pk, position=0)
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=now)
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.organization))
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(JobRun.objects.filter(pk=job.pk).exists()); self.assertFalse(Artifact.objects.filter(pk=artifact.pk).exists())

    def test_live_duplicate_and_stale_recovery_cannot_replay_the_locked_attempt(self):
        job = self.queue("live-duplicate")
        started, release = Event(), Event()
        def wait_for_duplicate():
            started.set()
            if not release.wait(timeout=10): raise AssertionError("Fixture duplicate did not release transport")
        fetcher = self.transport(on_response=wait_for_duplicate)
        def execute():
            close_old_connections()
            try: return collection.execute_passive_header_collection(job.pk, fetcher=fetcher)
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(execute)
            try:
                self.assertTrue(started.wait(timeout=10))
                JobRun.objects.filter(pk=job.pk).update(updated_at=timezone.now() - timedelta(seconds=120))
                self.assertEqual(reconcile_stuck_passive_headers(), 0)
                self.assertFalse(collection.execute_passive_header_collection(job.pk, fetcher=fetcher))
            finally: release.set()
            self.assertTrue(future.result(timeout=10))
        self.connection.request.assert_called_once()
        job.refresh_from_db(); self.assertEqual(job.status, "succeeded")
        from .tasks import execute_passive_header_collection_task
        with patch.object(collection, "execute_passive_header_collection", return_value=False) as handler:
            self.assertFalse(execute_passive_header_collection_task.run(job.pk)); handler.assert_called_once_with(job.pk)
        self.assertEqual(execute_passive_header_collection_task.max_retries, 0)
