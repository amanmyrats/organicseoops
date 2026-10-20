"""Fixed Yandex hosts, pinned public DNS/TLS, bounded JSON and categorical errors."""
import http.client
import json
import ssl
import time
from urllib.parse import urlencode
from django.views.decorators.debug import sensitive_variables

from jobs.crawling import (FetchDenied, FetchError, FetchLimitExceeded, _connection_factory, _host_header,
    _read_body, _remaining, _resolve_public_addresses, _set_socket_timeout, _system_resolver)
from .search_console_transport import _reject_constant, _unique_object


class YandexError(Exception):
    def __init__(self, category):
        self.category = category
        super().__init__(category)


@sensitive_variables()
def yandex_json(path, *, token=None, form=None, checkpoint, limit=262144):
    host = "oauth.yandex.ru" if form is not None else "api.webmaster.yandex.net"
    if (type(path) is not str or not path.startswith("/") or path.startswith("//")
        or any(ord(c) < 33 or ord(c) > 126 for c in path)
        or form is not None and path not in {"/token", "/revoke_token"}
        or form is None and not path.startswith("/v4/user") or not callable(checkpoint)):
        raise YandexError("invalid_request")
    from .yandex_oauth import credential
    if form is None:
        credential(token)
    body = urlencode(form).encode() if form is not None else None
    deadline = time.monotonic() + 15
    connection = None
    try:
        checkpoint()
        addresses = _resolve_public_addresses(host, 443, resolver=_system_resolver, timeout=_remaining(deadline, time.monotonic))
        checkpoint()
        connection = _connection_factory("https", addresses[0], host, 443, deadline, time.monotonic)
        connection.connect()
        _set_socket_timeout(connection, _remaining(deadline, time.monotonic))
        checkpoint()
        headers = {"Host": _host_header(host, 443, "https"), "Accept": "application/json",
            "Accept-Encoding": "identity", "Connection": "close"}
        if body is None:
            headers["Authorization"] = "OAuth " + token
        else:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        connection.request("GET" if body is None else "POST", path, body=body, headers=headers)
        _set_socket_timeout(connection, _remaining(deadline, time.monotonic))
        response = connection.getresponse()
        if response.status != 200:
            raise YandexError("redirect_denied" if 300 <= response.status < 400 else
                "authorization_unavailable" if response.status in {400, 401, 403} else
                "quota_limited" if response.status == 429 else "provider_unavailable")
        headers = {name.lower(): value.strip() for name, value in response.getheaders()}
        if headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise YandexError("malformed_response")
        raw = _read_body(response, headers, max_bytes=limit, deadline=deadline, clock=time.monotonic, connection=connection)
        payload = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        if type(payload) is not dict:
            raise YandexError("malformed_response")
        return payload
    except YandexError:
        raise
    except FetchDenied:
        raise YandexError("egress_denied") from None
    except (FetchError, FetchLimitExceeded, TimeoutError, OSError, ssl.SSLError, http.client.HTTPException):
        raise YandexError("network_unavailable") from None
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise YandexError("malformed_response") from None
    finally:
        if connection is not None:
            connection.close()
