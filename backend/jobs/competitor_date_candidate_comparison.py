"""All same-property stored Date candidate intervals; no matched publishing events."""
from datetime import date, datetime

from django.core.exceptions import PermissionDenied, ValidationError

from . import competitor_collection as lifecycle, competitor_page_dates_collection as collection
from .competitor_comparison import _read_pair_sources
from .competitor_date_candidates import article_date_literal_candidates
from .competitor_dates_comparison import compare_competitor_page_dates
from .models import JobCancellation, JobRun, JobStatus
from .usage import require_billable_access


METHOD = "competitor-date-candidate-pair-v1"
INTERPRETATION = "all_same_property_original_declaration_index_pairs_calendar_or_utc_candidate_intervals_not_matched_events_validated_publication_change_age_freshness_cadence_page_identity_whole_site_causality_approval_ai_or_source_authority"
MAX_RESULT_BYTES = 48 * 1024


def _candidate_rows(previous, current):
    if previous["candidates"] is None or current["candidates"] is None: return None
    rows = []
    for first, candidate in enumerate(previous["candidates"]):
        for second, other in enumerate(current["candidates"]):
            if previous["evidence"]["declarations"][first]["property"] != current["evidence"]["declarations"][second]["property"]:
                continue
            row = {"previous_declaration_index": first, "current_declaration_index": second,
                "state": "incomparable_literal_candidates", "calendar_day_delta": None, "utc_microsecond_delta": None}
            if candidate["state"] == other["state"] == "calendar_literal":
                row.update(state="calendar_candidates", calendar_day_delta=(date.fromisoformat(other["calendar_date"])
                    - date.fromisoformat(candidate["calendar_date"])).days)
            elif candidate["state"] == other["state"] == "offset_literal":
                delta = datetime.fromisoformat(other["utc_instant"]) - datetime.fromisoformat(candidate["utc_instant"])
                row.update(state="offset_candidates", utc_microsecond_delta=str((delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds))
            rows.append(row)
    return rows


def compare_competitor_date_candidates(*, project, actor, previous_job_id, current_job_id):
    ids = (previous_job_id, current_job_id)
    for key in ids: lifecycle._safe_id(key)
    if ids[0] == ids[1]: raise ValidationError("Choose two distinct saved Date observations.")
    jobs = {job.pk: job for job in JobRun.objects.select_related("project", "actor").filter(pk__in=ids,
        project_id=project.pk, organization_id=project.organization_id, handler=collection.HANDLER, status=JobStatus.SUCCEEDED)}
    if len(jobs) != 2: raise PermissionDenied
    callers = _read_pair_sources((jobs[key] for key in ids), project, actor)
    original = {key: lifecycle._read_metadata(key) for key in ids}
    comparison = compare_competitor_page_dates(project=project, actor=actor,
        previous_job_id=previous_job_id, current_job_id=current_job_id)
    previous, current = (article_date_literal_candidates(comparison[key]["evidence"]) for key in ("previous", "current"))
    result = {"method_version": METHOD, "organization_id": project.organization_id, "project_id": project.pk,
        "source_current": True, "comparison": comparison, "previous_candidates": previous["candidates"],
        "current_candidates": current["candidates"], "declaration_pair_candidates": _candidate_rows(previous, current),
        "interpretation": INTERPRETATION}
    if len(lifecycle._encode(result)) > MAX_RESULT_BYTES:
        raise ValidationError("The original Date candidate pair exceeds its bounded size.")
    if any(lifecycle._read_metadata(key) != original[key] for key in ids): raise PermissionDenied
    fresh = (JobRun.objects.select_related("project", "actor").get(pk=key, handler=collection.HANDLER) for key in ids)
    if _read_pair_sources(fresh, project, actor) != callers: raise PermissionDenied
    if any(lifecycle._read_metadata(key) != original[key] for key in ids) or JobCancellation.objects.filter(job_id__in=ids).exists():
        raise PermissionDenied
    require_billable_access(organization=project.organization)
    return result
