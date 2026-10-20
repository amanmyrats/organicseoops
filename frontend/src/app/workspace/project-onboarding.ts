import { Title } from '@angular/platform-browser';
import { DOCUMENT, JsonPipe, NgTemplateOutlet } from '@angular/common';
import { Component, computed, DestroyRef, effect, ElementRef, Inject, OnDestroy, OnInit, signal, ViewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';
import { ProjectCruxHistory } from './project-crux-history';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import {
  AccountApi,
  GoogleOAuthGrantInfo,
  OnboardingSourceChoice,
  OnboardingStep,
  ProjectConfigurationInfo,
  ProjectInfo,
  ProjectSourceInfo,
  SourceQueryInfo,
} from '../account/account-api';

type CoverageJob = { id: number; status: string; error_category: string; inspection_url: string;
  requests_attempted: number; sources_recorded: string[];
  results: { source: 'inspection' | 'sitemaps'; result: Record<string, unknown> }[] };
type BackfillJob = { id: number; status: 'running' | 'paused' | 'succeeded'; start_day: string;
  end_day: string; next_day: string; dimension: string; current_job: number | null; error_category: string };
type SourceSchedule = { id: number; enabled: boolean; dimension: string; next_run_at: string | null;
  last_run_at: string | null; last_error_category: string; skipped_occurrences: number };
type IndexationReport = { crawl_run_id: number; diagnostics_id: number;
  coverage: { state: string; engine_indexing_reports: string };
  urls: { url: string; crawlability: string; discovered_by: string[]; indexability_signals: string[];
    fetch_observations: { status_code: number | null; directive_state: string; declared_canonical: string | null }[];
    engine_reports: { provider: string; property: string; indexed_state: string; method: string;
      engine_selected_canonical: string | null; declared_canonical: string | null;
      collected_at: string; engine_last_crawl_at: string | null;
      stale_relative_to_local_crawl: boolean | null; disagreement_candidates: string[] }[] }[] };
type PerformanceJob = { id: number; status: string; error_category: string; target: string; grain: string;
  strategy: string; sources: string[]; requests_attempted: number; sources_recorded: number;
  lab: string; field: string; coverage: string };
type PerformanceObservation = { id: number; source: 'psi_lab' | 'crux_current' | 'crux_history';
  collected_at: string; result: Record<string, unknown> };
type OpportunityPreview = { method: string; property: string; dimension: string; timezone: string;
  market: string; languages: string[]; window: { import_id: number; start: string; end: string };
  thresholds: { position_inclusive: number[]; min_impressions: number; ctr_below: string };
  coverage: { provider_top_rows: string; hidden_queries: string; file: string };
  candidates: { detector: string; observation_id: number; query: string | null; page: string | null;
    clicks: number; impressions: number; ctr: string; position: string; confidence: string }[];
  truncated_candidates: boolean };
type FindingInfo = { id: number; detector: string; method_version: string; subject: string;
  source_metric_id: number | null; source_indexation_id: number | null;
  source_diagnostics_id: number | null; source_performance_id: number | null;
  source_import_id: number | null; source_connection_id: number | null;
  source_current: boolean; confidence: string; detected_at: string; evidence: Record<string, unknown>;
  review: null | { id: number; revision: number; priority: string; estimated_effort: string;
    business_relevance: string; review_reason: string } };
type GA4GrantInfo = { id: number; state: string; revision: number; property_id: string;
  selected_origins: string[]; scope_current: boolean; source_status: string; verified_at: string };
type GA4JobInfo = { id: number; status: string; day: string; hostname: string; report_kind: string; error_category: string;
  requests_attempted: number; pages_recorded: number; source_coverage: string;
  sampling_or_threshold_gaps: boolean | null };
type GA4PageInfo = { id: number; offset: number; report_kind: string; collected_at: string; result: {
  day: string; timezone: string; currency: string; report_kind: string; rows: { hostname: string; path: string;
    sessions: number; key_events: string; total_revenue: string; session_default_channel_group?: string }[];
  coverage: { sampled: boolean; thresholded: boolean; other_row_loss: boolean;
    full_activity_coverage: string; instrumentation_verified: boolean; acquisition_scope: string;
    omitted_foreign_or_parameterized_rows: number } } };
type GA4QualityInfo = { id: number; revision: number; property_id: string; currency: string; timezone: string;
  definitions: { goal: string; event_name: string; value_definition: string }[];
  instrumentation_state: 'unverified' | 'manual_reviewed'; event_quality_state: string; instrumentation_notes: string;
  attribution_notes: string; consent_notes: string; tracking_change_notes: string; created_at: string };

@Component({
  selector: 'app-project-onboarding',
  imports: [RouterLink, NgTemplateOutlet, JsonPipe, ProjectCruxHistory],
  template: `
    <section class="workspace-shell" lang="en" aria-labelledby="onboarding-title">
      <header [attr.lang]="uiLanguage()">
      <p class="eyebrow">{{ t("Project setup") }}</p>
      <h1 id="onboarding-title">{{ t("Resumable project onboarding") }}</h1>
      <p><a [routerLink]="pairedQueryRoute()">{{ t("Inspect genuine paired Search Console query–page reports") }}</a></p>
      <p><a [routerLink]="firstAuditRoute()">{{ t("Review the budgeted first audit and source-backed next actions") }}</a></p>
      <a routerLink="/app">{{ t("Back to organization and project context") }}</a>

      @if (uiLanguage() === 'tr') {
        <p role="status">{{ t("Unreviewed Turkish setup, CSV, query and finding-review draft in local development. Provider values and remaining report interfaces remain English; bilingual approval is pending.") }}</p>
      }
      </header>
      @if (csvAcknowledgment()?.message === message() && csvAcknowledgment(); as acknowledgment) {
        <p class="form-status" [attr.lang]="uiLanguage()" role="status">{{ t("CSV job acknowledged:") }} {{ acknowledgment.id }} (<span lang="en">{{ acknowledgment.status }}</span>). {{ t("Check job progress, then refresh import history. Export coverage remains unknown.") }}</p>
      } @else if (message()) { <p class="form-status" [attr.lang]="textLanguage(message())" role="status">{{ t(message()) }}</p> }
      @if (error()) { <p #errorSummary class="form-status error" [attr.lang]="textLanguage(error())" role="alert" tabindex="-1">{{ t(error()) }}</p> }
      @if (saving()) { <p class="form-status" [attr.lang]="uiLanguage()" role="status">{{ t("Saving project setup.") }}</p> }

      @if (loading()) {
        <p [attr.lang]="uiLanguage()" role="status">{{ t("Loading project onboarding.") }}</p>
      } @else if (denied()) {
        <section class="workspace-panel" [attr.lang]="uiLanguage()">
          <h2>{{ t("Project access unavailable") }}</h2>
          <p>{{ t("This project was not found in your authorized scope. Return to the workspace and choose an accessible project.") }}</p>
        </section>
      } @else if (project() && configuration()) {
        <div class="scope-summary" [attr.lang]="uiLanguage()" aria-live="polite">
          <strong>{{ t("Active project") }}</strong>
          <span lang="">{{ project()!.name }}</span>
          <span>{{ configuration()!.canonical_origin }}</span>
          <span>{{ t("Role:") }} <span lang="en">{{ project()!.role }}</span></span>
        </div>

        <section class="workspace-panel" aria-labelledby="existing-sources-title">
          <h2 id="existing-sources-title" [attr.lang]="uiLanguage()">{{ t("Existing source status") }}</h2>
          @if (canManage()) {
            <form [attr.lang]="uiLanguage()" (submit)="createCsvSource($event)">
              <label for="csv-property">{{ t("Local Search Console CSV property") }}</label>
              <select id="csv-property" name="property" required>
                <option [value]="project()!.canonical_origin">{{ project()!.canonical_origin }}</option>
                @for (origin of project()!.aliases; track origin) { <option [value]="origin">{{ origin }}</option> }
              </select>
              <p>{{ t("This records a local file source for the selected exact origin. It does not authorize Google access.") }}</p>
              <button type="submit" [disabled]="csvBusy()">{{ t("Set up local CSV source") }}</button>
            </form>
          }
          @if (pendingCsv() && !csvBusy()) {
            <p [attr.lang]="uiLanguage()" role="status">{{ t("Upload acknowledgment is uncertain. Check project jobs or retry the same frozen file and metadata.") }}</p>
            <button [attr.lang]="uiLanguage()" type="button" (click)="retryCsvUpload()">{{ t("Retry same CSV request") }}</button>
          }
          <p [attr.lang]="uiLanguage()"><a [routerLink]="['/app/jobs', organizationId, projectId]">{{ t("View import job progress and cancellation") }}</a></p>
          @if (sourceLoading()) {
            <p [attr.lang]="uiLanguage()" role="status">{{ t("Loading existing source status.") }}</p>
          } @else if (sourceError()) {
            <p [attr.lang]="uiLanguage()" role="status">{{ t("Source status is unavailable; this does not mean there are no imports. Reload the project to retry.") }}</p>
          } @else if (sources().length === 0) {
            <p [attr.lang]="uiLanguage()">{{ t("No source connections have been recorded for this project.") }}</p>
          } @else {
            <ul [attr.aria-label]="t('Existing project sources')" [attr.lang]="uiLanguage()">
              @for (source of sources(); track source.id) {
                <li lang="en">
                  <strong>{{ source.provider }}: {{ source.property }}</strong>
                  <span [attr.lang]="uiLanguage()"> · <span lang="en">{{ source.state }}</span> · {{ t(source.scope_current ? 'within current project scope' : 'scope changed; unavailable') }}</span>
                   <span [attr.lang]="uiLanguage()"> · {{ t('CSV import') }} {{ t(source.csv_import_supported ? 'supported' : 'unsupported') }}</span>
                   @if (source.scope_kind === 'verified_domain_page_only') {
                     <p [attr.lang]="uiLanguage()">{{ t("Domain property used only for pages on these currently verified project origins:") }}
                       @if (source.approved_origins?.length) { <span lang="en">{{ source.approved_origins!.join(', ') }}</span> }
                       @else { {{ t("none available") }} }.
                       {{ t("Domain-wide query, date and property totals are unavailable. Google top rows across all subdomains can omit in-scope pages; omitted or absent data is unknown, not zero.") }}</p>
                   }
                    <span [attr.lang]="uiLanguage()"> · {{ t('Credential:') }} {{ t(source.credential_status === 'not_connected' ? 'not connected' : 'OAuth reference recorded') }}</span>
                    @if (source.provider === 'yandex_webmaster') {
                      <p lang="en">Yandex aggregate history preserves provider timestamp offsets and missing indicators separately from Google metrics.
                        <a [routerLink]="['/app/yandex', organizationId, projectId]">Manage Yandex consent, bounded sync and history</a></p>
                    } @else if (source.provider === 'google_analytics_4') {
                      <p [attr.lang]="uiLanguage()">{{ t("Analytics property") }} <span lang="en">{{ source.property }}</span> · {{ t("configured host only") }}
                        @if (source.approved_origins?.length) { <span lang="en">{{ source.approved_origins!.join(', ') }}</span> }
                        @else { {{ t("scope unavailable") }} }.
                        {{ t("Search Console clicks, Analytics sessions and key events are different measurements. A configured web stream does not prove collection or conversion goals; absent rows are unknown. GA4's hostname-only landing report cannot distinguish this exact HTTPS origin from another scheme or port on the same host, so Analytics report sync is unavailable.") }}</p>
                      @if (canManage() && source.api_sync_available) {
                        <form [attr.lang]="uiLanguage()" (submit)="startGA4Sync($event, source.id)">
                          <label [for]="'ga4-day-' + source.id">{{ t("Analytics property-local reporting day") }}</label>
                          <input [id]="'ga4-day-' + source.id" name="day" type="date" required />
                          <label [for]="'ga4-kind-' + source.id">{{ t("Analytics report grain") }}</label>
                          <select [id]="'ga4-kind-' + source.id" name="report_kind">
                            <option value="all_channels">{{ t("All reported session channels") }}</option>
                            <option value="organic_search">{{ t("GA4 Organic Search session channel only") }}</option>
                          </select>
                          <p [attr.lang]="uiLanguage()">{{ t("One day aged 3–90 days, one selected hostname. Up to five attempted internal units: property, web streams, compatibility and up to two 100-row report pages. Data API sampling, thresholds, other rows and collection gaps remain visible.") }}</p>
                          <button [attr.lang]="uiLanguage()" type="submit" [disabled]="ga4SyncBusy() !== null">{{ t("Request bounded Analytics report") }}</button>
                        </form>
                      }
                      <button [attr.lang]="uiLanguage()" type="button" class="secondary-button" (click)="refreshGA4Sync(source.id)" [disabled]="ga4SyncBusy() !== null">{{ t("Refresh Analytics report status") }}</button>
                      @if (ga4SyncSourceId() === source.id) {
                        @if (ga4SyncLoading()) { <p [attr.lang]="uiLanguage()" role="status">{{ t("Loading Analytics report status.") }}</p> }
                        @else if (ga4SyncError()) { <p [attr.lang]="uiLanguage()" role="alert">{{ t("Analytics report status unavailable; refresh before retrying.") }}</p> }
                        @else if (ga4SyncJob(); as job) {
                          <p [attr.lang]="uiLanguage()" role="status">{{ t("Analytics job") }} {{ job.id }}: <span lang="en">{{ job.status }}</span> · {{ job.day }} · <span lang="en">{{ job.report_kind }}</span> · {{ t("hostname") }} <span lang="en">{{ job.hostname }}</span>;
                            {{ job.requests_attempted }} {{ t("attempted requests,") }} {{ job.pages_recorded }} {{ t("pages recorded.") }}
                            <span lang="en">{{ job.source_coverage }}</span>. @if (job.error_category) { {{ t("Reason:") }} <span lang="en">{{ job.error_category }}</span>. }</p>
                          @if (job.status === 'queued' || job.status === 'running') {
                            <button [attr.lang]="uiLanguage()" type="button" (click)="cancelGA4Sync(source.id, job.id)" [disabled]="ga4SyncBusy() !== null">{{ t("Cancel Analytics request") }}</button>
                          }
                          @for (page of ga4SyncPages(); track page.id) {
                            <p [attr.lang]="uiLanguage()">GA4 {{ page.result.day }} · <span lang="en">{{ page.result.timezone }}</span> · <span lang="en">{{ page.result.currency }}</span> · <span lang="en">{{ page.report_kind }}</span> · {{ t("offset") }} {{ page.offset }}.
                              {{ t("Source scope") }} <span lang="en">{{ page.result.coverage.acquisition_scope }}</span>{{ t("; GA4 session channel is not a Search Console click or a per-goal conversion.") }}
                              {{ t("Sampling") }} {{ t(page.result.coverage.sampled ? 'reported' : 'not reported') }};
                              {{ t("thresholding") }} {{ t(page.result.coverage.thresholded ? 'reported' : 'not reported') }};
                              {{ t("other-row loss") }} {{ t(page.result.coverage.other_row_loss ? 'reported' : 'not reported') }};
                              {{ t("omitted out-of-scope/parameterized rows") }} {{ page.result.coverage.omitted_foreign_or_parameterized_rows }}.
                              {{ t("Full activity") }} <span lang="en">{{ page.result.coverage.full_activity_coverage }}</span>;
                              {{ t("instrumentation") }} {{ t(page.result.coverage.instrumentation_verified ? 'verified' : 'not verified') }}.</p>
                            <ul>@for (row of page.result.rows; track $index) {
                              <li [attr.lang]="uiLanguage()"><span lang="en">{{ row.hostname }}{{ row.path }}</span> · @if (row.session_default_channel_group) { <span lang="en">{{ row.session_default_channel_group }}</span> } @else { {{ t('all session channels') }} }
                                · {{ t("sessions") }} {{ row.sessions }} · {{ t("key events") }} {{ row.key_events }}
                                · {{ t("reported revenue") }} {{ row.total_revenue }} <span lang="en">{{ page.result.currency }}</span>.</li>
                            }</ul>
                          }
                        } @else { <p [attr.lang]="uiLanguage()">{{ t("No Analytics report job recorded for this source.") }}</p> }
                      }
                      <button [attr.lang]="uiLanguage()" type="button" class="secondary-button" (click)="loadGA4Quality(source.id)" [disabled]="ga4QualityLoading()">{{ t("Review Analytics measurement definitions") }}</button>
                      @if (ga4QualitySourceId() === source.id) {
                        @if (ga4QualityLoading()) { <p [attr.lang]="uiLanguage()" role="status">{{ t("Loading measurement definitions.") }}</p> }
                        @else if (ga4QualityError()) { <p [attr.lang]="uiLanguage()" role="alert">{{ t("Measurement review history unavailable; refresh before editing.") }}</p> }
                        @else if (ga4QualityLoaded()) {
                          @if (!ga4QualityReviews().length) { <p [attr.lang]="uiLanguage()">{{ t("No property-bound conversion event definitions reviewed. GA4 aggregate key events cannot be assigned to a goal.") }}</p> }
                          @else {
                            <ul [attr.aria-label]="t('Analytics measurement review history')" [attr.lang]="uiLanguage()">
                              @for (review of ga4QualityReviews(); track review.id) {
                                <li [attr.lang]="uiLanguage()">{{ t("Revision") }} {{ review.revision }} · {{ t("property") }} <span lang="en">{{ review.property_id }}</span> · <span lang="en">{{ review.currency }}</span> · <span lang="en">{{ review.timezone }}</span> · <span lang="en">{{ review.instrumentation_state }}</span> · {{ t("event quality") }} <span lang="en">{{ review.event_quality_state }}</span> · {{ review.created_at }}.
                                  <p [attr.lang]="uiLanguage()">{{ t("Instrumentation:") }} @if (review.instrumentation_notes) { <span lang="">{{ review.instrumentation_notes }}</span> } @else { {{ t('not verified') }} };
                                    {{ t("attribution:") }} @if (review.attribution_notes) { <span lang="">{{ review.attribution_notes }}</span> } @else { {{ t('unknown') }} };
                                    {{ t("consent gaps:") }} @if (review.consent_notes) { <span lang="">{{ review.consent_notes }}</span> } @else { {{ t('unknown') }} };
                                    {{ t("tracking changes:") }} @if (review.tracking_change_notes) { <span lang="">{{ review.tracking_change_notes }}</span> } @else { {{ t('unknown') }} }.</p>
                                  <ul>@for (definition of review.definitions; track definition.event_name) {
                                    <li [attr.lang]="uiLanguage()"><span lang="">{{ definition.goal }}</span> → <span lang="en">{{ definition.event_name }}</span>; {{ t("manual value definition") }} @if (definition.value_definition) { <span lang="">{{ definition.value_definition }}</span> } @else { {{ t('unavailable') }} }.</li>
                                  }</ul>
                                </li>
                              }
                            </ul>
                            @if (ga4QualityTruncated()) { <p [attr.lang]="uiLanguage()">{{ t("Older measurement reviews are not shown.") }}</p> }
                          }
                          @if (canManage() && ga4QualitySourceCurrent()) {
                            <form [attr.lang]="uiLanguage()" (submit)="saveGA4Quality($event, source.id)">
                              <p [attr.lang]="uiLanguage()">{{ t("Describe up to ten manual goal → GA4 event mappings. These are definitions, not per-event counts. One line per mapping: goal | event_name | manual value definition.") }}</p>
                              <label [for]="'ga4-definitions-' + source.id">{{ t("Goals and event names") }}</label>
                              <textarea lang="" [id]="'ga4-definitions-' + source.id" name="definitions" rows="4" maxlength="3000"></textarea>
                              <label [for]="'ga4-instrumentation-' + source.id">{{ t("Instrumentation review status") }}</label>
                              <select [id]="'ga4-instrumentation-' + source.id" name="instrumentation_state">
                                <option value="unverified">{{ t("Unverified") }}</option>
                                <option value="manual_reviewed">{{ t("Manually reviewed (not provider-verified)") }}</option>
                              </select>
                              <label [for]="'ga4-event-quality-' + source.id">{{ t("Manual missing/duplicate event concern") }}</label>
                              <select [id]="'ga4-event-quality-' + source.id" name="event_quality_state">
                                <option value="not_checked">{{ t("Not checked") }}</option>
                                <option value="suspected_missing">{{ t("Suspected missing events") }}</option>
                                <option value="suspected_duplicate">{{ t("Suspected duplicate events") }}</option>
                                <option value="suspected_both">{{ t("Suspected missing and duplicate events") }}</option>
                                <option value="manual_review_no_concern">{{ t("Manual review noted no concern (not verified)") }}</option>
                              </select>
                              <label [for]="'ga4-instrumentation-notes-' + source.id">{{ t("Instrumentation review notes") }}</label>
                              <textarea lang="" [id]="'ga4-instrumentation-notes-' + source.id" name="instrumentation_notes" maxlength="1000"></textarea>
                              <label [for]="'ga4-attribution-notes-' + source.id">{{ t("Attribution settings/assumptions (manual)") }}</label>
                              <textarea lang="" [id]="'ga4-attribution-notes-' + source.id" name="attribution_notes" maxlength="1000"></textarea>
                              <label [for]="'ga4-consent-notes-' + source.id">{{ t("Consent/threshold/modeled reporting gaps") }}</label>
                              <textarea lang="" [id]="'ga4-consent-notes-' + source.id" name="consent_notes" maxlength="1000"></textarea>
                              <label [for]="'ga4-tracking-notes-' + source.id">{{ t("Tracking or configuration changes") }}</label>
                              <textarea lang="" [id]="'ga4-tracking-notes-' + source.id" name="tracking_change_notes" maxlength="1000"></textarea>
                              <button [attr.lang]="uiLanguage()" type="submit" [disabled]="ga4QualityBusy()">{{ t("Record human measurement revision") }}</button>
                            </form>
                          } @else { <p [attr.lang]="uiLanguage()">{{ t("Historical measurement notes remain visible; this source is not current for new reviews.") }}</p> }
                        }
                      }
                    } @else {
                    @if (source.sync; as sync) {
                     <p [attr.lang]="uiLanguage()">{{ t("Sync record:") }} <span lang="en">{{ sync.status }}</span> · {{ t("quota") }} <span lang="en">{{ sync.quota_state }}</span> · {{ t("coverage") }} {{ sync.coverage_start || t('unknown') }} {{ t('to') }} {{ sync.coverage_end || t('unknown') }} · {{ t('fresh through') }} {{ sync.fresh_through || t('unknown') }}. {{ t('Provider reports only top rows; unreported queries and pages remain unknown.') }}
                       @if (sync.retry_after) { {{ t("Local retry no earlier than") }} {{ sync.retry_after }}. }
                     </p>
                   } @else { <p [attr.lang]="uiLanguage()">{{ t("No API sync recorded for this property.") }}</p> }
                   @if (canManage() && source.api_sync_available) {
                     <form [attr.lang]="uiLanguage()" (submit)="startSync($event, source.id)">
                       <label [for]="'sync-day-' + source.id">{{ t("Finalized Search Console date (Pacific Time)") }}</label>
                       <input [id]="'sync-day-' + source.id" name="day" type="date" required />
                       <label [for]="'sync-grain-' + source.id">{{ t("Independent report dimension") }}</label>
                        <select [id]="'sync-grain-' + source.id" name="dimension">
                          @if (source.scope_kind === 'verified_domain_page_only') {
                            <option value="page">{{ t("Verified-origin pages only") }}</option>
                          } @else {
                            <option value="query">{{ t("Queries") }}</option><option value="page">{{ t("Pages") }}</option><option value="date">{{ t("Daily total") }}</option>
                          }
                       </select>
                        <p [attr.lang]="uiLanguage()">{{ t('At most') }} {{ t(source.scope_kind === 'verified_domain_page_only' ? 'two API requests (property check plus one report page)' : 'three API requests (property check plus two report pages)') }} {{ t('for one date, aged 3–90 days. Google supplies top rows only; omitted rows are unknown. Internal usage: up to') }} {{ source.scope_kind === 'verified_domain_page_only' ? 2 : 3 }} {{ t('request units.') }}</p>
                       <button [attr.lang]="uiLanguage()" type="submit" [disabled]="syncBusy() !== null || !!source.sync?.retry_after">{{ t("Sync this property") }}</button>
                     </form>
                     <button [attr.lang]="uiLanguage()" type="button" class="secondary-button" [disabled]="syncBusy() !== null" (click)="refreshSync(source.id)">{{ t("Refresh sync status") }}</button>
                   }
                     @if (syncSourceId() === source.id) {
                     @if (syncLoading()) { <p [attr.lang]="uiLanguage()" role="status">{{ t("Checking Search Console sync status.") }}</p> }
                     @else if (syncError()) { <p [attr.lang]="uiLanguage()" role="alert">{{ t("Sync status is unavailable; retry the refresh before submitting again.") }}</p> }
                     @else if (syncJob(); as job) {
                       <p [attr.lang]="uiLanguage()" role="status">{{ t("Job") }} {{ job.id }}: <span lang="en">{{ job.status }}</span> · {{ job.pages_recorded }} {{ t("pages recorded from") }} {{ job.requests_attempted }} {{ t("attempts; source coverage") }} <span lang="en">{{ job.source_coverage }}</span>. @if (job.error_category) { {{ t("Reason:") }} <span lang="en">{{ job.error_category }}</span>. }</p>
                       @if (job.status === 'queued' || job.status === 'running') {
                         <button [attr.lang]="uiLanguage()" type="button" class="secondary-button" [disabled]="syncBusy() !== null" (click)="cancelSync(source.id, job.id)">{{ t("Cancel this sync") }}</button>
                       }
                      } @else { <p [attr.lang]="uiLanguage()">{{ t("No sync job has been recorded for this source.") }}</p> }
                     }
                     @if (canManage() && source.api_sync_available) {
                       <form [attr.lang]="uiLanguage()" (submit)="startBackfill($event, source.id)">
                         <label [for]="'backfill-start-' + source.id">{{ t("Backfill first finalized Pacific Time day") }}</label>
                         <input [id]="'backfill-start-' + source.id" name="start_day" type="date" required />
                         <label [for]="'backfill-end-' + source.id">{{ t("Backfill last finalized Pacific Time day") }}</label>
                         <input [id]="'backfill-end-' + source.id" name="end_day" type="date" required />
                         <label [for]="'backfill-grain-' + source.id">{{ t("Independent report dimension") }}</label>
                         <select [id]="'backfill-grain-' + source.id" name="dimension">
                           @if (source.scope_kind === 'verified_domain_page_only') {
                             <option value="page">{{ t("Verified-origin pages only") }}</option>
                           } @else {
                             <option value="query">{{ t("Queries") }}</option><option value="page">{{ t("Pages") }}</option><option value="date">{{ t("Daily total") }}</option>
                           }
                         </select>
                         <p [attr.lang]="uiLanguage()">{{ t("One to seven days, 3–90 days old. One day runs at a time; pause on partial, quota or lost requests.") }}
                           {{ t("Up to") }} {{ source.scope_kind === 'verified_domain_page_only' ? 14 : 21 }} {{ t("internal request units for seven days. Provider top-row coverage remains incomplete and missing pages are unknown.") }}</p>
                         <button [attr.lang]="uiLanguage()" type="submit" [disabled]="backfillBusy() !== null">{{ t("Start bounded backfill") }}</button>
                       </form>
                       <button [attr.lang]="uiLanguage()" type="button" [disabled]="backfillBusy() !== null" (click)="refreshBackfill(source.id)">{{ t("Refresh backfill") }}</button>
                     }
                     @if (backfillSourceId() === source.id) {
                       @if (backfillLoading()) { <p [attr.lang]="uiLanguage()" role="status">{{ t("Checking backfill status.") }}</p> }
                       @else if (backfillError()) { <p [attr.lang]="uiLanguage()" role="alert">{{ t("Backfill status unavailable; refresh before retrying.") }}</p> }
                       @else if (backfillJob(); as batch) {
                         <p [attr.lang]="uiLanguage()" role="status">{{ t("Backfill") }} {{ batch.id }}: <span lang="en">{{ batch.status }}</span>; {{ t("requested") }} {{ batch.start_day }} {{ t("to") }}
                           {{ batch.end_day }}; {{ t("current day") }} {{ batch.next_day }}; {{ t("source") }} <span lang="en">{{ batch.dimension }}</span>.
                           @if (batch.error_category) { {{ t("Reason:") }} <span lang="en">{{ batch.error_category }}</span>. {{ t("Earlier days remain separate observations.") }} }
                         </p>
                         @if (batch.status === 'running') {
                           <button [attr.lang]="uiLanguage()" type="button" [disabled]="backfillBusy() !== null" (click)="cancelBackfill(source.id, batch.id)">{{ t("Stop remaining backfill days") }}</button>
                         }
                       } @else { <p [attr.lang]="uiLanguage()">{{ t("No backfill request recorded for this source.") }}</p> }
                     }
                     @if (canManage() && source.api_sync_available) {
                       @if (scheduleSourceId() === source.id && sourceSchedule(); as scheduled) {
                         <p [attr.lang]="uiLanguage()" role="status">{{ t("Daily") }} <span lang="en">{{ scheduled.dimension }}</span> {{ t('report:') }} {{ t(scheduled.enabled ? 'enabled' : 'paused') }};
                           {{ t('next due') }} {{ scheduled.next_run_at || t('not scheduled') }}; {{ t('last queued') }} {{ scheduled.last_run_at || t('never') }}.
                           @if (scheduled.last_error_category) { {{ t("Reason:") }} <span lang="en">{{ scheduled.last_error_category }}</span>. }
                           @if (scheduled.skipped_occurrences) { {{ t("Missed intervals skipped:") }} {{ scheduled.skipped_occurrences }}. }
                         </p>
                         <button [attr.lang]="uiLanguage()" type="button" [disabled]="scheduleBusy() !== null" (click)="toggleSchedule(source.id, scheduled.id, !scheduled.enabled)">{{ t(scheduled.enabled ? 'Pause' : 'Enable') }} {{ t('daily reports') }}</button>
                       } @else {
                         <form [attr.lang]="uiLanguage()" (submit)="createSchedule($event, source.id)">
                           <label [for]="'schedule-grain-' + source.id">{{ t("Daily report dimension") }}</label>
                           <select [id]="'schedule-grain-' + source.id" name="dimension">
                             @if (source.scope_kind === 'verified_domain_page_only') {
                               <option value="page">{{ t("Verified-origin pages only") }}</option>
                             } @else {
                               <option value="query">{{ t("Queries") }}</option><option value="page">{{ t("Pages") }}</option><option value="date">{{ t("Daily total") }}</option>
                             }
                           </select>
                           <p [attr.lang]="uiLanguage()">{{ t("One finalized Pacific Time day per occurrence, starting after you enable it. Missed days are not replayed; source loss or unknown work pauses the schedule. Pausing stops future runs; already queued work may finish. Google top rows remain incomplete.") }}</p>
                           <button [attr.lang]="uiLanguage()" type="submit" [disabled]="scheduleBusy() !== null">{{ t("Create daily report schedule") }}</button>
                         </form>
                       }
                       <button [attr.lang]="uiLanguage()" type="button" [disabled]="scheduleBusy() !== null" (click)="refreshSchedule(source.id)">{{ t("Refresh daily schedule") }}</button>
                       @if (scheduleSourceId() === source.id && scheduleError()) { <p [attr.lang]="uiLanguage()" role="alert">{{ t("Daily schedule status unavailable; refresh before retrying.") }}</p> }
                     }
                     @if (canManage() && source.coverage_available) {
                      <form [attr.lang]="uiLanguage()" (submit)="startCoverage($event, source.id)">
                        <label [for]="'coverage-url-' + source.id">{{ t("One exact project URL for Google indexed-version inspection") }}</label>
                        <input [id]="'coverage-url-' + source.id" name="inspection_url" type="url" maxlength="2048" required />
                        <p [attr.lang]="uiLanguage()">{{ t("Inspect Google's indexed version, not a live-page test. No query parameters or fragments. Also read a submitted sitemap list; only verified-origin sitemap URLs are retained, never domain-wide indexed counts. At most three attempted internal units. Missing reports are unknown.") }}</p>
                        <button [attr.lang]="uiLanguage()" type="submit" [disabled]="coverageBusy() !== null">{{ t("Inspect URL and submitted sitemaps") }}</button>
                      </form>
                    }
                    @if (coverageSourceId() === source.id) {
                      @if (coverageLoading()) { <p [attr.lang]="uiLanguage()" role="status">{{ t("Loading Google coverage job status.") }}</p> }
                      @else if (coverageError()) { <p [attr.lang]="uiLanguage()" role="alert">{{ t("Coverage status unavailable; retry refresh.") }}</p> }
                      @else if (coverageJob(); as current) {
                        <p [attr.lang]="uiLanguage()" role="status">{{ t("Inspection job") }} {{ current.id }}: <span lang="en">{{ current.status }}</span>;
                          {{ current.requests_attempted }} {{ t("attempted requests;") }} {{ current.sources_recorded.length }}
                          {{ t("scoped results.") }} @if (current.error_category) { {{ t("Reason:") }} <span lang="en">{{ current.error_category }}</span>. }</p>
                        @for (observation of current.results; track observation.source) {
                          @if (observation.source === 'inspection') {
                            <p [attr.lang]="uiLanguage()">{{ t("Google indexed-version verdict:") }} <span lang="en">{{ coverageValue(observation.result, 'verdict') }}</span>;
                              {{ t("indexed state") }} <span lang="en">{{ coverageValue(observation.result, 'indexed_state') }}</span>;
                              {{ t("last Google crawl") }} <span lang="en">{{ coverageValue(observation.result, 'last_crawl_at') }}</span>.
                              {{ t("This does not verify the current live page.") }}</p>
                          } @else {
                            <p [attr.lang]="uiLanguage()">{{ t("Submitted sitemap URLs on verified project origins only; totals and sibling-host coverage are unknown.") }}</p>
                            <ul>
                              @for (url of coverageSitemaps(observation.result); track url) { <li>{{ url }}</li> }
                            </ul>
                          }
                        }
                        <button [attr.lang]="uiLanguage()" type="button" (click)="refreshCoverage(source.id)" [disabled]="coverageBusy() !== null">{{ t("Refresh coverage status") }}</button>
                        @if (current.status === 'queued' || current.status === 'running') {
                          <button [attr.lang]="uiLanguage()" type="button" (click)="cancelCoverage(source.id, current.id)" [disabled]="coverageBusy() !== null">{{ t("Cancel coverage request") }}</button>
                        }
                      } @else { <p [attr.lang]="uiLanguage()">{{ t("No indexed-version or sitemap request recorded for this source.") }}</p> }
                    }
                   @if (source.latest_import; as latest) {
                    <p [attr.lang]="uiLanguage()">{{ t("Latest file:") }} <span lang="en">{{ latest.status }}</span> (<span lang="en">{{ latest.coverage_state }}</span> {{ t("file coverage") }}), {{ latest.date_start }} {{ t("to") }} {{ latest.date_end }}, <span lang="en">{{ latest.export_shape }}</span> {{ t("export;") }} {{ latest.rows_imported }} {{ t("of") }} {{ latest.rows_seen }} {{ t("rows imported,") }} {{ latest.row_errors }} {{ t("errors.") }} {{ t("Provider export completeness:") }} <span lang="en">{{ latest.source_completeness }}</span>.</p>
                  } @else { <p [attr.lang]="uiLanguage()">{{ t("No completed CSV import recorded.") }}</p> }
                  @if (canManage() && source.provider === 'google_search_console' && source.csv_import_supported
                    && source.scope_current && source.state === 'active' && source.credential_status === 'not_connected') {
                    <form [attr.lang]="uiLanguage()" (submit)="uploadCsv($event, source.id)">
                      <fieldset [disabled]="csvBusy() || pendingCsv() !== null">
                        <legend>{{ t("Import one Search Console performance CSV for") }} {{ source.property }}</legend>
                        <p>{{ t("Choose one exported table, not a ZIP: queries, pages, countries, devices, dates or search appearance. Limit: 1 MiB, 1,000 rows and a 90-day range in Pacific Time. Export completeness and hidden rows remain unknown.") }}</p>
                        <label [for]="'csv-file-' + source.id">{{ t("CSV file") }}</label>
                        <input [id]="'csv-file-' + source.id" name="file" type="file" accept=".csv,text/csv" required />
                        <label [for]="'csv-start-' + source.id">{{ t("First exported date (Pacific Time)") }}</label>
                        <input [id]="'csv-start-' + source.id" name="start" type="date" required />
                        <label [for]="'csv-end-' + source.id">{{ t("Last exported date (Pacific Time)") }}</label>
                        <input [id]="'csv-end-' + source.id" name="end" type="date" required />
                        <label [for]="'csv-type-' + source.id">{{ t("Export search type") }}</label>
                        <select [id]="'csv-type-' + source.id" name="search_type">
                          <option value="web">{{ t("Web") }}</option><option value="image">{{ t("Image") }}</option><option value="video">{{ t("Video") }}</option>
                          <option value="news">{{ t("News") }}</option><option value="discover">{{ t("Discover") }}</option><option value="google_news">{{ t("Google News") }}</option>
                        </select>
                        <label [for]="'csv-grain-' + source.id">{{ t("Export date grain") }}</label>
                        <select [id]="'csv-grain-' + source.id" name="date_granularity">
                          <option value="range">{{ t("Aggregated range (queries, pages or other dimension)") }}</option>
                          <option value="day">{{ t("Daily Dates table") }}</option>
                        </select>
                        <label class="check-row"><input type="checkbox" name="authorize" required />
                          {{ t("I may use this export and confirm it belongs to this exact property and selected dates/type.") }}</label>
                        <button type="submit">{{ t("Import CSV") }}</button>
                      </fieldset>
                    </form>
                  }
                  @if (canManage() && source.csv_import_supported && source.credential_status === 'not_connected' && source.state !== 'unavailable') {
                    @if (source.state === 'active') {
                      <button [attr.lang]="uiLanguage()" type="button" class="secondary-button" [disabled]="changingSource() !== null" (click)="setCsvSource(source.id, false)">{{ t("Disable this CSV source") }}</button>
                    } @else if (source.scope_current) {
                      <button [attr.lang]="uiLanguage()" type="button" class="secondary-button" [disabled]="changingSource() !== null" (click)="setCsvSource(source.id, true)">{{ t("Re-enable this CSV source") }}</button>
                    }
                  }
                   @if (source.csv_import_supported) {
                    <button [attr.lang]="uiLanguage()" type="button" class="secondary-button" (click)="showImportHistory(source.id)">{{ t("View CSV import history") }}</button>
                    <button [attr.lang]="uiLanguage()" type="button" class="secondary-button" (click)="showQueries(source.id)">{{ t("Review queries for this property") }}</button>
                   }
                    }
                 </li>
              }
              @if (sourcesTruncated()) { <li>{{ t("Additional connections are not shown.") }}</li> }
            </ul>
          }
          @if (selectedImportSource()) {
            <section [attr.lang]="uiLanguage()" aria-labelledby="import-history-title">
              <h3 id="import-history-title">{{ t("CSV import history for selected property") }}</h3>
              @if (importHistoryLoading()) { <p role="status">{{ t("Loading CSV import history.") }}</p> }
              @else if (importHistoryError()) { <p role="alert">{{ t("Import history is unavailable; reload the project to retry.") }}</p> }
              @else if (importHistory().length === 0) { <p>{{ t("No completed CSV imports are recorded for this property.") }}</p> }
              @else {
                <ol>
                  @for (record of importHistory(); track record.id) {
                     <li>{{ record.created_at }} · <span lang="en">{{ record.export_shape }}</span> · <span lang="en">{{ record.status }}</span> (<span lang="en">{{ record.coverage_state }}</span> {{ t("file coverage") }}), {{ record.date_start }} {{ t("to") }} {{ record.date_end }}, {{ record.rows_imported }} {{ t("of") }} {{ record.rows_seen }} {{ t("rows,") }} {{ record.row_errors }} {{ t("errors.") }} {{ t("Provider export completeness:") }} <span lang="en">{{ record.source_completeness }}</span>.
                       @if (record.status === 'succeeded' && record.coverage_state === 'complete' && (record.export_shape === 'query' || record.export_shape === 'page')) {
                         <button type="button" (click)="loadOpportunityPreview(selectedImportSource()!, record.id)" [disabled]="opportunityLoading()">{{ t("Preview source-qualified candidates") }}</button>
                       }
                     </li>
                  }
                </ol>
                @if (importHistoryTruncated()) { <p>{{ t("Older CSV imports are not shown.") }}</p> }
                @if (canManage() && importHistory().length > 1) {
                  <form (submit)="recordQueryChanges($event, selectedImportSource()!)">
                    <p>{{ t("Compare two adjacent, complete query CSV windows from this property. Only rows observed in both windows can produce click, impression or worsened average-position candidates. Missing/hidden queries and provider coverage remain unknown; no action is approved.") }}</p>
                    <label for="query-previous-import">{{ t("Earlier query export") }}</label>
                    <select id="query-previous-import" name="previous" required>
                      <option value="">{{ t("Select earlier window") }}</option>
                      @for (record of importHistory(); track record.id) {
                        @if (record.export_shape === 'query' && record.status === 'succeeded' && record.coverage_state === 'complete') {
                          <option [value]="record.id">{{ record.date_start }} {{ t("to") }} {{ record.date_end }} · {{ t("import") }} {{ record.id }}</option>
                        }
                      }
                    </select>
                    <label for="query-current-import">{{ t("Later query export") }}</label>
                    <select id="query-current-import" name="current" required>
                      <option value="">{{ t("Select later window") }}</option>
                      @for (record of importHistory(); track record.id) {
                        @if (record.export_shape === 'query' && record.status === 'succeeded' && record.coverage_state === 'complete') {
                          <option [value]="record.id">{{ record.date_start }} {{ t("to") }} {{ record.date_end }} · {{ t("import") }} {{ record.id }}</option>
                        }
                      }
                    </select>
                    <button type="submit" [disabled]="findingsBusy() !== null">{{ t("Record comparable query change candidates") }}</button>
                  </form>
                  <form (submit)="recordQueryChanges($event, selectedImportSource()!, 'page')">
                    <p>{{ t("Compare two adjacent, complete page CSV windows. Only clean pages observed in both exports qualify; parameterized pages and absent rows are omitted, and no search-query intent is inferred.") }}</p>
                    <label for="page-previous-import">{{ t("Earlier page export") }}</label>
                    <select id="page-previous-import" name="previous" required>
                      <option value="">{{ t("Select earlier window") }}</option>
                      @for (record of importHistory(); track record.id) {
                        @if (record.export_shape === 'page' && record.status === 'succeeded' && record.coverage_state === 'complete') {
                          <option [value]="record.id">{{ record.date_start }} {{ t("to") }} {{ record.date_end }} · {{ t("import") }} {{ record.id }}</option>
                        }
                      }
                    </select>
                    <label for="page-current-import">{{ t("Later page export") }}</label>
                    <select id="page-current-import" name="current" required>
                      <option value="">{{ t("Select later window") }}</option>
                      @for (record of importHistory(); track record.id) {
                        @if (record.export_shape === 'page' && record.status === 'succeeded' && record.coverage_state === 'complete') {
                          <option [value]="record.id">{{ record.date_start }} {{ t("to") }} {{ record.date_end }} · {{ t("import") }} {{ record.id }}</option>
                        }
                      }
                    </select>
                    <button type="submit" [disabled]="findingsBusy() !== null">{{ t("Record comparable page change candidates") }}</button>
                  </form>
                }
              }
              <div [attr.lang]="uiLanguage()">
              @if (opportunityLoading()) { <p role="status">{{ t("Checking deterministic candidate signals for this import.") }}</p> }
              @else if (opportunityError()) { <p role="alert">{{ t("Candidate signals are unavailable; check this import's source and retry.") }}</p> }
              @else if (opportunityPreview(); as preview) {
                <section [attr.aria-label]="t('Source-qualified candidate preview')">
                  <h4>{{ t("Candidate preview") }} · <span lang="en">{{ preview.method }}</span></h4>
                  <p><span lang="en">{{ preview.property }} · {{ preview.dimension }}</span> · {{ preview.window.start }} {{ t("to") }} {{ preview.window.end }}
                    · <span lang="en">{{ preview.timezone }}</span> · {{ t("market") }} @if (preview.market) { <span lang="">{{ preview.market }}</span> } @else { {{ t("not set") }} }
                    · {{ t("languages") }} @if (preview.languages.length) { <span lang="en">{{ preview.languages.join(', ') }}</span> } @else { {{ t("not set") }} }.
                    {{ t("File coverage") }} <span lang="en">{{ preview.coverage.file }}</span>{{ t("; provider top rows") }} <span lang="en">{{ preview.coverage.provider_top_rows }}</span>;
                    {{ t("hidden queries") }} <span lang="en">{{ preview.coverage.hidden_queries }}</span>{{ t(". Missing rows are not zero.") }}
                    {{ t("Thresholds: position") }} {{ preview.thresholds.position_inclusive.join('–') }},
                    {{ t("impressions at least") }} {{ preview.thresholds.min_impressions }}, {{ t("CTR below") }} {{ preview.thresholds.ctr_below }}.
                    {{ t("These are candidate observations, not approved findings, proven intent conflicts or action recommendations.") }}</p>
                  @if (!preview.candidates.length) { <p>{{ t("No candidate met these rules in this export; provider coverage remains unknown.") }}</p> }
                  <ul>@for (candidate of preview.candidates; track candidate.detector + '-' + candidate.observation_id) {
                    <li><span lang="en">{{ candidate.detector }}</span> · <span lang="">{{ candidate.query || candidate.page }}</span> ·
                      {{ candidate.impressions }} {{ t("impressions,") }} {{ candidate.clicks }} {{ t("clicks,") }}
                      CTR {{ candidate.ctr }}, {{ t("average position") }} {{ candidate.position }};
                      {{ t("source row") }} {{ candidate.observation_id }} · <span lang="en">{{ candidate.confidence }}</span>.</li>
                  }</ul>
                  @if (preview.truncated_candidates) { <p>{{ t("Additional candidates are not shown.") }}</p> }
                  @if (canRecordOpportunityPreview()) {
                    <button type="button" (click)="recordOpportunityCandidates(selectedImportSource()!, preview.window.import_id)"
                      [disabled]="findingsBusy() !== null">{{ t("Record immutable candidate evidence for human review") }}</button>
                  }
                </section>
              }
              </div>
            </section>
          }
          @if (selectedSource(); as connectionId) {
            <section [attr.lang]="uiLanguage()" aria-labelledby="source-queries-title">
              <h3 id="source-queries-title">{{ t("Queries for selected property") }}</h3>
              <p>{{ t("Labels use the current project brand aliases (method") }} <span lang="en">{{ queryMethod() }}</span>{{ t(", alias revision") }} {{ aliasRevision() }}{{ t("). Unreported or anonymized queries are unknown; provider export completeness is unknown. Rows from other properties and export shapes are not joined.") }}</p>
              @if (queryLoading()) { <p role="status">{{ t("Loading query evidence.") }}</p> }
              @if (queryError()) { <p role="alert">{{ t("Query evidence is unavailable. Reload this source to retry.") }}</p> }
              @if (!queryLoading() && !queryError() && queries().length === 0) { <p>{{ t("No query-grained CSV observations have been imported for this property.") }}</p> }
              @if (queries().length) {
                <label for="source-query-label-filter">{{ t("Filter loaded rows by brand label") }}</label>
                <select id="source-query-label-filter" (change)="setQueryFilter($event)">
                  <option value="all">{{ t("All labels") }}</option>
                  <option value="branded">{{ t("Branded") }}</option>
                  <option value="non_branded">{{ t("Non-branded") }}</option>
                  <option value="unclassified">{{ t("Unclassified") }}</option>
                </select>
                <ul>
                  @for (item of visibleQueries(); track item.id) {
                    <li>
                      <strong lang="">{{ item.query }}</strong> · <span lang="en">{{ item.label }}</span> ({{ t("default") }} <span lang="en">{{ item.default_label }}</span>, {{ t("review revision") }} {{ item.review_revision }})
                      <span> · {{ item.date_start }} {{ t("to") }} {{ item.date_end }} · <span lang="en">{{ item.search_type }}</span> · {{ t("import") }} <span lang="en">{{ item.import_status }}</span></span>
                      <button type="button" class="secondary-button" (click)="showQueryHistory(connectionId, item.id)">{{ t("Review history") }}</button>
                      @if (historyQueryId() === item.id) {
                        @if (historyLoading()) { <p role="status">{{ t("Loading review history.") }}</p> }
                        @else if (historyError()) { <p role="alert">{{ t("Review history is unavailable.") }}</p> }
                        @else if (history().length === 0) { <p>{{ t("No human corrections recorded.") }}</p> }
                        @else {
                          <ol [attr.aria-label]="t('Recent review corrections')">
                            @for (review of history(); track review.revision) {
                              <li>{{ t("Revision") }} {{ review.revision }}: <span lang="en">{{ review.label }}</span> — <span lang="">{{ review.reason }}</span> ({{ review.created_at }})</li>
                            }
                          </ol>
                          @if (historyTruncated()) { <p>{{ t("Older corrections are not shown.") }}</p> }
                        }
                      }
                      @if (canReview()) {
                        <form (submit)="saveBrandReview($event, connectionId, item)">
                          <label [for]="'brand-label-' + item.id">{{ t("Correct label for") }} <span lang="">{{ item.query }}</span></label>
                          <select [id]="'brand-label-' + item.id" name="label" required>
                            <option value="branded" [selected]="item.label === 'branded'">{{ t("Branded") }}</option>
                            <option value="non_branded" [selected]="item.label === 'non_branded'">{{ t("Non-branded") }}</option>
                            <option value="unclassified" [selected]="item.label === 'unclassified'">{{ t("Unclassified") }}</option>
                          </select>
                          <label [for]="'brand-reason-' + item.id">{{ t("Review reason") }}</label>
                          <input [id]="'brand-reason-' + item.id" name="reason" required maxlength="240" />
                          <button type="submit" [disabled]="reviewing() !== null">{{ t("Save correction") }}</button>
                        </form>
                      }
                    </li>
                  }
                </ul>
                @if (nextBefore()) { <button type="button" class="secondary-button" [disabled]="queryLoading()" (click)="loadQueries(connectionId, nextBefore()!)">{{ t("Show older query observations") }}</button> }
              }
            </section>
          }
        </section>

        <section class="workspace-panel" [attr.lang]="uiLanguage()" aria-labelledby="findings-title">
          <h2 id="findings-title">{{ t("Source-backed findings and human opportunity reviews") }}</h2>
          <p>{{ t("Candidate evidence is not a prioritized opportunity, recommendation or approved change. All reviews remain project-scoped and reversible only through a new revision.") }}</p>
          <p><a [routerLink]="intentRoute()">{{ t("Review source-limited query intent and preferred pages") }}</a></p>
           <p>{{ t("Query-page cannibalization needs joint query/page observations; separate CSV exports cannot prove it. Content age needs a verified publication date; GA4 goal conversion context needs exact-origin attributed event evidence. These are unavailable, not zero or no issue.") }}</p>
          <button type="button" (click)="loadFindings()" [disabled]="findingsLoading() || findingsBusy() !== null">{{ t(findingsLoaded() ? 'Refresh finding evidence' : 'Load finding evidence') }}</button>
          @if (findingsLoading()) { <p role="status">{{ t("Checking project finding evidence.") }}</p> }
          @else if (findingsError()) { <p role="alert">{{ t("Finding evidence unavailable; refresh this project.") }}</p> }
          @else if (findingsLoaded()) {
            @if (!findings().length) { <p>{{ t("No candidate finding evidence has been recorded for this project.") }}</p> }
            @else {
              <ul [attr.aria-label]="t('Project source-backed findings')">
                @for (finding of findings(); track finding.id) {
                  <li><strong><span lang="en">{{ finding.detector }}</span> · <span lang="">{{ finding.subject }}</span></strong>
                    <p>{{ t("Detector") }} <span lang="en">{{ finding.method_version }}</span> · {{ t("observation") }} {{ finding.source_metric_id || t('not attached') }}
                      · {{ t("crawl evidence") }} {{ finding.source_indexation_id || t('not attached') }}
                      · {{ t("technical evidence") }} {{ finding.source_diagnostics_id || t('not attached') }}
                      · {{ t("performance evidence") }} {{ finding.source_performance_id || t('not attached') }}
                      · {{ t("import") }} {{ finding.source_import_id || t('not attached') }} · {{ t(finding.source_current ? 'source current' : 'historical source; review unavailable') }}
                      · <span lang="en">{{ finding.confidence }}</span> · {{ t("detected") }} {{ finding.detected_at }}{{ t(". This is observed candidate evidence, not proven business value.") }}</p>
                    <details><summary>{{ t("Source evidence, observed values and limits") }}</summary>
                      <pre lang="en" style="white-space: pre-wrap; overflow-wrap: anywhere">{{ finding.evidence | json }}</pre>
                    </details>
                    @if (finding.review; as review) {
                      <p>{{ t("Human review revision") }} {{ review.revision }}: <span lang="en">{{ review.priority }}</span> {{ t("priority,") }}
                        {{ t("effort") }} <span lang="en">{{ review.estimated_effort }}</span>, {{ t("business relevance") }} <span lang="en">{{ review.business_relevance }}</span>;
                        {{ t("reason:") }} <span lang="">{{ review.review_reason }}</span>{{ t(". No recommendation or change has been approved.") }}</p>
                    } @else { <p>{{ t("Not yet prioritized by a human reviewer.") }}</p> }
                    @if (canManage() && finding.source_current && (finding.source_metric_id || finding.source_indexation_id || finding.source_diagnostics_id || finding.source_performance_id)) {
                      <form (submit)="submitFindingReview($event, finding)">
                        <label [for]="'finding-priority-' + finding.id">{{ t("Priority for") }} <span lang="">{{ finding.subject }}</span></label>
                        <select [id]="'finding-priority-' + finding.id" name="priority">
                          <option value="unprioritized">{{ t("Not prioritized") }}</option><option value="low">{{ t("Low") }}</option>
                          <option value="medium">{{ t("Medium") }}</option><option value="high">{{ t("High") }}</option>
                        </select>
                        <label [for]="'finding-effort-' + finding.id">{{ t("Estimated effort") }}</label>
                        <select [id]="'finding-effort-' + finding.id" name="effort">
                          <option value="unknown">{{ t("Unknown") }}</option><option value="small">{{ t("Small") }}</option>
                          <option value="medium">{{ t("Medium") }}</option><option value="large">{{ t("Large") }}</option>
                        </select>
                        <label [for]="'finding-relevance-' + finding.id">{{ t("Business relevance") }}</label>
                        <select [id]="'finding-relevance-' + finding.id" name="relevance">
                          <option value="unknown">{{ t("Unknown") }}</option><option value="low">{{ t("Low") }}</option>
                          <option value="medium">{{ t("Medium") }}</option><option value="high">{{ t("High") }}</option>
                        </select>
                        <label [for]="'finding-reason-' + finding.id">{{ t("Review rationale") }}</label>
                        <input [id]="'finding-reason-' + finding.id" name="reason" maxlength="240" required />
                        <button type="submit" [disabled]="findingsBusy() !== null">{{ t("Save human review revision") }}</button>
                      </form>
                    }
                  </li>
                }
              </ul>
              @if (findingsTruncated()) { <p>{{ t("Only the 50 most recent finding records are shown.") }}</p> }
            }
          }
        </section>

        <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="indexation-title">
          <h2 id="indexation-title">{{ t("Crawl and search-engine indexation evidence") }}</h2>
          <p>{{ t("A sitemap or successful local fetch is not proof of Google indexing. Google inspection describes its indexed version, not a live-page test. Missing reports are unknown.") }}</p>
          <button type="button" (click)="loadIndexation()" [disabled]="indexationLoading() || indexationBuilding()">{{ t(indexationLoaded() ? 'Refresh indexation evidence' : 'Load indexation evidence') }}</button>
          @if (indexationLoading()) { <p role="status">{{ t("Checking project crawl and engine evidence.") }}</p> }
          @else if (indexationError()) { <p role="alert">{{ t("Indexation evidence is unavailable; retry for this project.") }}</p> }
          @else if (indexationLoaded()) {
            @if (!indexationCrawls().length) { <p>{{ t("No completed crawl is available for this project.") }}</p> }
            @else {
              <label for="indexation-crawl">{{ t("Completed crawl") }}</label>
              <select id="indexation-crawl" (change)="selectIndexationCrawl($event)">
                @for (crawl of indexationCrawls(); track crawl.id) {
                  <option [value]="crawl.id" [selected]="crawl.id === indexationCrawlId()">{{ t("Crawl") }} {{ crawl.id }} · {{ crawl.completed_at }}</option>
                }
              </select>
              @if (indexationCrawlsTruncated()) { <p>{{ t("Only the 20 most recent completed crawls are listed.") }}</p> }
              @if (canManage() && !indexationReport()) {
                <button type="button" (click)="buildIndexation()" [disabled]="indexationBuilding()">{{ t("Build no-fetch evidence for this crawl") }}</button>
              }
              @if (indexationBuilding()) { <p role="status">{{ t("Recording immutable crawl observations without fetching pages.") }}</p> }
              @if (indexationReport(); as report) {
                <p>{{ t("Local coverage") }} <span lang="en">{{ report.coverage.state }}</span>; {{ t("engine reports") }} <span lang="en">{{ report.coverage.engine_indexing_reports }}</span>{{ t(". No missing URL implies zero or indexed.") }}</p>
                @if (canManage()) {
                  <button type="button" (click)="recordIndexationCandidates(report.crawl_run_id)" [disabled]="findingsBusy() !== null">{{ t("Record scoped indexation review candidates") }}</button>
                  <button type="button" (click)="recordTechnicalCandidates(report.diagnostics_id)" [disabled]="findingsBusy() !== null">{{ t("Record observed technical review candidates") }}</button>
                }
                <ul [attr.aria-label]="t('Per-URL crawl and indexation evidence')">
                  @for (entry of report.urls; track entry.url) {
                    <li><strong><span lang="en">{{ entry.url }}</span></strong> · {{ t("discovered by") }} <span lang="en">{{ entry.discovered_by.join(', ') }}</span>;
                      {{ t("local crawl") }} <span lang="en">{{ entry.crawlability }}</span>.
                      @for (visit of entry.fetch_observations; track $index) {
                        <p>{{ t("Observed HTTP") }} {{ visit.status_code ?? t('unknown') }}; {{ t("directive") }} <span lang="en">{{ visit.directive_state }}</span>;
                          {{ t("declared canonical") }} @if (visit.declared_canonical) { <span lang="en">{{ visit.declared_canonical }}</span> } @else { {{ t('unknown') }} }.</p>
                      }
                      @if (entry.indexability_signals.length) { <p>{{ t("Local candidates:") }} <span lang="en">{{ entry.indexability_signals.join(', ') }}</span>.</p> }
                      @if (!entry.engine_reports.length) { <p>{{ t("Search-engine indexed status unknown; no currently authorized exact-URL inspection report.") }}</p> }
                      @for (engine of entry.engine_reports; track engine.property) {
                        <p><span lang="en">{{ engine.provider }}</span> · <span lang="en">{{ engine.property }}</span>: <span lang="en">{{ engine.indexed_state }}</span> {{ t("on Google's indexed version;") }}
                          {{ t("collected") }} {{ engine.collected_at }}; {{ t("last Google crawl") }} {{ engine.engine_last_crawl_at || t('unknown') }};
                          {{ t(engine.stale_relative_to_local_crawl === null ? 'recency unknown' : engine.stale_relative_to_local_crawl ? 'older than local crawl' : 'not older than local crawl') }};
                          {{ t("Google-reported declared canonical") }} @if (engine.declared_canonical) { <span lang="en">{{ engine.declared_canonical }}</span> } @else { {{ t('unknown or outside scope') }} };
                          {{ t("Google-selected canonical") }} @if (engine.engine_selected_canonical) { <span lang="en">{{ engine.engine_selected_canonical }}</span> } @else { {{ t('unknown or outside scope') }} }.
                          @if (engine.disagreement_candidates.length) { {{ t("Review candidates:") }} <span lang="en">{{ engine.disagreement_candidates.join(', ') }}</span>. }
                        </p>
                      }
                    </li>
                  }
                </ul>
              } @else { <p>{{ t("No immutable crawl evidence has been built for the selected run.") }}</p> }
            }
          }
        </section>

        <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="performance-title">
          <h2 id="performance-title">{{ t("Page speed and real-user performance") }}</h2>
          <p>{{ t("Lighthouse is a lab run, not real-user field data. CrUX current and history use field p75 and may be unavailable for low traffic. Missing data never means passing.") }}</p>
          <button type="button" (click)="loadPerformance()" [disabled]="performanceLoading() || performanceBusy()">{{ t(performanceLoaded() ? 'Refresh performance history' : 'Load performance history') }}</button>
          @if (performanceLoading()) { <p role="status">{{ t("Checking project performance audits.") }}</p> }
          @else if (performanceError()) { <p role="alert">{{ t("Performance history is unavailable; refresh this project.") }}</p> }
          @else if (performanceLoaded()) {
            @if (!performanceKeyAvailable()) { <p>{{ t("A project-eligible Google performance key is not configured. An organization owner/admin or platform operator can set one in private provider settings.") }}</p> }
            @if (canReview() && performanceKeyAvailable()) {
              <form (submit)="startPerformance($event)">
                <label for="performance-target">{{ t("One exact project URL or origin") }}</label>
                <input id="performance-target" name="target" type="url" maxlength="2048" [value]="configuration()!.canonical_origin" required />
                <label for="performance-grain">{{ t("Source grain") }}</label>
                <select id="performance-grain" name="grain"><option value="page">{{ t("Page") }}</option><option value="origin">{{ t("Origin (CrUX only)") }}</option></select>
                <label for="performance-strategy">{{ t("Device") }}</label>
                <select id="performance-strategy" name="strategy"><option value="mobile">{{ t("Mobile") }}</option><option value="desktop">{{ t("Desktop") }}</option><option value="tablet">{{ t("Tablet (CrUX only)") }}</option></select>
                <fieldset><legend>{{ t("Independent sources (one unit each, at most three)") }}</legend>
                  <label class="check-row"><input type="checkbox" name="source" value="psi_lab" /> {{ t("Lighthouse lab") }}</label>
                  <label class="check-row"><input type="checkbox" name="source" value="crux_current" /> {{ t("CrUX current field") }}</label>
                  <label class="check-row"><input type="checkbox" name="source" value="crux_history" /> {{ t("CrUX field history") }}</label>
                </fieldset>
                <p>{{ t("One to three attempted internal units; provider quotas and trial limits can stop a partial job. No result is guaranteed.") }}</p>
                <button type="submit" [disabled]="performanceBusy()">{{ t("Request bounded performance audit") }}</button>
              </form>
            }
            @if (!performanceJobs().length) { <p>{{ t("No performance audit has been requested for this project.") }}</p> }
            @else {
              <ul [attr.aria-label]="t('Recent project performance audits')">
                @for (job of performanceJobs(); track job.id) {
                  <li>{{ t("Audit") }} {{ job.id }} · <span lang="en">{{ job.status }}</span> · <span lang="en">{{ job.grain }}</span> <span lang="en">{{ job.strategy }}</span> · <span lang="en">{{ job.target }}</span>;
                    {{ t("attempted") }} {{ job.requests_attempted }} {{ t("of") }} {{ job.sources.length }}; {{ t("lab") }} <span lang="en">{{ job.lab }}</span>, {{ t("field") }} <span lang="en">{{ job.field }}</span>.
                    @if (job.error_category) { {{ t("Reason:") }} <span lang="en">{{ job.error_category }}</span>. }
                    <button type="button" (click)="showPerformance(job.id)" [disabled]="performanceBusy()">{{ t("Inspect parsed evidence") }}</button>
                  </li>
                }
              </ul>
              @if (performanceHasMore()) { <p>{{ t("Only the 20 most recent audits are listed.") }}</p> }
            }
            @if (performanceDetailError()) { <p role="alert">{{ t("Selected audit detail is unavailable; retry from this project.") }}</p> }
            @if (performanceSelected(); as selected) {
              <h3>{{ t("Audit") }} {{ selected.id }} · <span lang="en">{{ selected.status }}</span> · <span lang="en">{{ selected.coverage }}</span></h3>
              @if (selected.status === 'queued' || selected.status === 'running') {
                @if (canReview()) { <button type="button" (click)="cancelPerformance(selected.id)" [disabled]="performanceBusy()">{{ t("Cancel audit") }}</button> }
              }
              @if (!performanceObservations().length) { <p>{{ t("No parsed lab or field observation is available yet; unavailable is not a passing grade.") }}</p> }
              @for (observation of performanceObservations(); track observation.source) {
                <section>
                  @if (canManage()) { <button type="button" (click)="recordPerformanceCandidates(observation.id)" [disabled]="findingsBusy() !== null">{{ t("Record parsed performance review candidates") }}</button> }
                  @if (observation.source === 'psi_lab') {
                    <h4>{{ t("Lighthouse lab") }} · <span lang="en">{{ selected.strategy }}</span> · {{ observation.collected_at }}</h4>
                    <p>{{ t("Lab performance score") }} {{ performanceLabScore(observation.result) === 'unavailable' ? t('unavailable') : performanceLabScore(observation.result) }} {{ t("(0–1, not a field p75). Status") }} <span lang="en">{{ performanceText(observation.result, 'status') }}</span>.</p>
                    <ul>@for (audit of performanceLabAudits(observation.result); track audit.name) {
                      <li><span lang="en">{{ audit.name }}</span>: {{ audit.value ?? t('unavailable') }} <span lang="en">{{ audit.unit }}</span> · <span lang="en">{{ audit.state }}</span></li>
                    }</ul>
                  } @else {
                    <h4>{{ t("CrUX") }} {{ t(observation.source === 'crux_history' ? 'history' : 'current') }} {{ t("field p75") }} · <span lang="en">{{ selected.strategy }}</span> · {{ observation.collected_at }}</h4>
                    <p>{{ t("Requested") }} <span lang="en">{{ performanceText(observation.result, 'requested_grain') }}</span>;
                      {{ t("observed") }} <span lang="en">{{ performanceText(observation.result, 'observed_grain') }}</span>;
                      {{ t(observation.result['origin_fallback'] === true ? 'origin fallback (not page data)' : 'no origin fallback') }}.
                      {{ t("History windows may overlap; a threshold change is not causal proof.") }}</p>
                    <ul>@for (metric of performanceFieldMetrics(observation.result); track $index) {
                      <li><span lang="en">{{ metric.name }}</span> <span lang="en">{{ metric.period }}</span>: p75 {{ metric.p75 ?? t('unavailable') }} <span lang="en">{{ metric.unit }}</span>
                        · <span lang="en">{{ metric.grade }}</span> · <span lang="en">{{ metric.state }}</span></li>
                    }</ul>
                    @if (observation.source === 'crux_history') {
                      <p>{{ t("These historical parsed values alone do not establish original raw integrity or actual period comparability. Inspect the original source below.") }}</p>
                      <app-project-crux-history [organizationId]="organizationId" [projectId]="projectId"
                        [job]="selected" [observation]="observation" [revision]="performanceInspectionRevision()" [language]="uiLanguage()" />
                    }
                  }
                </section>
              }
            }
          }
        </section>

        @if (canManage()) {
          <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="google-consent-title">
            <h2 id="google-consent-title">{{ t("Google Search Console authorization") }}</h2>
             <p>{{ t("Consent requires an administrator and a configured Google client. Choose an exact website property after returning from Google. A finalized daily sync can then be started from the source above.") }}</p>
            <button type="button" [disabled]="connectingGoogle()" (click)="connectGoogle()">{{ t("Authorize Google Search Console") }}</button>
            @if (connectingGoogle()) { <p role="status">{{ t("Starting Google authorization.") }}</p> }
            @if (grantLoading()) { <p role="status">{{ t("Loading Google authorization status.") }}</p> }
            @else if (grantError()) { <p role="alert">{{ t("Google authorization status is unavailable; reload this project to retry.") }}</p> }
            @else if (!grants().length) { <p>{{ t("No Google authorizations recorded for this project.") }}</p> }
            @else {
              <ul [attr.aria-label]="t('Google authorization records')">
                @for (grant of grants(); track grant.id) {
                  <li>
                    <strong>{{ t("Authorization") }} {{ grant.id }}</strong> · <span lang="en">{{ grant.state }}</span> · {{ t("verified") }} {{ grant.verified_at }}
                    @if (grant.state === 'pending_selection') {
                      <p>{{ t("Choose a website property while this authorization is current. Property selection expires after ten minutes.") }}</p>
                      @for (site of grant.sites; track site.site_url) {
                        @if (site.scope === 'verified_domain_page_only') {
                          <p>{{ t("Domain property") }} <span lang="en">{{ site.property }}</span> {{ t("includes other subdomains/protocols at Google.") }}
                            {{ t("Only page rows for verified project origins") }} <span lang="en">{{ site.approved_origins?.join(', ') }}</span>
                            {{ t("can be used here. Domain-wide totals and query/date reports stay unavailable.") }}</p>
                        }
                        <button type="button" class="secondary-button" [disabled]="busyGrant() !== null" (click)="selectGoogleProperty(grant, site.site_url)">{{ t("Use") }} <span lang="en">{{ site.property }}</span> {{ t("via Google") }}</button>
                      }
                      @if (!grant.sites.length) { <p>{{ t("No property is within the project's current scope. Reauthorize if its scope changed.") }}</p> }
                    } @else if (grant.state === 'active') {
                       <p>{{ t("Property authorization recorded. Sync history is shown on its source record above.") }}</p>
                    } @else if (grant.state === 'revocation_pending') {
                      <p>{{ t("Local access is disabled. Google revocation has not been confirmed; retry revocation.") }}</p>
                    } @else if (grant.state === 'reconnect_required') {
                      <p>{{ t("Authorization needs fresh consent. No API work is available.") }}</p>
                    } @else { <p>{{ t("Authorization revoked. Local credentials have been erased.") }}</p> }
                    @if (grant.state !== 'revoked') {
                      <button type="button" class="secondary-button" [disabled]="busyGrant() !== null" (click)="revokeGoogle(grant)">{{ t("Revoke Google authorization") }} {{ grant.id }}</button>
                    }
                  </li>
                }
              </ul>
              @if (grantsTruncated()) { <p>{{ t("Additional older authorizations are not shown.") }}</p> }
            }
          </section>
          <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="analytics-consent-title">
            <h2 id="analytics-consent-title">{{ t("Google Analytics authorization") }}</h2>
            <p>{{ t("Analytics requires separate read-only Google consent and an operator-configured Analytics application. A configured web stream is not proof of collection or conversion instrumentation. No GA4 sync is available yet.") }}</p>
            <button type="button" (click)="connectGA4()" [disabled]="ga4Busy() !== null">{{ t("Authorize Google Analytics") }}</button>
            <button type="button" class="secondary-button" (click)="loadGA4Grants()" [disabled]="ga4Loading()">{{ t("Refresh Analytics grants") }}</button>
            @if (ga4Loading()) { <p role="status">{{ t("Loading Analytics consent status.") }}</p> }
            @else if (ga4Error()) { <p role="alert">{{ t("Analytics consent status is unavailable; refresh before retrying.") }}</p> }
            @else if (!ga4Grants().length) { <p>{{ t("No Analytics grant recorded. No sessions, key events or revenue are available.") }}</p> }
            @else {
              <ul [attr.aria-label]="t('Analytics consent grants')">
                @for (grant of ga4Grants(); track grant.id) {
                  <li>
                    <strong>{{ t("Analytics consent") }} {{ grant.id }}</strong> · <span lang="en">{{ grant.state }}</span> · {{ grant.verified_at }}.
                    @if (grant.state === 'pending_selection' && !grant.property_id) {
                      <form (submit)="selectGA4($event, grant)">
                        <label [for]="'ga4-property-' + grant.id">{{ t("Google Analytics numeric property ID") }}</label>
                        <input [id]="'ga4-property-' + grant.id" name="property_id" inputmode="numeric" pattern="[1-9][0-9]{0,19}" maxlength="20" required />
                        <label [for]="'ga4-origin-' + grant.id">{{ t("One configured HTTPS web origin") }}</label>
                        <select [id]="'ga4-origin-' + grant.id" name="origin" required>
                          <option value="">{{ t("Choose a current project origin") }}</option>
                          @for (origin of ga4Origins(); track origin) { <option lang="en" [value]="origin">{{ origin }}</option> }
                        </select>
                        <button type="submit" [disabled]="ga4Busy() !== null">{{ t("Check scoped web stream and reporting columns") }}</button>
                      </form>
                    } @else if (grant.state === 'pending_selection') {
                      <p>{{ t("Selected property") }} <span lang="en">{{ grant.property_id }} · {{ grant.selected_origins.join(', ') }}</span>.
                        {{ t("The grant is disabled until a scoped source is linked.") }}</p>
                      <button type="button" [disabled]="ga4Busy() !== null || !grant.scope_current" (click)="linkGA4(grant)">{{ t("Link this configured Analytics source") }}</button>
                    } @else if (grant.state === 'active') {
                       <p>{{ t("Property") }} <span lang="en">{{ grant.property_id }} · {{ grant.selected_origins.join(', ') }}</span>. {{ t("A source reference is configured for manual measurement review; exact-origin Analytics reports and conversion instrumentation remain unavailable.") }}</p>
                    } @else if (grant.state === 'revocation_pending') {
                      <p>{{ t("Local access is disabled. Google remote revocation is pending; retry it.") }}</p>
                    } @else { <p>{{ t("Grant revoked; no Analytics data is available.") }}</p> }
                    @if (grant.state !== 'revoked') {
                      @if (confirmGA4Revoke() === grant.id) {
                        <p role="alert">{{ t("Disconnect this Analytics grant now? Remote revocation may need retry.") }}</p>
                        <button type="button" [disabled]="ga4Busy() !== null" (click)="revokeGA4(grant)">{{ t("Confirm Analytics disconnect") }}</button>
                        <button type="button" [disabled]="ga4Busy() !== null" (click)="confirmGA4Revoke.set(null)">{{ t("Cancel") }}</button>
                      } @else {
                        <button type="button" class="secondary-button" [disabled]="ga4Busy() !== null" (click)="confirmGA4Revoke.set(grant.id)">{{ t("Disconnect Analytics grant") }} {{ grant.id }}</button>
                      }
                    }
                  </li>
                }
              </ul>
              @if (ga4Truncated()) { <p>{{ t("Older Analytics grants are not shown.") }}</p> }
            }
          </section>
        }

        <div [attr.lang]="uiLanguage()">
        <ol class="onboarding-steps" [attr.aria-label]="t('Onboarding steps')">
          <li><button type="button" [attr.aria-current]="view() === 'basics' ? 'step' : null" (click)="show('basics')">{{ t("1 Website and goals") }}</button></li>
          <li><button type="button" [attr.aria-current]="view() === 'source' ? 'step' : null" (click)="show('source')">{{ t("2 Data source") }}</button></li>
          <li><button type="button" [attr.aria-current]="view() === 'advanced' ? 'step' : null" (click)="show('advanced')">{{ t("3 Advanced settings") }}</button></li>
          @if (configuration()!.current_step === 'complete') {
            <li><button type="button" [attr.aria-current]="view() === 'complete' ? 'step' : null" (click)="show('complete')">{{ t("4 Complete") }}</button></li>
          }
        </ol>

        @if (!canManage()) {
          <section class="workspace-panel" aria-labelledby="read-only-title">
            <h2 id="read-only-title">{{ t("Read-only configuration") }}</h2>
            <p>{{ t("An organization owner or admin can change project setup. Your project access is unchanged.") }}</p>
            <div class="read-only-summary">
              <span><strong>{{ t("Country:") }}</strong> {{ configuration()!.target_country || t('Not set') }}</span>
              <span><strong>{{ t("Languages:") }}</strong> {{ configuration()!.target_languages.join(', ') || t('Not set') }}</span>
              <span><strong>{{ t("Goal:") }}</strong> {{ configuration()!.business_goal || t('Not set') }}</span>
              <span><strong>{{ t("Source preference:") }}</strong> {{ t(sourceLabel(configuration()!.source_state)) }}</span>
              <span><strong>{{ t("Manual measurement notes (unverified):") }}</strong> {{ configuration()!.measurement_notes || t('None recorded') }}</span>
            </div>
          </section>
        } @else if (view() === 'basics') {
          <section class="workspace-panel" aria-labelledby="basics-title">
            <h2 #stepHeading id="basics-title" tabindex="-1">{{ t("Website and primary goal") }}</h2>
            <p>{{ t("The canonical website is reviewed here and remains editable from project settings. Project languages describe SEO work; they do not change the OrganicSEOOps interface language.") }}</p>
            <p><strong>{{ t("Canonical website:") }}</strong> {{ configuration()!.canonical_origin }}</p>
            <form (submit)="saveBasics($event)" [attr.aria-busy]="saving()">
              <label for="target-country">{{ t("Primary target country or market") }}</label>
              <input id="target-country" name="target-country" required maxlength="80" [value]="configuration()!.target_country" autocomplete="country-name" />
              <label for="target-languages">{{ t("Target language tags") }} <span class="field-help">{{ t("One per line, such as en, tr, or en-US") }}</span></label>
              <textarea id="target-languages" name="target-languages" required rows="3" [value]="configuration()!.target_languages.join('\n')"></textarea>
              <label for="business-goal">{{ t("Primary business goal") }}</label>
              <textarea id="business-goal" name="business-goal" required maxlength="240" rows="3" [value]="configuration()!.business_goal"></textarea>
              <label for="project-timezone">{{ t("Reporting timezone") }}</label>
              <input id="project-timezone" name="timezone" required maxlength="64" [value]="configuration()!.timezone" aria-describedby="timezone-help" />
              <p id="timezone-help" class="field-help">{{ t("Use an IANA timezone such as UTC or Europe/Istanbul.") }}</p>
              <button type="submit" [disabled]="saving()">{{ t("Save and continue to data source") }}</button>
            </form>
          </section>
        } @else if (view() === 'source') {
          <section class="workspace-panel" aria-labelledby="source-title">
            <h2 #stepHeading id="source-title" tabindex="-1">{{ t("Choose a data-source path") }}</h2>
             <p>{{ t("Saving a choice does not connect an account or start a job. Set up and upload a CSV in source status above. Google consent and bounded daily sync require a configured client and exact property authorization.") }}</p>
            <form (submit)="saveSource($event)" [attr.aria-busy]="saving()">
              <fieldset>
                <legend>{{ t("Source choice") }}</legend>
                <label class="check-row"><input type="radio" name="source" value="connect_search_console" required [checked]="configuration()!.source_choice === 'connect_search_console'" /> {{ t("Connect Search Console later") }}</label>
                <label class="check-row"><input type="radio" name="source" value="import_search_console" [checked]="configuration()!.source_choice === 'import_search_console'" /> {{ t("Import a Search Console CSV") }}</label>
                <label class="check-row"><input type="radio" name="source" value="skip" [checked]="configuration()!.source_choice === 'skip'" /> {{ t("Skip for now and keep setup recoverable") }}</label>
                <label class="check-row"><input type="radio" name="source" value="synthetic_demo" [checked]="configuration()!.source_choice === 'synthetic_demo'" /> {{ t("Use the isolated synthetic setup preview") }}</label>
              </fieldset>
              <div class="onboarding-actions">
                <button type="button" class="secondary-button" (click)="show('basics')">{{ t("Back to website and goals") }}</button>
                <button type="submit" [disabled]="saving()">{{ t("Save and continue to advanced settings") }}</button>
              </div>
            </form>
            @if (configuration()!.source_choice === 'synthetic_demo') { <ng-container [ngTemplateOutlet]="demo" /> }
          </section>
        } @else if (view() === 'advanced') {
          <section class="workspace-panel" aria-labelledby="advanced-title">
            <h2 #stepHeading id="advanced-title" tabindex="-1">{{ t("Optional advanced project settings") }}</h2>
            <p>{{ t("These editable inputs improve later evidence and defaults. They do not activate providers, schedules, commercial allowances, crawling, or publishing.") }}</p>
            <form (submit)="saveAdvanced($event)" [attr.aria-busy]="saving()">
              <label for="audience">{{ t("Ideal audience") }}</label><textarea id="audience" name="audience" maxlength="2000" [value]="configuration()!.audience"></textarea>
              <label for="offer">{{ t("Products or services") }}</label><textarea id="offer" name="offer" maxlength="2000" [value]="configuration()!.offer"></textarea>
              <label for="brand-voice">{{ t("Brand voice") }}</label><textarea id="brand-voice" name="brand-voice" maxlength="2000" [value]="configuration()!.brand_voice"></textarea>
              <label for="seed-topics">{{ t("Seed topics") }} <span class="field-help">{{ t("One per line") }}</span></label><textarea id="seed-topics" name="seed-topics" [value]="lines(configuration()!.seed_topics)"></textarea>
              <label for="prohibited-claims">{{ t("Prohibited topics or claims") }} <span class="field-help">{{ t("One per line") }}</span></label><textarea id="prohibited-claims" name="prohibited-claims" [value]="lines(configuration()!.prohibited_claims)"></textarea>
              <label for="conversion-goals">{{ t("Conversion goals") }} <span class="field-help">{{ t("One per line") }}</span></label><textarea id="conversion-goals" name="conversion-goals" [value]="lines(configuration()!.conversion_goals)"></textarea>
              <label for="brand-aliases">{{ t("Brand names and aliases") }} <span class="field-help">{{ t("One per line") }}</span></label><textarea id="brand-aliases" name="brand-aliases" [value]="lines(configuration()!.brand_aliases)"></textarea>
              <label for="measurement-notes">{{ t("Manual measurement-quality notes") }} <span class="field-help">{{ t("Optional: note conversion definitions, consent gaps or tracking changes. Notes are unverified, not GA4 data.") }}</span></label><textarea id="measurement-notes" name="measurement-notes" maxlength="2000" [value]="configuration()!.measurement_notes"></textarea>
              <label for="competitors">{{ t("Competitor origins") }} <span class="field-help">{{ t("One HTTP or HTTPS origin per line") }}</span></label><textarea id="competitors" name="competitors" [value]="lines(configuration()!.competitor_origins)"></textarea>
              <label for="research-allowed">{{ t("Allowed research origins") }} <span class="field-help">{{ t("One origin per line") }}</span></label><textarea id="research-allowed" name="research-allowed" [value]="lines(configuration()!.research_allowed_origins)"></textarea>
              <label for="rss-feeds">{{ t("RSS or Atom feed URLs") }} <span class="field-help">{{ t("Optional, up to five HTTPS URLs, one per line, each on an explicitly allowed research origin; no URL queries/credentials. Saving does not fetch a feed.") }}</span></label><textarea id="rss-feeds" name="rss-feeds" [value]="lines(configuration()!.rss_feed_urls)"></textarea>
              <label for="research-blocked">{{ t("Blocked research origins") }} <span class="field-help">{{ t("One origin per line") }}</span></label><textarea id="research-blocked" name="research-blocked" [value]="lines(configuration()!.research_blocked_origins)"></textarea>
              <label for="crawl-page-limit">{{ t("Preferred crawl page ceiling") }}</label><input id="crawl-page-limit" name="crawl-page-limit" type="number" min="1" max="100000" [value]="configuration()!.crawl_page_limit ?? ''" />
              <p class="field-help">{{ t("This is saved configuration, not an active crawl or commercial allowance.") }}</p>
              <label for="ignored-query-parameters">{{ t("Ignored tracking parameters") }} <span class="field-help">{{ t("Exact case-sensitive names, one per line") }}</span></label><textarea id="ignored-query-parameters" name="ignored-query-parameters" [value]="lines(configuration()!.ignored_query_parameters)"></textarea>
              <label for="pagination-query-parameters">{{ t("Pagination parameters") }} <span class="field-help">{{ t("Exact case-sensitive names, one per line") }}</span></label><textarea id="pagination-query-parameters" name="pagination-query-parameters" [value]="lines(configuration()!.pagination_query_parameters)"></textarea>
              <label for="facet-query-parameters">{{ t("Facet parameters") }} <span class="field-help">{{ t("Exact case-sensitive names, one per line") }}</span></label><textarea id="facet-query-parameters" name="facet-query-parameters" [value]="lines(configuration()!.facet_query_parameters)"></textarea>
              <label for="query-variant-limit">{{ t("Parameterized variants per path") }}</label><input id="query-variant-limit" name="query-variant-limit" type="number" min="1" max="25" required [value]="configuration()!.query_variant_limit" />
              <p class="field-help">{{ t("Ignored names deduplicate tracking-only URLs. Pagination, facet, and unlisted parameters keep their values within this safety cap.") }}</p>
              <label for="business-locations">{{ t("Real business locations") }} <span class="field-help">{{ t("One reviewed location per line") }}</span></label><textarea id="business-locations" name="business-locations" [value]="lines(configuration()!.business_locations)"></textarea>
              <label for="service-areas">{{ t("Actual service areas") }} <span class="field-help">{{ t("One per line") }}</span></label><textarea id="service-areas" name="service-areas" [value]="lines(configuration()!.service_areas)"></textarea>
              <label for="contact-details">{{ t("Contact details") }}</label><textarea id="contact-details" name="contact-details" maxlength="2000" [value]="configuration()!.contact_details"></textarea>
              <label for="business-hours">{{ t("Business hours") }}</label><textarea id="business-hours" name="business-hours" maxlength="2000" [value]="configuration()!.business_hours"></textarea>
              <label for="profile-urls">{{ t("Business profile links") }} <span class="field-help">{{ t("One public HTTP or HTTPS URL per line") }}</span></label><textarea id="profile-urls" name="profile-urls" [value]="lines(configuration()!.profile_urls)"></textarea>
               <label for="eligibility-notes">{{ t("Profile and local eligibility notes") }}</label><textarea id="eligibility-notes" name="eligibility-notes" maxlength="2000" [value]="configuration()!.local_eligibility_notes"></textarea>
               <p><a [routerLink]="localRoute()">{{ t("After saving these facts, review local business and profile evidence manually") }}</a>{{ t(". Profile eligibility and third-party reviews remain unverified.") }}</p>
              <div class="onboarding-actions">
                <button type="button" class="secondary-button" (click)="show('source')">{{ t("Back to data source") }}</button>
                <button type="submit" [disabled]="saving()">{{ t("Save and finish setup") }}</button>
              </div>
            </form>
          </section>
        } @else {
          <section class="workspace-panel" aria-labelledby="complete-title">
            <h2 #stepHeading id="complete-title" tabindex="-1">{{ t("Project setup saved") }}</h2>
            <p>{{ t("Your setup is resumable and remains editable. No import, provider connection, crawl, job, trial, or billing operation was started.") }}</p>
            <p><strong>{{ t("Country:") }}</strong> {{ configuration()!.target_country }}</p>
            <p><strong>{{ t("Languages:") }}</strong> {{ configuration()!.target_languages.join(', ') }}</p>
            <p><strong>{{ t("Goal:") }}</strong> {{ configuration()!.business_goal }}</p>
            <p><strong>{{ t("Source preference:") }}</strong> {{ t(sourceLabel(configuration()!.source_state)) }}</p>
            <p><strong>{{ t("Manual measurement notes (unverified):") }}</strong> {{ configuration()!.measurement_notes || t('None recorded') }}</p>
            @if (configuration()!.source_choice === 'synthetic_demo') { <ng-container [ngTemplateOutlet]="demo" /> }
            <div class="onboarding-actions">
              <button type="button" class="secondary-button" (click)="show('basics')">{{ t("Edit website and goals") }}</button>
              <button type="button" class="secondary-button" (click)="show('source')">{{ t("Edit source choice") }}</button>
              <button type="button" class="secondary-button" (click)="show('advanced')">{{ t("Edit advanced settings") }}</button>
            </div>
          </section>
        }

        <ng-template #demo>
          <aside [attr.lang]="uiLanguage()" class="demo-panel" [attr.aria-label]="t('Synthetic demo setup preview')">
            <strong>{{ t("Synthetic demo") }}</strong>
            <p>{{ t("This static preview is not project evidence. It creates no live metric, finding, job, artifact, export, usage, or billing record.") }}</p>
            <span>{{ t("Example source: labeled sample data · Example scope: 12 sample pages · Live data status: not connected") }}</span>
          </aside>
        </ng-template>
        </div>
      }
    </section>
  `,
})
export class ProjectOnboarding implements OnInit, OnDestroy {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  @ViewChild('errorSummary') private errorSummary?: ElementRef<HTMLElement>;
  @ViewChild('stepHeading') set activeStepHeading(element: ElementRef<HTMLElement> | undefined) {
    this.stepHeading = element;
    if (element && this.focusStep) {
      this.focusStep = false;
      element.nativeElement.focus();
    }
  }
  readonly project = signal<ProjectInfo | null>(null);
  readonly configuration = signal<ProjectConfigurationInfo | null>(null);
  readonly view = signal<OnboardingStep>('basics');
  readonly loading = signal(true);
  readonly saving = signal(false);
  readonly denied = signal(false);
  readonly message = signal('');
  readonly csvAcknowledgment = signal<{ id: number; status: string; message: string } | null>(null);
  private readonly messageDraft = signal<{ message: string; translation: string } | null>(null);
  readonly error = signal('');
  readonly sources = signal<ProjectSourceInfo[]>([]);
  readonly sourceLoading = signal(false);
  readonly sourceError = signal(false);
  readonly sourcesTruncated = signal(false);
  readonly changingSource = signal<number | null>(null);
  readonly csvBusy = signal(false);
  readonly pendingCsv = signal<{ connectionId: number; file: Blob; checksum: string; headers: Record<string, string> } | null>(null);
  readonly syncBusy = signal<number | null>(null);
  readonly syncSourceId = signal<number | null>(null);
  readonly syncLoading = signal(false);
  readonly syncError = signal(false);
  readonly syncJob = signal<{id: number; status: string; error_category: string; pages_recorded: number;
    requests_attempted: number; source_coverage: string} | null>(null);
  private pendingSync = { input: '', key: '' };
  readonly backfillBusy = signal<number | null>(null);
  readonly backfillSourceId = signal<number | null>(null);
  readonly backfillLoading = signal(false);
  readonly backfillError = signal(false);
  readonly backfillJob = signal<BackfillJob | null>(null);
  private pendingBackfill = { input: '', key: '' };
  private backfillRequest = 0;
  readonly scheduleBusy = signal<number | null>(null);
  readonly scheduleSourceId = signal<number | null>(null);
  readonly scheduleError = signal(false);
  readonly sourceSchedule = signal<SourceSchedule | null>(null);
  private scheduleRequest = 0;
  private pendingSchedule = { input: '', key: '' };
  readonly indexationLoaded = signal(false);
  readonly indexationLoading = signal(false);
  readonly indexationBuilding = signal(false);
  readonly indexationError = signal(false);
  readonly indexationCrawls = signal<{ id: number; completed_at: string }[]>([]);
  readonly indexationCrawlsTruncated = signal(false);
  readonly indexationCrawlId = signal<number | null>(null);
  readonly indexationReport = signal<IndexationReport | null>(null);
  private indexationRequest = 0;
  readonly performanceLoaded = signal(false);
  readonly performanceLoading = signal(false);
  readonly performanceBusy = signal(false);
  readonly performanceError = signal(false);
  readonly performanceDetailError = signal(false);
  readonly performanceKeyAvailable = signal(false);
  readonly performanceJobs = signal<PerformanceJob[]>([]);
  readonly performanceHasMore = signal(false);
  readonly performanceSelected = signal<PerformanceJob | null>(null);
  readonly performanceObservations = signal<PerformanceObservation[]>([]);
  readonly performanceInspectionRevision = signal(0);
  private performanceRequest = 0;
  private pendingPerformance = { input: '', key: '' };
  readonly coverageBusy = signal<number | null>(null);
  readonly coverageSourceId = signal<number | null>(null);
  readonly coverageLoading = signal(false);
  readonly coverageError = signal(false);
  readonly coverageJob = signal<CoverageJob | null>(null);
  private pendingCoverage = { input: '', key: '' };
  readonly grants = signal<GoogleOAuthGrantInfo[]>([]);
  readonly grantLoading = signal(false);
  readonly ga4Grants = signal<GA4GrantInfo[]>([]);
  readonly ga4Loading = signal(false);
  readonly ga4Error = signal(false);
  readonly ga4Truncated = signal(false);
  readonly ga4Busy = signal<number | null>(null);
  readonly confirmGA4Revoke = signal<number | null>(null);
  private ga4Request = 0;
  readonly ga4SyncSourceId = signal<number | null>(null);
  readonly ga4SyncJob = signal<GA4JobInfo | null>(null);
  readonly ga4SyncPages = signal<GA4PageInfo[]>([]);
  readonly ga4SyncLoading = signal(false);
  readonly ga4SyncError = signal(false);
  readonly ga4SyncBusy = signal<number | null>(null);
  private ga4SyncRequest = 0;
  private pendingGA4Sync = { input: '', key: '' };
  readonly ga4QualitySourceId = signal<number | null>(null);
  readonly ga4QualityReviews = signal<GA4QualityInfo[]>([]);
  readonly ga4QualitySourceCurrent = signal(false);
  readonly ga4QualityLoaded = signal(false);
  readonly ga4QualityLoading = signal(false);
  readonly ga4QualityError = signal(false);
  readonly ga4QualityTruncated = signal(false);
  readonly ga4QualityBusy = signal(false);
  private ga4QualityRequest = 0;
  readonly grantError = signal(false);
  readonly grantsTruncated = signal(false);
  readonly connectingGoogle = signal(false);
  readonly busyGrant = signal<number | null>(null);
  readonly selectedImportSource = signal<number | null>(null);
  readonly importHistory = signal<{id: number; created_at: string; export_shape: string; status: string;
    coverage_state: string; date_start: string; date_end: string; rows_seen: number; rows_imported: number;
    row_errors: number; source_completeness: string}[]>([]);
  readonly importHistoryLoading = signal(false);
  readonly importHistoryError = signal(false);
  readonly importHistoryTruncated = signal(false);
  readonly opportunityLoading = signal(false);
  readonly opportunityError = signal(false);
  readonly opportunityPreview = signal<OpportunityPreview | null>(null);
  private opportunityRequest = 0;
  readonly findingsLoaded = signal(false);
  readonly findingsLoading = signal(false);
  readonly findingsError = signal(false);
  readonly findingsBusy = signal<number | null>(null);
  readonly findings = signal<FindingInfo[]>([]);
  readonly findingsTruncated = signal(false);
  private findingsRequest = 0;
  readonly selectedSource = signal<number | null>(null);
  readonly queries = signal<SourceQueryInfo[]>([]);
  readonly queryMethod = signal('');
  readonly aliasRevision = signal(0);
  readonly nextBefore = signal<number | null>(null);
  readonly queryLoading = signal(false);
  readonly queryError = signal(false);
  readonly reviewing = signal<number | null>(null);
  readonly historyQueryId = signal<number | null>(null);
  readonly history = signal<{revision: number; label: string; reason: string; created_at: string}[]>([]);
  readonly historyLoading = signal(false);
  readonly historyError = signal(false);
  readonly historyTruncated = signal(false);
  readonly queryFilter = signal('all');
  private generation = 0;
  private grantsRequest = 0;
  private sourcesRequest = 0;
  private focusStep = false;
  private stepHeading?: ElementRef<HTMLElement>;
  protected organizationId = 0;
  protected projectId = 0;

  intentRoute() { return ['/app/intent', this.organizationId, this.projectId]; }
  firstAuditRoute() { return ['/app/first-audit', this.organizationId, this.projectId]; }
  pairedQueryRoute() { return ['/app/query-pages', this.organizationId, this.projectId]; }
  localRoute() { return ['/app/local', this.organizationId, this.projectId]; }

  constructor(
    private readonly route: ActivatedRoute,
    private readonly router: Router,
    private readonly api: AccountApi,
    private readonly destroyRef: DestroyRef,
    @Inject(DOCUMENT) private readonly document: Document,
    title: Title,
  ) {
    effect(() => title.setTitle(`${this.t('Project onboarding')} — OrganicSEOOps`));
  }

  ngOnInit() {
    void this.loadProductLanguage();
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((parameters) => {
      this.organizationId = Number(parameters.get('organizationId'));
      this.projectId = Number(parameters.get('projectId'));
      this.grantsRequest++;
      this.sourcesRequest++;
      this.sources.set([]);
      this.sourceError.set(false);
      this.sourceLoading.set(false);
      this.sourcesTruncated.set(false);
      this.changingSource.set(null);
      this.csvBusy.set(false);
      this.pendingCsv.set(null);
      this.clearStatus();
      this.syncBusy.set(null);
      this.syncSourceId.set(null);
      this.syncLoading.set(false);
      this.syncError.set(false);
      this.syncJob.set(null);
      this.pendingSync = { input: '', key: '' };
      this.backfillBusy.set(null);
      this.backfillSourceId.set(null);
      this.backfillLoading.set(false);
      this.backfillError.set(false);
      this.backfillJob.set(null);
      this.pendingBackfill = { input: '', key: '' };
      this.backfillRequest++;
      this.scheduleBusy.set(null);
      this.scheduleSourceId.set(null);
      this.scheduleError.set(false);
      this.sourceSchedule.set(null);
      this.scheduleRequest++;
      this.pendingSchedule = { input: '', key: '' };
      this.indexationLoaded.set(false);
      this.indexationLoading.set(false);
      this.indexationBuilding.set(false);
      this.indexationError.set(false);
      this.indexationCrawls.set([]);
      this.indexationCrawlsTruncated.set(false);
      this.indexationCrawlId.set(null);
      this.indexationReport.set(null);
      this.indexationRequest++;
      this.performanceLoaded.set(false);
      this.performanceLoading.set(false);
      this.performanceBusy.set(false);
      this.performanceError.set(false);
      this.performanceDetailError.set(false);
      this.performanceKeyAvailable.set(false);
      this.performanceJobs.set([]);
      this.performanceHasMore.set(false);
      this.performanceSelected.set(null);
      this.performanceObservations.set([]);
      this.performanceRequest++;
      this.pendingPerformance = { input: '', key: '' };
      this.coverageBusy.set(null);
      this.coverageSourceId.set(null);
      this.coverageLoading.set(false);
      this.coverageError.set(false);
      this.coverageJob.set(null);
      this.pendingCoverage = { input: '', key: '' };
      this.grants.set([]);
      this.ga4Grants.set([]);
      this.ga4Loading.set(false);
      this.ga4Error.set(false);
      this.ga4Truncated.set(false);
      this.ga4Busy.set(null);
      this.confirmGA4Revoke.set(null);
      this.ga4Request++;
      this.ga4SyncSourceId.set(null);
      this.ga4SyncJob.set(null);
      this.ga4SyncPages.set([]);
      this.ga4SyncLoading.set(false);
      this.ga4SyncError.set(false);
      this.ga4SyncBusy.set(null);
      this.ga4SyncRequest++;
      this.pendingGA4Sync = { input: '', key: '' };
      this.ga4QualitySourceId.set(null);
      this.ga4QualityReviews.set([]);
      this.ga4QualitySourceCurrent.set(false);
      this.ga4QualityLoaded.set(false);
      this.ga4QualityLoading.set(false);
      this.ga4QualityError.set(false);
      this.ga4QualityTruncated.set(false);
      this.ga4QualityBusy.set(false);
      this.ga4QualityRequest++;
      this.grantLoading.set(false);
      this.grantError.set(false);
      this.grantsTruncated.set(false);
      this.connectingGoogle.set(false);
      this.busyGrant.set(null);
      this.selectedImportSource.set(null);
      this.importHistory.set([]);
      this.importHistoryLoading.set(false);
      this.importHistoryError.set(false);
      this.opportunityLoading.set(false);
      this.opportunityError.set(false);
      this.opportunityPreview.set(null);
      this.opportunityRequest++;
      this.findingsLoaded.set(false);
      this.findingsLoading.set(false);
      this.findingsError.set(false);
      this.findingsBusy.set(null);
      this.findings.set([]);
      this.findingsTruncated.set(false);
      this.findingsRequest++;
      this.selectedSource.set(null);
      this.queries.set([]);
      this.historyQueryId.set(null);
      this.nextBefore.set(null);
      this.queryLoading.set(false);
      this.queryError.set(false);
      this.reviewing.set(null);
      this.historyLoading.set(false);
      this.historyError.set(false);
      this.queryFilter.set('all');
      if (!positiveInteger(this.organizationId) || !positiveInteger(this.projectId)) {
        this.generation++;
        this.loading.set(false);
        this.saving.set(false);
        this.project.set(null);
        this.configuration.set(null);
        this.denied.set(true);
        return;
      }
      void this.load();
    });
  }

  ngOnDestroy() {
    this.generation++;
  }

  private async loadProductLanguage() {
    try {
      const result = await this.api.productLanguage();
      if (!this.destroyRef.destroyed && result.status === 200 && isProductLanguageResult(result.body)) {
        this.productLanguage.set(result.body['language']);
      }
    } catch { /* Keep English when the private preference is unavailable. */ }
  }

  textLanguage(text: string) {
    return Object.hasOwn(onboardingTurkish, text) || this.messageDraft()?.message === text ? this.uiLanguage() : 'en';
  }

  t(text: string) {
    if (this.textLanguage(text) !== 'tr') return text;
    const draft = this.messageDraft();
    return draft?.message === text ? draft.translation : onboardingTurkish[text];
  }

  private setDraftMessage(message: string, translation: string) {
    this.messageDraft.set({ message, translation });
    this.message.set(message);
  }

  canManage() {
    return this.project()?.role === 'owner' || this.project()?.role === 'admin';
  }

  canReview() {
    return this.canManage() || this.project()?.role === 'member';
  }

  async loadIndexation(crawlId?: number) {
    const generation = this.generation;
    const requestId = ++this.indexationRequest;
    this.indexationLoading.set(true);
    this.indexationError.set(false);
    this.indexationReport.set(null);
    try {
      const response = await this.api.indexationEvidence(this.organizationId, this.projectId, crawlId);
      if (generation !== this.generation || requestId !== this.indexationRequest) return;
      const rows = response.body['crawls'];
      const selected = response.body['crawl_run_id'];
      const report = response.body['report'];
      if (response.status !== 200 || response.body['project_id'] !== this.projectId
        || !Array.isArray(rows) || rows.length > 20 || !rows.every((row) => row && typeof row === 'object'
          && positiveInteger(row['id']) && typeof row['completed_at'] === 'string')
        || typeof response.body['has_more'] !== 'boolean'
        || (selected !== null && !positiveInteger(selected))
        || (report !== null && !isIndexationReport(report, selected))) throw new Error();
      this.indexationCrawls.set(rows);
      this.indexationCrawlsTruncated.set(response.body['has_more'] as boolean);
      this.indexationCrawlId.set(selected as number | null);
      this.indexationReport.set(report as IndexationReport | null);
      this.indexationLoaded.set(true);
    } catch {
      if (generation === this.generation && requestId === this.indexationRequest) this.indexationError.set(true);
    } finally {
      if (generation === this.generation && requestId === this.indexationRequest) this.indexationLoading.set(false);
    }
  }

  selectIndexationCrawl(event: Event) {
    const selected = Number((event.target as HTMLSelectElement).value);
    if (this.indexationCrawls().some((crawl) => crawl.id === selected)) void this.loadIndexation(selected);
  }

  async buildIndexation() {
    const crawlId = this.indexationCrawlId();
    if (!this.canManage() || this.indexationBuilding() || !crawlId
      || !this.indexationCrawls().some((crawl) => crawl.id === crawlId)) return;
    const generation = this.generation;
    this.indexationBuilding.set(true);
    this.clearStatus();
    try {
      const response = await this.api.buildIndexationEvidence(this.organizationId, this.projectId, crawlId);
      if (generation !== this.generation || this.indexationCrawlId() !== crawlId) return;
      if (![200, 201].includes(response.status) || response.body['project_id'] !== this.projectId
        || response.body['crawl_run_id'] !== crawlId || !positiveInteger(response.body['snapshot_id'])) throw new Error();
      await this.loadIndexation(crawlId);
      if (generation === this.generation) this.message.set('No-fetch crawl evidence recorded; Google reports remain separate observations.');
    } catch {
      if (generation === this.generation) this.showError('Crawl evidence could not be built. Check the source and retry.');
    } finally {
      if (generation === this.generation) this.indexationBuilding.set(false);
    }
  }

  async recordIndexationCandidates(crawlRunId: number) {
    if (!this.canManage() || this.indexationReport()?.crawl_run_id !== crawlRunId
      || this.findingsBusy() !== null) return;
    const generation = this.generation;
    const requestId = this.indexationRequest;
    this.findingsBusy.set(crawlRunId);
    this.clearStatus();
    try {
      const response = await this.api.recordIndexationFindings(this.organizationId, this.projectId, crawlRunId);
      if (generation !== this.generation || requestId !== this.indexationRequest) return;
      const ids = response.body['finding_ids'];
      if (response.status !== 201 || response.body['project_id'] !== this.projectId
        || response.body['crawl_run_id'] !== crawlRunId
        || response.body['status'] !== 'recorded_candidate_evidence_not_prioritized'
        || !Array.isArray(ids) || ids.length > 100 || !ids.every(positiveInteger)
        || typeof response.body['truncated_candidates'] !== 'boolean') throw new Error();
      this.setDraftMessage(`${ids.length} scoped indexation candidates recorded for human review. ${response.body['truncated_candidates'] ? 'Other candidates were truncated.' : 'None are approved actions.'}`,
        `${ids.length} kapsam içi dizinleme adayı insan incelemesi için kaydedildi. ${response.body['truncated_candidates'] ? 'Diğer adaylar sınır nedeniyle dahil edilmedi.' : 'Hiçbiri onaylanmış aksiyon değildir.'}`);
      await this.loadFindings();
    } catch {
      if (generation === this.generation) this.showError('Indexation finding outcome unknown. Refresh before retrying.');
    } finally {
      if (generation === this.generation) this.findingsBusy.set(null);
    }
  }

  async recordTechnicalCandidates(diagnosticsId: number) {
    if (this.indexationReport()?.diagnostics_id !== diagnosticsId) return;
    await this.recordDerivedCandidates('technical', diagnosticsId);
  }

  async recordPerformanceCandidates(observationId: number) {
    if (!this.performanceObservations().some((item) => item.id === observationId)) return;
    await this.recordDerivedCandidates('performance', observationId);
  }

  private async recordDerivedCandidates(kind: 'technical' | 'performance', sourceId: number) {
    if (!this.canManage() || this.findingsBusy() !== null) return;
    const generation = this.generation;
    const sourceRequest = kind === 'technical' ? this.indexationRequest : this.performanceRequest;
    this.findingsBusy.set(sourceId);
    this.clearStatus();
    try {
      const response = kind === 'technical'
        ? await this.api.recordTechnicalFindings(this.organizationId, this.projectId, sourceId)
        : await this.api.recordPerformanceFindings(this.organizationId, this.projectId, sourceId);
      if (generation !== this.generation
        || sourceRequest !== (kind === 'technical' ? this.indexationRequest : this.performanceRequest)) return;
      const ids = response.body['finding_ids'];
      if (response.status !== 201 || response.body['project_id'] !== this.projectId
        || response.body[kind === 'technical' ? 'diagnostics_id' : 'observation_id'] !== sourceId
        || response.body['status'] !== 'recorded_candidate_evidence_not_prioritized'
        || !Array.isArray(ids) || ids.length > 100 || !ids.every(positiveInteger)
        || typeof response.body['truncated_candidates'] !== 'boolean') throw new Error();
      this.setDraftMessage(`${ids.length} source-qualified ${kind} candidates recorded for human review; ${response.body['truncated_candidates'] ? 'additional observations are truncated.' : 'none is an approved action.'}`,
        `${ids.length} kaynak kapsamına uygun ${kind === 'technical' ? 'teknik' : 'performans'} adayı insan incelemesi için kaydedildi; ${response.body['truncated_candidates'] ? 'ek gözlemler sınır nedeniyle dahil edilmedi.' : 'hiçbiri onaylanmış aksiyon değildir.'}`);
      await this.loadFindings();
    } catch {
      if (generation === this.generation) this.showError(`${kind} candidate outcome unknown. Refresh findings before retrying.`);
    } finally {
      if (generation === this.generation) this.findingsBusy.set(null);
    }
  }

  async loadPerformance() {
    const generation = this.generation;
    const requestId = ++this.performanceRequest;
    this.performanceLoading.set(true);
    this.performanceError.set(false);
    this.performanceJobs.set([]);
    this.performanceKeyAvailable.set(false);
    this.performanceLoaded.set(false);
    this.performanceHasMore.set(false);
    this.performanceDetailError.set(false);
    this.performanceSelected.set(null);
    this.performanceObservations.set([]);
    try {
      const response = await this.api.performanceAudits(this.organizationId, this.projectId);
      if (generation !== this.generation || requestId !== this.performanceRequest) return;
      const jobs = response.body['jobs'];
      if (response.status !== 200 || response.body['project_id'] !== this.projectId
        || typeof response.body['credential_available'] !== 'boolean'
        || typeof response.body['has_more'] !== 'boolean' || !Array.isArray(jobs) || jobs.length > 20
        || !jobs.every(readPerformanceJob)) throw new Error();
      this.performanceKeyAvailable.set(response.body['credential_available'] as boolean);
      this.performanceJobs.set(jobs);
      this.performanceHasMore.set(response.body['has_more'] as boolean);
      this.performanceLoaded.set(true);
    } catch {
      if (generation === this.generation && requestId === this.performanceRequest) this.performanceError.set(true);
    } finally {
      if (generation === this.generation && requestId === this.performanceRequest) this.performanceLoading.set(false);
    }
  }

  async startPerformance(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!this.canReview() || !this.performanceKeyAvailable() || this.performanceBusy() || !form.reportValidity()) return;
    const fields = new FormData(form);
    const target = String(fields.get('target'));
    const grain = String(fields.get('grain'));
    const strategy = String(fields.get('strategy'));
    const sources = fields.getAll('source').map(String);
    if (!sources.length || (sources.includes('psi_lab') && (grain !== 'page' || strategy === 'tablet'))) {
      this.showError('Select at least one source; Lighthouse lab needs a mobile or desktop page target.');
      return;
    }
    const input = JSON.stringify([this.organizationId, this.projectId, target, grain, strategy, sources]);
    if (this.pendingPerformance.input !== input) this.pendingPerformance = { input, key: crypto.randomUUID() };
    const generation = this.generation;
    this.performanceBusy.set(true);
    this.performanceInspectionRevision.update(value => value + 1);
    this.clearStatus();
    try {
      const response = await this.api.startPerformanceAudit(this.organizationId, this.projectId,
        target, grain, strategy, sources, this.pendingPerformance.key);
      if (generation !== this.generation) return;
      const job = response.body['job'];
      if (response.status !== 202 || response.body['project_id'] !== this.projectId
        || !readPerformanceJob(job) || response.body['max_requests'] !== sources.length) throw new Error();
      this.pendingPerformance = { input: '', key: '' };
      this.setDraftMessage(`Audit ${job.id} queued; refresh to see lab and field results independently.`,
        `Denetim ${job.id} kuyruğa alındı; laboratuvar ve saha sonuçlarını ayrı ayrı görmek için yenileyin.`);
      await this.loadPerformance();
      if (generation === this.generation) await this.showPerformance(job.id);
    } catch {
      if (generation === this.generation) this.showError('Audit outcome unknown. Refresh before retrying the same request.');
    } finally {
      if (generation === this.generation) this.performanceBusy.set(false);
    }
  }

  async showPerformance(jobId: number) {
    if (!this.performanceJobs().some((job) => job.id === jobId)) return;
    const generation = this.generation;
    const requestId = ++this.performanceRequest;
    this.performanceDetailError.set(false);
    this.performanceSelected.set(null);
    this.performanceObservations.set([]);
    try {
      const response = await this.api.performanceAuditDetail(this.organizationId, this.projectId, jobId);
      if (generation !== this.generation || requestId !== this.performanceRequest) return;
      const job = response.body['job'];
      const observations = response.body['observations'];
      if (response.status !== 200 || response.body['project_id'] !== this.projectId
        || !readPerformanceJob(job) || job.id !== jobId || !Array.isArray(observations)
        || observations.length > 3 || !observations.every(readPerformanceObservation)) throw new Error();
      this.performanceSelected.set(job);
      this.performanceObservations.set(observations);
    } catch {
      if (generation === this.generation && requestId === this.performanceRequest) this.performanceDetailError.set(true);
    }
  }

  async cancelPerformance(jobId: number) {
    if (!this.canReview() || this.performanceBusy() || this.performanceSelected()?.id !== jobId) return;
    const generation = this.generation;
    this.performanceBusy.set(true);
    this.performanceInspectionRevision.update(value => value + 1);
    try {
      const response = await this.api.cancelPerformanceAudit(this.organizationId, this.projectId, jobId);
      if (generation !== this.generation) return;
      const job = response.body['job'];
      if (![200, 202].includes(response.status) || response.body['project_id'] !== this.projectId
        || !readPerformanceJob(job) || job.id !== jobId) throw new Error();
      this.performanceSelected.set(job);
      this.performanceJobs.update((jobs) => jobs.map((entry) => entry.id === jobId ? job : entry));
      this.message.set(response.status === 202 ? 'Audit cancellation requested; one attempt may still finish.' : 'Audit cancelled.');
    } catch {
      if (generation === this.generation) this.showError('Audit cancellation outcome unknown; refresh its status.');
    } finally {
      if (generation === this.generation) this.performanceBusy.set(false);
    }
  }

  performanceText(result: Record<string, unknown>, key: string) {
    const value = result[key];
    return typeof value === 'string' && value.length <= 128 ? value : 'unknown';
  }

  performanceLabScore(result: Record<string, unknown>) {
    const scores = result['scores'];
    const value = scores && typeof scores === 'object' ? (scores as Record<string, unknown>)['performance'] : null;
    return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1 ? value : 'unavailable';
  }

  performanceLabAudits(result: Record<string, unknown>) {
    const raw = result['audits'];
    if (!raw || typeof raw !== 'object') return [];
    return Object.entries(raw).filter(([name]) => ['largest-contentful-paint', 'cumulative-layout-shift',
      'total-blocking-time', 'speed-index'].includes(name)).map(([name, data]) => {
      const item = data && typeof data === 'object' ? data as Record<string, unknown> : {};
      return { name, value: typeof item['value'] === 'number' && Number.isFinite(item['value']) ? item['value'] : null,
        unit: typeof item['unit'] === 'string' ? item['unit'] : '', state: item['state'] === 'observed' ? 'observed' : 'unavailable' };
    });
  }

  performanceFieldMetrics(result: Record<string, unknown>) {
    const rows = result['metrics'];
    if (!Array.isArray(rows) || rows.length > 160) return [];
    return rows.map((row: unknown) => {
      const item = row && typeof row === 'object' ? row as Record<string, unknown> : {};
      const period = item['period'] && typeof item['period'] === 'object' ? item['period'] as Record<string, unknown> : {};
      return { name: String(item['name'] ?? 'unknown'), p75: typeof item['p75'] === 'number' || typeof item['p75'] === 'string' ? item['p75'] : null,
        unit: String(item['unit'] ?? ''), grade: String(item['grade'] ?? 'unknown'), state: String(item['state'] ?? 'unavailable'),
        period: `${String(period['start'] ?? 'unknown')} to ${String(period['end'] ?? 'unknown')} (PST)` };
    });
  }

  async connectGoogle() {
    if (!this.canManage() || this.connectingGoogle()) return;
    const generation = this.generation;
    const projectId = this.projectId;
    this.connectingGoogle.set(true);
    this.clearStatus();
    try {
      const result = await this.api.startGoogleOAuth(this.organizationId, projectId);
      if (generation !== this.generation) return;
      const raw = result.body['authorization_url'];
      if (result.status !== 201 || typeof raw !== 'string') {
        this.showError('Google authorization is unavailable. Check the configured callback and your access.');
        return;
      }
      const target = new URL(raw);
      if (target.origin !== 'https://accounts.google.com' || target.pathname !== '/o/oauth2/v2/auth'
        || !target.searchParams.get('state')) {
        this.showError('Google authorization could not be started.');
        return;
      }
      this.document.defaultView?.location.assign(target.href);
    } catch {
      if (generation === this.generation) this.showError('Google authorization could not be started. Check the connection and retry.');
    } finally {
      if (generation === this.generation) this.connectingGoogle.set(false);
    }
  }

  ga4Origins() {
    const project = this.project();
    return project ? [project.canonical_origin, ...project.aliases].filter((origin) => origin.startsWith('https://')) : [];
  }

  async loadGA4Grants() {
    const generation = this.generation;
    const request = ++this.ga4Request;
    this.ga4Loading.set(true);
    this.ga4Error.set(false);
    this.ga4Grants.set([]);
    this.ga4Truncated.set(false);
    try {
      const response = await this.api.ga4Grants(this.organizationId, this.projectId);
      if (generation !== this.generation || request !== this.ga4Request) return;
      const rows = response.body['grants'];
      if (response.status !== 200 || response.body['project_id'] !== this.projectId
        || !Array.isArray(rows) || rows.length > 20 || !rows.every(isGA4GrantInfo)
        || typeof response.body['has_more'] !== 'boolean') throw new Error();
      this.ga4Grants.set(rows);
      this.ga4Truncated.set(response.body['has_more']);
    } catch {
      if (generation === this.generation && request === this.ga4Request) this.ga4Error.set(true);
    } finally {
      if (generation === this.generation && request === this.ga4Request) this.ga4Loading.set(false);
    }
  }

  async connectGA4() {
    if (!this.canManage() || this.ga4Busy() !== null) return;
    const generation = this.generation;
    this.ga4Busy.set(0);
    this.clearStatus();
    try {
      const response = await this.api.startGA4OAuth(this.organizationId, this.projectId);
      if (generation !== this.generation) return;
      const raw = response.body['authorization_url'];
      if (response.status !== 201 || typeof raw !== 'string') throw new Error();
      const target = new URL(raw);
      if (target.origin !== 'https://accounts.google.com' || target.pathname !== '/o/oauth2/v2/auth'
        || target.searchParams.get('scope') !== 'https://www.googleapis.com/auth/analytics.readonly'
        || !target.searchParams.get('state')) throw new Error();
      this.document.defaultView?.location.assign(target.href);
    } catch {
      if (generation === this.generation) this.showError('Analytics consent unavailable. Check staff app configuration, project access and retry.');
    } finally {
      if (generation === this.generation) this.ga4Busy.set(null);
    }
  }

  async selectGA4(event: SubmitEvent, grant: GA4GrantInfo) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || !this.canManage() || this.ga4Busy() !== null
      || !this.ga4Grants().some((row) => row.id === grant.id && row.revision === grant.revision)) return;
    const data = new FormData(form);
    const propertyId = String(data.get('property_id'));
    const origin = String(data.get('origin'));
    if (!/^[1-9][0-9]{0,19}$/.test(propertyId) || !this.ga4Origins().includes(origin)) return;
    await this.changeGA4(grant, () => this.api.selectGA4Property(this.organizationId, this.projectId,
      grant.id, propertyId, origin, grant.revision), 'Analytics web-stream candidate saved; no source or data sync is active.');
  }

  async linkGA4(grant: GA4GrantInfo) {
    if (!this.canManage() || grant.state !== 'pending_selection' || !grant.scope_current) return;
    await this.changeGA4(grant, () => this.api.linkGA4Source(this.organizationId, this.projectId,
      grant.id, grant.revision), 'Analytics source scoped to this project; data synchronization is not yet available.');
  }

  async revokeGA4(grant: GA4GrantInfo) {
    if (!this.canManage() || this.confirmGA4Revoke() !== grant.id) return;
    this.confirmGA4Revoke.set(null);
    await this.changeGA4(grant, () => this.api.revokeGA4Grant(this.organizationId, this.projectId, grant.id),
      'Local Analytics access disabled; refresh to confirm remote revocation.');
  }

  private async changeGA4(grant: GA4GrantInfo, action: () => ReturnType<AccountApi['revokeGA4Grant']>, message: string) {
    if (this.ga4Busy() !== null || !this.ga4Grants().some((row) => row.id === grant.id && row.revision === grant.revision)) return;
    const generation = this.generation;
    this.ga4Busy.set(grant.id);
    this.clearStatus();
    try {
      const response = await action();
      if (generation !== this.generation) return;
      if (response.status !== 200 || response.body['id'] !== grant.id || response.body['project_id'] !== this.projectId
        || typeof response.body['state'] !== 'string' || typeof response.body['source_status'] !== 'string') throw new Error();
      this.message.set(message);
      await this.loadGA4Grants();
      await this.loadSources(generation, this.organizationId, this.projectId);
    } catch {
      if (generation === this.generation) this.showError('Analytics grant outcome unknown. Refresh this project before retrying.');
    } finally {
      if (generation === this.generation) this.ga4Busy.set(null);
    }
  }

  async startGA4Sync(event: SubmitEvent, connectionId: number) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const source = this.sources().find((item) => item.id === connectionId);
    if (!this.canManage() || source?.provider !== 'google_analytics_4' || !source.api_sync_available
      || !form.reportValidity() || this.ga4SyncBusy() !== null) return;
    const day = String(new FormData(form).get('day'));
    const reportKind = String(new FormData(form).get('report_kind'));
    if (reportKind !== 'all_channels' && reportKind !== 'organic_search') return;
    const input = JSON.stringify([this.organizationId, this.projectId, connectionId, day, reportKind]);
    if (this.pendingGA4Sync.input !== input) this.pendingGA4Sync = { input, key: crypto.randomUUID() };
    const generation = this.generation;
    this.ga4SyncBusy.set(connectionId);
    this.ga4SyncSourceId.set(connectionId);
    this.ga4SyncError.set(false);
    this.clearStatus();
    try {
      const response = await this.api.queueGA4Sync(this.organizationId, this.projectId,
        connectionId, day, reportKind, this.pendingGA4Sync.key);
      if (generation !== this.generation || this.ga4SyncSourceId() !== connectionId) return;
      if (response.status !== 202 || response.body['project_id'] !== this.projectId
        || response.body['connection_id'] !== connectionId || !positiveInteger(response.body['job_id'])
        || response.body['max_requests'] !== 5 || response.body['report_kind'] !== reportKind) throw new Error();
      this.pendingGA4Sync = { input: '', key: '' };
      this.setDraftMessage(`Analytics job ${response.body['job_id']} queued. Refresh for observed rows; missing conversions remain unknown.`,
        `Analytics işi ${response.body['job_id']} kuyruğa alındı. Gözlenen satırlar için yenileyin; eksik dönüşümler bilinmiyor.`);
      await this.refreshGA4Sync(connectionId);
    } catch {
      if (generation === this.generation) this.showError('Analytics request outcome unknown. Refresh status before retrying the same day.');
    } finally {
      if (generation === this.generation) this.ga4SyncBusy.set(null);
    }
  }

  async refreshGA4Sync(connectionId: number) {
    if (!this.sources().some((source) => source.id === connectionId && source.provider === 'google_analytics_4')) return;
    const generation = this.generation;
    const request = ++this.ga4SyncRequest;
    this.ga4SyncSourceId.set(connectionId);
    this.ga4SyncLoading.set(true);
    this.ga4SyncError.set(false);
    this.ga4SyncJob.set(null);
    this.ga4SyncPages.set([]);
    try {
      const response = await this.api.ga4SyncStatus(this.organizationId, this.projectId, connectionId);
      if (generation !== this.generation || request !== this.ga4SyncRequest || this.ga4SyncSourceId() !== connectionId) return;
      const job = response.body['job'];
      const pages = response.body['pages'];
      if (response.status !== 200 || response.body['project_id'] !== this.projectId
        || response.body['connection_id'] !== connectionId || typeof response.body['source_current'] !== 'boolean'
        || (job !== null && !isGA4JobInfo(job)) || !Array.isArray(pages)
        || pages.length > 2 || !pages.every(isGA4PageInfo)) throw new Error();
      this.ga4SyncJob.set(job);
      this.ga4SyncPages.set(pages);
    } catch {
      if (generation === this.generation && request === this.ga4SyncRequest) this.ga4SyncError.set(true);
    } finally {
      if (generation === this.generation && request === this.ga4SyncRequest) this.ga4SyncLoading.set(false);
    }
  }

  async cancelGA4Sync(connectionId: number, jobId: number) {
    if (!this.canManage() || this.ga4SyncBusy() !== null || this.ga4SyncSourceId() !== connectionId
      || this.ga4SyncJob()?.id !== jobId) return;
    const generation = this.generation;
    this.ga4SyncBusy.set(connectionId);
    this.clearStatus();
    try {
      const response = await this.api.cancelGA4Sync(this.organizationId, this.projectId, connectionId, jobId);
      if (generation !== this.generation || this.ga4SyncSourceId() !== connectionId) return;
      if (response.status !== 200 || response.body['project_id'] !== this.projectId
        || response.body['connection_id'] !== connectionId || !isGA4JobInfo(response.body['job'])
        || response.body['job'].id !== jobId) throw new Error();
      this.message.set('Analytics cancellation requested. Refresh status to see the final observed result.');
      await this.refreshGA4Sync(connectionId);
    } catch {
      if (generation === this.generation) this.showError('Analytics cancellation outcome unknown; refresh before retrying.');
    } finally {
      if (generation === this.generation) this.ga4SyncBusy.set(null);
    }
  }

  async loadGA4Quality(connectionId: number) {
    if (!this.sources().some((source) => source.id === connectionId && source.provider === 'google_analytics_4')) return;
    const generation = this.generation;
    const request = ++this.ga4QualityRequest;
    this.ga4QualitySourceId.set(connectionId);
    this.ga4QualityLoading.set(true);
    this.ga4QualityLoaded.set(false);
    this.ga4QualityError.set(false);
    this.ga4QualityReviews.set([]);
    this.ga4QualitySourceCurrent.set(false);
    this.ga4QualityTruncated.set(false);
    try {
      const response = await this.api.ga4QualityHistory(this.organizationId, this.projectId, connectionId);
      if (generation !== this.generation || request !== this.ga4QualityRequest
        || this.ga4QualitySourceId() !== connectionId) return;
      const rows = response.body['reviews'];
      if (response.status !== 200 || response.body['project_id'] !== this.projectId
        || response.body['connection_id'] !== connectionId || typeof response.body['source_current'] !== 'boolean'
        || !Array.isArray(rows) || rows.length > 20 || !rows.every(isGA4QualityInfo)
        || typeof response.body['has_more'] !== 'boolean') throw new Error();
      this.ga4QualityReviews.set(rows);
      this.ga4QualitySourceCurrent.set(response.body['source_current']);
      this.ga4QualityTruncated.set(response.body['has_more']);
      this.ga4QualityLoaded.set(true);
    } catch {
      if (generation === this.generation && request === this.ga4QualityRequest) this.ga4QualityError.set(true);
    } finally {
      if (generation === this.generation && request === this.ga4QualityRequest) this.ga4QualityLoading.set(false);
    }
  }

  async saveGA4Quality(event: SubmitEvent, connectionId: number) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!this.canManage() || !this.ga4QualitySourceCurrent() || this.ga4QualitySourceId() !== connectionId
      || this.ga4QualityBusy() || !form.reportValidity()) return;
    const fields = new FormData(form);
    const lines = String(fields.get('definitions')).split('\n').map((line) => line.trim()).filter(Boolean);
    if (lines.length > 10) { this.showError('Choose at most ten Analytics event mappings.'); return; }
    const definitions = lines.map((line) => line.split('|').map((part) => part.trim()));
    if (definitions.some((row) => row.length !== 3 || !row[0] || !/^[A-Za-z][A-Za-z0-9_]{0,39}$/.test(row[1]))) {
      this.showError('Use goal | event_name | manual value definition on each line.'); return;
    }
    const generation = this.generation;
    const latest = this.ga4QualityReviews()[0]?.revision ?? 0;
    this.ga4QualityBusy.set(true);
    this.clearStatus();
    try {
      const response = await this.api.saveGA4Quality(this.organizationId, this.projectId, connectionId, {
        expected_revision: latest,
        definitions: definitions.map(([goal, event_name, value_definition]) => ({ goal, event_name, value_definition })),
        instrumentation_state: String(fields.get('instrumentation_state')),
        event_quality_state: String(fields.get('event_quality_state')),
        instrumentation_notes: String(fields.get('instrumentation_notes')).trim(),
        attribution_notes: String(fields.get('attribution_notes')).trim(),
        consent_notes: String(fields.get('consent_notes')).trim(),
        tracking_change_notes: String(fields.get('tracking_change_notes')).trim(),
      });
      if (generation !== this.generation || this.ga4QualitySourceId() !== connectionId) return;
      if (response.status !== 201 || response.body['project_id'] !== this.projectId
        || response.body['connection_id'] !== connectionId || !isGA4QualityInfo(response.body['review'])
        || response.body['provider_instrumentation_verified'] !== false) throw new Error();
      this.message.set('Manual Analytics measurement review recorded; no event count, attribution or conversion was verified.');
      form.reset();
      await this.loadGA4Quality(connectionId);
    } catch {
      if (generation === this.generation) this.showError('Analytics review outcome unknown. Refresh history before retrying.');
    } finally {
      if (generation === this.generation) this.ga4QualityBusy.set(false);
    }
  }

  async selectGoogleProperty(grant: GoogleOAuthGrantInfo, siteUrl: string) {
    if (!this.canManage() || this.busyGrant() !== null || grant.state !== 'pending_selection'
      || !grant.sites.some((site) => site.site_url === siteUrl)) return;
    await this.changeGoogleGrant(grant, () => this.api.selectGoogleSite(this.organizationId, this.projectId,
      grant.id, grant.revision, siteUrl), 'Google property authorization recorded. Check source status before starting API sync.');
  }

  async revokeGoogle(grant: GoogleOAuthGrantInfo) {
    if (!this.canManage() || this.busyGrant() !== null || grant.state === 'revoked') return;
    await this.changeGoogleGrant(grant, () => this.api.revokeGoogleOAuth(this.organizationId, this.projectId,
      grant.id, grant.revision), 'Local Google access disabled. Check whether remote revocation is still pending.');
  }

  async startSync(event: SubmitEvent, connectionId: number) {
    event.preventDefault();
    const source = this.sources().find((item) => item.id === connectionId);
    const form = event.currentTarget as HTMLFormElement;
    if (!this.canManage() || !source?.api_sync_available || !form.reportValidity() || this.syncBusy() !== null) return;
    const fields = new FormData(form);
    const day = String(fields.get('day'));
    const dimension = String(fields.get('dimension'));
    if (source.scope_kind === 'verified_domain_page_only' && dimension !== 'page') {
      this.showError('Domain properties only support verified-origin page reports.'); return;
    }
    const input = JSON.stringify([this.organizationId, this.projectId, connectionId, day, dimension]);
    if (this.pendingSync.input !== input) this.pendingSync = { input, key: crypto.randomUUID() };
    const generation = this.generation;
    const organizationId = this.organizationId;
    const projectId = this.projectId;
    if (this.syncSourceId() !== connectionId) {
      this.syncJob.set(null);
      this.syncLoading.set(false);
    }
    this.syncBusy.set(connectionId);
    this.syncSourceId.set(connectionId);
    this.syncError.set(false);
    this.clearStatus();
    try {
      const result = await this.api.startSearchConsoleSync(organizationId, projectId, connectionId,
        day, [dimension], this.pendingSync.key);
      if (generation !== this.generation || this.syncSourceId() !== connectionId) return;
      if (result.status !== 202 || result.body['project_id'] !== projectId
        || !positiveInteger(result.body['job_id'])) {
        this.showError(result.status === 429 ? 'Sync is rate limited or at capacity. Check the source status before retrying.'
          : 'Sync could not start. Check the current property, date, and authorization.');
        return;
      }
      this.pendingSync = { input: '', key: '' };
      this.setDraftMessage(`Search Console job ${result.body['job_id']} queued. Refresh its status below; missing provider rows remain unknown.`,
        `Search Console işi ${result.body['job_id']} kuyruğa alındı. Aşağıdan durumunu yenileyin; eksik sağlayıcı satırları bilinmiyor.`);
      await this.refreshSync(connectionId);
    } catch {
      if (generation === this.generation) this.showError('Sync request outcome is unknown. Retry the same date and dimension to avoid duplicate work.');
    } finally {
      if (generation === this.generation) this.syncBusy.set(null);
    }
  }

  async startBackfill(event: SubmitEvent, connectionId: number) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const source = this.sources().find((item) => item.id === connectionId);
    if (!this.canManage() || !source?.api_sync_available || !form.reportValidity() || this.backfillBusy() !== null) return;
    const fields = new FormData(form);
    const start = String(fields.get('start_day'));
    const end = String(fields.get('end_day'));
    const dimension = String(fields.get('dimension'));
    if (source.scope_kind === 'verified_domain_page_only' && dimension !== 'page') return;
    const input = JSON.stringify([this.organizationId, this.projectId, connectionId, start, end, dimension]);
    if (this.pendingBackfill.input !== input) this.pendingBackfill = { input, key: crypto.randomUUID() };
    const generation = this.generation;
    if (this.backfillSourceId() !== connectionId) {
      this.backfillJob.set(null);
      this.backfillLoading.set(false);
    }
    const requestId = ++this.backfillRequest;
    this.backfillBusy.set(connectionId);
    this.backfillSourceId.set(connectionId);
    this.backfillError.set(false);
    this.clearStatus();
    try {
      const response = await this.api.startSearchConsoleBackfill(this.organizationId, this.projectId, connectionId,
        start, end, dimension, this.pendingBackfill.key);
      if (generation !== this.generation || this.backfillSourceId() !== connectionId
        || requestId !== this.backfillRequest) return;
      const batch = readBackfillJob(response.body['backfill']);
      if (response.status !== 202 || response.body['project_id'] !== this.projectId
        || response.body['connection_id'] !== connectionId || !batch) throw new Error();
      this.pendingBackfill = { input: '', key: '' };
      this.backfillJob.set(batch);
      this.message.set('Backfill queued; refresh to see each finalized day or a paused outcome.');
    } catch {
      if (generation === this.generation && requestId === this.backfillRequest)
        this.showError('Backfill outcome unknown. Retry the same range to avoid duplicate work.');
    } finally {
      if (generation === this.generation) this.backfillBusy.set(null);
    }
  }

  async refreshBackfill(connectionId: number) {
    if (!this.sources().some((source) => source.id === connectionId)
      || this.backfillLoading() && this.backfillSourceId() === connectionId) return;
    const generation = this.generation;
    this.backfillJob.set(null);
    const requestId = ++this.backfillRequest;
    this.backfillSourceId.set(connectionId);
    this.backfillLoading.set(true);
    this.backfillError.set(false);
    try {
      const response = await this.api.searchConsoleBackfillStatus(this.organizationId, this.projectId, connectionId);
      if (generation !== this.generation || this.backfillSourceId() !== connectionId
        || requestId !== this.backfillRequest) return;
      const batch = response.body['backfill'];
      if (response.status !== 200 || response.body['project_id'] !== this.projectId
        || response.body['connection_id'] !== connectionId || batch !== null && !readBackfillJob(batch)) throw new Error();
      this.backfillJob.set(batch as BackfillJob | null);
    } catch {
      if (generation === this.generation && this.backfillSourceId() === connectionId
        && requestId === this.backfillRequest) this.backfillError.set(true);
    } finally {
      if (generation === this.generation && this.backfillSourceId() === connectionId
        && requestId === this.backfillRequest) this.backfillLoading.set(false);
    }
  }

  async cancelBackfill(connectionId: number, backfillId: number) {
    if (!this.canManage() || this.backfillBusy() !== null || this.backfillSourceId() !== connectionId
      || this.backfillJob()?.id !== backfillId) return;
    const generation = this.generation;
    this.backfillBusy.set(connectionId);
    try {
      const response = await this.api.cancelSearchConsoleBackfill(this.organizationId, this.projectId, connectionId, backfillId);
      if (generation !== this.generation || this.backfillSourceId() !== connectionId) return;
      const batch = readBackfillJob(response.body['backfill']);
      if (response.status !== 200 || response.body['project_id'] !== this.projectId
        || response.body['connection_id'] !== connectionId || batch?.id !== backfillId) throw new Error();
      this.backfillJob.set(batch);
    } catch {
      if (generation === this.generation) this.showError('Backfill stop outcome unknown; refresh its status.');
    } finally {
      if (generation === this.generation) this.backfillBusy.set(null);
    }
  }

  async createSchedule(event: SubmitEvent, connectionId: number) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const source = this.sources().find((item) => item.id === connectionId);
    if (!this.canManage() || !source?.api_sync_available || this.scheduleBusy() !== null) return;
    const dimension = String(new FormData(form).get('dimension'));
    if (source.scope_kind === 'verified_domain_page_only' && dimension !== 'page') return;
    const input = JSON.stringify([this.organizationId, this.projectId, connectionId, dimension]);
    if (this.pendingSchedule.input !== input) this.pendingSchedule = { input, key: crypto.randomUUID() };
    const generation = this.generation;
    const requestId = ++this.scheduleRequest;
    if (this.scheduleSourceId() !== connectionId) this.sourceSchedule.set(null);
    this.scheduleSourceId.set(connectionId);
    this.scheduleBusy.set(connectionId);
    this.scheduleError.set(false);
    try {
      const response = await this.api.createSearchConsoleSchedule(this.organizationId, this.projectId, connectionId,
        dimension, this.pendingSchedule.key);
      if (generation !== this.generation || requestId !== this.scheduleRequest) return;
      const schedule = readSourceSchedule(response.body['schedule']);
      if (response.status !== 201 || response.body['project_id'] !== this.projectId
        || response.body['connection_id'] !== connectionId || !schedule) throw new Error();
      this.pendingSchedule = { input: '', key: '' };
      this.sourceSchedule.set(schedule);
      this.message.set('Daily report schedule created but paused. Enable it to start future checks.');
    } catch {
      if (generation === this.generation && requestId === this.scheduleRequest)
        this.showError('Schedule outcome unknown. Refresh this source before retrying.');
    } finally {
      if (generation === this.generation) this.scheduleBusy.set(null);
    }
  }

  async refreshSchedule(connectionId: number) {
    if (!this.sources().some((source) => source.id === connectionId) || this.scheduleBusy() !== null) return;
    const generation = this.generation;
    const requestId = ++this.scheduleRequest;
    this.sourceSchedule.set(null);
    this.scheduleSourceId.set(connectionId);
    this.scheduleBusy.set(connectionId);
    this.scheduleError.set(false);
    try {
      const response = await this.api.searchConsoleScheduleStatus(this.organizationId, this.projectId, connectionId);
      if (generation !== this.generation || requestId !== this.scheduleRequest) return;
      const schedule = response.body['schedule'];
      if (response.status !== 200 || response.body['project_id'] !== this.projectId
        || response.body['connection_id'] !== connectionId || schedule !== null && !readSourceSchedule(schedule)) throw new Error();
      this.sourceSchedule.set(schedule as SourceSchedule | null);
    } catch {
      if (generation === this.generation && requestId === this.scheduleRequest) this.scheduleError.set(true);
    } finally {
      if (generation === this.generation && requestId === this.scheduleRequest) this.scheduleBusy.set(null);
    }
  }

  async toggleSchedule(connectionId: number, scheduleId: number, enabled: boolean) {
    if (!this.canManage() || this.scheduleBusy() !== null || this.scheduleSourceId() !== connectionId
      || this.sourceSchedule()?.id !== scheduleId) return;
    const generation = this.generation;
    const requestId = ++this.scheduleRequest;
    this.scheduleBusy.set(connectionId);
    try {
      const response = await this.api.toggleSearchConsoleSchedule(this.organizationId, this.projectId,
        connectionId, scheduleId, enabled);
      if (generation !== this.generation || requestId !== this.scheduleRequest) return;
      const schedule = readSourceSchedule(response.body['schedule']);
      if (response.status !== 200 || response.body['project_id'] !== this.projectId
        || response.body['connection_id'] !== connectionId || schedule?.id !== scheduleId
        || schedule.enabled !== enabled) throw new Error();
      this.sourceSchedule.set(schedule);
    } catch {
      if (generation === this.generation && requestId === this.scheduleRequest)
        this.showError('Daily schedule change could not be confirmed. Refresh before retrying.');
    } finally {
      if (generation === this.generation) this.scheduleBusy.set(null);
    }
  }

  coverageValue(result: Record<string, unknown>, key: string) {
    const value = result[key];
    return typeof value === 'string' && value.length <= 128 ? value : 'unknown';
  }

  coverageSitemaps(result: Record<string, unknown>): string[] {
    const rows = result['sitemaps'];
    return Array.isArray(rows) && rows.length <= 100 && rows.every((item: unknown) =>
      item && typeof item === 'object' && typeof (item as Record<string, unknown>)['url'] === 'string'
      && String((item as Record<string, unknown>)['url']).length <= 2048)
      ? rows.map((item: {url: string}) => item.url) : [];
  }

  async startCoverage(event: SubmitEvent, connectionId: number) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const source = this.sources().find((item) => item.id === connectionId);
    if (!this.canManage() || !source?.coverage_available || !form.reportValidity() || this.coverageBusy() !== null) return;
    const inspectionUrl = String(new FormData(form).get('inspection_url'));
    const input = JSON.stringify([this.organizationId, this.projectId, connectionId, inspectionUrl]);
    if (this.pendingCoverage.input !== input) this.pendingCoverage = { input, key: crypto.randomUUID() };
    const generation = this.generation;
    if (this.coverageSourceId() !== connectionId) {
      this.coverageJob.set(null);
      this.coverageLoading.set(false);
    }
    this.coverageBusy.set(connectionId);
    this.coverageSourceId.set(connectionId);
    this.coverageError.set(false);
    this.clearStatus();
    try {
      const response = await this.api.startSearchConsoleCoverage(this.organizationId, this.projectId, connectionId,
        inspectionUrl, this.pendingCoverage.key);
      if (generation !== this.generation || this.coverageSourceId() !== connectionId) return;
      const job = readCoverageJob(response.body['job']);
      if (response.status !== 202 || response.body['project_id'] !== this.projectId
        || response.body['connection_id'] !== connectionId || !job) throw new Error();
      this.pendingCoverage = { input: '', key: '' };
      this.coverageJob.set(job);
      this.setDraftMessage(`Coverage job ${job.id} queued. Google index-version evidence and scoped sitemap URLs are not live-page or whole-domain totals.`,
        `Kapsam işi ${job.id} kuyruğa alındı. Google dizin sürümü kanıtları ve kapsam içi site haritası URL’leri canlı sayfa veya tüm alan adı toplamları değildir.`);
      await this.refreshCoverage(connectionId);
    } catch {
      if (generation === this.generation) this.showError('Coverage request outcome is unknown. Retry the same URL to avoid duplicate work.');
    } finally {
      if (generation === this.generation) this.coverageBusy.set(null);
    }
  }

  async refreshCoverage(connectionId: number) {
    if (!this.sources().some((source) => source.id === connectionId)
      || this.coverageLoading() && this.coverageSourceId() === connectionId) return;
    const generation = this.generation;
    this.coverageJob.set(null);
    this.coverageSourceId.set(connectionId);
    this.coverageLoading.set(true);
    this.coverageError.set(false);
    try {
      const response = await this.api.searchConsoleCoverageStatus(this.organizationId, this.projectId, connectionId);
      if (generation !== this.generation || this.coverageSourceId() !== connectionId) return;
      const job = response.body['job'];
      if (response.status !== 200 || response.body['project_id'] !== this.projectId
        || response.body['connection_id'] !== connectionId || (job !== null && !readCoverageJob(job))) throw new Error();
      this.coverageJob.set(job as CoverageJob | null);
      void this.loadSources(generation, this.organizationId, this.projectId);
    } catch {
      if (generation === this.generation && this.coverageSourceId() === connectionId) this.coverageError.set(true);
    } finally {
      if (generation === this.generation && this.coverageSourceId() === connectionId) this.coverageLoading.set(false);
    }
  }

  async cancelCoverage(connectionId: number, jobId: number) {
    if (!this.canManage() || this.coverageBusy() !== null || this.coverageSourceId() !== connectionId
      || this.coverageJob()?.id !== jobId) return;
    const generation = this.generation;
    this.coverageBusy.set(connectionId);
    try {
      const response = await this.api.cancelSearchConsoleCoverage(this.organizationId, this.projectId, connectionId, jobId);
      if (generation !== this.generation) return;
      const job = readCoverageJob(response.body['job']);
      if (![200, 202].includes(response.status) || response.body['project_id'] !== this.projectId
        || response.body['connection_id'] !== connectionId || job?.id !== jobId) throw new Error();
      this.coverageJob.set(job);
      this.message.set(response.status === 202 ? 'Coverage cancellation requested; an attempt may still finish.'
        : 'Coverage request cancelled.');
    } catch {
      if (generation === this.generation) this.showError('Cancellation outcome is unknown. Refresh coverage status first.');
    } finally {
      if (generation === this.generation) this.coverageBusy.set(null);
    }
  }

  async refreshSync(connectionId: number) {
    if (!this.sources().some((source) => source.id === connectionId)
      || this.syncLoading() && this.syncSourceId() === connectionId) return;
    const generation = this.generation;
    const organizationId = this.organizationId;
    const projectId = this.projectId;
    this.syncJob.set(null);
    this.syncSourceId.set(connectionId);
    this.syncLoading.set(true);
    this.syncError.set(false);
    try {
      const result = await this.api.searchConsoleSyncStatus(organizationId, projectId, connectionId);
      if (generation !== this.generation || this.syncSourceId() !== connectionId) return;
      const job = result.body['job'];
      if (result.status !== 200 || result.body['project_id'] !== projectId || result.body['connection_id'] !== connectionId
        || (job !== null && !isSyncJob(job))) {
        this.syncError.set(true);
        return;
      }
      this.syncJob.set(job);
      void this.loadSources(generation, organizationId, projectId);
    } catch {
      if (generation === this.generation && this.syncSourceId() === connectionId) this.syncError.set(true);
    } finally {
      if (generation === this.generation && this.syncSourceId() === connectionId) this.syncLoading.set(false);
    }
  }

  async cancelSync(connectionId: number, jobId: number) {
    if (!this.canManage() || this.syncBusy() !== null || this.syncSourceId() !== connectionId || this.syncJob()?.id !== jobId) return;
    const generation = this.generation;
    this.syncBusy.set(connectionId);
    try {
      const result = await this.api.cancelSearchConsoleSync(this.organizationId, this.projectId, connectionId, jobId);
      if (generation !== this.generation) return;
      if (![200, 202].includes(result.status) || result.body['project_id'] !== this.projectId
        || result.body['connection_id'] !== connectionId || !isSyncJob(result.body['job'])
        || result.body['job'].id !== jobId) {
        this.showError('Sync cancellation could not be confirmed. Refresh its status before retrying.');
        return;
      }
      this.syncJob.set(result.body['job']);
      this.message.set(result.status === 202 ? 'Cancellation requested; the current request may finish.' : 'Sync cancelled.');
    } catch {
      if (generation === this.generation) this.showError('Cancellation outcome is unknown. Refresh sync status.');
    } finally {
      if (generation === this.generation) this.syncBusy.set(null);
    }
  }

  private async changeGoogleGrant(grant: GoogleOAuthGrantInfo, action: () => Promise<{status: number; body: Record<string, unknown>}>, success: string) {
    const generation = this.generation;
    const organizationId = this.organizationId;
    const projectId = this.projectId;
    this.busyGrant.set(grant.id);
    this.clearStatus();
    try {
      const result = await action();
      if (generation !== this.generation) return;
      if (![200, 202].includes(result.status) || (result.body['project_id'] !== undefined && result.body['project_id'] !== projectId)) {
        this.showError('Google authorization changed or is unavailable. Reload this project before retrying.');
        return;
      }
      this.message.set(success);
      void this.loadGrants(generation, organizationId, projectId);
      void this.loadSources(generation, organizationId, projectId);
    } catch {
      if (generation === this.generation) this.showError('Google authorization outcome is unknown. Reload before retrying.');
    } finally {
      if (generation === this.generation) this.busyGrant.set(null);
    }
  }

  async showImportHistory(connectionId: number) {
    if (!this.sources().some((source) => source.id === connectionId)) return;
    const generation = this.generation;
    const projectId = this.projectId;
    this.selectedImportSource.set(connectionId);
    this.opportunityRequest++;
    this.opportunityLoading.set(false);
    this.opportunityError.set(false);
    this.opportunityPreview.set(null);
    this.importHistory.set([]);
    this.importHistoryError.set(false);
    this.importHistoryLoading.set(true);
    try {
      const result = await this.api.sourceImportHistory(this.organizationId, projectId, connectionId);
      if (generation !== this.generation || this.selectedImportSource() !== connectionId) return;
      const records = result.body['imports'];
      if (result.status !== 200 || result.body['project_id'] !== projectId || result.body['connection_id'] !== connectionId
        || !Array.isArray(records) || !records.every((record) => record && typeof record === 'object'
          && ['id', 'rows_seen', 'rows_imported', 'row_errors'].every((field) => typeof record[field] === 'number'
            && Number.isSafeInteger(record[field]) && record[field] >= 0)
          && ['created_at', 'export_shape', 'status', 'coverage_state', 'date_start', 'date_end', 'source_completeness']
            .every((field) => typeof record[field] === 'string'))
        || typeof result.body['has_more'] !== 'boolean') {
        this.importHistoryError.set(true);
        return;
      }
      this.importHistory.set(records);
      this.importHistoryTruncated.set(result.body['has_more']);
    } catch {
      if (generation === this.generation && this.selectedImportSource() === connectionId) this.importHistoryError.set(true);
    } finally {
      if (generation === this.generation && this.selectedImportSource() === connectionId) this.importHistoryLoading.set(false);
    }
  }

  async loadOpportunityPreview(connectionId: number, importId: number) {
    if (this.selectedImportSource() !== connectionId || !this.importHistory().some((row) => row.id === importId
      && row.status === 'succeeded' && row.coverage_state === 'complete'
      && ['query', 'page'].includes(row.export_shape))) return;
    const generation = this.generation;
    const requestId = ++this.opportunityRequest;
    this.opportunityLoading.set(true);
    this.opportunityError.set(false);
    this.opportunityPreview.set(null);
    try {
      const response = await this.api.sourceOpportunityPreview(this.organizationId, this.projectId,
        connectionId, importId);
      if (generation !== this.generation || requestId !== this.opportunityRequest
        || this.selectedImportSource() !== connectionId) return;
      if (response.status !== 200 || response.body['project_id'] !== this.projectId
        || response.body['connection_id'] !== connectionId
        || !isOpportunityPreview(response.body, importId)) throw new Error();
      this.opportunityPreview.set(response.body);
    } catch {
      if (generation === this.generation && requestId === this.opportunityRequest) this.opportunityError.set(true);
    } finally {
      if (generation === this.generation && requestId === this.opportunityRequest) this.opportunityLoading.set(false);
    }
  }

  canRecordOpportunityPreview() {
    const selected = this.selectedImportSource();
    const preview = this.opportunityPreview();
    return !!(this.canManage() && selected && preview && this.sources().some((source) => source.id === selected
      && source.state === 'active' && source.scope_current && source.csv_import_supported));
  }

  async recordOpportunityCandidates(connectionId: number, importId: number) {
    if (!this.canRecordOpportunityPreview() || this.selectedImportSource() !== connectionId
      || this.opportunityPreview()?.window.import_id !== importId || this.findingsBusy() !== null) return;
    const generation = this.generation;
    this.findingsBusy.set(importId);
    this.clearStatus();
    try {
      const response = await this.api.recordImportFindings(this.organizationId, this.projectId, connectionId, importId);
      if (generation !== this.generation || this.selectedImportSource() !== connectionId) return;
      const ids = response.body['finding_ids'];
      if (response.status !== 201 || response.body['project_id'] !== this.projectId
        || response.body['connection_id'] !== connectionId || response.body['import_id'] !== importId
        || response.body['status'] !== 'recorded_candidate_evidence_not_prioritized'
        || !Array.isArray(ids) || ids.length > 100 || !ids.every(positiveInteger)) throw new Error();
      this.setDraftMessage(`${ids.length} immutable candidate finding observations recorded; none was prioritized or approved automatically.`,
        `${ids.length} değişmez aday bulgu gözlemi kaydedildi; hiçbiri otomatik olarak önceliklendirilmedi veya onaylanmadı.`);
      await this.loadFindings();
    } catch {
      if (generation === this.generation) this.showError('Candidate finding outcome unknown. Refresh finding evidence before retrying.');
    } finally {
      if (generation === this.generation) this.findingsBusy.set(null);
    }
  }

  async recordQueryChanges(event: Event, connectionId: number, dimension: 'query' | 'page' = 'query') {
    event.preventDefault();
    if (!this.canManage() || this.findingsBusy() !== null || this.selectedImportSource() !== connectionId
      || !this.sources().some((source) => source.id === connectionId && source.state === 'active' && source.scope_current)) return;
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    const data = new FormData(form);
    const previous = Number(data.get('previous'));
    const current = Number(data.get('current'));
    const eligible = (id: number) => this.importHistory().some((record) => record.id === id
      && record.export_shape === dimension && record.status === 'succeeded' && record.coverage_state === 'complete');
    if (!eligible(previous) || !eligible(current) || previous === current) {
      this.showError('Select two different complete query exports.');
      return;
    }
    const generation = this.generation;
    this.findingsBusy.set(current);
    this.clearStatus();
    try {
      const response = dimension === 'query'
        ? await this.api.recordQueryChangeFindings(this.organizationId, this.projectId, connectionId, previous, current)
        : await this.api.recordPageChangeFindings(this.organizationId, this.projectId, connectionId, previous, current);
      if (generation !== this.generation || this.selectedImportSource() !== connectionId) return;
      const ids = response.body['finding_ids'];
      if (response.status !== 201 || response.body['project_id'] !== this.projectId
        || response.body['connection_id'] !== connectionId || response.body['status'] !== 'recorded_candidate_evidence_not_prioritized'
        || !Array.isArray(ids) || ids.length > 100 || !ids.every(positiveInteger)) throw new Error();
      this.setDraftMessage(`${ids.length} comparable observed ${dimension}-change candidates recorded; missing rows remain unknown and no action was approved.`,
        `${ids.length} karşılaştırılabilir gözlenen ${dimension === 'query' ? 'sorgu' : 'sayfa'} değişimi adayı kaydedildi; eksik satırlar bilinmiyor ve hiçbir aksiyon onaylanmadı.`);
      await this.loadFindings();
    } catch {
      if (generation === this.generation) this.showError('Query comparison unavailable or outcome unknown. Refresh findings before retrying.');
    } finally {
      if (generation === this.generation) this.findingsBusy.set(null);
    }
  }

  async loadFindings() {
    const generation = this.generation;
    const requestId = ++this.findingsRequest;
    this.findingsLoading.set(true);
    this.findingsError.set(false);
    this.findings.set([]); this.findingsLoaded.set(false); this.findingsTruncated.set(false);
    try {
      const response = await this.api.projectFindings(this.organizationId, this.projectId);
      if (generation !== this.generation || requestId !== this.findingsRequest) return;
      const rows = response.body['findings'];
      if (response.status !== 200 || response.body['project_id'] !== this.projectId
        || !Array.isArray(rows) || rows.length > 50 || !rows.every(isFindingInfo)
        || typeof response.body['has_more'] !== 'boolean') throw new Error();
      this.findings.set(rows);
      this.findingsTruncated.set(response.body['has_more'] as boolean);
      this.findingsLoaded.set(true);
    } catch {
      if (generation === this.generation && requestId === this.findingsRequest) this.findingsError.set(true);
    } finally {
      if (generation === this.generation && requestId === this.findingsRequest) this.findingsLoading.set(false);
    }
  }

  async submitFindingReview(event: SubmitEvent, finding: FindingInfo) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!this.canManage() || !finding.source_current || (!finding.source_metric_id && !finding.source_indexation_id)
      || !this.findings().some((item) => item.id === finding.id) || this.findingsBusy() !== null
      || !form.reportValidity()) return;
    const fields = new FormData(form);
    const reason = String(fields.get('reason')).trim();
    const generation = this.generation;
    const expectedRevision = finding.review?.revision || 0;
    this.findingsBusy.set(finding.id);
    this.clearStatus();
    try {
      const response = await this.api.reviewFinding(this.organizationId, this.projectId, finding.id,
        expectedRevision, String(fields.get('priority')), String(fields.get('effort')),
        String(fields.get('relevance')), reason);
      if (generation !== this.generation) return;
      const review = response.body['review'];
      if (response.status !== 201 || response.body['project_id'] !== this.projectId
        || response.body['finding_id'] !== finding.id || response.body['approved_action'] !== null
        || !isOpportunityReview(review) || review.revision !== expectedRevision + 1) throw new Error();
      this.findings.update((items) => items.map((item) => item.id === finding.id ? { ...item, review } : item));
      this.message.set('Human opportunity review recorded as a revision; no recommendation or site change approved.');
    } catch {
      if (generation === this.generation) {
        this.showError('Opportunity review changed or could not be saved. Refresh findings before retrying.');
        void this.loadFindings();
      }
    } finally {
      if (generation === this.generation) this.findingsBusy.set(null);
    }
  }

  async createCsvSource(event: SubmitEvent) {
    event.preventDefault();
    const form = event.target as HTMLFormElement;
    if (!this.canManage() || this.csvBusy() || !form.reportValidity()) return;
    const property = String(new FormData(form).get('property') || '');
    if (![this.project()!.canonical_origin, ...this.project()!.aliases].includes(property)) return;
    const generation = this.generation;
    this.csvBusy.set(true); this.clearStatus();
    try {
      const result = await this.api.createCsvSource(this.organizationId, this.projectId, property);
      if (generation !== this.generation) return;
      if (result.status !== 200 || result.body['project_id'] !== this.projectId || result.body['property'] !== property
        || !positiveInteger(result.body['id']) || !['active', 'disconnected', 'unavailable'].includes(result.body['state'] as string)) {
        this.showError('CSV source setup was not acknowledged. Refresh source status before retrying.');
      } else this.message.set('Local CSV source recorded. Choose the export and its original metadata below.');
      await this.loadSources(generation, this.organizationId, this.projectId);
    } catch {
      if (generation === this.generation) this.showError('Source setup outcome unknown. Reload source status before retrying.');
    } finally { if (generation === this.generation) this.csvBusy.set(false); }
  }

  async uploadCsv(event: SubmitEvent, connectionId: number) {
    event.preventDefault();
    const form = event.target as HTMLFormElement;
    const source = this.sources().find((item) => item.id === connectionId);
    if (!this.canManage() || this.csvBusy() || this.pendingCsv() || !form.reportValidity()
      || !source || !source.scope_current || source.state !== 'active' || !source.csv_import_supported
      || source.provider !== 'google_search_console' || source.credential_status !== 'not_connected') return;
    const fields = new FormData(form);
    const file = fields.get('file');
    if (!(file instanceof Blob) || file.size < 1 || file.size > 1024 * 1024 || fields.get('authorize') !== 'on') {
      return this.showError('Choose a nonempty CSV within 1 MiB and authorize this export.');
    }
    const headers = { 'X-CSV-Start': String(fields.get('start') || ''), 'X-CSV-End': String(fields.get('end') || ''),
      'X-CSV-Search-Type': String(fields.get('search_type') || ''),
      'X-CSV-Date-Granularity': String(fields.get('date_granularity') || ''), 'X-CSV-Authorization': 'true' };
    const generation = this.generation;
    this.csvBusy.set(true); this.clearStatus();
    try {
      const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
      if (generation !== this.generation) return;
      const checksum = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
      this.pendingCsv.set({ connectionId, file, checksum, headers });
      form.reset();
    } catch {
      if (generation === this.generation) this.showError('CSV could not be read. Choose the export again; no upload was sent.');
    } finally { if (generation === this.generation) this.csvBusy.set(false); }
    if (generation === this.generation && this.pendingCsv()) await this.retryCsvUpload();
  }

  async retryCsvUpload() {
    const pending = this.pendingCsv();
    if (!pending || !this.canManage() || this.csvBusy()) return;
    const generation = this.generation;
    this.csvBusy.set(true); this.clearStatus();
    try {
      const result = await this.api.uploadSearchConsoleCsv(this.organizationId, this.projectId,
        pending.connectionId, pending.file, pending.headers);
      if (generation !== this.generation) return;
      const job = result.body['job'] as Record<string, unknown> | undefined;
      if (result.status === 202 && result.body['project_id'] === this.projectId
        && result.body['connection_id'] === pending.connectionId && job && positiveInteger(job['id'])
        && job['project_id'] === this.projectId && job['connection_id'] === pending.connectionId
        && job['source_checksum'] === pending.checksum && job['date_start'] === pending.headers['X-CSV-Start']
        && job['date_end'] === pending.headers['X-CSV-End'] && job['search_type'] === pending.headers['X-CSV-Search-Type']
        && job['date_granularity'] === (pending.headers['X-CSV-Date-Granularity'] === 'day' ? 'day' : null)
        && ['queued', 'running', 'waiting_provider', 'succeeded', 'partially_succeeded', 'failed', 'cancelled'].includes(job['status'] as string)) {
        this.pendingCsv.set(null);
        const message = `CSV job ${job['id']} acknowledged (${job['status']}). Check job progress, then refresh import history. Export coverage remains unknown.`;
        this.message.set(message);
        this.csvAcknowledgment.set({ id: job['id'] as number, status: job['status'] as string, message });
      } else if ([400, 401, 403, 404, 409, 413, 429].includes(result.status)) {
        this.pendingCsv.set(null);
        this.showError('CSV import rejected. Check source access, dates/type, file limits and import allowance before choosing it again.');
      } else this.showError('Upload acknowledgment is uncertain. Retry only the same frozen CSV request or inspect project jobs.');
    } catch {
      if (generation === this.generation) this.showError('Upload outcome unknown. Retry only the same frozen CSV request or inspect project jobs.');
    } finally { if (generation === this.generation) this.csvBusy.set(false); }
  }

  async setCsvSource(connectionId: number, enabled: boolean) {
    const source = this.sources().find((item) => item.id === connectionId);
    if (!this.canManage() || !source || !source.csv_import_supported || source.credential_status !== 'not_connected'
      || source.state === 'unavailable' || (enabled && !source.scope_current) || this.changingSource() !== null) return;
    const generation = this.generation;
    const projectId = this.projectId;
    this.changingSource.set(connectionId);
    this.clearStatus();
    try {
      const result = await this.api.setCsvSourceState(this.organizationId, projectId, connectionId, enabled);
      if (generation !== this.generation) return;
      const state = enabled ? 'active' : 'disconnected';
      if (result.status !== 200 || result.body['project_id'] !== projectId
        || result.body['id'] !== connectionId || result.body['state'] !== state) {
        this.showError('CSV source state could not be changed. Reload to check its current scope and access.');
        return;
      }
      this.sources.update((items) => items.map((item) => item.id === connectionId ? { ...item, state } : item));
      this.message.set(enabled ? 'CSV source record re-enabled; OAuth and API sync remain unavailable.'
        : 'CSV source disabled. Prior import evidence remains available.');
    } catch {
      if (generation === this.generation) this.showError('Source state outcome unknown. Reload before retrying.');
    } finally {
      if (generation === this.generation) this.changingSource.set(null);
    }
  }

  showQueries(connectionId: number) {
    if (!this.sources().some((source) => source.id === connectionId)) return;
    this.selectedSource.set(connectionId);
    this.queries.set([]);
    this.nextBefore.set(null);
    this.historyQueryId.set(null);
    this.queryFilter.set('all');
    void this.loadQueries(connectionId);
  }

  setQueryFilter(event: Event) {
    const value = (event.target as HTMLSelectElement).value;
    if (['all', 'branded', 'non_branded', 'unclassified'].includes(value)) this.queryFilter.set(value);
  }

  visibleQueries() {
    return this.queryFilter() === 'all' ? this.queries() : this.queries().filter((row) => row.label === this.queryFilter());
  }

  async loadQueries(connectionId: number, before?: number) {
    if (this.selectedSource() !== connectionId || this.queryLoading()) return;
    const generation = this.generation;
    const projectId = this.projectId;
    this.queryLoading.set(true);
    this.queryError.set(false);
    try {
      const result = await this.api.sourceQueries(this.organizationId, projectId, connectionId, before);
      if (generation !== this.generation || this.selectedSource() !== connectionId) return;
      const rows = result.body['queries'];
      if (result.status !== 200 || result.body['project_id'] !== projectId || result.body['connection_id'] !== connectionId
        || !Array.isArray(rows) || !rows.every(isSourceQuery) || typeof result.body['method'] !== 'string'
        || typeof result.body['alias_revision'] !== 'number' || typeof result.body['has_more'] !== 'boolean'
        || (result.body['has_more'] && !positiveInteger(Number(result.body['next_before'])))) {
        this.queryError.set(true);
        return;
      }
      if (before && (result.body['alias_revision'] !== this.aliasRevision() || result.body['method'] !== this.queryMethod())) {
        this.queryError.set(true);
        this.queries.set([]);
        this.nextBefore.set(null);
        return;
      }
      this.queryMethod.set(result.body['method']);
      this.aliasRevision.set(result.body['alias_revision']);
      this.queries.set(before ? [...this.queries(), ...rows] : rows);
      this.nextBefore.set(result.body['has_more'] ? Number(result.body['next_before']) : null);
    } catch {
      if (generation === this.generation && this.selectedSource() === connectionId) this.queryError.set(true);
    } finally {
      if (generation === this.generation && this.selectedSource() === connectionId) this.queryLoading.set(false);
    }
  }

  async saveBrandReview(event: SubmitEvent, connectionId: number, item: SourceQueryInfo) {
    event.preventDefault();
    if (!this.canReview() || this.reviewing() !== null || this.selectedSource() !== connectionId) return;
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity()) return;
    const fields = new FormData(form);
    const label = String(fields.get('label')) as SourceQueryInfo['label'];
    const reason = String(fields.get('reason') || '').trim();
    if (!['branded', 'non_branded', 'unclassified'].includes(label) || !reason) return;
    const generation = this.generation;
    const projectId = this.projectId;
    this.reviewing.set(item.id);
    this.clearStatus();
    try {
      const result = await this.api.reviewSourceQuery(this.organizationId, projectId, connectionId,
        item.id, item.review_revision, label, reason);
      if (generation !== this.generation || this.selectedSource() !== connectionId) return;
      const review = result.body['review'];
      if (result.status !== 201 || !review || typeof review !== 'object'
        || (review as Record<string, unknown>)['revision'] !== item.review_revision + 1
        || (review as Record<string, unknown>)['label'] !== label) {
        this.showError(result.status === 409 ? 'This query was reviewed elsewhere. Reload its source before correcting it.'
          : 'This correction could not be saved. Check your access and reload the source.');
        return;
      }
      this.message.set('Query correction saved with its review history.');
      this.queries.update((rows) => rows.map((row) => row.id === item.id
        ? { ...row, label, review_revision: item.review_revision + 1 } : row));
      this.historyQueryId.set(null);
      const reasonField = form.elements.namedItem('reason');
      if (reasonField instanceof HTMLInputElement) reasonField.value = '';
    } catch {
      if (generation === this.generation && this.selectedSource() === connectionId) this.showError('Correction outcome unknown. Reload the source before retrying.');
    } finally {
      if (generation === this.generation) this.reviewing.set(null);
    }
  }

  async showQueryHistory(connectionId: number, queryId: number) {
    if (this.selectedSource() !== connectionId || !this.queries().some((row) => row.id === queryId)) return;
    const generation = this.generation;
    const projectId = this.projectId;
    this.historyQueryId.set(queryId);
    this.history.set([]);
    this.historyError.set(false);
    this.historyLoading.set(true);
    try {
      const result = await this.api.sourceQueryHistory(this.organizationId, projectId, connectionId, queryId);
      if (generation !== this.generation || this.selectedSource() !== connectionId || this.historyQueryId() !== queryId) return;
      const reviews = result.body['reviews'];
      if (result.status !== 200 || result.body['project_id'] !== projectId
        || result.body['connection_id'] !== connectionId || result.body['query_id'] !== queryId
        || !Array.isArray(reviews) || !reviews.every((review) => review && typeof review === 'object'
          && typeof review['revision'] === 'number' && typeof review['reason'] === 'string'
          && typeof review['label'] === 'string' && typeof review['created_at'] === 'string')
        || typeof result.body['has_more'] !== 'boolean') {
        this.historyError.set(true);
        return;
      }
      this.history.set(reviews);
      this.historyTruncated.set(result.body['has_more']);
    } catch {
      if (generation === this.generation && this.historyQueryId() === queryId) this.historyError.set(true);
    } finally {
      if (generation === this.generation && this.historyQueryId() === queryId) this.historyLoading.set(false);
    }
  }

  show(step: OnboardingStep) {
    if (step === 'complete' && this.configuration()?.current_step !== 'complete') return;
    this.clearStatus();
    this.moveTo(step);
  }

  lines(values: string[]) {
    return values.join('\n');
  }

  sourceLabel(value: ProjectConfigurationInfo['source_state']) {
    return ({
      not_selected: 'Not selected', disconnected: 'Google OAuth preferred; authorize separately',
      awaiting_import: 'CSV import selected; see existing source status',
      skipped: 'Skipped for now', synthetic_demo: 'Synthetic demo selected',
    })[value];
  }

  async saveBasics(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity()) return;
    const fields = new FormData(form);
    const keepComplete = this.configuration()?.current_step === 'complete';
    if (await this.save({
      target_country: value(fields, 'target-country'),
      target_languages: list(fields, 'target-languages'),
      business_goal: value(fields, 'business-goal'),
      timezone: value(fields, 'timezone'),
      current_step: keepComplete ? 'complete' : 'source',
    }, 'Website, market, language, and goal saved.')) this.moveTo('source');
  }

  async saveSource(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity()) return;
    const source = value(new FormData(form), 'source');
    if (!isSourceChoice(source)) return this.showError('Choose a valid source path.');
    const keepComplete = this.configuration()?.current_step === 'complete';
    if (await this.save({
      source_choice: source,
      current_step: keepComplete ? 'complete' : 'advanced',
    }, 'Source preference saved. No connection, import, or job was started.')) this.moveTo('advanced');
  }

  async saveAdvanced(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity()) return;
    const fields = new FormData(form);
    const crawlLimit = value(fields, 'crawl-page-limit');
    const queryVariantLimit = Number(value(fields, 'query-variant-limit'));
    if (await this.save({
      audience: value(fields, 'audience'), offer: value(fields, 'offer'), brand_voice: value(fields, 'brand-voice'),
      seed_topics: list(fields, 'seed-topics'), prohibited_claims: list(fields, 'prohibited-claims'),
      conversion_goals: list(fields, 'conversion-goals'), brand_aliases: list(fields, 'brand-aliases'),
      measurement_notes: value(fields, 'measurement-notes'),
      competitor_origins: list(fields, 'competitors'), research_allowed_origins: list(fields, 'research-allowed'),
      rss_feed_urls: list(fields, 'rss-feeds'),
      research_blocked_origins: list(fields, 'research-blocked'), crawl_page_limit: crawlLimit ? Number(crawlLimit) : null,
      ignored_query_parameters: list(fields, 'ignored-query-parameters'),
      pagination_query_parameters: list(fields, 'pagination-query-parameters'),
      facet_query_parameters: list(fields, 'facet-query-parameters'), query_variant_limit: queryVariantLimit,
      business_locations: list(fields, 'business-locations'), service_areas: list(fields, 'service-areas'),
      contact_details: value(fields, 'contact-details'), business_hours: value(fields, 'business-hours'),
      profile_urls: list(fields, 'profile-urls'), local_eligibility_notes: value(fields, 'eligibility-notes'),
      current_step: 'complete',
    }, 'Project setup saved. No live work or commercial access was started.')) this.moveTo('complete');
  }

  private async load() {
    const generation = ++this.generation;
    this.loading.set(true);
    this.saving.set(false);
    this.denied.set(false);
    this.project.set(null);
    this.configuration.set(null);
    this.clearStatus();
    try {
      const result = await this.api.projectOnboarding(this.organizationId, this.projectId);
      if (generation !== this.generation) return;
      if (result.status === 401) return void this.router.navigateByUrl('/account/login');
      if (result.status === 403 || result.status === 404) {
        this.denied.set(true);
        return;
      }
      const project = readProject(result.body['project']);
      const configuration = readConfiguration(result.body['configuration']);
      if (result.status !== 200 || !project || !configuration
        || project.organization_id !== this.organizationId || project.id !== this.projectId
        || configuration.project_id !== this.projectId || configuration.canonical_origin !== project.canonical_origin) {
        return this.showError('Project onboarding is temporarily unavailable. Return to the workspace and retry.');
      }
      this.project.set(project);
      this.configuration.set(configuration);
      this.view.set(configuration.current_step);
      void this.loadSources(generation, this.organizationId, this.projectId);
      if (this.canManage()) {
        void this.loadGrants(generation, this.organizationId, this.projectId);
        void this.loadGA4Grants();
      }
    } catch {
      if (generation === this.generation) this.showError('Project onboarding is temporarily unavailable. Return to the workspace and retry.');
    } finally {
      if (generation === this.generation) this.loading.set(false);
    }
  }

  private async loadSources(generation: number, organizationId: number, projectId: number) {
    if (generation !== this.generation) return;
    const request = ++this.sourcesRequest;
    this.sources.set([]); this.sourcesTruncated.set(false);
    this.sourceLoading.set(true);
    this.sourceError.set(false);
    try {
      const result = await this.api.projectSources(organizationId, projectId);
      if (generation !== this.generation || request !== this.sourcesRequest) return;
      const sources = result.body['sources'];
      if (result.status !== 200 || result.body['project_id'] !== projectId || !Array.isArray(sources)
        || !sources.every(isProjectSource) || typeof result.body['has_more'] !== 'boolean') {
        this.sourceError.set(true);
        return;
      }
      this.sources.set(sources);
      this.sourcesTruncated.set(result.body['has_more']);
    } catch {
      if (generation === this.generation && request === this.sourcesRequest) this.sourceError.set(true);
    } finally {
      if (generation === this.generation && request === this.sourcesRequest) this.sourceLoading.set(false);
    }
  }

  private async loadGrants(generation: number, organizationId: number, projectId: number) {
    if (generation !== this.generation) return;
    const request = ++this.grantsRequest;
    this.grants.set([]); this.grantsTruncated.set(false);
    this.grantLoading.set(true);
    this.grantError.set(false);
    try {
      const result = await this.api.googleOAuthGrants(organizationId, projectId);
      if (generation !== this.generation || request !== this.grantsRequest) return;
      const grants = result.body['grants'];
      if (result.status !== 200 || result.body['project_id'] !== projectId || !Array.isArray(grants)
        || !grants.every(isGoogleOAuthGrant) || typeof result.body['has_more'] !== 'boolean') {
        this.grantError.set(true);
        return;
      }
      this.grants.set(grants);
      this.grantsTruncated.set(result.body['has_more']);
    } catch {
      if (generation === this.generation && request === this.grantsRequest) this.grantError.set(true);
    } finally {
      if (generation === this.generation && request === this.grantsRequest) this.grantLoading.set(false);
    }
  }

  private async save(changes: Record<string, unknown>, success: string) {
    const configuration = this.configuration();
    if (!configuration || !this.canManage() || this.saving()) return false;
    const generation = this.generation;
    const organizationId = this.organizationId;
    const projectId = this.projectId;
    this.saving.set(true);
    this.clearStatus();
    try {
      const result = await this.api.updateProjectOnboarding(organizationId, projectId, {
        revision: configuration.revision,
        ...changes,
      });
      if (generation !== this.generation || organizationId !== this.organizationId || projectId !== this.projectId) return false;
      if (result.status === 401) {
        await this.router.navigateByUrl('/account/login');
        return false;
      }
      if (result.status === 403 || result.status === 404) {
        this.project.set(null);
        this.configuration.set(null);
        this.denied.set(true);
        return false;
      }
      const updated = readConfiguration(result.body['configuration']);
      if (!updated || updated.project_id !== projectId || updated.canonical_origin !== this.project()?.canonical_origin) {
        this.showError('Project setup could not be saved. Check the fields and try again.');
        return false;
      }
      if (result.status === 409) {
        this.configuration.set(updated);
        this.showError('This setup changed in another session. The latest saved version is now loaded; review it before saving again.');
        return false;
      }
      if (result.status !== 200) {
        this.showError('Project setup could not be saved. Check the fields and try again.');
        return false;
      }
      this.configuration.set(updated);
      this.message.set(success);
      return true;
    } catch {
      if (generation === this.generation && organizationId === this.organizationId && projectId === this.projectId) {
        this.showError('The save outcome is unknown. Retry safely; a completed earlier save will reload as a revision conflict.');
      }
      return false;
    } finally {
      if (generation === this.generation && organizationId === this.organizationId && projectId === this.projectId) {
        this.saving.set(false);
      }
    }
  }

  private moveTo(step: OnboardingStep) {
    this.focusStep = true;
    this.view.set(step);
    if (this.stepHeading?.nativeElement.id.startsWith(step)) {
      this.focusStep = false;
      this.stepHeading.nativeElement.focus();
    }
  }

  private clearStatus() {
    this.csvAcknowledgment.set(null);
    this.messageDraft.set(null);
    this.message.set('');
    this.error.set('');
  }

  private showError(message: string) {
    this.error.set(message);
    const generation = this.generation;
    setTimeout(() => {
      if (!this.destroyRef.destroyed && generation === this.generation && this.error() === message)
        this.errorSummary?.nativeElement.focus();
    });
  }
}

function value(fields: FormData, name: string) {
  return String(fields.get(name) || '').trim();
}

function list(fields: FormData, name: string) {
  return value(fields, name).split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
}

function isSourceChoice(value: string): value is OnboardingSourceChoice {
  return ['connect_search_console', 'import_search_console', 'skip', 'synthetic_demo'].includes(value);
}

function positiveInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0;
}

function isOpportunityPreview(value: unknown, importId: number): value is OpportunityPreview {
  if (!value || typeof value !== 'object') return false;
  const preview = value as Record<string, unknown>;
  const window = preview['window'] as Record<string, unknown> | null;
  const coverage = preview['coverage'] as Record<string, unknown> | null;
  const thresholds = preview['thresholds'] as Record<string, unknown> | null;
  const candidates = preview['candidates'];
  return preview['method'] === 'gsc-csv-opportunity-v1'
    && typeof preview['dimension'] === 'string' && ['query', 'page'].includes(preview['dimension'])
    && typeof preview['property'] === 'string' && preview['property'].length <= 512
    && typeof preview['timezone'] === 'string' && typeof preview['market'] === 'string'
    && Array.isArray(preview['languages']) && preview['languages'].length <= 20
    && preview['languages'].every((language: unknown) => typeof language === 'string')
    && window !== null && typeof window === 'object' && window['import_id'] === importId
    && typeof window['start'] === 'string' && typeof window['end'] === 'string'
    && coverage !== null && typeof coverage === 'object' && coverage['file'] === 'complete'
    && coverage['provider_top_rows'] === 'incomplete_unknown' && coverage['hidden_queries'] === 'unknown'
    && thresholds !== null && typeof thresholds === 'object'
    && Array.isArray(thresholds['position_inclusive']) && thresholds['position_inclusive'].length === 2
    && typeof thresholds['min_impressions'] === 'number' && typeof thresholds['ctr_below'] === 'string'
    && typeof preview['truncated_candidates'] === 'boolean'
    && Array.isArray(candidates) && candidates.length <= 100
    && candidates.every((raw: unknown) => {
      if (!raw || typeof raw !== 'object') return false;
      const item = raw as Record<string, unknown>;
      return typeof item['detector'] === 'string' && ['web_position_4_to_20_candidate', 'web_high_impressions_low_ctr_candidate']
        .includes(item['detector']) && positiveInteger(item['observation_id'])
        && ((typeof item['query'] === 'string' && item['query'].length <= 1000 && item['page'] === null)
          || (item['query'] === null && typeof item['page'] === 'string' && item['page'].length <= 2048
              && !/[?#]/.test(item['page'])))
        && typeof item['clicks'] === 'number' && typeof item['impressions'] === 'number'
        && typeof item['ctr'] === 'string' && typeof item['position'] === 'string'
        && item['confidence'] === 'candidate_not_proven_business_value';
    });
}

function isOpportunityReview(value: unknown): value is NonNullable<FindingInfo['review']> {
  if (!value || typeof value !== 'object') return false;
  const review = value as Record<string, unknown>;
  return positiveInteger(review['id']) && positiveInteger(review['revision'])
    && typeof review['priority'] === 'string' && ['unprioritized', 'low', 'medium', 'high'].includes(review['priority'])
    && typeof review['estimated_effort'] === 'string' && ['unknown', 'small', 'medium', 'large'].includes(review['estimated_effort'])
    && typeof review['business_relevance'] === 'string' && ['unknown', 'low', 'medium', 'high'].includes(review['business_relevance'])
    && typeof review['review_reason'] === 'string' && review['review_reason'].length <= 240;
}

function isGA4GrantInfo(value: unknown): value is GA4GrantInfo {
  if (!value || typeof value !== 'object') return false;
  const row = value as Record<string, unknown>;
  return positiveInteger(row['id']) && Number.isSafeInteger(row['revision']) && Number(row['revision']) >= 0
    && typeof row['state'] === 'string'
    && ['pending_selection', 'active', 'revocation_pending', 'reconnect_required', 'revoked'].includes(row['state'])
    && typeof row['property_id'] === 'string' && row['property_id'].length <= 20
    && Array.isArray(row['selected_origins']) && row['selected_origins'].length <= 20
    && row['selected_origins'].every((origin: unknown) => typeof origin === 'string' && origin.length <= 512)
    && typeof row['scope_current'] === 'boolean' && typeof row['source_status'] === 'string'
    && typeof row['verified_at'] === 'string' && row['verified_at'].length <= 64;
}

function isGA4JobInfo(value: unknown): value is GA4JobInfo {
  if (!value || typeof value !== 'object') return false;
  const row = value as Record<string, unknown>;
  return positiveInteger(row['id']) && typeof row['status'] === 'string'
    && ['queued', 'running', 'partially_succeeded', 'succeeded', 'failed', 'cancelled'].includes(row['status'])
    && typeof row['day'] === 'string' && row['day'].length === 10
    && typeof row['report_kind'] === 'string' && ['all_channels', 'organic_search'].includes(row['report_kind'])
    && typeof row['hostname'] === 'string' && row['hostname'].length <= 253
    && typeof row['error_category'] === 'string' && row['error_category'].length <= 64
    && Number.isSafeInteger(row['requests_attempted']) && Number(row['requests_attempted']) >= 0
    && Number(row['requests_attempted']) <= 5 && Number.isSafeInteger(row['pages_recorded'])
    && Number(row['pages_recorded']) >= 0 && Number(row['pages_recorded']) <= 2
    && typeof row['source_coverage'] === 'string'
    && (row['sampling_or_threshold_gaps'] === null || typeof row['sampling_or_threshold_gaps'] === 'boolean');
}

function isGA4PageInfo(value: unknown): value is GA4PageInfo {
  if (!value || typeof value !== 'object') return false;
  const item = value as Record<string, unknown>;
  const result = item['result'];
  if (!positiveInteger(item['id']) || ![0, 100].includes(Number(item['offset']))
    || !['all_channels', 'organic_search'].includes(String(item['report_kind']))
    || typeof item['collected_at'] !== 'string' || item['collected_at'].length > 64
    || !result || typeof result !== 'object') return false;
  const report = result as Record<string, unknown>;
  const rows = report['rows'];
  const coverage = report['coverage'];
  return typeof report['day'] === 'string' && typeof report['timezone'] === 'string'
    && report['report_kind'] === item['report_kind']
    && typeof report['currency'] === 'string' && report['currency'].length === 3
    && Array.isArray(rows) && rows.length <= 100 && rows.every((row: unknown) => {
      if (!row || typeof row !== 'object') return false;
      const fields = row as Record<string, unknown>;
      return typeof fields['hostname'] === 'string' && fields['hostname'].length <= 253
        && typeof fields['path'] === 'string' && fields['path'].length <= 512
        && !/[?#]/.test(fields['path']) && Number.isSafeInteger(fields['sessions'])
        && Number(fields['sessions']) >= 0 && typeof fields['key_events'] === 'string'
        && typeof fields['total_revenue'] === 'string'
        && (item['report_kind'] !== 'organic_search'
          || fields['session_default_channel_group'] === 'Organic Search');
    }) && coverage !== null && typeof coverage === 'object'
    && ['sampled', 'thresholded', 'other_row_loss', 'instrumentation_verified'].every((key) =>
      typeof (coverage as Record<string, unknown>)[key] === 'boolean')
    && typeof (coverage as Record<string, unknown>)['full_activity_coverage'] === 'string'
    && typeof (coverage as Record<string, unknown>)['acquisition_scope'] === 'string'
    && Number.isSafeInteger((coverage as Record<string, unknown>)['omitted_foreign_or_parameterized_rows']);
}

function isGA4QualityInfo(value: unknown): value is GA4QualityInfo {
  if (!value || typeof value !== 'object') return false;
  const item = value as Record<string, unknown>;
  const definitions = item['definitions'];
  return positiveInteger(item['id']) && positiveInteger(item['revision'])
    && typeof item['property_id'] === 'string' && item['property_id'].length <= 20
    && typeof item['currency'] === 'string' && item['currency'].length === 3
    && typeof item['timezone'] === 'string' && item['timezone'].length <= 64
    && Array.isArray(definitions) && definitions.length <= 10 && definitions.every((row: unknown) => {
      if (!row || typeof row !== 'object') return false;
      const mapped = row as Record<string, unknown>;
      return typeof mapped['goal'] === 'string' && mapped['goal'].length <= 80
        && typeof mapped['event_name'] === 'string' && mapped['event_name'].length <= 40
        && typeof mapped['value_definition'] === 'string' && mapped['value_definition'].length <= 120;
    }) && typeof item['instrumentation_state'] === 'string'
    && ['unverified', 'manual_reviewed'].includes(item['instrumentation_state'])
    && typeof item['event_quality_state'] === 'string'
    && ['not_checked', 'suspected_missing', 'suspected_duplicate', 'suspected_both', 'manual_review_no_concern']
      .includes(item['event_quality_state'])
    && ['instrumentation_notes', 'attribution_notes', 'consent_notes', 'tracking_change_notes']
      .every((field) => typeof item[field] === 'string' && (item[field] as string).length <= 1000)
    && typeof item['created_at'] === 'string' && item['created_at'].length <= 64;
}

function isFindingInfo(value: unknown): value is FindingInfo {
  if (!value || typeof value !== 'object') return false;
  const finding = value as Record<string, unknown>;
  const evidence = finding['evidence'];
  return positiveInteger(finding['id']) && typeof finding['detector'] === 'string'
    && finding['detector'].length <= 80 && typeof finding['method_version'] === 'string'
    && finding['method_version'].length <= 64 && typeof finding['subject'] === 'string'
    && finding['subject'].length <= 2048
    && (finding['source_metric_id'] === null || positiveInteger(finding['source_metric_id']))
    && (finding['source_indexation_id'] === null || positiveInteger(finding['source_indexation_id']))
    && (finding['source_diagnostics_id'] === null || positiveInteger(finding['source_diagnostics_id']))
    && (finding['source_performance_id'] === null || positiveInteger(finding['source_performance_id']))
    && (finding['source_import_id'] === null || positiveInteger(finding['source_import_id']))
    && (finding['source_connection_id'] === null || positiveInteger(finding['source_connection_id']))
    && typeof finding['source_current'] === 'boolean' && typeof finding['confidence'] === 'string'
    && typeof finding['detected_at'] === 'string' && finding['detected_at'].length <= 64
    && evidence !== null && typeof evidence === 'object' && !Array.isArray(evidence)
    && (finding['review'] === null || isOpportunityReview(finding['review']));
}

function isIndexationReport(value: unknown, crawlId: unknown): value is IndexationReport {
  if (!value || typeof value !== 'object' || !positiveInteger(crawlId)) return false;
  const report = value as Record<string, unknown>;
  const coverage = report['coverage'];
  const rows = report['urls'];
  return report['crawl_run_id'] === crawlId && positiveInteger(report['diagnostics_id'])
    && coverage !== null && typeof coverage === 'object'
    && typeof (coverage as Record<string, unknown>)['state'] === 'string'
    && typeof (coverage as Record<string, unknown>)['engine_indexing_reports'] === 'string'
    && Array.isArray(rows) && rows.length <= 40 && rows.every((item: unknown) => {
      if (!item || typeof item !== 'object') return false;
      const row = item as Record<string, unknown>;
      return typeof row['url'] === 'string' && row['url'].length <= 2048
        && /^https?:\/\//.test(row['url']) && !/[?#]/.test(row['url'])
        && typeof row['crawlability'] === 'string'
        && Array.isArray(row['discovered_by']) && row['discovered_by'].length <= 10
        && row['discovered_by'].every((source: unknown) => typeof source === 'string')
        && Array.isArray(row['indexability_signals']) && row['indexability_signals'].length <= 20
        && row['indexability_signals'].every((signal: unknown) => typeof signal === 'string')
        && Array.isArray(row['fetch_observations']) && row['fetch_observations'].length <= 100
        && row['fetch_observations'].every((visit: unknown) => {
          if (!visit || typeof visit !== 'object') return false;
          const observed = visit as Record<string, unknown>;
          return (observed['status_code'] === null || typeof observed['status_code'] === 'number'
            && Number.isSafeInteger(observed['status_code']))
            && typeof observed['directive_state'] === 'string'
            && (observed['declared_canonical'] === null || typeof observed['declared_canonical'] === 'string');
        })
        && Array.isArray(row['engine_reports']) && row['engine_reports'].length <= 50
        && row['engine_reports'].every((engine: unknown) => {
          if (!engine || typeof engine !== 'object') return false;
          const result = engine as Record<string, unknown>;
          return ['provider', 'property', 'indexed_state', 'method', 'collected_at']
            .every((field) => typeof result[field] === 'string' && (result[field] as string).length <= 512)
            && (result['engine_selected_canonical'] === null || typeof result['engine_selected_canonical'] === 'string')
            && (result['declared_canonical'] === null || typeof result['declared_canonical'] === 'string')
            && (result['engine_last_crawl_at'] === null || typeof result['engine_last_crawl_at'] === 'string')
            && [true, false, null].includes(result['stale_relative_to_local_crawl'] as boolean | null)
            && Array.isArray(result['disagreement_candidates']) && result['disagreement_candidates'].length <= 20
            && result['disagreement_candidates'].every((item: unknown) => typeof item === 'string');
        });
    });
}

function readPerformanceJob(value: unknown): value is PerformanceJob {
  if (!value || typeof value !== 'object') return false;
  const job = value as Record<string, unknown>;
  return positiveInteger(job['id'])
    && typeof job['status'] === 'string'
    && ['queued', 'running', 'succeeded', 'failed', 'partially_succeeded', 'cancelled'].includes(job['status'])
    && typeof job['error_category'] === 'string' && job['error_category'].length <= 64
    && typeof job['target'] === 'string' && job['target'].length <= 2048
    && typeof job['grain'] === 'string' && ['page', 'origin'].includes(job['grain'])
    && typeof job['strategy'] === 'string' && ['mobile', 'desktop', 'tablet'].includes(job['strategy'])
    && Array.isArray(job['sources']) && job['sources'].length >= 1 && job['sources'].length <= 3
    && job['sources'].every((source: unknown) => typeof source === 'string' && ['psi_lab', 'crux_current', 'crux_history'].includes(source))
    && typeof job['requests_attempted'] === 'number' && Number.isSafeInteger(job['requests_attempted'])
    && job['requests_attempted'] >= 0 && job['requests_attempted'] <= 3
    && typeof job['sources_recorded'] === 'number' && Number.isSafeInteger(job['sources_recorded'])
    && job['sources_recorded'] >= 0 && job['sources_recorded'] <= 3
    && ['lab', 'field', 'coverage'].every((field) => typeof job[field] === 'string' && (job[field] as string).length <= 64);
}

function readPerformanceObservation(value: unknown): value is PerformanceObservation {
  if (!value || typeof value !== 'object') return false;
  const item = value as Record<string, unknown>;
  const result = item['result'];
  return positiveInteger(item['id'])
    && typeof item['source'] === 'string' && ['psi_lab', 'crux_current', 'crux_history'].includes(item['source'])
    && typeof item['collected_at'] === 'string' && item['collected_at'].length <= 64
    && result !== null && typeof result === 'object' && !Array.isArray(result)
    && typeof (result as Record<string, unknown>)['source'] === 'string'
    && ['pagespeed_insights', 'crux_api', 'crux_history_api'].includes((result as Record<string, unknown>)['source'] as string);
}

function isSyncJob(value: unknown): value is {id: number; status: string; error_category: string;
  pages_recorded: number; requests_attempted: number; source_coverage: string} {
  if (!value || typeof value !== 'object') return false;
  const job = value as Record<string, unknown>;
  return typeof job['id'] === 'number' && positiveInteger(job['id'])
    && typeof job['status'] === 'string'
    && ['queued', 'running', 'succeeded', 'failed', 'cancelled', 'partially_succeeded'].includes(job['status'])
    && typeof job['error_category'] === 'string' && typeof job['source_coverage'] === 'string'
    && ['pages_recorded', 'requests_attempted'].every((field) => typeof job[field] === 'number'
      && Number.isSafeInteger(job[field]) && (job[field] as number) >= 0);
}

function readCoverageJob(value: unknown): CoverageJob | null {
  if (!value || typeof value !== 'object') return null;
  const job = value as Record<string, unknown>;
  return typeof job['id'] === 'number' && positiveInteger(job['id'])
    && typeof job['status'] === 'string'
    && ['queued', 'running', 'succeeded', 'failed', 'cancelled', 'partially_succeeded'].includes(job['status'])
    && typeof job['error_category'] === 'string'
    && typeof job['inspection_url'] === 'string' && job['inspection_url'].length <= 2048
    && Number.isSafeInteger(job['requests_attempted']) && Number(job['requests_attempted']) >= 0
    && Number(job['requests_attempted']) <= 3
    && Array.isArray(job['sources_recorded']) && job['sources_recorded'].length <= 2
    && job['sources_recorded'].every((source: unknown) => typeof source === 'string' && ['inspection', 'sitemaps'].includes(source))
    && Array.isArray(job['results']) && job['results'].length <= 2
    && job['results'].every((item: unknown) => item && typeof item === 'object'
      && typeof (item as Record<string, unknown>)['source'] === 'string'
      && ['inspection', 'sitemaps'].includes((item as Record<string, unknown>)['source'] as string)
      && !!(item as Record<string, unknown>)['result']
      && typeof (item as Record<string, unknown>)['result'] === 'object')
    ? job as unknown as CoverageJob : null;
}

function readBackfillJob(value: unknown): BackfillJob | null {
  if (!value || typeof value !== 'object') return null;
  const job = value as Record<string, unknown>;
  return typeof job['id'] === 'number' && positiveInteger(job['id'])
    && typeof job['status'] === 'string' && ['running', 'paused', 'succeeded'].includes(job['status'])
    && ['start_day', 'end_day', 'next_day'].every((key) => typeof job[key] === 'string'
      && /^\d{4}-\d{2}-\d{2}$/.test(job[key] as string))
    && typeof job['dimension'] === 'string' && ['date', 'query', 'page'].includes(job['dimension'])
    && (job['current_job'] === null || typeof job['current_job'] === 'number' && positiveInteger(job['current_job']))
    && typeof job['error_category'] === 'string' && job['error_category'].length <= 64
    ? job as unknown as BackfillJob : null;
}

function readSourceSchedule(value: unknown): SourceSchedule | null {
  if (!value || typeof value !== 'object') return null;
  const schedule = value as Record<string, unknown>;
  return typeof schedule['id'] === 'number' && positiveInteger(schedule['id'])
    && typeof schedule['enabled'] === 'boolean'
    && typeof schedule['dimension'] === 'string' && ['date', 'query', 'page'].includes(schedule['dimension'])
    && ['next_run_at', 'last_run_at'].every((key) => schedule[key] === null
      || typeof schedule[key] === 'string' && (schedule[key] as string).length <= 64)
    && typeof schedule['last_error_category'] === 'string' && schedule['last_error_category'].length <= 64
    && typeof schedule['skipped_occurrences'] === 'number'
    && Number.isSafeInteger(schedule['skipped_occurrences']) && (schedule['skipped_occurrences'] as number) >= 0
    ? schedule as unknown as SourceSchedule : null;
}


function isProjectSource(value: unknown): value is ProjectSourceInfo {
  if (!value || typeof value !== 'object') return false;
  const source = value as Record<string, unknown>;
  const latest = source['latest_import'];
  if (latest !== null) {
    if (!latest || typeof latest !== 'object') return false;
    const record = latest as Record<string, unknown>;
    if (!['status', 'coverage_state', 'date_start', 'date_end', 'export_shape', 'source_completeness']
      .every((field) => typeof record[field] === 'string')
      || !['rows_seen', 'rows_imported', 'row_errors']
        .every((field) => typeof record[field] === 'number' && Number.isSafeInteger(record[field]) && (record[field] as number) >= 0)) return false;
  }
  const sync = source['sync'];
  if (sync !== null && (!sync || typeof sync !== 'object'
    || typeof (sync as Record<string, unknown>)['status'] !== 'string'
    || typeof (sync as Record<string, unknown>)['quota_state'] !== 'string'
    || ((sync as Record<string, unknown>)['retry_after'] !== null
      && typeof (sync as Record<string, unknown>)['retry_after'] !== 'string'))) return false;
  return typeof source['id'] === 'number' && positiveInteger(source['id'])
    && typeof source['provider'] === 'string' && typeof source['property'] === 'string'
    && typeof source['state'] === 'string' && ['active', 'disconnected', 'unavailable'].includes(source['state'])
    && typeof source['scope_current'] === 'boolean' && typeof source['csv_import_supported'] === 'boolean'
    && (source['coverage_available'] === undefined || typeof source['coverage_available'] === 'boolean')
    && (source['scope_kind'] === undefined || typeof source['scope_kind'] === 'string'
      && ['exact_origin_url_prefix', 'verified_domain_page_only', 'ga4_hostname_only'].includes(source['scope_kind']))
    && (source['approved_origins'] === undefined || Array.isArray(source['approved_origins'])
      && source['approved_origins'].length <= 20 && source['approved_origins'].every((origin: unknown) => typeof origin === 'string'))
    && (source['available_api_dimensions'] === undefined || Array.isArray(source['available_api_dimensions'])
      && source['available_api_dimensions'].every((dimension: unknown) => typeof dimension === 'string' && ['date', 'query', 'page'].includes(dimension)))
    && typeof source['oauth_available'] === 'boolean' && typeof source['api_sync_available'] === 'boolean'
    && typeof source['credential_status'] === 'string' && ['not_connected', 'reference_reserved'].includes(source['credential_status'])
    && (latest === null || typeof latest === 'object');
}

function isGoogleOAuthGrant(value: unknown): value is GoogleOAuthGrantInfo {
  if (!value || typeof value !== 'object') return false;
  const grant = value as Record<string, unknown>;
  return typeof grant['id'] === 'number' && positiveInteger(grant['id'])
    && typeof grant['revision'] === 'number' && Number.isSafeInteger(grant['revision']) && (grant['revision'] as number) >= 0
    && typeof grant['verified_at'] === 'string'
    && typeof grant['state'] === 'string' && ['pending_selection', 'active', 'reconnect_required', 'revocation_pending', 'revoked'].includes(grant['state'])
    && Array.isArray(grant['sites']) && grant['sites'].length <= 50
    && grant['sites'].every((site: unknown) => site && typeof site === 'object'
      && typeof (site as Record<string, unknown>)['property'] === 'string'
      && typeof (site as Record<string, unknown>)['site_url'] === 'string'
      && ((site as Record<string, unknown>)['scope'] === undefined
        || typeof (site as Record<string, unknown>)['scope'] === 'string'
        && ['exact_origin_url_prefix', 'verified_domain_page_only'].includes((site as Record<string, unknown>)['scope'] as string))
      && ((site as Record<string, unknown>)['approved_origins'] === undefined
        || Array.isArray((site as Record<string, unknown>)['approved_origins'])
        && ((site as Record<string, unknown>)['approved_origins'] as unknown[]).every((origin) => typeof origin === 'string')));
}

function isSourceQuery(value: unknown): value is SourceQueryInfo {
  if (!value || typeof value !== 'object') return false;
  const query = value as Record<string, unknown>;
  return typeof query['id'] === 'number' && positiveInteger(query['id'])
    && ['query', 'date_start', 'date_end', 'search_type', 'import_status']
      .every((field) => typeof query[field] === 'string')
    && ['default_label', 'label'].every((field) => typeof query[field] === 'string'
      && ['branded', 'non_branded', 'unclassified'].includes(query[field] as string))
    && typeof query['review_revision'] === 'number' && Number.isSafeInteger(query['review_revision']) && (query['review_revision'] as number) >= 0;
}

function stringList(value: unknown): string[] | null {
  return Array.isArray(value) && value.every((item) => typeof item === 'string') ? value : null;
}

function readProject(value: unknown): ProjectInfo | null {
  if (!value || typeof value !== 'object') return null;
  const item = value as Record<string, unknown>;
  const role = item['role'];
  const aliases = stringList(item['aliases']);
  return typeof item['id'] === 'number' && positiveInteger(item['id'])
    && typeof item['organization_id'] === 'number' && positiveInteger(item['organization_id'])
    && typeof item['name'] === 'string' && typeof item['canonical_origin'] === 'string'
    && aliases !== null && typeof item['access_restricted'] === 'boolean'
    && (role === 'owner' || role === 'admin' || role === 'member' || role === 'viewer')
    ? { id: item['id'], organization_id: item['organization_id'], name: item['name'], canonical_origin: item['canonical_origin'], aliases, access_restricted: item['access_restricted'], role }
    : null;
}

function readConfiguration(value: unknown): ProjectConfigurationInfo | null {
  if (!value || typeof value !== 'object') return null;
  const item = value as Record<string, unknown>;
  const arrays = ['target_languages', 'seed_topics', 'prohibited_claims', 'conversion_goals', 'brand_aliases',
    'competitor_origins', 'research_allowed_origins', 'research_blocked_origins', 'rss_feed_urls', 'business_locations', 'service_areas', 'profile_urls',
    'ignored_query_parameters', 'pagination_query_parameters', 'facet_query_parameters'];
  if (!arrays.every((field) => stringList(item[field]) !== null)) return null;
  const strings = ['canonical_origin', 'target_country', 'business_goal', 'timezone', 'audience', 'offer', 'brand_voice',
    'measurement_notes',
    'contact_details', 'business_hours', 'local_eligibility_notes'];
  if (!strings.every((field) => typeof item[field] === 'string')) return null;
  if (typeof item['project_id'] !== 'number' || !positiveInteger(item['project_id'])
    || typeof item['revision'] !== 'number' || !Number.isInteger(item['revision']) || item['revision'] < 0) return null;
  if (item['crawl_page_limit'] !== null
    && (typeof item['crawl_page_limit'] !== 'number' || !positiveInteger(item['crawl_page_limit']) || item['crawl_page_limit'] > 100000)) return null;
  if (typeof item['query_variant_limit'] !== 'number' || !positiveInteger(item['query_variant_limit'])
    || item['query_variant_limit'] > 25) return null;
  if (!isSourceChoice(item['source_choice'] as string) && item['source_choice'] !== 'undecided') return null;
  if (typeof item['source_state'] !== 'string'
    || !['not_selected', 'disconnected', 'awaiting_import', 'skipped', 'synthetic_demo'].includes(item['source_state'])) return null;
  if (typeof item['current_step'] !== 'string' || !['basics', 'source', 'advanced', 'complete'].includes(item['current_step'])) return null;
  if (item['updated_at'] !== null && typeof item['updated_at'] !== 'string') return null;
  return item as unknown as ProjectConfigurationInfo;
}

// Partial local draft: integration/report panels retain their explicit English region.
const onboardingTurkish: Readonly<Record<string, string>> = {
  "Project onboarding": "Proje başlangıç kurulumu",
  "technical candidate outcome unknown. Refresh findings before retrying.": "Teknik adayın sonucu bilinmiyor. Tekrar denemeden önce bulguları yenileyin.",
  "performance candidate outcome unknown. Refresh findings before retrying.": "Performans adayının sonucu bilinmiyor. Tekrar denemeden önce bulguları yenileyin.",
  "Page speed and real-user performance": "Sayfa hızı ve gerçek kullanıcı performansı",
  "Lighthouse is a lab run, not real-user field data. CrUX current and history use field p75 and may be unavailable for low traffic. Missing data never means passing.": "Lighthouse bir laboratuvar çalışmasıdır; gerçek kullanıcı saha verisi değildir. CrUX güncel ve geçmiş verileri saha p75 değerlerini kullanır ve düşük trafik nedeniyle kullanılamayabilir. Eksik veri, başarılı sonuç anlamına gelmez.",
  "Refresh performance history": "Performans geçmişini yenile",
  "Load performance history": "Performans geçmişini yükle",
  "Checking project performance audits.": "Proje performans denetimleri kontrol ediliyor.",
  "Performance history is unavailable; refresh this project.": "Performans geçmişi kullanılamıyor; bu projeyi yenileyin.",
  "A project-eligible Google performance key is not configured. An organization owner/admin or platform operator can set one in private provider settings.": "Proje için uygun Google performans anahtarı yapılandırılmamış. Kuruluş sahibi/yöneticisi veya platform operatörü özel sağlayıcı ayarlarında bir anahtar tanımlayabilir.",
  "One exact project URL or origin": "Tek bir tam proje URL’si veya kaynak adresi",
  "Source grain": "Kaynak düzeyi",
  "Page": "Sayfa",
  "Origin (CrUX only)": "Kaynak adresi (yalnızca CrUX)",
  "Device": "Cihaz",
  "Mobile": "Mobil",
  "Desktop": "Masaüstü",
  "Tablet (CrUX only)": "Tablet (yalnızca CrUX)",
  "Independent sources (one unit each, at most three)": "Bağımsız kaynaklar (her biri bir birim, en fazla üç)",
  "Lighthouse lab": "Lighthouse laboratuvarı",
  "CrUX current field": "CrUX güncel saha verisi",
  "CrUX field history": "CrUX saha geçmişi",
  "One to three attempted internal units; provider quotas and trial limits can stop a partial job. No result is guaranteed.": "Bir ile üç arasında dahili birim denenir; sağlayıcı kotaları ve deneme sınırları kısmi bir işi durdurabilir. Sonuç garanti edilmez.",
  "Request bounded performance audit": "Sınırlı performans denetimi iste",
  "No performance audit has been requested for this project.": "Bu proje için performans denetimi istenmemiş.",
  "Recent project performance audits": "Son proje performans denetimleri",
  "Audit": "Denetim",
  "attempted": "denenen",
  "lab": "laboratuvar",
  "field": "saha",
  "Inspect parsed evidence": "Ayrıştırılmış kanıtları incele",
  "Only the 20 most recent audits are listed.": "Yalnızca son 20 denetim listeleniyor.",
  "Selected audit detail is unavailable; retry from this project.": "Seçilen denetimin ayrıntıları kullanılamıyor; bu projeden tekrar deneyin.",
  "Cancel audit": "Denetimi iptal et",
  "No parsed lab or field observation is available yet; unavailable is not a passing grade.": "Henüz ayrıştırılmış laboratuvar veya saha gözlemi yok; kullanılamayan veri, başarılı not anlamına gelmez.",
  "Record parsed performance review candidates": "Ayrıştırılmış performans inceleme adaylarını kaydet",
  "Lab performance score": "Laboratuvar performans puanı",
  "(0–1, not a field p75). Status": "(0–1, saha p75 değeri değildir). Durum",
  "CrUX": "CrUX",
  "history": "geçmiş",
  "current": "güncel",
  "field p75": "saha p75",
  "Requested": "İstenen",
  "observed": "gözlenen",
  "origin fallback (not page data)": "kaynak adresine dönüş (sayfa verisi değil)",
  "no origin fallback": "kaynak adresine dönüş yok",
  "History windows may overlap; a threshold change is not causal proof.": "Geçmiş dönem pencereleri örtüşebilir; eşik değişikliği nedensellik kanıtı değildir.",
  "These historical parsed values alone do not establish original raw integrity or actual period comparability. Inspect the original source below.": "Bu ayrıştırılmış geçmiş değerleri tek başına özgün ham veri bütünlüğünü veya gerçek dönem karşılaştırılabilirliğini kanıtlamaz. Aşağıdaki özgün kaynağı inceleyin.",
  "Select at least one source; Lighthouse lab needs a mobile or desktop page target.": "En az bir kaynak seçin; Lighthouse laboratuvarı için mobil veya masaüstü sayfa hedefi gerekir.",
  "Audit outcome unknown. Refresh before retrying the same request.": "Denetim sonucu bilinmiyor. Aynı isteği tekrar denemeden önce yenileyin.",
  "Audit cancellation requested; one attempt may still finish.": "Denetimin iptali istendi; bir deneme yine de tamamlanabilir.",
  "Audit cancelled.": "Denetim iptal edildi.",
  "Audit cancellation outcome unknown; refresh its status.": "Denetimin iptal sonucu bilinmiyor; durumunu yenileyin.",

  "Crawl and search-engine indexation evidence": "Tarama ve arama motoru dizinleme kanıtları",
  "A sitemap or successful local fetch is not proof of Google indexing. Google inspection describes its indexed version, not a live-page test. Missing reports are unknown.": "Bir site haritası veya başarılı yerel sayfa alımı, Google dizinlemesinin kanıtı değildir. Google incelemesi dizinindeki sürümü açıklar; canlı sayfa testi değildir. Eksik raporlar bilinmiyor.",
  "Refresh indexation evidence": "Dizinleme kanıtlarını yenile",
  "Load indexation evidence": "Dizinleme kanıtlarını yükle",
  "Checking project crawl and engine evidence.": "Proje tarama ve arama motoru kanıtları kontrol ediliyor.",
  "Indexation evidence is unavailable; retry for this project.": "Dizinleme kanıtları kullanılamıyor; bu proje için tekrar deneyin.",
  "No completed crawl is available for this project.": "Bu proje için tamamlanmış tarama yok.",
  "Completed crawl": "Tamamlanmış tarama",
  "Crawl": "Tarama",
  "Only the 20 most recent completed crawls are listed.": "Yalnızca son 20 tamamlanmış tarama listeleniyor.",
  "Build no-fetch evidence for this crawl": "Bu tarama için sayfa almadan kanıt oluştur",
  "Recording immutable crawl observations without fetching pages.": "Sayfa almadan değişmez tarama gözlemleri kaydediliyor.",
  "Local coverage": "Yerel kapsam",
  "engine reports": "arama motoru raporları",
  ". No missing URL implies zero or indexed.": ". Eksik bir URL sıfır veya dizine alınmış anlamına gelmez.",
  "Record scoped indexation review candidates": "Kapsam içindeki dizinleme inceleme adaylarını kaydet",
  "Record observed technical review candidates": "Gözlenen teknik inceleme adaylarını kaydet",
  "Per-URL crawl and indexation evidence": "URL başına tarama ve dizinleme kanıtları",
  "discovered by": "keşif kaynağı",
  "local crawl": "yerel tarama",
  "Observed HTTP": "Gözlenen HTTP",
  "directive": "yönerge",
  "declared canonical": "bildirilen kanonik adres",
  "Local candidates:": "Yerel adaylar:",
  "Search-engine indexed status unknown; no currently authorized exact-URL inspection report.": "Arama motorundaki dizin durumu bilinmiyor; şu anda yetkilendirilmiş tam URL inceleme raporu yok.",
  "on Google's indexed version;": "Google dizinindeki sürüm için;",
  "collected": "toplanma zamanı",
  "recency unknown": "güncellik bilinmiyor",
  "older than local crawl": "yerel taramadan eski",
  "not older than local crawl": "yerel taramadan eski değil",
  "Google-reported declared canonical": "Google’ın bildirdiği kanonik adres",
  "Google-selected canonical": "Google’ın seçtiği kanonik adres",
  "unknown or outside scope": "bilinmiyor veya kapsam dışında",
  "Review candidates:": "İnceleme adayları:",
  "No immutable crawl evidence has been built for the selected run.": "Seçilen çalışma için değişmez tarama kanıtı oluşturulmadı.",
  "No-fetch crawl evidence recorded; Google reports remain separate observations.": "Sayfa almadan tarama kanıtı kaydedildi; Google raporları ayrı gözlemler olarak kalır.",
  "Crawl evidence could not be built. Check the source and retry.": "Tarama kanıtı oluşturulamadı. Kaynağı kontrol edip tekrar deneyin.",

  "Google Search Console authorization": "Google Search Console yetkilendirmesi",
  "Consent requires an administrator and a configured Google client. Choose an exact website property after returning from Google. A finalized daily sync can then be started from the source above.": "Onay için bir yönetici ve yapılandırılmış Google istemcisi gerekir. Google’dan döndükten sonra tam bir web sitesi mülkü seçin. Ardından yukarıdaki kaynaktan kesinleşmiş günlük eşitleme başlatılabilir.",
  "Authorize Google Search Console": "Google Search Console’u yetkilendir",
  "Starting Google authorization.": "Google yetkilendirmesi başlatılıyor.",
  "Loading Google authorization status.": "Google yetkilendirme durumu yükleniyor.",
  "Google authorization status is unavailable; reload this project to retry.": "Google yetkilendirme durumu kullanılamıyor; tekrar denemek için bu projeyi yeniden yükleyin.",
  "No Google authorizations recorded for this project.": "Bu proje için Google yetkilendirmesi kaydedilmedi.",
  "Google authorization records": "Google yetkilendirme kayıtları",
  "Authorization": "Yetkilendirme",
  "Choose a website property while this authorization is current. Property selection expires after ten minutes.": "Bu yetkilendirme geçerliyken bir web sitesi mülkü seçin. Mülk seçimi on dakika sonra sona erer.",
  "Domain property": "Alan adı mülkü",
  "includes other subdomains/protocols at Google.": "Google’da diğer alt alan adlarını ve protokolleri içerir.",
  "Only page rows for verified project origins": "Yalnızca doğrulanmış proje kaynak adreslerinin sayfa satırları",
  "can be used here. Domain-wide totals and query/date reports stay unavailable.": "burada kullanılabilir. Alan adı genelindeki toplamlar ve sorgu veya tarih raporları kullanılamaz.",
  "Use": "Kullan",
  "via Google": "Google aracılığıyla",
  "No property is within the project's current scope. Reauthorize if its scope changed.": "Projenin güncel kapsamında bir mülk yok. Kapsamı değiştiyse yeniden yetkilendirin.",
  "Property authorization recorded. Sync history is shown on its source record above.": "Mülk yetkilendirmesi kaydedildi. Eşitleme geçmişi yukarıdaki kaynak kaydında gösteriliyor.",
  "Local access is disabled. Google revocation has not been confirmed; retry revocation.": "Yerel erişim devre dışı. Google yetkisinin iptali doğrulanmadı; iptali tekrar deneyin.",
  "Authorization needs fresh consent. No API work is available.": "Yetkilendirme için yeni onay gerekiyor. API işi kullanılamıyor.",
  "Authorization revoked. Local credentials have been erased.": "Yetkilendirme iptal edildi. Yerel kimlik bilgileri silindi.",
  "Revoke Google authorization": "Google yetkilendirmesini iptal et",
  "Additional older authorizations are not shown.": "Ek eski yetkilendirmeler gösterilmiyor.",
  "Google Analytics authorization": "Google Analytics yetkilendirmesi",
  "Analytics requires separate read-only Google consent and an operator-configured Analytics application. A configured web stream is not proof of collection or conversion instrumentation. No GA4 sync is available yet.": "Analytics için ayrı salt okunur Google onayı ve operatör tarafından yapılandırılmış bir Analytics uygulaması gerekir. Yapılandırılmış bir web akışı, veri toplamanın veya dönüşüm ölçüm kurulumunun kanıtı değildir. GA4 eşitlemesi henüz kullanılamıyor.",
  "Authorize Google Analytics": "Google Analytics’i yetkilendir",
  "Refresh Analytics grants": "Analytics izinlerini yenile",
  "Loading Analytics consent status.": "Analytics onay durumu yükleniyor.",
  "Analytics consent status is unavailable; refresh before retrying.": "Analytics onay durumu kullanılamıyor; tekrar denemeden önce yenileyin.",
  "No Analytics grant recorded. No sessions, key events or revenue are available.": "Analytics izni kaydedilmedi. Oturum, önemli etkinlik veya gelir verisi kullanılamıyor.",
  "Analytics consent grants": "Analytics onay izinleri",
  "Analytics consent": "Analytics onayı",
  "Google Analytics numeric property ID": "Google Analytics sayısal mülk kimliği",
  "One configured HTTPS web origin": "Yapılandırılmış tek bir HTTPS web kaynak adresi",
  "Choose a current project origin": "Güncel bir proje kaynak adresi seçin",
  "Check scoped web stream and reporting columns": "Kapsam içindeki web akışını ve raporlama sütunlarını kontrol et",
  "Selected property": "Seçilen mülk",
  "The grant is disabled until a scoped source is linked.": "Kapsam içindeki bir kaynak bağlanana kadar izin devre dışıdır.",
  "Link this configured Analytics source": "Bu yapılandırılmış Analytics kaynağını bağla",
  "Property": "Mülk",
  "A source reference is configured for manual measurement review; exact-origin Analytics reports and conversion instrumentation remain unavailable.": "Manuel ölçüm incelemesi için bir kaynak başvurusu yapılandırıldı; tam kaynak adresi kapsamındaki Analytics raporları ve dönüşüm ölçüm kurulumu kullanılamıyor.",
  "Local access is disabled. Google remote revocation is pending; retry it.": "Yerel erişim devre dışı. Google’daki uzak yetki iptali bekleniyor; tekrar deneyin.",
  "Grant revoked; no Analytics data is available.": "İzin iptal edildi; Analytics verisi kullanılamıyor.",
  "Disconnect this Analytics grant now? Remote revocation may need retry.": "Bu Analytics izni şimdi kaldırılsın mı? Uzak yetki iptalini tekrar denemek gerekebilir.",
  "Confirm Analytics disconnect": "Analytics bağlantısının kesilmesini onayla",
  "Cancel": "Vazgeç",
  "Disconnect Analytics grant": "Analytics iznini kaldır",
  "Older Analytics grants are not shown.": "Daha eski Analytics izinleri gösterilmiyor.",
  "Google property authorization recorded. Check source status before starting API sync.": "Google mülk yetkilendirmesi kaydedildi. API eşitlemesini başlatmadan önce kaynak durumunu kontrol edin.",
  "Local Google access disabled. Check whether remote revocation is still pending.": "Yerel Google erişimi devre dışı bırakıldı. Uzak yetki iptalinin hâlâ bekleyip beklemediğini kontrol edin.",
  "Google authorization is unavailable. Check the configured callback and your access.": "Google yetkilendirmesi kullanılamıyor. Yapılandırılmış geri dönüş adresini ve erişiminizi kontrol edin.",
  "Google authorization could not be started.": "Google yetkilendirmesi başlatılamadı.",
  "Google authorization could not be started. Check the connection and retry.": "Google yetkilendirmesi başlatılamadı. Bağlantıyı kontrol edip tekrar deneyin.",
  "Google authorization changed or is unavailable. Reload this project before retrying.": "Google yetkilendirmesi değişti veya kullanılamıyor. Tekrar denemeden önce bu projeyi yeniden yükleyin.",
  "Google authorization outcome is unknown. Reload before retrying.": "Google yetkilendirme sonucu bilinmiyor. Tekrar denemeden önce yeniden yükleyin.",
  "Analytics consent unavailable. Check staff app configuration, project access and retry.": "Analytics onayı kullanılamıyor. Operatörün uygulama yapılandırmasını ve proje erişimini kontrol edip tekrar deneyin.",
  "Analytics web-stream candidate saved; no source or data sync is active.": "Analytics web akışı adayı kaydedildi; etkin kaynak veya veri eşitlemesi yok.",
  "Analytics source scoped to this project; data synchronization is not yet available.": "Analytics kaynağı bu proje kapsamına alındı; veri eşitlemesi henüz kullanılamıyor.",
  "Local Analytics access disabled; refresh to confirm remote revocation.": "Yerel Analytics erişimi devre dışı bırakıldı; uzak yetki iptalini doğrulamak için yenileyin.",
  "Analytics grant outcome unknown. Refresh this project before retrying.": "Analytics izin sonucu bilinmiyor. Tekrar denemeden önce bu projeyi yenileyin.",

  "Choose at most ten Analytics event mappings.": "En fazla on Analytics etkinlik eşlemesi seçin.",
  "Analytics property": "Analytics mülkü",
  "configured host only": "yalnızca yapılandırılmış ana makine",
  "scope unavailable": "kapsam kullanılamıyor",
  "Search Console clicks, Analytics sessions and key events are different measurements. A configured web stream does not prove collection or conversion goals; absent rows are unknown. GA4's hostname-only landing report cannot distinguish this exact HTTPS origin from another scheme or port on the same host, so Analytics report sync is unavailable.": "Search Console tıklamaları, Analytics oturumları ve önemli etkinlikler farklı ölçümlerdir. Yapılandırılmış bir web akışı, veri toplamayı veya dönüşüm hedeflerini kanıtlamaz; eksik satırlar bilinmiyor. GA4’ün yalnızca ana makine adına dayalı açılış sayfası raporu, bu tam HTTPS kaynak adresini aynı ana makinedeki başka bir şema veya bağlantı noktasından ayıramaz; bu nedenle Analytics rapor eşitlemesi kullanılamıyor.",
  "Analytics property-local reporting day": "Analytics mülkünün yerel raporlama günü",
  "Analytics report grain": "Analytics rapor ayrıntı düzeyi",
  "All reported session channels": "Bildirilen tüm oturum kanalları",
  "GA4 Organic Search session channel only": "Yalnızca GA4 Organik Arama oturum kanalı",
  "One day aged 3–90 days, one selected hostname. Up to five attempted internal units: property, web streams, compatibility and up to two 100-row report pages. Data API sampling, thresholds, other rows and collection gaps remain visible.": "3–90 gün önceki tek bir gün, seçilmiş tek bir ana makine adı. En fazla beş dahili birim denenir: mülk, web akışları, uyumluluk ve en fazla iki 100 satırlık rapor sayfası. Data API örneklemesi, eşikler, diğer satırlar ve veri toplama eksikleri görünür kalır.",
  "Request bounded Analytics report": "Sınırlı Analytics raporu iste",
  "Refresh Analytics report status": "Analytics rapor durumunu yenile",
  "Loading Analytics report status.": "Analytics rapor durumu yükleniyor.",
  "Analytics report status unavailable; refresh before retrying.": "Analytics rapor durumu kullanılamıyor; tekrar denemeden önce yenileyin.",
  "Analytics job": "Analytics işi",
  "hostname": "ana makine adı",
  "attempted requests,": "denenen istek,",
  "pages recorded.": "kaydedilen sayfa.",
  "Cancel Analytics request": "Analytics isteğini iptal et",
  "offset": "satır başlangıcı",
  "Source scope": "Kaynak kapsamı",
  "; GA4 session channel is not a Search Console click or a per-goal conversion.": "; GA4 oturum kanalı, Search Console tıklaması veya hedef başına dönüşüm değildir.",
  "Sampling": "Örnekleme",
  "reported": "bildirildi",
  "not reported": "bildirilmedi",
  "thresholding": "eşik uygulanması",
  "other-row loss": "diğer satır kaybı",
  "omitted out-of-scope/parameterized rows": "atlanan kapsam dışı veya parametreli satırlar",
  "Full activity": "Tüm etkinlik kapsamı",
  "instrumentation": "ölçüm kurulumu",
  "verified": "doğrulandı",
  "not verified": "doğrulanmadı",
  "all session channels": "tüm oturum kanalları",
  "sessions": "oturumlar",
  "key events": "önemli etkinlikler",
  "reported revenue": "bildirilen gelir",
  "No Analytics report job recorded for this source.": "Bu kaynak için Analytics rapor işi kaydedilmedi.",
  "Review Analytics measurement definitions": "Analytics ölçüm tanımlarını incele",
  "Loading measurement definitions.": "Ölçüm tanımları yükleniyor.",
  "Measurement review history unavailable; refresh before editing.": "Ölçüm inceleme geçmişi kullanılamıyor; düzenlemeden önce yenileyin.",
  "No property-bound conversion event definitions reviewed. GA4 aggregate key events cannot be assigned to a goal.": "Mülke bağlı dönüşüm etkinliği tanımları incelenmedi. GA4 toplam önemli etkinlikleri bir hedefe atanamaz.",
  "Analytics measurement review history": "Analytics ölçüm inceleme geçmişi",
  "property": "mülk",
  "event quality": "etkinlik kalitesi",
  "Instrumentation:": "Ölçüm kurulumu:",
  "attribution:": "ilişkilendirme:",
  "consent gaps:": "rıza kapsamındaki eksikler:",
  "tracking changes:": "izleme değişiklikleri:",
  "manual value definition": "manuel değer tanımı",
  "unavailable": "kullanılamıyor",
  "Older measurement reviews are not shown.": "Daha eski ölçüm incelemeleri gösterilmiyor.",
  "Describe up to ten manual goal → GA4 event mappings. These are definitions, not per-event counts. One line per mapping: goal | event_name | manual value definition.": "En fazla on manuel hedef → GA4 etkinlik eşlemesi tanımlayın. Bunlar tanımlardır; etkinlik başına sayılar değildir. Her eşleme için bir satır: hedef | event_name | manuel değer tanımı.",
  "Goals and event names": "Hedefler ve etkinlik adları",
  "Instrumentation review status": "Ölçüm kurulumu inceleme durumu",
  "Unverified": "Doğrulanmadı",
  "Manually reviewed (not provider-verified)": "Manuel olarak incelendi (sağlayıcı tarafından doğrulanmadı)",
  "Manual missing/duplicate event concern": "Manuel eksik veya yinelenen etkinlik endişesi",
  "Not checked": "Kontrol edilmedi",
  "Suspected missing events": "Eksik etkinlik şüphesi",
  "Suspected duplicate events": "Yinelenen etkinlik şüphesi",
  "Suspected missing and duplicate events": "Eksik ve yinelenen etkinlik şüphesi",
  "Manual review noted no concern (not verified)": "Manuel incelemede endişe belirtilmedi (doğrulanmadı)",
  "Instrumentation review notes": "Ölçüm kurulumu inceleme notları",
  "Attribution settings/assumptions (manual)": "İlişkilendirme ayarları veya varsayımları (manuel)",
  "Consent/threshold/modeled reporting gaps": "Rıza, eşik ve modellenmiş raporlama eksikleri",
  "Tracking or configuration changes": "İzleme veya yapılandırma değişiklikleri",
  "Record human measurement revision": "İnsan ölçüm incelemesi revizyonunu kaydet",
  "Historical measurement notes remain visible; this source is not current for new reviews.": "Geçmiş ölçüm notları görünür kalır; bu kaynak yeni incelemeler için güncel değildir.",
  "Analytics request outcome unknown. Refresh status before retrying the same day.": "Analytics isteğinin sonucu bilinmiyor. Aynı günü tekrar denemeden önce durumu yenileyin.",
  "Analytics cancellation requested. Refresh status to see the final observed result.": "Analytics iptali istendi. Gözlenen son sonucu görmek için durumu yenileyin.",
  "Analytics cancellation outcome unknown; refresh before retrying.": "Analytics iptal sonucu bilinmiyor; tekrar denemeden önce yenileyin.",
  "Manual Analytics measurement review recorded; no event count, attribution or conversion was verified.": "Manuel Analytics ölçüm incelemesi kaydedildi; etkinlik sayısı, ilişkilendirme veya dönüşüm doğrulanmadı.",
  "Analytics review outcome unknown. Refresh history before retrying.": "Analytics inceleme sonucu bilinmiyor. Tekrar denemeden önce geçmişi yenileyin.",
  "Use goal | event_name | manual value definition on each line.": "Her satırda hedef | event_name | manuel değer tanımı biçimini kullanın.",

  "Cancellation outcome is unknown. Refresh sync status.": "İptal sonucu bilinmiyor. Eşitleme durumunu yenileyin.",
  "Sync cancelled.": "Eşitleme iptal edildi.",
  "Cancellation requested; the current request may finish.": "İptal istendi; geçerli istek yine de tamamlanabilir.",
  "Sync record:": "Eşitleme kaydı:",
  "quota": "kota",
  "coverage": "kapsam",
  "fresh through": "güncel olduğu son tarih",
  "unknown": "bilinmiyor",
  "Provider reports only top rows; unreported queries and pages remain unknown.": "Sağlayıcı yalnızca üst sıralı satırları bildirir; bildirilmeyen sorgular ve sayfalar bilinmiyor.",
  "Local retry no earlier than": "Yerel yeniden deneme için en erken zaman",
  "No API sync recorded for this property.": "Bu mülk için API eşitlemesi kaydedilmedi.",
  "Finalized Search Console date (Pacific Time)": "Kesinleşmiş Search Console tarihi (Pasifik Saati)",
  "Independent report dimension": "Bağımsız rapor boyutu",
  "Verified-origin pages only": "Yalnızca doğrulanmış kaynak adreslerindeki sayfalar",
  "Queries": "Sorgular",
  "Pages": "Sayfalar",
  "Daily total": "Günlük toplam",
  "At most": "En fazla",
  "two API requests (property check plus one report page)": "iki API isteği (mülk kontrolü ve bir rapor sayfası)",
  "three API requests (property check plus two report pages)": "üç API isteği (mülk kontrolü ve iki rapor sayfası)",
  "for one date, aged 3–90 days. Google supplies top rows only; omitted rows are unknown. Internal usage: up to": "3–90 gün önceki tek bir tarih için. Google yalnızca üst sıralı satırları sağlar; atlanan satırlar bilinmiyor. Dahili kullanım: en fazla",
  "request units.": "istek birimi.",
  "Sync this property": "Bu mülkü eşitle",
  "Refresh sync status": "Eşitleme durumunu yenile",
  "Checking Search Console sync status.": "Search Console eşitleme durumu kontrol ediliyor.",
  "Sync status is unavailable; retry the refresh before submitting again.": "Eşitleme durumu kullanılamıyor; yeniden göndermeden önce yenilemeyi tekrar deneyin.",
  "Job": "İş",
  "pages recorded from": "sayfa kaydedildi;",
  "attempts; source coverage": "istek denemesi yapıldı; kaynak kapsamı",
  "Reason:": "Neden:",
  "Cancel this sync": "Bu eşitlemeyi iptal et",
  "No sync job has been recorded for this source.": "Bu kaynak için eşitleme işi kaydedilmedi.",
  "Backfill first finalized Pacific Time day": "Geçmiş veri için ilk kesinleşmiş Pasifik Saati günü",
  "Backfill last finalized Pacific Time day": "Geçmiş veri için son kesinleşmiş Pasifik Saati günü",
  "One to seven days, 3–90 days old. One day runs at a time; pause on partial, quota or lost requests.": "3–90 gün önceki bir ila yedi gün. Her seferinde bir gün işlenir; kısmi sonuç, kota veya kaybolan isteklerde duraklatılır.",
  "Up to": "En fazla",
  "internal request units for seven days. Provider top-row coverage remains incomplete and missing pages are unknown.": "dahili istek birimi, yedi gün için. Sağlayıcının üst sıralı satır kapsamı eksik kalır ve eksik sayfalar bilinmiyor.",
  "Start bounded backfill": "Sınırlı geçmiş veri alımını başlat",
  "Refresh backfill": "Geçmiş veri durumunu yenile",
  "Checking backfill status.": "Geçmiş veri durumu kontrol ediliyor.",
  "Backfill status unavailable; refresh before retrying.": "Geçmiş veri durumu kullanılamıyor; tekrar denemeden önce yenileyin.",
  "Backfill": "Geçmiş veri",
  "requested": "istenen",
  "current day": "geçerli gün",
  "source": "kaynak",
  "Earlier days remain separate observations.": "Önceki günler ayrı gözlemler olarak kalır.",
  "Stop remaining backfill days": "Kalan geçmiş veri günlerini durdur",
  "No backfill request recorded for this source.": "Bu kaynak için geçmiş veri isteği kaydedilmedi.",
  "Daily": "Günlük",
  "report:": "rapor:",
  "enabled": "etkin",
  "paused": "duraklatıldı",
  "next due": "sonraki çalışma",
  "not scheduled": "planlanmadı",
  "last queued": "son kuyruğa alma",
  "never": "hiçbir zaman",
  "Missed intervals skipped:": "Atlanan çalışma aralıkları:",
  "Pause": "Duraklat",
  "Enable": "Etkinleştir",
  "daily reports": "günlük raporları",
  "Daily report dimension": "Günlük rapor boyutu",
  "One finalized Pacific Time day per occurrence, starting after you enable it. Missed days are not replayed; source loss or unknown work pauses the schedule. Pausing stops future runs; already queued work may finish. Google top rows remain incomplete.": "Etkinleştirdikten sonra her çalışmada kesinleşmiş bir Pasifik Saati günü işlenir. Kaçırılan günler yeniden işlenmez; kaynak kaybı veya sonucu bilinmeyen işler zamanlamayı duraklatır. Duraklatma gelecekteki çalışmaları durdurur; kuyruğa alınmış işler tamamlanabilir. Google üst sıralı satırları eksik kalır.",
  "Create daily report schedule": "Günlük rapor zamanlaması oluştur",
  "Refresh daily schedule": "Günlük zamanlamayı yenile",
  "Daily schedule status unavailable; refresh before retrying.": "Günlük zamanlama durumu kullanılamıyor; tekrar denemeden önce yenileyin.",
  "One exact project URL for Google indexed-version inspection": "Google dizinindeki sürümü incelemek için tek bir tam proje URL’si",
  "Inspect Google's indexed version, not a live-page test. No query parameters or fragments. Also read a submitted sitemap list; only verified-origin sitemap URLs are retained, never domain-wide indexed counts. At most three attempted internal units. Missing reports are unknown.": "Google dizinindeki sürümü inceler; canlı sayfa testi değildir. Sorgu parametresi veya parça tanımlayıcısı kullanılamaz. Gönderilmiş site haritası listesi de okunur; yalnızca doğrulanmış kaynak adreslerinin site haritası URL’leri tutulur, alan adı genelindeki dizine alınmış sayılar tutulmaz. En fazla üç dahili birim denenir. Eksik raporlar bilinmiyor.",
  "Inspect URL and submitted sitemaps": "URL ve gönderilmiş site haritalarını incele",
  "Loading Google coverage job status.": "Google kapsam işi durumu yükleniyor.",
  "Coverage status unavailable; retry refresh.": "Kapsam durumu kullanılamıyor; yenilemeyi tekrar deneyin.",
  "Inspection job": "İnceleme işi",
  "attempted requests;": "denenen istek;",
  "scoped results.": "kapsam içindeki sonuç.",
  "Google indexed-version verdict:": "Google dizinindeki sürüm kararı:",
  "indexed state": "dizin durumu",
  "last Google crawl": "son Google taraması",
  "This does not verify the current live page.": "Bu, güncel canlı sayfayı doğrulamaz.",
  "Submitted sitemap URLs on verified project origins only; totals and sibling-host coverage are unknown.": "Yalnızca doğrulanmış proje kaynak adreslerindeki gönderilmiş site haritası URL’leri; toplamlar ve diğer alt alan adlarının kapsamı bilinmiyor.",
  "Refresh coverage status": "Kapsam durumunu yenile",
  "Cancel coverage request": "Kapsam isteğini iptal et",
  "No indexed-version or sitemap request recorded for this source.": "Bu kaynak için dizindeki sürüm veya site haritası isteği kaydedilmedi.",
  "Domain properties only support verified-origin page reports.": "Alan adı mülkleri yalnızca doğrulanmış kaynak adreslerinin sayfa raporlarını destekler.",
  "Sync is rate limited or at capacity. Check the source status before retrying.": "Eşitleme istek sınırına veya kapasitesine ulaştı. Tekrar denemeden önce kaynak durumunu kontrol edin.",
  "Sync could not start. Check the current property, date, and authorization.": "Eşitleme başlatılamadı. Güncel mülkü, tarihi ve yetkiyi kontrol edin.",
  "Sync request outcome is unknown. Retry the same date and dimension to avoid duplicate work.": "Eşitleme isteğinin sonucu bilinmiyor. Yinelenen işi önlemek için aynı tarih ve boyutla tekrar deneyin.",
  "Backfill queued; refresh to see each finalized day or a paused outcome.": "Geçmiş veri alımı kuyruğa alındı; her kesinleşmiş günü veya duraklatılan sonucu görmek için yenileyin.",
  "Backfill outcome unknown. Retry the same range to avoid duplicate work.": "Geçmiş veri alımının sonucu bilinmiyor. Yinelenen işi önlemek için aynı aralıkla tekrar deneyin.",
  "Backfill stop outcome unknown; refresh its status.": "Geçmiş veri durdurma sonucu bilinmiyor; durumunu yenileyin.",
  "Daily report schedule created but paused. Enable it to start future checks.": "Günlük rapor zamanlaması oluşturuldu ancak duraklatıldı. Gelecekteki kontrolleri başlatmak için etkinleştirin.",
  "Schedule outcome unknown. Refresh this source before retrying.": "Zamanlama sonucu bilinmiyor. Tekrar denemeden önce bu kaynağı yenileyin.",
  "Daily schedule change could not be confirmed. Refresh before retrying.": "Günlük zamanlama değişikliği doğrulanamadı. Tekrar denemeden önce yenileyin.",
  "Coverage request outcome is unknown. Retry the same URL to avoid duplicate work.": "Kapsam isteğinin sonucu bilinmiyor. Yinelenen işi önlemek için aynı URL ile tekrar deneyin.",
  "Coverage cancellation requested; an attempt may still finish.": "Kapsam iptali istendi; başlamış bir deneme yine de tamamlanabilir.",
  "Coverage request cancelled.": "Kapsam isteği iptal edildi.",
  "Cancellation outcome is unknown. Refresh coverage status first.": "İptal sonucu bilinmiyor. Önce kapsam durumunu yenileyin.",
  "Sync cancellation could not be confirmed. Refresh its status before retrying.": "Eşitleme iptali doğrulanamadı. Tekrar denemeden önce durumunu yenileyin.",

  "Checking deterministic candidate signals for this import.": "Bu içe aktarma için deterministik aday sinyalleri kontrol ediliyor.",
  "Candidate signals are unavailable; check this import's source and retry.": "Aday sinyalleri kullanılamıyor; bu içe aktarmanın kaynağını kontrol edip tekrar deneyin.",
  "Source-qualified candidate preview": "Kaynak kapsamına uygun aday önizlemesi",
  "Candidate preview": "Aday önizlemesi",
  "market": "pazar",
  "not set": "ayarlanmadı",
  "languages": "diller",
  "File coverage": "Dosya kapsamı",
  "; provider top rows": "; sağlayıcının üst sıralı satırları",
  "hidden queries": "gizli sorgular",
  ". Missing rows are not zero.": ". Eksik satırlar sıfır değildir.",
  "Thresholds: position": "Eşikler: konum",
  "impressions at least": "en az gösterim",
  "CTR below": "CTR üst sınırı",
  "These are candidate observations, not approved findings, proven intent conflicts or action recommendations.": "Bunlar aday gözlemleridir; onaylanmış bulgular, kanıtlanmış amaç çakışmaları veya eylem önerileri değildir.",
  "No candidate met these rules in this export; provider coverage remains unknown.": "Bu dışa aktarımda hiçbir aday bu kuralları karşılamadı; sağlayıcı kapsamı bilinmiyor.",
  "impressions,": "gösterim,",
  "clicks,": "tıklama,",
  "average position": "ortalama konum",
  "source row": "kaynak satırı",
  "Additional candidates are not shown.": "Ek adaylar gösterilmiyor.",
  "Record immutable candidate evidence for human review": "İnsan incelemesi için değişmez aday kanıtlarını kaydet",
  "Source-backed findings and human opportunity reviews": "Kaynaklara dayalı bulgular ve insan fırsat incelemeleri",
  "Candidate evidence is not a prioritized opportunity, recommendation or approved change. All reviews remain project-scoped and reversible only through a new revision.": "Aday kanıtı önceliklendirilmiş bir fırsat, öneri veya onaylanmış değişiklik değildir. Tüm incelemeler proje kapsamında kalır ve yalnızca yeni bir sürümle değiştirilebilir.",
  "Review source-limited query intent and preferred pages": "Kaynak kapsamıyla sınırlı sorgu amacını ve tercih edilen sayfaları incele",
  "Query-page cannibalization needs joint query/page observations; separate CSV exports cannot prove it. Content age needs a verified publication date; GA4 goal conversion context needs exact-origin attributed event evidence. These are unavailable, not zero or no issue.": "Sorgu–sayfa rekabeti ortak sorgu/sayfa gözlemleri gerektirir; ayrı CSV dışa aktarımları bunu kanıtlayamaz. İçerik yaşı doğrulanmış yayın tarihi gerektirir; GA4 hedef dönüşüm bağlamı tam kök adrese atfedilen olay kanıtı gerektirir. Bunlar kullanılamıyor; sıfır veya sorun yok anlamına gelmez.",
  "Refresh finding evidence": "Bulgu kanıtlarını yenile",
  "Load finding evidence": "Bulgu kanıtlarını yükle",
  "Checking project finding evidence.": "Proje bulgu kanıtları kontrol ediliyor.",
  "Finding evidence unavailable; refresh this project.": "Bulgu kanıtları kullanılamıyor; bu projeyi yenileyin.",
  "No candidate finding evidence has been recorded for this project.": "Bu proje için aday bulgu kanıtı kaydedilmedi.",
  "Project source-backed findings": "Projenin kaynaklara dayalı bulguları",
  "Detector": "Tespit yöntemi",
  "observation": "gözlem",
  "not attached": "eklenmedi",
  "crawl evidence": "tarama kanıtı",
  "technical evidence": "teknik kanıt",
  "performance evidence": "performans kanıtı",
  "source current": "kaynak güncel",
  "historical source; review unavailable": "geçmiş kaynak; inceleme kullanılamıyor",
  "detected": "tespit tarihi",
  ". This is observed candidate evidence, not proven business value.": ". Bu, gözlenen aday kanıtıdır; kanıtlanmış iş değeri değildir.",
  "Source evidence, observed values and limits": "Kaynak kanıtları, gözlenen değerler ve sınırlar",
  "Human review revision": "İnsan inceleme sürümü",
  "priority,": "öncelik,",
  "effort": "emek",
  "business relevance": "işle ilgisi",
  "reason:": "gerekçe:",
  ". No recommendation or change has been approved.": ". Hiçbir öneri veya değişiklik onaylanmadı.",
  "Not yet prioritized by a human reviewer.": "Henüz insan incelemeci tarafından önceliklendirilmedi.",
  "Priority for": "Şu konu için öncelik:",
  "Not prioritized": "Önceliklendirilmedi",
  "Low": "Düşük",
  "Medium": "Orta",
  "High": "Yüksek",
  "Estimated effort": "Tahmini emek",
  "Unknown": "Bilinmiyor",
  "Small": "Az",
  "Large": "Çok",
  "Business relevance": "İşle ilgisi",
  "Review rationale": "İnceleme gerekçesi",
  "Save human review revision": "İnsan inceleme sürümünü kaydet",
  "Only the 50 most recent finding records are shown.": "Yalnızca en son 50 bulgu kaydı gösteriliyor.",
  "Human opportunity review recorded as a revision; no recommendation or site change approved.": "İnsan fırsat incelemesi bir sürüm olarak kaydedildi; hiçbir öneri veya site değişikliği onaylanmadı.",
  "Opportunity review changed or could not be saved. Refresh findings before retrying.": "Fırsat incelemesi değişti veya kaydedilemedi. Tekrar denemeden önce bulguları yenileyin.",
  "Candidate finding outcome unknown. Refresh finding evidence before retrying.": "Aday bulgu sonucu bilinmiyor. Tekrar denemeden önce bulgu kanıtlarını yenileyin.",
  "Select two different complete query exports.": "İki farklı tam sorgu dışa aktarımı seçin.",
  "Query comparison unavailable or outcome unknown. Refresh findings before retrying.": "Sorgu karşılaştırması kullanılamıyor veya sonucu bilinmiyor. Tekrar denemeden önce bulguları yenileyin.",

  "Queries for selected property": "Seçilen mülkün sorguları",
  "Labels use the current project brand aliases (method": "Etiketler güncel proje marka adlarını kullanır (yöntem",
  ", alias revision": ", marka adı sürümü",
  "). Unreported or anonymized queries are unknown; provider export completeness is unknown. Rows from other properties and export shapes are not joined.": "). Bildirilmeyen veya anonimleştirilmiş sorgular bilinmiyor; sağlayıcı dışa aktarımının tamlığı bilinmiyor. Diğer mülklerden ve dışa aktarım biçimlerinden gelen satırlar birleştirilmez.",
  "Loading query evidence.": "Sorgu kanıtları yükleniyor.",
  "Query evidence is unavailable. Reload this source to retry.": "Sorgu kanıtları kullanılamıyor. Tekrar denemek için bu kaynağı yeniden yükleyin.",
  "No query-grained CSV observations have been imported for this property.": "Bu mülk için sorgu ayrıntısında CSV gözlemi içe aktarılmadı.",
  "Filter loaded rows by brand label": "Yüklenen satırları marka etiketine göre filtrele",
  "All labels": "Tüm etiketler",
  "Branded": "Markalı",
  "Non-branded": "Markasız",
  "Unclassified": "Sınıflandırılmamış",
  "default": "varsayılan",
  "review revision": "inceleme sürümü",
  "Review history": "İnceleme geçmişi",
  "Loading review history.": "İnceleme geçmişi yükleniyor.",
  "Review history is unavailable.": "İnceleme geçmişi kullanılamıyor.",
  "No human corrections recorded.": "İnsan düzeltmesi kaydedilmedi.",
  "Recent review corrections": "Son inceleme düzeltmeleri",
  "Revision": "Sürüm",
  "Older corrections are not shown.": "Daha eski düzeltmeler gösterilmiyor.",
  "Correct label for": "Şu sorgunun etiketini düzelt:",
  "Review reason": "İnceleme gerekçesi",
  "Save correction": "Düzeltmeyi kaydet",
  "Show older query observations": "Daha eski sorgu gözlemlerini yükle",
  "This query was reviewed elsewhere. Reload its source before correcting it.": "Bu sorgu başka bir yerde incelendi. Düzeltmeden önce kaynağını yeniden yükleyin.",
  "This correction could not be saved. Check your access and reload the source.": "Bu düzeltme kaydedilemedi. Erişiminizi kontrol edin ve kaynağı yeniden yükleyin.",
  "Query correction saved with its review history.": "Sorgu düzeltmesi inceleme geçmişiyle birlikte kaydedildi.",
  "Correction outcome unknown. Reload the source before retrying.": "Düzeltme sonucu bilinmiyor. Tekrar denemeden önce kaynağı yeniden yükleyin.",

  "Active project": "Etkin proje",
  "Role:": "Rol:",
  "Existing source status": "Mevcut kaynak durumu",
  "View import job progress and cancellation": "İçe aktarma işinin ilerlemesini ve iptalini görüntüle",
  "Loading existing source status.": "Mevcut kaynak durumu yükleniyor.",
  "Source status is unavailable; this does not mean there are no imports. Reload the project to retry.": "Kaynak durumu kullanılamıyor; bu, içe aktarma olmadığı anlamına gelmez. Tekrar denemek için projeyi yeniden yükleyin.",
  "No source connections have been recorded for this project.": "Bu proje için kaynak bağlantısı kaydedilmedi.",
  "Existing project sources": "Mevcut proje kaynakları",
  "within current project scope": "güncel proje kapsamında",
  "scope changed; unavailable": "kapsam değişti; kullanılamıyor",
  "CSV import": "CSV içe aktarma",
  "supported": "destekleniyor",
  "unsupported": "desteklenmiyor",
  "Credential:": "Kimlik bilgisi:",
  "not connected": "bağlı değil",
  "OAuth reference recorded": "OAuth referansı kaydedildi",
  "Domain property used only for pages on these currently verified project origins:": "Alan adı mülkü yalnızca şu anda doğrulanmış bu proje kök adreslerindeki sayfalar için kullanılır:",
  "none available": "kullanılabilir adres yok",
  "Domain-wide query, date and property totals are unavailable. Google top rows across all subdomains can omit in-scope pages; omitted or absent data is unknown, not zero.": "Alan adı genelindeki sorgu, tarih ve mülk toplamları kullanılamıyor. Google’ın tüm alt alan adlarındaki üst sıralı satırları, kapsam içindeki sayfaları içermeyebilir; atlanan veya bulunmayan veri sıfır değildir, bilinmiyor.",
  "No completed CSV import recorded.": "Tamamlanmış CSV içe aktarma kaydı yok.",
  "Latest file:": "Son dosya:",
  "file coverage": "dosya kapsamı",
  "to": "–",
  "export;": "dışa aktarımı;",
  "of": "/",
  "rows imported,": "satır içe aktarıldı,",
  "errors.": "hata.",
  "Provider export completeness:": "Sağlayıcı dışa aktarımının tamlığı:",
  "View CSV import history": "CSV içe aktarma geçmişini görüntüle",
  "Review queries for this property": "Bu mülkün sorgularını incele",
  "Additional connections are not shown.": "Ek bağlantılar gösterilmiyor.",
  "CSV import history for selected property": "Seçilen mülk için CSV içe aktarma geçmişi",
  "Loading CSV import history.": "CSV içe aktarma geçmişi yükleniyor.",
  "Import history is unavailable; reload the project to retry.": "İçe aktarma geçmişi kullanılamıyor; tekrar denemek için projeyi yeniden yükleyin.",
  "No completed CSV imports are recorded for this property.": "Bu mülk için tamamlanmış CSV içe aktarma kaydı yok.",
  "rows,": "satır,",
  "Preview source-qualified candidates": "Kaynak kapsamına uygun adayları önizle",
  "Older CSV imports are not shown.": "Daha eski CSV içe aktarmaları gösterilmiyor.",
  "Compare two adjacent, complete query CSV windows from this property. Only rows observed in both windows can produce click, impression or worsened average-position candidates. Missing/hidden queries and provider coverage remain unknown; no action is approved.": "Bu mülkün ardışık, tam iki sorgu CSV dönemini karşılaştırın. Yalnızca her iki dönemde de gözlenen satırlar tıklama, gösterim veya kötüleşen ortalama konum adayları üretebilir. Eksik/gizli sorgular ve sağlayıcı kapsamı bilinmiyor; hiçbir eylem onaylanmaz.",
  "Earlier query export": "Önceki sorgu dışa aktarımı",
  "Later query export": "Sonraki sorgu dışa aktarımı",
  "Select earlier window": "Önceki dönemi seçin",
  "Select later window": "Sonraki dönemi seçin",
  "import": "içe aktarma",
  "Record comparable query change candidates": "Karşılaştırılabilir sorgu değişikliği adaylarını kaydet",
  "Compare two adjacent, complete page CSV windows. Only clean pages observed in both exports qualify; parameterized pages and absent rows are omitted, and no search-query intent is inferred.": "Ardışık, tam iki sayfa CSV dönemini karşılaştırın. Yalnızca her iki dışa aktarımda da gözlenen temiz sayfalar uygundur; parametreli sayfalar ve bulunmayan satırlar hariç tutulur, arama sorgusu amacı çıkarılmaz.",
  "Earlier page export": "Önceki sayfa dışa aktarımı",
  "Later page export": "Sonraki sayfa dışa aktarımı",
  "Record comparable page change candidates": "Karşılaştırılabilir sayfa değişikliği adaylarını kaydet",
  "CSV job acknowledged:": "CSV işi onaylandı:",
  "Check job progress, then refresh import history. Export coverage remains unknown.": "İşin ilerlemesini kontrol edin, ardından içe aktarma geçmişini yenileyin. Dışa aktarım kapsamı bilinmiyor.",

  "Project setup": "Proje kurulumu",
  "Resumable project onboarding": "Devam edilebilir proje kurulumu",
  "Inspect genuine paired Search Console query–page reports": "Gerçek eşleştirilmiş Search Console sorgu–sayfa raporlarını incele",
  "Review the budgeted first audit and source-backed next actions": "Bütçeli ilk denetimi ve kaynaklara dayalı sonraki adımları incele",
  "Back to organization and project context": "Kuruluş ve proje bağlamına dön",
  "Saving project setup.": "Proje kurulumu kaydediliyor.",
  "Loading project onboarding.": "Proje kurulumu yükleniyor.",
  "Project access unavailable": "Proje erişimi kullanılamıyor",
  "This project was not found in your authorized scope. Return to the workspace and choose an accessible project.": "Bu proje yetkili kapsamınızda bulunamadı. Çalışma alanına dönüp erişebildiğiniz bir proje seçin.",
  "Onboarding steps": "Kurulum adımları",
  "1 Website and goals": "1 Web sitesi ve hedefler",
  "2 Data source": "2 Veri kaynağı",
  "3 Advanced settings": "3 Gelişmiş ayarlar",
  "4 Complete": "4 Tamamlandı",
  "Read-only configuration": "Salt okunur yapılandırma",
  "An organization owner or admin can change project setup. Your project access is unchanged.": "Proje kurulumunu kuruluş sahibi veya yöneticisi değiştirebilir. Proje erişiminiz değişmez.",
  "Country:": "Ülke:",
  "Languages:": "Diller:",
  "Goal:": "Hedef:",
  "Source preference:": "Kaynak tercihi:",
  "Manual measurement notes (unverified):": "Elle girilen ölçüm notları (doğrulanmadı):",
  "Not set": "Ayarlanmadı",
  "None recorded": "Kayıt yok",
  "Website and primary goal": "Web sitesi ve ana hedef",
  "The canonical website is reviewed here and remains editable from project settings. Project languages describe SEO work; they do not change the OrganicSEOOps interface language.": "Standart web sitesi burada incelenir ve proje ayarlarından düzenlenebilir. Proje dilleri SEO çalışmalarını tanımlar; OrganicSEOOps arayüz dilini değiştirmez.",
  "Canonical website:": "Standart web sitesi:",
  "Primary target country or market": "Ana hedef ülke veya pazar",
  "Target language tags": "Hedef dil etiketleri",
  "One per line, such as en, tr, or en-US": "Her satırda bir tane; örneğin en, tr veya en-US",
  "Primary business goal": "Ana iş hedefi",
  "Reporting timezone": "Raporlama saat dilimi",
  "Use an IANA timezone such as UTC or Europe/Istanbul.": "UTC veya Europe/Istanbul gibi bir IANA saat dilimi kullanın.",
  "Save and continue to data source": "Kaydet ve veri kaynağına devam et",
  "Choose a data-source path": "Veri kaynağı yolunu seçin",
  "Saving a choice does not connect an account or start a job. Set up and upload a CSV in source status above. Google consent and bounded daily sync require a configured client and exact property authorization.": "Bir tercihi kaydetmek hesap bağlamaz veya iş başlatmaz. Yukarıdaki kaynak durumu bölümünde CSV kaynağını kurup dosya yükleyin. Google izni ve sınırlı günlük eşitleme, yapılandırılmış bir istemci ve tam mülk yetkilendirmesi gerektirir.",
  "Source choice": "Kaynak seçimi",
  "Connect Search Console later": "Search Console’u daha sonra bağla",
  "Import a Search Console CSV": "Search Console CSV dosyası içe aktar",
  "Skip for now and keep setup recoverable": "Şimdilik atla; kuruluma daha sonra devam et",
  "Use the isolated synthetic setup preview": "Ayrı tutulan sentetik kurulum önizlemesini kullan",
  "Back to website and goals": "Web sitesi ve hedeflere dön",
  "Save and continue to advanced settings": "Kaydet ve gelişmiş ayarlara devam et",
  "Optional advanced project settings": "İsteğe bağlı gelişmiş proje ayarları",
  "These editable inputs improve later evidence and defaults. They do not activate providers, schedules, commercial allowances, crawling, or publishing.": "Bu düzenlenebilir bilgiler sonraki kanıtları ve varsayılanları iyileştirir. Sağlayıcıları, zamanlamaları, ticari kullanım haklarını, taramayı veya yayını etkinleştirmez.",
  "Ideal audience": "İdeal hedef kitle",
  "Products or services": "Ürünler veya hizmetler",
  "Brand voice": "Marka üslubu",
  "Seed topics": "Başlangıç konuları",
  "One per line": "Her satırda bir tane",
  "Prohibited topics or claims": "Yasaklanan konular veya iddialar",
  "Conversion goals": "Dönüşüm hedefleri",
  "Brand names and aliases": "Marka adları ve alternatif adlar",
  "Manual measurement-quality notes": "Elle girilen ölçüm kalitesi notları",
  "Optional: note conversion definitions, consent gaps or tracking changes. Notes are unverified, not GA4 data.": "İsteğe bağlı: dönüşüm tanımlarını, izin eksiklerini veya izleme değişikliklerini belirtin. Notlar doğrulanmamıştır; GA4 verisi değildir.",
  "Competitor origins": "Rakip site kök adresleri",
  "One HTTP or HTTPS origin per line": "Her satırda bir HTTP veya HTTPS kök adresi",
  "Allowed research origins": "Araştırmaya izin verilen kök adresler",
  "One origin per line": "Her satırda bir kök adresi",
  "RSS or Atom feed URLs": "RSS veya Atom akış URL’leri",
  "Optional, up to five HTTPS URLs, one per line, each on an explicitly allowed research origin; no URL queries/credentials. Saving does not fetch a feed.": "İsteğe bağlı, en fazla beş HTTPS URL’si; her satırda bir tane ve her biri açıkça izin verilen bir araştırma kök adresinde olmalıdır. URL sorguları/kimlik bilgileri kullanılamaz. Kaydetmek akışı indirmez.",
  "Blocked research origins": "Araştırması engellenen kök adresler",
  "Preferred crawl page ceiling": "Tercih edilen tarama sayfa üst sınırı",
  "This is saved configuration, not an active crawl or commercial allowance.": "Bu kayıtlı yapılandırmadır; etkin tarama veya ticari kullanım hakkı değildir.",
  "Ignored tracking parameters": "Yok sayılan izleme parametreleri",
  "Exact case-sensitive names, one per line": "Büyük/küçük harfe duyarlı tam adlar; her satırda bir tane",
  "Pagination parameters": "Sayfalama parametreleri",
  "Facet parameters": "Filtre parametreleri",
  "Parameterized variants per path": "Yol başına parametreli varyantlar",
  "Ignored names deduplicate tracking-only URLs. Pagination, facet, and unlisted parameters keep their values within this safety cap.": "Yok sayılan adlar yalnızca izleme için kullanılan URL’leri tekilleştirir. Sayfalama, filtre ve listelenmeyen parametreler bu güvenlik sınırı içinde değerlerini korur.",
  "Real business locations": "Gerçek işletme konumları",
  "One reviewed location per line": "Her satırda incelenmiş bir konum",
  "Actual service areas": "Gerçek hizmet bölgeleri",
  "Contact details": "İletişim bilgileri",
  "Business hours": "Çalışma saatleri",
  "Business profile links": "İşletme profili bağlantıları",
  "One public HTTP or HTTPS URL per line": "Her satırda herkese açık bir HTTP veya HTTPS URL’si",
  "Profile and local eligibility notes": "Profil ve yerel uygunluk notları",
  "After saving these facts, review local business and profile evidence manually": "Bu bilgileri kaydettikten sonra yerel işletme ve profil kanıtlarını elle inceleyin",
  ". Profile eligibility and third-party reviews remain unverified.": ". Profil uygunluğu ve üçüncü taraf yorumları henüz doğrulanmadı.",
  "Back to data source": "Veri kaynağına dön",
  "Save and finish setup": "Kaydet ve kurulumu tamamla",
  "Project setup saved": "Proje kurulumu kaydedildi",
  "Your setup is resumable and remains editable. No import, provider connection, crawl, job, trial, or billing operation was started.": "Kurulumunuza devam edebilir ve onu düzenleyebilirsiniz. İçe aktarma, sağlayıcı bağlantısı, tarama, iş, deneme veya faturalandırma işlemi başlatılmadı.",
  "Edit website and goals": "Web sitesi ve hedefleri düzenle",
  "Edit source choice": "Kaynak seçimini düzenle",
  "Edit advanced settings": "Gelişmiş ayarları düzenle",
  "Synthetic demo setup preview": "Sentetik demo kurulum önizlemesi",
  "Synthetic demo": "Sentetik demo",
  "This static preview is not project evidence. It creates no live metric, finding, job, artifact, export, usage, or billing record.": "Bu statik önizleme proje kanıtı değildir. Canlı metrik, bulgu, iş, çıktı, dışa aktarım, kullanım veya faturalandırma kaydı oluşturmaz.",
  "Example source: labeled sample data · Example scope: 12 sample pages · Live data status: not connected": "Örnek kaynak: etiketli örnek veriler · Örnek kapsam: 12 örnek sayfa · Canlı veri durumu: bağlı değil",
  "Not selected": "Seçilmedi",
  "Google OAuth preferred; authorize separately": "Google OAuth tercih edildi; ayrı yetkilendirin",
  "CSV import selected; see existing source status": "CSV içe aktarma seçildi; mevcut kaynak durumuna bakın",
  "Skipped for now": "Şimdilik atlandı",
  "Synthetic demo selected": "Sentetik demo seçildi",
  "Website, market, language, and goal saved.": "Web sitesi, pazar, dil ve hedef kaydedildi.",
  "Choose a valid source path.": "Geçerli bir kaynak yolu seçin.",
  "Source preference saved. No connection, import, or job was started.": "Kaynak tercihi kaydedildi. Bağlantı, içe aktarma veya iş başlatılmadı.",
  "Project setup saved. No live work or commercial access was started.": "Proje kurulumu kaydedildi. Canlı çalışma veya ticari erişim başlatılmadı.",
  "Project onboarding is temporarily unavailable. Return to the workspace and retry.": "Proje kurulumu geçici olarak kullanılamıyor. Çalışma alanına dönüp tekrar deneyin.",
  "Project setup could not be saved. Check the fields and try again.": "Proje kurulumu kaydedilemedi. Alanları kontrol edip tekrar deneyin.",
  "This setup changed in another session. The latest saved version is now loaded; review it before saving again.": "Bu kurulum başka bir oturumda değiştirildi. En son kaydedilen sürüm yüklendi; tekrar kaydetmeden önce inceleyin.",
  "The save outcome is unknown. Retry safely; a completed earlier save will reload as a revision conflict.": "Kaydetme sonucu bilinmiyor. Güvenle tekrar deneyin; önceden tamamlanan bir kayıt sürüm çakışması olarak yeniden yüklenir.",
  "Local Search Console CSV property": "Yerel Search Console CSV mülkü",
  "This records a local file source for the selected exact origin. It does not authorize Google access.": "Bu işlem seçilen tam kök adresi için yerel dosya kaynağı kaydeder. Google erişimini yetkilendirmez.",
  "Set up local CSV source": "Yerel CSV kaynağını kur",
  "Upload acknowledgment is uncertain. Check project jobs or retry the same frozen file and metadata.": "Yükleme onayı belirsiz. Proje işlerini kontrol edin veya aynı sabitlenmiş dosya ve meta verilerle tekrar deneyin.",
  "Retry same CSV request": "Aynı CSV isteğini yeniden dene",
  "Import one Search Console performance CSV for": "Bir Search Console performans CSV dosyasını şu mülk için içe aktarın:",
  "Choose one exported table, not a ZIP: queries, pages, countries, devices, dates or search appearance. Limit: 1 MiB, 1,000 rows and a 90-day range in Pacific Time. Export completeness and hidden rows remain unknown.": "ZIP yerine dışa aktarılmış tek bir tablo seçin: sorgular, sayfalar, ülkeler, cihazlar, tarihler veya arama görünümü. Sınır: 1 MiB, 1.000 satır ve Pasifik saatine göre 90 günlük aralık. Dışa aktarımın tamlığı ve gizli satırlar bilinmiyor.",
  "CSV file": "CSV dosyası",
  "First exported date (Pacific Time)": "Dışa aktarılan ilk tarih (Pasifik saati)",
  "Last exported date (Pacific Time)": "Dışa aktarılan son tarih (Pasifik saati)",
  "Export search type": "Dışa aktarım arama türü",
  "Web": "Web",
  "Image": "Görsel",
  "Video": "Video",
  "News": "Haberler",
  "Discover": "Discover",
  "Google News": "Google Haberler",
  "Export date grain": "Dışa aktarım tarih ayrıntısı",
  "Aggregated range (queries, pages or other dimension)": "Toplu tarih aralığı (sorgular, sayfalar veya diğer boyut)",
  "Daily Dates table": "Günlük Tarihler tablosu",
  "I may use this export and confirm it belongs to this exact property and selected dates/type.": "Bu dışa aktarımı kullanma yetkim var; tam olarak bu mülke ve seçilen tarihlere/türe ait olduğunu onaylıyorum.",
  "Import CSV": "CSV içe aktar",
  "Disable this CSV source": "Bu CSV kaynağını devre dışı bırak",
  "Re-enable this CSV source": "Bu CSV kaynağını yeniden etkinleştir",
  "CSV source setup was not acknowledged. Refresh source status before retrying.": "CSV kaynağı kurulumu onaylanmadı. Tekrar denemeden önce kaynak durumunu yenileyin.",
  "Local CSV source recorded. Choose the export and its original metadata below.": "Yerel CSV kaynağı kaydedildi. Aşağıdan dışa aktarımı ve özgün meta verilerini seçin.",
  "Source setup outcome unknown. Reload source status before retrying.": "Kaynak kurulumu sonucu bilinmiyor. Tekrar denemeden önce kaynak durumunu yeniden yükleyin.",
  "Choose a nonempty CSV within 1 MiB and authorize this export.": "1 MiB sınırı içinde boş olmayan bir CSV seçin ve bu dışa aktarımı yetkilendirin.",
  "CSV could not be read. Choose the export again; no upload was sent.": "CSV okunamadı. Dışa aktarımı yeniden seçin; yükleme gönderilmedi.",
  "CSV import rejected. Check source access, dates/type, file limits and import allowance before choosing it again.": "CSV içe aktarımı reddedildi. Yeniden seçmeden önce kaynak erişimini, tarihleri/türü, dosya sınırlarını ve içe aktarma kullanım hakkını kontrol edin.",
  "Upload acknowledgment is uncertain. Retry only the same frozen CSV request or inspect project jobs.": "Yükleme onayı belirsiz. Yalnızca aynı sabitlenmiş CSV isteğini tekrar deneyin veya proje işlerini inceleyin.",
  "Upload outcome unknown. Retry only the same frozen CSV request or inspect project jobs.": "Yükleme sonucu bilinmiyor. Yalnızca aynı sabitlenmiş CSV isteğini tekrar deneyin veya proje işlerini inceleyin.",
  "CSV source state could not be changed. Reload to check its current scope and access.": "CSV kaynağı durumu değiştirilemedi. Güncel kapsamını ve erişimini kontrol etmek için yeniden yükleyin.",
  "CSV source record re-enabled; OAuth and API sync remain unavailable.": "CSV kaynağı kaydı yeniden etkinleştirildi; OAuth ve API eşitlemesi hâlâ kullanılamıyor.",
  "CSV source disabled. Prior import evidence remains available.": "CSV kaynağı devre dışı bırakıldı. Önceki içe aktarma kanıtları kullanılabilir.",
  "Source state outcome unknown. Reload before retrying.": "Kaynak durumu sonucu bilinmiyor. Tekrar denemeden önce yeniden yükleyin.",
  "Unreviewed Turkish setup, CSV, query and finding-review draft in local development. Provider values and remaining report interfaces remain English; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe kurulum, CSV, sorgu ve bulgu inceleme taslağı. Sağlayıcı değerleri ve kalan rapor arayüzleri İngilizcedir; iki dilde onay bekleniyor."
};
