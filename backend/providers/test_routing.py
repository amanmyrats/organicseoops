import json
import os
from decimal import Decimal
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from jobs.ai_text import execute_ai_text, queue_routed_ai_text
from jobs.models import JobRun, JobStatus
from providers.adapters import ProviderRequestError
from tenancy.models import AuditEvent, AuditEventType
from tenancy.services import create_organization, create_project

from .models import AIModel, AIModelCapability, AIProvider, AIProviderAccount, AIRoutingPolicy
from .routing import configure_ai_text_route
from .services import configure_model, create_provider, create_provider_account


@override_settings(STAFF_MFA_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class RoutingPolicyTests(TestCase):
    def setUp(self):
        self.operator = get_user_model().objects.create_superuser("route-staff@example.com", "test-password")
        self.owner = get_user_model().objects.create_user("route-owner@example.com", "test-password")
        self.other = get_user_model().objects.create_user("route-other@example.com", "test-password")
        for actor in (self.owner, self.other):
            EmailAddress.objects.create(user=actor, email=actor.email, primary=True, verified=True)
        self.organization = create_organization(user=self.owner, name="Routing org")
        self.foreign_org = create_organization(user=self.other, name="Other routing org")
        self.project = create_project(organization=self.organization, user=self.owner, name="Routing project",
                                      canonical_origin="https://route.example.com")
        self.provider = create_provider(actor=self.operator, key="routing-ai", name="AI",
                                        kind=AIProvider.Kind.OPENAI, enabled=True)
        self.account = create_provider_account(actor=self.operator, provider=self.provider, label="Platform",
                                               secret_reference="env:OPENAI_API_KEY")
        self.primary = self.model("primary")
        self.fallback = self.model("fallback")

    def model(self, identifier):
        return configure_model(actor=self.operator, provider=self.provider, identifier=identifier,
                               name=identifier, capabilities=[AIModelCapability.TEXT_GENERATION], enabled=True,
                               max_output_tokens=200, capability_source="https://example.com/models",
                               capabilities_verified_at=timezone.now(),
                               input_price_usd_per_million=Decimal("0.1250"),
                               output_price_usd_per_million=Decimal("2.5000"),
                               pricing_source="https://example.com/prices", pricing_verified_at=timezone.now(),
                               access_tier="standard")

    def save(self, *, actor=None, project=None, revision=0, model=None, account=None, fallback=None):
        current_id = AIRoutingPolicy.objects.filter(project=project).values_list("pk", flat=True).first() if revision else None
        return configure_ai_text_route(actor=actor or self.operator, project=project,
                                       model_id=(model or self.primary).pk,
                                       account_id=(account or self.account).pk,
                                       fallback_model_ids=fallback if fallback is not None else [self.fallback.pk],
                                       max_output_tokens=100, max_cost_usd="0.010000", timeout_seconds=9,
                                       revision=revision, policy_id=current_id)

    def test_system_fallback_selected_before_queue_only_and_never_replays_provider_failure(self):
        with self.assertRaises(ValidationError):
            queue_routed_ai_text(project=self.project, actor=self.owner, prompt="Text", max_output_tokens=50,
                                 max_cost_usd="0.010000", idempotency_key="no-default")
        policy = self.save()
        self.assertEqual((policy.project_id, policy.revision), (None, 1))
        AIModel.objects.filter(pk=self.primary.pk).update(enabled=False)
        with patch("jobs.services.dispatch_pending") as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                job = queue_routed_ai_text(project=self.project, actor=self.owner, prompt="Approved text",
                                           max_output_tokens=50, max_cost_usd="0.010000", idempotency_key="fallback")
            dispatch.assert_called_once_with(job.pk)
        self.assertEqual((job.input_snapshot["model_id"], job.config_snapshot["fallback_index"],
                          job.config_snapshot["routing_source"], job.config_snapshot["timeout_seconds"]),
                         (self.fallback.pk, 1, "system", 9))
        self.assertNotIn("OPENAI_API_KEY", json.dumps(job.config_snapshot))
        calls = []

        def request(**args):
            calls.append((args["model"].pk, args["timeout"]))
            raise ProviderRequestError("rate_limited", retryable=True)

        with patch.dict(os.environ, {"OPENAI_API_KEY": "dummy-key"}):
            self.assertTrue(execute_ai_text(job.pk, request=request))
        job.refresh_from_db()
        self.assertEqual(calls, [(self.fallback.pk, 9)])
        self.assertEqual((job.status, job.error_category, job.steps.count(), job.usage.actual_units),
                         (JobStatus.FAILED, "rate_limited", 1, 1))

    def test_default_exhaustion_and_free_fallback_never_reserve_or_dispatch(self):
        self.save()
        AIModel.objects.filter(pk=self.primary.pk).update(enabled=False)
        AIModel.objects.filter(pk=self.fallback.pk).update(access_tier="free",
                                                           privacy_policy_url="https://example.com/data-use")
        with patch("jobs.services.dispatch_pending") as dispatch, self.assertRaises(ValidationError):
            queue_routed_ai_text(project=self.project, actor=self.owner, prompt="Approved text",
                                 max_output_tokens=50, max_cost_usd="0.010000", idempotency_key="exhausted")
        dispatch.assert_not_called()
        self.assertFalse(JobRun.objects.exists())

    def test_project_override_uses_current_scope_and_rejects_stale_or_free_fallback(self):
        system = self.save()
        project = self.save(actor=self.owner, project=self.project, fallback=[])
        self.assertNotEqual(system.pk, project.pk)
        self.assertEqual(project.revision, 1)
        with self.assertRaises(ValidationError):
            self.save(actor=self.owner, project=self.project, revision=0)
        with self.assertRaises(PermissionDenied):
            self.save(actor=self.other, project=self.project, revision=1)
        foreign_account = AIProviderAccount(provider=self.provider, organization=self.foreign_org,
                                            label="Other key", secret_reference="")
        foreign_account.save()
        with self.assertRaises(ValidationError):
            self.save(actor=self.owner, project=self.project, revision=1, account=foreign_account)
        AIModel.objects.filter(pk=self.fallback.pk).update(access_tier="free",
                                                           privacy_policy_url="https://example.com/data-use")
        with self.assertRaises(ValidationError):
            self.save(actor=self.owner, project=self.project, revision=1)
        events = list(AuditEvent.objects.filter(event_type=AuditEventType.AI_ROUTING_UPDATED))
        self.assertEqual({(event.organization_id, event.project_id) for event in events},
                         {(None, None), (self.organization.pk, self.project.pk)})
        with patch("jobs.services.dispatch_pending"):
            with self.captureOnCommitCallbacks(execute=True):
                job = queue_routed_ai_text(project=self.project, actor=self.owner, prompt="Approved text",
                                           max_output_tokens=200, max_cost_usd="0.010000", idempotency_key="project")
        self.assertEqual((job.input_snapshot["model_id"], job.input_snapshot["max_output_tokens"],
                          job.config_snapshot["routing_source"]), (self.primary.pk, 100, "project"))
        from .routing import remove_ai_text_route, choose_ai_text_route
        with self.assertRaises(ValidationError):
            remove_ai_text_route(actor=self.owner, project=self.project, revision=0, policy_id=project.pk)
        self.assertTrue(remove_ai_text_route(actor=self.owner, project=self.project,
                                             revision=1, policy_id=project.pk))
        self.assertFalse(AIRoutingPolicy.objects.filter(project=self.project).exists())
        _model, _account, _data, source = choose_ai_text_route(
            project=self.project, prompt="Approved text", max_output_tokens=50, max_cost_usd="0.010000")
        self.assertEqual(source["routing_source"], "system")
        self.assertFalse(remove_ai_text_route(actor=self.owner, project=self.project,
                                              revision=0, policy_id=None))
        recreated = self.save(actor=self.owner, project=self.project, fallback=[])
        with self.assertRaises(ValidationError):
            configure_ai_text_route(actor=self.owner, project=self.project, model_id=self.primary.pk,
                                    account_id=self.account.pk, fallback_model_ids=[], max_output_tokens=100,
                                    max_cost_usd="0.010000", timeout_seconds=9,
                                    revision=recreated.revision, policy_id=project.pk)

    def test_owner_policy_api_requires_csrf_and_separates_project_from_staff(self):
        owner = Client(enforce_csrf_checks=True)
        owner.force_login(self.owner)
        owner.get("/_allauth/browser/v1/auth/session", secure=True)
        path = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/ai-routing/"
        data = {"model_id": self.primary.pk, "account_id": self.account.pk,
                "fallback_model_ids": [self.fallback.pk], "max_output_tokens": 100,
                "max_cost_usd": "0.010000", "timeout_seconds": 9, "revision": 0, "policy_id": None}
        self.assertEqual(owner.post(path, json.dumps(data), content_type="application/json", secure=True).status_code, 403)
        headers = {"HTTP_X_CSRFTOKEN": owner.cookies["csrftoken"].value, "HTTP_REFERER": "https://testserver/"}
        response = owner.post(path, json.dumps(data), content_type="application/json", secure=True, **headers)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(owner.get(path, secure=True).json()["effective"]["revision"], 1)
        self.assertEqual(owner.post(path, json.dumps(data), content_type="application/json", secure=True,
                                    **headers).status_code, 409)
        policy_id = response.json()["policy"]["id"]
        self.assertEqual(owner.delete(path, json.dumps({"revision": 0, "policy_id": policy_id}), content_type="application/json",
                                      secure=True, **headers).status_code, 409)
        removed = owner.delete(path, json.dumps({"revision": 1, "policy_id": policy_id}), content_type="application/json",
                               secure=True, **headers)
        self.assertEqual((removed.status_code, removed.json()["removed"], removed.json()["policy"]),
                         (200, True, None))
        self.assertEqual(owner.get("/api/platform/ai-routing/", secure=True).status_code, 403)
