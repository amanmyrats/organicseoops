"""Manual native-text revisions and human approval. No network or publishing calls."""
from datetime import datetime
import re

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from tenancy.models import Organization, Project
from tenancy.services import Action, require_project_action
from .action_review import _source, _opportunity_source
from .content_brief import read_content_brief
from .intent_mapping import _project_page
from .models import ActionReview, ContentBriefSnapshot, ContentItem, ContentRevision, JobRun, JobStatus

TEXT_FIELDS = ("brief_id", "kind", "title", "body", "meta_description")
TRANSITIONS = {
    "idea": {"research", "brief", "draft", "archived"},
    "research": {"brief", "draft", "archived"},
    "brief": {"draft", "archived"},
    "draft": {"draft", "review", "archived"},
    "review": {"draft", "approved", "archived"},
    "approved": {"draft", "published", "archived"},
    "published": {"draft", "archived"},
    "archived": {"draft"},
}


def require_current_brief(project, actor, brief):
    data = read_content_brief(project=project, actor=actor, brief=brief)
    source = brief.action_review
    current = ActionReview.objects.filter(project=project, action_id=source.action_id).order_by("-revision").first()
    if current.pk != source.pk or current.state not in {"accepted", "in_progress", "implemented", "verified", "outcome_reviewed"}:
        raise ValidationError("Brief action changed; prepare a new source-linked brief.")
    if source.intent_cluster_id:
        _source(project, source.intent_cluster_id)
    else:
        _opportunity_source(project, actor, source.opportunity_id, source.action_kind,
            source.affected_urls[-1] if len(source.affected_urls) == 2 or source.action_kind == "create" else "")
    from .research import _context
    research = brief.research_job
    try:
        if _context(project, research.input_snapshot, actor) != research.config_snapshot["research_context"]:
            raise ValidationError("Research scope changed; prepare current evidence.")
    except (KeyError, TypeError):
        raise ValidationError("Research scope is unavailable; prepare current evidence.") from None
    return data


def record_content(*, project, actor, request_key, brief_id, kind, title, body, meta_description,
                   state, reason, item_id=None, expected_revision=None, publication_url="", published_at=None,
                   generating_job_id=None):
    if (type(request_key) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", request_key)
        or type(brief_id) is not int or brief_id < 1 or type(kind) is not str or kind not in ContentRevision.Kind.values
        or type(state) is not str or state not in ContentRevision.State.values
        or type(title) is not str or not 1 <= len(title.strip()) <= 240
        or type(body) is not str or len(body) > 30000 or len(body.encode()) > 120000
        or type(meta_description) is not str or len(meta_description) > 320
        or type(reason) is not str or not 1 <= len(reason.strip()) <= 500
        or type(publication_url) is not str or len(publication_url) > 512
        or published_at is not None and (not isinstance(published_at, datetime) or timezone.is_naive(published_at)
                                        or published_at > timezone.now())
        or (item_id is None) != (expected_revision is None)
        or item_id is not None and (type(item_id) is not int or item_id < 1
                                    or type(expected_revision) is not int or not 1 <= expected_revision < 2147483647)):
        raise ValidationError("Choose bounded text, a current revision and an explicit review reason.")
    values = dict(brief_id=brief_id, kind=kind, title=title.strip(), body=body,
                  meta_description=meta_description.strip(), state=state, reason=reason.strip())
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        require_project_action(project=project, user=actor,
            action=Action.APPROVE if state in {"approved", "published", "archived"} else Action.LAUNCH_JOB)
        brief = ContentBriefSnapshot.objects.filter(pk=brief_id, project=project).first()
        if brief is None:
            raise PermissionDenied
        generating_job = None
        if generating_job_id is not None:
            if type(generating_job_id) is not int:
                raise ValidationError("Generating job must be an exact project-owned attempt.")
            generating_job = JobRun.objects.filter(pk=generating_job_id, project=project, actor=actor,
                handler="generate_content", status__in=[JobStatus.RUNNING, JobStatus.SUCCEEDED]).first()
            if (not generating_job or generating_job.input_snapshot.get("brief_id") != brief.pk or state != "draft"
                or item_id is not None):
                raise ValidationError("Generation can only create a new unapproved source-linked draft.")
        previous = None
        if item_id is not None:
            previous = ContentRevision.objects.filter(item_id=item_id, project=project).order_by("-revision").first()
            if previous is None:
                raise PermissionDenied
        existing = ContentRevision.objects.filter(project=project, request_key=request_key).first()
        if existing:
            if (existing.actor_id != actor.pk or existing.item_id != (item_id or existing.item_id)
                or existing.revision != (expected_revision + 1 if item_id else 1)
                or generating_job_id is not None and existing.generating_job_id != generating_job_id
                or any(getattr(existing, key) != value for key, value in values.items())
                or (state == "published" and (existing.publication_url != publication_url or existing.published_at != published_at))):
                raise ValidationError("Request key belongs to another content decision.")
            return existing
        if previous:
            if previous.revision != expected_revision or state not in TRANSITIONS[previous.state]:
                raise ValidationError("Content changed; inspect the latest revision before saving.")
            if state != "draft" and any(getattr(previous, key) != values[key] for key in TEXT_FIELDS):
                raise ValidationError("Changed text or provenance requires a draft and fresh review.")
        elif state not in {"idea", "research", "brief", "draft"}:
            raise ValidationError("New content cannot bypass drafting and human review.")
        if state != "archived":
            require_current_brief(project, actor, brief)
        reviewed = approved_by = approved_at = None
        if state == "approved":
            reviewed, approved_by, approved_at = previous, actor, timezone.now()
        elif previous and state in {"published", "archived"}:
            reviewed, approved_by, approved_at = previous.reviewed_revision, previous.approved_by, previous.approved_at
        if state == "published":
            publication_url = _project_page(project, publication_url)
            if not published_at:
                raise ValidationError("Record the actual manual publication date. No page is changed here.")
        else:
            if publication_url or published_at:
                raise ValidationError("Publication metadata belongs only to a manual publication report.")
            publication_url = previous.publication_url if previous else ""
            published_at = previous.published_at if previous else None
        item = previous.item if previous else ContentItem.objects.create(project=project, actor=actor, request_key=request_key)
        return ContentRevision.objects.create(project=project, item=item, actor=actor, request_key=request_key,
            generating_job=generating_job if generating_job else previous.generating_job if previous else None,
            revision=previous.revision + 1 if previous else 1, reviewed_revision=reviewed,
            approved_by=approved_by, approved_at=approved_at, publication_url=publication_url,
            published_at=published_at, **values)
