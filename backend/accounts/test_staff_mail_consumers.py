import json
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlencode

from allauth.account.models import EmailAddress
from allauth.core.internal import ratelimit
from django.conf import settings
from django.contrib import admin
from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.db import transaction
from django.template.response import TemplateResponse
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from tenancy.models import AuditEvent, AuditEventType
from . import mail_api, test_staff_mail_investigation as fixtures
from .models import AccountEmailDelivery, User


@override_settings(STAFF_MFA_REQUIRED=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "staff-mail-consumers"}})
class StaffMailConsumerTests(TestCase):
    send = fixtures.StaffMailInvestigationTests.send

    def setUp(self):
        cache.clear(); fixtures.StaffMailInvestigationTests.setUp(self)
        self.url = reverse("admin:accounts_accountemaildelivery_scoped")
        self.api_url = reverse("platform-inspect-account-mail")
        guarded = Client(enforce_csrf_checks=True); guarded.cookies = self.client.cookies; self.client = guarded
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.scope = dict(user_id=self.target.pk, email_address_id=self.address.pk, delivery_id=self.record.pk, reason="investigation")
        self.token = self.client.cookies["csrftoken"].value

    def admin_post(self, **changes):
        return self.client.post(self.url, urlencode({**self.scope, "action": "inspect", "csrfmiddlewaretoken": self.token, **changes}, doseq=True),
            content_type="application/x-www-form-urlencoded")

    def api_post(self, **changes):
        return self.client.post(self.api_url, json.dumps({**self.scope, **changes}), content_type="application/json", HTTP_X_CSRFTOKEN=self.token)

    def test_exact_private_consumers_audit_legacy_retirement_no_generic_crud_or_purpose(self):
        AccountEmailDelivery.objects.filter(pk=self.record.pk).update(purpose="private-purpose-marker")
        page = self.admin_post(); self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, f"Recorded delivery {self.record.pk}"); self.assertContains(page, "not inbox delivery")
        self.assertContains(page, "not proof of the original recipient"); self.assertNotContains(page, self.target.email); self.assertNotContains(page, "private-purpose-marker")
        result = self.api_post(); self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual((len(result.json()["delivery"]), result.json()["delivery"]["state"]), (4, "transport_returned"))
        for response in (page, result):
            self.assertIn("no-store", response["Cache-Control"]); self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.STAFF_ACCOUNT_MAIL_INSPECTED).count(), 2)
        old = self.client.get(reverse("platform-email-deliveries"))
        self.assertEqual(old.status_code, 410); self.assertNotIn("deliveries", old.json())
        resource = admin.site._registry[AccountEmailDelivery]
        self.assertEqual(resource.get_queryset(self.request).count(), 0)
        self.assertFalse(resource.has_add_permission(self.request)); self.assertFalse(resource.has_change_permission(self.request)); self.assertFalse(resource.has_delete_permission(self.request))
        self.assertEqual(self.client.get(reverse("admin:accounts_accountemaildelivery_changelist")).url, self.url)
        response = self.client.get(reverse("admin:accounts_accountemaildelivery_change", args=[self.record.pk]))
        self.assertIn(response.status_code, (302, 403)); self.assertNotIn(b"private-purpose-marker", response.content)

    def test_both_consumers_csrf_exact_input_scope_and_separate_permissions(self):
        anonymous = Client().post(self.api_url, json.dumps(self.scope), content_type="application/json")
        self.assertEqual(anonymous.status_code, 401); self.assertIn("no-store", anonymous["Cache-Control"])
        self.assertEqual(self.client.post(self.api_url, json.dumps(self.scope), content_type="application/json").status_code, 403)
        self.assertEqual(self.client.post(self.url, urlencode({**self.scope, "action": "inspect"}), content_type="application/x-www-form-urlencoded").status_code, 403)
        for fields, code in (({"user_id": self.other.pk}, 403), ({"delivery_id": self.record.pk + 99999}, 403),
                ({"extra": "submitted-private-marker"}, 409), ({"reason": "private free text"}, 409)):
            for response in (self.admin_post(**fields), self.api_post(**fields)):
                self.assertEqual(response.status_code, code); self.assertNotIn(b"submitted-private-marker", response.content)
                self.assertNotIn(b"Recorded delivery", response.content)
        self.assertEqual(self.admin_post(delivery_id=[self.record.pk, self.record.pk]).status_code, 409)
        for payload in ('{"user_id":1,"user_id":1}', '{"user_id":NaN}', '[]', 'x' * 513):
            self.assertEqual(self.client.post(self.api_url, payload, content_type="application/json", HTTP_X_CSRFTOKEN=self.token).status_code, 409)
        for value in (True, 2**53, 0): self.assertEqual(self.api_post(delivery_id=value).status_code, 409)
        self.assertEqual(self.client.post(self.api_url, self.scope, HTTP_X_CSRFTOKEN=self.token).status_code, 409)
        self.assertEqual(self.client.get(self.api_url).status_code, 405)
        self.assertEqual(self.client.get(self.url + "?delivery_id=1").status_code, 409)
        self.assertEqual(self.client.post(self.api_url + "?delivery_id=1", json.dumps(self.scope), content_type="application/json", HTTP_X_CSRFTOKEN=self.token).status_code, 409)
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.STAFF_ACCOUNT_MAIL_INSPECTED).exists())
        for codename in ("view_user", "view_accountemaildelivery"):
            permission = Permission.objects.get(content_type__app_label="accounts", codename=codename)
            self.staff.user_permissions.remove(permission)
            self.assertEqual(self.api_post().status_code, 403); self.assertEqual(self.admin_post().status_code, 403)
            self.staff.user_permissions.add(permission)

    def test_actual_user_ip_budget_shared_between_admin_api_and_independent_of_notice_budget(self):
        for limit in ("1/h/user,99/h/ip", "99/h/user,1/h/ip"):
            cache.clear()
            with override_settings(ACCOUNT_RATE_LIMITS={**settings.ACCOUNT_RATE_LIMITS, "staff_account_mail_access": limit, "staff_notice_access": "1/h/user,1/h/ip"}):
                self.assertIsNotNone(ratelimit.consume(self.request, config=settings.ACCOUNT_RATE_LIMITS, limit_get=True,
                    action="staff_notice_access", user=self.staff))
                self.assertIsNone(ratelimit.consume(self.request, config=settings.ACCOUNT_RATE_LIMITS, limit_get=True,
                    action="staff_notice_access", user=self.staff))
                self.assertEqual(self.api_post().status_code, 200)
                self.assertEqual(self.admin_post().status_code, 429); self.assertEqual(self.api_post().status_code, 429)
            cache.clear()
            with override_settings(ACCOUNT_RATE_LIMITS={**settings.ACCOUNT_RATE_LIMITS, "staff_account_mail_access": limit}):
                self.assertEqual(self.admin_post().status_code, 200); self.assertEqual(self.api_post().status_code, 429)

    def test_post_render_serialization_linkage_lifecycle_session_permission_loss_never_returns_delivery(self):
        original_render, original_response = TemplateResponse.render, mail_api._response
        for mutate in (lambda: EmailAddress.objects.filter(pk=self.address.pk).update(user=self.other),
                lambda: User.objects.filter(pk=self.target.pk).update(is_active=False),
                lambda: AccountEmailDelivery.objects.filter(pk=self.record.pk).update(attempted_at=self.record.attempted_at - timedelta(microseconds=1)),
                lambda: Session.objects.filter(session_key=self.client.session.session_key).delete(),
                lambda: self.staff.user_permissions.clear()):
            for consumer in ("admin", "api"):
                with transaction.atomic():
                    def changed_render(response):
                        result = original_render(response)
                        if response.template_name == "admin/accounts/mail_investigation.html" and response.context_data.get("inspection"): mutate()
                        return result
                    def changed_response(payload, *args, **kwargs):
                        result = original_response(payload, *args, **kwargs)
                        if "delivery" in payload: mutate()
                        return result
                    with patch("django.template.response.TemplateResponse.render", changed_render), patch("accounts.mail_api._response", changed_response):
                        response = self.admin_post() if consumer == "admin" else self.api_post()
                    self.assertIn(response.status_code, (403, 409)); self.assertIn("no-store", response["Cache-Control"])
                    self.assertNotIn(b"Recorded delivery", response.content); self.assertNotIn(b'"delivery":', response.content)
                    transaction.set_rollback(True)
