"""Strict original selected chain metadata; no raw target reconstruction or current authority."""
import json
import re
from urllib.parse import urlsplit

from integrations.google_tokens import _reject_constant, _unique_object
from tenancy.support_requests import _safe_id
from . import passive_http_redirect_evidence as http
from . import passive_redirect_evidence as https
from .crawling import FetchResponse
from .passive_redirect_chain_source import MAX_TARGETS, METHOD as SOURCE_METHOD, validate_input
from .passive_redirect_evidence import _date, _deny


METHOD = "passive-exact-redirect-chain-evidence-v1"
MAX_RESULT_BYTES = 24 * 1024
INTERPRETATION = "dated_exact_selected_responses_not_browser_behavior_current_availability_authenticated_http_identity_or_security_verdict"
TRANSPORT_FIXED = {"method_version": "passive-exact-redirect-chain-response-v1",
    "coverage": "at_most_six_selected_original_header_responses_only", "interpretation": INTERPRETATION}
TARGET_STATES = {"permitted_target", "terminal_response", "location_unavailable", "unsupported_target", "outside_exact_target_allowlist"}


def _binding(binding):
    if (type(binding) is not dict or set(binding) != {"method_version", "organization_id", "project_id", "actor_id",
        "url", "target_urls", "observations", "collection_permission", "origins", "source_digest", "interpretation"}
        or binding["method_version"] != SOURCE_METHOD
        or binding["interpretation"] != "explicit_exact_url_allowlist_not_observed_chain_network_job_or_commercial_reservation"
        or type(binding["source_digest"]) is not str or not re.fullmatch(r"[a-f0-9]{64}", binding["source_digest"])):
        _deny()
    data, origins = validate_input({key: binding[key] for key in ("url", "target_urls", "observations", "collection_permission")})
    for key in ("organization_id", "project_id", "actor_id"): _safe_id(binding[key])
    if type(binding["origins"]) is not list or len(binding["origins"]) != len(origins): _deny()
    ids, dates = [], []
    for origin, row in zip(origins, binding["origins"]):
        if type(row) is not dict or set(row) != {"origin", "verification_id", "verified_at"} or row["origin"] != origin: _deny()
        _safe_id(row["verification_id"]); ids.append(row["verification_id"])
        dates.append(_date(row["verified_at"], microseconds=False))
    if len(set(ids)) != len(ids): _deny()
    return data, max(dates)


def _matches(location, current, target):
    current, target = urlsplit(current), urlsplit(target)
    return (location["target_scheme"] == target.scheme
        and location["same_origin"] == ((current.scheme, current.netloc) == (target.scheme, target.netloc))
        and (current.scheme != "http" or location["same_hostname_default_https"] ==
            (target.scheme == "https" and current.hostname == target.hostname)))


def validate_redirect_chain_evidence(result, *, binding):
    data, verified = _binding(binding)
    if (type(result) is not dict or set(result) != {"method", "url", "final_url", "status", "observed_at", "last_observed_at", "evidence", "interpretation"}
        or result["method"] != METHOD or result["url"] != data["url"] or result["interpretation"] != INTERPRETATION): _deny()
    evidence = result["evidence"]
    if (type(evidence) is not dict or set(evidence) != set(TRANSPORT_FIXED) | {"hops", "state"}
        or any(evidence[key] != value for key, value in TRANSPORT_FIXED.items())
        or type(evidence["state"]) is not str or evidence["state"] not in TARGET_STATES | {"redirect_loop", "redirect_limit"}
        or evidence["state"] == "permitted_target" or type(evidence["hops"]) is not list
        or not 1 <= len(evidence["hops"]) <= MAX_TARGETS + 1): _deny()
    allowed, seen, previous = [data["url"], *data["target_urls"]], [], verified
    hops = evidence["hops"]
    for index, hop in enumerate(hops):
        if (type(hop) is not dict or set(hop) != {"url", "status", "observed_at", "response_location", "target_state"}
            or type(hop["url"]) is not str or hop["url"] not in allowed or hop["url"] in seen
            or type(hop["status"]) is not int or not 200 <= hop["status"] <= 599
            or type(hop["target_state"]) is not str or hop["target_state"] not in TARGET_STATES): _deny()
        observed = _date(hop["observed_at"])
        if observed < previous or index == 0 and hop["url"] != data["url"]: _deny()
        previous = observed; seen.append(hop["url"])
        location = hop["response_location"]
        family = http if hop["url"].startswith("http://") else https
        family._location(location, source_url=hop["url"], status=hop["status"])
        state = hop["target_state"]
        if not location["redirect_status"]:
            if state != "terminal_response": _deny()
        elif location["location_state"] != "single_classified":
            if state != "location_unavailable": _deny()
        elif state not in {"permitted_target", "unsupported_target", "outside_exact_target_allowlist"}: _deny()
        if index:
            prior = hops[index - 1]
            if prior["target_state"] != "permitted_target" or not _matches(prior["response_location"], prior["url"], hop["url"]): _deny()
    last, stop = hops[-1], evidence["state"]
    if stop in {"redirect_loop", "redirect_limit"}:
        candidates = seen if stop == "redirect_loop" else [url for url in allowed if url not in seen]
        if last["target_state"] != "permitted_target" or not any(_matches(last["response_location"], last["url"], url) for url in candidates): _deny()
    elif stop != last["target_state"]: _deny()
    if (result["final_url"] != last["url"] or type(result["status"]) is not int or result["status"] != last["status"]
        or result["observed_at"] != hops[0]["observed_at"] or result["last_observed_at"] != last["observed_at"]): _deny()
    _encode(result)
    return result


def _encode(result):
    try: content = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError): _deny()
    if len(content) > MAX_RESULT_BYTES: _deny()
    return content


def minimized_redirect_chain_evidence(response, *, binding):
    if (type(response) is not FetchResponse or type(response.headers) is not dict or response.headers != {}
        or type(response.body) is not bytes or response.body != b"" or type(response.redirects) is not tuple or response.redirects != ()
        or response.header_observation is not None or response.resource_observation is not None or response.observed_at is not None
        or type(response.redirect_observation) is not dict): _deny()
    evidence = response.redirect_observation
    hops = evidence.get("hops")
    if type(hops) is not list or not hops or type(hops[0]) is not dict or type(hops[-1]) is not dict: _deny()
    result = {"method": METHOD, "url": binding.get("url") if type(binding) is dict else None,
        "final_url": response.url, "status": response.status, "observed_at": hops[0].get("observed_at"),
        "last_observed_at": hops[-1].get("observed_at"), "evidence": evidence, "interpretation": INTERPRETATION}
    return json.loads(encode_redirect_chain_evidence(result, binding=binding))


def encode_redirect_chain_evidence(result, *, binding):
    return _encode(validate_redirect_chain_evidence(result, binding=binding))


def parse_redirect_chain_evidence(content, *, binding):
    if type(content) is not bytes or not 1 <= len(content) <= MAX_RESULT_BYTES: _deny()
    try: result = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError): _deny()
    return validate_redirect_chain_evidence(result, binding=binding)
