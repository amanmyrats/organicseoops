import json
from types import SimpleNamespace
from unittest.mock import patch

from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.models import EmailAddress
from allauth.core.context import request_context
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, RequestFactory, TestCase, override_settings
from django.utils.translation import get_language, override

from tenancy.email_feedback import record_ses_feedback

from .auth import AccountAdapter
from .models import AccountEmailDelivery, EmailDeliveryState


class AccountEmailDeliveryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("mail-account@example.invalid", "Safe password 99!")
        EmailAddress.objects.create(user=self.user, email=self.user.email, verified=True, primary=True)

    def test_known_account_mail_records_transport_return_without_token_payload(self):
        with patch.object(DefaultAccountAdapter, "send_mail", return_value=None) as sender:
            AccountAdapter().send_mail("account/email/password_reset_key", self.user.email,
                                       {"key": "fixture-secret-fragment"})
        sender.assert_called_once()
        record = AccountEmailDelivery.objects.get()
        self.assertEqual(record.state, EmailDeliveryState.RETURNED)
        self.assertEqual(record.purpose, "password_reset_key")
        self.assertIsNotNone(record.finished_at)
        self.assertNotIn("fixture-secret-fragment", json.dumps(list(AccountEmailDelivery.objects.values()), default=str))

    def test_uncertain_and_suppressed_mail_need_user_initiated_recovery(self):
        with patch.object(DefaultAccountAdapter, "send_mail", side_effect=OSError("fixture mail uncertain")):
            with self.assertRaises(OSError):
                AccountAdapter().send_mail("account/email/email_confirmation", self.user.email,
                                           {"key": "fixture-secret"})
        self.assertEqual(AccountEmailDelivery.objects.get().state, EmailDeliveryState.UNKNOWN)
        record_ses_feedback(("sns-account-mail-0001", "permanent_bounce", (self.user.email,)))
        with patch.object(DefaultAccountAdapter, "send_mail") as sender:
            AccountAdapter().send_mail("account/email/password_reset_key", self.user.email, {})
        sender.assert_not_called()
        self.assertEqual(AccountEmailDelivery.objects.order_by("-pk").first().state, EmailDeliveryState.SUPPRESSED)

    def test_unknown_address_is_not_persisted_or_exposed_by_diagnostics(self):
        with patch.object(DefaultAccountAdapter, "send_mail") as sender:
            AccountAdapter().send_mail("account/email/unknown_account", "unknown@example.invalid", {})
        sender.assert_called_once()
        self.assertFalse(AccountEmailDelivery.objects.exists())

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_account_email_locale_uses_recipient_drafts_and_production_english_fallback(self):
        self.user.product_language = "tr"
        self.user.save(update_fields=["product_language"])
        context = {"current_site": SimpleNamespace(name="OrganicSEOOps", domain="mail.example.invalid"),
                   "user": get_user_model()(email="actor@example.invalid", product_language="en"),
                   "password_reset_url": "https://app.example.invalid/account/reset-password#fixture-token",
                   "activate_url": "https://app.example.invalid/account/verify-email#fixture-token"}
        for template, turkish_subject, english_subject, turkish_body in (
            ("password_reset_key", "Şifre Sıfırlama", "Password Reset", "şifre sıfırlama"),
            ("email_confirmation", "E-posta Adresinizi Onaylayın", "Confirm Your Email", "bir hesap oluşturmak"),
            ("password_changed", "Şifre Değiştirildi", "Password Changed", "Şifreniz değiştirildi"),
        ):
            with self.subTest(template=template), override("de"), request_context(RequestFactory().get("/")):
                with override_settings(DEBUG=True):
                    AccountAdapter().send_mail(f"account/email/{template}", self.user.email, context)
                self.assertEqual(get_language(), "de")
                self.assertIn(turkish_subject, mail.outbox[-1].subject)
                self.assertIn("Türkçe taslak", mail.outbox[-1].subject)
                self.assertIn(turkish_body, mail.outbox[-1].body)
                self.assertEqual(mail.outbox[-1].to, [self.user.email])
                if template != "password_changed":
                    self.assertIn("#fixture-token", mail.outbox[-1].body)
                with override_settings(DEBUG=False):
                    AccountAdapter().send_mail(f"account/email/{template}", self.user.email, context)
                self.assertEqual(get_language(), "de")
                self.assertIn(english_subject, mail.outbox[-1].subject)
                self.assertNotIn("taslak", mail.outbox[-1].subject)
        with override_settings(DEBUG=True), override("tr"), request_context(RequestFactory().get("/")):
            AccountAdapter().send_mail("account/email/password_reset_key", "unknown@example.invalid", context)
            self.assertIn("Password Reset", mail.outbox[-1].subject)
            self.assertEqual(get_language(), "tr")
            context["user"].product_language = "tr"
            for preference, active in (("en", True), ("tr", False)):
                self.user.product_language, self.user.is_active = preference, active
                self.user.save(update_fields=["product_language", "is_active"])
                AccountAdapter().send_mail("account/email/password_reset_key", self.user.email, context)
                self.assertIn("Password Reset", mail.outbox[-1].subject)
                self.assertNotIn("taslak", mail.outbox[-1].subject)
        self.assertFalse(AccountEmailDelivery.objects.exclude(address__user=self.user).exists())
        self.assertNotIn("fixture-token", json.dumps(list(AccountEmailDelivery.objects.values()), default=str))

    @override_settings(STAFF_MFA_REQUIRED=False)
    def test_staff_only_bounded_delivery_status_contains_no_message_or_address(self):
        with patch.object(DefaultAccountAdapter, "send_mail", return_value=None):
            AccountAdapter().send_mail("account/email/email_confirmation", self.user.email,
                                       {"key": "private-fixture-fragment"})
        customer = Client()
        customer.force_login(self.user)
        self.assertEqual(customer.get("/api/platform/email/deliveries/").status_code, 403)
        staff = get_user_model().objects.create_superuser("mail-operator@example.invalid", "Safe password 99!")
        operator = Client()
        operator.force_login(staff)
        with override_settings(STAFF_MFA_REQUIRED=True):
            self.assertEqual(operator.get("/api/platform/email/deliveries/").status_code, 403)
        response = operator.get("/api/platform/email/deliveries/")
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertNotIn("deliveries", response.json())
        self.assertNotIn(self.user.email, response.content.decode())
        self.assertNotIn("private-fixture-fragment", response.content.decode())
