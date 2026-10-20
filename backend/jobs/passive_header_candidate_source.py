"""Current private original header candidates under the existing passive-source boundary."""
from django.core.exceptions import PermissionDenied

from tenancy.support_requests import _safe_id
from tenancy.services import Action, require_project_action
from . import passive_header_collection as collection
from .models import JobCancellation, JobRun, JobStatus
from .passive_header_candidates import response_header_candidates


def _metadata(job_id, *, project, actor, handler):
    _safe_id(job_id)
    require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
    if not JobRun.objects.filter(pk=job_id, project_id=project.pk, organization_id=project.organization_id,
        handler=handler, status=JobStatus.SUCCEEDED).exists(): raise PermissionDenied
    return {**collection._read_metadata(job_id),
        "cancellation": JobCancellation.objects.filter(job_id=job_id).values().first()}


def current_header_candidates(*, project, actor, job_id):
    _safe_id(job_id)
    original = _metadata(job_id, project=project, actor=actor, handler=collection.HANDLER)
    source = collection.read_passive_header_observation(project=project, actor=actor, job_id=job_id)
    if _metadata(job_id, project=project, actor=actor, handler=collection.HANDLER) != original: raise PermissionDenied
    report = response_header_candidates(source["collection"], binding=original["job"]["config_snapshot"]["binding"])
    current = JobRun.objects.select_related("project", "actor").filter(pk=job_id, project_id=project.pk,
        organization_id=project.organization_id, handler=collection.HANDLER, status=JobStatus.SUCCEEDED).first()
    if current is None: raise PermissionDenied
    collection._read_source(current, project, actor)
    if _metadata(job_id, project=project, actor=actor, handler=collection.HANDLER) != original: raise PermissionDenied
    return {"job_id": job_id, "source_current": True, **report}
