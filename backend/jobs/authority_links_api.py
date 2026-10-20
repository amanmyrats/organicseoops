"""Private exact human link commands and real target-only candidates; no fetching or source fabrication."""
from datetime import datetime
from http import HTTPStatus
import json
import re
from urllib.parse import urlsplit

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Exists, OuterRef
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods

from integrations.google_tokens import GoogleTokenError, _reject_constant, _unique_object
from integrations.oauth import _verified
from tenancy.models import OrganizationMembership, ProjectConfiguration
from tenancy.services import Action, require_project_action
from .action_review import _assignee
from .authority_links import (POLICY, link_review_source_current, own_target_crawl_evidence,
    record_authority_link, target_recovery_action_evidence)
from .findings_api import _error, _response
from .local_assessment_api import _project_access
from .models import ActionReview, AuthorityLinkReview, CrawlPageSnapshot


def _serialize(row, *, latest):
    current = link_review_source_current(row)
    return {"id": row.pk, "link_id": str(row.link_id), "project_id": row.project_id, "revision": row.revision,
        "state": row.state, "intake": row.intake, "target_evidence": row.target_evidence, "proposal": row.proposal,
        "recovery_action_review_id": row.recovery_action_review_id, "recovery_evidence": row.recovery_evidence,
        "assignee_id": row.assignee_id, "actor_id": row.actor_id, "source_actor_id": row.source_actor_id,
        "reason": row.reason, "reviewed_revision_id": row.reviewed_revision_id, "approved_by_id": row.approved_by_id,
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "executed_at": row.executed_at.isoformat() if row.executed_at else None,
        "execution_note": row.execution_note, "created_at": row.created_at.isoformat(),
        "source_current": current, "is_latest": latest,
        "effective_approval": latest and current and row.state in {"approved", "reported"},
        "scope": "historical_human_link_report_not_independent_link_proof_or_site_approval",
        "execution_state": "customer_reported_manual_activity_not_verified" if row.executed_at else "not_reported"}


def _context(project, actor):
    can_review = False
    try:
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        can_review = _verified(actor)
    except PermissionDenied:
        pass
    targets, recoveries, assignees, more = [], [], [], False
    config = ProjectConfiguration.objects.filter(project=project).first()
    if can_review and config:
        pages = list(CrawlPageSnapshot.objects.filter(project=project, crawl_run__project=project,
            crawl_run__completed_at__isnull=False).order_by("-pk")[:21])
        more = len(pages) > 20
        # At most twenty genuine target readbacks and twenty independently resolved page actions.
        for page in pages[:20]:
            try:
                parts = urlsplit(page.requested_url)
                origin = parts.scheme + "://" + parts.netloc
                _verification, evidence = own_target_crawl_evidence(project=project, actor=actor, origin=origin,
                    configuration_revision=config.revision, crawl_page_id=page.pk, target_url=page.requested_url)
                targets.append(evidence)
            except (PermissionDenied, ValidationError, ValueError):
                continue
        newer = ActionReview.objects.filter(project=project, action_id=OuterRef("action_id"), revision__gt=OuterRef("revision"))
        actions = list(ActionReview.objects.filter(project=project, action_kind__in=["refresh", "redirect"],
            opportunity__finding__detector="observed_http_error_candidate").select_related("opportunity__finding__source_diagnostics").annotate(newer=Exists(newer))
            .filter(newer=False).order_by("-pk")[:21])
        more |= len(actions) > 20
        for action in actions[:20]:
            target = next((row for row in targets if row["requested_url"] == action.opportunity.finding.subject
                and row["crawl_run_id"] == action.opportunity.finding.source_diagnostics.crawl_run_id), None) if action.opportunity.finding.source_diagnostics_id else None
            if target is None:
                continue
            try:
                recoveries.append(target_recovery_action_evidence(project=project, actor=actor, origin=target["origin"],
                    configuration_revision=config.revision, crawl_page_id=target["crawl_page_id"],
                    target_url=target["requested_url"], action_review_id=action.pk))
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
                pass
    return {"organization_id": project.organization_id, "project_id": project.pk, "policy": POLICY,
        "can_review": can_review, "targets": targets, "recovery_actions": recoveries, "assignees": assignees,
        "candidates_has_more": more, "source_basis": "actual_own_target_http_and_separate_page_action_no_external_report",
        "sending": "unavailable", "independent_external_verification": "unavailable", "lost_unlinked_links": "not_established"}


@sensitive_post_parameters()
@sensitive_variables()
@require_http_methods(["GET", "POST"])
def project_authority_links(request, organization_id, project_id, link_id=None):
    project, error = _project_access(request, organization_id, project_id, edit=request.method == "POST")
    if error:
        return error
    if request.method == "POST":
        if not ratelimit.consume(request, action="authority_link_review", user=request.user):
            return _error("Too many link-review decisions. Try again later.", HTTPStatus.TOO_MANY_REQUESTS)
        fields = {"request_key", "intake", "proposal", "assignee_id", "recovery_action_review_id", "state", "reason", "executed_at", "execution_note"}
        if link_id is not None:
            fields.add("expected_revision")
        try:
            if request.content_type != "application/json" or len(request.body) > 32 * 1024:
                raise ValidationError("Choose bounded JSON link-review fields.")
            data = json.loads(request.body, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            if type(data) is not dict or set(data) != fields:
                raise ValidationError("Choose exact human link-review fields.")
            if data["executed_at"] is not None:
                if type(data["executed_at"]) is not str or len(data["executed_at"]) > 64:
                    raise ValidationError("Report an aware actual manual activity date.")
                data["executed_at"] = datetime.fromisoformat(data["executed_at"])
            row = record_authority_link(project=project, actor=request.user, link_id=link_id, **data)
        except PermissionDenied:
            return _error("Current source, reviewer and assignee authority is required.", HTTPStatus.FORBIDDEN)
        except (ValidationError, GoogleTokenError, UnicodeError, ValueError, TypeError, RecursionError):
            return _error("Link review changed or fields are unavailable; refresh exact source and history.", HTTPStatus.CONFLICT)
        return _response({"organization_id": project.organization_id, "project_id": project.pk,
            "review": _serialize(row, latest=True)}, HTTPStatus.OK if link_id else HTTPStatus.CREATED)
    if set(request.GET) - {"request_key"} or any(len(values) != 1 for _, values in request.GET.lists()):
        return _error("Choose one bounded request-key lookup.", HTTPStatus.BAD_REQUEST)
    key = request.GET.get("request_key")
    if key is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", key):
        return _error("Choose a bounded request key.", HTTPStatus.BAD_REQUEST)
    rows = AuthorityLinkReview.objects.filter(project=project).select_related(
        "project__organization", "actor", "source_actor", "assignee", "reviewed_revision__actor", "approved_by")
    if link_id is not None:
        rows = rows.filter(link_id=link_id)
        if not rows.exists():
            return _error("Link review not found.", HTTPStatus.NOT_FOUND)
    newer = AuthorityLinkReview.objects.filter(project=project, link_id=OuterRef("link_id"), revision__gt=OuterRef("revision"))
    rows = rows.annotate(newer=Exists(newer))
    if key is not None:
        rows = rows.filter(request_key=key)
    elif link_id is None:
        rows = rows.filter(newer=False)
    limit = 20 if link_id else 50
    rows = list(rows.order_by("-pk")[:limit + 1])
    return _response({**_context(project, request.user), "reviews": [_serialize(row, latest=not row.newer) for row in rows[:limit]],
        "has_more": len(rows) > limit, "lookup": "found" if key and rows else "not_found" if key else None})
