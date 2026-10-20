"""Current exact customer-selected competitor URI; no observed page or request authority."""
from hashlib import sha256
import json
from urllib.parse import urlsplit

from django.core.exceptions import PermissionDenied, ValidationError

from .competitor_metadata import validate_url
from .competitor_source import current_competitor_source


METHOD = "competitor-page-source-v1"
SCOPE = "selected_competitor_exact_same_origin_default_port_nonroot_uri_no_query_fragment"
INTERPRETATION = "customer_selected_exact_uri_not_page_identity_ownership_approval_time_network_commercial_or_observation_authority"


def validate_input(data):
    if (type(data) is not dict or set(data) != {"origin", "url", "collection_permission"}
        or data["collection_permission"] is not True):
        raise ValidationError("Explicitly select one configured competitor and exact non-root URI with collection permission.")
    url, origin = data["url"], data["origin"]
    validate_url(url)
    parts = urlsplit(url)
    if parts.path == "/" or parts.scheme + "://" + parts.netloc != origin:
        raise ValidationError("Choose one exact non-root URI on the selected competitor's original origin.")
    return {"origin": origin, "url": url, "collection_permission": True}


def current_competitor_page_source(*, project, actor, data):
    data = validate_input(data)
    url, origin = data["url"], data["origin"]
    selected = {"origin": origin, "collection_permission": True}
    original = current_competitor_source(project=project, actor=actor, data=selected)
    pin = json.dumps({"source": original, "url": url}, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    result = {**original, "method_version": METHOD, "url": url, "scope_kind": SCOPE,
        "source_sha256": sha256(pin).hexdigest(), "interpretation": INTERPRETATION}
    if current_competitor_source(project=project, actor=actor, data=selected) != original: raise PermissionDenied
    return result
