"""Finite explicit rank observations; missed slots never create a paid catch-up sweep."""
from datetime import datetime, timedelta
import re

from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from integrations.serp_models import SerpConfiguration
from tenancy.models import Organization
from tenancy.services import Action, require_project_action
from .models import JobRun, JobSchedule, JobStatus
from .serp import HANDLER, SerpCapacityError, money, queue_observation, selection, validate_input
from .usage import UsageLimitError, require_billable_access

METHOD = "serp-finite-repeat-v1"


def policy_for(sample, interval_minutes, max_occurrences, lifetime_days, total_max_cost_usd, acknowledge_paid_requests):
    validate_input(sample)
    if (type(interval_minutes) is not int or not 1440 <= interval_minutes <= 10080
        or type(max_occurrences) is not int or not 1 <= max_occurrences <= 30
        or type(lifetime_days) is not int or not 1 <= lifetime_days <= 30
        or interval_minutes >= lifetime_days * 1440 or acknowledge_paid_requests is not True
        or money(sample["max_cost_usd"]) * max_occurrences > money(total_max_cost_usd)):
        raise ValidationError("Choose daily-to-weekly cadence, at most30 occurrences/days and explicit estimated total exposure covering every slot.")
    return {"method": METHOD, "interval_minutes": interval_minutes, "max_occurrences": max_occurrences,
        "lifetime_days": lifetime_days, "total_max_cost_usd": total_max_cost_usd, "acknowledge_paid_requests": True}


def validate_schedule(schedule):
    data = schedule.input_snapshot
    try:
        if type(data) is not dict or set(data) != {"sample", "selection", "policy", "issued_at", "expires_at"}:
            raise ValueError
        policy = data["policy"]
        if type(policy) is not dict or set(policy) != {"method", "interval_minutes", "max_occurrences", "lifetime_days", "total_max_cost_usd", "acknowledge_paid_requests"}:
            raise ValueError
        expected = policy_for(data["sample"], **{key: value for key, value in policy.items() if key != "method"})
        issued, expires = (datetime.fromisoformat(data[key]) for key in ("issued_at", "expires_at"))
        if (policy != expected or timezone.is_naive(issued) or timezone.is_naive(expires)
            or expires != issued + timedelta(days=policy["lifetime_days"]) or type(data["selection"]) is not dict
            or schedule.handler != HANDLER or schedule.interval_minutes != policy["interval_minutes"]):
            raise ValueError
        if schedule._state.adding:
            if schedule.enabled or not timezone.now() - timedelta(minutes=5) <= issued <= timezone.now():
                raise ValueError
            require_billable_access(organization=schedule.project.organization)
            if selection(schedule.project, schedule.actor, data["sample"]) != data["selection"]:
                raise ValueError
        return issued, expires
    except (KeyError, ValueError, TypeError):
        raise ValidationError("Use an immutable bounded SERP repeat authorization.") from None


def schedule_denial(schedule, *, for_job=None, require_enabled=True):
    try:
        _issued, expires = validate_schedule(schedule)
        if require_enabled and not schedule.enabled:
            return "repeat_paused"
        if timezone.now() >= expires:
            return "repeat_expired"
        count = schedule.runs.count()
        maximum = schedule.input_snapshot["policy"]["max_occurrences"]
        if count > maximum or for_job is None and count >= maximum:
            return "repeat_exhausted"
        require_billable_access(organization=schedule.project.organization)
        if selection(schedule.project, schedule.actor, schedule.input_snapshot["sample"]) != schedule.input_snapshot["selection"]:
            return "repeat_selection_changed"
    except UsageLimitError as error:
        return error.category
    except (PermissionDenied, ValidationError, ObjectDoesNotExist):
        return "repeat_source_or_actor_lost"
    return ""


def validate_scheduled_job(job, *, current=False):
    schedule = JobSchedule.objects.select_related("project__organization", "actor").get(pk=job.schedule_id)
    issued, expires = validate_schedule(schedule)
    selected = {key: value for key, value in job.config_snapshot.items() if key != "budget_month"}
    if (schedule.handler != HANDLER or schedule.organization_id != job.organization_id or schedule.project_id != job.project_id
        or schedule.actor_id != job.actor_id or job.input_snapshot != schedule.input_snapshot["sample"]
        or selected != schedule.input_snapshot["selection"] or job.scheduled_for is None
        or timezone.is_naive(job.scheduled_for) or not issued <= job.scheduled_for < expires):
        raise ValidationError("This observation does not match its frozen repeat authorization.")
    if current:
        denied = schedule_denial(schedule, for_job=None if job._state.adding else job)
        if denied or job._state.adding and (job.scheduled_for != schedule.next_run_at or job.scheduled_for > timezone.now()):
            raise ValidationError(denied or "repeat_occurrence_unavailable")


def create_schedule(*, project, actor, sample, interval_minutes, max_occurrences, lifetime_days,
                    total_max_cost_usd, acknowledge_paid_requests, revision, request_key):
    if type(request_key) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", request_key):
        raise ValidationError("Use a bounded repeat request key.")
    policy = policy_for(sample, interval_minutes, max_occurrences, lifetime_days, total_max_cost_usd, acknowledge_paid_requests)
    with transaction.atomic():
        SerpConfiguration.objects.select_for_update().get(key="primary")
        Organization.objects.select_for_update().get(pk=project.organization_id)
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        existing = JobSchedule.objects.filter(project=project, handler=HANDLER, idempotency_key=request_key).first()
        if existing:
            if existing.actor_id != actor.pk or existing.input_snapshot["sample"] != sample or existing.input_snapshot["policy"] != policy:
                raise ValidationError("Repeat key belongs to another authorization.")
            return existing
        selected = selection(project, actor, sample)
        if type(revision) is not int or revision != selected["revision"]:
            raise ValidationError("Refresh provider configuration.")
        peers = list(JobSchedule.objects.filter(project=project, handler=HANDLER).order_by("-pk")[:101])
        if len(peers) > 100:
            raise ValidationError("The bounded project repeat-authorization limit is reached.")
        dimensions = {key: value for key, value in sample.items() if key != "max_cost_usd"}
        for peer in peers:
            if ({key: value for key, value in peer.input_snapshot["sample"].items() if key != "max_cost_usd"} == dimensions
                and not schedule_denial(peer, require_enabled=False)):
                raise ValidationError("These dimensions already have a live repeat authorization; use its controls.")
        now = timezone.now()
        return JobSchedule.objects.create(organization=project.organization, project=project, actor=actor, handler=HANDLER,
            interval_minutes=interval_minutes, idempotency_key=request_key, input_snapshot={"sample": sample,
            "selection": selected, "policy": policy, "issued_at": now.isoformat(), "expires_at": (now + timedelta(days=lifetime_days)).isoformat()})


def set_enabled(*, project, actor, schedule_id, enabled, acknowledge_paid_requests):
    if type(enabled) is not bool or enabled and acknowledge_paid_requests is not True:
        raise ValidationError("Explicitly acknowledge paid repeat observations.")
    with transaction.atomic():
        SerpConfiguration.objects.select_for_update().get(key="primary")
        Organization.objects.select_for_update().get(pk=project.organization_id)
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        schedule = JobSchedule.objects.select_for_update(of=("self",)).select_related("project__organization", "actor").get(
            pk=schedule_id, project=project, handler=HANDLER)
        if enabled:
            denied = schedule_denial(schedule, require_enabled=False)
            next_at = timezone.now() + timedelta(minutes=schedule.interval_minutes)
            if denied or next_at >= validate_schedule(schedule)[1]:
                raise ValidationError(denied or "No future slot remains before expiry.")
            if not schedule.enabled:
                schedule.next_run_at = next_at
        schedule.enabled = enabled
        schedule.last_error_category = "" if enabled else "repeat_paused"
        schedule.save(update_fields=["enabled", "next_run_at", "last_error_category"])
        return schedule


def run_due_schedules(*, limit=20):
    now = timezone.now()
    ids = list(JobSchedule.objects.filter(handler=HANDLER, enabled=True, next_run_at__lte=now)
        .order_by("next_run_at", "pk").values_list("pk", flat=True)[:limit])
    count = 0
    for pk in ids:
        with transaction.atomic():
            SerpConfiguration.objects.select_for_update().get(key="primary")
            identity = JobSchedule.objects.values_list("organization_id", flat=True).get(pk=pk)
            Organization.objects.select_for_update().get(pk=identity)
            schedule = JobSchedule.objects.select_for_update(of=("self",)).select_related("project__organization", "actor").get(pk=pk)
            if not schedule.enabled or schedule.next_run_at > now:
                continue
            denied = schedule_denial(schedule)
            # A final authorized request can finish before the next due tick disables its schedule.
            if denied == "repeat_exhausted" and schedule.runs.filter(status__in=[JobStatus.QUEUED, JobStatus.RUNNING]).exists():
                continue
            if denied:
                schedule.enabled, schedule.last_error_category = False, denied[:40]
                schedule.save(update_fields=["enabled", "last_error_category"])
                continue
            interval = timedelta(minutes=schedule.interval_minutes)
            missed = max(0, (now - schedule.next_run_at) // interval)
            occurrence = schedule.next_run_at + missed * interval
            schedule.next_run_at = occurrence
            schedule.skipped_occurrences = min(1000000, schedule.skipped_occurrences + missed)
            schedule.save(update_fields=["next_run_at", "skipped_occurrences"])
            next_delay = interval
            try:
                queue_observation(project=schedule.project, actor=schedule.actor, data=schedule.input_snapshot["sample"],
                    revision=schedule.input_snapshot["selection"]["revision"], schedule=schedule, scheduled_for=occurrence,
                    request_key=f"serp-{pk}-{int(occurrence.timestamp())}")
            except SerpCapacityError:
                schedule.last_error_category = "provider_busy_deferred"
                next_delay = timedelta(minutes=5)  # Revisit a current live sample; never replay a past paid request.
            except (ValidationError, PermissionDenied, UsageLimitError):
                schedule.enabled, schedule.last_error_category = False, "repeat_budget_or_selection_lost"
            else:
                count += 1
                schedule.last_run_at = occurrence
                schedule.last_error_category = ""
            schedule.next_run_at = now + next_delay
            schedule.save(update_fields=["enabled", "next_run_at", "last_run_at", "last_error_category", "skipped_occurrences"])
    return count
