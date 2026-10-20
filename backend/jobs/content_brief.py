"""Human-selected structured draft from already collected, quoted source evidence."""
from hashlib import sha256
import json
import re
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.conf import settings
from django.db import transaction

from config.artifacts import ArtifactNotFound, ArtifactStorageError, ArtifactValidationError
from tenancy.artifacts import delete_project_artifact, read_project_artifact, save_project_artifact
from tenancy.customer_artifact_barrier import project_artifact_barrier
from tenancy.models import Organization, Project
from tenancy.models import ProjectConfiguration
from tenancy.services import Action, require_project_action
from .action_review import _opportunity_source, _source
from .models import ActionReview, ContentBriefSnapshot, JobRun, JobStatus
from .research import _context

VERSION = "content-brief-v1"


def create_content_brief(*, project, actor, request_key, research_job_id, action_id,
                         title_options, angle, outline, questions, meta_description="", desired_action=""):
    if (type(request_key) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", request_key)
        or type(research_job_id) is not int or research_job_id < 1
        or type(title_options) is not list or not 1 <= len(title_options) <= 3
        or type(outline) is not list or not 1 <= len(outline) <= 12
        or type(questions) is not list or len(questions) > 10
        or type(angle) is not str or not 1 <= len(angle.strip()) <= 500
        or type(meta_description) is not str or len(meta_description) > 320
        or type(desired_action) is not str or len(desired_action) > 240
        or any(type(value) is not str or not 1 <= len(value.strip()) <= 160 for value in
               [*title_options, *outline, *questions])):
        raise ValidationError("Choose bounded human-authored draft sections and an evidenced action.")
    try:
        action_id = UUID(str(action_id))
    except (ValueError, TypeError):
        raise ValidationError("Choose a current reviewed action.") from None
    with project_artifact_barrier(project.organization_id, shared=True):
        key = None
        try:
            with transaction.atomic():
                organization = Organization.objects.select_for_update().get(pk=project.organization_id)
                project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
                require_project_action(project=project, user=actor, action=Action.LAUNCH_JOB)
                research = JobRun.objects.filter(pk=research_job_id, project=project, handler="research_topic",
                    status__in=[JobStatus.SUCCEEDED, JobStatus.PARTIALLY_SUCCEEDED]).first()
                if research is None:
                    raise PermissionDenied
                evidence = research.output
                if (evidence.get("synthesis_state") != "ai_draft_requires_human_review"
                    or not isinstance(evidence.get("sources"), list) or not evidence["sources"]):
                    raise ValidationError("Select research with collected sources and a reviewable interpretation.")
                try:
                    if _context(project, research.input_snapshot, actor) != research.config_snapshot["research_context"]:
                        raise ValidationError("Project source configuration or mapping changed.")
                except (KeyError, TypeError):
                    raise ValidationError("Research context requires review.") from None
                action = ActionReview.objects.filter(project=project, action_id=action_id).order_by("-revision").first()
                if action is None or action.state not in {"accepted", "in_progress", "implemented", "verified", "outcome_reviewed"}:
                    raise ValidationError("Briefs require a current accepted human action.")
                if action.intent_cluster_id:
                    _source(project, action.intent_cluster_id)
                    if research.input_snapshot["mapping_id"] != action.intent_cluster_id:
                        raise ValidationError("Research and action must use the same reviewed intent mapping.")
                else:
                    _opportunity_source(project, actor, action.opportunity_id, action.action_kind,
                        action.affected_urls[-1] if len(action.affected_urls) == 2 or action.action_kind == "create" else "")
                existing = ContentBriefSnapshot.objects.filter(project=project, request_key=request_key).first()
                if existing:
                    if existing.actor_id != actor.pk or existing.research_job_id != research.pk or existing.action_review_id != action.pk:
                        raise ValidationError("Brief request key belongs to another revision.")
                    data = read_content_brief(project=project, actor=actor, brief=existing)
                    if (data["title_options"], data["angle"], data["outline"], data["questions"],
                        data.get("meta_description", ""), data.get("desired_action", "")) != (
                        title_options, angle.strip(), outline, questions, meta_description.strip(), desired_action.strip()):
                        raise ValidationError("Brief request key belongs to another draft.")
                    return existing
                sources = [{key: source[key] for key in ("index", "state", "requested_url", "url", "title",
                    "retrieved_at", "sha256", "size_bytes", "excerpt_truncated") if key in source}
                    for source in evidence["sources"]]
                if not any(row["state"] == "collected" for row in sources):
                    raise ValidationError("Research contains no collected source evidence.")
                synthesis = evidence["synthesis"]
                config = ProjectConfiguration.objects.get(project=project)
                data = {"version": VERSION, "project_id": project.pk, "research_job_id": research.pk,
                    "action_review_id": action.pk, "action_id": str(action.action_id), "action_revision": action.revision,
                    "scope": "human_authored_structure_and_unverified_ai_interpretation_not_publication",
                    "topic": research.input_snapshot["topic"], "market": research.config_snapshot["research_context"]["market"],
                    "language": research.input_snapshot["language"], "intent": action.intent_cluster.intent if action.intent_cluster_id else "unknown",
                    "audience": research.config_snapshot["research_context"]["audience"] or "unknown_not_entered",
                    "business_goal": config.business_goal or "unknown_not_entered",
                    "desired_action": desired_action.strip(), "meta_description": meta_description.strip(),
                    "page_kind": action.intent_cluster.page_kind if action.intent_cluster_id else "human_selected_action_page",
                    "affected_pages": action.affected_urls, "action_kind": action.action_kind,
                    "acceptance_criteria": action.acceptance_criteria, "title_options": title_options,
                    "angle": angle.strip(), "outline": outline, "questions": questions,
                    "relevant_internal_links": action.affected_urls, "structured_data_suggestion": "none_without_fact_review",
                    "research_summary_to_verify": synthesis["summary"], "claims_to_verify": synthesis["claims"],
                    "sources": sources, "source_coverage": evidence["coverage"],
                    "missing_competitor_evidence": "unknown_unless_selected_sources_support_it",
                    "content_gap_evidence": "not_established_by_selected_excerpts",
                    "approval": "draft_human_review_required_no_site_change"}
                try:
                    content = json.dumps(data, ensure_ascii=False, sort_keys=True, allow_nan=False,
                                         separators=(",", ":")).encode()
                except (TypeError, ValueError, RecursionError):
                    raise ValidationError("Brief evidence is unavailable.") from None
                if len(content) > min(65536, settings.ARTIFACT_MAX_BYTES):
                    raise ValidationError("Brief exceeds the private size ceiling.")
                key = save_project_artifact(project=project, content=content, content_type="application/json")
                return ContentBriefSnapshot.objects.create(project=project, research_job=research,
                    action_review=action, actor=actor, request_key=request_key, artifact_key=key,
                    content_sha256=sha256(content).hexdigest(), size_bytes=len(content))
        except Exception as exc:
            if key:
                try:
                    delete_project_artifact(project=project, key=key)
                except ArtifactStorageError:
                    pass  # Exact-project orphan is swept by the existing retention runner.
            if isinstance(exc, (ArtifactStorageError, ArtifactValidationError)):
                raise ValidationError("Private brief storage is unavailable.") from None
            raise


def read_content_brief_bytes(*, project, actor, brief):
    project = Project.objects.get(pk=project.pk, organization_id=project.organization_id)
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    if brief.project_id != project.pk or not ContentBriefSnapshot.objects.filter(pk=brief.pk, project=project).exists():
        raise PermissionDenied
    try:
        content = read_project_artifact(project=project, key=brief.artifact_key)
    except (ArtifactNotFound, ArtifactStorageError, ArtifactValidationError):
        raise ValidationError("Private brief is unavailable.") from None
    if len(content) != brief.size_bytes or sha256(content).hexdigest() != brief.content_sha256:
        raise ValidationError("Private brief integrity check failed.")
    return content


def read_content_brief(*, project, actor, brief):
    try:
        body = json.loads(read_content_brief_bytes(project=project, actor=actor, brief=brief))
    except (ValueError, UnicodeError, RecursionError):
        raise ValidationError("Private brief content is unavailable.") from None
    if type(body) is not dict or body.get("version") != VERSION or body.get("project_id") != project.pk:
        raise ValidationError("Private brief content is unavailable.")
    return body
