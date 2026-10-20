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

from . import staff_checkout_investigation as staff, test_paddle_reconcile as fixtures
from .closure import close_organization_locally
from .models import AuditEvent, AuditEventType, Organization, PaddleCheckoutAttempt
from .paddle_checkout import reserve_paddle_checkout, start_paddle_checkout
from .paddle_reconcile import record_paid_checkout_receipt, record_current_subscription_receipt
from .paddle_transport import PaddleTransportError
from .services import create_organization
from .test_paddle_attempt import catalog, PRICE
from .test_trial_corrections import staff_trial_request


@override_settings(**fixtures.SignedPaymentEvidenceTests._overridden_settings,
    FRONTEND_ORIGIN="https://app.example.com", PADDLE_CHECKOUT_URL="https://app.example.com/account/billing/checkout")
class StaffCheckoutInvestigationTests(TestCase):
    provider_response = fixtures.SignedPaymentEvidenceTests.provider_response
    subscription_receipt = fixtures.SignedPaymentEvidenceTests.subscription_receipt
    subscription_response = fixtures.SignedPaymentEvidenceTests.subscription_response

    def setUp(self):
        fixtures.SignedPaymentEvidenceTests.setUp(self)
        self.inspector = get_user_model().objects.create_user("checkout-inspector@example.invalid", "fixture-password", is_staff=True)
        self.permissions = Permission.objects.filter(content_type__app_label="tenancy", codename__in=["view_organization", "view_paddlecheckoutattempt"])
        self.inspector.user_permissions.add(*self.permissions)
        self.request = staff_trial_request(self.inspector)

    def inspect(self, **changes):
        return staff.inspect_staff_checkout(**{**dict(request=self.request, organization_id=self.organization.pk,
            attempt_id=self.attempt.pk, reason="investigation"), **changes})

    def events(self):
        return AuditEvent.objects.filter(event_type=AuditEventType.STAFF_CHECKOUT_INSPECTED)

    def test_genuine_catalog_outage_reserved_sending_ready_unknown_and_no_repost(self):
        other = create_organization(user=self.owner, name="Other checkout fixture")
        def inspect(attempt_id): return self.inspect(organization_id=other.pk, attempt_id=attempt_id)["attempt"]
        def outage(**_): raise PaddleTransportError("timeout")
        row = reserve_paddle_checkout(organization=other, actor=self.owner, request_key="staff-checkout-fixture")
        result = start_paddle_checkout(organization=other, actor=self.owner, request_key=row.request_key, catalog_get=outage,
            transaction_create=lambda **_: self.fail("no POST on catalog outage"))
        self.assertEqual((result["state"], inspect(row.pk)["sent_at"]), ("reserved", None))
        calls = []
        def create(*, attempt, **_):
            calls.append(1); self.assertEqual(inspect(attempt.pk)["state"], "sending")
            return {"data": {"id": "txn_" + "z" * 26, "status": "draft", "collection_mode": "automatic",
                "custom_data": {"organization_id": str(other.pk), "checkout_attempt_id": str(attempt.pk), "offer_version": "agency-launch-v1"},
                "items": [{"price": {"id": PRICE}, "quantity": 1}],
                "checkout": {"url": "https://app.example.com/account/billing/checkout?_ptxn=txn_" + "z" * 26}}}
        result = start_paddle_checkout(organization=other, actor=self.owner, request_key=row.request_key,
            catalog_get=lambda **_: catalog(), transaction_create=create)
        self.assertEqual((result["state"], inspect(row.pk)["paid_verified_at"]), ("ready", None))
        start_paddle_checkout(organization=other, actor=self.owner, request_key=row.request_key,
            transaction_create=lambda **_: self.fail("no rePOST"))
        self.assertEqual(calls, [1])
        third = create_organization(user=self.owner, name="Unknown checkout fixture")
        result = start_paddle_checkout(organization=third, actor=self.owner, request_key="staff-unknown-fixture",
            catalog_get=lambda **_: catalog(), transaction_create=outage)
        observed = self.inspect(organization_id=third.pk, attempt_id=result["attempt_id"])["attempt"]
        self.assertEqual((observed["state"], observed["paid_verified_at"]), ("unknown", None))
        start_paddle_checkout(organization=third, actor=self.owner, request_key="staff-unknown-fixture",
            transaction_create=lambda **_: self.fail("no uncertain replay"))

    def test_genuine_signed_nullable_subscription_fill_and_settled_recheckout_are_not_current_paid_truth(self):
        response = self.provider_response(); response["data"]["subscription_id"] = None
        paid = record_paid_checkout_receipt(receipt=self.receipt, provider_response=response)
        self.assertEqual(paid.paid_subscription_id, "")
        before = self.inspect(); self.assertIsNotNone(before["attempt"]["paid_verified_at"])
        record_current_subscription_receipt(receipt=self.subscription_receipt(), provider_response=self.subscription_response())
        self.attempt.refresh_from_db(); self.assertTrue(self.attempt.paid_subscription_id)
        self.assertEqual(before["attempt"]["paid_verified_at"], self.inspect()["attempt"]["paid_verified_at"])
        self.assertNotEqual(before["source_digest"], self.inspect()["source_digest"])
        # Original genuine signed cancellation→new paid attempt fixture preserves the prior local paid date.
        fixtures.SignedPaymentEvidenceTests.test_fully_canceled_current_subscription_allows_new_paid_checkout_with_history(self)
        observed = self.inspect()["attempt"]
        self.assertEqual((len(observed), observed["state"], observed["paid_verified_at"]), (8, "settled", before["attempt"]["paid_verified_at"]))

    def test_genuine_closure_rejection_retained_old_other_environment_scalar_privacy_and_audit_only(self):
        other = create_organization(user=self.owner, name="Private closure fixture")
        attempt = reserve_paddle_checkout(organization=other, actor=self.owner, request_key="staff-close-fixture")
        updated = attempt.updated_at
        close_organization_locally(organization=other, actor=self.owner, request=staff_trial_request(self.owner))
        attempt.refresh_from_db(); self.assertEqual((attempt.state, attempt.updated_at), ("rejected", updated))
        old = timezone.now() - timedelta(days=500)
        PaddleCheckoutAttempt.objects.filter(pk=attempt.pk).update(created_at=old, updated_at=old)
        with override_settings(PADDLE_ENVIRONMENT="live"), CaptureQueriesContext(connection) as queries, \
                patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("django.core.mail.send_mail", side_effect=AssertionError("SMTP")), \
                patch("tenancy.billing_state.paid_access_state", side_effect=AssertionError("effective paid")):
            result = self.inspect(organization_id=other.pk, attempt_id=attempt.pk)
        self.assertEqual((result["attempt"]["state"], result["attempt"]["sent_at"]), ("rejected", None))
        event = self.events().get()
        self.assertEqual((event.organization_id, event.project_id, event.subject_user_id), (other.pk, None, None))
        self.assertEqual(set(event.details), {"attempt_id", "reason", "state"})
        for private in (attempt.product_id, attempt.price_id, attempt.request_key, self.owner.email, other.name,
                "actor_id", "closed_at", "transaction_id", "paid_customer_id", "paid_subscription_id"):
            self.assertNotIn(private, json.dumps(result)); self.assertNotIn(private, json.dumps(event.details))
        for query in queries:
            self.assertFalse(any(table in query["sql"] for table in ("paddleseller", "paddlewebhook", "paddlesubscription", "checkoutlinkreceipt", "firstactiveobservation", "billingcancellation", "organizationdeletionrun", "jobs_", "account_emailaddress")))
            if 'FROM "accounts_user"' in query["sql"]: self.assertIn(f'"accounts_user"."id" = {self.inspector.pk}', query["sql"])
        writes = [query["sql"] for query in queries if query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
        self.assertEqual(len(writes), 1); self.assertIn("tenancy_auditevent", writes[0])

    def test_exact_inputs_current_pair_mfa_hash_full_hidden_source_session_and_audit_rollback(self):
        foreign = create_organization(user=self.owner, name="Foreign exact scope")
        for changes, error in (({"organization_id": foreign.pk}, PermissionDenied), ({"attempt_id": self.attempt.pk + 99999}, PermissionDenied),
                ({"attempt_id": True}, ValidationError), ({"attempt_id": 2**53}, ValidationError), ({"reason": "private prose"}, ValidationError)):
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
        record_paid_checkout_receipt(receipt=self.receipt, provider_response=self.provider_response())
        self.attempt.refresh_from_db()
        mutations = [(lambda key=key, value=value: PaddleCheckoutAttempt.objects.filter(pk=self.attempt.pk).update(**{key: value}), ValidationError)
            for key, value in (("actor_id", self.inspector.pk), ("environment", "live"), ("product_id", "pro_" + "z" * 26),
                ("price_id", "pri_" + "z" * 26), ("request_key", "hidden-different-key"), ("transaction_id", "txn_" + "z" * 26),
                ("paid_customer_id", "ctm_" + "z" * 26), ("paid_subscription_id", "sub_" + "z" * 26),
                ("paid_verified_at", self.attempt.paid_verified_at + timedelta(microseconds=1)),
                ("created_at", self.attempt.created_at - timedelta(microseconds=1)),
                ("sent_at", self.attempt.sent_at + timedelta(microseconds=1)), ("updated_at", self.attempt.updated_at + timedelta(microseconds=1)))]
        mutations += [(lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True), ValidationError),
            (lambda: self.inspector.user_permissions.clear(), PermissionDenied),
            (lambda: Authenticator.objects.filter(user=self.inspector).delete(), PermissionDenied),
            (lambda: Session.objects.filter(session_key=session_key).delete(), PermissionDenied),
            (lambda: get_user_model().objects.filter(pk=self.inspector.pk).update(session_version="invalid"), PermissionDenied)]
        original = staff._source(self.organization.pk, self.attempt.pk)
        for mutate, error in mutations:
            def changed(**kwargs):
                event = create(**kwargs); mutate(); return event
            with patch.object(staff.AuditEvent.objects, "create", side_effect=changed), self.assertRaises(error): self.inspect()
            self.assertFalse(self.events().exists()); self.assertEqual(staff._source(self.organization.pk, self.attempt.pk), original)
            self.request.session = type(self.request.session)(session_key=session_key)
        with patch.object(staff.AuditEvent.objects, "create", side_effect=RuntimeError("audit unavailable")), self.assertRaises(RuntimeError): self.inspect()
        record = staff._record
        def changed(source, assessed):
            result = record(source, assessed); PaddleCheckoutAttempt.objects.filter(pk=self.attempt.pk).update(actor_id=self.inspector.pk); return result
        with patch.object(staff, "_record", side_effect=changed), self.assertRaises(ValidationError): self.inspect()
        self.assertFalse(self.events().exists())

    def test_date_state_null_identity_corruption_and_independently_ordered_update(self):
        source = staff._source(self.organization.pk, self.attempt.pk); assessed = timezone.now()
        for key, value in (("state", "invalid"), ("environment", "invalid"), ("offer_version", "private"), ("actor_id", True),
                ("product_id", "private"), ("request_key", "bad"), ("transaction_id", ""), ("sent_at", None),
                ("created_at", assessed + timedelta(microseconds=1)), ("updated_at", source["attempt"]["created_at"] - timedelta(microseconds=1)),
                ("updated_at", assessed + timedelta(microseconds=1)), ("sent_at", assessed.replace(tzinfo=None)),
                ("sent_at", source["attempt"]["created_at"] - timedelta(microseconds=1)), ("paid_customer_id", "ctm_" + "z" * 26),
                ("paid_verified_at", assessed)):
            invalid = copy.deepcopy(source); invalid["attempt"][key] = value
            with self.subTest(field=key), self.assertRaises(ValidationError): staff._record(invalid, assessed)
        paid = copy.deepcopy(source); paid["attempt"].update(paid_verified_at=assessed, paid_customer_id="ctm_" + "z" * 26,
            updated_at=source["attempt"]["created_at"])
        self.assertIsNotNone(staff._record(paid, assessed)["paid_verified_at"])
        for key, value in (("paid_verified_at", source["attempt"]["sent_at"] - timedelta(microseconds=1)),
                ("paid_verified_at", assessed + timedelta(microseconds=1)), ("paid_subscription_id", "private"), ("paid_customer_id", "")):
            invalid = copy.deepcopy(paid); invalid["attempt"][key] = value
            with self.assertRaises(ValidationError): staff._record(invalid, assessed)
        rejected = copy.deepcopy(source); rejected["attempt"].update(state="rejected", transaction_id="", updated_at=source["attempt"]["created_at"])
        self.assertEqual(staff._record(rejected, assessed)["state"], "rejected")
        reserved = copy.deepcopy(rejected); reserved["attempt"].update(state="reserved", sent_at=None)
        self.assertIsNone(staff._record(reserved, assessed)["sent_at"])
        settled = copy.deepcopy(source); settled["attempt"]["state"] = "settled"
        with self.assertRaises(ValidationError): staff._record(settled, assessed)
