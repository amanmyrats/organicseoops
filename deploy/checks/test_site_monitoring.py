from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("site_monitoring", ROOT / "deploy/checks/site_monitoring.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SiteMonitoringTests(unittest.TestCase):
    def setUp(self):
        self.template = MODULE.load(ROOT / "docs/SITE_MONITORING.json")

    def evidence(self, kind="hosted_observation", environment="production", suffix="HOSTED"):
        return {"checked_at": "2026-10-09", "environment": environment,
                "kind": kind, "reference": "P13MON-TEST-ONLY-" + suffix}

    def test_unconfigured_template_is_valid_but_unknown_and_release_unverified(self):
        original = deepcopy(self.template)
        lines = MODULE.report(self.template)
        self.assertIn("RELEASE UNVERIFIED", lines[0])
        self.assertEqual(lines[1], "Coverage gaps: 24")
        self.assertTrue(all(self.template[key] is None for key in ("origin", "owner", "cadence_days", "baseline")))
        self.assertEqual(self.template, original)
        ids = {row["id"] for row in self.template["checks"]}
        for group in ({"sitemap_submission", "observed_indexing"}, {"lab_performance", "field_performance"},
                      {"search", "referrals"}, {"cleanup_scheduler", "cleanup_queue", "cleanup_deadline"}):
            self.assertTrue(group <= ids)

    def test_complete_synthetic_references_never_certify_release_or_replace_authority(self):
        record = deepcopy(self.template)
        record.update(origin="https://product.example", owner="Synthetic owner", cadence_days=7,
                      baseline=self.evidence())
        for row in record["checks"]:
            row["evidence"] = [self.evidence()]
            if row["id"] in MODULE.HUMAN_REVIEW:
                row["evidence"].append(self.evidence("human_review", suffix="HUMAN"))
        lines = MODULE.report(record)
        self.assertEqual(lines[1], "Coverage gaps: 0")
        self.assertIn("RELEASE UNVERIFIED", lines[0])
        self.assertIn("remain authoritative", lines[-1])
        self.assertTrue(all(row["evidence"] == [] for row in self.template["checks"]))

    def test_fixture_staging_and_human_evidence_cannot_fill_hosted_production_gaps(self):
        for kind, environment in (("local_fixture", "local"), ("hosted_observation", "staging"),
                                  ("human_review", "production")):
            with self.subTest(kind=kind, environment=environment):
                record = deepcopy(self.template)
                record["baseline"] = self.evidence(kind, environment)
                for row in record["checks"]:
                    row["evidence"] = [self.evidence(kind, environment)]
                lines = MODULE.report(record)
                self.assertIn("baseline: production hosted reference absent", lines)
                self.assertTrue(any("field_performance: production hosted_observation reference absent" == line
                                    for line in lines))
                self.assertNotIn("Coverage gaps: 0", lines)

    def test_closed_typed_configuration_and_coverage_reject_unknown_zero_and_duplicates(self):
        mutations = [
            lambda r: r.update(version=True), lambda r: r.update(version=2),
            lambda r: r.update(api_key="synthetic-secret-forbidden"),
            lambda r: r.pop("baseline"), lambda r: r.update(baseline=0), lambda r: r.update(baseline=False),
            lambda r: r.update(baseline={"state": "unknown", "value": 0}),
            lambda r: r.update(owner=""), lambda r: r.update(owner="x" * 81), lambda r: r.update(owner=[]),
            lambda r: r.update(cadence_days=True), lambda r: r.update(cadence_days=0),
            lambda r: r.update(cadence_days=366), lambda r: r.update(cadence_days="7"),
            lambda r: r["related_records"].update(providers="other.json"),
            lambda r: r["checks"].pop(), lambda r: r["checks"].append(deepcopy(r["checks"][0])),
            lambda r: r["checks"][1].update(id=r["checks"][0]["id"]),
            lambda r: r["checks"][0].update(id="unselected"), lambda r: r["checks"][0].update(id=[]),
            lambda r: r["checks"][0].update(evidence=0),
            lambda r: r["checks"][0].update(evidence=[self.evidence()] * 5),
            lambda r: r["checks"][0].update(evidence=[self.evidence()] * 2),
            lambda r: r["checks"][0].update(value=0),
        ]
        for index, mutation in enumerate(mutations):
            with self.subTest(index=index):
                record = deepcopy(self.template)
                mutation(record)
                with self.assertRaises(ValueError):
                    MODULE.validate(record)
        for record in ([], None, True):
            with self.subTest(record=record), self.assertRaises(ValueError):
                MODULE.validate(record)

    def test_invalid_origin_and_evidence_fields_fail_closed(self):
        for origin in ("http://product.example", "https://user:pass@product.example", "https://product.example/path",
                       "https://product.example?key=secret", "https://product.example#fragment", "https://bad..example",
                       "https://-bad.example", "https://product.example:443", "https://PRODUCT.example",
                       "HTTPS://product.example", "https://product.example?", "https://product.example#", [], "x" * 254):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                record = deepcopy(self.template); record["origin"] = origin
                MODULE.validate(record)
        invalid = [None, 0, {}, self.evidence("local_fixture", "production"),
                   self.evidence("hosted_observation", "local")]
        for key, value in (("checked_at", "2026-02-30"), ("checked_at", "2099-01-01"),
                           ("checked_at", "20261009"), ("checked_at", 0), ("environment", "unknown"),
                           ("environment", []), ("kind", "passed"), ("kind", {}),
                           ("reference", "https://private.example/token"), ("reference", "P13MON-" + "X" * 49),
                           ("reference", 0)):
            row = self.evidence(); row[key] = value; invalid.append(row)
        extra = self.evidence(); extra["token"] = "forbidden"; invalid.append(extra)
        for index, evidence in enumerate(invalid):
            with self.subTest(index=index), self.assertRaises(ValueError):
                record = deepcopy(self.template); record["checks"][0]["evidence"] = [evidence]
                MODULE.validate(record)

    def test_bounded_utf8_json_reader_rejects_duplicate_fields_nonfinite_and_malformed_input(self):
        raw = json.dumps(self.template).encode()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "monitoring.json"
            path.write_bytes(raw)
            self.assertEqual(MODULE.load(path), self.template)
            invalid = [b"{}" + b" " * MODULE.MAX_BYTES, b"\xff", b"{", b"[]", b"NaN", b"Infinity",
                       raw.replace(b'"version": 1', b'"version": 1, "version": 1'),
                       raw.replace(b'"evidence": []', b'"evidence": [], "evidence": []', 1)]
            for index, data in enumerate(invalid):
                with self.subTest(index=index), self.assertRaises(ValueError):
                    path.write_bytes(data)
                    MODULE.load(path)

    def test_cli_reports_gaps_and_rejects_input_without_echoing_untrusted_values(self):
        result = subprocess.run([sys.executable, str(ROOT / "deploy/checks/site_monitoring.py")],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RELEASE UNVERIFIED", result.stdout)
        self.assertIn("cleanup_deadline", result.stdout)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"; path.write_text('{"private":"DO-NOT-ECHO"}')
            result = subprocess.run([sys.executable, str(ROOT / "deploy/checks/site_monitoring.py"), str(path)],
                                    cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("INVALID", result.stderr)
            self.assertNotIn("DO-NOT-ECHO", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
