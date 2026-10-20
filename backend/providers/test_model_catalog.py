import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from .models import AIModel, AIProvider
from .services import create_provider


@override_settings(STAFF_MFA_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class ModelCatalogAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.operator = get_user_model().objects.create_superuser("model-staff@example.com", "test-password")
        self.provider = create_provider(actor=self.operator, key="model-provider", name="Provider",
                                        kind=AIProvider.Kind.OPENAI, enabled=True)
        self.browser = Client(enforce_csrf_checks=True)
        self.browser.force_login(self.operator)
        self.browser.get("/_allauth/browser/v1/auth/session", secure=True)
        self.headers = {"HTTP_X_CSRFTOKEN": self.browser.cookies["csrftoken"].value,
                        "HTTP_REFERER": "https://testserver/"}
        self.payload = {"provider_id": self.provider.pk, "identifier": "chosen-model", "name": "Selected model",
                         "capabilities": ["text_generation"], "max_output_tokens": 100,
                         "capability_source": "https://example.com/model", "enabled": True,
                         "input_price_usd_per_million": None, "output_price_usd_per_million": None,
                         "pricing_source": "", "access_tier": "unknown", "privacy_policy_url": ""}

    def post(self, payload=None, *, csrf=True):
        return self.browser.post("/api/platform/models/", json.dumps(payload or self.payload),
                                 content_type="application/json", secure=True,
                                 **(self.headers if csrf else {}))

    def test_staff_upsert_is_scoped_validated_and_csrf_protected(self):
        self.assertEqual(self.post(csrf=False).status_code, 403)
        for invalid in ({**self.payload, "provider_id": self.provider.pk + 100},
                        {**self.payload, "capability_source": "https://example.com/model?secret=fixture"},
                        {**self.payload, "enabled": "true"},
                        {**self.payload, "max_output_tokens": -1},
                        {**self.payload, "capabilities": ["unsupported"]}):
            self.assertNotEqual(self.post(invalid).status_code, 200)
        self.assertFalse(AIModel.objects.exists())
        cache.clear()  # Separate the malicious-input burst from the valid staff write.
        saved = self.post()
        self.assertEqual(saved.status_code, 200, saved.content)
        model = AIModel.objects.get(pk=saved.json()["id"])
        self.assertTrue(model.enabled)
        self.assertIsNotNone(model.capabilities_verified_at)
        self.assertEqual(self.post({**self.payload, "enabled": False}).json()["id"], model.pk)
        listing = self.browser.get("/api/platform/models/", secure=True)
        self.assertEqual((listing.status_code, listing.json()["models"][0]["enabled"]), (200, False))
        self.assertIsNone(listing.json()["models"][0]["input_price_usd_per_million"])
        self.assertEqual(listing["Cache-Control"], "private, no-store")

        add_only = get_user_model().objects.create_user("limited-model@example.com", "test-password", is_staff=True)
        add_only.user_permissions.add(Permission.objects.get(codename="add_aimodel", content_type__app_label="providers"))
        self.browser.force_login(add_only)
        self.browser.get("/_allauth/browser/v1/auth/session", secure=True)
        self.headers["HTTP_X_CSRFTOKEN"] = self.browser.cookies["csrftoken"].value
        self.assertEqual(self.browser.get("/api/platform/models/", secure=True).status_code, 403)
        self.assertEqual(self.post().status_code, 403)

    def test_prices_and_free_tier_require_public_attested_evidence(self):
        for invalid in (
            {"input_price_usd_per_million": "0.10"},
            {"input_price_usd_per_million": "NaN", "output_price_usd_per_million": "1.00"},
            {"input_price_usd_per_million": "-1", "output_price_usd_per_million": "1.00"},
            {"input_price_usd_per_million": "0.10", "output_price_usd_per_million": "1.00",
             "pricing_source": "https://example.com/price?secret=fixture"},
            {"access_tier": "free"},
            {"access_tier": "free", "privacy_policy_url": "https://example.com/privacy#private"},
        ):
            with self.subTest(invalid=invalid):
                cache.clear()  # Each case checks validation rather than the shared staff rate limit.
                self.assertEqual(self.post({**self.payload, **invalid}).status_code, 400)
        self.assertFalse(AIModel.objects.exists())
        cache.clear()
        priced = {**self.payload, "access_tier": "standard", "input_price_usd_per_million": "0.1250",
                  "output_price_usd_per_million": "2.5000", "pricing_source": "https://example.com/prices"}
        self.assertEqual(self.post(priced).status_code, 200)
        model = AIModel.objects.get(identifier="chosen-model")
        self.assertEqual((str(model.input_price_usd_per_million), str(model.output_price_usd_per_million)),
                         ("0.1250", "2.5000"))
        self.assertIsNotNone(model.pricing_verified_at)
        listing = self.browser.get("/api/platform/models/", secure=True).json()["models"][0]
        self.assertEqual((listing["access_tier"], listing["pricing_source"]),
                         ("standard", "https://example.com/prices"))
        free = {**priced, "access_tier": "free", "privacy_policy_url": "https://example.com/privacy"}
        self.assertEqual(self.post(free).status_code, 200)
        self.assertEqual(AIModel.objects.get(pk=model.pk).access_tier, "free")
