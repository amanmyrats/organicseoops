from datetime import date

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from .ga4_reports import parse_ga4_landing_report


class GA4LandingReportTests(SimpleTestCase):
    def report(self, rows=None):
        rows = rows if rows is not None else [("site.example", "/landing", "4", "1.5", "-2.50")]
        return {
            "kind": "analyticsData#runReport",
            "dimensionHeaders": [{"name": "hostName"}, {"name": "landingPagePlusQueryString"}],
            "metricHeaders": [{"name": "sessions"}, {"name": "keyEvents"}, {"name": "totalRevenue"}],
            "rows": [{"dimensionValues": [{"value": host}, {"value": path}],
                      "metricValues": [{"value": sessions}, {"value": events}, {"value": revenue}]}
                     for host, path, sessions, events, revenue in rows],
            "rowCount": len(rows), "metadata": {"currencyCode": "USD", "timeZone": "Europe/Istanbul"},
        }

    def parse(self, response, **kwargs):
        return parse_ga4_landing_report(response=response, property_id="12345", day=date(2026, 9, 24),
                                        approved_origins=["https://site.example"], **kwargs)

    def test_separates_host_path_currency_and_instrumentation_from_search_metrics(self):
        output = self.parse(self.report())
        self.assertEqual(output["rows"], [{"hostname": "site.example", "path": "/landing",
                                          "sessions": 4, "key_events": "1.5", "total_revenue": "-2.50"}])
        self.assertEqual((output["property_id"], output["timezone"], output["currency"]),
                         ("12345", "Europe/Istanbul", "USD"))
        self.assertEqual(output["coverage"]["scope"], "approved_hostname_only_scheme_unknown")
        self.assertEqual(output["coverage"]["full_activity_coverage"], "unknown")
        self.assertFalse(output["coverage"]["instrumentation_verified"])
        self.assertEqual(output["coverage"]["search_clicks"], "not_reported")

    def test_omits_foreign_and_parameterized_rows_without_leaking_them(self):
        output = self.parse(self.report([
            ("site.example", "/safe", "1", "0", "0"),
            ("foreign.example", "/private", "2", "1", "4"),
            ("site.example", "/landing?key=secret", "3", "1", "5"),
            ("site.example", "/landing%3Fkey=secret", "3", "1", "5"),
        ]))
        self.assertEqual([row["path"] for row in output["rows"]], ["/safe"])
        self.assertEqual(output["coverage"]["omitted_foreign_or_parameterized_rows"], 3)
        self.assertFalse(output["coverage"]["returned_rows_exhausted_without_reported_gaps"])
        self.assertNotIn("secret", str(output))
        self.assertNotIn("foreign.example", str(output))

    def test_threshold_sampling_other_and_pagination_cannot_claim_complete_rows(self):
        response = self.report()
        response["rowCount"] = 101
        response["metadata"].update(subjectToThresholding=True, dataLossFromOtherRow=True,
                                    samplingMetadatas=[{"samplesReadCount": "10", "samplingSpaceSize": "100"}])
        output = self.parse(response)
        self.assertEqual((output["coverage"]["sampled"], output["coverage"]["thresholded"],
                          output["coverage"]["other_row_loss"]), (True, True, True))
        self.assertFalse(output["coverage"]["returned_rows_exhausted_without_reported_gaps"])
        with self.assertRaises(ValidationError):
            self.parse(self.report(), offset=100)

    def test_headers_metrics_duplicates_and_scope_fail_closed(self):
        cases = []
        duplicate = self.report([("site.example", "/same", "1", "0", "0")] * 2)
        cases.append(duplicate)
        headers = self.report()
        headers["metricHeaders"][1]["name"] = "clicks"
        cases.append(headers)
        negative = self.report([("site.example", "/landing", "3", "-1", "1")])
        cases.append(negative)
        nonfinite = self.report([("site.example", "/landing", "NaN", "1", "1")])
        cases.append(nonfinite)
        metadata = self.report()
        metadata["metadata"].pop("timeZone")
        cases.append(metadata)
        for response in cases:
            with self.subTest(response=response), self.assertRaises(ValidationError):
                self.parse(response)
        with self.assertRaises(ValidationError):
            parse_ga4_landing_report(response=self.report(), property_id="properties/12345",
                day=date(2026, 9, 24), approved_origins=["https://site.example"])
        with self.assertRaises(ValidationError):
            parse_ga4_landing_report(response=self.report(), property_id="12345",
                day=date(2026, 9, 24), approved_origins=["https://site.example", "http://site.example"])

    def test_organic_session_channel_is_independently_labeled_and_unexpected_channels_omitted(self):
        response = self.report()
        response["dimensionHeaders"].append({"name": "sessionDefaultChannelGroup"})
        response["rows"][0]["dimensionValues"].append({"value": "Organic Search"})
        response["rows"].append({"dimensionValues": [{"value": "site.example"}, {"value": "/other"},
                                                       {"value": "Direct"}],
                                 "metricValues": [{"value": "99"}, {"value": "7"}, {"value": "80"}]})
        response["rowCount"] = 2
        output = self.parse(response, report_kind="organic_search")
        self.assertEqual(output["report_kind"], "organic_search")
        self.assertEqual(output["rows"][0]["session_default_channel_group"], "Organic Search")
        self.assertEqual(len(output["rows"]), 1)
        self.assertEqual(output["coverage"]["omitted_unexpected_channel_rows"], 1)
        self.assertIn("not_gsc_clicks", output["coverage"]["acquisition_scope"])
        self.assertFalse(output["coverage"]["returned_rows_exhausted_without_reported_gaps"])
        with self.assertRaises(ValidationError):
            self.parse(self.report(), report_kind="organic_search")
