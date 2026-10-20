"""Current explicit competitor/Google processing selection, not request or observed authority."""
from hashlib import sha256
import json

from django.core.exceptions import PermissionDenied, ValidationError

from .competitor_page_source import current_competitor_page_source, validate_input as validate_page_input


METHOD = "competitor-lighthouse-source-v1"
PROVIDER = "google_pagespeed_insights"
INTERPRETATION = "current_selected_exact_uri_device_and_declared_google_processing_permission_not_ownership_legal_approval_key_network_commercial_or_observed_lab_authority"
MAX_RESULT_BYTES = 8192


def validate_input(data):
    if (type(data) is not dict or set(data) != {"origin", "url", "collection_permission", "provider_processing_permission", "strategy"}
        or data["provider_processing_permission"] is not True or type(data["strategy"]) is not str
        or data["strategy"] not in {"mobile", "desktop"}):
        raise ValidationError("Select one exact competitor page, device and independent Google processing permission.")
    page = validate_page_input({key: data[key] for key in ("origin", "url", "collection_permission")})
    return {**page, "provider_processing_permission": True, "strategy": data["strategy"]}


def current_competitor_lab_source(*, project, actor, data):
    data = validate_input(data)
    selected = {key: data[key] for key in ("origin", "url", "collection_permission")}
    original = current_competitor_page_source(project=project, actor=actor, data=selected)
    result = {"method_version": METHOD, "provider": PROVIDER, "page_source": original,
        "strategy": data["strategy"], "provider_processing_permission": True, "interpretation": INTERPRETATION}
    content = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(content) > MAX_RESULT_BYTES: raise ValidationError("Original selected Lighthouse source exceeds its bounded limit.")
    result["source_sha256"] = sha256(content).hexdigest()
    if current_competitor_page_source(project=project, actor=actor, data=selected) != original: raise PermissionDenied
    return result
