"""Explicit original literal-resource facts under their private source boundary."""
from copy import deepcopy
from hashlib import sha256

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from tenancy.models import Organization, Project
from tenancy.support_requests import _safe_id
from . import passive_header_collection as lifecycle
from . import passive_resource_candidate_source as source
from . import passive_resource_collection as collector
from .models import Finding, JobRun, JobStatus
from .passive_header_collection import _encode
from .passive_header_findings import _matches, _row_pin
from .passive_resource_candidates import static_resource_candidates


METHOD = "passive-resource-finding-v1"
CONFIDENCE = "dated_literal_fact_not_risk_severity"
FIELDS = ("source_passive_resource_id", "detector", "method_version", "subject", "fingerprint", "evidence", "confidence")


def resource_finding_values(*, job_id, binding, observation):
    """Compact original facts for the subsequent genuine resource JobRun relation."""
    _safe_id(job_id)
    report = static_resource_candidates(observation, binding=binding)
    saved = []
    for candidate in report["candidates"]:
        evidence = {"source": "passive_static_resource_references", "job_id": job_id, "binding": deepcopy(report["binding"]),
            "collection_sha256": sha256(_encode(report["collection"])).hexdigest(),
            "observed_at": observation["observed_at"], "status": observation["status"],
            "fact": deepcopy(candidate["evidence"]), "coverage": report["coverage"], "interpretation": report["interpretation"]}
        if len(_encode(evidence)) > 4096:
            raise ValidationError("Original resource finding exceeds the private evidence bound.")
        fingerprint = sha256(_encode([METHOD, candidate["detector"], evidence])).hexdigest()
        saved.append({"source_passive_resource_id": job_id, "detector": candidate["detector"], "method_version": METHOD,
            "subject": binding["url"], "fingerprint": fingerprint, "evidence": evidence, "confidence": CONFIDENCE})
    return saved


def validate_resource_finding(finding):
    job = finding.source_passive_resource
    if (job.handler != collector.HANDLER or job.status != JobStatus.SUCCEEDED or job.error_category
        or not job.output or job.organization_id != finding.project.organization_id):
        raise ValidationError("A resource finding needs its genuine successful original resource job.")
    collector.validate_job(job)
    observation = {key: value for key, value in job.output.items() if key not in {"artifact_id", "derived_sha256"}}
    recipes = resource_finding_values(job_id=job.pk, binding=job.config_snapshot["binding"], observation=observation)
    if not _matches({key: getattr(finding, key) for key in FIELDS}, recipes):
        raise ValidationError("Resource finding identity and facts differ from the original observation.")


def _rows(project, job_id):
    rows = list(Finding.objects.filter(project=project, source_passive_resource_id=job_id).order_by("pk").values()[:2])
    if len(rows) > 1:
        raise ValidationError("Original resource finding set exceeds its detector coverage.")
    return rows


def _validate_rows(rows, recipes, project, job_id):
    if rows and len(rows) != len(recipes):
        raise ValidationError("Retain the complete original materialized resource finding set.")
    job = JobRun.objects.select_related("project", "actor").get(pk=job_id)
    for row in rows:
        if (not _matches({key: row[key] for key in FIELDS}, recipes)
            or not lifecycle._date(row["evidence"]["observed_at"]) <= row["detected_at"] <= timezone.now()):
            raise ValidationError("Stored original resource finding needs review.")
        finding = Finding.objects.select_related("actor").get(pk=row["id"], project=project)
        lifecycle._read_source(job, project, finding.actor)


def _final_source(project, actor, job_id, original, report, rows):
    if source.current_resource_candidates(project=project, actor=actor, job_id=job_id) != report:
        raise PermissionDenied
    recipes = resource_finding_values(job_id=job_id, binding=report["binding"], observation=report["collection"])
    _validate_rows(rows, recipes, project, job_id)
    job = JobRun.objects.select_related("project", "actor").get(pk=job_id)
    lifecycle._read_source(job, project, actor)
    if source._metadata(job_id, project=project, actor=actor, handler=collector.HANDLER) != original or _row_pin(_rows(project, job_id)) != _row_pin(rows):
        raise PermissionDenied


def record_resource_findings(*, project, actor, job_id):
    _safe_id(job_id)
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        original = source._metadata(job_id, project=project, actor=actor, handler=collector.HANDLER)
        report = source.current_resource_candidates(project=project, actor=actor, job_id=job_id)
        recipes = resource_finding_values(job_id=job_id, binding=report["binding"], observation=report["collection"])
        rows = _rows(project, job_id)
        _validate_rows(rows, recipes, project, job_id)
        by_fingerprint = {row["fingerprint"]: row["id"] for row in rows}
        saved = []
        for recipe in recipes:
            existing = by_fingerprint.get(recipe["fingerprint"])
            saved.append(Finding.objects.get(pk=existing, project=project) if existing else
                Finding.objects.create(project=project, actor=actor, **recipe))
        expected = [{field.attname: getattr(row, field.attname) for field in Finding._meta.concrete_fields}
            for row in sorted(saved, key=lambda row: row.pk)]
        rows = _rows(project, job_id)
        if _row_pin(rows) != _row_pin(expected):
            raise PermissionDenied
        _final_source(project, actor, job_id, original, report, rows)
        return saved


def current_resource_findings(*, project, actor, job_id):
    """Current private original facts; CUSTOMER retained export has separate authority."""
    _safe_id(job_id)
    original = source._metadata(job_id, project=project, actor=actor, handler=collector.HANDLER)
    report = source.current_resource_candidates(project=project, actor=actor, job_id=job_id)
    recipes = resource_finding_values(job_id=job_id, binding=report["binding"], observation=report["collection"])
    rows = _rows(project, job_id)
    _validate_rows(rows, recipes, project, job_id)
    result = {"method_version": METHOD, "project_id": project.pk, "job_id": job_id, "source_current": True,
        "state": "current_materialized_facts" if rows else "no_retained_materialized_findings",
        "findings": [{"id": row["id"], **{key: deepcopy(row[key]) for key in FIELDS},
            "detected_at": row["detected_at"].isoformat()} for row in rows]}
    _final_source(project, actor, job_id, original, report, rows)
    return result
