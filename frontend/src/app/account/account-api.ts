import { DOCUMENT } from '@angular/common';
import { Inject, Injectable } from '@angular/core';
import { environment } from '../../environments/environment';

export interface ApiResult {
  status: number;
  body: Record<string, unknown>;
}

export interface AIRoutingPolicyInfo {
  id: number;
  project_id: number | null;
  model_id: number;
  account_id: number;
  fallback_model_ids: number[];
  max_output_tokens: number;
  max_cost_usd: string;
  timeout_seconds: number;
  revision: number;
}

export function readAIRoutingPolicy(value: unknown): AIRoutingPolicyInfo | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  return Number.isSafeInteger(row['id']) && Number(row['id']) > 0
    && (row['project_id'] === null || Number.isSafeInteger(row['project_id']))
    && Number.isSafeInteger(row['model_id']) && Number(row['model_id']) > 0
    && Number.isSafeInteger(row['account_id']) && Number(row['account_id']) > 0
    && Array.isArray(row['fallback_model_ids']) && row['fallback_model_ids'].length <= 2
    && row['fallback_model_ids'].every((item: unknown) => Number.isSafeInteger(item) && Number(item) > 0)
    && Number.isSafeInteger(row['max_output_tokens']) && Number(row['max_output_tokens']) > 0
    && typeof row['max_cost_usd'] === 'string' && /^\d{1,3}(?:\.\d{1,6})?$/.test(row['max_cost_usd'])
    && Number.isSafeInteger(row['timeout_seconds']) && Number(row['timeout_seconds']) > 0
    && Number.isSafeInteger(row['revision']) && Number(row['revision']) > 0
    ? row as unknown as AIRoutingPolicyInfo : null;
}

export interface SessionInfo {
  id: number;
  user_agent: string;
  ip: string;
  created_at: number;
  last_seen_at?: number;
  is_current: boolean;
}

export interface AuthenticatorInfo {
  type: 'totp' | 'recovery_codes';
  created_at: number;
  last_used_at?: number;
  total_code_count?: number;
  unused_code_count?: number;
  unused_codes?: string[];
}

export interface OrganizationInfo {
  id: number;
  name: string;
  role: 'owner' | 'admin' | 'member' | 'viewer';
  is_suspended?: boolean;
  access_state?: 'unavailable' | 'pending_review' | 'active' | 'read_only' | 'suspended';
  trial?: TrialInfo | null;
}

export interface TrialInfo {
  state: 'pending_review' | 'active' | 'expired' | 'suspended';
  access_state: 'pending_review' | 'active' | 'read_only' | 'suspended';
  offer_version: string;
  started_at: string | null;
  ends_at: string | null;
  project_limit: number;
  member_limit: number;
  unit_limit: number;
  settled_units: number;
  reserved_units: number;
}

export interface OwnershipTransferInfo {
  id: number;
  from_email: string;
  to_email: string;
}

export interface ProjectInfo {
  id: number;
  organization_id: number;
  name: string;
  canonical_origin: string;
  aliases: string[];
  access_restricted: boolean;
  role: OrganizationInfo['role'];
}

export type OnboardingStep = 'basics' | 'source' | 'advanced' | 'complete';
export type OnboardingSourceChoice = 'undecided' | 'connect_search_console' | 'import_search_console' | 'skip' | 'synthetic_demo';

export interface ProjectConfigurationInfo {
  project_id: number;
  canonical_origin: string;
  target_country: string;
  target_languages: string[];
  business_goal: string;
  timezone: string;
  audience: string;
  offer: string;
  brand_voice: string;
  seed_topics: string[];
  prohibited_claims: string[];
  conversion_goals: string[];
  brand_aliases: string[];
  measurement_notes: string;
  competitor_origins: string[];
  research_allowed_origins: string[];
  research_blocked_origins: string[];
  rss_feed_urls: string[];
  crawl_page_limit: number | null;
  ignored_query_parameters: string[];
  pagination_query_parameters: string[];
  facet_query_parameters: string[];
  query_variant_limit: number;
  business_locations: string[];
  service_areas: string[];
  contact_details: string;
  business_hours: string;
  profile_urls: string[];
  local_eligibility_notes: string;
  source_choice: OnboardingSourceChoice;
  source_state: 'not_selected' | 'disconnected' | 'awaiting_import' | 'skipped' | 'synthetic_demo';
  current_step: OnboardingStep;
  revision: number;
  updated_at: string | null;
}

export interface ProjectSourceInfo {
  id: number;
  provider: string;
  property: string;
  state: 'active' | 'disconnected' | 'unavailable';
  scope_current: boolean;
  scope_kind?: 'exact_origin_url_prefix' | 'verified_domain_page_only' | 'ga4_hostname_only';
  approved_origins?: string[];
  available_api_dimensions?: string[];
  csv_import_supported: boolean;
  oauth_available: boolean;
  api_sync_available: boolean;
  coverage_available?: boolean;
  query_page_available?: boolean;
  query_page_grant_id?: number | null;
  query_page_grant_revision?: number | null;
  credential_status: 'not_connected' | 'reference_reserved';
  sync: null | { status: string; quota_state: string; coverage_start: string | null;
    coverage_end: string | null; fresh_through: string | null; error_category: string; retry_after: string | null };
  latest_import: null | {
    status: string;
    coverage_state: string;
    date_start: string;
    date_end: string;
    export_shape: string;
    source_completeness: string;
    rows_seen: number;
    rows_imported: number;
    row_errors: number;
  };
}

export interface GoogleOAuthGrantInfo {
  id: number;
  state: 'pending_selection' | 'active' | 'reconnect_required' | 'revocation_pending' | 'revoked';
  revision: number;
  verified_at: string;
  sites: { property: string; site_url: string; scope?: 'exact_origin_url_prefix' | 'verified_domain_page_only';
    approved_origins?: string[]; available_dimensions?: string[] }[];
}

export interface SourceQueryInfo {
  id: number;
  query: string;
  date_start: string;
  date_end: string;
  search_type: string;
  import_status: string;
  default_label: 'branded' | 'non_branded' | 'unclassified';
  label: 'branded' | 'non_branded' | 'unclassified';
  review_revision: number;
}

export interface TeamMemberInfo {
  id: number;
  email: string;
  role: OrganizationInfo['role'];
  project_ids: number[];
}

export interface InvitationInfo {
  id: number;
  email: string;
  role: OrganizationInfo['role'];
  state: 'pending' | 'accepted' | 'revoked';
  expires_at: string;
  project_ids: number[];
}

export interface JobStepInfo {
  sequence: number;
  name: string;
  status: string;
  progress_percent: number;
  output: Record<string, unknown>;
  error_category: string;
}

export interface JobCitationInfo {
  id: number;
  source_title: string;
  source_url: string;
  observed_at: string;
}

export interface JobInfo {
  id: number;
  project_id: number;
  status: 'queued' | 'running' | 'waiting_provider' | 'succeeded' | 'failed' | 'cancelled' | 'partially_succeeded';
  progress_percent: number;
  error_category: string;
  retry_of: number | null;
  cancel_requested: boolean;
  updated_at: string;
  output?: Record<string, unknown>;
  steps?: JobStepInfo[];
  citations?: JobCitationInfo[];
  has_more?: boolean;
}

export interface JobScheduleInfo {
  id: number;
  project_id: number;
  enabled: boolean;
  interval_minutes: number;
  next_run_at: string | null;
  last_run_at: string | null;
  skipped_occurrences: number;
  last_error_category: string;
}

@Injectable({ providedIn: 'root' })
export class AccountApi {
  constructor(@Inject(DOCUMENT) private readonly document: Document) {}

  session() {
    return this.request(`${environment.authBase}/auth/session`);
  }

  signup(email: string, password: string) {
    return this.request(`${environment.authBase}/auth/signup`, 'POST', { email, password });
  }

  login(email: string, password: string) {
    return this.request(`${environment.authBase}/auth/login`, 'POST', { email, password });
  }

  authenticateMfa(code: string) {
    return this.request(`${environment.authBase}/auth/2fa/authenticate`, 'POST', { code });
  }

  authenticators() {
    return this.request(`${environment.authBase}/account/authenticators`);
  }

  totpSetup() {
    return this.request(`${environment.authBase}/account/authenticators/totp`);
  }

  activateTotp(code: string) {
    return this.request(`${environment.authBase}/account/authenticators/totp`, 'POST', { code });
  }

  recoveryCodes() {
    return this.request(`${environment.authBase}/account/authenticators/recovery-codes`);
  }

  regenerateRecoveryCodes() {
    return this.request(`${environment.authBase}/account/authenticators/recovery-codes`, 'POST', {});
  }

  logout() {
    return this.request(`${environment.authBase}/auth/session`, 'DELETE');
  }

  requestPasswordReset(email: string) {
    return this.request(`${environment.authBase}/auth/password/request`, 'POST', { email });
  }

  passwordResetInfo(key: string) {
    return this.request(`${environment.authBase}/auth/password/reset`, 'GET', undefined, {
      'X-Password-Reset-Key': key,
    });
  }

  resetPassword(key: string, password: string) {
    return this.request(`${environment.authBase}/auth/password/reset`, 'POST', { key, password });
  }

  changePassword(currentPassword: string, newPassword: string) {
    return this.request(`${environment.apiBase}/account/change-password/`, 'POST', {
      current_password: currentPassword,
      new_password: newPassword,
    });
  }

  reauthenticate(password: string) {
    return this.request(`${environment.authBase}/auth/reauthenticate`, 'POST', { password });
  }

  requestEmailChange(email: string) {
    return this.request(`${environment.authBase}/account/email`, 'POST', { email });
  }

  sessions() {
    return this.request(`${environment.authBase}/auth/sessions`);
  }

  endSessions(sessions: number[]) {
    return this.request(`${environment.authBase}/auth/sessions`, 'DELETE', { sessions });
  }

  logoutAll() {
    return this.request(`${environment.apiBase}/account/logout-all/`, 'POST', {});
  }

  productLanguage() {
    return this.request(`${environment.apiBase}/account/product-language/`);
  }

  saveProductLanguage(language: 'en' | 'tr') {
    return this.request(`${environment.apiBase}/account/product-language/`, 'POST', { language });
  }

  platformProviders() {
    return this.request(`${environment.apiBase}/platform/providers/`);
  }

  acquisitionMilestones() {
    return this.request(`${environment.apiBase}/platform/acquisition/milestones/`);
  }

  publicAnalyticsObservations() {
    return this.request(`${environment.apiBase}/platform/acquisition/public-observations/`);
  }

  trialPaidCohort(month = '') {
    return this.request(`${environment.apiBase}/platform/acquisition/trial-paid-cohorts/${month ? encodeURIComponent(month) + '/' : ''}`);
  }

  platformModels() {
    return this.request(`${environment.apiBase}/platform/models/`);
  }

  savePlatformModel(data: Record<string, unknown>) {
    return this.request(`${environment.apiBase}/platform/models/`, 'POST', data);
  }

  platformAIRouting() {
    return this.request(`${environment.apiBase}/platform/ai-routing/`);
  }

  savePlatformAIRouting(data: Record<string, unknown>) {
    return this.request(`${environment.apiBase}/platform/ai-routing/`, 'POST', data);
  }

  removePlatformAIRouting(revision: number, policyId: number) {
    return this.request(`${environment.apiBase}/platform/ai-routing/`, 'DELETE', { revision, policy_id: policyId });
  }

  platformGoogleOAuthApp() {
    return this.request(`${environment.apiBase}/platform/integrations/google-oauth-app/`);
  }

  platformGoogleAnalyticsApp() {
    return this.request(`${environment.apiBase}/platform/integrations/google-analytics-app/`);
  }

  platformGoogleBusinessApp(method: 'GET' | 'POST' | 'DELETE' = 'GET', payload?: Record<string, unknown>) {
    return this.request(`${environment.apiBase}/platform/integrations/google-business-app/`, method, payload);
  }

  platformPaddleSeller(environmentName: 'sandbox' | 'live') {
    return this.request(`${environment.apiBase}/platform/billing/paddle/${environmentName}/`);
  }

  setPlatformPaddleSeller(environmentName: 'sandbox' | 'live', data: Record<string, unknown>) {
    return this.request(`${environment.apiBase}/platform/billing/paddle/${environmentName}/`, 'POST', data);
  }

  revokePlatformPaddleSeller(environmentName: 'sandbox' | 'live') {
    return this.request(`${environment.apiBase}/platform/billing/paddle/${environmentName}/`, 'DELETE');
  }

  rotatePlatformPaddleApiKey(environmentName: 'sandbox' | 'live', apiKey: string) {
    return this.request(`${environment.apiBase}/platform/billing/paddle/${environmentName}/api-key/`,
      'POST', { api_key: apiKey });
  }

  retryPlatformPaddleReceipt(receiptId: number, reason: string) {
    return this.request(`${environment.apiBase}/platform/billing/paddle/receipts/${receiptId}/retry/`,
      'POST', { reason });
  }

  inspectPlatformPaddleReceipt(receiptId: number, reason: string) {
    return this.request(`${environment.apiBase}/platform/billing/paddle/receipts/inspect/`, 'POST',
      { receipt_id: receiptId, reason });
  }

  inspectPlatformNotice(organizationId: number, noticeId: number, reason: string) {
    return this.request(`${environment.apiBase}/platform/notices/inspect/`, 'POST',
      { organization_id: organizationId, notice_id: noticeId, reason });
  }

  retryPlatformNotice(noticeId: number, reason: string) {
    return this.request(`${environment.apiBase}/platform/notices/unknown/${noticeId}/retry/`,
      'POST', { reason, acknowledge_possible_duplicate: true });
  }

  inspectPlatformEmailFeedback(userId: number, emailAddressId: number, suppressionId: number, reason: string) {
    return this.request(`${environment.apiBase}/platform/email/suppressions/inspect/`, 'POST',
      { user_id: userId, email_address_id: emailAddressId, suppression_id: suppressionId, reason });
  }

  inspectPlatformAccountMail(userId: number, emailAddressId: number, deliveryId: number, reason: string) {
    return this.request(`${environment.apiBase}/platform/email/deliveries/inspect/`, 'POST',
      { user_id: userId, email_address_id: emailAddressId, delivery_id: deliveryId, reason });
  }

  clearPlatformEmailSuppression(id: number, reason: string) {
    return this.request(`${environment.apiBase}/platform/email/suppressions/${id}/clear/`,
      'POST', { reason, confirm_review: true });
  }

  organizationCheckout(organizationId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/billing/checkout/`);
  }

  organizationPaidObservationTiming(organizationId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/billing/first-paid/timing/`);
  }

  organizationTrialActivation(organizationId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/billing/trial/activation/`);
  }

  organizationTrialPaidTiming(organizationId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/billing/first-paid/trial-timing/`);
  }

  organizationTrialPaidWindow(organizationId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/billing/first-paid/trial-window/`);
  }

  startOrganizationCheckout(organizationId: number, requestKey: string) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/billing/checkout/`,
      'POST', { request_key: requestKey });
  }

  createOrganizationPortal(organizationId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/billing/portal/`, 'POST', {});
  }

  resolveCheckoutTransaction(transactionId: string) {
    return this.request(`${environment.apiBase}/billing/checkout/resolve/?transaction_id=${encodeURIComponent(transactionId)}`);
  }

  checkoutLinkReceipt(organizationId: number, attemptId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/billing/checkout/${attemptId}/link-receipt/`);
  }

  acknowledgeCheckoutLink(organizationId: number, attemptId: number, proof: string) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/billing/checkout/${attemptId}/link-receipt/`,
      'POST', { receipt_proof: proof, acknowledge_link_received: true });
  }

  startGA4OAuth(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/analytics/oauth/start/`,
      'POST', {});
  }

  ga4Grants(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/analytics/oauth/grants/`);
  }

  selectGA4Property(organizationId: number, projectId: number, grantId: number, propertyId: string,
    origin: string, expectedRevision: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/analytics/oauth/grants/${grantId}/select/`,
      'POST', { property_id: propertyId, origin, expected_revision: expectedRevision });
  }

  linkGA4Source(organizationId: number, projectId: number, grantId: number, expectedRevision: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/analytics/oauth/grants/${grantId}/link/`,
      'POST', { expected_revision: expectedRevision });
  }

  revokeGA4Grant(organizationId: number, projectId: number, grantId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/analytics/oauth/grants/${grantId}/revoke/`,
      'POST', {});
  }

  queueGA4Sync(organizationId: number, projectId: number, connectionId: number, day: string,
    reportKind: 'all_channels' | 'organic_search', key: string) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/analytics/sources/${connectionId}/sync/`,
      'POST', { day, report_kind: reportKind, idempotency_key: key });
  }

  ga4SyncStatus(organizationId: number, projectId: number, connectionId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/analytics/sources/${connectionId}/sync/status/`);
  }

  cancelGA4Sync(organizationId: number, projectId: number, connectionId: number, jobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/analytics/sources/${connectionId}/sync/${jobId}/cancel/`,
      'POST', {});
  }

  ga4QualityHistory(organizationId: number, projectId: number, connectionId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/analytics/sources/${connectionId}/quality/`);
  }

  saveGA4Quality(organizationId: number, projectId: number, connectionId: number, data: Record<string, unknown>) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/analytics/sources/${connectionId}/quality/reviews/`,
      'POST', data);
  }

  setPlatformGoogleOAuthApp(clientId: string, clientSecret: string, redirectUri: string) {
    return this.request(`${environment.apiBase}/platform/integrations/google-oauth-app/`, 'POST', {
      client_id: clientId, client_secret: clientSecret, redirect_uri: redirectUri,
    });
  }

  revokePlatformGoogleOAuthApp() {
    return this.request(`${environment.apiBase}/platform/integrations/google-oauth-app/`, 'DELETE');
  }

  setPlatformGoogleAnalyticsApp(clientId: string, clientSecret: string, redirectUri: string) {
    return this.request(`${environment.apiBase}/platform/integrations/google-analytics-app/`, 'POST', {
      client_id: clientId, client_secret: clientSecret, redirect_uri: redirectUri,
    });
  }

  revokePlatformGoogleAnalyticsApp() {
    return this.request(`${environment.apiBase}/platform/integrations/google-analytics-app/`, 'DELETE');
  }

  platformPerformanceKey() {
    return this.request(`${environment.apiBase}/platform/integrations/performance-key/`);
  }

  platformYouTubeKey(method: 'GET' | 'POST' | 'DELETE' = 'GET', data?: Record<string, unknown>) {
    return this.request(`${environment.apiBase}/platform/integrations/youtube-key/`, method, data);
  }

  projectYouTube(organizationId: number, projectId: number, data?: Record<string, unknown>) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/youtube-search/`, data ? 'POST' : 'GET', data);
  }

  projectBusinessProfile(organizationId: number, projectId: number, command?: Record<string, unknown>, requestKey?: string) {
    const query = requestKey ? `?request_key=${encodeURIComponent(requestKey)}` : '';
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/business-profile/${query}`,
      command ? 'POST' : 'GET', command);
  }

  visibilityPrompts(organizationId: number, projectId: number, setId = '', data?: Record<string, unknown>) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/visibility-prompts/${setId ? `${encodeURIComponent(setId)}/` : ''}`, data ? 'POST' : 'GET', data);
  }

  visibilitySamples(organizationId: number, projectId: number, jobId = 0, data?: Record<string, unknown>) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/visibility-samples/${jobId ? `${jobId}/` : ''}`, data ? 'POST' : 'GET', data);
  }

  visibilitySchedules(organizationId: number, projectId: number, scheduleId = 0, data?: Record<string, unknown>, query: Record<string, string> = {}) {
    const params = new URLSearchParams(query).toString();
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/visibility-schedules/${scheduleId ? `${scheduleId}/` : ''}${params ? `?${params}` : ''}`, data ? 'POST' : 'GET', data);
  }

  visibilityEntities(organizationId: number, projectId: number, jobId: number, data?: Record<string, unknown>) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/visibility-samples/${jobId}/entities/`, data ? 'POST' : 'GET', data);
  }

  visibilityHistory(organizationId: number, projectId: number, before: number | null = null) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/visibility-history/${before === null ? '' : `?before=${before}`}`, 'GET');
  }

  visibilityDiscoverability(organizationId: number, projectId: number, diagnostics: number | null = null) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/visibility-discoverability/${diagnostics === null ? '' : `?diagnostics=${diagnostics}`}`, 'GET');
  }

  botLogs(organizationId: number, projectId: number, jobId = 0, before: number | null = null, cancel = false) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/bot-logs/${jobId ? `${jobId}/` : before === null ? '' : `?before=${before}`}`, cancel ? 'POST' : 'GET', cancel ? {} : undefined);
  }

  yandexSyncs(organizationId: number, projectId: number, jobId = 0, before: number | null = null, cancel = false) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/yandex/sync/${jobId ? `${jobId}/` : before === null ? '' : `?before=${before}`}`, cancel ? 'POST' : 'GET', cancel ? {} : undefined);
  }

  readonly serpPendingRequests = new Map<string, string>();
  readonly repositoryPendingRequests = new Map<string, string>();

  repositoryAnalysis(organizationId: number, projectId: number, jobId = 0, data?: Record<string, unknown>, query: Record<string, string> = {}) {
    const params = new URLSearchParams(query).toString();
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/repository-analysis/${jobId ? `${jobId}/` : ''}${params ? `?${params}` : ''}`, data ? 'POST' : 'GET', data);
  }

  repositoryConnections(organizationId: number, projectId: number, before: number | null = null) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/repositories/${before === null ? '' : `?before=${before}`}`, 'GET');
  }

  repositoryConsent(organizationId: number, projectId: number, data: Record<string, unknown>) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/repositories/consent/`, 'POST', data);
  }

  repositoryDisconnect(organizationId: number, projectId: number, grantId: number, revision: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/repositories/grants/${grantId}/revoke/`, 'POST', { revision });
  }

  repositoryReportRevoked(organizationId: number, projectId: number, sourceId: number, unknown: boolean) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/repositories/${unknown ? 'consents' : 'grants'}/${sourceId}/report-revoked/`, 'POST', { remote_revocation_completed: true });
  }

  serp(organizationId: number, projectId: number, jobId = 0, data?: Record<string, unknown>, query: Record<string, string> = {}) {
    const params = new URLSearchParams(query).toString();
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/serp/${jobId ? `jobs/${jobId}/` : ''}${params ? `?${params}` : ''}`, data ? 'POST' : 'GET', data);
  }

  serpOverlap(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/serp/overlap/`, 'GET');
  }

  startYandexSync(organizationId: number, projectId: number, selection: Record<string, unknown>) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/yandex/sync/`, 'POST', selection);
  }

  reportYandexRefreshRevoked(organizationId: number, projectId: number, grantId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/yandex/grants/${grantId}/refresh-report-revoked/`, 'POST', { remote_revocation_completed: true });
  }

  yandexGrants(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/yandex/grants/`, 'GET');
  }

  reportYandexExchangeRevoked(organizationId: number, projectId: number, intentId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/yandex/exchanges/${intentId}/report-revoked/`, 'POST', { remote_revocation_completed: true });
  }

  startYandexConsent(organizationId: number, projectId: number, origin: string) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/yandex/oauth/start/`, 'POST', { origin });
  }

  revokeYandexGrant(organizationId: number, projectId: number, grantId: number, revision: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/yandex/grants/${grantId}/revoke/`, 'POST', { revision });
  }

  yandexImports(organizationId: number, projectId: number, jobId = 0, before: number | null = null, cancel = false) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/yandex/imports/${jobId ? `${jobId}/` : before === null ? '' : `?before=${before}`}`, cancel ? 'POST' : 'GET', cancel ? {} : undefined);
  }

  uploadYandex(organizationId: number, projectId: number, file: Blob, metadata: Record<string, string>) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/yandex/imports/`, 'POST', undefined,
      { ...metadata, 'Content-Type': 'text/csv' }, file);
  }

  uploadBotLogs(organizationId: number, projectId: number, file: Blob, metadata: Record<string, string>) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/bot-logs/`, 'POST', undefined,
      { ...metadata, 'Content-Type': 'application/x-ndjson' }, file);
  }

  setPlatformPerformanceKey(apiKey: string) {
    return this.request(`${environment.apiBase}/platform/integrations/performance-key/`, 'POST', { api_key: apiKey });
  }

  revokePlatformPerformanceKey() {
    return this.request(`${environment.apiBase}/platform/integrations/performance-key/`, 'DELETE');
  }

  addPlatformProvider(key: string, name: string, kind: string, baseUrl: string) {
    return this.request(`${environment.apiBase}/platform/providers/`, 'POST', {
      key, name, kind, base_url: baseUrl,
    });
  }

  addPlatformAccount(providerId: number, label: string, secret: string) {
    return this.request(`${environment.apiBase}/platform/providers/${providerId}/accounts/`, 'POST', { label, secret });
  }

  setPlatformCredential(providerId: number, accountId: number, secret: string) {
    return this.request(`${environment.apiBase}/platform/providers/${providerId}/accounts/${accountId}/credential/`,
      'POST', { secret });
  }

  revokePlatformCredential(providerId: number, accountId: number) {
    return this.request(`${environment.apiBase}/platform/providers/${providerId}/accounts/${accountId}/credential/`,
      'DELETE');
  }

  organizationProviderAccounts(organizationId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/provider-accounts/`);
  }

  projectAITextCatalog(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/ai-text/`);
  }

  projectAIRouting(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/ai-routing/`);
  }

  saveProjectAIRouting(organizationId: number, projectId: number, data: Record<string, unknown>) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/ai-routing/`,
      'POST', data);
  }

  removeProjectAIRouting(organizationId: number, projectId: number, revision: number, policyId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/ai-routing/`,
      'DELETE', { revision, policy_id: policyId });
  }

  createAIText(organizationId: number, projectId: number, data: Record<string, unknown>) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/ai-text/`,
      'POST', data);
  }

  aiTextJob(organizationId: number, projectId: number, jobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/ai-text/${jobId}/`);
  }

  projectResearch(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/research/`);
  }

  projectTopics(organizationId: number, projectId: number, snapshotId = 0, candidateIndex?: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/topics/${snapshotId ? `${snapshotId}/` : ''}${candidateIndex === undefined ? '' : `${candidateIndex}/`}`);
  }

  saveProjectTopic(organizationId: number, projectId: number, snapshotId: number, candidateIndex: number, data: Record<string, unknown>) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/topics/${snapshotId}/${candidateIndex}/`, 'POST', data);
  }

  discoverProjectTopics(organizationId: number, projectId: number, data: Record<string, unknown>) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/topics/`, 'POST', data);
  }

  projectTopicJob(organizationId: number, projectId: number, jobId: number, cancel = false) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/topics/jobs/${jobId}/`, cancel ? 'POST' : 'GET', cancel ? {} : undefined);
  }

  projectTopicReview(organizationId: number, projectId: number, reviewId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/topics/reviews/${reviewId}/`);
  }

  queueProjectResearch(organizationId: number, projectId: number, data: Record<string, unknown>) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/research/`, 'POST', data);
  }

  projectResearchJob(organizationId: number, projectId: number, jobId: number, cancel = false) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/research/${jobId}/`,
      cancel ? 'POST' : 'GET', cancel ? {} : undefined);
  }

  projectBriefs(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/briefs/`);
  }

  projectContent(organizationId: number, projectId: number, itemId = 0, before?: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/content/${itemId ? `${itemId}/` : ''}${before ? `?before=${before}` : ''}`);
  }

  saveProjectContent(organizationId: number, projectId: number, itemId: number, data: Record<string, unknown>) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/content/${itemId ? `${itemId}/` : ''}`, 'POST', data);
  }

  contentGeneration(organizationId: number, projectId: number, jobId = 0, cancel = false) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/content-generation/${jobId ? `${jobId}/` : ''}`,
      cancel ? 'POST' : 'GET', cancel ? {} : undefined);
  }

  generateProjectContent(organizationId: number, projectId: number, data: Record<string, unknown>) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/content-generation/`, 'POST', data);
  }

  createProjectBrief(organizationId: number, projectId: number, data: Record<string, unknown>) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/briefs/`, 'POST', data);
  }

  projectBrief(organizationId: number, projectId: number, briefId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/briefs/${briefId}/`);
  }

  firstProjectAudit(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/first-audit/`);
  }

  firstProjectAuditCompletion(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/first-audit/completion/`);
  }

  firstProjectAuditActionSource(organizationId: number, projectId: number, actionId: string, revision: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/first-audit/actions/${actionId}/${revision}/`);
  }

  firstProjectAuditUsefulness(organizationId: number, projectId: number, actionId?: string, revision?: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/first-audit/${actionId ? `actions/${actionId}/${revision}/usefulness/` : 'usefulness/'}`);
  }

  firstProjectAuditUsefulnessTiming(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/first-audit/usefulness/timing/`);
  }

  acknowledgeFirstProjectAuditUsefulness(organizationId: number, projectId: number, actionId: string, revision: number, proof: string) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/first-audit/actions/${actionId}/${revision}/usefulness/`,
      'POST', { receipt_proof: proof, acknowledge_useful_next_action: true });
  }

  startFirstProjectAudit(organizationId: number, projectId: number, pageLimit: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/first-audit/`, 'POST',
      { page_limit: pageLimit, idempotency_key: crypto.randomUUID().replaceAll('-', '') });
  }

  firstProjectAuditJob(organizationId: number, projectId: number, jobId: number, cancel = false) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/first-audit/${jobId}/`,
      cancel ? 'POST' : 'GET', cancel ? {} : undefined);
  }

  retryFirstProjectAudit(organizationId: number, projectId: number, jobId: number, key: string) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/first-audit/${jobId}/`,
      'POST', { idempotency_key: key });
  }

  aiTextHistory(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/ai-text/history/`);
  }

  cancelAIText(organizationId: number, projectId: number, jobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/ai-text/${jobId}/`,
      'POST', {});
  }

  addOrganizationProviderAccount(organizationId: number, providerId: number, label: string, secret: string) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/provider-accounts/`,
      'POST', { provider_id: providerId, label, secret });
  }

  setOrganizationProviderCredential(organizationId: number, accountId: number, secret: string) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/provider-accounts/${accountId}/credential/`,
      'POST', { secret });
  }

  revokeOrganizationProviderCredential(organizationId: number, accountId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/provider-accounts/${accountId}/credential/`,
      'DELETE');
  }

  organizationPerformanceKey(organizationId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/performance-key/`);
  }

  setOrganizationPerformanceKey(organizationId: number, apiKey: string) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/performance-key/`,
      'POST', { api_key: apiKey });
  }

  revokeOrganizationPerformanceKey(organizationId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/performance-key/`, 'DELETE');
  }

  organizations() {
    return this.request(`${environment.apiBase}/organizations/`);
  }

  createOrganization(name: string) {
    return this.request(`${environment.apiBase}/organizations/`, 'POST', { name });
  }

  updateOrganization(id: number, name: string) {
    return this.request(`${environment.apiBase}/organizations/${id}/`, 'PATCH', { name });
  }

  projects(organizationId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/`);
  }

  createProject(
    organizationId: number,
    name: string,
    canonicalOrigin: string,
    aliases: string[],
    accessRestricted: boolean,
  ) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/`, 'POST', {
      name,
      canonical_origin: canonicalOrigin,
      aliases,
      access_restricted: accessRestricted,
    });
  }

  updateProject(
    organizationId: number,
    projectId: number,
    details: { name: string; canonical_origin: string; aliases: string[]; access_restricted: boolean },
  ) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/`, 'PATCH', details);
  }

  projectOnboarding(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/onboarding/`);
  }

  projectSources(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/sources/`);
  }

  indexationEvidence(organizationId: number, projectId: number, crawlRunId?: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/indexation/`
      + (crawlRunId ? `?crawl_run_id=${crawlRunId}` : ''));
  }

  buildIndexationEvidence(organizationId: number, projectId: number, crawlRunId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/indexation/`,
      'POST', { crawl_run_id: crawlRunId });
  }

  performanceAudits(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/performance/`);
  }

  startPerformanceAudit(organizationId: number, projectId: number, target: string,
    grain: string, strategy: string, sources: string[], key: string) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/performance/`,
      'POST', { target, grain, strategy, sources, idempotency_key: key });
  }

  performanceAuditDetail(organizationId: number, projectId: number, jobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/performance/${jobId}/`);
  }

  projectCruxHistory(organizationId: number, projectId: number, observationId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/crux-history/${observationId}/`);
  }

  projectCruxMaterialPolicy(organizationId: number, projectId: number, observationId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/crux-history/${observationId}/material-policy/`);
  }

  cancelPerformanceAudit(organizationId: number, projectId: number, jobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/performance/${jobId}/cancel/`,
      'POST', {});
  }

  googleOAuthGrants(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/search-console/oauth/grants/`);
  }

  startGoogleOAuth(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/search-console/oauth/start/`, 'POST', {});
  }

  selectGoogleSite(organizationId: number, projectId: number, grantId: number, revision: number, siteUrl: string) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/search-console/oauth/grants/${grantId}/select/`,
      'POST', { revision, site_url: siteUrl });
  }

  revokeGoogleOAuth(organizationId: number, projectId: number, grantId: number, revision: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/search-console/oauth/grants/${grantId}/revoke/`,
      'POST', { revision });
  }

  startSearchConsoleSync(organizationId: number, projectId: number, connectionId: number,
    day: string, dimensions: string[], key: string) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/sources/${connectionId}/sync/`,
      'POST', { day, dimensions, idempotency_key: key });
  }

  searchConsoleSyncStatus(organizationId: number, projectId: number, connectionId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/sources/${connectionId}/sync/status/`);
  }

  searchConsoleQueryPages(organizationId: number, projectId: number, connectionId: number,
    data?: Record<string, unknown>, jobId?: number, requestKey?: string) {
    const query = jobId ? `?job_id=${jobId}` : requestKey ? `?request_key=${encodeURIComponent(requestKey)}` : '';
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/sources/${connectionId}/query-page/${query}`,
      data ? 'POST' : 'GET', data);
  }

  cancelSearchConsoleSync(organizationId: number, projectId: number, connectionId: number, jobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/sources/${connectionId}/sync/${jobId}/cancel/`,
      'POST', {});
  }

  startSearchConsoleBackfill(organizationId: number, projectId: number, connectionId: number,
    startDay: string, endDay: string, dimension: string, key: string) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/sources/${connectionId}/backfill/`,
      'POST', { start_day: startDay, end_day: endDay, dimension, idempotency_key: key });
  }

  searchConsoleBackfillStatus(organizationId: number, projectId: number, connectionId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/sources/${connectionId}/backfill/status/`);
  }

  cancelSearchConsoleBackfill(organizationId: number, projectId: number, connectionId: number, backfillId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/sources/${connectionId}/backfill/${backfillId}/cancel/`,
      'POST', {});
  }

  createSearchConsoleSchedule(organizationId: number, projectId: number, connectionId: number, dimension: string, key: string) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/sources/${connectionId}/sync-schedule/`,
      'POST', { dimension, idempotency_key: key });
  }

  searchConsoleScheduleStatus(organizationId: number, projectId: number, connectionId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/sources/${connectionId}/sync-schedule/status/`);
  }

  toggleSearchConsoleSchedule(organizationId: number, projectId: number, connectionId: number,
    scheduleId: number, enabled: boolean) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/sources/${connectionId}/sync-schedule/${scheduleId}/toggle/`,
      'POST', { enabled });
  }

  startSearchConsoleCoverage(organizationId: number, projectId: number, connectionId: number,
    inspectionUrl: string, key: string) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/sources/${connectionId}/coverage/`,
      'POST', { inspection_url: inspectionUrl, idempotency_key: key });
  }

  searchConsoleCoverageStatus(organizationId: number, projectId: number, connectionId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/sources/${connectionId}/coverage/status/`);
  }

  cancelSearchConsoleCoverage(organizationId: number, projectId: number, connectionId: number, jobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/sources/${connectionId}/coverage/${jobId}/cancel/`,
      'POST', {});
  }

  sourceImportHistory(organizationId: number, projectId: number, connectionId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/sources/${connectionId}/imports/`);
  }

  sourceOpportunityPreview(organizationId: number, projectId: number, connectionId: number, importId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/sources/${connectionId}/imports/${importId}/opportunities/`);
  }

  projectFindings(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/findings/`);
  }

  projectReports(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/reports/`);
  }

  projectSummaryPreference(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/summary-preference/`);
  }

  projectAlertPreference(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/alert-preference/`);
  }

  projectCruxAlertPreference(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/crux-alert-preference/`);
  }

  saveProjectCruxAlertPreference(organizationId: number, projectId: number, frequency: 'off' | 'daily', revision: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/crux-alert-preference/`,
      'POST', { frequency, expected_revision: revision });
  }

  saveProjectAlertPreference(organizationId: number, projectId: number, frequency: 'off' | 'daily',
                             sourceFamilies: ('crawl_failure' | 'integration_health')[], revision: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/alert-preference/`,
      'POST', { frequency, source_families: sourceFamilies, expected_revision: revision });
  }

  projectSummaryDeliveries(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/summary-deliveries/`);
  }

  projectAlertDeliveries(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/alert-deliveries/`);
  }

  projectCruxAlertDeliveries(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/crux-alert-deliveries/`);
  }

  projectSupportJobReference(organizationId: number, projectId: number, jobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/support-job-reference/${jobId}/`);
  }

  projectSupportRequests(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/support-requests/`);
  }

  projectSupportRequest(organizationId: number, projectId: number, requestId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/support-requests/${requestId}/`);
  }

  createProjectSupportRequest(organizationId: number, projectId: number, command: Record<string, unknown>) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/support-requests/`, 'POST', command);
  }

  projectCrawlFailures(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/crawl-failures/`);
  }

  projectIntegrationHealth(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/integration-health/`);
  }

  saveProjectSummaryPreference(organizationId: number, projectId: number, frequency: 'off' | 'weekly', revision: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/summary-preference/`,
      'POST', { frequency, expected_revision: revision });
  }

  organizationExportInventory(organizationId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/export-inventory/`);
  }

  organizationClosureStatus(organizationId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/closure-status/`);
  }

  organizationReportRepositoryConsentRevoked(organizationId: number, consentId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/closure/repository-consents/report-revoked/`,
      'POST', { consent_id: consentId, remote_revocation_completed: true });
  }

  organizationClose(organizationId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/close/`, 'POST',
      { acknowledge_irreversible: true });
  }

  organizationReconcileClosureBilling(organizationId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/closure/billing-reconcile/`,
      'POST', {});
  }

  organizationRevokePendingGrant(organizationId: number, provider: 'search_console' | 'analytics' | 'business_profile' | 'yandex' | 'repository', grantId: number, reported = false) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/closure/grants/revoke/`,
      'POST', { provider, grant_id: grantId, ...(reported ? { remote_revocation_completed: true } : {}) });
  }

  organizationCustomerRows(organizationId: number, model: string, afterId: number, throughId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/export/rows/`, 'POST',
      { model, after_id: afterId, through_id: throughId });
  }

  boundedOrganizationArchive(organizationId: number) {
    return this.requestArchive(`${environment.apiBase}/organizations/${organizationId}/export/archive/`);
  }

  captureOrganizationSnapshot(organizationId: number, format = 'bounded-zip-v1') {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/export/snapshots/`, 'POST',
      { request_key: crypto.randomUUID().replaceAll('-', ''), format });
  }

  organizationSnapshots(organizationId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/export/snapshots/`);
  }

  organizationSnapshotManifest(organizationId: number, snapshotId: number, position = 0) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/export/snapshots/${snapshotId}/?position=${position}`);
  }

  discardFailedOrganizationSnapshot(organizationId: number, snapshotId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/export/snapshots/${snapshotId}/discard/`,
      'POST', {});
  }

  async personalAccountArchive() {
    const fetcher = this.document.defaultView?.fetch.bind(this.document.defaultView);
    if (!fetcher) throw new Error('Private export requires a browser.');
    const session = await fetcher(`${environment.authBase}/auth/session`, {
      credentials: 'same-origin', cache: 'no-store',
    });
    const csrf = this.cookie('csrftoken');
    if (session.status !== 200 || !csrf) throw new Error('Reauthenticate before exporting personal data.');
    const form = this.document.createElement('form');
    form.method = 'POST'; form.action = `${environment.apiBase}/account/export/`;
    form.target = '_self'; form.hidden = true;
    const token = this.document.createElement('input');
    token.type = 'hidden'; token.name = 'csrfmiddlewaretoken'; token.value = csrf;
    form.append(token); this.document.body.append(form);
    try { form.submit(); } finally { form.remove(); }
  }

  personalClosureStatus() {
    return this.request(`${environment.apiBase}/account/closure-status/`);
  }

  closePersonalAccount() {
    return this.request(`${environment.apiBase}/account/close/`, 'POST',
      { acknowledge_restricted_identity_retention: true });
  }

  private async requestArchive(path: string) {
    const fetcher = this.document.defaultView?.fetch.bind(this.document.defaultView);
    if (!fetcher) throw new Error('Private export requires a browser.');
    await fetcher(`${environment.authBase}/auth/session`, { credentials: 'same-origin', cache: 'no-store' });
    const response = await fetcher(path, {
      method: 'POST', credentials: 'same-origin', cache: 'no-store', body: '{}',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.cookie('csrftoken') },
    });
    return { status: response.status, type: response.headers.get('Content-Type'),
      digest: response.headers.get('X-Content-SHA256'),
      blob: response.ok ? await response.blob() : null };
  }

  createProjectReport(organizationId: number, projectId: number, findingIds: number[], format: 'csv' | 'json') {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/reports/`,
      'POST', { request_key: crypto.randomUUID(), format, finding_ids: findingIds,
        action_review_ids: [], outcome_ids: [] });
  }

  projectReportShares(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/report-shares/`);
  }

  createProjectReportShare(organizationId: number, projectId: number, reportId: number,
                           recipient: string, hours: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/report-shares/`,
      'POST', { report_id: reportId, request_key: crypto.randomUUID(), intended_recipient: recipient,
        expires_hours: hours, acknowledge_link_access: true });
  }

  revokeProjectReportShare(organizationId: number, projectId: number, shareId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/report-shares/${shareId}/revoke/`,
      'POST', {});
  }

  intentClusters(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/intent-clusters/`);
  }

  intentClusterHistory(organizationId: number, projectId: number, clusterId: string) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/intent-clusters/${encodeURIComponent(clusterId)}/`);
  }

  saveIntentCluster(organizationId: number, projectId: number, data: Record<string, unknown>, clusterId?: string) {
    const suffix = clusterId ? `${encodeURIComponent(clusterId)}/` : '';
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/intent-clusters/${suffix}`,
      'POST', data);
  }

  projectActions(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/actions/`);
  }

  actionHistory(organizationId: number, projectId: number, actionId: string) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/actions/${encodeURIComponent(actionId)}/`);
  }

  saveAction(organizationId: number, projectId: number, data: Record<string, unknown>, actionId?: string) {
    const suffix = actionId ? `${encodeURIComponent(actionId)}/` : '';
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/actions/${suffix}`,
      'POST', data);
  }

  actionOutcomes(organizationId: number, projectId: number, actionId: string) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/actions/${encodeURIComponent(actionId)}/outcomes/`);
  }

  recordPageOutcome(organizationId: number, projectId: number, actionId: string,
                    connectionId: number, previousImportId: number, currentImportId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/actions/${encodeURIComponent(actionId)}/outcomes/`,
      'POST', { connection_id: connectionId, previous_import_id: previousImportId, current_import_id: currentImportId });
  }

  actionTechnicalOutcomes(organizationId: number, projectId: number, actionId: string) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/actions/${encodeURIComponent(actionId)}/technical-outcomes/`);
  }

  recordTechnicalOutcome(organizationId: number, projectId: number, actionId: string,
                         previousCrawlId: number, currentCrawlId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/actions/${encodeURIComponent(actionId)}/technical-outcomes/`,
      'POST', { previous_crawl_id: previousCrawlId, current_crawl_id: currentCrawlId });
  }

  localAssessments(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/local-assessments/`);
  }

  localFeedback(organizationId: number, projectId: number, data?: Record<string, unknown>, feedbackId?: string, requestKey?: string) {
    const suffix = feedbackId ? `${encodeURIComponent(feedbackId)}/` : '';
    const query = requestKey ? `?request_key=${encodeURIComponent(requestKey)}` : '';
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/local-feedback/${suffix}${query}`,
      data ? 'POST' : 'GET', data);
  }

  authorityLinks(organizationId: number, projectId: number, data?: Record<string, unknown>, linkId?: string, requestKey?: string) {
    const suffix = linkId ? `${encodeURIComponent(linkId)}/` : '';
    const query = requestKey ? `?request_key=${encodeURIComponent(requestKey)}` : '';
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/authority-links/${suffix}${query}`,
      data ? 'POST' : 'GET', data);
  }

  authorityLinkSources(organizationId: number, projectId: number, data?: Record<string, unknown>, jobId?: number, requestKey?: string) {
    const suffix = jobId ? `${jobId}/` : '';
    const query = requestKey ? `?idempotency_key=${encodeURIComponent(requestKey)}` : '';
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/authority-link-sources/${suffix}${query}`,
      data ? 'POST' : 'GET', data);
  }

  originVerifications(organizationId: number, projectId: number, method = 'GET', data?: Record<string, unknown>, verificationId?: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/origin-verifications/${verificationId ? `${verificationId}/` : ''}`,
      method, data);
  }

  passiveHeaders(organizationId: number, projectId: number, data?: Record<string, unknown>, jobId?: number, requestKey?: string, selection = false) {
    const suffix = selection ? 'selection/' : jobId ? `${jobId}/` : '';
    const query = requestKey ? `?idempotency_key=${encodeURIComponent(requestKey)}` : '';
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/passive-headers/${suffix}${query}`,
      data ? 'POST' : 'GET', data);
  }

  competitorRoots(organizationId: number, projectId: number, data?: Record<string, unknown>, jobId?: number, requestKey?: string, selection = false) {
    const suffix = selection ? 'selection/' : jobId ? `${jobId}/` : '';
    const query = requestKey ? `?idempotency_key=${encodeURIComponent(requestKey)}` : '';
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/competitor-roots/${suffix}${query}`,
      data === undefined ? 'GET' : 'POST', data);
  }

  competitorSchemaRoots(organizationId: number, projectId: number, data?: Record<string, unknown>, jobId?: number, requestKey?: string, selection = false) {
    const suffix = selection ? 'selection/' : jobId ? `${jobId}/` : '';
    const query = requestKey ? `?idempotency_key=${encodeURIComponent(requestKey)}` : '';
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/competitor-schema-roots/${suffix}${query}`,
      data === undefined ? 'GET' : 'POST', data);
  }

  competitorLinksRoots(organizationId: number, projectId: number, data?: Record<string, unknown>, jobId?: number, requestKey?: string, selection = false) {
    const suffix = selection ? 'selection/' : jobId ? `${jobId}/` : '';
    const query = requestKey ? `?idempotency_key=${encodeURIComponent(requestKey)}` : '';
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/competitor-links-roots/${suffix}${query}`,
      data === undefined ? 'GET' : 'POST', data);
  }

  competitorPages(organizationId: number, projectId: number, data?: Record<string, unknown>, jobId?: number, requestKey?: string, selection = false) {
    const suffix = selection ? 'selection/' : jobId ? `${jobId}/` : '';
    const query = requestKey ? `?idempotency_key=${encodeURIComponent(requestKey)}` : '';
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/competitor-pages/${suffix}${query}`,
      data === undefined ? 'GET' : 'POST', data);
  }

  competitorPageHeadings(organizationId: number, projectId: number, data?: Record<string, unknown>, jobId?: number, requestKey?: string, selection = false) {
    const suffix = selection ? 'selection/' : jobId ? `${jobId}/` : '';
    const query = requestKey ? `?idempotency_key=${encodeURIComponent(requestKey)}` : '';
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/competitor-page-headings/${suffix}${query}`,
      data === undefined ? 'GET' : 'POST', data);
  }
  competitorPageDestinations(organizationId: number, projectId: number, data?: Record<string, unknown>, jobId?: number, requestKey?: string, selection = false) {
    const suffix = selection ? 'selection/' : jobId ? `${jobId}/` : '';
    const query = requestKey ? `?idempotency_key=${encodeURIComponent(requestKey)}` : '';
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/competitor-page-destinations/${suffix}${query}`,
      data === undefined ? 'GET' : 'POST', data);
  }
  competitorPageFormats(organizationId: number, projectId: number, data?: Record<string, unknown>, jobId?: number, requestKey?: string, selection = false) {
    const suffix = selection ? 'selection/' : jobId ? `${jobId}/` : '';
    const query = requestKey ? `?idempotency_key=${encodeURIComponent(requestKey)}` : '';
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/competitor-page-formats/${suffix}${query}`,
      data === undefined ? 'GET' : 'POST', data);
  }

  competitorPageDates(organizationId: number, projectId: number, data?: Record<string, unknown>, jobId?: number, requestKey?: string, selection = false) {
    const suffix = selection ? 'selection/' : jobId ? `${jobId}/` : '';
    const query = requestKey ? `?idempotency_key=${encodeURIComponent(requestKey)}` : '';
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/competitor-page-dates/${suffix}${query}`,
      data === undefined ? 'GET' : 'POST', data);
  }
  competitorLighthouse(organizationId: number, projectId: number, data?: Record<string, unknown>, jobId?: number, requestKey?: string, selection = false) {
    const suffix = selection ? 'selection/' : jobId ? `${jobId}/` : '';
    const query = requestKey ? `?idempotency_key=${encodeURIComponent(requestKey)}` : '';
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/competitor-lighthouse/${suffix}${query}`,
      data === undefined ? 'GET' : 'POST', data);
  }

  competitorRootComparison(organizationId: number, projectId: number, previousJobId: number, currentJobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/competitor-roots/comparison/?previous_job_id=${previousJobId}&current_job_id=${currentJobId}`);
  }

  competitorLighthouseComparison(organizationId: number, projectId: number, previousJobId: number, currentJobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/competitor-lighthouse/comparison/?previous_job_id=${previousJobId}&current_job_id=${currentJobId}`);
  }

  competitorPageDatesComparison(organizationId: number, projectId: number, previousJobId: number, currentJobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/competitor-page-dates/comparison/?previous_job_id=${previousJobId}&current_job_id=${currentJobId}`);
  }

  competitorPageDateCandidates(organizationId: number, projectId: number, jobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/competitor-page-dates/${jobId}/candidates/`);
  }

  competitorPageDateCandidateComparison(organizationId: number, projectId: number, previousJobId: number, currentJobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/competitor-page-dates/candidates/comparison/?previous_job_id=${previousJobId}&current_job_id=${currentJobId}`);
  }

  competitorPageFormatsComparison(organizationId: number, projectId: number, previousJobId: number, currentJobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/competitor-page-formats/comparison/?previous_job_id=${previousJobId}&current_job_id=${currentJobId}`);
  }

  competitorPageFormatsStructure(organizationId: number, projectId: number, firstJobId: number, secondJobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/competitor-page-formats/structure/?first_job_id=${firstJobId}&second_job_id=${secondJobId}`);
  }

  competitorPageHeadingsStructure(organizationId: number, projectId: number, firstJobId: number, secondJobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/competitor-page-headings/structure/?first_job_id=${firstJobId}&second_job_id=${secondJobId}`);
  }

  competitorPageDestinationsComparison(organizationId: number, projectId: number, previousJobId: number, currentJobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/competitor-page-destinations/comparison/?previous_job_id=${previousJobId}&current_job_id=${currentJobId}`);
  }

  competitorPageDestinationInventory(organizationId: number, projectId: number, firstJobId: number, secondJobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/competitor-page-destinations/inventory/?first_job_id=${firstJobId}&second_job_id=${secondJobId}`);
  }
  competitorPageReferenceStructure(organizationId: number, projectId: number, firstJobId: number, secondJobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/competitor-page-destinations/structure/?first_job_id=${firstJobId}&second_job_id=${secondJobId}`);
  }

  competitorHeadingTopicsComparison(organizationId: number, projectId: number, firstJobId: number, secondJobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/competitor-heading-topics/comparison/?first_job_id=${firstJobId}&second_job_id=${secondJobId}`);
  }

  competitorPageHeadingsComparison(organizationId: number, projectId: number, previousJobId: number, currentJobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/competitor-page-headings/comparison/?previous_job_id=${previousJobId}&current_job_id=${currentJobId}`);
  }

  competitorPageComparison(organizationId: number, projectId: number, previousJobId: number, currentJobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/competitor-pages/comparison/?previous_job_id=${previousJobId}&current_job_id=${currentJobId}`);
  }

  competitorSchemaRootComparison(organizationId: number, projectId: number, previousJobId: number, currentJobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/competitor-schema-roots/comparison/?previous_job_id=${previousJobId}&current_job_id=${currentJobId}`);
  }

  competitorLinksRootComparison(organizationId: number, projectId: number, previousJobId: number, currentJobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/competitor-links-roots/comparison/?previous_job_id=${previousJobId}&current_job_id=${currentJobId}`);
  }

  competitorSyntheses(organizationId: number, projectId: number, data?: Record<string, unknown>, jobId?: number, requestKey?: string, selection = false) {
    const suffix = selection ? 'selection/' : jobId ? `${jobId}/` : '';
    const query = requestKey ? `?idempotency_key=${encodeURIComponent(requestKey)}` : '';
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/competitor-syntheses/${suffix}${query}`,
      data === undefined ? 'GET' : 'POST', data);
  }

  competitorHeadingTopics(organizationId: number, projectId: number, data?: Record<string, unknown>, jobId?: number, requestKey?: string, selection = false) {
    const suffix = selection ? 'selection/' : jobId ? `${jobId}/` : '';
    const query = requestKey ? `?idempotency_key=${encodeURIComponent(requestKey)}` : '';
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/competitor-heading-topics/${suffix}${query}`,
      data === undefined ? 'GET' : 'POST', data);
  }

  competitorHeadingSyntheses(organizationId: number, projectId: number, data?: Record<string, unknown>, jobId?: number, requestKey?: string, selection = false) {
    const suffix = selection ? 'selection/' : jobId ? `${jobId}/` : '';
    const query = requestKey ? `?idempotency_key=${encodeURIComponent(requestKey)}` : '';
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/competitor-heading-syntheses/${suffix}${query}`,
      data === undefined ? 'GET' : 'POST', data);
  }

  passiveHeaderCandidates(organizationId: number, projectId: number, jobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/passive-headers/${jobId}/candidates/`);
  }

  passiveHeaderFindings(organizationId: number, projectId: number, jobId: number, candidateDigest?: string) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/passive-headers/${jobId}/findings/`,
      candidateDigest === undefined ? 'GET' : 'POST', candidateDigest === undefined ? undefined : { candidate_digest: candidateDigest });
  }

  passiveHeaderPriority(organizationId: number, projectId: number, jobId: number, findingId: number, data?: Record<string, unknown>) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/passive-headers/${jobId}/findings/${findingId}/priority/`,
      data === undefined ? 'GET' : 'POST', data);
  }

  passiveTls(organizationId: number, projectId: number, data?: Record<string, unknown>, jobId?: number, requestKey?: string, selection = false) {
    const suffix = selection ? 'selection/' : jobId ? `${jobId}/` : '';
    const query = requestKey ? `?idempotency_key=${encodeURIComponent(requestKey)}` : '';
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/passive-tls/${suffix}${query}`,
      data ? 'POST' : 'GET', data);
  }

  passiveTlsCandidates(organizationId: number, projectId: number, jobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/passive-tls/${jobId}/candidates/`);
  }

  passiveTlsFindings(organizationId: number, projectId: number, jobId: number, candidateDigest?: string) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/passive-tls/${jobId}/findings/`,
      candidateDigest === undefined ? 'GET' : 'POST', candidateDigest === undefined ? undefined : { candidate_digest: candidateDigest });
  }

  passiveTlsPriority(organizationId: number, projectId: number, jobId: number, findingId: number, data?: Record<string, unknown>) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/passive-tls/${jobId}/findings/${findingId}/priority/`,
      data === undefined ? 'GET' : 'POST', data);
  }

  passiveResources(organizationId: number, projectId: number, data?: Record<string, unknown>, jobId?: number, requestKey?: string, selection = false) {
    const suffix = selection ? 'selection/' : jobId ? `${jobId}/` : '';
    const query = requestKey ? `?idempotency_key=${encodeURIComponent(requestKey)}` : '';
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/passive-resources/${suffix}${query}`,
      data ? 'POST' : 'GET', data);
  }

  passiveResourceCandidates(organizationId: number, projectId: number, jobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/passive-resources/${jobId}/candidates/`);
  }

  passiveResourceFindings(organizationId: number, projectId: number, jobId: number, candidateDigest?: string) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/passive-resources/${jobId}/findings/`,
      candidateDigest === undefined ? 'GET' : 'POST', candidateDigest === undefined ? undefined : { candidate_digest: candidateDigest });
  }

  passiveResourcePriority(organizationId: number, projectId: number, jobId: number, findingId: number, data?: Record<string, unknown>) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/passive-resources/${jobId}/findings/${findingId}/priority/`,
      data === undefined ? 'GET' : 'POST', data);
  }

  passiveRedirects(organizationId: number, projectId: number, data?: Record<string, unknown>, jobId?: number, requestKey?: string, selection = false) {
    const suffix = selection ? 'selection/' : jobId ? `${jobId}/` : '';
    const query = requestKey ? `?idempotency_key=${encodeURIComponent(requestKey)}` : '';
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/passive-redirects/${suffix}${query}`,
      data ? 'POST' : 'GET', data);
  }

  passiveHttpRedirects(organizationId: number, projectId: number, data?: Record<string, unknown>, jobId?: number, requestKey?: string, selection = false) {
    const suffix = selection ? 'selection/' : jobId ? `${jobId}/` : '';
    const query = requestKey ? `?idempotency_key=${encodeURIComponent(requestKey)}` : '';
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/passive-http-redirects/${suffix}${query}`,
      data === undefined ? 'GET' : 'POST', data);
  }

  passiveHttpHttpsComparison(organizationId: number, projectId: number, httpJobId: number, httpsJobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/passive-http-redirects/comparison/?http_job_id=${httpJobId}&https_job_id=${httpsJobId}`);
  }

  passiveRedirectChain(organizationId: number, projectId: number, data?: Record<string, unknown>, jobId?: number, requestKey?: string, selection = false) {
    const suffix = selection ? 'selection/' : jobId ? `${jobId}/` : '';
    const query = requestKey ? `?idempotency_key=${encodeURIComponent(requestKey)}` : '';
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/passive-redirect-chain/${suffix}${query}`,
      data === undefined ? 'GET' : 'POST', data);
  }

  passiveRedirectChainCandidates(organizationId: number, projectId: number, jobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/passive-redirect-chain/${jobId}/candidates/`);
  }

  passiveRedirectChainFindings(organizationId: number, projectId: number, jobId: number, candidateDigest?: string) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/passive-redirect-chain/${jobId}/findings/`,
      candidateDigest === undefined ? 'GET' : 'POST', candidateDigest === undefined ? undefined : { candidate_digest: candidateDigest });
  }

  passiveRedirectChainPriority(organizationId: number, projectId: number, jobId: number, findingId: number, data?: Record<string, unknown>) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/passive-redirect-chain/${jobId}/findings/${findingId}/priority/`,
      data === undefined ? 'GET' : 'POST', data);
  }

  passiveRedirectCandidates(organizationId: number, projectId: number, jobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/passive-redirects/${jobId}/candidates/`);
  }

  passiveRedirectFindings(organizationId: number, projectId: number, jobId: number, candidateDigest?: string) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/passive-redirects/${jobId}/findings/`,
      candidateDigest === undefined ? 'GET' : 'POST', candidateDigest === undefined ? undefined : { candidate_digest: candidateDigest });
  }

  passiveRedirectPriority(organizationId: number, projectId: number, jobId: number, findingId: number, data?: Record<string, unknown>) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/passive-redirects/${jobId}/findings/${findingId}/priority/`,
      data === undefined ? 'GET' : 'POST', data);
  }

  authorityLinkComparison(organizationId: number, projectId: number, previousJobId: number, currentJobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/authority-link-sources/comparison/?previous_job_id=${previousJobId}&current_job_id=${currentJobId}`);
  }

  authorityMentionCandidates(organizationId: number, projectId: number, prospectReviewId?: number, staticJobId?: number) {
    const query = prospectReviewId === undefined ? '' : `?prospect_review_id=${prospectReviewId}&static_job_id=${staticJobId}`;
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/authority-link-sources/mention-candidates/${query}`);
  }

  authorityDestinationCandidate(organizationId: number, projectId: number, staticJobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/authority-link-sources/destination-candidate/?static_job_id=${staticJobId}`);
  }

  contentLifecycle(organizationId: number, projectId: number, data?: Record<string, unknown>, reviewId?: string, requestKey?: string) {
    const suffix = reviewId ? `${encodeURIComponent(reviewId)}/` : '';
    const query = requestKey ? `?request_key=${encodeURIComponent(requestKey)}` : '';
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/content-lifecycle/${suffix}${query}`,
      data ? 'POST' : 'GET', data);
  }

  contentComparison(organizationId: number, projectId: number, revisionId: number,
    otherOrganizationId: number, otherProjectId: number, otherRevisionId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/content-lifecycle/comparison/?content_revision_id=${revisionId}&other_organization_id=${otherOrganizationId}&other_project_id=${otherProjectId}&other_content_revision_id=${otherRevisionId}`);
  }

  authorityProspects(organizationId: number, projectId: number, data?: Record<string, unknown>, prospectId?: string, requestKey?: string) {
    const suffix = prospectId ? `${encodeURIComponent(prospectId)}/` : '';
    const query = requestKey ? `?request_key=${encodeURIComponent(requestKey)}` : '';
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/authority-prospects/${suffix}${query}`,
      data ? 'POST' : 'GET', data);
  }

  localVisibility(organizationId: number, projectId: number, data?: Record<string, unknown>, observationId?: string, requestKey?: string) {
    const suffix = observationId ? `${encodeURIComponent(observationId)}/` : '';
    const query = requestKey ? `?request_key=${encodeURIComponent(requestKey)}` : '';
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/local-visibility/${suffix}${query}`,
      data ? 'POST' : 'GET', data);
  }

  visibilityManual(organizationId: number, projectId: number, data?: Record<string, unknown>, observationId?: string, requestKey?: string) {
    const suffix = observationId ? `${encodeURIComponent(observationId)}/` : '';
    const query = requestKey ? `?request_key=${encodeURIComponent(requestKey)}` : '';
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/visibility-manual/${suffix}${query}`,
      data ? 'POST' : 'GET', data);
  }

  visibilityManualRates(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/visibility-manual/rates/`);
  }

  localAssessmentHistory(organizationId: number, projectId: number, digest: string) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/local-assessments/${encodeURIComponent(digest)}/`);
  }

  saveLocalAssessment(organizationId: number, projectId: number, data: Record<string, unknown>, digest?: string) {
    const suffix = digest ? `${encodeURIComponent(digest)}/` : '';
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/local-assessments/${suffix}`,
      'POST', data);
  }

  recordImportFindings(organizationId: number, projectId: number, connectionId: number, importId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/findings/imports/${connectionId}/${importId}/`,
      'POST', {});
  }

  recordQueryChangeFindings(organizationId: number, projectId: number, connectionId: number,
    previousImportId: number, currentImportId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/findings/query-changes/${connectionId}/`,
      'POST', { previous_import_id: previousImportId, current_import_id: currentImportId });
  }

  recordPageChangeFindings(organizationId: number, projectId: number, connectionId: number,
    previousImportId: number, currentImportId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/findings/page-changes/${connectionId}/`,
      'POST', { previous_import_id: previousImportId, current_import_id: currentImportId });
  }

  recordIndexationFindings(organizationId: number, projectId: number, crawlRunId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/findings/indexation/${crawlRunId}/`,
      'POST', {});
  }

  recordTechnicalFindings(organizationId: number, projectId: number, diagnosticsId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/findings/technical/${diagnosticsId}/`,
      'POST', {});
  }

  recordPerformanceFindings(organizationId: number, projectId: number, observationId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/findings/performance/${observationId}/`,
      'POST', {});
  }

  reviewFinding(organizationId: number, projectId: number, findingId: number, expectedRevision: number,
    priority: string, estimatedEffort: string, businessRelevance: string, reason: string) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/findings/${findingId}/reviews/`,
      'POST', { expected_revision: expectedRevision, priority, estimated_effort: estimatedEffort,
        business_relevance: businessRelevance, reason });
  }

  setCsvSourceState(organizationId: number, projectId: number, connectionId: number, enabled: boolean) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/sources/${connectionId}/state/`,
      'PATCH', { enabled });
  }

  sourceQueries(organizationId: number, projectId: number, connectionId: number, before?: number) {
    const path = `${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/sources/${connectionId}/queries/`;
    return this.request(before ? `${path}?before=${before}` : path);
  }

  reviewSourceQuery(organizationId: number, projectId: number, connectionId: number, queryId: number,
    revision: number, label: SourceQueryInfo['label'], reason: string) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/sources/${connectionId}/queries/${queryId}/reviews/`,
      'POST', { revision, label, reason });
  }

  sourceQueryHistory(organizationId: number, projectId: number, connectionId: number, queryId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/sources/${connectionId}/queries/${queryId}/reviews/`);
  }

  updateProjectOnboarding(organizationId: number, projectId: number, details: Record<string, unknown>) {
    return this.request(
      `${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/onboarding/`,
      'PATCH',
      details,
    );
  }

  team(organizationId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/team/`);
  }

  inviteMember(organizationId: number, email: string, role: OrganizationInfo['role'], projectIds: number[]) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/team/`, 'POST', {
      email,
      role,
      project_ids: projectIds,
    });
  }

  updateMember(
    organizationId: number,
    membershipId: number,
    role: OrganizationInfo['role'],
    projectIds: number[],
  ) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/team/members/${membershipId}/`, 'PATCH', {
      role,
      project_ids: projectIds,
    });
  }

  removeMember(organizationId: number, membershipId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/team/members/${membershipId}/`, 'DELETE');
  }

  revokeInvitation(organizationId: number, invitationId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/team/invitations/${invitationId}/`, 'DELETE');
  }

  reissueInvitation(organizationId: number, invitationId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/team/invitations/${invitationId}/`, 'POST', {});
  }

  acceptInvitation(token: string) {
    return this.request(`${environment.apiBase}/invitations/accept/`, 'POST', { token });
  }

  ownershipTransfer(organizationId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/ownership/`);
  }

  proposeOwnershipTransfer(organizationId: number, memberId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/ownership/`, 'POST', { member_id: memberId });
  }

  acceptOwnershipTransfer(organizationId: number, transferId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/ownership/${transferId}/accept/`, 'POST', {});
  }

  cancelOwnershipTransfer(organizationId: number, transferId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/ownership/${transferId}/`, 'DELETE');
  }

  leaveOrganization(organizationId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/leave/`, 'POST', {});
  }

  jobs(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/jobs/`);
  }

  createDiagnostic(organizationId: number, projectId: number, sample: string, simulatePartial: boolean, key: string) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/jobs/`, 'POST', {
      handler: 'diagnostic_probe', input: { sample, simulate_partial: simulatePartial }, idempotency_key: key,
    });
  }

  jobDetails(organizationId: number, projectId: number, jobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/jobs/${jobId}/`);
  }

  cancelJob(organizationId: number, projectId: number, jobId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/jobs/${jobId}/cancel/`, 'POST', {});
  }

  retryJob(organizationId: number, projectId: number, jobId: number, key: string) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/jobs/${jobId}/retry/`, 'POST', { idempotency_key: key });
  }

  jobSchedules(organizationId: number, projectId: number) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/job-schedules/`);
  }

  createDiagnosticSchedule(organizationId: number, projectId: number, sample: string, intervalMinutes: number, key: string) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/job-schedules/`, 'POST', {
      input: { sample, simulate_partial: false }, interval_minutes: intervalMinutes, idempotency_key: key,
    });
  }

  setDiagnosticSchedule(organizationId: number, projectId: number, scheduleId: number, enabled: boolean) {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/job-schedules/${scheduleId}/`, 'PATCH', { enabled });
  }

  verificationStatus(key: string) {
    return this.request(`${environment.apiBase}/account/verification-status/`, 'GET', undefined, {
      'X-Email-Verification-Key': key,
    });
  }

  confirmVerification(key: string) {
    return this.request(`${environment.authBase}/auth/email/verify`, 'POST', { key });
  }

  resendVerification(email: string) {
    return this.request(`${environment.apiBase}/account/resend-verification/`, 'POST', { email });
  }

  hasPendingVerification(result: ApiResult) {
    const data = result.body['data'];
    const flows = data && typeof data === 'object' ? (data as Record<string, unknown>)['flows'] : undefined;
    return Array.isArray(flows) && flows.some((flow) => {
      if (!flow || typeof flow !== 'object') return false;
      const value = flow as Record<string, unknown>;
      return value['id'] === 'verify_email' && value['is_pending'] === true;
    });
  }

  hasPendingMfa(result: ApiResult) {
    const data = result.body['data'];
    const flows = data && typeof data === 'object' ? (data as Record<string, unknown>)['flows'] : undefined;
    return Array.isArray(flows) && flows.some((flow) => {
      if (!flow || typeof flow !== 'object') return false;
      const value = flow as Record<string, unknown>;
      return value['id'] === 'mfa_authenticate' && value['is_pending'] === true;
    });
  }

  createCsvSource(organizationId: number, projectId: number, property: string): Promise<ApiResult> {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/sources/csv/`,
      'POST', { property });
  }

  uploadSearchConsoleCsv(organizationId: number, projectId: number, connectionId: number,
    file: Blob, headers: Record<string, string>): Promise<ApiResult> {
    return this.request(`${environment.apiBase}/organizations/${organizationId}/projects/${projectId}/sources/${connectionId}/csv/`,
      'POST', undefined, { ...headers, 'Content-Type': 'text/csv' }, file);
  }

  private async request(
    path: string,
    method = 'GET',
    body?: unknown,
    headers: Record<string, string> = {},
    rawBody?: Blob,
  ): Promise<ApiResult> {
    const fetcher = this.document.defaultView?.fetch.bind(this.document.defaultView);
    if (!fetcher) throw new Error('Account requests require a browser.');

    if (method !== 'GET') {
      await fetcher(`${environment.authBase}/auth/session`, { credentials: 'same-origin', cache: 'no-store' });
      headers['X-CSRFToken'] = this.cookie('csrftoken');
    }
    if (body) headers['Content-Type'] = 'application/json';

    const response = await fetcher(path, {
      method,
      headers,
      body: rawBody ?? (body ? JSON.stringify(body) : undefined),
      credentials: 'same-origin',
      cache: 'no-store',
    });
    const parsed = await response.json().catch(() => ({}));
    return {
      status: response.status,
      body: parsed && typeof parsed === 'object' ? parsed as Record<string, unknown> : {},
    };
  }

  private cookie(name: string) {
    const prefix = `${encodeURIComponent(name)}=`;
    const value = this.document.cookie.split('; ').find((part) => part.startsWith(prefix));
    return value ? decodeURIComponent(value.slice(prefix.length)) : '';
  }
}
