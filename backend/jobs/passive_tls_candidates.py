"""Literal original TLS review candidates, not risk or current-source authority."""
from copy import deepcopy

from .passive_tls_evidence import validate_tls_evidence


METHOD = "passive-tls-candidates-v1"
INTERPRETATION = "dated_reported_dates_and_negotiated_version_candidates_not_supported_configuration_revocation_browser_behavior_or_exploitability"


def tls_review_candidates(collection, *, binding):
    validate_tls_evidence(collection, binding=binding)
    dates = collection["evidence"]["certificate_dates"]
    version = collection["evidence"]["negotiated_tls"]["version"]
    candidates = []
    if dates["state"] == "observed" and dates["position"] != "within_reported_window":
        candidates.append({"detector": "reported_certificate_date_outside_window_candidate",
            "evidence": {key: dates[key] for key in ("not_before", "not_after", "position", "remaining_microseconds")}})
    if version in {"TLSv1", "TLSv1.1"}:
        candidates.append({"detector": "negotiated_tlsv1_or_tlsv1_1_candidate", "evidence": {"version": version}})
    return {"method_version": METHOD, "binding": deepcopy(binding), "collection": deepcopy(collection),
        "availability": {"certificate_dates": dates["state"], "negotiated_version": "unavailable" if version is None else "observed"},
        "coverage": "one_original_reported_certificate_date_interval_and_actual_negotiated_version_only",
        "candidates": candidates, "interpretation": INTERPRETATION}
