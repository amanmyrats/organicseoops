import json
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlencode

from allauth.account.internal.flows.login import AUTHENTICATION_METHODS_SESSION_KEY
from allauth.mfa.models import Authenticator
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.db import transaction
from django.template.response import TemplateResponse
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import test_paddle_receipt_retry as fixtures
from .models import AuditEvent, AuditEventType, PaddleWebhookReceipt
from .test_trial_corrections import staff_trial_request


@override_settings(**fixtures.ReceiptRetryTests._overridden_settings)
class StaffReceiptRetryAdminTests(TestCase):
    def setUp(self):
        fixtures.ReceiptRetryTests.setUp(self)
        fixtures.ReceiptRetryTests.assure(self)
        self.url = reverse("admin:tenancy_paddlewebhookreceipt_retry")
        self.inspect_url = reverse("admin:tenancy_paddlewebhookreceipt_scoped")
        self.assertEqual(self.browser.get(self.url).status_code, 200)
        self.token = self.browser.cookies["csrftoken"].value

    def post(self, **changes):
        return self.browser.post(self.url, urlencode({"receipt_id": self.receipt.pk, "reason": "Fixture reviewed retry",
            "confirm_action": "on", "csrfmiddlewaretoken": self.token, **changes}, doseq=True), content_type="application/x-www-form-urlencoded")

    def events(self): return AuditEvent.objects.filter(event_type=AuditEventType.BILLING_RECONCILIATION_RETRY)
    def original(self): return PaddleWebhookReceipt.objects.filter(pk=self.receipt.pk).values().get()

    def test_change_only_mfa_exact_id_queues_after_commit_once_no_discovery_or_paid_payload(self):
        original = self.original()
        with patch("tenancy.staff_receipt_admin.dispatch_paddle_receipt") as dispatch, \
                patch("socket.create_connection", side_effect=AssertionError("provider")), \
                patch("django.core.mail.send_mail", side_effect=AssertionError("mail")), self.captureOnCommitCallbacks(execute=True):
            page = self.post(); dispatch.assert_not_called()
        dispatch.assert_called_once_with(self.receipt.pk)
        self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, f"Receipt {self.receipt.pk} queued")
        self.assertContains(page, "Queued is not reconciled billing or paid access")
        for private in (self.receipt.event_id, self.receipt.entity_id, self.receipt.raw_digest, "Fixture reviewed retry"):
            self.assertNotContains(page, private)
        self.assertEqual(self.original(), {**original, "state": "pending", "attempts": 0, "claimed_at": None,
            "retry_after": None, "processed_at": None, "error_category": ""})
        self.assertEqual(self.events().get().details, {"environment": "sandbox", "receipt_id": self.receipt.pk, "reason": "Fixture reviewed retry"})
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.STAFF_BILLING_RECEIPT_INSPECTED).exists())
        self.assertEqual(self.browser.get(self.inspect_url).status_code, 403)
        resource = admin.site._registry[PaddleWebhookReceipt]
        self.assertTrue(resource.has_module_permission(self.request)); self.assertEqual(resource.get_queryset(self.request).count(), 0)
        self.assertFalse(resource.has_view_permission(self.request, self.receipt))
        self.assertEqual(self.browser.get(reverse("admin:tenancy_paddlewebhookreceipt_changelist")).url, self.url)
        with patch("tenancy.staff_receipt_admin.dispatch_paddle_receipt") as dispatch, self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.post().status_code, 409)
        dispatch.assert_not_called(); self.assertEqual(self.events().count(), 1)

    def test_current_change_only_mfa_csrf_strict_input_confirmation_private_errors(self):
        original = self.original()
        self.staff.user_permissions.clear()
        self.staff.user_permissions.add(Permission.objects.get(content_type__app_label="tenancy", codename="view_paddlewebhookreceipt"))
        self.assertEqual(self.post().status_code, 403); self.assertEqual(self.browser.get(self.inspect_url).status_code, 200)
        self.staff.user_permissions.add(self.permission)
        session = self.browser.session; session[AUTHENTICATION_METHODS_SESSION_KEY] = [{"method": "password"}]; session.save()
        self.assertEqual(self.post().status_code, 403)
        self.request = staff_trial_request(self.staff, self.browser)
        self.assertEqual(self.browser.post(self.url, {"receipt_id": self.receipt.pk}).status_code, 403)
        for changes in ({"confirm_action": "false"}, {"confirm_action": "no"}, {"confirm_action": "0"}, {"confirm_action": ""},
                {"reason": " "}, {"reason": "x" * 251}, {"receipt_id": 0}, {"receipt_id": 2**53},
                {"receipt_id": [self.receipt.pk, self.receipt.pk]}, {"receipt_id": self.receipt.entity_id}, {"extra": "private marker"}):
            response = self.post(**changes)
            self.assertEqual(response.status_code, 409); self.assertNotContains(response, "private marker", status_code=409)
            self.assertIn("no-store", response["Cache-Control"]); self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        for response in (self.browser.get(self.url + "?receipt_id=1"), self.browser.put(self.url, b"", HTTP_X_CSRFTOKEN=self.token),
                self.browser.post(self.url, json.dumps({}), content_type="application/json", HTTP_X_CSRFTOKEN=self.token), self.post(reason="x" * 4097)):
            self.assertEqual(response.status_code, 409)
        self.assertEqual(self.post(receipt_id=self.receipt.pk + 99999).status_code, 403)
        self.assertEqual(self.original(), original); self.assertFalse(self.events().exists())

    def test_real_user_ip_budget_shared_with_original_api_and_independent_inspector(self):
        for limit in ("1/h/user,99/h/ip", "99/h/user,1/h/ip"):
            with override_settings(ACCOUNT_RATE_LIMITS={**settings.ACCOUNT_RATE_LIMITS, "platform_provider_secret": limit, "staff_billing_receipt_access": limit}):
                for first in ("admin", "api"):
                    cache.clear()
                    with transaction.atomic(), patch("tenancy.staff_receipt_admin.dispatch_paddle_receipt"), patch("tenancy.paddle_seller_api.dispatch_paddle_receipt"):
                        if first == "admin":
                            self.assertEqual(self.post().status_code, 200)
                            self.assertEqual(fixtures.ReceiptRetryTests.post(self).status_code, 429)
                        else:
                            self.assertEqual(fixtures.ReceiptRetryTests.post(self).status_code, 202)
                            self.assertEqual(self.post().status_code, 429)
                        transaction.set_rollback(True)
                cache.clear()
                from allauth.core.internal import ratelimit
                self.assertIsNotNone(ratelimit.consume(self.request, config=settings.ACCOUNT_RATE_LIMITS, limit_get=True,
                    action="staff_billing_receipt_access", user=self.staff))
                self.assertIsNone(ratelimit.consume(self.request, config=settings.ACCOUNT_RATE_LIMITS, limit_get=True,
                    action="staff_billing_receipt_access", user=self.staff))
                with transaction.atomic(), patch("tenancy.staff_receipt_admin.dispatch_paddle_receipt"):
                    self.assertEqual(self.post().status_code, 200); transaction.set_rollback(True)

    def test_original_environment_age_future_state_and_post_render_full_source_session_rollback(self):
        original = self.original()
        with override_settings(PADDLE_ENVIRONMENT="live"): self.assertEqual(self.post().status_code, 409)
        for changes in ({"received_at": timezone.now() - timedelta(days=31)}, {"received_at": timezone.now() + timedelta(days=1)},
                {"state": "pending", "attempts": 0, "claimed_at": None, "error_category": ""}):
            with transaction.atomic():
                PaddleWebhookReceipt.objects.filter(pk=self.receipt.pk).update(**changes)
                self.assertEqual(self.post().status_code, 409); transaction.set_rollback(True)
        render = TemplateResponse.render
        mutations = [lambda changes=changes: PaddleWebhookReceipt.objects.filter(pk=self.receipt.pk).update(**changes)
            for changes in ({"event_id": "evt_" + "z" * 26}, {"notification_id": "ntf_" + "z" * 26}, {"entity_id": "txn_" + "z" * 26},
                {"raw_digest": "a" * 64}, {"environment": "live"}, {"event_type": "transaction.paid"},
                {"occurred_at": self.receipt.occurred_at + timedelta(microseconds=1)},
                {"received_at": self.receipt.received_at - timedelta(microseconds=1)}, {"subscription_id": "sub_" + "z" * 26, "customer_id": "ctm_" + "z" * 26},
                {"state": "processing", "attempts": 1, "claimed_at": timezone.now()},
                {"state": "failed", "attempts": 1, "claimed_at": timezone.now(), "retry_after": timezone.now()}, {"error_category": "private marker"})]
        mutations += [lambda: self.staff.user_permissions.clear(), lambda: Authenticator.objects.filter(user=self.staff).delete(),
            lambda: Session.objects.filter(session_key=self.browser.session.session_key).delete(),
            lambda: get_user_model().objects.filter(pk=self.staff.pk).update(session_version="invalid")]
        for mutate in mutations:
            cache.clear()
            def changed(response):
                result = render(response)
                if response.template_name == "admin/tenancy/receipt_retry.html" and response.context_data.get("queued_receipt_id"): mutate()
                return result
            with patch("django.template.response.TemplateResponse.render", changed), \
                    patch("tenancy.staff_receipt_admin.dispatch_paddle_receipt") as dispatch, self.captureOnCommitCallbacks(execute=True):
                response = self.post()
            self.assertIn(response.status_code, (403, 409)); self.assertNotIn(b"<h2>Receipt", response.content)
            self.assertIn("no-store", response["Cache-Control"]); self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
            dispatch.assert_not_called(); self.assertEqual(self.original(), original); self.assertFalse(self.events().exists())
        clock = timezone.now()
        def expired(response):
            nonlocal clock
            result = render(response)
            if response.context_data.get("queued_receipt_id"): clock = self.receipt.received_at + timedelta(days=30, microseconds=1)
            return result
        cache.clear()
        with transaction.atomic():
            PaddleWebhookReceipt.objects.filter(pk=self.receipt.pk).update(received_at=clock - timedelta(days=30))
            self.receipt.refresh_from_db()
            with patch("django.utils.timezone.now", side_effect=lambda: clock), patch("django.template.response.TemplateResponse.render", expired), \
                    patch("tenancy.staff_receipt_admin.dispatch_paddle_receipt") as dispatch, self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.post().status_code, 409)
            dispatch.assert_not_called(); self.assertFalse(self.events().exists())
            transaction.set_rollback(True)
        self.receipt.refresh_from_db(); self.assertEqual(self.original(), original); self.assertFalse(self.events().exists())
        def changed_environment(response):
            result = render(response)
            if response.context_data.get("queued_receipt_id"): settings.PADDLE_ENVIRONMENT = "live"
            return result
        cache.clear()
        with override_settings(PADDLE_ENVIRONMENT="sandbox"), patch("django.template.response.TemplateResponse.render", changed_environment), \
                patch("tenancy.staff_receipt_admin.dispatch_paddle_receipt") as dispatch, self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.post().status_code, 409)
        dispatch.assert_not_called(); self.assertEqual(self.original(), original); self.assertFalse(self.events().exists())

    def test_audit_callback_registration_render_failures_rollback_broker_failure_retains_pending(self):
        original = self.original()
        for target in ("tenancy.paddle_webhooks.AuditEvent.objects.create", "tenancy.staff_receipt_admin.transaction.on_commit", "django.template.response.TemplateResponse.render"):
            cache.clear()
            with patch(target, side_effect=RuntimeError("fixture unavailable")), \
                    patch("tenancy.staff_receipt_admin.dispatch_paddle_receipt") as dispatch, self.assertRaises(RuntimeError): self.post()
            dispatch.assert_not_called(); self.assertEqual(self.original(), original); self.assertFalse(self.events().exists())
        with patch("tenancy.staff_receipt_admin.dispatch_paddle_receipt", side_effect=RuntimeError("broker unavailable")), self.assertRaises(RuntimeError):
            with self.captureOnCommitCallbacks(execute=True): self.assertEqual(self.post().status_code, 200)
        self.assertEqual(self.original()["state"], "pending"); self.assertEqual(self.events().count(), 1)
