from http import HTTPStatus

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.views.decorators.http import require_POST

from config.artifacts import ArtifactStorageError

from .api import _authenticated, _error, _payload
from .models import Organization
from .report_bundle import selected_report_bundle


@require_POST
def organization_selected_report_bundle(request, organization_id):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    organization = Organization.objects.for_user(request.user).filter(pk=organization_id).first()
    if organization is None:
        return _error("Organization unavailable.", status=HTTPStatus.NOT_FOUND)
    if not ratelimit.consume(request, action="organization_report_bundle", user=request.user):
        return _error("Too many export requests. Try again later.", status=HTTPStatus.TOO_MANY_REQUESTS)
    try:
        if len(request.body) > 4096:
            raise ValidationError("Choose bounded reports.")
        payload = _payload(request, allowed={"report_ids"}, required={"report_ids"})
        data = selected_report_bundle(organization=organization, actor=request.user,
                                      report_ids=payload["report_ids"])
    except PermissionDenied:
        return _error("Selected reports unavailable.", status=HTTPStatus.NOT_FOUND)
    except ValidationError:
        return _error("Choose bounded retained reports.", status=HTTPStatus.CONFLICT)
    except ArtifactStorageError:
        return _error("Private report archive unavailable.", status=HTTPStatus.SERVICE_UNAVAILABLE)
    response = HttpResponse(data, content_type="application/zip")
    response["Content-Disposition"] = 'attachment; filename="selected-project-reports.zip"'
    response["Cache-Control"] = "private, no-store"
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'"
    return response
