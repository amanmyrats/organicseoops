"""Normalize one fixture-backed GA4 Data API landing-page response, without claiming a source grant."""

import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError

from tenancy.models import normalize_origin


DIMENSIONS = ("hostName", "landingPagePlusQueryString")
ACQUISITION_DIMENSIONS = (*DIMENSIONS, "sessionDefaultChannelGroup")
METRICS = ("sessions", "keyEvents", "totalRevenue")
METHOD = "ga4-landing-report-v1"
REPORT_KINDS = {"all_channels", "organic_search"}


def _value(row, field, size):
    values = row.get(field)
    if type(values) is not list or len(values) != size or any(
        type(item) is not dict or type(item.get("value")) is not str for item in values
    ):
        raise ValidationError("GA4 report columns are unavailable.")
    return [item["value"] for item in values]


def _metric(value, *, integer=False):
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError):
        raise ValidationError("GA4 report metric is unavailable.") from None
    if not number.is_finite() or abs(number) > 10**12 or (integer and (number < 0 or number != number.to_integral_value())):
        raise ValidationError("GA4 report metric is unavailable.")
    return int(number) if integer else str(number)


def parse_ga4_landing_report(*, response, property_id, day, approved_origins, offset=0,
                            report_kind="all_channels"):
    if (type(property_id) is not str or not re.fullmatch(r"[1-9][0-9]{0,19}", property_id)
        or type(day) is not date or type(offset) is not int or offset not in {0, 100}
        or type(approved_origins) not in {tuple, list} or not 1 <= len(approved_origins) <= 20
        or type(report_kind) is not str or report_kind not in REPORT_KINDS):
        raise ValidationError("GA4 report scope is unavailable.")
    expected_dimensions = ACQUISITION_DIMENSIONS if report_kind == "organic_search" else DIMENSIONS
    hosts = set()
    for origin in approved_origins:
        if type(origin) is not str or normalize_origin(origin) != origin or urlsplit(origin).scheme != "https":
            raise ValidationError("GA4 host scope requires approved HTTPS origins.")
        host = urlsplit(origin).hostname
        if host in hosts:
            raise ValidationError("GA4 cannot distinguish multiple origins on one hostname.")
        hosts.add(host)
    try:
        encoded = json.dumps(response, allow_nan=False, separators=(",", ":")).encode()
    except (TypeError, ValueError):
        raise ValidationError("GA4 report is malformed.") from None
    if type(response) is not dict or len(encoded) > 256 * 1024 or response.get("kind") != "analyticsData#runReport":
        raise ValidationError("GA4 report is malformed.")
    dimensions, metrics = response.get("dimensionHeaders"), response.get("metricHeaders")
    if (type(dimensions) is not list or [item.get("name") for item in dimensions if type(item) is dict] != list(expected_dimensions)
        or len(dimensions) != len(expected_dimensions) or type(metrics) is not list
        or [item.get("name") for item in metrics if type(item) is dict] != list(METRICS)
        or len(metrics) != len(METRICS)):
        raise ValidationError("GA4 report columns changed.")
    rows, metadata, row_count = response.get("rows", []), response.get("metadata"), response.get("rowCount")
    if (type(rows) is not list or len(rows) > 100 or type(row_count) is not int or not 0 <= row_count <= 10**7
        or row_count < offset + len(rows) or type(metadata) is not dict):
        raise ValidationError("GA4 report coverage is unavailable.")
    currency, zone = metadata.get("currencyCode"), metadata.get("timeZone")
    if (type(currency) is not str or not re.fullmatch(r"[A-Z]{3}", currency)
        or type(zone) is not str or len(zone) > 64):
        raise ValidationError("GA4 report currency or timezone is unavailable.")
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValidationError("GA4 report timezone is unavailable.") from None
    for flag in ("subjectToThresholding", "dataLossFromOtherRow"):
        if flag in metadata and type(metadata[flag]) is not bool:
            raise ValidationError("GA4 report coverage is unavailable.")
    sampled = metadata.get("samplingMetadatas", [])
    if type(sampled) is not list or len(sampled) > 1:
        raise ValidationError("GA4 sampling state is unavailable.")
    parsed, seen = [], set()
    omitted = 0
    unexpected_channel = 0
    for row in rows:
        if type(row) is not dict:
            raise ValidationError("GA4 report row is malformed.")
        values_by_dimension = _value(row, "dimensionValues", len(expected_dimensions))
        host, path = values_by_dimension[:2]
        channel = values_by_dimension[2] if report_kind == "organic_search" else None
        sessions, events, revenue = _value(row, "metricValues", 3)
        values = {"sessions": _metric(sessions, integer=True), "key_events": _metric(events),
                  "total_revenue": _metric(revenue)}
        if Decimal(values["key_events"]) < 0:
            raise ValidationError("GA4 key events are unavailable.")
        if channel not in (None, "Organic Search"):
            unexpected_channel += 1
        if (host not in hosts or channel not in (None, "Organic Search")
            or not 1 <= len(path) <= 512 or not path.startswith("/")
            or path.startswith("//") or any(character in path for character in "?#\\\r\n")
            or any(character in unquote(path) for character in "?#\\\r\n")):
            omitted += 1
            continue
        identity = (host, path)
        if identity in seen:
            raise ValidationError("GA4 report contains duplicate landing rows.")
        seen.add(identity)
        parsed.append({"hostname": host, "path": path, **values,
                       **({"session_default_channel_group": channel} if channel else {})})
    return {"method": METHOD if report_kind == "all_channels" else "ga4-organic-search-landing-v1",
            "report_kind": report_kind, "property_id": property_id, "day": day.isoformat(),
            "offset": offset, "row_count": row_count, "currency": currency, "timezone": zone,
            "dimensions": list(expected_dimensions), "metrics": list(METRICS), "rows": parsed,
            "coverage": {"scope": "approved_hostname_only_scheme_unknown",
                         "acquisition_scope": ("all_channels" if report_kind == "all_channels"
                                               else "ga4_session_default_channel_organic_search_not_gsc_clicks"),
                         "omitted_foreign_or_parameterized_rows": omitted,
                         "omitted_unexpected_channel_rows": unexpected_channel,
                         "sampled": bool(sampled), "thresholded": metadata.get("subjectToThresholding", False),
                         "other_row_loss": metadata.get("dataLossFromOtherRow", False),
                         "returned_rows_exhausted_without_reported_gaps": (offset + len(rows) >= row_count and omitted == 0 and not sampled
                                      and not metadata.get("subjectToThresholding", False)
                                      and not metadata.get("dataLossFromOtherRow", False)),
                         "full_activity_coverage": "unknown",
                         "instrumentation_verified": False, "conversion_definition": "unverified_key_events",
                         "search_clicks": "not_reported"}}
