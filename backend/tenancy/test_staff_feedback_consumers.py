import json
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlencode

from allauth.account.models import EmailAddress
from allauth.core.internal import ratelimit
from django.conf import settings
from django.contrib import admin
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.db import transaction
from django.template.response import TemplateResponse
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from . import email_feedback_api, test_staff_feedback_investigation as fixtures
from .models import AuditEvent, AuditEventType, EmailFeedbackReceipt, EmailSuppression


@override_settings(STAFF_MFA_REQUIRED=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "staff-feedback-consumers"}})
class StaffFeedbackConsumerTests(TestCase):
    def setUp(self):
        cache.clear(); fixtures.StaffFeedbackInvestigationTests.setUp(self)
        self.url = reverse("admin:tenancy_emailsuppression_scoped")
        self.api_url = reverse("platform-inspect-email-feedback")
        guarded = Client(enforce_csrf_checks=True); guarded.cookies = self.client.cookies; self.client = guarded
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.scope = dict(user_id=self.target.pk, email_address_id=self.address.pk, suppression_id=self.row.pk, reason="investigation")
        self.token = self.client.cookies["csrftoken"].value

    def admin_post(self, **changes):
        return self.client.post(self.url, urlencode({**self.scope, "action": "inspect", "csrfmiddlewaretoken": self.token, **changes}, doseq=True),
            content_type="application/x-www-form-urlencoded")

    def api_post(self, **changes):
        return self.client.post(self.api_url, json.dumps({**self.scope, **changes}), content_type="application/json", HTTP_X_CSRFTOKEN=self.token)

    def test_exact_private_consumers_audit_legacy_retirement_generic_denial_no_clearance(self):
        with patch("tenancy.email_feedback.clear_email_suppression", side_effect=AssertionError("clearance")):
            page = self.admin_post(); result = self.api_post()
        self.assertEqual(page.status_code, 200, page.content); self.assertEqual(result.status_code, 200, result.content)
        self.assertContains(page, f"Recorded suppression {self.row.pk}")
        self.assertContains(page, "not proof of the original recipient"); self.assertContains(page, "not SES event occurrence")
        for private in (self.target.email, self.receipt.event_id, self.row.address_digest, self.receipt.addresses_digest):
            self.assertNotContains(page, private); self.assertNotIn(private, result.content.decode())
        self.assertEqual((len(result.json()["suppression"]), len(result.json()["feedback"])), (3, 3))
        for response in (page, result):
            self.assertIn("no-store", response["Cache-Control"]); self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.STAFF_EMAIL_FEEDBACK_INSPECTED).count(), 2)
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.EMAIL_SUPPRESSION_CLEARED).exists())
        self.assertTrue(EmailSuppression.objects.filter(pk=self.row.pk).exists())
        old = self.client.get(reverse("platform-email-suppressions"))
        self.assertEqual(old.status_code, 410); self.assertNotIn("suppressions", old.json())
        for model in (EmailSuppression, EmailFeedbackReceipt):
            resource = admin.site._registry[model]
            self.assertEqual(resource.get_queryset(self.request).count(), 0)
            self.assertFalse(resource.has_add_permission(self.request)); self.assertFalse(resource.has_change_permission(self.request)); self.assertFalse(resource.has_delete_permission(self.request))
        feedback_admin = admin.site._registry[EmailFeedbackReceipt]
        self.assertFalse(feedback_admin.has_module_permission(self.request)); self.assertFalse(feedback_admin.has_view_permission(self.request))
        self.assertEqual(self.client.get(reverse("admin:tenancy_emailsuppression_changelist")).url, self.url)
        for name, identity in (("emailsuppression", self.row.pk), ("emailfeedbackreceipt", self.receipt.pk)):
            response = self.client.get(reverse(f"admin:tenancy_{name}_change", args=[identity]))
            self.assertIn(response.status_code, (302, 403)); self.assertNotIn(self.receipt.event_id.encode(), response.content)
        # Inspection permissions cannot clear a suppression.
        response = self.client.post(reverse("platform-clear-email-suppression", args=[self.row.pk]),
            json.dumps({"reason": "review", "confirm_review": True}), content_type="application/json", HTTP_X_CSRFTOKEN=self.token)
        self.assertEqual(response.status_code, 403)

    def test_csrf_strict_scope_input_private_denials_and_each_separate_view_permission(self):
        anonymous = Client().post(self.api_url, json.dumps(self.scope), content_type="application/json")
        self.assertEqual(anonymous.status_code, 401); self.assertIn("no-store", anonymous["Cache-Control"])
        self.assertEqual(self.client.post(self.api_url, json.dumps(self.scope), content_type="application/json").status_code, 403)
        self.assertEqual(self.client.post(self.url, urlencode({**self.scope, "action": "inspect"}), content_type="application/x-www-form-urlencoded").status_code, 403)
        for fields, code in (({"user_id": self.other.pk}, 403), ({"suppression_id": self.row.pk + 99999}, 403),
                ({"email_address_id": self.address.pk + 99999}, 403), ({"extra": "submitted-private-marker"}, 409), ({"reason": "private prose"}, 409)):
            for response in (self.admin_post(**fields), self.api_post(**fields)):
                self.assertEqual(response.status_code, code); self.assertNotIn(b"submitted-private-marker", response.content)
                self.assertNotIn(b"Recorded suppression", response.content)
        self.assertEqual(self.admin_post(suppression_id=[self.row.pk, self.row.pk]).status_code, 409)
        for payload in ('{"user_id":1,"user_id":1}', '{"user_id":NaN}', '[]', 'x' * 513):
            self.assertEqual(self.client.post(self.api_url, payload, content_type="application/json", HTTP_X_CSRFTOKEN=self.token).status_code, 409)
        for value in (True, 2**53, 0): self.assertEqual(self.api_post(suppression_id=value).status_code, 409)
        self.assertEqual(self.client.post(self.api_url, self.scope, HTTP_X_CSRFTOKEN=self.token).status_code, 409)
        method = self.client.get(self.api_url); self.assertEqual(method.status_code, 405); self.assertIn("no-store", method["Cache-Control"])
        self.assertEqual(self.client.get(self.url + "?suppression_id=1").status_code, 409)
        self.assertEqual(self.client.post(self.api_url + "?suppression_id=1", json.dumps(self.scope), content_type="application/json", HTTP_X_CSRFTOKEN=self.token).status_code, 409)
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.STAFF_EMAIL_FEEDBACK_INSPECTED).exists())
        for permission in self.permissions:
            self.staff.user_permissions.remove(permission)
            self.assertEqual(self.api_post().status_code, 403); self.assertEqual(self.admin_post().status_code, 403)
            self.staff.user_permissions.add(permission)

    def test_actual_shared_user_ip_budget_independent_of_account_mail_budget(self):
        for limit in ("1/h/user,99/h/ip", "99/h/user,1/h/ip"):
            cache.clear()
            with override_settings(ACCOUNT_RATE_LIMITS={**settings.ACCOUNT_RATE_LIMITS, "staff_email_feedback_access": limit, "staff_account_mail_access": "1/h/user,1/h/ip"}):
                self.assertIsNotNone(ratelimit.consume(self.request, config=settings.ACCOUNT_RATE_LIMITS, limit_get=True, action="staff_account_mail_access", user=self.staff))
                self.assertIsNone(ratelimit.consume(self.request, config=settings.ACCOUNT_RATE_LIMITS, limit_get=True, action="staff_account_mail_access", user=self.staff))
                self.assertEqual(self.api_post().status_code, 200); self.assertEqual(self.admin_post().status_code, 429); self.assertEqual(self.api_post().status_code, 429)
            cache.clear()
            with override_settings(ACCOUNT_RATE_LIMITS={**settings.ACCOUNT_RATE_LIMITS, "staff_email_feedback_access": limit}):
                self.assertEqual(self.admin_post().status_code, 200); self.assertEqual(self.api_post().status_code, 429)

    def test_post_render_serialization_hidden_source_linkage_lifecycle_session_permission_loss(self):
        original_render, original_response = TemplateResponse.render, email_feedback_api._response
        for mutate in (lambda: EmailAddress.objects.filter(pk=self.address.pk).update(user=self.other),
                lambda: User.objects.filter(pk=self.target.pk).update(is_active=False),
                lambda: EmailSuppression.objects.filter(pk=self.row.pk).update(address_digest="e" * 64),
                lambda: EmailFeedbackReceipt.objects.filter(pk=self.receipt.pk).update(addresses_digest="f" * 64),
                lambda: EmailFeedbackReceipt.objects.filter(pk=self.receipt.pk).update(received_at=self.receipt.received_at - timedelta(microseconds=1)),
                lambda: Session.objects.filter(session_key=self.client.session.session_key).delete(), lambda: self.staff.user_permissions.clear()):
            for consumer in ("admin", "api"):
                with transaction.atomic():
                    def changed_render(response):
                        result = original_render(response)
                        if response.template_name == "admin/tenancy/feedback_investigation.html" and response.context_data.get("inspection"): mutate()
                        return result
                    def changed_response(payload, *args, **kwargs):
                        result = original_response(payload, *args, **kwargs)
                        if "feedback" in payload: mutate()
                        return result
                    with patch("django.template.response.TemplateResponse.render", changed_render), patch("tenancy.email_feedback_api._response", changed_response):
                        response = self.admin_post() if consumer == "admin" else self.api_post()
                    self.assertIn(response.status_code, (403, 409)); self.assertIn("no-store", response["Cache-Control"])
                    self.assertNotIn(b"Recorded suppression", response.content); self.assertNotIn(b'"feedback":', response.content)
                    transaction.set_rollback(True)
