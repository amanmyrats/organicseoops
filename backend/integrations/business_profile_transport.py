"""Fixed-host read-only GBP requests. Unregistered until dedicated consent/delivery exists."""
import time
from urllib.parse import urlencode

from django.core.exceptions import PermissionDenied, ValidationError
from django.views.decorators.debug import sensitive_variables

from jobs.crawling import _connection_factory, _system_resolver
from .business_profile import (READ_MASK, require_account_location, require_business_authority, resource_name,
                               validate_accounts, validate_authorized_location, validate_location,
                               validate_locations, validate_reviews)
from .search_console_transport import (BUSINESS_ACCOUNT_HOST, BUSINESS_INFORMATION_HOST,
                                       BUSINESS_REVIEW_HOST, SearchConsoleTransportError, _google_json)


def business_accounts_list(*, access_token, resolver=_system_resolver, connection_factory=_connection_factory,
                           clock=time.monotonic, timeout=10):
    return validate_accounts(_google_json("/v1/accounts?pageSize=20", host=BUSINESS_ACCOUNT_HOST,
        access_token=access_token, limit=64 * 1024, resolver=resolver, connection_factory=connection_factory,
        clock=clock, timeout=timeout))


def business_locations_list(*, account_name, access_token, resolver=_system_resolver,
                            connection_factory=_connection_factory, clock=time.monotonic, timeout=10):
    account_name = resource_name(account_name, "accounts")
    query = urlencode({"pageSize": 100, "readMask": READ_MASK})
    return validate_locations(_google_json(f"/v1/{account_name}/locations?{query}", host=BUSINESS_INFORMATION_HOST,
        access_token=access_token, limit=256 * 1024, resolver=resolver, connection_factory=connection_factory,
        clock=clock, timeout=timeout))


def business_location_get(*, location_name, access_token, resolver=_system_resolver,
                          connection_factory=_connection_factory, clock=time.monotonic, timeout=10):
    location_name = resource_name(location_name, "locations")
    query = urlencode({"readMask": READ_MASK})
    payload = _google_json(f"/v1/{location_name}?{query}", host=BUSINESS_INFORMATION_HOST,
        access_token=access_token, limit=64 * 1024, resolver=resolver, connection_factory=connection_factory,
        clock=clock, timeout=timeout)
    return validate_location(payload, location_name=location_name)


def business_reviews_list(*, account_name, location_name, access_token, resolver=_system_resolver,
                          connection_factory=_connection_factory, clock=time.monotonic, timeout=10):
    parent = resource_name(account_name, "accounts") + "/" + resource_name(location_name, "locations")
    payload = _google_json(f"/v4/{parent}/reviews?pageSize=50", host=BUSINESS_REVIEW_HOST,
        access_token=access_token, limit=256 * 1024, resolver=resolver, connection_factory=connection_factory,
        clock=clock, timeout=timeout)
    return validate_reviews(payload, account_name=account_name, location_name=location_name)


@sensitive_variables()
def read_authorized_business_profile(*, project, actor, selection, access_token, checkpoint, before_request,
                                    resolver=_system_resolver, connection_factory=_connection_factory,
                                    clock=time.monotonic, deadline=None):
    """Response-only collector. Dedicated grant/usage caller supplies both current guards.

    Only selected profile/reviews leave this function. No sibling inventories or
    response-derived hashes are returned or stored. There is no retry/paging path.
    """
    if not callable(checkpoint) or not callable(before_request):
        raise ValidationError("Current grant/usage checkpoints are required for a business read.")
    now = clock()
    if deadline is None:
        deadline = now + 30
    elif type(deadline) not in {int, float} or not 0 < deadline - now <= 30:
        raise SearchConsoleTransportError("timeout")
    _, original_authority = require_business_authority(project=project, actor=actor, selection=selection)
    selection = dict(selection)  # Scalar-only validated inputs cannot change during caller callbacks.

    def current():
        checkpoint()  # Future caller rechecks app, grant, usage/entitlements and cancellation.
        _, authority = require_business_authority(project=project, actor=actor, selection=selection)
        if authority != original_authority:
            raise PermissionDenied
        if clock() >= deadline:
            raise SearchConsoleTransportError("timeout")

    def request_settings(operation):
        current()
        before_request(operation)  # Commit only a categorical attempted request before network work.
        current()
        remaining = min(10, deadline - clock())
        if remaining < 1:
            raise SearchConsoleTransportError("timeout")
        return {"access_token": access_token, "resolver": resolver, "connection_factory": connection_factory,
                "clock": clock, "timeout": remaining}

    accounts = business_accounts_list(**request_settings("accounts_list"))
    current()
    if not any(row["name"] == selection["account_name"] for row in accounts.get("accounts", [])):
        raise PermissionDenied
    locations = business_locations_list(account_name=selection["account_name"], **request_settings("locations_list"))
    current()
    require_account_location(accounts=accounts, locations=locations, account_name=selection["account_name"],
                             location_name=selection["location_name"])
    profile = next(row for row in locations["locations"] if row["name"] == selection["location_name"])
    if validate_authorized_location(project=project, actor=actor, selection=selection, payload=profile) != original_authority:
        raise PermissionDenied
    reviews = business_reviews_list(account_name=selection["account_name"], location_name=selection["location_name"],
                                    **request_settings("reviews_list"))
    current()
    return {"profile": profile, "reviews": reviews, "coverage": "first_page_only_not_complete_history",
            "ranking": "unavailable", "device": "unsupported", "geolocation": "unsupported",
            "direct_writes": "unavailable", "other_platforms": "unavailable"}
