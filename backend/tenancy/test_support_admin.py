from unittest.mock import patch
from urllib.parse import urlencode

from django.contrib import admin
from django.conf import settings
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.template.response import TemplateResponse
from django.urls import reverse

from config.test_foundations import TEST_STORAGES
from . import test_support_staff as fixtures
from .models import AuditEvent, AuditEventType, SupportRequest, SupportRequestUpdate
from .support_requests import create_support_request


@override_settings(DEBUG=True, STORAGES=TEST_STORAGES, STAFF_MFA_REQUIRED=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "support-admin"}})
class SupportAdminTests(TestCase):
    command = fixtures.SupportStaffTests.command
    submit = fixtures.SupportStaffTests.submit

    def setUp(self):
        cache.clear(); fixtures.SupportStaffTests.setUp(self)
        self.url = reverse("admin:tenancy_supportrequest_scoped")
        guarded = Client(enforce_csrf_checks=True); guarded.cookies = self.client.cookies; self.client = guarded
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.scope = dict(organization_id=self.organization.pk, project_id=self.project.pk,
                          request_id=self.request_id, reason="customer_request", action="inspect",
                          csrfmiddlewaretoken=self.client.cookies["csrftoken"].value)

    def post(self, data):
        return self.client.post(self.url, urlencode(data), content_type="application/x-www-form-urlencoded")

    def test_admin_exact_scoped_csrf_inert_prose_response_audits_and_no_direct_crud(self):
        self.assertEqual(self.post({key: value for key, value in self.scope.items() if key != "csrfmiddlewaretoken"}).status_code, 403)
        self.assertFalse(AuditEvent.objects.filter(event_type__startswith="support.").exists())
        unsafe = "<img src=x onerror=alert(1)>"
        identity = create_support_request(project=self.project, actor=self.owner,
            command=self.command(question=unsafe, request_key="inert-question-001"))["request"]["id"]
        result = self.post({**self.scope, "request_id": identity})
        self.assertEqual(result.status_code, 200, result.content)
        self.assertContains(result, "&lt;img src=x onerror=alert(1)&gt;")
        self.assertNotContains(result, unsafe)
        self.assertIn("private", result["Cache-Control"]); self.assertIn("no-store", result["Cache-Control"])
        form = result.context["response_form"]
        response = {**self.scope, **form.initial, "action": "respond", "status": "resolved", "response": unsafe}
        result = self.post(response)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(self.post(response).status_code, 200)
        self.assertEqual(SupportRequestUpdate.objects.count(), 1)
        event = AuditEvent.objects.get(event_type=AuditEventType.SUPPORT_REQUEST_UPDATED)
        self.assertNotIn(unsafe, str(event.details))
        resource = admin.site._registry[SupportRequest]
        self.assertFalse(resource.has_add_permission(self.request)); self.assertFalse(resource.has_change_permission(self.request)); self.assertFalse(resource.has_delete_permission(self.request))
        self.assertEqual(resource.get_queryset(self.request).count(), 0)
        self.assertEqual(self.client.get(reverse("admin:tenancy_supportrequest_changelist")).status_code, 302)
        detail = self.client.get(reverse("admin:tenancy_supportrequest_change", args=[identity]))
        self.assertNotIn(unsafe.encode(), detail.content)

    def test_wrong_scope_extra_fields_and_post_render_permission_or_original_loss_never_return_body(self):
        for changed in ({"project_id": self.other_project.pk}, {"request_id": self.request_id + 99999}, {"organization_id": self.other_org.pk}):
            self.assertEqual(self.post({**self.scope, **changed}).status_code, 403)
        self.assertEqual(self.post({**self.scope, "extra": "private"}).status_code, 409)
        self.assertEqual(self.client.post(self.url, self.scope).status_code, 409)
        original = TemplateResponse.render
        for mutate in (lambda: self.staff.user_permissions.clear(),
                       lambda: SupportRequest.objects.filter(pk=self.request_id).update(question="Changed original")):
            from django.db import transaction
            with transaction.atomic():
                def changed(response):
                    result = original(response)
                    if response.template_name == "admin/tenancy/support_request.html" and response.context_data.get("support"):
                        mutate()
                    return result
                with patch("django.template.response.TemplateResponse.render", changed): result = self.post(self.scope)
                self.assertIn(result.status_code, (403, 409))
                self.assertNotIn(b"Why did my job stop?", result.content)
                transaction.set_rollback(True)

    def test_actual_staff_access_and_update_read_budgets_are_independent(self):
        rates = {**settings.ACCOUNT_RATE_LIMITS, "support_staff_access": "1/h/user,99/h/ip", "support_staff_update": "1/h/user,99/h/ip"}
        with override_settings(ACCOUNT_RATE_LIMITS=rates):
            first = self.post(self.scope); self.assertEqual(first.status_code, 200)
            denied = self.post(self.scope); self.assertEqual(denied.status_code, 429)
            self.assertNotIn(b"Why did my job stop?", denied.content)
            command = {**self.scope, **first.context["response_form"].initial, "action": "respond", "status": "in_progress", "response": "Investigating."}
            self.assertEqual(self.post(command).status_code, 200)
            self.assertEqual(self.post(command).status_code, 429)
        self.assertEqual(SupportRequestUpdate.objects.count(), 1)
