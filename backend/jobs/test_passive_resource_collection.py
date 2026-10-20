import http.client
import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event
from unittest.mock import Mock, patch
from urllib.parse import urlsplit
from zipfile import ZipFile

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.artifacts import read_project_artifact
from tenancy.models import Organization, OrganizationMembership, OrganizationTrial, ProjectOriginVerification
from . import passive_header_collection as lifecycle
from . import passive_resource_collection as collection
from . import test_passive_header_collection as fixtures
from .api import _job_payload
from .crawling import CrawlScope, SafeFetcher
from .models import Artifact, JobRun, JobStatus, JobStep, UsageReservation
from .recovery import reconcile_stuck_passive_resources
from .services import cancel_job, dispatch_pending, queue_job, retry_job
from .tasks import execute_passive_resource_collection_task
from .usage import reconcile_usage


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}))
class PassiveResourceCollectionTests(TransactionTestCase):
    verified = fixtures.PassiveHeaderCollectionTests.verified

    def setUp(self):
        fixtures.PassiveHeaderCollectionTests.setUp(self)
        self.data = {"url": self.project.canonical_origin + "/public", "observations": ["static_resource_references"],
                     "collection_permission": True}

    def queue(self, key="resource-request", **changes):
        with patch("jobs.tasks.execute_passive_resource_collection_task.apply_async") as task:
            job = collection.queue_passive_resource_collection(**{**dict(project=self.project, actor=self.owner,
                data=self.data, idempotency_key=key), **changes})
        self.dispatch = task
        return job

    def transport(self, *, body=None, fields=None, on_dns=None, on_connect=None, on_body=None):
        body = b'<img src="http://private.invalid/?secret=value"><script src="https://private.invalid/"></script>' if body is None else body
        fields = fields if fields is not None else f"Content-Length: {len(body)}\r\nContent-Type: text/html; charset=utf-8\r\n".encode()
        sock = Mock(); sock.makefile.return_value = io.BytesIO(b"HTTP/1.1 200 OK\r\n" + fields + b"\r\n" + body)
        response = http.client.HTTPResponse(sock); response.begin(); self.addCleanup(response.close)
        original = response.read1
        response.read1 = lambda amount: (on_body() if on_body else None, original(amount))[1]
        self.connection = Mock()
        self.connection.getresponse.return_value = response
        self.connection.connect.side_effect = on_connect
        def resolver(*args):
            if on_dns: on_dns()
            return ["93.184.216.34"]
        return SafeFetcher(CrawlScope(frozenset({urlsplit(self.data["url"]).hostname})), resolver=resolver,
            connection_factory=lambda *args: self.connection)

    def read(self, job):
        return collection.read_passive_resource_observation(project=self.project, actor=self.owner, job_id=job.pk)

    def test_genuine_original_source_private_date_usage_once_only_and_generic_metadata(self):
        job = self.queue()
        self.dispatch.assert_called_once_with(args=[job.pk], queue="audit", task_id=f"job-{job.pk}", retry=False)
        self.assertEqual((job.method_version, job.usage.provider, job.usage.reserved_units), (collection.METHOD, "passive_security", 1))
        self.assertEqual(self.queue().pk, job.pk); self.dispatch.assert_not_called()
        fetcher = self.transport()
        with patch("socket.create_connection", side_effect=AssertionError("No real egress")):
            self.assertTrue(collection.execute_passive_resource_collection(job.pk, fetcher=fetcher))
        job.refresh_from_db(); job.usage.refresh_from_db()
        self.assertEqual((job.status, job.usage.actual_units), ("succeeded", 1))
        result = self.read(job)["collection"]
        self.assertEqual(result["observed_at"], result["evidence"]["observed_at"])
        self.assertEqual(job.citations.get().observed_at.isoformat(timespec="microseconds"), result["observed_at"])
        self.assertEqual(job.citations.get().source_url, self.data["url"])
        self.assertEqual(result["evidence"]["resource_references"]["counts"]["http_absolute"], 1)
        artifact = job.artifacts.get(); content = read_project_artifact(project=self.project, key=artifact.key)
        self.assertEqual(json.loads(content), result); self.assertNotIn(b"private", content); self.assertNotIn(b"secret", content)
        self.assertFalse(set(_job_payload(job, detailed=True)) & {"output", "steps", "citations", "artifacts"})
        self.assertFalse(collection.execute_passive_resource_collection(job.pk, fetcher=fetcher))
        self.connection.request.assert_called_once()
        with self.assertRaises(PermissionDenied): lifecycle.read_passive_header_observation(project=self.project, actor=self.owner, job_id=job.pk)
        job.output = {}; self.assertRaises(ValidationError, job.save, update_fields=["output"])

    def test_named_permission_atomic_retry_schedule_and_model_payload_denials(self):
        for data in ({**self.data, "collection_permission": 1}, {**self.data, "observations": ["response_headers"]},
            {"origin": self.project.canonical_origin, "observations": ["certificate_dates", "negotiated_tls"], "collection_permission": True}):
            with self.assertRaises(ValidationError): self.queue(data=data)
        with self.assertRaises(PermissionDenied): self.queue(actor=self.member)
        job = self.queue(); fetcher = self.transport()
        with transaction.atomic(), self.assertRaises(ValidationError): collection.execute_passive_resource_collection(job.pk, fetcher=fetcher)
        self.connection.request.assert_not_called()
        with self.assertRaises(ValidationError):
            queue_job(project=self.project, actor=self.owner, handler=collection.HANDLER, input_snapshot=self.data,
                config_snapshot=job.config_snapshot, idempotency_key="retry", retry_of=job)
        with self.assertRaises(ValidationError):
            JobStep.objects.create(job=job, sequence=2, name=collection.STAGE, status="running", output={"method": collection.METHOD, "state": "attempted"})
        with self.assertRaises(ValidationError): Artifact.objects.create(job=job, project=self.project, key="private", content_type="text/html", size_bytes=1)
        with self.assertRaises(ValidationError): self.queue(data={**self.data, "url": "http://security.example.com/public"})

    def test_current_source_cancellation_natural_expiry_at_all_boundaries_with_exact_attempt_charge(self):
        for boundary in ("before", "dns", "connected", "body"):
            for loss in ("source", "cancel", "expiry"):
                job = self.queue(key=f"{boundary}-{loss}"); trial = self.organization.trial; original_end = trial.ends_at
                def lose():
                    if loss == "source": ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(challenge_digest="b" * 64)
                    elif loss == "cancel": cancel_job(job=job, actor=self.owner)
                    else: OrganizationTrial.objects.filter(pk=trial.pk).update(ends_at=timezone.now() - timedelta(microseconds=1))
                fetcher = self.transport(on_dns=lose if boundary == "dns" else None,
                    on_connect=lose if boundary == "connected" else None, on_body=lose if boundary == "body" else None)
                if boundary == "before": lose()
                collection.execute_passive_resource_collection(job.pk, fetcher=fetcher)
                job.refresh_from_db(); job.usage.refresh_from_db()
                self.assertEqual((job.status, job.output, job.artifacts.count(), job.usage.actual_units),
                    ("cancelled", {}, 0, 0 if boundary == "before" else 1))
                if boundary != "body": self.connection.request.assert_not_called()
                ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(challenge_digest=self.verification.challenge_digest)
                OrganizationTrial.objects.filter(pk=trial.pk).update(ends_at=original_end)

    def test_framing_failure_lexical_null_unknown_recovery_broker_and_task_never_replay(self):
        job = self.queue("truncated")
        fetcher = self.transport(fields=b"Content-Length: 999\r\nContent-Type: text/html; charset=utf-8\r\n")
        self.assertTrue(collection.execute_passive_resource_collection(job.pk, fetcher=fetcher))
        job.refresh_from_db(); self.assertEqual((job.status, job.error_category), ("failed", "incomplete_response_body"))
        with self.assertRaises(ValidationError): retry_job(job=job, actor=self.owner, idempotency_key="retry")
        self.assertFalse(collection.execute_passive_resource_collection(job.pk, fetcher=fetcher)); self.connection.request.assert_called_once()
        lexical = self.queue("lexical")
        collection.execute_passive_resource_collection(lexical.pk, fetcher=self.transport(body=b"<img src='x' src='y'>"))
        result = self.read(lexical)["collection"]["evidence"]["resource_references"]
        self.assertEqual(result["state"], "unavailable"); self.assertTrue(all(value is None for value in result["counts"].values()))
        unknown = self.queue("unknown"); unknown.status = JobStatus.RUNNING; unknown.save(update_fields=["status", "updated_at"])
        JobStep.objects.create(job=unknown, sequence=1, name=collection.STAGE, status="running", output={"method": collection.METHOD, "state": "attempted"})
        JobRun.objects.filter(pk=unknown.pk).update(updated_at=timezone.now() - timedelta(minutes=5))
        self.assertEqual(reconcile_stuck_passive_resources(), 1); self.assertEqual(reconcile_stuck_passive_resources(), 0)
        unknown.refresh_from_db(); unknown.usage.refresh_from_db(); self.assertEqual((unknown.error_category, unknown.usage.actual_units), ("request_outcome_unknown", 1))
        UsageReservation.objects.filter(job=unknown).update(state="reserved", actual_units=0, settled_at=None)
        self.assertEqual(reconcile_usage(), 1); unknown.usage.refresh_from_db(); self.assertEqual(unknown.usage.actual_units, 1)
        with patch("jobs.passive_resource_collection.execute_passive_resource_collection", return_value=False) as execute:
            self.assertFalse(execute_passive_resource_collection_task.run(unknown.pk)); execute.assert_called_once_with(unknown.pk)
        broker = self.queue("broker"); JobRun.objects.filter(pk=broker.pk).update(dispatched_at=None)
        with patch("jobs.tasks.execute_passive_resource_collection_task.apply_async", side_effect=OSError("fixture broker")):
            self.assertFalse(dispatch_pending(broker.pk))
        with patch("jobs.tasks.execute_passive_resource_collection_task.apply_async") as task:
            self.assertTrue(dispatch_pending(broker.pk)); self.assertFalse(dispatch_pending(broker.pk)); task.assert_called_once()

    def test_full_source_usage_private_write_read_and_late_settlement_fences(self):
        for boundary in ("reservation", "write", "read", "step", "settlement"):
            job = self.queue(boundary); original_digest = self.verification.challenge_digest
            if boundary == "reservation":
                stamp = job.usage.created_at
                def changed(): UsageReservation.objects.filter(job=job).update(created_at=stamp + timedelta(microseconds=1))
                collection.execute_passive_resource_collection(job.pk, fetcher=self.transport(on_connect=changed))
            elif boundary == "write":
                original = lifecycle.save_project_artifact
                def changed(**kwargs):
                    key = original(**kwargs)
                    OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member")
                    return key
                with patch.object(lifecycle, "save_project_artifact", changed): collection.execute_passive_resource_collection(job.pk, fetcher=self.transport())
                OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="owner")
            elif boundary == "read":
                collection.execute_passive_resource_collection(job.pk, fetcher=self.transport())
                original = lifecycle.read_project_artifact
                def changed(**kwargs):
                    content = original(**kwargs); JobStep.objects.filter(job=job).update(error_category="hidden"); return content
                with patch.object(lifecycle, "read_project_artifact", changed), self.assertRaises(PermissionDenied): self.read(job)
                continue
            else:
                original = JobStep.save if boundary == "step" else lifecycle.settle_usage
                def changed_step(step, *args, **kwargs):
                    value = original(step, *args, **kwargs)
                    if step.job_id == job.pk and step.status == "succeeded":
                        ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(challenge_digest="a" * 64)
                    return value
                def changed_settlement(**kwargs):
                    value = original(**kwargs)
                    if kwargs["job"].status == "succeeded": ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(challenge_digest="a" * 64)
                    return value
                context = patch.object(JobStep, "save", changed_step) if boundary == "step" else patch.object(lifecycle, "settle_usage", changed_settlement)
                with context: collection.execute_passive_resource_collection(job.pk, fetcher=self.transport())
                self.assertEqual(ProjectOriginVerification.objects.get(pk=self.verification.pk).challenge_digest, original_digest)
            job.refresh_from_db(); job.usage.refresh_from_db()
            self.assertEqual((job.output, job.artifacts.count(), job.usage.actual_units), ({}, 0, 1))
            self.assertIn(job.status, {"failed", "cancelled"})

    def test_postgresql_queue_race_and_active_advisory_recovery_never_repeat_get(self):
        barrier = Barrier(2)
        def queue():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                with patch("celery.app.task.Task.apply_async"):
                    return collection.queue_passive_resource_collection(project=self.project, actor=self.owner, data=self.data, idempotency_key="race").pk
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool: ids = list(pool.map(lambda _: queue(), range(2)))
        self.assertEqual(ids[0], ids[1]); self.assertEqual(JobRun.objects.filter(handler=collection.HANDLER, idempotency_key="race").count(), 1)
        job = self.queue("active"); started, release = Event(), Event()
        def wait():
            started.set()
            if not release.wait(timeout=10): raise AssertionError("Fixture must release body")
        fetcher = self.transport(on_body=wait)
        def execute():
            close_old_connections()
            try: return collection.execute_passive_resource_collection(job.pk, fetcher=fetcher)
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(execute)
            try:
                self.assertTrue(started.wait(timeout=10)); JobRun.objects.filter(pk=job.pk).update(updated_at=timezone.now() - timedelta(minutes=2))
                self.assertEqual(reconcile_stuck_passive_resources(), 0)
                self.assertFalse(collection.execute_passive_resource_collection(job.pk, fetcher=fetcher))
            finally: release.set()
            self.assertTrue(future.result(timeout=10))
        self.connection.request.assert_called_once(); job.refresh_from_db(); self.assertEqual(job.status, "succeeded")

    def test_genuine_customer_exports_retained_revocation_cutoff_and_scoped_erasure(self):
        from tenancy.customer_export import complete_bounded_customer_archive
        from tenancy.customer_inventory import CUSTOMER
        from tenancy.customer_snapshot import reserve_bounded_customer_snapshot, capture_reserved_customer_snapshot, private_snapshot_part
        from tenancy.customer_source_parts import capture_source_stage
        from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        from tenancy.services import revoke_origin_verification
        job = self.queue(); collection.execute_passive_resource_collection(job.pk, fetcher=self.transport())
        job.refresh_from_db(); artifact = job.artifacts.get(); content = read_project_artifact(project=self.project, key=artifact.key)
        with ZipFile(io.BytesIO(complete_bounded_customer_archive(organization=self.organization, actor=self.owner))) as archive:
            row = next(row for row in json.loads(archive.read("records/jobs/JobRun.json")) if row["id"] == job.pk)
            self.assertEqual(row["output"], job.output); self.assertIn(content, [archive.read(name) for name in archive.namelist()])
        bounded = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner, request_key="c" * 32)
        self.assertTrue(capture_reserved_customer_snapshot(bounded.pk))
        retained, _ = private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=bounded.pk, position=0)
        revoke_origin_verification(verification=self.verification, user=self.owner)
        with self.assertRaises(PermissionDenied): self.read(job)
        self.assertEqual(private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=bounded.pk, position=0)[0], retained)
        sequential = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner, request_key="d" * 32, format="source-parts-v2")
        for _ in range(len(CUSTOMER) * 2 + 10):
            sequential.refresh_from_db()
            if sequential.state != sequential.State.PREPARING: break
            self.assertTrue(capture_source_stage(sequential.pk, sequential.progress.get("step", 0)))
        sequential.refresh_from_db(); self.assertEqual(sequential.state, sequential.State.READY)
        part = sequential.parts.filter(source__model="jobs.JobRun").first()
        data, _ = private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=sequential.pk, position=part.position)
        with ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(next(row for row in json.loads(archive.read("data")) if row["id"] == job.pk)["output"], job.output)
        now = timezone.now(); OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now - timedelta(days=121), ends_at=now - timedelta(days=91))
        with self.assertRaises(PermissionDenied): private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=bounded.pk, position=0)
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=now)
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.organization))
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(JobRun.objects.filter(pk=job.pk).exists()); self.assertFalse(Artifact.objects.filter(pk=artifact.pk).exists())
