from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, TransactionTestCase, override_settings

from config.test_foundations import TEST_STORAGES
from . import test_competitor_collection as root_fixtures
from . import test_competitor_comparison_api as api_fixtures
from . import test_competitor_links_comparison as fixtures
from .competitor_links_comparison import METHOD


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "competitor-links-comparison-api"}},
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}))
class CompetitorLinksComparisonApiTests(TransactionTestCase):
    setUp = fixtures.CompetitorLinksComparisonTests.setUp
    queue = fixtures.CompetitorLinksComparisonTests.queue
    transport = fixtures.CompetitorLinksComparisonTests.transport
    collected = fixtures.CompetitorLinksComparisonTests.collected

    def pair(self):
        cache.clear()
        before = self.collected("api-links-pair-before")
        after = self.collected("api-links-pair-after", b'<a href="//external.example.invalid/one">One</a><a href="//external.example.invalid/two">Two</a>')
        self.base = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/competitor-links-roots/comparison/"
        self.query = f"?previous_job_id={before.pk}&current_job_id={after.pk}"
        self.client.force_login(self.owner)
        return before, after

    def test_genuine_exact_private_links_pair_and_shared_independent_maintained_read_budget(self):
        before, after = self.pair()
        response = self.client.get(self.base + self.query, secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        result = response.json()["comparison"]
        self.assertEqual((result["method_version"], result["url"], result["previous"]["job_id"], result["current"]["job_id"]),
            (METHOD, self.data["origin"] + "/", before.pk, after.pk))
        self.assertEqual(result["previous"]["evidence"], before.output["evidence"])
        self.assertEqual(response["Cache-Control"], "private, no-store"); self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        other = Client(); other.force_login(self.admin)
        self.assertEqual(other.get(self.base + self.query, secure=True).json()["comparison"], result)
        self.assertEqual(Client().get(self.base + self.query, secure=True).status_code, 401)
        cache.clear()
        with override_settings(ACCOUNT_RATE_LIMITS={"competitor_links_root_read": "1/h/ip"}):
            self.assertEqual(self.client.get(self.base + self.query, secure=True).status_code, 200)
            self.assertEqual(other.get(self.base.removesuffix("comparison/"), secure=True).status_code, 429)
            for family in ("competitor-roots", "competitor-pages", "competitor-schema-roots"):
                path = self.base.split("competitor-links-roots/")[0] + family + "/"
                self.assertEqual(other.get(path, secure=True).status_code, 200)

    def test_original_actor_and_genuine_old_family_cannot_enter_links_pair_or_old_root_consumers(self):
        before, after = self.pair()
        other = self.collected("other-actor", actor=self.admin)
        self.assertEqual(self.client.get(self.base + f"?previous_job_id={before.pk}&current_job_id={other.pk}", secure=True).status_code, 409)
        root = root_fixtures.CompetitorCollectionTests.queue(self, "api-actual-root",
            data={key: value for key, value in self.data.items() if key != "url"})
        from . import competitor_collection as collection
        with patch("socket.create_connection", side_effect=AssertionError("No actual egress")):
            self.assertTrue(collection.execute_competitor_collection(root.pk, fetcher=root_fixtures.CompetitorCollectionTests.fetcher(self)))
        root.refresh_from_db(); self.assertEqual(root.status, "succeeded")
        self.assertEqual(self.client.get(self.base + f"?previous_job_id={before.pk}&current_job_id={root.pk}", secure=True).status_code, 403)
        root_path = self.base.replace("competitor-links-roots/", "competitor-roots/")
        self.assertEqual(self.client.get(root_path + self.query, secure=True).status_code, 403)
        self.assertNotIn("comparison", self.client.get(root_path + self.query, secure=True).json())

    test_bodyless_canonical_distinct_query_only_and_current_scoped_source_denials = api_fixtures.CompetitorComparisonApiTests.test_bodyless_canonical_distinct_query_only_and_current_scoped_source_denials
    test_post_serialization_first_record_source_caller_cancellation_and_expiry_loss_withholds_pair = api_fixtures.CompetitorComparisonApiTests.test_post_serialization_first_record_source_caller_cancellation_and_expiry_loss_withholds_pair
    test_final_api_metadata_return_fences_original_authority_for_pair_and_root_detail = api_fixtures.CompetitorComparisonApiTests.test_final_api_metadata_return_fences_original_authority_for_pair_and_root_detail
    test_first_original_cancellation_during_last_post_serialization_second_source_read_withholds_response = api_fixtures.CompetitorComparisonApiTests.test_first_original_cancellation_during_last_post_serialization_second_source_read_withholds_response
