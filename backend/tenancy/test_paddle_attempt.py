from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from allauth.account.models import EmailAddress
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings

from .models import (MembershipRole, OrganizationMembership, PaddleCheckoutAttempt, PaddleSellerConfiguration,
                     PaddleSubscription)
from .paddle_checkout import mark_paddle_checkout_sending, reserve_paddle_checkout, start_paddle_checkout
from .paddle_seller import set_paddle_seller
from .paddle_transport import PaddleTransportError
from .services import create_organization
from .test_paddle_seller import SANDBOX_KEY, SANDBOX_TOKEN


PRODUCT = "pro_" + "a" * 26
PRICE = "pri_" + "b" * 26


def catalog():
    return {"data": {"id": PRICE, "product_id": PRODUCT, "type": "standard", "status": "active",
        "product": {"id": PRODUCT, "type": "standard", "status": "active", "tax_category": "saas"},
        "billing_cycle": {"interval": "month", "frequency": 1}, "trial_period": None,
        "unit_price": {"amount": "14900", "currency_code": "USD"}, "unit_price_overrides": [],
        "quantity": {"minimum": 1, "maximum": 1}}}


@override_settings(PADDLE_ENVIRONMENT="sandbox", PADDLE_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),),
                   FRONTEND_ORIGIN="https://app.example.com",
                   PADDLE_CHECKOUT_URL="https://app.example.com/account/billing/checkout")
class CheckoutAttemptTests(TestCase):
    def setUp(self):
        user = get_user_model()
        self.staff = user.objects.create_superuser("seller@example.com", "password")
        self.owner = user.objects.create_user("owner@example.com", "password")
        EmailAddress.objects.create(user=self.owner, email=self.owner.email, verified=True, primary=True)
        self.organization = create_organization(user=self.owner, name="Agency")
        self.other_owner = user.objects.create_user("other-owner@example.com", "password")
        EmailAddress.objects.create(user=self.other_owner, email=self.other_owner.email, verified=True, primary=True)
        self.other = create_organization(user=self.other_owner, name="Other agency")
        self.admin = user.objects.create_user("admin@example.com", "password")
        OrganizationMembership.objects.create(organization=self.organization, user=self.admin, role=MembershipRole.ADMIN)
        set_paddle_seller(actor=self.staff, environment="sandbox", api_key=SANDBOX_KEY,
                          webhook_secret="fixture-signing-secret", client_token=SANDBOX_TOKEN, product_id=PRODUCT, price_id=PRICE,
                          currency="USD", amount="14900", interval="month", frequency=1)

    def test_reservation_is_organization_owned_and_provider_attempt_is_once_only(self):
        row = reserve_paddle_checkout(organization=self.organization, actor=self.owner, request_key="stable-key-001")
        self.assertEqual(row.state, PaddleCheckoutAttempt.State.RESERVED)
        self.assertEqual(row.pk, reserve_paddle_checkout(
            organization=self.organization, actor=self.owner, request_key="stable-key-001").pk)
        with self.assertRaises(ValidationError):
            reserve_paddle_checkout(organization=self.organization, actor=self.owner, request_key="different-key-002")
        with self.assertRaises(PermissionDenied):
            reserve_paddle_checkout(organization=self.organization, actor=self.admin, request_key="another-key-003")
        with self.assertRaises(PermissionDenied):
            reserve_paddle_checkout(organization=self.other, actor=self.owner, request_key="another-key-004")
        with self.assertRaises(ValidationError):
            mark_paddle_checkout_sending(attempt=row, actor=self.owner, catalog_response={"data": {}})
        row.refresh_from_db()
        self.assertIsNone(row.sent_at)
        self.assertEqual(mark_paddle_checkout_sending(attempt=row, actor=self.owner, catalog_response=catalog()).state,
                         PaddleCheckoutAttempt.State.SENDING)
        with self.assertRaises(ValidationError):
            mark_paddle_checkout_sending(attempt=row, actor=self.owner, catalog_response=catalog())
        self.assertEqual(reserve_paddle_checkout(organization=self.organization, actor=self.owner,
                                                request_key="stable-key-001").state, PaddleCheckoutAttempt.State.SENDING)
        with self.assertRaises(ValidationError):
            reserve_paddle_checkout(organization=self.organization, actor=self.owner, request_key="different-key-005")
        with self.assertRaises(ValidationError):
            set_paddle_seller(actor=self.staff, environment="sandbox", api_key=SANDBOX_KEY,
                              webhook_secret="different-signing-secret", client_token=SANDBOX_TOKEN, product_id=PRODUCT, price_id=PRICE,
                              currency="USD", amount="14900", interval="month", frequency=1)

    def test_unconfigured_or_changed_source_cannot_reserve_or_send(self):
        with override_settings(PADDLE_ENVIRONMENT=""):
            with self.assertRaises(ValidationError):
                reserve_paddle_checkout(organization=self.organization, actor=self.owner, request_key="stable-key-002")
        row = reserve_paddle_checkout(organization=self.organization, actor=self.owner, request_key="stable-key-002")
        seller = PaddleSellerConfiguration.objects.get(environment="sandbox")
        seller.price_id = "pri_" + "c" * 26
        seller.save(update_fields=["price_id"])
        with self.assertRaises(ValidationError):
            mark_paddle_checkout_sending(attempt=row, actor=self.owner, catalog_response=catalog())
        seller.price_id = PRICE
        seller.save(update_fields=["price_id"])
        PaddleSubscription.objects.create(organization=self.organization, environment="sandbox",
                                          customer_id="ctm_" + "a" * 26, subscription_id="sub_" + "b" * 26,
                                          status="active")
        with self.assertRaises(ValidationError):
            mark_paddle_checkout_sending(attempt=row, actor=self.owner, catalog_response=catalog())
        self.assertEqual(PaddleCheckoutAttempt.objects.get(pk=row.pk).state, PaddleCheckoutAttempt.State.RESERVED)

    def test_revoked_owner_cannot_send_reserved_attempt(self):
        row = reserve_paddle_checkout(organization=self.organization, actor=self.owner, request_key="stable-key-003")
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(
            role=MembershipRole.VIEWER)
        with self.assertRaises(PermissionDenied):
            mark_paddle_checkout_sending(attempt=row, actor=self.owner, catalog_response=catalog())
        self.assertEqual(PaddleCheckoutAttempt.objects.get(pk=row.pk).state, PaddleCheckoutAttempt.State.RESERVED)

    def test_fixture_only_canceled_subscription_without_paid_attempt_cannot_start_again(self):
        from django.utils import timezone

        PaddleSubscription.objects.create(organization=self.organization, environment="sandbox",
            customer_id="ctm_" + "a" * 26, subscription_id="sub_" + "b" * 26,
            status="canceled", verified_at=timezone.now(), canceled_at=timezone.now(), currency_code="USD")
        with self.assertRaises(ValidationError):
            reserve_paddle_checkout(organization=self.organization, actor=self.owner,
                                    request_key="canceled-unverified-source-001")
        self.assertFalse(PaddleCheckoutAttempt.objects.exists())

    def test_checkout_fixture_stores_transaction_but_never_grants_paid_access_or_reposts(self):
        sent = []
        base = "https://app.example.com/account/billing/checkout"

        def catalog_get(**_):
            return catalog()

        def create(*, attempt, **_):
            sent.append(PaddleCheckoutAttempt.objects.get(pk=attempt.pk).state)
            txn = "txn_" + "c" * 26
            return {"data": {"id": txn, "status": "draft", "collection_mode": "automatic",
                "custom_data": {"organization_id": str(self.organization.pk), "offer_version": "agency-launch-v1",
                                "checkout_attempt_id": str(attempt.pk)},
                "items": [{"price": {"id": PRICE}, "quantity": 1}],
                "checkout": {"url": base + "?_ptxn=" + txn}}}

        result = start_paddle_checkout(organization=self.organization, actor=self.owner,
                                       request_key="checkout-fixture-001", catalog_get=catalog_get,
                                       transaction_create=create)
        self.assertEqual(result["state"], "ready")
        self.assertEqual(result["payment_confirmed"], False)
        self.assertEqual(sent, ["sending"])
        self.assertEqual(start_paddle_checkout(organization=self.organization, actor=self.owner,
            request_key="checkout-fixture-001", catalog_get=catalog_get, transaction_create=create), result)
        self.assertEqual(sent, ["sending"])
        self.assertFalse(PaddleSubscription.objects.filter(organization=self.organization).exists())
        self.assertEqual(self.organization.trial.state, "active")

    def test_provider_outage_and_malformed_response_become_unknown_without_replay(self):
        calls = []

        def outage(**_):
            calls.append(1)
            raise PaddleTransportError("provider_unavailable")

        result = start_paddle_checkout(organization=self.organization, actor=self.owner,
            request_key="checkout-outage-001", catalog_get=lambda **_: catalog(), transaction_create=outage)
        self.assertEqual((result["state"], result["checkout_url"]), ("unknown", None))
        self.assertEqual(start_paddle_checkout(organization=self.organization, actor=self.owner,
            request_key="checkout-outage-001", catalog_get=lambda **_: catalog(), transaction_create=outage), result)
        self.assertEqual(calls, [1])
        with self.assertRaises(ValidationError):
            start_paddle_checkout(organization=self.organization, actor=self.owner,
                request_key="checkout-outage-002", catalog_get=lambda **_: catalog(), transaction_create=outage)

    def test_missing_checkout_config_denies_before_reservation_and_provider_contact(self):
        calls = []
        with override_settings(PADDLE_CHECKOUT_URL=""):
            with self.assertRaises(ValidationError):
                start_paddle_checkout(organization=self.organization, actor=self.owner,
                    request_key="checkout-unavailable-001", catalog_get=lambda **_: calls.append(1))
        self.assertFalse(calls)
        self.assertFalse(PaddleCheckoutAttempt.objects.filter(organization=self.organization).exists())


@override_settings(PADDLE_ENVIRONMENT="sandbox", PADDLE_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),))
class CheckoutAttemptRaceTests(TransactionTestCase):
    def test_concurrent_owner_requests_reserve_one_record(self):
        user = get_user_model()
        staff = user.objects.create_superuser("paddle-race-staff@example.com", "password")
        owner = user.objects.create_user("paddle-race-owner@example.com", "password")
        EmailAddress.objects.create(user=owner, email=owner.email, verified=True, primary=True)
        organization = create_organization(user=owner, name="Agency")
        set_paddle_seller(actor=staff, environment="sandbox", api_key=SANDBOX_KEY,
                          webhook_secret="fixture-signing-secret", client_token=SANDBOX_TOKEN, product_id=PRODUCT, price_id=PRICE,
                          currency="USD", amount="14900", interval="month", frequency=1)
        barrier = Barrier(2)

        def reserve(_):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                return reserve_paddle_checkout(organization=organization, actor=owner,
                                               request_key="same-browser-key-001").pk
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            ids = list(executor.map(reserve, range(2)))
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(PaddleCheckoutAttempt.objects.filter(organization=organization).count(), 1)
