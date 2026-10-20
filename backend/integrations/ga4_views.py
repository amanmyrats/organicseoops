"""Private GA4 consent management; a selected grant is not a synced Analytics source."""

import json
from datetime import date
from http import HTTPStatus
from urllib.parse import urlencode

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from providers.google_app import google_analytics_oauth_client
from jobs.models import JobRun
from jobs.services import cancel_job
from jobs.usage import UsageLimitError
from tenancy.models import Project
from tenancy.services import Action, require_project_action

from .ga4_oauth import (SCOPE, begin_ga4_oauth_intent, complete_ga4_oauth,
                         consume_ga4_oauth_intent, link_ga4_source, revoke_ga4_grant, select_ga4_property)
from .google_tokens import GoogleTokenError
from .models import GA4OAuthGrant, IntegrationConnection, property_matches_project
from .oauth import OAuthStateError
from .oauth_views import _origin_matches_callback, _redirect, _return_to_project
from .search_console_transport import SearchConsoleTransportError
from .ga4_sync import GA4OriginAttributionUnavailable, queue_ga4_landing_sync
from .ga4_quality import record_ga4_measurement_review
from .models import GA4MeasurementReview


def _response(data, status=HTTPStatus.OK):
    result = JsonResponse(data, status=status)
    result["Cache-Control"] = "private, no-store"
    result["Referrer-Policy"] = "no-referrer"
    result["X-Robots-Tag"] = "noindex, nofollow"
    return result


def _error(message, status):
    return _response({"errors": [{"message": message}]}, status)


def _project(request, organization_id, project_id):
    return Project.objects.for_user(request.user).filter(pk=project_id, organization_id=organization_id).first()


def _payload(request, fields, *, limit=4096):
    if len(request.body) > limit:
        raise ValidationError("Choose bounded GA4 consent fields.")
    try:
        value = json.loads(request.body)
    except (UnicodeError, ValueError):
        raise ValidationError("Choose valid GA4 consent fields.") from None
    if type(value) is not dict or set(value) != fields:
        raise ValidationError("Choose exact GA4 consent fields.")
    return value


@require_POST
def ga4_oauth_start(request, organization_id, project_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _error("Project not found.", HTTPStatus.NOT_FOUND)
    try:
        _payload(request, set())
        require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
        client = google_analytics_oauth_client()
        if not _origin_matches_callback(request, client.redirect_uri):
            raise ValidationError("GA4 callback must share the browser origin.")
        if not ratelimit.consume(request, action="google_oauth_start", user=request.user):
            return _error("Consent requests are temporarily limited.", HTTPStatus.TOO_MANY_REQUESTS)
        intent, state = begin_ga4_oauth_intent(project=project, user=request.user,
                                               session_key=request.session.session_key)
        client = google_analytics_oauth_client()
        if client.redirect_uri != intent.redirect_uri or not _origin_matches_callback(request, client.redirect_uri):
            raise ValidationError("Analytics application changed before consent started.")
    except PermissionDenied:
        return _error("You cannot manage Analytics for this project.", HTTPStatus.FORBIDDEN)
    except (GoogleTokenError, ValidationError):
        return _error("Analytics consent is unavailable for this browser origin.", HTTPStatus.SERVICE_UNAVAILABLE)
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": client.client_id, "redirect_uri": client.redirect_uri, "response_type": "code",
        "scope": SCOPE, "access_type": "offline", "include_granted_scopes": "false",
        "prompt": "consent", "state": state,
    })
    return _response({"authorization_url": url, "expires_at": intent.expires_at.isoformat()}, HTTPStatus.CREATED)


@require_GET
def ga4_oauth_callback(request):
    if not request.user.is_authenticated or not request.user.is_active or not request.session.session_key:
        return _redirect("/account/login")
    try:
        client = google_analytics_oauth_client()
        if request.build_absolute_uri(request.path) != client.redirect_uri:
            raise OAuthStateError("GA4 callback origin did not match.")
        if not ratelimit.consume(request, action="google_oauth_callback", user=request.user):
            return _redirect("/app")
        state = request.GET.get("state", "")
        if request.GET.get("error"):
            intent = consume_ga4_oauth_intent(user=request.user, session_key=request.session.session_key,
                state=state, callback_url=client.redirect_uri, provider_denied=True)
            return _return_to_project(intent)
        grant = complete_ga4_oauth(user=request.user, session_key=request.session.session_key,
            state=state, callback_url=client.redirect_uri, code=request.GET.get("code", ""),
            client_id=client.client_id, client_secret=client.client_secret)
        return _return_to_project(grant)
    except (PermissionDenied, OAuthStateError, GoogleTokenError, ValidationError, SearchConsoleTransportError):
        return _redirect("/app")


@require_GET
def ga4_oauth_grants(request, organization_id, project_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _error("Project not found.", HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
    except PermissionDenied:
        return _error("Analytics grants are unavailable.", HTTPStatus.FORBIDDEN)
    grants = list(GA4OAuthGrant.objects.filter(project=project, organization=project.organization).order_by("-pk")[:21])
    connections = {item.credential_reference: item for item in IntegrationConnection.objects.filter(
        project=project, provider="google_analytics_4",
        credential_reference__in=[grant.credential_reference for grant in grants[:20]])}
    current_origins = {project.canonical_origin, *project.domain_aliases.values_list("origin", flat=True)}
    return _response({"project_id": project.pk, "grants": [
        {"id": grant.pk, "state": grant.state, "revision": grant.revision,
         "property_id": grant.property_id if grant.state != GA4OAuthGrant.State.REVOKED else "",
         "selected_origins": sorted(set(grant.selected_origins) & current_origins),
         "scope_current": bool(set(grant.selected_origins) & current_origins),
         "source_status": "configured_no_data_sync" if (
             (source := connections.get(grant.credential_reference)) and source.state == source.State.ACTIVE
             and property_matches_project(source)) else "not_linked_no_data_sync",
         "verified_at": grant.verified_at.isoformat()}
        for grant in grants[:20]], "has_more": len(grants) > 20})


@require_POST
def ga4_oauth_select(request, organization_id, project_id, grant_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _error("Project not found.", HTTPStatus.NOT_FOUND)
    grant = GA4OAuthGrant.objects.filter(project=project, organization=project.organization, pk=grant_id).first()
    if grant is None:
        return _error("Grant not found.", HTTPStatus.NOT_FOUND)
    if not ratelimit.consume(request, action="ga4_oauth_manage", user=request.user):
        return _error("Analytics requests are temporarily limited.", HTTPStatus.TOO_MANY_REQUESTS)
    try:
        data = _payload(request, {"property_id", "origin", "expected_revision"})
        client = google_analytics_oauth_client()
        grant = select_ga4_property(grant=grant, user=request.user, client_id=client.client_id,
            client_secret=client.client_secret, **data)
    except PermissionDenied:
        return _error("You cannot select this Analytics property.", HTTPStatus.FORBIDDEN)
    except (ValidationError, GoogleTokenError, SearchConsoleTransportError, TypeError):
        return _error("Analytics property or current project scope is unavailable.", HTTPStatus.CONFLICT)
    return _response({"id": grant.pk, "project_id": project.pk, "state": grant.state,
                      "property_id": grant.property_id, "selected_origins": grant.selected_origins,
                      "revision": grant.revision, "source_status": "not_linked_no_data_sync"})


@require_POST
def ga4_oauth_link(request, organization_id, project_id, grant_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _error("Project not found.", HTTPStatus.NOT_FOUND)
    grant = GA4OAuthGrant.objects.filter(project=project, organization=project.organization, pk=grant_id).first()
    if grant is None:
        return _error("Grant not found.", HTTPStatus.NOT_FOUND)
    if not ratelimit.consume(request, action="ga4_oauth_manage", user=request.user):
        return _error("Analytics requests are temporarily limited.", HTTPStatus.TOO_MANY_REQUESTS)
    try:
        revision = _payload(request, {"expected_revision"})["expected_revision"]
        client = google_analytics_oauth_client()
        grant, connection = link_ga4_source(grant=grant, user=request.user, expected_revision=revision,
            client_id=client.client_id, client_secret=client.client_secret)
    except PermissionDenied:
        return _error("You cannot link this Analytics source.", HTTPStatus.FORBIDDEN)
    except (ValidationError, GoogleTokenError, SearchConsoleTransportError, TypeError):
        return _error("Analytics property or reporting scope is unavailable.", HTTPStatus.CONFLICT)
    return _response({"id": grant.pk, "project_id": project.pk, "connection_id": connection.pk,
                      "state": grant.state, "revision": grant.revision,
                      "source_status": "configured_no_data_sync"})


@require_POST
def ga4_oauth_revoke(request, organization_id, project_id, grant_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _error("Project not found.", HTTPStatus.NOT_FOUND)
    grant = GA4OAuthGrant.objects.filter(project=project, organization=project.organization, pk=grant_id).first()
    if grant is None:
        return _error("Grant not found.", HTTPStatus.NOT_FOUND)
    if not ratelimit.consume(request, action="ga4_oauth_manage", user=request.user):
        return _error("Analytics requests are temporarily limited.", HTTPStatus.TOO_MANY_REQUESTS)
    try:
        _payload(request, set())
        grant = revoke_ga4_grant(grant=grant, user=request.user)
    except PermissionDenied:
        return _error("You cannot revoke this Analytics grant.", HTTPStatus.FORBIDDEN)
    except (ValidationError, GoogleTokenError, SearchConsoleTransportError):
        return _error("Analytics grant disabled locally; provider revocation remains pending.", HTTPStatus.SERVICE_UNAVAILABLE)
    return _response({"id": grant.pk, "project_id": project.pk, "state": grant.state,
                      "source_status": "not_linked_no_data_sync"})


def _source(request, organization_id, project_id, connection_id):
    project = _project(request, organization_id, project_id)
    connection = IntegrationConnection.objects.filter(project=project, pk=connection_id,
        provider="google_analytics_4").first() if project else None
    if connection is not None:
        require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
    return project, connection


def _job(job):
    return {"id": job.pk, "status": job.status, "day": job.input_snapshot["day"],
            "report_kind": job.input_snapshot.get("report_kind", "unavailable"),
            "hostname": job.input_snapshot["hostname"], "error_category": job.error_category or job.dispatch_error,
            "requests_attempted": job.output.get("requests_attempted", 0),
            "pages_recorded": job.output.get("pages_recorded", 0),
            "source_coverage": job.output.get("source_coverage", "unavailable"),
            "sampling_or_threshold_gaps": job.output.get("sampling_or_threshold_gaps")}


@require_POST
def ga4_sync_start(request, organization_id, project_id, connection_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    try:
        project, connection = _source(request, organization_id, project_id, connection_id)
        if connection is None:
            return _error("Source not found.", HTTPStatus.NOT_FOUND)
        if not ratelimit.consume(request, action="ga4_sync", user=request.user):
            return _error("Analytics requests are temporarily limited.", HTTPStatus.TOO_MANY_REQUESTS)
        data = _payload(request, {"day", "idempotency_key", "report_kind"})
        if (type(data["day"]) is not str or type(data["idempotency_key"]) is not str
            or type(data["report_kind"]) is not str):
            raise ValidationError("Choose one GA4 day and request key.")
        day = date.fromisoformat(data["day"])
        if day.isoformat() != data["day"]:
            raise ValidationError("Choose one exact GA4 reporting day.")
        grant = GA4OAuthGrant.objects.filter(project=project, organization=project.organization,
            credential_reference=connection.credential_reference, property_id=connection.external_property_id,
            state=GA4OAuthGrant.State.ACTIVE).first() if connection.credential_reference else None
        if grant is None:
            raise ValidationError("Analytics grant is unavailable.")
        job = queue_ga4_landing_sync(project=project, actor=request.user, connection=connection,
            grant=grant, day=day, report_kind=data["report_kind"], idempotency_key=data["idempotency_key"])
    except PermissionDenied:
        return _error("You cannot sync this Analytics source.", HTTPStatus.FORBIDDEN)
    except GoogleTokenError:
        return _error("Analytics application is not configured.", HTTPStatus.SERVICE_UNAVAILABLE)
    except GA4OriginAttributionUnavailable:
        return _error("GA4 cannot attribute landing sessions to this exact HTTPS origin; reports are unavailable.",
                      HTTPStatus.CONFLICT)
    except UsageLimitError as exc:
        return _response({"errors": [{"message": "Trial or source capacity is unavailable.",
                                      "code": exc.category}]},
                         HTTPStatus.FORBIDDEN if exc.category == "trial_unavailable" else HTTPStatus.TOO_MANY_REQUESTS)
    except (ValidationError, TypeError, ValueError, KeyError):
        return _error("Choose one active scoped GA4 source and an aged reporting day.", HTTPStatus.CONFLICT)
    return _response({"project_id": project.pk, "connection_id": connection.pk,
                      "job_id": job.pk, "status": job.status, "max_requests": job.usage.reserved_units,
                      "report_kind": job.input_snapshot["report_kind"],
                      "source_coverage": ("ga4_organic_session_channel_hostname_filtered"
                          if job.input_snapshot["report_kind"] == "organic_search" else
                          "hostname_filtered_reporting_gaps_unknown")}, HTTPStatus.ACCEPTED)


@require_GET
def ga4_sync_status(request, organization_id, project_id, connection_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    try:
        project, connection = _source(request, organization_id, project_id, connection_id)
    except PermissionDenied:
        return _error("You cannot inspect this Analytics source.", HTTPStatus.FORBIDDEN)
    if connection is None:
        return _error("Source not found.", HTTPStatus.NOT_FOUND)
    job = JobRun.objects.filter(project=project, handler="sync_ga4_landing",
        input_snapshot__connection_id=connection.pk).order_by("-created_at", "-pk").first()
    # Previously collected hostname-only pages cannot establish exact-origin ownership either.
    return _response({"project_id": project.pk, "connection_id": connection.pk,
        "source_current": False, "report_availability": "exact_origin_attribution_unavailable",
        "job": {**_job(job), "pages_recorded": 0, "source_coverage": "unavailable"} if job else None,
        "pages": []})


@require_POST
def ga4_sync_cancel(request, organization_id, project_id, connection_id, job_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    try:
        project, connection = _source(request, organization_id, project_id, connection_id)
        if connection is None:
            return _error("Source not found.", HTTPStatus.NOT_FOUND)
        job = JobRun.objects.filter(project=project, pk=job_id, handler="sync_ga4_landing",
                                    input_snapshot__connection_id=connection.pk).first()
        if job is None:
            return _error("Job not found.", HTTPStatus.NOT_FOUND)
        _payload(request, set())
        job, _created, pending = cancel_job(job=job, actor=request.user)
    except PermissionDenied:
        return _error("You cannot cancel this Analytics job.", HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _error("Analytics job cannot be cancelled in its current state.", HTTPStatus.CONFLICT)
    return _response({"project_id": project.pk, "connection_id": connection.pk,
                      "job": _job(job), "cancel_requested": pending})


def _quality_row(row):
    return {"id": row.pk, "revision": row.revision, "property_id": row.property_id,
            "currency": row.currency, "timezone": row.timezone,
            "definitions": row.definitions, "instrumentation_state": row.instrumentation_state,
            "event_quality_state": row.event_quality_state,
            "instrumentation_notes": row.instrumentation_notes, "attribution_notes": row.attribution_notes,
            "consent_notes": row.consent_notes, "tracking_change_notes": row.tracking_change_notes,
            "created_at": row.created_at.isoformat()}


@require_GET
def ga4_quality_history(request, organization_id, project_id, connection_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    try:
        project, connection = _source(request, organization_id, project_id, connection_id)
    except PermissionDenied:
        return _error("You cannot inspect Analytics quality reviews.", HTTPStatus.FORBIDDEN)
    if connection is None:
        return _error("Source not found.", HTTPStatus.NOT_FOUND)
    rows = list(GA4MeasurementReview.objects.filter(project=project, connection=connection)
                .order_by("-revision")[:21])
    return _response({"project_id": project.pk, "connection_id": connection.pk,
        "source_current": connection.state == connection.State.ACTIVE and property_matches_project(connection),
        "reviews": [_quality_row(row) for row in rows[:20]], "has_more": len(rows) > 20})


@require_POST
def ga4_quality_review(request, organization_id, project_id, connection_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    try:
        project, connection = _source(request, organization_id, project_id, connection_id)
        if connection is None:
            return _error("Source not found.", HTTPStatus.NOT_FOUND)
        if not ratelimit.consume(request, action="ga4_oauth_manage", user=request.user):
            return _error("Analytics review requests are temporarily limited.", HTTPStatus.TOO_MANY_REQUESTS)
        data = _payload(request, {"expected_revision", "definitions", "instrumentation_state",
                                  "event_quality_state",
                                  "instrumentation_notes", "attribution_notes", "consent_notes",
                                  "tracking_change_notes"}, limit=8192)
        review = record_ga4_measurement_review(project=project, user=request.user,
            connection=connection, **data)
    except PermissionDenied:
        return _error("You cannot review this Analytics source.", HTTPStatus.FORBIDDEN)
    except (ValidationError, TypeError):
        return _error("Measurement definitions changed or their GA4 scope is unavailable.", HTTPStatus.CONFLICT)
    return _response({"project_id": project.pk, "connection_id": connection.pk,
                      "review": _quality_row(review), "provider_instrumentation_verified": False}, HTTPStatus.CREATED)
