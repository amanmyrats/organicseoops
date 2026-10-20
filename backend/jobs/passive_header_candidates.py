"""Factual original response review candidates; no current source or persistence authority."""
from copy import deepcopy
import re

from django.core.exceptions import ValidationError

from tenancy.support_requests import _safe_id
from .passive_header_collection import _date, validate_result
from .passive_header_source import METHOD as SOURCE_METHOD, validate_input


METHOD = "passive-header-candidates-v1"
INTERPRETATION = "dated_response_review_candidates_not_severity_policy_effectiveness_browser_behavior_or_exploitability"
SECURITY_HEADERS = ("strict-transport-security", "content-security-policy", "x-frame-options",
    "x-content-type-options", "referrer-policy")
DISCLOSURE_HEADERS = ("server", "x-powered-by")
COOKIE_FLAGS = ("without_secure", "without_httponly", "without_recognized_samesite")


def response_header_candidates(collection, *, binding):
    """Validate minimized original evidence, preserving ambiguity instead of inventing risk."""
    if (type(binding) is not dict or set(binding) != {"method_version", "organization_id", "project_id", "actor_id",
        "origin", "url", "observations", "collection_permission", "verification_id", "verified_at", "source_digest", "interpretation"}
        or binding["method_version"] != SOURCE_METHOD
        or binding["interpretation"] != "current_source_binding_not_network_job_commercial_reservation_or_observation_authority"
        or type(binding["source_digest"]) is not str or not re.fullmatch(r"[a-f0-9]{64}", binding["source_digest"])):
        raise ValidationError("Choose exact original minimized header source evidence.")
    _data, origin = validate_input({key: binding[key] for key in ("url", "observations", "collection_permission")})
    if binding["origin"] != origin:
        raise ValidationError("Original header source origin differs.")
    for key in ("organization_id", "project_id", "actor_id", "verification_id"): _safe_id(binding[key])
    _date(binding["verified_at"])
    validate_result(collection, binding)
    headers, cookies = collection["evidence"]["headers"], collection["evidence"]["cookies"]
    candidates = []
    for header in SECURITY_HEADERS:
        state = headers[header]
        if state in {"absent", "present_empty"}:
            evidence = {"header": header, "state": state}
            if header == "content-security-policy":
                evidence["report_only_state"] = headers["content-security-policy-report-only"]
            candidates.append({"detector": "response_" + header.replace("-", "_") + "_" + state + "_candidate",
                "evidence": evidence})
    for header in DISCLOSURE_HEADERS:
        if headers[header] == "present_nonempty":
            candidates.append({"detector": "response_" + header.replace("-", "_") + "_disclosure_candidate",
                "evidence": {"header": header, "state": "present_nonempty"}})
    for flag in COOKIE_FLAGS:
        if cookies[flag] > 0:
            candidates.append({"detector": "parsed_public_cookie_" + flag + "_candidate",
                "evidence": {"flag": flag, "count": cookies[flag], "parsed_fields": cookies["parsed_fields"],
                    "observed_fields": cookies["observed_fields"], "unclassified_fields": cookies["unclassified_fields"]}})
    return {"method_version": METHOD, "binding": deepcopy(binding), "collection": deepcopy(collection),
        "coverage": "one_original_response_selected_header_categories_and_parsed_cookie_subset_only",
        "candidates": candidates, "interpretation": INTERPRETATION}
