"""Internal project-object admission; producers must enter before locks or provider work."""
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4
import json

from django.db import connection, DatabaseError, InterfaceError

from config.artifacts import ArtifactStorageError

_held = ContextVar("customer_artifact_admission", default={})
WRITER_ADMISSION_TIMEOUT_MS = 1000


class ArtifactAdmissionUnavailable(ArtifactStorageError):
    """Admission failed before caller work began; only this refusal is safe to retry."""


def require_artifact_admission(organization_id, *, shared):
    held = _held.get()
    if organization_id not in held:
        raise RuntimeError("Project artifact admission is required before work starts.")
    owner, writer, native, _attempt_id = held[organization_id]
    owner.validate_thread_sharing()
    if writer is not shared:
        raise RuntimeError("Capture admission cannot mutate its project objects.")
    if owner.connection is not native or native.closed:
        raise ArtifactStorageError("Artifact admission was lost; its original view cannot resume.")
    try:
        with owner.cursor() as cursor:
            cursor.execute("SELECT 1")
    except (DatabaseError, InterfaceError):
        raise ArtifactStorageError("Artifact admission was lost; its original view cannot resume.") from None
    return owner


def _clear_mutation_attempt(owner, attempt_id):
    # Keep admission until both journal deletes commit on its original session.
    owner.set_autocommit(False)
    try:
        with owner.cursor() as cursor:
            cursor.execute("DELETE FROM tenancy_projectartifactmutation WHERE attempt_id = %s", [attempt_id])
            cursor.execute("DELETE FROM tenancy_projectartifactmutationattempt WHERE id = %s", [attempt_id])
        owner.commit()
    finally:
        owner.set_autocommit(True)


def require_settled_project_mutations(organization_id, *, exclude_own=False):
    """Fresh admission-session read, including intents whose session has disappeared."""
    held = _held.get()
    owner, shared, _native, attempt_id = held[organization_id]
    require_artifact_admission(organization_id, shared=shared)
    with owner.cursor() as cursor:
        cursor.execute("SELECT 1 FROM tenancy_projectartifactmutationattempt WHERE organization_id = %s"
                       + (" AND id != %s" if exclude_own and attempt_id else "") + " LIMIT 1",
                       [organization_id, attempt_id] if exclude_own and attempt_id else [organization_id])
        if cursor.fetchone():
            raise ArtifactStorageError("Project artifact mutation is unresolved; capture or deletion cannot complete.")
        if exclude_own and attempt_id:
            cursor.execute("SELECT 1 FROM tenancy_projectartifactmutation WHERE attempt_id = %s"
                           " AND settled_at IS NULL LIMIT 1", [attempt_id])
            if cursor.fetchone():
                raise ArtifactStorageError("Project artifact mutation is unresolved; capture or deletion cannot complete.")


@contextmanager
def project_artifact_mutation(*, organization_id, project_id, key, operation, storage, version_id=""):
    """Commit exact intent before storage; only a normal synchronous return is settled."""
    owner = require_artifact_admission(organization_id, shared=True)
    attempt_id = _held.get()[organization_id][3]
    mutation_id = uuid4()
    identity = {"backend": f"{type(storage).__module__}.{type(storage).__qualname__}",
                "location": str(getattr(storage, "location", ""))}
    if hasattr(storage, "bucket_name"):
        identity["bucket"] = storage.bucket_name
    try:
        with owner.cursor() as cursor:
            cursor.execute("INSERT INTO tenancy_projectartifactmutation"
                " (id, attempt_id, project_id, operation, storage_key, version_id, storage_identity,"
                " result_key, created_at, settled_at) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, '', now(), NULL)",
                [mutation_id, attempt_id, project_id, operation, key, version_id, json.dumps(identity)])
        require_artifact_admission(organization_id, shared=True)
        result = {"key": ""}
        yield result
        require_artifact_admission(organization_id, shared=True)
        with owner.cursor() as cursor:
            cursor.execute("UPDATE tenancy_projectartifactmutation SET settled_at = now(), result_key = %s"
                           " WHERE id = %s AND attempt_id = %s", [result["key"], mutation_id, attempt_id])
    except (DatabaseError, InterfaceError):
        raise ArtifactStorageError("Artifact mutation settlement is unavailable; its outcome remains unresolved.") from None


@contextmanager
def project_artifact_barrier(organization_id, *, shared, timeout_ms=None):
    if type(organization_id) is not int or not 0 < organization_id < 2**63 or type(shared) is not bool:
        raise ValueError("Choose an exact organization and artifact admission mode.")
    if timeout_ms is not None and (type(timeout_ms) is not int or not 0 < timeout_ms < 2**31):
        raise ValueError("Choose a bounded artifact admission timeout.")
    if shared and timeout_ms is None:
        timeout_ms = WRITER_ADMISSION_TIMEOUT_MS
    held = _held.get()
    if organization_id in held:
        owner, writer, _native, _attempt_id = held[organization_id]
        owner.validate_thread_sharing()
        if not shared or not writer:
            raise RuntimeError("Capture admission cannot upgrade or mutate its project objects.")
        yield require_artifact_admission(organization_id, shared=True)
        return
    if connection.vendor != "postgresql" or connection.in_atomic_block or not connection.get_autocommit():
        raise RuntimeError("Artifact admission must precede the owning transaction and its row locks.")
    # PostgreSQL's two-int lock space is separate from existing one-bigint locks.
    low = organization_id & 0xFFFFFFFF
    key = [organization_id >> 32, low if low < 2**31 else low - 2**32]
    owner = connection.copy()
    try:
        try:
            with owner.cursor() as cursor:
                if timeout_ms is not None:
                    cursor.execute("SELECT set_config('statement_timeout', %s, false)", [f"{timeout_ms}ms"])
                cursor.execute("SELECT pg_advisory_lock_shared(%s, %s)" if shared
                               else "SELECT pg_advisory_lock(%s, %s)", key)
                if timeout_ms is not None:
                    cursor.execute("SET statement_timeout = 0")
        except (DatabaseError, InterfaceError):
            raise ArtifactAdmissionUnavailable("Artifact admission is unavailable; retry before starting work.") from None
        attempt_id = uuid4() if shared else None
        if shared:
            try:
                with owner.cursor() as cursor:
                    cursor.execute("INSERT INTO tenancy_projectartifactmutationattempt"
                        " (id, organization_id, admission_pid, created_at) VALUES (%s, %s, pg_backend_pid(), now())",
                        [attempt_id, organization_id])
            except (DatabaseError, InterfaceError):
                raise ArtifactAdmissionUnavailable("Artifact mutation ownership is unavailable; retry before starting work.") from None
        token = _held.set({**held, organization_id: (owner, shared, owner.connection, attempt_id)})
        try:
            if not shared:
                require_settled_project_mutations(organization_id)
            try:
                yield owner
            except BaseException:
                if shared:
                    try:
                        if not connection.in_atomic_block and connection.get_autocommit():
                            require_artifact_admission(organization_id, shared=True)
                            with owner.cursor() as cursor:
                                cursor.execute("SELECT 1 FROM tenancy_projectartifactmutation WHERE attempt_id = %s LIMIT 1",
                                               [attempt_id])
                                mutated = cursor.fetchone()
                            if not mutated:
                                _clear_mutation_attempt(owner, attempt_id)
                    except (ArtifactStorageError, DatabaseError, InterfaceError):
                        pass  # Preserve the original failure and any uncertain ownership.
                raise
            if shared:
                require_artifact_admission(organization_id, shared=True)
                if connection.in_atomic_block or not connection.get_autocommit():
                    raise RuntimeError("Artifact writer completion must follow its owning transaction.")
                with owner.cursor() as cursor:
                    cursor.execute("SELECT 1 FROM tenancy_projectartifactmutation WHERE attempt_id = %s"
                                   " AND settled_at IS NULL LIMIT 1", [attempt_id])
                    unresolved = cursor.fetchone()
                if not unresolved:
                    _clear_mutation_attempt(owner, attempt_id)
        finally:
            _held.reset(token)
    finally:
        owner.close()  # Session admission survives commit/rollback, not connection loss.
