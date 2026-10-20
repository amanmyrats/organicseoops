import json
from datetime import datetime, timezone as utc_timezone
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from tenancy.models import Organization, Project, normalize_origin
from tenancy.services import Action, require_project_action

from jobs.models import JobCancellation, JobRun, JobStatus

from .models import GoogleOAuthGrant, IntegrationConnection, SearchConsoleCoverageObservation

from .search_console import _RowError, _normalize_property_page


_VERDICTS = {"PASS", "FAIL", "NEUTRAL", "PARTIAL", "VERDICT_UNSPECIFIED"}
_ROBOTS = {"ALLOWED", "DISALLOWED", "ROBOTS_TXT_STATE_UNSPECIFIED"}
_INDEXING = {"INDEXING_ALLOWED", "BLOCKED_BY_META_TAG", "BLOCKED_BY_HTTP_HEADER",
             "BLOCKED_BY_ROBOTS_TXT", "INDEXING_STATE_UNSPECIFIED"}
_FETCH = {"SUCCESSFUL", "SOFT_404", "BLOCKED_ROBOTS_TXT", "NOT_FOUND", "ACCESS_DENIED",
          "SERVER_ERROR", "REDIRECT_ERROR", "ACCESS_FORBIDDEN", "BLOCKED_4XX", "INTERNAL_CRAWL_ERROR",
          "INVALID_URL", "PAGE_FETCH_STATE_UNSPECIFIED"}


def _approved_origins(origins):
    if (type(origins) is not list or not 1 <= len(origins) <= 20
        or any(type(origin) is not str or normalize_origin(origin) != origin for origin in origins)
        or len(set(origins)) != len(origins)):
        raise ValidationError("Choose current exact project origins.")
    return origins


def _scoped_url(value, origins):
    if type(value) is not str or not 1 <= len(value) <= 2048:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.query or parsed.fragment:
        return None
    for origin in origins:
        try:
            return _normalize_property_page(value, origin)
        except (_RowError, ValueError):
            continue
    return None


def _bounded(value):
    if type(value) is not dict:
        raise ValidationError("Search Console report is unavailable.")
    try:
        encoded = json.dumps(value, allow_nan=False, separators=(",", ":")).encode()
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ValidationError("Search Console report is unavailable.") from None
    if len(encoded) > 64 * 1024:
        raise ValidationError("Search Console report exceeds its safe bound.")


def parse_index_inspection(*, response, inspection_url, approved_origins):
    origins = _approved_origins(approved_origins)
    page = _scoped_url(inspection_url, origins)
    if page is None:
        raise ValidationError("URL inspection page is outside current project scope.")
    _bounded(response)
    result = response.get("inspectionResult")
    index = result.get("indexStatusResult") if type(result) is dict else None
    if type(index) is not dict:
        raise ValidationError("URL inspection index evidence is unavailable.")
    verdict = index.get("verdict")
    if type(verdict) is not str or verdict not in _VERDICTS:
        raise ValidationError("URL inspection verdict is unavailable.")
    states = {}
    for key, choices in (("robotsTxtState", _ROBOTS), ("indexingState", _INDEXING), ("pageFetchState", _FETCH)):
        raw = index.get(key)
        states[key] = raw if type(raw) is str and raw in choices else "unknown"
    crawled_at = None
    if type(index.get("lastCrawlTime")) is str:
        try:
            stamp = datetime.fromisoformat(index["lastCrawlTime"].replace("Z", "+00:00"))
            if stamp.tzinfo is not None and stamp <= timezone.now():
                crawled_at = stamp.astimezone(utc_timezone.utc).isoformat()
        except ValueError:
            pass
    return {"inspection_url": page, "method": "google_indexed_version_only", "verdict": verdict,
            "indexed_state": "reported_indexed" if verdict == "PASS" else
                             "reported_not_indexed" if verdict in {"FAIL", "NEUTRAL"} else "unknown",
            "robots_state": states["robotsTxtState"], "indexing_state": states["indexingState"],
            "page_fetch_state": states["pageFetchState"], "last_crawl_at": crawled_at,
            "google_canonical": _scoped_url(index.get("googleCanonical"), origins),
            "declared_canonical": _scoped_url(index.get("userCanonical"), origins),
            "coverage": "one_google_indexed_version_not_live_test"}


def parse_sitemap_listing(*, response, approved_origins):
    origins = _approved_origins(approved_origins)
    _bounded(response)
    rows = response.get("sitemap", [])
    if type(rows) is not list or len(rows) > 100:
        raise ValidationError("Search Console sitemap list exceeds its safe bound.")
    accepted = []
    seen = set()
    for item in rows:
        if type(item) is not dict:
            raise ValidationError("Search Console sitemap entry is unavailable.")
        site = _scoped_url(item.get("path"), origins)
        if site is not None and site not in seen:
            seen.add(site)
            accepted.append({"url": site})
    return {"sitemaps": accepted, "coverage": "submitted_sitemaps_for_verified_origins_only",
            "provider_total": None, "omitted_other_origins": None, "indexed_url_counts": None,
            "list_truncated": None}


def record_coverage_observation(*, job, connection, grant, source, response):
    if source not in SearchConsoleCoverageObservation.Source.values:
        raise ValidationError("Choose a supported Search Console coverage source.")
    from .search_console_coverage_job import _source

    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=job.organization_id)
        project = Project.objects.select_for_update().get(pk=job.project_id, organization=organization)
        job = JobRun.objects.select_for_update(no_key=True).select_related("actor").get(pk=job.pk, project=project)
        connection = IntegrationConnection.objects.select_for_update().get(pk=connection.pk, project=project)
        grant = GoogleOAuthGrant.objects.select_for_update().get(pk=grant.pk, project=project, organization=organization)
        _current_connection, _current_grant, origins = _source(
            project=project, organization=organization, data=job.input_snapshot, config=job.config_snapshot)
        result = (parse_index_inspection(response=response, inspection_url=job.input_snapshot["inspection_url"],
                                         approved_origins=origins) if source == "inspection"
                  else parse_sitemap_listing(response=response, approved_origins=origins))
        existing = SearchConsoleCoverageObservation.objects.filter(job=job, source=source).first()
        if existing is not None:
            if existing.connection_id == connection.pk and existing.grant_id == grant.pk and existing.result == result:
                return existing
            raise ValidationError("Coverage evidence was already recorded with different results.")
        if job.status != JobStatus.RUNNING or JobCancellation.objects.filter(job=job).exists():
            raise PermissionDenied
        require_project_action(project=project, user=job.actor, action=Action.MANAGE_PROJECT)
        snapshot = SearchConsoleCoverageObservation(
            project=project, connection=connection, grant=grant, job=job, source=source,
            external_property_id=connection.external_property_id,
            requested_url=job.input_snapshot["inspection_url"] if source == "inspection" else "",
            result=result,
        )
        snapshot.save()
        return snapshot
