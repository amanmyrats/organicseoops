import json
from datetime import timedelta
from unittest.mock import patch

from allauth.account.models import EmailAddress
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from .models import (MembershipRole, OrganizationDeletionRun, OrganizationMembership,
                     PaddleCheckoutAttempt, PaddleSubscription)
from .paddle_seller import set_paddle_seller
from .paddle_transport import PaddleTransportError
from .services import create_organization
from .test_paddle_attempt import PRICE, PRODUCT, catalog
from .test_paddle_seller import SANDBOX_KEY, SANDBOX_TOKEN


BASE = "https://app.example.com/account/billing/checkout"


@override_settings(PADDLE_ENVIRONMENT="sandbox", PADDLE_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),),
                   FRONTEND_ORIGIN="https://app.example.com", PADDLE_CHECKOUT_URL=BASE,
                   ALLOWED_HOSTS=["app.example.com"], SECURE_SSL_REDIRECT=False,
                   CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class CheckoutApiTests(TestCase):
    def setUp(self):
        cache.clear()
        users = get_user_model()
        self.staff = users.objects.create_superuser("checkout-staff@example.com", "password")
        self.owner = users.objects.create_user("checkout-owner@example.com", "password")
        self.admin = users.objects.create_user("checkout-admin@example.com", "password")
        self.foreign = users.objects.create_user("checkout-foreign@example.com", "password")
        EmailAddress.objects.create(user=self.owner, email=self.owner.email, verified=True, primary=True)
        EmailAddress.objects.create(user=self.foreign, email=self.foreign.email, verified=True, primary=True)
        self.organization = create_organization(user=self.owner, name="Checkout org")
        self.other = create_organization(user=self.foreign, name="Other org")
        OrganizationMembership.objects.create(organization=self.organization, user=self.admin, role=MembershipRole.ADMIN)
        self.path = f"/api/organizations/{self.organization.pk}/billing/checkout/"
        set_paddle_seller(actor=self.staff, environment="sandbox", api_key=SANDBOX_KEY,
                          webhook_secret="fixture-signing-secret", client_token=SANDBOX_TOKEN, product_id=PRODUCT, price_id=PRICE,
                          currency="USD", amount="14900", interval="month", frequency=1)

    def browser(self, user):
        client = Client(enforce_csrf_checks=True, HTTP_HOST="app.example.com")
        client.force_login(user)
        client.get("/_allauth/browser/v1/auth/session", secure=True)
        return client

    def post(self, browser, data, csrf=True):
        headers = {"HTTP_X_CSRFTOKEN": browser.cookies["csrftoken"].value,
                   "HTTP_REFERER": "https://app.example.com/"} if csrf else {}
        return browser.post(self.path, data=json.dumps(data), content_type="application/json", secure=True, **headers)

    def provider_response(self, attempt):
        txn = "txn_" + "c" * 26
        return {"data": {"id": txn, "status": "draft", "collection_mode": "automatic",
            "custom_data": {"organization_id": str(self.organization.pk), "offer_version": "agency-launch-v1",
                            "checkout_attempt_id": str(attempt.pk)},
            "items": [{"price": {"id": PRICE}, "quantity": 1}],
            "checkout": {"url": BASE + "?_ptxn=" + txn}}}

    def test_private_owner_checkout_replays_ready_without_second_post_or_paid_access(self):
        owner = self.browser(self.owner)
        with patch("tenancy.paddle_transport.paddle_price_get", return_value=catalog()) as get_price, \
             patch("tenancy.paddle_transport.paddle_transaction_create", side_effect=lambda **kwargs:
                   self.provider_response(kwargs["attempt"])) as create:
            self.assertEqual(self.post(owner, {"request_key": "owner-attempt-001"}, csrf=False).status_code, 403)
            self.assertEqual(self.post(self.browser(self.admin), {"request_key": "admin-attempt-001"}).status_code, 403)
            self.assertEqual(self.post(self.browser(self.foreign), {"request_key": "foreign-attempt-001"}).status_code, 404)
            self.assertEqual(self.post(owner, {"request_key": "owner-attempt-001", "price_id": PRICE}).status_code, 409)
            first = self.post(owner, {"request_key": "owner-attempt-001"})
            self.assertEqual(first.status_code, 200, first.content)
            self.assertFalse(first.json()["payment_confirmed"])
            self.assertEqual(first["Cache-Control"], "private, no-store")
            self.assertEqual(first["Referrer-Policy"], "no-referrer")
            self.assertEqual(self.post(owner, {"request_key": "owner-attempt-001"}).json(), first.json())
            self.assertEqual((get_price.call_count, create.call_count), (1, 1))
        status = owner.get(self.path, secure=True)
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["attempts"][0]["state"], "ready")
        self.assertEqual(status.json()["client_token"], SANDBOX_TOKEN)
        self.assertEqual(status.json()["attempts"][0]["checkout_url"], first.json()["checkout_url"])
        self.assertNotIn(SANDBOX_KEY, status.content.decode())
        resolve_url = "/api/billing/checkout/resolve/?transaction_id=" + "txn_" + "c" * 26
        resolved = owner.get(resolve_url, secure=True)
        self.assertEqual(resolved.status_code, 200)
        self.assertEqual(resolved.json()["client_token"], SANDBOX_TOKEN)
        self.assertFalse(resolved.json()["payment_confirmed"])
        for keys in ((), (Fernet.generate_key().decode(),)):
            with self.subTest(keys_configured=bool(keys)), override_settings(PADDLE_ENCRYPTION_KEYS=keys):
                unavailable = owner.get(self.path, secure=True).json()
                self.assertFalse(unavailable["seller_configured"])
                self.assertIsNone(unavailable["attempts"][0]["checkout_url"])
                self.assertEqual(unavailable["client_token"], "")
                self.assertEqual(owner.get(resolve_url, secure=True).status_code, 404)
        self.assertEqual(self.browser(self.foreign).get(resolve_url, secure=True).status_code, 404)
        self.assertEqual(self.browser(self.admin).get(resolve_url, secure=True).status_code, 404)
        self.assertFalse(PaddleSubscription.objects.filter(organization=self.organization).exists())
        PaddleSubscription.objects.create(organization=self.organization, environment="sandbox",
            customer_id="ctm_" + "a" * 26, subscription_id="sub_" + "b" * 26, status="active")
        self.assertIsNone(owner.get(self.path, secure=True).json()["attempts"][0]["checkout_url"])
        self.assertEqual(owner.get(self.path, secure=True).json()["billing_access_state"], "unverified")
        self.assertEqual(owner.get(resolve_url, secure=True).status_code, 404)

    def test_outage_is_unknown_and_unconfigured_denies_without_provider_call(self):
        owner = self.browser(self.owner)
        with override_settings(PADDLE_CHECKOUT_URL=""):
            self.assertEqual(self.post(owner, {"request_key": "owner-attempt-002"}).status_code, 409)
        self.assertFalse(PaddleCheckoutAttempt.objects.exists())
        with patch("tenancy.paddle_transport.paddle_price_get", return_value=catalog()), \
             patch("tenancy.paddle_transport.paddle_transaction_create",
                   side_effect=PaddleTransportError("provider_unavailable")) as create:
            first = self.post(owner, {"request_key": "owner-attempt-002"})
            self.assertEqual(first.status_code, 202)
            self.assertEqual((first.json()["state"], first.json()["checkout_url"]), ("unknown", None))
            self.assertEqual(self.post(owner, {"request_key": "owner-attempt-002"}).json(), first.json())
            self.assertEqual(create.call_count, 1)

    def test_source_loss_during_fresh_or_replayed_checkout_denies_link_without_reposting(self):
        from .paddle_checkout import reserve_paddle_checkout

        owner = self.browser(self.owner)
        key = {"request_key": "source-loss-attempt-001"}

        def create_then_begin_deletion(*, attempt, **kwargs):
            now = timezone.now()
            OrganizationDeletionRun.objects.create(organization=self.organization,
                source=OrganizationDeletionRun.Source.TRIAL_ELAPSED,
                eligible_at=now - timedelta(days=91), due_at=now - timedelta(days=1))
            return self.provider_response(attempt)

        with patch("tenancy.paddle_transport.paddle_price_get", return_value=catalog()), patch(
            "tenancy.paddle_transport.paddle_transaction_create", side_effect=create_then_begin_deletion) as create:
            response = self.post(owner, key)
            self.assertEqual(response.status_code, 403)
            self.assertNotIn("checkout_url", response.json())
            attempt = PaddleCheckoutAttempt.objects.get(organization=self.organization)
            self.assertEqual(attempt.state, "ready")
            self.assertEqual(attempt.transaction_id, "txn_" + "c" * 26)
            self.assertEqual(self.post(owner, key).status_code, 409)
            self.assertEqual(create.call_count, 1)

            # Remove only the synthetic deletion fixture to exercise the saved READY path.
            OrganizationDeletionRun.objects.filter(organization=self.organization).delete()

            def reserve_then_revoke(**kwargs):
                row = reserve_paddle_checkout(**kwargs)
                OrganizationMembership.objects.filter(organization=self.organization,
                    user=self.owner).update(role=MembershipRole.VIEWER)
                return row

            with patch("tenancy.paddle_checkout.reserve_paddle_checkout", side_effect=reserve_then_revoke):
                response = self.post(owner, key)
            self.assertEqual(response.status_code, 403)
            self.assertNotIn("checkout_url", response.json())
            attempt.refresh_from_db()
            self.assertEqual(attempt.state, "ready")
            self.assertEqual(create.call_count, 1)
