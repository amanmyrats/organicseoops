"""D145 current action evidence and D147 explicit subjective usefulness acknowledgment."""
import hashlib
import json
import re
from datetime import datetime, timedelta

from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.utils import timezone

from config.artifacts import ArtifactNotFound, ArtifactStorageError, ArtifactValidationError
from integrations.oauth import _verified
from tenancy.artifacts import project_artifact_scope, read_project_artifact
from tenancy.models import Organization, Project, ProjectConfiguration
from tenancy.services import Action, require_project_action
from .action_review import _assignee, _opportunity_source
from .crawler import FIRST_AUDIT_ENTRYPOINT, PageParser
from .crawling import CrawlScope
from .diagnostics import METHOD_VERSION, RULESET_VERSION, _coverage, _input_hash
from .findings import TECHNICAL_METHOD
from .first_audit_evidence import _dates, completion_source_digest, first_audit_completion_source
from .models import ActionReview, CrawlPageSnapshot, CrawlRun, FirstAuditValueAcknowledgment, JobStatus, RenderedPageSnapshot

METHOD = "bounded-audit-human-action-source-v1"
ACK_METHOD = "bounded-audit-usefulness-ack-v1"
ACK_SALT = "jobs.bounded-audit-usefulness-proof-v1"
ACK_MAX_AGE = 300
ACK_INTERPRETATION = "explicit_subjective_useful_next_action_not_implementation_or_seo_outcome"


def _decision_digest(finding, review, action, proposal):
    # Freeze exact decisions; notes and URLs never leave the resolver.
    return completion_source_digest({"finding": finding.evidence, "review": [review.pk, review.actor_id,
        review.revision, review.priority, review.estimated_effort, review.business_relevance, review.review_reason],
        "action": [action.pk, action.actor_id, str(action.action_id), action.revision, action.assignee_id,
            action.action_kind, action.affected_urls, action.acceptance_criteria, action.reason],
        "proposal": [proposal.pk, proposal.actor_id, proposal.reason]})


def _current_action_source(*, project, actor, job_id, action_review_id):
    project = Project.objects.select_related("organization").filter(pk=project.pk,
        organization_id=project.organization_id).first()
    if project is None:
        raise PermissionDenied
    audit = first_audit_completion_source(project=project, actor=actor, job_id=job_id)
    action = ActionReview.objects.select_related("opportunity__finding__source_diagnostics__crawl_run",
        "actor").filter(pk=action_review_id, project=project, state="accepted", intent_cluster__isnull=True).first()
    if action is None:
        raise ValidationError("Choose one actual accepted audit-backed action.")
    latest = ActionReview.objects.filter(project=project, action_id=action.action_id).order_by("-revision").first()
    proposal = ActionReview.objects.select_related("actor").filter(project=project, action_id=action.action_id,
        revision=action.revision - 1, state="proposed").first()
    if (latest.pk != action.pk or proposal is None or proposal.opportunity_id != action.opportunity_id
        or any(getattr(proposal, field) != getattr(action, field) for field in (
            "assignee_id", "action_kind", "affected_urls", "acceptance_criteria"))):
        raise ValidationError("Acceptance needs its unchanged latest actual proposal.")
    if (type(action.affected_urls) is not list or not 1 <= len(action.affected_urls) <= 2
        or any(type(url) is not str for url in action.affected_urls)):
        raise ValidationError("Accepted action needs bounded exact project pages.")
    review, urls = _opportunity_source(project, actor, action.opportunity_id, action.action_kind,
        action.affected_urls[-1] if len(action.affected_urls) == 2 or action.action_kind == "create" else "")
    if urls != action.affected_urls:
        raise ValidationError("Accepted action page scope changed.")
    finding = review.finding
    source = finding.source_diagnostics
    if source is None or finding.method_version != TECHNICAL_METHOD:
        raise ValidationError("This source does not bind raw crawl metadata.")
    run = source.crawl_run
    scope = CrawlScope.for_project(project)
    pages = list(run.pages.select_related("raw_artifact").order_by("observed_at", "id")[:6])
    if (source.project_id != project.pk or run.job_id != job_id or source.method_version != METHOD_VERSION
        or source.ruleset_version != RULESET_VERSION or run.pk != audit["crawl_run_id"]
        or RenderedPageSnapshot.objects.filter(crawl_page__crawl_run=run).exists()
        or source.input_hash != _input_hash(run, pages, {}, scope)
        or type(source.output) is not dict or source.output.get("coverage") != _coverage(run, pages)):
        raise ValidationError("Choose unchanged same-run raw diagnostics evidence.")
    for original, permission in ((finding.actor, Action.MANAGE_PROJECT), (review.actor, Action.MANAGE_PROJECT),
                                 (proposal.actor, Action.APPROVE), (action.actor, Action.APPROVE)):
        require_project_action(project=project, user=original, action=permission)
        if not _verified(original):
            raise PermissionDenied
    assignee = _assignee(project, action.assignee_id)
    if not _verified(assignee):
        raise PermissionDenied
    details = finding.evidence.get("details") if type(finding.evidence) is dict else None
    page = next((page for page in pages if type(details) is dict and page.pk == details.get("crawl_page_id")), None)
    if (page is None or page.raw_artifact is None or page.reused_from_id is not None or page.status_code != 200
        or page.requested_url != page.final_url or finding.subject != page.final_url):
        raise ValidationError("Choose actual same-job nonredirected successful raw HTML metadata.")
    field = details.get("field")
    if type(field) is not str or field not in {"title", "meta_description"}:
        raise ValidationError("Only actual raw title/description candidates bind this initial source.")
    minimum, maximum = (15, 70) if field == "title" else (50, 160)
    value = getattr(page, field)
    size = len(value.strip())
    rule = "missing" if not size else "short" if size < minimum else "excessive" if size > maximum else None
    expected = {"snapshot_id": source.pk, "crawl_run_id": run.pk, "diagnostics_method": source.method_version,
        "details": {"source": "raw_crawl", "crawl_page_id": page.pk, "observed_at": page.observed_at.isoformat(),
            "status_code": 200, "coverage": source.output["coverage"]["state"], "field": field,
            "character_count": size, "thresholds": {"minimum": minimum, "maximum": maximum},
            "interpretation": "review_candidate_not_search_snippet_prediction"}}
    fingerprint = hashlib.sha256(json.dumps([TECHNICAL_METHOD, "source_diagnostics", source.pk,
        finding.detector, finding.subject, f"page:{page.pk}"], separators=(",", ":")).encode()).hexdigest()
    if (rule is None or finding.detector != f"raw_{field}_{rule}_candidate" or finding.evidence != expected
        or finding.fingerprint != fingerprint or finding.confidence != "candidate_source_limited"
        or not action.reason.strip() or not proposal.reason.strip() or not action.acceptance_criteria.strip()):
        raise ValidationError("Actual metadata candidate and human decision need unchanged evidence.")
    _dates(run.completed_at, source.observed_at, finding.detected_at, review.created_at,
           proposal.created_at, action.created_at)
    result = {"method": METHOD, "organization_id": project.organization_id, "project_id": project.pk,
        "job_id": job_id, "audit_source_digest": completion_source_digest(audit),
        "audit_completed_at": audit["run_completed_at"], "diagnostics_id": source.pk,
        "diagnostics_observed_at": source.observed_at.isoformat(), "finding_id": finding.pk,
        "finding_detected_at": finding.detected_at.isoformat(), "detector": finding.detector,
        "opportunity_id": review.pk, "opportunity_reviewed_at": review.created_at.isoformat(),
        "action_review_id": action.pk, "action_accepted_at": action.created_at.isoformat(),
        "action_kind": action.action_kind, "decision_digest": _decision_digest(finding, review, action, proposal),
        "page_sha256": page.content_hash, "coverage": audit["coverage"],
        "first_value": "not_established", "first_ever_occurrence": "not_established"}
    return project, result, page.raw_artifact, field, value


def first_audit_action_source(*, project, actor, job_id, action_review_id):
    """Inspect actual current source/acceptance with no writes, fetching, new approval or first-value claim."""
    if any(type(value) is not int or not 1 <= value < 2**53 for value in (job_id, action_review_id)):
        raise ValidationError("Choose exact stored audit and accepted action review IDs.")
    project, result, artifact, field, value = _current_action_source(project=project, actor=actor,
        job_id=job_id, action_review_id=action_review_id)
    try:
        body = read_project_artifact(project=project, key=artifact.key)
        if len(body) != artifact.size_bytes or hashlib.sha256(body).hexdigest() != result["page_sha256"]:
            raise ValueError
        parser = PageParser()
        parser.feed(body.decode("utf-8", errors="strict"))
        parsed, _discovered = parser.result(base_url=project.canonical_origin + "/", scope=CrawlScope.for_project(project))
        if parsed[field] != value:
            raise ValueError
    except (ArtifactNotFound, ArtifactStorageError, ArtifactValidationError, UnicodeError, ValueError, RecursionError):
        raise ValidationError("Stored raw UTF-8 metadata proof is unavailable or changed.") from None
    _project, current, current_artifact, current_field, current_value = _current_action_source(project=project,
        actor=actor, job_id=job_id, action_review_id=action_review_id)
    if (current != result or (current_artifact.pk, current_artifact.key, current_artifact.size_bytes,
        current_field, current_value) != (artifact.pk, artifact.key, artifact.size_bytes, field, value)):
        raise ValidationError("Current audit/action source changed during private inspection.")
    return result


def first_value_acknowledgment_source(*, project, actor, job_id, action_review_id):
    """Current source eligible for an explicit human declaration; not a saved declaration or first value."""
    evidence = first_audit_action_source(project=project, actor=actor, job_id=job_id, action_review_id=action_review_id)
    require_project_action(project=project, user=actor, action=Action.APPROVE)
    if not _verified(actor):
        raise PermissionDenied
    return {"method": ACK_METHOD, "acknowledging_actor_id": actor.pk, "evidence": evidence,
        "interpretation": ACK_INTERPRETATION}


def first_value_acknowledgment_challenge(*, project, actor, job_id, action_review_id):
    source = first_value_acknowledgment_source(project=project, actor=actor, job_id=job_id, action_review_id=action_review_id)
    issued_at = timezone.now()
    proof = signing.dumps({"method": ACK_METHOD, "source": source, "issued_at": issued_at.isoformat()}, salt=ACK_SALT)
    if len(proof) > 4096:
        raise ValidationError("Bounded usefulness source proof exceeds its private limit.")
    return {"method": ACK_METHOD, "source": source, "source_digest": completion_source_digest(source),
        "receipt_proof": proof, "expires_at": (issued_at + timedelta(seconds=ACK_MAX_AGE)).isoformat(),
        "acknowledgment_recorded": False}


def validate_first_value_acknowledgment_proof(*, project, actor, job_id, action_review_id, proof,
                                            acknowledge_useful_next_action):
    """Read-only validation for the later atomic capture owner; repeated validation records nothing."""
    if (acknowledge_useful_next_action is not True or type(proof) is not str
        or not 1 <= len(proof) <= 4096 or not re.fullmatch(r"[A-Za-z0-9_:-]+", proof)):
        raise ValidationError("Explicitly acknowledge one bounded current usefulness proof.")
    try:
        payload = signing.loads(proof, salt=ACK_SALT, max_age=ACK_MAX_AGE)
        if (type(payload) is not dict or set(payload) != {"method", "source", "issued_at"}
            or payload["method"] != ACK_METHOD or type(payload["source"]) is not dict
            or type(payload["issued_at"]) is not str):
            raise ValueError
        issued_at = datetime.fromisoformat(payload["issued_at"])
        if timezone.is_naive(issued_at) or not timedelta(0) <= timezone.now() - issued_at <= timedelta(seconds=ACK_MAX_AGE):
            raise ValueError
    except (signing.BadSignature, ValueError, TypeError, UnicodeError, OverflowError):
        raise ValidationError("Usefulness proof is invalid, wrong-purpose or expired.") from None
    source = first_value_acknowledgment_source(project=project, actor=actor, job_id=job_id, action_review_id=action_review_id)
    if payload["source"] != source:
        raise ValidationError("Current actor or exact audit/action usefulness source changed.")
    _dates(datetime.fromisoformat(source["evidence"]["action_accepted_at"]), issued_at)
    # Private source reads can be slow: expire at the final validation, too.
    try:
        signing.loads(proof, salt=ACK_SALT, max_age=ACK_MAX_AGE)
    except signing.BadSignature:
        raise ValidationError("Usefulness proof expired during current source inspection.") from None
    if not timedelta(0) <= timezone.now() - issued_at <= timedelta(seconds=ACK_MAX_AGE):
        raise ValidationError("Usefulness proof expired during current source inspection.")
    return source


def validate_first_value_capture(record):
    """Model guard: only the owning current-proof transaction may insert original server-time history."""
    original = getattr(record, "_first_value_capture", None)
    if not connection.in_atomic_block or type(original) is not tuple or len(original) != 3:
        raise ValidationError("Usefulness capture requires its original atomic explicit proof.")
    proof, flag, acknowledged_at = original
    organization = Organization.objects.select_for_update().get(pk=record.organization_id)
    if organization.first_value_tracking != ACK_METHOD:
        raise ValidationError("First usefulness acknowledgment has unknown prospective tracking coverage.")
    source = validate_first_value_acknowledgment_proof(project=record.project, actor=record.actor,
        job_id=record.job_id, action_review_id=record.action_review_id, proof=proof,
        acknowledge_useful_next_action=flag)
    expected = {"method": ACK_METHOD, "tracking_started_at": organization.created_at.isoformat(),
                "acknowledged_at": acknowledged_at.isoformat(), "declaration": source}
    if (record.project.organization_id != organization.pk or record.job.organization_id != organization.pk
        or record.job.project_id != record.project_id or record.action_review.project_id != record.project_id
        or record.acknowledged_at != acknowledged_at or record.source != expected
        or record.source_digest != completion_source_digest(expected)):
        raise ValidationError("Usefulness acknowledgment must retain its exact original scoped source.")
    _dates(organization.created_at, record.job.created_at,
           datetime.fromisoformat(source["evidence"]["action_accepted_at"]), acknowledged_at)


def acknowledge_first_audit_value(*, project, actor, job_id, action_review_id, proof, acknowledge_useful_next_action):
    """Org-first atomic explicit capture; no challenge/approval/history read can call it implicitly."""
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().filter(pk=project.pk, organization=organization).first()
        if project is None:
            raise PermissionDenied
        source = validate_first_value_acknowledgment_proof(project=project, actor=actor, job_id=job_id,
            action_review_id=action_review_id, proof=proof, acknowledge_useful_next_action=acknowledge_useful_next_action)
        if organization.first_value_tracking != ACK_METHOD:
            raise ValidationError("First usefulness acknowledgment has unknown prospective tracking coverage.")
        saved = FirstAuditValueAcknowledgment.objects.filter(organization=organization).first()
        if saved is not None:
            if (saved.project_id != project.pk or saved.job_id != job_id or saved.action_review_id != action_review_id
                or saved.actor_id != actor.pk or type(saved.source) is not dict
                or saved.source != {"method": ACK_METHOD, "tracking_started_at": organization.created_at.isoformat(),
                    "acknowledged_at": saved.acknowledged_at.isoformat(), "declaration": source}
                or saved.source_digest != completion_source_digest(saved.source)):
                raise ValidationError("First usefulness acknowledgment is already recorded for another exact source.")
            _dates(organization.created_at, datetime.fromisoformat(source["evidence"]["action_accepted_at"]), saved.acknowledged_at)
            return saved
        acknowledged_at = timezone.now()
        captured = {"method": ACK_METHOD, "tracking_started_at": organization.created_at.isoformat(),
                    "acknowledged_at": acknowledged_at.isoformat(), "declaration": source}
        saved = FirstAuditValueAcknowledgment(organization=organization, project=project, job_id=job_id,
            action_review_id=action_review_id, actor=actor, acknowledged_at=acknowledged_at,
            source=captured, source_digest=completion_source_digest(captured))
        saved._first_value_capture = (proof, acknowledge_useful_next_action, acknowledged_at)
        try:
            saved.save()
        finally:
            del saved._first_value_capture
        return saved


def _historical_value_acknowledgment(*, project, actor):
    project = Project.objects.select_related("organization").filter(pk=project.pk, organization_id=project.organization_id).first()
    if project is None:
        raise PermissionDenied
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    if ProjectConfiguration.objects.filter(project=project, source_choice="synthetic_demo").exists():
        raise ValidationError("Inspect actual usefulness history separately from synthetic demo.")
    base = {"method": ACK_METHOD, "organization_id": project.organization_id, "project_id": project.pk,
            "interpretation": ACK_INTERPRETATION, "scope": "historical_organization_first_acknowledgment_within_selected_project_not_current_source_use"}
    saved = FirstAuditValueAcknowledgment.objects.select_related("job__crawl_run",
        "action_review__opportunity__finding__source_diagnostics").filter(project=project, organization=project.organization).first()
    if saved is None:
        return project, {**base, "state": "not_observed_for_project" if project.organization.first_value_tracking == ACK_METHOD else "unknown"}, None
    try:
        job, run, action = saved.job, saved.job.crawl_run, saved.action_review
        review, finding = action.opportunity, action.opportunity.finding
        diagnostics = finding.source_diagnostics
        proposal = ActionReview.objects.get(project=project, action_id=action.action_id, revision=action.revision - 1, state="proposed")
        original = saved.source["declaration"]["evidence"]
        page = CrawlPageSnapshot.objects.select_related("raw_artifact").get(crawl_run=run, project=project,
            pk=finding.evidence["details"]["crawl_page_id"])
        artifact = page.raw_artifact
        field = finding.evidence["details"]["field"]
        if (saved.source_digest != completion_source_digest(saved.source) or job.project_id != project.pk
            or job.organization_id != project.organization_id or job.status != JobStatus.SUCCEEDED
            or job.handler != "crawl_site" or job.error_category
            or job.config_snapshot.get("first_audit_entrypoint") != FIRST_AUDIT_ENTRYPOINT
            or run.project_id != project.pk or run.organization_id != project.organization_id
            or action.project_id != project.pk or action.state != "accepted" or action.intent_cluster_id is not None
            or review.project_id != project.pk or finding.project_id != project.pk
            or diagnostics.project_id != project.pk or diagnostics.crawl_run_id != run.pk
            or diagnostics.method_version != METHOD_VERSION or diagnostics.ruleset_version != RULESET_VERSION
            or finding.method_version != TECHNICAL_METHOD
            or proposal.opportunity_id != action.opportunity_id
            or any(getattr(proposal, name) != getattr(action, name) for name in (
                "assignee_id", "action_kind", "affected_urls", "acceptance_criteria"))
            or field not in {"title", "meta_description"} or page.status_code != 200 or page.reused_from_id is not None
            or finding.detector not in {f"raw_{field}_{rule}_candidate" for rule in ("missing", "short", "excessive")}
            or artifact.project_id != project.pk or artifact.job_id != job.pk or artifact.content_type != "text/html"
            or not 1 <= artifact.size_bytes <= 2 * 1024 * 1024
            or artifact.key != f"{project_artifact_scope(project)}/jobs/{job.pk}/{page.content_hash[:32]}.html"
            or not re.fullmatch(r"[a-f0-9]{64}", original["audit_source_digest"])):
            raise ValueError
        evidence = {"method": METHOD, "organization_id": project.organization_id, "project_id": project.pk,
            "job_id": job.pk, "audit_source_digest": original["audit_source_digest"],
            "audit_completed_at": run.completed_at.isoformat(), "diagnostics_id": diagnostics.pk,
            "diagnostics_observed_at": diagnostics.observed_at.isoformat(), "finding_id": finding.pk,
            "finding_detected_at": finding.detected_at.isoformat(), "detector": finding.detector,
            "opportunity_id": review.pk, "opportunity_reviewed_at": review.created_at.isoformat(),
            "action_review_id": action.pk, "action_accepted_at": action.created_at.isoformat(),
            "action_kind": action.action_kind, "decision_digest": _decision_digest(finding, review, action, proposal),
            "page_sha256": page.content_hash, "coverage": "bounded_discovered_http_sample_not_complete_site",
            "first_value": "not_established", "first_ever_occurrence": "not_established"}
        expected = {"method": ACK_METHOD, "tracking_started_at": project.organization.created_at.isoformat(),
            "acknowledged_at": saved.acknowledged_at.isoformat(), "declaration": {"method": ACK_METHOD,
                "acknowledging_actor_id": saved.actor_id, "evidence": evidence, "interpretation": ACK_INTERPRETATION}}
        if saved.source != expected:
            raise ValueError
        _dates(project.organization.created_at, job.created_at, run.completed_at, diagnostics.observed_at,
               finding.detected_at, review.created_at, proposal.created_at, action.created_at, saved.acknowledged_at)
    except (KeyError, TypeError, ValueError, AttributeError, ActionReview.DoesNotExist, CrawlRun.DoesNotExist, CrawlPageSnapshot.DoesNotExist):
        raise ValidationError("Historical usefulness declaration evidence needs review.") from None
    return project, {**base, "state": "recorded", "acknowledged_at": saved.acknowledged_at.isoformat(),
        "tracking_started_at": project.organization.created_at.isoformat(), "source_digest": saved.source_digest,
        "declaration_digest": completion_source_digest(saved.source["declaration"]),
        "action_id": str(action.action_id), "revision": action.revision, "source": evidence}, (
            artifact.key, artifact.size_bytes, page.content_hash, field, getattr(page, field), page.final_url)


def inspect_first_audit_value(*, project, actor):
    """Read a retained declaration under current read authority; never resurrect source/approval authority."""
    project, result, artifact = _historical_value_acknowledgment(project=project, actor=actor)
    if artifact is not None:
        key, size, digest, field, value, base_url = artifact
        try:
            body = read_project_artifact(project=project, key=key)
            if len(body) != size or hashlib.sha256(body).hexdigest() != digest:
                raise ValueError
            parser = PageParser()
            parser.feed(body.decode("utf-8", errors="strict"))
            parsed, _discovered = parser.result(base_url=base_url, scope=CrawlScope.for_project(project))
            if parsed[field] != value:
                raise ValueError
        except (ArtifactNotFound, ArtifactStorageError, ArtifactValidationError, UnicodeError, ValueError, RecursionError):
            raise ValidationError("Historical private raw metadata proof is unavailable or changed.") from None
    _project, current, current_artifact = _historical_value_acknowledgment(project=project, actor=actor)
    if current != result or current_artifact != artifact:
        raise ValidationError("Historical usefulness declaration changed during private inspection.")
    return result


def inspect_first_audit_value_timing(*, project, actor):
    """Organization age at its retained declaration, not work duration or actual time-to-business-value."""
    history = inspect_first_audit_value(project=project, actor=actor)
    result = {"method": "bounded-audit-usefulness-timing-v1", "organization_id": project.organization_id,
        "project_id": project.pk, "state": history["state"],
        "interpretation": "organization_age_at_first_server_subjective_ack_not_business_value_time",
        "precision": "whole_milliseconds_rounded_down"}
    if history["state"] == "recorded":
        started = datetime.fromisoformat(history["tracking_started_at"])
        acknowledged = datetime.fromisoformat(history["acknowledged_at"])
        _dates(started, acknowledged)
        result.update(tracking_started_at=history["tracking_started_at"], acknowledged_at=history["acknowledged_at"],
            source_digest=history["source_digest"], elapsed_milliseconds=(acknowledged - started) // timedelta(milliseconds=1))
    return result
