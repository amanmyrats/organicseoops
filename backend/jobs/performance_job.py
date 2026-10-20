import json
from hashlib import sha256

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from providers.performance_key import google_performance_key, performance_key_reference
from config.artifacts import cleanup_private_artifacts, read_private_artifact, save_private_artifact
from tenancy.artifacts import project_artifact_scope
from tenancy.customer_artifact_barrier import project_artifact_barrier
from tenancy.models import Organization, Project
from tenancy.services import Action, require_project_action

from .crawler import _crawl_execution_lock
from .models import Artifact, JobCancellation, JobRun, JobStatus, JobStep, PerformanceObservationSnapshot, UsageReservation
from .performance import _scoped_url, parse_crux, parse_pagespeed_lab
from .performance_transport import LIMITS, PerformanceTransportError, google_performance_request
from .usage import settle_usage, usage_denial


METHOD = "performance-observation-v1"


def validate_performance_selection(data):
    if (type(data) is not dict or set(data) != {"target", "grain", "strategy", "sources"}
        or type(data["target"]) is not str or not 1 <= len(data["target"]) <= 2048
        or type(data["grain"]) is not str or type(data["strategy"]) is not str
        or data["grain"] not in {"page", "origin"}
        or data["strategy"] not in {"mobile", "desktop", "tablet"}
        or type(data["sources"]) is not list or not 1 <= len(data["sources"]) <= 3
        or any(type(source) is not str for source in data["sources"])
        or len(set(data["sources"])) != len(data["sources"])
        or not set(data["sources"]) <= set(PerformanceObservationSnapshot.Source.values)
        or ("psi_lab" in data["sources"] and (data["grain"] != "page" or data["strategy"] == "tablet"))):
        raise ValidationError("Choose up to three comparable bounded performance sources.")
    return data


def _credential_scope_changed(job, organization):
    current = performance_key_reference(organization=organization)
    return (job.config_snapshot.get("performance_credential") != current
            and ("performance_credential" in job.config_snapshot or current["source"] == "organization"))


def record_performance_observation(*, job, source, response):
    with project_artifact_barrier(job.organization_id, shared=True), transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=job.organization_id)
        project = Project.objects.select_for_update().get(pk=job.project_id, organization=organization)
        job = JobRun.objects.select_for_update(no_key=True).select_related("actor").get(pk=job.pk, project=project)
        data = validate_performance_selection(job.input_snapshot)
        if job.handler != "audit_performance" or job.method_version != METHOD or source not in data["sources"]:
            raise ValidationError("Performance evidence requires its own bounded audit job and source.")
        target = _scoped_url(project, data["target"], origin=data["grain"] == "origin")
        if target != data["target"]:
            raise ValidationError("Performance job target no longer matches its normalized project scope.")
        if source == "psi_lab":
            result = parse_pagespeed_lab(project=project, requested_url=target, strategy=data["strategy"], payload=response)
        else:
            result = parse_crux(project=project, requested_url=target, requested_grain=data["grain"],
                                form_factor={"mobile": "PHONE", "desktop": "DESKTOP", "tablet": "TABLET"}[data["strategy"]],
                                payload=response, history=source == "crux_history")
        raw = json.dumps(response, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
        if len(raw) > LIMITS[source]:
            raise ValidationError("Raw performance response exceeds its source limit.")
        digest = sha256(raw).hexdigest()
        previous = PerformanceObservationSnapshot.objects.filter(job=job, source=source).first()
        if previous is not None:
            if (previous.output == result and previous.raw_sha256 in {None, digest}
                and read_private_artifact(previous.raw_artifact.key) == raw):
                return previous
            raise ValidationError("This audit job already recorded different source evidence.")
        if job.status != JobStatus.RUNNING or JobCancellation.objects.filter(job=job).exists():
            raise PermissionDenied
        require_project_action(project=project, user=job.actor, action=Action.LAUNCH_JOB)
        if usage_denial(job=job):
            raise PermissionDenied
        if _credential_scope_changed(job, organization):
            raise PermissionDenied
        scope = f"{project_artifact_scope(project)}/jobs/{job.pk}"
        stem = PerformanceObservationSnapshot.artifact_stem(job.pk, source)
        key = save_private_artifact(scope=scope, content=raw, content_type="application/json", key_stem=stem)
        artifact = Artifact.objects.create(job=job, project=project, key=key,
                                           content_type="application/json", size_bytes=len(raw))
        snapshot = PerformanceObservationSnapshot(job=job, project=project, source=source, target=target,
                                                  grain=data["grain"], strategy=data["strategy"], output=result,
                                                  raw_artifact=artifact, raw_sha256=digest)
        snapshot.save()
        return snapshot


def _cleanup_performance_artifacts(job_id):
    job = JobRun.objects.select_related("project").filter(pk=job_id, handler="audit_performance").first()
    if job is not None:
        with project_artifact_barrier(job.organization_id, shared=True):
            cleanup_private_artifacts(scope=f"{project_artifact_scope(job.project)}/jobs/{job.pk}",
                                      keep_keys=set(job.artifacts.values_list("key", flat=True)))


def queue_performance_audit(*, project, actor, target, grain, strategy, sources, idempotency_key):
    from .services import queue_job

    data = validate_performance_selection({"target": target, "grain": grain, "strategy": strategy, "sources": sources})
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        require_project_action(project=project, user=actor, action=Action.LAUNCH_JOB)
        data["target"] = _scoped_url(project, data["target"], origin=grain == "origin")
        return queue_job(project=project, actor=actor, handler="audit_performance", input_snapshot=data,
                         config_snapshot={"performance_credential": performance_key_reference(organization=organization)},
                         idempotency_key=idempotency_key)


def _denial(job):
    if JobCancellation.objects.filter(job=job).exists():
        return "cancelled"
    try:
        require_project_action(project=job.project, user=job.actor, action=Action.LAUNCH_JOB)
    except PermissionDenied:
        return "actor_revoked"
    denied = usage_denial(job=job)
    if denied:
        return denied
    try:
        data = validate_performance_selection(job.input_snapshot)
        if (job.handler != "audit_performance" or job.method_version != METHOD
            or _scoped_url(job.project, data["target"], origin=data["grain"] == "origin") != data["target"]):
            return "scope_revoked"
        if _credential_scope_changed(job, job.organization):
            return "credential_unavailable"
    except ValidationError:
        return "scope_revoked"
    return ""


def _finish(job_id, error=""):
    with transaction.atomic():
        org_id = JobRun.objects.filter(pk=job_id).values_list("organization_id", flat=True).first()
        if org_id is None:
            return False
        Organization.objects.select_for_update().get(pk=org_id)
        job = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id)
        if job.handler != "audit_performance" or job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            return False
        denied = _denial(job)
        for step in JobStep.objects.filter(job=job, name="Collect performance source", status=JobStep.Status.RUNNING):
            step.status = JobStep.Status.FAILED
            step.error_category = denied or "request_outcome_unknown"
            step.output = {"source": step.output.get("source"), "state": "unknown"}
            step.save(update_fields=["status", "error_category", "output"])
        steps = list(JobStep.objects.filter(job=job, name="Collect performance source").order_by("sequence"))
        snapshots = list(PerformanceObservationSnapshot.objects.filter(job=job).order_by("source"))
        attempted = len(steps)
        lab_failed = any(item.source == "psi_lab" and (item.output.get("status") != "observed"
            or item.output["scores"].get("performance") is None) for item in snapshots)
        missing_field = any(item.source != "psi_lab" and any(
            metric["state"] != "observed" for metric in item.output["metrics"]
        ) for item in snapshots)
        failed = bool(error or any(step.status == JobStep.Status.FAILED for step in steps)
                      or attempted < len(job.input_snapshot["sources"]) or missing_field or lab_failed)
        category = denied or error or "partial_coverage" if failed or denied else ""
        if job.status == JobStatus.QUEUED and not denied:
            job.status = JobStatus.RUNNING
            job.save(update_fields=["status", "updated_at"])
        job.status = (JobStatus.CANCELLED if denied else JobStatus.PARTIALLY_SUCCEEDED if snapshots and failed
                      else JobStatus.FAILED if failed else JobStatus.SUCCEEDED)
        job.error_category = category
        job.output = {"requests_attempted": attempted, "sources_recorded": len(snapshots),
                      "lab": "observed" if any(item.source == "psi_lab" and item.output.get("status") == "observed"
                                            for item in snapshots) else "unavailable",
                      "field": "observed" if any(item.source != "psi_lab" and any(
                          metric["state"] == "observed" for metric in item.output["metrics"]) for item in snapshots)
                      else "unavailable", "coverage": "partial" if failed else "source_rows_only"}
        job.save(update_fields=["status", "error_category", "output", "updated_at"])
        if UsageReservation.objects.filter(job=job, state=UsageReservation.State.RESERVED).exists():
            settle_usage(job=job, actual_units=attempted)
        transaction.on_commit(lambda job_id=job.pk: _cleanup_performance_artifacts(job_id))
    return True


def execute_performance_audit(job_id, *, fetch=google_performance_request):
    organization_id = JobRun.objects.filter(pk=job_id).values_list("organization_id", flat=True).first()
    if organization_id is None:
        return False
    with project_artifact_barrier(organization_id, shared=True), _crawl_execution_lock(job_id) as acquired:
        if not acquired:
            return False
        try:
            return _execute(job_id, fetch=fetch)
        except Exception:
            return _finish(job_id, error="handler_failed")


def _execute(job_id, *, fetch):
    org_id = JobRun.objects.filter(pk=job_id).values_list("organization_id", flat=True).first()
    if org_id is None:
        return False
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=org_id)
        job = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id)
        if job.handler != "audit_performance" or job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            return False
        denied = _denial(job)
        if not denied and job.status == JobStatus.QUEUED:
            job.status = JobStatus.RUNNING
            job.save(update_fields=["status", "updated_at"])
    if denied:
        return _finish(job_id)
    try:
        key = google_performance_key(organization=job.organization)
    except ValidationError:
        return _finish(job_id, error="credential_unavailable")

    data = job.input_snapshot
    def checkpoint():
        fresh = JobRun.objects.select_related("project", "actor", "organization").get(pk=job_id)
        if _denial(fresh):
            raise PermissionDenied

    for sequence, source in enumerate(data["sources"], start=1):
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=org_id)
            current = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id)
            denied = _denial(current)
            if denied:
                return _finish(job_id)
            step = JobStep.objects.filter(job=current, sequence=sequence).first()
            if step is not None:
                if step.status == JobStep.Status.RUNNING:
                    step.status = JobStep.Status.FAILED
                    step.error_category = "request_outcome_unknown"
                    step.output = {"source": source, "state": "unknown"}
                    step.save(update_fields=["status", "error_category", "output"])
                continue
            JobStep.objects.create(job=current, sequence=sequence, name="Collect performance source",
                                   status=JobStep.Status.RUNNING, output={"source": source, "state": "attempted"})
            current.save(update_fields=["updated_at"])
        try:
            response = fetch(project=current.project, kind=source, target=data["target"],
                             strategy=data["strategy"], grain=data["grain"], api_key=key, checkpoint=checkpoint)
            snapshot = record_performance_observation(job=current, source=source, response=response)
        except PerformanceTransportError as exc:
            category = exc.category
        except (PermissionDenied, ValidationError):
            category = "source_unavailable"
        else:
            category = ""
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=org_id)
            current = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id)
            denied = _denial(current)
            step = JobStep.objects.select_for_update().get(job=current, sequence=sequence)
            step.status = JobStep.Status.FAILED if denied or category else JobStep.Status.SUCCEEDED
            step.error_category = denied or category
            step.output = {"source": source, "state": "unavailable"} if step.error_category else {
                "source": source, "state": "recorded", "snapshot_id": snapshot.pk}
            step.save(update_fields=["status", "error_category", "output"])
            current.save(update_fields=["updated_at"])
        if denied or category == "quota_limited":
            return _finish(job_id, error=denied or category)
    return _finish(job_id)
