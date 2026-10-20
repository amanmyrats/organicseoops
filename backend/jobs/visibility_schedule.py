"""Explicit finite repeat authorization over an unchanged D120 prompt revision."""
from datetime import datetime, timedelta
from decimal import Decimal
import re

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from tenancy.models import Organization, Project
from tenancy.services import Action, require_project_action
from providers.services import resolve_provider_secret
from .ai_text import _max_cost
from .models import JobRun, JobSchedule, JobStatus
from .usage import UsageLimitError, require_billable_access
from .visibility_collection import HANDLER, _repeat_denial, selection_snapshot, validate_collection_input

METHOD = "visibility-repeat-schedule-v1"


def repeat_policy(*, sample, interval_minutes, max_occurrences, lifetime_days, total_max_cost_usd,
                  acknowledge_repeat_data_use):
    validate_collection_input(sample)
    total = _max_cost(total_max_cost_usd)
    if (type(interval_minutes) is not int or not 1440 <= interval_minutes <= 10080
        or type(max_occurrences) is not int or not 1 <= max_occurrences <= 30
        or type(lifetime_days) is not int or not 1 <= lifetime_days <= 30
        or interval_minutes > lifetime_days * 1440 or acknowledge_repeat_data_use is not True
        or Decimal(sample["max_cost_usd"]) * max_occurrences > total):
        raise ValidationError("Choose daily-to-weekly cadence, finite lifetime/occurrences and total estimated exposure covering every slot.")
    return {"method": METHOD, "interval_minutes": interval_minutes, "max_occurrences": max_occurrences,
        "lifetime_days": lifetime_days, "total_max_cost_usd": str(total), "acknowledge_repeat_data_use": True}


def validate_schedule_snapshot(schedule):
    data = schedule.input_snapshot
    if type(data) is not dict or set(data) != {"sample", "selection", "policy", "issued_at", "expires_at"}:
        raise ValidationError("Use a separately authorized repeat schedule.")
    policy = data["policy"]
    if type(policy) is not dict or set(policy) != {"method", "interval_minutes", "max_occurrences", "lifetime_days",
                                                "total_max_cost_usd", "acknowledge_repeat_data_use"}:
        raise ValidationError("Repeat policy is unavailable.")
    expected = repeat_policy(sample=data["sample"], **{key: value for key, value in policy.items() if key != "method"})
    try:
        issued, expires = (datetime.fromisoformat(data[key]) for key in ("issued_at", "expires_at"))
    except (ValueError, TypeError):
        raise ValidationError("Repeat lifetime is unavailable.") from None
    if (policy != expected or schedule.interval_minutes != policy["interval_minutes"]
        or timezone.is_naive(issued) or timezone.is_naive(expires)
        or expires != issued + timedelta(days=policy["lifetime_days"])
        or type(data["selection"]) is not dict or schedule.handler != HANDLER):
        raise ValidationError("Repeat bounds or lifetime changed.")
    return issued, expires


def schedule_denial(schedule, *, now=None, for_job=None, require_enabled=True, check_secret=True):
    now = now or timezone.now()
    try:
        _issued, expires = validate_schedule_snapshot(schedule)
        if require_enabled and not schedule.enabled:
            return "repeat_paused"
        if now >= expires:
            return "repeat_expired"
        count = schedule.runs.count()
        maximum = schedule.input_snapshot["policy"]["max_occurrences"]
        if count > maximum or for_job is None and count >= maximum:
            return "repeat_exhausted"
        require_project_action(project=schedule.project, user=schedule.actor, action=Action.MANAGE_PROJECT)
        require_billable_access(organization=schedule.project.organization)
        _model, account, config = selection_snapshot(schedule.project, schedule.actor, schedule.input_snapshot["sample"])
        if config != schedule.input_snapshot["selection"]:
            return "repeat_selection_changed"
        if check_secret:
            resolve_provider_secret(account, organization=schedule.project.organization,
                                    expected_revision=config["credential_revision"])
    except UsageLimitError as error:
        return error.category
    except (PermissionDenied, ValidationError, KeyError, TypeError, ValueError):
        return "repeat_source_or_actor_lost"
    return ""


def validate_scheduled_job(job, *, current=False):
    from .visibility_collection import METHOD as COLLECTION_METHOD
    if job.retry_of_id:
        raise ValidationError("Visibility attempts cannot use generic retries.")
    if not job.schedule_id:
        return
    schedule = JobSchedule.objects.select_related("project", "actor").get(pk=job.schedule_id)
    issued, expires = validate_schedule_snapshot(schedule)
    if (schedule.organization_id != job.organization_id or schedule.project_id != job.project_id
        or schedule.actor_id != job.actor_id or job.handler != HANDLER
        or job.method_version != COLLECTION_METHOD
        or job.input_snapshot != schedule.input_snapshot["sample"]
        or job.config_snapshot != schedule.input_snapshot["selection"]
        or job.scheduled_for is None or timezone.is_naive(job.scheduled_for)
        or not issued <= job.scheduled_for < expires):
        raise ValidationError("The occurrence must match its exact frozen authorization.")
    if current:
        denied = schedule_denial(schedule)
        if denied or job.scheduled_for != schedule.next_run_at or job.scheduled_for > timezone.now():
            raise ValidationError(denied or "repeat_occurrence_unavailable")


def create_visibility_schedule(*, project, actor, sample, interval_minutes, max_occurrences, lifetime_days,
                               total_max_cost_usd, acknowledge_repeat_data_use, idempotency_key):
    if type(idempotency_key) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", idempotency_key):
        raise ValidationError("Choose a bounded repeat request key.")
    policy = repeat_policy(sample=sample, interval_minutes=interval_minutes, max_occurrences=max_occurrences,
        lifetime_days=lifetime_days, total_max_cost_usd=total_max_cost_usd,
        acknowledge_repeat_data_use=acknowledge_repeat_data_use)
    with transaction.atomic():
        org = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=org)
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        require_billable_access(organization=org)
        _model, _account, config = selection_snapshot(project, actor, sample)
        existing = JobSchedule.objects.filter(project=project, handler=HANDLER, idempotency_key=idempotency_key).first()
        if existing:
            if (existing.actor_id != actor.pk or existing.input_snapshot["sample"] != sample
                or existing.input_snapshot["selection"] != config or existing.input_snapshot["policy"] != policy):
                raise ValidationError("Repeat request key belongs to another authorization.")
            return existing
        now = timezone.now()
        peers = JobSchedule.objects.filter(project=project, handler=HANDLER,
            input_snapshot__selection__visibility__set_id=config["visibility"]["set_id"],
            input_snapshot__sample__prompt_key=sample["prompt_key"])
        for peer in peers:
            if validate_schedule_snapshot(peer)[1] > now and peer.runs.count() < peer.input_snapshot["policy"]["max_occurrences"]:
                raise ValidationError("This set/prompt already has a live repeat authorization.")
        return JobSchedule.objects.create(organization=org, project=project, actor=actor, handler=HANDLER,
            interval_minutes=interval_minutes, idempotency_key=idempotency_key, input_snapshot={"sample": sample,
            "selection": config, "policy": policy, "issued_at": now.isoformat(),
            "expires_at": (now + timedelta(days=lifetime_days)).isoformat()})


def set_visibility_schedule_enabled(*, project, actor, schedule_id, enabled, acknowledge_repeat_data_use):
    if type(enabled) is not bool or enabled and acknowledge_repeat_data_use is not True:
        raise ValidationError("Explicitly acknowledge repeat costs and data use before enabling.")
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=project.organization_id)
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        schedule = JobSchedule.objects.select_for_update(of=("self",)).select_related("project", "actor").filter(
            pk=schedule_id, project=project, handler=HANDLER).first()
        if schedule is None:
            raise PermissionDenied
        if enabled:
            denied = schedule_denial(schedule, require_enabled=False)
            if denied:
                raise ValidationError(denied)
            next_at = timezone.now() + timedelta(minutes=schedule.interval_minutes)
            if next_at >= validate_schedule_snapshot(schedule)[1]:
                raise ValidationError("No future slot remains inside the fixed repeat lifetime.")
            if not schedule.enabled:
                schedule.next_run_at = next_at  # Idempotent enable; no missed-slot replay or lifetime renewal.
        schedule.enabled = enabled
        schedule.last_error_category = "" if enabled else "repeat_paused"
        schedule.save(update_fields=["enabled", "next_run_at", "last_error_category"])
        return schedule


def finish_scheduled_occurrence(job):
    if not job.schedule_id:
        return
    schedule = JobSchedule.objects.select_for_update().get(pk=job.schedule_id)
    reason = (job.error_category or "repeat_attempt_failed") if job.status != JobStatus.SUCCEEDED else schedule_denial(schedule)
    if reason:
        schedule.enabled = False
        schedule.last_error_category = reason[:40]
        schedule.save(update_fields=["enabled", "last_error_category"])


def run_due_visibility_schedules(*, limit=50, now=None):
    from .services import queue_job
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValidationError("Choose a bounded repeat due-run limit.")
    now = now or timezone.now()
    # Created deadlines are UTC ISO strings; select due/expired records so future slots cannot starve due work.
    candidates = list(JobSchedule.objects.filter(handler=HANDLER, enabled=True).filter(
        Q(next_run_at__lte=now) | Q(input_snapshot__expires_at__lte=now.isoformat())).order_by("next_run_at", "pk")
        .values_list("pk", "organization_id")[:limit])
    created = 0
    for pk, org_id in candidates:
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=org_id)
            schedule = JobSchedule.objects.select_for_update(of=("self",)).select_related("project", "actor").get(pk=pk)
            if not schedule.enabled:
                continue
            denied = schedule_denial(schedule, now=now)
            if denied == "repeat_exhausted" and schedule.runs.filter(
                status__in=[JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.WAITING_PROVIDER]).exists():
                continue  # The final authorized occurrence may finish; no further occurrence may queue.
            if denied:
                schedule.enabled = False
                schedule.last_error_category = denied[:40]
                schedule.save(update_fields=["enabled", "last_error_category"])
                continue
            if schedule.next_run_at is None or schedule.next_run_at > now:
                continue
            interval = timedelta(minutes=schedule.interval_minutes)
            missed = max(0, (now - schedule.next_run_at) // interval)
            occurrence = schedule.next_run_at + missed * interval
            schedule.skipped_occurrences = min(1_000_000, schedule.skipped_occurrences + missed)
            schedule.next_run_at = occurrence
            schedule.save(update_fields=["next_run_at", "skipped_occurrences"])
            data = schedule.input_snapshot
            busy = _repeat_denial(schedule.project, data["selection"], data["sample"])
            try:
                if not busy:
                    queue_job(project=schedule.project, actor=schedule.actor, handler=HANDLER,
                        input_snapshot=data["sample"], config_snapshot=data["selection"], schedule=schedule,
                        scheduled_for=occurrence, idempotency_key=f"repeat-{pk}-{int(occurrence.timestamp() * 1000000)}")
            except UsageLimitError as error:
                schedule.last_error_category = error.category
                if error.category != "internal_capacity":
                    schedule.enabled = False
            except (PermissionDenied, ValidationError):
                schedule.enabled = False
                schedule.last_error_category = "repeat_selection_changed"
            else:
                schedule.last_error_category = busy
                if not busy:
                    schedule.last_run_at = occurrence
                    created += 1
                else:
                    schedule.skipped_occurrences = min(1_000_000, schedule.skipped_occurrences + 1)
            schedule.next_run_at = now + interval
            schedule.save(update_fields=["enabled", "last_error_category", "last_run_at", "next_run_at", "skipped_occurrences"])
    return created
