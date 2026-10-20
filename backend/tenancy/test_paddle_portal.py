import json
from unittest.mock import patch

from allauth.account.models import EmailAddress
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.test import TestCase, override_settings

from .models import AuditEvent, AuditEventType, MembershipRole, OrganizationMembership, PaddleSubscription
from .paddle_portal import create_organization_portal, parse_portal_link
from .paddle_seller import set_paddle_seller
from .test_paddle_attempt import PRICE, PRODUCT
from .test_paddle_seller import SANDBOX_KEY, SANDBOX_TOKEN
from .services import create_organization


CUSTOMER = "ctm_" + "a" * 26
SUBSCRIPTION = "sub_" + "b" * 26
SESSION = "cpls_" + "c" * 26
LINK = "https://sandbox-customer-portal.paddle.com/cpl_" + "d" * 26 + "?action=overview&token=pga_fixture.token"


@override_settings(PADDLE_ENVIRONMENT="sandbox", PADDLE_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),))
class PortalTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.staff = users.objects.create_superuser("portal-staff@example.com", "password")
        self.owner = users.objects.create_user("portal-owner@example.com", "password")
        self.other = users.objects.create_user("portal-other@example.com", "password")
        self.admin = users.objects.create_user("portal-admin@example.com", "password")
        EmailAddress.objects.create(user=self.owner, email=self.owner.email, verified=True, primary=True)
        self.organization = create_organization(user=self.owner, name="Portal org")
        OrganizationMembership.objects.create(organization=self.organization, user=self.admin, role=MembershipRole.ADMIN)
        set_paddle_seller(actor=self.staff, environment="sandbox", api_key=SANDBOX_KEY,
                          webhook_secret="fixture-signing-secret", client_token=SANDBOX_TOKEN,
                          product_id=PRODUCT, price_id=PRICE, currency="USD", amount="14900", interval="month", frequency=1)
        PaddleSubscription.objects.create(organization=self.organization, environment="sandbox",
                                          customer_id=CUSTOMER, subscription_id=SUBSCRIPTION, status="past_due")

    def test_only_owner_with_current_provider_identity_gets_temporary_link(self):
        calls = []

        def get(**kwargs):
            calls.append(("get", kwargs["subscription_id"]))
            return {"data": {"id": SUBSCRIPTION, "customer_id": CUSTOMER, "status": "past_due"}}

        def create(**kwargs):
            calls.append(("create", kwargs["customer_id"]))
            return {"data": {"id": SESSION, "customer_id": CUSTOMER,
                              "urls": {"general": {"overview": LINK}}}}

        self.assertEqual(create_organization_portal(organization=self.organization, actor=self.owner,
                                                     subscription_get=get, portal_create=create), LINK)
        self.assertEqual(calls, [("get", SUBSCRIPTION), ("create", CUSTOMER)])
        for actor in (self.admin, self.other):
            with self.subTest(actor=actor.email), self.assertRaises(PermissionDenied):
                create_organization_portal(organization=self.organization, actor=actor,
                                           subscription_get=get, portal_create=create)
        self.assertEqual(calls, [("get", SUBSCRIPTION), ("create", CUSTOMER)])

    def test_foreign_provider_customer_and_host_fail_closed_without_leak(self):
        def create(**_):
            raise AssertionError("Portal must not be created when provider customer differs")

        with self.assertRaises(ValidationError):
            create_organization_portal(organization=self.organization, actor=self.owner,
                subscription_get=lambda **_: {"data": {"id": SUBSCRIPTION, "customer_id": "ctm_" + "z" * 26,
                                                    "status": "active"}}, portal_create=create)
        for bad in (LINK.replace("sandbox-customer-portal", "evil"),
                    LINK + "&next=https://evil.example", LINK.replace("pga_fixture.token", "bad%0dtoken")):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                parse_portal_link(response={"data": {"id": SESSION, "customer_id": CUSTOMER,
                    "urls": {"general": {"overview": bad}}}}, environment="sandbox", customer_id=CUSTOMER)
        self.assertNotIn("pga_fixture.token", json.dumps(list(PaddleSubscription.objects.values())))

    def test_role_revocation_during_provider_session_disallows_delivery(self):
        def create(**_):
            OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(
                role=MembershipRole.VIEWER)
            return {"data": {"id": SESSION, "customer_id": CUSTOMER, "urls": {"general": {"overview": LINK}}}}

        with self.assertRaises(PermissionDenied):
            create_organization_portal(organization=self.organization, actor=self.owner,
                subscription_get=lambda **_: {"data": {"id": SUBSCRIPTION, "customer_id": CUSTOMER,
                                                    "status": "active"}}, portal_create=create)

    def test_private_portal_api_uses_csrf_no_store_and_never_persists_signed_url(self):
        def browser(user):
            client = Client(enforce_csrf_checks=True)
            client.force_login(user)
            client.get("/_allauth/browser/v1/auth/session")
            return client

        def post(client, csrf=True):
            headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value} if csrf else {}
            return client.post(f"/api/organizations/{self.organization.pk}/billing/portal/",
                               data="{}", content_type="application/json", **headers)

        owner = browser(self.owner)
        with patch("tenancy.paddle_transport.paddle_subscription_get", return_value={"data": {
                 "id": SUBSCRIPTION, "customer_id": CUSTOMER, "status": "past_due"}}) as get, \
             patch("tenancy.paddle_transport.paddle_portal_create", return_value={"data": {
                 "id": SESSION, "customer_id": CUSTOMER, "urls": {"general": {"overview": LINK}}}}) as create:
            self.assertEqual(post(owner, csrf=False).status_code, 403)
            self.assertEqual(post(browser(self.admin)).status_code, 403)
            response = post(owner)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Cache-Control"], "private, no-store")
            self.assertEqual(response["Referrer-Policy"], "no-referrer")
            self.assertEqual(response.json(), {"portal_url": LINK})
            self.assertEqual((get.call_count, create.call_count), (1, 1))
        status = owner.get(f"/api/organizations/{self.organization.pk}/billing/checkout/")
        self.assertTrue(status.json()["subscription_linked"])
        self.assertTrue(status.json()["portal_available"])
        self.assertNotIn("pga_fixture", status.content.decode())
        self.assertNotIn("pga_fixture", json.dumps(list(AuditEvent.objects.values("details"))))
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.BILLING_PORTAL_OPENED).count(), 1)
