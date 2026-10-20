import json
from datetime import timedelta
from unittest.mock import patch

from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.internal.flows.login import AUTHENTICATION_METHODS_SESSION_KEY
from allauth.account.models import EmailAddress
from allauth.mfa.models import Authenticator
from django.contrib.auth import HASH_SESSION_KEY
from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tenancy.email_feedback import record_ses_feedback
from tenancy.models import AuditEvent, AuditEventType
from . import staff_mail_investigation as staff
from .auth import AccountAdapter
from .closure import close_personal_access
from .models import AccountEmailDelivery, EmailDeliveryState, User


class StaffMailInvestigationTests(TestCase):
    def setUp(self):
        self.target = User.objects.create_user("mail-target@example.invalid", "fixture-password")
        self.other = User.objects.create_user("mail-other@example.invalid", "fixture-password")
        self.address = EmailAddress.objects.create(user=self.target, email=self.target.email, primary=True, verified=True)
        self.staff = User.objects.create_user("mail-inspector@example.invalid", "fixture-password", is_staff=True)
        self.permissions = Permission.objects.filter(content_type__app_label="accounts", codename__in=["view_user", "view_accountemaildelivery"])
        self.staff.user_permissions.add(*self.permissions)
        Authenticator.objects.create(user=self.staff, type=Authenticator.Type.TOTP, data={"secret": "unused-fixture"})
        self.client.force_login(self.staff)
        session = self.client.session
        session[AUTHENTICATION_METHODS_SESSION_KEY] = [{"method": "mfa", "at": timezone.now().timestamp()}]; session.save()
        self.request = RequestFactory().post("/admin/accounts/accountemaildelivery/scoped/")
        self.request.user, self.request.session = self.staff, self.client.session
        self.record = self.send()

    def send(self, **changes):
        with patch.object(DefaultAccountAdapter, "send_mail", **{**{"return_value": None}, **changes}):
            AccountAdapter().send_mail("account/email/password_reset_key", self.address.email, {"key": "private-token-marker"})
        return AccountEmailDelivery.objects.latest("pk")

    def inspect(self, **changes):
        return staff.inspect_staff_account_mail(**{**dict(request=self.request, user_id=self.target.pk,
            email_address_id=self.address.pk, delivery_id=self.record.pk, reason="investigation"), **changes})

    def events(self):
        return AuditEvent.objects.filter(event_type=AuditEventType.STAFF_ACCOUNT_MAIL_INSPECTED)

    def test_genuine_transport_unknown_suppressed_attempted_and_ambiguous_missing_records(self):
        result = self.inspect()
        self.assertEqual((len(result["delivery"]), result["delivery"]["state"]), (4, "transport_returned"))
        self.assertEqual(result["delivery"]["attempted_at"], self.record.attempted_at.isoformat())
        self.assertEqual(result["delivery"]["finished_at"], self.record.finished_at.isoformat())
        with self.assertRaises(OSError): self.send(side_effect=OSError("private-smtp-marker"))
        unknown = AccountEmailDelivery.objects.latest("pk")
        self.assertEqual(self.inspect(delivery_id=unknown.pk)["delivery"]["state"], "unknown")
        record_ses_feedback(("sns-mail-investigation-0001", "permanent_bounce", (self.address.email,)))
        with patch.object(DefaultAccountAdapter, "send_mail", side_effect=AssertionError("suppressed SMTP")):
            AccountAdapter().send_mail("account/email/password_reset_key", self.address.email, {})
        self.assertEqual(self.inspect(delivery_id=AccountEmailDelivery.objects.latest("pk").pk)["delivery"]["state"], "suppressed")
        EmailAddress.objects.filter(pk=self.address.pk).update(verified=False)
        with patch.object(DefaultAccountAdapter, "send_mail", side_effect=lambda *args: self.assertEqual(
                self.inspect(delivery_id=AccountEmailDelivery.objects.latest("pk").pk)["delivery"]["state"], "attempted")):
            AccountAdapter().send_mail("account/email/email_confirmation", self.address.email, {})
        EmailAddress.objects.create(user=self.other, email=self.address.email, verified=False)
        count = AccountEmailDelivery.objects.count()
        with patch.object(DefaultAccountAdapter, "send_mail") as sender:
            AccountAdapter().send_mail("account/email/email_confirmation", self.address.email, {})
            AccountAdapter().send_mail("account/email/unknown_account", "unknown@example.invalid", {})
        self.assertEqual(sender.call_count, 2)
        self.assertEqual(AccountEmailDelivery.objects.count(), count)
        self.assertEqual({event.subject_user_id for event in self.events()}, {self.target.pk})
        for event in self.events():
            self.assertIsNone(event.organization_id); self.assertIsNone(event.project_id)
            self.assertEqual(set(event.details), {"email_address_id", "delivery_id", "reason", "state"})

    def test_current_record_linkage_is_not_original_recipient_and_retained_personal_close_survives(self):
        before = self.inspect()
        EmailAddress.objects.filter(pk=self.address.pk).update(email="changed-mail@example.invalid", verified=False, primary=False)
        self.assertEqual(self.inspect(), before)
        User.objects.filter(pk=self.target.pk).update(is_active=False)
        suspended = self.inspect()
        self.assertNotEqual(suspended["source_digest"], before["source_digest"])
        User.objects.filter(pk=self.target.pk).update(is_active=True)
        request = RequestFactory().post("/api/account/close/"); request.user = self.target
        with patch("tenancy.services.did_recently_authenticate", return_value=True):
            closed = close_personal_access(actor=self.target, request=request)
        self.assertIsNotNone(closed.closed_at)
        self.assertEqual(self.inspect()["delivery"], before["delivery"])
        EmailAddress.objects.filter(pk=self.address.pk).update(user=self.other)
        with self.assertRaises(PermissionDenied): self.inspect()
        moved = self.inspect(user_id=self.other.pk)
        self.assertEqual(moved["delivery"], before["delivery"])
        self.assertEqual(moved["user_id"], self.other.pk)
        self.assertNotEqual(moved["source_digest"], before["source_digest"])

    def test_scalar_sql_privacy_and_audit_only_no_mail_network_or_tenant_lookup(self):
        AccountEmailDelivery.objects.filter(pk=self.record.pk).update(purpose="private-purpose-marker")
        with CaptureQueriesContext(connection) as queries, patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch.object(DefaultAccountAdapter, "send_mail", side_effect=AssertionError("SMTP")):
            result = self.inspect()
        for private in (self.target.email, "private-purpose-marker", "private-token-marker", "password", "verified", "primary", "organization_id"):
            self.assertNotIn(private, json.dumps(result)); self.assertNotIn(private, json.dumps(self.events().get().details))
        for query in queries:
            sql = query["sql"]
            if sql.lstrip().upper().startswith("SELECT"):
                self.assertNotIn("tenancy_", sql); self.assertNotIn("jobs_", sql); self.assertNotIn("providers_", sql)
                if 'FROM "accounts_accountemaildelivery"' in sql or 'FROM "account_emailaddress"' in sql:
                    for private in ('"email"', '"purpose"', '"verified"', '"primary"'): self.assertNotIn(private, sql)
                if 'FROM "accounts_user"' in sql and f'"accounts_user"."id" = {self.target.pk}' in sql:
                    self.assertNotIn('"email"', sql); self.assertNotIn('"password"', sql)
        writes = [query["sql"] for query in queries if query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
        self.assertEqual(len(writes), 1); self.assertIn("tenancy_auditevent", writes[0])

    def test_exact_ids_current_pair_session_and_post_audit_source_authority_loss_roll_back(self):
        for changes in ({"user_id": self.other.pk}, {"delivery_id": self.record.pk + 99999}, {"email_address_id": self.address.pk + 99999}):
            with self.assertRaises(PermissionDenied): self.inspect(**changes)
        for changes in ({"user_id": True}, {"email_address_id": 0}, {"delivery_id": 2**53}, {"reason": "private free text"}, {"reason": []}):
            with self.assertRaises(ValidationError): self.inspect(**changes)
        for permission in self.permissions:
            self.staff.user_permissions.remove(permission)
            with patch("accounts.staff_mail_investigation._projection", side_effect=AssertionError("source before authority")), self.assertRaises(PermissionDenied): self.inspect()
            self.staff.user_permissions.add(permission)
        create = AuditEvent.objects.create
        for mutate, error in ((lambda: self.staff.user_permissions.clear(), PermissionDenied),
                (lambda: Session.objects.filter(session_key=self.request.session.session_key).delete(), PermissionDenied),
                (lambda: User.objects.filter(pk=self.staff.pk).update(session_version="invalidated"), PermissionDenied),
                (lambda: EmailAddress.objects.filter(pk=self.address.pk).update(user=self.other), PermissionDenied),
                (lambda: User.objects.filter(pk=self.target.pk).update(is_active=False), ValidationError),
                (lambda: AccountEmailDelivery.objects.filter(pk=self.record.pk).update(attempted_at=self.record.attempted_at - timedelta(seconds=1)), ValidationError)):
            self.request.session = self.client.session
            def changed(**kwargs):
                result = create(**kwargs); mutate(); return result
            with patch("accounts.staff_mail_investigation.AuditEvent.objects.create", side_effect=changed), self.assertRaises(error): self.inspect()
            self.assertFalse(self.events().exists())
        self.request.session = self.client.session
        with patch("accounts.staff_mail_investigation.AuditEvent.objects.create", side_effect=RuntimeError("audit unavailable")), self.assertRaises(RuntimeError): self.inspect()
        self.assertFalse(self.events().exists())
        session = self.client.session; session[HASH_SESSION_KEY] = "invalid"; session.save()
        with self.assertRaises(PermissionDenied): self.inspect()

    def test_date_state_shape_and_complete_original_reread_fail_closed(self):
        row = AccountEmailDelivery.objects.filter(pk=self.record.pk).values(*staff.FIELDS).get()
        for changes in ({"state": "private error"}, {"id": True}, {"address_id": 0}, {"attempted_at": None},
                {"attempted_at": row["attempted_at"].replace(tzinfo=None)}, {"attempted_at": timezone.now() + timedelta(seconds=1)},
                {"finished_at": None}, {"finished_at": row["attempted_at"] - timedelta(microseconds=1)},
                {"finished_at": timezone.now() + timedelta(seconds=1)}, {"finished_at": row["finished_at"].replace(tzinfo=None)},
                {"state": EmailDeliveryState.ATTEMPTED}):
            with self.assertRaises(ValidationError): staff._delivery({**row, **changes}, timezone.now())
        original = staff._delivery
        def changed(row, assessed):
            result = original(row, assessed)
            AccountEmailDelivery.objects.filter(pk=row["id"]).update(attempted_at=row["attempted_at"] - timedelta(seconds=1))
            return result
        with patch("accounts.staff_mail_investigation._delivery", side_effect=changed), self.assertRaises(ValidationError): self.inspect()
        self.assertFalse(self.events().exists())
        with transaction.atomic():
            User.objects.filter(pk=self.target.pk).update(is_active=False, closed_at=timezone.now() + timedelta(days=1))
            with self.assertRaises(ValidationError): self.inspect()
            transaction.set_rollback(True)

    def test_initial_fresh_staff_totp_and_persisted_mfa_authority_is_independent_of_target(self):
        for mutate in (lambda: User.objects.filter(pk=self.staff.pk).update(is_active=False),
                lambda: User.objects.filter(pk=self.staff.pk).update(is_staff=False),
                lambda: Authenticator.objects.filter(user=self.staff).delete(),
                lambda: Session.objects.filter(session_key=self.request.session.session_key).delete()):
            with transaction.atomic():
                mutate()
                with patch("accounts.staff_mail_investigation._projection", side_effect=AssertionError("source before authority")), self.assertRaises(PermissionDenied): self.inspect()
                transaction.set_rollback(True)
        session = self.client.session
        session[AUTHENTICATION_METHODS_SESSION_KEY] = [{"method": "password", "at": timezone.now().timestamp()}]; session.save()
        with self.assertRaises(PermissionDenied): self.inspect()
        self.assertFalse(self.events().exists())
