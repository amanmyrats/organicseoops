"""Once-only configured synthesis of a current original static pair, with private evidence."""
from datetime import datetime
from hashlib import sha256
import json
import re
import time

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.utils import timezone

from config.artifacts import ArtifactNotFound, ArtifactStorageError, ArtifactValidationError
from integrations.google_tokens import GoogleTokenError, _reject_constant, _unique_object
from providers.adapters import ProviderRequestError, create_response
from providers.models import AIModel, AIModelCapability, AIProvider, AIProviderAccount
from providers.services import require_model_capabilities
from tenancy.artifacts import delete_project_artifact, read_project_artifact, save_project_artifact
from tenancy.customer_artifact_barrier import project_artifact_barrier
from tenancy.models import Organization, Project
from . import competitor_collection as collection
from . import competitor_synthesis as synthesis
from .ai_text import _configuration, _max_cost, _selection
from .ai_usage import finish_ai_usage, record_ai_attempt
from .competitor_comparison import _read_pair_sources
from .crawler import _crawl_execution_lock
from .models import AIUsageRecord, Artifact, JobCancellation, JobRun, JobStatus, JobStep, SourceCitation, UsageReservation
from .passive_header_collection import JOB_FIELDS, _execution_pin, _job_pin
from .passive_tls_evidence import _date
from .usage import require_billable_access, settle_usage, usage_denial


METHOD = "competitor-static-synthesis-v1"
HANDLER = "synthesize_competitor_pair"
TOPICS_HANDLER = "classify_competitor_heading_topics"
SYNTHESIS_HANDLERS = (HANDLER, "synthesize_competitor_headings_pair", TOPICS_HANDLER)
CITATION_KIND = "static root"
STAGE = "Request selected model"
STATE = "unverified_ai_interpretations_require_human_review"
INTERPRETATION = "original_static_facts_separate_from_unverified_cited_ai_notes_not_approval_whole_site_or_causal_evidence"
MAX_RESULT_BYTES = 48 * 1024
INPUT_TOKEN_CEILING = synthesis.MAX_PROMPT_BYTES + 1024
ERRORS = {"invalid_credential", "egress_denied", "timeout", "tls_verification_failed", "dns_error", "network_error",
    "invalid_request", "malformed_response", "refused", "incomplete_response", "rate_limited", "provider_unavailable",
    "response_too_large", "invalid_response", "handler_failed", "request_outcome_unknown"}


def _contract(handler):
    # Fixed internal families only; callers never select a source/schema implementation.
    if handler == HANDLER:
        from . import competitor_synthesis_job
        return competitor_synthesis_job
    if handler == "synthesize_competitor_headings_pair":
        from . import competitor_headings_synthesis_job
        return competitor_headings_synthesis_job
    if handler == TOPICS_HANDLER:
        from . import competitor_topics_job
        return competitor_topics_job
    raise ValidationError("Choose a supported fixed original synthesis family.")


def read_source(**kwargs):
    return synthesis.read_competitor_synthesis_source(**kwargs)


def validate_notes(value, comparison):
    return synthesis.validate_interpretations(value, comparison)


def read_result(**kwargs):
    return read_competitor_synthesis(**kwargs)


def validate_input(data):
    if (type(data) is not dict or set(data) != {"previous_job_id", "current_job_id", "ai_processing_permission",
        "model_id", "account_id", "max_output_tokens", "max_cost_usd", "allow_free"}
        or data["ai_processing_permission"] is not True or type(data["allow_free"]) is not bool
        or type(data["max_output_tokens"]) is not int or not 128 <= data["max_output_tokens"] <= 2048):
        raise ValidationError("Choose an original pair, separate AI permission and bounded explicit model budget.")
    for key in ("previous_job_id", "current_job_id", "model_id", "account_id"):
        collection._safe_id(data[key])
    if data["previous_job_id"] == data["current_job_id"]:
        raise ValidationError("Choose two distinct original competitor jobs.")
    _max_cost(data["max_cost_usd"])
    return dict(data)


def _digest(value):
    # Preserve complete original datetime microseconds; DjangoJSONEncoder rounds them.
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def _model_rows(model, account):
    return {"model": AIModel.objects.filter(pk=model.pk).values().first(),
        "provider": AIProvider.objects.filter(pk=model.provider_id).values().first(),
        "account": AIProviderAccount.objects.filter(pk=account.pk).values().first()}


def selection_snapshot(project, actor, data):
    """Return compact configuration plus transient input, without resolving any credential."""
    return _selection_snapshot(project, actor, data, handler=collection.HANDLER,
        source_reader=synthesis.read_competitor_synthesis_source, method=METHOD, source_method=synthesis.METHOD,
        instructions=synthesis.INSTRUCTIONS, output_schema=synthesis.OUTPUT_SCHEMA)


def _selection_snapshot(project, actor, data, *, handler, source_reader, method, source_method, instructions, output_schema):
    data = validate_input(data)
    ids = (data["previous_job_id"], data["current_job_id"])
    jobs = {row.pk: row for row in JobRun.objects.select_related("project", "actor").filter(pk__in=ids,
        project_id=project.pk, organization_id=project.organization_id,
        handler=handler, status=JobStatus.SUCCEEDED)}
    if len(jobs) != 2:
        raise PermissionDenied
    callers = _read_pair_sources((jobs[key] for key in ids), project, actor)
    original = synthesis._pins(ids)
    source = source_reader(project=project, actor=actor,
        previous_job_id=ids[0], current_job_id=ids[1], ai_processing_permission=True)
    return _model_snapshot(project, actor, data, source, ids=ids, original=original, callers=callers,
        handler=handler, method=method, source_method=source_method, instructions=instructions, output_schema=output_schema)


def _model_snapshot(project, actor, data, source, *, ids, original, callers, handler, method, source_method, instructions, output_schema):
    """Shared fixed-family preparation after each caller validates its original source."""
    budget = {**data, "prompt": "x" * synthesis.MAX_PROMPT_BYTES}
    model, account = _selection(budget, organization_id=project.organization_id)
    priced_model = collection._row_pin(model)
    priced_provider = collection._row_pin(model.provider)
    model = require_model_capabilities(model, {AIModelCapability.TEXT_GENERATION,
        AIModelCapability.STRUCTURED_OUTPUT, AIModelCapability.REASONING})
    if collection._row_pin(model) != priced_model or collection._row_pin(model.provider) != priced_provider:
        raise PermissionDenied
    model.full_clean()
    account.full_clean()
    if model.context_window is None or model.context_window < INPUT_TOKEN_CEILING + data["max_output_tokens"]:
        raise ValidationError("Choose an evidenced context window covering the conservative original-pair input and output ceiling.")
    models = {"model": collection._row_pin(model), "provider": collection._row_pin(model.provider),
        "account": collection._row_pin(account)}
    config = {**_configuration(model, account, budget, {"routing_source": "explicit", "routing_policy_id": None,
        "routing_policy_revision": None, "fallback_index": 0, "timeout_seconds": 30}),
        "method": method, "organization_id": project.organization_id, "project_id": project.pk, "actor_id": actor.pk,
        "source_method": source_method, "source_selection_digest": source["selection_digest"],
        "source_metadata_sha256": _digest(original), "caller_source_sha256": _digest(callers),
        "model_selection_sha256": _digest(models), "prompt_sha256": sha256(instructions.encode()).hexdigest(),
        "output_schema_sha256": sha256(collection._encode(output_schema)).hexdigest()}
    if synthesis._pins(ids) != original or _model_rows(model, account) != models:
        raise PermissionDenied
    fresh = (JobRun.objects.select_related("project", "actor").get(pk=key, handler=handler) for key in ids)
    if _read_pair_sources(fresh, project, actor) != callers: raise PermissionDenied
    if synthesis._pins(ids) != original or _model_rows(model, account) != models: raise PermissionDenied
    if JobCancellation.objects.filter(job_id__in=ids).exists(): raise PermissionDenied
    require_billable_access(organization=project.organization)
    return model, account, config, source


def validate_job(job, *, current=False):
    return _validate_job(job, current=current, handler=HANDLER)


def _validate_job(job, *, current=False, handler):
    contract = _contract(handler)
    data = contract.validate_input(job.input_snapshot)
    config = job.config_snapshot
    # Same fixed configuration shape as selection; source text/prompt never enters snapshots.
    fields = {"provider_id", "model_identifier", "provider_kind", "provider_base_url", "model_revision",
        "model_access_tier", "input_price_usd_per_million", "output_price_usd_per_million", "estimated_max_cost_usd",
        "account_id", "credential_revision", "routing_source", "routing_policy_id", "routing_policy_revision",
        "fallback_index", "timeout_seconds", "method", "organization_id", "project_id", "actor_id", "source_method",
        "source_selection_digest", "source_metadata_sha256", "caller_source_sha256", "model_selection_sha256",
        "prompt_sha256", "output_schema_sha256"}
    hashes = ("source_selection_digest", "source_metadata_sha256", "caller_source_sha256", "model_selection_sha256",
        "prompt_sha256", "output_schema_sha256")
    if (job.handler != handler or job.method_version != contract.METHOD or job.retry_of_id or job.schedule_id or job.scheduled_for
        or type(config) is not dict or set(config) != fields
        or (config["method"], config["organization_id"], config["project_id"], config["actor_id"], config["account_id"],
            config["source_method"], config["routing_source"], config["routing_policy_id"], config["routing_policy_revision"],
            config["fallback_index"], config["timeout_seconds"]) !=
           (contract.METHOD, job.organization_id, job.project_id, job.actor_id, data["account_id"], contract.synthesis.METHOD, "explicit", None, None, 0, 30)
        or any(type(config[key]) is not str or not re.fullmatch(r"[0-9a-f]{64}", config[key]) for key in hashes)):
        raise ValidationError("Synthesis requires its original manual pair and explicit bounded model; no retry or schedule.")
    collection._safe_id(config["provider_id"])
    if job.output:
        output = job.output
        if (type(output) is not dict or set(output) != {"method", "state", "generated_at", "artifact_id", "derived_sha256"}
            or output["method"] != contract.METHOD or output["state"] != contract.STATE
            or type(output["derived_sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", output["derived_sha256"])):
            raise ValidationError("Retain only compact private synthesis integrity metadata.")
        collection._safe_id(output["artifact_id"])
        _date(output["generated_at"])
    if current:
        selected = contract.selection_snapshot(job.project, job.actor, data)
        if selected[2] != config: raise PermissionDenied
        return selected


def queue_competitor_synthesis(*, project, actor, data, idempotency_key):
    return _queue_synthesis(project=project, actor=actor, data=data, idempotency_key=idempotency_key, handler=HANDLER)


def _queue_synthesis(*, project, actor, data, idempotency_key, handler):
    contract = _contract(handler)
    from .services import queue_job
    data = contract.validate_input(data)
    with transaction.atomic():
        org = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=org)
        config = contract.selection_snapshot(project, actor, data)[2]
        job = queue_job(project=project, actor=actor, handler=handler, input_snapshot=data,
            config_snapshot=config, idempotency_key=idempotency_key)
        contract.validate_job(job, current=True)
        if job.status == JobStatus.QUEUED and _denial(job): raise PermissionDenied
        return job


def _attempt_pin(job_id):
    return {"steps": list(JobStep.objects.filter(job_id=job_id).order_by("pk").values()[:2]),
        "ai": AIUsageRecord.objects.filter(job_id=job_id).values().first()}


def _denial(job, original=None):
    if JobCancellation.objects.filter(job=job).exists(): return "cancel_requested"
    if original is not None and (_execution_pin(job) != original["execution"]
        or _attempt_pin(job.pk) != original["attempt"]): return "source_scope_changed"
    reservation = UsageReservation.objects.filter(job=job).first()
    if reservation is None or (reservation.organization_id, reservation.project_id, reservation.provider, reservation.reserved_units) != (
        job.organization_id, job.project_id, "ai", 1): return "usage_unreserved"
    denied = usage_denial(job=job)
    if denied: return denied
    try: _contract(job.handler).validate_job(job, current=True)
    except (PermissionDenied, ValidationError, Project.DoesNotExist): return "source_scope_changed"
    return ""


def _result(job, source, response):
    contract = _contract(job.handler)
    if job.handler == TOPICS_HANDLER:
        return contract.build_result(job, source, response)
    notes = contract.validate_notes(response.structured, source["comparison"])
    return {"method_version": contract.METHOD, "organization_id": job.organization_id, "project_id": job.project_id,
        "source_selection_digest": source["selection_digest"], "model_id": job.input_snapshot["model_id"],
        "account_id": job.input_snapshot["account_id"], "generated_at": timezone.now().isoformat(timespec="microseconds"),
        "comparison": source["comparison"], **notes, "state": contract.STATE, "interpretation": contract.INTERPRETATION}


def validate_result(result, job, source):
    return _validate_result(result, job, source, handler=HANDLER)


def _validate_result(result, job, source, *, handler):
    contract = _contract(handler)
    if job.handler != handler: raise PermissionDenied
    if (type(result) is not dict or set(result) != {"method_version", "organization_id", "project_id", "source_selection_digest",
        "model_id", "account_id", "generated_at", "comparison", "interpretations", "state", "interpretation"}
        or (result["method_version"], result["organization_id"], result["project_id"], result["source_selection_digest"],
            result["model_id"], result["account_id"], result["state"], result["interpretation"]) !=
           (contract.METHOD, job.organization_id, job.project_id, job.config_snapshot["source_selection_digest"],
            job.input_snapshot["model_id"], job.input_snapshot["account_id"], contract.STATE, contract.INTERPRETATION)
        or any(type(result[key]) is not int for key in ("organization_id", "project_id", "model_id", "account_id"))
        or collection._encode(result["comparison"]) != collection._encode(source["comparison"])
        or source["selection_digest"] != result["source_selection_digest"]
        or _date(result["generated_at"]) < _date(source["comparison"]["current"]["evidence"]["observed_at"])
        or len(collection._encode(result)) > MAX_RESULT_BYTES):
        raise ValidationError("Original static facts must remain separate from bounded unverified AI interpretations.")
    contract.validate_notes({"interpretations": result["interpretations"]}, result["comparison"])
    return result


def _read_metadata(job_id):
    return {"job": JobRun.objects.filter(pk=job_id, handler__in=SYNTHESIS_HANDLERS).values(*JOB_FIELDS, "status", "output", "error_category", "updated_at").first(),
        **_attempt_pin(job_id), "artifacts": list(Artifact.objects.filter(job_id=job_id).order_by("pk").values()[:2]),
        "citations": list(SourceCitation.objects.filter(job_id=job_id).order_by("pk").values()[:3]),
        "usage": UsageReservation.objects.filter(job_id=job_id).values().first()}


def _finish(job_id, *, result=None, response=None, error="", original=None, duration_ms=None,
            provider_request_id="", input_tokens=None, output_tokens=None):
    scope = JobRun.objects.filter(pk=job_id, handler__in=SYNTHESIS_HANDLERS).values_list("organization_id", "handler").first()
    if scope is None: return False
    org_id, handler = scope
    contract = _contract(handler)
    key = None
    project = None
    try:
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=org_id)
            job = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id, handler=handler)
            if job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}: return False
            project = Project.objects.select_for_update().get(pk=job.project_id, organization_id=org_id)
            denied = _denial(job, original)
            step = job.steps.filter(sequence=1).first()
            if job.status == JobStatus.QUEUED:
                job.status = JobStatus.RUNNING
                job.save(update_fields=["status", "updated_at"])
            useful = result is not None and not denied
            if useful:
                source = contract.selection_snapshot(project, job.actor, job.input_snapshot)[3]
                contract.validate_result(result, job, source)
                if step is None or job.steps.count() != 1: raise ValidationError("Original committed AI attempt is unavailable.")
                ai = AIUsageRecord.objects.get(job=job, step=step)
                if _date(result["generated_at"]) < ai.attempted_at: raise ValidationError("Generation precedes its committed AI attempt.")
                content = collection._encode(result)
                key = save_project_artifact(project=project, content=content, content_type="application/json")
                denied = _denial(JobRun.objects.select_related("project", "actor").get(pk=job_id), original)
                useful = not denied
                if useful:
                    artifact = Artifact.objects.create(job=job, project=project, key=key, content_type="application/json", size_bytes=len(content))
                    job.output = {"method": contract.METHOD, "state": contract.STATE, "generated_at": result["generated_at"],
                        "artifact_id": artifact.pk, "derived_sha256": sha256(content).hexdigest()}
                    citations = [SourceCitation.objects.create(job=job, step=step, source_title=title,
                        source_url=url, observed_at=observed) for title, url, observed in _source_citations(contract, source)]
                    if _denial(JobRun.objects.select_related("project", "actor").get(pk=job_id), original): raise PermissionDenied
            if not useful and key:
                delete_project_artifact(project=project, key=key)
                key = None
            if step:
                step.status = JobStep.Status.SUCCEEDED if useful else JobStep.Status.FAILED
                step.progress_percent = 100
                step.error_category = denied or error or ("" if useful else "request_outcome_unknown")
                step.output = {"method": contract.METHOD, "state": contract.STATE if useful else "unavailable"}
                step.save(update_fields=["status", "progress_percent", "error_category", "output"])
                ai = finish_ai_usage(job=job, step=step, result=response, error=error or denied, duration_ms=duration_ms,
                    provider_request_id=provider_request_id, input_tokens=input_tokens, output_tokens=output_tokens)
            # After intended attempt changes, continue comparing the ORIGINAL execution/reservation,
            # and compare complete intended private rows after settlement rather than repinning them.
            if useful:
                contract.validate_job(JobRun.objects.select_related("project", "actor").get(pk=job_id), current=True)
                if _execution_pin(job) != original["execution"] or JobCancellation.objects.filter(job=job).exists(): raise PermissionDenied
            job.status = JobStatus.CANCELLED if denied else JobStatus.SUCCEEDED if useful else JobStatus.FAILED
            job.error_category = denied or error or ("" if useful else "request_outcome_unknown")
            if not useful: job.output = {}
            job.save(update_fields=["status", "error_category", "output", "updated_at"])
            if UsageReservation.objects.filter(job=job, state="reserved").exists():
                usage = settle_usage(job=job, actual_units=int(step is not None))
            if useful:
                current = JobRun.objects.select_related("project", "actor").get(pk=job_id, handler=handler)
                contract.validate_job(current, current=True)
                require_billable_access(organization=project.organization)
                if _execution_pin(current) != original["execution"] or JobCancellation.objects.filter(job=current).exists(): raise PermissionDenied
                intended = {"job": {**_job_pin(job), "status": job.status, "output": job.output,
                    "error_category": job.error_category, "updated_at": job.updated_at}, "steps": [collection._row_pin(step)],
                    "ai": collection._row_pin(ai), "artifacts": [collection._row_pin(artifact)],
                    "citations": [collection._row_pin(item) for item in citations], "usage": collection._row_pin(usage)}
                if _read_metadata(job_id) != intended: raise PermissionDenied
                # The private bytes themselves must survive the same final current-source
                # and metadata boundary, not merely have a successful storage receipt.
                if contract.read_result(project=project, actor=job.actor, job_id=job_id)["synthesis"] != result:
                    raise PermissionDenied
                if _read_metadata(job_id) != intended: raise PermissionDenied
                current = JobRun.objects.select_related("project", "actor").get(pk=job_id, handler=handler)
                contract.validate_job(current, current=True)
                if (_execution_pin(current) != original["execution"] or current.status != JobStatus.SUCCEEDED
                    or current.output != job.output or JobCancellation.objects.filter(job=current).exists()): raise PermissionDenied
                require_billable_access(organization=project.organization)
    except Exception:
        if key: delete_project_artifact(project=project, key=key)
        raise
    return True


def execute_competitor_synthesis(job_id, *, request=create_response):
    return _execute_synthesis(job_id, request=request, handler=HANDLER)


def _execute_synthesis(job_id, *, request, handler):
    _contract(handler)
    if connection.in_atomic_block:
        raise ValidationError("AI attempts must commit outside a caller transaction before provider I/O.")
    organization_id = JobRun.objects.filter(pk=job_id, handler=handler).values_list("organization_id", flat=True).first()
    if organization_id is None:
        return False
    with project_artifact_barrier(organization_id, shared=True), _crawl_execution_lock(job_id) as acquired:
        if not acquired: return False
        pins = {}
        try: return _execute(job_id, request=request, pins=pins, handler=handler)
        except Exception: return _finish(job_id, error="handler_failed", original=pins.get("original"),
            response=pins.get("response"), duration_ms=pins.get("duration_ms"))


def _execute(job_id, *, request, pins, handler=HANDLER):
    contract = _contract(handler)
    org_id = JobRun.objects.filter(pk=job_id, handler=handler).values_list("organization_id", flat=True).first()
    if org_id is None: return False
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=org_id)
        job = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id, handler=handler)
        if job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}: return False
        if _denial(job): return _finish(job_id)
        if job.steps.exists(): return _finish(job_id, error="request_outcome_unknown")
        execution = _execution_pin(job)
        if job.status == JobStatus.QUEUED:
            job.status = JobStatus.RUNNING
            job.save(update_fields=["status", "updated_at"])
        step = JobStep.objects.create(job=job, sequence=1, name=contract.STAGE, status="running", output={"method": contract.METHOD, "state": "attempted"})
        ai = record_ai_attempt(job=job, step=step)
        pins["original"] = {"execution": execution, "attempt": {"steps": [collection._row_pin(step)], "ai": collection._row_pin(ai)}}
        if _attempt_pin(job_id) != pins["original"]["attempt"]: raise PermissionDenied
    def checkpoint():
        current = JobRun.objects.select_related("project", "actor").get(pk=job_id, handler=handler)
        if current.status != JobStatus.RUNNING or _denial(current, pins["original"]): raise PermissionDenied
    started = time.monotonic()
    checkpoint()
    model, account, config, source = contract.selection_snapshot(job.project, job.actor, job.input_snapshot)
    if config != job.config_snapshot: raise PermissionDenied
    checkpoint()
    try:
        response = request(account=account, model=model, prompt=source["prompt"], output_schema=contract.synthesis.OUTPUT_SCHEMA,
            max_output_tokens=job.input_snapshot["max_output_tokens"], web_search=False, timeout=30,
            organization=job.organization, expected_revision=config["credential_revision"],
            expected_model_revision=config["model_revision"], checkpoint=checkpoint)
        pins["response"] = response
        pins["duration_ms"] = int((time.monotonic() - started) * 1000)
        checkpoint()
        result = _result(job, source, response)
        contract.validate_result(result, job, source)
    except ProviderRequestError as error:
        # Provider details are untrusted; retain only fixed categories, never answer_text or raw errors.
        category = error.category if type(error.category) is str and error.category in ERRORS else "provider_unavailable"
        return _finish(job_id, error=category, original=pins["original"], provider_request_id=error.request_id,
            input_tokens=error.input_tokens, output_tokens=error.output_tokens, duration_ms=int((time.monotonic() - started) * 1000))
    return _finish(job_id, result=result, response=response, original=pins["original"], duration_ms=int((time.monotonic() - started) * 1000))


def _source_citations(contract, source):
    if contract.HANDLER == TOPICS_HANDLER:
        observation = source["observation"]["collection"]
        return (("Original single " + contract.CITATION_KIND, observation["url"], _date(observation["observed_at"])),)
    return tuple(("Original " + side + " " + contract.CITATION_KIND, source["comparison"]["url"],
        _date(source["comparison"][side]["evidence"]["observed_at"])) for side in ("previous", "current"))


def _reader_source(job, project, actor):
    contract = _contract(job.handler)
    contract.validate_job(job)
    ids = (job.input_snapshot["job_id"],) if job.handler == TOPICS_HANDLER else (
        job.input_snapshot["previous_job_id"], job.input_snapshot["current_job_id"])
    def current_sources():
        return {key: JobRun.objects.select_related("project", "actor").get(pk=key,
            project_id=project.pk, organization_id=project.organization_id) for key in ids}
    callers = _read_pair_sources(current_sources().values(), project, actor)
    model, account, config, source = contract.validate_job(job, current=True)
    if source["selection_digest"] != job.config_snapshot["source_selection_digest"]: raise PermissionDenied
    fresh = current_sources()
    if _read_pair_sources(fresh.values(), project, actor) != callers: raise PermissionDenied
    # Reuse the validated bytes once; mutable authority is still checked afresh.
    model_callers = {}
    for key, row in fresh.items():
        people = {person.pk: person for person in (row.actor, job.actor, actor)}
        bindings = {key: collection._source_snapshot(project, person, row.input_snapshot, row.handler)
            for key, person in people.items()}
        if bindings[row.actor_id] != row.config_snapshot["binding"] or bindings[actor.pk] != callers[key]: raise PermissionDenied
        model_callers[key] = bindings[job.actor_id]
    if (_digest(model_callers) != config["caller_source_sha256"]
        or _digest(synthesis._pins(ids)) != config["source_metadata_sha256"]
        or _digest(_model_rows(model, account)) != config["model_selection_sha256"]): raise PermissionDenied
    if JobCancellation.objects.filter(job_id__in=(job.pk, *ids)).exists(): raise PermissionDenied
    require_billable_access(organization=project.organization)
    return source, callers


def read_competitor_synthesis(*, project, actor, job_id):
    return _read_synthesis(project=project, actor=actor, job_id=job_id, handler=HANDLER)


def _read_synthesis(*, project, actor, job_id, handler):
    contract = _contract(handler)
    collection._safe_id(job_id)
    job = JobRun.objects.select_related("project", "actor").filter(pk=job_id, project_id=project.pk,
        organization_id=project.organization_id, handler=handler, status=JobStatus.SUCCEEDED).first()
    if job is None: raise PermissionDenied
    source, callers = _reader_source(job, project, actor)
    expected_citations = _source_citations(contract, source)
    original = _read_metadata(job_id)
    if (original["job"] != {**_job_pin(job), "status": job.status, "output": job.output,
        "error_category": job.error_category, "updated_at": job.updated_at} or not job.output or job.error_category
        or len(original["steps"]) != 1 or len(original["artifacts"]) != 1 or len(original["citations"]) != len(expected_citations)):
        raise ValidationError("Exact private synthesis provenance is unavailable.")
    step, artifact, ai, usage = original["steps"][0], original["artifacts"][0], original["ai"], original["usage"]
    if (step["sequence"] != 1 or step["name"] != contract.STAGE or step["status"] != "succeeded" or step["progress_percent"] != 100
        or step["error_category"] or step["output"] != {"method": contract.METHOD, "state": contract.STATE}
        or artifact["id"] != job.output["artifact_id"] or artifact["project_id"] != project.pk
        or artifact["content_type"] != "application/json" or not 1 <= artifact["size_bytes"] <= MAX_RESULT_BYTES
        or ai is None or (ai["organization_id"], ai["project_id"], ai["step_id"], ai["provider_id"], ai["model_id"],
            ai["account_id"], ai["operation_version"], ai["status"], ai["error_category"], ai["web_search_used"], ai["tool_call_count"]) !=
           (job.organization_id, project.pk, step["id"], job.config_snapshot["provider_id"], job.input_snapshot["model_id"],
            job.input_snapshot["account_id"], contract.METHOD, "completed", "", False, 0)
        or usage is None or (usage["organization_id"], usage["project_id"], usage["provider"], usage["reserved_units"],
            usage["actual_units"], usage["state"]) != (job.organization_id, project.pk, "ai", 1, 1, "settled")):
        raise ValidationError("Original synthesis attempt/model/usage binding needs review.")
    generated = _date(job.output["generated_at"])
    dates = (job.created_at, usage["created_at"], step["created_at"], ai["attempted_at"], generated, artifact["created_at"],
        *(row["created_at"] for row in original["citations"]), ai["finished_at"], job.updated_at, usage["settled_at"])
    if any(not isinstance(value, datetime) or timezone.is_naive(value) or value > timezone.now() for value in dates) or tuple(sorted(dates)) != dates:
        raise ValidationError("Original source and local AI provenance dates need review.")
    for row, (title, url, observed) in zip(original["citations"], expected_citations, strict=True):
        if (row["step_id"] != step["id"] or row["source_title"] != title
            or row["source_url"] != url or row["observed_at"] != observed or row["observed_at"] > job.created_at):
            raise ValidationError("Preserve both original source dates separately from AI generation.")
    try:
        content = read_project_artifact(project=project, key=artifact["key"])
        if len(content) != artifact["size_bytes"] or sha256(content).hexdigest() != job.output["derived_sha256"]: raise ValueError
        stored = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ArtifactNotFound, ArtifactStorageError, ArtifactValidationError, GoogleTokenError, ValueError, UnicodeError, RecursionError):
        raise ValidationError("Original private synthesis cannot be read back.") from None
    contract.validate_result(stored, job, source)
    if stored["generated_at"] != job.output["generated_at"]: raise ValidationError("Original generation time changed.")
    if _read_metadata(job_id) != original: raise PermissionDenied
    current = JobRun.objects.select_related("project", "actor").get(pk=job_id, handler=handler)
    if _reader_source(current, project, actor) != (source, callers): raise PermissionDenied
    if _read_metadata(job_id) != original: raise PermissionDenied
    if JobCancellation.objects.filter(job_id__in=(job_id, *callers)).exists(): raise PermissionDenied
    require_billable_access(organization=project.organization)
    return {"job_id": job_id, "synthesis": stored, "source_current": True}
