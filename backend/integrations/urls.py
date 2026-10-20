from django.urls import path
from .repository_views import repository_callback, repository_command, repository_connections, repository_webhook
from .yandex_sync_views import yandex_syncs, yandex_refresh_reported_revoked
from .yandex_views import project_yandex
from .yandex_oauth_views import yandex_grants, yandex_oauth_start, yandex_oauth_callback, yandex_oauth_revoke, yandex_unknown_revoked
from .business_profile_views import business_profile_callback, project_business_profile

from .ga4_views import (ga4_oauth_callback, ga4_oauth_grants, ga4_oauth_link, ga4_oauth_revoke,
                        ga4_oauth_select, ga4_oauth_start, ga4_quality_history, ga4_quality_review,
                        ga4_sync_cancel, ga4_sync_start, ga4_sync_status)

from .api import (csv_source_create, csv_source_upload, csv_source_state, project_sources, query_reviews, source_import_history,
                  source_opportunity_preview, source_queries)
from .oauth_views import (google_backfill_cancel, google_backfill_start, google_backfill_status,
                           google_coverage_cancel, google_coverage_start, google_coverage_status,
                          google_oauth_callback, google_oauth_grants, google_oauth_revoke, google_oauth_select,
                           google_oauth_start, google_sync_cancel, google_sync_start, google_sync_status)
from .oauth_views import google_source_schedule_start, google_source_schedule_status, google_source_schedule_toggle
from .search_console_query_page_api import project_query_page
from .health_source_api import project_integration_health


urlpatterns = [
    path("integrations/repository/oauth/callback/", repository_callback, name="repository-oauth-callback"),
    path("integrations/repository/webhook/", repository_webhook, name="repository-webhook"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/repositories/", repository_connections, name="repository-connections"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/repositories/consent/", repository_command, name="repository-consent"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/repositories/grants/<int:grant_id>/revoke/", repository_command, name="repository-revoke"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/repositories/grants/<int:grant_id>/report-revoked/", repository_command, {"reported": True}, name="repository-report-revoked"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/repositories/consents/<int:consent_id>/report-revoked/", repository_command, name="repository-unknown-revoked"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/yandex/sync/", yandex_syncs, name="yandex-syncs"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/yandex/sync/<int:job_id>/", yandex_syncs, name="yandex-sync-detail"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/yandex/grants/<int:grant_id>/refresh-report-revoked/", yandex_refresh_reported_revoked, name="yandex-refresh-reported-revoked"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/yandex/exchanges/<int:intent_id>/report-revoked/", yandex_unknown_revoked, name="yandex-unknown-revoked"),
    path("integrations/yandex/oauth/callback/", yandex_oauth_callback, name="yandex-oauth-callback"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/yandex/oauth/start/", yandex_oauth_start, name="yandex-oauth-start"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/yandex/grants/", yandex_grants, name="yandex-grants"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/yandex/grants/<int:grant_id>/revoke/", yandex_oauth_revoke, name="yandex-oauth-revoke"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/yandex/imports/", project_yandex, name="project-yandex-imports"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/yandex/imports/<int:job_id>/", project_yandex, name="project-yandex-import"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/sources/csv/", csv_source_create, name="csv-source-create"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/sources/<int:connection_id>/csv/", csv_source_upload, name="csv-source-upload"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/integration-health/", project_integration_health,
         name="project-integration-health"),
    path("integrations/google-business-profile/oauth/callback/", business_profile_callback, name="business-profile-callback"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/business-profile/", project_business_profile,
         name="project-business-profile"),
    path("integrations/google-analytics/oauth/callback/", ga4_oauth_callback, name="ga4-oauth-callback"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/analytics/oauth/start/", ga4_oauth_start,
         name="ga4-oauth-start"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/analytics/oauth/grants/", ga4_oauth_grants,
         name="ga4-oauth-grants"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/analytics/oauth/grants/<int:grant_id>/select/",
         ga4_oauth_select, name="ga4-oauth-select"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/analytics/oauth/grants/<int:grant_id>/link/",
         ga4_oauth_link, name="ga4-oauth-link"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/analytics/oauth/grants/<int:grant_id>/revoke/",
         ga4_oauth_revoke, name="ga4-oauth-revoke"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/analytics/sources/<int:connection_id>/sync/",
         ga4_sync_start, name="ga4-sync-start"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/analytics/sources/<int:connection_id>/sync/status/",
         ga4_sync_status, name="ga4-sync-status"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/analytics/sources/<int:connection_id>/sync/<int:job_id>/cancel/",
         ga4_sync_cancel, name="ga4-sync-cancel"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/analytics/sources/<int:connection_id>/quality/",
         ga4_quality_history, name="ga4-quality-history"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/analytics/sources/<int:connection_id>/quality/reviews/",
         ga4_quality_review, name="ga4-quality-review"),
    path("integrations/google-search-console/oauth/callback/", google_oauth_callback, name="google-oauth-callback"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/search-console/oauth/start/", google_oauth_start, name="google-oauth-start"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/search-console/oauth/grants/", google_oauth_grants, name="google-oauth-grants"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/search-console/oauth/grants/<int:grant_id>/select/", google_oauth_select, name="google-oauth-select"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/search-console/oauth/grants/<int:grant_id>/revoke/", google_oauth_revoke, name="google-oauth-revoke"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/sources/<int:connection_id>/sync/", google_sync_start, name="google-sync-start"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/sources/<int:connection_id>/query-page/", project_query_page, name="google-query-page"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/sources/<int:connection_id>/sync/status/", google_sync_status, name="google-sync-status"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/sources/<int:connection_id>/sync/<int:job_id>/cancel/", google_sync_cancel, name="google-sync-cancel"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/sources/<int:connection_id>/backfill/", google_backfill_start, name="google-backfill-start"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/sources/<int:connection_id>/backfill/status/", google_backfill_status, name="google-backfill-status"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/sources/<int:connection_id>/backfill/<int:backfill_id>/cancel/", google_backfill_cancel, name="google-backfill-cancel"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/sources/<int:connection_id>/sync-schedule/", google_source_schedule_start, name="google-source-schedule-start"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/sources/<int:connection_id>/sync-schedule/status/", google_source_schedule_status, name="google-source-schedule-status"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/sources/<int:connection_id>/sync-schedule/<int:schedule_id>/toggle/", google_source_schedule_toggle, name="google-source-schedule-toggle"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/sources/<int:connection_id>/coverage/", google_coverage_start, name="google-coverage-start"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/sources/<int:connection_id>/coverage/status/", google_coverage_status, name="google-coverage-status"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/sources/<int:connection_id>/coverage/<int:job_id>/cancel/", google_coverage_cancel, name="google-coverage-cancel"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/sources/", project_sources, name="project-sources"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/sources/<int:connection_id>/state/", csv_source_state, name="csv-source-state"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/sources/<int:connection_id>/imports/", source_import_history, name="source-import-history"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/sources/<int:connection_id>/imports/<int:import_id>/opportunities/", source_opportunity_preview, name="source-opportunity-preview"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/sources/<int:connection_id>/queries/", source_queries, name="source-queries"),
    path("organizations/<int:organization_id>/projects/<int:project_id>/sources/<int:connection_id>/queries/<int:observation_id>/reviews/", query_reviews, name="query-brand-reviews"),
]
