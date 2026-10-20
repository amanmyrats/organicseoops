import hashlib
import json
from collections import defaultdict
from datetime import datetime
from urllib.parse import urlsplit

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from tenancy.models import Project
from tenancy.services import Action, require_project_action

from .crawling import CrawlScope, FetchDenied
from .diagnostics import _has_noindex, build_technical_diagnostics
from .models import CrawlRun, IndexationEvidenceSnapshot, JobCancellation, JobRun


METHOD_VERSION = "indexation-evidence-v1"
MAX_EVIDENCE_URLS = 40


def build_indexation_evidence(crawl_run_id):
    diagnostics = build_technical_diagnostics(crawl_run_id)
    run = CrawlRun.objects.select_related("job__actor", "project").get(pk=crawl_run_id)
    if diagnostics.crawl_run_id != run.pk or diagnostics.project_id != run.project_id:
        raise ValidationError("Indexation evidence requires matching technical diagnostics.")
    pages = list(run.pages.order_by("id"))
    scope = CrawlScope.for_project(run.project)
    input_hash = _hash_input(diagnostics, scope)
    existing = IndexationEvidenceSnapshot.objects.filter(crawl_run=run).first()
    if existing:
        if existing.input_hash != input_hash:
            raise ValidationError("Indexation evidence already exists for different crawl evidence.")
        return existing
    output = _reconcile(run, pages, diagnostics, scope)

    with transaction.atomic():
        job = JobRun.objects.select_for_update().select_related("actor").get(pk=run.job_id)
        project = Project.objects.select_for_update().get(pk=run.project_id)
        locked = CrawlRun.objects.select_for_update().get(pk=run.pk, job=job, project=project)
        current = build_technical_diagnostics(locked.pk)
        if current.pk != diagnostics.pk or _hash_input(current, CrawlScope.for_project(project)) != input_hash:
            raise ValidationError("Crawl evidence changed while indexation evidence was computed.")
        if JobCancellation.objects.filter(job=job).exists():
            raise ValidationError("Cancelled crawls cannot create indexation evidence.")
        try:
            require_project_action(project=project, user=job.actor, action=Action.LAUNCH_JOB)
        except PermissionDenied:
            raise ValidationError("The crawl actor can no longer create indexation evidence.") from None
        existing = IndexationEvidenceSnapshot.objects.filter(crawl_run=locked).first()
        if existing:
            if existing.input_hash != input_hash:
                raise ValidationError("Indexation evidence already exists for different crawl evidence.")
            return existing
        return IndexationEvidenceSnapshot.objects.create(
            crawl_run=locked, project=project, diagnostics=current,
            input_hash=input_hash, method_version=METHOD_VERSION, output=output,
        )


def _hash_input(diagnostics, scope):
    value = {
        "diagnostics_id": diagnostics.pk,
        "diagnostics_hash": diagnostics.input_hash,
        "diagnostics_method": diagnostics.method_version,
        "scope_hosts": sorted(scope.hosts),
        "method": METHOD_VERSION,
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _canonical_evidence(url, scope):
    if not url:
        return None, "not_declared"
    try:
        parts = urlsplit(url)
        if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
            return None, "redacted_parameterized_or_credentialed"
        return scope.validate_url(url), "in_scope"
    except (ValueError, FetchDenied):
        return None, "outside_or_invalid_scope"


def _reconcile(run, pages, diagnostics, scope):
    sources = defaultdict(set)
    observed = defaultdict(list)
    omitted_parameterized = set()
    excluded_out_of_scope = 0

    def add(url, source, page=None, role=""):
        nonlocal excluded_out_of_scope
        if not isinstance(url, str) or not url:
            return
        try:
            url = scope.validate_url(url)
        except FetchDenied:
            excluded_out_of_scope += 1
            return
        if urlsplit(url).query:
            omitted_parameterized.add(url)
            return
        sources[url].add(source)
        if page is not None:
            observed[url].append((page, role))

    for url in run.job.input_snapshot.get("seeds", []):
        add(url, "configured_entry")
    for url in run.discovery.get("sitemap_urls", []):
        add(url, "sitemap")
    for url in run.discovery.get("urls", []):
        add(url, "crawl_discovery")
    for page in pages:
        add(page.requested_url, "crawl_request", page, "requested")
        if page.final_url and page.final_url != page.requested_url:
            add(page.final_url, "redirect_final", page, "final")
        for link in page.links:
            if isinstance(link, dict) and link.get("internal"):
                add(link.get("url"), "observed_internal_link")
    urls = sorted(sources)
    evidence = []
    for url in urls[:MAX_EVIDENCE_URLS]:
        visits = []
        for page, role in observed.get(url, []):
            status = page.status_code
            redirected_request = role == "requested" and page.final_url and page.final_url != page.requested_url
            canonical, canonical_scope = _canonical_evidence(page.canonical_url, scope)
            directives = (
                "unknown_failed_or_unchecked" if page.error_category or status == 304 or status is None or redirected_request
                else "noindex_observed" if _has_noindex(page.robots_directives)
                else "no_noindex_observed"
            )
            visits.append({
                "crawl_page_id": page.pk,
                "observed_at": page.observed_at.isoformat(),
                "role": role,
                "status_code": status,
                "fetch_state": "failed" if page.error_category else "conditional_reuse" if status == 304
                else "redirect_observed" if redirected_request
                else "http_observed" if status is not None else "unknown",
                "directive_state": directives,
                "declared_canonical": None if redirected_request else canonical,
                "declared_canonical_scope": "unknown_redirect_source" if redirected_request else canonical_scope,
                "error_category": page.error_category or None,
            })
        conflicts = []
        if "sitemap" in sources[url] and any(visit["fetch_state"] == "redirect_observed" for visit in visits):
            conflicts.append("sitemap_redirect_candidate")
        if "sitemap" in sources[url] and any(
            visit["status_code"] is not None and visit["status_code"] >= 400
            or visit["directive_state"] == "noindex_observed" for visit in visits
        ):
            conflicts.append("sitemap_http_or_noindex_candidate")
        evidence.append({
            "url": url,
            "discovered_by": sorted(sources[url]),
            "crawlability": "observed" if visits else "unknown_not_checked",
            "fetch_observations": visits,
            "indexability_signals": conflicts,
            "engine_indexed_state": "unknown_no_engine_report",
            "engine_selected_canonical": None,
            "engine_report_scope": "unavailable",
        })
    return {
        "crawl_run_id": run.pk,
        "diagnostics_id": diagnostics.pk,
        "diagnostics_method": diagnostics.method_version,
        "coverage": {
            "state": diagnostics.output["coverage"]["state"],
            "reasons": diagnostics.output["coverage"]["reasons"],
            "robots_status": run.robots_status or "unknown",
            "unattributed_robots_skips": run.discovery.get("skipped_robots", 0),
            "omitted_parameterized_urls": len(omitted_parameterized),
            "omitted_clean_urls": max(len(urls) - MAX_EVIDENCE_URLS, 0),
            "out_of_scope_references": excluded_out_of_scope,
            "analytics_inventory": "unavailable",
            "engine_indexing_reports": "unavailable",
        },
        "interpretation": "crawl_and_sitemap_observations_are_not_engine_indexing_evidence",
        "urls": evidence,
    }


def reconcile_indexation_reports(*, project, user, crawl_run_id):
    """Read-only join of immutable crawl evidence and currently authorized indexed-version reports."""
    from integrations.models import SearchConsoleCoverageObservation
    from integrations.search_console_coverage_job import METHOD as COVERAGE_METHOD, _source

    require_project_action(project=project, user=user, action=Action.VIEW_PROJECT)
    snapshot = IndexationEvidenceSnapshot.objects.filter(project=project, crawl_run_id=crawl_run_id).first()
    if snapshot is None:
        raise ValidationError("Indexation evidence is unavailable for this project.")
    scope = CrawlScope.for_project(project)
    rows = []
    for item in snapshot.output["urls"][:MAX_EVIDENCE_URLS]:
        url = item["url"]
        try:
            if urlsplit(url).query or urlsplit(url).fragment or scope.validate_url(url) != url:
                continue
        except (FetchDenied, ValueError):
            continue
        rows.append({**item, "engine_reports": []})
    by_url = {item["url"]: item for item in rows}
    observations = list(SearchConsoleCoverageObservation.objects.filter(
        project=project, source=SearchConsoleCoverageObservation.Source.INSPECTION,
        requested_url__in=by_url,
        job__status__in=["succeeded", "partially_succeeded"],
    ).select_related("job__actor", "connection", "grant").order_by("-collected_at", "-pk")[:201])
    seen = set()
    for item in observations[:200]:
        identity = (item.requested_url, item.connection_id)
        if identity in seen or item.connection.project_id != project.pk or item.grant.project_id != project.pk:
            continue
        job = item.job
        if (type(item.result) is not dict or job.project_id != project.pk or job.organization_id != project.organization_id
            or job.handler != "collect_search_console_coverage" or job.method_version != COVERAGE_METHOD
            or item.external_property_id != item.connection.external_property_id
            or item.grant.credential_reference != item.connection.credential_reference
            or item.result.get("inspection_url") != item.requested_url
            or item.result.get("method") != "google_indexed_version_only"
            or item.result.get("indexed_state") not in {"reported_indexed", "reported_not_indexed", "unknown"}):
            continue
        try:
            require_project_action(project=project, user=job.actor, action=Action.MANAGE_PROJECT)
            _source(project=project, organization=project.organization,
                    data=job.input_snapshot, config=job.config_snapshot)
        except (PermissionDenied, ValidationError, TypeError, KeyError):
            continue
        seen.add(identity)
        url_row = by_url[item.requested_url]
        result = item.result
        visits = url_row["fetch_observations"]
        newest_local = max((visit["observed_at"] for visit in visits), default=None)
        indexed_at = result.get("last_crawl_at")
        try:
            stale = (datetime.fromisoformat(indexed_at) < datetime.fromisoformat(newest_local)
                     if newest_local and indexed_at else None)
        except (TypeError, ValueError):
            stale = None
            indexed_at = None
        signals = []
        if stale is False and result["indexed_state"] == "reported_indexed":
            if any(visit["directive_state"] == "noindex_observed" for visit in visits):
                signals.append("local_noindex_vs_google_indexed_candidate")
            if any(visit["status_code"] is not None and visit["status_code"] >= 400 for visit in visits):
                signals.append("local_http_error_vs_google_indexed_candidate")
        declared = next((visit["declared_canonical"] for visit in reversed(visits)
                         if visit["declared_canonical"]), None)
        selected = result.get("google_canonical")
        if stale is False and declared and selected and declared != selected:
            signals.append("declared_vs_google_selected_canonical_candidate")
        url_row["engine_reports"].append({
            "provider": item.connection.provider, "property": item.external_property_id,
            "connection_id": item.connection_id, "observation_id": item.pk,
            "method": "google_indexed_version_only", "collected_at": item.collected_at.isoformat(),
            "engine_last_crawl_at": indexed_at, "indexed_state": result["indexed_state"],
            "engine_selected_canonical": selected, "declared_canonical": result.get("declared_canonical"),
            "stale_relative_to_local_crawl": stale, "disagreement_candidates": signals,
        })
    return {"crawl_run_id": snapshot.crawl_run_id, "diagnostics_id": snapshot.diagnostics_id,
            "project_id": project.pk,
            "crawl_observed_at": snapshot.observed_at.isoformat(),
            "coverage": {**snapshot.output["coverage"],
                         "engine_indexing_reports": "limited_recent_window" if len(observations) > 200 else
                         "indexed_version_per_url_where_authorized" if seen else "unavailable"},
            "interpretation": "local_crawl_is_not_engine_indexing;_google_inspection_is_indexed_version_only",
            "urls": rows}
