from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
import json
import os
from threading import Barrier
from unittest.mock import patch
from zipfile import ZipFile

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from providers.adapters import ProviderRequestError, ProviderResponse
from providers.models import AIModel, AIModelCapability, AIProvider
from providers.services import configure_model, create_provider, create_provider_account, revoke_provider_account
from tenancy.models import Organization, OrganizationTrial, ProjectConfiguration
from tenancy.models import OrganizationMembership, MembershipRole
from .models import AIUsageRecord, JobCancellation, JobRun, JobStatus, JobStep
from .recovery import reconcile_stuck_visibility_samples
from .services import dispatch_pending, queue_job, retry_job
from . import test_visibility_prompts as prompt_fixtures
from .visibility_collection import execute_visibility_sample, queue_visibility_sample
from .visibility_prompts import review_prompt_set


def fixture(test):
    prompt_fixtures.VisibilityPromptTests.setUp(test)
    test.operator = get_user_model().objects.create_superuser("visibility-operator@example.invalid", "test-password")
    test.provider = create_provider(actor=test.operator, key="visibility-openai", name="Synthetic OpenAI", kind=AIProvider.Kind.OPENAI, enabled=True)
    test.account = create_provider_account(actor=test.operator, provider=test.provider, label="Synthetic platform", secret_reference="env:OPENAI_API_KEY")
    test.model = configure_model(actor=test.operator, provider=test.provider, identifier="fixture-model", name="Synthetic model",
        capabilities=[AIModelCapability.TEXT_GENERATION], max_output_tokens=256, enabled=True,
        capability_source="https://example.invalid/models", capabilities_verified_at=timezone.now(),
        pricing_source="https://example.invalid/prices", pricing_verified_at=timezone.now(), access_tier="standard",
        input_price_usd_per_million=Decimal("0.125"), output_price_usd_per_million=Decimal("2.5"))
    test.prompt_set = review_prompt_set(project=test.project, actor=test.owner, **test.data)
    test.sample_data = {"prompt_set_id": test.prompt_set.pk, "prompt_key": "neutral-service", "model_id": test.model.pk,
        "account_id": test.account.pk, "max_output_tokens": 100, "max_cost_usd": "0.01", "acknowledge_api_limits": True}


@override_settings(STORAGES=TEST_STORAGES, CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class VisibilityCollectionTests(TransactionTestCase):
    fixture_project = prompt_fixtures.VisibilityPromptTests.fixture_project

    def setUp(self):
        dispatch = patch("jobs.services.dispatch_pending", return_value=False)
        self.addCleanup(dispatch.stop)
        dispatch.start()
        fixture(self)

    def queue(self, key="sample-request-1", **changes):
        with patch("jobs.services.dispatch_pending"):
            return queue_visibility_sample(project=self.project, actor=self.owner,
                data={**self.sample_data, **changes}, idempotency_key=key)

    def execute(self, job, request=None):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "dummy-fixture-key"}):
            return execute_visibility_sample(job.pk, request=request or (lambda **_: ProviderResponse(
                " Exact <script>alert(1)</script> javascript:bad https://127.0.0.1/ answer\n", None, (), "req_ok", "resp_ok", 12, 5, "fixture-model")))

    def test_exact_prompt_native_transport_evidence_usage_and_no_replay(self):
        job = self.queue()
        self.assertEqual(self.queue().pk, job.pk)
        with patch("jobs.tasks.execute_visibility_sample_task.apply_async") as send:
            self.assertTrue(dispatch_pending(job.pk))
        self.assertEqual(send.call_args.kwargs["queue"], "ai")
        payload = {"id": "resp_ok", "model": "fixture-model", "status": "completed", "usage": {"input_tokens": 12, "output_tokens": 5},
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "  Exact answer\n"}]}]}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "dummy-fixture-key"}), patch("providers.adapters.post_json",
            return_value=(200, "req_ok", json.dumps(payload).encode())) as transport:
            self.assertTrue(execute_visibility_sample(job.pk))
        sent = json.loads(transport.call_args.kwargs["body"])
        self.assertEqual(sent, {"model": "fixture-model", "input": self.prompts[0]["text"], "store": False, "max_output_tokens": 100})
        job.refresh_from_db()
        self.assertEqual(job.output["answer"], "  Exact answer\n")
        self.assertEqual((job.status, job.output["evaluation"], job.output["citations"], job.usage.actual_units), ("succeeded", "unevaluated", None, 1))
        self.assertEqual((job.ai_usage_record.input_tokens, job.ai_usage_record.reported_cost_usd), (12, None))
        self.assertFalse(execute_visibility_sample(job.pk, request=lambda **_: self.fail("replay")))
        self.assertEqual(AIUsageRecord.objects.filter(job=job).count(), 1)
        job.output["answer"] = "Tampered evidence"
        with self.assertRaises(ValidationError): job.save()
        with self.assertRaises(ValidationError): self.queue("sample-request-2")
        with self.assertRaises(ValidationError): retry_job(job=job, actor=self.owner, idempotency_key="generic-retry")

    def test_repeat_cooldown_across_revision_and_exact_24_hour_boundary(self):
        job = self.queue()
        with self.assertRaises(ValidationError): self.queue("parallel-request")
        self.execute(job)
        revised = review_prompt_set(project=self.project, actor=self.owner, **{**self.data, "request_key": "review-correction",
            "set_id": self.prompt_set.set_id, "expected_revision": 1, "label": "Human revised label"})
        with self.assertRaises(ValidationError): self.queue("revised-request", prompt_set_id=revised.pk)
        now = timezone.now()
        JobStep.objects.filter(job=job).update(created_at=now - timedelta(hours=24))
        with patch("jobs.visibility_collection.timezone.now", return_value=now):
            next_job = self.queue("revised-request", prompt_set_id=revised.pk)
        self.assertNotEqual(next_job.pk, job.pk)
        with self.assertRaises(ValidationError): self.queue("stale-request")

    def test_foreign_inputs_non_native_free_unknown_and_excess_budget_fail_without_job(self):
        foreign = review_prompt_set(project=self.foreign_project, actor=self.other, **{**self.data,
            "prompts": [{**row, "intent_review_id": self.foreign_mapping.pk} for row in self.prompts]})
        for changes in ({"prompt_set_id": foreign.pk}, {"prompt_key": "missing"}, {"max_output_tokens": 129},
            {"max_output_tokens": True}, {"max_cost_usd": "0.06"}, {"max_cost_usd": "0.000001"}, {"acknowledge_api_limits": False}):
            with self.subTest(changes=changes), self.assertRaises((PermissionDenied, ValidationError)): self.queue(**changes)
        for tier in ("free", "unknown"):
            AIModel.objects.filter(pk=self.model.pk).update(access_tier=tier)
            with self.assertRaises(ValidationError): self.queue()
        AIModel.objects.filter(pk=self.model.pk).update(access_tier="standard")
        AIProvider.objects.filter(pk=self.provider.pk).update(kind="openai_compatible", base_url="https://example.invalid/v1", egress_policy="public_https")
        with self.assertRaises(ValidationError): self.queue()
        self.assertFalse(JobRun.objects.exists())

    def test_pre_attempt_missing_key_cancel_source_change_and_expiry_release_zero(self):
        job = self.queue()
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            self.assertTrue(execute_visibility_sample(job.pk, request=lambda **_: self.fail("missing key")))
        job.refresh_from_db(); self.assertEqual(job.usage.actual_units, 0); self.assertFalse(job.steps.exists())
        cancelled = self.queue("cancelled-before")
        JobCancellation.objects.create(job=cancelled, requested_by=self.owner)
        self.execute(cancelled, lambda **_: self.fail("cancelled"))
        expired = self.queue("expired-before")
        OrganizationTrial.objects.filter(organization=self.project.organization).update(ends_at=timezone.now() - timedelta(seconds=1))
        self.execute(expired, lambda **_: self.fail("expired"))
        expired.refresh_from_db(); self.assertEqual(expired.usage.actual_units, 0)
        self.assertFalse(AIUsageRecord.objects.exists())

    def test_inflight_cancel_expiry_and_source_revocation_preserve_private_unevaluated_evidence(self):
        trial_end = OrganizationTrial.objects.get(organization=self.project.organization).ends_at
        for category in ("cancel", "expiry", "source"):
            with self.subTest(category=category):
                # Different selected prompt keys still have the same per-key policy.
                JobStep.objects.all().update(created_at=timezone.now() - timedelta(hours=25))
                OrganizationTrial.objects.filter(organization=self.project.organization).update(ends_at=trial_end)
                ProjectConfiguration.objects.filter(project=self.project).update(seed_topics=["service questions"])
                job = self.queue("inflight-" + category)
                def request(**_):
                    if category == "cancel": JobCancellation.objects.create(job=job, requested_by=self.owner)
                    if category == "expiry": OrganizationTrial.objects.filter(organization=self.project.organization).update(ends_at=timezone.now() - timedelta(seconds=1))
                    if category == "source": ProjectConfiguration.objects.filter(project=self.project).update(seed_topics=[])
                    return ProviderResponse("Private exact collected answer", None, (), "req_ok", "resp_ok", 3, 2)
                self.execute(job, request)
                job.refresh_from_db()
                self.assertEqual((job.status, job.usage.actual_units, job.output["answer"], job.output["collection_eligible"]),
                    ("cancelled", 1, "Private exact collected answer", False))
                self.assertEqual(job.ai_usage_record.status, "completed")

    def test_partial_provider_evidence_unknown_recovery_and_rate_limit_never_replay(self):
        job = self.queue()
        payload = {"id": "resp_partial", "model": "fixture-model", "status": "incomplete", "usage": {"input_tokens": 7, "output_tokens": 100},
            "output": [{"type": "message", "content": [{"type": "output_text", "text": " Exact partial answer "}]}]}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "dummy-fixture-key"}), patch("providers.adapters.post_json", return_value=(200, "req_partial", json.dumps(payload).encode())):
            self.assertTrue(execute_visibility_sample(job.pk))
        job.refresh_from_db()
        self.assertEqual((job.status, job.output["answer"], job.output["collection_eligible"], job.usage.actual_units), ("failed", " Exact partial answer ", False, 1))
        self.assertEqual(job.ai_usage_record.input_tokens, 7)
        second = self.queue("other-prompt", prompt_key="branded-service")
        JobRun.objects.filter(pk=second.pk).update(status=JobStatus.RUNNING, updated_at=timezone.now() - timedelta(minutes=3))
        JobStep.objects.create(job=second, sequence=1, name="Request selected model", status="running")
        self.assertEqual(reconcile_stuck_visibility_samples(), 1)
        self.assertFalse(execute_visibility_sample(second.pk, request=lambda **_: self.fail("unknown replay")))
        second.refresh_from_db(); self.assertEqual((second.usage.actual_units, second.ai_usage_record.status), (1, "unknown"))
        with self.assertRaises(ValidationError): retry_job(job=second, actor=self.owner, idempotency_key="generic-retry")

    def test_private_answer_customer_export_and_scoped_deletion(self):
        from tenancy.customer_export import complete_bounded_customer_archive
        from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        job = self.queue(); self.execute(job); job.refresh_from_db()
        archive = complete_bounded_customer_archive(organization=self.project.organization, actor=self.owner)
        with ZipFile(BytesIO(archive)) as zipped:
            rows = json.loads(zipped.read("records/jobs/JobRun.json"))
        self.assertEqual(rows[0]["output"]["answer"], job.output["answer"])
        Organization.objects.filter(pk=self.project.organization_id).update(is_suspended=True, closed_at=timezone.now())
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.project.organization))
        delete_customer_database_records(run=run)
        self.assertFalse(JobRun.objects.filter(pk=job.pk).exists())
        self.assertFalse(AIUsageRecord.objects.filter(job_id=job.pk).exists())

    def test_scoped_api_csrf_roles_catalog_history_and_safe_exact_answer(self):
        path = f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}/visibility-samples/"
        browser = Client(enforce_csrf_checks=True)
        self.assertEqual(browser.get(path).status_code, 401)
        browser.force_login(self.other); self.assertEqual(browser.get(path).status_code, 404)
        browser.force_login(self.owner)
        body = {**self.sample_data, "idempotency_key": "browser-sample"}
        self.assertEqual(browser.post(path, json.dumps(body), content_type="application/json").status_code, 403)
        browser.get("/_allauth/browser/v1/auth/session", secure=True)
        headers = {"secure": True, "HTTP_X_CSRFTOKEN": browser.cookies["csrftoken"].value, "HTTP_REFERER": "https://testserver/"}
        catalog = browser.get(path)
        self.assertEqual(catalog["Cache-Control"], "private, no-store")
        self.assertEqual(catalog.json()["models"][0]["id"], self.model.pk)
        self.assertFalse(catalog.json()["automatic_schedule"])
        with patch("jobs.services.dispatch_pending"):
            response = browser.post(path, json.dumps(body), content_type="application/json", **headers)
        self.assertEqual(response.status_code, 202, response.content)
        job = JobRun.objects.get(pk=response.json()["job"]["id"]); self.execute(job); job.refresh_from_db()
        detail = browser.get(path + str(job.pk) + "/").json()["job"]
        self.assertEqual(detail["evidence"]["answer"], job.output["answer"])
        self.assertEqual(detail["methodology"]["prompt"]["text"], self.prompts[0]["text"])
        self.assertIsNone(browser.get(path).json()["jobs"][0]["evidence"])
        self.assertEqual(browser.get(path + "999999/").status_code, 404)
        OrganizationMembership.objects.create(organization=self.project.organization, user=self.other, role=MembershipRole.VIEWER)
        browser.force_login(self.other); browser.get("/_allauth/browser/v1/auth/session", secure=True)
        headers["HTTP_X_CSRFTOKEN"] = browser.cookies["csrftoken"].value
        self.assertEqual(browser.get(path + str(job.pk) + "/").status_code, 200)
        body["idempotency_key"] = "viewer-new-sample"
        self.assertEqual(browser.post(path, json.dumps(body), content_type="application/json", **headers).status_code, 403)
        browser.force_login(self.owner); browser.get("/_allauth/browser/v1/auth/session", secure=True)
        headers["HTTP_X_CSRFTOKEN"] = browser.cookies["csrftoken"].value
        self.assertEqual(browser.post(path, json.dumps(body), content_type="application/json", **headers).json()["code"], "sample_repeat_cooldown")

    def test_key_revocation_model_change_actor_revoke_and_rate_limit_are_once_only(self):
        job = self.queue()
        AIModel.objects.filter(pk=self.model.pk).update(enabled=False)
        with patch("jobs.tasks.execute_visibility_sample_task.apply_async") as send:
            self.assertFalse(dispatch_pending(job.pk)); send.assert_not_called()
        job.refresh_from_db(); self.assertEqual(job.usage.actual_units, 0)
        AIModel.objects.filter(pk=self.model.pk).update(enabled=True)
        limited = self.queue("rate-limited")
        self.execute(limited, lambda **_: (_ for _ in ()).throw(ProviderRequestError("rate_limited", retryable=True)))
        limited.refresh_from_db(); self.assertEqual((limited.status, limited.usage.actual_units, limited.output), ("failed", 1, {}))
        self.assertFalse(execute_visibility_sample(limited.pk, request=lambda **_: self.fail("retry")))
        revoked = self.queue("revoked-inflight", prompt_key="branded-service")
        def request(**_):
            revoke_provider_account(actor=self.operator, account=self.account)
            return ProviderResponse("Private retained evidence", None, (), "req_ok", "resp_ok", 3, 2)
        self.execute(revoked, request)
        revoked.refresh_from_db(); self.assertEqual((revoked.status, revoked.usage.actual_units, revoked.output["collection_eligible"]), ("cancelled", 1, False))

    def test_actor_revocation_during_request_and_refusal_preserve_only_private_evidence(self):
        refusal = self.queue()
        payload = {"id": "resp_refused", "model": "fixture-model", "status": "completed", "usage": {"input_tokens": 7, "output_tokens": 1},
            "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "Exact refusal <script> text"}]}]}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "dummy-fixture-key"}), patch("providers.adapters.post_json", return_value=(200, "req_refused", json.dumps(payload).encode())):
            self.assertTrue(execute_visibility_sample(refusal.pk))
        refusal.refresh_from_db()
        self.assertEqual((refusal.output["answer"], refusal.error_category, refusal.usage.actual_units, refusal.output["collection_eligible"]),
            ("Exact refusal <script> text", "refused", 1, False))
        job = self.queue("actor-revoked", prompt_key="branded-service")
        def request(**_):
            get_user_model().objects.filter(pk=self.owner.pk).update(is_active=False)
            return ProviderResponse("Private answer after actor revocation", None, (), "req_ok", "resp_ok", 3, 2)
        self.execute(job, request); job.refresh_from_db()
        self.assertEqual((job.status, job.error_category, job.usage.actual_units, job.output["collection_eligible"]), ("cancelled", "actor_revoked", 1, False))
        browser = Client(); browser.force_login(self.owner)
        self.assertEqual(browser.get(f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}/visibility-samples/{job.pk}/").status_code, 401)

    def test_unstorable_provider_unicode_keeps_usage_without_invalid_json_or_replay(self):
        for index, text in enumerate(("invalid\x00answer", "invalid\ud800answer")):
            job = self.queue("invalid-unicode-" + str(index), prompt_key=self.prompts[index]["key"])
            self.execute(job, lambda **_: ProviderResponse(text, None, (), "req_ok", "resp_ok", 12, 1))
            job.refresh_from_db()
            self.assertEqual((job.status, job.error_category, job.output, job.usage.actual_units), ("failed", "sample_output_invalid", {}, 1))
            self.assertEqual((job.ai_usage_record.status, job.ai_usage_record.input_tokens), ("completed", 12))
            self.assertFalse(execute_visibility_sample(job.pk, request=lambda **_: self.fail("replay")))


@override_settings(STORAGES=TEST_STORAGES, CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class VisibilityCollectionConcurrencyTests(TransactionTestCase):
    fixture_project = prompt_fixtures.VisibilityPromptTests.fixture_project

    def setUp(self): fixture(self)

    def test_two_connections_reserve_only_one_sample_for_one_set_prompt(self):
        barrier = Barrier(2)
        def launch(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    queue_visibility_sample(project=self.project, actor=self.owner, data=self.sample_data, idempotency_key=f"race-request-{index}")
                    return "queued"
                except ValidationError: return "cooldown"
            finally: close_old_connections()
        with patch("jobs.services.dispatch_pending"), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(launch, index) for index in (1, 2)]
            self.assertEqual(sorted(item.result(timeout=40) for item in futures), ["cooldown", "queued"])
        self.assertEqual(JobRun.objects.filter(handler="sample_ai_visibility").count(), 1)
