import json
from datetime import date
from http import HTTPStatus
from urllib.parse import urlencode, urlsplit

from allauth.core import ratelimit
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponseRedirect, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from providers.google_app import google_oauth_client
from jobs.models import JobRun, JobSchedule
from jobs.services import cancel_job
from tenancy.models import Project
from tenancy.services import Action, require_project_action

from .google_oauth import complete_google_oauth, revoke_google_grant, select_google_site
from .google_tokens import GoogleTokenError, revoke_google_tokens, SCOPE
from .models import GoogleOAuthGrant, IntegrationConnection, SearchConsoleBackfill, verified_domain_origins
from .oauth import OAuthStateError, begin_google_oauth_intent, configured_redirect_uri, consume_google_oauth_intent
from .search_console_transport import SearchConsoleTransportError
from .search_console_sync import queue_search_console_sync
from .search_console_backfill import queue_search_console_backfill
from .search_console_schedule import create_search_console_schedule, set_search_console_schedule_enabled
from .search_console_coverage_job import queue_search_console_coverage
from .models import SearchConsoleCoverageObservation
from jobs.usage import UsageLimitError


def _response(payload, status=HTTPStatus.OK):
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


def _error(message, status, *, code=None):
    error = {"message": message}
    if code:
        error["code"] = code
    return _response({"errors": [error]}, status)


def _project(request, organization_id, project_id):
    return Project.objects.for_user(request.user).filter(pk=project_id, organization_id=organization_id).first()


def _payload(request, keys):
    if len(request.body) > 4096:
        raise ValidationError("Check the submitted OAuth fields.")
    try:
        value = json.loads(request.body)
    except (ValueError, UnicodeError):
        raise ValidationError("Check the submitted OAuth fields.") from None
    if type(value) is not dict or set(value) != keys:
        raise ValidationError("Check the submitted OAuth fields.")
    return value


def _configured_client():
    return google_oauth_client()


def _origin_matches_callback(request, redirect_uri):
    expected = urlsplit(redirect_uri)
    actual = urlsplit(request.build_absolute_uri(request.path))
    return (actual.scheme, actual.netloc) == (expected.scheme, expected.netloc)


@require_POST
def google_oauth_start(request, organization_id, project_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _error("Project not found.", HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
        client = _configured_client()
        redirect_uri = client.redirect_uri
        if not _origin_matches_callback(request, redirect_uri):
            raise ValidationError("OAuth callback must share this browser origin.")
        if not ratelimit.consume(request, action="google_oauth_start", user=request.user):
            return _error("OAuth requests are temporarily limited.", HTTPStatus.TOO_MANY_REQUESTS)
        intent, state = begin_google_oauth_intent(
            project=project, user=request.user, session_key=request.session.session_key,
        )
        client = _configured_client()
        if client.redirect_uri != intent.redirect_uri or not _origin_matches_callback(request, client.redirect_uri):
            raise ValidationError("OAuth application changed before consent could start.")
    except PermissionDenied:
        return _error("You cannot manage this connection.", HTTPStatus.FORBIDDEN)
    except (GoogleTokenError, ValidationError):
        return _error("Google OAuth is not configured for this browser origin.", HTTPStatus.SERVICE_UNAVAILABLE)
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": client.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "include_granted_scopes": "false",
        "prompt": "consent",
        "state": state,
    })
    return _response({"authorization_url": url, "expires_at": intent.expires_at.isoformat()}, HTTPStatus.CREATED)


def _redirect(path):
    response = HttpResponseRedirect(f"{settings.FRONTEND_ORIGIN}{path}")
    response.status_code = HTTPStatus.SEE_OTHER
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


def _return_to_project(record):
    return _redirect(f"/app/onboarding/{record.organization_id}/{getattr(record, 'project_id', record.pk)}")


@require_GET
def google_oauth_callback(request):
    if not request.user.is_authenticated or not request.user.is_active or not request.session.session_key:
        return _redirect("/account/login")
    try:
        redirect_uri = _configured_client().redirect_uri
        if request.build_absolute_uri(request.path) != redirect_uri:
            raise OAuthStateError("OAuth callback origin did not match.")
        if not ratelimit.consume(request, action="google_oauth_callback", user=request.user):
            return _redirect("/app")
        state = request.GET.get("state", "")
        if request.GET.get("error"):
            intent = consume_google_oauth_intent(
                user=request.user, session_key=request.session.session_key, state=state,
                callback_url=redirect_uri, provider_denied=True,
            )
            return _return_to_project(intent)
        code = request.GET.get("code", "")
        grant, _ = complete_google_oauth(
            user=request.user, session_key=request.session.session_key, state=state,
            callback_url=redirect_uri, code=code,
        )
        return _return_to_project(grant)
    except PermissionDenied:
        return _redirect("/app")
    except (GoogleTokenError, SearchConsoleTransportError, OAuthStateError, ValidationError):
        return _redirect("/app")


def _visible_site(project, site, current_origins):
    if type(site) is not dict or type(site.get("external_property_id")) is not str \
            or type(site.get("google_site_url")) is not str:
        return None
    if site.get("scope") == "verified_domain_page_only":
        if type(site.get("approved_origins")) is not list \
                or any(type(origin) is not str for origin in site["approved_origins"]):
            return None
        try:
            approved = sorted(set(site["approved_origins"]) & set(verified_domain_origins(
                project, site["external_property_id"])))
        except ValidationError:
            return None
        if not approved:
            return None
        return {"property": site["external_property_id"], "site_url": site["google_site_url"],
                "scope": "verified_domain_page_only", "approved_origins": approved,
                "available_dimensions": ["page"]}
    if site.get("scope") != "exact_origin_url_prefix" or site["external_property_id"] not in current_origins:
        return None
    return {"property": site["external_property_id"], "site_url": site["google_site_url"],
            "scope": "exact_origin_url_prefix", "approved_origins": [site["external_property_id"]],
            "available_dimensions": ["date", "query", "page"]}


@require_GET
def google_oauth_grants(request, organization_id, project_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _error("Project not found.", HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
    except PermissionDenied:
        return _error("You cannot manage these connections.", HTTPStatus.FORBIDDEN)
    grants = list(GoogleOAuthGrant.objects.filter(project=project).order_by("-created_at", "-pk")[:21])
    current_origins = {project.canonical_origin, *project.domain_aliases.values_list("origin", flat=True)}
    return _response({"project_id": project.pk, "has_more": len(grants) > 20,
                      "grants": [{"id": item.pk, "state": item.state, "revision": item.revision,
                                   "sites": [visible for site in item.selectable_sites
                                             if (visible := _visible_site(project, site, current_origins)) is not None],
                                  "verified_at": item.verified_at.isoformat()}
                                 for item in grants[:20]]})


@require_POST
def google_oauth_select(request, organization_id, project_id, grant_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    grant = GoogleOAuthGrant.objects.filter(pk=grant_id, project=project).first() if project else None
    if grant is None:
        return _error("Connection not found.", HTTPStatus.NOT_FOUND)
    try:
        payload = _payload(request, {"site_url", "revision"})
        connection = select_google_site(grant=grant, user=request.user, site_url=payload["site_url"],
                                        expected_revision=payload["revision"])
    except PermissionDenied:
        return _error("You cannot select this Google property.", HTTPStatus.FORBIDDEN)
    except (GoogleTokenError, SearchConsoleTransportError, ValidationError, TypeError):
        return _error("The Google property is unavailable. Reconnect and retry.", HTTPStatus.CONFLICT)
    return _response({"connection_id": connection.pk, "project_id": project.pk, "state": "active"})


@require_POST
def google_oauth_revoke(request, organization_id, project_id, grant_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    grant = GoogleOAuthGrant.objects.filter(pk=grant_id, project=project).first() if project else None
    if grant is None:
        return _error("Connection not found.", HTTPStatus.NOT_FOUND)
    try:
        payload = _payload(request, {"revision"})
        pending = revoke_google_grant(grant=grant, user=request.user, expected_revision=payload["revision"])
        if pending.state == GoogleOAuthGrant.State.REVOCATION_PENDING:
            try:
                pending = revoke_google_grant(grant=pending, user=request.user, expected_revision=pending.revision,
                                              remote_revoke=revoke_google_tokens)
            except GoogleTokenError:
                pass
    except PermissionDenied:
        return _error("You cannot revoke this connection.", HTTPStatus.FORBIDDEN)
    except (ValidationError, TypeError):
        return _error("The connection changed; reload before retrying.", HTTPStatus.CONFLICT)
    return _response({"state": pending.state, "revision": pending.revision},
                     HTTPStatus.ACCEPTED if pending.state == GoogleOAuthGrant.State.REVOCATION_PENDING else HTTPStatus.OK)


@require_POST
def google_sync_start(request, organization_id, project_id, connection_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    connection = IntegrationConnection.objects.filter(pk=connection_id, project=project).first() if project else None
    if connection is None:
        return _error("Source not found.", HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
        if not ratelimit.consume(request, action="search_console_sync", user=request.user):
            return _error("Search Console sync requests are temporarily limited.", HTTPStatus.TOO_MANY_REQUESTS)
        payload = _payload(request, {"day", "dimensions", "idempotency_key"})
        grant = GoogleOAuthGrant.objects.filter(project=project, credential_reference=connection.credential_reference,
                                                 state=GoogleOAuthGrant.State.ACTIVE).first() if connection.credential_reference else None
        if grant is None:
            raise ValidationError("Google authorization is unavailable.")
        job = queue_search_console_sync(project=project, actor=request.user, connection=connection, grant=grant,
                                        day=payload["day"], dimensions=payload["dimensions"],
                                        idempotency_key=payload["idempotency_key"])
    except PermissionDenied:
        return _error("You cannot sync this source.", HTTPStatus.FORBIDDEN)
    except GoogleTokenError:
        return _error("Google synchronization is not configured.", HTTPStatus.SERVICE_UNAVAILABLE)
    except UsageLimitError as error:
        if error.category == "trial_unavailable":
            return _error("Active trial access is required for this sync.", HTTPStatus.FORBIDDEN, code=error.category)
        if error.category == "trial_units_exhausted":
            return _error("Trial unit allowance reached.", HTTPStatus.TOO_MANY_REQUESTS, code=error.category)
        return _error("Internal source capacity is currently limited.", HTTPStatus.TOO_MANY_REQUESTS, code=error.category)
    except (ValidationError, TypeError, ValueError):
        return _error("Choose an active exact-scope source and a bounded finalized report day.", HTTPStatus.CONFLICT)
    return _response({"job_id": job.pk, "project_id": project.pk, "status": job.status,
                      "max_requests": job.usage.reserved_units,
                       "source_coverage": ("top_rows_only_domain_page_filtered" if job.config_snapshot.get("scope_strategy") == "domain-page-v1"
                                           else "top_rows_only")}, HTTPStatus.ACCEPTED)


def _sync_source(request, organization_id, project_id, connection_id):
    project = _project(request, organization_id, project_id)
    connection = IntegrationConnection.objects.filter(pk=connection_id, project=project).first() if project else None
    if connection is None:
        return None, None
    require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
    return project, connection


@require_GET
def google_sync_status(request, organization_id, project_id, connection_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    try:
        project, connection = _sync_source(request, organization_id, project_id, connection_id)
    except PermissionDenied:
        return _error("You cannot inspect this source.", HTTPStatus.FORBIDDEN)
    if connection is None:
        return _error("Source not found.", HTTPStatus.NOT_FOUND)
    job = JobRun.objects.filter(project=project, handler="sync_search_console",
                                 input_snapshot__connection_id=connection.pk,
                                 input_snapshot__report__isnull=True).order_by("-created_at", "-pk").first()
    return _response({"project_id": project.pk, "connection_id": connection.pk,
                      "job": None if job is None else _sync_job_payload(job)})


def _sync_job_payload(job):
    return {"id": job.pk, "status": job.status, "day": job.input_snapshot["day"],
            "dimensions": job.input_snapshot["dimensions"], "error_category": job.error_category or job.dispatch_error,
            "requests_attempted": job.output.get("requests_attempted", 0),
            "pages_recorded": job.output.get("pages_recorded", 0),
             "source_coverage": job.output.get("source_coverage", "unavailable")}


def _backfill_payload(batch):
    return {"id": batch.pk, "status": batch.status, "start_day": batch.start_day.isoformat(),
            "end_day": batch.end_day.isoformat(), "next_day": batch.next_day.isoformat(),
            "dimension": batch.dimension, "current_job": batch.current_job_id,
            "error_category": batch.error_category}


def _source_schedule_payload(schedule):
    return {"id": schedule.pk, "enabled": schedule.enabled,
            "dimension": schedule.input_snapshot["dimension"],
            "next_run_at": schedule.next_run_at.isoformat() if schedule.next_run_at else None,
            "last_run_at": schedule.last_run_at.isoformat() if schedule.last_run_at else None,
            "last_error_category": schedule.last_error_category,
            "skipped_occurrences": schedule.skipped_occurrences}


@require_POST
def google_source_schedule_start(request, organization_id, project_id, connection_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    try:
        project, connection = _sync_source(request, organization_id, project_id, connection_id)
        if connection is None:
            return _error("Source not found.", HTTPStatus.NOT_FOUND)
        if not ratelimit.consume(request, action="search_console_sync", user=request.user):
            return _error("Search Console requests are temporarily limited.", HTTPStatus.TOO_MANY_REQUESTS)
        data = _payload(request, {"dimension", "idempotency_key"})
        grant = GoogleOAuthGrant.objects.filter(project=project, credential_reference=connection.credential_reference,
                                                 state=GoogleOAuthGrant.State.ACTIVE).first() if connection.credential_reference else None
        if grant is None:
            raise ValidationError("Source grant is unavailable.")
        schedule = create_search_console_schedule(project=project, actor=request.user, connection=connection,
            grant=grant, dimension=data["dimension"], idempotency_key=data["idempotency_key"])
    except PermissionDenied:
        return _error("You cannot schedule this source.", HTTPStatus.FORBIDDEN)
    except GoogleTokenError:
        return _error("Google synchronization is not configured.", HTTPStatus.SERVICE_UNAVAILABLE)
    except UsageLimitError as error:
        return _error("Trial access is unavailable for this schedule.", HTTPStatus.FORBIDDEN
                      if error.category == "trial_unavailable" else HTTPStatus.TOO_MANY_REQUESTS, code=error.category)
    except (ValidationError, TypeError, KeyError):
        return _error("Choose an active source and one supported schedule dimension.", HTTPStatus.CONFLICT)
    return _response({"project_id": project.pk, "connection_id": connection.pk,
                      "schedule": _source_schedule_payload(schedule)}, HTTPStatus.CREATED)


@require_GET
def google_source_schedule_status(request, organization_id, project_id, connection_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    try:
        project, connection = _sync_source(request, organization_id, project_id, connection_id)
    except PermissionDenied:
        return _error("You cannot inspect this source.", HTTPStatus.FORBIDDEN)
    if connection is None:
        return _error("Source not found.", HTTPStatus.NOT_FOUND)
    schedule = JobSchedule.objects.filter(project=project, handler="sync_search_console",
                                          input_snapshot__connection_id=connection.pk).first()
    return _response({"project_id": project.pk, "connection_id": connection.pk,
                      "schedule": _source_schedule_payload(schedule) if schedule else None})


@require_POST
def google_source_schedule_toggle(request, organization_id, project_id, connection_id, schedule_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    try:
        project, connection = _sync_source(request, organization_id, project_id, connection_id)
        if connection is None:
            return _error("Source not found.", HTTPStatus.NOT_FOUND)
        data = _payload(request, {"enabled"})
        schedule = set_search_console_schedule_enabled(project=project, actor=request.user,
            connection=connection, schedule_id=schedule_id, enabled=data["enabled"])
    except PermissionDenied:
        return _error("You cannot change this schedule.", HTTPStatus.FORBIDDEN)
    except GoogleTokenError:
        return _error("Google synchronization is not configured.", HTTPStatus.SERVICE_UNAVAILABLE)
    except UsageLimitError as error:
        return _error("Trial access is unavailable for this schedule.", HTTPStatus.FORBIDDEN, code=error.category)
    except (ValidationError, TypeError, KeyError):
        return _error("Schedule or source is unavailable.", HTTPStatus.CONFLICT)
    return _response({"project_id": project.pk, "connection_id": connection.pk,
                      "schedule": _source_schedule_payload(schedule)})


@require_POST
def google_backfill_start(request, organization_id, project_id, connection_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    try:
        project, connection = _sync_source(request, organization_id, project_id, connection_id)
        if connection is None:
            return _error("Source not found.", HTTPStatus.NOT_FOUND)
        if not ratelimit.consume(request, action="search_console_sync", user=request.user):
            return _error("Search Console requests are temporarily limited.", HTTPStatus.TOO_MANY_REQUESTS)
        payload = _payload(request, {"start_day", "end_day", "dimension", "idempotency_key"})
        if (type(payload["start_day"]) is not str or type(payload["end_day"]) is not str
            or any(len(payload[key]) != 10 for key in ("start_day", "end_day"))):
            raise ValidationError("Choose a finalized backfill date range.")
        start_day, end_day = date.fromisoformat(payload["start_day"]), date.fromisoformat(payload["end_day"])
        if start_day.isoformat() != payload["start_day"] or end_day.isoformat() != payload["end_day"]:
            raise ValidationError("Choose canonical backfill dates.")
        grant = GoogleOAuthGrant.objects.filter(project=project, credential_reference=connection.credential_reference,
                                                 state=GoogleOAuthGrant.State.ACTIVE).first() if connection.credential_reference else None
        if grant is None:
            raise ValidationError("Source grant is unavailable.")
        batch = queue_search_console_backfill(project=project, actor=request.user, connection=connection,
            grant=grant, start_day=start_day, end_day=end_day, dimension=payload["dimension"],
            idempotency_key=payload["idempotency_key"])
    except PermissionDenied:
        return _error("You cannot backfill this source.", HTTPStatus.FORBIDDEN)
    except GoogleTokenError:
        return _error("Google synchronization is not configured.", HTTPStatus.SERVICE_UNAVAILABLE)
    except UsageLimitError as error:
        return _error("Trial access is unavailable for this backfill.", HTTPStatus.FORBIDDEN
                      if error.category == "trial_unavailable" else HTTPStatus.TOO_MANY_REQUESTS, code=error.category)
    except (ValidationError, ValueError, TypeError, KeyError):
        return _error("Choose an active source and up to seven finalized report days.", HTTPStatus.CONFLICT)
    return _response({"project_id": project.pk, "connection_id": connection.pk,
                      "backfill": _backfill_payload(batch)}, HTTPStatus.ACCEPTED)


@require_GET
def google_backfill_status(request, organization_id, project_id, connection_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    try:
        project, connection = _sync_source(request, organization_id, project_id, connection_id)
    except PermissionDenied:
        return _error("You cannot inspect this source.", HTTPStatus.FORBIDDEN)
    if connection is None:
        return _error("Source not found.", HTTPStatus.NOT_FOUND)
    batch = SearchConsoleBackfill.objects.filter(project=project, connection=connection).order_by("-created_at", "-pk").first()
    return _response({"project_id": project.pk, "connection_id": connection.pk,
                      "backfill": _backfill_payload(batch) if batch else None})


@require_POST
def google_backfill_cancel(request, organization_id, project_id, connection_id, backfill_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    try:
        project, connection = _sync_source(request, organization_id, project_id, connection_id)
        if connection is None:
            return _error("Source not found.", HTTPStatus.NOT_FOUND)
        _payload(request, set())
        from .search_console_backfill import pause_search_console_backfill
        batch = pause_search_console_backfill(project=project, actor=request.user, connection=connection, backfill_id=backfill_id)
    except PermissionDenied:
        return _error("You cannot cancel this backfill.", HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _error("Backfill is unavailable or already complete.", HTTPStatus.CONFLICT)
    return _response({"project_id": project.pk, "connection_id": connection.pk, "backfill": _backfill_payload(batch)})


@require_POST
def google_sync_cancel(request, organization_id, project_id, connection_id, job_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    try:
        project, connection = _sync_source(request, organization_id, project_id, connection_id)
    except PermissionDenied:
        return _error("You cannot cancel this source's work.", HTTPStatus.FORBIDDEN)
    if connection is None:
        return _error("Source not found.", HTTPStatus.NOT_FOUND)
    job = JobRun.objects.filter(pk=job_id, project=project, handler="sync_search_console",
                                input_snapshot__connection_id=connection.pk).first()
    if job is None:
        return _error("Sync job not found.", HTTPStatus.NOT_FOUND)
    try:
        _payload(request, set())
        job, _, requested = cancel_job(job=job, actor=request.user)
    except (PermissionDenied, ValidationError):
        return _error("This sync cannot be cancelled.", HTTPStatus.CONFLICT)
    return _response({"project_id": project.pk, "connection_id": connection.pk,
                      "job": _sync_job_payload(job), "cancel_requested": requested},
                     HTTPStatus.ACCEPTED if requested else HTTPStatus.OK)


def _coverage_job_payload(job):
    observations = list(SearchConsoleCoverageObservation.objects.filter(job=job).order_by("source")[:3])
    return {"id": job.pk, "status": job.status, "error_category": job.error_category or job.dispatch_error,
            "inspection_url": job.input_snapshot["inspection_url"],
            "requests_attempted": job.output.get("requests_attempted", 0),
            "sources_recorded": job.output.get("sources_recorded", []),
            "results": [{"source": item.source, "result": item.result} for item in observations]}


@require_POST
def google_coverage_start(request, organization_id, project_id, connection_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    try:
        project, connection = _sync_source(request, organization_id, project_id, connection_id)
    except PermissionDenied:
        return _error("You cannot inspect this source.", HTTPStatus.FORBIDDEN)
    if connection is None:
        return _error("Source not found.", HTTPStatus.NOT_FOUND)
    if not ratelimit.consume(request, action="search_console_coverage", user=request.user):
        return _error("Search Console inspection requests are temporarily limited.", HTTPStatus.TOO_MANY_REQUESTS)
    try:
        payload = _payload(request, {"inspection_url", "idempotency_key"})
        grant = GoogleOAuthGrant.objects.filter(project=project, credential_reference=connection.credential_reference,
                                                 state=GoogleOAuthGrant.State.ACTIVE).first() if connection.credential_reference else None
        if grant is None:
            raise ValidationError("Google authorization is unavailable.")
        job = queue_search_console_coverage(project=project, actor=request.user, connection=connection, grant=grant,
                                            inspection_url=payload["inspection_url"],
                                            idempotency_key=payload["idempotency_key"])
    except PermissionDenied:
        return _error("You cannot inspect this project source.", HTTPStatus.FORBIDDEN)
    except GoogleTokenError:
        return _error("Google synchronization is not configured.", HTTPStatus.SERVICE_UNAVAILABLE)
    except UsageLimitError as error:
        return _error("Trial or internal inspection capacity is unavailable.", HTTPStatus.TOO_MANY_REQUESTS,
                      code=error.category)
    except (ValidationError, TypeError, ValueError):
        return _error("Choose a currently authorized exact project URL and bounded request.", HTTPStatus.CONFLICT)
    return _response({"project_id": project.pk, "connection_id": connection.pk,
                      "job": _coverage_job_payload(job), "max_requests": 3}, HTTPStatus.ACCEPTED)


@require_GET
def google_coverage_status(request, organization_id, project_id, connection_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    try:
        project, connection = _sync_source(request, organization_id, project_id, connection_id)
    except PermissionDenied:
        return _error("You cannot inspect this source.", HTTPStatus.FORBIDDEN)
    if connection is None:
        return _error("Source not found.", HTTPStatus.NOT_FOUND)
    job = JobRun.objects.filter(project=project, handler="collect_search_console_coverage",
                                 input_snapshot__connection_id=connection.pk).order_by("-created_at", "-pk").first()
    return _response({"project_id": project.pk, "connection_id": connection.pk,
                      "job": _coverage_job_payload(job) if job is not None else None})


@require_POST
def google_coverage_cancel(request, organization_id, project_id, connection_id, job_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    try:
        project, connection = _sync_source(request, organization_id, project_id, connection_id)
    except PermissionDenied:
        return _error("You cannot cancel this source's work.", HTTPStatus.FORBIDDEN)
    if connection is None:
        return _error("Source not found.", HTTPStatus.NOT_FOUND)
    job = JobRun.objects.filter(pk=job_id, project=project, handler="collect_search_console_coverage",
                                 input_snapshot__connection_id=connection.pk).first()
    if job is None:
        return _error("Inspection job not found.", HTTPStatus.NOT_FOUND)
    try:
        _payload(request, set())
        job, _changed, requested = cancel_job(job=job, actor=request.user)
    except (PermissionDenied, ValidationError):
        return _error("This inspection cannot be cancelled.", HTTPStatus.CONFLICT)
    return _response({"project_id": project.pk, "connection_id": connection.pk,
                      "job": _coverage_job_payload(job), "cancel_requested": requested},
                     HTTPStatus.ACCEPTED if requested else HTTPStatus.OK)
