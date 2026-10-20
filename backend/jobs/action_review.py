"""Human approval and manual action history; never changes a customer website."""
from datetime import datetime
from uuid import UUID, uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from integrations.models import ImportRun, SourceDimension
from integrations.services import require_connection_capability
from tenancy.models import Organization, Project, ProjectConfiguration
from tenancy.services import Action, require_project_action

from .intent_mapping import _project_page, current_query_findings
from .findings import (indexation_finding_current, performance_finding_current, technical_finding_current)
from .models import ActionReview, IntentClusterReview, Opportunity


TRANSITIONS = {
    "proposed": {"accepted", "dismissed"},
    "accepted": {"in_progress", "proposed", "dismissed"},
    "in_progress": {"implemented", "proposed", "dismissed"},
    "implemented": {"verified", "proposed"},
    "verified": {"outcome_reviewed", "proposed"},
    "outcome_reviewed": {"proposed"},
    "dismissed": {"proposed"},
}


def _source(project, source_id):
    source = IntentClusterReview.objects.filter(pk=source_id, project=project).first()
    if source is None:
        raise PermissionDenied
    if IntentClusterReview.objects.filter(project=project, cluster_id=source.cluster_id).aggregate(
        last=Max("revision"))["last"] != source.revision:
        raise ValidationError("Intent mapping changed; review the latest source revision.")
    if source.proposed_action == IntentClusterReview.ProposedAction.UNSELECTED or source.page_kind == "unmapped":
        raise ValidationError("Choose an explicit, unapproved page action first.")
    if source.source_finding_ids:
        current_query_findings(project, source.source_finding_ids)
    else:
        config = ProjectConfiguration.objects.filter(project=project).first()
        if not config or any(topic not in config.seed_topics for topic in source.manual_topics):
            raise ValidationError("Manual seed evidence is no longer current.")
    urls = [source.affected_page, source.preferred_page] if source.affected_page else [source.preferred_page]
    return source, [_project_page(project, value) for value in urls]


def _opportunity_source(project, actor, source_id, action_kind, destination_page):
    review = Opportunity.objects.filter(pk=source_id, project=project).select_related(
        "finding__source_metric__import_run__connection", "finding__source_diagnostics",
        "finding__source_indexation", "finding__source_performance").first()
    if review is None:
        raise PermissionDenied
    if Opportunity.objects.filter(project=project, finding=review.finding).aggregate(
        last=Max("revision"))["last"] != review.revision:
        raise ValidationError("Opportunity review changed; use the latest revision.")
    finding = review.finding
    if finding.source_metric_id:
        metric = finding.source_metric
        if (metric.dimension != SourceDimension.PAGE or not metric.page
            or metric.import_run.status != ImportRun.Status.SUCCEEDED
            or metric.import_run.coverage_state != ImportRun.CoverageState.COMPLETE
            or metric.import_run.row_errors):
            raise ValidationError("A query-only candidate has no evidenced page; map intent first.")
        require_connection_capability(metric.import_run.connection, "page_metrics", dimensions=[SourceDimension.PAGE])
    elif finding.source_diagnostics_id:
        if not technical_finding_current(project=project, finding=finding):
            raise ValidationError("Technical finding evidence is no longer current.")
    elif finding.source_indexation_id:
        if not indexation_finding_current(project=project, user=actor, finding=finding):
            raise ValidationError("Indexation finding evidence is no longer current.")
    elif finding.source_performance_id:
        if not performance_finding_current(project=project, finding=finding):
            raise ValidationError("Performance finding evidence is no longer current.")
    else:
        raise ValidationError("This finding has no project-safe page evidence.")

    affected = _project_page(project, finding.subject)
    if action_kind == "create":
        if not destination_page:
            raise ValidationError("Propose the new exact-project page URL.")
        return review, [_project_page(project, destination_page)]
    if action_kind in {"merge", "redirect"}:
        target = _project_page(project, destination_page)
        if target == affected:
            raise ValidationError("Source and destination pages must differ.")
        return review, [affected, target]
    if destination_page:
        raise ValidationError("Only creation/merge/redirect may name a distinct destination.")
    return review, [affected]


def _assignee(project, assignee_id):
    if type(assignee_id) is not int or assignee_id < 1:
        raise ValidationError("Choose an active project assignee.")
    user = get_user_model().objects.filter(pk=assignee_id, is_active=True).first()
    if user is None:
        raise ValidationError("Choose an active project assignee.")
    require_project_action(project=project, user=user, action=Action.LAUNCH_JOB)
    return user


def record_action(*, project, actor, request_key, source_id, state, assignee_id, acceptance_criteria,
                  reason, action_id=None, expected_revision=None, change_summary="",
                  implemented_at=None, verification_note="", outcome_note="",
                  source_type="intent", action_kind=None, destination_page=""):
    if (type(request_key) is not str or not 8 <= len(request_key) <= 64
        or not request_key[0].isascii() or not request_key[0].isalnum()
        or any(not char.isascii() or not (char.isalnum() or char in "_-") for char in request_key)
        or type(source_id) is not int or source_id < 1
        or source_type not in {"intent", "opportunity"}
        or type(destination_page) is not str or len(destination_page) > 512
        or state not in ActionReview.State.values or type(acceptance_criteria) is not str
        or not 1 <= len(acceptance_criteria.strip()) <= 500
        or type(reason) is not str or not 1 <= len(reason.strip()) <= 500
        or implemented_at is not None and (not isinstance(implemented_at, datetime)
                                            or timezone.is_naive(implemented_at))
        or any(type(value) is not str or len(value) > 500
               for value in (change_summary, verification_note, outcome_note))):
        raise ValidationError("Choose a bounded action, assignee and review rationale.")
    if (action_id is None) != (expected_revision is None):
        raise ValidationError("Correct one known action revision or propose a new action.")
    if action_id is not None:
        try:
            action_id = UUID(str(action_id))
        except ValueError:
            raise ValidationError("Select a current action.") from None
        if type(expected_revision) is not int or not 1 <= expected_revision < 65535:
            raise ValidationError("Select a current action revision.")

    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        if source_type == "intent":
            source, urls = _source(project, source_id)
            if action_kind not in (None, source.proposed_action) or destination_page:
                raise ValidationError("A mapped human proposal fixes the action and affected pages.")
            action_kind = source.proposed_action
        else:
            if action_kind not in IntentClusterReview.ProposedAction.values or action_kind == "unselected":
                raise ValidationError("Choose a human action for page evidence.")
            source, urls = _opportunity_source(project, actor, source_id, action_kind, destination_page)
        assignee = _assignee(project, assignee_id)
        permission = Action.LAUNCH_JOB if state in {"in_progress", "implemented"} else Action.APPROVE
        require_project_action(project=project, user=actor, action=permission)
        if state in {"in_progress", "implemented"} and actor.pk != assignee.pk:
            raise PermissionDenied

        existing = ActionReview.objects.filter(project=project, request_key=request_key).first()
        if existing:
            latest = ActionReview.objects.filter(project=project, action_id=existing.action_id).aggregate(
                last=Max("revision"))["last"]
            if existing.revision != latest:
                raise ValidationError("Action history changed; reload the latest revision.")
            if (existing.actor_id != actor.pk or (action_id is not None and existing.action_id != action_id)
                or existing.revision != (expected_revision + 1 if action_id else 1)
                or (existing.intent_cluster_id if source_type == "intent" else existing.opportunity_id,
                    existing.state, existing.assignee_id, existing.action_kind, existing.affected_urls,
                    existing.acceptance_criteria, existing.reason, existing.change_summary,
                    existing.implemented_at, existing.verification_note, existing.outcome_note)
                != (source.pk, state, assignee.pk, action_kind, urls, acceptance_criteria.strip(), reason.strip(),
                    change_summary.strip(), implemented_at, verification_note.strip(), outcome_note.strip())):
                raise ValidationError("Action key belongs to another decision.")
            return existing

        if action_id is None:
            if state != ActionReview.State.PROPOSED:
                raise ValidationError("New actions must await human approval.")
            action_id, revision = uuid4(), 1
        else:
            previous = ActionReview.objects.filter(project=project, action_id=action_id).order_by("-revision").first()
            if previous is None or previous.revision != expected_revision or state not in TRANSITIONS[previous.state]:
                raise ValidationError("Action changed or this transition is unavailable.")
            if state != "proposed" and (
                (source_type == "intent" and previous.intent_cluster_id != source.pk)
                or (source_type == "opportunity" and previous.opportunity_id != source.pk)):
                raise ValidationError("Changed mapping requires a new unapproved proposal.")
            if state != "proposed" and (previous.assignee_id != assignee.pk
                or previous.acceptance_criteria != acceptance_criteria.strip()
                or previous.affected_urls != urls):
                raise ValidationError("Changed action scope requires a new proposal and approval.")
            revision = previous.revision + 1

        now = timezone.now()
        if state in {"proposed", "accepted", "in_progress", "dismissed"}:
            if implemented_at is not None or change_summary or verification_note or outcome_note:
                raise ValidationError("Implementation and verification need separate later states.")
            dates = (None, None, None)
        elif state == "implemented":
            if (not implemented_at or timezone.is_naive(implemented_at) or implemented_at > now
                or not change_summary.strip() or verification_note or outcome_note):
                raise ValidationError("Record the actual implementation date and a change summary only.")
            dates = (implemented_at, None, None)
        else:
            if (not previous or implemented_at != previous.implemented_at or change_summary.strip() != previous.change_summary
                or not verification_note.strip()):
                raise ValidationError("Verification requires the unchanged implementation and technical evidence note.")
            if state == "verified":
                if outcome_note:
                    raise ValidationError("Outcome review is a separate transition.")
                dates = (implemented_at, now, None)
            else:
                if not previous.verified_at or verification_note.strip() != previous.verification_note or not outcome_note.strip():
                    raise ValidationError("Outcome review needs existing verification and an explicit result note.")
                dates = (implemented_at, previous.verified_at, now)

        return ActionReview.objects.create(project=project,
            intent_cluster=source if source_type == "intent" else None,
            opportunity=source if source_type == "opportunity" else None, actor=actor,
            assignee=assignee, request_key=request_key, action_id=action_id, revision=revision,
            state=state, action_kind=action_kind, affected_urls=urls,
            acceptance_criteria=acceptance_criteria.strip(), reason=reason.strip(),
            change_summary=change_summary.strip(), verification_note=verification_note.strip(),
            outcome_note=outcome_note.strip(), implemented_at=dates[0], verified_at=dates[1],
            outcome_reviewed_at=dates[2])
