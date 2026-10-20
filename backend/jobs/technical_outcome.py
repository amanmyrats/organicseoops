"""Observed crawl changes around a manual action, never automatic proof of a fix."""
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from tenancy.models import Organization, Project
from tenancy.services import Action, require_project_action

from .models import ActionReview, ActionTechnicalOutcomeSnapshot, CrawlPageSnapshot, CrawlRun, JobStatus
from .intent_mapping import _project_page


def _page_observation(page):
    if page is None:
        return None
    return {"id": page.pk, "observed_at": page.observed_at.isoformat(),
            "requested_url": page.requested_url, "final_url": page.final_url,
            "status_code": page.status_code, "canonical_url": page.canonical_url,
            "title": page.title, "robots_directives": page.robots_directives,
            "content_hash": page.content_hash, "error_category": page.error_category}


def compare_crawl_observations(before, after):
    if before is None or after is None:
        return {"state": "missing_page_observation_not_clean_or_zero",
                "previous": _page_observation(before), "current": _page_observation(after), "changes": None}
    old, new = _page_observation(before), _page_observation(after)
    if before.status_code is None or after.status_code is None or before.error_category or after.error_category:
        return {"state": "fetch_failed_or_unavailable_not_verified", "previous": old, "current": new,
                "changes": None}
    return {"state": "observed_http_page_changes_not_fix_proof", "previous": old, "current": new,
            "changes": {field: {"previous": old[field], "current": new[field]}
                        for field in ("status_code", "final_url", "canonical_url", "title",
                                      "robots_directives", "content_hash") if old[field] != new[field]}}


def compare_action_crawls(*, project, actor, action_id, previous_crawl_id, current_crawl_id):
    project = Project.objects.get(pk=project.pk, organization_id=project.organization_id)
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    try:
        action_id = UUID(str(action_id))
    except ValueError:
        raise ValidationError("Select a current action.") from None
    action = ActionReview.objects.filter(project=project, action_id=action_id).order_by("-revision").first()
    if action is None:
        raise PermissionDenied
    if action.state not in {ActionReview.State.IMPLEMENTED, ActionReview.State.VERIFIED,
                            ActionReview.State.OUTCOME_REVIEWED} or not action.implemented_at:
        raise ValidationError("Log a manual implementation before comparing crawl observations.")
    urls = [_project_page(project, url) for url in action.affected_urls]
    if (type(previous_crawl_id) is not int or type(current_crawl_id) is not int
        or previous_crawl_id == current_crawl_id):
        raise ValidationError("Choose distinct project crawls.")
    runs = list(CrawlRun.objects.filter(project=project, pk__in=[previous_crawl_id, current_crawl_id])
                .select_related("job"))
    if len(runs) != 2:
        raise PermissionDenied
    by_id = {run.pk: run for run in runs}
    before_run, after_run = by_id[previous_crawl_id], by_id[current_crawl_id]
    if (not before_run.completed_at or not after_run.completed_at
        or before_run.completed_at >= action.implemented_at
        or after_run.started_at <= action.implemented_at
        or before_run.job.created_at > action.implemented_at
        or before_run.job.method_version != after_run.job.method_version
        or any(run.job.status not in {JobStatus.SUCCEEDED, JobStatus.PARTIALLY_SUCCEEDED}
               for run in (before_run, after_run))):
        raise ValidationError("Comparable completed crawls must bracket the logged change.")
    def observations(run):
        rows = list(CrawlPageSnapshot.objects.filter(project=project, crawl_run=run,
                    requested_url__in=urls).order_by("pk")[:len(urls) + 1])
        if len(rows) > len(urls):
            raise ValidationError("Crawl page identity is ambiguous.")
        return {page.requested_url: page for page in rows}
    old, new = observations(before_run), observations(after_run)
    if any(page and page.observed_at > action.implemented_at for page in old.values()) or any(
        page and page.observed_at <= action.implemented_at for page in new.values()
    ):
        raise ValidationError("Actual page observations must bracket the implementation time.")
    return {"method_version": "action-crawl-observation-v1", "project_id": project.pk,
            "action_id": str(action_id), "action_revision": action.revision,
            "implementation_at": action.implemented_at.isoformat(),
            "previous": {"crawl_run_id": before_run.pk, "completed_at": before_run.completed_at.isoformat(),
                         "pages_observed": before_run.pages_observed, "page_limit": before_run.page_limit},
            "current": {"crawl_run_id": after_run.pk, "completed_at": after_run.completed_at.isoformat(),
                        "pages_observed": after_run.pages_observed, "page_limit": after_run.page_limit},
            "urls": [{"url": url, **compare_crawl_observations(old.get(url), new.get(url))} for url in urls],
            "interpretation": "observed_technical_state_not_automatic_verification_or_causal_outcome"}


def record_action_crawl_observations(*, project, actor, action_id, previous_crawl_id, current_crawl_id):
    try:
        action_id = UUID(str(action_id))
    except ValueError:
        raise ValidationError("Select a current action.") from None
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        action = ActionReview.objects.filter(project=project, action_id=action_id).order_by("-revision").first()
        if action is None:
            raise PermissionDenied
        existing = ActionTechnicalOutcomeSnapshot.objects.filter(project=project, action_review=action).first()
        if existing:
            if (existing.actor_id != actor.pk or existing.previous_crawl_id != previous_crawl_id
                or existing.current_crawl_id != current_crawl_id):
                raise ValidationError("A different technical check already exists for this action revision.")
            return existing
        report = compare_action_crawls(project=project, actor=actor, action_id=action_id,
                                       previous_crawl_id=previous_crawl_id, current_crawl_id=current_crawl_id)
        previous = CrawlRun.objects.get(pk=previous_crawl_id, project=project)
        current = CrawlRun.objects.get(pk=current_crawl_id, project=project)
        return ActionTechnicalOutcomeSnapshot.objects.create(project=project, action_review=action,
            actor=actor, previous_crawl=previous, current_crawl=current, report=report)
