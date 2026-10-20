from http import HTTPStatus

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied
from django.views.decorators.http import require_GET

from config.artifacts import ArtifactStorageError, ArtifactValidationError

from .api import _authenticated, _error, _response
from .customer_inventory import inventory_customer_data
from .models import Organization


@require_GET
def organization_export_inventory(request, organization_id):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    organization = Organization.objects.for_user(request.user).filter(pk=organization_id).first()
    if organization is None:
        return _error("Organization unavailable.", status=HTTPStatus.NOT_FOUND)
    if not ratelimit.consume(request, action="organization_export_inventory", user=request.user):
        return _error("Too many inventory requests. Try again later.", status=HTTPStatus.TOO_MANY_REQUESTS)
    try:
        return _response(inventory_customer_data(organization=organization, actor=request.user))
    except PermissionDenied:
        return _error("Export inventory unavailable.", status=HTTPStatus.FORBIDDEN)
    except (RuntimeError, ArtifactStorageError, ArtifactValidationError):
        return _error("Export inventory unavailable.", status=HTTPStatus.SERVICE_UNAVAILABLE)
