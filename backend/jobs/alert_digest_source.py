"""One completed-day source pin; no persistence, SMTP or immutable incident claim."""
from datetime import date, datetime, timedelta, timezone as utc
from hashlib import sha256
import json
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from tenancy.models import Project
from . import alert_delivery_source as crawl, integration_alert_source as reconnect


METHOD = "optional-daily-operational-digest-source-v1"
_READERS = {"crawl_failure": crawl.current_daily_crawl_alert_source,
            "integration_health": reconnect.current_daily_integration_alert_source}


def _day():
    end = timezone.now().astimezone(utc.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return end - timedelta(days=1), end


def _date(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()  # DjangoJSONEncoder truncates datetime microseconds to milliseconds.
    if isinstance(value, UUID):
        return str(value)
    raise TypeError


def _fingerprint(value):
    try:
        data = json.dumps(value, default=_date, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise ValidationError("Operational source metadata needs review.") from None
    if len(data) > 131072:
        raise ValidationError("Operational source metadata exceeds bounded coverage.")
    return sha256(data).hexdigest()


def _snapshot(project, families, start, end, intent_at):
    current = Project.objects.get(pk=project.pk, organization_id=project.organization_id)
    origins = sorted({current.canonical_origin, *current.domain_aliases.values_list("origin", flat=True)})
    return {"origins": origins, "families": {
        family: (crawl._snapshot(current, start, end, intent_at) if family == "crawl_failure"
                 else reconnect._snapshot(current, start, end, intent_at)) for family in families}}


def _binding(project, recipient):
    return crawl._binding(project, recipient) or crawl._binding(project, recipient, "integration_health")


def current_daily_digest_source(*, project, recipient):
    binding = _binding(project, recipient)
    if binding is None:
        return None
    start, end = _day()
    families = binding[2]
    snapshot = _snapshot(project, families, start, end, binding[3])
    sources = {}
    episodes = []
    for family in families:
        source = _READERS[family](project=project, recipient=recipient)
        if (source["day_start"] != start.isoformat() or source["day_end"] != end.isoformat()
            or source["preference_revision"] != binding[1] or source["intent_updated_at"] != binding[3].isoformat()):
            raise PermissionDenied
        sources[family] = {key: value for key, value in source.items() if key != "assessed_at"}
        for row in source["rows"]:
            episodes.append(f"crawl:{row['job_id']}" if family == "crawl_failure"
                            else f"reconnect:{row['grant_id']}:{row['grant_revision']}")
    result = {"method_version": METHOD, "project_id": project.pk, "day_start": start.isoformat(),
              "day_end": end.isoformat(), "preference_revision": binding[1],
              "intent_updated_at": binding[3].isoformat(), "source_families": list(families),
              "sources": sources, "episodes": episodes}
    result["source_fingerprint"] = _fingerprint({"source": result, "snapshot": snapshot})
    if _snapshot(project, families, start, end, binding[3]) != snapshot:
        raise ValidationError("Original operational source selection changed during inspection.")
    if any(crawl._binding(project, recipient, family) != binding for family in families) or _day() != (start, end):
        raise PermissionDenied
    return result if episodes else None
