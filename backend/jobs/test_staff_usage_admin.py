from unittest.mock import patch
from urllib.parse import urlencode

from django.contrib import admin
from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.conf import settings
from django.db import transaction
from django.template.response import TemplateResponse
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from config.test_foundations import TEST_STORAGES
from tenancy.models import AuditEvent, AuditEventType
from . import test_staff_usage_investigation as fixtures
from .models import UsageReservation
from .services import create_job
from .usage import reserve_usage, settle_usage


@override_settings(DEBUG=True, STORAGES=TEST_STORAGES, STAFF_MFA_REQUIRED=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "staff-usage-admin"}})
class StaffUsageAdminTests(TestCase):
    queue = fixtures.StaffUsageInvestigationTests.queue

    def setUp(self):
        cache.clear(); fixtures.StaffUsageInvestigationTests.setUp(self)
        self.url = reverse("admin:jobs_jobrun_scoped")
        guarded = Client(enforce_csrf_checks=True); guarded.cookies = self.client.cookies; self.client = guarded
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.scope = dict(organization_id=self.organization.pk, project_id=self.project.pk, job_id=self.job.pk,
            reason="investigation", action="inspect_usage", csrfmiddlewaretoken=self.client.cookies["csrftoken"].value)

    def post(self, **changes):
        return self.client.post(self.url, urlencode({**self.scope, **changes}, doseq=True), content_type="application/x-www-form-urlencoded")

    def test_usage_only_staff_explicit_semantic_units_missing_overshoot_audits_and_generic_denial(self):
        page = self.client.get(self.url)
        self.assertContains(page, 'value="inspect_usage"'); self.assertNotContains(page, 'value="inspect"')
        self.assertEqual(self.post(action="inspect").status_code, 403)
        result = self.post()
        self.assertEqual(result.status_code, 200, result.content)
        self.assertContains(result, "released"); self.assertContains(result, "not provider tokens")
        self.assertContains(result, "Actual units can exceed"); self.assertNotContains(result, "Complete bounded recorded steps")
        self.assertIn("no-store", result["Cache-Control"]); self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.STAFF_USAGE_INSPECTED).count(), 1)
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.STAFF_JOB_INSPECTED).exists())
        job = create_job(project=self.project, actor=self.owner, handler="diagnostic_probe",
                         input_snapshot={"sample": "safe diagnostic", "simulate_partial": False})
        self.assertContains(self.post(job_id=job.pk), "Missing history is not zero usage")
        reserve_usage(job=job, provider="synthetic", units=1)
        self.assertContains(self.post(job_id=job.pk), "Not settled")
        settle_usage(job=job, actual_units=2)
        self.assertContains(self.post(job_id=job.pk), "<dd>2</dd>")
        resource = admin.site._registry[UsageReservation]
        self.assertFalse(resource.has_view_permission(self.request)); self.assertFalse(resource.has_module_permission(self.request))
        self.assertEqual(resource.get_queryset(self.request).count(), 0)
        self.assertFalse(resource.has_add_permission(self.request)); self.assertFalse(resource.has_change_permission(self.request)); self.assertFalse(resource.has_delete_permission(self.request))
        self.assertEqual(self.client.get(reverse("admin:jobs_usagereservation_changelist")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:jobs_usagereservation_change", args=[self.job.usage.pk])).status_code, 403)

    def test_current_action_pair_csrf_scope_input_and_privacy_never_reuse_page_permission(self):
        body = {key: value for key, value in self.scope.items() if key != "csrfmiddlewaretoken"}
        self.assertEqual(self.client.post(self.url, urlencode(body), content_type="application/x-www-form-urlencoded").status_code, 403)
        for fields, code in (({"project_id": self.other_project.pk}, 403), ({"job_id": self.job.pk + 99999}, 403),
                             ({"job_id": [self.job.pk, self.job.pk]}, 409), ({"extra": "submitted-private-marker"}, 409)):
            result = self.post(**fields); self.assertEqual(result.status_code, code)
            self.assertNotIn(b"submitted-private-marker", result.content)
            self.assertNotIn(b"Recorded internal-unit history for job", result.content)
        self.staff.user_permissions.remove(Permission.objects.get(content_type__app_label="jobs", codename="view_usagereservation"))
        self.staff.user_permissions.add(Permission.objects.get(content_type__app_label="jobs", codename="view_jobstep"))
        page = self.client.get(self.url); self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'value="inspect_usage"')
        self.assertEqual(self.post().status_code, 403)
        self.assertEqual(self.post(action="inspect").status_code, 200)
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.STAFF_USAGE_INSPECTED).exists())

    def test_independent_actual_user_ip_budgets_and_other_action_remains_usable(self):
        self.staff.user_permissions.add(Permission.objects.get(content_type__app_label="jobs", codename="view_jobstep"))
        for limit in ("1/h/user,99/h/ip", "99/h/user,1/h/ip"):
            cache.clear()
            with override_settings(ACCOUNT_RATE_LIMITS={**settings.ACCOUNT_RATE_LIMITS, "staff_usage_access": limit,
                                                       "staff_job_access": "1/h/user,99/h/ip"}):
                self.assertEqual(self.post().status_code, 200)
                denied = self.post(); self.assertEqual(denied.status_code, 429)
                self.assertNotIn(b"Recorded internal-unit history for job", denied.content)
                self.assertEqual(self.post(action="inspect").status_code, 200)
                self.assertEqual(self.post(action="inspect").status_code, 429)

    def test_usage_post_render_source_session_and_permission_loss_never_delivers_unit_history(self):
        original = TemplateResponse.render
        for mutate in (lambda: UsageReservation.objects.filter(job=self.job).update(reserved_units=1),
                       lambda: Session.objects.filter(session_key=self.client.session.session_key).delete(),
                       lambda: self.staff.user_permissions.clear()):
            with transaction.atomic():
                def changed(response):
                    result = original(response)
                    if response.template_name == "admin/jobs/job_investigation.html" and response.context_data.get("usage"):
                        mutate()
                    return result
                with patch("django.template.response.TemplateResponse.render", changed): response = self.post()
                self.assertIn(response.status_code, (403, 409))
                self.assertNotIn(b"Recorded internal-unit history for job", response.content)
                self.assertIn("no-store", response["Cache-Control"])
                transaction.set_rollback(True)
