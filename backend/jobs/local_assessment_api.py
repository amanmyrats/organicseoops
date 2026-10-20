from hashlib import sha256
from http import HTTPStatus
import re

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.views.decorators.http import require_http_methods

from tenancy.models import ProjectConfiguration
from tenancy.services import Action, require_project_action

from .findings_api import _error, _payload, _project, _response
from .local_assessment import review_local_business
from .models import LocalBusinessAssessment


def _project_access(request, organization_id, project_id, *, edit=False):
    if not request.user.is_authenticated or not request.user.is_active:
        return None, _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return None, _error("Project not found.", HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user,
                               action=Action.MANAGE_PROJECT if edit else Action.VIEW_PROJECT)
    except PermissionDenied:
        return None, _error("Local review is unavailable.", HTTPStatus.FORBIDDEN)
    return project, None


def _serialize(project, row):
    config = ProjectConfiguration.objects.filter(project=project).first()
    current = bool(config and row.configuration_revision == config.revision
        and (row.location_label in config.business_locations
             or not row.location_label and config.service_areas)
        and set(row.service_areas) <= set(config.service_areas)
        and (not row.profile_url or row.profile_url in config.profile_urls))
    return {"id": row.pk, "location_digest": row.location_digest, "revision": row.revision,
            "configuration_revision": row.configuration_revision, "source_current": current,
            "location_label": row.location_label, "business_name": row.business_name,
            "address_display": row.address_display, "phone": row.phone, "hours": row.hours,
            "services": row.services, "service_areas": row.service_areas, "profile_url": row.profile_url,
            "eligibility": row.eligibility, "review_theme": row.review_theme,
            "evidence_note": row.evidence_note, "suggested_action": row.suggested_action,
            "actor_id": row.actor_id, "reviewed_at": row.created_at.isoformat(),
            "verification_state": "manual_user_supplied_not_listing_or_provider_verified"}


def _save(request, project, *, location_digest=None):
    if not ratelimit.consume(request, action="local_review", user=request.user):
        return _error("Too many local reviews. Try again later.", HTTPStatus.TOO_MANY_REQUESTS)
    keys = {"request_key", "expected_config_revision", "location_label", "business_name",
            "address_display", "phone", "hours", "services", "service_areas", "profile_url",
            "eligibility", "review_theme", "evidence_note", "suggested_action"}
    if location_digest is not None:
        keys.add("expected_revision")
    try:
        data = _payload(request, keys)
        if location_digest is not None and sha256(str(data["location_label"]).encode()).hexdigest() != location_digest:
            raise PermissionDenied
        row = review_local_business(project=project, actor=request.user, **data)
    except PermissionDenied:
        return _error("Local review not found.", HTTPStatus.NOT_FOUND)
    except ValidationError:
        return _error("Current project business facts and reviewer evidence are required.", HTTPStatus.CONFLICT)
    return _response({"project_id": project.pk, "assessment": _serialize(project, row)},
                     HTTPStatus.OK if location_digest else HTTPStatus.CREATED)


@require_http_methods(["GET", "POST"])
def project_local_assessments(request, organization_id, project_id):
    project, error = _project_access(request, organization_id, project_id, edit=request.method == "POST")
    if error:
        return error
    if request.method == "POST":
        return _save(request, project)
    rows = list(LocalBusinessAssessment.objects.filter(project=project)
                .order_by("location_digest", "-revision").distinct("location_digest")[:51])
    return _response({"project_id": project.pk, "assessments": [_serialize(project, row) for row in rows[:50]],
                      "has_more": len(rows) > 50})


@require_http_methods(["GET", "POST"])
def project_local_assessment(request, organization_id, project_id, location_digest):
    project, error = _project_access(request, organization_id, project_id, edit=request.method == "POST")
    if error:
        return error
    if not re.fullmatch(r"[0-9a-f]{64}", location_digest):
        return _error("Local assessment not found.", HTTPStatus.NOT_FOUND)
    rows = LocalBusinessAssessment.objects.filter(project=project, location_digest=location_digest)
    if not rows.exists():
        return _error("Local assessment not found.", HTTPStatus.NOT_FOUND)
    if request.method == "POST":
        return _save(request, project, location_digest=location_digest)
    history = list(rows.order_by("-revision")[:21])
    return _response({"project_id": project.pk, "history": [_serialize(project, row) for row in history[:20]],
                      "has_more": len(history) > 20})
