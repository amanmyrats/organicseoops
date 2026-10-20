"""Fixed GA4 Admin/Data API read-only transport; callers supply separately authorized tokens."""

import json
import re
import time
from datetime import date, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.utils import timezone

from jobs.crawling import _connection_factory, _system_resolver
from tenancy.models import normalize_origin

from .ga4_reports import ACQUISITION_DIMENSIONS, DIMENSIONS, METRICS, REPORT_KINDS
from .search_console_transport import (ANALYTICS_ADMIN_HOST, ANALYTICS_DATA_HOST,
                                       _google_json)


def _property_id(value):
    if type(value) is not str or not re.fullmatch(r"[1-9][0-9]{0,19}", value):
        raise ValidationError("Choose a GA4 property ID.")
    return value


def _report_columns(hostname, report_kind):
    if type(report_kind) is not str or report_kind not in REPORT_KINDS:
        raise ValidationError("Choose a supported GA4 report grain.")
    dimensions = ACQUISITION_DIMENSIONS if report_kind == "organic_search" else DIMENSIONS
    host_filter = {"filter": {"fieldName": "hostName",
        "stringFilter": {"matchType": "EXACT", "value": hostname, "caseSensitive": True}}}
    dimension_filter = (host_filter if report_kind == "all_channels" else {"andGroup": {"expressions": [
        host_filter, {"filter": {"fieldName": "sessionDefaultChannelGroup",
            "stringFilter": {"matchType": "EXACT", "value": "Organic Search", "caseSensitive": True}}}]}})
    return {"dimensions": [{"name": name} for name in dimensions],
            "metrics": [{"name": name} for name in METRICS],
            "dimensionFilter": dimension_filter}


def _report_origin(value):
    if type(value) is not str or normalize_origin(value) != value or urlsplit(value).scheme != "https":
        raise ValidationError("GA4 report requires an exact configured HTTPS origin.")
    return urlsplit(value).hostname


def ga4_check_landing_compatibility(*, property_id, approved_origin, access_token,
                                    report_kind="all_channels",
                                    resolver=_system_resolver, connection_factory=_connection_factory,
                                    clock=time.monotonic, timeout=10):
    property_id = _property_id(property_id)
    body = json.dumps(_report_columns(_report_origin(approved_origin), report_kind), separators=(",", ":")).encode()
    response = _google_json(f"/v1beta/properties/{property_id}:checkCompatibility", host=ANALYTICS_DATA_HOST,
                            access_token=access_token, limit=16 * 1024, resolver=resolver,
                            connection_factory=connection_factory, clock=clock, timeout=timeout, body=body)
    dimensions = ACQUISITION_DIMENSIONS if report_kind == "organic_search" else DIMENSIONS
    for field, names, metadata in (("dimensionCompatibilities", dimensions, "dimensionMetadata"),
                                    ("metricCompatibilities", METRICS, "metricMetadata")):
        rows = response.get(field)
        if (type(rows) is not list or len(rows) != len(names)
            or {row.get(metadata, {}).get("apiName") for row in rows if type(row) is dict
                and type(row.get(metadata)) is dict} != set(names)
            or any(type(row) is not dict or row.get("compatibility") != "COMPATIBLE" for row in rows)):
            raise ValidationError("GA4 landing report dimensions/metrics are incompatible or unavailable.")
    return True


def ga4_admin_property_get(*, property_id, access_token, resolver=_system_resolver,
                           connection_factory=_connection_factory, clock=time.monotonic, timeout=10):
    return _google_json(f"/v1beta/properties/{_property_id(property_id)}", host=ANALYTICS_ADMIN_HOST,
                        access_token=access_token, limit=16 * 1024, resolver=resolver,
                        connection_factory=connection_factory, clock=clock, timeout=timeout)


def ga4_admin_streams_list(*, property_id, access_token, resolver=_system_resolver,
                           connection_factory=_connection_factory, clock=time.monotonic, timeout=10):
    response = _google_json(f"/v1beta/properties/{_property_id(property_id)}/dataStreams?pageSize=50",
                            host=ANALYTICS_ADMIN_HOST, access_token=access_token, limit=64 * 1024,
                            resolver=resolver, connection_factory=connection_factory, clock=clock, timeout=timeout)
    if response.get("nextPageToken"):
        raise ValidationError("GA4 web stream inventory is incomplete.")
    return response


def ga4_landing_report(*, property_id, approved_origin, day, offset, access_token,
                       report_kind="all_channels",
                       property_timezone="UTC",
                       resolver=_system_resolver, connection_factory=_connection_factory,
                       clock=time.monotonic, timeout=10):
    property_id = _property_id(property_id)
    if type(day) is not date or type(offset) is not int or offset not in {0, 100}:
        raise ValidationError("Choose one bounded GA4 reporting day/page.")
    if type(property_timezone) is not str or len(property_timezone) > 64:
        raise ValidationError("GA4 property reporting timezone is unavailable.")
    try:
        local_today = timezone.now().astimezone(ZoneInfo(property_timezone)).date()
    except (ValueError, ZoneInfoNotFoundError):
        raise ValidationError("GA4 property reporting timezone is unavailable.") from None
    if not local_today - timedelta(days=90) <= day <= local_today - timedelta(days=3):
        raise ValidationError("GA4 report day is outside the bounded finalized window.")
    hostname = _report_origin(approved_origin)
    body = json.dumps({"dateRanges": [{"startDate": day.isoformat(), "endDate": day.isoformat()}],
                       **_report_columns(hostname, report_kind),
                       "orderBys": [{"dimension": {"dimensionName": name}} for name in (
                           ACQUISITION_DIMENSIONS if report_kind == "organic_search" else DIMENSIONS)],
                       "limit": "100", "offset": str(offset), "returnPropertyQuota": True},
                      separators=(",", ":")).encode()
    return _google_json(f"/v1beta/properties/{property_id}:runReport", host=ANALYTICS_DATA_HOST,
                        access_token=access_token, limit=256 * 1024, resolver=resolver,
                        connection_factory=connection_factory, clock=clock, timeout=timeout, body=body)
