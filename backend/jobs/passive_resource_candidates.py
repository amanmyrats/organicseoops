"""Dated lexical review candidate, not browser behavior or current source authority."""
from copy import deepcopy

from .passive_resource_evidence import validate_resource_evidence


METHOD = "passive-resource-candidates-v1"
INTERPRETATION = "dated_literal_http_reference_candidate_not_browser_requests_mixed_content_policy_severity_or_whole_page_security"


def static_resource_candidates(collection, *, binding):
    validate_resource_evidence(collection, binding=binding)
    resources = collection["evidence"]["resource_references"]
    observed = resources["state"] == "observed"
    candidates = []
    if observed and resources["counts"]["http_absolute"] > 0:
        candidates.append({"detector": "literal_http_resource_reference_candidate",
            "evidence": {"counts": deepcopy(resources["counts"]),
                "selected_attributes": deepcopy(resources["selected_attributes"]), "excluded": resources["excluded"]}})
    return {"method_version": METHOD, "binding": deepcopy(binding), "collection": deepcopy(collection),
        "state": "original_lexical_review_candidates" if observed else "original_lexical_evaluation_unavailable",
        "reason": resources["reason"], "coverage": resources["coverage"], "candidates": candidates,
        "interpretation": INTERPRETATION}
