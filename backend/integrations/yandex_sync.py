"""Bounded Yandex aggregate history jobs; source offsets and unknowns stay explicit."""
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import json
import re
from urllib.parse import quote, urlencode
from uuid import uuid4

from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from jobs.models import JobCancellation, JobRun, JobStatus, JobStep
from jobs.usage import settle_usage, usage_denial
from tenancy.models import Organization, Project
from tenancy.services import Action, project_has_origin, require_project_action
from .models import IntegrationConnection, SyncCursor
from .yandex_models import YandexOAuthGrant
from .yandex_oauth import _application, _authority, _tokens, credential, seal, unseal, verified_host
from .yandex_transport import YandexError, yandex_json

HANDLER = "sync_yandex_webmaster"
METHOD = "yandex-site-history-v1"
INDICATORS = ("TOTAL_SHOWS", "TOTAL_CLICKS", "AVG_SHOW_POSITION", "AVG_CLICK_POSITION")


def _day(value):
    if type(value) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValidationError("Choose ISO calendar dates.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValidationError("Choose valid calendar dates.") from None


def validate_input(data):
    if (type(data) is not dict or set(data) != {"grant_id", "date_start", "date_end"}
        or type(data["grant_id"]) is not int or data["grant_id"] < 1):
        raise ValidationError("Choose a Yandex grant and bounded history window.")
    start, end = _day(data["date_start"]), _day(data["date_end"])
    if not 0 <= (end - start).days < 31:
        raise ValidationError("Choose at most31 inclusive calendar days.")
    return {}, False


def bind_connection(grant):
    if grant.connection_id:
        return grant.connection
    connection = IntegrationConnection.objects.select_for_update().filter(project=grant.project,
        provider="yandex_webmaster", external_property_id=grant.origin).first()
    if connection is None:
        connection = IntegrationConnection(project=grant.project, provider="yandex_webmaster", external_property_id=grant.origin,
            capabilities=["api_sync"], available_dimensions=["date"], source_semantics="yandex_site_history",
            source_semantics_version=METHOD, timezone="source_timestamp_offset", backfill_limit_days=90)
    elif YandexOAuthGrant.objects.filter(connection=connection).exclude(pk=grant.pk).exclude(state="revoked").exists():
        raise ValidationError("This Yandex connection belongs to another retained grant.")
    connection.credential_reference = uuid4()
    connection.state = "active"
    connection.save()
    cursor, _ = SyncCursor.objects.get_or_create(project=grant.project, connection=connection)
    cursor.status, cursor.position, cursor.quota_state, cursor.error_category = "idle", {}, "available", ""
    cursor.coverage_start = cursor.coverage_end = cursor.fresh_through = cursor.retry_after = None
    cursor.last_attempt_at = cursor.last_success_at = None
    cursor.revision += 1
    cursor.save()
    YandexOAuthGrant.objects.filter(pk=grant.pk, connection__isnull=True).update(connection=connection)
    grant.connection = connection
    return connection


def validate_job(job, *, current=False, allow_refresh=False):
    validate_input(job.input_snapshot)
    config = job.config_snapshot
    if (type(config) is not dict or set(config) != {"method", "connection_id", "credential_reference", "origin", "user_id", "host_id"}
        or config["method"] != METHOD or job.method_version != METHOD or job.retry_of_id or job.schedule_id or job.scheduled_for
        or type(config["connection_id"]) is not int or config["connection_id"] < 1):
        raise ValidationError("Yandex sync requires an explicit manual source selection.")
    if current:
        require_project_action(project=job.project, user=job.actor, action=Action.MANAGE_PROJECT)
        require_project_action(project=job.project, user=job.actor, action=Action.LAUNCH_JOB)
        grant = YandexOAuthGrant.objects.select_related("project__organization", "actor", "connection").get(
            pk=job.input_snapshot["grant_id"], project_id=job.project_id, organization_id=job.organization_id)
        _authority(job.project_id, grant.actor, grant.origin)
        connection = grant.connection
        if (grant.state != "active" or grant.refresh_started_at and not allow_refresh or connection is None
            or connection.state != "active" or not project_has_origin(grant.project, grant.origin)
            or config != {"method": METHOD, "connection_id": connection.pk, "credential_reference": str(connection.credential_reference),
                "origin": grant.origin, "user_id": grant.user_id, "host_id": grant.host_id}
            or connection.project_id != job.project_id or connection.provider != "yandex_webmaster"
            or connection.external_property_id != grant.origin):
            raise PermissionDenied
        return grant


def source_current(job):
    try:
        validate_job(job, current=True)
        return True
    except (ObjectDoesNotExist, PermissionDenied, ValidationError):
        return False


def queue_sync(*, project, actor, grant_id, expected_revision, date_start, date_end, idempotency_key):
    from jobs.services import queue_job
    data = {"grant_id": grant_id, "date_start": date_start, "date_end": date_end}
    validate_input(data)
    if type(idempotency_key) is not str or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", idempotency_key):
        raise ValidationError("A bounded request key is required.")
    today = timezone.now().date()
    if not today - timedelta(days=90) <= _day(date_start) <= _day(date_end) < today:
        raise ValidationError("Choose past dates within the local90-day request bound; provider availability is not guaranteed.")
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().select_related("organization").get(pk=project.pk)
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        grant = YandexOAuthGrant.objects.select_for_update(of=("self",)).select_related("project", "connection").get(
            pk=grant_id, project=project, organization_id=project.organization_id)
        existing = JobRun.objects.filter(project=project, handler=HANDLER, idempotency_key=idempotency_key).first()
        if existing:
            if existing.actor_id != actor.pk or existing.input_snapshot != data:
                raise ValidationError("This request key belongs to another sync selection.")
            return existing
        if grant.state != "active" or grant.refresh_started_at or type(expected_revision) is not int or grant.revision != expected_revision:
            raise ValidationError("Refresh Yandex connection status before selecting a sync.")
        _authority(project.pk, grant.actor, grant.origin)
        connection = bind_connection(grant)
        config = {"method": METHOD, "connection_id": connection.pk, "credential_reference": str(connection.credential_reference),
            "origin": grant.origin, "user_id": grant.user_id, "host_id": grant.host_id}
        if JobRun.objects.filter(project=project, handler=HANDLER, input_snapshot__grant_id=grant.pk,
            status__in=[JobStatus.QUEUED, JobStatus.RUNNING]).exists():
            raise ValidationError("This Yandex source already has unfinished work.")
        cursor = SyncCursor.objects.select_for_update().get(connection=connection)
        if cursor.retry_after and cursor.retry_after > timezone.now() or cursor.last_attempt_at and cursor.last_attempt_at > timezone.now() - timedelta(minutes=1):
            raise ValidationError("Wait for this source's retry/throttle interval.")
        job = queue_job(project=project, actor=actor, handler=HANDLER, input_snapshot=data, config_snapshot=config,
            idempotency_key=idempotency_key)
        return job


def _checkpoint(job_id, *, allow_refresh=False):
    job = JobRun.objects.select_related("project__organization", "actor").get(pk=job_id, handler=HANDLER)
    if job.status != JobStatus.RUNNING or JobCancellation.objects.filter(job=job).exists():
        raise PermissionDenied
    grant = validate_job(job, current=True, allow_refresh=allow_refresh)
    denial = usage_denial(job=job)
    if denial:
        raise YandexError(denial)
    return grant


@sensitive_variables()
def _access_token(job_id):
    grant = _checkpoint(job_id)
    tokens = unseal("tokens", grant.encrypted_tokens)
    if grant.expires_at > timezone.now() + timedelta(minutes=5):
        return credential(tokens.get("access_token"))
    refresh = credential(tokens.get("refresh_token"))
    app = _application(grant.application_id)
    secret = credential(unseal("application", app.encrypted_secret))
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=grant.organization_id)
        current = YandexOAuthGrant.objects.select_for_update().get(pk=grant.pk)
        _checkpoint(job_id)
        current.refresh_started_at = timezone.now()
        current.revision += 1
        current.save(update_fields=["refresh_started_at", "revision", "updated_at"])
        marker = current.refresh_started_at
    payload = yandex_json("/token", form={"grant_type": "refresh_token", "refresh_token": refresh,
        "client_id": app.client_id, "client_secret": secret}, checkpoint=lambda: _checkpoint(job_id, allow_refresh=True), limit=16384)
    # Persist issued material before parsing metadata or checking authority again.
    access = credential(payload.get("access_token"))
    refreshed = payload.get("refresh_token")
    try:
        refreshed = credential(refreshed) if refreshed else refresh
    except ValidationError:
        refreshed = refresh
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=grant.organization_id)
        current = YandexOAuthGrant.objects.select_for_update().get(pk=grant.pk)
        if current.refresh_started_at != marker or current.state == "revoked":
            raise PermissionDenied
        current.encrypted_tokens = seal("tokens", {"access_token": access, "refresh_token": refreshed})
        current.revision += 1
        current.save(update_fields=["encrypted_tokens", "revision", "updated_at"])
    _parsed, expiry = _tokens(payload)
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=grant.organization_id)
        current = YandexOAuthGrant.objects.select_for_update().get(pk=grant.pk)
        if current.refresh_started_at != marker or current.state == "revoked":
            raise PermissionDenied
        current.expires_at, current.refresh_started_at = expiry, None
        current.revision += 1
        current.save(update_fields=["expires_at", "refresh_started_at", "revision", "updated_at"])
    _checkpoint(job_id)
    return access


def parse_history(payload, *, start, end):
    indicators = payload.get("indicators")
    if type(indicators) is not dict or set(indicators) - set(INDICATORS):
        raise YandexError("malformed_response")
    rows = {}
    for indicator in INDICATORS:
        values = indicators.get(indicator, [])
        if type(values) is not list or len(values) > 35:
            raise YandexError("malformed_response")
        seen = set()
        for item in values:
            if type(item) is not dict or set(item) != {"date", "value"} or type(item["date"]) is not str or len(item["date"]) > 40:
                raise YandexError("malformed_response")
            try:
                stamp = datetime.fromisoformat(item["date"].replace(",", "."))
                if timezone.is_naive(stamp) or stamp.time().replace(tzinfo=None) != datetime.min.time():
                    raise ValueError
                day = stamp.date()
                number = Decimal(str(item["value"]))
                if type(item["value"]) not in {int, float} or not number.is_finite() or not 0 <= number <= 10**12:
                    raise ValueError
                if indicator.startswith("TOTAL_") and number != number.to_integral_value():
                    raise ValueError
            except (ValueError, TypeError, InvalidOperation):
                raise YandexError("malformed_response") from None
            if not start <= day <= end:
                continue
            if day in seen:
                raise YandexError("malformed_response")
            seen.add(day)
            row = rows.setdefault(day, {"date": day.isoformat(), "source_timestamp": item["date"],
                **{name: None for name in INDICATORS}})
            if datetime.fromisoformat(row["source_timestamp"].replace(",", ".")) != stamp:
                raise YandexError("malformed_response")
            row[indicator] = int(number) if indicator.startswith("TOTAL_") else str(number)
    output = [rows[day] for day in sorted(rows)]
    complete = len(output) == (end - start).days + 1 and all(
        row["TOTAL_SHOWS"] is not None and row["TOTAL_CLICKS"] is not None for row in output)
    return output, complete


def _finish(job_id, *, output=None, error="", actual_units=1):
    identity = JobRun.objects.filter(pk=job_id, handler=HANDLER).values_list("organization_id", flat=True).first()
    if identity is None:
        return False
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=identity)
        job = JobRun.objects.select_for_update(no_key=True).select_related("project__organization", "actor").get(pk=job_id)
        if job.status != JobStatus.RUNNING:
            return False
        cursor = SyncCursor.objects.select_for_update().get(connection_id=job.config_snapshot["connection_id"], project=job.project)
        cancelled = JobCancellation.objects.filter(job=job).exists()
        allowed = source_current(job) and not usage_denial(job=job)
        if cancelled or not allowed:
            error, output = "cancelled" if cancelled else "source_revoked", None
        job.output = output or {}
        job.status = JobStatus.CANCELLED if cancelled or not allowed else JobStatus.FAILED if error else (
            JobStatus.SUCCEEDED if output["complete_window"] else JobStatus.PARTIALLY_SUCCEEDED)
        job.error_category = error or ("" if output["complete_window"] else "partial_coverage")
        job.save(update_fields=["status", "output", "error_category", "updated_at"])
        cursor.status = "succeeded" if job.status == JobStatus.SUCCEEDED else "partially_succeeded" if output else "failed"
        cursor.error_category = job.error_category
        cursor.quota_state = "limited" if error == "quota_limited" else "available"
        cursor.retry_after = timezone.now() + timedelta(minutes=15) if error == "quota_limited" else None
        if output:
            cursor.coverage_start, cursor.coverage_end = _day(job.input_snapshot["date_start"]), _day(job.input_snapshot["date_end"])
            cursor.last_success_at = timezone.now()
        next_start = cursor.position.get("next_start")
        anchor = cursor.position.get("anchor_start")
        if output:
            next_day = _day(next_start) if next_start else cursor.coverage_start
            anchor = anchor or cursor.coverage_start.isoformat()
            if output["complete_window"] and cursor.coverage_start <= next_day <= cursor.coverage_end + timedelta(days=1):
                next_day = cursor.coverage_end + timedelta(days=1)
                cursor.fresh_through = cursor.coverage_end
            next_start = next_day.isoformat()
        cursor.position = {"method": METHOD, "job_id": job.pk, "window_complete": bool(output and output["complete_window"]),
            "next_start": next_start, "anchor_start": anchor}
        cursor.revision += 1
        cursor.save()
        JobStep.objects.create(job=job, sequence=1, name="Read bounded Yandex aggregate history", progress_percent=100,
            status=JobStep.Status.SUCCEEDED if output else JobStep.Status.FAILED,
            output={"row_count": len(output["rows"])} if output else {}, error_category=job.error_category)
        if hasattr(job, "usage"):
            settle_usage(job=job, actual_units=actual_units)
        return bool(output)


@sensitive_variables()
def execute_sync(job_id):
    from jobs.crawler import _crawl_execution_lock
    with _crawl_execution_lock(job_id) as acquired:
        if not acquired:
            return False
        identity = JobRun.objects.filter(pk=job_id, handler=HANDLER).values_list("organization_id", flat=True).first()
        if identity is None:
            return False
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=identity)
            job = JobRun.objects.select_for_update(no_key=True).select_related("project__organization", "actor").get(pk=job_id)
            if job.status != JobStatus.QUEUED:
                return False
            job.status = JobStatus.RUNNING
            job.save(update_fields=["status", "updated_at"])
            cursor = SyncCursor.objects.select_for_update().get(connection_id=job.config_snapshot["connection_id"], project=job.project)
            cursor.status, cursor.error_category, cursor.retry_after = "running", "", None
            cursor.last_attempt_at = timezone.now()
            cursor.revision += 1
            cursor.save()
        started = False
        try:
            grant = _checkpoint(job_id)
            started = True
            token = _access_token(job_id)
            checkpoint = lambda: _checkpoint(job_id)
            hosts_path = f"/v4/user/{grant.user_id}/hosts"
            if verified_host(yandex_json(hosts_path, token=token, checkpoint=checkpoint), origin=grant.origin) != grant.host_id:
                raise YandexError("property_unavailable")
            start, end = _day(job.input_snapshot["date_start"]), _day(job.input_snapshot["date_end"])
            params = [("query_indicator", name) for name in INDICATORS] + [("device_type_indicator", "ALL"),
                ("date_from", (start - timedelta(days=1)).isoformat() + "T00:00:00Z"),
                ("date_to", (end + timedelta(days=1)).isoformat() + "T23:59:59Z")]
            path = f"/v4/user/{grant.user_id}/hosts/{quote(grant.host_id, safe='')}/search-queries/all/history?" + urlencode(params)
            rows, complete = parse_history(yandex_json(path, token=token, checkpoint=checkpoint), start=start, end=end)
            if verified_host(yandex_json(hosts_path, token=token, checkpoint=checkpoint), origin=grant.origin) != grant.host_id:
                raise YandexError("property_unavailable")
            output = {"method": METHOD, "provider": "yandex_webmaster", "origin": grant.origin,
                "date_start": start.isoformat(), "date_end": end.isoformat(), "device": "ALL",
                "calendar": "provider_returned_timestamp_offset", "coverage": "provider_reported_not_guaranteed_complete_or_final",
                "complete_window": complete, "rows": rows}
            if len(json.dumps(output).encode()) > 24576:
                raise YandexError("malformed_response")
            return _finish(job_id, output=output)
        except (PermissionDenied, ObjectDoesNotExist):
            return _finish(job_id, error="source_revoked", actual_units=int(started))
        except ValidationError:
            return _finish(job_id, error="reauthorization_required", actual_units=int(started))
        except YandexError as error:
            return _finish(job_id, error=error.category, actual_units=int(started))


def reconcile_stuck_syncs(*, limit=20):
    from jobs.crawler import _crawl_execution_lock
    ids = list(JobRun.objects.filter(handler=HANDLER, status=JobStatus.RUNNING,
        updated_at__lt=timezone.now() - timedelta(minutes=3)).order_by("pk").values_list("pk", flat=True)[:limit])
    recovered = 0
    for job_id in ids:
        with _crawl_execution_lock(job_id) as acquired:
            if acquired and JobRun.objects.filter(pk=job_id, status=JobStatus.RUNNING).exists():
                _finish(job_id, error="request_outcome_unknown")
                recovered += 1
    return recovered
