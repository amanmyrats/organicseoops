from datetime import date, timedelta
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from jobs.crawler import _crawl_execution_lock
from jobs.models import JobCancellation, JobRun, JobStatus, JobStep, UsageReservation
from jobs.services import queue_job
from jobs.usage import settle_usage, usage_denial
from tenancy.models import Organization, Project
from tenancy.services import Action, require_project_action

from providers.google_app import google_oauth_client

from .google_tokens import GoogleTokenError, GoogleTokens, refresh_google_tokens
from .google_oauth import require_google_reconnect
from .models import GoogleOAuthGrant, IntegrationConnection, SearchAnalyticsPageSnapshot, SearchAnalyticsQueryPageSnapshot, SyncCursor, normalize_external_property, verified_domain_origins
from .search_console_analytics import record_search_analytics_page, record_search_analytics_query_page
from .search_console_api import exact_scope_search_console_sites
from .search_console_transport import SearchConsoleTransportError, google_search_analytics_query, google_search_analytics_query_page, google_site_get
from .services import require_connection_capability


METHOD = "search-console-api-v1"


def validate_sync_input(data):
    if (type(data) is not dict or set(data) not in ({"connection_id", "grant_id", "day", "dimensions"},
                                                  {"connection_id", "grant_id", "day", "dimensions", "report"})
        or "report" in data and (data["report"] != "query_page" or data["dimensions"] != ["query", "page"])
        or any(type(data[key]) is not int or data[key] < 1 for key in ("connection_id", "grant_id"))
        or type(data["dimensions"]) is not list or not 1 <= len(data["dimensions"]) <= 3
        or any(type(value) is not str for value in data["dimensions"])
        or len(data["dimensions"]) != len(set(data["dimensions"]))
        or not set(data["dimensions"]) <= {"date", "query", "page"}
        or type(data["day"]) is not str):
        raise ValidationError("Choose one bounded Search Console report day and dimensions.")
    try:
        day = date.fromisoformat(data["day"])
    except ValueError:
        raise ValidationError("Choose a valid Search Console report day.") from None
    today = timezone.now().astimezone(ZoneInfo("America/Los_Angeles")).date()
    if day.isoformat() != data["day"] or not today - timedelta(days=90) <= day <= today - timedelta(days=3):
        raise ValidationError("Choose a finalized Search Console day within 90 days.")
    return data


def _source(*, project, organization, data, config):
    validate_sync_input(data)
    connection = IntegrationConnection.objects.filter(pk=data["connection_id"], project=project).first()
    grant = GoogleOAuthGrant.objects.filter(pk=data["grant_id"], organization=organization, project=project).first()
    if connection is None or grant is None:
        raise PermissionDenied
    require_connection_capability(connection, "api_sync", dimensions=data["dimensions"])
    domain = connection.external_property_id.startswith("sc-domain:")
    approved = sorted(set(grant.selected_origins) & set(verified_domain_origins(
        project, connection.external_property_id))) if domain else None
    expected_config = {"grant_revision": grant.revision, "property_id": connection.external_property_id}
    if data.get("report") == "query_page":
        try:
            google_oauth_client(require_redirect=False)
        except (GoogleTokenError, ValidationError):
            raise PermissionDenied from None
        if (domain or connection.provider != "google_search_console"
            or not {"query_metrics", "page_metrics"} <= set(connection.capabilities)
            or connection.timezone != "America/Los_Angeles"):
            raise ValidationError("Paired reports require an actual URL-prefix query and page source.")
        expected_config["report_method"] = "gsc-query-page-parse-v1"
        require_project_action(project=project, user=grant.actor, action=Action.MANAGE_PROJECT)
    if domain:
        expected_config.update({"approved_origins": approved, "scope_strategy": "domain-page-v1"})
    if (grant.state != GoogleOAuthGrant.State.ACTIVE or not grant.encrypted_refresh_token
        or connection.credential_reference != grant.credential_reference
        or connection.external_property_id != grant.selected_property_id
        or normalize_external_property("google_search_console", grant.selected_site_url) != connection.external_property_id
        or config != expected_config or domain and (data["dimensions"] != ["page"] or not approved)):
        raise PermissionDenied
    return connection, grant


def queue_search_console_sync(*, project, actor, connection, grant, day, dimensions, idempotency_key,
                              schedule=None, scheduled_for=None, report=None, expected_grant_revision=None):
    data = {"connection_id": connection.pk, "grant_id": grant.pk,
            "day": day.isoformat() if type(day) is date else day, "dimensions": dimensions}
    if report is not None:
        data["report"] = report
    validate_sync_input(data)
    google_oauth_client(require_redirect=False)
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        connection = IntegrationConnection.objects.select_for_update().get(pk=data["connection_id"], project=project)
        grant = GoogleOAuthGrant.objects.select_for_update().get(pk=data["grant_id"], project=project,
                                                                  organization=organization)
        if expected_grant_revision is not None and (type(expected_grant_revision) is not int
                or expected_grant_revision < 0 or expected_grant_revision != grant.revision):
            raise ValidationError("The selected source grant revision changed before queueing.")
        config = {"grant_revision": grant.revision, "property_id": connection.external_property_id}
        if data.get("report") == "query_page":
            if schedule is not None or scheduled_for is not None:
                raise ValidationError("Paired reports require deliberate manual selection.")
            config["report_method"] = "gsc-query-page-parse-v1"
        if connection.external_property_id.startswith("sc-domain:"):
            config.update({"approved_origins": sorted(set(grant.selected_origins) & set(verified_domain_origins(
                project, connection.external_property_id))), "scope_strategy": "domain-page-v1"})
        _source(project=project, organization=organization, data=data, config=config)
        cursor = SyncCursor.objects.select_for_update().filter(connection=connection, project=project).first()
        if cursor and cursor.retry_after and cursor.retry_after > timezone.now():
            raise ValidationError("This Search Console source is temporarily rate limited.")
        return queue_job(project=project, actor=actor, handler="sync_search_console", input_snapshot=data,
                          config_snapshot=config, idempotency_key=idempotency_key,
                          schedule=schedule, scheduled_for=scheduled_for)


def _denial(job):
    if job.input_snapshot.get("report") == "query_page" and (
            job.schedule_id is not None or job.retry_of_id is not None or job.method_version != METHOD):
        return "source_revoked"
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
        _source(project=job.project, organization=job.organization, data=job.input_snapshot,
                config=job.config_snapshot)
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
        if job.handler != "sync_search_console" or job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            return False
        denied = _denial(job)
        paired = job.input_snapshot.get("report") == "query_page"
        snapshots = (SearchAnalyticsQueryPageSnapshot if paired else SearchAnalyticsPageSnapshot).objects.filter(job=job)
        pages = snapshots.count()
        attempted = JobStep.objects.filter(job=job, name__in=["Verify selected property", "Search Analytics page"]).count()
        failed = JobStep.objects.filter(job=job, name="Search Analytics page", status=JobStep.Status.FAILED).exists()
        # Preserve a definitive provider denial even though disconnecting its grant now revokes local scope.
        category = (error if denied == "source_revoked" and error in {
            "authorization_unavailable", "property_unavailable", "authorization_rejected", "reauthorization_required"
        } else denied or error or ("partial_coverage" if failed else ""))
        if job.status == JobStatus.QUEUED and not denied:
            job.status = JobStatus.RUNNING
            job.save(update_fields=["status", "updated_at"])
        job.status = (JobStatus.CANCELLED if denied else JobStatus.PARTIALLY_SUCCEEDED if pages and category
                      else JobStatus.FAILED if category else JobStatus.SUCCEEDED)
        job.error_category = category
        job.output = {"pages_recorded": pages, "requests_attempted": attempted,
                      "source_coverage": ("bounded_query_page_top_rows_only" if paired else "top_rows_only_domain_page_filtered" if job.config_snapshot.get("scope_strategy") == "domain-page-v1"
                                          else "top_rows_only") if pages else "unavailable",
                      "truncated": (None if job.config_snapshot.get("scope_strategy") == "domain-page-v1" else
                                    snapshots.filter(result__truncated=True).exists())}
        if paired:
            job.output.update({"report": "query_page", "provider_completeness": "not_established", "hidden_queries": "unknown"})
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
            # Local backoff, not a claimed provider Retry-After value.
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


def execute_search_console_sync(job_id, *, refresh=refresh_google_tokens, verify_site=google_site_get,
                                query=google_search_analytics_query, paired_query=google_search_analytics_query_page):
    with _crawl_execution_lock(job_id) as acquired:
        if not acquired:
            return False
        try:
            return _execute(job_id, refresh=refresh, verify_site=verify_site, query=query, paired_query=paired_query)
        except Exception:
            return _finish(job_id, error="handler_failed")


def _complete_verification(job_id, org_id, category=""):
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=org_id)
        current = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id)
        denied = _denial(current)
        step = JobStep.objects.select_for_update().get(job=current, sequence=1, name="Verify selected property")
        step.status = JobStep.Status.FAILED if denied or category else JobStep.Status.SUCCEEDED
        step.error_category = (category if denied == "source_revoked" and category in {
            "authorization_unavailable", "property_unavailable"
        } else denied or category)
        step.output = {"state": "unavailable" if step.error_category else "verified"}
        step.save(update_fields=["status", "error_category", "output"])
        current.save(update_fields=["updated_at"])
    return step.error_category


def _execute(job_id, *, refresh, verify_site, query, paired_query):
    org_id = JobRun.objects.filter(pk=job_id).values_list("organization_id", flat=True).first()
    if org_id is None:
        return False
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=org_id)
        job = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id)
        if job.handler != "sync_search_console" or job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            return False
        denied = _denial(job)
        if not denied:
            connection, grant = _source(project=job.project, organization=job.organization,
                                        data=job.input_snapshot, config=job.config_snapshot)
            cursor, _ = SyncCursor.objects.select_for_update().get_or_create(
                connection=connection, defaults={"project": job.project})
            if cursor.status == SyncCursor.Status.RUNNING and cursor.position.get("job_id") != job.pk:
                prior = JobRun.objects.filter(pk=cursor.position.get("job_id")).first()
                if prior is not None and prior.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
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
            verification = JobStep.objects.filter(job=job, sequence=1).first()
            if verification is not None and verification.status == JobStep.Status.RUNNING:
                verification.status = JobStep.Status.FAILED
                verification.error_category = "request_outcome_unknown"
                verification.output = {"state": "unknown"}
                verification.save(update_fields=["status", "error_category", "output"])
            if verification is not None and verification.status == JobStep.Status.FAILED:
                return _finish(job_id, error=verification.error_category)
    if denied:
        return _finish(job_id)
    try:
        client = google_oauth_client(require_redirect=False)
        tokens = refresh(encrypted_refresh=grant.encrypted_refresh_token,
                         client_id=client.client_id, client_secret=client.client_secret)
        if not isinstance(tokens, GoogleTokens):
            raise GoogleTokenError("malformed_response")
    except GoogleTokenError as exc:
        if exc.category in {"authorization_rejected", "reauthorization_required"}:
            require_google_reconnect(grant=grant)
        return _finish(job_id, error=exc.category)

    if verification is None:
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=org_id)
            current = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id)
            if _denial(current):
                return _finish(job_id)
            JobStep.objects.create(job=current, sequence=1, name="Verify selected property",
                                   status=JobStep.Status.RUNNING, output={"state": "attempted"})
            current.save(update_fields=["updated_at"])
        try:
            site = verify_site(site_url=grant.selected_site_url, access_token=tokens.access_token)
            available = exact_scope_search_console_sites(project=job.project, user=job.actor, response={"siteEntry": [site]})
            if not any(item["external_property_id"] == connection.external_property_id
                       and (not connection.external_property_id.startswith("sc-domain:")
                            or set(job.config_snapshot["approved_origins"]) <= set(item["approved_origins"]))
                       for item in available["sites"]):
                require_google_reconnect(grant=grant, reason="property_unavailable")
                raise PermissionDenied
        except SearchConsoleTransportError as exc:
            if exc.category in {"authorization_unavailable", "property_unavailable"}:
                require_google_reconnect(grant=grant, reason=exc.category)
            return _finish(job_id, error=_complete_verification(job_id, org_id, category=exc.category))
        except (PermissionDenied, ValidationError, TypeError):
            return _finish(job_id, error=_complete_verification(job_id, org_id, category="property_unavailable"))
        failure = _complete_verification(job_id, org_id)
        if failure:
            return _finish(job_id, error=failure)

    day = date.fromisoformat(job.input_snapshot["day"])
    paired = job.input_snapshot.get("report") == "query_page"
    for index, dimension in enumerate(["query_page"] if paired else job.input_snapshot["dimensions"]):
        for page_index, offset in enumerate((0,) if job.config_snapshot.get("scope_strategy") == "domain-page-v1" else (0, 100)):
            sequence = index * 2 + page_index + 2
            with transaction.atomic():
                Organization.objects.select_for_update().get(pk=org_id)
                current = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id)
                denied = _denial(current)
                if denied:
                    break
                saved = JobStep.objects.filter(job=current, sequence=sequence).first()
                if saved is not None:
                    if saved.status == JobStep.Status.RUNNING:
                        saved.status = JobStep.Status.FAILED
                        saved.error_category = "request_outcome_unknown"
                        saved.output = {"state": "unknown"}
                        saved.save(update_fields=["status", "error_category", "output"])
                    if saved.status == JobStep.Status.FAILED:
                        return _finish(job_id, error=saved.error_category)
                    if saved.output.get("next_start_row") is None:
                        break
                    continue
                JobStep.objects.create(job=current, sequence=sequence, name="Search Analytics page",
                                       status=JobStep.Status.RUNNING, output={"state": "attempted"})
                current.save(update_fields=["updated_at"])
            if denied:
                return _finish(job_id)
            try:
                if paired:
                    response = paired_query(connection=connection, access_token=tokens.access_token, day=day, start_row=offset)
                    snapshot = record_search_analytics_query_page(job=job, connection=connection, grant=grant,
                        day=day, start_row=offset, response=response)
                else:
                    response = query(connection=connection, access_token=tokens.access_token, day=day,
                                     dimension=dimension, start_row=offset)
                    snapshot = record_search_analytics_page(job=job, connection=connection, grant=grant,
                        day=day, dimension=dimension, start_row=offset, response=response)
            except (SearchConsoleTransportError, GoogleTokenError) as exc:
                failure = exc.category
                if isinstance(exc, SearchConsoleTransportError) and failure in {"authorization_unavailable", "property_unavailable"}:
                    require_google_reconnect(grant=grant, reason=failure)
            except (PermissionDenied, ValidationError):
                failure = "source_revoked"
            else:
                failure = ""
            with transaction.atomic():
                Organization.objects.select_for_update().get(pk=org_id)
                current = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id)
                denied = _denial(current)
                step = JobStep.objects.select_for_update().get(job=current, sequence=sequence)
                step.status = JobStep.Status.FAILED if denied or failure else JobStep.Status.SUCCEEDED
                step.error_category = (failure if denied == "source_revoked" and failure in {
                    "authorization_unavailable", "property_unavailable"
                } else denied or failure)
                step.output = {"state": "unavailable"} if step.error_category else {
                    "state": "recorded", "snapshot_id": snapshot.pk, "next_start_row": snapshot.result["next_start_row"]}
                if paired and not step.error_category:
                    step.output["result_sha256"] = snapshot.result_sha256
                step.save(update_fields=["status", "error_category", "output"])
                current.save(update_fields=["updated_at"])
            if denied or failure:
                return _finish(job_id, error=step.error_category)
            if snapshot.result["next_start_row"] is None:
                break
    return _finish(job_id)
