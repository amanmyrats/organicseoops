"""Transient original source/key/strict robots-bound Lighthouse producer; owning jobs supply usage gates."""
import json
import time

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from integrations.google_tokens import _reject_constant, _unique_object
from providers.performance_key import google_performance_key
from .competitor_collection import _encode
from .competitor_lab import validate_lab
from .competitor_lab_selection import selection_snapshot, MAX_RESULT_BYTES
from .competitor_lab_source import validate_input
from .competitor_lab_transport import request_competitor_lab
from .crawling import CrawlScope, FetchDenied, FetchError, SafeFetcher, USER_AGENT, _connection_factory, _remaining, _system_resolver
from .passive_tls_evidence import _date
from .performance_transport import PerformanceTransportError
from .static_robots import strict_robots_policy


METHOD = "competitor-lighthouse-collect-v1"
INTERPRETATION = "one_original_selected_uri_device_provider_returned_lab_sample_not_field_data_current_site_whole_site_rankings_causality_or_live_provider_proof"
ERRORS = {"credential_unavailable", "egress_denied", "timeout", "dns_error", "network_error", "tls_verification_failed",
    "quota_limited", "redirect_denied", "provider_unavailable", "provider_request_rejected", "malformed_response",
    "response_too_large", "resource_body_unavailable", "invalid_content_length", "unsupported_content_encoding",
    "invalid_content_encoding", "incomplete_response_body", "non_public_address", "static_document_unavailable",
    "static_source_robots_denied", "static_source_robots_unknown", "lighthouse_invalid", "lighthouse_failed"}


def _data(binding):
    try:
        source = binding["source"]; page = source["page_source"]
        return validate_input({"origin":page["origin"], "url":page["url"], "collection_permission":page["collection_permission"],
            "strategy":source["strategy"], "provider_processing_permission":source["provider_processing_permission"]})
    except (KeyError, TypeError, ValidationError): raise PermissionDenied from None


def validate_result(result, binding):
    if type(result) is not dict or result.get("method_version") != METHOD:
        raise ValidationError("Original minimized Lighthouse result is unavailable.")
    data = _data(binding)
    if result.get("state") == "unavailable":
        if (set(result) != {"method_version", "state", "error_category"}
            or type(result["error_category"]) is not str or result["error_category"] not in ERRORS):
            raise ValidationError("Original minimized Lighthouse result is unavailable.")
    elif result.get("state") == "collected":
        if (set(result) != {"method_version", "state", "selection_sha256", "url", "strategy", "robots", "request_started_at", "evidence", "interpretation"}
            or result["selection_sha256"] != binding["selection_sha256"] or result["url"] != data["url"] or result["strategy"] != data["strategy"]
            or result["interpretation"] != INTERPRETATION or type(result["robots"]) is not str
            or result["robots"] not in {"available", "missing_http_404_or_410"}):
            raise ValidationError("Original minimized Lighthouse result is unavailable.")
        started = _date(result["request_started_at"])
        evidence = validate_lab(result["evidence"])
        if (evidence["url"] != data["url"] or evidence["strategy"] != data["strategy"]
            or _date(evidence["received_at"]) < started
            or started < _date(binding["source"]["page_source"]["configuration_updated_at"], microseconds=False)):
            raise ValidationError("Original Lighthouse receipt precedes its request or configuration.")
    else: raise ValidationError("Original minimized Lighthouse result is unavailable.")
    if len(_encode(result)) > MAX_RESULT_BYTES: raise ValidationError("Original Lighthouse result exceeds its bounded limit.")
    return result


def parse_result(content, binding):
    try:
        if type(content) is not bytes or not 1 <= len(content) <= MAX_RESULT_BYTES: raise ValueError
        return validate_result(json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant), binding)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValidationError("Original minimized Lighthouse result is unavailable.") from None


def collect_competitor_lab(*, project, actor, binding, before_request, before_send, robots_fetcher=None,
                          resolver=_system_resolver, connection_factory=_connection_factory, clock=time.monotonic, sleep=time.sleep):
    if type(binding) is not dict or not callable(before_request) or not callable(before_send): raise PermissionDenied
    try:
        content = _encode(binding)
        if len(content) > MAX_RESULT_BYTES: raise ValueError
        binding = json.loads(content); data = _data(binding)
    except (ValueError, TypeError, UnicodeError, RecursionError): raise PermissionDenied from None
    key = None

    def current():
        before_request()
        if selection_snapshot(project=project, actor=actor, data=data) != binding: raise PermissionDenied
        if key is not None:
            try: fresh_key = google_performance_key(organization=project.organization)
            except ValidationError: raise PermissionDenied from None
            if fresh_key != key: raise PermissionDenied
        before_request()

    current()
    deadline = clock() + 30
    started_at = timezone.now().isoformat(timespec="microseconds")
    robots_url = data["origin"] + "/robots.txt"

    def robots_check(url):
        current()
        if url != robots_url: raise FetchDenied("static_source_robots_denied")
        _remaining(deadline, clock)

    def send():
        current(); before_send(); current(); _remaining(deadline, clock)

    try:
        try: key = google_performance_key(organization=project.organization)
        except ValidationError: raise PerformanceTransportError("credential_unavailable") from None
        current()
        fetcher = robots_fetcher or SafeFetcher(CrawlScope(frozenset({binding["source"]["page_source"]["hostname"]}), kind="competitor"),
            resolver=resolver, connection_factory=connection_factory, timeout=8, max_redirects=0, max_bytes=128*1024, clock=clock)
        response = fetcher.fetch(robots_url, static_document_type="text/plain", before_request=robots_check,
            before_send=robots_check, deadline=deadline)
        robots_check(response.url)
        if response.redirects: raise FetchDenied("static_source_robots_denied")
        robots, state, delay = strict_robots_policy(response)
        if not robots.can_fetch(USER_AGENT, data["url"]) or not robots.can_fetch("*", data["url"]):
            raise FetchDenied("static_source_robots_denied")
        current()
        if delay >= _remaining(deadline, clock): raise PerformanceTransportError("timeout")
        sleep(delay); current()
        evidence = request_competitor_lab(url=data["url"], strategy=data["strategy"], api_key=key,
            checkpoint=current, before_send=send, timeout=min(30, _remaining(deadline, clock)),
            resolver=resolver, connection_factory=connection_factory, clock=clock, _deadline=deadline)
        result = {"method_version":METHOD, "state":"collected", "selection_sha256":binding["selection_sha256"],
            "url":data["url"], "strategy":data["strategy"], "robots":state, "request_started_at":started_at,
            "evidence":evidence, "interpretation":INTERPRETATION}
        validate_result(result, binding)
    except (FetchError, PerformanceTransportError) as error:
        category = error.code if isinstance(error, FetchError) else error.category
        result = {"method_version":METHOD, "state":"unavailable", "error_category":category if type(category) is str and category in ERRORS else "lighthouse_failed"}
    except (ValidationError, ValueError, UnicodeError, RecursionError):
        result = {"method_version":METHOD, "state":"unavailable", "error_category":"lighthouse_invalid"}
    current()
    if clock() >= deadline: return {"method_version":METHOD, "state":"unavailable", "error_category":"timeout"}
    return result
