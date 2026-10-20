from decimal import Decimal
from unittest.mock import patch
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import admin
from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.db import transaction
from django.template.response import TemplateResponse
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from config.test_foundations import TEST_STORAGES
from providers.services import create_provider_account
from tenancy.models import AuditEvent, AuditEventType, Organization
from . import test_staff_ai_usage_investigation as fixtures
from .models import AIUsageRecord, JobRun, JobStep


@override_settings(DEBUG=True, STORAGES=TEST_STORAGES, STAFF_MFA_REQUIRED=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "staff-ai-usage-admin"}})
class StaffAIUsageAdminTests(TestCase):
    queue = fixtures.StaffAIUsageInvestigationTests.queue
    execute = fixtures.StaffAIUsageInvestigationTests.execute

    def setUp(self):
        cache.clear(); fixtures.StaffAIUsageInvestigationTests.setUp(self)
        self.url = reverse("admin:jobs_jobrun_scoped")
        guarded = Client(enforce_csrf_checks=True); guarded.cookies = self.client.cookies; self.client = guarded
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.scope = dict(organization_id=self.organization.pk, project_id=self.project.pk, job_id=self.job.pk,
            reason="investigation", action="inspect_ai_usage", csrfmiddlewaretoken=self.client.cookies["csrftoken"].value)

    def post(self, **changes):
        return self.client.post(self.url, urlencode({**self.scope, **changes}, doseq=True), content_type="application/x-www-form-urlencoded")

    def test_ai_only_explicit_private_original_nullable_semantics_audit_no_generic_discovery(self):
        page = self.client.get(self.url)
        self.assertContains(page, 'value="inspect_ai_usage"')
        for action in ("inspect", "inspect_usage"):
            self.assertNotContains(page, f'value="{action}"'); self.assertEqual(self.post(action=action).status_code, 403)
        poison = "<img src=x onerror=alert(1)>"
        JobRun.objects.filter(pk=self.job.pk).update(output={"body": poison}, input_snapshot={"private": poison}, error_category=poison)
        JobStep.objects.filter(job=self.job).update(name=poison, output={"body": poison}, error_category=poison)
        AIUsageRecord.objects.filter(job=self.job).update(error_category=poison, provider_request_id=poison, provider_response_id=poison)
        response = self.post(); self.assertEqual(response.status_code, 200, response.content)
        for text in ("Original AI observations for job", "completed", "0.000014", "Unknown values are not zero", "not recomputed", "customer charges", "Attempt recorded"):
            self.assertContains(response, text)
        for text in (poison, self.owner.email, self.project.canonical_origin, "Complete bounded recorded steps", "Recorded internal-unit history for job"):
            self.assertNotContains(response, text)
        self.assertIn("no-store", response["Cache-Control"]); self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.STAFF_AI_USAGE_INSPECTED).count(), 1)
        self.assertFalse(AuditEvent.objects.filter(event_type__in=[AuditEventType.STAFF_JOB_INSPECTED, AuditEventType.STAFF_USAGE_INSPECTED]).exists())
        # Explicit synthetic zero/null retained observations, not a provider-reported invoice fixture.
        AIUsageRecord.objects.filter(job=self.job).update(input_tokens=0, output_tokens=None, duration_ms=0,
            reported_cost_usd=Decimal("0.000000"), estimated_cost_usd=None)
        response = self.post(); self.assertContains(response, "<dd>0</dd>"); self.assertContains(response, "<dd>0.000000</dd>")
        self.assertContains(response, "<dd>Unknown</dd>")
        missing = self.queue(idempotency_key="no-record")
        self.assertContains(self.post(job_id=missing.pk), "Missing history is not zero tokens")
        resource = admin.site._registry[AIUsageRecord]
        self.assertFalse(resource.has_view_permission(self.request)); self.assertFalse(resource.has_module_permission(self.request))
        self.assertEqual(resource.get_queryset(self.request).count(), 0)
        self.assertFalse(resource.has_add_permission(self.request)); self.assertFalse(resource.has_change_permission(self.request)); self.assertFalse(resource.has_delete_permission(self.request))
        self.assertEqual(self.client.get(reverse("admin:jobs_aiusagerecord_changelist")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:jobs_aiusagerecord_change", args=[self.job.ai_usage_record.pk])).status_code, 403)

    def test_exact_action_pair_csrf_strict_input_scope_and_other_pairs_never_grant_ai_access(self):
        self.assertEqual(self.client.post(self.url, urlencode({key: value for key, value in self.scope.items() if key != "csrfmiddlewaretoken"}),
            content_type="application/x-www-form-urlencoded").status_code, 403)
        for fields, code in (({"organization_id": self.other_org.pk}, 403), ({"project_id": self.other_project.pk}, 403),
                ({"job_id": self.job.pk + 99999}, 403), ({"job_id": [self.job.pk, self.job.pk]}, 409),
                ({"extra": "submitted-private-marker"}, 409), ({"action": "retry"}, 409), ({"reason": "x" * 4096}, 409)):
            response = self.post(**fields); self.assertEqual(response.status_code, code)
            self.assertNotIn(b"submitted-private-marker", response.content); self.assertNotIn(b"Original AI observations for job", response.content)
        self.assertEqual(self.client.post(self.url, self.scope).status_code, 409)
        self.assertEqual(self.client.get(self.url + "?job_id=1").status_code, 409)
        self.assertEqual(self.client.put(self.url, "", HTTP_X_CSRFTOKEN=self.scope["csrfmiddlewaretoken"]).status_code, 409)
        self.staff.user_permissions.remove(Permission.objects.get(content_type__app_label="jobs", codename="view_aiusagerecord"))
        for permission, action in (("view_jobstep", "inspect"), ("view_usagereservation", "inspect_usage")):
            self.staff.user_permissions.add(Permission.objects.get(content_type__app_label="jobs", codename=permission))
            page = self.client.get(self.url); self.assertEqual(page.status_code, 200)
            self.assertNotContains(page, 'value="inspect_ai_usage"'); self.assertEqual(self.post().status_code, 403)
            self.assertEqual(self.post(action=action).status_code, 200)
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.STAFF_AI_USAGE_INSPECTED).exists())

    def test_actual_independent_ai_user_ip_budgets_other_actions_remain_usable(self):
        self.staff.user_permissions.add(*Permission.objects.filter(content_type__app_label="jobs",
            codename__in=["view_jobstep", "view_usagereservation"]))
        for limit in ("1/h/user,99/h/ip", "99/h/user,1/h/ip"):
            cache.clear()
            with override_settings(ACCOUNT_RATE_LIMITS={**settings.ACCOUNT_RATE_LIMITS, "staff_ai_usage_access": limit,
                "staff_job_access": "1/h/user,99/h/ip", "staff_usage_access": "1/h/user,99/h/ip"}):
                self.assertEqual(self.post().status_code, 200)
                response = self.post(); self.assertEqual(response.status_code, 429)
                self.assertNotIn(b"Original AI observations for job", response.content)
                for action in ("inspect", "inspect_usage"):
                    self.assertEqual(self.post(action=action).status_code, 200); self.assertEqual(self.post(action=action).status_code, 429)

    def test_post_render_display_hidden_binding_scope_permission_session_loss_never_delivers_observations(self):
        original = TemplateResponse.render
        alternate = create_provider_account(actor=self.operator, provider=self.provider, label="Alternate fixture account", secret_reference="env:OPENAI_API_KEY")
        for mutate in (lambda: AIUsageRecord.objects.filter(job=self.job).update(input_tokens=13),
                lambda: AIUsageRecord.objects.filter(job=self.job).update(account_id=alternate.pk),
                lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True),
                lambda: Session.objects.filter(session_key=self.client.session.session_key).delete(),
                lambda: self.staff.user_permissions.clear()):
            with transaction.atomic():
                def changed(response):
                    result = original(response)
                    if response.template_name == "admin/jobs/job_investigation.html" and response.context_data.get("ai_usage"):
                        mutate()
                    return result
                with patch("django.template.response.TemplateResponse.render", changed): response = self.post()
                self.assertIn(response.status_code, (403, 409)); self.assertIn("no-store", response["Cache-Control"])
                self.assertNotIn(b"Original AI observations for job", response.content); self.assertNotIn(b"0.000014", response.content)
                transaction.set_rollback(True)
