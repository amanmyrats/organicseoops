from copy import deepcopy
from datetime import timedelta
from unittest.mock import Mock, patch

from cryptography.fernet import Fernet
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from providers.google_app import (google_business_oauth_client, revoke_google_oauth_application,
                                  set_google_oauth_application)
from providers.models import GoogleOAuthApplication
from tenancy.customer_inventory import inventory_customer_data, require_complete_ownership_map
from tenancy.models import OrganizationDeletionRun, ProjectConfiguration, ProjectOriginVerification
from tenancy.closure_grants import revoke_closed_business_grant
from tenancy.deletion import delete_customer_database_records, prepare_customer_data_deletion
from . import test_business_profile as fixtures
from .business_profile import POLICY_VERSION
from .business_profile_oauth import (begin_business_oauth_intent, complete_business_oauth,
    consume_business_oauth_intent, refresh_business_grant, require_business_grant, revoke_business_grant)
from .business_profile_tokens import decrypt_business_refresh_token
from .google_tokens import GoogleTokenError, GoogleTokens
from .models import BusinessProfileOAuthGrant, BusinessProfileOAuthIntent
from .oauth import OAuthStateError

KEY = Fernet.generate_key().decode()
CALLBACK = "https://app.example.invalid/api/integrations/google-business-profile/oauth/callback/"


@override_settings(PROVIDER_ENCRYPTION_KEYS=(KEY,), STAFF_MFA_REQUIRED=False,
    SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=["testserver"],
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class BusinessConsentTests(TransactionTestCase):
    review = fixtures.BusinessProfileAuthorityTests.review

    def setUp(self):
        fixtures.BusinessProfileAuthorityTests.setUp(self)
        self.staff = get_user_model().objects.create_superuser("gbp-staff@example.invalid", "Test passphrase 99!")
        self.app = set_google_oauth_application(actor=self.staff, key="business_profile", client_id="gbp-client",
            client_secret="GBP_APP_SECRET", redirect_uri=CALLBACK)
        self.session = "fixture-browser-session-1234567890"

    def begin(self):
        return begin_business_oauth_intent(project=self.project, actor=self.owner, session_key=self.session,
            selection=self.selection, policy_version=POLICY_VERSION)

    def complete(self, state, exchange=None):
        return complete_business_oauth(actor=self.owner, session_key=self.session, state=state, callback_url=CALLBACK,
            code="CODE_SECRET", exchange=exchange or Mock(return_value=GoogleTokens(
                "ACCESS_SECRET", "REFRESH_SECRET", timezone.now() + timedelta(hours=1))))

    def test_consumed_before_exchange_session_replay_exact_binding_no_content_and_redacted_admin(self):
        intent, state = self.begin()
        self.assertNotIn(state, intent.state_digest)
        for changes, exception in (({"session_key": "another-browser-session-1234567890"}, PermissionDenied),
                                    ({"actor": self.staff}, PermissionDenied),
                                    ({"callback_url": CALLBACK + "?foreign=1"}, OAuthStateError)):
            with self.assertRaises(exception):
                consume_business_oauth_intent(**{**dict(actor=self.owner, session_key=self.session, state=state,
                                                       callback_url=CALLBACK), **changes})
        seen = []
        def exchange(**kwargs):
            seen.append(kwargs)
            intent.refresh_from_db()
            self.assertEqual(intent.status, "consumed")
            return GoogleTokens("ACCESS_SECRET", "REFRESH_SECRET", timezone.now() + timedelta(hours=1))
        grant = self.complete(state, exchange)
        self.assertEqual(grant.state, "pending_selection")
        self.assertEqual(decrypt_business_refresh_token(grant.encrypted_refresh_token,
            organization_id=self.org.pk, project_id=self.project.pk), "REFRESH_SECRET")
        self.assertEqual(seen[0]["client_id"], "gbp-client")
        with self.assertRaises(OAuthStateError):
            self.complete(state, Mock(side_effect=AssertionError("must not exchange twice")))
        with self.assertRaises(ValidationError):
            self.begin()
        require_complete_ownership_map()
        inventory = inventory_customer_data(organization=self.org, actor=self.owner)
        self.assertIn({"model": "integrations.BusinessProfileOAuthGrant", "count": 1}, inventory["secret_bearing"])
        for model in (BusinessProfileOAuthGrant, BusinessProfileOAuthIntent):
            display = admin.site._registry[model]
            self.assertFalse(display.has_change_permission(None))
            self.assertNotIn("encrypted_refresh_token", display.fields)
            self.assertNotIn("session_digest", display.fields)
            self.assertNotIn("selection", display.fields)
        self.assertNotIn("SECRET", repr(google_business_oauth_client()))
        from tenancy.customer_export import complete_bounded_customer_archive
        from io import BytesIO
        from zipfile import ZipFile
        with patch("tenancy.customer_export.iter_project_artifact_keys", return_value=iter(())):
            archive_bytes = complete_bounded_customer_archive(organization=self.org, actor=self.owner)
        with ZipFile(BytesIO(archive_bytes)) as archive:
            self.assertFalse(any("BusinessProfileOAuth" in path for path in archive.namelist()))
            self.assertFalse(any(b"REFRESH_SECRET" in archive.read(path) or b"GBP_APP_SECRET" in archive.read(path)
                                 for path in archive.namelist()))
        malformed = deepcopy(self.selection)
        malformed["reviews"] = fixtures.reviews()
        with self.assertRaises(ValidationError):
            begin_business_oauth_intent(project=self.project, actor=self.owner, session_key=self.session,
                selection=malformed, policy_version=POLICY_VERSION)

    def test_stale_app_config_verification_policy_denial_and_no_exchange(self):
        with self.assertRaises(ValidationError):
            begin_business_oauth_intent(project=self.project, actor=self.owner, session_key=self.session,
                selection=self.selection, policy_version="unreviewed")
        intent, state = self.begin()
        ProjectConfiguration.objects.filter(pk=self.config.pk).update(revision=self.config.revision + 1)
        with self.assertRaises(OAuthStateError):
            self.complete(state, Mock(side_effect=AssertionError("stale authority must not exchange")))
        intent.refresh_from_db()
        self.assertEqual(intent.status, "denied")
        self.assertFalse(BusinessProfileOAuthGrant.objects.exists())
        ProjectConfiguration.objects.filter(pk=self.config.pk).update(revision=self.config.revision)
        intent, state = self.begin()
        GoogleOAuthApplication.objects.filter(pk=self.app.pk).update(rotated_at=timezone.now())
        with self.assertRaises(OAuthStateError):
            self.complete(state)
        intent.refresh_from_db()
        self.assertEqual(intent.status, "denied")
        _, state = self.begin()
        denied, _ = consume_business_oauth_intent(actor=self.owner, session_key=self.session, state=state,
                                                  callback_url=CALLBACK, provider_denied=True)
        self.assertEqual(denied.status, "denied")

    def test_app_revoked_during_exchange_keeps_issued_material_disabled_for_confirmed_retry(self):
        _, state = self.begin()
        def exchange(**_kwargs):
            revoke_google_oauth_application(actor=self.staff, key="business_profile")
            return GoogleTokens("ACCESS_SECRET", "REFRESH_SECRET", timezone.now() + timedelta(hours=1))
        grant = self.complete(state, exchange)
        self.assertEqual(grant.state, "revocation_pending")
        with self.assertRaises(GoogleTokenError):
            google_business_oauth_client()
        with self.assertRaises(PermissionDenied):
            require_business_grant(grant=grant, actor=self.owner, expected_revision=0)
        with self.assertRaises(GoogleTokenError):
            revoke_business_grant(grant=grant, actor=self.owner, revoke=lambda **_kwargs: False)
        grant.refresh_from_db()
        self.assertTrue(grant.encrypted_refresh_token)
        grant = revoke_business_grant(grant=grant, actor=self.owner, revoke=lambda **_kwargs: True)
        self.assertEqual((grant.state, grant.encrypted_refresh_token), ("revoked", ""))
        self.assertEqual(revoke_business_grant(grant=grant, actor=self.owner,
            revoke=Mock(side_effect=AssertionError("already revoked"))).pk, grant.pk)

    def test_mid_exchange_actor_loss_and_mid_refresh_verification_loss_never_deliver(self):
        _, state = self.begin()
        def exchange(**_kwargs):
            get_user_model().objects.filter(pk=self.owner.pk).update(is_active=False)
            return GoogleTokens("ACCESS_SECRET", "REFRESH_SECRET", timezone.now() + timedelta(hours=1))
        grant = self.complete(state, exchange)
        self.assertEqual(grant.state, "revocation_pending")
        get_user_model().objects.filter(pk=self.owner.pk).update(is_active=True)
        revoke_business_grant(grant=grant, actor=self.owner, revoke=lambda **_kwargs: True)
        _, state = self.begin()
        grant = self.complete(state)
        seen = []
        def refresh(**_kwargs):
            ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(state="revoked", revoked_at=timezone.now())
            return GoogleTokens("ACCESS_SECRET", None, timezone.now() + timedelta(hours=1))
        with self.assertRaises(PermissionDenied):
            refresh_business_grant(grant=grant, actor=self.owner, expected_revision=0,
                before_request=seen.append, refresh=refresh)
        self.assertEqual(seen, ["token_refresh"])
        with self.assertRaises(PermissionDenied):
            require_business_grant(grant=grant, actor=self.staff, expected_revision=0)

    def test_write_only_staff_csrf_mfa_app_purpose_no_fallback_and_rotation_blocks_pending(self):
        from django.core.cache import cache
        cache.clear()
        path = "/api/platform/integrations/google-business-app/"
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.owner)
        self.assertEqual(browser.get(path).status_code, 403)
        browser.force_login(self.staff)
        self.assertNotIn("SECRET", browser.get(path).content.decode())
        self.assertEqual(browser.delete(path).status_code, 403)
        with override_settings(STAFF_MFA_REQUIRED=True):
            self.assertEqual(browser.get(path).status_code, 403)
        browser.get("/_allauth/browser/v1/auth/session")
        response = browser.post(path, data={"client_id": "gbp-client", "client_secret": "GBP_APP_SECRET",
            "redirect_uri": CALLBACK}, content_type="application/json",
            HTTP_X_CSRFTOKEN=browser.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"configured": True})
        _, _state = self.begin()
        with self.assertRaises(ValidationError):
            set_google_oauth_application(actor=self.staff, key="business_profile", client_id="replacement",
                client_secret="replacement", redirect_uri=CALLBACK)
        # Same bootstrap does not permit substitution of a different application's ciphertext.
        GoogleOAuthApplication.objects.filter(pk=self.app.pk).update(
            encrypted_secret="v1:" + Fernet(KEY.encode()).encrypt(b"another-app-secret").decode())
        with self.assertRaises(GoogleTokenError):
            google_business_oauth_client()
        GoogleOAuthApplication.objects.filter(pk=self.app.pk).delete()
        with override_settings(GOOGLE_OAUTH_CLIENT_ID="legacy", GOOGLE_OAUTH_CLIENT_SECRET="legacy",
                               GOOGLE_OAUTH_REDIRECT_URI=CALLBACK):
            with self.assertRaises(GoogleTokenError):
                google_business_oauth_client()

    def test_retention_disable_pending_status_remote_failure_blocks_deletion_then_confirmed_erasure(self):
        _, state = self.begin()
        grant = self.complete(state)
        from tenancy.models import OrganizationTrial
        end = timezone.now() - timedelta(days=91)
        OrganizationTrial.objects.filter(organization=self.org).update(started_at=end - timedelta(days=30), ends_at=end)
        run = prepare_customer_data_deletion(organization=self.org)
        grant.refresh_from_db()
        self.assertEqual(grant.state, "revocation_pending")
        self.assertEqual(revoke_closed_business_grant(grant_id=grant.pk, revoke=lambda **_kwargs: False).state,
                         "revocation_pending")
        OrganizationDeletionRun.objects.filter(pk=run.pk).update(state="storage_cleared")
        run.refresh_from_db()
        with self.assertRaisesMessage(ValidationError, "Confirm provider grant revocation"):
            delete_customer_database_records(run=run)
        confirmed = revoke_closed_business_grant(grant_id=grant.pk, revoke=lambda **_kwargs: True)
        self.assertEqual((confirmed.state, confirmed.encrypted_refresh_token), ("revoked", ""))
        with patch("tenancy.deletion.project_artifact_versions_remain", return_value=False), patch(
            "tenancy.deletion.organization_export_versions_remain", return_value=False):
            self.assertEqual(delete_customer_database_records(run=run).state, "complete")
        self.assertFalse(BusinessProfileOAuthGrant.objects.exists())
        self.assertFalse(BusinessProfileOAuthIntent.objects.exists())

    def test_owner_closure_denies_pending_consent_and_disables_grant_in_current_private_status(self):
        from django.test import RequestFactory
        from tenancy.closure import close_organization_locally
        intent, state = self.begin()
        grant = self.complete(state)
        request = RequestFactory().post("/")
        request.user = self.owner
        with patch("tenancy.services.did_recently_authenticate", return_value=True):
            close_organization_locally(organization=self.org, actor=self.owner, request=request)
        grant.refresh_from_db()
        self.assertEqual(grant.state, "revocation_pending")
        browser = Client()
        browser.force_login(self.owner)
        response = browser.get(f"/api/organizations/{self.org.pk}/closure-status/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["remote_revocation_pending"]["business_profile"], 1)
        self.assertEqual(response.json()["pending_grants"]["business_profile"], [grant.pk])
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertNotIn("SECRET", response.content.decode())
        self.assertEqual(revoke_closed_business_grant(grant_id=grant.pk, revoke=lambda **_kwargs: True).state, "revoked")

    def test_closure_during_exchange_cannot_delete_consent_before_disabled_token_capture(self):
        from django.test import RequestFactory
        from tenancy.closure import close_organization_locally
        _, state = self.begin()
        request = RequestFactory().post("/")
        request.user = self.owner
        def exchange(**_kwargs):
            with patch("tenancy.services.did_recently_authenticate", return_value=True):
                closed = close_organization_locally(organization=self.org, actor=self.owner, request=request)
            run = prepare_customer_data_deletion(organization=closed)
            OrganizationDeletionRun.objects.filter(pk=run.pk).update(state="storage_cleared")
            with self.assertRaisesMessage(ValidationError, "in-flight business consent exchange"):
                delete_customer_database_records(run=run)
            return GoogleTokens("ACCESS_SECRET", "REFRESH_SECRET", timezone.now() + timedelta(hours=1))
        grant = self.complete(state, exchange)
        self.assertEqual(grant.state, "revocation_pending")
        self.assertEqual(revoke_closed_business_grant(grant_id=grant.pk, revoke=lambda **_kwargs: True).state, "revoked")
