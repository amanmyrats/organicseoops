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
from django.test import Client, RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from . import staff_subscription_investigation as staff, test_paddle_reconcile as fixtures
from .models import AuditEvent, AuditEventType, Organization, PaddleSubscription
from .paddle_jobs import execute_paddle_receipt
from .paddle_cancellation import execute_billing_cancellation, prepare_billing_cancellation
from .closure import close_organization_locally
from .test_trial_corrections import staff_trial_request


@override_settings(**fixtures.SignedPaymentEvidenceTests._overridden_settings)
class StaffSubscriptionInvestigationTests(TestCase):
    provider_response = fixtures.SignedPaymentEvidenceTests.provider_response
    subscription_receipt = fixtures.SignedPaymentEvidenceTests.subscription_receipt
    subscription_response = fixtures.SignedPaymentEvidenceTests.subscription_response

    def setUp(self):
        fixtures.SignedPaymentEvidenceTests.setUp(self)
        self.inspector = get_user_model().objects.create_user("subscription-inspector@example.invalid", "fixture-password", is_staff=True)
        self.permissions = Permission.objects.filter(content_type__app_label="tenancy", codename__in=["view_organization", "view_paddlesubscription"])
        self.inspector.user_permissions.add(*self.permissions)
        self.request = staff_trial_request(self.inspector)

    def current(self):
        self.assertEqual(execute_paddle_receipt(self.receipt.pk, transaction_get=lambda **_: self.provider_response()), "succeeded")
        self.assertEqual(execute_paddle_receipt(self.subscription_receipt().pk, subscription_get=lambda **_: self.subscription_response()), "succeeded")
        self.subscription = PaddleSubscription.objects.get(organization=self.organization)
        return self.subscription

    def inspect(self, **changes):
        return staff.inspect_staff_subscription(**{**dict(request=self.request, organization_id=self.organization.pk,
            subscription_id=PaddleSubscription.objects.get(organization=self.organization).pk, reason="investigation"), **changes})

    def events(self):
        return AuditEvent.objects.filter(event_type=AuditEventType.STAFF_SUBSCRIPTION_INSPECTED)

    def test_genuine_signed_worker_renewal_recovery_keeps_recorded_anchor_not_current_access(self):
        fixtures.SignedPaymentEvidenceTests.test_signed_renewal_failure_and_recovery_use_current_provider_state(self)
        row = self.inspect()["subscription"]
        self.assertEqual((len(row), row["status"]), (12, "active"))
        self.assertIsNone(row["failed_at"])
        # The genuine producer's final new period is in the future; observation preserves it.
        self.assertGreater(row["period_starts_at"], timezone.now().isoformat())
        self.assertEqual(set(self.events().get().details), {"subscription_id", "reason", "status"})

    def test_genuine_adverse_hold_refund_and_same_pk_replacement_are_not_lifetime_identity_or_paid_truth(self):
        fixtures.SignedPaymentEvidenceTests.test_signed_adverse_receipt_holds_paid_work_even_after_provider_outage_exhausts_retries(self)
        row = self.inspect()["subscription"]
        self.assertEqual(row["status"], "active"); self.assertIsNotNone(row["refunded_at"])
        self.assertNotIn("paid_active", row)

    def test_genuine_recheckout_replaces_identity_in_place_without_inspector_history_lookup(self):
        self.current()
        before = self.inspect()
        fixtures.SignedPaymentEvidenceTests.test_fully_canceled_current_subscription_allows_new_paid_checkout_with_history(self)
        after = self.inspect()
        self.assertEqual(before["subscription"]["id"], after["subscription"]["id"])
        self.assertNotEqual(before["source_digest"], after["source_digest"])

    def test_genuine_confirmed_closure_ledger_can_leave_linked_subscription_active(self):
        linked = self.current()
        attempt = prepare_billing_cancellation(organization=self.organization, actor=self.owner)
        browser = Client(); browser.force_login(self.owner)
        session = browser.session
        session[AUTHENTICATION_METHODS_SESSION_KEY] = [{"method": "password", "at": timezone.now().timestamp()}]; session.save()
        request = RequestFactory().post("/unused-fixture-closure/"); request.user, request.session = self.owner, browser.session
        close_organization_locally(organization=self.organization, actor=self.owner, request=request)
        result = execute_billing_cancellation(attempt, cancel=lambda **_: {"data": {
            "id": linked.subscription_id, "customer_id": linked.customer_id, "status": "canceled", "canceled_at": timezone.now().isoformat()}})
        self.assertEqual(result.state, "confirmed")
        observed = self.inspect()["subscription"]
        self.assertEqual(observed["status"], "active"); self.assertIsNone(observed["canceled_at"])

    def test_scalar_privacy_audit_only_retained_closed_other_environment_and_unknown_verification(self):
        linked = self.current()
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=timezone.now())
        with override_settings(PADDLE_ENVIRONMENT="live"), CaptureQueriesContext(connection) as queries, \
                patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("django.core.mail.send_mail", side_effect=AssertionError("SMTP")), \
                patch("tenancy.billing_state.paid_access_state", side_effect=AssertionError("effective access")):
            result = staff.inspect_staff_subscription(request=self.request, organization_id=self.organization.pk,
                subscription_id=linked.pk, reason="customer_request")
        for private in (linked.customer_id, linked.subscription_id, self.owner.email, self.organization.name, "currency_code", "closed_at"):
            self.assertNotIn(private, json.dumps(result)); self.assertNotIn(private, json.dumps(self.events().get().details))
        for query in queries:
            self.assertFalse(any(table in query["sql"] for table in ("paddlewebhookreceipt", "paddlecheckout", "paddlesubscriptionhistory", "billingcancellation", "jobs_", "account_emailaddress")))
            if 'FROM "accounts_user"' in query["sql"]: self.assertIn(f'"accounts_user"."id" = {self.inspector.pk}', query["sql"])
        writes = [query["sql"] for query in queries if query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
        self.assertEqual(len(writes), 1); self.assertIn("tenancy_auditevent", writes[0])
        unknown_org = Organization.objects.create(name="Synthetic unverified linked identity")
        unknown = PaddleSubscription.objects.create(organization=unknown_org, environment="sandbox", status="active",
            customer_id="ctm_" + "a" * 26, subscription_id="sub_" + "b" * 26)
        self.assertIsNone(self.inspect(organization_id=unknown_org.pk, subscription_id=unknown.pk)["subscription"]["verified_at"])

    def test_exact_inputs_current_pair_authority_and_complete_post_audit_source_session_rollback(self):
        linked = self.current()
        for changes, error in (({"organization_id": linked.organization_id + 99999}, PermissionDenied),
                ({"subscription_id": linked.pk + 99999}, PermissionDenied), ({"subscription_id": True}, ValidationError),
                ({"subscription_id": 2**53}, ValidationError), ({"reason": "private prose"}, ValidationError)):
            with self.assertRaises(error): self.inspect(**changes)
        for permission in self.permissions:
            self.inspector.user_permissions.remove(permission)
            with patch.object(staff, "_source", side_effect=AssertionError("source before authority")), self.assertRaises(PermissionDenied): self.inspect()
            self.inspector.user_permissions.add(permission)
        session_key = self.request.session.session_key
        for key, value in ((HASH_SESSION_KEY, "invalidated"), (AUTHENTICATION_METHODS_SESSION_KEY, [{"method": "password"}])):
            with transaction.atomic():
                session = self.request.session; session[key] = value; session.save()
                with self.assertRaises(PermissionDenied): self.inspect()
                transaction.set_rollback(True)
            self.request.session = type(self.request.session)(session_key=session_key)
        create = AuditEvent.objects.create
        mutations = [(lambda key=key, value=value: PaddleSubscription.objects.filter(pk=linked.pk).update(**{key: value}), ValidationError)
            for key, value in (("customer_id", "ctm_" + "z" * 26), ("subscription_id", "sub_" + "z" * 26),
                ("currency_code", "TRY"), ("environment", "live"), ("status", "past_due"),
                ("verified_at", linked.verified_at - timedelta(microseconds=1)),
                ("period_starts_at", linked.period_starts_at - timedelta(microseconds=1)),
                ("period_ends_at", linked.period_ends_at + timedelta(microseconds=1)),
                ("failed_at", timezone.now()), ("grace_usage_starts_at", linked.period_starts_at),
                ("scheduled_cancel_at", linked.period_ends_at), ("refunded_at", timezone.now()), ("disputed_at", timezone.now()))]
        mutations += [(lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True), ValidationError),
            (lambda: self.inspector.user_permissions.clear(), PermissionDenied),
            (lambda: Authenticator.objects.filter(user=self.inspector).delete(), PermissionDenied),
            (lambda: Session.objects.filter(session_key=session_key).delete(), PermissionDenied),
            (lambda: get_user_model().objects.filter(pk=self.inspector.pk).update(session_version="invalidated"), PermissionDenied)]
        original = staff._source(self.organization.pk, linked.pk)
        for mutate, error in mutations:
            def changed(**kwargs):
                event = create(**kwargs); mutate(); return event
            with patch.object(staff.AuditEvent.objects, "create", side_effect=changed), self.assertRaises(error): self.inspect()
            self.assertFalse(self.events().exists()); self.assertEqual(staff._source(self.organization.pk, linked.pk), original)
            self.request.session = type(self.request.session)(session_key=session_key)
        with patch.object(staff.AuditEvent.objects, "create", side_effect=RuntimeError("audit unavailable")), self.assertRaises(RuntimeError): self.inspect()
        record = staff._record
        def changed(source, assessed):
            result = record(source, assessed)
            PaddleSubscription.objects.filter(pk=linked.pk).update(currency_code="TRY")
            return result
        with patch.object(staff, "_record", side_effect=changed), self.assertRaises(ValidationError): self.inspect()
        self.assertFalse(self.events().exists())

    def test_recorded_shapes_local_verification_vs_future_provider_dates_and_recovered_anchor(self):
        linked = self.current()
        source = staff._source(self.organization.pk, linked.pk)
        assessed = timezone.now()
        for key, value in (("status", "unknown"), ("customer_id", "private identity"), ("verified_at", assessed + timedelta(microseconds=1)),
                ("currency_code", "usd"), ("period_starts_at", None), ("period_ends_at", linked.period_starts_at),
                ("failed_at", linked.verified_at.replace(tzinfo=None)), ("canceled_at", assessed)):
            invalid = copy.deepcopy(source); invalid["subscription"][key] = value
            with self.subTest(field=key), self.assertRaises(ValidationError): staff._record(invalid, assessed)
        for field in ("period_starts_at", "period_ends_at", "failed_at", "scheduled_cancel_at", "refunded_at", "disputed_at"):
            future = copy.deepcopy(source)
            future["subscription"].update(period_starts_at=assessed + timedelta(days=30), period_ends_at=assessed + timedelta(days=60))
            if field not in {"period_starts_at", "period_ends_at"}: future["subscription"][field] = assessed + timedelta(minutes=4)
            self.assertIsNotNone(staff._record(future, assessed)[field])
        recovered = copy.deepcopy(source); recovered["subscription"]["grace_usage_starts_at"] = linked.period_starts_at
        self.assertIsNone(staff._record(recovered, assessed)["failed_at"])
        for status in ("paused", "trialing", "canceled"):
            variant = copy.deepcopy(source)
            variant["subscription"].update(status=status, period_starts_at=None, period_ends_at=None,
                canceled_at=assessed + timedelta(days=1) if status == "canceled" else None)
            self.assertEqual(staff._record(variant, assessed)["status"], status)
