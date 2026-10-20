"""Exact current private facts for a subsequent explicit human prioritization decision."""
from copy import deepcopy
from hashlib import sha256

from django.core.exceptions import PermissionDenied

from tenancy.support_requests import _safe_id
from . import passive_header_collection as lifecycle
from . import passive_header_findings as headers
from . import passive_resource_findings as resources
from . import passive_tls_findings as tls
from . import passive_redirect_findings as redirects
from . import passive_redirect_chain_findings as chains
from .passive_header_collection import _encode
from .passive_header_findings import _row_pin
from .models import Finding, JobRun


METHOD = "passive-finding-review-source-v1"
INTERPRETATION = "original_passive_fact_for_human_prioritization_not_severity_approval_or_page_action"


def current_header_review_source(*, project, actor, job_id, finding_id):
    return _current(project, actor, job_id, finding_id, headers, headers.current_header_findings)


def current_resource_review_source(*, project, actor, job_id, finding_id):
    return _current(project, actor, job_id, finding_id, resources, resources.current_resource_findings)


def current_tls_review_source(*, project, actor, job_id, finding_id):
    return _current(project, actor, job_id, finding_id, tls, tls.current_tls_findings)


def current_redirect_review_source(*, project, actor, job_id, finding_id):
    return _current(project, actor, job_id, finding_id, redirects, redirects.current_redirect_findings)


def current_redirect_chain_review_source(*, project, actor, job_id, finding_id):
    return _current(project, actor, job_id, finding_id, chains, chains.current_redirect_chain_findings)


def _current(project, actor, job_id, finding_id, service, read):
    # Services come only from fixed entrypoints, never a client-selected family.
    _safe_id(job_id)
    _safe_id(finding_id)
    original = service.source._metadata(job_id, project=project, actor=actor, handler=service.source.collection.HANDLER)
    rows = service._rows(project, job_id)
    if not any(row["id"] == finding_id for row in rows):
        raise PermissionDenied
    report = read(project=project, actor=actor, job_id=job_id)
    finding = next((row for row in report["findings"] if row["id"] == finding_id), None)
    if finding is None:
        raise PermissionDenied
    result = {"method_version": METHOD, "organization_id": project.organization_id, "project_id": project.pk,
        "job_id": job_id, "source_current": True, "finding": deepcopy(finding),
        "source_sha256": sha256(_row_pin([METHOD, project.organization_id, project.pk, job_id, finding_id,
            original, rows]).encode()).hexdigest(), "interpretation": INTERPRETATION}
    # Repeat genuine current authority after projection, including each retained materializer.
    if _encode(read(project=project, actor=actor, job_id=job_id)) != _encode(report):
        raise PermissionDenied
    if (service.source._metadata(job_id, project=project, actor=actor, handler=service.source.collection.HANDLER) != original
        or _row_pin(service._rows(project, job_id)) != _row_pin(rows)):
        raise PermissionDenied
    # The last slow pins cannot retain earlier actor/source/commercial authority.
    job = JobRun.objects.select_related("project", "actor").get(pk=job_id)
    if lifecycle._row_pin(job) != original["job"]: raise PermissionDenied
    for materializer_id in {row["actor_id"] for row in rows}:
        finding = Finding.objects.select_related("actor").filter(project=project,
            pk__in=[row["id"] for row in rows], actor_id=materializer_id).first()
        if finding is None: raise PermissionDenied
        lifecycle._read_source(job, project, finding.actor)
    lifecycle._read_source(job, project, actor)
    return result
