import json
import re

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.views.decorators.http import require_http_methods

from jobs.usage import UsageLimitError
from tenancy.services import Action, require_project_action

from .google_tokens import GoogleTokenError
from .models import GoogleOAuthGrant, IntegrationConnection
from .oauth_views import _error, _project, _response
from .search_console_query_page import paired_job_metadata, paired_jobs, paired_source_current, read_paired_evidence
from .search_console_sync import queue_search_console_sync
from .search_console_transport import _reject_constant, _unique_object


@require_http_methods(["GET", "POST"])
def project_query_page(request, organization_id, project_id, connection_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", 401)
    project = _project(request, organization_id, project_id)
    connection = IntegrationConnection.objects.filter(project=project, pk=connection_id).first() if project else None
    if connection is None:
        return _error("Source not found.", 404)
    try:
        require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
        if request.method == "GET":
            if request.GET:
                if set(request.GET) == {"request_key"}:
                    values = request.GET.getlist("request_key")
                    if len(values) != 1 or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", values[0]):
                        raise ValidationError("Choose one exact saved request key.")
                    job = paired_jobs(project, connection.pk).filter(idempotency_key=values[0]).first()
                    metadata = paired_job_metadata(job, request.user) if job else None
                    require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
                    return _response({"project_id": project.pk, "organization_id": organization_id,
                        "connection_id": connection.pk, "request_key": values[0], "job": metadata})
                values = request.GET.getlist("job_id")
                if (set(request.GET) != {"job_id"} or len(values) != 1 or not values[0].isascii()
                    or not values[0].isdecimal() or values[0].startswith("0") or len(values[0]) > 16):
                    raise ValidationError("Choose one exact paired job identifier.")
                return _response(read_paired_evidence(project=project, actor=request.user,
                    connection_id=connection.pk, job_id=int(values[0])))
            jobs = list(paired_jobs(project, connection.pk)[:21])
            metadata = [paired_job_metadata(job, request.user) for job in jobs[:20]]
            fresh = _project(request, organization_id, project_id)
            if fresh is None: raise PermissionDenied
            require_project_action(project=fresh, user=request.user, action=Action.MANAGE_PROJECT)
            for row, job in zip(metadata, jobs):
                row["source_current"] = paired_source_current(job, request.user)
            return _response({"project_id": project.pk, "organization_id": organization_id, "connection_id": connection.pk,
                "report": "query_page", "jobs": metadata, "has_more": len(jobs) > 20})
        if request.GET or request.content_type != "application/json" or len(request.body) > 4096:
            raise ValidationError("Choose a bounded explicit paired report request.")
        payload = json.loads(request.body, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        if (type(payload) is not dict or set(payload) != {"day", "idempotency_key", "grant_id", "grant_revision"}
            or type(payload["grant_id"]) is not int or payload["grant_id"] < 1
            or type(payload["grant_revision"]) is not int or payload["grant_revision"] < 0):
            raise ValidationError("Choose one source day and request key.")
        if not ratelimit.consume(request, action="search_console_sync", user=request.user):
            return _error("Search Console requests are temporarily limited.", 429)
        grant = GoogleOAuthGrant.objects.filter(project=project, organization_id=organization_id,
            pk=payload["grant_id"], credential_reference=connection.credential_reference,
            state=GoogleOAuthGrant.State.ACTIVE).first() if connection.credential_reference else None
        if grant is None: raise ValidationError("Current source authorization is unavailable.")
        job = queue_search_console_sync(project=project, actor=request.user, connection=connection, grant=grant,
            day=payload["day"], dimensions=["query", "page"], report="query_page", idempotency_key=payload["idempotency_key"],
            expected_grant_revision=payload["grant_revision"])
        return _response({"job_id": job.pk, "project_id": project.pk, "connection_id": connection.pk,
            "status": job.status, "report": "query_page", "max_requests": job.usage.reserved_units,
            "provider_completeness": "not_established", "hidden_queries": "unknown"}, 202)
    except PermissionDenied:
        return _error("Current paired source permission is unavailable.", 403)
    except UsageLimitError as error:
        return _error("Commercial source work is currently unavailable.", 429, code=error.category)
    except GoogleTokenError:
        return _error("Google synchronization is not configured.", 503)
    except (ValidationError, ValueError, TypeError, UnicodeError, RecursionError):
        return _error("Choose an intact current URL-prefix paired source, latest saved job or finalized day.", 409)
