"""D129 existing-source human authority prospects. No fetch, sending or link inference."""
from datetime import datetime
import json
import re
from urllib.parse import urlsplit

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from config.artifacts import ArtifactNotFound, ArtifactStorageError, ArtifactValidationError
from integrations.google_tokens import GoogleTokenError, _reject_constant, _unique_object
from integrations.oauth import _verified
from tenancy.artifacts import read_project_artifact
from tenancy.models import Project, ProjectConfiguration, normalize_origin
from tenancy.services import Action, require_project_action
from .local_feedback import _text
from .models import Artifact, JobRun, JobStatus, JobStep, SourceCitation
from .research import METHOD as RESEARCH_METHOD, _context, validate_research_input
from .research_sources import MAX_EXCERPT_CHARACTERS, MAX_SOURCE_BYTES, source_url

METHOD = "authority-research-evidence-v1"
POLICY = "authority-human-prospect-v1"
INTAKE_FIELDS = {"policy", "research_job_id", "source_index", "quote", "relevance", "proposed_action",
                 "target_url", "draft_text", "use_permission", "storage_permission", "outreach_permission"}
SOURCE_FIELDS = {"state", "requested_url", "url", "title", "retrieved_at", "sha256", "size_bytes", "excerpt",
                 "excerpt_truncated", "evidence"}


def research_authority_source(*, project, actor, research_job_id, source_index):
    """Read a real collected source and its private readback; text never proves href/rel or outreach permission."""
    if (type(research_job_id) is not int or not 1 <= research_job_id < 2**53
        or type(source_index) is not int or not 0 <= source_index < 5):
        raise ValidationError("Choose an exact stored research source index.")
    project = Project.objects.select_related("organization").filter(pk=project.pk, organization_id=project.organization_id).first()
    if project is None:
        raise PermissionDenied
    require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
    if not _verified(actor):
        raise PermissionDenied
    job = JobRun.objects.filter(project=project, pk=research_job_id, handler="research_topic",
        method_version=RESEARCH_METHOD, status__in=[JobStatus.SUCCEEDED, JobStatus.PARTIALLY_SUCCEEDED]).select_related("actor").first()
    if job is None:
        raise PermissionDenied
    require_project_action(project=project, user=job.actor, action=Action.LAUNCH_JOB)
    if not _verified(job.actor):
        raise PermissionDenied
    validate_research_input(job.input_snapshot)
    if _context(project, job.input_snapshot, job.actor) != job.config_snapshot.get("research_context"):
        raise ValidationError("Research source configuration/intent changed; review new supported evidence.")
    config = ProjectConfiguration.objects.get(project=project)
    output = job.output
    if (type(output) is not dict or output.get("method") != RESEARCH_METHOD or type(output.get("sources")) is not list
        or not 1 <= len(output["sources"]) <= 5 or source_index >= len(job.input_snapshot["source_urls"])):
        raise ValidationError("Research has no bounded stored source collection.")
    selected = [row for row in output["sources"] if type(row) is dict and row.get("index") == source_index]
    if len(selected) != 1:
        raise ValidationError("Select one actual collected source, never an unavailable or duplicate index.")
    source = selected[0]
    if (set(source) != SOURCE_FIELDS | {"index", "artifact_id"} or source["state"] != "collected"
        or type(source["index"]) is not int or type(source["artifact_id"]) is not int or source["artifact_id"] < 1
        or type(source["size_bytes"]) is not int or not 1 <= source["size_bytes"] <= MAX_SOURCE_BYTES
        or type(source["excerpt_truncated"]) is not bool or source["evidence"] != "public_page_text_not_verified_fact"
        or type(source["sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", source["sha256"])):
        raise ValidationError("Select bounded genuine public-page text evidence, not inferred links or facts.")
    for key, limit in (("requested_url", 1024), ("url", 1024), ("title", 240), ("retrieved_at", 64), ("excerpt", MAX_EXCERPT_CHARACTERS)):
        _text(source[key], limit, required=True)
    if (source["requested_url"] != job.input_snapshot["source_urls"][source_index]
        or source_url(source["requested_url"], config) != source["requested_url"]
        or source_url(source["url"], config) != source["url"]
        or normalize_origin("https://" + urlsplit(source["requested_url"]).netloc)
            != normalize_origin("https://" + urlsplit(source["url"]).netloc)):
        raise ValidationError("Source must retain actual currently permitted requested/final HTTPS scope.")
    try:
        retrieved_at = datetime.fromisoformat(source["retrieved_at"])
        if timezone.is_naive(retrieved_at) or retrieved_at > timezone.now():
            raise ValueError
    except ValueError:
        raise ValidationError("Source retrieval time must be an actual aware nonfuture observation.") from None
    step = JobStep.objects.filter(job=job, sequence=source_index + 2, status=JobStep.Status.SUCCEEDED).first()
    if step is None or step.output != {key: value for key, value in source.items() if key != "index"}:
        raise ValidationError("Source no longer matches its actual collected step.")
    if not SourceCitation.objects.filter(job=job, step=step, source_url=source["url"], source_title=source["title"], observed_at=retrieved_at).exists():
        raise ValidationError("Source citation/retrieval provenance is unavailable.")
    artifact = Artifact.objects.filter(pk=source["artifact_id"], job=job, project=project, content_type="application/json").first()
    if artifact is None or not 1 <= artifact.size_bytes <= MAX_SOURCE_BYTES:
        raise ValidationError("Exact private source artifact is unavailable.")
    try:
        content = read_project_artifact(project=project, key=artifact.key)
        if len(content) != artifact.size_bytes:
            raise ValidationError("Private source artifact size changed.")
        stored = json.loads(content, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ArtifactNotFound, ArtifactStorageError, ArtifactValidationError, GoogleTokenError, ValueError, UnicodeError, RecursionError):
        raise ValidationError("Private source evidence cannot be safely read back.") from None
    if type(stored) is not dict or json.dumps(stored, sort_keys=True, allow_nan=False) != json.dumps(
        {key: source[key] for key in SOURCE_FIELDS}, sort_keys=True, allow_nan=False):
        raise ValidationError("Private source artifact differs from its stored collection evidence.")
    return {"method": METHOD, "project_id": project.pk, "research_job_id": job.pk, "source_index": source_index,
        "step_id": step.pk, "artifact_id": artifact.pk, "configuration_revision": config.revision,
        "requested_url": source["requested_url"], "url": source["url"], "title": source["title"],
        "retrieved_at": source["retrieved_at"], "original_response_sha256": source["sha256"], "source_size_bytes": source["size_bytes"],
        "excerpt": source["excerpt"], "excerpt_truncated": source["excerpt_truncated"],
        "coverage": "selected_bounded_public_page_text_only", "facts": "unverified",
        "link_structure": "unavailable_href_rel_not_retained", "inbound_unlinked_lost_links": "not_established",
        "publication_time": None, "outreach_permission": "not_established"}


def validate_prospect_intake(data, *, evidence):
    """Exact scalar human judgment over the stored excerpt; a declaration is not verified permission."""
    if (type(data) is not dict or set(data) != INTAKE_FIELDS or data["policy"] != POLICY
        or type(data["research_job_id"]) is not int or not 1 <= data["research_job_id"] < 2**53
        or type(data["source_index"]) is not int or not 0 <= data["source_index"] < 5
        or type(data["proposed_action"]) is not str or data["proposed_action"] not in {"partnership", "mention", "digital_pr"}
        or data["use_permission"] is not True or data["storage_permission"] is not True
        or type(data["outreach_permission"]) is not bool):
        raise ValidationError("Choose exact human prospect fields and independent use/storage rights.")
    for field, limit, required in (("quote", 1000, True), ("relevance", 500, True),
                                  ("target_url", 1024, True), ("draft_text", 2000, False)):
        _text(data[field], limit, required=required)
    if (type(evidence) is not dict or evidence.get("method") != METHOD
        or (data["research_job_id"], data["source_index"], data["target_url"])
           != (evidence.get("research_job_id"), evidence.get("source_index"), evidence.get("url"))
        or type(evidence.get("excerpt")) is not str or data["quote"] not in evidence["excerpt"]
        or len(json.dumps(data, allow_nan=False).encode()) > 24 * 1024):
        raise ValidationError("Select an exact stored quote and its unchanged source-page target.")
    return dict(data)


def require_current_prospect(row, *, actor=None):
    from .action_review import _assignee
    _assignee(row.project, row.assignee_id)
    actors = [row.source_actor, row.actor]
    if row.reviewed_revision_id:
        actors.extend([row.reviewed_revision.actor, row.approved_by])
    if actor is not None:
        actors.append(actor)
    for user in actors:
        evidence = research_authority_source(project=row.project, actor=user,
            research_job_id=row.research_job_id, source_index=row.source_index)
        if evidence != row.source_evidence:
            raise ValidationError("Source evidence changed; make a new unapproved human draft.")
    validate_prospect_intake(row.intake, evidence=evidence)


def prospect_source_current(row):
    try:
        require_current_prospect(row)
        return True
    except (PermissionDenied, ValidationError):
        return False


def record_authority_prospect(*, project, actor, request_key, intake, assignee_id, state, reason,
                              prospect_id=None, expected_revision=None, executed_at=None, execution_note=""):
    from uuid import UUID, uuid4
    from django.db import transaction
    from tenancy.models import Organization
    from .action_review import _assignee
    from .models import AuthorityProspectReview
    if (type(request_key) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", request_key)
        or type(state) is not str or state not in AuthorityProspectReview.State.values
        or (prospect_id is None) != (expected_revision is None)
        or expected_revision is not None and (type(expected_revision) is not int or not 1 <= expected_revision < 2**31 - 1)
        or type(intake) is not dict):
        raise ValidationError("Choose an exact current prospect revision and request key.")
    _text(reason, 500, required=True)
    _text(execution_note, 500, required=state == "reported")
    if prospect_id is not None:
        try:
            prospect_id = UUID(str(prospect_id))
        except (ValueError, TypeError):
            raise ValidationError("Choose a project-owned prospect.") from None
    if state != "reported" and (executed_at is not None or execution_note):
        raise ValidationError("Execution requires a separate actual manual report.")
    if state == "reported" and (not isinstance(executed_at, datetime) or timezone.is_naive(executed_at)
                               or executed_at > timezone.now()):
        raise ValidationError("Report the actual aware nonfuture manual execution time.")
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().filter(pk=project.pk, organization=organization).first()
        if project is None:
            raise PermissionDenied
        evidence = research_authority_source(project=project, actor=actor,
            research_job_id=intake.get("research_job_id"), source_index=intake.get("source_index"))
        data = validate_prospect_intake(intake, evidence=evidence)
        assignee = _assignee(project, assignee_id)
        previous = None
        if prospect_id is not None:
            previous = AuthorityProspectReview.objects.filter(project=project, prospect_id=prospect_id).order_by("-revision").first()
            if previous is None:
                raise PermissionDenied
        existing = AuthorityProspectReview.objects.filter(project=project, request_key=request_key).first()
        if existing:
            latest = AuthorityProspectReview.objects.filter(project=project, prospect_id=existing.prospect_id).order_by("-revision").first()
            if (latest.pk != existing.pk or existing.actor_id != actor.pk
                or prospect_id is not None and existing.prospect_id != prospect_id
                or existing.revision != (expected_revision + 1 if prospect_id else 1)
                or (existing.intake, existing.source_evidence, existing.assignee_id, existing.state,
                    existing.reason, existing.executed_at, existing.execution_note)
                   != (data, evidence, assignee.pk, state, reason, executed_at, execution_note)):
                raise ValidationError("Request key belongs to another or stale prospect decision.")
            require_current_prospect(existing, actor=actor)
            return existing
        if previous:
            transitions = {"draft": {"draft", "review", "dismissed"}, "review": {"draft", "approved", "dismissed"},
                           "approved": {"draft", "reported", "dismissed"}, "reported": {"draft"}, "dismissed": {"draft"}}
            if previous.revision != expected_revision or state not in transitions[previous.state]:
                raise ValidationError("Prospect changed; inspect latest history and allowed state.")
            if state not in {"draft", "dismissed"}:
                require_current_prospect(previous, actor=actor)
            if state != "draft" and (previous.intake, previous.source_evidence, previous.assignee_id) != (data, evidence, assignee.pk):
                raise ValidationError("Changed source, target, judgment, draft or assignee requires fresh draft review.")
        elif state != "draft":
            raise ValidationError("New prospects start as an unapproved human draft.")
        reviewed = approver = approved_at = None
        if state == "approved":
            reviewed, approver, approved_at = previous, actor, timezone.now()
        elif state == "reported":
            reviewed, approver, approved_at = previous.reviewed_revision, previous.approved_by, previous.approved_at
            if executed_at < approved_at:
                raise ValidationError("Manual execution must follow exact human approval.")
        return AuthorityProspectReview.objects.create(project=project, actor=actor,
            source_actor=actor if state == "draft" else previous.source_actor, assignee=assignee,
            research_job_id=data["research_job_id"], source_index=data["source_index"], source_evidence=evidence,
            intake=data, prospect_id=prospect_id or uuid4(), revision=previous.revision + 1 if previous else 1,
            request_key=request_key, state=state, reason=reason, reviewed_revision=reviewed,
            approved_by=approver, approved_at=approved_at, executed_at=executed_at, execution_note=execution_note)
