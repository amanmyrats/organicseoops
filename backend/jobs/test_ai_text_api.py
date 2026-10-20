import json
import os
from decimal import Decimal
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from providers.models import AIModel, AIModelCapability, AIProvider
from providers.adapters import ProviderResponse
from providers.services import configure_model, create_provider, create_provider_account
from tenancy.models import MembershipRole, OrganizationMembership
from tenancy.services import create_organization, create_project

from .ai_text import execute_ai_text
from .models import AIUsageRecord, JobRun, JobStatus


@override_settings(STAFF_MFA_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class ProjectAITextAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = get_user_model().objects.create_user("ai-api-owner@example.com", "test-password")
        self.other = get_user_model().objects.create_user("ai-api-other@example.com", "test-password")
        self.viewer = get_user_model().objects.create_user("ai-api-viewer@example.com", "test-password")
        for user in (self.owner, self.other):
            EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
        self.organization = create_organization(user=self.owner, name="AI API organization")
        self.project = create_project(organization=self.organization, user=self.owner, name="AI project",
                                      canonical_origin="https://ai-api.example.com")
        self.foreign = create_organization(user=self.other, name="Foreign AI organization")
        self.foreign_project = create_project(organization=self.foreign, user=self.other, name="Other AI project",
                                              canonical_origin="https://other-ai-api.example.com")
        OrganizationMembership.objects.create(user=self.viewer, organization=self.organization, role=MembershipRole.VIEWER)
        operator = get_user_model().objects.create_superuser("ai-api-staff@example.com", "test-password")
        self.provider = create_provider(actor=operator, key="api-model", name="AI provider",
                                        kind=AIProvider.Kind.OPENAI, enabled=True)
        self.account = create_provider_account(actor=operator, provider=self.provider, label="Platform",
                                               secret_reference="env:OPENAI_API_KEY")
        self.model = configure_model(actor=operator, provider=self.provider, identifier="selected-api-model",
                                     name="Selectable model", capabilities=[AIModelCapability.TEXT_GENERATION],
                                     capability_source="https://example.com/models", capabilities_verified_at=timezone.now(),
                                     enabled=True, max_output_tokens=100,
                                     input_price_usd_per_million=Decimal("0.1250"),
                                     output_price_usd_per_million=Decimal("2.5000"),
                                     pricing_source="https://example.com/prices", pricing_verified_at=timezone.now(),
                                     access_tier="standard")
        self.path = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/ai-text/"
        self.browser = self.login(self.owner)
        self.data = {"model_id": self.model.pk, "account_id": self.account.pk,
                     "prompt": "Summarize the approved notes.", "max_output_tokens": 50,
                     "max_cost_usd": "0.010000", "allow_free": False,
                     "idempotency_key": "ai-request-1"}

    def login(self, user):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(user)
        browser.get("/_allauth/browser/v1/auth/session", secure=True)
        return browser

    def post(self, browser, path, data, *, csrf=True):
        headers = ({"HTTP_X_CSRFTOKEN": browser.cookies["csrftoken"].value,
                    "HTTP_REFERER": "https://testserver/"} if csrf else {})
        return browser.post(path, data=json.dumps(data), content_type="application/json", secure=True, **headers)

    def test_scoped_explicit_selection_csrf_idempotency_and_cancel(self):
        self.assertEqual(self.post(self.browser, self.path, self.data, csrf=False).status_code, 403)
        listing = self.browser.get(self.path, secure=True)
        self.assertEqual((listing.status_code, listing.json()["cost_status"]), (200, "unknown"))
        self.assertEqual(listing.json()["models"][0]["id"], self.model.pk)
        self.assertNotIn("secret_reference", listing.content.decode())
        self.assertEqual(self.login(self.viewer).get(self.path, secure=True).status_code, 200)
        self.assertEqual(self.post(self.login(self.viewer), self.path, self.data).status_code, 403)
        foreign_path = f"/api/organizations/{self.foreign.pk}/projects/{self.foreign_project.pk}/ai-text/"
        self.assertEqual(self.browser.get(foreign_path, secure=True).status_code, 404)
        with patch("jobs.services.dispatch_pending") as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                queued = self.post(self.browser, self.path, self.data)
            dispatch.assert_called_once()
        self.assertEqual(queued.status_code, 202, queued.content)
        self.assertEqual(queued.json()["job"]["status"], JobStatus.QUEUED)
        self.assertEqual(queued["Cache-Control"], "private, no-store")
        self.assertNotIn(self.data["prompt"], queued.content.decode())
        job = JobRun.objects.get(pk=queued.json()["job"]["id"])
        self.assertEqual((job.organization_id, job.project_id, job.usage.reserved_units),
                         (self.organization.pk, self.project.pk, 1))
        self.assertEqual(self.post(self.browser, self.path, self.data).json()["job"]["id"], job.pk)
        self.assertEqual(JobRun.objects.count(), 1)
        self.assertEqual(self.post(self.browser, self.path, {**self.data, "prompt": "Different"}).status_code, 400)
        status_path = f"{self.path}{job.pk}/"
        self.assertEqual(self.browser.get(status_path, secure=True).json()["job"]["status"], JobStatus.QUEUED)
        self.assertEqual(self.browser.get(f"{foreign_path}{job.pk}/", secure=True).status_code, 404)
        self.assertEqual(self.post(self.browser, status_path, {}, csrf=False).status_code, 403)
        cancelled = self.post(self.browser, status_path, {})
        self.assertEqual((cancelled.status_code, cancelled.json()["job"]["status"]), (200, JobStatus.CANCELLED))

    def test_unpriced_or_free_without_explicit_consent_does_not_queue(self):
        AIModel.objects.filter(pk=self.model.pk).update(input_price_usd_per_million=None,
                                                       output_price_usd_per_million=None)
        self.assertEqual(self.post(self.browser, self.path, self.data).status_code, 400)
        self.assertFalse(JobRun.objects.exists())
        AIModel.objects.filter(pk=self.model.pk).update(input_price_usd_per_million=Decimal("0.1250"),
                                                       output_price_usd_per_million=Decimal("2.5000"),
                                                       access_tier="free",
                                                       privacy_policy_url="https://example.com/data-use")
        self.assertEqual(self.post(self.browser, self.path, self.data).status_code, 400)
        self.assertFalse(JobRun.objects.exists())
        with patch("jobs.services.dispatch_pending"):
            with self.captureOnCommitCallbacks(execute=True):
                approved = self.post(self.browser, self.path, {**self.data, "allow_free": True})
        self.assertEqual(approved.status_code, 202, approved.content)
        self.assertGreater(Decimal(approved.json()["job"]["estimated_max_cost_usd"]), 0)

    def test_provider_usage_projection_is_scoped_and_never_claims_reported_cost(self):
        history_path = f"{self.path}history/"
        self.assertEqual(self.browser.get(history_path, secure=True).json(), {"jobs": [], "has_more": False})
        with patch("jobs.services.dispatch_pending"):
            with self.captureOnCommitCallbacks(execute=True):
                queued = self.post(self.browser, self.path, self.data)
        job_id = queued.json()["job"]["id"]
        detail = f"{self.path}{job_id}/"
        self.assertIsNone(self.browser.get(detail, secure=True).json()["job"]["usage"])
        with patch.dict(os.environ, {"OPENAI_API_KEY": "dummy-secret"}):
            self.assertTrue(execute_ai_text(job_id, request=lambda **_: ProviderResponse(
                "Approved result", None, (), "req_safe", "resp_safe", 12, 5)))
        response = self.browser.get(detail, secure=True)
        self.assertEqual(response.status_code, 200)
        usage = response.json()["job"]["usage"]
        self.assertEqual((usage["provider_id"], usage["model_id"], usage["input_tokens"],
                          usage["output_tokens"], usage["estimated_cost_usd"], usage["reported_cost_usd"]),
                         (self.provider.pk, self.model.pk, 12, 5, "0.000014", None))
        self.assertNotIn("dummy-secret", response.content.decode())
        self.assertEqual(self.login(self.other).get(detail, secure=True).status_code, 404)
        history = self.browser.get(history_path, secure=True)
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()["jobs"][0]["estimated_cost_usd"], "0.000014")
        self.assertIsNone(history.json()["jobs"][0]["reported_cost_usd"])
        self.assertNotIn(self.data["prompt"], history.content.decode())
        self.assertNotIn("Approved result", history.content.decode())
        self.assertEqual(self.login(self.other).get(history_path, secure=True).status_code, 404)
        record = AIUsageRecord.objects.get(job_id=job_id)
        record.organization = self.foreign
        with self.assertRaises(ValidationError):
            record.full_clean()
