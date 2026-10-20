import json
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from allauth.account.models import EmailAddress
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from providers.google_app import set_google_oauth_application
from tenancy.models import MembershipRole, OrganizationMembership
from tenancy.services import create_organization, create_project

from .ga4_oauth import (SCOPE, complete_ga4_oauth, decrypt_ga4_refresh_token,
                         link_ga4_source, revoke_ga4_grant, select_ga4_property)
from .google_tokens import GoogleTokenError, GoogleTokens
from .models import GA4OAuthGrant, GA4OAuthIntent, IntegrationConnection


KEY = Fernet.generate_key().decode()
CALLBACK = "https://app.example.com/api/integrations/google-analytics/oauth/callback/"


@override_settings(GOOGLE_ANALYTICS_ENCRYPTION_KEYS=(KEY,), FRONTEND_ORIGIN="https://app.example.com",
                   ALLOWED_HOSTS=["app.example.com"], SECURE_SSL_REDIRECT=False, STAFF_MFA_REQUIRED=False,
                   CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class GA4BrowserViewsTests(TestCase):
    def setUp(self):
        cache.clear()
        users = get_user_model().objects
        self.owner = users.create_user("analytics-owner@example.test", password="test-password")
        self.viewer = users.create_user("analytics-viewer@example.test", password="test-password")
        self.foreign = users.create_user("analytics-other@example.test", password="test-password")
        for user in (self.owner, self.viewer, self.foreign):
            EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
        self.staff = users.create_superuser("analytics-staff@example.test", "test-password")
        organization = create_organization(user=self.owner, name="Analytics consent fixture")
        self.project = create_project(organization=organization, user=self.owner,
            name="Analytics project", canonical_origin="https://project.example")
        OrganizationMembership.objects.create(organization=organization, user=self.viewer, role=MembershipRole.VIEWER)
        set_google_oauth_application(actor=self.staff, key="analytics", client_id="analytics-client",
            client_secret="analytics-secret", redirect_uri=CALLBACK)
        self.prefix = f"/api/organizations/{organization.pk}/projects/{self.project.pk}/analytics/oauth/"

    def browser(self, user):
        client = Client(enforce_csrf_checks=True, HTTP_HOST="app.example.com")
        client.force_login(user)
        client.get("/_allauth/browser/v1/auth/session", secure=True)
        return client

    def post(self, client, path, body=None, csrf=True):
        headers = ({"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value,
                    "HTTP_REFERER": "https://app.example.com/"} if csrf else {})
        return client.post(path, data=json.dumps(body if body is not None else {}),
                           content_type="application/json", secure=True, **headers)

    def begin(self, browser):
        response = self.post(browser, self.prefix + "start/")
        self.assertEqual(response.status_code, 201, response.content)
        url = response.json()["authorization_url"]
        values = parse_qs(urlsplit(url).query)
        self.assertEqual(values["scope"], [SCOPE])
        self.assertEqual(values["redirect_uri"], [CALLBACK])
        return values["state"][0]

    def consent(self, browser):
        state = self.begin(browser)
        def exchange(**kwargs):
            return complete_ga4_oauth(**kwargs, transport=lambda **_: {
                "scope": SCOPE, "token_type": "Bearer", "access_token": "ACCESS_SECRET",
                "refresh_token": "REFRESH_SECRET", "expires_in": 3600})
        with patch("integrations.ga4_views.complete_ga4_oauth", side_effect=exchange):
            result = browser.get(CALLBACK.replace("https://app.example.com", ""),
                                 {"state": state, "code": "once-code"}, secure=True)
        self.assertEqual(result.status_code, 303)
        self.assertEqual(result["Location"], f"https://app.example.com/app/onboarding/{self.project.organization_id}/{self.project.pk}")
        self.assertIn("no-store", result["Cache-Control"])
        self.assertNotIn("once-code", result["Location"])
        return state, GA4OAuthGrant.objects.get(project=self.project)

    def test_start_denial_and_callback_replay_are_browser_and_role_scoped(self):
        owner, viewer, foreign = (self.browser(actor) for actor in (self.owner, self.viewer, self.foreign))
        self.assertEqual(self.post(owner, self.prefix + "start/", csrf=False).status_code, 403)
        self.assertEqual(self.post(viewer, self.prefix + "start/").status_code, 403)
        self.assertEqual(self.post(foreign, self.prefix + "start/").status_code, 404)
        state, grant = self.consent(owner)
        self.assertEqual(grant.state, GA4OAuthGrant.State.PENDING_SELECTION)
        self.assertEqual(decrypt_ga4_refresh_token(grant.encrypted_refresh_token), "REFRESH_SECRET")
        self.assertEqual(owner.get(self.prefix + "grants/", secure=True).json()["grants"][0]["source_status"],
                         "not_linked_no_data_sync")
        self.assertEqual(viewer.get(self.prefix + "grants/", secure=True).status_code, 403)
        self.assertEqual(foreign.get(self.prefix + "grants/", secure=True).status_code, 404)
        duplicate = owner.get(CALLBACK.replace("https://app.example.com", ""),
                              {"state": state, "code": "once-code"}, secure=True)
        self.assertEqual(duplicate.status_code, 303)
        self.assertEqual(GA4OAuthGrant.objects.count(), 1)
        denied = self.begin(owner)
        result = owner.get(CALLBACK.replace("https://app.example.com", ""),
                           {"state": denied, "error": "access_denied"}, secure=True)
        self.assertEqual(result.status_code, 303)
        self.assertEqual(GA4OAuthIntent.objects.get(state_digest__isnull=False,
            status=GA4OAuthIntent.Status.DENIED).status, GA4OAuthIntent.Status.DENIED)

    def test_property_selection_and_retryable_remote_revoke_never_claim_a_sync(self):
        owner = self.browser(self.owner)
        _, grant = self.consent(owner)
        def select(**kwargs):
            return select_ga4_property(**kwargs,
                refresh=lambda **_: GoogleTokens("ACCESS_SECRET", None, timezone.now()),
                get_property=lambda **_: {"name": "properties/12345", "timeZone": "UTC", "currencyCode": "USD"},
                list_streams=lambda **_: {"dataStreams": [
                    {"name": "properties/12345/dataStreams/123", "type": "WEB_DATA_STREAM",
                     "webStreamData": {"defaultUri": "https://project.example"}}]},
                check_compatibility=lambda **_: True)
        select_url = self.prefix + f"grants/{grant.pk}/select/"
        with patch("integrations.ga4_views.select_ga4_property", side_effect=select):
            self.assertEqual(self.post(owner, select_url, {"property_id": "12345", "origin": "https://project.example",
                "expected_revision": 0}, csrf=False).status_code, 403)
            result = self.post(owner, select_url, {"property_id": "12345", "origin": "https://project.example",
                "expected_revision": 0})
            self.assertEqual(result.status_code, 200, result.content)
            self.assertEqual((result.json()["state"], result.json()["source_status"]),
                             ("pending_selection", "not_linked_no_data_sync"))
            self.assertEqual(self.post(owner, select_url, {"property_id": "12345",
                "origin": "https://project.example", "expected_revision": 0}).status_code, 409)
        link_url = self.prefix + f"grants/{grant.pk}/link/"
        def link(**kwargs):
            return link_ga4_source(**kwargs,
                refresh=lambda **_: GoogleTokens("ACCESS_SECRET", None, timezone.now()),
                get_property=lambda **_: {"name": "properties/12345", "timeZone": "UTC", "currencyCode": "USD"},
                list_streams=lambda **_: {"dataStreams": [
                    {"name": "properties/12345/dataStreams/123", "type": "WEB_DATA_STREAM",
                     "webStreamData": {"defaultUri": "https://project.example"}}]},
                check_compatibility=lambda **_: True)
        with patch("integrations.ga4_views.link_ga4_source", side_effect=link):
            self.assertEqual(self.post(owner, link_url, {"expected_revision": 1}, csrf=False).status_code, 403)
            linked = self.post(owner, link_url, {"expected_revision": 1})
            self.assertEqual((linked.status_code, linked.json()["source_status"]),
                             (200, "configured_no_data_sync"))
        self.assertEqual(IntegrationConnection.objects.get(project=self.project).provider, "google_analytics_4")
        self.assertFalse(owner.get(self.prefix + "grants/", secure=True).json()["grants"][0]["source_status"] == "not_linked_no_data_sync")
        sources = owner.get(f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}/sources/",
                            secure=True).json()["sources"]
        self.assertEqual((sources[0]["scope_current"], sources[0]["api_sync_available"], sources[0]["data_status"]),
                         (True, False, "exact_origin_attribution_unavailable"))
        revoke_url = self.prefix + f"grants/{grant.pk}/revoke/"
        with patch("integrations.ga4_views.revoke_ga4_grant", side_effect=lambda **kwargs: revoke_ga4_grant(
            **kwargs, revoke=lambda **_: (_ for _ in ()).throw(GoogleTokenError("provider_unavailable")))):
            self.assertEqual(self.post(owner, revoke_url).status_code, 503)
        grant.refresh_from_db()
        self.assertEqual(grant.state, GA4OAuthGrant.State.REVOCATION_PENDING)
        with patch("integrations.ga4_views.revoke_ga4_grant", side_effect=lambda **kwargs: revoke_ga4_grant(
            **kwargs, revoke=lambda **_: True)):
            self.assertEqual(self.post(owner, revoke_url).json()["state"], "revoked")
        self.assertEqual(GA4OAuthGrant.objects.get(pk=grant.pk).encrypted_refresh_token, "")

    def test_private_ga4_queue_status_cancel_are_source_owned_and_untested_live(self):
        owner, viewer, foreign = (self.browser(actor) for actor in (self.owner, self.viewer, self.foreign))
        _, pending = self.consent(owner)
        from .ga4_oauth import select_ga4_property, link_ga4_source
        candidate = {"name": "properties/12345", "timeZone": "UTC", "currencyCode": "USD"}
        streams = {"dataStreams": [{"name": "properties/12345/dataStreams/123", "type": "WEB_DATA_STREAM",
                                    "webStreamData": {"defaultUri": "https://project.example"}}]}
        provider = dict(refresh=lambda **_: GoogleTokens("ACCESS_SECRET", None, timezone.now()),
            get_property=lambda **_: candidate, list_streams=lambda **_: streams,
            check_compatibility=lambda **_: True)
        selected = select_ga4_property(grant=pending, user=self.owner, property_id="12345",
            origin="https://project.example", expected_revision=0,
            client_id="analytics-client", client_secret="analytics-secret", **provider)
        _, connection = link_ga4_source(grant=selected, user=self.owner, expected_revision=1,
            client_id="analytics-client", client_secret="analytics-secret", **provider)
        path = self.prefix.replace("/oauth/", f"/sources/{connection.pk}/sync/")
        day = (timezone.now().date() - timedelta(days=5)).isoformat()
        payload = {"day": day, "idempotency_key": "ga4-api-fixture", "report_kind": "all_channels"}
        self.assertEqual(self.post(owner, path, payload, csrf=False).status_code, 403)
        self.assertEqual(self.post(viewer, path, payload).status_code, 403)
        self.assertEqual(self.post(foreign, path, payload).status_code, 404)
        response = self.post(owner, path, payload)
        self.assertEqual(response.status_code, 409, response.content)
        self.assertIn("exact HTTPS origin", response.json()["errors"][0]["message"])
        self.assertEqual(self.post(owner, path, payload).status_code, 409)
        from jobs.models import JobRun
        self.assertFalse(JobRun.objects.filter(handler="sync_ga4_landing").exists())
        status = owner.get(path + "status/", secure=True)
        self.assertEqual(status.status_code, 200)
        self.assertFalse(status.json()["source_current"])
        self.assertEqual(status.json()["report_availability"], "exact_origin_attribution_unavailable")
        self.assertEqual(status.json()["pages"], [])
        self.assertIn("no-store", status["Cache-Control"])
