from http import HTTPStatus
import json
import re
from datetime import date

from allauth.core import ratelimit
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_http_methods

from config.artifacts import ArtifactStorageError, ArtifactValidationError
from jobs.usage import UsageLimitError
from tenancy.models import Organization, Project
from tenancy.services import Action, require_project_action

from .brand import BRAND_METHOD, BrandReviewConflict, brand_aliases, default_brand_label, review_query_brand
from .models import (GA4OAuthGrant, GoogleOAuthGrant, ImportRun, IntegrationConnection,
                     QueryBrandReview, SearchMetricObservation, SyncCursor,
                     property_matches_project, verified_domain_origins)
from .opportunity_signals import search_opportunity_signals
from providers.google_app import google_oauth_client

from .google_tokens import GoogleTokenError
from .services import UnsupportedIntegrationCapability, create_connection, require_connection_capability, set_csv_source_state
from .models import IntegrationCapability, SourceDimension, normalize_external_property
from .search_console import MAX_CSV_BYTES, SOURCE_TIMEZONE, queue_search_console_csv_import


def _response(payload, status=HTTPStatus.OK):
    result = JsonResponse(payload, status=status)
    result["Cache-Control"] = "private, no-store"
    return result


def _project(request, organization_id, project_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return None
    return Project.objects.for_user(request.user).filter(organization_id=organization_id, pk=project_id).first()


@require_http_methods(["POST"])
def csv_source_create(request, organization_id, project_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"errors": [{"message": "Authentication required."}]}, HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _response({"errors": [{"message": "Project not found."}]}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
        if not ratelimit.consume(request, action="csv_source_create", user=request.user):
            return _response({"errors": [{"message": "Too many source requests."}]}, HTTPStatus.TOO_MANY_REQUESTS)
        payload = json.loads(request.body)
        if type(payload) is not dict or set(payload) != {"property"}:
            raise ValidationError("Choose one exact project origin.")
        identity = normalize_external_property("google_search_console", payload["property"])
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=project.organization_id)
            project = Project.objects.select_for_update().select_related("organization").get(pk=project.pk)
            require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
            if identity not in {project.canonical_origin, *project.domain_aliases.values_list("origin", flat=True)}:
                raise ValidationError("Choose one exact project origin.")
            connection = IntegrationConnection.objects.filter(project=project, provider="google_search_console",
                                                               external_property_id=identity).first()
            if connection is not None:
                if connection.credential_reference or "csv_import" not in connection.capabilities:
                    raise ValidationError("This property already has a different source setup.")
            else:
                connection = create_connection(project=project, user=request.user, provider="google_search_console",
                    external_property_id=identity,
                    capabilities=[IntegrationCapability.CSV_IMPORT, IntegrationCapability.QUERY_METRICS,
                                  IntegrationCapability.PAGE_METRICS],
                    available_dimensions=[SourceDimension.DATE, SourceDimension.QUERY, SourceDimension.PAGE,
                        SourceDimension.COUNTRY, SourceDimension.DEVICE, SourceDimension.SEARCH_APPEARANCE],
                    source_semantics="search_console_performance", source_semantics_version="csv-v1",
                    timezone=SOURCE_TIMEZONE, backfill_limit_days=90)
        return _response({"project_id": project.pk, "id": connection.pk, "property": identity,
                          "state": connection.state}, HTTPStatus.OK)
    except PermissionDenied:
        return _response({"errors": [{"message": "You cannot set up this source."}]}, HTTPStatus.FORBIDDEN)
    except (ValueError, TypeError, ValidationError, IntegrityError):
        return _response({"errors": [{"message": "Choose a current exact project origin with local CSV support."}]}, HTTPStatus.CONFLICT)


@require_http_methods(["POST"])
def csv_source_upload(request, organization_id, project_id, connection_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"errors": [{"message": "Authentication required."}]}, HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    connection = IntegrationConnection.objects.filter(project=project, pk=connection_id).first() if project else None
    if connection is None:
        return _response({"errors": [{"message": "Source not found."}]}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
        require_project_action(project=project, user=request.user, action=Action.LAUNCH_JOB)
        if not ratelimit.consume(request, action="search_console_csv_upload", user=request.user):
            return _response({"errors": [{"message": "Too many upload requests."}]}, HTTPStatus.TOO_MANY_REQUESTS)
        if connection.provider != "google_search_console" or connection.credential_reference:
            raise ValidationError("Choose a local CSV source.")
        require_connection_capability(connection, IntegrationCapability.CSV_IMPORT)
        limit = min(settings.ARTIFACT_MAX_BYTES, MAX_CSV_BYTES)
        length = request.META.get("CONTENT_LENGTH", "")
        if (request.content_type != "text/csv" or not re.fullmatch(r"[0-9]{1,7}", length)
            or not 1 <= int(length) <= limit or request.headers.get("X-CSV-Authorization") != "true"):
            raise ValidationError("Choose a bounded CSV and authorize its use.")
        start = date.fromisoformat(request.headers.get("X-CSV-Start", ""))
        end = date.fromisoformat(request.headers.get("X-CSV-End", ""))
        search_type = request.headers.get("X-CSV-Search-Type", "")
        grain = request.headers.get("X-CSV-Date-Granularity", "")
        if grain not in {"range", "day"}:
            raise ValidationError("Declare the export date grain.")
        content = request.read(limit + 1)
        if len(content) != int(length):
            raise ValidationError("CSV size changed.")
        # The importer owns durable staging; do not wrap it in an outer transaction.
        job = queue_search_console_csv_import(connection=connection, user=request.user, content=content,
            date_start=start, date_end=end, search_type=search_type, date_granularity="day" if grain == "day" else None)
        return _response({"project_id": project.pk, "connection_id": connection.pk,
            "job": {"id": job.pk, "project_id": job.project_id, "status": job.status, **job.input_snapshot}},
            HTTPStatus.ACCEPTED)
    except PermissionDenied:
        return _response({"errors": [{"message": "You cannot upload to this source."}]}, HTTPStatus.FORBIDDEN)
    except UsageLimitError as error:
        return _response({"errors": [{"message": "Import allowance unavailable.", "code": error.category}]}, HTTPStatus.TOO_MANY_REQUESTS)
    except ArtifactStorageError:
        return _response({"errors": [{"message": "Private import storage is unavailable."}]}, HTTPStatus.SERVICE_UNAVAILABLE)
    except (ValueError, TypeError, ValidationError, ArtifactValidationError, IntegrityError):
        return _response({"errors": [{"message": "Check the current CSV source, date range, export metadata and file limit."}]}, HTTPStatus.CONFLICT)


@require_GET
def project_sources(request, organization_id, project_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"errors": [{"message": "Authentication required."}]}, HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _response({"errors": [{"message": "Project not found."}]}, HTTPStatus.NOT_FOUND)
    connections = list(IntegrationConnection.objects.filter(project=project).order_by("id")[:51])
    current_origins = {project.canonical_origin, *project.domain_aliases.values_list("origin", flat=True)}
    sources = []
    cursors = {cursor.connection_id: cursor for cursor in SyncCursor.objects.filter(connection__in=connections[:50])}
    active_grants = {grant.credential_reference: grant for grant in GoogleOAuthGrant.objects.filter(
        project=project, state=GoogleOAuthGrant.State.ACTIVE,
        credential_reference__in=[item.credential_reference for item in connections[:50] if item.credential_reference])}
    try:
        google_oauth_client()
        configured = True
    except (GoogleTokenError, ValidationError):
        configured = False
    for connection in connections[:50]:
        if connection.provider == "yandex_webmaster":
            from .yandex_models import YandexOAuthGrant
            grant = YandexOAuthGrant.objects.filter(project=project, organization_id=project.organization_id,
                connection=connection, state="active", refresh_started_at__isnull=True).first()
            ready = bool(grant and connection.state == "active" and property_matches_project(connection))
            cursor = cursors.get(connection.pk)
            sources.append({"id": connection.pk, "provider": connection.provider, "property": connection.external_property_id,
                "state": connection.state, "scope_current": ready, "scope_kind": "yandex_exact_origin_aggregate_history",
                "approved_origins": [connection.external_property_id] if ready else [], "available_api_dimensions": ["date"],
                "csv_import_supported": False, "oauth_available": True, "api_sync_available": ready,
                "coverage_available": False, "query_page_available": False,
                "credential_status": "reference_reserved", "sync": None, "latest_import": None,
                "data_status": "separate_yandex_history_view", "timezone": "source_timestamp_offset"})
            continue
        if connection.provider == "google_analytics_4":
            grant = GA4OAuthGrant.objects.filter(project=project, organization=project.organization,
                credential_reference=connection.credential_reference, property_id=connection.external_property_id,
                state=GA4OAuthGrant.State.ACTIVE).first() if connection.credential_reference else None
            scope_current = bool(grant and property_matches_project(connection))
            ready = False  # GA4 hostName + landing path cannot establish the exact HTTPS origin.
            sources.append({"id": connection.pk, "provider": connection.provider,
                "property": connection.external_property_id, "state": connection.state,
                "scope_current": scope_current, "scope_kind": "ga4_hostname_only",
                "approved_origins": grant.selected_origins if scope_current else [],
                "available_api_dimensions": [], "csv_import_supported": False,
                "oauth_available": False, "api_sync_available": ready, "coverage_available": False,
                "credential_status": "reference_reserved" if connection.credential_reference else "not_connected",
                "sync": None, "latest_import": None,
                "data_status": "exact_origin_attribution_unavailable"})
            continue
        latest = ImportRun.objects.filter(connection=connection).order_by("-created_at", "-id").first()
        cursor = cursors.get(connection.pk)
        grant = active_grants.get(connection.credential_reference)
        domain = connection.external_property_id.startswith("sc-domain:")
        approved = sorted(set(grant.selected_origins) & set(verified_domain_origins(
            project, connection.external_property_id))) if domain and grant else []
        scope_current = bool(approved) if domain else connection.external_property_id in current_origins
        ready = bool(configured and grant and connection.state == connection.State.ACTIVE
                     and scope_current
                     and grant.selected_property_id == connection.external_property_id
                     and "api_sync" in connection.capabilities)
        sources.append({
            "id": connection.pk,
            "provider": connection.provider,
            "property": connection.external_property_id,
            "state": connection.state,
            "scope_current": scope_current,
            "scope_kind": "verified_domain_page_only" if domain else "exact_origin_url_prefix",
            "approved_origins": approved if domain else [],
            "available_api_dimensions": [item for item in ("date", "query", "page")
                                         if item in connection.available_dimensions and "api_sync" in connection.capabilities],
            "csv_import_supported": "csv_import" in connection.capabilities,
            "oauth_available": configured,
            "api_sync_available": ready,
            "query_page_available": bool(ready and not domain and connection.timezone == "America/Los_Angeles"
                and {"query_metrics", "page_metrics"} <= set(connection.capabilities)
                and {"query", "page"} <= set(connection.available_dimensions)),
            "query_page_grant_id": grant.pk if ready and not domain else None,
            "query_page_grant_revision": grant.revision if ready and not domain else None,
            "coverage_available": ready and {"indexing_status", "sitemaps"} <= set(connection.capabilities),
            "credential_status": "reference_reserved" if connection.credential_reference else "not_connected",
            "sync": None if cursor is None else {
                "status": cursor.status, "quota_state": cursor.quota_state,
                "coverage_start": cursor.coverage_start.isoformat() if cursor.coverage_start else None,
                "coverage_end": cursor.coverage_end.isoformat() if cursor.coverage_end else None,
                "fresh_through": cursor.fresh_through.isoformat() if cursor.fresh_through else None,
                "error_category": cursor.error_category,
                "retry_after": cursor.retry_after.isoformat() if cursor.retry_after else None,
            },
            "latest_import": None if latest is None else {
                "id": latest.pk,
                "status": latest.status,
                "coverage_state": latest.coverage_state,
                "date_start": latest.date_start.isoformat(),
                "date_end": latest.date_end.isoformat(),
                "export_shape": latest.coverage.get("export_shape", "unknown"),
                "source_completeness": latest.coverage.get("source_completeness", "unknown"),
                "rows_seen": latest.rows_seen,
                "rows_imported": latest.rows_imported,
                "row_errors": latest.row_errors,
                "created_at": latest.created_at.isoformat(),
            },
        })
    return _response({"project_id": project.pk, "sources": sources, "has_more": len(connections) > 50})


@require_http_methods(["PATCH"])
def csv_source_state(request, organization_id, project_id, connection_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"errors": [{"message": "Authentication required."}]}, HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    connection = IntegrationConnection.objects.filter(project=project, pk=connection_id).first() if project else None
    if connection is None:
        return _response({"errors": [{"message": "Source not found."}]}, HTTPStatus.NOT_FOUND)
    try:
        payload = json.loads(request.body)
        if type(payload) is not dict or set(payload) != {"enabled"} or type(payload["enabled"]) is not bool:
            raise ValidationError("Check the source state.")
        connection = set_csv_source_state(
            connection=connection, user=request.user, active=payload["enabled"],
            request_id=getattr(request, "_organicseoops_request_id", ""),
        )
    except PermissionDenied:
        return _response({"errors": [{"message": "You cannot change this source."}]}, HTTPStatus.FORBIDDEN)
    except (ValueError, TypeError, ValidationError, UnsupportedIntegrationCapability):
        return _response({"errors": [{"message": "This CSV source cannot be changed with the current scope and capabilities."}]}, HTTPStatus.BAD_REQUEST)
    return _response({"id": connection.pk, "project_id": project.pk, "state": connection.state})


@require_GET
def source_import_history(request, organization_id, project_id, connection_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"errors": [{"message": "Authentication required."}]}, HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    connection = IntegrationConnection.objects.filter(project=project, pk=connection_id).first() if project else None
    if connection is None:
        return _response({"errors": [{"message": "Source not found."}]}, HTTPStatus.NOT_FOUND)
    runs = list(ImportRun.objects.filter(connection=connection, project=project).order_by("-created_at", "-pk")[:21])
    return _response({
        "project_id": project.pk, "connection_id": connection.pk, "provider": connection.provider,
        "property": connection.external_property_id, "has_more": len(runs) > 20,
        "imports": [
            {
                "id": run.pk, "date_start": run.date_start.isoformat(), "date_end": run.date_end.isoformat(),
                "observation_dimensions": run.observation_dimensions,
                "status": run.status, "coverage_state": run.coverage_state,
                "export_shape": run.coverage.get("export_shape", "unknown"),
                "source_completeness": run.coverage.get("source_completeness", "unknown"),
                "rows_seen": run.rows_seen, "rows_imported": run.rows_imported, "row_errors": run.row_errors,
                "error_categories": run.coverage.get("error_categories", {}),
                "created_at": run.created_at.isoformat(),
            }
            for run in runs[:20]
        ],
    })


@require_GET
def source_opportunity_preview(request, organization_id, project_id, connection_id, import_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"errors": [{"message": "Authentication required."}]}, HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    connection = IntegrationConnection.objects.filter(project=project, pk=connection_id).first() if project else None
    if connection is None:
        return _response({"errors": [{"message": "Source not found."}]}, HTTPStatus.NOT_FOUND)
    try:
        result = search_opportunity_signals(project=project, user=request.user, connection=connection,
                                            import_id=import_id)
    except PermissionDenied:
        return _response({"errors": [{"message": "Source evidence is unavailable."}]}, HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _response({"errors": [{"message": "Choose a complete current project source export."}]}, HTTPStatus.CONFLICT)
    return _response(result)


@require_GET
def source_queries(request, organization_id, project_id, connection_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"errors": [{"message": "Authentication required."}]}, HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    connection = IntegrationConnection.objects.filter(project=project, pk=connection_id).first() if project else None
    if connection is None:
        return _response({"errors": [{"message": "Source not found."}]}, HTTPStatus.NOT_FOUND)
    before = request.GET.get("before")
    if before is not None and (not before.isascii() or not before.isdecimal() or not 1 <= len(before) <= 20 or int(before) > 9223372036854775807):
        return _response({"errors": [{"message": "Check the query cursor."}]}, HTTPStatus.BAD_REQUEST)
    aliases, alias_revision = brand_aliases(project)
    queryset = SearchMetricObservation.objects.filter(
        import_run__project=project, import_run__connection=connection, query__gt="",
    )
    if before is not None:
        queryset = queryset.filter(pk__lt=int(before))
    rows = list(queryset.select_related("import_run").order_by("-pk")[:51])
    latest_reviews = {
        review.observation_id: review for review in QueryBrandReview.objects.filter(
            observation__in=rows[:50],
        ).order_by("observation_id", "-revision").distinct("observation_id")
    }
    return _response({
        "project_id": project.pk, "connection_id": connection.pk,
        "provider": connection.provider, "property": connection.external_property_id,
        "method": BRAND_METHOD, "alias_revision": alias_revision,
        "source_completeness": "provider_export_unknown",
        "queries": [
            {
                "id": row.pk, "query": row.query,
                "date_start": row.date_start.isoformat(), "date_end": row.date_end.isoformat(),
                "search_type": row.search_type,
                "import_status": row.import_run.status,
                "default_label": default_brand_label(row.query, aliases),
                "label": latest_reviews[row.pk].label if row.pk in latest_reviews else default_brand_label(row.query, aliases),
                "review_revision": latest_reviews[row.pk].revision if row.pk in latest_reviews else 0,
            }
            for row in rows[:50]
        ],
        "has_more": len(rows) > 50,
        "next_before": rows[49].pk if len(rows) > 50 else None,
    })


@require_http_methods(["GET", "POST"])
def query_reviews(request, organization_id, project_id, connection_id, observation_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"errors": [{"message": "Authentication required."}]}, HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    connection = IntegrationConnection.objects.filter(project=project, pk=connection_id).first() if project else None
    observation = SearchMetricObservation.objects.filter(
        pk=observation_id, import_run__project=project, import_run__connection=connection, query__gt="",
    ).first() if connection else None
    if observation is None:
        return _response({"errors": [{"message": "Query not found."}]}, HTTPStatus.NOT_FOUND)
    if request.method == "GET":
        reviews = list(QueryBrandReview.objects.filter(observation=observation).order_by("-revision")[:21])
        return _response({
            "project_id": project.pk, "connection_id": connection.pk, "query_id": observation.pk,
            "reviews": [
                {"revision": item.revision, "label": item.label, "reason": item.reason, "actor_id": item.actor_id,
                 "created_at": item.created_at.isoformat()}
                for item in reviews[:20]
            ],
            "has_more": len(reviews) > 20,
        })
    try:
        payload = json.loads(request.body)
        if type(payload) is not dict or set(payload) != {"revision", "label", "reason"}:
            raise ValidationError("Check the brand review fields.")
        review = review_query_brand(
            project=project, connection_id=connection.pk, observation_id=observation.pk,
            user=request.user, expected_revision=payload["revision"], label=payload["label"],
            reason=payload["reason"],
        )
    except PermissionDenied:
        return _response({"errors": [{"message": "You cannot review this query."}]}, HTTPStatus.FORBIDDEN)
    except BrandReviewConflict:
        return _response({"errors": [{"message": "Brand review changed; reload this query before saving."}]}, HTTPStatus.CONFLICT)
    except (ValueError, TypeError, ValidationError):
        return _response({"errors": [{"message": "Check the submitted brand review."}]}, HTTPStatus.BAD_REQUEST)
    return _response({"review": {"revision": review.revision, "label": review.label}}, HTTPStatus.CREATED)
