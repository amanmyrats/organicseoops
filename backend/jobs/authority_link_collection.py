"""D132 exact human-approved selected source, once-only collection and private readback."""
from datetime import datetime
from hashlib import sha256
import json
import re

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from config.artifacts import ArtifactNotFound, ArtifactStorageError, ArtifactValidationError
from integrations.google_tokens import GoogleTokenError, _reject_constant, _unique_object
from tenancy.artifacts import delete_project_artifact, read_project_artifact, save_project_artifact
from tenancy.customer_artifact_barrier import project_artifact_barrier
from tenancy.models import Organization, Project
from tenancy.services import Action, require_project_action
from .authority_link_sources import (COLLECTION_METHOD, EXCLUDED, MAX_ANCHORS, MAX_BODY_BYTES,
    MAX_MATCHES, MAX_RESULT_BYTES, METHOD, REFERENCE_METHOD, REFERENCE_COLLECTION_METHOD,
    collect_static_link_source, static_link_source_authority)
from .crawler import _crawl_execution_lock
from .local_feedback import _text, validate_owned_website_url
from .models import Artifact, AuthorityProspectReview, JobCancellation, JobRun, JobStatus, JobStep, SourceCitation, UsageReservation
from .usage import require_billable_access, settle_usage, usage_denial

HANDLER = "verify_authority_link_source"
STAGE = "Collect selected static-link source"
ERRORS = {"invalid_url", "outside_scope", "invalid_scope", "non_public_address", "dns_error", "timeout",
    "redirect_limit", "network_error", "invalid_content_length", "response_too_large",
    "unsupported_content_encoding", "invalid_content_encoding", "static_source_redirect_scope",
    "static_source_robots_denied", "static_source_robots_unknown", "static_source_http_status",
    "static_source_content_type", "static_source_result_limit", "static_source_deadline", "static_source_document_invalid"}


def validate_input(data):
    if (type(data) is not dict or set(data) not in ({"link_review_id", "source_collection_permission"},
        {"link_review_id", "source_collection_permission", "collection_method"})
        or type(data["link_review_id"]) is not int or not 1 <= data["link_review_id"] < 2**53
        or data["source_collection_permission"] is not True
        or data.get("collection_method", COLLECTION_METHOD) not in (COLLECTION_METHOD, REFERENCE_COLLECTION_METHOD)):
        raise ValidationError("Select one current human-approved source and separately affirm collection permission.")
    return dict(data)


def selection_snapshot(project, actor, data):
    data = validate_input(data)
    method = data.get("collection_method", COLLECTION_METHOD)
    return {"binding": static_link_source_authority(project=project, actor=actor,
                link_review_id=data["link_review_id"], source_collection_permission=data["source_collection_permission"]),
            "method": method, "parser_method": REFERENCE_METHOD if method == REFERENCE_COLLECTION_METHOD else METHOD}


def _date(value):
    _text(value, 64, required=True)
    try:
        stamp = datetime.fromisoformat(value)
        if timezone.is_naive(stamp) or stamp > timezone.now():
            raise ValueError
    except ValueError:
        raise ValidationError("Retain the actual aware nonfuture source collection time.") from None
    return stamp


def validate_result(data, binding, *, collection_method=COLLECTION_METHOD):
    """Accept only minimized parser evidence, never raw body or unrelated source inventories."""
    references = collection_method == REFERENCE_COLLECTION_METHOD
    if (collection_method not in (COLLECTION_METHOD, REFERENCE_COLLECTION_METHOD)
        or type(data) is not dict or data.get("method") != collection_method):
        raise ValidationError("Static source collection is unavailable.")
    if data.get("state") == "unavailable":
        if set(data) != {"method", "state", "error_category"} or data["error_category"] not in ERRORS:
            raise ValidationError("Static source errors are categorical only.")
        return data
    if (set(data) != {"method", "state", "requested_url", "url", "observed_at", "robots", "redirects", "evidence"}
        or data["state"] != "collected" or data["requested_url"] != binding["source_url"]
        or data["robots"] not in {"available", "missing_http_404_or_410"}
        or type(data["redirects"]) is not list or len(data["redirects"]) > 2):
        raise ValidationError("Retain one bounded actual selected-source observation.")
    validate_owned_website_url(data["url"], approved_origin=binding["source_origin"])
    _date(data["observed_at"])
    for hop in data["redirects"]:
        if (type(hop) is not dict or set(hop) != {"url", "status"} or type(hop["status"]) is not int
            or hop["status"] not in {301, 302, 303, 307, 308}):
            raise ValidationError("Retain bounded actual source redirects.")
        validate_owned_website_url(hop["url"], approved_origin=binding["source_origin"])
    evidence = data["evidence"]
    fixed = {"method": REFERENCE_METHOD if references else METHOD, "source_url": data["url"], "target_url": binding["target_url"],
        "observed_at": data["observed_at"], "href_semantics": "bounded_stdlib_uri_reference_join_against_final_source_no_base_no_browser_repair"
            if references else "html_character_references_decoded_exact_absolute_href_no_url_resolution",
        "source_authority": "not_established_by_parser", "unlinked_or_lost_link": "not_established",
        "raw_body_retention": "not_selected_transient_only",
        "interpretation": "parsed_static_markup_not_rendered_link_or_permission_or_link_loss_proof"}
    if (type(evidence) is not dict or set(evidence) != set(fixed) | {"body_sha256", "body_size_bytes", "matching_links", "state", "coverage"}
        or any(evidence[key] != value for key, value in fixed.items())
        or type(evidence["body_sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", evidence["body_sha256"])
        or type(evidence["body_size_bytes"]) is not int or not 1 <= evidence["body_size_bytes"] <= MAX_BODY_BYTES
        or type(evidence["matching_links"]) is not list or len(evidence["matching_links"]) > MAX_MATCHES):
        raise ValidationError("Retain minimized exact-target markup and original body integrity only.")
    for link in evidence["matching_links"]:
        if (type(link) is not dict or set(link) != {"parsed_href", "anchor_text", "anchor_text_truncated", "rel", "rel_truncated"}
            or link["parsed_href"] != binding["target_url"]
            or any(type(link[key]) is not bool for key in ("anchor_text_truncated", "rel_truncated"))):
            raise ValidationError("Retain only minimized matching absolute target attributes.")
        _text(link["anchor_text"], 240)
        _text(link["rel"], 100)
    coverage = evidence["coverage"]
    fixed_coverage = {"surface": "returned_static_html_not_rendered", "excluded_containers": sorted(EXCLUDED),
                      "whole_site": "not_established", "browser_visibility": "unknown"}
    if references:
        if (type(coverage) is not dict or type(coverage.get("unsupported_references")) is not int
            or type(coverage.get("anchors_inspected")) is not int
            or not 0 <= coverage["unsupported_references"] <= coverage.get("anchors_inspected", -1)):
            raise ValidationError("Unsupported static references retain only bounded uncertainty counts.")
        fixed_coverage.update({"unsupported_references": coverage["unsupported_references"],
            "reference_resolution": "unavailable_base_element" if coverage.get("base_element_seen") else "bounded_no_base_stdlib_uri_references"})
    if (type(coverage) is not dict or set(coverage) != set(fixed_coverage) | {"anchors_seen", "anchors_inspected",
        "anchor_limit_reached", "matches_seen", "matches_capped", "structure_uncertain", "base_element_seen"}
        or any(coverage[key] != value for key, value in fixed_coverage.items())
        or any(type(coverage[key]) is not bool for key in ("anchor_limit_reached", "matches_capped", "structure_uncertain", "base_element_seen"))
        or any(type(coverage[key]) is not int or not 0 <= coverage[key] <= MAX_BODY_BYTES for key in ("anchors_seen", "anchors_inspected", "matches_seen"))
        or coverage["anchors_inspected"] != min(coverage["anchors_seen"], MAX_ANCHORS)
        or coverage["anchor_limit_reached"] != (coverage["anchors_seen"] > MAX_ANCHORS)
        or coverage["matches_capped"] != (coverage["matches_seen"] > MAX_MATCHES)
        or not len(evidence["matching_links"]) <= coverage["matches_seen"] <= coverage["anchors_inspected"]):
        raise ValidationError("Keep bounded partial static-document coverage explicit.")
    if references and coverage["base_element_seen"] and (evidence["matching_links"] or not coverage["structure_uncertain"]):
        raise ValidationError("Base-dependent references never provide positive or comparable evidence.")
    expected = ("unavailable_base_dependent_references" if references and coverage["base_element_seen"] else
                "unavailable_ambiguous_markup" if coverage["structure_uncertain"] else
                "observed_resolved_target_in_static_uri_references" if references and evidence["matching_links"] else
                "observed_absolute_target_in_parsed_html" if evidence["matching_links"] else
                "not_observed_in_bounded_static_html_not_link_loss")
    if evidence["state"] != expected or len(json.dumps(data, allow_nan=False).encode()) > MAX_RESULT_BYTES:
        raise ValidationError("Partial/ambiguous static HTML is not link-loss proof.")
    return data


def validate_job(job, *, current=False):
    data = validate_input(job.input_snapshot)
    config = job.config_snapshot
    method = data.get("collection_method", COLLECTION_METHOD)
    if (job.method_version != method or job.retry_of_id or job.schedule_id or job.scheduled_for
        or type(config) is not dict or set(config) != {"binding", "method", "parser_method"}
        or config["method"] != method or config["parser_method"] != (REFERENCE_METHOD if method == REFERENCE_COLLECTION_METHOD else METHOD)
        or type(config["binding"]) is not dict
        or (config["binding"].get("project_id"), config["binding"].get("organization_id"), config["binding"].get("actor_id"),
            config["binding"].get("link_review_id"), config["binding"].get("source_collection_permission")) !=
           (job.project_id, job.organization_id, job.actor_id, data["link_review_id"], True)):
        raise ValidationError("Static-link jobs require an exact current manual source binding; no schedule or retry.")
    if job.output:
        output = {key: value for key, value in job.output.items() if key not in {"artifact_id", "derived_sha256"}}
        validate_result(output, config["binding"], collection_method=method)
        if output["state"] != "collected" or set(job.output) != set(output) | {"artifact_id", "derived_sha256"}:
            raise ValidationError("Only collected minimized observations may be persisted as job output.")
        if (type(job.output["artifact_id"]) is not int or job.output["artifact_id"] < 1
            or job.output["derived_sha256"] != sha256(json.dumps(output, sort_keys=True, allow_nan=False).encode()).hexdigest()):
            raise ValidationError("Private derived source integrity is unavailable.")
    if current and selection_snapshot(job.project, job.actor, data) != config:
        raise PermissionDenied


def queue_static_link_collection(*, project, actor, data, idempotency_key):
    from .services import queue_job
    data = validate_input(data)
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        config = selection_snapshot(project, actor, data)
        return queue_job(project=project, actor=actor, handler=HANDLER, input_snapshot=data,
                         config_snapshot=config, idempotency_key=idempotency_key)


def _denial(job):
    if JobCancellation.objects.filter(job=job).exists():
        return "cancel_requested"
    denied = usage_denial(job=job)
    if denied:
        return denied
    reservation = UsageReservation.objects.get(job=job)
    if reservation.provider != "authority_source" or reservation.reserved_units != 1:
        return "usage_unreserved"
    try:
        validate_job(job, current=True)
    except (PermissionDenied, ValidationError, Project.DoesNotExist):
        return "source_scope_changed"
    return ""


def _finish(job_id, *, result=None, error=""):
    org_id = JobRun.objects.filter(pk=job_id, handler=HANDLER).values_list("organization_id", flat=True).first()
    if org_id is None:
        return False
    key = None
    try:
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=org_id)
            job = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id)
            if job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
                return False
            Project.objects.select_for_update().get(pk=job.project_id)
            denied = _denial(job)
            step = job.steps.filter(sequence=1).first()
            if job.status == JobStatus.QUEUED and not denied:
                job.status = JobStatus.RUNNING
                job.save(update_fields=["status", "updated_at"])
            useful = bool(result and result.get("state") == "collected" and not denied)
            if useful:
                validate_result(result, job.config_snapshot["binding"], collection_method=job.method_version)
                content = json.dumps(result, sort_keys=True, allow_nan=False).encode()
                key = save_project_artifact(project=job.project, content=content, content_type="application/json")
                # Storage is outside DB transactions; recheck cancellation/current rights after its write.
                denied = _denial(job)
                if denied:
                    delete_project_artifact(project=job.project, key=key)
                    key = None
                    useful = False
                else:
                    artifact = Artifact.objects.create(job=job, project=job.project, key=key,
                        content_type="application/json", size_bytes=len(content))
                    job.output = {**result, "artifact_id": artifact.pk, "derived_sha256": sha256(content).hexdigest()}
                    SourceCitation.objects.create(job=job, step=step, source_title="Selected static-link source",
                        source_url=result["url"], observed_at=_date(result["observed_at"]))
            if step:
                step.status = JobStep.Status.SUCCEEDED if useful else JobStep.Status.FAILED
                step.progress_percent = 100
                step.error_category = denied or error
                step.output = {"method": job.method_version, "state": "collected" if useful else "unavailable"}
                step.save(update_fields=["status", "progress_percent", "error_category", "output"])
            job.status = JobStatus.CANCELLED if denied else JobStatus.SUCCEEDED if useful else JobStatus.FAILED
            job.error_category = denied or error
            if not useful:
                job.output = {}
            job.save(update_fields=["status", "error_category", "output", "updated_at"])
            if UsageReservation.objects.filter(job=job, state=UsageReservation.State.RESERVED).exists():
                settle_usage(job=job, actual_units=int(step is not None))
    except Exception:
        if key:
            delete_project_artifact(project=JobRun.objects.get(pk=job_id).project, key=key)
        raise
    return True


def execute_static_link_collection(job_id, *, fetcher=None):
    organization_id = JobRun.objects.filter(pk=job_id).values_list("organization_id", flat=True).first()
    if organization_id is None:
        return False
    with project_artifact_barrier(organization_id, shared=True), _crawl_execution_lock(job_id) as acquired:
        if not acquired:
            return False
        try:
            return _execute(job_id, fetcher=fetcher)
        except Exception:
            return _finish(job_id, error="handler_failed")


def _execute(job_id, *, fetcher):
    org_id = JobRun.objects.filter(pk=job_id, handler=HANDLER).values_list("organization_id", flat=True).first()
    if org_id is None:
        return False
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=org_id)
        job = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id)
        if job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            return False
        if _denial(job):
            return _finish(job_id)
        if job.steps.exists():
            return _finish(job_id, error="request_outcome_unknown")
        if job.status == JobStatus.QUEUED:
            job.status = JobStatus.RUNNING
            job.save(update_fields=["status", "updated_at"])
        JobStep.objects.create(job=job, sequence=1, name=STAGE, status=JobStep.Status.RUNNING,
                               output={"method": job.method_version, "state": "attempted"})

    def checkpoint():
        current = JobRun.objects.select_related("project", "actor").get(pk=job_id)
        if current.status != JobStatus.RUNNING or _denial(current):
            raise PermissionDenied

    result = collect_static_link_source(project=job.project, actor=job.actor,
        binding=job.config_snapshot["binding"], before_request=checkpoint, fetcher=fetcher, collection_method=job.method_version)
    validate_result(result, job.config_snapshot["binding"], collection_method=job.method_version)
    return _finish(job_id, result=result, error=result.get("error_category", ""))


def read_static_link_observation(*, project, actor, job_id):
    """Current-use readback; historical owner exports remain under D098's separate retained path."""
    require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
    require_billable_access(organization=project.organization)
    job = JobRun.objects.select_related("project", "actor").filter(pk=job_id, project=project,
        handler=HANDLER, status=JobStatus.SUCCEEDED).first()
    if job is None or JobCancellation.objects.filter(job=job).exists():
        raise PermissionDenied
    validate_job(job, current=True)
    caller_binding = selection_snapshot(project, actor, job.input_snapshot)["binding"]
    if {**caller_binding, "actor_id": job.actor_id} != job.config_snapshot["binding"]:
        raise PermissionDenied
    output = job.output
    artifact = Artifact.objects.filter(pk=output.get("artifact_id"), job=job, project=project,
        content_type="application/json", size_bytes__gte=1, size_bytes__lte=MAX_RESULT_BYTES).first()
    step = JobStep.objects.filter(job=job, sequence=1, name=STAGE, status=JobStep.Status.SUCCEEDED,
        output={"method": job.method_version, "state": "collected"}, progress_percent=100, error_category="").first()
    if artifact is None or step is None or job.artifacts.count() != 1 or job.steps.count() != 1:
        raise ValidationError("Exact private static-link source provenance is unavailable.")
    expected = {key: value for key, value in output.items() if key not in {"artifact_id", "derived_sha256"}}
    if not SourceCitation.objects.filter(job=job, step=step, source_title="Selected static-link source",
        source_url=output["url"], observed_at=_date(output["observed_at"])).exists():
        raise ValidationError("Actual source collection citation is unavailable.")
    try:
        content = read_project_artifact(project=project, key=artifact.key)
        if len(content) != artifact.size_bytes or sha256(content).hexdigest() != output["derived_sha256"]:
            raise ValidationError("Private derived source size/digest changed.")
        stored = json.loads(content, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ArtifactNotFound, ArtifactStorageError, ArtifactValidationError, GoogleTokenError, ValueError, UnicodeError, RecursionError):
        raise ValidationError("Private derived source cannot be safely read back.") from None
    if stored != expected:
        raise ValidationError("Private derived source differs from its actual observation.")
    validate_result(stored, job.config_snapshot["binding"], collection_method=job.method_version)
    validate_job(job, current=True)
    caller_binding = selection_snapshot(project, actor, job.input_snapshot)["binding"]
    if {**caller_binding, "actor_id": job.actor_id} != job.config_snapshot["binding"]:
        raise PermissionDenied
    require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
    require_billable_access(organization=project.organization)
    return {"job_id": job.pk, "artifact_id": artifact.pk, "step_id": step.pk, "source_current": True,
            "collection": stored, "interpretation": "independently_collected_static_markup_not_browser_visibility_or_link_loss"}


def _complete_static_coverage(evidence):
    return (not evidence["coverage"]["structure_uncertain"] and not evidence["coverage"]["anchor_limit_reached"]
        and not evidence["coverage"]["matches_capped"]
        and not evidence["coverage"].get("unsupported_references", 0)
        and not any(link["anchor_text_truncated"] or link["rel_truncated"] for link in evidence["matching_links"]))


def read_static_destination_candidate(*, project, actor, static_job_id):
    """One saved static observation and its genuine dated destination; no current broken-link claim."""
    from .authority_links import own_target_crawl_evidence
    if type(static_job_id) is not int or not 1 <= static_job_id < 2**53:
        raise ValidationError("Choose an exact actual saved static-source job.")
    observation = read_static_link_observation(project=project, actor=actor, job_id=static_job_id)
    job = JobRun.objects.select_related("project", "actor").get(pk=static_job_id, project=project, handler=HANDLER)
    binding = job.config_snapshot["binding"]
    bound = binding["target_evidence"]
    _verification, target = own_target_crawl_evidence(project=project, actor=actor, origin=bound["origin"],
        configuration_revision=bound["configuration_revision"], crawl_page_id=bound["crawl_page_id"], target_url=binding["target_url"])
    source = observation["collection"]
    if (target != bound or source["evidence"]["target_url"] != target["requested_url"]
        or _date(source["observed_at"]) < max(_date(target["observed_at"]), _date(target["completed_at"]))):
        raise ValidationError("Retain the exact bound destination and separately ordered original observations.")
    complete = _complete_static_coverage(source["evidence"])
    count = len(source["evidence"]["matching_links"])
    candidate = complete and count > 0 and not target["error_category"] and target["status_code"] in {404, 410}
    # The target private read may have outlived the earlier source-authority check.
    validate_job(job, current=True)
    caller = selection_snapshot(project, actor, job.input_snapshot)
    caller["binding"]["actor_id"] = job.actor_id
    if caller != job.config_snapshot:
        raise PermissionDenied
    require_billable_access(organization=project.organization)
    return {"method": "authority-static-destination-candidate-v1", "project_id": project.pk, "source_current": True,
        "selection": job.config_snapshot, "requested_source_url": source["requested_url"], "final_source_url": source["url"],
        "target_url": target["requested_url"], "target": target,
        "static": {"job_id": observation["job_id"], "step_id": observation["step_id"], "artifact_id": observation["artifact_id"],
            "observed_at": source["observed_at"], "method": source["method"], "parser_method": source["evidence"]["method"],
            "body_sha256": source["evidence"]["body_sha256"], "body_size_bytes": source["evidence"]["body_size_bytes"],
            "state": source["evidence"]["state"], "matching_target_count": count, "coverage": source["evidence"]["coverage"],
            "redirects": source["redirects"]},
        "static_coverage_complete": complete, "destination_recovery_candidate": candidate,
        "state": "incomparable_ambiguous_or_truncated_static_coverage" if not complete else
            "dated_static_target_and_http_missing_destination_candidate" if candidate else
            "target_not_observed_in_bounded_static_document_not_missing_or_healthy_proof" if not count else
            "no_dated_missing_destination_candidate_not_current_healthy_or_recovered_link_proof",
        "unlinked_or_lost_link": "not_established", "site_or_outreach_approval": "separate_human_workflows",
        "handoff": "separate_existing_own_page_action_review_required_no_automatic_action_or_approval",
        "interpretation": "separately_dated_static_target_and_own_http_candidate_not_current_broken_inbound_browser_or_causal_proof"}


def compare_static_link_observations(*, project, actor, previous_job_id, current_job_id):
    """Compare genuine dated same-source observations; absence is not verified link loss."""
    if (any(type(value) is not int or not 1 <= value < 2**53 for value in (previous_job_id, current_job_id))
        or previous_job_id == current_job_id):
        raise ValidationError("Choose two distinct actual dated selected-source jobs.")
    previous = read_static_link_observation(project=project, actor=actor, job_id=previous_job_id)
    current = read_static_link_observation(project=project, actor=actor, job_id=current_job_id)
    before, after = previous["collection"], current["collection"]
    jobs = list(JobRun.objects.filter(project=project, pk__in=[previous_job_id, current_job_id]).select_related("project", "actor"))
    if len(jobs) != 2:
        raise PermissionDenied
    bindings = [{key: value for key, value in row.config_snapshot["binding"].items() if key != "actor_id"} for row in jobs]
    if (bindings[0] != bindings[1] or any(before[key] != after[key] for key in ("method", "requested_url", "url"))
        or before["evidence"]["target_url"] != after["evidence"]["target_url"]
        or _date(before["observed_at"]) >= _date(after["observed_at"])):
        raise ValidationError("Compare increasing original dates with the exact same source, final URL, target, method and current binding.")
    comparable = all(_complete_static_coverage(source["evidence"]) for source in (before, after))
    counts = [len(source["evidence"]["matching_links"]) for source in (before, after)]
    state = ("incomparable_ambiguous_or_truncated_coverage" if not comparable else
        "target_markup_observed_again" if all(counts) else
        "target_markup_not_observed_again_candidate_not_verified_link_loss" if counts[0] else
        "target_markup_now_observed" if counts[1] else "target_markup_not_observed_in_either_bounded_document_not_unlinked_proof")

    def observation(item):
        source = item["collection"]
        return {"job_id": item["job_id"], "step_id": item["step_id"], "artifact_id": item["artifact_id"],
            "observed_at": source["observed_at"], "body_sha256": source["evidence"]["body_sha256"],
            "body_size_bytes": source["evidence"]["body_size_bytes"], "state": source["evidence"]["state"],
            "matching_target_count": len(source["evidence"]["matching_links"]), "coverage": source["evidence"]["coverage"]}

    # No SQL/network operation is authorized here; final current rechecks stop
    # stale source/actor/commercial changes during the second private readback.
    for row in jobs:
        validate_job(row, current=True)
        caller = selection_snapshot(project, actor, row.input_snapshot)["binding"]
        if {**caller, "actor_id": row.actor_id} != row.config_snapshot["binding"]:
            raise PermissionDenied
    require_billable_access(organization=project.organization)
    return {"method": "authority-static-link-comparison-v1", "project_id": project.pk,
        "collection_method": before["method"], "parser_method": before["evidence"]["method"],
        "requested_source_url": before["requested_url"], "final_source_url": before["url"],
        "target_url": before["evidence"]["target_url"], "previous": observation(previous), "current": observation(current),
        "comparable": comparable, "state": state, "body_changed": before["evidence"]["body_sha256"] != after["evidence"]["body_sha256"],
        "source_current": True, "unlinked_or_lost_link": "not_established", "site_approval": "separate_human_workflow",
        "interpretation": "dated_selected_static_document_candidate_not_browser_or_whole_site_or_verified_link_loss_or_causal_proof"}


def current_mention_review(*, project, actor, prospect_review_id):
    from .authority import require_current_prospect
    if type(prospect_review_id) is not int or not 1 <= prospect_review_id < 2**53:
        raise ValidationError("Choose an exact actual human mention review ID.")
    row = AuthorityProspectReview.objects.filter(pk=prospect_review_id, project=project).select_related(
        "project__organization", "research_job", "actor", "source_actor", "assignee", "reviewed_revision__actor", "approved_by").first()
    if row is None:
        raise PermissionDenied
    if (row.state not in {"approved", "reported"} or row.intake.get("proposed_action") != "mention"
        or AuthorityProspectReview.objects.filter(project=project, prospect_id=row.prospect_id, revision__gt=row.revision).exists()):
        raise ValidationError("Select the unchanged latest approved human mention, not a draft or other prospect action.")
    row.clean()
    require_current_prospect(row, actor=actor)
    require_current_mention_delivery(row, actor=actor)
    return row


def require_current_mention_delivery(row, *, actor):
    from .action_review import _assignee
    from .research import _context
    from integrations.oauth import _verified
    project = row.project
    # Private reads may take time: no earlier actor/config/latest check authorizes delivery.
    _assignee(project, row.assignee_id)
    for user in (row.source_actor, row.actor, row.reviewed_revision.actor, row.approved_by, actor):
        require_project_action(project=project, user=user, action=Action.MANAGE_PROJECT)
        if not _verified(user):
            raise PermissionDenied
    require_project_action(project=project, user=row.research_job.actor, action=Action.LAUNCH_JOB)
    if not _verified(row.research_job.actor):
        raise PermissionDenied
    if (_context(project, row.research_job.input_snapshot, row.research_job.actor) != row.research_job.config_snapshot.get("research_context")
        or AuthorityProspectReview.objects.filter(project=project, prospect_id=row.prospect_id, revision__gt=row.revision).exists()):
        raise ValidationError("Mention source configuration or latest review changed during readback.")


def mention_selection(row):
    """Minimized frozen human/source selection; never disclose the unrelated research excerpt."""
    source = row.source_evidence
    return {"review_id": row.pk, "prospect_id": str(row.prospect_id), "project_id": row.project_id, "revision": row.revision,
        "state": row.state, "quote": row.intake["quote"], "relevance": row.intake["relevance"], "assignee_id": row.assignee_id,
        "source_actor_id": row.source_actor_id, "reviewer_id": row.reviewed_revision.actor_id, "approved_by_id": row.approved_by_id,
        "requested_source_url": source["requested_url"], "final_source_url": source["url"], "research_job_id": row.research_job_id,
        "source_index": row.source_index, "retrieved_at": source["retrieved_at"], "body_sha256": source["original_response_sha256"],
        "body_size_bytes": source["source_size_bytes"], "source_current": True,
        "mention_basis": "human_selected_quote_in_normalized_bounded_research_text_not_browser_verification"}


def read_static_mention_candidate(*, project, actor, prospect_review_id, static_job_id):
    """D134 byte-equivalent existing documents; human mention judgment stays human."""
    if any(type(value) is not int or not 1 <= value < 2**53 for value in (prospect_review_id, static_job_id)):
        raise ValidationError("Choose exact actual human mention review and static-source job IDs.")
    require_billable_access(organization=project.organization)

    row = current_mention_review(project=project, actor=actor, prospect_review_id=prospect_review_id)
    observation = read_static_link_observation(project=project, actor=actor, job_id=static_job_id)
    source = observation["collection"]
    research, evidence = row.source_evidence, source["evidence"]
    if ((research["requested_url"], research["url"], research["original_response_sha256"], research["source_size_bytes"])
        != (source["requested_url"], source["url"], evidence["body_sha256"], evidence["body_size_bytes"])
        or _date(research["retrieved_at"]) > _date(source["observed_at"])):
        raise ValidationError("Associate exact requested/final source and byte-equivalent original bodies with ordered actual dates only.")
    complete = _complete_static_coverage(evidence)
    count = len(evidence["matching_links"])
    state = ("incomparable_ambiguous_or_truncated_static_coverage" if not complete else
             "human_mention_with_observed_exact_target_markup" if count else
             "human_mention_target_not_observed_candidate_not_verified_unlinked")
    refreshed = current_mention_review(project=project, actor=actor, prospect_review_id=prospect_review_id)
    if (refreshed.intake, refreshed.source_evidence, refreshed.assignee_id) != (row.intake, research, row.assignee_id):
        raise ValidationError("Human mention source or judgment changed during private readback.")
    job = JobRun.objects.select_related("project", "actor").get(pk=static_job_id, project=project, handler=HANDLER)
    validate_job(job, current=True)
    caller = selection_snapshot(project, actor, job.input_snapshot)
    caller["binding"]["actor_id"] = job.actor_id
    if caller != job.config_snapshot:
        raise PermissionDenied
    require_current_mention_delivery(refreshed, actor=actor)
    require_billable_access(organization=project.organization)
    return {"method": "authority-body-matched-mention-v1", "project_id": project.pk, "source_current": True,
        "selection": mention_selection(row),
        "requested_source_url": source["requested_url"], "final_source_url": source["url"], "target_url": evidence["target_url"],
        "prospect": {"review_id": row.pk, "prospect_id": str(row.prospect_id), "revision": row.revision, "state": row.state,
            "quote": row.intake["quote"], "relevance": row.intake["relevance"], "assignee_id": row.assignee_id,
            "mention_basis": "human_selected_quote_in_normalized_bounded_research_text_not_browser_verification"},
        "research": {"method": research["method"], "collection_method": row.research_job.method_version,
            **{key: research[key] for key in ("research_job_id", "source_index", "step_id", "artifact_id", "retrieved_at",
            "original_response_sha256", "source_size_bytes", "excerpt_truncated", "coverage")}},
        "static": {"job_id": observation["job_id"], "step_id": observation["step_id"], "artifact_id": observation["artifact_id"],
            "link_review_id": job.input_snapshot["link_review_id"], "observed_at": source["observed_at"], "method": source["method"],
            "parser_method": evidence["method"], "body_sha256": evidence["body_sha256"], "body_size_bytes": evidence["body_size_bytes"],
            "matching_target_count": count, "state": evidence["state"], "coverage": evidence["coverage"]},
        "body_match": "same_original_response_sha256_and_size_separate_dated_observations", "static_coverage_complete": complete,
        "state": state, "unlinked_or_lost_link": "not_established", "site_or_outreach_approval": "separate_human_workflows",
        "interpretation": "human_mention_body_matched_static_target_candidate_not_browser_whole_site_index_or_verified_unlinked_or_lost_proof"}
