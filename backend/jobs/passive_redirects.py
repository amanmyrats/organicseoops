"""Pure original Location metadata; never a target request or source authority."""
import re
from urllib.parse import unquote, urljoin, urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

from .crawling import REDIRECT_STATUSES
from .crawling import CrawlScope, FetchDenied
from .passive_header_source import validate_input as source_syntax
from .passive_headers import observe_response_headers


METHOD = "passive-response-location-v1"
MAX_REFERENCE = 1024
INTERPRETATION = "one_response_location_metadata_not_followed_chain_https_upgrade_browser_behavior_or_target_authority"


def _target(value, source_url):
    # urllib.parse does not validate and silently strips some controls. Check first.
    if (not 1 <= len(value) <= MAX_REFERENCE or any(ord(char) < 33 or ord(char) > 126 or char == "\\" for char in value)
        or re.search(r'["<>^`{|}]', value)
        or re.search(r"%(?![A-Fa-f0-9]{2})", value)
        or any(ord(char) < 32 or char == "\\" for char in unquote(value)) or value.startswith("///")):
        return None
    try:
        reference = urlsplit(value)
        if (reference.scheme and (reference.scheme not in {"http", "https"} or not reference.netloc)
            or value.startswith("//") and not reference.netloc
            or any("[" in part or "]" in part for part in (reference.path, reference.query, reference.fragment))): return None
        resolved = urljoin(source_url, value)
        URLValidator(schemes=["http", "https"])(resolved)
        parts = urlsplit(resolved)
        if parts.username is not None or parts.password is not None or parts.port == 0 or parts.netloc.endswith(":"): return None
        original = urlsplit(source_url)
        origin = lambda row: (row.scheme, row.hostname, row.port or (443 if row.scheme == "https" else 80))
        return parts.scheme, origin(parts) == origin(original)
    except (ValueError, ValidationError):
        return None


def observe_response_location(*, source_url, status, fields):
    # Only reuse pure URL syntax; this supplies no header/source/capture permission.
    source_syntax({"url": source_url, "observations": ["response_headers"], "collection_permission": True})
    return _location_metadata(source_url, status, fields)


def validate_http_source_url(source_url):
    """Pure canonical HTTP syntax shared by interpretation and independent source selection."""
    try:
        if (type(source_url) is not str or not 1 <= len(source_url) <= 1024 or not source_url.startswith("http://")
            or "?" in source_url or "#" in source_url or any(ord(char) < 33 or char == "\\" for char in source_url)):
            raise ValueError
        URLValidator(schemes=["http"])(source_url)
        source = urlsplit(source_url)
        if CrawlScope(frozenset({source.hostname})).validate_url(source_url) != source_url: raise ValueError
    except (ValueError, ValidationError, FetchDenied):
        raise ValidationError("Choose exact canonical default-port HTTP source syntax without credentials or parameters.") from None
    return source


def observe_http_response_location(*, source_url, status, fields):
    """Pure original HTTP reference syntax, never observed HTTPS or authority for either origin."""
    source = validate_http_source_url(source_url)
    result = _location_metadata(source_url, status, fields)
    result.update(method_version="passive-http-response-location-v1", same_hostname_default_https=None,
        interpretation="one_http_response_location_metadata_not_observed_https_followed_upgrade_browser_behavior_or_target_authority")
    if result["location_state"] == "single_classified":
        # Only a reference classified by the shared strict URI validator reaches this projection.
        reference = next(value.strip(" \t") for name, value in fields if name.lower() == "location")
        target = urlsplit(urljoin(source_url, reference))
        result["same_hostname_default_https"] = (target.scheme == "https" and target.hostname == source.hostname
            and target.port in (None, 443))
    return result


def _location_metadata(source_url, status, fields):
    if type(status) is not int or not 200 <= status <= 599:
        raise ValidationError("Original bounded response status is unavailable.")
    result = {"method_version": METHOD, "state": "unavailable" if fields is None else "observed",
        "response_status": status, "redirect_status": status in REDIRECT_STATUSES,
        "location_state": None, "target_scheme": None, "same_origin": None,
        "coverage": "one_complete_original_response_status_and_location_fields_only", "interpretation": INTERPRETATION}
    # Reuse the checked original sequence/type/control/latin1/100-field/32KiB validation.
    observe_response_headers(fields)
    if fields is None: return result
    values = [value.strip(" \t") for name, value in fields if name.lower() == "location"]
    if not values: result["location_state"] = "absent"
    elif len(values) > 1: result["location_state"] = "multiple_fields"
    elif not values[0]: result["location_state"] = "present_empty"
    else:
        target = _target(values[0], source_url)
        result["location_state"] = "single_unclassified" if target is None else "single_classified"
        if target is not None: result["target_scheme"], result["same_origin"] = target
    return result


def resolve_permitted_response_location(*, selection, current_url, status, fields):
    """Pure transient next-URL matching from fresh fields; no verification or follow authority."""
    from .passive_redirect_chain_source import validate_input

    selection, _ = validate_input(selection)
    allowed = [selection["url"], *selection["target_urls"]]
    if type(current_url) is not str or current_url not in allowed:
        raise ValidationError("The original response URL must be explicitly selected.")
    interpret = observe_http_response_location if current_url.startswith("http://") else observe_response_location
    location = interpret(source_url=current_url, status=status, fields=fields)
    result = {"method_version": "passive-permitted-response-location-v1", "state": "location_unavailable",
        "next_url": None, "response_location": location,
        "interpretation": "transient_exact_url_permission_match_not_verified_target_observed_chain_or_network_authority"}
    if location["state"] != "observed": return result
    if not location["redirect_status"]:
        result["state"] = "terminal_response"
        return result
    if location["location_state"] != "single_classified": return result
    reference = next(value.strip(" \t") for name, value in fields if name.lower() == "location")
    result["state"] = "unsupported_target"
    # urljoin can discard empty delimiters; they must not become an allowed parameter-free URL.
    if "?" in reference or "#" in reference: return result
    try:
        target = urljoin(current_url, reference)
        target = CrawlScope(frozenset({urlsplit(target).hostname})).validate_url(target)
    except (ValueError, FetchDenied):
        return result
    result["state"] = "outside_exact_target_allowlist"
    if target in allowed:
        result.update(state="permitted_target", next_url=target)
    return result
