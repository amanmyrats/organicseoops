import csv
import hashlib
import io
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from time import monotonic
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from config.artifacts import ArtifactNotFound, ArtifactStorageError, ArtifactValidationError
from jobs.models import Artifact, JobCancellation, JobRun, JobStatus, JobStep, UsageReservation
from jobs.usage import settle_usage, usage_denial
from tenancy.artifacts import delete_project_artifact, project_artifact_scope, read_project_artifact, save_project_artifact
from tenancy.customer_artifact_barrier import WRITER_ADMISSION_TIMEOUT_MS, project_artifact_barrier
from tenancy.models import Organization, Project, normalize_origin
from tenancy.services import Action, require_project_action

from .models import (
    ImportRowError,
    ImportExecutionState,
    ImportRun,
    IntegrationCapability,
    IntegrationConnection,
    PendingArtifactCleanup,
    SearchMetricObservation,
    SourceDimension,
)
from .services import record_import_run, require_connection_capability


MAX_CSV_BYTES = 1024 * 1024
MAX_CSV_ROWS = 1000
SOURCE_TIMEZONE = "America/Los_Angeles"
METRIC_HEADERS = ("Clicks", "Impressions", "CTR", "Position")
DIMENSION_HEADERS = {
    "Top queries": SourceDimension.QUERY,
    "Top pages": SourceDimension.PAGE,
    "Top countries": SourceDimension.COUNTRY,
    "Country": SourceDimension.COUNTRY,
    "Countries": SourceDimension.COUNTRY,
    "Top devices": SourceDimension.DEVICE,
    "Device": SourceDimension.DEVICE,
    "Devices": SourceDimension.DEVICE,
    "Date": SourceDimension.DATE,
    "Dates": SourceDimension.DATE,
    "Search Appearance": SourceDimension.SEARCH_APPEARANCE,
    "Search appearance": SourceDimension.SEARCH_APPEARANCE,
}
logger = logging.getLogger("organicseoops.integrations")


class SearchConsoleCSVError(Exception):
    def __init__(self, category, *, dimensions=(), rows_seen=0):
        self.category = category
        self.dimensions = tuple(dimensions)
        self.rows_seen = rows_seen
        super().__init__(category)


class _RowError(Exception):
    def __init__(self, category, field=""):
        self.category = category
        self.field = field
        super().__init__(category)


@dataclass(frozen=True)
class ParsedSearchConsoleCSV:
    dimension: str
    rows_seen: int
    observations: tuple[dict, ...]
    errors: tuple[tuple[int, str, str], ...]


def validate_search_console_import_input(data):
    expected = {"connection_id", "source_checksum", "date_start", "date_end", "search_type", "date_granularity"}
    if type(data) is not dict or set(data) != expected:
        raise ValidationError("Check the Search Console import input.")
    if type(data["connection_id"]) is not int or data["connection_id"] < 1:
        raise ValidationError("Check the Search Console connection.")
    if not isinstance(data["source_checksum"], str) or not re.fullmatch(r"[0-9a-f]{64}", data["source_checksum"]):
        raise ValidationError("Check the Search Console source checksum.")
    try:
        start = date.fromisoformat(data["date_start"])
        end = date.fromisoformat(data["date_end"])
    except (TypeError, ValueError):
        raise ValidationError("Check the Search Console date range.") from None
    if (
        end < start
        or data["search_type"] not in SearchMetricObservation.SearchType.values
        or data["date_granularity"] not in {None, SearchMetricObservation.TimeGranularity.DAY}
    ):
        raise ValidationError("Check the Search Console import input.")
    return {"method": "search-console-csv-v1"}


def _read_upload(content):
    limit = min(settings.ARTIFACT_MAX_BYTES, MAX_CSV_BYTES)
    try:
        data = bytes(content) if isinstance(content, (bytes, bytearray, memoryview)) else content.read(
            limit + 1
        )
    except Exception:
        raise ArtifactValidationError("Artifact content could not be read") from None
    if not isinstance(data, bytes) or not data:
        raise ArtifactValidationError("Artifact content must be non-empty bytes")
    if len(data) > limit:
        raise ArtifactValidationError("Search Console CSV exceeds the import size limit")
    return data


def _lock_import_scope(*, organization_id, project_id, connection_id):
    organization = Organization.objects.select_for_update().get(pk=organization_id)
    project = Project.objects.select_for_update().select_related("organization").get(
        pk=project_id,
        organization=organization,
    )
    connection = IntegrationConnection.objects.select_for_update().select_related("project").get(
        pk=connection_id,
        project=project,
    )
    return project, connection


def _validate_import_request(*, project, connection, user, input_snapshot, date_start, date_end):
    require_project_action(project=project, user=user, action=Action.LAUNCH_JOB)
    prior = JobRun.objects.filter(
        project=project,
        handler="import_search_console_csv",
        input_snapshot__connection_id=connection.pk,
        input_snapshot__source_checksum=input_snapshot["source_checksum"],
    ).order_by("pk").first()
    if prior is not None:
        if prior.actor_id == user.pk and prior.input_snapshot == input_snapshot:
            return prior
        raise ValidationError("This source file is already bound to a different import request.")
    require_connection_capability(connection, IntegrationCapability.CSV_IMPORT)
    if not {
        IntegrationCapability.QUERY_METRICS,
        IntegrationCapability.PAGE_METRICS,
    } & set(connection.capabilities):
        raise ValidationError("Search metric imports require query or page metric capability.")
    if (date_end - date_start).days + 1 > connection.backfill_limit_days:
        raise ValidationError("Import date range exceeds this connection's bounded window.")
    return None


def _discard_staged_artifact(*, project, key):
    with project_artifact_barrier(project.organization_id, shared=True):
        if Artifact.objects.filter(key=key).exists():
            PendingArtifactCleanup.objects.filter(key=key).delete()
            return
        try:
            delete_project_artifact(project=project, key=key)
        except ArtifactStorageError:
            return
        PendingArtifactCleanup.objects.filter(key=key).delete()


def queue_search_console_csv_import(
    *, connection, user, content, date_start, date_end, search_type=SearchMetricObservation.SearchType.WEB,
    date_granularity=None,
):
    if type(date_start) is not date or type(date_end) is not date or date_end < date_start:
        raise ValidationError("Choose a valid import date range.")
    source_zone = ZoneInfo(SOURCE_TIMEZONE)
    if date_end > timezone.now().astimezone(source_zone).date():
        raise ValidationError("Import observations cannot be dated in the future.")
    if search_type not in SearchMetricObservation.SearchType.values:
        raise ValidationError("Choose a supported Search Console search type.")
    if date_granularity not in {None, SearchMetricObservation.TimeGranularity.DAY}:
        raise ValidationError("Only declared daily Search Console date exports are supported.")
    data = _read_upload(content)
    checksum = hashlib.sha256(data).hexdigest()
    input_snapshot = {
        "connection_id": connection.pk,
        "source_checksum": checksum,
        "date_start": date_start.isoformat(),
        "date_end": date_end.isoformat(),
        "search_type": search_type,
        "date_granularity": date_granularity,
    }
    request_hash = hashlib.sha256(
        json.dumps(input_snapshot, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    organization_id = connection.project.organization_id
    project_id = connection.project_id
    connection_id = connection.pk
    with project_artifact_barrier(organization_id, shared=True):
        try:
            with transaction.atomic():
                project, connection = _lock_import_scope(
                    organization_id=organization_id,
                    project_id=project_id,
                    connection_id=connection_id,
                )
                prior = _validate_import_request(
                    project=project,
                    connection=connection,
                    user=user,
                    input_snapshot=input_snapshot,
                    date_start=date_start,
                    date_end=date_end,
                )
                if prior is not None:
                    return prior
                key_stem = uuid4().hex
                key = f"{project_artifact_scope(project)}/{key_stem}.csv"
                PendingArtifactCleanup.objects.create(project=project, key=key)

            save_project_artifact(project=project, content=data, content_type="text/csv", key_stem=key_stem)
            committed = False
            with transaction.atomic():
                project, connection = _lock_import_scope(
                    organization_id=organization_id,
                    project_id=project_id,
                    connection_id=connection_id,
                )
                prior = _validate_import_request(
                    project=project,
                    connection=connection,
                    user=user,
                    input_snapshot=input_snapshot,
                    date_start=date_start,
                    date_end=date_end,
                )
                if prior is not None:
                    job = prior
                else:
                    staged_data = read_project_artifact(project=project, key=key)
                    if len(staged_data) != len(data) or hashlib.sha256(staged_data).hexdigest() != checksum:
                        raise ArtifactValidationError("Staged import artifact does not match its source.")
                    from jobs.services import queue_job

                    job = queue_job(
                        project=project,
                        actor=user,
                        handler="import_search_console_csv",
                        input_snapshot=input_snapshot,
                        config_snapshot={
                            "provider": connection.provider,
                            "external_property_id": connection.external_property_id,
                            "source_semantics": connection.source_semantics,
                            "source_semantics_version": connection.source_semantics_version,
                        },
                        idempotency_key=f"gsc-csv-{request_hash[:48]}",
                    )
                    Artifact.objects.create(
                        job=job,
                        project=project,
                        key=key,
                        content_type="text/csv",
                        size_bytes=len(data),
                    )
                    ImportExecutionState.objects.create(job=job)
                    PendingArtifactCleanup.objects.filter(key=key).delete()
                    committed = True
            if not committed:
                _discard_staged_artifact(project=project, key=key)
            return job
        except Exception:
            if "key" in locals():
                _discard_staged_artifact(project=project, key=key)
            raise


def _integer_metric(value, field):
    if value is None or value.strip() in {"", "-", "~"}:
        return None
    cleaned = value.strip().replace(",", "")
    if len(cleaned) > 19 or not cleaned.isdigit():
        raise _RowError("invalid_metric", field)
    number = int(cleaned)
    if number > 9223372036854775807:
        raise _RowError("invalid_metric", field)
    return number


def _decimal_metric(value, field, *, percent=False):
    if value is None or value.strip() in {"", "-", "~"}:
        return None
    cleaned = value.strip().replace(",", "")
    is_percent = cleaned.endswith("%")
    if is_percent:
        cleaned = cleaned[:-1]
    if len(cleaned) > 32 or not re.fullmatch(r"\d+(?:\.\d+)?", cleaned):
        raise _RowError("invalid_metric", field)
    try:
        number = Decimal(cleaned)
    except InvalidOperation:
        raise _RowError("invalid_metric", field) from None
    if not number.is_finite():
        raise _RowError("invalid_metric", field)
    if percent and is_percent:
        number /= 100
    decimal_places = max(-number.as_tuple().exponent, 0)
    if (
        number < 0
        or (percent and (number > 1 or decimal_places > 12))
        or (not percent and (number > Decimal("99999999.99999999") or decimal_places > 8))
    ):
        raise _RowError("invalid_metric", field)
    return number


def _normalize_property_page(value, property_origin):
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise _RowError("invalid_or_out_of_scope_page", "page")
    if "\\" in value or any(ord(character) < 32 for character in value):
        raise _RowError("invalid_or_out_of_scope_page", "page")
    try:
        parsed = urlsplit(value)
        if parsed.username is not None or parsed.password is not None or parsed.fragment:
            raise ValueError
        origin = normalize_origin(urlunsplit((parsed.scheme, parsed.netloc, "", "", "")))
    except (UnicodeError, ValueError, ValidationError):
        raise _RowError("invalid_or_out_of_scope_page", "page") from None
    if origin != property_origin:
        raise _RowError("invalid_or_out_of_scope_page", "page")
    path = quote(parsed.path or "/", safe="/%:@-._~!$&'()*+,;=")
    query = quote(parsed.query, safe="/%?:@-._~!$&'()*+,;=")
    normalized_origin = urlsplit(origin)
    normalized = urlunsplit((normalized_origin.scheme, normalized_origin.netloc, path, query, ""))
    if len(normalized) > 2048:
        raise _RowError("invalid_or_out_of_scope_page", "page")
    return normalized


def _dimension_value(*, dimension, value, connection, date_start, date_end):
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise _RowError("invalid_dimension", dimension)
    value = value.strip()
    result = {
        "date_start": date_start,
        "date_end": date_end,
        "time_granularity": SearchMetricObservation.TimeGranularity.RANGE,
        "query": "",
        "page": "",
        "country": "",
        "device": "",
        "search_appearance": "",
    }
    if dimension == SourceDimension.DATE:
        try:
            observed = date.fromisoformat(value)
        except ValueError:
            raise _RowError("invalid_date", "date") from None
        if not date_start <= observed <= date_end:
            raise _RowError("date_outside_range", "date")
        result.update(date_start=observed, date_end=observed, time_granularity=SearchMetricObservation.TimeGranularity.DAY)
    elif dimension == SourceDimension.PAGE:
        result["page"] = _normalize_property_page(value, connection.external_property_id)
    elif dimension == SourceDimension.QUERY:
        if len(value) > 1000:
            raise _RowError("invalid_dimension", "query")
        result["query"] = value
    elif dimension == SourceDimension.COUNTRY:
        if len(value) > 128:
            raise _RowError("invalid_dimension", "country")
        result["country"] = value
    elif dimension == SourceDimension.DEVICE:
        value = value.lower()
        if value not in {"desktop", "mobile", "tablet"}:
            raise _RowError("invalid_dimension", "device")
        result["device"] = value
    else:
        if len(value) > 128:
            raise _RowError("invalid_dimension", "search_appearance")
        result["search_appearance"] = value
    return result


def parse_search_console_csv(*, data, connection, date_start, date_end, search_type, date_granularity=None):
    if not isinstance(data, bytes):
        raise SearchConsoleCSVError("invalid_content")
    if len(data) > MAX_CSV_BYTES:
        raise SearchConsoleCSVError("file_too_large")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise SearchConsoleCSVError("invalid_encoding") from None
    if "\x00" in text:
        raise SearchConsoleCSVError("invalid_encoding")
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), dialect="excel", strict=True)
        headers = reader.fieldnames
    except csv.Error:
        raise SearchConsoleCSVError("malformed_csv") from None
    if not headers or len(headers) != len(set(headers)):
        raise SearchConsoleCSVError("invalid_headers")
    dimension_headers = [header for header in headers if header in DIMENSION_HEADERS]
    dimensions = [DIMENSION_HEADERS[header] for header in dimension_headers]
    if len(dimensions) != 1 or set(headers) != {*METRIC_HEADERS, *dimension_headers}:
        raise SearchConsoleCSVError("unsupported_layout")
    dimension = dimensions[0]
    dimension_header = dimension_headers[0]
    if (
        (dimension == SourceDimension.DATE and date_granularity != SearchMetricObservation.TimeGranularity.DAY)
        or (dimension != SourceDimension.DATE and date_granularity is not None)
    ):
        raise SearchConsoleCSVError("unsupported_time_granularity", dimensions=[dimension])
    observations = []
    errors = []
    grains = set()
    rows_seen = 0
    try:
        for row in reader:
            if rows_seen >= MAX_CSV_ROWS:
                raise SearchConsoleCSVError("too_many_rows", dimensions=[dimension], rows_seen=rows_seen + 1)
            rows_seen += 1
            try:
                if None in row or any(not isinstance(value, str) for value in row.values()):
                    raise _RowError("malformed_row")
                values = _dimension_value(
                    dimension=dimension,
                    value=row[dimension_header],
                    connection=connection,
                    date_start=date_start,
                    date_end=date_end,
                )
                unavailable = [
                    field.lower() for field in METRIC_HEADERS if row[field].strip() in {"", "-", "~"}
                ]
                values.update(
                    source_row=rows_seen,
                    search_type=search_type,
                    clicks=_integer_metric(row["Clicks"], "clicks"),
                    impressions=_integer_metric(row["Impressions"], "impressions"),
                    ctr=_decimal_metric(row["CTR"], "ctr", percent=True),
                    position=_decimal_metric(row["Position"], "position"),
                    unavailable_metrics=unavailable,
                )
                if values["clicks"] is not None and values["impressions"] is not None and values["clicks"] > values["impressions"]:
                    raise _RowError("invalid_metric", "clicks")
                grain = tuple(values[field] for field in (
                    "date_start", "date_end", "time_granularity", "search_type", "query", "page",
                    "country", "device", "search_appearance",
                ))
                if grain in grains:
                    raise _RowError("duplicate_grain")
                grains.add(grain)
                observations.append(values)
            except _RowError as error:
                errors.append((rows_seen, error.category, error.field))
    except csv.Error:
        raise SearchConsoleCSVError("malformed_csv", dimensions=[dimension], rows_seen=rows_seen) from None
    if rows_seen == 0:
        raise SearchConsoleCSVError("empty_file", dimensions=[dimension])
    return ParsedSearchConsoleCSV(dimension, rows_seen, tuple(observations), tuple(errors))


def _coverage(*, dimension, rows_seen, rows_imported, errors, structural_error=""):
    categories = Counter(category for _row, category, _field in errors)
    if structural_error:
        categories[structural_error] += max(rows_seen, 1)
    return {
        "export_shape": dimension or "unknown",
        "source_rows": rows_seen,
        "imported_rows": rows_imported,
        "error_categories": dict(sorted(categories.items())),
        "source_completeness": "provider_export_unknown",
        "marked_unavailable_values_preserved": True,
        "numeric_zero_may_mean_provider_unavailable": True,
    }


def _finish_cancelled(job, category="", *, actual_units=0):
    job.status = JobStatus.CANCELLED
    job.error_category = category
    job.save(update_fields=["status", "error_category", "updated_at"])
    ImportExecutionState.objects.filter(job=job).update(retry_after=None)
    if UsageReservation.objects.filter(job=job, state=UsageReservation.State.RESERVED).exists():
        settle_usage(job=job, actual_units=actual_units)


def _execute_search_console_csv_import(job_id):
    identity = JobRun.objects.filter(pk=job_id).values_list("organization_id", "project_id").first()
    if identity is None:
        return False
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=identity[0])
        project = Project.objects.select_for_update().select_related("organization").get(
            pk=identity[1],
            organization_id=identity[0],
        )
        job = JobRun.objects.select_for_update(no_key=True).select_related("actor").filter(
            pk=job_id,
            organization_id=identity[0],
            project=project,
        ).first()
        if job is None or job.handler != "import_search_console_csv":
            return False
        if job.status != JobStatus.QUEUED:
            return False
        execution_state = ImportExecutionState.objects.select_for_update().filter(job=job).first()
        if execution_state is None:
            raise ValidationError("Import execution state is unavailable.")
        if JobCancellation.objects.filter(job=job).exists():
            _finish_cancelled(job)
            return True
        try:
            require_project_action(project=job.project, user=job.actor, action=Action.LAUNCH_JOB)
        except PermissionDenied:
            _finish_cancelled(job, "actor_revoked")
            return True
        denied = usage_denial(job=job)
        if denied:
            _finish_cancelled(job, denied)
            return True
        if execution_state.retry_after is not None and execution_state.retry_after > timezone.now():
            return False

        data_snapshot = validate_search_console_import_input(job.input_snapshot)
        del data_snapshot
        connection = IntegrationConnection.objects.select_for_update().select_related("project").filter(
            pk=job.input_snapshot["connection_id"],
            project_id=job.project_id,
        ).first()
        artifacts = list(Artifact.objects.select_for_update().filter(job=job, project=job.project, content_type="text/csv")[:2])
        if connection is None:
            _finish_cancelled(job, "source_scope_revoked")
            return True
        try:
            connection = require_connection_capability(connection, IntegrationCapability.CSV_IMPORT)
        except ValidationError:
            _finish_cancelled(job, "source_scope_revoked")
            return True
        if len(artifacts) != 1:
            job.status = JobStatus.RUNNING
            job.save(update_fields=["status", "updated_at"])
            job.status = JobStatus.FAILED
            job.error_category = "artifact_unavailable"
            job.save(update_fields=["status", "error_category", "updated_at"])
            ImportExecutionState.objects.filter(job=job).update(retry_after=None)
            if UsageReservation.objects.filter(job=job, state=UsageReservation.State.RESERVED).exists():
                settle_usage(job=job, actual_units=0)
            return True
        artifact = artifacts[0]
        start = date.fromisoformat(job.input_snapshot["date_start"])
        end = date.fromisoformat(job.input_snapshot["date_end"])
        checksum = job.input_snapshot["source_checksum"]
        search_type = job.input_snapshot["search_type"]
        date_granularity = job.input_snapshot["date_granularity"]
        if (end - start).days + 1 > connection.backfill_limit_days:
            _finish_cancelled(job, "source_scope_revoked")
            return True

        parsed = None
        structural_error = ""
        try:
            source = read_project_artifact(project=job.project, key=artifact.key)
            if len(source) != artifact.size_bytes or hashlib.sha256(source).hexdigest() != checksum:
                raise SearchConsoleCSVError("source_mismatch")
            parsed = parse_search_console_csv(
                data=source,
                connection=connection,
                date_start=start,
                date_end=end,
                search_type=search_type,
                date_granularity=date_granularity,
            )
        except ArtifactStorageError:
            execution_state.storage_failures += 1
            if execution_state.storage_failures < 3:
                execution_state.retry_after = timezone.now() + timedelta(minutes=2 ** (execution_state.storage_failures - 1))
                execution_state.save(update_fields=["storage_failures", "retry_after", "updated_at"])
                job.dispatch_error = "artifact_storage_unavailable"
                job.save(update_fields=["dispatch_error", "updated_at"])
                return False
            execution_state.retry_after = None
            execution_state.save(update_fields=["storage_failures", "retry_after", "updated_at"])
            job.status = JobStatus.RUNNING
            job.save(update_fields=["status", "updated_at"])
            job.status = JobStatus.FAILED
            job.error_category = "artifact_storage_unavailable"
            job.output = {"rows_seen": 0, "rows_imported": 0, "row_errors": 0, "export_shape": "unknown"}
            job.save(update_fields=["status", "error_category", "output", "updated_at"])
            record_import_run(
                connection=connection,
                job=job,
                source_artifact=artifact,
                source_format=ImportRun.SourceFormat.SEARCH_CONSOLE_CSV,
                source_checksum=checksum,
                date_start=start,
                date_end=end,
                observation_dimensions=[],
                source_timezone=SOURCE_TIMEZONE,
                coverage_state=ImportRun.CoverageState.UNAVAILABLE,
                coverage=_coverage(
                    dimension="",
                    rows_seen=0,
                    rows_imported=0,
                    errors=[],
                    structural_error="artifact_storage_unavailable",
                ),
                status=ImportRun.Status.UNAVAILABLE,
            )
            JobStep.objects.create(
                job=job,
                sequence=1,
                name="Read Search Console CSV",
                status=JobStep.Status.FAILED,
                progress_percent=100,
                error_category="artifact_storage_unavailable",
                output={"storage_attempts": execution_state.storage_failures},
            )
            if UsageReservation.objects.filter(job=job, state=UsageReservation.State.RESERVED).exists():
                settle_usage(job=job, actual_units=0)
            return True
        except (ArtifactNotFound, ArtifactValidationError):
            structural_error = "artifact_unavailable"
        except SearchConsoleCSVError as error:
            structural_error = error.category
            parsed = ParsedSearchConsoleCSV(
                error.dimensions[0] if error.dimensions else "",
                error.rows_seen,
                (),
                (),
            )

        if JobCancellation.objects.filter(job=job).exists():
            _finish_cancelled(job, actual_units=1)
            return True
        try:
            require_project_action(project=job.project, user=job.actor, action=Action.LAUNCH_JOB)
            connection = require_connection_capability(
                connection,
                IntegrationCapability.CSV_IMPORT,
                dimensions=[parsed.dimension] if parsed and parsed.dimension else [],
            )
            if parsed and parsed.dimension == SourceDimension.QUERY and IntegrationCapability.QUERY_METRICS not in connection.capabilities:
                raise ValidationError("Query metric capability is unavailable.")
            if parsed and parsed.dimension == SourceDimension.PAGE and IntegrationCapability.PAGE_METRICS not in connection.capabilities:
                raise ValidationError("Page metric capability is unavailable.")
            if parsed and parsed.dimension not in {SourceDimension.QUERY, SourceDimension.PAGE, ""} and not {
                IntegrationCapability.QUERY_METRICS,
                IntegrationCapability.PAGE_METRICS,
            } & set(connection.capabilities):
                raise ValidationError("Search metric capability is unavailable.")
        except (PermissionDenied, ValidationError):
            _finish_cancelled(job, "source_scope_revoked", actual_units=1)
            return True

        job.status = JobStatus.RUNNING
        job.dispatch_error = ""
        job.save(update_fields=["status", "dispatch_error", "updated_at"])

        rows_seen = parsed.rows_seen if parsed else 0
        errors = list(parsed.errors if parsed else ())
        observation_values = []
        if not structural_error:
            for values in parsed.observations:
                observation_values.append((values, SearchMetricObservation.hash_grain(connection.pk, values)))
            existing = set(SearchMetricObservation.objects.filter(
                grain_hash__in=[grain_hash for _values, grain_hash in observation_values],
            ).values_list("grain_hash", flat=True))
            retained = []
            for values, grain_hash in observation_values:
                if grain_hash in existing:
                    errors.append((values["source_row"], "source_grain_conflict", ""))
                else:
                    retained.append((values, grain_hash))
            observation_values = retained

        rows_imported = len(observation_values)
        if structural_error or not rows_imported:
            import_status = ImportRun.Status.FAILED
            coverage_state = ImportRun.CoverageState.UNAVAILABLE if not rows_seen else ImportRun.CoverageState.PARTIAL
            job_status = JobStatus.FAILED
        elif errors:
            import_status = ImportRun.Status.PARTIALLY_SUCCEEDED
            coverage_state = ImportRun.CoverageState.PARTIAL
            job_status = JobStatus.PARTIALLY_SUCCEEDED
        else:
            import_status = ImportRun.Status.SUCCEEDED
            coverage_state = ImportRun.CoverageState.COMPLETE
            job_status = JobStatus.SUCCEEDED

        job.status = job_status
        job.error_category = structural_error or ("row_errors" if errors else "")
        job.output = {
            "rows_seen": rows_seen,
            "rows_imported": rows_imported,
            "row_errors": rows_seen - rows_imported,
            "export_shape": parsed.dimension if parsed else "unknown",
        }
        job.save(update_fields=["status", "error_category", "output", "updated_at"])
        execution_state.retry_after = None
        execution_state.save(update_fields=["retry_after", "updated_at"])
        coverage = _coverage(
            dimension=parsed.dimension if parsed else "",
            rows_seen=rows_seen,
            rows_imported=rows_imported,
            errors=errors,
            structural_error=structural_error,
        )
        run = record_import_run(
            connection=connection,
            job=job,
            source_artifact=artifact,
            source_format=ImportRun.SourceFormat.SEARCH_CONSOLE_CSV,
            source_checksum=checksum,
            date_start=start,
            date_end=end,
            observation_dimensions=[parsed.dimension] if parsed and parsed.dimension else [],
            source_timezone=SOURCE_TIMEZONE,
            coverage_state=coverage_state,
            coverage=coverage,
            status=import_status,
            rows_seen=rows_seen,
            rows_imported=rows_imported,
            row_errors=rows_seen - rows_imported,
        )
        observations = [
            SearchMetricObservation(import_run=run, grain_hash=grain_hash, **values)
            for values, grain_hash in observation_values
        ]
        for observation in observations:
            observation.full_clean(validate_unique=False, validate_constraints=False)
        SearchMetricObservation.objects.bulk_create(observations)
        error_by_row = {row: (category, field) for row, category, field in errors}
        ImportRowError.objects.bulk_create([
            ImportRowError(import_run=run, source_row=row, category=category, field=field)
            for row, (category, field) in sorted(error_by_row.items())
        ])
        JobStep.objects.create(
            job=job,
            sequence=1,
            name="Validate Search Console CSV",
            status=JobStep.Status.FAILED if structural_error else JobStep.Status.SUCCEEDED,
            progress_percent=50,
            error_category=structural_error,
            output={"rows_seen": rows_seen, "export_shape": parsed.dimension if parsed else "unknown"},
        )
        JobStep.objects.create(
            job=job,
            sequence=2,
            name="Persist search metrics",
            status=JobStep.Status.FAILED if job_status != JobStatus.SUCCEEDED else JobStep.Status.SUCCEEDED,
            progress_percent=100,
            error_category=job.error_category,
            output={"rows_imported": rows_imported, "row_errors": rows_seen - rows_imported},
        )
        if UsageReservation.objects.filter(job=job, state=UsageReservation.State.RESERVED).exists():
            settle_usage(job=job, actual_units=1)
    return True


def execute_search_console_csv_import(job_id):
    try:
        return _execute_search_console_csv_import(job_id)
    except Exception as error:
        logger.error(
            "search_console.import_failed",
            extra={"error_type": type(error).__name__},
        )
        organization_id = JobRun.objects.filter(pk=job_id).values_list("organization_id", flat=True).first()
        if organization_id is None:
            return True
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=organization_id)
            job = JobRun.objects.select_for_update(no_key=True).filter(
                pk=job_id,
                organization_id=organization_id,
                handler="import_search_console_csv",
                status__in=[JobStatus.QUEUED, JobStatus.RUNNING],
            ).first()
            if job is not None:
                if job.status == JobStatus.QUEUED:
                    job.status = JobStatus.RUNNING
                    job.save(update_fields=["status", "updated_at"])
                job.status = JobStatus.FAILED
                job.error_category = "handler_failed"
                job.save(update_fields=["status", "error_category", "updated_at"])
                ImportExecutionState.objects.filter(job=job).update(retry_after=None)
                if UsageReservation.objects.filter(job=job, state=UsageReservation.State.RESERVED).exists():
                    settle_usage(job=job, actual_units=1)
        return True


def reconcile_search_console_artifacts(*, limit=100, stale_seconds=300):
    if type(limit) is not int or not 1 <= limit <= 100 or type(stale_seconds) is not int or stale_seconds < 60:
        raise ValidationError("Invalid Search Console artifact cleanup limit.")
    cutoff = timezone.now() - timedelta(seconds=stale_seconds)
    candidates = list(PendingArtifactCleanup.objects.filter(created_at__lte=cutoff).order_by("created_at", "pk").values_list(
        "pk", "project__organization_id", "project_id",
    )[:limit])
    removed = 0
    # Leave time for other recovery work in the 15-second reconciliation task.
    deadline, unavailable = monotonic() + 3, set()
    for cleanup_id, organization_id, project_id in candidates:
        remaining_ms = int((deadline - monotonic()) * 1000)
        if remaining_ms <= 0:
            break
        if organization_id in unavailable:
            continue
        try:
            with project_artifact_barrier(organization_id, shared=True,
                        timeout_ms=min(WRITER_ADMISSION_TIMEOUT_MS, remaining_ms)), transaction.atomic():
                Organization.objects.select_for_update().get(pk=organization_id)
                project = Project.objects.select_for_update().get(pk=project_id, organization_id=organization_id)
                cleanup = PendingArtifactCleanup.objects.select_for_update(skip_locked=True).filter(
                    pk=cleanup_id,
                    project=project,
                ).first()
                if cleanup is None:
                    continue
                if Artifact.objects.filter(key=cleanup.key).exists():
                    cleanup.delete()
                    continue
                try:
                    delete_project_artifact(project=project, key=cleanup.key)
                except ArtifactStorageError:
                    continue
                cleanup.delete()
                removed += 1
        except ArtifactStorageError:
            unavailable.add(organization_id)
    return removed
