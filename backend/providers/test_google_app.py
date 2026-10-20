import json
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

from allauth.account.models import EmailAddress
from cryptography.fernet import Fernet
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from integrations.google_tokens import GoogleTokenError, SCOPE, encrypt_refresh_token
from integrations.ga4_oauth import (SCOPE as GA4_SCOPE, begin_ga4_oauth_intent,
                                    complete_ga4_oauth, encrypt_ga4_refresh_token, revoke_ga4_grant)
from integrations.models import GA4OAuthGrant, GA4OAuthIntent, IntegrationConnection, GoogleOAuthGrant, GoogleOAuthIntent
from tenancy.models import AuditEvent
from tenancy.services import create_organization, create_project

from .admin import GoogleOAuthApplicationAdmin
from .google_app import google_analytics_oauth_client, google_oauth_client
from .models import GoogleOAuthApplication


KEY = Fernet.generate_key().decode()
CALLBACK = "https://app.example.com/api/integrations/google-search-console/oauth/callback/"


@override_settings(
    GOOGLE_OAUTH_CLIENT_ID="", GOOGLE_OAUTH_CLIENT_SECRET="", GOOGLE_OAUTH_REDIRECT_URI="",
    GOOGLE_OAUTH_ENCRYPTION_KEYS=(KEY,), FRONTEND_ORIGIN="https://app.example.com",
    ALLOWED_HOSTS=["app.example.com"], SECURE_SSL_REDIRECT=False, STAFF_MFA_REQUIRED=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class GoogleApplicationTests(TestCase):
    path = "/api/platform/integrations/google-oauth-app/"

    def setUp(self):
        cache.clear()
        self.staff = get_user_model().objects.create_superuser("google-operator@example.com", "test-password")
        self.owner = get_user_model().objects.create_user("google-owner@example.com", "test-password")
        EmailAddress.objects.create(user=self.owner, email=self.owner.email, verified=True, primary=True)
        organization = create_organization(user=self.owner, name="Google test organization")
        self.project = create_project(organization=organization, user=self.owner, name="Google test project",
                                      canonical_origin="https://project.example.com")

    def browser(self, user):
        client = Client(enforce_csrf_checks=True, HTTP_HOST="app.example.com")
        client.force_login(user)
        client.get("/_allauth/browser/v1/auth/session", secure=True)
        return client

    def request(self, browser, method, path, payload=None, *, csrf=True):
        headers = ({"HTTP_X_CSRFTOKEN": browser.cookies["csrftoken"].value,
                    "HTTP_REFERER": "https://app.example.com/"} if csrf else {})
        return getattr(browser, method)(path, data=json.dumps(payload) if payload is not None else {},
                                        content_type="application/json",
                                        secure=True, **headers)

    def configure(self, browser, secret="dummy-client-secret"):
        return self.request(browser, "post", self.path, {
            "client_id": "fixture-client-id", "client_secret": secret, "redirect_uri": CALLBACK,
        })

    def test_staff_write_only_client_uses_existing_oauth_boundary_and_revocation_blocks_env_fallback(self):
        staff = self.browser(self.staff)
        self.assertEqual(self.configure(staff).status_code, 200)
        record = GoogleOAuthApplication.objects.get(key="primary")
        self.assertNotIn("dummy-client-secret", record.encrypted_secret)
        self.assertTrue(record.encrypted_secret.startswith("v1:"))
        self.assertNotIn("encrypted_secret", GoogleOAuthApplicationAdmin(GoogleOAuthApplication, admin.site).get_fields(None, record))
        self.assertEqual(self.request(staff, "get", self.path).json(), {"state": "active", "redirect_uri": CALLBACK})
        self.assertNotIn("dummy-client-secret", json.dumps(list(AuditEvent.objects.values("details"))))
        client = google_oauth_client()
        self.assertEqual((client.client_id, client.client_secret, client.redirect_uri),
                         ("fixture-client-id", "dummy-client-secret", CALLBACK))
        self.assertNotIn("dummy-client-secret", repr(client))

        owner = self.browser(self.owner)
        url = (f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}"
               "/search-console/oauth/start/")
        started = self.request(owner, "post", url, {})
        self.assertEqual(started.status_code, 201, started.content)
        self.assertEqual(parse_qs(urlsplit(started.json()["authorization_url"]).query)["client_id"],
                         ["fixture-client-id"])
        self.assertEqual(self.configure(staff, "replaced-secret").status_code, 409)
        self.assertEqual(self.request(staff, "delete", self.path).status_code, 409)
        GoogleOAuthIntent.objects.filter(project=self.project).update(status=GoogleOAuthIntent.Status.DENIED,
                                                                       used_at=timezone.now())
        self.assertEqual(self.configure(staff, "replaced-secret").status_code, 200)
        self.assertEqual(google_oauth_client().client_secret, "replaced-secret")
        self.assertEqual(self.request(staff, "delete", self.path).json(), {"revoked": True})
        with override_settings(GOOGLE_OAUTH_CLIENT_ID="legacy-id", GOOGLE_OAUTH_CLIENT_SECRET="legacy-secret",
                               GOOGLE_OAUTH_REDIRECT_URI=CALLBACK):
            with self.assertRaises(GoogleTokenError):
                google_oauth_client()

    def test_unconfigured_and_wrong_role_or_host_cannot_create_client(self):
        with self.assertRaises(GoogleTokenError):
            google_oauth_client()
        owner = self.browser(self.owner)
        self.assertEqual(self.configure(owner).status_code, 403)
        staff = self.browser(self.staff)
        self.assertEqual(self.configure(staff).status_code, 200)
        self.assertEqual(self.request(staff, "get", self.path).status_code, 200)
        self.assertEqual(self.request(staff, "post", self.path, {
            "client_id": "fixture-client-id", "client_secret": "invalid", "redirect_uri": "https://evil.example/callback/",
        }).status_code, 409)
        self.assertEqual(google_oauth_client().client_secret, "dummy-client-secret")

    def test_existing_unrevoked_grant_prevents_client_rotation(self):
        staff = self.browser(self.staff)
        self.assertEqual(self.configure(staff).status_code, 200)
        GoogleOAuthGrant.objects.create(
            organization=self.project.organization, project=self.project, actor=self.owner,
            encrypted_refresh_token=encrypt_refresh_token("fixture-refresh-token"), scope=SCOPE,
            verified_at=timezone.now() - timedelta(minutes=1),
        )
        self.assertEqual(self.configure(staff, "replacement-secret").status_code, 409)
        self.assertEqual(self.request(staff, "delete", self.path).status_code, 409)
        self.assertEqual(google_oauth_client().client_secret, "dummy-client-secret")

    def test_platform_client_write_requires_staff_mfa_when_enforced(self):
        staff = self.browser(self.staff)
        with override_settings(STAFF_MFA_REQUIRED=True):
            response = self.configure(staff)
        self.assertEqual((response.status_code, response.json()["errors"][0]["code"]), (403, "mfa_required"))
        self.assertFalse(GoogleOAuthApplication.objects.exists())

    @override_settings(GOOGLE_ANALYTICS_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),))
    def test_independent_analytics_app_staff_entry_rotation_and_revoke(self):
        path = "/api/platform/integrations/google-analytics-app/"
        callback = "https://app.example.com/api/integrations/google-analytics/oauth/callback/"
        payload = {"client_id": "analytics-fixture", "client_secret": "analytics-secret", "redirect_uri": callback}
        staff = self.browser(self.staff)
        self.assertEqual(self.configure(staff).status_code, 200)
        self.assertEqual(self.request(staff, "post", path, payload, csrf=False).status_code, 403)
        self.assertEqual(self.request(self.browser(self.owner), "post", path, payload).status_code, 403)
        with override_settings(STAFF_MFA_REQUIRED=True):
            self.assertEqual(self.request(staff, "post", path, payload).status_code, 403)
        response = self.request(staff, "post", path, payload)
        self.assertEqual(response.status_code, 200, response.content)
        record = GoogleOAuthApplication.objects.get(key="analytics")
        self.assertNotIn("analytics-secret", record.encrypted_secret)
        self.assertNotIn("encrypted_secret", GoogleOAuthApplicationAdmin(GoogleOAuthApplication, admin.site).get_fields(None, record))
        self.assertEqual(self.request(staff, "get", path).json(), {"state": "active", "redirect_uri": callback})
        self.assertNotIn("analytics-secret", json.dumps(list(AuditEvent.objects.values("details"))))
        self.assertEqual(google_analytics_oauth_client().client_secret, "analytics-secret")
        self.assertEqual(google_oauth_client().client_secret, "dummy-client-secret")
        self.assertNotIn("analytics-secret", repr(google_analytics_oauth_client()))
        GA4OAuthIntent.objects.create(organization=self.project.organization, project=self.project,
            actor=self.owner, state_digest="a" * 64, session_digest="b" * 64,
            redirect_uri=callback, expires_at=timezone.now() + timedelta(minutes=2))
        self.assertEqual(self.request(staff, "delete", path).status_code, 200)
        self.assertEqual(GA4OAuthIntent.objects.get().status, GA4OAuthIntent.Status.DENIED)
        with self.assertRaises(GoogleTokenError):
            google_analytics_oauth_client()
        self.assertEqual(google_oauth_client().client_secret, "dummy-client-secret")

    @override_settings(GOOGLE_ANALYTICS_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),))
    def test_emergency_analytics_app_revoke_disables_source_and_keeps_remote_revoke_recoverable(self):
        staff = self.browser(self.staff)
        self.assertEqual(self.configure(staff).status_code, 200)
        path = "/api/platform/integrations/google-analytics-app/"
        callback = "https://app.example.com/api/integrations/google-analytics/oauth/callback/"
        self.assertEqual(self.request(staff, "post", path, {
            "client_id": "analytics-fixture", "client_secret": "analytics-secret", "redirect_uri": callback,
        }).status_code, 200)
        grant = GA4OAuthGrant.objects.create(organization=self.project.organization, project=self.project,
            actor=self.owner, encrypted_refresh_token=encrypt_ga4_refresh_token("analytics-refresh"),
            scope=GA4_SCOPE, property_id="12345", selected_origins=[self.project.canonical_origin],
            state=GA4OAuthGrant.State.ACTIVE, verified_at=timezone.now())
        source = IntegrationConnection.objects.create(project=self.project, provider="google_analytics_4",
            external_property_id="12345", credential_reference=grant.credential_reference,
            capabilities=["api_sync", "landing_metrics"], available_dimensions=["hostname", "landing_page"],
            source_semantics="ga4_landing_pages", source_semantics_version="ga4-data-v1", currency="USD")
        self.assertEqual(self.request(staff, "delete", path).status_code, 200)
        grant.refresh_from_db()
        source.refresh_from_db()
        self.assertEqual((grant.state, source.state),
            (GA4OAuthGrant.State.REVOCATION_PENDING, IntegrationConnection.State.DISCONNECTED))
        self.assertTrue(grant.encrypted_refresh_token.startswith("v1:"))
        self.assertEqual(GoogleOAuthApplication.objects.get(key="analytics").encrypted_secret, "")
        with self.assertRaises(GoogleTokenError):
            google_analytics_oauth_client()
        self.assertEqual(google_oauth_client().client_secret, "dummy-client-secret")
        self.assertEqual(self.request(staff, "post", path, {
            "client_id": "new", "client_secret": "new-secret", "redirect_uri": callback,
        }).status_code, 409)
        revoked = revoke_ga4_grant(grant=grant, user=self.owner, revoke=lambda **_: True)
        self.assertEqual((revoked.state, revoked.encrypted_refresh_token), (GA4OAuthGrant.State.REVOKED, ""))

    @override_settings(GOOGLE_ANALYTICS_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),))
    def test_app_revoked_during_consumed_callback_quarantines_new_grant(self):
        staff = self.browser(self.staff)
        callback = "https://app.example.com/api/integrations/google-analytics/oauth/callback/"
        path = "/api/platform/integrations/google-analytics-app/"
        self.assertEqual(self.request(staff, "post", path, {
            "client_id": "analytics-fixture", "client_secret": "analytics-secret", "redirect_uri": callback,
        }).status_code, 200)
        _, state = begin_ga4_oauth_intent(project=self.project, user=self.owner,
            session_key="consent-browser-session-123456")
        def exchange(**_):
            self.assertEqual(self.request(staff, "delete", path).status_code, 200)
            return {"scope": GA4_SCOPE, "token_type": "Bearer", "access_token": "ACCESS_SECRET",
                    "refresh_token": "REFRESH_SECRET", "expires_in": 3600}
        grant = complete_ga4_oauth(user=self.owner, session_key="consent-browser-session-123456",
            state=state, callback_url=callback, code="once-code", client_id="analytics-fixture",
            client_secret="analytics-secret", transport=exchange)
        self.assertEqual(grant.state, GA4OAuthGrant.State.REVOCATION_PENDING)
        self.assertTrue(grant.encrypted_refresh_token.startswith("v1:"))
