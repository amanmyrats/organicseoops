import json
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlencode

from allauth.account.internal.flows.login import AUTHENTICATION_METHODS_SESSION_KEY
from allauth.core.internal import ratelimit
from django.conf import settings
from django.contrib import admin
from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.template.response import TemplateResponse
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from . import test_staff_subscription_investigation as fixtures
from .models import AuditEvent, AuditEventType, Organization, PaddleSubscription
from .test_trial_corrections import staff_trial_request


@override_settings(**fixtures.StaffSubscriptionInvestigationTests._overridden_settings,
    STAFF_MFA_REQUIRED=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "staff-subscription-admin"}})
class StaffSubscriptionAdminTests(TestCase):
    provider_response = fixtures.StaffSubscriptionInvestigationTests.provider_response
    subscription_receipt = fixtures.StaffSubscriptionInvestigationTests.subscription_receipt
    subscription_response = fixtures.StaffSubscriptionInvestigationTests.subscription_response
    current = fixtures.StaffSubscriptionInvestigationTests.current

    def setUp(self):
        cache.clear(); fixtures.StaffSubscriptionInvestigationTests.setUp(self); self.current()
        self.browser = Client(enforce_csrf_checks=True); self.browser.force_login(self.inspector)
        self.request = staff_trial_request(self.inspector, self.browser)
        self.url = reverse("admin:tenancy_paddlesubscription_scoped")
        self.assertEqual(self.browser.get(self.url).status_code, 200)
        self.token = self.browser.cookies["csrftoken"].value

    def post(self, **changes):
        return self.browser.post(self.url, urlencode({"organization_id": self.organization.pk, "subscription_id": self.subscription.pk,
            "reason": "investigation", "action": "inspect", "csrfmiddlewaretoken": self.token, **changes}, doseq=True),
            content_type="application/x-www-form-urlencoded")

    def events(self):
        return AuditEvent.objects.filter(event_type=AuditEventType.STAFF_SUBSCRIPTION_INSPECTED)

    def test_exact_private_audited_inspection_generic_denied_without_provider_or_correction(self):
        with patch("socket.create_connection", side_effect=AssertionError("provider")), \
                patch("django.core.mail.send_mail", side_effect=AssertionError("SMTP")):
            page = self.post()
        self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, f"Recorded linked subscription {self.subscription.pk}")
        for text in ("not current paid access", "Missing verification remains unknown", "Provider dates can be future", "local record ID may survive", "separately confirmed closure cancellation ledger"):
            self.assertContains(page, text)
        for private in (self.subscription.customer_id, self.subscription.subscription_id, self.owner.email, self.organization.name, "currency_code"):
            self.assertNotContains(page, private)
        self.assertIn("no-store", page["Cache-Control"]); self.assertEqual(page["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(self.events().count(), 1)
        resource = admin.site._registry[PaddleSubscription]
        self.assertEqual(resource.get_queryset(self.request).count(), 0)
        for permission in (resource.has_add_permission, resource.has_change_permission, resource.has_delete_permission): self.assertFalse(permission(self.request))
        self.assertEqual(self.browser.get(reverse("admin:tenancy_paddlesubscription_changelist")).url, self.url)
        detail = self.browser.get(reverse("admin:tenancy_paddlesubscription_change", args=[self.subscription.pk]))
        self.assertIn(detail.status_code, (302, 403)); self.assertNotIn(self.subscription.customer_id.encode(), detail.content)

    def test_pair_current_mfa_csrf_strict_scope_private_denials_no_free_text_echo_or_audit(self):
        for permission in self.permissions:
            self.inspector.user_permissions.remove(permission); self.assertEqual(self.post().status_code, 403)
            self.inspector.user_permissions.add(permission)
        session = self.browser.session; session[AUTHENTICATION_METHODS_SESSION_KEY] = [{"method": "password"}]; session.save()
        self.assertEqual(self.post().status_code, 403)
        self.request = staff_trial_request(self.inspector, self.browser)
        self.assertEqual(self.browser.post(self.url, {"subscription_id": self.subscription.pk}).status_code, 403)
        for changes, code in (({"organization_id": self.organization.pk + 99999}, 403), ({"extra": "private marker"}, 409),
                ({"reason": "private marker"}, 409), ({"action": "reconcile"}, 409),
                ({"subscription_id": [self.subscription.pk, self.subscription.pk]}, 409), ({"subscription_id": 0}, 409),
                ({"subscription_id": self.subscription.subscription_id}, 409), ({"subscription_id": 2**53}, 409)):
            response = self.post(**changes)
            self.assertEqual(response.status_code, code); self.assertNotIn(b"private marker", response.content)
            self.assertIn("no-store", response["Cache-Control"]); self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        for response in (self.browser.get(self.url + "?subscription_id=1"), self.browser.put(self.url, b"", HTTP_X_CSRFTOKEN=self.token),
                self.browser.post(self.url, json.dumps({}), content_type="application/json", HTTP_X_CSRFTOKEN=self.token), self.post(reason="x" * 4097)):
            self.assertEqual(response.status_code, 409)
        self.inspector.user_permissions.clear()
        self.inspector.user_permissions.add(Permission.objects.get(content_type__app_label="tenancy", codename="change_paddlesubscription"))
        self.assertEqual(self.post().status_code, 403); self.assertFalse(self.events().exists())

    def test_actual_user_ip_budget_independent_of_trial_budget(self):
        for limit in ("1/h/user,99/h/ip", "99/h/user,1/h/ip"):
            cache.clear()
            with override_settings(ACCOUNT_RATE_LIMITS={**settings.ACCOUNT_RATE_LIMITS, "staff_subscription_access": limit, "staff_trial_access": limit}):
                self.assertIsNotNone(ratelimit.consume(self.request, config=settings.ACCOUNT_RATE_LIMITS, limit_get=True, action="staff_trial_access", user=self.inspector))
                self.assertIsNone(ratelimit.consume(self.request, config=settings.ACCOUNT_RATE_LIMITS, limit_get=True, action="staff_trial_access", user=self.inspector))
                self.assertEqual(self.post().status_code, 200); self.assertEqual(self.post().status_code, 429)

    def test_post_render_hidden_identity_dates_lifecycle_session_and_audit_failure_roll_back(self):
        render = TemplateResponse.render
        original = PaddleSubscription.objects.filter(pk=self.subscription.pk).values().get()
        for mutate in (lambda: PaddleSubscription.objects.filter(pk=self.subscription.pk).update(customer_id="ctm_" + "z" * 26),
                lambda: PaddleSubscription.objects.filter(pk=self.subscription.pk).update(currency_code="TRY"),
                lambda: PaddleSubscription.objects.filter(pk=self.subscription.pk).update(verified_at=self.subscription.verified_at - timedelta(microseconds=1)),
                lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True),
                lambda: self.inspector.user_permissions.clear(), lambda: Session.objects.filter(session_key=self.browser.session.session_key).delete()):
            def changed(response):
                result = render(response)
                if response.template_name == "admin/tenancy/subscription_investigation.html" and response.context_data.get("inspection"): mutate()
                return result
            with patch("django.template.response.TemplateResponse.render", changed): response = self.post()
            self.assertIn(response.status_code, (403, 409)); self.assertNotIn(b"<h2>Recorded linked subscription", response.content)
            self.assertIn("no-store", response["Cache-Control"]); self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
            self.assertFalse(self.events().exists()); self.assertEqual(PaddleSubscription.objects.filter(pk=self.subscription.pk).values().get(), original)
        with patch("tenancy.staff_subscription_investigation.AuditEvent.objects.create", side_effect=RuntimeError("audit unavailable")), self.assertRaises(RuntimeError): self.post()
        self.assertFalse(self.events().exists())
