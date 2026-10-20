import json
import os
from unittest.mock import patch

from allauth.account.models import EmailAddress
from allauth.mfa.models import Authenticator
from cryptography.fernet import Fernet
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings

from tenancy.models import AuditEvent, MembershipRole, OrganizationMembership
from tenancy.services import create_organization

from .admin import AIProviderAccountAdmin
from .models import AIProvider, AIProviderAccount, AIProviderSecret
from .services import (create_provider, create_provider_account, resolve_provider_secret,
                       revoke_provider_account, set_provider_secret)


OLD_KEY = Fernet.generate_key().decode()
NEW_KEY = Fernet.generate_key().decode()


@override_settings(PROVIDER_ENCRYPTION_KEYS=(OLD_KEY,), STAFF_MFA_REQUIRED=False,
                   CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
                   SECURE_SSL_REDIRECT=False)
class ProviderCredentialTests(TestCase):
    def setUp(self):
        cache.clear()
        self.operator = get_user_model().objects.create_superuser("key-operator@example.com", "test-password")
        self.provider = create_provider(actor=self.operator, key="key-provider", name="AI provider",
                                        kind=AIProvider.Kind.OPENAI, enabled=True)
        self.account = create_provider_account(actor=self.operator, provider=self.provider,
                                               label="Platform", secret_reference="env:OPENAI_API_KEY")
        self.path = f"/api/platform/providers/{self.provider.pk}/accounts/{self.account.pk}/credential/"

    def browser(self, user):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(user)
        browser.get("/_allauth/browser/v1/auth/session", secure=True)
        return browser

    def post(self, browser, payload, *, csrf=True):
        headers = ({"HTTP_X_CSRFTOKEN": browser.cookies["csrftoken"].value,
                    "HTTP_REFERER": "https://testserver/"} if csrf else {})
        return browser.post(self.path, data=json.dumps(payload), content_type="application/json",
                            secure=True, **headers)

    def test_write_only_api_encrypts_and_worker_resolution_prefers_rotatable_secret(self):
        browser = self.browser(self.operator)
        self.assertEqual(self.post(browser, {"secret": "dummy-first-key"}, csrf=False).status_code, 403)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "environment-value"}):
            response = self.post(browser, {"secret": "dummy-first-key"})
            self.assertEqual((response.status_code, response.json()),
                             (200, {"configured": True, "account_id": self.account.pk}))
            self.assertEqual(resolve_provider_secret(self.account), "dummy-first-key")
        stored = AIProviderSecret.objects.get(account=self.account)
        self.assertTrue(stored.ciphertext.startswith("v1:"))
        self.assertNotIn("dummy-first-key", stored.ciphertext)
        self.assertFalse(admin.site.is_registered(AIProviderSecret))
        self.assertNotIn("ciphertext", AIProviderAccountAdmin(AIProviderAccount, admin.site).get_fields(None, self.account))
        self.assertNotIn("dummy-first-key", response.content.decode() +
                         json.dumps(list(AuditEvent.objects.values("details"))))
        self.assertEqual(response["Cache-Control"], "private, no-store")

        with override_settings(PROVIDER_ENCRYPTION_KEYS=(NEW_KEY, OLD_KEY)):
            self.assertEqual(resolve_provider_secret(self.account), "dummy-first-key")
            self.assertEqual(self.post(browser, {"secret": "dummy-second-key"}).status_code, 200)
        with override_settings(PROVIDER_ENCRYPTION_KEYS=(NEW_KEY,)):
            self.assertEqual(resolve_provider_secret(self.account), "dummy-second-key")
        with override_settings(PROVIDER_ENCRYPTION_KEYS=(OLD_KEY,)):
            with self.assertRaises(ValidationError):
                resolve_provider_secret(self.account)
        revoke_provider_account(actor=self.operator, account=self.account)
        with self.assertRaises(PermissionDenied):
            resolve_provider_secret(self.account)
        self.assertEqual(self.post(browser, {"secret": "dummy-third-key"}).status_code, 400)

    def test_staff_permission_mfa_scope_and_unconfigured_encryption_fail_closed(self):
        customer = get_user_model().objects.create_user("customer@example.com", "test-password")
        staff = get_user_model().objects.create_user("unprivileged@example.com", "test-password", is_staff=True)
        self.assertEqual(self.post(self.browser(customer), {"secret": "dummy-secret"}).status_code, 403)
        self.assertEqual(self.post(self.browser(staff), {"secret": "dummy-secret"}).status_code, 403)
        browser = self.browser(self.operator)
        with override_settings(STAFF_MFA_REQUIRED=True):
            denied = self.post(browser, {"secret": "dummy-secret"})
            self.assertEqual(denied.json()["errors"][0]["code"], "mfa_required")
            Authenticator.objects.create(user=self.operator, type=Authenticator.Type.TOTP,
                                         data={"secret": "test-only"})
            denied = self.post(browser, {"secret": "dummy-secret"})
            self.assertEqual(denied.json()["errors"][0]["code"], "mfa_authentication_required")
        self.assertFalse(AIProviderSecret.objects.exists())
        browser = self.browser(self.operator)
        for path in (f"/api/platform/providers/{self.provider.pk + 1}/accounts/{self.account.pk}/credential/",
                     f"/api/platform/providers/{self.provider.pk}/accounts/{self.account.pk + 1}/credential/"):
            self.assertEqual(browser.post(path, data=json.dumps({"secret": "dummy-secret"}),
                                          content_type="application/json", secure=True,
                                          HTTP_X_CSRFTOKEN=browser.cookies["csrftoken"].value,
                                          HTTP_REFERER="https://testserver/").status_code, 404)
        with override_settings(PROVIDER_ENCRYPTION_KEYS=()):
            self.assertEqual(self.post(browser, {"secret": "dummy-secret"}).status_code, 400)
        self.assertFalse(AIProviderSecret.objects.exists())
        with self.assertRaises(ValidationError):
            set_provider_secret(actor=self.operator, account=self.account, secret="invalid\nkey")

    def test_staff_can_create_provider_and_key_account_without_env_secret_then_revoke(self):
        browser = self.browser(self.operator)
        headers = {"HTTP_X_CSRFTOKEN": browser.cookies["csrftoken"].value,
                   "HTTP_REFERER": "https://testserver/"}
        listing = browser.get("/api/platform/providers/", secure=True)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["accounts"][0]["stored"], False)
        self.assertNotIn("OPENAI_API_KEY", listing.content.decode())

        response = browser.post("/api/platform/providers/", data=json.dumps({
            "key": "compatible", "name": "Compatible", "kind": "openai_compatible",
            "base_url": "https://compatible.example/v1",
        }), content_type="application/json", secure=True, **headers)
        self.assertEqual(response.status_code, 201, response.content)
        provider_id = response.json()["id"]
        accounts_path = f"/api/platform/providers/{provider_id}/accounts/"
        with override_settings(PROVIDER_ENCRYPTION_KEYS=()):
            rejected = browser.post(accounts_path, data=json.dumps({"label": "Platform", "secret": "dummy-secret"}),
                                    content_type="application/json", secure=True, **headers)
        self.assertEqual(rejected.status_code, 400)
        self.assertFalse(AIProviderAccount.objects.filter(provider_id=provider_id).exists())

        created = browser.post(accounts_path, data=json.dumps({"label": "Platform", "secret": "dummy-secret"}),
                               content_type="application/json", secure=True, **headers)
        self.assertEqual(created.status_code, 201, created.content)
        account = AIProviderAccount.objects.get(pk=created.json()["id"])
        self.assertEqual(account.secret_reference, "")
        self.assertEqual(AIProviderAccountAdmin(AIProviderAccount, admin.site).credential_status(account), "configured")
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            self.assertEqual(resolve_provider_secret(account), "dummy-secret")
        self.assertNotIn("dummy-secret", created.content.decode() +
                         browser.get("/api/platform/providers/", secure=True).content.decode())
        self.assertTrue(next(item for item in browser.get("/api/platform/providers/", secure=True).json()["accounts"]
                             if item["id"] == account.pk)["stored"])

        revoked = browser.delete(f"/api/platform/providers/{provider_id}/accounts/{account.pk}/credential/",
                                 secure=True, **headers)
        self.assertEqual((revoked.status_code, revoked.json()), (200, {"revoked": True}))
        self.assertFalse(AIProviderSecret.objects.filter(account=account).exists())
        with self.assertRaises(PermissionDenied):
            resolve_provider_secret(account)

    def test_organization_keys_are_tenant_owned_and_inaccessible_to_staff_platform_actions(self):
        owner = get_user_model().objects.create_user("byok-owner@example.com", "test-password")
        other = get_user_model().objects.create_user("byok-other@example.com", "test-password")
        viewer = get_user_model().objects.create_user("byok-viewer@example.com", "test-password")
        for user in (owner, other):
            EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
        organization = create_organization(user=owner, name="BYOK organization")
        foreign = create_organization(user=other, name="Other organization")
        OrganizationMembership.objects.create(user=viewer, organization=organization, role=MembershipRole.VIEWER)
        path = f"/api/organizations/{organization.pk}/provider-accounts/"
        self.assertEqual(self.browser(other).get(path, secure=True).status_code, 404)
        self.assertEqual(self.browser(viewer).get(path, secure=True).status_code, 403)
        browser = self.browser(owner)
        self.assertEqual(browser.get(path, secure=True).json()["accounts"], [])
        headers = {"HTTP_X_CSRFTOKEN": browser.cookies["csrftoken"].value, "HTTP_REFERER": "https://testserver/"}
        with override_settings(PROVIDER_ENCRYPTION_KEYS=()):
            denied = browser.post(path, data=json.dumps({"provider_id": self.provider.pk,
                                                         "label": "Own key", "secret": "dummy-owned-key"}),
                                  content_type="application/json", secure=True, **headers)
        self.assertEqual(denied.status_code, 400)
        self.assertFalse(AIProviderAccount.objects.filter(organization=organization).exists())
        created = browser.post(path, data=json.dumps({"provider_id": self.provider.pk,
                                                     "label": "Own key", "secret": "dummy-owned-key"}),
                               content_type="application/json", secure=True, **headers)
        self.assertEqual(created.status_code, 201, created.content)
        account = AIProviderAccount.objects.get(pk=created.json()["id"])
        self.assertEqual((account.organization_id, account.secret_reference), (organization.pk, ""))
        self.assertNotIn("dummy-owned-key", created.content.decode() + browser.get(path, secure=True).content.decode())
        self.assertEqual(resolve_provider_secret(account, organization=organization), "dummy-owned-key")
        with self.assertRaises(PermissionDenied):
            resolve_provider_secret(account)
        with self.assertRaises(PermissionDenied):
            resolve_provider_secret(account, organization=foreign)
        with self.assertRaises(PermissionDenied):
            set_provider_secret(actor=self.operator, account=account, secret="staff-secret")
        with self.assertRaises(PermissionDenied):
            revoke_provider_account(actor=self.operator, account=account)
        staff_browser = self.browser(self.operator)
        self.assertEqual(staff_browser.post(
            f"/api/platform/providers/{self.provider.pk}/accounts/{account.pk}/credential/",
            data=json.dumps({"secret": "staff-secret"}), content_type="application/json", secure=True,
            HTTP_X_CSRFTOKEN=staff_browser.cookies["csrftoken"].value,
            HTTP_REFERER="https://testserver/",
        ).status_code, 404)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AIProviderAccount.objects.filter(pk=account.pk).update(secret_reference="env:OPENAI_API_KEY")

        foreign_browser = self.browser(other)
        foreign_headers = {"HTTP_X_CSRFTOKEN": foreign_browser.cookies["csrftoken"].value,
                           "HTTP_REFERER": "https://testserver/"}
        self.assertEqual(foreign_browser.post(
            f"/api/organizations/{foreign.pk}/provider-accounts/{account.pk}/credential/",
            data=json.dumps({"secret": "foreign-secret"}), content_type="application/json", secure=True,
            **foreign_headers).status_code, 404)
        self.assertEqual(browser.delete(f"/api/organizations/{organization.pk}/provider-accounts/{account.pk}/credential/",
                                        secure=True, **headers).status_code, 200)
        self.assertFalse(AIProviderSecret.objects.filter(account=account).exists())
        with self.assertRaises(PermissionDenied):
            resolve_provider_secret(account, organization=organization)
