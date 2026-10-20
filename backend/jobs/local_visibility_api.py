"""Private manual observation/correction history, not a Google search endpoint."""
from http import HTTPStatus
import json
import re

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Exists, OuterRef
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods

from integrations.google_tokens import GoogleTokenError, _reject_constant, _unique_object
from tenancy.models import ProjectConfiguration
from .findings_api import _error, _response
from .local_assessment_api import _project_access
from .local_feedback_api import _context as manual_source_context
from .local_visibility import METHOD, SOURCE, record_local_visibility, visibility_source_current
from .models import LocalBusinessAssessment, LocalVisibilityObservation


def _serialize(row, *, latest):
    return {"id": row.pk, "project_id": row.project_id, "observation_id": str(row.observation_id),
        "revision": row.revision, "intake": row.intake, "reason": row.reason, "actor_id": row.actor_id,
        "assessment_id": row.assessment_id, "verification_id": row.verification_id,
        "verified_at": row.verified_at.isoformat(), "created_at": row.created_at.isoformat(),
        "source_current": visibility_source_current(row), "is_latest": latest,
        "basis": "customer_reported_not_provider_verified", "coverage": "partial_inspected_organic_set_only",
        "rank_scope": "human_ordinal_not_universal_or_local_pack_rank"}


def _context(project, actor):
    context = manual_source_context(project, actor)
    context.pop("policy_version")
    context.update(method_version=METHOD, source_kind=SOURCE, platform="google_search", surface="organic_links",
        automated_collection="unavailable", local_pack_maps="unavailable", other_platforms="unavailable")
    rows = {row.pk: row for row in LocalBusinessAssessment.objects.filter(project=project,
        pk__in=[row["id"] for row in context["assessments"]])}
    for row in context["assessments"]:
        source = rows[row["id"]]
        row["locations"] = list(dict.fromkeys(([source.location_label] if source.location_label else []) + source.service_areas))
    config = ProjectConfiguration.objects.filter(project=project).first()
    context["requested_languages"] = config.target_languages if config and context["can_review"] else []
    return context


@sensitive_post_parameters()
@sensitive_variables()
@require_http_methods(["GET", "POST"])
def project_local_visibility(request, organization_id, project_id, observation_id=None):
    project, error = _project_access(request, organization_id, project_id, edit=request.method == "POST")
    if error:
        return error
    if request.method == "POST":
        if not ratelimit.consume(request, action="local_visibility_review", user=request.user):
            return _error("Too many observation decisions. Try again later.", HTTPStatus.TOO_MANY_REQUESTS)
        fields = {"request_key", "intake", "reason"} | ({"expected_revision"} if observation_id else set())
        try:
            if request.content_type != "application/json" or len(request.body) > 20 * 1024:
                raise ValidationError("Choose bounded manual JSON observation fields.")
            data = json.loads(request.body, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            if type(data) is not dict or set(data) != fields:
                raise ValidationError("Choose exact manual observation fields.")
            row = record_local_visibility(project=project, actor=request.user, observation_id=observation_id, **data)
        except PermissionDenied:
            return _error("Current actor, business, location/language and verified website authority is required.", HTTPStatus.FORBIDDEN)
        except (ValidationError, GoogleTokenError, UnicodeError, ValueError, TypeError, RecursionError):
            return _error("Observation changed or fields are unavailable. Reload exact current context before correction.", HTTPStatus.CONFLICT)
        return _response({"organization_id": project.organization_id, "project_id": project.pk,
                          "observation": _serialize(row, latest=True)}, HTTPStatus.OK if observation_id else HTTPStatus.CREATED)
    if set(request.GET) - {"request_key"} or any(len(values) != 1 for _, values in request.GET.lists()):
        return _error("Choose one bounded request-key lookup.", HTTPStatus.BAD_REQUEST)
    key = request.GET.get("request_key")
    if key is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", key):
        return _error("Choose a bounded request key.", HTTPStatus.BAD_REQUEST)
    rows = LocalVisibilityObservation.objects.filter(project=project).select_related("project__organization", "actor", "assessment", "verification")
    if observation_id is not None:
        rows = rows.filter(observation_id=observation_id)
        if not rows.exists():
            return _error("Local observation not found.", HTTPStatus.NOT_FOUND)
    newer = LocalVisibilityObservation.objects.filter(project=project, observation_id=OuterRef("observation_id"), revision__gt=OuterRef("revision"))
    rows = rows.annotate(newer=Exists(newer))
    if key is not None:
        rows = rows.filter(request_key=key)
    elif observation_id is None:
        rows = rows.filter(newer=False)
    limit = 20 if observation_id else 50
    rows = list(rows.order_by("-pk")[:limit + 1])
    return _response({**_context(project, request.user),
        "observations": [_serialize(row, latest=not row.newer) for row in rows[:limit]], "has_more": len(rows) > limit,
        "lookup": "found" if key and rows else "not_found" if key else None})
