"""Fixed private original-pair synthesis commands; previews never resolve keys or call providers."""
from functools import partial
from http import HTTPStatus
import re

from allauth.account import app_settings as account_settings
from allauth.core.internal import ratelimit
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.utils import timezone

from integrations.google_tokens import GoogleTokenError
from providers.models import AIModel, AIProvider, AIProviderAccount
from tenancy.models import Organization, Project
from . import competitor_synthesis_job as synthesis, competitor_headings_synthesis_job as heading_synthesis
from . import competitor_topics_job as topic_synthesis
from .competitor_topics_comparison import compare_competitor_topic_labels
from .authority_link_collection_api import _query_ids
from .competitor_api import _current, _digest
from .findings_api import _project
from .first_audit_api import _response
from .models import AIUsageRecord, JobCancellation, JobRun, JobStatus
from .passive_header_api import KEY, _payload, _status as _base_status
from .services import cancel_job
from .staff_ai_usage_investigation import FIELDS as AI_FIELDS, _observation
from .usage import UsageLimitError, require_billable_access


INPUT_FIELDS = {"previous_job_id", "current_job_id", "ai_processing_permission", "model_id", "account_id",
    "max_output_tokens", "max_cost_usd", "allow_free"}
TOPIC_INPUT_FIELDS = (INPUT_FIELDS - {"previous_job_id", "current_job_id"}) | {"job_id"}


@sensitive_variables()
def project_competitor_topic_comparison(request, organization_id, project_id):
    if request.method != "GET":
        response = _response({"message": "Read two explicitly saved topic-hypothesis jobs."}, HTTPStatus.METHOD_NOT_ALLOWED)
        response["Allow"] = "GET"
        return response
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    if request.body or not all(type(value) is int and 1 <= value < 2**53 for value in (organization_id, project_id)):
        return _response({"message": "Choose exact saved topic-hypothesis jobs."}, HTTPStatus.BAD_REQUEST)
    project = _project(request, organization_id, project_id)
    if project is None: return _response({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    if ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True,
        action="competitor_heading_topics_read", user=request.user) is None:
        return _response({"message": "Too many private topic reads."}, HTTPStatus.TOO_MANY_REQUESTS)
    try:
        pair = _query_ids(request, {"first_job_id", "second_job_id"})
        if len(set(pair.values())) != 2: raise ValidationError("Choose distinct saved topic-hypothesis jobs.")
    except ValidationError:
        return _response({"message": "Choose two exact distinct saved topic-hypothesis job IDs."}, HTTPStatus.BAD_REQUEST)
    try:
        _current(project, request.user)
        jobs = {job.pk: job for job in JobRun.objects.select_related("project", "actor").filter(
            pk__in=pair.values(), project_id=project_id, organization_id=organization_id,
            handler=topic_synthesis.HANDLER, status=JobStatus.SUCCEEDED)}
        if len(jobs) != 2: raise PermissionDenied
        ids = (pair["first_job_id"], pair["second_job_id"])
        callers = {key: synthesis._reader_source(jobs[key], project, request.user) for key in ids}
        original = {key: _metadata(jobs[key], family=topic_synthesis) for key in ids}
        sources = tuple(jobs[key].input_snapshot["job_id"] for key in ids)
        comparison = compare_competitor_topic_labels(project=project, actor=request.user, **pair)
        response = _response({"organization_id": organization_id, "project_id": project_id, "comparison": comparison})
        if any(_metadata(jobs[key], family=topic_synthesis) != original[key] for key in ids): raise PermissionDenied
        fresh = {key: JobRun.objects.select_related("project", "actor").get(pk=key, handler=topic_synthesis.HANDLER) for key in ids}
        if {key: synthesis._reader_source(fresh[key], project, request.user) for key in ids} != callers: raise PermissionDenied
        if any(_metadata(fresh[key], family=topic_synthesis) != original[key] for key in ids): raise PermissionDenied
        # Final metadata reads can invalidate the original authority checked above.
        fresh = {key: JobRun.objects.select_related("project", "actor").get(pk=key, handler=topic_synthesis.HANDLER) for key in ids}
        if {key: synthesis._reader_source(fresh[key], project, request.user) for key in ids} != callers: raise PermissionDenied
        if any(_metadata(fresh[key], family=topic_synthesis) != original[key] for key in ids): raise PermissionDenied
        if JobCancellation.objects.filter(job_id__in=(*ids, *sources)).exists(): raise PermissionDenied
        _current(project, request.user)
        require_billable_access(organization=project.organization)
        return response
    except (UsageLimitError, PermissionDenied, ObjectDoesNotExist):
        return _response({"message": "Current original topic sources, models and authority are required."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, GoogleTokenError, UnicodeError, ValueError, TypeError, RecursionError):
        return _response({"message": "Exact private topic-hypothesis pair unavailable."}, HTTPStatus.CONFLICT)


def _selection(project, actor, data, *, family=synthesis):
    data = family.validate_input(data)
    return {"input": data, "configuration": family.selection_snapshot(project, actor, data)[2]}


def _status(job):
    result = _base_status(job)
    category = job.error_category or job.dispatch_error
    if type(category) is str and category in synthesis.ERRORS: result["error_category"] = category
    return result


def _metadata(job, *, family=synthesis):
    data = family.validate_input(job.input_snapshot)
    ids = (data["job_id"],) if family is topic_synthesis else (data["previous_job_id"], data["current_job_id"])
    return {"own": synthesis._read_metadata(job.pk),
        "cancellation": JobCancellation.objects.filter(job=job).values().first(),
        ("source" if family is topic_synthesis else "pair"): synthesis.synthesis._pins(ids),
        "models": {"model": AIModel.objects.filter(pk=data["model_id"]).values().first(),
            "provider": AIProvider.objects.filter(pk=job.config_snapshot.get("provider_id")).values().first(),
            "account": AIProviderAccount.objects.filter(pk=data["account_id"]).values().first()}}


def _detail(job, project, actor, *, family=synthesis):
    family.validate_job(job)
    selection = {"input": job.input_snapshot, "configuration": job.config_snapshot}
    ai = AIUsageRecord.objects.filter(job=job).values(*AI_FIELDS).first()
    # Reuse the checked pure original-date/nullable-token/currency projection;
    # it grants no staff or provider authority and returns no provider request identifiers.
    usage = _observation(ai, synthesis.collection._row_pin(job), timezone.now())
    return {"job": _status(job), "selection": selection, "selection_digest": _digest(selection), "usage": usage,
        "evidence": family.read_result(project=project, actor=actor, job_id=job.pk)
            if job.status == JobStatus.SUCCEEDED else None}


@sensitive_post_parameters()
@sensitive_variables()
def project_competitor_syntheses(request, organization_id, project_id, job_id=None, selection=False):
    return _project_competitor_syntheses(request, organization_id, project_id, job_id=job_id, selection=selection)


@sensitive_post_parameters()
@sensitive_variables()
def project_competitor_heading_syntheses(request, organization_id, project_id, job_id=None, selection=False):
    return _project_competitor_syntheses(request, organization_id, project_id, job_id=job_id, selection=selection, headings=True)


@sensitive_post_parameters()
@sensitive_variables()
def project_competitor_heading_topics(request, organization_id, project_id, job_id=None, selection=False):
    return _project_competitor_syntheses(request, organization_id, project_id, job_id=job_id, selection=selection, topics=True)


@sensitive_variables()
def _project_competitor_syntheses(request, organization_id, project_id, job_id=None, selection=False, *, headings=False, topics=False):
    family = topic_synthesis if topics else heading_synthesis if headings else synthesis
    input_fields = TOPIC_INPUT_FIELDS if topics else INPUT_FIELDS
    # Keep the original Root callback signatures and patch/read boundaries intact.
    choose = partial(_selection, family=family) if headings or topics else _selection
    metadata = partial(_metadata, family=family) if headings or topics else _metadata
    detail_reader = partial(_detail, family=family) if headings or topics else _detail
    queue = family.queue_competitor_topics if topics else family.queue_competitor_headings_synthesis if headings else family.queue_competitor_synthesis
    methods = {"POST"} if selection else {"GET", "POST"}
    if request.method not in methods:
        response = _response({"message": "Use an explicit private synthesis command."}, HTTPStatus.METHOD_NOT_ALLOWED)
        response["Allow"] = ", ".join(sorted(methods))
        return response
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    if (not all(type(value) is int and 1 <= value < 2**53 for value in (organization_id, project_id))
        or job_id is not None and (type(job_id) is not int or not 1 <= job_id < 2**53)
        or request.method == "POST" and request.GET or request.method == "GET" and request.body):
        return _response({"message": "Choose exact original synthesis fields."}, HTTPStatus.BAD_REQUEST)
    project = _project(request, organization_id, project_id)
    if project is None: return _response({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    action = ("competitor_heading_topics_" if topics else "competitor_heading_synthesis_" if headings else "competitor_synthesis_") + (("selection" if selection else "cancel" if job_id is not None else "request")
        if request.method == "POST" else "read")
    if ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True, action=action, user=request.user) is None:
        return _response({"message": "Too many private synthesis commands."}, HTTPStatus.TOO_MANY_REQUESTS)
    rows = JobRun.objects.filter(organization_id=organization_id, project_id=project_id, handler=family.HANDLER)
    scope = {"organization_id": organization_id, "project_id": project_id}
    try:
        _current(project, request.user)
        if request.method == "POST":
            with transaction.atomic():
                org = Organization.objects.select_for_update().get(pk=organization_id)
                project = Project.objects.select_for_update().get(pk=project_id, organization=org)
                if selection:
                    data = _payload(request, input_fields)
                    original = choose(project, request.user, data)
                    response = _response({**scope, "selection": original, "selection_digest": _digest(original), "estimate_units": 1})
                    if choose(project, request.user, data) != original: raise PermissionDenied
                elif job_id is not None:
                    _payload(request, set())
                    job = rows.select_related("project", "actor").filter(pk=job_id).first()
                    if job is None: raise PermissionDenied
                    job, _changed, _requested = cancel_job(job=job, actor=request.user)
                    saved = metadata(job)
                    response = _response({**scope, "job": _status(job)}, HTTPStatus.ACCEPTED)
                    if metadata(job) != saved: raise PermissionDenied
                else:
                    data = _payload(request, input_fields | {"idempotency_key", "selection_digest"})
                    key, expected = data.pop("idempotency_key"), data.pop("selection_digest")
                    if (type(key) is not str or not re.fullmatch(KEY, key) or type(expected) is not str
                        or not re.fullmatch(r"[a-f0-9]{64}", expected)): raise ValidationError("Choose the exact preview and request key.")
                    original = choose(project, request.user, data)
                    if _digest(original) != expected: raise PermissionDenied
                    job = queue(project=project, actor=request.user, data=data, idempotency_key=key)
                    saved = metadata(job)
                    response = _response({**scope, "job": _status(job)}, HTTPStatus.ACCEPTED)
                    if metadata(job) != saved: raise PermissionDenied
                    if choose(project, request.user, data) != original: raise PermissionDenied
                    family.validate_job(rows.select_related("project", "actor").get(pk=job.pk), current=True)
                    if JobCancellation.objects.filter(job=job).values().first() != saved["cancellation"]: raise PermissionDenied
                _current(project, request.user)
                if selection or job_id is None: require_billable_access(organization=org)
                return response
        if job_id is not None:
            if request.GET: raise ValidationError("No extra exact-job query is supported.")
            job = rows.select_related("project", "actor").filter(pk=job_id).first()
            if job is None: raise PermissionDenied
            original = metadata(job)
            caller = synthesis._reader_source(job, project, request.user) if job.status == JobStatus.SUCCEEDED else None
            detail = detail_reader(job, project, request.user)
            response = _response({**scope, **detail})
            if metadata(job) != original: raise PermissionDenied
            fresh = rows.select_related("project", "actor").get(pk=job.pk)
            if caller is not None and synthesis._reader_source(fresh, project, request.user) != caller: raise PermissionDenied
            if metadata(fresh) != original: raise PermissionDenied
            if detail["evidence"]: require_billable_access(organization=project.organization)
        else:
            if set(request.GET) - {"idempotency_key"} or any(len(values) != 1 for _, values in request.GET.lists()):
                raise ValidationError("Choose only one original request key.")
            key = request.GET.get("idempotency_key")
            if key is not None:
                if not re.fullmatch(KEY, key): raise ValidationError("Choose an original request key.")
                rows = rows.filter(idempotency_key=key, actor=request.user)
            rows = rows.order_by("-pk")
            original = list(rows.values()[:21])
            cancellations = JobCancellation.objects.filter(job_id__in=[row["id"] for row in original]).order_by("pk")
            original_cancellations = list(cancellations.values())
            jobs = list(rows[:21])
            response = _response({**scope, "jobs": [_status(job) for job in jobs[:20]], "has_more": len(jobs) > 20, "lookup": key})
            if list(rows.values()[:21]) != original or list(cancellations.values()) != original_cancellations: raise PermissionDenied
        _current(project, request.user)
        return response
    except (UsageLimitError, PermissionDenied, ObjectDoesNotExist):
        return _response({"message": "Current exact synthesis source, model and authority are required."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, GoogleTokenError, UnicodeError, ValueError, TypeError, IntegrityError, RecursionError):
        return _response({"message": "Refresh the exact preview or reconcile the original synthesis request."}, HTTPStatus.CONFLICT)
