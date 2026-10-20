import json
from datetime import timedelta
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from providers.models import AIModel, AIProviderAccount
from tenancy.models import Organization, OrganizationMembership, OrganizationTrial, ProjectConfiguration
from . import competitor_synthesis_api as api
from . import competitor_synthesis_job as synthesis
from . import test_competitor_synthesis_job as fixtures
from .models import AIUsageRecord, Artifact, JobCancellation, JobRun, UsageReservation


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "competitor-synthesis-api"}})
class CompetitorSynthesisApiTests(TransactionTestCase):
    queue = fixtures.CompetitorSynthesisJobTests.queue
    transport = fixtures.CompetitorSynthesisJobTests.transport
    collected = fixtures.CompetitorSynthesisJobTests.collected
    input_data = fixtures.CompetitorSynthesisJobTests.input_data
    pair = fixtures.CompetitorSynthesisJobTests.pair
    response = fixtures.CompetitorSynthesisJobTests.response
    request = fixtures.CompetitorSynthesisJobTests.request

    def setUp(self):
        fixtures.CompetitorSynthesisJobTests.setUp(self)
        cache.clear()
        self.client = Client(enforce_csrf_checks=True); self.client.force_login(self.admin)
        self.client.get("/_allauth/browser/v1/auth/session", secure=True)
        self.csrf = self.client.cookies["csrftoken"].value
        self.base = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/competitor-syntheses/"

    def post(self, suffix="", data=None):
        return self.client.post(self.base + suffix, json.dumps(self.input if data is None else data), content_type="application/json",
            secure=True, HTTP_X_CSRFTOKEN=self.csrf, HTTP_REFERER="https://testserver/")

    def command(self, key="synthesis-api-request"):
        preview = self.post("selection/")
        self.assertEqual(preview.status_code, 200, preview.content)
        self.assertEqual(api._digest(preview.json()["selection"]), preview.json()["selection_digest"])
        return {**self.input, "idempotency_key": key, "selection_digest": preview.json()["selection_digest"]}

    def test_preview_queue_own_key_private_original_notes_nullable_metering_independent_reader_and_cancel(self):
        before, after = self.pair(); self.input = self.input_data(before, after)
        with patch("providers.adapters.create_response", side_effect=AssertionError("No preview provider")), \
             patch("providers.services.resolve_provider_secret", side_effect=AssertionError("No preview secret")):
            command = self.command()
            self.assertFalse(JobRun.objects.filter(handler=synthesis.HANDLER).exists())
            self.assertEqual(self.client.get(self.base + "?idempotency_key=synthesis-api-request", secure=True).json()["jobs"], [])
            queued = self.post(data=command); self.assertEqual(queued.status_code, 202, queued.content)
            job_id = queued.json()["job"]["id"]
            self.assertEqual(self.post(data=command).json()["job"]["id"], job_id)
        waiting = self.client.get(self.base + f"{job_id}/", secure=True)
        self.assertEqual(waiting.status_code, 200, waiting.content)
        self.assertIsNone(waiting.json()["evidence"]); self.assertIsNone(waiting.json()["usage"])
        self.assertEqual(waiting.json()["selection"]["input"], self.input)
        self.assertEqual(waiting.json()["selection_digest"], command["selection_digest"])
        self.assertEqual(self.client.get(self.base + "?idempotency_key=synthesis-api-request", secure=True).json()["jobs"][0]["id"], job_id)
        self.assertTrue(synthesis.execute_competitor_synthesis(job_id, request=self.request))
        detail = self.client.get(self.base + f"{job_id}/", secure=True)
        self.assertEqual(detail.status_code, 200, detail.content)
        body = detail.json()
        self.assertEqual(body["evidence"]["synthesis"]["state"], synthesis.STATE)
        self.assertEqual(body["evidence"]["synthesis"]["comparison"]["previous"]["evidence"], before.output["evidence"])
        self.assertEqual(body["usage"]["status"], "completed"); self.assertIsNone(body["usage"]["reported_cost_usd"])
        self.assertNotIn("provider_request_id", body["usage"]); self.assertNotIn(b"Untrusted raw answer", detail.content)
        self.assertIn("no-store", detail["Cache-Control"]); self.assertEqual(detail["X-Robots-Tag"], "noindex, nofollow")
        other = Client(); other.force_login(self.owner)
        self.assertEqual(other.get(self.base + f"{job_id}/", secure=True).json()["evidence"], body["evidence"])
        self.assertEqual(other.get(self.base + "?idempotency_key=synthesis-api-request", secure=True).json()["jobs"], [])
        cancel_command = self.command("synthesis-api-cancel")
        cancel_id = self.post(data=cancel_command).json()["job"]["id"]
        AIProviderAccount.objects.filter(pk=self.account.pk).update(state="revoked", revoked_at=timezone.now())
        self.assertEqual(self.post(f"{cancel_id}/", {}).status_code, 202)
        self.assertEqual(JobRun.objects.get(pk=cancel_id).status, "cancelled")
        AIProviderAccount.objects.filter(pk=self.account.pk).update(state="active", revoked_at=None)
        unchanged = self.post(data=cancel_command)
        self.assertEqual(unchanged.status_code, 202, unchanged.content)
        self.assertEqual((unchanged.json()["job"]["id"], unchanged.json()["job"]["status"]), (cancel_id, "cancelled"))

    def test_strict_digest_binds_all_input_csrf_query_json_and_current_scope_without_reservation(self):
        before, after = self.pair(); self.input = self.input_data(before, after)
        command = self.command()
        self.assertEqual(self.client.post(self.base, json.dumps(command), content_type="application/json", secure=True).status_code, 403)
        # A different USD ceiling above the same estimate produces identical configuration,
        # but MUST change the command digest because all original inputs are frozen.
        for change in ({"max_cost_usd": "0.020000"}, {"max_output_tokens": 513}, {"ai_processing_permission": False},
            {"allow_free": 1}, {"model_id": True}, {"current_job_id": before.pk}, {"raw_prompt": "private"}, {"selection_digest": "a" * 64}):
            with self.subTest(change=change):
                self.assertIn(self.post(data={**command, **change}).status_code, (403, 409))
        self.assertFalse(JobRun.objects.filter(handler=synthesis.HANDLER).exists())
        for body in ('{"model_id":1,"model_id":2}', '{', '[]', 'null', '{"model_id":NaN}', " " * 2049):
            cache.clear()
            response = self.client.post(self.base, body, content_type="application/json", secure=True,
                HTTP_X_CSRFTOKEN=self.csrf, HTTP_REFERER="https://testserver/")
            self.assertEqual(response.status_code, 409)
        self.assertEqual(self.post("?posted=1", command).status_code, 400)
        for query in ("?extra=1", "?idempotency_key=original-key&idempotency_key=original-key"):
            self.assertEqual(self.client.get(self.base + query, secure=True).status_code, 409)
        self.assertEqual(self.client.get(self.base + "selection/", secure=True).status_code, 405)
        self.assertEqual(Client().get(self.base, secure=True).status_code, 401)
        self.client.force_login(self.foreign); self.assertEqual(self.client.get(self.base, secure=True).status_code, 404)
        self.client.force_login(self.admin)
        EmailAddress.objects.filter(user=self.admin).update(verified=False)
        self.assertEqual(self.client.get(self.base, secure=True).status_code, 403)

    def test_four_independent_synthesis_budgets_shared_ip_and_competitor_read_remains_separate(self):
        before, after = self.pair(); self.input = self.input_data(before, after)
        command = self.command(); job_id = self.post(data=command).json()["job"]["id"]
        other = Client(); other.force_login(self.owner)
        cache.clear()
        limits = {"competitor_synthesis_" + suffix: "1/h/ip" for suffix in ("read", "selection", "request", "cancel")}
        with override_settings(ACCOUNT_RATE_LIMITS=limits):
            self.assertEqual(self.client.get(self.base, secure=True).status_code, 200)
            self.assertEqual(other.get(self.base, secure=True).status_code, 429)
            self.assertEqual(self.post("selection/").status_code, 200); self.assertEqual(self.post("selection/").status_code, 429)
            self.assertEqual(self.post(data=command).status_code, 202); self.assertEqual(self.post(data=command).status_code, 429)
            self.assertEqual(self.post(f"{job_id}/", {}).status_code, 202); self.assertEqual(self.post(f"{job_id}/", {}).status_code, 429)

    def test_queue_post_serialization_full_pair_model_caller_loss_rolls_back_usage_and_dispatch(self):
        before, after = self.pair(); self.input = self.input_data(before, after)
        command = self.command(); response = api._response
        for mutation in (lambda: OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer"),
            lambda: ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2),
            lambda: AIModel.objects.filter(pk=self.model.pk).update(enabled=False),
            lambda: Artifact.objects.filter(job=before).update(created_at=timezone.now()),
            lambda: EmailAddress.objects.filter(user=self.admin).update(verified=False)):
            def changed(data, *args, **kwargs):
                result = response(data, *args, **kwargs)
                if "job" in data: mutation()
                return result
            with patch.object(api, "_response", side_effect=changed), patch("jobs.tasks.execute_competitor_synthesis_task.apply_async") as task:
                result = self.post(data=command)
            self.assertIn(result.status_code, (403, 409), result.content)
            self.assertFalse(JobRun.objects.filter(handler=synthesis.HANDLER).exists()); task.assert_not_called()
            self.assertEqual(UsageReservation.objects.count(), 2)
            self.assertEqual(OrganizationMembership.objects.get(pk=self.membership.pk).role, "admin")

    def test_detail_post_serialization_full_original_pair_ai_model_caller_cancel_and_expiry_withhold(self):
        before, after = self.pair(); self.input = self.input_data(before, after)
        job_id = self.post(data=self.command()).json()["job"]["id"]
        synthesis.execute_competitor_synthesis(job_id, request=self.request)
        original_response = api._response
        for mutation in (lambda: Artifact.objects.filter(job=before).update(created_at=timezone.now()),
            lambda: AIUsageRecord.objects.filter(job_id=job_id).update(duration_ms=1),
            lambda: AIModel.objects.filter(pk=self.model.pk).update(enabled=False),
            lambda: OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer"),
            lambda: JobCancellation.objects.create(job_id=job_id, requested_by=self.owner)):
            with transaction.atomic():
                def changed(data, *args, **kwargs):
                    result = original_response(data, *args, **kwargs)
                    if "evidence" in data: mutation()
                    return result
                with patch.object(api, "_response", side_effect=changed): result = self.client.get(self.base + f"{job_id}/", secure=True)
                self.assertIn(result.status_code, (403, 409), result.content); self.assertNotIn(b"interpretations", result.content)
                transaction.set_rollback(True)
        trial = OrganizationTrial.objects.get(organization=self.organization)
        now = [timezone.now()]; ends = now[0] + timedelta(seconds=10)
        OrganizationTrial.objects.filter(pk=trial.pk).update(started_at=ends - timedelta(days=30), ends_at=ends)
        def expire(data, *args, **kwargs):
            result = original_response(data, *args, **kwargs)
            if "evidence" in data: now[0] = ends
            return result
        with patch("jobs.usage.timezone.now", side_effect=lambda: now[0]), patch.object(api, "_response", side_effect=expire):
            result = self.client.get(self.base + f"{job_id}/", secure=True)
        self.assertEqual(result.status_code, 403); self.assertNotIn(b"interpretations", result.content)
        self.assertEqual(self.client.get(self.base, secure=True).status_code, 200)  # Retained status is separate.

    def test_final_unchanged_api_metadata_fences_queue_and_independent_private_detail(self):
        before, after = self.pair(); self.input = self.input_data(before, after)
        job_id = self.post(data=self.command("final-api-healthy")).json()["job"]["id"]
        self.assertTrue(synthesis.execute_competitor_synthesis(job_id, request=self.request))
        self.assertEqual(JobRun.objects.get(pk=job_id).status, "succeeded")
        reader = get_user_model().objects.create_user("third-synthesis-api-reader@example.invalid", "test-password")
        EmailAddress.objects.create(user=reader, email=reader.email, primary=True, verified=True)
        membership = OrganizationMembership.objects.create(organization=self.organization, user=reader, role="admin")
        self.assertEqual(len({before.actor_id, self.admin.pk, reader.pk}), 3)
        client = Client(); client.force_login(reader)
        url = self.base + f"{job_id}/"
        healthy = client.get(url, secure=True)
        self.assertEqual(healthy.status_code, 200, healthy.content)
        expected = healthy.json()["evidence"]
        metadata = api._metadata
        for phase in ("queue", "detail"):
            losses = ("collector", "synthesis-actor", "revision", "approval-list", "first-cancel", "own-cancel",
                "model", "account", "organization", "expiry") + (("caller", "caller-role") if phase == "detail" else ())
            for loss in losses:
                command = self.command("final-api-" + loss) if phase == "queue" else None
                with self.subTest(phase=phase, loss=loss), transaction.atomic():
                    cache.clear()
                    now = [timezone.now()]; ends = now[0] + timedelta(seconds=20)
                    OrganizationTrial.objects.filter(organization=self.organization).update(started_at=ends - timedelta(days=30), ends_at=ends)
                    pins = []
                    def last_metadata(job):
                        result = metadata(job)
                        pins.append(result)
                        if len(pins) == 2:
                            self.assertEqual(result, pins[0])
                            self.assertEqual(set(result["pair"]), {before.pk, after.pk})
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
                    with patch.object(api, "_metadata", side_effect=last_metadata), \
                         patch("jobs.usage.timezone.now", side_effect=lambda: now[0]), \
                         patch("jobs.tasks.execute_competitor_synthesis_task.apply_async") as dispatch:
                        result = self.post(data=command) if phase == "queue" else client.get(url, secure=True)
                        self.assertEqual(len(pins), 2)
                        self.assertIn(result.status_code, (403, 409), result.content)
                        self.assertNotIn(b"interpretations", result.content)
                        self.assertIn("no-store", result["Cache-Control"])
                        self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")
                        if phase == "queue":
                            self.assertFalse(JobRun.objects.filter(handler=synthesis.HANDLER, idempotency_key=command["idempotency_key"]).exists())
                            self.assertEqual(UsageReservation.objects.count(), 3)
                            self.assertEqual(AIUsageRecord.objects.count(), 1)
                        dispatch.assert_not_called()
                    transaction.set_rollback(True)
        cache.clear()
        self.assertEqual(client.get(url, secure=True).json()["evidence"], expected)
        self.assertEqual(self.post(data=self.command("final-api-positive-after")).status_code, 202)
