from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch
import json

from allauth.account.models import EmailAddress
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from datetime import timedelta

from tenancy.models import MembershipRole, OrganizationMembership, Project, ProjectOriginVerification
from tenancy.services import create_organization, create_project

from .google_oauth import complete_google_oauth, select_google_site
from .google_tokens import GoogleTokenError, GoogleTokens
from .models import GoogleOAuthGrant, GoogleOAuthIntent, IntegrationConnection
from .search_console_api import exact_scope_search_console_sites
from .services import create_connection
from .oauth import CALLBACK_PATH


HOST = "callback.example.com"
CALLBACK = f"https://{HOST}{CALLBACK_PATH}"


@override_settings(
    GOOGLE_OAUTH_CLIENT_ID="fixture-client-id", GOOGLE_OAUTH_CLIENT_SECRET="fixture-client-secret",
    GOOGLE_OAUTH_REDIRECT_URI=CALLBACK, GOOGLE_OAUTH_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),),
    FRONTEND_ORIGIN=f"https://{HOST}", ALLOWED_HOSTS=[HOST, "alternate.example.com"], SECURE_SSL_REDIRECT=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "oauth-api-fixtures"}},
)
class GoogleOAuthBrowserTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user("oauth-browser-owner@example.com", password="test-password")
        self.outsider = users.create_user("oauth-browser-outsider@example.com", password="test-password")
        self.viewer = users.create_user("oauth-browser-viewer@example.com", password="test-password")
        for user in (self.owner, self.outsider, self.viewer):
            EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
        self.organization = create_organization(user=self.owner, name="Browser OAuth")
        OrganizationMembership.objects.create(organization=self.organization, user=self.viewer, role=MembershipRole.VIEWER)
        self.project = create_project(organization=self.organization, user=self.owner, name="Site",
                                      canonical_origin="https://owned.example")
        self.start_url = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/search-console/oauth/start/"
        self.grants_url = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/search-console/oauth/grants/"

    def client_for(self, user):
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        self.assertEqual(client.get("/_allauth/browser/v1/auth/session", secure=True, HTTP_HOST=HOST).status_code, 200)
        return client

    def post(self, client, path, data=None, *, csrf=True, host=HOST):
        headers = {"secure": True, "HTTP_HOST": host, "HTTP_REFERER": f"https://{host}/"}
        if csrf:
            headers["HTTP_X_CSRFTOKEN"] = client.cookies["csrftoken"].value
        return client.post(path, data=json.dumps(data or {}), content_type="application/json", **headers)

    def start(self, client):
        result = self.post(client, self.start_url)
        self.assertEqual(result.status_code, 201, result.content)
        self.assertIn("no-store", result["Cache-Control"])
        self.assertEqual(result["Referrer-Policy"], "no-referrer")
        url = result.json()["authorization_url"]
        self.assertEqual(urlsplit(url).netloc, "accounts.google.com")
        self.assertNotIn("fixture-client-secret", url)
        params = parse_qs(urlsplit(url).query)
        self.assertEqual(params["redirect_uri"], [CALLBACK])
        self.assertEqual(params["scope"], ["https://www.googleapis.com/auth/webmasters.readonly"])
        return params["state"][0]

    def complete(self, **kwargs):
        return complete_google_oauth(
            **kwargs,
            exchange=lambda **_params: GoogleTokens("ACCESS_SECRET", "REFRESH_SECRET",
                                                    timezone.now() + timedelta(hours=1)),
            list_sites=lambda **_params: {"siteEntry": [
                {"siteUrl": "https://owned.example/", "permissionLevel": "siteOwner"},
            ]},
        )

    def test_start_callback_replay_and_no_code_in_redirect_or_grant_response(self):
        owner = self.client_for(self.owner)
        self.assertEqual(self.post(owner, self.start_url, csrf=False).status_code, 403)
        state = self.start(owner)
        self.assertNotIn(state, str(GoogleOAuthIntent.objects.get().__dict__))
        outsider = self.client_for(self.outsider)
        self.assertEqual(outsider.get(CALLBACK_PATH, {"state": state, "code": "CREDENTIAL"},
                                      secure=True, HTTP_HOST=HOST).status_code, 303)
        self.assertEqual(GoogleOAuthIntent.objects.get().status, GoogleOAuthIntent.Status.PENDING)
        with patch("integrations.oauth_views.complete_google_oauth", side_effect=self.complete):
            result = owner.get(CALLBACK_PATH, {"state": state, "code": "CREDENTIAL"},
                               secure=True, HTTP_HOST=HOST)
        self.assertEqual(result.status_code, 303)
        self.assertEqual(result["Location"], f"https://{HOST}/app/onboarding/{self.organization.pk}/{self.project.pk}")
        self.assertEqual(result["Referrer-Policy"], "no-referrer")
        self.assertIn("no-store", result["Cache-Control"])
        self.assertNotIn("CREDENTIAL", result["Location"])
        self.assertNotIn(state, result["Location"])
        self.assertEqual(GoogleOAuthGrant.objects.count(), 1)
        with patch("integrations.oauth_views.complete_google_oauth", side_effect=self.complete):
            replay = owner.get(CALLBACK_PATH, {"state": state, "code": "CREDENTIAL"},
                               secure=True, HTTP_HOST=HOST)
        self.assertEqual((replay.status_code, replay["Location"]), (303, f"https://{HOST}/app"))
        self.assertEqual(GoogleOAuthGrant.objects.count(), 1)
        grants = owner.get(self.grants_url, secure=True, HTTP_HOST=HOST)
        self.assertEqual(grants.status_code, 200)
        self.assertNotIn("REFRESH_SECRET", grants.content.decode())
        self.assertNotIn("encrypted_refresh_token", grants.content.decode())
        self.assertEqual(grants.json()["grants"][0]["sites"][0]["property"], "https://owned.example")

    def test_domain_candidate_selection_and_page_only_status_deny_broad_aggregates(self):
        verification = ProjectOriginVerification.objects.create(
            organization=self.organization, project=self.project, origin=self.project.canonical_origin,
            challenge_digest="a" * 64, state=ProjectOriginVerification.State.VERIFIED,
            verified_at=timezone.now(),
        )
        site = {"siteUrl": "sc-domain:owned.example", "permissionLevel": "siteOwner"}
        options = exact_scope_search_console_sites(project=self.project, user=self.owner,
                                                    response={"siteEntry": [site]})["sites"]
        grant = GoogleOAuthGrant.objects.create(
            organization=self.organization, project=self.project, actor=self.owner,
            scope="https://www.googleapis.com/auth/webmasters.readonly", verified_at=timezone.now(),
            encrypted_refresh_token="v1:fixture-only", selectable_sites=options,
        )
        owner = self.client_for(self.owner)
        listed = owner.get(self.grants_url, secure=True, HTTP_HOST=HOST)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["grants"][0]["sites"][0]["approved_origins"], ["https://owned.example"])
        self.assertEqual(listed.json()["grants"][0]["sites"][0]["available_dimensions"], ["page"])
        select_path = f"{self.grants_url}{grant.pk}/select/"
        with patch("integrations.oauth_views.select_google_site", side_effect=lambda **kwargs: select_google_site(
                **kwargs, refresh=lambda **_params: GoogleTokens("ACCESS_SECRET", None,
                                                                  timezone.now() + timedelta(hours=1)),
                verify_site=lambda **_params: site)):
            selected = self.post(owner, select_path, {"site_url": site["siteUrl"], "revision": 0})
        self.assertEqual(selected.status_code, 200, selected.content)
        source_url = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/sources/"
        source = owner.get(source_url, secure=True, HTTP_HOST=HOST).json()["sources"][0]
        self.assertEqual((source["scope_kind"], source["approved_origins"], source["available_api_dimensions"]),
                         ("verified_domain_page_only", ["https://owned.example"], ["page"]))
        self.assertTrue(source["api_sync_available"])
        self.assertTrue(source["coverage_available"])
        sync_path = f"{source_url}{source['id']}/sync/"
        data = {"day": (timezone.now().date() - timedelta(days=7)).isoformat(),
                "dimensions": ["query"], "idempotency_key": "forbidden-domain-aggregate"}
        self.assertEqual(self.post(owner, sync_path, data).status_code, 409)
        with patch("jobs.services.dispatch_pending"):
            self.assertEqual(self.post(owner, sync_path, {**data, "dimensions": ["page"],
                                                         "idempotency_key": "page-only"}).status_code, 202)
        coverage_path = f"{source_url}{source['id']}/coverage/"
        inspection = {"inspection_url": "https://owned.example/selected", "idempotency_key": "coverage-page"}
        self.assertEqual(self.post(owner, coverage_path, inspection, csrf=False).status_code, 403)
        self.assertEqual(self.post(self.client_for(self.viewer), coverage_path, inspection).status_code, 403)
        self.assertEqual(self.post(self.client_for(self.outsider), coverage_path, inspection).status_code, 404)
        self.assertEqual(self.post(owner, coverage_path, {**inspection, "inspection_url":
                                                        "https://m.owned.example/foreign"}).status_code, 409)
        with patch("jobs.services.dispatch_pending"):
            queued = self.post(owner, coverage_path, inspection)
        self.assertEqual(queued.status_code, 202, queued.content)
        self.assertEqual((queued.json()["job"]["status"], queued.json()["max_requests"]), ("queued", 3))
        self.assertNotIn("fixture-only", queued.content.decode())
        status_path = f"{coverage_path}status/"
        self.assertEqual(owner.get(status_path, secure=True, HTTP_HOST=HOST).json()["job"]["id"],
                         queued.json()["job"]["id"])
        cancelled = self.post(owner, f"{coverage_path}{queued.json()['job']['id']}/cancel/")
        self.assertEqual((cancelled.status_code, cancelled.json()["job"]["status"]), (200, "cancelled"))
        ProjectOriginVerification.objects.filter(pk=verification.pk).update(
            state=ProjectOriginVerification.State.REVOKED, revoked_at=timezone.now())
        stale = owner.get(source_url, secure=True, HTTP_HOST=HOST).json()["sources"][0]
        self.assertFalse(stale["scope_current"])
        self.assertFalse(stale["api_sync_available"])
        self.assertFalse(stale["coverage_available"])

    def test_scope_role_and_callback_failure_are_queryless_and_fail_closed(self):
        viewer = self.client_for(self.viewer)
        self.assertEqual(self.post(viewer, self.start_url).status_code, 403)
        self.assertEqual(viewer.get(self.grants_url, secure=True, HTTP_HOST=HOST).status_code, 403)
        owner = self.client_for(self.owner)
        with override_settings(GOOGLE_OAUTH_CLIENT_SECRET=""):
            self.assertEqual(self.post(owner, self.start_url).status_code, 503)
        self.assertFalse(GoogleOAuthIntent.objects.exists())
        state = self.start(owner)
        wrong = owner.get(CALLBACK_PATH, {"state": state, "code": "secret-code"},
                          secure=True, HTTP_HOST="alternate.example.com")
        self.assertEqual((wrong.status_code, wrong["Location"]), (303, f"https://{HOST}/app"))
        self.assertNotIn("secret-code", wrong["Location"])
        self.assertEqual(GoogleOAuthIntent.objects.get().status, GoogleOAuthIntent.Status.PENDING)
        denied = owner.get(CALLBACK_PATH, {"state": state, "error": "access_denied"},
                           secure=True, HTTP_HOST=HOST)
        self.assertEqual(denied.status_code, 303)
        self.assertNotIn("state", denied["Location"])
        self.assertEqual(GoogleOAuthIntent.objects.get().status, GoogleOAuthIntent.Status.DENIED)

    def test_sync_endpoint_requires_csrf_current_grant_scope_and_idempotent_bound(self):
        connection = create_connection(
            project=self.project, user=self.owner, provider="google_search_console",
            external_property_id="https://owned.example/", capabilities=["api_sync", "query_metrics"],
            available_dimensions=["query"], source_semantics="search_console_performance",
            source_semantics_version="gsc-performance-v1", timezone="America/Los_Angeles",
        )
        grant = GoogleOAuthGrant.objects.create(
            organization=self.organization, project=self.project, actor=self.owner,
            scope="https://www.googleapis.com/auth/webmasters.readonly", verified_at=timezone.now(),
            encrypted_refresh_token="v1:fixture-only", state=GoogleOAuthGrant.State.ACTIVE,
            selected_property_id=connection.external_property_id, selected_site_url="https://owned.example/",
        )
        connection.credential_reference = grant.credential_reference
        connection.save()
        path = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/sources/{connection.pk}/sync/"
        owner = self.client_for(self.owner)
        request = {"day": (timezone.now().date() - timedelta(days=7)).isoformat(),
                   "dimensions": ["query"], "idempotency_key": "fixture-sync"}
        self.assertEqual(self.post(owner, path, request, csrf=False).status_code, 403)
        viewer = self.client_for(self.viewer)
        self.assertEqual(self.post(viewer, path, request).status_code, 403)
        outsider = self.client_for(self.outsider)
        self.assertEqual(self.post(outsider, path, request).status_code, 404)
        with override_settings(GOOGLE_OAUTH_CLIENT_SECRET=""):
            self.assertEqual(self.post(owner, path, request).status_code, 503)
        response = self.post(owner, path, request)
        self.assertEqual(response.status_code, 202, response.content)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response.json()["source_coverage"], "top_rows_only")
        self.assertEqual(response.json()["max_requests"], 3)
        self.assertNotIn("fixture-only", response.content.decode())
        status_path = path + "status/"
        status = owner.get(status_path, secure=True, HTTP_HOST=HOST)
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["job"]["id"], response.json()["job_id"])
        self.assertNotIn("fixture-only", status.content.decode())
        self.assertEqual(viewer.get(status_path, secure=True, HTTP_HOST=HOST).status_code, 403)
        self.assertEqual(outsider.get(status_path, secure=True, HTTP_HOST=HOST).status_code, 404)
        cancel_path = path + f'{response.json()["job_id"]}/cancel/'
        self.assertEqual(self.post(owner, cancel_path, csrf=False).status_code, 403)
        self.assertEqual(self.post(outsider, cancel_path).status_code, 404)
        self.assertEqual(self.post(owner, cancel_path).json()["job"]["status"], "cancelled")
        self.assertEqual(owner.get(status_path, secure=True, HTTP_HOST=HOST).json()["job"]["status"], "cancelled")
        self.assertEqual(self.post(owner, path, request).json()["job_id"], response.json()["job_id"])
        self.assertEqual(self.post(owner, path, {**request, "dimensions": ["page"]}).status_code, 429)
        grant.state = grant.State.RECONNECT_REQUIRED
        grant.revision += 1
        grant.save()
        with patch("integrations.oauth_views.ratelimit.consume", return_value=True):
            self.assertEqual(self.post(owner, path, request).status_code, 409)

    def test_invalid_code_consumes_intent_and_selection_requires_provider_verification(self):
        owner = self.client_for(self.owner)
        state = self.start(owner)
        missing = owner.get(CALLBACK_PATH, {"state": state, "code": " "}, secure=True, HTTP_HOST=HOST)
        self.assertEqual((missing.status_code, missing["Location"]), (303, f"https://{HOST}/app"))
        self.assertEqual(GoogleOAuthIntent.objects.get().status, GoogleOAuthIntent.Status.CONSUMED)
        self.assertEqual(GoogleOAuthGrant.objects.count(), 0)
        state = self.start(owner)
        with patch("integrations.oauth_views.complete_google_oauth", side_effect=self.complete):
            owner.get(CALLBACK_PATH, {"state": state, "code": "valid-code"}, secure=True, HTTP_HOST=HOST)
        grant = GoogleOAuthGrant.objects.get()
        path = f"{self.grants_url}{grant.pk}/select/"
        wrong = self.post(owner, path, {"site_url": "sc-domain:owned.example", "revision": 0})
        self.assertEqual(wrong.status_code, 403)
        self.assertFalse(IntegrationConnection.objects.exists())

        def fixture_select(**kwargs):
            return select_google_site(
                **kwargs, refresh=lambda **_params: GoogleTokens("ACCESS_SECRET", None,
                                                                  timezone.now() + timedelta(hours=1)),
                verify_site=lambda **_params: {"siteUrl": "https://owned.example/", "permissionLevel": "siteFullUser"},
            )

        with patch("integrations.oauth_views.select_google_site", side_effect=fixture_select):
            selected = self.post(owner, path, {"site_url": "https://owned.example/", "revision": 0})
        self.assertEqual(selected.status_code, 200, selected.content)
        self.assertEqual(selected.json()["state"], "active")
        self.assertEqual(self.post(owner, path, {"site_url": "https://owned.example/", "revision": 0}).status_code, 409)
        self.assertEqual(IntegrationConnection.objects.count(), 1)
        grant.refresh_from_db()
        revoke_path = f"{self.grants_url}{grant.pk}/revoke/"
        with patch("integrations.oauth_views.revoke_google_tokens", side_effect=GoogleTokenError("provider_unavailable")):
            pending = self.post(owner, revoke_path, {"revision": grant.revision})
        self.assertEqual((pending.status_code, pending.json()["state"]), (202, "revocation_pending"))
        self.assertEqual(IntegrationConnection.objects.get().state, IntegrationConnection.State.DISCONNECTED)
        grant.refresh_from_db()
        with patch("integrations.oauth_views.revoke_google_tokens", return_value=True):
            revoked = self.post(owner, revoke_path, {"revision": grant.revision})
        self.assertEqual((revoked.status_code, revoked.json()["state"]), (200, "revoked"))
        self.assertEqual(GoogleOAuthGrant.objects.get().encrypted_refresh_token, "")
        self.assertIsNone(IntegrationConnection.objects.get().credential_reference)

    def test_grant_ids_cannot_cross_project_boundaries(self):
        owner = self.client_for(self.owner)
        state = self.start(owner)
        with patch("integrations.oauth_views.complete_google_oauth", side_effect=self.complete):
            owner.get(CALLBACK_PATH, {"state": state, "code": "valid-code"}, secure=True, HTTP_HOST=HOST)
        grant = GoogleOAuthGrant.objects.get()
        sibling = Project.objects.create(
            organization=self.organization, name="Sibling site", canonical_origin="https://sibling.example",
        )
        base = f"/api/organizations/{self.organization.pk}/projects/{sibling.pk}/search-console/oauth/grants/"
        self.assertEqual(owner.get(base, secure=True, HTTP_HOST=HOST).json()["grants"], [])
        self.assertEqual(self.post(owner, f"{base}{grant.pk}/select/",
                                   {"site_url": "https://owned.example/", "revision": 0}).status_code, 404)
        self.assertEqual(self.post(owner, f"{base}{grant.pk}/revoke/", {"revision": 0}).status_code, 404)
        self.assertEqual(grant.state, GoogleOAuthGrant.State.PENDING_SELECTION)
