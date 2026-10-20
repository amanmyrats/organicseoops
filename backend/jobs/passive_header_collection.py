"""One explicitly selected public response, committed attempt, minimized private evidence."""
from datetime import datetime
from hashlib import sha256
import json
from urllib.parse import urlsplit

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.utils import timezone

from config.artifacts import ArtifactNotFound, ArtifactStorageError, ArtifactValidationError
from integrations.google_tokens import GoogleTokenError, _reject_constant, _unique_object
from tenancy.artifacts import delete_project_artifact, read_project_artifact, save_project_artifact
from tenancy.customer_artifact_barrier import project_artifact_barrier
from tenancy.models import Organization, Project
from tenancy.support_requests import _safe_id
from .crawler import _crawl_execution_lock
from .crawling import CrawlScope, FetchError, SafeFetcher
from .models import Artifact, JobCancellation, JobRun, JobStatus, JobStep, SourceCitation, UsageReservation
from .passive_header_source import passive_header_source, validate_input as validate_source_input
from .passive_headers import MAX_FIELDS, SELECTED_HEADERS, observe_response_headers
from .usage import require_billable_access, settle_usage, usage_denial


HANDLER = "collect_passive_headers"
PASSIVE_HANDLERS = (HANDLER, "collect_passive_tls", "collect_passive_resources", "collect_passive_redirects", "collect_passive_http_redirects", "collect_passive_redirect_chain")
METHOD = "passive-header-collection-v1"
STAGE = "Observe selected response headers"
MAX_RESULT_BYTES = 8192
JOB_FIELDS = ("id", "organization_id", "project_id", "actor_id", "handler", "method_version", "input_snapshot",
    "config_snapshot", "idempotency_key", "retry_of_id", "schedule_id", "scheduled_for", "created_at")
INTERPRETATION = "one_public_response_not_policy_effectiveness_tls_configuration_redirect_behavior_or_exploitability"
ERRORS = {"invalid_header_observation", "invalid_url", "outside_scope", "non_public_address", "dns_error",
    "timeout", "network_error", "response_headers_unavailable", "request_outcome_unknown", "handler_failed",
    "invalid_tls_observation", "tls_observation_failed", "invalid_resource_observation", "resource_body_unavailable",
    "incomplete_response_body", "response_too_large", "invalid_content_encoding", "invalid_redirect_observation"}


def validate_input(data):
    return validate_source_input(data)[0]


def _collection_contract(handler):
    if handler == "collect_passive_redirect_chain":
        from . import passive_redirect_chain_collection as chain
        return chain.METHOD, chain.STAGE, chain.passive_redirect_chain_source, chain.validate_input, chain.validate_result, "url"
    if handler == HANDLER:
        return METHOD, STAGE, passive_header_source, validate_input, validate_result, "url"
    if handler == "collect_passive_tls":
        from . import passive_tls_collection as tls
        return tls.METHOD, tls.STAGE, tls.passive_tls_source, tls.validate_input, tls.validate_result, "origin"
    if handler == "collect_passive_resources":
        from . import passive_resource_collection as resources
        return resources.METHOD, resources.STAGE, resources.passive_resource_source, resources.validate_input, resources.validate_result, "url"
    if handler == "collect_passive_redirects":
        from . import passive_redirect_collection as redirects
        return redirects.METHOD, redirects.STAGE, redirects.passive_redirect_source, redirects.validate_input, redirects.validate_result, "url"
    if handler == "collect_passive_http_redirects":
        from . import passive_http_redirect_collection as http_redirects
        return http_redirects.METHOD, http_redirects.STAGE, http_redirects.passive_http_redirect_source, http_redirects.validate_input, http_redirects.validate_result, "url"
    raise ValidationError("Choose a supported explicit passive observation.")


def result_byte_limit(handler):
    _collection_contract(handler)
    if handler == "collect_passive_redirect_chain":
        from .passive_redirect_chain_evidence import MAX_RESULT_BYTES as chain_limit
        return chain_limit
    return MAX_RESULT_BYTES


def selection_snapshot(project, actor, data, *, handler=HANDLER):
    method, _stage, source, _input, _result, _target = _collection_contract(handler)
    return {"method": method, "binding": source(project=project, actor=actor, data=data)}


def _date(value):
    try:
        if type(value) is not str or len(value) > 64: raise ValueError
        stamp = datetime.fromisoformat(value)
        if timezone.is_naive(stamp) or stamp > timezone.now(): raise ValueError
    except ValueError:
        raise ValidationError("Original aware response observation date is unavailable.") from None
    return stamp


def _encode(result):
    return json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def validate_result(result, binding):
    if (type(result) is not dict or set(result) != {"method", "url", "status", "observed_at", "evidence", "interpretation"}
        or result["method"] != METHOD or result["url"] != binding["url"]
        or result["interpretation"] != INTERPRETATION or type(result["status"]) is not int
        or not 200 <= result["status"] <= 599 or _date(result["observed_at"]) < _date(binding["verified_at"])):
        raise ValidationError("Retain only the exact selected response and original minimized evidence.")
    evidence = result["evidence"]
    template = observe_response_headers([])
    if (type(evidence) is not dict or set(evidence) != set(template)
        or any(evidence[key] != template[key] for key in ("method_version", "state", "coverage", "interpretation"))
        or type(evidence["headers"]) is not dict or set(evidence["headers"]) != set(SELECTED_HEADERS)
        or any(type(value) is not str or value not in {"absent", "present_empty", "present_nonempty", "multiple_fields"}
               for value in evidence["headers"].values())
        or type(evidence["cookies"]) is not dict or set(evidence["cookies"]) != set(template["cookies"])):
        raise ValidationError("Raw or unsupported response metadata cannot be retained.")
    cookies = evidence["cookies"]
    if (any(type(value) is not int or not 0 <= value <= MAX_FIELDS for value in cookies.values())
        or cookies["observed_fields"] != cookies["parsed_fields"] + cookies["unclassified_fields"]
        or any(cookies[key] > cookies["parsed_fields"] for key in ("without_secure", "without_httponly", "without_recognized_samesite"))
        or cookies["observed_fields"] + sum(0 if value == "absent" else 2 if value == "multiple_fields" else 1
            for value in evidence["headers"].values()) > MAX_FIELDS
        or len(_encode(result)) > MAX_RESULT_BYTES):
        raise ValidationError("Retain bounded explicit cookie-flag counts only.")
    return result


def validate_job(job, *, current=False):
    method, _stage, _source, check_input, check_result, _target = _collection_contract(job.handler)
    data = check_input(job.input_snapshot)
    config = job.config_snapshot
    if (job.method_version != method or job.retry_of_id or job.schedule_id or job.scheduled_for
        or type(config) is not dict or set(config) != {"method", "binding"} or config["method"] != method
        or type(config["binding"]) is not dict
        or (config["binding"].get("organization_id"), config["binding"].get("project_id"), config["binding"].get("actor_id"))
            != (job.organization_id, job.project_id, job.actor_id)
        or any(config["binding"].get(key) != value for key, value in data.items())):
        raise ValidationError("Header collection requires its exact manual source binding; no retry or schedule.")
    if job.output:
        result = {key: value for key, value in job.output.items() if key not in {"artifact_id", "derived_sha256"}}
        check_result(result, config["binding"])
        if set(job.output) != set(result) | {"artifact_id", "derived_sha256"}: raise ValidationError("Invalid private evidence.")
        _safe_id(job.output["artifact_id"])
        if job.output["derived_sha256"] != sha256(_encode(result)).hexdigest(): raise ValidationError("Invalid private evidence digest.")
    if current and selection_snapshot(job.project, job.actor, data, handler=job.handler) != config: raise PermissionDenied


def queue_passive_header_collection(*, project, actor, data, idempotency_key, handler=HANDLER):
    from .services import queue_job
    _method, _stage, _source, check_input, _result, _target = _collection_contract(handler)
    data = check_input(data)
    with transaction.atomic():
        org = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=org)
        config = selection_snapshot(project, actor, data, handler=handler)
        job = queue_job(project=project, actor=actor, handler=handler, input_snapshot=data,
            config_snapshot=config, idempotency_key=idempotency_key)
        validate_job(job, current=True)
        if job.status == JobStatus.QUEUED and _denial(job): raise PermissionDenied
        return job


def _job_pin(job):
    return {key: getattr(job, key) for key in JOB_FIELDS}


def _execution_pin(job):
    return {"job": _job_pin(job), "usage": UsageReservation.objects.filter(job=job).values(
         "id", "job_id", "organization_id", "project_id", "provider", "reserved_units", "period_start", "created_at").first()}


def _row_pin(row):
    return {field.attname: getattr(row, field.attname) for field in row._meta.concrete_fields}


def _passive_execution_pin(job):
    return {"execution": _execution_pin(job), "dispatch": {"dispatched_at": job.dispatched_at, "dispatch_error": job.dispatch_error},
        "steps": list(JobStep.objects.filter(job=job).order_by("pk").values()[:2])}


def _denial(job, original=None):
    if JobCancellation.objects.filter(job=job).exists(): return "cancel_requested"
    if original is not None and _passive_execution_pin(job) != original: return "source_scope_changed"
    reservation = UsageReservation.objects.filter(job=job).first()
    if (reservation is None or reservation.organization_id != job.organization_id or reservation.project_id != job.project_id
        or reservation.provider != "passive_security" or reservation.reserved_units != 1): return "usage_unreserved"
    denied = usage_denial(job=job)
    if denied: return denied
    try: validate_job(job, current=True)
    except (PermissionDenied, ValidationError, Project.DoesNotExist): return "source_scope_changed"
    return usage_denial(job=job)


def _finish(job_id, *, result=None, error="", original=None):
    org_id = JobRun.objects.filter(pk=job_id, handler__in=PASSIVE_HANDLERS).values_list("organization_id", flat=True).first()
    if org_id is None: return False
    key = None
    project = None
    try:
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=org_id)
            job = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id, handler__in=PASSIVE_HANDLERS)
            method, stage, _source, _input, check_result, target_key = _collection_contract(job.handler)
            if job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}: return False
            project = Project.objects.select_for_update().get(pk=job.project_id, organization_id=org_id)
            original = original or _passive_execution_pin(job)
            denied = _denial(job, original)
            step = job.steps.filter(sequence=1).first()
            if job.status == JobStatus.QUEUED:
                job.status = JobStatus.RUNNING
                job.save(update_fields=["status", "updated_at"])
            if result is not None and not denied:
                check_result(result, job.config_snapshot["binding"])
                if step is None or job.steps.count() != 1: raise ValidationError("Original committed attempt is unavailable.")
                content = _encode(result)
                key = save_project_artifact(project=project, content=content, content_type="application/json")
                fresh = JobRun.objects.select_related("project", "actor").get(pk=job_id)
                denied = _denial(fresh, original)
                if not denied:
                    artifact = Artifact.objects.create(job=job, project=project, key=key, content_type="application/json", size_bytes=len(content))
                    job.output = {**result, "artifact_id": artifact.pk, "derived_sha256": sha256(content).hexdigest()}
                    citation = SourceCitation.objects.create(job=job, step=step, source_title=stage,
                        source_url=result[target_key], observed_at=_date(result["observed_at"]))
                    if _denial(JobRun.objects.select_related("project", "actor").get(pk=job_id), original): raise PermissionDenied
            useful = bool(result is not None and not denied)
            if not useful and key:
                delete_project_artifact(project=project, key=key)
                key = None
            if step:
                step.status = JobStep.Status.SUCCEEDED if useful else JobStep.Status.FAILED
                step.progress_percent = 100
                step.error_category = denied or error
                step.output = {"method": method, "state": "collected" if useful else "unavailable"}
                step.save(update_fields=["status", "progress_percent", "error_category", "output"])
                original = {**original, "steps": [_row_pin(step)]}
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
                if (_passive_execution_pin(current) != original or current.status != JobStatus.SUCCEEDED or current.output != job.output
                    or JobCancellation.objects.filter(job=current).exists()
                    or not UsageReservation.objects.filter(job=current, state="settled", actual_units=1).exists()): raise PermissionDenied
                intended = {"job": _row_pin(job), "steps": [_row_pin(step)], "artifacts": [_row_pin(artifact)],
                    "citations": [_row_pin(citation)], "usage": _row_pin(usage)}
                if _read_metadata(job_id) != intended: raise PermissionDenied
                if read_passive_header_observation(project=project, actor=current.actor, job_id=job_id, handler=current.handler)["collection"] != result:
                    raise PermissionDenied
                if _read_metadata(job_id) != intended: raise PermissionDenied
                require_billable_access(organization=project.organization)
    except Exception:
        if key: delete_project_artifact(project=project, key=key)
        raise
    return True


def execute_passive_header_collection(job_id, *, fetcher=None, handler=HANDLER):
    if connection.in_atomic_block:
        raise ValidationError("Header attempts must commit outside a caller transaction before any request.")
    organization_id = JobRun.objects.filter(pk=job_id, handler=handler).values_list("organization_id", flat=True).first()
    if organization_id is None:
        return False
    with project_artifact_barrier(organization_id, shared=True), _crawl_execution_lock(job_id) as acquired:
        if not acquired: return False
        pins = {}
        try: return _execute(job_id, fetcher=fetcher, handler=handler, pins=pins)
        except FetchError as error: return _finish(job_id, error=error.code if error.code in ERRORS else "handler_failed", original=pins.get("original"))
        except Exception: return _finish(job_id, error="handler_failed", original=pins.get("original"))


def _execute(job_id, *, fetcher, pins, handler=HANDLER):
    method, stage, _source, _input, check_result, target_key = _collection_contract(handler)
    org_id = JobRun.objects.filter(pk=job_id, handler=handler).values_list("organization_id", flat=True).first()
    if org_id is None: return False
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=org_id)
        job = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id, handler=handler)
        if job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}: return False
        if _denial(job): return _finish(job_id)
        if job.steps.exists(): return _finish(job_id, error="request_outcome_unknown")
        original = _passive_execution_pin(job)
        if job.status == JobStatus.QUEUED:
            job.status = JobStatus.RUNNING
            job.save(update_fields=["status", "updated_at"])
        step = JobStep.objects.create(job=job, sequence=1, name=stage, status=JobStep.Status.RUNNING,
            output={"method": method, "state": "attempted"})
        original = {**original, "steps": [_row_pin(step)]}
        pins["original"] = original
    url = job.input_snapshot[target_key]
    selected_urls = [url, *job.input_snapshot["target_urls"]] if handler == "collect_passive_redirect_chain" else [url]
    def checkpoint(current_url):
        current = JobRun.objects.select_related("project", "actor").get(pk=job_id, handler=handler)
        if current_url not in selected_urls or current.status != JobStatus.RUNNING or _denial(current, original): raise PermissionDenied
    fetcher = fetcher or SafeFetcher(CrawlScope(frozenset(urlsplit(value).hostname for value in selected_urls)),
        timeout=10, max_redirects=5 if handler == "collect_passive_redirect_chain" else 0)
    if handler == "collect_passive_redirect_chain":
        from .passive_redirect_chain_evidence import minimized_redirect_chain_evidence
        response = fetcher.fetch(url, redirect_chain_selection=job.input_snapshot, before_request=checkpoint, before_send=checkpoint)
        checkpoint(response.url)
        result = minimized_redirect_chain_evidence(response, binding=job.config_snapshot["binding"])
    elif handler == HANDLER:
        response = fetcher.fetch(url, observe_headers=True, before_request=checkpoint, before_send=checkpoint)
        checkpoint(response.url)
        if (response.headers or response.body or response.redirects or response.resource_observation is not None
            or response.redirect_observation is not None):
            raise ValidationError("Only minimized header transport is accepted.")
        result = {"method": METHOD, "url": response.url, "status": response.status, "observed_at": timezone.now().isoformat(),
            "evidence": response.header_observation, "interpretation": INTERPRETATION}
    elif handler == "collect_passive_tls":
        from .passive_tls_evidence import minimized_tls_evidence
        observation = fetcher.observe_tls(url, before_request=checkpoint, before_send=checkpoint)
        checkpoint(observation.get("origin"))
        result = minimized_tls_evidence(observation, binding=job.config_snapshot["binding"])
    elif handler == "collect_passive_resources":
        from .passive_resource_evidence import minimized_resource_evidence
        response = fetcher.fetch(url, observe_resources=True, before_request=checkpoint, before_send=checkpoint)
        checkpoint(response.url)
        result = minimized_resource_evidence(response, binding=job.config_snapshot["binding"])
    elif handler == "collect_passive_http_redirects":
        from .passive_http_redirect_evidence import minimized_http_redirect_evidence
        response = fetcher.fetch(url, observe_http_redirects=True, before_request=checkpoint, before_send=checkpoint)
        checkpoint(response.url)
        result = minimized_http_redirect_evidence(response, binding=job.config_snapshot["binding"])
    else:
        from .passive_redirect_evidence import minimized_redirect_evidence
        response = fetcher.fetch(url, observe_redirects=True, before_request=checkpoint, before_send=checkpoint)
        checkpoint(response.url)
        result = minimized_redirect_evidence(response, binding=job.config_snapshot["binding"])
    check_result(result, job.config_snapshot["binding"])
    return _finish(job_id, result=result, original=original)


def _read_source(job, project, actor):
    validate_job(job, current=True)
    require_billable_access(organization=project.organization)
    caller = selection_snapshot(project, actor, job.input_snapshot, handler=job.handler)
    caller["binding"]["actor_id"] = job.actor_id
    if caller != job.config_snapshot or JobCancellation.objects.filter(job=job).exists(): raise PermissionDenied
    require_billable_access(organization=project.organization)


def _read_metadata(job_id):
    return {"job": JobRun.objects.filter(pk=job_id, handler__in=PASSIVE_HANDLERS).values().first(),
        "steps": list(JobStep.objects.filter(job_id=job_id).order_by("pk").values()[:2]),
        "artifacts": list(Artifact.objects.filter(job_id=job_id).order_by("pk").values()[:2]),
        "citations": list(SourceCitation.objects.filter(job_id=job_id).order_by("pk").values()[:2]),
        "usage": UsageReservation.objects.filter(job_id=job_id).values().first()}


def read_passive_header_observation(*, project, actor, job_id, handler=HANDLER):
    _safe_id(job_id)
    method, stage, _source, _input, check_result, target_key = _collection_contract(handler)
    job = JobRun.objects.select_related("project", "actor").filter(pk=job_id, project_id=project.pk,
        organization_id=project.organization_id, handler=handler, status=JobStatus.SUCCEEDED).first()
    if job is None: raise PermissionDenied
    if not job.output: raise ValidationError("Exact private passive evidence is unavailable.")
    _read_source(job, project, actor)
    original = _read_metadata(job_id)
    if original["job"] != _row_pin(job): raise PermissionDenied
    if (any(len(original[key]) != 1 for key in ("steps", "artifacts", "citations")) or job.error_category):
        raise ValidationError("Exact private header provenance is unavailable.")
    artifact, step, citation, usage = (original["artifacts"][0], original["steps"][0], original["citations"][0], original["usage"])
    result = {key: value for key, value in job.output.items() if key not in {"artifact_id", "derived_sha256"}}
    if (artifact["id"] != job.output["artifact_id"] or artifact["project_id"] != project.pk
        or artifact["content_type"] != "application/json" or not 1 <= artifact["size_bytes"] <= result_byte_limit(handler)
        or step["sequence"] != 1 or step["name"] != stage or step["status"] != "succeeded" or step["progress_percent"] != 100
        or step["error_category"] or step["output"] != {"method": method, "state": "collected"}
        or citation["step_id"] != step["id"] or citation["source_title"] != stage or citation["source_url"] != result[target_key]
        or citation["observed_at"] != _date(result["observed_at"]) or step["created_at"] > citation["observed_at"]
        or usage is None or (usage["organization_id"], usage["project_id"], usage["provider"], usage["reserved_units"],
            usage["actual_units"], usage["state"]) != (project.organization_id, project.pk, "passive_security", 1, 1, "settled")):
        raise ValidationError("Exact original response/attempt/usage provenance is unavailable.")
    dates = (job.created_at, usage["created_at"], step["created_at"], citation["observed_at"], artifact["created_at"],
             citation["created_at"], job.updated_at, usage["settled_at"])
    if (any(not isinstance(value, datetime) or timezone.is_naive(value) or value > timezone.now() for value in dates)
        or tuple(sorted(dates)) != dates): raise ValidationError("Original header provenance dates need review.")
    if handler == "collect_passive_redirect_chain" and _date(result["last_observed_at"]) > artifact["created_at"]:
        raise ValidationError("Original chain responses must precede their private artifact.")
    try:
        content = read_project_artifact(project=project, key=artifact["key"])
        if len(content) != artifact["size_bytes"] or sha256(content).hexdigest() != job.output["derived_sha256"]: raise ValueError
        if handler == "collect_passive_redirect_chain":
            from .passive_redirect_chain_evidence import parse_redirect_chain_evidence
            stored = parse_redirect_chain_evidence(content, binding=job.config_snapshot["binding"])
        elif handler == "collect_passive_tls":
            from .passive_tls_evidence import parse_tls_evidence
            stored = parse_tls_evidence(content, binding=job.config_snapshot["binding"])
        elif handler == "collect_passive_resources":
            from .passive_resource_evidence import parse_resource_evidence
            stored = parse_resource_evidence(content, binding=job.config_snapshot["binding"])
        elif handler == "collect_passive_redirects":
            from .passive_redirect_evidence import parse_redirect_evidence
            stored = parse_redirect_evidence(content, binding=job.config_snapshot["binding"])
        elif handler == "collect_passive_http_redirects":
            from .passive_http_redirect_evidence import parse_http_redirect_evidence
            stored = parse_http_redirect_evidence(content, binding=job.config_snapshot["binding"])
        else:
            stored = json.loads(content, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        if stored != result: raise ValueError
    except (ArtifactNotFound, ArtifactStorageError, ArtifactValidationError, GoogleTokenError, ValueError, UnicodeError, RecursionError):
        raise ValidationError("Private minimized header evidence cannot be read back.") from None
    check_result(stored, job.config_snapshot["binding"])
    current = JobRun.objects.select_related("project", "actor").get(pk=job_id, handler=handler)
    _read_source(current, project, actor)
    if _read_metadata(job_id) != original: raise PermissionDenied
    require_billable_access(organization=project.organization)
    return {"job_id": job_id, "collection": stored, "source_current": True}
