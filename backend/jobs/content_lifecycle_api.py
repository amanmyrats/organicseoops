"""Private human content-quality decisions; no fetch, automatic action, publishing or deletion."""
from datetime import datetime
from http import HTTPStatus
import json
import re

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.db.models import Exists, OuterRef
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods

from integrations.google_tokens import GoogleTokenError, _reject_constant, _unique_object
from integrations.oauth import _verified
from tenancy.models import OrganizationMembership
from tenancy.services import Action, require_project_action
from .action_review import _assignee
from .content_lifecycle import POLICY, _current_authority, compare_content_lifecycle_sources, lifecycle_source_current, read_content_lifecycle_source, record_content_lifecycle, require_current_lifecycle_delivery
from .findings_api import _error, _response
from .local_assessment_api import _project_access
from .models import ContentLifecycleReview, ContentRevision

KEY = r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}"


@sensitive_variables()
@require_http_methods(["GET"])
def project_content_comparison(request, organization_id, project_id):
    project, error = _project_access(request, organization_id, project_id, edit=True)
    if error:
        return error
    fields = {"content_revision_id", "other_organization_id", "other_project_id", "other_content_revision_id"}
    if set(request.GET) != fields or any(len(values) != 1 for _, values in request.GET.lists()):
        return _error("Choose two exact independently authorized saved content selections.", HTTPStatus.BAD_REQUEST)
    data = {}
    for field in fields:
        value = request.GET[field]
        if not re.fullmatch(r"[1-9][0-9]{0,15}", value) or int(value) >= 2**53:
            return _error("Choose exact positive saved selection identifiers.", HTTPStatus.BAD_REQUEST)
        data[field] = int(value)
    other, error = _project_access(request, data["other_organization_id"], data["other_project_id"], edit=True)
    if error:
        return error
    try:
        result = compare_content_lifecycle_sources(project=project, other_project=other, actor=request.user,
            revision_id=data["content_revision_id"], other_revision_id=data["other_content_revision_id"])
    except PermissionDenied:
        return _error("Current authority to each project, content and original source is required.", HTTPStatus.FORBIDDEN)
    except (ValidationError, UnicodeError, ValueError, TypeError):
        return _error("An exact current saved text/source changed; refresh both selections.", HTTPStatus.CONFLICT)
    return _response({"organization_id": organization_id, "project_id": project_id, "comparison": result})


def _serialize(row):
    current = lifecycle_source_current(row)
    latest = not ContentLifecycleReview.objects.filter(project=row.project, review_id=row.review_id, revision__gt=row.revision).exists()
    return {"id": row.pk, "review_id": str(row.review_id), "project_id": row.project_id, "revision": row.revision,
        "content_revision_id": row.content_revision_id, "state": row.state, "intake": row.intake, "source_evidence": row.source_evidence,
        "assignee_id": row.assignee_id, "actor_id": row.actor_id, "source_actor_id": row.source_actor_id,
        "reason": row.reason, "reviewed_revision_id": row.reviewed_revision_id, "approved_by_id": row.approved_by_id,
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "executed_at": row.executed_at.isoformat() if row.executed_at else None,
        "execution_note": row.execution_note, "created_at": row.created_at.isoformat(),
        "source_current": current, "is_latest": latest,
        "effective_approval": current and latest and row.state in {"approved", "reported"},
        "scope": "historical_human_content_judgment_not_verified_live_quality_or_site_approval",
        "execution_state": "manual_handoff_not_site_implementation_or_outcome" if row.executed_at else "not_reported"}


def _context(project, actor):
    can_review = False
    try:
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        can_review = _verified(actor)
    except PermissionDenied:
        pass
    sources, assignees, more = [], [], False
    if can_review:
        newer = ContentRevision.objects.filter(project=project, item_id=OuterRef("item_id"), revision__gt=OuterRef("revision"))
        rows = list(ContentRevision.objects.filter(project=project).annotate(newer=Exists(newer)).filter(newer=False).order_by("-pk")[:21])
        more = len(rows) > 20
        for row in rows[:20]:
            try:
                sources.append(read_content_lifecycle_source(project=project, actor=actor, revision_id=row.pk))
            except (PermissionDenied, ValidationError):
                continue
        members = list(OrganizationMembership.objects.filter(organization=project.organization,
            role__in=["owner", "admin", "member"], user__is_active=True).order_by("user_id")[:21])
        more |= len(members) > 20
        for member in members[:20]:
            try:
                _assignee(project, member.user_id)
                assignees.append({"id": member.user_id})
            except PermissionDenied:
                continue
        # Later private reads cannot authorize earlier selections after scope/role/latest loss.
        for source in sources:
            row = ContentRevision.objects.filter(project=project, pk=source["content"]["revision_id"]).select_related(
                "project__organization", "actor", "item__actor", "brief__actor", "brief__research_job__actor",
                "brief__action_review__actor", "reviewed_revision__actor", "approved_by").first()
            if row is None:
                raise PermissionDenied
            _current_authority(row, actor)
        for assignee in assignees:
            _assignee(project, assignee["id"])
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        if not _verified(actor):
            raise PermissionDenied
    return {"organization_id": project.organization_id, "project_id": project.pk, "policy": POLICY,
        "can_review": can_review, "sources": sources, "assignees": assignees, "sources_has_more": more,
        "source_basis": "actual_saved_native_text_and_dated_sources_not_verified_live_page_or_service_facts",
        "site_action": "separate_existing_page_action_approval_implementation_and_outcome_required"}


@sensitive_post_parameters()
@sensitive_variables()
@require_http_methods(["GET", "POST"])
def project_content_lifecycle(request, organization_id, project_id, review_id=None):
    project, error = _project_access(request, organization_id, project_id, edit=request.method == "POST")
    if error:
        return error
    if request.method == "POST":
        if request.GET:
            return _error("Content decisions use exact body fields only.", HTTPStatus.BAD_REQUEST)
        if not ratelimit.consume(request, action="content_lifecycle_review", user=request.user):
            return _error("Too many content-quality decisions. Try again later.", HTTPStatus.TOO_MANY_REQUESTS)
        fields = {"request_key", "intake", "assignee_id", "state", "reason", "executed_at", "execution_note"}
        if review_id is not None:
            fields.add("expected_revision")
        try:
            if request.content_type != "application/json" or len(request.body) > 24 * 1024:
                raise ValidationError("Choose bounded exact JSON human review fields.")
            data = json.loads(request.body, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            if type(data) is not dict or set(data) != fields:
                raise ValidationError("Choose exact human review command fields.")
            if data["executed_at"] is not None:
                if type(data["executed_at"]) is not str or len(data["executed_at"]) > 64:
                    raise ValidationError("Record an actual aware manual handoff date.")
                data["executed_at"] = datetime.fromisoformat(data["executed_at"])
            row = record_content_lifecycle(project=project, actor=request.user, review_id=review_id, **data)
            result = _serialize(row)
            require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
            if not _verified(request.user):
                raise PermissionDenied
        except PermissionDenied:
            return _error("Current content/source/reviewer/assignee authority is required.", HTTPStatus.FORBIDDEN)
        except (ValidationError, IntegrityError, GoogleTokenError, UnicodeError, ValueError, TypeError, RecursionError):
            return _error("Content review or exact source changed; refresh selections and history.", HTTPStatus.CONFLICT)
        return _response({"organization_id": project.organization_id, "project_id": project.pk, "review": result},
                         HTTPStatus.OK if review_id else HTTPStatus.CREATED)
    if set(request.GET) - {"request_key"} or any(len(values) != 1 for _, values in request.GET.lists()):
        return _error("Choose one exact request-key lookup.", HTTPStatus.BAD_REQUEST)
    key = request.GET.get("request_key")
    if key is not None and not re.fullmatch(KEY, key):
        return _error("Choose a bounded request key.", HTTPStatus.BAD_REQUEST)
    rows = ContentLifecycleReview.objects.filter(project=project).select_related(
        "project__organization", "content_revision", "actor", "source_actor", "assignee", "reviewed_revision__actor", "approved_by")
    if review_id is not None:
        rows = rows.filter(review_id=review_id)
        if not rows.exists():
            return _error("Content review not found.", HTTPStatus.NOT_FOUND)
    if key is not None:
        rows = rows.filter(request_key=key)
    elif review_id is None:
        newer = ContentLifecycleReview.objects.filter(project=project, review_id=OuterRef("review_id"), revision__gt=OuterRef("revision"))
        rows = rows.annotate(newer=Exists(newer)).filter(newer=False)
    limit = 20 if review_id else 50
    rows = list(rows.order_by("-pk")[:limit + 1])
    try:
        serialized = [_serialize(row) for row in rows[:limit]]
        context = _context(project, request.user)
        # Reconcile effective flags after later list private reads; retained history itself stays readable.
        for row, value in zip(rows, serialized):
            value["source_current"] = lifecycle_source_current(row)
            value["is_latest"] = not ContentLifecycleReview.objects.filter(project=project, review_id=row.review_id, revision__gt=row.revision).exists()
            value["effective_approval"] = value["source_current"] and value["is_latest"] and row.state in {"approved", "reported"}
        for row, value in zip(rows, serialized):
            if value["source_current"]:
                try:
                    require_current_lifecycle_delivery(row)
                except (PermissionDenied, ValidationError):
                    value["source_current"] = value["effective_approval"] = False
        for source in context["sources"]:
            row = ContentRevision.objects.filter(project=project, pk=source["content"]["revision_id"]).first()
            if row is None:
                raise PermissionDenied
            _current_authority(row, request.user)
        require_project_action(project=project, user=request.user, action=Action.VIEW_PROJECT)
        if context["can_review"]:
            require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
            if not _verified(request.user):
                raise PermissionDenied
    except PermissionDenied:
        return _error("Current content/source delivery authority is unavailable.", HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _error("Current exact content selections changed; refresh history.", HTTPStatus.CONFLICT)
    return _response({**context, "reviews": serialized, "has_more": len(rows) > limit,
        "lookup": "found" if key and rows else "not_found" if key else None})
