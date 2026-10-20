from tenancy.customer_artifact_barrier import project_artifact_barrier
import io
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import timedelta
from decimal import Decimal
from threading import Barrier, Event
from unittest.mock import patch
from zipfile import ZipFile

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from kombu.exceptions import OperationalError

from config.test_foundations import TEST_STORAGES
from providers.adapters import ProviderRequestError, ProviderResponse
from providers.models import AIModel, AIProviderAccount
from tenancy.artifacts import read_project_artifact, save_project_artifact
from tenancy.models import Organization, OrganizationMembership, OrganizationTrial, ProjectConfiguration
from . import competitor_synthesis_job as synthesis
from . import test_competitor_synthesis_selection as fixtures
from .ai_usage import record_ai_attempt
from .models import AIUsageRecord, Artifact, CrawlRun, Finding, JobCancellation, JobRun, JobStep, SourceCitation, UsageReservation
from .recovery import reconcile_stuck_competitor_synthesis
from .services import cancel_job, dispatch_pending, queue_job, retry_job
from .usage import UsageLimitError, reconcile_usage


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}))
class CompetitorSynthesisJobTests(TransactionTestCase):
    setUp = fixtures.CompetitorSynthesisSelectionTests.setUp
    queue = fixtures.CompetitorSynthesisSelectionTests.queue
    transport = fixtures.CompetitorSynthesisSelectionTests.transport
    collected = fixtures.CompetitorSynthesisSelectionTests.collected
    input_data = fixtures.CompetitorSynthesisSelectionTests.input_data

    def pair(self):
        return self.collected("original-before"), self.collected("original-after", b"<title>Second</title><h2>New</h2>")

    def queue_synthesis(self, before, after, key="synthesis-request", **changes):
        with patch("jobs.tasks.execute_competitor_synthesis_task.apply_async") as task:
            job = synthesis.queue_competitor_synthesis(project=self.project, actor=self.admin,
                data=self.input_data(before, after, **changes), idempotency_key=key)
        self.dispatch = task
        return job

    def response(self):
        return ProviderResponse(text="Untrusted raw answer excluded", structured={"interpretations": [{
            "text": "The current original title says Second; verify this interpretation before acting.",
            "reference": "current_title", "quote": "Second"}]}, citations=(), request_id="fixture-request",
            response_id="fixture-response", input_tokens=40, output_tokens=20)

    def request(self, **kwargs):
        self.assertFalse(connection.in_atomic_block)
        job = JobRun.objects.get(handler=synthesis.HANDLER, status="running")
        self.assertEqual(job.steps.get().output, {"method": synthesis.METHOD, "state": "attempted"})
        self.assertEqual(job.ai_usage_record.status, "attempted")
        self.assertEqual(kwargs["output_schema"], synthesis.synthesis.OUTPUT_SCHEMA)
        self.assertIs(kwargs["web_search"], False)
        self.assertEqual(kwargs["timeout"], 30)
        self.assertIn("untrusted source data", kwargs["prompt"])
        kwargs["checkpoint"]()
        return self.response()

    def read(self, job, actor=None):
        return synthesis.read_competitor_synthesis(project=self.project, actor=actor or self.owner, job_id=job.pk)

    def test_committed_once_only_original_facts_separate_notes_private_readback_and_ai_usage(self):
        before, after = self.pair()
        job = self.queue_synthesis(before, after)
        self.dispatch.assert_called_once_with(args=[job.pk], queue="ai", task_id=f"job-{job.pk}", retry=False)
        self.assertEqual((job.usage.provider, job.usage.reserved_units), ("ai", 1))
        self.assertEqual(self.queue_synthesis(before, after).pk, job.pk); self.dispatch.assert_not_called()
        with patch("socket.create_connection", side_effect=AssertionError("No actual provider")):
            self.assertTrue(synthesis.execute_competitor_synthesis(job.pk, request=self.request))
        job.refresh_from_db(); self.assertEqual(job.status, "succeeded", job.error_category)
        result = self.read(job)
        self.assertEqual(self.read(job, self.admin), result)
        self.assertEqual(result["synthesis"]["comparison"]["previous"]["evidence"], before.output["evidence"])
        self.assertEqual(result["synthesis"]["comparison"]["current"]["evidence"], after.output["evidence"])
        self.assertEqual(result["synthesis"]["state"], synthesis.STATE)
        self.assertEqual(len(result["synthesis"]["interpretations"]), 1)
        ai = job.ai_usage_record
        self.assertEqual((ai.status, ai.input_tokens, ai.output_tokens, ai.estimated_cost_usd, ai.reported_cost_usd),
            ("completed", 40, 20, Decimal("0.000055"), None))
        self.assertFalse(ai.web_search_used); self.assertEqual(ai.tool_call_count, 0)
        self.assertEqual((job.usage.actual_units, job.usage.state), (1, "settled"))
        self.assertLess(job.citations.first().observed_at, ai.attempted_at)
        content = read_project_artifact(project=self.project, key=job.artifacts.get().key)
        self.assertEqual(json.loads(content), result["synthesis"])
        for poison in (b"Untrusted raw answer", b"prompt", b"secret_reference", self.owner.email.encode()): self.assertNotIn(poison, content)
        from .api import _job_payload
        self.assertFalse({"output", "steps", "citations", "artifacts"} & set(_job_payload(job, detailed=True)))
        self.assertFalse(CrawlRun.objects.exists()); self.assertFalse(Finding.objects.exists())
        with patch.object(synthesis, "create_response", side_effect=AssertionError("No replay")):
            self.assertFalse(synthesis.execute_competitor_synthesis(job.pk, request=self.request))
        job.output = {**job.output, "prompt": "private"}
        with self.assertRaises(ValidationError): job.save()
        step = job.steps.get(); step.output = {"text": "private"}
        with self.assertRaises(ValidationError): step.save()

    def test_current_guard_loses_pair_model_account_actor_attempt_usage_cancel_and_deadline(self):
        before, after = self.pair()
        for point in ("pair", "model", "account", "actor", "attempt", "usage", "cancel", "expiry"):
            job = self.queue_synthesis(before, after, "loss-" + point)
            now = [timezone.now()]; ends = now[0] + timedelta(seconds=30)
            trial = OrganizationTrial.objects.get(organization=self.organization)
            if point == "expiry":
                OrganizationTrial.objects.filter(pk=trial.pk).update(started_at=ends - timedelta(days=30), ends_at=ends)
            def request(**kwargs):
                self.assertFalse(connection.in_atomic_block)
                if point == "pair": Artifact.objects.filter(job=before).update(created_at=before.artifacts.get().created_at + timedelta(microseconds=1))
                elif point == "model": AIModel.objects.filter(pk=self.model.pk).update(enabled=False)
                elif point == "account": AIProviderAccount.objects.filter(pk=self.account.pk).update(state="revoked", revoked_at=timezone.now())
                elif point == "actor": OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer")
                elif point == "attempt": AIUsageRecord.objects.filter(job=job).update(attempted_at=timezone.now() + timedelta(microseconds=1))
                elif point == "usage": UsageReservation.objects.filter(job=job).update(period_start=job.usage.period_start.replace(year=2001))
                elif point == "cancel": cancel_job(job=job, actor=self.admin)
                else: now[0] = ends
                kwargs["checkpoint"]()
                raise AssertionError("Current fence must deny before sending")
            original_artifact = before.artifacts.get()
            with patch("jobs.usage.timezone.now", side_effect=lambda: now[0]):
                synthesis.execute_competitor_synthesis(job.pk, request=request)
            job.refresh_from_db(); self.assertEqual(job.status, "cancelled", point)
            self.assertFalse(job.output); self.assertFalse(job.artifacts.exists())
            self.assertEqual(job.usage.actual_units, 1)
            self.assertFalse(synthesis.execute_competitor_synthesis(job.pk, request=request))
            Artifact.objects.filter(pk=original_artifact.pk).update(created_at=original_artifact.created_at)
            AIModel.objects.filter(pk=self.model.pk).update(enabled=True)
            AIProviderAccount.objects.filter(pk=self.account.pk).update(state="active", revoked_at=None)
            OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="admin")
            OrganizationTrial.objects.filter(pk=trial.pk).update(started_at=trial.started_at, ends_at=trial.ends_at)

    def test_first_original_cancellation_during_last_second_reader_source_withholds_private_synthesis(self):
        before, after = self.pair()
        job = self.queue_synthesis(before, after)
        self.assertTrue(synthesis.execute_competitor_synthesis(job.pk, request=self.request))
        job.refresh_from_db()
        packet, source = synthesis.synthesis.read_competitor_synthesis_source, synthesis.collection._read_source
        completed, injected = [0], [False]
        def completed_packet(*args, **kwargs):
            result = packet(*args, **kwargs); completed[0] += 1; return result
        def final_source(original, *args, **kwargs):
            result = source(original, *args, **kwargs)
            if completed[0] and original.pk == after.pk and not injected[0]:
                JobCancellation.objects.create(job=before, requested_by=self.owner)
                injected[0] = True
            return result
        denied = False
        with patch.object(synthesis.synthesis, "read_competitor_synthesis_source", side_effect=completed_packet), \
             patch.object(synthesis.collection, "_read_source", side_effect=final_source):
            try: synthesis._reader_source(job, self.project, self.owner)
            except PermissionDenied: denied = True
        self.assertTrue(injected[0])
        self.assertTrue(denied, "Private synthesis reader authority escaped after its first original was cancelled during the final second source read.")

    def test_actual_native_adapter_pinned_transfer_committed_usage_and_connected_current_model_loss(self):
        from providers import adapters
        from providers.test_adapters import FakeHTTPResponse, GuardedConnection
        before, after = self.pair()
        for loss in (False, True):
            job = self.queue_synthesis(before, after, "native-" + str(loss))
            payload = {"id": "fixture-response", "status": "completed", "model": self.model.identifier,
                "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(self.response().structured)}]}],
                "usage": {"input_tokens": 40, "output_tokens": 20}}
            calls = []; connections = []
            def factory(*args):
                conn = GuardedConnection(FakeHTTPResponse(200, payload), calls, *args)
                if loss:
                    def connect(): AIModel.objects.filter(pk=self.model.pk).update(enabled=False)
                    conn.connect = connect
                connections.append(conn)
                return conn
            def transport(**kwargs):
                return adapters.post_json(**kwargs, resolver=lambda *args: ["93.184.216.34"], connection_factory=factory)
            def secret(*args, **kwargs):
                self.assertFalse(connection.in_atomic_block)
                self.assertEqual(AIUsageRecord.objects.get(job=job).status, "attempted")
                return "fixture-secret"
            def request(**kwargs): return adapters.create_response(**kwargs, transport=transport)
            with patch.object(adapters, "resolve_provider_secret", side_effect=secret), \
                 patch("socket.create_connection", side_effect=AssertionError("No actual network")):
                synthesis.execute_competitor_synthesis(job.pk, request=request)
            job.refresh_from_db(); self.assertEqual(job.status, "cancelled" if loss else "succeeded", job.error_category)
            sent = [call for call in calls if call[0] == "request"]
            self.assertEqual(len(sent), 0 if loss else 1)
            self.assertTrue(connections[0].closed)
            if not loss:
                body = json.loads(sent[0][3]["body"])
                self.assertIs(body["store"], False); self.assertNotIn("tools", body)
                self.assertEqual(body["text"]["format"]["schema"], synthesis.synthesis.OUTPUT_SCHEMA)
                self.assertEqual(self.read(job)["synthesis"]["comparison"]["current"]["job_id"], after.pk)
            AIModel.objects.filter(pk=self.model.pk).update(enabled=True)

    def test_manual_manager_queue_no_retry_schedule_and_final_private_byte_readback(self):
        before, after = self.pair()
        data = self.input_data(before, after)
        with self.assertRaises(PermissionDenied):
            synthesis.queue_competitor_synthesis(project=self.project, actor=self.foreign, data=data, idempotency_key="foreign")
        OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="member")
        with self.assertRaises(PermissionDenied): self.queue_synthesis(before, after)
        OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="admin")
        with self.assertRaises((PermissionDenied, ValidationError)):
            queue_job(project=self.project, actor=self.admin, handler=synthesis.HANDLER, input_snapshot=data,
                config_snapshot={}, idempotency_key="missing-config")
        job = self.queue_synthesis(before, after)
        for extra in ({"retry_of": job}, {"scheduled_for": timezone.now()}):
            with self.assertRaises(ValidationError):
                queue_job(project=self.project, actor=self.admin, handler=synthesis.HANDLER, input_snapshot=data,
                    config_snapshot=job.config_snapshot, idempotency_key="forbidden", **extra)
        with patch.object(synthesis, "read_project_artifact", return_value=b'{}'):
            synthesis.execute_competitor_synthesis(job.pk, request=self.request)
        job.refresh_from_db(); self.assertEqual(job.status, "failed")
        self.assertFalse(job.artifacts.exists()); self.assertFalse(job.output)
        self.assertEqual(job.usage.actual_units, 1)

    def test_broker_cancel_unknown_recovery_and_invalid_output_never_replay(self):
        before, after = self.pair()
        job = self.queue_synthesis(before, after)
        JobRun.objects.filter(pk=job.pk).update(dispatched_at=None)
        with patch("jobs.tasks.execute_competitor_synthesis_task.apply_async", side_effect=OperationalError("Fixture")):
            self.assertFalse(dispatch_pending(job.pk))
        with patch("jobs.tasks.execute_competitor_synthesis_task.apply_async") as task:
            self.assertTrue(dispatch_pending(job.pk)); self.assertFalse(dispatch_pending(job.pk)); task.assert_called_once()
        cancel_job(job=job, actor=self.admin)
        self.assertFalse(synthesis.execute_competitor_synthesis(job.pk, request=self.request))
        job.refresh_from_db(); self.assertEqual(job.usage.actual_units, 0)
        self.assertFalse(AIUsageRecord.objects.filter(job=job).exists())
        unknown = self.queue_synthesis(before, after, "unknown")
        unknown.status = "running"; unknown.save(update_fields=["status", "updated_at"])
        step = JobStep.objects.create(job=unknown, sequence=1, name=synthesis.STAGE, status="running",
            output={"method": synthesis.METHOD, "state": "attempted"})
        record_ai_attempt(job=unknown, step=step)
        JobRun.objects.filter(pk=unknown.pk).update(updated_at=timezone.now() - timedelta(seconds=200))
        self.assertEqual(reconcile_stuck_competitor_synthesis(), 1); self.assertEqual(reconcile_stuck_competitor_synthesis(), 0)
        unknown.refresh_from_db(); self.assertEqual((unknown.status, unknown.error_category, unknown.ai_usage_record.status),
            ("failed", "request_outcome_unknown", "unknown"))
        self.assertFalse(synthesis.execute_competitor_synthesis(unknown.pk, request=self.request))
        with self.assertRaises(ValidationError): retry_job(job=unknown, actor=self.admin, idempotency_key="retry")
        UsageReservation.objects.filter(job=unknown).update(state="reserved", actual_units=0, settled_at=None)
        self.assertEqual(reconcile_usage(), 1); unknown.refresh_from_db(); self.assertEqual(unknown.usage.actual_units, 1)
        invalid = self.queue_synthesis(before, after, "invalid")
        response = self.response()
        response.structured["interpretations"][0]["quote"] = "foreign evidence"
        synthesis.execute_competitor_synthesis(invalid.pk, request=lambda **kwargs: response)
        invalid.refresh_from_db(); self.assertEqual(invalid.status, "failed")
        self.assertEqual(invalid.ai_usage_record.status, "completed")  # Provider completion is not usable output.
        self.assertFalse(invalid.artifacts.exists())
        failed = self.queue_synthesis(before, after, "provider-error")
        def provider_error(**kwargs): raise ProviderRequestError("secret untrusted category", answer_text="private", request_id="safe-id")
        synthesis.execute_competitor_synthesis(failed.pk, request=provider_error)
        failed.refresh_from_db(); self.assertEqual((failed.error_category, failed.ai_usage_record.status), ("provider_unavailable", "unknown"))

    def test_storage_insertion_settlement_metadata_losses_roll_back_private_evidence(self):
        before, after = self.pair()
        for point in ("storage", "step", "artifact", "citation", "ai", "usage", "settlement"):
            job = self.queue_synthesis(before, after, "private-" + point)
            def revoke(): OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer")
            if point == "storage":
                def save(**kwargs):
                    key = save_project_artifact(**kwargs); revoke(); return key
                context = patch.object(synthesis, "save_project_artifact", side_effect=save)
            else:
                original_settle = synthesis.settle_usage
                def settle(**kwargs):
                    result = original_settle(**kwargs)
                    if kwargs["job"].status == "succeeded":
                        if point == "step": JobStep.objects.filter(job=job).update(created_at=timezone.now())
                        elif point == "artifact": Artifact.objects.filter(job=job).update(size_bytes=1)
                        elif point == "citation": SourceCitation.objects.filter(job=job).update(observed_at=timezone.now())
                        elif point == "ai": AIUsageRecord.objects.filter(job=job).update(finished_at=timezone.now())
                        elif point == "usage": UsageReservation.objects.filter(job=job).update(settled_at=timezone.now() + timedelta(days=1))
                        else: revoke()
                    return result
                context = patch.object(synthesis, "settle_usage", side_effect=settle)
            with context: synthesis.execute_competitor_synthesis(job.pk, request=self.request)
            job.refresh_from_db(); self.assertIn(job.status, {"failed", "cancelled"}, point)
            self.assertFalse(job.output); self.assertFalse(job.artifacts.exists()); self.assertEqual(job.usage.actual_units, 1)
            self.assertEqual(OrganizationMembership.objects.get(pk=self.membership.pk).role, "viewer" if point == "storage" else "admin")
            OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="admin")

    def test_current_independent_reader_full_metadata_and_private_integrity_loss(self):
        before, after = self.pair()
        job = self.queue_synthesis(before, after)
        synthesis.execute_competitor_synthesis(job.pk, request=self.request); job.refresh_from_db()
        expected = self.read(job)
        for mutation in (lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer"),
            lambda: OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer"),
            lambda: Artifact.objects.filter(job=before).update(created_at=timezone.now()),
            lambda: AIUsageRecord.objects.filter(job=job).update(attempted_at=timezone.now()),
            lambda: SourceCitation.objects.filter(job=job).update(source_title="changed"),
            lambda: ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)):
            with transaction.atomic():
                def read(**kwargs):
                    content = read_project_artifact(**kwargs); mutation(); return content
                with patch.object(synthesis, "read_project_artifact", side_effect=read), self.assertRaises((PermissionDenied, ValidationError)):
                    self.read(job)
                transaction.set_rollback(True)
        self.assertEqual(self.read(job), expected)
        with self.assertRaises(PermissionDenied): self.read(job, self.foreign)
        with project_artifact_barrier(self.project.organization_id, shared=True):
            key = save_project_artifact(project=self.project, content=b'{"raw_document":"private"}', content_type="application/json")
        Artifact.objects.filter(job=job).update(key=key)
        with self.assertRaises(ValidationError): self.read(job)

    def test_final_unchanged_own_metadata_fences_delivery_and_committed_capture_authority(self):
        before, after = self.pair()
        reader = get_user_model().objects.create_user("third-synthesis-reader@example.invalid", "test-password")
        EmailAddress.objects.create(user=reader, email=reader.email, verified=True, primary=True)
        membership = OrganizationMembership.objects.create(organization=self.organization, user=reader, role="admin")
        self.assertEqual(len({before.actor_id, self.admin.pk, reader.pk}), 3)
        healthy = self.queue_synthesis(before, after, "final-own-healthy")
        self.assertTrue(synthesis.execute_competitor_synthesis(healthy.pk, request=self.request))
        healthy.refresh_from_db(); self.assertEqual(healthy.status, "succeeded", healthy.error_category)
        expected = self.read(healthy, reader)
        metadata, private_read = synthesis._read_metadata, synthesis.read_competitor_synthesis
        trial = OrganizationTrial.objects.get(organization=self.organization)
        losses = ("collector", "synthesis-actor", "revision", "approval-list", "first-cancel", "own-cancel",
            "model", "account", "organization", "expiry")
        for phase in ("delivery", "capture"):
            for loss in losses + (("caller", "caller-role") if phase == "delivery" else ()):
                job = healthy if phase == "delivery" else self.queue_synthesis(before, after, "final-own-" + loss)
                now = [timezone.now()]; ends = now[0] + timedelta(seconds=20)
                OrganizationTrial.objects.filter(pk=trial.pk).update(started_at=ends - timedelta(days=30), ends_at=ends)
                boundary = {"reader_returned": False, "reads": 0, "injected": False}
                def read_private(**kwargs):
                    result = private_read(**kwargs)
                    boundary["reader_returned"] = True
                    return result
                def last_metadata(job_id):
                    result = metadata(job_id)
                    boundary["reads"] += 1
                    final = boundary["reader_returned"] if phase == "capture" else boundary["reads"] == 2
                    if final and not boundary["injected"]:
                        self.assertEqual(result["job"]["status"], "succeeded")
                        self.assertEqual(result["usage"]["state"], "settled")
                        self.assertEqual(len(result["artifacts"]), 1)
                        boundary["injected"] = True
                        if loss == "collector": OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
                        elif loss == "synthesis-actor": OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer")
                        elif loss == "caller": OrganizationMembership.objects.filter(pk=membership.pk).update(role="viewer")
                        elif loss == "caller-role": OrganizationMembership.objects.filter(pk=membership.pk).update(role="owner")
                        elif loss == "revision": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)
                        elif loss == "approval-list": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[self.data["origin"]])
                        elif loss == "first-cancel": JobCancellation.objects.create(job=before, requested_by=self.owner)
                        elif loss == "own-cancel": JobCancellation.objects.create(job=job, requested_by=self.admin)
                        elif loss == "model": AIModel.objects.filter(pk=self.model.pk).update(enabled=False)
                        elif loss == "account": AIProviderAccount.objects.filter(pk=self.account.pk).update(state="revoked", revoked_at=now[0])
                        elif loss == "organization": Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True)
                        else: now[0] = ends
                    return result
                with self.subTest(phase=phase, loss=loss):
                    with (transaction.atomic() if phase == "delivery" else nullcontext()), \
                         patch.object(synthesis, "_read_metadata", side_effect=last_metadata), \
                         patch.object(synthesis, "read_competitor_synthesis", side_effect=read_private), \
                         patch("jobs.usage.timezone.now", side_effect=lambda: now[0]), \
                         patch("socket.create_connection", side_effect=AssertionError("No actual provider")):
                        if phase == "delivery":
                            with self.assertRaises((PermissionDenied, ValidationError, UsageLimitError)): self.read(job, reader)
                            transaction.set_rollback(True)
                        else:
                            with patch.object(self, "request", wraps=self.request) as request:
                                self.assertTrue(synthesis.execute_competitor_synthesis(job.pk, request=request))
                                request.assert_called_once()
                            job.refresh_from_db(); self.assertIn(job.status, {"failed", "cancelled"})
                            self.assertFalse(job.output); self.assertFalse(job.artifacts.exists()); self.assertFalse(job.citations.exists())
                            self.assertEqual((job.usage.state, job.usage.actual_units), ("settled", 1))
                            self.assertEqual(AIUsageRecord.objects.filter(job=job).count(), 1)
                            with patch.object(self, "request", side_effect=AssertionError("No replay")) as request:
                                self.assertFalse(synthesis.execute_competitor_synthesis(job.pk, request=request))
                        self.assertTrue(boundary["injected"])
                OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="owner")
                OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="admin")
                OrganizationMembership.objects.filter(pk=membership.pk).update(role="admin")
                ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=self.configuration.revision,
                    competitor_origins=self.configuration.competitor_origins)
                JobCancellation.objects.filter(job__in=[before, job]).delete()
                AIModel.objects.filter(pk=self.model.pk).update(enabled=True)
                AIProviderAccount.objects.filter(pk=self.account.pk).update(state="active", revoked_at=None)
                Organization.objects.filter(pk=self.organization.pk).update(is_suspended=False)
                OrganizationTrial.objects.filter(pk=trial.pk).update(started_at=trial.started_at, ends_at=trial.ends_at)
        self.assertEqual(self.read(healthy, reader), expected)
        final = self.queue_synthesis(before, after, "final-own-positive-after")
        self.assertTrue(synthesis.execute_competitor_synthesis(final.pk, request=self.request))
        final.refresh_from_db(); self.assertEqual(final.status, "succeeded", final.error_category)
        self.assertEqual(self.read(final, reader)["synthesis"]["comparison"], expected["synthesis"]["comparison"])

    def test_outer_atomic_concurrent_queue_and_duplicate_recovery_during_committed_request(self):
        before, after = self.pair()
        job = self.queue_synthesis(before, after)
        with transaction.atomic(), self.assertRaises(ValidationError): synthesis.execute_competitor_synthesis(job.pk, request=self.request)
        self.assertFalse(job.steps.exists())
        barrier = Barrier(2)
        def queue():
            close_old_connections()
            try:
                barrier.wait(timeout=20)
                return synthesis.queue_competitor_synthesis(project=self.project, actor=self.admin,
                    data=self.input_data(before, after), idempotency_key="concurrent").pk
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(lambda _: queue(), range(2)))
        self.assertEqual(ids[0], ids[1])
        started, release = Event(), Event()
        def request(**kwargs):
            started.set()
            if not release.wait(timeout=30): raise AssertionError("Fixture release missing")
            return self.response()
        def execute():
            close_old_connections()
            try: return synthesis.execute_competitor_synthesis(job.pk, request=request)
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(execute)
            try:
                self.assertTrue(started.wait(timeout=30))
                JobRun.objects.filter(pk=job.pk).update(updated_at=timezone.now() - timedelta(seconds=200))
                self.assertEqual(reconcile_stuck_competitor_synthesis(), 0)
                self.assertFalse(synthesis.execute_competitor_synthesis(job.pk, request=self.request))
            finally: release.set()
            self.assertTrue(future.result(timeout=60))
        job.refresh_from_db(); self.assertEqual(job.status, "succeeded", job.error_category)
        from .tasks import execute_competitor_synthesis_task
        with patch.object(synthesis, "execute_competitor_synthesis", return_value=False) as handler:
            self.assertFalse(execute_competitor_synthesis_task.run(job.pk)); handler.assert_called_once_with(job.pk)
        self.assertEqual(execute_competitor_synthesis_task.max_retries, 0)

    def test_historical_customer_exports_retained_copies_and_child_first_erasure(self):
        from tenancy.customer_export import complete_bounded_customer_archive
        from tenancy.customer_inventory import CUSTOMER
        from tenancy.customer_snapshot import reserve_bounded_customer_snapshot, capture_reserved_customer_snapshot, private_snapshot_part
        from tenancy.customer_source_parts import capture_source_stage
        from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        before, after = self.pair()
        job = self.queue_synthesis(before, after)
        synthesis.execute_competitor_synthesis(job.pk, request=self.request); job.refresh_from_db()
        artifact = job.artifacts.get(); content = read_project_artifact(project=self.project, key=artifact.key)
        with ZipFile(io.BytesIO(complete_bounded_customer_archive(organization=self.organization, actor=self.owner))) as archive:
            row = next(row for row in json.loads(archive.read("records/jobs/JobRun.json")) if row["id"] == job.pk)
            self.assertEqual(row["scope"], "historical_original_static_facts_and_unverified_ai_notes_not_current_use_or_human_approval")
            self.assertEqual(row["output"], job.output); self.assertIn(content, [archive.read(name) for name in archive.namelist()])
            # Existing AI/units observations are RESTRICTED operational history, not CUSTOMER exports.
            self.assertNotIn("records/jobs/AIUsageRecord.json", archive.namelist())
            self.assertEqual(AIUsageRecord.objects.filter(job=job).count(), 1)
        bounded = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner, request_key="a" * 32)
        self.assertTrue(capture_reserved_customer_snapshot(bounded.pk))
        retained, _ = private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=bounded.pk, position=0)
        ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[])
        with self.assertRaises((PermissionDenied, ValidationError)): self.read(job)
        self.assertEqual(private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=bounded.pk, position=0)[0], retained)
        sequential = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner, request_key="b" * 32, format="source-parts-v2")
        for _ in range(len(CUSTOMER) * 2 + 10):
            sequential.refresh_from_db()
            if sequential.state != sequential.State.PREPARING: break
            self.assertTrue(capture_source_stage(sequential.pk, sequential.progress.get("step", 0)))
        sequential.refresh_from_db(); self.assertEqual(sequential.state, sequential.State.READY)
        now = timezone.now()
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now - timedelta(days=121), ends_at=now - timedelta(days=91))
        with self.assertRaises(PermissionDenied): private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=bounded.pk, position=0)
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=now)
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.organization))
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(JobRun.objects.filter(pk=job.pk).exists()); self.assertFalse(AIUsageRecord.objects.filter(job_id=job.pk).exists())
