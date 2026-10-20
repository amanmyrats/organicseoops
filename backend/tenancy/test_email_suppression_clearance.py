import json
from datetime import timedelta
from unittest.mock import patch

from allauth.account.internal.flows.login import AUTHENTICATION_METHODS_SESSION_KEY
from allauth.account.models import EmailAddress
from allauth.mfa.models import Authenticator
from django.contrib.auth import HASH_SESSION_KEY
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.test import Client, RequestFactory, TestCase, override_settings
from django.utils import timezone

from .email_feedback import clear_email_suppression, is_email_suppressed, record_ses_feedback
from .models import AuditEvent, AuditEventType, EmailSuppression


@override_settings(STAFF_MFA_REQUIRED=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "suppression-clearance"}})
class SuppressionClearanceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user("clearance-target@example.invalid", "fixture-password")
        self.address = EmailAddress.objects.create(user=self.user, email=self.user.email, primary=True, verified=True)
        record_ses_feedback(("sns-clearance-00000001", "complaint", (self.user.email,)))
        self.row = EmailSuppression.objects.get()
        self.staff = get_user_model().objects.create_superuser("clearance-staff@example.invalid", "fixture-password")
        self.browser = Client(enforce_csrf_checks=True); self.browser.force_login(self.staff)
        self.browser.get("/_allauth/browser/v1/auth/session")
        self.url = f"/api/platform/email/suppressions/{self.row.pk}/clear/"
        self.payload = {"reason": "Fixture deliberate reviewed clearance", "confirm_review": True}

    def post(self):
        return self.browser.post(self.url, json.dumps(self.payload), content_type="application/json",
            HTTP_X_CSRFTOKEN=self.browser.cookies["csrftoken"].value, HTTP_REFERER="http://testserver/")

    def test_api_requires_persisted_mfa_even_when_development_middleware_is_optional(self):
        self.assertEqual(self.post().status_code, 403)
        self.assertTrue(EmailSuppression.objects.filter(pk=self.row.pk).exists())
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.EMAIL_SUPPRESSION_CLEARED).exists())

    def assure(self):
        # Delete permission is independent of diagnostic/view permissions.
        get_user_model().objects.filter(pk=self.staff.pk).update(is_superuser=False)
        self.staff.refresh_from_db()
        self.permission = Permission.objects.get(content_type__app_label="tenancy", codename="delete_emailsuppression")
        self.staff.user_permissions.add(self.permission)
        Authenticator.objects.create(user=self.staff, type=Authenticator.Type.TOTP, data={"secret": "unused-fixture"})
        session = self.browser.session
        session[AUTHENTICATION_METHODS_SESSION_KEY] = [{"method": "mfa", "at": timezone.now().timestamp()}]; session.save()
        self.request = RequestFactory().post(self.url); self.request.user, self.request.session = self.staff, self.browser.session

    def clear(self, **changes):
        return clear_email_suppression(**{**dict(suppression=self.row, actor=self.staff, request=self.request,
            reason=self.payload["reason"]), **changes})

    def assert_retained(self):
        self.assertTrue(EmailSuppression.objects.filter(pk=self.row.pk).exists())
        self.assertTrue(is_email_suppressed(self.user.email))
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.EMAIL_SUPPRESSION_CLEARED).exists())

    def test_genuine_delete_only_mfa_positive_is_audited_and_sends_nothing(self):
        self.assure()
        with override_settings(STAFF_MFA_REQUIRED=True), patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("django.core.mail.send_mail", side_effect=AssertionError("SMTP")):
            response = self.post()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("no-store", response["Cache-Control"]); self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertFalse(EmailSuppression.objects.filter(pk=self.row.pk).exists()); self.assertFalse(is_email_suppressed(self.user.email))
        event = AuditEvent.objects.get(event_type=AuditEventType.EMAIL_SUPPRESSION_CLEARED)
        self.assertEqual((event.actor_id, event.subject_user_id, event.organization_id, event.project_id), (self.staff.pk, self.user.pk, None, None))
        self.assertEqual(event.details, {"suppression_id": self.row.pk, "email_address_id": self.address.pk, "reason": self.payload["reason"]})

    def test_direct_root_requires_exact_actor_live_permission_session_hash_and_original_suppression(self):
        self.assure()
        with self.assertRaises(PermissionDenied): self.clear(actor=self.user)
        self.staff.user_permissions.remove(self.permission)
        with self.assertRaises(PermissionDenied): self.clear()
        self.staff.user_permissions.add(self.permission)
        for mutate in (lambda: EmailSuppression.objects.filter(pk=self.row.pk).update(created_at=self.row.created_at - timedelta(microseconds=1)),
                lambda: EmailSuppression.objects.filter(pk=self.row.pk).update(reason="permanent_bounce")):
            with transaction.atomic():
                mutate()
                with self.assertRaises(ValidationError): self.clear()
                transaction.set_rollback(True)
        session = self.browser.session; session[HASH_SESSION_KEY] = "invalidated"; session.save()
        with self.assertRaises(PermissionDenied): self.clear()
        self.assert_retained()

    def test_old_digest_is_not_current_address_clearance_even_after_valid_verified_identity_change(self):
        self.assure()
        changed_email = "new-clearance-target@example.invalid"
        get_user_model().objects.filter(pk=self.user.pk).update(email=changed_email)
        EmailAddress.objects.filter(pk=self.address.pk).update(email=changed_email)
        self.assertFalse(is_email_suppressed(changed_email))
        self.assertEqual(self.post().status_code, 409)
        self.assertTrue(EmailSuppression.objects.filter(pk=self.row.pk).exists())
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.EMAIL_SUPPRESSION_CLEARED).exists())

    def test_post_audit_source_target_permission_session_loss_rolls_back_clearance_and_audit(self):
        self.assure()
        create = AuditEvent.objects.create
        for mutate, error in ((lambda: self.staff.user_permissions.remove(self.permission), PermissionDenied),
                (lambda: Session.objects.filter(session_key=self.browser.session.session_key).delete(), PermissionDenied),
                (lambda: get_user_model().objects.filter(pk=self.staff.pk).update(session_version="invalidated"), PermissionDenied),
                (lambda: get_user_model().objects.filter(pk=self.user.pk).update(is_active=False), ValidationError),
                (lambda: EmailAddress.objects.filter(pk=self.address.pk).update(primary=False), ValidationError),
                (lambda: EmailAddress.objects.filter(pk=self.address.pk).update(verified=False), ValidationError),
                (lambda: EmailSuppression.objects.filter(pk=self.row.pk).update(reason="permanent_bounce"), ValidationError)):
            self.request.session = self.browser.session
            def changed(**kwargs):
                result = create(**kwargs); mutate(); return result
            with patch("tenancy.email_feedback.AuditEvent.objects.create", side_effect=changed), self.assertRaises(error): self.clear()
            self.assert_retained()
        self.request.session = self.browser.session
        with patch("tenancy.email_feedback.AuditEvent.objects.create", side_effect=RuntimeError("audit unavailable")), self.assertRaises(RuntimeError): self.clear()
        self.assert_retained()

    def test_api_post_audit_and_post_delete_authority_loss_leaves_no_clearance(self):
        self.assure()
        create = AuditEvent.objects.create
        def changed(**kwargs):
            result = create(**kwargs); self.staff.user_permissions.clear(); return result
        with patch("tenancy.email_feedback.AuditEvent.objects.create", side_effect=changed):
            self.assertEqual(self.post().status_code, 403)
        self.assert_retained()
        delete = EmailSuppression.delete
        def changed_delete(row, *args, **kwargs):
            result = delete(row, *args, **kwargs); self.staff.user_permissions.clear(); return result
        with patch.object(EmailSuppression, "delete", changed_delete): self.assertEqual(self.post().status_code, 403)
        self.assert_retained()
