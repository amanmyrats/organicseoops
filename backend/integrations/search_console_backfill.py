from datetime import date, timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from jobs.models import JobRun, JobStatus
from jobs.services import cancel_job
from jobs.usage import UsageLimitError, require_billable_access
from providers.google_app import google_oauth_client
from tenancy.models import Organization, Project
from tenancy.services import Action, require_project_action

from .google_tokens import GoogleTokenError
from .models import GoogleOAuthGrant, IntegrationConnection, SearchConsoleBackfill, SyncCursor, verified_domain_origins
from .search_console_sync import _source, queue_search_console_sync, validate_sync_input


def _source_config(project, connection, grant):
    config = {"grant_revision": grant.revision, "property_id": connection.external_property_id}
    if connection.external_property_id.startswith("sc-domain:"):
        config.update({"approved_origins": sorted(set(grant.selected_origins) & set(verified_domain_origins(
            project, connection.external_property_id))), "scope_strategy": "domain-page-v1"})
    return config


def queue_search_console_backfill(*, project, actor, connection, grant, start_day, end_day, dimension, idempotency_key):
    if (type(start_day) is not date or type(end_day) is not date or not 0 <= (end_day - start_day).days < 7
        or type(dimension) is not str or dimension not in {"date", "query", "page"}
        or type(idempotency_key) is not str or not 1 <= len(idempotency_key) <= 64
        or not all(char.isascii() and (char.isalnum() or char in "._-") for char in idempotency_key)):
        raise ValidationError("Choose a bounded finalized Search Console backfill.")
    for day in (start_day, end_day):
        validate_sync_input({"connection_id": connection.pk, "grant_id": grant.pk,
                             "day": day.isoformat(), "dimensions": [dimension]})
    google_oauth_client(require_redirect=False)
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        require_billable_access(organization=organization)
        connection = IntegrationConnection.objects.select_for_update().get(pk=connection.pk, project=project)
        grant = GoogleOAuthGrant.objects.select_for_update().get(pk=grant.pk, project=project, organization=organization)
        _source(project=project, organization=organization,
                data={"connection_id": connection.pk, "grant_id": grant.pk, "day": start_day.isoformat(),
                      "dimensions": [dimension]}, config=_source_config(project, connection, grant))
        existing = SearchConsoleBackfill.objects.filter(project=project, idempotency_key=idempotency_key).first()
        if existing:
            if (existing.actor_id, existing.connection_id, existing.grant_id, existing.start_day,
                existing.end_day, existing.dimension) != (actor.pk, connection.pk, grant.pk,
                                                              start_day, end_day, dimension):
                raise ValidationError("Backfill key belongs to another request.")
            return existing
        cursor = SyncCursor.objects.filter(project=project, connection=connection).first()
        if cursor and cursor.retry_after and cursor.retry_after > timezone.now():
            raise ValidationError("This Search Console source is temporarily rate limited.")
        try:
            return SearchConsoleBackfill.objects.create(
                organization=organization, project=project, connection=connection, grant=grant, actor=actor,
                start_day=start_day, end_day=end_day, next_day=start_day, dimension=dimension,
                idempotency_key=idempotency_key,
            )
        except IntegrityError:
            raise ValidationError("This source has an active backfill.") from None


def advance_search_console_backfills(*, limit=50):
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValidationError("Choose a bounded backfill scheduler limit.")
    candidates = list(SearchConsoleBackfill.objects.filter(status=SearchConsoleBackfill.Status.RUNNING)
                      .order_by("pk").values_list("pk", "organization_id")[:limit])
    advanced = 0
    for backfill_id, organization_id in candidates:
        with transaction.atomic():
            organization = Organization.objects.select_for_update().get(pk=organization_id)
            batch = (SearchConsoleBackfill.objects.select_for_update(of=("self",))
                     .select_related("project", "actor", "connection", "grant", "current_job")
                     .get(pk=backfill_id, organization=organization))
            if batch.status != batch.Status.RUNNING:
                continue
            if batch.current_job_id:
                job = batch.current_job
                if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                    continue
                if job.status != JobStatus.SUCCEEDED:
                    batch.status = batch.Status.PAUSED
                    batch.error_category = job.error_category or job.dispatch_error or "source_unavailable"
                    batch.save(update_fields=["status", "error_category", "updated_at"])
                    continue
                if batch.next_day == batch.end_day:
                    batch.status = batch.Status.SUCCEEDED
                    batch.save(update_fields=["status", "updated_at"])
                    continue
                next_day = batch.next_day + timedelta(days=1)
            else:
                next_day = batch.next_day
            cursor = SyncCursor.objects.filter(connection=batch.connection, project=batch.project).first()
            if JobRun.objects.filter(project=batch.project, handler="sync_search_console",
                input_snapshot__connection_id=batch.connection_id,
                status__in=[JobStatus.QUEUED, JobStatus.RUNNING]).exists():
                continue  # Wait for other work on this source instead of producing source_busy children.
            try:
                job = queue_search_console_sync(project=batch.project, actor=batch.actor, connection=batch.connection,
                    grant=batch.grant, day=next_day, dimensions=[batch.dimension],
                    idempotency_key=f"backfill-{batch.pk}-{next_day.toordinal()}")
            except PermissionDenied:
                error = "source_revoked"
            except UsageLimitError as exc:
                error = exc.category
            except (ValidationError, GoogleTokenError, IntegrationConnection.DoesNotExist, GoogleOAuthGrant.DoesNotExist):
                error = "source_unavailable"
            else:
                batch.next_day = next_day
                batch.current_job = job
                batch.save(update_fields=["next_day", "current_job", "updated_at"])
                advanced += 1
                continue
            batch.status = batch.Status.PAUSED
            batch.error_category = error
            batch.save(update_fields=["status", "error_category", "updated_at"])
    return advanced


def pause_search_console_backfill(*, project, actor, connection, backfill_id):
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        batch = SearchConsoleBackfill.objects.select_for_update().filter(
            pk=backfill_id, project=project, connection=connection).first()
        if batch is None or batch.status == batch.Status.SUCCEEDED:
            raise ValidationError("Backfill is unavailable.")
        if batch.status == batch.Status.RUNNING:
            batch.status = batch.Status.PAUSED
            batch.error_category = "cancelled"
            batch.save(update_fields=["status", "error_category", "updated_at"])
            if batch.current_job_id and batch.current_job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                cancel_job(job=batch.current_job, actor=actor)
        return batch
