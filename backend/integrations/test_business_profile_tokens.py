from cryptography.fernet import Fernet
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings

from .business_profile import SCOPE
from .business_profile_tokens import (CALLBACK_PATH, configured_business_redirect_uri, decrypt_business_refresh_token,
    encrypt_business_refresh_token, exchange_business_code, refresh_business_tokens, revoke_business_tokens)
from .google_tokens import GoogleTokenError

CALLBACK = "https://callback.example.invalid" + CALLBACK_PATH


class BusinessProfileTokenTests(SimpleTestCase):
    payload = {"token_type": "Bearer", "access_token": "ACCESS_SECRET", "refresh_token": "REFRESH_SECRET",
               "scope": SCOPE, "expires_in": 3600}

    def test_exchange_requires_exact_separate_scope_and_callback_before_one_transport_request(self):
        calls = []
        def transport(*, form):
            calls.append(form)
            return self.payload
        tokens = exchange_business_code(code="one-use-code", client_id="business-client", client_secret="APP_SECRET",
                                        redirect_uri=CALLBACK, transport=transport)
        self.assertNotIn("SECRET", repr(tokens))
        self.assertEqual(tokens.refresh_token, "REFRESH_SECRET")
        self.assertEqual(calls, [{"code": "one-use-code", "client_id": "business-client", "client_secret": "APP_SECRET",
                                 "grant_type": "authorization_code", "redirect_uri": CALLBACK}])
        for changes, category in (({"scope": "https://www.googleapis.com/auth/webmasters.readonly"}, "scope_unavailable"),
                                  ({"scope": "https://www.googleapis.com/auth/analytics.readonly"}, "scope_unavailable"),
                                  ({"scope": SCOPE + " openid"}, "scope_unavailable"),
                                  ({"refresh_token": None}, "reauthorization_required"),
                                  ({"expires_in": True}, "malformed_response"),
                                  ({"access_token": "SECRET\nINJECT"}, "malformed_response")):
            with self.subTest(changes=changes), self.assertRaises(GoogleTokenError) as error:
                exchange_business_code(code="code", client_id="client", client_secret="APP_SECRET", redirect_uri=CALLBACK,
                                       transport=lambda **_: {**self.payload, **changes})
            self.assertEqual(error.exception.category, category)
            self.assertNotIn("SECRET", str(error.exception))
        with self.assertRaises(GoogleTokenError):
            exchange_business_code(code="bad\ncode", client_id="client", client_secret="APP_SECRET", redirect_uri=CALLBACK,
                                   transport=transport)
        with self.assertRaises(ValidationError):
            exchange_business_code(code="code", client_id="client", client_secret="APP_SECRET",
                                   redirect_uri="https://callback.example.invalid/api/integrations/google-analytics/oauth/callback/",
                                   transport=transport)
        self.assertEqual(len(calls), 1)

    @override_settings(DEBUG=False)
    def test_callback_rejects_cross_source_query_fragment_userinfo_controls_and_nonproduction_http(self):
        self.assertEqual(configured_business_redirect_uri(CALLBACK), CALLBACK)
        for value in (CALLBACK + "?code=SECRET", CALLBACK + "#SECRET", CALLBACK + "/", "https://user@callback.example.invalid" + CALLBACK_PATH,
                      "http://127.0.0.1:18000" + CALLBACK_PATH, "https://callback.example.invalid:444" + CALLBACK_PATH,
                      "\n" + CALLBACK, CALLBACK.replace("/api/", "/api/%2f"), "https://callback.example.invalid\\evil" + CALLBACK_PATH):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                configured_business_redirect_uri(value)
        with override_settings(DEBUG=True):
            self.assertEqual(configured_business_redirect_uri("http://127.0.0.1:18000" + CALLBACK_PATH),
                             "http://127.0.0.1:18000" + CALLBACK_PATH)

    def test_purpose_and_tenant_bound_ciphertext_does_not_accept_other_provider_material_or_wrong_keys(self):
        old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
        scope = {"organization_id": 12, "project_id": 34}
        with override_settings(PROVIDER_ENCRYPTION_KEYS=(old,)):
            encrypted = encrypt_business_refresh_token("REFRESH_SECRET", **scope)
            self.assertNotIn("SECRET", encrypted)
            self.assertEqual(decrypt_business_refresh_token(encrypted, **scope), "REFRESH_SECRET")
            for context in ({"organization_id": 13, "project_id": 34}, {"organization_id": 12, "project_id": 35},
                            {"organization_id": True, "project_id": 34}):
                with self.assertRaises(GoogleTokenError):
                    decrypt_business_refresh_token(encrypted, **context)
            alien = "v1:" + Fernet(old.encode()).encrypt(b"REFRESH_SECRET").decode()
            with self.assertRaises(GoogleTokenError):
                decrypt_business_refresh_token(alien, **scope)
        with override_settings(PROVIDER_ENCRYPTION_KEYS=(new, old)):
            self.assertEqual(decrypt_business_refresh_token(encrypted, **scope), "REFRESH_SECRET")
        for keys in ((new,), (), ("invalid",), None):
            with override_settings(PROVIDER_ENCRYPTION_KEYS=keys), self.assertRaises(GoogleTokenError) as error:
                decrypt_business_refresh_token(encrypted, **scope)
            self.assertEqual(error.exception.category, "credential_unavailable")
            self.assertNotIn("SECRET", str(error.exception))

    def test_refresh_scope_and_confirmed_remote_revoke_never_replay_or_abandon_unconfirmed_token(self):
        with override_settings(PROVIDER_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),)):
            scope = {"organization_id": 12, "project_id": 34}
            encrypted = encrypt_business_refresh_token("REFRESH_SECRET", **scope)
            calls = []
            def transport(*, form):
                calls.append(form)
                return {**self.payload, "refresh_token": None}
            tokens = refresh_business_tokens(encrypted_refresh=encrypted, **scope, client_id="business-client",
                                              client_secret="APP_SECRET", transport=transport)
            self.assertEqual(tokens.access_token, "ACCESS_SECRET")
            self.assertEqual(calls, [{"refresh_token": "REFRESH_SECRET", "client_id": "business-client",
                                     "client_secret": "APP_SECRET", "grant_type": "refresh_token"}])
            with self.assertRaises(GoogleTokenError) as error:
                refresh_business_tokens(encrypted_refresh=encrypted, **scope, client_id="client", client_secret="APP_SECRET",
                    transport=lambda **_: {**self.payload, "scope": "https://www.googleapis.com/auth/analytics.readonly"})
            self.assertEqual(error.exception.category, "scope_unavailable")
            revoked = []
            self.assertTrue(revoke_business_tokens(encrypted_refresh=encrypted, **scope,
                                                  transport=lambda **kwargs: revoked.append(kwargs) or True))
            self.assertEqual(revoked, [{"token": "REFRESH_SECRET"}])
            for outcome in (False, None, {"success": True}):
                with self.assertRaises(GoogleTokenError) as error:
                    revoke_business_tokens(encrypted_refresh=encrypted, **scope, transport=lambda **_: outcome)
                self.assertEqual(error.exception.category, "revocation_unconfirmed")
            self.assertEqual(decrypt_business_refresh_token(encrypted, **scope), "REFRESH_SECRET")
