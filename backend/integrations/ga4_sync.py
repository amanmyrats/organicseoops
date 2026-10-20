"""Scoped GA4 job input and immutable page evidence; queue execution attaches after schema checks."""

from datetime import date, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from jobs.crawler import _crawl_execution_lock
from jobs.models import JobCancellation, JobRun, JobStatus, JobStep, UsageReservation
from jobs.services import queue_job
from jobs.usage import settle_usage, usage_denial
from tenancy.models import AuditEvent, AuditEventType, Organization, Project
from tenancy.services import Action, require_project_action

from .ga4_reports import REPORT_KINDS, parse_ga4_landing_report
from .ga4_oauth import refresh_ga4_tokens
from .ga4_properties import eligible_ga4_property
from .ga4_transport import (ga4_admin_property_get, ga4_admin_streams_list,
                            ga4_check_landing_compatibility, ga4_landing_report)
from .google_tokens import GoogleTokenError, GoogleTokens
from .models import GA4LandingPageSnapshot, GA4OAuthGrant, IntegrationConnection, SyncCursor
from .search_console_transport import SearchConsoleTransportError
from .services import require_connection_capability
from providers.google_app import google_analytics_oauth_client


METHOD = "ga4-landing-api-v2"


class GA4OriginAttributionUnavailable(ValidationError):
    pass


def _require_exact_origin_reporting(_origin):
    # ponytail: GA4 hostname + landing path cannot prove scheme/port; enable only with a verified exact-origin report grain.
    raise GA4OriginAttributionUnavailable("GA4 exact-origin landing attribution is unavailable.")


def validate_ga4_sync_input(data):
    if (type(data) is not dict or set(data) != {"connection_id", "grant_id", "day", "hostname", "report_kind"}
        or any(type(data[key]) is not int or data[key] < 1 for key in ("connection_id", "grant_id"))
        or type(data["day"]) is not str or type(data["hostname"]) is not str
        or type(data["report_kind"]) is not str or data["report_kind"] not in REPORT_KINDS
        or not 1 <= len(data["hostname"]) <= 253):
        raise ValidationError("Choose one bounded GA4 property/hostname/day.")
    try:
        day = date.fromisoformat(data["day"])
    except ValueError:
        raise ValidationError("Choose a GA4 reporting day.") from None
    if day.isoformat() != data["day"] or not data["hostname"].isascii() or data["hostname"].lower() != data["hostname"]:
        raise ValidationError("Choose one exact GA4 reporting day and hostname.")
    return data


def _source(*, project, organization, data, config):
    validate_ga4_sync_input(data)
    connection = IntegrationConnection.objects.filter(pk=data["connection_id"], project=project,
                                                      provider="google_analytics_4").first()
    grant = GA4OAuthGrant.objects.filter(pk=data["grant_id"], project=project, organization=organization).first()
    if connection is None or grant is None:
        raise PermissionDenied
    require_connection_capability(connection, "landing_metrics", dimensions=["hostname", "landing_page"])
    if (grant.state != GA4OAuthGrant.State.ACTIVE or grant.selected_origins != [config.get("origin")]
        or connection.credential_reference != grant.credential_reference
        or connection.external_property_id != grant.property_id
        or config != {"grant_revision": grant.revision, "property_id": grant.property_id,
                      "origin": grant.selected_origins[0], "currency": connection.currency,
                      "timezone": connection.timezone}
        or urlsplit(grant.selected_origins[0]).hostname != data["hostname"]):
        raise PermissionDenied
    _require_exact_origin_reporting(grant.selected_origins[0])
    return connection, grant


def queue_ga4_landing_sync(*, project, actor, connection, grant, day, idempotency_key,
                          report_kind="all_channels"):
    if type(day) is not date:
        raise ValidationError("Choose one GA4 property reporting day.")
    google_analytics_oauth_client()
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        connection = IntegrationConnection.objects.select_for_update().get(pk=connection.pk, project=project)
        grant = GA4OAuthGrant.objects.select_for_update().get(pk=grant.pk, project=project, organization=organization)
        if len(grant.selected_origins) != 1:
            raise PermissionDenied
        origin = grant.selected_origins[0]
        data = validate_ga4_sync_input({"connection_id": connection.pk, "grant_id": grant.pk,
                                        "hostname": urlsplit(origin).hostname, "day": day.isoformat(),
                                        "report_kind": report_kind})
        today = timezone.now().astimezone(ZoneInfo(connection.timezone)).date()
        if not today - timedelta(days=90) <= day <= today - timedelta(days=3):
            raise ValidationError("Choose one aged GA4 reporting day within 90 days.")
        config = {"grant_revision": grant.revision, "property_id": connection.external_property_id,
                  "origin": origin, "currency": connection.currency, "timezone": connection.timezone}
        _source(project=project, organization=organization, data=data, config=config)
        cursor = SyncCursor.objects.select_for_update().filter(connection=connection, project=project).first()
        if cursor and cursor.retry_after and cursor.retry_after > timezone.now():
            raise ValidationError("This GA4 source is temporarily rate limited.")
        return queue_job(project=project, actor=actor, handler="sync_ga4_landing", input_snapshot=data,
                         config_snapshot=config, idempotency_key=idempotency_key)


def _denial(job):
    if JobCancellation.objects.filter(job=job).exists():
        return "cancelled"
    try:
        require_project_action(project=job.project, user=job.actor, action=Action.MANAGE_PROJECT)
    except PermissionDenied:
        return "source_revoked"
    denied = usage_denial(job=job)
    if denied:
        return denied
    try:
        _source(project=job.project, organization=job.organization,
                data=job.input_snapshot, config=job.config_snapshot)
    except GA4OriginAttributionUnavailable:
        return "origin_attribution_unavailable"
    except (PermissionDenied, ValidationError):
        return "source_revoked"
    return ""


def _finish(job_id, error=""):
    with transaction.atomic():
        org_id = JobRun.objects.filter(pk=job_id).values_list("organization_id", flat=True).first()
        if org_id is None:
            return False
        Organization.objects.select_for_update().get(pk=org_id)
        job = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id)
        if job.handler != "sync_ga4_landing" or job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            return False
        denied = _denial(job)
        pages = list(GA4LandingPageSnapshot.objects.filter(job=job).order_by("offset")[:2])
        attempted = JobStep.objects.filter(job=job, name__in=[
            "GA4 property check", "GA4 web streams", "GA4 compatibility", "GA4 report page"]).count()
        incomplete = bool(pages and (not pages[-1].result["coverage"]["returned_rows_exhausted_without_reported_gaps"]
            or any(page.result["coverage"]["omitted_foreign_or_parameterized_rows"]
                or page.result["coverage"]["sampled"] or page.result["coverage"]["thresholded"]
                or page.result["coverage"]["other_row_loss"] for page in pages)))
        category = error if denied == "source_revoked" and error in {
            "authorization_unavailable", "authorization_rejected", "property_unavailable", "reauthorization_required"
        } else denied or error or ("report_coverage_limited" if incomplete else "")
        if job.status == JobStatus.QUEUED and not denied:
            job.status = JobStatus.RUNNING
            job.save(update_fields=["status", "updated_at"])
        job.status = (JobStatus.CANCELLED if denied else JobStatus.PARTIALLY_SUCCEEDED if pages and category
                      else JobStatus.FAILED if category else JobStatus.SUCCEEDED)
        job.error_category = category
        job.output = {"pages_recorded": len(pages), "requests_attempted": attempted,
                      "source_coverage": ("ga4_organic_session_channel_hostname_filtered"
                          if job.input_snapshot["report_kind"] == "organic_search" else
                          "hostname_filtered_reporting_gaps_unknown") if pages else "unavailable",
                      "sampling_or_threshold_gaps": any(
                          page.result["coverage"][key] for page in pages
                          for key in ("sampled", "thresholded", "other_row_loss")) if pages else None}
        job.save(update_fields=["status", "error_category", "output", "updated_at"])
        cursor = SyncCursor.objects.select_for_update().filter(project=job.project,
            connection_id=job.input_snapshot["connection_id"], status=SyncCursor.Status.RUNNING).first()
        if cursor and cursor.position.get("job_id") == job.pk:
            cursor.status = (SyncCursor.Status.UNAVAILABLE if denied else SyncCursor.Status.WAITING_PROVIDER
                             if category == "quota_limited" else SyncCursor.Status.PARTIALLY_SUCCEEDED
                             if job.status == JobStatus.PARTIALLY_SUCCEEDED else SyncCursor.Status.FAILED
                             if category else SyncCursor.Status.SUCCEEDED)
            cursor.error_category = category
            cursor.quota_state = SyncCursor.QuotaState.LIMITED if category == "quota_limited" else SyncCursor.QuotaState.AVAILABLE
            cursor.retry_after = timezone.now() + timedelta(hours=1) if category == "quota_limited" else None
            cursor.coverage_start = cursor.coverage_end = date.fromisoformat(job.input_snapshot["day"]) if pages else None
            if pages and job.status == JobStatus.SUCCEEDED:
                cursor.fresh_through = max(cursor.fresh_through or cursor.coverage_end, cursor.coverage_end)
            cursor.last_success_at = timezone.now() if job.status == JobStatus.SUCCEEDED else cursor.last_success_at
            cursor.revision += 1
            cursor.save()
        if UsageReservation.objects.filter(job=job, state=UsageReservation.State.RESERVED).exists():
            settle_usage(job=job, actual_units=attempted)
    return True


def _reconnect(grant):
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=grant.organization_id)
        project = Project.objects.select_for_update().get(pk=grant.project_id, organization=organization)
        current = GA4OAuthGrant.objects.select_for_update().get(pk=grant.pk, project=project, organization=organization)
        if current.state == GA4OAuthGrant.State.ACTIVE:
            IntegrationConnection.objects.filter(project=project, provider="google_analytics_4",
                credential_reference=current.credential_reference).update(
                state=IntegrationConnection.State.DISCONNECTED, updated_at=timezone.now())
            current.state = GA4OAuthGrant.State.RECONNECT_REQUIRED
            current.revision += 1
            current.save(update_fields=["state", "revision", "updated_at"])
            AuditEvent.objects.create(organization=organization, project=project, actor=current.actor,
                event_type=AuditEventType.GA4_RECONNECT_REQUIRED,
                details={"grant_id": current.pk, "property_id": current.property_id})


def execute_ga4_landing_sync(job_id, *, refresh=refresh_ga4_tokens, get_property=ga4_admin_property_get,
                             list_streams=ga4_admin_streams_list, check_compatibility=ga4_check_landing_compatibility,
                             report=ga4_landing_report):
    with _crawl_execution_lock(job_id) as acquired:
        if not acquired:
            return False
        try:
            return _execute(job_id, refresh, get_property, list_streams, check_compatibility, report)
        except Exception:
            return _finish(job_id, error="handler_failed")


def _execute(job_id, refresh, get_property, list_streams, check_compatibility, report):
    org_id = JobRun.objects.filter(pk=job_id).values_list("organization_id", flat=True).first()
    if org_id is None:
        return False
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=org_id)
        job = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id)
        if job.handler != "sync_ga4_landing" or job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            return False
        denied = _denial(job)
        if not denied:
            connection, grant = _source(project=job.project, organization=job.organization,
                                        data=job.input_snapshot, config=job.config_snapshot)
            cursor, _ = SyncCursor.objects.select_for_update().get_or_create(
                connection=connection, defaults={"project": job.project})
            if cursor.status == SyncCursor.Status.RUNNING and cursor.position.get("job_id") != job.pk:
                prior = JobRun.objects.filter(pk=cursor.position.get("job_id")).first()
                if prior and prior.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                    return _finish(job_id, error="source_busy")
            if cursor.retry_after and cursor.retry_after > timezone.now():
                return _finish(job_id, error="quota_limited")
            cursor.status = SyncCursor.Status.RUNNING
            cursor.position = {"job_id": job.pk, "day": job.input_snapshot["day"]}
            cursor.last_attempt_at = timezone.now()
            cursor.retry_after = None
            cursor.error_category = ""
            cursor.revision += 1
            cursor.save()
            if job.status == JobStatus.QUEUED:
                job.status = JobStatus.RUNNING
                job.save(update_fields=["status", "updated_at"])
            if JobStep.objects.filter(job=job).exists():
                # A worker lost between request and commit may already have consumed provider quota.
                JobStep.objects.filter(job=job, status=JobStep.Status.RUNNING).update(
                    status=JobStep.Status.FAILED, error_category="request_outcome_unknown",
                    output={"state": "unknown"})
                return _finish(job_id, error="request_outcome_unknown")
    if denied:
        return _finish(job_id)
    try:
        client = google_analytics_oauth_client()
        tokens = refresh(encrypted_refresh=grant.encrypted_refresh_token,
                         client_id=client.client_id, client_secret=client.client_secret)
        if not isinstance(tokens, GoogleTokens):
            raise GoogleTokenError("malformed_response")
    except GoogleTokenError as exc:
        if exc.category in {"authorization_rejected", "reauthorization_required"}:
            _reconnect(grant)
        return _finish(job_id, error=exc.category)
    origin = job.config_snapshot["origin"]
    property_id = connection.external_property_id
    day = date.fromisoformat(job.input_snapshot["day"])
    report_kind = job.input_snapshot["report_kind"]
    steps = ((1, "GA4 property check", lambda: get_property(property_id=property_id,
                access_token=tokens.access_token)),
             (2, "GA4 web streams", lambda: list_streams(property_id=property_id,
                access_token=tokens.access_token)),
             (3, "GA4 compatibility", lambda: check_compatibility(property_id=property_id,
                approved_origin=origin, report_kind=report_kind, access_token=tokens.access_token)),
             (4, "GA4 report page", lambda: report(property_id=property_id, approved_origin=origin,
                day=day, offset=0, report_kind=report_kind, property_timezone=connection.timezone,
                access_token=tokens.access_token)),
             (5, "GA4 report page", lambda: report(property_id=property_id, approved_origin=origin,
                day=day, offset=100, report_kind=report_kind, property_timezone=connection.timezone,
                access_token=tokens.access_token)))
    property_response = streams_response = None
    for sequence, name, request in steps:
        if sequence == 5 and GA4LandingPageSnapshot.objects.filter(job_id=job_id, offset=0,
            result__row_count__lte=100).exists():
            break
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=org_id)
            current = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id)
            if _denial(current):
                return _finish(job_id)
            JobStep.objects.create(job=current, sequence=sequence, name=name, status=JobStep.Status.RUNNING,
                                   output={"state": "attempted"})
            current.save(update_fields=["updated_at"])
        try:
            payload = request()
            if sequence == 1:
                property_response = payload
            elif sequence == 2:
                streams_response = payload
                candidate = eligible_ga4_property(project=current.project, user=current.actor,
                    property_id=property_id, property_response=property_response, streams_response=streams_response)
                if (origin not in candidate["matched_origins"] or candidate["currency"] != connection.currency
                    or candidate["timezone"] != connection.timezone):
                    raise ValidationError("GA4 property origin or metric context changed.")
            elif sequence == 3 and payload is not True:
                raise ValidationError("GA4 report columns are unavailable.")
            elif sequence in {4, 5}:
                snapshot = record_ga4_landing_page(job=current, connection=connection, grant=grant,
                    day=day, origin=origin, offset=0 if sequence == 4 else 100, response=payload)
        except (GoogleTokenError, SearchConsoleTransportError) as exc:
            failure = exc.category
            if failure in {"authorization_unavailable", "property_unavailable"}:
                _reconnect(grant)
        except (PermissionDenied, ValidationError, TypeError):
            failure = "source_revoked" if _denial(current) else "report_unavailable"
        else:
            failure = ""
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=org_id)
            current = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id)
            revoked = _denial(current)
            step = JobStep.objects.select_for_update().get(job=current, sequence=sequence)
            step.status = JobStep.Status.FAILED if revoked or failure else JobStep.Status.SUCCEEDED
            step.error_category = (failure if revoked == "source_revoked" and failure in {
                "authorization_unavailable", "property_unavailable"} else revoked or failure)
            step.output = {"state": "unavailable"} if step.error_category else {
                "state": "recorded", **({"snapshot_id": snapshot.pk} if sequence in {4, 5} else {})}
            step.save(update_fields=["status", "error_category", "output"])
            current.save(update_fields=["updated_at"])
        if revoked or failure:
            return _finish(job_id, error=step.error_category)
    return _finish(job_id)


def record_ga4_landing_page(*, job, connection, grant, day, origin, offset, response):
    if type(day) is not date or type(offset) is not int or offset not in {0, 100}:
        raise ValidationError("Choose a bounded GA4 job page.")
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=job.organization_id)
        project = Project.objects.select_for_update().get(pk=job.project_id, organization=organization)
        job = JobRun.objects.select_for_update(no_key=True).select_related("actor").get(pk=job.pk, project=project)
        connection = IntegrationConnection.objects.select_for_update().get(pk=connection.pk, project=project)
        grant = GA4OAuthGrant.objects.select_for_update().get(pk=grant.pk, project=project, organization=organization)
        if (job.handler != "sync_ga4_landing" or job.method_version != METHOD
            or job.input_snapshot != {"connection_id": connection.pk, "grant_id": grant.pk,
                                      "day": day.isoformat(), "hostname": urlsplit(origin).hostname,
                                      "report_kind": job.input_snapshot.get("report_kind")}
            or job.input_snapshot["report_kind"] not in REPORT_KINDS):
            raise ValidationError("GA4 job identity changed.")
        _source(project=project, organization=organization, data=job.input_snapshot, config=job.config_snapshot)
        if grant.selected_origins != [origin]:
            raise PermissionDenied
        result = parse_ga4_landing_report(response=response, property_id=connection.external_property_id,
            day=day, approved_origins=[origin], offset=offset,
            report_kind=job.input_snapshot["report_kind"])
        if result["currency"] != connection.currency or result["timezone"] != connection.timezone:
            raise ValidationError("GA4 metric currency or timezone changed.")
        existing = GA4LandingPageSnapshot.objects.filter(job=job, offset=offset).first()
        if existing is not None:
            if (existing.project_id == project.pk and existing.connection_id == connection.pk
                and existing.grant_id == grant.pk and existing.result == result):
                return existing
            raise ValidationError("GA4 page has conflicting immutable evidence.")
        if job.status != JobStatus.RUNNING or JobCancellation.objects.filter(job=job).exists():
            raise PermissionDenied
        require_project_action(project=project, user=job.actor, action=Action.MANAGE_PROJECT)
        if usage_denial(job=job):
            raise PermissionDenied
        return GA4LandingPageSnapshot.objects.create(project=project, connection=connection, grant=grant,
            job=job, property_id=connection.external_property_id, hostname=job.input_snapshot["hostname"],
            day=day, offset=offset, report_kind=job.input_snapshot["report_kind"], result=result)
