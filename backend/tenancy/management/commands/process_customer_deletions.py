"""Explicit, bounded app-host process for customer active-store retention."""
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F
from django.db.models.deletion import ProtectedError

from config.artifacts import ArtifactStorageError, ArtifactValidationError
from tenancy.deletion import (delete_customer_database_records, prepare_customer_data_deletion,
                              sweep_customer_artifact_versions)
from tenancy.models import Organization, OrganizationDeletionRun


class Command(BaseCommand):
    help = "Run bounded, resumable customer content deletion; never calls billing or OAuth providers"

    def add_arguments(self, parser):
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--limit", type=int, default=10)

    def handle(self, *args, **options):
        if not options["execute"]:
            raise CommandError("Pass --execute for an explicitly authorized retention pass")
        if not settings.PRODUCTION_APP_HOST and not settings.DEBUG:
            raise CommandError("Use the configured app host or an isolated development check")
        limit = options["limit"]
        if not 1 <= limit <= 20:
            raise CommandError("Deletion limit must be between 1 and 20")
        processed = completed = blocked = 0
        # ponytail: scan all org IDs daily; add indexed due candidates if tenant count
        # grows enough for this pass to threaten the retention deadline.
        # Attempt fewer-tried tenants first; one blocked provider cannot occupy
        # every daily slot while later eligible tenants miss their deadline.
        for organization_id in Organization.objects.order_by(
            F("deletion_run__attempts").asc(nulls_first=True), "pk").values_list(
            "pk", flat=True).iterator(chunk_size=200):
            if processed >= limit:
                break
            organization = Organization.objects.get(pk=organization_id)
            try:
                run = prepare_customer_data_deletion(organization=organization)
            except PermissionDenied:
                continue  # Not yet eligible; no customer-content mutation.
            except ValidationError:
                blocked += 1
                continue
            if run.state == run.State.COMPLETE:
                continue
            processed += 1
            try:
                if run.state in {run.State.PENDING, run.State.STORAGE_CLEARED}:
                    run = sweep_customer_artifact_versions(run=run)
                if run.state == run.State.STORAGE_CLEARED:
                    run = delete_customer_database_records(run=run)
                if run.state == run.State.COMPLETE:
                    completed += 1
                elif run.last_error_category:
                    blocked += 1
            except (PermissionDenied, ValidationError, ArtifactStorageError, ArtifactValidationError, ProtectedError):
                blocked += 1
                with transaction.atomic():
                    Organization.objects.select_for_update().get(pk=organization_id)
                    current = OrganizationDeletionRun.objects.select_for_update().get(pk=run.pk)
                    if current.state != current.State.COMPLETE:
                        current.attempts += 1
                        current.last_error_category = "retention_review_required"
                        current.save(update_fields=["attempts", "last_error_category"])
        self.stdout.write(f"retention.pass attempted={processed} completed={completed} blocked={blocked}")
