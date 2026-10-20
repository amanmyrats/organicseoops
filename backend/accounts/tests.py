import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch

from asgiref.sync import async_to_sync
from allauth.account.models import EmailAddress
from allauth.mfa.models import Authenticator
from allauth.mfa.totp.internal.auth import TOTP
from cryptography.fernet import Fernet
from django.contrib.auth import authenticate, get_user_model
from django.contrib.admin.models import LogEntry
from django.core.exceptions import ValidationError
from django.core.management import call_command, CommandError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from .forms import UserCreationForm, UserEditForm
from .auth import AccountAdapter, StaffMFAAdapter
from tenancy.models import AuditEvent, AuditEventType

User = get_user_model()


@override_settings(SECURE_SSL_REDIRECT=False)
class UserTests(TestCase):
    def test_normalized_identity_password_and_authentication(self):
        password = secrets.token_urlsafe(24)
        user = User.objects.create_user("  Alice.Tag+SEO@EXAMPLE.COM \t", password)
        user.refresh_from_db()
        self.assertEqual(user.email, "alice.tag+seo@example.com")
        self.assertIsNone(user.registration_origin)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertNotEqual(user.password, password)
        self.assertTrue(user.check_password(password))
        self.assertEqual(authenticate(email=" ALICE.TAG+SEO@Example.COM ", password=password), user)
        self.assertEqual(async_to_sync(User.objects.aget_by_natural_key)(" ALICE.TAG+SEO@Example.COM "), user)
        user.is_active = False
        user.save(update_fields=["is_active"])
        self.assertIsNone(authenticate(email=user.email, password=password))

    def test_invalid_and_duplicate_email_on_manager_forms_and_model(self):
        for email in (None, "", " \t", "not-an-email", "a b@example.com"):
            with self.subTest(email=email), self.assertRaises(ValidationError):
                User.objects.create_user(email)
        user = User.objects.create_user("one@example.com")
        self.assertFalse(user.has_usable_password())
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(" ONE@EXAMPLE.COM ")
        duplicate = User(email=" ONE@EXAMPLE.COM ")
        duplicate.set_unusable_password()
        with self.assertRaises(ValidationError) as error:
            duplicate.full_clean()
        self.assertIn("email", error.exception.message_dict)
        form = UserCreationForm(data={"email": "ONE@EXAMPLE.COM", "usable_password": "false"})
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)
        user.email = " NEW@EXAMPLE.COM "
        user.save(update_fields=["email"])
        user.refresh_from_db()
        self.assertEqual(user.email, "new@example.com")

    def test_database_constraints_protect_bypass_writes(self):
        user = User.objects.create_user("one@example.com")
        for email in ("one@example.com", "ONE@example.com", " other@example.com ", "", "\t"):
            with self.subTest(email=email), self.assertRaises(IntegrityError), transaction.atomic():
                User.objects.bulk_create([User(email=email)])
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.filter(pk=user.pk).update(email="ONE@example.com")

    def test_supported_superuser_command_admin_forms_and_csrf(self):
        password = secrets.token_urlsafe(24)
        with patch.dict(os.environ, {"DJANGO_SUPERUSER_PASSWORD": password}):
            call_command("createsuperuser", email="STAFF@EXAMPLE.COM", interactive=False, stdout=StringIO())
        staff = User.objects.get(email="staff@example.com")
        self.assertTrue(staff.is_staff and staff.is_superuser and staff.is_active)
        self.assertTrue(staff.check_password(password))
        self.assertTrue(EmailAddress.objects.filter(user=staff, email=staff.email, primary=True, verified=True).exists())
        self.assertIsNone(staff.registration_origin)
        browser = Client(enforce_csrf_checks=True)
        login_url = reverse("admin:login")
        response = browser.get(login_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/account/login", response.url)
        browser.force_login(staff)
        self.assertEqual(browser.get(reverse("admin:index")).status_code, 200)
        self.assertEqual(browser.get(reverse("admin:accounts_user_add")).status_code, 200)
        self.assertEqual(browser.get(reverse("admin:accounts_user_change", args=[staff.pk])).status_code, 200)
        form = UserCreationForm(data={
            "email": " New@Example.COM ", "usable_password": "true",
            "password1": password, "password2": password,
        })
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertEqual(user.email, "new@example.com")
        self.assertTrue(user.check_password(password))
        edit = UserEditForm(instance=user, data={
            "email": "new@example.com", "password": "replace-the-hash", "is_active": True,
            "date_joined": user.date_joined,
        })
        self.assertTrue(edit.is_valid(), edit.errors)
        self.assertTrue(edit.save().check_password(password))
        self.assertTrue(self.client.login(email=user.email, password=password))
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 302)
        for flag in ("is_staff", "is_superuser"):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                User.objects.create_superuser("invalid@example.com", password, **{flag: False})

    def test_migrations_use_custom_user_and_admin_reference(self):
        self.assertEqual(User._meta.label, "accounts.User")
        self.assertIs(LogEntry._meta.get_field("user").remote_field.model, User)
        tables = connection.introspection.table_names()
        self.assertIn("accounts_user", tables)
        self.assertNotIn("auth_user", tables)
        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(cursor, "django_admin_log")
        self.assertIn(("accounts_user", "id"), [item["foreign_key"] for item in constraints.values()])

    def test_mfa_encryption_supports_key_rotation(self):
        old_key = Fernet.generate_key().decode()
        new_key = Fernet.generate_key().decode()
        with override_settings(MFA_ENCRYPTION_KEYS=(old_key,)):
            encrypted = StaffMFAAdapter().encrypt("known-secret")
        self.assertNotIn("known-secret", encrypted)
        with override_settings(MFA_ENCRYPTION_KEYS=(new_key, old_key)):
            adapter = StaffMFAAdapter()
            self.assertEqual(adapter.decrypt(encrypted), "known-secret")
            self.assertEqual(adapter.decrypt(adapter.encrypt("new-secret")), "new-secret")

    def test_later_verification_keeps_historical_first_verification_unknown(self):
        user = User.objects.create_user("historical@example.com")
        EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
        pending = EmailAddress.objects.create(user=user, email="historical-new@example.com")

        with (
            patch.object(AccountAdapter, "add_message"),
            patch("allauth.account.internal.flows.email_verification.emit_email_changed"),
        ):
            self.assertTrue(AccountAdapter().confirm_email(SimpleNamespace(user=user), pending))

        user.refresh_from_db()
        self.assertIsNone(user.first_email_verified_at)

    def test_lost_factor_command_requires_two_person_confirmation_and_revokes_access(self):
        actor = User.objects.create_superuser("operator@example.com", secrets.token_urlsafe(24))
        target = User.objects.create_superuser("locked@example.com", secrets.token_urlsafe(24))
        TOTP.activate(target, "JBSWY3DPEHPK3PXP")
        browser = Client()
        browser.force_login(target)
        browser.get("/api/health/", secure=True)
        old_version = target.session_version

        with self.assertRaises(CommandError):
            call_command(
                "reset_staff_mfa",
                target.email,
                actor=target.email,
                reason="Lost device",
                confirm_email=target.email,
            )
        output = StringIO()
        call_command(
            "reset_staff_mfa",
            target.email,
            actor=actor.email,
            reason="Approved ticket 123",
            confirm_email=target.email,
            stdout=output,
        )
        target.refresh_from_db()
        self.assertNotEqual(target.session_version, old_version)
        self.assertFalse(Authenticator.objects.filter(user=target).exists())
        self.assertEqual(browser.get("/api/health/", secure=True).status_code, 200)
        self.assertEqual(browser.get("/api/organizations/", secure=True).status_code, 401)
        event = AuditEvent.objects.get(subject_user=target, event_type=AuditEventType.STAFF_MFA_RECOVERY_RESET)
        self.assertEqual(event.actor, actor)
        self.assertEqual(event.details, {"operation": "lost_factor_reset", "reason": "Approved ticket 123"})
        self.assertNotIn("JBSWY3DPEHPK3PXP", output.getvalue())


class EmailRaceTests(TransactionTestCase):
    @override_settings(PERSONAL_IDENTITY_ERASURE_POLICY_REFERENCE="fixture-policy-v1",
                       PERSONAL_IDENTITY_TRIAL_RETENTION_DAYS=10,
                       PERSONAL_IDENTITY_RETENTION_KEY="fixture-key-" * 4)
    @patch("tenancy.services.did_recently_authenticate", return_value=True)
    def test_stale_email_and_session_writes_cannot_recreate_erased_account_identity(self, _reauth):
        from threading import Event
        from django.test import RequestFactory
        from django.utils import timezone
        from allauth.account.internal.flows.login import AUTHENTICATION_METHODS_SESSION_KEY
        from allauth.usersessions.models import UserSession
        from .closure import close_personal_access, erase_closed_account_identity
        user = User.objects.create_user("child-erase-race@example.invalid")
        old_address = EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
        staff = User.objects.create_superuser("child-erase-staff@example.invalid")
        Authenticator.objects.create(user=staff, type=Authenticator.Type.TOTP, data={"secret": "unused-fixture"})
        client = Client(); client.force_login(staff)
        session = client.session
        session[AUTHENTICATION_METHODS_SESSION_KEY] = [{"method": "mfa", "at": timezone.now().timestamp()}]
        session.save()
        close_request = RequestFactory().post("/api/account/close/"); close_request.user = user
        cleanup_request = RequestFactory().post("/admin/accounts/user/identity-cleanup/")
        cleanup_request.user, cleanup_request.session = staff, client.session
        started = Event()

        def stale_identity_writes():
            close_old_connections()
            try:
                started.set()
                results = []
                for create in (lambda: EmailAddress.objects.create(user_id=user.pk, email="stale-add@example.invalid"),
                               lambda: UserSession.objects.create(user_id=user.pk, session_key="r" * 40,
                                                                  ip="127.0.0.1", user_agent="stale-session")):
                    try:
                        with transaction.atomic(): create()
                        results.append("recreated")
                    except IntegrityError:
                        results.append("denied")
                return results
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=1) as pool:
            with patch("accounts.closure.end_sessions"), transaction.atomic():
                close_personal_access(actor=user, request=close_request)
                erase_closed_account_identity(request=cleanup_request, user_id=user.pk, policy_reference="fixture-policy-v1")
                result = pool.submit(stale_identity_writes)
                self.assertTrue(started.wait(timeout=5))
            self.assertEqual(result.result(timeout=10), ["denied", "denied"])
        self.assertFalse(EmailAddress.objects.filter(user=user).exists())
        self.assertFalse(UserSession.objects.filter(user=user).exists())
        self.assertFalse(AccountAdapter().confirm_email(close_request, old_address))
        self.assertFalse(EmailAddress.objects.filter(user=user).exists())

    def test_concurrent_registration_cannot_duplicate_identity(self):
        barrier = Barrier(2, timeout=10)

        def create(email):
            close_old_connections()
            try:
                barrier.wait()
                User.objects.create_user(email)
                return "created"
            except IntegrityError:
                return "duplicate"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(create, ["race@example.com", " RACE@EXAMPLE.COM "]))
        self.assertCountEqual(outcomes, ["created", "duplicate"])
        self.assertEqual(User.objects.filter(email="race@example.com").count(), 1)

    def test_concurrent_email_change_verification_has_one_winner(self):
        users = [User.objects.create_user(f"person-{index}@example.com") for index in range(2)]
        for user in users:
            EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
            EmailAddress.objects.create(user=user, email="race-change@example.com")
        barrier = Barrier(2, timeout=10)

        def verify(user_id):
            close_old_connections()
            try:
                with transaction.atomic():
                    address = EmailAddress.objects.get(user_id=user_id, email="race-change@example.com")
                    barrier.wait()
                    address.set_verified()
                    address.set_as_primary()
                return "changed"
            except IntegrityError:
                return "duplicate"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(verify, [user.pk for user in users]))
        self.assertCountEqual(outcomes, ["changed", "duplicate"])
        self.assertEqual(User.objects.filter(email="race-change@example.com").count(), 1)
        self.assertEqual(EmailAddress.objects.filter(email="race-change@example.com", verified=True).count(), 1)

    def test_concurrent_first_verification_sets_one_timestamp(self):
        user = User.objects.create_user("first-verification-race@example.com")
        EmailAddress.objects.create(user=user, email=user.email, primary=True)
        barrier = Barrier(2, timeout=10)

        def verify(_):
            close_old_connections()
            try:
                thread_user = User.objects.get(pk=user.pk)
                address = EmailAddress.objects.get(user=thread_user)
                barrier.wait()
                return AccountAdapter().confirm_email(SimpleNamespace(user=thread_user), address)
            finally:
                close_old_connections()

        with patch.object(AccountAdapter, "add_message"):
            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(verify, range(2)))

        self.assertCountEqual(outcomes, [True, False])
        user.refresh_from_db()
        self.assertIsNotNone(user.first_email_verified_at)
        self.assertTrue(EmailAddress.objects.get(user=user).verified)
        self.assertEqual(AuditEvent.objects.filter(subject_user=user,
            event_type=AuditEventType.ACCOUNT_EMAIL_VERIFIED).count(), 1)
