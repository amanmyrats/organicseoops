"""Bounded official Yandex query-by-URL exports; raw CSV is never retained."""
import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from io import StringIO
import json
import re
from urllib.parse import urlsplit

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from jobs.models import JobCancellation, JobRun, JobStatus, JobStep
from tenancy.models import Organization, Project, normalize_origin
from tenancy.services import Action, project_has_origin, require_project_action

HANDLER = "import_yandex_webmaster_csv"
METHOD = "yandex-query-url-csv-v1"
MAX_BYTES = 1048576
MAX_ROWS = 100
MAX_EVIDENCE_BYTES = 24576
HEADERS = (
    ("date", "host", "url", "query", "region", "clicks", "impressions", "ranking"),
    ("дата", "хост", "url", "запрос", "регион", "клики", "показы", "позиция"),
)


def _day(value):
    if type(value) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValidationError("Use ISO calendar dates (YYYY-MM-DD).")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValidationError("Use valid calendar dates.") from None


def _text(value, limit):
    if (type(value) is not str or not 1 <= len(value) <= limit or value != value.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValidationError("Export contains an unsupported field.")
    return value


def _row(values, *, origin, start, end):
    if len(values) != 8:
        raise ValidationError("Use the eight official Yandex export columns.")
    day, host, url, query, region, clicks, impressions, ranking = values
    if not start <= _day(day) <= end:
        raise ValidationError("Export dates must fall inside the declared window.")
    _text(host, 512)
    _text(url, 2048)
    try:
        parts = urlsplit(url)
        url_origin = normalize_origin(parts.scheme + "://" + parts.netloc)
        host_origin = normalize_origin(host if "://" in host else parts.scheme + "://" + host)
    except (ValueError, ValidationError):
        raise ValidationError("Export origin is invalid.") from None
    if (url_origin != origin or host_origin != origin or parts.fragment or "\\" in url
        or parts.username is not None or parts.password is not None):
        raise ValidationError("Every export URL and host must match the selected exact origin.")
    _text(query, 1000)
    _text(region, 200)
    if any(type(value) is not str or not re.fullmatch(r"[0-9]{1,12}", value) for value in (clicks, impressions)):
        raise ValidationError("Clicks and impressions must be nonnegative integers.")
    position = None
    if ranking:
        if type(ranking) is not str or not re.fullmatch(r"[0-9]{1,7}(?:[.,][0-9]{1,8})?", ranking):
            raise ValidationError("Ranking must be a positive decimal or empty.")
        try:
            position = Decimal(ranking.replace(",", "."))
        except InvalidOperation:
            raise ValidationError("Ranking is invalid.") from None
        if not position.is_finite() or position <= 0:
            raise ValidationError("Ranking must be positive.")
    return {"date": day, "host": host, "url": url, "query": query, "region": region,
        "clicks": int(clicks), "impressions": int(impressions),
        "ranking": str(position) if position is not None else None}


def parse_export(content, *, origin, date_start, date_end):
    origin = normalize_origin(origin)
    start, end = _day(date_start), _day(date_end)
    if start > end or (end - start).days >= 550:
        raise ValidationError("Choose an inclusive window of at most550days.")
    if type(content) is not bytes or not 1 <= len(content) <= MAX_BYTES:
        raise ValidationError("Choose a CSV export of at most1MiB.")
    try:
        text = content.decode("utf-8-sig")
        delimiter = next((separator for separator in (",", ";")
            if tuple(cell.strip().casefold() for cell in next(csv.reader(StringIO(text), delimiter=separator, strict=True))) in HEADERS), None)
        if delimiter is None:
            raise ValidationError("Use the official English or Russian eight-column CSV header.")
        reader = csv.reader(StringIO(text, newline=""), delimiter=delimiter, strict=True)
        next(reader)
        rows, grains = [], set()
        for values in reader:
            if len(rows) >= MAX_ROWS:
                raise ValidationError("Split exports into at most100rows; no rows were imported.")
            row = _row(values, origin=origin, start=start, end=end)
            grain = tuple(row[key] for key in ("date", "url", "query", "region"))
            if grain in grains:
                raise ValidationError("Duplicate date/URL/query/region rows are unsupported.")
            grains.add(grain)
            rows.append(row)
    except (UnicodeError, csv.Error, StopIteration):
        raise ValidationError("Use a valid UTF-8 Yandex CSV export.") from None
    if not rows:
        raise ValidationError("The export has no metric rows; absence is not zero traffic.")
    evidence = {"provider": "yandex_webmaster", "method": METHOD, "origin": origin,
        "date_start": date_start, "date_end": date_end, "source_sha256": sha256(content).hexdigest(),
        "rows": rows, "coverage": "customer_supplied_partial_export", "timezone": "unspecified_by_export"}
    if len(json.dumps(evidence).encode()) > MAX_EVIDENCE_BYTES:
        raise ValidationError("Split exports into at most24KiB of parsed evidence; no rows were imported.")
    return evidence


def validate_input(data):
    if type(data) is not dict or set(data) != {"evidence", "authorized"} or data["authorized"] is not True:
        raise ValidationError("Explicit source authorization is required.")
    evidence = data["evidence"]
    if (type(evidence) is not dict or set(evidence) != {"provider", "method", "origin", "date_start", "date_end",
        "source_sha256", "rows", "coverage", "timezone"} or evidence["provider"] != "yandex_webmaster"
        or evidence["method"] != METHOD or evidence["coverage"] != "customer_supplied_partial_export"
        or evidence["timezone"] != "unspecified_by_export"
        or type(evidence["source_sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", evidence["source_sha256"])
        or type(evidence["rows"]) is not list or not 1 <= len(evidence["rows"]) <= MAX_ROWS):
        raise ValidationError("Yandex source evidence is invalid.")
    if normalize_origin(evidence["origin"]) != evidence["origin"]:
        raise ValidationError("An exact normalized origin is required.")
    start, end = _day(evidence["date_start"]), _day(evidence["date_end"])
    if start > end or (end - start).days >= 550:
        raise ValidationError("Unsupported Yandex window.")
    grains = set()
    for row in evidence["rows"]:
        if (type(row) is not dict or set(row) != {"date", "host", "url", "query", "region", "clicks", "impressions", "ranking"}
            or any(type(row[key]) is not int or row[key] < 0 for key in ("clicks", "impressions"))):
            raise ValidationError("Invalid Yandex row.")
        values = [row[key] for key in ("date", "host", "url", "query", "region")]
        values += [str(row["clicks"]), str(row["impressions"]), row["ranking"] if row["ranking"] is not None else ""]
        if _row(values, origin=evidence["origin"], start=start, end=end) != row:
            raise ValidationError("Yandex row is not normalized.")
        grain = tuple(row[key] for key in ("date", "url", "query", "region"))
        if grain in grains:
            raise ValidationError("Duplicate Yandex grain.")
        grains.add(grain)
    if len(json.dumps(evidence).encode()) > MAX_EVIDENCE_BYTES:
        raise ValidationError("Yandex evidence exceeds24KiB.")
    return {}, False


def validate_job(job, *, current=False):
    validate_input(job.input_snapshot)
    if (job.config_snapshot != {"method": METHOD} or job.method_version != METHOD or job.retry_of_id
        or job.schedule_id or job.scheduled_for or job.output and job.output != {"row_count": len(job.input_snapshot["evidence"]["rows"])}):
        raise ValidationError("Yandex exports require a manual source upload.")
    if current:
        require_project_action(project=job.project, user=job.actor, action=Action.MANAGE_PROJECT)
        require_project_action(project=job.project, user=job.actor, action=Action.LAUNCH_JOB)
        if not project_has_origin(job.project, job.input_snapshot["evidence"]["origin"]):
            raise PermissionDenied


def source_current(job):
    try:
        job.project = Project.objects.select_related("organization").get(pk=job.project_id, organization_id=job.organization_id)
        validate_job(job, current=True)
        return True
    except (PermissionDenied, ValidationError, Project.DoesNotExist):
        return False


def queue_import(*, project, actor, content, origin, date_start, date_end, idempotency_key):
    if type(idempotency_key) is not str or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", idempotency_key):
        raise ValidationError("A bounded import request key is required.")
    require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
    require_project_action(project=project, user=actor, action=Action.LAUNCH_JOB)
    if not project_has_origin(project, normalize_origin(origin)):
        raise PermissionDenied
    evidence = parse_export(content, origin=origin, date_start=date_start, date_end=date_end)
    from jobs.services import queue_job
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().select_related("organization").get(pk=project.pk, organization_id=project.organization_id)
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        require_project_action(project=project, user=actor, action=Action.LAUNCH_JOB)
        if not project_has_origin(project, evidence["origin"]):
            raise PermissionDenied
        if not JobRun.objects.filter(project=project, handler=HANDLER, idempotency_key=idempotency_key).exists():
            duplicate = JobRun.objects.filter(project=project, handler=HANDLER, actor=actor,
                method_version=METHOD, status__in=[JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.SUCCEEDED],
                input_snapshot__evidence__source_sha256=evidence["source_sha256"],
                input_snapshot__evidence__origin=evidence["origin"], input_snapshot__evidence__date_start=date_start,
                input_snapshot__evidence__date_end=date_end).first()
            if duplicate:
                return duplicate
        return queue_job(project=project, actor=actor, handler=HANDLER, input_snapshot={"evidence": evidence, "authorized": True},
            config_snapshot={"method": METHOD}, idempotency_key=idempotency_key)


def execute_import(job_id):
    organization_id = JobRun.objects.filter(pk=job_id, handler=HANDLER).values_list("organization_id", flat=True).first()
    if organization_id is None:
        return False
    # Bounded offline work commits atomically; a crash leaves QUEUED for redispatch.
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=organization_id)
        job = JobRun.objects.select_for_update(no_key=True).select_related("project__organization", "actor").get(pk=job_id)
        if job.status != JobStatus.QUEUED:
            return False
        Project.objects.select_for_update().get(pk=job.project_id)
        from jobs.usage import settle_usage, usage_denial
        denial = "cancel_requested" if JobCancellation.objects.filter(job=job).exists() else ""
        if not denial:
            try:
                validate_job(job, current=True)
            except (ValidationError, PermissionDenied):
                denial = "source_or_actor_revoked"
        if not denial:
            denial = usage_denial(job=job)
        if denial:
            job.status, job.error_category = JobStatus.CANCELLED, denial
            job.save(update_fields=["status", "error_category", "updated_at"])
            if hasattr(job, "usage"):
                settle_usage(job=job, actual_units=0)
            return False
        job.status = JobStatus.RUNNING
        job.save(update_fields=["status", "updated_at"])
        job.output = {"row_count": len(job.input_snapshot["evidence"]["rows"])}
        JobStep.objects.create(job=job, sequence=1, name="Finalize Yandex export evidence", status=JobStep.Status.SUCCEEDED,
            progress_percent=100, output=job.output)
        job.status = JobStatus.SUCCEEDED
        job.save(update_fields=["status", "output", "updated_at"])
        settle_usage(job=job, actual_units=1)
        return True
