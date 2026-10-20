import json
from datetime import timedelta
from unittest.mock import patch

from allauth.account.internal.flows.login import AUTHENTICATION_METHODS_SESSION_KEY
from allauth.account.models import EmailAddress
from allauth.mfa.models import Authenticator
from django.contrib.auth import HASH_SESSION_KEY, get_user_model
from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.test import Client, RequestFactory, TestCase, override_settings
from django.utils import timezone

from .models import AutomaticTrialEligibility, AuditEvent, AuditEventType, Organization, OrganizationTrial, PaddleSubscription, TrialState
from .services import approve_organization_trial, create_organization, extend_organization_trial
from . import services
from . import test_paddle_reconcile as paid_fixtures
from .paddle_reconcile import record_paid_checkout_receipt


def staff_trial_request(actor, browser=None):
    """Genuine persisted correction authority; other password-only fixtures stay unchanged."""
    Authenticator.objects.get_or_create(user=actor, type=Authenticator.Type.TOTP,
        defaults={"data": {"secret": "unused-fixture"}})
    if browser is None:
        browser = Client(); browser.force_login(actor)
    session = browser.session
    session[AUTHENTICATION_METHODS_SESSION_KEY] = [{"method": "mfa", "at": timezone.now().timestamp()}]
    session.save()
    request = RequestFactory().post("/api/platform/unused-trial-fixture/")
    request.user, request.session = actor, browser.session
    return request


@override_settings(STAFF_MFA_REQUIRED=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "trial-corrections"}})
class TrialCorrectionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = get_user_model().objects.create_user("correction-owner@example.invalid", "fixture-password")
        EmailAddress.objects.create(user=self.owner, email=self.owner.email, primary=True, verified=True)
        self.active = create_organization(user=self.owner, name="Synthetic active correction")
        self.pending = create_organization(user=self.owner, name="Synthetic pending correction")
        self.staff = get_user_model().objects.create_superuser("correction-staff@example.invalid", "fixture-password")
        self.browser = Client(enforce_csrf_checks=True); self.browser.force_login(self.staff)
        self.browser.get("/_allauth/browser/v1/auth/session")

    def post(self, organization, action, **changes):
        return self.browser.post(f"/api/platform/organizations/{organization.pk}/trial/{action}/",
            json.dumps({"reason": "Fixture reviewed trial correction", **changes}), content_type="application/json",
            HTTP_X_CSRFTOKEN=self.browser.cookies["csrftoken"].value, HTTP_REFERER="http://testserver/")

    def test_password_only_cannot_correct_trials_when_development_middleware_is_optional(self):
        for organization, action in ((self.pending, "approve"), (self.active, "extend")):
            with self.subTest(action=action):
                original = OrganizationTrial.objects.filter(organization=organization).values().get()
                self.assertEqual(self.post(organization, action).status_code, 403)
                self.assertEqual(OrganizationTrial.objects.filter(organization=organization).values().get(), original)
        self.assertFalse(AuditEvent.objects.filter(event_type__in=[AuditEventType.TRIAL_APPROVED, AuditEventType.TRIAL_EXTENDED]).exists())

    def assure(self):
        get_user_model().objects.filter(pk=self.staff.pk).update(is_superuser=False)
        self.staff.refresh_from_db()
        self.permission = Permission.objects.get(content_type__app_label="tenancy", codename="change_organizationtrial")
        self.staff.user_permissions.add(self.permission)
        self.request = staff_trial_request(self.staff, self.browser)

    def correct(self, organization, action, **changes):
        self.request.session = self.browser.session
        root = approve_organization_trial if action == "approve" else extend_organization_trial
        return root(**{**dict(organization=organization, actor=self.staff, request=self.request,
            reason="Fixture reviewed trial correction", request_id="fixture-trial-correction"), **changes})

    def test_genuine_change_only_mfa_csrf_and_policy_preserve_original_history(self):
        self.assure()
        for organization, action, event_type, days in ((self.pending, "approve", AuditEventType.TRIAL_APPROVED, 30),
                (self.active, "extend", AuditEventType.TRIAL_EXTENDED, 37)):
            original = OrganizationTrial.objects.get(organization=organization)
            denied = self.browser.post(f"/api/platform/organizations/{organization.pk}/trial/{action}/",
                json.dumps({"reason": "Reviewed"}), content_type="application/json")
            self.assertEqual(denied.status_code, 403)
            with override_settings(STAFF_MFA_REQUIRED=True), patch("socket.create_connection", side_effect=AssertionError("network")), \
                    patch("django.core.mail.send_mail", side_effect=AssertionError("SMTP")):
                response = self.post(organization, action)
            self.assertEqual(response.status_code, 200, response.content)
            self.assertIn("no-store", response["Cache-Control"])
            trial = OrganizationTrial.objects.get(pk=original.pk)
            self.assertEqual((trial.automatic_eligibility_id, trial.created_at, trial.offer_version,
                trial.project_limit, trial.member_limit, trial.unit_limit),
                (original.automatic_eligibility_id, original.created_at, original.offer_version, 1, 3, 40))
            self.assertEqual(trial.ends_at, trial.started_at + timedelta(days=days))
            if action == "extend": self.assertEqual(trial.started_at, original.started_at)
            event = AuditEvent.objects.get(organization=organization, event_type=event_type)
            self.assertEqual(event.actor_id, self.staff.pk)
            self.assertEqual(event.details["reason"], "Fixture reviewed trial correction")
            self.assertEqual(event.details["after"]["ends_at"], trial.ends_at.isoformat())
            self.assertEqual(self.post(organization, action).status_code, 409)

    def test_direct_roots_require_matching_actor_current_permission_factor_and_persisted_session(self):
        self.assure()
        for organization, action in ((self.pending, "approve"), (self.active, "extend")):
            original = OrganizationTrial.objects.filter(organization=organization).values().get()
            with self.assertRaises(PermissionDenied): self.correct(organization, action, actor=self.owner)
            for change in (lambda: self.staff.user_permissions.clear(),
                    lambda: Authenticator.objects.filter(user=self.staff).delete(),
                    lambda: Session.objects.filter(session_key=self.request.session.session_key).delete(),
                    lambda: get_user_model().objects.filter(pk=self.staff.pk).update(is_active=False),
                    lambda: get_user_model().objects.filter(pk=self.staff.pk).update(is_staff=False),
                    lambda: get_user_model().objects.filter(pk=self.staff.pk).update(session_version="invalidated")):
                with transaction.atomic():
                    change()
                    with self.assertRaises(PermissionDenied): self.correct(organization, action)
                    transaction.set_rollback(True)
            for key, value in ((HASH_SESSION_KEY, "invalidated"), (AUTHENTICATION_METHODS_SESSION_KEY, [{"method": "password"}])):
                with transaction.atomic():
                    session = self.browser.session; session[key] = value; session.save()
                    with self.assertRaises(PermissionDenied): self.correct(organization, action)
                    transaction.set_rollback(True)
            self.assertEqual(OrganizationTrial.objects.filter(organization=organization).values().get(), original)

    def test_post_audit_complete_trial_lifecycle_and_actor_loss_roll_back_both_corrections(self):
        self.assure()
        audit = services._audit
        for organization, action in ((self.pending, "approve"), (self.active, "extend")):
            original = OrganizationTrial.objects.filter(organization=organization).values().get()
            for field, value in (("offer_version", "legacy-offer"), ("project_limit", 2), ("member_limit", 4), ("unit_limit", 41),
                    ("state", TrialState.EXPIRED), ("created_at", original["created_at"] - timedelta(microseconds=1)),
                    ("updated_at", original["updated_at"]), ("automatic_eligibility_id", None)):
                if field == "automatic_eligibility_id" and action == "approve": continue
                def changed(**kwargs):
                    event = audit(**kwargs)
                    OrganizationTrial.objects.filter(pk=original["id"]).update(**{field: value})
                    return event
                cache.clear()  # Each injected source loss must reach the correction, not exhaust its real budget.
                with self.subTest(action=action, field=field), patch("tenancy.services._audit", side_effect=changed):
                    self.assertEqual(self.post(organization, action).status_code, 409)
                self.assertEqual(OrganizationTrial.objects.filter(organization=organization).values().get(), original)
            for mutate, error in ((lambda: self.staff.user_permissions.clear(), PermissionDenied),
                    (lambda: Session.objects.filter(session_key=self.request.session.session_key).delete(), PermissionDenied),
                    (lambda: Authenticator.objects.filter(user=self.staff).delete(), PermissionDenied),
                    (lambda: get_user_model().objects.filter(pk=self.staff.pk).update(session_version="invalidated"), PermissionDenied),
                    (lambda: get_user_model().objects.filter(pk=self.staff.pk).update(is_staff=False), PermissionDenied),
                    (lambda: Organization.objects.filter(pk=organization.pk).update(is_suspended=True), ValidationError),
                    (lambda: Organization.objects.filter(pk=organization.pk).update(is_suspended=True, closed_at=timezone.now()), ValidationError),
                    (lambda: PaddleSubscription.objects.create(organization=organization, environment="sandbox", status="canceled",
                        customer_id="ctm_" + "a" * 26, subscription_id="sub_" + "b" * 26), ValidationError),
                    (lambda: OrganizationTrial.objects.filter(pk=original["id"]).update(
                        ends_at=OrganizationTrial.objects.get(pk=original["id"]).ends_at + timedelta(microseconds=1)), ValidationError),
                    (lambda: OrganizationTrial.objects.filter(pk=original["id"]).update(
                        started_at=OrganizationTrial.objects.get(pk=original["id"]).started_at + timedelta(microseconds=1)), ValidationError)):
                def changed(**kwargs):
                    event = audit(**kwargs); mutate(); return event
                with patch("tenancy.services._audit", side_effect=changed), self.assertRaises(error): self.correct(organization, action)
                self.assertEqual(OrganizationTrial.objects.filter(organization=organization).values().get(), original)
            with patch("tenancy.services._audit", side_effect=RuntimeError("audit unavailable")), self.assertRaises(RuntimeError):
                self.correct(organization, action)
        self.assertFalse(AuditEvent.objects.filter(event_type__in=[AuditEventType.TRIAL_APPROVED, AuditEventType.TRIAL_EXTENDED]).exists())

    def test_both_api_corrections_recheck_late_permission_and_share_existing_budget(self):
        self.assure()
        audit = services._audit
        def changed(**kwargs):
            event = audit(**kwargs); self.staff.user_permissions.clear(); return event
        for organization, action in ((self.pending, "approve"), (self.active, "extend")):
            with patch("tenancy.services._audit", side_effect=changed):
                response = self.post(organization, action)
            self.assertEqual(response.status_code, 403)
            self.assertNotIn(self.owner.email, response.content.decode())
        for index in range(8):
            organization, action = (self.pending, "approve") if index % 2 else (self.active, "extend")
            self.assertIn(self.post(organization, action).status_code, (200, 409))
        self.assertEqual(self.post(self.pending, "approve").status_code, 429)
        self.assertEqual(self.post(self.active, "extend").status_code, 429)

    def test_post_audit_original_eligibility_scalars_cannot_change(self):
        self.assure()
        trial = self.active.trial
        original = AutomaticTrialEligibility.objects.filter(pk=trial.automatic_eligibility_id).values().get()
        audit = services._audit
        for field, value in (("granted_at", original["granted_at"] + timedelta(microseconds=1)),
                ("offer_version", "legacy-offer"), ("organization_id", self.pending.pk), ("user_id", self.staff.pk)):
            def changed(**kwargs):
                event = audit(**kwargs)
                AutomaticTrialEligibility.objects.filter(pk=original["id"]).update(**{field: value})
                return event
            with self.subTest(field=field), patch("tenancy.services._audit", side_effect=changed), self.assertRaises(ValidationError):
                self.correct(self.active, "extend")
            self.assertEqual(AutomaticTrialEligibility.objects.filter(pk=original["id"]).values().get(), original)
            self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.TRIAL_EXTENDED).exists())

    def test_future_original_start_and_window_expiring_during_audit_fail_closed(self):
        self.assure()
        future = timezone.now() + timedelta(days=1)
        with transaction.atomic():
            OrganizationTrial.objects.filter(organization=self.active).update(started_at=future, ends_at=future + timedelta(days=30))
            self.assertEqual(self.post(self.active, "extend").status_code, 409)
            transaction.set_rollback(True)
        # Advance the clock only after the actual audit, crossing the exact half-open corrected end.
        audit = services._audit
        for organization, action in ((self.pending, "approve"), (self.active, "extend")):
            clock = timezone.now()
            initial = clock
            def changed(**kwargs):
                nonlocal clock
                event = audit(**kwargs)
                clock = OrganizationTrial.objects.get(organization=organization).ends_at
                return event
            with patch("django.utils.timezone.now", side_effect=lambda: clock), patch("tenancy.services._audit", side_effect=changed):
                self.assertEqual(self.post(organization, action).status_code, 409)
            self.assertGreater(clock, initial)
        self.assertFalse(AuditEvent.objects.filter(event_type__in=[AuditEventType.TRIAL_APPROVED, AuditEventType.TRIAL_EXTENDED]).exists())


@override_settings(**paid_fixtures.SignedPaymentEvidenceTests._overridden_settings)
class TrialPaidCorrectionTests(TestCase):
    setUp = paid_fixtures.SignedPaymentEvidenceTests.setUp
    provider_response = paid_fixtures.SignedPaymentEvidenceTests.provider_response

    def test_actual_signed_payment_after_trial_audit_rolls_back_extension_and_preserves_initial_paid_exclusion(self):
        request = staff_trial_request(self.staff)
        original = OrganizationTrial.objects.filter(organization=self.organization).values().get()
        audit = services._audit
        def paid(**kwargs):
            event = audit(**kwargs)
            record_paid_checkout_receipt(receipt=self.receipt, provider_response=self.provider_response())
            return event
        with patch("tenancy.services._audit", side_effect=paid), patch("socket.create_connection", side_effect=AssertionError("network")), \
                self.assertRaises(ValidationError):
            extend_organization_trial(organization=self.organization, actor=self.staff, reason="Reviewed", request=request)
        self.assertEqual(OrganizationTrial.objects.filter(organization=self.organization).values().get(), original)
        self.attempt.refresh_from_db(); self.assertIsNone(self.attempt.paid_verified_at)
        self.assertFalse(AuditEvent.objects.filter(event_type__in=[AuditEventType.TRIAL_EXTENDED, AuditEventType.BILLING_PAYMENT_VERIFIED]).exists())
        record_paid_checkout_receipt(receipt=self.receipt, provider_response=self.provider_response())
        with self.assertRaises(ValidationError):
            extend_organization_trial(organization=self.organization, actor=self.staff, reason="Reviewed", request=request)
        self.assertEqual(OrganizationTrial.objects.filter(organization=self.organization).values().get(), original)
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.BILLING_PAYMENT_VERIFIED).count(), 1)
