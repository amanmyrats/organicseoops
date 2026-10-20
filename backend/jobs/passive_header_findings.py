"""Explicit original header findings, separate from ordinary project-read consumers."""
from copy import deepcopy
from hashlib import sha256
import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from tenancy.models import Organization, Project
from tenancy.support_requests import _safe_id
from . import passive_header_candidate_source as source
from . import passive_header_collection as collection
from .models import Finding, JobRun, JobStatus
from .passive_header_candidates import response_header_candidates


METHOD = "passive-header-finding-v1"
CONFIDENCE = "dated_response_fact_not_risk_severity"
FIELDS = ("source_passive_header_id", "detector", "method_version", "subject", "fingerprint", "evidence", "confidence")


def header_finding_values(*, job_id, binding, observation):
    """Pure bounded recipes; the digest binds minimized collection bytes, never raw headers."""
    _safe_id(job_id)
    report = response_header_candidates(observation, binding=binding)
    saved = []
    for candidate in report["candidates"]:
        evidence = {"source": "passive_response_headers", "job_id": job_id, "binding": deepcopy(report["binding"]),
            "collection_sha256": sha256(collection._encode(report["collection"])).hexdigest(),
            "observed_at": observation["observed_at"], "status": observation["status"],
            "fact": deepcopy(candidate["evidence"]), "coverage": report["coverage"], "interpretation": report["interpretation"]}
        if len(collection._encode(evidence)) > 4096:
            raise ValidationError("Original header finding exceeds the private evidence bound.")
        fingerprint = sha256(collection._encode([METHOD, candidate["detector"], evidence])).hexdigest()
        saved.append({"source_passive_header_id": job_id, "detector": candidate["detector"], "method_version": METHOD,
            "subject": binding["url"], "fingerprint": fingerprint, "evidence": evidence, "confidence": CONFIDENCE})
    return saved


def validate_header_finding(finding):
    job = finding.source_passive_header
    if (job.handler != collection.HANDLER or job.status != JobStatus.SUCCEEDED or job.error_category
        or not job.output or job.organization_id != finding.project.organization_id):
        raise ValidationError("A passive finding needs its genuine successful original header job.")
    collection.validate_job(job)
    observation = {key: value for key, value in job.output.items() if key not in {"artifact_id", "derived_sha256"}}
    recipes = header_finding_values(job_id=job.pk, binding=job.config_snapshot["binding"], observation=observation)
    if not _matches({key: getattr(finding, key) for key in FIELDS}, recipes):
        raise ValidationError("Passive finding identity and facts differ from the original observation.")


def _matches(values, recipes):
    try:
        return collection._encode(values) in [collection._encode(recipe) for recipe in recipes]
    except (TypeError, ValueError, RecursionError):
        raise ValidationError("Original passive finding facts must be bounded valid JSON.") from None


def _row_pin(rows):
    return json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)


def _rows(project, job_id):
    rows = list(Finding.objects.filter(project=project, source_passive_header_id=job_id).order_by("pk").values()[:11])
    if len(rows) > 10:
        raise ValidationError("Original header finding set exceeds its detector coverage.")
    return rows


def _validate_rows(rows, recipes, project, job_id):
    if rows and len(rows) != len(recipes):
        raise ValidationError("Retain the complete original materialized finding set.")
    job = JobRun.objects.select_related("project", "actor").get(pk=job_id)
    materializers = set()
    for row in rows:
        if (not _matches({key: row[key] for key in FIELDS}, recipes)
            or not collection._date(row["evidence"]["observed_at"]) <= row["detected_at"] <= timezone.now()):
            raise ValidationError("Stored original header finding needs review.")
        if row["actor_id"] not in materializers:
            finding = Finding.objects.select_related("actor").get(pk=row["id"], project=project)
            collection._read_source(job, project, finding.actor)
            materializers.add(row["actor_id"])


def _final_source(project, actor, job_id, original, report, rows):
    if source.current_header_candidates(project=project, actor=actor, job_id=job_id) != report:
        raise PermissionDenied
    recipes = header_finding_values(job_id=job_id, binding=report["binding"], observation=report["collection"])
    _validate_rows(rows, recipes, project, job_id)
    job = JobRun.objects.select_related("project", "actor").get(pk=job_id)
    collection._read_source(job, project, actor)
    if source._metadata(job_id, project=project, actor=actor, handler=collection.HANDLER) != original or _row_pin(_rows(project, job_id)) != _row_pin(rows):
        raise PermissionDenied


def record_header_findings(*, project, actor, job_id):
    _safe_id(job_id)
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        original = source._metadata(job_id, project=project, actor=actor, handler=collection.HANDLER)
        report = source.current_header_candidates(project=project, actor=actor, job_id=job_id)
        recipes = header_finding_values(job_id=job_id, binding=report["binding"], observation=report["collection"])
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


def current_header_findings(*, project, actor, job_id):
    """Current private original facts; historical CUSTOMER export uses separate authority."""
    _safe_id(job_id)
    original = source._metadata(job_id, project=project, actor=actor, handler=collection.HANDLER)
    report = source.current_header_candidates(project=project, actor=actor, job_id=job_id)
    recipes = header_finding_values(job_id=job_id, binding=report["binding"], observation=report["collection"])
    rows = _rows(project, job_id)
    _validate_rows(rows, recipes, project, job_id)
    result = {"method_version": METHOD, "project_id": project.pk, "job_id": job_id, "source_current": True,
        "state": "current_materialized_facts" if rows else "no_retained_materialized_findings",
        "findings": [{"id": row["id"], **{key: deepcopy(row[key]) for key in FIELDS},
            "detected_at": row["detected_at"].isoformat()} for row in rows]}
    _final_source(project, actor, job_id, original, report, rows)
    return result
