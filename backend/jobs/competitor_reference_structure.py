"""Exact reference occurrences between two saved static page samples; no crawl authority."""
from urllib.parse import urlsplit

from django.core.exceptions import PermissionDenied, ValidationError

from . import competitor_collection as lifecycle, competitor_page_destinations_collection as references, competitor_page_formats_collection as elements, competitor_page_headings_collection as heading_pages
from .competitor_comparison import _read_pair_sources
from .competitor_formats import COUNTS
from .competitor_headings import COUNTS as HEADING_COUNTS
from .models import JobCancellation, JobRun, JobStatus
from .usage import require_billable_access


METHOD = "competitor-two-page-references-v1"
INTERPRETATION = "two_selected_static_samples_exact_reference_occurrences_not_unique_pages_target_health_browser_visibility_indexing_inbound_links_whole_site_topology_topics_freshness_causality_or_crawl_authority"
MAX_RESULT_BYTES = 24 * 1024
FORMATS_METHOD = "competitor-two-page-elements-v1"
FORMATS_INTERPRETATION = "two_selected_static_samples_literal_start_tag_counts_not_rendered_formats_loaded_media_semantic_page_types_search_features_accessibility_site_totals_whole_site_freshness_changes_causality_ai_or_collection_authority"
HEADINGS_METHOD = "competitor-two-page-headings-v1"
HEADINGS_INTERPRETATION = "two_selected_static_samples_literal_heading_level_counts_with_original_text_order_truncation_not_rendered_semantic_outline_accessibility_topics_intent_page_identity_freshness_site_totals_whole_site_causality_ai_or_collection_authority"


def read_competitor_reference_structure(*, project, actor, first_job_id, second_job_id):
    return _read_two_page_structure(project=project, actor=actor, first_job_id=first_job_id, second_job_id=second_job_id)


def _read_two_page_structure(*, project, actor, first_job_id, second_job_id, formats=False, headings=False):
    if formats and headings: raise ValidationError("Choose one fixed original observation family.")
    family = heading_pages if headings else elements if formats else references
    ids = (first_job_id, second_job_id)
    for key in ids:
        lifecycle._safe_id(key)
    if ids[0] == ids[1]:
        raise ValidationError("Choose two distinct saved selected-page observations.")
    jobs = {job.pk: job for job in JobRun.objects.select_related("project", "actor").filter(
        pk__in=ids, project_id=project.pk, organization_id=project.organization_id,
        handler=family.HANDLER, status=JobStatus.SUCCEEDED)}
    if len(jobs) != 2:
        raise PermissionDenied
    callers = _read_pair_sources((jobs[key] for key in ids), project, actor)
    original = {key: lifecycle._read_metadata(key) for key in ids}
    reader = heading_pages.read_competitor_page_headings_observation if headings else elements.read_competitor_page_formats_observation if formats else references.read_competitor_page_destinations_observation
    observed = [reader(project=project, actor=actor, job_id=key) for key in ids]
    urls = [value["collection"]["url"] for value in observed]
    origins = [(urlsplit(url).scheme, urlsplit(url).netloc) for url in urls]
    if urls[0] == urls[1] or origins[0] != origins[1]:
        raise ValidationError("Inspect two different exact selected page URIs on one exact origin.")
    counts = []
    for value in observed:
        evidence = value["collection"]["evidence"]
        if formats or headings:
            counts.append([evidence["counts"][name] for name in (HEADING_COUNTS if headings else COUNTS)])
        else:
            counts.append([evidence["destinations"].count(url) for url in urls]
                if evidence["state"] == "observed" else [None, None])
    result = {"method_version": HEADINGS_METHOD if headings else FORMATS_METHOD if formats else METHOD, "organization_id": project.organization_id,
        "project_id": project.pk, "source_current": True, "pages": observed,
        "selected_heading_occurrences" if headings else "selected_element_occurrences" if formats else "selected_uri_reference_occurrences": counts,
        "interpretation": HEADINGS_INTERPRETATION if headings else FORMATS_INTERPRETATION if formats else INTERPRETATION}
    if formats or headings:
        result["heading_levels" if headings else "element_names"] = list(HEADING_COUNTS if headings else COUNTS)
        result["all_rows_observed"] = all(row["collection"]["evidence"]["state"] == "observed" for row in observed)
    content = lifecycle._encode(result)
    if len(content) > MAX_RESULT_BYTES:
        raise ValidationError("The original two-page packet exceeds its bounded size.")
    if any(lifecycle._read_metadata(key) != original[key] for key in ids):
        raise PermissionDenied
    fresh = (JobRun.objects.select_related("project", "actor").get(pk=key, handler=family.HANDLER) for key in ids)
    if _read_pair_sources(fresh, project, actor) != callers:
        raise PermissionDenied
    if any(lifecycle._read_metadata(key) != original[key] for key in ids) or JobCancellation.objects.filter(job_id__in=ids).exists():
        raise PermissionDenied
    require_billable_access(organization=project.organization)
    return result
