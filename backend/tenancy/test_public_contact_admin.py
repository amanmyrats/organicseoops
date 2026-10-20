from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlencode

from allauth.account.internal.flows.login import AUTHENTICATION_METHODS_SESSION_KEY
from allauth.mfa.models import Authenticator
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.db import transaction
from django.test import Client, RequestFactory, TestCase, override_settings
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from .models import AuditEvent, AuditEventType, PublicContactRequest
from .public_contact_store import create_contact_request
from . import test_public_contact as fixtures


@override_settings(DEBUG=True, STORAGES=TEST_STORAGES, STAFF_MFA_REQUIRED=True,
    PUBLIC_CONTACT_RETENTION_DAYS=2, PUBLIC_CONTACT_ENABLED=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class PublicContactAdminTests(TestCase):
    def setUp(self):
        cache.clear()
        self.question = "<img src=x onerror=alert(1)> Synthetic enquiry"
        create_contact_request(browser_key="a" * 43,
            command=fixtures.PublicContactCommandTests.command(self, question=self.question))
        self.identity = PublicContactRequest.objects.get().pk
        self.staff = get_user_model().objects.create_user("contact-staff@example.invalid", password="fixture-password", is_staff=True)
        self.permission = Permission.objects.get(codename="view_publiccontactrequest", content_type__app_label="tenancy")
        self.staff.user_permissions.add(self.permission)
        self.client = Client(enforce_csrf_checks=True); self.client.force_login(self.staff)
        Authenticator.objects.create(user=self.staff, type=Authenticator.Type.TOTP, data={"secret": "unused-fixture"})
        session = self.client.session
        session[AUTHENTICATION_METHODS_SESSION_KEY] = [{"method": "mfa", "at": timezone.now().timestamp()}]; session.save()
        self.url = reverse("admin:tenancy_publiccontactrequest_scoped")
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.data = {"action": "inspect", "request_id": self.identity, "reason": "customer_request",
                     "csrfmiddlewaretoken": self.client.cookies["csrftoken"].value}

    def post(self, **changes):
        return self.client.post(self.url, urlencode({**self.data, **changes}), content_type="application/x-www-form-urlencoded")

    def test_explicit_minimized_identifier_discovery_exact_escaped_inspection_and_global_payload_free_audit(self):
        row = PublicContactRequest.objects.get()
        PublicContactRequest.objects.bulk_create([PublicContactRequest(browser_key_hash="f" * 64,
            **fixtures.PublicContactCommandTests.command(self, request_key=f"contact-listed-{index}"),
            created_at=row.created_at, expires_at=row.expires_at) for index in range(21)])
        with override_settings(PUBLIC_CONTACT_RETENTION_DAYS=None), patch("django.core.mail.send_mail", side_effect=AssertionError("mail")):
            identifiers = self.post(action="list", request_id="")
            self.assertEqual(identifiers.status_code, 200, identifiers.content)
            self.assertEqual(len(identifiers.context["identifiers"]["rows"]), 20)
            self.assertTrue(identifiers.context["identifiers"]["has_more"])
            self.assertNotIn(self.question.encode(), identifiers.content)
            self.assertNotIn(row.reply_email.encode(), identifiers.content)
            earlier = self.post(action="list", request_id=identifiers.context["identifiers"]["next_before_id"])
            self.assertEqual(earlier.status_code, 200, earlier.content)
            self.assertEqual(len(earlier.context["identifiers"]["rows"]), 2)
            self.assertFalse(earlier.context["identifiers"]["has_more"])
            self.assertIsNone(earlier.context["identifiers"]["next_before_id"])
            self.assertNotIn(row.reply_email.encode(), earlier.content)
            self.assertIn(self.identity, [item["id"] for item in earlier.context["identifiers"]["rows"]])
            result = self.post()
        self.assertEqual(result.status_code, 200, result.content)
        self.assertContains(result, "&lt;img src=x onerror=alert(1)&gt;")
        self.assertNotContains(result, self.question)
        self.assertContains(result, "Unverified reply email")
        events = list(AuditEvent.objects.filter(event_type=AuditEventType.SUPPORT_REQUEST_ACCESSED).order_by("pk"))
        self.assertEqual(len(events), 3)
        self.assertEqual(events[0].details, {"scope": "public_contact", "action": "list", "reason": "customer_request", "count": 20, "before_id": None})
        self.assertEqual(events[2].details, {"scope": "public_contact", "action": "inspect", "reason": "customer_request", "request_id": self.identity})
        for event in events:
            self.assertEqual(event.actor_id, self.staff.pk)
            self.assertIsNone(event.organization_id); self.assertIsNone(event.project_id); self.assertIsNone(event.subject_user_id)
            self.assertNotIn(row.reply_email, str(event.details)); self.assertNotIn(self.question, str(event.details))
        request = RequestFactory().get(self.url); request.user, request.session = self.staff, self.client.session
        resource = admin.site._registry[PublicContactRequest]
        self.assertEqual(resource.get_queryset(request).count(), 0)
        self.assertFalse(resource.has_add_permission(request)); self.assertFalse(resource.has_change_permission(request)); self.assertFalse(resource.has_delete_permission(request))
        self.assertEqual(self.client.get(reverse("admin:tenancy_publiccontactrequest_changelist")).status_code, 302)
        direct = self.client.get(reverse("admin:tenancy_publiccontactrequest_change", args=[self.identity]))
        self.assertEqual(direct.status_code, 302)
        self.assertEqual(direct["Location"], reverse("admin:index"))
        self.assertNotIn(b"Synthetic enquiry", direct.content)
        self.assertEqual(result["Cache-Control"], "private, no-store"); self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")

    def test_csrf_exact_scope_live_permission_mfa_and_post_render_loss_never_deliver_body(self):
        no_csrf = self.client.post(self.url, urlencode({key: value for key, value in self.data.items() if key != "csrfmiddlewaretoken"}),
                                  content_type="application/x-www-form-urlencoded")
        self.assertEqual(no_csrf.status_code, 403); self.assertIn("no-store", no_csrf["Cache-Control"])
        for changes in ({"request_id": self.identity + 9999}, {"request_id": ""},
                        {"reason": "unknown"}, {"extra": "private"}):
            self.assertIn(self.post(**changes).status_code, (403, 409))
        self.assertFalse(AuditEvent.objects.exists())
        original_render = TemplateResponse.render
        mutations = [lambda: self.staff.user_permissions.clear(),
                     lambda: PublicContactRequest.objects.filter(pk=self.identity).update(question="Changed question"),
                     lambda: PublicContactRequest.objects.filter(pk=self.identity).update(created_at=timezone.now() - timedelta(days=3), expires_at=timezone.now() - timedelta(seconds=1))]
        for mutation in mutations:
            with transaction.atomic():
                def change(response):
                    result = original_render(response)
                    if response.template_name == "admin/tenancy/public_contact.html" and response.context_data.get("contact"):
                        mutation()
                    return result
                with patch("django.template.response.TemplateResponse.render", change): result = self.post()
                self.assertIn(result.status_code, (403, 409)); self.assertNotIn(b"Synthetic enquiry", result.content)
                transaction.set_rollback(True)
        for mutation in (lambda: self.staff.user_permissions.clear(), lambda: Authenticator.objects.filter(user=self.staff).delete()):
            with transaction.atomic():
                mutation(); result = self.post()
                self.assertIn(result.status_code, (302, 403)); self.assertNotIn(b"Synthetic enquiry", result.content)
                transaction.set_rollback(True)

    def test_actual_staff_budget_and_invalid_budget_fail_closed_without_inspection_audit(self):
        rates = {**settings.ACCOUNT_RATE_LIMITS, "public_contact_staff": "1/h/user,99/h/ip"}
        with override_settings(ACCOUNT_RATE_LIMITS=rates):
            self.assertEqual(self.post().status_code, 200)
            result = self.post(); self.assertEqual(result.status_code, 429)
            self.assertNotIn(b"Synthetic enquiry", result.content)
        self.assertEqual(AuditEvent.objects.count(), 1)
        for rate in (None, " ", "1/h/user", "0/h/ip", "1/nanh/ip"):
            with override_settings(ACCOUNT_RATE_LIMITS={"public_contact_staff": rate}):
                self.assertEqual(self.post().status_code, 503)
        with patch("allauth.core.internal.ratelimit.consume", side_effect=RuntimeError("budget")):
            self.assertEqual(self.post().status_code, 503)
        self.assertEqual(AuditEvent.objects.count(), 1)
