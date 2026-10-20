"""Bounded expiry cleanup; storage uncertainty keeps metadata and its occupied slot."""
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from config.artifacts import ArtifactStorageError, ArtifactValidationError
from .artifacts import delete_expired_organization_export_batch, failed_export_versions_remain
from .models import AuditEvent, AuditEventType, Organization, OrganizationCustomerExport


def purge_expired_customer_copies(*, limit=20, storage=None):
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("Choose a bounded expired-copy batch.")
    now = timezone.now()
    due = OrganizationCustomerExport.objects.filter(state=OrganizationCustomerExport.State.READY,
                                                    expires_at__lte=now)
    rows = list(due.order_by(F("last_progress_at").asc(nulls_first=True), "pk").values_list(
        "pk", "organization_id")[:limit])
    result = {"removed": 0, "pending": 0, "failed": 0}
    for snapshot_id, organization_id in rows:
        with transaction.atomic():
            organization = Organization.objects.select_for_update().filter(pk=organization_id).first()
            snapshot = due.select_for_update().filter(pk=snapshot_id, organization=organization).first()
            if snapshot is None:
                continue
            # Commit fairness even if storage fails; do not strand later expired copies.
            OrganizationCustomerExport.objects.filter(pk=snapshot.pk).update(last_progress_at=now)
            try:
                _, complete = delete_expired_organization_export_batch(
                    organization=organization, snapshot_id=snapshot.pk, storage=storage)
                if not complete or failed_export_versions_remain(
                    organization=organization, snapshot_id=snapshot.pk, storage=storage):
                    result["pending"] += 1
                    continue
            except (PermissionDenied, ArtifactStorageError, ArtifactValidationError):
                result["failed"] += 1
                continue
            AuditEvent.objects.create(organization=organization,
                event_type=AuditEventType.ORGANIZATION_EXPORT_ACCESSED,
                details={"kind": "expired_copy_removed", "export_id": snapshot.pk,
                         "policy_reference": snapshot.expiry_policy_reference})
            snapshot.delete()
            result["removed"] += 1
    return result
