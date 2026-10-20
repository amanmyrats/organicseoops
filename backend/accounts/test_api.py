import json
import re
import secrets
from datetime import timedelta
from unittest.mock import patch

from allauth.account.models import EmailAddress, EmailConfirmation
from allauth.account.internal.flows.login import AUTHENTICATION_METHODS_SESSION_KEY
from allauth.mfa.models import Authenticator
from allauth.mfa.totp.internal.auth import format_hotp_value, hotp_value, yield_hotp_counters_from_time
from allauth.usersessions.models import UserSession
from django.contrib.auth import SESSION_KEY, get_user_model
from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from tenancy.models import AuditEvent, AuditEventType

User = get_user_model()


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "auth-tests"}},
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    SECURE_SSL_REDIRECT=False,
)
class AccountApiTests(TestCase):
    signup_url = "/_allauth/browser/v1/auth/signup"
    login_url = "/_allauth/browser/v1/auth/login"
    session_url = "/_allauth/browser/v1/auth/session"
    verify_url = "/_allauth/browser/v1/auth/email/verify"
    password_request_url = "/_allauth/browser/v1/auth/password/request"
    password_reset_url = "/_allauth/browser/v1/auth/password/reset"
    password_change_url = "/api/account/change-password/"
    reauthenticate_url = "/_allauth/browser/v1/auth/reauthenticate"
    email_url = "/_allauth/browser/v1/account/email"
    sessions_url = "/_allauth/browser/v1/auth/sessions"
    authenticators_url = "/_allauth/browser/v1/account/authenticators"
    totp_url = "/_allauth/browser/v1/account/authenticators/totp"
    recovery_codes_url = "/_allauth/browser/v1/account/authenticators/recovery-codes"
    mfa_authenticate_url = "/_allauth/browser/v1/auth/2fa/authenticate"
    logout_all_url = "/api/account/logout-all/"
    product_language_url = "/api/account/product-language/"

    def setUp(self):
        cache.clear()
        self.client = Client(enforce_csrf_checks=True)
        self.password = f"A-{secrets.token_urlsafe(24)}"

    def csrf(self, client=None):
        client = client or self.client
        response = client.get(self.session_url, secure=True)
        self.assertEqual(response.status_code, 401)
        return client.cookies["csrftoken"].value

    def request(self, method, path, payload=None, *, client=None, csrf=True, origin=None):
        client = client or self.client
        headers = {}
        if csrf:
            headers["HTTP_X_CSRFTOKEN"] = client.cookies["csrftoken"].value
            headers["HTTP_REFERER"] = "https://testserver/"
        if origin:
            headers["HTTP_ORIGIN"] = origin
        kwargs = {"secure": True, **headers}
        if payload is not None:
            kwargs.update(data=json.dumps(payload), content_type="application/json")
        return getattr(client, method)(path, **kwargs)

    def signup(self, email="new@example.com"):
        self.csrf()
        response = self.request("post", self.signup_url, {"email": email, "password": self.password})
        self.assertEqual(response.status_code, 401, response.content)
        return User.objects.get(email=email), self.verification_key(), response

    def verification_key(self):
        self.assertTrue(mail.outbox)
        match = re.search(r"/account/verify-email#([^\s]+)", mail.outbox[-1].body)
        self.assertIsNotNone(match, mail.outbox[-1].body)
        return match.group(1)

    def create_verified_user(self, email="person@example.com"):
        user = User.objects.create_user(email=email, password=self.password)
        EmailAddress.objects.create(user=user, email=email, primary=True, verified=True)
        return user

    def login(self, client, user, password=None):
        self.csrf(client)
        response = self.request(
            "post",
            self.login_url,
            {"email": user.email, "password": password or self.password},
            client=client,
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response

    def assert_account_audit(self, user, event_type):
        event = AuditEvent.objects.get(event_type=event_type, subject_user=user)
        self.assertEqual(event.actor_id, user.pk)
        self.assertEqual(event.details, {})
        self.assertEqual((event.organization_id, event.project_id, event.invitation_id), (None, None, None))
        self.assertRegex(event.request_id, r"^[a-f0-9]{32}$")

    def test_product_language_is_private_per_user_and_does_not_claim_turkish_copy(self):
        self.assertEqual(self.client.get(self.product_language_url, secure=True).status_code, 401)
        person = self.create_verified_user()
        other = self.create_verified_user("other-language@example.com")
        self.login(self.client, person)
        self.assertEqual(self.client.get(self.product_language_url, secure=True).json()["language"], "en")
        self.assertEqual(self.request("post", self.product_language_url, {"language": "tr"}, csrf=False).status_code, 403)
        for data in ({"language": "ru"}, {"language": "tr", "project_language": "tr"}, {"language": None}):
            self.assertEqual(self.request("post", self.product_language_url, data).status_code, 400)
        result = self.request("post", self.product_language_url, {"language": "tr"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {"language": "tr", "current_ui_language": "en", "current_email_language": "en"})
        self.assertEqual(result["Cache-Control"], "private, no-store")
        person.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual((person.product_language, other.product_language), ("tr", "en"))
        with override_settings(DEBUG=True):
            draft = self.client.get(self.product_language_url, secure=True)
        self.assertEqual(draft.json(), {"language": "tr", "current_ui_language": "en", "current_email_language": "tr"})
        self.assertEqual(draft["Cache-Control"], "private, no-store")

    def test_registration_requires_csrf_and_valid_password_then_stays_unverified(self):
        response = self.request(
            "post", self.signup_url, {"email": "new@example.com", "password": self.password}, csrf=False
        )
        self.assertEqual(response.status_code, 403)

        self.csrf()
        weak = self.request("post", self.signup_url, {"email": "weak@example.com", "password": "password"})
        self.assertEqual(weak.status_code, 400)
        self.assertFalse(User.objects.filter(email="weak@example.com").exists())

        user, key, response = self.signup()
        self.assertEqual(user.registration_origin, User.RegistrationOrigin.SELF_SERVICE)
        self.assertIn(
            {"id": "verify_email", "is_pending": True},
            response.json()["data"]["flows"],
        )
        self.assertFalse(EmailAddress.objects.get(user=user).verified)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertTrue(self.client.cookies["sessionid"]["httponly"])
        self.assertEqual(self.client.cookies["sessionid"]["samesite"], "Lax")
        self.assertFalse(self.client.cookies["csrftoken"]["httponly"])
        self.assertEqual(
            self.client.get(
                reverse("verification-status"), HTTP_X_EMAIL_VERIFICATION_KEY=key, secure=True
            ).json(),
            {"state": "pending"},
        )

    def test_verification_expiry_replay_login_session_and_logout(self):
        user, key, _ = self.signup()
        self.assertIsNone(user.first_email_verified_at)
        preview = self.client.get(self.verify_url, HTTP_X_EMAIL_VERIFICATION_KEY=key, secure=True)
        self.assertEqual(preview.status_code, 200, preview.content)

        verified = self.request("post", self.verify_url, {"key": key})
        self.assertEqual(verified.status_code, 401, verified.content)
        self.assertTrue(EmailAddress.objects.get(user=user).verified)
        user.refresh_from_db()
        verified_at = user.first_email_verified_at
        self.assertIsNotNone(verified_at)
        self.assertEqual(user.registration_origin, User.RegistrationOrigin.SELF_SERVICE)
        replay = self.request("post", self.verify_url, {"key": key})
        self.assertEqual(replay.status_code, 400)
        user.refresh_from_db()
        self.assertEqual(user.first_email_verified_at, verified_at)
        self.assertEqual(user.registration_origin, User.RegistrationOrigin.SELF_SERVICE)
        self.assert_account_audit(user, AuditEventType.ACCOUNT_EMAIL_VERIFIED)
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.ACCOUNT_EMAIL_CHANGED).exists())
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.ACCOUNT_LOGGED_IN).exists())
        self.assertEqual(
            self.client.get(
                reverse("verification-status"), HTTP_X_EMAIL_VERIFICATION_KEY=key, secure=True
            ).json(),
            {"state": "used"},
        )

        logged_in = self.request(
            "post", self.login_url, {"email": user.email, "password": self.password}
        )
        self.assertEqual(logged_in.status_code, 200, logged_in.content)
        self.assertIn(SESSION_KEY, self.client.session)
        self.assertEqual(self.client.get(self.session_url, secure=True).status_code, 200)
        self.assert_account_audit(user, AuditEventType.ACCOUNT_LOGGED_IN)
        logged_out = self.request("delete", self.session_url)
        self.assertEqual(logged_out.status_code, 401, logged_out.content)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assert_account_audit(user, AuditEventType.ACCOUNT_LOGGED_OUT)

    def test_unverified_login_is_denied_and_resend_is_generic_and_throttled(self):
        user, _, _ = self.signup()
        denied = self.request(
            "post", self.login_url, {"email": user.email, "password": self.password}
        )
        self.assertEqual(denied.status_code, 401)
        self.assertIn(
            {"id": "verify_email", "is_pending": True},
            denied.json()["data"]["flows"],
        )
        self.assertNotIn(SESSION_KEY, self.client.session)

        cache.clear()
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.ACCOUNT_LOGGED_IN).exists())
        before = len(mail.outbox)
        sent = self.request("post", reverse("resend-verification"), {"email": user.email})
        self.assertEqual(sent.status_code, 202, sent.content)
        self.assertEqual(len(mail.outbox), before + 1)
        limited = self.request("post", reverse("resend-verification"), {"email": user.email})
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.headers["Retry-After"], "180")

        cache.clear()
        unknown = self.request("post", reverse("resend-verification"), {"email": "unknown@example.com"})
        self.assertEqual(unknown.status_code, 202)
        self.assertEqual(set(unknown.json()), {"message"})
        self.assertEqual(len(mail.outbox), before + 1)

        for index in range(4):
            response = self.request(
                "post", reverse("resend-verification"), {"email": f"unknown-{index}@example.com"}
            )
            self.assertEqual(response.status_code, 202)
        source_limited = self.request(
            "post", reverse("resend-verification"), {"email": "unknown-5@example.com"}
        )
        self.assertEqual(source_limited.status_code, 429)
        self.assertEqual(len(mail.outbox), before + 1)

    def test_expired_and_invalid_verification_states(self):
        user, key, _ = self.signup()
        EmailConfirmation.objects.filter(key=key).update(sent=timezone.now() - timedelta(days=4))
        status = reverse("verification-status")
        self.assertEqual(
            self.client.get(status, HTTP_X_EMAIL_VERIFICATION_KEY=key, secure=True).json(),
            {"state": "expired"},
        )
        self.assertEqual(
            self.client.get(status, HTTP_X_EMAIL_VERIFICATION_KEY="not-a-key", secure=True).json(),
            {"state": "invalid"},
        )
        expired = self.client.get(self.verify_url, HTTP_X_EMAIL_VERIFICATION_KEY=key, secure=True)
        self.assertEqual(expired.status_code, 400)
        user.refresh_from_db()
        self.assertIsNone(user.first_email_verified_at)
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.ACCOUNT_EMAIL_VERIFIED).exists())

    def test_duplicate_signup_does_not_replace_existing_registration_origin(self):
        user = self.create_verified_user("existing@example.com")
        self.assertIsNone(user.registration_origin)
        self.csrf()
        self.request("post", self.signup_url, {"email": user.email, "password": self.password})
        user.refresh_from_db()
        self.assertIsNone(user.registration_origin)
        self.assertEqual(User.objects.filter(email=user.email).count(), 1)

    def test_same_origin_is_allowed_and_untrusted_origin_is_rejected(self):
        allowed = Client(enforce_csrf_checks=True)
        self.csrf(allowed)
        response = self.request(
            "post",
            self.signup_url,
            {"email": "allowed@example.com", "password": self.password},
            client=allowed,
            origin="https://testserver",
        )
        self.assertEqual(response.status_code, 401, response.content)

        denied = Client(enforce_csrf_checks=True)
        self.csrf(denied)
        response = self.request(
            "post",
            self.signup_url,
            {"email": "denied@example.com", "password": self.password},
            client=denied,
            origin="https://evil.example",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(email="denied@example.com").exists())

    def test_password_reset_is_generic_single_use_and_revokes_existing_sessions(self):
        user = self.create_verified_user()
        existing_session = Client(enforce_csrf_checks=True)
        self.login(existing_session, user)
        old_password_hash = user.password

        self.csrf()
        known = self.request("post", self.password_request_url, {"email": user.email})
        self.assertEqual(known.status_code, 200, known.content)
        match = re.search(r"/account/reset-password#([^\s]+)", mail.outbox[-1].body)
        self.assertIsNotNone(match, mail.outbox[-1].body)
        key = match.group(1)
        user.refresh_from_db()
        self.assertEqual(user.password, old_password_hash)
        self.assertEqual(existing_session.get(self.session_url, secure=True).status_code, 200)

        unknown = self.request("post", self.password_request_url, {"email": "unknown@example.com"})
        self.assertEqual(unknown.status_code, known.status_code)
        self.assertEqual(unknown.json(), known.json())
        self.assertEqual(len(mail.outbox), 2)

        with override_settings(PASSWORD_RESET_TIMEOUT=-1):
            expired = self.client.get(
                self.password_reset_url,
                HTTP_X_PASSWORD_RESET_KEY=key,
                secure=True,
            )
        self.assertEqual(expired.status_code, 400)
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.ACCOUNT_PASSWORD_RESET).exists())

        new_password = f"B-{secrets.token_urlsafe(24)}"
        reset = self.request(
            "post",
            self.password_reset_url,
            {"key": key, "password": new_password},
        )
        self.assertEqual(reset.status_code, 401, reset.content)
        user.refresh_from_db()
        self.assertTrue(user.check_password(new_password))
        self.assertEqual(existing_session.get(self.session_url, secure=True).status_code, 401)
        self.assertTrue(any(message.to == [user.email] and "reset" in message.subject.lower() for message in mail.outbox))

        replay = self.request(
            "post",
            self.password_reset_url,
            {"key": key, "password": f"C-{secrets.token_urlsafe(24)}"},
        )
        self.assertEqual(replay.status_code, 400)
        self.assert_account_audit(user, AuditEventType.ACCOUNT_PASSWORD_RESET)
        self.login(Client(enforce_csrf_checks=True), user, new_password)

    def test_password_change_requires_current_password_and_ends_all_sessions(self):
        user = self.create_verified_user()
        current = Client(enforce_csrf_checks=True)
        other = Client(enforce_csrf_checks=True)
        self.login(current, user)
        self.login(other, user)

        no_csrf = current.post(
            self.password_change_url,
            data=json.dumps({"current_password": self.password, "new_password": "Not-used-password-123"}),
            content_type="application/json",
            secure=True,
        )
        self.assertEqual(no_csrf.status_code, 403)
        untrusted = self.request(
            "post",
            self.password_change_url,
            {"current_password": self.password, "new_password": "Not-used-password-123"},
            client=current,
            origin="https://evil.example",
        )
        self.assertEqual(untrusted.status_code, 403)

        denied = self.request(
            "post",
            self.password_change_url,
            {"current_password": "wrong", "new_password": f"B-{secrets.token_urlsafe(24)}"},
            client=current,
        )
        self.assertEqual(denied.status_code, 400)
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.ACCOUNT_PASSWORD_CHANGED).exists())

        new_password = f"C-{secrets.token_urlsafe(24)}"
        changed = self.request(
            "post",
            self.password_change_url,
            {"current_password": self.password, "new_password": new_password},
            client=current,
        )
        self.assertEqual(changed.status_code, 204, changed.content)
        self.assertEqual(current.get(self.session_url, secure=True).status_code, 401)
        self.assertEqual(other.get(self.session_url, secure=True).status_code, 401)
        self.assertTrue(any("password changed" in message.subject.lower() for message in mail.outbox))
        self.assert_account_audit(user, AuditEventType.ACCOUNT_PASSWORD_CHANGED)
        self.login(Client(enforce_csrf_checks=True), user, new_password)

    def test_security_audit_failure_does_not_interrupt_password_session_revocation(self):
        user = self.create_verified_user()
        other = Client(enforce_csrf_checks=True)
        self.login(self.client, user)
        self.login(other, user)
        new_password = f"B-{secrets.token_urlsafe(24)}"
        create_audit = AuditEvent.objects.create
        def invalid_audit(**fields):
            return create_audit(**{**fields, "event_type": None})
        with patch("tenancy.signals.AuditEvent.objects.create", side_effect=invalid_audit), \
                self.assertLogs("organicseoops.security", level="ERROR") as logs:
            changed = self.request("post", self.password_change_url,
                {"current_password": self.password, "new_password": new_password})
        self.assertEqual(changed.status_code, 204, changed.content)
        user.refresh_from_db()
        self.assertTrue(user.check_password(new_password))
        self.assertEqual(self.client.get(self.session_url, secure=True).status_code, 401)
        self.assertEqual(other.get(self.session_url, secure=True).status_code, 401)
        self.assertFalse(UserSession.objects.filter(user=user).exists())
        self.assertTrue(logs.output)
        self.assertTrue(all(line.endswith("account.security_audit_failed") for line in logs.output))
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.ACCOUNT_PASSWORD_CHANGED).exists())

    def test_email_change_requires_recent_authentication_and_verification(self):
        user = self.create_verified_user()
        first_verified_at = timezone.now() - timedelta(days=1)
        User.objects.filter(pk=user.pk).update(first_email_verified_at=first_verified_at)
        self.login(self.client, user)
        session = self.client.session
        session[AUTHENTICATION_METHODS_SESSION_KEY] = []
        session.save()

        stale = self.request("post", self.email_url, {"email": "New@Example.com"})
        self.assertEqual(stale.status_code, 401)
        self.assertTrue(any(flow["id"] == "reauthenticate" for flow in stale.json()["data"]["flows"]))
        reauthenticated = self.request("post", self.reauthenticate_url, {"password": self.password})
        self.assertEqual(reauthenticated.status_code, 200, reauthenticated.content)

        requested = self.request("post", self.email_url, {"email": "New@Example.com"})
        self.assertEqual(requested.status_code, 200, requested.content)
        user.refresh_from_db()
        self.assertEqual(user.email, "person@example.com")
        pending = EmailAddress.objects.get(user=user, verified=False)
        self.assertEqual(pending.email, "new@example.com")
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.ACCOUNT_EMAIL_CHANGED).exists())

        preverification = Client(enforce_csrf_checks=True)
        self.csrf(preverification)
        denied = self.request(
            "post",
            self.login_url,
            {"email": pending.email, "password": self.password},
            client=preverification,
        )
        self.assertEqual(denied.status_code, 401)
        self.assertNotIn(SESSION_KEY, preverification.session)
        user.refresh_from_db()
        self.assertEqual(user.email, "person@example.com")

        key = self.verification_key()
        verified = self.request("post", self.verify_url, {"key": key})
        self.assertEqual(verified.status_code, 200, verified.content)
        user.refresh_from_db()
        self.assertEqual(user.email, "new@example.com")
        self.assertEqual(user.first_email_verified_at, first_verified_at)
        self.assertIsNone(user.registration_origin)
        self.assertFalse(EmailAddress.objects.filter(user=user, email="person@example.com").exists())
        self.assertTrue(any(message.to == ["person@example.com"] and "email changed" in message.subject.lower() for message in mail.outbox))
        self.assert_account_audit(user, AuditEventType.ACCOUNT_EMAIL_CHANGED)
        self.assert_account_audit(user, AuditEventType.ACCOUNT_EMAIL_VERIFIED)

    def test_email_collision_cannot_replace_the_login_identifier(self):
        user = self.create_verified_user()
        self.create_verified_user("taken@example.com")
        self.login(self.client, user)

        requested = self.request("post", self.email_url, {"email": "TAKEN@example.com"})
        self.assertEqual(requested.status_code, 200, requested.content)
        key = self.verification_key()
        rejected = self.request("post", self.verify_url, {"key": key})
        self.assertEqual(rejected.status_code, 400)
        user.refresh_from_db()
        self.assertEqual(user.email, "person@example.com")
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.ACCOUNT_EMAIL_CHANGED).exists())

    def test_session_listing_individual_revocation_and_logout_all(self):
        user = self.create_verified_user()
        current = Client(enforce_csrf_checks=True, HTTP_USER_AGENT="current-browser")
        other = Client(enforce_csrf_checks=True, HTTP_USER_AGENT="other-browser")
        self.login(current, user)
        self.login(other, user)

        no_csrf = current.post(
            self.logout_all_url,
            data="{}",
            content_type="application/json",
            secure=True,
        )
        self.assertEqual(no_csrf.status_code, 403)

        sessions = current.get(self.sessions_url, secure=True)
        self.assertEqual(sessions.status_code, 200, sessions.content)
        listed = sessions.json()["data"]
        self.assertEqual(len(listed), 2)
        other_id = next(item["id"] for item in listed if not item["is_current"])
        revoked = self.request(
            "delete", self.sessions_url, {"sessions": [str(other_id)]}, client=current
        )
        self.assertEqual(revoked.status_code, 200, revoked.content)
        self.assertEqual(other.get(self.session_url, secure=True).status_code, 401)
        self.assertEqual(current.get(self.session_url, secure=True).status_code, 200)

        late = Client(enforce_csrf_checks=True, HTTP_USER_AGENT="late-browser")
        self.login(late, user)
        logged_out = self.request("post", self.logout_all_url, {}, client=current)
        self.assertEqual(logged_out.status_code, 204, logged_out.content)
        self.assertNotIn(SESSION_KEY, current.session)
        self.assertEqual(late.get(self.session_url, secure=True).status_code, 401)
        self.assertFalse(UserSession.objects.filter(user=user).exists())

    def test_staff_mfa_enrollment_challenge_recovery_and_session_revocation(self):
        staff = User.objects.create_superuser("staff@example.com", self.password)
        current = Client(enforce_csrf_checks=True, HTTP_USER_AGENT="current-browser")
        other = Client(enforce_csrf_checks=True, HTTP_USER_AGENT="other-browser")
        self.login(current, staff)
        self.login(other, staff)

        setup = current.get(self.totp_url, secure=True)
        self.assertEqual(setup.status_code, 404)
        secret = setup.json()["meta"]["secret"]
        code = format_hotp_value(hotp_value(secret, next(yield_hotp_counters_from_time())))
        self.assertEqual(
            current.post(self.totp_url, data=json.dumps({"code": code}), content_type="application/json", secure=True).status_code,
            403,
        )
        with patch("django.db.transaction.on_commit", side_effect=lambda callback: callback()):
            activated = self.request("post", self.totp_url, {"code": code}, client=current)
        self.assertEqual(activated.status_code, 200, activated.content)
        stored_totp = Authenticator.objects.get(user=staff, type=Authenticator.Type.TOTP)
        self.assertNotEqual(stored_totp.data["secret"], secret)
        self.assertTrue(stored_totp.data["secret"].startswith("v1:"))
        self.assertEqual(current.get(self.session_url, secure=True).status_code, 200)
        self.assertEqual(other.get(self.session_url, secure=True).status_code, 401)
        self.assertTrue(AuditEvent.objects.filter(
            subject_user=staff,
            event_type=AuditEventType.STAFF_MFA_ADDED,
            details={"authenticator_type": Authenticator.Type.TOTP},
        ).exists())
        with override_settings(STAFF_MFA_REQUIRED=True):
            self.assertEqual(current.get(reverse("admin:index"), secure=True).status_code, 200)

        recovery = current.get(self.recovery_codes_url, secure=True)
        self.assertEqual(recovery.status_code, 200)
        recovery_code = recovery.json()["data"]["unused_codes"][0]

        challenged = Client(enforce_csrf_checks=True)
        self.csrf(challenged)
        password_stage = self.request(
            "post",
            self.login_url,
            {"email": staff.email, "password": self.password},
            client=challenged,
        )
        self.assertEqual(password_stage.status_code, 401, password_stage.content)
        pending = next(flow for flow in password_stage.json()["data"]["flows"] if flow["id"] == "mfa_authenticate")
        self.assertTrue(pending["is_pending"])
        self.assertEqual(set(pending["types"]), {"totp", "recovery_codes"})

        completed = self.request(
            "post",
            self.mfa_authenticate_url,
            {"code": recovery_code},
            client=challenged,
        )
        self.assertEqual(completed.status_code, 200, completed.content)
        self.assertEqual(challenged.get(self.session_url, secure=True).status_code, 200)
        self.assertTrue(AuditEvent.objects.filter(
            subject_user=staff,
            event_type=AuditEventType.STAFF_MFA_RECOVERY_USED,
        ).exists())
        self.assertNotIn(recovery_code, str(AuditEvent.objects.filter(subject_user=staff).values("details")))

        replay = Client(enforce_csrf_checks=True)
        self.csrf(replay)
        replay_stage = self.request(
            "post", self.login_url, {"email": staff.email, "password": self.password}, client=replay
        )
        self.assertEqual(replay_stage.status_code, 401)
        rejected = self.request("post", self.mfa_authenticate_url, {"code": recovery_code}, client=replay)
        self.assertEqual(rejected.status_code, 400)

    @override_settings(STAFF_MFA_REQUIRED=True)
    def test_production_admin_requires_staff_totp_and_customer_mfa_endpoints_are_hidden(self):
        customer = self.create_verified_user()
        customer_client = Client(enforce_csrf_checks=True)
        self.login(customer_client, customer)
        self.assertEqual(customer_client.get(self.authenticators_url, secure=True).status_code, 404)

        staff = User.objects.create_superuser("staff@example.com", self.password)
        staff_client = Client(enforce_csrf_checks=True)
        self.login(staff_client, staff)
        blocked = staff_client.get(reverse("admin:index"), secure=True)
        self.assertEqual(blocked.status_code, 302)
        self.assertEqual(
            blocked.url,
            f"{settings.FRONTEND_ORIGIN}/account/security?mfa=required&next=%2Fadmin%2F",
        )

        Authenticator.objects.create(
            user=staff,
            type=Authenticator.Type.TOTP,
            data={"secret": "test-only"},
        )
        stale = staff_client.get(reverse("admin:index"), secure=True)
        self.assertEqual(stale.status_code, 302)
        self.assertIn("/account/login?mfa=required", stale.url)
        self.assertNotIn(SESSION_KEY, staff_client.session)
