"""D123 response-only validation. Returned Google content is never a durable source snapshot."""
from datetime import datetime
import json
import math
import re
from urllib.parse import urlsplit

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from jobs.models import LocalBusinessAssessment
from tenancy.models import Project, ProjectConfiguration, normalize_origin
from tenancy.services import require_passive_security_scope

SCOPE = "https://www.googleapis.com/auth/business.manage"
POLICY_VERSION = "business-profile-response-only-v1"
MEMORY_SECONDS = 900
READ_MASK = "name,title,websiteUri,phoneNumbers,storefrontAddress,regularHours,specialHours,serviceArea,metadata.mapsUri"


def resource_name(value, kind):
    if (kind not in {"accounts", "locations"} or type(value) is not str
        or not re.fullmatch(kind + r"/[0-9]{1,40}", value)):
        raise ValidationError("Choose an exact Google business account/location resource.")
    return value


def _payload(payload, limit):
    try:
        if type(payload) is not dict or len(json.dumps(payload, allow_nan=False).encode()) > limit:
            raise ValueError
        pending = [(payload, 0)]
        seen = 0
        while pending:
            value, depth = pending.pop()
            seen += 1
            if depth > 10 or seen > 12000:
                raise ValueError
            if type(value) is dict:
                if len(value) > 100 or any(type(key) is not str or not 1 <= len(key) <= 160 for key in value):
                    raise ValueError
                pending.extend((item, depth + 1) for pair in value.items() for item in pair)
            elif type(value) is list:
                if len(value) > 100:
                    raise ValueError
                pending.extend((item, depth + 1) for item in value)
            elif type(value) is str:
                if len(value) > 8192 or any((ord(char) < 32 and char not in "\n\r\t")
                                          or 0xD800 <= ord(char) <= 0xDFFF for char in value):
                    raise ValueError
            elif type(value) is float:
                if not math.isfinite(value):
                    raise ValueError
            elif type(value) is int:
                if abs(value) > 2**53 - 1:
                    raise ValueError  # Preserve exact JSON integer values in the native browser consumer.
            elif type(value) not in {int, bool, type(None)}:
                raise ValueError
    except (ValueError, TypeError, OverflowError, UnicodeError, RecursionError):
        raise ValidationError("Google business response is malformed or exceeds this feature's bounds.") from None
    # Validation is read-only: preserve all returned attribution, fields and provider order.
    return payload


def _page(payload, key, maximum, limit):
    _payload(payload, limit)
    rows = payload.get(key, [])
    if (type(rows) is not list or len(rows) > maximum or any(type(row) is not dict for row in rows)
        or "nextPageToken" in payload and (type(payload["nextPageToken"]) is not str
                                            or len(payload["nextPageToken"]) > 2048)):
        raise ValidationError("Google business inventory is malformed or incomplete for this request.")
    return rows


def validate_accounts(payload):
    rows = _page(payload, "accounts", 20, 64 * 1024)
    names = [resource_name(row.get("name"), "accounts") for row in rows]
    if len(names) != len(set(names)):
        raise ValidationError("Google business account inventory contains duplicate identities.")
    return payload


def validate_location(payload, *, location_name):
    resource_name(location_name, "locations")
    _payload(payload, 64 * 1024)
    if (payload.get("name") != location_name or type(payload.get("title")) is not str
        or not 1 <= len(payload["title"]) <= 240
        or any(key in payload and type(payload[key]) is not dict for key in (
            "phoneNumbers", "storefrontAddress", "regularHours", "specialHours", "serviceArea", "metadata"))
        or "websiteUri" in payload and type(payload["websiteUri"]) is not str):
        raise ValidationError("Google business profile does not match the selected location.")
    return payload


def validate_locations(payload):
    rows = _page(payload, "locations", 100, 256 * 1024)
    names = [resource_name(row.get("name"), "locations") for row in rows]
    if len(names) != len(set(names)):
        raise ValidationError("Google business location inventory contains duplicate identities.")
    for row in rows:
        validate_location(row, location_name=row["name"])
    return payload


def require_account_location(*, accounts, locations, account_name, location_name):
    resource_name(account_name, "accounts")
    resource_name(location_name, "locations")
    validate_accounts(accounts)
    validate_locations(locations)
    # Caller must obtain locations from this exact account endpoint with this grant.
    # No location GET, title or URL alone proves account membership.
    if (not any(row["name"] == account_name for row in accounts.get("accounts", []))
        or not any(row["name"] == location_name for row in locations.get("locations", []))):
        raise PermissionDenied


def validate_reviews(payload, *, account_name, location_name):
    parent = resource_name(account_name, "accounts") + "/" + resource_name(location_name, "locations")
    rows = _page(payload, "reviews", 50, 256 * 1024)
    identities = set()
    for row in rows:
        identity = row.get("reviewId")
        if (type(identity) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", identity)
            or identity in identities or "name" in row and row["name"] != parent + "/reviews/" + identity
            or type(row.get("starRating")) is not str or row["starRating"] not in {"ONE", "TWO", "THREE", "FOUR", "FIVE"}
            or "comment" in row and type(row["comment"]) is not str
            or "reviewer" in row and type(row["reviewer"]) is not dict
            or "reviewReply" in row and type(row["reviewReply"]) is not dict):
            raise ValidationError("Google business review does not match the selected resource/schema.")
        identities.add(identity)
        for key in ("createTime", "updateTime"):
            try:
                if type(row.get(key)) is not str or timezone.is_naive(datetime.fromisoformat(row[key])):
                    raise ValueError
            except (ValueError, TypeError):
                raise ValidationError("Google review timestamps must be timezone-aware.") from None
    count = payload.get("totalReviewCount")
    rating = payload.get("averageRating")
    if (count is not None and (type(count) is not int or count < len(rows))
        or rating is not None and (type(rating) not in {int, float}
                                  or not 1 <= rating <= 5 and not (rating == 0 and count == 0))):
        raise ValidationError("Google review count/rating fields are malformed.")
    return payload


def validate_business_selection(selection):
    if (type(selection) is not dict or set(selection) != {"account_name", "location_name", "assessment_id",
        "configuration_revision", "origin", "authorize_business"} or selection["authorize_business"] is not True
        or type(selection["assessment_id"]) is not int or selection["assessment_id"] < 1
        or type(selection["configuration_revision"]) is not int or selection["configuration_revision"] < 0
        or type(selection["origin"]) is not str or normalize_origin(selection["origin"]) != selection["origin"]):
        raise ValidationError("Confirm exact business authority and choose current reviewed project facts.")
    resource_name(selection["account_name"], "accounts")
    resource_name(selection["location_name"], "locations")


def require_business_authority(*, project, actor, selection):
    validate_business_selection(selection)
    project = Project.objects.select_related("organization").filter(
        pk=project.pk, organization_id=project.organization_id).first()
    if project is None:
        raise PermissionDenied
    from .oauth import _verified
    if not _verified(actor):
        raise PermissionDenied
    verification = require_passive_security_scope(project=project, user=actor, origin=selection["origin"])
    config = ProjectConfiguration.objects.filter(project=project).first()
    assessment = LocalBusinessAssessment.objects.filter(pk=selection["assessment_id"], project=project).first()
    if (config is None or assessment is None or config.revision != selection["configuration_revision"]
        or assessment.configuration_revision != config.revision or verification.verified_at > timezone.now()
        or assessment.eligibility != LocalBusinessAssessment.Eligibility.USER_ATTESTED
        or not config.local_eligibility_notes.strip() or assessment.profile_url not in config.profile_urls
        or not assessment.profile_url or not assessment.services
        or assessment.location_label not in config.business_locations and not (not assessment.location_label and config.service_areas)
        or not set(assessment.service_areas) <= set(config.service_areas)
        or LocalBusinessAssessment.objects.filter(project=project, location_digest=assessment.location_digest,
                                                  revision__gt=assessment.revision).exists()):
        raise PermissionDenied
    return assessment, {"assessment_id": assessment.pk, "assessment_revision": assessment.revision,
        "configuration_revision": config.revision, "verification_id": verification.pk,
        "verified_at": verification.verified_at.isoformat()}


def validate_authorized_location(*, project, actor, selection, payload):
    assessment, authority = require_business_authority(project=project, actor=actor, selection=selection)
    validate_location(payload, location_name=selection["location_name"])
    website = payload.get("websiteUri")
    try:
        parts = urlsplit(website) if type(website) is str else None
        matches = (parts is not None and not parts.username and not parts.password and not parts.query
                   and not parts.fragment and not any(ord(char) < 33 or char == "\\" for char in website)
                   and normalize_origin(parts.scheme + "://" + parts.netloc) == selection["origin"])
    except (ValueError, ValidationError):
        matches = False
    if (not matches or payload["title"] != assessment.business_name
        or payload.get("metadata", {}).get("mapsUri") != assessment.profile_url):
        raise PermissionDenied
    return authority
