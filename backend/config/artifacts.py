import logging
import os
import re
from contextlib import nullcontext
from pathlib import Path
from uuid import uuid4

from botocore.config import Config
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.core.files.storage import storages


logger = logging.getLogger("organicseoops.artifacts")
_segment = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}").fullmatch
_extensions = {
    "application/json": "json",
    "application/zip": "zip",
    "text/csv": "csv",
    "text/html": "html",
    "text/plain": "txt",
}
_content_types_by_extension = {extension: content_type for content_type, extension in _extensions.items()}


class ArtifactValidationError(ValueError):
    pass


class ArtifactNotFound(Exception):
    pass


class ArtifactStorageError(Exception):
    pass


def artifact_settings(environ=os.environ, *, default_local_root):
    try:
        max_bytes = int(environ.get("ARTIFACT_MAX_BYTES", 10 * 1024 * 1024))
    except ValueError as error:
        raise ImproperlyConfigured("ARTIFACT_MAX_BYTES must be an integer") from error
    if not 1 <= max_bytes <= 100 * 1024 * 1024:
        raise ImproperlyConfigured("ARTIFACT_MAX_BYTES must be between 1 and 104857600")

    allowed_types = frozenset(filter(None, environ.get(
        "ARTIFACT_ALLOWED_CONTENT_TYPES", ",".join(_extensions),
    ).split(",")))
    if not allowed_types or not allowed_types <= _extensions.keys():
        raise ImproperlyConfigured("ARTIFACT_ALLOWED_CONTENT_TYPES contains an unsupported type")

    backend = environ.get("ARTIFACT_STORAGE_BACKEND", "filesystem")
    if backend == "filesystem":
        root = Path(environ.get("ARTIFACT_LOCAL_ROOT", default_local_root)).expanduser()
        if not root.is_absolute():
            raise ImproperlyConfigured("ARTIFACT_LOCAL_ROOT must be absolute")
        storage = {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {
                "location": str(root),
                "base_url": None,
                "file_permissions_mode": 0o600,
                "directory_permissions_mode": 0o700,
            },
        }
    elif backend == "s3":
        bucket = environ.get("ARTIFACT_S3_BUCKET", "")
        if not bucket:
            raise ImproperlyConfigured("ARTIFACT_S3_BUCKET is required for S3 artifact storage")
        prefix = environ.get("ARTIFACT_S3_PREFIX", "artifacts").strip("/")
        try:
            _validate_path(prefix, "ARTIFACT_S3_PREFIX")
        except ArtifactValidationError as error:
            raise ImproperlyConfigured(str(error)) from error
        options = {
            "bucket_name": bucket,
            "location": prefix,
            "default_acl": None,
            "querystring_auth": True,
            "querystring_expire": 300,
            "max_memory_size": min(max_bytes, 8 * 1024 * 1024),
            "file_overwrite": False,
            "custom_domain": None,
            "object_parameters": {
                "CacheControl": "private, no-store",
                "ServerSideEncryption": "AES256",
            },
            "client_config": Config(
                connect_timeout=1,
                read_timeout=2,
                retries={"total_max_attempts": 1, "mode": "standard"},
            ),
        }
        if environ.get("AWS_REGION"):
            options["region_name"] = environ["AWS_REGION"]
        storage = {"BACKEND": "storages.backends.s3.S3Storage", "OPTIONS": options}
    else:
        raise ImproperlyConfigured("ARTIFACT_STORAGE_BACKEND must be filesystem or s3")
    return storage, max_bytes, allowed_types


def _validate_path(value, label="artifact path"):
    parts = value.split("/")
    if not value or value.startswith("/") or "\\" in value or any(
        part in {"", ".", ".."} or not _segment(part) for part in parts
    ):
        raise ArtifactValidationError(f"Invalid {label}")


def _read_bounded(content):
    try:
        data = bytes(content) if isinstance(content, (bytes, bytearray, memoryview)) else content.read(
            settings.ARTIFACT_MAX_BYTES + 1
        )
    except Exception:
        raise ArtifactValidationError("Artifact content could not be read") from None
    if not isinstance(data, bytes):
        raise ArtifactValidationError("Artifact content must be bytes")
    if not data:
        raise ArtifactValidationError("Artifact content is empty")
    if len(data) > settings.ARTIFACT_MAX_BYTES:
        raise ArtifactValidationError("Artifact exceeds the configured size limit")
    return data


def _validate_key(key):
    _validate_path(key)
    name = key.rsplit("/", 1)[-1]
    stem, separator, extension = name.rpartition(".")
    content_type = _content_types_by_extension.get(extension)
    if not separator or not re.fullmatch(r"[0-9a-f]{32}", stem) or content_type not in settings.ARTIFACT_ALLOWED_CONTENT_TYPES:
        raise ArtifactValidationError("Invalid artifact key")


def _require_project_artifact_admission(path):
    parts = path.split("/")
    if len(parts) >= 3 and parts[0] == "organizations" and parts[2] == "projects":
        if (len(parts) < 4 or not re.fullmatch(r"[1-9][0-9]*", parts[1])
            or not re.fullmatch(r"[1-9][0-9]*", parts[3]) or int(parts[1]) >= 2**63
            or int(parts[3]) >= 2**63):
            raise ArtifactValidationError("Invalid project artifact scope")
        from tenancy.customer_artifact_barrier import require_artifact_admission
        require_artifact_admission(int(parts[1]), shared=True)


def _project_artifact_mutation(key, *, operation, storage, version_id=""):
    _require_project_artifact_admission(key)
    parts = key.split("/")
    if len(parts) >= 4 and parts[0] == "organizations" and parts[2] == "projects":
        from tenancy.customer_artifact_barrier import project_artifact_mutation
        return project_artifact_mutation(organization_id=int(parts[1]), project_id=int(parts[3]),
            key=key, operation=operation, storage=storage, version_id=version_id)
    return nullcontext({"key": ""})


def save_private_artifact(*, scope, content, content_type, key_stem=None):
    _validate_path(scope, "artifact scope")
    if content_type not in settings.ARTIFACT_ALLOWED_CONTENT_TYPES:
        raise ArtifactValidationError("Artifact content type is not allowed")
    data = _read_bounded(content)
    if key_stem is not None and not re.fullmatch(r"[0-9a-f]{32}", key_stem):
        raise ArtifactValidationError("Invalid artifact key stem")
    key = f"{scope}/{key_stem or uuid4().hex}.{_extensions[content_type]}"
    file = ContentFile(data, name=key.rsplit("/", 1)[-1])
    file.content_type = content_type
    _require_project_artifact_admission(scope)
    try:
        storage = storages["artifacts"]
        if storage.exists(key):
            with storage.open(key, "rb") as existing:
                if existing.read(settings.ARTIFACT_MAX_BYTES + 1) == data:
                    return key
            raise ArtifactStorageError("Artifact key collision")
        with _project_artifact_mutation(key, operation="save", storage=storage) as result:
            saved_key = storage.save(key, file)
            if not isinstance(saved_key, str) or saved_key.rsplit("/", 1)[0] != scope:
                raise ArtifactStorageError("Artifact storage returned an invalid scope")
            _validate_path(saved_key)
            result["key"] = saved_key
        if saved_key != key:
            with _project_artifact_mutation(saved_key, operation="delete", storage=storage):
                storage.delete(saved_key)
            raise ArtifactStorageError("Artifact key collision")
    except ArtifactStorageError:
        raise
    except Exception as error:
        logger.error("artifact.store_failed", extra={"error_type": type(error).__name__})
        raise ArtifactStorageError("Artifact storage is unavailable") from None
    return key


def read_private_artifact(key):
    _validate_key(key)
    try:
        storage = storages["artifacts"]
        if not storage.exists(key):
            raise ArtifactNotFound("Artifact not found")
        if storage.size(key) > settings.ARTIFACT_MAX_BYTES:
            raise ArtifactStorageError("Stored artifact exceeds the configured size limit")
        with storage.open(key, "rb") as file:
            data = file.read(settings.ARTIFACT_MAX_BYTES + 1)
    except (ArtifactNotFound, ArtifactStorageError):
        raise
    except Exception as error:
        logger.error("artifact.read_failed", extra={"error_type": type(error).__name__})
        raise ArtifactStorageError("Artifact storage is unavailable") from None
    if len(data) > settings.ARTIFACT_MAX_BYTES:
        raise ArtifactStorageError("Stored artifact exceeds the configured size limit")
    return data


def delete_private_artifact(key):
    _validate_key(key)
    _require_project_artifact_admission(key)
    try:
        storage = storages["artifacts"]
        with _project_artifact_mutation(key, operation="delete", storage=storage):
            storage.delete(key)
    except ArtifactStorageError:
        raise
    except Exception as error:
        logger.error("artifact.delete_failed", extra={"error_type": type(error).__name__})
        raise ArtifactStorageError("Artifact storage is unavailable") from None


def cleanup_private_artifacts(*, scope, keep_keys, limit=100):
    _validate_path(scope, "artifact scope")
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ArtifactValidationError("Invalid artifact cleanup limit")
    _require_project_artifact_admission(scope)
    try:
        storage = storages["artifacts"]
        _directories, files = storage.listdir(scope)
        removed = 0
        for name in files[:limit]:
            key = f"{scope}/{name}"
            try:
                _validate_key(key)
            except ArtifactValidationError:
                continue
            if key not in keep_keys:
                with _project_artifact_mutation(key, operation="delete", storage=storage):
                    storage.delete(key)
                removed += 1
        return removed
    except FileNotFoundError:
        return 0
    except ArtifactStorageError:
        raise
    except Exception as error:
        logger.error("artifact.cleanup_failed", extra={"error_type": type(error).__name__})
        return 0
