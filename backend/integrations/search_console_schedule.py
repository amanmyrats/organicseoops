from datetime import timedelta
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from jobs.models import JobRun, JobSchedule, JobStatus
from jobs.usage import UsageLimitError, require_billable_access
from providers.google_app import google_oauth_client
from tenancy.models import Organization, Project
from tenancy.services import Action, require_project_action

from .google_tokens import GoogleTokenError
from .models import GoogleOAuthGrant, IntegrationConnection, SearchConsoleBackfill, SyncCursor
from .search_console_backfill import _source_config
from .search_console_sync import _source, queue_search_console_sync


def _day(now):
    return now.astimezone(ZoneInfo("America/Los_Angeles")).date() - timedelta(days=3)


def _validate_source(*, project, organization, connection, grant, dimension, day):
    if type(dimension) is not str or dimension not in {"date", "query", "page"}:
        raise ValidationError("Choose one supported scheduled report dimension.")
    _source(project=project, organization=organization,
            data={"connection_id": connection.pk, "grant_id": grant.pk,
                  "day": day.isoformat(), "dimensions": [dimension]},
            config=_source_config(project, connection, grant))


def create_search_console_schedule(*, project, actor, connection, grant, dimension, idempotency_key):
    if (type(idempotency_key) is not str or not 1 <= len(idempotency_key) <= 64
        or not all(char.isascii() and (char.isalnum() or char in "._-") for char in idempotency_key)):
        raise ValidationError("Choose a bounded schedule key.")
    google_oauth_client(require_redirect=False)
    with transaction.atomic():
        org = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=org)
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        require_billable_access(organization=org)
        connection = IntegrationConnection.objects.select_for_update().get(pk=connection.pk, project=project)
        grant = GoogleOAuthGrant.objects.select_for_update().get(pk=grant.pk, project=project, organization=org)
        _validate_source(project=project, organization=org, connection=connection, grant=grant,
                         dimension=dimension, day=_day(timezone.now()))
        existing = JobSchedule.objects.filter(project=project, handler="sync_search_console",
                                              input_snapshot__connection_id=connection.pk).first()
        if existing:
            if (existing.actor_id != actor.pk or existing.input_snapshot != {
                "connection_id": connection.pk, "grant_id": grant.pk, "dimension": dimension,
            } or existing.idempotency_key != idempotency_key):
                raise ValidationError("This source already has a different schedule.")
            return existing
        return JobSchedule.objects.create(organization=org, project=project, actor=actor,
            handler="sync_search_console", input_snapshot={"connection_id": connection.pk,
            "grant_id": grant.pk, "dimension": dimension}, idempotency_key=idempotency_key)


def set_search_console_schedule_enabled(*, project, actor, connection, schedule_id, enabled):
    if type(enabled) is not bool:
        raise ValidationError("Choose a schedule state.")
    with transaction.atomic():
        org = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=org)
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        schedule = JobSchedule.objects.select_for_update(of=("self",)).select_related("actor").filter(
            pk=schedule_id, project=project, handler="sync_search_console",
            input_snapshot__connection_id=connection.pk).first()
        if schedule is None:
            raise ValidationError("Schedule is unavailable.")
        if enabled:
            require_project_action(project=project, user=schedule.actor, action=Action.MANAGE_PROJECT)
            require_billable_access(organization=org)
            grant = GoogleOAuthGrant.objects.filter(pk=schedule.input_snapshot.get("grant_id"), project=project,
                                                    organization=org).first()
            if grant is None:
                raise ValidationError("Source grant is unavailable.")
            google_oauth_client(require_redirect=False)
            _validate_source(project=project, organization=org, connection=connection, grant=grant,
                             dimension=schedule.input_snapshot.get("dimension"), day=_day(timezone.now()))
            schedule.next_run_at = timezone.now() + timedelta(days=1)
        schedule.enabled = enabled
        schedule.last_error_category = ""
        schedule.save(update_fields=["enabled", "last_error_category", "next_run_at"])
        return schedule


def run_due_search_console_schedules(*, now=None, limit=50):
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValidationError("Choose a bounded schedule limit.")
    now = now or timezone.now()
    ids = list(JobSchedule.objects.filter(handler="sync_search_console", enabled=True, next_run_at__lte=now)
               .order_by("next_run_at", "pk").values_list("pk", "organization_id")[:limit])
    created = 0
    for schedule_id, org_id in ids:
        with transaction.atomic():
            org = Organization.objects.select_for_update().get(pk=org_id)
            schedule = (JobSchedule.objects.select_for_update(of=("self",))
                        .select_related("project", "actor").get(pk=schedule_id, organization=org))
            if not schedule.enabled or schedule.next_run_at is None or schedule.next_run_at > now:
                continue
            occurrence = schedule.next_run_at
            missed = max(0, (now - occurrence) // timedelta(days=1))
            schedule.skipped_occurrences = min(1_000_000, schedule.skipped_occurrences + missed)
            schedule.next_run_at = now + timedelta(days=1)  # One current day; no catch-up flood.
            details = schedule.input_snapshot
            connection = IntegrationConnection.objects.filter(pk=details.get("connection_id"), project=schedule.project).first()
            grant = GoogleOAuthGrant.objects.filter(pk=details.get("grant_id"), project=schedule.project,
                                                   organization=org).first()
            previous = JobRun.objects.filter(schedule=schedule).order_by("-scheduled_for", "-pk").first()
            if previous and previous.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                schedule.last_error_category = "source_busy"
                schedule.next_run_at = now + timedelta(hours=1)
            elif previous and previous.status != JobStatus.SUCCEEDED:
                schedule.enabled = False
                schedule.last_error_category = previous.error_category or previous.dispatch_error or "request_outcome_unknown"
            elif previous and previous.input_snapshot.get("day") == _day(now).isoformat():
                schedule.last_error_category = ""
            elif connection is None or grant is None:
                schedule.enabled = False
                schedule.last_error_category = "source_revoked"
            elif SearchConsoleBackfill.objects.filter(connection=connection, status=SearchConsoleBackfill.Status.RUNNING).exists():
                schedule.last_error_category = "source_busy"
                schedule.next_run_at = now + timedelta(hours=1)
            else:
                cursor = SyncCursor.objects.filter(project=schedule.project, connection=connection).first()
                if cursor and cursor.retry_after and cursor.retry_after > now:
                    schedule.last_error_category = "quota_limited"
                    schedule.next_run_at = max(cursor.retry_after, now + timedelta(hours=1))
                elif JobRun.objects.filter(project=schedule.project, handler="sync_search_console",
                    input_snapshot__connection_id=connection.pk,
                    status__in=[JobStatus.QUEUED, JobStatus.RUNNING]).exists():
                    schedule.last_error_category = "source_busy"
                    schedule.next_run_at = now + timedelta(hours=1)
                else:
                    try:
                        require_project_action(project=schedule.project, user=schedule.actor, action=Action.MANAGE_PROJECT)
                        job = queue_search_console_sync(project=schedule.project, actor=schedule.actor,
                            connection=connection, grant=grant, day=_day(now),
                            dimensions=[details.get("dimension")],
                            idempotency_key=f"schedule-{schedule.pk}-{_day(now).toordinal()}",
                            schedule=schedule, scheduled_for=occurrence)
                    except UsageLimitError as exc:
                        schedule.last_error_category = exc.category
                        if exc.category in {"trial_unavailable", "trial_units_exhausted",
                                            "paid_unavailable", "paid_units_exhausted", "billing_review_hold"}:
                            schedule.enabled = False
                        else:
                            schedule.next_run_at = now + timedelta(hours=1)
                    except (PermissionDenied, ValidationError, GoogleTokenError):
                        schedule.enabled = False
                        schedule.last_error_category = "source_revoked"
                    else:
                        schedule.last_run_at = occurrence
                        schedule.last_error_category = ""
                        created += 1
            schedule.save(update_fields=["enabled", "next_run_at", "last_run_at", "skipped_occurrences", "last_error_category"])
    return created
