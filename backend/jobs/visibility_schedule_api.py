"""Private repeat authorization commands and metadata; never an answer replay endpoint."""
from http import HTTPStatus
import json
import re

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.views.decorators.http import require_http_methods

from integrations.google_tokens import GoogleTokenError, _reject_constant, _unique_object
from tenancy.services import Action, require_project_action
from .ai_text_api import _project
from .models import JobSchedule
from .research_api import _result
from .usage import UsageLimitError
from .visibility_collection import HANDLER
from .visibility_schedule import (METHOD, create_visibility_schedule, schedule_denial,
                                  set_visibility_schedule_enabled)


def _row(schedule):
    data = schedule.input_snapshot
    return {"id": schedule.pk, "project_id": schedule.project_id, "request_key": schedule.idempotency_key,
        "enabled": schedule.enabled, "sample": data["sample"], "selection": data["selection"], "policy": data["policy"],
        "expires_at": data["expires_at"], "created_at": schedule.created_at.isoformat(),
        "next_run_at": schedule.next_run_at.isoformat() if schedule.next_run_at else None,
        "last_run_at": schedule.last_run_at.isoformat() if schedule.last_run_at else None,
        "queued_occurrences": schedule.runs.count(), "skipped_occurrences": schedule.skipped_occurrences,
        "last_error_category": schedule.last_error_category,
        "blocked_reason": schedule_denial(schedule, require_enabled=False, check_secret=False),
        "attempted_units": sum(job.steps.filter(sequence=1).count() for job in schedule.runs.all()),
        "job_ids": list(schedule.runs.order_by("-pk").values_list("pk", flat=True)[:30])}


@require_http_methods(["GET", "POST"])
def project_visibility_schedules(request, organization_id, project_id, schedule_id=None):
    if not request.user.is_authenticated or not request.user.is_active:
        return _result({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _result({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user,
                               action=Action.MANAGE_PROJECT if request.method == "POST" else Action.VIEW_PROJECT)
    except PermissionDenied:
        return _result({"message": "Current project role unavailable."}, HTTPStatus.FORBIDDEN)
    query = JobSchedule.objects.filter(project=project, handler=HANDLER).select_related("project__organization", "actor")
    schedule = query.filter(pk=schedule_id).first() if schedule_id else None
    if schedule_id and schedule is None:
        return _result({"message": "Repeat authorization unavailable."}, HTTPStatus.NOT_FOUND)
    if request.method == "POST":
        if not ratelimit.consume(request, action="ai_text_request", user=request.user):
            return _result({"message": "Too many repeat decisions."}, HTTPStatus.TOO_MANY_REQUESTS)
        try:
            if request.content_type != "application/json" or len(request.body) > 8192:
                raise ValidationError("Use bounded repeat JSON.")
            data = json.loads(request.body, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            fields = ({"enabled", "acknowledge_repeat_data_use"} if schedule else
                {"sample", "interval_minutes", "max_occurrences", "lifetime_days", "total_max_cost_usd",
                 "acknowledge_repeat_data_use", "idempotency_key"})
            if type(data) is not dict or set(data) != fields:
                raise ValidationError("Use exact repeat command fields.")
            schedule = (set_visibility_schedule_enabled(project=project, actor=request.user, schedule_id=schedule_id, **data)
                if schedule else create_visibility_schedule(project=project, actor=request.user, **data))
        except PermissionDenied:
            return _result({"message": "Current owner/admin source authority required."}, HTTPStatus.FORBIDDEN)
        except UsageLimitError as error:
            return _result({"message": "Repeat allowance unavailable.", "code": error.category}, HTTPStatus.TOO_MANY_REQUESTS)
        except (ValidationError, GoogleTokenError, ValueError, TypeError, UnicodeError, RecursionError, IntegrityError):
            return _result({"message": "Repeat decision unconfirmed: check exact source/model/key, fixed lifetime and exposure. Inspect current status/request key.",
                            "code": "repeat_selection_unavailable"}, HTTPStatus.CONFLICT)
        return _result({"project_id": project.pk, "method": METHOD, "schedule": _row(schedule)}, HTTPStatus.OK if schedule_id else HTTPStatus.CREATED)
    if set(request.GET) - {"request_key", "before_id"} or any(len(values) != 1 for _, values in request.GET.lists()):
        return _result({"message": "Use one bounded repeat lookup/cursor."}, HTTPStatus.BAD_REQUEST)
    key, cursor = request.GET.get("request_key"), request.GET.get("before_id")
    if (key is not None and (cursor is not None or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", key))
        or cursor is not None and (not cursor.isascii() or not cursor.isdigit() or not 1 <= int(cursor) <= 2**53 - 1)):
        return _result({"message": "Use an actual repeat request key/cursor."}, HTTPStatus.BAD_REQUEST)
    if schedule:
        return _result({"project_id": project.pk, "method": METHOD, "schedule": _row(schedule)})
    if key:
        query = query.filter(idempotency_key=key)
    if cursor:
        query = query.filter(pk__lt=int(cursor))
    rows = list(query.order_by("-pk")[:21])
    return _result({"project_id": project.pk, "method": METHOD, "live_verified": False,
        "schedules": [_row(row) for row in rows[:20]], "has_more": len(rows) > 20,
        "next_before_id": rows[19].pk if len(rows) > 20 else None,
        "lookup": "found" if rows else "not_found" if key else "not_requested"})
