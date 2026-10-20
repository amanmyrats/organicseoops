"""Small first-audit entry over actual project source jobs, never demo findings."""
import json
from http import HTTPStatus

from allauth.core import ratelimit
from allauth.account import app_settings as account_settings
from allauth.core.internal import ratelimit as history_ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.http import JsonResponse
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods

from integrations.models import ImportRun
from integrations.google_tokens import _reject_constant, _unique_object
from tenancy.models import Project
from tenancy.services import Action, require_project_action
from .first_audit import queue_first_audit, retry_first_audit
from .first_audit_evidence import inspect_bounded_completion
from .first_audit_value import (ACK_METHOD, acknowledge_first_audit_value, first_audit_action_source,
                                first_value_acknowledgment_challenge, inspect_first_audit_value, inspect_first_audit_value_timing)
from .findings_api import project_findings
from .models import ActionReview, JobCancellation, JobRun, JobStatus
from .services import cancel_job
from .usage import UsageLimitError


def _response(data, status=HTTPStatus.OK):
    response = JsonResponse(data, status=status)
    response["Cache-Control"] = "private, no-store"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


def _job(job):
    from .crawler import FIRST_AUDIT_ENTRYPOINT
    steps = list(job.steps.order_by("sequence")[:21])
    return {"id": job.pk, "status": job.status, "error_category": job.error_category or job.dispatch_error,
            "handler": job.handler, "attempted_units": job.usage.actual_units if hasattr(job, "usage")
            and job.usage.state == "settled" else 0, "estimated_units": job.usage.reserved_units if hasattr(job, "usage") else 0,
            "cancel_requested": JobCancellation.objects.filter(job=job).exists(),
            "created_at": job.created_at.isoformat(), "updated_at": job.updated_at.isoformat(),
            "retry_supported": job.config_snapshot.get("first_audit_entrypoint") == FIRST_AUDIT_ENTRYPOINT,
            "steps": [{"sequence": step.sequence, "name": step.name, "status": step.status,
                       "progress_percent": step.progress_percent, "error_category": step.error_category}
                      for step in steps[:20]], "steps_has_more": len(steps) > 20}


def project_first_audit_completion(request, organization_id, project_id):
    if request.method != "GET":
        response = _response({"message": "Inspect saved history with GET."}, HTTPStatus.METHOD_NOT_ALLOWED)
        response["Allow"] = "GET"
        return response
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    if request.GET or request.body or not all(1 <= value < 2**53 for value in (organization_id, project_id)):
        return _response({"message": "Choose one exact project history without additional input."}, HTTPStatus.BAD_REQUEST)
    project = Project.objects.for_user(request.user).filter(pk=project_id, organization_id=organization_id).first()
    if project is None:
        return _response({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.VIEW_PROJECT)
        # The maintained public wrapper skips GET; these bounded private-body reads need their own limit.
        if history_ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True,
                action="first_audit_history_read", user=request.user) is None:
            return _response({"message": "Too many history inspections."}, HTTPStatus.TOO_MANY_REQUESTS)
        history = inspect_bounded_completion(project=project, actor=request.user)
    except PermissionDenied:
        return _response({"message": "Project history unavailable."}, HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _response({"message": "Saved bounded completion needs review."}, HTTPStatus.CONFLICT)
    return _response(history)


def project_first_audit_action_source(request, organization_id, project_id, action_id, revision):
    if request.method != "GET":
        response = _response({"message": "Inspect current source with GET."}, HTTPStatus.METHOD_NOT_ALLOWED)
        response["Allow"] = "GET"
        return response
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    if (request.GET or request.body or not 1 <= revision < 65535
        or not all(1 <= value < 2**53 for value in (organization_id, project_id))):
        return _response({"message": "Choose one exact action revision without additional input."}, HTTPStatus.BAD_REQUEST)
    project = Project.objects.for_user(request.user).filter(pk=project_id, organization_id=organization_id).first()
    if project is None:
        return _response({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.VIEW_PROJECT)
        if history_ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True,
                action="first_audit_history_read", user=request.user) is None:
            return _response({"message": "Too many source inspections."}, HTTPStatus.TOO_MANY_REQUESTS)
        selected = ActionReview.objects.filter(project=project, action_id=action_id, revision=revision).values(
            "pk", "opportunity__finding__source_diagnostics__crawl_run__job_id").first()
        if selected is None:
            return _response({"message": "Action revision unavailable."}, HTTPStatus.NOT_FOUND)
        job_id = selected["opportunity__finding__source_diagnostics__crawl_run__job_id"]
        if job_id is None:
            raise ValidationError("No supported linked audit source.")
        source = first_audit_action_source(project=project, actor=request.user, job_id=job_id,
                                          action_review_id=selected["pk"])
    except PermissionDenied:
        return _response({"message": "Current action source unavailable."}, HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _response({"message": "Current accepted audit source unavailable or needs review."}, HTTPStatus.CONFLICT)
    return _response({"organization_id": organization_id, "project_id": project_id,
        "action_id": str(action_id), "revision": revision, "source": source})


@sensitive_post_parameters()
@sensitive_variables()
def project_first_audit_usefulness(request, organization_id, project_id, action_id=None, revision=None, timing=False):
    methods = {"GET", "POST"} if action_id is not None else {"GET"}
    if request.method not in methods:
        response = _response({"message": "Use the explicit usefulness inspection or acknowledgment method."}, HTTPStatus.METHOD_NOT_ALLOWED)
        response["Allow"] = "GET, POST" if action_id is not None else "GET"
        return response
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    if (request.GET or request.method == "GET" and request.body
        or revision is not None and not 1 <= revision < 65535
        or not all(1 <= value < 2**53 for value in (organization_id, project_id))):
        return _response({"message": "Choose exact usefulness scope without additional input."}, HTTPStatus.BAD_REQUEST)
    project = Project.objects.for_user(request.user).filter(pk=project_id, organization_id=organization_id).first()
    if project is None:
        return _response({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user,
            action=Action.APPROVE if action_id is not None else Action.VIEW_PROJECT)
        if history_ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True,
            action="first_audit_usefulness_ack" if request.method == "POST" else "first_audit_history_read",
            user=request.user) is None:
            return _response({"message": "Too many usefulness requests."}, HTTPStatus.TOO_MANY_REQUESTS)
        if action_id is None:
            inspect = inspect_first_audit_value_timing if timing else inspect_first_audit_value
            return _response(inspect(project=project, actor=request.user))
        selected = ActionReview.objects.filter(project=project, action_id=action_id, revision=revision).values(
            "pk", "opportunity__finding__source_diagnostics__crawl_run__job_id").first()
        if selected is None:
            return _response({"message": "Action revision unavailable."}, HTTPStatus.NOT_FOUND)
        job_id = selected["opportunity__finding__source_diagnostics__crawl_run__job_id"]
        if job_id is None or project.organization.first_value_tracking != ACK_METHOD:
            raise ValidationError("Supported prospective usefulness source unavailable.")
        if request.method == "GET":
            result = {"organization_id": organization_id, "project_id": project_id,
                "action_id": str(action_id), "revision": revision,
                "challenge": first_value_acknowledgment_challenge(project=project, actor=request.user,
                    job_id=job_id, action_review_id=selected["pk"])}
        else:
            if request.content_type != "application/json" or len(request.body) > 6144:
                raise ValueError
            data = json.loads(request.body, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            if (type(data) is not dict or set(data) != {"receipt_proof", "acknowledge_useful_next_action"}
                or data["acknowledge_useful_next_action"] is not True):
                raise ValueError
            acknowledge_first_audit_value(project=project, actor=request.user, job_id=job_id,
                action_review_id=selected["pk"], proof=data["receipt_proof"],
                acknowledge_useful_next_action=data["acknowledge_useful_next_action"])
            result = inspect_first_audit_value(project=project, actor=request.user)
    except PermissionDenied:
        return _response({"message": "Current usefulness access unavailable."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, IntegrityError, TypeError, ValueError, UnicodeError, RecursionError):
        return _response({"message": "Usefulness could not be confirmed. Inspect saved history before another acknowledgment."}, HTTPStatus.CONFLICT)
    return _response(result)


@require_http_methods(["GET", "POST"])
def project_first_audit(request, organization_id, project_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    project = Project.objects.for_user(request.user).filter(pk=project_id, organization_id=organization_id).first()
    if project is None:
        return _response({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user,
                               action=Action.LAUNCH_JOB if request.method == "POST" else Action.VIEW_PROJECT)
    except PermissionDenied:
        return _response({"message": "First audit unavailable."}, HTTPStatus.FORBIDDEN)
    configuration = getattr(project, "configuration", None)
    if configuration and configuration.source_choice == "synthetic_demo":
        if request.method == "POST":
            return _response({"message": "Synthetic demo cannot launch live project work. Select an actual source mode first."},
                             HTTPStatus.CONFLICT)
        return _response({"project_id": project.pk, "scope": "current_bounded_project_sources_not_a_complete_audit",
            "mode": "synthetic_demo_separate_no_live_observation", "crawl": [], "crawl_has_more": False,
            "performance": [], "performance_has_more": False, "imports": [], "imports_has_more": False,
            "candidates": [], "candidate_state": "synthetic_demo_separate_no_live_observation",
            "candidates_truncated": False, "limitations": ["demo_is_not_live_data_or_metered_work"]})
    if request.method == "POST":
        if not ratelimit.consume(request, action="performance_audit", user=request.user):
            return _response({"message": "Too many audit requests."}, HTTPStatus.TOO_MANY_REQUESTS)
        try:
            if len(request.body) > 256:
                raise ValidationError("Choose a bounded project crawl.")
            data = json.loads(request.body)
            if type(data) is not dict or set(data) != {"page_limit", "idempotency_key"} or type(data["page_limit"]) is not int:
                raise ValidationError("Choose a bounded project crawl.")
            if not 1 <= data["page_limit"] <= 5:
                raise ValidationError("First audit crawls at most five project pages.")
            job = queue_first_audit(project=project, actor=request.user, page_limit=data["page_limit"],
                                    idempotency_key=data["idempotency_key"])
        except PermissionDenied:
            return _response({"message": "Project crawl unavailable."}, HTTPStatus.FORBIDDEN)
        except UsageLimitError as error:
            return _response({"message": "First audit trial or internal capacity unavailable.", "code": error.category},
                             HTTPStatus.FORBIDDEN if error.category == "trial_unavailable" else HTTPStatus.TOO_MANY_REQUESTS)
        except (ValidationError, ValueError, TypeError, IntegrityError):
            return _response({"message": "Choose a current project and a 1–5 page budget."}, HTTPStatus.CONFLICT)
        return _response({"project_id": project.pk, "job": _job(job),
                          "next_step": "refresh_and_review_actual_crawl_evidence"}, HTTPStatus.ACCEPTED)
    crawl = list(JobRun.objects.filter(project=project, handler="crawl_site").order_by("-created_at", "-pk")[:11])
    performance = list(JobRun.objects.filter(project=project, handler="audit_performance").order_by("-created_at", "-pk")[:11])
    imports = list(ImportRun.objects.filter(project=project).order_by("-created_at", "-pk")[:11])
    findings_response = project_findings(request, organization_id, project_id)
    findings = json.loads(findings_response.content) if findings_response.status_code == 200 else None
    candidates = [row for row in findings["findings"] if row["source_current"]] if findings else []
    candidates.sort(key=lambda row: {"high": 0, "medium": 1, "low": 2}.get(
        row["review"]["priority"] if row["review"] else "", 3))
    return _response({"project_id": project.pk, "scope": "current_bounded_project_sources_not_a_complete_audit",
        "mode": "live_configured_project_sources",
        "crawl": [_job(job) for job in crawl[:10]], "crawl_has_more": len(crawl) > 10,
        "performance": [_job(job) for job in performance[:10]], "performance_has_more": len(performance) > 10,
        "imports": [{"id": row.pk, "state": row.status, "coverage": row.coverage_state,
                     "row_errors": row.row_errors, "recorded_at": row.created_at.isoformat()} for row in imports[:10]],
        "imports_has_more": len(imports) > 10,
        "candidates": [{"id": row["id"], "subject": row["subject"], "detector": row["detector"],
                        "source_id": row["source_metric_id"] or row["source_diagnostics_id"] or
                        row["source_indexation_id"] or row["source_performance_id"],
                        "confidence": row["confidence"], "priority": row["review"]["priority"] if row["review"] else "unreviewed",
                        "detected_at": row["detected_at"]} for row in candidates[:3]],
        "candidate_state": "source_unavailable" if findings is None else "candidates" if candidates else "no_current_candidates_observed_not_clean",
        "candidates_truncated": bool(findings and (findings["has_more"] or len(candidates) > 3)),
        "limitations": ["csv_and_crawl_are_different_sources", "crawl_is_not_indexation",
                        "performance_requires_a_configured_key", "no_conversion_without_exact_origin"]})


@require_http_methods(["GET", "POST"])
def project_first_audit_job(request, organization_id, project_id, job_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    project = Project.objects.for_user(request.user).filter(pk=project_id, organization_id=organization_id).first()
    if project is None:
        return _response({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    job = JobRun.objects.filter(pk=job_id, project=project, handler="crawl_site").first()
    if job is None:
        return _response({"message": "First audit crawl unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user,
                               action=Action.LAUNCH_JOB if request.method == "POST" else Action.VIEW_PROJECT)
        if request.method == "POST":
            if request.content_type != "application/json" or len(request.body) > 256:
                raise ValidationError("Choose one audit request.")
            data = json.loads(request.body, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            if type(data) is not dict:
                raise ValidationError("Choose one audit request.")
            if set(data) == {"idempotency_key"}:
                if not ratelimit.consume(request, action="performance_audit", user=request.user):
                    return _response({"message": "Too many audit requests."}, HTTPStatus.TOO_MANY_REQUESTS)
                job = retry_first_audit(job=job, actor=request.user, idempotency_key=data["idempotency_key"])
                return _response({"project_id": project.pk, "job": _job(job)}, HTTPStatus.ACCEPTED)
            if data:
                raise ValidationError("Choose one audit request.")
            job, _changed, _requested = cancel_job(job=job, actor=request.user)
    except PermissionDenied:
        return _response({"message": "First audit crawl unavailable."}, HTTPStatus.FORBIDDEN)
    except UsageLimitError as error:
        return _response({"message": "First audit trial or internal capacity unavailable.", "code": error.category},
                         HTTPStatus.FORBIDDEN if error.category == "trial_unavailable" else HTTPStatus.TOO_MANY_REQUESTS)
    except (ValidationError, ValueError, TypeError, IntegrityError):
        return _response({"message": "Audit request unavailable; refresh status."}, HTTPStatus.CONFLICT)
    return _response({"project_id": project.pk, "job": _job(job)})
