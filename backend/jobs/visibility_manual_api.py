"""Private human reports/evaluation; no consumer session or provider request endpoint."""
from http import HTTPStatus
import json
import re

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Exists, OuterRef
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods

from integrations.google_tokens import GoogleTokenError, _reject_constant, _unique_object
from integrations.oauth import _verified
from tenancy.models import ProjectConfiguration, ProjectOriginVerification
from tenancy.services import Action, project_has_origin, require_project_action
from .findings_api import _error, _response
from .intent_api import _serialize as serialize_intent
from .local_assessment_api import _project_access
from .models import AIVisibilityManualObservation, IntentClusterReview
from .visibility_entities import candidates
from .visibility_manual import METHOD, SOURCE, SURFACE, comparable_context, entity_context, manual_rates, manual_source_current, record_manual_answer


def _serialize(row, *, latest):
    return {"id": row.pk, "project_id": row.project_id, "observation_id": str(row.observation_id), "revision": row.revision,
        "intake": row.intake, "context": row.context, "matches": row.matches, "evaluated": row.evaluated,
        "verification_id": row.verification_id, "verified_at": row.verified_at.isoformat(), "actor_id": row.actor_id,
        "reason": row.reason, "created_at": row.created_at.isoformat(), "source_current": manual_source_current(row),
        "is_latest": latest, "basis": "human_report_not_consumer_or_provider_verified", "comparison_context": comparable_context(row),
        "preview": candidates(row.intake["answer"], entity_context(row.context)), "external_cost": None, "referrals": None}


def _context(project, actor):
    can_review = False
    try:
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        can_review = _verified(actor)
    except PermissionDenied:
        pass
    config = ProjectConfiguration.objects.filter(project=project).first()
    origins = list(ProjectOriginVerification.objects.filter(project=project, organization_id=project.organization_id,
        state="verified", revoked_at__isnull=True, verified_at__isnull=False).order_by("pk")[:21])
    mappings = list(IntentClusterReview.objects.filter(project=project).order_by("cluster_id", "-revision").distinct("cluster_id")[:51])
    return {"organization_id": project.organization_id, "project_id": project.pk, "method_version": METHOD,
        "source_kind": SOURCE, "surface": SURFACE, "can_review": can_review,
        "configuration_revision": config.revision if config else None, "market": config.target_country if config else "",
        "languages": config.target_languages if config else [], "brand_aliases": config.brand_aliases if config else [],
        "verified_origins": [row.origin for row in origins[:20] if can_review and row.origin.startswith("https://")
            and project_has_origin(project, row.origin)],
        "intent_reviews": [serialize_intent(project, row) for row in mappings[:50]] if can_review else [],
        "sources_has_more": len(origins) > 20 or len(mappings) > 50,
        "rights": "independent_customer_permission_D098_not_platform_license", "consumer_verification": "unavailable"}


@sensitive_post_parameters()
@sensitive_variables()
@require_http_methods(["GET", "POST"])
def project_manual_visibility(request, organization_id, project_id, observation_id=None, rates=False):
    project, error = _project_access(request, organization_id, project_id, edit=request.method == "POST")
    if error:
        return error
    if rates:
        if request.method != "GET" or request.GET:
            return _error("Choose read-only separate manual denominators.", HTTPStatus.BAD_REQUEST)
        return _response({"organization_id": project.organization_id, **manual_rates(project=project, actor=request.user)})
    if request.method == "POST":
        if not ratelimit.consume(request, action="visibility_manual_review", user=request.user):
            return _error("Too many manual answer decisions.", HTTPStatus.TOO_MANY_REQUESTS)
        fields = {"request_key", "intake", "reason", "evaluated", "matches"} | ({"expected_revision"} if observation_id else set())
        try:
            # Intake24KiB + evaluation32KiB + envelope; match default JSON escaping used in durable records.
            if request.content_type != "application/json" or len(request.body) > 60 * 1024:
                raise ValidationError("Choose bounded private manual-answer JSON.")
            data = json.loads(request.body, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            if request.GET or type(data) is not dict or set(data) != fields or type(data["matches"]) is not list:
                raise ValidationError("Choose exact manual report/evaluation fields.")
            row = record_manual_answer(project=project, actor=request.user, observation_id=observation_id, **data)
        except PermissionDenied:
            return _error("Current actor, intent/configuration and exact verified website authority required.", HTTPStatus.FORBIDDEN)
        except (ValidationError, GoogleTokenError, UnicodeError, ValueError, TypeError, RecursionError):
            return _error("Manual evidence/revision or source changed. Reload before another decision.", HTTPStatus.CONFLICT)
        return _response({"organization_id": project.organization_id, "project_id": project.pk,
            "observation": _serialize(row, latest=True)}, HTTPStatus.OK if observation_id else HTTPStatus.CREATED)
    if set(request.GET) - {"request_key"} or any(len(values) != 1 for _, values in request.GET.lists()):
        return _error("Choose one exact bounded request-key lookup.", HTTPStatus.BAD_REQUEST)
    key = request.GET.get("request_key")
    if key is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", key):
        return _error("Choose a bounded request key.", HTTPStatus.BAD_REQUEST)
    rows = AIVisibilityManualObservation.objects.filter(project=project).select_related("project__organization", "actor", "intent_review", "verification")
    if observation_id:
        rows = rows.filter(observation_id=observation_id)
        if not rows.exists():
            return _error("Manual report not found.", HTTPStatus.NOT_FOUND)
    newer = AIVisibilityManualObservation.objects.filter(project=project, observation_id=OuterRef("observation_id"), revision__gt=OuterRef("revision"))
    rows = rows.annotate(newer=Exists(newer))
    if key is not None:
        rows = rows.filter(request_key=key)
    elif observation_id is None:
        rows = rows.filter(newer=False)
    limit = 20 if observation_id else 50
    selected = list(rows.order_by("-pk")[:limit + 1])
    return _response({**_context(project, request.user), "observations": [_serialize(row, latest=not row.newer) for row in selected[:limit]],
        "has_more": len(selected) > limit, "lookup": "found" if key and selected else "not_found" if key else None})
