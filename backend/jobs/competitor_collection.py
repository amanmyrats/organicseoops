"""One declared competitor document, committed attempt, original minimized private evidence."""
from datetime import datetime
from hashlib import sha256
import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.utils import timezone

from config.artifacts import ArtifactNotFound, ArtifactStorageError, ArtifactValidationError
from integrations.google_tokens import GoogleTokenError, _reject_constant, _unique_object
from tenancy.artifacts import delete_project_artifact, read_project_artifact, save_project_artifact
from tenancy.customer_artifact_barrier import project_artifact_barrier
from tenancy.models import Organization, Project
from tenancy.support_requests import _safe_id
from .competitor_fetch import ERRORS, INTERPRETATION, METHOD, collect_competitor_metadata
from .competitor_metadata import MAX_RESULT_BYTES, validate_metadata
from .competitor_source import _origin, current_competitor_source
from .crawler import _crawl_execution_lock
from .models import Artifact, JobCancellation, JobRun, JobStatus, JobStep, SourceCitation, UsageReservation
from .passive_header_collection import JOB_FIELDS, _execution_pin, _job_pin, _row_pin
from .passive_tls_evidence import _date
from .usage import require_billable_access, settle_usage, usage_denial


HANDLER = "collect_competitor_root"
COMPETITOR_HANDLERS = (HANDLER, "collect_competitor_schema_root", "collect_competitor_links_root", "collect_competitor_page", "collect_competitor_page_headings", "collect_competitor_page_destinations", "collect_competitor_page_dates", "collect_competitor_page_formats")
LIGHTHOUSE_HANDLER = "collect_competitor_lighthouse"
COMPETITOR_OBSERVATION_HANDLERS = (*COMPETITOR_HANDLERS, LIGHTHOUSE_HANDLER)
STAGE = "Collect selected competitor root"
PROVIDER = "competitor_source"


def validate_input(data, *, handler=HANDLER):
    if handler == LIGHTHOUSE_HANDLER:
        from .competitor_lab_collection import validate_input as validate_lab_input
        return validate_lab_input(data)
    if handler in {"collect_competitor_page", "collect_competitor_page_headings", "collect_competitor_page_destinations", "collect_competitor_page_dates", "collect_competitor_page_formats"}:
        from .competitor_page_collection import validate_input as validate_page_input
        return validate_page_input(data)
    if (type(data) is not dict or set(data) != {"origin", "collection_permission", "use_permission", "storage_permission"}
        or any(data[key] is not True for key in ("collection_permission", "use_permission", "storage_permission"))):
        raise ValidationError("Select one competitor and separately declare collection, independent use and storage permission.")
    _origin(data["origin"])
    return dict(data)


def _collection_contract(handler):
    if handler == LIGHTHOUSE_HANDLER:
        from . import competitor_lab_collection as lab
        return lab.METHOD, lab.STAGE, lab.collect_competitor_lab, lab.validate_result
    if handler == HANDLER:
        return METHOD, STAGE, collect_competitor_metadata, validate_result
    if handler == "collect_competitor_schema_root":
        from . import competitor_schema_collection as schema
        return schema.METHOD, schema.STAGE, schema.collect_competitor_schema, schema.validate_result
    if handler == "collect_competitor_links_root":
        from . import competitor_links_collection as links
        return links.METHOD, links.STAGE, links.collect_competitor_links, links.validate_result
    if handler == "collect_competitor_page":
        from . import competitor_page_collection as page
        return page.METHOD, page.STAGE, page.collect_competitor_page_metadata, page.validate_result
    if handler == "collect_competitor_page_formats":
        from . import competitor_page_formats_collection as formats
        return formats.METHOD, formats.STAGE, formats.collect_competitor_page_formats, formats.validate_result
    if handler == "collect_competitor_page_dates":
        from . import competitor_page_dates_collection as dates
        return dates.METHOD, dates.STAGE, dates.collect_competitor_page_dates, dates.validate_result
    if handler == "collect_competitor_page_destinations":
        from . import competitor_page_destinations_collection as destinations
        return destinations.METHOD, destinations.STAGE, destinations.collect_competitor_page_destinations, destinations.validate_result
    if handler == "collect_competitor_page_headings":
        from . import competitor_page_headings_collection as headings
        return headings.METHOD, headings.STAGE, headings.collect_competitor_page_headings, headings.validate_result
    raise ValidationError("Choose an explicit supported competitor observation.")


def selection_snapshot(project, actor, data, *, handler=HANDLER):
    method, *_ = _collection_contract(handler)
    data = validate_input(data, handler=handler)
    return {"method": method, "binding": _source_snapshot(project, actor, data, handler),
        "use_permission": True, "storage_permission": True}


def _source_snapshot(project, actor, data, handler):
    if handler == LIGHTHOUSE_HANDLER:
        from .competitor_lab_selection import selection_snapshot as lab_selection
        return lab_selection(project=project, actor=actor, data={key:value for key,value in data.items() if key not in {"use_permission", "storage_permission"}})
    selected = {"origin": data["origin"], "collection_permission": True}
    if handler in {"collect_competitor_page", "collect_competitor_page_headings", "collect_competitor_page_destinations", "collect_competitor_page_dates", "collect_competitor_page_formats"}:
        from .competitor_page_source import current_competitor_page_source
        selected["url"] = data["url"]
        return current_competitor_page_source(project=project, actor=actor, data=selected)
    return current_competitor_source(project=project, actor=actor, data=selected)


def _encode(result):
    return json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def validate_result(result, binding):
    return _validate_result(result, binding, method=METHOD, check_evidence=validate_metadata)


def _validate_result(result, binding, *, method, check_evidence, page=False):
    from .competitor_fetch import PAGE_INTERPRETATION
    if (type(result) is not dict or set(result) != {"method_version", "state", "requested_url", "url", "observed_at",
        "robots", "source_sha256", "evidence", "interpretation"} or result["method_version"] != method
        or result["state"] != "collected" or result["requested_url"] != (binding.get("url") if page else binding["origin"] + "/")
        or result["url"] != result["requested_url"] or result["source_sha256"] != binding["source_sha256"]
        or type(result["robots"]) is not str or result["robots"] not in {"available", "missing_http_404_or_410"}
        or result["interpretation"] != (PAGE_INTERPRETATION if page else INTERPRETATION)):
        raise ValidationError("Retain only original minimized selected-document evidence.")
    check_evidence(result["evidence"])
    if (result["evidence"]["url"] != result["url"] or result["evidence"]["observed_at"] != result["observed_at"]
        or _date(result["observed_at"]) < _date(binding["configuration_updated_at"], microseconds=False)
        or len(_encode(result)) > MAX_RESULT_BYTES):
        raise ValidationError("Original bounded competitor evidence/date is unavailable.")
    return result


def validate_job(job, *, current=False):
    method, _stage, _producer, check_result = _collection_contract(job.handler)
    data = validate_input(job.input_snapshot, handler=job.handler)
    config = job.config_snapshot
    if (job.method_version != method or job.retry_of_id or job.schedule_id or job.scheduled_for
        or type(config) is not dict or set(config) != {"method", "binding", "use_permission", "storage_permission"}
        or config["method"] != method or config["use_permission"] is not True or config["storage_permission"] is not True
        or type(config["binding"]) is not dict):
        raise ValidationError("Competitor jobs require their original declared manual source; no retry or schedule.")
    binding = config["binding"]
    if job.handler == LIGHTHOUSE_HANDLER:
        from .competitor_lab_collection import binding_page
        binding = binding_page(binding, data)
    if (job.handler in {"collect_competitor_page", "collect_competitor_page_headings", "collect_competitor_page_destinations", "collect_competitor_page_dates", "collect_competitor_page_formats"} and binding.get("url") != data["url"]
        or (binding.get("organization_id"), binding.get("project_id"), binding.get("actor_id"),
            binding.get("origin"), binding.get("collection_permission")) !=
           (job.organization_id, job.project_id, job.actor_id, data["origin"], True)):
        raise ValidationError("Competitor jobs require their original declared manual source; no retry or schedule.")
    if job.output:
        result = {key: value for key, value in job.output.items() if key not in {"artifact_id", "derived_sha256"}}
        check_result(result, config["binding"])
        if set(job.output) != set(result) | {"artifact_id", "derived_sha256"}: raise ValidationError("Invalid private evidence.")
        _safe_id(job.output["artifact_id"])
        if job.output["derived_sha256"] != sha256(_encode(result)).hexdigest(): raise ValidationError("Invalid private evidence digest.")
    if current and selection_snapshot(job.project, job.actor, data, handler=job.handler) != config: raise PermissionDenied


def queue_competitor_collection(*, project, actor, data, idempotency_key, handler=HANDLER):
    from .services import queue_job
    data = validate_input(data, handler=handler)
    with transaction.atomic():
        org = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=org)
        config = selection_snapshot(project, actor, data, handler=handler)
        job = queue_job(project=project, actor=actor, handler=handler, input_snapshot=data,
            config_snapshot=config, idempotency_key=idempotency_key)
        validate_job(job, current=True)
        if job.status == JobStatus.QUEUED and _denial(job): raise PermissionDenied
        return job


def _denial(job, original=None):
    if JobCancellation.objects.filter(job=job).exists(): return "cancel_requested"
    if original is not None and _execution_pin(job) != original: return "source_scope_changed"
    reservation = UsageReservation.objects.filter(job=job).first()
    if (reservation is None or (reservation.organization_id, reservation.project_id, reservation.provider, reservation.reserved_units)
        != (job.organization_id, job.project_id, PROVIDER, 1)): return "usage_unreserved"
    denied = usage_denial(job=job)
    if denied: return denied
    try: validate_job(job, current=True)
    except (PermissionDenied, ValidationError, Project.DoesNotExist): return "source_scope_changed"
    return ""


def _observation_date(result, handler):
    return _date(result["evidence"]["received_at"] if handler == LIGHTHOUSE_HANDLER else result["observed_at"])


def _finish(job_id, *, result=None, error="", original=None):
    org_id = JobRun.objects.filter(pk=job_id, handler__in=COMPETITOR_OBSERVATION_HANDLERS).values_list("organization_id", flat=True).first()
    if org_id is None: return False
    key = None
    project = None
    try:
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=org_id)
            job = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id, handler__in=COMPETITOR_OBSERVATION_HANDLERS)
            method, stage, _producer, check_result = _collection_contract(job.handler)
            if job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}: return False
            project = Project.objects.select_for_update().get(pk=job.project_id, organization_id=org_id)
            original = original or _execution_pin(job)
            denied = _denial(job, original)
            step = job.steps.filter(sequence=1).first()
            if job.status == JobStatus.QUEUED:
                job.status = JobStatus.RUNNING
                job.save(update_fields=["status", "updated_at"])
            useful = bool(result is not None and not denied)
            if useful:
                check_result(result, job.config_snapshot["binding"])
                if step is None or job.steps.count() != 1: raise ValidationError("Original committed attempt is unavailable.")
                if _observation_date(result, job.handler) < step.created_at or job.handler == LIGHTHOUSE_HANDLER and _date(result["request_started_at"]) < step.created_at: raise ValidationError("Observation precedes its committed attempt.")
                content = _encode(result)
                key = save_project_artifact(project=project, content=content, content_type="application/json")
                denied = _denial(JobRun.objects.select_related("project", "actor").get(pk=job_id), original)
                useful = not denied
                if useful:
                    artifact = Artifact.objects.create(job=job, project=project, key=key, content_type="application/json", size_bytes=len(content))
                    job.output = {**result, "artifact_id": artifact.pk, "derived_sha256": sha256(content).hexdigest()}
                    citation = SourceCitation.objects.create(job=job, step=step, source_title=stage, source_url=result["url"],
                        observed_at=_observation_date(result, job.handler))
                    if _denial(JobRun.objects.select_related("project", "actor").get(pk=job_id), original): raise PermissionDenied
            if not useful and key:
                delete_project_artifact(project=project, key=key)
                key = None
            if step:
                step.status = JobStep.Status.SUCCEEDED if useful else JobStep.Status.FAILED
                step.progress_percent = 100
                step.error_category = denied or error
                step.output = {"method": method, "state": "collected" if useful else "unavailable"}
                step.save(update_fields=["status", "progress_percent", "error_category", "output"])
            if useful and _denial(JobRun.objects.select_related("project", "actor").get(pk=job_id), original): raise PermissionDenied
            job.status = JobStatus.CANCELLED if denied else JobStatus.SUCCEEDED if useful else JobStatus.FAILED
            job.error_category = denied or error
            if not useful: job.output = {}
            job.save(update_fields=["status", "error_category", "output", "updated_at"])
            if UsageReservation.objects.filter(job=job, state=UsageReservation.State.RESERVED).exists():
                usage = settle_usage(job=job, actual_units=int(step is not None))
            if useful:
                current = JobRun.objects.select_related("project", "actor").get(pk=job_id, handler=job.handler)
                validate_job(current, current=True)
                require_billable_access(organization=project.organization)
                if (_execution_pin(current) != original or current.status != JobStatus.SUCCEEDED or current.output != job.output
                    or JobCancellation.objects.filter(job=current).exists()
                    or not UsageReservation.objects.filter(job=current, state="settled", actual_units=1).exists()): raise PermissionDenied
                intended = {"job": {**_job_pin(job), "status": job.status, "output": job.output,
                    "error_category": job.error_category, "updated_at": job.updated_at}, "steps": [_row_pin(step)],
                    "artifacts": [_row_pin(artifact)], "citations": [_row_pin(citation)], "usage": _row_pin(usage)}
                if _read_metadata(job_id) != intended: raise PermissionDenied
                if read_competitor_observation(project=project, actor=job.actor, job_id=job_id, handler=job.handler)["collection"] != result:
                    raise PermissionDenied
                if _read_metadata(job_id) != intended: raise PermissionDenied
                current = JobRun.objects.select_related("project", "actor").get(pk=job_id, handler=job.handler)
                validate_job(current, current=True)
                if _read_metadata(job_id) != intended: raise PermissionDenied
                if (_execution_pin(current) != original or current.status != JobStatus.SUCCEEDED or current.output != job.output
                    or JobCancellation.objects.filter(job=current).exists()): raise PermissionDenied
                require_billable_access(organization=project.organization)
    except Exception:
        if key: delete_project_artifact(project=project, key=key)
        raise
    return True


def execute_competitor_collection(job_id, *, fetcher=None, handler=HANDLER):
    _collection_contract(handler)
    if not JobRun.objects.filter(pk=job_id, handler=handler).exists(): return False
    if connection.in_atomic_block:
        raise ValidationError("Competitor attempts must commit outside a caller transaction before any request.")
    organization_id = JobRun.objects.filter(pk=job_id, handler=handler).values_list("organization_id", flat=True).first()
    if organization_id is None:
        return False
    with project_artifact_barrier(organization_id, shared=True), _crawl_execution_lock(job_id) as acquired:
        if not acquired: return False
        try: return _execute(job_id, fetcher=fetcher, handler=handler)
        except Exception: return _finish(job_id, error="handler_failed")


def _execute(job_id, *, fetcher, handler=HANDLER):
    method, stage, producer, check_result = _collection_contract(handler)
    org_id = JobRun.objects.filter(pk=job_id, handler=handler).values_list("organization_id", flat=True).first()
    if org_id is None: return False
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=org_id)
        job = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id, handler=handler)
        if job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}: return False
        if _denial(job): return _finish(job_id)
        if job.steps.exists(): return _finish(job_id, error="request_outcome_unknown")
        original = _execution_pin(job)
        if job.status == JobStatus.QUEUED:
            job.status = JobStatus.RUNNING
            job.save(update_fields=["status", "updated_at"])
        JobStep.objects.create(job=job, sequence=1, name=stage, status=JobStep.Status.RUNNING,
            output={"method": method, "state": "attempted"})
    def checkpoint():
        current = JobRun.objects.select_related("project", "actor").get(pk=job_id, handler=handler)
        if current.status != JobStatus.RUNNING or _denial(current, original): raise PermissionDenied
    try:
        result = producer(project=job.project, actor=job.actor, binding=job.config_snapshot["binding"],
            before_request=checkpoint, fetcher=fetcher)
    except Exception:
        # Preserve the committed original pins when a transport checkpoint fails;
        # recovery must not accept a mutated reservation as a fresh baseline.
        return _finish(job_id, error="handler_failed", original=original)
    if result.get("state") == "unavailable":
        error = result.get("error_category")
        errors = ERRORS
        if handler == LIGHTHOUSE_HANDLER:
            from .competitor_lab_fetch import ERRORS as errors
        return _finish(job_id, error=error if type(error) is str and error in errors else "handler_failed", original=original)
    check_result(result, job.config_snapshot["binding"])
    return _finish(job_id, result=result, original=original)


def _read_source(job, project, actor):
    validate_job(job, current=True)
    # a's SHA includes the ORIGINAL actor membership/role. Check caller authority
    # independently; replacing actor_id in a caller-derived digest cannot match it.
    caller = _source_snapshot(project, actor, job.input_snapshot, job.handler)
    require_billable_access(organization=project.organization)
    validate_job(JobRun.objects.select_related("project", "actor").get(pk=job.pk, handler=job.handler), current=True)
    if JobCancellation.objects.filter(job=job).exists(): raise PermissionDenied
    require_billable_access(organization=project.organization)
    return caller


def _read_metadata(job_id):
    return {"job": JobRun.objects.filter(pk=job_id, handler__in=COMPETITOR_OBSERVATION_HANDLERS).values(*JOB_FIELDS, "status", "output", "error_category", "updated_at").first(),
        "steps": list(JobStep.objects.filter(job_id=job_id).order_by("pk").values()[:2]),
        "artifacts": list(Artifact.objects.filter(job_id=job_id).order_by("pk").values()[:2]),
        "citations": list(SourceCitation.objects.filter(job_id=job_id).order_by("pk").values()[:2]),
        "usage": UsageReservation.objects.filter(job_id=job_id).values().first()}


def read_competitor_observation(*, project, actor, job_id, handler=HANDLER):
    method, stage, _producer, check_result = _collection_contract(handler)
    _safe_id(job_id)
    job = JobRun.objects.select_related("project", "actor").filter(pk=job_id, project_id=project.pk,
        organization_id=project.organization_id, handler=handler, status=JobStatus.SUCCEEDED).first()
    if job is None: raise PermissionDenied
    if not job.output: raise ValidationError("Original private competitor evidence is unavailable.")
    caller = _read_source(job, project, actor)
    original = _read_metadata(job_id)
    if original["job"] != {**_job_pin(job), "status": job.status, "output": job.output,
        "error_category": job.error_category, "updated_at": job.updated_at}: raise PermissionDenied
    if any(len(original[key]) != 1 for key in ("steps", "artifacts", "citations")) or job.error_category:
        raise ValidationError("Exact private competitor provenance is unavailable.")
    artifact, step, citation, usage = (original["artifacts"][0], original["steps"][0], original["citations"][0], original["usage"])
    result = {key: value for key, value in job.output.items() if key not in {"artifact_id", "derived_sha256"}}
    if (artifact["id"] != job.output["artifact_id"] or artifact["project_id"] != project.pk
        or artifact["content_type"] != "application/json" or not 1 <= artifact["size_bytes"] <= MAX_RESULT_BYTES
        or step["sequence"] != 1 or step["name"] != stage or step["status"] != "succeeded" or step["progress_percent"] != 100
        or step["error_category"] or step["output"] != {"method": method, "state": "collected"}
        or citation["step_id"] != step["id"] or citation["source_title"] != stage or citation["source_url"] != result["url"]
        or citation["observed_at"] != _observation_date(result, job.handler) or step["created_at"] > citation["observed_at"]
        or usage is None or (usage["organization_id"], usage["project_id"], usage["provider"], usage["reserved_units"],
            usage["actual_units"], usage["state"]) != (project.organization_id, project.pk, PROVIDER, 1, 1, "settled")):
        raise ValidationError("Exact original competitor/attempt/usage provenance is unavailable.")
    dates = (job.created_at, usage["created_at"], step["created_at"], citation["observed_at"], artifact["created_at"],
        citation["created_at"], job.updated_at, usage["settled_at"])
    if (any(not isinstance(value, datetime) or timezone.is_naive(value) or value > timezone.now() for value in dates)
        or tuple(sorted(dates)) != dates): raise ValidationError("Original competitor provenance dates need review.")
    try:
        content = read_project_artifact(project=project, key=artifact["key"])
        if len(content) != artifact["size_bytes"] or sha256(content).hexdigest() != job.output["derived_sha256"]: raise ValueError
        stored = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        if stored != result: raise ValueError
    except (ArtifactNotFound, ArtifactStorageError, ArtifactValidationError, GoogleTokenError, ValueError, UnicodeError, RecursionError):
        raise ValidationError("Original minimized competitor evidence cannot be read back.") from None
    check_result(stored, job.config_snapshot["binding"])
    current = JobRun.objects.select_related("project", "actor").get(pk=job_id, handler=handler)
    if _read_source(current, project, actor) != caller: raise PermissionDenied
    if _read_metadata(job_id) != original: raise PermissionDenied
    current = JobRun.objects.select_related("project", "actor").get(pk=job_id, handler=handler)
    if _read_source(current, project, actor) != caller: raise PermissionDenied
    if _read_metadata(job_id) != original or JobCancellation.objects.filter(job_id=job_id).exists(): raise PermissionDenied
    current = JobRun.objects.select_related("project", "actor").get(pk=job_id, handler=handler)
    if _read_source(current, project, actor) != caller or JobCancellation.objects.filter(job_id=job_id).exists(): raise PermissionDenied
    require_billable_access(organization=project.organization)
    return {"job_id": job_id, "collection": stored, "source_current": True}
