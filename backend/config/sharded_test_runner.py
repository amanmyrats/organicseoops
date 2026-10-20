import hashlib
import unittest

from django.test.runner import DiscoverRunner
from django.test.utils import iter_test_cases


FULL_LABELS = ("accounts", "config", "tenancy", "jobs", "providers", "integrations")


class ShardedDiscoverRunner(DiscoverRunner):
    @classmethod
    def add_arguments(cls, parser):
        super().add_arguments(parser)
        parser.add_argument("--shard", type=int, choices=(0, 1), required=True)

    def __init__(self, *args, shard=None, **kwargs):
        super().__init__(*args, **kwargs)
        if type(shard) is not int or shard not in (0, 1):
            raise ValueError("Select backend check group 0 or 1")
        if (self.parallel or self.pattern not in (None, "test*.py") or self.tags
                or self.exclude_tags or self.test_name_patterns):
            raise ValueError("Grouped checks require the complete serial suite")
        self.shard = shard

    def build_suite(self, test_labels=None, **kwargs):
        if tuple(test_labels or ()) != FULL_LABELS:
            raise ValueError("Grouped checks require all six backend apps")
        cases = list(iter_test_cases(super().build_suite(test_labels, **kwargs)))
        if any(isinstance(case, unittest.loader._FailedTest) for case in cases):
            raise RuntimeError("Full backend test discovery failed")
        selected = [case for case in cases if hashlib.sha256(
            type(case).__module__.encode()).digest()[0] % 2 == self.shard]
        if not selected:
            raise ValueError("Backend check group is empty")
        catalog = hashlib.sha256("\n".join(case.id() for case in cases).encode()).hexdigest()
        print(f"Backend group {self.shard}/2: {len(selected)} of {len(cases)} tests; full catalog {catalog}")
        return unittest.TestSuite(selected)
