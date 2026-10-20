"""Current existing-content evidence for human quality review; no site change or fact inference."""
from datetime import datetime
from hashlib import sha256
import json
import re
from uuid import UUID, uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from integrations.oauth import _verified
from tenancy.models import Organization, Project
from tenancy.services import Action, require_project_action
from .action_review import _assignee, _opportunity_source, _source
from .authority import research_authority_source
from .content_brief import read_content_brief
from .intent_mapping import _project_page
from .local_feedback import _text
from .models import ActionReview, Artifact, ContentBriefSnapshot, ContentLifecycleReview, ContentRevision, JobRun, JobStep, SourceCitation
from .research import _context

METHOD = "content-lifecycle-source-v1"
POLICY = "content-human-quality-v1"
SOURCE_FIELDS = ("index", "state", "requested_url", "url", "title", "retrieved_at", "sha256", "size_bytes", "excerpt_truncated")
INTAKE_FIELDS = {"policy", "content_revision_id", "text_sha256", "reviewed_at", "judgment", "substantive_basis",
    "quote", "evidence_note", "expertise_note", "service_fact_note", "facts_checked_at", "proposed_action",
    "rationale", "destination_url", "destination_review", "user_impact", "use_permission", "storage_permission",
    "not_restricted_copy", "no_personal_payload"}
TRANSITIONS = {"draft": {"draft", "review", "dismissed"}, "review": {"draft", "approved", "dismissed"},
    "approved": {"draft", "reported", "dismissed"}, "reported": {"draft"}, "dismissed": {"draft"}}


def _text_digest(row):
    text = {key: getattr(row, key) for key in ("kind", "title", "body", "meta_description")}
    return sha256(json.dumps(text, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _current_authority(row, actor):
    project = Project.objects.select_related("organization").filter(pk=row.project_id, organization_id=row.project.organization_id).first()
    if project is None:
        raise PermissionDenied
    brief = row.brief
    action, research = brief.action_review, brief.research_job
    users = [(actor, Action.MANAGE_PROJECT), (row.actor, Action.LAUNCH_JOB), (row.item.actor, Action.LAUNCH_JOB),
             (brief.actor, Action.LAUNCH_JOB), (research.actor, Action.LAUNCH_JOB),
             (action.actor, Action.LAUNCH_JOB if action.state in {"in_progress", "implemented"} else Action.APPROVE)]
    if row.reviewed_revision_id:
        users.extend([(row.reviewed_revision.actor, Action.LAUNCH_JOB), (row.approved_by, Action.APPROVE)])
    for user, permission in users:
        require_project_action(project=project, user=user, action=permission)
        if not _verified(user):
            raise PermissionDenied
    if (any(timezone.is_naive(date) or date > timezone.now() for date in
            (row.created_at, brief.created_at, *[date for date in (row.approved_at, row.published_at) if date]))
        or brief.created_at > row.created_at):
        raise ValidationError("Keep actual ordered source/content dates and original manual publication time.")
    _assignee(project, action.assignee_id)
    if (ContentRevision.objects.filter(project=project, item_id=row.item_id, revision__gt=row.revision).exists()
        or ActionReview.objects.filter(project=project, action_id=action.action_id, revision__gt=action.revision).exists()
        or action.state not in {"accepted", "in_progress", "implemented", "verified", "outcome_reviewed"}):
        raise ValidationError("Content/action selection changed; review the current exact revisions.")
    if action.intent_cluster_id:
        mapping, urls = _source(project, action.intent_cluster_id)
        if research.input_snapshot.get("mapping_id") != mapping.pk:
            raise ValidationError("Content research and action require the same exact intent mapping.")
    else:
        _review, urls = _opportunity_source(project, actor, action.opportunity_id, action.action_kind,
            action.affected_urls[-1] if len(action.affected_urls) == 2 or action.action_kind == "create" else "")
    if (urls != action.affected_urls
        or _context(project, research.input_snapshot, research.actor) != research.config_snapshot.get("research_context")):
        raise ValidationError("Current content source configuration and page mapping are required.")
    if row.publication_url and row.publication_url != _project_page(project, row.publication_url):
        raise ValidationError("Reported publication must remain within current project scope.")


def read_content_lifecycle_source(*, project, actor, revision_id):
    """Freeze an actual latest draft and real dated private sources, never live-page/service verification."""
    if type(revision_id) is not int or not 1 <= revision_id < 2**53:
        raise ValidationError("Choose an exact saved content revision.")
    project = Project.objects.select_related("organization").filter(pk=project.pk, organization_id=project.organization_id).first()
    if project is None:
        raise PermissionDenied
    row = ContentRevision.objects.filter(pk=revision_id, project=project).select_related(
        "project__organization", "item__actor", "actor", "approved_by", "reviewed_revision__actor",
        "brief__actor", "brief__research_job__actor", "brief__action_review__actor").first()
    if row is None:
        raise PermissionDenied
    row.clean()
    if not row.body.strip():
        raise ValidationError("Quality review requires actual saved native text.")
    _current_authority(row, actor)
    brief, research, action = row.brief, row.brief.research_job, row.brief.action_review
    body = read_content_brief(project=project, actor=actor, brief=brief)
    actual_sources = research.output.get("sources")
    if (type(actual_sources) is not list or not 1 <= len(actual_sources) <= 5
        or any(type(source) is not dict for source in actual_sources)):
        raise ValidationError("Bounded actual research provenance is required.")
    selected_sources = [{key: source[key] for key in SOURCE_FIELDS if key in source} for source in actual_sources]
    if (body.get("sources") != selected_sources or body.get("research_job_id") != research.pk
        or body.get("action_review_id") != action.pk or body.get("action_id") != str(action.action_id)
        or body.get("action_revision") != action.revision or body.get("affected_pages") != action.affected_urls):
        raise ValidationError("Private brief differs from its exact action/research sources.")
    sources = []
    for source in selected_sources:
        if source.get("state") != "collected":
            sources.append({"source_index": source.get("index"), "state": source.get("state"),
                            "retrieved_at": None, "facts": "unavailable"})
            continue
        evidence = research_authority_source(project=project, actor=actor,
            research_job_id=research.pk, source_index=source.get("index"))
        if datetime.fromisoformat(evidence["retrieved_at"]) > brief.created_at:
            raise ValidationError("Source retrieval cannot postdate the original private brief.")
        sources.append({key: evidence[key] for key in ("method", "research_job_id", "source_index", "step_id", "artifact_id",
            "requested_url", "url", "title", "retrieved_at", "original_response_sha256", "source_size_bytes",
            "excerpt_truncated", "coverage", "facts")})
    if not any("method" in source for source in sources):
        raise ValidationError("At least one actual private collected source is required.")
    # Private reads may outlive the earlier authorization/configuration/latest checks.
    fresh = JobRun.objects.filter(pk=research.pk, project=project).first()
    if fresh is None or (fresh.output, fresh.input_snapshot, fresh.config_snapshot, fresh.status) != (
        research.output, research.input_snapshot, research.config_snapshot, research.status):
        raise ValidationError("Research changed during private readback.")
    _current_authority(row, actor)
    return {"method": METHOD, "project_id": project.pk, "configuration_revision": research.config_snapshot["research_context"]["configuration_revision"],
        "content": {"item_id": row.item_id, "revision_id": row.pk, "revision": row.revision, "state": row.state,
            "kind": row.kind, "title": row.title, "text_sha256": _text_digest(row), "actor_id": row.actor_id,
            "created_at": row.created_at.isoformat(), "reviewed_revision_id": row.reviewed_revision_id,
            "approved_by_id": row.approved_by_id, "approved_at": row.approved_at.isoformat() if row.approved_at else None,
            "publication_url": row.publication_url, "published_at": row.published_at.isoformat() if row.published_at else None,
            "publication_basis": "historical_manual_report_not_verified_live_content_or_publication_age",
            "archive_effect": "record_only_no_live_page_removed"},
        "brief": {"id": brief.pk, "sha256": brief.content_sha256, "size_bytes": brief.size_bytes,
                  "created_at": brief.created_at.isoformat(), "actor_id": brief.actor_id},
        "action": {"review_id": action.pk, "action_id": str(action.action_id), "revision": action.revision,
            "state": action.state, "kind": action.action_kind, "affected_urls": action.affected_urls,
            "intent_cluster_id": action.intent_cluster_id, "opportunity_id": action.opportunity_id,
            "assignee_id": action.assignee_id, "approval": "separate_existing_page_action_not_content_lifecycle_approval"},
        "sources": sources, "source_current": True, "expertise": "not_recorded_requires_human_evidence",
        "service_facts": "not_verified_by_research_or_manual_local_assessment", "quality_judgment": "not_recorded",
        "conversion_context": "unavailable_exact_origin_attribution_not_established",
        "interpretation": "saved_native_text_and_dated_sources_not_live_page_quality_or_deletion_recommendation"}


def compare_content_lifecycle_sources(*, project, other_project, actor, revision_id, other_revision_id):
    """Two independently authorized saved native texts, never a copy, live-page or duplicate-SEO claim."""
    if revision_id == other_revision_id:
        raise ValidationError("Choose two distinct actual saved content selections.")
    def metadata(row, evidence):
        collected = [source for source in evidence["sources"] if "method" in source]
        step_ids = [source["step_id"] for source in collected]
        artifact_ids = [source["artifact_id"] for source in collected]
        steps = list(JobStep.objects.filter(job=row.brief.research_job, pk__in=step_ids).order_by("pk").values())
        artifacts = list(Artifact.objects.filter(project=row.project, job=row.brief.research_job, pk__in=artifact_ids).order_by("pk").values())
        citations = list(SourceCitation.objects.filter(job=row.brief.research_job, step_id__in=step_ids).order_by("pk").values())
        if (len(steps) != len(step_ids) or len(artifacts) != len(artifact_ids)
            or any(not any(citation["step_id"] == source["step_id"] and citation["source_url"] == source["url"]
                and citation["source_title"] == source["title"] and citation["observed_at"] == datetime.fromisoformat(source["retrieved_at"])
                for citation in citations) for source in collected)):
            raise ValidationError("Each exact private source and citation must remain available.")
        return (ContentRevision.objects.filter(project=row.project, pk=row.pk).values().first(),
            ContentBriefSnapshot.objects.filter(project=row.project, pk=row.brief_id).values().first(),
            JobRun.objects.filter(project=row.project, pk=row.brief.research_job_id).values("output", "input_snapshot", "config_snapshot", "status").first(),
            steps, artifacts, citations)

    selections, snapshots = [], []
    for selected_project, selected_id in ((project, revision_id), (other_project, other_revision_id)):
        evidence = read_content_lifecycle_source(project=selected_project, actor=actor, revision_id=selected_id)
        row = ContentRevision.objects.get(project=selected_project, pk=selected_id)
        if _text_digest(row) != evidence["content"]["text_sha256"]:
            raise ValidationError("Exact native text changed during source inspection.")
        snapshots.append(metadata(row, evidence))
        selections.append({"organization_id": selected_project.organization_id, "project_id": selected_project.pk,
            "source": evidence, "text": {key: getattr(row, key) for key in ("kind", "title", "body", "meta_description")}})
    # Reading the other project's private sources must not outlive either side's authority/latest metadata.
    for selection, snapshot in zip(selections, snapshots):
        selected_project = project if selection["project_id"] == project.pk else other_project
        row = ContentRevision.objects.filter(project=selected_project, pk=selection["source"]["content"]["revision_id"]).first()
        if row is None:
            raise PermissionDenied
        _current_authority(row, actor)
        if _text_digest(row) != selection["source"]["content"]["text_sha256"] or metadata(row, selection["source"]) != snapshot:
            raise ValidationError("Exact current native text is required for each comparison side.")
    return {"method": "content-native-comparison-v1", "left": selections[0], "right": selections[1],
        "same_native_body": selections[0]["text"]["body"] == selections[1]["text"]["body"],
        "interpretation": "saved_native_text_only_not_live_duplicate_content_thinness_or_service_verification",
        "site_action": "separate_human_judgment_and_each_project_action_approval_required"}


def validate_content_lifecycle_intake(data, *, project, revision, evidence):
    """Scalar human declarations only; the caller must resolve actual current evidence before saving."""
    if (type(data) is not dict or set(data) != INTAKE_FIELDS or data["policy"] != POLICY
        or type(data["content_revision_id"]) is not int or not 1 <= data["content_revision_id"] < 2**53
        or any(data[key] is not True for key in ("use_permission", "storage_permission", "not_restricted_copy", "no_personal_payload"))
        or type(evidence) is not dict or evidence.get("method") != METHOD or evidence.get("source_current") is not True
        or evidence.get("project_id") != project.pk or revision.project_id != project.pk
        or data["content_revision_id"] != revision.pk or type(evidence.get("content")) is not dict
        or type(evidence.get("action")) is not dict or type(evidence["action"].get("affected_urls")) is not list
        or evidence["content"].get("revision_id") != revision.pk or data["text_sha256"] != _text_digest(revision)
        or data["text_sha256"] != evidence["content"].get("text_sha256")):
        raise ValidationError("Review the exact current native-text revision with independent storage/use declarations.")
    for field, limit, required in (("text_sha256", 64, True), ("reviewed_at", 64, True), ("judgment", 64, True),
        ("substantive_basis", 64, True), ("quote", 1000, False), ("evidence_note", 1000, False),
        ("expertise_note", 1000, False), ("service_fact_note", 1000, False), ("facts_checked_at", 64, False),
        ("proposed_action", 32, True), ("rationale", 500, False), ("destination_url", 512, False),
        ("destination_review", 500, False), ("user_impact", 500, False)):
        _text(data[field], limit, required=required)
    try:
        reviewed = datetime.fromisoformat(data["reviewed_at"])
        if timezone.is_naive(reviewed) or not revision.created_at <= reviewed <= timezone.now():
            raise ValueError
        if bool(data["service_fact_note"].strip()) != bool(data["facts_checked_at"]):
            raise ValueError
        if data["facts_checked_at"]:
            checked = datetime.fromisoformat(data["facts_checked_at"])
            if timezone.is_naive(checked) or checked > reviewed:
                raise ValueError
        if len(json.dumps(data, ensure_ascii=False, allow_nan=False).encode()) > 16 * 1024:
            raise ValueError
    except (ValueError, TypeError, UnicodeError):
        raise ValidationError("Keep original aware nonfuture human review/fact dates and bounded scalar evidence.") from None
    if data["judgment"] == "not_checked":
        if data["substantive_basis"] != "unreviewed" or data["quote"] or data["evidence_note"]:
            raise ValidationError("Not checked cannot contain an issue or a checked-evidence claim.")
    elif (data["judgment"] not in {"no_issue_found_in_reviewed_text", "outdated_claim", "thin_coverage", "overlap", "service_detail_changed"}
        or data["substantive_basis"] not in {"content_claim_check", "business_expertise_review", "coverage_review"}
        or not data["quote"].strip() or not data["evidence_note"].strip()
        or not any(data["quote"] in value for value in (revision.title, revision.body, revision.meta_description))
        or data["substantive_basis"] == "business_expertise_review" and not (data["expertise_note"].strip() or data["service_fact_note"].strip())
        or data["judgment"] == "service_detail_changed" and not data["service_fact_note"].strip()):
        raise ValidationError("Human quality judgments require an exact stored quote and substantive evidence, never traffic/word count alone.")
    action = data["proposed_action"]
    if action == "unselected":
        if any(data[key] for key in ("rationale", "destination_url", "destination_review", "user_impact")):
            raise ValidationError("An unselected lifecycle action cannot claim a destination or implementation review.")
    elif action not in {"keep", "refresh", "consolidate", "redirect", "retire"} or data["judgment"] == "not_checked" or not (
        data["rationale"].strip() and data["user_impact"].strip()):
        raise ValidationError("Proposals require a substantive human review, rationale and user-impact review.")
    elif action in {"consolidate", "redirect", "retire"}:
        destination = _project_page(project, data["destination_url"])
        if (destination != data["destination_url"] or destination in evidence["action"]["affected_urls"]
            or destination == revision.publication_url or not data["destination_review"].strip()):
            raise ValidationError("Review a distinct exact-project replacement and user impact before destructive proposals.")
    elif data["destination_url"] or data["destination_review"]:
        raise ValidationError("Only consolidation/redirect/retirement proposals may name a reviewed replacement.")
    return dict(data)


def require_current_lifecycle_delivery(row, *, actor=None):
    _assignee(row.project, row.assignee_id)
    users = [row.source_actor, row.actor]
    if row.reviewed_revision_id:
        users.extend([row.reviewed_revision.actor, row.approved_by])
    if actor is not None:
        users.append(actor)
    for user in users:
        require_project_action(project=row.project, user=user, action=Action.MANAGE_PROJECT)
        if not _verified(user):
            raise PermissionDenied
    _current_authority(row.content_revision, actor or row.source_actor)


def require_current_lifecycle_review(row, *, actor=None):
    require_current_lifecycle_delivery(row, actor=actor)
    source = read_content_lifecycle_source(project=row.project, actor=actor or row.source_actor, revision_id=row.content_revision_id)
    if source != row.source_evidence:
        raise ValidationError("Content source changed; prepare a fresh unapproved quality review.")
    validate_content_lifecycle_intake(row.intake, project=row.project, revision=row.content_revision, evidence=source)
    require_current_lifecycle_delivery(row, actor=actor)


def lifecycle_source_current(row):
    try:
        require_current_lifecycle_review(row)
        return True
    except (PermissionDenied, ValidationError):
        return False


def record_content_lifecycle(*, project, actor, request_key, intake, assignee_id, state, reason,
                             review_id=None, expected_revision=None, executed_at=None, execution_note=""):
    if (type(request_key) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", request_key)
        or type(intake) is not dict or type(state) is not str or state not in ContentLifecycleReview.State.values
        or (review_id is None) != (expected_revision is None)
        or expected_revision is not None and (type(expected_revision) is not int or not 1 <= expected_revision < 2**31 - 1)):
        raise ValidationError("Choose an exact current human content-review revision and request key.")
    _text(reason, 500, required=True)
    _text(execution_note, 500, required=state == "reported")
    if state != "reported" and (executed_at is not None or execution_note):
        raise ValidationError("Manual handoff requires a separate report after exact approval.")
    if state == "reported" and (not isinstance(executed_at, datetime) or timezone.is_naive(executed_at) or executed_at > timezone.now()):
        raise ValidationError("Record the actual aware nonfuture manual handoff time.")
    if review_id is not None:
        try:
            review_id = UUID(str(review_id))
        except (ValueError, TypeError):
            raise ValidationError("Choose a project-owned human content review.") from None
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().filter(pk=project.pk, organization=organization).first()
        if project is None:
            raise PermissionDenied
        evidence = read_content_lifecycle_source(project=project, actor=actor, revision_id=intake.get("content_revision_id"))
        content = ContentRevision.objects.get(project=project, pk=evidence["content"]["revision_id"])
        data = validate_content_lifecycle_intake(intake, project=project, revision=content, evidence=evidence)
        assignee = _assignee(project, assignee_id)
        previous = ContentLifecycleReview.objects.filter(project=project, review_id=review_id).order_by("-revision").first() if review_id else None
        if review_id and previous is None:
            raise PermissionDenied
        existing = ContentLifecycleReview.objects.filter(project=project, request_key=request_key).first()
        if existing:
            if (existing.actor_id != actor.pk or review_id is not None and existing.review_id != review_id
                or existing.revision != (expected_revision + 1 if review_id else 1)
                or ContentLifecycleReview.objects.filter(project=project, review_id=existing.review_id, revision__gt=existing.revision).exists()
                or (existing.intake, existing.source_evidence, existing.assignee_id, existing.state, existing.reason,
                    existing.executed_at, existing.execution_note) != (data, evidence, assignee.pk, state, reason, executed_at, execution_note)):
                raise ValidationError("Request key belongs to another or stale content review.")
            require_current_lifecycle_review(existing, actor=actor)
            return existing
        if previous:
            if previous.revision != expected_revision or state not in TRANSITIONS[previous.state]:
                raise ValidationError("Content review changed; inspect the latest allowed transition.")
            if state not in {"draft", "dismissed"}:
                require_current_lifecycle_review(previous, actor=actor)
            if state != "draft" and (previous.intake, previous.source_evidence, previous.assignee_id) != (data, evidence, assignee.pk):
                raise ValidationError("Changed content/source/judgment/assignee requires a fresh unapproved draft.")
        elif state != "draft":
            raise ValidationError("New quality reviews start as an unapproved human draft.")
        reviewed = approver = approved_at = None
        if state == "approved":
            reviewed, approver, approved_at = previous, actor, timezone.now()
        elif state == "reported":
            reviewed, approver, approved_at = previous.reviewed_revision, previous.approved_by, previous.approved_at
            if executed_at < approved_at:
                raise ValidationError("Manual handoff must follow exact human proposal approval.")
        return ContentLifecycleReview.objects.create(project=project, content_revision=content, actor=actor,
            source_actor=actor if state == "draft" else previous.source_actor, assignee=assignee, review_id=review_id or uuid4(),
            revision=previous.revision + 1 if previous else 1, request_key=request_key, state=state, intake=data,
            source_evidence=evidence, reason=reason, reviewed_revision=reviewed, approved_by=approver, approved_at=approved_at,
            executed_at=executed_at, execution_note=execution_note)
