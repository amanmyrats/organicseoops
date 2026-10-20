from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("provider_readiness", ROOT / "deploy/checks/provider_readiness.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ProviderReadinessTests(unittest.TestCase):
    def test_fixture_contracts_do_not_authorize_public_claims(self):
        readiness = json.loads((ROOT / "docs/PROVIDER_READINESS.json").read_text())
        approvals = json.loads((ROOT / "frontend/publication-approvals.json").read_text())
        MODULE.validate(readiness, approvals)
        self.assertTrue(all(row["live_status"] == "unverified" and not row["public_claimable"]
                            and not row["evidence"] for row in readiness["providers"]))
        claim = deepcopy(approvals)
        claim["routes"][""] = {"state": "approved", "claimed_providers": ["google_search_console"]}
        with self.assertRaisesRegex(ValueError, "Unverified provider claim"):
            MODULE.validate(readiness, claim)
        inconsistent = deepcopy(readiness)
        inconsistent["providers"][0]["public_claimable"] = True
        with self.assertRaisesRegex(ValueError, "Missing release"):
            MODULE.validate(inconsistent, approvals)
        inconsistent = deepcopy(readiness)
        inconsistent["providers"][1]["live_status"] = "verified"
        with self.assertRaisesRegex(ValueError, "source-blocked"):
            MODULE.validate(inconsistent, approvals)

    def test_only_dated_complete_synthetic_fixture_evidence_passes_shape_check(self):
        readiness = json.loads((ROOT / "docs/PROVIDER_READINESS.json").read_text())
        approvals = json.loads((ROOT / "frontend/publication-approvals.json").read_text())
        fake = deepcopy(readiness)
        row = fake["providers"][0]
        row["live_status"] = "verified"
        row["public_claimable"] = True
        row["evidence"] = {key: {"checked_at": "2026-09-29", "reference": "P3A12-TEST-ONLY"}
                           for key in MODULE.REQUIRED_EVIDENCE}
        claim = deepcopy(approvals)
        claim["routes"][""] = {"state": "approved", "claimed_providers": ["google_search_console"]}
        MODULE.validate(fake, claim)  # Shape only; no provider was contacted.
        row["evidence"]["cost"]["checked_at"] = "2026-99-99"
        with self.assertRaisesRegex(ValueError, "Invalid release evidence date"):
            MODULE.validate(fake, claim)

    def test_ai_surface_claims_need_separate_evidence_and_cannot_expand_supported_observations(self):
        readiness = json.loads((ROOT / "docs/PROVIDER_READINESS.json").read_text())
        approvals = {"routes": {"": {"state": "approved", "claimed_providers": [],
                                   "claimed_ai_visibility_surfaces": ["openai_responses_text"]}}}
        self.assertFalse(readiness["ai_visibility"]["public_claimable"])
        with self.assertRaisesRegex(ValueError, "Unverified AI visibility"):
            MODULE.validate(readiness, approvals)
        for unsupported in ("consumer_chatgpt", "global_chat_visibility", "citations", "ai_referrals", "automatic_schedules", "geolocation", "gptbot_training_membership"):
            claim = deepcopy(approvals)
            claim["routes"][""]["claimed_ai_visibility_surfaces"] = [unsupported]
            with self.assertRaisesRegex(ValueError, "Unsupported AI visibility"):
                MODULE.validate(readiness, claim)
        fake = deepcopy(readiness)
        provider = next(row for row in fake["providers"] if row["id"] == "ai_text")
        provider.update(live_status="verified", public_claimable=True,
            evidence={key: {"checked_at": "2026-10-01", "reference": "P3A12-TEST-ONLY"} for key in MODULE.REQUIRED_EVIDENCE})
        claim = deepcopy(approvals); claim["routes"][""]["claimed_providers"] = ["ai_text"]
        with self.assertRaisesRegex(ValueError, "Unverified AI visibility"):
            MODULE.validate(fake, claim)  # General AI text readiness cannot license consumer/visibility claims.
        fake["ai_visibility"].update(live_status="verified", public_claimable=True,
            evidence={key: {"checked_at": "2026-10-01", "reference": "P11A05-TEST-ONLY"} for key in MODULE.AI_VISIBILITY_EVIDENCE})
        MODULE.validate(fake, claim)  # Shape-only fixture, never saved as real approval.
        del fake["ai_visibility"]["evidence"]["accessibility"]
        with self.assertRaisesRegex(ValueError, "complete surface release evidence"):
            MODULE.validate(fake, claim)


if __name__ == "__main__":
    unittest.main()
