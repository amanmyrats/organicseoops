"""Fixed private saved-Date candidate inspection; reads never collect or process with AI."""
from http import HTTPStatus

from allauth.account import app_settings as account_settings
from allauth.core.internal import ratelimit
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.views.decorators.debug import sensitive_variables

from integrations.google_tokens import GoogleTokenError
from . import competitor_collection as lifecycle, competitor_page_dates_collection as collection
from .competitor_api import _current, _metadata, _project, _response, _status
from .competitor_date_candidate_source import current_date_candidates
from .models import JobCancellation, JobRun, JobStatus
from .usage import UsageLimitError, require_billable_access


@sensitive_variables()
def project_competitor_date_candidates(request, organization_id, project_id, job_id):
    if request.method != "GET":
        response = _response({"message": "Inspect one saved Date job."}, HTTPStatus.METHOD_NOT_ALLOWED)
        response["Allow"] = "GET"
        return response
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    if request.body or request.GET or not all(type(key) is int and 1 <= key < 2**53
        for key in (organization_id, project_id, job_id)):
        return _response({"message": "Choose an exact saved Date job."}, HTTPStatus.BAD_REQUEST)
    project = _project(request, organization_id, project_id)
    if project is None: return _response({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    if ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True,
        action="competitor_page_dates_read", user=request.user) is None:
        return _response({"message": "Too many saved Date reads."}, HTTPStatus.TOO_MANY_REQUESTS)
    try:
        _current(project, request.user)
        def current_job():
            return JobRun.objects.select_related("project", "actor").get(pk=job_id, project_id=project_id,
                organization_id=organization_id, handler=collection.HANDLER, status=JobStatus.SUCCEEDED)
        job = current_job()
        caller = lifecycle._read_source(job, project, request.user)
        original = _metadata(job_id)
        packet = current_date_candidates(project=project, actor=request.user, job_id=job_id)
        response = _response({"organization_id": organization_id, "project_id": project_id,
            "job": _status(job), "candidates": packet})
        if _metadata(job_id) != original: raise PermissionDenied
        if lifecycle._read_source(current_job(), project, request.user) != caller: raise PermissionDenied
        if _metadata(job_id) != original: raise PermissionDenied
        if lifecycle._read_source(current_job(), project, request.user) != caller: raise PermissionDenied
        if lifecycle._read_metadata(job_id) != original["source"] or JobCancellation.objects.filter(job_id=job_id).exists():
            raise PermissionDenied
        _current(project, request.user)
        require_billable_access(organization=project.organization)
        return response
    except (UsageLimitError, PermissionDenied, ObjectDoesNotExist):
        return _response({"message": "Current exact Date source and authority are required."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, GoogleTokenError, UnicodeError, ValueError, TypeError, RecursionError):
        return _response({"message": "Original private Date candidates unavailable."}, HTTPStatus.CONFLICT)
