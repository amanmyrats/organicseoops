import copy
import json
from datetime import timedelta
from unittest.mock import patch

from allauth.account.internal.flows.login import AUTHENTICATION_METHODS_SESSION_KEY
from allauth.account.models import EmailAddress
from allauth.mfa.models import Authenticator
from django.contrib.auth import HASH_SESSION_KEY, get_user_model
from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from . import staff_trial_investigation as staff
from .models import AutomaticTrialEligibility, AuditEvent, AuditEventType, Organization, OrganizationTrial, PaddleSubscription
from .services import active_trial_for_policy, approve_organization_trial, create_organization, extend_organization_trial
from .test_trial_corrections import staff_trial_request


@override_settings(STAFF_MFA_REQUIRED=False)
class StaffTrialInvestigationTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("trial-source-owner@example.invalid", "fixture-password")
        EmailAddress.objects.create(user=self.owner, email=self.owner.email, primary=True, verified=True)
        with patch("django.utils.timezone.now", return_value=timezone.now() - timedelta(days=36)):
            self.organization = create_organization(user=self.owner, name="Synthetic trial source")
            self.pending = create_organization(user=self.owner, name="Synthetic pending trial source")
        self.trial = OrganizationTrial.objects.get(organization=self.organization)
        self.inspector = get_user_model().objects.create_user("trial-source-staff@example.invalid", "fixture-password", is_staff=True)
        self.permissions = Permission.objects.filter(content_type__app_label="tenancy",
            codename__in=["view_organization", "view_organizationtrial", "view_automatictrialeligibility"])
        self.inspector.user_permissions.add(*self.permissions)
        self.request = staff_trial_request(self.inspector)

    def inspect(self, **changes):
        return staff.inspect_staff_trial(**{**dict(request=self.request, organization_id=self.organization.pk,
            trial_id=self.trial.pk, reason="investigation"), **changes})

    def events(self):
        return AuditEvent.objects.filter(event_type=AuditEventType.STAFF_TRIAL_INSPECTED)

    def test_genuine_automatic_pending_approved_extended_and_natural_expiry_are_recorded_not_effective(self):
        initial = self.inspect()
        self.assertEqual(len(initial["trial"]), 10)
        self.assertEqual(initial["trial"]["state"], "active")
        pending_trial = OrganizationTrial.objects.get(organization=self.pending)
        pending = self.inspect(organization_id=self.pending.pk, trial_id=pending_trial.pk)
        self.assertEqual((pending["trial"]["state"], pending["trial"]["started_at"], pending["trial"]["ends_at"]), ("pending_review", None, None))
        self.inspector.user_permissions.add(Permission.objects.get(content_type__app_label="tenancy", codename="change_organizationtrial"))
        approved = approve_organization_trial(organization=self.pending, actor=self.inspector, request=self.request, reason="Fixture review")
        self.assertEqual(self.inspect(organization_id=self.pending.pk, trial_id=approved.pk)["trial"]["started_at"], approved.started_at.isoformat())
        extended = extend_organization_trial(organization=self.organization, actor=self.inspector, request=self.request, reason="Fixture review")
        observed = self.inspect()["trial"]
        self.assertEqual(observed["started_at"], initial["trial"]["started_at"])
        self.assertEqual(extended.ends_at - extended.started_at, timedelta(days=37))
        with patch("django.utils.timezone.now", return_value=extended.ends_at):
            self.assertIsNone(active_trial_for_policy(organization=self.organization))
            self.assertEqual(self.inspect()["trial"], observed)  # No producer rewrites ACTIVE on natural expiry.
        for event in self.events():
            self.assertIsNone(event.project_id); self.assertIsNone(event.subject_user_id)
            self.assertEqual(set(event.details), {"trial_id", "reason", "state"})

    def test_retained_suspended_closed_old_paid_and_legacy_policy_do_not_confer_access_or_history(self):
        original = self.inspect()["trial"]
        PaddleSubscription.objects.create(organization=self.organization, environment="sandbox", status="canceled",
            customer_id="ctm_" + "a" * 26, subscription_id="sub_" + "b" * 26)
        self.assertIsNone(active_trial_for_policy(organization=self.organization))
        self.assertEqual(self.inspect()["trial"], original)
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=timezone.now())
        self.assertEqual(self.inspect()["trial"], original)
        old_owner = get_user_model().objects.create_user("old-trial-owner@example.invalid", "fixture-password")
        EmailAddress.objects.create(user=old_owner, email=old_owner.email, primary=True, verified=True)
        with patch("django.utils.timezone.now", return_value=timezone.now() - timedelta(days=500)):
            old_org = create_organization(user=old_owner, name="Synthetic old retained trial")
        self.assertEqual(self.inspect(organization_id=old_org.pk, trial_id=old_org.trial.pk)["trial"]["state"], "active")
        OrganizationTrial.objects.filter(pk=self.trial.pk).update(offer_version="legacy-trial-v0", project_limit=2, unit_limit=41)
        AutomaticTrialEligibility.objects.filter(pk=self.trial.automatic_eligibility_id).update(offer_version="legacy-trial-v0")
        recorded = self.inspect()["trial"]
        self.assertEqual((recorded["offer_version"], recorded["project_limit"], recorded["unit_limit"]), ("legacy-trial-v0", 2, 41))

    def test_scalar_privacy_sql_audit_only_no_paid_usage_history_provider_correction_or_mail(self):
        with CaptureQueriesContext(connection) as queries, patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("django.core.mail.send_mail", side_effect=AssertionError("SMTP")), \
                patch("tenancy.services.approve_organization_trial", side_effect=AssertionError("correction")):
            result = self.inspect()
        for private in (self.owner.email, self.organization.name, "automatic_eligibility", "user_id", "closed_at", "is_suspended", '"remaining_units"', '"paid_active"'):
            self.assertNotIn(private, json.dumps(result)); self.assertNotIn(private, json.dumps(self.events().get().details))
        self.assertRegex(result["source_digest"], "^[a-f0-9]{64}$")
        for query in queries:
            self.assertFalse(any(table in query["sql"] for table in ("tenancy_paddle", "jobs_", "account_emailaddress")))
            if 'FROM "tenancy_organization"' in query["sql"]: self.assertNotIn('"name"', query["sql"])
            if 'FROM "accounts_user"' in query["sql"]: self.assertIn(f'"accounts_user"."id" = {self.inspector.pk}', query["sql"])
        writes = [query["sql"] for query in queries if query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
        self.assertEqual(len(writes), 1); self.assertIn("tenancy_auditevent", writes[0])

    def test_exact_scope_separate_current_permissions_factor_session_hash_and_inputs(self):
        for changes in ({"organization_id": self.pending.pk}, {"trial_id": self.trial.pk + 999999}):
            with self.assertRaises(PermissionDenied): self.inspect(**changes)
        for changes in ({"organization_id": True}, {"trial_id": 0}, {"trial_id": 2**53}, {"reason": "private prose"}, {"reason": []}):
            with self.assertRaises(ValidationError): self.inspect(**changes)
        for permission in self.permissions:
            self.inspector.user_permissions.remove(permission)
            with patch.object(staff, "_source", side_effect=AssertionError("source before authority")), self.assertRaises(PermissionDenied): self.inspect()
            self.inspector.user_permissions.add(permission)
        for mutate in (lambda: Authenticator.objects.filter(user=self.inspector).delete(),
                lambda: Session.objects.filter(session_key=self.request.session.session_key).delete(),
                lambda: get_user_model().objects.filter(pk=self.inspector.pk).update(is_active=False)):
            with transaction.atomic():
                mutate()
                with self.assertRaises(PermissionDenied): self.inspect()
                transaction.set_rollback(True)
        for key, value in ((HASH_SESSION_KEY, "invalidated"), (AUTHENTICATION_METHODS_SESSION_KEY, [{"method": "password"}])):
            with transaction.atomic():
                session = self.request.session; session[key] = value; session.save()
                with self.assertRaises(PermissionDenied): self.inspect()
                transaction.set_rollback(True)
                self.request.session = type(session)(session_key=session.session_key)
        self.assertFalse(self.events().exists())

    def test_full_original_hidden_source_and_current_authority_after_audit_and_selection_roll_back(self):
        create = AuditEvent.objects.create
        eligibility_id = self.trial.automatic_eligibility_id
        session_key = self.request.session.session_key
        mutations = [(lambda key=key, value=value: OrganizationTrial.objects.filter(pk=self.trial.pk).update(**{key: value}), ValidationError)
            for key, value in (("state", "read_only"), ("offer_version", "legacy-trial"), ("project_limit", 2),
                ("member_limit", 4), ("unit_limit", 41), ("ends_at", self.trial.ends_at + timedelta(microseconds=1)),
                ("created_at", self.trial.created_at + timedelta(microseconds=1)),
                ("started_at", self.trial.started_at + timedelta(microseconds=1)))]
        mutations += [(lambda key=key, value=value: AutomaticTrialEligibility.objects.filter(pk=eligibility_id).update(**{key: value}), ValidationError)
            for key, value in (("organization_id", self.pending.pk), ("offer_version", "legacy-trial"),
                ("granted_at", self.trial.started_at + timedelta(microseconds=1)))]
        mutations += [(lambda: OrganizationTrial.objects.filter(pk=self.trial.pk).update(unit_limit=41), ValidationError),
                (lambda: OrganizationTrial.objects.filter(pk=self.trial.pk).update(updated_at=self.trial.updated_at + timedelta(microseconds=1)), ValidationError),
                (lambda: OrganizationTrial.objects.filter(pk=self.trial.pk).update(automatic_eligibility_id=None), ValidationError),
                (lambda: AutomaticTrialEligibility.objects.filter(pk=eligibility_id).update(user_id=self.inspector.pk), ValidationError),
                (lambda: Organization.objects.filter(pk=self.organization.pk).update(created_at=self.organization.created_at - timedelta(microseconds=1)), ValidationError),
                (lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True), ValidationError),
                (lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=timezone.now()), ValidationError),
                (lambda: self.inspector.user_permissions.clear(), PermissionDenied),
                (lambda: Session.objects.filter(session_key=self.request.session.session_key).delete(), PermissionDenied),
                (lambda: Authenticator.objects.filter(user=self.inspector).delete(), PermissionDenied),
                (lambda: get_user_model().objects.filter(pk=self.inspector.pk).update(session_version="invalidated"), PermissionDenied)]
        for mutate, error in mutations:
            original = staff._source(self.organization.pk, self.trial.pk)
            def changed(**kwargs):
                event = create(**kwargs); mutate(); return event
            with patch.object(staff.AuditEvent.objects, "create", side_effect=changed), self.assertRaises(error): self.inspect()
            self.assertFalse(self.events().exists()); self.assertEqual(staff._source(self.organization.pk, self.trial.pk), original)
            self.request.session = type(self.request.session)(session_key=session_key)
        record = staff._record
        def changed(source, assessed):
            result = record(source, assessed)
            AutomaticTrialEligibility.objects.filter(pk=eligibility_id).update(user_id=self.inspector.pk)
            return result
        with patch.object(staff, "_record", side_effect=changed), self.assertRaises(ValidationError): self.inspect()
        with patch.object(staff.AuditEvent.objects, "create", side_effect=RuntimeError("audit unavailable")), self.assertRaises(RuntimeError): self.inspect()
        self.assertFalse(self.events().exists())

    def test_recorded_state_null_dates_limits_and_eligibility_corruption_fail_closed(self):
        source = staff._source(self.organization.pk, self.trial.pk)
        assessed = timezone.now()
        for key, value in (("state", "unclassified"), ("state", "pending_review"), ("started_at", None),
                ("started_at", assessed + timedelta(days=1)), ("ends_at", self.trial.started_at),
                ("created_at", self.trial.created_at.replace(tzinfo=None)), ("updated_at", assessed + timedelta(seconds=1)),
                ("offer_version", " "), ("project_limit", True), ("unit_limit", 0)):
            invalid = copy.deepcopy(source); invalid["trial"][key] = value
            with self.subTest(field=key), self.assertRaises(ValidationError): staff._record(invalid, assessed)
        for key, value in (("organization_id", self.pending.pk), ("offer_version", "other-offer"),
                ("granted_at", self.trial.started_at + timedelta(microseconds=1))):
            invalid = copy.deepcopy(source); invalid["eligibility"][key] = value
            with self.assertRaises(ValidationError): staff._record(invalid, assessed)
        for state in ("active", "expired", "read_only", "suspended"):
            self.assertEqual(staff._record({**source, "trial": {**source["trial"], "state": state}}, assessed)["state"], state)
