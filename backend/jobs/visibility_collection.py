"""One explicit native API-text observation. Stored answers are evidence, never instructions."""
from datetime import timedelta
from decimal import Decimal
import re
import time

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from providers.adapters import ProviderRequestError, create_response
from providers.models import AIModel, AIProvider
from providers.services import resolve_provider_secret
from tenancy.models import Organization, Project
from tenancy.services import Action, require_project_action
from .ai_text import _configuration, _max_cost, _selection
from .ai_usage import _safe_id, finish_ai_usage, record_ai_attempt
from .crawler import _crawl_execution_lock
from .models import AIVisibilityPromptSet, JobCancellation, JobRun, JobStatus, JobStep, UsageReservation
from .usage import settle_usage, usage_denial
from .visibility_prompts import current_prompt_set

METHOD = "visibility-text-collection-v1"
HANDLER = "sample_ai_visibility"
ROUTE = {"routing_source": "explicit", "routing_policy_id": None, "routing_policy_revision": None,
         "fallback_index": 0, "timeout_seconds": 30}


def valid_answer(text):
    return (type(text) is str and 1 <= len(text) <= 4000
            and not any(ord(char) == 0 or 0xD800 <= ord(char) <= 0xDFFF for char in text))


def validate_collection_input(data):
    if (type(data) is not dict or set(data) != {"prompt_set_id", "prompt_key", "model_id", "account_id",
                                              "max_output_tokens", "max_cost_usd", "acknowledge_api_limits"}
        or any(type(data[key]) is not int or data[key] < 1 for key in ("prompt_set_id", "model_id", "account_id"))
        or type(data["prompt_key"]) is not str or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", data["prompt_key"])
        or type(data["max_output_tokens"]) is not int or not 1 <= data["max_output_tokens"] <= 256
        or data["acknowledge_api_limits"] is not True):
        raise ValidationError("Choose one reviewed prompt and explicitly acknowledge API-only sampling limits.")
    _max_cost(data["max_cost_usd"])
    return data


def selection_snapshot(project, actor, data):
    data = validate_collection_input(data)
    row = AIVisibilityPromptSet.objects.filter(pk=data["prompt_set_id"], project=project).first()
    if row is None:
        raise PermissionDenied
    current_prompt_set(project=project, actor=actor, row=row)
    prompt = next((prompt for prompt in row.prompts if prompt["key"] == data["prompt_key"]), None)
    if prompt is None or data["max_output_tokens"] > row.policy["max_output_tokens"] or _max_cost(data["max_cost_usd"]) > Decimal(row.policy["max_cost_usd"]):
        raise ValidationError("Use the reviewed prompt and its token/cost ceilings.")
    budget = {**data, "prompt": prompt["text"], "allow_free": False}
    model, account = _selection(budget, organization_id=project.organization_id)
    if model.provider.kind != AIProvider.Kind.OPENAI or model.access_tier != AIModel.AccessTier.STANDARD:
        raise ValidationError("This methodology supports only explicitly selected native standard-access text models.")
    config = _configuration(model, account, budget, ROUTE)
    return model, account, {**config, "visibility": {"prompt_set_id": row.pk, "set_id": str(row.set_id),
        "revision": row.revision, "methodology": row.policy["method"], "prompt": prompt,
        "context": row.context, "policy": row.policy, "review_note": row.review_note}}


def repeat_available_at(project, set_id, prompt_key):
    attempted = JobStep.objects.filter(job__project=project, job__handler=HANDLER, sequence=1,
        job__config_snapshot__visibility__set_id=str(set_id), job__input_snapshot__prompt_key=prompt_key).order_by("-created_at").first()
    return attempted.created_at + timedelta(hours=24) if attempted else None


def _repeat_denial(project, config, data, *, exclude=None):
    peers = JobRun.objects.filter(project=project, handler=HANDLER,
        config_snapshot__visibility__set_id=config["visibility"]["set_id"], input_snapshot__prompt_key=data["prompt_key"])
    if exclude is not None:
        peers = peers.exclude(pk=exclude)
    if peers.filter(status__in=[JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.WAITING_PROVIDER]).exists():
        return "sample_in_flight"
    if JobStep.objects.filter(job__in=peers, sequence=1, created_at__gt=timezone.now() - timedelta(hours=24)).exists():
        return "sample_repeat_cooldown"
    return ""


def queue_visibility_sample(*, project, actor, data, idempotency_key):
    from .services import queue_job
    data = validate_collection_input(data)
    with transaction.atomic():
        org = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=org)
        require_project_action(project=project, user=actor, action=Action.LAUNCH_JOB)
        _model, _account, config = selection_snapshot(project, actor, data)
        existing = JobRun.objects.filter(project=project, handler=HANDLER, idempotency_key=idempotency_key).first()
        if existing:
            if existing.actor_id != actor.pk or existing.input_snapshot != data or existing.config_snapshot != config:
                raise ValidationError("Sample key belongs to another request.")
            return existing
        denied = _repeat_denial(project, config, data)
        if denied:
            raise ValidationError(denied, code=denied)
        return queue_job(project=project, actor=actor, handler=HANDLER, input_snapshot=data,
                         config_snapshot=config, idempotency_key=idempotency_key)


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
        _model, _account, config = selection_snapshot(job.project, job.actor, job.input_snapshot)
        if job.method_version != METHOD or job.config_snapshot != config or job.retry_of_id:
            return "sample_selection_changed"
        if job.schedule_id:
            from .visibility_schedule import schedule_denial, validate_scheduled_job
            validate_scheduled_job(job)
            from .models import JobSchedule
            schedule = JobSchedule.objects.select_related("project", "actor").get(pk=job.schedule_id)
            denied = schedule_denial(schedule, for_job=job)
            if denied:
                return denied
        return _repeat_denial(job.project, config, job.input_snapshot, exclude=job.pk)
    except (PermissionDenied, ValidationError, KeyError, TypeError):
        return "sample_selection_changed"


def _finish(job_id, *, result=None, error="", duration_ms=None, provider_request_id="", input_tokens=None,
            output_tokens=None, answer_text="", response_id="", response_model=""):
    org_id = JobRun.objects.filter(pk=job_id, handler=HANDLER).values_list("organization_id", flat=True).first()
    if org_id is None:
        return False
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=org_id)
        job = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id)
        if job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            return False
        denied = _denial(job)
        step = job.steps.filter(sequence=1).first()
        if job.status == JobStatus.QUEUED:
            job.status = JobStatus.RUNNING
            job.save(update_fields=["status", "updated_at"])
        if result is not None:
            answer_text, response_id, response_model = result.text, result.response_id, result.response_model
        collected = step is not None and valid_answer(answer_text)
        completed = result is not None and collected and not error
        job.output = ({"answer": answer_text, "collected_at": timezone.now().isoformat(),
            "provider_status": "completed" if completed else error or "unknown",
            "response_id": _safe_id(response_id), "returned_model": _safe_id(response_model) or None,
            "surface": "openai_responses_text", "mode": "text_only_no_tools", "citations": None,
            "citation_measurement": "unavailable", "evaluation": "unevaluated",
            "collection_eligible": completed and not denied,
            "delivery_limit": denied or error or "", "referral_visits": None} if collected else {})
        if step:
            step.status = JobStep.Status.SUCCEEDED if completed and not denied else JobStep.Status.FAILED
            step.error_category = denied or error or ("request_outcome_unknown" if not completed else "")
            step.output = {"state": "collected_unevaluated" if collected else "unavailable"}
            step.save(update_fields=["status", "error_category", "output"])
            finish_ai_usage(job=job, step=step, result=result, error=error, duration_ms=duration_ms,
                provider_request_id=provider_request_id, input_tokens=input_tokens, output_tokens=output_tokens)
        job.status = JobStatus.CANCELLED if denied else JobStatus.SUCCEEDED if completed else JobStatus.FAILED
        job.error_category = denied or error or ("request_outcome_unknown" if not completed else "")
        job.save(update_fields=["status", "error_category", "output", "updated_at"])
        if UsageReservation.objects.filter(job=job, state=UsageReservation.State.RESERVED).exists():
            settle_usage(job=job, actual_units=int(step is not None))
        from .visibility_schedule import finish_scheduled_occurrence
        finish_scheduled_occurrence(job)
    return True


def execute_visibility_sample(job_id, *, request=create_response):
    with _crawl_execution_lock(job_id) as acquired:
        if not acquired:
            return False
        try:
            return _execute(job_id, request=request)
        except Exception:
            return _finish(job_id, error="handler_failed")


def _execute(job_id, *, request):
    org_id = JobRun.objects.filter(pk=job_id, handler=HANDLER).values_list("organization_id", flat=True).first()
    if org_id is None:
        return False
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=org_id)
        job = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id)
        if job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            return False
        if _denial(job):
            return _finish(job_id)
        if job.status == JobStatus.QUEUED:
            job.status = JobStatus.RUNNING
            job.save(update_fields=["status", "updated_at"])
    if job.steps.filter(sequence=1).exists():
        return _finish(job_id, error="request_outcome_unknown")
    model, account, config = selection_snapshot(job.project, job.actor, job.input_snapshot)
    try:
        resolve_provider_secret(account, organization=job.organization, expected_revision=config["credential_revision"])
    except (PermissionDenied, ValidationError):
        return _finish(job_id, error="credential_unavailable")
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=org_id)
        if _denial(job):
            return _finish(job_id)
        step = JobStep.objects.create(job=job, sequence=1, name="Request selected model", status=JobStep.Status.RUNNING,
                                      output={"state": "attempted"})
        record_ai_attempt(job=job, step=step)
        job.save(update_fields=["updated_at"])
    started = time.monotonic()
    result = None
    try:
        result = request(account=account, model=model, prompt=config["visibility"]["prompt"]["text"],
            max_output_tokens=job.input_snapshot["max_output_tokens"], timeout=30, organization=job.organization,
            expected_revision=config["credential_revision"], expected_model_revision=config["model_revision"], preserve_answer=True)
        if not valid_answer(result.text) or result.citations or result.structured is not None:
            raise ValidationError("Unexpected or oversized text evidence.")
    except ProviderRequestError as error:
        return _finish(job_id, error=error.category, provider_request_id=error.request_id,
            input_tokens=error.input_tokens, output_tokens=error.output_tokens, answer_text=error.answer_text,
            response_id=error.response_id, response_model=error.response_model, duration_ms=int((time.monotonic() - started) * 1000))
    except (PermissionDenied, ValidationError):
        return _finish(job_id, result=result, error="sample_output_invalid", duration_ms=int((time.monotonic() - started) * 1000))
    return _finish(job_id, result=result, duration_ms=int((time.monotonic() - started) * 1000))
