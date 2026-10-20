from tenancy.customer_artifact_barrier import project_artifact_barrier
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
import json
import os
from unittest.mock import patch
from zipfile import ZipFile

from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from kombu.exceptions import OperationalError

from config.test_foundations import TEST_STORAGES
from tenancy.artifacts import read_project_artifact, save_project_artifact
from tenancy.models import OrganizationMembership, OrganizationTrial, Project
from tenancy.services import update_project_configuration
from . import test_authority_link_sources as source_fixtures
from . import test_crawling as transport_fixtures
from .authority_link_collection import (COLLECTION_METHOD, HANDLER, STAGE, execute_static_link_collection,
    compare_static_link_observations, queue_static_link_collection, read_static_destination_candidate,
    read_static_link_observation, read_static_mention_candidate, selection_snapshot, validate_job,
    REFERENCE_COLLECTION_METHOD, REFERENCE_METHOD, validate_result)
from .crawling import CrawlScope, SafeFetcher
from .models import Artifact, JobRun, JobStatus, JobStep, UsageReservation
from .recovery import reconcile_stuck_static_link_sources
from .services import cancel_job, create_job, dispatch_pending, queue_job, retry_job
from .usage import UsageLimitError, reconcile_usage


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}), DEBUG=True)
class StaticLinkCollectionTests(source_fixtures.StaticSourceFixture, TransactionTestCase):
    def source_job(self, key="static-source-request", **changes):
        with patch("jobs.tasks.execute_static_link_collection_task.apply_async") as dispatch:
            job = queue_static_link_collection(**{**dict(project=self.project, actor=self.owner,
                data={"link_review_id": self.approved.pk, "source_collection_permission": True}, idempotency_key=key), **changes})
        self.dispatch = dispatch
        return job

    def transport(self, *, denied=False, on_request=None, html_body=None):
        self.requests = []
        responses = [transport_fixtures.FakeResponse(200, b"User-agent: *\nDisallow: /" if denied else b"User-agent: *\nDisallow:\n",
            {"Content-Type": "text/plain"}), transport_fixtures.FakeResponse(200,
            html_body if html_body is not None else (f'<p>Private unrelated fixture-contact@example.invalid</p><a href="{self.data["target_url"]}" rel="nofollow">Target only</a>').encode(),
            {"Content-Type": "text/html"})]

        def factory(*_args):
            self.requests.append(len(self.requests) + 1)
            if on_request:
                on_request(len(self.requests))
            return transport_fixtures.FakeConnection(responses.pop(0))

        return SafeFetcher(CrawlScope(frozenset({"publisher.example.invalid"})), timeout=8, max_redirects=2,
            max_bytes=128 * 1024, resolver=lambda *_args: ["93.184.216.34"], connection_factory=factory)

    def read(self, job, **changes):
        return read_static_link_observation(**{**dict(project=self.project, actor=self.owner, job_id=job.pk), **changes})

    def test_actual_queue_once_only_execution_minimized_artifact_citation_readback_and_settled_unit(self):
        job = self.source_job()
        self.dispatch.assert_called_once_with(args=[job.pk], queue="crawl", task_id=f"job-{job.pk}", retry=False)
        self.assertEqual(job.usage.provider, "authority_source")
        self.assertEqual(job.usage.reserved_units, 1)
        self.assertEqual(self.source_job().pk, job.pk)
        self.dispatch.assert_not_called()
        transport = self.transport()
        self.assertTrue(execute_static_link_collection(job.pk, fetcher=transport))
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.SUCCEEDED)
        self.assertEqual(len(self.requests), 2)
        self.assertFalse(execute_static_link_collection(job.pk, fetcher=transport))
        self.assertEqual(len(self.requests), 2)
        result = self.read(job)
        self.assertEqual(result["collection"]["evidence"]["matching_links"][0]["anchor_text"], "Target only")
        artifact = job.artifacts.get()
        content = read_project_artifact(project=self.project, key=artifact.key)
        self.assertNotIn(b"fixture-contact", content)
        self.assertNotIn(b"<a", content)
        self.assertEqual(json.loads(content), result["collection"])
        self.assertEqual(job.usage.actual_units, 1)
        self.assertEqual(job.usage.state, UsageReservation.State.SETTLED)
        with self.assertRaises(ValidationError): retry_job(job=job, actor=self.owner, idempotency_key="no-replay")
        job.output = {**job.output, "raw_html": "Unrelated retained body"}
        with self.assertRaises(ValidationError): job.save()
        step = job.steps.get(); step.output = {"raw_html": "No raw output"}
        with self.assertRaises(ValidationError): step.save()

    def test_actual_foreign_scope_separate_permission_direct_queue_and_model_snapshot_retry_schedule_denials(self):
        data = {"link_review_id": self.approved.pk, "source_collection_permission": True}
        config = selection_snapshot(self.project, self.owner, data)
        for changes in ({"source_collection_permission": False}, {"link_review_id": True}, {"url": self.data["source_url"]}):
            with self.assertRaises(ValidationError): self.source_job(data={**data, **changes})
        foreign = Project.objects.create(organization=self.organization, name="Synthetic foreign collection", canonical_origin="https://foreign.example.invalid")
        with self.assertRaises(PermissionDenied): self.source_job(project=foreign)
        for altered in ({}, {**config, "binding": {**config["binding"], "target_url": "https://own.example.invalid/other"}}):
            with self.assertRaises((ValidationError, PermissionDenied)):
                queue_job(project=self.project, actor=self.owner, handler=HANDLER, input_snapshot=data,
                    config_snapshot=altered, idempotency_key="generic-current-selection")
        first = self.source_job()
        with self.assertRaises(ValidationError):
            create_job(project=self.project, actor=self.owner, handler=HANDLER, input_snapshot=data,
                config_snapshot=config, idempotency_key="direct-retry", retry_of=first)
        with self.assertRaises(ValidationError):
            JobRun.objects.create(project=self.project, organization=self.organization, actor=self.owner, handler=HANDLER,
                method_version=COLLECTION_METHOD, input_snapshot=data, config_snapshot=config, scheduled_for=timezone.now())
        self.assertEqual(JobRun.objects.filter(handler=HANDLER).count(), 1)

    def test_dispatch_broker_recovery_current_source_loss_and_prestart_cancel_release_without_network(self):
        job = self.source_job()
        JobRun.objects.filter(pk=job.pk).update(dispatched_at=None)
        with patch("jobs.tasks.execute_static_link_collection_task.apply_async", side_effect=OperationalError("Fixture no broker")):
            self.assertFalse(dispatch_pending(job.pk))
        job.refresh_from_db(); self.assertEqual(job.dispatch_error, "broker_unavailable")
        with patch("jobs.tasks.execute_static_link_collection_task.apply_async") as task:
            self.assertTrue(dispatch_pending(job.pk))
            self.assertFalse(dispatch_pending(job.pk))
            task.assert_called_once()
        cancelled = self.source_job("static-source-cancel")
        cancel_job(job=cancelled, actor=self.owner)
        transport = self.transport()
        self.assertFalse(execute_static_link_collection(cancelled.pk, fetcher=transport))
        self.assertEqual(self.requests, [])
        cancelled.refresh_from_db(); self.assertEqual(cancelled.usage.state, UsageReservation.State.RELEASED)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
        JobRun.objects.filter(pk=job.pk).update(dispatched_at=None)
        with patch("jobs.tasks.execute_static_link_collection_task.apply_async") as task:
            self.assertFalse(dispatch_pending(job.pk)); task.assert_not_called()
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.CANCELLED)
        self.assertEqual(job.usage.actual_units, 0)

    def test_commercial_internal_budget_and_expiry_mid_request_cancel_without_delivering_evidence(self):
        with override_settings(INTERNAL_PROJECT_MONTHLY_UNITS=2):
            with self.assertRaises(UsageLimitError): self.source_job()
        self.assertFalse(JobRun.objects.filter(handler=HANDLER).exists())
        job = self.source_job()
        def expire(count):
            if count == 1:
                start = timezone.now() - timedelta(days=31)
                OrganizationTrial.objects.filter(organization=self.organization).update(started_at=start, ends_at=start + timedelta(days=30))
        transport = self.transport(on_request=expire)
        execute_static_link_collection(job.pk, fetcher=transport)
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.CANCELLED)
        self.assertEqual(job.error_category, "trial_unavailable")
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(job.output, {})
        self.assertFalse(job.artifacts.exists())
        self.assertEqual(job.usage.actual_units, 1)
        with self.assertRaises(UsageLimitError): self.source_job("no-cost-after-expiry")

    def test_denied_robots_failed_attempt_and_unknown_running_recovery_never_replay_and_settle_once(self):
        job = self.source_job()
        transport = self.transport(denied=True)
        self.assertTrue(execute_static_link_collection(job.pk, fetcher=transport))
        job.refresh_from_db(); self.assertEqual(job.status, JobStatus.FAILED)
        self.assertEqual(job.error_category, "static_source_robots_denied")
        self.assertEqual(job.usage.actual_units, 1)
        self.assertEqual(len(self.requests), 1)
        with self.assertRaises(ValidationError): retry_job(job=job, actor=self.owner, idempotency_key="no-auto-replay")
        unknown = self.source_job("unknown-static-source")
        unknown.status = JobStatus.RUNNING; unknown.save(update_fields=["status", "updated_at"])
        JobStep.objects.create(job=unknown, sequence=1, name=STAGE, status=JobStep.Status.RUNNING,
            output={"method": unknown.method_version, "state": "attempted"})
        JobRun.objects.filter(pk=unknown.pk).update(updated_at=timezone.now() - timedelta(seconds=120))
        with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("Unknown attempt cannot replay")):
            self.assertEqual(reconcile_stuck_static_link_sources(), 1)
            self.assertEqual(reconcile_stuck_static_link_sources(), 0)
            self.assertFalse(execute_static_link_collection(unknown.pk))
        unknown.refresh_from_db()
        self.assertEqual(unknown.status, JobStatus.FAILED)
        self.assertEqual(unknown.error_category, "request_outcome_unknown")
        self.assertEqual(unknown.usage.actual_units, 1)
        self.assertFalse(unknown.artifacts.exists())
        UsageReservation.objects.filter(job=unknown).update(state="reserved", actual_units=0, settled_at=None)
        self.assertEqual(reconcile_usage(), 1)
        unknown.refresh_from_db(); self.assertEqual(unknown.usage.actual_units, 1)

    def test_private_readback_tamper_foreign_scope_and_source_role_loss_deny_current_use_and_generic_status_is_metadata_only(self):
        job = self.source_job()
        self.assertTrue(execute_static_link_collection(job.pk, fetcher=self.transport()))
        job.refresh_from_db()
        validate_job(job, current=True)
        original = self.read(job)
        from .api import _job_payload
        payload = _job_payload(job, detailed=True)
        self.assertFalse({"output", "steps", "citations", "artifacts"} & set(payload))
        foreign = Project.objects.create(organization=self.organization, name="Synthetic foreign readback", canonical_origin="https://other.example.invalid")
        with self.assertRaises(PermissionDenied): self.read(job, project=foreign)
        artifact = job.artifacts.get()
        with project_artifact_barrier(self.project.organization_id, shared=True):
            key = save_project_artifact(project=self.project, content=b'{"raw_html":"tamper"}', content_type="application/json")
        Artifact.objects.filter(pk=artifact.pk).update(key=key, size_bytes=len(b'{"raw_html":"tamper"}'))
        with self.assertRaises(ValidationError): self.read(job)
        Artifact.objects.filter(pk=artifact.pk).update(key=artifact.key, size_bytes=artifact.size_bytes)
        self.assertEqual(self.read(job), original)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
        with self.assertRaises(PermissionDenied): self.read(job)

    def test_source_role_revocation_during_private_storage_write_discards_artifact_and_settles_attempt(self):
        job = self.source_job()
        def save_then_revoke(**kwargs):
            key = save_project_artifact(**kwargs)
            OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
            return key
        with patch("jobs.authority_link_collection.save_project_artifact", side_effect=save_then_revoke):
            self.assertTrue(execute_static_link_collection(job.pk, fetcher=self.transport()))
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.CANCELLED)
        self.assertEqual(job.error_category, "source_scope_changed")
        self.assertEqual(job.output, {})
        self.assertFalse(job.artifacts.exists())
        self.assertEqual(job.usage.actual_units, 1)

    def test_revocation_during_dns_or_connected_tls_prevents_get_and_uncertain_replay(self):
        for point in ("dns", "tls"):
            job = self.source_job("static-pre-send-" + point)
            transport = self.transport()
            get_requests = []
            factory = transport.connection_factory
            def revoke():
                OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
            if point == "dns":
                def resolver(*_args):
                    revoke()
                    return ["93.184.216.34"]
                transport.resolver = resolver
            def connected_factory(*args):
                conn = factory(*args)
                request = conn.request
                def send(*request_args, **kwargs):
                    get_requests.append(request_args)
                    return request(*request_args, **kwargs)
                conn.request = send
                if point == "tls":
                    conn.connect = revoke
                return conn
            transport.connection_factory = connected_factory
            self.assertTrue(execute_static_link_collection(job.pk, fetcher=transport))
            job.refresh_from_db()
            self.assertEqual(get_requests, [])
            self.assertEqual(job.status, JobStatus.CANCELLED)
            self.assertEqual(job.error_category, "source_scope_changed")
            self.assertEqual(job.output, {})
            self.assertFalse(job.artifacts.exists())
            self.assertEqual(job.usage.actual_units, 1)
            self.assertFalse(execute_static_link_collection(job.pk, fetcher=transport))
            self.assertEqual(get_requests, [])
            OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="owner")

    def test_actual_derived_job_bounded_stored_sequential_exports_retention_closure_and_deletion(self):
        from tenancy.customer_export import complete_bounded_customer_archive
        from tenancy.customer_inventory import CUSTOMER
        from tenancy.customer_snapshot import reserve_bounded_customer_snapshot, capture_reserved_customer_snapshot, private_snapshot_part
        from tenancy.customer_source_parts import capture_source_stage
        from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        from tenancy.models import Organization
        from tenancy.services import revoke_origin_verification
        job = self.source_job()
        self.assertTrue(execute_static_link_collection(job.pk, fetcher=self.transport()))
        job.refresh_from_db()
        artifact = job.artifacts.get()
        original = read_project_artifact(project=self.project, key=artifact.key)
        with ZipFile(BytesIO(complete_bounded_customer_archive(organization=self.organization, actor=self.owner))) as archive:
            rows = json.loads(archive.read("records/jobs/JobRun.json"))
            row = next(row for row in rows if row["id"] == job.pk)
            self.assertEqual(row["output"], job.output)
            self.assertNotIn(b"fixture-contact", json.dumps(rows).encode())
            self.assertIn(original, [archive.read(name) for name in archive.namelist()])
        with patch("tenancy.tasks.capture_customer_snapshot_task.apply_async"):
            bounded = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner, request_key="e" * 32)
            self.assertTrue(capture_reserved_customer_snapshot(bounded.pk))
            retained, _ = private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=bounded.pk, position=0)
            revoke_origin_verification(verification=self.verification, user=self.owner)
            with self.assertRaises(PermissionDenied): self.read(job)
            self.assertEqual(private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=bounded.pk, position=0)[0], retained)
            sequential = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner,
                request_key="f" * 32, format="source-parts-v2")
            for _ in range(len(CUSTOMER) * 2 + 10):
                sequential.refresh_from_db()
                if sequential.state != sequential.State.PREPARING:
                    break
                self.assertTrue(capture_source_stage(sequential.pk, sequential.progress.get("step", 0)))
            sequential.refresh_from_db(); self.assertEqual(sequential.state, sequential.State.READY)
            part = sequential.parts.filter(source__model="jobs.JobRun").first()
            data, _ = private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=sequential.pk, position=part.position)
            with ZipFile(BytesIO(data)) as archive:
                rows = json.loads(archive.read("data"))
                self.assertEqual(next(row for row in rows if row["id"] == job.pk)["output"], job.output)
        now = timezone.now()
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now - timedelta(days=121), ends_at=now - timedelta(days=91))
        with self.assertRaises(PermissionDenied):
            private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=bounded.pk, position=0)
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=now)
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.organization))
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(JobRun.objects.filter(pk=job.pk).exists())
        self.assertFalse(Artifact.objects.filter(pk=artifact.pk).exists())


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json"}), DEBUG=True)
class StaticLinkComparisonTests(source_fixtures.StaticSourceFixture, TransactionTestCase):
    source_job = StaticLinkCollectionTests.source_job
    transport = StaticLinkCollectionTests.transport

    def collected(self, key, body=None):
        job = self.source_job(key)
        self.assertTrue(execute_static_link_collection(job.pk, fetcher=self.transport(html_body=body)))
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.SUCCEEDED)
        # Keep the following no-write capture complete despite this fixture's
        # repeated full current-source readbacks under DEBUG query logging.
        connection.queries_log.clear()
        return job

    def compare(self, previous, current, **changes):
        return compare_static_link_observations(**{**dict(project=self.project, actor=self.owner,
            previous_job_id=previous.pk, current_job_id=current.pk), **changes})

    def test_actual_dated_same_source_not_observed_again_is_only_a_candidate_with_no_write_or_network(self):
        previous = self.collected("dated-static-before")
        current = self.collected("dated-static-after", b"<p>Bounded static document with no selected absolute target markup</p>")
        with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("Comparison cannot fetch")), CaptureQueriesContext(connection) as queries:
            result = self.compare(previous, current)
        self.assertFalse(any(source_fixtures.re.match(r"\s*(INSERT|UPDATE|DELETE)\b", row["sql"], source_fixtures.re.I) for row in queries))
        self.assertTrue(result["comparable"])
        self.assertEqual(result["state"], "target_markup_not_observed_again_candidate_not_verified_link_loss")
        self.assertEqual(result["previous"]["observed_at"], previous.output["observed_at"])
        self.assertEqual(result["current"]["observed_at"], current.output["observed_at"])
        self.assertEqual(result["unlinked_or_lost_link"], "not_established")
        self.assertTrue(result["body_changed"])
        self.assertNotIn("fixture-contact", json.dumps(result))
        self.assertEqual(result["previous"]["matching_target_count"], 1)
        self.assertEqual(result["current"]["matching_target_count"], 0)
        for first, second in ((previous, previous), (current, previous)):
            with self.assertRaises(ValidationError): self.compare(first, second)
        with self.assertRaises(ValidationError): self.compare(previous, current, previous_job_id=True)
        foreign = Project.objects.create(organization=self.organization, name="Synthetic foreign comparison", canonical_origin="https://foreign.example.invalid")
        with self.assertRaises(PermissionDenied): self.compare(previous, current, project=foreign)
        original = current.artifacts.get()
        Artifact.objects.filter(pk=original.pk).update(project=foreign)
        with self.assertRaises(ValidationError): self.compare(previous, current)
        Artifact.objects.filter(pk=original.pk).update(project=self.project)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
        with self.assertRaises(PermissionDenied): self.compare(previous, current)

    def test_real_ambiguous_truncated_and_different_final_source_coverage_never_become_comparable_loss(self):
        previous = self.collected("static-history-positive")
        for key, body in (("static-history-ambiguous", b"<template>Unclosed"),
            ("static-history-truncated", (f'<a href="{self.data["target_url"]}">{"x" * 241}</a>').encode()),
            ("static-history-inventory", b'<a href="/other">Other</a>' * 1001)):
            current = self.collected(key, body)
            result = self.compare(previous, current)
            self.assertFalse(result["comparable"])
            self.assertEqual(result["state"], "incomparable_ambiguous_or_truncated_coverage")
            self.assertEqual(result["unlinked_or_lost_link"], "not_established")
        current = self.source_job("static-history-redirect")
        transport = self.transport()
        normal_factory = transport.connection_factory
        calls = 0
        def redirect(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                return transport_fixtures.FakeConnection(transport_fixtures.FakeResponse(302, headers={"Location": "/different-final"}))
            return normal_factory(*args)
        transport.connection_factory = redirect
        self.assertTrue(execute_static_link_collection(current.pk, fetcher=transport))
        current.refresh_from_db(); self.assertEqual(current.status, JobStatus.SUCCEEDED, current.error_category)
        with self.assertRaises(ValidationError): self.compare(previous, current)


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json"}), DEBUG=True)
class StaticMentionCandidateTests(source_fixtures.StaticSourceFixture, TransactionTestCase):
    source_job = StaticLinkCollectionTests.source_job
    transport = StaticLinkCollectionTests.transport

    def setUp(self):
        source_fixtures.StaticSourceFixture.setUp(self)
        from providers.models import AIModelCapability, AIProvider
        from providers.services import configure_model, create_provider, create_provider_account
        config = update_project_configuration(project=self.project, user=self.owner, expected_revision=2,
            changes={"target_country": "Türkiye", "target_languages": ["en"]})
        self.data["configuration_revision"] = config.revision
        draft = self.record(request_key="body-match-current-link")
        self.approved = self.transition(self.transition(draft, "review"), "approved")
        operator = get_user_model().objects.create_superuser("body-match-staff@example.invalid", "fixture-password")
        provider = create_provider(actor=operator, key="mention-fixture", name="Mention fixture", kind=AIProvider.Kind.OPENAI, enabled=True)
        account = create_provider_account(actor=operator, provider=provider, label="Fixture only", secret_reference="env:OPENAI_API_KEY")
        model = configure_model(actor=operator, provider=provider, identifier="mention-fixture", name="Mention fixture",
            capabilities=[AIModelCapability.TEXT_GENERATION, AIModelCapability.STRUCTURED_OUTPUT], max_output_tokens=2048,
            capability_source="https://provider.example.invalid/models", capabilities_verified_at=timezone.now(),
            input_price_usd_per_million=Decimal("0.1"), output_price_usd_per_million=Decimal("1"),
            pricing_source="https://provider.example.invalid/prices", pricing_verified_at=timezone.now(), access_tier="standard", enabled=True)
        self.research_data = {"topic": "Human mention candidate review", "mapping_id": None, "language": "en",
            "source_urls": [self.data["source_url"]], "model_id": model.pk, "account_id": account.pk,
            "max_output_tokens": 512, "max_cost_usd": "0.1", "allow_free": False}

    def sources(self, key, body=b"<p>Evidence useful.</p><p>Unrelated private fixture-contact@example.invalid</p>"):
        from .authority import POLICY, record_authority_prospect
        from .crawling import FetchResponse
        from .research import execute_research, queue_research
        with patch("jobs.tasks.execute_research_task.apply_async"):
            research = queue_research(project=self.project, actor=self.owner, data=self.research_data, idempotency_key=key + "-research")
        class Fetcher:
            def fetch(inner, url, *, before_request):
                before_request(url)
                return FetchResponse(url=url, status=200, headers={"content-type": "text/html"}, body=body)
        def no_synthesis(**_kwargs):
            raise ValidationError("Fixture source stays actual partial; no AI output required.")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-not-real"}):
            self.assertTrue(execute_research(research.pk, fetcher=Fetcher(), request=no_synthesis))
        research.refresh_from_db(); self.assertEqual(research.status, JobStatus.PARTIALLY_SUCCEEDED)
        intake = {"policy": POLICY, "research_job_id": research.pk, "source_index": 0, "quote": "Evidence useful.",
            "relevance": "Human selected mention candidate; not automatic brand classification.", "proposed_action": "mention",
            "target_url": self.data["source_url"], "draft_text": "Human reviewed mention discussion, not a site change.",
            "use_permission": True, "storage_permission": True, "outreach_permission": True}
        row = record_authority_prospect(project=self.project, actor=self.owner, request_key=key + "-draft", intake=intake,
            assignee_id=self.owner.pk, state="draft", reason="Human-selected quote.")
        draft = row
        for state in ("review", "approved"):
            row = record_authority_prospect(project=self.project, actor=self.owner, request_key=key + "-" + state,
                intake=intake, assignee_id=self.owner.pk, state=state, reason="Exact human judgment.",
                prospect_id=row.prospect_id, expected_revision=row.revision)
        static = self.source_job(key + "-static")
        self.assertTrue(execute_static_link_collection(static.pk, fetcher=self.transport(html_body=body)))
        static.refresh_from_db(); self.assertEqual(static.status, JobStatus.SUCCEEDED)
        connection.queries_log.clear()
        return row, static, draft

    def candidate(self, row, static, **changes):
        return read_static_mention_candidate(**{**dict(project=self.project, actor=self.owner,
            prospect_review_id=row.pk, static_job_id=static.pk), **changes})

    def test_actual_human_approved_quote_same_body_static_candidate_without_sql_write_network_or_unlinked_proof(self):
        row, static, draft = self.sources("mention-actual")
        with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No network")), patch(
            "jobs.research.create_response", side_effect=AssertionError("No AI")), CaptureQueriesContext(connection) as queries:
            result = self.candidate(row, static)
        self.assertFalse(any(source_fixtures.re.match(r"\s*(INSERT|UPDATE|DELETE)\b", item["sql"], source_fixtures.re.I) for item in queries))
        self.assertEqual(result["state"], "human_mention_target_not_observed_candidate_not_verified_unlinked")
        self.assertEqual(result["prospect"]["quote"], "Evidence useful.")
        self.assertEqual(result["research"]["retrieved_at"], row.source_evidence["retrieved_at"])
        self.assertEqual(result["static"]["observed_at"], static.output["observed_at"])
        self.assertEqual(result["research"]["original_response_sha256"], result["static"]["body_sha256"])
        self.assertEqual(result["unlinked_or_lost_link"], "not_established")
        self.assertNotIn("fixture-contact", json.dumps(result))
        for changes in ({"prospect_review_id": True}, {"static_job_id": 0}, {"static_job_id": 2**53}):
            with self.assertRaises(ValidationError): self.candidate(row, static, **changes)
        with self.assertRaises(ValidationError): self.candidate(draft, static)
        foreign = Project.objects.create(organization=self.organization, name="Synthetic foreign mention", canonical_origin="https://foreign.example.invalid")
        with self.assertRaises(PermissionDenied): self.candidate(row, static, project=foreign)
        artifact = static.artifacts.get()
        Artifact.objects.filter(pk=artifact.pk).update(size_bytes=artifact.size_bytes + 1)
        with self.assertRaises(ValidationError): self.candidate(row, static)
        Artifact.objects.filter(pk=artifact.pk).update(size_bytes=artifact.size_bytes)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
        with self.assertRaises(PermissionDenied): self.candidate(row, static)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="owner")
        from .authority import record_authority_prospect
        record_authority_prospect(project=self.project, actor=self.owner, request_key="mention-reopened", intake=row.intake,
            assignee_id=self.owner.pk, state="draft", reason="Fresh human correction.", prospect_id=row.prospect_id, expected_revision=row.revision)
        with self.assertRaises(ValidationError): self.candidate(row, static)

    def test_actual_body_mismatch_or_incomparable_coverage_never_creates_an_unlinked_candidate(self):
        row, static, _ = self.sources("mention-ambiguous", b"<p>Evidence useful.</p><template>Unclosed")
        result = self.candidate(row, static)
        self.assertFalse(result["static_coverage_complete"])
        self.assertEqual(result["state"], "incomparable_ambiguous_or_truncated_static_coverage")
        different = self.source_job("mention-different-body")
        self.assertTrue(execute_static_link_collection(different.pk, fetcher=self.transport(html_body=b"<p>Different original body.</p>")))
        with self.assertRaises(ValidationError): self.candidate(row, different)
        from .models import AuthorityProspectReview
        changed = {**row.intake, "proposed_action": "partnership"}
        AuthorityProspectReview.objects.filter(pk=row.pk).update(intake=changed)
        with self.assertRaises(ValidationError): self.candidate(row, static)
        AuthorityProspectReview.objects.filter(pk=row.pk).update(intake=row.intake)
        # Revoke during the actual selected static private readback; no old quote can be delivered.
        original = read_project_artifact
        def revoke_after_read(**kwargs):
            content = original(**kwargs)
            OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
            return content
        with patch("jobs.authority_link_collection.read_project_artifact", side_effect=revoke_after_read), self.assertRaises(PermissionDenied):
            self.candidate(row, static)

    def test_actual_positive_markup_research_later_than_static_and_different_final_source_are_separate(self):
        body = (f'<p>Evidence useful.</p><a href="{self.data["target_url"]}">Exact target</a>').encode()
        row, static, _ = self.sources("mention-positive", body)
        result = self.candidate(row, static)
        self.assertEqual(result["state"], "human_mention_with_observed_exact_target_markup")
        self.assertEqual(result["static"]["matching_target_count"], 1)
        self.assertEqual(result["research"]["collection_method"], "research-v1")
        later, _, _ = self.sources("mention-research-later", body)
        with self.assertRaises(ValidationError): self.candidate(later, static)
        redirected = self.source_job("mention-final-source-mismatch")
        transport = self.transport(html_body=body)
        normal_factory = transport.connection_factory
        calls = 0
        def factory(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                return transport_fixtures.FakeConnection(transport_fixtures.FakeResponse(302, headers={"Location": "/different-final"}))
            return normal_factory(*args)
        transport.connection_factory = factory
        self.assertTrue(execute_static_link_collection(redirected.pk, fetcher=transport))
        redirected.refresh_from_db(); self.assertEqual(redirected.status, JobStatus.SUCCEEDED)
        with self.assertRaises(ValidationError): self.candidate(later, redirected)


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json"}), DEBUG=True)
class StaticDestinationCandidateTests(source_fixtures.StaticSourceFixture, TransactionTestCase):
    source_job = StaticLinkCollectionTests.source_job
    transport = StaticLinkCollectionTests.transport

    def collected(self, key, body=None):
        job = self.source_job(key)
        self.assertTrue(execute_static_link_collection(job.pk, fetcher=self.transport(html_body=body)))
        job.refresh_from_db(); self.assertEqual(job.status, JobStatus.SUCCEEDED)
        connection.queries_log.clear()
        return job

    def candidate(self, job, **changes):
        return read_static_destination_candidate(**{**dict(project=self.project, actor=self.owner, static_job_id=job.pk), **changes})

    def test_actual_static_positive_and_separate_404_private_target_without_write_network_or_site_approval(self):
        job = self.collected("static-destination-positive")
        with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            result = self.candidate(job)
        self.assertFalse(any(source_fixtures.re.match(r"\s*(INSERT|UPDATE|DELETE)\b", item["sql"], source_fixtures.re.I) for item in queries))
        self.assertTrue(result["destination_recovery_candidate"])
        self.assertEqual(result["state"], "dated_static_target_and_http_missing_destination_candidate")
        self.assertEqual(result["target"], self.approved.target_evidence)
        self.assertEqual(result["target"]["status_code"], 404)
        self.assertEqual(result["static"]["observed_at"], job.output["observed_at"])
        self.assertEqual(result["static"]["matching_target_count"], 1)
        self.assertEqual(result["site_or_outreach_approval"], "separate_human_workflows")
        self.assertNotIn("fixture-contact", json.dumps(result))
        self.assertNotIn("matching_links", result["static"])
        self.assertLess(len(json.dumps(result).encode()), 32768)
        for value in (True, 0, 2**53):
            with self.assertRaises(ValidationError): self.candidate(job, static_job_id=value)
        foreign = Project.objects.create(organization=self.organization, name="Synthetic foreign destination", canonical_origin="https://foreign.example.invalid")
        with self.assertRaises(PermissionDenied): self.candidate(job, project=foreign)
        artifact = self.page.raw_artifact
        Artifact.objects.filter(pk=artifact.pk).update(size_bytes=artifact.size_bytes + 1)
        with self.assertRaises(ValidationError): self.candidate(job)
        Artifact.objects.filter(pk=artifact.pk).update(size_bytes=artifact.size_bytes)
        original = read_project_artifact
        def revoke_after_static_read(**kwargs):
            body = original(**kwargs)
            OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
            return body
        with patch("jobs.authority_link_collection.read_project_artifact", side_effect=revoke_after_static_read), self.assertRaises(PermissionDenied):
            self.candidate(job)

    def test_actual_no_match_ambiguous_truncated_and_successful_destination_never_claim_missing_or_healthy_current_link(self):
        for key, body, state in (("static-destination-no-match", b"<p>Bounded document</p>", "target_not_observed_in_bounded_static_document_not_missing_or_healthy_proof"),
            ("static-destination-ambiguous", b"<template>Unclosed", "incomparable_ambiguous_or_truncated_static_coverage"),
            ("static-destination-truncated", ('<a href="' + self.data["target_url"] + '">' + 'x' * 241 + '</a>').encode(),
             "incomparable_ambiguous_or_truncated_static_coverage")):
            job = self.collected(key, body)
            result = self.candidate(job)
            self.assertFalse(result["destination_recovery_candidate"])
            self.assertEqual(result["state"], state)
        # Exercise date-order rejection over the actual private source summary,
        # without modifying the retained original job/artifact or target records.
        original = read_static_link_observation(project=self.project, actor=self.owner, job_id=job.pk)
        original["collection"]["observed_at"] = (self.page.observed_at - timedelta(seconds=1)).isoformat()
        with patch("jobs.authority_link_collection.read_static_link_observation", return_value=original), self.assertRaises(ValidationError):
            self.candidate(job)
        from .test_crawler import response
        from .test_authority_links import OwnTargetEvidenceTests
        page = OwnTargetEvidenceTests.crawl(self, "static-destination-success-target", response(self.target, body=b"<title>Useful destination</title>",
            headers={"content-type": "text/html"}))
        self.data["crawl_page_id"] = page.pk
        draft = self.record(request_key="static-destination-success-draft")
        self.approved = self.transition(self.transition(draft, "review"), "approved")
        success = self.collected("static-destination-success-source")
        result = self.candidate(success)
        self.assertEqual(result["target"]["status_code"], 200)
        self.assertFalse(result["destination_recovery_candidate"])
        self.assertEqual(result["state"], "no_dated_missing_destination_candidate_not_current_healthy_or_recovered_link_proof")
        self.assertEqual(result["unlinked_or_lost_link"], "not_established")


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json"}), DEBUG=True)
class StaticDestinationCandidateAPITests(source_fixtures.StaticSourceFixture, TransactionTestCase):
    source_job = StaticLinkCollectionTests.source_job
    transport = StaticLinkCollectionTests.transport
    collected = StaticDestinationCandidateTests.collected

    @property
    def url(self):
        return f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/authority-link-sources/destination-candidate/"

    def test_actual_private_read_no_write_network_strict_scalar_foreign_tamper_and_role_loss(self):
        job = self.collected("static-destination-api")
        self.assertEqual(self.client.get(self.url, {"static_job_id": job.pk}).status_code, 401)
        self.client.force_login(self.owner)
        with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.url, {"static_job_id": job.pk})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["candidate"]["destination_recovery_candidate"])
        self.assertEqual(response.json()["candidate"]["selection"], job.config_snapshot)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertFalse(any(source_fixtures.re.match(r"\s*(INSERT|UPDATE|DELETE)\b", item["sql"], source_fixtures.re.I) for item in queries))
        self.assertNotIn(b"fixture-contact", response.content)
        for query in ("", "?extra=1", "?static_job_id=01", "?static_job_id=true", f"?static_job_id={2**53}",
            f"?static_job_id={job.pk}&static_job_id={job.pk}", f"?static_job_id={job.pk}&other=1"):
            self.assertEqual(self.client.get(self.url + query).status_code, 400)
        self.assertEqual(self.client.post(self.url, "{}", content_type="application/json").status_code, 405)
        self.assertEqual(self.client.get(self.url, {"static_job_id": 99999999}).status_code, 403)
        foreign = Project.objects.create(organization=self.organization, name="Synthetic foreign destination API", canonical_origin="https://foreign.example.invalid")
        foreign_url = f"/api/organizations/{self.organization.pk}/projects/{foreign.pk}/authority-link-sources/destination-candidate/"
        self.assertEqual(self.client.get(foreign_url, {"static_job_id": job.pk}).status_code, 403)
        artifact = self.page.raw_artifact
        Artifact.objects.filter(pk=artifact.pk).update(size_bytes=artifact.size_bytes + 1)
        self.assertEqual(self.client.get(self.url, {"static_job_id": job.pk}).status_code, 409)
        Artifact.objects.filter(pk=artifact.pk).update(size_bytes=artifact.size_bytes)
        original = read_project_artifact
        static_read_complete = False
        def read_static_then_target(**kwargs):
            nonlocal static_read_complete
            result = read_static_link_observation(**kwargs)
            static_read_complete = True
            return result
        def revoke_during_target_read(**kwargs):
            content = original(**kwargs)
            if static_read_complete:
                OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
            return content
        with patch("jobs.authority_links.read_project_artifact", side_effect=revoke_during_target_read), patch(
            "jobs.authority_link_collection.read_static_link_observation", side_effect=read_static_then_target):
            denied = self.client.get(self.url, {"static_job_id": job.pk})
        self.assertEqual(denied.status_code, 403)
        self.assertNotIn("candidate", denied.json())


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json"}), DEBUG=True)
class StaticMentionCandidateAPITests(source_fixtures.StaticSourceFixture, TransactionTestCase):
    source_job = StaticLinkCollectionTests.source_job
    transport = StaticLinkCollectionTests.transport
    sources = StaticMentionCandidateTests.sources

    def setUp(self):
        # Reuse the actual combined-source fixture without inheriting its test methods.
        StaticMentionCandidateTests.setUp(self)

    @property
    def url(self):
        return f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/authority-link-sources/mention-candidates/"

    def test_actual_private_current_selection_exact_candidate_read_only_strict_scope_and_source_loss(self):
        row, static, _ = self.sources("mention-api-real")
        pair = {"prospect_review_id": row.pk, "static_job_id": static.pk}
        self.assertEqual(self.client.get(self.url).status_code, 401)
        self.client.force_login(self.owner)
        with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            listed = self.client.get(self.url)
            result = self.client.get(self.url, pair)
        self.assertEqual(listed.status_code, 200, listed.content)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(listed.json()["candidates"][0], result.json()["candidate"]["selection"])
        self.assertEqual(result.json()["candidate"]["prospect"]["quote"], row.intake["quote"])
        self.assertNotIn(b"fixture-contact", listed.content + result.content)
        self.assertLess(len(result.content), 32768)
        self.assertFalse(any(source_fixtures.re.match(r"\s*(INSERT|UPDATE|DELETE)\b", item["sql"], source_fixtures.re.I) for item in queries))
        self.assertEqual(result["Cache-Control"], "private, no-store")
        for query in ("?extra=1", f"?prospect_review_id={row.pk}",
            f"?prospect_review_id={row.pk}&static_job_id={static.pk}&prospect_review_id={row.pk}",
            f"?prospect_review_id=true&static_job_id={static.pk}", f"?prospect_review_id={row.pk}&static_job_id=01",
            f"?prospect_review_id={2**53}&static_job_id={static.pk}"):
            self.assertEqual(self.client.get(self.url + query).status_code, 400)
        self.assertEqual(self.client.post(self.url, "{}", content_type="application/json").status_code, 405)
        self.assertEqual(self.client.get(self.url, {**pair, "prospect_review_id": 99999999}).status_code, 403)
        foreign = Project.objects.create(organization=self.organization, name="Synthetic foreign mention API", canonical_origin="https://foreign.example.invalid")
        url = f"/api/organizations/{self.organization.pk}/projects/{foreign.pk}/authority-link-sources/mention-candidates/"
        self.assertEqual(self.client.get(url, pair).status_code, 403)
        # Current-source loss during a D129 private read cannot leak the selected quote.
        original = read_project_artifact
        def revoke_after_read(**kwargs):
            content = original(**kwargs)
            OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member")
            return content
        with patch("jobs.authority.read_project_artifact", side_effect=revoke_after_read):
            response = self.client.get(self.url, pair)
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("candidate", response.json())
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="owner")
        artifact = static.artifacts.get()
        Artifact.objects.filter(pk=artifact.pk).update(size_bytes=artifact.size_bytes + 1)
        self.assertEqual(self.client.get(self.url, pair).status_code, 409)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
        self.assertEqual(self.client.get(self.url).status_code, 403)


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json"}), DEBUG=True)
class StaticLinkComparisonAPITests(source_fixtures.StaticSourceFixture, TransactionTestCase):
    source_job = StaticLinkCollectionTests.source_job
    transport = StaticLinkCollectionTests.transport
    collected = StaticLinkComparisonTests.collected

    @property
    def url(self):
        return f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/authority-link-sources/comparison/"

    def get(self, previous, current, **changes):
        return self.client.get(self.url, {**dict(previous_job_id=previous.pk, current_job_id=current.pk), **changes})

    def test_actual_pair_private_no_write_no_fetch_strict_ids_dates_foreign_tamper_and_retained_role_loss(self):
        previous = self.collected("static-comparison-api-before")
        current = self.collected("static-comparison-api-after", b"<p>No selected absolute target in this bounded static document</p>")
        self.assertEqual(self.get(previous, current).status_code, 401)
        self.client.force_login(self.owner)
        with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("Comparison cannot fetch")), CaptureQueriesContext(connection) as queries:
            response = self.get(previous, current)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertFalse(any(source_fixtures.re.match(r"\s*(INSERT|UPDATE|DELETE)\b", row["sql"], source_fixtures.re.I) for row in queries))
        result = response.json()["comparison"]
        self.assertEqual(result["previous"]["job_id"], previous.pk)
        self.assertEqual(result["current"]["observed_at"], current.output["observed_at"])
        self.assertEqual(result["state"], "target_markup_not_observed_again_candidate_not_verified_link_loss")
        self.assertEqual(result["unlinked_or_lost_link"], "not_established")
        self.assertLess(len(response.content), 32768)
        self.assertNotIn(b"fixture-contact", response.content)
        for value in ("", "0", "-1", "true", "1.0", "1e1", "+1", "01", " 1", "١", str(2**53), "9" * 100):
            self.assertEqual(self.get(previous, current, previous_job_id=value).status_code, 400)
        for query in ("", f"?previous_job_id={previous.pk}",
            f"?previous_job_id={previous.pk}&current_job_id={current.pk}&previous_job_id={previous.pk}",
            f"?previous_job_id={previous.pk}&current_job_id={current.pk}&scope=9"):
            self.assertEqual(self.client.get(self.url + query).status_code, 400)
        self.assertEqual(self.get(previous, previous).status_code, 400)
        self.assertEqual(self.get(current, previous).status_code, 409)
        self.assertEqual(self.client.post(self.url, "{}", content_type="application/json").status_code, 405)
        foreign = Project.objects.create(organization=self.organization, name="Synthetic foreign pair", canonical_origin="https://foreign.example.invalid")
        foreign_url = f"/api/organizations/{self.organization.pk}/projects/{foreign.pk}/authority-link-sources/comparison/"
        self.assertEqual(self.client.get(foreign_url, {"previous_job_id": previous.pk, "current_job_id": current.pk}).status_code, 403)
        self.assertEqual(self.get(previous, current, current_job_id=99999999).status_code, 403)
        artifact = current.artifacts.get()
        Artifact.objects.filter(pk=artifact.pk).update(size_bytes=artifact.size_bytes + 1)
        response = self.get(previous, current)
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("comparison", response.json())
        Artifact.objects.filter(pk=artifact.pk).update(size_bytes=artifact.size_bytes)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
        self.assertEqual(self.get(previous, current).status_code, 403)

    def test_actual_incomparable_delivery_and_mid_read_source_revocation_or_commercial_expiry_withhold_pair(self):
        previous = self.collected("static-pair-api-positive")
        current = self.collected("static-pair-api-ambiguous", b"<template>Unclosed")
        self.client.force_login(self.owner)
        response = self.get(previous, current)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(response.json()["comparison"]["comparable"])
        self.assertEqual(response.json()["comparison"]["state"], "incomparable_ambiguous_or_truncated_coverage")
        original_read = read_project_artifact
        calls = 0
        def read_then_revoke(**kwargs):
            nonlocal calls
            result = original_read(**kwargs)
            calls += 1
            if calls == 2:
                OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
            return result
        with patch("jobs.authority_link_collection.read_project_artifact", side_effect=read_then_revoke):
            response = self.get(previous, current)
        self.assertEqual(calls, 2)
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("comparison", response.json())
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="owner")
        start = timezone.now() - timedelta(days=31)
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=start, ends_at=start + timedelta(days=30))
        response = self.get(previous, current)
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("comparison", response.json())
        self.assertEqual(response["Cache-Control"], "private, no-store")


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}), DEBUG=True)
class StaticURICollectionTests(source_fixtures.StaticSourceFixture, TransactionTestCase):
    transport = StaticLinkCollectionTests.transport
    read = StaticLinkCollectionTests.read

    def source_job(self, key="uri-source-request", **changes):
        return StaticLinkCollectionTests.source_job(self, key, **{**{"data": {
            "link_review_id": self.approved.pk, "source_collection_permission": True,
            "collection_method": REFERENCE_COLLECTION_METHOD}}, **changes})

    def collected(self, key, body):
        job = self.source_job(key)
        self.assertTrue(execute_static_link_collection(job.pk, fetcher=self.transport(html_body=body)))
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.SUCCEEDED, job.error_category)
        return job

    def test_explicit_actual_uri_job_private_readback_method_integrity_and_literal_history_are_separate(self):
        body = (f'<a href="//{self.data["target_url"].split("//")[1]}">Exact URI Ω</a>'
                '<a href="/publisher-path">Unrelated</a>').encode()
        job = self.collected("uri-method-source", body)
        self.assertEqual(len(self.requests), 2)  # Only robots and selected source, never href destinations.
        self.assertEqual(job.method_version, REFERENCE_COLLECTION_METHOD)
        self.assertEqual(job.config_snapshot["parser_method"], REFERENCE_METHOD)
        self.assertEqual(job.steps.get().output, {"method": REFERENCE_COLLECTION_METHOD, "state": "collected"})
        result = self.read(job)["collection"]
        self.assertEqual(result["evidence"]["state"], "observed_resolved_target_in_static_uri_references")
        self.assertEqual(result["evidence"]["matching_links"][0]["anchor_text"], "Exact URI Ω")
        self.assertNotIn("publisher-path", json.dumps(result))
        literal = StaticLinkCollectionTests.source_job(self, "literal-same-body")
        self.assertTrue(execute_static_link_collection(literal.pk, fetcher=self.transport(html_body=body)))
        literal.refresh_from_db()
        self.assertEqual(self.read(literal)["collection"]["evidence"]["matching_links"], [])
        with self.assertRaises(ValidationError):
            compare_static_link_observations(project=self.project, actor=self.owner, previous_job_id=job.pk, current_job_id=literal.pk)
        with self.assertRaises(ValidationError): self.source_job("uri-method-source", data=literal.input_snapshot)
        with self.assertRaises(ValidationError): validate_result(result, job.config_snapshot["binding"])
        altered = json.loads(json.dumps(result)); altered["evidence"]["method"] = "authority-static-link-parse-v1"
        with self.assertRaises(ValidationError): validate_result(altered, job.config_snapshot["binding"], collection_method=REFERENCE_COLLECTION_METHOD)
        for method in (None, True, {}, "browser-url-repair", "authority-static-uri-parse-v1"):
            with self.assertRaises(ValidationError): self.source_job("invalid-uri-method", data={**job.input_snapshot, "collection_method": method})
        job.method_version = COLLECTION_METHOD
        with self.assertRaises(ValidationError): job.save()
        artifact = literal.artifacts.get()
        Artifact.objects.filter(pk=artifact.pk).update(size_bytes=artifact.size_bytes + 1)
        with self.assertRaises(ValidationError): self.read(literal)

    def test_actual_same_method_history_base_and_unsupported_coverage_never_prove_loss(self):
        body = (f'<a href="//{self.data["target_url"].split("//")[1]}">Own target</a>').encode()
        previous = self.collected("uri-history-previous", body)
        for key, markup, comparable in (("uri-history-absent", b"<p>No selected target</p>", True),
            ("uri-history-base", body + b'<base href="https://unrelated.example.invalid/">', False),
            ("uri-history-unsupported", body + b'<a href="https://private.example.invalid/?secret=omit">Other</a>', False)):
            current = self.collected(key, markup)
            result = compare_static_link_observations(project=self.project, actor=self.owner,
                previous_job_id=previous.pk, current_job_id=current.pk)
            self.assertEqual(result["comparable"], comparable)
            self.assertEqual(result["collection_method"], REFERENCE_COLLECTION_METHOD)
            self.assertEqual(result["parser_method"], REFERENCE_METHOD)
            self.assertEqual(result["unlinked_or_lost_link"], "not_established")
            self.assertNotIn("secret=omit", json.dumps(result))
            candidate = read_static_destination_candidate(project=self.project, actor=self.owner, static_job_id=current.pk)
            self.assertFalse(candidate["destination_recovery_candidate"])
            if key.endswith("base"):
                collection = self.read(current)["collection"]
                evidence = collection["evidence"]
                self.assertEqual(evidence["state"], "unavailable_base_dependent_references")
                self.assertEqual(evidence["matching_links"], [])
                evidence["state"] = "unavailable_ambiguous_markup"
                with self.assertRaises(ValidationError): validate_result(collection,
                    current.config_snapshot["binding"], collection_method=REFERENCE_COLLECTION_METHOD)
        artifact = previous.artifacts.get()
        Artifact.objects.filter(pk=artifact.pk).update(size_bytes=artifact.size_bytes + 1)
        with self.assertRaises(ValidationError): self.read(previous)
        Artifact.objects.filter(pk=artifact.pk).update(size_bytes=artifact.size_bytes)
        original = read_project_artifact
        def revoke_during_private_read(**kwargs):
            content = original(**kwargs)
            OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
            return content
        with patch("jobs.authority_link_collection.read_project_artifact", side_effect=revoke_during_private_read), self.assertRaises(PermissionDenied):
            self.read(previous)

    test_current_source_loss_cancel_and_dispatch_recovery = StaticLinkCollectionTests.test_dispatch_broker_recovery_current_source_loss_and_prestart_cancel_release_without_network
    test_commercial_expiry_no_delivery = StaticLinkCollectionTests.test_commercial_internal_budget_and_expiry_mid_request_cancel_without_delivering_evidence
    test_robots_unknown_attempt_no_replay = StaticLinkCollectionTests.test_denied_robots_failed_attempt_and_unknown_running_recovery_never_replay_and_settle_once
    test_dns_tls_current_loss_no_send = StaticLinkCollectionTests.test_revocation_during_dns_or_connected_tls_prevents_get_and_uncertain_replay
    test_actual_export_retention_closure_deletion = StaticLinkCollectionTests.test_actual_derived_job_bounded_stored_sequential_exports_retention_closure_and_deletion


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json"}), DEBUG=True)
class StaticLinkCollectionAPITests(source_fixtures.StaticSourceFixture, TransactionTestCase):
    source_job = StaticLinkCollectionTests.source_job
    transport = StaticLinkCollectionTests.transport

    @property
    def url(self):
        return f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/authority-link-sources/"

    def payload(self, **changes):
        return {**dict(link_review_id=self.approved.pk, source_collection_permission=True,
                       idempotency_key="static-api-collect"), **changes}

    def test_real_get_has_no_write_or_fetch_or_consent_and_csrf_post_exact_lookup_current_evidence_cancel(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.get(self.url).status_code, 401)
        client.force_login(self.owner)
        with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("GET cannot fetch")), CaptureQueriesContext(connection) as queries:
            result = client.get(self.url)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertFalse(any(source_fixtures.re.match(r"\s*(INSERT|UPDATE|DELETE)\b", row["sql"], source_fixtures.re.I) for row in queries))
        info = result.json()
        self.assertTrue(info["can_collect"])
        self.assertEqual(info["candidates"][0]["link_review_id"], self.approved.pk)
        self.assertTrue(info["candidates"][0]["requires_separate_collection_permission"])
        self.assertNotIn("source_collection_permission", info["candidates"][0]["binding"])
        self.assertEqual(result["Cache-Control"], "private, no-store")
        self.assertEqual(client.post(self.url, json.dumps(self.payload()), content_type="application/json").status_code, 403)
        client.get("/_allauth/browser/v1/auth/session")
        headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value}
        def post(path, data):
            with patch("jobs.tasks.execute_static_link_collection_task.apply_async"):
                return client.post(path, json.dumps(data), content_type="application/json", **headers)
        result = post(self.url, self.payload())
        self.assertEqual(result.status_code, 202, result.content)
        job_id = result.json()["job"]["id"]
        self.assertEqual(post(self.url, self.payload()).json()["job"]["id"], job_id)
        self.assertEqual(client.get(self.url + "?idempotency_key=static-api-collect").json()["lookup"], "found")
        self.assertEqual(client.get(self.url + "?idempotency_key=static-api-missing").json()["lookup"], "not_found")
        self.assertEqual(client.get(self.url + str(job_id) + "/").json()["job"]["evidence_state"], "not_collected")
        self.assertTrue(execute_static_link_collection(job_id, fetcher=self.transport()))
        result = client.get(self.url + str(job_id) + "/")
        self.assertEqual(result.json()["job"]["evidence_state"], "current_private_readback_checked")
        self.assertNotIn(b"fixture-contact", result.content)
        second = post(self.url, self.payload(idempotency_key="static-api-cancel")).json()["job"]
        result = post(self.url + str(second["id"]) + "/", {})
        self.assertEqual(result.status_code, 202)
        self.assertEqual(result.json()["job"]["status"], "cancelled")
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
        self.assertFalse(client.get(self.url).json()["can_collect"])
        result = client.get(self.url + str(job_id) + "/").json()["job"]
        self.assertIsNone(result["evidence"])
        self.assertEqual(result["evidence_state"], "retained_current_use_unavailable")

    def test_foreign_draft_permission_strict_json_queries_own_launch_cancel_rate_and_retained_loss(self):
        self.client.force_login(self.owner)
        # Malformed-input checks must reach validation; separate nested denials
        # below exercise the launch/cancel limiter without exhausting this fixture.
        allowed = patch("jobs.authority_link_collection_api.ratelimit.consume", return_value=True)
        allowed.start(); self.addCleanup(allowed.stop)
        for body, kind in (("{}", "text/plain"), ('{"link_review_id":1,"link_review_id":2}', "application/json"),
            ('{"value":NaN}', "application/json"), ('{"value":Infinity}', "application/json"), ("[]", "application/json"),
            ("{}", "application/json"), ("x" * 2049, "application/json"), ('{"x":' + "[" * 1500, "application/json")):
            self.assertEqual(self.client.post(self.url, body, content_type=kind).status_code, 409)
        for query in ("?foreign=1", "?idempotency_key=bad", "?idempotency_key=static-api-one&idempotency_key=static-api-two"):
            self.assertEqual(self.client.get(self.url + query).status_code, 400)
        with patch("jobs.authority_link_collection_api.ratelimit.consume", return_value=False) as limiter:
            self.assertEqual(self.client.post(self.url, json.dumps(self.payload()), content_type="application/json").status_code, 429)
            self.assertEqual(limiter.call_args.kwargs["action"], "authority_source_request")
        for changes in ({"source_collection_permission": False}, {"link_review_id": self.draft.pk}):
            self.assertIn(self.client.post(self.url, json.dumps(self.payload(**changes)), content_type="application/json").status_code, {403, 409})
        self.assertFalse(JobRun.objects.filter(handler=HANDLER).exists())
        job = self.source_job()
        with patch("jobs.authority_link_collection_api.ratelimit.consume", return_value=False) as limiter:
            self.assertEqual(self.client.post(self.url + str(job.pk) + "/", "{}", content_type="application/json").status_code, 429)
            self.assertEqual(limiter.call_args.kwargs["action"], "authority_source_cancel")
        foreign = Project.objects.create(organization=self.organization, name="Synthetic foreign API static source", canonical_origin="https://foreign.example.invalid")
        foreign_url = f"/api/organizations/{self.organization.pk}/projects/{foreign.pk}/authority-link-sources/"
        self.assertEqual(self.client.get(foreign_url + str(job.pk) + "/").status_code, 404)
        self.assertEqual(self.client.post(foreign_url, json.dumps(self.payload()), content_type="application/json").status_code, 403)
        self.assertEqual(self.client.get(self.url + "99999999/").status_code, 404)
        self.transition(self.approved, "draft")
        self.assertEqual(self.client.get(self.url).json()["candidates"], [])
        self.assertFalse(self.client.get(self.url + str(job.pk) + "/").json()["job"]["source_current"])


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json"}), DEBUG=True)
class StaticURICollectionAPITests(source_fixtures.StaticSourceFixture, TransactionTestCase):
    source_job = StaticURICollectionTests.source_job
    transport = StaticLinkCollectionTests.transport
    url = StaticLinkCollectionAPITests.url

    def payload(self, **changes):
        return StaticLinkCollectionAPITests.payload(self, **{**{"collection_method": REFERENCE_COLLECTION_METHOD}, **changes})

    test_actual_csrf_queue_lookup_current_private_and_cancellation = StaticLinkCollectionAPITests.test_real_get_has_no_write_or_fetch_or_consent_and_csrf_post_exact_lookup_current_evidence_cancel

    def test_explicit_api_methods_current_metadata_private_base_history_and_mixed_method_denial(self):
        self.client.force_login(self.owner)
        with patch("jobs.authority_link_collection_api.ratelimit.consume", return_value=True):
            for method in (None, False, {}, "unknown", REFERENCE_METHOD):
                result = self.client.post(self.url, json.dumps(self.payload(collection_method=method)), content_type="application/json")
                self.assertEqual(result.status_code, 409)
            for body in ('{"collection_method":"' + REFERENCE_COLLECTION_METHOD + '","collection_method":"' + COLLECTION_METHOD + '"}',
                         json.dumps({**self.payload(), "raw_html": "forbidden"})):
                self.assertEqual(self.client.post(self.url, body, content_type="application/json").status_code, 409)
        self.assertFalse(JobRun.objects.filter(handler=HANDLER).exists())
        info = self.client.get(self.url).json()
        self.assertEqual(info["collection_methods"], [COLLECTION_METHOD, REFERENCE_COLLECTION_METHOD])
        previous = self.source_job("uri-api-previous")
        body = (f'<a href="//{self.data["target_url"].split("//")[1]}">URI only</a>').encode()
        self.assertTrue(execute_static_link_collection(previous.pk, fetcher=self.transport(html_body=body)))
        current = self.source_job("uri-api-base")
        self.assertTrue(execute_static_link_collection(current.pk, fetcher=self.transport(html_body=body + b'<base href="/">')))
        listed = self.client.get(self.url).json()["jobs"]
        self.assertEqual(listed[0]["selection"]["method"], REFERENCE_COLLECTION_METHOD)
        self.assertIsNone(listed[0]["evidence"])
        detail = self.client.get(self.url + str(current.pk) + "/")
        self.assertEqual(detail.status_code, 200, detail.content)
        self.assertEqual(detail.json()["job"]["evidence"]["collection"]["evidence"]["state"], "unavailable_base_dependent_references")
        pair_url = self.url + "comparison/"
        pair = self.client.get(pair_url, {"previous_job_id": previous.pk, "current_job_id": current.pk})
        self.assertEqual(pair.status_code, 200, pair.content)
        self.assertFalse(pair.json()["comparison"]["comparable"])
        self.assertEqual(pair.json()["comparison"]["parser_method"], REFERENCE_METHOD)
        literal = StaticLinkCollectionTests.source_job(self, "literal-uri-api-history")
        self.assertTrue(execute_static_link_collection(literal.pk, fetcher=self.transport(html_body=body)))
        self.assertEqual(self.client.get(pair_url, {"previous_job_id": previous.pk, "current_job_id": literal.pk}).status_code, 409)
        current.refresh_from_db()
        artifact = current.artifacts.get()
        Artifact.objects.filter(pk=artifact.pk).update(size_bytes=artifact.size_bytes + 1)
        detail = self.client.get(self.url + str(current.pk) + "/").json()["job"]
        self.assertIsNone(detail["evidence"])
        self.assertEqual(detail["evidence_state"], "retained_current_use_unavailable")
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
        self.assertIsNone(self.client.get(self.url + str(previous.pk) + "/").json()["job"]["evidence"])


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json"}), DEBUG=True)
class StaticURIMentionTests(source_fixtures.StaticSourceFixture, TransactionTestCase):
    source_job = StaticURICollectionTests.source_job
    transport = StaticLinkCollectionTests.transport
    setUp = StaticMentionCandidateTests.setUp
    sources = StaticMentionCandidateTests.sources
    candidate = StaticMentionCandidateTests.candidate

    def test_actual_current_approved_mention_and_uri_body_match_keep_unsupported_coverage_incomparable(self):
        body = (f'<p>Evidence useful.</p><a href="//{self.data["target_url"].split("//")[1]}">Own target</a>'
            '<a href="https://private.example.invalid/?secret=omit">Unrelated</a>').encode()
        row, static, _ = self.sources("uri-mention-actual", body)
        with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            result = self.candidate(row, static)
        self.assertFalse(any(source_fixtures.re.match(r"\s*(INSERT|UPDATE|DELETE)\b", item["sql"], source_fixtures.re.I) for item in queries))
        self.assertEqual(result["static"]["method"], REFERENCE_COLLECTION_METHOD)
        self.assertEqual(result["static"]["parser_method"], REFERENCE_METHOD)
        self.assertEqual(result["static"]["matching_target_count"], 1)
        self.assertFalse(result["static_coverage_complete"])
        self.assertEqual(result["state"], "incomparable_ambiguous_or_truncated_static_coverage")
        self.assertEqual(result["unlinked_or_lost_link"], "not_established")
        self.assertNotIn("secret=omit", json.dumps(result))
        self.assertNotIn("Unrelated", json.dumps(result))
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
        with self.assertRaises(PermissionDenied): self.candidate(row, static)
