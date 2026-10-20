"""Current private original selected-chain candidates, not retained-export or new capture authority."""
from django.core.exceptions import PermissionDenied

from tenancy.support_requests import _safe_id
from . import passive_header_collection as lifecycle
from . import passive_redirect_chain_collection as collection
from .models import JobRun, JobStatus
from .passive_header_candidate_source import _metadata
from .passive_redirect_chain_candidates import redirect_chain_review_candidates


def current_redirect_chain_candidates(*, project, actor, job_id):
    _safe_id(job_id)
    original = _metadata(job_id, project=project, actor=actor, handler=collection.HANDLER)
    source = collection.read_passive_redirect_chain_observation(project=project, actor=actor, job_id=job_id)
    if _metadata(job_id, project=project, actor=actor, handler=collection.HANDLER) != original: raise PermissionDenied
    report = redirect_chain_review_candidates(source["collection"], binding=original["job"]["config_snapshot"]["binding"])
    # Projection cannot retain authority from bytes or sources that are no longer current.
    if collection.read_passive_redirect_chain_observation(project=project, actor=actor, job_id=job_id) != source:
        raise PermissionDenied
    current = JobRun.objects.select_related("project", "actor").filter(pk=job_id, project_id=project.pk,
        organization_id=project.organization_id, handler=collection.HANDLER, status=JobStatus.SUCCEEDED).first()
    if current is None: raise PermissionDenied
    lifecycle._read_source(current, project, actor)
    if _metadata(job_id, project=project, actor=actor, handler=collection.HANDLER) != original: raise PermissionDenied
    current.refresh_from_db()
    if lifecycle._row_pin(current) != original["job"]: raise PermissionDenied
    lifecycle._read_source(current, project, actor)
    return {"job_id": job_id, "source_current": True, **report}
