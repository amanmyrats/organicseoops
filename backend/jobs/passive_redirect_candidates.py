"""Literal original Location review candidates, not followed-chain or risk authority."""
from copy import deepcopy

from .passive_redirect_evidence import validate_redirect_evidence


METHOD = "passive-redirect-candidates-v1"
INTERPRETATION = "dated_http_scheme_location_reference_not_followed_redirect_downgrade_https_upgrade_browser_behavior_severity_or_target_authority"


def redirect_review_candidates(collection, *, binding):
    validate_redirect_evidence(collection, binding=binding)
    location = collection["evidence"]["response_location"]
    classified = location["location_state"] == "single_classified"
    candidates = []
    if classified and location["target_scheme"] == "http":
        candidates.append({"detector": "http_scheme_location_reference_candidate", "evidence": {
            key: location[key] for key in ("response_status", "redirect_status", "location_state", "target_scheme", "same_origin")}})
    return {"method_version": METHOD, "binding": deepcopy(binding), "collection": deepcopy(collection),
        "availability": {"target_metadata": "observed" if classified else "unavailable"},
        "coverage": "one_original_first_https_response_classified_location_metadata_only",
        "candidates": candidates, "interpretation": INTERPRETATION}
