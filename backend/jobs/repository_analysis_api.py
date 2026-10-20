"""Private project-scoped commands and bounded root-manifest evidence."""
from http import HTTPStatus
import json
import re

from allauth.core import ratelimit
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import IntegrityError
from django.views.decorators.http import require_http_methods

from integrations.repository_models import RepositoryGrant
from integrations.repository_oauth import grant_current
from integrations.search_console_transport import _reject_constant, _unique_object
from tenancy.services import Action, require_project_action
from .ai_text_api import _project
from .models import JobCancellation, JobRun
from .repository_analysis import ATTEMPT, HANDLER, METHOD, SANDBOX, configuration, maximum_requests, queue_analysis, source_current
from . import repository_advisories as advisories
from . import repository_code as code
from .research_api import _result
from .services import cancel_job
from .usage import UsageLimitError, require_billable_access


def available(*, advisory=False):
    try:
        configuration()
        if advisory:
            advisories.configuration()
        return True
    except ValidationError:
        return False


def job_payload(job, *, detailed=False):
    current = source_current(job)
    step = job.steps.filter(name=SANDBOX).first()
    source = {key: job.config_snapshot[key] for key in ("provider", "repository", "repository_id", "commit_sha")}
    evidence = None
    if current and detailed and job.output:
        evidence = {key: job.output[key] for key in ("method", "tree_sha", "collected_at", "coverage", "cleanup_confirmed", "analysis")}
        evidence["advisories"] = job.output.get("advisories")
        evidence["code_analysis"] = evidence["analysis"] if job.input_snapshot["operation"] == code.OPERATION else None
        if evidence["code_analysis"] is not None:
            evidence["analysis"] = None
    return {"id": job.pk, "project_id": job.project_id, "status": job.status, "request_key": job.idempotency_key,
        "grant_id": job.input_snapshot["grant_id"], "operation": job.input_snapshot["operation"], "source_path": job.input_snapshot.get("source_path"), "source": source, "source_current": current,
        "created_at": job.created_at.isoformat(), "error_category": job.error_category or job.dispatch_error,
        "cancel_requested": JobCancellation.objects.filter(job=job).exists(),
        "attempted_requests": job.steps.filter(name__in=[ATTEMPT, advisories.ATTEMPT]).count(), "maximum_requests": maximum_requests(job.input_snapshot),
        "attempted_repository_requests": job.steps.filter(name=ATTEMPT).count(),
        "attempted_advisory_requests": job.steps.filter(name=advisories.ATTEMPT).count(),
        "cleanup": "not_started" if step is None else "confirmed" if step.output.get("cleanup_confirmed") is True else "pending",
        "evidence": evidence}


@require_http_methods(["GET", "POST"])
def project_repository_analysis(request, organization_id, project_id, job_id=None):
    project = _project(request, organization_id, project_id)
    if project is None:
        return _result({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.VIEW_PROJECT)
        query = JobRun.objects.filter(project=project, organization_id=organization_id, handler=HANDLER).select_related("project", "actor")
        job = query.get(pk=job_id) if job_id else None
        if request.method == "POST":
            require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
            if not ratelimit.consume(request, action="repository_analysis", user=request.user):
                return _result({"message": "Too many repository decisions."}, HTTPStatus.TOO_MANY_REQUESTS)
            if request.GET or request.content_type != "application/json" or len(request.body) > 4096:
                raise ValidationError("Use bounded exact JSON commands.")
            data = json.loads(request.body, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            if type(data) is not dict:
                raise ValidationError("Use exact repository command fields.")
            if job:
                if data != {"command": "cancel"}:
                    raise ValidationError("Use explicit cancellation.")
                job, _changed, _pending = cancel_job(job=job, actor=request.user)
                return _result({"project_id": project.pk, "method": METHOD, "job": job_payload(job)})
            if data.pop("command", None) != "analyze" or "request_key" not in data:
                raise ValidationError("Use exact analysis fields.")
            key = data.pop("request_key")
            job = queue_analysis(project=project, actor=request.user, data=data, request_key=key)
            return _result({"project_id": project.pk, "method": METHOD, "job": job_payload(job)}, HTTPStatus.ACCEPTED)
        if job:
            if request.GET:
                raise ValidationError("Use the exact analysis address.")
            return _result({"project_id": project.pk, "method": METHOD, "job": job_payload(job, detailed=True)})
        if set(request.GET) - {"before", "grant_before", "request_key"} or any(len(values) != 1 for _, values in request.GET.lists()):
            raise ValidationError("Use bounded history cursors.")
        grants = RepositoryGrant.objects.filter(project=project, organization_id=organization_id, state="active").select_related("actor", "consent")
        for name in ("before", "grant_before"):
            value = request.GET.get(name)
            if value is not None:
                if not re.fullmatch(r"[1-9][0-9]{0,15}", value):
                    raise ValidationError("Use an actual history cursor.")
                if name == "before":
                    query = query.filter(pk__lt=int(value))
                else:
                    grants = grants.filter(pk__lt=int(value))
        key = request.GET.get("request_key")
        if key is not None:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{7,63}", key):
                raise ValidationError("Use a bounded request key.")
            query = query.filter(idempotency_key=key)
        rows, sources = list(query.order_by("-pk")[:21]), list(grants.order_by("-pk")[:21])
        can_manage = can_collect = False
        try:
            require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
            can_manage = True
            require_billable_access(organization=project.organization)
            can_collect = True
        except (PermissionDenied, UsageLimitError):
            pass
        return _result({"project_id": project.pk, "method": METHOD, "available": available(), "advisories_available": available(advisory=True),
            "can_manage": can_manage, "can_collect": can_collect,
            "grants": [{"id": grant.pk, "revision": grant.revision, "repository": grant.repository,
                "repository_id": grant.repository_id, "commit_sha": grant.commit_sha,
                "expires_at": grant.expires_at.isoformat(), "source_current": grant_current(grant)} for grant in sources[:20]],
            "next_grant_before": sources[19].pk if len(sources) > 20 else None,
            "jobs": [job_payload(row) for row in rows[:20]], "next_before": rows[19].pk if len(rows) > 20 else None})
    except PermissionDenied:
        return _result({"message": "Current project authority required."}, HTTPStatus.FORBIDDEN)
    except ObjectDoesNotExist:
        return _result({"message": "Repository record unavailable."}, HTTPStatus.NOT_FOUND)
    except UsageLimitError as error:
        return _result({"message": "Job allowance unavailable.", "code": error.category}, HTTPStatus.TOO_MANY_REQUESTS)
    except (ValidationError, IntegrityError, ValueError, TypeError, UnicodeError, RecursionError):
        return _result({"message": "Analysis decision unconfirmed. Inspect history using the same request key before another collection."}, HTTPStatus.CONFLICT)
