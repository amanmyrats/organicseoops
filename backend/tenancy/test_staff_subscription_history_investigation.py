import copy
import json
from datetime import timedelta
from unittest.mock import patch

from allauth.account.internal.flows.login import AUTHENTICATION_METHODS_SESSION_KEY
from allauth.mfa.models import Authenticator
from django.contrib.auth import HASH_SESSION_KEY, get_user_model
from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from . import staff_subscription_history_investigation as staff, test_paddle_reconcile as fixtures
from .models import AuditEvent, AuditEventType, Organization, PaddleSubscriptionHistory
from .paddle_jobs import execute_paddle_receipt
from .paddle_webhooks import record_paddle_notification
from .test_trial_corrections import staff_trial_request


@override_settings(**fixtures.SignedPaymentEvidenceTests._overridden_settings)
class StaffSubscriptionHistoryInvestigationTests(TestCase):
    provider_response = fixtures.SignedPaymentEvidenceTests.provider_response
    subscription_receipt = fixtures.SignedPaymentEvidenceTests.subscription_receipt
    subscription_response = fixtures.SignedPaymentEvidenceTests.subscription_response

    def setUp(self):
        fixtures.SignedPaymentEvidenceTests.setUp(self)
        self.inspector = get_user_model().objects.create_user("archive-inspector@example.invalid", "fixture-password", is_staff=True)
        self.permissions = Permission.objects.filter(content_type__app_label="tenancy", codename__in=["view_organization", "view_paddlesubscriptionhistory"])
        self.inspector.user_permissions.add(*self.permissions)
        self.request = staff_trial_request(self.inspector)

    def archive(self):
        fixtures.SignedPaymentEvidenceTests.test_fully_canceled_current_subscription_allows_new_paid_checkout_with_history(self)
        self.history = PaddleSubscriptionHistory.objects.get(organization=self.organization)
        return self.history

    def inspect(self, **changes):
        return staff.inspect_staff_subscription_history(**{**dict(request=self.request, organization_id=self.organization.pk,
            history_id=self.history.pk, reason="investigation"), **changes})

    def events(self):
        return AuditEvent.objects.filter(event_type=AuditEventType.STAFF_SUBSCRIPTION_HISTORY_INSPECTED)

    def test_genuine_recheckout_archive_late_signed_noop_and_late_adjustment_do_not_complete_history(self):
        self.archive()
        before = self.inspect()
        self.assertEqual((len(before["history"]), before["history"]["status"]), (8, "canceled"))
        raw = json.dumps({"event_id": "evt_" + "z" * 26, "notification_id": "ntf_" + "z" * 26,
            "event_type": "adjustment.updated", "occurred_at": fixtures.NOW.isoformat(), "data": {"id": "adj_" + "z" * 26}}).encode()
        receipt, _ = record_paddle_notification(environment="sandbox", raw_body=raw, signature=fixtures.header(raw), now=fixtures.NOW)
        response = {"data": [{"id": receipt.entity_id, "action": "refund", "status": "approved", "type": "full",
            "subscription_id": self.history.subscription_id, "customer_id": self.history.customer_id,
            "transaction_id": "txn_" + "c" * 26}], "meta": {"pagination": {"has_more": False}}}
        self.assertEqual(execute_paddle_receipt(receipt.pk, adjustment_get=lambda **_: response), "succeeded")
        self.assertEqual(self.inspect(), before)
        self.assertIsNone(before["history"]["refunded_at"])
        self.assertEqual(set(self.events().first().details), {"history_id", "reason", "status"})

    def test_genuine_foreign_history_does_not_grant_selected_org_authority(self):
        fixtures.SignedPaymentEvidenceTests.test_foreign_historical_customer_cannot_claim_current_paid_org(self)
        self.history = PaddleSubscriptionHistory.objects.get()
        with self.assertRaises(PermissionDenied): self.inspect()
        self.assertEqual(self.inspect(organization_id=self.history.organization_id)["history"]["id"], self.history.pk)

    def test_scalar_privacy_audit_only_retained_closed_old_other_environment(self):
        self.archive()
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=timezone.now())
        old = timezone.now() - timedelta(days=500)
        PaddleSubscriptionHistory.objects.filter(pk=self.history.pk).update(verified_at=old, canceled_at=old, archived_at=old)
        with override_settings(PADDLE_ENVIRONMENT="live"), CaptureQueriesContext(connection) as queries, \
                patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("django.core.mail.send_mail", side_effect=AssertionError("SMTP")), \
                patch("tenancy.billing_state.paid_access_state", side_effect=AssertionError("effective paid")):
            result = self.inspect()
        for private in (self.history.customer_id, self.history.subscription_id, self.owner.email, self.organization.name, "closed_at"):
            self.assertNotIn(private, json.dumps(result)); self.assertNotIn(private, json.dumps(self.events().get().details))
        for query in queries:
            self.assertFalse(any(table in query["sql"] for table in ("paddlewebhookreceipt", "paddlecheckout", '"tenancy_paddlesubscription"', "billingcancellation", "jobs_", "account_emailaddress")))
            if 'FROM "accounts_user"' in query["sql"]: self.assertIn(f'"accounts_user"."id" = {self.inspector.pk}', query["sql"])
        writes = [query["sql"] for query in queries if query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
        self.assertEqual(len(writes), 1); self.assertIn("tenancy_auditevent", writes[0])

    def test_exact_inputs_current_pair_hash_mfa_and_full_post_audit_rollback(self):
        self.archive()
        for changes, error in (({"organization_id": self.organization.pk + 99999}, PermissionDenied),
                ({"history_id": self.history.pk + 99999}, PermissionDenied), ({"history_id": True}, ValidationError),
                ({"history_id": 2**53}, ValidationError), ({"reason": "private prose"}, ValidationError)):
            with self.assertRaises(error): self.inspect(**changes)
        for permission in self.permissions:
            self.inspector.user_permissions.remove(permission)
            with patch.object(staff, "_source", side_effect=AssertionError("source before authority")), self.assertRaises(PermissionDenied): self.inspect()
            self.inspector.user_permissions.add(permission)
        session_key = self.request.session.session_key
        for key, value in ((HASH_SESSION_KEY, "invalid"), (AUTHENTICATION_METHODS_SESSION_KEY, [{"method": "password"}])):
            with transaction.atomic():
                self.request.session[key] = value; self.request.session.save()
                with self.assertRaises(PermissionDenied): self.inspect()
                transaction.set_rollback(True)
            self.request.session = type(self.request.session)(session_key=session_key)
        create = AuditEvent.objects.create
        mutations = [(lambda key=key, value=value: PaddleSubscriptionHistory.objects.filter(pk=self.history.pk).update(**{key: value}), ValidationError)
            for key, value in (("customer_id", "ctm_" + "z" * 26), ("subscription_id", "sub_" + "z" * 26), ("environment", "live"),
                ("verified_at", self.history.verified_at - timedelta(microseconds=1)), ("canceled_at", self.history.canceled_at - timedelta(microseconds=1)),
                ("archived_at", self.history.archived_at - timedelta(microseconds=1)), ("refunded_at", timezone.now()), ("disputed_at", timezone.now()))]
        mutations += [(lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True), ValidationError),
            (lambda: self.inspector.user_permissions.clear(), PermissionDenied),
            (lambda: Authenticator.objects.filter(user=self.inspector).delete(), PermissionDenied),
            (lambda: Session.objects.filter(session_key=session_key).delete(), PermissionDenied),
            (lambda: get_user_model().objects.filter(pk=self.inspector.pk).update(session_version="invalid"), PermissionDenied)]
        original = staff._source(self.organization.pk, self.history.pk)
        for mutate, error in mutations:
            def changed(**kwargs):
                event = create(**kwargs); mutate(); return event
            with patch.object(staff.AuditEvent.objects, "create", side_effect=changed), self.assertRaises(error): self.inspect()
            self.assertFalse(self.events().exists()); self.assertEqual(staff._source(self.organization.pk, self.history.pk), original)
            self.request.session = type(self.request.session)(session_key=session_key)
        with patch.object(staff.AuditEvent.objects, "create", side_effect=RuntimeError("audit unavailable")), self.assertRaises(RuntimeError): self.inspect()
        record = staff._record
        def changed(source, assessed):
            result = record(source, assessed)
            PaddleSubscriptionHistory.objects.filter(pk=self.history.pk).update(customer_id="ctm_" + "z" * 26)
            return result
        with patch.object(staff, "_record", side_effect=changed), self.assertRaises(ValidationError): self.inspect()
        self.assertFalse(self.events().exists())

    def test_archive_date_shapes_and_optional_provider_clock_are_not_local_order(self):
        self.archive()
        source = staff._source(self.organization.pk, self.history.pk); assessed = timezone.now()
        for key, value in (("status", "active"), ("environment", "unknown"), ("customer_id", "private"),
                ("verified_at", None), ("verified_at", self.history.archived_at + timedelta(microseconds=1)),
                ("canceled_at", None), ("canceled_at", self.history.archived_at + timedelta(microseconds=1)),
                ("archived_at", assessed + timedelta(microseconds=1)), ("refunded_at", assessed.replace(tzinfo=None))):
            invalid = copy.deepcopy(source); invalid["history"][key] = value
            with self.subTest(field=key), self.assertRaises(ValidationError): staff._record(invalid, assessed)
        future = copy.deepcopy(source)
        future["history"].update(refunded_at=assessed + timedelta(minutes=4), disputed_at=assessed + timedelta(minutes=4),
            verified_at=self.history.canceled_at - timedelta(seconds=1))
        self.assertIsNotNone(staff._record(future, assessed)["refunded_at"])
