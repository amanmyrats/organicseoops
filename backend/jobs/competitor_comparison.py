"""Dated literal same-URI metadata comparisons; no collection or whole-site inference."""
from django.core.exceptions import PermissionDenied, ValidationError

from . import competitor_collection as collection
from .competitor_metadata import COUNTS
from .competitor_links import COUNTS as LINK_COUNTS
from .competitor_headings import COUNTS as HEADING_COUNTS
from .competitor_formats import COUNTS as FORMAT_COUNTS
from .models import JobCancellation, JobRun, JobStatus
from .passive_tls_evidence import _date
from .usage import require_billable_access


METHOD = "competitor-static-comparison-v1"
INTERPRETATION = "dated_selected_root_literal_changes_not_topics_publication_age_schema_validity_traffic_rankings_backlinks_whole_site_or_causality"
PAGE_METHOD = "competitor-static-page-comparison-v1"
PAGE_INTERPRETATION = "dated_selected_nonroot_uri_literal_changes_not_page_identity_topics_publication_age_freshness_schema_validity_traffic_rankings_backlinks_whole_site_or_causality"
SCHEMA_METHOD = "competitor-static-schema-comparison-v1"
SCHEMA_INTERPRETATION = "dated_selected_root_lexical_label_changes_not_resolved_schema_validity_actual_page_type_rich_results_topics_freshness_whole_site_or_causality"
LINKS_METHOD = "competitor-static-link-categories-comparison-v1"
LINKS_INTERPRETATION = "dated_selected_root_literal_reference_category_changes_not_destinations_unique_pages_browser_visibility_link_health_inbound_links_whole_site_structure_freshness_or_causality"

DESTINATIONS_METHOD = "competitor-page-references-pair-v1"
DESTINATIONS_INTERPRETATION = "dated_selected_nonroot_uri_literal_supported_same_origin_reference_order_changes_not_unique_pages_fetched_targets_link_health_browser_visibility_freshness_whole_site_causality_or_crawl_authority"

HEADINGS_METHOD = "competitor-page-headings-comparison-v1"
HEADINGS_INTERPRETATION = "dated_selected_nonroot_uri_literal_heading_text_order_changes_not_browser_semantic_outline_accessibility_topics_page_identity_freshness_whole_site_or_causality"


DATES_METHOD = "competitor-page-dates-pair-v1"
DATES_INTERPRETATION = "dated_selected_nonroot_uri_literal_article_date_declaration_order_changes_not_validated_dates_publication_change_age_freshness_cadence_page_identity_whole_site_or_causality"

FORMATS_METHOD = "competitor-page-elements-pair-v1"
FORMATS_INTERPRETATION = "dated_selected_nonroot_uri_literal_start_tag_count_changes_not_rendered_formats_loaded_media_semantic_page_types_accessibility_search_features_topics_freshness_whole_site_causality_or_collection_authority"


def _read_pair_sources(jobs, project, actor):
    callers = {job.pk: collection._read_source(job, project, actor) for job in jobs}
    # The last source read can cancel an original checked earlier in this pair.
    if JobCancellation.objects.filter(job_id__in=callers).exists(): raise PermissionDenied
    return callers


def compare_competitor_roots(*, project, actor, previous_job_id, current_job_id):
    return _compare_competitor_metadata(project=project, actor=actor,
        previous_job_id=previous_job_id, current_job_id=current_job_id)


def _compare_competitor_metadata(*, project, actor, previous_job_id, current_job_id, page=False, schema=False, links=False, headings=False, destinations=False, dates=False, formats=False):
    handler = "collect_competitor_page_formats" if formats else "collect_competitor_page_dates" if dates else "collect_competitor_page_destinations" if destinations else "collect_competitor_page_headings" if headings else "collect_competitor_schema_root" if schema else "collect_competitor_links_root" if links else "collect_competitor_page" if page else collection.HANDLER
    ids = (previous_job_id, current_job_id)
    if any(type(value) is not int or not 1 <= value < 2**53 for value in ids) or ids[0] == ids[1]:
        raise ValidationError("Choose two distinct actual original competitor jobs.")
    jobs = {row.pk: row for row in JobRun.objects.select_related("project", "actor").filter(
        pk__in=ids, project_id=project.pk, organization_id=project.organization_id,
        handler=handler, status=JobStatus.SUCCEEDED)}
    if len(jobs) != 2: raise PermissionDenied
    callers = _read_pair_sources((jobs[key] for key in ids), project, actor)
    original = {key: collection._read_metadata(key) for key in ids}
    if jobs[ids[0]].config_snapshot != jobs[ids[1]].config_snapshot:
        raise ValidationError("Compare the exact same original selected source, including original actor provenance.")
    observed = [collection.read_competitor_observation(project=project, actor=actor, job_id=key, handler=handler)["collection"] for key in ids]
    before, after = observed
    if (any(before[key] != after[key] for key in ("method_version", "requested_url", "url", "source_sha256"))
        or any(before["evidence"][key] != after["evidence"][key] for key in ("method_version", "coverage", "excluded_containers", "interpretation"))
        or _date(before["observed_at"]) >= _date(after["observed_at"])):
        raise ValidationError("Compare increasing original dates with the exact same URI, method and coverage.")
    if dates:
        comparable = all(item["evidence"]["state"] == "observed" and not any(
            declaration["truncated"] for declaration in item["evidence"]["declarations"]) for item in observed)
    elif headings:
        comparable = all(item["evidence"]["state"] == "observed" and not any(
            heading["truncated"] for heading in item["evidence"]["headings"]) for item in observed)
    else:
        comparable = all(item["evidence"]["state"] == "observed" and (formats or destinations or schema or links or not any(
            item["evidence"]["metadata"][key] for key in ("title_truncated", "description_truncated"))) for item in observed)
    result = {"method_version": FORMATS_METHOD if formats else DATES_METHOD if dates else DESTINATIONS_METHOD if destinations else HEADINGS_METHOD if headings else SCHEMA_METHOD if schema else LINKS_METHOD if links else PAGE_METHOD if page else METHOD, "organization_id": project.organization_id, "project_id": project.pk,
        "source_current": True, "collection_method": before["method_version"], "parser_method": before["evidence"]["method_version"],
        "url": before["url"], "source_sha256": before["source_sha256"],
        "previous": {"job_id": ids[0], "robots": before["robots"], "evidence": before["evidence"]},
        "current": {"job_id": ids[1], "robots": after["robots"], "evidence": after["evidence"]},
        "comparable": comparable,
        "body_changed": before["evidence"]["body_sha256"] != after["evidence"]["body_sha256"],
        "interpretation": FORMATS_INTERPRETATION if formats else DATES_INTERPRETATION if dates else DESTINATIONS_INTERPRETATION if destinations else HEADINGS_INTERPRETATION if headings else SCHEMA_INTERPRETATION if schema else LINKS_INTERPRETATION if links else PAGE_INTERPRETATION if page else INTERPRETATION}
    if formats:
        result.update(state="comparable_original_static_content_element_counts" if comparable else "incomparable_unavailable_content_element_counts",
            count_deltas={key: after["evidence"]["counts"][key] - before["evidence"]["counts"][key]
                for key in FORMAT_COUNTS} if comparable else None)
    elif dates:
        result.update(state="comparable_original_static_article_date_declarations" if comparable else "incomparable_unavailable_or_truncated_article_date_declarations",
            declarations_changed=before["evidence"]["declarations"] != after["evidence"]["declarations"] if comparable else None)
    elif destinations:
        result.update(state="comparable_original_static_supported_same_origin_references" if comparable else "incomparable_unavailable_supported_same_origin_references",
            destinations_changed=before["evidence"]["destinations"] != after["evidence"]["destinations"] if comparable else None,
            count_deltas={key: after["evidence"]["counts"][key] - before["evidence"]["counts"][key]
                for key in LINK_COUNTS} if comparable else None)
    elif headings:
        result.update(state="comparable_original_static_heading_text_and_order" if comparable else "incomparable_unavailable_or_truncated_heading_text",
            headings_changed=before["evidence"]["headings"] != after["evidence"]["headings"] if comparable else None,
            count_deltas={key: after["evidence"]["counts"][key] - before["evidence"]["counts"][key]
                for key in HEADING_COUNTS} if comparable else None)
    elif schema:
        result.update(state="comparable_original_static_schema_labels" if comparable else "incomparable_unavailable_schema_labels",
            type_changes={"added": sorted(set(after["evidence"]["summary"]["types"]) - set(before["evidence"]["summary"]["types"])),
                "removed": sorted(set(before["evidence"]["summary"]["types"]) - set(after["evidence"]["summary"]["types"]))} if comparable else None,
            count_deltas={key: after["evidence"]["summary"][key] - before["evidence"]["summary"][key]
                for key in ("json_ld_blocks", "typed_nodes", "unrecognized_type_count")} if comparable else None)
    elif links:
        result.update(state="comparable_original_static_link_categories" if comparable else "incomparable_unavailable_link_categories",
            count_deltas={key: after["evidence"]["counts"][key] - before["evidence"]["counts"][key]
                for key in LINK_COUNTS} if comparable else None)
    else:
        result.update(state="comparable_original_static_metadata" if comparable else "incomparable_unavailable_or_truncated_metadata",
            metadata_changed={key: before["evidence"]["metadata"][key] != after["evidence"]["metadata"][key]
                for key in ("title", "description")} if comparable else None,
            count_deltas={key: after["evidence"]["counts"][key] - before["evidence"]["counts"][key]
                for key in COUNTS} if comparable else None)
    # The second read may change the FIRST source/record. Fence both originals,
    # not only the last record, without substituting the independent reader's SHA.
    if any(collection._read_metadata(key) != original[key] for key in ids): raise PermissionDenied
    fresh = (JobRun.objects.select_related("project", "actor").get(pk=key, handler=handler) for key in ids)
    if _read_pair_sources(fresh, project, actor) != callers: raise PermissionDenied
    if any(collection._read_metadata(key) != original[key] for key in ids): raise PermissionDenied
    if JobCancellation.objects.filter(job_id__in=ids).exists(): raise PermissionDenied
    require_billable_access(organization=project.organization)
    return result
