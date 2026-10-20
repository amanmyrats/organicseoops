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
from django.utils import timezone

from . import test_staff_subscription_history_investigation as fixtures
from .models import AuditEvent, AuditEventType, Organization, PaddleSubscriptionHistory
from .test_trial_corrections import staff_trial_request


@override_settings(**fixtures.StaffSubscriptionHistoryInvestigationTests._overridden_settings,
    STAFF_MFA_REQUIRED=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "staff-subscription-history-admin"}})
class StaffSubscriptionHistoryAdminTests(TestCase):
    provider_response = fixtures.StaffSubscriptionHistoryInvestigationTests.provider_response
    subscription_receipt = fixtures.StaffSubscriptionHistoryInvestigationTests.subscription_receipt
    subscription_response = fixtures.StaffSubscriptionHistoryInvestigationTests.subscription_response
    archive = fixtures.StaffSubscriptionHistoryInvestigationTests.archive

    def setUp(self):
        cache.clear(); fixtures.StaffSubscriptionHistoryInvestigationTests.setUp(self); self.archive()
        self.browser = Client(enforce_csrf_checks=True); self.browser.force_login(self.inspector)
        self.request = staff_trial_request(self.inspector, self.browser)
        self.url = reverse("admin:tenancy_paddlesubscriptionhistory_scoped")
        self.assertEqual(self.browser.get(self.url).status_code, 200)
        self.token = self.browser.cookies["csrftoken"].value

    def post(self, **changes):
        return self.browser.post(self.url, urlencode({"organization_id": self.organization.pk, "history_id": self.history.pk,
            "reason": "investigation", "action": "inspect", "csrfmiddlewaretoken": self.token, **changes}, doseq=True),
            content_type="application/x-www-form-urlencoded")

    def events(self):
        return AuditEvent.objects.filter(event_type=AuditEventType.STAFF_SUBSCRIPTION_HISTORY_INSPECTED)

    def test_exact_private_retained_copy_generic_denied_and_no_provider_authority(self):
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=timezone.now())
        with patch("socket.create_connection", side_effect=AssertionError("provider")), \
                patch("django.core.mail.send_mail", side_effect=AssertionError("SMTP")), override_settings(PADDLE_ENVIRONMENT="live"):
            page = self.post()
        self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, f"Recorded archived subscription {self.history.pk}")
        for text in ("not current paid access", "complete lifetime history", "prior last server observation", "Optional provider dates can be future", "no later adjustment"):
            self.assertContains(page, text)
        for private in (self.history.customer_id, self.history.subscription_id, self.owner.email, self.organization.name): self.assertNotContains(page, private)
        self.assertIn("no-store", page["Cache-Control"]); self.assertEqual(page["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(self.events().count(), 1)
        resource = admin.site._registry[PaddleSubscriptionHistory]
        self.assertEqual(resource.get_queryset(self.request).count(), 0)
        self.assertFalse(resource.has_view_permission(self.request, self.history))
        for permission in (resource.has_add_permission, resource.has_change_permission, resource.has_delete_permission): self.assertFalse(permission(self.request))
        self.assertEqual(self.browser.get(reverse("admin:tenancy_paddlesubscriptionhistory_changelist")).url, self.url)
        detail = self.browser.get(reverse("admin:tenancy_paddlesubscriptionhistory_change", args=[self.history.pk]))
        self.assertIn(detail.status_code, (302, 403)); self.assertNotIn(self.history.customer_id.encode(), detail.content)

    def test_current_pair_mfa_actual_csrf_strict_input_private_denial_and_change_only(self):
        for permission in self.permissions:
            self.inspector.user_permissions.remove(permission); self.assertEqual(self.post().status_code, 403)
            self.inspector.user_permissions.add(permission)
        session = self.browser.session; session[AUTHENTICATION_METHODS_SESSION_KEY] = [{"method": "password"}]; session.save()
        self.assertEqual(self.post().status_code, 403)
        self.request = staff_trial_request(self.inspector, self.browser)
        self.assertEqual(self.browser.post(self.url, {"history_id": self.history.pk}).status_code, 403)
        for changes, code in (({"organization_id": self.organization.pk + 99999}, 403), ({"extra": "private marker"}, 409),
                ({"reason": "private marker"}, 409), ({"action": "reconcile"}, 409),
                ({"history_id": [self.history.pk, self.history.pk]}, 409), ({"history_id": 0}, 409),
                ({"history_id": self.history.subscription_id}, 409), ({"history_id": 2**53}, 409)):
            response = self.post(**changes)
            self.assertEqual(response.status_code, code); self.assertNotIn(b"private marker", response.content)
            self.assertIn("no-store", response["Cache-Control"]); self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        for response in (self.browser.get(self.url + "?history_id=1"), self.browser.put(self.url, b"", HTTP_X_CSRFTOKEN=self.token),
                self.browser.post(self.url, json.dumps({}), content_type="application/json", HTTP_X_CSRFTOKEN=self.token), self.post(reason="x" * 4097)):
            self.assertEqual(response.status_code, 409)
        self.inspector.user_permissions.clear()
        self.inspector.user_permissions.add(Permission.objects.get(content_type__app_label="tenancy", codename="change_paddlesubscriptionhistory"))
        self.assertEqual(self.post().status_code, 403); self.assertFalse(self.events().exists())

    def test_actual_user_ip_budget_independent_of_current_subscription_in_both_directions(self):
        for limit in ("1/h/user,99/h/ip", "99/h/user,1/h/ip"):
            cache.clear()
            with override_settings(ACCOUNT_RATE_LIMITS={**settings.ACCOUNT_RATE_LIMITS, "staff_subscription_history_access": limit, "staff_subscription_access": limit}):
                self.assertIsNotNone(ratelimit.consume(self.request, config=settings.ACCOUNT_RATE_LIMITS, limit_get=True, action="staff_subscription_access", user=self.inspector))
                self.assertIsNone(ratelimit.consume(self.request, config=settings.ACCOUNT_RATE_LIMITS, limit_get=True, action="staff_subscription_access", user=self.inspector))
                self.assertEqual(self.post().status_code, 200); self.assertEqual(self.post().status_code, 429)
                cache.clear()
                self.assertEqual(self.post().status_code, 200); self.assertEqual(self.post().status_code, 429)
                self.assertIsNotNone(ratelimit.consume(self.request, config=settings.ACCOUNT_RATE_LIMITS, limit_get=True, action="staff_subscription_access", user=self.inspector))

    def test_post_render_hidden_identity_dates_lifecycle_session_and_audit_failure_rollback(self):
        render = TemplateResponse.render
        original = PaddleSubscriptionHistory.objects.filter(pk=self.history.pk).values().get()
        for mutate in (lambda: PaddleSubscriptionHistory.objects.filter(pk=self.history.pk).update(customer_id="ctm_" + "z" * 26),
                lambda: PaddleSubscriptionHistory.objects.filter(pk=self.history.pk).update(subscription_id="sub_" + "z" * 26),
                lambda: PaddleSubscriptionHistory.objects.filter(pk=self.history.pk).update(verified_at=self.history.verified_at - timedelta(microseconds=1)),
                lambda: PaddleSubscriptionHistory.objects.filter(pk=self.history.pk).update(archived_at=self.history.archived_at + timedelta(microseconds=1)),
                lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True),
                lambda: self.inspector.user_permissions.clear(), lambda: Session.objects.filter(session_key=self.browser.session.session_key).delete()):
            def changed(response):
                result = render(response)
                if response.template_name == "admin/tenancy/subscription_history_investigation.html" and response.context_data.get("inspection"): mutate()
                return result
            with patch("django.template.response.TemplateResponse.render", changed): response = self.post()
            self.assertIn(response.status_code, (403, 409)); self.assertNotIn(b"<h2>Recorded archived subscription", response.content)
            self.assertIn("no-store", response["Cache-Control"]); self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
            self.assertFalse(self.events().exists()); self.assertEqual(PaddleSubscriptionHistory.objects.filter(pk=self.history.pk).values().get(), original)
        with patch("tenancy.staff_subscription_history_investigation.AuditEvent.objects.create", side_effect=RuntimeError("audit unavailable")), self.assertRaises(RuntimeError): self.post()
        self.assertFalse(self.events().exists())
