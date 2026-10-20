"""Complete newest observed-source selection; no collection, SQL claim or sender."""
from datetime import timedelta, timezone as utc
from hashlib import sha256

from django.core.exceptions import PermissionDenied
from django.utils import timezone

from . import crux_delivery_source as exact, crux_history_source as history
from .models import PerformanceObservationSnapshot


METHOD = "optional-newest-observed-crux-daily-digest-source-v1"
COLLECTION_LIMIT = 100
_DIMENSIONS = ("source", "method", "form_factor", "observed_grain", "observed_key", "collection_timezone")


def _ids(project):
    return list(PerformanceObservationSnapshot.objects.filter(project_id=project.pk, source="crux_history")
                .order_by("-collected_at", "-pk").values_list("pk", flat=True)[:COLLECTION_LIMIT + 1])


def _snapshot(project, recipient, assessed):
    ids = _ids(project)
    if len(ids) > COLLECTION_LIMIT:
        return {"ids": ids, "state": "unavailable_collection_overflow"}, []
    originals = []
    newest = []
    seen = set()
    legacy = False
    for observation_id in ids:
        row, original = history._source(project, recipient, observation_id, assessed)
        legacy |= row.raw_sha256 is None
        if row.raw_sha256 is not None:
            # Stored observed_key alone cannot establish genuine provider normalization/fallback.
            history.current_crux_history_source(project=project, actor=recipient, observation_id=observation_id)
            if history._source(project, recipient, observation_id, assessed)[1] != original:
                raise PermissionDenied
            group = tuple(row.output[key] for key in _DIMENSIONS)
            if group not in seen:
                seen.add(group)
                newest.append(observation_id)
        originals.append({"id": observation_id, "original_sha256": sha256(original).hexdigest(),
                          "has_retries": row.job.retries.exists()})
    if _ids(project) != ids:
        raise PermissionDenied
    return {"originals": originals, "state": "unavailable_original_raw_integrity" if legacy else "complete"}, [] if legacy else newest


def current_daily_crux_digest_source(*, project, recipient):
    binding = exact._binding(project, recipient)
    result = {"method_version": METHOD, "project_id": project.pk, "scope": exact.SCOPE,
              "collection_limit": COLLECTION_LIMIT, "state": "unavailable_crux_intent",
              "preference_revision": None, "intent_updated_at": None, "day_start": None, "day_end": None,
              "sources": [], "episodes": [], "source_fingerprint": None, "assessed_at": None}
    if binding is None:
        if exact._binding(project, recipient) is not None:
            raise PermissionDenied
        return result
    assessed = timezone.now().astimezone(utc.utc)
    end = assessed.replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=1)
    snapshot, newest = _snapshot(project, recipient, assessed)
    result.update(preference_revision=binding[1], intent_updated_at=binding[2].isoformat(),
                  day_start=start.isoformat(), day_end=end.isoformat(), assessed_at=assessed.isoformat(),
                  state=snapshot["state"] if snapshot["state"] != "complete" else "unavailable_no_current_material_candidate")
    for observation_id in newest:
        source = exact.current_exact_crux_delivery_source(project=project, recipient=recipient, observation_id=observation_id)
        if (source["preference_revision"] != binding[1] or source["intent_updated_at"] != result["intent_updated_at"]
            or source["day_start"] != result["day_start"] or source["day_end"] != result["day_end"]):
            raise PermissionDenied
        result["sources"].append({key: value for key, value in source.items() if key != "assessed_at"})
        if source["state"] == "eligible_current_material_source_not_sent":
            result["episodes"].extend(item["episode_key"] for item in source["source"]["episodes"])
    if result["episodes"]:
        result["state"] = "eligible_current_material_digest_not_sent"
    if snapshot["state"] != "unavailable_collection_overflow":
        result["source_fingerprint"] = sha256(history._encoded({
            "source": {key: value for key, value in result.items() if key != "assessed_at"}, "snapshot": snapshot,
            "binding": [binding[0], binding[1], binding[2].isoformat(), binding[3], binding[4]]})).hexdigest()
    if _snapshot(project, recipient, assessed) != (snapshot, newest):
        raise PermissionDenied
    if exact._binding(project, recipient) != binding or timezone.now().astimezone(utc.utc).date() != end.date():
        raise PermissionDenied
    return result
