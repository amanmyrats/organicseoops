"""Private scoped observations and explicit paid-repeat commands."""
from datetime import timedelta
from http import HTTPStatus
import json
import re

from allauth.core import ratelimit
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import IntegrityError
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from integrations.search_console_transport import _reject_constant, _unique_object
from tenancy.models import DomainAlias
from tenancy.services import Action, project_has_origin, require_project_action
from .ai_text_api import _project
from .models import JobCancellation, JobRun, JobSchedule
from .research_api import _result
from .serp import HANDLER, METHOD, configuration, queue_observation
from .serp_schedule import create_schedule, schedule_denial, set_enabled
from .services import cancel_job
from .usage import UsageLimitError, require_billable_access


def job_payload(job, *, detailed=False):
    current = project_has_origin(job.project, job.input_snapshot["origin"])
    step = job.steps.filter(sequence=1).first()
    return {"id": job.pk, "project_id": job.project_id, "status": job.status, "request_key": job.idempotency_key,
        "selection": job.input_snapshot, "source": job.config_snapshot, "schedule_id": job.schedule_id,
        "scheduled_for": job.scheduled_for.isoformat() if job.scheduled_for else None, "source_current": current,
        "created_at": job.created_at.isoformat(), "error_category": job.error_category or job.dispatch_error,
        "cancel_requested": JobCancellation.objects.filter(job=job).exists(), "attempted": step is not None,
        "reported_cost_usd": step.output.get("reported_cost_usd") if step else None,
        "evidence": job.output if current and detailed and job.output else None}


def _schedule_row(schedule):
    return {"id": schedule.pk, "project_id": schedule.project_id, "request_key": schedule.idempotency_key,
        "enabled": schedule.enabled, "sample": schedule.input_snapshot["sample"], "policy": schedule.input_snapshot["policy"],
        "expires_at": schedule.input_snapshot["expires_at"], "queued_occurrences": schedule.runs.count(),
        "skipped_occurrences": schedule.skipped_occurrences, "blocked_reason": schedule_denial(schedule, require_enabled=False),
        "last_error_category": schedule.last_error_category,
        "next_run_at": schedule.next_run_at.isoformat() if schedule.next_run_at else None}


def _capabilities():
    try:
        config = configuration()
        return {"provider": "dataforseo", "engine": "google", "revision": config.revision,
            "locations": config.locations, "languages": config.languages, "devices": ["desktop", "mobile"],
            "depth": 10, "estimated_task_cost_usd": str(config.estimated_task_cost_usd),
            "reviewed_until": config.reviewed_until.isoformat(), "hard_provider_cost_cap": False}
    except ValidationError:
        return None


def _body(request):
    if request.content_type != "application/json" or len(request.body) > 8192:
        raise ValidationError("Use bounded JSON commands.")
    data = json.loads(request.body, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    if type(data) is not dict:
        raise ValidationError("Use exact command fields.")
    return data


@require_http_methods(["GET", "POST"])
def project_serp(request, organization_id, project_id, job_id=None):
    project = _project(request, organization_id, project_id)
    if project is None:
        return _result({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.VIEW_PROJECT)
        query = JobRun.objects.filter(project=project, organization_id=organization_id, handler=HANDLER).select_related("project")
        job = query.get(pk=job_id) if job_id else None
        if request.method == "POST":
            require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
            if not ratelimit.consume(request, action="serp_observation", user=request.user):
                return _result({"message": "Too many SERP decisions."}, HTTPStatus.TOO_MANY_REQUESTS)
            data = _body(request)
            if job:
                if data != {"command": "cancel"}:
                    raise ValidationError("Use an explicit cancellation command.")
                job, _changed, _pending = cancel_job(job=job, actor=request.user)
                return _result({"project_id": project.pk, "method": METHOD, "job": job_payload(job)}, HTTPStatus.OK)
            command = data.pop("command", None)
            if command == "observe" and set(data) == {"sample", "revision", "request_key", "acknowledge_paid_requests"}:
                if data.pop("acknowledge_paid_requests") is not True:
                    raise ValidationError("Acknowledge the paid request and estimated exposure.")
                job = queue_observation(project=project, actor=request.user, data=data.pop("sample"), **data)
                return _result({"project_id": project.pk, "method": METHOD, "job": job_payload(job)}, HTTPStatus.ACCEPTED)
            if command == "create_schedule" and set(data) == {"sample", "revision", "request_key", "interval_minutes", "max_occurrences", "lifetime_days", "total_max_cost_usd", "acknowledge_paid_requests"}:
                schedule = create_schedule(project=project, actor=request.user, **data)
            elif command == "set_schedule" and set(data) == {"schedule_id", "enabled", "acknowledge_paid_requests"} and type(data["schedule_id"]) is int:
                schedule = set_enabled(project=project, actor=request.user, **data)
            else:
                raise ValidationError("Use exact SERP command fields.")
            return _result({"project_id": project.pk, "method": METHOD, "schedule": _schedule_row(schedule)})
        if job:
            if request.GET:
                raise ValidationError("Use the exact observation address.")
            return _result({"project_id": project.pk, "method": METHOD, "job": job_payload(job, detailed=True)})
        if set(request.GET) - {"before", "schedule_before", "request_key"} or any(len(values) != 1 for _, values in request.GET.lists()):
            raise ValidationError("Use one bounded history cursor per list.")
        schedules = JobSchedule.objects.filter(project=project, handler=HANDLER).select_related("project__organization", "actor")
        for name in ("before", "schedule_before"):
            value = request.GET.get(name)
            if value is not None:
                if not re.fullmatch(r"[1-9][0-9]{0,15}", value):
                    raise ValidationError("Use an actual history cursor.")
                if name == "before":
                    query = query.filter(pk__lt=int(value))
                else:
                    schedules = schedules.filter(pk__lt=int(value))
        key = request.GET.get("request_key")
        if key is not None:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{7,63}", key):
                raise ValidationError("Use a bounded request key.")
            query, schedules = query.filter(idempotency_key=key), schedules.filter(idempotency_key=key)
        rows, repeats = list(query.order_by("-pk")[:21]), list(schedules.order_by("-pk")[:21])
        can_manage, can_collect = False, False
        try:
            require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
            can_manage = True
            require_billable_access(organization=project.organization)
            can_collect = True
        except (PermissionDenied, UsageLimitError):
            can_collect = False
        oldest = JobRun.objects.filter(project=project, handler=HANDLER, status="succeeded").order_by("created_at").first()
        return _result({"project_id": project.pk, "method": METHOD, "can_manage": can_manage, "can_collect": can_collect,
            "capabilities": _capabilities(), "origins": sorted({project.canonical_origin, *DomainAlias.objects.filter(project=project).values_list("origin", flat=True)}),
            "history_started_at": oldest.output.get("observed_at") if oldest else None,
            "jobs": [job_payload(row) for row in rows[:20]], "next_before": rows[19].pk if len(rows) > 20 else None,
            "schedules": [_schedule_row(row) for row in repeats[:20]], "next_schedule_before": repeats[19].pk if len(repeats) > 20 else None,
            "live_verified": False, "backfill_available": False})
    except PermissionDenied:
        return _result({"message": "Current project authority required."}, HTTPStatus.FORBIDDEN)
    except ObjectDoesNotExist:
        return _result({"message": "SERP configuration or record unavailable."}, HTTPStatus.NOT_FOUND)
    except UsageLimitError as error:
        return _result({"message": "Job allowance unavailable.", "code": error.category}, HTTPStatus.TOO_MANY_REQUESTS)
    except (ValidationError, IntegrityError, ValueError, TypeError, UnicodeError, RecursionError):
        return _result({"message": "SERP decision unconfirmed. Inspect history using the same request key before another paid selection."}, HTTPStatus.CONFLICT)


@require_http_methods(["GET"])
def project_serp_overlap(request, organization_id, project_id):
    project = _project(request, organization_id, project_id)
    if project is None:
        return _result({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.VIEW_PROJECT)
    except PermissionDenied:
        return _result({"message": "Project unavailable."}, HTTPStatus.FORBIDDEN)
    if request.GET:
        return _result({"message": "Use the exact bounded overlap address."}, HTTPStatus.BAD_REQUEST)
    jobs = list(JobRun.objects.filter(project=project, handler=HANDLER, status="succeeded",
        created_at__gte=timezone.now() - timedelta(days=90)).order_by("-pk")[:101])
    groups = {}
    origins = {project.canonical_origin, *DomainAlias.objects.filter(project=project).values_list("origin", flat=True)}
    for job in jobs[:100]:
        data = job.input_snapshot
        if data["origin"] not in origins:
            continue
        dimension = (data["engine"], data["location_code"], data["language_code"], data["device"], data["origin"])
        for row in job.output.get("rows", []):
            if row["matches_origin"]:
                continue
            key = (*dimension, row["domain"])
            group = groups.setdefault(key, {"domain": row["domain"], "engine": dimension[0], "location_code": dimension[1],
                "language_code": dimension[2], "device": dimension[3], "origin": dimension[4], "queries": set(), "job_ids": set()})
            group["queries"].add(data["query"])
            group["job_ids"].add(job.pk)
    candidates = [{**group, "queries": sorted(group["queries"]), "job_ids": sorted(group["job_ids"])}
        for group in groups.values() if len(group["queries"]) >= 2]
    candidates.sort(key=lambda row: (-len(row["queries"]), row["domain"], row["location_code"], row["device"]))
    return _result({"project_id": project.pk, "method": METHOD, "window_days": 90, "inspected_jobs": min(100, len(jobs)),
        "history_truncated": len(jobs) > 100, "candidates": candidates[:20], "has_more": len(candidates) > 20,
        "approval_required": True, "basis": "domain_observed_for_at_least_two_distinct_tracked_queries_same_dimensions_not_market_share"})
