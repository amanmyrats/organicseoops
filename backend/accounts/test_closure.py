from unittest.mock import patch

from allauth.account.models import EmailAddress
from allauth.usersessions.models import UserSession
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, RequestFactory, TestCase
from django.utils import timezone

from tenancy.models import AuditEvent, AuditEventType, Organization
from tenancy.services import create_organization, create_project, set_user_suspension

from .closure import close_personal_access


class PersonalClosureTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user("personal-close@example.invalid", password="test-password",
                                       first_name="Private", last_name="Name")
        self.other = users.create_user("other-account@example.invalid", password="test-password")
        self.staff = users.create_superuser("close-staff@example.invalid", password="test-password")
        for user in (self.owner, self.other):
            EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
        self.org = create_organization(user=self.owner, name="First owner's customer organization")
        self.project = create_project(organization=self.org, user=self.owner, name="Private project",
                                      canonical_origin="https://personal-close.example.invalid")
        self.other_org = create_organization(user=self.other, name="Other owner organization")
        self.request = RequestFactory().post("/api/account/close/")
        self.request.user = self.owner

    @patch("tenancy.services.did_recently_authenticate", return_value=True)
    def test_owner_cannot_close_before_org_closure_and_closed_account_cannot_reactivate(self, _reauth):
        owner_client = Client()
        owner_client.force_login(self.owner)
        with self.assertRaises(ValidationError):
            close_personal_access(actor=self.owner, request=self.request)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_active)
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
        original_email = self.owner.email
        tracked = UserSession.objects.create(user=self.owner, session_key="t" * 40, ip="127.0.0.1",
                                             user_agent="fixture")
        with patch("accounts.closure.end_sessions") as end:
            with self.captureOnCommitCallbacks(execute=True):
                closed = close_personal_access(actor=self.owner, request=self.request)
            self.assertEqual(end.call_count, 1)
            self.assertEqual(end.call_args.args[0], self.request)
            self.assertEqual([item.pk for item in end.call_args.args[1]], [tracked.pk])
        self.assertIsNotNone(closed.closed_at)
        self.assertFalse(closed.is_active)
        self.assertFalse(closed.has_usable_password())
        self.assertEqual((closed.first_name, closed.last_name), ("", ""))
        self.assertEqual(owner_client.get("/api/organizations/").status_code, 401)
        self.assertTrue(self.project.__class__.objects.filter(pk=self.project.pk).exists())
        self.assertTrue(Organization.objects.filter(pk=self.other_org.pk).exists())
        self.assertEqual(EmailAddress.objects.get(user=closed).email, original_email)
        self.assertEqual(AuditEvent.objects.filter(actor=closed, event_type=AuditEventType.ACCOUNT_CLOSED).count(), 1)
        with self.assertRaises(ValidationError):
            set_user_suspension(user=closed, actor=self.staff, suspended=False, reason="Cannot reopen")
        closed.is_active = True
        with self.assertRaises(ValidationError):
            closed.save(update_fields=["is_active"])

    @patch("tenancy.services.did_recently_authenticate", return_value=True)
    def test_audit_failure_rolls_back_personal_closure_and_staff_cannot_self_close(self, _reauth):
        self.request.user = self.staff
        with self.assertRaises(PermissionDenied):
            close_personal_access(actor=self.staff, request=self.request)
        self.request.user = self.owner
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
        with patch("accounts.closure.AuditEvent.objects.create", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaises(RuntimeError):
                close_personal_access(actor=self.owner, request=self.request)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_active)
        self.assertIsNone(self.owner.closed_at)
        self.assertTrue(self.owner.has_usable_password())

    def _staff_cleanup_request(self):
        from allauth.account.internal.flows.login import AUTHENTICATION_METHODS_SESSION_KEY
        from allauth.mfa.models import Authenticator
        Authenticator.objects.get_or_create(user=self.staff, type=Authenticator.Type.TOTP,
                                           defaults={"data": {"secret": "unused-fixture"}})
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.staff)
        session = client.session
        session[AUTHENTICATION_METHODS_SESSION_KEY] = [{"method": "mfa", "at": timezone.now().timestamp()}]
        session.save()
        request = RequestFactory().post("/admin/accounts/user/identity-cleanup/")
        request.user, request.session = self.staff, client.session
        return client, request

    @patch("tenancy.services.did_recently_authenticate", return_value=True)
    def test_reviewed_account_cleanup_retains_lineage_without_regranting_erased_identity_trial(self, _reauth):
        from datetime import timedelta
        from allauth.mfa.models import Authenticator
        from django.test import override_settings
        from .closure import erase_closed_account_identity
        from .models import AccountEmailDelivery, RetainedTrialIdentity
        from tenancy.models import AutomaticTrialEligibility, TrialState
        original_email = self.owner.email
        alternate = EmailAddress.objects.create(user=self.owner, email="verified-alternate@example.invalid", verified=True)
        EmailAddress.objects.create(user=self.owner, email="unverified-victim@example.invalid", verified=False)
        AccountEmailDelivery.objects.create(address=alternate, purpose="fixture")
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
        close_personal_access(actor=self.owner, request=self.request)
        tracked = UserSession.objects.create(user=self.owner, session_key="e" * 40, ip="127.0.0.1",
                                             user_agent="identity-erase-marker")
        Authenticator.objects.create(user=self.owner, type=Authenticator.Type.TOTP, data={"secret": "target-secret"})
        _, request = self._staff_cleanup_request()
        # These are synthetic policy values, not accepted real retention terms.
        policy = dict(PERSONAL_IDENTITY_ERASURE_POLICY_REFERENCE="fixture-policy-v1",
                      PERSONAL_IDENTITY_TRIAL_RETENTION_DAYS=10, PERSONAL_IDENTITY_RETENTION_KEY="fixture-key-" * 4)
        with override_settings(**policy):
            closed = erase_closed_account_identity(request=request, user_id=self.owner.pk, policy_reference="fixture-policy-v1")
            self.assertIsNotNone(closed.identity_erased_at)
            self.assertNotEqual(closed.email, original_email)
            self.assertEqual((closed.first_name, closed.last_name, closed.registration_origin,
                              closed.first_email_verified_at, closed.last_login), ("", "", None, None, None))
            self.assertFalse(EmailAddress.objects.filter(user=closed).exists())
            self.assertFalse(AccountEmailDelivery.objects.filter(address__user=closed).exists())
            self.assertFalse(UserSession.objects.filter(pk=tracked.pk).exists())
            self.assertFalse(Authenticator.objects.filter(user=closed).exists())
            self.assertTrue(AutomaticTrialEligibility.objects.filter(user=closed).exists())
            self.assertTrue(self.project.__class__.objects.filter(pk=self.project.pk).exists())
            self.assertEqual(self.other_org.__class__.objects.get(pk=self.other_org.pk).name, self.other_org.name)
            retained = list(RetainedTrialIdentity.objects.all())
            self.assertEqual(len(retained), 2)
            self.assertTrue(all(row.expires_at == closed.identity_erased_at + timedelta(days=10) for row in retained))
            self.assertNotIn(original_email, str([row.__dict__ for row in retained]))
            self.assertNotIn(policy["PERSONAL_IDENTITY_RETENTION_KEY"], str([row.__dict__ for row in retained]))
            for email, expected in ((original_email.upper(), TrialState.PENDING_REVIEW),
                                    (alternate.email, TrialState.PENDING_REVIEW),
                                    ("unverified-victim@example.invalid", TrialState.ACTIVE)):
                new = get_user_model().objects.create_user(email, password="fixture-password")
                EmailAddress.objects.create(user=new, email=new.email, verified=True, primary=True)
                self.assertEqual(create_organization(user=new, name="New registration").trial.state, expected)
            self.assertEqual(erase_closed_account_identity(request=request, user_id=closed.pk,
                             policy_reference="fixture-policy-v1").identity_erased_at, closed.identity_erased_at)
            self.assertEqual(AuditEvent.objects.filter(subject_user=closed,
                             details__state="account_identity_erased").count(), 1)
            closed.email = original_email
            with self.assertRaises(ValidationError):
                closed.save(update_fields=["email"])

    @patch("tenancy.services.did_recently_authenticate", return_value=True)
    def test_identity_cleanup_policy_authority_and_audit_failures_preserve_original_identity(self, _reauth):
        from django.test import override_settings
        from .closure import erase_closed_account_identity
        from .models import RetainedTrialIdentity
        from .staff_access import require_staff_permissions
        _, request = self._staff_cleanup_request()
        original_email = self.owner.email
        policy = dict(PERSONAL_IDENTITY_ERASURE_POLICY_REFERENCE="fixture-policy-v1",
                      PERSONAL_IDENTITY_TRIAL_RETENTION_DAYS=10, PERSONAL_IDENTITY_RETENTION_KEY="fixture-key-" * 4)
        with override_settings(**policy):
            with self.assertRaises(ValidationError):
                erase_closed_account_identity(request=request, user_id=self.owner.pk, policy_reference="fixture-policy-v1")
            Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
            close_personal_access(actor=self.owner, request=self.request)
            for changes in ({"PERSONAL_IDENTITY_ERASURE_POLICY_REFERENCE": ""},
                            {"PERSONAL_IDENTITY_TRIAL_RETENTION_DAYS": 0},
                            {"PERSONAL_IDENTITY_RETENTION_KEY": ""}):
                with override_settings(**changes), self.assertRaises(ValidationError):
                    erase_closed_account_identity(request=request, user_id=self.owner.pk, policy_reference="fixture-policy-v1")
            with self.assertRaises(ValidationError):
                erase_closed_account_identity(request=request, user_id=True, policy_reference="fixture-policy-v1")
            with self.assertRaises(ValidationError):
                erase_closed_account_identity(request=request, user_id=self.owner.pk, policy_reference="old-policy")
            with patch("accounts.closure.AuditEvent.objects.create", side_effect=RuntimeError("audit unavailable")):
                with self.assertRaises(RuntimeError):
                    erase_closed_account_identity(request=request, user_id=self.owner.pk, policy_reference="fixture-policy-v1")
            original_create = AuditEvent.objects.create
            def revoke_after_audit(*args, **kwargs):
                result = original_create(*args, **kwargs)
                get_user_model().objects.filter(pk=self.staff.pk).update(is_active=False)
                return result
            with patch("accounts.closure.AuditEvent.objects.create", side_effect=revoke_after_audit), self.assertRaises(PermissionDenied):
                erase_closed_account_identity(request=request, user_id=self.owner.pk, policy_reference="fixture-policy-v1")
            self.owner.refresh_from_db()
            self.assertEqual(self.owner.email, original_email)
            self.assertIsNone(self.owner.identity_erased_at)
            self.assertTrue(EmailAddress.objects.filter(user=self.owner, email=original_email).exists())
            self.assertFalse(RetainedTrialIdentity.objects.exists())
            require_staff_permissions(request, permissions=("accounts.change_user",))
            session = request.session
            session.flush()
            with self.assertRaises(PermissionDenied):
                erase_closed_account_identity(request=request, user_id=self.owner.pk, policy_reference="fixture-policy-v1")

    @patch("tenancy.services.did_recently_authenticate", return_value=True)
    def test_exact_staff_cleanup_csrf_and_expired_fingerprints_do_not_affect_customer_data(self, _reauth):
        from urllib.parse import urlencode
        from django.db import IntegrityError, transaction
        from django.test import override_settings
        from .models import RetainedTrialIdentity
        from .tasks import purge_retained_trial_identities_task
        from tenancy.models import TrialState
        original_email = self.owner.email
        client, _ = self._staff_cleanup_request()
        url = "/admin/accounts/user/identity-cleanup/"
        with override_settings(SECURE_SSL_REDIRECT=False, PERSONAL_IDENTITY_ERASURE_POLICY_REFERENCE="fixture-policy-v1",
                PERSONAL_IDENTITY_TRIAL_RETENTION_DAYS=10, PERSONAL_IDENTITY_RETENTION_KEY="fixture-key-" * 4):
            client.get(url, secure=True)
            form = {"user_id": self.owner.pk, "policy_reference": "fixture-policy-v1",
                    "acknowledge_account_only_cleanup": "on"}
            self.assertEqual(client.post(url, form, secure=True).status_code, 403)
            headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value, "HTTP_REFERER": "https://testserver/"}
            form["csrfmiddlewaretoken"] = client.cookies["csrftoken"].value
            headers["content_type"] = "application/x-www-form-urlencoded"
            self.assertEqual(client.post(url, urlencode(form), secure=True, **headers).status_code, 409)
            Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
            close_personal_access(actor=self.owner, request=self.request)
            self.assertEqual(client.post(url, urlencode({**form, "extra": "denied"}), secure=True, **headers).status_code, 409)
            response = client.post(url, urlencode(form), secure=True, **headers)
            self.assertEqual(response.status_code, 200, response.context_data.get("error"))
            self.assertTrue({"private", "no-store"}.issubset(set(response["Cache-Control"].split(", "))))
            retained = RetainedTrialIdentity.objects.get()
            new = get_user_model().objects.create_user(original_email, password="fixture-password")
            EmailAddress.objects.create(user=new, email=new.email, primary=True, verified=True)
            with override_settings(PERSONAL_IDENTITY_RETENTION_KEY="changed-key-" * 4), self.assertRaises(ValidationError):
                create_organization(user=new, name="Must not bypass changed key")
            self.assertFalse(Organization.objects.filter(name="Must not bypass changed key").exists())
            with override_settings(PERSONAL_IDENTITY_RETENTION_KEY=""), self.assertRaises(ValidationError):
                create_organization(user=new, name="Must not bypass missing key")
            self.assertEqual(purge_retained_trial_identities_task.run(), 0)
            with patch("accounts.tasks.timezone.now", return_value=retained.expires_at):
                self.assertEqual(purge_retained_trial_identities_task.run(), 1)
            self.assertFalse(RetainedTrialIdentity.objects.exists())
            self.assertEqual(create_organization(user=new, name="After policy expiry").trial.state, TrialState.ACTIVE)
            self.assertTrue(self.project.__class__.objects.filter(pk=self.project.pk).exists())
            with transaction.atomic(), self.assertRaises(IntegrityError):
                # Database writes cannot restore a raw email into the erased shell.
                get_user_model().objects.filter(pk=self.owner.pk).update(email="restored@example.invalid")
