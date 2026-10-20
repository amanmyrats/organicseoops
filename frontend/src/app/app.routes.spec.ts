import { Location } from '@angular/common';
import { createHash, webcrypto } from 'node:crypto';
import { TestBed } from '@angular/core/testing';
import { Meta, Title } from '@angular/platform-browser';
import { provideRouter, Router } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { AccountApi, ApiResult } from './account/account-api';
import { routes } from './app.routes';
import { environment } from '../environments/environment';
import { draftProductLanguage } from './product-language';
import { Security } from './account/security';
import { Invitation } from './account/invitation';
import { VerifyEmail } from './account/verify-email';
import { VerificationPending } from './account/verification-pending';
import { Login } from './account/login';
import { Register } from './account/register';
import { ForgotPassword } from './account/forgot-password';
import { ResetPassword } from './account/reset-password';
import { Acquisition } from './account/acquisition';
import { ProviderSettings } from './account/provider-settings';
import { JobDashboard } from './workspace/job-dashboard';
import { Overview } from './workspace/overview';
import { ProjectOnboarding } from './workspace/project-onboarding';
import { ProjectReports } from './workspace/project-reports';

function fixtureDigest(value: unknown): string {
  const sorted = (item: unknown): unknown => item && typeof item === 'object' && !Array.isArray(item)
    ? Object.fromEntries(Object.keys(item).sort().map(key => [key, sorted((item as Record<string, unknown>)[key])])) : item;
  return createHash('sha256').update(JSON.stringify(sorted(value))).digest('hex');
}

function recordedPaidTiming(api: AccountApiStub) {
  const timing = { ...api.paidTimingResult.body['timing'] as Record<string, unknown>, state: 'recorded',
    tracking_started_at: '2026-01-01T00:00:00.000999+00:00', observed_at: '2026-01-01T00:00:00.333001+00:00',
    source_digest: 'a'.repeat(64), elapsed_milliseconds: 332 };
  api.paidTimingResult = { status: 200, body: { organization_id: 7, timing } };
  api.billingResult.body['first_paid_observation'] = { method: 'first-active-observation-v1', organization_id: 7,
    state: 'recorded', observation: { attempt_id: 91, source_digest: timing.source_digest, observed_at: timing.observed_at,
      provider_occurred_at: '2026-01-01T00:00:00Z', environment: 'sandbox', offer_version: 'agency-launch-v1', currency_code: 'USD',
      interpretation: 'historical_first_active_server_observation_not_current_access_or_provider_activation_time' } };
  return structuredClone(api.paidTimingResult);
}

function recordedTrialPaidTiming(api: AccountApiStub, activationMethod = 'automatic') {
  recordedPaidTiming(api);
  const activation = { activation_method: activationMethod, offer_version: 'agency-launch-v1',
    started_at: '2026-01-01T00:00:00.000999+00:00', audited_at: '2026-01-01T00:00:00.001002+00:00', source_digest: 'b'.repeat(64) };
  api.trialActivationResult = { status: 200, body: { organization_id: 7, trial_activation: {
    method: 'audited-trial-activation-v1', state: 'recorded', activation } } };
  const source = { activation_method: activationMethod, method: 'trial-to-first-paid-server-timing-v1',
    observed_at: '2026-01-01T00:00:00.333001+00:00', organization_id: 7, paid_source_digest: 'a'.repeat(64),
    trial_source_digest: activation.source_digest, trial_started_at: activation.started_at };
  const { organization_id, ...fields } = source;
  api.trialPaidTimingResult = { status: 200, body: { organization_id, timing: { ...fields, state: 'recorded',
    precision: 'whole_milliseconds_rounded_down', elapsed_milliseconds: 332, source_digest: fixtureDigest(source),
    interpretation: 'audited_trial_start_to_first_paid_server_observation_not_provider_activation_or_cohort' } } };
  return structuredClone(api.trialPaidTimingResult);
}

function recordedTrialPaidWindow(api: AccountApiStub, assessedAt = '2026-02-08T00:00:00+00:00', paidAt: string | null = '2026-01-01T00:00:00.333001+00:00') {
  recordedTrialPaidTiming(api);
  const history = api.billingResult.body['first_paid_observation'] as Record<string, unknown>;
  if (paidAt === null) { history['state'] = 'not_observed'; history['observation'] = null; }
  else (history['observation'] as Record<string, unknown>)['observed_at'] = paidAt;
  const end = '2026-02-07T00:00:00.000999+00:00';
  const mature = assessedAt >= end; // Fixture dates use the same UTC spelling, retaining sub-millisecond boundaries.
  const source = { method: 'original-trial-paid-observation-window-v1', organization_id: 7, window_days: 37,
    assessed_at: assessedAt, trial_started_at: '2026-01-01T00:00:00.000999+00:00', window_ends_at: end,
    paid_observed_at: paidAt, trial_source_digest: 'b'.repeat(64), paid_source_digest: paidAt === null ? null : 'a'.repeat(64),
    paid_state: paidAt === null ? 'not_observed' : 'recorded', state: mature ? 'mature' : 'immature',
    outcome: mature ? paidAt !== null && paidAt < end ? 'observed_within_window' : 'not_observed_within_window' : null };
  const { organization_id, paid_state, ...fields } = source;
  api.trialPaidWindowResult = { status: 200, body: { organization_id, window: { ...fields, source_digest: fixtureDigest(source),
    interpretation: 'fixed_half_open_original_trial_paid_server_window_not_provider_activation_or_conversion_rate' } } };
  return structuredClone(api.trialPaidWindowResult);
}

class AccountApiStub {
  loginResult: ApiResult = { status: 400, body: { errors: [{ message: 'private backend detail' }] } };
  mfaResult: ApiResult = { status: 400, body: {} };
  authenticatorsResult: ApiResult = { status: 404, body: {} };
  platformProvidersResult: ApiResult = { status: 403, body: {} };
  acquisitionResult: ApiResult = { status: 403, body: {} };
  platformModelsResult: ApiResult = { status: 403, body: {} };
  platformAIRoutingResult: ApiResult = { status: 403, body: {} };
  savedPlatformRoutes: Record<string, unknown>[] = [];
  savedModels: Record<string, unknown>[] = [];
  aiCatalogResult: ApiResult = { status: 404, body: {} };
  aiHistoryResult: ApiResult = { status: 200, body: { jobs: [], has_more: false } };
  projectAIRoutingResult: ApiResult = { status: 200, body: { policy: null, effective: null } };
  savedProjectRoutes: Record<string, unknown>[] = [];
  aiRequests: Record<string, unknown>[] = [];
  savedPlatformSecrets: string[] = [];
  googleApplicationResult: ApiResult = { status: 403, body: {} };
  savedGoogleSecrets: string[] = [];
  savedAnalyticsSecrets: string[] = [];
  savedBusinessSecrets: string[] = [];
  ga4GrantRows: Record<string, unknown>[] = [];
  ga4JobResult: Record<string, unknown> | null = null;
  ga4QualityRows: Record<string, unknown>[] = [];
  performanceKeyResult: ApiResult = { status: 403, body: {} };
  savedPerformanceKeys: string[] = [];
  organizationProviderResult: ApiResult = { status: 403, body: {} };
  savedOrganizationSecrets: string[] = [];
  organizationPerformanceResult: ApiResult = { status: 403, body: {} };
  savedOrganizationPerformanceKeys: string[] = [];
  totpSetupResult: ApiResult = { status: 404, body: { meta: { secret: 'STAFFSETUPKEY' } } };
  recoveryCodesResult: ApiResult = { status: 200, body: { data: { unused_codes: ['first-code', 'second-code'] } } };
  mfaCodes: string[] = [];
  logoutResult: ApiResult = { status: 500, body: {} };
  verificationResult: ApiResult = { status: 200, body: { state: 'pending' } };
  passwordRequestResult: ApiResult = { status: 200, body: { status: 200 } };
  passwordResetInfoResult: ApiResult = { status: 200, body: { status: 200 } };
  organizationsResult: ApiResult = { status: 200, body: { organizations: [], has_more: false } };
  projectsResult: ApiResult = { status: 200, body: { projects: [], has_more: false } };
  teamResult: ApiResult = { status: 200, body: { members: [], invitations: [], events: [], has_more: false } };
  jobsResult: ApiResult = { status: 200, body: { jobs: [], has_more: false } };
  jobSchedulesResult: ApiResult = { status: 200, body: { schedules: [], has_more: false } };
  onboardingResult: ApiResult = { status: 200, body: {
    project: { id: 9, organization_id: 7, name: 'Onboarding project', canonical_origin: 'https://onboarding.example', aliases: [], access_restricted: false, role: 'owner' },
    configuration: {
      project_id: 9, canonical_origin: 'https://onboarding.example', target_country: '', target_languages: [],
      business_goal: '', timezone: 'UTC', audience: '', offer: '', brand_voice: '', seed_topics: [],
      prohibited_claims: [], conversion_goals: [], brand_aliases: [], measurement_notes: '', competitor_origins: [],
      research_allowed_origins: [], research_blocked_origins: [], rss_feed_urls: [], crawl_page_limit: null,
      ignored_query_parameters: [], pagination_query_parameters: [], facet_query_parameters: [], query_variant_limit: 5,
      business_locations: [], service_areas: [], contact_details: '', business_hours: '', profile_urls: [],
      local_eligibility_notes: '', source_choice: 'undecided', source_state: 'not_selected', current_step: 'basics',
      revision: 0, updated_at: null,
    },
  } };
  onboardingHandler?: (details: Record<string, unknown>) => Promise<ApiResult>;
  onboardingLoadHandler?: (organizationId: number, projectId: number) => Promise<ApiResult>;
  sourcesHandler?: (organizationId: number, projectId: number) => Promise<ApiResult>;
  googleGrantsHandler?: (organizationId: number, projectId: number) => Promise<ApiResult>;
  googleGrantRows: Record<string, unknown>[] = [];
  selectedGoogleSites: string[] = [];
  revokedGoogleGrants: number[] = [];
  syncRequests: {connectionId: number; day: string; dimensions: string[]; key: string}[] = [];
  coverageRequests: {connectionId: number; inspectionUrl: string; key: string}[] = [];
  indexationBuilt = false;
  performanceKeyAvailable = false;
  performanceHistory = false;
  cruxInspections: number[][] = [];
  cruxHandler?: () => Promise<ApiResult>;
  cruxPolicyInspections: number[][] = [];
  cruxPolicyHandler?: () => Promise<ApiResult>;
  performanceRequests: { target: string; sources: string[]; key: string }[] = [];
  backfillRequests: {connectionId: number; startDay: string; endDay: string; dimension: string; key: string}[] = [];
  scheduleRequests: {connectionId: number; dimension: string; key: string}[] = [];
  findingRows: Record<string, unknown>[] = [];
  reportRows: Record<string, unknown>[] = [];
  exportInventoryResult: ApiResult = { status: 200, body: {
    organization_id: 7, scope: 'record_counts_only_not_a_complete_export_or_deletion_receipt',
    customer: [{ model: 'tenancy.Project', count: 1, latest_id: 9 }],
    artifact_counts: { projects: [{ project_id: 9, visible_count: 1 }] },
  } };
  exportHistoryRows: Record<string, unknown>[] = [
    { id: 42, state: 'ready', created_at: '2026-09-29T08:00:00Z',
      manifest_path: '/api/organizations/7/export/snapshots/42/' },
    { id: 41, state: 'failed', created_at: '2026-09-29T07:00:00Z', manifest_path: null },
  ];
  closureStatusResult: ApiResult = { status: 200, body: {
    organization_id: 7, state: 'open', closed_at: null, close_action_available: false,
    deletion: null, billing_cancellation: null,
    remote_revocation_pending: { search_console: 0, analytics: 0 },
    pending_grants: { search_console: [], analytics: [] },
    limitations: 'Already downloaded copies cannot be erased. Hosted backup expiry requires verification.',
  } };
  closureRequests: number[] = [];
  closureBillingChecks: number[] = [];
  closureGrantAttempts: { organizationId: number; provider: string; grantId: number }[] = [];
  reportShareRows: Record<string, unknown>[] = [];
  researchRequests: Record<string, unknown>[] = [];
  researchJob: Record<string, unknown> | null = null;
  topicReviews: Record<string, unknown>[] = [];
  topicInputs: Record<string, unknown>[] = [];
  topicDiscoveryInputs: Record<string, unknown>[] = [];
  topicSaveStatus = 201;
  topicSourceCurrent = true;
  topicReviewHandler?: (projectId: number, reviewId: number) => Promise<ApiResult>;
  topicEvidence = { kind: 'public_feed_item', title: '<script>Inert synthetic feed topic</script>',
    url: 'https://research-source.example.invalid/article', source_feeds: ['https://research-source.example.invalid/rss'],
    published_at: null, freshness: 'unknown', trend_state: 'not_measured', evergreen_state: 'unknown', business_relevance: 'not_evaluated' };
  briefInputs: Record<string, unknown>[] = [];
  briefRows: Record<string, unknown>[] = [];
  firstAuditRequests: number[] = [];
  firstAuditCandidate: Record<string, unknown> | null = null;
  firstAuditJob: Record<string, unknown> | null = null;
  firstAuditDemo = false;
  firstAuditHistoryReads: number[][] = [];
  firstAuditHistoryResult: ApiResult = { status: 200, body: {
    method: 'bounded-first-audit-completion-v1', organization_id: 7, project_id: 9,
    scope: 'historical_organization_first_bounded_completion_within_selected_project_not_current_use_or_first_value',
    state: 'recorded', job_id: 77, source_digest: 'a'.repeat(64),
    tracking_started_at: '2026-09-29T10:00:00Z', observed_at: '2026-09-30T10:00:00Z',
    page_limit: 3, pages_observed: 2, successful_html_pages: 1,
    coverage: 'bounded_discovered_http_sample_not_complete_site', robots_status: 'available', discovery_truncated: false,
  } };
  firstAuditHistoryHandler?: () => Promise<ApiResult>;
  usefulnessTimingReads: number[][] = [];
  usefulnessTimingResult: ApiResult = { status: 200, body: {
    method: 'bounded-audit-usefulness-timing-v1', organization_id: 7, project_id: 9, state: 'recorded',
    interpretation: 'organization_age_at_first_server_subjective_ack_not_business_value_time',
    precision: 'whole_milliseconds_rounded_down', tracking_started_at: '2026-09-30T10:00:00.123900Z',
    acknowledged_at: '2026-09-30T10:00:00.456100Z', source_digest: 'd'.repeat(64), elapsed_milliseconds: 332 } };
  usefulnessTimingHandler?: () => Promise<ApiResult>;
  auditActionRow: Record<string, unknown> = { action_id: 'a64070a5-91a1-4198-9556-651ab00c11bc', revision: 2,
    state: 'accepted', action_kind: 'refresh', source_type: 'opportunity', source_id: 45, source_current: true,
    affected_urls: ['https://onboarding.example/'], assignee_id: 7, acceptance_criteria: 'Human review criteria.',
    reason: 'Human accepts review.', change_summary: '', verification_note: '', outcome_note: '',
    implemented_at: null, verified_at: null, outcome_reviewed_at: null, execution: 'human_only_no_website_change',
    recorded_at: '2026-09-30T10:05:00Z' };
  auditActionResult: ApiResult = { status: 200, body: { organization_id: 7, project_id: 9,
    action_id: 'a64070a5-91a1-4198-9556-651ab00c11bc', revision: 2, source: {
      method: 'bounded-audit-human-action-source-v1', organization_id: 7, project_id: 9, job_id: 77,
      audit_source_digest: 'a'.repeat(64), decision_digest: 'b'.repeat(64), page_sha256: 'c'.repeat(64),
      audit_completed_at: '2026-09-30T10:00:00Z', diagnostics_id: 31, diagnostics_observed_at: '2026-09-30T10:01:00Z',
      finding_id: 32, finding_detected_at: '2026-09-30T10:02:00Z', detector: 'raw_meta_description_missing_candidate',
      opportunity_id: 45, opportunity_reviewed_at: '2026-09-30T10:03:00Z', action_review_id: 46,
      action_accepted_at: '2026-09-30T10:05:00Z', action_kind: 'refresh',
      coverage: 'bounded_discovered_http_sample_not_complete_site', first_value: 'not_established', first_ever_occurrence: 'not_established',
    } } };
  auditActionReads: {organizationId: number; projectId: number; actionId: string; revision: number}[] = [];
  auditActionHandler?: () => Promise<ApiResult>;
  usefulnessReads: { organizationId: number; projectId: number; actionId?: string; revision?: number }[] = [];
  usefulnessPosts: { organizationId: number; projectId: number; actionId: string; revision: number; proof: string }[] = [];
  usefulnessSaved: Record<string, unknown> | null = null;
  usefulnessLose = false;
  usefulnessDrop = false;
  usefulnessProof = 'Synthetic_original_proof:only';
  usefulnessExpires = () => new Date(Date.now() + 240000).toISOString();
  usefulnessHandler?: (result: ApiResult, actionId?: string) => Promise<ApiResult>;
  usefulnessPostHandler?: (result: ApiResult) => Promise<ApiResult>;
  usefulnessSource() {
    return { method: 'bounded-audit-usefulness-ack-v1', acknowledging_actor_id: 7,
      evidence: structuredClone(this.auditActionResult.body['source']),
      interpretation: 'explicit_subjective_useful_next_action_not_implementation_or_seo_outcome' };
  }
  usefulnessHistory() {
    return this.usefulnessSaved || { method: 'bounded-audit-usefulness-ack-v1', organization_id: 7, project_id: 9,
      interpretation: 'explicit_subjective_useful_next_action_not_implementation_or_seo_outcome',
      scope: 'historical_organization_first_acknowledgment_within_selected_project_not_current_source_use', state: 'not_observed_for_project' };
  }
  reportCreateIds: number[][] = [];
  intentRows: Record<string, unknown>[] = [];
  savedIntent: Record<string, unknown>[] = [];
  actionRows: Record<string, unknown>[] = [];
  savedActions: Record<string, unknown>[] = [];
  actionCurrentUserId = 7;
  outcomeRows: Record<string, unknown>[] = [];
  technicalOutcomeRows: Record<string, unknown>[] = [];
  recordedTechnicalInputs: {before: number; after: number}[] = [];
  localAssessmentRows: Record<string, unknown>[] = [];
  savedLocalAssessments: Record<string, unknown>[] = [];
  indexationCrawlChoices: {id: number; completed_at: string}[] = [{ id: 42, completed_at: '2026-09-27T12:00:00Z' }];
  recordedOutcomeInputs: {connectionId: number; before: number; after: number}[] = [];
  sourceImportHistoryHandler?: (organizationId: number, projectId: number, connectionId: number) => Promise<ApiResult>;
  coverageStatusHandler?: (projectId: number, connectionId: number) => Promise<ApiResult>;
  syncStatusHandler?: (projectId: number, connectionId: number) => Promise<ApiResult>;
  queriesHandler?: (organizationId: number, projectId: number, connectionId: number) => Promise<ApiResult>;
  brandReviews: { queryId: number; revision: number; label: string; reason: string }[] = [];
  csvStateChanges: boolean[] = [];
  onboardingUpdates: Record<string, unknown>[] = [];
  jobDetailResult: ApiResult = { status: 200, body: { job: {
    id: 3, project_id: 9, status: 'succeeded', progress_percent: 100,
    error_category: '', retry_of: null, cancel_requested: false,
    updated_at: '2026-09-24T10:00:00Z', steps: [], output: { sample_length: 4 },
  } } };
  jobDetailsHandler?: (jobId: number) => Promise<ApiResult>;
  diagnosticHandler?: () => Promise<ApiResult>;
  diagnosticKeys: string[] = [];
  retriedKeys: string[] = [];
  cancelledJobIds: number[] = [];
  scheduleKeys: string[] = [];
  scheduleToggles: boolean[] = [];
  scheduleHandler?: () => Promise<ApiResult>;
  invitationAcceptResult: ApiResult = { status: 200, body: { accepted: true } };
  transferResult: ApiResult = { status: 200, body: { transfer: null } };
  proposedMembers: number[] = [];
  acceptedTransfers: number[] = [];
  cancelledTransfers: number[] = [];
  leftOrganizations: number[] = [];
  projectsHandler?: (organizationId: number) => Promise<ApiResult>;
  organizationsHandler?: () => Promise<ApiResult>;
  teamHandler?: (organizationId: number) => Promise<ApiResult>;
  sessionResult: ApiResult = { status: 200, body: { data: [
    { id: 1, user_agent: 'Current browser', ip: '127.0.0.1', created_at: 1, is_current: true },
    { id: 2, user_agent: 'Other browser', ip: '192.0.2.2', created_at: 2, is_current: false },
  ] } };
  endedSessions: number[] = [];
  savedProductLanguage: 'en' | 'tr' = 'en';
  personalExportCalls = 0;
  personalClosureResult: ApiResult = { status: 200, body: { action_available: false,
    requires_org_exit: false, retained_identity: 'restricted_policy_review_not_erased' } };
  personalCloseCalls = 0;
  passwordResetKeys: string[] = [];
  invitationTokens: string[] = [];
  invitedEmail = '';
  invitedRole = '';
  invitedProjects: number[] = [];
  removedMembers: number[] = [];
  reissuedInvitations: number[] = [];

  signup(_email: string, _password: string): Promise<ApiResult> { return Promise.resolve({ status: 200, body: {} }); }
  login() { return Promise.resolve(this.loginResult); }
  authenticateMfa(code: string) {
    this.mfaCodes.push(code);
    return Promise.resolve(this.mfaResult);
  }
  authenticators() { return Promise.resolve(this.authenticatorsResult); }
  productLanguage(): Promise<ApiResult> { return Promise.resolve({ status: 200, body: { language: this.savedProductLanguage,
    current_ui_language: 'en', current_email_language: 'en' } }); }
  saveProductLanguage(language: 'en' | 'tr') {
    this.savedProductLanguage = language;
    return this.productLanguage();
  }
  platformProviders() { return Promise.resolve(this.platformProvidersResult); }
  acquisitionMilestones() { return Promise.resolve(this.acquisitionResult); }
  publicAnalyticsObservations() { return Promise.resolve({ status: 403, body: {} }); }
  trialPaidCohort(_month = '') { return Promise.resolve({ status: 403, body: {} }); }
  platformModels() { return Promise.resolve(this.platformModelsResult); }
  savePlatformModel(data: Record<string, unknown>) {
    this.savedModels.push(data);
    return Promise.resolve({ status: 200, body: { id: 9 } });
  }
  platformAIRouting() { return Promise.resolve(this.platformAIRoutingResult); }
  savePlatformAIRouting(data: Record<string, unknown>) {
    this.savedPlatformRoutes.push(data);
    return Promise.resolve({ status: 200, body: { policy: { id: 31, project_id: null, ...data, revision: 1 } } });
  }
  removePlatformAIRouting() { return Promise.resolve({ status: 200, body: { removed: true, policy: null } }); }
  projectAITextCatalog() { return Promise.resolve(this.aiCatalogResult); }
  projectAIRouting() { return Promise.resolve(this.projectAIRoutingResult); }
  saveProjectAIRouting(_orgId: number, projectId: number, data: Record<string, unknown>) {
    this.savedProjectRoutes.push(data);
    return Promise.resolve({ status: 200, body: { policy: { id: 32, project_id: projectId, ...data, revision: 1 } } });
  }
  removeProjectAIRouting() {
    return Promise.resolve({ status: 200, body: { removed: true, policy: null, effective: null } });
  }
  createAIText(_orgId: number, projectId: number, data: Record<string, unknown>) {
    this.aiRequests.push(data);
    return Promise.resolve({ status: 202, body: { job: { id: 77, project_id: projectId, status: 'queued',
      error_category: '', text: '', attempted_units: 0, cancel_requested: false,
      estimated_max_cost_usd: '0.000385', routing_source: data['model_id'] === null ? 'system' : 'explicit',
      fallback_index: 0, usage: null, updated_at: '2026-09-27T00:00:00Z' } } });
  }
  aiTextJob(_orgId: number, projectId: number, jobId: number) {
    return Promise.resolve({ status: 200, body: { job: { id: jobId, project_id: projectId, status: 'succeeded',
      error_category: '', text: 'Result text', attempted_units: 1, cancel_requested: false,
      estimated_max_cost_usd: '0.000385', routing_source: 'explicit', fallback_index: 0,
      usage: { provider_id: 5, model_id: 3, operation_version: 'ai-text-v2', request_status: 'completed',
        error_category: '', input_tokens: 12, output_tokens: 5, duration_ms: 80,
        estimated_cost_usd: '0.000014', reported_cost_usd: null,
        provider_request_id: 'req_safe', provider_response_id: 'resp_safe', web_search_used: false, tool_call_count: 0 },
      updated_at: '2026-09-27T00:01:00Z' } } });
  }
  aiTextHistory() { return Promise.resolve(this.aiHistoryResult); }
  cancelAIText() { return Promise.resolve({ status: 404, body: {} }); }
  platformGoogleOAuthApp() { return Promise.resolve(this.googleApplicationResult); }
  platformGoogleAnalyticsApp(): Promise<ApiResult> { return Promise.resolve({ status: 200, body: { state: 'unconfigured', redirect_uri: '' } }); }
  platformGoogleBusinessApp(method = 'GET', payload?: Record<string, unknown>): Promise<ApiResult> {
    if (method === 'POST') this.savedBusinessSecrets.push(String(payload?.['client_secret']));
    return Promise.resolve({ status: 200, body: method === 'GET' ? { state: 'unconfigured', redirect_uri: '' } : {} });
  }
  savedPaddle: { environment: string; payload: Record<string, unknown> }[] = [];
  retriedPaddleReceipts: { id: number; reason: string }[] = [];
  receiptInspection: Record<string, unknown> = {};
  inspectedPaddleReceipts: { id: number; reason: string }[] = [];
  noticeInspection: Record<string, unknown> = {};
  inspectedNotices: { organization: number; notice: number; reason: string }[] = [];
  retriedUnknownNotices: { id: number; reason: string }[] = [];
  emailFeedbackInspection: Record<string, unknown> = {};
  inspectedEmailFeedback: { user: number; address: number; suppression: number; reason: string }[] = [];
  suppressionDiscoveryCalls = 0;
  accountMailInspection: Record<string, unknown> = {};
  inspectedAccountMail: { user: number; address: number; delivery: number; reason: string }[] = [];
  clearedEmailSuppressions: { id: number; reason: string }[] = [];
  paddleStatuses: Record<string, 'unconfigured' | 'active' | 'revoked'> = { sandbox: 'unconfigured', live: 'unconfigured' };
  billingResult: ApiResult = { status: 200, body: { seller_configured: false,
    can_start_new_checkout: false,
    offer_version: 'agency-launch-v1', subscription_linked: false, portal_available: false,
    billing_access_state: 'unverified', attempts: [] } };
  billingRequests: { org: number; key: string }[] = [];
  portalRequests: number[] = [];
  portalResult: ApiResult = { status: 409, body: {} };
  checkoutResolution: ApiResult = { status: 404, body: {} };
  billingWait: Promise<ApiResult> | null = null;
  billingReads: number[] = [];
  paidTimingReads: number[] = [];
  paidTimingResult: ApiResult = { status: 200, body: { organization_id: 7, timing: {
    method: 'first-active-observation-timing-v1', state: 'not_observed', precision: 'whole_milliseconds_rounded_down',
    tracking_started_at: null, observed_at: null, source_digest: null, elapsed_milliseconds: null,
    interpretation: 'organization_age_at_first_paid_server_observation_not_provider_activation_trial_or_cohort' } } };
  paidTimingHandler?: () => Promise<ApiResult>;
  organizationPaidObservationTiming(org: number) {
    this.paidTimingReads.push(org);
    return this.paidTimingHandler?.() || Promise.resolve(structuredClone(this.paidTimingResult));
  }
  trialActivationReads: number[] = [];
  trialPaidTimingReads: number[] = [];
  trialActivationResult: ApiResult = { status: 200, body: { organization_id: 7, trial_activation: {
    method: 'audited-trial-activation-v1', state: 'unknown', activation: null } } };
  trialPaidTimingResult: ApiResult = { status: 409, body: {} };
  trialActivationHandler?: () => Promise<ApiResult>;
  trialPaidTimingHandler?: () => Promise<ApiResult>;
  organizationTrialActivation(org: number) {
    this.trialActivationReads.push(org);
    return this.trialActivationHandler?.() || Promise.resolve(structuredClone(this.trialActivationResult));
  }
  organizationTrialPaidTiming(org: number) {
    this.trialPaidTimingReads.push(org);
    return this.trialPaidTimingHandler?.() || Promise.resolve(structuredClone(this.trialPaidTimingResult));
  }
  trialPaidWindowReads: number[] = [];
  trialPaidWindowResult: ApiResult = { status: 409, body: {} };
  trialPaidWindowHandler?: () => Promise<ApiResult>;
  organizationTrialPaidWindow(org: number) {
    this.trialPaidWindowReads.push(org);
    return this.trialPaidWindowHandler?.() || Promise.resolve(structuredClone(this.trialPaidWindowResult));
  }
  organizationCheckout(organizationId: number) { this.billingReads.push(organizationId); return this.billingWait || Promise.resolve({ ...this.billingResult,
    body: { first_paid_observation: { method: 'first-active-observation-v1', organization_id: organizationId,
      state: 'not_observed', observation: null }, ...this.billingResult.body } }); }
  createOrganizationPortal(org: number) { this.portalRequests.push(org); return Promise.resolve(this.portalResult); }
  startOrganizationCheckout(org: number, key: string): Promise<ApiResult> {
    this.billingRequests.push({ org, key });
    this.billingResult = { status: 200, body: { seller_configured: true, offer_version: 'agency-launch-v1',
      can_start_new_checkout: false,
      subscription_linked: false, portal_available: false,
      billing_access_state: 'unverified',
      attempts: [{ id: 91, state: 'ready', created_at: '2026-09-28T00:00:00Z',
        checkout_url: `${window.location.origin}/account/billing/checkout?_ptxn=txn_${'a'.repeat(26)}`,
        payment_confirmed: false, payment_captured: false }] } };
    return Promise.resolve({ status: 200, body: { attempt_id: 91, state: 'ready', payment_confirmed: false,
      checkout_url: `${window.location.origin}/account/billing/checkout?_ptxn=txn_${'a'.repeat(26)}` } });
  }
  resolveCheckoutTransaction(_transactionId: string) { return Promise.resolve(this.checkoutResolution); }
  platformPaddleSeller(environment: string): Promise<ApiResult> { return Promise.resolve({ status: 200, body: {
    environment, state: this.paddleStatuses[environment], product_id: '', price_id: '', catalog_verified: false,
  } }); }
  setPlatformPaddleSeller(environment: string, payload: Record<string, unknown>) {
    this.savedPaddle.push({ environment, payload });
    this.paddleStatuses[environment] = 'active';
    return Promise.resolve({ status: 200, body: { configured: true, catalog_verified: false } });
  }
  rotatePlatformPaddleApiKey(_environment: string, _apiKey: string) {
    return Promise.resolve({ status: 200, body: { rotated: true } });
  }
  revokePlatformPaddleSeller(environment: string) {
    this.paddleStatuses[environment] = 'revoked';
    return Promise.resolve({ status: 200, body: { revoked: true } });
  }
  retryPlatformPaddleReceipt(id: number, reason: string) {
    this.retriedPaddleReceipts.push({ id, reason });
    return Promise.resolve({ status: 202, body: { queued: true } });
  }
  inspectPlatformPaddleReceipt(id: number, reason: string) {
    this.inspectedPaddleReceipts.push({ id, reason });
    return Promise.resolve({ status: 200, body: this.receiptInspection });
  }
  inspectPlatformNotice(organization: number, notice: number, reason: string) {
    this.inspectedNotices.push({ organization, notice, reason });
    return Promise.resolve({ status: 200, body: this.noticeInspection });
  }
  retryPlatformNotice(id: number, reason: string) {
    this.retriedUnknownNotices.push({ id, reason });
    return Promise.resolve({ status: 202, body: { queued: true, possible_duplicate: true } });
  }
  platformEmailSuppressions() {
    this.suppressionDiscoveryCalls++;
    throw new Error('Global discovery is retired');
  }
  inspectPlatformEmailFeedback(user: number, address: number, suppression: number, reason: string) {
    this.inspectedEmailFeedback.push({ user, address, suppression, reason });
    return Promise.resolve({ status: 200, body: this.emailFeedbackInspection });
  }
  inspectPlatformAccountMail(user: number, address: number, delivery: number, reason: string) {
    this.inspectedAccountMail.push({ user, address, delivery, reason });
    return Promise.resolve({ status: 200, body: this.accountMailInspection });
  }
  clearPlatformEmailSuppression(id: number, reason: string) {
    this.clearedEmailSuppressions.push({ id, reason });
    return Promise.resolve({ status: 200, body: { cleared: true } });
  }
  ga4Grants(_organizationId: number, projectId: number): Promise<ApiResult> {
    return Promise.resolve({ status: 200, body: { project_id: projectId, grants: this.ga4GrantRows, has_more: false } });
  }
  startGA4OAuth(_organizationId: number, _projectId: number) {
    return Promise.resolve({ status: 201, body: { authorization_url:
      'https://accounts.google.com/o/oauth2/v2/auth?scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fanalytics.readonly&state=fixture-state' } });
  }
  selectGA4Property(_organizationId: number, projectId: number, grantId: number, propertyId: string,
    origin: string, revision: number) {
    this.ga4GrantRows = this.ga4GrantRows.map((item) => item['id'] === grantId
      ? { ...item, property_id: propertyId, selected_origins: [origin], scope_current: true, revision: revision + 1 } : item);
    return Promise.resolve({ status: 200, body: { id: grantId, project_id: projectId, state: 'pending_selection',
      revision: revision + 1, source_status: 'not_linked_no_data_sync' } });
  }
  linkGA4Source(_organizationId: number, projectId: number, grantId: number, revision: number) {
    this.ga4GrantRows = this.ga4GrantRows.map((item) => item['id'] === grantId
      ? { ...item, state: 'active', revision: revision + 1, source_status: 'configured_no_data_sync' } : item);
    return Promise.resolve({ status: 200, body: { id: grantId, project_id: projectId, state: 'active',
      source_status: 'configured_no_data_sync' } });
  }
  revokeGA4Grant(_organizationId: number, projectId: number, grantId: number) {
    this.ga4GrantRows = this.ga4GrantRows.map((item) => item['id'] === grantId
      ? { ...item, state: 'revoked', property_id: '', selected_origins: [], source_status: 'not_linked_no_data_sync' } : item);
    return Promise.resolve({ status: 200, body: { id: grantId, project_id: projectId,
      state: 'revoked', source_status: 'not_linked_no_data_sync' } });
  }
  queueGA4Sync(_org: number, projectId: number, connectionId: number, day: string,
    reportKind: 'all_channels' | 'organic_search', _key: string) {
    this.ga4JobResult = { id: 719, status: 'queued', day, report_kind: reportKind,
      hostname: 'onboarding.example',
      error_category: '', requests_attempted: 0, pages_recorded: 0,
      source_coverage: 'unavailable', sampling_or_threshold_gaps: null };
    return Promise.resolve({ status: 202, body: { project_id: projectId, connection_id: connectionId,
      job_id: 719, status: 'queued', max_requests: 5, report_kind: reportKind,
      source_coverage: reportKind === 'organic_search' ? 'ga4_organic_session_channel_hostname_filtered'
        : 'hostname_filtered_reporting_gaps_unknown' } });
  }
  ga4SyncStatus(_org: number, projectId: number, connectionId: number): Promise<ApiResult> {
    return Promise.resolve({ status: 200, body: { project_id: projectId, connection_id: connectionId,
      source_current: true, job: this.ga4JobResult, pages: [] } });
  }
  cancelGA4Sync(_org: number, projectId: number, connectionId: number, _jobId: number): Promise<ApiResult> {
    this.ga4JobResult = { ...(this.ga4JobResult || {}), status: 'cancelled' };
    return Promise.resolve({ status: 200, body: { project_id: projectId, connection_id: connectionId,
      job: this.ga4JobResult, cancel_requested: false } });
  }
  ga4QualityHistory(_org: number, projectId: number, connectionId: number): Promise<ApiResult> {
    return Promise.resolve({ status: 200, body: { project_id: projectId, connection_id: connectionId,
      source_current: true, reviews: this.ga4QualityRows, has_more: false } });
  }
  saveGA4Quality(_org: number, projectId: number, connectionId: number, data: Record<string, unknown>): Promise<ApiResult> {
    const review = { id: 301, revision: Number(data['expected_revision']) + 1, property_id: '12345',
      currency: 'USD', timezone: 'UTC', definitions: data['definitions'],
      instrumentation_state: data['instrumentation_state'], instrumentation_notes: data['instrumentation_notes'],
      event_quality_state: data['event_quality_state'],
      attribution_notes: data['attribution_notes'], consent_notes: data['consent_notes'],
      tracking_change_notes: data['tracking_change_notes'], created_at: '2026-09-28T00:00:00Z' };
    this.ga4QualityRows = [review];
    return Promise.resolve({ status: 201, body: { project_id: projectId, connection_id: connectionId,
      review, provider_instrumentation_verified: false } });
  }
  setPlatformGoogleOAuthApp(_id: string, secret: string, _redirect: string) {
    this.savedGoogleSecrets.push(secret);
    return Promise.resolve({ status: 200, body: { configured: true } });
  }
  setPlatformGoogleAnalyticsApp(_id: string, secret: string, _redirect: string) {
    this.savedAnalyticsSecrets.push(secret);
    return Promise.resolve({ status: 200, body: { configured: true } });
  }
  platformPerformanceKey() { return Promise.resolve(this.performanceKeyResult); }
  setPlatformPerformanceKey(key: string) {
    this.savedPerformanceKeys.push(key);
    return Promise.resolve({ status: 200, body: { configured: true } });
  }
  addPlatformAccount(_providerId: number, _label: string, secret: string) {
    this.savedPlatformSecrets.push(secret);
    return Promise.resolve({ status: 201, body: { configured: true } });
  }
  organizationProviderAccounts() { return Promise.resolve(this.organizationProviderResult); }
  addOrganizationProviderAccount(_orgId: number, _providerId: number, _label: string, secret: string) {
    this.savedOrganizationSecrets.push(secret);
    return Promise.resolve({ status: 201, body: { configured: true } });
  }
  setOrganizationProviderCredential(_orgId: number, _accountId: number, secret: string) {
    this.savedOrganizationSecrets.push(secret); return Promise.resolve({ status: 200, body: { configured: true } });
  }
  revokeOrganizationProviderCredential(_orgId: number, _accountId: number) {
    this.organizationProviderResult.body['accounts'] = []; return Promise.resolve({ status: 200, body: {} });
  }
  revokeOrganizationPerformanceKey(_orgId: number) {
    this.organizationPerformanceResult = { status: 200, body: { state: 'revoked' } };
    return Promise.resolve({ status: 200, body: {} });
  }
  organizationPerformanceKey() { return Promise.resolve(this.organizationPerformanceResult); }
  setOrganizationPerformanceKey(_orgId: number, key: string) {
    this.savedOrganizationPerformanceKeys.push(key);
    return Promise.resolve({ status: 200, body: { configured: true } });
  }
  totpSetup() { return Promise.resolve(this.totpSetupResult); }
  activateTotp(code: string) {
    this.mfaCodes.push(code);
    return Promise.resolve({ status: 200, body: { data: { type: 'totp', created_at: 1 } } });
  }
  recoveryCodes() { return Promise.resolve(this.recoveryCodesResult); }
  regenerateRecoveryCodes() { return Promise.resolve(this.recoveryCodesResult); }
  logout() { return Promise.resolve(this.logoutResult); }
  resentVerificationEmails: string[] = [];
  resendVerification(email: string) {
    this.resentVerificationEmails.push(email);
    return Promise.resolve({ status: 200, body: {} });
  }
  confirmedVerificationKeys: string[] = [];
  verificationStatus() { return Promise.resolve(this.verificationResult); }
  confirmVerification(key: string) {
    this.confirmedVerificationKeys.push(key);
    this.verificationResult = { status: 200, body: { state: 'used' } };
    return Promise.resolve({ status: 200, body: {} });
  }
  requestPasswordReset(_email: string) { return Promise.resolve(this.passwordRequestResult); }
  passwordResetInfo(key: string) {
    this.passwordResetKeys.push(key);
    return Promise.resolve(this.passwordResetInfoResult);
  }
  resetPassword(_key: string, _password: string): Promise<ApiResult> { return Promise.resolve({ status: 401, body: {} }); }
  changePassword() { return Promise.resolve({ status: 204, body: {} }); }
  reauthenticate() { return Promise.resolve({ status: 200, body: {} }); }
  personalAccountArchive() {
    this.personalExportCalls++;
    return Promise.resolve();
  }
  personalClosureStatus() { return Promise.resolve(this.personalClosureResult); }
  closePersonalAccount() {
    this.personalCloseCalls++;
    return Promise.resolve({ status: 202, body: { state: 'access_closed',
      retained_identity: 'restricted_policy_review_not_erased' } });
  }
  requestEmailChange() { return Promise.resolve({ status: 200, body: {} }); }
  sessions() { return Promise.resolve(this.sessionResult); }
  endSessions(ids: number[]) {
    this.endedSessions = ids;
    const data = this.sessionResult.body['data'];
    return Promise.resolve({ status: 200, body: { data: Array.isArray(data) ? data.slice(0, 1) : [] } });
  }
  logoutAll() { return Promise.resolve({ status: 204, body: {} }); }
  organizations() {
    return this.organizationsHandler ? this.organizationsHandler() : Promise.resolve(this.organizationsResult);
  }
  projects(organizationId: number) {
    return this.projectsHandler ? this.projectsHandler(organizationId) : Promise.resolve(this.projectsResult);
  }
  team(organizationId: number) {
    return this.teamHandler ? this.teamHandler(organizationId) : Promise.resolve(this.teamResult);
  }
  jobs() { return Promise.resolve(this.jobsResult); }
  jobDetails(_organizationId: number, _projectId: number, jobId: number) {
    return this.jobDetailsHandler ? this.jobDetailsHandler(jobId) : Promise.resolve(this.jobDetailResult);
  }
  createDiagnostic(_organizationId: number, _projectId: number, _sample: string, _partial: boolean, key: string) {
    this.diagnosticKeys.push(key);
    return this.diagnosticHandler ? this.diagnosticHandler()
      : Promise.resolve({ status: 202, body: { job: this.jobDetailResult.body['job'] } });
  }
  cancelJob(_organizationId: number, _projectId: number, jobId: number) {
    this.cancelledJobIds.push(jobId);
    return Promise.resolve({ status: 202, body: { cancel_requested: true } });
  }
  jobSchedules() { return Promise.resolve(this.jobSchedulesResult); }
  createDiagnosticSchedule(_organizationId: number, _projectId: number, _sample: string, _interval: number, key: string) {
    this.scheduleKeys.push(key);
    return this.scheduleHandler ? this.scheduleHandler() : Promise.resolve({ status: 201, body: {
      schedule: { id: 12, project_id: 9, enabled: false, interval_minutes: 60,
        next_run_at: null, last_run_at: null, skipped_occurrences: 0, last_error_category: '' },
    } });
  }
  setDiagnosticSchedule(_organizationId: number, _projectId: number, _scheduleId: number, enabled: boolean) {
    this.scheduleToggles.push(enabled);
    return Promise.resolve({ status: 200, body: { schedule: {
      id: 12, project_id: 9, enabled, interval_minutes: 60,
      next_run_at: enabled ? '2026-09-25T10:00:00Z' : null,
      last_run_at: null, skipped_occurrences: 0, last_error_category: '',
    } } });
  }
  retryJob(_organizationId: number, _projectId: number, _jobId: number, key: string) {
    this.retriedKeys.push(key);
    const job = { ...(this.jobDetailResult.body['job'] as object), id: 4, status: 'succeeded' };
    this.jobDetailResult = { status: 200, body: { job } };
    return Promise.resolve({ status: 202, body: { job } });
  }
  inviteMember(_organizationId: number, email: string, role: string, projectIds: number[]) {
    this.invitedEmail = email;
    this.invitedRole = role;
    this.invitedProjects = projectIds;
    return Promise.resolve({ status: 201, body: { delivery: 'sent' } });
  }
  updateMember() { return Promise.resolve({ status: 200, body: {} }); }
  removeMember(_organizationId: number, membershipId: number) {
    this.removedMembers.push(membershipId);
    return Promise.resolve({ status: 204, body: {} });
  }
  revokeInvitation() { return Promise.resolve({ status: 204, body: {} }); }
  reissueInvitation(_organizationId: number, invitationId: number) {
    this.reissuedInvitations.push(invitationId);
    return Promise.resolve({ status: 201, body: { delivery: 'sent' } });
  }
  acceptInvitation(token: string) {
    this.invitationTokens.push(token);
    return Promise.resolve(this.invitationAcceptResult);
  }
  ownershipTransfer() { return Promise.resolve(this.transferResult); }
  proposeOwnershipTransfer(_organizationId: number, memberId: number) {
    this.proposedMembers.push(memberId);
    return Promise.resolve({ status: 201, body: { transfer: { id: 12 } } });
  }
  acceptOwnershipTransfer(_organizationId: number, transferId: number) {
    this.acceptedTransfers.push(transferId);
    return Promise.resolve({ status: 200, body: { accepted: true } });
  }
  cancelOwnershipTransfer(_organizationId: number, transferId: number) {
    this.cancelledTransfers.push(transferId);
    return Promise.resolve({ status: 204, body: {} });
  }
  leaveOrganization(organizationId: number) {
    this.leftOrganizations.push(organizationId);
    return Promise.resolve({ status: 204, body: {} });
  }
  createOrganization() { return Promise.resolve({ status: 400, body: {} }); }
  updateOrganization() { return Promise.resolve({ status: 400, body: {} }); }
  createProject() { return Promise.resolve({ status: 400, body: {} }); }
  updateProject() { return Promise.resolve({ status: 400, body: {} }); }
  projectOnboarding(organizationId: number, projectId: number) {
    return this.onboardingLoadHandler ? this.onboardingLoadHandler(organizationId, projectId) : Promise.resolve(this.onboardingResult);
  }
  projectSources(organizationId: number, projectId: number) {
    return this.sourcesHandler ? this.sourcesHandler(organizationId, projectId)
      : Promise.resolve({ status: 200, body: { project_id: projectId, sources: [], has_more: false } });
  }
  createCsvSource(_organizationId: number, projectId: number, property: string) {
    return Promise.resolve({ status: 200, body: { project_id: projectId, id: 5, property, state: 'active' } });
  }
  uploadSearchConsoleCsv(_organizationId: number, projectId: number, connectionId: number,
    _file: Blob, headers: Record<string, string>): Promise<ApiResult> {
    return Promise.resolve({ status: 202, body: { project_id: projectId, connection_id: connectionId,
      job: { id: 81, project_id: projectId, connection_id: connectionId, status: 'queued',
        source_checksum: createHash('sha256').update('private fixture').digest('hex'),
        date_start: headers['X-CSV-Start'], date_end: headers['X-CSV-End'], search_type: headers['X-CSV-Search-Type'],
        date_granularity: headers['X-CSV-Date-Granularity'] === 'day' ? 'day' : null } } });
  }
  indexationEvidence(_organizationId: number, projectId: number, crawlRunId?: number): Promise<ApiResult> {
    return Promise.resolve({ status: 200, body: { project_id: projectId, crawl_run_id: crawlRunId || 42,
      crawls: this.indexationCrawlChoices, has_more: false,
      report: this.indexationBuilt ? { crawl_run_id: 42, diagnostics_id: 59,
        coverage: { state: 'partial', engine_indexing_reports: 'unavailable' },
        urls: [{ url: 'https://onboarding.example/', discovered_by: ['sitemap'], crawlability: 'observed',
          indexability_signals: ['sitemap_http_or_noindex_candidate'], fetch_observations: [{ status_code: 200, directive_state: 'no_noindex_observed',
            declared_canonical: null }], engine_reports: [] }],
      } : null } });
  }
  buildIndexationEvidence(_organizationId: number, projectId: number, crawlRunId: number) {
    this.indexationBuilt = true;
    return Promise.resolve({ status: 201, body: { project_id: projectId, crawl_run_id: crawlRunId, snapshot_id: 51 } });
  }
  performanceAudits(_organizationId: number, projectId: number): Promise<ApiResult> {
    return Promise.resolve({ status: 200, body: { project_id: projectId,
      credential_available: this.performanceKeyAvailable, has_more: false,
      jobs: this.performanceRequests.length ? [this.performanceJob()] : [] } });
  }
  private performanceJob() {
    return { id: 72, status: 'partially_succeeded', error_category: 'partial_coverage',
      target: 'https://onboarding.example/', grain: 'page', strategy: 'mobile',
      sources: this.performanceHistory ? ['crux_history'] : ['psi_lab', 'crux_current'],
      requests_attempted: this.performanceHistory ? 1 : 2, sources_recorded: this.performanceHistory ? 1 : 2,
      lab: this.performanceHistory ? 'unavailable' : 'observed', field: 'observed', coverage: 'partial' };
  }
  startPerformanceAudit(_organizationId: number, projectId: number, target: string,
    _grain: string, _strategy: string, sources: string[], key: string): Promise<ApiResult> {
    this.performanceRequests.push({ target, sources, key });
    return Promise.resolve({ status: 202, body: { project_id: projectId, job: this.performanceJob(), max_requests: 2 } });
  }
  performanceAuditDetail(_organizationId: number, projectId: number, jobId: number): Promise<ApiResult> {
    return Promise.resolve({ status: 200, body: { project_id: projectId, job: { ...this.performanceJob(), id: jobId },
      observations: this.performanceHistory ? [{ id: 75, source: 'crux_history', collected_at: '2026-09-28T01:00:00Z', result: {
        source: 'crux_history_api', requested_grain: 'page', observed_grain: 'page', origin_fallback: false, url_normalization: 'none',
        metrics: [{ name: 'LCP', state: 'observed', p75: 4500, unit: 'ms', grade: 'poor',
          period: { start: '2026-08-01', end: '2026-08-28' } }],
        regressions: [{ metric: 'LCP', state: 'regression_candidate', previous: { p75: 2000 }, current: { p75: 4500 } }] } }]
        : [{ id: 73, source: 'psi_lab', collected_at: '2026-09-28T01:00:00Z', result: {
        source: 'pagespeed_insights', scores: { performance: .7 }, status: 'observed', audits: {} } },
      { id: 74, source: 'crux_current', collected_at: '2026-09-28T01:00:00Z', result: {
        source: 'crux_api', requested_grain: 'page', observed_grain: 'origin', origin_fallback: true,
        metrics: [{ name: 'LCP', state: 'unavailable', p75: null, unit: 'ms', grade: 'unknown',
          period: { start: '2026-08-01', end: '2026-08-28' } }] } }] } });
  }
  cancelPerformanceAudit(_organizationId: number, projectId: number, jobId: number): Promise<ApiResult> {
    return Promise.resolve({ status: 200, body: { project_id: projectId,
      job: { ...this.performanceJob(), id: jobId, status: 'cancelled' }, cancel_requested: false } });
  }
  projectCruxHistory(organizationId: number, projectId: number, observationId: number) {
    this.cruxInspections.push([organizationId, projectId, observationId]);
    return this.cruxHandler ? this.cruxHandler() : Promise.resolve({ status: 200, body: {
      method_version: 'current-crux-history-threshold-source-v1', project_id: projectId, observation_id: observationId,
      job_id: 72, assessed_at: '2026-10-03T01:00:00Z', collected_at: '2026-09-28T01:00:00Z',
      raw_sha256: null, state: 'unknown_original_raw_integrity', comparisons: [] } });
  }
  projectCruxMaterialPolicy(organizationId: number, projectId: number, observationId: number) {
    this.cruxPolicyInspections.push([organizationId, projectId, observationId]);
    return this.cruxPolicyHandler ? this.cruxPolicyHandler() : Promise.resolve({ status: 200, body: {
      method_version: 'material-crux-threshold-candidate-v1', state: 'unknown_original_raw_integrity', rows: [],
      assessed_at: '2026-10-03T01:00:00Z', source_fingerprint: 'b'.repeat(64),
      interpretation: 'product_material_change_heuristic_not_statistical_seo_regression_causality_consent_or_delivery',
      source: { method_version: 'current-crux-history-threshold-source-v1', project_id: projectId, observation_id: observationId,
        job_id: 72, collected_at: '2026-09-28T01:00:00Z', raw_sha256: null, state: 'unknown_original_raw_integrity', comparisons: [] } } });
  }
  googleOAuthGrants(organizationId: number, projectId: number) {
    return this.googleGrantsHandler ? this.googleGrantsHandler(organizationId, projectId)
      : Promise.resolve({ status: 200, body: { project_id: projectId, grants: this.googleGrantRows, has_more: false } });
  }
  startGoogleOAuth() { return Promise.resolve({ status: 503, body: {} }); }
  selectGoogleSite(_organizationId: number, projectId: number, grantId: number, revision: number, siteUrl: string) {
    this.selectedGoogleSites.push(siteUrl);
    this.googleGrantRows = this.googleGrantRows.map((row) => row['id'] === grantId
      ? { ...row, state: 'active', revision: revision + 1 } : row);
    return Promise.resolve({ status: 200, body: { connection_id: 3, project_id: projectId, state: 'active' } });
  }
  revokeGoogleOAuth(_organizationId: number, _projectId: number, grantId: number, revision: number) {
    this.revokedGoogleGrants.push(grantId);
    this.googleGrantRows = this.googleGrantRows.map((row) => row['id'] === grantId
      ? { ...row, state: 'revoked', revision: revision + 1, sites: [] } : row);
    return Promise.resolve({ status: 200, body: { state: 'revoked', revision: revision + 1 } });
  }
  startSearchConsoleSync(_org: number, projectId: number, connectionId: number, day: string, dimensions: string[], key: string): Promise<ApiResult> {
    this.syncRequests.push({ connectionId, day, dimensions, key });
    return Promise.resolve({ status: 202, body: { project_id: projectId, job_id: 51, status: 'queued', max_requests: 3,
      source_coverage: 'top_rows_only' } });
  }
  searchConsoleSyncStatus(_org: number, projectId: number, connectionId: number) {
    return this.syncStatusHandler ? this.syncStatusHandler(projectId, connectionId)
      : Promise.resolve({ status: 200, body: { project_id: projectId, connection_id: connectionId,
        job: { id: 51, status: 'queued', error_category: '', pages_recorded: 0,
          requests_attempted: 0, source_coverage: 'unavailable' } } });
  }
  cancelSearchConsoleSync(_org: number, projectId: number, connectionId: number, jobId: number): Promise<ApiResult> {
    return Promise.resolve({ status: 200, body: { project_id: projectId, connection_id: connectionId,
      job: { id: jobId, status: 'cancelled', error_category: '', pages_recorded: 0,
        requests_attempted: 0, source_coverage: 'unavailable' } } });
  }
  startSearchConsoleBackfill(_org: number, projectId: number, connectionId: number,
    startDay: string, endDay: string, dimension: string, key: string): Promise<ApiResult> {
    this.backfillRequests.push({ connectionId, startDay, endDay, dimension, key });
    return Promise.resolve({ status: 202, body: { project_id: projectId, connection_id: connectionId,
      backfill: { id: 96, status: 'running', start_day: startDay, end_day: endDay, next_day: startDay,
        dimension, current_job: null, error_category: '' } } });
  }
  searchConsoleBackfillStatus(_org: number, projectId: number, connectionId: number): Promise<ApiResult> {
    return Promise.resolve({ status: 200, body: { project_id: projectId, connection_id: connectionId,
      backfill: { id: 96, status: 'paused', start_day: '2026-09-16', end_day: '2026-09-18',
        next_day: '2026-09-17', dimension: 'page', current_job: 52, error_category: 'quota_limited' } } });
  }
  cancelSearchConsoleBackfill(_org: number, projectId: number, connectionId: number, backfillId: number): Promise<ApiResult> {
    return Promise.resolve({ status: 200, body: { project_id: projectId, connection_id: connectionId,
      backfill: { id: backfillId, status: 'paused', start_day: '2026-09-16', end_day: '2026-09-18',
        next_day: '2026-09-16', dimension: 'page', current_job: null, error_category: 'cancelled' } } });
  }
  createSearchConsoleSchedule(_org: number, projectId: number, connectionId: number, dimension: string, key: string): Promise<ApiResult> {
    this.scheduleRequests.push({ connectionId, dimension, key });
    return Promise.resolve({ status: 201, body: { project_id: projectId, connection_id: connectionId,
      schedule: { id: 27, enabled: false, dimension, next_run_at: null, last_run_at: null,
        last_error_category: '', skipped_occurrences: 0 } } });
  }
  searchConsoleScheduleStatus(_org: number, projectId: number, connectionId: number): Promise<ApiResult> {
    return Promise.resolve({ status: 200, body: { project_id: projectId, connection_id: connectionId,
      schedule: { id: 27, enabled: false, dimension: 'page', next_run_at: null, last_run_at: null,
        last_error_category: '', skipped_occurrences: 0 } } });
  }
  toggleSearchConsoleSchedule(_org: number, projectId: number, connectionId: number,
    scheduleId: number, enabled: boolean): Promise<ApiResult> {
    return Promise.resolve({ status: 200, body: { project_id: projectId, connection_id: connectionId,
      schedule: { id: scheduleId, enabled, dimension: 'page', next_run_at: enabled ? '2026-09-29T00:00:00Z' : null,
        last_run_at: null, last_error_category: '', skipped_occurrences: 0 } } });
  }
  startSearchConsoleCoverage(_org: number, projectId: number, connectionId: number, inspectionUrl: string, key: string): Promise<ApiResult> {
    this.coverageRequests.push({ connectionId, inspectionUrl, key });
    return Promise.resolve({ status: 202, body: { project_id: projectId, connection_id: connectionId,
      max_requests: 3, job: { id: 66, status: 'queued', error_category: '', inspection_url: inspectionUrl,
        requests_attempted: 0, sources_recorded: [], results: [] } } });
  }
  searchConsoleCoverageStatus(_org: number, projectId: number, connectionId: number) {
    return this.coverageStatusHandler ? this.coverageStatusHandler(projectId, connectionId)
      : Promise.resolve({ status: 200, body: { project_id: projectId, connection_id: connectionId,
        job: { id: 66, status: 'queued', error_category: '', inspection_url: 'https://onboarding.example/page',
          requests_attempted: 0, sources_recorded: [], results: [] } } });
  }
  cancelSearchConsoleCoverage(_org: number, projectId: number, connectionId: number, jobId: number): Promise<ApiResult> {
    return Promise.resolve({ status: 200, body: { project_id: projectId, connection_id: connectionId,
      job: { id: jobId, status: 'cancelled', error_category: '', inspection_url: 'https://onboarding.example/page',
        requests_attempted: 0, sources_recorded: [], results: [] } } });
  }
  setCsvSourceState(_organizationId: number, projectId: number, connectionId: number, enabled: boolean) {
    this.csvStateChanges.push(enabled);
    return Promise.resolve({ status: 200, body: { id: connectionId, project_id: projectId,
      state: enabled ? 'active' : 'disconnected' } });
  }
  sourceQueries(organizationId: number, projectId: number, connectionId: number) {
    return this.queriesHandler ? this.queriesHandler(organizationId, projectId, connectionId)
      : Promise.resolve({ status: 200, body: { project_id: projectId, connection_id: connectionId,
        method: 'alias-boundary-v1', alias_revision: 0, source_completeness: 'provider_export_unknown',
        queries: [], has_more: false, next_before: null } });
  }
  sourceImportHistory(_organizationId: number, projectId: number, connectionId: number) {
    if (this.sourceImportHistoryHandler) return this.sourceImportHistoryHandler(_organizationId, projectId, connectionId);
    return Promise.resolve({ status: 200, body: { project_id: projectId, connection_id: connectionId,
      property: 'https://onboarding.example', provider: 'google_search_console', has_more: false,
      imports: [{ id: 2, created_at: '2026-09-26T00:00:00Z', export_shape: 'query', status: 'partially_succeeded',
        coverage_state: 'partial', date_start: '2026-09-01', date_end: '2026-09-05', rows_seen: 2,
        rows_imported: 1, row_errors: 1, source_completeness: 'provider_export_unknown' }] } });
  }
  sourceOpportunityPreview(_organizationId: number, projectId: number, connectionId: number, importId: number): Promise<ApiResult> {
    return Promise.resolve({ status: 200, body: { project_id: projectId, connection_id: connectionId,
      method: 'gsc-csv-opportunity-v1', property: 'https://onboarding.example', dimension: 'query',
      timezone: 'America/Los_Angeles', market: 'Türkiye', languages: ['tr'],
      window: { import_id: importId, start: '2026-09-01', end: '2026-09-05' },
      thresholds: { position_inclusive: [4, 20], min_impressions: 100, ctr_below: '0.03' },
      coverage: { file: 'complete', provider_top_rows: 'incomplete_unknown', hidden_queries: 'unknown' },
      candidates: [{ detector: 'web_position_4_to_20_candidate', observation_id: 22, query: 'owned query',
        page: null, clicks: 2, impressions: 200, ctr: '0.01', position: '10',
        confidence: 'candidate_not_proven_business_value' }], truncated_candidates: false } });
  }
  projectFindings(_organizationId: number, projectId: number): Promise<ApiResult> {
    return Promise.resolve({ status: 200, body: { project_id: projectId, findings: this.findingRows,
      has_more: false } });
  }
  projectReports(_organizationId: number, projectId: number) {
    return Promise.resolve({ status: 200, body: { project_id: projectId, reports: this.reportRows, has_more: false } });
  }
  projectSummaryPreference(_organizationId: number, projectId: number) {
    return Promise.resolve({ status: 200, body: { project_id: projectId,
      preference: { channel: 'email', frequency: 'off', revision: 0, delivery_state: 'rollout_off' } } });
  }
  alertPreferenceSaves: unknown[][] = [];
  cruxPreferenceSaves: unknown[][] = [];
  projectCruxAlertPreference(_organizationId: number, projectId: number) {
    return Promise.resolve({ status: 200, body: { project_id: projectId,
      preference: { channel: 'email', source_family: 'crux_material', frequency: 'off', revision: 0, delivery_state: 'rollout_off' } } });
  }
  saveProjectCruxAlertPreference(organizationId: number, projectId: number, frequency: string, revision: number) {
    this.cruxPreferenceSaves.push([organizationId, projectId, frequency, revision]);
    return Promise.resolve({ status: 200, body: { project_id: projectId,
      preference: { channel: 'email', source_family: 'crux_material', frequency, revision: revision + 1, delivery_state: 'rollout_off' } } });
  }
  projectAlertPreference(_organizationId: number, projectId: number) {
    return Promise.resolve({ status: 200, body: { project_id: projectId,
      preference: { channel: 'email', frequency: 'off', source_families: [], revision: 0, delivery_state: 'rollout_off' } } });
  }
  saveProjectAlertPreference(organizationId: number, projectId: number, frequency: string, sourceFamilies: string[], revision: number) {
    this.alertPreferenceSaves.push([organizationId, projectId, frequency, sourceFamilies, revision]);
    return Promise.resolve({ status: 200, body: { project_id: projectId,
      preference: { channel: 'email', frequency, source_families: sourceFamilies, revision: revision + 1, delivery_state: 'rollout_off' } } });
  }
  summaryHistoryReads: number[][] = [];
  alertHistoryReads: number[][] = [];
  cruxHistoryReads: number[][] = [];
  supportReferenceReads: number[][] = [];
  supportRequestReads: number[][] = [];
  supportRequestCreates: Record<string, unknown>[] = [];
  projectSupportRequests(organizationId: number, projectId: number) {
    this.supportRequestReads.push([organizationId, projectId]);
    return Promise.resolve({ status: 200, body: { project_id: projectId, actor_id: 4,
      method_version: 'own-project-support-request-v2',
      scope: 'own_retained_support_records_not_email_delivery_staff_response_or_job_access_authority', requests: [], has_more: false } });
  }
  createProjectSupportRequest(_organizationId: number, projectId: number, command: Record<string, unknown>) {
    this.supportRequestCreates.push(structuredClone(command));
    return Promise.resolve({ status: 200, body: { project_id: projectId, actor_id: 4,
      method_version: 'own-project-support-request-v2',
      scope: 'own_retained_support_records_not_email_delivery_staff_response_or_job_access_authority',
      request: { id: 888, question: command['question'], category: command['category'], job_id: command['job_id'],
        created_at: '2026-10-04T00:00:00.000001Z', revision: 0, status: 'received', updates: [], updates_has_more: false } } });
  }
  projectSupportJobReference(organizationId: number, projectId: number, jobId: number) {
    this.supportReferenceReads.push([organizationId, projectId, jobId]);
    return Promise.resolve({ status: 200, body: { project_id: projectId,
      method_version: 'retained-project-job-support-reference-v1',
      scope: 'retained_operational_job_reference_not_completion_incident_seo_outcome_or_retry_authority', state: 'retained_job_reference',
      job: { id: jobId, status: 'failed', created_at: '2026-10-02T10:00:00.100001Z', updated_at: '2026-10-02T10:00:00.100002Z' } } });
  }
  projectCruxAlertDeliveries(organizationId: number, projectId: number) {
    this.cruxHistoryReads.push([organizationId, projectId]);
    return Promise.resolve({ status: 200, body: { project_id: projectId,
      method_version: 'own-daily-crux-delivery-history-v1',
      scope: 'own_retained_crux_transport_history_not_recipient_delivery_read_regression_or_current_eligibility', has_more: false,
      rows: [{ id: 997, day_start: '2026-10-01', created_at: '2026-10-02T10:00:00.100001+00:00',
        attempted_at: null, accepted_at: null, state: 'queued', error_category: '' }] } });
  }
  projectAlertDeliveries(organizationId: number, projectId: number) {
    this.alertHistoryReads.push([organizationId, projectId]);
    return Promise.resolve({ status: 200, body: { project_id: projectId,
      method_version: 'own-daily-operational-delivery-history-v1',
      scope: 'own_retained_transport_history_not_recipient_delivery_read_incident_or_current_eligibility', has_more: false,
      rows: [{ id: 998, day_start: '2026-10-01', created_at: '2026-10-02T10:00:00.100001+00:00',
        attempted_at: null, accepted_at: null, state: 'queued', error_category: '' }] } });
  }
  crawlFailureReads: number[][] = [];
  integrationHealthReads: number[][] = [];
  projectIntegrationHealth(organizationId: number, projectId: number) {
    this.integrationHealthReads.push([organizationId, projectId]);
    return Promise.resolve({ status: 200, body: { project_id: projectId, method_version: 'integration-health-metadata-v1',
      scope: 'bounded_connection_sync_metadata_not_readiness_staleness_regression_or_delivery_authority',
      assessed_at: '2026-10-01T10:00:00.100003Z', has_more: false,
      rows: [{ connection_id: 661, provider: 'google_search_console', connection_state: 'active',
        source_state: 'api_sync_metadata', sync: null }] } });
  }
  projectCrawlFailures(organizationId: number, projectId: number) {
    this.crawlFailureReads.push([organizationId, projectId]);
    return Promise.resolve({ status: 200, body: { project_id: projectId, method_version: 'retained-crawl-failures-v1',
      scope: 'retained_failed_crawl_jobs_not_current_incident_regression_or_retry_authority', has_more: false,
      assessed_at: '2026-10-01T10:00:00.100003Z', rows: [{ job_id: 771, source_method: 'crawl-http-v2',
        created_at: '2026-10-01T10:00:00.100001Z', status_updated_at: '2026-10-01T10:00:00.100002Z', failure_category: 'handler_failed' }] } });
  }
  projectSummaryDeliveries(organizationId: number, projectId: number) {
    this.summaryHistoryReads.push([organizationId, projectId]);
    return Promise.resolve({ status: 200, body: { project_id: projectId, method_version: 'own-weekly-delivery-history-v1',
      scope: 'own_retained_transport_history_not_recipient_delivery_read_or_current_eligibility', has_more: false,
      rows: [{ id: 991, week_start: '2026-09-28', created_at: '2026-09-30T10:00:00.100001+00:00',
        attempted_at: null, accepted_at: null, state: 'queued', error_category: '' }] } });
  }
  organizationExportInventory(organizationId: number) {
    return Promise.resolve(organizationId === 7 ? this.exportInventoryResult : { status: 404, body: {} });
  }
  organizationClosureStatus(organizationId: number) {
    return Promise.resolve(organizationId === 7 ? this.closureStatusResult : { status: 404, body: {} });
  }
  organizationClose(organizationId: number): Promise<ApiResult> {
    this.closureRequests.push(organizationId);
    this.closureStatusResult = { status: 200, body: { ...this.closureStatusResult.body,
      state: 'closed', closed_at: '2026-09-29T02:00:00Z', close_action_available: false,
      deletion: { source: 'owner_closed', state: 'pending', eligible_at: '2026-09-29T02:00:00Z',
        due_at: '2026-10-29T02:00:00Z', completed_at: null, error_category: '',
        backup_latest_expiry_bound_at: null },
    } };
    return Promise.resolve({ status: 202, body: { state: 'closed', organization_id: organizationId,
      status_path: `/api/organizations/${organizationId}/closure-status/`,
      backup_expiry: 'policy_only_unverified' } });
  }
  organizationReconcileClosureBilling(organizationId: number): Promise<ApiResult> {
    this.closureBillingChecks.push(organizationId);
    this.closureStatusResult = { status: 200, body: { ...this.closureStatusResult.body,
      billing_cancellation: { state: 'confirmed', error_category: '' } } };
    return Promise.resolve({ status: 200, body: { organization_id: organizationId, state: 'confirmed',
      status_path: `/api/organizations/${organizationId}/closure-status/` } });
  }
  organizationRevokePendingGrant(organizationId: number, provider: string, grantId: number): Promise<ApiResult> {
    this.closureGrantAttempts.push({ organizationId, provider, grantId });
    this.closureStatusResult = { status: 200, body: { ...this.closureStatusResult.body,
      remote_revocation_pending: { search_console: 0, analytics: 0 },
      pending_grants: { search_console: [], analytics: [] } } };
    return Promise.resolve({ status: 200, body: { organization_id: organizationId, provider, state: 'revoked',
      status_path: `/api/organizations/${organizationId}/closure-status/` } });
  }
  organizationCustomerRows(organizationId: number, model: string, afterId: number, throughId: number) {
    return Promise.resolve({ status: 200, body: {
      version: 'organization-export-rows-v1', organization_id: organizationId,
      scope: 'one_model_page_not_a_complete_organization_export', model,
      rows: [{ id: 9, name: 'Synthetic project' }], has_more: false,
      next_after_id: Math.max(9, afterId + 1), through_id: throughId,
    } });
  }
  boundedOrganizationArchive(_organizationId: number) {
    return Promise.resolve({ status: 200, type: 'application/zip', blob: new Blob(['synthetic ZIP']), digest: 'a'.repeat(64) });
  }
  sourcePartFormat = false;
  captureOrganizationSnapshot(organizationId: number, format = 'bounded-zip-v1'): Promise<ApiResult> {
    this.sourcePartFormat = format === 'source-parts-v2';
    this.exportHistoryRows = [{ id: 42, state: 'preparing', created_at: '2026-09-29T09:00:00Z', manifest_path: null },
      ...this.exportHistoryRows];
    return Promise.resolve({ status: 202, body: { organization_id: organizationId, snapshot_id: 42,
      state: 'preparing', format, scope: this.sourcePartFormat ? 'sequential_source_parts_not_transactional'
        : 'bounded_customer_content_only', manifest_path: null } });
  }
  organizationSnapshots(organizationId: number): Promise<ApiResult> {
    return Promise.resolve({ status: 200, body: { organization_id: organizationId,
      scope: 'bounded_capture_history_not_complete_export', snapshots: this.exportHistoryRows } });
  }
  discardFailedOrganizationSnapshot(organizationId: number, snapshotId: number) {
    this.exportHistoryRows = this.exportHistoryRows.filter((row) => row['id'] !== snapshotId);
    return Promise.resolve({ status: 200, body: { organization_id: organizationId,
      snapshot_id: snapshotId, state: 'discarded', removed: 1 } });
  }
  organizationSnapshotManifest(organizationId: number, snapshotId: number, position = 0): Promise<ApiResult> {
    if (this.sourcePartFormat) return Promise.resolve({ status: 200, body: {
      version: 'source-parts-v2', organization_id: organizationId, snapshot_id: snapshotId,
      scope: 'sequential_source_parts_not_transactional', size_bytes: 51 * 700000,
      sha256: 'a'.repeat(64), part_count: 51, next_position: position === 0 ? 50 : null,
      integrity: 'sha256_chain_of_canonical_part_descriptors_from_32_zero_bytes',
      parts: Array.from({ length: position === 0 ? 50 : 1 }, (_, index) => ({
        position: position + index, size_bytes: 700000, sha256: 'b'.repeat(64),
        source: { kind: 'rows', model: 'jobs.JobStep' },
        download_path: `/api/organizations/${organizationId}/export/snapshots/${snapshotId}/parts/${position + index}/`,
      })),
    } });
    return Promise.resolve({ status: 200, body: { version: 'bounded-organization-snapshot-v1', organization_id: organizationId, snapshot_id: snapshotId,
      scope: 'captured_bounded_customer_content_not_legal_or_backup_export', size_bytes: 10,
      sha256: 'a'.repeat(64), parts: [{ position: 0, size_bytes: 10, sha256: 'b'.repeat(64),
        download_path: `/api/organizations/${organizationId}/export/snapshots/${snapshotId}/parts/0/` }] } });
  }
  createProjectReport(_organizationId: number, _projectId: number, ids: number[], format: 'csv' | 'json') {
    this.reportCreateIds.push(ids);
    const report = { id: 22, format, created_at: '2026-09-29T09:00:00Z', size_bytes: 72,
      source_counts: { findings: ids.length, actions: 0, outcomes: 0 } };
    this.reportRows = [report];
    return Promise.resolve({ status: 201, body: { report } });
  }
  projectReportShares() {
    return Promise.resolve({ status: 200, body: { shares: this.reportShareRows } });
  }
  createProjectReportShare(_organizationId: number, _projectId: number, reportId: number): Promise<ApiResult> {
    const share = { id: 31, report_id: reportId, intended_recipient: 'reader@example.invalid',
      expires_at: '2026-09-30T09:00:00Z', state: 'active' };
    this.reportShareRows = [share];
    return Promise.resolve({ status: 201, body: { share, link_path: `/api/reports/shared/${'A'.repeat(43)}/` } });
  }
  revokeProjectReportShare(_organizationId: number, _projectId: number, shareId: number) {
    const share = { ...this.reportShareRows.find((row) => row['id'] === shareId)!, state: 'revoked' };
    this.reportShareRows = [share];
    return Promise.resolve({ status: 200, body: { share } });
  }
  intentClusters(_organizationId: number, projectId: number) {
    return Promise.resolve({ status: 200, body: { project_id: projectId, clusters: this.intentRows, has_more: false } });
  }
  projectResearch(_organizationId: number, projectId: number) {
    return Promise.resolve({ status: 200, body: { project_id: projectId, models: [
      { id: 30, provider_id: 1, name: 'Synthetic model', access_tier: 'standard', price_known: true,
        max_output_tokens: 2048, privacy_policy_url: '' }], accounts: [
      { id: 31, provider_id: 1, label: 'Fixture account', source: 'platform' }], languages: ['en'],
      source_scope: 'explicit_configured_https_origins_only', jobs: this.researchJob ? [this.researchJob] : [], has_more: false } });
  }
  projectTopics(_organizationId: number, projectId: number, snapshotId = 0, candidateIndex?: number) {
    return Promise.resolve({ status: 200, body: snapshotId ? candidateIndex === undefined
      ? { project_id: projectId, snapshot_id: snapshotId, coverage: { truncated: false }, candidates: [
        { index: 0, evidence: this.topicEvidence, review: this.topicReviews[0] || null }] }
      : { project_id: projectId, snapshot_id: snapshotId, candidate_index: candidateIndex,
        evidence: this.topicEvidence, history: [...this.topicReviews], source_current: this.topicSourceCurrent }
      : { project_id: projectId, feeds: ['https://research-source.example.invalid/rss'], languages: ['en'],
        news: { provider: 'gdelt', phrases: ['local service news'], publisher_origins: ['https://research-source.example.invalid'], live_verified: false },
        connections: [], imports: [], jobs: [{ id: 81, status: 'queued' }],
        snapshots: [{ id: 80, candidate_count: 1, created_at: '2026-10-01' }], has_more: false } });
  }
  projectTopicReview(_organizationId: number, projectId: number, reviewId: number) {
    if (this.topicReviewHandler) return this.topicReviewHandler(projectId, reviewId);
    return Promise.resolve({ status: this.topicSourceCurrent ? 200 : 409, body: {
      project_id: projectId, review: this.topicReviews.find((row) => row['id'] === reviewId),
      source_current: this.topicSourceCurrent, evidence: this.topicEvidence } });
  }
  saveProjectTopic(_organizationId: number, projectId: number, snapshotId: number, candidateIndex: number, data: Record<string, unknown>) {
    this.topicInputs.push(data);
    const judgments = data['judgments'] as Record<string, { score: number | null; note: string }>;
    const review = { ...data, id: 90 + this.topicReviews.length, project_id: projectId, snapshot_id: snapshotId,
      candidate_index: candidateIndex, revision: Number(data['expected_revision']) + 1, market: 'Türkiye', created_at: '2026-10-01',
      report: { method: 'topic-review-v1', snapshot_id: snapshotId, candidate_index: candidateIndex,
        components: [...['relevance', 'business_value', 'geographic_language_fit', 'existing_coverage'].map((name) => ({
          name, ...judgments[name], maximum: 3, basis: 'human_judgment_not_measured' })),
          { name: 'growth', score: null, maximum: 1, basis: 'unavailable_feed_is_not_trend_measurement' },
          { name: 'freshness', score: null, maximum: 1, basis: 'feed_reported_date_at_collection_not_verified_publication_or_current_freshness' },
          { name: 'evidence', score: 1, maximum: 3, basis: 'bounded_source_observation_count_not_authority_confidence_or_demand' },
          { name: 'competition', score: null, maximum: 3, basis: 'unavailable_no_connected_competition_provider' },
        ], existing_mapping: null } };
    if (this.topicSaveStatus === 201) this.topicReviews.unshift(review);
    return Promise.resolve({ status: this.topicSaveStatus, body: { project_id: projectId, review } });
  }
  discoverProjectTopics(_organizationId: number, projectId: number, data: Record<string, unknown>) {
    this.topicDiscoveryInputs.push(data);
    return Promise.resolve({ status: 202, body: { project_id: projectId, job_id: 81, status: 'queued', estimated_units: 1 } });
  }
  projectTopicJob(_organizationId: number, projectId: number, id: number, cancel = false) {
    return Promise.resolve({ status: 200, body: { project_id: projectId, job: { id, project_id: projectId,
      status: cancel ? 'cancelled' : 'running', cancel_requested: cancel, error_category: '', snapshot_id: null,
      estimated_units: 1, attempted_units: 0, steps: [] } } });
  }
  queueProjectResearch(_organizationId: number, projectId: number, data: Record<string, unknown>) {
    this.researchRequests.push(data);
    this.researchJob = { id: 72, project_id: projectId, topic: data['topic'], status: 'queued',
      updated_at: '2026-09-30T10:00:00Z', error_category: '', estimate_units: 2, attempted_units: 0,
      cancel_requested: false, estimated_max_cost_usd: '0.01', context_current: true, usage: null, evidence: null };
    return Promise.resolve({ status: 202, body: { project_id: projectId, job: this.researchJob } });
  }
  projectResearchJob(_organizationId: number, projectId: number, _jobId: number, cancel = false) {
    const job = { ...this.researchJob!, project_id: projectId, status: cancel ? 'cancelled' : 'partially_succeeded',
      cancel_requested: cancel, attempted_units: 2, evidence: cancel ? null : { coverage: 'partial',
        provider_search: 'not_used_explicit_urls_only', sources: [{ index: 0, state: 'collected',
          url: 'https://research-source.example.invalid/page', title: 'Synthetic research',
          excerpt: 'Evidence is provisional.', sha256: 'a'.repeat(64), retrieved_at: '2026-09-30T10:00:00Z' }],
        synthesis_state: 'ai_draft_requires_human_review', synthesis: { summary: 'Review this synthetic result.',
          claims: [{ text: 'Review an interpretation.', source_index: 0, quote: 'Evidence is provisional.' }] } } };
    return Promise.resolve({ status: 200, body: { project_id: projectId, job } });
  }
  projectBriefs(_organizationId: number, projectId: number) {
    return Promise.resolve({ status: 200, body: { project_id: projectId, briefs: this.briefRows, has_more: false } });
  }
  contentRows: Record<string, unknown>[] = [];
  generationInputs: Record<string, unknown>[] = [];
  generationJobs: Record<string, unknown>[] = [];
  contentInputs: Record<string, unknown>[] = [];
  contentStatus = 201;
  projectContent(_organizationId: number, projectId: number, itemId = 0) {
    const current = this.contentRows[0];
    return Promise.resolve({ status: 200, body: itemId ? { project_id: projectId, current,
      history: this.contentRows, next_before: null, source_state: 'current_review_still_required',
      brief: { version: 'content-brief-v1', project_id: projectId, research_job_id: 72, action_review_id: 74,
        scope: 'human_authored_structure_and_unverified_ai_interpretation_not_publication',
        approval: 'draft_human_review_required_no_site_change', source_coverage: 'collected_selected_sources_only',
        topic: 'Synthetic content source', angle: 'Human angle', audience: 'User-entered audience',
        business_goal: 'User-entered goal', action_revision: 2, outline: ['Human heading'],
        research_summary_to_verify: 'Unverified source interpretation',
        claims_to_verify: [{ text: 'Unverified source claim', quote: 'Original synthetic quote', source_index: 0 }],
        sources: [{ index: 0, state: 'collected', url: 'https://source.example.invalid/article', title: 'Synthetic source',
          sha256: 'a'.repeat(64), retrieved_at: '2026-09-30T10:00:00Z' }] }
    } : { project_id: projectId, items: this.contentRows.slice(0, 1), next_before: null } });
  }
  saveProjectContent(_organizationId: number, projectId: number, itemId: number, data: Record<string, unknown>) {
    this.contentInputs.push(data);
    const row = { ...data, id: 100 + this.contentRows.length, item_id: itemId || 80, project_id: projectId,
      revision: Number(data['expected_revision'] || 0) + 1, actor_id: 1, approved_by_id: null,
      reviewed_revision_id: null, approved_at: null, generating_job_id: null, publication_url: '', published_at: null,
      created_at: '2026-09-30T12:00:00Z' };
    if (this.contentStatus === 201) this.contentRows.unshift(row);
    return Promise.resolve({ status: this.contentStatus, body: { project_id: projectId, revision: row } });
  }
  contentGeneration(_organizationId: number, projectId: number, jobId = 0, cancel = false) {
    if (!jobId) return Promise.resolve({ status: 200, body: { project_id: projectId, jobs: this.generationJobs } });
    const job = { ...this.generationJobs.find((row) => row['id'] === jobId), status: cancel ? 'cancelled' : 'succeeded',
      cancel_requested: cancel, draft: cancel ? null : { item_id: 80, review_state: 'unverified_draft_human_review_required' } };
    return Promise.resolve({ status: 200, body: { project_id: projectId, job } });
  }
  generateProjectContent(_organizationId: number, projectId: number, data: Record<string, unknown>) {
    this.generationInputs.push(data);
    const job = { id: 101, project_id: projectId, status: 'queued', brief_id: data['brief_id'], kind: data['kind'],
      platform: data['platform'], source_current: true, estimate_units: 1, attempted_units: 0, cancel_requested: false,
      error_category: '', estimated_max_cost_usd: '0.02', draft: null, usage: null };
    this.generationJobs = [job];
    return Promise.resolve({ status: 202, body: { project_id: projectId, job } });
  }
  createProjectBrief(_organizationId: number, projectId: number, data: Record<string, unknown>) {
    this.briefInputs.push(data);
    const brief = { id: 75, project_id: projectId, research_job_id: data['research_job_id'], action_review_id: 91,
      created_at: '2026-09-30T10:00:00Z', size_bytes: 300, sha256: 'a'.repeat(64),
      review_state: 'draft_human_review_required_no_site_change' };
    this.briefRows = [brief];
    return Promise.resolve({ status: 201, body: { project_id: projectId, brief } });
  }
  projectBrief(_organizationId: number, projectId: number, id: number) {
    const brief = this.briefRows.find((row) => row['id'] === id);
    return Promise.resolve({ status: 200, body: { project_id: projectId, brief,
      draft: { version: 'content-brief-v1', project_id: projectId, research_job_id: brief?.['research_job_id'],
        action_review_id: brief?.['action_review_id'], scope: 'human_authored_structure_and_unverified_ai_interpretation_not_publication',
        audience: 'unknown_not_entered', business_goal: 'Human business goal', desired_action: '', meta_description: '', topic: 'Human-selected topic', angle: 'Human reviewer angle',
        title_options: ['Human title'], outline: ['Human heading'], questions: [], relevant_internal_links: ['https://source.example.invalid/page'],
        research_summary_to_verify: 'Evidence is provisional.', claims_to_verify: [{ text: 'Check this claim',
          quote: 'Source quote', source_index: 0 }], sources: [{ index: 0, state: 'collected',
          url: 'https://research-source.example.invalid/', title: 'Synthetic source', sha256: 'a'.repeat(64), retrieved_at: '2026-10-01T00:00:00Z' }],
        approval: 'draft_human_review_required_no_site_change', source_coverage: 'partial', action_revision: 2,
        page_kind: 'existing_unverified' } } });
  }
  firstProjectAudit(_organizationId: number, projectId: number) {
    return Promise.resolve({ status: 200, body: { project_id: projectId,
      mode: this.firstAuditDemo ? 'synthetic_demo_separate_no_live_observation' : 'live_configured_project_sources',
      scope: 'current_bounded_project_sources_not_a_complete_audit', imports: [],
      crawl: this.firstAuditJob ? [this.firstAuditJob] : [], performance: [],
      candidates: this.firstAuditCandidate ? [this.firstAuditCandidate] : [],
      candidate_state: this.firstAuditCandidate ? 'candidates' : 'no_current_candidates_observed_not_clean',
      candidates_truncated: false } });
  }
  firstProjectAuditCompletion(organizationId: number, projectId: number) {
    this.firstAuditHistoryReads.push([organizationId, projectId]);
    return this.firstAuditHistoryHandler?.() || Promise.resolve(this.firstAuditHistoryResult);
  }
  firstProjectAuditUsefulnessTiming(organizationId: number, projectId: number) {
    this.usefulnessTimingReads.push([organizationId, projectId]);
    return this.usefulnessTimingHandler?.() || Promise.resolve(structuredClone(this.usefulnessTimingResult));
  }
  firstProjectAuditActionSource(organizationId: number, projectId: number, actionId: string, revision: number) {
    this.auditActionReads.push({organizationId, projectId, actionId, revision});
    return this.auditActionHandler?.() || Promise.resolve(this.auditActionResult);
  }
  firstProjectAuditUsefulness(organizationId: number, projectId: number, actionId?: string, revision?: number) {
    this.usefulnessReads.push({ organizationId, projectId, actionId, revision });
    const source = this.usefulnessSource();
    const result = { status: 200, body: actionId ? { organization_id: organizationId, project_id: projectId, action_id: actionId,
      revision, challenge: { method: 'bounded-audit-usefulness-ack-v1', source, source_digest: fixtureDigest(source),
        receipt_proof: this.usefulnessProof, expires_at: this.usefulnessExpires(), acknowledgment_recorded: false } } : this.usefulnessHistory() };
    return this.usefulnessHandler?.(result, actionId) || Promise.resolve(structuredClone(result));
  }
  acknowledgeFirstProjectAuditUsefulness(organizationId: number, projectId: number, actionId: string, revision: number, proof: string) {
    this.usefulnessPosts.push({ organizationId, projectId, actionId, revision, proof });
    if (!this.usefulnessDrop) this.usefulnessSaved = { ...this.usefulnessHistory(), state: 'recorded', action_id: actionId,
      revision, tracking_started_at: '2026-09-29T10:00:00Z', acknowledged_at: new Date().toISOString(),
      source_digest: 'd'.repeat(64), declaration_digest: fixtureDigest(this.usefulnessSource()),
      source: structuredClone(this.auditActionResult.body['source']) };
    const result = { status: 200, body: structuredClone(this.usefulnessHistory()) };
    return this.usefulnessPostHandler?.(result) || (this.usefulnessLose || this.usefulnessDrop
      ? Promise.reject(new Error('Synthetic uncertain response')) : Promise.resolve(result));
  }
  startFirstProjectAudit(_organizationId: number, projectId: number, pages: number) {
    this.firstAuditRequests.push(pages);
    this.firstAuditJob = { id: 77, handler: 'crawl_site', status: 'queued', error_category: '',
      estimated_units: pages, attempted_units: 0, cancel_requested: false,
      retry_supported: true, steps: [], steps_has_more: false,
      created_at: '2026-09-30T10:00:00Z', updated_at: '2026-09-30T10:00:00Z' };
    return Promise.resolve({ status: 202, body: { project_id: projectId, job: this.firstAuditJob } });
  }
  firstProjectAuditJob(_organizationId: number, projectId: number, _jobId: number, cancel = false): Promise<ApiResult> {
    this.firstAuditJob = { ...this.firstAuditJob!, status: cancel ? 'cancelled' : 'partially_succeeded',
      cancel_requested: cancel, attempted_units: 1, steps: [{ sequence: 1, name: 'Fetch project page',
        status: 'failed', progress_percent: 50, error_category: 'synthetic_failure' }] };
    return Promise.resolve({ status: 200, body: { project_id: projectId, job: this.firstAuditJob } });
  }
  retryFirstProjectAudit(_organizationId: number, projectId: number, _jobId: number, _key: string): Promise<ApiResult> {
    return Promise.resolve({ status: 202, body: { project_id: projectId,
      job: { ...this.firstAuditJob!, id: 78, status: 'queued', attempted_units: 0, steps: [] } } });
  }
  intentClusterHistory(_organizationId: number, projectId: number, clusterId: string) {
    return Promise.resolve({ status: 200, body: { project_id: projectId,
      history: this.intentRows.filter((row) => row['cluster_id'] === clusterId) } });
  }
  saveIntentCluster(_organizationId: number, projectId: number, data: Record<string, unknown>, clusterId?: string): Promise<ApiResult> {
    this.savedIntent.push({ ...data, projectId, clusterId });
    const manual = Array.isArray(data['manual_topics']) && data['manual_topics'].length > 0;
    const row = { review_id: 91, cluster_id: clusterId || 'f4eccfe5-71cb-4bbf-99dd-c851494e45ce',
      revision: clusterId ? Number(data['expected_revision']) + 1 : 1,
      label: data['label'], market: 'Turkey', language: data['language'], intent: data['intent'],
      page_kind: data['page_kind'], preferred_page: data['preferred_page'], reason: data['reason'],
      source_finding_ids: data['source_finding_ids'], manual_topics: data['manual_topics'],
      source_terms: manual ? data['manual_topics'] : ['owned query'],
      source_kind: manual ? 'manual_seed_no_search_observation' : 'csv_query_candidate_not_joined_to_page',
      proposed_action: data['proposed_action'], action_reason: data['action_reason'],
      affected_page: data['affected_page'], proposal_state: 'unapproved_human_proposal',
      source_current: true,
      page_attribution: 'human_selected_no_joint_query_page_evidence', created_at: '2026-09-29T10:00:00Z' };
    this.intentRows = [row];
    return Promise.resolve({ status: clusterId ? 200 : 201, body: { project_id: projectId, cluster: row } });
  }
  projectActions(_organizationId: number, projectId: number) {
    return Promise.resolve({ status: 200, body: { project_id: projectId, current_user_id: this.actionCurrentUserId,
      actions: this.actionRows, has_more: false } });
  }
  actionHistory(_organizationId: number, projectId: number, actionId: string) {
    return Promise.resolve({ status: 200, body: { project_id: projectId, current_user_id: 7,
      history: this.actionRows.filter((row) => row['action_id'] === actionId) } });
  }
  saveAction(_organizationId: number, projectId: number, data: Record<string, unknown>, actionId?: string) {
    this.savedActions.push({ ...data, projectId, actionId });
    const row = { action_id: actionId || 'a64070a5-91a1-4198-9556-651ab00c11bc',
      revision: actionId ? Number(data['expected_revision']) + 1 : 1, state: data['state'],
      action_kind: data['action_kind'], source_type: data['source_type'], source_id: data['source_id'],
      source_current: true, affected_urls: ['https://example.invalid/page'],
      assignee_id: data['assignee_id'], acceptance_criteria: data['acceptance_criteria'],
      reason: data['reason'], change_summary: data['change_summary'], verification_note: data['verification_note'],
      outcome_note: data['outcome_note'], implemented_at: data['implemented_at'], verified_at: null,
      outcome_reviewed_at: null, execution: 'human_only_no_website_change' };
    this.actionRows = [row];
    return Promise.resolve({ status: actionId ? 200 : 201, body: { project_id: projectId, action: row } });
  }
  actionOutcomes(_organizationId: number, projectId: number, _actionId: string) {
    return Promise.resolve({ status: 200, body: { project_id: projectId,
      outcomes: this.outcomeRows, state: this.outcomeRows.length ? 'recorded_source_limited' : 'unavailable_no_comparison',
      has_more: false } });
  }
  recordPageOutcome(_organizationId: number, projectId: number, actionId: string,
                    connectionId: number, before: number, after: number) {
    this.recordedOutcomeInputs.push({connectionId, before, after});
    const metric = { state: 'zero_baseline', previous: '0', current: '4', absolute_change: '4', relative_change: null };
    const row = { id: 72, action_id: actionId, action_revision: 4, source_current: true,
      recorded_at: '2026-09-29T12:00:00Z', report: { method_version: 'gsc-csv-page-outcome-v1',
        page: 'https://onboarding.example/landing', implementation_date: '2026-09-10',
        coverage: 'uploaded_file_rows_complete_provider_top_rows_unknown', reporting_lag_days: 6, gap_days: 2,
        before: { import_id: before, start: '2026-08-01', end: '2026-08-07' },
        after: { import_id: after, start: '2026-09-15', end: '2026-09-21' },
        search_metrics: { clicks: metric, impressions: metric, ctr: metric, average_position: metric },
        conversion: { state: 'unavailable_no_exact_origin_ga4_source' },
        interpretation: 'observed_comparable_page_rows_not_causal_uplift' } };
    this.outcomeRows = [row];
    return Promise.resolve({ status: 201, body: { project_id: projectId, outcome: row } });
  }
  actionTechnicalOutcomes(_organizationId: number, projectId: number, _actionId: string) {
    return Promise.resolve({ status: 200, body: { project_id: projectId,
      snapshots: this.technicalOutcomeRows, state: this.technicalOutcomeRows.length ? 'recorded_crawl_observations' : 'not_checked',
      has_more: false } });
  }
  recordTechnicalOutcome(_organizationId: number, projectId: number, actionId: string, before: number, after: number) {
    this.recordedTechnicalInputs.push({ before, after });
    const row = { id: 71, action_id: actionId, action_revision: 4, recorded_at: '2026-09-29T12:00:00Z',
      report: { method_version: 'action-crawl-observation-v1',
        previous: { crawl_run_id: before, completed_at: '2026-09-01T12:00:00Z' },
        current: { crawl_run_id: after, completed_at: '2026-09-27T12:00:00Z' },
        urls: [{ url: 'https://onboarding.example/landing', state: 'observed_http_page_changes_not_fix_proof',
          previous: { status_code: 200, title: 'Before title' }, current: { status_code: 200, title: 'After title' },
          changes: { title: { previous: 'Before title', current: 'After title' } } }],
        interpretation: 'observed_technical_state_not_automatic_verification_or_causal_outcome' } };
    this.technicalOutcomeRows = [row];
    return Promise.resolve({ status: 201, body: { project_id: projectId, snapshot: row } });
  }
  localAssessments(_organizationId: number, projectId: number) {
    return Promise.resolve({ status: 200, body: { project_id: projectId,
      assessments: this.localAssessmentRows, has_more: false } });
  }
  localAssessmentHistory(_organizationId: number, projectId: number, digest: string) {
    return Promise.resolve({ status: 200, body: { project_id: projectId,
      history: this.localAssessmentRows.filter((row) => row['location_digest'] === digest) } });
  }
  saveLocalAssessment(_organizationId: number, projectId: number, data: Record<string, unknown>, digest?: string): Promise<ApiResult> {
    this.savedLocalAssessments.push({ ...data, projectId, digest });
    const row = { id: 90, location_digest: digest || 'a'.repeat(64),
      revision: digest ? Number(data['expected_revision']) + 1 : 1,
      configuration_revision: data['expected_config_revision'], source_current: true,
      location_label: data['location_label'], business_name: data['business_name'],
      address_display: data['address_display'], phone: data['phone'], hours: data['hours'],
      services: data['services'], service_areas: data['service_areas'], profile_url: data['profile_url'],
      eligibility: data['eligibility'], review_theme: data['review_theme'], evidence_note: data['evidence_note'],
      suggested_action: data['suggested_action'], actor_id: 7, reviewed_at: '2026-09-29T12:00:00Z',
      verification_state: 'manual_user_supplied_not_listing_or_provider_verified' };
    this.localAssessmentRows = [row];
    return Promise.resolve({ status: digest ? 200 : 201, body: { project_id: projectId, assessment: row } });
  }
  recordImportFindings(_organizationId: number, projectId: number, connectionId: number, importId: number) {
    this.findingRows = [{ id: 112, detector: 'web_position_4_to_20_candidate',
      method_version: 'gsc-csv-opportunity-v1', subject: 'owned query', source_metric_id: 22, source_indexation_id: null,
      source_diagnostics_id: null, source_performance_id: null,
      source_import_id: importId, source_connection_id: connectionId, source_current: true,
      confidence: 'candidate_not_proven_business_value', detected_at: '2026-09-28T01:00:00Z',
      evidence: { source: 'search_console_csv' }, review: null }];
    return Promise.resolve({ status: 201, body: { project_id: projectId, connection_id: connectionId,
      import_id: importId, finding_ids: [112], truncated_candidates: false,
      status: 'recorded_candidate_evidence_not_prioritized' } });
  }
  recordQueryChangeFindings(_organizationId: number, projectId: number, connectionId: number,
    _previousImportId: number, currentImportId: number) {
    this.findingRows = [{ id: 116, detector: 'web_query_clicks_decreased_candidate',
      method_version: 'gsc-query-change-v1', subject: 'owned query', source_metric_id: 32,
      source_indexation_id: null, source_diagnostics_id: null, source_performance_id: null,
      source_import_id: currentImportId, source_connection_id: connectionId, source_current: true,
      confidence: 'candidate_source_limited', detected_at: '2026-09-28T01:00:00Z',
      evidence: { coverage: { hidden_queries: 'unknown' } }, review: null }];
    return Promise.resolve({ status: 201, body: { project_id: projectId, connection_id: connectionId,
      finding_ids: [116], truncated_candidates: false,
      status: 'recorded_candidate_evidence_not_prioritized' } });
  }
  recordPageChangeFindings(_organizationId: number, projectId: number, connectionId: number,
    _previousImportId: number, currentImportId: number) {
    this.findingRows = [{ id: 117, detector: 'web_page_clicks_decreased_candidate',
      method_version: 'gsc-page-change-v1', subject: 'https://onboarding.example/page',
      source_metric_id: 42, source_indexation_id: null, source_diagnostics_id: null,
      source_performance_id: null, source_import_id: currentImportId,
      source_connection_id: connectionId, source_current: true, confidence: 'candidate_source_limited',
      detected_at: '2026-09-28T01:00:00Z', evidence: { coverage: { hidden_queries: 'unknown' } }, review: null }];
    return Promise.resolve({ status: 201, body: { project_id: projectId, connection_id: connectionId,
      finding_ids: [117], truncated_candidates: false,
      status: 'recorded_candidate_evidence_not_prioritized' } });
  }
  recordIndexationFindings(_organizationId: number, projectId: number, crawlRunId: number) {
    this.findingRows = [{ id: 113, detector: 'sitemap_http_or_noindex_candidate',
      method_version: 'indexation-candidate-v1', subject: 'https://onboarding.example/', source_metric_id: null,
      source_indexation_id: 51, source_diagnostics_id: null, source_performance_id: null,
      source_import_id: null, source_connection_id: null, source_current: true,
      confidence: 'candidate_not_engine_or_live_crawl_proof', detected_at: '2026-09-28T01:00:00Z',
      evidence: { source: 'local_indexation' }, review: null }];
    return Promise.resolve({ status: 201, body: { project_id: projectId, crawl_run_id: crawlRunId,
      finding_ids: [113], engine_report_scope: 'unavailable', truncated_candidates: false,
      status: 'recorded_candidate_evidence_not_prioritized' } });
  }
  recordTechnicalFindings(_organizationId: number, projectId: number, diagnosticsId: number) {
    this.findingRows = [{ id: 114, detector: 'canonical_canonical_chain',
      method_version: 'technical-candidate-v1', subject: 'https://onboarding.example/',
      source_metric_id: null, source_indexation_id: null, source_diagnostics_id: diagnosticsId,
      source_performance_id: null, source_import_id: null, source_connection_id: null,
      source_current: true, confidence: 'candidate_source_limited', detected_at: '2026-09-28T01:00:00Z',
      evidence: { source: 'technical_diagnostics' }, review: null }];
    return Promise.resolve({ status: 201, body: { project_id: projectId, diagnostics_id: diagnosticsId,
      finding_ids: [114], truncated_candidates: false,
      status: 'recorded_candidate_evidence_not_prioritized' } });
  }
  recordPerformanceFindings(_organizationId: number, projectId: number, observationId: number) {
    this.findingRows = [{ id: 115, detector: 'poor_crux_field_lcp_candidate',
      method_version: 'performance-candidate-v1', subject: 'https://onboarding.example/',
      source_metric_id: null, source_indexation_id: null, source_diagnostics_id: null,
      source_performance_id: observationId, source_import_id: null, source_connection_id: null,
      source_current: true, confidence: 'candidate_source_limited', detected_at: '2026-09-28T01:00:00Z',
      evidence: { source: 'crux_history' }, review: null }];
    return Promise.resolve({ status: 201, body: { project_id: projectId, observation_id: observationId,
      finding_ids: [115], truncated_candidates: false,
      status: 'recorded_candidate_evidence_not_prioritized' } });
  }
  reviewFinding(_organizationId: number, projectId: number, findingId: number, expectedRevision: number,
    priority: string, estimatedEffort: string, businessRelevance: string, reason: string): Promise<ApiResult> {
    const review = { id: 120, revision: expectedRevision + 1, priority,
      estimated_effort: estimatedEffort, business_relevance: businessRelevance, review_reason: reason };
    this.findingRows = this.findingRows.map((item) => item['id'] === findingId ? { ...item, review } : item);
    return Promise.resolve({ status: 201, body: { project_id: projectId, finding_id: findingId,
      review, recommendation: null, approved_action: null } });
  }
  reviewSourceQuery(_organizationId: number, _projectId: number, _connectionId: number,
    queryId: number, revision: number, label: string, reason: string): Promise<ApiResult> {
    this.brandReviews.push({ queryId, revision, label, reason });
    return Promise.resolve({ status: 201, body: { review: { revision: revision + 1, label } } });
  }
  sourceQueryHistory(_organizationId: number, projectId: number, connectionId: number, queryId: number) {
    return Promise.resolve({ status: 200, body: { project_id: projectId, connection_id: connectionId,
      query_id: queryId, reviews: this.brandReviews.map((review, index) => ({ revision: index + 1,
        label: review.label, reason: review.reason, created_at: '2026-09-26T00:00:00Z' })), has_more: false } });
  }
  updateProjectOnboarding(_organizationId: number, _projectId: number, details: Record<string, unknown>) {
    this.onboardingUpdates.push(details);
    if (this.onboardingHandler) return this.onboardingHandler(details);
    const current = this.onboardingResult.body['configuration'] as Record<string, unknown>;
    const source = details['source_choice'] || current['source_choice'];
    const configuration = { ...current, ...details, revision: Number(current['revision']) + 1,
      source_state: source === 'synthetic_demo' ? 'synthetic_demo' : source === 'skip' ? 'skipped'
        : source === 'connect_search_console' ? 'disconnected' : source === 'import_search_console' ? 'awaiting_import' : 'not_selected' };
    this.onboardingResult = { status: 200, body: { ...this.onboardingResult.body, configuration } };
    return Promise.resolve({ status: 200, body: { configuration } });
  }
  hasPendingVerification(_result: ApiResult) { return false; }
  hasPendingMfa(result: ApiResult) {
    const data = result.body['data'];
    const flows = data && typeof data === 'object' ? (data as Record<string, unknown>)['flows'] : undefined;
    return Array.isArray(flows) && flows.some((flow) => (
      !!flow && typeof flow === 'object'
      && (flow as Record<string, unknown>)['id'] === 'mfa_authenticate'
      && (flow as Record<string, unknown>)['is_pending'] === true
    ));
  }
}

describe('public/account/app route boundaries', () => {
  beforeEach(() => TestBed.configureTestingModule({
    providers: [provideRouter(routes), { provide: AccountApi, useClass: AccountApiStub }],
  }));

  it.each(['en', 'tr'] as const)('loads the unreviewed public homepage draft by explicit path in %s', async (language) => {
    const path = language === 'tr' ? '/preview/tr/home' : '/';
    const preference = vi.spyOn(TestBed.inject(AccountApi), 'productLanguage');
    const harness = await RouterTestingHarness.create(path); const root = harness.routeNativeElement!;
    expect(root.querySelector('h1')?.textContent).toContain(language === 'tr' ? 'Müşteri sitelerinin kanıtlarını' : 'client-site evidence');
    expect(root.textContent).toContain(language === 'tr' ? 'Herkese açık deneme ve ödeme sunulmaz' : 'Public trials and payments are not open.');
    expect(root.textContent).toContain(language === 'tr' ? 'müşteri sonuçları veya canlı rapor değildir' : 'not customer results or a live report');
    expect(root.textContent).toContain(language === 'tr' ? 'eksik verileri ölçülmüş sonuçlardan ayrı' : 'missing data distinct from measured results');
    expect(root.querySelector('.home-draft')?.getAttribute('lang')).toBe(language);
    expect(root.querySelector('[role="status"]')?.textContent).toContain(language === 'tr' ? 'İki dilli insan onayı' : 'Bilingual human approval');
    expect(document.documentElement.lang).toBe(language);
    expect(document.title).toContain(language === 'tr' ? 'Türkçe taslak' : 'Agency SEO evidence workflow');
    expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).toContain(language === 'tr' ? 'incelenmemiş Türkçe taslak' : 'agency teams');
    expect(root.querySelector('a[href="/account/register"]')).toBeTruthy();
    expect(root.querySelector('a[href="/account/login"]')).toBeTruthy();
    expect(root.querySelector(`a[href="${language === 'tr' ? '/preview/tr' : '/preview'}"]`)).toBeTruthy();
    expect(root.querySelector(`a[href="${language === 'tr' ? '/preview/tr/sample-report' : '/sample-report'}"]`)).toBeTruthy();
    expect(root.querySelector(`a[href="${language === 'tr' ? '/preview/tr/help' : '/preview/help'}"]`)).toBeTruthy();
    expect(root.querySelector(`a[href="${language === 'tr' ? '/preview/tr/seo-agencies' : '/preview/seo-agencies'}"]`)).toBeTruthy();
    expect(root.querySelector(`a[href="${language === 'tr' ? '/preview/tr/seo-opportunities' : '/preview/seo-opportunities'}"]`)).toBeTruthy();
    expect(root.querySelector(`a[href="${language === 'tr' ? '/preview/tr/accessibility' : '/preview/accessibility'}"]`)).toBeTruthy();
    expect(root.querySelector(`a[href="${language === 'tr' ? '/preview/tr/data-handling' : '/preview/data-handling'}"]`)).toBeTruthy();
    expect(root.querySelector(`a[href="${language === 'tr' ? '/preview/tr/cancellation' : '/preview/cancellation'}"]`)).toBeTruthy();
    expect(root.querySelector(`a[href="${language === 'tr' ? '/preview/tr/privacy' : '/preview/privacy'}"]`)).toBeTruthy();
    expect(root.querySelector(`a[href="${language === 'tr' ? '/preview/tr/terms' : '/preview/terms'}"]`)).toBeTruthy();
    expect(root.querySelector(`a[href="${language === 'tr' ? '/preview/tr/contact' : '/preview/contact'}"]`)).toBeTruthy();
    expect(root.querySelector(`a[href="${language === 'tr' ? '/preview/tr/pricing' : '/preview/pricing'}"]`)).toBeTruthy();
    expect(root.querySelector(`a[href="${language === 'tr' ? '/preview/tr/content-and-keywords' : '/preview/content-and-keywords'}"]`)).toBeTruthy();
    expect(root.querySelector(`a[href="${language === 'tr' ? '/preview/tr/airport-transfer-seo' : '/preview/airport-transfer-seo'}"]`)).toBeTruthy();
    expect(root.querySelector(`a[href="${language === 'tr' ? '/preview/tr/data-sources' : '/preview/data-sources'}"]`)).toBeTruthy();
    expect(root.querySelector(`a[href="${language === 'tr' ? '/preview/tr/technical-seo-audits' : '/preview/technical-seo-audits'}"]`)).toBeTruthy();
    expect(TestBed.inject(Router).routerState.snapshot.root.firstChild?.firstChild?.routeConfig?.path).toBe(path.slice(1));
    expect(root.querySelector(`nav a[lang="${language}"]`)?.getAttribute('aria-current')).toBe('page');
    root.querySelector<HTMLAnchorElement>(`nav a[lang="${language === 'tr' ? 'en' : 'tr'}"]`)!.click();
    await harness.fixture.whenStable(); harness.detectChanges();
    expect(document.documentElement.lang).toBe(language === 'tr' ? 'en' : 'tr');
    expect(document.querySelector('link[rel="canonical"], link[hreflang]')).toBeNull();
    expect(preference).not.toHaveBeenCalled(); preference.mockRestore();
    await harness.navigateByUrl('/account/login');
    expect(document.documentElement.lang).toBe('en');
    expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).not.toContain('Türkçe');
  });

  it('renders unpublished locale drafts by explicit path and restores English metadata on exit', async () => {
    // A direct entry inherits the Turkish prerender's document metadata before hydration.
    document.documentElement.lang = 'tr';
    TestBed.inject(Meta).updateTag({ name: 'description', content: 'Türkçe taslak' });
    const harness = await RouterTestingHarness.create('/preview/tr');
    expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Geliştirme durumu');
    expect(harness.routeNativeElement?.textContent).toContain('iki dilli insan incelemesi bekleyen bir taslak');
    expect(harness.routeNativeElement?.querySelector('section')?.lang).toBe('tr');
    expect(document.documentElement.lang).toBe('tr');
    expect(document.title).toContain('Türkçe taslak');
    expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).toContain('Türkçe taslak');
    expect(harness.routeNativeElement?.querySelector('a[href="/preview"][lang="en"]')).toBeTruthy();
    expect(harness.routeNativeElement?.querySelector('a[href="/preview/tr"]')?.getAttribute('aria-current')).toBe('page');
    await harness.navigateByUrl('/preview');
    expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Development status');
    expect(document.documentElement.lang).toBe('en');
    expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).toContain('unreviewed locale drafts');
    await harness.navigateByUrl('/preview/tr');
    await harness.navigateByUrl('/');
    expect(document.documentElement.lang).toBe('en');
    expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).not.toContain('Türkçe');
    expect(document.querySelector('link[rel="canonical"], link[hreflang]')).toBeNull();
  });

  it('renders the paired synthetic sample drafts by explicit path with unchanged facts and resets locale metadata', async () => {
    const preference = vi.spyOn(TestBed.inject(AccountApi), 'productLanguage');
    const harness = await RouterTestingHarness.create('/preview/tr/sample-report');
    for (const language of ['tr', 'en'] as const) {
      const root = harness.routeNativeElement!;
      expect(root.querySelector('article')?.lang).toBe(language);
      expect(document.documentElement.lang).toBe(language);
      expect(document.title).toContain(language === 'tr' ? 'Türkçe taslak' : 'Synthetic SEO action example');
      expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).toContain(language === 'tr' ? 'incelenmemiş Türkçe taslak' : 'unreviewed draft');
      expect(root.querySelector('[role="status"]')?.textContent).toContain(language === 'tr' ? 'İki dilli insan onayı' : 'Bilingual human approval');
      for (const text of language === 'tr'
        ? ['Sentetik geliştirme örneği', 'bağlı bir Search Console mülkü', 'öncelik bir insan kararı', 'Arama sonucu: bilinmiyor', 'tek başına nedenselliği kanıtlamaz']
        : ['Synthetic development example', 'not a connected Search Console property', 'human decision', 'Search outcome: unknown', 'alone would not prove causation']) expect(root.textContent).toContain(text);
      expect(root.querySelector('code[lang="en"]')?.textContent).toBe('sample.example.invalid');
      expect([...root.querySelectorAll('tbody [lang="en"]')].map(row => row.textContent)).toEqual(['airport transfer example', '1,200', '24', '2%']);
      expect(root.querySelector('form, img, script, iframe')).toBeNull();
      expect(document.querySelector('link[rel="canonical"], link[hreflang]')).toBeNull();
      expect(root.querySelector(`nav a[lang="${language}"]`)?.getAttribute('aria-current')).toBe('page');
      if (language === 'tr') {
        root.querySelector<HTMLAnchorElement>('nav a[lang="en"]')!.click();
        await harness.fixture.whenStable(); harness.detectChanges();
      }
    }
    harness.routeNativeElement!.querySelector<HTMLAnchorElement>('nav a[lang="tr"]')!.click();
    await harness.fixture.whenStable(); harness.detectChanges();
    expect(document.documentElement.lang).toBe('tr');
    expect(preference).not.toHaveBeenCalled();
    preference.mockRestore();
    await harness.navigateByUrl('/account/login');
    expect(document.documentElement.lang).toBe('en');
    expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).not.toContain('Türkçe');
  });

  it('renders paired local help drafts by explicit path and restores English metadata on exit', async () => {
    const preference = vi.spyOn(TestBed.inject(AccountApi), 'productLanguage');
    const harness = await RouterTestingHarness.create('/preview/tr/help');
    for (const language of ['tr', 'en'] as const) {
      const root = harness.routeNativeElement!;
      expect(root.querySelector(`a[href="${language === 'tr' ? '/preview/tr/contact' : '/preview/contact'}"]`)).toBeTruthy();
      for (const [path, label] of language === 'tr'
        ? [['/preview/tr/terms', 'Yerel koşullar taslağını okuyun'], ['/preview/tr/privacy', 'Yerel gizlilik taslağını okuyun'], ['/preview/tr', 'Geliştirme durumunu okuyun']]
        : [['/preview/terms', 'Read local terms draft'], ['/preview/privacy', 'Read local privacy draft'], ['/preview', 'Read development status']]) expect(root.querySelector(`a[href="${path}"]`)?.textContent).toBe(label);
      expect(root.querySelector('article')?.lang).toBe(language);
      expect(document.documentElement.lang).toBe(language);
      expect(document.title).toContain(language === 'tr' ? 'Türkçe taslak' : 'Help and methodology');
      expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).toContain(language === 'tr' ? 'incelenmemiş Türkçe taslak' : 'unreviewed local draft');
      expect(root.querySelectorAll('section h2')).toHaveLength(6);
      expect(root.querySelector('[role="status"]')?.textContent).toContain(language === 'tr' ? 'İki dilli insan onayı' : 'Bilingual human approval');
      for (const text of language === 'tr'
        ? ['müşteri verisi girmeyin', 'Eksik veya kısmi veri sıfır değildir', 'insan onayı gerektirir', 'İptal bir istektir', 'ücretli erişimi doğrulamaz', 'henüz doğrulanmadı', 'yanıt süresi taahhüdü sunmaz', 'OAuth belirteci']
        : ['Do not enter customer data', 'Missing or partial data is not zero', 'require human approval', 'Cancellation is a request', 'does not confirm paid access', 'acceptance remains unverified', 'no public support endpoint or response-time commitment', 'OAuth tokens']) expect(root.textContent).toContain(text);
      for (const path of language === 'tr' ? ['/preview/tr/home', '/preview/tr', '/preview/tr/sample-report'] : ['/', '/preview', '/sample-report']) expect(root.querySelector(`a[href="${path}"]`)).toBeTruthy();
      expect(root.querySelector('form, img, script, iframe, a[href="/help"], a[href="/tr/yardim"], a[href="/contact"]')).toBeNull();
      expect(document.querySelector('link[rel="canonical"], link[hreflang]')).toBeNull();
      expect(root.querySelector(`nav a[lang="${language}"]`)?.getAttribute('aria-current')).toBe('page');
      if (language === 'tr') {
        root.querySelector<HTMLAnchorElement>('nav a[lang="en"]')!.click();
        await harness.fixture.whenStable(); harness.detectChanges();
      }
    }
    harness.routeNativeElement!.querySelector<HTMLAnchorElement>('nav a[lang="tr"]')!.click();
    await harness.fixture.whenStable(); harness.detectChanges();
    expect(document.documentElement.lang).toBe('tr');
    expect(preference).not.toHaveBeenCalled(); preference.mockRestore();
    await harness.navigateByUrl('/account/login');
    expect(document.documentElement.lang).toBe('en');
    expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).not.toContain('Türkçe');
  });

  it('renders paired local source-readiness drafts by explicit path and restores English metadata on exit', async () => {
    const preference = vi.spyOn(TestBed.inject(AccountApi), 'productLanguage');
    const harness = await RouterTestingHarness.create('/preview/tr/data-sources');
    for (const language of ['tr', 'en'] as const) {
      const root = harness.routeNativeElement!;
      expect(root.querySelector('article')?.lang).toBe(language);
      expect(document.documentElement.lang).toBe(language);
      expect(document.title).toContain(language === 'tr' ? 'Türkçe taslak' : 'SEO data sources, scope and readiness');
      expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).toContain(language === 'tr' ? 'incelenmemiş Türkçe taslak' : 'unreviewed local draft');
      expect(root.querySelectorAll('tbody th[scope="row"]')).toHaveLength(5);
      expect(root.querySelector('[role="status"]')?.textContent).toContain(language === 'tr' ? 'İki dilli insan onayı' : 'Bilingual human approval');
      for (const text of language === 'tr'
        ? ['canlı kullanılabilirliği göstermez', 'gerçek kaynak izinleri ve sağlayıcı kabulü bekleniyor', 'ölçüm kalitesi incelemesi bekleniyor', 'Eksik, bağlantısız, kısmi ve eski', 'rakip trafiğini göstermez']
        : ['not live availability', 'real source grants and provider acceptance pending', 'measurement-quality review pending', 'Missing, disconnected, partial and stale', 'rankings or competitor traffic']) expect(root.textContent).toContain(text);
      for (const path of language === 'tr' ? ['/preview/tr/home', '/preview/tr/help', '/preview/tr/sample-report'] : ['/', '/preview/help', '/sample-report']) expect(root.querySelector(`a[href="${path}"]`)).toBeTruthy();
      expect(root.querySelector('form, img, script, iframe, a[href="/data-sources"], a[href="/tr/veri-kaynaklari"], a[href="/contact"]')).toBeNull();
      expect(document.querySelector('link[rel="canonical"], link[hreflang]')).toBeNull();
      expect(root.querySelector(`nav a[lang="${language}"]`)?.getAttribute('aria-current')).toBe('page');
      if (language === 'tr') {
        root.querySelector<HTMLAnchorElement>('nav a[lang="en"]')!.click();
        await harness.fixture.whenStable(); harness.detectChanges();
      }
    }
    harness.routeNativeElement!.querySelector<HTMLAnchorElement>('nav a[lang="tr"]')!.click();
    await harness.fixture.whenStable(); harness.detectChanges();
    expect(document.documentElement.lang).toBe('tr');
    expect(preference).not.toHaveBeenCalled(); preference.mockRestore();
    await harness.navigateByUrl('/account/login');
    expect(document.documentElement.lang).toBe('en');
    expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).not.toContain('Türkçe');
  });


  it('renders paired local technical-audit drafts by explicit path and restores English metadata on exit', async () => {
    const preference = vi.spyOn(TestBed.inject(AccountApi), 'productLanguage');
    const harness = await RouterTestingHarness.create('/preview/tr/technical-seo-audits');
    for (const language of ['tr', 'en'] as const) {
      const root = harness.routeNativeElement!;
      expect(root.querySelector('article')?.lang).toBe(language);
      expect(document.documentElement.lang).toBe(language);
      expect(document.title).toContain(language === 'tr' ? 'Türkçe taslak' : 'Technical SEO audit evidence');
      expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).toContain(language === 'tr' ? 'incelenmemiş Türkçe taslak' : 'unreviewed local draft');
      expect(root.querySelectorAll('section h2')).toHaveLength(4);
      expect(root.querySelector('[role="status"]')?.textContent).toContain(language === 'tr' ? 'İki dilli insan onayı' : 'Bilingual human approval');
      for (const text of language === 'tr'
        ? ['müşteri denetimi veya ölçülmüş sonuç içermez', 'eksiksiz site veya tüm web veri kümesi değildir', 'arama motorunun sayfayı nasıl render ettiğini kanıtlamaz', 'hiçbiri bir sonrakini garanti etmez', 'dizine eklenme kanıtı değildir', 'insan onayı']
        : ['no customer audit or measured result', 'not a complete site or whole-web dataset', 'does not prove how a search engine rendered', 'none guarantees the next', 'not proof of indexing', 'human approval']) expect(root.textContent).toContain(text);
      for (const path of language === 'tr' ? ['/preview/tr/home', '/preview/tr/data-sources', '/preview/tr/sample-report'] : ['/', '/preview/data-sources', '/sample-report']) expect(root.querySelector(`a[href="${path}"]`)).toBeTruthy();
      expect(root.querySelector('form, img, script, iframe, a[href="/features/technical-seo-audits"], a[href="/tr/ozellikler/teknik-seo-denetimleri"], a[href="/contact"]')).toBeNull();
      expect(root.querySelector(`a[href="${language === 'tr' ? '/preview/tr/seo-opportunities' : '/preview/seo-opportunities'}"]`)).toBeTruthy();
      expect(document.querySelector('link[rel="canonical"], link[hreflang]')).toBeNull();
      expect(root.querySelector(`nav a[lang="${language}"]`)?.getAttribute('aria-current')).toBe('page');
      if (language === 'tr') {
        root.querySelector<HTMLAnchorElement>('nav a[lang="en"]')!.click();
        await harness.fixture.whenStable(); harness.detectChanges();
      }
    }
    harness.routeNativeElement!.querySelector<HTMLAnchorElement>('nav a[lang="tr"]')!.click();
    await harness.fixture.whenStable(); harness.detectChanges();
    expect(document.documentElement.lang).toBe('tr');
    expect(preference).not.toHaveBeenCalled(); preference.mockRestore();
    await harness.navigateByUrl('/account/login');
    expect(document.documentElement.lang).toBe('en');
    expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).not.toContain('Türkçe');
  });


  it('renders paired local agency-team drafts by explicit path and restores English metadata on exit', async () => {
    const preference = vi.spyOn(TestBed.inject(AccountApi), 'productLanguage');
    const harness = await RouterTestingHarness.create('/preview/tr/seo-agencies');
    for (const language of ['tr', 'en'] as const) {
      const root = harness.routeNativeElement!;
      expect(root.querySelector('article')?.lang).toBe(language);
      expect(document.documentElement.lang).toBe(language);
      expect(document.title).toContain(language === 'tr' ? 'Türkçe taslak' : 'Multi-client agency SEO workflow');
      expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).toContain(language === 'tr' ? 'incelenmemiş Türkçe taslak' : 'unreviewed local draft');
      expect(root.querySelectorAll('section h2')).toHaveLength(4);
      expect(root.querySelector('[role="status"]')?.textContent).toContain(language === 'tr' ? 'İki dilli insan onayı' : 'Bilingual human approval');
      for (const text of language === 'tr'
        ? ['proje eklemek yeni bir deneme başlatmaz', 'başka bir kuruluşa erişim vermez', 'Görüntüleyiciler iş başlatamaz', 'insan onayı gerektirir', 'otomatik raporlar sunulmaz', 'Herkese açık deneme ve ödeme sunulmaz']
        : ['adding a project does not start another trial', 'does not grant access to another organization', 'Viewers cannot launch jobs', 'Human approval is required', 'automatic reports are not offered', 'Public trials and payments are not open']) expect(root.textContent).toContain(text);
      for (const path of language === 'tr' ? ['/preview/tr/home', '/preview/tr/data-sources', '/preview/tr/sample-report', '/preview/tr/technical-seo-audits'] : ['/', '/preview/data-sources', '/sample-report', '/preview/technical-seo-audits']) expect(root.querySelector(`a[href="${path}"]`)).toBeTruthy();
      expect(root.querySelector('form, img, script, iframe, a[href="/seo-agencies"], a[href="/tr/seo-ajanslari"], a[href="/account/register"]')).toBeNull();
      expect(root.querySelector(`a[href="${language === 'tr' ? '/preview/tr/airport-transfer-seo' : '/preview/airport-transfer-seo'}"]`)).toBeTruthy();
      expect(root.querySelector(`a[href="${language === 'tr' ? '/preview/tr/seo-opportunities' : '/preview/seo-opportunities'}"]`)).toBeTruthy();
      expect(document.querySelector('link[rel="canonical"], link[hreflang]')).toBeNull();
      expect(root.querySelector(`nav a[lang="${language}"]`)?.getAttribute('aria-current')).toBe('page');
      if (language === 'tr') {
        root.querySelector<HTMLAnchorElement>('nav a[lang="en"]')!.click();
        await harness.fixture.whenStable(); harness.detectChanges();
      }
    }
    harness.routeNativeElement!.querySelector<HTMLAnchorElement>('nav a[lang="tr"]')!.click();
    await harness.fixture.whenStable(); harness.detectChanges();
    expect(document.documentElement.lang).toBe('tr');
    expect(preference).not.toHaveBeenCalled(); preference.mockRestore();
    await harness.navigateByUrl('/account/login');
    expect(document.documentElement.lang).toBe('en');
    expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).not.toContain('Türkçe');
  });


  it('renders paired local transfer-use-case drafts by explicit path and restores English metadata on exit', async () => {
    const preference = vi.spyOn(TestBed.inject(AccountApi), 'productLanguage');
    const harness = await RouterTestingHarness.create('/preview/tr/airport-transfer-seo');
    for (const language of ['tr', 'en'] as const) {
      const root = harness.routeNativeElement!;
      expect(root.querySelector('article')?.lang).toBe(language);
      expect(document.documentElement.lang).toBe(language);
      expect(document.title).toContain(language === 'tr' ? 'Türkçe taslak' : 'Airport-transfer SEO workflow');
      expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).toContain(language === 'tr' ? 'incelenmemiş Türkçe taslak' : 'unreviewed local draft');
      expect(root.querySelectorAll('section h2')).toHaveLength(4);
      expect(root.querySelector('[role="status"]')?.textContent).toContain(language === 'tr' ? 'İki dilli insan onayı' : 'Bilingual human approval');
      for (const text of language === 'tr'
        ? ['arama talebini kanıtlamaz', 'işletme profili uygunluğunu kanıtlamaz', 'konum ve yorum uydurmayın', 'insan onayı alın', 'nedenselliği kanıtlamaz', 'Herkese açık deneme ve ödeme sunulmaz']
        : ['do not establish search demand', 'does not establish eligibility for a business profile', 'fabricate locations and reviews', 'obtain human approval', 'does not prove causation', 'Public trials and payments are not open']) expect(root.textContent).toContain(text);
      for (const path of language === 'tr' ? ['/preview/tr/home', '/preview/tr/data-sources', '/preview/tr/sample-report', '/preview/tr/technical-seo-audits', '/preview/tr/seo-agencies'] : ['/', '/preview/data-sources', '/sample-report', '/preview/technical-seo-audits', '/preview/seo-agencies']) expect(root.querySelector(`a[href="${path}"]`)).toBeTruthy();
      expect(root.querySelector('form, img, script, iframe, a[href="/use-cases/airport-transfer-seo"], a[href="/tr/kullanim-alanlari/havalimani-transfer-seo"], a[href="/account/register"]')).toBeNull();
      expect(root.querySelector(`a[href="${language === 'tr' ? '/preview/tr/content-and-keywords' : '/preview/content-and-keywords'}"]`)).toBeTruthy();
      expect(document.querySelector('link[rel="canonical"], link[hreflang]')).toBeNull();
      expect(root.querySelector(`nav a[lang="${language}"]`)?.getAttribute('aria-current')).toBe('page');
      if (language === 'tr') {
        root.querySelector<HTMLAnchorElement>('nav a[lang="en"]')!.click();
        await harness.fixture.whenStable(); harness.detectChanges();
      }
    }
    harness.routeNativeElement!.querySelector<HTMLAnchorElement>('nav a[lang="tr"]')!.click();
    await harness.fixture.whenStable(); harness.detectChanges();
    expect(document.documentElement.lang).toBe('tr');
    expect(preference).not.toHaveBeenCalled(); preference.mockRestore();
    await harness.navigateByUrl('/account/login');
    expect(document.documentElement.lang).toBe('en');
    expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).not.toContain('Türkçe');
  });



  it('renders paired local opportunity-review drafts by explicit path and restores English metadata on exit', async () => {
    const preference = vi.spyOn(TestBed.inject(AccountApi), 'productLanguage');
    const harness = await RouterTestingHarness.create('/preview/tr/seo-opportunities');
    for (const language of ['tr', 'en'] as const) {
      const root = harness.routeNativeElement!;
      expect(root.querySelector('article')?.lang).toBe(language);
      expect(document.documentElement.lang).toBe(language);
      expect(document.title).toContain(language === 'tr' ? 'Türkçe taslak' : 'Review SEO opportunities and actions');
      expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).toContain(language === 'tr' ? 'incelenmemiş Türkçe taslak' : 'unreviewed local draft');
      expect(root.querySelectorAll('section h2')).toHaveLength(4);
      expect(root.querySelector('[role="status"]')?.textContent).toContain(language === 'tr' ? 'İki dilli insan onayı' : 'Bilingual human approval');
      for (const text of language === 'tr'
        ? ['yamyamlaşmayı kanıtlamaz', 'ilgili kaynağa bağlı kontrolleri kullanılamaz', 'insan onayı gerektirir', 'müşteri sitesini düzenlemez', 'eksik satır sıfır değil', 'nedensel artışı kanıtlamaz']
        : ['prove cannibalization', 'source-dependent checks unavailable', 'require human approval', 'does not edit a customer site', 'missing row in a top-rows export is unknown, not zero', 'do not prove causal uplift']) expect(root.textContent).toContain(text);
      for (const path of language === 'tr' ? ['/preview/tr/home', '/preview/tr/data-sources', '/preview/tr/sample-report', '/preview/tr/technical-seo-audits'] : ['/', '/preview/data-sources', '/sample-report', '/preview/technical-seo-audits']) expect(root.querySelector(`a[href="${path}"]`)).toBeTruthy();
      expect(root.querySelector('form, img, script, iframe, a[href="/features/seo-opportunities"], a[href="/tr/ozellikler/seo-firsatlari"], a[href="/account/register"]')).toBeNull();
      expect(root.querySelector(`a[href="${language === 'tr' ? '/preview/tr/content-and-keywords' : '/preview/content-and-keywords'}"]`)).toBeTruthy();
      expect(document.querySelector('link[rel="canonical"], link[hreflang]')).toBeNull();
      expect(root.querySelector(`nav a[lang="${language}"]`)?.getAttribute('aria-current')).toBe('page');
      if (language === 'tr') {
        root.querySelector<HTMLAnchorElement>('nav a[lang="en"]')!.click();
        await harness.fixture.whenStable(); harness.detectChanges();
      }
    }
    harness.routeNativeElement!.querySelector<HTMLAnchorElement>('nav a[lang="tr"]')!.click();
    await harness.fixture.whenStable(); harness.detectChanges();
    expect(document.documentElement.lang).toBe('tr');
    expect(preference).not.toHaveBeenCalled(); preference.mockRestore();
    await harness.navigateByUrl('/account/login');
    expect(document.documentElement.lang).toBe('en');
    expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).not.toContain('Türkçe');
  });


  it('renders paired local content-keyword drafts by explicit path and restores English metadata on exit', async () => {
    const preference = vi.spyOn(TestBed.inject(AccountApi), 'productLanguage');
    const harness = await RouterTestingHarness.create('/preview/tr/content-and-keywords');
    for (const language of ['tr', 'en'] as const) {
      const root = harness.routeNativeElement!;
      expect(root.querySelector('article')?.lang).toBe(language);
      expect(document.documentElement.lang).toBe(language);
      expect(document.title).toContain(language === 'tr' ? 'Türkçe taslak' : 'Content and keyword workflow');
      expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).toContain(language === 'tr' ? 'incelenmemiş Türkçe taslak' : 'unreviewed local draft');
      expect(root.querySelectorAll('section h2')).toHaveLength(4);
      expect(root.querySelector('[role="status"]')?.textContent).toContain(language === 'tr' ? 'İki dilli insan onayı' : 'Bilingual human approval');
      for (const text of language === 'tr'
        ? ['Ortak kanıt olmadan yapılan insan eşlemesi bunu belirtmelidir', 'yamyamlaşmayı kanıtlamaz', 'kelime sayısı tek başına', 'Atıflar tek başına özgün uzmanlığı', 'yetkili insan onayı gerektirir', 'otomatik yayımlama']
        : ['human mapping without joint evidence must say so', 'keyword overlap alone does not prove cannibalization', 'word count alone is not a deletion or quality verdict', 'Citations alone do not establish original expertise', 'require authorized human approval', 'does not offer automatic publishing']) expect(root.textContent?.toLowerCase()).toContain(text.toLowerCase());
      for (const path of language === 'tr' ? ['/preview/tr/home', '/preview/tr/seo-opportunities', '/preview/tr/sample-report', '/preview/tr/airport-transfer-seo'] : ['/', '/preview/seo-opportunities', '/sample-report', '/preview/airport-transfer-seo']) expect(root.querySelector(`a[href="${path}"]`)).toBeTruthy();
      expect(root.querySelector('form, img, script, iframe, a[href="/features/content-and-keywords"], a[href="/tr/ozellikler/icerik-ve-anahtar-kelimeler"], a[href="/account/register"]')).toBeNull();
      expect(document.querySelector('link[rel="canonical"], link[hreflang]')).toBeNull();
      expect(root.querySelector(`nav a[lang="${language}"]`)?.getAttribute('aria-current')).toBe('page');
      if (language === 'tr') {
        root.querySelector<HTMLAnchorElement>('nav a[lang="en"]')!.click();
        await harness.fixture.whenStable(); harness.detectChanges();
      }
    }
    harness.routeNativeElement!.querySelector<HTMLAnchorElement>('nav a[lang="tr"]')!.click();
    await harness.fixture.whenStable(); harness.detectChanges();
    expect(document.documentElement.lang).toBe('tr');
    expect(preference).not.toHaveBeenCalled(); preference.mockRestore();
    await harness.navigateByUrl('/account/login');
    expect(document.documentElement.lang).toBe('en');
    expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).not.toContain('Türkçe');
  });


  it('renders paired local pricing-policy drafts by explicit path and restores English metadata on exit', async () => {
    const preference = vi.spyOn(TestBed.inject(AccountApi), 'productLanguage');
    const harness = await RouterTestingHarness.create('/preview/tr/pricing');
    for (const language of ['tr', 'en'] as const) {
      const root = harness.routeNativeElement!;
      expect(root.querySelector('article')?.lang).toBe(language);
      expect(document.documentElement.lang).toBe(language);
      expect(document.title).toContain(language === 'tr' ? 'Türkçe taslak' : 'Planned Agency pricing');
      expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).toContain(language === 'tr' ? 'incelenmemiş Türkçe taslak' : 'unreviewed local draft');
      expect(root.querySelectorAll('section h2')).toHaveLength(6);
      expect(root.querySelector('[role="status"]')?.textContent).toContain(language === 'tr' ? 'İki dilli insan onayı' : 'Bilingual human approval');
      for (const text of language === 'tr'
        ? ['ayda 149 USD', '30 gün, kart gerekmez', '40 dahili birim', '100 dahili birim', 'satın alınabilir kredi değildir', 'hemen tahsil edilir', 'aylık yenilenir', 'dönem sonunda geçerli olur', 'yedi takvim günüdür', '90 günlük', '30 gün içinde', 'en fazla 35 günlük', 'doğrulanmamıştır', 'Paddle satıcı']
        : ['USD 149', '30 days, no card required', '40 internal units', '100 internal units', 'not money, provider cost or purchasable credits', 'charges immediately', 'renews monthly', 'takes effect at period end', 'seven calendar days', '90 days', 'within 30 days', 'maximum 35-day', 'remain unverified', 'Paddle seller']) expect(root.textContent).toContain(text);
      for (const path of language === 'tr' ? ['/preview/tr/home', '/preview/tr/data-sources', '/preview/tr/help'] : ['/', '/preview/data-sources', '/preview/help']) expect(root.querySelector(`a[href="${path}"]`)).toBeTruthy();
      expect(root.querySelector('form, button, img, script, iframe, a[href="/pricing"], a[href="/tr/fiyatlandirma"], a[href="/account/register"], a[href^="https://"]')).toBeNull();
      expect(document.querySelector('link[rel="canonical"], link[hreflang]')).toBeNull();
      expect(root.querySelector(`nav a[lang="${language}"]`)?.getAttribute('aria-current')).toBe('page');
      if (language === 'tr') {
        root.querySelector<HTMLAnchorElement>('nav a[lang="en"]')!.click();
        await harness.fixture.whenStable(); harness.detectChanges();
      }
    }
    harness.routeNativeElement!.querySelector<HTMLAnchorElement>('nav a[lang="tr"]')!.click();
    await harness.fixture.whenStable(); harness.detectChanges();
    expect(document.documentElement.lang).toBe('tr');
    expect(preference).not.toHaveBeenCalled(); preference.mockRestore();
    await harness.navigateByUrl('/account/login');
    expect(document.documentElement.lang).toBe('en');
    expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).not.toContain('Türkçe');
  });


  it('renders paired local contact-support drafts by explicit path and restores English metadata on exit', async () => {
    const preference = vi.spyOn(TestBed.inject(AccountApi), 'productLanguage');
    const harness = await RouterTestingHarness.create('/preview/tr/contact');
    for (const language of ['tr', 'en'] as const) {
      const root = harness.routeNativeElement!;
      for (const [path, label] of language === 'tr'
        ? [['/preview/tr/terms', 'Yerel koşullar taslağını okuyun'], ['/preview/tr/privacy', 'Yerel gizlilik taslağını okuyun'], ['/preview/tr', 'Geliştirme durumunu okuyun']]
        : [['/preview/terms', 'Read local terms draft'], ['/preview/privacy', 'Read local privacy draft'], ['/preview', 'Read development status']]) expect(root.querySelector(`a[href="${path}"]`)?.textContent).toBe(label);
      expect(root.querySelector('article')?.lang).toBe(language);
      expect(document.documentElement.lang).toBe(language);
      expect(document.title).toContain(language === 'tr' ? 'Türkçe taslak' : 'Contact and support');
      expect(root.querySelector(`a[href="${language === 'tr' ? '/preview/tr/accessibility' : '/preview/accessibility'}"]`)).toBeTruthy();
      expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).toContain(language === 'tr' ? 'incelenmemiş Türkçe taslak' : 'unreviewed local draft');
      expect(root.querySelectorAll('section h2')).toHaveLength(5);
      expect(root.querySelector('[role="status"]')?.textContent).toContain(language === 'tr' ? 'İki dilli insan onayı' : 'Bilingual human approval');
      for (const text of language === 'tr'
        ? ['herkese açık iletişim gönderim kanalı yoktur', 'soru veya ek toplamaz', 'MFA ile doğrulanmış destek personeli', 'müşteri dışa aktarımına dahil edebilir', 'personel yanıtı, e-posta teslimatı', 'yeni anahtarla yinelenen gönderim yapmayın', 'yanıt süresi taahhüdü', 'hâlâ doğrulanmamıştır']
        : ['no public contact submission channel', 'collects no question or attachment', 'MFA-authenticated support staff', 'include it in a customer export', 'not staff response, email delivery', 'do not send a duplicate with a new key', 'response-time commitment', 'still unverified']) expect(root.textContent).toContain(text);
      for (const path of language === 'tr' ? ['/preview/tr/home', '/preview/tr/help', '/preview/tr', '/account/login'] : ['/', '/preview/help', '/preview', '/account/login']) expect(root.querySelector(`a[href="${path}"]`)).toBeTruthy();
      expect(root.querySelector('form, input, textarea, img, script, iframe, a[href="/contact"], a[href="/tr/iletisim"], a[href="/account/register"], a[href^="https://"], a[href^="mailto:"]')).toBeNull();
      expect(root.querySelector('app-contact-submission button')?.textContent).toContain(language === 'tr' ? 'yerel gönderimi kontrol et' : 'Check configured local intake');
      expect(document.querySelector('link[rel="canonical"], link[hreflang]')).toBeNull();
      expect(root.querySelector(`nav a[lang="${language}"]`)?.getAttribute('aria-current')).toBe('page');
      if (language === 'tr') {
        root.querySelector<HTMLAnchorElement>('nav a[lang="en"]')!.click();
        await harness.fixture.whenStable(); harness.detectChanges();
      }
    }
    harness.routeNativeElement!.querySelector<HTMLAnchorElement>('nav a[lang="tr"]')!.click();
    await harness.fixture.whenStable(); harness.detectChanges();
    expect(document.documentElement.lang).toBe('tr');
    expect(preference).not.toHaveBeenCalled(); preference.mockRestore();
    await harness.navigateByUrl('/account/login');
    expect(document.documentElement.lang).toBe('en');
    expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).not.toContain('Türkçe');
  });


  it('renders paired local accessibility-evidence drafts by explicit path and restores English metadata on exit', async () => {
    const preference = vi.spyOn(TestBed.inject(AccountApi), 'productLanguage');
    const harness = await RouterTestingHarness.create('/preview/tr/accessibility');
    for (const language of ['tr', 'en'] as const) {
      const root = harness.routeNativeElement!;
      expect(root.querySelector('article')?.lang).toBe(language);
      expect(document.documentElement.lang).toBe(language);
      expect(document.title).toContain(language === 'tr' ? 'Türkçe taslak' : 'Accessibility target and evidence');
      expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).toContain(language === 'tr' ? 'incelenmemiş Türkçe taslak' : 'unreviewed local draft');
      expect(root.querySelectorAll('section h2')).toHaveLength(4);
      expect(root.querySelector('[role="status"]')?.textContent).toContain(language === 'tr' ? 'İki dilli insan onayı' : 'Bilingual human approval');
      for (const text of language === 'tr'
        ? ['uygunluk veya sertifikasyon iddiası değildir', 'WCAG 2.2 AA', 'uygunluğu kanıtlamaz', 'görünür çerçevesi', '320 CSS piksel', '%400', 'doğrulanmamıştır', 'test edilmiş tarayıcı/ekran okuyucu matrisi', 'özel dışa aktarım eklemeyin', 'yanıt süresi taahhüdü yoktur']
        : ['not a compliance or certification claim', 'WCAG 2.2 AA', 'does not establish conformance', 'visible outline', '320 CSS-pixel', '400%', 'remain unverified', 'No tested browser/screen-reader matrix', 'private exports', 'no public inbox or response-time commitment']) expect(root.textContent).toContain(text);
      for (const path of language === 'tr' ? ['/preview/tr/home', '/preview/tr/help', '/preview/tr/contact'] : ['/', '/preview/help', '/preview/contact']) expect(root.querySelector(`a[href="${path}"]`)).toBeTruthy();
      expect(root.querySelector('form, button, input, textarea, img, script, iframe, a[href="/accessibility"], a[href="/tr/erisilebilirlik"], a[href="/account/register"], a[href^="https://"], a[href^="mailto:"]')).toBeNull();
      expect(document.querySelector('link[rel="canonical"], link[hreflang]')).toBeNull();
      expect(root.querySelector(`nav a[lang="${language}"]`)?.getAttribute('aria-current')).toBe('page');
      if (language === 'tr') {
        root.querySelector<HTMLAnchorElement>('nav a[lang="en"]')!.click();
        await harness.fixture.whenStable(); harness.detectChanges();
      }
    }
    harness.routeNativeElement!.querySelector<HTMLAnchorElement>('nav a[lang="tr"]')!.click();
    await harness.fixture.whenStable(); harness.detectChanges();
    expect(document.documentElement.lang).toBe('tr');
    expect(preference).not.toHaveBeenCalled(); preference.mockRestore();
    await harness.navigateByUrl('/account/login');
    expect(document.documentElement.lang).toBe('en');
    expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).not.toContain('Türkçe');
  });

  it('renders paired local data-handling drafts by explicit path and restores English metadata on exit', async () => {
    const preference = vi.spyOn(TestBed.inject(AccountApi), 'productLanguage');
    const harness = await RouterTestingHarness.create('/preview/tr/data-handling');
    for (const language of ['tr', 'en'] as const) {
      const root = harness.routeNativeElement!;
      expect(root.querySelector('article')?.lang).toBe(language);
      expect(document.documentElement.lang).toBe(language);
      expect(document.title).toContain(language === 'tr' ? 'Türkçe taslak' : 'Data handling and current limits');
      expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).toContain(language === 'tr' ? 'incelenmemiş Türkçe taslak' : 'unreviewed local draft');
      expect(root.querySelectorAll('section h2')).toHaveLength(5);
      expect(root.querySelector('[role="status"]')?.textContent).toContain(language === 'tr' ? 'İki dilli insan onayı' : 'Bilingual human approval');
      for (const text of language === 'tr'
        ? ['onaylı gizlilik bildirimi veya güvenlik sertifikasyonu değildir', 'MFA', 'şifrelenmiş depolama', 'OAuth', 'sağlayıcı tarafındaki silmeyi kanıtlamaz', 'uygun kullanım ve depolama hakları', 'sıfır saklama sözü verilmez', 'alıcılarında kalır', '90 gün', '30 gün', '35 günlük', 'self servis kapatılması devre dışıdır']
        : ['not an approved privacy notice or security certification', 'MFA', 'encrypted storage', 'OAuth', 'does not prove provider-side deletion', 'appropriate use and storage rights', 'zero-retention promise', 'remain with their recipients', '90 days', '30 days', '35-day', 'Self-service organization closure remains disabled']) expect(root.textContent).toContain(text);
      for (const path of language === 'tr' ? ['/preview/tr/home', '/preview/tr/data-sources', '/preview/tr/contact'] : ['/', '/preview/data-sources', '/preview/contact']) expect(root.querySelector(`a[href="${path}"]`)).toBeTruthy();
      expect(root.querySelector('form, button, input, textarea, img, script, iframe, a[href="/data-handling"], a[href="/tr/veri-isleme"], a[href="/account/register"], a[href^="https://"], a[href^="mailto:"]')).toBeNull();
      expect(document.querySelector('link[rel="canonical"], link[hreflang]')).toBeNull();
      expect(root.querySelector(`nav a[lang="${language}"]`)?.getAttribute('aria-current')).toBe('page');
      if (language === 'tr') {
        root.querySelector<HTMLAnchorElement>('nav a[lang="en"]')!.click();
        await harness.fixture.whenStable(); harness.detectChanges();
      }
    }
    harness.routeNativeElement!.querySelector<HTMLAnchorElement>('nav a[lang="tr"]')!.click();
    await harness.fixture.whenStable(); harness.detectChanges();
    expect(document.documentElement.lang).toBe('tr');
    expect(preference).not.toHaveBeenCalled(); preference.mockRestore();
    await harness.navigateByUrl('/account/login');
    expect(document.documentElement.lang).toBe('en');
    expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).not.toContain('Türkçe');
  });

  it('renders paired local cancellation drafts by explicit path and restores English metadata on exit', async () => {
    const preference = vi.spyOn(TestBed.inject(AccountApi), 'productLanguage');
    const harness = await RouterTestingHarness.create('/preview/tr/cancellation');
    for (const language of ['tr', 'en'] as const) {
      const root = harness.routeNativeElement!;
      expect(root.querySelector('article')?.lang).toBe(language);
      expect(document.documentElement.lang).toBe(language);
      expect(document.title).toContain(language === 'tr' ? 'Türkçe taslak' : 'Cancellation and retained access');
      expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).toContain(language === 'tr' ? 'incelenmemiş Türkçe taslak' : 'unreviewed local draft');
      expect(root.querySelectorAll('section h2')).toHaveLength(4);
      expect(root.querySelector('[role="status"]')?.textContent).toContain(language === 'tr' ? 'İki dilli insan onayı' : 'Bilingual human approval');
      for (const text of language === 'tr'
        ? ['30 günlük kartsız', 'anında tahsilat', 'dönem sonu iptal', 'iptali kanıtlamaz', 'yedi takvim günü', 'otomatik orantılı iade değildir', '90 gün', '30 gün', '35 günlük', 'Self servis kapatma devre dışıdır']
        : ['30-day no-card', 'immediate charge', 'period-end cancellation', 'does not prove cancellation', 'seven calendar days', 'not an automatic prorated refund', '90 days', '30 days', '35-day', 'Self-service closure remains disabled']) expect(root.textContent).toContain(text);
      for (const path of language === 'tr' ? ['/preview/tr/home', '/preview/tr/pricing', '/preview/tr/data-handling', '/preview/tr/contact'] : ['/', '/preview/pricing', '/preview/data-handling', '/preview/contact']) expect(root.querySelector(`a[href="${path}"]`)).toBeTruthy();
      expect(root.querySelector('form, button, input, textarea, img, script, iframe, a[href="/cancellation"], a[href="/tr/iptal"], a[href="/account/register"], a[href^="https://"], a[href^="mailto:"]')).toBeNull();
      expect(document.querySelector('link[rel="canonical"], link[hreflang]')).toBeNull();
      expect(root.querySelector(`nav a[lang="${language}"]`)?.getAttribute('aria-current')).toBe('page');
      if (language === 'tr') {
        root.querySelector<HTMLAnchorElement>('nav a[lang="en"]')!.click();
        await harness.fixture.whenStable(); harness.detectChanges();
      }
    }
    harness.routeNativeElement!.querySelector<HTMLAnchorElement>('nav a[lang="tr"]')!.click();
    await harness.fixture.whenStable(); harness.detectChanges();
    expect(document.documentElement.lang).toBe('tr');
    expect(preference).not.toHaveBeenCalled(); preference.mockRestore();
    await harness.navigateByUrl('/account/login');
    expect(document.documentElement.lang).toBe('en');
    expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).not.toContain('Türkçe');
  });

  it('renders paired local privacy drafts by explicit path and restores English metadata on exit', async () => {
    const preference = vi.spyOn(TestBed.inject(AccountApi), 'productLanguage');
    const harness = await RouterTestingHarness.create('/preview/tr/privacy');
    for (const language of ['tr', 'en'] as const) {
      const root = harness.routeNativeElement!;
      expect(root.querySelector('article')?.lang).toBe(language);
      expect(document.documentElement.lang).toBe(language);
      expect(document.title).toContain(language === 'tr' ? 'Türkçe taslak' : 'Privacy and data choices');
      expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).toContain(language === 'tr' ? 'incelenmemiş Türkçe taslak' : 'unreviewed local draft');
      expect(root.querySelectorAll('section h2')).toHaveLength(6);
      expect(root.querySelector('[role="status"]')?.textContent).toContain(language === 'tr' ? 'İki dilli insan onayı' : 'Bilingual human approval');
      for (const text of language === 'tr'
        ? ['onaylı gizlilik bildirimi değildir', 'hizmet kayıtları', 'ürün edinim gözlemlerinden ayrı', 'OAuth', 'uluslararası aktarımlar', 'taslak yollar isteğe bağlı edinim analitiği toplamaz', 'on beş dakikalık', 'yetmiş beş dakika', 'Kimlik temizleme', '90 gün', '30 gün', '35 günlük', 'self servis kapatılması devre dışıdır', 'veri sorumlusu kimliğini', 'doğrulanmış hak talebi kanalı değildir']
        : ['not an approved privacy notice', 'service records', 'separate from product acquisition observations', 'OAuth', 'international transfers', 'draft routes collect no optional acquisition analytics', 'fifteen-minute', 'seventy-five minutes', 'Identity cleanup', '90 days', '30 days', '35-day', 'Self-service organization closure remains disabled', 'controller identity', 'not a verified rights-request channel']) expect(root.textContent).toContain(text);
      for (const path of language === 'tr' ? ['/preview/tr/home', '/preview/tr/data-handling', '/preview/tr/contact'] : ['/', '/preview/data-handling', '/preview/contact']) expect(root.querySelector(`a[href="${path}"]`)).toBeTruthy();
      expect(root.querySelector('form, button, input, textarea, img, script, iframe, a[href="/privacy"], a[href="/tr/gizlilik"], a[href="/account/register"], a[href^="https://"], a[href^="mailto:"]')).toBeNull();
      expect(document.querySelector('link[rel="canonical"], link[hreflang]')).toBeNull();
      expect(root.querySelector(`nav a[lang="${language}"]`)?.getAttribute('aria-current')).toBe('page');
      if (language === 'tr') {
        root.querySelector<HTMLAnchorElement>('nav a[lang="en"]')!.click();
        await harness.fixture.whenStable(); harness.detectChanges();
      }
    }
    harness.routeNativeElement!.querySelector<HTMLAnchorElement>('nav a[lang="tr"]')!.click();
    await harness.fixture.whenStable(); harness.detectChanges();
    expect(document.documentElement.lang).toBe('tr');
    expect(preference).not.toHaveBeenCalled(); preference.mockRestore();
    await harness.navigateByUrl('/account/login');
    expect(document.documentElement.lang).toBe('en');
    expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).not.toContain('Türkçe');
  });

  it('renders paired local terms drafts by explicit path and restores English metadata on exit', async () => {
    const preference = vi.spyOn(TestBed.inject(AccountApi), 'productLanguage');
    const harness = await RouterTestingHarness.create('/preview/tr/terms');
    for (const language of ['tr', 'en'] as const) {
      const root = harness.routeNativeElement!;
      expect(root.querySelector('article')?.lang).toBe(language);
      expect(document.documentElement.lang).toBe(language);
      expect(document.title).toContain(language === 'tr' ? 'Türkçe taslak' : 'Product terms and responsibilities');
      expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).toContain(language === 'tr' ? 'incelenmemiş Türkçe taslak' : 'unreviewed local draft');
      expect(root.querySelectorAll('section h2')).toHaveLength(5);
      expect(root.querySelector('[role="status"]')?.textContent).toContain(language === 'tr' ? 'İki dilli insan onayı' : 'Bilingual human approval');
      for (const text of language === 'tr'
        ? ['onaylı sözleşme veya mevcut teklif değildir', 'her aktif kuruluştan ayrılın', 'toplama izinlerine', 'satın alınabilir kredi değildir', 'Aktif güvenlik taraması açık kapsam', 'insan onayı gerektirir', 'dönüş sayfasının görüntülenmesi değil', 'anında silme komutu değildir', 'satıcı kimliği', 'yargı yetkisi', 'uygulanabilir yasal söz oluşturmaz']
        : ['not an approved contract or an available offer', 'leave every active organization', 'an owner must first transfer ownership or deliberately close', 'collection permissions', 'not money or purchasable credits', 'Active security scanning requires explicit scope', 'require human approval', 'not a return-page view', 'not an immediate deletion command', 'seller identity', 'jurisdiction', 'enforceable legal promise']) expect(root.textContent).toContain(text);
      for (const path of language === 'tr' ? ['/preview/tr/home', '/preview/tr/pricing', '/preview/tr/cancellation', '/preview/tr/privacy', '/preview/tr/contact'] : ['/', '/preview/pricing', '/preview/cancellation', '/preview/privacy', '/preview/contact']) expect(root.querySelector(`a[href="${path}"]`)).toBeTruthy();
      expect(root.querySelector('form, button, input, textarea, img, script, iframe, a[href="/terms"], a[href="/tr/kullanim-kosullari"], a[href="/account/register"], a[href^="https://"], a[href^="mailto:"]')).toBeNull();
      expect(document.querySelector('link[rel="canonical"], link[hreflang]')).toBeNull();
      expect(root.querySelector(`nav a[lang="${language}"]`)?.getAttribute('aria-current')).toBe('page');
      if (language === 'tr') {
        root.querySelector<HTMLAnchorElement>('nav a[lang="en"]')!.click();
        await harness.fixture.whenStable(); harness.detectChanges();
      }
    }
    harness.routeNativeElement!.querySelector<HTMLAnchorElement>('nav a[lang="tr"]')!.click();
    await harness.fixture.whenStable(); harness.detectChanges();
    expect(document.documentElement.lang).toBe('tr');
    expect(preference).not.toHaveBeenCalled(); preference.mockRestore();
    await harness.navigateByUrl('/account/login');
    expect(document.documentElement.lang).toBe('en');
    expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).not.toContain('Türkçe');
  });


  it('loads the lazy account and workspace development pages', async () => {
    const harness = await RouterTestingHarness.create('/account/login');
    expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Sign in');
    expect(harness.routeNativeElement?.querySelector('input[autocomplete="current-password"]')).toBeTruthy();
    expect(harness.routeNativeElement?.querySelector('a[href="/account/forgot-password"]')).toBeTruthy();
    await harness.navigateByUrl('/account/register');
    expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Create your account');
    expect(harness.routeNativeElement?.querySelector('input[autocomplete="new-password"]')).toBeTruthy();
    await harness.navigateByUrl('/account/verify');
    expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Check your email');
    await harness.navigateByUrl('/app');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain('Organization: none selected');
    expect(harness.routeNativeElement?.textContent).toContain('Sign out');
  });

  it.each(['en', 'tr'] as const)('keeps staff credentials write-only and hides controls on access denial in %s', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    const harness = await RouterTestingHarness.create('/account/provider-settings');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Sağlayıcı kimlik bilgileri — OrganicSEOOps' : 'Provider credentials — OrganicSEOOps');
    expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe(language);
    expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe(language === 'tr' ? 'Yapay zekâ sağlayıcı kimlik bilgileri' : 'AI provider credentials');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'erişimi kullanılamıyor' : 'access is unavailable');
    expect(harness.routeNativeElement?.querySelector('input[name="secret"]')).toBeNull();

    api.platformProvidersResult = { status: 200, body: {
      providers: [{ id: 9, key: 'openai', name: 'OpenAI', kind: 'openai', enabled: true }],
      accounts: [], has_more: false,
    } };
    await harness.routeDebugElement?.componentInstance.load();
    harness.fixture.detectChanges();
    const form = harness.routeNativeElement?.querySelectorAll('form')[1] as HTMLFormElement;
    const label = form.querySelector<HTMLInputElement>('input[name="label"]')!;
    const secret = form.querySelector<HTMLInputElement>('input[name="secret"]')!;
    label.value = 'Platform';
    secret.value = 'dummy-private-key';
    const component = harness.routeDebugElement!.componentInstance as ProviderSettings;
    const read = vi.spyOn(api, 'platformProviders'), write = vi.spyOn(api, 'addPlatformAccount');
    const providers = component.providers(), accounts = component.accounts();
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Provider credentials — OrganicSEOOps' : 'Sağlayıcı kimlik bilgileri — OrganicSEOOps');
    expect(component.providers()).toBe(providers); expect(component.accounts()).toBe(accounts);
    expect(secret.value).toBe('dummy-private-key'); expect(label.value).toBe('Platform');
    expect(read).not.toHaveBeenCalled(); expect(write).not.toHaveBeenCalled();
    component.productLanguage.set(language); harness.fixture.detectChanges();
    expect(harness.routeNativeElement!.querySelector('label[for="new-platform-key"]')!.textContent).toContain(language === 'tr' ? 'Sağlayıcı API anahtarı' : 'Provider API key');
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.savedPlatformSecrets).toEqual(['dummy-private-key']);
    expect(secret.value).toBe('');
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Kimlik bilgisi kaydedildi.' : 'Credential saved.');
    expect(harness.routeNativeElement?.textContent).not.toContain('dummy-private-key');
  });

  it('keeps invalid unavailable or signed-out platform settings preference and fresh production English', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const preference = vi.spyOn(api, 'productLanguage'), credential = vi.spyOn(api, 'addPlatformAccount');
    const retry = vi.spyOn(api, 'retryPlatformPaddleReceipt'), notice = vi.spyOn(api, 'retryPlatformNotice');
    const clear = vi.spyOn(api, 'clearPlatformEmailSuppression'), seller = vi.spyOn(api, 'setPlatformPaddleSeller');
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    const harness = await RouterTestingHarness.create();
    try {
      for (const mode of ['invalid', 'incompatible', 'signed-out', 'unavailable', 'production'] as const) {
        buildEnvironment.production = mode === 'production';
        if (mode === 'unavailable') preference.mockRejectedValue(new Error('private preference error'));
        else preference.mockResolvedValue(mode === 'signed-out' ? { status: 401, body: { detail: 'private preference error' } }
          : { status: 200, body: { language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: mode === 'incompatible' ? 'tr' : 'en', current_email_language: 'en' } });
        await harness.navigateByUrl('/account/provider-settings'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
        expect(TestBed.inject(Title).getTitle()).toBe('Provider credentials — OrganicSEOOps');
        expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe('AI provider credentials');
        expect(harness.routeNativeElement!.textContent).not.toContain('private preference error');
        expect(harness.routeNativeElement!.textContent).not.toContain('incelenmemiş Türkçe');
        if (mode === 'production') expect((harness.routeDebugElement!.componentInstance as ProviderSettings).productLanguage()).toBe('tr');
        await harness.navigateByUrl('/');
      }
      for (const action of [credential, retry, notice, clear, seller]) expect(action).not.toHaveBeenCalled();
    } finally { buildEnvironment.production = production; }
  });

  it.each(['en', 'tr'] as const)('labels retained operational counts and does not invent an unavailable funnel in %s', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    const harness = await RouterTestingHarness.create('/account/acquisition');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Operasyonel edinim aşamaları — OrganicSEOOps' : 'Operational acquisition milestones — OrganicSEOOps');
    expect(harness.routeNativeElement?.querySelector('[role="alert"]')?.textContent).toContain(language === 'tr' ? 'Personel MFA' : 'staff MFA');
    expect(harness.routeNativeElement?.querySelector('table')).toBeNull();
    expect(harness.routeNativeElement?.querySelector('section')?.getAttribute('lang')).toBe(language);
    expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe(language === 'tr' ? 'Operasyonel edinim aşamaları' : 'Operational acquisition milestones');

    const available = (grain: string, count: number) => ({ state: 'derivable', grain, count });
    const unavailable = { state: 'unavailable', count: null };
    api.acquisitionResult = { status: 200, body: {
      dictionary_version: 'acquisition-v1', basis: 'current_retained_operational_records', funnel_rates_available: false,
      milestones: { public_page_view: unavailable, public_cta_selected: unavailable,
        registration_succeeded: available('user', 2), email_verified: available('user', 1),
        trial_activated: available('organization', 1), first_import_succeeded: available('organization', 0),
        first_audit_succeeded: available('organization', 1), first_action_accepted: available('organization', 3),
        checkout_initiated: available('checkout_attempt', 4), paid_activation_confirmed: available('organization', 2) },
    } };
    await harness.routeDebugElement?.componentInstance.load();
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'halen saklanan kayıtlardan' : 'currently retained records');
    expect(harness.routeNativeElement?.textContent).toContain('2 (user)');
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'Kullanılamıyor — kabul edilmiş kaynak veya rıza sözleşmesi yok' : 'Unavailable — no accepted source or consent contract');
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'Dönüşüm oranları' : 'No conversion rates');
    expect(harness.routeNativeElement?.querySelectorAll('tbody tr').length).toBe(10);
    const acceptance = Array.from(harness.routeNativeElement!.querySelectorAll('tbody tr')).find((row) => row.textContent!.includes(language === 'tr' ? 'saklanan ilk insan tarafından kabul' : 'human-accepted'))!;
    expect(acceptance.textContent).toContain('3 (organization)');
    for (const explanation of (language === 'tr' ? ['her kuruluşu bir kez', 'geçmişinin silinmesi sayıları azaltabilir', 'sitede uygulama veya SEO iyileşmesi değildir'] : ['each organization once', 'history deletion can reduce counts', 'not site implementation or SEO improvement']))
      expect(harness.routeNativeElement?.textContent).toContain(explanation);
    const checkout = Array.from(harness.routeNativeElement!.querySelectorAll('tbody tr')).find((row) => row.textContent!.includes(language === 'tr' ? 'sahip veya tarayıcı' : 'owner/browser'))!;
    expect(checkout.textContent).toContain('4 (checkout_attempt)');
    for (const explanation of (language === 'tr' ? ['onaylanan her girişimi bir kez', 'eski girişimler alındı kaydı değildir', 'müşteri içeriğinin silinmesinden sonra korunur', 'sağlayıcı sayfasının yüklenmesini'] : ['each prospectively acknowledged attempt once', 'old attempts are not receipts',
      'receipts survive customer-content erasure', 'does not prove provider-page loading'])) expect(harness.routeNativeElement?.textContent).toContain(explanation);
    const paid = Array.from(harness.routeNativeElement!.querySelectorAll('tbody tr')).find((row) => row.textContent!.includes(language === 'tr' ? 'aktif ücretli erişim sunucu gözlemi' : 'paid server observation'))!;
    expect(paid.textContent).toContain('2 (organization)');
    for (const explanation of (language === 'tr' ? ['sağlayıcı etkinleştirme zamanı veya mevcut erişim değil', 'yeniden ödeme başka bir kuruluş eklemez', 'tüm geçmişi kapsayan bir dönüşüm oranı değildir'] : ['not provider activation time', 'recheckout do not add another organization', 'not a lifetime conversion rate']))
      expect(harness.routeNativeElement?.textContent).toContain(explanation);
    const component = harness.routeDebugElement!.componentInstance as Acquisition;
    const retained = component.milestones(); component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Operational acquisition milestones — OrganicSEOOps' : 'Operasyonel edinim aşamaları — OrganicSEOOps');
    expect(component.milestones()).toBe(retained); expect(harness.routeNativeElement?.textContent).toContain('4 (checkout_attempt)');
    expect(component.publicRows()).toEqual([]); expect(component.cohort()).toBeNull();
    component.productLanguage.set(language); harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.querySelector('span[lang="en"]')?.textContent).toBe('user');
    const milestones = api.acquisitionResult.body['milestones'] as Record<string, unknown>;
    for (const [id, row] of [
      ['registration_succeeded', { state: 'derivable', grain: ['user'], count: 2 }],
      ['registration_succeeded', available('organization', 2)], ['email_verified', available('organization', 1)],
      ['trial_activated', available('user', 1)], ['first_import_succeeded', available('user', 0)],
      ['public_page_view', available('user', 0)], ['public_cta_selected', available('organization', 0)],
    ] as [string, unknown][]) {
      const original = milestones[id]; milestones[id] = row;
      await harness.routeDebugElement?.componentInstance.load(); harness.fixture.detectChanges();
      expect(harness.routeNativeElement?.querySelector('table'), id).toBeNull();
      expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'aşamalar kullanılamıyor' : 'Milestones are unavailable');
      milestones[id] = original;
    }
    await harness.routeDebugElement?.componentInstance.load(); harness.fixture.detectChanges();
    const audit = Array.from(harness.routeNativeElement!.querySelectorAll('tbody tr')).find(row => row.textContent!.includes(language === 'tr' ? 'öznel sınırlı denetim' : 'subjective bounded-audit'))!;
    expect(audit.textContent).toContain('1 (organization)');
    for (const explanation of (language === 'tr' ? ['açık müşteri onayıyla', 'Eski veya boş takip bilinmiyor', 'Yalnızca onay, operasyonel tamamlanma ve inceleme', 'Müşteri geçmişinin silinmesi bu saklanan sayıyı azaltabilir'] : ['explicit customer acknowledgment', 'Old/null tracking remains unknown', 'Approval, operational completion and inspection alone', 'Customer-history erasure can reduce']))
      expect(harness.routeNativeElement?.textContent).toContain(explanation);
    milestones['first_audit_succeeded'] = available('user', 1);
    await harness.routeDebugElement?.componentInstance.load(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.querySelector('table')).toBeNull();
    milestones['first_audit_succeeded'] = available('organization', 1);
    milestones['paid_activation_confirmed'] = available('user', 2);
    await harness.routeDebugElement?.componentInstance.load(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.querySelector('table')).toBeNull();
    milestones['paid_activation_confirmed'] = available('organization', 2);
    milestones['first_action_accepted'] = available('user', 3);
    await harness.routeDebugElement?.componentInstance.load(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.querySelector('table')).toBeNull();
    expect(harness.routeNativeElement?.querySelector('[role="alert"]')).not.toBeNull();
    milestones['first_action_accepted'] = available('organization', 3);
    milestones['checkout_initiated'] = available('organization', 4);
    await harness.routeDebugElement?.componentInstance.load(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.querySelector('table')).toBeNull();
  });

  it('keeps invalid unavailable or signed-out acquisition preference and fresh production English', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const preference = vi.spyOn(api, 'productLanguage');
    const publicCounts = vi.spyOn(api, 'publicAnalyticsObservations'), cohorts = vi.spyOn(api, 'trialPaidCohort');
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    const harness = await RouterTestingHarness.create();
    try {
      for (const mode of ['invalid', 'incompatible', 'signed-out', 'unavailable', 'production'] as const) {
        buildEnvironment.production = mode === 'production';
        if (mode === 'unavailable') preference.mockRejectedValue(new Error('private preference error'));
        else preference.mockResolvedValue(mode === 'signed-out' ? { status: 401, body: { detail: 'private preference error' } }
          : { status: 200, body: { language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: mode === 'incompatible' ? 'tr' : 'en', current_email_language: 'en' } });
        await harness.navigateByUrl('/account/acquisition'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
        expect(TestBed.inject(Title).getTitle()).toBe('Operational acquisition milestones — OrganicSEOOps');
        expect(harness.routeNativeElement?.querySelector('section')?.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Operational acquisition milestones');
        expect(harness.routeNativeElement?.textContent).not.toContain('private preference error');
        if (mode === 'production') expect((harness.routeDebugElement!.componentInstance as Acquisition).productLanguage()).toBe('tr');
        await harness.navigateByUrl('/');
      }
      expect(publicCounts).not.toHaveBeenCalled(); expect(cohorts).not.toHaveBeenCalled();
    } finally { buildEnvironment.production = production; preference.mockRestore(); }
  });

  it.each(['en', 'tr'] as const)('lets an owner map only current query evidence as a human decision, with no inferred page join (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    const onboarding = structuredClone(api.onboardingResult.body);
    (onboarding['configuration'] as Record<string, unknown>)['target_country'] = 'Turkey';
    (onboarding['configuration'] as Record<string, unknown>)['target_languages'] = ['en'];
    api.onboardingResult = { status: 200, body: onboarding };
    api.findingRows = [{ id: 112, subject: 'owned query', detector: 'web_position_4_to_20_candidate',
      source_current: true, source_metric_id: 22, evidence: { dimension: 'query' } },
    { id: 113, subject: 'page-only row', detector: 'web_high_impressions_low_ctr_candidate',
      source_current: true, source_metric_id: 23, evidence: { dimension: 'page' } }];
    const harness = await RouterTestingHarness.create('/app/intent/7/9');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Kaynakları dikkate alan niyet eşlemesi — OrganicSEOOps' : 'Source-aware intent mapping — OrganicSEOOps');
    const element = harness.routeNativeElement!;
    const component = harness.routeDebugElement!.componentInstance;
    expect(element.querySelector('[aria-labelledby="intent-title"]')?.getAttribute('lang')).toBe(language);
    expect(element.querySelector('h1')?.textContent).toBe(language === 'tr' ? 'Niyet ve tercih edilen sayfaları incele' : 'Review intent and preferred pages');
    expect(element.textContent).toContain(language === 'tr' ? 'bir sorguda hangi sayfanın göründüğünü göstermez' : 'do not show which page appeared for a query');
    expect(element.textContent).toContain(language === 'tr' ? 'sıralama veya dönüşüm gözlemi değildir' : 'not a ranking or conversion observation');
    expect(element.querySelector('ul')?.getAttribute('aria-label')).toBe(language === 'tr' ? 'İnsan tarafından incelenmiş niyet eşlemesi' : 'Human-reviewed intent mapping');
    expect(element.querySelector('label[for="intent-language"]')?.textContent).toBe(language === 'tr' ? 'Proje SEO dili' : 'Project SEO language');
    expect(element.querySelector('#intent-language option')?.textContent).toBe('en');
    expect(element.querySelector('#intent-language option')?.getAttribute('lang')).toBe('en');
    expect(element.querySelector('#intent-kind option[value="informational"]')?.getAttribute('lang')).toBe('en');
    expect(Array.from(element.querySelectorAll('[lang=""]')).some(node => node.textContent === 'owned query')).toBe(true);
    expect(Array.from(element.querySelectorAll('[lang="en"]')).some(node => node.textContent === 'web_position_4_to_20_candidate')).toBe(true);
    expect(element.querySelectorAll('input[type="checkbox"]').length).toBe(1);
    const checkbox = element.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
    checkbox.click();
    const form = element.querySelector('form')!;
    form.querySelector<HTMLInputElement>('input[name="label"]')!.value = 'Human grouped query';
    form.querySelector<HTMLTextAreaElement>('textarea[name="reason"]')!.value = 'Review source scope before page decisions.';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.savedIntent.length).toBe(1);
    expect(api.savedIntent[0]['source_finding_ids']).toEqual([112]);
    expect(api.savedIntent[0]['manual_topics']).toEqual([]);
    expect(api.savedIntent[0]['page_kind']).toBe('unmapped');
    expect(api.savedIntent[0]['proposed_action']).toBe('unselected');
    expect(element.textContent).toContain(language === 'tr' ? 'insan tarafından seçilmiş; ortak kaynak kanıtı yok' : 'human-selected; no joint source evidence');
    expect(element.textContent).toContain(language === 'tr' ? 'İnsan eşlemesi kaydedildi' : 'Human mapping saved');
    expect(element.textContent).toContain(language === 'tr' ? 'onaylanmamış veya uygulanmamış' : 'not approved or executed');
    expect(api.savedIntent[0]['language']).toBe('en'); expect(api.savedIntent[0]['intent']).toBe('unknown');
    for (const text of ['Human grouped query', 'Review source scope before page decisions.']) {
      expect(Array.from(element.querySelectorAll('[lang=""]')).some(node => node.textContent === text)).toBe(true);
    }
    await component.history(component.clusters()[0].cluster_id); harness.fixture.detectChanges();
    expect(element.querySelector('#history-title')?.textContent).toBe(language === 'tr' ? 'Önceki incelenmiş revizyonlar' : 'Previous reviewed revisions');
    expect(element.querySelector('#history-title + ol [lang="en"]')?.textContent).toBe('unknown · unmapped');
    component.edit(component.clusters()[0]); harness.fixture.detectChanges();
    expect(element.querySelector('#intent-form-title')?.textContent).toBe(language === 'tr' ? 'Seçili eşlemeyi düzelt' : 'Correct the selected mapping');
    expect(element.textContent).toContain(language === 'tr' ? 'özgün revizyonlar incelenebilir' : 'original revisions remain inspectable');
    const correctionForm = element.querySelector<HTMLFormElement>('form')!;
    const correctionReason = correctionForm.querySelector<HTMLTextAreaElement>('#intent-reason')!;
    correctionReason.value = 'Unsaved customer correction';
    const reads = vi.spyOn(api, 'intentClusters');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Source-aware intent mapping — OrganicSEOOps' : 'Kaynakları dikkate alan niyet eşlemesi — OrganicSEOOps');
    expect(correctionReason.value).toBe('Unsaved customer correction'); expect(component.selected()).toEqual([112]);
    expect(component.editing().revision).toBe(1); expect(component.historyRows()).toHaveLength(1); expect(reads).not.toHaveBeenCalled();
    component.productLanguage.set(language); reads.mockRestore();
    const proposal = correctionForm.querySelector<HTMLSelectElement>('#intent-action')!;
    const actionReason = correctionForm.querySelector<HTMLTextAreaElement>('#intent-action-reason')!;
    expect(actionReason.required).toBe(false);
    proposal.value = 'refresh'; proposal.dispatchEvent(new Event('change')); harness.fixture.detectChanges();
    expect(actionReason.required).toBe(true); expect(correctionForm.checkValidity()).toBe(false);
    correctionForm.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.savedIntent).toHaveLength(1); expect(correctionReason.value).toBe('Unsaved customer correction');
    actionReason.value = 'Human reason for the optional proposal.';
    expect(correctionForm.checkValidity()).toBe(true);
    component.cancelEdit(); harness.fixture.detectChanges(); expect(actionReason.required).toBe(false);
    await harness.navigateByUrl('/app/intent/8/9');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(element.querySelector('form')).toBeNull();
    expect(element.textContent).toContain(language === 'tr' ? 'Bu proje veya oturum için niyet kanıtları kullanılamıyor' : 'unavailable for this project or session');
    expect(element.textContent).not.toContain('Human grouped query'); expect(component.historyRows()).toEqual([]);
    if (language === 'tr') {
      const preference = vi.spyOn(api, 'productLanguage').mockResolvedValue({ status: 200,
        body: { language: ['tr'], current_ui_language: 'en', current_email_language: 'en' } });
      await harness.navigateByUrl('/app'); await harness.navigateByUrl('/app/intent/7/9');
      await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(TestBed.inject(Title).getTitle()).toBe('Source-aware intent mapping — OrganicSEOOps');
      expect(harness.routeNativeElement?.querySelector('[aria-labelledby="intent-title"]')?.getAttribute('lang')).toBe('en');
      preference.mockRejectedValue(new Error('private preference transport text'));
      await harness.navigateByUrl('/app'); await harness.navigateByUrl('/app/intent/7/9');
      await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Review intent and preferred pages');
      expect(TestBed.inject(Title).getTitle()).toBe('Source-aware intent mapping — OrganicSEOOps');
      expect(harness.routeNativeElement?.textContent).not.toContain('private preference transport text');
      preference.mockRestore();
      const buildEnvironment = environment as { production: boolean }; const production = buildEnvironment.production;
      try {
        buildEnvironment.production = true;
        await harness.navigateByUrl('/app'); await harness.navigateByUrl('/app/intent/7/9');
        await harness.fixture.whenStable(); harness.fixture.detectChanges();
        expect(harness.routeDebugElement!.componentInstance.productLanguage()).toBe('tr');
        expect(TestBed.inject(Title).getTitle()).toBe('Source-aware intent mapping — OrganicSEOOps');
        expect(harness.routeNativeElement?.querySelector('[aria-labelledby="intent-title"]')?.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Review intent and preferred pages');
        expect(harness.routeNativeElement?.textContent).not.toContain('iki dilli onay bekleniyor');
      } finally { buildEnvironment.production = production; }
    }
    await harness.navigateByUrl('/'); harness.fixture.detectChanges();
    const nextTitle = TestBed.inject(Title).getTitle();
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(nextTitle);
  });

  it.each(['en', 'tr'] as const)('labels manually configured seed topics as unmeasured rather than search queries (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    const onboarding = structuredClone(api.onboardingResult.body);
    const config = onboarding['configuration'] as Record<string, unknown>;
    config['target_country'] = 'Turkey';
    config['target_languages'] = ['en'];
    config['seed_topics'] = ['reviewed airport services'];
    api.onboardingResult = { status: 200, body: onboarding };
    const harness = await RouterTestingHarness.create('/app/intent/7/9');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const element = harness.routeNativeElement!;
    expect(element.textContent).toContain(language === 'tr' ? 'ölçülmüş arama sorguları değildir' : 'not measured search queries');
    element.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click();
    const form = element.querySelector('form')!;
    form.querySelector<HTMLInputElement>('input[name="label"]')!.value = 'Service discovery';
    form.querySelector<HTMLTextAreaElement>('textarea[name="reason"]')!.value = 'Human seed topic only, no observed search demand.';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.savedIntent[0]['source_finding_ids']).toEqual([]);
    expect(api.savedIntent[0]['manual_topics']).toEqual(['reviewed airport services']);
    expect(element.textContent).toContain(language === 'tr' ? 'arama gözlemi yok' : 'no search observations');
  });

  it('rejects array intent mapping roles and source kinds across current rows history and save responses', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const original = structuredClone(api.onboardingResult);
    const project = original.body['project'] as Record<string, unknown>;
    const config = original.body['configuration'] as Record<string, unknown>;
    config['target_country'] = 'Turkey'; config['target_languages'] = ['en']; config['seed_topics'] = ['reviewed services'];
    api.onboardingResult = original;
    const harness = await RouterTestingHarness.create('/app/intent/7/9'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    harness.fixture.detectChanges();
    const form = harness.routeNativeElement!.querySelector('form')!;
    component.toggleTopic('reviewed services');
    form.querySelector<HTMLInputElement>('input[name="label"]')!.value = 'Human seed mapping';
    form.querySelector<HTMLTextAreaElement>('textarea[name="reason"]')!.value = 'Manual topic without search observations.';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    expect(api.savedIntent).toHaveLength(1); expect(component.clusters()).toHaveLength(1);
    const row = structuredClone(api.intentRows[0]);
    for (const role of ['owner', 'admin', 'member', 'viewer']) {
      api.onboardingResult = { ...original, body: { ...original.body, project: { ...project, role: [role] } } };
      await component.load(); expect(component.canManage()).toBe(false); expect(component.clusters()).toEqual([]); expect(component.error()).not.toBe('');
      api.onboardingResult = { ...original, body: { ...original.body, project: { ...project, role } } };
      await component.load(); expect(component.error()).toBe(''); expect(component.clusters()).toHaveLength(1);
      expect(component.canManage()).toBe(role === 'owner' || role === 'admin');
    }
    api.onboardingResult = original;
    const save = vi.spyOn(api, 'saveIntentCluster');
    for (const kind of ['manual_seed_no_search_observation', 'csv_query_candidate_not_joined_to_page']) {
      api.intentRows = [{ ...row, source_kind: [kind] }];
      await component.load(); expect(component.clusters()).toEqual([]); expect(component.error()).not.toBe('');
      await component.history(row['cluster_id']); expect(component.historyRows()).toEqual([]);
      api.intentRows = [{ ...row, source_kind: kind }]; await component.load();
      expect(component.clusters()).toHaveLength(1);
      await component.history(row['cluster_id']); expect(component.historyRows()).toHaveLength(1);
      save.mockResolvedValueOnce({ status: 201, body: { project_id: 9, cluster: { ...row, source_kind: [kind] } } });
      harness.fixture.detectChanges(); component.toggleTopic('reviewed services');
      const currentForm = harness.routeNativeElement!.querySelector('form')!;
      currentForm.querySelector<HTMLInputElement>('input[name="label"]')!.value = 'Deliberate new human mapping';
      currentForm.querySelector<HTMLTextAreaElement>('textarea[name="reason"]')!.value = 'Manual topic without search observations.';
      currentForm.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
      await harness.fixture.whenStable();
      expect(component.message()).toContain('Mapping outcome is unknown'); expect(component.selectedTopics()).toEqual(['reviewed services']);
      component.cancelEdit();
    }
    expect(save.mock.calls).toHaveLength(2); expect(api.savedIntent).toHaveLength(1); save.mockRestore();
  });

  it.each(['en', 'tr'] as const)('separates an owner action proposal from manual approval and any website change (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    api.intentRows = [{ review_id: 91, label: 'Human mapping', source_current: true, proposed_action: 'refresh' }];
    api.teamResult = { status: 200, body: { members: [{ id: 1, user_id: 7, email: 'owner@example.invalid',
      role: 'owner', project_ids: [] }], invitations: [], events: [] } };
    const harness = await RouterTestingHarness.create('/app/actions/7/9');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'İnsan SEO eylem geçmişi — OrganicSEOOps' : 'Human SEO action history — OrganicSEOOps');
    const element = harness.routeNativeElement!;
    expect(element.textContent).toContain(language === 'tr' ? 'Bu kontrollerin hiçbiri web sitesini değiştirmez' : 'None of these controls changes a website');
    expect(element.querySelector('[aria-labelledby="actions-title"]')?.getAttribute('lang')).toBe(language);
    expect(element.querySelector('h1')?.textContent).toBe(language === 'tr' ? 'Atanmış SEO eylemleri ve elle tutulan değişiklik geçmişi' : 'Assigned SEO actions and manual change history');
    expect(element.querySelector('ul')?.getAttribute('aria-label')).toBe(language === 'tr' ? 'Proje insan eylemi durumu' : 'Project human action state');
    expect(element.querySelector('#action-source option')?.getAttribute('lang')).toBe('');
    expect(element.querySelector('#action-assignee option')?.getAttribute('lang')).toBe('');
    expect(element.querySelector('#action-kind option')?.getAttribute('lang')).toBe('en');
    const form = element.querySelectorAll('form')[0] as HTMLFormElement;
    form.querySelector<HTMLTextAreaElement>('textarea[name="acceptance_criteria"]')!.value = 'Human to check page copy.';
    form.querySelector<HTMLTextAreaElement>('textarea[name="reason"]')!.value = 'Source-limited proposal only.';
    const component = harness.routeDebugElement!.componentInstance;
    const reads = vi.spyOn(api, 'projectActions');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Human SEO action history — OrganicSEOOps' : 'İnsan SEO eylem geçmişi — OrganicSEOOps');
    expect(form.querySelector<HTMLTextAreaElement>('textarea[name="reason"]')!.value).toBe('Source-limited proposal only.');
    expect(reads).not.toHaveBeenCalled(); reads.mockRestore(); component.productLanguage.set(language);
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.savedActions[0]['state']).toBe('proposed');
    expect(api.savedActions[0]['source_type']).toBe('intent');
    expect(api.savedActions[0]['action_kind']).toBe('refresh');
    expect(element.textContent).toContain(language === 'tr' ? 'web sitesinde değişiklik yapılmadı' : 'no website change was made');
    for (const text of ['Human to check page copy.', 'Source-limited proposal only.']) {
      expect(Array.from(element.querySelectorAll('[lang=""]')).some(node => node.textContent === text)).toBe(true);
    }
    expect(element.querySelector('li h2 [lang="en"]')?.textContent).toBe('refresh · proposed');
    const transition = element.querySelector('li form') as HTMLFormElement;
    transition.querySelector<HTMLInputElement>('input[name="reason"]')!.value = 'Owner accepts manual work.';
    transition.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.savedActions[1]['state']).toBe('accepted');
    expect(api.savedActions[1]['expected_revision']).toBe(1);
    expect(element.textContent).toContain('accepted');
    await harness.navigateByUrl('/app/actions/8/9');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(element.querySelector('form')).toBeNull();
    expect(element.textContent).toContain(language === 'tr' ? 'Bu proje veya oturum için eylem kanıtları kullanılamıyor' : 'unavailable for this project or session');
    if (language === 'tr') {
      const preference = vi.spyOn(api, 'productLanguage').mockResolvedValue({ status: 200,
        body: { language: 'tr', current_ui_language: 'tr', current_email_language: 'en' } });
      await harness.navigateByUrl('/app'); await harness.navigateByUrl('/app/actions/7/9');
      await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(TestBed.inject(Title).getTitle()).toBe('Human SEO action history — OrganicSEOOps');
      expect(harness.routeNativeElement?.querySelector('[aria-labelledby="actions-title"]')?.getAttribute('lang')).toBe('en');
      preference.mockRejectedValue(new Error('private preference transport text'));
      await harness.navigateByUrl('/app'); await harness.navigateByUrl('/app/actions/7/9');
      await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Assigned SEO actions and manual change history');
      expect(TestBed.inject(Title).getTitle()).toBe('Human SEO action history — OrganicSEOOps');
      expect(harness.routeNativeElement?.textContent).not.toContain('private preference transport text');
      preference.mockRestore();
      const buildEnvironment = environment as { production: boolean }; const production = buildEnvironment.production;
      try {
        buildEnvironment.production = true;
        await harness.navigateByUrl('/app'); await harness.navigateByUrl('/app/actions/7/9');
        await harness.fixture.whenStable(); harness.fixture.detectChanges();
        expect(harness.routeDebugElement!.componentInstance.productLanguage()).toBe('tr');
        expect(TestBed.inject(Title).getTitle()).toBe('Human SEO action history — OrganicSEOOps');
        expect(harness.routeNativeElement?.querySelector('[aria-labelledby="actions-title"]')?.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Assigned SEO actions and manual change history');
        expect(harness.routeNativeElement?.textContent).not.toContain('iki dilli onay bekleniyor');
      } finally { buildEnvironment.production = production; }
    }
    await harness.navigateByUrl('/'); harness.fixture.detectChanges();
    const nextTitle = TestBed.inject(Title).getTitle();
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(nextTitle);
  });

  it('rejects array action approval and assignee roles including fresh usefulness preflight', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.actionRows = [api.auditActionRow];
    const original = structuredClone(api.onboardingResult);
    const project = original.body['project'] as Record<string, unknown>;
    const member = { user_id: 7, email: 'owner@example.invalid', role: 'owner', project_ids: [] };
    api.teamResult = { status: 200, body: { members: [member] } };
    const harness = await RouterTestingHarness.create('/app/actions/7/9'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    expect(component.canApprove()).toBe(true); expect(component.assignees()).toHaveLength(1);
    for (const role of ['owner', 'admin', 'member', 'viewer']) {
      api.onboardingResult = { ...original, body: { ...original.body, project: { ...project, role: [role] } } };
      await component.load();
      expect(component.canApprove()).toBe(false); expect(component.actions()).toEqual([]); expect(component.error()).not.toBe('');
      api.onboardingResult = { ...original, body: { ...original.body, project: { ...project, role } } };
      await component.load(); expect(component.error()).toBe(''); expect(component.canApprove()).toBe(role === 'owner' || role === 'admin');
    }
    api.onboardingResult = original;
    for (const role of ['owner', 'admin', 'member']) {
      api.teamResult.body['members'] = [{ ...member, role: [role] }]; await component.load();
      expect(component.assignees()).toEqual([]);
      api.teamResult.body['members'] = [{ ...member, role }]; await component.load(); expect(component.assignees()).toHaveLength(1);
    }
    for (const role of ['owner', 'admin']) {
      api.onboardingResult = original; await component.load();
      api.onboardingResult = { ...original, body: { ...original.body, project: { ...project, role: [role] } } };
      const reads = api.usefulnessReads.length;
      await component.prepareUsefulness(component.actions()[0]);
      expect(component.usefulnessChallenge()).toBeNull(); expect(api.usefulnessReads).toHaveLength(reads);
    }
    expect(api.savedActions).toEqual([]); expect(api.usefulnessPosts).toEqual([]);
  });

  it.each(['en', 'tr'] as const)('allows only the currently assigned member to advance manual work, not approve (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    const onboarding = structuredClone(api.onboardingResult.body);
    (onboarding['project'] as Record<string, unknown>)['role'] = 'member';
    api.onboardingResult = { status: 200, body: onboarding };
    api.teamResult = { status: 403, body: {} };
    api.actionRows = [{ action_id: 'a64070a5-91a1-4198-9556-651ab00c11bc', revision: 2,
      state: 'accepted', action_kind: 'refresh', source_type: 'intent', source_id: 91, source_current: true,
      affected_urls: ['https://example.invalid/page'], assignee_id: 7,
      acceptance_criteria: 'Record the manual change.', reason: 'Owner approved this action.',
      change_summary: '', verification_note: '', outcome_note: '', implemented_at: null,
      verified_at: null, outcome_reviewed_at: null, execution: 'human_only_no_website_change' }];
    const harness = await RouterTestingHarness.create('/app/actions/7/9');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const element = harness.routeNativeElement!;
    expect(element.querySelector('#propose-title')).toBeNull();
    expect(element.querySelectorAll('li form').length).toBe(1);
    expect(element.querySelector('li form')?.textContent).toContain('in_progress');
    expect(element.querySelector('li form')?.textContent).not.toContain('verified');
    expect(element.querySelector('li form option')?.getAttribute('lang')).toBe('en');
    expect(element.querySelector('li form label')?.textContent).toBe(language === 'tr' ? 'Sonraki insan eylemi durumu' : 'Next human state');
    const form = element.querySelector('li form') as HTMLFormElement;
    form.querySelector<HTMLInputElement>('input[name="reason"]')!.value = 'Assigned member starts manual work.';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.savedActions[0]['state']).toBe('in_progress');
    expect(api.savedActions[0]['assignee_id']).toBe(7);
  });

  it.each(['en', 'tr'] as const)('records only comparable complete page exports and labels zero versus unknown outcomes (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    const id = 'a64070a5-91a1-4198-9556-651ab00c11bc';
    api.actionRows = [{ action_id: id, revision: 4, state: 'implemented', action_kind: 'refresh',
      source_type: 'intent', source_id: 91, source_current: true,
      affected_urls: ['https://onboarding.example/landing'], assignee_id: 7,
      acceptance_criteria: 'Log the manual change.', reason: 'Owner approved it.',
      change_summary: 'Synthetic edit only.', verification_note: '', outcome_note: '',
      implemented_at: '2026-09-10T12:00:00Z', verified_at: null, outcome_reviewed_at: null,
      execution: 'human_only_no_website_change' }];
    api.indexationCrawlChoices = [{ id: 41, completed_at: '2026-09-01T12:00:00Z' },
      { id: 42, completed_at: '2026-09-27T12:00:00Z' }];
    api.sourcesHandler = async (_org, projectId) => ({ status: 200, body: { project_id: projectId,
      sources: [{ id: 5, provider: 'google_search_console', property: 'https://onboarding.example',
        state: 'active', scope_current: true, csv_import_supported: true }], has_more: false } });
    api.sourceImportHistoryHandler = async (_org, projectId, connectionId) => ({ status: 200, body: {
      project_id: projectId, connection_id: connectionId, imports: [
        { id: 10, status: 'succeeded', coverage_state: 'complete', row_errors: 0,
          observation_dimensions: ['page'], date_start: '2026-08-01', date_end: '2026-08-07',
          created_at: '2026-08-08T00:00:00Z' },
        { id: 11, status: 'succeeded', coverage_state: 'complete', row_errors: 0,
          observation_dimensions: ['page'], date_start: '2026-09-15', date_end: '2026-09-21',
          created_at: '2026-09-25T00:00:00Z' },
        { id: 12, status: 'partially_succeeded', coverage_state: 'partial', row_errors: 1,
          observation_dimensions: ['query'], date_start: '2026-09-15', date_end: '2026-09-21',
          created_at: '2026-09-25T00:00:00Z' },
      ] } });
    const harness = await RouterTestingHarness.create(`/app/outcomes/7/9/${id}`);
    await harness.fixture.whenStable();
    await harness.routeDebugElement?.componentInstance.load();
    harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Kaynakla sınırlı eylem sonuçları — OrganicSEOOps' : 'Source-limited action outcomes — OrganicSEOOps');
    const element = harness.routeNativeElement!;
    expect(element.textContent).toContain(language === 'tr' ? 'Bu eylem için karşılaştırılabilir önce/sonra kaynak anlık görüntüsü kaydedilmemiş' : 'No comparable before/after source snapshot');
    const component = harness.routeDebugElement!.componentInstance;
    expect(element.querySelector('[aria-labelledby="outcome-title"]')?.getAttribute('lang')).toBe(language);
    expect(element.querySelector('h1')?.textContent).toBe(language === 'tr' ? 'Kaynakla sınırlı eylem karşılaştırması' : 'Source-limited action comparison');
    expect(element.textContent).toContain(language === 'tr' ? 'Dışa aktarım eksikleri bilinmez; sıfır değildir' : 'Export omissions are unknown, not zero');
    expect(element.textContent).toContain(language === 'tr' ? 'Eksik veya başarısız' : 'missing or failed');
    expect(element.querySelector('#outcome-source option[value="5"]')?.getAttribute('lang')).toBe('');
    const source = element.querySelector<HTMLSelectElement>('#outcome-source')!;
    source.value = '5'; source.dispatchEvent(new Event('change'));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(element.querySelectorAll('#before-import option').length).toBe(2);
    const form = element.querySelector('#before-import')?.closest('form') as HTMLFormElement;
    form.querySelector<HTMLSelectElement>('#after-import')!.value = '11';
    const reads = vi.spyOn(api, 'sourceImportHistory');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Source-limited action outcomes — OrganicSEOOps' : 'Kaynakla sınırlı eylem sonuçları — OrganicSEOOps');
    expect(form.querySelector<HTMLSelectElement>('#after-import')!.value).toBe('11');
    expect(component.selectedSource()).toBe(5); expect(component.imports()).toHaveLength(2); expect(reads).not.toHaveBeenCalled();
    component.productLanguage.set(language); reads.mockRestore();
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.recordedOutcomeInputs).toEqual([{ connectionId: 5, before: 10, after: 11 }]);
    expect(element.textContent).toContain(language === 'tr' ? 'sıfır başlangıç değerinin göreli yüzdesi yoktur' : 'zero baseline has no relative percentage');
    expect(element.textContent).toContain(language === 'tr' ? 'sıfırdan tanımsız' : 'undefined from zero');
    expect(element.textContent).toContain(language === 'tr' ? 'Dönüşümler ve gelir: kullanılamıyor' : 'Conversions and revenue: unavailable');
    expect(element.querySelector('caption')?.textContent).toBe(language === 'tr' ? 'Gözlenen web sayfası ölçümleri; sıfır başlangıç değerinin göreli yüzdesi yoktur' : 'Observed web page metrics; zero baseline has no relative percentage');
    expect(element.querySelector('tbody tr th')?.textContent).toBe(language === 'tr' ? 'tıklamalar' : 'clicks');
    expect(element.querySelector('tbody tr td')?.textContent).toBe('0');
    expect(Array.from(element.querySelectorAll('[lang="en"]')).some(node => node.textContent === 'uploaded_file_rows_complete_provider_top_rows_unknown')).toBe(true);
    expect(Array.from(element.querySelectorAll('[lang=""]')).some(node => node.textContent === 'https://onboarding.example/landing')).toBe(true);
    const missingMetric = structuredClone(component.outcomes());
    missingMetric[0].report.search_metrics.ctr = { ...missingMetric[0].report.search_metrics.ctr, previous: null };
    component.outcomes.set(missingMetric); harness.fixture.detectChanges();
    expect(element.querySelectorAll('tbody tr')[2].querySelector('td')?.textContent).toBe(language === 'tr' ? 'bilinmiyor' : 'unknown');
    const technicalForm = element.querySelector('#before-crawl')?.closest('form') as HTMLFormElement;
    technicalForm.querySelector<HTMLSelectElement>('#after-crawl')!.value = '42';
    technicalForm.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.recordedTechnicalInputs).toEqual([{ before: 41, after: 42 }]);
    expect(element.textContent).toContain(language === 'tr' ? 'Otomatik teknik doğrulama iddiası yok' : 'No automatic technical verification claim');
    for (const text of ['Before title', 'After title']) {
      expect(Array.from(element.querySelectorAll('[lang=""]')).some(node => node.textContent === text)).toBe(true);
    }
    expect(element.querySelector('article [lang="en"]')?.textContent).toBe('observed_http_page_changes_not_fix_proof');
    const missingPage = structuredClone(component.technical()); missingPage[0].report.urls[0].previous = null;
    component.technical.set(missingPage); harness.fixture.detectChanges();
    expect(element.querySelector('article p')?.textContent).toContain(language === 'tr' ? 'HTTP bilinmiyor' : 'HTTP unknown');
    expect(Array.from(element.querySelectorAll(`article span[lang="${language}"]`)).some(node => node.textContent === (language === 'tr' ? 'bilinmiyor' : 'unknown'))).toBe(true);
    await harness.navigateByUrl(`/app/outcomes/8/9/${id}`);
    await harness.fixture.whenStable();
    await harness.routeDebugElement?.componentInstance.load();
    harness.fixture.detectChanges();
    expect(element.querySelector('form')).toBeNull();
    expect(element.textContent).toContain(language === 'tr' ? 'Bu proje için karşılaştırılabilir eylem kanıtları kullanılamıyor' : 'unavailable for this project');
    expect(element.querySelector('table')).toBeNull(); expect(element.querySelector('article')).toBeNull();
    if (language === 'tr') {
      const preference = vi.spyOn(api, 'productLanguage').mockResolvedValue({ status: 503,
        body: { language: 'tr', current_ui_language: 'en', current_email_language: 'en' } });
      await harness.navigateByUrl('/app'); await harness.navigateByUrl(`/app/outcomes/7/9/${id}`);
      await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(TestBed.inject(Title).getTitle()).toBe('Source-limited action outcomes — OrganicSEOOps');
      expect(harness.routeNativeElement?.querySelector('[aria-labelledby="outcome-title"]')?.getAttribute('lang')).toBe('en');
      preference.mockRestore();
      const buildEnvironment = environment as { production: boolean }; const production = buildEnvironment.production;
      try {
        buildEnvironment.production = true;
        await harness.navigateByUrl('/app'); await harness.navigateByUrl(`/app/outcomes/7/9/${id}`);
        await harness.fixture.whenStable(); harness.fixture.detectChanges();
        expect(harness.routeDebugElement!.componentInstance.productLanguage()).toBe('tr');
        expect(TestBed.inject(Title).getTitle()).toBe('Source-limited action outcomes — OrganicSEOOps');
        expect(harness.routeNativeElement?.querySelector('[aria-labelledby="outcome-title"]')?.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Source-limited action comparison');
        expect(harness.routeNativeElement?.textContent).not.toContain('iki dilli onay bekleniyor');
      } finally { buildEnvironment.production = production; }
    }
    await harness.navigateByUrl('/'); harness.fixture.detectChanges();
    const nextTitle = TestBed.inject(Title).getTitle();
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(nextTitle);
  });

  it('rejects array action comparison roles and clears management while context refresh is pending or denied', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.actionRows = [api.auditActionRow];
    const original = structuredClone(api.onboardingResult);
    const project = original.body['project'] as Record<string, unknown>;
    const harness = await RouterTestingHarness.create(`/app/outcomes/7/9/${api.auditActionRow['action_id']}`);
    await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    expect(component.canManage()).toBe(true);
    for (const role of ['owner', 'admin', 'member', 'viewer']) {
      api.onboardingResult = { ...original, body: { ...original.body, project: { ...project, role: [role] } } };
      await component.load(); harness.fixture.detectChanges();
      expect(component.canManage()).toBe(false); expect(component.error()).not.toBe('');
      expect(harness.routeNativeElement?.querySelector('form')).toBeNull();
      api.onboardingResult = { ...original, body: { ...original.body, project: { ...project, role } } };
      await component.load(); expect(component.error()).toBe('');
      expect(component.canManage()).toBe(role === 'owner' || role === 'admin');
    }
    api.onboardingResult = original; await component.load();
    expect(component.canManage()).toBe(true);
    let finish!: (result: ApiResult) => void;
    api.onboardingLoadHandler = () => new Promise(resolve => { finish = resolve; });
    const pending = component.load();
    expect(component.canManage()).toBe(false);
    finish({ status: 403, body: {} }); await pending;
    expect(component.canManage()).toBe(false); expect(component.error()).not.toBe('');
    expect(api.recordedOutcomeInputs).toEqual([]); expect(api.recordedTechnicalInputs).toEqual([]);
  });

  it.each(['en', 'tr'] as const)('keeps manual local facts, missing profiles and eligibility explicitly unverified (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    const onboarding = structuredClone(api.onboardingResult.body);
    const config = onboarding['configuration'] as Record<string, unknown>;
    config['business_locations'] = ['Synthetic location'];
    config['service_areas'] = ['Synthetic service area'];
    config['profile_urls'] = ['https://profiles.example.invalid/synthetic'];
    config['business_hours'] = '09:00–17:00';
    api.onboardingResult = { status: 200, body: onboarding };
    const harness = await RouterTestingHarness.create('/app/local/7/9');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const element = harness.routeNativeElement!;
    const component = harness.routeDebugElement!.componentInstance;
    expect(element.querySelector('[aria-labelledby="local-title"]')?.getAttribute('lang')).toBe(language);
    expect(element.querySelector('h1')?.textContent).toBe(language === 'tr' ? 'İşletme için elle yerel değerlendirme' : 'Manual local business assessment');
    expect(element.textContent).toContain(language === 'tr' ? 'Hiçbir Google İşletme Profili hesabı' : 'No Google Business Profile account');
    expect(element.querySelector('strong')?.textContent).toBe(language === 'tr' ? 'bilinmiyor' : 'unknown');
    expect(element.textContent).toContain(language === 'tr' ? 'tutarsızlık değildir' : 'not an inconsistency');
    expect(element.querySelector('ul')?.getAttribute('aria-label')).toBe(language === 'tr' ? 'Projenin elle yerel işletme incelemeleri' : 'Project manual local business reviews');
    expect(element.querySelector('option[value=""]')?.textContent).toBe(language === 'tr' ? 'Genel hizmet bölgesi incelemesi' : 'General service-area review');
    expect(element.querySelector('#local-profile option[value=""]')?.textContent).toBe(language === 'tr' ? 'İncelenmiş profil yok' : 'No reviewed profile');
    expect(element.querySelector('#local-eligibility')?.getAttribute('lang')).toBe('en');
    expect(Array.from(element.querySelectorAll('#local-eligibility option')).map(node => node.textContent)).toEqual(['unknown', 'review_needed', 'user_attested']);
    expect(element.textContent).toContain(language === 'tr' ? 'sağlayıcı tarafından doğrulanmadı' : 'not provider verified');
    const form = element.querySelector('form')!;
    for (const name of ['location_label', 'business_name', 'address_display', 'phone', 'hours', 'services', 'profile_url', 'review_theme', 'evidence_note', 'suggested_action']) {
      expect(form.querySelector(`[name="${name}"]`)?.getAttribute('lang')).toBe('');
    }
    form.querySelector<HTMLInputElement>('input[name="business_name"]')!.value = 'Synthetic business';
    form.querySelector<HTMLTextAreaElement>('textarea[name="services"]')!.value = 'Airport transfers';
    form.querySelector<HTMLTextAreaElement>('textarea[name="evidence_note"]')!.value = 'Owner entered facts, not checked.';
    form.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click();
    const loads = vi.spyOn(api, 'localAssessments'); const saves = vi.spyOn(api, 'saveLocalAssessment');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Manual local business review — OrganicSEOOps' : 'Elle yerel işletme incelemesi — OrganicSEOOps');
    expect(element.querySelector('form')).toBe(form);
    expect(form.querySelector<HTMLInputElement>('input[name="business_name"]')!.value).toBe('Synthetic business');
    expect(component.selectedAreas()).toEqual(['Synthetic service area']);
    expect(loads).not.toHaveBeenCalled(); expect(saves).not.toHaveBeenCalled();
    component.productLanguage.set(language); harness.fixture.detectChanges();
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.savedLocalAssessments[0]['business_name']).toBe('Synthetic business');
    expect(api.savedLocalAssessments[0]['services']).toEqual(['Airport transfers']);
    expect(api.savedLocalAssessments[0]['service_areas']).toEqual(['Synthetic service area']);
    expect(api.savedLocalAssessments[0]['eligibility']).toBe('unknown');
    expect(api.savedLocalAssessments[0]['expected_config_revision']).toBe(config['revision']);
    expect(element.textContent).toContain(language === 'tr' ? 'profil, yorumlar ve uygunluk hâlâ doğrulanmadı' : 'profile, reviews and eligibility remain unverified');
    expect(element.textContent).toContain(language === 'tr' ? 'Güncel proje yapılandırmasına dayanır' : 'Based on current project configuration');
    expect(element.textContent).toContain(language === 'tr' ? 'Hiçbir uyuşmazlık otomatik olarak tespit edilmez' : 'No discrepancy is automatically detected');
    expect(element.textContent).toContain(language === 'tr' ? 'yalnızca kullanıcı beyanı; sağlayıcı onayı değildir' : 'user claim only, not provider approved');
    for (const text of ['Synthetic business', 'Synthetic location', 'Airport transfers', 'Synthetic service area', 'Owner entered facts, not checked.']) {
      expect(Array.from(element.querySelectorAll('[lang=""]')).some(node => node.textContent === text)).toBe(true);
    }
    expect(element.querySelector('li [lang="en"]')?.textContent).toBe('unknown');
    element.querySelector<HTMLButtonElement>('li button')!.click();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(element.querySelector('#local-history-title')?.textContent).toBe(language === 'tr' ? 'Değiştirilemez elle inceleme sürümleri' : 'Immutable manual review revisions');
    expect(element.querySelector('ol [lang="en"]')?.textContent).toBe('unknown');
    element.querySelectorAll<HTMLButtonElement>('li button')[1].click(); harness.fixture.detectChanges();
    const correction = element.querySelector('form')!;
    expect(correction.querySelector<HTMLInputElement>('[name="business_name"]')!.value).toBe('Synthetic business');
    expect(correction.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(true);
    expect(element.querySelector('#local-form-title')?.textContent).toBe(language === 'tr' ? 'Elle girilen kanıtı düzelt' : 'Correct manual evidence');
    correction.querySelector<HTMLTextAreaElement>('[name="evidence_note"]')!.value = 'Corrected owner evidence.';
    correction.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.savedLocalAssessments[1]['expected_revision']).toBe(1);
    expect(api.savedLocalAssessments[1]['digest']).toBe('a'.repeat(64));
    expect(component.assessments()[0].revision).toBe(2);
    element.querySelectorAll<HTMLButtonElement>('li button')[1].click(); harness.fixture.detectChanges();
    element.querySelector<HTMLButtonElement>('form button[type="button"]')!.click(); harness.fixture.detectChanges();
    expect(component.editing()).toBeNull(); expect(component.selectedAreas()).toEqual([]);
    const stale = structuredClone(api.localAssessmentRows); stale[0]['source_current'] = false;
    api.localAssessmentRows = stale; await component.load(); harness.fixture.detectChanges();
    expect(element.textContent).toContain(language === 'tr' ? 'Geçmiş bilgiler; yapılandırma değişti, tekrar inceleyin' : 'Historical facts; configuration changed, review again');
    expect(element.querySelectorAll('li button')).toHaveLength(1);
    loads.mockRestore(); saves.mockRestore();
    await harness.navigateByUrl('/app/local/8/9');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(element.querySelector('form')).toBeNull();
    expect(element.querySelector('li')).toBeNull();
    expect(element.textContent).toContain(language === 'tr' ? 'Bu proje veya oturum için elle yerel kanıt kullanılamıyor' : 'unavailable for this project or session');
    if (language === 'tr') {
      const preference = vi.spyOn(api, 'productLanguage');
      for (const result of [
        { status: 503, body: { language: 'tr', current_ui_language: 'en', current_email_language: 'en' } },
        { status: 200, body: { language: ['tr'], current_ui_language: 'en', current_email_language: 'en' } },
        { status: 200, body: { language: 'tr', current_ui_language: 'tr', current_email_language: 'en' } },
      ]) {
        preference.mockResolvedValue(result);
        await harness.navigateByUrl('/app'); await harness.navigateByUrl('/app/local/7/9');
        await harness.fixture.whenStable(); harness.fixture.detectChanges();
        expect(TestBed.inject(Title).getTitle()).toBe('Manual local business review — OrganicSEOOps');
        expect(harness.routeNativeElement?.querySelector('[aria-labelledby="local-title"]')?.getAttribute('lang')).toBe('en');
      }
      preference.mockRejectedValue(new Error('private preference unavailable'));
      await harness.navigateByUrl('/app'); await harness.navigateByUrl('/app/local/7/9');
      await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(TestBed.inject(Title).getTitle()).toBe('Manual local business review — OrganicSEOOps');
      expect(harness.routeNativeElement?.querySelector('[aria-labelledby="local-title"]')?.getAttribute('lang')).toBe('en');
      expect(harness.routeNativeElement?.textContent).not.toContain('private preference unavailable');
      preference.mockRestore();
      const buildEnvironment = environment as { production: boolean }; const production = buildEnvironment.production;
      try {
        buildEnvironment.production = true;
        await harness.navigateByUrl('/app'); await harness.navigateByUrl('/app/local/7/9');
        await harness.fixture.whenStable(); harness.fixture.detectChanges();
        expect(harness.routeDebugElement!.componentInstance.productLanguage()).toBe('tr');
        expect(TestBed.inject(Title).getTitle()).toBe('Manual local business review — OrganicSEOOps');
        expect(harness.routeNativeElement?.querySelector('[aria-labelledby="local-title"]')?.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Manual local business assessment');
        expect(harness.routeNativeElement?.textContent).not.toContain('iki dilli onay bekleniyor');
      } finally { buildEnvironment.production = production; }
    }
    await harness.navigateByUrl('/'); harness.fixture.detectChanges();
    const nextTitle = TestBed.inject(Title).getTitle();
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(nextTitle);
  });

  it('rejects array manual local review digests across current history save and malformed editing roles', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const original = structuredClone(api.onboardingResult);
    const project = original.body['project'] as Record<string, unknown>;
    const config = original.body['configuration'] as Record<string, unknown>;
    config['business_locations'] = ['Synthetic location']; config['service_areas'] = ['Synthetic service area'];
    config['profile_urls'] = ['https://profiles.example.invalid/synthetic']; config['business_hours'] = '09:00–17:00';
    api.onboardingResult = original;
    const harness = await RouterTestingHarness.create('/app/local/7/9'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const component = harness.routeDebugElement!.componentInstance;
    const form = harness.routeNativeElement!.querySelector('form')!;
    form.querySelector<HTMLInputElement>('input[name="business_name"]')!.value = 'Synthetic business';
    form.querySelector<HTMLTextAreaElement>('textarea[name="services"]')!.value = 'Airport transfers';
    form.querySelector<HTMLTextAreaElement>('textarea[name="evidence_note"]')!.value = 'Human entered facts, unverified.';
    form.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click();
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true })); await harness.fixture.whenStable();
    expect(api.savedLocalAssessments).toHaveLength(1); expect(component.assessments()).toHaveLength(1);
    const row = structuredClone(api.localAssessmentRows[0]);
    const malformed = { ...row, location_digest: [row['location_digest']] };
    api.localAssessmentRows = [malformed]; await component.load();
    expect(component.assessments()).toEqual([]); expect(component.error()).not.toBe('');
    const history = vi.spyOn(api, 'localAssessmentHistory').mockResolvedValueOnce({ status: 200, body: { project_id: 9, history: [malformed] } });
    await component.history(row['location_digest']); expect(component.historyRows()).toEqual([]); history.mockRestore();
    api.localAssessmentRows = [row]; await component.load(); await component.history(row['location_digest']);
    expect(component.assessments()).toHaveLength(1); expect(component.historyRows()).toHaveLength(1);
    const save = vi.spyOn(api, 'saveLocalAssessment').mockResolvedValueOnce({ status: 201, body: { project_id: 9, assessment: malformed } });
    harness.fixture.detectChanges();
    const currentForm = harness.routeNativeElement!.querySelector('form')!;
    currentForm.querySelector<HTMLInputElement>('input[name="business_name"]')!.value = 'Synthetic new business';
    currentForm.querySelector<HTMLTextAreaElement>('textarea[name="services"]')!.value = 'Airport transfers';
    currentForm.querySelector<HTMLTextAreaElement>('textarea[name="evidence_note"]')!.value = 'Human entered facts, unverified.';
    currentForm.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click();
    currentForm.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true })); await harness.fixture.whenStable();
    expect(component.message()).toContain('Review outcome unknown'); expect(save.mock.calls).toHaveLength(1);
    expect(currentForm.querySelector<HTMLInputElement>('input[name="business_name"]')!.value).toBe('Synthetic new business'); save.mockRestore();
    for (const role of ['owner', 'admin', 'member', 'viewer']) {
      api.onboardingResult = { ...original, body: { ...original.body, project: { ...project, role: [role] } } };
      await component.load(); expect(component.canManage()).toBe(false); expect(component.assessments()).toEqual([]); expect(component.error()).not.toBe('');
      api.onboardingResult = { ...original, body: { ...original.body, project: { ...project, role } } };
      await component.load(); expect(component.error()).toBe(''); expect(component.assessments()).toHaveLength(1);
      expect(component.canManage()).toBe(role === 'owner' || role === 'admin');
    }
    expect(api.savedLocalAssessments).toHaveLength(1);
  });

  it.each(['en', 'tr'] as const)('keeps source outage distinct from evidenced findings and clears prior project data (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    api.organizationsResult = { status: 200, body: { organizations: [{ id: 7, access_state: 'read_only' }], has_more: false } };
    api.sourcesHandler = async () => ({ status: 503, body: {} });
    api.findingRows = [{ id: 112, subject: 'synthetic query', detector: 'candidate_not_proof',
      method_version: 'gsc-csv-opportunity-v1', confidence: 'candidate_source_limited',
      detected_at: '2026-09-29T12:00:00Z', source_current: true,
      review: { priority: 'high', estimated_effort: 'unknown', business_relevance: 'unknown',
        review_reason: 'Inspect source first.' } }];
    const harness = await RouterTestingHarness.create('/app/dashboard/7/9');
    await harness.routeDebugElement?.componentInstance.load();
    harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Kanıt ve eylem panosu — OrganicSEOOps' : 'Evidence and action dashboard — OrganicSEOOps');
    const element = harness.routeNativeElement!;
    const component = harness.routeDebugElement!.componentInstance;
    expect(element.querySelector('[aria-labelledby="dashboard-title"]')?.getAttribute('lang')).toBe(language);
    expect(element.querySelector('h1')?.textContent).toBe(language === 'tr' ? 'Önemli olanlar, nedenleri ve insanın sonraki adımı' : 'What matters, why, and the next human action');
    expect(element.querySelector('nav')?.getAttribute('aria-label')).toBe(language === 'tr' ? 'Proje inceleme bağlantıları' : 'Project review destinations');
    expect(element.querySelector('a[href="/app/first-audit/7/9"]')).not.toBeNull();
    expect(element.textContent).toContain(language === 'tr' ? 'Kaynak durumu kullanılamıyor' : 'Source status unavailable');
    expect(element.textContent).toContain(language === 'tr' ? 'eksik kaynak sıfır etkinlik sayılmaz' : 'no missing source is treated as zero activity');
    expect(element.textContent).toContain(language === 'tr' ? 'kaynakla sınırlı kanıttır' : 'source-limited evidence');
    expect(element.textContent).toContain(language === 'tr' ? 'Eksik listeleme/profil bilgileri bilinmez' : 'Missing listing/profile facts are unknown');
    expect(element.querySelector('#priorities-title + p')?.textContent).toContain(language === 'tr' ? 'tam trafik eğilimleri değildir' : 'not complete traffic trends');
    expect(element.querySelector('#priority-filter option[value="high"]')?.textContent).toBe(language === 'tr' ? 'Yüksek' : 'High');
    for (const text of ['Onboarding project', 'synthetic query', 'Inspect source first.']) {
      expect(Array.from(element.querySelectorAll('[lang=""]')).some(node => node.textContent === text)).toBe(true);
    }
    expect(Array.from(element.querySelectorAll('[lang="en"]')).some(node => node.textContent === 'gsc-csv-opportunity-v1 · candidate_source_limited')).toBe(true);
    expect(element.textContent).toContain(language === 'tr' ? 'Kuruluş erişimi: read_only' : 'Organization access: read_only');
    expect(element.textContent).toContain('synthetic query');
    expect(element.textContent).toContain(language === 'tr' ? 'İnsan önceliği high' : 'Human priority high');
    expect(element.textContent).toContain(language === 'tr' ? 'Henüz onaylı veya kaydedilmiş insan eylemi yok' : 'No approved or recorded human action yet');
    expect(element.textContent).not.toContain('SEO score:');
    for (const state of ['unavailable', 'pending_review', 'active', 'read_only', 'suspended']) {
      api.organizationsResult.body['organizations'] = [{ id: 7, access_state: [state] }];
      await harness.routeDebugElement!.componentInstance.load(); harness.fixture.detectChanges();
      expect(harness.routeDebugElement!.componentInstance.accessState()).toBe('');
      expect(element.textContent).toContain(language === 'tr' ? 'Yetki durumu kullanılamıyor' : 'Entitlement state unavailable');
      api.organizationsResult.body['organizations'] = [{ id: 7, access_state: state }];
      await harness.routeDebugElement!.componentInstance.load(); harness.fixture.detectChanges();
      expect(harness.routeDebugElement!.componentInstance.accessState()).toBe(state);
      expect(harness.routeDebugElement!.componentInstance.accessError()).toBe(false);
    }
    const priority = element.querySelector<HTMLSelectElement>('#priority-filter')!;
    priority.value = 'low'; priority.dispatchEvent(new Event('change'));
    harness.fixture.detectChanges();
    expect(element.textContent).toContain(language === 'tr' ? 'Bu filtreye uyan bulgu adayı yok' : 'No finding candidate matches this filter');
    priority.value = 'high'; priority.dispatchEvent(new Event('change'));
    const date = element.querySelector<HTMLInputElement>('#finding-date-filter')!;
    date.value = '2026-09-30'; date.dispatchEvent(new Event('change'));
    harness.fixture.detectChanges();
    expect(element.textContent).toContain(language === 'tr' ? 'Bu filtreye uyan bulgu adayı yok' : 'No finding candidate matches this filter');
    component.findingSince.set(''); component.priorityFilter.set('all');
    api.sourcesHandler = async (_org, projectId) => ({ status: 200, body: { project_id: projectId, sources: [{
      id: 5, provider: 'google_search_console', state: 'active', scope_current: true,
      latest_import: { status: 'partially_succeeded', coverage_state: 'partial', date_end: '2026-09-29', source_completeness: 'provider_export_unknown' },
      sync: { status: 'failed', quota_state: 'exhausted', fresh_through: null, error_category: 'provider_unavailable' },
      data_status: 'exact_origin_attribution_unavailable',
    }] } });
    api.actionRows = [{ action_id: 'a64070a5-91a1-4198-9556-651ab00c11bc', state: 'implemented', action_kind: 'refresh',
      source_current: false, affected_urls: ['https://synthetic.example/path'], acceptance_criteria: 'Customer criterion',
      implemented_at: '2026-09-29T12:00:00Z' }];
    await component.load(); harness.fixture.detectChanges();
    expect(element.textContent).toContain(language === 'tr' ? 'Sağlayıcı bütünlüğü provider_export_unknown' : 'Provider completeness provider_export_unknown');
    expect(element.textContent).toContain(language === 'tr' ? 'dönüşüm ilişkilendirmesi kullanılamıyor' : 'conversion attribution is unavailable');
    expect(element.textContent).toContain(language === 'tr' ? 'sonuç kanıtlanmamıştır' : 'outcome unproven without comparable follow-up');
    expect(element.querySelector('#provider-filter option[value="google_search_console"]')?.getAttribute('lang')).toBe('en');
    for (const text of ['google_search_console · active', 'partially_succeeded / partial', 'failed', 'exhausted', 'provider_unavailable', 'refresh · implemented']) {
      expect(Array.from(element.querySelectorAll('[lang="en"]')).some(node => node.textContent === text)).toBe(true);
    }
    for (const text of ['https://synthetic.example/path', 'Customer criterion']) {
      expect(Array.from(element.querySelectorAll('[lang=""]')).some(node => node.textContent === text)).toBe(true);
    }
    const source = element.querySelector<HTMLSelectElement>('#source-filter')!;
    source.value = 'unavailable'; source.dispatchEvent(new Event('change')); harness.fixture.detectChanges();
    expect(component.sourceFilter()).toBe('unavailable'); expect(element.textContent).toContain('google_search_console');
    const provider = element.querySelector<HTMLSelectElement>('#provider-filter')!;
    provider.value = 'google_search_console'; provider.dispatchEvent(new Event('change')); harness.fixture.detectChanges();
    expect(component.providerFilter()).toBe('google_search_console');
    const action = element.querySelector<HTMLSelectElement>('#action-filter')!;
    action.value = 'proposed'; action.dispatchEvent(new Event('change')); harness.fixture.detectChanges();
    expect(component.actionFilter()).toBe('proposed');
    expect(element.textContent).toContain(language === 'tr' ? 'Bu kayıtlı durumda eylem yok' : 'No action has this recorded state');
    // A language-only change must retain selected filters and loaded evidence without refetching.
    const sourceReads = vi.spyOn(api, 'projectSources');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Evidence and action dashboard — OrganicSEOOps' : 'Kanıt ve eylem panosu — OrganicSEOOps');
    expect(component.providerFilter()).toBe('google_search_console'); expect(component.actionFilter()).toBe('proposed');
    expect(component.findings()[0].subject).toBe('synthetic query'); expect(sourceReads).not.toHaveBeenCalled();
    component.productLanguage.set(language); sourceReads.mockRestore();
    await harness.navigateByUrl('/app/dashboard/8/9');
    await harness.routeDebugElement?.componentInstance.load();
    harness.fixture.detectChanges();
    expect(element.textContent).not.toContain('synthetic query');
    expect(element.textContent).toContain(language === 'tr' ? 'Bu proje için pano bağlamı kullanılamıyor' : 'unavailable for this project');
    expect(element.textContent).not.toContain('Customer criterion'); expect(component.actions()).toEqual([]);
    expect(component.sourceFilter()).toBe('all'); expect(component.providerFilter()).toBe('all');
    expect(component.priorityFilter()).toBe('all'); expect(component.findingSince()).toBe(''); expect(component.actionFilter()).toBe('all');
    if (language === 'tr') {
      const preference = vi.spyOn(api, 'productLanguage').mockResolvedValue({ status: 200,
        body: { language: 'tr', current_ui_language: ['en'], current_email_language: 'en' } });
      await harness.navigateByUrl('/app'); await harness.navigateByUrl('/app/dashboard/7/9');
      await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(TestBed.inject(Title).getTitle()).toBe('Evidence and action dashboard — OrganicSEOOps');
      expect(harness.routeNativeElement?.querySelector('[aria-labelledby="dashboard-title"]')?.getAttribute('lang')).toBe('en');
      preference.mockRejectedValue(new Error('private preference transport text'));
      await harness.navigateByUrl('/app'); await harness.navigateByUrl('/app/dashboard/7/9');
      await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('What matters, why, and the next human action');
      expect(TestBed.inject(Title).getTitle()).toBe('Evidence and action dashboard — OrganicSEOOps');
      expect(harness.routeNativeElement?.textContent).not.toContain('private preference transport text');
      preference.mockRestore();
      const buildEnvironment = environment as { production: boolean }; const production = buildEnvironment.production;
      try {
        buildEnvironment.production = true;
        await harness.navigateByUrl('/app'); await harness.navigateByUrl('/app/dashboard/7/9');
        await harness.fixture.whenStable(); harness.fixture.detectChanges();
        expect(harness.routeDebugElement!.componentInstance.productLanguage()).toBe('tr');
        expect(TestBed.inject(Title).getTitle()).toBe('Evidence and action dashboard — OrganicSEOOps');
        expect(harness.routeNativeElement?.querySelector('[aria-labelledby="dashboard-title"]')?.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('What matters, why, and the next human action');
        expect(harness.routeNativeElement?.textContent).not.toContain('iki dilli onay bekleniyor');
        expect(harness.routeNativeElement?.querySelector('a[href="/app/jobs/7/9"]')).toBeNull();
      } finally { buildEnvironment.production = production; }
    }
    await harness.navigateByUrl('/'); harness.fixture.detectChanges();
    const nextTitle = TestBed.inject(Title).getTitle();
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(nextTitle);
  });

  it.each(['en', 'tr'] as const)('shows scoped report sharing disclosure and clears the one-time link when project context changes (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    api.findingRows = [{ id: 11, subject: 'Synthetic bounded candidate', source_current: true }];
    const harness = await RouterTestingHarness.create('/app/reports/7/9');
    await harness.routeDebugElement?.componentInstance.load();
    harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Özel proje raporları ve paylaşımları — OrganicSEOOps' : 'Private project reports and shares — OrganicSEOOps');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const element = harness.routeNativeElement!;
    expect(element.querySelector('[aria-labelledby="reports-title"]')?.getAttribute('lang')).toBe(language);
    expect(element.querySelector('h1')?.textContent).toBe(language === 'tr' ? 'Özel proje kanıt raporları' : 'Private project evidence reports');
    expect(element.querySelector('[aria-labelledby="project-help-title"]')?.getAttribute('lang')).toBe(language);
    expect(element.querySelector('app-project-crux-alert-preference section')?.getAttribute('lang')).toBe(language);
    expect(element.querySelector('fieldset span')?.getAttribute('lang')).toBe('');
    expect(element.querySelector('fieldset span')?.textContent).toBe('Synthetic bounded candidate');
    expect(element.textContent).toContain(language === 'tr' ? 'Bağlantıya sahip olan herkes' : 'Anyone holding a link');
    expect(element.textContent).toContain(language === 'tr' ? 'Otomatik e-posta gönderilmez' : 'No email is sent automatically');
    expect(element.querySelector('app-project-summary-preference section')?.getAttribute('lang')).toBe(language);
    expect(element.querySelector('app-project-alert-preference section')?.getAttribute('lang')).toBe(language);
    for (const name of ['crawl-failures', 'integration-health', 'job-reference', 'support']) {
      expect(element.querySelector(`app-project-${name} section`)?.getAttribute('lang')).toBe(language);
    }
    expect(element.querySelector('app-project-summary-preference')?.textContent)
      .toContain(language === 'tr' ? 'doğrudan e-posta planlamaz veya göndermez' : 'does not directly schedule or send mail');
    expect(element.textContent).toContain(language === 'tr' ? 'Haftalık teslimat etkinleştirilmemiş' : 'Weekly delivery rollout is off');
    expect(element.textContent).toContain(language === 'tr' ? 'Saklanmış haftalık iletim geçmişiniz' : 'Your retained weekly transport history');
    expect(element.textContent).toContain(language === 'tr' ? 'Kaydedilmiş uyarı e-posta sıklığı: off' : 'Saved alert email frequency: off');
    expect(element.textContent).toContain(language === 'tr' ? 'Kaydedilmiş CrUX e-posta sıklığı: off' : 'Saved CrUX email frequency: off');
    expect(element.textContent).toContain(language === 'tr' ? 'CrUX teslimatı etkinleştirilmemiş' : 'CrUX delivery rollout is off');
    expect(api.cruxHistoryReads).toEqual([]);
    expect(api.supportReferenceReads).toEqual([]);
    const referenceForm = element.querySelector<HTMLFormElement>('app-project-job-reference form')!;
    const referenceInput = referenceForm.querySelector<HTMLInputElement>('#support-job-id')!;
    referenceInput.value = '777'; referenceInput.dispatchEvent(new Event('input'));
    referenceForm.dispatchEvent(new Event('submit', { cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.supportReferenceReads).toEqual([[7, 9, 777]]); expect(element.textContent).toContain(language === 'tr' ? 'İş referansı 777' : 'Job reference 777');
    expect(api.supportRequestReads).toEqual([]); expect(api.supportRequestCreates).toEqual([]);
    const supportForm = element.querySelector<HTMLFormElement>('app-project-support form')!;
    const question = supportForm.querySelector<HTMLTextAreaElement>('#support-question')!;
    question.value = 'Routed private question'; question.dispatchEvent(new Event('input'));
    supportForm.querySelector<HTMLInputElement>('[name="declaration"]')!.click();
    supportForm.dispatchEvent(new Event('submit', { cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.supportRequestReads).toEqual([[7, 9]]);
    expect(api.supportRequestCreates[0]).toMatchObject({ question: 'Routed private question', expected_actor_id: 4, no_sensitive_data: true });
    expect(element.textContent).toContain(language === 'tr' ? 'Talep 888' : 'Request 888');
    expect(api.cruxPreferenceSaves).toEqual([]);
    const cruxForm = element.querySelector<HTMLFormElement>('app-project-crux-alert-preference form')!;
    const cruxFrequency = cruxForm.querySelector<HTMLSelectElement>('#crux-alert-frequency')!;
    cruxFrequency.value = 'daily'; cruxFrequency.dispatchEvent(new Event('change'));
    cruxForm.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.cruxPreferenceSaves).toEqual([[7, 9, 'daily', 0]]);
    expect(element.textContent).toContain(language === 'tr' ? 'Kaydedilmiş CrUX e-posta sıklığı: daily' : 'Saved CrUX email frequency: daily');
    Array.from(element.querySelectorAll<HTMLButtonElement>('app-project-crux-alert-preference button')).find(button => button.textContent?.includes(language === 'tr' ? 'CrUX geçmişimi' : 'my CrUX history'))!.click();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.cruxHistoryReads).toEqual([[7, 9]]); expect(element.textContent).toContain(language === 'tr' ? 'Kayıt 997' : 'Record 997');
    expect(api.alertHistoryReads).toEqual([]);
    expect(element.textContent).toContain(language === 'tr' ? 'Kaydedilmiş uyarı e-posta sıklığı: off' : 'Saved alert email frequency: off');
    expect(api.alertPreferenceSaves).toEqual([]);
    const alertForm = element.querySelector<HTMLFormElement>('app-project-alert-preference form')!;
    const alertFrequency = alertForm.querySelector<HTMLSelectElement>('#alert-frequency')!;
    alertFrequency.value = 'daily'; alertFrequency.dispatchEvent(new Event('change'));
    alertForm.querySelector<HTMLInputElement>('[name="crawl_failure"]')!.click();
    alertForm.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.alertPreferenceSaves).toEqual([[7, 9, 'daily', ['crawl_failure'], 0]]);
    expect(element.textContent).toContain(language === 'tr' ? 'Kaydedilmiş uyarı e-posta sıklığı: daily' : 'Saved alert email frequency: daily');
    expect(element.textContent).toContain(language === 'tr' ? 'doğrudan isteğe bağlı özet planlamadı veya göndermedi' : 'did not directly schedule or send');
    expect(api.summaryHistoryReads).toEqual([]);
    Array.from(element.querySelectorAll<HTMLButtonElement>('button')).find(button => button.textContent?.includes(language === 'tr' ? 'Haftalık geçmişimi' : 'my weekly history'))!.click();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.summaryHistoryReads).toEqual([[7, 9]]); expect(element.textContent).toContain(language === 'tr' ? 'Kayıt 991' : 'Record 991');
    expect(api.alertHistoryReads).toEqual([]);
    Array.from(element.querySelectorAll<HTMLButtonElement>('app-project-alert-preference button')).find(button => button.textContent?.includes(language === 'tr' ? 'Günlük geçmişimi' : 'my daily history'))!.click();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.alertHistoryReads).toEqual([[7, 9]]); expect(element.textContent).toContain(language === 'tr' ? 'Kayıt 998' : 'Record 998');
    expect(api.crawlFailureReads).toEqual([]);
    Array.from(element.querySelectorAll<HTMLButtonElement>('button')).find(button => button.textContent?.includes(language === 'tr' ? 'Saklanmış tarama hatalarını' : 'Inspect / refresh retained crawl failures'))!.click();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.crawlFailureReads).toEqual([[7, 9]]); expect(element.textContent).toContain(language === 'tr' ? 'İş 771' : 'Job 771');
    expect(api.integrationHealthReads).toEqual([]);
    Array.from(element.querySelectorAll<HTMLButtonElement>('button')).find(button => button.textContent?.includes(language === 'tr' ? 'Entegrasyon meta verilerini' : 'Inspect / refresh integration metadata'))!.click();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.integrationHealthReads).toEqual([[7, 9]]); expect(element.textContent).toContain(language === 'tr' ? 'Bağlantı 661' : 'Connection 661');
    element.querySelector<HTMLInputElement>('fieldset input[type="checkbox"]')!.click();
    element.querySelector<HTMLFormElement>('form')!.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.reportCreateIds).toEqual([[11]]);
    expect(element.querySelector('[aria-labelledby="saved-reports-title"] a')?.textContent)
      .toBe(language === 'tr' ? 'İndir (güncel proje izni gerekir)' : 'Download (current project permission required)');
    const shareForm = element.querySelectorAll<HTMLFormElement>('form')[1];
    shareForm.querySelector<HTMLInputElement>('#share-recipient')!.value = 'reader@example.invalid';
    shareForm.querySelector<HTMLInputElement>('[name="acknowledge"]')!.click();
    shareForm.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(element.querySelector<HTMLInputElement>('#share-link')?.value).toContain('/api/reports/shared/');
    expect(element.querySelector<HTMLInputElement>('#share-link')?.getAttribute('lang')).toBe('');
    const component = harness.routeDebugElement!.componentInstance;
    const originalLink = component.shareLink();
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Private project reports and shares — OrganicSEOOps' : 'Özel proje raporları ve paylaşımları — OrganicSEOOps');
    expect(component.shareLink()).toBe(originalLink); expect(api.reportCreateIds).toEqual([[11]]);
    component.productLanguage.set(language); harness.fixture.detectChanges();
    expect(element.textContent).toContain(language === 'tr' ? 'tekrar gösterilmez' : 'it will not be shown again');
    expect(element.querySelector('[aria-labelledby="shares-title"] span[lang="en"]')?.textContent).toBe('active');
    const revoke = Array.from(element.querySelectorAll<HTMLButtonElement>('button'))
      .find(button => button.textContent === (language === 'tr' ? 'Gelecekteki erişimi kaldır' : 'Revoke future access'))!;
    revoke.click(); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(element.querySelector('#share-link')).toBeNull();
    expect(element.textContent).toContain(language === 'tr' ? 'indirilmiş kopyalar silinemez' : 'copies already downloaded cannot be erased');
    await harness.navigateByUrl('/app/reports/8/9');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(element.querySelector('#share-link')).toBeNull();
    expect(element.textContent).not.toContain(language === 'tr' ? 'Kayıt 998' : 'Record 998');
    expect(element.textContent).not.toContain(language === 'tr' ? 'Kayıt 997' : 'Record 997');
    expect(element.textContent).not.toContain('Job reference 777');
    expect(element.textContent).not.toContain('Request 888');
    expect(element.textContent).not.toContain('Routed private question');
    expect(element.textContent).not.toContain('Synthetic bounded candidate');
    expect(element.textContent).not.toContain(language === 'tr' ? 'Kayıt 991' : 'Record 991');
    expect(element.textContent).not.toContain('Job 771');
    expect(element.textContent).not.toContain('Connection 661');
    expect(element.textContent).not.toContain(language === 'tr' ? 'Kaydedilmiş uyarı e-posta sıklığı: daily' : 'Saved alert email frequency: daily');
    expect(element.textContent).not.toContain(language === 'tr' ? 'Kaydedilmiş CrUX e-posta sıklığı: daily' : 'Saved CrUX email frequency: daily');
    expect(element.querySelector('[role="alert"]')?.textContent).toContain(language === 'tr' ? 'raporu erişimi kullanılamıyor' : 'report access is unavailable');
    const preference = vi.spyOn(api, 'productLanguage'), buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    try {
      for (const mode of ['unavailable', 'invalid', 'production'] as const) {
        await harness.navigateByUrl('/');
        buildEnvironment.production = mode === 'production';
        if (mode === 'unavailable') preference.mockRejectedValue(new Error('PRIVATE preference error'));
        else preference.mockResolvedValue({ status: 200, body: { language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: 'en', current_email_language: 'en' } });
        await harness.navigateByUrl('/app/reports/7/9'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
        expect(TestBed.inject(Title).getTitle()).toBe('Private project reports and shares — OrganicSEOOps');
        expect(harness.routeNativeElement!.querySelector('[aria-labelledby="reports-title"]')?.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement!.querySelector('h1')?.textContent).toBe('Private project evidence reports');
        expect(harness.routeNativeElement!.textContent).not.toContain('PRIVATE preference error');
        expect(harness.routeNativeElement!.textContent).not.toContain('incelenmemiş Türkçe rapor');
      }
    } finally { buildEnvironment.production = production; preference.mockRestore(); }
    await harness.navigateByUrl('/'); harness.fixture.detectChanges();
    const nextTitle = TestBed.inject(Title).getTitle();
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(nextTitle);
  });

  it('rejects array report roles formats and share states and clears previous projections on refresh', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const original = structuredClone(api.onboardingResult);
    const project = original.body['project'] as Record<string, unknown>;
    const report = { id: 22, format: 'csv', created_at: '2026-09-29T09:00:00Z', size_bytes: 72,
      source_counts: { findings: 1, actions: 0, outcomes: 0 } };
    const share = { id: 31, report_id: 22, intended_recipient: 'reader@example.invalid',
      expires_at: '2026-09-30T09:00:00Z', state: 'active' };
    api.reportRows = [report]; api.reportShareRows = [share];
    const harness = await RouterTestingHarness.create('/app/reports/7/9');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const component = harness.routeDebugElement!.componentInstance;
    expect(component.canShare()).toBe(true); expect(component.reports()).toEqual([report]); expect(component.shares()).toEqual([share]);
    for (const role of ['owner', 'admin', 'member', 'viewer']) {
      api.onboardingResult = { ...original, body: { ...original.body, project: { ...project, role: [role] } } };
      component.shareLink.set('/api/reports/shared/OLD');
      await component.load(); harness.fixture.detectChanges();
      expect(component.canShare()).toBe(false); expect(component.reports()).toEqual([]); expect(component.shares()).toEqual([]);
      expect(component.shareLink()).toBe(''); expect(component.error()).toContain('report access is unavailable');
      expect(harness.routeNativeElement?.querySelector('#share-link')).toBeNull();
      api.onboardingResult = { ...original, body: { ...original.body, project: { ...project, role } } };
      await component.load();
      expect(component.error()).toBe(''); expect(component.reports()).toEqual([report]);
      expect(component.canShare()).toBe(role === 'owner' || role === 'admin');
    }
    api.onboardingResult = original;
    for (const format of ['csv', 'json']) {
      api.reportRows = [report]; await component.load();
      api.reportRows = [{ ...report, format: [format] }]; await component.load();
      expect(component.error()).toContain('report access is unavailable'); expect(component.reports()).toEqual([]);
    }
    api.reportRows = [report];
    for (const state of ['active', 'revoked', 'expired']) {
      api.reportShareRows = [share]; await component.load(); component.shareLink.set('/api/reports/shared/OLD');
      expect(component.shareError()).toBe(false); expect(component.shares()).toEqual([share]);
      api.reportShareRows = [{ ...share, state: [state] }]; await component.load(); harness.fixture.detectChanges();
      expect(component.shareError()).toBe(true); expect(component.shares()).toEqual([]); expect(component.shareLink()).toBe('');
      expect(harness.routeNativeElement?.querySelector('#share-link')).toBeNull();
      expect(harness.routeNativeElement?.querySelector<HTMLButtonElement>('section[aria-labelledby="shares-title"] button[type="submit"]')?.disabled).toBe(true);
    }
    api.reportShareRows = [share]; await component.load(); harness.fixture.detectChanges();
    const issue = vi.spyOn(api, 'createProjectReportShare');
    const form = harness.routeNativeElement!.querySelector<HTMLInputElement>('#share-recipient')!.closest('form')!;
    form.querySelector<HTMLInputElement>('#share-recipient')!.value = 'reader@example.invalid';
    form.querySelector<HTMLInputElement>('[name="acknowledge"]')!.checked = true;
    for (const state of ['active', 'revoked', 'expired']) {
      issue.mockResolvedValue({ status: 201, body: { share: { ...share, state: [state] },
        link_path: `/api/reports/shared/${'A'.repeat(43)}/` } });
      form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
      await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(component.shareLink()).toBe(''); expect(component.message()).toContain('Share outcome unavailable');
      expect(harness.routeNativeElement?.querySelector('#share-link')).toBeNull();
    }
    expect(issue.mock.calls).toHaveLength(3); issue.mockRestore();
    component.shareLink.set('/api/reports/shared/OLD');
    let finish!: (value: ApiResult) => void;
    api.onboardingLoadHandler = () => new Promise(resolve => { finish = resolve; });
    const pending = component.load();
    expect(component.canShare()).toBe(false); expect(component.reports()).toEqual([]); expect(component.shares()).toEqual([]); expect(component.shareLink()).toBe('');
    finish({ status: 403, body: {} }); await pending;
    expect(component.reports()).toEqual([]); expect(component.shares()).toEqual([]);
    expect(api.reportCreateIds).toEqual([]);
  });

  it.each(['en', 'tr'] as const)('keeps contextual evidence and retention help truthful and owner controls scoped across role loss and refresh (%s)', async (language) => {
    const api = new AccountApiStub();
    api.savedProductLanguage = language;
    TestBed.configureTestingModule({ providers: [provideRouter(routes), { provide: AccountApi, useValue: api }] });
    const harness = await RouterTestingHarness.create('/app/reports/7/9');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const element = harness.routeNativeElement!, component = harness.routeDebugElement!.componentInstance as ProjectReports;
    const help = () => element.querySelector<HTMLElement>('[aria-labelledby="project-help-title"]');
    expect(help()?.querySelectorAll('details > summary').length).toBe(4);
    expect(help()?.getAttribute('lang')).toBe(language);
    for (const text of language === 'tr' ? ['Eksik kaynak verisi sıfır trafik', 'dizine alınmanın kanıtı değildir', '90 gün', '30 gün', '35 günlük',
      'tam yasal, finansal veya yedek dışa aktarımı değildir', 'gerçekleştiğinin kanıtı değildir', 'kimliğin tamamen silindiğini kanıtlamaz'] :
      ['Missing source data is not zero', 'not proof of indexing', '90 days', '30 days', '35-day',
      'not a complete legal', 'not proof that a hosted deletion', 'does not prove complete identity erasure']) expect(help()?.textContent).toContain(text);
    for (const path of ['/app/export/7', '/app/closure-status/7', '/app/billing/7', '/account/security']) expect(help()?.querySelector(`a[href="${path}"]`)).not.toBeNull();
    expect(api.supportRequestCreates).toEqual([]); expect(api.supportRequestReads).toEqual([]); expect(api.reportCreateIds).toEqual([]);
    for (const role of ['admin', 'viewer']) {
      api.onboardingResult.body['project'] = { ...(api.onboardingResult.body['project'] as object), role };
      const refresh = component.load(); harness.fixture.detectChanges();
      expect(help()).toBeNull(); expect(component.organizationOwner()).toBe(false);
      await refresh; harness.fixture.detectChanges();
      for (const path of ['/app/export/7', '/app/closure-status/7', '/app/billing/7']) expect(help()?.querySelector(`a[href="${path}"]`)).toBeNull();
      expect(help()?.querySelector('a[href="/account/security"]')).not.toBeNull(); expect(help()?.textContent).toContain(language === 'tr' ? 'güncel kuruluş sahibine başvurun' : 'Ask the current organization owner');
    }
    api.onboardingResult = { status: 403, body: {} }; await component.load(); harness.fixture.detectChanges();
    expect(help()).toBeNull(); expect(component.organizationOwner()).toBe(false);
    await harness.navigateByUrl('/app/reports/8/9'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(element.querySelector('a[href="/app/export/7"]')).toBeNull();
  });

  it('reviews immutable source topics, filters human classifications, keeps errors and clears foreign scope', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const harness = await RouterTestingHarness.create('/app/topics/7/9');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const element = harness.routeNativeElement!;
    const click = async (text: string) => {
      Array.from(element.querySelectorAll<HTMLButtonElement>('button')).find((button) => button.textContent?.includes(text))!.click();
      await harness.fixture.whenStable(); harness.fixture.detectChanges();
    };
    const discovery = element.querySelector<HTMLFormElement>('form')!;
    discovery.querySelector<HTMLInputElement>('[name="feeds"]')!.checked = true;
    discovery.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.topicDiscoveryInputs[0]['feeds']).toEqual(['https://research-source.example.invalid/rss']);
    expect(api.topicDiscoveryInputs[0]['connection_id']).toBeNull();
    await click('Inspect discovery'); await click('Cancel discovery');
    expect(element.textContent).toContain('Cancellation requested.');
    await click('Inspect collection'); await click('Review candidate');
    expect(element.querySelector('script')).toBeNull();
    expect(element.textContent).toContain('Competition, volume');
    const form = element.querySelector<HTMLFormElement>('#topic-label')!.closest('form')!;
    form.querySelector<HTMLInputElement>('#topic-label')!.value = 'Human evergreen fixture';
    form.querySelector<HTMLSelectElement>('#topic-class')!.value = 'evergreen';
    form.querySelector<HTMLSelectElement>('#topic-language')!.value = 'en';
    form.querySelector<HTMLTextAreaElement>('#topic-reason')!.value = 'Human review, not demand measurement.';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect((api.topicInputs[0]['judgments'] as Record<string, unknown>)['existing_coverage']).toEqual({ score: null, note: '' });
    expect(element.querySelector<HTMLAnchorElement>('a[href*="topic_review"]')?.href).toContain('topic_review=90');
    const filter = element.querySelector<HTMLSelectElement>('#topic-filter')!;
    filter.value = 'trending'; filter.dispatchEvent(new Event('change')); harness.fixture.detectChanges();
    expect(element.textContent).toContain('No candidates in this filter');
    api.topicSaveStatus = 409;
    form.querySelector<HTMLInputElement>('#topic-label')!.value = 'Rejected correction retained';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(form.querySelector<HTMLInputElement>('#topic-label')!.value).toBe('Rejected correction retained');
    expect(element.textContent).toContain('Input retained');
    expect(element.querySelector('a[href*="topic_review"]')).toBeNull();
    await harness.navigateByUrl('/app/topics/8/9'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).not.toContain('Human evergreen fixture');
    expect(harness.routeNativeElement?.querySelector('#topic-label')).toBeNull();
  });

  it('binds research to authenticated current review and blocks stale or foreign query selections', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.topicReviews = [{ id: 90, project_id: 9, snapshot_id: 80, candidate_index: 0, revision: 1,
      label: 'Authenticated reviewed topic', language: 'en', classification: 'evergreen', intent_review_id: null }];
    const harness = await RouterTestingHarness.create('/app/research/7/9?topic_review=90&topic=ForgedURL');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const element = harness.routeNativeElement!;
    expect(element.textContent).toContain('Authenticated exact-current topic review');
    const form = element.querySelector<HTMLFormElement>('form')!;
    expect(form.querySelector<HTMLInputElement>('#research-topic')!.value).toBe('Authenticated reviewed topic');
    expect(form.querySelector<HTMLInputElement>('#research-topic')!.readOnly).toBe(true);
    expect(form.querySelector<HTMLTextAreaElement>('#research-urls')!.value).toBe(api.topicEvidence.url);
    form.querySelector<HTMLSelectElement>('#research-model')!.value = '30';
    form.querySelector<HTMLSelectElement>('#research-model')!.dispatchEvent(new Event('change')); harness.fixture.detectChanges();
    form.querySelector<HTMLSelectElement>('#research-account')!.value = '31';
    form.querySelector<HTMLInputElement>('#research-cost')!.value = '0.01';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.researchRequests[0]['topic_review_id']).toBe(90);
    expect(api.researchRequests[0]['topic']).toBe('Authenticated reviewed topic');
    expect(api.researchRequests[0]['language']).toBe('en');
    api.topicSourceCurrent = false;
    await harness.navigateByUrl('/app/research/7/9?topic_review=91'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(element.textContent).toContain('research is blocked');
    expect(element.querySelector<HTMLInputElement>('#research-topic')!.value).toBe('');
    expect(element.querySelector<HTMLButtonElement>('button[type="submit"]')!.disabled).toBe(true);
    api.topicSourceCurrent = true;
    api.topicReviews = [{ ...api.topicReviews[0], id: 92, project_id: 10 }];
    await harness.navigateByUrl('/app/research/7/9?topic_review=92'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(element.textContent).toContain('research is blocked');
    expect(api.researchRequests).toHaveLength(1);
  });

  it('selects bounded attributed news separately and does not invent optional source demand', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const harness = await RouterTestingHarness.create('/app/topics/7/9');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const element = harness.routeNativeElement!;
    expect(element.textContent).toContain('Live provider readiness is unverified');
    expect(element.textContent).toContain('Official Trends remains alpha');
    const checkbox = element.querySelector<HTMLInputElement>('#topic-news')!;
    checkbox.checked = true; checkbox.dispatchEvent(new Event('change')); harness.fixture.detectChanges();
    const form = checkbox.closest('form')!;
    form.querySelector<HTMLSelectElement>('#topic-news-phrase')!.value = 'local service news';
    form.querySelector<HTMLSelectElement>('#topic-news-publisher')!.value = 'https://research-source.example.invalid';
    form.querySelector<HTMLSelectElement>('#topic-news-window')!.value = '7';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.topicDiscoveryInputs[0]['news']).toEqual({ phrase: 'local service news', publisher_origin: 'https://research-source.example.invalid', days: 7 });
    expect(api.topicDiscoveryInputs[0]['feeds']).toEqual([]);
    expect(element.querySelector<HTMLAnchorElement>('a[href="https://www.gdeltproject.org/"]')?.rel).toContain('noreferrer');
    await harness.navigateByUrl('/app/topics/8/9'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.querySelector('#topic-news')).toBeNull();
  });

  it('keeps selected research sources private and clears evidence on project switch', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const harness = await RouterTestingHarness.create('/app/research/7/9');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const element = harness.routeNativeElement!;
    expect(element.textContent).toContain('Active project:');
    const form = element.querySelector<HTMLFormElement>('form')!;
    form.querySelector<HTMLInputElement>('#research-topic')!.value = 'Selected fixture topic';
    form.querySelector<HTMLSelectElement>('#research-language')!.value = 'en';
    form.querySelector<HTMLTextAreaElement>('#research-urls')!.value = 'https://research-source.example.invalid/page';
    form.querySelector<HTMLSelectElement>('#research-model')!.value = '30';
    form.querySelector<HTMLSelectElement>('#research-model')!.dispatchEvent(new Event('change'));
    harness.fixture.detectChanges();
    form.querySelector<HTMLSelectElement>('#research-account')!.value = '31';
    form.querySelector<HTMLInputElement>('#research-cost')!.value = '0.01';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.researchRequests[0]['source_urls']).toEqual(['https://research-source.example.invalid/page']);
    Array.from(element.querySelectorAll<HTMLButtonElement>('button'))
      .find((button) => button.textContent?.includes('Refresh this job'))!.click();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(element.textContent).toContain('Evidence is provisional.');
    expect(element.textContent).toContain('requires human review');
    await harness.navigateByUrl('/app/research/8/9');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).not.toContain('Evidence is provisional.');
  });

  it('shows source-linked unapproved briefs and clears content on project switch', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.researchJob = { id: 72, project_id: 9, topic: 'Human-selected topic', status: 'succeeded',
      updated_at: '2026-09-30T10:00:00Z' };
    api.actionRows = [{ action_id: 'a64070a5-91a1-4198-9556-651ab00c11bc', revision: 2,
      state: 'accepted', source_current: true, action_kind: 'refresh', source_type: 'intent', source_id: 1,
      affected_urls: ['https://example.invalid/page'] }];
    const harness = await RouterTestingHarness.create('/app/briefs/7/9');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const element = harness.routeNativeElement!;
    expect(element.textContent).toContain('Active project');
    const form = element.querySelector<HTMLFormElement>('form')!;
    form.querySelector<HTMLSelectElement>('#brief-research')!.value = '72';
    form.querySelector<HTMLSelectElement>('#brief-action')!.value = 'a64070a5-91a1-4198-9556-651ab00c11bc';
    form.querySelector<HTMLTextAreaElement>('#brief-titles')!.value = 'Human title';
    form.querySelector<HTMLTextAreaElement>('#brief-angle')!.value = 'Human reviewer angle';
    form.querySelector<HTMLTextAreaElement>('#brief-outline')!.value = 'Human heading';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.briefInputs[0]['research_job_id']).toBe(72);
    expect(element.textContent).toContain('Evidence is provisional.');
    expect(element.textContent).toContain('Verify this claim independently.');
    await harness.navigateByUrl('/app/briefs/8/9');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).not.toContain('Evidence is provisional.');
  });

  it.each(['en', 'tr'] as const)('keeps studio markup inert, binds revision commands, preserves rejected text and clears foreign routes (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    api.briefRows = [{ id: 75, project_id: 9, research_job_id: 72, created_at: '2026-09-30T00:00:00Z' }];
    const harness = await RouterTestingHarness.create('/app/content/7/9');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const element = harness.routeNativeElement!;
    expect(element.querySelector('section')?.getAttribute('lang')).toBe(language);
    expect(element.querySelector('h1')?.textContent).toBe(language === 'tr' ? 'Özel içerik stüdyosu' : 'Private content studio');
    let form = element.querySelector<HTMLFormElement>('form')!;
    form.querySelector<HTMLSelectElement>('#content-brief')!.value = '75';
    form.querySelector<HTMLInputElement>('#content-title-input')!.value = 'Human draft';
    form.querySelector<HTMLTextAreaElement>('#content-body')!.value = '<script>untrusted()</script>';
    form.querySelector<HTMLTextAreaElement>('#content-reason')!.value = 'Manual text for review.';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.contentInputs[0]['state']).toBe('draft');
    expect(element.querySelector('pre')?.textContent).toBe('<script>untrusted()</script>');
    expect(element.querySelector('script')).toBeNull();
    expect(element.textContent).toContain('Unverified source interpretation');
    expect(element.querySelector('a[href="https://source.example.invalid/article"]')).not.toBeNull();
    form = element.querySelector<HTMLFormElement>('form')!;
    const state = form.querySelector<HTMLSelectElement>('#content-state')!;
    state.value = 'review'; state.dispatchEvent(new Event('change', { bubbles: true }));
    form.querySelector<HTMLTextAreaElement>('#content-reason')!.value = 'Review exact current text.';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.contentInputs[1]['expected_revision']).toBe(1);
    api.contentStatus = 409;
    form = element.querySelector<HTMLFormElement>('form')!;
    form.querySelector<HTMLTextAreaElement>('#content-body')!.value = 'Unsaved correction';
    form.querySelector<HTMLTextAreaElement>('#content-reason')!.value = 'Keep correction after rejection.';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(form.querySelector<HTMLTextAreaElement>('#content-body')!.value).toBe('Unsaved correction');
    expect(element.querySelector('#content-save-error')?.getAttribute('role')).toBe('alert');
    await vi.waitFor(() => expect(document.activeElement?.id).toBe('content-save-error'));
    expect(element.querySelector('#content-save-error')?.textContent).toContain(language === 'tr' ? 'Girdinizi koruyun' : 'Keep your input');
    const compare = Array.from(element.querySelectorAll<HTMLButtonElement>('button')).find((button) => button.textContent?.includes(language === 'tr' ? 'Sürümü karşılaştırın: 1' : 'Compare revision 1'))!;
    compare.click(); harness.fixture.detectChanges();
    expect(element.textContent).toContain(language === 'tr' ? 'Karşılaştırılan sürüm 1' : 'Compared revision 1');
    await harness.navigateByUrl('/app/content/8/9');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).not.toContain('Unverified source interpretation');
    expect(harness.routeNativeElement?.querySelector('textarea')).toBeNull();
  });

  it('queues source-grounded generation with explicit model budget and clears job data on foreign studio routes', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.briefRows = [{ id: 75, project_id: 9, research_job_id: 72, created_at: '2026-09-30T00:00:00Z' }];
    const harness = await RouterTestingHarness.create('/app/content/7/9');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const element = harness.routeNativeElement!;
    const form = element.querySelector<HTMLFormElement>('section[aria-labelledby="content-generation-title"] form')!;
    expect(form).not.toBeNull();
    form.querySelector<HTMLSelectElement>('#generation-brief')!.value = '75';
    const model = form.querySelector<HTMLSelectElement>('#generation-model')!;
    model.value = model.options[1].value; model.dispatchEvent(new Event('change', { bubbles: true }));
    harness.fixture.detectChanges();
    const account = form.querySelector<HTMLSelectElement>('#generation-account')!;
    account.value = account.options[1].value;
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.generationInputs[0]['source_revision_id']).toBeNull();
    expect(api.generationInputs[0]['max_output_tokens']).toBe(512);
    expect(api.generationInputs[0]['platform']).toBe('');
    expect(element.textContent).toContain('One unverified draft queued');
    Array.from(element.querySelectorAll<HTMLButtonElement>('button')).find((button) => button.textContent?.includes('Refresh this generation'))!.click();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(element.textContent).toContain('unverified_draft_human_review_required');
    await harness.navigateByUrl('/app/content/8/9');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).not.toContain('unverified_draft_human_review_required');
  });

  it.each(['en', 'tr'] as const)('starts only a bounded first-audit crawl and shows actual candidates without inventing three findings (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    const harness = await RouterTestingHarness.create('/app/first-audit/7/9');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const element = harness.routeNativeElement!;
    const component = harness.routeDebugElement!.componentInstance;
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Bütçeli ilk proje denetimi — OrganicSEOOps' : 'Budgeted first project audit — OrganicSEOOps');
    expect(element.textContent).toContain(language === 'tr' ? 'listeyi doldurmak için hiçbir şey uydurulmaz' : 'nothing is fabricated to fill a list');
    expect(element.querySelector('[aria-labelledby="first-audit-title"]')?.getAttribute('lang')).toBe(language);
    expect(element.querySelector('h1')?.textContent).toBe(language === 'tr' ? 'İlk proje denetimi: eylemden önce kanıt' : 'First project audit: evidence before action');
    expect(element.querySelector('p span')?.getAttribute('lang')).toBe('');
    expect(element.querySelector('label[for="first-page-budget"]')?.textContent).toContain('1–5');
    const form = element.querySelector<HTMLFormElement>('form')!;
    form.querySelector<HTMLInputElement>('#first-page-budget')!.value = '2';
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Budgeted first project audit — OrganicSEOOps' : 'Bütçeli ilk proje denetimi — OrganicSEOOps');
    expect(element.querySelector('form')).toBe(form); expect(form.querySelector<HTMLInputElement>('#first-page-budget')!.value).toBe('2');
    expect(api.firstAuditRequests).toEqual([]);
    component.productLanguage.set(language); harness.detectChanges();
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.firstAuditRequests).toEqual([2]);
    expect(element.textContent).toContain(language === 'tr' ? 'Denetim 77' : 'Audit 77');
    await component.refresh(77); harness.detectChanges();
    expect(element.textContent).toContain('Fetch project page');
    expect(element.textContent).toContain('50%');
    const retry = vi.spyOn(api, 'retryFirstProjectAudit');
    retry.mockRejectedValueOnce(new Error('uncertain response'));
    await component.retry(77); expect(component.message()).toContain('outcome unavailable');
    const key = retry.mock.calls[0][3];
    const next = { ...api.firstAuditJob!, id: 78, status: 'queued', steps: [], attempted_units: 0 };
    retry.mockResolvedValueOnce({ status: 202, body: { project_id: 9, job: next } });
    await component.retry(77); harness.detectChanges();
    expect(retry.mock.calls[1]).toEqual([7, 9, 77, key]);
    expect(component.crawls().map((job: { id: number }) => job.id)).toEqual([78, 77]);
    let resolveRetry!: (result: ApiResult) => void;
    retry.mockImplementationOnce(() => new Promise(resolve => { resolveRetry = resolve; }));
    const pendingRetry = component.retry(77);
    await harness.navigateByUrl('/app/first-audit/8/9');
    resolveRetry({ status: 202, body: { project_id: 9, job: next } }); await pendingRetry;
    expect(component.crawls()).toEqual([]);
    await harness.navigateByUrl('/app/first-audit/7/9'); await harness.fixture.whenStable();
    retry.mockRestore();
    api.firstAuditCandidate = { id: 88, subject: 'Synthetic observed title', detector: 'title_candidate',
      source_id: 8, confidence: 'source_limited', priority: 'unreviewed', detected_at: '2026-09-30T10:00:00Z' };
    await harness.routeDebugElement?.componentInstance.load();
    harness.fixture.detectChanges();
    expect(element.textContent).toContain('Synthetic observed title');
    expect(element.querySelector('section[aria-labelledby="first-findings-title"] li span')?.getAttribute('lang')).toBe('');
    expect(element.querySelectorAll('section[aria-labelledby="first-findings-title"] li span')[1]?.getAttribute('lang')).toBe('en');
    expect(element.querySelectorAll('section[aria-labelledby="first-findings-title"] li').length).toBe(1);
    await harness.navigateByUrl('/app/first-audit/8/9');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).not.toContain('Synthetic observed title');
    const preference = vi.spyOn(api, 'productLanguage');
    preference.mockResolvedValue({ status: 200, body: { language: 'tr', current_ui_language: 'tr', current_email_language: 'tr' } });
    await harness.navigateByUrl('/account/login'); await harness.fixture.whenStable(); harness.detectChanges();
    const nextTitle = TestBed.inject(Title).getTitle(); component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); TestBed.tick();
    expect(TestBed.inject(Title).getTitle()).toBe(nextTitle);
    await harness.navigateByUrl('/app/first-audit/7/9');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe('Budgeted first project audit — OrganicSEOOps');
    expect(harness.routeNativeElement?.querySelector('[aria-labelledby="first-audit-title"]')?.getAttribute('lang')).toBe('en');
    preference.mockRejectedValue(new Error('private preference error'));
    await harness.navigateByUrl('/account/login'); await harness.navigateByUrl('/app/first-audit/7/9');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe('Budgeted first project audit — OrganicSEOOps');
    expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('First project audit: evidence before action');
    expect(harness.routeNativeElement?.textContent).not.toContain('private preference error'); preference.mockRestore();
    const buildEnvironment = environment as { production: boolean }, previous = buildEnvironment.production;
    try {
      buildEnvironment.production = true;
      await harness.navigateByUrl('/account/login'); await harness.navigateByUrl('/app/first-audit/7/9');
      await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(harness.routeDebugElement!.componentInstance.productLanguage()).toBe(language);
      expect(TestBed.inject(Title).getTitle()).toBe('Budgeted first project audit — OrganicSEOOps');
    expect(harness.routeNativeElement?.querySelector('[aria-labelledby="first-audit-title"]')?.getAttribute('lang')).toBe('en');
      expect(TestBed.inject(Title).getTitle()).toBe('Budgeted first project audit — OrganicSEOOps');
    expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('First project audit: evidence before action');
      expect(api.firstAuditRequests).toEqual([2]);
    } finally { buildEnvironment.production = previous; }

  });

  it('rejects array first audit launch roles and job handlers in current rows and refreshed status', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const original = structuredClone(api.onboardingResult), project = original.body['project'] as Record<string, unknown>;
    const job = { id: 77, handler: 'crawl_site', status: 'queued', error_category: '', estimated_units: 3,
      attempted_units: 0, cancel_requested: false, created_at: '2026-09-30T10:00:00Z', updated_at: '2026-09-30T10:00:00Z' };
    api.firstAuditJob = job;
    const harness = await RouterTestingHarness.create('/app/first-audit/7/9'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    expect(component.canLaunch()).toBe(true); expect(component.crawls()).toHaveLength(1);
    for (const role of ['owner', 'admin', 'member', 'viewer']) {
      api.onboardingResult = { ...original, body: { ...original.body, project: { ...project, role: [role] } } };
      await component.load(); expect(component.canLaunch()).toBe(false); expect(component.error()).not.toBe(''); expect(component.crawls()).toEqual([]);
      api.onboardingResult = { ...original, body: { ...original.body, project: { ...project, role } } };
      await component.load(); expect(component.error()).toBe(''); expect(component.canLaunch()).toBe(role !== 'viewer');
    }
    api.onboardingResult = original;
    const refresh = vi.spyOn(api, 'firstProjectAuditJob');
    for (const handler of ['crawl_site', 'audit_performance']) {
      api.firstAuditJob = { ...job, handler: [handler] }; await component.load(); expect(component.crawls()).toEqual([]);
      api.firstAuditJob = { ...job, handler }; await component.load(); expect(component.crawls()).toHaveLength(1);
      refresh.mockResolvedValueOnce({ status: 200, body: { project_id: 9, job: { ...job, handler: [handler] } } });
      await component.refresh(77); expect(component.crawls()[0].handler).toBe(handler);
      expect(component.message()).toContain('Crawl status unavailable');
    }
    api.firstAuditJob = { ...job, retry_supported: ['true'] };
    await component.load(); expect(component.crawls()).toEqual([]);
    api.firstAuditJob = { ...job, steps: [{ sequence: 1, name: 'Fetch', status: 'failed',
      progress_percent: 101, error_category: '' }] };
    await component.load(); expect(component.crawls()).toEqual([]);
    expect(refresh.mock.calls).toHaveLength(2); expect(api.firstAuditRequests).toEqual([]); refresh.mockRestore();
  });

  it.each(['en', 'tr'] as const)('deliberately inspects exact private bounded history without starting work or implying first value (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    const harness = await RouterTestingHarness.create('/app/first-audit/7/9');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const element = harness.routeNativeElement!;
    expect(api.firstAuditHistoryReads).toEqual([]);
    element.querySelector<HTMLButtonElement>('section[aria-labelledby="first-completion-title"] button')!.click();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.firstAuditHistoryReads).toEqual([[7, 9]]);
    expect(api.firstAuditRequests).toEqual([]);
    expect(element.textContent).toContain(language === 'tr' ? 'Kaydedilmiş geçmiş denetim 77' : 'Recorded historical audit 77');
    expect(element.textContent).toContain(language === 'tr' ? 'kaynağı yeniden kullanmak için güncel izin' : 'not current permission to reuse its source');
    expect(element.textContent).toContain(language === 'tr' ? 'kabul edilmiş ilk değer sonucu' : 'an accepted first-value result');
    expect(element.textContent).toContain('2026-09-30T10:00:00Z');
    expect(element.querySelector('code')?.textContent).toBe('a'.repeat(64));
    await harness.routeDebugElement!.componentInstance.load();
    harness.fixture.detectChanges();
    expect(element.textContent).not.toContain(language === 'tr' ? 'Kaydedilmiş geçmiş denetim 77' : 'Recorded historical audit 77');
    const { method, organization_id, project_id, scope } = api.firstAuditHistoryResult.body;
    for (const state of ['unknown', 'not_observed_for_project']) {
      api.firstAuditHistoryResult = { status: 200, body: { method, organization_id, project_id, scope, state } };
      await harness.routeDebugElement!.componentInstance.inspectCompletion(); harness.fixture.detectChanges();
      expect(element.querySelector('code')).toBeNull();
      expect(element.textContent).toContain(state === 'unknown'
        ? language === 'tr' ? 'Geçmiş izleme kapsamı bilinmiyor' : 'Historical tracking coverage is unknown'
        : language === 'tr' ? 'Diğer projenin geçmişi açıklanmaz' : 'Other-project history is not disclosed');
    }
  });

  it('rejects malformed, wrong-scope and denied bounded history without retaining prior source data', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const original = structuredClone(api.firstAuditHistoryResult.body);
    const harness = await RouterTestingHarness.create('/app/first-audit/7/9');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const component = harness.routeDebugElement!.componentInstance;
    const changes: Record<string, unknown>[] = [
      { method: 'other' }, { scope: 'current' }, { organization_id: 8 }, { project_id: 10 }, { state: 'succeeded' },
      { job_id: 0 }, { source_digest: 'invalid' }, { observed_at: '2026-09-30T10:00:00' },
      { observed_at: '2099-01-01T10:00:00Z' }, { observed_at: '2026-09-28T10:00:00Z' },
      { page_limit: 6 }, { pages_observed: 4 }, { successful_html_pages: 0 }, { successful_html_pages: 3 },
      { coverage: 'complete_site' }, { discovery_truncated: 'false' }, { robots_status: 'unavailable' },
      { robots_status: ['available'] }, { robots_status: ['missing'] },
      { raw_body: 'PRIVATE_PAYLOAD' }, { state: 'unknown' },
    ];
    for (const change of changes) {
      api.firstAuditHistoryResult = { status: 200, body: original };
      await component.inspectCompletion();
      expect(component.completion()?.job_id).toBe(77);
      api.firstAuditHistoryResult = { status: 200, body: { ...original, ...change } };
      await component.inspectCompletion(); harness.fixture.detectChanges();
      expect(component.completion()).toBeNull();
      expect(harness.routeNativeElement!.textContent).toContain('Saved completion unavailable or needs review');
      expect(harness.routeNativeElement!.textContent).not.toContain('PRIVATE_PAYLOAD');
    }
    const { method, organization_id, project_id, scope } = original;
    for (const state of ['unknown', 'not_observed_for_project']) {
      api.firstAuditHistoryResult = { status: 200, body: { method, organization_id, project_id, scope, state: [state] } };
      await component.inspectCompletion(); expect(component.completion()).toBeNull();
    }
    api.firstAuditHistoryResult = { status: 403, body: original };
    await component.inspectCompletion(); expect(component.completion()).toBeNull();
  });

  it('clears late history on project refresh, demo, route scope and component destruction', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const harness = await RouterTestingHarness.create('/app/first-audit/7/9');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const component = harness.routeDebugElement!.componentInstance;
    let resolve!: (value: ApiResult) => void;
    api.firstAuditHistoryHandler = () => new Promise((done) => { resolve = done; });
    const pending = component.inspectCompletion();
    api.firstAuditDemo = true;
    await component.load();
    resolve(api.firstAuditHistoryResult); await pending; harness.fixture.detectChanges();
    expect(component.completion()).toBeNull();
    expect(harness.routeNativeElement!.querySelector('section[aria-labelledby="first-completion-title"]')).toBeNull();
    await component.inspectCompletion(); expect(api.firstAuditHistoryReads).toHaveLength(1);
    api.firstAuditDemo = false; await component.load();
    const scoped = component.inspectCompletion();
    await harness.navigateByUrl('/app/first-audit/8/9');
    resolve(api.firstAuditHistoryResult); await scoped;
    expect(component.completion()).toBeNull();
    await harness.navigateByUrl('/app/first-audit/7/9');
    await harness.fixture.whenStable();
    const current = harness.routeDebugElement!.componentInstance;
    const destroyed = current.inspectCompletion();
    await harness.navigateByUrl('/account/login');
    resolve(api.firstAuditHistoryResult); await destroyed;
    expect(current.completion()).toBeNull();
    expect(current.historyLoading()).toBe(false);
  });

  it.each(['en', 'tr'] as const)('deliberately inspects original server timing with exact microsecond rounding and no acknowledgment or new work (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    const harness = await RouterTestingHarness.create('/app/first-audit/7/9'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const component = harness.routeDebugElement!.componentInstance, element = harness.routeNativeElement!;
    expect(api.usefulnessTimingReads).toEqual([]);
    Array.from(element.querySelectorAll<HTMLButtonElement>('button')).find(button => button.textContent?.includes(language === 'tr' ? 'Kaydedilmiş sunucu yararlılık zamanlamasını' : 'Inspect saved server usefulness timing'))!.click();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.usefulnessTimingReads).toEqual([[7, 9]]);
    const section = element.querySelector('section[aria-labelledby="first-usefulness-timing-title"]')!;
    expect(section.textContent).toContain(language === 'tr' ? '332 tam milisaniye, aşağı yuvarlanmış' : '332 whole milliseconds, rounded down');
    expect(section.textContent).toContain('2026-09-30T10:00:00.123900Z');
    expect(section.textContent).toContain(language === 'tr' ? 'denetim çalışma süresi' : 'not audit runtime'); expect(section.textContent).toContain(language === 'tr' ? 'gerçek işletme değerine ulaşma süresi' : 'actual time-to-business-value');
    expect(api.usefulnessPosts).toEqual([]); expect(api.firstAuditRequests).toEqual([]);
    await component.load(); expect(component.usefulnessTiming()).toBeNull();
  });

  it('rejects timing scope, method, original-date, exact-duration and extra fields, preserving unknown without a duration', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const harness = await RouterTestingHarness.create('/app/first-audit/7/9'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance, original = structuredClone(api.usefulnessTimingResult);
    for (const delta of [{ method: 'wrong' }, { project_id: 10 }, { organization_id: 8 }, { precision: 'approximate' },
      { elapsed_milliseconds: 333 }, { elapsed_milliseconds: -1 }, { elapsed_milliseconds: 332.2 }, { elapsed_milliseconds: Number.MAX_SAFE_INTEGER + 1 },
      { tracking_started_at: '2026-09-30T10:00:00.500000Z' }, { acknowledged_at: '2099-01-01T10:00:00Z' },
      { acknowledged_at: '2026-09-30T10:00:00' }, { source_digest: 'bad' }, { state: 'unknown' }, { raw_body: 'PRIVATE_TIMING' }]) {
      api.usefulnessTimingResult = { status: 200, body: { ...original.body, ...delta } };
      await component.inspectUsefulnessTiming(); expect(component.usefulnessTiming()).toBeNull();
    }
    const { tracking_started_at: _start, acknowledged_at: _end, source_digest: _digest, elapsed_milliseconds: _elapsed, ...unknown } = original.body;
    for (const state of ['unknown', 'not_observed_for_project']) {
      api.usefulnessTimingResult = { status: 200, body: { ...unknown, state: [state] } };
      await component.inspectUsefulnessTiming(); expect(component.usefulnessTiming()).toBeNull();
      api.usefulnessTimingResult = { status: 200, body: { ...unknown, state } };
      await component.inspectUsefulnessTiming(); expect(component.usefulnessTiming()?.state).toBe(state);
      expect(component.usefulnessTiming()?.elapsed_milliseconds).toBeUndefined();
    }
    api.usefulnessTimingResult = { status: 403, body: original.body };
    await component.inspectUsefulnessTiming(); harness.fixture.detectChanges();
    expect(component.usefulnessTiming()).toBeNull(); expect(harness.routeNativeElement!.textContent).not.toContain('PRIVATE_TIMING');
  });

  it('clears delayed timing on final demo, refresh, changed scope and destruction without replay or late context reads', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const harness = await RouterTestingHarness.create('/app/first-audit/7/9'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    let resolve!: (value: ApiResult) => void;
    api.usefulnessTimingHandler = () => new Promise(done => { resolve = done; });
    const pending = component.inspectUsefulnessTiming();
    const config = api.onboardingResult.body['configuration'] as Record<string, unknown>;
    config['source_choice'] = 'synthetic_demo'; resolve(api.usefulnessTimingResult); await pending;
    expect(component.usefulnessTiming()).toBeNull();
    api.firstAuditDemo = true; await component.load(); const reads = api.usefulnessTimingReads.length;
    await component.inspectUsefulnessTiming(); expect(api.usefulnessTimingReads).toHaveLength(reads);
    api.firstAuditDemo = false; config['source_choice'] = 'skip'; await component.load();
    const refreshed = component.inspectUsefulnessTiming(); await component.load(); resolve(api.usefulnessTimingResult); await refreshed;
    expect(component.usefulnessTiming()).toBeNull();
    const scoped = component.inspectUsefulnessTiming(); await harness.navigateByUrl('/app/first-audit/8/9'); resolve(api.usefulnessTimingResult); await scoped;
    expect(component.usefulnessTiming()).toBeNull();
    await harness.navigateByUrl('/app/first-audit/7/9'); await harness.fixture.whenStable();
    const current = harness.routeDebugElement!.componentInstance;
    const destroyed = current.inspectUsefulnessTiming(); await harness.navigateByUrl('/account/login'); resolve(api.usefulnessTimingResult); await destroyed;
    expect(current.usefulnessTiming()).toBeNull(); expect(current.timingLoading()).toBe(false); expect(current.busy()).toBe(false);
    expect(api.usefulnessPosts).toEqual([]); expect(api.firstAuditRequests).toEqual([]);
  });

  it.each(['en', 'tr'] as const)('deliberately inspects a frozen accepted opportunity action with current source and original dates only (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    api.actionRows = [api.auditActionRow];
    const harness = await RouterTestingHarness.create('/app/actions/7/9');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const element = harness.routeNativeElement!;
    expect(api.auditActionReads).toEqual([]);
    Array.from(element.querySelectorAll<HTMLButtonElement>('button')).find((button) => button.textContent?.includes(language === 'tr' ? 'sınırlı denetim kaynağını' : "accepted action's bounded audit source"))!.click();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.auditActionReads).toEqual([{ organizationId: 7, projectId: 9, actionId: api.auditActionRow['action_id'], revision: 2 }]);
    expect(element.textContent).toContain(language === 'tr' ? 'İşaretlenmiş denetim 77 tamamlanma tarihi 2026-09-30T10:00:00Z' : 'Marked audit 77 completed 2026-09-30T10:00:00Z');
    expect(element.textContent).toContain(language === 'tr' ? 'müşteri yararlılığı, kabul edilmiş ilk değer' : 'does not establish customer usefulness, accepted first value');
    expect(element.textContent).toContain(language === 'tr' ? 'eylem incelemesi 46 kabul tarihi 2026-09-30T10:05:00Z' : 'action review 46 accepted 2026-09-30T10:05:00Z');
    expect(element.querySelector('#action-audit-source-title')?.textContent).toBe(language === 'tr' ? 'Güncel sınırlı denetim ve insan kabulü kanıtları' : 'Current bounded audit and human acceptance evidence');
    expect(element.querySelector('[aria-labelledby="action-audit-source-title"] [lang="en"]')?.textContent).toBe((api.auditActionResult.body['source'] as Record<string, unknown>)['detector']);
    expect(element.textContent).toContain(language === 'tr' ? 'sitenin tamamı veya sorunsuz site sonucu değildir' : 'not the complete site or a clean-site result');
    expect(api.savedActions).toEqual([]);
    expect(api.firstAuditRequests).toEqual([]);
    expect(element.querySelectorAll('section[aria-labelledby="action-audit-source-title"] code').length).toBe(3);
    await harness.routeDebugElement!.componentInstance.load(); harness.fixture.detectChanges();
    expect(element.querySelector('section[aria-labelledby="action-audit-source-title"]')).toBeNull();
  });

  it('withholds malformed or mismatched audit-action source and rechecks exact latest human state', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.actionRows = [api.auditActionRow];
    const harness = await RouterTestingHarness.create('/app/actions/7/9');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const component = harness.routeDebugElement!.componentInstance;
    const original = structuredClone(api.auditActionResult);
    const source = original.body['source'] as Record<string, unknown>;
    for (const change of [{ job_id: 0 }, { method: 'other' }, { project_id: 10 }, { decision_digest: 'bad' },
      { audit_completed_at: '2026-09-30T10:00:00' }, { diagnostics_observed_at: '2099-01-01T10:00:00Z' },
      { finding_detected_at: '2026-09-29T10:00:00Z' }, { opportunity_id: 99 },
      { action_accepted_at: '2026-09-30T10:06:00Z' }, { detector: 'arbitrary' }, { first_value: 'accepted' },
      { raw_body: 'PRIVATE_PAYLOAD' }]) {
      api.auditActionResult = { status: 200, body: { ...original.body, source: { ...source, ...change } } };
      await component.inspectAuditSource(component.actions()[0]); harness.fixture.detectChanges();
      expect(component.auditSource()).toBeNull();
      expect(harness.routeNativeElement!.textContent).not.toContain('PRIVATE_PAYLOAD');
    }
    api.auditActionResult = { status: 200, body: { ...original.body, revision: 3 } };
    await component.inspectAuditSource(component.actions()[0]); expect(component.auditSource()).toBeNull();
    api.auditActionResult = { status: 403, body: original.body };
    await component.inspectAuditSource(component.actions()[0]); expect(component.auditSource()).toBeNull();
    api.auditActionHandler = async () => {
      api.actionRows = [{ ...api.auditActionRow, state: 'proposed', revision: 3 }];
      return original;
    };
    await component.inspectAuditSource(component.actions()[0]); harness.fixture.detectChanges();
    expect(component.auditSource()).toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain('Current accepted audit source unavailable or changed');
    expect(api.savedActions).toEqual([]);
  });

  it('clears delayed audit-action source on demo, scope and destroyed component without replay', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.actionRows = [api.auditActionRow];
    const harness = await RouterTestingHarness.create('/app/actions/7/9');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const component = harness.routeDebugElement!.componentInstance;
    let resolve!: (value: ApiResult) => void;
    api.auditActionHandler = () => new Promise((done) => { resolve = done; });
    const waitForSource = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); };
    const pending = component.inspectAuditSource(component.actions()[0]);
    await waitForSource();
    const config = api.onboardingResult.body['configuration'] as Record<string, unknown>;
    config['source_choice'] = 'synthetic_demo';
    resolve(api.auditActionResult); await pending; harness.fixture.detectChanges();
    expect(component.auditSource()).toBeNull();
    await component.load(); harness.fixture.detectChanges();
    const reads = api.auditActionReads.length;
    await component.inspectAuditSource(component.actions()[0]);
    expect(api.auditActionReads).toHaveLength(reads);
    config['source_choice'] = 'skip'; await component.load();
    const switched = component.inspectAuditSource(component.actions()[0]);
    await waitForSource();
    await harness.navigateByUrl('/app/actions/8/9');
    resolve(api.auditActionResult); await switched;
    expect(component.auditSource()).toBeNull();
    await harness.navigateByUrl('/app/actions/7/9'); await harness.fixture.whenStable();
    const current = harness.routeDebugElement!.componentInstance;
    const destroyed = current.inspectAuditSource(current.actions()[0]);
    await waitForSource();
    await harness.navigateByUrl('/account/login');
    resolve(api.auditActionResult); await destroyed;
    expect(current.auditSource()).toBeNull();
    expect(current.auditSourceLoading()).toBe(false);
    expect(api.savedActions).toEqual([]);
  });

  it('rejects array action source types and retained usefulness state or action metadata', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const missing = structuredClone(api.usefulnessHistory());
    api.actionRows = [api.auditActionRow];
    const harness = await RouterTestingHarness.create('/app/actions/7/9'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    for (const sourceType of ['intent', 'opportunity']) {
      api.actionRows = [{ ...api.auditActionRow, source_type: [sourceType] }]; await component.load();
      expect(component.actions()).toEqual([]); expect(component.error()).not.toBe('');
    }
    api.actionRows = [api.auditActionRow]; await component.load();
    await component.prepareUsefulness(component.actions()[0]); component.usefulnessChecked.set(true);
    await component.acknowledgeUsefulness();
    const original = structuredClone(api.usefulnessSaved!);
    expect(component.usefulnessHistory()?.['state']).toBe('recorded');
    for (const state of ['unknown', 'not_observed_for_project']) {
      api.usefulnessSaved = { ...missing, state: [state] }; await component.load(); await component.inspectUsefulnessHistory();
      expect(component.usefulnessHistory()).toBeNull(); expect(component.usefulnessError()).not.toBe('');
    }
    for (const actionKind of ['keep', 'refresh', 'merge', 'redirect', 'retire', 'create']) {
      const source = { ...original['source'] as Record<string, unknown>, action_kind: [actionKind] };
      api.usefulnessSaved = { ...original, source, source_digest: fixtureDigest(source) };
      await component.load(); await component.inspectUsefulnessHistory();
      expect(component.usefulnessHistory()).toBeNull(); expect(component.usefulnessError()).not.toBe('');
    }
    api.usefulnessSaved = original; await component.load(); await component.inspectUsefulnessHistory();
    expect(component.usefulnessHistory()?.['acknowledged_at']).toBe(original['acknowledged_at']);
    expect(api.usefulnessPosts).toHaveLength(1);
  });

  it.each(['en', 'tr'] as const)('requires deliberate current-source inspection and a native unchecked usefulness checkbox before any POST (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    api.actionRows = [api.auditActionRow];
    const harness = await RouterTestingHarness.create('/app/actions/7/9');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const component = harness.routeDebugElement!.componentInstance, element = harness.routeNativeElement!;
    expect(api.usefulnessReads).toEqual([]); expect(api.usefulnessPosts).toEqual([]);
    const section = () => element.querySelector('section[aria-labelledby="audit-usefulness-title"]')!;
    Array.from(element.querySelectorAll<HTMLButtonElement>('button')).find(button => button.textContent?.includes(language === 'tr' ? 'tam olarak bu eylemi incele' : 'Review this exact action'))!.click();
    await vi.waitFor(() => expect(component.usefulnessChallenge()).not.toBeNull());
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const checkbox = section().querySelector<HTMLInputElement>('input[type="checkbox"]')!;
    expect(checkbox.checked).toBe(false);
    await component.acknowledgeUsefulness(); expect(api.usefulnessPosts).toEqual([]);
    expect(section().querySelector('h2')?.textContent).toBe(language === 'tr' ? 'İsteğe bağlı öznel yararlılık beyanı' : 'Optional subjective usefulness acknowledgment');
    expect(section().textContent).toContain(language === 'tr' ? 'web sitesi değişikliğini onaylamaz' : 'does not approve a website change');
    expect(Array.from(section().querySelectorAll('[lang=""]')).some(node => node.textContent === api.auditActionRow['acceptance_criteria'])).toBe(true);
    checkbox.checked = true; checkbox.dispatchEvent(new Event('change')); harness.fixture.detectChanges();
    const frozen = component.usefulnessChallenge(), readCount = api.usefulnessReads.length;
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(component.usefulnessChallenge()).toBe(frozen); expect(component.usefulnessChecked()).toBe(true);
    expect(checkbox.checked).toBe(true); expect(api.usefulnessReads).toHaveLength(readCount); expect(api.usefulnessPosts).toEqual([]);
    component.productLanguage.set(language); harness.fixture.detectChanges();
    Array.from(section().querySelectorAll<HTMLButtonElement>('button')).find(button => button.textContent?.includes(language === 'tr' ? 'Bu yararlılık beyanını kaydet' : 'Record this usefulness'))!.click();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.usefulnessPosts).toEqual([{ organizationId: 7, projectId: 9, actionId: api.auditActionRow['action_id'], revision: 2, proof: api.usefulnessProof }]);
    expect(api.usefulnessReads.filter(read => !read.actionId)).toHaveLength(1);
    expect(section().textContent).toContain(language === 'tr' ? 'İlk sunucu yararlılık beyanı' : 'First server usefulness acknowledgment');
    expect(section().textContent).toContain(language === 'tr' ? 'Özgün denetim 2026-09-30T10:00:00Z' : 'Original audit 2026-09-30T10:00:00Z');
    expect(element.textContent).not.toContain(api.usefulnessProof);
    expect(api.savedActions).toEqual([]); expect(api.firstAuditRequests).toEqual([]);
    await component.load(); expect(component.usefulnessHistory()).toBeNull();
  });

  it.each(['en', 'tr'] as const)('resolves lost usefulness responses with independent exact historical GET even after current action loss, never replaying (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    api.actionRows = [api.auditActionRow]; api.usefulnessLose = true;
    const harness = await RouterTestingHarness.create('/app/actions/7/9'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    await component.prepareUsefulness(component.actions()[0]); component.usefulnessChecked.set(true);
    await component.acknowledgeUsefulness(); expect(component.usefulnessUnknown()).toBe(true);
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'Yararlılık beyanının sonucu bilinmiyor' : 'Usefulness acknowledgment outcome unknown');
    const reads = api.usefulnessReads.length;
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(component.usefulnessUnknown()).toBe(true); expect(api.usefulnessReads).toHaveLength(reads); expect(api.usefulnessPosts).toHaveLength(1);
    component.productLanguage.set(language);
    api.actionRows = [{ ...api.auditActionRow, revision: 3, state: 'proposed' }];
    await component.lookupUsefulness();
    expect(component.usefulnessUnknown()).toBe(false); expect(component.usefulnessHistory()?.['state']).toBe('recorded');
    expect(api.usefulnessPosts).toHaveLength(1);
    expect(api.usefulnessReads).toHaveLength(2); expect(api.usefulnessReads[1].actionId).toBeUndefined();
    const originalDate = api.usefulnessSaved!['acknowledged_at'];
    await component.inspectUsefulnessHistory(); expect(component.usefulnessHistory()?.['acknowledged_at']).toBe(originalDate);
    expect(api.usefulnessPosts).toHaveLength(1);
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'Geçmiş beyan; bu kaynağı yeniden kullanmak için güncel izin' : 'Historical declaration, not current permission to reuse this source');
  });

  it('allows only a deliberate checked original-proof retry after negative history lookup without issuing another challenge', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.actionRows = [api.auditActionRow]; api.usefulnessDrop = true;
    const harness = await RouterTestingHarness.create('/app/actions/7/9'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    await component.prepareUsefulness(component.actions()[0]); component.usefulnessChecked.set(true);
    await component.acknowledgeUsefulness();
    await component.acknowledgeUsefulness(true); expect(api.usefulnessPosts).toHaveLength(1);
    await component.lookupUsefulness(); expect(component.usefulnessCanRetry()).toBe(true);
    await component.acknowledgeUsefulness(true); expect(api.usefulnessPosts).toHaveLength(1);
    api.usefulnessDrop = false; api.usefulnessProof = 'Different_new_proof:must_not_send';
    component.usefulnessChecked.set(true); await component.acknowledgeUsefulness(true);
    expect(api.usefulnessPosts).toHaveLength(2);
    expect(api.usefulnessPosts[1].proof).toBe(api.usefulnessPosts[0].proof);
    expect(api.usefulnessReads.filter(read => !!read.actionId)).toHaveLength(1);
    expect(component.usefulnessUnknown()).toBe(false);
  });

  it('never treats another actor or source declaration as its uncertain acknowledgment or enables replay from malformed history', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.actionRows = [api.auditActionRow]; api.usefulnessLose = true;
    const harness = await RouterTestingHarness.create('/app/actions/7/9'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    await component.prepareUsefulness(component.actions()[0]); component.usefulnessChecked.set(true); await component.acknowledgeUsefulness();
    const original = structuredClone(api.usefulnessSaved!);
    for (const delta of [{ declaration_digest: 'e'.repeat(64) }, { project_id: 10 }, { revision: 3 },
      { acknowledged_at: '2026-09-29T10:00:00Z' }, { tracking_started_at: '2026-09-30T10:06:00Z' },
      { acknowledged_at: '2026-09-30T10:06:00' }, { raw_body: 'PRIVATE_USEFULNESS_PAYLOAD' }]) {
      api.usefulnessSaved = { ...original, ...delta };
      await component.lookupUsefulness(); expect(component.usefulnessHistory()).toBeNull();
      expect(component.usefulnessCanRetry()).toBe(false); expect(component.usefulnessUnknown()).toBe(true);
      await component.acknowledgeUsefulness(true); expect(api.usefulnessPosts).toHaveLength(1);
    }
    api.usefulnessSaved = original; await component.lookupUsefulness();
    expect(component.usefulnessHistory()?.['acknowledged_at']).toBe(original['acknowledged_at']);
  });

  it('rejects malformed challenge actor, scope, digest, source and expiry with no command or proof display', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.actionRows = [api.auditActionRow];
    const harness = await RouterTestingHarness.create('/app/actions/7/9'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    for (const delta of [{ method: 'wrong' }, { acknowledgment_recorded: true }, { receipt_proof: 'private invalid proof' },
      { source_digest: 'a'.repeat(64) }, { expires_at: '2026-09-30T10:00:00Z' }, { expires_at: '2099-01-01T10:00:00Z' },
      { extra: 'PRIVATE_USEFULNESS_PAYLOAD' }]) {
      api.usefulnessHandler = async result => { Object.assign(result.body['challenge'] as object, delta); return result; };
      await component.prepareUsefulness(component.actions()[0]); expect(component.usefulnessChallenge()).toBeNull();
    }
    for (const delta of [{ acknowledging_actor_id: 8 }, { evidence: { ...api.auditActionResult.body['source'] as object, project_id: 10 } }]) {
      api.usefulnessHandler = async result => {
        const challenge = result.body['challenge'] as Record<string, unknown>;
        Object.assign(challenge['source'] as object, delta); challenge['source_digest'] = fixtureDigest(challenge['source']); return result;
      };
      await component.prepareUsefulness(component.actions()[0]); expect(component.usefulnessChallenge()).toBeNull();
    }
    harness.fixture.detectChanges(); expect(harness.routeNativeElement!.textContent).not.toContain('PRIVATE_USEFULNESS_PAYLOAD');
    expect(api.usefulnessPosts).toEqual([]);
    api.usefulnessHandler = undefined; await component.prepareUsefulness(component.actions()[0]);
    api.actionRows = [{ ...api.auditActionRow, revision: 3, acceptance_criteria: 'Changed decision' }];
    component.usefulnessChecked.set(true); await component.acknowledgeUsefulness(); expect(api.usefulnessPosts).toEqual([]);
    expect(component.usefulnessChallenge()).toBeNull();
  });

  it('clears late usefulness challenges and unknown proof on refresh, demo, route and destruction without replay', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.actionRows = [api.auditActionRow];
    const harness = await RouterTestingHarness.create('/app/actions/7/9'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    let resolve!: (value: ApiResult) => void, captured!: ApiResult;
    api.usefulnessHandler = result => { captured = result; return new Promise(done => { resolve = done; }); };
    const wait = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); };
    const pending = component.prepareUsefulness(component.actions()[0]); await wait();
    const config = api.onboardingResult.body['configuration'] as Record<string, unknown>;
    config['source_choice'] = 'synthetic_demo'; resolve(captured); await pending;
    expect(component.usefulnessChallenge()).toBeNull();
    await component.load(); const reads = api.usefulnessReads.length;
    await component.prepareUsefulness(component.actions()[0]); await component.inspectUsefulnessHistory();
    expect(api.usefulnessReads).toHaveLength(reads);
    config['source_choice'] = 'skip'; await component.load();
    const refreshed = component.prepareUsefulness(component.actions()[0]); await wait(); await component.load();
    resolve(captured); await refreshed; expect(component.usefulnessChallenge()).toBeNull();
    const scoped = component.prepareUsefulness(component.actions()[0]); await wait();
    await harness.navigateByUrl('/app/actions/8/9'); resolve(captured); await scoped;
    expect(component.usefulnessChallenge()).toBeNull();
    await harness.navigateByUrl('/app/actions/7/9'); await harness.fixture.whenStable();
    const current = harness.routeDebugElement!.componentInstance;
    api.usefulnessHandler = undefined; api.usefulnessLose = true;
    await current.prepareUsefulness(current.actions()[0]); current.usefulnessChecked.set(true); await current.acknowledgeUsefulness();
    expect(current.usefulnessUnknown()).toBe(true);
    api.usefulnessHandler = result => { captured = result; return new Promise(done => { resolve = done; }); };
    const destroyed = current.lookupUsefulness(); await wait(); await harness.navigateByUrl('/account/login');
    resolve(captured); await destroyed;
    expect(current.usefulnessHistory()).toBeNull(); expect(current.usefulnessUnknown()).toBe(false);
    expect(current.usefulnessCanRetry()).toBe(false); expect(current.busy()).toBe(false); expect(api.usefulnessPosts).toHaveLength(1);
  });

  it('preserves uncertainty after a postcommit conflict and refuses expired proof or current project role loss', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.actionRows = [api.auditActionRow];
    const harness = await RouterTestingHarness.create('/app/actions/7/9'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    api.usefulnessPostHandler = async result => ({ ...result, status: 409 });
    await component.prepareUsefulness(component.actions()[0]); component.usefulnessChecked.set(true);
    await component.acknowledgeUsefulness(); expect(component.usefulnessUnknown()).toBe(true);
    await component.lookupUsefulness(); expect(component.usefulnessUnknown()).toBe(false); expect(api.usefulnessPosts).toHaveLength(1);
    await component.load(); api.usefulnessDrop = true; api.usefulnessSaved = null; api.usefulnessPostHandler = undefined;
    await component.prepareUsefulness(component.actions()[0]);
    component.usefulnessChallenge().challenge.expires_at = '2026-09-30T10:00:00Z';
    component.usefulnessChecked.set(true); await component.acknowledgeUsefulness(); expect(api.usefulnessPosts).toHaveLength(1);
    await component.prepareUsefulness(component.actions()[0]);
    (api.onboardingResult.body['project'] as Record<string, unknown>)['role'] = 'viewer';
    component.usefulnessChecked.set(true); await component.acknowledgeUsefulness(); expect(api.usefulnessPosts).toHaveLength(1);
    expect(component.usefulnessChallenge()).toBeNull();
  });

  it('clears usefulness proof and affirmative state immediately when a manual action form is edited', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.actionRows = [api.auditActionRow];
    const harness = await RouterTestingHarness.create('/app/actions/7/9'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    await component.prepareUsefulness(component.actions()[0]); component.usefulnessChecked.set(true);
    harness.fixture.detectChanges();
    const input = harness.routeNativeElement!.querySelector<HTMLInputElement>('input[name="reason"]')!;
    input.value = 'An unsaved human edit'; input.dispatchEvent(new Event('input', { bubbles: true }));
    expect(component.usefulnessChallenge()).toBeNull(); expect(component.usefulnessChecked()).toBe(false);
    await component.acknowledgeUsefulness(); expect(api.usefulnessPosts).toEqual([]);
  });

  it('shows only current owner export scope and clears it on an unauthorized organization switch', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const harness = await RouterTestingHarness.create('/app/export/7');
    await harness.routeDebugElement?.componentInstance.load();
    harness.fixture.detectChanges();
    const element = harness.routeNativeElement!;
    expect(element.textContent).toContain('not a complete or immutable organization export');
    expect(element.textContent).toContain('tenancy.Project · 1 record(s)');
    expect(element.textContent).toContain('Project 9 · 1 currently visible object(s)');
    expect(element.querySelector<HTMLAnchorElement>('a[download]')?.getAttribute('href'))
      .toBe('/api/organizations/7/export/projects/9/artifacts/0/');
    element.querySelectorAll<HTMLButtonElement>('section[aria-labelledby="archive-title"] button')[1].click();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(element.textContent).toContain('capture is preparing');
    expect(element.querySelector<HTMLAnchorElement>('a[href="/api/organizations/7/export/snapshots/42/parts/0/"]'))
      .toBeNull();
    api.exportHistoryRows[0] = { id: 42, state: 'ready', created_at: '2026-09-29T09:00:00Z',
      manifest_path: '/api/organizations/7/export/snapshots/42/' };
    await harness.routeDebugElement?.componentInstance.loadSnapshotHistory();
    harness.fixture.detectChanges();
    Array.from(element.querySelectorAll<HTMLButtonElement>('button'))
      .find((button) => button.textContent?.includes('Show its parts'))!.click();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(element.textContent).toContain('Captured snapshot 42');
    expect(element.querySelector<HTMLAnchorElement>('a[href="/api/organizations/7/export/snapshots/42/parts/0/"]'))
      .not.toBeNull();
    const discard = Array.from(element.querySelectorAll<HTMLButtonElement>('button'))
      .find((button) => button.textContent?.includes('Discard failed capture copy'))!;
    discard.click();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(element.textContent).toContain('its slot is available again');
    expect(element.textContent).not.toContain('Snapshot 41');
    const choice = element.querySelector<HTMLSelectElement>('#export-model')!;
    choice.value = 'tenancy.Project'; choice.dispatchEvent(new Event('change'));
    harness.fixture.detectChanges();
    expect(element.querySelector<HTMLButtonElement>('section[aria-labelledby="records-title"] button')?.disabled).toBe(false);
    await harness.navigateByUrl('/app/export/8');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain('permission was revoked');
    expect(harness.routeNativeElement?.querySelector('#export-model')).toBeNull();
    expect(harness.routeNativeElement?.querySelector('a[download]')).toBeNull();
  });

  it('offers sequential source captures and bounded manifest pages without concatenated-ZIP instructions', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const harness = await RouterTestingHarness.create('/app/export/7');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const element = harness.routeNativeElement!;
    Array.from(element.querySelectorAll<HTMLButtonElement>('button'))
      .find((button) => button.textContent?.includes('Capture sequential source parts'))!.click();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.sourcePartFormat).toBe(true);
    await harness.routeDebugElement?.componentInstance.loadSnapshot(42);
    harness.fixture.detectChanges();
    expect(element.textContent).toContain('Part-descriptor chain SHA-256');
    expect(element.textContent).toContain('through 49 of 51 parts');
    expect(element.querySelector<HTMLAnchorElement>('a[href$="?position=0"]')?.download).toBe('');
    Array.from(element.querySelectorAll<HTMLButtonElement>('button'))
      .find((button) => button.textContent?.includes('Next manifest page'))!.click();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(element.textContent).toContain('through 50 of 51 parts');
    expect(element.querySelector('a[href$="/parts/0/"]')).toBeNull();
    expect(element.querySelector('a[href$="/parts/50/"]')).not.toBeNull();
    await harness.navigateByUrl('/app/export/8');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).not.toContain('Part-descriptor chain SHA-256');
  });

  it('rejects array snapshot states and clears actionable history during pending malformed or denied refresh', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const harness = await RouterTestingHarness.create('/app/export/7');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const component = harness.routeDebugElement!.componentInstance;
    const history = structuredClone(api.exportHistoryRows);
    expect(component.snapshotHistory()).toEqual(history);
    expect(harness.routeNativeElement?.querySelector('section[aria-labelledby="archive-title"] li button')).not.toBeNull();
    for (const state of ['ready', 'preparing', 'failed', 'expired']) {
      api.exportHistoryRows = [{ ...history[0], state: [state], manifest_path: null }];
      await component.loadSnapshotHistory(); harness.fixture.detectChanges();
      expect(component.snapshotHistory()).toEqual([]);
      expect(component.snapshotHistoryError()).toContain('captures are unavailable');
      expect(harness.routeNativeElement?.querySelector('section[aria-labelledby="archive-title"] li button')).toBeNull();
      api.exportHistoryRows = structuredClone(history); await component.loadSnapshotHistory();
    }
    const expiry = '2026-10-15T00:00:00Z';
    api.exportHistoryRows = [{ ...history[0], state: 'expired', expires_at: expiry, manifest_path: null }];
    await component.loadSnapshotHistory(); harness.fixture.detectChanges();
    expect(component.snapshotHistory()[0].state).toBe('expired');
    expect(harness.routeNativeElement?.textContent).toContain('storage cleanup may still be pending');
    expect(harness.routeNativeElement?.querySelector('time')?.getAttribute('datetime')).toBe(expiry);
    expect(harness.routeNativeElement?.querySelector('section[aria-labelledby="archive-title"] li button')).toBeNull();
    for (const expires_at of [null, ['2026-10-15T00:00:00Z'], 'invalid']) {
      api.exportHistoryRows = [{ ...history[0], state: 'expired', expires_at, manifest_path: null }];
      await component.loadSnapshotHistory(); expect(component.snapshotHistory()).toEqual([]);
    }
    api.exportHistoryRows = structuredClone(history); await component.loadSnapshotHistory();
    const read = vi.spyOn(api, 'organizationSnapshots');
    await component.loadSnapshotHistory(-1);
    expect(read).not.toHaveBeenCalled(); expect(component.snapshotHistory()).toEqual(history);
    let finish!: (value: ApiResult) => void;
    read.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    const pending = component.loadSnapshotHistory(); harness.fixture.detectChanges();
    expect(component.snapshotHistory()).toEqual([]);
    expect(harness.routeNativeElement?.querySelector('section[aria-labelledby="archive-title"] li button')).toBeNull();
    finish({ status: 403, body: {} }); await pending;
    expect(component.snapshotHistory()).toEqual([]);
    read.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    const olderHistory = component.loadSnapshotHistory();
    read.mockResolvedValueOnce({ status: 403, body: {} }); await component.loadSnapshotHistory();
    finish({ status: 200, body: { organization_id: 7, scope: 'bounded_capture_history_not_complete_export', snapshots: history } });
    await olderHistory; harness.fixture.detectChanges();
    expect(component.snapshotHistory()).toEqual([]);
    expect(harness.routeNativeElement?.querySelector('section[aria-labelledby="archive-title"] li button')).toBeNull();
    const captures = vi.spyOn(api, 'captureOrganizationSnapshot');
    for (const format of ['bounded-zip-v1', 'source-parts-v2']) {
      for (const state of ['ready', 'preparing']) {
        captures.mockResolvedValue({ status: 202, body: { organization_id: 7, snapshot_id: 42, state: [state],
          scope: format === 'source-parts-v2' ? 'sequential_source_parts_not_transactional' : 'bounded_customer_content_only' } });
        read.mockClear(); await component.captureSnapshot(format);
        expect(component.message()).toContain('Private snapshot unavailable'); expect(read).not.toHaveBeenCalled();
        expect(component.snapshotParts()).toEqual([]);
      }
    }
    expect(captures.mock.calls).toHaveLength(4); captures.mockRestore(); read.mockRestore();
  });

  it('reads coherent manifest pages with explicit consistency and rejects unknown or mismatched formats', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const harness = await RouterTestingHarness.create('/app/export/7');
    await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    api.sourcePartFormat = true;
    const response = await api.organizationSnapshotManifest(7, 42);
    const body = { ...response.body, version: 'coherent-parts-v3', scope: 'coherent_customer_content_only',
      consistency: 'one_live_database_snapshot_and_admitted_visible_objects_not_legal_or_backup_export',
      capture_window: { started_at: '2026-10-11T01:00:00Z', completed_at: '2026-10-11T01:01:00Z' } };
    const manifest = vi.spyOn(api, 'organizationSnapshotManifest').mockResolvedValue({ status: 200, body });
    await component.loadSnapshot(42); harness.fixture.detectChanges();
    expect(component.snapshotFormat()).toBe('coherent-parts-v3');
    expect(harness.routeNativeElement?.textContent).toContain('through 49 of 51 parts');
    expect(component.message()).toContain('coherent customer-content parts');
    expect(harness.routeNativeElement?.querySelector('a[href$="?position=0"]')).not.toBeNull();
    const firstPart = (response.body['parts'] as Record<string, unknown>[])[0];
    const second = { ...body, parts: [{ ...firstPart, position: 50,
      download_path: '/api/organizations/7/export/snapshots/42/parts/50/' }], next_position: null };
    manifest.mockResolvedValue({ status: 200, body: second });
    await component.loadSnapshot(42, undefined, 50); harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain('through 50 of 51 parts');
    expect(harness.routeNativeElement?.querySelector('a[href$="/parts/0/"]')).toBeNull();
    expect(harness.routeNativeElement?.querySelector('a[href$="/parts/50/"]')).not.toBeNull();
    let finishHistory!: (value: ApiResult) => void;
    const history = vi.spyOn(api, 'organizationSnapshots').mockReturnValueOnce(new Promise(resolve => { finishHistory = resolve; }));
    const refresh = component.loadSnapshotHistory(); harness.fixture.detectChanges();
    expect(component.snapshotParts()).toEqual([]);
    expect(harness.routeNativeElement?.querySelector('a[href$="/parts/50/"]')).toBeNull();
    finishHistory({ status: 403, body: {} }); await refresh;
    let finishManifest!: (value: ApiResult) => void;
    manifest.mockReturnValueOnce(new Promise(resolve => { finishManifest = resolve; }));
    const olderManifest = component.loadSnapshot(42);
    history.mockResolvedValueOnce({ status: 403, body: {} });
    await component.loadSnapshotHistory();
    finishManifest({ status: 200, body }); await olderManifest; harness.fixture.detectChanges();
    expect(component.snapshotParts()).toEqual([]);
    expect(harness.routeNativeElement?.querySelector('a[href$="/parts/0/"]')).toBeNull();
    history.mockRestore();
    for (const invalid of [{ ...body, version: 'future-parts' }, { ...body, consistency: 'sequential' },
      { ...body, capture_window: { started_at: 'invalid', completed_at: 'invalid' } }]) {
      manifest.mockResolvedValue({ status: 200, body: invalid });
      await component.loadSnapshot(42); harness.fixture.detectChanges();
      expect(component.snapshotParts()).toEqual([]);
      expect(harness.routeNativeElement?.querySelector('a[href$="/parts/0/"]')).toBeNull();
    }
    const capture = vi.spyOn(api, 'captureOrganizationSnapshot').mockResolvedValue({ status: 202,
      body: { organization_id: 7, snapshot_id: 42, state: 'preparing', format: 'source-parts-v2',
        scope: 'coherent_customer_content_only' } });
    await component.captureSnapshot('coherent-parts-v3');
    expect(component.message()).toContain('Private snapshot unavailable');
    await component.captureSnapshot('future-parts');
    expect(capture).toHaveBeenCalledTimes(1);
    capture.mockResolvedValueOnce({ status: 202, body: { organization_id: 7, snapshot_id: 42,
      state: 'preparing', format: 'coherent-parts-v3', scope: 'coherent_customer_content_only' } });
    harness.fixture.detectChanges();
    Array.from(harness.routeNativeElement!.querySelectorAll<HTMLButtonElement>('button'))
      .find(button => button.textContent?.includes('Capture coherent customer-content parts'))!.click();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(capture).toHaveBeenLastCalledWith(7, 'coherent-parts-v3');
    expect(component.message()).toContain('capture is preparing');
    expect(component.snapshotParts()).toEqual([]);
  });

  it('localizes the Turkish organization export draft and preserves owner scope selections and private downloads', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    let finishPreference!: (value: ApiResult) => void;
    const preference = vi.spyOn(api, 'productLanguage').mockReturnValue(new Promise(resolve => { finishPreference = resolve; }));
    const harness = await RouterTestingHarness.create('/app/export/7');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe('Organization customer-data export inventory — OrganicSEOOps');
    const component = harness.routeDebugElement!.componentInstance, element = harness.routeNativeElement!;
    const choice = element.querySelector<HTMLSelectElement>('#export-model')!;
    choice.value = 'tenancy.Project'; choice.dispatchEvent(new Event('change'));
    const artifact = element.querySelector<HTMLInputElement>('#artifact-index-9')!;
    artifact.value = '0'; artifact.dispatchEvent(new Event('change'));
    await component.loadSnapshot(42);
    const parts = component.snapshotParts(), history = component.snapshotHistory();
    const inventory = vi.spyOn(api, 'organizationExportInventory'), manifests = vi.spyOn(api, 'organizationSnapshotManifest');
    finishPreference({ status: 200, body: { language: 'tr', current_ui_language: 'en', current_email_language: 'en' } });
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe('Kuruluş müşteri verisi dışa aktarma envanteri — OrganicSEOOps');
    expect(element.querySelector('.workspace-panel')?.getAttribute('lang')).toBe('tr');
    expect(element.querySelector('h1')?.textContent).toBe('Kuruluş 7 müşteri verisi dışa aktarma envanteri');
    expect(element.textContent).toContain('incelenmemiş Türkçe kuruluş dışa aktarma');
    expect(element.textContent).toContain('tam veya değişmez bir kuruluş dışa aktarımı değildir');
    expect(element.textContent).toContain('5.000 satır, proje başına 1.000 nesne veya 32 MiB');
    expect(element.textContent).toContain('müşteri verileri silinene kadar özel kalır');
    expect(element.textContent).toContain('Kuruluş başına üç kopya');
    expect(element.textContent).toContain('yasal bir dışa aktarım değildir');
    expect(element.textContent).toContain('gizli S3 sürümleri ve yedekler hariçtir');
    expect(element.textContent).toContain('güncel sahip yetkisi gerektirir');
    expect(element.querySelector('label[for="export-model"]')?.textContent).toBe('Kaynak kayıt grubu');
    expect(choice.value).toBe('tenancy.Project'); expect(choice.getAttribute('lang')).toBeNull();
    expect(choice.closest('[lang]')?.getAttribute('lang')).toBe('tr');
    expect(choice.options[1].getAttribute('lang')).toBe('en');
    expect(choice.options[0].getAttribute('lang')).toBe('tr');
    expect(choice.options[1].textContent).toBe('tenancy.Project · 1 record(s)');
    expect(artifact.value).toBe('0'); expect(component.throughId()).toBe(9);
    expect(component.snapshotParts()).toBe(parts); expect(component.snapshotHistory()).toBe(history);
    expect(inventory).not.toHaveBeenCalled(); expect(manifests).not.toHaveBeenCalled();
    expect(element.querySelector('a[href$="/parts/0/"]')?.textContent).toBe('Parçayı indir 0');
    const snapshotStatus = element.querySelector<HTMLParagraphElement>('p[role="status"][lang]')!;
    expect(component.message()).toBe('Private captured parts are ready. Source observations are sequential, not a transactional snapshot.');
    expect(snapshotStatus.lang).toBe('tr'); expect(snapshotStatus.textContent).toContain('Kaynak gözlemleri sıralıdır');
    expect(Array.from(element.querySelectorAll('[lang="en"]')).some(node => node.textContent?.includes('ready'))).toBe(true);
    const button = (text: string) => Array.from(element.querySelectorAll<HTMLButtonElement>('button')).find(item => item.textContent?.trim() === text)!;
    const create = vi.fn((_blob: Blob) => 'blob:private-export'), revoke = vi.fn();
    const originalURL = globalThis.URL;
    vi.stubGlobal('URL', class extends originalURL { static override createObjectURL = create; static override revokeObjectURL = revoke; });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const rows = vi.spyOn(api, 'organizationCustomerRows'), archive = vi.spyOn(api, 'boundedOrganizationArchive');
    try {
      button('Sonraki sınırlı JSON sayfasını indir').click(); await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(rows).toHaveBeenLastCalledWith(7, 'tenancy.Project', 0, 9); expect(component.afterId()).toBe(9);
      expect(button('Sonraki sınırlı JSON sayfasını indir').disabled).toBe(true);
      expect(element.textContent).toContain('Diğer modeller ve özel dosyalar ayrı ayrı dışa aktarılmalıdır');
      expect(create.mock.calls[0][0]).toBeInstanceOf(Blob);
      button('Sınırlı özel ZIP’i indir').click(); await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(archive).toHaveBeenLastCalledWith(7); expect(click).toHaveBeenCalledTimes(2);
      expect(element.textContent).toContain('Özel müşteri içeriği ZIP’i indirildi (SHA-256 ' + 'a'.repeat(64));
      expect(element.textContent).toContain('Kısıtlı faturalama/hesap verileri ve yedekler ayrıdır');
      const status = element.querySelector<HTMLParagraphElement>('p[role="status"][lang]')!;
      const english = 'Private customer-content ZIP downloaded (SHA-256 ' + 'a'.repeat(64) + '). Restricted billing/account data and backups are separate.';
      expect(component.message()).toBe(english); expect(status.lang).toBe('tr');
      choice.focus(); component.productLanguage.set('en'); harness.fixture.detectChanges();
      expect(TestBed.inject(Title).getTitle()).toBe('Organization customer-data export inventory — OrganicSEOOps');
      expect(element.querySelector('p[role="status"][lang]')).toBe(status);
      expect(status.lang).toBe('en'); expect(status.textContent).toBe(english); expect(component.message()).toBe(english);
      expect(element.querySelector('#export-model')).toBe(choice); expect(choice.value).toBe('tenancy.Project');
      expect(component.snapshotParts()).toBe(parts); expect(component.snapshotHistory()).toBe(history);
      expect(document.activeElement).toBe(choice); expect(click).toHaveBeenCalledTimes(2);
      expect(archive).toHaveBeenCalledTimes(1); expect(rows).toHaveBeenCalledTimes(1);
      component.productLanguage.set('tr'); harness.fixture.detectChanges();
      expect(TestBed.inject(Title).getTitle()).toBe('Kuruluş müşteri verisi dışa aktarma envanteri — OrganicSEOOps');
      expect(status.lang).toBe('tr'); expect(status.textContent).toContain('Özel müşteri içeriği ZIP’i indirildi');
    } finally { vi.stubGlobal('URL', originalURL); click.mockRestore(); }
    const discard = vi.spyOn(api, 'discardFailedOrganizationSnapshot');
    button('Başarısız kopyayı kaldır').click(); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(discard).toHaveBeenLastCalledWith(7, 41); expect(element.textContent).toContain('yeri yeniden kullanılabilir');
    const capture = vi.spyOn(api, 'captureOrganizationSnapshot');
    button('Sınırlı ZIP parçalarını oluştur').click(); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(capture).toHaveBeenLastCalledWith(7, 'bounded-zip-v1');
    expect(element.textContent).toContain('Özel kopya hazırlanıyor');
    expect(element.textContent).toContain('sonuç bilinmezken başka bir istek oluşturmayın');
    expect(element.querySelector('a[href$="/parts/0/"]')).toBeNull();
    await harness.navigateByUrl('/app/export/8'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.querySelector('[role="alert"]')?.textContent).toContain('izin kaldırılmış');
    expect(harness.routeNativeElement?.querySelector('a[download]')).toBeNull();
    expect(component.snapshotParts()).toEqual([]); expect(component.selectedModel()).toBe('');
    const deniedElement = harness.routeNativeElement!, alert = deniedElement.querySelector<HTMLParagraphElement>('[role="alert"]')!;
    const deniedRequests = inventory.mock.calls.length;
    const rawError = 'Organization export inventory is unavailable or permission was revoked.';
    expect(component.error()).toBe(rawError); expect(alert.lang).toBe('tr');
    component.productLanguage.set('en'); harness.fixture.detectChanges();
    expect(deniedElement.querySelector('[role="alert"]')).toBe(alert);
    expect(alert.lang).toBe('en'); expect(alert.textContent).toBe(rawError);
    component.productLanguage.set('tr'); harness.fixture.detectChanges();
    expect(alert.lang).toBe('tr'); expect(alert.textContent).toContain('izin kaldırılmış');
    expect(component.error()).toBe(rawError); expect(component.models()).toEqual([]); expect(component.projects()).toEqual([]);
    expect(inventory).toHaveBeenCalledTimes(deniedRequests);
    expect(capture).toHaveBeenCalledTimes(1); expect(discard).toHaveBeenCalledTimes(1);
    await harness.navigateByUrl('/');
    preference.mockReturnValue(new Promise(resolve => { finishPreference = resolve; }));
    await harness.navigateByUrl('/app/export/0'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const invalidComponent = harness.routeDebugElement!.componentInstance;
    const invalidElement = harness.routeNativeElement!, invalidAlert = invalidElement.querySelector<HTMLParagraphElement>('[role="alert"]')!;
    expect(invalidComponent.error()).toBe('Select a current organization.');
    expect(invalidAlert.lang).toBe('en'); expect(invalidAlert.textContent).toBe('Select a current organization.');
    finishPreference({ status: 200, body: { language: 'tr', current_ui_language: 'en', current_email_language: 'en' } });
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(invalidElement.querySelector('[role="alert"]')).toBe(invalidAlert);
    expect(invalidAlert.lang).toBe('tr'); expect(invalidAlert.textContent).toBe('Güncel bir kuruluş seçin.');
    expect(invalidComponent.error()).toBe('Select a current organization.');
    expect(invalidElement.querySelector('a[download]')).toBeNull();
    expect(inventory).toHaveBeenCalledTimes(deniedRequests);
    expect(capture).toHaveBeenCalledTimes(1); expect(discard).toHaveBeenCalledTimes(1);
    await harness.navigateByUrl('/'); harness.fixture.detectChanges();
    const nextTitle = TestBed.inject(Title).getTitle();
    invalidComponent.productLanguage.set('en'); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(nextTitle);
    expect(nextTitle).not.toContain('export inventory');
    preference.mockRestore();
  });

  it.each(['source-parts-v2', 'coherent-parts-v3'])('uses Turkish organization export controls for %s with unchanged manifest formats and pagination', async format => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = 'tr'; api.sourcePartFormat = true;
    const originalManifest = api.organizationSnapshotManifest.bind(api);
    const manifest = vi.spyOn(api, 'organizationSnapshotManifest').mockImplementation(async (org, id, position = 0) => {
      const result = await originalManifest(org, id, position);
      return format === 'source-parts-v2' ? result : { status: 200, body: { ...result.body,
        version: format, scope: 'coherent_customer_content_only',
        consistency: 'one_live_database_snapshot_and_admitted_visible_objects_not_legal_or_backup_export',
        capture_window: { started_at: '2026-10-11T01:00:00Z', completed_at: '2026-10-11T01:01:00Z' } } };
    });
    const capture = vi.spyOn(api, 'captureOrganizationSnapshot').mockResolvedValue({ status: 202, body: {
      organization_id: 7, snapshot_id: 42, format, state: 'preparing',
      scope: format === 'source-parts-v2' ? 'sequential_source_parts_not_transactional' : 'coherent_customer_content_only' } });
    const harness = await RouterTestingHarness.create('/app/export/7'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const component = harness.routeDebugElement!.componentInstance, element = harness.routeNativeElement!;
    expect(element.textContent).toContain('başlangıçtaki kayıt üst sınırlarını');
    expect(element.textContent).toContain('eşzamanlı değişiklikler dışarıda kalabilir');
    expect(element.textContent).toContain('sıralı parça tanımlayıcılarını doğrular');
    expect(element.textContent).toContain('dokuz dakika içinde tamamlanmalıdır');
    expect(element.textContent).toContain('süresi dolan kopya oluşturma işlemi sürdürülemez');
    expect(element.textContent).toContain('yasal dışa aktarım veya silme hazırlığının tamamlandığını kanıtlamaz');
    const button = (text: string) => Array.from(element.querySelectorAll<HTMLButtonElement>('button')).find(item => item.textContent === text)!;
    button(format === 'source-parts-v2' ? 'Sıralı kaynak parçalarını oluştur' : 'Tutarlı müşteri içeriği parçalarını oluştur').click();
    await harness.fixture.whenStable(); harness.fixture.detectChanges(); expect(capture).toHaveBeenLastCalledWith(7, format);
    button('Parçalarını göster').click(); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(component.snapshotFormat()).toBe(format); expect(element.textContent).toContain('Parça tanımlayıcı zinciri SHA-256');
    expect(element.textContent).toContain('0 ile 49 / 51 parça');
    expect(element.textContent).toContain(format === 'source-parts-v2' ? 'Kaynak gözlemleri sıralıdır' : 'kısıtlı kayıtlar ve yedekler hariçtir');
    const status = element.querySelector<HTMLParagraphElement>('p[role="status"][lang]')!;
    const sourceMessage = component.message(), sourceParts = component.snapshotParts(), requests = manifest.mock.calls.length;
    expect(sourceMessage).toContain(format === 'source-parts-v2' ? 'Source observations are sequential' : 'restricted records and backups are excluded');
    component.productLanguage.set('en'); harness.fixture.detectChanges();
    expect(element.querySelector('p[role="status"][lang]')).toBe(status);
    expect(status.lang).toBe('en'); expect(status.textContent).toBe(sourceMessage);
    expect(component.snapshotParts()).toBe(sourceParts); expect(manifest).toHaveBeenCalledTimes(requests);
    expect(capture).toHaveBeenCalledTimes(1);
    component.productLanguage.set('tr'); harness.fixture.detectChanges(); expect(status.lang).toBe('tr');
    expect(element.querySelector('a[href$="?position=0"]')?.textContent).toBe('Bu manifest sayfasını indir');
    expect(Array.from(element.querySelectorAll('[lang="en"]')).some(node => node.textContent?.includes('rows jobs.JobStep'))).toBe(true);
    button('Sonraki manifest sayfası').click(); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(manifest).toHaveBeenLastCalledWith(7, 42, 50); expect(element.textContent).toContain('50 ile 50 / 51 parça');
    expect(element.querySelector('a[href$="/parts/0/"]')).toBeNull(); expect(element.querySelector('a[href$="/parts/50/"]')).not.toBeNull();
    button('Önceki manifest sayfası').click(); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(manifest).toHaveBeenLastCalledWith(7, 42, 0); expect(component.snapshotNextPosition()).toBe(50);
    const history = vi.spyOn(api, 'organizationSnapshots').mockResolvedValue({ status: 403, body: {} });
    button('Kopya durumunu yenile').click(); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(element.textContent).toContain('Önceki özel kopyalar kullanılamıyor');
    const historyStatus = Array.from(element.querySelectorAll<HTMLParagraphElement>('p[role="status"][lang]'))
      .find(node => node.textContent?.includes('Önceki özel kopyalar kullanılamıyor'))!;
    const historyReads = history.mock.calls.length;
    expect(component.snapshotHistoryError()).toBe('Previous private captures are unavailable.');
    component.productLanguage.set('en'); harness.fixture.detectChanges();
    expect(historyStatus.lang).toBe('en'); expect(historyStatus.textContent).toBe('Previous private captures are unavailable.');
    expect(history).toHaveBeenCalledTimes(historyReads); expect(component.snapshotHistory()).toEqual([]);
    component.productLanguage.set('tr'); harness.fixture.detectChanges();
    expect(historyStatus.lang).toBe('tr'); expect(historyStatus.textContent).toContain('Önceki özel kopyalar kullanılamıyor');
    expect(element.querySelector('a[href$="/parts/0/"]')).toBeNull(); expect(component.snapshotHistory()).toEqual([]);
    manifest.mockResolvedValue({ status: 403, body: {} }); await component.loadSnapshot(42); harness.fixture.detectChanges();
    expect(element.textContent).toContain('Özel kopya parçaları kullanılamıyor veya izin kaldırılmış');
    expect(capture).toHaveBeenCalledTimes(1); history.mockRestore();
  });

  it('keeps organization export English for denied malformed unavailable and fresh production preferences', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const preference = vi.spyOn(api, 'productLanguage'), buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    const harness = await RouterTestingHarness.create('/');
    try {
      for (const mode of ['denied', 'invalid', 'unavailable', 'production'] as const) {
        await harness.navigateByUrl('/'); buildEnvironment.production = mode === 'production';
        if (mode === 'unavailable') preference.mockRejectedValue(new Error('PRIVATE preference details'));
        else preference.mockResolvedValue({ status: mode === 'denied' ? 403 : 200, body: {
          language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: 'en', current_email_language: 'en' } });
        await harness.navigateByUrl('/app/export/7'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
        expect(TestBed.inject(Title).getTitle()).toBe('Organization customer-data export inventory — OrganicSEOOps');
        expect(harness.routeNativeElement?.querySelector('.workspace-panel')?.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Organization 7 customer-data export inventory');
        expect(harness.routeNativeElement?.textContent).not.toContain('incelenmemiş Türkçe');
        expect(harness.routeNativeElement?.textContent).not.toContain('PRIVATE preference details');
        expect(harness.routeNativeElement?.querySelector('#export-model')).not.toBeNull();
        await harness.navigateByUrl('/app/export/8'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
        const component = harness.routeDebugElement!.componentInstance, alert = harness.routeNativeElement!.querySelector<HTMLParagraphElement>('[role="alert"]')!;
        expect(component.error()).toBe('Organization export inventory is unavailable or permission was revoked.');
        expect(alert.lang).toBe('en'); expect(alert.textContent).toBe(component.error());
        expect(harness.routeNativeElement?.querySelector('a[download]')).toBeNull();
        expect(component.models()).toEqual([]); expect(component.projects()).toEqual([]);
      }
    } finally { buildEnvironment.production = production; preference.mockRestore(); }
  });

  it.each(['en', 'tr'] as const)('shows source-limited closure status and clears a prior organization on denied navigation (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    const original = structuredClone(api.closureStatusResult.body);
    const harness = await RouterTestingHarness.create('/app/closure-status/7');
    await harness.routeDebugElement?.componentInstance.load();
    harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Kuruluş saklama ve kapatma durumu — OrganicSEOOps' : 'Organization retention and closure status — OrganicSEOOps');
    expect(harness.routeNativeElement?.textContent).toContain((language === 'tr' ? 'Güncel durum: open' : 'Current state: open'));
    expect(harness.routeNativeElement?.textContent).toContain((language === 'tr' ? 'içeriğin silindiğinin kanıtı değildir' : 'not proof that content has been deleted'));
    expect(harness.routeNativeElement?.textContent).toContain('Hosted backup expiry requires verification');
    for (const state of ['open', 'closed', 'retention_cleanup']) {
      api.closureStatusResult.body = { ...original, state: [state] };
      await harness.routeDebugElement!.componentInstance.load(); harness.fixture.detectChanges();
      expect(harness.routeDebugElement!.componentInstance.status()).toBeNull();
      expect(harness.routeNativeElement?.textContent).toContain((language === 'tr' ? 'kuruluşun kapatma veya saklama durumu kullanılamıyor' : 'status unavailable for this organization'));
      expect(harness.routeNativeElement?.querySelector('form')).toBeNull();
    }
    expect(api.closureRequests).toEqual([]); expect(api.closureBillingChecks).toEqual([]); expect(api.closureGrantAttempts).toEqual([]);
    api.closureStatusResult.body = original;
    await harness.navigateByUrl('/app/closure-status/8');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain((language === 'tr' ? 'kuruluşun kapatma veya saklama durumu kullanılamıyor' : 'status unavailable for this organization'));
    expect(harness.routeNativeElement?.textContent).not.toContain((language === 'tr' ? 'Güncel durum: open' : 'Current state: open'));
    const component = harness.routeDebugElement!.componentInstance, element = harness.routeNativeElement!;
    const alert = element.querySelector<HTMLParagraphElement>('[role="alert"]')!;
    const rawError = 'Closure or retention status unavailable for this organization.';
    const reads = vi.spyOn(api, 'organizationClosureStatus');
    expect(component.error()).toBe(rawError); expect(alert.lang).toBe(language);
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Organization retention and closure status — OrganicSEOOps' : 'Kuruluş saklama ve kapatma durumu — OrganicSEOOps');
    expect(element.querySelector('[role="alert"]')).toBe(alert);
    expect(alert.lang).toBe(language === 'tr' ? 'en' : 'tr');
    expect(alert.textContent).toBe(component.t(rawError)); expect(component.error()).toBe(rawError);
    expect(component.status()).toBeNull(); expect(element.querySelector('form')).toBeNull();
    expect(reads).not.toHaveBeenCalled(); reads.mockRestore();
    component.productLanguage.set(language); harness.fixture.detectChanges();
    if (language === 'tr') {
      const preference = vi.spyOn(api, 'productLanguage'), buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
      try {
        for (const mode of ['denied', 'invalid', 'unavailable', 'production'] as const) {
          await harness.navigateByUrl('/'); buildEnvironment.production = mode === 'production';
          if (mode === 'unavailable') preference.mockRejectedValue(new Error('PRIVATE preference detail'));
          else preference.mockResolvedValue({ status: mode === 'denied' ? 403 : 200, body: {
            language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: 'en', current_email_language: 'en' } });
          await harness.navigateByUrl('/app/closure-status/7'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
          expect(harness.routeNativeElement?.querySelector('.workspace-panel')?.getAttribute('lang')).toBe('en');
          expect(TestBed.inject(Title).getTitle()).toBe('Organization retention and closure status — OrganicSEOOps');
          expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Organization 7 retention and closure status');
          expect(harness.routeNativeElement?.textContent).not.toContain('incelenmemiş Türkçe');
          expect(harness.routeNativeElement?.textContent).not.toContain('PRIVATE preference detail');
          expect(harness.routeNativeElement?.querySelector('form')).toBeNull();
        }
      } finally { buildEnvironment.production = production; preference.mockRestore(); }
    }
    await harness.navigateByUrl('/'); harness.fixture.detectChanges();
    const nextTitle = TestBed.inject(Title).getTitle();
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(nextTitle);
    expect(nextTitle).not.toContain('closure status');

  });

  it.each(['en', 'tr'] as const)('rejects array closure command outcomes without success refresh or automatic replay (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    const original = structuredClone(api.closureStatusResult.body);
    const path = '/api/organizations/7/closure-status/';
    const harness = await RouterTestingHarness.create('/app/closure-status/7');
    const cases = [
      { method: 'organizationClose' as const, selector: '#closure-password',
        states: ['closed', 'closed_cleanup_review', 'closed_billing_review'], status: 202,
        source: { ...original, close_action_available: true }, extra: { backup_expiry: 'policy_only_unverified' },
        message: (language === 'tr' ? 'Kapatma sonucu kullanılamıyor' : 'Closure outcome unavailable') },
      { method: 'organizationReconcileClosureBilling' as const, selector: '#billing-reconcile-password',
        states: ['unknown', 'confirmed', 'sending'], status: 200,
        source: { ...original, state: 'closed', billing_cancellation: { state: 'unknown', error_category: '' } }, extra: {},
        message: (language === 'tr' ? 'Sağlayıcı mutabakatı kullanılamıyor' : 'Provider reconciliation unavailable') },
      { method: 'organizationRevokePendingGrant' as const, selector: '#grant-revoke-password',
        states: ['revoked', 'revocation_pending'], status: 200,
        source: { ...original, state: 'closed', pending_grants: { search_console: [31], analytics: [] } }, extra: { provider: 'search_console' },
        message: (language === 'tr' ? 'Uzak erişimi kaldırma sonucu kullanılamıyor' : 'Remote revocation outcome unavailable') },
    ];
    for (const entry of cases) {
      const command = vi.spyOn(api, entry.method);
      for (const state of entry.states) {
        api.closureStatusResult.body = entry.source;
        await harness.routeDebugElement!.componentInstance.load(); harness.fixture.detectChanges();
        const reads = vi.spyOn(api, 'organizationClosureStatus');
        command.mockResolvedValue({ status: entry.status, body: { organization_id: 7,
          status_path: path, ...entry.extra, state: [state] } });
        const form = harness.routeNativeElement!.querySelector<HTMLInputElement>(entry.selector)!.closest('form')!;
        form.querySelector<HTMLInputElement>('[name="password"]')!.value = 'owner-password';
        const checkbox = form.querySelector<HTMLInputElement>('[name="acknowledge"]');
        if (checkbox) checkbox.checked = true;
        form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
        await harness.fixture.whenStable(); harness.fixture.detectChanges();
        const component = harness.routeDebugElement!.componentInstance, element = harness.routeNativeElement!;
        const message = component.message(), status = element.querySelector<HTMLParagraphElement>('p[role="status"][lang]')!;
        expect(component.t(message)).toContain(entry.message); expect(message).toContain('unavailable');
        expect(status.lang).toBe(language); expect(status.textContent).toBe(component.t(message));
        const requests = command.mock.calls.length, password = form.querySelector<HTMLInputElement>('[name="password"]')!;
        password.focus(); component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
        expect(element.querySelector('p[role="status"][lang]')).toBe(status);
        expect(status.lang).toBe(language === 'tr' ? 'en' : 'tr'); expect(status.textContent).toBe(component.t(message));
        expect(component.message()).toBe(message); expect(password.value).toBe('owner-password');
        expect(document.activeElement).toBe(password); expect(password.closest('form')).toBe(form);
        expect(command).toHaveBeenCalledTimes(requests); expect(reads).not.toHaveBeenCalled();
        component.productLanguage.set(language); harness.fixture.detectChanges(); reads.mockRestore();
      }
      expect(command.mock.calls).toHaveLength(entry.states.length); command.mockRestore();
    }
    expect(api.closureRequests).toEqual([]); expect(api.closureBillingChecks).toEqual([]); expect(api.closureGrantAttempts).toEqual([]);
  });

  it.each(['en', 'tr'] as const)('requires explicit owner acknowledgement before the gated close action and refreshes truthful status (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    api.closureStatusResult = { status: 200, body: {
      ...api.closureStatusResult.body, close_action_available: true,
    } };
    const harness = await RouterTestingHarness.create('/app/closure-status/7');
    await harness.routeDebugElement?.componentInstance.load();
    harness.fixture.detectChanges();
    const form = harness.routeNativeElement!.querySelector<HTMLInputElement>('#closure-password')!.closest('form')!;
    form.querySelector<HTMLInputElement>('[name="password"]')!.value = 'owner-password';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.closureRequests).toEqual([]);

    const component = harness.routeDebugElement!.componentInstance;
    expect(harness.routeNativeElement?.querySelector('.workspace-panel')?.getAttribute('lang')).toBe(language);
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? '30 günlük aktif depolama' : '30-day active-store');
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'kapatma sonrasında erişilemezler' : 'after closure they are inaccessible');
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'İndirilmiş kopyalar silinemez' : 'Already downloaded copies cannot be erased');
    expect(form.querySelector('label[for="closure-password"]')?.textContent).toBe(language === 'tr' ? 'Güncel parola' : 'Current password');
    const password = form.querySelector<HTMLInputElement>('[name="password"]')!, acknowledge = form.querySelector<HTMLInputElement>('[name="acknowledge"]')!;
    expect(password.getAttribute('lang')).toBe('');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(password.value).toBe('owner-password'); expect(acknowledge.checked).toBe(false);
    expect(harness.routeNativeElement?.querySelector('#closure-password')).toBe(password);
    expect(api.closureRequests).toEqual([]);
    component.productLanguage.set(language); harness.fixture.detectChanges();
    form.querySelector<HTMLInputElement>('[name="acknowledge"]')!.click();
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.closureRequests).toEqual([7]);
    expect(harness.routeNativeElement?.textContent).toContain((language === 'tr' ? 'Güncel durum: closed' : 'Current state: closed'));
    expect(harness.routeNativeElement?.textContent).toContain((language === 'tr' ? 'doğrulanmadı' : 'not confirmed'));
    expect(harness.routeNativeElement?.textContent).toContain('Hosted backup expiry requires verification');
    expect(harness.routeNativeElement?.querySelector('#closure-password')).toBeNull();
    const resultComponent = harness.routeDebugElement!.componentInstance, resultElement = harness.routeNativeElement!;
    const acknowledgment = resultElement.querySelector<HTMLParagraphElement>('p[role="status"][lang]')!;
    const rawMessage = resultComponent.message(), currentStatus = resultComponent.status();
    const reads = vi.spyOn(api, 'organizationClosureStatus');
    expect(rawMessage).toContain('Organization access closed.'); expect(acknowledgment.lang).toBe(language);
    resultComponent.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(resultElement.querySelector('p[role="status"][lang]')).toBe(acknowledgment);
    expect(acknowledgment.lang).toBe(language === 'tr' ? 'en' : 'tr');
    expect(acknowledgment.textContent).toBe(resultComponent.t(rawMessage)); expect(resultComponent.message()).toBe(rawMessage);
    expect(resultComponent.status()).toBe(currentStatus); expect(reads).not.toHaveBeenCalled();
    expect(api.closureRequests.length + api.closureBillingChecks.length + api.closureGrantAttempts.length).toBe(1);
    resultComponent.productLanguage.set(language); harness.fixture.detectChanges(); reads.mockRestore();
  });

  it.each(['en', 'tr'] as const)('checks an unknown billing cancellation without issuing another destructive close request (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    api.closureStatusResult = { status: 200, body: {
      ...api.closureStatusResult.body, state: 'closed', close_action_available: false,
      closed_at: '2026-09-29T02:00:00Z', billing_cancellation: { state: 'unknown', error_category: 'timeout' },
    } };
    const harness = await RouterTestingHarness.create('/app/closure-status/7');
    await harness.routeDebugElement?.componentInstance.load(); harness.fixture.detectChanges();
    const form = harness.routeNativeElement!.querySelector<HTMLInputElement>('#billing-reconcile-password')!.closest('form')!;

    expect(form.querySelector('label')?.textContent).toBe(language === 'tr' ? 'Salt okunur sağlayıcı durum kontrolünden önce güncel parola' : 'Current password before a read-only provider status check');
    expect(form.querySelector('button')?.textContent).toBe(language === 'tr' ? 'Başka iptal isteği göndermeden sağlayıcı iptalini kontrol et' : 'Check provider cancellation without sending another cancel request');
    expect(Array.from(harness.routeNativeElement!.querySelectorAll('[lang="en"]')).some(node => node.textContent === 'unknown')).toBe(true);
    form.querySelector<HTMLInputElement>('input')!.value = 'owner-password';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.closureBillingChecks).toEqual([7]);
    expect(api.closureRequests).toEqual([]);
    expect(harness.routeNativeElement?.textContent).toContain((language === 'tr' ? 'Sağlayıcı abonelik iptali: confirmed' : 'Provider subscription cancellation: confirmed'));
    expect(harness.routeNativeElement?.querySelector('#billing-reconcile-password')).toBeNull();
    const resultComponent = harness.routeDebugElement!.componentInstance, resultElement = harness.routeNativeElement!;
    const acknowledgment = resultElement.querySelector<HTMLParagraphElement>('p[role="status"][lang]')!;
    const rawMessage = resultComponent.message(), currentStatus = resultComponent.status();
    const reads = vi.spyOn(api, 'organizationClosureStatus');
    expect(rawMessage).toContain('Provider cancellation observed.'); expect(acknowledgment.lang).toBe(language);
    resultComponent.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(resultElement.querySelector('p[role="status"][lang]')).toBe(acknowledgment);
    expect(acknowledgment.lang).toBe(language === 'tr' ? 'en' : 'tr');
    expect(acknowledgment.textContent).toBe(resultComponent.t(rawMessage)); expect(resultComponent.message()).toBe(rawMessage);
    expect(resultComponent.status()).toBe(currentStatus); expect(reads).not.toHaveBeenCalled();
    expect(api.closureRequests.length + api.closureBillingChecks.length + api.closureGrantAttempts.length).toBe(1);
    resultComponent.productLanguage.set(language); harness.fixture.detectChanges(); reads.mockRestore();
  });

  it.each(['en', 'tr'] as const)('selects only a server-listed pending grant before attempting owner remote revocation (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    api.closureStatusResult = { status: 200, body: {
      ...api.closureStatusResult.body, state: 'closed', closed_at: '2026-09-29T02:00:00Z',
      pending_grants: { search_console: [31], analytics: [] },
      remote_revocation_pending: { search_console: 1, analytics: 0 },
    } };
    const harness = await RouterTestingHarness.create('/app/closure-status/7');
    await harness.routeDebugElement?.componentInstance.load(); harness.fixture.detectChanges();
    const form = harness.routeNativeElement!.querySelector<HTMLInputElement>('#grant-revoke-password')!.closest('form')!;
    form.querySelector<HTMLInputElement>('input[name="password"]')!.value = 'owner-password';

    const select = form.querySelector<HTMLSelectElement>('#pending-grant')!, password = form.querySelector<HTMLInputElement>('[name="password"]')!;
    const component = harness.routeDebugElement!.componentInstance;
    expect(select.options[0].textContent).toBe(language === 'tr' ? 'Search Console yetkisi 31' : 'Search Console grant 31');
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'bir isteği tekrarlamak ilkinin başarısız olduğunu kanıtlamaz' : 'repeating a request cannot prove the first one failed');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(select.value).toBe('search_console:31'); expect(password.value).toBe('owner-password');
    expect(api.closureGrantAttempts).toEqual([]); component.productLanguage.set(language); harness.fixture.detectChanges();
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.closureGrantAttempts).toEqual([{ organizationId: 7, provider: 'search_console', grantId: 31 }]);
    expect(api.closureRequests).toEqual([]);
    expect(harness.routeNativeElement?.textContent).toContain('Search Console 0, Analytics 0');
    expect(harness.routeNativeElement?.querySelector('#grant-revoke-password')).toBeNull();
    const resultComponent = harness.routeDebugElement!.componentInstance, resultElement = harness.routeNativeElement!;
    const acknowledgment = resultElement.querySelector<HTMLParagraphElement>('p[role="status"][lang]')!;
    const rawMessage = resultComponent.message(), currentStatus = resultComponent.status();
    const reads = vi.spyOn(api, 'organizationClosureStatus');
    expect(rawMessage).toContain('Provider grant revocation confirmed.'); expect(acknowledgment.lang).toBe(language);
    resultComponent.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(resultElement.querySelector('p[role="status"][lang]')).toBe(acknowledgment);
    expect(acknowledgment.lang).toBe(language === 'tr' ? 'en' : 'tr');
    expect(acknowledgment.textContent).toBe(resultComponent.t(rawMessage)); expect(resultComponent.message()).toBe(rawMessage);
    expect(resultComponent.status()).toBe(currentStatus); expect(reads).not.toHaveBeenCalled();
    expect(api.closureRequests.length + api.closureBillingChecks.length + api.closureGrantAttempts.length).toBe(1);
    resultComponent.productLanguage.set(language); harness.fixture.detectChanges(); reads.mockRestore();
  });

  it('requires current-password reauthentication before downloading personal account details', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const harness = await RouterTestingHarness.create('/account/security');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const element = harness.routeNativeElement!;
    const form = element.querySelector<HTMLInputElement>('#account-export-password')!.closest('form')!;
    expect(element.textContent).toContain('Self-service account closure is release-gated');
    vi.spyOn(api, 'reauthenticate').mockResolvedValueOnce({ status: 403, body: {} });
    form.querySelector<HTMLInputElement>('input')!.value = 'incorrect-password';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.personalExportCalls).toBe(0);
    expect(element.textContent).toContain('Personal account export is unavailable');
    form.querySelector<HTMLInputElement>('input')!.value = 'correct-password';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.personalExportCalls).toBe(1);
    expect(element.textContent).toContain('Personal account download requested');
    expect(form.querySelector<HTMLInputElement>('input')!.value).toBe('');
  });

  it('hands personal account downloads to a fixed native CSRF POST without loading a Blob', async () => {
    const fetcher = vi.fn().mockResolvedValue({ status: 200 });
    const doc = { cookie: 'csrftoken=fixture-csrf', defaultView: { fetch: fetcher },
      createElement: document.createElement.bind(document), body: document.body } as unknown as Document;
    const api = new AccountApi(doc);
    const submit = vi.spyOn(HTMLFormElement.prototype, 'submit').mockImplementation(function(this: HTMLFormElement) {
      expect(this.method).toBe('post'); expect(this.getAttribute('action')).toBe('/api/account/export/');
      expect(this.target).toBe('_self'); expect(this.isConnected).toBe(true);
      expect([...new FormData(this).entries()]).toEqual([['csrfmiddlewaretoken', 'fixture-csrf']]);
    });
    const before = document.body.querySelectorAll('form').length;
    try {
      await api.personalAccountArchive();
      expect(submit).toHaveBeenCalledOnce();
      expect(fetcher).toHaveBeenCalledExactlyOnceWith('/_allauth/browser/v1/auth/session', {
        credentials: 'same-origin', cache: 'no-store',
      });
      expect(document.body.querySelectorAll('form').length).toBe(before);
      fetcher.mockResolvedValue({ status: 401 });
      await expect(api.personalAccountArchive()).rejects.toThrow('Reauthenticate');
      fetcher.mockResolvedValue({ status: 200 }); Object.assign(doc, { cookie: '' });
      await expect(api.personalAccountArchive()).rejects.toThrow('Reauthenticate');
      expect(submit).toHaveBeenCalledOnce();
      Object.assign(doc, { cookie: 'csrftoken=fixture-csrf' });
      submit.mockImplementation(() => { throw new Error('Submission failed'); });
      await expect(api.personalAccountArchive()).rejects.toThrow('Submission failed');
      expect(document.body.querySelectorAll('form').length).toBe(before);
    } finally { submit.mockRestore(); }
  });

  it('shows personal closure only when the server allows it and requires explicit acknowledgement', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.personalClosureResult = { status: 200, body: { action_available: true,
      requires_org_exit: false, retained_identity: 'restricted_policy_review_not_erased' } };
    const harness = await RouterTestingHarness.create('/account/security');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const element = harness.routeNativeElement!;
    const form = element.querySelector<HTMLInputElement>('#personal-closure-password')!.closest('form')!;
    form.querySelector<HTMLInputElement>('input[name="password"]')!.value = 'password-confirmation';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.personalCloseCalls).toBe(0);
    form.querySelector<HTMLInputElement>('[name="acknowledge"]')!.click();
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.personalCloseCalls).toBe(1);
    expect(element.textContent).toContain('Personal access closed; all sessions are invalid');
    expect(element.querySelector('#personal-closure-password')).toBeNull();
  });

  it.each(['en', 'tr'] as const)('requires a staff catalog response before model configuration and submits the selected capability in %s', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    const harness = await RouterTestingHarness.create('/account/provider-settings');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe(language);
    expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe(language === 'tr' ? 'Yapay zekâ sağlayıcı kimlik bilgileri' : 'AI provider credentials');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.querySelector('#model-identifier')).toBeNull();
    api.platformProvidersResult = { status: 200, body: {
      providers: [{ id: 9, key: 'openai', name: 'OpenAI', kind: 'openai', enabled: true }],
      accounts: [], has_more: false,
    } };
    api.platformModelsResult = { status: 200, body: {
      models: [], has_more: false, capability_choices: ['text_generation', 'web_search'],
    } };
    await harness.routeDebugElement?.componentInstance.load();
    await harness.routeDebugElement?.componentInstance.loadModels();
    harness.fixture.detectChanges();
    const form = harness.routeNativeElement?.querySelector('#model-identifier')!.closest('form')!;
    form.querySelector<HTMLInputElement>('[name="identifier"]')!.value = 'staff-selected-model';
    form.querySelector<HTMLInputElement>('[name="name"]')!.value = 'Model';
    form.querySelector<HTMLOptionElement>('option[value="text_generation"]')!.selected = true;
    form.querySelector<HTMLInputElement>('[name="capability_source"]')!.value = 'https://example.com/models';
    form.querySelector<HTMLInputElement>('[name="max_output_tokens"]')!.value = '100';
    form.querySelector<HTMLInputElement>('[name="enabled"]')!.checked = true;
    expect(harness.routeNativeElement!.querySelector('label[for="model-capabilities"]')!.textContent).toContain(language === 'tr' ? 'Belgelenmiş yetenekler' : 'Documented capabilities');
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    expect(api.savedModels).toEqual([{
      provider_id: 9, identifier: 'staff-selected-model', name: 'Model', capabilities: ['text_generation'],
      max_output_tokens: 100, capability_source: 'https://example.com/models', enabled: true,
      input_price_usd_per_million: null, output_price_usd_per_million: null, pricing_source: '',
      access_tier: 'unknown', privacy_policy_url: '',
    }]);
  });

  it.each(['en', 'tr'] as const)('keeps system AI routing staff-only and submits priced standard model limits in %s', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    const harness = await RouterTestingHarness.create('/account/provider-settings');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe(language);
    expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe(language === 'tr' ? 'Yapay zekâ sağlayıcı kimlik bilgileri' : 'AI provider credentials');
    await harness.fixture.whenStable();
    expect(harness.routeNativeElement?.querySelector('#system-route-model')).toBeNull();
    api.platformProvidersResult = { status: 200, body: {
      providers: [{ id: 9, key: 'native', name: 'Provider', kind: 'openai', enabled: true }],
      accounts: [{ id: 8, provider_id: 9, label: 'Platform', state: 'active', stored: true }], has_more: false,
    } };
    api.platformModelsResult = { status: 200, body: {
      models: [{ id: 3, provider_id: 9, identifier: 'selected', name: 'Model',
        capabilities: ['text_generation'], enabled: true, max_output_tokens: 200,
        capability_source: 'https://example.com/models', input_price_usd_per_million: '0.1250',
        output_price_usd_per_million: '2.5000', pricing_source: 'https://example.com/prices',
        access_tier: 'standard', privacy_policy_url: '' }], has_more: false,
      capability_choices: ['text_generation'],
    } };
    api.platformAIRoutingResult = { status: 200, body: { policy: null } };
    await harness.routeDebugElement?.componentInstance.load();
    await harness.routeDebugElement?.componentInstance.loadModels();
    await harness.routeDebugElement?.componentInstance.loadRouting();
    harness.fixture.detectChanges();
    const form = harness.routeNativeElement?.querySelector('#system-route-model')?.closest('form')!;
    form.querySelector<HTMLSelectElement>('#system-route-model')!.value = '3';
    form.querySelector<HTMLSelectElement>('#system-route-model')!.dispatchEvent(new Event('change'));
    harness.fixture.detectChanges();
    form.querySelector<HTMLSelectElement>('#system-route-account')!.value = '8';
    form.querySelector<HTMLInputElement>('#system-route-cost')!.value = '0.010000';
    expect(harness.routeNativeElement!.querySelector('label[for="system-route-cost"]')!.textContent).toContain(language === 'tr' ? 'azami tahmini USD maliyeti' : 'Maximum estimated USD cost');
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    expect(api.savedPlatformRoutes[0]).toEqual({ model_id: 3, account_id: 8, fallback_model_ids: [],
      max_output_tokens: 100, max_cost_usd: '0.010000', timeout_seconds: 30, revision: 0, policy_id: null });
    harness.routeDebugElement?.componentInstance.confirmRemoveRoute.set(true);
    await harness.routeDebugElement?.componentInstance.removeSystemRoute();
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'Sistem yapay zekâ modeli seçilmemiş.' : 'No system AI model is chosen.');
  });

  it.each(['en', 'tr'] as const)('uses explicit project model/account selection and reports a bounded job status in %s', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    api.projectsResult = { status: 200, body: { projects: [
      { id: 9, organization_id: 7, name: 'Authorized project', role: 'member' },
    ] } };
    api.aiCatalogResult = { status: 200, body: {
      models: [{ id: 3, provider_id: 5, name: 'Model', identifier: 'choice', max_output_tokens: 200,
        access_tier: 'standard', price_known: true, privacy_policy_url: '' }],
      accounts: [{ id: 4, provider_id: 5, label: 'Own key', source: 'organization' }],
      estimate_units: 1, cost_status: 'unknown', has_more: false,
    } };
    const harness = await RouterTestingHarness.create('/app/ai-text/7/9');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain('Authorized project');
    const root = harness.routeNativeElement!, component = harness.routeDebugElement!.componentInstance;
    expect(root.querySelector('section')?.getAttribute('lang')).toBe(language);
    expect(root.textContent).toContain(language === 'tr' ? 'sağlayıcının bildirdiği gerçek ücret değildir' : 'not a provider-reported actual charge');
    expect(root.querySelector('h1')?.textContent).toBe(language === 'tr' ? 'Bu proje için bir model seçin' : 'Select a model for this project');
    expect(root.querySelector('span[lang=""]')?.textContent).toBe('Authorized project');
    const form = harness.routeNativeElement?.querySelector('form')!;
    const model = form.querySelector<HTMLSelectElement>('#ai-model')!;
    model.value = '3';
    model.dispatchEvent(new Event('change'));
    harness.fixture.detectChanges();
    form.querySelector<HTMLSelectElement>('#ai-account')!.value = '4';
    expect(form.querySelector('#ai-prompt')?.getAttribute('lang')).toBe('');
    expect(form.querySelector<HTMLInputElement>('#ai-tokens')!.max).toBe('200');
    form.querySelector<HTMLTextAreaElement>('#ai-prompt')!.value = 'Approved notes';
    form.querySelector<HTMLInputElement>('#ai-max-cost')!.value = '0.010000';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.aiRequests[0]['model_id']).toBe(3);
    expect(api.aiRequests[0]['account_id']).toBe(4);
    expect(api.aiRequests[0]['max_cost_usd']).toBe('0.010000');
    expect(api.aiRequests[0]['allow_free']).toBe(false);
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'İş 77' : 'Job 77');
    expect([...root.querySelectorAll('[lang="en"]')].some(node => node.textContent === 'queued')).toBe(true);
    const cancel = vi.spyOn(api, 'cancelAIText');
    [...root.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent === (language === 'tr' ? 'İptal isteyin' : 'Request cancellation'))!.click();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(cancel).toHaveBeenCalledOnce();
    expect(root.querySelector('[role="alert"]')?.textContent).toContain(language === 'tr' ? 'İptal sonucu bilinmiyor' : 'Cancellation outcome is unknown');
    cancel.mockRestore();
    await harness.routeDebugElement?.componentInstance.refresh();
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain('Result text');
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'Sağlayıcının bildirdiği ücret: bilinmiyor' : 'Provider-reported charge: unknown');
    expect(root.querySelector('pre[lang=""]')?.textContent).toBe('Result text');
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'Bildirilen girdi belirteçleri: 12' : 'Reported input tokens: 12');
    api.aiHistoryResult = { status: 200, body: { jobs: [{ id: 77, status: 'succeeded',
      model_id: 3, updated_at: '2026-09-27T00:01:00Z', request_status: 'completed', attempted_units: 1,
      estimated_cost_usd: '0.000014', reported_cost_usd: null }], has_more: false } };
    await harness.routeDebugElement?.componentInstance.loadHistory();
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'Bu projenin son yapay zekâ istekleri' : 'Recent AI requests for this project');
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'sağlayıcının bildirdiği ücret bilinmiyor' : 'provider-reported charge unknown');
    const reads = vi.spyOn(api, 'aiTextHistory');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(root.querySelector('section')?.getAttribute('lang')).toBe(language === 'tr' ? 'en' : 'tr');
    expect(root.querySelector('pre[lang=""]')?.textContent).toBe('Result text');
    expect(api.aiRequests).toHaveLength(1); expect(reads).not.toHaveBeenCalled(); reads.mockRestore();
    component.productLanguage.set(language); harness.fixture.detectChanges();
    [...root.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent?.includes(language === 'tr' ? 'İşi inceleyin' : 'Inspect job'))!.click();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(root.querySelector('pre[lang=""]')?.textContent).toBe('Result text');
  });

  it.each(['en', 'tr'] as const)('uses an authorized project default without silently switching to a free model in %s', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    api.projectsResult = { status: 200, body: { projects: [
      { id: 9, organization_id: 7, name: 'Authorized project', role: 'owner' },
    ] } };
    api.aiCatalogResult = { status: 200, body: {
      models: [{ id: 3, provider_id: 5, name: 'Standard', identifier: 'standard', max_output_tokens: 200,
        access_tier: 'standard', price_known: true, privacy_policy_url: '' },
      { id: 4, provider_id: 5, name: 'Free', identifier: 'free', max_output_tokens: 200,
        access_tier: 'free', price_known: true, privacy_policy_url: 'https://example.com/privacy' }],
      accounts: [{ id: 6, provider_id: 5, label: 'Platform', source: 'platform' }],
      estimate_units: 1, cost_status: 'unknown', has_more: false,
    } };
    const policy = { id: 31, project_id: 9, model_id: 3, account_id: 6, fallback_model_ids: [],
      max_output_tokens: 100, max_cost_usd: '0.010000', timeout_seconds: 10, revision: 1 };
    api.projectAIRoutingResult = { status: 200, body: { policy, effective: policy } };
    const harness = await RouterTestingHarness.create('/app/ai-text/7/9');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const form = harness.routeNativeElement?.querySelector('#ai-model')?.closest('form')!;
    form.querySelector<HTMLSelectElement>('#ai-model')!.value = 'default';
    form.querySelector<HTMLSelectElement>('#ai-model')!.dispatchEvent(new Event('change'));
    harness.fixture.detectChanges();
    expect(form.querySelector<HTMLSelectElement>('#ai-account')!.disabled).toBe(true);
    expect(form.querySelector('#ai-free-consent')).toBeNull();
    expect(form.querySelector<HTMLInputElement>('#ai-tokens')!.max).toBe('100');
    expect(form.querySelector('option[value="default"]')?.textContent).toContain(language === 'tr' ? 'proje' : 'project');
    form.querySelector<HTMLTextAreaElement>('#ai-prompt')!.value = 'Approved notes';
    form.querySelector<HTMLInputElement>('#ai-max-cost')!.value = '0.010000';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    expect(api.aiRequests[0]['model_id']).toBeNull();
    expect(api.aiRequests[0]['account_id']).toBeNull();
    expect(api.aiRequests[0]['allow_free']).toBe(false);

    const root = harness.routeNativeElement!;
    expect(root.querySelector('section')?.getAttribute('lang')).toBe(language);
    expect(root.textContent).toContain(language === 'tr' ? 'Başarısız bir sağlayıcı isteği asla' : 'A failed provider request never');
    const policyForm = harness.routeNativeElement?.querySelector('#project-route-model')?.closest('form')!;
    policyForm.querySelector<HTMLSelectElement>('#project-route-model')!.value = '3';
    policyForm.querySelector<HTMLSelectElement>('#project-route-model')!.dispatchEvent(new Event('change'));
    harness.fixture.detectChanges();
    expect(policyForm.querySelector('option[value="4"]')).toBeNull();
    policyForm.querySelector<HTMLSelectElement>('#project-route-account')!.value = '6';
    policyForm.querySelector<HTMLInputElement>('#project-route-cost')!.value = '0.020000';
    policyForm.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    expect(api.savedProjectRoutes[0]['model_id']).toBe(3);
    expect(api.savedProjectRoutes[0]['revision']).toBe(1);
    expect(api.savedProjectRoutes[0]['policy_id']).toBe(31);
    expect(api.savedProjectRoutes[0]['fallback_model_ids']).toEqual([]);
    harness.fixture.detectChanges();
    const remove = vi.spyOn(api, 'removeProjectAIRouting');
    const panel = root.querySelector('[aria-labelledby="project-route-title"]')!;
    [...panel.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent === (language === 'tr' ? 'Proje varsayılanını kaldırın' : 'Remove project default'))!.click();
    harness.fixture.detectChanges(); expect(remove).not.toHaveBeenCalled();
    expect(panel.querySelector('[role="alert"]')?.textContent).toContain(language === 'tr' ? 'doğrulanmış sistem varsayılanı' : 'verified system default');
    [...panel.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent === (language === 'tr' ? 'Kaldırmayı onaylayın' : 'Confirm removal'))!.click();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(remove).toHaveBeenCalledOnce(); remove.mockRestore();
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'Proje geçersiz kılması yok' : 'No project override');
  });

  it.each(['en', 'tr'] as const)('clears a write-only Google OAuth client secret after staff configuration in %s', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    api.googleApplicationResult = { status: 200, body: { state: 'unconfigured', redirect_uri: '' } };
    const harness = await RouterTestingHarness.create('/account/provider-settings');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe(language);
    expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe(language === 'tr' ? 'Yapay zekâ sağlayıcı kimlik bilgileri' : 'AI provider credentials');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const form = harness.routeNativeElement?.querySelector('form') as HTMLFormElement;
    form.querySelector<HTMLInputElement>('input[name="client_id"]')!.value = 'fixture-client';
    const secret = form.querySelector<HTMLInputElement>('input[name="client_secret"]')!;
    secret.value = 'dummy-google-secret';
    form.querySelector<HTMLInputElement>('input[name="redirect_uri"]')!.value =
      'https://app.example.com/api/integrations/google-search-console/oauth/callback/';
    expect(harness.routeNativeElement!.querySelector('label[for="google-client-secret"]')!.textContent).toContain(language === 'tr' ? 'Google istemci sırrı' : 'Google client secret');
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.savedGoogleSecrets).toEqual(['dummy-google-secret']);
    expect(secret.value).toBe('');
    expect(harness.routeNativeElement?.textContent).not.toContain('dummy-google-secret');
    const message = harness.routeNativeElement!.querySelector('section > p[role="status"][lang]')!;
    expect(message.getAttribute('lang')).toBe(language);
    expect(message.textContent).toBe(language === 'tr' ? 'Search Console uygulaması kaydedildi. Mevcut müşteri yetkileri ayrı kalır.' : 'Search Console application saved. Existing customer grants remain separate.');
  });

  it.each(['en', 'tr'] as const)('uses independent write-only Analytics staff credentials in %s', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    const harness = await RouterTestingHarness.create('/account/provider-settings');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe(language);
    expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe(language === 'tr' ? 'Yapay zekâ sağlayıcı kimlik bilgileri' : 'AI provider credentials');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const form = harness.routeNativeElement?.querySelector('#analytics-client-id')?.closest('form')!;
    form.querySelector<HTMLInputElement>('input[name="client_id"]')!.value = 'analytics-fixture';
    const secret = form.querySelector<HTMLInputElement>('input[name="client_secret"]')!;
    secret.value = 'analytics-fixture-secret';
    form.querySelector<HTMLInputElement>('input[name="redirect_uri"]')!.value =
      'https://app.example.com/api/integrations/google-analytics/oauth/callback/';
    expect(harness.routeNativeElement!.querySelector('label[for="analytics-client-secret"]')!.textContent).toContain(language === 'tr' ? 'Analytics istemci sırrı' : 'Analytics client secret');
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.savedAnalyticsSecrets).toEqual(['analytics-fixture-secret']);
    expect(api.savedGoogleSecrets).toEqual([]);
    expect(secret.value).toBe('');
    expect(harness.routeNativeElement?.textContent).not.toContain('analytics-fixture-secret');
    const message = harness.routeNativeElement!.querySelector('section > p[role="status"][lang]')!;
    expect(message.getAttribute('lang')).toBe(language);
    expect(message.textContent).toBe(language === 'tr' ? 'Analytics uygulaması kaydedildi. Mevcut müşteri yetkileri ayrı kalır.' : 'Analytics application saved. Existing customer grants remain separate.');
  });

  it.each(['en', 'tr'] as const)('uses a dedicated Business Profile staff app and clears its write-only secret even on failure in %s', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    const harness = await RouterTestingHarness.create('/account/provider-settings');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe(language);
    expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe(language === 'tr' ? 'Yapay zekâ sağlayıcı kimlik bilgileri' : 'AI provider credentials');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const form = harness.routeNativeElement!.querySelector('#business-client-id')!.closest('form')!;
    form.querySelector<HTMLInputElement>('[name="client_id"]')!.value = 'business-fixture';
    const secret = form.querySelector<HTMLInputElement>('[name="client_secret"]')!;
    secret.value = 'business-private-secret';
    form.querySelector<HTMLInputElement>('[name="redirect_uri"]')!.value =
      'https://app.example.invalid/api/integrations/google-business-profile/oauth/callback/';
    expect(harness.routeNativeElement!.querySelector('label[for="business-client-secret"]')!.textContent).toContain(language === 'tr' ? 'Business Profile istemci sırrı' : 'Business Profile client secret');
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.savedBusinessSecrets).toEqual(['business-private-secret']);
    expect(api.savedGoogleSecrets).toEqual([]); expect(api.savedAnalyticsSecrets).toEqual([]);
    expect(secret.value).toBe('');
    expect(harness.routeNativeElement!.textContent).not.toContain('business-private-secret');
    const message = harness.routeNativeElement!.querySelector('section > p[role="status"][lang]')!;
    expect(message.getAttribute('lang')).toBe(language);
    expect(message.textContent).toBe(language === 'tr' ? 'Business Profile uygulaması kaydedildi. Mevcut müşteri yetkileri ayrı kalır.' : 'Business Profile application saved. Existing customer grants remain separate.');
    vi.spyOn(api, 'platformGoogleBusinessApp').mockRejectedValueOnce(new Error('private error'));
    form.querySelector<HTMLInputElement>('[name="client_id"]')!.value = 'business-fixture';
    form.querySelector<HTMLInputElement>('[name="redirect_uri"]')!.value =
      'https://app.example.invalid/api/integrations/google-business-profile/oauth/callback/';
    secret.value = 'failed-private-secret';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(secret.value).toBe(''); expect(harness.routeNativeElement!.textContent).not.toContain('private error');
    expect(harness.routeNativeElement!.querySelector('[role="alert"]')!.textContent).toContain(language === 'tr' ? 'Google uygulaması kaydedilmedi' : 'Google application was not saved');
  });

  it.each(['en', 'tr'] as const)('offers only server-listed Business Profile closure revocation with owner reauthentication (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    api.closureStatusResult = { status: 200, body: { ...api.closureStatusResult.body, state: 'closed',
      closed_at: '2026-10-01T02:00:00Z', pending_grants: { search_console: [], analytics: [], business_profile: [44] },
      remote_revocation_pending: { search_console: 0, analytics: 0, business_profile: 1 } } };
    const harness = await RouterTestingHarness.create('/app/closure-status/7');
    await harness.routeDebugElement?.componentInstance.load(); harness.fixture.detectChanges();
    const form = harness.routeNativeElement!.querySelector('#grant-revoke-password')!.closest('form')!;
    expect(form.textContent).toContain((language === 'tr' ? 'Business Profile yetkisi 44' : 'Business Profile grant 44'));
    form.querySelector<HTMLInputElement>('[name="password"]')!.value = 'owner-password';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.closureGrantAttempts).toEqual([{ organizationId: 7, provider: 'business_profile', grantId: 44 }]);
    expect(api.closureRequests).toEqual([]);
  });

  it.each(['en', 'tr'] as const)('submits a sandbox-only seller catalog and clears both write-only secrets in %s', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    const harness = await RouterTestingHarness.create('/account/provider-settings');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe(language);
    expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe(language === 'tr' ? 'Yapay zekâ sağlayıcı kimlik bilgileri' : 'AI provider credentials');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const form = harness.routeNativeElement?.querySelector('#paddle-environment')?.closest('form')!;
    const key = form.querySelector<HTMLInputElement>('#paddle-api-key')!;
    const webhook = form.querySelector<HTMLInputElement>('#paddle-webhook-secret')!;
    const token = form.querySelector<HTMLInputElement>('#paddle-client-token')!;
    key.value = 'sandbox-key-private'; webhook.value = 'sandbox-webhook-private';
    token.value = 'test_' + 'a'.repeat(27);
    form.querySelector<HTMLInputElement>('#paddle-product')!.value = 'pro_' + 'a'.repeat(26);
    form.querySelector<HTMLInputElement>('#paddle-price')!.value = 'pri_' + 'b'.repeat(26);
    expect(form.textContent).toContain(language === 'tr' ? 'müşteri ödemelerini etkinleştirmez' : 'activate customer payments');
    expect(harness.routeNativeElement!.querySelector('label[for="paddle-webhook-secret"]')!.textContent).toContain(language === 'tr' ? 'Webhook doğrulama sırrı' : 'Webhook verification secret');
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.savedPaddle).toEqual([{ environment: 'sandbox', payload: {
      api_key: 'sandbox-key-private', webhook_secret: 'sandbox-webhook-private', client_token: 'test_' + 'a'.repeat(27),
      product_id: 'pro_' + 'a'.repeat(26), price_id: 'pri_' + 'b'.repeat(26),
      currency: 'USD', amount: '14900', interval: 'month', frequency: 1,
    } }]);
    expect(key.value).toBe(''); expect(webhook.value).toBe(''); expect(token.value).toBe('');
    expect(harness.routeNativeElement?.textContent).not.toContain('sandbox-webhook-private');
    const status = harness.routeNativeElement!.querySelector<HTMLParagraphElement>('p[role="status"][lang]')!;
    const english = 'sandbox seller settings stored. Catalog remains unverified; checkout is unavailable.';
    expect((harness.routeDebugElement!.componentInstance as ProviderSettings).message()).toBe(english);
    expect(status.textContent).toBe(language === 'tr'
      ? 'sandbox satıcı ayarları kaydedildi. Katalog hâlâ doğrulanmamıştır; ödeme kullanılamaz.' : english);
    expect(status.lang).toBe(language);
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'katalog sağlayıcı tarafından doğrulanmamış' : 'catalog not provider-verified');
  });

  it.each(['en', 'tr'] as const)('keeps exact seller environment and confirmation in dynamic rotation and revoke acknowledgments in %s', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    api.paddleStatuses['live'] = 'active';
    const rotate = vi.spyOn(api, 'rotatePlatformPaddleApiKey').mockResolvedValue({ status: 200, body: { rotated: true } });
    const revoke = vi.spyOn(api, 'revokePlatformPaddleSeller');
    const harness = await RouterTestingHarness.create('/account/provider-settings');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const root = harness.routeNativeElement!, component = harness.routeDebugElement!.componentInstance as ProviderSettings;
    const form = root.querySelector('#paddle-rotate-api-key')!.closest('form')!;
    const key = form.querySelector<HTMLInputElement>('#paddle-rotate-api-key')!;
    key.value = 'pdl_live_apikey_' + 'a'.repeat(54);
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(rotate).toHaveBeenCalledExactlyOnceWith('live', 'pdl_live_apikey_' + 'a'.repeat(54));
    expect(key.value).toBe('');
    const status = root.querySelector<HTMLParagraphElement>('p[role="status"][lang]')!;
    const english = 'live seller API key rotated; webhook secret and catalog remain unchanged.';
    expect(component.message()).toBe(english);
    expect(status.textContent).toBe(language === 'tr'
      ? 'live satıcı API anahtarı yenilendi; webhook sırrı ve katalog değişmedi.' : english);
    expect(status.lang).toBe(language);
    const seller = root.querySelector('#paddle-seller-title')!.closest('section')!;
    const open = Array.from(seller.querySelectorAll<HTMLButtonElement>('button')).find(button => button.textContent?.includes('live'))!;
    open.click(); harness.fixture.detectChanges(); expect(revoke).not.toHaveBeenCalled();
    const confirm = Array.from(seller.querySelectorAll<HTMLButtonElement>('button')).find(button => button.textContent === (language === 'tr' ? 'İptali onaylayın' : 'Confirm revoke'))!;
    confirm.click(); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(revoke).toHaveBeenCalledExactlyOnceWith('live');
    expect(component.message()).toBe('live seller secrets removed.');
    expect(status.textContent).toBe(language === 'tr' ? 'live satıcı sırları kaldırıldı.' : 'live seller secrets removed.');
    expect(status.lang).toBe(language); expect(api.billingRequests).toEqual([]);
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    try {
      buildEnvironment.production = true;
      api.paddleStatuses['live'] = 'active';
      await harness.navigateByUrl('/');
      await harness.navigateByUrl('/account/provider-settings');
      const fresh = harness;
      await fresh.fixture.whenStable(); fresh.fixture.detectChanges();
      const freshComponent = fresh.routeDebugElement!.componentInstance as ProviderSettings;
      expect(freshComponent.productLanguage()).toBe(language);
      const freshSeller = fresh.routeNativeElement!.querySelector('#paddle-seller-title')!.closest('section')!;
      Array.from(freshSeller.querySelectorAll<HTMLButtonElement>('button')).find(button => button.textContent?.includes('live'))!.click();
      fresh.fixture.detectChanges();
      Array.from(freshSeller.querySelectorAll<HTMLButtonElement>('button')).find(button => button.textContent === 'Confirm revoke')!.click();
      await fresh.fixture.whenStable(); fresh.fixture.detectChanges();
      expect(freshComponent.message()).toBe('live seller secrets removed.');
      const freshStatus = fresh.routeNativeElement!.querySelector<HTMLParagraphElement>('p[role="status"][lang]')!;
      expect(freshStatus.lang).toBe('en'); expect(freshStatus.textContent).toBe('live seller secrets removed.');
    } finally { buildEnvironment.production = production; }
    expect(rotate).toHaveBeenCalledTimes(1); expect(revoke).toHaveBeenCalledTimes(2);
  });

  it.each(['en', 'tr'] as const)('submits one audited staff billing receipt retry without any payment request in %s', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    api.receiptInspection = { method_version: 'exact-staff-retained-paddle-receipt-v1',
      scope: 'retained_global_receipt_not_tenant_paid_truth_lifetime_attempts_or_retry_authority', source_digest: 'a'.repeat(64),
      receipt: { id: 42, environment: 'sandbox', state: 'failed', attempts: 1, error_category: 'timeout',
        received_at: '2026-01-01T00:00:00.000001+00:00', claimed_at: '2026-01-01T00:00:00.000002+00:00', retry_after: null, processed_at: null } };
    const harness = await RouterTestingHarness.create('/account/provider-settings');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe(language);
    expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe(language === 'tr' ? 'Yapay zekâ sağlayıcı kimlik bilgileri' : 'AI provider credentials');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const root = harness.routeNativeElement!, inspector = root.querySelector('app-staff-receipt-inspector')!;
    expect(api.inspectedPaddleReceipts).toEqual([]); expect(inspector.textContent).not.toContain(language === 'tr' ? 'Kayıtlı alındı 42' : 'Recorded receipt 42');
    const selected = inspector.querySelector<HTMLInputElement>('#receipt-inspect-id')!;
    selected.value = '42'; selected.dispatchEvent(new Event('input', { bubbles: true }));
    const inspect = async () => {
      selected.closest('form')!.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
      await harness.fixture.whenStable(); harness.fixture.detectChanges();
    };
    await inspect(); expect(inspector.textContent).toContain(language === 'tr' ? 'Kayıtlı alındı 42' : 'Recorded receipt 42');
    expect(api.retriedPaddleReceipts).toEqual([]);
    let finish!: (result: { status: number; body: { queued: boolean } }) => void;
    vi.spyOn(api, 'retryPlatformPaddleReceipt').mockImplementation((id, reason) => {
      api.retriedPaddleReceipts.push({ id, reason }); return new Promise(resolve => finish = resolve);
    });
    const form = harness.routeNativeElement?.querySelector('#paddle-receipt-id')?.closest('form')!;
    form.querySelector<HTMLInputElement>('#paddle-receipt-id')!.value = '42';
    form.querySelector<HTMLInputElement>('#paddle-retry-reason')!.value = 'Provider recovered';
    expect(harness.routeNativeElement!.querySelector('label[for="paddle-retry-reason"]')!.textContent).toContain(language === 'tr' ? 'yeniden denemenin nedeni' : 'Reason for this audited retry');
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    harness.fixture.detectChanges(); expect(inspector.textContent).not.toContain(language === 'tr' ? 'Kayıtlı alındı 42' : 'Recorded receipt 42');
    await inspect(); expect(inspector.textContent).toContain(language === 'tr' ? 'Kayıtlı alındı 42' : 'Recorded receipt 42');
    finish({ status: 202, body: { queued: true } });
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.retriedPaddleReceipts).toEqual([{ id: 42, reason: 'Provider recovered' }]);
    const status = root.querySelector<HTMLParagraphElement>('p[role="status"][lang]')!;
    const english = 'Billing receipt 42 queued for current-provider reconciliation; status is not yet changed.';
    expect((harness.routeDebugElement!.componentInstance as ProviderSettings).message()).toBe(english);
    expect(status.textContent).toBe(language === 'tr'
      ? 'Faturalama alındısı 42, mevcut sağlayıcıyla mutabakat için kuyruğa alındı; durum henüz değişmedi.' : english);
    expect(status.lang).toBe(language);
    expect(api.billingRequests).toEqual([]);
    expect(inspector.textContent).not.toContain(language === 'tr' ? 'Kayıtlı alındı 42' : 'Recorded receipt 42');
    expect(api.inspectedPaddleReceipts).toEqual([{ id: 42, reason: 'investigation' }, { id: 42, reason: 'investigation' }]);
  });

  it.each(['en', 'tr'] as const)('shows sanitized uncertain notice status and requires duplicate acknowledgment before reissue in %s', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    api.noticeInspection = { method_version: 'scoped-staff-organization-notice-v1', organization_id: 7,
      scope: 'recorded_transport_not_inbox_delivery_current_eligibility_reissue_billing_or_account_mail_authority', source_digest: 'a'.repeat(64),
      notice: { id: 17, kind: 'trial_ending', state: 'unknown', manual_retries: 0,
        created_at: '2026-01-01T00:00:00.000001+00:00', attempted_at: '2026-01-01T00:00:01+00:00', sent_at: null } };
    const harness = await RouterTestingHarness.create('/account/provider-settings');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe(language);
    expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe(language === 'tr' ? 'Yapay zekâ sağlayıcı kimlik bilgileri' : 'AI provider credentials');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    expect(api.inspectedNotices).toEqual([]);
    expect(root.textContent).not.toContain(language === 'tr' ? 'Bildirim 17' : 'Notice 17');
    const inspector = root.querySelector('#notice-inspect-id')!.closest('form')!;
    for (const [id, value] of [['notice-inspect-organization', '7'], ['notice-inspect-id', '17']]) {
      const input = inspector.querySelector<HTMLInputElement>('#' + id)!;
      input.value = value; input.dispatchEvent(new Event('input', { bubbles: true }));
    }
    inspector.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(root.textContent).toContain(language === 'tr' ? 'Bildirim 17' : 'Notice 17');
    expect(api.inspectedNotices).toEqual([{ organization: 7, notice: 17, reason: 'investigation' }]);
    const form = root.querySelector('#unknown-notice-id')!.closest('form')!;
    form.querySelector<HTMLInputElement>('#unknown-notice-id')!.value = '17';
    form.querySelector<HTMLInputElement>('#unknown-notice-reason')!.value = 'Reviewed possible duplicate';
    expect(harness.routeNativeElement!.querySelector('label[for="unknown-notice-id"]')!.textContent).toContain(language === 'tr' ? 'belirsiz bildirim kimliği' : 'Uncertain notice ID');
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.retriedUnknownNotices).toEqual([]);
    form.querySelector<HTMLInputElement>('input[name="acknowledged"]')!.checked = true;
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.retriedUnknownNotices).toEqual([{ id: 17, reason: 'Reviewed possible duplicate' }]);
    const status = root.querySelector<HTMLParagraphElement>('p[role="status"][lang]')!;
    const component = harness.routeDebugElement!.componentInstance as ProviderSettings;
    const english = 'Notice 17 queued for one reviewed reissue. A duplicate remains possible.';
    expect(component.message()).toBe(english);
    expect(status.textContent).toBe(language === 'tr'
      ? 'Bildirim 17, incelenmiş tek bir yeniden gönderim için kuyruğa alındı. Yinelenen gönderim hâlâ mümkündür.' : english);
    expect(status.lang).toBe(language);
    const input = form.querySelector<HTMLInputElement>('#unknown-notice-reason')!;
    input.value = 'Unsubmitted human review'; input.focus();
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(root.querySelector('p[role="status"][lang]')).toBe(status);
    expect(status.lang).toBe(language === 'tr' ? 'en' : 'tr');
    expect(status.textContent).toContain(language === 'tr' ? 'A duplicate remains possible' : 'Yinelenen gönderim hâlâ mümkündür');
    expect(component.message()).toBe(english); expect(input.value).toBe('Unsubmitted human review');
    expect(document.activeElement).toBe(input);
    expect(api.retriedUnknownNotices).toEqual([{ id: 17, reason: 'Reviewed possible duplicate' }]);
    expect(root.querySelector('app-staff-notice-inspector')?.textContent).not.toContain(language === 'tr' ? 'Bildirim 17' : 'Notice 17');
    expect(api.inspectedNotices.length).toBe(1);
  });

  it.each(['en', 'tr'] as const)('requires staff review confirmation before clearing a bounced address suppression in %s', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    api.emailFeedbackInspection = { method_version: 'scoped-staff-retained-email-feedback-v1', user_id: 7, email_address_id: 9,
      scope: 'current_record_first_feedback_not_original_recipient_provider_occurrence_current_applicability_or_clearance_authority', source_digest: 'a'.repeat(64),
      suppression: { id: 19, reason: 'permanent_bounce', created_at: '2026-01-01T00:00:00.000002+00:00' },
      feedback: { id: 21, kind: 'permanent_bounce', received_at: '2026-01-01T00:00:00.000001+00:00' } };
    const harness = await RouterTestingHarness.create('/account/provider-settings');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe(language);
    expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe(language === 'tr' ? 'Yapay zekâ sağlayıcı kimlik bilgileri' : 'AI provider credentials');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    expect(api.suppressionDiscoveryCalls).toBe(0); expect(api.inspectedEmailFeedback).toEqual([]);
    const inspector = root.querySelector('app-staff-feedback-inspector')!;
    expect(inspector.textContent).not.toContain(language === 'tr' ? 'Engelleme 19' : 'Suppression 19');
    const inspectionForm = root.querySelector('#feedback-inspect-user')!.closest('form')!;
    for (const [id, value] of [['feedback-inspect-user', '7'], ['feedback-inspect-address', '9'], ['feedback-inspect-suppression', '19']]) {
      const input = inspectionForm.querySelector<HTMLInputElement>('#' + id)!;
      input.value = value; input.dispatchEvent(new Event('input', { bubbles: true }));
    }
    inspectionForm.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.inspectedEmailFeedback).toEqual([{ user: 7, address: 9, suppression: 19, reason: 'investigation' }]);
    expect(inspector.textContent).toContain(language === 'tr' ? 'Engelleme 19' : 'Suppression 19');
    const form = root.querySelector('#email-suppression-id')!.closest('form')!;
    form.querySelector<HTMLInputElement>('#email-suppression-id')!.value = '19';
    form.querySelector<HTMLInputElement>('#email-suppression-reason')!.value = 'Verified address recovery';
    expect(harness.routeNativeElement!.querySelector('label[for="email-suppression-id"]')!.textContent).toContain(language === 'tr' ? 'Engelleme kimliği' : 'Suppression ID');
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    expect(api.clearedEmailSuppressions).toEqual([]);
    form.querySelector<HTMLInputElement>('input[name="confirmed"]')!.checked = true;
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.clearedEmailSuppressions).toEqual([{ id: 19, reason: 'Verified address recovery' }]);
    const status = root.querySelector<HTMLParagraphElement>('p[role="status"][lang]')!;
    const english = 'Suppression 19 cleared after review. A new provider failure may suppress it again.';
    expect((harness.routeDebugElement!.componentInstance as ProviderSettings).message()).toBe(english);
    expect(status.textContent).toBe(language === 'tr'
      ? 'Engelleme 19, incelemeden sonra kaldırıldı. Yeni bir sağlayıcı hatası yeniden engellemeye neden olabilir.' : english);
    expect(status.lang).toBe(language);
    expect(inspector.textContent).not.toContain(language === 'tr' ? 'Engelleme 19' : 'Suppression 19');
    expect(api.inspectedEmailFeedback.length).toBe(1); expect(api.suppressionDiscoveryCalls).toBe(0);
  });

  it('deliberately inspects exact current account mail without purpose discovery or token replay', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.accountMailInspection = { method_version: 'scoped-staff-current-account-mail-v1', user_id: 7, email_address_id: 9,
      scope: 'current_record_linkage_not_original_recipient_purpose_inbox_current_suppression_or_resend_authority', source_digest: 'a'.repeat(64),
      delivery: { id: 21, state: 'unknown', attempted_at: '2026-01-01T00:00:00.000001+00:00', finished_at: '2026-01-01T00:00:00.000002+00:00' } };
    const harness = await RouterTestingHarness.create('/account/provider-settings');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    expect(api.inspectedAccountMail).toEqual([]); expect(root.textContent).not.toContain('Delivery 21');
    const form = root.querySelector('#mail-inspect-user')!.closest('form')!;
    for (const [id, value] of [['mail-inspect-user', '7'], ['mail-inspect-address', '9'], ['mail-inspect-delivery', '21']]) {
      const input = form.querySelector<HTMLInputElement>('#' + id)!;
      input.value = value; input.dispatchEvent(new Event('input', { bubbles: true }));
    }
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.inspectedAccountMail).toEqual([{ user: 7, address: 9, delivery: 21, reason: 'investigation' }]);
    const text = root.textContent;
    expect(text).toContain('Delivery 21');
    expect(text).toContain('cannot be replayed');
    expect(text).not.toContain('password_reset_key');
    expect(text).not.toContain('private-fixture-fragment');
    const input = form.querySelector<HTMLInputElement>('#mail-inspect-user')!;
    input.value = '8'; input.dispatchEvent(new Event('input', { bubbles: true })); harness.fixture.detectChanges();
    expect(root.textContent).not.toContain('Delivery 21');
  });

  it.each(['en', 'tr'] as const)('requires deliberate owner billing consent and never calls checkout on status load (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    const harness = await RouterTestingHarness.create('/app/billing/7');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'sağlayıcıda ödeme işlemi yapılandırılmamış' : 'Hosted checkout is not configured');
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Kuruluş faturalandırması — OrganicSEOOps' : 'Organization billing — OrganicSEOOps');
    const root = harness.routeNativeElement!;
    expect(root.querySelector('.workspace-panel')?.getAttribute('lang')).toBe(language);
    expect(root.querySelector('h1')?.textContent).toBe(language === 'tr' ? 'Kuruluş faturalandırması' : 'Organization billing');
    const text = root.textContent!;
    for (const phrase of language === 'tr'
      ? ['ayda 149 USD', 'vergiyi ve toplamı', 'kart gerekmez', 'aylık döneminiz hemen başlar', 'birimleri devredilmez', 'her ay yenilenir', 'ücretli dönemin sonunda', 'yalnızca kuruluş sahibi', 'ödemenin kanıtı değildir', 'incelenmemiş Türkçe']
      : ['USD 149 per month', 'tax and total', 'requires no card', 'starts immediately', 'units do not carry over', 'Renewal is monthly', 'end of the paid period', 'Only the organization owner', 'does not prove payment']) expect(text).toContain(phrase);
    expect(api.billingRequests).toEqual([]);
    api.billingResult = { status: 200, body: { seller_configured: true, offer_version: 'agency-launch-v1',
      can_start_new_checkout: true,
      subscription_linked: false, portal_available: false, billing_access_state: 'unverified', attempts: [] } };
    await harness.routeDebugElement?.componentInstance.load();
    harness.fixture.detectChanges();
    const button = [...harness.routeNativeElement!.querySelectorAll('button')]
      .find((item) => item.textContent?.includes(language === 'tr' ? 'Paddle’a devam et' : 'Continue to Paddle'))!;
    expect(button.disabled).toBe(true);
    const checkbox = harness.routeNativeElement!.querySelector<HTMLInputElement>('#billing-consent')!;
    expect(checkbox.labels?.[0].textContent).toContain(language === 'tr' ? 'hemen tahsil edilmesini' : 'immediate early-trial charge');
    checkbox.click(); harness.fixture.detectChanges();
    expect(button.disabled).toBe(false);
    button.click(); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.billingRequests).toHaveLength(1);
    expect(api.billingRequests[0].org).toBe(7);
    expect(api.billingRequests[0].key).toMatch(/^[a-f0-9-]{36}$/);
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'Ödeme henüz doğrulanmadı' : 'payment is not yet confirmed');
    expect(harness.routeNativeElement?.textContent).not.toContain('Payment complete');
    expect(root.textContent).toContain(language === 'tr' ? 'Ödeme işlemi hazırlandı' : 'A checkout is prepared');
    const component = harness.routeDebugElement!.componentInstance;
    const acknowledgment = root.querySelector<HTMLParagraphElement>('p[role="status"][lang]')!;
    const rawMessage = component.message(), attempts = component.attempts(), billingReads = api.billingReads.length;
    expect(rawMessage).toContain('A checkout is prepared.'); expect(acknowledgment.lang).toBe(language);
    const refresh = root.querySelector<HTMLButtonElement>('button')!;
    refresh.focus(); component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Organization billing — OrganicSEOOps' : 'Kuruluş faturalandırması — OrganicSEOOps');
    expect(root.querySelector('p[role="status"][lang]')).toBe(acknowledgment);
    expect(acknowledgment.lang).toBe(language === 'tr' ? 'en' : 'tr'); expect(acknowledgment.textContent).toBe(component.t(rawMessage));
    expect(component.message()).toBe(rawMessage); expect(component.attempts()).toBe(attempts);
    expect(root.querySelector('#billing-consent')).toBeNull(); expect(component.consented()).toBe(true);
    expect(root.querySelector('button')).toBe(refresh); expect(document.activeElement).toBe(refresh); expect(api.billingRequests).toHaveLength(1);
    expect(api.billingReads).toHaveLength(billingReads); component.productLanguage.set(language); harness.fixture.detectChanges();
    [...root.querySelectorAll<HTMLButtonElement>('button')].find(item => item.textContent?.includes(language === 'tr' ? 'Girişimi seç:' : 'Select attempt'))!.click(); harness.fixture.detectChanges();
    expect(root.querySelector('app-checkout-link-receipt section')?.getAttribute('lang')).toBe(language);
    expect(root.querySelector('app-checkout-link-receipt h2')?.textContent).toContain(language === 'tr' ? 'Tarayıcı bağlantı alındısı' : 'Browser link receipt');
    expect([...root.querySelectorAll('[lang="en"]')].some(item => item.textContent === 'ready')).toBe(true);
    const firstKey = api.billingRequests[0].key;
    await harness.routeDebugElement!.componentInstance.beginCheckout();
    expect(api.billingRequests.map(row => row.key)).toEqual([firstKey]);
    api.billingResult.body['attempts'] = [{ id: 91, state: 'unknown', created_at: '2026-01-01T00:00:00Z',
      payment_confirmed: false, payment_captured: true, checkout_url: null }];
    await harness.routeDebugElement!.componentInstance.load(); harness.fixture.detectChanges();
    expect(root.textContent).toContain(language === 'tr' ? 'Başka bir ödeme isteği göndermeyin' : 'Do not submit another payment request');
    expect(root.textContent).toContain(language === 'tr' ? 'mevcut aboneliğin mutabakatını bekler' : 'awaits current subscription reconciliation');
    expect([...root.querySelectorAll('button')].some(item => item.textContent?.includes(language === 'tr' ? 'Paddle ödeme işlemini incele' : 'Review Paddle checkout'))).toBe(false);
    harness.routeDebugElement!.componentInstance.openCheckout('https://foreign.invalid/account/billing/checkout?_ptxn=txn_' + 'a'.repeat(26));
    harness.fixture.detectChanges();
    expect(root.querySelector('[role="alert"]')?.textContent).toContain(language === 'tr' ? 'onaylı hesap sunucusunda değil' : 'not on the approved account host');
    const error = component.error(), alert = root.querySelector<HTMLParagraphElement>('[role="alert"]')!;
    expect(error).toContain('not on the approved account host'); expect(alert.lang).toBe(language);
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(root.querySelector('[role="alert"]')).toBe(alert); expect(alert.textContent).toBe(component.t(error));
    expect(alert.lang).toBe(language === 'tr' ? 'en' : 'tr'); expect(component.error()).toBe(error);
    expect(api.billingRequests).toHaveLength(1); expect(api.portalRequests).toEqual([]);

  });

  it('keeps organization billing English for denied malformed unavailable and fresh production preferences', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const preference = vi.spyOn(api, 'productLanguage'), buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    const harness = await RouterTestingHarness.create('/');
    try {
      for (const mode of ['denied', 'invalid', 'unavailable', 'production'] as const) {
        await harness.navigateByUrl('/'); buildEnvironment.production = mode === 'production';
        if (mode === 'unavailable') preference.mockRejectedValue(new Error('PRIVATE preference detail'));
        else preference.mockResolvedValue({ status: mode === 'denied' ? 403 : 200, body: {
          language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: 'en', current_email_language: 'en' } });
        await harness.navigateByUrl('/app/billing/7'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
        expect(TestBed.inject(Title).getTitle()).toBe('Organization billing — OrganicSEOOps');
        expect(harness.routeNativeElement!.querySelector('.workspace-panel')?.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement!.querySelector('h1')?.textContent).toBe('Organization billing');
        expect(harness.routeNativeElement!.textContent).not.toContain('incelenmemiş Türkçe');
        expect(harness.routeNativeElement!.textContent).not.toContain('PRIVATE preference detail');
        expect(api.billingRequests).toEqual([]); expect(api.portalRequests).toEqual([]);
      }
    } finally { buildEnvironment.production = production; preference.mockRestore(); }
  });

  it('rejects array owner checkout states before rendering controls or accepting a start response', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const attempt = { id: 91, state: 'ready', created_at: '2026-09-28T00:00:00Z',
      checkout_url: `${window.location.origin}/account/billing/checkout?_ptxn=txn_${'a'.repeat(26)}`,
      payment_confirmed: false, payment_captured: false };
    const valid = { ...api.billingResult.body, seller_configured: true, can_start_new_checkout: true,
      subscription_linked: true, attempts: [attempt] };
    api.billingResult.body = structuredClone(valid);
    const harness = await RouterTestingHarness.create('/app/billing/7');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const component = harness.routeDebugElement!.componentInstance;
    expect(component.denied()).toBe(false); expect(component.attempts()).toEqual([attempt]);
    expect(harness.routeNativeElement?.querySelector('#billing-consent')).not.toBeNull();
    for (const body of [
      ...['unverified', 'unavailable', 'paid_active', 'cancellation_scheduled', 'payment_grace',
        'read_only', 'retained_read_only', 'retention_elapsed', 'billing_review_hold']
        .map(state => ({ ...valid, billing_access_state: [state] })),
      ...['reserved', 'sending', 'unknown', 'ready', 'rejected', 'settled']
        .map(state => ({ ...valid, attempts: [{ ...attempt, state: [state] }] })),
    ]) {
      api.billingResult.body = body; await component.load(); harness.fixture.detectChanges();
      expect(component.denied()).toBe(true); expect(component.attempts()).toEqual([]);
      expect(harness.routeNativeElement?.querySelector('#billing-consent')).toBeNull();
    }
    expect(api.billingRequests).toEqual([]); expect(api.portalRequests).toEqual([]);
    api.billingResult.body = structuredClone(valid); await component.load(); component.consented.set(true);
    const start = vi.spyOn(api, 'startOrganizationCheckout');
    for (const state of ['ready', 'reserved', 'sending', 'unknown']) {
      start.mockResolvedValue({ status: 200, body: { state: [state] } });
      const reads = api.billingReads.length;
      await component.beginCheckout();
      expect(component.error()).toContain('Checkout could not be confirmed');
      expect(component.message()).toBe(''); expect(api.billingReads).toHaveLength(reads);
    }
    expect(start.mock.calls).toHaveLength(4);
    expect(new Set(start.mock.calls.map(([, key]) => key)).size).toBe(1);
    start.mockRestore();
  });

  it.each(['en', 'tr'] as const)('does not auto-open checkout from a pasted transaction URL or accept a foreign result (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    const txn = 'txn_' + 'a'.repeat(26);
    const harness = await RouterTestingHarness.create(`/account/billing/checkout?_ptxn=${txn}`);
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'mevcut hesabınız için kullanılamıyor' : 'checkout is unavailable');
    expect(document.querySelector('script[src*="paddle.com"]')).toBeNull();
    const root = harness.routeNativeElement!, component = harness.routeDebugElement!.componentInstance;
    const alert = root.querySelector<HTMLParagraphElement>('[role="alert"]')!, rawError = component.error();
    expect(rawError).toBe('This checkout is unavailable for your current account. Return to billing and refresh status.');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(root.querySelector('[role="alert"]')).toBe(alert); expect(alert.lang).toBe(language === 'tr' ? 'en' : 'tr');
    expect(alert.textContent).toBe(component.t(rawError)); expect(component.error()).toBe(rawError); expect(component.checkout()).toBeNull();
    component.productLanguage.set(language); harness.detectChanges();

    await harness.navigateByUrl('/');
    await harness.navigateByUrl('/account/billing/checkout?_ptxn=invalid'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement!.querySelector('[role="alert"]')?.textContent).toContain(language === 'tr' ? 'ödeme bağlantısı geçersiz' : 'payment link is invalid');
    const invalidRoot = harness.routeNativeElement!, invalid = harness.routeDebugElement!.componentInstance;
    const invalidAlert = invalidRoot.querySelector<HTMLParagraphElement>('[role="alert"]')!;
    expect(invalid.error()).toBe('This payment link is invalid. Return to your organization billing page.');
    invalid.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(invalidRoot.querySelector('[role="alert"]')).toBe(invalidAlert);
    expect(invalidAlert.textContent).toBe(invalid.t(invalid.error())); expect(invalid.checkout()).toBeNull();
    expect(document.querySelector('script[src*="paddle.com"]')).toBeNull(); expect(api.billingRequests).toEqual([]);
  });

  it.each(['en', 'tr'] as const)('shows first active server observation as immutable history and rejects foreign malformed or future proof metadata (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    const observation = { attempt_id: 91, source_digest: 'a'.repeat(64), observed_at: '2026-01-02T00:00:00Z',
      provider_occurred_at: '2026-01-01T00:00:00Z', environment: 'sandbox', offer_version: 'agency-launch-v1',
      currency_code: 'USD', interpretation: 'historical_first_active_server_observation_not_current_access_or_provider_activation_time' };
    const history = { method: 'first-active-observation-v1', organization_id: 7, state: 'recorded', observation };
    api.billingResult.body['first_paid_observation'] = structuredClone(history);
    const harness = await RouterTestingHarness.create('/app/billing/7');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const component = harness.routeDebugElement!.componentInstance;
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'geçmiş sunucu mutabakatı kanıtıdır' : 'historical server reconciliation evidence');
    expect(harness.routeNativeElement?.textContent).toContain('2026-01-02T00:00:00Z');
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'Ayrı imzalı sağlayıcı olayının zamanı' : 'separate signed provider event');
    expect(api.billingRequests).toEqual([]); expect(api.portalRequests).toEqual([]);
    const bad: Record<string, unknown>[] = [
      { ...history, organization_id: 8 }, { ...history, method: 'wrong' }, { ...history, state: 'unknown' },
      ...['recorded', 'not_observed', 'unknown'].map(state => ({ ...history, state: [state], observation: null })),
      ...[{ source_digest: '<script>' }, { attempt_id: true }, { currency_code: '<b>' },
        { environment: ['sandbox'] }, { environment: ['live'] },
        { observed_at: '2026-01-02T00:00:00' }, { observed_at: new Date(Date.now() + 60000).toISOString() },
        { provider_occurred_at: '2026-01-03T00:00:00Z' }].map(change => ({ ...history, observation: { ...observation, ...change } })),
    ];
    for (const value of bad) {
      api.billingResult.body['first_paid_observation'] = value;
      await component.load(); harness.fixture.detectChanges();
      expect(component.firstPaidObservation()).toBeNull();
      expect(harness.routeNativeElement?.textContent).not.toContain(observation.source_digest);
      expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'Bu kuruluş veya rol için faturalandırma durumu kullanılamıyor' : 'unavailable for this organization or role');
    }
    api.billingResult.body['first_paid_observation'] = { ...history, state: 'unknown', observation: null };
    await component.load(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'Mevcut faturalandırma durumu bunu yeniden oluşturamaz' : 'Current billing status cannot reconstruct it');
    expect(harness.routeNativeElement!.querySelector('time')).toBeNull();

  });

  it('clears first paid history on a new org or destroyed screen and ignores late billing reads', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const harness = await RouterTestingHarness.create('/app/billing/7');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const component = harness.routeDebugElement!.componentInstance;
    let resolve!: (value: ApiResult) => void;
    api.billingWait = new Promise<ApiResult>(done => { resolve = done; });
    const waiting = component.load(); expect(component.firstPaidObservation()).toBeNull();
    api.billingWait = null;
    await harness.navigateByUrl('/app/billing/8'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    resolve({ status: 200, body: { ...api.billingResult.body, first_paid_observation: {
      method: 'first-active-observation-v1', organization_id: 7, state: 'unknown', observation: null } } });
    await waiting;
    expect(harness.routeDebugElement!.componentInstance.firstPaidObservation().organization_id).toBe(8);
    await harness.navigateByUrl('/app');
    expect(component.firstPaidObservation()).toBeNull();
  });

  it.each(['en', 'tr'] as const)('deliberately inspects original paid server timing with owner preflight/final history and exact microsecond rounding (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    recordedPaidTiming(api);
    const harness = await RouterTestingHarness.create('/app/billing/7');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.paidTimingReads).toEqual([]);
    const component = harness.routeDebugElement!.componentInstance;
    [...harness.routeNativeElement!.querySelectorAll<HTMLButtonElement>('button')]
      .find(button => button.textContent?.includes(language === 'tr' ? 'Kaydedilen ücretli erişim sunucu zamanlamasını incele' : 'Inspect saved paid server timing'))!.click();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.paidTimingReads).toEqual([7]); expect(api.billingReads).toEqual([7, 7, 7]);
    const section = harness.routeNativeElement!.querySelector('section[aria-labelledby="paid-timing-title"]')!;
    expect(section.textContent).toContain(language === 'tr' ? '332 aşağı yuvarlanmış tam milisaniye' : '332 whole milliseconds, rounded down');
    expect(section.textContent).toContain(language === 'tr' ? 'kayıt veya denemeden itibaren geçen süreyi' : 'not time from registration or trial');
    expect(section.querySelector('time')?.getAttribute('datetime')).toBe('2026-01-01T00:00:00.000999+00:00');
    expect(api.billingRequests).toEqual([]); expect(api.portalRequests).toEqual([]);
    await component.load(); expect(component.paidTiming()).toBeNull();
    expect(api.paidTimingReads).toEqual([7]);
    expect([...section.querySelectorAll('time, code')].every(item => item.getAttribute('lang') === 'en')).toBe(true);

  });

  it.each(['en', 'tr'] as const)('rejects malformed or different original paid timing and leaves unknown/unobserved duration null (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    const original = recordedPaidTiming(api);
    const harness = await RouterTestingHarness.create('/app/billing/7');
    await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    const timing = original.body['timing'] as Record<string, unknown>;
    for (const change of [
      { method: 'wrong' }, { precision: 'seconds' }, { interpretation: 'conversion' }, { state: 'unknown' },
      { source_digest: 'b'.repeat(64) }, { source_digest: '<b>PRIVATE_TIMING</b>' }, { elapsed_milliseconds: 333 },
      { elapsed_milliseconds: -1 }, { elapsed_milliseconds: true }, { elapsed_milliseconds: 332.1 },
      { elapsed_milliseconds: Number.MAX_SAFE_INTEGER + 1 }, { observed_at: '2026-01-01T00:00:00.333002+00:00' },
      { tracking_started_at: '2026-01-01T00:00:00.000999' }, { tracking_started_at: '2026-01-02T00:00:00Z' },
      { tracking_started_at: '2026-02-30T00:00:00Z' }, { tracking_started_at: '2026-01-01T24:00:00Z' },
      { observed_at: new Date(Date.now() + 60000).toISOString() }, { tracking_started_at: null }, { extra: 'PRIVATE_TIMING' },
    ]) {
      api.paidTimingResult = { status: 200, body: { ...original.body, timing: { ...timing, ...change } } };
      await component.inspectPaidTiming(); expect(component.paidTiming()).toBeNull();
      await component.load();
    }
    for (const body of [{ ...original.body, organization_id: 8 }, { ...original.body, extra: 'PRIVATE_TIMING' },
      { ...original.body, timing: null }]) {
      api.paidTimingResult = { status: 200, body };
      await component.inspectPaidTiming(); expect(component.paidTiming()).toBeNull(); await component.load();
    }
    for (const state of ['unknown', 'not_observed']) {
      api.billingResult.body['first_paid_observation'] = { method: 'first-active-observation-v1', organization_id: 7, state, observation: null };
      api.paidTimingResult = { status: 200, body: { organization_id: 7, timing: { ...timing, state,
        tracking_started_at: null, observed_at: null, source_digest: null, elapsed_milliseconds: null } } };
      await component.load(); await component.inspectPaidTiming(); harness.fixture.detectChanges();
      expect(component.paidTiming()?.elapsed_milliseconds).toBeNull();
      expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Sıfır süre çıkarımı yapılmaz' : 'No zero-value timing is inferred');
      api.paidTimingResult.body['timing'] = { ...api.paidTimingResult.body['timing'] as object, elapsed_milliseconds: 0 };
      await component.inspectPaidTiming(); expect(component.paidTiming()).toBeNull();
    }
    harness.fixture.detectChanges(); expect(harness.routeNativeElement!.textContent).not.toContain('PRIVATE_TIMING');
    const element = harness.routeNativeElement!, alert = element.querySelector<HTMLParagraphElement>('[role="alert"]')!;
    const rawError = component.timingError(), reads = api.paidTimingReads.length, billingReads = api.billingReads.length;
    expect(rawError).toContain('Original paid server timing unavailable'); expect(alert.lang).toBe(language);
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(element.querySelector('[role="alert"]')).toBe(alert); expect(alert.textContent).toBe(component.t(rawError));
    expect(alert.lang).toBe(language === 'tr' ? 'en' : 'tr'); expect(component.timingError()).toBe(rawError);
    expect(component.paidTiming()).toBeNull(); expect(api.paidTimingReads).toHaveLength(reads);
    expect(api.billingReads).toHaveLength(billingReads); expect(api.billingRequests).toEqual([]); expect(api.portalRequests).toEqual([]);
  });

  it('denies paid timing when fresh owner/history is lost before or after the timing read', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const original = recordedPaidTiming(api);
    const harness = await RouterTestingHarness.create('/app/billing/7'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    api.billingResult.status = 403;
    await component.inspectPaidTiming(); expect(api.paidTimingReads).toEqual([]); expect(component.firstPaidObservation()).toBeNull();
    api.billingResult.status = 200; await component.load();
    let resolve!: (result: ApiResult) => void;
    api.paidTimingHandler = () => new Promise(done => resolve = done);
    for (const loss of ['owner', 'original', 'scope']) {
      recordedPaidTiming(api); await component.load();
      const pending = component.inspectPaidTiming(); await Promise.resolve(); await Promise.resolve();
      if (loss === 'owner') api.billingResult.status = 403;
      else if (loss === 'scope') (api.billingResult.body['first_paid_observation'] as Record<string, unknown>)['organization_id'] = 8;
      else api.billingResult.body['first_paid_observation'] = { method: 'first-active-observation-v1', organization_id: 7, state: 'unknown', observation: null };
      resolve(original); await pending;
      expect(component.paidTiming()).toBeNull(); expect(component.firstPaidObservation()).toBeNull();
      api.billingResult.status = 200;
    }
    expect(api.billingRequests).toEqual([]); expect(api.portalRequests).toEqual([]);
  });

  it('drops delayed paid timing on refresh, changed route and destruction without final reads or replay', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const original = recordedPaidTiming(api);
    const harness = await RouterTestingHarness.create('/app/billing/7'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    let resolve!: (result: ApiResult) => void;
    api.paidTimingHandler = () => new Promise(done => resolve = done);
    const refreshed = component.inspectPaidTiming(); await Promise.resolve(); await Promise.resolve();
    await component.load(); const reads = api.billingReads.length;
    resolve(original); await refreshed; expect(component.paidTiming()).toBeNull(); expect(api.billingReads).toHaveLength(reads);
    const scoped = component.inspectPaidTiming(); await Promise.resolve(); await Promise.resolve();
    delete api.billingResult.body['first_paid_observation'];
    await harness.navigateByUrl('/app/billing/8'); await harness.fixture.whenStable();
    const scopedReads = api.billingReads.length; resolve(original); await scoped;
    expect(component.paidTiming()).toBeNull(); expect(api.billingReads).toHaveLength(scopedReads);
    expect(component.firstPaidObservation()?.organization_id).toBe(8);
    api.paidTimingResult = { status: 200, body: { ...api.paidTimingResult.body, organization_id: 8 } };
    const destroyed = component.inspectPaidTiming(); await Promise.resolve(); await Promise.resolve();
    await harness.navigateByUrl('/account/login'); const destroyedReads = api.billingReads.length;
    resolve(api.paidTimingResult); await destroyed;
    expect(component.paidTiming()).toBeNull(); expect(component.firstPaidObservation()).toBeNull();
    expect(component.timingLoading()).toBe(false); expect(component.busy()).toBe(false);
    expect(api.billingReads).toHaveLength(destroyedReads); expect(api.paidTimingReads).toEqual([7, 7, 8]);
  });

  it.each(['en', 'tr'] as const)('deliberately checks frozen original trial and paid sources with exact microseconds and separate audit/provider dates (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    recordedTrialPaidTiming(api);
    const harness = await RouterTestingHarness.create('/app/billing/7'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const component = harness.routeDebugElement!.componentInstance;
    expect(api.trialActivationReads).toEqual([]); expect(api.trialPaidTimingReads).toEqual([]);
    [...harness.routeNativeElement!.querySelectorAll<HTMLButtonElement>('button')]
      .find(button => button.textContent?.includes(language === 'tr' ? 'Kaydedilen denemeden ücretli erişime sunucu zamanlamasını incele' : 'Inspect saved trial-to-paid'))!.click();
    await vi.waitFor(() => expect(component.busy()).toBe(false));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.billingReads).toEqual([7, 7, 7]); expect(api.trialActivationReads).toEqual([7, 7]); expect(api.trialPaidTimingReads).toEqual([7]);
    const section = harness.routeNativeElement!.querySelector('section[aria-labelledby="trial-paid-timing-title"]')!;
    expect(section.textContent).toContain(language === 'tr' ? '332 aşağı yuvarlanmış tam milisaniye' : '332 whole milliseconds, rounded down');
    expect([...section.querySelectorAll('time')].map(item => item.getAttribute('datetime'))).toEqual([
      '2026-01-01T00:00:00.000999+00:00', '2026-01-01T00:00:00.001002+00:00', '2026-01-01T00:00:00.333001+00:00']);
    expect(section.textContent).toContain(language === 'tr' ? 'sağlayıcı etkinleştirme zamanını, mevcut erişimi veya dönüşüm kohortunu göstermez' : 'not provider activation time, current access or a conversion cohort');
    recordedTrialPaidTiming(api, 'staff_approved'); await component.load(); await component.inspectTrialPaidTiming();
    expect(component.trialPaidTiming()?.activation_method).toBe('staff_approved');
    expect(api.billingRequests).toEqual([]); expect(api.portalRequests).toEqual([]); expect(api.paidTimingReads).toEqual([]);
    await component.load(); expect(component.trialPaidTiming()).toBeNull(); expect(component.trialActivation()).toBeNull();
    harness.fixture.detectChanges();
    expect([...section.querySelectorAll('time, code')].every(item => item.getAttribute('lang') === 'en')).toBe(true);

  });

  it('rejects malformed trial originals before timing and malformed mismatched or incorrectly rounded combined timing', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const original = recordedTrialPaidTiming(api), trial = structuredClone(api.trialActivationResult);
    const harness = await RouterTestingHarness.create('/app/billing/7'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    const activation = (trial.body['trial_activation'] as Record<string, unknown>)['activation'] as Record<string, unknown>;
    for (const change of [{ activation_method: 'other' }, { activation_method: ['automatic'] }, { activation_method: ['staff_approved'] },
      { offer_version: 'other' }, { source_digest: 'PRIVATE_TRIAL' },
      { started_at: '2026-02-30T00:00:00Z' }, { audited_at: '2025-12-31T00:00:00Z' }, { audited_at: true },
      { started_at: '2026-01-01T00:00:00' }, { audited_at: new Date(Date.now() + 60000).toISOString() }, { extra: 'PRIVATE_TRIAL' }]) {
      api.trialActivationResult = { status: 200, body: { ...trial.body, trial_activation: {
        ...trial.body['trial_activation'] as object, activation: { ...activation, ...change } } } };
      await component.inspectTrialPaidTiming(); expect(component.trialPaidTiming()).toBeNull(); expect(component.trialActivation()).toBeNull();
      await component.load();
    }
    for (const body of [{ ...trial.body, organization_id: 8 }, { ...trial.body, extra: 'PRIVATE_TRIAL' },
      { ...trial.body, trial_activation: { ...trial.body['trial_activation'] as object, state: 'unknown' } },
      ...['recorded', 'not_activated', 'unknown'].map(state => ({ ...trial.body, trial_activation: {
        ...trial.body['trial_activation'] as object, state: [state], activation: null } })),
      { ...trial.body, trial_activation: null }]) {
      api.trialActivationResult = { status: 200, body }; await component.inspectTrialPaidTiming(); await component.load();
    }
    expect(api.trialPaidTimingReads).toEqual([]);
    api.trialActivationResult = trial;
    const timing = original.body['timing'] as Record<string, unknown>;
    for (const change of [{ method: 'wrong' }, { state: 'unknown' }, { precision: 'seconds' }, { interpretation: 'conversion' },
      { activation_method: 'staff_approved' }, { trial_source_digest: 'c'.repeat(64) }, { paid_source_digest: 'c'.repeat(64) },
      { source_digest: 'c'.repeat(64) }, { elapsed_milliseconds: 333 }, { elapsed_milliseconds: -1 },
      { elapsed_milliseconds: true }, { elapsed_milliseconds: 332.5 }, { elapsed_milliseconds: Number.MAX_SAFE_INTEGER + 1 },
      { trial_started_at: '2026-01-01T00:00:00.000998+00:00' }, { observed_at: '2026-01-01T00:00:00.333002+00:00' },
      { source_digest: null }, { extra: 'PRIVATE_TRIAL' }]) {
      api.trialPaidTimingResult = { status: 200, body: { ...original.body, timing: { ...timing, ...change } } };
      await component.inspectTrialPaidTiming(); expect(component.trialPaidTiming()).toBeNull(); expect(component.trialActivation()).toBeNull(); await component.load();
    }
    for (const body of [{ ...original.body, organization_id: 8 }, { ...original.body, extra: 'PRIVATE_TRIAL' }, { ...original.body, timing: null }]) {
      api.trialPaidTimingResult = { status: 200, body }; await component.inspectTrialPaidTiming(); expect(component.trialPaidTiming()).toBeNull(); await component.load();
    }
    await component.inspectTrialPaidTiming(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement!.textContent).not.toContain('PRIVATE_TRIAL');
    const element = harness.routeNativeElement!, alert = element.querySelector<HTMLParagraphElement>('[role="alert"]')!;
    const rawError = component.trialTimingError(), reads = api.trialPaidTimingReads.length, activationReads = api.trialActivationReads.length;
    const billingReads = api.billingReads.length;
    expect(rawError).toContain('Original trial-to-paid server evidence unavailable'); expect(alert.lang).toBe('en');
    component.productLanguage.set('tr'); harness.fixture.detectChanges();
    expect(element.querySelector('[role="alert"]')).toBe(alert); expect(alert.lang).toBe('tr');
    expect(alert.textContent).toBe(component.t(rawError)); expect(component.trialTimingError()).toBe(rawError);
    expect(component.trialPaidTiming()).toBeNull(); expect(component.trialActivation()).toBeNull();
    expect(api.trialPaidTimingReads).toHaveLength(reads); expect(api.trialActivationReads).toHaveLength(activationReads);
    expect(api.billingReads).toHaveLength(billingReads); expect(api.billingRequests).toEqual([]); expect(api.portalRequests).toEqual([]);
  });

  it.each(['en', 'tr'] as const)('keeps all seven timing fields null for pending unknown or unobserved original sources rather than infer zero (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    const original = recordedTrialPaidTiming(api), trial = structuredClone(api.trialActivationResult);
    const harness = await RouterTestingHarness.create('/app/billing/7'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    const fields = ['trial_started_at', 'observed_at', 'activation_method', 'trial_source_digest', 'paid_source_digest', 'source_digest', 'elapsed_milliseconds'];
    for (const [trialState, paidState] of [['recorded', 'unknown'], ['recorded', 'not_observed'], ['unknown', 'recorded'], ['not_activated', 'recorded']]) {
      recordedTrialPaidTiming(api);
      api.trialActivationResult = { status: 200, body: { ...trial.body, trial_activation: trialState === 'recorded'
        ? trial.body['trial_activation'] : { method: 'audited-trial-activation-v1', state: trialState, activation: null } } };
      if (paidState !== 'recorded') api.billingResult.body['first_paid_observation'] = {
        method: 'first-active-observation-v1', organization_id: 7, state: paidState, observation: null };
      const timing = { ...original.body['timing'] as object, state: trialState === 'recorded' ? paidState : 'unknown',
        ...Object.fromEntries(fields.map(key => [key, null])) };
      api.trialPaidTimingResult = { status: 200, body: { organization_id: 7, timing } };
      await component.load(); await component.inspectTrialPaidTiming(); harness.fixture.detectChanges();
      expect(component.trialPaidTiming()?.elapsed_milliseconds).toBeNull();
      expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Denemeden ücretli erişime sıfır süre çıkarımı yapılmaz' : 'No zero-value trial-to-paid timing is inferred');
      for (const key of fields) {
        api.trialPaidTimingResult.body['timing'] = { ...timing, [key]: key === 'elapsed_milliseconds' ? 0 : 'a'.repeat(64) };
        await component.inspectTrialPaidTiming(); expect(component.trialPaidTiming()).toBeNull(); await component.load();
      }
    }
  });

  it('denies timing on owner preflight loss or final owner paid original or trial original displacement', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    recordedTrialPaidTiming(api);
    const harness = await RouterTestingHarness.create('/app/billing/7'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    api.billingResult.status = 403; await component.inspectTrialPaidTiming();
    expect(api.trialActivationReads).toEqual([]); expect(api.trialPaidTimingReads).toEqual([]);
    api.billingResult.status = 200;
    for (const loss of ['owner', 'paid', 'trial', 'audit', 'trial_scope']) {
      const original = recordedTrialPaidTiming(api); await component.load();
      api.trialPaidTimingHandler = async () => {
        if (loss === 'owner') api.billingResult.status = 403;
        else if (loss === 'paid') api.billingResult.body['first_paid_observation'] = {
          method: 'first-active-observation-v1', organization_id: 7, state: 'unknown', observation: null };
        else if (loss === 'trial_scope') api.trialActivationResult.body['organization_id'] = 8;
        else if (loss === 'audit') ((api.trialActivationResult.body['trial_activation'] as Record<string, unknown>)['activation'] as Record<string, unknown>)['audited_at'] = '2026-01-01T00:00:00.001003+00:00';
        else api.trialActivationResult.body['trial_activation'] = { method: 'audited-trial-activation-v1', state: 'unknown', activation: null };
        return original;
      };
      await component.inspectTrialPaidTiming(); expect(component.trialPaidTiming()).toBeNull();
      expect(component.trialActivation()).toBeNull(); expect(component.firstPaidObservation()).toBeNull();
      api.billingResult.status = 200;
    }
    expect(api.billingRequests).toEqual([]); expect(api.portalRequests).toEqual([]);
  });

  it('drops late trial source and timing reads on refresh route change or destruction without final reads or replay', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    recordedTrialPaidTiming(api);
    const harness = await RouterTestingHarness.create('/app/billing/7'); await harness.fixture.whenStable();
    for (const stage of ['trial', 'timing', 'window']) {
      for (const exit of ['refresh', 'route', 'destroy']) {
        const original = stage === 'window' ? recordedTrialPaidWindow(api) : recordedTrialPaidTiming(api); await harness.navigateByUrl('/app/billing/7');
        const component = harness.routeDebugElement!.componentInstance; await component.load();
        let resolve!: (result: ApiResult) => void, reached!: () => void;
        const ready = new Promise<void>(done => reached = done);
        const handler = () => { reached(); return new Promise<ApiResult>(done => resolve = done); };
        api.trialActivationHandler = stage === 'trial' ? handler : undefined;
        api.trialPaidTimingHandler = stage === 'timing' ? handler : undefined;
        api.trialPaidWindowHandler = stage === 'window' ? handler : undefined;
        const pending = component.inspectTrialPaidTiming(stage === 'window' ? 'window' : 'timing'); await ready;
        api.trialActivationHandler = undefined; api.trialPaidTimingHandler = undefined; api.trialPaidWindowHandler = undefined;
        if (exit === 'refresh') await component.load();
        else if (exit === 'route') { delete api.billingResult.body['first_paid_observation']; await harness.navigateByUrl('/app/billing/8'); }
        else await harness.navigateByUrl('/app');
        const reads = [api.billingReads.length, api.trialActivationReads.length, api.trialPaidTimingReads.length, api.trialPaidWindowReads.length];
        resolve(stage === 'trial' ? api.trialActivationResult : original); await pending;
        expect(component.trialPaidTiming()).toBeNull(); expect(component.trialActivation()).toBeNull();
        expect(component.trialPaidWindow()).toBeNull();
        expect(component.trialTimingLoading()).toBe(false); expect(component.busy()).toBe(false);
        expect([api.billingReads.length, api.trialActivationReads.length, api.trialPaidTimingReads.length, api.trialPaidWindowReads.length]).toEqual(reads);
      }
    }
  });

  it.each(['en', 'tr'] as const)('deliberately inspects the original fixed window with mature half-open outcomes, original SHA and frozen assessment (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    recordedTrialPaidWindow(api);
    const harness = await RouterTestingHarness.create('/app/billing/7'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const component = harness.routeDebugElement!.componentInstance;
    expect(api.trialPaidWindowReads).toEqual([]);
    [...harness.routeNativeElement!.querySelectorAll<HTMLButtonElement>('button')]
      .find(button => button.textContent?.includes(language === 'tr' ? 'Kaydedilen deneme ücretli erişim gözlem aralığını incele' : 'Inspect saved trial paid-observation window'))!.click();
    await vi.waitFor(() => expect(component.busy()).toBe(false)); harness.fixture.detectChanges();
    expect(api.billingReads).toEqual([7, 7, 7]); expect(api.trialActivationReads).toEqual([7, 7]); expect(api.trialPaidWindowReads).toEqual([7]);
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'tamamlanan bu aralığın içindeydi' : 'within this completed window');
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'deneme erişimini uzatmaz veya dönüşüm oranı bildirmez' : 'does not extend trial access or report a conversion rate');
    expect(component.trialPaidWindow()?.assessed_at).toBe('2026-02-08T00:00:00+00:00');
    for (const paidAt of ['2026-02-07T00:00:00.000998+00:00', '2026-02-07T00:00:00.000999+00:00', '2026-02-07T00:00:00.001000+00:00', null]) {
      recordedTrialPaidWindow(api, undefined, paidAt); await component.load(); await component.inspectTrialPaidTiming('window');
      expect(component.trialPaidWindow()?.outcome).toBe(paidAt?.includes('.000998') ? 'observed_within_window' : 'not_observed_within_window');
      expect(component.trialPaidWindow()?.paid_observed_at).toBe(paidAt);
      harness.fixture.detectChanges();
      if (paidAt === null) expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Ücretli erişim gözlemi yok' : 'No paid observation');
    }
    recordedTrialPaidWindow(api, '2026-02-07T00:00:00.000998+00:00'); await component.load(); await component.inspectTrialPaidTiming('window');
    expect(component.trialPaidWindow()?.state).toBe('immature'); expect(component.trialPaidWindow()?.outcome).toBeNull();
    harness.fixture.detectChanges(); expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Takip süresinin tamamı geçmedi' : 'Full follow-up has not elapsed');
    recordedTrialPaidWindow(api, '2026-02-07T00:00:00.000999+00:00'); await component.load(); await component.inspectTrialPaidTiming('window');
    expect(component.trialPaidWindow()?.state).toBe('mature');
    const clock = vi.spyOn(Date, 'now').mockReturnValue(Date.parse('2026-01-02T00:00:00Z'));
    try {
      recordedTrialPaidWindow(api, '2026-01-02T00:00:00+00:00'); await component.load(); await component.inspectTrialPaidTiming('window');
      expect(component.trialPaidWindow()?.state).toBe('immature'); // Valid end is future; observations and assessment are not.
    } finally { clock.mockRestore(); }
    expect(api.billingRequests).toEqual([]); expect(api.portalRequests).toEqual([]); expect(api.trialPaidTimingReads).toEqual([]);
    await component.load(); expect(component.trialPaidWindow()).toBeNull();
  });

  it('rejects wrong original window dates, maturity, outcome, snapshot, scope and unknown non-null fields', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const original = recordedTrialPaidWindow(api);
    const harness = await RouterTestingHarness.create('/app/billing/7'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance, window = original.body['window'] as Record<string, unknown>;
    for (const change of [{ method: 'wrong' }, { window_days: true }, { window_days: 30 }, { interpretation: 'conversion_rate' },
      { state: 'immature' }, { outcome: 'not_observed_within_window' }, { outcome: null }, { source_digest: 'c'.repeat(64) },
      { trial_source_digest: 'c'.repeat(64) }, { paid_source_digest: 'c'.repeat(64) }, { trial_started_at: '2026-01-01T00:00:00.000998+00:00' },
      { paid_observed_at: '2026-01-01T00:00:00.333002+00:00' }, { window_ends_at: '2026-02-07T00:00:00.000998+00:00' },
      { window_ends_at: '2026-02-30T00:00:00Z' }, { window_ends_at: '2026-02-07T24:00:00Z' },
      { assessed_at: '2026-02-08T00:00:00' }, { assessed_at: new Date(Date.now() + 60000).toISOString() }, { extra: 'PRIVATE_WINDOW' }]) {
      api.trialPaidWindowResult = { status: 200, body: { ...original.body, window: { ...window, ...change } } };
      await component.inspectTrialPaidTiming('window'); expect(component.trialPaidWindow()).toBeNull(); expect(component.trialActivation()).toBeNull(); await component.load();
    }
    for (const body of [{ ...original.body, organization_id: 8 }, { ...original.body, extra: 'PRIVATE_WINDOW' }, { ...original.body, window: null }]) {
      api.trialPaidWindowResult = { status: 200, body }; await component.inspectTrialPaidTiming('window'); expect(component.trialPaidWindow()).toBeNull(); await component.load();
    }
    const fields = ['trial_started_at', 'window_ends_at', 'paid_observed_at', 'trial_source_digest', 'paid_source_digest', 'source_digest', 'outcome'];
    api.billingResult.body['first_paid_observation'] = { method: 'first-active-observation-v1', organization_id: 7, state: 'unknown', observation: null };
    const unknown = { ...window, state: 'unknown', ...Object.fromEntries(fields.map(key => [key, null])) };
    api.trialPaidWindowResult = { status: 200, body: { organization_id: 7, window: unknown } };
    await component.load(); await component.inspectTrialPaidTiming('window'); expect(component.trialPaidWindow()?.state).toBe('unknown');
    for (const key of fields) {
      api.trialPaidWindowResult.body['window'] = { ...unknown, [key]: 'PRIVATE_WINDOW' };
      await component.inspectTrialPaidTiming('window'); expect(component.trialPaidWindow()).toBeNull(); await component.load();
    }
    harness.fixture.detectChanges(); expect(harness.routeNativeElement!.textContent).not.toContain('PRIVATE_WINDOW');
  });

  it('clears window evidence when the final original trial or owner-paid history is displaced', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    recordedTrialPaidWindow(api);
    const harness = await RouterTestingHarness.create('/app/billing/7'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    for (const loss of ['trial', 'owner', 'paid']) {
      const original = recordedTrialPaidWindow(api); await component.load();
      api.trialPaidWindowHandler = async () => {
        if (loss === 'trial') api.trialActivationResult.body['trial_activation'] = { method: 'audited-trial-activation-v1', state: 'unknown', activation: null };
        else if (loss === 'owner') api.billingResult.status = 403;
        else api.billingResult.body['first_paid_observation'] = { method: 'first-active-observation-v1', organization_id: 7, state: 'unknown', observation: null };
        return original;
      };
      await component.inspectTrialPaidTiming('window'); expect(component.trialPaidWindow()).toBeNull();
      expect(component.trialActivation()).toBeNull(); expect(component.firstPaidObservation()).toBeNull(); api.billingResult.status = 200;
    }
  });

  it('keeps checkout review English for denied malformed unavailable and fresh production preferences', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const preference = vi.spyOn(api, 'productLanguage'), buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    const harness = await RouterTestingHarness.create('/');
    try {
      for (const mode of ['denied', 'invalid', 'unavailable', 'production'] as const) {
        await harness.navigateByUrl('/'); buildEnvironment.production = mode === 'production';
        if (mode === 'unavailable') preference.mockRejectedValue(new Error('PRIVATE preference detail'));
        else preference.mockResolvedValue({ status: mode === 'denied' ? 403 : 200, body: {
          language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: 'en', current_email_language: 'en' } });
        await harness.navigateByUrl('/account/billing/checkout?_ptxn=txn_' + 'a'.repeat(26)); await harness.fixture.whenStable(); harness.fixture.detectChanges();
        expect(TestBed.inject(Title).getTitle()).toBe('Hosted checkout — OrganicSEOOps');
        expect(harness.routeNativeElement!.querySelector('.account-card')?.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement!.querySelector('h1')?.textContent).toBe('Review Paddle checkout');
        expect(harness.routeNativeElement!.textContent).not.toContain('incelenmemiş Türkçe');
        expect(harness.routeNativeElement!.textContent).not.toContain('PRIVATE preference detail');
        expect(document.querySelector('script[src*="paddle.com"]')).toBeNull(); expect(api.billingRequests).toEqual([]);
      }
    } finally { buildEnvironment.production = production; preference.mockRestore(); }
  });

  it.each(['en', 'tr'] as const)('only offers manual Paddle activation after the server resolves an owner transaction (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    const txn = 'txn_' + 'a'.repeat(26);
    api.checkoutResolution = { status: 200, body: { organization_id: 7, attempt_id: 91,
      transaction_id: txn, environment: 'sandbox', client_token: 'test_' + 'a'.repeat(27),
      payment_confirmed: false, checkout_url: `${window.location.origin}/account/billing/checkout?_ptxn=${txn}` } };
    const harness = await RouterTestingHarness.create(`/account/billing/checkout?_ptxn=${txn}`);
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Barındırılan ödeme işlemi — OrganicSEOOps' : 'Hosted checkout — OrganicSEOOps');
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'Paddle ödeme incelemesini aç' : 'Open Paddle payment review');
    expect(document.querySelector('script[src*="paddle.com"]')).toBeNull();
    const root = harness.routeNativeElement!;
    expect(root.querySelector('.account-card')?.getAttribute('lang')).toBe(language);
    expect(root.querySelector('h1')?.textContent).toBe(language === 'tr' ? 'Paddle ödeme işlemini incele' : 'Review Paddle checkout');
    const component = harness.routeDebugElement!.componentInstance;
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Hosted checkout — OrganicSEOOps' : 'Barındırılan ödeme işlemi — OrganicSEOOps');
    expect(document.querySelector('script[src*="paddle.com"]')).toBeNull();
    expect(api.billingRequests).toEqual([]); expect(api.portalRequests).toEqual([]);
    component.productLanguage.set(language); harness.fixture.detectChanges();
    for (const phrase of language === 'tr'
      ? ['ayda 149 USD', 'vergiyi, toplamı ve aylık yenilemeyi', 'denemeyi hemen sona erdirir', 'birimler devredilmez', 'İptal dönem sonunda', 'burada hizmeti etkinleştirmez', 'mutabakatla doğruladıktan', 'Hiçbir ödeme doğrulanmadı', 'incelenmemiş Türkçe']
      : ['USD 149 per month', 'tax, total and monthly renewal', 'trial immediately', 'units do not carry over', 'Cancellation takes effect at period end', 'never activates service here', 'server reconciles provider billing events', 'No payment has been confirmed']) expect(root.textContent).toContain(phrase);
    expect(root.querySelector('app-checkout-link-receipt section')?.getAttribute('lang')).toBe(language);
    expect([...root.querySelectorAll('[lang="en"]')].some(item => item.textContent === 'sandbox')).toBe(true);
    expect(root.textContent).not.toContain('test_' + 'a'.repeat(27));
    expect(api.billingRequests).toEqual([]); expect(api.portalRequests).toEqual([]);
    await harness.navigateByUrl('/account/billing/checkout?_ptxn=invalid'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement!.querySelector('[role="alert"]')?.textContent).toContain(language === 'tr' ? 'ödeme bağlantısı geçersiz' : 'payment link is invalid');
    expect(document.querySelector('script[src*="paddle.com"]')).toBeNull();
  });

  it.each(['en', 'tr'] as const)('shows only a validated fresh owner portal link without treating it as paid status (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    api.billingResult = { status: 200, body: { seller_configured: false, offer_version: 'agency-launch-v1',
      can_start_new_checkout: false,
      subscription_linked: true, portal_available: true, billing_access_state: 'unverified', attempts: [] } };
    api.portalResult = { status: 200, body: { portal_url:
      `https://sandbox-customer-portal.paddle.com/cpl_${'a'.repeat(26)}?action=overview&token=pga_test.token` } };
    const harness = await RouterTestingHarness.create('/app/billing/7');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'aboneliğin durumunu ve ücretli erişimi doğrulamaz' : 'status and paid access are not verified');
    expect(api.portalRequests).toEqual([]);
    const button = [...harness.routeNativeElement!.querySelectorAll('button')]
      .find((item) => item.textContent?.includes(language === 'tr' ? 'Yeni bir Paddle faturalandırma portalı bağlantısı al' : 'fresh Paddle billing portal'))!;
    button.click(); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.portalRequests).toEqual([7]);
    const link = harness.routeNativeElement?.querySelector<HTMLAnchorElement>('a[href*="customer-portal.paddle.com"]')!;
    expect(link.rel).toContain('noreferrer');
    expect(link.textContent).toContain(language === 'tr' ? 'Geçici Paddle portalını aç' : 'temporary Paddle portal');
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'yalnızca bu oturum' : 'this session only');
    const component = harness.routeDebugElement!.componentInstance, element = harness.routeNativeElement!;
    const acknowledgment = element.querySelector<HTMLParagraphElement>('p[role="status"][lang]')!;
    const message = component.message(), portal = component.portalUrl(), reads = api.billingReads.length;
    expect(message).toBe('This temporary Paddle portal link is available for this session only.'); expect(acknowledgment.lang).toBe(language);
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(element.querySelector('p[role="status"][lang]')).toBe(acknowledgment);
    expect(acknowledgment.textContent).toBe(component.t(message)); expect(acknowledgment.lang).toBe(language === 'tr' ? 'en' : 'tr');
    expect(component.message()).toBe(message); expect(component.portalUrl()).toBe(portal);
    expect(element.querySelector('a[href*="customer-portal.paddle.com"]')).toBe(link);
    expect(api.portalRequests).toEqual([7]); expect(api.billingReads).toHaveLength(reads);
    component.productLanguage.set(language); harness.fixture.detectChanges();
    api.portalResult.body['portal_url'] = 'https://foreign.invalid/cpl_' + 'a'.repeat(26) + '?action=overview&token=test';
    await harness.routeDebugElement!.componentInstance.requestPortal(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement!.querySelector('a[href*="customer-portal.paddle.com"]')).toBeNull();
    expect(harness.routeNativeElement!.querySelector('[role="alert"]')?.textContent).toContain(language === 'tr' ? 'portalı kullanılamıyor' : 'portal is unavailable');
    const alert = element.querySelector<HTMLParagraphElement>('[role="alert"]')!, rawError = component.error();
    expect(rawError).toBe('The billing portal is unavailable. Refresh and try again later.'); expect(alert.lang).toBe(language);
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(element.querySelector('[role="alert"]')).toBe(alert); expect(alert.textContent).toBe(component.t(rawError));
    expect(alert.lang).toBe(language === 'tr' ? 'en' : 'tr'); expect(component.error()).toBe(rawError);
    expect(component.portalUrl()).toBeNull(); expect(api.portalRequests).toEqual([7, 7]); expect(api.billingRequests).toEqual([]);

  });

  it.each(['en', 'tr'] as const)('does not render saved performance keys or retain submitted key input in %s', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    api.performanceKeyResult = { status: 200, body: { state: 'unconfigured' } };
    const harness = await RouterTestingHarness.create('/account/provider-settings');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe(language);
    expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe(language === 'tr' ? 'Yapay zekâ sağlayıcı kimlik bilgileri' : 'AI provider credentials');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const input = harness.routeNativeElement?.querySelector<HTMLInputElement>('#performance-api-key')!;
    input.value = 'fixture_key_with_32_placeholder_chars';
    expect(harness.routeNativeElement!.querySelector('label[for="performance-api-key"]')!.textContent).toContain(language === 'tr' ? 'Yeni API anahtarı' : 'Replacement API key');
    input.closest('form')!.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.savedPerformanceKeys).toEqual(['fixture_key_with_32_placeholder_chars']);
    expect(input.value).toBe('');
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Performans anahtarı kaydedildi.' : 'Performance key saved.');
    expect(harness.routeNativeElement?.textContent).not.toContain('fixture_key_with_32_placeholder_chars');
  });

  it.each(['en', 'tr'] as const)('hides organization key forms on denial and clears submitted key values (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    const harness = await RouterTestingHarness.create('/app/provider-accounts/7');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Kuruluş AI kimlik bilgileri — OrganicSEOOps' : 'Organization AI credentials — OrganicSEOOps');
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'kuruluş veya rol için sağlayıcı kimlik bilgileri kullanılamıyor' : 'unavailable for this organization');
    expect(harness.routeNativeElement?.querySelector('input[name="secret"]')).toBeNull();

    api.organizationProviderResult = { status: 200, body: {
      providers: [{ id: 9, name: 'OpenAI', kind: 'openai' }], accounts: [], has_more: false,
    } };
    await harness.routeDebugElement?.componentInstance.load();
    harness.fixture.detectChanges();
    const form = harness.routeNativeElement?.querySelector('form') as HTMLFormElement;
    form.querySelector<HTMLInputElement>('input[name="label"]')!.value = 'Own account';
    const secret = form.querySelector<HTMLInputElement>('input[name="secret"]')!;
    secret.value = 'dummy-private-key';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.savedOrganizationSecrets).toEqual(['dummy-private-key']);
    expect(secret.value).toBe('');
    expect(harness.routeNativeElement?.textContent).not.toContain('dummy-private-key');
    const element = harness.routeNativeElement!, component = harness.routeDebugElement!.componentInstance;
    expect(element.querySelector('.workspace-panel')?.getAttribute('lang')).toBe(language);
    expect(element.textContent).toContain(language === 'tr' ? 'Kaydedilen anahtarınız bir daha gösterilmez' : 'Your saved key will never be shown again');
    expect(element.textContent).toContain(language === 'tr' ? 'Model seçimi ve desteklenen yetenekler ayrı' : 'Model selection and supported capabilities are configured separately');
    expect(element.textContent).toContain(language === 'tr' ? 'Kimlik bilgisi kaydedildi' : 'Credential saved');
    {
      const acknowledgment = element.querySelector<HTMLParagraphElement>('p[role="status"][lang]')!;
      const sourceAccounts = component.accounts(), requests = api.savedOrganizationSecrets.length;
      expect(component.message()).toBe('Credential saved.'); expect(acknowledgment.lang).toBe(language);
      component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
      expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Organization AI credentials — OrganicSEOOps' : 'Kuruluş AI kimlik bilgileri — OrganicSEOOps');
      expect(element.querySelector('p[role="status"][lang]')).toBe(acknowledgment);
      expect(acknowledgment.lang).toBe(language === 'tr' ? 'en' : 'tr');
      expect(acknowledgment.textContent).toBe(component.t('Credential saved.')); expect(component.message()).toBe('Credential saved.');
      expect(component.accounts()).toBe(sourceAccounts); expect(api.savedOrganizationSecrets.length).toBe(requests);
      expect(element.textContent).not.toContain('dummy-private-key'); expect(element.textContent).not.toContain('synthetic-replacement');
      expect(element.textContent).not.toContain('fixture_org_key_with_32_characters');
      component.productLanguage.set(language); harness.fixture.detectChanges();
    }
    expect(form.querySelector('label[for="org-provider-key"]')?.textContent).toBe(language === 'tr' ? 'Sağlayıcı API anahtarı' : 'Provider API key');
    const rawLabel = '<script>Customer account</script>';
    api.organizationProviderResult.body['accounts'] = [{ id: 8, provider_id: 9, label: rawLabel, state: 'active', stored: true }];
    await component.load(); harness.fixture.detectChanges();
    const rotate = element.querySelector('#org-replacement-key')!.closest('form')!, replacement = rotate.querySelector<HTMLInputElement>('[name="secret"]')!;
    replacement.value = 'synthetic-replacement';
    const choice = rotate.querySelector<HTMLSelectElement>('[name="account_id"]')!;
    const save = vi.spyOn(api, 'setOrganizationProviderCredential');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(choice.value).toBe('8'); expect(replacement.value).toBe('synthetic-replacement');
    expect(choice.getAttribute('lang')).toBe(''); expect(replacement.getAttribute('lang')).toBe('');
    expect(save).not.toHaveBeenCalled(); component.productLanguage.set(language); harness.fixture.detectChanges();
    rotate.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true })); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(save).toHaveBeenLastCalledWith(7, 8, 'synthetic-replacement'); expect(replacement.value).toBe('');
    expect(element.textContent).not.toContain('synthetic-replacement'); expect(element.textContent).toContain(language === 'tr' ? 'Kimlik bilgisi değiştirildi' : 'Credential replaced');
    expect(element.querySelector('script')).toBeNull(); expect(element.textContent).toContain(rawLabel);
    {
      const acknowledgment = element.querySelector<HTMLParagraphElement>('p[role="status"][lang]')!;
      const sourceAccounts = component.accounts(), requests = api.savedOrganizationSecrets.length;
      expect(component.message()).toBe('Credential replaced.'); expect(acknowledgment.lang).toBe(language);
      component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
      expect(element.querySelector('p[role="status"][lang]')).toBe(acknowledgment);
      expect(acknowledgment.lang).toBe(language === 'tr' ? 'en' : 'tr');
      expect(acknowledgment.textContent).toBe(component.t('Credential replaced.')); expect(component.message()).toBe('Credential replaced.');
      expect(component.accounts()).toBe(sourceAccounts); expect(api.savedOrganizationSecrets.length).toBe(requests);
      expect(element.textContent).not.toContain('dummy-private-key'); expect(element.textContent).not.toContain('synthetic-replacement');
      expect(element.textContent).not.toContain('fixture_org_key_with_32_characters');
      component.productLanguage.set(language); harness.fixture.detectChanges();
    }
    const button = (text: string) => Array.from(element.querySelectorAll<HTMLButtonElement>('button')).find(item => item.textContent?.trim() === text)!;
    const revoke = vi.spyOn(api, 'revokeOrganizationProviderCredential');
    button((language === 'tr' ? 'Bağlantıyı kes ' : 'Disconnect ') + rawLabel).click(); harness.fixture.detectChanges();
    expect(revoke).not.toHaveBeenCalled(); expect(element.textContent).toContain(language === 'tr' ? 'gelecekteki kullanımını durdurmak' : 'Stop future use');
    button(language === 'tr' ? 'Vazgeç' : 'Cancel').click(); harness.fixture.detectChanges(); expect(revoke).not.toHaveBeenCalled();
    button((language === 'tr' ? 'Bağlantıyı kes ' : 'Disconnect ') + rawLabel).click(); harness.fixture.detectChanges();
    button(language === 'tr' ? 'Bağlantıyı kesmeyi onayla' : 'Confirm disconnect').click(); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(revoke).toHaveBeenLastCalledWith(7, 8); expect(element.querySelector('#org-replacement-key')).toBeNull();
    expect(element.textContent).toContain(language === 'tr' ? 'Gelecekteki sağlayıcı işleri bunu kullanamaz' : 'Future provider jobs cannot use it');
    {
      const acknowledgment = element.querySelector<HTMLParagraphElement>('p[role="status"][lang]')!;
      const sourceAccounts = component.accounts(), requests = revoke.mock.calls.length;
      expect(component.message()).toBe('Key disconnected. Future provider jobs cannot use it.'); expect(acknowledgment.lang).toBe(language);
      component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
      expect(element.querySelector('p[role="status"][lang]')).toBe(acknowledgment);
      expect(acknowledgment.lang).toBe(language === 'tr' ? 'en' : 'tr');
      expect(acknowledgment.textContent).toBe(component.t('Key disconnected. Future provider jobs cannot use it.')); expect(component.message()).toBe('Key disconnected. Future provider jobs cannot use it.');
      expect(component.accounts()).toBe(sourceAccounts); expect(revoke.mock.calls.length).toBe(requests);
      expect(element.textContent).not.toContain('dummy-private-key'); expect(element.textContent).not.toContain('synthetic-replacement');
      expect(element.textContent).not.toContain('fixture_org_key_with_32_characters');
      component.productLanguage.set(language); harness.fixture.detectChanges();
    }
    vi.spyOn(api, 'organizationProviderAccounts').mockResolvedValue({ status: 403, body: {} });
    await harness.navigateByUrl('/app/provider-accounts/8'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(element.querySelector('input[name="secret"]')).toBeNull(); expect(element.textContent).not.toContain(rawLabel);
    if (language === 'tr') {
      const preference = vi.spyOn(api, 'productLanguage'), buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
      try {
        for (const mode of ['denied', 'invalid', 'unavailable', 'production'] as const) {
          await harness.navigateByUrl('/'); buildEnvironment.production = mode === 'production';
          if (mode === 'unavailable') preference.mockRejectedValue(new Error('PRIVATE preference detail'));
          else preference.mockResolvedValue({ status: mode === 'denied' ? 403 : 200, body: {
            language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: 'en', current_email_language: 'en' } });
          await harness.navigateByUrl('/app/provider-accounts/7'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
          expect(harness.routeNativeElement?.querySelector('.workspace-panel')?.getAttribute('lang')).toBe('en');
          expect(TestBed.inject(Title).getTitle()).toBe('Organization AI credentials — OrganicSEOOps');
          expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Organization AI provider credentials');
          expect(harness.routeNativeElement?.textContent).not.toContain('incelenmemiş Türkçe');
          expect(harness.routeNativeElement?.textContent).not.toContain('PRIVATE preference detail');
        }
      } finally { buildEnvironment.production = production; preference.mockRestore(); }
    }
    await harness.navigateByUrl('/account/login'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const nextTitle = TestBed.inject(Title).getTitle();
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(nextTitle);
    expect(nextTitle).toMatch(/^(Sign in|Oturum aç) — OrganicSEOOps$/);

  });

  it.each(['en', 'tr'] as const)('clears a submitted organization performance key and never renders it in the page (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    api.organizationProviderResult = { status: 200, body: { providers: [], accounts: [], has_more: false } };
    api.organizationPerformanceResult = { status: 200, body: { state: 'unconfigured' } };
    const harness = await RouterTestingHarness.create('/app/provider-accounts/7');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const input = harness.routeNativeElement?.querySelector<HTMLInputElement>('#organization-performance-key')!;
    input.value = 'fixture_org_key_with_32_characters';
    input.closest('form')!.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.savedOrganizationPerformanceKeys).toEqual(['fixture_org_key_with_32_characters']);
    expect(input.value).toBe('');
    expect(harness.routeNativeElement?.textContent).not.toContain('fixture_org_key_with_32_characters');
    const element = harness.routeNativeElement!, component = harness.routeDebugElement!.componentInstance;
    expect(element.textContent).toContain(language === 'tr' ? 'Anahtar yoksa mevcut platform finansmanı kullanılabilir' : 'A missing key may use available platform funding');
    expect(element.textContent).toContain(language === 'tr' ? 'değiştirene kadar alternatif platform kullanımını durdurur' : 'stops fallback until you replace it');
    expect(element.textContent).toContain(language === 'tr' ? 'Kuruluş performans anahtarı kaydedildi' : 'Organization performance key saved');
    {
      const acknowledgment = element.querySelector<HTMLParagraphElement>('p[role="status"][lang]')!;
      const sourceAccounts = component.accounts(), requests = api.savedOrganizationPerformanceKeys.length;
      expect(component.message()).toBe('Organization performance key saved.'); expect(acknowledgment.lang).toBe(language);
      component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
      expect(element.querySelector('p[role="status"][lang]')).toBe(acknowledgment);
      expect(acknowledgment.lang).toBe(language === 'tr' ? 'en' : 'tr');
      expect(acknowledgment.textContent).toBe(component.t('Organization performance key saved.')); expect(component.message()).toBe('Organization performance key saved.');
      expect(component.accounts()).toBe(sourceAccounts); expect(api.savedOrganizationPerformanceKeys.length).toBe(requests);
      expect(element.textContent).not.toContain('dummy-private-key'); expect(element.textContent).not.toContain('synthetic-replacement');
      expect(element.textContent).not.toContain('fixture_org_key_with_32_characters');
      component.productLanguage.set(language); harness.fixture.detectChanges();
    }
    expect(input.getAttribute('lang')).toBe('');
    api.organizationPerformanceResult = { status: 200, body: { state: 'active' } }; await component.loadPerformance(); harness.fixture.detectChanges();
    expect(element.querySelector('#org-performance-title')?.textContent).toBe(language === 'tr' ? 'Kuruluş performans API anahtarı' : 'Organization performance API key');
    expect(Array.from(element.querySelectorAll('[lang="en"]')).some(node => node.textContent === 'active')).toBe(true);
    const revoke = vi.spyOn(api, 'revokeOrganizationPerformanceKey');
    const button = (text: string) => Array.from(element.querySelectorAll<HTMLButtonElement>('button')).find(item => item.textContent === text)!;
    button(language === 'tr' ? 'Kuruluş anahtarını kaldır' : 'Revoke organization key').click(); harness.fixture.detectChanges();
    expect(revoke).not.toHaveBeenCalled(); expect(element.textContent).toContain(language === 'tr' ? 'kuyruktaki ve gelecekteki performans isteklerini' : 'queued and future performance requests');
    button(language === 'tr' ? 'Kaldırmayı onayla' : 'Confirm revoke').click(); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(revoke).toHaveBeenLastCalledWith(7); expect(component.performanceState()).toBe('revoked');
    expect(element.textContent).toContain(language === 'tr' ? 'Başka bir denetim çalıştırmadan önce değiştirin' : 'Replace it before running another audit');
    {
      const acknowledgment = element.querySelector<HTMLParagraphElement>('p[role="status"][lang]')!;
      const sourceAccounts = component.accounts(), requests = revoke.mock.calls.length;
      expect(component.message()).toBe('Organization key revoked. Replace it before running another audit.'); expect(acknowledgment.lang).toBe(language);
      component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
      expect(element.querySelector('p[role="status"][lang]')).toBe(acknowledgment);
      expect(acknowledgment.lang).toBe(language === 'tr' ? 'en' : 'tr');
      expect(acknowledgment.textContent).toBe(component.t('Organization key revoked. Replace it before running another audit.')); expect(component.message()).toBe('Organization key revoked. Replace it before running another audit.');
      expect(component.accounts()).toBe(sourceAccounts); expect(revoke.mock.calls.length).toBe(requests);
      expect(element.textContent).not.toContain('dummy-private-key'); expect(element.textContent).not.toContain('synthetic-replacement');
      expect(element.textContent).not.toContain('fixture_org_key_with_32_characters');
      component.productLanguage.set(language); harness.fixture.detectChanges();
    }
    expect(element.querySelector('button')?.textContent).toBe(language === 'tr' ? 'Hesapları yenile' : 'Refresh accounts');

  });

  it('shows locale-controlled 404 previews and English unknown public/private paths instead of the workspace', async () => {
    const harness = await RouterTestingHarness.create('/preview/tr/404');
    expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Sayfa bulunamadı');
    expect(harness.routeNativeElement?.querySelector('section')?.lang).toBe('tr');
    expect(document.documentElement.lang).toBe('tr');
    expect(document.title).toContain('Türkçe taslak');
    expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).toContain('incelenmemiş Türkçe taslak');
    expect(harness.routeNativeElement?.querySelector('[role="status"]')?.textContent).toContain('İki dilli insan onayı');
    expect(harness.routeNativeElement?.querySelector('a[href="/preview/tr/home"]')).toBeTruthy();
    expect(harness.routeNativeElement?.querySelector('a[href="/preview/tr/404"]')?.getAttribute('aria-current')).toBe('page');
    harness.routeNativeElement?.querySelector<HTMLAnchorElement>('nav a[lang="en"]')!.click();
    await harness.fixture.whenStable(); harness.detectChanges();
    for (const path of ['/404', '/missing', '/preview/missing', '/preview/tr/missing', '/application', '/account/missing', '/app/missing']) {
      await harness.navigateByUrl(path);
      expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Page not found');
      expect(harness.routeNativeElement?.querySelector('section')?.lang).toBe('en');
      expect(document.documentElement.lang).toBe('en');
      expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).not.toContain('Türkçe');
      expect(harness.routeNativeElement?.textContent).not.toContain('Organization:');
    }
    expect(document.querySelector('link[rel="canonical"], link[hreflang]')).toBeNull();
    await harness.navigateByUrl('/preview/tr/404'); await harness.navigateByUrl('/');
    expect(document.documentElement.lang).toBe('en');
    expect(document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).toContain('agency teams');
  });

  it.each(['en', 'tr'] as const)('associates password confirmation errors and links development notices in %s', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    const signup = vi.spyOn(api, 'signup');
    const harness = await RouterTestingHarness.create('/account/register');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Hesap oluştur — OrganicSEOOps' : 'Create account — OrganicSEOOps');
    const root = harness.routeNativeElement!, component = harness.routeDebugElement!.componentInstance as Register;
    const form = root.querySelector('form')!;
    const email = root.querySelector<HTMLInputElement>('#email')!;
    const password = root.querySelector<HTMLInputElement>('#password')!;
    const confirmation = root.querySelector<HTMLInputElement>('#password-confirm')!;
    const terms = root.querySelector<HTMLInputElement>('#development-terms')!;
    expect(root.querySelector('section')?.getAttribute('lang')).toBe(language);
    expect(root.querySelector('label[for="password-confirm"]')?.textContent).toBe(language === 'tr' ? 'Parolayı doğrulayın' : 'Confirm password');
    expect(root.querySelector('#password-help')?.textContent).toContain(language === 'tr' ? 'En az 12 karakter' : 'at least 12 characters');
    expect(root.querySelector('button')?.textContent).toBe(language === 'tr' ? 'Hesap oluştur' : 'Create account');
    if (language === 'tr') expect(root.textContent).toContain('Bağlantılı yerel koşullar ve gizlilik taslakları da incelenmemiştir');
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    expect(signup).not.toHaveBeenCalled();
    email.value = 'person@example.com';
    password.value = 'A-long-enough-password';
    confirmation.value = 'A-different-password';
    terms.checked = true;
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    harness.fixture.detectChanges();
    await new Promise((resolve) => setTimeout(resolve));
    expect(confirmation.getAttribute('aria-invalid')).toBe('true');
    expect(confirmation.getAttribute('aria-describedby')).toBe('password-confirm-error');
    expect(confirmation.validationMessage).toBe(language === 'tr' ? 'Parola doğrulaması eşleşmiyor.' : 'The password confirmation does not match.');
    expect(root.querySelector('#password-confirm-error')?.textContent).toBe(confirmation.validationMessage);
    for (const [path, label] of language === 'tr'
      ? [['/preview/tr/terms', 'yerel koşullar taslağı'], ['/preview/tr/privacy', 'yerel gizlilik taslağı']]
      : [['/preview/terms', 'local terms draft'], ['/preview/privacy', 'local privacy draft']]) expect(root.querySelector(`a[href="${path}"]`)?.textContent).toBe(label);
    expect(terms.required).toBe(true); expect(terms.getAttribute('aria-describedby')).toBe('development-policy-help');
    expect(root.querySelector('#development-policy-help')?.textContent).toContain(language === 'tr' ? 'onaylı sözleşme veya gizlilik bildirimi değildir' : 'not an approved contract or privacy notice');
    expect(document.activeElement?.getAttribute('role')).toBe('alert');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Create account — OrganicSEOOps' : 'Hesap oluştur — OrganicSEOOps');
    expect(confirmation.validationMessage).toBe(language === 'tr' ? 'The password confirmation does not match.' : 'Parola doğrulaması eşleşmiyor.');
    expect(root.querySelector('#password-confirm-error')?.textContent).toBe(confirmation.validationMessage);
    expect(root.querySelector('[role="alert"]')?.textContent).toBe(confirmation.validationMessage);
    expect(root.querySelector(`a[href="${language === 'tr' ? '/preview/terms' : '/preview/tr/terms'}"]`)).toBeTruthy();
    expect(root.querySelector(`a[href="${language === 'tr' ? '/preview/privacy' : '/preview/tr/privacy'}"]`)).toBeTruthy();
    expect(email.value).toBe('person@example.com'); expect(password.value).toBe('A-long-enough-password');
    expect(confirmation.value).toBe('A-different-password'); expect(terms.checked).toBe(true);
    expect(signup).not.toHaveBeenCalled();
    confirmation.value = password.value; confirmation.dispatchEvent(new Event('input', { bubbles: true })); harness.fixture.detectChanges();
    expect(confirmation.validity.customError).toBe(false); expect(form.checkValidity()).toBe(true);
    expect(confirmation.hasAttribute('aria-invalid')).toBe(false); expect(root.querySelector('#password-confirm-error')).toBeNull();
  });

  it.each(['en', 'tr'] as const)('keeps registration deliberate with generic failures and a masked verification redirect in %s', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    const signup = vi.spyOn(api, 'signup'), pending = vi.spyOn(api, 'hasPendingVerification').mockImplementation(AccountApi.prototype.hasPendingVerification);
    const harness = await RouterTestingHarness.create('/account/register'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const root = harness.routeNativeElement!, component = harness.routeDebugElement!.componentInstance as Register;
    const form = root.querySelector('form')!;
    const fill = () => {
      root.querySelector<HTMLInputElement>('#email')!.value = 'person@example.com';
      root.querySelector<HTMLInputElement>('#password')!.value = 'A-long-enough-password';
      root.querySelector<HTMLInputElement>('#password-confirm')!.value = 'A-long-enough-password';
      root.querySelector<HTMLInputElement>('#development-terms')!.checked = true;
    };
    fill(); let resolve!: (result: ApiResult) => void;
    signup.mockImplementationOnce(() => new Promise(done => resolve = done));
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true })); harness.fixture.detectChanges();
    expect(root.querySelector<HTMLButtonElement>('button')!.disabled).toBe(true);
    expect(root.querySelector('button')?.textContent).toBe(language === 'tr' ? 'Hesap oluşturuluyor…' : 'Creating account…');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true })); expect(signup).toHaveBeenCalledTimes(1);
    component.productLanguage.set(language); resolve({ status: 400, body: { detail: 'private signup detail' } });
    await harness.fixture.whenStable(); harness.fixture.detectChanges(); await new Promise(done => setTimeout(done));
    expect(root.textContent).toContain(language === 'tr' ? 'Hesap oluşturulamadı.' : 'Account creation failed.');
    expect(root.textContent).not.toContain('private signup detail'); expect(document.activeElement?.getAttribute('role')).toBe('alert');
    signup.mockRejectedValueOnce(new Error('private transport detail'));
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true })); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(root.textContent).toContain(language === 'tr' ? 'Hesap oluşturma geçici olarak kullanılamıyor.' : 'Account creation is temporarily unavailable.');
    expect(root.textContent).not.toContain('private transport detail');
    for (const result of [{ status: 200, body: {} }, { status: 401, body: { data: { flows: [{ id: 'verify_email', is_pending: true }] } } }]) {
      await harness.navigateByUrl('/account/register'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
      const element = harness.routeNativeElement!;
      element.querySelector<HTMLInputElement>('#email')!.value = 'person@example.com';
      element.querySelector<HTMLInputElement>('#password')!.value = 'A-long-enough-password';
      element.querySelector<HTMLInputElement>('#password-confirm')!.value = 'A-long-enough-password';
      element.querySelector<HTMLInputElement>('#development-terms')!.checked = true;
      signup.mockResolvedValueOnce(result);
      element.querySelector('form')!.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
      await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(TestBed.inject(Router).url).toBe('/account/verify?to=p*****@example.com');
      expect(harness.routeNativeElement?.textContent).toContain('p*****@example.com');
      expect(harness.routeNativeElement?.textContent).not.toContain('person@example.com');
      expect(signup).toHaveBeenLastCalledWith('person@example.com', 'A-long-enough-password');
    }
    pending.mockRestore();
  });

  it('keeps invalid unavailable or signed-out registration preference and fresh production English', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const preference = vi.spyOn(api, 'productLanguage'), signup = vi.spyOn(api, 'signup');
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    try {
      const harness = await RouterTestingHarness.create();
      for (const result of [
        { status: 200, body: { language: ['tr'], current_ui_language: 'en', current_email_language: 'en' } },
        { status: 200, body: { language: 'tr', current_ui_language: 'tr', current_email_language: 'tr' } },
        { status: 401, body: { detail: 'private preference error' } },
      ]) {
        preference.mockResolvedValue(result); await harness.navigateByUrl('/account/register');
        await harness.fixture.whenStable(); harness.fixture.detectChanges();
        expect(TestBed.inject(Title).getTitle()).toBe('Create account — OrganicSEOOps');
        expect(harness.routeNativeElement?.querySelector('section')?.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Create your account');
        expect(harness.routeNativeElement?.textContent).not.toContain('private preference error'); await harness.navigateByUrl('/');
      }
      preference.mockRejectedValue(new Error('private transport error')); await harness.navigateByUrl('/account/register');
      await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(TestBed.inject(Title).getTitle()).toBe('Create account — OrganicSEOOps');
      expect(harness.routeNativeElement?.querySelector('section')?.getAttribute('lang')).toBe('en');
      expect(harness.routeNativeElement?.textContent).not.toContain('private transport error'); await harness.navigateByUrl('/');
      buildEnvironment.production = true;
      preference.mockResolvedValue({ status: 200, body: { language: 'tr', current_ui_language: 'en', current_email_language: 'en' } });
      await harness.navigateByUrl('/account/register'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(TestBed.inject(Title).getTitle()).toBe('Create account — OrganicSEOOps');
      expect((harness.routeDebugElement!.componentInstance as Register).productLanguage()).toBe('tr');
      expect(harness.routeNativeElement?.querySelector('section')?.getAttribute('lang')).toBe('en');
      expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Create your account');
      expect(harness.routeNativeElement?.textContent).not.toContain('İncelenmemiş'); expect(signup).not.toHaveBeenCalled();
      expect(TestBed.inject(Router).url).toBe('/account/register');
    } finally { buildEnvironment.production = production; preference.mockRestore(); }
  });

  it.each(['en', 'tr'] as const)('keeps authentication errors generic and announces verification state in %s', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    const harness = await RouterTestingHarness.create('/account/login');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    let root = harness.routeNativeElement!;
    expect(root.querySelector('section')?.getAttribute('lang')).toBe(language);
    expect(root.querySelector('label[for="password"]')?.textContent).toBe(language === 'tr' ? 'Parola' : 'Password');
    const form = root.querySelector('form')!;
    root.querySelector<HTMLInputElement>('#email')!.value = 'person@example.com';
    root.querySelector<HTMLInputElement>('#password')!.value = 'A-long-enough-password';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(root.textContent).toContain(language === 'tr' ? 'Oturum açılamadı. Bilgilerinizi kontrol edip tekrar deneyin.' : 'Sign-in failed. Check your details and try again.');
    expect(root.textContent).not.toContain('private backend detail');

    await harness.navigateByUrl('/account/verify-email#verification-key');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    root = harness.routeNativeElement!;
    expect(root.querySelector('h1')?.textContent).toBe(language === 'tr' ? 'E-posta adresinizi doğrulayın' : 'Confirm your email address');
    expect(document.activeElement).toBe(root.querySelector('h1'));
    expect(root.querySelector('section')?.getAttribute('lang')).toBe(language);
    expect(root.querySelector('button')?.textContent).toBe(language === 'tr' ? 'E-posta adresini doğrula' : 'Verify email address');
    expect(root.textContent).toContain(language === 'tr' ? 'Henüz kuruluş veya deneme süresi oluşturulmayacak' : 'No organization or trial will be created yet');
    expect(TestBed.inject(Location).path(true)).toBe('/account/verify-email');
    expect(document.body.textContent).not.toContain('verification-key');
    expect(api.confirmedVerificationKeys).toEqual([]);
    const component = harness.routeDebugElement!.componentInstance as VerifyEmail;
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'E-postayı doğrula — OrganicSEOOps' : 'Verify email — OrganicSEOOps');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Verify email — OrganicSEOOps' : 'E-postayı doğrula — OrganicSEOOps');
    expect(api.confirmedVerificationKeys).toEqual([]); expect(component.state()).toBe('pending');
    component.productLanguage.set(language); harness.fixture.detectChanges();
    root.querySelector<HTMLButtonElement>('button')!.click();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.confirmedVerificationKeys).toEqual(['verification-key']);
    expect(root.querySelector('h1')?.textContent).toBe(language === 'tr' ? 'E-posta adresi doğrulandı' : 'Email address verified');
    expect(root.querySelector('a')?.textContent).toBe(language === 'tr' ? 'Oturum açmaya devam et' : 'Continue to sign in');
    expect(document.activeElement).toBe(root.querySelector('h1'));
  });

  it('keeps invalid, unavailable or signed-out verification preference and fresh production English', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const preference = vi.spyOn(api, 'productLanguage');
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    try {
      const harness = await RouterTestingHarness.create();
      for (const result of [
        { status: 200, body: { language: ['tr'], current_ui_language: 'en', current_email_language: 'en' } },
        { status: 200, body: { language: 'tr', current_ui_language: 'tr', current_email_language: 'tr' } },
        { status: 401, body: { detail: 'private preference error' } },
      ]) {
        preference.mockResolvedValue(result);
        await harness.navigateByUrl('/account/verify-email#fallback-secret');
        await harness.fixture.whenStable(); harness.fixture.detectChanges();
        expect(TestBed.inject(Title).getTitle()).toBe('Verify email — OrganicSEOOps');
        expect(harness.routeNativeElement?.querySelector('section')?.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Confirm your email address');
        expect(harness.routeNativeElement?.textContent).not.toContain('private preference error');
        await harness.navigateByUrl('/account/login');
      }
      preference.mockRejectedValue(new Error('private transport error'));
      await harness.navigateByUrl('/account/verify-email#fallback-secret');
      await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(TestBed.inject(Title).getTitle()).toBe('Verify email — OrganicSEOOps');
      expect(harness.routeNativeElement?.querySelector('section')?.getAttribute('lang')).toBe('en');
      expect(harness.routeNativeElement?.textContent).not.toContain('private transport error');
      await harness.navigateByUrl('/account/login');
      buildEnvironment.production = true;
      preference.mockResolvedValue({ status: 200, body: { language: 'tr', current_ui_language: 'en', current_email_language: 'en' } });
      await harness.navigateByUrl('/account/verify-email#fallback-secret');
      await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(TestBed.inject(Title).getTitle()).toBe('Verify email — OrganicSEOOps');
      expect((harness.routeDebugElement!.componentInstance as VerifyEmail).productLanguage()).toBe('tr');
      expect(harness.routeNativeElement?.querySelector('section')?.getAttribute('lang')).toBe('en');
      expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Confirm your email address');
      expect(api.confirmedVerificationKeys).toEqual([]);
      expect(TestBed.inject(Location).path(true)).toBe('/account/verify-email');
      expect(document.body.textContent).not.toContain('fallback-secret');
    } finally { buildEnvironment.production = production; preference.mockRestore(); }
  });

  it.each(['en', 'tr'] as const)('keeps verification resend deliberate, masked and non-enumerating in %s', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    const resend = vi.spyOn(api, 'resendVerification');
    const harness = await RouterTestingHarness.create('/account/verify?to=pers***%40example.com');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    expect(root.querySelector('section')?.getAttribute('lang')).toBe(language);
    expect(root.querySelector('h1')?.textContent).toBe(language === 'tr' ? 'E-postanızı kontrol edin' : 'Check your email');
    expect(root.querySelector('span[lang=""]')?.textContent).toBe('pers***@example.com');
    expect(root.querySelector('label[for="resend-email"]')?.textContent).toBe(language === 'tr' ? 'Başka bir bağlantı mı gerekiyor? E-posta adresinizi girin' : 'Need another link? Enter your email address');
    expect(root.textContent).toContain(language === 'tr' ? 'kuruluş veya deneme süresi oluşturmadı' : 'has not created an organization or trial');
    const component = harness.routeDebugElement!.componentInstance as VerificationPending;
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'E-postayı doğrula — OrganicSEOOps' : 'Verify email — OrganicSEOOps');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Verify email — OrganicSEOOps' : 'E-postayı doğrula — OrganicSEOOps');
    expect(resend).not.toHaveBeenCalled();
    component.productLanguage.set(language); harness.fixture.detectChanges();
    const email = root.querySelector<HTMLInputElement>('#resend-email')!; email.value = 'person@example.com';
    const messages = language === 'tr'
      ? ['Doğrulama kullanılabiliyorsa', 'lütfen bekleyin', 'İstek tamamlanamadı', 'geçici olarak kullanılamıyor']
      : ['If verification is available', 'Please wait', 'The request could not be completed', 'temporarily unavailable'];
    for (const [index, status] of [200, 429, 503, null].entries()) {
      if (status === null) resend.mockRejectedValue(new Error('private transport error'));
      else resend.mockResolvedValue({ status, body: { detail: 'private server error' } });
      email.form!.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
      await harness.fixture.whenStable(); harness.fixture.detectChanges();
      await new Promise(resolve => setTimeout(resolve));
      expect(resend).toHaveBeenLastCalledWith('person@example.com');
      expect(root.querySelector('.form-status')?.textContent).toContain(messages[index]);
      expect(root.textContent).not.toContain('private server error'); expect(root.textContent).not.toContain('private transport error');
      expect(component.failed()).toBe(status !== 200);
      expect(document.activeElement).toBe(root.querySelector('.form-status'));
    }
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(resend).toHaveBeenCalledTimes(4);
    await harness.navigateByUrl('/account/login');
    await harness.navigateByUrl('/account/verify?to=full-address%40example.com');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).not.toContain('full-address@example.com');
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'e-posta adresiniz' : 'your email address');
  });

  it('keeps invalid, unavailable or signed-out verification-resend preference and fresh production English', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const preference = vi.spyOn(api, 'productLanguage');
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    try {
      const harness = await RouterTestingHarness.create();
      for (const result of [
        { status: 200, body: { language: ['tr'], current_ui_language: 'en', current_email_language: 'en' } },
        { status: 200, body: { language: 'tr', current_ui_language: 'tr', current_email_language: 'tr' } },
        { status: 401, body: { detail: 'private preference error' } },
      ]) {
        preference.mockResolvedValue(result);
        await harness.navigateByUrl('/account/verify');
        await harness.fixture.whenStable(); harness.fixture.detectChanges();
        expect(TestBed.inject(Title).getTitle()).toBe('Verify email — OrganicSEOOps');
        expect(harness.routeNativeElement?.querySelector('section')?.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Check your email');
        expect(harness.routeNativeElement?.textContent).not.toContain('private preference error');
        await harness.navigateByUrl('/account/login');
      }
      preference.mockRejectedValue(new Error('private transport error'));
      await harness.navigateByUrl('/account/verify');
      await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(TestBed.inject(Title).getTitle()).toBe('Verify email — OrganicSEOOps');
      expect(harness.routeNativeElement?.querySelector('section')?.getAttribute('lang')).toBe('en');
      expect(harness.routeNativeElement?.textContent).not.toContain('private transport error');
      await harness.navigateByUrl('/account/login');
      buildEnvironment.production = true;
      preference.mockResolvedValue({ status: 200, body: { language: 'tr', current_ui_language: 'en', current_email_language: 'en' } });
      await harness.navigateByUrl('/account/verify');
      await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(TestBed.inject(Title).getTitle()).toBe('Verify email — OrganicSEOOps');
      expect((harness.routeDebugElement!.componentInstance as VerificationPending).productLanguage()).toBe('tr');
      expect(harness.routeNativeElement?.querySelector('section')?.getAttribute('lang')).toBe('en');
      expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Check your email');
      expect(api.resentVerificationEmails).toEqual([]);
      expect(TestBed.inject(Location).path(true)).toBe('/account/verify');
      expect(document.body.textContent).not.toContain('fallback-secret');
    } finally { buildEnvironment.production = production; preference.mockRestore(); }
  });

  it('rejects malformed scalar states in existing verification and provider screens', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const harness = await RouterTestingHarness.create('/account/verify-email#scalar-state-fixture');
    await harness.fixture.whenStable();
    const verification = harness.routeDebugElement!.componentInstance;
    for (const state of ['pending', 'expired', 'used', 'invalid']) {
      api.verificationResult = { status: 200, body: { state: [state] } };
      await verification.ngOnInit(); harness.fixture.detectChanges();
      expect(verification.state()).toBe('invalid');
      expect(harness.routeNativeElement?.textContent).toContain('Request a new verification email');
    }
    api.verificationResult = { status: 200, body: { state: 'pending' } };
    await verification.ngOnInit(); harness.fixture.detectChanges();
    expect(verification.state()).toBe('pending');
    expect(harness.routeNativeElement?.textContent).toContain('Verify email address');

    await harness.navigateByUrl('/account/provider-settings'); await harness.fixture.whenStable();
    const platform = harness.routeDebugElement!.componentInstance;
    for (const state of ['unconfigured', 'active', 'revoked', 'environment_reference']) {
      api.performanceKeyResult = { status: 200, body: { state: [state] } };
      await platform.loadPerformance(); expect(platform.performanceState()).toBe('denied');
      const result = { status: 200, body: { state: [state], redirect_uri: '' } };
      api.googleApplicationResult = result;
      vi.spyOn(api, 'platformGoogleAnalyticsApp').mockResolvedValue(result);
      vi.spyOn(api, 'platformGoogleBusinessApp').mockResolvedValue(result);
      for (const [kind, status] of [['search', platform.googleState], ['analytics', platform.analyticsState],
                                    ['business', platform.businessState]]) {
        await platform.loadGoogle(kind); expect(status()).toBe('denied');
      }
      harness.fixture.detectChanges();
      expect(harness.routeNativeElement?.querySelector('#performance-api-key')).toBeNull();
    }
    api.performanceKeyResult = { status: 200, body: { state: 'active' } };
    await platform.loadPerformance(); expect(platform.performanceState()).toBe('active');
    api.googleApplicationResult = { status: 200, body: { state: 'active', redirect_uri: '' } };
    vi.spyOn(api, 'platformGoogleAnalyticsApp').mockResolvedValue(api.googleApplicationResult);
    vi.spyOn(api, 'platformGoogleBusinessApp').mockResolvedValue(api.googleApplicationResult);
    for (const [kind, status] of [['search', platform.googleState], ['analytics', platform.analyticsState],
                                  ['business', platform.businessState]]) {
      await platform.loadGoogle(kind); expect(status()).toBe('active');
    }

    api.organizationProviderResult = { status: 200, body: { providers: [], accounts: [], has_more: false } };
    await harness.navigateByUrl('/app/provider-accounts/7'); await harness.fixture.whenStable();
    const organization = harness.routeDebugElement!.componentInstance;
    for (const state of ['unconfigured', 'active', 'revoked']) {
      api.organizationPerformanceResult = { status: 200, body: { state: [state] } };
      await organization.loadPerformance(); harness.fixture.detectChanges();
      expect(organization.performanceState()).toBe('denied');
      expect(harness.routeNativeElement?.querySelector('#organization-performance-key')).toBeNull();
    }
    api.organizationPerformanceResult = { status: 200, body: { state: 'active' } };
    await organization.loadPerformance(); expect(organization.performanceState()).toBe('active');
  });

  it('rejects enum arrays and clears stale provider rows and seller metadata after malformed refresh', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const provider = { id: 9, key: 'native', name: 'Provider', kind: 'openai', enabled: true };
    const account = { id: 8, provider_id: 9, label: 'Account', state: 'active', stored: true };
    const model = { id: 3, provider_id: 9, identifier: 'selected', name: 'Model',
      capabilities: ['text_generation'], enabled: true, max_output_tokens: 200,
      capability_source: 'https://example.com/models', input_price_usd_per_million: '0.1250',
      output_price_usd_per_million: '2.5000', pricing_source: 'https://example.com/prices',
      access_tier: 'standard', privacy_policy_url: '' };
    const valid = { status: 200, body: { providers: [provider], accounts: [account], has_more: false } };
    const harness = await RouterTestingHarness.create('/account/provider-settings');
    await harness.fixture.whenStable();
    const platform = harness.routeDebugElement!.componentInstance;
    for (const rows of [{ providers: [{ ...provider, kind: ['openai'] }], accounts: [account] },
                        { providers: [provider], accounts: [{ ...account, state: ['active'] }] },
                        { providers: [provider], accounts: [{ ...account, state: 'unsupported' }] }]) {
      api.platformProvidersResult = valid; await platform.load();
      expect(platform.providers().length).toBe(1); expect(platform.accounts().length).toBe(1);
      api.platformProvidersResult = { status: 200, body: { ...rows, has_more: false } };
      await platform.load(); harness.fixture.detectChanges();
      expect(platform.providers()).toEqual([]); expect(platform.accounts()).toEqual([]);
      expect(platform.denied()).toBe(true);
    }
    for (const tier of ['unknown', 'standard', 'free']) {
      api.platformModelsResult = { status: 200, body: { models: [model], has_more: false, capability_choices: ['text_generation'] } };
      await platform.loadModels(); expect(platform.models().length).toBe(1);
      api.platformModelsResult.body['models'] = [{ ...model, access_tier: [tier] }];
      await platform.loadModels(); expect(platform.models()).toEqual([]); expect(platform.modelDenied()).toBe(true);
    }
    for (const environment of ['sandbox', 'live']) {
      for (const state of ['active', 'revoked', 'unconfigured']) {
        const body = { environment, state: 'active', product_id: 'fixture-product', price_id: 'fixture-price', catalog_verified: false };
        vi.spyOn(api, 'platformPaddleSeller').mockResolvedValue({ status: 200, body });
        await platform.loadPaddle(environment); expect(platform.paddleStates()[environment]).toBe('active');
        vi.spyOn(api, 'platformPaddleSeller').mockResolvedValue({ status: 200, body: { ...body, state: [state] } });
        await platform.loadPaddle(environment);
        expect(platform.paddleStates()[environment]).toBe('denied');
        expect(platform.paddleProducts()[environment]).toBe(''); expect(platform.paddlePrices()[environment]).toBe('');
      }
    }
    await harness.navigateByUrl('/app/provider-accounts/7'); await harness.fixture.whenStable();
    const organization = harness.routeDebugElement!.componentInstance;
    for (const rows of [{ providers: [{ ...provider, kind: ['openai'] }], accounts: [account] },
                        { providers: [provider], accounts: [{ ...account, state: ['active'] }] },
                        { providers: [provider], accounts: [{ ...account, state: 'unsupported' }] }]) {
      api.organizationProviderResult = valid; await organization.load();
      expect(organization.providers().length).toBe(1); expect(organization.accounts().length).toBe(1);
      api.organizationProviderResult = { status: 200, body: { ...rows, has_more: false } };
      await organization.load(); harness.fixture.detectChanges();
      expect(organization.providers()).toEqual([]); expect(organization.accounts()).toEqual([]);
      expect(organization.denied()).toBe(true);
    }
  });

  it.each(['en', 'tr'] as const)('completes a pending staff MFA login without exposing backend errors in %s', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    const login = vi.spyOn(api, 'login');
    api.loginResult = { status: 401, body: { data: { flows: [
      { id: 'mfa_authenticate', is_pending: true, types: ['totp', 'recovery_codes'] },
    ] } } };
    api.mfaResult = { status: 200, body: { data: { user: { email: 'staff@example.com' } } } };
    const harness = await RouterTestingHarness.create('/account/login');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Oturum aç — OrganicSEOOps' : 'Sign in — OrganicSEOOps');
    let root = harness.routeNativeElement!;
    root.querySelector<HTMLInputElement>('#email')!.value = 'staff@example.com';
    root.querySelector<HTMLInputElement>('#password')!.value = 'A-long-enough-password';
    root.querySelector('form')!.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    root = harness.routeNativeElement!;
    expect(root.textContent).toContain(language === 'tr' ? 'kullanılmamış kurtarma kodu gerekir' : 'requires a code');
    expect(root.querySelector('#email')).toBeNull();
    expect(root.querySelector('label[for="mfa-code"]')?.textContent).toBe(language === 'tr' ? 'Kimlik doğrulama kodu' : 'Authentication code');
    const component = harness.routeDebugElement!.componentInstance as Login;
    const code = root.querySelector<HTMLInputElement>('#mfa-code')!; code.value = 'recovery-code';
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Sign in — OrganicSEOOps' : 'Oturum aç — OrganicSEOOps');
    expect(code.value).toBe('recovery-code'); expect(api.mfaCodes).toEqual([]); expect(login).toHaveBeenCalledOnce();
    component.productLanguage.set(language); harness.fixture.detectChanges();
    api.mfaResult = { status: 403, body: { detail: 'private MFA error' } };
    code.form!.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    await new Promise(resolve => setTimeout(resolve));
    expect(root.querySelector('[role="alert"]')?.textContent).toBe(language === 'tr' ? 'Kimlik doğrulama kodu kabul edilmedi. Kontrol edip tekrar deneyin.' : 'The authentication code was not accepted. Check it and try again.');
    expect(root.textContent).not.toContain('private MFA error');
    expect(document.activeElement).toBe(root.querySelector('[role="alert"]'));
    api.mfaResult = { status: 200, body: {} };
    root.querySelector('form')!.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    expect(api.mfaCodes).toEqual(['recovery-code', 'recovery-code']);
    expect(TestBed.inject(Router).url).toBe('/app');
  });

  it('keeps invalid, unavailable or signed-out login preference and fresh production English', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const preference = vi.spyOn(api, 'productLanguage'), login = vi.spyOn(api, 'login');
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    try {
      const harness = await RouterTestingHarness.create();
      for (const result of [
        { status: 200, body: { language: ['tr'], current_ui_language: 'en', current_email_language: 'en' } },
        { status: 200, body: { language: 'tr', current_ui_language: 'tr', current_email_language: 'tr' } },
        { status: 401, body: { detail: 'private preference error' } },
      ]) {
        preference.mockResolvedValue(result);
        await harness.navigateByUrl('/account/login');
        await harness.fixture.whenStable(); harness.fixture.detectChanges();
        expect(TestBed.inject(Title).getTitle()).toBe('Sign in — OrganicSEOOps');
        expect(harness.routeNativeElement?.querySelector('section')?.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Sign in');
        expect(harness.routeNativeElement?.textContent).not.toContain('private preference error');
        await harness.navigateByUrl('/');
      }
      preference.mockRejectedValue(new Error('private transport error'));
      await harness.navigateByUrl('/account/login');
      await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(TestBed.inject(Title).getTitle()).toBe('Sign in — OrganicSEOOps');
      expect(harness.routeNativeElement?.querySelector('section')?.getAttribute('lang')).toBe('en');
      expect(harness.routeNativeElement?.textContent).not.toContain('private transport error');
      await harness.navigateByUrl('/');
      buildEnvironment.production = true;
      preference.mockResolvedValue({ status: 200, body: { language: 'tr', current_ui_language: 'en', current_email_language: 'en' } });
      await harness.navigateByUrl('/account/login');
      await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(TestBed.inject(Title).getTitle()).toBe('Sign in — OrganicSEOOps');
      expect((harness.routeDebugElement!.componentInstance as Login).productLanguage()).toBe('tr');
      expect(harness.routeNativeElement?.querySelector('section')?.getAttribute('lang')).toBe('en');
      expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Sign in');
      expect(api.mfaCodes).toEqual([]); expect(login).not.toHaveBeenCalled();
      expect(TestBed.inject(Location).path(true)).toBe('/account/login');
      expect(document.body.textContent).not.toContain('fallback-secret');
    } finally { buildEnvironment.production = production; preference.mockRestore(); }
  });

  it.each(['en', 'tr'] as const)('does not claim logout succeeded when the server rejects it in %s', async (language) => {
    (TestBed.inject(AccountApi) as unknown as AccountApiStub).savedProductLanguage = language;
    const harness = await RouterTestingHarness.create('/app');
    harness.routeNativeElement?.querySelector<HTMLButtonElement>('.sign-out')?.click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(TestBed.inject(Router).url).toBe('/app');
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'Oturumunuz hâlâ etkin olabilir' : 'Your session may still be active');
  });

  it.each(['en', 'tr'] as const)('returns to login after a successful logout response in %s', async (language) => {
    (TestBed.inject(AccountApi) as unknown as AccountApiStub).savedProductLanguage = language;
    const harness = await RouterTestingHarness.create('/app');
    (TestBed.inject(AccountApi) as unknown as AccountApiStub).logoutResult = { status: 204, body: {} };
    harness.routeNativeElement?.querySelector<HTMLButtonElement>('.sign-out')?.click();
    await harness.fixture.whenStable();
    expect(TestBed.inject(Router).url).toBe('/account/login');
  });

  it.each(['en', 'tr'] as const)('keeps password recovery responses generic and requests deliberate in %s', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    const request = vi.spyOn(api, 'requestPasswordReset');
    const harness = await RouterTestingHarness.create('/account/forgot-password');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Parolayı sıfırla — OrganicSEOOps' : 'Reset password — OrganicSEOOps');
    const root = harness.routeNativeElement!, component = harness.routeDebugElement!.componentInstance as ForgotPassword;
    const input = root.querySelector<HTMLInputElement>('#recovery-email')!, form = root.querySelector('form')!;
    expect(root.querySelector('section')?.getAttribute('lang')).toBe(language);
    expect(root.querySelector('label')?.textContent).toBe(language === 'tr' ? 'E-posta adresi' : 'Email address');
    expect(root.querySelector('button')?.textContent).toBe(language === 'tr' ? 'Sıfırlama bağlantısı gönder' : 'Send reset link');
    expect(root.querySelector('a')?.getAttribute('href')).toBe('/account/login');
    expect(root.textContent).toContain(language === 'tr' ? 'bir saat sonra' : 'one hour');
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true })); expect(request).not.toHaveBeenCalled();
    input.value = 'person@example.com'; let resolve!: (result: ApiResult) => void;
    request.mockImplementationOnce(() => new Promise(done => resolve = done));
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true })); harness.fixture.detectChanges();
    expect(root.querySelector<HTMLButtonElement>('button')!.disabled).toBe(true);
    expect(root.querySelector('button')?.textContent).toBe(language === 'tr' ? 'İstek gönderiliyor…' : 'Requesting…');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Reset password — OrganicSEOOps' : 'Parolayı sıfırla — OrganicSEOOps');
    expect(input.value).toBe('person@example.com');
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true })); expect(request).toHaveBeenCalledTimes(1);
    component.productLanguage.set(language); resolve({ status: 200, body: { detail: 'private recovery detail' } });
    await harness.fixture.whenStable(); harness.fixture.detectChanges(); await new Promise(done => setTimeout(done));
    expect(root.textContent).toContain(language === 'tr' ? 'Kurtarma kullanılabiliyorsa bir sıfırlama bağlantısı gönderildi.' : 'If recovery is available, a reset link has been sent.');
    expect(root.textContent).not.toContain('person@example.com'); expect(root.textContent).not.toContain('private recovery detail');
    expect(input.value).toBe(''); expect(document.activeElement?.getAttribute('role')).toBe('status');
    expect(request).toHaveBeenLastCalledWith('person@example.com');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(root.textContent).toContain(language === 'tr' ? 'If recovery is available, a reset link has been sent.' : 'Kurtarma kullanılabiliyorsa bir sıfırlama bağlantısı gönderildi.');
    expect(request).toHaveBeenCalledTimes(1); component.productLanguage.set(language);
    for (const status of [429, 503, 'transport'] as const) {
      input.value = 'person@example.com';
      if (status === 'transport') request.mockRejectedValueOnce(new Error('private transport detail'));
      else request.mockResolvedValueOnce({ status, body: { detail: 'private recovery detail' } });
      form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
      await harness.fixture.whenStable(); harness.fixture.detectChanges(); await new Promise(done => setTimeout(done));
      expect(root.querySelector('.form-status[role="status"]')).toBeNull();
      expect(root.querySelector('[role="alert"]')?.textContent).toBe(status === 429
        ? language === 'tr' ? 'Başka bir sıfırlama bağlantısı istemeden önce lütfen bekleyin.' : 'Please wait before requesting another reset link.'
        : language === 'tr' ? 'Parola kurtarma geçici olarak kullanılamıyor. Tekrar deneyin.' : 'Password recovery is temporarily unavailable. Try again.');
      expect(document.activeElement?.getAttribute('role')).toBe('alert'); expect(input.value).toBe('person@example.com');
      expect(root.textContent).not.toContain('private recovery detail'); expect(root.textContent).not.toContain('private transport detail');
    }
  });

  it('keeps invalid unavailable or signed-out recovery preference and fresh production English', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const preference = vi.spyOn(api, 'productLanguage'), request = vi.spyOn(api, 'requestPasswordReset');
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    const harness = await RouterTestingHarness.create();
    try {
      for (const mode of ['invalid', 'incompatible', 'signed-out', 'unavailable', 'production'] as const) {
        buildEnvironment.production = mode === 'production';
        if (mode === 'unavailable') preference.mockRejectedValue(new Error('private preference error'));
        else preference.mockResolvedValue(mode === 'signed-out' ? { status: 401, body: { detail: 'private preference error' } }
          : { status: 200, body: { language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: mode === 'incompatible' ? 'tr' : 'en', current_email_language: 'en' } });
        await harness.navigateByUrl('/account/forgot-password'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
        expect(TestBed.inject(Title).getTitle()).toBe('Reset password — OrganicSEOOps');
        expect(harness.routeNativeElement?.querySelector('section')?.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Reset your password');
        expect(harness.routeNativeElement?.textContent).not.toContain('private preference error');
        if (mode === 'production') expect((harness.routeDebugElement!.componentInstance as ForgotPassword).productLanguage()).toBe('tr');
        expect(TestBed.inject(Router).url).toBe('/account/forgot-password'); await harness.navigateByUrl('/');
      }
      expect(request).not.toHaveBeenCalled();
    } finally { buildEnvironment.production = production; preference.mockRestore(); }
  });

  it('keeps invalid unavailable or denied workspace preference and fresh production English', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const preference = vi.spyOn(api, 'productLanguage');
    const commands = [vi.spyOn(api, 'createOrganization'), vi.spyOn(api, 'createProject'), vi.spyOn(api, 'inviteMember'), vi.spyOn(api, 'reauthenticate'), vi.spyOn(api, 'logout')];
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    const harness = await RouterTestingHarness.create();
    try {
      for (const mode of ['invalid', 'incompatible', 'email', 'denied', 'unavailable', 'production'] as const) {
        buildEnvironment.production = mode === 'production';
        if (mode === 'unavailable') preference.mockRejectedValue(new Error('private preference error'));
        else preference.mockResolvedValue(mode === 'denied' ? { status: 403, body: { detail: 'private preference error' } }
          : { status: 200, body: { language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: mode === 'incompatible' ? 'tr' : 'en', current_email_language: mode === 'email' ? ['tr'] : 'en' } });
        await harness.navigateByUrl('/app'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
        expect(TestBed.inject(Title).getTitle()).toBe('Organization and project context — OrganicSEOOps');
        expect(harness.routeNativeElement?.querySelector('section')?.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Organization and project context');
        expect(harness.routeNativeElement?.textContent).not.toContain('private preference error');
        expect(harness.routeNativeElement?.textContent).not.toContain('Unreviewed Turkish');
        if (mode === 'production') expect((harness.routeDebugElement!.componentInstance as Overview).productLanguage()).toBe('tr');
        expect(TestBed.inject(Router).url).toBe('/app'); await harness.navigateByUrl('/');
      }
      for (const command of commands) expect(command).not.toHaveBeenCalled();
    } finally { buildEnvironment.production = production; preference.mockRestore(); }
  });

  it('shows settings to owners but not other organization roles', async () => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.organizationsResult = { status: 200, body: { organizations: [
      { id: 7, name: 'Owner organization', role: 'owner', access_state: 'active', trial: {
        state: 'active', access_state: 'active', offer_version: 'agency-launch-v1',
        started_at: '2026-09-01T12:00:00Z', ends_at: '2026-10-01T12:00:00Z',
        project_limit: 1, member_limit: 3, unit_limit: 40, settled_units: 12, reserved_units: 3,
      } },
    ] } };
    api.projectsResult = { status: 200, body: { projects: [
      {
        id: 9,
        organization_id: 7,
        name: 'Owner project',
        canonical_origin: 'https://owner.example',
        aliases: ['https://www.owner.example', 'https://m.owner.example'],
        access_restricted: false,
        role: 'owner',
      },
    ] } };
    await harness.navigateByUrl('/app');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain('Organization settings');
    expect(harness.routeNativeElement?.textContent).toContain('Project settings');
    expect(harness.routeNativeElement?.textContent).toContain('Team and project access');
    expect(harness.routeNativeElement?.textContent).toContain('Trial status');
    expect(harness.routeNativeElement?.textContent).toContain('40 internal units');
    expect(harness.routeNativeElement?.textContent).toContain('12 settled internal units and 3 currently reserved');
    expect(harness.routeNativeElement?.textContent).toContain('New work rechecks effective trial or paid capacity');
    expect(harness.routeNativeElement?.textContent).toContain('in your local time');
    expect(harness.routeNativeElement?.textContent).toContain('complete organization export, hosted deletion');
    expect(harness.routeNativeElement?.querySelector('time')?.getAttribute('datetime')).toBe('2026-10-01T12:00:00Z');
    expect(harness.routeNativeElement?.querySelector<HTMLTextAreaElement>('#project-aliases')?.value).toBe(
      'https://www.owner.example\nhttps://m.owner.example',
    );

    await harness.navigateByUrl('/');
    api.organizationsResult = { status: 200, body: { organizations: [
      { id: 7, name: 'Expired suspended organization', role: 'owner', access_state: 'suspended', trial: {
        state: 'expired', access_state: 'suspended', offer_version: 'agency-launch-v1',
        started_at: '2026-08-01T12:00:00Z', ends_at: '2026-08-31T12:00:00Z',
        project_limit: 1, member_limit: 3, unit_limit: 40, settled_units: 12, reserved_units: 0,
      } },
    ] } };
    await harness.navigateByUrl('/app');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain('Expired and suspended');

    await harness.navigateByUrl('/');
    api.organizationsResult = { status: 200, body: { organizations: [
      { id: 7, name: 'Viewer organization', role: 'viewer' },
    ] } };
    api.projectsResult = { status: 200, body: { projects: [] } };
    await harness.navigateByUrl('/app');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).not.toContain('Organization settings');
    expect(harness.routeNativeElement?.textContent).not.toContain('Add project');
    expect(harness.routeNativeElement?.textContent).not.toContain('Team and project access');
  });

  it('fails closed when trial dates or lifecycle states are malformed', async () => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.organizationsResult = { status: 200, body: { organizations: [{
      id: 7, name: 'Malformed trial', role: 'owner', access_state: 'active', trial: {
        state: 'active', access_state: 'read_only', offer_version: 'agency-launch-v1',
        started_at: 'not-a-date', ends_at: 'also-not-a-date',
        project_limit: 1, member_limit: 3, unit_limit: 40, settled_units: 0, reserved_units: 0,
      },
    }] } };
    await harness.navigateByUrl('/app');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain('Trial status');
    expect(harness.routeNativeElement?.textContent).toContain('Trial status could not be loaded');
    expect(harness.routeNativeElement?.textContent).not.toContain('Invalid Date');
  });

  it('lets admins manage members and projects without exposing privileged grants', async () => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.organizationsResult = { status: 200, body: { organizations: [
      { id: 7, name: 'Admin organization', role: 'admin' },
    ] } };
    api.projectsResult = { status: 200, body: { projects: [
      {
        id: 9,
        organization_id: 7,
        name: 'Admin project',
        canonical_origin: 'https://admin.example',
        aliases: [],
        access_restricted: true,
        role: 'admin',
      },
    ] } };
    api.teamResult = { status: 200, body: {
      members: [
        { id: 1, email: 'owner@example.com', role: 'owner', project_ids: [] },
        { id: 2, email: 'member@example.com', role: 'member', project_ids: [9] },
      ],
      invitations: [],
      events: [],
    } };
    await harness.navigateByUrl('/app');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    expect(root.textContent).toContain('Team and project access');
    expect(root.textContent).toContain('Project settings');
    expect(root.textContent).not.toContain('Organization settings');
    expect(root.querySelectorAll<HTMLSelectElement>('.team-list select')[0].textContent).toContain('member');
    expect(root.querySelectorAll<HTMLSelectElement>('.team-list select')[0].textContent).not.toContain('admin');
    expect(root.querySelectorAll('.team-list .danger-button').length).toBe(1);
  });

  it.each(['en', 'tr'] as const)('submits team invitations and requires confirmation before removal in %s', async (language) => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    api.organizationsResult = { status: 200, body: { organizations: [
      { id: 7, name: 'Owner organization', role: 'owner' },
    ] } };
    api.projectsResult = { status: 200, body: { projects: [{
      id: 9,
      organization_id: 7,
      name: 'Assigned project',
      canonical_origin: 'https://assigned.example',
      aliases: [],
      access_restricted: true,
      role: 'owner',
    }] } };
    api.teamResult = { status: 200, body: {
      members: [{ id: 2, email: 'member@example.com', role: 'member', project_ids: [] }],
      invitations: [],
      events: [],
    } };
    await harness.navigateByUrl('/app');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    expect([...root.querySelectorAll<HTMLOptionElement>('#invitation-role option')].map((option) => option.value))
      .toEqual(['member', 'viewer', 'admin']);
    root.querySelector<HTMLInputElement>('#invitation-email')!.value = 'new-member@example.com';
    root.querySelector<HTMLSelectElement>('#invitation-role')!.value = 'viewer';
    root.querySelector<HTMLInputElement>('#invitation-project-9')!.checked = true;
    const component = harness.routeDebugElement!.componentInstance as Overview;
    expect(root.querySelector('section')?.getAttribute('lang')).toBe(language);
    expect(root.querySelector('h1')?.textContent).toBe(language === 'tr' ? 'Kuruluş ve proje bağlamı' : 'Organization and project context');
    const controls = ['#organization-name', '#project-name', '#project-origin', '#project-aliases', '#new-project-name', '#new-project-origin', '#new-project-aliases', '#new-project-restricted', '#invitation-email', '#invitation-role', '#invitation-project-9', '#member-role-2', '#member-2-project-9'];
    const nodes = controls.map(id => root.querySelector<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(id)!);
    for (const node of nodes) {
      if (node instanceof HTMLInputElement && node.type === 'checkbox') node.checked = true;
      else if (node.tagName !== 'SELECT' && !node.id.startsWith('invitation-')) node.value = node.id.includes('origin') ? 'https://unsaved.example' : 'İnsan metni 雪';
    }
    const values = nodes.map(node => [node.value, node instanceof HTMLInputElement ? node.checked : null]);
    const commands = [vi.spyOn(api, 'inviteMember'), vi.spyOn(api, 'updateMember'), vi.spyOn(api, 'updateOrganization'), vi.spyOn(api, 'updateProject')];
    const reads = [vi.spyOn(api, 'organizations'), vi.spyOn(api, 'projects'), vi.spyOn(api, 'team')];
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    for (let i = 0; i < controls.length; i++) {
      expect(root.querySelector(controls[i])).toBe(nodes[i]);
      expect([nodes[i].value, nodes[i] instanceof HTMLInputElement ? (nodes[i] as HTMLInputElement).checked : null]).toEqual(values[i]);
    }
    for (const command of [...commands, ...reads]) expect(command).not.toHaveBeenCalled();
    expect(root.querySelector('#project-name')?.getAttribute('lang')).toBe('');
    expect(root.querySelector('#member-role-2 option')?.getAttribute('lang')).toBe('en');
    component.productLanguage.set(language); harness.fixture.detectChanges();
    root.querySelector<HTMLInputElement>('#invitation-email')!.form!.dispatchEvent(
      new SubmitEvent('submit', { bubbles: true, cancelable: true }),
    );
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.invitedEmail).toBe('new-member@example.com');
    expect(api.invitedRole).toBe('viewer');
    expect(api.invitedProjects).toEqual([9]);
    expect(root.textContent).toContain(language === 'tr' ? 'Davet gönderildi' : 'Invitation sent');

    let remove = root.querySelector<HTMLButtonElement>('.team-list .danger-button')!;
    remove.click();
    harness.fixture.detectChanges();
    expect(remove.textContent).toContain(language === 'tr' ? 'Üyeyi kaldırmayı onaylayın' : 'Confirm remove member');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(component.pendingRemoval()).toBe(2); expect(api.removedMembers).toEqual([]);
    component.productLanguage.set(language); harness.fixture.detectChanges();
    remove = root.querySelector<HTMLButtonElement>('.team-list .danger-button')!;
    remove.click();
    await harness.fixture.whenStable();
    expect(api.removedMembers).toEqual([2]);
  });

  it.each(['en', 'tr'] as const)('requires confirmation before replacing a pending invitation link in %s', async (language) => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    api.organizationsResult = { status: 200, body: { organizations: [
      { id: 7, name: 'Owner organization', role: 'owner' },
    ] } };
    api.teamResult = { status: 200, body: {
      members: [],
      invitations: [{ id: 12, email: 'invited@example.com', role: 'viewer', state: 'pending', project_ids: [], expires_at: '2026-10-01' }],
    } };
    await harness.navigateByUrl('/app');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    const reissue = [...root.querySelectorAll<HTMLButtonElement>('.invitation-list button')]
      .find((button) => button.textContent?.includes(language === 'tr' ? 'Daveti yeniden gönderin' : 'Reissue invitation'))!;
    reissue.click();
    harness.fixture.detectChanges();
    expect(api.reissuedInvitations).toEqual([]);
    expect(reissue.textContent).toContain(language === 'tr' ? 'eski bağlantı çalışmaz' : 'old link stops working');
    const component = harness.routeDebugElement!.componentInstance as Overview;
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(component.pendingInvitationReissue()).toBe(12); expect(api.reissuedInvitations).toEqual([]);
    expect(root.querySelector('.invitation-list button')).toBe(reissue);
    component.productLanguage.set(language); harness.fixture.detectChanges();
    reissue.click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.reissuedInvitations).toEqual([12]);
    expect(root.textContent).toContain(language === 'tr' ? 'Eski bağlantı artık çalışmaz' : 'The old link no longer works');
  });

  it.each(['en', 'tr'] as const)('reuses the same diagnostic key after an unknown request outcome in %s', async (language) => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    api.projectsResult = { status: 200, body: {
      organization: { id: 7, name: 'Owner organization', role: 'owner' },
      projects: [{ id: 9, name: 'Authorized project', organization_id: 7 }],
    } };
    let attempts = 0;
    api.diagnosticHandler = () => ++attempts === 1 ? Promise.reject(new Error('network'))
      : Promise.resolve({ status: 202, body: { job: api.jobDetailResult.body['job'] } });
    await harness.navigateByUrl('/app/jobs/7/9');
    await harness.fixture.whenStable();
    await new Promise((resolve) => setTimeout(resolve));
    harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    expect(root.querySelector('section')!.getAttribute('lang')).toBe(language);
    expect(root.querySelector('h1')!.textContent).toBe(language === 'tr' ? 'Proje işi ilerlemesi' : 'Project job progress');
    expect(root.textContent).toContain(language === 'tr' ? 'sıfır tanılama birimi' : 'zero diagnostic units');
    root.querySelector<HTMLInputElement>('#diagnostic-sample')!.value = 'same sample';
    const form = root.querySelector<HTMLInputElement>('#diagnostic-sample')!.form!;
    expect(root.querySelector('label[for="diagnostic-sample"]')!.textContent).toBe(language === 'tr' ? 'Kısa sentetik örnek' : 'Short synthetic sample');
    const component = harness.routeDebugElement!.componentInstance as JobDashboard;
    const read = vi.spyOn(api, 'jobs'), write = vi.spyOn(api, 'createDiagnostic');
    const retained = component.jobs(); component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(component.jobs()).toBe(retained); expect(form.querySelector<HTMLInputElement>('[name="sample"]')!.value).toBe('same sample');
    expect(read).not.toHaveBeenCalled(); expect(write).not.toHaveBeenCalled();
    component.productLanguage.set(language); harness.fixture.detectChanges();
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(root.textContent).toContain(language === 'tr' ? 'İstek sonucu bilinmiyor' : 'request outcome is unknown');
    await vi.waitFor(() => expect(document.activeElement).toBe(root.querySelector('[role="alert"]')));
    expect(root.textContent).not.toContain('network');
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    expect(api.diagnosticKeys).toHaveLength(2);
    expect(api.diagnosticKeys[0]).toBe(api.diagnosticKeys[1]);
    expect(TestBed.inject(Router).url).toBe('/app/jobs/7/9/3');
  });

  it.each(['en', 'tr'] as const)('shows schedule state and avoids duplicate schedule creation after a lost response in %s', async (language) => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    api.projectsResult = { status: 200, body: {
      organization: { id: 7, name: 'Owner organization', role: 'owner' },
      projects: [{ id: 9, name: 'Scheduled site', organization_id: 7 }],
    } };
    api.jobSchedulesResult = { status: 200, body: { schedules: [{
      id: 12, project_id: 9, enabled: false, interval_minutes: 60,
      next_run_at: null, last_run_at: '2026-09-24T09:00:00Z',
      skipped_occurrences: 3, last_error_category: 'internal_capacity',
    }] } };
    let attempts = 0;
    api.scheduleHandler = () => ++attempts === 1 ? Promise.reject(new Error('network'))
      : Promise.resolve({ status: 201, body: { schedule: api.jobSchedulesResult.body['schedules'] instanceof Array
        ? (api.jobSchedulesResult.body['schedules'] as object[])[0] : {} } });
    await harness.navigateByUrl('/app/jobs/7/9');
    await new Promise((resolve) => setTimeout(resolve));
    harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    expect(root.querySelector('section')!.getAttribute('lang')).toBe(language);
    expect(root.querySelector('h1')!.textContent).toBe(language === 'tr' ? 'Proje işi ilerlemesi' : 'Project job progress');
    expect(root.textContent).toContain(language === 'tr' ? 'atlanan 3 kaçırılmış çalıştırma' : 'skipped 3 missed runs');
    expect(root.textContent).toContain(language === 'tr' ? 'sorun internal_capacity' : 'issue internal_capacity');
    root.querySelector<HTMLInputElement>('#schedule-sample')!.value = 'synthetic';
    const form = root.querySelector<HTMLInputElement>('#schedule-sample')!.form!;
    expect(form.querySelector('label[for="schedule-sample"]')!.textContent).toBe(language === 'tr' ? 'Gelecekteki çalıştırmalar için sentetik örnek' : 'Synthetic sample for future runs');
    expect(root.querySelector('span[lang="en"]')!.textContent).toBe('2026-09-24T09:00:00Z');
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(root.textContent).toContain(language === 'tr' ? 'Zamanlama sonucu bilinmiyor' : 'Schedule outcome is unknown');
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.scheduleKeys).toHaveLength(2);
    expect(api.scheduleKeys[0]).toBe(api.scheduleKeys[1]);
    const toggle = [...root.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent?.includes(language === 'tr' ? 'Zamanlamayı etkinleştirin' : 'Enable schedule'))!;
    toggle.click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.scheduleToggles).toEqual([true]);
    expect(root.textContent).toContain(language === 'tr' ? 'sonraki 2026-09-25' : 'next 2026-09-25');

    await harness.navigateByUrl('/');
    api.projectsResult = { status: 200, body: {
      organization: { id: 7, name: 'Viewer organization', role: 'viewer' },
      projects: [{ id: 9, name: 'Read-only site', organization_id: 7 }],
    } };
    await harness.navigateByUrl('/app/jobs/7/9');
    await new Promise((resolve) => setTimeout(resolve));
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'atlanan 3 kaçırılmış çalıştırma' : 'skipped 3 missed runs');
    expect(harness.routeNativeElement?.querySelector('#schedule-sample')).toBeFalsy();
    expect(harness.routeNativeElement?.textContent).not.toContain(language === 'tr' ? 'Zamanlamayı etkinleştirin' : 'Enable schedule');
  });

  it.each(['en', 'tr'] as const)('shows scoped partial results and retry while hiding mutations from viewers in %s', async (language) => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    api.projectsResult = { status: 200, body: {
      organization: { id: 7, name: 'Owner organization', role: 'owner' },
      projects: [{ id: 9, name: 'Authorized project', organization_id: 7 }],
    } };
    api.jobDetailResult = { status: 200, body: { job: {
      id: 3, project_id: 9, status: 'partially_succeeded', progress_percent: 100, error_category: '',
      retry_of: null, cancel_requested: false, updated_at: '2026-09-24T10:00:00Z',
      output: { sample_length: 4, partial: true }, steps: [
        { sequence: 1, name: 'Validate input', status: 'succeeded', progress_percent: 50, output: {}, error_category: '' },
        { sequence: 2, name: 'Synthetic observation', status: 'failed', progress_percent: 100, output: {}, error_category: 'synthetic_partial' },
      ], citations: [],
    } } };
    await harness.navigateByUrl('/app/jobs/7/9/3');
    await harness.fixture.whenStable();
    await new Promise((resolve) => setTimeout(resolve));
    harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    expect(root.querySelector('section')!.getAttribute('lang')).toBe(language);
    expect(root.querySelector('h1')!.textContent).toBe(language === 'tr' ? 'Proje işi ilerlemesi' : 'Project job progress');
    expect(root.textContent).toContain('partially succeeded');
    expect(root.textContent).toContain('synthetic_partial');
    expect(root.textContent).toContain(language === 'tr' ? 'Yapılandırılmış tanılama çıktısı' : 'Structured diagnostic output');
    const retry = [...root.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent?.includes(language === 'tr' ? 'Yeni iş olarak yeniden deneyin' : 'Retry as a new job'))!;
    retry.click();
    await harness.fixture.whenStable();
    expect(api.retriedKeys).toHaveLength(1);
    expect(TestBed.inject(Router).url).toBe('/app/jobs/7/9/4');

    await harness.navigateByUrl('/');
    api.projectsResult = { status: 200, body: {
      organization: { id: 7, name: 'Viewer organization', role: 'viewer' },
      projects: [{ id: 9, name: 'Read-only project', organization_id: 7 }],
    } };
    await harness.navigateByUrl('/app/jobs/7/9/3');
    await harness.fixture.whenStable();
    await new Promise((resolve) => setTimeout(resolve));
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain('Read-only project');
    expect(harness.routeNativeElement?.querySelector('#diagnostic-sample')).toBeFalsy();
    expect(harness.routeNativeElement?.textContent).not.toContain(language === 'tr' ? 'Yeni iş olarak yeniden deneyin' : 'Retry as a new job');
  });

  it('rejects array onboarding progress fields in reads and save or conflict replies while preserving scalar states', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const original = structuredClone(api.onboardingResult);
    const configuration = { ...(original.body['configuration'] as Record<string, unknown>),
      target_country: 'Turkey', target_languages: ['en'], business_goal: 'Human goal', source_choice: 'skip', source_state: 'skipped' };
    const current = { ...original, body: { ...original.body, configuration } };
    api.onboardingResult = current;
    const harness = await RouterTestingHarness.create('/app/onboarding/7/9'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    const sourceChoices: Record<string, string> = { not_selected: 'undecided', disconnected: 'connect_search_console',
      awaiting_import: 'import_search_console', skipped: 'skip', synthetic_demo: 'synthetic_demo' };
    const fields = { source_state: Object.keys(sourceChoices), current_step: ['basics', 'source', 'advanced', 'complete'] };
    for (const [field, values] of Object.entries(fields)) {
      for (const value of values) {
        const scalar = { ...configuration, [field]: value,
          source_choice: field === 'source_state' ? sourceChoices[value] : configuration.source_choice };
        api.onboardingResult = { ...current, body: { ...current.body, configuration: { ...scalar, [field]: [value] } } };
        await component.load(); await harness.fixture.whenStable();
        expect(component.configuration()).toBeNull(); expect(component.project()).toBeNull();
        expect(component.error()).toContain('Project onboarding is temporarily unavailable');
        api.onboardingResult = { ...current, body: { ...current.body, configuration: scalar } };
        await component.load(); await harness.fixture.whenStable();
        expect(component.configuration()[field]).toBe(value); expect(component.error()).toBe('');
        const retained = component.configuration();
        for (const status of [200, 409]) {
          api.onboardingHandler = () => Promise.resolve({ status, body: { configuration: { ...scalar, revision: 2, [field]: [value] } } });
          expect(await component.save({ target_country: 'Human edit' }, 'Saved')).toBe(false);
          expect(component.configuration()).toBe(retained); expect(component.message()).toBe('');
          expect(component.error()).toContain('Project setup could not be saved');
        }
      }
    }
    expect(api.onboardingUpdates).toHaveLength(18); api.onboardingHandler = undefined;
  });

  it('rejects foreign project or changed-origin saved onboarding configurations before success and conflict publication', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const original = api.onboardingResult.body['configuration'] as Record<string, unknown>;
    const harness = await RouterTestingHarness.create('/app/onboarding/7/9'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    const retained = component.configuration();
    for (const status of [200, 409]) {
      for (const mismatch of [{ project_id: 10 }, { canonical_origin: 'https://different.example' }]) {
        api.onboardingHandler = () => Promise.resolve({ status, body: { configuration: {
          ...original, ...mismatch, revision: 2, target_country: 'Foreign saved market' } } });
        expect(await component.save({ target_country: 'Human market' }, 'Saved')).toBe(false);
        expect(component.configuration()).toBe(retained); expect(component.message()).toBe('');
        expect(component.error()).toContain('Project setup could not be saved');
      }
    }
    api.onboardingHandler = () => Promise.resolve({ status: 200, body: { configuration: {
      ...original, revision: 1, target_country: 'Current saved market' } } });
    expect(await component.save({ target_country: 'Current saved market' }, 'Saved')).toBe(true);
    expect(component.configuration().project_id).toBe(9); expect(component.configuration().revision).toBe(1);
    api.onboardingHandler = () => Promise.resolve({ status: 409, body: { configuration: {
      ...original, revision: 2, target_country: 'Current latest market' } } });
    expect(await component.save({ target_country: 'Stale market' }, 'Saved')).toBe(false);
    expect(component.configuration().project_id).toBe(9); expect(component.configuration().revision).toBe(2);
    expect(component.error()).toContain('changed in another session'); expect(component.message()).toBe('');
    expect(api.onboardingUpdates).toHaveLength(6); api.onboardingHandler = undefined;
  });

  it.each(['en', 'tr'] as const)('saves and resumes named onboarding steps without starting live work (%s)', async (language) => {
    (TestBed.inject(AccountApi) as unknown as AccountApiStub).savedProductLanguage = language;
    const harness = await RouterTestingHarness.create('/app/onboarding/7/9');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Proje başlangıç kurulumu — OrganicSEOOps' : 'Project onboarding — OrganicSEOOps');
    const root = harness.routeNativeElement!;
    expect(root.querySelector('header')?.getAttribute('lang')).toBe(language);
    expect(root.querySelector('#basics-title')?.parentElement?.parentElement?.getAttribute('lang')).toBe(language);
    expect(root.querySelector('.workspace-shell')?.getAttribute('lang')).toBe('en');
    expect(root.querySelector('#existing-sources-title')?.textContent).toBe(language === 'tr' ? 'Mevcut kaynak durumu' : 'Existing source status');
    expect(root.querySelector('#existing-sources-title')?.closest('[lang]')?.getAttribute('lang')).toBe(language);
    expect(root.textContent).toContain(language === 'tr' ? 'Proje dilleri SEO çalışmalarını tanımlar' : 'Project languages describe SEO work');
    if (language === 'tr') expect(root.textContent).toContain('Sağlayıcı değerleri ve kalan rapor arayüzleri İngilizcedir');
    const component = harness.routeDebugElement!.componentInstance as ProjectOnboarding;
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Project onboarding — OrganicSEOOps' : 'Proje başlangıç kurulumu — OrganicSEOOps');
    expect(api.onboardingUpdates).toEqual([]);
    component.productLanguage.set(language); harness.fixture.detectChanges();
    root.querySelector<HTMLInputElement>('#target-country')!.value = 'Türkiye';
    root.querySelector<HTMLTextAreaElement>('#target-languages')!.value = 'tr\nen-US';
    root.querySelector<HTMLTextAreaElement>('#business-goal')!.value = 'Increase qualified bookings';
    root.querySelector<HTMLInputElement>('#project-timezone')!.value = 'Europe/Istanbul';
    root.querySelector<HTMLInputElement>('#target-country')!.form!.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.onboardingUpdates[0]).toEqual(expect.objectContaining({
      revision: 0, target_country: 'Türkiye', target_languages: ['tr', 'en-US'], current_step: 'source',
    }));
    expect(root.textContent).toContain(language === 'tr' ? 'Bir tercihi kaydetmek hesap bağlamaz veya iş başlatmaz' : 'Saving a choice does not connect an account or start a job');
    expect(document.activeElement?.id).toBe('source-title');
    root.querySelector<HTMLInputElement>('input[value="synthetic_demo"]')!.checked = true;
    root.querySelector<HTMLInputElement>('input[value="synthetic_demo"]')!.form!.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.onboardingUpdates[1]).toEqual(expect.objectContaining({ revision: 1, source_choice: 'synthetic_demo', current_step: 'advanced' }));
    expect(root.textContent).toContain(language === 'tr' ? 'Sağlayıcıları, zamanlamaları, ticari kullanım haklarını' : 'They do not activate providers');
    root.querySelector<HTMLTextAreaElement>('#audience')!.value = 'Travelers';
    root.querySelector<HTMLTextAreaElement>('#seed-topics')!.value = 'airport transfer';
    root.querySelector<HTMLTextAreaElement>('#rss-feeds')!.value = 'https://trusted.example/feed.xml';
    root.querySelector<HTMLTextAreaElement>('#measurement-notes')!.value = 'Check consent and conversion events';
    root.querySelector<HTMLTextAreaElement>('#ignored-query-parameters')!.value = 'utm_source';
    root.querySelector<HTMLTextAreaElement>('#pagination-query-parameters')!.value = 'page\nUTM_SOURCE';
    root.querySelector<HTMLTextAreaElement>('#facet-query-parameters')!.value = 'color';
    root.querySelector<HTMLInputElement>('#query-variant-limit')!.value = '4';
    root.querySelector<HTMLTextAreaElement>('#audience')!.form!.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.onboardingUpdates[2]).toEqual(expect.objectContaining({
      revision: 2, audience: 'Travelers', seed_topics: ['airport transfer'], ignored_query_parameters: ['utm_source'],
      pagination_query_parameters: ['page', 'UTM_SOURCE'], facet_query_parameters: ['color'], query_variant_limit: 4,
      measurement_notes: 'Check consent and conversion events', rss_feed_urls: ['https://trusted.example/feed.xml'], current_step: 'complete',
    }));
    expect(root.textContent).toContain(language === 'tr' ? 'İçe aktarma, sağlayıcı bağlantısı, tarama, iş, deneme veya faturalandırma işlemi başlatılmadı' : 'No import, provider connection, crawl, job, trial, or billing operation was started');
    expect(root.textContent).toContain(language === 'tr' ? 'Bu statik önizleme proje kanıtı değildir' : 'This static preview is not project evidence');
    expect(root.querySelector('.demo-panel')?.getAttribute('lang')).toBe(language);
    expect(root.querySelector('.form-status[role="status"]')?.getAttribute('lang')).toBe(language);
  });

  it.each(['en', 'tr'] as const)('loads the latest onboarding revision after a stale save and keeps viewers read-only (%s)', async (language) => {
    (TestBed.inject(AccountApi) as unknown as AccountApiStub).savedProductLanguage = language;
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.onboardingHandler = () => Promise.resolve({ status: 409, body: { configuration: {
      ...(api.onboardingResult.body['configuration'] as object), target_country: 'Current market', revision: 4,
    } } });
    await harness.navigateByUrl('/app/onboarding/7/9');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    let root = harness.routeNativeElement!;
    root.querySelector<HTMLInputElement>('#target-country')!.value = 'Stale market';
    root.querySelector<HTMLTextAreaElement>('#target-languages')!.value = 'en';
    root.querySelector<HTMLTextAreaElement>('#business-goal')!.value = 'Goal';
    root.querySelector<HTMLInputElement>('#target-country')!.form!.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(root.textContent).toContain(language === 'tr' ? 'Bu kurulum başka bir oturumda değiştirildi' : 'changed in another session');
    expect(root.querySelector('.error[role="alert"]')?.getAttribute('lang')).toBe(language);
    expect(root.querySelector<HTMLInputElement>('#target-country')?.value).toBe('Current market');

    await harness.navigateByUrl('/');
    api.onboardingHandler = undefined;
    api.onboardingResult = { status: 200, body: {
      ...api.onboardingResult.body,
      project: { ...(api.onboardingResult.body['project'] as object), role: 'viewer' },
      configuration: { ...(api.onboardingResult.body['configuration'] as object), target_country: 'Türkiye', target_languages: ['tr'], business_goal: 'Read evidence' },
    } };
    await harness.navigateByUrl('/app/onboarding/7/9');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    root = harness.routeNativeElement!;
    expect(root.textContent).toContain(language === 'tr' ? 'Salt okunur yapılandırma' : 'Read-only configuration');
    expect(root.textContent).toContain('Türkiye');
    expect(root.querySelector('form')).toBeFalsy();
  });

  it('keeps onboarding English on invalid or unavailable preference and suppresses drafts in production', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.sourcesHandler = (_org, projectId) => Promise.resolve({ status: 200, body: { project_id: projectId, has_more: false,
      sources: [{ id: 8, provider: 'google_search_console', property: 'https://onboarding.example', state: 'active',
        scope_current: true, csv_import_supported: true, oauth_available: true, api_sync_available: true,
        coverage_available: true, credential_status: 'reference_reserved', sync: null, latest_import: null }] } });
    const preference = vi.spyOn(api, 'productLanguage');
    const harness = await RouterTestingHarness.create();
    const buildEnvironment = environment as { production: boolean };
    const production = buildEnvironment.production;
    try {
      for (const mode of ['unavailable', 'invalid', 'production'] as const) {
        buildEnvironment.production = mode === 'production';
        if (mode === 'unavailable') preference.mockRejectedValue(new Error('private preference error'));
        else preference.mockResolvedValue({ status: 200, body: { language: mode === 'invalid' ? 'de' : 'tr',
          current_ui_language: 'en', current_email_language: 'en' } });
        await harness.navigateByUrl('/app/onboarding/7/9');
        await harness.fixture.whenStable(); harness.fixture.detectChanges();
        expect(TestBed.inject(Title).getTitle()).toBe('Project onboarding — OrganicSEOOps');
        const root = harness.routeNativeElement!;
        expect(root.querySelector('header')?.getAttribute('lang')).toBe('en');
        expect(root.querySelector('h1')?.textContent).toBe('Resumable project onboarding');
        expect(root.querySelector('#basics-title')?.textContent).toBe('Website and primary goal');
        expect(root.querySelector('#existing-sources-title')?.textContent).toBe('Existing source status');
        expect(root.querySelector('#existing-sources-title')?.closest('[lang]')?.getAttribute('lang')).toBe('en');
        expect(root.textContent).not.toContain('incelenmemiş Türkçe kurulum');
        expect(root.textContent).not.toContain('private preference error');
        expect(root.querySelector('#target-country')).toBeTruthy();
        for (const id of ['sync-day-8', 'backfill-start-8', 'schedule-grain-8', 'coverage-url-8']) {
          expect(root.querySelector('#' + id)?.closest('form')?.getAttribute('lang')).toBe('en');
        }
        expect(root.textContent).toContain('Finalized Search Console date (Pacific Time)');
        expect(root.textContent).toContain('Inspect URL and submitted sitemaps');
        const form = root.querySelector<HTMLFormElement>('#sync-day-8')!.closest('form')!;
        form.querySelector<HTMLInputElement>('input[name="day"]')!.value = '2026-09-20';
        form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
        await harness.fixture.whenStable(); harness.fixture.detectChanges();
        expect(TestBed.inject(Title).getTitle()).toBe('Project onboarding — OrganicSEOOps');
        expect(root.querySelector('.form-status[role="status"]')?.getAttribute('lang')).toBe('en');
        expect(root.querySelector('.form-status[role="status"]')?.textContent).toContain('Search Console job 51 queued');
        await harness.navigateByUrl('/');
      }
    } finally { buildEnvironment.production = production; }
  });

  it.each(['en', 'tr'] as const)('shows exact Google site choices, revokes grants, and ignores a late grant list from another project (%s)', async (language) => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    api.googleGrantRows = [{ id: 12, state: 'pending_selection', revision: 0, verified_at: '2026-09-26T00:00:00Z',
      sites: [{ property: 'https://onboarding.example', site_url: 'https://onboarding.example/' }] }];
    await harness.navigateByUrl('/app/onboarding/7/9');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    expect(root.textContent).toContain(language === 'tr' ? 'bir web sitesi mülkü seçin' : 'Choose a website property');
    const panel = root.querySelector('section[aria-labelledby="google-consent-title"]')!;
    expect(panel.getAttribute('lang')).toBe(language);
    expect([...panel.querySelectorAll('span[lang="en"]')].map(item => item.textContent)).toEqual(expect.arrayContaining(['pending_selection', 'https://onboarding.example']));
    const button = (label: string) => Array.from(root.querySelectorAll('button')).find((item) => item.textContent?.includes(label))!;
    button(language === 'tr' ? 'Kullan https://onboarding.example' : 'Use https://onboarding.example').click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.selectedGoogleSites).toEqual(['https://onboarding.example/']);
    expect(root.textContent).toContain(language === 'tr' ? 'Mülk yetkilendirmesi kaydedildi' : 'Property authorization recorded');
    expect(root.querySelector('.form-status[role="status"]')?.getAttribute('lang')).toBe(language);
    expect(root.querySelector('.form-status[role="status"]')?.textContent).toContain(language === 'tr' ? 'API eşitlemesini başlatmadan önce kaynak durumunu kontrol edin' : 'Check source status before starting API sync');
    button(language === 'tr' ? 'Google yetkilendirmesini iptal et 12' : 'Revoke Google authorization 12').click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.revokedGoogleGrants).toEqual([12]);
    expect(root.textContent).toContain(language === 'tr' ? 'Yetkilendirme iptal edildi' : 'Authorization revoked');

    const component = harness.routeDebugElement!.componentInstance;
    await component.connectGoogle(); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(root.querySelector('.form-status[role="alert"]')?.getAttribute('lang')).toBe(language);
    expect(root.querySelector('.form-status[role="alert"]')?.textContent).toContain(language === 'tr' ? 'Google yetkilendirmesi kullanılamıyor' : 'Google authorization is unavailable');
    const configuration = api.onboardingResult.body['configuration'] as Record<string, unknown>;
    const project = api.onboardingResult.body['project'] as Record<string, unknown>;
    api.onboardingLoadHandler = (_organizationId, projectId) => Promise.resolve({ status: 200, body: {
      project: { ...project, id: projectId }, configuration: { ...configuration, project_id: projectId },
    } });
    let resolveOld!: (value: ApiResult) => void;
    api.googleGrantsHandler = (_org, projectId) => projectId === 9
      ? new Promise((resolve) => { resolveOld = resolve; })
      : Promise.resolve({ status: 200, body: { project_id: projectId, has_more: false, grants: [] } });
    await harness.navigateByUrl('/app/onboarding/7/10');
    await harness.fixture.whenStable();
    await harness.navigateByUrl('/app/onboarding/7/9');
    await new Promise((resolve) => setTimeout(resolve));
    await harness.navigateByUrl('/app/onboarding/7/10');
    await harness.fixture.whenStable();
    resolveOld({ status: 200, body: { project_id: 9, has_more: false, grants: [{ id: 99, state: 'active', revision: 1,
      verified_at: '2026-09-26T00:00:00Z', sites: [{ property: 'https://private.example', site_url: 'https://private.example/' }] }] } });
    await new Promise((resolve) => setTimeout(resolve));
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).not.toContain('private.example');
  });

  it('rejects array source states scope kinds credential statuses and API dimension entries', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = 'tr';
    const original = { id: 8, provider: 'google_search_console', property: 'https://onboarding.example',
      state: 'active', scope_current: true, scope_kind: 'exact_origin_url_prefix', approved_origins: [],
      available_api_dimensions: ['query'], csv_import_supported: true, oauth_available: true, api_sync_available: true,
      credential_status: 'reference_reserved', sync: null, latest_import: null };
    let source: Record<string, unknown> = original;
    api.sourcesHandler = (_org, projectId) => Promise.resolve({ status: 200, body: { project_id: projectId, has_more: false, sources: [source] } });
    const harness = await RouterTestingHarness.create('/app/onboarding/7/9'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    expect(component.sourceError()).toBe(false); expect(component.sources()).toHaveLength(1);
    const changes = [
      ...['active', 'disconnected', 'unavailable'].map(state => ({ state: [state] })),
      ...['exact_origin_url_prefix', 'verified_domain_page_only', 'ga4_hostname_only'].map(scope_kind => ({ scope_kind: [scope_kind] })),
      ...['query', 'date', 'page'].map(dimension => ({ available_api_dimensions: [[dimension]] })),
      ...['not_connected', 'reference_reserved'].map(credential_status => ({ credential_status: [credential_status] })),
    ];
    for (const change of changes) {
      source = { ...original, ...change }; await component.load(); await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(component.sourceError()).toBe(true); expect(component.sources()).toEqual([]);
      expect(harness.routeNativeElement?.querySelector('section[aria-labelledby="existing-sources-title"] input[name="day"]')).toBeNull();
      source = original; await component.load(); await harness.fixture.whenStable();
      expect(component.sourceError()).toBe(false); expect(component.sources()).toHaveLength(1);
    }
    const { scope_kind: _scope, available_api_dimensions: _dimensions, ...legacy } = original;
    source = legacy; await component.load(); await harness.fixture.whenStable(); expect(component.sources()).toHaveLength(1);
    const available = component.sources(), requests = vi.spyOn(api, 'projectSources');
    await component.loadSources(component.generation - 1, 7, 9);
    expect(requests).not.toHaveBeenCalled(); expect(component.sources()).toBe(available);
    let finish!: (value: ApiResult) => void;
    api.sourcesHandler = () => new Promise(resolve => { finish = resolve; });
    component.sourcesTruncated.set(true);
    const pending = component.loadSources(component.generation, 7, 9);
    expect(component.sources()).toEqual([]); expect(component.sourcesTruncated()).toBe(false);
    harness.detectChanges(); expect(harness.routeNativeElement?.textContent).toContain('Mevcut kaynak durumu yükleniyor');
    finish({ status: 403, body: {} }); await pending;
    expect(component.sources()).toEqual([]); expect(component.sourceError()).toBe(true); expect(requests.mock.calls).toHaveLength(1); requests.mockRestore();
    harness.detectChanges(); expect(harness.routeNativeElement?.textContent).toContain('bu, içe aktarma olmadığı anlamına gelmez');
    api.sourcesHandler = () => Promise.resolve({ status: 200, body: { project_id: 9, sources: [], has_more: false } });
    await component.loadSources(component.generation, 7, 9); harness.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain('Bu proje için kaynak bağlantısı kaydedilmedi');
    expect(api.syncRequests).toEqual([]);
  });

  it('rejects array Google grant states and optional site scopes without exposing selection controls', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const site = { property: 'https://onboarding.example', site_url: 'https://onboarding.example/', scope: 'exact_origin_url_prefix' };
    const original = { id: 12, state: 'pending_selection', revision: 0, verified_at: '2026-09-26T00:00:00Z', sites: [site] };
    api.googleGrantRows = [original];
    const harness = await RouterTestingHarness.create('/app/onboarding/7/9'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    expect(component.grantError()).toBe(false); expect(component.grants()).toHaveLength(1);
    const changes = [
      ...['pending_selection', 'active', 'reconnect_required', 'revocation_pending', 'revoked'].map(state => ({ state: [state] })),
      ...['exact_origin_url_prefix', 'verified_domain_page_only'].map(scope => ({ sites: [{ ...site, scope: [scope] }] })),
    ];
    for (const change of changes) {
      api.googleGrantRows = [{ ...original, ...change }]; await component.load(); await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(component.grantError()).toBe(true); expect(component.grants()).toEqual([]);
      expect(harness.routeNativeElement?.textContent).not.toContain('Use https://onboarding.example');
      api.googleGrantRows = [original]; await component.load(); await harness.fixture.whenStable();
      expect(component.grantError()).toBe(false); expect(component.grants()).toHaveLength(1);
    }
    const { scope: _scope, ...legacy } = site;
    api.googleGrantRows = [{ ...original, sites: [legacy] }]; await component.load(); await harness.fixture.whenStable(); expect(component.grants()).toHaveLength(1);
    const available = component.grants(), requests = vi.spyOn(api, 'googleOAuthGrants');
    await component.loadGrants(component.generation - 1, 7, 9);
    expect(requests).not.toHaveBeenCalled(); expect(component.grants()).toBe(available);
    let finish!: (value: ApiResult) => void;
    api.googleGrantsHandler = () => new Promise(resolve => { finish = resolve; });
    component.grantsTruncated.set(true);
    const pending = component.loadGrants(component.generation, 7, 9);
    expect(component.grants()).toEqual([]); expect(component.grantsTruncated()).toBe(false);
    finish({ status: 403, body: {} }); await pending;
    expect(component.grants()).toEqual([]); expect(component.grantError()).toBe(true); expect(requests.mock.calls).toHaveLength(1); requests.mockRestore();
    expect(api.selectedGoogleSites).toEqual([]); expect(api.revokedGoogleGrants).toEqual([]);
  });

  it('rejects array sync states and mismatched acknowledgments and clears current pending sync authority', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.sourcesHandler = (_org, projectId) => Promise.resolve({ status: 200, body: { project_id: projectId, has_more: false,
      sources: [{ id: 8, provider: 'google_search_console', property: 'https://onboarding.example', state: 'active',
        scope_current: true, csv_import_supported: true, oauth_available: true, api_sync_available: true,
        credential_status: 'reference_reserved', sync: null, latest_import: null }] } });
    const job = { id: 51, status: 'queued', error_category: '', pages_recorded: 0,
      requests_attempted: 0, source_coverage: 'unavailable' };
    const response = { status: 200, body: { project_id: 9, connection_id: 8, job } };
    const harness = await RouterTestingHarness.create('/app/onboarding/7/9'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    for (const status of ['queued', 'running', 'succeeded', 'failed', 'cancelled', 'partially_succeeded']) {
      api.syncStatusHandler = () => Promise.resolve({ ...response, body: { ...response.body, job: { ...job, status: [status] } } });
      await component.refreshSync(8); expect(component.syncError()).toBe(true); expect(component.syncJob()).toBeNull();
      api.syncStatusHandler = () => Promise.resolve({ ...response, body: { ...response.body, job: { ...job, status } } });
      await component.refreshSync(8); await harness.fixture.whenStable();
      expect(component.syncError()).toBe(false); expect(component.syncJob().status).toBe(status);
    }
    api.syncStatusHandler = () => Promise.resolve(response); await component.refreshSync(8); await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const form = harness.routeNativeElement!.querySelector<HTMLInputElement>('input[name="day"]')!.closest('form')!;
    form.querySelector<HTMLInputElement>('input[name="day"]')!.value = '2026-09-20';
    const start = vi.spyOn(api, 'startSearchConsoleSync');
    for (const jobId of ['51', [51]]) {
      start.mockResolvedValue({ status: 202, body: { project_id: 9, job_id: jobId, status: 'queued', max_requests: 3, source_coverage: 'top_rows_only' } });
      form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
      await harness.fixture.whenStable();
      expect(component.error()).toContain('Sync could not start'); expect(component.message()).toBe('');
    }
    expect(start).toHaveBeenCalledTimes(2);
    expect(start.mock.calls[0][5]).toBeTruthy(); expect(start.mock.calls[0][5]).toBe(start.mock.calls[1][5]); start.mockRestore();
    const cancel = vi.spyOn(api, 'cancelSearchConsoleSync').mockResolvedValue({ status: 200,
      body: { ...response.body, job: { ...job, id: 52, status: 'cancelled' } } });
    await component.cancelSync(8, 51);
    expect(component.error()).toContain('Sync cancellation could not be confirmed'); expect(component.syncJob().id).toBe(51);
    expect(component.message()).not.toContain('Sync cancelled'); expect(cancel).toHaveBeenCalledTimes(1);
    cancel.mockRestore(); await component.cancelSync(8, 51); expect(component.syncJob().status).toBe('cancelled');
    let finish!: (value: ApiResult) => void;
    api.syncStatusHandler = () => new Promise(resolve => { finish = resolve; });
    const pending = component.refreshSync(8); expect(component.syncJob()).toBeNull();
    const staleCancel = vi.spyOn(api, 'cancelSearchConsoleSync');
    await component.cancelSync(8, 51); expect(staleCancel).not.toHaveBeenCalled();
    finish({ status: 403, body: {} }); await pending;
    expect(component.syncJob()).toBeNull(); expect(component.syncError()).toBe(true); staleCancel.mockRestore();
    expect(api.syncRequests).toEqual([]);
  });

  it.each(['en', 'tr'] as const)('bounds one property sync, shows scoped job status and cancels without exposing source rows (%s)', async (language) => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    api.sourcesHandler = (_org, projectId) => Promise.resolve({ status: 200, body: {
      project_id: projectId, has_more: false, sources: [{ id: 8, provider: 'google_search_console',
        property: 'https://onboarding.example', state: 'active', scope_current: true,
        csv_import_supported: true, oauth_available: true, api_sync_available: true,
        credential_status: 'reference_reserved', sync: { status: 'succeeded', quota_state: 'available', coverage_start: null, coverage_end: '2026-09-20', fresh_through: null, error_category: '', retry_after: null }, latest_import: null }],
    } });
    await harness.navigateByUrl('/app/onboarding/7/9');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    expect(root.textContent).toContain(language === 'tr' ? 'bildirilmeyen sorgular ve sayfalar bilinmiyor' : 'unreported queries and pages remain unknown');
    const record = [...root.querySelectorAll('p')].find(item => item.textContent?.includes(language === 'tr' ? 'Eşitleme kaydı:' : 'Sync record:'))!;
    expect(record.getAttribute('lang')).toBe(language);
    expect(record.textContent).toContain(language === 'tr' ? 'bilinmiyor' : 'unknown');
    expect([...record.querySelectorAll('span[lang="en"]')].map(item => item.textContent)).toEqual(['succeeded', 'available']);
    const form = root.querySelector<HTMLFormElement>('input[name="day"]')!.closest('form')!;
    expect(form.getAttribute('lang')).toBe(language);
    expect(form.textContent).toContain(language === 'tr' ? 'Kesinleşmiş Search Console tarihi (Pasifik Saati)' : 'Finalized Search Console date (Pacific Time)');
    expect(Array.from(form.querySelectorAll('option')).map(item => item.value)).toEqual(['query', 'page', 'date']);
    form.querySelector<HTMLInputElement>('input[name="day"]')!.value = '2026-09-20';
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.syncRequests).toHaveLength(1);
    expect(api.syncRequests[0]).toEqual(expect.objectContaining({ connectionId: 8, day: '2026-09-20', dimensions: ['query'] }));
    expect(root.textContent).toContain(language === 'tr' ? 'İş 51: queued' : 'Job 51: queued');
    expect(root.textContent).toContain(language === 'tr' ? '0 sayfa kaydedildi; 0 istek denemesi yapıldı; kaynak kapsamı' : '0 pages recorded from 0 attempts; source coverage');
    expect(root.textContent).toContain(language === 'tr' ? 'Google yalnızca üst sıralı satırları sağlar' : 'Google supplies top rows only');
    expect([...root.querySelectorAll('[role="status"] span[lang="en"]')].map(item => item.textContent)).toContain('queued');
    const cancel = Array.from(root.querySelectorAll('button')).find((item) => item.textContent?.includes(language === 'tr' ? 'Bu eşitlemeyi iptal et' : 'Cancel this sync'))!;
    expect(root.querySelector('.form-status[role="status"]')?.getAttribute('lang')).toBe(language);
    expect(root.querySelector('.form-status[role="status"]')?.textContent).toContain(language === 'tr' ? 'Search Console işi 51 kuyruğa alındı' : 'Search Console job 51 queued');
    cancel.click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(root.textContent).toContain(language === 'tr' ? 'İş 51: cancelled' : 'Job 51: cancelled');
    expect(root.querySelector('.form-status[role="status"]')?.getAttribute('lang')).toBe(language);
  });

  it.each(['en', 'tr'] as const)('labels domain-wide Google properties as verified-origin page-only choices (%s)', async (language) => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    api.googleGrantRows = [{ id: 23, state: 'pending_selection', revision: 0,
      verified_at: '2026-09-27T00:00:00Z', sites: [{ property: 'sc-domain:onboarding.example',
        site_url: 'sc-domain:onboarding.example', scope: 'verified_domain_page_only',
        approved_origins: ['https://onboarding.example'], available_dimensions: ['page'] }] }];
    api.sourcesHandler = (_org, projectId) => Promise.resolve({ status: 200, body: {
      project_id: projectId, has_more: false, sources: [{ id: 31, provider: 'google_search_console',
        property: 'sc-domain:onboarding.example', state: 'active', scope_current: true,
        scope_kind: 'verified_domain_page_only', approved_origins: ['https://onboarding.example'],
        available_api_dimensions: ['page'], csv_import_supported: false,
        oauth_available: true, api_sync_available: true, credential_status: 'reference_reserved',
        sync: null, latest_import: null }],
    } });
    await harness.navigateByUrl('/app/onboarding/7/9');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    expect(root.textContent).toContain(language === 'tr' ? 'Alan adı genelindeki sorgu, tarih ve mülk toplamları kullanılamıyor' : 'Domain-wide query, date and property totals are unavailable');
    expect(root.textContent).toContain(language === 'tr' ? 'Yalnızca doğrulanmış proje kaynak adreslerinin sayfa satırları' : 'Only page rows for verified project origins');
    const form = root.querySelector<HTMLFormElement>('input[name="day"]')!.closest('form')!;
    const choices = Array.from(form.querySelectorAll<HTMLOptionElement>('select[name="dimension"] option'));
    expect(choices.map((option) => option.value)).toEqual(['page']);
    expect(form.closest('[lang]')?.getAttribute('lang')).toBe(language);
    expect(choices[0].textContent).toContain(language === 'tr' ? 'Yalnızca doğrulanmış kaynak adreslerindeki sayfalar' : 'Verified-origin pages only');
    expect(form.textContent).toContain(language === 'tr' ? 'iki API isteği' : 'two API requests');
    form.querySelector<HTMLInputElement>('input[name="day"]')!.value = '2026-09-20';
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    expect(api.syncRequests[0].dimensions).toEqual(['page']);
  });

  it('rejects array indexed-version coverage statuses and source labels and clears current pending coverage', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.sourcesHandler = (_org, projectId) => Promise.resolve({ status: 200, body: { project_id: projectId, has_more: false,
      sources: [{ id: 31, provider: 'google_search_console', property: 'sc-domain:onboarding.example', state: 'active',
        scope_current: true, scope_kind: 'verified_domain_page_only', approved_origins: ['https://onboarding.example'],
        available_api_dimensions: ['page'], csv_import_supported: false, oauth_available: true, api_sync_available: true,
        coverage_available: true, credential_status: 'reference_reserved', sync: null, latest_import: null }] } });
    const results: Record<string, Record<string, unknown>> = {
      inspection: { inspection_url: 'https://onboarding.example/page', method: 'google_indexed_version_only', verdict: 'PASS',
        indexed_state: 'reported_indexed', robots_state: 'unknown', indexing_state: 'unknown', page_fetch_state: 'unknown',
        last_crawl_at: null, google_canonical: null, declared_canonical: null, coverage: 'one_google_indexed_version_not_live_test' },
      sitemaps: { sitemaps: [], coverage: 'submitted_sitemaps_for_verified_origins_only', provider_total: null,
        omitted_other_origins: null, indexed_url_counts: null, list_truncated: null },
    };
    const job = { id: 66, status: 'partially_succeeded', error_category: 'quota_limited',
      inspection_url: 'https://onboarding.example/page', requests_attempted: 3,
      sources_recorded: ['sitemaps'], results: [{ source: 'sitemaps', result: results['sitemaps'] }] };
    const response = { status: 200, body: { project_id: 9, connection_id: 31, job } };
    const harness = await RouterTestingHarness.create('/app/onboarding/7/9'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    api.coverageStatusHandler = () => Promise.resolve(response); await component.refreshCoverage(31); await harness.fixture.whenStable();
    for (const status of ['queued', 'running', 'succeeded', 'failed', 'cancelled', 'partially_succeeded']) {
      api.coverageStatusHandler = () => Promise.resolve({ ...response, body: { ...response.body, job: { ...job, status: [status] } } });
      await component.refreshCoverage(31); expect(component.coverageError()).toBe(true); expect(component.coverageJob()).toBeNull();
      api.coverageStatusHandler = () => Promise.resolve({ ...response, body: { ...response.body, job: { ...job, status } } });
      await component.refreshCoverage(31); await harness.fixture.whenStable();
      expect(component.coverageError()).toBe(false); expect(component.coverageJob().status).toBe(status);
    }
    for (const source of ['inspection', 'sitemaps']) {
      const scalar = { ...job, sources_recorded: [source], results: [{ source, result: results[source] }] };
      for (const invalid of [{ ...scalar, sources_recorded: [[source]] },
        { ...scalar, results: [{ source: [source], result: results[source] }] }]) {
        api.coverageStatusHandler = () => Promise.resolve({ ...response, body: { ...response.body, job: invalid } });
        await component.refreshCoverage(31); expect(component.coverageError()).toBe(true); expect(component.coverageJob()).toBeNull();
        api.coverageStatusHandler = () => Promise.resolve({ ...response, body: { ...response.body, job: scalar } });
        await component.refreshCoverage(31); await harness.fixture.whenStable();
        expect(component.coverageError()).toBe(false); expect(component.coverageJob().sources_recorded).toEqual([source]);
      }
    }
    api.coverageStatusHandler = () => Promise.resolve(response); await component.refreshCoverage(31); await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const form = harness.routeNativeElement!.querySelector<HTMLInputElement>('input[name="inspection_url"]')!.closest('form')!;
    form.querySelector<HTMLInputElement>('input[name="inspection_url"]')!.value = 'https://onboarding.example/page';
    const start = vi.spyOn(api, 'startSearchConsoleCoverage').mockResolvedValue({ status: 202, body: {
      ...response.body, job: { ...job, status: ['queued'] }, max_requests: 3 } });
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true })); await harness.fixture.whenStable();
    expect(component.error()).toContain('Coverage request outcome is unknown'); expect(component.message()).toBe('');
    expect(start).toHaveBeenCalledTimes(1); start.mockRestore();
    const cancel = vi.spyOn(api, 'cancelSearchConsoleCoverage').mockResolvedValue({ status: 200,
      body: { ...response.body, job: { ...job, status: ['cancelled'] } } });
    await component.cancelCoverage(31, 66); expect(component.error()).toContain('Cancellation outcome is unknown');
    expect(component.message()).not.toContain('Coverage request cancelled'); expect(cancel).toHaveBeenCalledTimes(1); cancel.mockRestore();
    await component.cancelCoverage(31, 66); expect(component.coverageJob().status).toBe('cancelled');
    let finish!: (value: ApiResult) => void;
    api.coverageStatusHandler = () => new Promise(resolve => { finish = resolve; });
    const pending = component.refreshCoverage(31); expect(component.coverageJob()).toBeNull();
    const staleCancel = vi.spyOn(api, 'cancelSearchConsoleCoverage');
    await component.cancelCoverage(31, 66); expect(staleCancel).not.toHaveBeenCalled();
    finish({ status: 403, body: {} }); await pending; expect(component.coverageError()).toBe(true); expect(component.coverageJob()).toBeNull();
    staleCancel.mockRestore(); expect(api.coverageRequests).toEqual([]);
  });

  it.each(['en', 'tr'] as const)('queues bounded indexed-version coverage and shows only scoped sitemap evidence (%s)', async (language) => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    api.sourcesHandler = (_org, projectId) => Promise.resolve({ status: 200, body: {
      project_id: projectId, has_more: false, sources: [{ id: 31, provider: 'google_search_console',
        property: 'sc-domain:onboarding.example', state: 'active', scope_current: true,
        scope_kind: 'verified_domain_page_only', approved_origins: ['https://onboarding.example'],
        available_api_dimensions: ['page'], csv_import_supported: false, oauth_available: true,
        api_sync_available: true, coverage_available: true, credential_status: 'reference_reserved',
        sync: null, latest_import: null }],
    } });
    await harness.navigateByUrl('/app/onboarding/7/9');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    const form = root.querySelector<HTMLInputElement>('input[name="inspection_url"]')!.closest('form')!;
    expect(form.getAttribute('lang')).toBe(language);
    expect(form.textContent).toContain(language === 'tr' ? 'canlı sayfa testi değildir' : 'not a live-page test');
    expect(form.textContent).toContain(language === 'tr' ? 'Eksik raporlar bilinmiyor' : 'Missing reports are unknown');
    form.querySelector<HTMLInputElement>('input[name="inspection_url"]')!.value = 'https://onboarding.example/page';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.coverageRequests[0]).toEqual(expect.objectContaining({
      connectionId: 31, inspectionUrl: 'https://onboarding.example/page',
    }));
    expect(root.textContent).toContain(language === 'tr' ? 'İnceleme işi 66: queued' : 'Inspection job 66: queued');
    expect(root.querySelector('.form-status[role="status"]')?.getAttribute('lang')).toBe(language);
    expect(root.querySelector('.form-status[role="status"]')?.textContent).toContain(language === 'tr' ? 'Kapsam işi 66 kuyruğa alındı' : 'Coverage job 66 queued');
    expect([...root.querySelectorAll('[role="status"] span[lang="en"]')].map(item => item.textContent)).toContain('queued');
    const cancel = Array.from(root.querySelectorAll('button')).find((button) => button.textContent?.includes(language === 'tr' ? 'Kapsam isteğini iptal et' : 'Cancel coverage request'))!;
    cancel.click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(root.textContent).toContain(language === 'tr' ? 'İnceleme işi 66: cancelled' : 'Inspection job 66: cancelled');
    api.coverageStatusHandler = (projectId, connectionId) => Promise.resolve({ status: 200, body: {
      project_id: projectId, connection_id: connectionId, job: { id: 66, status: 'partially_succeeded',
        error_category: 'quota_limited', inspection_url: 'https://onboarding.example/page',
        requests_attempted: 3, sources_recorded: ['sitemaps'], results: [{ source: 'sitemaps', result: {
          sitemaps: [{ url: 'https://onboarding.example/sitemap.xml' }], provider_total: null,
          indexed_url_counts: null, coverage: 'submitted_sitemaps_for_verified_origins_only',
        } }],
      },
    } });
    await harness.routeDebugElement?.componentInstance.refreshCoverage(31);
    harness.fixture.detectChanges();
    expect(root.textContent).toContain(language === 'tr' ? 'İnceleme işi 66: partially_succeeded' : 'Inspection job 66: partially_succeeded');
    expect(root.textContent).toContain('https://onboarding.example/sitemap.xml');
    expect(root.textContent).toContain(language === 'tr' ? 'toplamlar ve diğer alt alan adlarının' : 'totals and sibling-host');
    expect(root.textContent).not.toContain('m.onboarding.example/secret');
    api.coverageStatusHandler = (projectId, connectionId) => Promise.resolve({ status: 200, body: { project_id: projectId, connection_id: connectionId, job: { id: 66, status: 'succeeded', error_category: '', inspection_url: 'https://onboarding.example/page', requests_attempted: 3, sources_recorded: ['inspection'], results: [{ source: 'inspection', result: { verdict: 'PASS', indexed_state: 'indexed', last_crawl_at: null } }] } } });
    await harness.routeDebugElement!.componentInstance.refreshCoverage(31);
    harness.fixture.detectChanges();
    expect(root.textContent).toContain(language === 'tr' ? 'güncel canlı sayfayı doğrulamaz' : 'does not verify the current live page');
    expect([...root.querySelectorAll('p span[lang="en"]')].map(item => item.textContent)).toEqual(expect.arrayContaining(['PASS', 'indexed', 'unknown']));
  });

  it('rejects array backfill states and dimensions in reads and acknowledgments and clears pending current backfill', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.sourcesHandler = (_org, projectId) => Promise.resolve({ status: 200, body: { project_id: projectId, has_more: false,
      sources: [{ id: 31, provider: 'google_search_console', property: 'sc-domain:onboarding.example', state: 'active',
        scope_current: true, scope_kind: 'verified_domain_page_only', approved_origins: ['https://onboarding.example'],
        available_api_dimensions: ['page'], csv_import_supported: false, oauth_available: true, api_sync_available: true,
        credential_status: 'reference_reserved', sync: null, latest_import: null }] } });
    const original = await api.searchConsoleBackfillStatus(7, 9, 31);
    const batch = original.body['backfill'] as Record<string, unknown>;
    const harness = await RouterTestingHarness.create('/app/onboarding/7/9'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    const read = vi.spyOn(api, 'searchConsoleBackfillStatus');
    for (const [field, values] of Object.entries({ status: ['running', 'paused', 'succeeded'], dimension: ['date', 'query', 'page'] })) {
      for (const value of values) {
        read.mockResolvedValue({ ...original, body: { ...original.body, backfill: { ...batch, [field]: [value] } } });
        await component.refreshBackfill(31); expect(component.backfillError()).toBe(true); expect(component.backfillJob()).toBeNull();
        read.mockResolvedValue({ ...original, body: { ...original.body, backfill: { ...batch, [field]: value } } });
        await component.refreshBackfill(31); expect(component.backfillError()).toBe(false); expect(component.backfillJob()[field]).toBe(value);
      }
    }
    read.mockResolvedValue(original); await component.refreshBackfill(31); harness.fixture.detectChanges();
    const form = harness.routeNativeElement!.querySelector<HTMLInputElement>('#backfill-start-31')!.closest('form')!;
    form.querySelector<HTMLInputElement>('input[name="start_day"]')!.value = '2026-09-16';
    form.querySelector<HTMLInputElement>('input[name="end_day"]')!.value = '2026-09-18';
    const start = vi.spyOn(api, 'startSearchConsoleBackfill').mockResolvedValue({ status: 202,
      body: { ...original.body, backfill: { ...batch, status: ['running'] } } });
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true })); await harness.fixture.whenStable();
    expect(component.error()).toContain('Backfill outcome unknown'); expect(component.message()).toBe('');
    expect(start).toHaveBeenCalledTimes(1); start.mockRestore();
    const stop = vi.spyOn(api, 'cancelSearchConsoleBackfill').mockResolvedValue({ status: 200,
      body: { ...original.body, backfill: { ...batch, dimension: ['page'] } } });
    await component.cancelBackfill(31, 96); expect(component.error()).toContain('Backfill stop outcome unknown');
    expect(component.backfillJob().dimension).toBe('page'); expect(stop).toHaveBeenCalledTimes(1); stop.mockRestore();
    await component.cancelBackfill(31, 96); expect(component.backfillJob().status).toBe('paused');
    let finish!: (value: ApiResult) => void;
    read.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    const pending = component.refreshBackfill(31); expect(component.backfillJob()).toBeNull();
    const staleStop = vi.spyOn(api, 'cancelSearchConsoleBackfill');
    await component.cancelBackfill(31, 96); expect(staleStop).not.toHaveBeenCalled();
    finish({ status: 403, body: {} }); await pending; expect(component.backfillError()).toBe(true); expect(component.backfillJob()).toBeNull();
    staleStop.mockRestore(); read.mockRestore(); expect(api.backfillRequests).toEqual([]);
  });

  it('rejects array daily schedule dimensions and clears pending authority without creating or enabling schedules', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.sourcesHandler = (_org, projectId) => Promise.resolve({ status: 200, body: { project_id: projectId, has_more: false,
      sources: [{ id: 31, provider: 'google_search_console', property: 'sc-domain:onboarding.example', state: 'active',
        scope_current: true, scope_kind: 'verified_domain_page_only', approved_origins: ['https://onboarding.example'],
        available_api_dimensions: ['page'], csv_import_supported: false, oauth_available: true, api_sync_available: true,
        credential_status: 'reference_reserved', sync: null, latest_import: null }] } });
    const original = await api.searchConsoleScheduleStatus(7, 9, 31);
    const schedule = original.body['schedule'] as Record<string, unknown>;
    const harness = await RouterTestingHarness.create('/app/onboarding/7/9'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    const read = vi.spyOn(api, 'searchConsoleScheduleStatus');
    for (const dimension of ['date', 'query', 'page']) {
      read.mockResolvedValue({ ...original, body: { ...original.body, schedule: { ...schedule, dimension: [dimension] } } });
      await component.refreshSchedule(31); expect(component.scheduleError()).toBe(true); expect(component.sourceSchedule()).toBeNull();
      read.mockResolvedValue({ ...original, body: { ...original.body, schedule: { ...schedule, dimension } } });
      await component.refreshSchedule(31); expect(component.scheduleError()).toBe(false); expect(component.sourceSchedule().dimension).toBe(dimension);
    }
    read.mockResolvedValue({ ...original, body: { ...original.body, schedule: null } }); await component.refreshSchedule(31);
    harness.fixture.detectChanges();
    const form = harness.routeNativeElement!.querySelector<HTMLSelectElement>('#schedule-grain-31')!.closest('form')!;
    const create = vi.spyOn(api, 'createSearchConsoleSchedule').mockResolvedValue({ status: 201,
      body: { ...original.body, schedule: { ...schedule, dimension: ['page'] } } });
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true })); await harness.fixture.whenStable();
    expect(component.error()).toContain('Schedule outcome unknown'); expect(component.message()).toBe(''); expect(component.sourceSchedule()).toBeNull();
    expect(create).toHaveBeenCalledTimes(1);
    read.mockResolvedValue(original); await component.refreshSchedule(31);
    const toggle = vi.spyOn(api, 'toggleSearchConsoleSchedule').mockResolvedValue({ status: 200,
      body: { ...original.body, schedule: { ...schedule, enabled: true, dimension: ['page'], next_run_at: '2026-09-29T00:00:00Z' } } });
    await component.toggleSchedule(31, 27, true); expect(component.error()).toContain('Daily schedule change could not be confirmed');
    expect(component.sourceSchedule().enabled).toBe(false); expect(toggle).toHaveBeenCalledTimes(1);
    toggle.mockRestore(); await component.toggleSchedule(31, 27, true); expect(component.sourceSchedule().enabled).toBe(true);
    let finish!: (value: ApiResult) => void;
    read.mockImplementation(() => new Promise(resolve => { finish = resolve; })); read.mockClear();
    const pending = component.refreshSchedule(31); expect(component.sourceSchedule()).toBeNull(); expect(component.scheduleBusy()).toBe(31);
    await component.refreshSchedule(31); expect(read).toHaveBeenCalledTimes(1);
    const staleToggle = vi.spyOn(api, 'toggleSearchConsoleSchedule');
    await component.toggleSchedule(31, 27, false); expect(staleToggle).not.toHaveBeenCalled();
    create.mockClear(); harness.fixture.detectChanges();
    const pendingForm = harness.routeNativeElement!.querySelector<HTMLSelectElement>('#schedule-grain-31')!.closest('form')!;
    expect(pendingForm.querySelector<HTMLButtonElement>('button[type="submit"]')!.disabled).toBe(true);
    pendingForm.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true })); await Promise.resolve(); expect(create).not.toHaveBeenCalled();
    finish({ status: 403, body: {} }); await pending;
    expect(component.scheduleError()).toBe(true); expect(component.sourceSchedule()).toBeNull(); expect(component.scheduleBusy()).toBeNull();
    staleToggle.mockRestore(); create.mockRestore(); read.mockRestore(); expect(api.scheduleRequests).toEqual([]);
  });

  it.each(['en', 'tr'] as const)('starts a bounded page-only domain backfill and shows paused partial status (%s)', async (language) => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    api.sourcesHandler = (_org, projectId) => Promise.resolve({ status: 200, body: {
      project_id: projectId, has_more: false, sources: [{ id: 31, provider: 'google_search_console',
        property: 'sc-domain:onboarding.example', state: 'active', scope_current: true,
        scope_kind: 'verified_domain_page_only', approved_origins: ['https://onboarding.example'],
        available_api_dimensions: ['page'], csv_import_supported: false, oauth_available: true,
        api_sync_available: true, credential_status: 'reference_reserved', sync: null, latest_import: null }],
    } });
    await harness.navigateByUrl('/app/onboarding/7/9');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    const form = root.querySelector<HTMLFormElement>('#backfill-start-31')!.closest('form')!;
    expect(form.getAttribute('lang')).toBe(language);
    expect(form.textContent).toContain(language === 'tr' ? 'yedi gün için' : 'for seven days');
    expect(form.textContent).toContain(language === 'tr' ? 'eksik sayfalar bilinmiyor' : 'missing pages are unknown');
    expect(Array.from(form.querySelectorAll<HTMLOptionElement>('select option')).map((option) => option.value)).toEqual(['page']);
    form.querySelector<HTMLInputElement>('input[name="start_day"]')!.value = '2026-09-16';
    form.querySelector<HTMLInputElement>('input[name="end_day"]')!.value = '2026-09-18';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.backfillRequests[0]).toEqual(expect.objectContaining({ connectionId: 31,
      startDay: '2026-09-16', endDay: '2026-09-18', dimension: 'page' }));
    expect(root.textContent).toContain(language === 'tr' ? 'Geçmiş veri 96: running' : 'Backfill 96: running');
    await harness.routeDebugElement!.componentInstance.refreshBackfill(31);
    harness.fixture.detectChanges();
    expect(root.textContent).toContain(language === 'tr' ? 'Geçmiş veri 96: paused' : 'Backfill 96: paused');
    expect(root.textContent).toContain('quota_limited');
    expect(root.textContent).toContain(language === 'tr' ? 'Önceki günler ayrı gözlemler olarak kalır' : 'Earlier days remain separate observations');
  });

  it.each(['en', 'tr'] as const)('keeps a domain daily schedule paused until explicitly enabled (%s)', async (language) => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    api.sourcesHandler = (_org, projectId) => Promise.resolve({ status: 200, body: {
      project_id: projectId, has_more: false, sources: [{ id: 31, provider: 'google_search_console',
        property: 'sc-domain:onboarding.example', state: 'active', scope_current: true,
        scope_kind: 'verified_domain_page_only', approved_origins: ['https://onboarding.example'],
        available_api_dimensions: ['page'], csv_import_supported: false, oauth_available: true,
        api_sync_available: true, credential_status: 'reference_reserved', sync: null, latest_import: null }],
    } });
    await harness.navigateByUrl('/app/onboarding/7/9');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    const form = root.querySelector<HTMLFormElement>('#schedule-grain-31')!.closest('form')!;
    expect(form.getAttribute('lang')).toBe(language);
    expect(form.textContent).toContain(language === 'tr' ? 'Kaçırılan günler yeniden işlenmez' : 'Missed days are not replayed');
    expect(Array.from(form.querySelectorAll<HTMLOptionElement>('option')).map((option) => option.value)).toEqual(['page']);
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.scheduleRequests[0]).toEqual(expect.objectContaining({ connectionId: 31, dimension: 'page' }));
    expect(root.textContent).toContain(language === 'tr' ? 'Günlük page rapor: duraklatıldı' : 'Daily page report: paused');
    expect(root.querySelector('.form-status[role="status"]')?.getAttribute('lang')).toBe(language);
    expect([...root.querySelectorAll('[role="status"] span[lang="en"]')].map(item => item.textContent)).toContain('page');
    const enable = Array.from(root.querySelectorAll('button')).find((item) => item.textContent?.includes(language === 'tr' ? 'Etkinleştir günlük raporları' : 'Enable daily reports'))!;
    enable.click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(root.textContent).toContain(language === 'tr' ? 'Günlük page rapor: etkin' : 'Daily page report: enabled');
  });

  it.each(['en', 'tr'] as const)('shows crawl indexation unknown until an authorized no-fetch evidence build (%s)', async (language) => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    await harness.navigateByUrl('/app/onboarding/7/9');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    const panel = root.querySelector('section[aria-labelledby="indexation-title"]')!;
    expect(panel.getAttribute('lang')).toBe(language);
    expect(panel.textContent).toContain(language === 'tr' ? 'canlı sayfa testi değildir' : 'not a live-page test');
    expect(root.textContent).toContain(language === 'tr' ? 'Tarama ve arama motoru dizinleme kanıtları' : 'Crawl and search-engine indexation evidence');
    Array.from(root.querySelectorAll('button')).find((item) => item.textContent?.includes(language === 'tr' ? 'Dizinleme kanıtlarını yükle' : 'Load indexation evidence'))!.click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(root.textContent).toContain(language === 'tr' ? 'Seçilen çalışma için değişmez tarama kanıtı oluşturulmadı' : 'No immutable crawl evidence has been built');
    expect(api.indexationBuilt).toBe(false);
    Array.from(root.querySelectorAll('button')).find((item) => item.textContent?.includes(language === 'tr' ? 'Bu tarama için sayfa almadan kanıt oluştur' : 'Build no-fetch evidence'))!.click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.indexationBuilt).toBe(true);
    expect(root.textContent).toContain(language === 'tr' ? 'Arama motorundaki dizin durumu bilinmiyor' : 'Search-engine indexed status unknown');
    expect(root.textContent).not.toContain('reported_indexed');
    Array.from(root.querySelectorAll('button')).find((item) => item.textContent?.includes(language === 'tr' ? 'Kapsam içindeki dizinleme inceleme adaylarını kaydet' : 'Record scoped indexation review candidates'))!.click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(root.textContent).toContain('sitemap_http_or_noindex_candidate');
    expect(root.textContent).toContain(language === 'tr' ? 'tarama kanıtı 51' : 'crawl evidence 51');
    expect(root.querySelector('.form-status[role="status"]')?.getAttribute('lang')).toBe(language);
    expect(root.querySelector('.form-status[role="status"]')?.textContent).toContain(language === 'tr' ? '1 kapsam içi dizinleme adayı' : '1 scoped indexation candidates');
    expect(root.querySelector('.form-status[role="status"]')?.textContent).toContain(language === 'tr' ? 'Hiçbiri onaylanmış aksiyon değildir' : 'None are approved actions');
    const originalTechnical = api.recordTechnicalFindings.bind(api);
    vi.spyOn(api, 'recordTechnicalFindings').mockImplementation(async (...args) => {
      const result = await originalTechnical(...args); return { ...result, body: { ...result.body, truncated_candidates: true } };
    });
    Array.from(root.querySelectorAll('button')).find((item) => item.textContent?.includes(language === 'tr' ? 'Gözlenen teknik inceleme adaylarını kaydet' : 'Record observed technical review candidates'))!.click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(root.textContent).toContain(language === 'tr' ? 'teknik kanıt 59' : 'technical evidence 59');
    expect(root.querySelector('.form-status[role="status"]')?.getAttribute('lang')).toBe(language);
    expect(root.querySelector('.form-status[role="status"]')?.textContent).toContain(language === 'tr' ? '1 kaynak kapsamına uygun teknik adayı' : '1 source-qualified technical candidates');
    expect(root.querySelector('.form-status[role="status"]')?.textContent).toContain(language === 'tr' ? 'ek gözlemler sınır nedeniyle dahil edilmedi' : 'additional observations are truncated');
    const component = harness.routeDebugElement!.componentInstance;
    const response = await api.indexationEvidence(7, 9, 42);
    const report = response.body['report'] as Record<string, unknown>;
    const url = (report['urls'] as Record<string, unknown>[])[0];
    const engine = { provider: 'google_search_console', property: 'https://onboarding.example', indexed_state: 'reported_indexed', method: 'url_inspection', engine_selected_canonical: 'https://onboarding.example/', declared_canonical: null, collected_at: '2026-09-27T12:00:00Z', engine_last_crawl_at: null, stale_relative_to_local_crawl: true, disagreement_candidates: ['canonical_disagreement_candidate'] };
    const read = vi.spyOn(api, 'indexationEvidence').mockResolvedValue({ ...response, body: { ...response.body, report: { ...report, urls: [{ ...url, engine_reports: [engine] }] } } });
    await component.loadIndexation(42); harness.fixture.detectChanges();
    expect(panel.textContent).toContain(language === 'tr' ? 'Google dizinindeki sürüm için' : "on Google's indexed version");
    expect(panel.textContent).toContain(language === 'tr' ? 'yerel taramadan eski' : 'older than local crawl');
    expect(panel.textContent).toContain(language === 'tr' ? 'bilinmiyor veya kapsam dışında' : 'unknown or outside scope');
    expect([...panel.querySelectorAll('span[lang="en"]')].map(item => item.textContent)).toEqual(expect.arrayContaining(['reported_indexed', 'canonical_disagreement_candidate', 'https://onboarding.example/']));
    let finish!: (value: ApiResult) => void;
    read.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    const pending = component.loadIndexation(42); harness.fixture.detectChanges();
    expect(panel.textContent).not.toContain('reported_indexed');
    expect(panel.querySelector('[role="status"]')?.textContent).toContain(language === 'tr' ? 'kanıtları kontrol ediliyor' : 'Checking project crawl and engine evidence');
    finish({ status: 403, body: {} }); await pending; harness.fixture.detectChanges();
    expect(panel.querySelector('[role="alert"]')?.textContent).toContain(language === 'tr' ? 'Dizinleme kanıtları kullanılamıyor' : 'Indexation evidence is unavailable');
    expect(panel.querySelector('ul')).toBeNull(); read.mockRestore();
  });

  it.each(['en', 'tr'] as const)('previews deterministic CSV candidates only for a complete selected source import (%s)', async (language) => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    api.sourcesHandler = (_org, projectId) => Promise.resolve({ status: 200, body: {
      project_id: projectId, has_more: false, sources: [{ id: 8, provider: 'google_search_console',
        property: 'https://onboarding.example', state: 'active', scope_current: true,
        csv_import_supported: true, oauth_available: false, api_sync_available: false,
        credential_status: 'not_connected', sync: null, latest_import: null }],
    } });
    vi.spyOn(api, 'sourceImportHistory').mockImplementation((_org, projectId, connectionId) => Promise.resolve({
      status: 200, body: { project_id: projectId, connection_id: connectionId,
        property: 'https://onboarding.example', provider: 'google_search_console', has_more: false,
        imports: [{ id: 23, created_at: '2026-09-26T00:00:00Z', export_shape: 'query', status: 'succeeded',
          coverage_state: 'complete', date_start: '2026-09-01', date_end: '2026-09-05', rows_seen: 1,
          rows_imported: 1, row_errors: 0, source_completeness: 'provider_export_unknown' }] },
    }));
    await harness.navigateByUrl('/app/onboarding/7/9');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    Array.from(root.querySelectorAll('button')).find((button) => button.textContent?.includes(language === 'tr' ? 'CSV içe aktarma geçmişini görüntüle' : 'View CSV import history'))!.click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(root.textContent).not.toContain('web_position_4_to_20_candidate');
    Array.from(root.querySelectorAll('button')).find((button) => button.textContent?.includes(language === 'tr' ? 'Kaynak kapsamına uygun adayları önizle' : 'Preview source-qualified candidates'))!.click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(root.textContent).toContain('gsc-csv-opportunity-v1');
    expect(root.querySelector('#import-history-title')?.parentElement?.querySelector('section[aria-label]')?.closest('[lang]')?.getAttribute('lang')).toBe(language);
    expect(root.textContent).toContain(language === 'tr' ? 'sağlayıcının üst sıralı satırları incomplete_unknown' : 'provider top rows incomplete_unknown');
    expect(root.textContent).toContain('web_position_4_to_20_candidate');
    expect(root.textContent).toContain(language === 'tr' ? 'onaylanmış bulgular' : 'not approved findings');
    const component = harness.routeDebugElement!.componentInstance;
    const original = structuredClone(component.opportunityPreview());
    const preview = vi.spyOn(api, 'sourceOpportunityPreview'), record = vi.spyOn(api, 'recordImportFindings');
    const changes = [
      ...['query', 'page'].map(dimension => ({ dimension: [dimension] })),
      ...['web_position_4_to_20_candidate', 'web_high_impressions_low_ctr_candidate'].map(detector => ({
        candidates: original.candidates.map((candidate: Record<string, unknown>) => ({ ...candidate, detector: [detector] })),
      })),
    ];
    for (const change of changes) {
      preview.mockResolvedValueOnce({ status: 200, body: { ...original, ...change } }); await component.loadOpportunityPreview(8, 23);
      expect(component.opportunityPreview()).toBeNull(); expect(component.opportunityError()).toBe(true);
      expect(component.canRecordOpportunityPreview()).toBe(false); await component.recordOpportunityCandidates(8, 23); expect(record).not.toHaveBeenCalled();
      preview.mockResolvedValueOnce({ status: 200, body: original }); await component.loadOpportunityPreview(8, 23);
      expect(component.opportunityPreview()?.method).toBe('gsc-csv-opportunity-v1'); expect(component.opportunityError()).toBe(false);
    }
    preview.mockRestore(); record.mockRestore(); harness.fixture.detectChanges();
    const recordAcknowledgment = vi.spyOn(api, 'recordImportFindings');
    Array.from(root.querySelectorAll('button')).find((button) => button.textContent?.includes(language === 'tr' ? 'İnsan incelemesi için değişmez aday kanıtlarını kaydet' : 'Record immutable candidate evidence'))!.click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(root.textContent).toContain(language === 'tr' ? 'Henüz insan incelemeci tarafından önceliklendirilmedi' : 'Not yet prioritized by a human reviewer');
    const acknowledgment = root.querySelector('.form-status[role="status"]')!;
    expect(acknowledgment.getAttribute('lang')).toBe(language);
    expect(acknowledgment.textContent).toContain(language === 'tr' ? '1 değişmez aday bulgu gözlemi kaydedildi' : '1 immutable candidate finding observations recorded');
    const originalMessage = component.message();
    const review = root.querySelector<HTMLFormElement>('#finding-priority-112')!.closest('form')!;
    review.querySelector<HTMLSelectElement>('select[name="priority"]')!.value = 'medium';
    review.querySelector<HTMLInputElement>('input[name="reason"]')!.value = 'Review actual intent first';
    const humanReason = review.querySelector<HTMLInputElement>('input[name="reason"]')!;
    humanReason.focus();
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(component.message()).toBe(originalMessage);
    expect(root.querySelector('.form-status[role="status"]')).toBe(acknowledgment);
    expect(acknowledgment.getAttribute('lang')).toBe(language === 'tr' ? 'en' : 'tr');
    expect(acknowledgment.textContent).toContain(language === 'tr' ? '1 immutable candidate finding observations recorded' : '1 değişmez aday bulgu gözlemi kaydedildi');
    expect(recordAcknowledgment).toHaveBeenCalledOnce();
    expect(review.querySelector('input[name="reason"]')).toBe(humanReason);
    expect(humanReason.value).toBe('Review actual intent first'); expect(document.activeElement).toBe(humanReason);
    component.productLanguage.set(language); harness.fixture.detectChanges();
    review.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(root.textContent).toContain(language === 'tr' ? 'İnsan inceleme sürümü 1: medium öncelik' : 'Human review revision 1: medium priority');
    expect(root.querySelector('#findings-title')?.closest('[lang]')?.getAttribute('lang')).toBe(language);
    expect(root.querySelector('[aria-labelledby="findings-title"] pre')?.getAttribute('lang')).toBe('en');
    expect(root.querySelector('[aria-labelledby="findings-title"] strong span[lang=""]')).toBeTruthy();
    expect(root.querySelector('.form-status[role="status"]')?.getAttribute('lang')).toBe(language);
    expect(root.textContent).toContain(language === 'tr' ? 'Hiçbir öneri veya değişiklik onaylanmadı' : 'No recommendation or change has been approved');
  });

  it('rejects array human opportunity reviews in current evidence and POST replies and clears pending denied findings', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    await api.recordImportFindings(7, 9, 8, 23);
    const review = { id: 120, revision: 1, priority: 'medium', estimated_effort: 'small', business_relevance: 'high', review_reason: 'Human source review.' };
    const original = { ...api.findingRows[0], review }; api.findingRows = [original];
    const harness = await RouterTestingHarness.create('/app/onboarding/7/9'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    await component.loadFindings(); expect(component.findings()).toHaveLength(1);
    const fields: Record<string, string[]> = { priority: ['unprioritized', 'low', 'medium', 'high'],
      estimated_effort: ['unknown', 'small', 'medium', 'large'], business_relevance: ['unknown', 'low', 'medium', 'high'] };
    for (const [field, values] of Object.entries(fields)) for (const value of values) {
      api.findingRows = [{ ...original, review: { ...review, [field]: [value] } }]; await component.loadFindings();
      expect(component.findingsError()).toBe(true); expect(component.findings()).toEqual([]);
      api.findingRows = [{ ...original, review: { ...review, [field]: value } }]; await component.loadFindings();
      expect(component.findingsError()).toBe(false); expect(component.findings()[0].review[field]).toBe(value);
    }
    api.findingRows = [original]; await component.loadFindings();
    const write = vi.spyOn(api, 'reviewFinding');
    for (const field of Object.keys(fields)) {
      write.mockResolvedValueOnce({ status: 201, body: { project_id: 9, finding_id: 112, approved_action: null,
        review: { ...review, revision: 2, [field]: [review[field as keyof typeof review]] } } });
      harness.fixture.detectChanges();
      const form = harness.routeNativeElement!.querySelector('#finding-priority-112')!.closest('form')!;
      form.querySelector<HTMLInputElement>('input[name="reason"]')!.value = 'Deliberate human source review.';
      form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true })); await harness.fixture.whenStable();
      expect(component.error()).toContain('Opportunity review changed'); expect(component.message()).toBe('');
      expect(component.findings()[0].review.revision).toBe(1);
    }
    expect(write.mock.calls).toHaveLength(3); write.mockRestore();
    let finish!: (value: ApiResult) => void;
    vi.spyOn(api, 'projectFindings').mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    component.findingsTruncated.set(true);
    const pending = component.loadFindings();
    expect(component.findings()).toEqual([]); expect(component.findingsLoaded()).toBe(false); expect(component.findingsTruncated()).toBe(false);
    finish({ status: 403, body: {} }); await pending;
    expect(component.findingsError()).toBe(true); expect(component.findings()).toEqual([]);
  });

  it.each(['en', 'tr'] as const)('records only explicitly selected complete query-window candidate evidence (%s)', async (language) => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    api.sourcesHandler = (_org, projectId) => Promise.resolve({ status: 200, body: {
      project_id: projectId, has_more: false, sources: [{ id: 8, provider: 'google_search_console',
        property: 'https://onboarding.example', state: 'active', scope_current: true,
        csv_import_supported: true, oauth_available: false, api_sync_available: false,
        credential_status: 'not_connected', sync: null, latest_import: null }],
    } });
    vi.spyOn(api, 'sourceImportHistory').mockImplementation((_org, projectId, connectionId) => Promise.resolve({
      status: 200, body: { project_id: projectId, connection_id: connectionId,
        property: 'https://onboarding.example', provider: 'google_search_console', has_more: false,
        imports: [23, 24].map((id) => ({ id, created_at: '2026-09-26T00:00:00Z',
          export_shape: 'query', status: 'succeeded', coverage_state: 'complete',
          date_start: id === 23 ? '2026-09-01' : '2026-09-08',
          date_end: id === 23 ? '2026-09-07' : '2026-09-14', rows_seen: 1,
          rows_imported: 1, row_errors: 0, source_completeness: 'provider_export_unknown' })) },
    }));
    const record = vi.spyOn(api, 'recordQueryChangeFindings');
    await harness.navigateByUrl('/app/onboarding/7/9');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    Array.from(root.querySelectorAll('button')).find((button) => button.textContent?.includes(language === 'tr' ? 'CSV içe aktarma geçmişini görüntüle' : 'View CSV import history'))!.click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const form = root.querySelector<HTMLFormElement>('select[name="previous"]')!.closest('form')!;
    form.querySelector<HTMLSelectElement>('select[name="previous"]')!.value = '23';
    form.querySelector<HTMLSelectElement>('select[name="current"]')!.value = '24';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(record).toHaveBeenCalledWith(7, 9, 8, 23, 24);
    expect(root.textContent).toContain('web_query_clicks_decreased_candidate');
    expect(root.textContent).toContain('hidden_queries');
    expect(root.textContent).toContain(language === 'tr' ? 'ortak sorgu/sayfa gözlemleri' : 'joint query/page observations');
    expect(root.textContent).toContain(language === 'tr' ? 'hiçbir aksiyon onaylanmadı' : 'no action was approved');
    expect(root.querySelector('.form-status[role="status"]')?.getAttribute('lang')).toBe(language);
    expect(root.querySelector('.form-status[role="status"]')?.textContent).toContain(language === 'tr' ? '1 karşılaştırılabilir gözlenen sorgu değişimi adayı' : '1 comparable observed query-change candidates');
  });

  it.each(['en', 'tr'] as const)('keeps page comparison separate from query candidate evidence (%s)', async (language) => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    api.sourcesHandler = (_org, projectId) => Promise.resolve({ status: 200, body: {
      project_id: projectId, has_more: false, sources: [{ id: 8, provider: 'google_search_console',
        property: 'https://onboarding.example', state: 'active', scope_current: true,
        csv_import_supported: true, oauth_available: false, api_sync_available: false,
        credential_status: 'not_connected', sync: null, latest_import: null }],
    } });
    vi.spyOn(api, 'sourceImportHistory').mockImplementation((_org, projectId, connectionId) => Promise.resolve({
      status: 200, body: { project_id: projectId, connection_id: connectionId,
        property: 'https://onboarding.example', provider: 'google_search_console', has_more: false,
        imports: [33, 34].map((id) => ({ id, created_at: '2026-09-26T00:00:00Z',
          export_shape: 'page', status: 'succeeded', coverage_state: 'complete',
          date_start: id === 33 ? '2026-09-01' : '2026-09-08',
          date_end: id === 33 ? '2026-09-07' : '2026-09-14', rows_seen: 1, rows_imported: 1,
          row_errors: 0, source_completeness: 'provider_export_unknown' })) },
    }));
    const record = vi.spyOn(api, 'recordPageChangeFindings');
    await harness.navigateByUrl('/app/onboarding/7/9');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    Array.from(root.querySelectorAll('button')).find((button) => button.textContent?.includes(language === 'tr' ? 'CSV içe aktarma geçmişini görüntüle' : 'View CSV import history'))!.click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const form = root.querySelector<HTMLFormElement>('#page-previous-import')!.closest('form')!;
    form.querySelector<HTMLSelectElement>('select[name="previous"]')!.value = '33';
    form.querySelector<HTMLSelectElement>('select[name="current"]')!.value = '34';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(record).toHaveBeenCalledWith(7, 9, 8, 33, 34);
    expect(root.textContent).toContain('web_page_clicks_decreased_candidate');
    expect(root.textContent).toContain(language === 'tr' ? 'eksik satırlar bilinmiyor' : 'missing rows remain unknown');
    expect(root.querySelector('.form-status[role="status"]')?.getAttribute('lang')).toBe(language);
    expect(root.querySelector('.form-status[role="status"]')?.textContent).toContain(language === 'tr' ? '1 karşılaştırılabilir gözlenen sayfa değişimi adayı' : '1 comparable observed page-change candidates');
  });

  it('rejects array Analytics grant states and clears pending denied grant controls', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const original = { id: 71, state: 'pending_selection', revision: 1, property_id: '12345',
      selected_origins: ['https://onboarding.example'], scope_current: true,
      source_status: 'not_linked_no_data_sync', verified_at: '2026-09-28T02:00:00Z' };
    api.ga4GrantRows = [original];
    const harness = await RouterTestingHarness.create('/app/onboarding/7/9'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    expect(component.ga4Error()).toBe(false); expect(component.ga4Grants()).toHaveLength(1);
    for (const state of ['pending_selection', 'active', 'revocation_pending', 'reconnect_required', 'revoked']) {
      api.ga4GrantRows = [{ ...original, state: [state] }]; await component.loadGA4Grants();
      expect(component.ga4Error()).toBe(true); expect(component.ga4Grants()).toEqual([]);
      api.ga4GrantRows = [{ ...original, state }]; await component.loadGA4Grants();
      expect(component.ga4Error()).toBe(false); expect(component.ga4Grants()[0].state).toBe(state);
    }
    api.ga4GrantRows = [original]; await component.loadGA4Grants();
    const grant = component.ga4Grants()[0], link = vi.spyOn(api, 'linkGA4Source');
    let finish!: (value: ApiResult) => void;
    const read = vi.spyOn(api, 'ga4Grants').mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    component.ga4Truncated.set(true);
    const pending = component.loadGA4Grants();
    expect(component.ga4Grants()).toEqual([]); expect(component.ga4Truncated()).toBe(false);
    await component.linkGA4(grant); expect(link).not.toHaveBeenCalled();
    finish({ status: 403, body: {} }); await pending;
    expect(component.ga4Grants()).toEqual([]); expect(component.ga4Error()).toBe(true);
    expect(read).toHaveBeenCalledTimes(1); read.mockRestore(); link.mockRestore();
  });

  it.each(['en', 'tr'] as const)('rejects array manual Analytics review states in history and acknowledgments without verifying measurements (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    api.sourcesHandler = (_org, projectId) => Promise.resolve({ status: 200, body: {
      project_id: projectId, has_more: false, sources: [{ id: 91, provider: 'google_analytics_4',
        property: '12345', state: 'active', scope_current: true, scope_kind: 'ga4_hostname_only',
        approved_origins: ['https://onboarding.example'], available_api_dimensions: [],
        csv_import_supported: false, oauth_available: false, api_sync_available: false,
        coverage_available: false, credential_status: 'reference_reserved', sync: null, latest_import: null,
        data_status: 'exact_origin_attribution_unavailable' }],
    } });
    const review = { id: 301, revision: 1, property_id: '12345', currency: 'USD', timezone: 'UTC', definitions: [],
      instrumentation_state: 'unverified', event_quality_state: 'not_checked', instrumentation_notes: 'Manual observation',
      attribution_notes: '', consent_notes: '', tracking_change_notes: '', created_at: '2026-09-28T00:00:00Z' };
    api.ga4QualityRows = [review];
    const harness = await RouterTestingHarness.create('/app/onboarding/7/9'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    const fields: Record<string, string[]> = { instrumentation_state: ['unverified', 'manual_reviewed'],
      event_quality_state: ['not_checked', 'suspected_missing', 'suspected_duplicate', 'suspected_both', 'manual_review_no_concern'] };
    await component.loadGA4Quality(91);
    expect(component.ga4QualityReviews()).toHaveLength(1);
    for (const [field, values] of Object.entries(fields)) {
      for (const value of values) {
        api.ga4QualityRows = [{ ...review, [field]: [value] }]; await component.loadGA4Quality(91);
        expect(component.ga4QualityError()).toBe(true); expect(component.ga4QualityReviews()).toEqual([]);
        expect(component.ga4QualitySourceCurrent()).toBe(false);
        api.ga4QualityRows = [{ ...review, [field]: value }]; await component.loadGA4Quality(91);
        expect(component.ga4QualityError()).toBe(false); expect(component.ga4QualityReviews()[0][field]).toBe(value);
      }
    }
    api.ga4QualityRows = [review]; await component.loadGA4Quality(91); harness.fixture.detectChanges();
    const save = vi.spyOn(api, 'saveGA4Quality');
    for (const field of Object.keys(fields)) {
      save.mockResolvedValue({ status: 201, body: { project_id: 9, connection_id: 91,
        review: { ...review, revision: 2, [field]: [fields[field][0]] }, provider_instrumentation_verified: false } });
      const form = harness.routeNativeElement!.querySelector<HTMLTextAreaElement>('#ga4-definitions-91')!.closest('form')!;
      form.querySelector<HTMLTextAreaElement>('textarea[name="instrumentation_notes"]')!.value = 'Keep manual observation';
      form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
      await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(component.error()).toContain('Analytics review outcome unknown'); expect(component.message()).toBe('');
      expect(harness.routeNativeElement!.querySelector('.form-status[role="alert"]')?.getAttribute('lang')).toBe(language);
      expect(harness.routeNativeElement!.querySelector('.form-status[role="alert"]')?.textContent).toContain(language === 'tr' ? 'Analytics inceleme sonucu bilinmiyor' : 'Analytics review outcome unknown');
      expect(component.ga4QualityReviews()[0].revision).toBe(1);
      expect(form.querySelector<HTMLTextAreaElement>('textarea[name="instrumentation_notes"]')!.value).toBe('Keep manual observation');
    }
    expect(save).toHaveBeenCalledTimes(2); save.mockRestore();
    const read = vi.spyOn(api, 'ga4QualityHistory').mockResolvedValue({ status: 403, body: {} });
    component.ga4QualityTruncated.set(true);
    const pending = component.loadGA4Quality(91);
    expect(component.ga4QualityReviews()).toEqual([]); expect(component.ga4QualitySourceCurrent()).toBe(false);
    expect(component.ga4QualityTruncated()).toBe(false);
    await pending; expect(component.ga4QualityError()).toBe(true); read.mockRestore();
    expect(api.ga4JobResult).toBeNull(); expect(harness.routeNativeElement!.querySelector('#ga4-day-91')).toBeNull();
  });

  it.each(['en', 'tr'] as const)('selects a scoped Analytics grant without claiming synced conversions (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    api.ga4GrantRows = [{ id: 71, state: 'pending_selection', revision: 0, property_id: '',
      selected_origins: [], scope_current: false, source_status: 'not_linked_no_data_sync',
      verified_at: '2026-09-28T02:00:00Z' }];
    const harness = await RouterTestingHarness.create('/app/onboarding/7/9');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    const form = root.querySelector<HTMLInputElement>('#ga4-property-71')!.closest('form')!;
    expect(form.closest('section')?.getAttribute('lang')).toBe(language);
    expect(form.textContent).toContain(language === 'tr' ? 'Yapılandırılmış tek bir HTTPS web kaynak adresi' : 'One configured HTTPS web origin');
    expect([...form.querySelectorAll('option')].map(item => item.value)).toEqual(['', 'https://onboarding.example']);
    expect(form.querySelector('option[value="https://onboarding.example"]')?.getAttribute('lang')).toBe('en');
    form.querySelector<HTMLInputElement>('input[name="property_id"]')!.value = '12345';
    form.querySelector<HTMLSelectElement>('select[name="origin"]')!.value = 'https://onboarding.example';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(root.textContent).toContain(language === 'tr' ? 'Kapsam içindeki bir kaynak bağlanana kadar izin devre dışıdır' : 'grant is disabled until a scoped source is linked');
    Array.from(root.querySelectorAll('button')).find((button) => button.textContent?.includes(language === 'tr' ? 'Bu yapılandırılmış Analytics kaynağını bağla' : 'Link this configured Analytics source'))!.click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(root.textContent).toContain(language === 'tr' ? 'tam kaynak adresi kapsamındaki Analytics raporları ve dönüşüm ölçüm kurulumu kullanılamıyor' : 'exact-origin Analytics reports and conversion instrumentation remain unavailable');
    expect(api.ga4GrantRows[0]['source_status']).toBe('configured_no_data_sync');
    expect(root.querySelector('.form-status[role="status"]')?.getAttribute('lang')).toBe(language);
    const revoke = vi.spyOn(api, 'revokeGA4Grant');
    const button = (en: string, tr: string) => [...root.querySelectorAll('button')].find(item => item.textContent?.includes(language === 'tr' ? tr : en))!;
    button('Disconnect Analytics grant 71', 'Analytics iznini kaldır 71').click(); harness.fixture.detectChanges();
    expect(revoke).not.toHaveBeenCalled();
    expect(root.querySelector('section[aria-labelledby="analytics-consent-title"] [role="alert"]')?.textContent).toContain(language === 'tr' ? 'Uzak yetki iptalini tekrar denemek gerekebilir' : 'Remote revocation may need retry');
    button('Cancel', 'Vazgeç').click(); harness.fixture.detectChanges(); expect(revoke).not.toHaveBeenCalled();
    expect(root.querySelector('section[aria-labelledby="analytics-consent-title"] [role="alert"]')).toBeNull();
    button('Disconnect Analytics grant 71', 'Analytics iznini kaldır 71').click(); harness.fixture.detectChanges();
    button('Confirm Analytics disconnect', 'Analytics bağlantısının kesilmesini onayla').click();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(revoke).toHaveBeenCalledWith(7, 9, 71);
    expect(root.textContent).toContain(language === 'tr' ? 'İzin iptal edildi; Analytics verisi kullanılamıyor' : 'Grant revoked; no Analytics data is available');
    expect(root.querySelector('.form-status[role="status"]')?.getAttribute('lang')).toBe(language); revoke.mockRestore();
    const component = harness.routeDebugElement!.componentInstance;
    const consent = vi.spyOn(api, 'startGA4OAuth').mockResolvedValue({ status: 503, body: { authorization_url: '' } });
    await component.connectGA4(); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(root.querySelector('.form-status[role="alert"]')?.getAttribute('lang')).toBe(language);
    expect(root.querySelector('.form-status[role="alert"]')?.textContent).toContain(language === 'tr' ? 'Analytics onayı kullanılamıyor' : 'Analytics consent unavailable'); consent.mockRestore();
  });

  it.each(['en', 'tr'] as const)('rejects array historical Analytics job statuses and report kinds without activating unavailable reports (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    api.sourcesHandler = (_org, projectId) => Promise.resolve({ status: 200, body: { project_id: projectId, has_more: false,
      sources: [{ id: 91, provider: 'google_analytics_4', property: '12345', state: 'active', scope_current: true,
        scope_kind: 'ga4_hostname_only', approved_origins: ['https://onboarding.example'], available_api_dimensions: [],
        csv_import_supported: false, oauth_available: false, api_sync_available: false, coverage_available: false,
        credential_status: 'reference_reserved', sync: null, latest_import: null, data_status: 'exact_origin_attribution_unavailable' }] } });
    const job = { id: 719, status: 'queued', day: '2026-09-20', report_kind: 'organic_search', hostname: 'onboarding.example',
      error_category: '', requests_attempted: 0, pages_recorded: 0, source_coverage: 'unavailable', sampling_or_threshold_gaps: null };
    const response = { status: 200, body: { project_id: 9, connection_id: 91, source_current: false,
      report_availability: 'exact_origin_attribution_unavailable', job, pages: [] } };
    const harness = await RouterTestingHarness.create('/app/onboarding/7/9'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    const read = vi.spyOn(api, 'ga4SyncStatus'), queue = vi.spyOn(api, 'queueGA4Sync');
    for (const [field, values] of Object.entries({ status: ['queued', 'running', 'partially_succeeded', 'succeeded', 'failed', 'cancelled'],
      report_kind: ['all_channels', 'organic_search'] })) {
      for (const value of values) {
        read.mockResolvedValue({ ...response, body: { ...response.body, job: { ...job, [field]: [value] } } });
        await component.refreshGA4Sync(91);
        expect(component.ga4SyncError()).toBe(true); expect(component.ga4SyncJob()).toBeNull(); expect(component.ga4SyncPages()).toEqual([]);
        read.mockResolvedValue({ ...response, body: { ...response.body, job: { ...job, [field]: value } } });
        await component.refreshGA4Sync(91);
        expect(component.ga4SyncError()).toBe(false); expect(component.ga4SyncJob()[field]).toBe(value); expect(component.ga4SyncPages()).toEqual([]);
      }
    }
    read.mockResolvedValue(response); await component.refreshGA4Sync(91);
    const cancel = vi.spyOn(api, 'cancelGA4Sync');
    for (const change of [{ status: ['cancelled'] }, { report_kind: ['organic_search'] }]) {
      cancel.mockResolvedValue({ status: 200, body: { project_id: 9, connection_id: 91, job: { ...job, ...change }, cancel_requested: false } });
      await component.cancelGA4Sync(91, 719);
      expect(component.error()).toContain('Analytics cancellation outcome unknown'); expect(component.message()).toBe('');
    }
    expect(cancel).toHaveBeenCalledTimes(2); cancel.mockRestore(); api.ga4JobResult = job;
    read.mockImplementation(() => Promise.resolve({ ...response, body: { ...response.body, job: api.ga4JobResult } }));
    await component.cancelGA4Sync(91, 719); expect(component.ga4SyncJob().status).toBe('cancelled');
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement!.querySelector('#ga4-day-91')).toBeNull(); expect(queue).not.toHaveBeenCalled();
    expect(component.ga4SyncPages()).toEqual([]);
    const root = harness.routeNativeElement!;
    expect(root.textContent).toContain(language === 'tr' ? 'Analytics işi 719: cancelled' : 'Analytics job 719: cancelled');
    expect([...root.querySelectorAll('[role="status"] span[lang="en"]')].map(item => item.textContent)).toEqual(expect.arrayContaining(['cancelled', 'organic_search', 'onboarding.example', 'unavailable']));
    const page = { id: 901, offset: 0, report_kind: 'organic_search', collected_at: '2026-09-28T00:00:00Z', result: {
      day: '2026-09-20', timezone: 'UTC', currency: 'USD', report_kind: 'organic_search',
      rows: [{ hostname: 'onboarding.example', path: '/sample', sessions: 2, key_events: '0.5', total_revenue: '12.30', session_default_channel_group: 'Organic Search' }],
      coverage: { sampled: true, thresholded: false, other_row_loss: true, full_activity_coverage: 'unknown', instrumentation_verified: false, acquisition_scope: 'ga4_organic_session_channel_hostname_filtered', omitted_foreign_or_parameterized_rows: 1 } } };
    read.mockResolvedValue({ ...response, body: { ...response.body, job: { ...job, status: 'succeeded', pages_recorded: 1 }, pages: [page] } });
    await component.refreshGA4Sync(91); harness.fixture.detectChanges();
    expect(root.textContent).toContain(language === 'tr' ? 'GA4 oturum kanalı, Search Console tıklaması veya hedef başına dönüşüm değildir' : 'GA4 session channel is not a Search Console click or a per-goal conversion');
    expect(root.textContent).toContain(language === 'tr' ? 'Örnekleme bildirildi' : 'Sampling reported');
    expect(root.textContent).toContain(language === 'tr' ? 'ölçüm kurulumu doğrulanmadı' : 'instrumentation not verified');
    expect(root.textContent).toContain('12.30 USD');
    expect([...root.querySelectorAll('span[lang="en"]')].map(item => item.textContent)).toEqual(expect.arrayContaining(['Organic Search', 'ga4_organic_session_channel_hostname_filtered']));
    expect(root.querySelector('#ga4-day-91')).toBeNull(); expect(queue).not.toHaveBeenCalled();
    read.mockRestore(); queue.mockRestore();
  });

  it.each(['en', 'tr'] as const)('keeps ambiguous Analytics sync unavailable while allowing manual measurement reviews (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    api.sourcesHandler = (_org, projectId) => Promise.resolve({ status: 200, body: {
      project_id: projectId, has_more: false, sources: [{ id: 91, provider: 'google_analytics_4',
        property: '12345', state: 'active', scope_current: true, scope_kind: 'ga4_hostname_only',
        approved_origins: ['https://onboarding.example'], available_api_dimensions: [],
         csv_import_supported: false, oauth_available: false, api_sync_available: false,
        coverage_available: false, credential_status: 'reference_reserved', sync: null, latest_import: null,
         data_status: 'exact_origin_attribution_unavailable' }],
    } });
    const harness = await RouterTestingHarness.create('/app/onboarding/7/9');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    expect(root.textContent).toContain(language === 'tr' ? 'Search Console tıklamaları, Analytics oturumları ve önemli etkinlikler farklı ölçümlerdir' : 'Search Console clicks, Analytics sessions and key events are different measurements');
    expect(root.querySelector('#ga4-day-91')).toBeNull();
    expect(root.textContent).toContain(language === 'tr' ? 'bu tam HTTPS kaynak adresini' : 'cannot distinguish this exact HTTPS origin');
    expect(api.ga4JobResult).toBeNull();
    Array.from(root.querySelectorAll('button')).find((button) => button.textContent?.includes(language === 'tr' ? 'Analytics ölçüm tanımlarını incele' : 'Review Analytics measurement definitions'))!.click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const review = root.querySelector<HTMLTextAreaElement>('#ga4-definitions-91')!.closest('form')!;
    expect(review.getAttribute('lang')).toBe(language);
    expect([...review.querySelectorAll('textarea')].every(item => item.getAttribute('lang') === '')).toBe(true);
    expect(review.textContent).toContain(language === 'tr' ? 'Bunlar tanımlardır; etkinlik başına sayılar değildir' : 'These are definitions, not per-event counts');
    expect([...review.querySelectorAll('select[name="instrumentation_state"] option')].map(item => (item as HTMLOptionElement).value)).toEqual(['unverified', 'manual_reviewed']);
    review.querySelector<HTMLTextAreaElement>('textarea[name="definitions"]')!.value =
      'Qualified booking | purchase | Unverified booking value';
    review.querySelector<HTMLTextAreaElement>('textarea[name="consent_notes"]')!.value = 'Collection gaps unknown';
    review.querySelector<HTMLSelectElement>('select[name="event_quality_state"]')!.value = 'suspected_missing';
    review.querySelector<HTMLTextAreaElement>('textarea[name="instrumentation_notes"]')!.value = 'Manual check needed';
    review.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.ga4QualityRows[0]['instrumentation_state']).toBe('unverified');
    expect(api.ga4QualityRows[0]['event_quality_state']).toBe('suspected_missing');
    expect(root.textContent).toContain(language === 'tr' ? 'etkinlik sayısı, ilişkilendirme veya dönüşüm doğrulanmadı' : 'no event count, attribution or conversion was verified');
    expect(root.textContent).toContain('Qualified booking → purchase');
    expect(root.querySelector('.form-status[role="status"]')?.getAttribute('lang')).toBe(language);
    const history = root.querySelector('ul[aria-label="' + (language === 'tr' ? 'Analytics ölçüm inceleme geçmişi' : 'Analytics measurement review history') + '"]')!;
    const unknown = [...history.querySelectorAll('span[lang=""]')].map(item => item.textContent);
    expect(unknown).toEqual(expect.arrayContaining(['Qualified booking', 'Unverified booking value', 'Collection gaps unknown', 'Manual check needed']));
    expect([...history.querySelectorAll('span[lang="en"]')].map(item => item.textContent)).toEqual(expect.arrayContaining(['purchase', 'unverified', 'suspected_missing', 'USD', 'UTC']));
    const component = harness.routeDebugElement!.componentInstance;
    const read = vi.spyOn(api, 'ga4QualityHistory').mockResolvedValue({ status: 200, body: { project_id: 9, connection_id: 91, source_current: false, reviews: api.ga4QualityRows, has_more: false } });
    await component.loadGA4Quality(91); harness.fixture.detectChanges();
    expect(root.querySelector('#ga4-definitions-91')).toBeNull();
    expect(root.textContent).toContain(language === 'tr' ? 'bu kaynak yeni incelemeler için güncel değildir' : 'this source is not current for new reviews');
    read.mockRejectedValue(new Error('private transport detail')); await component.loadGA4Quality(91); harness.fixture.detectChanges();
    expect(root.querySelector('ul[aria-label="' + (language === 'tr' ? 'Analytics ölçüm inceleme geçmişi' : 'Analytics measurement review history') + '"]')).toBeNull();
    expect(root.querySelector('[role="alert"]')?.getAttribute('lang')).toBe(language);
    expect(root.textContent).toContain(language === 'tr' ? 'Ölçüm inceleme geçmişi kullanılamıyor' : 'Measurement review history unavailable');
    expect(root.textContent).not.toContain('private transport detail'); read.mockRestore();
  });

  it('rejects array performance job metadata across history detail and command replies and clears pending authority', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.performanceKeyAvailable = true;
    api.performanceRequests.push({ target: 'https://onboarding.example/', sources: ['psi_lab', 'crux_current'], key: 'fixture' });
    const listResponse = await api.performanceAudits(7, 9), detailResponse = await api.performanceAuditDetail(7, 9, 72);
    const job = detailResponse.body['job'] as Record<string, unknown>;
    const harness = await RouterTestingHarness.create('/app/onboarding/7/9'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    await component.loadPerformance(); await component.showPerformance(72);
    const read = vi.spyOn(api, 'performanceAudits'), detail = vi.spyOn(api, 'performanceAuditDetail');
    const changes = [
      ...['queued', 'running', 'succeeded', 'failed', 'partially_succeeded', 'cancelled'].map(status => ({ status: [status] })),
      ...['page', 'origin'].map(grain => ({ grain: [grain] })),
      ...['mobile', 'desktop', 'tablet'].map(strategy => ({ strategy: [strategy] })),
      ...['psi_lab', 'crux_current', 'crux_history'].map(source => ({ sources: [[source]] })),
    ];
    for (const change of changes) {
      read.mockResolvedValue({ ...listResponse, body: { ...listResponse.body, jobs: [{ ...job, ...change }] } });
      await component.loadPerformance();
      expect(component.performanceError()).toBe(true); expect(component.performanceJobs()).toEqual([]);
      expect(component.performanceKeyAvailable()).toBe(false); expect(component.performanceLoaded()).toBe(false);
      read.mockResolvedValue(listResponse); await component.loadPerformance();
      expect(component.performanceError()).toBe(false); expect(component.performanceJobs()).toHaveLength(1);
      detail.mockResolvedValue({ ...detailResponse, body: { ...detailResponse.body, job: { ...job, ...change } } });
      await component.showPerformance(72);
      expect(component.performanceDetailError()).toBe(true); expect(component.performanceSelected()).toBeNull();
      expect(component.performanceObservations()).toEqual([]);
      const scalar = Object.fromEntries(Object.entries(change).map(([field, values]) =>
        [field, field === 'sources' ? [values[0][0]] : values[0]]));
      detail.mockResolvedValue({ ...detailResponse, body: { ...detailResponse.body, job: { ...job, ...scalar } } });
      await component.showPerformance(72); expect(component.performanceDetailError()).toBe(false);
    }
    detail.mockResolvedValue(detailResponse); await component.showPerformance(72); harness.fixture.detectChanges();
    const form = harness.routeNativeElement!.querySelector<HTMLInputElement>('input[name="target"]')!.closest('form')!;
    for (const source of ['psi_lab', 'crux_current']) form.querySelector<HTMLInputElement>(`input[value="${source}"]`)!.checked = true;
    const start = vi.spyOn(api, 'startPerformanceAudit').mockResolvedValue({ status: 202, body: {
      project_id: 9, job: { ...job, status: ['queued'] }, max_requests: 2 } });
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); expect(component.error()).toContain('Audit outcome unknown'); expect(start).toHaveBeenCalledTimes(1);
    const cancel = vi.spyOn(api, 'cancelPerformanceAudit').mockResolvedValue({ status: 200, body: {
      project_id: 9, job: { ...job, status: ['cancelled'] }, cancel_requested: false } });
    await component.cancelPerformance(72); expect(component.error()).toContain('Audit cancellation outcome unknown');
    expect(component.message()).not.toContain('Audit cancelled'); expect(cancel).toHaveBeenCalledTimes(1);
    cancel.mockRestore(); await component.cancelPerformance(72); expect(component.performanceSelected().status).toBe('cancelled');
    let finish!: (value: ApiResult) => void;
    read.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    component.performanceHasMore.set(true); const pending = component.loadPerformance();
    expect(component.performanceJobs()).toEqual([]); expect(component.performanceSelected()).toBeNull();
    expect(component.performanceObservations()).toEqual([]); expect(component.performanceKeyAvailable()).toBe(false);
    expect(component.performanceHasMore()).toBe(false); expect(component.performanceLoaded()).toBe(false);
    detail.mockClear(); await component.showPerformance(72); expect(detail).not.toHaveBeenCalled();
    start.mockClear(); form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await Promise.resolve(); expect(start).not.toHaveBeenCalled();
    finish({ status: 403, body: {} }); await pending; expect(component.performanceError()).toBe(true);
    expect(component.performanceJobs()).toEqual([]); read.mockRestore(); detail.mockRestore(); start.mockRestore();
  });

  it('rejects array parsed performance source labels while preserving separate scalar lab and field evidence', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.performanceRequests.push({ target: 'https://onboarding.example/', sources: ['psi_lab', 'crux_current'], key: 'fixture' });
    const original = await api.performanceAuditDetail(7, 9, 72);
    const observations = original.body['observations'] as Record<string, unknown>[];
    api.performanceHistory = true;
    const history = await api.performanceAuditDetail(7, 9, 72);
    api.performanceHistory = false;
    const all = [...observations, ...(history.body['observations'] as Record<string, unknown>[])];
    const harness = await RouterTestingHarness.create('/app/onboarding/7/9'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    await component.loadPerformance();
    const detail = vi.spyOn(api, 'performanceAuditDetail');
    for (const observation of all) {
      const result = observation['result'] as Record<string, unknown>;
      for (const invalid of [{ ...observation, source: [observation['source']] },
        { ...observation, result: { ...result, source: [result['source']] } }]) {
        detail.mockResolvedValue({ ...original, body: { ...original.body, observations: [invalid] } });
        await component.showPerformance(72);
        expect(component.performanceDetailError()).toBe(true); expect(component.performanceSelected()).toBeNull();
        expect(component.performanceObservations()).toEqual([]);
        detail.mockResolvedValue({ ...original, body: { ...original.body, observations: [observation] } });
        await component.showPerformance(72);
        expect(component.performanceDetailError()).toBe(false); expect(component.performanceObservations()).toEqual([observation]);
      }
    }
    detail.mockRestore(); expect(api.cruxInspections).toEqual([]); expect(api.cruxPolicyInspections).toEqual([]);
  });

  it.each(['en', 'tr'] as const)('shows key absence and separates Lighthouse lab from partial CrUX field results (%s)', async (language) => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    await harness.navigateByUrl('/app/onboarding/7/9');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    expect(root.querySelector('[aria-labelledby="performance-title"]')?.getAttribute('lang')).toBe(language);
    Array.from(root.querySelectorAll('button')).find((button) => button.textContent?.includes(language === 'tr' ? 'Performans geçmişini yükle' : 'Load performance history'))!.click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(root.textContent).toContain(language === 'tr' ? 'performans anahtarı yapılandırılmamış' : 'performance key is not configured');
    expect(root.querySelector('input[name="target"]')).toBeNull();
    api.performanceKeyAvailable = true;
    Array.from(root.querySelectorAll('button')).find((button) => button.textContent?.includes(language === 'tr' ? 'Performans geçmişini yenile' : 'Refresh performance history'))!.click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const form = root.querySelector<HTMLFormElement>('input[name="target"]')!.closest('form')!;
    for (const source of ['psi_lab', 'crux_current']) form.querySelector<HTMLInputElement>(`input[value="${source}"]`)!.checked = true;
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.performanceRequests[0].sources).toEqual(['psi_lab', 'crux_current']);
    expect(root.textContent).toContain(language === 'tr' ? 'Lighthouse laboratuvarı' : 'Lighthouse lab');
    expect(root.textContent).toContain(language === 'tr' ? 'CrUX güncel saha p75' : 'CrUX current field p75');
    expect(root.textContent).toContain(language === 'tr' ? 'kaynak adresine dönüş (sayfa verisi değil)' : 'origin fallback (not page data)');
    expect(root.textContent).toContain(language === 'tr' ? 'p75 kullanılamıyor' : 'p75 unavailable');
    expect(root.textContent).not.toContain('PRIVATE_PROVIDER_BODY');
    expect(root.querySelector('#performance-grain option[value="page"]')?.textContent).toBe(language === 'tr' ? 'Sayfa' : 'Page');
    expect(root.querySelector('[aria-labelledby="performance-title"] span[lang="en"]')?.textContent).toBe('partially_succeeded');
    expect(root.querySelector('.form-status[role="status"]')?.getAttribute('lang')).toBe(language);
    expect(root.querySelector('.form-status[role="status"]')?.textContent).toContain(language === 'tr' ? 'Denetim 72 kuyruğa alındı' : 'Audit 72 queued');
    const page = harness.routeDebugElement!.componentInstance as ProjectOnboarding;
    const read = vi.spyOn(api, 'performanceAudits').mockResolvedValue({ status: 503, body: {} });
    await page.loadPerformance(); harness.fixture.detectChanges();
    expect(root.querySelector('[aria-labelledby="performance-title"] [role="alert"]')?.textContent)
      .toContain(language === 'tr' ? 'Performans geçmişi kullanılamıyor' : 'Performance history is unavailable');
    read.mockRestore();
  });

  it.each(['en', 'tr'] as const)('requires deliberate original CrUX inspection rather than historical parsed overlap labels (%s)', async (language) => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    api.performanceKeyAvailable = true;
    api.performanceHistory = true;
    api.performanceRequests.push({ target: 'https://onboarding.example/', sources: ['crux_history'], key: 'fixture' });
    await harness.navigateByUrl('/app/onboarding/7/9');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    expect(root.querySelector('[aria-labelledby="performance-title"]')?.getAttribute('lang')).toBe(language);
    Array.from(root.querySelectorAll('button')).find((button) => button.textContent?.includes(language === 'tr' ? 'Performans geçmişini yükle' : 'Load performance history'))!.click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    Array.from(root.querySelectorAll('button')).find((button) => button.textContent?.includes(language === 'tr' ? 'Ayrıştırılmış kanıtları incele' : 'Inspect parsed evidence'))!.click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(root.textContent).toContain(language === 'tr' ? 'CrUX geçmiş saha p75' : 'CrUX history field p75');
    expect(root.textContent).not.toContain('LCP: regression_candidate');
    expect(root.textContent).toContain(language === 'tr' ? 'özgün ham veri bütünlüğünü' : 'do not establish original raw integrity');
    expect(api.cruxInspections).toEqual([]);
    expect(root.querySelector('app-project-crux-history section')?.getAttribute('lang')).toBe(language);
    Array.from(root.querySelectorAll('button')).find(button => button.textContent?.includes(language === 'tr' ? 'Özgün CrUX geçmişini incele / yenile' : 'Inspect / refresh original CrUX history'))!.click();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.cruxInspections).toEqual([[7, 9, 75]]);
    expect(root.textContent).toContain(language === 'tr' ? 'Karşılaştırma yeniden oluşturulmadı' : 'No comparison was reconstructed');
    expect(root.textContent).not.toContain('Lighthouse lab · mobile');
    Array.from(root.querySelectorAll('button')).find((button) => button.textContent?.includes(language === 'tr' ? 'Ayrıştırılmış performans inceleme adaylarını kaydet' : 'Record parsed performance review candidates'))!.click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(root.textContent).toContain(language === 'tr' ? 'performans kanıtı 75' : 'performance evidence 75');
    expect(root.querySelector('.form-status[role="status"]')?.getAttribute('lang')).toBe(language);
    expect(root.querySelector('.form-status[role="status"]')?.textContent).toContain(language === 'tr' ? '1 kaynak kapsamına uygun performans adayı' : '1 source-qualified performance candidates');
    expect(root.querySelector('.form-status[role="status"]')?.textContent).toContain(language === 'tr' ? 'hiçbiri onaylanmış aksiyon değildir' : 'none is an approved action');
  });

  it('explicitly inspects material policy and clears audit switch, refresh, cancellation and routed late scope results', async () => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.performanceHistory = true;
    api.performanceRequests.push({ target: 'https://onboarding.example/', sources: ['crux_history'], key: 'fixture' });
    const page = await harness.navigateByUrl('/app/onboarding/7/9', ProjectOnboarding);
    await harness.fixture.whenStable(); await page.loadPerformance(); await page.showPerformance(72); harness.fixture.detectChanges();
    expect(api.cruxPolicyInspections).toEqual([]);
    const click = () => Array.from(harness.routeNativeElement!.querySelectorAll('button'))
      .find(button => button.textContent?.includes('Inspect / refresh CrUX material policy'))!.click();
    const inspect = async () => { click(); await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(harness.routeNativeElement!.textContent).toContain('no material comparison reconstructed'); };
    await inspect(); expect(api.cruxPolicyInspections).toEqual([[7, 9, 75]]); expect(api.cruxInspections).toEqual([]);
    const switched = page.showPerformance(72); harness.fixture.detectChanges();
    expect(harness.routeNativeElement!.textContent).not.toContain('no material comparison reconstructed');
    await switched; harness.fixture.detectChanges(); await inspect();
    await page.cancelPerformance(72); harness.fixture.detectChanges();
    expect(harness.routeNativeElement!.textContent).not.toContain('no material comparison reconstructed');
    await page.showPerformance(72); harness.fixture.detectChanges(); await inspect();
    const refreshed = page.loadPerformance(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement!.querySelector('app-project-crux-history')).toBeNull();
    await refreshed; await page.showPerformance(72); harness.fixture.detectChanges();
    let resolve!: (value: ApiResult) => void; api.cruxPolicyHandler = () => new Promise(done => resolve = done);
    click(); harness.fixture.detectChanges(); await harness.navigateByUrl('/app/onboarding/7/10');
    resolve({ status: 200, body: { message: 'PRIVATE old policy' } });
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement!.querySelector('app-project-crux-history')).toBeNull();
    expect(harness.routeNativeElement!.textContent).not.toContain('PRIVATE');
  });

  it('clears original CrUX inspection on audit switch, refresh, cancellation and routed late scope results', async () => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.performanceHistory = true;
    api.performanceRequests.push({ target: 'https://onboarding.example/', sources: ['crux_history'], key: 'fixture' });
    const page = await harness.navigateByUrl('/app/onboarding/7/9', ProjectOnboarding);
    await harness.fixture.whenStable(); await page.loadPerformance(); await page.showPerformance(72); harness.fixture.detectChanges();
    const click = () => Array.from(harness.routeNativeElement!.querySelectorAll('button'))
      .find(button => button.textContent?.includes('Inspect / refresh original CrUX history'))!.click();
    const inspect = async () => { click(); await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(harness.routeNativeElement!.textContent).toContain('No comparison was reconstructed'); };
    await inspect();
    const switched = page.showPerformance(72); harness.fixture.detectChanges();
    expect(harness.routeNativeElement!.textContent).not.toContain('No comparison was reconstructed');
    await switched; harness.fixture.detectChanges(); await inspect();
    await page.cancelPerformance(72); harness.fixture.detectChanges();
    expect(harness.routeNativeElement!.textContent).not.toContain('No comparison was reconstructed');
    await page.showPerformance(72); harness.fixture.detectChanges(); await inspect();
    const refreshed = page.loadPerformance(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement!.querySelector('app-project-crux-history')).toBeNull();
    await refreshed; await page.showPerformance(72); harness.fixture.detectChanges();
    let resolve!: (value: ApiResult) => void;
    api.cruxHandler = () => new Promise(done => resolve = done);
    click(); harness.fixture.detectChanges(); expect(api.cruxInspections.at(-1)).toEqual([7, 9, 75]);
    await harness.navigateByUrl('/app/onboarding/7/10'); harness.fixture.detectChanges();
    resolve({ status: 200, body: { message: 'PRIVATE old project source' } });
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement!.querySelector('app-project-crux-history')).toBeNull();
    expect(harness.routeNativeElement!.textContent).not.toContain('PRIVATE');
  });

  it.each(['en', 'tr'] as const)('clears a different source’s sync and coverage evidence while new requests are pending or fail (%s)', async (language) => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    api.sourcesHandler = (_org, projectId) => Promise.resolve({ status: 200, body: {
      project_id: projectId, has_more: false, sources: [8, 9].map((id) => ({
        id, provider: 'google_search_console', property: `https://source-${id}.example`, state: 'active',
        scope_current: true, csv_import_supported: false, oauth_available: true, api_sync_available: true,
        coverage_available: true, credential_status: 'reference_reserved', sync: null, latest_import: null,
      })),
    } });
    api.syncStatusHandler = (projectId, connectionId) => Promise.resolve({ status: 200, body: {
      project_id: projectId, connection_id: connectionId,
      job: { id: 81, status: 'succeeded', error_category: '', pages_recorded: 1,
        requests_attempted: 2, source_coverage: 'top_rows_only' },
    } });
    api.coverageStatusHandler = (projectId, connectionId) => Promise.resolve({ status: 200, body: {
      project_id: projectId, connection_id: connectionId,
      job: { id: 82, status: 'succeeded', error_category: '', inspection_url: 'https://source-8.example/old',
        requests_attempted: 3, sources_recorded: ['sitemaps'], results: [{ source: 'sitemaps',
          result: { sitemaps: [{ url: 'https://source-8.example/old-sitemap' }] } }] },
    } });
    await harness.navigateByUrl('/app/onboarding/7/9');
    await harness.fixture.whenStable();
    const onboarding = harness.routeDebugElement!.componentInstance;
    await onboarding.refreshSync(8);
    await onboarding.refreshCoverage(8);
    harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    expect(root.textContent).toContain(language === 'tr' ? 'İş 81: succeeded' : 'Job 81: succeeded');
    expect(root.textContent).toContain('source-8.example/old-sitemap');

    let rejectSync!: (error: Error) => void;
    let rejectCoverage!: (error: Error) => void;
    vi.spyOn(api, 'startSearchConsoleSync').mockImplementationOnce(() => new Promise((_, reject) => { rejectSync = reject; }));
    vi.spyOn(api, 'startSearchConsoleCoverage').mockImplementationOnce(() => new Promise((_, reject) => { rejectCoverage = reject; }));
    const syncForm = root.querySelector<HTMLFormElement>('#sync-day-9')!.closest('form')!;
    syncForm.querySelector<HTMLInputElement>('input[name="day"]')!.value = '2026-09-20';
    syncForm.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    const coverageForm = root.querySelector<HTMLFormElement>('#coverage-url-9')!.closest('form')!;
    coverageForm.querySelector<HTMLInputElement>('input[name="inspection_url"]')!.value = 'https://source-9.example/page';
    coverageForm.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    harness.fixture.detectChanges();
    expect(root.textContent).not.toContain(language === 'tr' ? 'İş 81:' : 'Job 81:');
    expect(root.textContent).not.toContain('source-8.example/old-sitemap');
    expect(root.textContent).not.toContain(language === 'tr' ? 'Bu eşitlemeyi iptal et' : 'Cancel this sync');
    expect(root.textContent).not.toContain(language === 'tr' ? 'Kapsam isteğini iptal et' : 'Cancel coverage request');
    rejectSync(new Error('unknown sync outcome'));
    rejectCoverage(new Error('unknown coverage outcome'));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(root.textContent).not.toContain(language === 'tr' ? 'İş 81:' : 'Job 81:');
    expect(root.textContent).not.toContain('source-8.example/old-sitemap');
    expect(root.querySelector('[role="alert"]')?.getAttribute('lang')).toBe(language);
    expect(root.querySelector('[role="alert"]')?.textContent).toContain(language === 'tr' ? 'isteğinin sonucu bilinmiyor' : 'request outcome is unknown');
  });

  it.each(['en', 'tr'] as const)('sets up and uploads local CSV with explicit metadata and clears the native file input (%s)', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    api.sourcesHandler = (_org, projectId) => Promise.resolve({ status: 200, body: { project_id: projectId, has_more: false,
      sources: [{ id: 5, provider: 'google_search_console', property: 'https://onboarding.example', state: 'active', scope_current: true,
        csv_import_supported: true, oauth_available: false, api_sync_available: false, credential_status: 'not_connected', sync: null, latest_import: null },
        { id: 6, provider: 'google_search_console', property: 'https://onboarding.example', state: 'active', scope_current: true,
          csv_import_supported: false, oauth_available: true, api_sync_available: true, credential_status: 'reference_reserved', sync: null, latest_import: null }] } });
    const harness = await RouterTestingHarness.create('/app/onboarding/7/9'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance as ProjectOnboarding;
    const root = harness.routeNativeElement!;
    const setup = root.querySelector<HTMLSelectElement>('#csv-property')!.form!;
    const create = vi.spyOn(api, 'createCsvSource');
    await component.createCsvSource({ preventDefault() {}, target: setup } as unknown as SubmitEvent);
    expect(create).toHaveBeenCalledWith(7, 9, 'https://onboarding.example'); harness.detectChanges();
    expect(setup.getAttribute('lang')).toBe(language);
    expect(root.querySelector('.form-status[role="status"]')?.getAttribute('lang')).toBe(language);
    expect(setup.querySelector('button')?.textContent).toContain(language === 'tr' ? 'Yerel CSV kaynağını kur' : 'Set up local CSV source');
    const form = root.querySelector<HTMLInputElement>('#csv-file-5')!.form!;
    expect(form.getAttribute('lang')).toBe(language);
    expect(form.querySelector('label')?.textContent).toBe(language === 'tr' ? 'CSV dosyası' : 'CSV file');
    const file = new File(['private fixture'], 'private-name.csv');
    Object.defineProperty(file, 'arrayBuffer', { value: async () => new TextEncoder().encode('private fixture').buffer });
    Object.defineProperty(form.querySelector('input[type=file]'), 'files', { value: [file] });
    const fields = new FormData(); fields.set('file', file); fields.set('start', '2026-09-01'); fields.set('end', '2026-09-07');
    fields.set('search_type', 'web'); fields.set('date_granularity', 'range'); fields.set('authorize', 'on');
    vi.spyOn(form, 'reportValidity').mockReturnValue(true);
    const reset = vi.spyOn(form, 'reset'); const upload = vi.spyOn(api, 'uploadSearchConsoleCsv');
    const data = vi.spyOn(globalThis, 'FormData').mockImplementation(function () { return fields; });
    vi.stubGlobal('crypto', webcrypto);
    try {
      await component.uploadCsv({ preventDefault() {}, target: form } as unknown as SubmitEvent, 5);
      expect(upload).toHaveBeenCalledTimes(1); expect(upload.mock.calls[0].slice(0, 3)).toEqual([7, 9, 5]);
      expect(upload.mock.calls[0][4]).toEqual({ 'X-CSV-Start': '2026-09-01', 'X-CSV-End': '2026-09-07',
        'X-CSV-Search-Type': 'web', 'X-CSV-Date-Granularity': 'range', 'X-CSV-Authorization': 'true' });
      expect(reset).toHaveBeenCalled(); expect(component.pendingCsv()).toBeNull();
      expect(component.message()).toContain('CSV job 81 acknowledged'); harness.detectChanges();
      expect(root.textContent).not.toContain('private fixture'); expect(root.textContent).not.toContain(file.name);
      expect(root.textContent).toContain(language === 'tr' ? 'Dışa aktarımın tamlığı ve gizli satırlar bilinmiyor' : 'Export completeness and hidden rows remain unknown');
      expect(root.querySelector('.form-status[role="status"]')?.getAttribute('lang')).toBe(language);
      expect(root.querySelector('.form-status[role="status"] span[lang="en"]')?.textContent).toBe('queued');
      expect(root.textContent).toContain(language === 'tr' ? 'CSV işi onaylandı: 81' : 'CSV job acknowledged: 81');
      expect(root.textContent).toContain(language === 'tr' ? 'Dışa aktarım kapsamı bilinmiyor' : 'Export coverage remains unknown');
      data.mockRestore();
      const schedule = root.querySelector<HTMLSelectElement>('#schedule-grain-6')!.form!;
      const scheduled = vi.spyOn(api, 'createSearchConsoleSchedule');
      await component.createSchedule({ preventDefault() {}, currentTarget: schedule } as unknown as SubmitEvent, 6);
      harness.detectChanges();
      expect(scheduled).toHaveBeenCalledWith(7, 9, 6, 'query', expect.any(String));
      expect(root.textContent).toContain(language === 'tr' ? 'Günlük rapor zamanlaması oluşturuldu ancak duraklatıldı' : 'Daily report schedule created but paused');
      expect(root.textContent).not.toContain(language === 'tr' ? 'CSV işi onaylandı' : 'CSV job acknowledged');
      expect(root.querySelector('.form-status[role="status"]')?.getAttribute('lang')).toBe(language);
      await harness.navigateByUrl('/app/onboarding/7/0'); harness.detectChanges();
      expect(component.csvAcknowledgment()).toBeNull(); expect(component.message()).toBe('');
      expect(root.textContent).not.toContain(language === 'tr' ? 'Günlük rapor zamanlaması oluşturuldu ancak duraklatıldı' : 'Daily report schedule created but paused');
      expect(root.textContent).not.toContain('CSV job 81');
      expect(root.textContent).not.toContain(language === 'tr' ? 'CSV işi onaylandı' : 'CSV job acknowledged');
    } finally { data.mockRestore(); vi.unstubAllGlobals(); }
  });

  it('freezes uncertain CSV uploads for explicit identical retry and ignores late prior-project acknowledgment', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const harness = await RouterTestingHarness.create('/app/onboarding/7/9'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance as ProjectOnboarding;
    const frozen = { connectionId: 5, file: new Blob(['private fixture']), checksum: createHash('sha256').update('private fixture').digest('hex'),
      headers: { 'X-CSV-Start': '2026-09-01', 'X-CSV-End': '2026-09-07', 'X-CSV-Search-Type': 'web',
        'X-CSV-Date-Granularity': 'range', 'X-CSV-Authorization': 'true' } };
    component.pendingCsv.set(frozen);
    const upload = vi.spyOn(api, 'uploadSearchConsoleCsv').mockRejectedValueOnce(new Error('network'));
    await component.retryCsvUpload(); expect(component.pendingCsv()).toBe(frozen); expect(component.error()).toContain('unknown');
    harness.detectChanges(); expect(harness.routeNativeElement!.textContent).toContain('Retry same CSV request');
    upload.mockResolvedValueOnce({ status: 202, body: { project_id: 99 } });
    await component.retryCsvUpload(); expect(component.pendingCsv()).toBe(frozen);
    await component.retryCsvUpload(); expect(component.pendingCsv()).toBeNull();
    for (const call of upload.mock.calls) { expect(call[3]).toBe(frozen.file); expect(call[4]).toBe(frozen.headers); }
    component.pendingCsv.set(frozen); let finish!: (result: ApiResult) => void;
    upload.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const late = component.retryCsvUpload();
    const original = api.onboardingResult.body;
    api.onboardingLoadHandler = (_org, projectId) => Promise.resolve({ status: 200, body: {
      project: { ...original['project'] as object, id: projectId, role: 'viewer' },
      configuration: { ...original['configuration'] as object, project_id: projectId } } });
    await harness.navigateByUrl('/app/onboarding/7/10');
    finish({ status: 202, body: { project_id: 9 } }); await late; await harness.fixture.whenStable(); harness.detectChanges();
    expect(component.pendingCsv()).toBeNull(); expect(component.message()).toBe(''); expect(component.csvAcknowledgment()).toBeNull();
    expect(harness.routeNativeElement!.querySelector('#csv-property')).toBeNull();
    await component.retryCsvUpload(); expect(upload).toHaveBeenCalledTimes(4);
  });

  it('sends Search Console CSV as a raw private CSRF-protected body without a filename', async () => {
    const calls: { path: string; options: RequestInit }[] = [];
    const fetch = async (path: string, options: RequestInit) => {
      calls.push({ path, options }); return { status: 202, json: async () => ({}) };
    };
    const api = new AccountApi({ cookie: 'csrftoken=fixture-token', defaultView: { fetch } } as unknown as Document);
    const file = new Blob(['private fixture']);
    await api.uploadSearchConsoleCsv(7, 9, 5, file, { 'X-CSV-Authorization': 'true' });
    expect(calls).toHaveLength(2); expect(calls[0].path).toContain('/auth/session');
    expect(calls[1].path).toContain('/organizations/7/projects/9/sources/5/csv/');
    expect(calls[1].options.body).toBe(file); expect(calls[1].options.credentials).toBe('same-origin');
    expect(calls[1].options.cache).toBe('no-store');
    expect(calls[1].options.headers).toEqual({ 'X-CSV-Authorization': 'true', 'Content-Type': 'text/csv', 'X-CSRFToken': 'fixture-token' });
  });

  it.each(['en', 'tr'] as const)('labels partial CSV evidence and ignores a delayed source response from another project (%s)', async (language) => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    const configuration = api.onboardingResult.body['configuration'] as Record<string, unknown>;
    const project = api.onboardingResult.body['project'] as Record<string, unknown>;
    api.onboardingLoadHandler = (_organizationId, projectId) => Promise.resolve({ status: 200, body: {
      project: { ...project, id: projectId, name: `Project ${projectId}` },
      configuration: { ...configuration, project_id: projectId, current_step: 'source' },
    } });
    let resolveOld!: (result: ApiResult) => void;
    api.sourcesHandler = (_organizationId, projectId) => projectId === 9
      ? new Promise((resolve) => { resolveOld = resolve; })
      : Promise.resolve({ status: 200, body: { project_id: projectId, has_more: false, sources: [{
        id: 5, provider: 'google_search_console', property: 'https://current.example', state: 'active',
        scope_current: true, csv_import_supported: true, oauth_available: false, api_sync_available: false,
        credential_status: 'not_connected', sync: null,
        latest_import: { status: 'partially_succeeded', coverage_state: 'partial', date_start: '2026-09-01',
          date_end: '2026-09-05', export_shape: 'query', source_completeness: 'provider_export_unknown',
          rows_seen: 2, rows_imported: 1, row_errors: 1 },
      }] } });
    await harness.navigateByUrl('/app/onboarding/7/9');
    await harness.fixture.whenStable();
    await harness.navigateByUrl('/app/onboarding/7/10');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'partial dosya kapsamı' : 'partial file coverage');
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'Sağlayıcı dışa aktarımının tamlığı: provider_export_unknown' : 'Provider export completeness: provider_export_unknown');
    resolveOld({ status: 200, body: { project_id: 9, has_more: false, sources: [{
      id: 6, provider: 'google_search_console', property: 'https://old-private.example', state: 'active',
      scope_current: true, csv_import_supported: true, oauth_available: false, api_sync_available: false,
      credential_status: 'not_connected', sync: null,
      latest_import: null,
    }] } });
    await new Promise((resolve) => setTimeout(resolve));
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).not.toContain('old-private.example');
  });

  it.each(['en', 'tr'] as const)('reviews one property-scoped query and shows human correction history (%s)', async (language) => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = language;
    api.sourcesHandler = (_org, projectId) => Promise.resolve({ status: 200, body: {
      project_id: projectId, has_more: false, sources: [{ id: 5, provider: 'google_search_console',
        property: 'https://onboarding.example', state: 'active', scope_current: true,
        csv_import_supported: true, oauth_available: false, api_sync_available: false,
        credential_status: 'not_connected', sync: null, latest_import: null }],
    } });
    api.queriesHandler = (_org, projectId, connectionId) => Promise.resolve({ status: 200, body: {
      project_id: projectId, connection_id: connectionId, method: 'alias-boundary-v1', alias_revision: 2,
      source_completeness: 'provider_export_unknown', has_more: false, next_before: null,
      queries: [{ id: 12, query: 'Organic Ops prices', date_start: '2026-09-01', date_end: '2026-09-05',
        search_type: 'web', import_status: 'partially_succeeded', default_label: 'branded', label: 'branded', review_revision: 0 }],
    } });
    await harness.navigateByUrl('/app/onboarding/7/9');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    const button = (text: string) => Array.from(root.querySelectorAll('button')).find((item) => item.textContent === text)!;
    button(language === 'tr' ? 'Bu CSV kaynağını devre dışı bırak' : 'Disable this CSV source').click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(root.textContent).toContain(language === 'tr' ? 'Önceki içe aktarma kanıtları kullanılabilir' : 'Prior import evidence remains available');
    button(language === 'tr' ? 'Bu CSV kaynağını yeniden etkinleştir' : 'Re-enable this CSV source').click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.csvStateChanges).toEqual([false, true]);
    button(language === 'tr' ? 'CSV içe aktarma geçmişini görüntüle' : 'View CSV import history').click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(root.textContent).toContain(language === 'tr' ? 'Seçilen mülk için CSV içe aktarma geçmişi' : 'CSV import history for selected property');
    expect(root.textContent).toContain(language === 'tr' ? '1 / 2 satır' : '1 of 2 rows');
    expect(root.querySelector('#import-history-title')?.closest('[lang]')?.getAttribute('lang')).toBe(language);
    expect(root.querySelector('[aria-labelledby="import-history-title"] span[lang="en"]')?.textContent).toBe('query');
    const component = harness.routeDebugElement!.componentInstance as ProjectOnboarding;
    const history = vi.spyOn(api, 'sourceImportHistory');
    let finish!: (result: ApiResult) => void;
    history.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const loading = component.showImportHistory(5); harness.detectChanges();
    expect(root.textContent).toContain(language === 'tr' ? 'CSV içe aktarma geçmişi yükleniyor' : 'Loading CSV import history');
    expect(root.textContent).not.toContain(language === 'tr' ? '1 / 2 satır' : '1 of 2 rows');
    finish({ status: 403, body: {} }); await loading; harness.detectChanges();
    expect(root.textContent).toContain(language === 'tr' ? 'İçe aktarma geçmişi kullanılamıyor' : 'Import history is unavailable');
    history.mockResolvedValueOnce({ status: 200, body: { project_id: 9, connection_id: 5, imports: [], has_more: false } });
    await component.showImportHistory(5); harness.detectChanges();
    expect(root.textContent).toContain(language === 'tr' ? 'tamamlanmış CSV içe aktarma kaydı yok' : 'No completed CSV imports');
    history.mockRestore();
    button(language === 'tr' ? 'Bu mülkün sorgularını incele' : 'Review queries for this property').click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(root.textContent).toContain('Organic Ops prices');
    expect(root.textContent).toContain(language === 'tr' ? 'sağlayıcı dışa aktarımının tamlığı bilinmiyor' : 'provider export completeness is unknown');
    expect(root.querySelector('#source-queries-title')?.closest('[lang]')?.getAttribute('lang')).toBe(language);
    expect(root.querySelector('[aria-labelledby="source-queries-title"] strong[lang=""]')?.textContent).toBe('Organic Ops prices');
    const filter = root.querySelector<HTMLSelectElement>('#source-query-label-filter')!;
    expect(filter.options[1].textContent).toBe(language === 'tr' ? 'Markalı' : 'Branded');
    filter.value = 'non_branded'; filter.dispatchEvent(new Event('change')); harness.detectChanges();
    expect(root.textContent).not.toContain('Organic Ops prices');
    filter.value = 'all'; filter.dispatchEvent(new Event('change')); harness.detectChanges();
    root.querySelector<HTMLSelectElement>('#brand-label-12')!.value = 'unclassified';
    root.querySelector<HTMLInputElement>('#brand-reason-12')!.value = 'Ambiguous mention';
    root.querySelector<HTMLSelectElement>('#brand-label-12')!.form!.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.brandReviews).toEqual([{ queryId: 12, revision: 0, label: 'unclassified', reason: 'Ambiguous mention' }]);
    expect(root.textContent).toContain(language === 'tr' ? 'inceleme sürümü 1' : 'revision 1');
    expect(root.querySelector('.form-status[role="status"]')?.getAttribute('lang')).toBe(language);
    expect(root.textContent).toContain(language === 'tr' ? 'Sorgu düzeltmesi inceleme geçmişiyle birlikte kaydedildi' : 'Query correction saved with its review history');
    const historyButton = Array.from(root.querySelectorAll('button')).find((item) => item.textContent === (language === 'tr' ? 'İnceleme geçmişi' : 'Review history'))!;
    historyButton.click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(root.textContent).toContain('Ambiguous mention');
    expect(root.querySelector('ol[aria-label] span[lang="en"]')?.textContent).toBe('unclassified');
    expect(root.querySelector('ol[aria-label] span[lang=""]')?.textContent).toBe('Ambiguous mention');
    const review = vi.spyOn(api, 'reviewSourceQuery').mockResolvedValueOnce({ status: 409, body: {} });
    const form = root.querySelector<HTMLInputElement>('#brand-reason-12')!.form!;
    form.querySelector<HTMLInputElement>('input[name="reason"]')!.value = 'Human retry';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.detectChanges();
    expect(root.textContent).toContain(language === 'tr' ? 'Bu sorgu başka bir yerde incelendi' : 'This query was reviewed elsewhere');
    expect(root.querySelector('[role="alert"].form-status')?.getAttribute('lang')).toBe(language);
    await new Promise(resolve => setTimeout(resolve));
    expect(document.activeElement).toBe(root.querySelector('[role="alert"].form-status'));
    expect(root.textContent).toContain('unclassified'); review.mockRestore();
  });

  it('rejects array default and reviewed query brand labels while preserving scalar source observations', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.sourcesHandler = (_org, projectId) => Promise.resolve({ status: 200, body: { project_id: projectId, has_more: false,
      sources: [{ id: 5, provider: 'google_search_console', property: 'https://onboarding.example', state: 'active', scope_current: true,
        csv_import_supported: true, oauth_available: false, api_sync_available: false, credential_status: 'not_connected', sync: null, latest_import: null }] } });
    const original = { id: 12, query: 'Organic Ops prices', date_start: '2026-09-01', date_end: '2026-09-05', search_type: 'web',
      import_status: 'partially_succeeded', default_label: 'branded', label: 'branded', review_revision: 0 };
    let row: Record<string, unknown> = original;
    api.queriesHandler = (_org, projectId, connectionId) => Promise.resolve({ status: 200, body: { project_id: projectId, connection_id: connectionId,
      method: 'alias-boundary-v1', alias_revision: 2, source_completeness: 'provider_export_unknown', queries: [row], has_more: false, next_before: null } });
    const harness = await RouterTestingHarness.create('/app/onboarding/7/9'); await harness.fixture.whenStable();
    const component = harness.routeDebugElement!.componentInstance;
    component.showQueries(5); await harness.fixture.whenStable(); expect(component.queries()).toHaveLength(1);
    for (const field of ['default_label', 'label']) for (const label of ['branded', 'non_branded', 'unclassified']) {
      row = { ...original, [field]: [label] }; component.showQueries(5); await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(component.queryError()).toBe(true); expect(component.queries()).toEqual([]);
      expect(harness.routeNativeElement?.querySelector('#brand-label-12')).toBeNull();
      row = { ...original, [field]: label }; component.showQueries(5); await harness.fixture.whenStable();
      expect(component.queryError()).toBe(false); expect(component.queries()).toHaveLength(1); expect(component.queries()[0][field]).toBe(label);
    }
    expect(api.brandReviews).toEqual([]);
  });

  it('isolates delayed onboarding loads and saves across direct project route changes', async () => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const base = api.onboardingResult.body['configuration'] as Record<string, unknown>;
    let resolveOldLoad!: (result: ApiResult) => void;
    api.onboardingLoadHandler = (_organizationId, projectId) => projectId === 9
      ? new Promise((resolve) => { resolveOldLoad = resolve; })
      : Promise.resolve({ status: 200, body: {
        project: { id: projectId, organization_id: 7, name: `Project ${projectId}`, canonical_origin: `https://project-${projectId}.example`, aliases: [], access_restricted: false, role: 'owner' },
        configuration: { ...base, project_id: projectId, canonical_origin: `https://project-${projectId}.example`, target_country: `Market ${projectId}` },
      } });

    await harness.navigateByUrl('/app/onboarding/7/9');
    await new Promise((resolve) => setTimeout(resolve));
    expect(typeof resolveOldLoad).toBe('function');
    await harness.navigateByUrl('/app/onboarding/7/10');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain('Project 10');
    resolveOldLoad({ status: 200, body: {
      project: { id: 9, organization_id: 7, name: 'Old private project', canonical_origin: 'https://old.example', aliases: [], access_restricted: false, role: 'owner' },
      configuration: { ...base, project_id: 9, canonical_origin: 'https://old.example', business_goal: 'old-private-marker' },
    } });
    await new Promise((resolve) => setTimeout(resolve));
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain('Project 10');
    expect(harness.routeNativeElement?.textContent).not.toContain('old-private-marker');

    let resolveOldSave!: (result: ApiResult) => void;
    api.onboardingHandler = () => new Promise((resolve) => { resolveOldSave = resolve; });
    const root = harness.routeNativeElement!;
    root.querySelector<HTMLInputElement>('#target-country')!.value = 'Ten';
    root.querySelector<HTMLTextAreaElement>('#target-languages')!.value = 'en';
    root.querySelector<HTMLTextAreaElement>('#business-goal')!.value = 'Ten goal';
    root.querySelector<HTMLInputElement>('#target-country')!.form!.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    harness.fixture.detectChanges();
    expect(root.textContent).toContain('Saving project setup');
    await harness.navigateByUrl('/app/onboarding/7/11');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain('Project 11');
    resolveOldSave({ status: 200, body: { configuration: {
      ...base, project_id: 10, canonical_origin: 'https://project-10.example', target_country: 'old-save-marker', revision: 1,
    } } });
    await new Promise((resolve) => setTimeout(resolve));
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain('Project 11');
    expect(harness.routeNativeElement?.textContent).not.toContain('old-save-marker');
  });

  it('rejects a mismatched onboarding response scope', async () => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.onboardingResult = { status: 200, body: {
      ...api.onboardingResult.body,
      project: { ...(api.onboardingResult.body['project'] as object), organization_id: 99 },
    } };
    await harness.navigateByUrl('/app/onboarding/7/9');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain('Project onboarding is temporarily unavailable');
    expect(harness.routeNativeElement?.querySelector('#target-country')).toBeFalsy();
  });

  it('polls active and waiting-provider jobs until terminal, then clears denied detail', async () => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.projectsResult = { status: 200, body: {
      organization: { id: 7, name: 'Owner organization', role: 'owner' },
      projects: [{ id: 9, name: 'Monitored project', organization_id: 7 }],
    } };
    let requests = 0;
    api.jobDetailsHandler = () => {
      const status = ++requests === 1 ? 'running' : requests === 2 ? 'waiting_provider' : 'partially_succeeded';
      return Promise.resolve({ status: 200, body: { job: {
        id: 3, project_id: 9, status, progress_percent: status === 'running' ? 50 : 100,
        error_category: '', retry_of: null, cancel_requested: false, updated_at: '2026-09-24T10:00:00Z',
        steps: [], output: status === 'partially_succeeded' ? { partial: true } : {},
      } } });
    };
    await harness.navigateByUrl('/app/jobs/7/9/3');
    await new Promise((resolve) => setTimeout(resolve, 4300));
    harness.fixture.detectChanges();
    expect(requests).toBe(3);
    expect(harness.routeNativeElement?.textContent).toContain('partially succeeded');
    expect(harness.routeNativeElement?.textContent).toContain('Structured diagnostic output');
    api.jobDetailsHandler = () => Promise.resolve({ status: 404, body: {} });
    harness.routeNativeElement!.querySelector<HTMLButtonElement>('button')!.click();
    await new Promise((resolve) => setTimeout(resolve));
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain('Job access changed');
    expect(harness.routeNativeElement?.textContent).not.toContain('Structured diagnostic output');
  });

  it('clears old project job evidence and ignores delayed responses after scope change', async () => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.projectsResult = { status: 200, body: {
      organization: { id: 7, name: 'Organization', role: 'owner' },
      projects: [{ id: 9, name: 'First site', organization_id: 7 }],
    } };
    let resolveOld!: (result: ApiResult) => void;
    api.jobDetailsHandler = () => new Promise((resolve) => { resolveOld = resolve; });
    await harness.navigateByUrl('/app/jobs/7/9/3');
    await new Promise((resolve) => setTimeout(resolve));
    harness.fixture.detectChanges();
    expect(typeof resolveOld).toBe('function');
    api.projectsResult = { status: 200, body: {
      organization: { id: 7, name: 'Organization', role: 'owner' },
      projects: [{ id: 10, name: 'Second site', organization_id: 7 }],
    } };
    api.jobDetailsHandler = () => Promise.resolve({ status: 200, body: { job: {
      id: 4, project_id: 10, status: 'succeeded', progress_percent: 100, error_category: '',
      retry_of: null, cancel_requested: false, updated_at: '2026-09-24T10:00:00Z', steps: [], output: {},
    } } });
    await harness.navigateByUrl('/app/jobs/7/10/4');
    await new Promise((resolve) => setTimeout(resolve));
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain('Second site');
    resolveOld({ status: 200, body: { job: {
      id: 3, project_id: 9, status: 'succeeded', progress_percent: 100,
      error_category: '', retry_of: null, cancel_requested: false,
      updated_at: '2026-09-24T10:00:00Z', steps: [], output: { old_private_marker: 'must-not-render' },
    } } });
    await new Promise((resolve) => setTimeout(resolve));
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain('Second site');
    expect(harness.routeNativeElement?.textContent).not.toContain('must-not-render');
  });

  it.each(['en', 'tr'] as const)('requires owner password and recipient acceptance for ownership transfer in %s', async (language) => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    api.organizationsResult = { status: 200, body: { organizations: [{ id: 7, name: 'Owner organization', role: 'owner' }] } };
    api.teamResult = { status: 200, body: {
      members: [{ id: 4, email: 'new-owner@example.com', role: 'member', project_ids: [] }], invitations: [],
    } };
    await harness.navigateByUrl('/app');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    expect(root.querySelector<HTMLSelectElement>('#transfer-member option[value="4"]')).toBeTruthy();
    root.querySelector<HTMLSelectElement>('#transfer-member')!.value = '4';
    root.querySelector<HTMLInputElement>('#transfer-password')!.value = 'current password';
    const component = harness.routeDebugElement!.componentInstance as Overview;
    const password = root.querySelector<HTMLInputElement>('#transfer-password')!, member = root.querySelector<HTMLSelectElement>('#transfer-member')!;
    const auth = vi.spyOn(api, 'reauthenticate');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(root.querySelector('#transfer-password')).toBe(password); expect(password.value).toBe('current password');
    expect(root.querySelector('#transfer-member')).toBe(member); expect(member.value).toBe('4');
    expect(auth).not.toHaveBeenCalled(); expect(api.proposedMembers).toEqual([]);
    component.productLanguage.set(language); harness.fixture.detectChanges();
    root.querySelector<HTMLInputElement>('#transfer-password')!.form!.dispatchEvent(
      new SubmitEvent('submit', { bubbles: true, cancelable: true }),
    );
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.proposedMembers).toEqual([4]); expect(auth).toHaveBeenLastCalledWith('current password');
    api.organizationsResult = { status: 200, body: { organizations: [{ id: 7, name: 'Owner organization', role: 'member' }] } };
    api.transferResult = { status: 200, body: {
      transfer: { id: 12, from_email: 'old-owner@example.com', to_email: 'new-owner@example.com' },
    } };
    await (harness.routeDebugElement!.componentInstance as Overview).loadOrganizations(7);
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    root.querySelector<HTMLInputElement>('#accept-transfer-password')!.value = 'current password';
    const acceptance = root.querySelector<HTMLInputElement>('#accept-transfer-password')!;
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(root.querySelector('#accept-transfer-password')).toBe(acceptance); expect(acceptance.value).toBe('current password');
    expect(root.querySelector<HTMLInputElement>('#cancel-transfer-password')?.form?.querySelector('button')?.textContent).toContain(language === 'tr' ? 'Decline transfer' : 'Devri reddedin');
    expect(api.acceptedTransfers).toEqual([]);
    component.productLanguage.set(language); harness.fixture.detectChanges();
    root.querySelector<HTMLInputElement>('#accept-transfer-password')!.form!.dispatchEvent(
      new SubmitEvent('submit', { bubbles: true, cancelable: true }),
    );
    await harness.fixture.whenStable();
    expect(api.acceptedTransfers).toEqual([12]);
    harness.fixture.detectChanges();
    const decline = root.querySelector<HTMLInputElement>('#cancel-transfer-password')!; decline.value = 'wrong password';
    auth.mockResolvedValueOnce({ status: 403, body: {} });
    decline.form!.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges(); await new Promise(done => setTimeout(done));
    expect(api.cancelledTransfers).toEqual([]);
    expect(root.querySelector('[role="alert"]')?.textContent).toBe(language === 'tr' ? 'Yeniden kimlik doğrulama başarısız oldu. Parolanızı kontrol edip tekrar deneyin.' : 'Reauthentication failed. Check your password and try again.');
    expect(document.activeElement?.getAttribute('role')).toBe('alert');
    expect(decline.value).toBe('wrong password');
  });

  it.each(['en', 'tr'] as const)('blocks suspended organization controls and confirms a leave request in %s', async (language) => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    api.organizationsResult = { status: 200, body: { organizations: [
      { id: 7, name: 'Suspended organization', role: 'owner', is_suspended: true },
      { id: 8, name: 'Active organization', role: 'member', is_suspended: false },
    ] } };
    await harness.navigateByUrl('/app');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Kuruluş ve proje bağlamı — OrganicSEOOps' : 'Organization and project context — OrganicSEOOps');
    const root = harness.routeNativeElement!;
    expect(root.textContent).toContain(language === 'tr' ? 'Bu kuruluş askıya alındı' : 'This organization is suspended');
    expect(root.querySelector('#transfer-password')).toBeFalsy();
    expect(root.querySelector('#leave-password')).toBeFalsy();
    const selector = root.querySelector<HTMLSelectElement>('#organization-selector')!;
    selector.value = '8';
    selector.dispatchEvent(new Event('change', { bubbles: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    root.querySelector<HTMLInputElement>('#leave-password')!.value = 'current password';
    const form = root.querySelector<HTMLInputElement>('#leave-password')!.form!;
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    harness.fixture.detectChanges();
    expect(api.leftOrganizations).toEqual([]);
    const component = harness.routeDebugElement!.componentInstance as Overview;
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Organization and project context — OrganicSEOOps' : 'Kuruluş ve proje bağlamı — OrganicSEOOps');
    expect(component.pendingLeave()).toBe(true); expect(selector.value).toBe('8');
    expect(root.querySelector<HTMLInputElement>('#leave-password')!.form).toBe(form);
    expect(root.querySelector<HTMLInputElement>('#leave-password')!.value).toBe('current password');
    expect(form.querySelector('button')?.textContent).toContain(language === 'tr' ? 'Confirm leave organization' : 'Kuruluştan ayrılmayı onaylayın');
    component.productLanguage.set(language); harness.fixture.detectChanges();
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    expect(api.leftOrganizations).toEqual([8]);
  });

  it('clears tenant state while organizations reload', async () => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.organizationsResult = { status: 200, body: { organizations: [
      { id: 7, name: 'Sensitive organization', role: 'owner' },
    ] } };
    await harness.navigateByUrl('/app');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain('Sensitive organization');

    let resolveReload!: (result: ApiResult) => void;
    api.organizationsHandler = () => new Promise((resolve) => { resolveReload = resolve; });
    const reload = (harness.routeDebugElement!.componentInstance as Overview).loadOrganizations(7);
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).not.toContain('Sensitive organization');
    expect(harness.routeNativeElement?.textContent).not.toContain('Team and project access');
    resolveReload({ status: 503, body: {} });
    await reload;
  });

  it('ignores a delayed previous organization response', async () => {
    const harness = await RouterTestingHarness.create('/app');
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    await harness.fixture.whenStable();
    let resolveOld!: (result: ApiResult) => void;
    api.organizationsHandler = () => new Promise((resolve) => { resolveOld = resolve; });
    const overview = harness.routeDebugElement!.componentInstance as Overview;
    const oldRequest = overview.loadOrganizations();
    api.organizationsHandler = () => Promise.resolve({ status: 200, body: {
      organizations: [{ id: 2, name: 'Current organization', role: 'owner' }],
    } });
    await overview.loadOrganizations();
    resolveOld({ status: 200, body: {
      organizations: [{ id: 1, name: 'Stale organization', role: 'owner' }],
    } });
    await oldRequest;
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain('Current organization');
    expect(harness.routeNativeElement?.textContent).not.toContain('Stale organization');
  });

  it('clears stale project context and ignores a delayed previous organization response', async () => {
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.organizationsResult = { status: 200, body: { organizations: [
      { id: 1, name: 'First organization', role: 'owner' },
      { id: 2, name: 'Second organization', role: 'owner' },
    ] } };
    let resolveFirst!: (result: ApiResult) => void;
    api.projectsHandler = (organizationId) => organizationId === 1
      ? new Promise((resolve) => { resolveFirst = resolve; })
      : Promise.resolve({ status: 200, body: { projects: [
        {
          id: 22,
          organization_id: 2,
          name: 'Second project',
          canonical_origin: 'https://second.example',
          aliases: [],
          access_restricted: false,
          role: 'owner',
        },
      ] } });

    await harness.navigateByUrl('/app');
    await new Promise((resolve) => setTimeout(resolve));
    harness.fixture.detectChanges();
    const organization = harness.routeNativeElement!.querySelector<HTMLSelectElement>('#organization-selector')!;
    organization.value = '2';
    organization.dispatchEvent(new Event('change', { bubbles: true }));
    await new Promise((resolve) => setTimeout(resolve));
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain('Project: Second project');

    resolveFirst({ status: 200, body: { projects: [
      {
        id: 11,
        organization_id: 1,
        name: 'Stale first project',
        canonical_origin: 'https://first.example',
        aliases: [],
        access_restricted: false,
        role: 'owner',
      },
    ] } });
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain('Project: Second project');
    expect(harness.routeNativeElement?.textContent).not.toContain('Stale first project');
  });

  it.each(['en', 'tr'] as const)('keeps failed loads distinct from successful empty states and offers retry in %s', async (language) => {
    (TestBed.inject(AccountApi) as unknown as AccountApiStub).savedProductLanguage = language;
    const harness = await RouterTestingHarness.create();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.organizationsResult = { status: 503, body: {} };
    await harness.navigateByUrl('/app');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'Kuruluşlar geçici olarak kullanılamıyor' : 'Organizations are temporarily unavailable');
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'Erişiminiz değiştirilmedi' : 'Your access has not been changed');
    expect(harness.routeNativeElement?.textContent).not.toContain(language === 'tr' ? 'Kuruluşunuzu oluşturun' : 'Create your organization');

    api.organizationsResult = { status: 200, body: { organizations: 'invalid' } };
    harness.routeNativeElement?.querySelector<HTMLButtonElement>('.retry-organizations')?.click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'Kuruluşlar geçici olarak kullanılamıyor' : 'Organizations are temporarily unavailable');
    expect(harness.routeNativeElement?.textContent).not.toContain(language === 'tr' ? 'Kuruluşunuzu oluşturun' : 'Create your organization');

    api.organizationsResult = { status: 200, body: { organizations: [
      { id: 7, name: 'Recovered organization', role: 'owner' },
    ] } };
    api.projectsResult = { status: 503, body: {} };
    harness.routeNativeElement?.querySelector<HTMLButtonElement>('.retry-organizations')?.click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'Projeler geçici olarak kullanılamıyor' : 'Projects are temporarily unavailable');
    expect(harness.routeNativeElement?.textContent).not.toContain(language === 'tr' ? 'Bu kuruluşta erişilebilir proje yok' : 'No accessible projects are available');
    expect(harness.routeNativeElement?.querySelector('.retry-projects')).toBeTruthy();
  });

  it.each(['en', 'tr'] as const)('reads reset secrets from the fragment and shows invalid links safely in %s', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    const reset = vi.spyOn(api, 'resetPassword');
    const preference = vi.spyOn(api, 'productLanguage'), preferencePaths: string[] = [];
    preference.mockImplementation(() => {
      preferencePaths.push(TestBed.inject(Location).path(true));
      return Promise.resolve({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } });
    });
    const harness = await RouterTestingHarness.create('/account/reset-password#reset-secret');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe(language === 'tr' ? 'Yeni bir parola seçin' : 'Choose a new password');
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Yeni bir parola seçin — OrganicSEOOps' : 'Choose new password — OrganicSEOOps');
    expect(api.passwordResetKeys).toContain('reset-secret');
    expect(preferencePaths).toEqual(['/account/reset-password']);
    expect(TestBed.inject(Location).path(true)).toBe('/account/reset-password');
    expect(document.body.textContent).not.toContain('reset-secret');
    const root = harness.routeNativeElement!, component = harness.routeDebugElement!.componentInstance as ResetPassword;
    const password = root.querySelector<HTMLInputElement>('#new-password')!, confirmation = root.querySelector<HTMLInputElement>('#new-password-confirm')!;
    const form = root.querySelector('form')!;
    expect(root.querySelector('section')?.getAttribute('lang')).toBe(language);
    expect(root.querySelector('label')?.textContent).toBe(language === 'tr' ? 'Yeni parola' : 'New password');
    expect(root.textContent).toContain(language === 'tr' ? 'mevcut tüm oturumları kapatır' : 'signs out every existing session');
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true })); expect(reset).not.toHaveBeenCalled();
    password.value = 'New-password-123'; confirmation.value = 'Different-password-123';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true })); harness.fixture.detectChanges();
    await new Promise((resolve) => setTimeout(resolve));
    expect(confirmation.getAttribute('aria-invalid')).toBe('true');
    expect(confirmation.getAttribute('aria-describedby')).toBe('reset-password-confirm-error');
    expect(root.querySelector('#reset-password-confirm-error')?.textContent).toBe(language === 'tr' ? 'Parola doğrulaması eşleşmiyor.' : 'The password confirmation does not match.');
    expect(document.activeElement).toBe(confirmation);
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Choose new password — OrganicSEOOps' : 'Yeni bir parola seçin — OrganicSEOOps');
    expect(root.querySelector('#reset-password-confirm-error')?.textContent).toBe(language === 'tr' ? 'The password confirmation does not match.' : 'Parola doğrulaması eşleşmiyor.');
    expect(password.value).toBe('New-password-123'); expect(confirmation.value).toBe('Different-password-123');
    expect(api.passwordResetKeys).toEqual(['reset-secret']); expect(reset).not.toHaveBeenCalled(); component.productLanguage.set(language);
    confirmation.value = password.value; confirmation.dispatchEvent(new Event('input', { bubbles: true })); harness.fixture.detectChanges();
    expect(root.querySelector('#reset-password-confirm-error')).toBeNull();
    let resolve!: (result: ApiResult) => void; reset.mockImplementationOnce(() => new Promise(done => resolve = done));
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true })); harness.fixture.detectChanges();
    expect(root.querySelector<HTMLButtonElement>('button')!.disabled).toBe(true);
    expect(root.querySelector('button')?.textContent).toBe(language === 'tr' ? 'Sıfırlanıyor…' : 'Resetting…');
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true })); expect(reset).toHaveBeenCalledTimes(1);
    resolve({ status: 503, body: { detail: 'private reset detail' } }); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(root.querySelector('[role="alert"]')?.textContent).toBe(language === 'tr' ? 'Parola sıfırlama geçici olarak kullanılamıyor. Tekrar deneyin.' : 'Password reset is temporarily unavailable. Try again.');
    expect(root.textContent).not.toContain('private reset detail'); expect(document.activeElement).toBe(root.querySelector('h1'));
    for (const result of ['transport', 401] as const) {
      if (result === 'transport') reset.mockRejectedValueOnce(new Error('private transport detail'));
      else reset.mockResolvedValueOnce({ status: result, body: {} });
      form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true })); await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(root.textContent).not.toContain('private transport detail');
    }
    expect(root.querySelector('h1')?.textContent).toBe(language === 'tr' ? 'Parola sıfırlama tamamlandı' : 'Password reset complete');
    expect(root.textContent).toContain(language === 'tr' ? 'mevcut oturumlar kapatıldı' : 'existing sessions have been signed out');
    expect(root.querySelector('form')).toBeNull(); expect(password.value).toBe('');
    expect(root.querySelector('a')?.getAttribute('href')).toBe('/account/login');
    expect(reset).toHaveBeenLastCalledWith('reset-secret', 'New-password-123');
    await harness.navigateByUrl('/account/login');
    await harness.navigateByUrl('/account/reset-password#second-reset-secret'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const second = harness.routeNativeElement!;
    second.querySelector<HTMLInputElement>('#new-password')!.value = 'New-password-123';
    second.querySelector<HTMLInputElement>('#new-password-confirm')!.value = 'New-password-123';
    reset.mockResolvedValueOnce({ status: 200, body: {} });
    second.querySelector('form')!.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect((harness.routeDebugElement!.componentInstance as ResetPassword).state()).toBe('complete');
    expect(reset).toHaveBeenLastCalledWith('second-reset-secret', 'New-password-123');
    expect(preferencePaths.at(-1)).toBe('/account/reset-password');
    await harness.navigateByUrl('/account/login'); api.passwordResetInfoResult = { status: 400, body: {} };
    await harness.navigateByUrl('/account/reset-password#replayed-secret'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'geçersiz, süresi dolmuş veya zaten kullanılmış' : 'invalid, expired, or already used');
    expect(harness.routeNativeElement?.querySelector('a')?.getAttribute('href')).toBe('/account/forgot-password');
    expect(document.body.textContent).not.toContain('replayed-secret'); preference.mockRestore();
  });

  it('keeps invalid unavailable or signed-out password-reset preference and fresh production English', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const preference = vi.spyOn(api, 'productLanguage'), reset = vi.spyOn(api, 'resetPassword');
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    const harness = await RouterTestingHarness.create();
    try {
      for (const mode of ['invalid', 'incompatible', 'signed-out', 'unavailable', 'production'] as const) {
        buildEnvironment.production = mode === 'production';
        if (mode === 'unavailable') preference.mockRejectedValue(new Error('private preference error'));
        else preference.mockResolvedValue(mode === 'signed-out' ? { status: 401, body: { detail: 'private preference error' } }
          : { status: 200, body: { language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: mode === 'incompatible' ? 'tr' : 'en', current_email_language: 'en' } });
        await harness.navigateByUrl('/account/reset-password#fallback-secret'); await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(TestBed.inject(Title).getTitle()).toBe('Choose new password — OrganicSEOOps');
        expect(harness.routeNativeElement?.querySelector('section')?.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Choose a new password');
        expect(harness.routeNativeElement?.textContent).not.toContain('private preference error');
        if (mode === 'production') expect((harness.routeDebugElement!.componentInstance as ResetPassword).productLanguage()).toBe('tr');
        expect(TestBed.inject(Location).path(true)).toBe('/account/reset-password');
        expect(document.body.textContent).not.toContain('fallback-secret'); await harness.navigateByUrl('/');
      }
      expect(reset).not.toHaveBeenCalled();
    } finally { buildEnvironment.production = production; preference.mockRestore(); }
  });

  it.each(['en', 'tr'] as const)('removes invitation tokens from browser history and reports acceptance states in %s', async (language) => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub; api.savedProductLanguage = language;
    const harness = await RouterTestingHarness.create('/account/invitation#invitation-secret');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    expect(TestBed.inject(Location).path(true)).toBe('/account/invitation');
    expect(document.body.textContent).not.toContain('invitation-secret');
    expect(api.invitationTokens).toEqual([]);
    expect(root.querySelector('section')?.getAttribute('lang')).toBe(language);
    expect(root.querySelector('button')?.textContent).toBe(language === 'tr' ? 'Daveti kabul et' : 'Accept invitation');
    expect(root.textContent).toContain(language === 'tr' ? 'deneme süresi oluşturmaz veya sıfırlamaz' : 'does not create or reset a trial');
    const component = harness.routeDebugElement!.componentInstance as Invitation;
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Kuruluş daveti — OrganicSEOOps' : 'Organization invitation — OrganicSEOOps');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Organization invitation — OrganicSEOOps' : 'Kuruluş daveti — OrganicSEOOps');
    expect(api.invitationTokens).toEqual([]);
    component.productLanguage.set(language); harness.fixture.detectChanges();
    root.querySelector<HTMLButtonElement>('button')!.click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.invitationTokens).toEqual(['invitation-secret']);
    expect(root.textContent).toContain(language === 'tr' ? 'Davet kabul edildi' : 'Invitation accepted');
    expect(root.querySelector('a')?.textContent).toBe(language === 'tr' ? 'Çalışma alanını aç' : 'Open the workspace');

    await harness.navigateByUrl('/account/login');
    api.invitationAcceptResult = { status: 410, body: {} };
    await harness.navigateByUrl('/account/invitation#expired-secret');
    harness.fixture.detectChanges();
    harness.routeNativeElement!.querySelector<HTMLButtonElement>('button')!.click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'Davet kullanılamıyor' : 'Invitation unavailable');
    expect(document.body.textContent).not.toContain('expired-secret');

    await harness.navigateByUrl('/account/login');
    api.invitationAcceptResult = { status: 403, body: { errors: [{ code: 'suspended' }] } };
    await harness.navigateByUrl('/account/invitation#paused-secret');
    harness.routeNativeElement!.querySelector<HTMLButtonElement>('button')!.click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'Kuruluş askıya alındı' : 'Organization suspended');
    expect(harness.routeNativeElement?.textContent).toContain(language === 'tr' ? 'Destek erişimi yeniden sağladıktan sonra' : 'after support restores access');
  });

  it('keeps invalid, unavailable or signed-out invitation preference and fresh production English', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const preference = vi.spyOn(api, 'productLanguage');
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    try {
      const harness = await RouterTestingHarness.create();
      for (const result of [
        { status: 200, body: { language: ['tr'], current_ui_language: 'en', current_email_language: 'en' } },
        { status: 200, body: { language: 'tr', current_ui_language: 'tr', current_email_language: 'tr' } },
        { status: 401, body: { detail: 'private preference error' } },
      ]) {
        preference.mockResolvedValue(result);
        await harness.navigateByUrl('/account/invitation#fallback-secret');
        await harness.fixture.whenStable(); harness.fixture.detectChanges();
        expect(TestBed.inject(Title).getTitle()).toBe('Organization invitation — OrganicSEOOps');
        expect(harness.routeNativeElement?.querySelector('section')?.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Join the organization');
        expect(harness.routeNativeElement?.textContent).not.toContain('private preference error');
        await harness.navigateByUrl('/account/login');
      }
      preference.mockRejectedValue(new Error('private transport error'));
      await harness.navigateByUrl('/account/invitation#fallback-secret');
      await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(TestBed.inject(Title).getTitle()).toBe('Organization invitation — OrganicSEOOps');
      expect(harness.routeNativeElement?.querySelector('section')?.getAttribute('lang')).toBe('en');
      expect(harness.routeNativeElement?.textContent).not.toContain('private transport error');
      await harness.navigateByUrl('/account/login');
      buildEnvironment.production = true;
      preference.mockResolvedValue({ status: 200, body: { language: 'tr', current_ui_language: 'en', current_email_language: 'en' } });
      await harness.navigateByUrl('/account/invitation#fallback-secret');
      await harness.fixture.whenStable(); harness.fixture.detectChanges();
      expect(TestBed.inject(Title).getTitle()).toBe('Organization invitation — OrganicSEOOps');
      expect((harness.routeDebugElement!.componentInstance as Invitation).productLanguage()).toBe('tr');
      expect(harness.routeNativeElement?.querySelector('section')?.getAttribute('lang')).toBe('en');
      expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Join the organization');
      expect(api.invitationTokens).toEqual([]);
      expect(TestBed.inject(Location).path(true)).toBe('/account/invitation');
      expect(document.body.textContent).not.toContain('fallback-secret');
    } finally { buildEnvironment.production = production; preference.mockRestore(); }
  });

  it('lists sessions and revokes another session', async () => {
    const harness = await RouterTestingHarness.create('/account/security');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    expect(root.textContent).toContain('This session');
    expect(root.textContent).toContain('Other browser');
    const revoke = root.querySelector<HTMLButtonElement>('.session-list button')!;
    expect(revoke.getAttribute('aria-label')).toContain('Other browser');
    revoke.click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    expect(api.endedSessions).toEqual([2]);
    expect(root.textContent).toContain('selected session was revoked');

    root.querySelector<HTMLButtonElement>('.danger-button')!.click();
    harness.fixture.detectChanges();
    expect(root.textContent).toContain('including this one');
    root.querySelector<HTMLButtonElement>('.danger-button')!.click();
    await harness.fixture.whenStable();
    expect(TestBed.inject(Router).url).toBe('/account/login');
  });

  it('saves a personal Turkish preference and switches only the local Security draft', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    const harness = await RouterTestingHarness.create('/account/security');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    const selector = root.querySelector<HTMLSelectElement>('#product-language')!;
    expect(selector.value).toBe('en');
    selector.value = 'tr';
    selector.form!.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.savedProductLanguage).toBe('tr');
    expect(root.querySelector('.security-card')?.getAttribute('lang')).toBe('tr');
    expect(root.querySelector('h1')?.textContent).toBe('Güvenlik ve oturumlar');
    expect(TestBed.inject(Title).getTitle()).toBe('Güvenlik ve oturumlar — OrganicSEOOps');
    expect(root.textContent).toContain('Hesap e-postaları hâlâ İngilizcedir');
    expect(root.textContent).toContain('SEO hedef dilleri ayrıdır');
    expect(root.textContent).toContain('iki dilde onay bekleniyor');
    vi.spyOn(api, 'productLanguage').mockResolvedValue({ status: 200,
      body: { language: 'tr', current_ui_language: 'en', current_email_language: 'tr' } });
    selector.form!.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(root.textContent).toContain('Önemli e-postalar yerel geliştirmede incelenmemiş Türkçe taslaklar kullanır');
    selector.value = 'en';
    vi.mocked(api.productLanguage).mockRestore();
    selector.form!.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(api.savedProductLanguage).toBe('en');
    expect(root.querySelector('.security-card')?.getAttribute('lang')).toBe('en');
    expect(root.querySelector('h1')?.textContent).toBe('Security and sessions');
    expect(TestBed.inject(Title).getTitle()).toBe('Security and sessions — OrganicSEOOps');
    expect(root.textContent).not.toContain('Türkçe Güvenlik taslağı');
  });

  it('loads the saved Turkish Security draft and retains accessible security errors and logout confirmation', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = 'tr';
    const logout = vi.spyOn(api, 'logoutAll').mockResolvedValue({ status: 500, body: { detail: 'private server text' } });
    const harness = await RouterTestingHarness.create('/account/security');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    expect(root.querySelector('.security-card')?.getAttribute('lang')).toBe('tr');
    expect(root.querySelector('h1')?.textContent).toBe('Güvenlik ve oturumlar');
    expect(TestBed.inject(Title).getTitle()).toBe('Güvenlik ve oturumlar — OrganicSEOOps');
    expect(root.querySelector('.session-list button')?.getAttribute('aria-label')).toBe('Oturumu iptal et: Other browser');
    const current = root.querySelector<HTMLInputElement>('#current-password')!;
    current.value = 'Current-fixture-password';
    root.querySelector<HTMLInputElement>('#security-new-password')!.value = 'New-fixture-password';
    const confirmation = root.querySelector<HTMLInputElement>('#security-new-password-confirm')!;
    confirmation.value = 'Different-fixture-password';
    current.form!.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    await new Promise(resolve => setTimeout(resolve));
    expect(confirmation.getAttribute('aria-describedby')).toBe('security-password-confirm-error');
    expect(confirmation.getAttribute('aria-invalid')).toBe('true');
    expect(root.querySelector('#security-password-confirm-error')?.textContent).toBe('Yeni parola ile doğrulaması eşleşmiyor.');
    expect(document.activeElement).toBe(root.querySelector('.error[role="alert"]'));
    const form = root.querySelector<HTMLSelectElement>('#product-language')!.form!;
    root.querySelector<HTMLSelectElement>('#product-language')!.value = 'en';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(root.querySelector('#security-password-confirm-error')?.textContent).toBe('The new password confirmation does not match.');
    root.querySelector<HTMLSelectElement>('#product-language')!.value = 'tr';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    root.querySelector<HTMLButtonElement>('.danger-button')!.click(); harness.fixture.detectChanges();
    expect(logout).not.toHaveBeenCalled();
    expect(root.textContent).toContain('Bu oturum dahil tüm oturumlardan çıkılsın mı?');
    root.querySelector<HTMLButtonElement>('.danger-button')!.click();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(logout).toHaveBeenCalledOnce();
    expect(TestBed.inject(Router).url).toBe('/account/security');
    expect(root.querySelector('.error[role="alert"]')?.textContent).toBe('Oturumlar hâlâ etkin olabilir. Sayfayı yenileyip tekrar deneyin.');
    expect(root.textContent).not.toContain('private server text');
  });

  it('falls back to English when the Security preference cannot be loaded or is invalid', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.savedProductLanguage = 'tr';
    const harness = await RouterTestingHarness.create('/account/security');
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(harness.routeNativeElement?.querySelector('.security-card')?.getAttribute('lang')).toBe('tr');
    const preference = vi.spyOn(api, 'productLanguage').mockRejectedValue(new Error('private transport text'));
    await (harness.routeDebugElement!.componentInstance as Security).loadLanguage();
    harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    expect(root.querySelector('.security-card')?.getAttribute('lang')).toBe('en');
    expect(root.querySelector('h1')?.textContent).toBe('Security and sessions');
    expect(TestBed.inject(Title).getTitle()).toBe('Security and sessions — OrganicSEOOps');
    expect(root.textContent).toContain('Language preference is unavailable.');
    expect(root.textContent).not.toContain('private transport text');
    preference.mockResolvedValue({ status: 200, body: { language: 'de', current_ui_language: 'en', current_email_language: 'en' } });
    root.querySelector<HTMLButtonElement>('#language-title ~ button')!.click();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(root.querySelector('#product-language')).toBeNull();
    expect(root.querySelector('.security-card')?.getAttribute('lang')).toBe('en');
    preference.mockResolvedValue({ status: 200, body: { language: 'tr', current_ui_language: 'en', current_email_language: 'en' } });
    root.querySelector<HTMLButtonElement>('#language-title ~ button')!.click();
    await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(root.querySelector<HTMLSelectElement>('#product-language')?.value).toBe('tr');
    expect(root.querySelector('.security-card')?.getAttribute('lang')).toBe('tr');
    expect(TestBed.inject(Title).getTitle()).toBe('Güvenlik ve oturumlar — OrganicSEOOps');
    let finishPreference!: (value: ApiResult) => void;
    preference.mockImplementationOnce(() => new Promise(resolve => { finishPreference = resolve; }));
    const security = harness.routeDebugElement!.componentInstance as Security;
    const pending = security.loadLanguage();
    preference.mockResolvedValue({ status: 200, body: { language: 'en', current_ui_language: 'en', current_email_language: 'en' } });
    await harness.navigateByUrl('/account/login');
    expect(TestBed.inject(Title).getTitle()).toBe('Sign in — OrganicSEOOps');
    finishPreference({ status: 200, body: { language: 'tr', current_ui_language: 'en', current_email_language: 'en' } });
    await pending; await harness.fixture.whenStable(); harness.fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe('Sign in — OrganicSEOOps');
  });

  it('keeps Security English in production while preserving the saved Turkish preference', async () => {
    const buildEnvironment = environment as { production: boolean };
    const production = buildEnvironment.production;
    buildEnvironment.production = true;
    try {
      const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
      api.savedProductLanguage = 'tr';
      const harness = await RouterTestingHarness.create('/account/security');
      await harness.fixture.whenStable(); harness.fixture.detectChanges();
      const root = harness.routeNativeElement!;
      expect(root.querySelector('.security-card')?.getAttribute('lang')).toBe('en');
      expect(root.querySelector('h1')?.textContent).toBe('Security and sessions');
    expect(TestBed.inject(Title).getTitle()).toBe('Security and sessions — OrganicSEOOps');
      expect(root.querySelector<HTMLSelectElement>('#product-language')?.value).toBe('tr');
      expect(root.textContent).not.toContain('Türkçe Güvenlik taslağı');
      expect(draftProductLanguage('tr')).toBe('en');
    } finally { buildEnvironment.production = production; }
    expect(draftProductLanguage('tr')).toBe('tr');
    expect(draftProductLanguage('de')).toBe('en');
    expect(draftProductLanguage(undefined)).toBe('en');
  });

  it('shows staff-only MFA setup and one-time recovery codes accessibly', async () => {
    const api = TestBed.inject(AccountApi) as unknown as AccountApiStub;
    api.authenticatorsResult = { status: 200, body: { data: [] } };
    const harness = await RouterTestingHarness.create('/account/security?mfa=required');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    expect(root.textContent).toContain('Set up two-factor authentication before opening Django Admin.');
    root.querySelector<HTMLButtonElement>('#mfa-title ~ button')!.click();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(root.textContent).toContain('STAFFSETUPKEY');
    root.querySelector<HTMLInputElement>('#totp-code')!.value = '123456';
    root.querySelector<HTMLInputElement>('#totp-code')!.form!.dispatchEvent(
      new SubmitEvent('submit', { bubbles: true, cancelable: true }),
    );
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    expect(api.mfaCodes).toEqual(['123456']);
    expect(root.textContent).toContain('Store these recovery codes now');
    expect(root.textContent).toContain('first-code');
    expect(root.querySelector<HTMLInputElement>('#mfa-current-password')).toBeTruthy();
  });

  it('associates and focuses password-change confirmation errors', async () => {
    const harness = await RouterTestingHarness.create('/account/security');
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    const root = harness.routeNativeElement!;
    root.querySelector<HTMLInputElement>('#current-password')!.value = 'Current-password-123';
    root.querySelector<HTMLInputElement>('#security-new-password')!.value = 'New-password-123';
    root.querySelector<HTMLInputElement>('#security-new-password-confirm')!.value = 'Different-password-123';
    root.querySelector('form')!.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    harness.fixture.detectChanges();
    await harness.fixture.whenStable();
    harness.fixture.detectChanges();
    await new Promise((resolve) => setTimeout(resolve));
    const confirmation = root.querySelector<HTMLInputElement>('#security-new-password-confirm')!;
    expect(confirmation.getAttribute('aria-invalid')).toBe('true');
    expect(confirmation.getAttribute('aria-describedby')).toBe('security-password-confirm-error');
    expect(document.activeElement?.getAttribute('role')).toBe('alert');
  });
});
