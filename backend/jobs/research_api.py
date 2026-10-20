from http import HTTPStatus

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.views.decorators.http import require_http_methods

from providers.models import AIModel, AIModelCapability, AIProviderAccount
from tenancy.services import Action, require_project_action
from .ai_text_api import _job as _ai_job, _payload, _project, _response
from .models import JobRun, JobStatus
from .research import _context, queue_research
from .services import cancel_job
from .usage import UsageLimitError


def _result(data, status=HTTPStatus.OK):
    response = _response(data, status)
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


def _job(job):
    ai = _ai_job(job)
    try:
        current = _context(job.project, job.input_snapshot, job.actor) == job.config_snapshot.get("research_context")
    except (PermissionDenied, ValidationError):
        current = False
    return {"id": job.pk, "project_id": job.project_id, "status": job.status,
            "topic": job.input_snapshot["topic"], "updated_at": job.updated_at.isoformat(),
            "cancel_requested": ai["cancel_requested"], "error_category": ai["error_category"],
            "estimate_units": len(job.input_snapshot["source_urls"]) + 1,
            "attempted_units": job.steps.count(), "estimated_max_cost_usd": ai["estimated_max_cost_usd"],
            "usage": ai["usage"], "evidence": job.output if job.status in {
                JobStatus.SUCCEEDED, JobStatus.PARTIALLY_SUCCEEDED, JobStatus.FAILED} else None,
            "context_current": current}


@require_http_methods(["GET", "POST"])
def project_research(request, organization_id, project_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _result({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _result({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.VIEW_PROJECT)
    except PermissionDenied:
        return _result({"message": "Project access unavailable."}, HTTPStatus.FORBIDDEN)
    if request.method == "GET":
        models = list(AIModel.objects.filter(enabled=True, provider__enabled=True,
            capabilities__contains=[AIModelCapability.TEXT_GENERATION, AIModelCapability.STRUCTURED_OUTPUT]).order_by("pk")[:101])
        from django.db.models import Q
        accounts = list(AIProviderAccount.objects.filter(state=AIProviderAccount.State.ACTIVE, provider__enabled=True).filter(
            Q(organization=project.organization) | Q(organization__isnull=True)).order_by("pk")[:201])
        jobs = list(JobRun.objects.filter(project=project, handler="research_topic").order_by("-created_at", "-pk")[:21])
        config = getattr(project, "configuration", None)
        return _result({"project_id": project.pk,
            "models": [{"id": model.pk, "provider_id": model.provider_id, "name": model.name,
                "access_tier": model.access_tier, "privacy_policy_url": model.privacy_policy_url,
                "max_output_tokens": model.max_output_tokens, "price_known": model.input_price_usd_per_million is not None
                and model.output_price_usd_per_million is not None and model.pricing_verified_at is not None
                and bool(model.pricing_source)} for model in models[:100]],
            "accounts": [{"id": account.pk, "provider_id": account.provider_id, "label": account.label,
                "source": "platform" if account.organization_id is None else "organization"} for account in accounts[:200]],
            "languages": config.target_languages if config else [], "source_limit": 5,
            "source_scope": "explicit_configured_https_origins_only", "provider_search": "not_available_in_this_handler",
            "jobs": [{"id": job.pk, "project_id": project.pk, "status": job.status,
                      "topic": job.input_snapshot["topic"], "updated_at": job.updated_at.isoformat()} for job in jobs[:20]],
            "has_more": len(models) > 100 or len(accounts) > 200 or len(jobs) > 20})
    if not ratelimit.consume(request, action="ai_text_request", user=request.user):
        return _result({"message": "Too many research requests."}, HTTPStatus.TOO_MANY_REQUESTS)
    try:
        data = _payload(request, {"topic", "mapping_id", "language", "source_urls", "model_id", "account_id",
                                  "max_output_tokens", "max_cost_usd", "allow_free", "idempotency_key"}, optional={"topic_review_id"})
        key = data.pop("idempotency_key")
        job = queue_research(project=project, actor=request.user, data=data, idempotency_key=key)
    except PermissionDenied:
        return _result({"message": "Research selection unavailable for this project."}, HTTPStatus.FORBIDDEN)
    except UsageLimitError as error:
        return _result({"message": "Research allowance unavailable.", "code": error.category}, HTTPStatus.TOO_MANY_REQUESTS)
    except (ValidationError, ValueError, TypeError, UnicodeError, IntegrityError):
        return _result({"message": "Choose a current mapping, approved URLs and eligible model with a bounded budget."},
                       HTTPStatus.BAD_REQUEST)
    return _result({"project_id": project.pk, "job": _job(job)}, HTTPStatus.ACCEPTED)


@require_http_methods(["GET", "POST"])
def project_research_job(request, organization_id, project_id, job_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _result({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _result({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.VIEW_PROJECT)
    except PermissionDenied:
        return _result({"message": "Project access unavailable."}, HTTPStatus.FORBIDDEN)
    job = JobRun.objects.filter(pk=job_id, project=project, handler="research_topic").first()
    if job is None:
        return _result({"message": "Research job unavailable."}, HTTPStatus.NOT_FOUND)
    if request.method == "POST":
        try:
            _payload(request, set())
            job, _changed, _requested = cancel_job(job=job, actor=request.user)
        except PermissionDenied:
            return _result({"message": "Research cancellation unavailable."}, HTTPStatus.FORBIDDEN)
        except (ValidationError, ValueError, TypeError, UnicodeError):
            return _result({"message": "Research cancellation unavailable."}, HTTPStatus.CONFLICT)
    return _result({"project_id": project.pk, "job": _job(job)})
