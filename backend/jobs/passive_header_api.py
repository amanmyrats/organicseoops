"""Fixed separate passive commands; preview/readback never issue a site request."""
from contextlib import nullcontext
from hashlib import sha256
from http import HTTPStatus
import json
import re

from allauth.account import app_settings as account_settings
from allauth.core.internal import ratelimit
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables

from integrations.google_tokens import GoogleTokenError, _reject_constant, _unique_object
from tenancy.services import Action, require_project_action
from tenancy.models import Organization, Project
from .findings_api import _project
from .first_audit_api import _response
from .models import JobCancellation, JobRun, JobStatus
from . import passive_header_collection as collection
from . import passive_header_findings as findings
from . import passive_resource_findings as resource_findings
from . import passive_tls_findings as tls_findings
from . import passive_redirect_findings as redirect_findings
from . import passive_header_candidate_source as candidate_source
from .passive_header_candidate_source import current_header_candidates
from .passive_resource_candidate_source import current_resource_candidates
from .passive_tls_candidate_source import current_tls_candidates
from .passive_redirect_candidate_source import current_redirect_candidates
from .passive_scheme_comparison import compare_http_https_observations
from .services import cancel_job
from .usage import UsageLimitError, require_billable_access


KEY = r"[A-Za-z0-9][A-Za-z0-9._-]{7,63}"
INPUT_FIELDS = {"url", "observations", "collection_permission"}


def _payload(request, fields, *, max_bytes=2048):
    if request.content_type != "application/json" or len(request.body) > max_bytes:
        raise ValidationError("Choose bounded application/json command fields.")
    data = json.loads(request.body, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    if type(data) is not dict or set(data) != fields: raise ValidationError("Choose exact command fields.")
    return data


def _digest(selection):
    return sha256(collection._encode(selection)).hexdigest()


def _status(job):
    if job.status not in JobStatus.values: raise ValidationError
    collection._date(job.created_at.isoformat()); collection._date(job.updated_at.isoformat())
    if job.created_at > job.updated_at: raise ValidationError
    errors = collection.ERRORS | {"cancel_requested", "source_scope_changed", "usage_unreserved", "broker_unavailable",
        "internal_capacity", "trial_unavailable", "trial_units_exhausted", "paid_unavailable", "billing_review_hold",
        "paid_period_changed", "paid_units_exhausted", "actor_revoked"}
    category = job.error_category or job.dispatch_error
    return {"id": job.pk, "status": job.status, "created_at": job.created_at.isoformat(), "updated_at": job.updated_at.isoformat(),
        "cancel_requested": JobCancellation.objects.filter(job=job).exists(), "estimate_units": 1,
        "error_category": category if category in errors else "unclassified_failure" if category else ""}


def _current(project, actor):
    require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)


def _metadata(job_id):
    return {"source": collection._read_metadata(job_id),
            "cancellation": JobCancellation.objects.filter(job_id=job_id).values().first()}


@sensitive_variables()
def project_passive_scheme_comparison(request, organization_id, project_id):
    if request.method != "GET":
        response = _response({"message": "Read an explicit independent HTTP/HTTPS original pair."}, HTTPStatus.METHOD_NOT_ALLOWED)
        response["Allow"] = "GET"
        return response
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    if request.body or not all(type(value) is int and 1 <= value < 2**53 for value in (organization_id, project_id)):
        return _response({"message": "Choose exact original HTTP and HTTPS jobs."}, HTTPStatus.BAD_REQUEST)
    project = _project(request, organization_id, project_id)
    if project is None: return _response({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    if ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True,
        action="passive_http_redirect_read", user=request.user) is None:
        return _response({"message": "Too many HTTP Location reads."}, HTTPStatus.TOO_MANY_REQUESTS)
    try:
        from .authority_link_collection_api import _query_ids
        pair = _query_ids(request, {"http_job_id", "https_job_id"})
        if pair["http_job_id"] == pair["https_job_id"]: raise ValidationError("Choose distinct original HTTP and HTTPS jobs.")
    except ValidationError:
        return _response({"message": "Choose two exact distinct original HTTP and HTTPS job IDs."}, HTTPStatus.BAD_REQUEST)
    try:
        _current(project, request.user)
        rows = dict(JobRun.objects.filter(pk__in=pair.values(), project_id=project_id,
            organization_id=organization_id, status=JobStatus.SUCCEEDED).values_list("pk", "handler"))
        if (rows.get(pair["http_job_id"]) != "collect_passive_http_redirects"
            or rows.get(pair["https_job_id"]) != "collect_passive_redirects"): raise PermissionDenied
        original = {key: _metadata(key) for key in pair.values()}
        comparison = compare_http_https_observations(project=project, actor=request.user, **pair)
        response = _response({"organization_id": organization_id, "project_id": project_id, "comparison": comparison})
        if any(_metadata(key) != original[key] for key in pair.values()): raise PermissionDenied
        if compare_http_https_observations(project=project, actor=request.user, **pair) != comparison: raise PermissionDenied
        _current(project, request.user)
        require_billable_access(organization=project.organization)
        return response
    except (UsageLimitError, PermissionDenied, ObjectDoesNotExist):
        return _response({"message": "Current independent original pair and authority are required."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, GoogleTokenError, UnicodeError, ValueError, TypeError, KeyError, RecursionError):
        return _response({"message": "Exact private original HTTP/HTTPS pair unavailable."}, HTTPStatus.CONFLICT)


@sensitive_post_parameters()
@sensitive_variables()
def project_header_findings(request, organization_id, project_id, job_id):
    return _project_findings(request, organization_id, project_id, job_id, family="header")


@sensitive_post_parameters()
@sensitive_variables()
def project_resource_findings(request, organization_id, project_id, job_id):
    return _project_findings(request, organization_id, project_id, job_id, family="resource")


@sensitive_post_parameters()
@sensitive_variables()
def project_tls_findings(request, organization_id, project_id, job_id):
    return _project_findings(request, organization_id, project_id, job_id, family="tls")


@sensitive_post_parameters()
@sensitive_variables()
def project_redirect_findings(request, organization_id, project_id, job_id):
    return _project_findings(request, organization_id, project_id, job_id, family="redirect")


@sensitive_post_parameters()
@sensitive_variables()
def project_redirect_chain_findings(request, organization_id, project_id, job_id):
    return _project_findings(request, organization_id, project_id, job_id, family="redirect_chain")


@sensitive_post_parameters()
@sensitive_variables()
def _project_findings(request, organization_id, project_id, job_id, *, family):
    # Only fixed server entrypoints choose the source and command services.
    if family == "header":
        service, candidates = findings, current_header_candidates
        record, read = findings.record_header_findings, findings.current_header_findings
    elif family == "resource":
        service, candidates = resource_findings, current_resource_candidates
        record, read = resource_findings.record_resource_findings, resource_findings.current_resource_findings
    elif family == "tls":
        service, candidates = tls_findings, current_tls_candidates
        record, read = tls_findings.record_tls_findings, tls_findings.current_tls_findings
    elif family == "redirect":
        service, candidates = redirect_findings, current_redirect_candidates
        record, read = redirect_findings.record_redirect_findings, redirect_findings.current_redirect_findings
    elif family == "redirect_chain":
        from . import passive_redirect_chain_findings as service
        from .passive_redirect_chain_candidate_source import current_redirect_chain_candidates
        candidates = current_redirect_chain_candidates
        record, read = service.record_redirect_chain_findings, service.current_redirect_chain_findings
    else:
        raise ValidationError
    label = family
    if request.method not in {"GET", "POST"}:
        response = _response({"message": f"Use an explicit {label}-finding GET or POST."}, HTTPStatus.METHOD_NOT_ALLOWED)
        response["Allow"] = "GET, POST"
        return response
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    if (not all(type(value) is int and 1 <= value < 2**53 for value in (organization_id, project_id, job_id))
        or request.GET or request.method == "GET" and request.body):
        return _response({"message": f"Choose one exact original {label} job."}, HTTPStatus.BAD_REQUEST)
    project = _project(request, organization_id, project_id)
    if project is None: return _response({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    action = f"passive_{label}_findings_" + ("write" if request.method == "POST" else "read")
    if ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True,
        action=action, user=request.user) is None:
        return _response({"message": f"Too many {label}-finding commands."}, HTTPStatus.TOO_MANY_REQUESTS)
    try:
        _current(project, request.user)
        expected = None
        if request.method == "POST":
            expected = _payload(request, {"candidate_digest"})["candidate_digest"]
            if type(expected) is not str or not re.fullmatch(r"[a-f0-9]{64}", expected): raise ValidationError
        with transaction.atomic() if request.method == "POST" else nullcontext():
            if request.method == "POST":
                organization = Organization.objects.select_for_update().get(pk=organization_id)
                project = Project.objects.select_for_update().get(pk=project_id, organization=organization)
            original = candidate_source._metadata(job_id, project=project, actor=request.user, handler=service.source.collection.HANDLER)
            report = candidates(project=project, actor=request.user, job_id=job_id)
            candidate_digest = _digest(report)
            if expected is not None:
                if candidate_digest != expected: raise PermissionDenied
                record(project=project, actor=request.user, job_id=job_id)
            rows = service._rows(project, job_id)
            finding_set = read(project=project, actor=request.user, job_id=job_id)
            response = _response({"organization_id": organization_id, "project_id": project_id,
                "candidates": report, "candidate_digest": candidate_digest, "finding_set": finding_set})
            service._final_source(project, request.user, job_id, original, report, rows)
            _current(project, request.user)
            return response
    except (UsageLimitError, PermissionDenied, ObjectDoesNotExist):
        return _response({"message": f"Current exact {label} source, findings and allowance are required."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, GoogleTokenError, UnicodeError, ValueError, TypeError, IntegrityError, RecursionError):
        return _response({"message": f"Original minimized {label} findings are unavailable. Inspect the exact source again."}, HTTPStatus.CONFLICT)


@sensitive_variables()
def project_header_candidates(request, organization_id, project_id, job_id):
    return _project_candidates(request, organization_id, project_id, job_id, family="header")


@sensitive_variables()
def project_resource_candidates(request, organization_id, project_id, job_id):
    return _project_candidates(request, organization_id, project_id, job_id, family="resource")


@sensitive_variables()
def project_tls_candidates(request, organization_id, project_id, job_id):
    return _project_candidates(request, organization_id, project_id, job_id, family="tls")


@sensitive_variables()
def project_redirect_candidates(request, organization_id, project_id, job_id):
    return _project_candidates(request, organization_id, project_id, job_id, family="redirect")


@sensitive_variables()
def project_redirect_chain_candidates(request, organization_id, project_id, job_id):
    return _project_candidates(request, organization_id, project_id, job_id, family="redirect_chain")


@sensitive_variables()
def _project_candidates(request, organization_id, project_id, job_id, *, family):
    # Only these fixed server entrypoints select a family, never request input.
    if family == "header":
        handler, read = collection.HANDLER, current_header_candidates
    elif family == "resource":
        handler, read = "collect_passive_resources", current_resource_candidates
    elif family == "tls":
        handler, read = "collect_passive_tls", current_tls_candidates
    elif family == "redirect":
        handler, read = "collect_passive_redirects", current_redirect_candidates
    elif family == "redirect_chain":
        from .passive_redirect_chain_candidate_source import current_redirect_chain_candidates
        handler, read = "collect_passive_redirect_chain", current_redirect_chain_candidates
    else:
        raise ValidationError
    action, label = f"passive_{family}_read", family
    if request.method != "GET":
        response = _response({"message": f"Use an explicit {label}-candidate GET."}, HTTPStatus.METHOD_NOT_ALLOWED)
        response["Allow"] = "GET"
        return response
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    if (not all(type(value) is int and 1 <= value < 2**53 for value in (organization_id, project_id, job_id))
        or request.GET or request.body):
        return _response({"message": f"Choose one exact original {label} job."}, HTTPStatus.BAD_REQUEST)
    project = _project(request, organization_id, project_id)
    if project is None: return _response({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    if ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True,
        action=action, user=request.user) is None:
        return _response({"message": f"Too many {label} reads."}, HTTPStatus.TOO_MANY_REQUESTS)
    try:
        _current(project, request.user)
        original = candidate_source._metadata(job_id, project=project, actor=request.user, handler=handler)
        report = read(project=project, actor=request.user, job_id=job_id)
        response = _response({"organization_id": organization_id, "project_id": project_id, "candidates": report})
        current = JobRun.objects.select_related("project", "actor").filter(pk=job_id, organization_id=organization_id,
            project_id=project_id, handler=handler, status=JobStatus.SUCCEEDED).first()
        if current is None: raise PermissionDenied
        collection._read_source(current, project, request.user)
        if candidate_source._metadata(job_id, project=project, actor=request.user, handler=handler) != original: raise PermissionDenied
        if family == "redirect_chain" and read(project=project, actor=request.user, job_id=job_id) != report: raise PermissionDenied
        _current(project, request.user)
        return response
    except (UsageLimitError, PermissionDenied):
        return _response({"message": f"Current exact {label} source and allowance are required."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, GoogleTokenError, UnicodeError, ValueError, TypeError, RecursionError):
        return _response({"message": f"Original minimized {label} evidence is unavailable."}, HTTPStatus.CONFLICT)


@sensitive_post_parameters()
@sensitive_variables()
def project_passive_headers(request, organization_id, project_id, job_id=None, selection=False, handler=collection.HANDLER):
    # Only fixed server routes select this contract, never client input/query fields.
    if handler == collection.HANDLER:
        source, fields, queue, read = (collection, INPUT_FIELDS,
            collection.queue_passive_header_collection, collection.read_passive_header_observation)
        prefix, label = "passive_header", "passive-header"
    elif handler == "collect_passive_tls":
        from . import passive_tls_collection as source
        fields, queue, read = ({"origin", "observations", "collection_permission"},
            source.queue_passive_tls_collection, source.read_passive_tls_observation)
        prefix, label = "passive_tls", "passive-TLS"
    elif handler == "collect_passive_resources":
        from . import passive_resource_collection as source
        fields, queue, read = (INPUT_FIELDS,
            source.queue_passive_resource_collection, source.read_passive_resource_observation)
        prefix, label = "passive_resource", "passive-resource"
    elif handler == "collect_passive_redirects":
        from . import passive_redirect_collection as source
        fields, queue, read = (INPUT_FIELDS,
            source.queue_passive_redirect_collection, source.read_passive_redirect_observation)
        prefix, label = "passive_redirect", "passive-Location"
    elif handler == "collect_passive_http_redirects":
        from . import passive_http_redirect_collection as source
        fields, queue, read = (INPUT_FIELDS,
            source.queue_passive_http_redirect_collection, source.read_passive_http_redirect_observation)
        prefix, label = "passive_http_redirect", "plaintext-HTTP-Location"
    elif handler == "collect_passive_redirect_chain":
        from . import passive_redirect_chain_collection as source
        fields, queue, read = (INPUT_FIELDS | {"target_urls"},
            source.queue_passive_redirect_chain_collection, source.read_passive_redirect_chain_observation)
        prefix, label = "passive_redirect_chain", "exact-redirect-chain"
    else:
        raise ValidationError("Choose a fixed passive route.")
    max_command_bytes = 8192 if handler == "collect_passive_redirect_chain" else 2048
    methods = {"POST"} if selection else {"GET", "POST"}
    if request.method not in methods:
        response = _response({"message": f"Use an explicit supported {label} command."}, HTTPStatus.METHOD_NOT_ALLOWED)
        response["Allow"] = ", ".join(sorted(methods))
        return response
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    if (not all(type(value) is int and 1 <= value < 2**53 for value in (organization_id, project_id))
        or job_id is not None and not 1 <= job_id < 2**53
        or request.method == "POST" and request.GET or request.method == "GET" and request.body):
        return _response({"message": f"Choose exact {label} fields."}, HTTPStatus.BAD_REQUEST)
    project = _project(request, organization_id, project_id)
    if project is None: return _response({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    action = prefix + (("_selection" if selection else "_cancel" if job_id is not None
              else "_request") if request.method == "POST" else "_read")
    if ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True, action=action, user=request.user) is None:
        return _response({"message": f"Too many {label} commands."}, HTTPStatus.TOO_MANY_REQUESTS)
    rows = JobRun.objects.filter(organization_id=organization_id, project_id=project_id, handler=handler)
    try:
        _current(project, request.user)
        if request.method == "POST":
            with transaction.atomic():
                if selection:
                    data = _payload(request, fields, max_bytes=max_command_bytes)
                    require_billable_access(organization=project.organization)
                    original = source.selection_snapshot(project, request.user, data)
                    response = _response({"organization_id": organization_id, "project_id": project_id,
                        "selection": original, "selection_digest": _digest(original), "estimate_units": 1})
                    if source.selection_snapshot(project, request.user, data) != original: raise PermissionDenied
                    require_billable_access(organization=project.organization)
                elif job_id is not None:
                    _payload(request, set())
                    job = rows.select_related("project", "actor").filter(pk=job_id).first()
                    if job is None: raise PermissionDenied
                    job, _changed, _requested = cancel_job(job=job, actor=request.user)
                    saved = _metadata(job.pk)
                    response = _response({"organization_id": organization_id, "project_id": project_id, "job": _status(job)}, HTTPStatus.ACCEPTED)
                    if _metadata(job.pk) != saved: raise PermissionDenied
                else:
                    data = _payload(request, fields | {"idempotency_key", "selection_digest"}, max_bytes=max_command_bytes)
                    key, expected = data.pop("idempotency_key"), data.pop("selection_digest")
                    if (type(key) is not str or not re.fullmatch(KEY, key) or type(expected) is not str
                        or not re.fullmatch(r"[a-f0-9]{64}", expected)): raise ValidationError
                    original = source.selection_snapshot(project, request.user, data)
                    if _digest(original) != expected: raise PermissionDenied
                    job = queue(project=project, actor=request.user, data=data, idempotency_key=key)
                    saved = _metadata(job.pk)
                    response = _response({"organization_id": organization_id, "project_id": project_id, "job": _status(job)}, HTTPStatus.ACCEPTED)
                    if source.selection_snapshot(project, request.user, data) != original: raise PermissionDenied
                    source.validate_job(job, current=True)
                    require_billable_access(organization=project.organization)
                    if _metadata(job.pk) != saved: raise PermissionDenied
                _current(project, request.user)
                return response
        if job_id is not None:
            if request.GET: raise ValidationError
            job = rows.select_related("project", "actor").filter(pk=job_id).first()
            if job is None: raise PermissionDenied
            original = _metadata(job.pk)
            evidence = read(project=project, actor=request.user,
                job_id=job.pk) if job.status == JobStatus.SUCCEEDED else None
            if evidence and handler == "collect_passive_redirect_chain":
                evidence = {**evidence, "binding": job.config_snapshot["binding"]}
            response = _response({"organization_id": organization_id, "project_id": project_id, "job": _status(job), "evidence": evidence})
            if evidence:
                fresh = rows.select_related("project", "actor").get(pk=job.pk)
                collection._read_source(fresh, project, request.user)
                if handler == "collect_passive_redirect_chain":
                    reread = read(project=project, actor=request.user, job_id=job.pk)
                    if {**reread, "binding": fresh.config_snapshot["binding"]} != evidence: raise PermissionDenied
            if _metadata(job.pk) != original: raise PermissionDenied
        else:
            if set(request.GET) - {"idempotency_key"} or any(len(values) != 1 for _, values in request.GET.lists()): raise ValidationError
            key = request.GET.get("idempotency_key")
            if key is not None:
                if not re.fullmatch(KEY, key): raise ValidationError
                rows = rows.filter(idempotency_key=key, actor=request.user)
            rows = rows.order_by("-pk")
            original = list(rows.values()[:21])
            original_cancellations = list(JobCancellation.objects.filter(job_id__in=[row["id"] for row in original]).order_by("pk").values())
            jobs = list(rows[:21])
            response = _response({"organization_id": organization_id, "project_id": project_id,
                "jobs": [_status(job) for job in jobs[:20]], "has_more": len(jobs) > 20, "lookup": key})
            if list(rows.values()[:21]) != original: raise PermissionDenied
            if list(JobCancellation.objects.filter(job_id__in=[row["id"] for row in original]).order_by("pk").values()) != original_cancellations:
                raise PermissionDenied
        _current(project, request.user)
        if job_id is not None and evidence:
            require_billable_access(organization=project.organization)
        return response
    except UsageLimitError:
        return _response({"message": "Current collection allowance is unavailable."}, HTTPStatus.FORBIDDEN)
    except PermissionDenied:
        return _response({"message": f"Current exact {label} source and authority are required."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, GoogleTokenError, UnicodeError, ValueError, TypeError, IntegrityError, RecursionError):
        return _response({"message": "Refresh the exact selection or reconcile the original request."}, HTTPStatus.CONFLICT)
