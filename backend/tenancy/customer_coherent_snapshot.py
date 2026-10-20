"""Once-only coherent customer-content capture with retained source authority."""
from contextlib import contextmanager
from hashlib import sha256
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.utils import timezone

from config.artifacts import ArtifactStorageError, read_private_artifact
from .artifacts import organization_export_scope
from .customer_coherent_parts import (CONSISTENCY, FORMAT, _current_owner,
                                      coherent_customer_content)
from .customer_source_parts import _store, descriptor, encoded
from .models import AuditEvent, AuditEventType, Organization, OrganizationCustomerExport
from .services import Action, require_organization_action


@contextmanager
def _claimed_snapshot(snapshot_id, organization_id, attempt):
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization_id)
        snapshot = OrganizationCustomerExport.objects.select_for_update().get(pk=snapshot_id, organization=organization)
        if (snapshot.state != snapshot.State.PREPARING or snapshot.format != FORMAT
            or snapshot.progress.get("attempt") != attempt or not snapshot.progress.get("in_flight")):
            raise ArtifactStorageError("Original coherent capture claim is no longer current.")
        actor = get_user_model().objects.get(pk=snapshot.actor_id)
        require_organization_action(organization=organization, user=actor, action=Action.ORGANIZATION_EXPORT)
        yield snapshot, organization, actor


def _verify_parts(snapshot, validate, *, readback):
    chain, size, count = "00" * 32, 0, 0
    scope = f"{organization_export_scope(snapshot.organization)}/{snapshot.pk}/"
    for part in snapshot.parts.order_by("position").iterator(chunk_size=50):
        if part.position != count or not part.storage_key.startswith(scope):
            raise ArtifactStorageError("Coherent capture part inventory requires review.")
        if part.source.get("logfile_window") != snapshot.progress.get("logfile_window"):
            raise ArtifactStorageError("Coherent capture source lineage requires review.")
        validate()
        if readback:
            data = read_private_artifact(part.storage_key)
            if len(data) != part.size_bytes or sha256(data).hexdigest() != part.content_sha256:
                raise ArtifactStorageError("Coherent capture part integrity check failed.")
            validate()
        chain = sha256(bytes.fromhex(chain) + encoded(descriptor(part))).hexdigest()
        count += 1
        size += part.size_bytes
    if (not count or count != snapshot.progress.get("parts") or size != snapshot.progress.get("bytes")
        or chain != snapshot.progress.get("chain")):
        raise ArtifactStorageError("Coherent capture descriptor chain requires review.")
    return size, chain


def capture_coherent_customer_snapshot(snapshot_id):
    if type(snapshot_id) is not int or snapshot_id < 1:
        return False
    if connection.in_atomic_block or not connection.get_autocommit():
        raise RuntimeError("Coherent capture must commit its claim before starting content or storage.")
    organization_id = OrganizationCustomerExport.objects.filter(pk=snapshot_id, format=FORMAT).values_list(
        "organization_id", flat=True).first()
    if organization_id is None:
        return False
    attempt = uuid4().hex
    claimed = False
    write_returned = False
    try:
        with transaction.atomic():
            organization = Organization.objects.select_for_update().get(pk=organization_id)
            snapshot = OrganizationCustomerExport.objects.select_for_update().get(pk=snapshot_id, organization=organization)
            if (snapshot.state != snapshot.State.PREPARING or snapshot.progress
                or snapshot.last_progress_at is not None or snapshot.parts.exists()):
                return False
            actor = get_user_model().objects.get(pk=snapshot.actor_id)
            require_organization_action(organization=organization, user=actor, action=Action.ORGANIZATION_EXPORT)
            now = timezone.now()
            OrganizationCustomerExport.objects.filter(pk=snapshot.pk).update(last_progress_at=now,
                progress={"attempt": attempt, "in_flight": True, "write_in_flight": False, "parts": 0, "bytes": 0,
                          "chain": "00" * 32, "started_at": now.isoformat()})
        claimed = True
        with coherent_customer_content(organization_id=organization_id, actor_id=snapshot.actor_id) as (pages, validate, lineage):
            for data, source in pages:
                key_stem = uuid4().hex
                write_returned = False
                with _claimed_snapshot(snapshot_id, organization_id, attempt) as (snapshot, organization, actor):
                    validate()
                    OrganizationCustomerExport.objects.filter(pk=snapshot.pk).update(last_progress_at=timezone.now(),
                        progress={**snapshot.progress, "write_in_flight": True,
                                  "intended_key": f"{organization_export_scope(organization)}/{snapshot.pk}/{key_stem}.zip"})
                with _claimed_snapshot(snapshot_id, organization_id, attempt) as (snapshot, organization, actor):
                    validate()
                    progress = {**snapshot.progress, "logfile_window": lineage}
                    source = {**source, "logfile_window": lineage}
                    _store(snapshot, organization, progress, data, source, format=FORMAT,
                           consistency=CONSISTENCY, key_stem=key_stem)
                    write_returned = True
                    validate()
                    progress.update(write_in_flight=False, intended_key="")
                    OrganizationCustomerExport.objects.filter(pk=snapshot.pk).update(
                        progress=progress, last_progress_at=timezone.now())
            with _claimed_snapshot(snapshot_id, organization_id, attempt) as (snapshot, organization, actor):
                validate()
            size, chain = _verify_parts(snapshot, validate, readback=True)
            with _claimed_snapshot(snapshot_id, organization_id, attempt) as (snapshot, organization, actor):
                if _verify_parts(snapshot, lambda: None, readback=False) != (size, chain):
                    raise ArtifactStorageError("Verified coherent part inventory changed before publication.")
                validate()
                snapshot.state = snapshot.State.READY
                snapshot.size_bytes = size
                snapshot.content_sha256 = chain
                snapshot.completed_at = timezone.now()
                snapshot.last_progress_at = snapshot.completed_at
                snapshot.progress = {**snapshot.progress, "in_flight": False}
                snapshot.save(update_fields=["state", "size_bytes", "content_sha256", "completed_at",
                                             "last_progress_at", "progress"])
                AuditEvent.objects.create(organization=organization, actor=actor,
                    event_type=AuditEventType.ORGANIZATION_EXPORT_ACCESSED,
                    details={"kind": FORMAT, "export_id": snapshot.pk, "parts": snapshot.progress["parts"]})
                validate()
        return True
    except Exception:
        if claimed:
            with transaction.atomic():
                Organization.objects.select_for_update().get(pk=organization_id)
                snapshot = OrganizationCustomerExport.objects.select_for_update().filter(pk=snapshot_id,
                    state=OrganizationCustomerExport.State.PREPARING, progress__attempt=attempt).first()
                if snapshot:
                    # A normal return proves this writer stopped; unknown calls retain their scope.
                    if write_returned or not snapshot.progress.get("write_in_flight", True):
                        snapshot.progress = {**snapshot.progress, "in_flight": False, "write_in_flight": False}
                    snapshot.state = snapshot.State.FAILED
                    snapshot.save(update_fields=["state", "progress"])
        return False


def current_coherent_customer_snapshot(*, organization, actor, snapshot_id):
    """Current owner and original-source authority for retained private captures."""
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization.pk)
        _current_owner(organization.pk, actor.pk, check_sources=True)
        snapshot = OrganizationCustomerExport.objects.filter(pk=snapshot_id, organization=organization,
            format=FORMAT, state=OrganizationCustomerExport.State.READY).first()
        if (snapshot is None or snapshot.delivery_state != snapshot.State.READY
            or snapshot.progress.get("in_flight")):
            raise PermissionDenied
        _current_owner(organization.pk, snapshot.actor_id)
        size, chain = _verify_parts(snapshot, lambda: None, readback=False)
        if size != snapshot.size_bytes or chain != snapshot.content_sha256:
            raise ArtifactStorageError("Coherent capture manifest integrity check failed.")
        _current_owner(organization.pk, actor.pk, check_sources=True, logfile_window=snapshot.progress["logfile_window"])
        return snapshot


def private_coherent_snapshot_part(*, organization, actor, snapshot_id, position):
    if type(position) is not int or position < 0:
        raise PermissionDenied
    from .customer_snapshot import _read_snapshot_part
    with transaction.atomic():
        snapshot = current_coherent_customer_snapshot(organization=organization, actor=actor, snapshot_id=snapshot_id)
        result = _read_snapshot_part(snapshot, actor, position)
        current_coherent_customer_snapshot(organization=organization, actor=actor, snapshot_id=snapshot_id)
        return result
