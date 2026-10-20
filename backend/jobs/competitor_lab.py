"""Minimized provider-returned lab JSON; no grant, protected request or live audit proof."""
from datetime import datetime
from hashlib import sha256
import json
import math
import re
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError

from integrations.google_tokens import _reject_constant, _unique_object
from .competitor_metadata import validate_url
from .passive_tls_evidence import _date
from .performance import LAB_AUDITS, _lighthouse_lab, _object


METHOD = "competitor-pagespeed-lab-v1"
COVERAGE = "one_complete_provider_json_selected_exact_nonroot_uri_lighthouse_lab_sample_only"
INTERPRETATION = "provider_reported_lab_sample_not_field_p75_core_web_vitals_whole_site_rankings_causality_ownership_current_site_or_live_provider_proof"
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_RESULT_BYTES = 8192
SCORES = ("performance", "accessibility", "best-practices", "seo")
FIELDS = {"method_version", "url", "strategy", "received_at", "response_sha256", "response_size_bytes",
    "provider_reported_at", "state", "reason", "lab", "coverage", "interpretation"}
LAB_FIELDS = {"source", "kind", "status", "requested_url", "final_url", "strategy", "lighthouse_version",
    "observed_at", "scores", "audits", "score_method", "field_data"}


def _deny():
    raise ValidationError("Original bounded selected-URI Lighthouse lab evidence is unavailable.")


def _provider_date(value):
    try:
        if type(value) is not str or not 1 <= len(value) <= 48: raise ValueError
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.utcoffset() is None: raise ValueError
    except (ValueError, OverflowError): _deny()
    return stamp


def _url(value):
    validate_url(value)
    if urlsplit(value).path == "/": _deny()


def validate_lab(result):
    if (type(result) is not dict or set(result) != FIELDS or result["method_version"] != METHOD
        or result["coverage"] != COVERAGE or result["interpretation"] != INTERPRETATION
        or type(result["strategy"]) is not str or result["strategy"] not in {"mobile", "desktop"}
        or type(result["response_sha256"]) is not str or not re.fullmatch(r"[a-f0-9]{64}", result["response_sha256"])
        or type(result["response_size_bytes"]) is not int or not 1 <= result["response_size_bytes"] <= MAX_BODY_BYTES): _deny()
    _url(result["url"])
    received = _date(result["received_at"])
    provider_date = _provider_date(result["provider_reported_at"])
    if provider_date > received: _deny()
    lab = result["lab"]
    if result["state"] == "unavailable":
        if type(result["reason"]) is not str or result["reason"] != "runtime_failed" or lab is not None: _deny()
    elif result["state"] == "observed":
        if (result["reason"] != "" or type(lab) is not dict or set(lab) != LAB_FIELDS
            or lab["source"] != "pagespeed_insights" or lab["kind"] != "lighthouse_lab" or lab["status"] != "observed"
            or lab["requested_url"] != result["url"] or lab["final_url"] != result["url"] or lab["strategy"] != result["strategy"]
            or lab["observed_at"] != provider_date.isoformat() or lab["field_data"] != "not_used"
            or lab["score_method"] != "lighthouse_lab_score_not_field_p75"
            or type(lab["lighthouse_version"]) is not str or len(lab["lighthouse_version"]) > 32
            or lab["lighthouse_version"] != "unknown" and not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", lab["lighthouse_version"])
            or type(lab["scores"]) is not dict or set(lab["scores"]) != set(SCORES)
            or type(lab["audits"]) is not dict or set(lab["audits"]) != set(LAB_AUDITS)): _deny()
        for value in lab["scores"].values():
            if value is not None and (type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 1): _deny()
        for key, unit in LAB_AUDITS.items():
            item = lab["audits"][key]
            if type(item) is not dict or set(item) != {"value", "unit", "state"} or item["unit"] != unit: _deny()
            value = item["value"]
            if (item["state"] != ("observed" if value is not None else "unavailable")
                or value is not None and (type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 10_000_000)): _deny()
    else: _deny()
    return result


def encode_lab(result):
    validate_lab(result)
    try: content = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError): _deny()
    if len(content) > MAX_RESULT_BYTES: _deny()
    return content


def parse_lab(content):
    if type(content) is not bytes or not 1 <= len(content) <= MAX_RESULT_BYTES: _deny()
    try: result = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError): _deny()
    encode_lab(result)
    return result


def observe_pagespeed_lab(*, body, body_complete, url, strategy, received_at):
    _url(url)
    received = _date(received_at)
    if (body_complete is not True or type(body) is not bytes or not 1 <= len(body) <= MAX_BODY_BYTES
        or type(strategy) is not str or strategy not in {"mobile", "desktop"}): _deny()
    try: payload = json.loads(body.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError): _deny()
    _object(payload, MAX_BODY_BYTES)
    if payload.get("id") != url: _deny()
    lighthouse = payload.get("lighthouseResult")
    if (type(lighthouse) is not dict or lighthouse.get("requestedUrl") != url or lighthouse.get("finalUrl") != url
        or type(lighthouse.get("configSettings")) is not dict or lighthouse["configSettings"].get("formFactor") != strategy): _deny()
    reported = lighthouse.get("fetchTime")
    if _provider_date(reported) > received: _deny()
    lab = _lighthouse_lab(lighthouse=lighthouse, requested=url, final_url=url, strategy=strategy)
    failed = lab["status"] != "observed"
    if not failed and len(lab["lighthouse_version"]) > 32: lab["lighthouse_version"] = "unknown"
    result = {"method_version": METHOD, "url": url, "strategy": strategy, "received_at": received_at,
        "response_sha256": sha256(body).hexdigest(), "response_size_bytes": len(body), "provider_reported_at": reported,
        "state": "unavailable" if failed else "observed", "reason": "runtime_failed" if failed else "", "lab": None if failed else lab,
        "coverage": COVERAGE, "interpretation": INTERPRETATION}
    return parse_lab(encode_lab(result))
