from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from .outcome_comparison import compare_page_rows


class PageOutcomeCalculationTests(SimpleTestCase):
    def test_zero_missing_metrics_and_ctr_units_do_not_invent_improvement(self):
        row = lambda **values: SimpleNamespace(**values)
        before = row(clicks=0, impressions=200, ctr=Decimal("0"), position=Decimal("12"))
        after = row(clicks=4, impressions=250, ctr=Decimal("0.016"), position=Decimal("9"))
        report = compare_page_rows(before, after)
        self.assertEqual(report["clicks"]["absolute_change"], "4")
        self.assertIsNone(report["clicks"]["relative_change"])
        self.assertEqual(report["clicks"]["state"], "zero_baseline")
        self.assertEqual(report["impressions"]["relative_change"], "0.2500")
        self.assertEqual(report["ctr"]["absolute_change"], "0.016")
        self.assertEqual(report["average_position"]["absolute_change"], "-3")
        self.assertIn("not_causal", report["state"])
        missing = compare_page_rows(None, after)
        self.assertIsNone(missing["clicks"]["absolute_change"])
        self.assertIn("not_zero", missing["state"])
        empty = row(clicks=0, impressions=0, ctr=Decimal("0"), position=None)
        no_ctr = compare_page_rows(empty, after)
        self.assertEqual(no_ctr["ctr"]["state"], "unavailable")
        self.assertEqual(no_ctr["average_position"]["state"], "unavailable")
