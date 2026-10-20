import json
from unittest.mock import patch

from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.models import EmailAddress
from allauth.account.internal.flows.login import AUTHENTICATION_METHODS_SESSION_KEY
from allauth.mfa.models import Authenticator
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.auth import AccountAdapter

from .email_feedback import is_email_suppressed, record_ses_feedback
from .models import AuditEvent, AuditEventType, EmailFeedbackReceipt, EmailSuppression
from .ses_feedback import parse_ses_feedback
from .ses_feedback_transport import poll_ses_feedback
from .test_ses_feedback import NOW, SENDER, TOPIC, feedback


class EmailFeedbackTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("feedback-owner@example.invalid", "Safe password 99!")
        self.address = EmailAddress.objects.create(user=self.user, email=self.user.email, verified=True, primary=True)

    def test_provider_event_deduplicates_and_suppresses_only_the_current_verified_address(self):
        event = ("sns-event-00000001", "permanent_bounce", (self.user.email,))
        self.assertTrue(record_ses_feedback(event))
        self.assertTrue(record_ses_feedback(event))
        self.assertEqual(EmailFeedbackReceipt.objects.count(), 1)
        self.assertEqual(EmailSuppression.objects.count(), 1)
        self.assertTrue(is_email_suppressed(self.user.email))
        with patch.object(DefaultAccountAdapter, "send_mail") as sender:
            AccountAdapter().send_mail("account/email/test", self.user.email, {})
        sender.assert_not_called()

        self.address.primary = False
        self.address.save(update_fields=["primary"])
        self.user.email = "new-owner@example.invalid"
        self.user.save(update_fields=["email"])
        EmailAddress.objects.create(user=self.user, email=self.user.email, verified=True, primary=True)
        self.assertFalse(is_email_suppressed(self.user.email))
        with patch.object(DefaultAccountAdapter, "send_mail") as sender:
            AccountAdapter().send_mail("account/email/test", self.user.email, {})
        sender.assert_called_once()

    def test_foreign_or_unverified_address_does_not_suppress_current_owner(self):
        self.assertTrue(record_ses_feedback(("sns-event-00000002", "complaint", ("other@example.invalid",))))
        self.assertFalse(is_email_suppressed(self.user.email))
        self.address.verified = False
        self.address.save(update_fields=["verified"])
        self.assertTrue(record_ses_feedback(("sns-event-00000003", "permanent_bounce", (self.user.email,))))
        self.assertEqual(EmailSuppression.objects.count(), 1)
        self.assertFalse(is_email_suppressed(self.user.email))
        self.address.verified = True
        self.address.save(update_fields=["verified"])
        self.assertTrue(is_email_suppressed(self.user.email))

    @override_settings(SES_FEEDBACK_QUEUE_URL="https://sqs.eu-west-1.amazonaws.com/123456789012/organicseoops-mail-feedback",
                       SES_FEEDBACK_TOPIC_ARN=TOPIC, SES_FEEDBACK_REGION="eu-west-1", DEFAULT_FROM_EMAIL=SENDER)
    def test_queue_delete_after_commit_and_duplicate_receive_do_not_double_suppress(self):
        body = json.dumps(feedback(recipients=[{"emailAddress": self.user.email}],
                                   destinations=[self.user.email]))

        class FakeQueue:
            deleted = []
            fail_delete = True

            def receive_message(self, **_):
                return {"Messages": [{"Body": body, "ReceiptHandle": "fixture-receipt"}]}

            def delete_message(self, **kwargs):
                if self.fail_delete:
                    raise OSError("fixture delete lost")
                self.deleted.append(kwargs["ReceiptHandle"])

        queue = FakeQueue()
        with patch("tenancy.ses_feedback_transport.parse_ses_feedback",
                   side_effect=lambda raw, **kwargs: parse_ses_feedback(raw, now=NOW, **kwargs)):
            with self.assertRaises(OSError):
                poll_ses_feedback(handle=record_ses_feedback, client=queue)
            self.assertEqual(EmailFeedbackReceipt.objects.count(), 1)
            self.assertTrue(is_email_suppressed(self.user.email))
            queue.fail_delete = False
            self.assertEqual(poll_ses_feedback(handle=record_ses_feedback, client=queue), 1)
        self.assertEqual(queue.deleted, ["fixture-receipt"])
        self.assertEqual(EmailFeedbackReceipt.objects.count(), 1)
        self.assertEqual(EmailSuppression.objects.count(), 1)

    @override_settings(STAFF_MFA_REQUIRED=False,
                       CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
    def test_staff_review_clear_is_csrf_mfa_reason_bound_and_audited(self):
        cache.clear()
        record_ses_feedback(("sns-event-00000004", "complaint", (self.user.email,)))
        suppression = EmailSuppression.objects.get()
        staff = get_user_model().objects.create_superuser("mail-staff@example.invalid", "Safe password 99!")
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(staff)
        browser.get("/_allauth/browser/v1/auth/session")
        path = f"/api/platform/email/suppressions/{suppression.pk}/clear/"
        payload = {"reason": "Address recovered after a verified review", "confirm_review": True}
        self.assertEqual(browser.post(path, data=json.dumps(payload), content_type="application/json").status_code, 403)
        headers = {"HTTP_X_CSRFTOKEN": browser.cookies["csrftoken"].value,
                   "HTTP_REFERER": "http://testserver/"}
        with override_settings(STAFF_MFA_REQUIRED=True):
            self.assertEqual(browser.post(path, data=json.dumps(payload), content_type="application/json",
                                          **headers).status_code, 403)
        Authenticator.objects.create(user=staff, type=Authenticator.Type.TOTP, data={"secret": "unused-fixture"})
        session = browser.session
        session[AUTHENTICATION_METHODS_SESSION_KEY] = [{"method": "mfa", "at": timezone.now().timestamp()}]; session.save()
        self.assertEqual(browser.get("/api/platform/email/suppressions/").status_code, 410)
        self.assertEqual(browser.post(path, data=json.dumps({**payload, "confirm_review": False}),
                                      content_type="application/json", **headers).status_code, 409)
        self.assertEqual(browser.post(path, data=json.dumps(payload), content_type="application/json",
                                      **headers).status_code, 200)
        self.assertFalse(is_email_suppressed(self.user.email))
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.EMAIL_SUPPRESSION_CLEARED,
                                                   subject_user=self.user).count(), 1)
        self.assertEqual(browser.post(path, data=json.dumps(payload), content_type="application/json",
                                      **headers).status_code, 404)

        customer = Client(enforce_csrf_checks=True)
        customer.force_login(self.user)
        self.assertEqual(customer.get("/api/platform/email/suppressions/").status_code, 403)

    @override_settings(STAFF_MFA_REQUIRED=False,
                       CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
    def test_staff_cannot_clear_suppression_for_stale_address(self):
        cache.clear()
        self.address.verified = False
        self.address.save(update_fields=["verified"])
        record_ses_feedback(("sns-event-00000005", "permanent_bounce", (self.user.email,)))
        row = EmailSuppression.objects.get()
        staff = get_user_model().objects.create_superuser("old-mail-staff@example.invalid", "Safe password 99!")
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(staff)
        browser.get("/_allauth/browser/v1/auth/session")
        Authenticator.objects.create(user=staff, type=Authenticator.Type.TOTP, data={"secret": "unused-fixture"})
        session = browser.session
        session[AUTHENTICATION_METHODS_SESSION_KEY] = [{"method": "mfa", "at": timezone.now().timestamp()}]; session.save()
        response = browser.post(f"/api/platform/email/suppressions/{row.pk}/clear/",
                                data=json.dumps({"reason": "check", "confirm_review": True}),
                                content_type="application/json",
                                HTTP_X_CSRFTOKEN=browser.cookies["csrftoken"].value,
                                HTTP_REFERER="http://testserver/")
        self.assertEqual(response.status_code, 409)
        self.assertTrue(EmailSuppression.objects.filter(pk=row.pk).exists())
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.EMAIL_SUPPRESSION_CLEARED).exists())
