from types import SimpleNamespace

from django.test import SimpleTestCase

from .technical_outcome import compare_crawl_observations


class TechnicalOutcomeCalculationTests(SimpleTestCase):
    def test_missing_failed_and_changed_pages_do_not_claim_technical_success(self):
        def page(**changes):
            values = dict(pk=1, observed_at=SimpleNamespace(isoformat=lambda: "2026-09-29T00:00:00Z"),
                requested_url="https://source.example.invalid/page", final_url="https://source.example.invalid/page",
                status_code=200, canonical_url="https://source.example.invalid/page", title="Before title",
                robots_directives=[], content_hash="a" * 64, error_category="")
            return SimpleNamespace(**{**values, **changes})

        missing = compare_crawl_observations(None, page())
        self.assertIn("not_clean_or_zero", missing["state"])
        self.assertIsNone(missing["changes"])
        failed = compare_crawl_observations(page(), page(status_code=None, error_category="timeout"))
        self.assertIn("not_verified", failed["state"])
        changed = compare_crawl_observations(page(), page(pk=2, title="After title", content_hash="b" * 64))
        self.assertEqual(changed["changes"]["title"], {"previous": "Before title", "current": "After title"})
        self.assertNotIn("status_code", changed["changes"])
        self.assertIn("not_fix_proof", changed["state"])
