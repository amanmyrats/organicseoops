import hashlib
import json
from urllib.parse import urlsplit

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from integrations.models import ImportRun, IntegrationConnection, SearchMetricObservation
from integrations.opportunity_signals import search_opportunity_signals
from integrations.query_growth import page_change_signals, query_growth_signals
from integrations.services import require_connection_capability
from tenancy.models import Organization, Project
from tenancy.services import Action, require_project_action

from .indexation import reconcile_indexation_reports
from .models import (Finding, IndexationEvidenceSnapshot, JobStatus, Opportunity,
                     PerformanceObservationSnapshot, TechnicalDiagnosticsSnapshot)
from .performance import _scoped_url, compare_crux_history
from .performance_job import METHOD as PERFORMANCE_JOB_METHOD, _credential_scope_changed


def record_csv_findings(*, project, actor, connection, import_id):
    """Persist only deterministic source-bound observations; no opportunity or action is auto-approved."""
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        connection = IntegrationConnection.objects.select_for_update().filter(pk=connection.pk, project=project).first()
        if connection is None:
            raise PermissionDenied
        run = ImportRun.objects.select_for_update().filter(pk=import_id, project=project,
                                                           connection=connection).first()
        if run is None:
            raise ValidationError("Choose one current source import.")
        report = search_opportunity_signals(project=project, user=actor, connection=connection, import_id=run.pk)
        observation_ids = {item["observation_id"] for item in report["candidates"]}
        observations = {item.pk: item for item in SearchMetricObservation.objects.filter(
            pk__in=observation_ids, import_run=run)}
        if len(observations) != len(observation_ids):
            raise ValidationError("Candidate source observations changed.")
        saved = []
        for candidate in report["candidates"]:
            observation = observations[candidate["observation_id"]]
            subject = candidate["query"] or candidate["page"]
            if subject != (observation.query or observation.page):
                raise ValidationError("Candidate scope changed.")
            evidence = {"source": "search_console_csv", "import_id": run.pk,
                        "observation_id": observation.pk, "connection_id": connection.pk,
                        "provider": report["provider"], "property": report["property"],
                        "dimension": report["dimension"], "search_type": report["search_type"],
                        "source_semantics_version": report["source_semantics_version"],
                        "window": report["window"], "timezone": report["timezone"],
                        "market": report["market"], "languages": report["languages"],
                        "coverage": {"provider_top_rows": "incomplete_unknown", "hidden_queries": "unknown"},
                        "thresholds": report["thresholds"], "metrics": {
                            "clicks": candidate["clicks"], "impressions": candidate["impressions"],
                            "ctr": candidate["ctr"], "position": candidate["position"]}}
            fingerprint = hashlib.sha256(json.dumps([report["method"], observation.pk,
                candidate["detector"]], separators=(",", ":")).encode()).hexdigest()
            existing = Finding.objects.filter(project=project, fingerprint=fingerprint).first()
            if existing is not None:
                if (existing.source_metric_id != observation.pk or existing.evidence != evidence
                    or existing.method_version != report["method"] or existing.detector != candidate["detector"]
                    or existing.subject != subject):
                    raise ValidationError("Existing finding evidence differs from this source.")
                saved.append(existing)
                continue
            saved.append(Finding.objects.create(project=project, actor=actor, source_metric=observation,
                detector=candidate["detector"], method_version=report["method"], subject=subject,
                fingerprint=fingerprint, evidence=evidence, confidence=candidate["confidence"]))
        return saved, report["truncated_candidates"]


QUERY_CHANGE_METHOD = "gsc-query-change-v1"


def record_query_change_findings(*, project, actor, connection, previous_import_id, current_import_id):
    return _record_comparison_findings(project=project, actor=actor, connection=connection,
        previous_import_id=previous_import_id, current_import_id=current_import_id, dimension="query")


def record_page_change_findings(*, project, actor, connection, previous_import_id, current_import_id):
    return _record_comparison_findings(project=project, actor=actor, connection=connection,
        previous_import_id=previous_import_id, current_import_id=current_import_id, dimension="page")


def _record_comparison_findings(*, project, actor, connection, previous_import_id, current_import_id, dimension):
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        connection = IntegrationConnection.objects.select_for_update().filter(pk=connection.pk, project=project).first()
        if connection is None:
            raise PermissionDenied
        report = (query_growth_signals if dimension == "query" else page_change_signals)(
            project=project, user=actor, connection=connection,
            previous_import_id=previous_import_id, current_import_id=current_import_id)
        if any(change["search_type"] != "web" for change in report["observed_changes"]):
            raise ValidationError("Only comparable web query changes are supported.")
        ids = {change["previous_observation_id"] for change in report["observed_changes"]}
        ids.update(change["current_observation_id"] for change in report["observed_changes"])
        observations = {item.pk: item for item in SearchMetricObservation.objects.filter(
            pk__in=ids, import_run_id__in=[previous_import_id, current_import_id])}
        if len(ids) != len(observations):
            raise ValidationError("Query comparison source observations changed.")
        saved = []
        for change in report["observed_changes"][:100]:
            before = observations[change["previous_observation_id"]]
            after = observations[change["current_observation_id"]]
            subject = getattr(after, dimension)
            if (before.import_run_id != previous_import_id or after.import_run_id != current_import_id
                or getattr(before, dimension) != subject or subject != change[dimension]):
                raise ValidationError("Query comparison source scope changed.")
            detector = f"web_{dimension}_{change['metric']}_{change['direction']}_candidate"
            evidence = {"source": "search_console_csv", "comparison_method": report["method"],
                        "connection_id": connection.pk, "provider": report["provider"],
                        "property": report["property"], "source_semantics": report["source_semantics"],
                        "source_semantics_version": report["source_semantics_version"],
                        "timezone": report["timezone"], "market": report["market"],
                        "languages": report["languages"], "previous": report["previous"],
                        "current": report["current"], "coverage": report["coverage"],
                        "search_type": change["search_type"], "metric": change["metric"],
                        "previous_observation_id": before.pk, "current_observation_id": after.pk,
                        "previous_value": change["previous"], "current_value": change["current"],
                        "interpretation": "observed_comparable_rows_not_causal_or_complete_demand"}
            method = QUERY_CHANGE_METHOD if dimension == "query" else "gsc-page-change-v1"
            fingerprint = hashlib.sha256(json.dumps([method, before.pk, after.pk, detector],
                separators=(",", ":")).encode()).hexdigest()
            existing = Finding.objects.filter(project=project, fingerprint=fingerprint).first()
            if existing is not None:
                if (existing.source_metric_id != after.pk or existing.evidence != evidence
                    or existing.detector != detector or existing.method_version != method
                    or existing.subject != subject):
                    raise ValidationError("Existing query comparison evidence differs from its source.")
                saved.append(existing)
            else:
                saved.append(Finding.objects.create(project=project, actor=actor, source_metric=after,
                    detector=detector, method_version=method, subject=subject,
                    fingerprint=fingerprint, evidence=evidence, confidence="candidate_source_limited"))
        return saved, report["truncated_observed_changes"] or len(report["observed_changes"]) > 100


def review_finding(*, project, actor, finding_id, expected_revision, priority, estimated_effort,
                   business_relevance, reason):
    if (type(expected_revision) is not int or not 0 <= expected_revision < 65535
        or priority not in Opportunity.Priority.values
        or estimated_effort not in {"unknown", "small", "medium", "large"}
        or business_relevance not in {"unknown", "low", "medium", "high"}
        or type(reason) is not str or not 1 <= len(reason.strip()) <= 240):
        raise ValidationError("Choose a bounded, reviewable opportunity decision.")
    reason = reason.strip()
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        finding = Finding.objects.select_for_update().filter(pk=finding_id, project=project).first()
        if finding is None:
            raise PermissionDenied
        if finding.source_metric_id:
            connection = finding.source_metric.import_run.connection
            if connection.project_id != project.pk:
                raise PermissionDenied
            require_connection_capability(connection, "query_metrics" if finding.source_metric.query else "page_metrics",
                                          dimensions=[finding.source_metric.dimension])
        elif finding.source_indexation_id:
            if not indexation_finding_current(project=project, user=actor, finding=finding):
                raise ValidationError("Indexation evidence is stale or outside the current source scope.")
        elif finding.source_diagnostics_id:
            if not technical_finding_current(project=project, finding=finding):
                raise ValidationError("Technical crawl evidence is outside current project scope.")
        elif finding.source_performance_id:
            if not performance_finding_current(project=project, finding=finding):
                raise ValidationError("Performance evidence is outside current project scope.")
        else:
            raise ValidationError("This detector source does not yet support opportunity review.")
        current = Opportunity.objects.filter(project=project, finding=finding).order_by("-revision").first()
        revision = current.revision if current else 0
        if revision != expected_revision:
            if (current and current.revision == expected_revision + 1 and current.actor_id == actor.pk
                and (current.priority, current.estimated_effort, current.business_relevance, current.review_reason)
                == (priority, estimated_effort, business_relevance, reason)):
                return current
            raise ValidationError("Opportunity review changed; reload its latest revision.")
        return Opportunity.objects.create(project=project, finding=finding, actor=actor,
            revision=revision + 1, priority=priority, estimated_effort=estimated_effort,
            business_relevance=business_relevance, review_reason=reason)


INDEXATION_METHOD = "indexation-candidate-v1"
_LOCAL_SIGNALS = {"sitemap_redirect_candidate", "sitemap_http_or_noindex_candidate"}
_ENGINE_SIGNALS = {"local_noindex_vs_google_indexed_candidate",
                   "local_http_error_vs_google_indexed_candidate",
                   "declared_vs_google_selected_canonical_candidate"}


def _short_url(value):
    return value if isinstance(value, str) and len(value) <= 512 else None


def indexation_finding_current(*, project, user, finding, report=None):
    if finding.source_indexation_id is None or finding.method_version != INDEXATION_METHOD:
        return False
    report = report if report is not None else reconcile_indexation_reports(
        project=project, user=user, crawl_run_id=finding.source_indexation.crawl_run_id)
    provider = finding.evidence.get("provider") if type(finding.evidence) is dict else None
    for row in report["urls"]:
        if row["url"] != finding.subject:
            continue
        if provider is None:
            return finding.detector in row["indexability_signals"]
        if type(provider) is not dict:
            return False
        return any(item["observation_id"] == provider.get("observation_id")
                   and item["property"] == provider.get("property")
                   and finding.detector in item["disagreement_candidates"]
                   for item in row["engine_reports"])
    return False


def record_indexation_findings(*, project, actor, crawl_run_id):
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        snapshot = IndexationEvidenceSnapshot.objects.select_for_update().filter(
            project=project, crawl_run_id=crawl_run_id).select_related("crawl_run__job__actor").first()
        if snapshot is None:
            raise ValidationError("Choose an immutable project crawl snapshot.")
        require_project_action(project=project, user=snapshot.crawl_run.job.actor, action=Action.LAUNCH_JOB)
        report = reconcile_indexation_reports(project=project, user=actor, crawl_run_id=crawl_run_id)
        saved = []
        truncated = False
        for row in report["urls"][:40]:
            for rule, engine in ([(item, None) for item in row["indexability_signals"] if item in _LOCAL_SIGNALS]
                                 + [(item, observation) for observation in row["engine_reports"]
                                    for item in observation["disagreement_candidates"] if item in _ENGINE_SIGNALS]):
                if len(saved) >= 100:
                    truncated = True
                    break
                identity = [INDEXATION_METHOD, snapshot.pk, row["url"], rule,
                            engine["connection_id"] if engine else None,
                            engine["observation_id"] if engine else None]
                fingerprint = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
                evidence = {"source": "local_indexation" if engine is None else "google_indexed_version",
                            "snapshot_id": snapshot.pk, "crawl_run_id": crawl_run_id,
                            "coverage": report["coverage"]["state"],
                            "local_observations": [{"status_code": item["status_code"],
                                "directive_state": item["directive_state"],
                                "declared_canonical": _short_url(item["declared_canonical"])}
                                for item in row["fetch_observations"][-1:]],
                            "provider": None if engine is None else {"property": engine["property"],
                                "connection_id": engine["connection_id"],
                                "observation_id": engine["observation_id"],
                                "collected_at": engine["collected_at"],
                                "engine_last_crawl_at": engine["engine_last_crawl_at"],
                                "indexed_state": engine["indexed_state"],
                                "engine_selected_canonical": _short_url(engine["engine_selected_canonical"])}}
                existing = Finding.objects.filter(project=project, fingerprint=fingerprint).first()
                if existing is not None:
                    if (existing.source_indexation_id != snapshot.pk or existing.detector != rule
                        or existing.method_version != INDEXATION_METHOD or existing.subject != row["url"]
                        or existing.evidence != evidence):
                        raise ValidationError("Existing indexation candidate differs from its evidence.")
                    saved.append(existing)
                else:
                    saved.append(Finding.objects.create(project=project, actor=actor, source_indexation=snapshot,
                        detector=rule, method_version=INDEXATION_METHOD, subject=row["url"],
                        fingerprint=fingerprint, evidence=evidence,
                        confidence="candidate_not_engine_or_live_crawl_proof"))
            if truncated:
                break
        return saved, report["coverage"]["engine_indexing_reports"], truncated


def _store_snapshot_candidate(*, project, actor, source, field, method, detector, subject, evidence, variant=""):
    fingerprint = hashlib.sha256(json.dumps([method, field, source.pk, detector, subject, variant],
                                    separators=(",", ":")).encode()).hexdigest()
    existing = Finding.objects.filter(project=project, fingerprint=fingerprint).first()
    if existing is not None:
        if (getattr(existing, field + "_id") != source.pk or existing.method_version != method
            or existing.detector != detector or existing.subject != subject or existing.evidence != evidence):
            raise ValidationError("Existing detector evidence differs from its source.")
        return existing
    return Finding.objects.create(project=project, actor=actor, detector=detector,
        method_version=method, subject=subject, fingerprint=fingerprint, evidence=evidence,
        confidence="candidate_source_limited", **{field: source})


TECHNICAL_METHOD = "technical-candidate-v1"
_CANONICAL_RULES = {"canonical_target_redirects", "canonical_target_non_200",
                    "canonical_target_noindex", "canonical_chain", "raw_rendered_disagreement"}


def record_technical_findings(*, project, actor, diagnostics_id):
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        source = (TechnicalDiagnosticsSnapshot.objects.select_for_update(of=("self",))
                  .select_related("crawl_run__job__actor").filter(pk=diagnostics_id, project=project).first())
        if source is None:
            raise ValidationError("Choose an immutable technical diagnostics snapshot.")
        require_project_action(project=project, user=source.crawl_run.job.actor, action=Action.LAUNCH_JOB)
        output = source.output
        coverage = output["coverage"]["state"]
        if coverage not in {"complete_for_crawl_scope", "partial"}:
            raise ValidationError("Technical crawl coverage is unavailable.")
        candidates = []
        for item in output["canonicals"]["observations"]:
            raw = item["raw"]
            for rule in item["conflicts"]:
                if rule in _CANONICAL_RULES:
                    candidates.append((item["url"], "canonical_" + rule, {
                        "source": "technical_diagnostics", "observation": "observed_canonical_candidate",
                        "target_state": raw.get("target_state", "unknown"),
                        "target_status": raw.get("target_status"), "coverage": coverage}, rule))
        for item in output["link_graph"]["nodes"]:
            if item["orphan_status"] == "candidate" and coverage == "complete_for_crawl_scope":
                candidates.append((item["url"], "orphan_relative_to_complete_crawl_candidate", {
                    "source": "technical_diagnostics", "inbound_links": item["inbound_links"],
                    "in_sitemap_inventory": item["in_sitemap_inventory"], "coverage": coverage}, "orphan"))
            if item["weakly_connected_candidate"] and item["depth_state"] == "observed" and item["crawl_state"] == "observed":
                candidates.append((item["url"], "weakly_connected_candidate", {
                    "source": "technical_diagnostics", "inbound_links": item["inbound_links"],
                    "observed_depth": item["depth"], "coverage": coverage}, "weak_link"))
        for item in output["structured_data"]["observations"]:
            raw = item["raw"]
            if raw["state"] in {"invalid_syntax", "type_shape_issue_observed"}:
                candidates.append((item["url"], "schema_" + raw["state"] + "_candidate", {
                    "source": "technical_diagnostics", "ruleset": source.ruleset_version,
                    "schema_state": raw["state"], "coverage": coverage,
                    "rich_result_eligibility": "not_evaluated"}, "schema"))
        for group in output["url_variants"]["groups"]:
            for signal, detector in (("pagination_candidate", "pagination_variant_candidate"),
                                     ("high_variant_count_candidate", "high_variant_count_candidate")):
                if group[signal]:
                    names = group["parameters"]
                    candidates.append((group["base_url"], detector, {
                        "source": "technical_diagnostics", "policy": output["url_variants"]["policy"],
                        "variant_count": group["variant_count"],
                        "parameters": [name for name in names if isinstance(name, str) and len(name) <= 64][:10],
                        "parameters_omitted": len(names) > 10 or any(not isinstance(name, str) or len(name) > 64 for name in names),
                        "coverage": coverage, "values": "omitted"}, signal))
        html_pages = []
        observed_pages = list(source.crawl_run.pages.select_related("raw_artifact").order_by("pk")[:26])
        observed_by_url = {page.requested_url: page for page in observed_pages}
        for page in observed_pages:
            url = page.final_url or page.requested_url
            try:
                if (type(url) is not str or urlsplit(url).query or urlsplit(url).fragment
                    or _scoped_url(project, url) != url):
                    continue
            except (ValidationError, ValueError):
                continue
            if page.error_category or page.reused_from_id or page.status_code in {None, 304}:
                continue
            details = {"source": "raw_crawl", "crawl_page_id": page.pk,
                       "observed_at": page.observed_at.isoformat(), "status_code": page.status_code,
                       "coverage": coverage, "interpretation": "observed_raw_not_engine_indexing"}
            if page.status_code >= 400:
                candidates.append((url, "observed_http_error_candidate", details, f"page:{page.pk}"))
            if len(page.redirect_chain) >= 2:
                candidates.append((page.requested_url, "observed_redirect_chain_candidate",
                                   {**details, "hop_count": len(page.redirect_chain)}, f"page:{page.pk}"))
            if (page.status_code != 200 or page.raw_artifact_id is None
                or page.raw_artifact.content_type != "text/html"
                or page.final_url != page.requested_url or not page.content_hash):
                continue
            html_pages.append(page)
            for link in page.links[:100]:
                if type(link) is not dict or link.get("internal") is not True:
                    continue
                target_url = link.get("url")
                if type(target_url) is not str:
                    continue
                try:
                    if (urlsplit(target_url).query or urlsplit(target_url).fragment
                        or _scoped_url(project, target_url) != target_url):
                        continue
                except (ValidationError, ValueError):
                    continue
                target = observed_by_url.get(target_url)
                if (target is not None and not target.error_category and not target.reused_from_id
                    and target.status_code is not None and target.status_code >= 400):
                    candidates.append((url, "observed_internal_link_http_error_candidate", {
                        **details, "target_url": target_url, "target_page_id": target.pk,
                        "target_status": target.status_code,
                        "interpretation": "observed_internal_link_target_not_unfetched_links"},
                        f"link:{page.pk}:{target.pk}"))
            languages = {}
            for alternate in page.hreflang[:100]:
                if type(alternate) is not dict:
                    continue
                language, alternate_url = alternate.get("language"), alternate.get("url")
                if (type(language) is not str or not 1 <= len(language) <= 35
                    or not all(character.isascii() and (character.isalnum() or character == "-") for character in language)
                    or type(alternate_url) is not str):
                    continue
                try:
                    if (urlsplit(alternate_url).query or urlsplit(alternate_url).fragment
                        or _scoped_url(project, alternate_url) != alternate_url):
                        continue
                except (ValidationError, ValueError):
                    continue
                if language in languages and languages[language] != alternate_url:
                    candidates.append((url, "conflicting_raw_hreflang_candidate", {
                        **details, "language": language,
                        "interpretation": "two_observed_targets_not_missing_locale_or_reciprocity_proof"},
                        f"hreflang:{page.pk}:{language}"))
                languages[language] = alternate_url
            for field, minimum, maximum in (("title", 15, 70), ("meta_description", 50, 160)):
                value = getattr(page, field)
                size = len(value.strip())
                rule = "missing" if not size else "short" if size < minimum else "excessive" if size > maximum else ""
                if rule:
                    candidates.append((url, f"raw_{field}_{rule}_candidate",
                        {**details, "field": field, "character_count": size,
                         "thresholds": {"minimum": minimum, "maximum": maximum},
                         "interpretation": "review_candidate_not_search_snippet_prediction"}, f"page:{page.pk}"))
        if coverage == "complete_for_crawl_scope":
            for index, page in enumerate(html_pages):
                for other in html_pages[index + 1:]:
                    for field, detector in (("content_hash", "exact_raw_html_duplicate_candidate"),
                                            ("title", "duplicate_raw_title_candidate"),
                                            ("meta_description", "duplicate_raw_description_candidate")):
                        value = getattr(page, field)
                        if value and value == getattr(other, field):
                            candidates.append((page.final_url, detector, {
                                "source": "raw_crawl", "crawl_page_ids": [page.pk, other.pk],
                                "observed_at": [page.observed_at.isoformat(), other.observed_at.isoformat()],
                                "other_url": other.final_url, "coverage": coverage,
                                "comparison": "exact_raw_html_bytes" if field == "content_hash" else "exact_raw_metadata",
                                "interpretation": "observed_pair_not_near_duplicate_or_merge_instruction"},
                                f"pair:{page.pk}:{other.pk}:{field}"))
        saved = []
        seen = set()
        truncated = False
        for url, detector, details, variant in candidates:
            try:
                if type(url) is not str or urlsplit(url).query or urlsplit(url).fragment or _scoped_url(project, url) != url:
                    continue
            except (ValidationError, ValueError):
                continue
            identity = (url, detector, variant)
            if identity in seen:
                continue
            seen.add(identity)
            if len(saved) >= 100:
                truncated = True
                break
            evidence = {"snapshot_id": source.pk, "crawl_run_id": source.crawl_run_id,
                        "diagnostics_method": source.method_version, "details": details}
            saved.append(_store_snapshot_candidate(project=project, actor=actor, source=source,
                field="source_diagnostics", method=TECHNICAL_METHOD, detector=detector,
                subject=url, evidence=evidence, variant=variant))
        return saved, truncated


PERFORMANCE_METHOD = "performance-candidate-v1"


def technical_finding_current(*, project, finding):
    if finding.source_diagnostics_id is None or finding.method_version != TECHNICAL_METHOD:
        return False
    source = finding.source_diagnostics
    if (source.project_id != project.pk or source.crawl_run.project_id != project.pk
        or finding.evidence.get("snapshot_id") != source.pk):
        return False
    try:
        require_project_action(project=project, user=source.crawl_run.job.actor, action=Action.LAUNCH_JOB)
        return _scoped_url(project, finding.subject) == finding.subject
    except (PermissionDenied, ValidationError):
        return False


def performance_finding_current(*, project, finding):
    if finding.source_performance_id is None or finding.method_version != PERFORMANCE_METHOD:
        return False
    source = finding.source_performance
    if (source.project_id != project.pk or source.job.project_id != project.pk
        or source.job.status not in {JobStatus.SUCCEEDED, JobStatus.PARTIALLY_SUCCEEDED}
        or source.job.method_version != PERFORMANCE_JOB_METHOD
        or finding.evidence.get("snapshot_id") != source.pk):
        return False
    try:
        require_project_action(project=project, user=source.job.actor, action=Action.LAUNCH_JOB)
        return (_scoped_url(project, finding.subject, origin=source.grain == "origin") == source.target
                and not _credential_scope_changed(source.job, project.organization))
    except (PermissionDenied, ValidationError):
        return False


def record_performance_findings(*, project, actor, observation_id):
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        source = (PerformanceObservationSnapshot.objects.select_for_update(of=("self",))
                  .select_related("job__actor").filter(pk=observation_id, project=project).first())
        if source is None or source.job.status not in {JobStatus.SUCCEEDED, JobStatus.PARTIALLY_SUCCEEDED}:
            raise ValidationError("Choose a completed project performance observation.")
        require_project_action(project=project, user=source.job.actor, action=Action.LAUNCH_JOB)
        if source.job.method_version != PERFORMANCE_JOB_METHOD or _credential_scope_changed(source.job, organization):
            raise ValidationError("Performance credential source changed.")
        if _scoped_url(project, source.target, origin=source.grain == "origin") != source.target:
            raise ValidationError("Performance target changed scope.")
        output = source.output
        candidates = []
        if source.source == PerformanceObservationSnapshot.Source.PSI_LAB:
            scores = output.get("scores", {})
            score = scores.get("performance") if type(scores) is dict else None
            if output.get("status") == "observed" and type(score) in {int, float} and 0 <= score < .5:
                candidates.append(("low_lighthouse_lab_score_candidate", {
                    "score": score, "method": "lighthouse_lab_score_not_field_p75",
                    "observed_at": output.get("observed_at")}, "lab"))
        elif source.source in {PerformanceObservationSnapshot.Source.CRUX_CURRENT,
                               PerformanceObservationSnapshot.Source.CRUX_HISTORY}:
            for metric in output.get("metrics", [])[:160]:
                if metric.get("state") == "observed" and metric.get("grade") == "poor" and metric.get("name") in {"LCP", "INP", "CLS"}:
                    candidates.append(("poor_crux_field_" + metric["name"].lower() + "_candidate", {
                        "metric": metric["name"], "p75": metric["p75"], "unit": metric["unit"],
                        "grade": "poor", "period": metric["period"], "method": "field_p75_not_a_lab_score"},
                        metric["name"] + ":" + metric["period"]["end"]))
            if source.source == PerformanceObservationSnapshot.Source.CRUX_HISTORY:
                for metric in ("LCP", "INP", "CLS"):
                    comparison = compare_crux_history(output, metric)
                    if comparison["state"] == "regression_candidate":
                        candidates.append(("crux_field_threshold_regression_candidate", {
                            "metric": metric, "comparison": comparison,
                            "interpretation": "overlapping_field_windows_not_causal_change"},
                            metric + ":regression"))
        saved = []
        for detector, details, variant in candidates[:100]:
            evidence = {"source": source.source, "snapshot_id": source.pk, "job_id": source.job_id,
                        "grain": source.grain, "strategy": source.strategy,
                        "observed_grain": output.get("observed_grain", source.grain),
                        "origin_fallback": output.get("origin_fallback", False), "details": details}
            saved.append(_store_snapshot_candidate(project=project, actor=actor, source=source,
                field="source_performance", method=PERFORMANCE_METHOD, detector=detector,
                subject=source.target, evidence=evidence, variant=variant))
        return saved, len(candidates) > 100
