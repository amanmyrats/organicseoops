"""Owner-only captured private ZIP parts with explicit format-specific authority."""
import re
from datetime import timedelta
from hashlib import sha256
from tempfile import SpooledTemporaryFile

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from kombu.exceptions import OperationalError

from config.artifacts import (ArtifactNotFound, ArtifactStorageError, ArtifactValidationError,
                              read_private_artifact, save_private_artifact)

from .artifacts import (delete_failed_organization_export_batch, failed_export_versions_remain,
                        organization_export_scope)
from .customer_export import complete_bounded_customer_archive
from .models import (AuditEvent, AuditEventType, Organization, OrganizationCustomerExport,
                     OrganizationCustomerExportPart)
from .services import Action, require_organization_action


def reserve_bounded_customer_snapshot(*, organization, actor, request_key, format="bounded-zip-v1"):
    if type(request_key) is not str or not re.fullmatch(r"[0-9a-f]{32}", request_key):
        raise ValidationError("Choose one unique private export request.")
    if type(format) is not str or format not in {"bounded-zip-v1", "source-parts-v2", "coherent-parts-v3"}:
        raise ValidationError("Choose a supported private export format.")
    from .customer_export_policy import reviewed_copy_lifetime
    reviewed_copy_lifetime()
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization.pk)
        require_organization_action(organization=organization, user=actor, action=Action.ORGANIZATION_EXPORT)
        existing = OrganizationCustomerExport.objects.filter(organization=organization, request_key=request_key).first()
        if existing:
            if existing.actor_id != actor.pk or existing.format != format or existing.state == existing.State.FAILED:
                raise ValidationError("Export request needs review; do not replay private storage writes.")
            return existing
        if OrganizationCustomerExport.objects.filter(organization=organization).count() >= 3:
            raise ValidationError("Organization reached its private snapshot limit.")
        if settings.ARTIFACT_MAX_BYTES < 4 * 1024 * 1024 or "application/zip" not in settings.ARTIFACT_ALLOWED_CONTENT_TYPES:
            raise ValidationError("Private ZIP part storage is not available.")
        snapshot = OrganizationCustomerExport.objects.create(organization=organization, actor=actor,
                                                               request_key=request_key, format=format)
        from .tasks import capture_customer_snapshot_task
        def dispatch():
            try:
                capture_customer_snapshot_task.apply_async(
                    args=[snapshot.pk], queue="audit", task_id=f"customer-export-{snapshot.pk}", retry=False)
            except (OperationalError, OSError, TimeoutError):
                pass  # PREPARING remains visible; stale recovery fails closed without replay.
        transaction.on_commit(dispatch)
        return snapshot


def capture_reserved_customer_snapshot(snapshot_id):
    if OrganizationCustomerExport.objects.filter(pk=snapshot_id, format="coherent-parts-v3").exists():
        from .customer_coherent_snapshot import capture_coherent_customer_snapshot
        return capture_coherent_customer_snapshot(snapshot_id)
    if OrganizationCustomerExport.objects.filter(pk=snapshot_id, format="source-parts-v2").exists():
        from .customer_source_parts import capture_source_stage
        return capture_source_stage(snapshot_id, 0)
    organization_id = OrganizationCustomerExport.objects.filter(pk=snapshot_id, format="bounded-zip-v1").values_list(
        "organization_id", flat=True).first()
    if organization_id is None:
        return False
    try:
        with SpooledTemporaryFile(max_size=8 * 1024 * 1024) as spool:
            with transaction.atomic():
                organization = Organization.objects.select_for_update().get(pk=organization_id)
                snapshot = OrganizationCustomerExport.objects.select_for_update().select_related("actor").get(
                    pk=snapshot_id, organization=organization)
                if snapshot.state != snapshot.State.PREPARING or snapshot.last_progress_at is not None:
                    return False  # Unknown redelivery cannot repeat a private write.
                OrganizationCustomerExport.objects.filter(pk=snapshot.pk, state=snapshot.State.PREPARING).update(
                    last_progress_at=timezone.now())
                require_organization_action(organization=organization, user=snapshot.actor,
                                            action=Action.ORGANIZATION_EXPORT)
                data = complete_bounded_customer_archive(organization=organization, actor=snapshot.actor,
                                                         output=spool)
                OrganizationCustomerExport.objects.filter(pk=snapshot.pk, state=snapshot.State.PREPARING).update(
                    last_progress_at=timezone.now())
            _write_bounded_snapshot(snapshot=snapshot, organization=organization, actor=snapshot.actor, data=data)
            return True
    except Exception:
        OrganizationCustomerExport.objects.filter(pk=snapshot_id, state=OrganizationCustomerExport.State.PREPARING).update(
            state=OrganizationCustomerExport.State.FAILED)
        return False


def _write_bounded_snapshot(*, snapshot, organization, actor, data):
    part_size = min(settings.ARTIFACT_MAX_BYTES, 8 * 1024 * 1024)
    data.seek(0, 2)
    size = data.tell()
    data.seek(0)
    original = sha256()
    while block := data.read(1024 * 1024):
        original.update(block)
    data.seek(0)
    try:
        for position in range((size + part_size - 1) // part_size):
            chunk = data.read(part_size)
            if not chunk:
                raise ArtifactStorageError("Private export capture is incomplete.")
            # Hold the same organization lock as closure until the storage write
            # and its metadata commit; never write a later part after closure.
            with transaction.atomic():
                organization = Organization.objects.select_for_update().get(pk=organization.pk)
                require_organization_action(organization=organization, user=actor, action=Action.ORGANIZATION_EXPORT)
                if not OrganizationCustomerExport.objects.filter(pk=snapshot.pk, organization=organization,
                                                                 state=snapshot.State.PREPARING).exists():
                    raise ValidationError("Export capture requires review.")
                key = save_private_artifact(scope=f"{organization_export_scope(organization)}/{snapshot.pk}",
                                            content=chunk, content_type="application/zip")
                OrganizationCustomerExportPart.objects.create(export=snapshot, position=position,
                    storage_key=key, size_bytes=len(chunk), content_sha256=sha256(chunk).hexdigest())
                OrganizationCustomerExport.objects.filter(pk=snapshot.pk, state=snapshot.State.PREPARING).update(
                    last_progress_at=timezone.now())
        with transaction.atomic():
            organization = Organization.objects.select_for_update().get(pk=organization.pk)
            require_organization_action(organization=organization, user=actor, action=Action.ORGANIZATION_EXPORT)
            snapshot = OrganizationCustomerExport.objects.select_for_update().get(pk=snapshot.pk,
                                                                                   organization=organization)
            if snapshot.state != snapshot.State.PREPARING:
                raise ValidationError("Export capture requires review.")
            verified = sha256()
            verified_bytes = 0
            parts = list(snapshot.parts.order_by("position"))
            if not parts or len(parts) != (size + part_size - 1) // part_size:
                raise ArtifactStorageError("Private export capture is incomplete.")
            for position, part in enumerate(parts):
                if (part.position != position or not part.storage_key.startswith(
                    f"{organization_export_scope(organization)}/{snapshot.pk}/")):
                    raise ArtifactStorageError("Private export capture is incomplete.")
                captured = read_private_artifact(part.storage_key)
                if len(captured) != part.size_bytes or sha256(captured).hexdigest() != part.content_sha256:
                    raise ArtifactStorageError("Private export part integrity check failed.")
                verified.update(captured)
                verified_bytes += len(captured)
            if verified_bytes != size or verified.digest() != original.digest():
                raise ArtifactStorageError("Private export capture integrity check failed.")
            snapshot.state = snapshot.State.READY
            snapshot.size_bytes = size
            snapshot.content_sha256 = original.hexdigest()
            snapshot.completed_at = timezone.now()
            snapshot.save(update_fields=["state", "size_bytes", "content_sha256", "completed_at"])
            AuditEvent.objects.create(organization=organization, actor=actor,
                event_type=AuditEventType.ORGANIZATION_EXPORT_ACCESSED,
                details={"kind": "private_snapshot", "export_id": snapshot.pk,
                         "parts": snapshot.parts.count(), "size_bytes": snapshot.size_bytes})
            return snapshot
    except Exception:
        OrganizationCustomerExport.objects.filter(pk=snapshot.pk, state=snapshot.State.PREPARING).update(
            state=snapshot.State.FAILED)
        raise ArtifactStorageError("Private export capture is incomplete and requires review.") from None


def current_customer_snapshot(*, organization, actor, snapshot_id):
    if OrganizationCustomerExport.objects.filter(pk=snapshot_id, organization=organization,
                                                 format="coherent-parts-v3").exists():
        from .customer_coherent_snapshot import current_coherent_customer_snapshot
        return current_coherent_customer_snapshot(organization=organization, actor=actor, snapshot_id=snapshot_id)
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization.pk)
        require_organization_action(organization=organization, user=actor, action=Action.ORGANIZATION_EXPORT)
        snapshot = OrganizationCustomerExport.objects.filter(pk=snapshot_id, organization=organization,
                                                              format__in=["bounded-zip-v1", "source-parts-v2"],
                                                              state=OrganizationCustomerExport.State.READY).first()
        if snapshot is None or snapshot.delivery_state != snapshot.State.READY:
            raise PermissionDenied
        # Stored captures cannot bypass current logfile source/actor authority.
        from jobs.bot_log_import import HANDLER, source_current
        from jobs.models import JobRun
        for job in JobRun.objects.filter(organization=organization, handler=HANDLER).iterator():
            if not source_current(job):
                raise PermissionDenied
        return snapshot


def private_snapshot_part(*, organization, actor, snapshot_id, position):
    if type(position) is not int or position < 0:
        raise PermissionDenied
    if OrganizationCustomerExport.objects.filter(pk=snapshot_id, organization=organization,
                                                 format="coherent-parts-v3").exists():
        from .customer_coherent_snapshot import private_coherent_snapshot_part
        return private_coherent_snapshot_part(organization=organization, actor=actor,
                                              snapshot_id=snapshot_id, position=position)
    with transaction.atomic():
        snapshot = current_customer_snapshot(organization=organization, actor=actor, snapshot_id=snapshot_id)
        return _read_snapshot_part(snapshot, actor, position)


def _read_snapshot_part(snapshot, actor, position):
    part = OrganizationCustomerExportPart.objects.filter(export=snapshot, position=position).first()
    if part is None or not part.storage_key.startswith(
        f"{organization_export_scope(snapshot.organization)}/{snapshot.pk}/"):
        raise PermissionDenied
    try:
        data = read_private_artifact(part.storage_key)
    except (ArtifactNotFound, ArtifactStorageError, ArtifactValidationError):
        raise ArtifactStorageError("Private export part is unavailable.") from None
    if len(data) != part.size_bytes or sha256(data).hexdigest() != part.content_sha256:
        raise ArtifactStorageError("Private export part integrity check failed.")
    if snapshot.delivery_state != snapshot.State.READY:
        raise PermissionDenied
    AuditEvent.objects.create(organization=snapshot.organization, actor=actor,
        event_type=AuditEventType.ORGANIZATION_EXPORT_ACCESSED,
        details={"kind": "private_snapshot_part", "export_id": snapshot.pk,
                 "position": position, "size_bytes": part.size_bytes})
    return data, part.content_sha256


def recover_stale_customer_snapshots(*, now=None, limit=20):
    now = now or timezone.now()
    cutoff = now - timedelta(minutes=15)
    stale = Q(last_progress_at__lte=cutoff) | Q(last_progress_at__isnull=True, created_at__lte=cutoff)
    ids = list(OrganizationCustomerExport.objects.filter(
        state=OrganizationCustomerExport.State.PREPARING).filter(stale).order_by(
        "created_at", "pk").values_list("pk", flat=True)[:limit])
    recovered = 0
    for snapshot_id in ids:
        organization_id = OrganizationCustomerExport.objects.filter(pk=snapshot_id).values_list(
            "organization_id", flat=True).first()
        if organization_id is None:
            continue
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=organization_id)
            snapshot = OrganizationCustomerExport.objects.select_for_update().filter(pk=snapshot_id,
                organization_id=organization_id, state=OrganizationCustomerExport.State.PREPARING).filter(stale).first()
            if snapshot:
                if snapshot.format == "source-parts-v2" and not snapshot.progress.get("in_flight"):
                    # Committed stages are safe to redispatch; an interrupted
                    # unknown write still fails closed below.
                    from .customer_source_parts import dispatch_source_stage
                    OrganizationCustomerExport.objects.filter(pk=snapshot.pk).update(last_progress_at=now)
                    transaction.on_commit(lambda pk=snapshot.pk, step=snapshot.progress.get("step", 0):
                                          dispatch_source_stage(pk, step))
                    recovered += 1
                    continue
                snapshot.state = snapshot.State.FAILED
                if snapshot.format == "coherent-parts-v3" and not snapshot.progress.get("write_in_flight", bool(snapshot.progress)):
                    snapshot.progress = {**snapshot.progress, "in_flight": False}
                snapshot.save(update_fields=["state", "progress"])
                recovered += 1
    return recovered


def discard_failed_customer_snapshot(*, organization, actor, snapshot_id, storage=None):
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization.pk)
        require_organization_action(organization=organization, user=actor, action=Action.ORGANIZATION_EXPORT)
        snapshot = OrganizationCustomerExport.objects.select_for_update().filter(
            pk=snapshot_id, organization=organization, state=OrganizationCustomerExport.State.FAILED).first()
        if snapshot is None:
            raise PermissionDenied
        removed, complete = delete_failed_organization_export_batch(
            organization=organization, actor=actor, snapshot_id=snapshot.pk, storage=storage)
        if not complete or failed_export_versions_remain(organization=organization, snapshot_id=snapshot.pk,
                                                       storage=storage):
            return "cleanup_pending", removed
        AuditEvent.objects.create(organization=organization, actor=actor,
            event_type=AuditEventType.ORGANIZATION_EXPORT_ACCESSED,
            details={"kind": "failed_capture_discard", "export_id": snapshot.pk, "parts": snapshot.parts.count()})
        snapshot.delete()
        return "discarded", removed
