from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from tenancy.models import Organization
from tenancy.services import Action, require_project_action

from .models import JobSchedule
from .services import _diagnostic_probe, _snapshot, queue_job
from .usage import UsageLimitError


def create_schedule(*, project, actor, input_snapshot, interval_minutes=1440, idempotency_key=""):
    if not settings.DEBUG or type(interval_minutes) is not int or not 60 <= interval_minutes <= 10080:
        raise ValidationError("Choose an interval between one hour and one week.")
    if not isinstance(idempotency_key, str) or len(idempotency_key) > 64:
        raise ValidationError("Invalid schedule idempotency key.")
    data = _snapshot(input_snapshot)
    _diagnostic_probe(data)
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=project.organization_id)
        require_project_action(project=project, user=actor, action=Action.LAUNCH_JOB)
        existing = (JobSchedule.objects.filter(project=project, handler="diagnostic_probe",
                                                idempotency_key=idempotency_key).first()
                    if idempotency_key else None)
        if existing is not None:
            if existing.actor_id != actor.pk or existing.input_snapshot != data or existing.interval_minutes != interval_minutes:
                raise ValidationError("Schedule key belongs to a different request.")
            return existing
        return JobSchedule.objects.create(
            organization=project.organization, project=project, actor=actor,
            handler="diagnostic_probe", input_snapshot=data, interval_minutes=interval_minutes,
            idempotency_key=idempotency_key,
        )


def set_schedule_enabled(*, schedule, actor, enabled):
    if not settings.DEBUG or type(enabled) is not bool or schedule.handler != "diagnostic_probe":
        raise ValidationError("Choose an enabled or paused schedule state.")
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=schedule.organization_id)
        schedule = JobSchedule.objects.select_for_update().select_related("project", "actor").get(pk=schedule.pk)
        require_project_action(project=schedule.project, user=actor, action=Action.LAUNCH_JOB)
        if enabled:
            require_project_action(project=schedule.project, user=schedule.actor, action=Action.LAUNCH_JOB)
            schedule.next_run_at = timezone.now() + timedelta(minutes=schedule.interval_minutes)
        schedule.enabled = enabled
        schedule.last_error_category = ""
        schedule.save(update_fields=["enabled", "next_run_at", "last_error_category"])
    return schedule


def run_due_schedules(*, limit=100, now=None):
    if not settings.DEBUG:
        return 0
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValidationError("Invalid due-run limit.")
    now = now or timezone.now()
    candidates = list(JobSchedule.objects.filter(handler="diagnostic_probe", enabled=True, next_run_at__lte=now)
                      .order_by("next_run_at", "pk").values_list("pk", "organization_id")[:limit])
    created = 0
    for schedule_id, organization_id in candidates:
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=organization_id)
            schedule = JobSchedule.objects.select_for_update().select_related("project", "actor").get(pk=schedule_id)
            if not schedule.enabled or schedule.next_run_at is None or schedule.next_run_at > now:
                continue
            interval = timedelta(minutes=schedule.interval_minutes)
            missed = max(0, (now - schedule.next_run_at) // interval)
            occurrence = schedule.next_run_at + missed * interval
            schedule.next_run_at = now + interval  # One current occurrence; no backlog flood.
            schedule.skipped_occurrences = min(1_000_000, schedule.skipped_occurrences + missed)
            try:
                require_project_action(project=schedule.project, user=schedule.actor, action=Action.LAUNCH_JOB)
                queue_job(project=schedule.project, actor=schedule.actor, handler=schedule.handler,
                          input_snapshot=schedule.input_snapshot, schedule=schedule, scheduled_for=occurrence,
                          idempotency_key=f"schedule-{schedule.pk}-{int(occurrence.timestamp())}")
            except PermissionDenied:
                schedule.enabled = False
                schedule.last_error_category = "access_revoked"
            except UsageLimitError as error:
                schedule.last_error_category = error.category
                if error.category in {"trial_unavailable", "trial_units_exhausted"}:
                    schedule.enabled = False
            else:
                schedule.last_run_at = occurrence
                schedule.last_error_category = ""
                created += 1
            schedule.save(update_fields=["enabled", "next_run_at", "last_run_at", "skipped_occurrences", "last_error_category"])
    return created
