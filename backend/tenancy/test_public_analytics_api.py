import json
from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from .models import PublicAnalyticsConsentEpoch, PublicAnalyticsObservation
from .public_analytics_source import CONSENT_VERSION
from .test_public_analytics import CONFIG, configure_policy
from .test_public_analytics_source import candidate


@override_settings(**CONFIG, ALLOWED_HOSTS=["product.example.invalid", "api.example.invalid"],
                   SECURE_SSL_REDIRECT=False, CSRF_TRUSTED_ORIGINS=[CONFIG["FRONTEND_ORIGIN"]],
                   CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class PublicAnalyticsApiTests(TestCase):
    def setUp(self):
        configure_policy(self)
        cache.clear()
        self.client = Client(enforce_csrf_checks=True)
        self.headers = {"HTTP_HOST": "product.example.invalid", "HTTP_X_FORWARDED_PROTO": "https",
                        "HTTP_ORIGIN": CONFIG["FRONTEND_ORIGIN"], "HTTP_SEC_FETCH_SITE": "same-origin"}
        csrf = self.client.get("/api/public-analytics/csrf/", **self.headers)
        self.assertEqual(csrf.status_code, 200)
        self.headers["HTTP_X_CSRFTOKEN"] = csrf.json()["csrfToken"]

    def post(self, action, data, **headers):
        return self.client.post(f"/api/public-analytics/{action}/", data=json.dumps(data),
                                content_type="application/json", **{**self.headers, **headers})

    def grant(self):
        result = self.post("grant", {"allowed": True, "consent_version": CONSENT_VERSION})
        self.assertEqual(result.status_code, 200, result.content)
        return result.json()

    def test_actual_anonymous_csrf_capability_original_receipt_and_policy_off_withdrawal(self):
        self.assertEqual(PublicAnalyticsConsentEpoch.objects.count(), 0)
        grant = self.grant()
        self.assertNotIn("sessionid", self.client.cookies)
        payload = {"receipt_proof": grant["receipt_proof"], "candidate": candidate()}
        first = self.post("receipt", payload); second = self.post("receipt", payload)
        self.assertEqual(first.status_code, 200); self.assertEqual(first.json(), second.json())
        self.assertEqual(PublicAnalyticsObservation.objects.count(), 1)
        self.policy_path.unlink()
        self.assertEqual(self.post("receipt", payload).status_code, 409)
        with override_settings(PUBLIC_ANALYTICS_ENABLED=False):
            result = self.post("withdraw", {"receipt_proof": grant["receipt_proof"]})
        self.assertEqual(result.status_code, 200); self.assertEqual(result.json()["state"], "withdrawn")
        self.assertEqual(PublicAnalyticsObservation.objects.count(), 0)
        self.assertIsNotNone(PublicAnalyticsConsentEpoch.objects.get().revoked_at)
        for result in (first, second, result):
            self.assertEqual(result["Cache-Control"], "private, no-store")
            self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")
            self.assertNotIn(grant["receipt_proof"], result.content.decode())

    def test_strict_methods_query_size_json_duplicates_extra_fields_host_and_csrf_reject(self):
        value = {"allowed": True, "consent_version": CONSENT_VERSION}
        for headers in ({"HTTP_ORIGIN": "https://evil.example.invalid"}, {"HTTP_ORIGIN": ""},
                        {"HTTP_HOST": "api.example.invalid"}, {"HTTP_X_CSRFTOKEN": ""},
                        {"HTTP_SEC_FETCH_SITE": "cross-site"}):
            result = self.post("grant", value, **headers)
            self.assertEqual(result.status_code, 403)
            self.assertEqual(result["Cache-Control"], "private, no-store")
            self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")
        for method in ("get", "put", "delete", "head", "options"):
            self.assertEqual(getattr(self.client, method)("/api/public-analytics/grant/", **self.headers).status_code, 405)
        for raw, status, kwargs in (("{}", 400, {}), ('{"allowed":true,"allowed":false}', 400, {}),
                                  ('{"allowed":NaN}', 400, {}), ("\xff", 400, {}),
                                  (" " * 2049, 413, {}), (json.dumps(value), 400, {"HTTP_CONTENT_ENCODING": "gzip"})):
            result = self.client.post("/api/public-analytics/grant/", data=raw.encode("latin-1"),
                                      content_type="application/json", **self.headers, **kwargs)
            self.assertEqual(result.status_code, status, result.content)
        self.assertEqual(self.post("grant", {**value, "customer_export": "private"}).status_code, 400)
        self.assertEqual(self.client.post("/api/public-analytics/grant/?token=private", data=json.dumps(value),
                                         content_type="application/json", **self.headers).status_code, 400)
        self.assertEqual(PublicAnalyticsConsentEpoch.objects.count(), 0)

    def test_explicit_choice_current_original_expiry_and_actual_grant_abuse_limit(self):
        self.assertEqual(self.post("grant", {"allowed": 1, "consent_version": CONSENT_VERSION}).status_code, 409)
        grant = self.grant(); epoch = PublicAnalyticsConsentEpoch.objects.get()
        with patch("tenancy.public_analytics.timezone.now", return_value=epoch.expires_at):
            self.assertEqual(self.post("receipt", {"receipt_proof": grant["receipt_proof"], "candidate": candidate()}).status_code, 409)
        self.assertEqual(PublicAnalyticsObservation.objects.count(), 0)
        for _ in range(8): self.grant()
        result = self.post("grant", {"allowed": True, "consent_version": CONSENT_VERSION})
        self.assertEqual(result.status_code, 429); self.assertEqual(PublicAnalyticsConsentEpoch.objects.count(), 9)
        # Withdraw uses its independent budget even after grant abuse is blocked.
        self.assertEqual(self.post("withdraw", {"receipt_proof": grant["receipt_proof"]}).status_code, 200)

    def test_postcommit_uncertainty_preserves_original_without_implicit_new_epoch_or_replay(self):
        from .public_analytics import record_public_observation
        grant = self.grant(); payload = {"receipt_proof": grant["receipt_proof"], "candidate": candidate()}
        observed = {}
        def lose_response(**kwargs):
            observed.update(record_public_observation(**kwargs))
            raise RuntimeError("Fixture lost response")
        with patch("tenancy.public_analytics_api.record_public_observation", side_effect=lose_response):
            with self.assertRaises(RuntimeError): self.post("receipt", payload)
        self.assertEqual(PublicAnalyticsObservation.objects.count(), 1)
        self.assertEqual(self.post("receipt", payload).json(), observed)
        self.assertEqual(PublicAnalyticsConsentEpoch.objects.count(), 1)

    def test_actual_receipt_and_withdrawal_budgets_are_separate_and_csrf_inspection_is_read_only(self):
        grant = self.grant()
        for _ in range(60):
            self.assertEqual(self.post("receipt", {"receipt_proof": grant["receipt_proof"], "candidate": candidate()}).status_code, 200)
        self.assertEqual(self.post("receipt", {"receipt_proof": grant["receipt_proof"], "candidate": candidate()}).status_code, 429)
        self.assertEqual(PublicAnalyticsObservation.objects.count(), 1)
        for _ in range(60):
            self.assertEqual(self.post("withdraw", {"receipt_proof": grant["receipt_proof"]}).status_code, 200)
        self.assertEqual(self.post("withdraw", {"receipt_proof": grant["receipt_proof"]}).status_code, 429)
        self.assertEqual(PublicAnalyticsObservation.objects.count(), 0)
        for _ in range(29):
            self.assertEqual(self.client.get("/api/public-analytics/csrf/", **self.headers).status_code, 200)
        self.assertEqual(self.client.get("/api/public-analytics/csrf/", **self.headers).status_code, 429)
        self.assertEqual(PublicAnalyticsConsentEpoch.objects.count(), 1)
