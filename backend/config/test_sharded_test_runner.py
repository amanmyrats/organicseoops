from collections import Counter
import io
import unittest
from unittest.mock import patch

from django.test import SimpleTestCase
from django.test.runner import DiscoverRunner
from django.test.utils import iter_test_cases

from .sharded_test_runner import FULL_LABELS, ShardedDiscoverRunner


class ShardedRunnerTests(SimpleTestCase):
    def cases(self):
        return [type("Fixture", (unittest.TestCase,), {
            "__module__": f"fixture.module{index}", "runTest": lambda self: None})()
            for index in range(8)]

    def group(self, cases, shard):
        with patch.object(DiscoverRunner, "build_suite", return_value=unittest.TestSuite(cases)), \
                patch("sys.stdout", new_callable=io.StringIO):
            return list(iter_test_cases(ShardedDiscoverRunner(shard=shard).build_suite(FULL_LABELS)))

    def test_groups_preserve_order_modules_duplicates_and_complete_discovery(self):
        cases = self.cases()
        cases.append(cases[0])
        groups = [self.group(cases, shard) for shard in (0, 1)]
        ids = [Counter(case.id() for case in group) for group in groups]
        self.assertFalse(ids[0].keys() & ids[1].keys())
        self.assertEqual(ids[0] + ids[1], Counter(case.id() for case in cases))
        for group in groups:
            modules = {type(case).__module__ for case in group}
            self.assertEqual(group, [case for case in cases if type(case).__module__ in modules])
        self.assertEqual(self.group(cases, 0), groups[0])

    def test_invalid_group_partial_scope_and_suite_filters_deny(self):
        self.assertEqual(ShardedDiscoverRunner(shard=0, pattern="test*.py").pattern, "test*.py")
        for shard in (None, True, -1, 2, "0"):
            with self.subTest(shard=shard), self.assertRaises(ValueError):
                ShardedDiscoverRunner(shard=shard)
        for options in ({"parallel": 2}, {"pattern": "test_subset.py"}, {"tags": ["fast"]}, {"exclude_tags": ["slow"]},
                        {"test_name_patterns": ["*healthy*"]}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                ShardedDiscoverRunner(shard=0, **options)
        with patch.object(DiscoverRunner, "build_suite") as discover, self.assertRaises(ValueError):
            ShardedDiscoverRunner(shard=0).build_suite(("jobs",))
        discover.assert_not_called()

    def test_empty_group_and_import_failure_deny_before_execution(self):
        with self.assertRaises(ValueError):
            self.group([], 0)
        loader = unittest.TestLoader()
        failed = list(iter_test_cases(loader.loadTestsFromName("nonexistent_backend_fixture_module")))
        for shard in (0, 1):
            with self.subTest(shard=shard), self.assertRaises(RuntimeError):
                self.group(self.cases() + failed, shard)

    def test_both_groups_execute_every_selected_case(self):
        for shard in (0, 1):
            group = self.group(self.cases(), shard)
            result = unittest.TestResult()
            unittest.TestSuite(group).run(result)
            self.assertTrue(result.wasSuccessful())
            self.assertEqual(result.testsRun, len(group))
