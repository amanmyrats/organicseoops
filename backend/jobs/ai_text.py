import re
import time
from decimal import Decimal, ROUND_UP

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from providers.adapters import ProviderRequestError, create_response
from providers.models import AIModel, AIModelCapability, AIProviderAccount
from providers.services import require_model_capabilities, resolve_provider_secret
from tenancy.models import Organization, Project
from tenancy.services import Action, require_project_action

from .crawler import _crawl_execution_lock
from .ai_usage import finish_ai_usage, record_ai_attempt
from .models import JobCancellation, JobRun, JobStatus, JobStep, UsageReservation
from .usage import settle_usage, usage_denial


METHOD = "ai-text-v2"


def _max_cost(value):
    if type(value) is not str or not re.fullmatch(r"\d{1,3}(?:\.\d{1,6})?", value):
        raise ValidationError("Choose a bounded positive USD cost ceiling.")
    cost = Decimal(value)
    if not 0 < cost <= 100:
        raise ValidationError("Choose a bounded positive USD cost ceiling.")
    return cost


def validate_ai_text_input(data):
    if (
        type(data) is not dict or set(data) != {"model_id", "account_id", "prompt", "max_output_tokens",
                                                  "max_cost_usd", "allow_free"}
        or any(type(data[key]) is not int or data[key] < 1 for key in ("model_id", "account_id"))
        or type(data["prompt"]) is not str or not 1 <= len(data["prompt"]) <= 2000
        or type(data["max_output_tokens"]) is not int or not 1 <= data["max_output_tokens"] <= 256
        or type(data["allow_free"]) is not bool
    ):
        raise ValidationError("Choose a bounded text request and an enabled model.")
    _max_cost(data["max_cost_usd"])
    return data


def _selection(data, *, organization_id):
    model = AIModel.objects.filter(pk=data["model_id"]).first()
    if model is None:
        raise ValidationError("Choose an enabled text model.")
    model = require_model_capabilities(model, {AIModelCapability.TEXT_GENERATION})
    if model.max_output_tokens is not None and data["max_output_tokens"] > model.max_output_tokens:
        raise ValidationError("Output limit exceeds the selected model limit.")
    if (model.access_tier == AIModel.AccessTier.UNKNOWN
        or model.input_price_usd_per_million is None or model.output_price_usd_per_million is None
        or model.pricing_verified_at is None or not model.pricing_source):
        raise ValidationError("Verified model price and access policy are unavailable.")
    if model.access_tier == AIModel.AccessTier.FREE and (not data["allow_free"] or not model.privacy_policy_url):
        raise ValidationError("Free-tier data use requires explicit acknowledgement.")
    if model.access_tier != AIModel.AccessTier.FREE and data["allow_free"]:
        raise ValidationError("Free-tier consent cannot be applied to a different model.")
    if _estimated_cost(model, data) > _max_cost(data["max_cost_usd"]):
        raise ValidationError("Selected model exceeds the request cost ceiling.")
    account = AIProviderAccount.objects.filter(pk=data["account_id"], provider=model.provider,
                                               state=AIProviderAccount.State.ACTIVE).first()
    if account is None or (account.organization_id is not None and account.organization_id != organization_id):
        raise ValidationError("Choose an available provider account for this model.")
    return model, account


def _estimated_cost(model, data):
    # ponytail: conservative byte+1024 input-token estimate; use provider metering if pricing variance demands it.
    input_ceiling = len(data["prompt"].encode("utf-8")) + 1024
    return ((input_ceiling * model.input_price_usd_per_million
             + data["max_output_tokens"] * model.output_price_usd_per_million) / Decimal(1_000_000)).quantize(
                 Decimal("0.000001"), rounding=ROUND_UP)


def _route_details(route):
    if (type(route) is not dict or set(route) != {"routing_source", "routing_policy_id", "routing_policy_revision",
                                                  "fallback_index", "timeout_seconds"}
        or type(route["routing_source"]) is not str
        or route["routing_source"] not in {"explicit", "project", "system"}
        or type(route["timeout_seconds"]) is not int or not 1 <= route["timeout_seconds"] <= 30
        or type(route["fallback_index"]) is not int or not 0 <= route["fallback_index"] <= 2):
        raise ValidationError("AI routing details are unavailable.")
    if route["routing_source"] == "explicit":
        if route["routing_policy_id"] is not None or route["routing_policy_revision"] is not None \
                or route["fallback_index"] != 0:
            raise ValidationError("Explicit model selection cannot use a fallback policy.")
    elif (type(route["routing_policy_id"]) is not int or route["routing_policy_id"] < 1
          or type(route["routing_policy_revision"]) is not int or route["routing_policy_revision"] < 1):
        raise ValidationError("AI routing policy identity is unavailable.")
    return route


def _configuration(model, account, data, route):
    route = _route_details(route)
    return {"provider_id": model.provider_id, "model_identifier": model.identifier,
            "provider_kind": model.provider.kind, "provider_base_url": model.provider.base_url,
            "model_revision": model.updated_at.isoformat(),
            "model_access_tier": model.access_tier,
            "input_price_usd_per_million": str(model.input_price_usd_per_million),
            "output_price_usd_per_million": str(model.output_price_usd_per_million),
            "estimated_max_cost_usd": str(_estimated_cost(model, data)),
            "account_id": account.pk,
            "credential_revision": account.rotated_at.isoformat() if account.rotated_at else "", **route}


def queue_ai_text(*, project, actor, model, account, prompt, max_output_tokens, max_cost_usd, allow_free,
                  idempotency_key, route=None):
    from .services import queue_job

    data = validate_ai_text_input({"model_id": model.pk, "account_id": account.pk, "prompt": prompt,
                                   "max_output_tokens": max_output_tokens, "max_cost_usd": max_cost_usd,
                                   "allow_free": allow_free})
    route = _route_details(route if route is not None else {"routing_source": "explicit", "routing_policy_id": None,
                                                            "routing_policy_revision": None, "fallback_index": 0,
                                                            "timeout_seconds": 30})
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        require_project_action(project=project, user=actor, action=Action.LAUNCH_JOB)
        model, account = _selection(data, organization_id=organization.pk)
        return queue_job(project=project, actor=actor, handler="ai_text", input_snapshot=data,
                          config_snapshot=_configuration(model, account, data, route),
                          idempotency_key=idempotency_key)


def queue_routed_ai_text(*, project, actor, prompt, max_output_tokens, max_cost_usd, idempotency_key):
    from providers.routing import choose_ai_text_route

    # Validate caller-controlled values before policy resolution and any reservation.
    validate_ai_text_input({"model_id": 1, "account_id": 1, "prompt": prompt,
                            "max_output_tokens": max_output_tokens, "max_cost_usd": max_cost_usd,
                            "allow_free": False})
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        require_project_action(project=project, user=actor, action=Action.LAUNCH_JOB)
        model, account, data, route = choose_ai_text_route(
            project=project, prompt=prompt, max_output_tokens=max_output_tokens, max_cost_usd=max_cost_usd)
        return queue_ai_text(project=project, actor=actor, model=model, account=account,
                             prompt=prompt, max_output_tokens=data["max_output_tokens"],
                             max_cost_usd=data["max_cost_usd"], allow_free=False,
                             idempotency_key=idempotency_key, route=route)


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
        data = validate_ai_text_input(job.input_snapshot)
        model, account = _selection(data, organization_id=job.organization_id)
        if (job.handler != "ai_text" or job.method_version != METHOD
            or job.config_snapshot != _configuration(model, account, data, {
                key: job.config_snapshot.get(key) for key in ("routing_source", "routing_policy_id",
                                                           "routing_policy_revision", "fallback_index", "timeout_seconds")
            })):
            return "model_unavailable"
    except (ValidationError, PermissionDenied):
        return "model_unavailable"
    return ""


def _finish(job_id, *, result=None, error="", provider_request_id="", duration_ms=None,
            input_tokens=None, output_tokens=None):
    org_id = JobRun.objects.filter(pk=job_id).values_list("organization_id", flat=True).first()
    if org_id is None:
        return False
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=org_id)
        job = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id)
        if job.handler != "ai_text" or job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            return False
        denied = _denial(job)
        step = JobStep.objects.filter(job=job, sequence=1).first()
        if step is not None and step.status == JobStep.Status.RUNNING:
            step.status = JobStep.Status.FAILED if denied or error or result is None else JobStep.Status.SUCCEEDED
            step.error_category = denied or error or ("request_outcome_unknown" if result is None else "")
            step.output = {"state": "unknown" if step.error_category else "completed"}
            step.save(update_fields=["status", "error_category", "output"])
        if job.status == JobStatus.QUEUED:
            job.status = JobStatus.RUNNING
            job.save(update_fields=["status", "updated_at"])
        job.status = JobStatus.CANCELLED if denied else JobStatus.FAILED if error or result is None else JobStatus.SUCCEEDED
        job.error_category = denied or error or ("request_outcome_unknown" if result is None else "")
        job.output = ({"model_id": job.input_snapshot["model_id"], "text": result.text,
                       "request_id": result.request_id, "response_id": result.response_id,
                       "input_tokens": result.input_tokens, "output_tokens": result.output_tokens}
                      if job.status == JobStatus.SUCCEEDED else {})
        job.save(update_fields=["status", "error_category", "output", "updated_at"])
        if step is not None:
            finish_ai_usage(job=job, step=step, result=result, error=error,
                            provider_request_id=provider_request_id, duration_ms=duration_ms,
                            input_tokens=input_tokens, output_tokens=output_tokens)
        if UsageReservation.objects.filter(job=job, state=UsageReservation.State.RESERVED).exists():
            settle_usage(job=job, actual_units=int(step is not None))
    return True


def execute_ai_text(job_id, *, request=create_response):
    with _crawl_execution_lock(job_id) as acquired:
        if not acquired:
            return False
        try:
            return _execute(job_id, request=request)
        except Exception:
            return _finish(job_id, error="handler_failed")


def _execute(job_id, *, request):
    org_id = JobRun.objects.filter(pk=job_id).values_list("organization_id", flat=True).first()
    if org_id is None:
        return False
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=org_id)
        job = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id)
        if job.handler != "ai_text" or job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            return False
        denied = _denial(job)
        if not denied and job.status == JobStatus.QUEUED:
            job.status = JobStatus.RUNNING
            job.save(update_fields=["status", "updated_at"])
    if denied:
        return _finish(job_id)
    if JobStep.objects.filter(job_id=job_id, sequence=1).exists():
        return _finish(job_id, error="request_outcome_unknown")
    data = job.input_snapshot
    try:
        model, account = _selection(data, organization_id=org_id)
        resolve_provider_secret(account, organization=job.organization,
                                expected_revision=job.config_snapshot["credential_revision"])
    except (PermissionDenied, ValidationError):
        return _finish(job_id, error="credential_unavailable")
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=org_id)
        job = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id)
        denied = _denial(job)
        if denied or JobStep.objects.filter(job=job, sequence=1).exists():
            return _finish(job_id, error="request_outcome_unknown")
        step = JobStep.objects.create(job=job, sequence=1, name="Request selected model",
                                      status=JobStep.Status.RUNNING, output={"state": "attempted"})
        record_ai_attempt(job=job, step=step)
        job.save(update_fields=["updated_at"])
    started = time.monotonic()
    try:
        response = request(account=account, model=model, prompt=data["prompt"],
                           max_output_tokens=data["max_output_tokens"],
                           timeout=job.config_snapshot["timeout_seconds"], organization=job.organization,
                           expected_revision=job.config_snapshot["credential_revision"],
                           expected_model_revision=job.config_snapshot["model_revision"])
        if not isinstance(response.text, str) or not 1 <= len(response.text) <= 4000:
            raise ValidationError("Provider output exceeded the allowed size.")
    except ProviderRequestError as error:
        return _finish(job_id, error=error.category, provider_request_id=error.request_id,
                       input_tokens=error.input_tokens, output_tokens=error.output_tokens,
                       duration_ms=int((time.monotonic() - started) * 1000))
    except (PermissionDenied, ValidationError):
        return _finish(job_id, error="provider_unavailable", duration_ms=int((time.monotonic() - started) * 1000))
    return _finish(job_id, result=response, duration_ms=int((time.monotonic() - started) * 1000))
