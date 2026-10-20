from unittest.mock import patch
from urllib.parse import urlencode

from django.contrib import admin
from django.conf import settings
from django.core.cache import cache
from django.contrib.sessions.models import Session
from django.db import transaction
from django.template.response import TemplateResponse
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from config.test_foundations import TEST_STORAGES
from tenancy.models import AuditEvent, AuditEventType, Organization
from . import test_staff_job_investigation as fixtures
from .models import JobRun, JobStep


@override_settings(DEBUG=True, STORAGES=TEST_STORAGES, STAFF_MFA_REQUIRED=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "staff-job-admin"}})
class StaffJobAdminTests(TestCase):
    queue = fixtures.StaffJobInvestigationTests.queue

    def setUp(self):
        cache.clear(); fixtures.StaffJobInvestigationTests.setUp(self)
        self.url = reverse("admin:jobs_jobrun_scoped")
        guarded = Client(enforce_csrf_checks=True); guarded.cookies = self.client.cookies; self.client = guarded
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.scope = dict(organization_id=self.organization.pk, project_id=self.project.pk, job_id=self.job.pk,
            reason="investigation", action="inspect", csrfmiddlewaretoken=self.client.cookies["csrftoken"].value)

    def post(self, data=None, **kwargs):
        return self.client.post(self.url, urlencode(self.scope if data is None else data, doseq=True),
                                content_type="application/x-www-form-urlencoded", **kwargs)

    def test_exact_scoped_csrf_minimized_native_table_private_audit_no_generic_discovery_or_crud(self):
        self.assertEqual(self.post({key: value for key, value in self.scope.items() if key != "csrfmiddlewaretoken"}).status_code, 403)
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.STAFF_JOB_INSPECTED).exists())
        poison = "<img src=x onerror=alert(1)>"
        JobRun.objects.filter(pk=self.job.pk).update(output={"body": poison}, input_snapshot={"private": poison}, error_category=poison)
        JobStep.objects.filter(job=self.job).update(name=poison, output={"body": poison}, error_category=poison)
        result = self.post()
        self.assertEqual(result.status_code, 200, result.content)
        self.assertContains(result, f"Recorded job {self.job.pk}")
        self.assertContains(result, "partially_succeeded"); self.assertContains(result, "failed")
        self.assertContains(result, "<caption>"); self.assertContains(result, 'scope="col"'); self.assertContains(result, 'scope="row"')
        self.assertContains(result, "it performs no retry")
        for private in (poison, self.owner.email, self.project.canonical_origin, "Synthetic observation", "handler_failed"):
            self.assertNotContains(result, private)
        self.assertIn("private", result["Cache-Control"]); self.assertIn("no-store", result["Cache-Control"])
        self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.STAFF_JOB_INSPECTED).count(), 1)
        self.assertEqual(self.client.get(reverse("admin:jobs_jobrun_changelist")).url, self.url)
        for model in (JobRun, JobStep):
            resource = admin.site._registry[model]
            self.assertEqual(resource.get_queryset(self.request).count(), 0)
            self.assertFalse(resource.has_add_permission(self.request))
            self.assertFalse(resource.has_change_permission(self.request)); self.assertFalse(resource.has_delete_permission(self.request))
        self.assertFalse(admin.site._registry[JobStep].has_view_permission(self.request))
        for route, identity in (("admin:jobs_jobrun_change", self.job.pk), ("admin:jobs_jobstep_change", self.job.steps.first().pk)):
            response = self.client.get(reverse(route, args=[identity]))
            self.assertIn(response.status_code, (302, 403)); self.assertNotIn(poison.encode(), response.content)
        self.assertEqual(self.client.get(reverse("admin:jobs_jobstep_changelist")).status_code, 403)

    def test_wrong_scope_unsafe_extra_duplicate_method_content_and_body_are_generic_private_no_audit(self):
        for changed in ({"organization_id": self.other_org.pk}, {"project_id": self.other_project.pk}, {"job_id": self.job.pk + 99999}):
            self.assertEqual(self.post({**self.scope, **changed}).status_code, 403)
        for changed in ({"job_id": 2**53}, {"reason": "private free text"}, {"action": "retry"},
                        {"private": "submitted-private-payload-marker"}, {"job_id": [self.job.pk, self.job.pk]}, {"reason": "x" * 4096}):
            response = self.post({**self.scope, **changed})
            self.assertEqual(response.status_code, 409)
            self.assertNotIn(b"submitted-private-payload-marker", response.content)
            self.assertNotIn(b"private free text", response.content)
            self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(self.client.post(self.url, self.scope).status_code, 409)
        self.assertEqual(self.client.get(self.url + "?job_id=1").status_code, 409)
        self.assertEqual(self.client.put(self.url, "", HTTP_X_CSRFTOKEN=self.scope["csrfmiddlewaretoken"]).status_code, 409)
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.STAFF_JOB_INSPECTED).exists())

    def test_final_render_source_scope_permission_or_persisted_session_loss_never_delivers_job_table(self):
        original = TemplateResponse.render
        for mutate in (lambda: self.staff.user_permissions.clear(),
                       lambda: Session.objects.filter(session_key=self.client.session.session_key).delete(),
                       lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True),
                       lambda: JobStep.objects.filter(job=self.job, sequence=1).update(progress_percent=51)):
            with transaction.atomic():
                def changed(response):
                    result = original(response)
                    if response.template_name == "admin/jobs/job_investigation.html" and response.context_data.get("investigation"):
                        mutate()
                    return result
                with patch("django.template.response.TemplateResponse.render", changed): response = self.post()
                self.assertIn(response.status_code, (403, 409))
                self.assertNotIn(f"Recorded job {self.job.pk}".encode(), response.content)
                self.assertNotIn(b"partially_succeeded", response.content)
                self.assertIn("no-store", response["Cache-Control"])
                transaction.set_rollback(True)

    def test_real_independent_user_and_ip_budgets_and_current_support_permission_denial(self):
        for limit in ("1/h/user,99/h/ip", "99/h/user,1/h/ip"):
            cache.clear()
            with override_settings(ACCOUNT_RATE_LIMITS={**settings.ACCOUNT_RATE_LIMITS, "staff_job_access": limit,
                                                       "support_staff_access": "1/h/user,1/h/ip"}):
                self.assertEqual(self.post().status_code, 200)
                response = self.post()
                self.assertEqual(response.status_code, 429)
                self.assertNotIn(b"partially_succeeded", response.content)
        self.staff.user_permissions.clear()
        response = self.post(); self.assertEqual(response.status_code, 403)
        self.assertNotIn(b"partially_succeeded", response.content)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
