import copy
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

from accounts.closure import close_personal_access
from accounts.models import User
from . import staff_feedback_investigation as staff
from .email_feedback import is_email_suppressed, record_ses_feedback
from .models import AuditEvent, AuditEventType, EmailFeedbackReceipt, EmailSuppression


class StaffFeedbackInvestigationTests(TestCase):
    def setUp(self):
        self.target = User.objects.create_user("feedback-target@example.invalid", "fixture-password")
        self.other = User.objects.create_user("feedback-other@example.invalid", "fixture-password")
        self.address = EmailAddress.objects.create(user=self.target, email=self.target.email, primary=True, verified=True)
        self.staff = User.objects.create_user("feedback-inspector@example.invalid", "fixture-password", is_staff=True)
        self.permissions = [Permission.objects.get(content_type__app_label=app, codename=name) for app, name in (
            ("accounts", "view_user"), ("tenancy", "view_emailsuppression"), ("tenancy", "view_emailfeedbackreceipt"))]
        self.staff.user_permissions.add(*self.permissions)
        Authenticator.objects.create(user=self.staff, type=Authenticator.Type.TOTP, data={"secret": "unused-fixture"})
        self.client.force_login(self.staff)
        session = self.client.session
        session[AUTHENTICATION_METHODS_SESSION_KEY] = [{"method": "mfa", "at": timezone.now().timestamp()}]; session.save()
        self.request = RequestFactory().post("/admin/tenancy/emailsuppression/scoped/")
        self.request.user, self.request.session = self.staff, self.client.session
        self.event = ("sns-feedback-inspection-0001", "permanent_bounce", (self.address.email,))
        record_ses_feedback(self.event)
        self.row = EmailSuppression.objects.get()
        self.receipt = EmailFeedbackReceipt.objects.get()

    def inspect(self, **changes):
        return staff.inspect_staff_email_feedback(**{**dict(request=self.request, user_id=self.target.pk,
            email_address_id=self.address.pk, suppression_id=self.row.pk, reason="investigation"), **changes})

    def events(self):
        return AuditEvent.objects.filter(event_type=AuditEventType.STAFF_EMAIL_FEEDBACK_INSPECTED)

    def test_genuine_first_receipt_dates_duplicate_later_feedback_and_multiple_pending_records(self):
        first = self.inspect()
        self.assertEqual(first["suppression"], {"id": self.row.pk, "reason": "permanent_bounce", "created_at": self.row.created_at.isoformat()})
        self.assertEqual(first["feedback"], {"id": self.receipt.pk, "kind": "permanent_bounce", "received_at": self.receipt.received_at.isoformat()})
        record_ses_feedback(self.event)
        with self.assertRaises(ValidationError): record_ses_feedback((self.event[0], "complaint", self.event[2]))
        record_ses_feedback(("sns-feedback-inspection-0002", "complaint", self.event[2]))
        self.assertEqual(self.inspect(), first)
        self.assertEqual(EmailFeedbackReceipt.objects.count(), 2)
        self.assertEqual(EmailSuppression.objects.count(), 1)
        pending = EmailAddress.objects.create(user=self.other, email="pending-feedback@example.invalid", primary=False, verified=False)
        ambiguous = EmailAddress.objects.create(user=self.target, email=pending.email, primary=False, verified=False)
        record_ses_feedback(("sns-feedback-inspection-0003", "complaint", (pending.email,)))
        for address in (pending, ambiguous):
            row = EmailSuppression.objects.get(email_address=address)
            self.assertEqual(self.inspect(user_id=address.user_id, email_address_id=address.pk, suppression_id=row.pk)["feedback"]["kind"], "complaint")
        self.assertFalse(is_email_suppressed(pending.email))
        another = EmailAddress.objects.create(user=self.other, email=self.other.email, primary=True, verified=True)
        record_ses_feedback(("sns-feedback-inspection-0004", "permanent_bounce", (self.address.email, another.email)))
        later = EmailSuppression.objects.get(email_address=another)
        self.assertEqual(self.inspect(user_id=self.other.pk, email_address_id=another.pk, suppression_id=later.pk)["feedback"]["kind"], "permanent_bounce")
        self.assertEqual(self.inspect(), first)
        for event in self.events():
            self.assertIsNone(event.organization_id); self.assertIsNone(event.project_id)
            self.assertEqual(set(event.details), {"email_address_id", "suppression_id", "feedback_id", "reason", "kind"})

    def test_current_linkage_retained_suspension_personal_close_stale_digest_not_clearance(self):
        before = self.inspect()
        EmailAddress.objects.filter(pk=self.address.pk).update(email="changed-feedback@example.invalid", verified=False, primary=False)
        self.assertEqual(self.inspect(), before)
        User.objects.filter(pk=self.target.pk).update(is_active=False)
        self.assertNotEqual(self.inspect()["source_digest"], before["source_digest"])
        User.objects.filter(pk=self.target.pk).update(is_active=True)
        request = RequestFactory().post("/api/account/close/"); request.user = self.target
        with patch("tenancy.services.did_recently_authenticate", return_value=True): close_personal_access(actor=self.target, request=request)
        self.assertEqual(self.inspect()["suppression"], before["suppression"])
        EmailAddress.objects.filter(pk=self.address.pk).update(user=self.other)
        with self.assertRaises(PermissionDenied): self.inspect()
        moved = self.inspect(user_id=self.other.pk)
        self.assertEqual(moved["feedback"], before["feedback"])
        self.assertNotEqual(moved["source_digest"], before["source_digest"])

    def test_scalar_sql_privacy_audit_only_and_no_mail_provider_or_tenant_lookup(self):
        with CaptureQueriesContext(connection) as queries, patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch.object(DefaultAccountAdapter, "send_mail", side_effect=AssertionError("SMTP")), \
                patch("tenancy.email_feedback.clear_email_suppression", side_effect=AssertionError("clearance")):
            result = self.inspect()
        text = json.dumps(result) + json.dumps(self.events().get().details)
        for private in (self.target.email, self.event[0], self.row.address_digest, self.receipt.addresses_digest,
                        "password", "verified", "primary", "organization_id"):
            self.assertNotIn(private, text)
        for query in queries:
            sql = query["sql"]
            if sql.lstrip().upper().startswith("SELECT"):
                for table in ("tenancy_organization", "jobs_", "providers_", "integrations_"): self.assertNotIn(table, sql)
                if any(table in sql for table in ('FROM "tenancy_emailfeedbackreceipt"', 'FROM "tenancy_emailsuppression"', 'FROM "account_emailaddress"')):
                    for private in ('"email"', '"event_id"', '"verified"', '"primary"'): self.assertNotIn(private, sql)
                if 'FROM "accounts_user"' in sql and f'"accounts_user"."id" = {self.target.pk}' in sql:
                    self.assertNotIn('"email"', sql); self.assertNotIn('"password"', sql)
        writes = [query["sql"] for query in queries if query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
        self.assertEqual(len(writes), 1); self.assertIn("tenancy_auditevent", writes[0])
        self.assertTrue(EmailSuppression.objects.filter(pk=self.row.pk).exists())

    def test_exact_ids_triple_permissions_and_initial_current_staff_persisted_mfa(self):
        for changes in ({"user_id": self.other.pk}, {"email_address_id": self.address.pk + 99999}, {"suppression_id": self.row.pk + 99999}):
            with self.assertRaises(PermissionDenied): self.inspect(**changes)
        for changes in ({"user_id": True}, {"email_address_id": 0}, {"suppression_id": 2**53}, {"reason": []}, {"reason": "private prose"}):
            with self.assertRaises(ValidationError): self.inspect(**changes)
        for permission in self.permissions:
            self.staff.user_permissions.remove(permission)
            with patch("tenancy.staff_feedback_investigation._projection", side_effect=AssertionError("source before authority")), self.assertRaises(PermissionDenied): self.inspect()
            self.staff.user_permissions.add(permission)
        for mutate in (lambda: User.objects.filter(pk=self.staff.pk).update(is_active=False),
                lambda: User.objects.filter(pk=self.staff.pk).update(is_staff=False),
                lambda: Authenticator.objects.filter(user=self.staff).delete(),
                lambda: Session.objects.filter(session_key=self.request.session.session_key).delete()):
            with transaction.atomic():
                mutate()
                with patch("tenancy.staff_feedback_investigation._projection", side_effect=AssertionError("source before authority")), self.assertRaises(PermissionDenied): self.inspect()
                transaction.set_rollback(True)
        session = self.client.session; session[HASH_SESSION_KEY] = "invalid"; session.save()
        with self.assertRaises(PermissionDenied): self.inspect()
        session[HASH_SESSION_KEY] = self.staff.get_session_auth_hash()
        session[AUTHENTICATION_METHODS_SESSION_KEY] = [{"method": "password", "at": timezone.now().timestamp()}]; session.save()
        with self.assertRaises(PermissionDenied): self.inspect()
        self.assertFalse(self.events().exists())

    def test_post_audit_hidden_source_actor_session_loss_and_audit_failure_roll_back(self):
        create = AuditEvent.objects.create
        for mutate, error in ((lambda: self.staff.user_permissions.clear(), PermissionDenied),
                (lambda: Session.objects.filter(session_key=self.request.session.session_key).delete(), PermissionDenied),
                (lambda: User.objects.filter(pk=self.staff.pk).update(session_version="invalidated"), PermissionDenied),
                (lambda: EmailAddress.objects.filter(pk=self.address.pk).update(user=self.other), PermissionDenied),
                (lambda: User.objects.filter(pk=self.target.pk).update(is_active=False), ValidationError),
                (lambda: EmailSuppression.objects.filter(pk=self.row.pk).update(address_digest="b" * 64), ValidationError),
                (lambda: EmailFeedbackReceipt.objects.filter(pk=self.receipt.pk).update(addresses_digest="c" * 64), ValidationError),
                (lambda: EmailFeedbackReceipt.objects.filter(pk=self.receipt.pk).update(received_at=self.receipt.received_at - timedelta(microseconds=1)), ValidationError),
                (lambda: EmailSuppression.objects.filter(pk=self.row.pk).update(created_at=self.row.created_at + timedelta(microseconds=1)), ValidationError)):
            self.request.session = self.client.session
            def changed(**kwargs):
                result = create(**kwargs); mutate(); return result
            with patch("tenancy.staff_feedback_investigation.AuditEvent.objects.create", side_effect=changed), self.assertRaises(error): self.inspect()
            self.assertFalse(self.events().exists())
            self.assertEqual(EmailSuppression.objects.get(pk=self.row.pk).address_digest, self.row.address_digest)
        self.request.session = self.client.session
        with patch("tenancy.staff_feedback_investigation.AuditEvent.objects.create", side_effect=RuntimeError("audit unavailable")), self.assertRaises(RuntimeError): self.inspect()
        self.assertFalse(self.events().exists())

    def test_original_scalar_date_kind_digest_linkage_shapes_and_mid_projection_reread(self):
        original = staff._rows(self.target.pk, self.address.pk, self.row.pk)
        now = timezone.now()
        for bucket, changes in (("suppression", {"id": True}), ("feedback", {"id": 0}),
                ("address", {"user_id": self.other.pk}), ("suppression", {"email_address_id": self.address.pk + 1}),
                ("suppression", {"feedback_id": self.receipt.pk + 1}), ("feedback", {"kind": "complaint"}),
                ("suppression", {"reason": "private prose"}), ("suppression", {"address_digest": "A" * 64}),
                ("feedback", {"addresses_digest": []}), ("user", {"is_active": 1}),
                ("user", {"closed_at": now}), ("user", {"is_active": False, "closed_at": now + timedelta(days=1)}),
                ("feedback", {"received_at": None}), ("feedback", {"received_at": self.receipt.received_at.replace(tzinfo=None)}),
                ("suppression", {"created_at": now + timedelta(seconds=1)}),
                ("suppression", {"created_at": self.receipt.received_at - timedelta(microseconds=1)})):
            bad = copy.deepcopy(original); bad[bucket].update(changes)
            with self.assertRaises(ValidationError): staff._records(bad, now)
        project = staff._records
        def changed(rows, assessed):
            result = project(rows, assessed)
            EmailFeedbackReceipt.objects.filter(pk=self.receipt.pk).update(addresses_digest="d" * 64)
            return result
        with patch("tenancy.staff_feedback_investigation._records", side_effect=changed), self.assertRaises(ValidationError): self.inspect()
        self.assertFalse(self.events().exists())
