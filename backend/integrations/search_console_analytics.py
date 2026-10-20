from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from urllib.parse import urlsplit

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from jobs.models import JobCancellation, JobRun, JobStatus, JobStep
from jobs.usage import usage_denial
from tenancy.models import Organization, Project, normalize_origin
from tenancy.services import Action, require_project_action

from .models import GoogleOAuthGrant, IntegrationConnection, SearchAnalyticsPageSnapshot, SearchAnalyticsQueryPageSnapshot, _domain_site, normalize_external_property, verified_domain_origins
from .search_console import _RowError, _normalize_property_page
from .services import require_connection_capability


def _metric(value, *, integer=False, maximum=None):
    if type(value) not in {int, float}:
        raise ValidationError("Search Analytics metrics are unavailable.")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValidationError("Search Analytics metrics are unavailable.") from None
    if not result.is_finite() or result < 0 or (maximum is not None and result > maximum):
        raise ValidationError("Search Analytics metrics are unavailable.")
    if integer:
        if result != result.to_integral_value() or result > 9223372036854775807:
            raise ValidationError("Search Analytics metrics are unavailable.")
        return int(result)
    if len(str(result)) > 40:
        raise ValidationError("Search Analytics metrics are unavailable.")
    return str(result)


def parse_search_analytics_page(*, response, day, dimension, property_origin, start_row, approved_origins=None):
    if (type(day) is not date or type(dimension) is not str or dimension not in {"date", "query", "page"}
        or type(start_row) is not int or start_row not in {0, 100} or type(response) is not dict):
        raise ValidationError("Search Analytics report format is unavailable.")
    if type(property_origin) is not str or normalize_external_property("google_search_console", property_origin) != property_origin:
        raise ValidationError("Search Analytics property identity is unavailable.")
    domain = property_origin.startswith("sc-domain:")
    if domain:
        domain_name = _domain_site(property_origin)
        if (dimension != "page" or start_row != 0 or type(approved_origins) is not list or not 1 <= len(approved_origins) <= 20
            or any(type(origin) is not str or normalize_origin(origin) != origin for origin in approved_origins)
            or any((host := urlsplit(origin).hostname) != domain_name and not host.endswith("." + domain_name)
                   for origin in approved_origins)
            or len(set(approved_origins)) != len(approved_origins)):
            raise ValidationError("Domain property reports require verified exact page origins.")
    elif approved_origins is not None:
        raise ValidationError("URL-prefix reports cannot use domain-origin filters.")
    rows = response.get("rows", [])
    metadata = response.get("metadata", {})
    if (type(rows) is not list or len(rows) > 100 or type(metadata) is not dict
        or metadata.get("first_incomplete_date") or metadata.get("first_incomplete_hour")):
        raise ValidationError("Search Analytics report format is unavailable.")
    expected_aggregation = "byPage" if dimension == "page" else "byProperty"
    if rows and response.get("responseAggregationType") != expected_aggregation:
        raise ValidationError("Search Analytics aggregation does not match its source.")
    observations = []
    omitted_pages = 0
    seen = set()
    for row in rows:
        if type(row) is not dict or type(row.get("keys")) is not list or len(row["keys"]) != 1:
            raise ValidationError("Search Analytics row keys are unavailable.")
        key = row["keys"][0]
        if not isinstance(key, str) or not key or len(key) > 2048 or any(ord(character) < 32 for character in key):
            raise ValidationError("Search Analytics row keys are unavailable.")
        if dimension == "date":
            if key != day.isoformat():
                raise ValidationError("Search Analytics date does not match the requested window.")
        elif dimension == "query":
            if len(key) > 1000:
                raise ValidationError("Search Analytics query exceeds the safe bound.")
        else:
            try:
                if urlsplit(key).query:
                    raise _RowError("parameterized_page")
                if domain:
                    key = next((_normalize_property_page(key, origin) for origin in approved_origins
                                if urlsplit(key).scheme == urlsplit(origin).scheme
                                and urlsplit(key).netloc.lower() == urlsplit(origin).netloc.lower()), None)
                    if key is None:
                        raise _RowError("outside_verified_origin")
                else:
                    key = _normalize_property_page(key, property_origin)
            except (_RowError, ValueError):
                omitted_pages += 1
                continue
        if key in seen:
            raise ValidationError("Search Analytics returned a duplicate report row.")
        seen.add(key)
        clicks = _metric(row.get("clicks"), integer=True)
        impressions = _metric(row.get("impressions"), integer=True)
        if clicks > impressions:
            raise ValidationError("Search Analytics metrics are unavailable.")
        observations.append({"key": key, "clicks": clicks, "impressions": impressions,
                             "ctr": _metric(row.get("ctr"), maximum=1),
                             "position": _metric(row.get("position"), maximum=Decimal("99999999.99999999"))})
    return {"dimension": dimension, "day": day.isoformat(), "aggregation": expected_aggregation,
            "source_coverage": "top_rows_only_domain_page_filtered" if domain else "top_rows_only",
            "approved_origins": approved_origins if domain else [],
            "start_row": start_row, "rows_returned": len(observations) if domain else len(rows),
            "omitted_pages": None if domain else omitted_pages,
            "truncated": None if domain else len(rows) == 100 and start_row == 100,
            "next_start_row": 100 if not domain and len(rows) == 100 and start_row == 0 else None,
            "observations": observations}


def parse_search_analytics_query_page(*, response, day, property_origin, start_row=0):
    """D137 genuine ordered query,page keys; no join, database, network or complete-coverage inference."""
    if (type(response) is not dict or type(day) is not date or type(start_row) is not int or start_row not in {0, 100}
        or type(property_origin) is not str or property_origin.startswith("sc-domain:")
        or normalize_external_property("google_search_console", property_origin) != property_origin):
        raise ValidationError("Choose one actual bounded URL-prefix query-page report.")
    try:
        if len(json.dumps(response, ensure_ascii=False, allow_nan=False).encode()) > 256 * 1024:
            raise ValueError
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ValidationError("Query-page response exceeds its safe scalar byte bound.") from None
    rows, metadata = response.get("rows", []), response.get("metadata", {})
    aggregation = response.get("responseAggregationType")
    if (type(rows) is not list or len(rows) > 100 or type(metadata) is not dict
        or metadata.get("first_incomplete_date") or metadata.get("first_incomplete_hour")
        or aggregation is not None and aggregation != "byPage" or rows and aggregation != "byPage"):
        raise ValidationError("Actual finalized byPage query-page evidence is required.")
    observations, seen, omitted = [], set(), 0
    for row in rows:
        if type(row) is not dict or type(row.get("keys")) is not list or len(row["keys"]) != 2:
            raise ValidationError("Keep actual ordered query and page keys from the same row.")
        query, page = row["keys"]
        if (type(query) is not str or not query.strip() or len(query) > 1000 or any(ord(char) < 32 for char in query)
            or type(page) is not str or not 1 <= len(page) <= 2048 or any(ord(char) < 32 for char in page)):
            raise ValidationError("Query-page row keys are unavailable or exceed their bounds.")
        try:
            if urlsplit(page).query:
                raise _RowError("parameterized_page")
            page = _normalize_property_page(page, property_origin)
        except (_RowError, ValueError):
            omitted += 1
            continue
        pair = (query, page)
        if pair in seen:
            raise ValidationError("Query-page report returned a duplicate exact pair.")
        seen.add(pair)
        clicks, impressions = _metric(row.get("clicks"), integer=True), _metric(row.get("impressions"), integer=True)
        if clicks > impressions:
            raise ValidationError("Query-page metrics are unavailable.")
        observations.append({"query": query, "page": page, "clicks": clicks, "impressions": impressions,
            "ctr": _metric(row.get("ctr"), maximum=1),
            "position": _metric(row.get("position"), maximum=Decimal("99999999.99999999"))})
    return {"method": "gsc-query-page-parse-v1", "property": property_origin, "day": day.isoformat(),
        "dimensions": ["query", "page"], "search_type": "web", "timezone": "America/Los_Angeles",
        "requested_aggregation": "auto", "response_aggregation": aggregation,
        "source_coverage": "bounded_query_page_top_rows_only", "provider_completeness": "not_established",
        "hidden_queries": "unknown", "start_row": start_row, "rows_returned": len(rows), "omitted_pages": omitted,
        "truncated": len(rows) == 100 and start_row == 100,
        "next_start_row": 100 if len(rows) == 100 and start_row == 0 else None,
        "observations": observations, "interpretation": "paired_observations_not_proven_cannibalization_rank_or_complete_demand"}


def query_page_result_digest(result, *, day, property_origin, start_row):
    """Validate the persisted normalized shape, including every scalar, before hashing it."""
    if (type(result) is not dict or type(result.get("observations")) is not list
        or type(result.get("rows_returned")) is not int or not 0 <= result["rows_returned"] <= 100
        or type(result.get("omitted_pages")) is not int or result["omitted_pages"] < 0
        or len(result["observations"]) + result["omitted_pages"] != result["rows_returned"]
        or type(result.get("truncated")) is not bool):
        raise ValidationError("Paired evidence has an invalid scalar shape or coverage count.")
    try:
        rows = []
        for row in result["observations"]:
            if (type(row) is not dict or set(row) != {"query", "page", "clicks", "impressions", "ctr", "position"}
                or type(row["ctr"]) is not str or type(row["position"]) is not str):
                raise ValueError
            rows.append({"keys": [row["query"], row["page"]], "clicks": row["clicks"], "impressions": row["impressions"],
                "ctr": json.loads(row["ctr"]), "position": json.loads(row["position"])})
        response = {"rows": rows}
        if result.get("response_aggregation") is not None:
            response["responseAggregationType"] = result["response_aggregation"]
        expected = parse_search_analytics_query_page(response=response, day=day, property_origin=property_origin, start_row=start_row)
        # Revalidate only safe stored rows; discarded raw keys are never reconstructed or retained.
        expected.update(rows_returned=result["rows_returned"], omitted_pages=result["omitted_pages"],
            truncated=result["rows_returned"] == 100 and start_row == 100,
            next_start_row=100 if result["rows_returned"] == 100 and start_row == 0 else None)
        if result != expected or result["rows_returned"] and result["response_aggregation"] != "byPage":
            raise ValueError
        encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()
        if len(encoded) > 256 * 1024:
            raise ValueError
    except (TypeError, ValueError, UnicodeError, RecursionError, KeyError):
        raise ValidationError("Paired evidence integrity or normalized fields are unavailable.") from None
    return sha256(encoded).hexdigest()


def validate_query_page_snapshot(snapshot, *, current):
    from .search_console_sync import _source

    job = snapshot.job
    if (job.project_id != snapshot.project_id or job.organization_id != snapshot.project.organization_id
        or snapshot.connection.project_id != snapshot.project_id or snapshot.grant.project_id != snapshot.project_id
        or snapshot.grant.organization_id != job.organization_id
        or job.handler != "sync_search_console" or job.method_version != "search-console-api-v1"
        or job.schedule_id is not None or job.retry_of_id is not None
        or job.input_snapshot != {"connection_id": snapshot.connection_id, "grant_id": snapshot.grant_id,
            "day": snapshot.day.isoformat(), "dimensions": ["query", "page"], "report": "query_page"}
        or job.config_snapshot != {"grant_revision": snapshot.grant_revision, "property_id": snapshot.external_property_id,
            "report_method": "gsc-query-page-parse-v1"}
        or snapshot.external_property_id != snapshot.connection.external_property_id):
        raise ValidationError("Paired evidence requires its exact original project, job, report and grant revision.")
    digest = query_page_result_digest(snapshot.result, day=snapshot.day,
        property_origin=snapshot.external_property_id, start_row=snapshot.start_row)
    if snapshot.result_sha256 != digest:
        raise ValidationError("Paired evidence digest does not match its stored source.")
    if current:
        if job.status != JobStatus.RUNNING or JobCancellation.objects.filter(job=job).exists() or usage_denial(job=job):
            raise PermissionDenied
        require_project_action(project=snapshot.project, user=job.actor, action=Action.MANAGE_PROJECT)
        _source(project=snapshot.project, organization=job.organization, data=job.input_snapshot, config=job.config_snapshot)
        if not JobStep.objects.filter(job=job, sequence=2 + snapshot.start_row // 100,
                name="Search Analytics page", status=JobStep.Status.RUNNING, output={"state": "attempted"}).exists():
            raise ValidationError("Paired evidence requires the actual once-only attempted page stage.")


def record_search_analytics_query_page(*, job, connection, grant, day, start_row, response):
    """Persist actual bounded same-row evidence after final current-source and attempted-stage checks."""
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=job.organization_id)
        project = Project.objects.select_for_update().get(pk=job.project_id, organization=organization)
        job = JobRun.objects.select_for_update(no_key=True).select_related("actor").get(pk=job.pk, project=project)
        connection = IntegrationConnection.objects.select_for_update().get(pk=connection.pk, project=project)
        grant = GoogleOAuthGrant.objects.select_for_update().get(pk=grant.pk, project=project, organization=organization)
        result = parse_search_analytics_query_page(response=response, day=day,
            property_origin=connection.external_property_id, start_row=start_row)
        snapshot = SearchAnalyticsQueryPageSnapshot(project=project, job=job, connection=connection, grant=grant,
            grant_revision=grant.revision, external_property_id=connection.external_property_id, day=day,
            start_row=start_row, result=result, result_sha256=query_page_result_digest(result, day=day,
                property_origin=connection.external_property_id, start_row=start_row))
        validate_query_page_snapshot(snapshot, current=True)
        existing = SearchAnalyticsQueryPageSnapshot.objects.filter(job=job, start_row=start_row).first()
        if existing:
            validate_query_page_snapshot(existing, current=False)
            if existing.result == result and existing.result_sha256 == snapshot.result_sha256:
                return existing
            raise ValidationError("This paired page already has different immutable evidence.")
        if start_row == 100:
            first = SearchAnalyticsQueryPageSnapshot.objects.filter(job=job, start_row=0).first()
            if first is None:
                raise ValidationError("Record the actual first paired page before pagination.")
            validate_query_page_snapshot(first, current=False)
            if (first.result["next_start_row"] != 100 or not JobStep.objects.filter(job=job, sequence=2,
                name="Search Analytics page", status=JobStep.Status.SUCCEEDED,
                output={"state": "recorded", "snapshot_id": first.pk, "next_start_row": 100,
                        "result_sha256": first.result_sha256}).exists()
                or {(row["query"], row["page"]) for row in first.result["observations"]}
                    & {(row["query"], row["page"]) for row in result["observations"]}):
                raise ValidationError("Paired pagination requires intact prior evidence and distinct exact pairs.")
        snapshot.save()
        return snapshot


def record_search_analytics_page(*, job, connection, grant, day, dimension, start_row, response):
    """Commit only parsed, scoped API evidence; duplicate delivery cannot replace a prior page."""
    if type(day) is not date or dimension not in {"date", "query", "page"}:
        raise ValidationError("Choose a bounded Search Analytics day and dimension.")
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=job.organization_id)
        project = Project.objects.select_for_update().get(pk=job.project_id, organization=organization)
        job = JobRun.objects.select_for_update(no_key=True).select_related("actor").get(pk=job.pk, project=project)
        connection = IntegrationConnection.objects.select_for_update().get(pk=connection.pk, project=project)
        grant = GoogleOAuthGrant.objects.select_for_update().get(pk=grant.pk, project=project, organization=organization)
        selected = job.input_snapshot.get("dimensions")
        domain = connection.external_property_id.startswith("sc-domain:")
        approved = sorted(set(grant.selected_origins) & set(verified_domain_origins(project,
                                 connection.external_property_id))) if domain else None
        expected_config = {"grant_revision": grant.revision, "property_id": connection.external_property_id}
        if domain:
            expected_config.update({"approved_origins": approved, "scope_strategy": "domain-page-v1"})
        if (type(selected) is not list or not selected or len(selected) > 3
            or any(type(item) is not str for item in selected)
            or len(set(selected)) != len(selected) or not set(selected) <= {"date", "query", "page"}
            or job.handler != "sync_search_console" or job.input_snapshot != {
            "connection_id": connection.pk, "grant_id": grant.pk, "day": day.isoformat(),
            "dimensions": selected,
        } or dimension not in selected
            or job.config_snapshot != expected_config
            or domain and (not approved or selected != ["page"])):
            raise ValidationError("Search Analytics job source changed.")
        result = parse_search_analytics_page(response=response, day=day, dimension=dimension,
                                             property_origin=connection.external_property_id, start_row=start_row,
                                             approved_origins=approved)
        existing = SearchAnalyticsPageSnapshot.objects.filter(job=job, dimension=dimension, start_row=start_row).first()
        if existing is not None:
            if (existing.connection_id == connection.pk and existing.grant_id == grant.pk
                and existing.day == day and existing.result == result):
                return existing
            raise ValidationError("Search Analytics page was already recorded with different evidence.")
        if job.status != JobStatus.RUNNING or JobCancellation.objects.filter(job=job).exists():
            raise PermissionDenied
        require_project_action(project=project, user=job.actor, action=Action.LAUNCH_JOB)
        require_connection_capability(connection, "api_sync", dimensions=[dimension])
        if (grant.state != GoogleOAuthGrant.State.ACTIVE or not grant.encrypted_refresh_token
            or connection.credential_reference != grant.credential_reference
            or connection.external_property_id != grant.selected_property_id
            or normalize_external_property("google_search_console", grant.selected_site_url) != connection.external_property_id):
            raise PermissionDenied
        snapshot = SearchAnalyticsPageSnapshot(
            project=project, job=job, connection=connection, grant=grant,
            external_property_id=connection.external_property_id, day=day, dimension=dimension,
            start_row=start_row, result=result,
        )
        snapshot.save()
        return snapshot
