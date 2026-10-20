import http.client
import json
import re
import ssl
import time
from urllib.parse import urlencode, urlsplit

from django.core.exceptions import ValidationError

from tenancy.models import Project

from .crawling import (
    FetchDenied, FetchError, FetchLimitExceeded, _connection_factory, _host_header,
    _read_body, _remaining, _resolve_public_addresses, _resource_response_headers, _set_socket_timeout, _system_resolver,
)
from .performance import CRUX_METRICS, _scoped_url, parse_crux, parse_pagespeed_lab


HOSTS = {"psi_lab": "pagespeedonline.googleapis.com", "crux_current": "chromeuxreport.googleapis.com",
         "crux_history": "chromeuxreport.googleapis.com"}
PATHS = {"psi_lab": "/pagespeedonline/v5/runPagespeed", "crux_current": "/v1/records:queryRecord",
         "crux_history": "/v1/records:queryHistoryRecord"}
LIMITS = {"psi_lab": 2 * 1024 * 1024, "crux_current": 256 * 1024, "crux_history": 256 * 1024}
_API_KEY = re.compile(r"[A-Za-z0-9_-]{20,200}\Z")


def _reject_json_constant(_value):
    raise ValueError


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


class PerformanceTransportError(Exception):
    def __init__(self, category, *, retryable=False):
        self.category = category
        self.retryable = retryable
        super().__init__(category)


def google_performance_request(*, project, kind, target, strategy, grain, api_key, timeout=30,
                               resolver=_system_resolver, connection_factory=_connection_factory,
                               clock=time.monotonic, checkpoint=None):
    if kind not in HOSTS or strategy not in {"mobile", "desktop", "tablet"} or grain not in {"page", "origin"}:
        raise ValidationError("Choose a supported performance report and device.")
    if kind == "psi_lab" and (strategy == "tablet" or grain != "page"):
        raise ValidationError("PageSpeed lab audits require a desktop or mobile page.")
    if grain == "origin" and (not isinstance(target, str) or urlsplit(target).path not in {"", "/"}):
        raise ValidationError("CrUX origin requests cannot contain page paths.")
    project = Project.objects.get(pk=project.pk, organization_id=project.organization_id)
    target = _scoped_url(project, target, origin=grain == "origin")
    if type(timeout) not in {int, float} or not 1 <= timeout <= 60:
        raise ValidationError("Choose a bounded performance request timeout.")
    if not isinstance(api_key, str) or not _API_KEY.fullmatch(api_key):
        raise PerformanceTransportError("credential_unavailable")
    data = _google_performance_response(kind=kind, target=target, strategy=strategy, grain=grain, api_key=api_key,
        timeout=timeout, resolver=resolver, connection_factory=connection_factory, clock=clock, checkpoint=checkpoint)
    try:
        payload = json.loads(data, parse_constant=_reject_json_constant, object_pairs_hook=_unique_json_object)
    except (ValueError, UnicodeError, RecursionError):
        raise PerformanceTransportError("malformed_response") from None
    if type(payload) is not dict:
        raise PerformanceTransportError("malformed_response")
    return payload


def _google_performance_response(*, kind, target, strategy, grain, api_key, timeout, resolver, connection_factory,
                                 clock, checkpoint=None, before_send=None, complete=False, deadline=None):
    """Shared fixed Google wire; protected callers opt into connected/send and full framing fences."""
    host = HOSTS[kind]
    method = "GET" if kind == "psi_lab" else "POST"
    path = PATHS[kind]
    body = None
    if kind == "psi_lab":
        path += "?" + urlencode({"url": target, "strategy": strategy, "category": "PERFORMANCE"})
    else:
        request = {
            "origin" if grain == "origin" else "url": target,
            "formFactor": {"mobile": "PHONE", "desktop": "DESKTOP", "tablet": "TABLET"}[strategy],
            "metrics": list(CRUX_METRICS),
        }
        if kind == "crux_history":
            request["collectionPeriodCount"] = 40
        body = json.dumps(request, separators=(",", ":"), allow_nan=False).encode()
    deadline = clock() + timeout if deadline is None else deadline
    connection = None
    try:
        if checkpoint is not None: checkpoint()
        addresses = _resolve_public_addresses(host, 443, resolver=resolver, timeout=_remaining(deadline, clock))
        if checkpoint is not None: checkpoint()
        _remaining(deadline, clock)
        connection = connection_factory("https", addresses[0], host, 443, deadline, clock)
        if checkpoint is not None:
            connection.connect()
            checkpoint()
        _remaining(deadline, clock)
        if before_send is not None: before_send()
        _remaining(deadline, clock)
        connection.request(method, path, body=body, headers={
            "Host": _host_header(host, 443, "https"), "X-goog-api-key": api_key,
            "Accept": "application/json", "Content-Type": "application/json",
            "Accept-Encoding": "identity", "Connection": "close",
        })
        _set_socket_timeout(connection, _remaining(deadline, clock))
        response = connection.getresponse()
        _set_socket_timeout(connection, _remaining(deadline, clock))
        status = response.status
        if not 200 <= status < 300:
            if status == 404 and kind != "psi_lab":
                raise PerformanceTransportError("field_data_unavailable")
            if status == 429:
                raise PerformanceTransportError("quota_limited", retryable=True)
            if status in {301, 302, 303, 307, 308}:
                raise PerformanceTransportError("redirect_denied")
            raise PerformanceTransportError("provider_unavailable" if status >= 500 else "provider_request_rejected",
                                            retryable=status >= 500 or status == 408)
        headers = {name.lower(): value.strip() for name, value in response.getheaders()}
        if headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise PerformanceTransportError("malformed_response")
        if complete:
            headers = _resource_response_headers(response, media_type="application/json")
        if checkpoint is not None: checkpoint()
        _remaining(deadline, clock)
        data = _read_body(response, headers, max_bytes=LIMITS[kind], deadline=deadline,
                          clock=clock, connection=connection, require_complete=complete)
        if checkpoint is not None: checkpoint()
        _remaining(deadline, clock)
        return data
    except PerformanceTransportError:
        raise
    except FetchDenied:
        raise PerformanceTransportError("egress_denied") from None
    except FetchLimitExceeded as error:
        raise PerformanceTransportError(error.code, retryable=error.code == "timeout") from None
    except TimeoutError:
        raise PerformanceTransportError("timeout", retryable=True) from None
    except ssl.SSLCertVerificationError:
        raise PerformanceTransportError("tls_verification_failed") from None
    except FetchError as error:
        raise PerformanceTransportError(error.code, retryable=error.code in {"dns_error", "network_error"}) from None
    except (ssl.SSLError, OSError, http.client.HTTPException):
        raise PerformanceTransportError("network_error", retryable=True) from None
    except (TypeError, ValueError, UnicodeError):
        raise PerformanceTransportError("malformed_response") from None
    finally:
        if connection is not None:
            connection.close()


def collect_performance(*, project, target, kind, strategy, grain, api_key, transport=google_performance_request):
    if kind not in HOSTS or strategy not in {"mobile", "desktop", "tablet"} or grain not in {"page", "origin"}:
        raise ValidationError("Choose a supported performance operation.")
    if kind == "psi_lab" and (grain != "page" or strategy == "tablet"):
        raise ValidationError("PageSpeed lab audits require a desktop or mobile page.")
    if grain == "origin" and (not isinstance(target, str) or urlsplit(target).path not in {"", "/"}):
        raise ValidationError("CrUX origin requests cannot contain page paths.")
    project = Project.objects.get(pk=project.pk, organization_id=project.organization_id)
    normalized = _scoped_url(project, target, origin=grain == "origin")
    payload = transport(project=project, kind=kind, target=normalized, strategy=strategy, grain=grain, api_key=api_key)
    if kind == "psi_lab":
        return parse_pagespeed_lab(project=project, requested_url=normalized, strategy=strategy, payload=payload)
    return parse_crux(project=project, requested_url=normalized, requested_grain=grain,
                      form_factor={"mobile": "PHONE", "desktop": "DESKTOP", "tablet": "TABLET"}[strategy],
                      payload=payload, history=kind == "crux_history")
