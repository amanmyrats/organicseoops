from urllib.parse import urlsplit

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from jobs.crawler import _crawl_execution_lock
from jobs.models import JobCancellation, JobRun, JobStatus, JobStep, UsageReservation
from jobs.services import queue_job
from jobs.usage import settle_usage, usage_denial
from tenancy.models import Organization, Project
from tenancy.services import Action, require_project_action

from providers.google_app import google_oauth_client

from .google_oauth import require_google_reconnect
from .google_tokens import GoogleTokenError, GoogleTokens, refresh_google_tokens
from .models import (GoogleOAuthGrant, IntegrationConnection, SearchConsoleCoverageObservation,
                     normalize_external_property, verified_domain_origins)
from .search_console import _RowError, _normalize_property_page
from .search_console_api import exact_scope_search_console_sites
from .search_console_coverage import record_coverage_observation
from .search_console_transport import (SearchConsoleTransportError, google_site_get, google_sitemaps_list,
                                       google_url_inspection)
from .services import require_connection_capability


METHOD = "search-console-coverage-v1"


def validate_coverage_input(data):
    if (type(data) is not dict or set(data) != {"connection_id", "grant_id", "inspection_url"}
        or any(type(data[key]) is not int or data[key] < 1 for key in ("connection_id", "grant_id"))
        or type(data["inspection_url"]) is not str or not 1 <= len(data["inspection_url"]) <= 2048):
        raise ValidationError("Choose one bounded Search Console page and source.")
    try:
        parsed = urlsplit(data["inspection_url"])
    except ValueError:
        raise ValidationError("Choose a valid exact project URL.") from None
    if parsed.query or parsed.fragment:
        raise ValidationError("Inspection URLs cannot contain query or fragment secrets.")
    return data


def _source(*, project, organization, data, config):
    validate_coverage_input(data)
    connection = IntegrationConnection.objects.filter(pk=data["connection_id"], project=project).first()
    grant = GoogleOAuthGrant.objects.filter(pk=data["grant_id"], project=project,
                                             organization=organization).first()
    if connection is None or grant is None:
        raise PermissionDenied
    for capability in ("api_sync", "indexing_status", "sitemaps"):
        require_connection_capability(connection, capability)
    if connection.external_property_id.startswith("sc-domain:"):
        origins = sorted(set(grant.selected_origins) & set(verified_domain_origins(
            project, connection.external_property_id)))
    else:
        origins = [connection.external_property_id]
    expected_config = {"grant_revision": grant.revision, "property_id": connection.external_property_id,
                       "approved_origins": origins}
    if (not origins or grant.state != GoogleOAuthGrant.State.ACTIVE or not grant.encrypted_refresh_token
        or connection.credential_reference != grant.credential_reference
        or grant.selected_property_id != connection.external_property_id
        or normalize_external_property("google_search_console", grant.selected_site_url) != connection.external_property_id
        or config != expected_config):
        raise PermissionDenied
    for origin in origins:
        try:
            if _normalize_property_page(data["inspection_url"], origin) == data["inspection_url"]:
                return connection, grant, origins
        except (_RowError, ValueError):
            continue
    raise ValidationError("URL Inspection is unavailable outside this project scope.")


def queue_search_console_coverage(*, project, actor, connection, grant, inspection_url, idempotency_key):
    data = validate_coverage_input({"connection_id": connection.pk, "grant_id": grant.pk,
                                    "inspection_url": inspection_url})
    google_oauth_client(require_redirect=False)
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        connection = IntegrationConnection.objects.select_for_update().get(pk=connection.pk, project=project)
        grant = GoogleOAuthGrant.objects.select_for_update().get(pk=grant.pk, project=project, organization=organization)
        origins = (sorted(set(grant.selected_origins) & set(verified_domain_origins(
            project, connection.external_property_id))) if connection.external_property_id.startswith("sc-domain:")
            else [connection.external_property_id])
        config = {"grant_revision": grant.revision, "property_id": connection.external_property_id,
                  "approved_origins": origins}
        _source(project=project, organization=organization, data=data, config=config)
        return queue_job(project=project, actor=actor, handler="collect_search_console_coverage",
                         input_snapshot=data, config_snapshot=config, idempotency_key=idempotency_key)


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
        if job.method_version != METHOD:
            return "source_revoked"
        _source(project=job.project, organization=job.organization, data=job.input_snapshot,
                config=job.config_snapshot)
    except (PermissionDenied, ValidationError):
        return "source_revoked"
    return ""


def _finish(job_id, error=""):
    org_id = JobRun.objects.filter(pk=job_id).values_list("organization_id", flat=True).first()
    if org_id is None:
        return False
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=org_id)
        job = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id)
        if job.handler != "collect_search_console_coverage" or job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            return False
        denied = _denial(job)
        category = (error if denied == "source_revoked" and error in {
            "authorization_unavailable", "property_unavailable", "reauthorization_required"
        } else denied or error)
        for step in JobStep.objects.filter(job=job, status=JobStep.Status.RUNNING):
            step.status = JobStep.Status.FAILED
            step.error_category = category or "request_outcome_unknown"
            step.output = {"state": "unknown"}
            step.save(update_fields=["status", "error_category", "output"])
        recorded = list(SearchConsoleCoverageObservation.objects.filter(job=job).values_list("source", flat=True))
        attempts = JobStep.objects.filter(job=job).count()
        if job.status == JobStatus.QUEUED and not denied:
            job.status = JobStatus.RUNNING
            job.save(update_fields=["status", "updated_at"])
        job.status = (JobStatus.CANCELLED if denied else JobStatus.PARTIALLY_SUCCEEDED if recorded and category
                      else JobStatus.FAILED if category else JobStatus.SUCCEEDED)
        job.error_category = category
        job.output = {"sources_recorded": sorted(recorded), "requests_attempted": attempts,
                      "coverage": "one_indexed_version_and_scoped_sitemaps" if recorded else "unavailable"}
        job.save(update_fields=["status", "error_category", "output", "updated_at"])
        if UsageReservation.objects.filter(job=job, state=UsageReservation.State.RESERVED).exists():
            settle_usage(job=job, actual_units=attempts)
    return True


def execute_search_console_coverage(job_id, *, refresh=refresh_google_tokens, verify_site=google_site_get,
                                    list_sitemaps=google_sitemaps_list, inspect=google_url_inspection):
    with _crawl_execution_lock(job_id) as acquired:
        if not acquired:
            return False
        try:
            return _execute(job_id, refresh=refresh, verify_site=verify_site,
                            list_sitemaps=list_sitemaps, inspect=inspect)
        except Exception:
            return _finish(job_id, error="handler_failed")


def _execute(job_id, *, refresh, verify_site, list_sitemaps, inspect):
    org_id = JobRun.objects.filter(pk=job_id).values_list("organization_id", flat=True).first()
    if org_id is None:
        return False
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=org_id)
        job = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id)
        if job.handler != "collect_search_console_coverage" or job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            return False
        denied = _denial(job)
        if not denied and job.status == JobStatus.QUEUED:
            job.status = JobStatus.RUNNING
            job.save(update_fields=["status", "updated_at"])
    if denied:
        return _finish(job_id)
    grant = None
    try:
        client = google_oauth_client(require_redirect=False)
        _connection, grant, _origins = _source(project=job.project, organization=job.organization,
                                               data=job.input_snapshot, config=job.config_snapshot)
        tokens = refresh(encrypted_refresh=grant.encrypted_refresh_token,
                         client_id=client.client_id, client_secret=client.client_secret)
        if not isinstance(tokens, GoogleTokens):
            raise GoogleTokenError("malformed_response")
    except GoogleTokenError as exc:
        if grant is not None and exc.category in {"authorization_rejected", "reauthorization_required"}:
            require_google_reconnect(grant=grant)
        return _finish(job_id, error=exc.category)
    except (PermissionDenied, ValidationError):
        return _finish(job_id, error="source_revoked")

    for sequence, source in ((1, "site"), (2, "sitemaps"), (3, "inspection")):
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=org_id)
            current = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id)
            denied = _denial(current)
            if denied:
                return _finish(job_id)
            existing = JobStep.objects.filter(job=current, sequence=sequence).first()
            if existing is not None:
                if existing.status == JobStep.Status.RUNNING:
                    return _finish(job_id, error="request_outcome_unknown")
                if existing.status == JobStep.Status.FAILED:
                    return _finish(job_id, error=existing.error_category or "request_outcome_unknown")
                if source != "site" and not SearchConsoleCoverageObservation.objects.filter(job=current, source=source).exists():
                    return _finish(job_id, error="request_outcome_unknown")
                continue
            JobStep.objects.create(job=current, sequence=sequence, name={
                "site": "Verify selected property", "sitemaps": "List selected sitemaps",
                "inspection": "Inspect selected URL in Google index",
            }[source], status=JobStep.Status.RUNNING, output={"state": "attempted"})
            current.save(update_fields=["updated_at"])
        snapshot = None
        try:
            if source == "site":
                site = verify_site(site_url=grant.selected_site_url, access_token=tokens.access_token)
                if _denial(job):
                    raise PermissionDenied
                candidates = exact_scope_search_console_sites(project=job.project, user=job.actor,
                                                                 response={"siteEntry": [site]})["sites"]
                if not any(item["external_property_id"] == job.config_snapshot["property_id"]
                           and (not item["external_property_id"].startswith("sc-domain:")
                                or set(job.config_snapshot["approved_origins"]) <= set(item["approved_origins"]))
                           for item in candidates):
                    if (type(site) is dict and (site.get("siteUrl") != grant.selected_site_url
                        or site.get("permissionLevel") not in {"siteOwner", "siteFullUser", "siteRestrictedUser"})):
                        require_google_reconnect(grant=grant, reason="property_unavailable")
                    raise PermissionDenied
            else:
                connection, grant, _origins = _source(project=job.project, organization=job.organization,
                                                      data=job.input_snapshot, config=job.config_snapshot)
                response = (list_sitemaps(connection=connection, access_token=tokens.access_token)
                            if source == "sitemaps" else inspect(connection=connection,
                            inspection_url=job.input_snapshot["inspection_url"], access_token=tokens.access_token))
                snapshot = record_coverage_observation(job=job, connection=connection, grant=grant,
                                                        source=source, response=response)
        except SearchConsoleTransportError as exc:
            failure = exc.category
            if failure in {"authorization_unavailable", "property_unavailable"}:
                require_google_reconnect(grant=grant, reason=failure)
        except GoogleTokenError as exc:
            failure = exc.category
        except PermissionDenied:
            failure = "source_revoked"
        except (ValidationError, TypeError):
            failure = "source_revoked" if _denial(job) else "malformed_response"
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
                "state": "verified" if source == "site" else "recorded",
                "snapshot_id": snapshot.pk if snapshot is not None else None}
            step.save(update_fields=["status", "error_category", "output"])
            current.save(update_fields=["updated_at"])
        if denied or failure:
            return _finish(job_id, error=step.error_category)
    return _finish(job_id)
