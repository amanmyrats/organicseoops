from cryptography.fernet import Fernet
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from tenancy.services import create_organization, create_project, update_project
from tenancy.models import AuditEvent, AuditEventType

from .ga4_oauth import (SCOPE, begin_ga4_oauth_intent, complete_ga4_oauth,
                        consume_ga4_oauth_intent, decrypt_ga4_refresh_token, revoke_ga4_grant,
                        link_ga4_source, select_ga4_property)
from .google_tokens import GoogleTokenError, GoogleTokens
from .models import GA4OAuthGrant, GA4OAuthIntent, IntegrationConnection
from .oauth import OAuthStateError
from .services import require_connection_capability


CALLBACK = "https://api.example.test/api/integrations/google-analytics/oauth/callback/"
KEY = Fernet.generate_key().decode()


@override_settings(GOOGLE_ANALYTICS_REDIRECT_URI=CALLBACK, GOOGLE_ANALYTICS_ENCRYPTION_KEYS=(KEY,))
class GA4OAuthTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user("ga4-consent@example.test", password="test-password")
        self.other = users.create_user("ga4-other@example.test", password="test-password")
        for user in (self.owner, self.other):
            EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
        organization = create_organization(user=self.owner, name="Consent fixture")
        self.project = create_project(organization=organization, user=self.owner,
                                      name="Consent project", canonical_origin="https://consent.example")
        self.session = "safe-browser-session-key-123456789"

    def consume(self, state, **kwargs):
        return consume_ga4_oauth_intent(user=kwargs.pop("user", self.owner),
            session_key=kwargs.pop("session_key", self.session), state=state,
            callback_url=kwargs.pop("callback_url", CALLBACK), **kwargs)

    def test_intent_replay_wrong_browser_and_scope_change_deny_without_using_search_console(self):
        intent, state = begin_ga4_oauth_intent(project=self.project, user=self.owner, session_key=self.session)
        self.assertNotEqual(intent.state_digest, state)
        self.assertNotIn(self.session, intent.session_digest)
        with self.assertRaises(PermissionDenied):
            self.consume(state, user=self.other)
        with self.assertRaises(PermissionDenied):
            self.consume(state, session_key="another-browser-session-1234567")
        with self.assertRaises(OAuthStateError):
            self.consume(state, callback_url="https://foreign.example/api/integrations/google-analytics/oauth/callback/")
        self.assertEqual(self.consume(state).status, GA4OAuthIntent.Status.CONSUMED)
        with self.assertRaises(OAuthStateError):
            self.consume(state)
        _, second = begin_ga4_oauth_intent(project=self.project, user=self.owner, session_key=self.session)
        denied = self.consume(second, provider_denied=True)
        self.assertEqual(denied.status, GA4OAuthIntent.Status.DENIED)
        with self.assertRaises(OAuthStateError):
            self.consume(second)
        _, third = begin_ga4_oauth_intent(project=self.project, user=self.owner, session_key=self.session)
        update_project(project=self.project, user=self.owner, canonical_origin="https://new.example")
        # Changing the project origin does not silently authorize a new source; permission is still rechecked.
        self.assertEqual(self.consume(third).status, GA4OAuthIntent.Status.CONSUMED)

    def test_callback_consumes_state_before_exchange_and_encrypts_separate_analytics_scope(self):
        intent, state = begin_ga4_oauth_intent(project=self.project, user=self.owner, session_key=self.session)
        def exchange(*, form):
            self.assertEqual(GA4OAuthIntent.objects.get(pk=intent.pk).status, GA4OAuthIntent.Status.CONSUMED)
            self.assertEqual(form["redirect_uri"], CALLBACK)
            self.assertEqual(form["code"], "once-only-code")
            return {"scope": SCOPE, "token_type": "Bearer", "access_token": "ACCESS_SECRET",
                    "refresh_token": "REFRESH_SECRET", "expires_in": 3600}
        grant = complete_ga4_oauth(user=self.owner, session_key=self.session, state=state,
            callback_url=CALLBACK, code="once-only-code", client_id="fixture-id",
            client_secret="fixture-secret", transport=exchange)
        self.assertEqual(grant.state, GA4OAuthGrant.State.PENDING_SELECTION)
        self.assertEqual(decrypt_ga4_refresh_token(grant.encrypted_refresh_token), "REFRESH_SECRET")
        self.assertNotIn("REFRESH_SECRET", str(grant.__dict__))
        self.assertNotIn("ACCESS_SECRET", str(grant.__dict__))
        self.assertEqual(grant.property_id, "")
        with self.assertRaises(OAuthStateError):
            complete_ga4_oauth(user=self.owner, session_key=self.session, state=state,
                callback_url=CALLBACK, code="once-only-code", client_id="fixture-id",
                client_secret="fixture-secret", transport=exchange)
        self.assertEqual(GA4OAuthGrant.objects.count(), 1)

    def test_wrong_scope_missing_refresh_and_missing_cipher_key_never_create_grant(self):
        for response in (
            {"scope": "https://www.googleapis.com/auth/webmasters.readonly", "token_type": "Bearer",
             "access_token": "ACCESS_SECRET", "refresh_token": "REFRESH_SECRET", "expires_in": 3600},
            {"scope": SCOPE, "token_type": "Bearer", "access_token": "ACCESS_SECRET", "expires_in": 3600},
        ):
            _, state = begin_ga4_oauth_intent(project=self.project, user=self.owner, session_key=self.session)
            with self.assertRaises(GoogleTokenError):
                complete_ga4_oauth(user=self.owner, session_key=self.session, state=state,
                    callback_url=CALLBACK, code="once-only-code", client_id="fixture-id",
                    client_secret="fixture-secret", transport=lambda **_: response)
        self.assertFalse(GA4OAuthGrant.objects.exists())
        with override_settings(GOOGLE_ANALYTICS_ENCRYPTION_KEYS=()):
            with self.assertRaises(GoogleTokenError):
                decrypt_ga4_refresh_token("v1:anything")
        with self.assertRaises(ValidationError):
            GA4OAuthGrant(organization=self.project.organization, project=self.project, actor=self.owner,
                encrypted_refresh_token="v1:not-encrypted", scope="webmasters.readonly").full_clean()

    def pending_grant(self):
        _intent, state = begin_ga4_oauth_intent(project=self.project, user=self.owner, session_key=self.session)
        return complete_ga4_oauth(user=self.owner, session_key=self.session, state=state,
            callback_url=CALLBACK, code="one-use-code", client_id="fixture-client", client_secret="fixture-secret",
            transport=lambda **_: {"scope": SCOPE, "token_type": "Bearer", "access_token": "ACCESS_SECRET",
                                 "refresh_token": "REFRESH_SECRET", "expires_in": 3600})

    def select(self, grant, **overrides):
        response = {"name": "properties/12345", "timeZone": "Europe/Istanbul", "currencyCode": "USD"}
        streams = {"dataStreams": [{"name": "properties/12345/dataStreams/456", "type": "WEB_DATA_STREAM",
                                    "webStreamData": {"defaultUri": "https://consent.example"}}]}
        options = dict(grant=grant, user=self.owner, property_id="12345", origin="https://consent.example",
            expected_revision=grant.revision, client_id="fixture-client", client_secret="fixture-secret",
            refresh=lambda **_: GoogleTokens("ACCESS_SECRET", None, timezone.now()),
            get_property=lambda **_: response, list_streams=lambda **_: streams,
            check_compatibility=lambda **_: True)
        options.update(overrides)
        return select_ga4_property(**options)

    def test_property_selection_rechecks_scope_and_stays_disabled_until_source_link(self):
        grant = self.pending_grant()
        selected = self.select(grant)
        self.assertEqual((selected.property_id, selected.selected_origins, selected.revision),
                         ("12345", ["https://consent.example"], 1))
        self.assertEqual(selected.state, GA4OAuthGrant.State.PENDING_SELECTION)
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.GA4_PROPERTY_SELECTED,
            project=self.project).count(), 1)
        with self.assertRaises(ValidationError):
            self.select(grant)
        second = self.pending_grant()
        with self.assertRaises(PermissionDenied):
            self.select(second, user=self.other)
        third = self.pending_grant()
        def changes_scope(**_):
            update_project(project=self.project, user=self.owner, canonical_origin="https://moved.example")
            return {"name": "properties/12345", "timeZone": "Europe/Istanbul", "currencyCode": "USD"}
        with self.assertRaises(ValidationError):
            self.select(third, get_property=changes_scope)
        third.refresh_from_db()
        self.assertEqual((third.property_id, third.state), ("", GA4OAuthGrant.State.PENDING_SELECTION))

    def test_remote_revocation_failure_disables_locally_and_retains_retry_ciphertext(self):
        grant = self.select(self.pending_grant())
        def unavailable(**_):
            raise GoogleTokenError("provider_unavailable", retryable=True)
        with self.assertRaises(GoogleTokenError):
            revoke_ga4_grant(grant=grant, user=self.owner, revoke=unavailable)
        grant.refresh_from_db()
        self.assertEqual(grant.state, GA4OAuthGrant.State.REVOCATION_PENDING)
        self.assertEqual(decrypt_ga4_refresh_token(grant.encrypted_refresh_token), "REFRESH_SECRET")
        self.assertEqual(grant.property_id, "12345")
        revoked = revoke_ga4_grant(grant=grant, user=self.owner, revoke=lambda **_: True)
        self.assertEqual((revoked.state, revoked.encrypted_refresh_token, revoked.property_id,
                          revoked.selected_origins), (GA4OAuthGrant.State.REVOKED, "", "", []))
        self.assertEqual(revoke_ga4_grant(grant=revoked, user=self.owner).revision, revoked.revision)

    def link(self, grant, **overrides):
        response = {"name": "properties/12345", "timeZone": "Europe/Istanbul", "currencyCode": "USD"}
        streams = {"dataStreams": [{"name": "properties/12345/dataStreams/456", "type": "WEB_DATA_STREAM",
                                    "webStreamData": {"defaultUri": "https://consent.example"}}]}
        options = dict(grant=grant, user=self.owner, expected_revision=grant.revision,
            client_id="fixture-client", client_secret="fixture-secret",
            refresh=lambda **_: GoogleTokens("ACCESS_SECRET", None, timezone.now()),
            get_property=lambda **_: response, list_streams=lambda **_: streams,
            check_compatibility=lambda **_: True)
        options.update(overrides)
        return link_ga4_source(**options)

    def test_link_creates_only_current_ga4_source_and_revoke_disconnects_it(self):
        selected = self.select(self.pending_grant())
        grant, connection = self.link(selected)
        self.assertEqual((connection.provider, connection.external_property_id, connection.currency,
                          connection.timezone, grant.state),
                         ("google_analytics_4", "12345", "USD", "Europe/Istanbul", GA4OAuthGrant.State.ACTIVE))
        self.assertEqual(connection.available_dimensions, ["hostname", "landing_page"])
        self.assertEqual(require_connection_capability(connection, "landing_metrics",
            dimensions=["hostname", "landing_page"]).pk, connection.pk)
        with self.assertRaises(ValidationError):
            require_connection_capability(connection, "query_metrics", dimensions=["query"])
        self.assertEqual(IntegrationConnection.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.GA4_SOURCE_CONNECTED,
            project=self.project).count(), 1)
        with self.assertRaises(ValidationError):
            self.link(selected)
        with self.assertRaises(GoogleTokenError):
            revoke_ga4_grant(grant=grant, user=self.owner, revoke=lambda **_: (_ for _ in ()).throw(
                GoogleTokenError("provider_unavailable")))
        connection.refresh_from_db()
        self.assertEqual(connection.state, IntegrationConnection.State.DISCONNECTED)
        grant.refresh_from_db()
        revoked = revoke_ga4_grant(grant=grant, user=self.owner, revoke=lambda **_: True)
        self.assertEqual(revoked.state, GA4OAuthGrant.State.REVOKED)
        self.assertEqual(IntegrationConnection.objects.get(pk=connection.pk).state,
                         IntegrationConnection.State.DISCONNECTED)
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.GA4_REVOCATION_REQUESTED,
            project=self.project).count(), 1)
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.GA4_REVOKED,
            project=self.project).count(), 1)

    def test_same_property_reconsent_requires_old_token_scrub_before_rebinding(self):
        old, connection = self.link(self.select(self.pending_grant()))
        new = self.select(self.pending_grant())
        with self.assertRaises(ValidationError):
            self.link(new)
        with self.assertRaises(GoogleTokenError):
            revoke_ga4_grant(grant=old, user=self.owner, revoke=lambda **_: (_ for _ in ()).throw(
                GoogleTokenError("provider_unavailable", retryable=True)))
        with self.assertRaises(ValidationError):
            self.link(new)
        old.refresh_from_db()
        self.assertEqual(old.state, GA4OAuthGrant.State.REVOCATION_PENDING)
        revoked = revoke_ga4_grant(grant=old, user=self.owner, revoke=lambda **_: True)
        self.assertEqual((revoked.encrypted_refresh_token, revoked.property_id), ("", ""))
        new, rebound = self.link(new)
        self.assertEqual(rebound.pk, connection.pk)
        self.assertEqual(rebound.state, IntegrationConnection.State.ACTIVE)
        self.assertEqual(rebound.credential_reference, new.credential_reference)
        self.assertEqual(IntegrationConnection.objects.count(), 1)
        self.assertNotEqual(rebound.credential_reference, old.credential_reference)

    def test_origin_removed_during_provider_validation_prevents_source_link(self):
        selected = self.select(self.pending_grant())
        def changed(**_):
            update_project(project=self.project, user=self.owner, canonical_origin="https://moved.example")
            return {"name": "properties/12345", "timeZone": "Europe/Istanbul", "currencyCode": "USD"}
        with self.assertRaises(ValidationError):
            self.link(selected, get_property=changed)
        self.assertFalse(IntegrationConnection.objects.exists())
        selected.refresh_from_db()
        self.assertEqual(selected.state, GA4OAuthGrant.State.PENDING_SELECTION)

    def test_removed_origin_invalidates_active_analytics_source(self):
        grant, connection = self.link(self.select(self.pending_grant()))
        update_project(project=self.project, user=self.owner, canonical_origin="https://moved.example")
        with self.assertRaises(ValidationError):
            require_connection_capability(connection, "landing_metrics", dimensions=["hostname"])
        self.assertEqual(GA4OAuthGrant.objects.get(pk=grant.pk).state, GA4OAuthGrant.State.ACTIVE)
