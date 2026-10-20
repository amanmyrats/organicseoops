from datetime import timedelta
import json
import os
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TransactionTestCase, override_settings
from django.test import Client
from django.utils import timezone
from kombu.exceptions import OperationalError

from config.test_foundations import TEST_STORAGES
from providers.adapters import ProviderRequestError, ProviderResponse
from tenancy.models import OrganizationMembership, ProjectConfiguration
from .content_generation import execute_content_generation, queue_content_generation
from .models import AIUsageRecord, ContentRevision, JobCancellation, JobRun, JobStatus, JobStep
from .recovery import reconcile_stuck_content_generation
from .services import dispatch_pending, retry_job


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}), DEBUG=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "generation-fixtures"}})
class ContentGenerationTests(TransactionTestCase):
    def setUp(self):
        from .test_content import ContentTests
        ContentTests.setUp(self)
        self.generation_input = {"brief_id": self.brief.pk, "source_revision_id": None, "kind": "refresh", "platform": "",
            "model_id": self.model.pk, "account_id": self.account.pk, "max_output_tokens": 512,
            "max_cost_usd": "0.1", "allow_free": False}

    def queue(self, key="generation-fixture-1", **changes):
        with patch("jobs.services.dispatch_pending"):
            return queue_content_generation(project=self.project, actor=self.owner,
                data={**self.generation_input, **changes}, idempotency_key=key)

    def response(self, **kwargs):
        self.assertIn("untrusted data", kwargs["prompt"])
        self.assertIn("no_provider_verified_facts_available", kwargs["prompt"])
        self.assertNotIn("web_search", kwargs)
        data = {"title": "Unverified model title", "meta_description": "Unverified meta draft",
            "sections": [{"text": "A service question needing original expertise.", "source_index": 0, "quote": "Evidence useful."}]}
        return ProviderResponse(json.dumps(data), data, (), "req_draft", "resp_draft", 45, 40)

    def execute(self, job, request=None):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-not-real"}):
            return execute_content_generation(job.pk, request=request or self.response)

    def test_one_metered_unapproved_revision_retains_citations_job_and_no_duplicate_request(self):
        job = self.queue()
        self.assertEqual(self.queue().pk, job.pk)
        self.assertEqual(job.usage.reserved_units, 1)
        with patch("jobs.tasks.execute_content_generation_task.apply_async") as task:
            self.assertTrue(dispatch_pending(job.pk))
        self.assertEqual(task.call_args.kwargs["queue"], "ai")
        self.assertTrue(self.execute(job))
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.SUCCEEDED, job.error_category)
        revision = ContentRevision.objects.get(generating_job=job)
        self.assertEqual((revision.state, revision.reviewed_revision_id, revision.approved_by_id), ("draft", None, None))
        self.assertIn("UNVERIFIED INTERPRETATION", revision.body)
        self.assertIn("Evidence useful.", revision.body)
        self.assertEqual(job.output["publication"], "not_attempted")
        self.assertEqual(job.ai_usage_record.operation_version, "content-generation-v1")
        self.assertEqual((job.ai_usage_record.input_tokens, job.ai_usage_record.output_tokens), (45, 40))
        self.assertIsNone(job.ai_usage_record.reported_cost_usd)
        self.assertFalse(self.execute(job, request=lambda **_: self.fail("Must not duplicate provider use")))
        self.assertEqual(ContentRevision.objects.filter(generating_job=job).count(), 1)
        from .content import record_content
        review_fields = {"project": self.project, "actor": self.owner, "brief_id": revision.brief_id,
            "kind": revision.kind, "title": revision.title, "body": revision.body,
            "meta_description": revision.meta_description, "item_id": revision.item_id,
            "reason": "Human review of exact generated draft and unverified source claims."}
        review = record_content(**review_fields, request_key="generated-review-001", state="review",
                                expected_revision=revision.revision)
        approved = record_content(**review_fields, request_key="generated-approval-001", state="approved",
                                  expected_revision=review.revision)
        self.assertEqual((approved.generating_job_id, approved.reviewed_revision_id), (job.pk, review.pk))

    def test_variants_require_exact_current_approved_source_and_keep_separate_review(self):
        from .test_content import ContentTests
        source = ContentTests.record(self)
        with self.assertRaises(ValidationError):
            self.queue(source_revision_id=source.pk, kind="social", platform="linkedin")
        review = ContentTests.record(self, source, request_key="variant-review-001", state="review")
        approved = ContentTests.record(self, review, request_key="variant-approval-001", state="approved")
        job = self.queue(source_revision_id=approved.pk, kind="social", platform="linkedin")
        self.assertTrue(self.execute(job))
        job.refresh_from_db()
        variant = ContentRevision.objects.get(generating_job=job)
        self.assertEqual((variant.kind, variant.state), ("social", "draft"))
        self.assertNotEqual(variant.item_id, approved.item_id)
        self.assertEqual(job.output["source_revision_id"], approved.pk)
        self.assertIsNone(variant.approved_at)
        duplicate = self.queue(key="duplicate-native-platform", source_revision_id=approved.pk, kind="social", platform="instagram")
        self.assertTrue(self.execute(duplicate))
        duplicate.refresh_from_db()
        self.assertEqual((duplicate.status, duplicate.error_category), (JobStatus.FAILED, "generation_output_invalid"))
        ContentTests.record(self, approved, request_key="variant-source-edit", body="Changed source text")
        with self.assertRaises(ValidationError):
            self.queue(key="stale-variant-source", source_revision_id=approved.pk, kind="social", platform="x")

    def test_invalid_citation_marks_failed_but_meters_attempt_and_never_saves_claim_as_fact(self):
        job = self.queue()
        def invalid(**kwargs):
            response = self.response(**kwargs)
            response.structured["sections"][0]["quote"] = "Invented quote"
            return response
        self.assertTrue(self.execute(job, request=invalid))
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category), (JobStatus.FAILED, "generation_output_invalid"))
        self.assertFalse(ContentRevision.objects.filter(generating_job=job).exists())
        self.assertEqual(job.usage.actual_units, 1)
        self.assertEqual(job.ai_usage_record.input_tokens, 45)

    def test_unknown_attempt_and_broker_failure_recover_without_paid_replay(self):
        job = self.queue()
        with patch("jobs.tasks.execute_content_generation_task.apply_async", side_effect=OperationalError("fixture")):
            self.assertFalse(dispatch_pending(job.pk))
        job.status = JobStatus.RUNNING; job.save(update_fields=["status", "updated_at"])
        step = JobStep.objects.create(job=job, sequence=1, name="Committed provider attempt", status=JobStep.Status.RUNNING)
        from .ai_usage import record_ai_attempt
        record_ai_attempt(job=job, step=step)
        JobRun.objects.filter(pk=job.pk).update(updated_at=timezone.now() - timedelta(seconds=100))
        self.assertEqual(reconcile_stuck_content_generation(), 1)
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category), (JobStatus.FAILED, "request_outcome_unknown"))
        self.assertEqual(job.ai_usage_record.status, AIUsageRecord.Status.UNKNOWN)
        self.assertFalse(self.execute(job, request=lambda **_: self.fail("No replay")))
        with self.assertRaises(ValidationError):
            retry_job(job=job, actor=self.owner, idempotency_key="generation-blind-retry")

    def test_cancel_scope_and_membership_changes_stop_request_or_output_but_keep_consumed_usage(self):
        with self.assertRaises(PermissionDenied):
            queue_content_generation(project=self.project, actor=self.viewer, data=self.generation_input,
                                     idempotency_key="viewer-generation")
        job = self.queue()
        JobCancellation.objects.create(job=job, requested_by=self.owner)
        self.assertTrue(self.execute(job, request=lambda **_: self.fail("No canceled provider use")))
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.CANCELLED)
        self.assertEqual(job.usage.actual_units, 0)
        inflight = self.queue(key="inflight-generation")
        def revoke(**kwargs):
            result = self.response(**kwargs)
            OrganizationMembership.objects.filter(organization=self.org, user=self.owner).delete()
            return result
        self.assertTrue(self.execute(inflight, request=revoke))
        inflight.refresh_from_db()
        self.assertEqual((inflight.status, inflight.error_category), (JobStatus.CANCELLED, "actor_revoked"))
        self.assertEqual(inflight.usage.actual_units, 1)
        self.assertFalse(ContentRevision.objects.filter(generating_job=inflight).exists())

    def test_private_api_csrf_foreign_source_cost_expiry_and_inflight_scope_change(self):
        path = f"/api/organizations/{self.org.pk}/projects/{self.project.pk}/content-generation/"
        client = Client(enforce_csrf_checks=True); client.force_login(self.owner)
        body = {**self.generation_input, "idempotency_key": "api-generation-test"}
        self.assertEqual(client.post(path, json.dumps(body), content_type="application/json").status_code, 403)
        client.get("/_allauth/browser/v1/auth/session")
        headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value}
        with patch("jobs.services.dispatch_pending"):
            response = client.post(path, json.dumps(body), content_type="application/json", **headers)
        self.assertEqual(response.status_code, 202, response.content)
        job_id = response.json()["job"]["id"]
        foreign = Client(); foreign.force_login(self.other)
        self.assertEqual(foreign.get(f"{path}{job_id}/").status_code, 404)
        self.assertEqual(foreign.get(path).status_code, 404)
        with self.assertRaises(ValidationError):
            self.queue(key="cost-too-low", max_cost_usd="0.000001")
        with self.assertRaises(PermissionDenied):
            self.queue(key="foreign-brief-id", brief_id=self.brief.pk + 999)
        expired = JobRun.objects.get(pk=job_id)
        from tenancy.models import OrganizationTrial
        OrganizationTrial.objects.filter(organization=self.org).update(started_at=timezone.now() - timedelta(days=31),
                                                                      ends_at=timezone.now() - timedelta(days=1))
        self.assertTrue(self.execute(expired, request=lambda **_: self.fail("No expired provider request")))
        expired.refresh_from_db()
        self.assertEqual((expired.status, expired.error_category), (JobStatus.CANCELLED, "trial_unavailable"))
        now = timezone.now()
        OrganizationTrial.objects.filter(organization=self.org).update(started_at=now, ends_at=now + timedelta(days=30))
        inflight = self.queue(key="scope-change-generation")
        def change_source(**kwargs):
            result = self.response(**kwargs)
            ProjectConfiguration.objects.filter(project=self.project).update(research_allowed_origins=[])
            return result
        self.assertTrue(self.execute(inflight, request=change_source))
        inflight.refresh_from_db()
        self.assertEqual((inflight.status, inflight.error_category), (JobStatus.CANCELLED, "content_source_changed"))
        self.assertEqual(inflight.usage.actual_units, 1)
        self.assertFalse(ContentRevision.objects.filter(generating_job=inflight).exists())

    def test_provider_failure_no_key_rotation_token_and_privacy_gates(self):
        with self.assertRaises(ValidationError):
            self.queue(key="invalid-token-budget", max_output_tokens=2049)
        with self.assertRaises(ValidationError):
            self.queue(key="invalid-free-consent", allow_free=True)
        no_key = self.queue(key="generation-key-missing")
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            self.assertTrue(execute_content_generation(no_key.pk, request=lambda **_: self.fail("No key")))
        no_key.refresh_from_db()
        self.assertEqual((no_key.status, no_key.error_category, no_key.usage.actual_units),
                         (JobStatus.FAILED, "credential_unavailable", 0))
        failed = self.queue(key="generation-provider-failure")
        def refusal(**_):
            raise ProviderRequestError("refused", request_id="req_safe", input_tokens=20, output_tokens=1)
        self.assertTrue(self.execute(failed, request=refusal))
        failed.refresh_from_db()
        self.assertEqual((failed.status, failed.error_category, failed.usage.actual_units), (JobStatus.FAILED, "refused", 1))
        self.assertEqual(failed.ai_usage_record.input_tokens, 20)
        rotation = self.queue(key="generation-key-rotation")
        def rotate(**kwargs):
            result = self.response(**kwargs)
            from providers.models import AIProviderAccount
            AIProviderAccount.objects.filter(pk=self.account.pk).update(rotated_at=timezone.now())
            return result
        self.assertTrue(self.execute(rotation, request=rotate))
        rotation.refresh_from_db()
        self.assertEqual((rotation.status, rotation.error_category, rotation.usage.actual_units),
                         (JobStatus.CANCELLED, "content_source_changed", 1))
        self.assertFalse(ContentRevision.objects.filter(generating_job=rotation).exists())
