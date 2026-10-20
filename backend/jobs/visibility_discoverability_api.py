from http import HTTPStatus

from django.core.exceptions import PermissionDenied, ValidationError
from django.views.decorators.http import require_GET

from .ai_text_api import _project
from .research_api import _result
from .visibility_discoverability import discoverability_evidence


@require_GET
def project_visibility_discoverability(request, organization_id, project_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _result({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _result({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        if set(request.GET) - {"diagnostics"}:
            raise ValidationError("Unsupported source filter.")
        source = int(request.GET["diagnostics"]) if "diagnostics" in request.GET else None
        return _result(discoverability_evidence(project=project, actor=request.user, diagnostics_id=source))
    except PermissionDenied:
        return _result({"message": "Project source unavailable."}, HTTPStatus.NOT_FOUND)
    except (ValueError, TypeError, ValidationError):
        return _result({"message": "Choose one stored project source."}, HTTPStatus.BAD_REQUEST)
