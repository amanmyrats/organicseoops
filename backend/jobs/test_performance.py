from datetime import timedelta

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from tenancy.services import create_organization, create_project

from .performance import compare_crux_history, parse_crux, parse_pagespeed_lab


class PerformanceEvidenceTests(TestCase):
    def setUp(self):
        owner = get_user_model().objects.create_user("performance@example.com", password="test-password")
        EmailAddress.objects.create(user=owner, email=owner.email, verified=True, primary=True)
        organization = create_organization(user=owner, name="Performance")
        self.project = create_project(organization=organization, user=owner, name="Site",
                                      canonical_origin="https://performance.example", aliases=["https://m.performance.example"])
        self.page = "https://performance.example/page"
        self.period_end = timezone.now().date() - timedelta(days=2)

    def period(self, ending):
        def part(value):
            return {"year": value.year, "month": value.month, "day": value.day}
        return {"firstDate": part(ending - timedelta(days=27)), "lastDate": part(ending)}

    def crux(self, *, scope="url", history=False):
        metrics = {
            "largest_contentful_paint": {"percentiles": {"p75": 2500}},
            "interaction_to_next_paint": {"percentiles": {"p75": 501}},
            "cumulative_layout_shift": {"percentiles": {"p75": "0.10"}},
            "experimental_time_to_first_byte": {"percentiles": {"p75": 800}},
        }
        record = {"key": {"formFactor": "PHONE", scope: self.page if scope == "url" else "https://performance.example"},
                  "metrics": metrics, "collectionPeriod": self.period(self.period_end)}
        if history:
            record.pop("collectionPeriod")
            record["collectionPeriods"] = [self.period(self.period_end - timedelta(days=7)), self.period(self.period_end)]
            record["metrics"] = {
                "largest_contentful_paint": {"percentilesTimeseries": {"p75s": [2400, None]}},
                "interaction_to_next_paint": {"percentilesTimeseries": {"p75s": [201, 501]}},
                "cumulative_layout_shift": {"percentilesTimeseries": {"p75s": ["0.11", "NaN"]}},
            }
        return {"record": record}

    def test_field_current_boundary_and_origin_fallback_remain_distinct(self):
        current = parse_crux(project=self.project, requested_url=self.page, requested_grain="page",
                             form_factor="PHONE", payload=self.crux())
        metrics = {entry["name"]: entry for entry in current["metrics"]}
        self.assertEqual((metrics["LCP"]["p75"], metrics["LCP"]["grade"]), (2500, "good"))
        self.assertEqual((metrics["INP"]["p75"], metrics["INP"]["grade"]), (501, "poor"))
        self.assertEqual((metrics["CLS"]["p75"], metrics["CLS"]["unit"], metrics["CLS"]["grade"]),
                         ("0.10", "unitless", "good"))
        self.assertEqual(metrics["TTFB"]["grade"], "not_evaluated")
        self.assertEqual(current["requested_grain"], "page")
        self.assertFalse(current["origin_fallback"])
        fallback = parse_crux(project=self.project, requested_url=self.page, requested_grain="page",
                              form_factor="PHONE", payload=self.crux(scope="origin"))
        self.assertTrue(fallback["origin_fallback"])
        self.assertEqual(fallback["observed_grain"], "origin")
        origin = parse_crux(project=self.project, requested_url="https://performance.example",
                            requested_grain="origin", form_factor="PHONE", payload=self.crux(scope="origin"))
        self.assertEqual((origin["requested_grain"], origin["observed_grain"]), ("origin", "origin"))

    def test_history_keeps_overlap_and_missing_eligibility_unknown(self):
        history = parse_crux(project=self.project, requested_url=self.page, requested_grain="page",
                             form_factor="PHONE", history=True, payload=self.crux(history=True))
        self.assertEqual(len(history["collection_periods"]), 2)
        self.assertTrue(history["rolling_windows_overlap"])
        self.assertEqual(history["collection_timezone"], "PST_fixed_UTC_minus_8")
        self.assertEqual([item["grade"] for item in history["metrics"] if item["name"] == "LCP"], ["good", "unknown"])
        self.assertEqual([item["grade"] for item in history["metrics"] if item["name"] == "INP"], ["needs_improvement", "poor"])
        self.assertEqual([item["grade"] for item in history["metrics"] if item["name"] == "CLS"], ["needs_improvement", "unknown"])
        self.assertTrue(all(window["eligible_days"] == "unknown" for window in history["collection_periods"]))
        self.assertTrue(history["missing_is_not_passing"])
        self.assertEqual(compare_crux_history(history, "LCP")["state"], "unknown_insufficient_eligible_periods")
        self.assertEqual(compare_crux_history(history, "INP")["state"], "regression_candidate")
        self.assertEqual(compare_crux_history(history, "INP")["interpretation"], "overlapping_28_day_field_windows_not_causal_change")
        self.assertEqual(compare_crux_history(history, "TTFB")["state"], "unknown_insufficient_eligible_periods")

    def test_field_p75_threshold_edges_and_absence_are_not_lab_scores(self):
        response = self.crux()
        metrics = response["record"]["metrics"]
        metrics["largest_contentful_paint"]["percentiles"]["p75"] = 4000
        metrics["interaction_to_next_paint"]["percentiles"]["p75"] = 500
        metrics["cumulative_layout_shift"]["percentiles"]["p75"] = "0.25"
        metrics.pop("experimental_time_to_first_byte")
        parsed = parse_crux(project=self.project, requested_url=self.page, requested_grain="page",
                            form_factor="PHONE", payload=response)
        grades = {item["name"]: item["grade"] for item in parsed["metrics"]}
        self.assertEqual(grades, {"LCP": "needs_improvement", "INP": "needs_improvement",
                                  "CLS": "needs_improvement", "TTFB": "unknown"})
        metrics["largest_contentful_paint"]["percentiles"]["p75"] = 4001
        metrics["interaction_to_next_paint"]["percentiles"]["p75"] = 200
        metrics["cumulative_layout_shift"]["percentiles"]["p75"] = "0.1"
        parsed = parse_crux(project=self.project, requested_url=self.page, requested_grain="page",
                            form_factor="PHONE", payload=response)
        grades = {item["name"]: item["grade"] for item in parsed["metrics"]}
        self.assertEqual((grades["LCP"], grades["INP"], grades["CLS"]), ("poor", "good", "good"))

    def test_bad_scope_dimensions_and_nonfinite_values_fail_closed(self):
        response = self.crux()
        response["record"]["key"]["url"] = "https://unrelated.example/page"
        with self.assertRaises(ValidationError):
            parse_crux(project=self.project, requested_url=self.page, requested_grain="page",
                       form_factor="PHONE", payload=response)
        response = self.crux()
        response["record"]["key"]["formFactor"] = "DESKTOP"
        with self.assertRaises(ValidationError):
            parse_crux(project=self.project, requested_url=self.page, requested_grain="page",
                       form_factor="PHONE", payload=response)
        response = self.crux()
        response["record"]["metrics"]["largest_contentful_paint"]["percentiles"]["p75"] = float("nan")
        with self.assertRaises(ValidationError):
            parse_crux(project=self.project, requested_url=self.page, requested_grain="page",
                       form_factor="PHONE", payload=response)
        with self.assertRaises(ValidationError):
            parse_crux(project=self.project, requested_url=self.page + "?token=private", requested_grain="page",
                       form_factor="PHONE", payload=self.crux())
        response = self.crux()
        response["record"]["metrics"]["largest_contentful_paint"]["percentiles"] = "malformed"
        with self.assertRaises(ValidationError):
            parse_crux(project=self.project, requested_url=self.page, requested_grain="page",
                       form_factor="PHONE", payload=response)
        with self.assertRaises(ValidationError):
            parse_crux(project=self.project, requested_url=self.page, requested_grain="origin",
                       form_factor="PHONE", payload=self.crux(scope="origin"))

    def test_provider_page_normalization_requires_matching_evidence(self):
        response = self.crux()
        response["record"]["key"]["url"] = "https://performance.example/page/"
        with self.assertRaises(ValidationError):
            parse_crux(project=self.project, requested_url=self.page, requested_grain="page",
                       form_factor="PHONE", payload=response)
        response["urlNormalizationDetails"] = {
            "originalUrl": self.page, "normalizedUrl": "https://performance.example/page/",
        }
        observed = parse_crux(project=self.project, requested_url=self.page, requested_grain="page",
                              form_factor="PHONE", payload=response)
        self.assertEqual((observed["requested_url"], observed["observed_key"], observed["url_normalization"]),
                         (self.page, "https://performance.example/page/", "provider_normalized"))

    def test_lighthouse_lab_never_reuses_pagespeed_field_data(self):
        payload = {"loadingExperience": {"overall_category": "FAST", "metrics": {"fake": 1}},
                   "lighthouseResult": {
                       "requestedUrl": self.page, "finalUrl": self.page,
                       "fetchTime": timezone.now().isoformat(), "lighthouseVersion": "12.5.0",
                       "configSettings": {"formFactor": "mobile"},
                       "categories": {"performance": {"score": 0.75}, "seo": {"score": None}},
                       "audits": {"largest-contentful-paint": {"numericValue": 3000},
                                  "cumulative-layout-shift": {"numericValue": 0.15}},
                   }}
        observed = parse_pagespeed_lab(project=self.project, requested_url=self.page, strategy="mobile", payload=payload)
        self.assertEqual((observed["kind"], observed["field_data"]), ("lighthouse_lab", "not_used"))
        self.assertEqual(observed["scores"]["performance"], 0.75)
        self.assertIsNone(observed["scores"]["seo"])
        self.assertEqual(observed["audits"]["largest-contentful-paint"], {"value": 3000, "unit": "ms", "state": "observed"})
        self.assertEqual(observed["audits"]["total-blocking-time"]["state"], "unavailable")
        payload["lighthouseResult"]["finalUrl"] = "https://unrelated.example/redirect"
        denied = parse_pagespeed_lab(project=self.project, requested_url=self.page, strategy="mobile", payload=payload)
        self.assertEqual((denied["status"], denied["field_data"]), ("outside_project_scope", "not_used"))
        self.assertNotIn("unrelated.example", str(denied))
        payload["lighthouseResult"]["finalUrl"] = self.page
        payload["lighthouseResult"]["runtimeError"] = {"code": "PROTOCOL_TIMEOUT", "message": "private response"}
        failed = parse_pagespeed_lab(project=self.project, requested_url=self.page, strategy="mobile", payload=payload)
        self.assertEqual((failed["status"], failed["error_category"]), ("runtime_failed", "PROTOCOL_TIMEOUT"))
        self.assertNotIn("private response", str(failed))
