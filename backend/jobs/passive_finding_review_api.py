"""Fixed private exact-Finding human commands, separate from ordinary project review."""
from contextlib import nullcontext
from http import HTTPStatus

from allauth.account import app_settings as account_settings
from allauth.core.internal import ratelimit
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables

from integrations.google_tokens import GoogleTokenError
from tenancy.models import Organization, Project
from . import passive_finding_reviews as reviews
from .findings_api import _project
from .first_audit_api import _response
from .models import Opportunity
from .passive_header_api import _current, _payload
from .usage import UsageLimitError


FIELDS = {"source_sha256", "expected_revision", "priority", "estimated_effort", "business_relevance", "reason"}


@sensitive_post_parameters()
@sensitive_variables()
def project_header_priority(request, organization_id, project_id, job_id, finding_id):
    return _priority(request, organization_id, project_id, job_id, finding_id, family="header")


@sensitive_post_parameters()
@sensitive_variables()
def project_resource_priority(request, organization_id, project_id, job_id, finding_id):
    return _priority(request, organization_id, project_id, job_id, finding_id, family="resource")


@sensitive_post_parameters()
@sensitive_variables()
def project_tls_priority(request, organization_id, project_id, job_id, finding_id):
    return _priority(request, organization_id, project_id, job_id, finding_id, family="tls")


@sensitive_post_parameters()
@sensitive_variables()
def project_redirect_priority(request, organization_id, project_id, job_id, finding_id):
    return _priority(request, organization_id, project_id, job_id, finding_id, family="redirect")


@sensitive_post_parameters()
@sensitive_variables()
def project_redirect_chain_priority(request, organization_id, project_id, job_id, finding_id):
    return _priority(request, organization_id, project_id, job_id, finding_id, family="redirect_chain")


@sensitive_post_parameters()
@sensitive_variables()
def _priority(request, organization_id, project_id, job_id, finding_id, *, family):
    if family == "header": record, read = reviews.record_header_priority, reviews.current_header_priority
    elif family == "resource": record, read = reviews.record_resource_priority, reviews.current_resource_priority
    elif family == "tls": record, read = reviews.record_tls_priority, reviews.current_tls_priority
    elif family == "redirect": record, read = reviews.record_redirect_priority, reviews.current_redirect_priority
    elif family == "redirect_chain": record, read = reviews.record_redirect_chain_priority, reviews.current_redirect_chain_priority
    else: raise ValidationError
    if request.method not in {"GET", "POST"}:
        response = _response({"message": "Use an explicit private priority GET or POST."}, HTTPStatus.METHOD_NOT_ALLOWED)
        response["Allow"] = "GET, POST"
        return response
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    if (not all(type(value) is int and 1 <= value < 2**53 for value in (organization_id, project_id, job_id, finding_id))
        or request.GET or request.method == "GET" and request.body):
        return _response({"message": "Choose one exact original job and materialized finding."}, HTTPStatus.BAD_REQUEST)
    project = _project(request, organization_id, project_id)
    if project is None: return _response({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    action = f"passive_{family}_priority_" + ("write" if request.method == "POST" else "read")
    if ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True, action=action, user=request.user) is None:
        return _response({"message": "Too many private priority commands."}, HTTPStatus.TOO_MANY_REQUESTS)
    try:
        _current(project, request.user)
        data = _payload(request, FIELDS) if request.method == "POST" else None
        with transaction.atomic() if data is not None else nullcontext():
            if data is not None:
                organization = Organization.objects.select_for_update().get(pk=organization_id)
                project = Project.objects.select_for_update().get(pk=project_id, organization=organization)
                review = record(project=project, actor=request.user, job_id=job_id, finding_id=finding_id, **data)
                latest = {field.attname: getattr(review, field.attname) for field in Opportunity._meta.concrete_fields}
            else:
                latest = reviews._latest(project, finding_id)  # Pin before any original private-source I/O.
            current = read(project=project, actor=request.user, job_id=job_id, finding_id=finding_id)
            original = current["source"]
            if data is not None and original["source_sha256"] != data["source_sha256"]: raise PermissionDenied
            response = _response({"organization_id": organization_id, "project_id": project_id, "prioritization": current})
            reviews._final(project, request.user, job_id, finding_id, reviews._reader(family), original, latest)
            _current(project, request.user)
            return response
    except (UsageLimitError, PermissionDenied, ObjectDoesNotExist):
        return _response({"message": "Current exact passive source, human review and authority are required."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, GoogleTokenError, UnicodeError, ValueError, TypeError, IntegrityError, RecursionError):
        return _response({"message": "Original source or human judgment changed. Inspect the exact finding again."}, HTTPStatus.CONFLICT)
