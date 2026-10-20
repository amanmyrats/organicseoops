import hashlib
import json
import re
from collections import Counter, deque
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from config.artifacts import ArtifactNotFound, ArtifactStorageError, read_private_artifact
from tenancy.models import Project
from tenancy.services import Action, require_project_action

from .crawler import PageParser, crawl_url_identity, snapshotted_url_parameter_policy
from .crawling import CrawlScope, FetchDenied
from .models import (
    CrawlRun,
    JobCancellation,
    JobRun,
    JobStatus,
    RenderedPageSnapshot,
    TechnicalDiagnosticsSnapshot,
)
from .renderer import VisibleTextParser


METHOD_VERSION = "technical-diagnostics-v1"
RULESET_VERSION = "schema-observation-2026-09-25-v1"
MAX_VARIANTS = 200
MAX_SCHEMA_NODES = 500
PAGINATION_PARAMETERS = frozenset({"page", "paged", "p", "offset", "start", "cursor"})


def build_technical_diagnostics(crawl_run_id):
    crawl_run = CrawlRun.objects.select_related("job__actor", "project").get(pk=crawl_run_id)
    if crawl_run.completed_at is None or crawl_run.job.status not in {
        JobStatus.SUCCEEDED, JobStatus.PARTIALLY_SUCCEEDED, JobStatus.FAILED,
    }:
        raise ValidationError("Technical diagnostics require a completed crawl.")
    if JobCancellation.objects.filter(job=crawl_run.job).exists():
        raise ValidationError("Cancelled crawls cannot create technical diagnostics.")
    try:
        require_project_action(project=crawl_run.project, user=crawl_run.job.actor, action=Action.LAUNCH_JOB)
    except PermissionDenied:
        raise ValidationError("The crawl actor can no longer create diagnostics.") from None

    pages = list(crawl_run.pages.select_related("raw_artifact").order_by("observed_at", "id"))
    rendered = {}
    observations = RenderedPageSnapshot.objects.filter(
        crawl_page__crawl_run=crawl_run,
    ).select_related("attempt", "rendered_artifact").order_by("crawl_page_id", "-observed_at", "-id")
    for observation in observations:
        rendered.setdefault(observation.crawl_page_id, observation)
    scope = CrawlScope.for_project(crawl_run.project)
    input_hash = _input_hash(crawl_run, pages, rendered, scope)
    existing = TechnicalDiagnosticsSnapshot.objects.filter(crawl_run=crawl_run).first()
    if existing:
        if existing.input_hash != input_hash:
            raise ValidationError("Technical diagnostics already exist for different crawl evidence.")
        return existing

    coverage = _coverage(crawl_run, pages)
    output = {
        "coverage": coverage,
        "canonicals": _canonical_diagnostics(pages, rendered, scope),
        "link_graph": _link_graph(crawl_run, pages, coverage),
        "url_variants": _url_variants(crawl_run, pages, scope),
        "structured_data": _structured_data_diagnostics(pages, rendered, scope),
    }
    with transaction.atomic():
        locked_job = JobRun.objects.select_for_update().select_related("actor").get(pk=crawl_run.job_id)
        locked_project = Project.objects.select_for_update().get(pk=crawl_run.project_id)
        locked = CrawlRun.objects.select_for_update().get(pk=crawl_run.pk, job=locked_job, project=locked_project)
        locked.job = locked_job
        locked.project = locked_project
        locked_pages = list(
            locked.pages.select_for_update(of=("self",)).select_related("raw_artifact").order_by("observed_at", "id")
        )
        current_rendered = {}
        for observation in RenderedPageSnapshot.objects.filter(
            crawl_page__crawl_run=locked,
        ).select_related("attempt", "rendered_artifact").order_by("crawl_page_id", "-observed_at", "-id"):
            current_rendered.setdefault(observation.crawl_page_id, observation)
        current_scope = CrawlScope.for_project(locked_project)
        if _input_hash(locked, locked_pages, current_rendered, current_scope) != input_hash:
            raise ValidationError("Crawl evidence changed while diagnostics were computed.")
        if JobCancellation.objects.filter(job=locked.job).exists():
            raise ValidationError("Cancelled crawls cannot create technical diagnostics.")
        try:
            require_project_action(project=locked_project, user=locked_job.actor, action=Action.LAUNCH_JOB)
        except PermissionDenied:
            raise ValidationError("The crawl actor can no longer create diagnostics.") from None
        existing = TechnicalDiagnosticsSnapshot.objects.filter(crawl_run=locked).first()
        if existing:
            if existing.input_hash != input_hash:
                raise ValidationError("Technical diagnostics already exist for different crawl evidence.")
            return existing
        return TechnicalDiagnosticsSnapshot.objects.create(
            crawl_run=locked,
            project=locked_project,
            input_hash=input_hash,
            method_version=METHOD_VERSION,
            ruleset_version=RULESET_VERSION,
            output=output,
        )


def _input_hash(crawl_run, pages, rendered, scope):
    evidence = {
        "crawl_run": crawl_run.pk,
        "job_status": crawl_run.job.status,
        "job_input": crawl_run.job.input_snapshot,
        "job_config": crawl_run.job.config_snapshot,
        "crawl_method_version": crawl_run.job.method_version,
        "scope_hosts": sorted(scope.hosts),
        "page_limit": crawl_run.page_limit,
        "pages_attempted": crawl_run.pages_attempted,
        "pages_observed": crawl_run.pages_observed,
        "completed_at": crawl_run.completed_at.isoformat() if crawl_run.completed_at else None,
        "discovery": crawl_run.discovery,
        "pages": [{
            "id": page.pk,
            "requested_url": page.requested_url,
            "final_url": page.final_url,
            "redirect_chain": page.redirect_chain,
            "status_code": page.status_code,
            "canonical_url": page.canonical_url,
            "robots_directives": page.robots_directives,
            "links": page.links,
            "structured_data": page.structured_data,
            "structured_data_errors": page.structured_data_errors,
            "content_hash": page.content_hash,
            "error_category": page.error_category,
        } for page in pages],
        "rendered": [{
            "id": observation.pk,
            "page": page_id,
            "content_hash": observation.content_hash,
            "canonical_url": observation.canonical_url,
            "robots_directives": observation.robots_directives,
            "links": observation.links,
            "comparison": observation.comparison,
            "method_version": observation.method_version,
        } for page_id, observation in sorted(rendered.items())],
    }
    try:
        encoded = json.dumps(evidence, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    except (TypeError, ValueError):
        raise ValidationError("Crawl evidence is not valid JSON.") from None
    return hashlib.sha256(encoded).hexdigest()


def _coverage(crawl_run, pages):
    discovery = crawl_run.discovery
    reasons = []
    if crawl_run.job.status != JobStatus.SUCCEEDED:
        reasons.append(f"job_{crawl_run.job.status}")
    for key in (
        "queue_remaining", "sitemap_failures", "denied_urls", "skipped_family", "skipped_parameter_variants",
        "skipped_robots",
    ):
        if discovery.get(key):
            reasons.append(key)
    if discovery.get("truncated"):
        reasons.append("discovery_truncated")
    if any(page.error_category for page in pages):
        reasons.append("page_failures")
    return {
        "state": "partial" if reasons else "complete_for_crawl_scope",
        "reasons": sorted(set(reasons)),
        "pages_attempted": crawl_run.pages_attempted,
        "pages_observed": crawl_run.pages_observed,
        "page_limit": crawl_run.page_limit,
        "configured_entries": len(crawl_run.job.input_snapshot.get("seeds", [])),
        "discovered_inventory": len(discovery.get("urls", [])),
        "sitemap_inventory": (
            {"state": "available", "urls": len(discovery["sitemap_urls"])}
            if isinstance(discovery.get("sitemap_urls"), list)
            else {"state": "not_recorded", "urls": None}
        ),
        "analytics_inventory": "unavailable",
    }


def _canonical_diagnostics(pages, rendered, scope):
    page_by_url = {page.requested_url: (page, "requested") for page in pages}
    for page in pages:
        if page.final_url:
            page_by_url.setdefault(page.final_url, (page, "final"))
    target_counts = Counter(page.canonical_url for page in pages if page.canonical_url)
    observations = []
    for page in pages:
        raw = _canonical_target(page.canonical_url, page_by_url, scope)
        render = rendered.get(page.pk)
        rendered_target = _canonical_target(render.canonical_url, page_by_url, scope) if render else None
        conflicts = []
        browser_observations = []
        if raw.get("target_redirects"):
            conflicts.append("canonical_target_redirects")
        if raw.get("target_status") not in {None, 200, 304}:
            conflicts.append("canonical_target_non_200")
        if raw.get("target_state") == "failed_observation":
            conflicts.append("canonical_target_failed_observation")
        if raw.get("target_noindex"):
            conflicts.append("canonical_target_noindex")
        if raw.get("target_declared_canonical") not in {None, "", page.canonical_url}:
            conflicts.append("canonical_chain")
        if render and render.canonical_url != page.canonical_url:
            if render.comparison.get("completeness") == "complete_for_supplied_html":
                conflicts.append("raw_rendered_disagreement")
            else:
                browser_observations.append("partial_raw_rendered_difference")
        observations.append({
            "url": page.final_url or page.requested_url,
            "raw": raw,
            "rendered": ({
                **rendered_target,
                "completeness": render.comparison.get("completeness", "unknown"),
                "method_version": render.method_version,
            } if render else {"state": "not_observed"}),
            "conflicts": sorted(set(conflicts)),
            "browser_observations": browser_observations,
        })
    return {
        "observations": observations,
        "shared_targets": [
            {"url": url, "source_count": count, "interpretation": "review_candidate_not_conflict"}
            for url, count in sorted(target_counts.items()) if count > 1
        ],
    }


def _canonical_target(declared_url, page_by_url, scope):
    if not declared_url:
        return {"declared_url": "", "scope": "absent", "target_state": "unknown"}
    try:
        normalized = scope.validate_url(declared_url)
    except FetchDenied:
        return {"declared_url": declared_url, "scope": "outside_scope", "target_state": "unknown"}
    matched = page_by_url.get(normalized)
    if matched is None:
        return {"declared_url": normalized, "scope": "in_scope", "target_state": "unchecked"}
    target, matched_as = matched
    if target.status_code == 304:
        target_state = "conditional_reuse"
    else:
        target_state = "observed" if not target.error_category else "failed_observation"
    return {
        "declared_url": normalized,
        "scope": "in_scope",
        "target_state": target_state,
        "matched_as": matched_as,
        "target_status": target.status_code,
        "target_effective_status": "unknown" if target.status_code == 304 else target.status_code,
        "target_redirects": len(target.redirect_chain) if matched_as == "requested" else 0,
        "target_noindex": _has_noindex(target.robots_directives),
        "target_declared_canonical": target.canonical_url,
    }


def _has_noindex(directives):
    return any(
        token.strip().lower() == "noindex"
        for directive in directives if isinstance(directive, dict)
        for token in directive.get("content", "").replace(";", ",").split(",")
    )


def _link_graph(crawl_run, pages, coverage):
    lookup = {page.requested_url: (page.requested_url, "requested") for page in pages}
    for page in pages:
        if page.final_url:
            lookup.setdefault(page.final_url, (page.requested_url, "final"))
    edges = {page.requested_url: set() for page in pages}
    inbound = Counter()
    unknown_targets = set()
    for page in pages:
        for link in page.links:
            if not isinstance(link, dict) or not link.get("internal") or not isinstance(link.get("url"), str):
                continue
            matched = lookup.get(link["url"])
            if matched is None:
                unknown_targets.add(link["url"])
            else:
                target = matched[0]
            if matched is not None and target not in edges[page.requested_url]:
                edges[page.requested_url].add(target)
                inbound[target] += 1
    entry_mappings = []
    entries = set()
    for seed in crawl_run.job.input_snapshot.get("seeds", []):
        matched = lookup.get(seed)
        if matched is None:
            entry_mappings.append({"configured_url": seed, "state": "unobserved"})
        else:
            node_url, matched_as = matched
            entries.add(node_url)
            entry_mappings.append({
                "configured_url": seed, "state": "observed", "node_url": node_url, "matched_as": matched_as,
            })
    depth = {entry: 0 for entry in entries}
    pending = deque(entries)
    while pending:
        source = pending.popleft()
        for target in edges[source]:
            if target not in depth:
                depth[target] = depth[source] + 1
                pending.append(target)
    discovery_urls = set(crawl_run.discovery.get("urls", []))
    sitemap_urls = set(crawl_run.discovery.get("sitemap_urls", []))
    nodes = []
    for page in pages:
        url = page.requested_url
        if url in entries:
            orphan_status = "entry"
        elif inbound[url]:
            orphan_status = "not_candidate"
        else:
            orphan_status = "candidate" if coverage["state"] == "complete_for_crawl_scope" else "unknown_partial_coverage"
        node_depth = depth.get(url)
        if node_depth is not None:
            depth_state = "observed"
        elif coverage["state"] == "complete_for_crawl_scope":
            depth_state = "unreachable_candidate"
        else:
            depth_state = "unknown_partial_coverage"
        nodes.append({
            "url": url,
            "final_url": page.final_url,
            "depth": node_depth,
            "depth_state": depth_state,
            "inbound_links": inbound[url],
            "outbound_observed_links": len(edges[url]),
            "orphan_status": orphan_status,
            "weakly_connected_candidate": node_depth is not None and (
                node_depth >= 3 or url not in entries and inbound[url] <= 1
            ),
            "in_discovery_inventory": url in discovery_urls or page.final_url in discovery_urls,
            "in_sitemap_inventory": url in sitemap_urls or page.final_url in sitemap_urls,
            "crawl_state": "failed" if page.error_category else "observed",
        })
    return {
        "coverage_state": coverage["state"],
        "nodes": nodes,
        "entry_mappings": entry_mappings,
        "observed_edges": sum(len(targets) for targets in edges.values()),
        "unobserved_internal_targets": len(unknown_targets),
        "orphan_interpretation": "candidate_relative_to_observed_crawl_and_discovery_inventory",
    }


def _url_variants(crawl_run, pages, scope):
    configured, policy = snapshotted_url_parameter_policy(crawl_run.job)
    ignored = set(policy["ignored"])
    pagination = set(policy["pagination"])
    facets = set(policy["facet"])
    urls = set()
    for page in pages:
        for value in (page.requested_url, page.final_url):
            if value:
                urls.add(value)
        urls.update(
            link["url"] for link in page.links
            if isinstance(link, dict) and link.get("internal") and isinstance(link.get("url"), str)
        )
    grouped = {}
    truncated = False
    for url in sorted(urls):
        try:
            normalized = scope.validate_url(url)
        except FetchDenied:
            continue
        parsed = urlsplit(normalized)
        if not parsed.query:
            continue
        if sum(len(items) for items in grouped.values()) >= MAX_VARIANTS:
            truncated = True
            break
        base = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        counts = Counter(name for name, _value in pairs)
        effective_counts = Counter(name for name, _value in pairs if name not in ignored)
        grouped.setdefault(base, []).append({
            "identity": crawl_url_identity(normalized, policy),
            "parameters": sorted(effective_counts),
            "ignored_parameters": sorted(counts.keys() & ignored),
            "repeated_parameters": sorted(name for name, count in effective_counts.items() if count > 1),
        })
    groups = []
    for base, variants in sorted(grouped.items()):
        unique_variants = {}
        for variant in variants:
            existing = unique_variants.setdefault(variant["identity"], variant)
            existing["ignored_parameters"] = sorted(
                set(existing["ignored_parameters"]) | set(variant["ignored_parameters"])
            )
        variants = list(unique_variants.values())
        parameters = sorted({name for variant in variants for name in variant["parameters"]})
        ignored_parameters = sorted({name for variant in variants for name in variant["ignored_parameters"]})
        shapes = Counter(
            (tuple(variant["parameters"]), tuple(variant["repeated_parameters"])) for variant in variants
        )
        groups.append({
            "base_url": base,
            "variant_count": len(variants),
            "parameters": parameters,
            "ignored_parameters": ignored_parameters,
            "configured_pagination_parameters": sorted(set(parameters) & pagination),
            "configured_facet_parameters": sorted(set(parameters) & facets),
            "unclassified_parameters": sorted(set(parameters) - pagination - facets),
            "pagination_candidate": bool(
                set(parameters) & pagination or PAGINATION_PARAMETERS & {name.lower() for name in parameters}
            ),
            "high_variant_count_candidate": len(variants) >= 5,
            "variant_limit": policy["variant_limit"],
            "observed_variant_count_at_or_above_limit": len(variants) >= policy["variant_limit"],
            "shapes": [
                {"parameters": list(names), "repeated_parameters": list(repeated), "observed_count": count}
                for (names, repeated), count in sorted(shapes.items())
            ],
        })
    return {
        "policy": "project_rules" if configured else "preserve_unconfigured",
        "project_rules_available": configured,
        "configured_rules": policy,
        "groups": groups,
        "truncated": truncated,
        "skipped_parameter_variants": crawl_run.discovery.get("skipped_parameter_variants", 0),
    }


def _structured_data_diagnostics(pages, rendered, scope):
    observations = []
    for page in pages:
        raw_visible, raw_visible_complete = (
            _artifact_visible_text(page.raw_artifact.key) if page.raw_artifact_id else (None, False)
        )
        raw = _schema_observation(
            page.structured_data, page.structured_data_errors, raw_visible, raw_visible_complete,
        )
        render = rendered.get(page.pk)
        rendered_observation = {"state": "not_observed"}
        if render:
            try:
                html = read_private_artifact(render.rendered_artifact.key).decode("utf-8", errors="strict")
                parser = PageParser()
                parser.feed(html)
                parsed, _links = parser.result(base_url=page.final_url or page.requested_url, scope=scope)
                visible = VisibleTextParser()
                visible.feed(html)
                completeness = render.comparison.get("completeness", "unknown")
                rendered_observation = _schema_observation(
                    parsed["structured_data"], parsed["structured_data_errors"], visible.text(),
                    not visible.truncated and completeness == "complete_for_supplied_html",
                )
                rendered_observation["completeness"] = completeness
            except (ArtifactNotFound, ArtifactStorageError, UnicodeError, ValueError, RecursionError):
                rendered_observation = {"state": "artifact_unavailable", "completeness": "unknown"}
        observations.append({
            "url": page.final_url or page.requested_url,
            "raw": raw,
            "rendered": rendered_observation,
        })
    return {
        "ruleset_scope": "bounded JSON-LD syntax/type-shape and visible name/headline/description observations",
        "rich_result_eligibility": "not_evaluated",
        "search_appearance": "unknown",
        "observations": observations,
    }


def _artifact_visible_text(key):
    try:
        html = read_private_artifact(key).decode("utf-8", errors="strict")
        parser = VisibleTextParser()
        parser.feed(html)
        return parser.text(), not parser.truncated
    except (ArtifactNotFound, ArtifactStorageError, UnicodeError, ValueError, RecursionError):
        return None, False


def _schema_observation(blocks, parser_errors, visible_text, visible_complete):
    nodes = []
    shape_errors = 0
    pending = list(reversed(blocks))
    while pending and len(nodes) < MAX_SCHEMA_NODES:
        value = pending.pop()
        if isinstance(value, list):
            pending.extend(reversed(value))
        elif isinstance(value, dict):
            graph = value.get("@graph")
            if isinstance(graph, list):
                pending.extend(reversed(graph))
            if "@type" in value or graph is None:
                nodes.append(value)
        else:
            shape_errors += 1
    results = []
    type_issues = shape_errors
    visible_checks = []
    normalized_visible = " ".join((visible_text or "").lower().split())
    for node in nodes:
        type_result = _schema_types(node.get("@type"))
        if type_result is None:
            type_issues += 1
            types, type_status = [], "missing_or_malformed"
        else:
            types, type_status = type_result
        checks = []
        for property_name in ("name", "headline", "description"):
            value = node.get(property_name)
            if not isinstance(value, str) or not value.strip():
                continue
            normalized = " ".join(value.lower().split())
            status = (
                "unknown" if visible_text is None
                else "matched" if normalized in normalized_visible
                else "not_matched" if visible_complete
                else "unknown"
            )
            check = {"property": property_name, "status": status}
            checks.append(check)
            visible_checks.append(status)
        results.append({"types": types, "type_status": type_status, "visible_content": checks})
    errors = [
        item for item in parser_errors
        if isinstance(item, dict) and set(item) == {"block", "category"}
        and type(item["block"]) is int and isinstance(item["category"], str)
    ][:20]
    syntax_errors = [item for item in errors if item["category"] in {"empty", "invalid_json"}]
    limits = [item for item in errors if item["category"] not in {"empty", "invalid_json"}]
    if syntax_errors:
        state = "invalid_syntax"
    elif limits:
        state = "partial_limit"
    elif type_issues:
        state = "type_shape_issue_observed"
    elif nodes:
        state = "syntax_type_observed"
    else:
        state = "not_present"
    if not visible_checks:
        consistency = "not_applicable"
    elif "not_matched" in visible_checks:
        consistency = "mismatch_observed"
    elif "unknown" in visible_checks:
        consistency = "unknown"
    else:
        consistency = "matched"
    return {
        "state": state,
        "syntax_errors": syntax_errors,
        "limit_observations": limits,
        "type_shape_issues": type_issues,
        "nodes": results,
        "node_limit_reached": len(nodes) == MAX_SCHEMA_NODES and bool(pending),
        "visible_content_consistency": consistency,
    }


def _schema_types(value):
    values = [value] if isinstance(value, str) else value if isinstance(value, list) else None
    if values is None or not 1 <= len(values) <= 20 or any(not isinstance(item, str) for item in values):
        return None
    normalized = []
    unresolved = False
    for item in values:
        item = item.strip()
        if item.startswith(("https://schema.org/", "http://schema.org/")):
            item = item.rstrip("/").rsplit("/", 1)[-1]
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,100}", item):
            normalized.append(item)
        elif item and len(item) <= 512 and not any(character.isspace() or ord(character) < 32 for character in item):
            unresolved = True
        else:
            return None
    return normalized, "unresolved_identifier" if unresolved else "observed"
