from http import HTTPStatus

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.db.models import Q
from django.views.decorators.http import require_http_methods

from providers.models import AIModel, AIModelCapability, AIProvider, AIProviderAccount
from tenancy.services import Action, require_project_action
from .ai_text_api import _job as _ai_job, _payload, _project
from .models import AIVisibilityPromptSet, JobRun
from .research_api import _result
from .services import cancel_job
from .usage import UsageLimitError
from .visibility_collection import HANDLER, METHOD, queue_visibility_sample, repeat_available_at, selection_snapshot
from .visibility_prompt_api import _row as _prompt_set


def _job(job, *, detailed=False):
    data = _ai_job(job)
    visibility = job.config_snapshot["visibility"]
    try:
        current = selection_snapshot(job.project, job.actor, job.input_snapshot)[2] == job.config_snapshot
        if job.schedule_id:
            require_project_action(project=job.project, user=job.actor, action=Action.MANAGE_PROJECT)
    except (PermissionDenied, ValidationError):
        current = False
    next_at = repeat_available_at(job.project, visibility["set_id"], job.input_snapshot["prompt_key"])
    return {**data, "text": "", "set_id": visibility["set_id"], "prompt_set_id": visibility["prompt_set_id"],
        "revision": visibility["revision"], "prompt_key": job.input_snapshot["prompt_key"],
        "prompt_kind": visibility["prompt"]["kind"], "model_identifier": job.config_snapshot["model_identifier"],
        "account_id": job.input_snapshot["account_id"], "source_current": current, "estimate_units": 1,
        "collection_state": "collected_unevaluated" if job.output else "unavailable" if job.error_category else "not_collected",
        "repeat_available_at": next_at.isoformat() if next_at else None,
        "repeat_context": {"method": job.schedule.input_snapshot["policy"]["method"] if job.schedule_id else "manual",
            "policy": job.schedule.input_snapshot["policy"] if job.schedule_id else None,
            "schedule_id": job.schedule_id, "scheduled_for": job.scheduled_for.isoformat() if job.scheduled_for else None},
        "methodology": visibility if detailed else None, "evidence": job.output or None if detailed else None,
        "settings": {"max_output_tokens": job.input_snapshot["max_output_tokens"],
                     "max_cost_usd": job.input_snapshot["max_cost_usd"], "timeout_seconds": 30,
                     "retrieval": "none", "store": False, "temperature": "provider_default_not_controlled",
                     "language_location_device": "not_guaranteed_or_unsupported"}, "created_at": job.created_at.isoformat()}


@require_http_methods(["GET", "POST"])
def project_visibility_samples(request, organization_id, project_id, job_id=None):
    if not request.user.is_authenticated or not request.user.is_active:
        return _result({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _result({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.VIEW_PROJECT)
    except PermissionDenied:
        return _result({"message": "Project evidence unavailable."}, HTTPStatus.FORBIDDEN)
    job = JobRun.objects.filter(pk=job_id, project=project, handler=HANDLER).first() if job_id else None
    if job_id and job is None:
        return _result({"message": "Sample unavailable."}, HTTPStatus.NOT_FOUND)
    if request.method == "POST":
        if not ratelimit.consume(request, action="ai_text_request", user=request.user):
            return _result({"message": "Too many sample requests."}, HTTPStatus.TOO_MANY_REQUESTS)
        try:
            if job:
                _payload(request, set())
                job, _changed, _pending = cancel_job(job=job, actor=request.user)
            else:
                data = _payload(request, {"prompt_set_id", "prompt_key", "model_id", "account_id", "max_output_tokens",
                                         "max_cost_usd", "acknowledge_api_limits", "idempotency_key"})
                key = data.pop("idempotency_key")
                job = queue_visibility_sample(project=project, actor=request.user, data=data, idempotency_key=key)
        except PermissionDenied:
            return _result({"message": "Current project role or methodology unavailable."}, HTTPStatus.FORBIDDEN)
        except UsageLimitError as error:
            return _result({"message": "Sample allowance unavailable.", "code": error.category}, HTTPStatus.TOO_MANY_REQUESTS)
        except (ValidationError, ValueError, TypeError, UnicodeError, IntegrityError) as error:
            code = getattr(error, "code", "")
            return _result({"message": "Choose exact-current reviewed prompt, native standard model/account and bounded budget; repeats require24hours.",
                "code": code if code in {"sample_repeat_cooldown", "sample_in_flight"} else "sample_selection_unavailable"}, HTTPStatus.CONFLICT)
        return _result({"project_id": project.pk, "job": _job(job, detailed=True)}, HTTPStatus.OK if job_id else HTTPStatus.ACCEPTED)
    if job:
        return _result({"project_id": project.pk, "job": _job(job, detailed=True)})
    models = list(AIModel.objects.filter(enabled=True, provider__enabled=True, provider__kind=AIProvider.Kind.OPENAI,
        access_tier=AIModel.AccessTier.STANDARD, capabilities__contains=[AIModelCapability.TEXT_GENERATION],
        input_price_usd_per_million__isnull=False, output_price_usd_per_million__isnull=False,
        pricing_verified_at__isnull=False).exclude(pricing_source="").order_by("pk")[:101])
    accounts = list(AIProviderAccount.objects.filter(state="active", provider__enabled=True, provider__kind=AIProvider.Kind.OPENAI)
        .filter(Q(organization__isnull=True) | Q(organization_id=project.organization_id)).order_by("pk")[:101])
    rows = list(JobRun.objects.filter(project=project, handler=HANDLER).order_by("-pk")[:21])
    sets = list(AIVisibilityPromptSet.objects.filter(project=project).order_by("set_id", "-revision").distinct("set_id")[:21])
    return _result({"project_id": project.pk, "method": METHOD, "surface": "openai_responses_text", "live_verified": False,
        "automatic_schedule": False, "estimate_units": 1, "repeat_minimum_hours": 24,
        "models": [{"id": row.pk, "provider_id": row.provider_id, "identifier": row.identifier, "name": row.name,
                    "max_output_tokens": row.max_output_tokens} for row in models[:100]],
        "accounts": [{"id": row.pk, "provider_id": row.provider_id, "label": row.label,
                      "source": "platform" if row.organization_id is None else "organization"} for row in accounts[:100]],
        "prompt_sets": [{**_prompt_set(project, request.user, row), "repeat_available_at": {prompt["key"]:
            (next_at.isoformat() if (next_at := repeat_available_at(project, row.set_id, prompt["key"])) else None)
            for prompt in row.prompts}} for row in sets[:20]],
        "jobs": [_job(row) for row in rows[:20]], "has_more": any(len(items) > bound for items, bound in
            ((models, 100), (accounts, 100), (rows, 20), (sets, 20)))})
