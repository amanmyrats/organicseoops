import http.client
import json
import re
import ssl
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlencode

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.utils import timezone

from jobs.crawling import (
    FetchDenied, FetchError, FetchLimitExceeded, _connection_factory, _host_header, _read_body,
    _remaining, _resolve_public_addresses, _set_socket_timeout, _system_resolver,
)

from .oauth import configured_redirect_uri


HOST = "oauth2.googleapis.com"
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
_SECRET = re.compile(r"[\x21-\x7e]{1,4096}\Z")


class GoogleTokenError(Exception):
    def __init__(self, category, *, retryable=False):
        self.category = category
        self.retryable = retryable
        super().__init__(category)


@dataclass(frozen=True, repr=False)
class GoogleTokens:
    access_token: str
    refresh_token: str | None
    expires_at: datetime


def _credential(value, *, limit=4096):
    if not isinstance(value, str) or len(value) > limit or not _SECRET.fullmatch(value):
        raise GoogleTokenError("credential_unavailable")
    return value


def _cipher():
    keys = getattr(settings, "GOOGLE_OAUTH_ENCRYPTION_KEYS", ())
    if type(keys) not in {tuple, list} or not 1 <= len(keys) <= 5:
        raise GoogleTokenError("credential_unavailable")
    try:
        return MultiFernet([Fernet(key.encode()) for key in keys])
    except (ValueError, TypeError, AttributeError):
        raise GoogleTokenError("credential_unavailable") from None


def encrypt_refresh_token(token):
    _credential(token)
    return "v1:" + _cipher().encrypt(token.encode()).decode()


def decrypt_refresh_token(encrypted):
    if not isinstance(encrypted, str) or not encrypted.startswith("v1:") or len(encrypted) > 8192:
        raise GoogleTokenError("credential_unavailable")
    try:
        return _cipher().decrypt(encrypted[3:].encode()).decode()
    except (InvalidToken, ValueError, UnicodeError):
        raise GoogleTokenError("credential_unavailable") from None


def rotate_refresh_token(encrypted):
    if not isinstance(encrypted, str) or not encrypted.startswith("v1:") or len(encrypted) > 8192:
        raise GoogleTokenError("credential_unavailable")
    try:
        return "v1:" + _cipher().rotate(encrypted[3:].encode()).decode()
    except (InvalidToken, ValueError):
        raise GoogleTokenError("credential_unavailable") from None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError


def post_google_token_form(*, form, resolver=_system_resolver, connection_factory=_connection_factory,
                           clock=time.monotonic, timeout=10):
    return _post_google_form(form=form, kind="token", resolver=resolver, connection_factory=connection_factory,
                             clock=clock, timeout=timeout)


def post_google_revoke_form(*, token, resolver=_system_resolver, connection_factory=_connection_factory,
                            clock=time.monotonic, timeout=10):
    _credential(token)
    return _post_google_form(form={"token": token}, kind="revoke", resolver=resolver,
                             connection_factory=connection_factory, clock=clock, timeout=timeout)


def _post_google_form(*, form, kind, resolver, connection_factory, clock, timeout):
    if type(form) is not dict or not 1 <= len(form) <= 5 or any(
        not isinstance(key, str) or not isinstance(value, str) for key, value in form.items()
    ) or kind not in {"token", "revoke"} or type(timeout) not in {int, float} or not 1 <= timeout <= 30:
        raise GoogleTokenError("invalid_request")
    body = urlencode(form).encode()
    if len(body) > 16384:
        raise GoogleTokenError("invalid_request")
    deadline = clock() + timeout
    connection = None
    try:
        addresses = _resolve_public_addresses(HOST, 443, resolver=resolver, timeout=_remaining(deadline, clock))
        connection = connection_factory("https", addresses[0], HOST, 443, deadline, clock)
        connection.request("POST", "/token" if kind == "token" else "/revoke", body=body, headers={
            "Host": _host_header(HOST, 443, "https"),
            "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json",
            "Accept-Encoding": "identity", "Connection": "close",
        })
        _set_socket_timeout(connection, _remaining(deadline, clock))
        response = connection.getresponse()
        _set_socket_timeout(connection, _remaining(deadline, clock))
        if response.status != 200:
            status = response.status
            if status in {301, 302, 303, 307, 308}:
                raise GoogleTokenError("redirect_denied")
            if status == 429:
                raise GoogleTokenError("quota_limited", retryable=True)
            raise GoogleTokenError("provider_unavailable" if status >= 500 else
                                   "authorization_rejected" if kind == "token" else "revocation_rejected",
                                   retryable=status >= 500 or status == 408)
        headers = {name.lower(): value.strip() for name, value in response.getheaders()}
        if kind == "revoke":
            _read_body(response, headers, max_bytes=1024, deadline=deadline, clock=clock, connection=connection)
            return True
        if headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise GoogleTokenError("malformed_response")
        raw = _read_body(response, headers, max_bytes=32768, deadline=deadline, clock=clock, connection=connection)
        try:
            payload = json.loads(raw, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise GoogleTokenError("malformed_response") from None
        if type(payload) is not dict:
            raise GoogleTokenError("malformed_response")
        return payload
    except GoogleTokenError:
        raise
    except FetchDenied:
        raise GoogleTokenError("egress_denied") from None
    except FetchLimitExceeded as error:
        raise GoogleTokenError(error.code, retryable=error.code == "timeout") from None
    except TimeoutError:
        raise GoogleTokenError("timeout", retryable=True) from None
    except ssl.SSLCertVerificationError:
        raise GoogleTokenError("tls_verification_failed") from None
    except FetchError as error:
        raise GoogleTokenError(error.code, retryable=error.code in {"dns_error", "network_error"}) from None
    except (ssl.SSLError, OSError, http.client.HTTPException):
        raise GoogleTokenError("network_error", retryable=True) from None
    except (TypeError, ValueError, UnicodeError):
        raise GoogleTokenError("invalid_request") from None
    finally:
        if connection is not None:
            connection.close()


def _parse_tokens(payload, *, needs_refresh, expected_scope=SCOPE):
    if type(payload) is not dict or payload.get("token_type") != "Bearer":
        raise GoogleTokenError("malformed_response")
    scopes = payload.get("scope")
    if not isinstance(scopes, str) or set(scopes.split()) != {expected_scope}:
        raise GoogleTokenError("scope_unavailable")
    try:
        access = _credential(payload.get("access_token"))
        refresh = payload.get("refresh_token")
        if refresh is not None:
            refresh = _credential(refresh)
    except GoogleTokenError:
        raise GoogleTokenError("malformed_response") from None
    if needs_refresh and refresh is None:
        raise GoogleTokenError("reauthorization_required")
    seconds = payload.get("expires_in")
    if type(seconds) is not int or not 1 <= seconds <= 86400:
        raise GoogleTokenError("malformed_response")
    return GoogleTokens(access_token=access, refresh_token=refresh,
                        expires_at=timezone.now() + timedelta(seconds=max(0, seconds - 60)))


def exchange_google_code(*, code, client_id, client_secret, transport=post_google_token_form):
    _credential(code, limit=2048)
    _credential(client_id, limit=512)
    _credential(client_secret, limit=512)
    form = {"code": code, "client_id": client_id, "client_secret": client_secret,
            "grant_type": "authorization_code", "redirect_uri": configured_redirect_uri()}
    return _parse_tokens(transport(form=form), needs_refresh=True)


def refresh_google_tokens(*, encrypted_refresh, client_id, client_secret, transport=post_google_token_form):
    _credential(client_id, limit=512)
    _credential(client_secret, limit=512)
    refresh = decrypt_refresh_token(encrypted_refresh)
    form = {"refresh_token": refresh, "client_id": client_id, "client_secret": client_secret,
            "grant_type": "refresh_token"}
    return _parse_tokens(transport(form=form), needs_refresh=False)


def revoke_google_tokens(*, encrypted_refresh, transport=post_google_revoke_form):
    return transport(token=decrypt_refresh_token(encrypted_refresh))
