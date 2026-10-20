"""Compact original chain facts, separate from ordinary project-read consumers."""
from copy import deepcopy
from hashlib import sha256

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from tenancy.models import Organization, Project
from tenancy.support_requests import _safe_id
from . import passive_header_collection as lifecycle
from . import passive_redirect_chain_candidate_source as source
from . import passive_redirect_chain_collection as collector
from .models import Finding, JobRun, JobStatus
from .passive_header_collection import _encode
from .passive_header_findings import _matches, _row_pin
from .passive_redirect_chain_candidates import redirect_chain_review_candidates


METHOD = "passive-redirect-chain-finding-v1"
CONFIDENCE = "dated_chain_fact_not_risk_severity"
FIELDS = ("source_passive_redirect_chain_id", "detector", "method_version", "subject", "fingerprint", "evidence", "confidence")


def redirect_chain_finding_values(*, job_id, binding, observation):
    """Hashes bind complete minimized originals, not raw fields or reconstructed grants."""
    _safe_id(job_id)
    report = redirect_chain_review_candidates(observation, binding=binding)
    saved = []
    for candidate in report["candidates"]:
        evidence = {"source": "passive_exact_selected_redirect_chain", "job_id": job_id,
            "binding": deepcopy({key: binding[key] for key in ("method_version", "organization_id", "project_id", "actor_id",
                "source_digest", "observations", "collection_permission")}),
            "binding_sha256": sha256(_encode(report["binding"])).hexdigest(),
            "collection_sha256": sha256(_encode(report["collection"])).hexdigest(),
            "observed_at": observation["observed_at"], "last_observed_at": observation["last_observed_at"],
            "captures": [{"hop": index, "scheme": hop["url"].split(":", 1)[0], "status": hop["status"], "observed_at": hop["observed_at"]}
                for index, hop in enumerate(observation["evidence"]["hops"])],
            "availability": deepcopy(report["availability"]), "fact": deepcopy(candidate["evidence"]),
            "coverage": report["coverage"], "interpretation": report["interpretation"]}
        if len(_encode(evidence)) > 4096:
            raise ValidationError("Original chain finding exceeds the private evidence bound.")
        fingerprint = sha256(_encode([METHOD, candidate["detector"], evidence])).hexdigest()
        saved.append({"source_passive_redirect_chain_id": job_id, "detector": candidate["detector"], "method_version": METHOD,
            "subject": binding["url"], "fingerprint": fingerprint, "evidence": evidence, "confidence": CONFIDENCE})
    return saved


def validate_redirect_chain_finding(finding):
    job = finding.source_passive_redirect_chain
    if (job.handler != collector.HANDLER or job.status != JobStatus.SUCCEEDED or job.error_category
        or not job.output or job.organization_id != finding.project.organization_id):
        raise ValidationError("A chain finding needs its genuine successful original chain job.")
    collector.validate_job(job)
    observation = {key: value for key, value in job.output.items() if key not in {"artifact_id", "derived_sha256"}}
    recipes = redirect_chain_finding_values(job_id=job.pk, binding=job.config_snapshot["binding"], observation=observation)
    if not _matches({key: getattr(finding, key) for key in FIELDS}, recipes):
        raise ValidationError("Chain finding identity and facts differ from the original observation.")


def _rows(project, job_id):
    rows = list(Finding.objects.filter(project=project, source_passive_redirect_chain_id=job_id).order_by("pk").values()[:3])
    if len(rows) > 2:
        raise ValidationError("Original chain finding set exceeds its detector coverage.")
    return rows


def _validate_rows(rows, recipes, project, job_id):
    if rows and (len(rows) != len(recipes) or {row["fingerprint"] for row in rows} != {recipe["fingerprint"] for recipe in recipes}):
        raise ValidationError("Retain the complete original materialized chain finding set.")
    job = JobRun.objects.select_related("project", "actor").get(pk=job_id)
    materializers = set()
    for row in rows:
        if (not _matches({key: row[key] for key in FIELDS}, recipes)
            or not lifecycle._date(row["evidence"]["last_observed_at"]) <= row["detected_at"] <= timezone.now()):
            raise ValidationError("Stored original chain finding needs review.")
        if row["actor_id"] not in materializers:
            finding = Finding.objects.select_related("actor").get(pk=row["id"], project=project)
            lifecycle._read_source(job, project, finding.actor)
            materializers.add(row["actor_id"])


def _final_source(project, actor, job_id, original, report, rows):
    if source.current_redirect_chain_candidates(project=project, actor=actor, job_id=job_id) != report:
        raise PermissionDenied
    recipes = redirect_chain_finding_values(job_id=job_id, binding=report["binding"], observation=report["collection"])
    _validate_rows(rows, recipes, project, job_id)
    if (source._metadata(job_id, project=project, actor=actor, handler=collector.HANDLER) != original
        or _row_pin(_rows(project, job_id)) != _row_pin(rows)):
        raise PermissionDenied
    # Slow metadata/row validation cannot leave earlier source or commercial authority current.
    job = JobRun.objects.select_related("project", "actor").get(pk=job_id)
    if lifecycle._row_pin(job) != original["job"]: raise PermissionDenied
    for materializer_id in {row["actor_id"] for row in rows}:
        materializer = Finding.objects.select_related("actor").filter(project=project,
            source_passive_redirect_chain_id=job_id, actor_id=materializer_id).first()
        if materializer is None: raise PermissionDenied
        lifecycle._read_source(job, project, materializer.actor)
    lifecycle._read_source(job, project, actor)


def record_redirect_chain_findings(*, project, actor, job_id):
    _safe_id(job_id)
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        original = source._metadata(job_id, project=project, actor=actor, handler=collector.HANDLER)
        report = source.current_redirect_chain_candidates(project=project, actor=actor, job_id=job_id)
        recipes = redirect_chain_finding_values(job_id=job_id, binding=report["binding"], observation=report["collection"])
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
        if _row_pin(rows) != _row_pin(expected): raise PermissionDenied
        _final_source(project, actor, job_id, original, report, rows)
        return saved


def current_redirect_chain_findings(*, project, actor, job_id):
    """Current private facts; retained CUSTOMER export has independent owner authority."""
    _safe_id(job_id)
    original = source._metadata(job_id, project=project, actor=actor, handler=collector.HANDLER)
    report = source.current_redirect_chain_candidates(project=project, actor=actor, job_id=job_id)
    recipes = redirect_chain_finding_values(job_id=job_id, binding=report["binding"], observation=report["collection"])
    rows = _rows(project, job_id)
    _validate_rows(rows, recipes, project, job_id)
    result = {"method_version": METHOD, "project_id": project.pk, "job_id": job_id, "source_current": True,
        "state": "current_materialized_facts" if rows else "no_retained_materialized_findings",
        "findings": [{"id": row["id"], **{key: deepcopy(row[key]) for key in FIELDS},
            "detected_at": row["detected_at"].isoformat()} for row in rows]}
    _final_source(project, actor, job_id, original, report, rows)
    return result
