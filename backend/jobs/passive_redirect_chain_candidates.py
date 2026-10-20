"""Literal original selected-chain facts, not current source, severity or browser authority."""
from copy import deepcopy

from .passive_redirect_chain_evidence import validate_redirect_chain_evidence


METHOD = "passive-redirect-chain-candidates-v1"
INTERPRETATION = "dated_selected_scheme_transitions_and_stop_facts_not_current_availability_browser_behavior_authenticated_http_identity_severity_or_target_authority"


def redirect_chain_review_candidates(collection, *, binding):
    validate_redirect_chain_evidence(collection, binding=binding)
    hops = collection["evidence"]["hops"]
    transitions = [{"from_hop": index, "to_hop": index + 1} for index, (before, after) in enumerate(zip(hops, hops[1:]))
        if before["url"].startswith("https://") and after["url"].startswith("http://")]
    candidates = []
    if transitions:
        candidates.append({"detector": "observed_https_to_http_transition_candidate", "evidence": {"transitions": transitions}})
    stop = collection["evidence"]["state"]
    if stop in {"redirect_loop", "redirect_limit"}:
        candidates.append({"detector": "redirect_chain_loop_stop_candidate" if stop == "redirect_loop" else "redirect_chain_budget_stop_candidate",
            "evidence": {"state": stop, "observed_hops": len(hops), "last_hop": len(hops) - 1}})
    return {"method_version": METHOD, "binding": deepcopy(binding), "collection": deepcopy(collection),
        "availability": {"selected_urls": 1 + len(binding["target_urls"]), "observed_hops": len(hops),
            "last_target_metadata": "observed" if hops[-1]["response_location"]["location_state"] == "single_classified" else "unavailable"},
        "coverage": "original_selected_adjacent_scheme_transitions_and_transport_stop_only",
        "candidates": candidates, "interpretation": INTERPRETATION}
