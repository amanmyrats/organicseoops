from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from tenancy.models import AuditEvent, AuditEventType, Organization, Project
from tenancy.services import Action, require_project_action

from .models import ImportRun, IntegrationCapability, IntegrationConnection, SyncCursor, property_matches_project


class UnsupportedIntegrationCapability(ValidationError):
    pass


class SyncCursorConflict(Exception):
    pass


def create_connection(
    *, project, user, provider, external_property_id, capabilities, available_dimensions,
    source_semantics, source_semantics_version, timezone="UTC", currency="", backfill_limit_days=90,
):
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().select_related("organization").get(
            pk=project.pk,
            organization_id=project.organization_id,
        )
        require_project_action(project=project, user=user, action=Action.MANAGE_PROJECT)
        connection = IntegrationConnection(
            project=project,
            provider=provider,
            external_property_id=external_property_id,
            capabilities=capabilities,
            available_dimensions=available_dimensions,
            source_semantics=source_semantics,
            source_semantics_version=source_semantics_version,
            timezone=timezone,
            currency=currency,
            backfill_limit_days=backfill_limit_days,
        )
        connection.save()
    return connection


def require_connection_capability(connection, capability, *, dimensions=()):
    connection = IntegrationConnection.objects.select_related("project").filter(
        pk=connection.pk,
        state=IntegrationConnection.State.ACTIVE,
    ).first()
    if connection is None or not property_matches_project(connection) or capability not in connection.capabilities:
        raise UnsupportedIntegrationCapability("This connection does not support the requested operation.")
    if (
        type(dimensions) not in {list, tuple, set, frozenset}
        or any(not isinstance(item, str) for item in dimensions)
        or not set(dimensions) <= set(connection.available_dimensions)
    ):
        raise UnsupportedIntegrationCapability("This connection does not support the requested observation grain.")
    return connection


def set_csv_source_state(*, connection, user, active, request_id=""):
    if type(active) is not bool:
        raise ValidationError("Choose whether the CSV source is enabled.")
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=connection.project.organization_id)
        project = Project.objects.select_for_update().get(pk=connection.project_id, organization=organization)
        require_project_action(project=project, user=user, action=Action.MANAGE_PROJECT)
        connection = IntegrationConnection.objects.select_for_update().get(pk=connection.pk, project=project)
        if IntegrationCapability.CSV_IMPORT not in connection.capabilities or connection.credential_reference is not None:
            raise UnsupportedIntegrationCapability("Only local CSV source records may be changed here.")
        if connection.state == IntegrationConnection.State.UNAVAILABLE:
            raise UnsupportedIntegrationCapability("This source cannot be re-enabled locally.")
        if active and not property_matches_project(connection):
            raise UnsupportedIntegrationCapability("This source no longer matches the project's exact origin scope.")
        target = IntegrationConnection.State.ACTIVE if active else IntegrationConnection.State.DISCONNECTED
        if connection.state != target:
            previous = connection.state
            IntegrationConnection.objects.filter(pk=connection.pk).update(state=target, updated_at=timezone.now())
            connection.refresh_from_db()
            AuditEvent.objects.create(
                organization=organization, project=project, actor=user,
                event_type=AuditEventType.SOURCE_ENABLED if active else AuditEventType.SOURCE_DISABLED,
                details={"connection_id": connection.pk, "provider": connection.provider,
                         "previous_state": previous, "new_state": target}, request_id=request_id,
            )
    return connection


def record_import_run(
    *, connection, job, source_artifact, source_format, source_checksum, date_start, date_end,
    observation_dimensions, source_timezone, source_currency="", coverage_state, coverage,
    fresh_through=None, status, rows_seen=0, rows_imported=0, row_errors=0,
):
    from jobs.models import Artifact, JobRun

    with transaction.atomic():
        connection = IntegrationConnection.objects.select_for_update().select_related("project").get(pk=connection.pk)
        job = JobRun.objects.select_for_update().select_related("actor").get(pk=job.pk)
        source_artifact = Artifact.objects.select_for_update().get(pk=source_artifact.pk)
        run = ImportRun(
            project=connection.project,
            connection=connection,
            job=job,
            source_artifact=source_artifact,
            source_format=source_format,
            source_checksum=source_checksum,
            provider=connection.provider,
            external_property_id=connection.external_property_id,
            source_semantics=connection.source_semantics,
            source_semantics_version=connection.source_semantics_version,
            date_start=date_start,
            date_end=date_end,
            observation_dimensions=observation_dimensions,
            source_timezone=source_timezone,
            source_currency=source_currency,
            coverage_state=coverage_state,
            coverage=coverage,
            fresh_through=fresh_through,
            status=status,
            rows_seen=rows_seen,
            rows_imported=rows_imported,
            row_errors=row_errors,
        )
        run.full_clean(validate_unique=False, validate_constraints=False)
        existing = ImportRun.objects.select_for_update().filter(job=job).first()
        if existing is not None:
            fields = (
                "project_id", "connection_id", "job_id", "source_artifact_id", "source_format", "source_checksum",
                "provider", "external_property_id", "source_semantics", "source_semantics_version", "date_start",
                "date_end", "observation_dimensions", "source_timezone", "source_currency", "coverage_state",
                "coverage", "fresh_through", "status", "rows_seen", "rows_imported", "row_errors",
            )
            if all(getattr(existing, field) == getattr(run, field) for field in fields):
                return existing
            raise ValidationError("Import job already has different provenance.")
        require_project_action(project=connection.project, user=job.actor, action=Action.LAUNCH_JOB)
        require_connection_capability(connection, "csv_import", dimensions=observation_dimensions)
        run.save()
    return run


def update_sync_cursor(*, connection, user, expected_revision, **changes):
    mutable = {
        "status", "position", "coverage_start", "coverage_end", "fresh_through", "quota_state",
        "retry_after", "error_category", "last_attempt_at", "last_success_at",
    }
    if type(expected_revision) is not int or expected_revision < 0 or not changes or set(changes) - mutable:
        raise ValidationError("Check the sync cursor fields.")
    with transaction.atomic():
        connection = IntegrationConnection.objects.select_for_update().select_related("project__organization").get(
            pk=connection.pk
        )
        require_project_action(project=connection.project, user=user, action=Action.MANAGE_PROJECT)
        require_connection_capability(connection, "api_sync")
        cursor, _ = SyncCursor.objects.select_for_update().get_or_create(
            connection=connection,
            defaults={"project": connection.project},
        )
        if cursor.project_id != connection.project_id:
            raise PermissionDenied
        if cursor.revision != expected_revision:
            raise SyncCursorConflict
        previous_status = cursor.status
        next_status = changes.get("status", previous_status)
        legal = {
            SyncCursor.Status.IDLE: {SyncCursor.Status.RUNNING, SyncCursor.Status.UNAVAILABLE},
            SyncCursor.Status.RUNNING: {
                SyncCursor.Status.WAITING_PROVIDER, SyncCursor.Status.SUCCEEDED,
                SyncCursor.Status.PARTIALLY_SUCCEEDED, SyncCursor.Status.FAILED, SyncCursor.Status.UNAVAILABLE,
            },
            SyncCursor.Status.WAITING_PROVIDER: {
                SyncCursor.Status.RUNNING, SyncCursor.Status.FAILED, SyncCursor.Status.UNAVAILABLE,
            },
            SyncCursor.Status.SUCCEEDED: {SyncCursor.Status.RUNNING},
            SyncCursor.Status.PARTIALLY_SUCCEEDED: {SyncCursor.Status.RUNNING},
            SyncCursor.Status.FAILED: {SyncCursor.Status.RUNNING},
            SyncCursor.Status.UNAVAILABLE: {SyncCursor.Status.RUNNING},
        }
        if next_status != previous_status and next_status not in legal[previous_status]:
            raise ValidationError("Invalid sync cursor status transition.")
        if next_status in {SyncCursor.Status.RUNNING, SyncCursor.Status.SUCCEEDED}:
            changes["error_category"] = ""
            changes["retry_after"] = None
        for field, value in changes.items():
            setattr(cursor, field, value)
        cursor.revision += 1
        cursor.save()
    return cursor
