"""GA4 Admin API property/stream candidate selection; configuration is not traffic verification."""

import json
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError

from tenancy.models import Project, normalize_origin
from tenancy.services import Action, require_project_action


def eligible_ga4_property(*, project, user, property_id, property_response, streams_response):
    project = Project.objects.get(pk=project.pk, organization_id=project.organization_id)
    require_project_action(project=project, user=user, action=Action.MANAGE_PROJECT)
    if type(property_id) is not str or not re.fullmatch(r"[1-9][0-9]{0,19}", property_id):
        raise ValidationError("Choose a GA4 property ID.")
    try:
        property_size = len(json.dumps(property_response, allow_nan=False).encode())
        stream_size = len(json.dumps(streams_response, allow_nan=False).encode())
    except (TypeError, ValueError):
        raise ValidationError("GA4 property selection is unavailable.") from None
    identity = "properties/" + property_id
    if (type(property_response) is not dict or property_size > 16 * 1024
        or property_response.get("name") != identity
        or property_response.get("propertyType", "PROPERTY_TYPE_ORDINARY") != "PROPERTY_TYPE_ORDINARY"
        or type(streams_response) is not dict or stream_size > 64 * 1024
        or streams_response.get("nextPageToken")
        or type(streams_response.get("dataStreams")) is not list
        or len(streams_response["dataStreams"]) > 50):
        raise ValidationError("GA4 property selection is unavailable or incomplete.")
    currency, zone = property_response.get("currencyCode"), property_response.get("timeZone")
    if (type(currency) is not str or not re.fullmatch(r"[A-Z]{3}", currency)
        or type(zone) is not str or len(zone) > 64):
        raise ValidationError("GA4 property measurement context is unavailable.")
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValidationError("GA4 property timezone is unavailable.") from None
    origins = {project.canonical_origin, *project.domain_aliases.values_list("origin", flat=True)}
    matched = set()
    skipped = 0
    matched_count = 0
    for stream in streams_response["dataStreams"]:
        if type(stream) is not dict or type(stream.get("name")) is not str:
            raise ValidationError("GA4 data stream inventory is unavailable.")
        if not re.fullmatch(re.escape(identity) + r"/dataStreams/[1-9][0-9]{0,19}", stream["name"]):
            raise ValidationError("GA4 data stream property does not match.")
        if stream.get("type") != "WEB_DATA_STREAM" or type(stream.get("webStreamData")) is not dict:
            skipped += 1
            continue
        uri = stream["webStreamData"].get("defaultUri")
        try:
            if (type(uri) is not str or len(uri) > 512 or uri.strip() != uri
                or urlsplit(uri).query or urlsplit(uri).fragment or normalize_origin(uri) not in origins
                or urlsplit(uri).path not in {"", "/"}):
                skipped += 1
                continue
            matched.add(normalize_origin(uri))
            matched_count += 1
        except (ValueError, ValidationError):
            skipped += 1
    if not matched or any(urlsplit(origin).scheme != "https" for origin in matched):
        raise ValidationError("No exact configured HTTPS origin has a selected GA4 web stream.")
    return {"property_id": property_id, "matched_origins": sorted(matched),
            "matching_stream_count": matched_count,
            "other_stream_count": skipped,
            "currency": currency, "timezone": zone,
            "scope": "configured_web_stream_default_uri_only_not_domain_or_instrumentation_proof",
            "analytics_oauth_scope": "https://www.googleapis.com/auth/analytics.readonly",
            "host_filter_required": True, "url_scheme_from_ga4_hostname": "unknown"}
