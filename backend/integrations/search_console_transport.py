import http.client
import json
import ssl
import time
from datetime import date, timedelta
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.utils import timezone

from jobs.crawling import (
    FetchDenied, FetchError, FetchLimitExceeded, _connection_factory, _host_header, _read_body,
    _remaining, _resolve_public_addresses, _set_socket_timeout, _system_resolver,
)

from .google_tokens import _credential
from .models import GoogleOAuthGrant, normalize_external_property, verified_domain_origins
from .services import require_connection_capability
from .search_console import _RowError, _normalize_property_page


HOST = "www.googleapis.com"
INSPECTION_HOST = "searchconsole.googleapis.com"
ANALYTICS_ADMIN_HOST = "analyticsadmin.googleapis.com"
ANALYTICS_DATA_HOST = "analyticsdata.googleapis.com"
BUSINESS_ACCOUNT_HOST = "mybusinessaccountmanagement.googleapis.com"
BUSINESS_INFORMATION_HOST = "mybusinessbusinessinformation.googleapis.com"
BUSINESS_REVIEW_HOST = "mybusiness.googleapis.com"


class SearchConsoleTransportError(Exception):
    def __init__(self, category, *, retryable=False):
        self.category = category
        self.retryable = retryable
        super().__init__(category)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError


def google_sites_list(*, access_token, resolver=_system_resolver, connection_factory=_connection_factory,
                      clock=time.monotonic, timeout=10):
    return _google_json("/webmasters/v3/sites", access_token=access_token, limit=256 * 1024,
                             resolver=resolver, connection_factory=connection_factory, clock=clock, timeout=timeout)


def google_site_get(*, site_url, access_token, resolver=_system_resolver, connection_factory=_connection_factory,
                    clock=time.monotonic, timeout=10):
    if not isinstance(site_url, str) or len(site_url) > 512 or site_url.strip() != site_url:
        raise ValidationError("Choose a bounded Search Console property.")
    normalize_external_property("google_search_console", site_url)
    return _google_json("/webmasters/v3/sites/" + quote(site_url, safe=""), access_token=access_token, limit=4096,
                              resolver=resolver, connection_factory=connection_factory, clock=clock, timeout=timeout)


def google_search_analytics_query(*, connection, access_token, day, dimension, start_row=0,
                                  resolver=_system_resolver, connection_factory=_connection_factory,
                                  clock=time.monotonic, timeout=10):
    if type(day) is not date or type(dimension) is not str or dimension not in {"date", "query", "page"} or type(start_row) is not int or start_row not in {0, 100}:
        raise ValidationError("Choose a bounded finalized Search Console report page.")
    today = timezone.now().astimezone(ZoneInfo("America/Los_Angeles")).date()
    if not today - timedelta(days=90) <= day <= today - timedelta(days=3):
        raise ValidationError("Choose a finalized date within the bounded Search Console backfill window.")
    connection = require_connection_capability(connection, "api_sync", dimensions=(dimension,))
    grant = GoogleOAuthGrant.objects.filter(
        project_id=connection.project_id, credential_reference=connection.credential_reference,
        selected_property_id=connection.external_property_id, state=GoogleOAuthGrant.State.ACTIVE,
    ).first() if connection.credential_reference else None
    if grant is None or normalize_external_property("google_search_console", grant.selected_site_url) != connection.external_property_id:
        raise ValidationError("Search Console authorization is unavailable for this project property.")
    if connection.external_property_id.startswith("sc-domain:") and (
        dimension != "page" or not set(grant.selected_origins) & set(verified_domain_origins(
            connection.project, connection.external_property_id))):
        raise ValidationError("Domain reports require currently verified exact page origins.")
    body = json.dumps({
        "startDate": day.isoformat(), "endDate": day.isoformat(), "dimensions": [dimension],
        "type": "web", "aggregationType": "byPage" if dimension == "page" else "byProperty",
        "dataState": "final", "rowLimit": 100, "startRow": start_row,
    }, separators=(",", ":")).encode()
    return _google_json(
        "/webmasters/v3/sites/" + quote(grant.selected_site_url, safe="") + "/searchAnalytics/query",
        access_token=access_token, limit=256 * 1024, resolver=resolver, connection_factory=connection_factory,
        clock=clock, timeout=timeout, body=body,
    )


def _scoped_site(connection):
    connection = require_connection_capability(connection, "api_sync")
    grant = GoogleOAuthGrant.objects.filter(
        project_id=connection.project_id, credential_reference=connection.credential_reference,
        selected_property_id=connection.external_property_id, state=GoogleOAuthGrant.State.ACTIVE,
    ).first() if connection.credential_reference else None
    if grant is None or normalize_external_property("google_search_console", grant.selected_site_url) != connection.external_property_id:
        raise ValidationError("Search Console authorization is unavailable for this project property.")
    if connection.external_property_id.startswith("sc-domain:"):
        approved = sorted(set(grant.selected_origins) & set(verified_domain_origins(
            connection.project, connection.external_property_id)))
    else:
        approved = [connection.external_property_id]
    if not approved:
        raise ValidationError("Verified project origin scope is unavailable.")
    return grant, approved


def google_search_analytics_query_page(*, connection, access_token, day, start_row=0,
                                     resolver=_system_resolver, connection_factory=_connection_factory,
                                     clock=time.monotonic, timeout=10):
    """Explicit same-row report, never reinterpret the independent dimension list."""
    today = timezone.now().astimezone(ZoneInfo("America/Los_Angeles")).date()
    if (type(day) is not date or not today - timedelta(days=90) <= day <= today - timedelta(days=3)
        or type(start_row) is not int or start_row not in {0, 100}):
        raise ValidationError("Choose one bounded finalized paired report page.")
    connection = require_connection_capability(connection, "api_sync", dimensions=["query", "page"])
    if (connection.provider != "google_search_console" or connection.external_property_id.startswith("sc-domain:")
        or not {"query_metrics", "page_metrics"} <= set(connection.capabilities)
        or connection.timezone != "America/Los_Angeles"):
        raise ValidationError("Paired reports require a URL-prefix query and page source.")
    grant, _approved = _scoped_site(connection)
    body = json.dumps({"startDate": day.isoformat(), "endDate": day.isoformat(), "dimensions": ["query", "page"],
        "type": "web", "aggregationType": "auto", "dataState": "final", "rowLimit": 100,
        "startRow": start_row}, separators=(",", ":")).encode()
    return _google_json("/webmasters/v3/sites/" + quote(grant.selected_site_url, safe="") + "/searchAnalytics/query",
        access_token=access_token, limit=256 * 1024, resolver=resolver, connection_factory=connection_factory,
        clock=clock, timeout=timeout, body=body)


def google_sitemaps_list(*, connection, access_token, resolver=_system_resolver,
                         connection_factory=_connection_factory, clock=time.monotonic, timeout=10):
    grant, _approved = _scoped_site(connection)
    return _google_json("/webmasters/v3/sites/" + quote(grant.selected_site_url, safe="") + "/sitemaps",
                             access_token=access_token, limit=64 * 1024, resolver=resolver,
                             connection_factory=connection_factory, clock=clock, timeout=timeout)


def google_url_inspection(*, connection, inspection_url, access_token, resolver=_system_resolver,
                          connection_factory=_connection_factory, clock=time.monotonic, timeout=10):
    grant, approved = _scoped_site(connection)
    try:
        parsed = urlsplit(inspection_url) if type(inspection_url) is str else None
    except ValueError:
        parsed = None
    if parsed is None or not 1 <= len(inspection_url) <= 2048 or parsed.query or parsed.fragment:
        raise ValidationError("Choose an exact project-owned URL without parameters or fragments.")
    scoped_url = None
    for origin in approved:
        try:
            scoped_url = _normalize_property_page(inspection_url, origin)
            break
        except (_RowError, ValueError):
            continue
    if scoped_url is None:
        raise ValidationError("URL Inspection is unavailable outside the selected project origin.")
    body = json.dumps({"inspectionUrl": scoped_url, "siteUrl": grant.selected_site_url},
                      separators=(",", ":")).encode()
    return _google_json("/v1/urlInspection/index:inspect", access_token=access_token, limit=64 * 1024,
                             resolver=resolver, connection_factory=connection_factory, clock=clock, timeout=timeout,
                             body=body, host=INSPECTION_HOST)


def _google_json(path, *, access_token, limit, resolver, connection_factory, clock, timeout, body=None, host=HOST):
    _credential(access_token)
    if type(timeout) not in {int, float} or not 1 <= timeout <= 30 or host not in {
        HOST, INSPECTION_HOST, ANALYTICS_ADMIN_HOST, ANALYTICS_DATA_HOST,
        BUSINESS_ACCOUNT_HOST, BUSINESS_INFORMATION_HOST, BUSINESS_REVIEW_HOST,
    }:
        raise SearchConsoleTransportError("invalid_request")
    deadline = clock() + timeout
    connection = None
    try:
        addresses = _resolve_public_addresses(host, 443, resolver=resolver, timeout=_remaining(deadline, clock))
        connection = connection_factory("https", addresses[0], host, 443, deadline, clock)
        headers = {
            "Host": _host_header(host, 443, "https"), "Authorization": f"Bearer {access_token}",
            "Accept": "application/json", "Accept-Encoding": "identity", "Connection": "close",
        }
        if body is None:
            connection.request("GET", path, headers=headers)
        else:
            headers["Content-Type"] = "application/json"
            connection.request("POST", path, body=body, headers=headers)
        _set_socket_timeout(connection, _remaining(deadline, clock))
        response = connection.getresponse()
        _set_socket_timeout(connection, _remaining(deadline, clock))
        if response.status != 200:
            status = response.status
            if status in {301, 302, 303, 307, 308}:
                raise SearchConsoleTransportError("redirect_denied")
            if status in {401, 403}:
                raise SearchConsoleTransportError("authorization_unavailable")
            if status == 404:
                raise SearchConsoleTransportError("property_unavailable")
            if status == 429:
                raise SearchConsoleTransportError("quota_limited", retryable=True)
            raise SearchConsoleTransportError("provider_unavailable" if status >= 500 else "provider_request_rejected",
                                              retryable=status >= 500 or status == 408)
        headers = {name.lower(): value.strip() for name, value in response.getheaders()}
        if headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise SearchConsoleTransportError("malformed_response")
        raw = _read_body(response, headers, max_bytes=limit, deadline=deadline, clock=clock, connection=connection)
        try:
            payload = json.loads(raw, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
        except (ValueError, UnicodeError, RecursionError):
            raise SearchConsoleTransportError("malformed_response") from None
        if type(payload) is not dict:
            raise SearchConsoleTransportError("malformed_response")
        return payload
    except SearchConsoleTransportError:
        raise
    except FetchDenied:
        raise SearchConsoleTransportError("egress_denied") from None
    except FetchLimitExceeded as error:
        raise SearchConsoleTransportError(error.code, retryable=error.code == "timeout") from None
    except TimeoutError:
        raise SearchConsoleTransportError("timeout", retryable=True) from None
    except ssl.SSLCertVerificationError:
        raise SearchConsoleTransportError("tls_verification_failed") from None
    except FetchError as error:
        raise SearchConsoleTransportError(error.code, retryable=error.code in {"dns_error", "network_error"}) from None
    except (ssl.SSLError, OSError, http.client.HTTPException):
        raise SearchConsoleTransportError("network_error", retryable=True) from None
    except (ValueError, TypeError, UnicodeError):
        raise SearchConsoleTransportError("invalid_request") from None
    finally:
        if connection is not None:
            connection.close()
