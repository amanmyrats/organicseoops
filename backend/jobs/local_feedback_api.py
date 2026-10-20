"""Private retained feedback history and manual review commands; no remote operation."""
from datetime import datetime
from http import HTTPStatus
import json
import re

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Exists, OuterRef
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods

from integrations.google_tokens import GoogleTokenError, _reject_constant, _unique_object
from integrations.oauth import _verified
from tenancy.models import ProjectConfiguration, ProjectOriginVerification
from tenancy.services import Action, require_project_action
from .findings_api import _error, _response
from .local_assessment_api import _project_access, _serialize as assessment_payload
from .local_feedback import POLICY_VERSION, feedback_source_current, record_local_feedback
from .models import LocalBusinessAssessment, LocalFeedbackReview


def _serialize(row, *, latest):
    current = feedback_source_current(row)
    return {"id": row.pk, "feedback_id": str(row.feedback_id), "project_id": row.project_id,
        "revision": row.revision, "state": row.state, "intake": row.intake, "reason": row.reason,
        "actor_id": row.actor_id, "source_actor_id": row.source_actor_id, "assessment_id": row.assessment_id,
        "verification_id": row.verification_id, "verified_at": row.verified_at.isoformat(), "origin": row.origin,
        "reviewed_revision_id": row.reviewed_revision_id, "approved_by_id": row.approved_by_id,
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "executed_at": row.executed_at.isoformat() if row.executed_at else None,
        "execution_note": row.execution_note, "created_at": row.created_at.isoformat(),
        "source_current": current, "is_latest": latest,
        "effective_approval": latest and current and row.state in {"approved", "reported"},
        "coverage": "selected_customer_supplied_feedback_not_complete_history",
        "execution_state": "customer_reported_not_verified" if row.executed_at else "not_reported"}


def _context(project, actor):
    can_review = False
    try:
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        can_review = _verified(actor)
    except PermissionDenied:
        pass
    config = ProjectConfiguration.objects.filter(project=project).first()
    origins = {project.canonical_origin, *project.domain_aliases.values_list("origin", flat=True)}
    verified = list(ProjectOriginVerification.objects.filter(project=project, organization_id=project.organization_id,
        state="verified", origin__in=origins, verified_at__lte=timezone.now(), revoked_at__isnull=True)
        .order_by("pk").values_list("origin", flat=True)[:21]) if can_review else []
    newer = LocalBusinessAssessment.objects.filter(project=project, location_digest=OuterRef("location_digest"),
                                                   revision__gt=OuterRef("revision"))
    assessments = list(LocalBusinessAssessment.objects.filter(project=project, configuration_revision=config.revision)
        .annotate(newer=Exists(newer)).filter(newer=False).order_by("-pk")[:21]) if can_review and config else []
    candidates = [row for row in assessments[:20] if assessment_payload(project, row)["source_current"]]
    return {"organization_id": project.organization_id, "project_id": project.pk, "can_review": can_review,
        "policy_version": POLICY_VERSION, "configuration_revision": config.revision if config else None,
        "verified_origins": verified[:20], "sources_has_more": len(verified) > 20 or len(assessments) > 20,
        "assessments": [{"id": row.pk, "business_name": row.business_name, "location_label": row.location_label,
                         "eligibility": row.eligibility} for row in candidates],
        "source_basis": "current_manual_candidates_not_source_permission",
        "direct_writes": "unavailable", "other_platforms": "unavailable"}


@sensitive_post_parameters()
@sensitive_variables()
@require_http_methods(["GET", "POST"])
def project_local_feedback(request, organization_id, project_id, feedback_id=None):
    project, error = _project_access(request, organization_id, project_id, edit=request.method == "POST")
    if error:
        return error
    if request.method == "POST":
        if not ratelimit.consume(request, action="local_feedback_review", user=request.user):
            return _error("Too many feedback decisions. Try again later.", HTTPStatus.TOO_MANY_REQUESTS)
        fields = {"request_key", "intake", "state", "reason", "executed_at", "execution_note"}
        if feedback_id is not None:
            fields.add("expected_revision")
        try:
            if request.content_type != "application/json" or len(request.body) > 36 * 1024:
                raise ValidationError("Choose bounded JSON feedback fields.")
            data = json.loads(request.body, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            if type(data) is not dict or set(data) != fields:
                raise ValidationError("Choose exact feedback fields.")
            if data["executed_at"] is not None:
                if type(data["executed_at"]) is not str or len(data["executed_at"]) > 64:
                    raise ValidationError("Report an aware actual manual execution date.")
                data["executed_at"] = datetime.fromisoformat(data["executed_at"])
            row = record_local_feedback(project=project, actor=request.user, feedback_id=feedback_id, **data)
        except PermissionDenied:
            return _error("Current business, source and reviewer authority is required.", HTTPStatus.FORBIDDEN)
        except (ValidationError, GoogleTokenError, UnicodeError, ValueError, TypeError, RecursionError):
            return _error("Feedback changed or fields are unavailable; refresh and review exact source/text.", HTTPStatus.CONFLICT)
        return _response({"organization_id": project.organization_id, "project_id": project.pk,
                          "review": _serialize(row, latest=True)}, HTTPStatus.OK if feedback_id else HTTPStatus.CREATED)
    if set(request.GET) - {"request_key"} or any(len(values) != 1 for _, values in request.GET.lists()):
        return _error("Choose one bounded request-key lookup.", HTTPStatus.BAD_REQUEST)
    key = request.GET.get("request_key")
    if key is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", key):
        return _error("Choose a bounded request key.", HTTPStatus.BAD_REQUEST)
    rows = LocalFeedbackReview.objects.filter(project=project).select_related(
        "project__organization", "actor", "source_actor", "assessment", "verification", "reviewed_revision__actor", "approved_by")
    if feedback_id is not None:
        rows = rows.filter(feedback_id=feedback_id)
        if not rows.exists():
            return _error("Feedback review not found.", HTTPStatus.NOT_FOUND)
    newer = LocalFeedbackReview.objects.filter(project=project, feedback_id=OuterRef("feedback_id"), revision__gt=OuterRef("revision"))
    rows = rows.annotate(newer=Exists(newer))
    if key is not None:
        rows = rows.filter(request_key=key)
    elif feedback_id is None:
        rows = rows.filter(newer=False)
    limit = 20 if feedback_id else 50
    rows = list(rows.order_by("-pk")[:limit + 1])
    return _response({**_context(project, request.user),
        "reviews": [_serialize(row, latest=not row.newer) for row in rows[:limit]], "has_more": len(rows) > limit,
        "lookup": "found" if key and rows else "not_found" if key else None})
