import json
from http import HTTPStatus

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from providers.models import AIModel, AIModelCapability, AIProviderAccount
from tenancy.models import Project
from tenancy.services import Action, require_project_action

from .ai_text import queue_ai_text, queue_routed_ai_text
from .models import AIUsageRecord, JobCancellation, JobRun, JobStatus, JobStep
from .services import cancel_job
from .usage import UsageLimitError


def _response(data, status=HTTPStatus.OK):
    response = JsonResponse(data, status=status)
    response["Cache-Control"] = "private, no-store"
    return response


def _project(request, organization_id, project_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return None
    return Project.objects.for_user(request.user).filter(pk=project_id, organization_id=organization_id).first()


def _payload(request, fields, optional=(), *, max_bytes=8192):
    if len(request.body) > max_bytes:
        raise ValueError
    data = json.loads(request.body)
    if type(data) is not dict or set(data) - set(optional) != fields:
        raise ValueError
    return data


def _job(job):
    usage = AIUsageRecord.objects.filter(job=job).first()
    return {"id": job.pk, "project_id": job.project_id, "status": job.status,
            "cancel_requested": JobCancellation.objects.filter(job=job).exists(),
            "error_category": job.error_category or job.dispatch_error,
            "text": job.output.get("text", "") if job.status == JobStatus.SUCCEEDED else "",
            "attempted_units": job.steps.filter(sequence=1).count(),
            "estimated_max_cost_usd": job.config_snapshot.get("estimated_max_cost_usd"),
            "routing_source": job.config_snapshot.get("routing_source", "explicit"),
            "fallback_index": job.config_snapshot.get("fallback_index", 0),
            "usage": ({"provider_id": usage.provider_id, "model_id": usage.model_id,
                       "operation_version": usage.operation_version, "request_status": usage.status,
                       "error_category": usage.error_category, "input_tokens": usage.input_tokens,
                       "output_tokens": usage.output_tokens, "duration_ms": usage.duration_ms,
                       "provider_request_id": usage.provider_request_id,
                       "provider_response_id": usage.provider_response_id,
                       "estimated_cost_usd": str(usage.estimated_cost_usd)
                       if usage.estimated_cost_usd is not None else None,
                       "reported_cost_usd": str(usage.reported_cost_usd)
                       if usage.reported_cost_usd is not None else None,
                       "web_search_used": usage.web_search_used, "tool_call_count": usage.tool_call_count}
                      if usage is not None else None),
            "updated_at": job.updated_at.isoformat()}


@require_http_methods(["GET", "POST"])
def project_ai_text(request, organization_id, project_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _response({"message": "Project not found."}, HTTPStatus.NOT_FOUND)
    if request.method == "GET":
        try:
            require_project_action(project=project, user=request.user, action=Action.VIEW_PROJECT)
        except PermissionDenied:
            return _response({"message": "Project access unavailable."}, HTTPStatus.FORBIDDEN)
        models = list(AIModel.objects.filter(enabled=True, provider__enabled=True,
                                            capabilities__contains=[AIModelCapability.TEXT_GENERATION])
                      .order_by("pk")[:101])
        accounts = list(AIProviderAccount.objects.filter(
            state=AIProviderAccount.State.ACTIVE, provider__enabled=True,
        ).filter(organization__isnull=True)[:101])
        own = list(AIProviderAccount.objects.filter(
            organization=project.organization, state=AIProviderAccount.State.ACTIVE, provider__enabled=True,
        ).order_by("pk")[:101])
        return _response({"models": [{"id": row.pk, "provider_id": row.provider_id, "name": row.name,
                                      "identifier": row.identifier, "max_output_tokens": row.max_output_tokens,
                                      "access_tier": row.access_tier,
                                      "price_known": row.input_price_usd_per_million is not None
                                      and row.output_price_usd_per_million is not None,
                                      "privacy_policy_url": row.privacy_policy_url}
                                     for row in models[:100]],
                          "accounts": [{"id": row.pk, "provider_id": row.provider_id, "label": row.label,
                                        "source": "platform" if row.organization_id is None else "organization"}
                                       for row in (accounts[:100] + own[:100])],
                          "has_more": any(len(rows) > 100 for rows in (models, accounts, own)),
                          "estimate_units": 1, "cost_status": "unknown"})
    if not ratelimit.consume(request, action="ai_text_request", user=request.user):
        return _response({"message": "Too many AI requests."}, HTTPStatus.TOO_MANY_REQUESTS)
    try:
        data = _payload(request, {"model_id", "account_id", "prompt", "max_output_tokens", "idempotency_key",
                                  "max_cost_usd", "allow_free"})
        if data["model_id"] is None and data["account_id"] is None:
            if data["allow_free"] is not False:
                raise ValueError
            job = queue_routed_ai_text(project=project, actor=request.user, prompt=data["prompt"],
                                       max_output_tokens=data["max_output_tokens"],
                                       max_cost_usd=data["max_cost_usd"], idempotency_key=data["idempotency_key"])
        else:
            if any(type(data[key]) is not int or data[key] < 1 for key in ("model_id", "account_id")):
                raise ValueError
            model = AIModel.objects.filter(pk=data["model_id"]).first()
            account = AIProviderAccount.objects.filter(pk=data["account_id"]).first()
            if model is None or account is None:
                raise ValueError
            job = queue_ai_text(project=project, actor=request.user, model=model, account=account,
                                prompt=data["prompt"], max_output_tokens=data["max_output_tokens"],
                                max_cost_usd=data["max_cost_usd"], allow_free=data["allow_free"],
                                idempotency_key=data["idempotency_key"])
    except PermissionDenied:
        return _response({"message": "You cannot launch AI work for this project."}, HTTPStatus.FORBIDDEN)
    except UsageLimitError as error:
        return _response({"message": "Trial or internal AI capacity is unavailable.", "code": error.category},
                         HTTPStatus.TOO_MANY_REQUESTS)
    except (ValidationError, ValueError, TypeError, UnicodeError, IntegrityError):
        return _response({"message": "Choose an available model/account and bounded text request."}, HTTPStatus.BAD_REQUEST)
    return _response({"job": _job(job)}, HTTPStatus.ACCEPTED)


@require_http_methods(["GET"])
def project_ai_text_history(request, organization_id, project_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _response({"message": "Project not found."}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.VIEW_PROJECT)
    except PermissionDenied:
        return _response({"message": "Project access unavailable."}, HTTPStatus.FORBIDDEN)
    jobs = list(JobRun.objects.filter(project=project, handler="ai_text").order_by("-created_at", "-pk")[:21])
    ids = [job.pk for job in jobs[:20]]
    observations = {record.job_id: record for record in AIUsageRecord.objects.filter(job_id__in=ids)}
    attempted = set(JobStep.objects.filter(job_id__in=ids, sequence=1).values_list("job_id", flat=True))
    return _response({"jobs": [{"id": job.pk, "status": job.status, "updated_at": job.updated_at.isoformat(),
                                "model_id": job.input_snapshot.get("model_id") if isinstance(job.input_snapshot, dict)
                                and type(job.input_snapshot.get("model_id")) is int else None,
                                "request_status": observations[job.pk].status if job.pk in observations
                                else "unknown" if job.pk in attempted else "not_attempted",
                                "attempted_units": int(job.pk in attempted),
                                "estimated_cost_usd": (str(observations[job.pk].estimated_cost_usd)
                                                       if observations[job.pk].estimated_cost_usd is not None else None)
                                if job.pk in observations else None,
                                "reported_cost_usd": (str(observations[job.pk].reported_cost_usd)
                                                      if observations[job.pk].reported_cost_usd is not None else None)
                                if job.pk in observations else None} for job in jobs[:20]],
                      "has_more": len(jobs) > 20}, HTTPStatus.OK)


@require_http_methods(["GET", "POST"])
def project_ai_text_job(request, organization_id, project_id, job_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _response({"message": "Project not found."}, HTTPStatus.NOT_FOUND)
    job = JobRun.objects.filter(pk=job_id, project=project, handler="ai_text").first()
    if job is None:
        return _response({"message": "AI job not found."}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user,
                               action=Action.VIEW_PROJECT if request.method == "GET" else Action.LAUNCH_JOB)
        if request.method == "POST":
            _payload(request, set())
            job, _changed, _requested = cancel_job(job=job, actor=request.user)
    except PermissionDenied:
        return _response({"message": "Project job access unavailable."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, ValueError, TypeError, UnicodeError):
        return _response({"message": "AI cancellation is unavailable."}, HTTPStatus.CONFLICT)
    return _response({"job": _job(job)})
