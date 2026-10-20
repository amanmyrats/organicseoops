"""Local synthetic acceptance journey; injected native transport never calls a provider."""
from datetime import timedelta
import json
import os
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from providers.adapters import ProviderResponse
from tenancy.models import OrganizationMembership, OrganizationTrial
from . import test_visibility_entities as fixtures
from .models import AIUsageRecord, JobRun, JobStep
from .visibility_collection import execute_visibility_sample
from .recovery import reconcile_stuck_visibility_samples


@override_settings(STORAGES=TEST_STORAGES, CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class VisibilityJourneyTests(TestCase):
    fixture_project = fixtures.VisibilityEntityTests.fixture_project
    execute = fixtures.VisibilityEntityTests.execute

    def test_authenticated_manual_collection_correction_denominators_failures_history_and_retention(self):
        fixtures.fixture(self)
        browser = Client(enforce_csrf_checks=True); browser.force_login(self.owner)
        browser.get("/_allauth/browser/v1/auth/session", secure=True)
        headers = {"secure": True, "HTTP_X_CSRFTOKEN": browser.cookies["csrftoken"].value,
                   "HTTP_REFERER": "https://testserver/"}
        prefix = f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}/"

        def post(path, data):
            with patch("jobs.services.dispatch_pending"), self.captureOnCommitCallbacks(execute=True):
                return browser.post(prefix + path, json.dumps(data), content_type="application/json", **headers)

        methodology = post("visibility-prompts/", {**self.data, "request_key": "journey-human-methodology"})
        self.assertEqual(methodology.status_code, 201, methodology.content)
        set_id = methodology.json()["prompt_set"]["id"]
        selection = {**self.sample_data, "prompt_set_id": set_id, "idempotency_key": "journey-first-attempt"}
        queued = post("visibility-samples/", selection)
        self.assertEqual(queued.status_code, 202, queued.content)
        job = JobRun.objects.get(pk=queued.json()["job"]["id"])
        answer = "😀 Synthetic Brand <script>untrusted</script> https://127.0.0.1/"
        self.execute(job, lambda **_: ProviderResponse(answer, None, (), "req_fixture", "resp_fixture", 20, 12, "fixture-model"))
        self.assertFalse(execute_visibility_sample(job.pk, request=lambda **_: self.fail("Automatic replay")))
        detail = browser.get(prefix + f"visibility-samples/{job.pk}/").json()["job"]
        self.assertEqual(detail["evidence"]["answer"], answer)
        self.assertEqual(detail["methodology"]["prompt"]["text"], self.prompts[0]["text"])
        self.assertEqual(detail["usage"]["input_tokens"], 20)
        self.assertIsNone(detail["usage"]["reported_cost_usd"])
        self.assertEqual(detail["attempted_units"], 1)
        entities = f"visibility-samples/{job.pk}/entities/"
        self.assertFalse(any(group["eligible_sample_ids"] for group in browser.get(prefix + entities).json()["rates"]["groups"]))
        review = {"request_key": "journey-human-review-one", "expected_revision": 0, "expected_configuration_revision": 2,
            "matches": [{"kind": "brand", "entity": "project_brand", "start": 2, "end": 17,
                         "decision": "uncertain", "note": "Check this actual brand in the full answer."}],
            "evaluated": True, "review_note": "Human review; lexical uncertainty remains.",
            "factual_notes": [{"start": 2, "end": 17, "note": "Verify against actual business records."}]}
        uncertain = post(entities, review); self.assertEqual(uncertain.status_code, 201, uncertain.content)
        self.assertFalse(any(group["eligible_sample_ids"] for group in uncertain.json()["rates"]["groups"]))
        corrected = post(entities, {**review, "request_key": "journey-human-review-two", "expected_revision": 1,
            "matches": [{**review["matches"][0], "decision": "confirmed"}]})
        self.assertEqual(corrected.status_code, 201, corrected.content)
        rates = corrected.json()["rates"]
        eligible = next(group for group in rates["groups"] if job.pk in group["eligible_sample_ids"])
        self.assertEqual(eligible["mention_rate"]["denominator"], 1)
        self.assertEqual(eligible["mention_rate"]["numerator"], 1)
        self.assertIsNone(eligible["citation_rate"]["percent"])
        self.assertEqual(post("visibility-samples/", {**selection, "idempotency_key": "journey-too-early"}).status_code, 409)

        JobStep.objects.all().update(created_at=timezone.now() - timedelta(hours=25))
        partial = post("visibility-samples/", {**selection, "idempotency_key": "journey-partial"})
        partial_id = partial.json()["job"]["id"]
        payload = {"id": "resp_partial", "model": "fixture-model", "status": "incomplete", "usage": {"input_tokens": 7, "output_tokens": 100},
                   "output": [{"type": "message", "content": [{"type": "output_text", "text": "Partial text"}]}]}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic-not-real"}), patch("providers.adapters.post_json", return_value=(200, "req_partial", json.dumps(payload).encode())):
            self.assertTrue(execute_visibility_sample(partial_id))
        partial_review = post(f"visibility-samples/{partial_id}/entities/", {**review, "request_key": "journey-invalid-negative",
            "matches": [], "factual_notes": []})
        self.assertEqual(partial_review.status_code, 409)
        unknown = post("visibility-samples/", {**selection, "prompt_key": "branded-service", "idempotency_key": "journey-unknown"})
        unknown_id = unknown.json()["job"]["id"]
        JobRun.objects.filter(pk=unknown_id).update(status="running", updated_at=timezone.now() - timedelta(minutes=3))
        JobStep.objects.create(job_id=unknown_id, sequence=1, name="Request selected model", status="running")
        self.assertEqual(reconcile_stuck_visibility_samples(), 1)
        self.assertFalse(execute_visibility_sample(unknown_id, request=lambda **_: self.fail("Uncertain replay")))
        self.assertEqual(AIUsageRecord.objects.filter(job__project=self.project).count(), 3)
        final_rates = browser.get(prefix + entities).json()["rates"]
        self.assertEqual(sum(row["mention_rate"]["denominator"] for row in final_rates["groups"]), 1)
        history_response = browser.get(prefix + "visibility-history/"); history = history_response.json()
        self.assertEqual(history_response["Cache-Control"], "private, no-store")
        self.assertEqual(len(history["observations"]), 3)
        self.assertIsNone(history["referrals"]["visits"])
        self.assertEqual(next(row for row in history["observations"] if row["id"] == job.pk)["review_revision"], 2)
        guidance = browser.get(prefix + "visibility-discoverability/").json()
        self.assertEqual(guidance["human_factual_concerns"][0]["text"], "Synthetic Brand")
        self.assertEqual(guidance["proposals"], [])  # Missing crawl data cannot create a technical proposal.
        OrganizationMembership.objects.filter(organization=self.project.organization, user=self.owner).update(role="viewer")
        self.assertEqual(post("visibility-samples/", {**selection, "idempotency_key": "journey-revoked"}).status_code, 403)
        self.assertEqual(browser.get(prefix + "visibility-history/").status_code, 200)
        end = timezone.now() - timedelta(days=91)
        OrganizationTrial.objects.filter(organization=self.project.organization).update(started_at=end - timedelta(days=30), ends_at=end)
        self.assertEqual(browser.get(prefix + "visibility-history/").status_code, 404)
        self.assertTrue(JobRun.objects.filter(pk=job.pk).exists())  # Retained-access cutoff is not deletion.
