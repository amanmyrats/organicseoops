"""Current private original Date evidence and bounded stored-literal syntax candidates."""
from django.core.exceptions import PermissionDenied, ValidationError

from . import competitor_collection as lifecycle, competitor_page_dates_collection as collection
from .competitor_date_candidates import article_date_literal_candidates
from .models import JobCancellation, JobRun, JobStatus
from .usage import require_billable_access


MAX_RESULT_BYTES = 24 * 1024


def current_date_candidates(*, project, actor, job_id):
    lifecycle._safe_id(job_id)
    def current_job():
        job = JobRun.objects.select_related("project", "actor").filter(pk=job_id, project_id=project.pk,
            organization_id=project.organization_id, handler=collection.HANDLER, status=JobStatus.SUCCEEDED).first()
        if job is None: raise PermissionDenied
        return job
    caller = lifecycle._read_source(current_job(), project, actor)
    original = lifecycle._read_metadata(job_id)
    saved = collection.read_competitor_page_dates_observation(project=project, actor=actor, job_id=job_id)
    report = article_date_literal_candidates(saved["collection"]["evidence"])
    result = {**saved, **{key: report[key] for key in ("method_version", "candidates", "interpretation")}}
    if len(lifecycle._encode(result)) > MAX_RESULT_BYTES:
        raise ValidationError("The original date-candidate source exceeds its bounded size.")
    if lifecycle._read_metadata(job_id) != original: raise PermissionDenied
    if lifecycle._read_source(current_job(), project, actor) != caller: raise PermissionDenied
    if lifecycle._read_metadata(job_id) != original or JobCancellation.objects.filter(job_id=job_id).exists():
        raise PermissionDenied
    require_billable_access(organization=project.organization)
    return result
