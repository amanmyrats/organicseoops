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

from . import staff_first_active_investigation as staff, test_paddle_activation as activation, test_paddle_reconcile as fixtures
from .models import AuditEvent, AuditEventType, Organization, OrganizationMembership, PaddleCheckoutAttempt, PaddleFirstActiveObservation, PaddleSellerConfiguration, PaddleWebhookReceipt
from .paddle_checkout_delivery import checkout_source_digest
from .test_trial_corrections import staff_trial_request


@override_settings(**fixtures.SignedPaymentEvidenceTests._overridden_settings)
class StaffFirstActiveInvestigationTests(TestCase):
    provider_response = fixtures.SignedPaymentEvidenceTests.provider_response
    subscription_receipt = fixtures.SignedPaymentEvidenceTests.subscription_receipt
    subscription_response = fixtures.SignedPaymentEvidenceTests.subscription_response
    current = activation.PaidActivationSourceTests.current
    paid = activation.FirstActiveObservationTests.paid
    signed = activation.FirstActiveObservationTests.signed

    def setUp(self):
        fixtures.SignedPaymentEvidenceTests.setUp(self)
        self.inspector = get_user_model().objects.create_user("first-active-inspector@example.invalid", "fixture-password", is_staff=True)
        self.permissions = Permission.objects.filter(content_type__app_label="tenancy", codename__in=["view_organization", "view_paddlefirstactiveobservation"])
        self.inspector.user_permissions.add(*self.permissions)
        self.request = staff_trial_request(self.inspector)

    def capture(self):
        self.current()
        self.observation = PaddleFirstActiveObservation.objects.get(organization=self.organization)

    def inspect(self, **changes):
        return staff.inspect_staff_first_active(**{**dict(request=self.request, organization_id=self.organization.pk,
            observation_id=self.observation.pk, reason="investigation"), **changes})

    def events(self):
        return AuditEvent.objects.filter(event_type=AuditEventType.STAFF_FIRST_ACTIVE_INSPECTED)

    def test_genuine_signed_renewal_recovery_settled_recheckout_role_seller_loss_preserve_original_observation(self):
        self.capture()
        before = self.inspect()["observation"]
        fixtures.SignedPaymentEvidenceTests.test_signed_renewal_failure_and_recovery_use_current_provider_state(self)
        self.assertEqual(self.inspect()["observation"], before)
        fixtures.SignedPaymentEvidenceTests.test_fully_canceled_current_subscription_allows_new_paid_checkout_with_history(self)
        self.attempt.refresh_from_db(); self.assertEqual(self.attempt.state, "settled")
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="admin")
        PaddleSellerConfiguration.objects.filter(environment="sandbox").update(price_id="pri_" + "z" * 26, client_token="")
        with override_settings(PADDLE_ENVIRONMENT="live", PADDLE_ENCRYPTION_KEYS=()):
            self.assertEqual(self.inspect()["observation"], before)
        self.assertEqual(set(before), {"id", "attempt_id", "observed_at", "provider_occurred_at", "environment", "offer_version", "currency_code", "original_source_digest"})
        self.assertNotEqual(before["observed_at"], before["provider_occurred_at"])

    def test_genuine_recurring_transaction_can_be_original_first_active_provenance(self):
        activation.FirstActiveObservationTests.test_genuine_recurring_reconciliation_can_supply_first_active_observation_after_initial_past_due(self)
        self.observation = PaddleFirstActiveObservation.objects.get(organization=self.organization)
        result = self.inspect()
        self.assertEqual(result["observation"]["observed_at"], self.observation.observed_at.isoformat())
        self.assertEqual(self.observation.source["reconciliation_receipt"]["event_type"], "transaction.completed")

    @patch("tenancy.services.did_recently_authenticate", return_value=True)
    def test_real_customer_erasure_retains_history_with_private_audit_only_and_no_current_paid_lookup(self, _reauth):
        activation.FirstActiveObservationTests.test_real_closure_customer_erasure_retains_restricted_immutable_observation_and_audits(self)
        self.observation = PaddleFirstActiveObservation.objects.get(organization=self.organization)
        with CaptureQueriesContext(connection) as queries, patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("tenancy.paddle_activation.first_active_observation_source", side_effect=AssertionError("current capture source")), \
                patch("django.core.mail.send_mail", side_effect=AssertionError("SMTP")):
            result = self.inspect()
        event = self.events().get()
        self.assertEqual((event.organization_id, event.project_id, event.subject_user_id), (self.organization.pk, None, None))
        self.assertEqual(event.details, {"observation_id": self.observation.pk, "reason": "investigation"})
        for private in (self.owner.email, self.organization.name, "request_actor_id", "raw_digest", "product_id", "price_id",
                self.observation.source["customer_id"], self.observation.source["provider_subscription_id"], self.observation.source["transaction_id"]):
            self.assertNotIn(private, json.dumps(result)); self.assertNotIn(private, json.dumps(event.details))
        for query in queries:
            self.assertFalse(any(table in query["sql"] for table in ("paddleseller", "paddlesubscription", "organizationdeletionrun", "jobs_", "account_emailaddress", "organizationmembership")))
            if 'FROM "accounts_user"' in query["sql"]: self.assertIn(f'"accounts_user"."id" = {self.inspector.pk}', query["sql"])
        writes = [row["sql"] for row in queries if row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
        self.assertEqual(len(writes), 1); self.assertIn("tenancy_auditevent", writes[0])

    def test_exact_inputs_current_independent_pair_mfa_and_full_hidden_post_audit_loss_roll_back(self):
        self.capture()
        for changes, error in (({"organization_id": self.organization.pk + 99999}, PermissionDenied),
                ({"observation_id": True}, ValidationError), ({"observation_id": 2**53}, ValidationError), ({"reason": "private prose"}, ValidationError)):
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
        original = staff._source(self.organization.pk, self.observation.pk)
        original_result = self.inspect()
        self.events().delete()
        create = AuditEvent.objects.create
        def change_source():
            source = copy.deepcopy(self.observation.source); source["price_id"] = "pri_" + "z" * 26
            PaddleFirstActiveObservation.objects.filter(pk=self.observation.pk).update(source=source, source_digest=checkout_source_digest(source))
        mutations = [change_source,
            lambda: PaddleFirstActiveObservation.objects.filter(pk=self.observation.pk).update(observed_at=self.observation.observed_at + timedelta(microseconds=1)),
            lambda: PaddleWebhookReceipt.objects.filter(pk=self.observation.receipt_id).update(raw_digest="a" * 64),
            lambda: AuditEvent.objects.filter(pk=self.observation.source["payment_audit_id"]).update(details={}),
            lambda: PaddleCheckoutAttempt.objects.filter(pk=self.attempt.pk).update(request_key="changed-private-key"),
            lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True),
            lambda: Organization.objects.filter(pk=self.organization.pk).update(paid_activation_tracking=None),
            lambda: self.inspector.user_permissions.clear(), lambda: Authenticator.objects.filter(user=self.inspector).delete(),
            lambda: Session.objects.filter(session_key=key).delete(),
            lambda: get_user_model().objects.filter(pk=self.inspector.pk).update(session_version="invalid")]
        for mutate in mutations:
            def changed(**kwargs):
                event = create(**kwargs); mutate(); return event
            with patch.object(staff.AuditEvent.objects, "create", side_effect=changed), self.assertRaises((PermissionDenied, ValidationError)): self.inspect()
            self.assertFalse(self.events().exists()); self.assertEqual(staff._source(self.organization.pk, self.observation.pk), original)
            self.request.session = type(self.request.session)(session_key=key)
            staff.require_staff_first_active_delivery(request=self.request, original=original_result)
        with patch.object(staff.AuditEvent.objects, "create", side_effect=RuntimeError("audit unavailable")), self.assertRaises(RuntimeError): self.inspect()

    def test_exact_original_json_identity_date_digest_and_signed_provenance_corruption_deny(self):
        self.capture()
        source = staff._source(self.organization.pk, self.observation.pk); now = timezone.now()
        for key, value in (("method", "payment"), ("request_actor_id", True), ("organization_id", self.organization.pk + 1),
                ("environment", "unknown"), ("product_id", []), ("offer_version", "private"),
                ("tracking_started_at", now.replace(tzinfo=None).isoformat()), ("attempt_created_at", (now + timedelta(days=1)).isoformat()),
                ("payment_audit_id", 0), ("currency_code", "usd"), ("period_ends_at", self.observation.observed_at.isoformat())):
            changed = copy.deepcopy(source); changed["observation"]["source"][key] = value
            changed["observation"]["source_digest"] = checkout_source_digest(changed["observation"]["source"])
            with self.subTest(key=key), self.assertRaises(ValidationError): staff._record(changed, now)
        for key in ("payment_receipt", "reconciliation_receipt"):
            for field, value in (("id", True), ("raw_digest", "private"), ("event_type", "unknown"),
                    ("processed_at", (now + timedelta(days=1)).isoformat()), ("occurred_at", "invalid")):
                changed = copy.deepcopy(source); changed["observation"]["source"][key][field] = value
                changed["observation"]["source_digest"] = checkout_source_digest(changed["observation"]["source"])
                with self.assertRaises(ValidationError): staff._record(changed, now)
        for key in ("extra", "payment_receipt"):
            changed = copy.deepcopy(source)
            if key == "extra": changed["observation"]["source"][key] = "private"
            else: changed["observation"]["source"][key]["extra"] = "private"
            with self.assertRaises(ValidationError): staff._record(changed, now)
        for model, pk, changes in ((PaddleWebhookReceipt, self.observation.receipt_id, {"raw_digest": "a" * 64}),
                (AuditEvent, self.observation.source["subscription_audit_id"], {"details": {}}),
                (PaddleCheckoutAttempt, self.attempt.pk, {"price_id": "pri_" + "z" * 26})):
            with transaction.atomic(), self.assertRaises(ValidationError):
                model.objects.filter(pk=pk).update(**changes)
                try: self.inspect()
                finally: transaction.set_rollback(True)
        self.assertFalse(self.events().exists())
