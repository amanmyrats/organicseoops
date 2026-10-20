"""D143 current evidence and D144 bounded operational history; customer first value is unestablished."""
import hashlib
import json
import re
from datetime import datetime
from urllib.parse import urlsplit

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.utils import timezone

from config.artifacts import ArtifactNotFound, ArtifactStorageError, ArtifactValidationError
from integrations.oauth import _verified
from tenancy.artifacts import project_artifact_scope, read_project_artifact
from tenancy.models import Organization, Project, ProjectConfiguration, normalize_origin
from tenancy.services import Action, require_project_action
from .crawler import FIRST_AUDIT_ENTRYPOINT, HOST_DELAY_SECONDS, METHOD_VERSION, validate_crawl_input, validate_url_parameter_policy
from .crawling import CrawlScope, FetchDenied
from .models import (CrawlPageSnapshot, CrawlRun, FirstBoundedAuditCompletion, JobCancellation, JobRun,
                     JobStatus, JobStep, UsageReservation)

METHOD = "bounded-first-audit-completion-evidence-v1"
COMPLETION_METHOD = "bounded-first-audit-completion-v1"


def _dates(*values):
    if (any(not isinstance(value, datetime) or timezone.is_naive(value) for value in values)
        or any(left > right for left, right in zip(values, values[1:])) or values[-1] > timezone.now()):
        raise ValidationError("Audit evidence needs original ordered aware nonfuture dates.")


def _page_evidence(page):
    return {"page_id": page.pk, "requested_url": page.requested_url, "final_url": page.final_url,
        "status_code": page.status_code, "redirect_chain": page.redirect_chain, "reused_from_id": page.reused_from_id,
        "observed_at": page.observed_at.isoformat(), "sha256": page.content_hash, "artifact_id": page.raw_artifact_id}


def _url(value, scope, origins):
    try:
        if scope.validate_url(value) != value or normalize_origin(f"{urlsplit(value).scheme}://{urlsplit(value).netloc}") not in origins:
            raise FetchDenied("outside_scope")
    except (FetchDenied, ValidationError):
        raise ValidationError("Audit evidence no longer matches exact configured origins.") from None


def _source(*, project, actor, job_id):
    project = Project.objects.select_related("organization").filter(pk=project.pk, organization_id=project.organization_id).first()
    if project is None:
        raise PermissionDenied
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    choice = ProjectConfiguration.objects.filter(project=project).values_list("source_choice", flat=True).first()
    if choice == "synthetic_demo":
        raise ValidationError("Synthetic demo is not actual audit evidence.")
    job = JobRun.objects.select_related("actor").filter(pk=job_id, project=project, organization=project.organization,
        handler="crawl_site", method_version=METHOD_VERSION, status=JobStatus.SUCCEEDED).first()
    if job is None:
        raise PermissionDenied
    require_project_action(project=project, user=job.actor, action=Action.LAUNCH_JOB)
    if not _verified(job.actor):
        raise PermissionDenied
    validate_crawl_input(job.input_snapshot)
    scope = CrawlScope.for_project(project)
    origins = sorted({project.canonical_origin, *project.domain_aliases.values_list("origin", flat=True)})
    if (type(job.config_snapshot) is not dict or job.input_snapshot["page_limit"] > 5
        or job.input_snapshot["seeds"] != [scope.validate_url(project.canonical_origin)]
        or job.config_snapshot.get("first_audit_entrypoint") != FIRST_AUDIT_ENTRYPOINT
        or job.config_snapshot.get("host_delay_seconds") != HOST_DELAY_SECONDS
        or job.error_category or JobCancellation.objects.filter(job=job).exists()):
        raise ValidationError("Choose actual marked successful bounded audit evidence.")
    validate_url_parameter_policy(job.config_snapshot.get("url_parameter_policy"))
    run = CrawlRun.objects.filter(job=job, project=project, organization=project.organization).first()
    usage = UsageReservation.objects.filter(job=job, project=project, organization=project.organization,
        provider="crawler", state=UsageReservation.State.SETTLED).first()
    step = JobStep.objects.filter(job=job, sequence=2, name="Fetch pages", status=JobStep.Status.SUCCEEDED,
        progress_percent=100, error_category="").first()
    discovery_step = JobStep.objects.filter(job=job, sequence=1, name="Discover crawl scope",
        status=JobStep.Status.SUCCEEDED, error_category="").first()
    if run is None or usage is None or step is None or discovery_step is None:
        raise ValidationError("Actual completed crawl, successful steps and settled usage are required.")
    pages = list(CrawlPageSnapshot.objects.filter(crawl_run=run).select_related("raw_artifact")[:6])
    count = len(pages)
    if (not 1 <= count <= run.page_limit <= 5 or run.page_limit != job.input_snapshot["page_limit"]
        or run.pages_attempted != count or run.pages_observed != count
        or usage.actual_units != count or usage.reserved_units != run.page_limit
        or step.output != {"attempted": count, "observed": count} or run.robots_status not in {"available", "missing"}):
        raise ValidationError("Actual page counts, usage and completion steps must agree.")
    _dates(job.created_at, run.started_at, discovery_step.created_at, job.updated_at,
           run.completed_at, step.created_at, usage.settled_at)
    discovery = run.discovery
    counters = ("sitemaps_fetched", "sitemap_failures", "denied_urls", "queue_remaining", "skipped_family",
                "skipped_parameter_variants", "skipped_robots")
    if (type(discovery) is not dict or set(discovery) != set(counters) | {
            "truncated", "urls", "sitemap_urls", "sitemap_failure_details", "robots_failures"}
        or any(type(discovery.get(key)) is not int or discovery[key] < 0 for key in counters)
        or type(discovery.get("truncated")) is not bool
        or any(discovery[key] for key in ("sitemap_failures", "queue_remaining", "skipped_family",
                                         "skipped_parameter_variants", "skipped_robots"))
        or discovery.get("sitemap_failure_details") != [] or discovery.get("robots_failures") != []):
        raise ValidationError("Successful bounded discovery coverage is unavailable or inconsistent.")
    for key in ("urls", "sitemap_urls"):
        urls = discovery.get(key)
        if type(urls) is not list or len(urls) > run.page_limit * 4 + 1:
            raise ValidationError("Audit discovery inventory must remain bounded.")
        for url in urls:
            _url(url, scope, origins)
    if discovery_step.output != {key: discovery[key] for key in (
        "sitemaps_fetched", "sitemap_failures", "sitemap_failure_details", "denied_urls", "truncated")}:
        raise ValidationError("Original discovery step no longer matches crawl evidence.")
    expected_output = {"pages_attempted": count, "pages_observed": count, "robots_status": run.robots_status,
        "discovery_truncated": discovery["truncated"], **{key: discovery[key] for key in (
            "sitemap_failures", "skipped_family", "skipped_parameter_variants", "skipped_robots")}}
    if job.output != expected_output:
        raise ValidationError("Actual job output differs from completed crawl evidence.")
    artifacts, observations = [], []
    for page in pages:
        if page.project_id != project.pk or page.error_category:
            raise ValidationError("Page evidence is foreign or failed.")
        _dates(discovery_step.created_at, page.observed_at, job.updated_at)
        for url in (page.requested_url, page.final_url):
            _url(url, scope, origins)
        if type(page.redirect_chain) is not list or len(page.redirect_chain) > 5:
            raise ValidationError("Page redirect evidence must remain bounded.")
        for hop in page.redirect_chain:
            if (type(hop) is not dict or set(hop) != {"url", "status"} or type(hop["status"]) is not int
                or hop["status"] not in {301, 302, 303, 307, 308}):
                raise ValidationError("Page redirect evidence is invalid.")
            _url(hop["url"], scope, origins)
        observations.append(_page_evidence(page))
        artifact = page.raw_artifact
        if page.reused_from_id is not None or page.status_code is None or not 200 <= page.status_code < 300 or artifact is None:
            continue
        if (artifact.job_id != job.pk or artifact.project_id != project.pk or artifact.content_type != "text/html"
            or not 1 <= artifact.size_bytes <= 2 * 1024 * 1024 or not re.fullmatch(r"[0-9a-f]{64}", page.content_hash)
            or artifact.key != f"{project_artifact_scope(project)}/jobs/{job.pk}/{page.content_hash[:32]}.html"):
            raise ValidationError("Successful HTML must retain exact same-job private body evidence.")
        _dates(run.started_at, artifact.created_at, page.observed_at)
        artifacts.append({"id": artifact.pk, "key": artifact.key, "sha256": page.content_hash,
                          "size_bytes": artifact.size_bytes, "created_at": artifact.created_at.isoformat()})
    if not artifacts:
        raise ValidationError("At least one actual same-job non-reused successful HTML page is required.")
    source = {"method": METHOD, "organization_id": project.organization_id, "project_id": project.pk,
        "canonical_origin": project.canonical_origin, "configured_origins": origins, "source_choice": choice,
        "job_id": job.pk, "actor_id": job.actor_id, "retry_of_id": job.retry_of_id, "crawl_run_id": run.pk,
        "crawl_method": job.method_version, "input_snapshot": job.input_snapshot, "config_snapshot": job.config_snapshot,
        "job_created_at": job.created_at.isoformat(), "job_updated_at": job.updated_at.isoformat(),
        "run_started_at": run.started_at.isoformat(), "run_completed_at": run.completed_at.isoformat(),
        "discovery_step_id": discovery_step.pk, "discovery_step_created_at": discovery_step.created_at.isoformat(),
        "fetch_step_id": step.pk, "fetch_step_created_at": step.created_at.isoformat(),
        "usage_id": usage.pk, "usage_settled_at": usage.settled_at.isoformat(), "actual_units": usage.actual_units,
        "page_limit": run.page_limit, "robots_status": run.robots_status, "discovery": discovery, "pages": observations,
        "coverage": "bounded_discovered_http_sample_not_complete_site", "first_ever_completion": "not_established",
        "first_value": "not_established"}
    return project, source, artifacts


def first_audit_completion_source(*, project, actor, job_id):
    """Read private body integrity, then recheck current exact source and authority without writes/fetches."""
    if type(job_id) is not int or not 1 <= job_id < 2**53:
        raise ValidationError("Choose one exact stored bounded-audit job.")
    project, source, artifacts = _source(project=project, actor=actor, job_id=job_id)
    for artifact in artifacts:
        try:
            body = read_project_artifact(project=project, key=artifact["key"])
        except (ArtifactNotFound, ArtifactStorageError, ArtifactValidationError):
            raise ValidationError("Private audit body evidence is unavailable.") from None
        if len(body) != artifact["size_bytes"] or hashlib.sha256(body).hexdigest() != artifact["sha256"]:
            raise ValidationError("Private audit body evidence no longer matches its original digest and size.")
    _current_project, current, current_artifacts = _source(project=project, actor=actor, job_id=job_id)
    if current != source or current_artifacts != artifacts:
        raise ValidationError("Audit source changed during private evidence inspection.")
    return {**source, "successful_html": [{key: value for key, value in row.items() if key != "key"} for row in artifacts]}


def completion_source_digest(source):
    return hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def bounded_completion_capture_source(*, job):
    """Genuine original finalization source; old/mixed-worker gaps cannot become later history."""
    organization = Organization.objects.get(pk=job.organization_id)
    completed_at = CrawlRun.objects.filter(job=job).values_list("completed_at", flat=True).first()
    if (not connection.in_atomic_block or completed_at is None
        or getattr(job, "_first_audit_completed_at", None) != completed_at
        or organization.first_audit_tracking != COMPLETION_METHOD
        or JobRun.objects.filter(organization=organization, handler="crawl_site", status=JobStatus.SUCCEEDED,
            config_snapshot__first_audit_entrypoint=FIRST_AUDIT_ENTRYPOINT).exclude(pk=job.pk).exists()):
        raise ValidationError("Bounded completion has unknown prospective tracking coverage.")
    source = first_audit_completion_source(project=job.project, actor=job.actor, job_id=job.pk)
    observed_at = completed_at
    _dates(organization.created_at, job.created_at, observed_at)
    return {"method": COMPLETION_METHOD, "tracking_started_at": organization.created_at.isoformat(),
            "observed_at": observed_at.isoformat(), "evidence": source,
            "interpretation": "first_prospectively_tracked_bounded_completion_not_customer_first_value"}


def capture_bounded_completion(*, job):
    """Only owning org-first worker finalization calls this, in the same success/usage transaction."""
    if not connection.in_atomic_block:
        raise RuntimeError("Bounded completion requires atomic worker finalization.")
    organization = Organization.objects.get(pk=job.organization_id)
    if (job.status != JobStatus.SUCCEEDED or job.config_snapshot.get("first_audit_entrypoint") != FIRST_AUDIT_ENTRYPOINT
        or organization.first_audit_tracking != COMPLETION_METHOD
        or FirstBoundedAuditCompletion.objects.filter(organization=organization).exists()):
        return
    try:
        source = bounded_completion_capture_source(job=job)
        FirstBoundedAuditCompletion.objects.create(organization=organization, project=job.project, job=job,
            observed_at=job.crawl_run.completed_at, source=source, source_digest=completion_source_digest(source))
    except (PermissionDenied, ValidationError):
        # A successful marked completion without current complete proof is a gap, never later backfill.
        Organization.objects.filter(pk=organization.pk).update(first_audit_tracking=None)


def _historical_completion(*, project, actor):
    project = Project.objects.select_related("organization").filter(pk=project.pk, organization_id=project.organization_id).first()
    if project is None:
        raise PermissionDenied
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    if ProjectConfiguration.objects.filter(project=project, source_choice="synthetic_demo").exists():
        raise ValidationError("Inspect actual history separately from synthetic demo.")
    saved = FirstBoundedAuditCompletion.objects.select_related("job", "job__crawl_run").filter(
        project=project, organization=project.organization).first()
    base = {"method": COMPLETION_METHOD, "organization_id": project.organization_id, "project_id": project.pk,
        "scope": "historical_organization_first_bounded_completion_within_selected_project_not_current_use_or_first_value"}
    if saved is None:
        # Do not disclose a restricted different project's organization-first observation.
        return project, {**base, "state": "not_observed_for_project" if project.organization.first_audit_tracking == COMPLETION_METHOD
                         else "unknown"}, []
    job, source = saved.job, saved.source
    try:
        run = job.crawl_run
        evidence = source["evidence"]
        discovery_step = JobStep.objects.get(pk=evidence["discovery_step_id"], job=job, sequence=1,
            name="Discover crawl scope", status="succeeded", error_category="")
        step = JobStep.objects.get(pk=evidence["fetch_step_id"], job=job, sequence=2,
            name="Fetch pages", status="succeeded", progress_percent=100, error_category="")
        usage = UsageReservation.objects.get(pk=evidence["usage_id"], job=job, project=project,
            organization=project.organization, state="settled", provider="crawler")
        pages = list(run.pages.all()[:6])
        if (set(source) != {"method", "tracking_started_at", "observed_at", "evidence", "interpretation"}
            or source["method"] != COMPLETION_METHOD or completion_source_digest(source) != saved.source_digest
            or source["interpretation"] != "first_prospectively_tracked_bounded_completion_not_customer_first_value"
            or source["observed_at"] != saved.observed_at.isoformat() or saved.observed_at != run.completed_at
            or source["tracking_started_at"] != project.organization.created_at.isoformat()
            or job.project_id != project.pk or job.organization_id != project.organization_id
            or job.status != JobStatus.SUCCEEDED or job.error_category or job.handler != "crawl_site"
            or job.config_snapshot.get("first_audit_entrypoint") != FIRST_AUDIT_ENTRYPOINT
            or run.project_id != project.pk or run.organization_id != project.organization_id
            or evidence["method"] != METHOD or evidence["job_id"] != job.pk or evidence["crawl_run_id"] != run.pk
            or evidence["project_id"] != project.pk or evidence["organization_id"] != project.organization_id
            or evidence["actor_id"] != job.actor_id or evidence["retry_of_id"] != job.retry_of_id
            or evidence["input_snapshot"] != job.input_snapshot or evidence["config_snapshot"] != job.config_snapshot
            or evidence["crawl_method"] != job.method_version or job.method_version != METHOD_VERSION
            or evidence["job_created_at"] != job.created_at.isoformat()
            or evidence["job_updated_at"] != job.updated_at.isoformat()
            or evidence["run_started_at"] != run.started_at.isoformat()
            or evidence["run_completed_at"] != run.completed_at.isoformat()
            or evidence["fetch_step_created_at"] != step.created_at.isoformat()
            or evidence["discovery_step_created_at"] != discovery_step.created_at.isoformat()
            or evidence["usage_settled_at"] != usage.settled_at.isoformat()
            or not 1 <= len(pages) == run.pages_observed == run.pages_attempted == usage.actual_units <= run.page_limit <= 5
            or evidence["actual_units"] != usage.actual_units or evidence["page_limit"] != run.page_limit
            or usage.reserved_units != run.page_limit or step.output != {"attempted": len(pages), "observed": len(pages)}
            or evidence["discovery"] != run.discovery or evidence["robots_status"] != run.robots_status
            or evidence["pages"] != [_page_evidence(page) for page in pages]
            or evidence["first_ever_completion"] != "not_established" or evidence["first_value"] != "not_established"
            or evidence["coverage"] != "bounded_discovered_http_sample_not_complete_site"
            or any(page.project_id != project.pk or page.error_category for page in pages)):
            raise ValueError
        _dates(project.organization.created_at, job.created_at, run.started_at, job.updated_at, saved.observed_at,
               step.created_at, usage.settled_at)
        html = evidence["successful_html"]
        if type(html) is not list or not 1 <= len(html) <= len(pages):
            raise ValueError
        if [row["id"] for row in html] != [page.raw_artifact_id for page in pages if page.raw_artifact_id is not None
            and page.reused_from_id is None and page.status_code is not None and 200 <= page.status_code < 300]:
            raise ValueError
        artifacts = []
        for item in html:
            page = next(page for page in pages if page.raw_artifact_id == item["id"] and page.reused_from_id is None
                        and page.status_code is not None and 200 <= page.status_code < 300)
            artifact = page.raw_artifact
            if (set(item) != {"id", "sha256", "size_bytes", "created_at"} or artifact.job_id != job.pk
                or artifact.project_id != project.pk or artifact.content_type != "text/html"
                or artifact.key != f"{project_artifact_scope(project)}/jobs/{job.pk}/{page.content_hash[:32]}.html"
                or item["sha256"] != page.content_hash or item["size_bytes"] != artifact.size_bytes
                or not 1 <= artifact.size_bytes <= 2 * 1024 * 1024 or item["created_at"] != artifact.created_at.isoformat()):
                raise ValueError
            artifacts.append({**item, "key": artifact.key})
    except (KeyError, TypeError, ValueError, AttributeError, StopIteration, CrawlRun.DoesNotExist,
            JobStep.DoesNotExist, UsageReservation.DoesNotExist):
        raise ValidationError("Historical bounded completion evidence needs review.") from None
    return project, {**base, "state": "recorded", "job_id": job.pk, "source_digest": saved.source_digest,
        "observed_at": saved.observed_at.isoformat(), "tracking_started_at": source["tracking_started_at"],
        "page_limit": run.page_limit, "pages_observed": len(pages), "successful_html_pages": len(html),
        "coverage": evidence["coverage"], "robots_status": evidence["robots_status"],
        "discovery_truncated": evidence["discovery"]["truncated"]}, artifacts


def inspect_bounded_completion(*, project, actor):
    """Minimized historical readback; original actor's later role loss is not erasure or current-use authority."""
    project, result, artifacts = _historical_completion(project=project, actor=actor)
    for artifact in artifacts:
        try:
            body = read_project_artifact(project=project, key=artifact["key"])
        except (ArtifactNotFound, ArtifactStorageError, ArtifactValidationError):
            raise ValidationError("Historical private bounded-audit body is unavailable.") from None
        if len(body) != artifact["size_bytes"] or hashlib.sha256(body).hexdigest() != artifact["sha256"]:
            raise ValidationError("Historical private bounded-audit body has changed.")
    _project, current, current_artifacts = _historical_completion(project=project, actor=actor)
    if current != result or current_artifacts != artifacts:
        raise ValidationError("Historical bounded completion changed during private inspection.")
    return result
