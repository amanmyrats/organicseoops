"""Exact stored resolved destinations in two samples; no target or crawl authority."""
from django.core.exceptions import PermissionDenied, ValidationError

from . import competitor_collection as lifecycle, competitor_synthesis as synthesis
from .competitor_comparison import _read_pair_sources
from .competitor_page_destinations_collection import HANDLER
from .competitor_reference_structure import read_competitor_reference_structure
from .models import JobCancellation, JobRun, JobStatus
from .usage import require_billable_access


METHOD = "competitor-two-sample-destination-inventory-v1"
INTERPRETATION = "exact_stored_resolved_supported_destination_uris_in_two_selected_static_samples_not_complete_site_page_or_destination_inventory_fetched_targets_target_health_browser_visibility_indexing_inbound_links_topology_topics_freshness_causality_or_crawl_authority"
MAX_RESULT_BYTES = 32 * 1024


def read_competitor_destination_inventory(*, project, actor, first_job_id, second_job_id):
    ids = (first_job_id, second_job_id)
    for key in ids:
        lifecycle._safe_id(key)
    if ids[0] == ids[1]:
        raise ValidationError("Choose two distinct saved selected-page reference samples.")
    jobs = {job.pk: job for job in JobRun.objects.select_related("project", "actor").filter(
        pk__in=ids, project_id=project.pk, organization_id=project.organization_id,
        handler=HANDLER, status=JobStatus.SUCCEEDED)}
    if len(jobs) != 2:
        raise PermissionDenied
    callers = _read_pair_sources((jobs[key] for key in ids), project, actor)
    original = synthesis._pins(ids)
    samples = read_competitor_reference_structure(project=project, actor=actor,
        first_job_id=ids[0], second_job_id=ids[1])["pages"]
    rows = [sample["collection"]["evidence"]["destinations"] for sample in samples]
    destinations = list(dict.fromkeys(url for row in rows if row is not None for url in row))
    occurrences = [[row.count(url) for url in destinations] if row is not None else None for row in rows]
    result = {"method_version": METHOD, "organization_id": project.organization_id,
        "project_id": project.pk, "source_current": True, "pages": samples,
        "destinations": destinations, "destination_reference_occurrences": occurrences,
        "all_rows_observed": all(row is not None for row in rows), "interpretation": INTERPRETATION}
    if len(lifecycle._encode(result)) > MAX_RESULT_BYTES:
        raise ValidationError("The original two-sample destination inventory exceeds its bounded size.")
    if synthesis._pins(ids) != original:
        raise PermissionDenied
    fresh = (JobRun.objects.select_related("project", "actor").get(pk=key, handler=HANDLER) for key in ids)
    if _read_pair_sources(fresh, project, actor) != callers:
        raise PermissionDenied
    if synthesis._pins(ids) != original or JobCancellation.objects.filter(job_id__in=ids).exists():
        raise PermissionDenied
    require_billable_access(organization=project.organization)
    return result
