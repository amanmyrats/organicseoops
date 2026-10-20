"""Fixed-host Paddle Billing transport; callers own checkout attempt/reconciliation state."""

import http.client
import json
import re
import ssl
import time

from django.core.exceptions import ValidationError

from integrations.search_console_transport import _reject_constant, _unique_object
from jobs.crawling import (FetchDenied, FetchError, FetchLimitExceeded, _connection_factory,
                           _host_header, _read_body, _remaining, _resolve_public_addresses,
                           _set_socket_timeout, _system_resolver)

from .models import PaddleEnvironment
from .paddle_checkout import checkout_transaction_body
from .paddle_seller import _api_key, _catalog_id


HOSTS = {PaddleEnvironment.SANDBOX: "sandbox-api.paddle.com", PaddleEnvironment.LIVE: "api.paddle.com"}


class PaddleTransportError(Exception):
    def __init__(self, category):
        self.category = category
        super().__init__(category)


def paddle_price_get(*, environment, price_id, api_key, resolver=_system_resolver,
                     connection_factory=_connection_factory, clock=time.monotonic, timeout=10):
    _catalog_id(price_id, "pri")
    return _paddle_json(environment=environment, api_key=api_key,
                        path=f"/prices/{price_id}?include=product", body=None, limit=64 * 1024,
                        resolver=resolver, connection_factory=connection_factory, clock=clock, timeout=timeout)


def paddle_transaction_create(*, environment, api_key, attempt, resolver=_system_resolver,
                              connection_factory=_connection_factory, clock=time.monotonic, timeout=10):
    if attempt.state != attempt.State.SENDING or attempt.sent_at is None or attempt.environment != environment:
        raise ValidationError("A durable attempted checkout is required before contacting Paddle.")
    body = json.dumps(checkout_transaction_body(organization_id=attempt.organization_id,
        price_id=attempt.price_id, attempt_id=attempt.pk), separators=(",", ":")).encode()
    return _paddle_json(environment=environment, api_key=api_key, path="/transactions", body=body,
                        limit=128 * 1024, resolver=resolver, connection_factory=connection_factory,
                        clock=clock, timeout=timeout)


def paddle_subscription_get(*, environment, subscription_id, api_key, resolver=_system_resolver,
                            connection_factory=_connection_factory, clock=time.monotonic, timeout=10):
    if type(subscription_id) is not str or not re.fullmatch(r"sub_[a-z0-9]{26}", subscription_id):
        raise ValidationError("Choose a bounded provider subscription.")
    return _paddle_json(environment=environment, api_key=api_key,
                        path=f"/subscriptions/{subscription_id}", body=None, limit=128 * 1024,
                         resolver=resolver, connection_factory=connection_factory, clock=clock, timeout=timeout)


def paddle_subscription_cancel(*, attempt, api_key, resolver=_system_resolver,
                               connection_factory=_connection_factory, clock=time.monotonic, timeout=10):
    if (attempt.state != attempt.State.SENDING or attempt.attempted_at is None
        or not attempt.organization.closed_at or not attempt.organization.is_suspended
        or attempt.environment != attempt.subscription.environment
        or attempt.provider_subscription_id != attempt.subscription.subscription_id
        or attempt.customer_id != attempt.subscription.customer_id):
        raise ValidationError("A committed closed-organization cancellation attempt is required.")
    return _paddle_json(environment=attempt.environment, api_key=api_key,
                         path=f"/subscriptions/{attempt.provider_subscription_id}/cancel",
                         body=b'{"effective_from":"immediately"}', limit=128 * 1024,
                         resolver=resolver, connection_factory=connection_factory, clock=clock,
                         timeout=timeout, success_status=200)


def paddle_transaction_get(*, environment, transaction_id, api_key, resolver=_system_resolver,
                           connection_factory=_connection_factory, clock=time.monotonic, timeout=10):
    if type(transaction_id) is not str or not re.fullmatch(r"txn_[a-z0-9]{26}", transaction_id):
        raise ValidationError("Choose a bounded provider transaction.")
    return _paddle_json(environment=environment, api_key=api_key,
                        path=f"/transactions/{transaction_id}", body=None, limit=128 * 1024,
                        resolver=resolver, connection_factory=connection_factory, clock=clock, timeout=timeout)


def paddle_adjustment_get(*, environment, adjustment_id, api_key, resolver=_system_resolver,
                          connection_factory=_connection_factory, clock=time.monotonic, timeout=10):
    if type(adjustment_id) is not str or not re.fullmatch(r"adj_[a-z0-9]{26}", adjustment_id):
        raise ValidationError("Choose a bounded provider adjustment.")
    return _paddle_json(environment=environment, api_key=api_key,
                        path=f"/adjustments?id={adjustment_id}&per_page=1", body=None, limit=64 * 1024,
                        resolver=resolver, connection_factory=connection_factory, clock=clock, timeout=timeout)


def paddle_portal_create(*, environment, customer_id, subscription_id, api_key, resolver=_system_resolver,
                         connection_factory=_connection_factory, clock=time.monotonic, timeout=10):
    for prefix, value in (("ctm", customer_id), ("sub", subscription_id)):
        if type(value) is not str or not re.fullmatch(prefix + r"_[a-z0-9]{26}", value):
            raise ValidationError("Choose a bounded provider billing identity.")
    body = json.dumps({"subscription_ids": [subscription_id]}, separators=(",", ":")).encode()
    return _paddle_json(environment=environment, api_key=api_key,
                        path=f"/customers/{customer_id}/portal-sessions", body=body, limit=64 * 1024,
                        resolver=resolver, connection_factory=connection_factory, clock=clock, timeout=timeout)


def _paddle_json(*, environment, api_key, path, body, limit, resolver, connection_factory, clock, timeout,
                 success_status=None):
    if type(environment) is not str or environment not in HOSTS or type(timeout) not in (int, float) or not 1 <= timeout <= 20:
        raise ValidationError("Choose a configured Paddle catalog environment.")
    try:
        _api_key(api_key, environment)
    except ValidationError:
        raise PaddleTransportError("credential_unavailable")
    host = HOSTS[environment]
    deadline = clock() + timeout
    connection = None
    try:
        addresses = _resolve_public_addresses(host, 443, resolver=resolver, timeout=_remaining(deadline, clock))
        connection = connection_factory("https", addresses[0], host, 443, deadline, clock)
        headers = {
            "Host": _host_header(host, 443, "https"), "Authorization": f"Bearer {api_key}",
            "Paddle-Version": "1", "Accept": "application/json", "Accept-Encoding": "identity",
            "Connection": "close",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        connection.request("POST" if body is not None else "GET", path, body=body, headers=headers)
        _set_socket_timeout(connection, _remaining(deadline, clock))
        response = connection.getresponse()
        _set_socket_timeout(connection, _remaining(deadline, clock))
        if response.status != (success_status if success_status is not None else (201 if body is not None else 200)):
            category = ("redirect_denied" if response.status in (301, 302, 303, 307, 308)
                        else "authorization_unavailable" if response.status in (401, 403)
                        else "catalog_unavailable" if response.status == 404
                        else "quota_limited" if response.status == 429
                        else "provider_unavailable" if response.status >= 500
                        else "provider_request_rejected")
            raise PaddleTransportError(category)
        headers = {name.lower(): value.strip() for name, value in response.getheaders()}
        if headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise PaddleTransportError("malformed_response")
        raw = _read_body(response, headers, max_bytes=limit, deadline=deadline,
                         clock=clock, connection=connection)
        try:
            payload = json.loads(raw, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
        except (ValueError, UnicodeError, RecursionError):
            raise PaddleTransportError("malformed_response") from None
        if type(payload) is not dict:
            raise PaddleTransportError("malformed_response")
        return payload
    except PaddleTransportError:
        raise
    except FetchDenied:
        raise PaddleTransportError("egress_denied") from None
    except FetchLimitExceeded as error:
        raise PaddleTransportError(error.code) from None
    except TimeoutError:
        raise PaddleTransportError("timeout") from None
    except ssl.SSLCertVerificationError:
        raise PaddleTransportError("tls_verification_failed") from None
    except FetchError as error:
        raise PaddleTransportError(error.code) from None
    except (ssl.SSLError, OSError, http.client.HTTPException):
        raise PaddleTransportError("network_error") from None
    finally:
        if connection is not None:
            connection.close()
