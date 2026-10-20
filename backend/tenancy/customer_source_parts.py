"""Checkpointed source observations, not a point-in-time tenant snapshot.

Each task handles one <=50-row page or one configured-size private object.
No whole-export ZIP/spool is assembled. Unknown interrupted writes fail closed;
only committed stage boundaries can be redispatched.
"""
from hashlib import sha256
from io import BytesIO
import json
from zipfile import ZIP_STORED, ZipFile
from contextlib import closing

from django.conf import settings
from django.core.files.storage import storages
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Count, Max, Sum
from django.utils import timezone
from kombu.exceptions import OperationalError

from config.artifacts import ArtifactStorageError, read_private_artifact, save_private_artifact
from .artifacts import iter_project_artifact_keys, organization_export_scope
from .customer_export import CUSTOMER, SCHEMAS, _reviewed_fields, _row
from .models import AuditEvent, AuditEventType, Organization, OrganizationCustomerExport, OrganizationCustomerExportPart, Project
from .services import Action, require_organization_action

FORMAT = "source-parts-v2"
PART_BYTES = 4 * 1024 * 1024
CONSISTENCY = "sequential_high_water_rows_and_visible_keyset_observations_not_transactional"


def encoded(value):
    return json.dumps(value, cls=DjangoJSONEncoder, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(",", ":")).encode()


def descriptor(part):
    return {"position": part.position, "size_bytes": part.size_bytes,
            "sha256": part.content_sha256, "source": part.source}


def dispatch_source_stage(snapshot_id, step):
    from .tasks import capture_customer_snapshot_task
    try:
        capture_customer_snapshot_task.apply_async(args=[snapshot_id, step], queue="audit",
            task_id=f"customer-export-{snapshot_id}-{step}", retry=False)
    except (OperationalError, OSError, TimeoutError):
        pass  # Recovery redispatches this exact committed stage, never an unknown write.


def _store(snapshot, organization, progress, data, source, *, format=FORMAT, consistency=CONSISTENCY, key_stem=None):
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_STORED) as archive:
        archive.writestr("data", data)
        archive.writestr("source.json", encoded({"version": format, "consistency": consistency, **source}))
    content = output.getvalue()
    if len(content) > min(8 * 1024 * 1024, settings.ARTIFACT_MAX_BYTES):
        raise ArtifactStorageError("Source part exceeds the private part ceiling.")
    key = save_private_artifact(scope=f"{organization_export_scope(organization)}/{snapshot.pk}",
                                content=content, content_type="application/zip",
                                **({"key_stem": key_stem} if key_stem is not None else {}))
    checksum = sha256(content).hexdigest()
    captured = read_private_artifact(key)
    if len(captured) != len(content) or sha256(captured).hexdigest() != checksum:
        raise ArtifactStorageError("Private source part integrity check failed.")
    part = OrganizationCustomerExportPart.objects.create(export=snapshot, position=progress["parts"],
        storage_key=key, size_bytes=len(content), content_sha256=checksum, source=source)
    progress["chain"] = sha256(bytes.fromhex(progress["chain"]) + encoded(descriptor(part))).hexdigest()
    progress["parts"] += 1
    progress["bytes"] += len(content)


def _initial_progress(organization):
    started_at = timezone.now().isoformat()
    windows = {}
    for label, lookup in sorted(CUSTOMER.items()):
        model, _fields = _reviewed_fields(label)
        window = model.objects.filter(**{lookup: organization.pk}).aggregate(count=Count("pk"), through=Max("pk"))
        windows[label] = {"count": window["count"], "through": window["through"] or 0}
    return {"step": 0, "in_flight": False, "phase": "rows", "table": 0, "after": 0, "rows": 0,
            "windows": windows, "project_after": 0,
            "project_through": Project.objects.filter(organization=organization).aggregate(pk=Max("pk"))["pk"] or 0,
            "key_after": None, "artifact_index": 0, "parts": 0, "bytes": 0, "chain": "00" * 32,
            "started_at": started_at}


def _rows_page(organization, progress):
    started_at = timezone.now().isoformat()
    labels = sorted(CUSTOMER)
    label = labels[progress["table"]]
    model, fields = _reviewed_fields(label)
    window = progress["windows"][label]
    queryset = model.objects.filter(**{CUSTOMER[label]: organization.pk}, pk__gt=progress["after"],
                                    pk__lte=window["through"]).order_by("pk")
    if label == "tenancy.OrganizationMembership":
        queryset = queryset.select_related("user")
    rows, size = [], 2
    next_after = progress["after"]
    for record in queryset[:50].iterator(chunk_size=1):
        row = encoded(_row(record, fields))
        if size + len(row) + 1 > min(PART_BYTES, settings.ARTIFACT_MAX_BYTES - 64 * 1024):
            if not rows:
                raise ArtifactStorageError("A customer row exceeds the source part ceiling.")
            break
        rows.append(row)
        size += len(row) + 1
        next_after = record.pk
    remaining = queryset.filter(pk__gt=next_after).exists()
    source = {"kind": "rows", "model": label, "schema": SCHEMAS[label], "after_id": progress["after"],
              "through_id": window["through"], "next_after_id": next_after, "count": len(rows),
              "inventory_count": window["count"], "table_complete": not remaining,
              "started_at": started_at, "observed_at": timezone.now().isoformat()}
    progress["rows"] += len(rows)
    progress["after"] = next_after
    if not remaining:
        if progress["rows"] != window["count"]:
            raise ArtifactStorageError("Source record inventory changed during capture.")
        progress.update(table=progress["table"] + 1, after=0, rows=0)
        if progress["table"] == len(labels):
            progress["phase"] = "artifacts"
    return b"[" + b",".join(rows) + b"]", source


def _rows_stage(snapshot, organization, progress):
    data, source = _rows_page(organization, progress)
    _store(snapshot, organization, progress, data, source)


def _artifact_stage(snapshot, organization, progress):
    project = Project.objects.filter(organization=organization, pk__gt=progress["project_after"],
                                    pk__lte=progress["project_through"]).order_by("pk").first()
    if project is None:
        return True
    key = next(iter_project_artifact_keys(project=project, after_key=progress["key_after"]), None)
    if key is None:
        _store(snapshot, organization, progress, b"[]", {"kind": "project_artifacts_complete",
            "project_id": project.pk, "visible_objects_observed": progress["artifact_index"],
            "observed_at": timezone.now().isoformat()})
        progress.update(project_after=project.pk, key_after=None, artifact_index=0)
        return False
    with closing(_artifact_pages(project, key, progress["artifact_index"])) as pages:
        for data, source in pages:
            _store(snapshot, organization, progress, data, source)
    progress.update(key_after=key, artifact_index=progress["artifact_index"] + 1)
    return False


def _artifact_pages(project, key, artifact_index):
    """Serialize one opened object in bounded pieces; exhaust or close the iterator."""
    storage = storages["artifacts"]
    size = storage.size(key)
    if type(size) is not int or not 1 <= size <= settings.ARTIFACT_MAX_BYTES:
        raise ArtifactStorageError("Private source object has an invalid size.")
    digest, offset = sha256(), 0
    block_limit = min(PART_BYTES, settings.ARTIFACT_MAX_BYTES - 64 * 1024)
    started_at = timezone.now().isoformat()
    with storage.open(key, "rb") as source:
        while offset < size:
            block = source.read(min(block_limit, size - offset))
            if not isinstance(block, bytes) or not block or len(block) > min(block_limit, size - offset):
                raise ArtifactStorageError("Private source changed during capture.")
            digest.update(block)
            yield block, {"kind": "artifact_chunk", "project_id": project.pk,
                "artifact_index": artifact_index, "extension": key.rsplit(".", 1)[-1],
                "offset": offset, "size_bytes": len(block), "object_size_bytes": size,
                "started_at": started_at, "observed_at": timezone.now().isoformat()}
            offset += len(block)
        if source.read(1) or storage.size(key) != size:
            raise ArtifactStorageError("Private source changed during capture.")
    yield b"", {"kind": "artifact_complete", "project_id": project.pk,
        "artifact_index": artifact_index, "size_bytes": size, "sha256": digest.hexdigest(),
        "started_at": started_at, "observed_at": timezone.now().isoformat()}


def capture_source_stage(snapshot_id, step):
    if type(snapshot_id) is not int or type(step) is not int or step < 0:
        return False
    organization_id = OrganizationCustomerExport.objects.filter(pk=snapshot_id, format=FORMAT).values_list(
        "organization_id", flat=True).first()
    if organization_id is None:
        return False
    claimed = False
    try:
        with transaction.atomic():
            organization = Organization.objects.select_for_update().get(pk=organization_id)
            snapshot = OrganizationCustomerExport.objects.select_for_update().select_related("actor").get(pk=snapshot_id)
            if snapshot.state != snapshot.State.PREPARING:
                return False
            if ((snapshot.progress and (snapshot.progress["step"] != step or snapshot.progress["in_flight"]))
                or (not snapshot.progress and step != 0)):
                return False
            claimed = True
            require_organization_action(organization=organization, user=snapshot.actor, action=Action.ORGANIZATION_EXPORT)
            progress = snapshot.progress or _initial_progress(organization)
            progress["in_flight"] = True
            OrganizationCustomerExport.objects.filter(pk=snapshot.pk).update(progress=progress, last_progress_at=timezone.now())
        # Persist the claim before any external write. A crash cannot blindly
        # resume a half-written object; FAILED copies remain scoped for cleanup.
        with transaction.atomic():
            organization = Organization.objects.select_for_update().get(pk=organization_id)
            snapshot = OrganizationCustomerExport.objects.select_for_update().select_related("actor").get(pk=snapshot_id)
            require_organization_action(organization=organization, user=snapshot.actor, action=Action.ORGANIZATION_EXPORT)
            if snapshot.state != snapshot.State.PREPARING:
                return False
            progress = snapshot.progress
            complete = False
            if progress["phase"] == "rows":
                _rows_stage(snapshot, organization, progress)
            else:
                complete = _artifact_stage(snapshot, organization, progress)
            if complete:
                totals = snapshot.parts.aggregate(count=Count("pk"), size=Sum("size_bytes"), last=Max("position"))
                if (totals["count"] != progress["parts"] or totals["size"] != progress["bytes"]
                    or totals["last"] != progress["parts"] - 1):
                    raise ArtifactStorageError("Source part capture is incomplete.")
                snapshot.state = snapshot.State.READY
                snapshot.size_bytes = progress["bytes"]
                snapshot.content_sha256 = progress["chain"]
                snapshot.completed_at = timezone.now()
                snapshot.save(update_fields=["state", "size_bytes", "content_sha256", "completed_at"])
                AuditEvent.objects.create(organization=organization, actor=snapshot.actor,
                    event_type=AuditEventType.ORGANIZATION_EXPORT_ACCESSED,
                    details={"kind": FORMAT, "export_id": snapshot.pk, "parts": progress["parts"]})
            else:
                progress.update(step=step + 1, in_flight=False)
                OrganizationCustomerExport.objects.filter(pk=snapshot.pk).update(progress=progress, last_progress_at=timezone.now())
                transaction.on_commit(lambda: dispatch_source_stage(snapshot_id, step + 1))
        return True
    except Exception:
        if claimed:
            OrganizationCustomerExport.objects.filter(pk=snapshot_id, state=OrganizationCustomerExport.State.PREPARING).update(
                state=OrganizationCustomerExport.State.FAILED)
        return False
