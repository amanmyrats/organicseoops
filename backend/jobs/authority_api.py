"""Private bounded current research candidates and immutable human prospect commands."""
from datetime import datetime
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
from tenancy.models import OrganizationMembership
from tenancy.services import Action, require_project_action
from .action_review import _assignee
from .authority import POLICY, prospect_source_current, record_authority_prospect, research_authority_source
from .findings_api import _error, _response
from .local_assessment_api import _project_access
from .models import AuthorityProspectReview, JobRun, JobStatus
from .research import METHOD as RESEARCH_METHOD


def _serialize(row, *, latest):
    current = prospect_source_current(row)
    return {"id": row.pk, "prospect_id": str(row.prospect_id), "project_id": row.project_id,
        "revision": row.revision, "state": row.state, "intake": row.intake, "source_evidence": row.source_evidence,
        "assignee_id": row.assignee_id, "actor_id": row.actor_id, "source_actor_id": row.source_actor_id,
        "reason": row.reason, "reviewed_revision_id": row.reviewed_revision_id, "approved_by_id": row.approved_by_id,
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "executed_at": row.executed_at.isoformat() if row.executed_at else None,
        "execution_note": row.execution_note, "created_at": row.created_at.isoformat(),
        "source_current": current, "is_latest": latest,
        "effective_approval": latest and current and row.state in {"approved", "reported"},
        "scope": "historical_human_prospect_not_link_proof_or_current_use_permission",
        "execution_state": "customer_reported_not_verified" if row.executed_at else "not_reported"}


def _context(project, actor):
    can_review = False
    try:
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        can_review = _verified(actor)
    except PermissionDenied:
        pass
    sources, assignees, more = [], [], False
    if can_review:
        jobs = list(JobRun.objects.filter(project=project, handler="research_topic", method_version=RESEARCH_METHOD,
            status__in=[JobStatus.SUCCEEDED, JobStatus.PARTIALLY_SUCCEEDED]).order_by("-pk")[:21])
        more = len(jobs) > 20
        for job in jobs[:20]:
            # Bound artifact readbacks to the genuine selected indices of twenty recent jobs.
            for index in range(5):
                try:
                    evidence = research_authority_source(project=project, actor=actor, research_job_id=job.pk, source_index=index)
                except (PermissionDenied, ValidationError):
                    continue
                sources.append(evidence)
                if len(sources) == 21: break
            if len(sources) == 21: break
        more |= len(sources) > 20
        members = list(OrganizationMembership.objects.filter(organization=project.organization,
            role__in=["owner", "admin", "member"], user__is_active=True).order_by("user_id")[:21])
        more |= len(members) > 20
        for member in members[:20]:
            try:
                _assignee(project, member.user_id)
                assignees.append({"id": member.user_id})
            except PermissionDenied:
                pass
    return {"organization_id": project.organization_id, "project_id": project.pk, "policy": POLICY,
        "can_review": can_review, "sources": sources[:20], "assignees": assignees, "sources_has_more": more,
        "source_basis": "current_bounded_research_text_not_link_proof_or_permission",
        "sending": "unavailable", "link_recovery": "unavailable_requires_supported_link_evidence"}


@sensitive_post_parameters()
@sensitive_variables()
@require_http_methods(["GET", "POST"])
def project_authority_prospects(request, organization_id, project_id, prospect_id=None):
    project, error = _project_access(request, organization_id, project_id, edit=request.method == "POST")
    if error:
        return error
    if request.method == "POST":
        if not ratelimit.consume(request, action="authority_prospect_review", user=request.user):
            return _error("Too many prospect decisions. Try again later.", HTTPStatus.TOO_MANY_REQUESTS)
        fields = {"request_key", "intake", "assignee_id", "state", "reason", "executed_at", "execution_note"}
        if prospect_id is not None:
            fields.add("expected_revision")
        try:
            if request.content_type != "application/json" or len(request.body) > 28 * 1024:
                raise ValidationError("Choose bounded JSON prospect fields.")
            data = json.loads(request.body, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            if type(data) is not dict or set(data) != fields:
                raise ValidationError("Choose exact human prospect fields.")
            if data["executed_at"] is not None:
                if type(data["executed_at"]) is not str or len(data["executed_at"]) > 64:
                    raise ValidationError("Report an aware actual manual execution date.")
                data["executed_at"] = datetime.fromisoformat(data["executed_at"])
            row = record_authority_prospect(project=project, actor=request.user, prospect_id=prospect_id, **data)
        except PermissionDenied:
            return _error("Current source, reviewer and assignee authority is required.", HTTPStatus.FORBIDDEN)
        except (ValidationError, GoogleTokenError, UnicodeError, ValueError, TypeError, RecursionError):
            return _error("Prospect changed or fields are unavailable; refresh exact source and history.", HTTPStatus.CONFLICT)
        return _response({"organization_id": project.organization_id, "project_id": project.pk,
            "review": _serialize(row, latest=True)}, HTTPStatus.OK if prospect_id else HTTPStatus.CREATED)
    if set(request.GET) - {"request_key"} or any(len(values) != 1 for _, values in request.GET.lists()):
        return _error("Choose one bounded request-key lookup.", HTTPStatus.BAD_REQUEST)
    key = request.GET.get("request_key")
    if key is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", key):
        return _error("Choose a bounded request key.", HTTPStatus.BAD_REQUEST)
    rows = AuthorityProspectReview.objects.filter(project=project).select_related(
        "project__organization", "research_job", "actor", "source_actor", "assignee", "reviewed_revision__actor", "approved_by")
    if prospect_id is not None:
        rows = rows.filter(prospect_id=prospect_id)
        if not rows.exists():
            return _error("Prospect not found.", HTTPStatus.NOT_FOUND)
    newer = AuthorityProspectReview.objects.filter(project=project, prospect_id=OuterRef("prospect_id"), revision__gt=OuterRef("revision"))
    rows = rows.annotate(newer=Exists(newer))
    if key is not None:
        rows = rows.filter(request_key=key)
    elif prospect_id is None:
        rows = rows.filter(newer=False)
    limit = 20 if prospect_id else 50
    rows = list(rows.order_by("-pk")[:limit + 1])
    return _response({**_context(project, request.user), "reviews": [_serialize(row, latest=not row.newer) for row in rows[:limit]],
        "has_more": len(rows) > limit, "lookup": "found" if key and rows else "not_found" if key else None})
