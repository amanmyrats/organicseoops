"""Protected fixed-host PSI wire; caller supplies current source/key/robots/commercial gates."""
import time
from urllib.parse import urlsplit

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from .competitor_lab import observe_pagespeed_lab, _url
from .crawling import FetchDenied, FetchError, _connection_factory, _remaining, _resolve_public_addresses, _system_resolver
from .performance_transport import PerformanceTransportError, _API_KEY, _google_performance_response


METHOD = "competitor-lighthouse-transport-v1"


def request_competitor_lab(*, url, strategy, api_key, checkpoint, before_send, timeout=30,
                          resolver=_system_resolver, connection_factory=_connection_factory, clock=time.monotonic, _deadline=None):
    if (type(strategy) is not str or strategy not in {"mobile", "desktop"}
        or type(timeout) not in {int, float} or not 1 <= timeout <= 30):
        raise ValidationError("Select one bounded mobile or desktop Lighthouse request.")
    _url(url)
    if not callable(checkpoint) or not callable(before_send): raise PermissionDenied
    if type(api_key) is not str or not _API_KEY.fullmatch(api_key):
        raise PerformanceTransportError("credential_unavailable")
    if _deadline is not None and type(_deadline) not in {int, float}: raise ValidationError("Choose a bounded Lighthouse deadline.")
    deadline = clock() + timeout if _deadline is None else min(clock() + timeout, _deadline)
    try:
        checkpoint()
        parts = urlsplit(url)
        _resolve_public_addresses(parts.hostname, 443 if parts.scheme == "https" else 80,
            resolver=resolver, timeout=_remaining(deadline, clock))
        checkpoint()
        # Reuse one total deadline; the Google helper cannot reset the target-DNS budget.
        body = _google_performance_response(kind="psi_lab", target=url, strategy=strategy, grain="page", api_key=api_key,
            timeout=_remaining(deadline, clock), resolver=resolver, connection_factory=connection_factory, clock=clock,
            checkpoint=checkpoint, before_send=before_send, complete=True, deadline=deadline)
        received_at = timezone.now().isoformat(timespec="microseconds")
        try:
            result = observe_pagespeed_lab(body=body, body_complete=True, url=url, strategy=strategy, received_at=received_at)
        except ValidationError:
            raise PerformanceTransportError("malformed_response") from None
        checkpoint()
        _remaining(deadline, clock)
        return result
    except FetchDenied:
        raise PerformanceTransportError("egress_denied") from None
    except FetchError as error:
        raise PerformanceTransportError(error.code, retryable=error.code in {"timeout", "dns_error", "network_error"}) from None
    except TimeoutError:
        raise PerformanceTransportError("timeout", retryable=True) from None
    except OSError:
        raise PerformanceTransportError("network_error", retryable=True) from None

