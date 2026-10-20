"""Fail closed on public provider claims without dated, secret-free release evidence."""
import json
from datetime import date
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
REQUIRED_EVIDENCE = frozenset({"access", "capabilities", "quota", "cost", "terms", "retention", "representative_job"})
AI_VISIBILITY_EVIDENCE = frozenset({"methodology", "terms_privacy", "budget_retention", "evidence_denominators", "hosted_journey", "accessibility"})


def validate(readiness, approvals):
    if readiness.get("version") != 1 or type(readiness.get("providers")) is not list:
        raise ValueError("Unknown provider readiness format")
    providers = {}
    for row in readiness["providers"]:
        if (type(row) is not dict or not re.fullmatch(r"[a-z][a-z0-9_]{2,39}", str(row.get("id", "")))
            or row["id"] in providers or row.get("owner_role") != "platform_operator"
            or row.get("local_contract") not in {"fixture_checked", "blocked_source_contract"}
            or row.get("live_status") not in {"unverified", "verified"}
            or type(row.get("public_claimable")) is not bool or not row.get("scope_note")
            or type(row.get("evidence")) is not dict):
            raise ValueError("Invalid provider readiness record")
        if row["live_status"] == "verified" or row["public_claimable"]:
            if row["local_contract"] != "fixture_checked":
                raise ValueError("Fixture/source-blocked provider cannot be publicly claimed")
            if set(row["evidence"]) != REQUIRED_EVIDENCE:
                raise ValueError("Missing release capability, cost, terms or job evidence")
            for value in row["evidence"].values():
                if (type(value) is not dict or not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", str(value.get("checked_at", "")))
                    or not re.fullmatch(r"P3A12-[A-Z0-9_-]{3,36}", str(value.get("reference", "")))):
                    raise ValueError("Release evidence must use dated, non-secret references")
                try:
                    date.fromisoformat(value["checked_at"])
                except ValueError as error:
                    raise ValueError("Invalid release evidence date") from error
            if row["public_claimable"] and row["live_status"] != "verified":
                raise ValueError("Unverified provider cannot be publicly claimed")
        providers[row["id"]] = row

    visibility = readiness.get("ai_visibility")
    if (type(visibility) is not dict or visibility.get("surface") != "openai_responses_text"
        or visibility.get("methodology") != "api-text-visibility-v1"
        or visibility.get("local_contract") != "fixture_checked"
        or visibility.get("live_status") not in {"unverified", "verified"}
        or type(visibility.get("public_claimable")) is not bool or type(visibility.get("evidence")) is not dict):
        raise ValueError("Unknown AI visibility surface/methodology readiness")
    if visibility["live_status"] == "verified" or visibility["public_claimable"]:
        if (not providers.get("ai_text", {}).get("public_claimable")
            or visibility["live_status"] != "verified" or set(visibility["evidence"]) != AI_VISIBILITY_EVIDENCE):
            raise ValueError("AI visibility requires actual provider and complete surface release evidence")
        for value in visibility["evidence"].values():
            if (type(value) is not dict or not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", str(value.get("checked_at", "")))
                or not re.fullmatch(r"P11A05-[A-Z0-9_-]{3,36}", str(value.get("reference", "")))):
                raise ValueError("AI visibility evidence requires dated non-secret references")
            try:
                date.fromisoformat(value["checked_at"])
            except ValueError as error:
                raise ValueError("Invalid AI visibility evidence date") from error

    if type(approvals.get("routes")) is not dict:
        raise ValueError("Missing public route approval manifest")
    for path, approval in approvals["routes"].items():
        if approval.get("state") != "approved":
            continue
        claims = approval.get("claimed_providers")
        if (type(claims) is not list or len(claims) != len(set(claims))
            or any(provider not in providers or not providers[provider]["public_claimable"] for provider in claims)):
            raise ValueError(f"Unverified provider claim on reviewed route /{path}")
        surfaces = approval.get("claimed_ai_visibility_surfaces", [])
        if (type(surfaces) is not list or any(type(surface) is not str for surface in surfaces)
            or len(surfaces) != len(set(surfaces)) or any(surface != "openai_responses_text" for surface in surfaces)):
            raise ValueError(f"Unsupported AI visibility surface claim on reviewed route /{path}")
        if surfaces and (not visibility["public_claimable"] or "ai_text" not in claims):
            raise ValueError(f"Unverified AI visibility claim on reviewed route /{path}")


if __name__ == "__main__":
    validate(json.loads((ROOT / "docs/PROVIDER_READINESS.json").read_text()),
             json.loads((ROOT / "frontend/publication-approvals.json").read_text()))
    print("PASS: no unverified provider or unsupported/unverified AI visibility surface is declared claimable")
