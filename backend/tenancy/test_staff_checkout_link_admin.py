import copy
import json
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlencode

from allauth.account.internal.flows.login import AUTHENTICATION_METHODS_SESSION_KEY
from allauth.core.internal import ratelimit
from allauth.mfa.models import Authenticator
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.template.response import TemplateResponse
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import test_staff_checkout_link_investigation as fixtures
from .models import AuditEvent, AuditEventType, Organization, PaddleCheckoutAttempt, PaddleCheckoutLinkReceipt
from .paddle_checkout_delivery import checkout_source_digest
from .paddle_reconcile import record_paid_checkout_receipt
from .test_trial_corrections import staff_trial_request


@override_settings(**fixtures.StaffCheckoutLinkInvestigationTests._overridden_settings, STAFF_MFA_REQUIRED=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "staff-checkout-link-admin"}})
class StaffCheckoutLinkAdminTests(TestCase):
    provider_response = fixtures.StaffCheckoutLinkInvestigationTests.provider_response
    subscription_receipt = fixtures.StaffCheckoutLinkInvestigationTests.subscription_receipt
    subscription_response = fixtures.StaffCheckoutLinkInvestigationTests.subscription_response

    def setUp(self):
        cache.clear(); fixtures.StaffCheckoutLinkInvestigationTests.setUp(self)
        self.browser = Client(enforce_csrf_checks=True); self.browser.force_login(self.inspector)
        self.request = staff_trial_request(self.inspector, self.browser)
        self.url = reverse("admin:tenancy_paddlecheckoutlinkreceipt_scoped")
        self.assertEqual(self.browser.get(self.url).status_code, 200)
        self.token = self.browser.cookies["csrftoken"].value

    def post(self, **changes):
        return self.browser.post(self.url, urlencode({"organization_id": self.organization.pk, "receipt_id": self.link_receipt.pk,
            "reason": "investigation", "action": "inspect", "csrfmiddlewaretoken": self.token, **changes}, doseq=True),
            content_type="application/x-www-form-urlencoded")

    def events(self):
        return AuditEvent.objects.filter(event_type=AuditEventType.STAFF_CHECKOUT_LINK_INSPECTED)

    def test_exact_private_retained_paid_closed_environment_generic_discovery_denied(self):
        record_paid_checkout_receipt(receipt=self.receipt, provider_response=self.provider_response())
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=timezone.now())
        with patch("socket.create_connection", side_effect=AssertionError("provider")), \
                patch("tenancy.paddle_checkout_delivery.checkout_link_delivery_source", side_effect=AssertionError("current source")), \
                patch("django.core.mail.send_mail", side_effect=AssertionError("SMTP")), override_settings(PADDLE_ENVIRONMENT="live"):
            page = self.post()
        self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, f"Recorded link acknowledgment {self.link_receipt.pk}")
        self.assertContains(page, self.link_receipt.acknowledged_at.isoformat())
        for text in ("not provider page loading", "Original proof issue and expiry bytes are not retained", "do not rewrite the capture"):
            self.assertContains(page, text)
        for private in (self.proof, self.owner.email, self.organization.name, self.link_receipt.source["transaction_id"],
                self.link_receipt.source["checkout_url"], self.link_receipt.source["product_id"], self.link_receipt.source["price_id"]):
            self.assertNotContains(page, private)
        self.assertIn("no-store", page["Cache-Control"]); self.assertEqual(page["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(self.events().count(), 1)
        resource = admin.site._registry[PaddleCheckoutLinkReceipt]
        self.assertEqual(resource.get_queryset(self.request).count(), 0); self.assertFalse(resource.has_view_permission(self.request, self.link_receipt))
        for permission in (resource.has_add_permission, resource.has_change_permission, resource.has_delete_permission): self.assertFalse(permission(self.request))
        self.assertEqual(self.browser.get(reverse("admin:tenancy_paddlecheckoutlinkreceipt_changelist")).url, self.url)
        detail = self.browser.get(reverse("admin:tenancy_paddlecheckoutlinkreceipt_change", args=[self.link_receipt.pk]))
        self.assertIn(detail.status_code, (302, 403)); self.assertNotIn(self.owner.email.encode(), detail.content)

    def test_current_pair_mfa_actual_csrf_strict_input_private_denial_and_change_only(self):
        for permission in self.permissions:
            self.inspector.user_permissions.remove(permission); self.assertEqual(self.post().status_code, 403)
            self.inspector.user_permissions.add(permission)
        session = self.browser.session; session[AUTHENTICATION_METHODS_SESSION_KEY] = [{"method": "password"}]; session.save()
        self.assertEqual(self.post().status_code, 403)
        self.request = staff_trial_request(self.inspector, self.browser)
        self.assertEqual(self.browser.post(self.url, {"receipt_id": self.link_receipt.pk}).status_code, 403)
        for changes, code in (({"organization_id": self.organization.pk + 99999}, 403), ({"extra": "private marker"}, 409),
                ({"reason": "private marker"}, 409), ({"action": "acknowledge"}, 409), ({"receipt_id": [self.link_receipt.pk, self.link_receipt.pk]}, 409),
                ({"receipt_id": 0}, 409), ({"receipt_id": self.attempt.transaction_id}, 409), ({"receipt_id": 2**53}, 409)):
            response = self.post(**changes)
            self.assertEqual(response.status_code, code); self.assertNotIn(b"private marker", response.content)
            self.assertIn("no-store", response["Cache-Control"]); self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        for response in (self.browser.get(self.url + "?receipt_id=1"), self.browser.put(self.url, b"", HTTP_X_CSRFTOKEN=self.token),
                self.browser.post(self.url, json.dumps({}), content_type="application/json", HTTP_X_CSRFTOKEN=self.token), self.post(reason="x" * 4097)):
            self.assertEqual(response.status_code, 409)
        self.inspector.user_permissions.clear()
        self.inspector.user_permissions.add(Permission.objects.get(content_type__app_label="tenancy", codename="change_paddlecheckoutlinkreceipt"))
        self.assertEqual(self.post().status_code, 403); self.assertFalse(self.events().exists())

    def test_actual_user_ip_budget_independent_of_checkout_in_both_directions(self):
        for limit in ("1/h/user,99/h/ip", "99/h/user,1/h/ip"):
            cache.clear()
            with override_settings(ACCOUNT_RATE_LIMITS={**settings.ACCOUNT_RATE_LIMITS, "staff_checkout_link_access": limit, "staff_checkout_access": limit}):
                self.assertIsNotNone(ratelimit.consume(self.request, config=settings.ACCOUNT_RATE_LIMITS, limit_get=True, action="staff_checkout_access", user=self.inspector))
                self.assertIsNone(ratelimit.consume(self.request, config=settings.ACCOUNT_RATE_LIMITS, limit_get=True, action="staff_checkout_access", user=self.inspector))
                self.assertEqual(self.post().status_code, 200); self.assertEqual(self.post().status_code, 429)
                cache.clear()
                self.assertEqual(self.post().status_code, 200); self.assertEqual(self.post().status_code, 429)
                self.assertIsNotNone(ratelimit.consume(self.request, config=settings.ACCOUNT_RATE_LIMITS, limit_get=True, action="staff_checkout_access", user=self.inspector))

    def test_post_render_full_json_row_minimal_binding_lifecycle_session_and_audit_failure_rollback(self):
        render = TemplateResponse.render
        original = PaddleCheckoutLinkReceipt.objects.filter(pk=self.link_receipt.pk).values().get()
        def change_json():
            changed = copy.deepcopy(self.link_receipt.source); changed["request_actor_id"] = self.inspector.pk
            PaddleCheckoutLinkReceipt.objects.filter(pk=self.link_receipt.pk).update(source=changed, source_digest=checkout_source_digest(changed))
        mutations = [change_json,
            lambda: PaddleCheckoutLinkReceipt.objects.filter(pk=self.link_receipt.pk).update(actor=self.inspector),
            lambda: PaddleCheckoutLinkReceipt.objects.filter(pk=self.link_receipt.pk).update(acknowledged_at=self.link_receipt.acknowledged_at + timedelta(microseconds=1)),
            lambda: PaddleCheckoutAttempt.objects.filter(pk=self.attempt.pk).update(organization=Organization.objects.create(name="Foreign fixture")),
            lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True),
            lambda: self.inspector.user_permissions.clear(), lambda: Authenticator.objects.filter(user=self.inspector).delete(),
            lambda: get_user_model().objects.filter(pk=self.inspector.pk).update(session_version="invalid"),
            lambda: Session.objects.filter(session_key=self.browser.session.session_key).delete()]
        for mutate in mutations:
            def changed(response):
                result = render(response)
                if response.template_name == "admin/tenancy/checkout_link_investigation.html" and response.context_data.get("inspection"): mutate()
                return result
            with patch("django.template.response.TemplateResponse.render", changed): response = self.post()
            self.assertIn(response.status_code, (403, 409)); self.assertNotIn(b"<h2>Recorded link acknowledgment", response.content)
            self.assertIn("no-store", response["Cache-Control"]); self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
            self.assertFalse(self.events().exists()); self.assertEqual(PaddleCheckoutLinkReceipt.objects.filter(pk=self.link_receipt.pk).values().get(), original)
        with patch("tenancy.staff_checkout_link_investigation.AuditEvent.objects.create", side_effect=RuntimeError("audit unavailable")), self.assertRaises(RuntimeError): self.post()
        self.assertFalse(self.events().exists())
