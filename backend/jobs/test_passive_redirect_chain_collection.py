import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event
from unittest.mock import patch
from zipfile import ZipFile

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.artifacts import read_project_artifact
from tenancy.models import Organization, OrganizationMembership, OrganizationTrial, ProjectOriginVerification
from tenancy.services import revoke_origin_verification
from . import passive_header_collection as lifecycle
from . import passive_redirect_chain_collection as collection
from . import test_passive_redirect_chain_source as source_fixtures
from . import test_passive_redirect_chain_transport as transport_fixtures
from .api import _job_payload
from .crawling import CrawlScope
from .models import Artifact, JobRun, JobStep, SourceCitation, UsageReservation
from .recovery import reconcile_stuck_passive_redirect_chain
from .services import cancel_job, dispatch_pending, execute_job, queue_job, retry_job
from .tasks import execute_passive_redirect_chain_collection_task
from .usage import UsageLimitError, reconcile_usage


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json", "application/zip"}))
class PassiveRedirectChainCollectionTests(TransactionTestCase):
    verified = source_fixtures.PassiveRedirectChainSourceTests.verified

    def setUp(self):
        dispatch = patch("celery.app.task.Task.apply_async")
        dispatch.start(); self.addCleanup(dispatch.stop)
        source_fixtures.PassiveRedirectChainSourceTests.setUp(self)
        self.http_verification, self.https_verification = self.verified(self.http), self.verified(self.https)
        self.data = {"url": self.http + "/public", "target_urls": [self.https + "/public"],
            "observations": ["redirect_chain"], "collection_permission": True}

    def queue(self, key="chain-request", **changes):
        with patch("jobs.tasks.execute_passive_redirect_chain_collection_task.apply_async") as task:
            job = collection.queue_passive_redirect_chain_collection(**{**dict(project=self.project, actor=self.owner,
                data=self.data, idempotency_key=key), **changes})
        self.dispatch = task
        return job

    def transport(self, data=None):
        data = data or self.data
        wires = [f"HTTP/1.1 301 Moved\r\nLocation: {url}\r\nSet-Cookie: private=secret\r\n\r\nprivate body".encode()
            for url in data["target_urls"]] + [b"HTTP/1.1 200 OK\r\nServer: private\r\n\r\nprivate body"]
        case = transport_fixtures.PassiveRedirectChainTransportTests(); self.addCleanup(case.doCleanups)
        fetcher, connections, responses, factory, resolver = case.transport(*wires)
        fetcher.scope = CrawlScope(frozenset({"security.example.com", "www.security.example.com"}))
        return fetcher, connections, responses, factory, resolver

    def collect(self, job, fetcher=None):
        return collection.execute_passive_redirect_chain_collection(job.pk, fetcher=fetcher or self.transport()[0])

    def read(self, job, actor=None):
        return collection.read_passive_redirect_chain_observation(project=self.project, actor=actor or self.owner, job_id=job.pk)

    def test_genuine_committed_multi_origin_native_once_only_private_original_and_independent_reader(self):
        self.verified("https://www.security.example.com")
        self.data["target_urls"].append("https://www.security.example.com/public")
        job = self.queue()
        self.dispatch.assert_called_once_with(args=[job.pk], queue="audit", task_id=f"job-{job.pk}", retry=False)
        self.assertEqual((job.method_version, job.usage.provider, job.usage.reserved_units), (collection.METHOD, "passive_security", 1))
        self.assertEqual(self.queue().pk, job.pk); self.dispatch.assert_not_called()
        fetcher, connections, responses, factory, resolver = self.transport(); fetch = fetcher.fetch; captured = []
        def capture(*args, **kwargs):
            self.assertEqual(kwargs["redirect_chain_selection"], self.data)
            self.assertFalse(connection.in_atomic_block)
            self.assertEqual(job.steps.get().output, {"method": collection.METHOD, "state": "attempted"})
            result = fetch(*args, **kwargs); captured.append(result); return result
        fetcher.fetch = capture
        with patch("socket.create_connection", side_effect=AssertionError("No actual egress")), patch.object(lifecycle, "SafeFetcher", return_value=fetcher) as native:
            self.assertTrue(collection.execute_passive_redirect_chain_collection(job.pk))
        native.assert_called_once_with(CrawlScope(frozenset({"security.example.com", "www.security.example.com"})), timeout=10, max_redirects=5)
        job.refresh_from_db(); result = self.read(job)["collection"]
        self.assertEqual((job.status, job.usage.state, job.usage.actual_units), ("succeeded", "settled", 1))
        self.assertEqual(result["evidence"], captured[0].redirect_observation)
        self.assertEqual([hop["url"] for hop in result["evidence"]["hops"]], [self.data["url"], *self.data["target_urls"]])
        self.assertEqual(job.citations.get().source_url, self.data["url"])
        self.assertEqual(job.citations.get().observed_at.isoformat(timespec="microseconds"), result["observed_at"])
        content = read_project_artifact(project=self.project, key=job.artifacts.get().key)
        self.assertEqual(json.loads(content), result)
        for raw in (b"private", b"secret", b"source_digest", self.challenge.encode()): self.assertNotIn(raw, content)
        self.assertFalse(set(_job_payload(job, detailed=True)) & {"output", "steps", "citations", "artifacts"})
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        self.assertEqual(self.read(job, self.member)["collection"], result)
        for handler in lifecycle.PASSIVE_HANDLERS:
            if handler != collection.HANDLER:
                with self.assertRaises(PermissionDenied):
                    lifecycle.read_passive_header_observation(project=self.project, actor=self.owner, job_id=job.pk, handler=handler)
        self.assertFalse(self.collect(job, fetcher))
        for conn, response in zip(connections, responses): conn.request.assert_called_once(); response.read.assert_not_called()
        job.output = {}; self.assertRaises(ValidationError, job.save, update_fields=["output"])

    def test_actual_six_maximum_paths_and_chain_only_model_reader_cap_preserve_original_families(self):
        prefix = self.http + "/"; url = prefix + "x" * (1024 - len(prefix))
        targets = []
        for index in range(5):
            prefix = self.https + f"/page-{index}-"; targets.append(prefix + "x" * (1024 - len(prefix)))
        data = {**self.data, "url": url, "target_urls": targets}
        job = self.queue(data=data); fetcher, connections, *_ = self.transport(data)
        self.assertTrue(self.collect(job, fetcher)); job.refresh_from_db()
        result = self.read(job)["collection"]; artifact = job.artifacts.get()
        self.assertEqual(len(result["evidence"]["hops"]), 6); self.assertGreater(artifact.size_bytes, 8192)
        self.assertLessEqual(artifact.size_bytes, 24576)
        artifact.size_bytes = 24576; artifact.full_clean()
        artifact.size_bytes = 24577
        with self.assertRaises(ValidationError): artifact.full_clean()
        for handler in lifecycle.PASSIVE_HANDLERS:
            if handler == collection.HANDLER: continue
            job.handler = handler; artifact.job = job; artifact.size_bytes = 8192; artifact.full_clean()
            artifact.size_bytes = 8193
            with self.assertRaises(ValidationError): artifact.full_clean()
        job.refresh_from_db()
        with transaction.atomic():
            Artifact.objects.filter(job=job).update(size_bytes=24577)
            with patch.object(lifecycle, "read_project_artifact", side_effect=AssertionError("Cap before byte read")), self.assertRaises(ValidationError): self.read(job)
            transaction.set_rollback(True)
        for conn in connections: conn.request.assert_called_once()

    def test_exact_permissions_current_all_origins_manual_models_atomic_retry_and_expired_queue(self):
        for changes in ({"collection_permission": 1}, {"observations": ["response_location"]},
            {"target_urls": [self.https + "/public?"]}, {"target_urls": [self.data["url"]]}):
            with self.assertRaises(ValidationError): self.queue(data={**self.data, **changes})
        with self.assertRaises(PermissionDenied): self.queue(actor=self.member)
        with self.assertRaises((PermissionDenied, ValidationError)):
            queue_job(project=self.project, actor=self.owner, handler=collection.HANDLER, input_snapshot=self.data,
                config_snapshot={}, idempotency_key="bad-config")
        with transaction.atomic():
            revoke_origin_verification(verification=self.https_verification, user=self.owner)
            with self.assertRaises(PermissionDenied): self.queue("missing-target-grant")
            transaction.set_rollback(True)
        job = self.queue(); fetcher, connections, *_ = self.transport()
        with transaction.atomic(), self.assertRaises(ValidationError): self.collect(job, fetcher)
        self.assertFalse(job.steps.exists()); connections[0].request.assert_not_called()
        with self.assertRaises(ValidationError):
            JobRun.objects.create(project=self.project, organization=self.organization, actor=self.owner, handler=collection.HANDLER,
                method_version=collection.METHOD, input_snapshot=self.data, config_snapshot=job.config_snapshot, scheduled_for=timezone.now())
        with self.assertRaises(ValidationError):
            JobStep.objects.create(job=job, sequence=2, name=collection.STAGE, status="running", output={"method": collection.METHOD, "state": "attempted"})
        with self.assertRaises(ValidationError):
            queue_job(project=self.project, actor=self.owner, handler=collection.HANDLER, input_snapshot=self.data,
                config_snapshot=job.config_snapshot, idempotency_key="retry", retry_of=job)
        def unselected(url, **kwargs): kwargs["before_request"](self.http + "/unselected")
        fetcher.fetch = unselected; self.collect(job, fetcher)
        job.refresh_from_db(); self.assertEqual((job.status, job.output, job.usage.actual_units), ("failed", {}, 1))
        with self.assertRaises(ValidationError): retry_job(job=job, actor=self.owner, idempotency_key="retry-failed")
        trial = self.organization.trial
        start = timezone.now() - timedelta(days=31)
        OrganizationTrial.objects.filter(pk=trial.pk).update(started_at=start, ends_at=start + timedelta(days=30))
        with self.assertRaises(UsageLimitError): self.queue("expired")
        OrganizationTrial.objects.filter(pk=trial.pk).update(started_at=trial.started_at, ends_at=trial.ends_at)
        revoked = self.queue("revoked-before-attempt")
        revoke_origin_verification(verification=self.https_verification, user=self.owner)
        fetcher, connections, *_ = self.transport(); self.collect(revoked, fetcher); revoked.refresh_from_db()
        self.assertEqual((revoked.status, revoked.usage.actual_units, revoked.steps.count()), ("cancelled", 0, 0))
        connections[0].request.assert_not_called()

    def test_each_hop_all_origin_loss_before_dns_connected_and_completion_discards_whole_chain(self):
        for hop in (0, 1):
            for boundary in ("before", "dns", "connected", "completion"):
                for verification in (self.http_verification, self.https_verification):
                    with self.subTest(hop=hop, boundary=boundary, origin=verification.origin):
                        job = self.queue(f"{hop}-{boundary}-{verification.pk}")
                        fetcher, connections, responses, factory, resolver = self.transport()
                        def lose(): ProjectOriginVerification.objects.filter(pk=verification.pk).update(challenge_digest="b" * 64)
                        if boundary == "before":
                            fetch = fetcher.fetch
                            def guarded(url, **kwargs):
                                before = kwargs["before_request"]; calls = 0
                                def changed(current):
                                    nonlocal calls
                                    calls += 1
                                    if calls == hop * 2 + 1: lose()
                                    return before(current)
                                return fetch(url, **{**kwargs, "before_request": changed})
                            fetcher.fetch = guarded
                        elif boundary == "dns":
                            calls = 0
                            def dns(*args):
                                nonlocal calls
                                calls += 1
                                if calls == hop + 1: lose()
                                return ["93.184.216.34"]
                            fetcher.resolver = dns
                        elif boundary == "connected": connections[hop].connect.side_effect = lose
                        else:
                            connections[hop].getresponse.side_effect = lambda: (lose(), responses[hop])[1]
                        self.collect(job, fetcher); job.refresh_from_db()
                        self.assertEqual((job.status, job.output, job.artifacts.count(), job.usage.actual_units),
                            ("cancelled", {}, 0, 1))
                        if boundary != "completion": connections[hop].request.assert_not_called()
                        else: connections[hop].request.assert_called_once()
                        if hop == 0: connections[1].request.assert_not_called()
                        self.assertFalse(self.collect(job, fetcher))
                        ProjectOriginVerification.objects.filter(pk=verification.pk).update(challenge_digest=verification.challenge_digest)

    def test_second_connected_cancel_and_natural_expiry_after_slow_every_origin_source(self):
        for loss in ("cancel", "expiry"):
            job = self.queue(loss); fetcher, connections, *_ = self.transport(); now = [timezone.now()]; connected = False
            end = self.organization.trial.ends_at; validate = lifecycle.validate_job
            def connect():
                nonlocal connected
                connected = True
                if loss == "cancel": cancel_job(job=job, actor=self.owner)
            connections[1].connect.side_effect = connect
            def slow(*args, **kwargs):
                result = validate(*args, **kwargs)
                if connected and kwargs.get("current") and loss == "expiry": now[0] = end
                return result
            with patch.object(lifecycle, "validate_job", slow), patch("jobs.usage.timezone.now", side_effect=lambda: now[0]): self.collect(job, fetcher)
            connections[0].request.assert_called_once(); connections[1].request.assert_not_called(); job.refresh_from_db()
            self.assertEqual((job.status, job.output, job.usage.actual_units), ("cancelled", {}, 1))

    def test_full_intended_metadata_actual_private_bytes_last_date_and_late_independent_read_fail_closed(self):
        for boundary in ("attempt", "artifact", "citation", "settlement", "bytes"):
            job = self.queue(boundary); fetcher, connections, *_ = self.transport()
            if boundary == "attempt":
                def drift():
                    step = job.steps.get(); JobStep.objects.filter(pk=step.pk).update(created_at=step.created_at - timedelta(microseconds=1))
                connections[1].connect.side_effect = drift
                self.collect(job, fetcher); connections[1].request.assert_not_called()
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
                with context: self.collect(job, fetcher)
            job.refresh_from_db()
            self.assertIn(job.status, {"cancelled", "failed"})
            self.assertEqual((job.output, job.artifacts.count(), job.citations.count(), job.usage.actual_units), ({}, 0, 0, 1))
            self.assertFalse(self.collect(job, fetcher))
        job = self.queue("read"); self.collect(job); job.refresh_from_db()
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        expected = self.read(job, self.member)
        for boundary in ("source", "metadata", "bytes", "last_date"):
            with transaction.atomic():
                now = [timezone.now()]; calls = 0
                attribute = {"source": "selection_snapshot", "metadata": "_read_metadata", "bytes": "read_project_artifact", "last_date": "_read_metadata"}[boundary]
                original = getattr(lifecycle, attribute)
                def changed(*args, **kwargs):
                    nonlocal calls
                    value = original(*args, **kwargs); calls += 1
                    if boundary == "source" and calls == 4 or boundary == "metadata" and calls == 2: now[0] = self.organization.trial.ends_at
                    elif boundary == "bytes": OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="viewer")
                    elif boundary == "last_date": value["artifacts"][0]["created_at"] = timezone.datetime.fromisoformat(job.output["last_observed_at"]) - timedelta(microseconds=1)
                    return value
                with patch.object(lifecycle, attribute, changed), patch("jobs.usage.timezone.now", side_effect=lambda: now[0]):
                    with self.assertRaises((PermissionDenied, ValidationError)): self.read(job, self.member)
                transaction.set_rollback(True)
        self.assertEqual(self.read(job, self.member), expected)

    def test_mid_chain_failure_unknown_recovery_usage_broker_and_task_entrypoints_never_replay(self):
        job = self.queue("network"); fetcher, connections, *_ = self.transport()
        connections[1].connect.side_effect = OSError("private provider error")
        self.collect(job, fetcher); job.refresh_from_db()
        self.assertEqual((job.status, job.error_category, job.output, job.usage.actual_units), ("failed", "network_error", {}, 1))
        connections[0].request.assert_called_once(); connections[1].request.assert_not_called()
        self.assertFalse(self.collect(job, fetcher))
        unknown = self.queue("unknown"); unknown.status = "running"; unknown.save(update_fields=["status", "updated_at"])
        JobStep.objects.create(job=unknown, sequence=1, name=collection.STAGE, status="running", output={"method": collection.METHOD, "state": "attempted"})
        JobRun.objects.filter(pk=unknown.pk).update(updated_at=timezone.now() - timedelta(minutes=5))
        with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No unknown replay")):
            self.assertEqual(reconcile_stuck_passive_redirect_chain(), 1); self.assertEqual(reconcile_stuck_passive_redirect_chain(), 0)
            self.assertFalse(self.collect(unknown))
        unknown.refresh_from_db(); self.assertEqual((unknown.error_category, unknown.usage.actual_units), ("request_outcome_unknown", 1))
        UsageReservation.objects.filter(job=unknown).update(state="reserved", actual_units=0, settled_at=None)
        self.assertEqual(reconcile_usage(), 1); unknown.usage.refresh_from_db(); self.assertEqual(unknown.usage.actual_units, 1)
        with patch.object(collection, "execute_passive_redirect_chain_collection", return_value=False) as execute:
            self.assertFalse(execute_passive_redirect_chain_collection_task.run(unknown.pk)); execute.assert_called_once_with(unknown.pk)
            self.assertFalse(execute_job(unknown.pk)); self.assertEqual(execute.call_count, 2)
        broker = self.queue("broker"); JobRun.objects.filter(pk=broker.pk).update(dispatched_at=None)
        with patch("jobs.tasks.execute_passive_redirect_chain_collection_task.apply_async", side_effect=OSError("fixture broker")): self.assertFalse(dispatch_pending(broker.pk))
        with patch("jobs.tasks.execute_passive_redirect_chain_collection_task.apply_async") as task:
            self.assertTrue(dispatch_pending(broker.pk)); self.assertFalse(dispatch_pending(broker.pk))
            task.assert_called_once_with(args=[broker.pk], queue="audit", task_id=f"job-{broker.pk}", retry=False)

    def test_postgresql_duplicate_queue_and_live_second_hop_advisory_recovery_never_repeat(self):
        barrier = Barrier(2)
        def queue():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return self.queue("concurrent").pk
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool: ids = list(pool.map(lambda _: queue(), range(2)))
        self.assertEqual(ids[0], ids[1])
        job = self.queue("active"); started, release = Event(), Event(); fetcher, connections, responses, *_ = self.transport()
        def wait():
            started.set()
            if not release.wait(timeout=10): raise AssertionError("Release fixture transport")
            return responses[1]
        connections[1].getresponse.side_effect = wait
        def execute():
            close_old_connections()
            try: return self.collect(job, fetcher)
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(execute)
            try:
                self.assertTrue(started.wait(timeout=10))
                JobRun.objects.filter(pk=job.pk).update(updated_at=timezone.now() - timedelta(minutes=2))
                self.assertEqual(reconcile_stuck_passive_redirect_chain(), 0); self.assertFalse(self.collect(job, fetcher))
            finally: release.set()
            self.assertTrue(future.result(timeout=10))
        for conn in connections: conn.request.assert_called_once()
        job.refresh_from_db(); self.assertEqual(job.status, "succeeded")

    def test_genuine_customer_stored_sequential_history_retention_and_child_first_scoped_erasure(self):
        from tenancy.customer_export import complete_bounded_customer_archive
        from tenancy.customer_inventory import CUSTOMER
        from tenancy.customer_snapshot import reserve_bounded_customer_snapshot, capture_reserved_customer_snapshot, private_snapshot_part
        from tenancy.customer_source_parts import capture_source_stage
        from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        job = self.queue(); self.collect(job); job.refresh_from_db(); artifact = job.artifacts.get()
        content = read_project_artifact(project=self.project, key=artifact.key)
        with ZipFile(io.BytesIO(complete_bounded_customer_archive(organization=self.organization, actor=self.owner))) as archive:
            row = next(row for row in json.loads(archive.read("records/jobs/JobRun.json")) if row["id"] == job.pk)
            self.assertEqual(row["output"], job.output); self.assertIn("historical_exact_selected_chain", row["scope"])
            self.assertIn(content, [archive.read(name) for name in archive.namelist()])
        bounded = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner, request_key="1" * 32)
        self.assertTrue(capture_reserved_customer_snapshot(bounded.pk))
        retained, _ = private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=bounded.pk, position=0)
        revoke_origin_verification(verification=self.https_verification, user=self.owner)
        with self.assertRaises(PermissionDenied): self.read(job)
        self.assertEqual(private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=bounded.pk, position=0)[0], retained)
        sequential = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner, request_key="2" * 32, format="source-parts-v2")
        for _ in range(len(CUSTOMER) * 2 + 10):
            sequential.refresh_from_db()
            if sequential.state != sequential.State.PREPARING: break
            self.assertTrue(capture_source_stage(sequential.pk, sequential.progress.get("step", 0)))
        sequential.refresh_from_db(); self.assertEqual(sequential.state, sequential.State.READY)
        part = sequential.parts.filter(source__model="jobs.JobRun").first()
        data, _ = private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=sequential.pk, position=part.position)
        with ZipFile(io.BytesIO(data)) as archive:
            row = next(row for row in json.loads(archive.read("data")) if row["id"] == job.pk)
            self.assertEqual(row["output"], job.output); self.assertIn("historical_exact_selected_chain", row["scope"])
        now = timezone.now()
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now - timedelta(days=121), ends_at=now - timedelta(days=91))
        with self.assertRaises(PermissionDenied): private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=bounded.pk, position=0)
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=now)
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.organization))
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(JobRun.objects.filter(pk=job.pk).exists()); self.assertFalse(Artifact.objects.filter(pk=artifact.pk).exists())
