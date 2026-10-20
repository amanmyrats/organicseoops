import json
from datetime import timedelta
from unittest.mock import patch

from allauth.account.internal.flows.login import AUTHENTICATION_METHODS_SESSION_KEY
from allauth.account.models import EmailAddress
from allauth.mfa.models import Authenticator
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from . import staff_notice_investigation as staff, test_notices as fixtures
from .models import AuditEvent, AuditEventType, MembershipRole, Organization, OrganizationMembership, OrganizationNotice, OrganizationTrial, Project
from .notices import deliver_organization_notice, recover_organization_notices, requeue_unknown_organization_notice, reserve_due_trial_notices


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", FRONTEND_ORIGIN="https://app.example.invalid")
class StaffNoticeInvestigationTests(TestCase):
    def setUp(self):
        fixtures.TrialNoticeTests.setUp(self)
        self.staff = get_user_model().objects.create_user("notice-inspector@example.invalid", password="fixture-password", is_staff=True)
        self.permissions = Permission.objects.filter(content_type__app_label="tenancy",
            codename__in=["view_organization", "view_organizationnotice"])
        self.staff.user_permissions.add(*self.permissions)
        self.client.force_login(self.staff)
        Authenticator.objects.create(user=self.staff, type=Authenticator.Type.TOTP, data={"secret": "unused-fixture"})
        session = self.client.session
        session[AUTHENTICATION_METHODS_SESSION_KEY] = [{"method": "mfa", "at": timezone.now().timestamp()}]; session.save()
        self.request = RequestFactory().post("/admin/tenancy/organizationnotice/scoped/")
        self.request.user, self.request.session = self.staff, self.client.session
        self.notice_id = reserve_due_trial_notices()[0]
        self.other_org = Organization.objects.create(name="Other notice fixture")

    def inspect(self, **changes):
        return staff.inspect_staff_notice(**{**dict(request=self.request, organization_id=self.organization.pk,
            notice_id=self.notice_id, reason="investigation"), **changes})

    def events(self):
        return AuditEvent.objects.filter(event_type=AuditEventType.STAFF_NOTICE_INSPECTED)

    def test_genuine_queued_transport_unknown_skip_and_reissue_history_not_retry_eligibility(self):
        self.assertFalse(Project.objects.filter(organization=self.organization).exists())
        self.assertEqual(self.inspect()["notice"]["state"], "queued")
        with patch("tenancy.notices.send_mail", side_effect=OSError("private SMTP outcome")) as send:
            self.assertEqual(deliver_organization_notice(self.notice_id), "unknown")
            before = self.inspect()["notice"]
            self.assertEqual(before["state"], "unknown")
            self.assertEqual(deliver_organization_notice(self.notice_id), "unknown")
        send.assert_called_once()
        self.assertEqual(recover_organization_notices(), [])
        self.staff.user_permissions.add(Permission.objects.get(content_type__app_label="tenancy", codename="change_organizationnotice"))
        requeue_unknown_organization_notice(notice=OrganizationNotice.objects.get(pk=self.notice_id), actor=self.staff,
            reason="Fixture explicit possible duplicate review", request=self.request)
        reissued = self.inspect()["notice"]
        self.assertEqual((reissued["state"], reissued["manual_retries"], reissued["attempted_at"]), ("queued", 1, None))
        self.assertEqual(deliver_organization_notice(self.notice_id), "sent")
        result = self.inspect()["notice"]
        self.assertEqual((len(result), result["state"], result["manual_retries"]), (7, "sent", 1))
        self.assertEqual(len(mail.outbox), 1)
        other = get_user_model().objects.create_user("another-notice-owner@example.invalid", password="fixture-password")
        EmailAddress.objects.create(user=other, email=other.email, primary=True, verified=True)
        membership = OrganizationMembership.objects.create(organization=self.organization, user=other, role=MembershipRole.OWNER)
        notice_id = reserve_due_trial_notices()[0]
        membership.delete()
        self.assertEqual(deliver_organization_notice(notice_id), "skipped")
        self.assertEqual(self.inspect(notice_id=notice_id)["notice"]["state"], "skipped")
        for event in self.events():
            self.assertEqual((event.organization_id, event.project_id, event.actor_id), (self.organization.pk, None, self.staff.pk))
            self.assertEqual(set(event.details), {"notice_id", "reason", "state"})

    def test_scalar_privacy_audit_only_no_recipient_account_billing_or_feedback_lookup_or_mail(self):
        OrganizationNotice.objects.filter(pk=self.notice_id).update(error_category="private-provider-secret-marker")
        with CaptureQueriesContext(connection) as queries, patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("tenancy.notices.send_mail", side_effect=AssertionError("SMTP")), \
                patch("tenancy.notices.requeue_unknown_organization_notice", side_effect=AssertionError("reissue")), \
                patch("tenancy.notices.recover_organization_notices", side_effect=AssertionError("recovery")):
            result = self.inspect()
        for private in (self.owner.email, "private-provider-secret-marker", '"recipient_id"', '"trial_id"', '"project_id"', "retry_available"):
            self.assertNotIn(private, json.dumps(result)); self.assertNotIn(private, json.dumps(self.events().get().details))
        # Retained-scope SQL may join trial/subscription dates; it never selects their source/provider identities or payloads.
        self.assertFalse(any(field in query["sql"] for query in queries for field in (
            "error_category", "account_emailaddress", "accounts_accountemaildelivery", "tenancy_email", "paddlewebhookreceipt",
            '"name"', "customer_id", "subscription_id\" FROM", "event_id", "raw_digest", "encrypted", "jobs_")))
        # Shared staff assurance reads only the current staff user, never the notice recipient.
        for query in queries:
            if 'FROM "accounts_user"' in query["sql"]:
                self.assertIn(f'"accounts_user"."id" = {self.staff.pk}', query["sql"])
            if query["sql"].lstrip().upper().startswith("SELECT") and 'FROM "tenancy_organizationnotice"' in query["sql"]:
                self.assertNotIn('"email"', query["sql"])
        writes = [query["sql"] for query in queries if query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
        self.assertEqual(len(writes), 1); self.assertIn("tenancy_auditevent", writes[0])

    def test_exact_org_scope_separate_current_permission_session_and_post_audit_hidden_loss_roll_back(self):
        for changes in ({"organization_id": self.other_org.pk}, {"notice_id": self.notice_id + 99999}):
            with self.assertRaises(PermissionDenied): self.inspect(**changes)
        for changes in ({"organization_id": True}, {"notice_id": 2**53}, {"notice_id": 0}, {"reason": "private free text"}):
            with self.assertRaises(ValidationError): self.inspect(**changes)
        for permission in self.permissions:
            self.staff.user_permissions.remove(permission)
            with patch("tenancy.staff_notice_investigation._projection", side_effect=AssertionError("source before authority")), self.assertRaises(PermissionDenied): self.inspect()
            self.staff.user_permissions.add(permission)
        alternate = get_user_model().objects.create_user("alternate-notice-recipient@example.invalid", password="fixture-password")
        create = AuditEvent.objects.create
        for mutate, error in ((lambda: self.staff.user_permissions.clear(), PermissionDenied),
                (lambda: Session.objects.filter(session_key=self.request.session.session_key).delete(), PermissionDenied),
                (lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True), PermissionDenied),
                (lambda: OrganizationNotice.objects.filter(pk=self.notice_id).update(recipient_id=alternate.pk), ValidationError),
                (lambda: OrganizationNotice.objects.filter(pk=self.notice_id).update(manual_retries=1), ValidationError)):
            self.request.session = self.client.session
            def changed(**kwargs):
                result = create(**kwargs); mutate(); return result
            with patch("tenancy.staff_notice_investigation.AuditEvent.objects.create", side_effect=changed), self.assertRaises(error): self.inspect()
            self.assertFalse(self.events().exists())
        self.request.session = self.client.session
        with patch("tenancy.staff_notice_investigation.AuditEvent.objects.create", side_effect=RuntimeError("audit unavailable")), self.assertRaises(RuntimeError): self.inspect()
        self.assertFalse(self.events().exists())

    def test_original_dates_source_shape_retry_bounds_and_selection_reread(self):
        row = OrganizationNotice.objects.filter(pk=self.notice_id).values(*staff.FIELDS).get()
        for changes in ({"kind": "private free text"}, {"state": "private error"}, {"manual_retries": True}, {"manual_retries": 2},
                {"created_at": timezone.now() + timedelta(seconds=1)}, {"created_at": row["created_at"].replace(tzinfo=None)},
                {"attempted_at": timezone.now()}, {"sent_at": timezone.now()}, {"trial_id": None}, {"source_receipt_id": 123},
                {"trial_ends_at": None}, {"trial_ends_at": row["trial_ends_at"].replace(tzinfo=None)}):
            with self.assertRaises(ValidationError): staff._notice({**row, **changes}, timezone.now())
        attempted = {**row, "state": "sending", "attempted_at": row["created_at"]}
        self.assertEqual(staff._notice(attempted, timezone.now())["state"], "sending")
        for changes in ({"attempted_at": row["created_at"] - timedelta(microseconds=1)}, {"attempted_at": timezone.now() + timedelta(seconds=1)},
                {"state": "sent", "sent_at": row["created_at"] - timedelta(microseconds=1)}):
            with self.assertRaises(ValidationError): staff._notice({**attempted, **changes}, timezone.now())
        original = staff._notice
        def changed(row, assessed):
            result = original(row, assessed)
            OrganizationNotice.objects.filter(pk=row["id"]).update(manual_retries=1)
            return result
        with patch("tenancy.staff_notice_investigation._notice", side_effect=changed), self.assertRaises(ValidationError): self.inspect()
        self.assertFalse(self.events().exists())

    def test_retained_history_survives_original_recipient_or_trial_loss_but_closed_expired_scope_denies(self):
        self.membership.delete()
        EmailAddress.objects.filter(user=self.owner).update(verified=False)
        self.assertEqual(self.inspect()["notice"]["state"], "queued")
        now = timezone.now()
        OrganizationTrial.objects.filter(pk=self.trial.pk).update(started_at=now - timedelta(days=31), ends_at=now - timedelta(days=1))
        self.assertEqual(self.inspect()["notice"]["state"], "queued")
        with transaction.atomic():
            Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=now)
            with self.assertRaises(PermissionDenied): self.inspect()
            transaction.set_rollback(True)
        OrganizationTrial.objects.filter(pk=self.trial.pk).update(started_at=now - timedelta(days=121), ends_at=now - timedelta(days=91))
        with self.assertRaises(PermissionDenied): self.inspect()
