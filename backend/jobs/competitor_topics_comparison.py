"""Literal labels from two saved cited AI samples; no semantic topic/gap claim."""
from urllib.parse import urlsplit

from django.core.exceptions import PermissionDenied, ValidationError

from . import competitor_collection as collection, competitor_synthesis as synthesis
from . import competitor_synthesis_job as original, competitor_topics_job as topics
from .models import JobCancellation, JobRun, JobStatus
from .usage import require_billable_access


METHOD = "competitor-heading-topic-label-pair-v1"
INTERPRETATION = "exact_original_unverified_ai_label_matches_and_unmatched_indices_not_semantic_shared_or_missing_page_topics_content_gaps_intent_freshness_rankings_whole_site_or_approval"
MAX_RESULT_BYTES = 100 * 1024


def compare_competitor_topic_labels(*, project, actor, first_job_id, second_job_id):
    ids = (first_job_id, second_job_id)
    for key in ids:
        collection._safe_id(key)
    if ids[0] == ids[1]:
        raise ValidationError("Choose two distinct saved topic-hypothesis jobs.")
    jobs = {job.pk: job for job in JobRun.objects.select_related("project", "actor").filter(
        pk__in=ids, project_id=project.pk, organization_id=project.organization_id,
        handler=topics.HANDLER, status=JobStatus.SUCCEEDED)}
    if len(jobs) != 2:
        raise PermissionDenied
    sources = {key: original._reader_source(jobs[key], project, actor) for key in ids}
    metadata = {key: original._read_metadata(key) for key in ids}
    heading_ids = tuple(jobs[key].input_snapshot["job_id"] for key in ids)
    headings = synthesis._pins(heading_ids)
    samples = [topics.read_competitor_topics(project=project, actor=actor, job_id=key) for key in ids]
    urls = [sample["synthesis"]["observation"]["collection"]["url"] for sample in samples]
    if urls[0] == urls[1] or urlsplit(urls[0])[:2] != urlsplit(urls[1])[:2]:
        raise ValidationError("Compare two different original page URIs on one exact origin.")
    labels = [[item["label"] for item in sample["synthesis"]["topics"]] for sample in samples]
    matches = [[first, second] for first, label in enumerate(labels[0])
        for second, other in enumerate(labels[1]) if label == other]
    result = {"method_version": METHOD, "organization_id": project.organization_id,
        "project_id": project.pk, "source_current": True, "samples": samples,
        "exact_label_match_indices": matches,
        "unmatched_topic_indices": [[i for i, label in enumerate(side) if label not in labels[1 - index]]
            for index, side in enumerate(labels)], "interpretation": INTERPRETATION}
    if len(collection._encode(result)) > MAX_RESULT_BYTES:
        raise ValidationError("The original topic-hypothesis pair exceeds its bounded size.")
    if any(original._read_metadata(key) != metadata[key] for key in ids) or synthesis._pins(heading_ids) != headings:
        raise PermissionDenied
    fresh = {key: JobRun.objects.select_related("project", "actor").get(pk=key, handler=topics.HANDLER) for key in ids}
    if {key: original._reader_source(fresh[key], project, actor) for key in ids} != sources:
        raise PermissionDenied
    if any(original._read_metadata(key) != metadata[key] for key in ids) or synthesis._pins(heading_ids) != headings:
        raise PermissionDenied
    # Final metadata reads can invalidate the original authority checked above.
    fresh = {key: JobRun.objects.select_related("project", "actor").get(pk=key, handler=topics.HANDLER) for key in ids}
    if {key: original._reader_source(fresh[key], project, actor) for key in ids} != sources:
        raise PermissionDenied
    if any(original._read_metadata(key) != metadata[key] for key in ids) or synthesis._pins(heading_ids) != headings:
        raise PermissionDenied
    if JobCancellation.objects.filter(job_id__in=(*ids, *heading_ids)).exists():
        raise PermissionDenied
    require_billable_access(organization=project.organization)
    return result
