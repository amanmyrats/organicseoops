"""One fixed-host paid request; no redirects, retries or result-page scraping."""
import base64
import http.client
import json
import ssl
import time

from django.views.decorators.debug import sensitive_variables

from integrations.search_console_transport import _reject_constant, _unique_object
from .crawling import (FetchDenied, FetchError, FetchLimitExceeded, _connection_factory, _read_body,
    _remaining, _resolve_public_addresses, _set_socket_timeout, _system_resolver)


class SerpError(Exception):
    def __init__(self, category):
        self.category = category
        super().__init__(category)


@sensitive_variables()
def collect_serp(data, credentials, *, checkpoint, before_send):
    host = "api.dataforseo.com"
    task = {"keyword": data["query"].replace("%", "%25").replace("+", "%2B"),
        "location_code": data["location_code"], "language_code": data["language_code"],
        "device": data["device"], "os": "windows" if data["device"] == "desktop" else "android",
        "depth": 10, "max_crawl_pages": 1, "load_async_ai_overview": False,
        "calculate_rectangles": False, "group_organic_results": True}
    body = json.dumps([task], ensure_ascii=False, allow_nan=False).encode()
    deadline, connection = time.monotonic() + 45, None
    try:
        checkpoint()
        addresses = _resolve_public_addresses(host, 443, resolver=_system_resolver, timeout=_remaining(deadline, time.monotonic))
        checkpoint()
        connection = _connection_factory("https", addresses[0], host, 443, deadline, time.monotonic)
        connection.connect()
        _set_socket_timeout(connection, _remaining(deadline, time.monotonic))
        before_send()  # Persist the unknown-charge boundary after DNS/TLS and fresh authority checks.
        authorization = base64.b64encode((credentials[0] + ":" + credentials[1]).encode()).decode()
        connection.request("POST", "/v3/serp/google/organic/live/advanced", body=body, headers={
            "Host": host, "Authorization": "Basic " + authorization, "Content-Type": "application/json",
            "Accept": "application/json", "Accept-Encoding": "identity", "Connection": "close"})
        _set_socket_timeout(connection, _remaining(deadline, time.monotonic))
        response = connection.getresponse()
        if response.status != 200:
            raise SerpError("quota_limited" if response.status == 429 else "authorization_unavailable"
                if response.status in {401, 403} else "request_outcome_unknown")
        headers = {name.lower(): value.strip() for name, value in response.getheaders()}
        if headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise SerpError("malformed_response")
        raw = _read_body(response, headers, max_bytes=1048576, deadline=deadline, clock=time.monotonic, connection=connection)
        checkpoint()
        payload = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        if type(payload) is not dict:
            raise SerpError("malformed_response")
        return payload
    except SerpError:
        raise
    except FetchDenied:
        raise SerpError("egress_denied") from None
    except (FetchError, FetchLimitExceeded, TimeoutError, OSError, ssl.SSLError, http.client.HTTPException):
        raise SerpError("request_outcome_unknown") from None
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise SerpError("malformed_response") from None
    finally:
        if connection is not None:
            connection.close()
