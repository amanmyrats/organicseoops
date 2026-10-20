import json
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlencode

from allauth.core.internal import ratelimit
from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib import admin
from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.db import transaction
from django.template.response import TemplateResponse
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from . import staff_receipt_api, test_staff_receipt_investigation as fixtures
from .models import AuditEvent, AuditEventType, PaddleWebhookReceipt


@override_settings(STAFF_MFA_REQUIRED=True, PADDLE_ENVIRONMENT="sandbox", PADDLE_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),),
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "staff-receipt-consumers"}})
class StaffReceiptConsumerTests(TestCase):
    def setUp(self):
        cache.clear(); fixtures.StaffReceiptInvestigationTests.setUp(self)
        self.url = reverse("admin:tenancy_paddlewebhookreceipt_scoped")
        self.api_url = reverse("platform-inspect-billing-receipt")
        guarded = Client(enforce_csrf_checks=True); guarded.cookies = self.browser.cookies; self.browser = guarded
        self.assertEqual(self.browser.get(self.url).status_code, 200)
        self.scope = dict(receipt_id=self.receipt.pk, reason="investigation")
        self.token = self.browser.cookies["csrftoken"].value

    def admin_post(self, **changes):
        return self.browser.post(self.url, urlencode({**self.scope, "action": "inspect", "csrfmiddlewaretoken": self.token, **changes}, doseq=True),
            content_type="application/x-www-form-urlencoded")

    def api_post(self, **changes):
        return self.browser.post(self.api_url, json.dumps({**self.scope, **changes}), content_type="application/json", HTTP_X_CSRFTOKEN=self.token)

    def test_exact_private_audited_consumers_generic_denial_and_independent_retry_authority(self):
        with patch("tenancy.paddle_seller_api.dispatch_paddle_receipt", side_effect=AssertionError("dispatch")), \
                patch("socket.create_connection", side_effect=AssertionError("provider")):
            page = self.admin_post(); result = self.api_post()
        self.assertEqual(page.status_code, 200, page.content); self.assertEqual(result.status_code, 200, result.content)
        self.assertContains(page, f"Recorded receipt {self.receipt.pk}")
        for explanation in ("not organization ownership", "Succeeded may be a no-op", "not lifetime attempts", "not provider occurrence times"):
            self.assertContains(page, explanation)
        for private in (self.receipt.event_id, self.receipt.notification_id, self.receipt.entity_id, self.receipt.raw_digest):
            self.assertNotContains(page, private); self.assertNotIn(private, result.content.decode())
        self.assertEqual(len(result.json()["receipt"]), 9)
        for response in (page, result):
            self.assertIn("no-store", response["Cache-Control"]); self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.STAFF_BILLING_RECEIPT_INSPECTED).count(), 2)
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.BILLING_RECONCILIATION_RETRY).exists())
        resource = admin.site._registry[PaddleWebhookReceipt]
        self.assertEqual(resource.get_queryset(self.request).count(), 0)
        for permission in (resource.has_add_permission, resource.has_change_permission, resource.has_delete_permission):
            self.assertFalse(permission(self.request))
        self.assertEqual(self.browser.get(reverse("admin:tenancy_paddlewebhookreceipt_changelist")).url, self.url)
        detail = self.browser.get(reverse("admin:tenancy_paddlewebhookreceipt_change", args=[self.receipt.pk]))
        self.assertIn(detail.status_code, (302, 403)); self.assertNotIn(self.receipt.event_id.encode(), detail.content)
        retry = reverse("platform-paddle-receipt-retry", args=[self.receipt.pk])
        self.assertEqual(self.browser.post(retry, json.dumps({"reason": "Fixture recovery"}), content_type="application/json", HTTP_X_CSRFTOKEN=self.token).status_code, 403)
        change = Permission.objects.get(content_type__app_label="tenancy", codename="change_paddlewebhookreceipt")
        self.inspector.user_permissions.remove(self.permission); self.inspector.user_permissions.add(change)
        self.assertEqual(self.api_post().status_code, 403); self.assertEqual(self.admin_post().status_code, 403)

    def test_csrf_strict_inputs_private_denials_no_payload_or_scope_discovery(self):
        anonymous = Client().post(self.api_url, json.dumps(self.scope), content_type="application/json")
        self.assertEqual(anonymous.status_code, 401); self.assertIn("no-store", anonymous["Cache-Control"])
        self.assertEqual(self.browser.post(self.api_url, json.dumps(self.scope), content_type="application/json").status_code, 403)
        self.assertEqual(self.browser.post(self.url, urlencode({**self.scope, "action": "inspect"}), content_type="application/x-www-form-urlencoded").status_code, 403)
        for fields, code in (({"receipt_id": self.receipt.pk + 99999}, 403), ({"extra": "private marker"}, 409), ({"reason": "private prose"}, 409)):
            for response in (self.admin_post(**fields), self.api_post(**fields)):
                self.assertEqual(response.status_code, code); self.assertNotIn(b"private marker", response.content); self.assertNotIn(b"Recorded receipt", response.content)
        self.assertEqual(self.admin_post(receipt_id=[self.receipt.pk, self.receipt.pk]).status_code, 409)
        for payload in ('{"receipt_id":1,"receipt_id":1}', '{"receipt_id":NaN}', '[]', 'x' * 513):
            self.assertEqual(self.browser.post(self.api_url, payload, content_type="application/json", HTTP_X_CSRFTOKEN=self.token).status_code, 409)
        for value in (True, 2**53, 0): self.assertEqual(self.api_post(receipt_id=value).status_code, 409)
        self.assertEqual(self.browser.post(self.api_url, self.scope, HTTP_X_CSRFTOKEN=self.token).status_code, 409)
        method = self.browser.get(self.api_url); self.assertEqual(method.status_code, 405); self.assertIn("no-store", method["Cache-Control"])
        self.assertEqual(self.browser.get(self.url + "?receipt_id=1").status_code, 409)
        self.assertEqual(self.browser.post(self.api_url + "?receipt_id=1", json.dumps(self.scope), content_type="application/json", HTTP_X_CSRFTOKEN=self.token).status_code, 409)
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.STAFF_BILLING_RECEIPT_INSPECTED).exists())

    def test_actual_shared_user_ip_budget_independent_of_other_staff_budget(self):
        for limit in ("1/h/user,99/h/ip", "99/h/user,1/h/ip"):
            cache.clear()
            with override_settings(ACCOUNT_RATE_LIMITS={**settings.ACCOUNT_RATE_LIMITS, "staff_billing_receipt_access": limit, "staff_email_feedback_access": "1/h/user,1/h/ip"}):
                self.assertIsNotNone(ratelimit.consume(self.request, config=settings.ACCOUNT_RATE_LIMITS, limit_get=True, action="staff_email_feedback_access", user=self.inspector))
                self.assertIsNone(ratelimit.consume(self.request, config=settings.ACCOUNT_RATE_LIMITS, limit_get=True, action="staff_email_feedback_access", user=self.inspector))
                self.assertEqual(self.api_post().status_code, 200); self.assertEqual(self.admin_post().status_code, 429); self.assertEqual(self.api_post().status_code, 429)
            cache.clear()
            with override_settings(ACCOUNT_RATE_LIMITS={**settings.ACCOUNT_RATE_LIMITS, "staff_billing_receipt_access": limit}):
                self.assertEqual(self.admin_post().status_code, 200); self.assertEqual(self.api_post().status_code, 429)

    def test_post_render_serialization_hidden_source_dates_session_permission_loss_rolls_back_audit(self):
        original_render, original_response = TemplateResponse.render, staff_receipt_api._response
        for mutate in (lambda: PaddleWebhookReceipt.objects.filter(pk=self.receipt.pk).update(raw_digest="e" * 64),
                lambda: PaddleWebhookReceipt.objects.filter(pk=self.receipt.pk).update(entity_id="txn_" + "f" * 26),
                lambda: PaddleWebhookReceipt.objects.filter(pk=self.receipt.pk).update(received_at=self.receipt.received_at - timedelta(microseconds=1)),
                lambda: Session.objects.filter(session_key=self.browser.session.session_key).delete(), lambda: self.inspector.user_permissions.clear()):
            for consumer in ("admin", "api"):
                with transaction.atomic():
                    def changed_render(response):
                        result = original_render(response)
                        if response.template_name == "admin/tenancy/receipt_investigation.html" and response.context_data.get("inspection"): mutate()
                        return result
                    def changed_response(payload, *args, **kwargs):
                        result = original_response(payload, *args, **kwargs)
                        if "receipt" in payload: mutate()
                        return result
                    with patch("django.template.response.TemplateResponse.render", changed_render), patch.object(staff_receipt_api, "_response", changed_response):
                        response = self.admin_post() if consumer == "admin" else self.api_post()
                    self.assertIn(response.status_code, (403, 409)); self.assertIn("no-store", response["Cache-Control"])
                    self.assertNotIn(b"Recorded receipt", response.content); self.assertNotIn(b'"receipt":', response.content)
                    self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.STAFF_BILLING_RECEIPT_INSPECTED).exists())
                    transaction.set_rollback(True)
