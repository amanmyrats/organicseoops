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

from accounts.models import User
from . import services, test_trial_corrections as fixtures
from .models import AuditEvent, AuditEventType, Organization, OrganizationTrial, PaddleSubscription


@override_settings(STAFF_MFA_REQUIRED=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "trial-correction-admin"}})
class TrialCorrectionAdminTests(TestCase):
    def setUp(self):
        fixtures.TrialCorrectionTests.setUp(self)
        self.inspector = User.objects.create_user("trial-admin@example.invalid", "fixture-password", is_staff=True)
        self.permission = Permission.objects.get(content_type__app_label="tenancy", codename="change_organizationtrial")
        self.inspector.user_permissions.add(self.permission)
        self.browser = Client(enforce_csrf_checks=True); self.browser.force_login(self.inspector)
        self.request = fixtures.staff_trial_request(self.inspector, self.browser)
        self.url = reverse("admin:tenancy_organizationtrial_corrections")
        self.assertEqual(self.browser.get(self.url).status_code, 200)
        self.token = self.browser.cookies["csrftoken"].value

    def post(self, organization=None, **changes):
        return self.browser.post(self.url, urlencode({"organization_id": (organization or self.pending).pk, "action": "approve",
            "reason": "Reviewed exact fixture", "confirm_action": "on", "csrfmiddlewaretoken": self.token, **changes}, doseq=True),
            content_type="application/x-www-form-urlencoded")

    def correction_audits(self):
        return AuditEvent.objects.filter(event_type__in=[AuditEventType.TRIAL_APPROVED, AuditEventType.TRIAL_EXTENDED])

    def test_change_only_confirmed_approval_extension_uses_original_policy_audits_no_network(self):
        self.assertFalse(self.inspector.has_perm("tenancy.view_organizationtrial"))
        with patch("socket.create_connection", side_effect=AssertionError("provider")), \
                patch("tenancy.paddle_jobs.dispatch_paddle_receipt", side_effect=AssertionError("dispatch")):
            approved = self.post(); extended = self.post(self.active, action="extend")
        for page in (approved, extended):
            self.assertEqual(page.status_code, 200, page.content)
            self.assertContains(page, "Recorded correction for organization")
            self.assertIn("no-store", page["Cache-Control"]); self.assertEqual(page["X-Robots-Tag"], "noindex, nofollow")
            self.assertNotContains(page, self.owner.email); self.assertNotContains(page, "Reviewed exact fixture")
        pending, active = (OrganizationTrial.objects.get(organization=org) for org in (self.pending, self.active))
        self.assertEqual(pending.ends_at - pending.started_at, timedelta(days=30))
        self.assertEqual(active.ends_at - active.started_at, timedelta(days=37))
        self.assertEqual(self.correction_audits().count(), 2)
        self.assertEqual(self.post().status_code, 409); self.assertEqual(self.post(self.active, action="extend").status_code, 409)
        self.assertEqual(self.correction_audits().count(), 2)

    def test_correction_only_navigation_has_no_generic_queryset_or_crud_view_only_cannot_correct(self):
        resource = admin.site._registry[OrganizationTrial]
        self.assertEqual(resource.get_queryset(self.request).count(), 0)
        for permission in (resource.has_add_permission, resource.has_change_permission, resource.has_delete_permission): self.assertFalse(permission(self.request))
        listing = self.browser.get(reverse("admin:tenancy_organizationtrial_changelist"))
        self.assertEqual(listing.url, self.url)
        trial = OrganizationTrial.objects.get(organization=self.active)
        detail = self.browser.get(reverse("admin:tenancy_organizationtrial_change", args=[trial.pk]))
        self.assertIn(detail.status_code, (302, 403)); self.assertNotIn(str(trial.ends_at).encode(), detail.content)
        view = Permission.objects.get(content_type__app_label="tenancy", codename="view_organizationtrial")
        self.inspector.user_permissions.remove(self.permission); self.inspector.user_permissions.add(view)
        self.assertEqual(self.post().status_code, 403)
        listing = self.browser.get(reverse("admin:tenancy_organizationtrial_changelist"))
        self.assertEqual(listing.status_code, 403)  # Trial view alone no longer grants generic diagnostic discovery.
        self.inspector.user_permissions.add(*Permission.objects.filter(content_type__app_label="tenancy",
            codename__in=["view_organization", "view_automatictrialeligibility"]))
        listing = self.browser.get(reverse("admin:tenancy_organizationtrial_changelist"))
        self.assertEqual(listing.url, reverse("admin:tenancy_organizationtrial_scoped"))
        self.assertContains(self.browser.get(listing.url), "Exact trial corrections")
        session = self.browser.session
        session[AUTHENTICATION_METHODS_SESSION_KEY] = [{"method": "password", "at": timezone.now().timestamp()}]; session.save()
        self.inspector.user_permissions.add(self.permission)
        self.assertEqual(self.post().status_code, 403)
        self.assertFalse(self.correction_audits().exists())

    def test_actual_csrf_confirmation_strict_input_methods_no_echo_or_mutation(self):
        for changes in ({"organization_id": [self.pending.pk, self.pending.pk]}, {"extra": "private marker"},
                {"confirm_action": ""}, {"confirm_action": "false"}, {"confirm_action": "no"}, {"confirm_action": "0"},
                {"action": "paid"}, {"organization_id": 0}, {"organization_id": 2**53},
                {"reason": " "}, {"reason": "x" * 251}):
            response = self.post(**changes)
            self.assertEqual(response.status_code, 409); self.assertNotIn(b"private marker", response.content)
        self.assertEqual(self.post(organization_id=999999999).status_code, 403)
        self.assertEqual(self.browser.post(self.url, {"organization_id": self.pending.pk}).status_code, 403)
        self.assertEqual(self.browser.post(self.url, json.dumps({}), content_type="application/json", HTTP_X_CSRFTOKEN=self.token).status_code, 409)
        self.assertEqual(self.browser.get(self.url + "?organization_id=1").status_code, 409)
        self.assertEqual(self.browser.put(self.url, b"", HTTP_X_CSRFTOKEN=self.token).status_code, 409)
        self.assertFalse(self.correction_audits().exists())

    def test_actual_user_ip_budget_shared_with_original_correction_api(self):
        for limit in ("1/h/user,99/h/ip", "99/h/user,1/h/ip"):
            with transaction.atomic():
                cache.clear()
                with override_settings(ACCOUNT_RATE_LIMITS={**settings.ACCOUNT_RATE_LIMITS, "platform_trial": limit}):
                    self.assertEqual(self.post().status_code, 200)
                    endpoint = reverse("platform-trial-extension", args=[self.active.pk])
                    self.assertEqual(self.browser.post(endpoint, json.dumps({"reason": "Fixture review"}), content_type="application/json", HTTP_X_CSRFTOKEN=self.token).status_code, 429)
                    self.assertEqual(self.post(self.active, action="extend").status_code, 429)
                transaction.set_rollback(True)
            with transaction.atomic():
                cache.clear()
                with override_settings(ACCOUNT_RATE_LIMITS={**settings.ACCOUNT_RATE_LIMITS, "platform_trial": limit}):
                    endpoint = reverse("platform-trial-approval", args=[self.pending.pk])
                    self.assertEqual(self.browser.post(endpoint, json.dumps({"reason": "Fixture review"}), content_type="application/json", HTTP_X_CSRFTOKEN=self.token).status_code, 200)
                    self.assertEqual(self.post(self.active, action="extend").status_code, 429)
                transaction.set_rollback(True)

    def test_original_paid_suspended_closed_policy_and_missing_trial_denials(self):
        for organization, changes in ((self.pending, {"is_suspended": True}),
                (self.active, {"is_suspended": True, "closed_at": timezone.now()})):
            with transaction.atomic():
                Organization.objects.filter(pk=organization.pk).update(**changes)
                self.assertEqual(self.post(organization, action="approve" if organization == self.pending else "extend").status_code, 409)
                transaction.set_rollback(True)
        with transaction.atomic():
            PaddleSubscription.objects.create(organization=self.pending, environment="sandbox", status="canceled",
                customer_id="ctm_" + "a" * 26, subscription_id="sub_" + "b" * 26)
            self.assertEqual(self.post().status_code, 409); transaction.set_rollback(True)
        OrganizationTrial.objects.filter(organization=self.pending).update(unit_limit=41)
        self.assertEqual(self.post().status_code, 409)
        OrganizationTrial.objects.filter(organization=self.pending).delete()
        self.assertEqual(self.post().status_code, 403)
        self.assertFalse(self.correction_audits().exists())

    def test_post_render_original_source_session_actor_paid_loss_and_audit_failure_roll_back(self):
        render = TemplateResponse.render
        for organization, action in ((self.pending, "approve"), (self.active, "extend")):
            original = OrganizationTrial.objects.filter(organization=organization).values().get()
            for mutate in (lambda: OrganizationTrial.objects.filter(organization=organization).update(unit_limit=41),
                    lambda: OrganizationTrial.objects.filter(organization=organization).update(ends_at=timezone.now()),
                    lambda: Organization.objects.filter(pk=organization.pk).update(is_suspended=True),
                    lambda: PaddleSubscription.objects.create(organization=organization, environment="sandbox", status="canceled",
                        customer_id="ctm_" + "a" * 26, subscription_id="sub_" + "b" * 26),
                    lambda: Session.objects.filter(session_key=self.browser.session.session_key).delete(), lambda: self.inspector.user_permissions.clear()):
                cache.clear()
                def changed(response):
                    result = render(response)
                    if response.template_name == "admin/tenancy/trial_correction.html" and response.context_data.get("corrected"): mutate()
                    return result
                with patch("django.template.response.TemplateResponse.render", changed): response = self.post(organization, action=action)
                self.assertIn(response.status_code, (403, 409)); self.assertNotIn(b"Recorded correction for organization", response.content)
                self.assertEqual(OrganizationTrial.objects.filter(organization=organization).values().get(), original)
                self.assertFalse(self.correction_audits().exists())
            with patch.object(services, "_audit", side_effect=RuntimeError("audit unavailable")), self.assertRaises(RuntimeError): self.post(organization, action=action)
            self.assertEqual(OrganizationTrial.objects.filter(organization=organization).values().get(), original)
            self.assertFalse(self.correction_audits().exists())
