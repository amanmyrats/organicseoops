"""Fixed GitHub OAuth/API hosts and exact operation shapes, no redirects or raw errors."""
import base64
import http.client
import json
import re
import ssl
import time
from urllib.parse import urlencode

from django.views.decorators.debug import sensitive_variables
from jobs.crawling import (FetchDenied, FetchError, FetchLimitExceeded, _connection_factory, _read_body,
    _remaining, _resolve_public_addresses, _set_socket_timeout, _system_resolver)
from .search_console_transport import _reject_constant, _unique_object


class RepositoryError(Exception):
    def __init__(self, category):
        self.category = category
        super().__init__(category)


@sensitive_variables()
def github_request(path, *, checkpoint, token=None, exchange=None, revoke=None, basic=None, before_send=None, response_limit=524288):
    if (type(response_limit) is not int or response_limit not in {524288, 1048576}
        or response_limit > 524288 and (exchange is not None or revoke is not None or not re.fullmatch(
            r"/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/git/blobs/[0-9a-f]{40}", path))):
        raise RepositoryError("invalid_response_limit")
    host, method, body = "api.github.com", "GET", None
    headers = {"Accept": "application/vnd.github+json", "Accept-Encoding": "identity", "Connection": "close",
        "User-Agent": "OrganicSEOOps-repository-readonly", "X-GitHub-Api-Version": "2026-03-10"}
    if exchange is not None:
        if path != "/login/oauth/access_token" or token or revoke or basic:
            raise RepositoryError("invalid_request")
        host, method = "github.com", "POST"
        body = urlencode(exchange).encode()
        headers.update({"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    elif revoke is not None:
        if not re.fullmatch(r"/applications/[A-Za-z0-9_.-]{1,128}/token", path) or token or type(basic) is not tuple or len(basic) != 2:
            raise RepositoryError("invalid_request")
        method, body = "DELETE", json.dumps({"access_token": revoke}).encode()
        headers.update({"Content-Type": "application/json", "Authorization": "Basic " + base64.b64encode((basic[0] + ":" + basic[1]).encode()).decode()})
    else:
        if (type(token) is not str or not re.fullmatch(r"ghu_[A-Za-z0-9_]{8,512}", token)
            or not re.fullmatch(r"/(?:user|user/installations\?per_page=100|repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/git/(?:commits|trees|blobs)/[0-9a-f]{40})?)", path)):
            raise RepositoryError("invalid_request")
        headers["Authorization"] = "Bearer " + token
    headers["Host"] = host
    deadline, connection = time.monotonic() + 15, None
    try:
        checkpoint()
        addresses = _resolve_public_addresses(host, 443, resolver=_system_resolver, timeout=_remaining(deadline, time.monotonic))
        checkpoint()
        connection = _connection_factory("https", addresses[0], host, 443, deadline, time.monotonic)
        connection.connect()
        _set_socket_timeout(connection, _remaining(deadline, time.monotonic))
        checkpoint()
        if before_send is not None:
            before_send()
        connection.request(method, path, body=body, headers=headers)
        _set_socket_timeout(connection, _remaining(deadline, time.monotonic))
        response = connection.getresponse()
        if method == "DELETE" and response.status == 204:
            return {"revoked": True}
        if response.status != 200:
            raise RepositoryError("authorization_unavailable" if response.status in {401, 403, 404} else
                "quota_limited" if response.status == 429 else "provider_unavailable")
        response_headers = {name.lower(): value.strip() for name, value in response.getheaders()}
        if response_headers.get("content-type", "").split(";", 1)[0].strip().lower() not in {"application/json", "application/vnd.github+json"}:
            raise RepositoryError("malformed_response")
        raw = _read_body(response, response_headers, max_bytes=response_limit, deadline=deadline, clock=time.monotonic, connection=connection)
        payload = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        if type(payload) is not dict:
            raise RepositoryError("malformed_response")
        return payload
    except RepositoryError:
        raise
    except FetchDenied:
        raise RepositoryError("egress_denied") from None
    except (FetchError, FetchLimitExceeded, TimeoutError, OSError, ssl.SSLError, http.client.HTTPException):
        raise RepositoryError("request_outcome_unknown") from None
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise RepositoryError("malformed_response") from None
    finally:
        if connection is not None:
            connection.close()
