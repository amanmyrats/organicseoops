"""D151 pure observation eligibility; no consent grant, capture or transport."""
import re

from .public_analytics_policy import parse_public_analytics_policy

METHOD = "public-observation-source-v1"
CONSENT_VERSION = "first-party-analytics-consent-v1"
ERROR = "public_observation_source_unavailable"


def public_observation_source(candidate, *, policy_content, expected_policy_digest, current_choice=False):
    """A future trusted caller must check its real current grant; client flags are not authority."""
    if (current_choice is not True or type(expected_policy_digest) is not str
        or not re.fullmatch(r"[0-9a-f]{64}", expected_policy_digest) or type(candidate) is not dict):
        raise ValueError(ERROR)
    try:
        policy, digest = parse_public_analytics_policy(policy_content)
        event = candidate.get("event_id")
        cta = event == "public_cta_selected"
        fields = {"dictionary_version", "event_id", "route_id", "locale", "consent_version", "consent_state"}
        if cta:
            fields.add("cta_id")
        if (digest != expected_policy_digest or set(candidate) != fields
            or candidate.get("dictionary_version") != "acquisition-v1"
            or type(event) is not str or event not in {"public_page_view", "public_cta_selected"}
            or candidate.get("consent_version") != CONSENT_VERSION or candidate.get("consent_state") != "granted"
            or type(candidate.get("route_id")) is not str or type(candidate.get("locale")) is not str):
            raise ValueError(ERROR)
        route = next((row for row in policy["routes"] if row["id"] == candidate["route_id"]
                      and row["locale"] == candidate["locale"]), None)
        if route is None or (cta and (type(candidate["cta_id"]) is not str or candidate["cta_id"] not in route["cta_ids"])):
            raise ValueError(ERROR)
        return {"method": METHOD, "dictionary_version": "acquisition-v1", "event_id": event,
                "route_id": route["id"], "locale": route["locale"], "consent_version": CONSENT_VERSION,
                "html_sha256": route["html_sha256"], "policy_digest": digest,
                **({"cta_id": candidate["cta_id"]} if cta else {})}
    except (ValueError, TypeError, RecursionError):
        raise ValueError(ERROR) from None
