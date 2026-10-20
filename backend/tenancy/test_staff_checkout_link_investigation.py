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

from . import staff_checkout_link_investigation as staff, test_paddle_reconcile as fixtures
from .closure import close_organization_locally
from .models import AuditEvent, AuditEventType, Organization, OrganizationMembership, PaddleCheckoutAttempt, PaddleCheckoutLinkReceipt, PaddleSellerConfiguration
from .paddle_checkout_delivery import acknowledge_checkout_link, checkout_link_receipt_challenge, checkout_source_digest
from .paddle_reconcile import record_paid_checkout_receipt, record_current_subscription_receipt
from .test_trial_corrections import staff_trial_request


@override_settings(**fixtures.SignedPaymentEvidenceTests._overridden_settings,
    FRONTEND_ORIGIN="https://app.example.com", PADDLE_CHECKOUT_URL="https://app.example.com/account/billing/checkout")
class StaffCheckoutLinkInvestigationTests(TestCase):
    provider_response = fixtures.SignedPaymentEvidenceTests.provider_response
    subscription_receipt = fixtures.SignedPaymentEvidenceTests.subscription_receipt
    subscription_response = fixtures.SignedPaymentEvidenceTests.subscription_response

    def setUp(self):
        fixtures.SignedPaymentEvidenceTests.setUp(self)
        self.attempt.refresh_from_db()
        self.proof = checkout_link_receipt_challenge(organization=self.organization, actor=self.owner, attempt_id=self.attempt.pk)["proof"]
        acknowledge_checkout_link(organization=self.organization, actor=self.owner, attempt_id=self.attempt.pk, proof=self.proof)
        self.link_receipt = PaddleCheckoutLinkReceipt.objects.get(attempt=self.attempt)
        self.inspector = get_user_model().objects.create_user("link-inspector@example.invalid", "fixture-password", is_staff=True)
        self.permissions = Permission.objects.filter(content_type__app_label="tenancy", codename__in=["view_organization", "view_paddlecheckoutlinkreceipt"])
        self.inspector.user_permissions.add(*self.permissions)
        self.request = staff_trial_request(self.inspector)

    def inspect(self, **changes):
        return staff.inspect_staff_checkout_link(**{**dict(request=self.request, organization_id=self.organization.pk,
            receipt_id=self.link_receipt.pk, reason="investigation"), **changes})

    def events(self):
        return AuditEvent.objects.filter(event_type=AuditEventType.STAFF_CHECKOUT_LINK_INSPECTED)

    def test_genuine_capture_signed_paid_settled_role_and_seller_loss_preserve_original_history(self):
        before = self.inspect()
        fixtures.SignedPaymentEvidenceTests.test_fully_canceled_current_subscription_allows_new_paid_checkout_with_history(self)
        self.attempt.refresh_from_db(); self.assertEqual(self.attempt.state, "settled")
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="admin")
        PaddleSellerConfiguration.objects.filter(environment="sandbox").update(rotated_at=timezone.now(), client_token="")
        with override_settings(PADDLE_ENVIRONMENT="live", PADDLE_ENCRYPTION_KEYS=()):
            after = self.inspect()
        self.assertEqual(before, after)
        self.link_receipt.refresh_from_db()
        self.assertEqual(self.link_receipt.source_digest, before["receipt"]["original_source_digest"])
        self.assertEqual(set(after["receipt"]), {"id", "attempt_id", "acknowledged_at", "original_source_digest"})
        self.assertIn("not_provider_page_payment", after["scope"])

    def test_real_paid_canceled_closure_and_private_scalar_audit_only_without_current_billing_lookup(self):
        record_paid_checkout_receipt(receipt=self.receipt, provider_response=self.provider_response())
        record_current_subscription_receipt(receipt=self.subscription_receipt(), provider_response=self.subscription_response(
            status="canceled", canceled_at=fixtures.NOW.isoformat(), current_billing_period=None))
        close_organization_locally(organization=self.organization, actor=self.owner, request=staff_trial_request(self.owner))
        with CaptureQueriesContext(connection) as queries, patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("tenancy.paddle_checkout_delivery.checkout_link_delivery_source", side_effect=AssertionError("current eligibility")), \
                patch("django.core.mail.send_mail", side_effect=AssertionError("SMTP")):
            result = self.inspect()
        event = self.events().get()
        self.assertEqual((event.organization_id, event.project_id, event.subject_user_id), (self.organization.pk, None, None))
        self.assertEqual(event.details, {"receipt_id": self.link_receipt.pk, "reason": "investigation"})
        for private in (self.proof, self.owner.email, self.organization.name, self.link_receipt.source["transaction_id"],
                self.link_receipt.source["checkout_url"], "request_actor_id", "seller_rotated_at", "product_id", "price_id"):
            self.assertNotIn(private, json.dumps(result)); self.assertNotIn(private, json.dumps(event.details))
        for query in queries:
            self.assertFalse(any(table in query["sql"] for table in ("paddleseller", "paddlesubscription", "paddlewebhook", "firstactiveobservation", "billingcancellation", "organizationdeletionrun", "jobs_", "account_emailaddress")))
            if 'FROM "accounts_user"' in query["sql"]: self.assertIn(f'"accounts_user"."id" = {self.inspector.pk}', query["sql"])
            if 'JOIN "tenancy_paddlecheckoutattempt"' in query["sql"]:
                select = query["sql"].split(" FROM ", 1)[0]
                for private in ("transaction_id", "paid_verified_at", "price_id", "request_key"): self.assertNotIn(private, select)
        writes = [row["sql"] for row in queries if row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
        self.assertEqual(len(writes), 1); self.assertIn("tenancy_auditevent", writes[0])

    def test_exact_inputs_independent_current_pair_mfa_session_and_hidden_post_audit_loss_roll_back(self):
        for changes, error in (({"organization_id": self.organization.pk + 99999}, PermissionDenied),
                ({"receipt_id": True}, ValidationError), ({"receipt_id": 2**53}, ValidationError), ({"reason": "private prose"}, ValidationError)):
            with self.assertRaises(error): self.inspect(**changes)
        for permission in self.permissions:
            self.inspector.user_permissions.remove(permission)
            with patch.object(staff, "_source", side_effect=AssertionError("source before authority")), self.assertRaises(PermissionDenied): self.inspect()
            self.inspector.user_permissions.add(permission)
        key = self.request.session.session_key
        for field, value in ((HASH_SESSION_KEY, "invalid"), (AUTHENTICATION_METHODS_SESSION_KEY, [{"method": "password"}])):
            with transaction.atomic():
                self.request.session[field] = value; self.request.session.save()
                with self.assertRaises(PermissionDenied): self.inspect()
                transaction.set_rollback(True)
            self.request.session = type(self.request.session)(session_key=key)
        original = staff._source(self.organization.pk, self.link_receipt.pk)
        create = AuditEvent.objects.create
        def change_json():
            changed = copy.deepcopy(self.link_receipt.source); changed["seller_id"] += 1
            PaddleCheckoutLinkReceipt.objects.filter(pk=self.link_receipt.pk).update(source=changed, source_digest=checkout_source_digest(changed))
        mutations = [change_json,
            lambda: PaddleCheckoutLinkReceipt.objects.filter(pk=self.link_receipt.pk).update(acknowledged_at=self.link_receipt.acknowledged_at + timedelta(microseconds=1)),
            lambda: PaddleCheckoutLinkReceipt.objects.filter(pk=self.link_receipt.pk).update(actor=self.inspector),
            lambda: PaddleCheckoutAttempt.objects.filter(pk=self.attempt.pk).update(organization=Organization.objects.create(name="Foreign fixture")),
            lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True),
            lambda: self.inspector.user_permissions.clear(), lambda: Authenticator.objects.filter(user=self.inspector).delete(),
            lambda: Session.objects.filter(session_key=key).delete(),
            lambda: get_user_model().objects.filter(pk=self.inspector.pk).update(session_version="invalid")]
        for mutate in mutations:
            def changed(**kwargs):
                event = create(**kwargs); mutate(); return event
            with patch.object(staff.AuditEvent.objects, "create", side_effect=changed), self.assertRaises((PermissionDenied, ValidationError)): self.inspect()
            self.assertFalse(self.events().exists()); self.assertEqual(staff._source(self.organization.pk, self.link_receipt.pk), original)
            self.request.session = type(self.request.session)(session_key=key)
        with patch.object(staff.AuditEvent.objects, "create", side_effect=RuntimeError("audit unavailable")), self.assertRaises(RuntimeError): self.inspect()

    def test_original_json_digest_linkage_date_shapes_and_old_history_without_reconstruction(self):
        source = staff._source(self.organization.pk, self.link_receipt.pk); now = timezone.now()
        for field, value in (("method", "payment"), ("actor_id", True), ("organization_id", self.organization.pk + 1),
                ("environment", "unknown"), ("payment_confirmed", 0), ("request_actor_id", True), ("offer_version", "private"),
                ("checkout_url", "https://foreign.example.invalid/account/checkout?_ptxn=wrong"),
                ("created_at", (now + timedelta(days=1)).isoformat()), ("sent_at", now.replace(tzinfo=None).isoformat()),
                ("seller_rotated_at", (now + timedelta(days=1)).isoformat())):
            altered = copy.deepcopy(source); altered["receipt"]["source"][field] = value
            altered["receipt"]["source_digest"] = checkout_source_digest(altered["receipt"]["source"])
            with self.subTest(field=field), self.assertRaises(ValidationError): staff._record(altered, now)
        for field, value in (("source_digest", "a" * 64), ("acknowledged_at", now.replace(tzinfo=None)),
                ("acknowledged_at", now + timedelta(days=1)), ("actor_id", self.inspector.pk)):
            altered = copy.deepcopy(source); altered["receipt"][field] = value
            with self.assertRaises(ValidationError): staff._record(altered, now)
        older = copy.deepcopy(source)
        for field in ("created_at", "sent_at", "seller_rotated_at"):
            older["receipt"]["source"][field] = (staff._original_date(older["receipt"]["source"][field]) - timedelta(days=500)).isoformat()
        older["receipt"]["acknowledged_at"] -= timedelta(days=500)
        older["receipt"]["source_digest"] = checkout_source_digest(older["receipt"]["source"])
        self.assertEqual(staff._record(older, now)["acknowledged_at"], older["receipt"]["acknowledged_at"].isoformat())
