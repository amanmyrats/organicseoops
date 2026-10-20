import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connection
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from . import test_paddle_checkout_api as fixtures
from config.test_foundations import TEST_STORAGES
from .models import (AuditEvent, AuditEventType, Organization, OrganizationMembership, PaddleCheckoutAttempt,
                     PaddleCheckoutLinkReceipt, PaddleSellerConfiguration, PaddleSubscription)
from .paddle_checkout_delivery import (RECEIPT_MAX_AGE, RECEIPT_SALT, acknowledge_checkout_link,
                                     checkout_link_delivery_source, checkout_link_receipt_challenge)
from .test_paddle_attempt import catalog
from .test_paddle_seller import SANDBOX_KEY


@override_settings(**fixtures.CheckoutApiTests._overridden_settings, DEBUG=True)
class CheckoutLinkSourceTests(TestCase):
    setUp = fixtures.CheckoutApiTests.setUp
    browser = fixtures.CheckoutApiTests.browser
    post = fixtures.CheckoutApiTests.post
    provider_response = fixtures.CheckoutApiTests.provider_response

    def ready(self):
        with patch("tenancy.paddle_transport.paddle_price_get", return_value=catalog()), patch(
            "tenancy.paddle_transport.paddle_transaction_create", side_effect=lambda **kwargs: self.provider_response(kwargs["attempt"])):
            response = self.post(self.browser(self.owner), {"request_key": "delivery-source-fixture"})
        self.assertEqual(response.status_code, 200, response.content)
        return PaddleCheckoutAttempt.objects.get(pk=response.json()["attempt_id"])

    def source(self, attempt, **changes):
        return checkout_link_delivery_source(**{**dict(organization=self.organization, actor=self.owner, attempt_id=attempt.pk), **changes})

    def test_actual_owner_ready_link_is_only_read_eligibility_without_writes_network_receipt_or_secrets(self):
        attempt = self.ready()
        with patch("tenancy.paddle_transport.paddle_price_get", side_effect=AssertionError("No provider GET")), patch(
            "tenancy.paddle_transport.paddle_transaction_create", side_effect=AssertionError("No provider POST")), CaptureQueriesContext(connection) as queries:
            source = self.source(attempt)
        self.assertFalse(any(row["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"} for row in queries))
        self.assertEqual(source["checkout_url"], fixtures.BASE + "?_ptxn=" + attempt.transaction_id)
        self.assertEqual(source["attempt_id"], attempt.pk)
        self.assertEqual(source["sent_at"], attempt.sent_at.isoformat())
        self.assertEqual(source["actor_id"], self.owner.pk)
        self.assertFalse(source["payment_confirmed"])
        self.assertIn("not_delivered_link", source["interpretation"])
        self.assertNotIn(SANDBOX_KEY, json.dumps(source))
        self.assertNotIn("client_token", source)
        self.assertNotIn("receipt", source)
        from .acquisition import acquisition_milestones
        self.assertEqual(acquisition_milestones()["milestones"]["checkout_initiated"], {"grain": "checkout_attempt", "count": 0, "state": "derivable"})
        for value in (True, 0, 2**53, "1"):
            with self.assertRaises(ValidationError): self.source(attempt, attempt_id=value)
        for changes in ({"actor": self.admin}, {"actor": self.foreign}, {"organization": self.other}):
            with self.assertRaises(PermissionDenied): self.source(attempt, **changes)
        original = PaddleSellerConfiguration.objects.get(environment="sandbox")
        with override_settings(PADDLE_ENVIRONMENT="live"), self.assertRaises(PermissionDenied): self.source(attempt)
        with override_settings(PADDLE_ENCRYPTION_KEYS=()), self.assertRaises(PermissionDenied): self.source(attempt)
        with override_settings(PADDLE_CHECKOUT_URL="https://foreign.example.invalid/account/checkout"), self.assertRaises(ValidationError): self.source(attempt)
        for change in ({"state": PaddleSellerConfiguration.State.REVOKED, "encrypted_api_key": "", "encrypted_webhook_secret": ""},
                       {"price_id": "pri_" + "z" * 26}, {"client_token": ""}):
            PaddleSellerConfiguration.objects.filter(pk=original.pk).update(**change)
            with self.assertRaises(PermissionDenied): self.source(attempt)
            PaddleSellerConfiguration.objects.filter(pk=original.pk).update(state=original.state, price_id=original.price_id,
                client_token=original.client_token, encrypted_api_key=original.encrypted_api_key, encrypted_webhook_secret=original.encrypted_webhook_secret)
        PaddleCheckoutAttempt.objects.filter(pk=attempt.pk).update(sent_at=timezone.now() + timedelta(hours=1))
        with self.assertRaises(ValidationError): self.source(attempt)
        PaddleCheckoutAttempt.objects.filter(pk=attempt.pk).update(sent_at=attempt.sent_at)
        PaddleSellerConfiguration.objects.filter(pk=original.pk).update(rotated_at=timezone.now() + timedelta(hours=1))
        with self.assertRaises(ValidationError): self.source(attempt)
        PaddleSellerConfiguration.objects.filter(pk=original.pk).update(rotated_at=original.rotated_at)
        from .paddle_checkout import _current_seller
        def seller_then_revoke_role():
            seller = _current_seller()
            OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="admin")
            return seller
        with patch("tenancy.paddle_checkout_delivery._current_seller", side_effect=seller_then_revoke_role), self.assertRaises(PermissionDenied):
            self.source(attempt)

    def test_real_reserved_unknown_paid_linked_and_closed_sources_cannot_authorize_receipt_issuance(self):
        from .paddle_checkout import reserve_paddle_checkout
        reserved = reserve_paddle_checkout(organization=self.organization, actor=self.owner, request_key="delivery-source-fixture")
        with self.assertRaises(PermissionDenied): self.source(reserved)
        attempt = self.ready()
        PaddleCheckoutAttempt.objects.filter(pk=attempt.pk).update(state="unknown", transaction_id="")
        with self.assertRaises(PermissionDenied): self.source(attempt)
        PaddleCheckoutAttempt.objects.filter(pk=attempt.pk).update(state="ready", transaction_id=attempt.transaction_id,
            paid_verified_at=timezone.now(), paid_customer_id="ctm_" + "p" * 26)
        with self.assertRaises(PermissionDenied): self.source(attempt)
        PaddleCheckoutAttempt.objects.filter(pk=attempt.pk).update(paid_verified_at=None, paid_customer_id="")
        PaddleSubscription.objects.create(organization=self.organization, environment="sandbox",
            customer_id="ctm_" + "p" * 26, subscription_id="sub_" + "q" * 26, status="active")
        with self.assertRaises(PermissionDenied): self.source(attempt)
        PaddleSubscription.objects.filter(organization=self.organization).delete()
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=timezone.now())
        with self.assertRaises(PermissionDenied): self.source(attempt)


@override_settings(**fixtures.CheckoutApiTests._overridden_settings, DEBUG=True, STORAGES=TEST_STORAGES)
class CheckoutLinkReceiptTests(TransactionTestCase):
    setUp = fixtures.CheckoutApiTests.setUp
    browser = fixtures.CheckoutApiTests.browser
    post = fixtures.CheckoutApiTests.post
    provider_response = fixtures.CheckoutApiTests.provider_response
    ready = CheckoutLinkSourceTests.ready

    def challenge(self, attempt):
        return checkout_link_receipt_challenge(organization=self.organization, actor=self.owner, attempt_id=attempt.pk)

    def acknowledge(self, attempt, proof, **changes):
        return acknowledge_checkout_link(**{**dict(organization=self.organization, actor=self.owner,
            attempt_id=attempt.pk, proof=proof), **changes})

    def test_actual_prospective_proof_is_read_only_and_first_acknowledgment_is_immutable_and_payment_independent(self):
        attempt = self.ready()
        with patch("tenancy.paddle_transport.paddle_price_get", side_effect=AssertionError("No provider GET")), patch(
            "tenancy.paddle_transport.paddle_transaction_create", side_effect=AssertionError("No provider POST")):
            with CaptureQueriesContext(connection) as queries:
                challenge = self.challenge(attempt)
            self.assertFalse(any(row["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"} for row in queries))
            self.assertFalse(PaddleCheckoutLinkReceipt.objects.exists())
            result = self.acknowledge(attempt, challenge["proof"])
            self.assertEqual(self.acknowledge(attempt, challenge["proof"]), result)
            self.assertEqual(self.acknowledge(attempt, self.challenge(attempt)["proof"]), result)
        receipt = PaddleCheckoutLinkReceipt.objects.get(attempt=attempt)
        self.assertEqual(receipt.actor_id, self.owner.pk)
        self.assertEqual(receipt.source, challenge["source"])
        self.assertEqual(receipt.source_digest, challenge["source_digest"])
        self.assertGreaterEqual(receipt.acknowledged_at, attempt.sent_at)
        self.assertFalse(result["payment_confirmed"])
        with self.assertRaises(ValidationError): receipt.save()
        audit = AuditEvent.objects.get(organization=self.organization,
            event_type=AuditEventType.BILLING_CHECKOUT_LINK_ACKNOWLEDGED)
        self.assertEqual(audit.actor_id, self.owner.pk)
        for private in (challenge["proof"], SANDBOX_KEY, "client_token"):
            self.assertNotIn(private, json.dumps(audit.details))
            self.assertNotIn(private, json.dumps(receipt.source))
            self.assertNotIn(private, json.dumps(result))
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, "ready")
        self.assertIsNone(attempt.paid_verified_at)
        self.assertFalse(PaddleSubscription.objects.exists())
        from .acquisition import acquisition_milestones
        self.assertEqual(acquisition_milestones()["milestones"]["checkout_initiated"], {"grain": "checkout_attempt", "count": 1, "state": "derivable"})

    def test_signature_purpose_expiry_future_foreign_actor_and_exact_source_loss_never_record_receipts(self):
        attempt = self.ready()
        challenge = self.challenge(attempt)
        proof = challenge["proof"]
        payload = signing.loads(proof, salt=RECEIPT_SALT)
        for invalid in (True, "", "a" * 4097, proof[:-1], proof + "!", signing.dumps(payload, salt="another-purpose"),
                        signing.dumps({**payload, "method": "payment"}, salt=RECEIPT_SALT),
                        signing.dumps({**payload, "issued_at": timezone.now().replace(tzinfo=None).isoformat()}, salt=RECEIPT_SALT),
                        signing.dumps({**payload, "issued_at": (timezone.now() + timedelta(minutes=1)).isoformat()}, salt=RECEIPT_SALT)):
            with self.assertRaises(ValidationError): self.acknowledge(attempt, invalid)
        from time import time
        with patch("django.core.signing.time.time", return_value=time() + RECEIPT_MAX_AGE + 1), self.assertRaises(ValidationError):
            self.acknowledge(attempt, proof)
        with patch("tenancy.paddle_checkout_delivery.timezone.now", return_value=timezone.now() + timedelta(seconds=RECEIPT_MAX_AGE + 1)), self.assertRaises(ValidationError):
            self.acknowledge(attempt, proof)
        for change in ({"organization": self.other}, {"actor": self.foreign}, {"actor": self.admin}, {"attempt_id": attempt.pk + 1}):
            with self.assertRaises(PermissionDenied): self.acknowledge(attempt, proof, **change)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.admin).update(role="owner")
        with self.assertRaises(PermissionDenied): self.acknowledge(attempt, proof, actor=self.admin)
        seller = PaddleSellerConfiguration.objects.get(environment="sandbox")
        for change in ({"rotated_at": timezone.now()}, {"price_id": "pri_" + "z" * 26}, {"client_token": ""}):
            PaddleSellerConfiguration.objects.filter(pk=seller.pk).update(**change)
            with self.assertRaises(PermissionDenied): self.acknowledge(attempt, proof)
            PaddleSellerConfiguration.objects.filter(pk=seller.pk).update(rotated_at=seller.rotated_at,
                price_id=seller.price_id, client_token=seller.client_token)
        for change in ({"sent_at": attempt.sent_at + timedelta(microseconds=1)}, {"transaction_id": "txn_" + "z" * 26}):
            PaddleCheckoutAttempt.objects.filter(pk=attempt.pk).update(**change)
            with self.assertRaises(PermissionDenied): self.acknowledge(attempt, proof)
            PaddleCheckoutAttempt.objects.filter(pk=attempt.pk).update(sent_at=attempt.sent_at, transaction_id=attempt.transaction_id)
        with override_settings(PADDLE_ENVIRONMENT="live"), self.assertRaises(PermissionDenied): self.acknowledge(attempt, proof)
        with override_settings(PADDLE_ENCRYPTION_KEYS=()), self.assertRaises(PermissionDenied): self.acknowledge(attempt, proof)
        with override_settings(PADDLE_CHECKOUT_URL=fixtures.BASE + "/changed"), self.assertRaises(PermissionDenied): self.acknowledge(attempt, proof)
        PaddleCheckoutAttempt.objects.filter(pk=attempt.pk).update(paid_verified_at=timezone.now(), paid_customer_id="ctm_" + "p" * 26)
        with self.assertRaises(PermissionDenied): self.acknowledge(attempt, proof)
        self.assertFalse(PaddleCheckoutLinkReceipt.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.BILLING_CHECKOUT_LINK_ACKNOWLEDGED).exists())

    def test_loss_after_proof_read_or_expiry_during_locked_source_checks_rolls_back(self):
        attempt = self.ready()
        proof = self.challenge(attempt)["proof"]
        def source_then_revoke(**kwargs):
            source = checkout_link_delivery_source(**kwargs)
            OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="admin")
            return source
        with patch("tenancy.paddle_checkout_delivery.checkout_link_delivery_source", side_effect=source_then_revoke), self.assertRaises(PermissionDenied):
            self.acknowledge(attempt, proof)
        def source_then_expire(**kwargs):
            source = checkout_link_delivery_source(**kwargs)
            if source_then_expire.calls == 0:
                source_then_expire.clock = patch("tenancy.paddle_checkout_delivery.timezone.now", return_value=timezone.now() + timedelta(seconds=RECEIPT_MAX_AGE + 1))
                source_then_expire.clock.start()
            source_then_expire.calls += 1
            return source
        source_then_expire.calls = 0
        try:
            with patch("tenancy.paddle_checkout_delivery.checkout_link_delivery_source", side_effect=source_then_expire), self.assertRaises(ValidationError):
                self.acknowledge(attempt, proof)
        finally:
            source_then_expire.clock.stop()
        self.assertFalse(PaddleCheckoutLinkReceipt.objects.exists())

    def test_post_audit_owner_loss_rolls_back_capture_audit_and_mutation(self):
        attempt = self.ready()
        proof = self.challenge(attempt)["proof"]
        create = AuditEvent.objects.create
        def audit_then_demote(**kwargs):
            audit = create(**kwargs)
            OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="admin")
            return audit
        with patch("tenancy.paddle_checkout_delivery.AuditEvent.objects.create", side_effect=audit_then_demote), self.assertRaises(PermissionDenied):
            self.acknowledge(attempt, proof)
        self.assertFalse(PaddleCheckoutLinkReceipt.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.BILLING_CHECKOUT_LINK_ACKNOWLEDGED).exists())
        self.assertEqual(OrganizationMembership.objects.get(organization=self.organization, user=self.owner).role, "owner")

    def test_post_audit_source_receipt_expiry_and_audit_failure_roll_back(self):
        from contextlib import ExitStack
        from .paddle_checkout_delivery import checkout_source_digest
        attempt = self.ready()
        proof = self.challenge(attempt)["proof"]
        seller = PaddleSellerConfiguration.objects.get(environment="sandbox")
        create = AuditEvent.objects.create
        def altered_json():
            row = PaddleCheckoutLinkReceipt.objects.get(attempt=attempt)
            row.source["request_actor_id"] = self.admin.pk
            PaddleCheckoutLinkReceipt.objects.filter(pk=row.pk).update(source=row.source, source_digest=checkout_source_digest(row.source))
        mutations = (
            lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True),
            lambda: self.owner.__class__.objects.filter(pk=self.owner.pk).update(is_active=False),
            lambda: PaddleSellerConfiguration.objects.filter(pk=seller.pk).update(rotated_at=timezone.now()),
            lambda: PaddleSellerConfiguration.objects.filter(pk=seller.pk).update(client_token=""),
            lambda: PaddleCheckoutAttempt.objects.filter(pk=attempt.pk).update(transaction_id="txn_" + "z" * 26),
            lambda: PaddleCheckoutAttempt.objects.filter(pk=attempt.pk).update(paid_verified_at=timezone.now(), paid_customer_id="ctm_" + "p" * 26),
            altered_json,
            lambda: PaddleCheckoutLinkReceipt.objects.filter(attempt=attempt).update(actor=self.admin),
            lambda: PaddleCheckoutLinkReceipt.objects.filter(attempt=attempt).update(acknowledged_at=attempt.sent_at),
            lambda: PaddleCheckoutLinkReceipt.objects.filter(attempt=attempt).update(id=2**52),
        )
        with patch("tenancy.paddle_transport.paddle_transaction_create", side_effect=AssertionError("No provider replay")):
            for mutation in mutations:
                with self.subTest(mutation=mutations.index(mutation)):
                    def audit_then_change(**kwargs):
                        audit = create(**kwargs)
                        mutation()
                        return audit
                    with patch("tenancy.paddle_checkout_delivery.AuditEvent.objects.create", side_effect=audit_then_change), self.assertRaises((PermissionDenied, ValidationError)):
                        self.acknowledge(attempt, proof)
                    self.assertFalse(PaddleCheckoutLinkReceipt.objects.exists())
                    self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.BILLING_CHECKOUT_LINK_ACKNOWLEDGED).exists())
                    self.assertEqual(self.challenge(attempt)["source_digest"], self.challenge_digest(proof))
            with ExitStack() as stack:
                def audit_then_expire(**kwargs):
                    audit = create(**kwargs)
                    stack.enter_context(patch("tenancy.paddle_checkout_delivery.timezone.now", return_value=timezone.now() + timedelta(seconds=RECEIPT_MAX_AGE + 1)))
                    return audit
                with patch("tenancy.paddle_checkout_delivery.AuditEvent.objects.create", side_effect=audit_then_expire), self.assertRaises(ValidationError):
                    self.acknowledge(attempt, proof)
            with patch("tenancy.paddle_checkout_delivery.AuditEvent.objects.create", side_effect=ValueError("fixture audit failure")), self.assertRaises(ValueError):
                self.acknowledge(attempt, proof)
        self.assertFalse(PaddleCheckoutLinkReceipt.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.BILLING_CHECKOUT_LINK_ACKNOWLEDGED).exists())
        self.assertEqual(self.acknowledge(attempt, proof)["state"], "acknowledged")

    def test_existing_receipt_result_callback_loss_denies_without_changing_original_capture(self):
        from .paddle_checkout_delivery import checkout_link_receipt_result
        attempt = self.ready()
        proof = self.challenge(attempt)["proof"]
        original = self.acknowledge(attempt, proof)
        def result_then_demote(receipt):
            result = checkout_link_receipt_result(receipt)
            OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="admin")
            return result
        with patch("tenancy.paddle_checkout_delivery.checkout_link_receipt_result", side_effect=result_then_demote), self.assertRaises(PermissionDenied):
            self.acknowledge(attempt, proof)
        self.assertEqual(self.acknowledge(attempt, proof), original)
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.BILLING_CHECKOUT_LINK_ACKNOWLEDGED).count(), 1)

    @patch("tenancy.services.did_recently_authenticate", return_value=True)
    def test_actual_closure_and_customer_erasure_preserve_only_restricted_billing_receipt_and_audit(self, _reauth):
        from .closure import close_organization_locally
        from .customer_inventory import CUSTOMER, RESTRICTED, inventory_customer_data
        from .deletion import delete_customer_database_records, prepare_customer_data_deletion, sweep_customer_artifact_versions
        from .services import create_project
        attempt = self.ready()
        proof = self.challenge(attempt)["proof"]
        self.acknowledge(attempt, proof)
        receipt = PaddleCheckoutLinkReceipt.objects.get(attempt=attempt)
        self.assertNotIn("tenancy.PaddleCheckoutLinkReceipt", CUSTOMER)
        self.assertEqual(RESTRICTED["tenancy.PaddleCheckoutLinkReceipt"], "attempt__organization_id")
        counts = inventory_customer_data(organization=self.organization, actor=self.owner)
        self.assertEqual(next(row["count"] for row in counts["restricted"] if row["model"] == "tenancy.PaddleCheckoutLinkReceipt"), 1)
        self.assertNotIn(proof, json.dumps(counts))
        request = RequestFactory().post("/api/organizations/close/")
        request.user = self.owner
        with self.assertRaises(ValidationError): close_organization_locally(organization=self.organization, actor=self.owner, request=request)
        project = create_project(organization=self.organization, user=self.owner, name="Synthetic retention",
            canonical_origin="https://receipt-retention.example.invalid")
        now = timezone.now()
        # Inject reconciled provider truth separately; acknowledgment must never do this.
        PaddleCheckoutAttempt.objects.filter(pk=attempt.pk).update(paid_verified_at=now,
            paid_customer_id="ctm_" + "p" * 26, paid_subscription_id="sub_" + "q" * 26)
        PaddleSubscription.objects.create(organization=self.organization, environment="sandbox", status="canceled",
            customer_id="ctm_" + "p" * 26, subscription_id="sub_" + "q" * 26,
            verified_at=now, canceled_at=now, currency_code="USD")
        close_organization_locally(organization=self.organization, actor=self.owner, request=request)
        with self.assertRaises(PermissionDenied): self.acknowledge(attempt, proof)
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.organization))
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(project.__class__.objects.filter(pk=project.pk).exists())
        receipt.refresh_from_db()
        self.assertEqual(receipt.source_digest, self.challenge_digest(proof))
        from .acquisition import acquisition_milestones
        self.assertEqual(acquisition_milestones()["milestones"]["checkout_initiated"]["count"], 1)
        self.assertEqual(AuditEvent.objects.filter(organization=self.organization,
            event_type=AuditEventType.BILLING_CHECKOUT_LINK_ACKNOWLEDGED).count(), 1)
        self.assertTrue(Organization.objects.filter(pk=self.other.pk, closed_at__isnull=True).exists())

    def challenge_digest(self, proof):
        from .paddle_checkout_delivery import checkout_source_digest
        return checkout_source_digest(signing.loads(proof, salt=RECEIPT_SALT)["source"])

    @override_settings(STAFF_MFA_REQUIRED=False)
    def test_retained_aggregate_counts_actual_prospective_attempts_not_ready_reads_or_distinct_organizations(self):
        from .acquisition import acquisition_milestones
        from .paddle_checkout import checkout_transaction_body, start_paddle_checkout
        def count(): return acquisition_milestones()["milestones"]["checkout_initiated"]["count"]
        first = self.ready()
        self.assertEqual(count(), 0)
        proof = self.challenge(first)["proof"]
        self.acknowledge(first, proof); self.acknowledge(first, proof)
        self.assertEqual(count(), 1)
        now = timezone.now()
        PaddleCheckoutAttempt.objects.filter(pk=first.pk).update(paid_verified_at=now,
            paid_customer_id="ctm_" + "p" * 26, paid_subscription_id="sub_" + "q" * 26)
        PaddleSubscription.objects.create(organization=self.organization, environment="sandbox", status="canceled",
            customer_id="ctm_" + "p" * 26, subscription_id="sub_" + "q" * 26,
            verified_at=now, canceled_at=now, currency_code="USD")
        def provider(**kwargs):
            attempt = kwargs["attempt"]; txn = "txn_" + str(attempt.pk).zfill(26)
            return {"data": {"id": txn, "status": "draft", "collection_mode": "automatic",
                "custom_data": checkout_transaction_body(organization_id=attempt.organization_id,
                    attempt_id=attempt.pk, price_id=attempt.price_id)["custom_data"],
                "items": [{"price": {"id": attempt.price_id}, "quantity": 1}],
                "checkout": {"url": fixtures.BASE + "?_ptxn=" + txn}}}
        for org, actor in ((self.organization, self.owner), (self.other, self.foreign)):
            result = start_paddle_checkout(organization=org, actor=actor, request_key="aggregate-prospective-fixture",
                catalog_get=lambda **_: catalog(), transaction_create=provider)
            self.assertEqual(result["state"], "ready")
            challenge = checkout_link_receipt_challenge(organization=org, actor=actor, attempt_id=result["attempt_id"])
            acknowledge_checkout_link(organization=org, actor=actor, attempt_id=result["attempt_id"], proof=challenge["proof"])
        self.assertEqual(count(), 3)  # Two attempts in one org plus one in another, not org count two.
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="admin")
        seller = PaddleSellerConfiguration.objects.get(environment="sandbox")
        PaddleSellerConfiguration.objects.filter(pk=seller.pk).update(rotated_at=timezone.now())
        self.assertEqual(count(), 3)  # Historical receipt remains, not current link authority.
        self.client.force_login(self.staff)
        with patch("tenancy.paddle_transport.paddle_transaction_create", side_effect=AssertionError("No provider")), CaptureQueriesContext(connection) as queries:
            response = self.client.get("/api/platform/acquisition/milestones/", secure=True, HTTP_HOST="app.example.com")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response.json()["milestones"]["checkout_initiated"], {"count": 3, "grain": "checkout_attempt", "state": "derivable"})
        self.assertEqual(response.json()["milestones"]["paid_activation_confirmed"], {"count": 0, "grain": "organization", "state": "derivable"})
        self.assertFalse(any(row["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"} for row in queries))
        for private in (proof, self.owner.email, "organization_id", "actor_id", "attempt_id", "transaction_id", "acknowledged_at", "source_digest", "checkout_url"):
            self.assertNotIn(private, response.content.decode())
        with override_settings(STAFF_MFA_REQUIRED=True):
            self.assertEqual(self.client.get("/api/platform/acquisition/milestones/", secure=True, HTTP_HOST="app.example.com").status_code, 403)


@override_settings(**fixtures.CheckoutApiTests._overridden_settings, DEBUG=True)
class CheckoutLinkReceiptApiTests(TestCase):
    setUp = fixtures.CheckoutApiTests.setUp
    browser = fixtures.CheckoutApiTests.browser
    post = fixtures.CheckoutApiTests.post
    provider_response = fixtures.CheckoutApiTests.provider_response
    ready = CheckoutLinkSourceTests.ready

    def receipt_post(self, client, path, body, *, csrf=True, content_type="application/json"):
        return client.post(path, data=body, content_type=content_type, secure=True,
            **({"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value,
                "HTTP_REFERER": "https://app.example.com/"} if csrf else {}))

    def test_actual_exact_private_get_challenge_and_explicit_csrf_acknowledgment_reconcile_without_provider_repost(self):
        from config.observability import redact
        attempt = self.ready()
        path = self.path + f"{attempt.pk}/link-receipt/"
        owner = self.browser(self.owner)
        with patch("tenancy.paddle_transport.paddle_price_get", side_effect=AssertionError("No provider GET")), patch(
            "tenancy.paddle_transport.paddle_transaction_create", side_effect=AssertionError("No provider POST")):
            with CaptureQueriesContext(connection) as queries:
                response = owner.get(path, secure=True)
            self.assertEqual(response.status_code, 200, response.content)
            self.assertFalse(any(row["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"} for row in queries))
            self.assertIsNone(response.json()["receipt"])
            challenge = response.json()["challenge"]
            self.assertEqual(challenge["source"]["checkout_url"], fixtures.BASE + "?_ptxn=" + attempt.transaction_id)
            self.assertEqual(response["Cache-Control"], "private, no-store")
            self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
            self.assertEqual(response["Referrer-Policy"], "no-referrer")
            body = json.dumps({"receipt_proof": challenge["proof"], "acknowledge_link_received": True})
            self.assertNotIn(challenge["proof"], redact(body))
            self.assertEqual(self.receipt_post(owner, path, body, csrf=False).status_code, 403)
            self.assertFalse(PaddleCheckoutLinkReceipt.objects.exists())
            recorded = self.receipt_post(owner, path, body)
            self.assertEqual(recorded.status_code, 200, recorded.content)
            self.assertEqual(self.receipt_post(owner, path, body).json(), recorded.json())
            history = owner.get(path, secure=True)
            self.assertEqual(history.json()["receipt"], recorded.json())
            self.assertIsNone(history.json()["challenge"])
            self.assertEqual(PaddleCheckoutLinkReceipt.objects.count(), 1)
            self.assertFalse(recorded.json()["payment_confirmed"])
            self.assertNotIn(challenge["proof"], history.content.decode())
            # Paid transitions do not rewrite the earlier receipt or authorize another ack.
            PaddleCheckoutAttempt.objects.filter(pk=attempt.pk).update(paid_verified_at=timezone.now(), paid_customer_id="ctm_" + "p" * 26)
            self.assertEqual(self.receipt_post(owner, path, body).status_code, 403)
            self.assertEqual(owner.get(path, secure=True).json()["receipt"], recorded.json())
            PaddleCheckoutLinkReceipt.objects.filter(attempt=attempt).update(source_digest="a" * 64)
            self.assertEqual(owner.get(path, secure=True).status_code, 409)

    def test_unauthorized_foreign_malformed_duplicate_nonfinite_rate_and_mid_read_role_loss_fail_closed(self):
        from django.test import Client
        attempt = self.ready()
        path = self.path + f"{attempt.pk}/link-receipt/"
        owner = self.browser(self.owner)
        proof = owner.get(path, secure=True).json()["challenge"]["proof"]
        valid = json.dumps({"receipt_proof": proof, "acknowledge_link_received": True})
        self.assertEqual(Client(HTTP_HOST="app.example.com").get(path, secure=True).status_code, 401)
        self.assertEqual(self.browser(self.admin).get(path, secure=True).status_code, 403)
        self.assertEqual(self.browser(self.foreign).get(path, secure=True).status_code, 404)
        self.assertEqual(owner.get(self.path + f"{attempt.pk + 1}/link-receipt/", secure=True).status_code, 404)
        self.assertEqual(owner.get(path + "?proof=hidden", secure=True).status_code, 400)
        for bad in ("{}", "[]", '{"receipt_proof":"x","acknowledge_link_received":NaN}',
                    '{"receipt_proof":"x","receipt_proof":"y","acknowledge_link_received":true}',
                    json.dumps({"receipt_proof": proof, "acknowledge_link_received": False}),
                    json.dumps({"receipt_proof": proof, "acknowledge_link_received": 1}),
                    json.dumps({"receipt_proof": True, "acknowledge_link_received": True}),
                    valid[:-1] + ',"organization_id":1}', "{" * 6145):
            self.assertEqual(self.receipt_post(owner, path, bad).status_code, 409)
        self.assertEqual(self.receipt_post(owner, path, valid, content_type="text/plain").status_code, 409)
        with override_settings(ACCOUNT_RATE_LIMITS={"billing_checkout_receipt": "1/h/user", "billing_checkout_receipt_read": "1/h/user"}):
            from django.core.cache import cache
            cache.clear()
            self.assertEqual(owner.get(path, secure=True).status_code, 200)
            self.assertEqual(owner.get(path, secure=True).status_code, 429)
            self.assertEqual(self.receipt_post(owner, path, "{}").status_code, 409)
            self.assertEqual(self.receipt_post(owner, path, valid).status_code, 429)
        from django.core.cache import cache
        cache.clear()
        def source_then_revoke(**kwargs):
            source = checkout_link_delivery_source(**kwargs)
            OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="admin")
            return source
        with patch("tenancy.paddle_checkout_delivery.checkout_link_delivery_source", side_effect=source_then_revoke):
            self.assertEqual(owner.get(path, secure=True).status_code, 403)
        self.assertFalse(PaddleCheckoutLinkReceipt.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.BILLING_CHECKOUT_LINK_ACKNOWLEDGED).exists())

    def test_response_serialization_owner_receipt_and_expiry_loss_rolls_back_acknowledgment(self):
        from contextlib import ExitStack
        from django.core.cache import cache
        from .paddle_checkout_api import _response
        attempt = self.ready()
        path = self.path + f"{attempt.pk}/link-receipt/"
        owner = self.browser(self.owner)
        proof = owner.get(path, secure=True).json()["challenge"]["proof"]
        body = json.dumps({"receipt_proof": proof, "acknowledge_link_received": True})
        for change, status in (("owner", 403), ("receipt", 409), ("expiry", 409), ("exception", 409)):
            cache.clear()
            with self.subTest(change=change), ExitStack() as stack:
                def serialize_then_change(data, *args, **kwargs):
                    response = _response(data, *args, **kwargs)
                    if data.get("state") == "acknowledged":
                        if change == "owner":
                            OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="admin")
                        elif change == "receipt":
                            PaddleCheckoutLinkReceipt.objects.filter(attempt=attempt).update(acknowledged_at=attempt.sent_at)
                        elif change == "expiry":
                            stack.enter_context(patch("tenancy.paddle_checkout_delivery.timezone.now", return_value=timezone.now() + timedelta(seconds=RECEIPT_MAX_AGE + 1)))
                        else:
                            raise ValueError("fixture serialization failure")
                    return response
                with patch("tenancy.paddle_checkout_api._response", side_effect=serialize_then_change):
                    denied = self.receipt_post(owner, path, body)
                self.assertEqual(denied.status_code, status, denied.content)
                self.assertEqual(denied["Cache-Control"], "private, no-store")
                self.assertEqual(denied["X-Robots-Tag"], "noindex, nofollow")
                self.assertNotIn(proof, denied.content.decode())
                self.assertFalse(PaddleCheckoutLinkReceipt.objects.exists())
                self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.BILLING_CHECKOUT_LINK_ACKNOWLEDGED).exists())
                self.assertEqual(OrganizationMembership.objects.get(organization=self.organization, user=self.owner).role, "owner")
        self.assertEqual(self.receipt_post(owner, path, body).status_code, 200)


@override_settings(**fixtures.CheckoutApiTests._overridden_settings, DEBUG=True)
class CheckoutLinkReceiptRaceTests(TransactionTestCase):
    setUp = fixtures.CheckoutApiTests.setUp
    browser = fixtures.CheckoutApiTests.browser
    post = fixtures.CheckoutApiTests.post
    provider_response = fixtures.CheckoutApiTests.provider_response
    ready = CheckoutLinkSourceTests.ready

    def test_two_postgresql_sessions_acknowledge_one_first_receipt_and_audit_without_provider_replay(self):
        attempt = self.ready()
        challenge = checkout_link_receipt_challenge(organization=self.organization, actor=self.owner, attempt_id=attempt.pk)
        barrier = Barrier(2)
        def acknowledge(_):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                return acknowledge_checkout_link(organization=self.organization, actor=self.owner,
                    attempt_id=attempt.pk, proof=challenge["proof"])
            finally:
                close_old_connections()
        with patch("tenancy.paddle_transport.paddle_transaction_create", side_effect=AssertionError("No provider replay")), ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(acknowledge, range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(PaddleCheckoutLinkReceipt.objects.filter(attempt=attempt).count(), 1)
        self.assertEqual(AuditEvent.objects.filter(organization=self.organization,
            event_type=AuditEventType.BILLING_CHECKOUT_LINK_ACKNOWLEDGED).count(), 1)
