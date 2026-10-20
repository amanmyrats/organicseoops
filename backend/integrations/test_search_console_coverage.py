from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from .search_console_coverage import parse_index_inspection, parse_sitemap_listing


class SearchConsoleCoverageContractTests(SimpleTestCase):
    origins = ["https://owned.example"]

    def test_inspection_keeps_only_indexed_version_categorical_exact_page_evidence(self):
        result = parse_index_inspection(response={"inspectionResult": {"indexStatusResult": {
            "verdict": "PASS", "robotsTxtState": "ALLOWED", "indexingState": "INDEXING_ALLOWED",
            "pageFetchState": "SUCCESSFUL", "lastCrawlTime": "2026-09-20T08:00:00Z",
            "googleCanonical": "https://m.owned.example/foreign?token=PRIVATE_SECRET",
            "userCanonical": "https://owned.example/canonical", "referringUrls": ["https://other.example/private"],
            "coverageState": "Provider text PRIVATE_SECRET", "sitemap": ["https://m.owned.example/sitemap.xml"],
        }}}, inspection_url="https://owned.example/page", approved_origins=self.origins)
        self.assertEqual((result["inspection_url"], result["indexed_state"], result["last_crawl_at"]),
                         ("https://owned.example/page", "reported_indexed", "2026-09-20T08:00:00+00:00"))
        self.assertEqual(result["method"], "google_indexed_version_only")
        self.assertIsNone(result["google_canonical"])
        self.assertEqual(result["declared_canonical"], "https://owned.example/canonical")
        self.assertNotIn("PRIVATE_SECRET", str(result))
        for url in ("https://m.owned.example/page", "http://owned.example/page",
                    "https://owned.example/?code=PRIVATE_SECRET", "https://owned.example/page#private"):
            with self.subTest(url=url), self.assertRaises(ValidationError):
                parse_index_inspection(response={"inspectionResult": {"indexStatusResult": {"verdict": "PASS"}}},
                                       inspection_url=url, approved_origins=self.origins)
        with self.assertRaises(ValidationError):
            parse_index_inspection(response={"inspectionResult": {"indexStatusResult": {"verdict": "unknown"}}},
                                   inspection_url="https://owned.example/page", approved_origins=self.origins)

    def test_sitemap_listing_drops_foreign_urls_and_does_not_expose_domain_counts(self):
        result = parse_sitemap_listing(response={"sitemap": [
            {"path": "https://owned.example/sitemap.xml", "contents": [{"indexed": "9000"}]},
            {"path": "https://m.owned.example/secret.xml", "contents": [{"indexed": "1000"}]},
            {"path": "https://owned.example/?code=PRIVATE_SECRET"},
        ]}, approved_origins=self.origins)
        self.assertEqual(result["sitemaps"], [{"url": "https://owned.example/sitemap.xml"}])
        self.assertIsNone(result["indexed_url_counts"])
        self.assertIsNone(result["provider_total"])
        self.assertNotIn("PRIVATE_SECRET", str(result))
        self.assertNotIn("9000", str(result))
        with self.assertRaises(ValidationError):
            parse_sitemap_listing(response={"sitemap": [{}] * 101}, approved_origins=self.origins)
