from unittest.mock import patch
from cryptography.fernet import Fernet
from providers.models import OrganizationPerformanceKey
from django.db import transaction
from django.utils import timezone
from . import competitor_api as api

from django.core.cache import cache
from django.test import Client, TransactionTestCase, override_settings

from config.test_foundations import TEST_STORAGES
from . import test_competitor_collection as root_fixtures
from . import test_competitor_comparison_api as api_fixtures
from . import test_competitor_lab_comparison as fixtures
from .competitor_lab_comparison import METHOD


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False, PERFORMANCE_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),), GOOGLE_PERFORMANCE_API_KEY="",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "competitor-lighthouse-comparison-api"}},
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}))
class CompetitorLabComparisonApiTests(TransactionTestCase):
    setUp = fixtures.CompetitorLabComparisonTests.setUp
    queue = fixtures.CompetitorLabComparisonTests.queue
    transport = fixtures.CompetitorLabComparisonTests.transport
    collected = fixtures.CompetitorLabComparisonTests.collected
    fetcher = fixtures.CompetitorLabComparisonTests.fetcher
    payload = fixtures.CompetitorLabComparisonTests.payload
    revoke = fixtures.CompetitorLabComparisonTests.revoke

    def pair(self):
        cache.clear()
        before = self.collected("api-page-pair-before")
        payload = self.payload(); payload["lighthouseResult"]["categories"]["performance"]["score"] = 0.5
        after = self.collected("api-page-pair-after", payload)
        self.base = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/competitor-lighthouse/comparison/"
        self.query = f"?previous_job_id={before.pk}&current_job_id={after.pk}"
        self.client.force_login(self.owner)
        return before, after

    def test_genuine_exact_private_page_pair_and_shared_independent_maintained_read_budget(self):
        before, after = self.pair()
        response = self.client.get(self.base + self.query, secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        result = response.json()["comparison"]
        self.assertEqual((result["method_version"], result["url"], result["previous"]["job_id"], result["current"]["job_id"]),
            (METHOD, self.data["url"], before.pk, after.pk))
        self.assertEqual(result["previous"]["evidence"], before.output["evidence"])
        self.assertEqual(result["current"]["evidence"], after.output["evidence"])
        self.assertEqual(result["score_deltas"]["performance"], -0.25)
        self.assertNotIn("metadata_changed", result)
        self.assertNotIn("headings_changed", result)
        self.assertNotIn("count_deltas", result)
        self.assertEqual(result["state"], "arithmetic_original_lab_samples")
        self.assertEqual(response["Cache-Control"], "private, no-store"); self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        other = Client(); other.force_login(self.admin)
        self.assertEqual(other.get(self.base + self.query, secure=True).json()["comparison"], result)
        self.assertEqual(Client().get(self.base + self.query, secure=True).status_code, 401)
        cache.clear()
        with override_settings(ACCOUNT_RATE_LIMITS={"competitor_lighthouse_read": "1/h/ip"}):
            self.assertEqual(self.client.get(self.base + self.query, secure=True).status_code, 200)
            self.assertEqual(other.get(self.base.removesuffix("comparison/"), secure=True).status_code, 429)
            for family in ("competitor-roots", "competitor-schema-roots", "competitor-links-roots", "competitor-pages", "competitor-page-headings", "competitor-page-destinations", "competitor-page-dates"):
                path = self.base.split("competitor-lighthouse/")[0] + family + "/"
                self.assertEqual(other.get(path, secure=True).status_code, 200)

    def test_other_uri_original_actor_and_genuine_old_family_cannot_enter_page_pair_or_old_root_consumers(self):
        before, after = self.pair()
        for key, changes in (("other-uri", {"data": {**self.data, "url": self.data["url"] + "-other"}}), ("other-actor", {"actor": self.admin})):
            other = self.collected(key, **changes)
            self.assertEqual(self.client.get(self.base + f"?previous_job_id={before.pk}&current_job_id={other.pk}", secure=True).status_code, 409)
        from . import competitor_collection as collection
        for handler in (name for name in collection.COMPETITOR_HANDLERS if name != "collect_competitor_lighthouse"):
            data = {key:value for key,value in self.data.items() if key not in {"strategy","provider_processing_permission"} and (key != "url" or handler in {"collect_competitor_page", "collect_competitor_page_headings", "collect_competitor_page_destinations", "collect_competitor_page_dates", "collect_competitor_page_formats"})}
            other = root_fixtures.CompetitorCollectionTests.queue(self, "api-actual-"+handler, handler=handler, data=data)
            with patch("socket.create_connection", side_effect=AssertionError("No actual egress")):
                self.assertTrue(collection.execute_competitor_collection(other.pk, fetcher=root_fixtures.CompetitorCollectionTests.fetcher(self), handler=handler))
            other.refresh_from_db(); self.assertEqual(other.status, "succeeded")
            response = self.client.get(self.base + f"?previous_job_id={before.pk}&current_job_id={other.pk}", secure=True)
            self.assertEqual(response.status_code, 403); self.assertNotIn("comparison", response.json())
        for family in ("competitor-roots", "competitor-pages", "competitor-schema-roots", "competitor-links-roots", "competitor-page-headings", "competitor-page-destinations", "competitor-page-dates"):
            path = self.base.replace("competitor-lighthouse/", family + "/")
            response = self.client.get(path + self.query, secure=True)
            self.assertEqual(response.status_code, 403); self.assertNotIn("comparison", response.json())

    def test_nullable_zero_runtime_version_and_report_time_incompatibility_remain_private_original_samples(self):
        before, _ = self.pair()
        for index, kind in enumerate(("runtime", "version", "cached", "nullable")):
            payload = self.payload(); lab = payload["lighthouseResult"]
            if kind == "runtime": lab["runtimeError"] = {"code":"private", "message":"secret"}
            elif kind == "version": lab["lighthouseVersion"] = "13.0.0"
            elif kind == "cached": lab["fetchTime"] = before.output["evidence"]["provider_reported_at"]
            else: lab["categories"] = {}; lab["audits"] = {}
            after = self.collected("coverage-"+str(index), payload)
            response = self.client.get(self.base + f"?previous_job_id={before.pk}&current_job_id={after.pk}", secure=True)
            self.assertEqual(response.status_code, 200, response.content)
            result = response.json()["comparison"]
            self.assertEqual(result["state"], "arithmetic_original_lab_samples" if kind == "nullable" else "incomparable_lab_samples")
            self.assertTrue(all(value is None for value in result["score_deltas"].values()))
            self.assertEqual(result["current"]["evidence"], after.output["evidence"])
            self.assertNotIn(b"secret", response.content)

    def test_final_unchanged_api_metadata_cannot_release_either_original_after_key_reference_loss(self):
        before, after = self.pair(); self.client.force_login(self.admin)
        original = api._metadata
        with transaction.atomic():
            calls = []
            def changed(job_id):
                value = original(job_id); calls.append(job_id)
                if len(calls) == 4: OrganizationPerformanceKey.objects.filter(pk=self.key.pk).update(rotated_at=timezone.now())
                return value
            with patch.object(api, "_metadata", side_effect=changed): response = self.client.get(self.base + self.query, secure=True)
            self.assertEqual(len(calls),4); self.assertEqual(response.status_code,403,response.content)
            self.assertNotIn(b'"comparison"', response.content); transaction.set_rollback(True)

    test_bodyless_canonical_distinct_query_only_and_current_scoped_source_denials = api_fixtures.CompetitorComparisonApiTests.test_bodyless_canonical_distinct_query_only_and_current_scoped_source_denials
    test_post_serialization_first_record_source_caller_cancellation_and_expiry_loss_withholds_pair = api_fixtures.CompetitorComparisonApiTests.test_post_serialization_first_record_source_caller_cancellation_and_expiry_loss_withholds_pair
    test_final_api_metadata_return_fences_original_authority_for_pair_and_root_detail = api_fixtures.CompetitorComparisonApiTests.test_final_api_metadata_return_fences_original_authority_for_pair_and_root_detail
    test_first_original_cancellation_during_last_post_serialization_second_source_read_withholds_response = api_fixtures.CompetitorComparisonApiTests.test_first_original_cancellation_during_last_post_serialization_second_source_read_withholds_response
