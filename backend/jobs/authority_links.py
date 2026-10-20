"""D130 immutable human link reviews and separate stored own-target HTTP evidence. No network."""
from datetime import datetime
from hashlib import sha256
import json
import re
from urllib.parse import urlsplit

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from config.artifacts import ArtifactNotFound, ArtifactStorageError, ArtifactValidationError
from integrations.oauth import _verified
from tenancy.artifacts import project_artifact_scope, read_project_artifact
from tenancy.models import Project, ProjectConfiguration, normalize_origin
from tenancy.services import Action, require_passive_security_scope, require_project_action
from .crawler import METHOD_VERSION as CRAWL_METHOD, HOST_DELAY_SECONDS, project_url_parameter_policy, snapshotted_url_parameter_policy, validate_crawl_input
from .local_feedback import _text, validate_owned_website_url
from .models import CrawlPageSnapshot, JobCancellation, JobStatus

POLICY = "authority-human-link-v1"
SOURCE = "customer_manual_link_observation"
METHOD = "authority-own-target-http-v1"
MAX_BYTES = 16 * 1024
FIELDS = {"policy", "source_kind", "configuration_revision", "origin", "crawl_page_id", "observation_reference",
    "source_url", "target_url", "observed_at", "status", "coverage", "surface", "href", "anchor_text", "rel",
    "evidence_note", "use_permission", "storage_permission", "not_restricted_provider_copy", "no_personal_payload"}


def validate_link_intake(data, *, as_of=None):
    """Preserve original scalar human claims; caller must resolve actual current scope and authority."""
    as_of = timezone.now() if as_of is None else as_of
    if (not isinstance(as_of, datetime) or timezone.is_naive(as_of)
        or type(data) is not dict or set(data) != FIELDS or data["policy"] != POLICY or data["source_kind"] != SOURCE
        or type(data["configuration_revision"]) is not int or not 0 <= data["configuration_revision"] < 2**31
        or type(data["crawl_page_id"]) is not int or not 1 <= data["crawl_page_id"] < 2**53
        or any(data[field] is not True for field in
            ("use_permission", "storage_permission", "not_restricted_provider_copy", "no_personal_payload"))):
        raise ValidationError("Choose exact independent human link-report fields, current scope and affirmative rights.")
    for field, limit, required in (("origin", 512, True), ("observation_reference", 64, True),
        ("source_url", 1024, True), ("target_url", 1024, True), ("observed_at", 64, True),
        ("status", 32, True), ("coverage", 40, True), ("surface", 24, True),
        ("href", 1024, False), ("anchor_text", 240, False), ("rel", 100, False), ("evidence_note", 500, True)):
        _text(data[field], limit, required=required)
    validate_owned_website_url(data["target_url"], approved_origin=data["origin"])
    try:
        parts = urlsplit(data["source_url"])
        source_origin = normalize_origin(parts.scheme + "://" + parts.netloc)
        validate_owned_website_url(data["source_url"], approved_origin=source_origin)
        if (parts.port not in {None, 443} or source_origin == data["origin"]
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", data["observation_reference"])):
            raise ValueError
    except (ValueError, TypeError):
        raise ValidationError("Choose an original external HTTPS source URL and opaque observation reference.") from None
    if (data["surface"] not in {"html_document", "rendered_document", "unknown"}
        or data["coverage"] not in {"partial_page", "complete_document_customer_reported", "unavailable"}):
        raise ValidationError("Declare actual inspected document surface and human-reported coverage.")
    if data["status"] == "observed":
        if (data["href"] != data["target_url"] or data["coverage"] == "unavailable" or data["surface"] == "unknown"):
            raise ValidationError("Observed links require the unchanged literal absolute own-target href and inspected document.")
    elif data["status"] in {"not_seen_in_inspected_page", "unavailable"}:
        if (data["href"] or data["anchor_text"] or data["rel"]
            or data["status"] == "not_seen_in_inspected_page" and (data["coverage"] == "unavailable" or data["surface"] == "unknown")
            or data["status"] == "unavailable" and (data["coverage"] != "unavailable" or data["surface"] != "unknown")):
            raise ValidationError("Absence/unavailability has no reported href, anchor or rel; never infer lost/unlinked links.")
    else:
        raise ValidationError("Choose observed, partial not-seen or unavailable; independently verified link loss is unsupported.")
    try:
        observed = datetime.fromisoformat(data["observed_at"])
        if timezone.is_naive(observed) or observed > as_of or len(json.dumps(data, allow_nan=False).encode()) > MAX_BYTES:
            raise ValueError
    except (ValueError, TypeError, UnicodeError):
        raise ValidationError("Use an aware nonfuture observation date and bounded serialized scalar evidence.") from None
    return dict(data)


def _check_target_page(page, *, project, target_url, origin, as_of):
    run, job = page.crawl_run, page.crawl_run.job
    if (page.project_id != project.pk or run.project_id != project.pk or run.organization_id != project.organization_id
        or job.project_id != project.pk or job.organization_id != project.organization_id
        or job.handler != "crawl_site" or job.method_version != CRAWL_METHOD
        or job.status not in {JobStatus.SUCCEEDED, JobStatus.PARTIALLY_SUCCEEDED}
        or run.completed_at is None or not job.created_at <= run.started_at <= page.observed_at <= run.completed_at <= as_of
        or page.requested_url != target_url or JobCancellation.objects.filter(job=job).exists()):
        raise ValidationError("Choose an actual exact-target completed same-project HTTP crawl observation.")
    require_project_action(project=project, user=job.actor, action=Action.LAUNCH_JOB)
    if not _verified(job.actor):
        raise PermissionDenied
    validate_crawl_input(job.input_snapshot)
    _configured, policy = snapshotted_url_parameter_policy(job)
    if (policy != project_url_parameter_policy(project) or job.config_snapshot.get("host_delay_seconds") != HOST_DELAY_SECONDS
        or run.page_limit != job.input_snapshot["page_limit"]):
        raise ValidationError("Crawl parameter configuration changed; choose current supported target evidence.")
    if (type(page.redirect_chain) is not list or len(page.redirect_chain) > 5
        or page.status_code is not None and (type(page.status_code) is not int or not 100 <= page.status_code <= 599)
        or type(page.content_hash) is not str or page.content_hash and not re.fullmatch(r"[0-9a-f]{64}", page.content_hash)):
        raise ValidationError("Retain actual bounded HTTP status, redirect and body-digest evidence.")
    validate_owned_website_url(page.requested_url, approved_origin=origin)
    if page.final_url:
        validate_owned_website_url(page.final_url, approved_origin=origin)
    elif not page.error_category:
        raise ValidationError("Successful HTTP observations need their actual final URL.")
    for hop in page.redirect_chain:
        if (type(hop) is not dict or set(hop) != {"url", "status"} or type(hop["status"]) is not int
            or hop["status"] not in {301, 302, 303, 307, 308}):
            raise ValidationError("Retain original scoped HTTP redirect hops.")
        validate_owned_website_url(hop["url"], approved_origin=origin)
    if not page.error_category and (page.status_code is None or not page.content_hash):
        raise ValidationError("Successful HTTP observations need original status and body digest.")


def own_target_evidence(*, project, actor, intake):
    """Read actual dated own-target evidence, never independently verify the external human report."""
    project = Project.objects.filter(pk=project.pk, organization_id=project.organization_id).first()
    if project is None:
        raise PermissionDenied
    data = validate_link_intake(intake)
    own_hosts = {urlsplit(value).hostname for value in [project.canonical_origin, *project.domain_aliases.values_list("origin", flat=True)]}
    if urlsplit(data["source_url"]).hostname in own_hosts:
        raise ValidationError("An own-project/alias link is not an external inbound source.")
    verification, target = own_target_crawl_evidence(project=project, actor=actor, origin=data["origin"],
        configuration_revision=data["configuration_revision"], crawl_page_id=data["crawl_page_id"], target_url=data["target_url"])
    return verification, data, target


def own_target_crawl_evidence(*, project, actor, origin, configuration_revision, crawl_page_id, target_url):
    """Current actual destination candidate, without inventing an external report or rights declaration."""
    project = Project.objects.select_related("organization").filter(pk=project.pk, organization_id=project.organization_id).first()
    if project is None or not _verified(actor):
        raise PermissionDenied
    require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
    if (type(configuration_revision) is not int or not 0 <= configuration_revision < 2**31
        or type(crawl_page_id) is not int or not 1 <= crawl_page_id < 2**53):
        raise ValidationError("Choose an actual current configuration and target crawl page.")
    validate_owned_website_url(target_url, approved_origin=origin)
    verification = require_passive_security_scope(project=project, user=actor, origin=origin)
    config = ProjectConfiguration.objects.filter(project=project).first()
    as_of = timezone.now()
    if config is None or config.revision != configuration_revision or verification.verified_at > as_of:
        raise ValidationError("Reload current project configuration and exact verified own-target authority.")
    page = CrawlPageSnapshot.objects.select_related("crawl_run__job__actor", "raw_artifact").filter(
        pk=crawl_page_id, project=project, crawl_run__project=project).first()
    if page is None:
        raise PermissionDenied
    _check_target_page(page, project=project, target_url=target_url, origin=origin, as_of=as_of)
    content_page, seen = page, set()
    while content_page.reused_from_id:
        if (content_page.pk in seen or len(seen) >= 32 or content_page.status_code != 304 or content_page.error_category):
            raise ValidationError("Reused HTTP content requires a bounded actual 304 predecessor chain.")
        seen.add(content_page.pk)
        previous = content_page.reused_from
        _check_target_page(previous, project=project, target_url=target_url, origin=origin, as_of=as_of)
        if (previous.observed_at >= content_page.observed_at or previous.crawl_run.completed_at > content_page.crawl_run.started_at
            or previous.error_category or previous.content_hash != content_page.content_hash
            or previous.raw_artifact_id != content_page.raw_artifact_id):
            raise ValidationError("304 reuse must retain its genuine earlier exact-target body evidence.")
        content_page = previous
    if content_page.status_code == 304 and not content_page.error_category:
        raise ValidationError("304 without actual original content is not usable destination evidence.")
    artifact = page.raw_artifact
    if artifact:
        if (artifact.project_id != project.pk or artifact.job_id != content_page.crawl_run.job_id
            or artifact.content_type != "text/html" or not 1 <= artifact.size_bytes <= 2 * 1024 * 1024
            or not artifact.key.startswith(f"{project_artifact_scope(project)}/jobs/{artifact.job_id}/")):
            raise ValidationError("Retained private target body must belong to its actual project/crawl source.")
        try:
            body = read_project_artifact(project=project, key=artifact.key)
            if len(body) != artifact.size_bytes or sha256(body).hexdigest() != page.content_hash:
                raise ValidationError("Private target body size/digest differs from stored HTTP evidence.")
        except (ArtifactNotFound, ArtifactStorageError, ArtifactValidationError):
            raise ValidationError("Private target body evidence is unavailable.") from None
    if page.error_category or page.status_code is None:
        state = "fetch_failed_or_unavailable_not_broken_proof"
    elif page.status_code in {404, 410}:
        state = "dated_http_missing_destination_candidate"
    elif page.status_code == 304:
        state = "not_modified_reused_body_not_new_success_status"
    elif 200 <= page.status_code < 300:
        state = "dated_http_success_not_usefulness_or_link_recovery_proof"
    else:
        state = "dated_http_other_status_not_missing_destination_proof"
    run = page.crawl_run
    return verification, {"method": METHOD, "project_id": project.pk, "configuration_revision": config.revision,
        "origin": origin, "verification_id": verification.pk, "verified_at": verification.verified_at.isoformat(),
        "crawl_page_id": page.pk, "crawl_run_id": run.pk, "job_id": run.job_id, "crawl_method": run.job.method_version,
        "observed_at": page.observed_at.isoformat(), "completed_at": run.completed_at.isoformat(),
        "requested_url": page.requested_url, "final_url": page.final_url, "redirect_chain": page.redirect_chain,
        "status_code": page.status_code, "error_category": page.error_category, "body_sha256": page.content_hash,
        "raw_artifact_id": artifact.pk if artifact else None, "raw_body_readback": "checked" if artifact else "not_retained",
        "content_observed_at": content_page.observed_at.isoformat(), "reused_from_id": page.reused_from_id,
        "coverage": {"page_limit": run.page_limit, "pages_attempted": run.pages_attempted, "pages_observed": run.pages_observed,
            "crawl_status": run.job.status, "whole_site": "not_established"}, "state": state,
        "external_source": "customer_reported_not_independently_verified", "unlinked_or_lost_link": "not_established",
        "interpretation": "separate_dated_own_target_http_not_current_site_or_external_link_verification"}


def recovery_action_evidence(*, project, actor, intake, action_review_id):
    """Inspect an existing exact-target page action; link/source permission never approves site remediation."""
    _verification, data, _target = own_target_evidence(project=project, actor=actor, intake=intake)
    if data["status"] != "observed":
        raise ValidationError("Useful destination recovery requires a reported literal inbound href.")
    return target_recovery_action_evidence(project=project, actor=actor, origin=data["origin"],
        configuration_revision=data["configuration_revision"], crawl_page_id=data["crawl_page_id"],
        target_url=data["target_url"], action_review_id=action_review_id)


def target_recovery_action_evidence(*, project, actor, origin, configuration_revision, crawl_page_id, target_url, action_review_id):
    """Read genuine destination recovery candidate independently of any external/manual link observation."""
    from .action_review import _assignee, _opportunity_source
    from .diagnostics import METHOD_VERSION as DIAGNOSTICS_METHOD
    from .findings import TECHNICAL_METHOD
    from .models import ActionReview
    if type(action_review_id) is not int or not 1 <= action_review_id < 2**53:
        raise ValidationError("Choose an exact stored current own-page action revision.")
    project = Project.objects.select_related("organization").filter(pk=project.pk, organization_id=project.organization_id).first()
    if project is None:
        raise PermissionDenied
    _verification, target = own_target_crawl_evidence(project=project, actor=actor, origin=origin,
        configuration_revision=configuration_revision, crawl_page_id=crawl_page_id, target_url=target_url)
    if target["state"] != "dated_http_missing_destination_candidate":
        raise ValidationError("Useful destination recovery requires a reported literal inbound href and actual dated 404/410 target.")
    action = ActionReview.objects.select_related("actor", "opportunity__finding__source_diagnostics").filter(
        pk=action_review_id, project=project).first()
    if action is None:
        raise PermissionDenied
    if (ActionReview.objects.filter(project=project, action_id=action.action_id).order_by("-revision").first().pk != action.pk
        or action.state == "dismissed" or not action.opportunity_id or action.action_kind not in {"refresh", "redirect"}
        or type(action.affected_urls) is not list or len(action.affected_urls) != (2 if action.action_kind == "redirect" else 1)):
        raise ValidationError("Use a current genuine HTTP-error opportunity's useful refresh/redirect proposal.")
    require_project_action(project=project, user=action.actor,
        action=Action.LAUNCH_JOB if action.state in {"in_progress", "implemented"} else Action.APPROVE)
    if not _verified(action.actor):
        raise PermissionDenied
    _assignee(project, action.assignee_id)
    destination = action.affected_urls[-1] if action.action_kind == "redirect" else ""
    opportunity, urls = _opportunity_source(project, actor, action.opportunity_id, action.action_kind, destination)
    finding = opportunity.finding
    source = finding.source_diagnostics
    if (source is None or source.method_version != DIAGNOSTICS_METHOD or source.crawl_run_id != target["crawl_run_id"]
        or type(source.output) is not dict or type(source.output.get("coverage")) is not dict
        or finding.method_version != TECHNICAL_METHOD or finding.detector != "observed_http_error_candidate"
        or finding.subject != target_url or action.affected_urls != urls
        or finding.evidence != {"snapshot_id": source.pk, "crawl_run_id": target["crawl_run_id"],
            "diagnostics_method": DIAGNOSTICS_METHOD, "details": {"source": "raw_crawl", "crawl_page_id": target["crawl_page_id"],
                "observed_at": target["observed_at"], "status_code": target["status_code"],
                "coverage": source.output.get("coverage", {}).get("state"), "interpretation": "observed_raw_not_engine_indexing"}}):
        raise ValidationError("Recovery must retain the actual selected target's diagnostic/HTTP-error finding, never synthetic intent/link evidence.")
    for url in urls:
        validate_owned_website_url(url, approved_origin=origin)
    approval = None
    if action.state != "proposed":
        approval = ActionReview.objects.filter(project=project, action_id=action.action_id, state="accepted",
            revision__lte=action.revision).select_related("actor").order_by("-revision").first()
        if (approval is None or any(getattr(approval, field) != getattr(action, field) for field in
            ("opportunity_id", "assignee_id", "action_kind", "affected_urls", "acceptance_criteria"))):
            raise ValidationError("Own-site implementation requires its own unchanged exact accepted page proposal.")
        require_project_action(project=project, user=approval.actor, action=Action.APPROVE)
        if not _verified(approval.actor):
            raise PermissionDenied
    return {"method": "authority-own-target-recovery-v1", "project_id": project.pk,
        "target_evidence": target, "action_review_id": action.pk, "action_id": str(action.action_id),
        "action_revision": action.revision, "state": action.state, "action_kind": action.action_kind,
        "affected_urls": urls, "assignee_id": action.assignee_id, "acceptance_criteria": action.acceptance_criteria,
        "opportunity_id": opportunity.pk, "finding_id": finding.pk, "diagnostics_id": source.pk,
        "site_approval_review_id": approval.pk if approval else None,
        "implemented_at": action.implemented_at.isoformat() if action.implemented_at else None,
        "interpretation": "existing_separately_approved_own_page_action_not_outreach_or_external_link_recovery_proof"}


def validate_link_proposal(proposal):
    if (type(proposal) is not dict or set(proposal) != {"action", "relevance", "draft_text", "outreach_permission"}
        or type(proposal["action"]) is not str or proposal["action"] not in
            {"verify_source", "request_source_correction", "review_target_recovery"}
        or type(proposal["outreach_permission"]) is not bool):
        raise ValidationError("Choose an exact human link-review proposal and separate outreach declaration.")
    _text(proposal["relevance"], 500, required=True)
    _text(proposal["draft_text"], 2000)
    return dict(proposal)


def require_current_link_review(row, *, actor=None):
    from .action_review import _assignee
    _assignee(row.project, row.assignee_id)
    users = [row.source_actor, row.actor]
    if actor is not None:
        users.append(actor)
    if row.reviewed_revision_id:
        users.extend([row.reviewed_revision.actor, row.approved_by])
    for user in users:
        verification, _data, target = own_target_evidence(project=row.project, actor=user, intake=row.intake)
        recovery = recovery_action_evidence(project=row.project, actor=user, intake=row.intake,
            action_review_id=row.recovery_action_review_id) if row.recovery_action_review_id else {}
        if (verification.pk != row.verification_id or verification.verified_at != row.verified_at
            or target != row.target_evidence or recovery != row.recovery_evidence):
            raise ValidationError("Target/source authority or recovery handoff changed; make a fresh unapproved human draft.")


def link_review_source_current(row):
    try:
        require_current_link_review(row)
        return True
    except (PermissionDenied, ValidationError):
        return False


def record_authority_link(*, project, actor, request_key, intake, proposal, assignee_id, state, reason,
                          recovery_action_review_id=None, link_id=None, expected_revision=None,
                          executed_at=None, execution_note=""):
    from uuid import UUID, uuid4
    from django.db import transaction
    from tenancy.models import Organization
    from .action_review import _assignee
    from .models import AuthorityLinkReview
    if (type(request_key) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", request_key)
        or type(state) is not str or state not in AuthorityLinkReview.State.values
        or (link_id is None) != (expected_revision is None)
        or expected_revision is not None and (type(expected_revision) is not int or not 1 <= expected_revision < 2**31 - 1)):
        raise ValidationError("Choose an exact current human link-review revision and request key.")
    proposal = validate_link_proposal(proposal)
    if ((proposal["action"] == "review_target_recovery") != (recovery_action_review_id is not None)
        or recovery_action_review_id is not None and
            (type(recovery_action_review_id) is not int or not 1 <= recovery_action_review_id < 2**53)):
        raise ValidationError("Only useful-target recovery handoffs bind a genuine exact page-action revision.")
    _text(reason, 500, required=True)
    _text(execution_note, 500, required=state == "reported")
    if link_id is not None:
        try:
            link_id = UUID(str(link_id))
        except (ValueError, TypeError):
            raise ValidationError("Choose a project-owned human link review.") from None
    if state != "reported" and (executed_at is not None or execution_note):
        raise ValidationError("Manual activity reporting is a separate stage, never automatic site/link execution.")
    if state == "reported" and (not isinstance(executed_at, datetime) or timezone.is_naive(executed_at) or executed_at > timezone.now()):
        raise ValidationError("Report the actual aware nonfuture manual activity time.")
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().filter(pk=project.pk, organization=organization).first()
        if project is None:
            raise PermissionDenied
        verification, data, target = own_target_evidence(project=project, actor=actor, intake=intake)
        recovery = recovery_action_evidence(project=project, actor=actor, intake=data,
            action_review_id=recovery_action_review_id) if recovery_action_review_id else {}
        assignee = _assignee(project, assignee_id)
        previous = None
        if link_id is not None:
            previous = AuthorityLinkReview.objects.filter(project=project, link_id=link_id).order_by("-revision").first()
            if previous is None:
                raise PermissionDenied
        exact = (data, target, proposal, assignee.pk, recovery_action_review_id, recovery)
        existing = AuthorityLinkReview.objects.filter(project=project, request_key=request_key).first()
        if existing:
            latest = AuthorityLinkReview.objects.filter(project=project, link_id=existing.link_id).order_by("-revision").first()
            if (latest.pk != existing.pk or existing.actor_id != actor.pk or link_id is not None and existing.link_id != link_id
                or existing.revision != (expected_revision + 1 if link_id else 1)
                or (existing.intake, existing.target_evidence, existing.proposal, existing.assignee_id,
                    existing.recovery_action_review_id, existing.recovery_evidence) != exact
                or (existing.state, existing.reason, existing.executed_at, existing.execution_note) != (state, reason, executed_at, execution_note)):
                raise ValidationError("Request key belongs to another or stale human link decision.")
            require_current_link_review(existing, actor=actor)
            return existing
        if previous:
            transitions = {"draft": {"draft", "review", "dismissed"}, "review": {"draft", "approved", "dismissed"},
                "approved": {"draft", "reported", "dismissed"}, "reported": {"draft"}, "dismissed": {"draft"}}
            if previous.revision != expected_revision or state not in transitions[previous.state]:
                raise ValidationError("Link review changed; inspect latest history and allowed state.")
            if state not in {"draft", "dismissed"}:
                require_current_link_review(previous, actor=actor)
            if state != "draft" and (previous.intake, previous.target_evidence, previous.proposal, previous.assignee_id,
                previous.recovery_action_review_id, previous.recovery_evidence) != exact:
                raise ValidationError("Changed source/target/text/assignee/recovery action needs a fresh unapproved draft.")
        elif state != "draft":
            raise ValidationError("New human link reviews begin as an unapproved draft.")
        reviewed = approver = approved_at = None
        if state == "approved":
            reviewed, approver, approved_at = previous, actor, timezone.now()
        elif state == "reported":
            reviewed, approver, approved_at = previous.reviewed_revision, previous.approved_by, previous.approved_at
            if executed_at < approved_at:
                raise ValidationError("Manual activity must follow exact human approval.")
        return AuthorityLinkReview.objects.create(project=project, actor=actor,
            source_actor=actor if state == "draft" else previous.source_actor, assignee=assignee,
            verification=verification, verified_at=verification.verified_at, crawl_page_id=data["crawl_page_id"],
            intake=data, target_evidence=target, proposal=proposal, recovery_action_review_id=recovery_action_review_id,
            recovery_evidence=recovery, link_id=link_id or uuid4(), revision=previous.revision + 1 if previous else 1,
            request_key=request_key, state=state, reason=reason, reviewed_revision=reviewed,
            approved_by=approver, approved_at=approved_at, executed_at=executed_at, execution_note=execution_note)
