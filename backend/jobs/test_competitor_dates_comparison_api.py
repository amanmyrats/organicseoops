from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, TransactionTestCase, override_settings

from config.test_foundations import TEST_STORAGES
from . import test_competitor_collection as root_fixtures
from . import test_competitor_comparison_api as api_fixtures
from . import test_competitor_dates_comparison as fixtures
from .competitor_dates_comparison import METHOD


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "competitor-dates-comparison-api"}},
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}))
class CompetitorDatesComparisonApiTests(TransactionTestCase):
    setUp = fixtures.CompetitorDatesComparisonTests.setUp
    queue = fixtures.CompetitorDatesComparisonTests.queue
    transport = fixtures.CompetitorDatesComparisonTests.transport
    collected = fixtures.CompetitorDatesComparisonTests.collected

    def pair(self):
        cache.clear()
        before = self.collected("api-page-pair-before")
        after = self.collected("api-page-pair-after", b'<meta property="article:modified_time" content="not a calendar date"><meta property="article:published_time" content="2099-01-01">')
        self.base = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/competitor-page-dates/comparison/"
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
        self.assertTrue(result["declarations_changed"])
        self.assertNotIn("metadata_changed", result)
        self.assertNotIn("headings_changed", result)
        self.assertNotIn("count_deltas", result)
        self.assertEqual(result["current"]["evidence"]["declarations"][0]["value"], "not a calendar date")
        self.assertEqual(response["Cache-Control"], "private, no-store"); self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        other = Client(); other.force_login(self.admin)
        self.assertEqual(other.get(self.base + self.query, secure=True).json()["comparison"], result)
        self.assertEqual(Client().get(self.base + self.query, secure=True).status_code, 401)
        cache.clear()
        with override_settings(ACCOUNT_RATE_LIMITS={"competitor_page_dates_read": "1/h/ip"}):
            self.assertEqual(self.client.get(self.base + self.query, secure=True).status_code, 200)
            self.assertEqual(other.get(self.base.removesuffix("comparison/"), secure=True).status_code, 429)
            for family in ("competitor-roots", "competitor-schema-roots", "competitor-links-roots", "competitor-pages", "competitor-page-headings", "competitor-page-destinations"):
                path = self.base.split("competitor-page-dates/")[0] + family + "/"
                self.assertEqual(other.get(path, secure=True).status_code, 200)

    def test_other_uri_original_actor_and_genuine_old_family_cannot_enter_page_pair_or_old_root_consumers(self):
        before, after = self.pair()
        for key, changes in (("other-uri", {"data": {**self.data, "url": self.data["url"] + "-other"}}), ("other-actor", {"actor": self.admin})):
            other = self.collected(key, **changes)
            self.assertEqual(self.client.get(self.base + f"?previous_job_id={before.pk}&current_job_id={other.pk}", secure=True).status_code, 409)
        from . import competitor_collection as collection
        for handler in (name for name in collection.COMPETITOR_HANDLERS if name != "collect_competitor_page_dates"):
            data = self.data if handler in {"collect_competitor_page", "collect_competitor_page_headings", "collect_competitor_page_destinations", "collect_competitor_page_formats"} else {key: value for key, value in self.data.items() if key != "url"}
            other = root_fixtures.CompetitorCollectionTests.queue(self, "api-actual-"+handler, handler=handler, data=data)
            with patch("socket.create_connection", side_effect=AssertionError("No actual egress")):
                self.assertTrue(collection.execute_competitor_collection(other.pk, fetcher=root_fixtures.CompetitorCollectionTests.fetcher(self), handler=handler))
            other.refresh_from_db(); self.assertEqual(other.status, "succeeded")
            response = self.client.get(self.base + f"?previous_job_id={before.pk}&current_job_id={other.pk}", secure=True)
            self.assertEqual(response.status_code, 403); self.assertNotIn("comparison", response.json())
        for family in ("competitor-roots", "competitor-pages", "competitor-schema-roots", "competitor-links-roots", "competitor-page-headings", "competitor-page-destinations"):
            path = self.base.replace("competitor-page-dates/", family + "/")
            response = self.client.get(path + self.query, secure=True)
            self.assertEqual(response.status_code, 403); self.assertNotIn("comparison", response.json())

    def test_observed_empty_and_empty_value_vs_whole_unavailable_or_truncated_date_pair(self):
        self.pair()
        before = self.collected("api-empty-before", b"<p>Known empty</p>")
        for key, body, comparable, changed in (
            ("empty", b"<p>Still empty</p>", True, False),
            ("empty-value", b'<meta property="article:published_time" content="">', True, True),
            ("unavailable", b"<template>Unclosed", False, None),
            ("truncated", b'<meta property="article:published_time" content="' + b"x"*81 + b'">', False, None)):
            after = self.collected("api-coverage-"+key, body)
            response = self.client.get(self.base + f"?previous_job_id={before.pk}&current_job_id={after.pk}", secure=True)
            self.assertEqual(response.status_code, 200, response.content)
            result = response.json()["comparison"]
            self.assertEqual(result["comparable"], comparable); self.assertEqual(result["declarations_changed"], changed)
            self.assertNotIn("count_deltas", result)
            self.assertEqual(result["previous"]["evidence"], before.output["evidence"])
            self.assertEqual(result["current"]["evidence"], after.output["evidence"])

    test_bodyless_canonical_distinct_query_only_and_current_scoped_source_denials = api_fixtures.CompetitorComparisonApiTests.test_bodyless_canonical_distinct_query_only_and_current_scoped_source_denials
    test_post_serialization_first_record_source_caller_cancellation_and_expiry_loss_withholds_pair = api_fixtures.CompetitorComparisonApiTests.test_post_serialization_first_record_source_caller_cancellation_and_expiry_loss_withholds_pair
    test_final_api_metadata_return_fences_original_authority_for_pair_and_root_detail = api_fixtures.CompetitorComparisonApiTests.test_final_api_metadata_return_fences_original_authority_for_pair_and_root_detail
    test_first_original_cancellation_during_last_post_serialization_second_source_read_withholds_response = api_fixtures.CompetitorComparisonApiTests.test_first_original_cancellation_during_last_post_serialization_second_source_read_withholds_response
