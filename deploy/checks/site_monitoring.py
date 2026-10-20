"""Validate secret-free monitoring references offline; never certify a release."""
import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]
MAX_BYTES = 32 * 1024
COVERAGE = (
    "public_indexability", "sitemap_submission", "observed_indexing", "links",
    "availability", "search", "referrals", "lab_performance", "field_performance",
    "mobile", "accessibility", "approved_claims", "consent", "app_handoff",
    "email_handoff", "payment_handoff", "cleanup_scheduler", "cleanup_queue",
    "cleanup_deadline", "content_rollback",
)
RELATED_RECORDS = {
    "publication": "frontend/publication-approvals.json",
    "providers": "docs/PROVIDER_READINESS.json",
    "cleanup": "docs/PUBLIC_CONTENT_WORKFLOW.md",
}
HUMAN_REVIEW = {"accessibility", "approved_claims", "consent"}


def validate_evidence(row):
    if (type(row) is not dict
        or set(row) != {"checked_at", "environment", "kind", "reference"}
        or type(row["checked_at"]) is not str
        or not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", row["checked_at"])
        or type(row["environment"]) is not str
        or row["environment"] not in {"local", "staging", "production"}
        or type(row["kind"]) is not str
        or row["kind"] not in {"local_fixture", "human_review", "hosted_observation"}
        or type(row["reference"]) is not str
        or not re.fullmatch(r"P13MON-[A-Z0-9_-]{3,48}", row["reference"])):
        raise ValueError("Invalid dated environment/kind/reference evidence")
    if date.fromisoformat(row["checked_at"]) > datetime.now(timezone.utc).date():
        raise ValueError("Evidence date cannot be in the future")
    if ((row["kind"] == "local_fixture" and row["environment"] != "local")
        or (row["kind"] == "hosted_observation" and row["environment"] == "local")):
        raise ValueError("Evidence kind does not match its environment")


def validate(record):
    if (type(record) is not dict
        or set(record) != {"version", "origin", "owner", "cadence_days", "baseline", "related_records", "checks"}
        or type(record["version"]) is not int or record["version"] != 1
        or record["related_records"] != RELATED_RECORDS):
        raise ValueError("Unknown monitoring record format or authority references")
    if record["origin"] is not None:
        origin = record["origin"]
        if type(origin) is not str or len(origin) > 253:
            raise ValueError("Invalid HTTPS origin")
        parsed = urlsplit(origin)
        if (parsed.scheme != "https" or parsed.path or parsed.query or parsed.fragment
            or origin != f"https://{parsed.hostname}"
            or parsed.username is not None or parsed.password is not None
            or not parsed.hostname or parsed.netloc != parsed.hostname
            or not re.fullmatch(r"[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?", parsed.hostname)
            or any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
                   for label in parsed.hostname.split("."))):
            raise ValueError("Invalid HTTPS origin")
    if (record["owner"] is not None and (type(record["owner"]) is not str
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,79}", record["owner"]))):
        raise ValueError("Invalid non-secret owner reference")
    if (record["cadence_days"] is not None and (type(record["cadence_days"]) is not int
        or not 1 <= record["cadence_days"] <= 365)):
        raise ValueError("Invalid review cadence")
    if record["baseline"] is not None:
        validate_evidence(record["baseline"])
    if type(record["checks"]) is not list or len(record["checks"]) != len(COVERAGE):
        raise ValueError("Missing fixed monitoring coverage")
    seen = set()
    for row in record["checks"]:
        if (type(row) is not dict or set(row) != {"id", "evidence"}
            or type(row["id"]) is not str or row["id"] not in COVERAGE or row["id"] in seen
            or type(row["evidence"]) is not list or len(row["evidence"]) > 4):
            raise ValueError("Invalid, duplicate or oversized monitoring coverage")
        seen.add(row["id"])
        references = set()
        for evidence in row["evidence"]:
            validate_evidence(evidence)
            if evidence["reference"] in references:
                raise ValueError("Duplicate evidence reference within a check")
            references.add(evidence["reference"])


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError("Non-finite JSON number")


def load(path):
    with Path(path).open("rb") as source:
        raw = source.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Monitoring input exceeds 32 KiB")
    record = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=reject_constant)
    validate(record)
    return record


def report(record):
    validate(record)
    gaps = [f"{key}: unconfigured/unknown" for key in ("origin", "owner", "cadence_days", "baseline")
            if record[key] is None]
    if record["baseline"] is not None and (record["baseline"]["environment"] != "production"
        or record["baseline"]["kind"] != "hosted_observation"):
        gaps.append("baseline: production hosted reference absent")
    for row in record["checks"]:
        kinds = {e["kind"] for e in row["evidence"] if e["environment"] == "production"}
        required = {"hosted_observation"} | ({"human_review"} if row["id"] in HUMAN_REVIEW else set())
        missing = sorted(required - kinds)
        if missing:
            gaps.append(f"{row['id']}: production {' + '.join(missing)} reference absent")
    return ["RELEASE UNVERIFIED: offline shape/coverage only; references require independent review.",
            f"Coverage gaps: {len(gaps)}", *gaps,
            "Original publication/provider/manual/hosted/cleanup/rollback gates remain authoritative."]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=ROOT / "docs/SITE_MONITORING.json")
    args = parser.parse_args(argv)
    try:
        lines = report(load(args.path))
    except (OSError, ValueError, UnicodeError, RecursionError):
        parser.exit(2, "INVALID: monitoring input does not match the bounded offline contract.\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
