import os
import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from allauth.account.models import EmailAddress
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from providers.adapters import ProviderRequestError, ProviderResponse
from providers.models import AIModel, AIModelCapability, AIProvider
from providers.services import (configure_model, create_organization_provider_account,
                                 create_provider, create_provider_account, revoke_organization_provider_account,
                                 revoke_provider_account, set_organization_provider_secret,
                                 set_provider_secret)
from tenancy.models import OrganizationTrial
from tenancy.services import create_organization, create_project

from .ai_text import execute_ai_text, queue_ai_text
from .models import AIUsageRecord, JobCancellation, JobRun, JobStatus, JobStep, UsageReservation
from .recovery import reconcile_stuck_ai_text


class AITextJobTests(TestCase):
    def setUp(self):
        self.operator = get_user_model().objects.create_superuser("ai-operator@example.com", "test-password")
        self.owner = get_user_model().objects.create_user("ai-owner@example.com", "test-password")
        EmailAddress.objects.create(user=self.owner, email=self.owner.email, primary=True, verified=True)
        self.organization = create_organization(user=self.owner, name="AI test organization")
        self.project = create_project(organization=self.organization, user=self.owner,
                                      name="AI test site", canonical_origin="https://ai-site.example.com")
        self.provider = create_provider(actor=self.operator, key="test-openai", name="OpenAI",
                                        kind=AIProvider.Kind.OPENAI, enabled=True)
        self.account = create_provider_account(actor=self.operator, provider=self.provider,
                                               label="Platform", secret_reference="env:OPENAI_API_KEY")
        self.model = configure_model(actor=self.operator, provider=self.provider, identifier="chosen-model",
                                     name="Chosen model", capabilities=[AIModelCapability.TEXT_GENERATION],
                                     max_output_tokens=256, capability_source="https://example.com/models/chosen-model",
                                     capabilities_verified_at=timezone.now(), enabled=True,
                                     input_price_usd_per_million=Decimal("0.1250"),
                                     output_price_usd_per_million=Decimal("2.5000"),
                                     pricing_source="https://example.com/prices", pricing_verified_at=timezone.now(),
                                     access_tier="standard")

    def queue(self, **overrides):
        args = {"project": self.project, "actor": self.owner, "model": self.model, "account": self.account,
                "prompt": "Summarize the provided notes.", "max_output_tokens": 100,
                "max_cost_usd": "0.010000", "allow_free": False, "idempotency_key": "text-1"}
        args.update(overrides)
        with patch("jobs.services.dispatch_pending") as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                job = queue_ai_text(**args)
            dispatch.assert_called_once_with(job.pk)
        return job

    def test_selected_model_executes_once_on_ai_queue_and_settles_attempt(self):
        job = self.queue()
        self.assertEqual(job.method_version, "ai-text-v2")
        self.assertEqual(job.config_snapshot["model_identifier"], "chosen-model")
        self.assertEqual(job.config_snapshot["provider_kind"], AIProvider.Kind.OPENAI)
        self.assertEqual((job.usage.provider, job.usage.reserved_units), ("ai", 1))
        with patch.dict(os.environ, {"OPENAI_API_KEY": "dummy-secret"}):
            with patch("jobs.tasks.execute_ai_text_task.apply_async") as send:
                from .services import dispatch_pending
                self.assertTrue(dispatch_pending(job.pk))
            self.assertEqual(send.call_args.kwargs["queue"], "ai")
            seen = []

            def request(**args):
                seen.append((args["model"].identifier, args["max_output_tokens"]))
                return ProviderResponse("Result", None, (), "req_safe", "resp_safe", 12, 5)

            self.assertTrue(execute_ai_text(job.pk, request=request))
        job.refresh_from_db()
        self.assertEqual(seen, [("chosen-model", 100)])
        self.assertEqual((job.status, job.output["text"], job.output["output_tokens"]),
                         (JobStatus.SUCCEEDED, "Result", 5))
        self.assertEqual(job.steps.get().status, JobStep.Status.SUCCEEDED)
        self.assertEqual((job.usage.state, job.usage.actual_units), (UsageReservation.State.SETTLED, 1))
        observed = AIUsageRecord.objects.get(job=job)
        self.assertEqual((observed.project_id, observed.organization_id, observed.step_id, observed.model_id,
                          observed.provider_id, observed.account_id),
                         (self.project.pk, self.organization.pk, job.steps.get().pk, self.model.pk,
                          self.provider.pk, self.account.pk))
        self.assertEqual((observed.status, observed.input_tokens, observed.output_tokens,
                          observed.estimated_cost_usd, observed.reported_cost_usd),
                         (AIUsageRecord.Status.COMPLETED, 12, 5, Decimal("0.000014"), None))
        self.assertIsNotNone(observed.duration_ms)
        self.assertEqual((observed.web_search_used, observed.tool_call_count), (False, 0))
        self.assertNotIn("dummy-secret", str(observed.__dict__))
        with patch.dict(os.environ, {"OPENAI_API_KEY": "dummy-secret"}):
            self.assertFalse(execute_ai_text(job.pk, request=lambda **_: self.fail("must not replay")))
        self.assertEqual(AIUsageRecord.objects.filter(job=job).count(), 1)

    def test_unavailable_model_account_and_foreign_actor_fail_before_dispatch(self):
        with self.assertRaises(PermissionDenied):
            self.queue(actor=self.operator)
        other = create_provider(actor=self.operator, key="other", name="Other", kind=AIProvider.Kind.OPENAI,
                                enabled=True)
        unrelated = create_provider_account(actor=self.operator, provider=other, label="Other",
                                            secret_reference="env:OPENAI_API_KEY")
        with self.assertRaises(ValidationError):
            self.queue(account=unrelated)
        with self.assertRaises(ValidationError):
            self.queue(max_output_tokens=257)
        with self.assertRaises(ValidationError):
            self.queue(max_cost_usd="0.000001")
        self.assertFalse(JobRun.objects.exists())

        job = self.queue()
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            self.assertTrue(execute_ai_text(job.pk, request=lambda **_: self.fail("no key")))
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category, job.usage.actual_units),
                         (JobStatus.FAILED, "credential_unavailable", 0))
        self.assertFalse(job.steps.exists())
        self.assertFalse(AIUsageRecord.objects.filter(job=job).exists())

    def test_attempt_outcome_is_not_replayed_after_provider_failure_or_worker_loss(self):
        job = self.queue()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "dummy-secret"}):
            self.assertTrue(execute_ai_text(job.pk, request=lambda **_: (_ for _ in ()).throw(
                ProviderRequestError("rate_limited", retryable=True, request_id="req_safe"))))
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category, job.usage.actual_units),
                         (JobStatus.FAILED, "rate_limited", 1))
        self.assertNotIn("dummy-secret", str(job.output) + str(job.steps.get().output))
        failed = AIUsageRecord.objects.get(job=job)
        self.assertEqual((failed.status, failed.error_category, failed.input_tokens, failed.estimated_cost_usd),
                         (AIUsageRecord.Status.FAILED, "rate_limited", None, None))
        self.assertEqual(failed.provider_request_id, "req_safe")

        next_job = self.queue(idempotency_key="text-2")
        JobRun.objects.filter(pk=next_job.pk).update(status=JobStatus.RUNNING,
                                                     updated_at=timezone.now() - timedelta(minutes=3))
        JobStep.objects.create(job=next_job, sequence=1, name="Request selected model",
                               status=JobStep.Status.RUNNING, output={"state": "attempted"})
        with patch.dict(os.environ, {"OPENAI_API_KEY": "dummy-secret"}):
            self.assertEqual(reconcile_stuck_ai_text(), 1)
            self.assertFalse(execute_ai_text(next_job.pk, request=lambda **_: self.fail("uncertain replay")))
        next_job.refresh_from_db()
        self.assertEqual((next_job.status, next_job.error_category, next_job.usage.actual_units),
                         (JobStatus.FAILED, "request_outcome_unknown", 1))
        self.assertEqual((next_job.ai_usage_record.status, next_job.ai_usage_record.reported_cost_usd),
                         (AIUsageRecord.Status.UNKNOWN, None))

    def test_refusal_preserves_reported_tokens_without_claiming_provider_charge(self):
        job = self.queue(idempotency_key="refused-with-usage")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "dummy-secret"}):
            self.assertTrue(execute_ai_text(job.pk, request=lambda **_: (_ for _ in ()).throw(
                ProviderRequestError("refused", request_id="req_safe", input_tokens=10, output_tokens=1))))
        job.refresh_from_db()
        usage = job.ai_usage_record
        self.assertEqual((job.status, job.usage.actual_units, usage.status, usage.error_category),
                         (JobStatus.FAILED, 1, AIUsageRecord.Status.FAILED, "refused"))
        self.assertEqual((usage.input_tokens, usage.output_tokens, usage.estimated_cost_usd,
                          usage.reported_cost_usd, usage.provider_request_id),
                         (10, 1, Decimal("0.000004"), None, "req_safe"))

    def test_success_without_provider_token_counts_keeps_cost_unknown(self):
        job = self.queue(idempotency_key="missing-token-counts")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "dummy-secret"}):
            self.assertTrue(execute_ai_text(job.pk, request=lambda **_: ProviderResponse(
                "Result without usage", None, (), "req_safe", "resp_safe", None, None)))
        job.refresh_from_db()
        record = job.ai_usage_record
        self.assertEqual((job.status, job.usage.actual_units, record.status),
                         (JobStatus.SUCCEEDED, 1, AIUsageRecord.Status.COMPLETED))
        self.assertEqual((record.input_tokens, record.output_tokens, record.estimated_cost_usd,
                          record.reported_cost_usd), (None, None, None, None))

    def test_implausibly_large_reported_usage_keeps_tokens_without_losing_job(self):
        configure_model(actor=self.operator, provider=self.provider, identifier=self.model.identifier,
                        name=self.model.name, capabilities=[AIModelCapability.TEXT_GENERATION],
                        capability_source="https://example.com/models", capabilities_verified_at=timezone.now(),
                        enabled=True, max_output_tokens=256,
                        input_price_usd_per_million=Decimal("10000"),
                        output_price_usd_per_million=Decimal("10000"),
                        pricing_source="https://example.com/prices", pricing_verified_at=timezone.now(),
                        access_tier="standard")
        job = self.queue(idempotency_key="large-provider-usage", max_cost_usd="100.000000")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "dummy-secret"}):
            self.assertTrue(execute_ai_text(job.pk, request=lambda **_: ProviderResponse(
                "Result", None, (), "req_safe", "resp_safe", 100_000_000, 100_000_000)))
        job.refresh_from_db()
        record = job.ai_usage_record
        self.assertEqual((job.status, job.usage.actual_units, record.input_tokens, record.output_tokens),
                         (JobStatus.SUCCEEDED, 1, 100_000_000, 100_000_000))
        self.assertIsNone(record.estimated_cost_usd)

    def test_provider_revocation_during_request_discards_output_and_charges_attempt(self):
        job = self.queue()

        def request(**_):
            revoke_provider_account(actor=self.operator, account=self.account)
            return ProviderResponse("Untrusted text", None, (), "req_safe", "resp_safe", 3, 2)

        with patch.dict(os.environ, {"OPENAI_API_KEY": "dummy-secret"}):
            self.assertTrue(execute_ai_text(job.pk, request=request))
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category, job.output, job.usage.actual_units),
                         (JobStatus.CANCELLED, "model_unavailable", {}, 1))
        self.assertEqual((job.ai_usage_record.status, job.ai_usage_record.input_tokens),
                         (AIUsageRecord.Status.COMPLETED, 3))

    def test_cancellation_during_request_discards_output_and_direct_queue_checks_selection(self):
        job = self.queue()

        def request(**_):
            JobCancellation.objects.create(job=job, requested_by=self.owner)
            return ProviderResponse("Must stay private", None, (), "req_safe", "resp_safe", 3, 2)

        with patch.dict(os.environ, {"OPENAI_API_KEY": "dummy-secret"}):
            self.assertTrue(execute_ai_text(job.pk, request=request))
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category, job.output, job.usage.actual_units),
                         (JobStatus.CANCELLED, "cancelled", {}, 1))
        self.assertEqual((job.ai_usage_record.status, job.ai_usage_record.input_tokens,
                          job.ai_usage_record.reported_cost_usd), (AIUsageRecord.Status.COMPLETED, 3, None))

        from .services import queue_job
        with self.assertRaises(ValidationError):
            queue_job(project=self.project, actor=self.owner, handler="ai_text", idempotency_key="direct-invalid",
                      input_snapshot={"model_id": self.model.pk, "account_id": self.account.pk + 9999,
                                       "prompt": "Short prompt", "max_output_tokens": 20,
                                       "max_cost_usd": "0.010000", "allow_free": False})
        self.assertFalse(JobRun.objects.filter(idempotency_key="direct-invalid").exists())

    def test_trial_expiry_during_request_discards_output_but_preserves_attempt(self):
        job = self.queue()

        def request(**_):
            OrganizationTrial.objects.filter(organization=self.organization).update(
                started_at=timezone.now() - timedelta(days=31), ends_at=timezone.now() - timedelta(days=1))
            return ProviderResponse("Do not show", None, (), "req_safe", "resp_safe", 3, 2)

        with patch.dict(os.environ, {"OPENAI_API_KEY": "dummy-secret"}):
            self.assertTrue(execute_ai_text(job.pk, request=request))
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category, job.output, job.usage.actual_units),
                         (JobStatus.CANCELLED, "trial_unavailable", {}, 1))

    def test_compatible_selected_model_routes_through_adapter_without_network(self):
        provider = create_provider(actor=self.operator, key="compatible-ai", name="Compatible",
                                   kind=AIProvider.Kind.OPENAI_COMPATIBLE,
                                   base_url="https://compatible.example/v1", enabled=True)
        account = create_provider_account(actor=self.operator, provider=provider, label="Compatible",
                                          secret_reference="env:OPENAI_COMPATIBLE_API_KEY")
        model = configure_model(actor=self.operator, provider=provider, identifier="user-choice",
                                name="User choice", capabilities=[AIModelCapability.TEXT_GENERATION],
                                capability_source="https://compatible.example/models/user-choice",
                                capabilities_verified_at=timezone.now(), enabled=True,
                                input_price_usd_per_million=Decimal("0.1250"),
                                output_price_usd_per_million=Decimal("2.5000"),
                                pricing_source="https://example.com/prices", pricing_verified_at=timezone.now(),
                                access_tier="standard")
        job = self.queue(model=model, account=account)
        with patch.dict(os.environ, {"OPENAI_COMPATIBLE_API_KEY": "dummy-secret"}):
            with patch("providers.adapters.post_json", return_value=(200, "req_ok", json.dumps({
                "id": "resp_ok", "status": "completed", "output": [{"type": "message", "content": [
                    {"type": "output_text", "text": "Bounded answer"}]}],
            }).encode())) as transport:
                self.assertTrue(execute_ai_text(job.pk))
        self.assertEqual(transport.call_args.kwargs["endpoint"], "https://compatible.example/v1/responses")
        self.assertEqual(json.loads(transport.call_args.kwargs["body"])["model"], "user-choice")
        job.refresh_from_db()
        self.assertEqual((job.status, job.output["text"]), (JobStatus.SUCCEEDED, "Bounded answer"))

    def test_compatible_endpoint_change_cancels_queued_job_before_request(self):
        provider = create_provider(actor=self.operator, key="another-compatible", name="Compatible",
                                   kind=AIProvider.Kind.OPENAI_COMPATIBLE,
                                   base_url="https://first.example/v1", enabled=True)
        account = create_provider_account(actor=self.operator, provider=provider, label="Platform",
                                          secret_reference="env:OPENAI_COMPATIBLE_API_KEY")
        model = configure_model(actor=self.operator, provider=provider, identifier="chosen-compatible",
                                name="Chosen compatible", capabilities=[AIModelCapability.TEXT_GENERATION],
                                capability_source="https://first.example/models",
                                 capabilities_verified_at=timezone.now(), enabled=True,
                                 input_price_usd_per_million=Decimal("0.1250"),
                                 output_price_usd_per_million=Decimal("2.5000"),
                                 pricing_source="https://example.com/prices", pricing_verified_at=timezone.now(),
                                 access_tier="standard")
        job = self.queue(model=model, account=account)
        self.assertEqual(job.config_snapshot["provider_base_url"], "https://first.example/v1")
        AIProvider.objects.filter(pk=provider.pk).update(base_url="https://second.example/v1")
        with patch.dict(os.environ, {"OPENAI_COMPATIBLE_API_KEY": "dummy-secret"}):
            self.assertTrue(execute_ai_text(job.pk, request=lambda **_: self.fail("changed endpoint must not run")))
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category, job.usage.actual_units),
                         (JobStatus.CANCELLED, "model_unavailable", 0))

    def test_organization_key_is_scoped_at_queue_worker_and_adapter(self):
        with override_settings(PROVIDER_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),)):
            account = create_organization_provider_account(actor=self.owner, organization=self.organization,
                                                            provider=self.provider, label="Customer key",
                                                            secret="dummy-owned-key")
            job = self.queue(account=account)
            other_owner = get_user_model().objects.create_user("another-ai-owner@example.com", "test-password")
            EmailAddress.objects.create(user=other_owner, email=other_owner.email, primary=True, verified=True)
            other_org = create_organization(user=other_owner, name="Another AI organization")
            other_project = create_project(organization=other_org, user=other_owner, name="Another AI site",
                                           canonical_origin="https://other-ai.example.com")
            with self.assertRaises(ValidationError):
                queue_ai_text(project=other_project, actor=other_owner, model=self.model, account=account,
                              prompt="No access", max_output_tokens=50, max_cost_usd="0.010000",
                              allow_free=False, idempotency_key="foreign")
            with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
                with patch("providers.adapters.post_json", return_value=(200, "req_ok", json.dumps({
                    "id": "resp_ok", "status": "completed", "output": [{"type": "message", "content": [
                        {"type": "output_text", "text": "Own result"}]}],
                }).encode())) as transport:
                    self.assertTrue(execute_ai_text(job.pk))
            self.assertEqual(transport.call_args.kwargs["secret"], "dummy-owned-key")
        job.refresh_from_db()
        self.assertEqual((job.status, job.output["text"]), (JobStatus.SUCCEEDED, "Own result"))

    def test_organization_key_revoked_during_request_discards_output(self):
        with override_settings(PROVIDER_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),)):
            account = create_organization_provider_account(actor=self.owner, organization=self.organization,
                                                            provider=self.provider, label="Own key",
                                                            secret="dummy-owned-key")
            job = self.queue(account=account)

            def request(**_):
                revoke_organization_provider_account(actor=self.owner, organization=self.organization, account=account)
                return ProviderResponse("Should be discarded", None, (), "req_safe", "resp_safe", 3, 2)

            self.assertTrue(execute_ai_text(job.pk, request=request))
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category, job.output, job.usage.actual_units),
                         (JobStatus.CANCELLED, "model_unavailable", {}, 1))

    def test_platform_key_rotation_blocks_queued_job_and_discards_inflight_response(self):
        with override_settings(PROVIDER_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),)):
            set_provider_secret(actor=self.operator, account=self.account, secret="dummy-original-key")
            queued = self.queue()
            self.assertEqual(queued.config_snapshot["account_id"], self.account.pk)
            self.assertNotIn("dummy-original-key", str(queued.config_snapshot))
            set_provider_secret(actor=self.operator, account=self.account, secret="dummy-replacement-key")
            self.assertTrue(execute_ai_text(queued.pk, request=lambda **_: self.fail("rotated key must not run")))
            queued.refresh_from_db()
            self.assertEqual((queued.status, queued.usage.actual_units), (JobStatus.CANCELLED, 0))
            self.assertFalse(queued.steps.exists())

            active = self.queue(idempotency_key="platform-inflight")

            def request(**_):
                set_provider_secret(actor=self.operator, account=self.account, secret="dummy-third-key")
                return ProviderResponse("Discarded", None, (), "req_safe", "resp_safe", 3, 2)

            self.assertTrue(execute_ai_text(active.pk, request=request))
            active.refresh_from_db()
            self.assertEqual((active.status, active.output, active.usage.actual_units), (JobStatus.CANCELLED, {}, 1))

    def test_organization_key_rotation_blocks_queued_job_and_discards_inflight_response(self):
        with override_settings(PROVIDER_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),)):
            account = create_organization_provider_account(actor=self.owner, organization=self.organization,
                                                            provider=self.provider, label="Rotating org key",
                                                            secret="dummy-original-key")
            queued = self.queue(account=account)
            set_organization_provider_secret(actor=self.owner, organization=self.organization, account=account,
                                             secret="dummy-replacement-key")
            self.assertTrue(execute_ai_text(queued.pk, request=lambda **_: self.fail("rotated key must not run")))
            queued.refresh_from_db()
            self.assertEqual((queued.status, queued.usage.actual_units), (JobStatus.CANCELLED, 0))
            self.assertFalse(queued.steps.exists())

            active = self.queue(account=account, idempotency_key="org-inflight")

            def request(**_):
                set_organization_provider_secret(actor=self.owner, organization=self.organization, account=account,
                                                 secret="dummy-third-key")
                return ProviderResponse("Discarded", None, (), "req_safe", "resp_safe", 3, 2)

            self.assertTrue(execute_ai_text(active.pk, request=request))
            active.refresh_from_db()
            self.assertEqual((active.status, active.output, active.usage.actual_units), (JobStatus.CANCELLED, {}, 1))

    def test_unknown_price_or_tier_fails_closed_and_free_requires_opt_in(self):
        self.assertGreater(Decimal(self.queue().config_snapshot["estimated_max_cost_usd"]), 0)
        with self.assertRaises(ValidationError):
            self.queue(max_cost_usd="NaN")
        with self.assertRaises(ValidationError):
            self.queue(max_cost_usd="0.000001")
        with self.assertRaises(ValidationError):
            self.queue(allow_free=True)
        AIModel.objects.filter(pk=self.model.pk).update(access_tier="unknown")
        with self.assertRaises(ValidationError):
            self.queue(idempotency_key="unknown-tier")
        AIModel.objects.filter(pk=self.model.pk).update(access_tier="standard",
                                                       input_price_usd_per_million=None,
                                                       output_price_usd_per_million=None)
        with self.assertRaises(ValidationError):
            self.queue(idempotency_key="unknown-price")

        AIModel.objects.filter(pk=self.model.pk).update(
            input_price_usd_per_million=Decimal("0.1250"), output_price_usd_per_million=Decimal("2.5000"),
            access_tier="free", privacy_policy_url="https://example.com/data-use")
        with self.assertRaises(ValidationError):
            self.queue(idempotency_key="free-no-opt-in")
        job = self.queue(idempotency_key="free-opt-in", allow_free=True)
        self.assertEqual(job.config_snapshot["model_access_tier"], "free")

    def test_malformed_routing_snapshot_fails_closed_without_provider_attempt(self):
        from .services import queue_job

        with patch("jobs.services.dispatch_pending"):
            with self.captureOnCommitCallbacks(execute=True):
                job = queue_job(project=self.project, actor=self.owner, handler="ai_text",
                                input_snapshot={"model_id": self.model.pk, "account_id": self.account.pk,
                                                "prompt": "Approved", "max_output_tokens": 50,
                                                "max_cost_usd": "0.010000", "allow_free": False},
                                config_snapshot={"routing_source": []}, idempotency_key="invalid-route")
        self.assertTrue(execute_ai_text(job.pk, request=lambda **_: self.fail("bad route must not send")))
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category, job.usage.actual_units),
                         (JobStatus.CANCELLED, "model_unavailable", 0))

    def test_price_change_after_queue_and_during_request_never_publishes_result(self):
        queued = self.queue()
        configure_model(actor=self.operator, provider=self.provider, identifier=self.model.identifier,
                        name=self.model.name, capabilities=[AIModelCapability.TEXT_GENERATION],
                        capability_source="https://example.com/models", capabilities_verified_at=timezone.now(),
                        enabled=True, max_output_tokens=256,
                        input_price_usd_per_million=Decimal("0.1250"),
                        output_price_usd_per_million=Decimal("4.0000"),
                        pricing_source="https://example.com/new-prices", pricing_verified_at=timezone.now(),
                        access_tier="standard")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "dummy-secret"}):
            self.assertTrue(execute_ai_text(queued.pk, request=lambda **_: self.fail("changed price must not send")))
        queued.refresh_from_db()
        self.assertEqual((queued.status, queued.usage.actual_units), (JobStatus.CANCELLED, 0))
        active = self.queue(idempotency_key="model-inflight")

        def request(**_):
            configure_model(actor=self.operator, provider=self.provider, identifier=self.model.identifier,
                            name=self.model.name, capabilities=[AIModelCapability.TEXT_GENERATION],
                            capability_source="https://example.com/models", capabilities_verified_at=timezone.now(),
                            enabled=True, max_output_tokens=256,
                            input_price_usd_per_million=Decimal("0.1250"),
                            output_price_usd_per_million=Decimal("6.0000"),
                            pricing_source="https://example.com/new-prices", pricing_verified_at=timezone.now(),
                            access_tier="standard")
            return ProviderResponse("Discarded", None, (), "req_safe", "resp_safe", 3, 2)

        with patch.dict(os.environ, {"OPENAI_API_KEY": "dummy-secret"}):
            self.assertTrue(execute_ai_text(active.pk, request=request))
        active.refresh_from_db()
        self.assertEqual((active.status, active.output, active.usage.actual_units), (JobStatus.CANCELLED, {}, 1))
