from datetime import timedelta
from unittest.mock import patch

from allauth.account.models import EmailAddress
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from tenancy.models import AuditEvent, AuditEventType, MembershipRole, OrganizationMembership, ProjectOriginVerification
from tenancy.services import create_organization, create_project, update_project

from .google_oauth import complete_google_oauth, revoke_google_grant, select_google_site
from .google_tokens import GoogleTokens, GoogleTokenError, SCOPE, decrypt_refresh_token
from .models import GoogleOAuthGrant, GoogleOAuthIntent, IntegrationConnection
from .oauth import CALLBACK_PATH, OAuthStateError, begin_google_oauth_intent
from .services import create_connection


CALLBACK = f"https://callback.example.com{CALLBACK_PATH}"


@override_settings(
    GOOGLE_OAUTH_REDIRECT_URI=CALLBACK,
    GOOGLE_OAUTH_CLIENT_ID="fixture-client-id",
    GOOGLE_OAUTH_CLIENT_SECRET="fixture-client-secret",
    GOOGLE_OAUTH_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),),
)
class GoogleOAuthGrantTests(TestCase):
    session = "f" * 32

    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user("grant-owner@example.com", password="test-password")
        self.admin = users.create_user("grant-admin@example.com", password="test-password")
        self.outsider = users.create_user("grant-outsider@example.com", password="test-password")
        for user in (self.owner, self.admin, self.outsider):
            EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
        organization = create_organization(user=self.owner, name="Grant organization")
        OrganizationMembership.objects.create(organization=organization, user=self.admin, role=MembershipRole.ADMIN)
        self.project = create_project(organization=organization, user=self.owner, name="Grant site",
                                      canonical_origin="https://grant.example", aliases=["https://www.grant.example"])

    def begin(self):
        return begin_google_oauth_intent(project=self.project, user=self.admin, session_key=self.session)

    def select(self, *, grant, user, site_url, permission_response, expected_revision=0):
        return select_google_site(
            grant=grant, user=user, site_url=site_url, expected_revision=expected_revision,
            refresh=lambda **_kwargs: GoogleTokens(access_token="ACCESS_SECRET", refresh_token=None,
                                                     expires_at=timezone.now() + timedelta(hours=1)),
            verify_site=lambda **_kwargs: permission_response,
        )

    def complete(self, token, *, sites=None, exchange=None, user=None):
        called = []

        def fake_exchange(**kwargs):
            called.append(kwargs)
            return GoogleTokens(access_token="ACCESS_SECRET", refresh_token="REFRESH_SECRET",
                                expires_at=timezone.now() + timedelta(hours=1))

        def fake_sites(**kwargs):
            called.append(kwargs)
            return {"siteEntry": sites if sites is not None else [
                {"siteUrl": "https://grant.example/", "permissionLevel": "siteOwner"},
                {"siteUrl": "sc-domain:grant.example", "permissionLevel": "siteOwner"},
                {"siteUrl": "https://outside.example/", "permissionLevel": "siteOwner"},
            ]}

        result = complete_google_oauth(
            user=user or self.admin, session_key=self.session, state=token, callback_url=CALLBACK,
            code="one-use-code", exchange=exchange or fake_exchange, list_sites=fake_sites,
        )
        return result, called

    def test_callback_selects_exact_origin_with_encrypted_refresh_and_audited_revoke(self):
        intent, token = self.begin()
        (grant, available), calls = self.complete(token)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["client_id"], "fixture-client-id")
        self.assertEqual(calls[1], {"access_token": "ACCESS_SECRET"})
        self.assertEqual(available["api_sync_status"], "not_verified")
        self.assertEqual(len(grant.selectable_sites), 1)
        self.assertNotIn("sc-domain:", str(grant.selectable_sites))
        self.assertEqual(grant.state, GoogleOAuthGrant.State.PENDING_SELECTION)
        self.assertEqual(decrypt_refresh_token(grant.encrypted_refresh_token), "REFRESH_SECRET")
        self.assertNotIn("REFRESH_SECRET", str(grant.__dict__))
        intent.refresh_from_db()
        self.assertEqual(intent.status, GoogleOAuthIntent.Status.CONSUMED)
        with self.assertRaises(OAuthStateError):
            self.complete(token)
        with self.assertRaises(PermissionDenied):
            self.select(grant=grant, user=self.outsider, site_url="https://grant.example/",
                        permission_response={"siteUrl": "https://grant.example/", "permissionLevel": "siteOwner"})
        with self.assertRaises(PermissionDenied):
            self.select(grant=grant, user=self.admin, site_url="https://outside.example/",
                        permission_response={"siteUrl": "https://outside.example/", "permissionLevel": "siteOwner"})
        connection = self.select(grant=grant, user=self.admin, site_url="https://grant.example/",
                                 permission_response={"siteUrl": "https://grant.example/", "permissionLevel": "siteOwner"})
        grant.refresh_from_db()
        self.assertEqual(grant.state, GoogleOAuthGrant.State.ACTIVE)
        self.assertEqual((grant.revision, connection.credential_reference), (1, grant.credential_reference))
        self.assertEqual(connection.external_property_id, "https://grant.example")
        self.assertIn("api_sync", connection.capabilities)
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.GOOGLE_OAUTH_CONNECTED).count(), 1)
        with self.assertRaises(ValidationError):
            grant.save()
        pending = revoke_google_grant(grant=grant, user=self.owner, expected_revision=1)
        connection.refresh_from_db()
        self.assertEqual(pending.state, GoogleOAuthGrant.State.REVOCATION_PENDING)
        self.assertEqual(connection.credential_reference, pending.credential_reference)
        self.assertEqual(connection.state, IntegrationConnection.State.DISCONNECTED)
        self.assertEqual(decrypt_refresh_token(pending.encrypted_refresh_token), "REFRESH_SECRET")
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.GOOGLE_OAUTH_REVOCATION_REQUESTED).count(), 1)
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.GOOGLE_OAUTH_REVOKED).count(), 0)

        def outage(**_kwargs):
            raise GoogleTokenError("provider_unavailable", retryable=True)

        with self.assertRaises(GoogleTokenError):
            revoke_google_grant(grant=pending, user=self.owner, expected_revision=2, remote_revoke=outage)
        pending.refresh_from_db()
        self.assertEqual(pending.state, GoogleOAuthGrant.State.REVOCATION_PENDING)
        self.assertEqual(decrypt_refresh_token(pending.encrypted_refresh_token), "REFRESH_SECRET")
        revoked = revoke_google_grant(grant=pending, user=self.owner, expected_revision=2,
                                      remote_revoke=lambda **_kwargs: True)
        connection.refresh_from_db()
        self.assertEqual(revoked.state, GoogleOAuthGrant.State.REVOKED)
        self.assertEqual(revoked.encrypted_refresh_token, "")
        self.assertEqual(revoked.selectable_sites, [])
        self.assertIsNone(connection.credential_reference)
        self.assertEqual(connection.state, IntegrationConnection.State.DISCONNECTED)
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.GOOGLE_OAUTH_REVOKED).count(), 1)
        revoke_google_grant(grant=revoked, user=self.owner, expected_revision=3)
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.GOOGLE_OAUTH_REVOKED).count(), 1)

    def test_domain_property_is_page_only_and_captures_verified_exact_origin_scope(self):
        ProjectOriginVerification.objects.create(
            organization=self.project.organization, project=self.project, origin=self.project.canonical_origin,
            challenge_digest="a" * 64, state=ProjectOriginVerification.State.VERIFIED,
            verified_at=timezone.now(),
        )
        _intent, token = self.begin()
        site = {"siteUrl": "sc-domain:grant.example", "permissionLevel": "siteOwner"}
        (grant, sites), _calls = self.complete(token, sites=[site])
        self.assertEqual(sites["sites"][0]["approved_origins"], ["https://grant.example"])
        connection = self.select(grant=grant, user=self.owner, site_url=site["siteUrl"], permission_response=site)
        grant.refresh_from_db()
        self.assertEqual((connection.external_property_id, connection.source_semantics,
                          connection.capabilities, connection.available_dimensions),
                         ("sc-domain:grant.example", "search_console_domain_pages",
                          ["api_sync", "indexing_status", "page_metrics", "sitemaps"], ["page"]))
        self.assertEqual(grant.selected_origins, ["https://grant.example"])
        from .services import require_connection_capability
        with self.assertRaises(ValidationError):
            require_connection_capability(connection, "api_sync", dimensions=["query"])
        with self.assertRaises(ValidationError):
            require_connection_capability(connection, "api_sync", dimensions=["date"])
        pending = revoke_google_grant(grant=grant, user=self.owner, expected_revision=grant.revision)
        revoked = revoke_google_grant(grant=pending, user=self.owner, expected_revision=pending.revision,
                                      remote_revoke=lambda **_kwargs: True)
        self.assertEqual(revoked.selected_origins, [])

    def test_domain_selection_rechecks_removed_verified_alias_after_consent(self):
        alias = "https://www.grant.example"
        ProjectOriginVerification.objects.create(
            organization=self.project.organization, project=self.project, origin=alias,
            challenge_digest="b" * 64, state=ProjectOriginVerification.State.VERIFIED,
            verified_at=timezone.now(),
        )
        _intent, token = self.begin()
        site = {"siteUrl": "sc-domain:grant.example", "permissionLevel": "siteOwner"}
        (grant, _sites), _calls = self.complete(token, sites=[site])
        self.assertEqual(grant.selectable_sites[0]["approved_origins"], [alias])
        update_project(project=self.project, user=self.owner, aliases=[])
        with self.assertRaises(PermissionDenied):
            self.select(grant=grant, user=self.owner, site_url=site["siteUrl"], permission_response=site)
        self.assertFalse(IntegrationConnection.objects.exists())
        grant.refresh_from_db()
        self.assertEqual(grant.state, GoogleOAuthGrant.State.PENDING_SELECTION)

    def test_existing_csv_property_is_reused_without_overwriting_import_semantics(self):
        csv_connection = create_connection(
            project=self.project, user=self.owner, provider="google_search_console",
            external_property_id="https://grant.example/", capabilities=["csv_import", "query_metrics"],
            available_dimensions=["query"], source_semantics="search_console_performance",
            source_semantics_version="csv-v1", timezone="America/Los_Angeles",
        )
        _intent, token = self.begin()
        (grant, _), _calls = self.complete(token)
        connection = self.select(grant=grant, user=self.owner, site_url="https://grant.example/",
                                 permission_response={"siteUrl": "https://grant.example/", "permissionLevel": "siteFullUser"})
        self.assertEqual(connection.pk, csv_connection.pk)
        self.assertEqual(connection.source_semantics_version, "csv-v1")
        self.assertIn("api_sync", connection.capabilities)

    def test_callback_failure_or_property_loss_keeps_state_consumed_without_token_storage(self):
        _intent, token = self.begin()
        with self.assertRaises(GoogleTokenError):
            self.complete(token, exchange=lambda **_kwargs: (_ for _ in ()).throw(GoogleTokenError("quota_limited")))
        self.assertFalse(GoogleOAuthGrant.objects.exists())
        with self.assertRaises(OAuthStateError):
            self.complete(token)
        _intent, token = self.begin()

        def site_outage(**_kwargs):
            raise GoogleTokenError("provider_unavailable", retryable=True)

        with self.assertRaises(GoogleTokenError):
            complete_google_oauth(
                user=self.admin, session_key=self.session, state=token, callback_url=CALLBACK,
                code="valid-code", exchange=lambda **_kwargs: GoogleTokens(
                    "ACCESS_SECRET", "REFRESH_SECRET", timezone.now() + timedelta(hours=1)),
                list_sites=site_outage,
            )
        self.assertEqual(GoogleOAuthGrant.objects.get().state, GoogleOAuthGrant.State.REVOCATION_PENDING)
        _intent, token = self.begin()
        (grant, available), _calls = self.complete(token, sites=[
            {"siteUrl": "https://outside.example/", "permissionLevel": "siteOwner"},
        ])
        self.assertEqual(grant.state, GoogleOAuthGrant.State.REVOCATION_PENDING)
        self.assertEqual(decrypt_refresh_token(grant.encrypted_refresh_token), "REFRESH_SECRET")
        self.assertEqual(available["result_state"], "no_accessible_exact_scope_property")
        self.assertFalse(IntegrationConnection.objects.exists())
        _intent, token = self.begin()

        def remove_alias(**_kwargs):
            update_project(project=self.project, user=self.owner, aliases=[])
            return GoogleTokens(access_token="ACCESS_SECRET", refresh_token="REFRESH_SECRET",
                                expires_at=timezone.now() + timedelta(hours=1))

        (grant, available), _calls = self.complete(token, exchange=remove_alias, sites=[
            {"siteUrl": "https://www.grant.example/", "permissionLevel": "siteOwner"},
        ])
        self.assertEqual(grant.state, GoogleOAuthGrant.State.REVOCATION_PENDING)
        self.assertEqual(available["sites"], [])

        intent, token = self.begin()
        from .search_console_api import exact_scope_search_console_sites

        def list_then_revoke(**kwargs):
            result = exact_scope_search_console_sites(**kwargs)
            OrganizationMembership.objects.filter(organization=self.project.organization,
                user=self.admin).update(role=MembershipRole.VIEWER)
            return result

        count = GoogleOAuthGrant.objects.count()
        with patch("integrations.google_oauth.exact_scope_search_console_sites", side_effect=list_then_revoke):
            with self.assertRaises(PermissionDenied):
                self.complete(token)
        self.assertEqual(GoogleOAuthGrant.objects.count(), count + 1)
        retained = GoogleOAuthGrant.objects.order_by("-pk").first()
        self.assertEqual(retained.state, GoogleOAuthGrant.State.REVOCATION_PENDING)
        self.assertEqual(retained.actor_id, self.admin.pk)
        self.assertEqual(retained.project_id, self.project.pk)
        self.assertEqual(decrypt_refresh_token(retained.encrypted_refresh_token), "REFRESH_SECRET")
        self.assertEqual(retained.selectable_sites, [])
        self.assertFalse(IntegrationConnection.objects.exists())
        intent.refresh_from_db()
        self.assertEqual(intent.status, GoogleOAuthIntent.Status.CONSUMED)
        with self.assertRaises(OAuthStateError):
            self.complete(token)

    def test_wrong_scope_and_stale_grant_revision_cannot_activate(self):
        _intent, token = self.begin()
        (grant, _), _calls = self.complete(token)
        with self.assertRaises(PermissionDenied):
            self.select(grant=grant, user=self.admin, site_url="https://grant.example/",
                        permission_response={"siteUrl": "https://grant.example/", "permissionLevel": "siteUnverifiedUser"})
        with self.assertRaises(ValidationError):
            self.select(grant=grant, user=self.admin, site_url="https://grant.example/",
                        permission_response={"siteUrl": "https://grant.example/", "permissionLevel": "siteOwner"},
                        expected_revision=1)
        self.assertFalse(IntegrationConnection.objects.filter(project=self.project).exists())

    def test_role_revoked_during_provider_verification_cannot_activate_property(self):
        _intent, state = self.begin()
        (grant, _available), _calls = self.complete(state)

        def revoke_member(**_kwargs):
            OrganizationMembership.objects.filter(organization=self.project.organization, user=self.admin).delete()
            return {"siteUrl": "https://grant.example/", "permissionLevel": "siteOwner"}

        with self.assertRaises(PermissionDenied):
            select_google_site(
                grant=grant, user=self.admin, site_url="https://grant.example/", expected_revision=0,
                refresh=lambda **_kwargs: GoogleTokens("ACCESS_SECRET", None, timezone.now() + timedelta(hours=1)),
                verify_site=revoke_member,
            )
        grant.refresh_from_db()
        self.assertEqual(grant.state, GoogleOAuthGrant.State.PENDING_SELECTION)
        self.assertFalse(IntegrationConnection.objects.exists())
