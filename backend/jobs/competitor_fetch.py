"""Transient fixed single-document producers; owning once-only jobs supply costly-work gates."""
import json
import time

from django.core.exceptions import PermissionDenied, ValidationError

from .competitor_metadata import MAX_BODY_BYTES, MAX_RESULT_BYTES, observe_static_metadata, validate_url
from .competitor_schema import observe_static_schema
from .competitor_links import observe_static_links
from .competitor_headings import observe_static_headings
from .competitor_destinations import observe_static_destinations
from .competitor_dates import observe_static_dates
from .competitor_source import current_competitor_source
from .competitor_page_source import current_competitor_page_source
from .crawler import CrawlStopped, PacedFetcher
from .crawling import CrawlScope, FetchDenied, FetchError, SafeFetcher, USER_AGENT
from .passive_tls_evidence import _date
from .static_robots import strict_robots_policy


METHOD = "competitor-static-root-collect-v1"
SCHEMA_METHOD = "competitor-static-schema-root-collect-v1"
LINKS_METHOD = "competitor-static-root-links-collect-v1"
PAGE_METHOD = "competitor-static-page-collect-v1"
PAGE_HEADINGS_METHOD = "competitor-page-headings-collect-v1"
PAGE_DESTINATIONS_METHOD = "competitor-page-destinations-v1"
PAGE_DATES_METHOD = "competitor-page-dates-collect-v1"
DEADLINE_SECONDS = 30
INTERPRETATION = "one_selected_static_root_not_site_inventory_rendering_freshness_traffic_rankings_or_backlinks"
PAGE_INTERPRETATION = "one_selected_static_nonroot_uri_not_site_inventory_rendering_freshness_traffic_rankings_or_backlinks"
ERRORS = {"invalid_url", "outside_scope", "invalid_scope", "non_public_address", "dns_error", "timeout", "network_error",
    "invalid_static_document", "static_document_unavailable", "resource_body_unavailable", "invalid_content_length",
    "response_too_large", "unsupported_content_encoding", "invalid_content_encoding", "incomplete_response_body",
    "static_source_robots_denied", "static_source_robots_unknown", "competitor_document_scope", "competitor_document_deadline",
    "competitor_document_http_status", "competitor_document_result_limit", "competitor_document_invalid", "competitor_document_failed"}


def collect_competitor_metadata(*, project, actor, binding, before_request, fetcher=None, clock=time.monotonic, sleep=time.sleep):
    return _collect(project=project, actor=actor, binding=binding, before_request=before_request,
        fetcher=fetcher, clock=clock, sleep=sleep, method=METHOD, observer=observe_static_metadata)


def collect_competitor_schema(*, project, actor, binding, before_request, fetcher=None, clock=time.monotonic, sleep=time.sleep):
    return _collect(project=project, actor=actor, binding=binding, before_request=before_request,
        fetcher=fetcher, clock=clock, sleep=sleep, method=SCHEMA_METHOD, observer=observe_static_schema)


def collect_competitor_links(*, project, actor, binding, before_request, fetcher=None, clock=time.monotonic, sleep=time.sleep):
    return _collect(project=project, actor=actor, binding=binding, before_request=before_request,
        fetcher=fetcher, clock=clock, sleep=sleep, method=LINKS_METHOD, observer=observe_static_links)


def collect_competitor_page_metadata(*, project, actor, binding, before_request, fetcher=None, clock=time.monotonic, sleep=time.sleep):
    return _collect(project=project, actor=actor, binding=binding, before_request=before_request,
        fetcher=fetcher, clock=clock, sleep=sleep, method=PAGE_METHOD, observer=observe_static_metadata, page=True)


def collect_competitor_page_headings(*, project, actor, binding, before_request, fetcher=None, clock=time.monotonic, sleep=time.sleep):
    return _collect(project=project, actor=actor, binding=binding, before_request=before_request,
        fetcher=fetcher, clock=clock, sleep=sleep, method=PAGE_HEADINGS_METHOD, observer=observe_static_headings, page=True)


def collect_competitor_page_destinations(*, project, actor, binding, before_request, fetcher=None, clock=time.monotonic, sleep=time.sleep):
    return _collect(project=project, actor=actor, binding=binding, before_request=before_request,
        fetcher=fetcher, clock=clock, sleep=sleep, method=PAGE_DESTINATIONS_METHOD, observer=observe_static_destinations, page=True)


def collect_competitor_page_dates(*, project, actor, binding, before_request, fetcher=None, clock=time.monotonic, sleep=time.sleep):
    return _collect(project=project, actor=actor, binding=binding, before_request=before_request,
        fetcher=fetcher, clock=clock, sleep=sleep, method=PAGE_DATES_METHOD, observer=observe_static_dates, page=True)


def _collect(*, project, actor, binding, before_request, fetcher, clock, sleep, method, observer, page=False):
    if type(binding) is not dict or not callable(before_request): raise PermissionDenied
    try:
        content = json.dumps(binding, allow_nan=False).encode()
        if len(content) > MAX_RESULT_BYTES: raise ValueError
        binding = json.loads(content)
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise PermissionDenied from None

    def current():
        before_request()
        selected = {"origin": binding.get("origin"), "collection_permission": binding.get("collection_permission")}
        if page: selected["url"] = binding.get("url")
        reader = current_competitor_page_source if page else current_competitor_source
        fresh = reader(project=project, actor=actor, data=selected)
        if fresh != binding: raise PermissionDenied
        before_request()  # Source reads cannot carry an earlier commercial/cancel check past expiry.

    current()
    origin = binding["origin"]
    target, robots_url = binding["url"] if page else origin + "/", origin + "/robots.txt"
    deadline = clock() + DEADLINE_SECONDS
    robots = None
    source_phase = False

    def checkpoint(url):
        current()
        validate_url(url)
        # No-follow transport and exact phase URL prevent cross-origin robots reuse.
        if url != (target if source_phase else robots_url): raise FetchDenied("competitor_document_scope")
        if source_phase and not robots.can_fetch(USER_AGENT, url): raise FetchDenied("static_source_robots_denied")
        if clock() >= deadline: raise FetchError("competitor_document_deadline")
        return ""

    transport = fetcher or SafeFetcher(CrawlScope(frozenset({binding["hostname"]}), kind="competitor"),
        timeout=8, max_redirects=0, max_bytes=MAX_BODY_BYTES)
    paced = PacedFetcher(transport, denial=checkpoint, deadline=deadline, delay_seconds=1, clock=clock, sleep=sleep)
    try:
        response = paced.fetch(robots_url, static_document_type="text/plain", before_send=checkpoint)
        checkpoint(response.url)
        robots, robots_state, paced.delay_seconds = strict_robots_policy(response)
        source_phase = True
        response = paced.fetch(target, static_document_type="text/html", before_send=checkpoint)
        checkpoint(response.url)
        if response.status != 200: raise FetchError("competitor_document_http_status")
        if response.headers != {"content-type": "text/html"} or response.redirects: raise FetchError("static_document_unavailable")
        if _date(response.observed_at) < _date(binding["configuration_updated_at"], microseconds=False):
            raise ValidationError("Original observation precedes its source configuration.")
        evidence = observer(body=response.body, body_complete=True, url=response.url, observed_at=response.observed_at)
        result = {"method_version": method, "state": "collected", "requested_url": target, "url": response.url,
            "observed_at": response.observed_at, "robots": robots_state, "source_sha256": binding["source_sha256"],
            "evidence": evidence, "interpretation": PAGE_INTERPRETATION if page else INTERPRETATION}
        checkpoint(response.url)
        if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > MAX_RESULT_BYTES:
            raise FetchError("competitor_document_result_limit")
    except FetchError as error:
        category = error.code if type(error.code) is str and error.code in ERRORS else "competitor_document_failed"
        result = {"method_version": method, "state": "unavailable", "error_category": category}
    except CrawlStopped:
        result = {"method_version": method, "state": "unavailable", "error_category": "competitor_document_deadline"}
    except (UnicodeError, ValidationError, ValueError, RecursionError):
        result = {"method_version": method, "state": "unavailable", "error_category": "competitor_document_invalid"}
    current()
    if result["state"] == "collected" and clock() >= deadline:
        return {"method_version": method, "state": "unavailable", "error_category": "competitor_document_deadline"}
    return result
