from django.contrib import admin

from tenancy.admin import InspectOnlyAdmin

from .models import (
    BusinessProfileOAuthGrant,
    BusinessProfileOAuthIntent,
    GA4OAuthGrant,
    GA4OAuthIntent,
    GA4LandingPageSnapshot,
    GA4MeasurementReview,
    GoogleOAuthGrant,
    ImportRowError,
    ImportExecutionState,
    ImportRun,
    GoogleOAuthIntent,
    IntegrationConnection,
    PendingArtifactCleanup,
    SearchAnalyticsPageSnapshot,
    SearchAnalyticsQueryPageSnapshot,
    SearchConsoleBackfill,
    SearchConsoleCoverageObservation,
    SearchMetricObservation,
    SyncCursor,
)


@admin.register(BusinessProfileOAuthIntent)
class BusinessProfileOAuthIntentAdmin(InspectOnlyAdmin):
    fields = ("organization", "project", "actor", "status", "app_revision", "policy_version", "created_at", "expires_at", "used_at")
    list_display = ("id", "organization_id", "project_id", "actor_id", "status", "created_at")
    search_fields = ("=id", "=project__id", "=organization__id")


@admin.register(BusinessProfileOAuthGrant)
class BusinessProfileOAuthGrantAdmin(InspectOnlyAdmin):
    fields = ("organization", "project", "actor", "intent", "state", "revision", "scope", "created_at", "revoked_at")
    list_display = ("id", "organization_id", "project_id", "actor_id", "state", "revision")
    search_fields = ("=id", "=project__id", "=organization__id")


@admin.register(GA4OAuthIntent)
class GA4OAuthIntentAdmin(InspectOnlyAdmin):
    fields = ("organization", "project", "actor", "status", "created_at", "expires_at", "used_at")
    list_display = ("id", "organization_id", "project_id", "actor_id", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("=id", "=organization__id", "=project__id")


@admin.register(GA4LandingPageSnapshot)
class GA4LandingPageSnapshotAdmin(InspectOnlyAdmin):
    fields = ("project", "connection", "grant", "job", "property_id", "hostname", "day", "report_kind", "offset", "collected_at")
    list_display = ("id", "project_id", "connection_id", "day", "report_kind", "offset", "collected_at")
    search_fields = ("=id", "=project__id", "=connection__id", "=job__id")


@admin.register(GA4MeasurementReview)
class GA4MeasurementReviewAdmin(InspectOnlyAdmin):
    fields = ("project", "connection", "actor", "revision", "property_id", "currency", "timezone",
              "instrumentation_state", "event_quality_state", "created_at")
    list_display = ("id", "project_id", "connection_id", "revision", "event_quality_state", "created_at")
    search_fields = ("=id", "=project__id", "=connection__id")


@admin.register(GA4OAuthGrant)
class GA4OAuthGrantAdmin(InspectOnlyAdmin):
    fields = ("organization", "project", "actor", "state", "revision", "scope", "property_id",
              "verified_at", "revoked_at", "created_at", "updated_at")
    list_display = ("id", "organization_id", "project_id", "actor_id", "state", "revision")
    list_filter = ("state",)
    search_fields = ("=id", "=organization__id", "=project__id")


@admin.register(GoogleOAuthGrant)
class GoogleOAuthGrantAdmin(InspectOnlyAdmin):
    fields = ("organization", "project", "actor", "state", "revision", "scope",
              "selected_property_id", "verified_at", "revoked_at", "created_at", "updated_at")
    list_display = ("id", "organization_id", "project_id", "actor_id", "state", "revision", "updated_at")
    list_filter = ("state",)
    search_fields = ("=id", "=organization__id", "=project__id", "=actor__id")


@admin.register(GoogleOAuthIntent)
class GoogleOAuthIntentAdmin(InspectOnlyAdmin):
    fields = ("organization", "project", "actor", "redirect_uri", "status", "created_at", "expires_at", "used_at")
    list_display = ("id", "organization_id", "project_id", "actor_id", "status", "created_at", "expires_at")
    list_filter = ("status",)
    search_fields = ("=id", "=organization__id", "=project__id", "=actor__id")


@admin.register(IntegrationConnection)
class IntegrationConnectionAdmin(InspectOnlyAdmin):
    fields = (
        "project", "provider", "external_property_id", "credential_status", "capabilities",
        "available_dimensions", "source_semantics", "source_semantics_version", "timezone", "currency",
        "backfill_limit_days", "state", "created_at", "updated_at",
    )
    readonly_fields = ("credential_status",)
    list_display = ("id", "project_id", "provider", "external_property_id", "credential_status", "state", "updated_at")
    list_filter = ("provider", "state")
    search_fields = ("=id", "=project__id", "external_property_id")

    @admin.display(description="Credential reference")
    def credential_status(self, obj):
        return "configured" if obj and obj.credential_reference else "missing"


@admin.register(ImportRun)
class ImportRunAdmin(InspectOnlyAdmin):
    fields = (
        "project", "connection", "job", "source_artifact", "source_format", "source_checksum", "provider",
        "external_property_id", "source_semantics", "source_semantics_version", "date_start", "date_end",
        "observation_dimensions", "source_timezone", "source_currency", "coverage_state", "coverage", "fresh_through",
        "status", "rows_seen", "rows_imported", "row_errors", "created_at",
    )
    list_display = ("id", "project_id", "connection_id", "provider", "source_format", "status", "coverage_state", "created_at")
    list_filter = ("provider", "source_format", "status", "coverage_state")
    search_fields = ("=id", "=project__id", "=connection__id", "=job__id", "external_property_id")


@admin.register(ImportRowError)
class ImportRowErrorAdmin(InspectOnlyAdmin):
    fields = ("import_run", "source_row", "category", "field", "created_at")
    list_display = ("id", "import_run_id", "source_row", "category", "field")
    list_filter = ("category", "field")
    search_fields = ("=id", "=import_run__id", "=import_run__project__id")


@admin.register(PendingArtifactCleanup)
class PendingArtifactCleanupAdmin(InspectOnlyAdmin):
    fields = ("project", "created_at")
    list_display = ("id", "project_id", "created_at")
    search_fields = ("=id", "=project__id")


@admin.register(ImportExecutionState)
class ImportExecutionStateAdmin(InspectOnlyAdmin):
    fields = ("job", "storage_failures", "retry_after", "updated_at")
    list_display = ("id", "job_id", "storage_failures", "retry_after", "updated_at")
    search_fields = ("=id", "=job__id", "=job__project__id")


@admin.register(SearchMetricObservation)
class SearchMetricObservationAdmin(InspectOnlyAdmin):
    fields = (
        "import_run", "source_row", "date_start", "date_end", "time_granularity", "search_type", "query", "page",
        "country", "device", "search_appearance", "clicks", "impressions", "ctr", "position", "unavailable_metrics",
        "grain_hash", "created_at",
    )
    list_display = (
        "id", "import_run_id", "source_row", "date_start", "search_type",
    )
    list_filter = ("time_granularity", "search_type")
    search_fields = ("=id", "=import_run__id", "=import_run__project__id", "=import_run__connection__id")


@admin.register(SearchAnalyticsPageSnapshot)
class SearchAnalyticsPageSnapshotAdmin(InspectOnlyAdmin):
    fields = ("project", "connection", "grant", "job", "external_property_id", "day", "dimension",
              "start_row", "collected_at")
    list_display = ("id", "project_id", "connection_id", "day", "dimension", "start_row", "collected_at")
    list_filter = ("dimension",)
    search_fields = ("=id", "=project__id", "=connection__id", "=job__id")


@admin.register(SearchAnalyticsQueryPageSnapshot)
class SearchAnalyticsQueryPageSnapshotAdmin(InspectOnlyAdmin):
    fields = ("project", "connection", "grant", "job", "grant_revision", "external_property_id", "day", "start_row",
              "result_sha256", "collected_at")
    list_display = ("id", "project_id", "connection_id", "day", "start_row", "collected_at")
    search_fields = ("=id", "=project__id", "=connection__id", "=job__id")


@admin.register(SearchConsoleCoverageObservation)
class SearchConsoleCoverageObservationAdmin(InspectOnlyAdmin):
    fields = ("project", "connection", "grant", "job", "source", "external_property_id", "requested_url", "collected_at")
    list_display = ("id", "project_id", "connection_id", "source", "collected_at")
    list_filter = ("source",)
    search_fields = ("=id", "=project__id", "=connection__id", "=job__id")


@admin.register(SearchConsoleBackfill)
class SearchConsoleBackfillAdmin(InspectOnlyAdmin):
    fields = ("organization", "project", "connection", "grant", "actor", "start_day", "end_day",
              "next_day", "dimension", "status", "error_category", "current_job", "created_at", "updated_at")
    list_display = ("id", "project_id", "connection_id", "status", "next_day", "updated_at")
    list_filter = ("status",)
    search_fields = ("=id", "=project__id", "=connection__id")


@admin.register(SyncCursor)
class SyncCursorAdmin(InspectOnlyAdmin):
    fields = (
        "project", "connection", "status", "coverage_start", "coverage_end", "fresh_through", "quota_state",
        "retry_after", "error_category", "revision", "last_attempt_at", "last_success_at", "created_at", "updated_at",
    )
    list_display = ("id", "project_id", "connection_id", "status", "revision", "quota_state", "fresh_through", "updated_at")
    list_filter = ("status", "quota_state")
    search_fields = ("=id", "=project__id", "=connection__id")


from . import yandex_admin
from . import serp_admin
from . import repository_admin
