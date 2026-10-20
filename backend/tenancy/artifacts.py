from django.core.exceptions import ValidationError

from django.core.exceptions import PermissionDenied
from django.core.files.storage import storages
from django.utils import timezone
from itertools import islice

from config.artifacts import (ArtifactStorageError, ArtifactValidationError, _validate_key, _validate_path,
                              _require_project_artifact_admission, _project_artifact_mutation,
                              delete_private_artifact, read_private_artifact, save_private_artifact)

from .customer_artifact_barrier import project_artifact_barrier
from .models import (Organization, OrganizationCustomerExport, OrganizationDeletionRun,
                     Project, retained_content_window)


def project_artifact_scope(project):
    if (
        not isinstance(project, Project)
        or project._state.adding
        or project.pk is None
        or project.organization_id is None
    ):
        raise ValidationError("A saved project is required.")
    return f"organizations/{project.organization_id}/projects/{project.pk}"


def organization_export_scope(organization):
    if not isinstance(organization, Organization) or organization._state.adding or organization.pk is None:
        raise ValidationError("A saved organization is required.")
    return f"organizations/{organization.pk}/exports"


def save_project_artifact(*, project, content, content_type, key_stem=None):
    return save_private_artifact(
        scope=project_artifact_scope(project),
        content=content,
        content_type=content_type,
        key_stem=key_stem,
    )


def read_project_artifact(*, project, key):
    prefix = project_artifact_scope(project) + "/"
    if not isinstance(key, str) or not key.startswith(prefix):
        raise ArtifactValidationError("Invalid artifact key")
    return read_private_artifact(key)


def delete_project_artifact(*, project, key):
    prefix = project_artifact_scope(project) + "/"
    if not isinstance(key, str) or not key.startswith(prefix):
        raise ArtifactValidationError("Invalid artifact key")
    delete_private_artifact(key)


def iter_project_artifact_keys(*, project, after_key=None):
    """Yield deterministic visible keys, including nested job files and orphans."""
    scope = project_artifact_scope(project)
    if after_key is not None:
        _validate_key(after_key)
        if not after_key.startswith(scope + "/"):
            raise ArtifactValidationError("Scoped artifact cursor is invalid.")
    yield from _iter_scope_keys(scope, after_key=after_key)


def _iter_scope_keys(scope, *, after_key=None):
    try:
        storage = storages["artifacts"]
        if hasattr(storage, "bucket_name") and hasattr(storage, "connection"):
            prefix = storage._normalize_name(scope + "/")
            location = storage.location.strip("/")
            relative_prefix = location + "/" if location else ""
            parameters = {"Bucket": storage.bucket_name, "Prefix": prefix}
            if after_key is not None:
                parameters["StartAfter"] = storage._normalize_name(after_key)
            for page in storage.connection.meta.client.get_paginator("list_objects_v2").paginate(**parameters):
                for item in page.get("Contents", []):
                    key = item.get("Key")
                    if type(key) is not str or not key.startswith(prefix) or not key.startswith(relative_prefix):
                        raise ArtifactValidationError("Scoped artifact listing is invalid.")
                    relative_key = key[len(relative_prefix):]
                    _validate_key(relative_key)
                    if relative_key[len(scope) + 1:].count("/") > 3:
                        raise ArtifactValidationError("Project artifact nesting exceeds the supported depth.")
                    if after_key is not None and relative_key <= after_key:
                        raise ArtifactValidationError("Scoped artifact cursor did not advance.")
                    yield relative_key
            return
        pending = [(scope, 0, False)]
        while pending:
            path, depth, is_file = pending.pop()
            if is_file:
                _validate_key(path)
                if after_key is None or path > after_key:
                    yield path
                continue
            try:
                directories, files = storage.listdir(path)
            except FileNotFoundError:
                continue
            children = [(f"{path}/{name}", depth, True) for name in files]
            for name in directories:
                child = f"{path}/{name}"
                _validate_path(child)
                if depth >= 3:
                    raise ArtifactValidationError("Project artifact nesting exceeds the supported depth.")
                if after_key is None or child + "/" > after_key or after_key.startswith(child + "/"):
                    children.append((child, depth + 1, False))
            # Lexical key order matches S3 StartAfter; numeric owner indices
            # remain current-list selections, never immutable identities.
            pending.extend(sorted(children, key=lambda item: item[0] + ("" if item[2] else "/"), reverse=True))
    except (ArtifactValidationError, ArtifactStorageError):
        raise
    except Exception:
        raise ArtifactStorageError("Private project artifact inventory is unavailable.") from None


def project_artifact_page(*, project, offset, limit=100):
    if (type(offset) is not int or not 0 <= offset <= 1_000_000
        or type(limit) is not int or not 1 <= limit <= 100):
        raise ArtifactValidationError("Choose a bounded private artifact page.")
    # ponytail: seek by scanning the project prefix; use a provider cursor if
    # repeated deep offsets become a practical source/export cost.
    rows = list(islice(iter_project_artifact_keys(project=project), offset, offset + limit + 1))
    return rows[:limit], len(rows) > limit


def list_project_artifact_keys(*, project, limit=1000, truncate=False):
    if type(limit) is not int or not 1 <= limit <= 1000 or type(truncate) is not bool:
        raise ArtifactValidationError("Choose a bounded project artifact inventory.")
    rows = list(islice(iter_project_artifact_keys(project=project), limit + 1))
    if len(rows) > limit and not truncate:
        raise ArtifactValidationError("Project artifact inventory exceeds the bounded batch.")
    return rows[:limit]


def delete_closed_project_artifact_batch(*, organization, project, limit=100, storage=None):
    """Delete only one closed tenant's keys, including all S3 versions/markers."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ArtifactValidationError("Choose a bounded deletion batch.")
    with project_artifact_barrier(organization.pk, shared=True):
        organization = _deletion_organization(organization)
        project = Project.objects.filter(pk=project.pk, organization=organization).first()
        if project is None:
            raise PermissionDenied
        return _delete_scope_batch(scope=project_artifact_scope(project), limit=limit, storage=storage,
                                   delete=lambda key: delete_project_artifact(project=project, key=key))


def delete_closed_organization_export_batch(*, organization, limit=100, storage=None):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ArtifactValidationError("Choose a bounded deletion batch.")
    organization = _deletion_organization(organization)
    if OrganizationCustomerExport.objects.filter(organization=organization, format="coherent-parts-v3",
        progress__in_flight=True).exists():
        raise ArtifactStorageError("Private export writes remain unresolved; preserve their cleanup scope.")
    return _delete_scope_batch(scope=organization_export_scope(organization), limit=limit, storage=storage)


def delete_failed_organization_export_batch(*, organization, actor, snapshot_id, limit=10, storage=None):
    if type(snapshot_id) is not int or snapshot_id < 1 or type(limit) is not int or not 1 <= limit <= 10:
        raise ArtifactValidationError("Choose one bounded failed export cleanup.")
    from .services import Action, require_organization_action
    require_organization_action(organization=organization, user=actor, action=Action.ORGANIZATION_EXPORT)
    if not OrganizationCustomerExport.objects.filter(pk=snapshot_id, organization=organization,
        state=OrganizationCustomerExport.State.FAILED).exists():
        raise PermissionDenied
    if OrganizationCustomerExport.objects.filter(pk=snapshot_id, organization=organization,
        format="coherent-parts-v3", progress__in_flight=True).exists():
        raise PermissionDenied
    return _delete_scope_batch(scope=f"{organization_export_scope(organization)}/{snapshot_id}",
                               limit=limit, storage=storage)


def delete_expired_organization_export_batch(*, organization, snapshot_id, storage=None):
    """Caller holds the organization lock through deletion and final version verification."""
    from django.utils import timezone
    snapshot = OrganizationCustomerExport.objects.filter(pk=snapshot_id, organization=organization,
        state=OrganizationCustomerExport.State.READY, expires_at__lte=timezone.now()).first()
    if (snapshot is None or not snapshot.expiry_policy_reference
        or (snapshot.format == "coherent-parts-v3" and snapshot.progress.get("in_flight"))):
        raise PermissionDenied
    return _delete_scope_batch(scope=f"{organization_export_scope(organization)}/{snapshot.pk}",
                               limit=10, storage=storage)


def _deletion_organization(organization):
    organization = Organization.objects.filter(pk=organization.pk).first()
    if organization is None:
        raise PermissionDenied
    if not (organization.is_suspended and organization.closed_at is not None):
        if (organization.is_suspended or organization.closed_at is not None
            or not OrganizationDeletionRun.objects.filter(organization=organization,
                state__in=[OrganizationDeletionRun.State.PENDING,
                           OrganizationDeletionRun.State.STORAGE_CLEARED], eligible_at__lte=timezone.now()).exists()
            or Organization.objects.filter(pk=organization.pk).filter(retained_content_window()).exists()):
            raise PermissionDenied
    else:
        from .paddle_cancellation import require_confirmed_closed_billing
        require_confirmed_closed_billing(organization)
    return organization


def _delete_scope_batch(*, scope, limit, storage, delete=delete_private_artifact):
    storage = storage or storages["artifacts"]
    scope += "/"
    if hasattr(storage, "bucket_name") and hasattr(storage, "connection"):
        # S3Storage.delete() only writes a marker on versioned buckets; remove
        # exact-scope versions and old markers, not just visible objects.
        _require_project_artifact_admission(scope)
        prefix = storage._normalize_name(scope)
        location = storage.location.strip("/")
        relative_prefix = location + "/" if location else ""
        deleted = 0
        try:
            client = storage.connection.meta.client
            pages = client.get_paginator("list_object_versions").paginate(
                Bucket=storage.bucket_name, Prefix=prefix)
            for page in pages:
                items = [*page.get("Versions", []), *page.get("DeleteMarkers", [])]
                for item in items:
                    key, version = item.get("Key"), item.get("VersionId")
                    if (type(key) is not str or not key.startswith(prefix) or not key.startswith(relative_prefix)
                        or type(version) is not str or not 1 <= len(version) <= 512):
                        raise ArtifactValidationError("Scoped artifact version listing is invalid.")
                    _validate_key(key[len(relative_prefix):])
                for item in items:
                    with _project_artifact_mutation(item["Key"][len(relative_prefix):],
                            operation="delete_version", storage=storage, version_id=item["VersionId"]):
                        client.delete_object(Bucket=storage.bucket_name, Key=item["Key"], VersionId=item["VersionId"])
                    deleted += 1
                    if deleted >= limit:
                        return deleted, False  # A later pass proves no versions remain.
            return deleted, True
        except (ArtifactValidationError, ArtifactStorageError):
            raise
        except Exception:
            raise ArtifactStorageError("Private artifact version deletion is unavailable.") from None
    keys = list(islice(_iter_scope_keys(scope[:-1]), limit + 1))
    for key in keys[:limit]:
        delete(key)
    return min(len(keys), limit), len(keys) <= limit


def project_artifact_versions_remain(*, project, storage=None):
    """Read-only final gate: hidden S3 versions count even without a visible object."""
    return _scope_versions_remain(project_artifact_scope(project), storage)


def organization_export_versions_remain(*, organization, storage=None):
    if OrganizationCustomerExport.objects.filter(organization=organization, format="coherent-parts-v3",
        progress__in_flight=True).exists():
        return True  # An absent object cannot prove an unknown write has finished.
    return _scope_versions_remain(organization_export_scope(organization), storage)


def failed_export_versions_remain(*, organization, snapshot_id, storage=None):
    if type(snapshot_id) is not int or snapshot_id < 1:
        raise ArtifactValidationError("Choose one private export scope.")
    return _scope_versions_remain(f"{organization_export_scope(organization)}/{snapshot_id}", storage)


def _scope_versions_remain(scope, storage):
    scope += "/"
    storage = storage or storages["artifacts"]
    if hasattr(storage, "bucket_name") and hasattr(storage, "connection"):
        prefix = storage._normalize_name(scope)
        location = storage.location.strip("/")
        relative_prefix = location + "/" if location else ""
        try:
            pages = storage.connection.meta.client.get_paginator("list_object_versions").paginate(
                Bucket=storage.bucket_name, Prefix=prefix)
            for page in pages:
                for item in (*page.get("Versions", []), *page.get("DeleteMarkers", [])):
                    key = item.get("Key")
                    if type(key) is not str or not key.startswith(prefix) or not key.startswith(relative_prefix):
                        raise ArtifactValidationError("Scoped artifact version listing is invalid.")
                    _validate_key(key[len(relative_prefix):])
                    return True
            return False
        except ArtifactValidationError:
            raise
        except Exception:
            raise ArtifactStorageError("Private artifact version listing is unavailable.") from None
    return bool(next(_iter_scope_keys(scope[:-1]), None))
