"""Read-only source-limited guidance over existing human review/approval workflows."""
from django.core.exceptions import PermissionDenied, ValidationError

from tenancy.models import Project, ProjectConfiguration
from tenancy.services import Action, require_project_action
from .findings import technical_finding_current
from .models import (AIVisibilityAnswerReview, ContentRevision, Finding, JobCancellation,
                     Opportunity, TechnicalDiagnosticsSnapshot)
from .visibility_collection import selection_snapshot
from .visibility_entities import answer_for, entity_context, validate_review_snapshot

METHOD = "visibility-discoverability-v1"
PROVIDER_GUIDANCE = "https://developers.openai.com/api/docs/bots"


def proposal_text(detector):
    if detector.startswith("schema_"):
        return "Review observed schema syntax/type and visible-content consistency; publish structured data only for verified facts. Valid schema does not establish rich-result eligibility or AI citation."
    if "link" in detector or "orphan" in detector:
        return "Review useful internal links to this page against the bounded crawl inventory and genuine customer intent. Crawl-relative isolation is not proof of whole-site orphaning."
    if "title" in detector or "description" in detector or "duplicate" in detector:
        return "Review useful distinct page answers, accurate entity details and original business expertise using the exact stored content/source evidence; metadata length or duplication alone does not justify removal."
    return "Review the observed HTTP/canonical/URL condition and the intended accessible page. Preserve user impact and destination review; a local fetch is not provider indexing or AI inclusion evidence."


def discoverability_evidence(*, project, actor, diagnostics_id=None):
    project = Project.objects.get(pk=project.pk, organization_id=project.organization_id)
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    if diagnostics_id is not None and (type(diagnostics_id) is not int or diagnostics_id < 1):
        raise ValidationError("Choose one stored diagnostics snapshot.")
    sources = list(TechnicalDiagnosticsSnapshot.objects.filter(project=project,
        crawl_run__project=project, crawl_run__job__project=project,
        crawl_run__job__status__in=["succeeded", "partially_succeeded"],
        crawl_run__completed_at__isnull=False).select_related("crawl_run__job__actor").order_by("-pk")[:21])
    selected = None
    if diagnostics_id is not None:
        selected = TechnicalDiagnosticsSnapshot.objects.filter(pk=diagnostics_id, project=project,
            crawl_run__project=project, crawl_run__job__project=project,
            crawl_run__job__status__in=["succeeded", "partially_succeeded"],
            crawl_run__completed_at__isnull=False).select_related("crawl_run__job__actor").first()
        if selected is None:
            raise PermissionDenied
    proposals = []
    findings = list(Finding.objects.filter(project=project, source_diagnostics=selected)
        .select_related("source_diagnostics__crawl_run__job__actor").order_by("-pk")[:101]) if selected else []
    reviews = {row.finding_id: row for row in Opportunity.objects.filter(project=project, finding__in=findings[:100])
        .order_by("finding_id", "-revision").distinct("finding_id")}
    for finding in findings[:100]:
        review = reviews.get(finding.pk)
        proposals.append({"id": finding.pk, "project_id": project.pk, "subject": finding.subject,
            "detector": finding.detector, "evidence": finding.evidence, "detected_at": finding.detected_at.isoformat(),
            "source_current": _source_current(project, finding.source_diagnostics) and technical_finding_current(project=project, finding=finding),
            "proposal": proposal_text(finding.detector), "approval": "requires_separate_exact_human_action_approval",
            "review": None if review is None else {"id": review.pk, "revision": review.revision,
                "reason": review.review_reason, "priority": review.priority}})
    config = ProjectConfiguration.objects.filter(project=project).first()
    latest_reviews = AIVisibilityAnswerReview.objects.filter(project=project, job__project=project).order_by("job_id", "-revision").distinct("job_id").values("pk")
    entities = list(AIVisibilityAnswerReview.objects.filter(pk__in=latest_reviews)
        .select_related("job__actor", "job__project").order_by("-pk")[:21])
    concerns = []
    for review in entities[:20]:
        try:
            validate_review_snapshot(review)
            current = config is not None and review.context == entity_context(review.job, config)
            try:
                current = current and selection_snapshot(project, review.job.actor, review.job.input_snapshot)[2] == review.job.config_snapshot
            except (PermissionDenied, ValidationError):
                current = False
            answer = answer_for(review.job)
        except ValidationError:
            continue
        for note in review.factual_notes:
            concerns.append({"project_id": project.pk, "job_id": review.job_id, "review_id": review.pk,
                "review_revision": review.revision, "reviewed_at": review.created_at.isoformat(),
                "collected_at": review.job.output.get("collected_at"), "source_current": current,
                "text": answer[note["start"]:note["end"]], "note": note["note"],
                "proposal": "Verify this human concern against approved business records before proposing a source-linked content correction; the answer/note is not factual truth."})
    latest_content = ContentRevision.objects.filter(project=project, item__project=project).order_by("item_id", "-revision").distinct("item_id").values("pk")
    content = list(ContentRevision.objects.filter(pk__in=latest_content).order_by("-pk")[:21])
    return {"method": METHOD, "project_id": project.pk,
        "diagnostics": [{"id": row.pk, "project_id": project.pk, "crawl_run_id": row.crawl_run_id,
            "observed_at": row.observed_at.isoformat(), "coverage": row.output["coverage"]["state"],
            "source_current": _source_current(project, row)} for row in sources[:20]],
        "selected_diagnostics_id": selected.pk if selected else None, "proposals": proposals,
        "has_more": len(sources) > 20 or len(findings) > 100 or len(entities) > 20 or len(content) > 20,
        "human_factual_concerns": concerns,
        "content_revisions": [{"project_id": project.pk, "item_id": row.item_id, "revision_id": row.pk,
            "revision": row.revision, "title": row.title, "state": row.state, "brief_id": row.brief_id,
            "reviewed_revision_id": row.reviewed_revision_id, "created_at": row.created_at.isoformat(),
            "proposal": "Review the exact linked brief/sources, genuinely helpful answers and original business expertise in the content workflow. Current record revision is not verified live-page quality or business truth."} for row in content[:20]],
        "provider_agents": [{"agent": agent, "purpose": purpose, "access": "unavailable_no_agent_specific_robots_evidence"}
            for agent, purpose in (("OAI-SearchBot", "search_retrieval"), ("GPTBot", "potential_training"),
                                   ("ChatGPT-User", "user_triggered_robots_may_not_apply_not_search_inclusion"))],
        "guidance_source": PROVIDER_GUIDANCE, "guidance_reviewed_on": "2026-10-01",
        "unavailable": ["provider_agent_robots_rules", "verified_bot_visits", "approved_business_fact_registry",
            "credible_external_mentions", "ai_placement_or_training_membership"],
        "limits": "Stored bounded crawl/content/human evidence only; no fetch, IP list, experimental file or inclusion guarantee. Prioritization is not approval; no website changes."}


def _source_current(project, source):
    if (source.project_id != project.pk or source.crawl_run.project_id != project.pk
        or source.crawl_run.job.project_id != project.pk
        or source.output.get("coverage", {}).get("state") not in {"partial", "complete_for_crawl_scope"}
        or JobCancellation.objects.filter(job_id=source.crawl_run.job_id).exists()):
        return False
    try:
        require_project_action(project=project, user=source.crawl_run.job.actor, action=Action.LAUNCH_JOB)
        from .performance import _scoped_url
        for url in source.crawl_run.job.input_snapshot.get("seeds", []):
            _scoped_url(project, url)
        return bool(source.crawl_run.job.input_snapshot.get("seeds"))
    except (PermissionDenied, ValidationError):
        return False
