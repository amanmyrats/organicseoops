import io
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier, Event
from unittest.mock import patch
from zipfile import ZipFile

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.artifacts import read_project_artifact
from tenancy.models import Organization, OrganizationMembership, OrganizationTrial, ProjectOriginVerification
from tenancy.services import update_project, revoke_origin_verification
from . import passive_header_collection as lifecycle
from . import passive_http_redirect_collection as collection
from . import test_passive_header_collection as fixtures
from . import test_security as verification_fixtures
from .api import _job_payload
from .models import Artifact, JobRun, JobStep, SourceCitation, UsageReservation
from .recovery import reconcile_stuck_passive_http_redirects
from .services import cancel_job, dispatch_pending, execute_job, queue_job, retry_job
from .tasks import execute_passive_http_redirect_collection_task
from .usage import UsageLimitError, reconcile_usage


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json", "application/zip"}))
class PassiveHTTPRedirectCollectionTests(TransactionTestCase):
    verified = fixtures.PassiveHeaderCollectionTests.verified
    transport = fixtures.PassiveHeaderCollectionTests.transport
    WIRE = b"HTTP/1.1 301 Moved\r\nLocation: https://security.example.com/private?secret=value\r\nSet-Cookie: private=secret\r\n\r\nprivate body"

    def setUp(self):
        dispatch = patch("celery.app.task.Task.apply_async")
        dispatch.start(); self.addCleanup(dispatch.stop)
        verification_fixtures.OriginVerificationTests.setUp(self)
        self.https_origin = self.project.canonical_origin
        self.project = update_project(project=self.project, user=self.owner, canonical_origin="http://security.example.com",
            aliases=[self.https_origin])
        self.verification = self.verified()
        self.data = {"url": self.project.canonical_origin + "/public", "observations": ["http_response_location"], "collection_permission": True}

    def queue(self, key="http-redirect-request", **changes):
        with patch("jobs.tasks.execute_passive_http_redirect_collection_task.apply_async") as task:
            job = collection.queue_passive_http_redirect_collection(**{**dict(project=self.project, actor=self.owner,
                data=self.data, idempotency_key=key), **changes})
        self.dispatch = task
        return job

    def collect(self, job, **transport):
        return collection.execute_passive_http_redirect_collection(job.pk, fetcher=self.transport(wire=self.WIRE, **transport))

    def read(self, job, actor=None):
        return collection.read_passive_http_redirect_observation(project=self.project, actor=actor or self.owner, job_id=job.pk)

    def test_genuine_native_plaintext_once_only_original_full_private_rows_and_independent_reader(self):
        job = self.queue()
        self.dispatch.assert_called_once_with(args=[job.pk], queue="audit", task_id=f"job-{job.pk}", retry=False)
        self.assertEqual((job.method_version, job.usage.provider, job.usage.reserved_units), (collection.METHOD, "passive_security", 1))
        self.assertEqual(self.queue().pk, job.pk); self.dispatch.assert_not_called()
        fetcher = self.transport(wire=self.WIRE); fetch = fetcher.fetch; captured = []
        def capture(*args, **kwargs):
            self.assertIs(kwargs["observe_http_redirects"], True)
            self.assertNotIn("observe_redirects", kwargs)
            response = fetch(*args, **kwargs); captured.append(response); return response
        fetcher.fetch = capture
        with patch("socket.create_connection", side_effect=AssertionError("No actual egress")):
            self.assertTrue(collection.execute_passive_http_redirect_collection(job.pk, fetcher=fetcher))
        job.refresh_from_db(); result = self.read(job)["collection"]
        self.assertEqual((job.status, job.usage.state, job.usage.actual_units), ("succeeded", "settled", 1))
        self.assertEqual(result["observed_at"], captured[0].redirect_observation["observed_at"])
        self.assertEqual(job.citations.get().observed_at.isoformat(timespec="microseconds"), result["observed_at"])
        location = result["evidence"]["response_location"]
        self.assertEqual((location["response_status"], location["target_scheme"], location["same_origin"], location["same_hostname_default_https"]),
            (301, "https", False, True))
        self.assertIn("not_authenticated_identity_observed_https_followed_upgrade", result["interpretation"])
        content = read_project_artifact(project=self.project, key=job.artifacts.get().key)
        self.assertEqual(json.loads(content), result)
        for raw in (b"private", b"secret", b"source_digest", self.challenge.encode()): self.assertNotIn(raw, content)
        self.assertFalse(set(_job_payload(job, detailed=True)) & {"output", "steps", "citations", "artifacts"})
        self.assertFalse(collection.execute_passive_http_redirect_collection(job.pk, fetcher=fetcher)); self.connection.request.assert_called_once()
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        self.assertEqual(self.read(job, self.member)["collection"], result)
        for handler in lifecycle.PASSIVE_HANDLERS:
            if handler != collection.HANDLER:
                with self.assertRaises(PermissionDenied):
                    lifecycle.read_passive_header_observation(project=self.project, actor=self.owner, job_id=job.pk, handler=handler)
        job.output = {}; self.assertRaises(ValidationError, job.save, update_fields=["output"])

    def test_independent_http_permission_ownership_manual_models_outer_atomic_and_expired_queue(self):
        for changes in ({"collection_permission": 1}, {"observations": ["response_location"]}, {"observations": ["response_headers"]},
            {"url": self.https_origin + "/public"}):
            with self.assertRaises(ValidationError): self.queue(data={**self.data, **changes})
        with self.assertRaises(PermissionDenied): self.queue(actor=self.member)
        with self.assertRaises((PermissionDenied, ValidationError)):
            queue_job(project=self.project, actor=self.owner, handler=collection.HANDLER, input_snapshot=self.data,
                config_snapshot={}, idempotency_key="bad-config")
        with transaction.atomic():
            revoke_origin_verification(verification=self.verification, user=self.owner)
            self.verified(self.https_origin)
            with self.assertRaises(PermissionDenied): self.queue("https-only")
            transaction.set_rollback(True)
        self.verification.refresh_from_db()
        job = self.queue()
        with transaction.atomic(), self.assertRaises(ValidationError): self.collect(job)
        self.connection.request.assert_not_called(); self.assertFalse(job.steps.exists())
        with self.assertRaises(ValidationError):
            JobRun.objects.create(project=self.project, organization=self.organization, actor=self.owner, handler=collection.HANDLER,
                method_version=collection.METHOD, input_snapshot=self.data, config_snapshot=job.config_snapshot, scheduled_for=timezone.now())
        with self.assertRaises(ValidationError):
            JobStep.objects.create(job=job, sequence=2, name=collection.STAGE, status="running", output={"method": collection.METHOD, "state": "attempted"})
        start = timezone.now() - timedelta(days=31)
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=start, ends_at=start + timedelta(days=30))
        with self.assertRaises(UsageLimitError): self.queue("expired")

    def test_source_cancel_natural_expiry_at_all_original_request_boundaries_zero_or_one_charge(self):
        for boundary in ("before", "dns", "connected", "completion"):
            for loss in ("source", "cancel", "expiry"):
                with self.subTest(boundary=boundary, loss=loss):
                    job = self.queue(f"{boundary}-{loss}"); now = [timezone.now()]; end = self.organization.trial.ends_at
                    def lose():
                        if loss == "source": ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(challenge_digest="b" * 64)
                        elif loss == "cancel": cancel_job(job=job, actor=self.owner)
                        else: now[0] = end
                    options = {"on_" + name: lose for name in ("dns", "connect", "response")
                        if {"dns": "dns", "connect": "connected", "response": "completion"}[name] == boundary}
                    if boundary == "before": lose()
                    with patch("jobs.usage.timezone.now", side_effect=lambda: now[0]): self.collect(job, **options)
                    job.refresh_from_db()
                    self.assertEqual((job.status, job.output, job.artifacts.count(), job.usage.actual_units),
                        ("cancelled", {}, 0, 0 if boundary == "before" else 1))
                    if boundary != "completion": self.connection.request.assert_not_called()
                    else: self.connection.request.assert_called_once()
                    ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(challenge_digest=self.verification.challenge_digest)

    def test_original_attempt_intended_settlement_and_actual_byte_readback_fail_closed(self):
        for boundary in ("attempt", "artifact", "citation", "settlement", "bytes"):
            job = self.queue("intended-" + boundary)
            if boundary == "attempt":
                def drift():
                    step = job.steps.get()
                    JobStep.objects.filter(pk=step.pk).update(created_at=step.created_at - timedelta(microseconds=1))
                self.collect(job, on_connect=drift)
                self.connection.request.assert_not_called()
            else:
                model = {"artifact": Artifact, "citation": SourceCitation, "settlement": UsageReservation}.get(boundary)
                save = model.save if model else None
                def drift_save(row, *args, **kwargs):
                    value = save(row, *args, **kwargs)
                    if row.job_id == job.pk and (model is not UsageReservation or row.state == "settled"):
                        field = "settled_at" if model is UsageReservation else "created_at"
                        model.objects.filter(pk=row.pk).update(**{field: getattr(row, field) - timedelta(microseconds=1)})
                    return value
                context = patch.object(model, "save", drift_save) if model else patch.object(lifecycle, "read_project_artifact", return_value=b"{}")
                with context: self.collect(job)
                self.connection.request.assert_called_once()
            job.refresh_from_db()
            self.assertIn(job.status, {"cancelled", "failed"})
            self.assertEqual((job.output, job.artifacts.count(), job.citations.count(), job.usage.actual_units), ({}, 0, 0, 1))
            self.assertFalse(collection.execute_passive_http_redirect_collection(job.pk))

    def test_natural_expiry_inside_connected_current_source_read_stops_http_get(self):
        job = self.queue("slow-connected-source"); now = [timezone.now()]; connected = False
        end = self.organization.trial.ends_at; validate = lifecycle.validate_job
        def connect():
            nonlocal connected
            connected = True
        def slow_source(*args, **kwargs):
            result = validate(*args, **kwargs)
            if connected and kwargs.get("current"): now[0] = end
            return result
        with patch.object(lifecycle, "validate_job", slow_source), patch("jobs.usage.timezone.now", side_effect=lambda: now[0]):
            self.collect(job, on_connect=connect)
        self.connection.request.assert_not_called(); job.refresh_from_db()
        self.assertEqual((job.status, job.error_category, job.output, job.usage.actual_units), ("cancelled", "trial_unavailable", {}, 1))

    def test_last_source_metadata_and_private_read_recheck_independent_authority_and_natural_expiry(self):
        job = self.queue(); self.collect(job); job.refresh_from_db()
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        expected = self.read(job, self.member)
        for boundary in ("source", "metadata", "bytes"):
            with transaction.atomic():
                now = [timezone.now()]; end = self.organization.trial.ends_at; calls = 0
                original = {"source": lifecycle.selection_snapshot, "metadata": lifecycle._read_metadata, "bytes": lifecycle.read_project_artifact}[boundary]
                def slow(*args, **kwargs):
                    nonlocal calls
                    result = original(*args, **kwargs); calls += 1
                    if boundary == "source" and calls == 4 or boundary == "metadata" and calls == 2: now[0] = end
                    elif boundary == "bytes": OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="viewer")
                    return result
                attribute = {"source": "selection_snapshot", "metadata": "_read_metadata", "bytes": "read_project_artifact"}[boundary]
                with patch.object(lifecycle, attribute, slow), patch("jobs.usage.timezone.now", side_effect=lambda: now[0]):
                    with self.assertRaises((PermissionDenied, ValidationError)): self.read(job, self.member)
                transaction.set_rollback(True)
        self.assertEqual(self.read(job, self.member), expected)

    def test_transport_unknown_broker_usage_recovery_task_wrapper_and_foreign_family_no_replay(self):
        job = self.queue("bad-fields")
        collection.execute_passive_http_redirect_collection(job.pk, fetcher=self.transport(wire=b"HTTP/1.1 301 Moved\r\nBad Name: private\r\n\r\n"))
        job.refresh_from_db(); self.assertEqual((job.status, job.error_category), ("failed", "response_headers_unavailable"))
        with self.assertRaises(ValidationError): retry_job(job=job, actor=self.owner, idempotency_key="retry")
        mixed = self.queue("mixed"); fetcher = self.transport(wire=self.WIRE); fetch = fetcher.fetch
        fetcher.fetch = lambda *args, **kwargs: replace(fetch(*args, **kwargs), header_observation={})
        collection.execute_passive_http_redirect_collection(mixed.pk, fetcher=fetcher)
        mixed.refresh_from_db(); self.assertEqual((mixed.status, mixed.output, mixed.usage.actual_units), ("failed", {}, 1))
        unknown = self.queue("unknown"); unknown.status = "running"; unknown.save(update_fields=["status", "updated_at"])
        JobStep.objects.create(job=unknown, sequence=1, name=collection.STAGE, status="running", output={"method": collection.METHOD, "state": "attempted"})
        JobRun.objects.filter(pk=unknown.pk).update(updated_at=timezone.now() - timedelta(minutes=5))
        with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No unknown replay")):
            self.assertEqual(reconcile_stuck_passive_http_redirects(), 1); self.assertEqual(reconcile_stuck_passive_http_redirects(), 0)
            self.assertFalse(collection.execute_passive_http_redirect_collection(unknown.pk))
        unknown.refresh_from_db(); self.assertEqual((unknown.error_category, unknown.usage.actual_units), ("request_outcome_unknown", 1))
        UsageReservation.objects.filter(job=unknown).update(state="reserved", actual_units=0, settled_at=None)
        self.assertEqual(reconcile_usage(), 1); unknown.usage.refresh_from_db(); self.assertEqual(unknown.usage.actual_units, 1)
        with patch.object(collection, "execute_passive_http_redirect_collection", return_value=False) as execute:
            self.assertFalse(execute_passive_http_redirect_collection_task.run(unknown.pk)); execute.assert_called_once_with(unknown.pk)
            self.assertFalse(execute_job(unknown.pk)); self.assertEqual(execute.call_count, 2)
        broker = self.queue("broker"); JobRun.objects.filter(pk=broker.pk).update(dispatched_at=None)
        with patch("jobs.tasks.execute_passive_http_redirect_collection_task.apply_async", side_effect=OSError("fixture broker")):
            self.assertFalse(dispatch_pending(broker.pk))
        with patch("jobs.tasks.execute_passive_http_redirect_collection_task.apply_async") as task:
            self.assertTrue(dispatch_pending(broker.pk)); self.assertFalse(dispatch_pending(broker.pk)); task.assert_called_once()

    def test_postgresql_duplicate_queue_and_live_advisory_recovery_do_not_repeat_http_request(self):
        barrier = Barrier(2)
        def queue():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return self.queue("concurrent").pk
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool: ids = list(pool.map(lambda _: queue(), range(2)))
        self.assertEqual(ids[0], ids[1])
        job = self.queue("active"); started, release = Event(), Event()
        def wait():
            started.set()
            if not release.wait(timeout=10): raise AssertionError("Release fixture transport")
        def execute():
            close_old_connections()
            try: return self.collect(job, on_response=wait)
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(execute)
            try:
                self.assertTrue(started.wait(timeout=10))
                JobRun.objects.filter(pk=job.pk).update(updated_at=timezone.now() - timedelta(minutes=2))
                self.assertEqual(reconcile_stuck_passive_http_redirects(), 0)
                self.assertFalse(collection.execute_passive_http_redirect_collection(job.pk))
            finally: release.set()
            self.assertTrue(future.result(timeout=10))
        self.connection.request.assert_called_once(); job.refresh_from_db(); self.assertEqual(job.status, "succeeded")

    def test_genuine_customer_stored_sequential_history_retention_and_child_first_erasure(self):
        from tenancy.customer_export import complete_bounded_customer_archive
        from tenancy.customer_inventory import CUSTOMER
        from tenancy.customer_snapshot import reserve_bounded_customer_snapshot, capture_reserved_customer_snapshot, private_snapshot_part
        from tenancy.customer_source_parts import capture_source_stage
        from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        job = self.queue(); self.collect(job); job.refresh_from_db(); artifact = job.artifacts.get()
        content = read_project_artifact(project=self.project, key=artifact.key)
        with ZipFile(io.BytesIO(complete_bounded_customer_archive(organization=self.organization, actor=self.owner))) as archive:
            row = next(row for row in json.loads(archive.read("records/jobs/JobRun.json")) if row["id"] == job.pk)
            self.assertEqual(row["output"], job.output); self.assertIn("historical_plaintext_http", row["scope"])
            self.assertIn(content, [archive.read(name) for name in archive.namelist()])
        bounded = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner, request_key="e" * 32)
        self.assertTrue(capture_reserved_customer_snapshot(bounded.pk))
        retained, _ = private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=bounded.pk, position=0)
        revoke_origin_verification(verification=self.verification, user=self.owner)
        with self.assertRaises(PermissionDenied): self.read(job)
        self.assertEqual(private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=bounded.pk, position=0)[0], retained)
        sequential = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner, request_key="f" * 32, format="source-parts-v2")
        for _ in range(len(CUSTOMER) * 2 + 10):
            sequential.refresh_from_db()
            if sequential.state != sequential.State.PREPARING: break
            self.assertTrue(capture_source_stage(sequential.pk, sequential.progress.get("step", 0)))
        sequential.refresh_from_db(); self.assertEqual(sequential.state, sequential.State.READY)
        part = sequential.parts.filter(source__model="jobs.JobRun").first()
        data, _ = private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=sequential.pk, position=part.position)
        with ZipFile(io.BytesIO(data)) as archive:
            row = next(row for row in json.loads(archive.read("data")) if row["id"] == job.pk)
            self.assertEqual(row["output"], job.output); self.assertIn("historical_plaintext_http", row["scope"])
        now = timezone.now()
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now - timedelta(days=121), ends_at=now - timedelta(days=91))
        with self.assertRaises(PermissionDenied): private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=bounded.pk, position=0)
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=now)
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.organization))
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(JobRun.objects.filter(pk=job.pk).exists()); self.assertFalse(Artifact.objects.filter(pk=artifact.pk).exists())
