"""Current private readback and deterministic positive overlap preview of genuine paired rows."""
from copy import deepcopy

from django.core.exceptions import PermissionDenied, ValidationError

from jobs.models import JobRun, JobStatus, JobStep
from tenancy.models import Project
from tenancy.services import Action, require_project_action

from .models import SearchAnalyticsQueryPageSnapshot
from .search_console_analytics import validate_query_page_snapshot
from .search_console_sync import _source


METHOD = "gsc-query-page-overlap-v1"


def paired_jobs(project, connection_id):
    return JobRun.objects.filter(project=project, organization_id=project.organization_id,
        handler="sync_search_console", input_snapshot__connection_id=connection_id,
        input_snapshot__report="query_page").order_by("-created_at", "-pk")


def require_paired_source(job, actor, *, latest=True):
    project = Project.objects.get(pk=job.project_id, organization_id=job.organization_id)
    require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
    require_project_action(project=project, user=job.actor, action=Action.MANAGE_PROJECT)
    if (job.handler != "sync_search_console" or job.method_version != "search-console-api-v1"
        or job.input_snapshot.get("report") != "query_page" or job.schedule_id or job.retry_of_id):
        raise ValidationError("Choose an actual manually selected paired report.")
    _source(project=project, organization=project.organization, data=job.input_snapshot, config=job.config_snapshot)
    if latest and paired_jobs(project, job.input_snapshot["connection_id"]).filter(
            input_snapshot__day=job.input_snapshot["day"]).values_list("pk", flat=True).first() != job.pk:
        raise ValidationError("A newer paired report superseded this exact source day.")
    return project


def paired_source_current(job, actor):
    try:
        require_paired_source(job, actor)
    except (PermissionDenied, ValidationError, Project.DoesNotExist):
        return False
    return True


def paired_job_metadata(job, actor):
    return {"id": job.pk, "status": job.status, "day": job.input_snapshot["day"],
        "property": job.config_snapshot.get("property_id"), "grant_revision": job.config_snapshot.get("grant_revision"),
        "created_at": job.created_at.isoformat(), "source_current": paired_source_current(job, actor),
        "error_category": job.error_category or job.dispatch_error,
        "requests_attempted": job.output.get("requests_attempted", 0), "pages_recorded": job.output.get("pages_recorded", 0),
        "snapshots": list(SearchAnalyticsQueryPageSnapshot.objects.filter(job=job).values(
            "id", "start_row", "result_sha256", "collected_at")[:2])}


def _read_paired_pages(job):
    pages = list(SearchAnalyticsQueryPageSnapshot.objects.filter(job=job).select_related(
        "job", "project", "connection", "grant").order_by("start_row")[:3])
    if not pages or len(pages) > 2 or pages[0].start_row != 0:
        raise ValidationError("Actual bounded paired page evidence is unavailable.")
    seen = set()
    for page in pages:
        validate_query_page_snapshot(page, current=False)
        if (page.start_row == 100 and (pages[0].result["next_start_row"] != 100 or len(pages) != 2)
            or page.collected_at is None or page.collected_at < job.created_at
            or not JobStep.objects.filter(job=job, sequence=2 + page.start_row // 100,
                name="Search Analytics page", status=JobStep.Status.SUCCEEDED,
                output={"state": "recorded", "snapshot_id": page.pk, "next_start_row": page.result["next_start_row"],
                        "result_sha256": page.result_sha256}).exists()):
            raise ValidationError("Paired source completion, dates or stage integrity is unavailable.")
        for row in page.result["observations"]:
            pair = (row["query"], row["page"])
            if pair in seen:
                raise ValidationError("Paired source contains a duplicate exact pair.")
            seen.add(pair)
    if job.status == JobStatus.SUCCEEDED and len(pages) == 1 and pages[0].result["next_start_row"] is not None:
        raise ValidationError("The claimed successful paired report lacks its required second page.")
    return pages


def read_paired_evidence(*, project, actor, connection_id, job_id):
    if type(job_id) is not int or not 1 <= job_id <= 9007199254740991:
        raise ValidationError("Choose one exact safe paired job identifier.")
    job = paired_jobs(project, connection_id).filter(pk=job_id).select_related("actor").first()
    if job is None:
        raise PermissionDenied
    require_paired_source(job, actor)
    if job.status not in {JobStatus.SUCCEEDED, JobStatus.PARTIALLY_SUCCEEDED}:
        raise ValidationError("Inspect a completed actual paired report, not an attempted or cancelled request.")
    pages = _read_paired_pages(job)
    groups = {}
    for page in pages:
        for index, row in enumerate(page.result["observations"]):
            if row["impressions"] > 0:
                groups.setdefault(row["query"], []).append({"snapshot_id": page.pk,
                    "result_sha256": page.result_sha256, "row_index": index})
    candidates = [{"query": query, "evidence": refs, "classification": "positive_same_query_distinct_page_candidate"}
        for query, refs in groups.items() if len(refs) > 1]
    metadata = paired_job_metadata(job, actor)
    payload = {"method": METHOD, "organization_id": project.organization_id, "project_id": project.pk,
        "connection_id": connection_id, "job": metadata,
        "pages": [{"id": page.pk, "start_row": page.start_row, "collected_at": page.collected_at.isoformat(),
            "result_sha256": page.result_sha256, "result": deepcopy(page.result)} for page in pages],
        "candidates": candidates[:20], "candidates_truncated": len(candidates) > 20,
        "candidate_state": "positive_overlap_candidates" if candidates else "no_positive_overlap_in_bounded_rows_not_absence",
        "interpretation": "human_review_only_not_proven_intent_conflict_causal_loss_live_rank_complete_demand_or_deletion",
        "provider_completeness": "not_established", "hidden_queries": "unknown"}
    # Final delivery follows all stored reads and metadata/candidate work. Never return cached usable evidence after loss.
    current = paired_jobs(project, connection_id).get(pk=job.pk)
    if (current.status != job.status or current.input_snapshot != job.input_snapshot
        or current.config_snapshot != job.config_snapshot or current.output != job.output
        or current.actor_id != job.actor_id):
        raise ValidationError("Paired job changed during readback.")
    final_pages = _read_paired_pages(current)
    if [(page.pk, page.result_sha256, page.result, page.collected_at) for page in final_pages] != [
            (page.pk, page.result_sha256, page.result, page.collected_at) for page in pages]:
        raise ValidationError("Paired evidence changed during delivery.")
    require_paired_source(current, actor)
    return payload
