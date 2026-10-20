import json
from datetime import timedelta
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from .models import AuditEvent, AuditEventType, Organization, OrganizationMembership, OrganizationTrial, TrialState
from .services import active_trial_for_policy, approve_organization_trial, create_organization, extend_organization_trial
from . import trial_activation
from . import test_paddle_activation as activation_fixtures
from . import test_paddle_reconcile as paid_fixtures
from .test_trial_corrections import staff_trial_request


class OriginalTrialActivationTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("trial-source@example.invalid", "fixture-passphrase")
        EmailAddress.objects.create(user=self.owner, email=self.owner.email, primary=True, verified=True)
        self.staff = get_user_model().objects.create_superuser("trial-source-staff@example.invalid", "fixture-passphrase")
        self.organization = create_organization(user=self.owner, name="Synthetic original trial source")

    def inspect(self, **changes):
        return trial_activation.inspect_trial_activation(**{**dict(organization=self.organization, actor=self.owner), **changes})

    def test_genuine_automatic_original_dates_read_only_minimized_and_unchanged_by_extension_or_current_status(self):
        trial = OrganizationTrial.objects.get(organization=self.organization)
        with patch("socket.create_connection", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            result = self.inspect()
        self.assertEqual(result["state"], "recorded")
        activation = result["activation"]
        self.assertEqual(activation["activation_method"], "automatic")
        self.assertEqual(activation["started_at"], trial.started_at.isoformat())
        audit = AuditEvent.objects.get(organization=self.organization, event_type=AuditEventType.TRIAL_GRANTED)
        self.assertEqual(activation["audited_at"], audit.created_at.isoformat())
        self.assertRegex(activation["source_digest"], r"^[a-f0-9]{64}$")
        self.assertFalse(any(row["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"} for row in queries))
        self.assertNotRegex(json.dumps(result), "_id|reason|ends_at|unit_limit|example.invalid|Synthetic")
        extend_organization_trial(organization=self.organization, actor=self.staff, reason="Synthetic bounded extension", request=staff_trial_request(self.staff))
        self.assertEqual(self.inspect(), result)
        OrganizationTrial.objects.filter(pk=trial.pk).update(state=TrialState.READ_ONLY, unit_limit=99)
        self.assertEqual(self.inspect(), result)
        # A later ownership handoff changes current authority, not the original grant actor/date.
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
        OrganizationMembership.objects.create(organization=self.organization, user=self.staff, role="owner")
        self.assertEqual(self.inspect(actor=self.staff), result)
        with self.assertRaises(PermissionDenied): self.inspect()

    def test_actual_staff_approval_pending_legacy_and_later_original_actor_loss(self):
        later = create_organization(user=self.owner, name="Synthetic staff-approved trial")
        self.assertEqual(self.inspect(organization=later), {"method": trial_activation.METHOD, "state": "not_activated", "activation": None})
        approved = approve_organization_trial(organization=later, actor=self.staff, reason="Synthetic approval reason", request=staff_trial_request(self.staff))
        result = self.inspect(organization=later)
        self.assertEqual(result["activation"]["activation_method"], "staff_approved")
        self.assertEqual(result["activation"]["started_at"], approved.started_at.isoformat())
        extend_organization_trial(organization=later, actor=self.staff, reason="Synthetic extension", request=staff_trial_request(self.staff))
        get_user_model().objects.filter(pk=self.staff.pk).update(is_staff=False, is_superuser=False, is_active=False)
        self.assertEqual(self.inspect(organization=later), result)
        AuditEvent.objects.filter(organization=later, event_type=AuditEventType.TRIAL_APPROVED).delete()
        self.assertEqual(self.inspect(organization=later)["state"], "unknown")
        self.assertIsNone(self.inspect(organization=later)["activation"])
        missing = Organization.objects.create(name="Synthetic no-source organization")
        OrganizationMembership.objects.create(organization=missing, user=self.owner, role="owner")
        self.assertEqual(self.inspect(organization=missing)["state"], "unknown")
        self.assertFalse(OrganizationTrial.objects.filter(organization=missing).exists())

    def test_original_grant_start_offer_audit_and_foreign_source_tamper_fail_closed(self):
        trial = OrganizationTrial.objects.get(organization=self.organization)
        audit = AuditEvent.objects.get(organization=self.organization, event_type=AuditEventType.TRIAL_GRANTED)
        with self.assertRaises(PermissionDenied): self.inspect(organization=Organization.objects.create(name="Synthetic foreign"))
        for changed in ({"started_at": trial.started_at + timedelta(seconds=1)}, {"offer_version": "other-offer"}):
            OrganizationTrial.objects.filter(pk=trial.pk).update(**changed)
            with self.assertRaises(ValidationError): self.inspect()
            OrganizationTrial.objects.filter(pk=trial.pk).update(started_at=trial.started_at, offer_version=trial.offer_version)
        other_owner = get_user_model().objects.create_user("other-trial@example.invalid", "fixture-passphrase")
        EmailAddress.objects.create(user=other_owner, email=other_owner.email, primary=True, verified=True)
        other = create_organization(user=other_owner, name="Synthetic foreign eligibility")
        eligibility_id = other.trial.automatic_eligibility_id
        OrganizationTrial.objects.filter(organization=other).update(automatic_eligibility_id=None)
        OrganizationTrial.objects.filter(pk=trial.pk).update(automatic_eligibility_id=eligibility_id)
        with self.assertRaises(ValidationError): self.inspect()
        OrganizationTrial.objects.filter(pk=trial.pk).update(automatic_eligibility_id=trial.automatic_eligibility_id)
        for changed in ({"details": {}}, {"actor_id": self.staff.pk}, {"subject_user_id": None},
                        {"created_at": timezone.now() + timedelta(days=1)}):
            AuditEvent.objects.filter(pk=audit.pk).update(**changed)
            with self.assertRaises(ValidationError): self.inspect()
            AuditEvent.objects.filter(pk=audit.pk).update(details=audit.details, actor_id=audit.actor_id,
                subject_user_id=audit.subject_user_id, created_at=audit.created_at)
        AuditEvent.objects.create(organization=self.organization, event_type=AuditEventType.TRIAL_GRANTED,
            actor=self.owner, subject_user=self.owner, details=audit.details)
        with self.assertRaises(ValidationError): self.inspect()

    def test_actual_staff_original_audit_dates_and_source_or_owner_loss_during_read_deny(self):
        later = create_organization(user=self.owner, name="Synthetic approved integrity")
        approve_organization_trial(organization=later, actor=self.staff, reason="Synthetic original reason", request=staff_trial_request(self.staff))
        audit = AuditEvent.objects.get(organization=later, event_type=AuditEventType.TRIAL_APPROVED)
        original = audit.details
        for changed in ({"after": {**original["after"], "started_at": timezone.now().isoformat()}},
                        {"after": {**original["after"], "ends_at": timezone.now().isoformat()}},
                        {"before": {"state": "active"}}, {"reason": True}):
            AuditEvent.objects.filter(pk=audit.pk).update(details={**original, **changed})
            with self.assertRaises(ValidationError): self.inspect(organization=later)
        AuditEvent.objects.filter(pk=audit.pk).update(details=original)
        actual = trial_activation._trial_activation_history
        def revoke(organization):
            result = actual(organization)
            OrganizationMembership.objects.filter(organization=organization, user=self.owner).update(role="admin")
            return result
        with patch("tenancy.trial_activation._trial_activation_history", side_effect=revoke):
            with self.assertRaises(PermissionDenied): self.inspect(organization=later)
        def remove(organization):
            result = actual(organization)
            AuditEvent.objects.filter(organization=organization, event_type=AuditEventType.TRIAL_GRANTED).delete()
            return result
        with patch("tenancy.trial_activation._trial_activation_history", side_effect=remove):
            with self.assertRaises(PermissionDenied): self.inspect()


@override_settings(**paid_fixtures.SignedPaymentEvidenceTests._overridden_settings, DEBUG=True)
class OriginalTrialPaidTransitionTests(TestCase):
    setUp = paid_fixtures.SignedPaymentEvidenceTests.setUp
    provider_response = paid_fixtures.SignedPaymentEvidenceTests.provider_response
    subscription_receipt = paid_fixtures.SignedPaymentEvidenceTests.subscription_receipt
    subscription_response = paid_fixtures.SignedPaymentEvidenceTests.subscription_response
    current = activation_fixtures.PaidActivationSourceTests.current

    def test_actual_signed_paid_reconciliation_preserves_original_trial_not_current_end_or_paid_observation(self):
        before = trial_activation.inspect_trial_activation(organization=self.organization, actor=self.owner)
        self.current()
        self.assertIsNone(active_trial_for_policy(organization=self.organization))
        self.assertEqual(trial_activation.inspect_trial_activation(organization=self.organization, actor=self.owner), before)
        self.assertEqual(set(before["activation"]), {"activation_method", "offer_version", "started_at", "audited_at", "source_digest"})
