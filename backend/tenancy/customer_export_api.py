from http import HTTPStatus
from hashlib import sha256

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, HttpResponse
from django.views.decorators.http import require_GET, require_POST

from config.artifacts import ArtifactNotFound, ArtifactStorageError, ArtifactValidationError
from .api import _authenticated, _error, _payload, _response
from .customer_export import (complete_bounded_customer_archive, project_customer_artifact,
                              project_customer_rows)
from .models import Organization


@require_POST
def organization_customer_rows(request, organization_id):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    organization = Organization.objects.for_user(request.user).filter(pk=organization_id).first()
    if organization is None:
        return _error("Organization unavailable.", status=HTTPStatus.NOT_FOUND)
    if not ratelimit.consume(request, action="organization_export_rows", user=request.user):
        return _error("Too many export requests. Try again later.", status=HTTPStatus.TOO_MANY_REQUESTS)
    try:
        if len(request.body) > 4096:
            raise ValidationError("Choose a bounded export window.")
        body = _payload(request, allowed={"model", "after_id", "through_id"},
                        required={"model", "after_id", "through_id"})
        return _response(project_customer_rows(organization=organization, actor=request.user,
            model_label=body["model"], after_id=body["after_id"], through_id=body["through_id"]))
    except PermissionDenied:
        return _error("Customer rows unavailable.", status=HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _error("Choose a bounded current organization record window.", status=HTTPStatus.CONFLICT)
    except RuntimeError:
        return _error("Customer export unavailable until its schema is reviewed.", status=HTTPStatus.SERVICE_UNAVAILABLE)


@require_GET
def organization_customer_artifact(request, organization_id, project_id, artifact_index):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    organization = Organization.objects.for_user(request.user).filter(pk=organization_id).first()
    if organization is None:
        return _error("Organization unavailable.", status=HTTPStatus.NOT_FOUND)
    if not ratelimit.consume(request, action="organization_export_artifact", user=request.user):
        return _error("Too many export requests. Try again later.", status=HTTPStatus.TOO_MANY_REQUESTS)
    try:
        data, extension, checksum = project_customer_artifact(organization=organization, actor=request.user,
                                                               project_id=project_id, artifact_index=artifact_index)
    except PermissionDenied:
        return _error("Export unavailable.", status=HTTPStatus.FORBIDDEN)
    except (ArtifactStorageError, ArtifactValidationError):
        return _error("Private artifact unavailable.", status=HTTPStatus.SERVICE_UNAVAILABLE)
    except ValidationError:
        return _error("Selected artifact unavailable.", status=HTTPStatus.NOT_FOUND)
    response = (HttpResponse(data, content_type="application/octet-stream") if isinstance(data, bytes)
                else FileResponse(data, content_type="application/octet-stream"))
    response["Content-Disposition"] = f'attachment; filename="project-{project_id}-artifact-{artifact_index}.{extension}"'
    response["Cache-Control"] = "private, no-store"
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'"
    response["X-Content-SHA256"] = checksum
    return response


@require_POST
def organization_bounded_archive(request, organization_id):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    organization = Organization.objects.for_user(request.user).filter(pk=organization_id).first()
    if organization is None:
        return _error("Organization unavailable.", status=HTTPStatus.NOT_FOUND)
    if not ratelimit.consume(request, action="organization_export_archive", user=request.user):
        return _error("Too many archive requests. Try again later.", status=HTTPStatus.TOO_MANY_REQUESTS)
    try:
        if len(request.body) > 4096:
            raise ValidationError("Choose a bounded export request.")
        _payload(request, allowed=set(), required=set())
        data = complete_bounded_customer_archive(organization=organization, actor=request.user)
    except PermissionDenied:
        return _error("Organization archive unavailable.", status=HTTPStatus.FORBIDDEN)
    except (ArtifactNotFound, ArtifactStorageError, ArtifactValidationError, RuntimeError):
        return _error("Private archive unavailable.", status=HTTPStatus.SERVICE_UNAVAILABLE)
    except ValidationError:
        return _error("Archive exceeds local limits; export record and artifact parts separately.",
                      status=HTTPStatus.CONFLICT)
    response = HttpResponse(data, content_type="application/zip")
    response["Content-Disposition"] = 'attachment; filename="organization-customer-content.zip"'
    response["Cache-Control"] = "private, no-store"
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'"
    response["X-Content-SHA256"] = sha256(data).hexdigest()
    return response
