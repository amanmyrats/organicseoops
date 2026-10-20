import json
from unittest.mock import patch
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import admin
from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from django.contrib.auth import HASH_SESSION_KEY
from django.core.cache import cache
from django.db import transaction
from django.template.response import TemplateResponse
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import notice_api, test_staff_notice_investigation as fixtures
from .models import AuditEvent, AuditEventType, Organization, OrganizationNotice


@override_settings(STAFF_MFA_REQUIRED=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "staff-notice-consumers"}})
class StaffNoticeConsumerTests(TestCase):
    def setUp(self):
        cache.clear(); fixtures.StaffNoticeInvestigationTests.setUp(self)
        self.url = reverse("admin:tenancy_organizationnotice_scoped")
        self.api_url = reverse("platform-inspect-notice")
        guarded = Client(enforce_csrf_checks=True); guarded.cookies = self.client.cookies; self.client = guarded
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.scope = dict(organization_id=self.organization.pk, notice_id=self.notice_id, reason="investigation")
        self.token = self.client.cookies["csrftoken"].value

    def admin_post(self, **changes):
        return self.client.post(self.url, urlencode({**self.scope, "action": "inspect", "csrfmiddlewaretoken": self.token, **changes}, doseq=True),
            content_type="application/x-www-form-urlencoded")

    def api_post(self, **changes):
        return self.client.post(self.api_url, json.dumps({**self.scope, **changes}), content_type="application/json", HTTP_X_CSRFTOKEN=self.token)

    def test_private_exact_admin_api_audit_legacy_retirement_and_no_generic_crud(self):
        OrganizationNotice.objects.filter(pk=self.notice_id).update(error_category="private-provider-marker")
        page = self.admin_post(); self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, f"Recorded notice {self.notice_id}"); self.assertContains(page, "not inbox delivery")
        self.assertContains(page, "retry count is history"); self.assertNotContains(page, self.owner.email); self.assertNotContains(page, "private-provider-marker")
        result = self.api_post(); self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual((len(result.json()["notice"]), result.json()["notice"]["state"]), (7, "queued"))
        for response in (page, result):
            self.assertIn("no-store", response["Cache-Control"]); self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.STAFF_NOTICE_INSPECTED).count(), 2)
        old = self.client.get(reverse("platform-unknown-notices"))
        self.assertEqual(old.status_code, 410); self.assertNotIn("notices", old.json())
        self.assertNotIn(b"private-provider-marker", old.content)
        resource = admin.site._registry[OrganizationNotice]
        self.assertEqual(resource.get_queryset(self.request).count(), 0)
        self.assertFalse(resource.has_add_permission(self.request)); self.assertFalse(resource.has_change_permission(self.request)); self.assertFalse(resource.has_delete_permission(self.request))
        self.assertEqual(self.client.get(reverse("admin:tenancy_organizationnotice_changelist")).url, self.url)
        response = self.client.get(reverse("admin:tenancy_organizationnotice_change", args=[self.notice_id]))
        self.assertIn(response.status_code, (302, 403)); self.assertNotIn(self.owner.email.encode(), response.content)

    def test_both_consumers_csrf_strict_body_query_methods_safe_scope_and_permission_pairs(self):
        self.assertEqual(self.client.post(self.api_url, json.dumps(self.scope), content_type="application/json").status_code, 403)
        self.assertEqual(self.client.post(self.url, urlencode({**self.scope, "action": "inspect"}), content_type="application/x-www-form-urlencoded").status_code, 403)
        for fields, code in (({"organization_id": self.other_org.pk}, 403), ({"notice_id": self.notice_id + 99999}, 403),
                ({"extra": "submitted-private-marker"}, 409), ({"reason": "private free text"}, 409)):
            for response in (self.admin_post(**fields), self.api_post(**fields)):
                self.assertEqual(response.status_code, code); self.assertNotIn(b"submitted-private-marker", response.content)
                self.assertNotIn(b"Recorded notice", response.content)
        self.assertEqual(self.admin_post(notice_id=[self.notice_id, self.notice_id]).status_code, 409)
        self.assertEqual(self.client.post(self.api_url, '{"organization_id":1,"organization_id":1}', content_type="application/json", HTTP_X_CSRFTOKEN=self.token).status_code, 409)
        self.assertEqual(self.api_post(notice_id=True).status_code, 409)
        self.assertEqual(self.api_post(notice_id=2**53).status_code, 409)
        self.assertEqual(self.client.post(self.api_url, self.scope, HTTP_X_CSRFTOKEN=self.token).status_code, 409)
        self.assertEqual(self.client.get(self.api_url).status_code, 405)
        self.assertEqual(self.client.get(self.url + "?notice_id=1").status_code, 409)
        self.assertEqual(self.client.post(self.api_url + "?notice_id=1", json.dumps(self.scope), content_type="application/json", HTTP_X_CSRFTOKEN=self.token).status_code, 409)
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.STAFF_NOTICE_INSPECTED).exists())
        for codename in ("view_organization", "view_organizationnotice"):
            permission = Permission.objects.get(content_type__app_label="tenancy", codename=codename)
            self.staff.user_permissions.remove(permission)
            self.assertEqual(self.api_post().status_code, 403); self.assertEqual(self.admin_post().status_code, 403)
            self.staff.user_permissions.add(permission)

    def test_actual_user_ip_budget_shared_between_admin_api_and_separate_from_other_investigations(self):
        for limit in ("1/h/user,99/h/ip", "99/h/user,1/h/ip"):
            cache.clear()
            with override_settings(ACCOUNT_RATE_LIMITS={**settings.ACCOUNT_RATE_LIMITS, "staff_notice_access": limit}):
                self.assertEqual(self.api_post().status_code, 200)
                self.assertEqual(self.admin_post().status_code, 429); self.assertEqual(self.api_post().status_code, 429)
            cache.clear()
            with override_settings(ACCOUNT_RATE_LIMITS={**settings.ACCOUNT_RATE_LIMITS, "staff_notice_access": limit}):
                self.assertEqual(self.admin_post().status_code, 200); self.assertEqual(self.api_post().status_code, 429)

    def test_post_render_or_serialization_hidden_source_scope_session_loss_never_returns_notice(self):
        original_render, original_response = TemplateResponse.render, notice_api._response
        for mutate in (lambda: OrganizationNotice.objects.filter(pk=self.notice_id).update(recipient_id=self.staff.pk),
                lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True),
                lambda: Session.objects.filter(session_key=self.client.session.session_key).delete(),
                lambda: self.staff.user_permissions.clear()):
            for consumer in ("admin", "api"):
                with transaction.atomic():
                    def changed_render(response):
                        result = original_render(response)
                        if response.template_name == "admin/tenancy/notice_investigation.html" and response.context_data.get("inspection"): mutate()
                        return result
                    def changed_response(payload, *args, **kwargs):
                        result = original_response(payload, *args, **kwargs)
                        if "notice" in payload: mutate()
                        return result
                    with patch("django.template.response.TemplateResponse.render", changed_render), patch("tenancy.notice_api._response", changed_response):
                        response = self.admin_post() if consumer == "admin" else self.api_post()
                    self.assertIn(response.status_code, (403, 409)); self.assertIn("no-store", response["Cache-Control"])
                    self.assertNotIn(b"Recorded notice", response.content); self.assertNotIn(b'"notice":', response.content)
                    transaction.set_rollback(True)

    def test_separate_reissue_requires_current_persisted_assurance_and_final_permission_before_commit_or_dispatch(self):
        permission = Permission.objects.get(content_type__app_label="tenancy", codename="change_organizationnotice")
        OrganizationNotice.objects.filter(pk=self.notice_id).update(state="unknown", attempted_at=timezone.now())
        url = reverse("platform-unknown-notice-retry", args=[self.notice_id])
        payload = json.dumps({"reason": "Fixture possible duplicate review", "acknowledge_possible_duplicate": True})
        def request():
            return self.client.post(url, payload, content_type="application/json", HTTP_X_CSRFTOKEN=self.token)
        with patch("tenancy.notice_api.send_organization_notice_task.apply_async") as dispatch:
            self.assertEqual(request().status_code, 403)  # Inspection pair is not reissue permission.
            self.staff.user_permissions.add(permission)
            create = AuditEvent.objects.create
            for mutate in (lambda: self.staff.user_permissions.remove(permission),
                    lambda: Session.objects.filter(session_key=self.client.session.session_key).delete()):
                def changed(**kwargs):
                    result = create(**kwargs); mutate(); return result
                with patch("tenancy.notices.AuditEvent.objects.create", side_effect=changed): self.assertEqual(request().status_code, 403)
                row = OrganizationNotice.objects.get(pk=self.notice_id)
                self.assertEqual((row.state, row.manual_retries), ("unknown", 0))
                self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.NOTICE_RETRY_REQUESTED).exists())
            session = self.client.session; session[HASH_SESSION_KEY] = "invalidated-fixture-hash"; session.save()
            self.assertIn(request().status_code, (401, 403))
            dispatch.assert_not_called()
