"""Arithmetic between original provider lab samples; never a controlled benchmark."""
import json

from django.core.exceptions import PermissionDenied, ValidationError

from . import competitor_collection as lifecycle, competitor_lab_collection as collection
from .competitor_comparison import _read_pair_sources
from .competitor_lab import LAB_AUDITS, SCORES, _provider_date
from .models import JobCancellation, JobRun, JobStatus
from .passive_tls_evidence import _date
from .usage import require_billable_access


METHOD = "competitor-lighthouse-pair-v1"
INTERPRETATION = "original_same_uri_device_version_lab_sample_arithmetic_not_controlled_conditions_representative_benchmark_statistical_significance_field_p75_current_site_whole_site_rankings_or_causality"
MAX_RESULT_BYTES = 32768


def compare_competitor_lab(*, project, actor, previous_job_id, current_job_id):
    ids = (previous_job_id, current_job_id)
    if any(type(value) is not int or not 1 <= value < 2**53 for value in ids) or ids[0] == ids[1]:
        raise ValidationError("Choose two distinct original Lighthouse jobs.")
    jobs = {row.pk: row for row in JobRun.objects.select_related("project", "actor").filter(
        pk__in=ids, project_id=project.pk, organization_id=project.organization_id,
        handler=collection.HANDLER, status=JobStatus.SUCCEEDED)}
    if len(jobs) != 2: raise PermissionDenied
    callers = _read_pair_sources((jobs[key] for key in ids), project, actor)
    original = {key: lifecycle._read_metadata(key) for key in ids}
    if jobs[ids[0]].config_snapshot != jobs[ids[1]].config_snapshot:
        raise ValidationError("Retain the exact same original source, device, actor and credential reference.")
    observed = [collection.read_competitor_lab_observation(project=project, actor=actor, job_id=key)["collection"] for key in ids]
    before, after = observed
    if (any(before[key] != after[key] for key in ("method_version", "url", "strategy", "selection_sha256"))
        or any(before["evidence"][key] != after["evidence"][key] for key in ("method_version", "coverage", "interpretation"))
        or _date(before["request_started_at"]) >= _date(after["request_started_at"])
        or _date(before["evidence"]["received_at"]) >= _date(after["evidence"]["received_at"])):
        raise ValidationError("Retain increasing original request and receipt dates for the exact same source and device.")
    first, second = before["evidence"], after["evidence"]
    reason = ""
    if first["state"] != "observed" or second["state"] != "observed": reason = "lab_unavailable"
    elif (first["lab"]["lighthouse_version"] == "unknown"
        or first["lab"]["lighthouse_version"] != second["lab"]["lighthouse_version"]):
        reason = "lighthouse_version_unavailable_or_changed"
    elif _provider_date(first["provider_reported_at"]) >= _provider_date(second["provider_reported_at"]):
        reason = "provider_report_time_not_increasing"
    scores = {key: None for key in SCORES}
    audits = {key: {"value": None, "unit": unit} for key, unit in LAB_AUDITS.items()}
    if not reason:
        for key in SCORES:
            earlier, later = first["lab"]["scores"][key], second["lab"]["scores"][key]
            if earlier is not None and later is not None: scores[key] = later - earlier
        for key in LAB_AUDITS:
            earlier, later = first["lab"]["audits"][key]["value"], second["lab"]["audits"][key]["value"]
            if earlier is not None and later is not None: audits[key]["value"] = later - earlier
    result = {"method_version": METHOD, "organization_id": project.organization_id, "project_id": project.pk,
        "source_current": True, "collection_method": before["method_version"], "parser_method": first["method_version"],
        "url": before["url"], "strategy": before["strategy"], "selection_sha256": before["selection_sha256"],
        "previous": {"job_id": ids[0], "robots": before["robots"], "request_started_at": before["request_started_at"], "evidence": first},
        "current": {"job_id": ids[1], "robots": after["robots"], "request_started_at": after["request_started_at"], "evidence": second},
        "state": "arithmetic_original_lab_samples" if not reason else "incomparable_lab_samples", "reason": reason,
        "body_changed": first["response_sha256"] != second["response_sha256"],
        "score_deltas": scores, "audit_deltas": audits, "interpretation": INTERPRETATION}
    content = lifecycle._encode(result)
    if len(content) > MAX_RESULT_BYTES: raise ValidationError("Original Lighthouse pair exceeds its bounded limit.")
    if any(lifecycle._read_metadata(key) != original[key] for key in ids): raise PermissionDenied
    fresh = (JobRun.objects.select_related("project", "actor").get(pk=key, handler=collection.HANDLER) for key in ids)
    if _read_pair_sources(fresh, project, actor) != callers: raise PermissionDenied
    if any(lifecycle._read_metadata(key) != original[key] for key in ids): raise PermissionDenied
    if JobCancellation.objects.filter(job_id__in=ids).exists(): raise PermissionDenied
    require_billable_access(organization=project.organization)
    # A fresh JSON value keeps callers from mutating either original stored projection.
    return json.loads(content)
