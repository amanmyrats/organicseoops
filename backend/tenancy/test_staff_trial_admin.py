import json
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlencode

from allauth.account.internal.flows.login import AUTHENTICATION_METHODS_SESSION_KEY
from django.conf import settings
from django.contrib import admin
from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.db import transaction
from django.template.response import TemplateResponse
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import test_staff_trial_investigation as fixtures
from .models import AutomaticTrialEligibility, AuditEvent, AuditEventType, Organization, OrganizationTrial
from .test_trial_corrections import staff_trial_request


@override_settings(STAFF_MFA_REQUIRED=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "staff-trial-admin"}})
class StaffTrialAdminTests(TestCase):
    def setUp(self):
        cache.clear(); fixtures.StaffTrialInvestigationTests.setUp(self)
        self.browser = Client(enforce_csrf_checks=True); self.browser.force_login(self.inspector)
        self.request = staff_trial_request(self.inspector, self.browser)
        self.url = reverse("admin:tenancy_organizationtrial_scoped")
        self.correction_url = reverse("admin:tenancy_organizationtrial_corrections")
        self.assertEqual(self.browser.get(self.url).status_code, 200)
        self.token = self.browser.cookies["csrftoken"].value

    def post(self, **changes):
        return self.browser.post(self.url, urlencode({"organization_id": self.organization.pk, "trial_id": self.trial.pk,
            "reason": "investigation", "action": "inspect", "csrfmiddlewaretoken": self.token, **changes}, doseq=True),
            content_type="application/x-www-form-urlencoded")

    def events(self):
        return AuditEvent.objects.filter(event_type=AuditEventType.STAFF_TRIAL_INSPECTED)

    def test_exact_private_audited_inspection_no_generic_trial_eligibility_or_correction_authority(self):
        with patch("socket.create_connection", side_effect=AssertionError("provider")), \
                patch("django.core.mail.send_mail", side_effect=AssertionError("SMTP")):
            response = self.post()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertContains(response, f"Recorded trial {self.trial.pk}")
        for text in ("not effective paid access", "remaining usage", "extension history", "Older policy values"):
            self.assertContains(response, text)
        for private in (self.owner.email, self.organization.name, "granted_at", "automatic_eligibility_id"):
            self.assertNotContains(response, private)
        self.assertIn("no-store", response["Cache-Control"]); self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(self.events().count(), 1)
        self.assertEqual(self.browser.get(reverse("admin:tenancy_organizationtrial_changelist")).url, self.url)
        for model, prefix, identity in ((OrganizationTrial, "organizationtrial", self.trial.pk),
                (AutomaticTrialEligibility, "automatictrialeligibility", self.trial.automatic_eligibility_id)):
            resource = admin.site._registry[model]
            self.assertEqual(resource.get_queryset(self.request).count(), 0)
            for permission in (resource.has_add_permission, resource.has_change_permission, resource.has_delete_permission): self.assertFalse(permission(self.request))
            detail = self.browser.get(reverse(f"admin:tenancy_{prefix}_change", args=[identity]))
            self.assertIn(detail.status_code, (302, 403)); self.assertNotIn(self.owner.email.encode(), detail.content)
        self.assertEqual(self.browser.get(reverse("admin:tenancy_automatictrialeligibility_changelist")).status_code, 403)
        self.assertEqual(self.browser.get(self.correction_url).status_code, 403)
        self.assertFalse(AuditEvent.objects.filter(event_type__in=[AuditEventType.TRIAL_APPROVED, AuditEventType.TRIAL_EXTENDED]).exists())

    def test_each_view_permission_and_password_session_independent_change_only_navigation(self):
        for permission in self.permissions:
            self.inspector.user_permissions.remove(permission)
            self.assertEqual(self.post().status_code, 403)
            self.inspector.user_permissions.add(permission)
        session = self.browser.session; session[AUTHENTICATION_METHODS_SESSION_KEY] = [{"method": "password", "at": timezone.now().timestamp()}]; session.save()
        self.assertEqual(self.post().status_code, 403)
        self.request = staff_trial_request(self.inspector, self.browser)
        self.inspector.user_permissions.clear()
        self.inspector.user_permissions.add(Permission.objects.get(content_type__app_label="tenancy", codename="change_organizationtrial"))
        self.assertEqual(self.post().status_code, 403)
        self.assertEqual(self.browser.get(reverse("admin:tenancy_organizationtrial_changelist")).url, self.correction_url)
        self.assertEqual(self.browser.get(self.correction_url).status_code, 200)
        self.assertFalse(self.events().exists())

    def test_actual_csrf_strict_input_foreign_scope_private_methods_without_echo_or_audit(self):
        self.assertEqual(self.browser.post(self.url, {"trial_id": self.trial.pk}).status_code, 403)
        for changes, status in (({"extra": "private marker"}, 409), ({"reason": "private prose"}, 409),
                ({"action": "approve"}, 409), ({"trial_id": [self.trial.pk, self.trial.pk]}, 409),
                ({"trial_id": 0}, 409), ({"trial_id": 2**53}, 409), ({"organization_id": self.pending.pk}, 403)):
            response = self.post(**changes)
            self.assertEqual(response.status_code, status); self.assertNotContains(response, "private marker", status_code=status)
            self.assertIn("no-store", response["Cache-Control"]); self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        for response in (self.browser.get(self.url + "?trial_id=1"),
                self.browser.put(self.url, b"", HTTP_X_CSRFTOKEN=self.token),
                self.browser.post(self.url, json.dumps({}), content_type="application/json", HTTP_X_CSRFTOKEN=self.token),
                self.post(reason="x" * 4097)):
            self.assertEqual(response.status_code, 409)
        self.assertFalse(self.events().exists())

    def test_actual_user_ip_inspection_budget_independent_of_original_correction_budget(self):
        self.inspector.user_permissions.add(Permission.objects.get(content_type__app_label="tenancy", codename="change_organizationtrial"))
        for limit in ("1/h/user,99/h/ip", "99/h/user,1/h/ip"):
            with transaction.atomic():
                cache.clear()
                with override_settings(ACCOUNT_RATE_LIMITS={**settings.ACCOUNT_RATE_LIMITS, "staff_trial_access": limit, "platform_trial": limit}):
                    self.assertEqual(self.post().status_code, 200); self.assertEqual(self.post().status_code, 429)
                    correction = self.browser.post(self.correction_url, urlencode({"organization_id": self.pending.pk,
                        "action": "approve", "reason": "Fixture review", "confirm_action": "on", "csrfmiddlewaretoken": self.token}),
                        content_type="application/x-www-form-urlencoded")
                    self.assertEqual(correction.status_code, 200, correction.content)
                    pending_trial = OrganizationTrial.objects.get(organization=self.pending)
                    self.assertEqual(self.post(organization_id=self.pending.pk, trial_id=pending_trial.pk).status_code, 429)
                transaction.set_rollback(True)
            with transaction.atomic():
                cache.clear()
                with override_settings(ACCOUNT_RATE_LIMITS={**settings.ACCOUNT_RATE_LIMITS, "staff_trial_access": limit, "platform_trial": limit}):
                    endpoint = reverse("platform-trial-approval", args=[self.pending.pk])
                    for status in (200, 429):
                        response = self.browser.post(endpoint, json.dumps({"reason": "Fixture review"}), content_type="application/json", HTTP_X_CSRFTOKEN=self.token)
                        self.assertEqual(response.status_code, status)
                    self.assertEqual(self.post().status_code, 200); self.assertEqual(self.post().status_code, 429)
                transaction.set_rollback(True)

    def test_retained_closed_legacy_offer_is_escaped_without_current_policy_or_recovery_inference(self):
        offer = '<img src=x onerror="alert(1)">'
        OrganizationTrial.objects.filter(pk=self.trial.pk).update(offer_version=offer)
        AutomaticTrialEligibility.objects.filter(pk=self.trial.automatic_eligibility_id).update(offer_version=offer)
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=timezone.now())
        response = self.post()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertContains(response, "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;")
        self.assertNotContains(response, offer)
        self.assertEqual(self.events().count(), 1)

    def test_final_render_full_hidden_source_lifecycle_and_session_loss_rolls_back_access_audit(self):
        render = TemplateResponse.render
        original = OrganizationTrial.objects.filter(pk=self.trial.pk).values().get()
        for mutate in (lambda: OrganizationTrial.objects.filter(pk=self.trial.pk).update(ends_at=self.trial.ends_at + timedelta(microseconds=1)),
                lambda: AutomaticTrialEligibility.objects.filter(pk=self.trial.automatic_eligibility_id).update(user_id=self.inspector.pk),
                lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=timezone.now()),
                lambda: self.inspector.user_permissions.clear(), lambda: Session.objects.filter(session_key=self.browser.session.session_key).delete()):
            def changed(response):
                result = render(response)
                if response.template_name == "admin/tenancy/trial_investigation.html" and response.context_data.get("inspection"): mutate()
                return result
            with patch("django.template.response.TemplateResponse.render", changed): response = self.post()
            self.assertIn(response.status_code, (403, 409)); self.assertNotIn(b"<h2>Recorded trial", response.content)
            self.assertIn("no-store", response["Cache-Control"]); self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
            self.assertFalse(self.events().exists()); self.assertEqual(OrganizationTrial.objects.filter(pk=self.trial.pk).values().get(), original)
        with patch("tenancy.staff_trial_investigation.AuditEvent.objects.create", side_effect=RuntimeError("audit unavailable")), self.assertRaises(RuntimeError): self.post()
        self.assertFalse(self.events().exists())
