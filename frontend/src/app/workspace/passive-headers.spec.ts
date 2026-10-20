import { Title } from '@angular/platform-browser';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { vi } from 'vitest';
import { environment } from '../../environments/environment';
import { AccountApi, ApiResult } from '../account/account-api';
import { PassiveHeaders } from './passive-headers';
import { microseconds } from './utc-date';
import { workspaceRoutes } from './workspace.routes';

const ORIGIN = 'https://security.example.invalid';
const DATE = '2026-01-01T00:00:00.000001+00:00';
const LATER = '2026-01-01T00:00:00.000002+00:00';
const PATH = '/.well-known/organicseoops-verification.txt';
const binding = () => ({ method_version: 'passive-header-source-v1', organization_id: 7, project_id: 9, actor_id: 1,
  origin: ORIGIN, url: ORIGIN + '/', observations: ['response_headers'], collection_permission: true, verification_id: 11,
  verified_at: DATE, source_digest: 'b'.repeat(64), interpretation: 'current_source_binding_not_network_job_commercial_reservation_or_observation_authority' });
const verification = () => ({ id: 11, project_id: 9, origin: ORIGIN, method: 'http_file', state: 'verified', challenge_path: PATH,
  created_at: DATE, updated_at: LATER, verified_at: DATE, revoked_at: null });
const job = () => ({ id: 21, status: 'queued', created_at: DATE, updated_at: LATER, cancel_requested: false, estimate_units: 1, error_category: '' });
function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, row]) => [key, canonical(row)]));
  return value;
}
async function sha(value: unknown) {
  const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(canonical(value))));
  return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, '0')).join('');
}
function evidence() {
  return { job_id: 21, source_current: true, collection: { method: 'passive-header-collection-v1', url: ORIGIN + '/', status: 302,
    observed_at: DATE, interpretation: 'one_public_response_not_policy_effectiveness_tls_configuration_redirect_behavior_or_exploitability',
    evidence: { method_version: 'passive-response-headers-v1', state: 'observed', coverage: 'one_complete_original_response_header_sequence_only',
      interpretation: 'header_presence_and_explicit_cookie_flags_not_policy_effectiveness_browser_acceptance_or_exploitability',
      headers: Object.fromEntries(['strict-transport-security', 'content-security-policy', 'content-security-policy-report-only', 'x-frame-options',
        'x-content-type-options', 'referrer-policy', 'server', 'x-powered-by'].map(key => [key, 'absent'])),
      cookies: { observed_fields: 2, parsed_fields: 1, unclassified_fields: 1, without_secure: 0, without_httponly: 1, without_recognized_samesite: 1 } } } };
}
function headerCandidateReport() {
  return { job_id: 21, source_current: true, method_version: 'passive-header-candidates-v1', binding: binding(), collection: evidence().collection,
    coverage: 'one_original_response_selected_header_categories_and_parsed_cookie_subset_only',
    interpretation: 'dated_response_review_candidates_not_severity_policy_effectiveness_browser_behavior_or_exploitability',
    candidates: [
      { detector: 'response_strict_transport_security_absent_candidate', evidence: { header: 'strict-transport-security', state: 'absent' } },
      { detector: 'response_content_security_policy_absent_candidate', evidence: { header: 'content-security-policy', state: 'absent', report_only_state: 'absent' } },
      { detector: 'response_x_frame_options_absent_candidate', evidence: { header: 'x-frame-options', state: 'absent' } },
      { detector: 'response_x_content_type_options_absent_candidate', evidence: { header: 'x-content-type-options', state: 'absent' } },
      { detector: 'response_referrer_policy_absent_candidate', evidence: { header: 'referrer-policy', state: 'absent' } },
      { detector: 'parsed_public_cookie_without_httponly_candidate', evidence: { flag: 'without_httponly', count: 1, observed_fields: 2, parsed_fields: 1, unclassified_fields: 1 } },
      { detector: 'parsed_public_cookie_without_recognized_samesite_candidate', evidence: { flag: 'without_recognized_samesite', count: 1, observed_fields: 2, parsed_fields: 1, unclassified_fields: 1 } },
    ] };
}
async function headerFindingResult(saved = false, report = headerCandidateReport()): Promise<ApiResult> {
  const findings = [];
  if (saved) for (const [index, candidate] of report.candidates.entries()) {
    const evidence = { source: 'passive_response_headers', job_id: report.job_id, binding: report.binding,
      collection_sha256: await sha(report.collection), observed_at: report.collection.observed_at, status: report.collection.status,
      fact: candidate.evidence, coverage: report.coverage, interpretation: report.interpretation };
    findings.push({ id: 100 + index, source_passive_header_id: report.job_id, detector: candidate.detector, method_version: 'passive-header-finding-v1',
      subject: report.collection.url, fingerprint: await sha(['passive-header-finding-v1', candidate.detector, evidence]), evidence,
      confidence: 'dated_response_fact_not_risk_severity', detected_at: LATER });
  }
  return { status: 200, body: { organization_id: 7, project_id: 9, candidates: report, candidate_digest: await sha(report),
    finding_set: { method_version: 'passive-header-finding-v1', project_id: 9, job_id: report.job_id, source_current: true,
      state: findings.length ? 'current_materialized_facts' : 'no_retained_materialized_findings', findings } } };
}
const tlsBinding = () => {
  const { url: _url, ...row } = binding();
  return { ...row, method_version: 'passive-tls-source-v1', observations: ['certificate_dates', 'negotiated_tls'] };
};
function tlsEvidence(observed = DATE, start = '2020-01-01T00:00:00.000000+00:00', end = '2040-01-01T00:00:00.000000+00:00') {
  const position = microseconds(observed)! < microseconds(start)! ? 'before_reported_window'
    : microseconds(observed)! > microseconds(end)! ? 'after_reported_window' : 'within_reported_window';
  return { job_id: 21, source_current: true, collection: { method: 'passive-tls-evidence-v1', origin: ORIGIN, observed_at: observed,
    interpretation: 'one_validated_handshake_not_all_supported_tls_configuration_revocation_or_exploitability', evidence: {
      method_version: 'passive-tls-handshake-v1', origin: ORIGIN, observed_at: observed,
      coverage: 'one_default_context_hostname_chain_validated_handshake_only',
      interpretation: 'negotiated_parameters_not_all_supported_configuration_revocation_or_exploitability',
      certificate_dates: { method_version: 'passive-peer-certificate-dates-v1', coverage: 'one_original_peer_certificate_reported_date_interval_only',
        interpretation: 'reported_dates_not_tls_chain_hostname_revocation_validation_or_server_identity', observed_at: observed, state: 'observed',
        not_before: start, not_after: end, position, remaining_microseconds: String(microseconds(end)! - microseconds(observed)!) },
      negotiated_tls: { version: 'TLSv1.3', cipher: { name: 'TLS_AES_256_GCM_SHA384', secret_bits: 256 } } } } };
}
function tlsCandidateReport(item = tlsEvidence(DATE, '2026-01-01T00:00:00.000000+00:00', '2026-01-01T00:00:00.000000+00:00')): {
  job_id: number; source_current: boolean; method_version: string; binding: ReturnType<typeof tlsBinding>; collection: any;
  availability: { certificate_dates: string; negotiated_version: string }; coverage: string; interpretation: string; candidates: { detector: string; evidence: any }[];
} {
  return { job_id: 21, source_current: true, method_version: 'passive-tls-candidates-v1', binding: tlsBinding(), collection: item.collection,
    availability: { certificate_dates: 'observed', negotiated_version: 'observed' },
    coverage: 'one_original_reported_certificate_date_interval_and_actual_negotiated_version_only',
    interpretation: 'dated_reported_dates_and_negotiated_version_candidates_not_supported_configuration_revocation_browser_behavior_or_exploitability',
    candidates: [{ detector: 'reported_certificate_date_outside_window_candidate', evidence: {
      not_before: '2026-01-01T00:00:00.000000+00:00', not_after: '2026-01-01T00:00:00.000000+00:00', position: 'after_reported_window', remaining_microseconds: '-1' } }] };
}
async function tlsFindingResult(saved = false, report = tlsCandidateReport()): Promise<ApiResult> {
  const findings = [];
  if (saved) for (const [index, candidate] of report.candidates.entries()) {
    const evidence = { source: 'passive_certificate_dates_and_negotiated_tls', job_id: report.job_id, binding: report.binding,
      collection_sha256: await sha(report.collection), observed_at: report.collection.observed_at, availability: report.availability,
      fact: candidate.evidence, coverage: report.coverage, interpretation: report.interpretation };
    findings.push({ id: 100 + index, source_passive_tls_id: report.job_id, detector: candidate.detector, method_version: 'passive-tls-finding-v1',
      subject: report.collection.origin, fingerprint: await sha(['passive-tls-finding-v1', candidate.detector, evidence]), evidence,
      confidence: 'dated_tls_fact_not_risk_severity', detected_at: LATER });
  }
  return { status: 200, body: { organization_id: 7, project_id: 9, candidates: report, candidate_digest: await sha(report),
    finding_set: { method_version: 'passive-tls-finding-v1', project_id: 9, job_id: report.job_id, source_current: true,
      state: findings.length ? 'current_materialized_facts' : 'no_retained_materialized_findings', findings } } };
}
function twoTlsCandidates() {
  const report = tlsCandidateReport(); report.collection.evidence.negotiated_tls.version = 'TLSv1.1';
  report.candidates.push({ detector: 'negotiated_tlsv1_or_tlsv1_1_candidate', evidence: { version: 'TLSv1.1' } });
  return report;
}
class FixtureApi {
  savedProductLanguage: 'en' | 'tr' = 'en';
  productLanguage(): Promise<ApiResult> { return Promise.resolve({ status: 200, body: { language: this.savedProductLanguage, current_ui_language: 'en', current_email_language: 'en' } }); }
  tls = false; resources = false; redirects = false; httpRedirects = false; families: string[] = [];
  role: unknown = 'owner'; rows: ReturnType<typeof job>[] = []; verifications: Record<string, unknown>[] = [verification()];
  changed = false; uncertain = false; drop = false; deny = false; wrong = false;
  commands: Record<string, unknown>[] = []; lookups: string[] = []; ownership: unknown[][] = []; previews = 0;
  keys: string[] = []; detail: ApiResult | null = null; previewResult: ApiResult | null = null;
  detailPromise: Promise<ApiResult> | null = null; previewPromise: Promise<ApiResult> | null = null;
  candidateCalls: number[] = []; candidateResult: ApiResult | null = null; candidatePromise: Promise<ApiResult> | null = null;
  resourceCandidateCalls: number[] = []; resourceCandidateResult: ApiResult | null = null; resourceCandidatePromise: Promise<ApiResult> | null = null;
  tlsCandidateCalls: number[] = []; tlsCandidateResult: ApiResult | null = null; tlsCandidatePromise: Promise<ApiResult> | null = null;
  redirectCandidateCalls: number[] = []; redirectCandidateResult: ApiResult | null = null; redirectCandidatePromise: Promise<ApiResult> | null = null;
  findingReads: number[] = []; findingCommands: [number, string][] = []; findingsSaved = false; findingUncertain = false; findingDrop = false;
  findingResult: ApiResult | null = null; findingPromise: Promise<ApiResult> | null = null;
  findingPostPromise: Promise<ApiResult> | null = null;
  resourceFindingReads: number[] = []; resourceFindingCommands: [number, string][] = [];
  resourceFindingResult: ApiResult | null = null; resourceFindingPromise: Promise<ApiResult> | null = null;
  resourceFindingPostPromise: Promise<ApiResult> | null = null;
  tlsFindingReads: number[] = []; tlsFindingCommands: [number, string][] = [];
  tlsFindingResult: ApiResult | null = null; tlsFindingPromise: Promise<ApiResult> | null = null;
  tlsFindingPostPromise: Promise<ApiResult> | null = null;
  redirectFindingReads: number[] = []; redirectFindingCommands: [number, string][] = [];
  redirectFindingResult: ApiResult | null = null; redirectFindingPromise: Promise<ApiResult> | null = null;
  redirectFindingPostPromise: Promise<ApiResult> | null = null;
  priorityReads: [string, number, number][] = []; priorityCommands: [string, number, number, Record<string, unknown>][] = [];
  priorityDecision: Record<string, unknown> | null = null; priorityUncertain = false; priorityDrop = false; priorityReadUnavailable = false;
  priorityResult: ApiResult | null = null; priorityPromise: Promise<ApiResult> | null = null; priorityPostPromise: Promise<ApiResult> | null = null;
  passiveHeaderPriority(org: number, project: number, id: number, finding: number, data?: Record<string, unknown>) { return this.priority('headers', org, project, id, finding, data); }
  passiveResourcePriority(org: number, project: number, id: number, finding: number, data?: Record<string, unknown>) { return this.priority('resources', org, project, id, finding, data); }
  passiveTlsPriority(org: number, project: number, id: number, finding: number, data?: Record<string, unknown>) { return this.priority('tls', org, project, id, finding, data); }
  passiveRedirectPriority(org: number, project: number, id: number, finding: number, data?: Record<string, unknown>) { return this.priority('redirects', org, project, id, finding, data); }
  passiveRedirectChainPriority(org: number, project: number, id: number, finding: number, data?: Record<string, unknown>) { return this.priority('redirect-chain', org, project, id, finding, data); }
  async priorityResponse(family: string, org = 7, project = 9, id = 21, finding = 100): Promise<ApiResult> {
    const facts = family === 'redirect-chain' && this instanceof ChainFixtureApi ? await chainFindingResult(true, this.chainCandidateResult || twoChainCandidates())
      : family === 'redirects' ? await redirectFindingResult(true) : family === 'tls' ? await tlsFindingResult(true)
      : family === 'resources' ? await resourceFindingResult(true) : await headerFindingResult(true);
    return { status: 200, body: { organization_id: org, project_id: project, prioritization: {
      method_version: 'passive-human-prioritization-v1', source: { method_version: 'passive-finding-review-source-v1', organization_id: org,
        project_id: project, job_id: id, source_current: true, finding: (facts.body['finding_set'] as any).findings.find((row: any) => row.id === finding),
        source_sha256: 'c'.repeat(64), interpretation: 'original_passive_fact_for_human_prioritization_not_severity_approval_or_page_action' },
      decision: structuredClone(this.priorityDecision), reviewed_at: this.priorityDecision ? '2026-01-01T00:00:00.000003+00:00' : null,
      interpretation: 'human_priority_not_measured_risk_severity_recommendation_approval_or_page_action' } } };
  }
  private async priority(family: string, org: number, project: number, id: number, finding: number, data?: Record<string, unknown>): Promise<ApiResult> {
    if (data !== undefined) {
      this.priorityCommands.push([family, id, finding, structuredClone(data)]);
      if (!this.priorityDrop) this.priorityDecision = { id: 500 + Number(data['expected_revision']), revision: Number(data['expected_revision']) + 1,
        priority: data['priority'], estimated_effort: data['estimated_effort'], business_relevance: data['business_relevance'], review_reason: data['reason'] };
      if (this.priorityPostPromise) return this.priorityPostPromise;
      if (this.priorityUncertain || this.priorityDrop) throw new Error('Lost human judgment acknowledgement');
    } else { this.priorityReads.push([family, id, finding]); if (this.priorityReadUnavailable) throw new Error('lookup unavailable'); }
    return (data === undefined && this.priorityPromise) || this.priorityResult || this.priorityResponse(family, org, project, id, finding);
  }
  async passiveRedirectFindings(_org: number, _project: number, id: number, digest?: string): Promise<ApiResult> {
    if (digest !== undefined) {
      this.redirectFindingCommands.push([id, digest]);
      if (!this.findingDrop) this.findingsSaved = true;
      if (this.redirectFindingPostPromise) return this.redirectFindingPostPromise;
      if (this.findingUncertain || this.findingDrop) throw new Error('Lost Location save acknowledgement');
    } else this.redirectFindingReads.push(id);
    return this.redirectFindingPromise || this.redirectFindingResult || redirectFindingResult(this.findingsSaved);
  }
  async passiveTlsFindings(_org: number, _project: number, id: number, digest?: string): Promise<ApiResult> {
    if (digest !== undefined) {
      this.tlsFindingCommands.push([id, digest]);
      if (!this.findingDrop) this.findingsSaved = true;
      if (this.tlsFindingPostPromise) return this.tlsFindingPostPromise;
      if (this.findingUncertain || this.findingDrop) throw new Error('Lost TLS save acknowledgement');
    } else this.tlsFindingReads.push(id);
    return this.tlsFindingPromise || this.tlsFindingResult || tlsFindingResult(this.findingsSaved);
  }
  async passiveResourceFindings(_org: number, _project: number, id: number, digest?: string): Promise<ApiResult> {
    if (digest !== undefined) {
      this.resourceFindingCommands.push([id, digest]);
      if (!this.findingDrop) this.findingsSaved = true;
      if (this.resourceFindingPostPromise) return this.resourceFindingPostPromise;
      if (this.findingUncertain || this.findingDrop) throw new Error('Lost resource save acknowledgement');
    } else this.resourceFindingReads.push(id);
    return this.resourceFindingPromise || this.resourceFindingResult || resourceFindingResult(this.findingsSaved);
  }
  async passiveHeaderFindings(_org: number, _project: number, id: number, digest?: string): Promise<ApiResult> {
    if (digest !== undefined) {
      this.findingCommands.push([id, digest]);
      if (!this.findingDrop) this.findingsSaved = true;
      if (this.findingPostPromise) return this.findingPostPromise;
      if (this.findingUncertain || this.findingDrop) throw new Error('Lost save acknowledgement');
    } else this.findingReads.push(id);
    return this.findingPromise || this.findingResult || headerFindingResult(this.findingsSaved);
  }
  passiveHeaderCandidates(org: number, project: number, id: number): Promise<ApiResult> {
    this.candidateCalls.push(id);
    return this.candidatePromise || Promise.resolve(this.candidateResult || { status: 200, body: {
      organization_id: org, project_id: project, candidates: headerCandidateReport() } });
  }
  passiveResourceCandidates(org: number, project: number, id: number): Promise<ApiResult> {
    this.resourceCandidateCalls.push(id);
    return this.resourceCandidatePromise || Promise.resolve(this.resourceCandidateResult || { status: 200, body: {
      organization_id: org, project_id: project, candidates: resourceCandidateReport() } });
  }
  passiveTlsCandidates(org: number, project: number, id: number): Promise<ApiResult> {
    this.tlsCandidateCalls.push(id);
    return this.tlsCandidatePromise || Promise.resolve(this.tlsCandidateResult || { status: 200, body: {
      organization_id: org, project_id: project, candidates: tlsCandidateReport() } });
  }
  passiveRedirectCandidates(org: number, project: number, id: number): Promise<ApiResult> {
    this.redirectCandidateCalls.push(id);
    return this.redirectCandidatePromise || Promise.resolve(this.redirectCandidateResult || { status: 200, body: {
      organization_id: org, project_id: project, candidates: redirectCandidateReport() } });
  }
  projectOnboarding(org: number, project: number) { return Promise.resolve({ status: 200, body: { project: {
    id: project, organization_id: org, role: this.role, canonical_origin: ORIGIN, aliases: this.httpRedirects ? [HTTP_ORIGIN] : [] as string[] } } }); }
  async originVerifications(_org: number, _project: number, method = 'GET', data?: Record<string, unknown>, id?: number): Promise<ApiResult> {
    if (method === 'GET') return { status: 200, body: { verifications: this.verifications, has_more: false } };
    this.ownership.push([method, structuredClone(data), id]);
    if (this.uncertain) throw new Error('Lost ownership acknowledgement');
    const row = { ...(this.httpRedirects ? httpVerification() : verification()), state: method === 'DELETE' ? 'revoked' : 'pending', verified_at: null,
      revoked_at: method === 'DELETE' ? LATER : null };
    this.verifications = [row];
    return { status: method === 'DELETE' ? 200 : id ? 202 : 201, body: { verification: row,
      ...(method === 'DELETE' ? { revoked: true } : id ? { job: { id: 22, handler: 'verify_project_origin', status: 'queued' } }
        : { challenge: { path: PATH, content: 'a'.repeat(43) } }) } };
  }
  async preview(org = 7, project = 9): Promise<ApiResult> {
    const selection = { method: this.httpRedirects ? 'passive-http-redirect-collection-v1' : this.redirects ? 'passive-redirect-collection-v1' : this.resources ? 'passive-resource-collection-v1' : this.tls ? 'passive-tls-collection-v1' : 'passive-header-collection-v1',
      binding: { ...(this.httpRedirects ? httpBinding() : this.redirects ? redirectBinding() : this.resources ? resourceBinding() : this.tls ? tlsBinding() : binding()), source_digest: (this.changed ? 'c' : 'b').repeat(64) } };
    return { status: 200, body: { organization_id: org, project_id: project, selection, selection_digest: await sha(selection), estimate_units: 1 } };
  }
  passiveHeaders(org: number, project: number, data?: Record<string, unknown>, id?: number, key?: string, preview = false): Promise<ApiResult> {
    this.families.push('headers'); return this.passive(org, project, data, id, key, preview);
  }
  passiveTls(org: number, project: number, data?: Record<string, unknown>, id?: number, key?: string, preview = false): Promise<ApiResult> {
    this.families.push('tls'); return this.passive(org, project, data, id, key, preview);
  }
  passiveResources(org: number, project: number, data?: Record<string, unknown>, id?: number, key?: string, preview = false): Promise<ApiResult> {
    this.families.push('resources'); return this.passive(org, project, data, id, key, preview);
  }
  passiveRedirects(org: number, project: number, data?: Record<string, unknown>, id?: number, key?: string, preview = false): Promise<ApiResult> {
    this.families.push('redirects'); return this.passive(org, project, data, id, key, preview);
  }
  passiveHttpRedirects(org: number, project: number, data?: Record<string, unknown>, id?: number, key?: string, preview = false): Promise<ApiResult> {
    this.families.push('http-redirects'); return this.passive(org, project, data, id, key, preview);
  }
  passiveRedirectChain(org: number, project: number, data?: Record<string, unknown>, id?: number, key?: string, preview = false): Promise<ApiResult> {
    this.families.push('redirect-chain'); return this.passive(org, project, data, id, key, preview);
  }
  private async passive(org: number, project: number, data?: Record<string, unknown>, id?: number, key?: string, preview = false): Promise<ApiResult> {
    if (this.deny) return { status: 403, body: {} };
    if (preview) { this.previews++; return this.previewPromise || this.previewResult || this.preview(org, project); }
    const scope = { organization_id: org, project_id: this.wrong ? 99 : project };
    if (!data) {
      if (id) return this.detailPromise || this.detail || { status: 200, body: { ...scope, job: this.rows.find(row => row.id === id), evidence: null } };
      if (key) this.lookups.push(key);
      return { status: 200, body: { ...scope, jobs: key ? this.rows.filter((_row, i) => this.keys[i] === key) : this.rows, has_more: false, lookup: key ?? null } };
    }
    this.commands.push(structuredClone(data));
    if (this.drop) throw new Error('Fixture command not saved');
    const row = id ? { ...this.rows[0], status: 'cancelled', cancel_requested: true } : job();
    if (id) this.rows[0] = row; else { this.rows = [row]; this.keys = [String(data['idempotency_key'])]; }
    if (this.uncertain) throw new Error('Lost command acknowledgement');
    return { status: 202, body: { ...scope, job: row } };
  }
}

function retainDraftLanguage(harness: RouterTestingHarness, component: PassiveHeaders, api: FixtureApi, language: 'en' | 'tr') {
  harness.detectChanges(); const root = harness.routeNativeElement!;
  expect(root.querySelector('section')?.getAttribute('lang')).toBe(language);
  const nodes = [...root.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>('input, select, textarea')];
  const values = nodes.map(node => [node.value, node instanceof HTMLInputElement ? node.checked : null]);
  const original = structuredClone({ selection: component.selection(), pending: component.pending(), permission: component.permission(), targets: component.targetUrls(), judgment: component.priorityInspection(), priorityPending: component.priorityPending(), commands: api.commands, ownership: api.ownership, lookups: api.lookups, previews: api.previews, priorityCommands: api.priorityCommands });
  component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
  expect([...root.querySelectorAll('input, select, textarea')]).toEqual(nodes);
  expect(nodes.map(node => [node.value, node instanceof HTMLInputElement ? node.checked : null])).toEqual(values);
  expect({ selection: component.selection(), pending: component.pending(), permission: component.permission(), targets: component.targetUrls(), judgment: component.priorityInspection(), priorityPending: component.priorityPending(), commands: api.commands, ownership: api.ownership, lookups: api.lookups, previews: api.previews, priorityCommands: api.priorityCommands }).toEqual(original);
  component.productLanguage.set(language); harness.detectChanges();
}

describe.each(['headers', 'resources', 'tls', 'redirects', 'redirect-chain'])('Private passive %s human prioritization', family => {
  let api: FixtureApi;
  beforeEach(() => {
    api = family === 'redirect-chain' ? new ChainFixtureApi() : new FixtureApi();
    if (api instanceof ChainFixtureApi) api.chainCandidateResult = twoChainCandidates();
    api.tls = family === 'tls'; api.resources = family === 'resources'; api.redirects = family === 'redirects';
    api.rows = [{ ...job(), status: 'succeeded' }]; api.findingsSaved = true;
    TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] });
  });
  async function screen() {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl(`/passive-${family}/7/9?passiveObservation=foreign`, PassiveHeaders);
    await harness.fixture.whenStable(); await vi.waitFor(() => { expect(component.ready()).toBe(true); expect(component.busy()).toBe(false); });
    await component.inspectFindings(21); harness.detectChanges();
    expect(component.findingRows().map(row => row['id'])).toContain(100); return { harness, component };
  }
  function draft(component: PassiveHeaders, reason = 'Human relevance only') {
    component.editJudgment('priority', 'high'); component.editJudgment('estimated_effort', 'small');
    component.editJudgment('business_relevance', 'medium'); component.editJudgment('reason', reason);
  }
  function judgment(result: ApiResult): any { return result.body['prioritization']; }
  it('requires a scalar current role before and after a deliberate human decision without replay', async () => {
    const { component } = await screen();
    const method = family === 'redirect-chain' ? 'passiveRedirectChainPriority' : family === 'headers' ? 'passiveHeaderPriority'
      : family === 'tls' ? 'passiveTlsPriority' : family === 'resources' ? 'passiveResourcePriority' : 'passiveRedirectPriority';
    const original = api[method].bind(api);
    for (const role of ['owner', 'admin']) for (const afterPost of [false, true]) {
      vi.restoreAllMocks(); api.role = role;
      await component.load(); await component.inspectFindings(21); await component.inspectPriority(100); draft(component);
      expect(component.priorityInspection()).not.toBeNull();
      const count = api.priorityCommands.length;
      vi.spyOn(api, method).mockImplementation(async (...args) => {
        const result = await original(...args);
        if ((args[4] !== undefined) === afterPost) api.role = [role];
        return result;
      });
      await component.savePriority();
      expect(api.priorityCommands).toHaveLength(count + (afterPost ? 1 : 0));
      expect(component.ready()).toBe(false); expect(component.jobs()).toEqual([]);
      expect(component.findingInspection()).toBeNull(); expect(component.priorityInspection()).toBeNull();
      expect(component.priorityPending()).toBeNull(); expect(component.permission()).toBe(false);
      await component.reconcilePriority(); await component.savePriority();
      expect(api.priorityCommands).toHaveLength(count + (afterPost ? 1 : 0));
    }
    vi.restoreAllMocks();
  });
  it.each(['en', 'tr'] as const)('deliberately reads one genuine fact, distinguishes no judgment from human unprioritized, and saves optimistic corrections without new work or storage in %s', async (language) => {
    api.savedProductLanguage = language;
    const { harness, component } = await screen(); const storage = vi.spyOn(Storage.prototype, 'setItem');
    const metadata: Record<string, [string, string]> = {
  "headers": [
    "Private exact response-header observations — OrganicSEOOps",
    "Özel tam yanıt başlığı gözlemleri — OrganicSEOOps"
  ],
  "tls": [
    "Private exact TLS handshake observations — OrganicSEOOps",
    "Özel tam TLS el sıkışması gözlemleri — OrganicSEOOps"
  ],
  "resources": [
    "Private exact static resource candidates — OrganicSEOOps",
    "Özel tam statik kaynak adayları — OrganicSEOOps"
  ],
  "redirects": [
    "Private exact first-response Location metadata — OrganicSEOOps",
    "Özel tam ilk yanıt Location meta verileri — OrganicSEOOps"
  ],
  "http-redirects": [
    "Private plaintext HTTP Location metadata — OrganicSEOOps",
    "Özel düz metin HTTP Location meta verileri — OrganicSEOOps"
  ],
  "redirect-chain": [
    "Private exact permitted redirect chain — OrganicSEOOps",
    "Özel tam izin verilmiş yönlendirme zinciri — OrganicSEOOps"
  ]
};
    const titles = metadata[family];
    expect(TestBed.inject(Title).getTitle()).toBe(titles[language === 'tr' ? 1 : 0]);
    expect(api.priorityReads).toEqual([]); await component.inspectPriority(999); await component.inspectPriority(NaN); expect(api.priorityReads).toEqual([]);
    await component.inspectPriority(100); harness.detectChanges();
    expect(component.error()).toBe(''); expect(api.priorityReads).toEqual([[family, 21, 100]]); expect(judgment(await api.priorityResponse(family)).decision).toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Saklanan güncel insan yargısı yok' : 'No retained current human judgment');
    const reason = harness.routeNativeElement!.querySelector<HTMLTextAreaElement>('#passive-reason')!;
    expect(harness.routeNativeElement!.querySelector('label[for="passive-reason"]')).not.toBeNull();
    reason.value = '  Explicit human unprioritized  '; reason.dispatchEvent(new Event('input', { bubbles: true }));
    retainDraftLanguage(harness, component, api, language);
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(titles[language === 'tr' ? 0 : 1]);
    component.productLanguage.set(language); harness.detectChanges();
    expect(reason.getAttribute('lang')).toBe('');
    reason.closest('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.busy()).toBe(false)); harness.detectChanges();
    expect(api.priorityCommands[0]).toEqual([family, 21, 100, { source_sha256: 'c'.repeat(64), expected_revision: 0,
      priority: 'unprioritized', estimated_effort: 'unknown', business_relevance: 'unknown', reason: 'Explicit human unprioritized' }]);
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'öncelik unprioritized' : 'priority unprioritized');
    draft(component, '<script>never executable</script>'); await component.savePriority(); harness.detectChanges();
    expect(api.priorityCommands[1][3]['expected_revision']).toBe(1); expect((component.priorityInspection()?.judgment['decision'] as any).revision).toBe(2);
    expect(harness.routeNativeElement!.querySelector('script')).toBeNull(); expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
    expect(api.commands).toEqual([]); expect(api.findingCommands).toEqual([]); expect(api.resourceFindingCommands).toEqual([]);
    expect(api.tlsFindingCommands).toEqual([]); expect(api.redirectFindingCommands).toEqual([]);
    harness.fixture.destroy(); TestBed.inject(Title).setTitle('Next route — OrganicSEOOps');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); TestBed.tick();
    expect(TestBed.inject(Title).getTitle()).toBe('Next route — OrganicSEOOps');
  });
  it('rejects complete DTO/source/fact/ID/date/revision/field tampering including foreign family and truthy non-booleans', async () => {
    const { component } = await screen();
    const changes: ((value: any) => void)[] = [
      value => value.raw = 'not selected', value => value.method_version = 'ordinary-review', value => value.interpretation = 'severity',
      value => value.source.method_version = 'other', value => value.source.organization_id = 8, value => value.source.project_id = 10,
      value => value.source.job_id = 22, value => value.source.source_current = 1, value => value.source.source_sha256 = 'C'.repeat(64),
      value => value.source.interpretation = 'approval', value => value.source.finding.id = 101,
      value => value.source.finding.detected_at = DATE, value => value.source.finding.subject = ORIGIN + '/other',
      value => value.source.finding.fingerprint = 'd'.repeat(64), value => value.source.finding.evidence.fact = {},
      value => value.source.finding.source_passive_foreign_id = 21, value => value.source.finding.confidence = 'high',
      value => value.reviewed_at = DATE, value => value.decision.id = 0, value => value.decision.revision = true,
      value => value.decision.revision = 0, value => value.decision.revision = 65536, value => value.decision.priority = ['high'],
      value => value.decision.estimated_effort = ['small'], value => value.decision.business_relevance = ['medium'],
      value => value.decision.review_reason = ' ', value => value.decision.review_reason = 'x'.repeat(241),
      value => value.decision.review_reason = ' unstripped', value => value.decision.actor_id = 1,
      value => value.reviewed_at = '2026-02-30T00:00:00+00:00', value => value.reviewed_at = '2026-01-01T00:00:00',
      value => value.reviewed_at = '2099-01-01T00:00:00+00:00', value => { value.decision = null; value.reviewed_at = LATER; },
    ];
    api.priorityDecision = { id: 500, revision: 1, priority: 'high', estimated_effort: 'small', business_relevance: 'medium', review_reason: 'Human only' };
    for (const change of changes) {
      await component.inspectFindings(21); api.priorityResult = await api.priorityResponse(family); change(judgment(api.priorityResult));
      await component.inspectPriority(100); expect(component.priorityInspection()).toBeNull(); expect(component.priorityPending()).toBeNull();
    }
    api.priorityResult = await api.priorityResponse(family); api.priorityResult.body['project_id'] = 10;
    await component.inspectFindings(21); await component.inspectPriority(100); expect(component.priorityInspection()).toBeNull();
    api.priorityResult = await api.priorityResponse(family); judgment(api.priorityResult).source.finding = judgment(await api.priorityResponse(family === 'tls' ? 'headers' : 'tls')).source.finding;
    await component.inspectFindings(21); await component.inspectPriority(100); expect(component.priorityInspection()).toBeNull(); expect(api.priorityCommands).toEqual([]);
  });
  it('validates human input and correction limits; source or latest judgment drift before POST requires new inspection', async () => {
    const { component } = await screen(); await component.inspectPriority(100);
    for (const [field, value] of [['reason', ' '], ['reason', 'x'.repeat(241)], ['priority', 'critical'], ['estimated_effort', 'zero'], ['business_relevance', 'guaranteed']]) {
      draft(component); component.editJudgment(field, value); await component.savePriority(); expect(api.priorityCommands).toEqual([]);
    }
    draft(component); api.priorityResult = await api.priorityResponse(family); judgment(api.priorityResult).source.source_sha256 = 'd'.repeat(64);
    await component.savePriority(); expect(api.priorityCommands).toEqual([]); expect(component.priorityInspection()).toBeNull();
    api.priorityResult = null; await component.inspectFindings(21); await component.inspectPriority(100); draft(component);
    api.priorityDecision = { id: 501, revision: 1, priority: 'low', estimated_effort: 'unknown', business_relevance: 'unknown', review_reason: 'Another review' };
    await component.savePriority(); expect(api.priorityCommands).toEqual([]); expect(component.priorityInspection()).toBeNull();
    api.priorityDecision['revision'] = 65535; await component.inspectFindings(21); await component.inspectPriority(100);
    expect(component.priorityCanSave()).toBe(false); draft(component); await component.savePriority(); expect(api.priorityCommands).toEqual([]);
  });
  it('freezes uncertain commands, blocks conflicting operations and reconciles only by same-source GET without attribution or replay', async () => {
    const { harness, component } = await screen(); await component.inspectPriority(100); draft(component); api.priorityUncertain = true;
    await component.savePriority(); const frozen = structuredClone(component.priorityPending()!); harness.detectChanges();
    expect(frozen.command['expected_revision']).toBe(0); expect(frozen.findingId).toBe(100); expect(frozen.original.job.id).toBe(21);
    expect(harness.routeNativeElement!.querySelector('fieldset.observation-controls')?.hasAttribute('disabled')).toBe(true);
    const reads = api.priorityReads.length; const facts = api.findingReads.length + api.tlsFindingReads.length + api.resourceFindingReads.length + api.redirectFindingReads.length;
    await component.load(); await component.inspect(21); await component.inspectCandidates(21); await component.inspectResourceCandidates(21);
    await component.inspectTlsCandidates(21); await component.inspectRedirectCandidates(21); await component.inspectFindings(21); await component.saveFindings();
    await component.inspectPriority(100); await component.savePriority(); component.editJudgment('reason', 'replacement');
    expect(api.priorityReads).toHaveLength(reads); expect(api.findingReads.length + api.tlsFindingReads.length + api.resourceFindingReads.length + api.redirectFindingReads.length).toBe(facts);
    expect(component.priorityPending()).toEqual(frozen); expect(api.priorityCommands).toHaveLength(1);
    await component.reconcilePriority(); expect(component.priorityPending()).toBeNull(); expect(component.priorityInspection()).not.toBeNull();
    expect(component.message()).toContain('does not identify who saved it'); expect(api.priorityCommands).toHaveLength(1);
  });
  it('keeps missing or unavailable command outcomes unknown, while new conflicting revisions and hidden-source changes clear uncertainty for fresh review', async () => {
    const { component } = await screen(); await component.inspectPriority(100); draft(component); api.priorityDrop = true; await component.savePriority();
    const frozen = structuredClone(component.priorityPending()); await component.reconcilePriority(); expect(component.priorityPending()).toEqual(frozen);
    expect(component.message()).toContain('not confirmed no-op'); api.priorityReadUnavailable = true;
    await component.reconcilePriority(); expect(component.priorityPending()).toEqual(frozen); api.priorityReadUnavailable = false;
    api.priorityDecision = { id: 502, revision: 2, priority: 'low', estimated_effort: 'unknown', business_relevance: 'unknown', review_reason: 'Different review' };
    await component.reconcilePriority(); expect(component.priorityPending()).toBeNull(); expect(component.priorityInspection()).toBeNull();
    expect(component.message()).toContain('fresh deliberate inspection'); expect(api.priorityCommands).toHaveLength(1);
    api.priorityDrop = false; api.priorityUncertain = true; api.priorityDecision = null; await component.inspectFindings(21); await component.inspectPriority(100); draft(component); await component.savePriority();
    api.priorityResult = await api.priorityResponse(family); judgment(api.priorityResult).source.source_sha256 = 'd'.repeat(64);
    await component.reconcilePriority(); expect(component.priorityPending()).toBeNull(); expect(component.findingInspection()).toBeNull();
    expect(api.priorityCommands).toHaveLength(2);
  });
  it('rechecks fresh role/configuration/verification before and after commands, with late denial or foreign responses clearing all judgments and uncertainty', async () => {
    const { component } = await screen(); const method = family === 'redirect-chain' ? 'passiveRedirectChainPriority' : family === 'headers' ? 'passiveHeaderPriority' : family === 'tls' ? 'passiveTlsPriority'
      : family === 'resources' ? 'passiveResourcePriority' : 'passiveRedirectPriority';
    const original = api[method].bind(api);
    for (const afterPost of [false, true]) for (const loss of ['role', 'verification', 'config']) {
      api.role = 'owner'; api.verifications = family === 'redirect-chain' ? chainVerifications() : [verification()]; vi.restoreAllMocks();
      await component.load(); await component.inspectFindings(21); await component.inspectPriority(100); draft(component);
      const count = api.priorityCommands.length;
      vi.spyOn(api, method).mockImplementation(async (...args) => {
        const result = await original(...args); if ((args[4] !== undefined) === afterPost) {
          if (loss === 'role') api.role = 'member'; else if (loss === 'verification') api.verifications = [];
          else vi.spyOn(api, 'projectOnboarding').mockResolvedValue({ status: 200, body: { project: { id: 9, organization_id: 7, role: 'owner', canonical_origin: ORIGIN + '.different', aliases: [] } } });
        } return result;
      });
      await component.savePriority(); expect(api.priorityCommands).toHaveLength(count + (afterPost ? 1 : 0));
      expect(component.priorityInspection()).toBeNull(); expect(component.priorityPending()).toBeNull(); expect(component.findingInspection()).toBeNull(); expect(component.ready()).toBe(false);
    }
    vi.restoreAllMocks(); api.role = 'owner'; api.verifications = family === 'redirect-chain' ? chainVerifications() : [verification()]; await component.load();
    for (const invalid of ['denied', 'foreign']) {
      await component.inspectFindings(21); await component.inspectPriority(100); draft(component);
      api.priorityPostPromise = Promise.resolve(invalid === 'denied' ? { status: 403, body: {} } : await api.priorityResponse(family, 7, 10));
      await component.savePriority(); expect(component.priorityInspection()).toBeNull(); expect(component.priorityPending()).toBeNull(); api.priorityPostPromise = null;
    }
  });
  it('clears existing judgment on fact reads, other operations and edits, and discards late GET/POST after edit, route/family changes or destruction', async () => {
    const { harness, component } = await screen(); await component.inspectPriority(100); await component.inspectFindings(21); expect(component.priorityInspection()).toBeNull();
    await component.inspectPriority(100); await component.inspect(21); expect(component.priorityInspection()).toBeNull();
    await component.inspectFindings(21); await component.inspectPriority(100); component.editPermission(false); expect(component.priorityInspection()).toBeNull();
    await component.inspectFindings(21); let resolve!: (row: ApiResult) => void;
    const reads = api.priorityReads.length; api.priorityPromise = new Promise(done => resolve = done); const reading = component.inspectPriority(100);
    await vi.waitFor(() => expect(api.priorityReads).toHaveLength(reads + 1));
    component.editUrl(ORIGIN + '/different'); resolve(await api.priorityResponse(family)); await reading; expect(component.priorityInspection()).toBeNull(); api.priorityPromise = null;
    await component.inspectFindings(21); await component.inspectPriority(100); draft(component); api.priorityPostPromise = new Promise(done => resolve = done);
    const saving = component.savePriority(); await vi.waitFor(() => expect(api.priorityCommands).toHaveLength(1));
    await harness.navigateByUrl(`/passive-${family}/7/10`, PassiveHeaders); await harness.fixture.whenStable(); resolve(await api.priorityResponse(family)); await saving;
    expect(component.priorityInspection()).toBeNull(); expect(component.priorityPending()).toBeNull(); api.priorityPostPromise = null;
    const current = await harness.navigateByUrl(`/passive-${family}/7/9`, PassiveHeaders); await harness.fixture.whenStable();
    await vi.waitFor(() => { expect(current.ready()).toBe(true); expect(current.busy()).toBe(false); });
    await current.inspectFindings(21); await current.inspectPriority(100); draft(current);
    api.priorityUncertain = true; await current.savePriority(); expect(current.priorityPending()).not.toBeNull();
    await harness.navigateByUrl(`/passive-${family === 'tls' ? 'headers' : 'tls'}/7/9`, PassiveHeaders); await harness.fixture.whenStable(); expect(current.priorityPending()).toBeNull();
    harness.fixture.destroy(); expect(current.priorityInspection()).toBeNull(); expect(current.humanReason()).toBe('');
  });
  it('clears uncertainty after denied or malformed GET, and discards actually late priority responses on destruction', async () => {
    const { harness, component } = await screen(); api.priorityUncertain = true;
    for (const status of [401, 403, 404, 409, 200]) {
      api.priorityResult = null; await component.inspectFindings(21); await component.inspectPriority(100); draft(component); await component.savePriority();
      expect(component.priorityPending()).not.toBeNull(); api.priorityResult = { status, body: {} };
      await component.reconcilePriority(); expect(component.priorityPending()).toBeNull(); expect(component.priorityInspection()).toBeNull();
    }
    api.priorityResult = null; api.priorityUncertain = false; await component.inspectFindings(21);
    let resolve!: (row: ApiResult) => void; const reads = api.priorityReads.length;
    api.priorityPromise = new Promise(done => resolve = done); const reading = component.inspectPriority(100);
    await vi.waitFor(() => expect(api.priorityReads).toHaveLength(reads + 1)); harness.fixture.destroy();
    resolve(await api.priorityResponse(family)); await reading; expect(component.priorityInspection()).toBeNull(); expect(component.priorityPending()).toBeNull();
  });
});

describe('Exact passive priority AccountApi commands', () => {
  it('uses five fixed exact-job/Finding queryless bodyless GET and exact CSRF POST with private same-origin fetch', async () => {
    const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) })); vi.stubGlobal('fetch', fetcher);
    try {
      const api = TestBed.inject(AccountApi); const data = { source_sha256: 'c'.repeat(64), expected_revision: 0,
        priority: 'unprioritized', estimated_effort: 'unknown', business_relevance: 'unknown', reason: 'Human only' };
      const methods = [api.passiveHeaderPriority, api.passiveResourcePriority, api.passiveTlsPriority, api.passiveRedirectPriority, api.passiveRedirectChainPriority];
      for (const method of methods) { await method.call(api, 7, 9, 21, 100); await method.call(api, 7, 9, 21, 100, data); }
      const calls = (fetcher.mock.calls as unknown as [string, RequestInit][]).filter(([path]) => path.startsWith('/api/'));
      expect(calls.map(([path]) => path)).toEqual(['headers', 'resources', 'tls', 'redirects', 'redirect-chain'].flatMap(family => Array(2).fill(`/api/organizations/7/projects/9/passive-${family}/21/findings/100/priority/`)));
      for (const [index, [, options]] of calls.entries()) {
        expect(options.cache).toBe('no-store'); expect(options.credentials).toBe('same-origin');
        expect(options.method).toBe(index % 2 ? 'POST' : 'GET'); expect(options.body).toBe(index % 2 ? JSON.stringify(data) : undefined);
        if (index % 2) expect(options.headers).toHaveProperty('X-CSRFToken');
      }
    } finally { vi.unstubAllGlobals(); }
  });
});

describe('Exact passive header native consumers', () => {
  let api: FixtureApi;
  beforeEach(() => { api = new FixtureApi(); TestBed.configureTestingModule({ providers: [provideRouter([
    { path: 'headers/:organizationId/:projectId', component: PassiveHeaders }, { path: 'away', component: PassiveHeaders },
  ]), { provide: AccountApi, useValue: api }] }); });
  async function screen() {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/headers/7/9', PassiveHeaders);
    await harness.fixture.whenStable(); harness.detectChanges(); return { harness, component };
  }
  async function preview(component: PassiveHeaders) { component.editUrl(ORIGIN + '/'); component.editPermission(true); await component.preview(); }
  it('keeps invalid unavailable or denied passive preference and fresh production English', async () => {
    const preference = vi.spyOn(api, 'productLanguage');
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    const harness = await RouterTestingHarness.create();
    try {
      for (const mode of ['invalid', 'incompatible', 'denied', 'unavailable', 'production'] as const) {
        buildEnvironment.production = mode === 'production';
        if (mode === 'unavailable') preference.mockRejectedValue(new Error('private preference error'));
        else preference.mockResolvedValue(mode === 'denied' ? { status: 403, body: { detail: 'private preference error' } }
          : { status: 200, body: { language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: mode === 'incompatible' ? 'tr' : 'en', current_email_language: 'en' } });
        const component = await harness.navigateByUrl('/headers/7/9', PassiveHeaders);
        await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.busy()).toBe(false)); harness.detectChanges();
        expect(TestBed.inject(Title).getTitle()).toBe('Private exact response-header observations — OrganicSEOOps');
        expect(harness.routeNativeElement?.querySelector('section')?.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Exact public response-header observations');
        expect(harness.routeNativeElement?.textContent).not.toContain('private preference error');
        expect(harness.routeNativeElement?.textContent).not.toContain('Unreviewed Turkish');
        if (mode === 'production') expect(component.productLanguage()).toBe('tr');
        await harness.navigateByUrl('/away'); await harness.fixture.whenStable();
      }
      expect(api.commands).toEqual([]); expect(api.ownership).toEqual([]); expect(api.previews).toBe(0);
    } finally { buildEnvironment.production = production; preference.mockRestore(); }
  });
  it('rejects array verification states while retaining the three scalar date and revocation contracts', async () => {
    const { component } = await screen();
    for (const state of ['pending', 'verified', 'revoked']) {
      const row = { ...verification(), state, verified_at: state === 'pending' ? null : DATE, revoked_at: state === 'revoked' ? LATER : null };
      api.verifications = [{ ...row, state: [state] }]; await component.load();
      expect(component.ready()).toBe(false); expect(component.verifications()).toEqual([]);
      expect(component.origins()).toEqual([]); expect(component.permission()).toBe(false);
      api.verifications = [row]; await component.load();
      expect(component.ready()).toBe(true); expect(component.verifications()[0].state).toBe(state);
    }
    expect(api.commands).toEqual([]); expect(api.ownership).toEqual([]);
  });
  it('rejects array passive job states and categories without changing scalar history', async () => {
    const { component } = await screen();
    for (const [field, values] of [['status', ['queued', 'running', 'succeeded', 'failed', 'cancelled']],
      ['error_category', ['', 'cancel_requested', 'actor_revoked']]] as const) {
      for (const value of values) {
        api.rows = [{ ...job(), [field]: [value] } as unknown as ReturnType<typeof job>]; await component.load();
        expect(component.ready()).toBe(false); expect(component.jobs()).toEqual([]);
        api.rows = [{ ...job(), [field]: value }]; await component.load();
        expect(component.ready()).toBe(true); expect(component.jobs()[0][field]).toBe(value);
      }
    }
    expect(api.commands).toEqual([]); expect(api.lookups).toEqual([]);
  });
  it('rejects array header-presence labels in exact original evidence and retains all scalar labels', async () => {
    const { component } = await screen(); api.rows = [{ ...job(), status: 'succeeded' }]; await component.load();
    for (const header of Object.keys(evidence().collection.evidence.headers)) {
      for (const state of ['absent', 'present_empty', 'present_nonempty', 'multiple_fields']) {
        const row = evidence(); (row.collection.evidence.headers as Record<string, unknown>)[header] = [state];
        api.detail = { status: 200, body: { organization_id: 7, project_id: 9, job: api.rows[0], evidence: row } };
        await component.inspect(21); expect(component.evidence()).toBeNull(); expect(component.selected()).toBeNull();
        row.collection.evidence.headers[header] = state; await component.inspect(21);
        expect(component.evidence()).toEqual(row);
      }
    }
    expect(api.commands).toEqual([]); expect(api.ownership).toEqual([]);
  });
  it('treats array ownership-check acknowledgment states as uncertain without claiming or replaying a check', async () => {
    const { component } = await screen(); const pending = { ...verification(), state: 'pending', verified_at: null };
    api.verifications = [pending]; await component.load(); const ownership = vi.spyOn(api, 'originVerifications');
    for (const status of ['queued', 'running', 'succeeded', 'failed', 'cancelled']) {
      ownership.mockResolvedValueOnce({ status: 202, body: { verification: pending, job: { id: 22, handler: 'verify_project_origin', status: [status] } } });
      await component.verify(component.verifications()[0]);
      expect(component.message()).toContain('uncertain or denied'); expect(component.message()).not.toContain('check queued');
      expect(component.verifications()[0].state).toBe('pending'); expect(component.challenge()).toBeNull();
      const count = ownership.mock.calls.length; await Promise.resolve(); expect(ownership).toHaveBeenCalledTimes(count);
      ownership.mockResolvedValueOnce({ status: 202, body: { verification: pending, job: { id: 22, handler: 'verify_project_origin', status } } });
      await component.verify(component.verifications()[0]); expect(component.message()).toContain('not proof of verification');
      expect(component.verifications()[0].state).toBe('pending');
    }
    expect(api.commands).toEqual([]); ownership.mockRestore();
  });
  it('requires a scalar current role before ownership or private passive history reads', async () => {
    const { component } = await screen();
    const ownership = vi.spyOn(api, 'originVerifications'); const history = vi.spyOn(api, 'passiveHeaders');
    for (const role of [['owner'], ['admin'], ['member'], ['viewer'], null, {}, 'unknown', 'member', 'viewer']) {
      api.role = role; ownership.mockClear(); history.mockClear(); await component.load();
      expect(component.ready()).toBe(false); expect(component.origins()).toEqual([]);
      expect(component.verifications()).toEqual([]); expect(component.jobs()).toEqual([]);
      expect(component.permission()).toBe(false); expect(component.challenge()).toBeNull();
      expect(ownership).not.toHaveBeenCalled(); expect(history).not.toHaveBeenCalled();
      await preview(component); await component.launch();
      expect(api.commands).toEqual([]); expect(api.previews).toBe(0);
    }
    for (const role of ['owner', 'admin']) {
      api.role = role; ownership.mockClear(); history.mockClear(); await component.load();
      expect(component.ready()).toBe(true); expect(component.origins()).toEqual([ORIGIN]);
      expect(ownership).toHaveBeenCalledOnce(); expect(history).toHaveBeenCalledOnce();
    }
  });
  it.each(['en', 'tr'] as const)('uses only actual explicit ownership setup/check/revoke and never persists or retrieves the once-shown challenge in %s', async (language) => {
    api.savedProductLanguage = language;
    const { harness, component } = await screen(); const storage = vi.spyOn(Storage.prototype, 'setItem');
    expect(api.ownership).toEqual([]); expect(api.commands).toEqual([]); expect(component.permission()).toBe(false);
    component.editOrigin(ORIGIN); await component.createChallenge(); harness.detectChanges();
    expect(component.challenge()?.content).toBe('a'.repeat(43)); expect(harness.routeNativeElement!.textContent).toContain(ORIGIN + PATH);
    retainDraftLanguage(harness, component, api, language);
    expect(harness.routeNativeElement!.querySelector('pre')?.getAttribute('lang')).toBe('en');
    expect(api.ownership[0]).toEqual(['POST', { origin: ORIGIN }, undefined]);
    await component.verify(component.verifications()[0]); expect(component.challenge()).toBeNull();
    expect(api.ownership[1][2]).toBe(11); expect(component.message()).toContain('not proof of verification');
    await component.revoke(component.verifications()[0]); expect(api.ownership[2]).toEqual(['DELETE', undefined, 11]);
    expect(component.verifications()[0].state).toBe('revoked'); expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
    api.uncertain = true; await component.createChallenge(); expect(component.challenge()).toBeNull();
    const count = api.ownership.length; await component.load(); expect(api.ownership.length).toBe(count); expect(component.challenge()).toBeNull();
  });
  it.each(['en', 'tr'] as const)('requires initially unchecked separate permission, valid canonical scope and fresh unchanged preview before the one-unit command in %s', async (language) => {
    api.savedProductLanguage = language;
    const { harness, component } = await screen(); component.editUrl(ORIGIN + '/'); await component.preview();
    expect(api.previews).toBe(0); expect(api.commands).toEqual([]);
    for (const url of ['javascript:evil()', ORIGIN + '/?q=x', ORIGIN + '/#x', 'https://foreign.example.invalid/', ORIGIN + ':444/']) {
      component.editUrl(url); component.editPermission(true); await component.preview(); expect(component.selection()).toBeNull();
    }
    await preview(component); retainDraftLanguage(harness, component, api, language); expect(component.selection()).not.toBeNull(); expect(api.commands).toEqual([]); harness.detectChanges();
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Bir dahili işlem birimi' : 'One internal operation unit');
    api.changed = true; await component.launch(); expect(api.commands).toEqual([]); expect(component.error()).toContain('No collection command sent');
    api.changed = false; await preview(component); const frozen = structuredClone(component.selection()); await component.launch();
    expect(api.commands[0]['selection_digest']).toBe(frozen?.selection_digest); expect(api.commands[0]['collection_permission']).toBe(true);
    expect(api.commands[0]['observations']).toEqual(['response_headers']); expect(component.pending()).toBeNull();
  });
  it.each(['en', 'tr'] as const)('reconciles an exact own-actor uncertain key without replay and only deliberately retries unchanged unsaved commands in %s', async (language) => {
    api.savedProductLanguage = language;
    const { harness, component } = await screen(); await preview(component); api.uncertain = true; await component.launch();
    retainDraftLanguage(harness, component, api, language); const frozen = structuredClone(component.pending()); expect(frozen).not.toBeNull();
    await component.reconcile(); expect(component.pending()).toBeNull(); expect(api.commands.length).toBe(1); expect(api.lookups).toEqual([frozen!.key]);
    expect(component.message()).toContain('no command replayed'); api.uncertain = false; api.rows = []; await component.load(); await preview(component);
    api.drop = true; await component.launch(); const unsaved = structuredClone(component.pending()); await component.reconcile();
    expect(component.notFound()).toBe(true); api.changed = true; await component.retry(); expect(api.commands.length).toBe(2);
    expect(component.pending()).toEqual(unsaved); expect(component.notFound()).toBe(false);
    api.changed = false; await component.reconcile(); api.drop = false; await component.retry();
    expect(api.commands[2]).toEqual(api.commands[1]); expect(component.pending()).toBeNull();
  });
  it('reconciles cancellation with current exact detail and never replays or offers collection retry for it', async () => {
    const { component } = await screen(); api.rows = [job()]; await component.load(); api.uncertain = true;
    await component.cancel(21); expect(component.pending()?.jobId).toBe(21); expect(api.commands).toEqual([{}]);
    await component.reconcile(); expect(component.pending()).toBeNull(); expect(component.selected()?.cancel_requested).toBe(true); expect(api.commands).toEqual([{}]);
  });
  it('shows only minimized original response evidence and unknown categories without TLS/security or zero-result claims', async () => {
    const { harness, component } = await screen(); api.rows = [{ ...job(), status: 'succeeded' }]; await component.load();
    api.detail = { status: 200, body: { organization_id: 7, project_id: 9, job: api.rows[0], evidence: evidence() } };
    await component.inspect(21); harness.detectChanges(); expect(component.evidence()).not.toBeNull();
    for (const text of [DATE, '302', 'unclassified_fields', 'one_public_response_not_policy_effectiveness', 'not insecure or secure verdicts']) {
      expect(harness.routeNativeElement!.textContent).toContain(text);
    }
    expect(harness.routeNativeElement!.querySelector('img, script, iframe')).toBeNull(); expect(api.commands).toEqual([]);
    api.detail.body['evidence'] = null; await component.inspect(21); harness.detectChanges();
    expect(component.evidence()).toBeNull(); expect(harness.routeNativeElement!.textContent).toContain('not zero findings');
  });
  it('rejects foreign/extra/raw metadata, invalid calendar/microsecond order, malformed counts and disclosure values', async () => {
    const { component } = await screen(); api.rows = [{ ...job(), status: 'succeeded' }]; await component.load();
    const response = () => ({ status: 200, body: { organization_id: 7, project_id: 9, job: { ...api.rows[0] }, evidence: evidence() } });
    const bad: ApiResult[] = [{ status: 403, body: {} }];
    for (const changes of [{ project_id: 99 }, { raw_headers: 'private' }]) { const row = response(); Object.assign(row.body, changes); bad.push(row); }
    for (const changes of [{ id: 99 }, { created_at: '2026-02-30T00:00:00Z' }, { created_at: LATER, updated_at: DATE }, { error_category: '<img onerror=x>' }, { cancel_requested: true }]) {
      const row = response(); Object.assign(row.body.job, changes); bad.push(row);
    }
    for (const changes of [{ url: 'https://foreign.example.invalid/' }, { observed_at: '2026-01-01T00:00:00' }, { observed_at: '2025-01-01T00:00:00Z' },
      { observed_at: '2026-01-01T00:00:00.000003Z' }, { status: 199 }, { raw_cookie: 'private' }, { interpretation: 'secure' }]) {
      const row = response(); Object.assign(row.body.evidence.collection, changes); bad.push(row);
    }
    for (const changes of [{ observed_fields: 0 }, { parsed_fields: -1 }, { without_secure: 2 }, { raw: 'private' }]) {
      const row = response(); Object.assign(row.body.evidence.collection.evidence.cookies, changes); bad.push(row);
    }
    const disclosure = response(); disclosure.body.evidence.collection.evidence.headers['server'] = '<img onerror=x>'; bad.push(disclosure);
    for (const row of bad) { api.detail = row; await component.inspect(21); expect(component.selected()).toBeNull(); expect(component.evidence()).toBeNull(); }
  });
  it('rejects malformed original source digests, hidden selection fields and invalid ownership records instead of granting permission', async () => {
    const { component } = await screen();
    for (const change of [{ selection_digest: 'a'.repeat(64) }, { estimate_units: 0 }, { project_id: 99 }, { raw: 'private' }]) {
      api.previewResult = await api.preview(); Object.assign(api.previewResult.body, change); await preview(component); expect(component.selection()).toBeNull();
    }
    api.previewResult = await api.preview(); const info = api.previewResult.body['selection'] as Record<string, unknown>;
    (info['binding'] as Record<string, unknown>)['challenge_digest'] = 'private'; await preview(component); expect(component.selection()).toBeNull();
    api.previewResult = null; api.verifications[0]['verified_at'] = '2026-02-30T00:00:00Z'; await component.load(); expect(component.ready()).toBe(false);
    api.verifications = [verification()]; api.role = 'member'; await component.load(); expect(component.ready()).toBe(false); expect(api.commands).toEqual([]);
  });
  it('clears original scope, permission, challenge and evidence on edits, route changes, denied refresh and destruction, discarding late work', async () => {
    const { harness, component } = await screen(); await preview(component); component.editUrl(ORIGIN + '/new');
    expect(component.selection()).toBeNull(); expect(component.permission()).toBe(false);
    component.editUrl(ORIGIN + '/'); component.editPermission(true); let resolve!: (row: ApiResult) => void;
    api.previewPromise = new Promise(done => resolve = done); const late = component.preview();
    component.editUrl(ORIGIN + '/edited'); resolve(await api.preview()); await late; expect(component.selection()).toBeNull();
    api.previewPromise = null; await preview(component); api.rows = [{ ...job(), status: 'succeeded' }];
    let detailResolve!: (row: ApiResult) => void; api.detailPromise = new Promise(done => detailResolve = done); const reading = component.inspect(21);
    await harness.navigateByUrl('/headers/7/10', PassiveHeaders); detailResolve({ status: 200, body: {
      organization_id: 7, project_id: 9, job: api.rows[0], evidence: evidence() } }); await reading;
    expect(component.evidence()).toBeNull(); expect(component.selection()).toBeNull(); expect(component.pending()).toBeNull();
    api.deny = true; await component.load(); expect(component.ready()).toBe(false); expect(component.origins()).toEqual([]);
    api.deny = false; api.detailPromise = null; await harness.navigateByUrl('/headers/7/9', PassiveHeaders); await harness.fixture.whenStable();
    component.editOrigin(ORIGIN); await component.createChallenge(); expect(component.challenge()).not.toBeNull();
    harness.fixture.destroy(); expect(component.challenge()).toBeNull(); expect(component.verifications()).toEqual([]);
  });
  it('denies unsafe route IDs before any API call', async () => {
    const project = vi.spyOn(api, 'projectOnboarding'); const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/headers/7/9007199254740992', PassiveHeaders); await harness.fixture.whenStable(); expect(project).not.toHaveBeenCalled();
  });
  it('uses fixed same-origin no-store AccountApi paths, encoded own-key queries and CSRF-capable explicit methods', async () => {
    const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) })); vi.stubGlobal('fetch', fetcher);
    TestBed.resetTestingModule(); const real = TestBed.inject(AccountApi);
    await real.originVerifications(7, 9, 'POST', { origin: ORIGIN }); await real.originVerifications(7, 9, 'DELETE', undefined, 11);
    await real.passiveHeaders(7, 9, undefined, undefined, 'key&extra=x'); await real.passiveHeaders(7, 9, { collection_permission: true }, undefined, undefined, true);
    const calls = fetcher.mock.calls as unknown as [string, RequestInit][];
    expect(calls.map(([path]) => path)).toEqual(['/_allauth/browser/v1/auth/session', '/api/organizations/7/projects/9/origin-verifications/',
      '/_allauth/browser/v1/auth/session', '/api/organizations/7/projects/9/origin-verifications/11/', '/api/organizations/7/projects/9/passive-headers/?idempotency_key=key%26extra%3Dx',
      '/_allauth/browser/v1/auth/session', '/api/organizations/7/projects/9/passive-headers/selection/']);
    expect(calls.every(([, options]) => options.cache === 'no-store' && options.credentials === 'same-origin')).toBe(true);
    expect(calls[3][1].method).toBe('DELETE'); expect(calls[6][1].method).toBe('POST'); expect(calls[6][1].headers).toHaveProperty('X-CSRFToken');
    vi.unstubAllGlobals();
  });
  it.each(['en', 'tr'] as const)('deliberately reads original factual candidates without collection, risk inference or automatic approval in %s', async (language) => {
    api.savedProductLanguage = language;
    const { harness, component } = await screen(); api.rows = [{ ...job(), status: 'succeeded' }]; await component.load();
    expect(api.candidateCalls).toEqual([]); harness.detectChanges();
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Özgün başlık inceleme adaylarını inceleyin' : 'Inspect original header review candidates');
    const report = headerCandidateReport();
    report.collection.evidence.headers['x-frame-options'] = 'present_empty';
    report.candidates[2] = { detector: 'response_x_frame_options_present_empty_candidate', evidence: { header: 'x-frame-options', state: 'present_empty' } };
    report.collection.evidence.headers['server'] = 'present_nonempty';
    report.candidates.splice(5, 0, { detector: 'response_server_disclosure_candidate', evidence: { header: 'server', state: 'present_nonempty' } });
    report.collection.evidence.cookies.without_secure = 1;
    report.candidates.splice(6, 0, { detector: 'parsed_public_cookie_without_secure_candidate', evidence: { flag: 'without_secure', count: 1, observed_fields: 2, parsed_fields: 1, unclassified_fields: 1 } });
    api.candidateResult = { status: 200, body: { organization_id: 7, project_id: 9, candidates: report } };
    await component.inspectCandidates(21); harness.detectChanges();
    expect(component.candidateReport()).not.toBeNull(); expect(api.candidateCalls).toEqual([21]); expect(api.commands).toEqual([]);
    for (const text of [DATE, '302', language === 'tr' ? 'bu yanıtta yok' : 'absent in this response',
      language === 'tr' ? 'x-frame-options: tek boş alan' : 'x-frame-options: one empty field',
      language === 'tr' ? 'server: tek boş olmayan bilgi ifşa alanı' : 'server: one nonempty disclosure field',
      language === 'tr' ? 'bayrak: Secure' : 'fields without Secure',
      language === 'tr' ? 'tanınan SameSite' : 'recognized SameSite',
      language === 'tr' ? 'yalnızca raporlayan CSP: absent' : 'report-only CSP: absent',
      language === 'tr' ? '1 / 1 ayrıştırılmış herkese açık çerez alanında bulunmayan bayrak: HttpOnly' : '1 of 1 parsed public cookie fields without HttpOnly',
      language === 'tr' ? '1 sınıflandırılmamış alan dışlandı' : '1 unclassified fields excluded',
      language === 'tr' ? 'Yalnızca raporlayan CSP uygulama sağlamaz' : 'Report-only CSP does not provide enforcement',
      language === 'tr' ? 'önem derecesi, onay' : 'not severity, approval']) {
      expect(harness.routeNativeElement!.textContent).toContain(text);
    }
    const originalCandidates = structuredClone(component.candidateReport());
    const captionNode = [...harness.routeNativeElement!.querySelectorAll('li > span')].find(row => row.textContent === component.candidateText(component.candidateRows()[0]))!;
    expect(captionNode.getAttribute('lang')).toBe(language);
    retainDraftLanguage(harness, component, api, language);
    expect(component.candidateReport()).toEqual(originalCandidates);
    expect(harness.routeNativeElement!.querySelector('pre[lang="en"]')?.textContent).toContain(JSON.stringify(component.candidateReport(), null, 2));
    api.rows[0].status = 'queued'; await component.load(); await component.inspectCandidates(21);
    expect(api.candidateCalls).toEqual([21]); expect(component.candidateReport()).toBeNull();
  });
  it('preserves multiple policies, report-only categories and honest eligible-empty versus unavailable results', async () => {
    const { harness, component } = await screen(); api.rows = [{ ...job(), status: 'succeeded' }]; await component.load();
    const report = headerCandidateReport();
    const headers = report.collection.evidence.headers;
    for (const header of ['strict-transport-security', 'content-security-policy', 'x-frame-options', 'x-content-type-options', 'referrer-policy']) headers[header] = 'present_nonempty';
    headers['content-security-policy'] = 'multiple_fields'; headers['content-security-policy-report-only'] = 'present_nonempty';
    report.collection.evidence.cookies.without_httponly = 0; report.collection.evidence.cookies.without_recognized_samesite = 0;
    report.candidates = []; api.candidateResult = { status: 200, body: { organization_id: 7, project_id: 9, candidates: report } };
    await component.inspectCandidates(21); harness.detectChanges();
    expect(component.candidateRows()).toEqual([]); expect(component.candidateReport()).not.toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain('not a clean, secure or whole-site result');
    api.candidateResult = { status: 409, body: {} }; await component.inspectCandidates(21); harness.detectChanges();
    expect(component.candidateReport()).toBeNull(); expect(component.error()).toContain('Missing is not zero candidates');
    expect(harness.routeNativeElement!.textContent).not.toContain('No eligible review candidates');
  });
  it('rejects malformed source, dates, raw fields and candidate facts disagreeing with original categories or parsed counts', async () => {
    const { component } = await screen(); api.rows = [{ ...job(), status: 'succeeded' }]; await component.load();
    const mutations = [
      (row: ReturnType<typeof headerCandidateReport>) => row.source_current = false,
      (row: ReturnType<typeof headerCandidateReport>) => row.job_id = 99,
      (row: ReturnType<typeof headerCandidateReport>) => row.binding.project_id = 99,
      (row: ReturnType<typeof headerCandidateReport>) => row.binding.method_version = 'passive-tls-source-v1',
      (row: ReturnType<typeof headerCandidateReport>) => row.binding.verified_at = LATER,
      (row: ReturnType<typeof headerCandidateReport>) => row.collection.url += '?',
      (row: ReturnType<typeof headerCandidateReport>) => row.collection.observed_at = '2026-02-30T00:00:00Z',
      (row: ReturnType<typeof headerCandidateReport>) => row.candidates[0].evidence.state = 'present_nonempty',
      (row: ReturnType<typeof headerCandidateReport>) => row.candidates[1].evidence.report_only_state = 'present_nonempty',
      (row: ReturnType<typeof headerCandidateReport>) => row.candidates[5].evidence.count = 2,
      (row: ReturnType<typeof headerCandidateReport>) => row.candidates[5].evidence.unclassified_fields = 0,
      (row: ReturnType<typeof headerCandidateReport>) => row.candidates.push(row.candidates[0]),
      (row: ReturnType<typeof headerCandidateReport>) => row.candidates = [],
      (row: ReturnType<typeof headerCandidateReport>) => Object.assign(row, { severity: 'critical' }),
      (row: ReturnType<typeof headerCandidateReport>) => Object.assign(row.collection.evidence, { raw_cookie: 'private' }),
    ];
    for (const mutate of mutations) {
      const report = headerCandidateReport(); mutate(report);
      api.candidateResult = { status: 200, body: { organization_id: 7, project_id: 9, candidates: report } };
      await component.inspectCandidates(21); expect(component.candidateReport()).toBeNull();
    }
    expect(api.commands).toEqual([]);
  });
  it('owns fresh candidate objects and clears them on edits, other inspections, scope changes, destruction and late replies', async () => {
    const { harness, component } = await screen(); api.rows = [{ ...job(), status: 'succeeded' }]; await component.load();
    const report = headerCandidateReport(); api.candidateResult = { status: 200, body: { organization_id: 7, project_id: 9, candidates: report } };
    await component.inspectCandidates(21); report.candidates[0].evidence.state = 'changed';
    expect(component.candidateRows()[0].evidence['state']).toBe('absent');
    component.editPermission(false); expect(component.candidateReport()).toBeNull();
    api.candidateResult = null; await component.inspectCandidates(21); await component.inspect(21); expect(component.candidateReport()).toBeNull();
    let resolve!: (row: ApiResult) => void; api.candidatePromise = new Promise(done => resolve = done);
    const reading = component.inspectCandidates(21); component.editUrl(ORIGIN + '/edited');
    resolve({ status: 200, body: { organization_id: 7, project_id: 9, candidates: headerCandidateReport() } }); await reading;
    expect(component.candidateReport()).toBeNull(); api.candidatePromise = null;
    await component.inspectCandidates(21); await harness.navigateByUrl('/headers/7/10', PassiveHeaders); expect(component.candidateReport()).toBeNull();
    await harness.fixture.whenStable(); await component.inspectCandidates(21); expect(component.candidateReport()).toBeNull();
    await harness.navigateByUrl('/headers/7/9', PassiveHeaders); await harness.fixture.whenStable(); await component.inspectCandidates(21);
    harness.fixture.destroy(); expect(component.candidateReport()).toBeNull();
  });
  it('uses the fixed same-origin no-store candidate GET without a body or command', async () => {
    const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) })); vi.stubGlobal('fetch', fetcher);
    TestBed.resetTestingModule(); const real = TestBed.inject(AccountApi); await real.passiveHeaderCandidates(7, 9, 21);
    const calls = fetcher.mock.calls as unknown as [string, RequestInit][];
    expect(calls).toEqual([['/api/organizations/7/projects/9/passive-headers/21/candidates/', {
      method: 'GET', headers: {}, body: undefined, credentials: 'same-origin', cache: 'no-store' }]]);
    vi.unstubAllGlobals();
  });
  it('never grants header-candidate inspection through another fixed observation family', async () => {
    TestBed.resetTestingModule(); TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] });
    const harness = await RouterTestingHarness.create(); api.rows = [{ ...job(), status: 'succeeded' }];
    for (const family of ['tls', 'resources', 'redirects']) {
      const component = await harness.navigateByUrl(`/passive-${family}/7/9`, PassiveHeaders);
      await harness.fixture.whenStable(); harness.detectChanges(); await component.inspectCandidates(21);
      expect(api.candidateCalls).toEqual([]); expect(component.candidateReport()).toBeNull();
      expect(harness.routeNativeElement!.textContent).not.toContain('Inspect original header review candidates');
    }
  });
  it('independently inspects current findings without saves, then explicitly saves only the freshly unchanged original report SHA', async () => {
    const { harness, component } = await screen(); api.rows = [{ ...job(), status: 'succeeded' }]; await component.load();
    const storage = vi.spyOn(Storage.prototype, 'setItem'); expect(api.findingReads).toEqual([]);
    await component.inspectFindings(21); expect(component.findingInspection()).not.toBeNull(); expect(api.findingCommands).toEqual([]);
    harness.detectChanges(); expect(harness.routeNativeElement!.textContent).toContain('does not mean zero eligible candidates');
    const report = structuredClone(component.candidateReport()); await component.saveFindings();
    expect(api.findingCommands).toEqual([[21, await sha(report)]]); expect(api.commands).toEqual([]); expect(component.findingPending()).toBeNull();
    expect(component.findingInspection()?.findingSet['state']).toBe('current_materialized_facts');
    harness.detectChanges(); for (const text of ['no personal attribution', 'no site request', 'Detection time', DATE, LATER]) expect(harness.routeNativeElement!.textContent).toContain(text);
    expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
  });
  it('requires fresh owner/admin, original ownership/configuration and exactly unchanged candidate facts before POST', async () => {
    const { component } = await screen(); api.rows = [{ ...job(), status: 'succeeded' }]; await component.load(); await component.inspectCandidates(21);
    api.role = 'member'; await component.saveFindings(); expect(api.findingCommands).toEqual([]); expect(component.findingPending()).toBeNull(); expect(component.ready()).toBe(false);
    api.role = 'owner'; await component.load(); await component.inspectCandidates(21);
    api.verifications[0]['state'] = 'revoked'; api.verifications[0]['revoked_at'] = LATER;
    await component.saveFindings(); expect(api.findingCommands).toEqual([]); expect(component.candidateReport()).toBeNull();
    api.verifications = [verification()]; await component.load(); await component.inspectCandidates(21);
    const changed = headerCandidateReport(); changed.binding.actor_id = 2; api.findingResult = await headerFindingResult(false, changed);
    await component.saveFindings(); expect(api.findingCommands).toEqual([]); expect(component.findingPending()).toBeNull();
    expect(component.error()).toContain('No fact-save command sent');
  });
  it('freezes memory-only uncertainty and reconciles a complete original set without replay or attributing another save to this caller', async () => {
    const { harness, component } = await screen(); api.rows = [{ ...job(), status: 'succeeded' }]; await component.load(); await component.inspectCandidates(21);
    api.findingUncertain = true; await component.saveFindings(); const frozen = structuredClone(component.findingPending());
    expect(frozen?.candidateDigest).toBe(await sha(headerCandidateReport())); expect(component.candidateReport()).toBeNull();
    await component.saveFindings(); expect(api.findingCommands).toHaveLength(1);
    await component.reconcileFindings(); expect(component.findingPending()).toBeNull(); expect(api.findingCommands).toHaveLength(1);
    expect(api.findingReads).toEqual([21, 21]); harness.detectChanges(); expect(harness.routeNativeElement!.textContent).toContain('does not identify who saved it');
    expect(component.message()).toContain('No command replayed');
  });
  it('keeps absent-set and lookup-network uncertainty distinct from zero facts or a confirmed no-op and requires deliberate discard', async () => {
    const { component } = await screen(); api.rows = [{ ...job(), status: 'succeeded' }]; await component.load(); await component.inspectCandidates(21);
    api.findingDrop = true; await component.saveFindings(); const frozen = structuredClone(component.findingPending());
    await component.reconcileFindings(); expect(component.findingPending()).toEqual(frozen); expect(component.message()).toContain('not confirmed no-op');
    api.findingPromise = Promise.reject(new Error('lookup unavailable')); await component.reconcileFindings();
    expect(component.findingPending()).toEqual(frozen); expect(component.findingInspection()).toBeNull(); expect(api.findingCommands).toHaveLength(1);
    api.findingPromise = null; component.discardFindingCommand(); expect(component.findingPending()).toBeNull();
    expect(component.message()).toContain('Stored facts may still exist');
    await component.inspectFindings(21); await component.saveFindings(); expect(api.findingCommands).toHaveLength(2);
  });
  it('rejects tampered original digest and full compact fact/identity/date shapes, incomplete or duplicated sets and false current flags', async () => {
    const { component } = await screen(); api.rows = [{ ...job(), status: 'succeeded' }]; await component.load();
    const mutate: ((body: Record<string, any>) => void)[] = [
      body => body['candidate_digest'] = 'a'.repeat(64), body => body['project_id'] = 99, body => body['raw_headers'] = 'private',
      body => body['finding_set'].job_id = 99, body => body['finding_set'].source_current = 1, body => body['finding_set'].state = 'secure',
      body => body['finding_set'].findings.pop(), body => body['finding_set'].findings[1] = body['finding_set'].findings[0],
      body => body['finding_set'].findings[0].id = true, body => body['finding_set'].findings[0].source_passive_header_id = 99,
      body => body['finding_set'].findings[0].detector = 'invented', body => body['finding_set'].findings[0].method_version = 'passive-tls-finding-v1',
      body => body['finding_set'].findings[0].subject += '/other', body => body['finding_set'].findings[0].confidence = 'high',
      body => body['finding_set'].findings[0].fingerprint = 'a'.repeat(64), body => body['finding_set'].findings[0].actor_id = 1,
      body => body['finding_set'].findings[0].detected_at = '2026-02-30T00:00:00Z', body => body['finding_set'].findings[0].detected_at = '2025-01-01T00:00:00Z',
      body => body['finding_set'].findings[0].evidence.collection_sha256 = 'a'.repeat(64), body => body['finding_set'].findings[0].evidence.status = true,
      body => body['finding_set'].findings[0].evidence.binding.actor_id = 99, body => body['finding_set'].findings[0].evidence.fact.state = 'present_empty',
      body => body['finding_set'].findings[0].evidence.raw_cookie = 'secret', body => body['candidates'].candidates = [],
    ];
    for (const change of mutate) {
      const result = await headerFindingResult(true); change(result.body); api.findingResult = result;
      await component.inspectFindings(21); expect(component.findingInspection()).toBeNull(); expect(component.candidateReport()).toBeNull();
    }
    expect(api.findingCommands).toEqual([]);
  });
  it('keeps eligible-empty candidates distinct from a retained empty set and never sends an empty save', async () => {
    const { harness, component } = await screen(); api.rows = [{ ...job(), status: 'succeeded' }]; await component.load();
    const report = headerCandidateReport(); for (const key of Object.keys(report.collection.evidence.headers)) report.collection.evidence.headers[key] = 'multiple_fields';
    report.collection.evidence.cookies.without_httponly = 0; report.collection.evidence.cookies.without_recognized_samesite = 0; report.candidates = [];
    api.findingResult = await headerFindingResult(false, report); await component.inspectFindings(21); await component.saveFindings();
    expect(component.findingInspection()).not.toBeNull(); expect(component.candidateRows()).toEqual([]); expect(api.findingCommands).toEqual([]);
    harness.detectChanges(); expect(harness.routeNativeElement!.textContent).toContain('not a clean, secure or whole-site result');
    api.findingResult = { status: 409, body: {} }; await component.inspectFindings(21); expect(component.findingInspection()).toBeNull();
  });
  it('clears original facts/frozen save on edits, operations, owner/verification loss, denied responses, scope-family changes and destruction; discards late work', async () => {
    const { harness, component } = await screen(); api.rows = [{ ...job(), status: 'succeeded' }]; await component.load();
    await component.inspectFindings(21); component.editPermission(false); expect(component.findingInspection()).toBeNull();
    await component.inspectFindings(21); await component.inspectCandidates(21); expect(component.findingInspection()).toBeNull();
    api.findingUncertain = true; await component.saveFindings(); expect(component.findingPending()).not.toBeNull();
    api.role = 'member'; await component.reconcileFindings(); expect(component.findingPending()).toBeNull(); expect(component.ready()).toBe(false);
    api.role = 'owner'; await component.load(); await component.inspectCandidates(21); await component.saveFindings();
    api.findingResult = { status: 403, body: {} }; await component.reconcileFindings(); expect(component.findingPending()).toBeNull(); expect(component.candidateReport()).toBeNull();
    api.findingResult = null; await component.load(); api.findingUncertain = false;
    let resolve!: (row: ApiResult) => void; api.findingPromise = new Promise(done => resolve = done);
    const waiting = component.inspectFindings(21); component.editUrl(ORIGIN + '/changed'); resolve(await headerFindingResult(true)); await waiting;
    expect(component.findingInspection()).toBeNull(); api.findingPromise = null;
    await component.inspectFindings(21); let resolvePost!: (row: ApiResult) => void;
    const sent = api.findingCommands.length; api.findingPostPromise = new Promise(done => resolvePost = done); const saving = component.saveFindings();
    for (let i = 0; i < 100 && api.findingCommands.length === sent; i++) await new Promise(done => setTimeout(done, 0));
    expect(api.findingCommands.length).toBe(sent + 1); expect(component.findingPending()).not.toBeNull();
    await harness.navigateByUrl('/headers/7/10', PassiveHeaders); resolvePost(await headerFindingResult(true)); await saving;
    expect(component.findingInspection()).toBeNull(); expect(component.findingPending()).toBeNull();
    api.findingPostPromise = null; await harness.navigateByUrl('/headers/7/9', PassiveHeaders); await harness.fixture.whenStable();
    await component.inspectFindings(21); harness.fixture.destroy(); expect(component.findingInspection()).toBeNull(); expect(component.findingPending()).toBeNull();
  });
  it('uses only the fixed GET or SHA-only CSRF POST route, and other three families never call the findings endpoint', async () => {
    TestBed.resetTestingModule(); TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] });
    const harness = await RouterTestingHarness.create(); api.rows = [{ ...job(), status: 'succeeded' }];
    for (const family of ['tls', 'resources', 'redirects']) {
      const component = await harness.navigateByUrl(`/passive-${family}/7/9`, PassiveHeaders); await harness.fixture.whenStable();
      component.candidateReport.set(headerCandidateReport()); await component.inspectFindings(21); await component.saveFindings(); await component.reconcileFindings();
    }
    expect(api.findingReads).toEqual([]); expect(api.findingCommands).toEqual([]);
    const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) })); vi.stubGlobal('fetch', fetcher);
    TestBed.resetTestingModule(); const real = TestBed.inject(AccountApi); await real.passiveHeaderFindings(7, 9, 21); await real.passiveHeaderFindings(7, 9, 21, 'a'.repeat(64));
    const calls = fetcher.mock.calls as unknown as [string, RequestInit][];
    expect(calls.map(([path]) => path)).toEqual(['/api/organizations/7/projects/9/passive-headers/21/findings/', '/_allauth/browser/v1/auth/session', '/api/organizations/7/projects/9/passive-headers/21/findings/']);
    expect(calls[0][1].body).toBeUndefined(); expect(calls[2][1].body).toBe(JSON.stringify({ candidate_digest: 'a'.repeat(64) }));
    expect(calls[2][1].headers).toHaveProperty('X-CSRFToken'); expect(calls.every(([, options]) => options.cache === 'no-store' && options.credentials === 'same-origin')).toBe(true);
    vi.unstubAllGlobals();
  });
  it('withholds late successful POST facts after fresh role/configuration/ownership loss and clears frozen evidence', async () => {
    const { component } = await screen(); api.rows = [{ ...job(), status: 'succeeded' }]; await component.load(); await component.inspectCandidates(21);
    const post = api.passiveHeaderFindings.bind(api);
    vi.spyOn(api, 'passiveHeaderFindings').mockImplementation(async (org, project, id, digest) => {
      const result = await post(org, project, id, digest); if (digest) api.role = 'member'; return result;
    });
    await component.saveFindings(); expect(api.findingCommands).toHaveLength(1); expect(api.findingsSaved).toBe(true);
    expect(component.findingInspection()).toBeNull(); expect(component.findingPending()).toBeNull(); expect(component.candidateReport()).toBeNull();
    expect(component.ready()).toBe(false); expect(component.error()).toContain('stored facts may still exist');
  });
});

describe('Separate exact passive TLS native consumers', () => {
  let api: FixtureApi;
  beforeEach(() => {
    api = new FixtureApi(); api.tls = true;
    TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] });
  });
  async function screen() {
    const harness = await RouterTestingHarness.create();
    const component = await harness.navigateByUrl('/passive-tls/7/9', PassiveHeaders);
    await harness.fixture.whenStable(); harness.detectChanges(); return { harness, component };
  }
  async function preview(component: PassiveHeaders) { component.editOrigin(ORIGIN); component.editPermission(true); await component.preview(); }
  function detail(item = tlsEvidence(), observed = DATE) {
    return { status: 200, body: { organization_id: 7, project_id: 9, job: { ...job(), status: 'succeeded', created_at: observed }, evidence: item } };
  }
  function candidates(report = tlsCandidateReport()): ApiResult { return { status: 200, body: { organization_id: 7, project_id: 9, candidates: report } }; }
  it('independently reads and deliberately saves the exact original TLS SHA and complete date-then-version facts without new work or browser storage', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen();
    await component.load(); harness.detectChanges();
    const storage = vi.spyOn(Storage.prototype, 'setItem'); expect(api.tlsFindingReads).toEqual([]);
    expect(harness.routeNativeElement!.textContent).toContain('Inspect current original TLS findings (no save)');
    const report = twoTlsCandidates(); api.tlsFindingResult = await tlsFindingResult(false, report);
    await component.inspectFindings(21); harness.detectChanges(); expect(api.tlsFindingCommands).toEqual([]);
    expect(component.findingInspection()?.findingSet['state']).toBe('no_retained_materialized_findings');
    expect(harness.routeNativeElement!.textContent).toContain('does not mean zero eligible candidates');
    const read = api.passiveTlsFindings.bind(api);
    vi.spyOn(api, 'passiveTlsFindings').mockImplementation(async (...args) => args[3] ? tlsFindingResult(true, report).then(result => {
      api.tlsFindingCommands.push([args[2], args[3]!]); return result;
    }) : read(...args));
    await component.saveFindings(); harness.detectChanges(); expect(api.tlsFindingCommands).toEqual([[21, await sha(report)]]);
    expect(component.findingPending()).toBeNull(); expect((component.findingInspection()?.findingSet['findings'] as any[])).toHaveLength(2);
    for (const text of [ORIGIN, DATE, LATER, 'dated_tls_fact_not_risk_severity', 'remaining_microseconds -1', 'no personal attribution', 'Detection time', 'no handshake']) {
      expect(harness.routeNativeElement!.textContent).toContain(text);
    }
    const result = await tlsFindingResult(true, report); api.tlsFindingResult = result; await component.inspectFindings(21);
    (result.body['finding_set'] as any).findings[0].evidence.fact.remaining_microseconds = '-2';
    expect((component.findingInspection()?.findingSet['findings'] as any[])[0].evidence.fact.remaining_microseconds).toBe('-1');
    expect(api.commands).toEqual([]); expect(api.findingReads).toEqual([]); expect(api.resourceFindingReads).toEqual([]);
    expect(storage).not.toHaveBeenCalled(); storage.mockRestore(); vi.restoreAllMocks();
  });
  it('preserves independently unavailable dates/version and eligible-empty facts versus absent retained sets without an empty save', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen();
    for (const datesAvailable of [true, false]) for (const version of [null, 'TLSv1', 'TLSv1.2']) {
      const report = tlsCandidateReport(tlsEvidence()); report.candidates = [];
      if (!datesAvailable) Object.assign(report.collection.evidence.certificate_dates, { state: 'unavailable', not_before: null, not_after: null, position: null, remaining_microseconds: null });
      report.collection.evidence.negotiated_tls.version = version;
      report.availability = { certificate_dates: datesAvailable ? 'observed' : 'unavailable', negotiated_version: version === null ? 'unavailable' : 'observed' };
      if (version === 'TLSv1') report.candidates.push({ detector: 'negotiated_tlsv1_or_tlsv1_1_candidate', evidence: { version } });
      api.tlsFindingResult = await tlsFindingResult(version === 'TLSv1', report); await component.inspectFindings(21); harness.detectChanges();
      expect(component.findingInspection()).not.toBeNull(); expect(component.candidateRows()).toHaveLength(version === 'TLSv1' ? 1 : 0);
      expect(harness.routeNativeElement!.textContent).toContain('unavailable value remains independently unknown');
      if (version !== 'TLSv1') {
        await component.saveFindings(); expect(harness.routeNativeElement!.textContent).toContain('not a clean or whole-site result');
        expect(harness.routeNativeElement!.textContent).toContain('No retained materialized findings');
      }
    }
    expect(api.tlsFindingCommands).toEqual([]); api.tlsFindingResult = { status: 409, body: {} }; await component.inspectFindings(21);
    expect(component.findingInspection()).toBeNull(); expect(component.candidateReport()).toBeNull(); expect(component.ready()).toBe(false);
  });
  it('rejects original SHA, compact TLS identity, partial/duplicate/reordered max2 sets and date-version availability/fact tampering', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { component } = await screen();
    const mutations: ((b: any) => void)[] = [
      b => b.candidate_digest = 'a'.repeat(64), b => b.organization_id = 99, b => b.raw_certificate = 'private',
      b => b.candidates.availability.certificate_dates = 'unavailable', b => b.candidates.collection.status = 200,
      b => b.candidates.binding.observations = ['response_headers'], b => b.candidates.candidates.reverse(),
      b => b.finding_set.job_id = 99, b => b.finding_set.source_current = 1, b => b.finding_set.method_version = 'passive-resource-finding-v1',
      b => b.finding_set.state = 'secure', b => b.finding_set.findings.pop(), b => b.finding_set.findings.push(b.finding_set.findings[0]),
      b => b.finding_set.findings[1] = { ...b.finding_set.findings[0], id: 101 },
      b => { b.finding_set.findings.reverse(); b.finding_set.findings.forEach((f: any, i: number) => f.id = 100 + i); },
      b => b.finding_set.findings[0].id = true, b => b.finding_set.findings[0].source_passive_tls_id = 99,
      b => b.finding_set.findings[0].source_passive_header_id = 21, b => b.finding_set.findings[0].subject += '/',
      b => b.finding_set.findings[0].confidence = 'dated_response_fact_not_risk_severity', b => b.finding_set.findings[0].fingerprint = 'a'.repeat(64),
      b => b.finding_set.findings[0].detected_at = '2025-01-01T00:00:00Z', b => b.finding_set.findings[0].detected_at = '2026-02-30T00:00:00Z',
      b => b.finding_set.findings[0].evidence.collection_sha256 = 'a'.repeat(64), b => b.finding_set.findings[0].evidence.source = 'passive_response_headers',
      b => b.finding_set.findings[0].evidence.status = 200, b => b.finding_set.findings[0].evidence.url = ORIGIN + '/',
      b => b.finding_set.findings[0].evidence.availability.negotiated_version = 'unavailable',
      b => b.finding_set.findings[0].evidence.fact.remaining_microseconds = '-2', b => b.finding_set.findings[1].evidence.fact.version = 'TLSv1',
      b => b.finding_set.findings[0].evidence.raw_certificate = 'private', b => b.finding_set.findings[0].actor_id = 1,
    ];
    for (const mutate of mutations) {
      const result = await tlsFindingResult(true, twoTlsCandidates()); mutate(result.body); api.tlsFindingResult = result;
      await component.inspectFindings(21); expect(component.findingInspection()).toBeNull(); expect(component.candidateReport()).toBeNull();
    }
    for (const result of [await headerFindingResult(true), await resourceFindingResult(true)]) {
      api.tlsFindingResult = result; await component.inspectFindings(21); expect(component.findingInspection()).toBeNull();
    }
    expect(api.tlsFindingCommands).toEqual([]);
  });
  it('rechecks original role/configuration/verification immediately before POST and after late success, and denies changed original reports', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { component } = await screen(); const read = api.passiveTlsFindings.bind(api);
    for (const afterPost of [false, true]) for (const lose of [() => api.role = 'member', () => api.verifications = [], () => api.verifications[0]['verified_at'] = LATER,
      () => vi.spyOn(api, 'projectOnboarding').mockImplementation(async (org, project) => ({ status: 200, body: { project: {
        id: project, organization_id: org, role: 'owner', canonical_origin: ORIGIN, aliases: ['https://other.example.invalid'] } } }))]) {
      api.role = 'owner'; api.verifications = [verification()]; await component.load(); await component.inspectTlsCandidates(21);
      const count = api.tlsFindingCommands.length;
      vi.spyOn(api, 'passiveTlsFindings').mockImplementation(async (...args) => { const result = await read(...args); if (!!args[3] === afterPost) lose(); return result; });
      await component.saveFindings(); expect(api.tlsFindingCommands).toHaveLength(count + (afterPost ? 1 : 0));
      expect(component.findingInspection()).toBeNull(); expect(component.findingPending()).toBeNull(); expect(component.candidateReport()).toBeNull();
      expect(component.ready()).toBe(false); vi.restoreAllMocks();
    }
    api.role = 'owner'; api.verifications = [verification()]; await component.load(); await component.inspectTlsCandidates(21);
    const changed = tlsCandidateReport(); changed.binding.actor_id = 2; api.tlsFindingResult = await tlsFindingResult(false, changed);
    const count = api.tlsFindingCommands.length; await component.saveFindings(); expect(api.tlsFindingCommands).toHaveLength(count);
    expect(component.error()).toContain('No fact-save command sent');
  });
  it('freezes original same-job SHA/set in memory and reconciles complete sets without replay or caller attribution; rejects changed retained sets', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen(); await component.inspectTlsCandidates(21);
    api.findingUncertain = true; await component.saveFindings(); const frozen = structuredClone(component.findingPending());
    expect(frozen?.candidateDigest).toBe(await sha(tlsCandidateReport())); expect(frozen?.job.id).toBe(21);
    harness.detectChanges(); expect(harness.routeNativeElement!.textContent).toContain('TLS-fact save outcome is uncertain');
    await component.saveFindings(); await component.inspectFindings(21); expect(api.tlsFindingCommands).toHaveLength(1);
    await component.reconcileFindings(); expect(component.findingPending()).toBeNull(); expect(api.tlsFindingReads).toEqual([21, 21]);
    expect(api.tlsFindingCommands).toHaveLength(1); expect(component.message()).toContain('does not identify who saved it');
    await component.saveFindings(); expect(component.findingPending()?.findingSet['state']).toBe('current_materialized_facts');
    const changed = await tlsFindingResult(true); (changed.body['finding_set'] as any).findings[0].id = 101;
    api.tlsFindingResult = changed; await component.reconcileFindings(); expect(component.findingPending()).toBeNull(); expect(component.findingInspection()).toBeNull();
    expect(component.error()).toContain('changed or became unavailable');
  });
  it('keeps absent-set/network uncertainty distinct from no-op, clears changed original or denied lookups and allows deliberate discard', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { component } = await screen(); await component.inspectTlsCandidates(21); api.findingDrop = true;
    await component.saveFindings(); const frozen = structuredClone(component.findingPending()); await component.reconcileFindings();
    expect(component.findingPending()).toEqual(frozen); expect(component.message()).toContain('not confirmed no-op');
    api.tlsFindingPromise = Promise.reject(new Error('lookup unavailable')); await component.reconcileFindings();
    expect(component.findingPending()).toEqual(frozen); expect(component.findingInspection()).toBeNull(); expect(api.tlsFindingCommands).toHaveLength(1);
    api.tlsFindingPromise = null; const changed = tlsCandidateReport(); changed.binding.actor_id = 2;
    api.tlsFindingResult = await tlsFindingResult(false, changed); await component.reconcileFindings(); expect(component.findingPending()).toBeNull();
    api.tlsFindingResult = null; await component.inspectTlsCandidates(21); await component.saveFindings();
    api.tlsFindingResult = { status: 403, body: {} }; await component.reconcileFindings(); expect(component.findingPending()).toBeNull(); expect(component.ready()).toBe(false);
    api.tlsFindingResult = null; await component.load(); await component.inspectTlsCandidates(21); await component.saveFindings(); component.discardFindingCommand();
    expect(component.findingPending()).toBeNull(); expect(component.message()).toContain('Stored facts may still exist');
  });
  it('clears TLS facts/uncertainty on edits, operations, ownership, route-family-destroy and discards late GET/POST replies', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const view = await screen(); const harness = view.harness; let component = view.component;
    for (const action of [() => component.editOrigin(ORIGIN), () => component.editPermission(false), () => component.editUrl(ORIGIN + '/'),
      () => component.inspect(21), () => component.inspectTlsCandidates(21), () => component.preview(), () => component.load(), () => component.revoke(component.verifications()[0])]) {
      api.verifications = [verification()]; await component.load(); await component.inspectTlsCandidates(21); api.findingUncertain = true;
      await component.saveFindings(); expect(component.findingPending()).not.toBeNull(); await action();
      expect(component.findingPending()).toBeNull(); expect(component.findingInspection()).toBeNull();
    }
    api.verifications = [verification()]; await component.load(); let resolve!: (result: ApiResult) => void;
    api.tlsFindingPromise = new Promise(done => resolve = done); const editing = component.inspectFindings(21);
    component.editPermission(false); resolve(await tlsFindingResult(true)); await editing; expect(component.findingInspection()).toBeNull(); api.tlsFindingPromise = null;
    await component.inspectTlsCandidates(21); api.findingUncertain = false; api.tlsFindingPostPromise = new Promise(done => resolve = done);
    const count = api.tlsFindingCommands.length; const saving = component.saveFindings();
    for (let i = 0; i < 100 && api.tlsFindingCommands.length === count; i++) await new Promise(done => setTimeout(done, 0));
    expect(api.tlsFindingCommands).toHaveLength(count + 1); await harness.navigateByUrl('/passive-tls/7/10', PassiveHeaders); await harness.fixture.whenStable();
    const error = component.error(); resolve({ status: 403, body: {} }); await saving;
    expect(component.error()).toBe(error); expect(component.findingPending()).toBeNull(); api.tlsFindingPostPromise = null;
    component = await harness.navigateByUrl('/passive-tls/7/9', PassiveHeaders); await harness.fixture.whenStable();
    api.tlsFindingPromise = new Promise(done => resolve = done); const family = component.inspectFindings(21);
    await harness.navigateByUrl('/passive-redirects/7/9', PassiveHeaders); resolve(await tlsFindingResult(true)); await family; expect(component.findingInspection()).toBeNull();
    api.tlsFindingPromise = null; component = await harness.navigateByUrl('/passive-tls/7/9', PassiveHeaders); await harness.fixture.whenStable();
    api.tlsFindingPromise = new Promise(done => resolve = done); const destroying = component.inspectFindings(21);
    harness.fixture.destroy(); resolve(await tlsFindingResult(true)); await destroying; expect(component.findingInspection()).toBeNull(); expect(component.findingPending()).toBeNull();
  });
  it('keeps commands family-fixed and uses only bodyless GET or SHA-only CSRF POST for TLS', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const harness = await RouterTestingHarness.create();
    for (const family of ['headers', 'resources', 'redirects']) {
      const component = await harness.navigateByUrl(`/passive-${family}/7/9?passiveObservation=tls`, PassiveHeaders); await harness.fixture.whenStable();
      component.candidateReport.set(tlsCandidateReport()); await component.saveFindings(); harness.detectChanges();
      expect(harness.routeNativeElement!.textContent).not.toContain('Explicitly save these original TLS facts');
    }
    expect(api.tlsFindingReads).toEqual([]); expect(api.tlsFindingCommands).toEqual([]); expect(api.findingReads).toEqual([]); expect(api.resourceFindingReads).toEqual([]);
    const component = await harness.navigateByUrl('/passive-tls/7/9', PassiveHeaders); await harness.fixture.whenStable();
    for (const report of [headerCandidateReport(), resourceCandidateReport()]) { component.candidateReport.set(report); await component.saveFindings(); }
    expect(api.tlsFindingReads).toEqual([]);
    const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) })); vi.stubGlobal('fetch', fetcher);
    TestBed.resetTestingModule(); const real = TestBed.inject(AccountApi); await real.passiveTlsFindings(7, 9, 21); await real.passiveTlsFindings(7, 9, 21, 'a'.repeat(64));
    const calls = fetcher.mock.calls as unknown as [string, RequestInit][];
    expect(calls.map(([path]) => path)).toEqual(['/api/organizations/7/projects/9/passive-tls/21/findings/', '/_allauth/browser/v1/auth/session', '/api/organizations/7/projects/9/passive-tls/21/findings/']);
    expect(calls[0][1].method).toBe('GET'); expect(calls[0][1].body).toBeUndefined(); expect(calls[2][1].method).toBe('POST');
    expect(calls[2][1].body).toBe(JSON.stringify({ candidate_digest: 'a'.repeat(64) })); expect(calls[2][1].headers).toHaveProperty('X-CSRFToken');
    expect(calls.every(([, options]) => options.cache === 'no-store' && options.credentials === 'same-origin')).toBe(true); vi.unstubAllGlobals();
  });
  it.each(['en', 'tr'] as const)('deliberately inspects exact original date/version facts, owns fresh objects and never automatically saves or requests another handshake in %s', async (language) => {
    api.savedProductLanguage = language;
    api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen();
    expect(api.tlsCandidateCalls).toEqual([]); const storage = vi.spyOn(Storage.prototype, 'setItem');
    const report = tlsCandidateReport(); report.collection.evidence.negotiated_tls.version = 'TLSv1.1';
    report.candidates.push({ detector: 'negotiated_tlsv1_or_tlsv1_1_candidate', evidence: { version: 'TLSv1.1' } });
    api.tlsCandidateResult = candidates(report); await component.inspectTlsCandidates(21); harness.detectChanges();
    expect(api.tlsCandidateCalls).toEqual([21]); expect(component.candidateRows()).toHaveLength(2);
    for (const text of [DATE, ORIGIN, 'remaining_microseconds -1', language === 'tr' ? 'Gerçek özgün müzakere edilen sürüm: TLSv1.1' : 'Actual original negotiated version: TLSv1.1', language === 'tr' ? 'desteklenen sunucu yapılandırması' : 'not supported server configuration', language === 'tr' ? 'güncel sertifika doğrulaması değildir' : 'not current certificate validation']) {
      expect(harness.routeNativeElement!.textContent).toContain(text);
    }
    const originalCandidates = structuredClone(component.candidateReport());
    const captionNode = [...harness.routeNativeElement!.querySelectorAll('li > span')].find(row => row.textContent === component.candidateText(component.candidateRows()[0]))!;
    expect(captionNode.getAttribute('lang')).toBe(language);
    retainDraftLanguage(harness, component, api, language);
    expect(component.candidateReport()).toEqual(originalCandidates);
    expect(harness.routeNativeElement!.querySelector('pre[lang="en"]')?.textContent).toContain(JSON.stringify(component.candidateReport(), null, 2));
    const caption = [...harness.routeNativeElement!.querySelectorAll('p')].find(row => row.textContent?.includes(language === 'tr' ? '· tam köken' : '· exact origin'))!;
    expect(caption.textContent).toContain((language === 'tr' ? '· tam köken ' : '· exact origin ') + ORIGIN);
    expect([...caption.querySelectorAll('span[lang="en"]')].some(row => row.textContent === ORIGIN)).toBe(true);
    retainDraftLanguage(harness, component, api, language);
    expect(caption.textContent).toContain(ORIGIN);
    report.candidates[0].evidence.remaining_microseconds = '-2'; expect(component.candidateRows()[0].evidence['remaining_microseconds']).toBe('-1');
    expect(api.findingReads).toEqual([]); expect(api.resourceFindingReads).toEqual([]); expect(api.findingCommands).toEqual([]); expect(api.resourceFindingCommands).toEqual([]);
    expect(api.tlsFindingReads).toEqual([]); expect(api.tlsFindingCommands).toEqual([]);
    expect(api.commands).toEqual([]); expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
    expect(harness.routeNativeElement!.querySelector('img, script, iframe')).toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Bu özgün TLS olgularını açıkça kaydedin' : 'Explicitly save these original TLS facts');
  });
  it('preserves inclusive bounds, exact signed microseconds and independently nullable date/version evidence versus eligible-empty', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen();
    const boundary = '2026-01-01T00:00:00.000000+00:00'; const next = '2026-01-01T00:00:01.000000+00:00';
    for (const [observed, start, end, position, remaining] of [
      [boundary, boundary, boundary, 'within_reported_window', '0'], [DATE, next, next, 'before_reported_window', '999999'],
      [DATE, boundary, boundary, 'after_reported_window', '-1'],
    ]) {
      api.rows = [{ ...job(), status: 'succeeded', created_at: observed }]; await component.load();
      const report = tlsCandidateReport(tlsEvidence(observed, start, end));
      report.binding.verified_at = boundary; api.verifications = [{ ...verification(), created_at: boundary, verified_at: boundary }];
      report.candidates = position === 'within_reported_window' ? [] : [{ detector: 'reported_certificate_date_outside_window_candidate', evidence: {
        not_before: start, not_after: end, position, remaining_microseconds: remaining } }];
      api.tlsCandidateResult = candidates(report); await component.inspectTlsCandidates(21); expect(component.candidateReport()).not.toBeNull();
    }
    api.rows = [{ ...job(), status: 'succeeded' }]; api.verifications = [verification()]; await component.load();
    for (const datesAvailable of [true, false]) for (const version of [null, 'TLSv1', 'TLSv1.2', 'TLSv1.3']) {
      const report = tlsCandidateReport(tlsEvidence()); report.candidates = [];
      if (!datesAvailable) Object.assign(report.collection.evidence.certificate_dates, { state: 'unavailable', not_before: null, not_after: null, position: null, remaining_microseconds: null });
      report.collection.evidence.negotiated_tls.version = version;
      report.collection.evidence.negotiated_tls.cipher = { name: 'TLSv1', secret_bits: 256 };
      report.availability = { certificate_dates: datesAvailable ? 'observed' : 'unavailable', negotiated_version: version === null ? 'unavailable' : 'observed' };
      if (version === 'TLSv1') report.candidates = [{ detector: 'negotiated_tlsv1_or_tlsv1_1_candidate', evidence: { version } }];
      api.tlsCandidateResult = candidates(report); await component.inspectTlsCandidates(21); expect(component.candidateReport()).not.toBeNull();
      expect(component.candidateRows()).toHaveLength(version === 'TLSv1' ? 1 : 0);
    }
    harness.detectChanges(); expect(harness.routeNativeElement!.textContent).toContain('unavailable value remains independently unknown');
    expect(harness.routeNativeElement!.textContent).toContain('not a clean or whole-site result');
    api.tlsCandidateResult = { status: 409, body: {} }; await component.inspectTlsCandidates(21); harness.detectChanges();
    expect(component.candidateReport()).toBeNull(); expect(component.ready()).toBe(false); expect(component.error()).toContain('Missing is not zero candidates');
    expect(harness.routeNativeElement!.textContent).not.toContain('No eligible review candidates');
  });
  it('rejects full original shape-family-date-interval-availability and candidate-fact tampering', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { component } = await screen();
    const mutations: ((r: any) => void)[] = [
      r => r.job_id = 99, r => r.source_current = 1, r => r.method_version = 'passive-header-candidates-v1', r => r.coverage = 'whole_configuration',
      r => r.interpretation = 'secure', r => r.raw_certificate = 'private', r => r.binding.url = ORIGIN + '/', r => r.binding.actor_id = true,
      r => r.binding.project_id = 99, r => r.binding.method_version = 'passive-header-source-v1', r => r.binding.observations = ['response_headers'],
      r => r.binding.collection_permission = 1, r => r.binding.origin = 'https://foreign.example.invalid', r => r.binding.verified_at = LATER,
      r => r.collection.observed_at = '2026-01-01T00:00:00.000001Z', r => r.collection.observed_at = '2026-02-30T00:00:00.000001+00:00',
      r => r.collection.observed_at = '2026-01-01T00:00:00.000003+00:00', r => r.collection.status = 200,
      r => r.collection.evidence.certificate_dates.not_after = '2026-01-01T00:00:00.000001+00:00',
      r => r.collection.evidence.certificate_dates.remaining_microseconds = '-0', r => r.collection.evidence.certificate_dates.position = 'within_reported_window',
      r => r.collection.evidence.negotiated_tls.cipher.protocol = 'TLSv1', r => r.collection.evidence.negotiated_tls.version = 'TLSv1.4',
      r => r.availability.negotiated_version = 'unavailable', r => r.availability.certificate_dates = 'unavailable', r => r.availability.extra = true,
      r => r.candidates[0].evidence.remaining_microseconds = -1, r => r.candidates[0].evidence.remaining_microseconds = '-2',
      r => r.candidates[0].evidence.not_before = '2025-01-01T00:00:00.000000+00:00', r => r.candidates[0].evidence.extra = 'raw',
      r => r.candidates[0].detector = 'risk', r => r.candidates = [], r => r.candidates.push(r.candidates[0]),
      r => r.candidates.push({ detector: 'negotiated_tlsv1_or_tlsv1_1_candidate', evidence: { version: 'TLSv1' } }),
      r => { r.collection.evidence.negotiated_tls.version = 'TLSv1'; r.candidates.unshift({ detector: 'negotiated_tlsv1_or_tlsv1_1_candidate', evidence: { version: 'TLSv1' } }); },
    ];
    for (const mutate of mutations) { const report = tlsCandidateReport(); mutate(report); api.tlsCandidateResult = candidates(report);
      await component.inspectTlsCandidates(21); expect(component.candidateReport()).toBeNull(); }
    api.tlsCandidateResult = { ...candidates(), body: { ...candidates().body, project_id: 99 } };
    await component.inspectTlsCandidates(21); expect(component.candidateReport()).toBeNull(); expect(api.commands).toEqual([]);
  });
  it('checks fresh role, configured origins and exact original verification after GET before displaying facts', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { component } = await screen();
    const read = api.passiveTlsCandidates.bind(api);
    for (const lose of [() => api.role = 'member', () => api.verifications = [], () => api.verifications[0]['verified_at'] = LATER,
      () => api.verifications[0]['state'] = 'pending']) {
      api.role = 'owner'; api.verifications = [verification()]; await component.load();
      vi.spyOn(api, 'passiveTlsCandidates').mockImplementation(async (org, project, id) => { const result = await read(org, project, id); lose(); return result; });
      await component.inspectTlsCandidates(21); expect(component.candidateReport()).toBeNull(); expect(component.ready()).toBe(false);
      expect(component.verifications()).toEqual([]); expect(component.origins()).toEqual([]); vi.restoreAllMocks();
    }
    api.role = 'owner'; api.verifications = [verification()]; await component.load();
    vi.spyOn(api, 'projectOnboarding').mockImplementation((org, project) => Promise.resolve({ status: 200, body: { project: {
      id: project, organization_id: org, role: 'owner', canonical_origin: ORIGIN, aliases: ['https://added.example.invalid'] } } }));
    await component.inspectTlsCandidates(21); expect(component.candidateReport()).toBeNull(); expect(component.ready()).toBe(false);
    vi.restoreAllMocks();
  });
  it('clears facts on edits, operations, ownership commands, denied refresh and late route/family/destroy responses', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen();
    for (const clear of [() => component.editOrigin(ORIGIN), () => component.editPermission(false), () => component.editUrl(ORIGIN + '/'),
      () => component.inspect(21), () => component.preview(), () => component.load(), () => component.revoke(component.verifications()[0])]) {
      api.verifications = [verification()]; await component.load(); await component.inspectTlsCandidates(21); expect(component.candidateReport()).not.toBeNull();
      await clear(); expect(component.candidateReport()).toBeNull();
    }
    api.verifications = [verification()]; await component.load();
    for (const status of [401, 403, 404, 409]) { api.tlsCandidateResult = { status, body: {} }; await component.inspectTlsCandidates(21);
      expect(component.ready()).toBe(false); expect(component.candidateReport()).toBeNull(); await component.load(); }
    api.tlsCandidateResult = null;
    let resolve!: (r: ApiResult) => void; api.tlsCandidatePromise = new Promise(done => resolve = done);
    const reading = component.inspectTlsCandidates(21); component.editOrigin(ORIGIN); resolve(candidates()); await reading; expect(component.candidateReport()).toBeNull();
    api.tlsCandidatePromise = new Promise(done => resolve = done); const scoped = component.inspectTlsCandidates(21);
    await harness.navigateByUrl('/passive-tls/7/10', PassiveHeaders); resolve(candidates()); await scoped; expect(component.candidateReport()).toBeNull();
    api.tlsCandidatePromise = null; await harness.navigateByUrl('/passive-tls/7/9', PassiveHeaders); await harness.fixture.whenStable();
    api.tlsCandidatePromise = new Promise(done => resolve = done); const family = component.inspectTlsCandidates(21);
    await harness.navigateByUrl('/passive-redirects/7/9', PassiveHeaders); resolve(candidates()); await family; expect(component.candidateReport()).toBeNull();
    api.tlsCandidatePromise = null; const current = await harness.navigateByUrl('/passive-tls/7/9', PassiveHeaders); await harness.fixture.whenStable();
    api.tlsCandidatePromise = new Promise(done => resolve = done); const destroyed = current.inspectTlsCandidates(21);
    harness.fixture.destroy(); resolve(candidates()); await destroyed; expect(current.candidateReport()).toBeNull(); expect(current.ready()).toBe(false);
  });
  it('denies another family, unsafe/missing/failed/cancelled jobs and query-family authority without calling the TLS endpoint', async () => {
    const { harness, component } = await screen();
    for (const row of [job(), { ...job(), status: 'failed' }, { ...job(), status: 'succeeded', cancel_requested: true }]) {
      api.rows = [row]; await component.load(); await component.inspectTlsCandidates(21);
    }
    await component.inspectTlsCandidates(0); await component.inspectTlsCandidates(9007199254740992); await component.inspectTlsCandidates(99);
    api.rows = [{ ...job(), status: 'succeeded' }];
    for (const family of ['headers', 'resources', 'redirects']) {
      const current = await harness.navigateByUrl(`/passive-${family}/7/9?passiveObservation=tls`, PassiveHeaders); await harness.fixture.whenStable();
      await current.inspectTlsCandidates(21); harness.detectChanges(); expect(current.candidateReport()).toBeNull();
      expect(harness.routeNativeElement!.textContent).not.toContain('Inspect original certificate-date and negotiated-version review candidates');
    }
    expect(api.tlsCandidateCalls).toEqual([]);
  });
  it('uses only the fixed bodyless same-origin no-store TLS candidate GET', async () => {
    const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) })); vi.stubGlobal('fetch', fetcher);
    TestBed.resetTestingModule(); const real = TestBed.inject(AccountApi); await real.passiveTlsCandidates(7, 9, 21);
    expect(fetcher.mock.calls).toEqual([['/api/organizations/7/projects/9/passive-tls/21/candidates/', {
      method: 'GET', headers: {}, body: undefined, credentials: 'same-origin', cache: 'no-store' }]]); vi.unstubAllGlobals();
  });
  it.each(['en', 'tr'] as const)('uses actual reusable ownership with separate initially unchecked exact-origin consent and fixed TLS-only commands in %s', async (language) => {
    api.savedProductLanguage = language;
    const { harness, component } = await screen(); const storage = vi.spyOn(Storage.prototype, 'setItem');
    expect(component.permission()).toBe(false); component.editOrigin(ORIGIN); await component.preview(); expect(api.previews).toBe(0);
    await component.createChallenge(); expect(component.challenge()?.content).toBe('a'.repeat(43));
    await component.verify(component.verifications()[0]); expect(component.challenge()).toBeNull();
    expect(component.message()).toContain('not proof'); await component.revoke(component.verifications()[0]);
    expect(api.ownership.map(row => row[0])).toEqual(['POST', 'POST', 'DELETE']);
    await preview(component); retainDraftLanguage(harness, component, api, language); expect(component.selection()).not.toBeNull(); api.changed = true; await component.launch(); expect(api.commands).toEqual([]);
    api.changed = false; await preview(component); await component.launch();
    expect(api.commands[0]['origin']).toBe(ORIGIN); expect(api.commands[0]).not.toHaveProperty('url');
    expect(api.commands[0]['observations']).toEqual(['certificate_dates', 'negotiated_tls']);
    expect(api.families.every(value => value === 'tls')).toBe(true); expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
    harness.detectChanges(); expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'TLS bunları incelemek için gevşetilmez' : 'TLS is never relaxed');
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Başlık izni TLS gözlemine izin vermez' : 'Header permission does not authorize');
  });
  it('freezes original TLS command through uncertain own-key lookup and permits only deliberate unchanged-source retry', async () => {
    const { component } = await screen(); await preview(component); api.uncertain = true; await component.launch();
    const command = structuredClone(component.pending()); await component.reconcile();
    expect(component.pending()).toBeNull(); expect(api.lookups).toEqual([command!.key]); expect(api.commands.length).toBe(1);
    api.uncertain = false; api.rows = []; await component.load(); await preview(component); api.drop = true; await component.launch();
    const unsaved = structuredClone(component.pending()); await component.reconcile(); api.changed = true; await component.retry();
    expect(api.commands.length).toBe(2); expect(component.pending()).toEqual(unsaved);
    api.changed = false; await component.reconcile(); api.drop = false; await component.retry(); expect(api.commands[2]).toEqual(api.commands[1]);
    await component.load(); api.uncertain = true; await component.cancel(21); expect(component.pending()?.jobId).toBe(21);
    await component.reconcile(); expect(component.pending()).toBeNull(); expect(component.selected()?.cancel_requested).toBe(true);
    expect(api.commands).toHaveLength(4); expect(api.commands[3]).toEqual({});
  });
  it('validates original exact microseconds, inclusive bounds, signed decimal count and unavailable null without configuration claims', async () => {
    const { harness, component } = await screen();
    const boundary = '2026-01-01T00:00:00.000000+00:00';
    const next = '2026-01-01T00:00:01.000000+00:00';
    for (const [observed, start, end] of [[boundary, boundary, boundary], [DATE, boundary, boundary], [DATE, next, next],
      [DATE, '0001-01-01T00:00:00.000000+00:00', '9999-12-31T23:59:59.000000+00:00']]) {
      api.detail = detail(tlsEvidence(observed, start, end), observed); await component.inspect(21); expect(component.evidence()).not.toBeNull();
    }
    api.detail = detail(tlsEvidence(DATE, boundary, boundary)); await component.inspect(21); harness.detectChanges();
    expect(harness.routeNativeElement!.textContent).toContain('"remaining_microseconds": "-1"');
    expect(harness.routeNativeElement!.textContent).toContain('after_reported_window');
    const missing = tlsEvidence(); Object.assign(missing.collection.evidence.certificate_dates, { state: 'unavailable', not_before: null,
      not_after: null, position: null, remaining_microseconds: null });
    Object.assign(missing.collection.evidence.negotiated_tls, { version: null, cipher: null });
    api.detail = detail(missing); await component.inspect(21); harness.detectChanges(); expect(component.evidence()).not.toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain('Null/unavailable is not zero');
    expect(harness.routeNativeElement!.querySelector('iframe, img, script')).toBeNull(); expect(api.commands).toEqual([]);
    api.detail = { status: 200, body: { ...detail().body, evidence: null } }; await component.inspect(21); expect(component.evidence()).toBeNull();
  });
  it('withholds foreign, raw, false-method, invalid-calendar, altered microsecond/count and unsupported negotiated data', async () => {
    const { component } = await screen(); const bad: ApiResult[] = [{ status: 403, body: {} }];
    for (const changes of [{ project_id: 99 }, { raw_certificate: 'private' }]) { const row = detail(); Object.assign(row.body, changes); bad.push(row); }
    for (const changes of [{ id: 99 }, { cancel_requested: true }, { error_category: 'server-private' }]) { const row = detail(); Object.assign(row.body.job, changes); bad.push(row); }
    for (const changes of [{ method: 'passive-tls-collection-v1' }, { origin: ORIGIN + '/' }, { origin: 'https://foreign.example.invalid' },
      { observed_at: '2026-01-01T00:00:00.000001Z' }, { observed_at: '2026-01-01T00:00:00.000001' }, { status: 200 }, { url: ORIGIN + '/' }]) {
      const row = detail(); Object.assign(row.body.evidence.collection, changes); bad.push(row);
    }
    for (const changes of [{ not_before: '2020-02-30T00:00:00.000000+00:00' }, { not_before: '2041-01-01T00:00:00.000000+00:00' },
      { not_after: '2040-01-01T00:00:00.000001+00:00' }, { not_after: '2040-01-01T00:00:00Z' }, { remaining_microseconds: 0 },
      { remaining_microseconds: '-0' }, { remaining_microseconds: '00' }, { remaining_microseconds: '1.0' }, { position: 'secure' },
      { state: 'unavailable' }, { subject: 'private' }, { observed_at: LATER }]) {
      const row = detail(); Object.assign(row.body.evidence.collection.evidence.certificate_dates, changes); bad.push(row);
    }
    for (const changes of [{ version: 'TLSv1.4' }, { version: ['TLSv1.3'] }, { protocol_inventory: ['TLSv1.3'] }, { cipher: { name: '<img onerror=x>', secret_bits: 256 } },
      { cipher: { name: 'TLS_AES', secret_bits: true } }, { cipher: { name: 'TLS_AES', secret_bits: 513 } },
      { cipher: { name: 'TLS_AES', secret_bits: 256, protocol: 'TLSv1.2' } }]) {
      const row = detail(); Object.assign(row.body.evidence.collection.evidence.negotiated_tls, changes); bad.push(row);
    }
    for (const row of bad) { api.detail = row; await component.inspect(21); expect(component.selected()).toBeNull(); expect(component.evidence()).toBeNull(); }
  });
  it('rejects mixed header bindings, full-selection digest mismatch and source additions without sending a TLS command', async () => {
    const { component } = await screen();
    for (const changes of [{ url: ORIGIN + '/' }, { method_version: 'passive-header-source-v1' }, { observations: ['response_headers'] },
      { collection_permission: 1 }, { origin: ORIGIN + ':443' }, { verified_at: '2026-02-30T00:00:00Z' }]) {
      api.previewResult = await api.preview(); const selection = api.previewResult.body['selection'] as Record<string, unknown>;
      Object.assign(selection['binding'] as object, changes); api.previewResult.body['selection_digest'] = await sha(selection);
      await preview(component); expect(component.selection()).toBeNull();
    }
    api.previewResult = await api.preview(); api.previewResult.body['selection_digest'] = 'a'.repeat(64); await preview(component);
    expect(component.selection()).toBeNull(); expect(api.commands).toEqual([]);
  });
  it('clears TLS original permission/uncertainty/evidence at edit, route denial and destruction and discards late responses', async () => {
    const { harness, component } = await screen(); await preview(component); component.editOrigin(ORIGIN);
    expect(component.permission()).toBe(false); expect(component.selection()).toBeNull();
    let resolve!: (value: ApiResult) => void; api.previewPromise = new Promise(done => resolve = done);
    component.editPermission(true); const waiting = component.preview(); component.editOrigin('https://foreign.example.invalid');
    resolve(await api.preview()); await waiting; expect(component.selection()).toBeNull(); expect(component.origin()).toBe('');
    api.previewPromise = null; await preview(component); api.uncertain = true; await component.launch(); expect(component.pending()).not.toBeNull();
    await harness.navigateByUrl('/passive-tls/7/10', PassiveHeaders); await harness.fixture.whenStable();
    expect(component.pending()).toBeNull(); expect(component.permission()).toBe(false);
    await harness.navigateByUrl('/passive-tls/7/9', PassiveHeaders); await harness.fixture.whenStable(); expect(component.ready()).toBe(true);
    let resolveDetail!: (value: ApiResult) => void; api.detailPromise = new Promise(done => resolveDetail = done); const read = component.inspect(21);
    expect(component.busy()).toBe(true);
    await harness.navigateByUrl('/passive-tls/7/10', PassiveHeaders); resolveDetail(detail()); await read; expect(component.evidence()).toBeNull();
    api.deny = true; await component.load(); expect(component.ready()).toBe(false); expect(component.origins()).toEqual([]);
    harness.fixture.destroy(); expect(component.verifications()).toEqual([]); expect(component.evidence()).toBeNull();
  });
  it('denies invalid TLS route IDs and ignores query fields as observation-family authority', async () => {
    const project = vi.spyOn(api, 'projectOnboarding'); const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/passive-tls/7/9007199254740992', PassiveHeaders); await harness.fixture.whenStable(); expect(project).not.toHaveBeenCalled();
    await harness.navigateByUrl('/passive-tls/7/9?passiveObservation=headers', PassiveHeaders); await harness.fixture.whenStable();
    expect(api.families).toEqual(['tls']); expect(api.commands).toEqual([]);
  });
  it('uses fixed no-store same-origin TLS routes and encoded own-key requests with CSRF-protected explicit POST only', async () => {
    const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) })); vi.stubGlobal('fetch', fetcher);
    TestBed.resetTestingModule(); const real = TestBed.inject(AccountApi);
    await real.passiveTls(7, 9, undefined, undefined, 'key&extra=x'); await real.passiveTls(7, 9, { origin: ORIGIN }, undefined, undefined, true);
    await real.passiveTls(7, 9, undefined, 21); await real.passiveTls(7, 9, {}, 21);
    const calls = fetcher.mock.calls as unknown as [string, RequestInit][];
    expect(calls.map(([path]) => path)).toEqual(['/api/organizations/7/projects/9/passive-tls/?idempotency_key=key%26extra%3Dx',
      '/_allauth/browser/v1/auth/session', '/api/organizations/7/projects/9/passive-tls/selection/', '/api/organizations/7/projects/9/passive-tls/21/',
      '/_allauth/browser/v1/auth/session', '/api/organizations/7/projects/9/passive-tls/21/']);
    expect(calls.every(([, options]) => options.cache === 'no-store' && options.credentials === 'same-origin')).toBe(true);
    expect(calls[2][1].method).toBe('POST'); expect(calls[5][1].headers).toHaveProperty('X-CSRFToken'); vi.unstubAllGlobals();
  });
});

const HTTP_ORIGIN = 'http://security.example.invalid';
const httpVerification = () => ({ ...verification(), id: 12, origin: HTTP_ORIGIN });
const httpBinding = () => ({ ...binding(), method_version: 'passive-http-redirect-source-v1', origin: HTTP_ORIGIN, url: HTTP_ORIGIN + '/',
  observations: ['http_response_location'], verification_id: 12 });
function httpEvidence(status = 302, state = 'single_classified', scheme: string | null = 'https', sameOrigin: boolean | null = false, counterpart: boolean | null = true) {
  const meaning = 'plaintext_http_location_metadata_not_authenticated_identity_observed_https_followed_upgrade_browser_behavior_or_target_authority';
  return { job_id: 21, source_current: true, collection: { method: 'passive-http-redirect-evidence-v1', url: HTTP_ORIGIN + '/', status,
    observed_at: DATE, interpretation: meaning, evidence: { method_version: 'passive-http-redirect-response-v1', observed_at: DATE,
      coverage: 'one_original_first_http_response_only', interpretation: meaning, response_location: {
        method_version: 'passive-http-response-location-v1', state: 'observed', response_status: status,
        redirect_status: [301, 302, 303, 307, 308].includes(status), location_state: state, target_scheme: scheme, same_origin: sameOrigin,
        same_hostname_default_https: counterpart, coverage: 'one_complete_original_response_status_and_location_fields_only',
        interpretation: 'one_http_response_location_metadata_not_observed_https_followed_upgrade_browser_behavior_or_target_authority' } } } };
}

describe('Independent plaintext HTTP Location native consumers', () => {
  let api: FixtureApi;
  beforeEach(() => { api = new FixtureApi(); api.httpRedirects = true; api.verifications = [verification(), httpVerification()];
    TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] }); });
  async function screen() {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/passive-http-redirects/7/9?passiveObservation=redirects', PassiveHeaders);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.ready()).toBe(true)); harness.detectChanges(); return { harness, component };
  }
  async function preview(component: PassiveHeaders) { component.editUrl(HTTP_ORIGIN + '/'); component.editPermission(true); await component.preview(); }
  function detail(item = httpEvidence()): ApiResult { return { status: 200, body: { organization_id: 7, project_id: 9, job: { ...job(), status: 'succeeded' }, evidence: item } }; }
  it.each(['en', 'tr'] as const)('uses separately configured HTTP ownership, unchecked permission and the original whole-source SHA without HTTPS grants or storage in %s', async (language) => {
    api.savedProductLanguage = language;
    const { harness, component } = await screen(); const storage = vi.spyOn(Storage.prototype, 'setItem');
    const metadata: Record<string, [string, string]> = {
  "http-redirects": [
    "Private plaintext HTTP Location metadata — OrganicSEOOps",
    "Özel düz metin HTTP Location meta verileri — OrganicSEOOps"
  ]
};
    const titles = metadata['http-redirects'];
    expect(TestBed.inject(Title).getTitle()).toBe(titles[language === 'tr' ? 1 : 0]);
    expect(component.permission()).toBe(false); expect(api.commands).toEqual([]); expect(api.families).toEqual(['http-redirects']);
    expect([...harness.routeNativeElement!.querySelectorAll('#header-origin option')].map(row => row.getAttribute('value'))).toEqual(['', HTTP_ORIGIN]);
    component.editOrigin(ORIGIN); expect(component.origin()).toBe(''); component.editOrigin(HTTP_ORIGIN);
    await component.createChallenge(); expect(api.ownership[0]).toEqual(['POST', { origin: HTTP_ORIGIN }, undefined]);
    expect(component.challenge()?.origin).toBe(HTTP_ORIGIN); await component.verify(component.verifications().find(row => row.id === 12)!);
    expect(component.challenge()).toBeNull(); expect(component.message()).toContain('not proof');
    api.verifications = [verification(), httpVerification()]; await component.load(); component.editUrl(HTTP_ORIGIN + '/'); await component.preview(); expect(api.previews).toBe(0);
    for (const url of [ORIGIN + '/', HTTP_ORIGIN + ':80/', HTTP_ORIGIN + ':81/', HTTP_ORIGIN + '/?x=y', HTTP_ORIGIN + '/#x', HTTP_ORIGIN + '/?',
      'http://user@security.example.invalid/', 'HTTP://security.example.invalid/', 'http://foreign.example.invalid/', HTTP_ORIGIN + '/a\\b', HTTP_ORIGIN + '/a/../']) {
      component.editUrl(url); component.editPermission(true); await component.preview(); expect(component.selection()).toBeNull();
    }
    await preview(component); retainDraftLanguage(harness, component, api, language);
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(titles[language === 'tr' ? 0 : 1]);
    component.productLanguage.set(language); harness.detectChanges(); const frozen = structuredClone(component.selection()!); expect(frozen.selection_digest).toBe(await sha(frozen.selection));
    await component.launch(); expect(api.commands).toEqual([{ url: HTTP_ORIGIN + '/', observations: ['http_response_location'], collection_permission: true,
      selection_digest: frozen.selection_digest, idempotency_key: expect.any(String) }]); expect(component.pending()).toBeNull();
    expect(api.families.every(row => row === 'http-redirects')).toBe(true); expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
    harness.fixture.destroy(); TestBed.inject(Title).setTitle('Next route — OrganicSEOOps');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); TestBed.tick();
    expect(TestBed.inject(Title).getTitle()).toBe('Next route — OrganicSEOOps');
  });
  it('rejects full selection/permission/method/hidden-source substitutions and independently requires original HTTP verification', async () => {
    const { component } = await screen();
    const changes: ((row: any) => void)[] = [r => r.method = 'passive-redirect-collection-v1', r => r.binding.method_version = 'passive-redirect-source-v1',
      r => r.binding.observations = ['response_location'], r => r.binding.observations.push('response_headers'), r => r.binding.collection_permission = 1,
      r => r.binding.url = ORIGIN + '/', r => r.binding.origin = ORIGIN, r => r.binding.actor_id = true, r => r.binding.verification_id = 11,
      r => r.binding.verified_at = LATER, r => r.binding.source_digest = 'B'.repeat(64), r => r.binding.challenge_digest = 'private'];
    for (const change of changes) {
      api.verifications = [verification(), httpVerification()]; await component.load(); api.previewResult = await api.preview();
      change(api.previewResult.body['selection']); api.previewResult.body['selection_digest'] = await sha(api.previewResult.body['selection']);
      await preview(component); expect(component.selection()).toBeNull();
    }
    api.previewResult = await api.preview(); api.previewResult.body['selection_digest'] = 'a'.repeat(64); await component.load(); await preview(component);
    expect(component.selection()).toBeNull(); api.previewResult = null; api.verifications = [verification()]; await component.load(); await preview(component);
    expect(component.selection()).toBeNull(); expect(component.ready()).toBe(false); expect(api.commands).toEqual([]);
  });
  it('rechecks role/configuration/exact verification before and after commands, withholding late success and clearing frozen state', async () => {
    const { component } = await screen(); const original = api.passiveHttpRedirects.bind(api);
    for (const afterPost of [false, true]) for (const loss of ['role', 'config', 'verification']) {
      vi.restoreAllMocks(); api.role = 'owner'; api.verifications = [verification(), httpVerification()]; await component.load(); await preview(component);
      const count = api.commands.length;
      vi.spyOn(api, 'passiveHttpRedirects').mockImplementation(async (...args) => { const result = await original(...args);
        if (afterPost ? args[2] !== undefined && !args[5] : args[5]) {
          if (loss === 'role') api.role = 'member'; else if (loss === 'verification') api.verifications = [verification()];
          else vi.spyOn(api, 'projectOnboarding').mockResolvedValue({ status: 200, body: { project: { id: 9, organization_id: 7, role: 'owner', canonical_origin: ORIGIN, aliases: [] } } });
        } return result;
      });
      await component.launch(); expect(api.commands).toHaveLength(count + (afterPost ? 1 : 0)); expect(component.pending()).toBeNull();
      expect(component.selection()).toBeNull(); expect(component.selected()).toBeNull(); expect(component.ready()).toBe(false);
    }
    vi.restoreAllMocks(); api.role = 'owner'; api.verifications = [verification(), httpVerification()]; await component.load(); await preview(component);
    api.changed = true; await component.launch(); expect(component.selection()).toBeNull(); expect(component.pending()).toBeNull();
  });
  it('freezes one uncertain original key in memory and uses GET-only lookup, including missing outcomes, without any retry', async () => {
    const { harness, component } = await screen(); await preview(component); api.uncertain = true; await component.launch();
    const frozen = structuredClone(component.pending()!); await component.launch(); await component.load(); await component.inspect(21); expect(api.commands).toHaveLength(1);
    await component.reconcile(); expect(api.lookups).toEqual([frozen.key]); expect(component.pending()).toBeNull(); expect(api.commands).toHaveLength(1);
    api.rows = []; api.drop = true; await component.load(); await preview(component); await component.launch(); const missing = structuredClone(component.pending());
    await component.reconcile(); expect(component.notFound()).toBe(true); expect(component.pending()).toEqual(missing); expect(component.message()).toContain('remains unknown');
    await component.retry(); harness.detectChanges(); expect(api.commands).toHaveLength(2);
    expect(harness.routeNativeElement!.textContent).not.toContain('Deliberately retry same command');
    component.discardHttpCommand(); expect(component.pending()).toBeNull(); expect(component.message()).toContain('saved job may exist');
  });
  it('clears denied/malformed or source-lost uncertain lookups while retaining only frozen memory for a network failure', async () => {
    const { component } = await screen(); const original = api.passiveHttpRedirects.bind(api);
    for (const status of [401, 403, 404, 409, 200]) {
      await component.load(); await preview(component); api.uncertain = true; await component.launch();
      vi.spyOn(api, 'passiveHttpRedirects').mockResolvedValue({ status, body: {} }); await component.reconcile();
      expect(component.pending()).toBeNull(); expect(component.origins()).toEqual([]); vi.restoreAllMocks();
    }
    await component.load(); await preview(component); await component.launch(); const frozen = structuredClone(component.pending());
    vi.spyOn(api, 'passiveHttpRedirects').mockImplementation(async (...args) => { if (args[4]) throw new Error('network'); return original(...args); });
    await component.reconcile(); expect(component.pending()).toEqual(frozen); vi.restoreAllMocks();
    api.verifications = [verification()]; await component.reconcile(); expect(component.pending()).toBeNull(); expect(component.ready()).toBe(false);
  });
  it('retains metadata and independently cancels after HTTP source loss, reconciling cancellation with exact-job GET only', async () => {
    api.rows = [job()]; const { component } = await screen(); api.verifications = [verification()]; await component.load();
    api.uncertain = true; await component.cancel(21); expect(component.pending()?.jobId).toBe(21); expect(api.commands).toEqual([{}]);
    await component.retry(); await component.reconcile(); expect(component.pending()).toBeNull(); expect(component.selected()?.cancel_requested).toBe(true); expect(api.commands).toEqual([{}]);
  });
  it('preserves original plaintext microseconds/status, all cardinalities and nullable syntax independent of redirect status, without links or Findings', async () => {
    const { harness, component } = await screen();
    for (const status of [200, 301, 302, 303, 307, 308, 404, 599]) {
      for (const state of ['absent', 'present_empty', 'multiple_fields', 'single_unclassified']) {
        api.detail = detail(httpEvidence(status, state, null, null, null)); await component.inspect(21); expect(component.evidence()).not.toBeNull();
      }
      for (const [scheme, sameOrigin, counterpart] of [['http', true, false], ['http', false, false], ['https', false, true], ['https', false, false]] as const) {
        api.detail = detail(httpEvidence(status, 'single_classified', scheme, sameOrigin, counterpart)); await component.inspect(21); expect(component.evidence()).not.toBeNull();
      }
    }
    api.detail = detail(httpEvidence(200)); await component.inspect(21); harness.detectChanges();
    for (const text of [DATE, 'unauthenticated plaintext', 'syntactic only', 'not observed HTTPS availability', 'Null is not zero', 'same_hostname_default_https']) expect(harness.routeNativeElement!.textContent).toContain(text);
    (api.detail.body['evidence'] as any).collection.status = 599; expect((component.evidence()?.['collection'] as any).status).toBe(200);
    expect(harness.routeNativeElement!.querySelectorAll('a')).toHaveLength(1); expect(harness.routeNativeElement!.querySelector('script, img, iframe')).toBeNull();
    await component.inspectCandidates(21); await component.inspectResourceCandidates(21); await component.inspectTlsCandidates(21); await component.inspectRedirectCandidates(21); await component.inspectFindings(21); await component.saveFindings();
    expect(api.candidateCalls.concat(api.resourceCandidateCalls, api.tlsCandidateCalls, api.redirectCandidateCalls)).toEqual([]);
    expect(api.findingReads.concat(api.resourceFindingReads, api.tlsFindingReads, api.redirectFindingReads)).toEqual([]); expect(api.commands).toEqual([]);
  });
  it('rejects complete DTO/date/status/real boolean/counterpart privacy and cross-family substitutions instead of coercing', async () => {
    const { component } = await screen();
    const changes: ((b: any) => void)[] = [b => b.project_id = 10, b => b.raw = 'private', b => b.job.id = 22,
      b => b.job.cancel_requested = true, b => b.job.status = 'failed', b => b.evidence.source_current = 1, b => b.evidence.job_id = 22,
      b => b.evidence.collection.method = 'passive-redirect-evidence-v1', b => b.evidence.collection.url = ORIGIN + '/', b => b.evidence.collection.url += '?x=y',
      b => b.evidence.collection.status = true, b => b.evidence.collection.status = '302', b => b.evidence.collection.status = 600,
      b => b.evidence.collection.observed_at = '2026-01-01T00:00:00.000001Z', b => b.evidence.collection.observed_at = '2026-02-30T00:00:00.000001+00:00',
      b => b.evidence.collection.observed_at = '2026-01-01T00:00:00.000000+00:00', b => b.evidence.collection.observed_at = '2026-01-01T00:00:00.000003+00:00',
      b => b.evidence.collection.evidence.observed_at = LATER, b => b.evidence.collection.evidence.raw_location = 'private',
      b => b.evidence.collection.evidence.method_version = 'passive-redirect-response-v1', b => b.evidence.collection.evidence.coverage = 'whole_site',
      b => b.evidence.collection.evidence.response_location.method_version = 'passive-response-location-v1', b => b.evidence.collection.evidence.response_location.state = 'unavailable',
      b => b.evidence.collection.evidence.response_location.response_status = 301, b => b.evidence.collection.evidence.response_location.redirect_status = 1,
      b => b.evidence.collection.evidence.response_location.same_origin = true, b => b.evidence.collection.evidence.response_location.same_hostname_default_https = 1,
      b => b.evidence.collection.evidence.response_location.same_hostname_default_https = null, b => b.evidence.collection.evidence.response_location.target_scheme = 'http',
      b => b.evidence.collection.evidence.response_location.location_state = 'absent', b => b.evidence.collection.evidence.response_location.target_scheme = ['https'],
      b => b.evidence.collection.evidence.response_location.raw_url = '<img onerror=x>'];
    for (const change of changes) { await component.load(); api.detail = detail(); change(api.detail.body); await component.inspect(21);
      expect(component.evidence()).toBeNull(); expect(component.selected()).toBeNull(); expect(component.ready()).toBe(false); }
    for (const state of ['absent', 'present_empty', 'multiple_fields', 'single_unclassified']) {
      await component.load(); api.detail = detail(httpEvidence(200, state, null, null, false)); await component.inspect(21); expect(component.evidence()).toBeNull();
    }
  });
  it('withholds late valid private evidence after current role/config/verification loss or original verification-date drift', async () => {
    const { component } = await screen(); const original = api.passiveHttpRedirects.bind(api);
    for (const loss of ['role', 'config', 'verification', 'date']) {
      vi.restoreAllMocks(); api.role = 'owner'; api.verifications = [verification(), httpVerification()]; await component.load(); api.detail = detail();
      vi.spyOn(api, 'passiveHttpRedirects').mockImplementation(async (...args) => { const result = await original(...args);
        if (loss === 'role') api.role = 'member'; else if (loss === 'verification') api.verifications = [verification()];
        else if (loss === 'date') api.verifications[1]['verified_at'] = LATER;
        else vi.spyOn(api, 'projectOnboarding').mockResolvedValue({ status: 200, body: { project: { id: 9, organization_id: 7, role: 'owner', canonical_origin: ORIGIN, aliases: [] } } });
        return result;
      });
      await component.inspect(21); expect(component.evidence()).toBeNull(); expect(component.verifications()).toEqual([]); expect(component.ready()).toBe(false);
    }
    vi.restoreAllMocks();
  });
  it('clears edit/ownership/scope/family/destroy state and discards genuinely late preview/detail and command replies', async () => {
    const { harness, component } = await screen(); await preview(component); component.editOrigin(HTTP_ORIGIN);
    expect(component.permission()).toBe(false); expect(component.selection()).toBeNull();
    let resolve!: (result: ApiResult) => void; api.previewPromise = new Promise(done => resolve = done);
    component.editPermission(true); const waiting = component.preview(); component.editUrl(HTTP_ORIGIN + '/edited'); resolve(await api.preview()); await waiting; expect(component.selection()).toBeNull();
    api.previewPromise = null; await preview(component); api.uncertain = true; await component.launch(); component.editPermission(false); expect(component.pending()).toBeNull();
    await preview(component); await component.launch(); await harness.navigateByUrl('/passive-http-redirects/7/10', PassiveHeaders); await harness.fixture.whenStable(); expect(component.pending()).toBeNull();
    const current = await harness.navigateByUrl('/passive-http-redirects/7/9', PassiveHeaders); await harness.fixture.whenStable();
    api.detailPromise = new Promise(done => resolve = done); const reading = current.inspect(21); await vi.waitFor(() => expect(api.families.at(-1)).toBe('http-redirects'));
    await harness.navigateByUrl('/passive-redirects/7/9', PassiveHeaders); resolve(detail()); await reading; expect(current.evidence()).toBeNull();
    api.detailPromise = null; const final = await harness.navigateByUrl('/passive-http-redirects/7/9', PassiveHeaders); await harness.fixture.whenStable();
    api.detailPromise = new Promise(done => resolve = done); const destroying = final.inspect(21); harness.fixture.destroy(); resolve(detail()); await destroying;
    expect(final.origins()).toEqual([]); expect(final.evidence()).toBeNull(); expect(final.permission()).toBe(false);
  });
  it('discards actual late HTTP POST acknowledgements and ownership changes clear permission and observation state', async () => {
    const { harness, component } = await screen(); await preview(component);
    let resolve!: (result: ApiResult) => void; const original = api.passiveHttpRedirects.bind(api);
    vi.spyOn(api, 'passiveHttpRedirects').mockImplementation(async (...args) => args[2] !== undefined && !args[5]
      ? new Promise(done => { api.commands.push(structuredClone(args[2]!)); resolve = done; }) : original(...args));
    const sending = component.launch(); await vi.waitFor(() => expect(api.commands).toHaveLength(1));
    expect(component.pending()).not.toBeNull(); await harness.navigateByUrl('/passive-http-redirects/8/9', PassiveHeaders); await harness.fixture.whenStable();
    resolve({ status: 202, body: { organization_id: 7, project_id: 9, job: job() } }); await sending;
    expect(component.selected()).toBeNull(); expect(component.pending()).toBeNull(); expect(component.permission()).toBe(false);
    vi.restoreAllMocks(); const current = await harness.navigateByUrl('/passive-http-redirects/7/9', PassiveHeaders); await harness.fixture.whenStable(); await preview(current);
    current.editOrigin(HTTP_ORIGIN); current.editPermission(true); await current.createChallenge();
    expect(current.permission()).toBe(false); expect(current.selection()).toBeNull(); expect(current.challenge()).not.toBeNull();
    await current.revoke(current.verifications().find(row => row.id === 12)!); expect(current.challenge()).toBeNull();
    expect(current.verifications().find(row => row.id === 12)?.state).toBe('revoked');
  });
  it('uses only fixed same-origin no-store HTTP routes, encoded own-key GET and CSRF POST; unsafe IDs and query-family input grant nothing', async () => {
    const project = vi.spyOn(api, 'projectOnboarding'); const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/passive-http-redirects/7/9007199254740992', PassiveHeaders); await harness.fixture.whenStable(); expect(project).not.toHaveBeenCalled();
    const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) })); vi.stubGlobal('fetch', fetcher);
    try { TestBed.resetTestingModule(); const real = TestBed.inject(AccountApi);
      await real.passiveHttpRedirects(7, 9); await real.passiveHttpRedirects(7, 9, undefined, undefined, 'key&extra=x');
      await real.passiveHttpRedirects(7, 9, { url: HTTP_ORIGIN + '/' }, undefined, undefined, true);
      await real.passiveHttpRedirects(7, 9, { url: HTTP_ORIGIN + '/' }); await real.passiveHttpRedirects(7, 9, undefined, 21); await real.passiveHttpRedirects(7, 9, {}, 21);
      const calls = (fetcher.mock.calls as unknown as [string, RequestInit][]).filter(([path]) => path.startsWith('/api/'));
      expect(calls.map(([path]) => path)).toEqual(['', '?idempotency_key=key%26extra%3Dx', 'selection/', '', '21/', '21/'].map(suffix => '/api/organizations/7/projects/9/passive-http-redirects/' + suffix));
      expect(calls.map(([, options]) => options.method)).toEqual(['GET', 'GET', 'POST', 'POST', 'GET', 'POST']);
      expect(calls.every(([, options]) => options.credentials === 'same-origin' && options.cache === 'no-store')).toBe(true);
      for (const [, options] of calls) { if (options.method === 'GET') expect(options.body).toBeUndefined(); else expect(options.headers).toHaveProperty('X-CSRFToken'); }
    } finally { vi.unstubAllGlobals(); }
  });
});

const CHAIN_OTHER = 'https://unvisited.example.invalid';
const chainVerifications = () => [verification(), httpVerification(), { ...verification(), id: 13, origin: CHAIN_OTHER }];
const chainInput = () => ({ url: HTTP_ORIGIN + '/', target_urls: [ORIGIN + '/', CHAIN_OTHER + '/'], observations: ['redirect_chain'], collection_permission: true });
function chainBinding(data = chainInput()) {
  return { method_version: 'passive-redirect-chain-source-v1', organization_id: 7, project_id: 9, actor_id: 2, ...data,
    origins: [...new Set([data.url, ...data.target_urls].map(url => new URL(url).origin))].map(origin => {
      const record = chainVerifications().find(row => row.origin === origin)!;
      return { origin, verification_id: record.id, verified_at: record.verified_at };
    }), source_digest: 'b'.repeat(64), interpretation: 'explicit_exact_url_allowlist_not_observed_chain_network_job_or_commercial_reservation' };
}
function chainDetail(data = chainInput(), urls = [HTTP_ORIGIN + '/', ORIGIN + '/']): ApiResult {
  const meaning = 'dated_exact_selected_responses_not_browser_behavior_current_availability_authenticated_http_identity_or_security_verdict';
  const hops = urls.map((url, index) => {
    const last = index === urls.length - 1; const http = url.startsWith('http://'); const from = new URL(url); const to = new URL(urls[index + 1] || url);
    const location = (http ? httpEvidence(last ? 200 : 302, last ? 'absent' : 'single_classified', last ? null : to.protocol.slice(0, -1), last ? null : from.origin === to.origin,
      last ? null : to.protocol === 'https:' && from.hostname === to.hostname) : redirectEvidence(last ? 200 : 302, last ? 'absent' : 'single_classified',
      last ? null : to.protocol.slice(0, -1), last ? null : from.origin === to.origin)).collection.evidence.response_location;
    return { url, status: last ? 200 : 302, observed_at: last ? LATER : DATE, response_location: location, target_state: last ? 'terminal_response' : 'permitted_target' };
  });
  return { status: 200, body: { organization_id: 7, project_id: 9, job: { ...job(), status: 'succeeded' }, evidence: {
    job_id: 21, source_current: true, binding: chainBinding(data), collection: { method: 'passive-exact-redirect-chain-evidence-v1', url: data.url,
      final_url: urls.at(-1), status: hops.at(-1)!.status, observed_at: hops[0].observed_at, last_observed_at: hops.at(-1)!.observed_at,
      interpretation: meaning, evidence: { method_version: 'passive-exact-redirect-chain-response-v1', hops, state: 'terminal_response',
        coverage: 'at_most_six_selected_original_header_responses_only', interpretation: meaning } } } } };
}
class ChainFixtureApi extends FixtureApi {
  input = chainInput();
  chainCandidateCalls: number[][] = []; chainCandidateResult: ApiResult | null = null; chainCandidatePromise: Promise<ApiResult> | null = null;
  chainFindingReads: number[] = []; chainFindingCommands: [number, string][] = [];
  chainFindingResult: ApiResult | null = null; chainFindingPromise: Promise<ApiResult> | null = null;
  chainFindingPostPromise: Promise<ApiResult> | null = null;
  constructor() { super(); this.verifications = chainVerifications(); this.detail = chainDetail(); }
  override projectOnboarding(org: number, project: number) { return Promise.resolve({ status: 200, body: { project: {
    id: project, organization_id: org, role: this.role, canonical_origin: ORIGIN, aliases: [HTTP_ORIGIN, CHAIN_OTHER] } } }); }
  override async preview(org = 7, project = 9): Promise<ApiResult> {
    const selection = { method: 'passive-exact-redirect-chain-evidence-v1', binding: { ...chainBinding(this.input), source_digest: (this.changed ? 'c' : 'b').repeat(64) } };
    return { status: 200, body: { organization_id: org, project_id: project, selection, selection_digest: await sha(selection), estimate_units: 1 } };
  }
  override passiveRedirectChain(org: number, project: number, data?: Record<string, unknown>, id?: number, key?: string, preview = false) {
    if (preview && data) this.input = structuredClone(data) as ReturnType<typeof chainInput>;
    return super.passiveRedirectChain(org, project, data, id, key, preview);
  }
  passiveRedirectChainCandidates(org: number, project: number, id: number): Promise<ApiResult> {
    this.chainCandidateCalls.push([org, project, id]);
    return this.chainCandidatePromise || Promise.resolve(this.chainCandidateResult || chainCandidateResult());
  }
  async passiveRedirectChainFindings(_org: number, _project: number, id: number, digest?: string): Promise<ApiResult> {
    if (digest === undefined) { this.chainFindingReads.push(id);
      return this.chainFindingPromise || this.chainFindingResult || chainFindingResult(this.findingsSaved, this.chainCandidateResult || chainCandidateResult()); }
    this.chainFindingCommands.push([id, digest]);
    if (!this.findingDrop) this.findingsSaved = true;
    if (this.chainFindingPostPromise) return this.chainFindingPostPromise;
    if (this.findingDrop || this.findingUncertain) throw new Error('uncertain');
    return chainFindingResult(true, this.chainCandidateResult || chainCandidateResult());
  }
}
function chainCandidateResult(detail = chainDetail()): ApiResult {
  const original = detail.body['evidence'] as any; const hops = original.collection.evidence.hops; const state = original.collection.evidence.state;
  const transitions = hops.slice(0, -1).flatMap((hop: any, index: number) => hop.url.startsWith('https://') && hops[index + 1].url.startsWith('http://')
    ? [{ from_hop: index, to_hop: index + 1 }] : []);
  const candidates = [];
  if (transitions.length) candidates.push({ detector: 'observed_https_to_http_transition_candidate', evidence: { transitions } });
  if (state === 'redirect_loop' || state === 'redirect_limit') candidates.push({ detector: state === 'redirect_loop' ? 'redirect_chain_loop_stop_candidate' : 'redirect_chain_budget_stop_candidate',
    evidence: { state, observed_hops: hops.length, last_hop: hops.length - 1 } });
  return { status: 200, body: { organization_id: 7, project_id: 9, candidates: { ...original, method_version: 'passive-redirect-chain-candidates-v1',
    availability: { selected_urls: original.binding.target_urls.length + 1, observed_hops: hops.length,
      last_target_metadata: hops.at(-1).response_location.location_state === 'single_classified' ? 'observed' : 'unavailable' }, candidates,
    coverage: 'original_selected_adjacent_scheme_transitions_and_transport_stop_only',
    interpretation: 'dated_selected_scheme_transitions_and_stop_facts_not_current_availability_browser_behavior_authenticated_http_identity_severity_or_target_authority' } } };
}
describe('Deliberate saved original chain candidate inspection', () => {
  let api: ChainFixtureApi;
  beforeEach(() => { api = new ChainFixtureApi(); api.rows = [{ ...job(), status: 'succeeded' }];
    TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] }); });
  async function screen() {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/passive-redirect-chain/7/9?job_id=21&passiveObservation=headers', PassiveHeaders);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.ready()).toBe(true)); harness.detectChanges(); return { harness, component };
  }
  it('requires a deliberate saved-job button and preserves original counts/dates/unvisited provenance, unknowns and meanings without writes, links or persistence', async () => {
    const { harness, component } = await screen(); const storage = vi.spyOn(Storage.prototype, 'setItem');
    expect(api.chainCandidateCalls).toEqual([]); expect(component.candidateReport()).toBeNull();
    Array.from(harness.routeNativeElement!.querySelectorAll('button')).find(button => button.textContent?.includes('Inspect original chain transition'))!.click();
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.busy()).toBe(false)); harness.detectChanges();
    expect(api.chainCandidateCalls).toEqual([[7, 9, 21]]); expect(component.candidateReport()).toEqual(chainCandidateResult().body['candidates']);
    for (const text of ['Originally selected URLs: 3', 'actually captured responses: 2', 'UNVISITED', DATE, LATER, 'Last target syntax is unknown',
      'not a clean, secure', 'not a repeated response', 'not a broken destination', 'authenticated HTTP identity', 'Finding save', 'zero-based']) expect(harness.routeNativeElement!.textContent).toContain(text);
    expect(harness.routeNativeElement!.querySelectorAll('a')).toHaveLength(1); expect(harness.routeNativeElement!.querySelector('img, iframe, script')).toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain('Explicitly save these original chain facts');
    expect(api.findingCommands.concat(api.resourceFindingCommands, api.tlsFindingCommands, api.redirectFindingCommands)).toEqual([]);
    expect(api.commands).toEqual([]); expect(api.previews).toBe(0); expect(api.ownership).toEqual([]); expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
  });
  it.each(['en', 'tr'] as const)('derives only actual adjacent captured HTTPS-to-HTTP indices and literal loop/budget stops, retaining max-path/unknown coverage in %s', async (language) => {
    api.savedProductLanguage = language;
    const { harness, component } = await screen();
    const data = { ...chainInput(), url: ORIGIN + '/', target_urls: [HTTP_ORIGIN + '/', CHAIN_OTHER + '/'] };
    const detail = chainDetail(data, [ORIGIN + '/', HTTP_ORIGIN + '/']); const source = (detail.body['evidence'] as any).collection;
    api.chainCandidateResult = chainCandidateResult(detail); await component.inspectChainCandidates(21); harness.detectChanges();
    expect(component.candidateRows()).toEqual([{ detector: 'observed_https_to_http_transition_candidate', evidence: { transitions: [{ from_hop: 0, to_hop: 1 }] } }]);
    expect(harness.routeNativeElement!.textContent).toContain('0→1');
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Gerçekte bitişik özgün HTTPS→HTTP' : 'Actually adjacent original HTTPS→HTTP');
    retainDraftLanguage(harness, component, api, language);
    for (const state of ['redirect_loop', 'redirect_limit']) {
      const last = source.evidence.hops.at(-1); source.evidence.state = state; source.status = last.status = 302; last.target_state = 'permitted_target';
      last.response_location = httpEvidence(302, 'single_classified', 'https', false, state === 'redirect_loop').collection.evidence.response_location;
      api.chainCandidateResult = chainCandidateResult(detail); await component.inspectChainCandidates(21);
      expect(component.candidateRows()).toHaveLength(2); expect(component.candidateRows()[1].evidence).toEqual({ state, observed_hops: 2, last_hop: 1 });
      harness.detectChanges();
      expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? `Özgün ${state} durma olgusu · 2 yakalanmış yanıt · son sıfır tabanlı adım 1` : `Original ${state} stopping fact · 2 captured responses · last zero-based hop 1`);
      expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Durulan hedeften bir yanıt alındığı ima edilmez' : 'No stopped target response is implied');
    }
    for (const state of ['terminal_response', 'location_unavailable', 'unsupported_target', 'outside_exact_target_allowlist']) {
      const result = chainDetail(); const collection = (result.body['evidence'] as any).collection; const last = collection.evidence.hops.at(-1);
      collection.evidence.state = last.target_state = state;
      if (state !== 'terminal_response') { collection.status = last.status = 302;
        last.response_location = redirectEvidence(302, state === 'location_unavailable' ? 'multiple_fields' : 'single_classified',
          state === 'location_unavailable' ? null : 'https', state === 'location_unavailable' ? null : false).collection.evidence.response_location; }
      api.chainCandidateResult = chainCandidateResult(result); await component.inspectChainCandidates(21); expect(component.candidateReport(), state).not.toBeNull();
      expect(component.candidateRows()).toEqual([]);
    }
    const urls = Array.from({ length: 6 }, (_, i) => (i % 2 ? HTTP_ORIGIN : ORIGIN) + '/' + String(i).repeat(1024 - (i % 2 ? HTTP_ORIGIN : ORIGIN).length - 1));
    api.chainCandidateResult = chainCandidateResult(chainDetail({ ...chainInput(), url: urls[0], target_urls: urls.slice(1) }, urls));
    await component.inspectChainCandidates(21); expect(component.candidateRows()[0].evidence).toEqual({ transitions: [{ from_hop: 0, to_hop: 1 }, { from_hop: 2, to_hop: 3 }, { from_hop: 4, to_hop: 5 }] });
    (api.chainCandidateResult.body['candidates'] as any).collection.evidence.hops[0].url = 'changed'; expect((component.candidateReport()!['collection'] as any).evidence.hops[0].url).toBe(urls[0]);
  });
  it('rejects original strict DTO/family/date/null/status/binding/privacy and fabricated, missing or nonadjacent candidate facts', async () => {
    const { component } = await screen();
    const good = chainCandidateResult(chainDetail({ ...chainInput(), url: ORIGIN + '/', target_urls: [HTTP_ORIGIN + '/', CHAIN_OTHER + '/'] }, [ORIGIN + '/', HTTP_ORIGIN + '/']));
    const mutations: ((r: any) => void)[] = [r => r.job_id = true, r => r.source_current = 1, r => r.method_version = 'passive-redirect-candidates-v1',
      r => r.coverage = 'whole_site', r => r.interpretation = 'secure', r => r.raw_location = 'private', r => r.availability.selected_urls = 2,
      r => r.availability.observed_hops = true, r => r.availability.last_target_metadata = 'observed', r => r.availability.raw = 'private',
      r => r.candidates = [], r => r.candidates.push(r.candidates[0]), r => r.candidates[0].detector = 'downgrade_proof',
      r => r.candidates[0].evidence.transitions[0].from_hop = true, r => r.candidates[0].evidence.transitions[0].to_hop = 2,
      r => r.candidates[0].evidence.transitions[0].target_url = 'private', r => r.candidates[0].evidence.status = 302,
      r => r.binding.origins.pop(), r => r.binding.actor_id = true, r => r.binding.origins[2].verified_at = LATER,
      r => r.binding.collection_permission = 1, r => r.binding.observations = ['response_location'], r => r.binding.target_urls.pop(),
      r => r.collection.status = true, r => r.collection.method = 'passive-redirect-evidence-v1', r => r.collection.observed_at = LATER,
      r => r.collection.evidence.hops[0].observed_at = '2026-01-01T00:00:00.000001Z', r => r.collection.evidence.hops[1].response_location.target_scheme = 'http',
      r => r.collection.evidence.hops[1].response_location.same_origin = false, r => r.collection.evidence.hops[0].response_location.raw = 'private',
      r => r.collection.evidence.hops[0].response_location.method_version = 'passive-http-response-location-v1', r => r.collection.evidence.state = 'redirect_loop'];
    for (const mutate of mutations) { await component.load(); api.chainCandidateResult = structuredClone(good); mutate(api.chainCandidateResult.body['candidates']);
      await component.inspectChainCandidates(21); expect(component.candidateReport()).toBeNull(); expect(component.ready()).toBe(false); }
    for (const status of [401, 403, 404, 409, 200]) { await component.load(); api.chainCandidateResult = { status, body: {} }; await component.inspectChainCandidates(21);
      expect(component.candidateReport()).toBeNull(); expect(component.jobs()).toEqual([]); }
  });
  it('checks full current role/configuration and every original verification including UNVISITED before GET and after final saved metadata', async () => {
    const { component } = await screen(); const original = api.passiveRedirectChainCandidates.bind(api);
    for (const after of [false, true]) for (const loss of ['role', 'config', 'initial', 'visited', 'unvisited', 'updated']) {
      vi.restoreAllMocks(); api.role = 'owner'; api.verifications = chainVerifications(); await component.load(); const count = api.chainCandidateCalls.length;
      const lose = () => { if (loss === 'role') api.role = 'member';
        else if (loss === 'config') vi.spyOn(api, 'projectOnboarding').mockResolvedValue({ status: 200, body: { project: { id: 9, organization_id: 7, role: 'owner', canonical_origin: ORIGIN, aliases: [HTTP_ORIGIN] } } });
        else if (loss === 'updated') api.verifications[2]['updated_at'] = '2026-01-01T00:00:00.000003+00:00';
        else api.verifications.splice(loss === 'initial' ? 1 : loss === 'visited' ? 0 : 2, 1); };
      if (after) vi.spyOn(api, 'passiveRedirectChainCandidates').mockImplementation(async (...args) => { const result = await original(...args); lose(); return result; }); else lose();
      await component.inspectChainCandidates(21); expect(api.chainCandidateCalls).toHaveLength(count + (after ? 1 : 0)); expect(component.candidateReport()).toBeNull(); expect(component.ready()).toBe(false);
    }
    vi.restoreAllMocks(); api.role = 'owner'; api.verifications = chainVerifications(); await component.load();
    const history = api.passiveRedirectChain.bind(api); let reads = 0;
    vi.spyOn(api, 'passiveRedirectChain').mockImplementation(async (...args) => { const result = await history(...args); if (++reads === 2) api.verifications.pop(); return result; });
    await component.inspectChainCandidates(21); expect(reads).toBe(2); expect(component.candidateReport()).toBeNull(); expect(component.ready()).toBe(false);
  });
  it('pins full selected saved Job metadata before and after GET and never silently adopts a newer cancelled/failed/changed row', async () => {
    const { component } = await screen(); const original = api.passiveRedirectChainCandidates.bind(api);
    for (const after of [false, true]) for (const change of [{ status: 'failed' }, { cancel_requested: true }, { updated_at: '2026-01-01T00:00:00.000003+00:00' },
      { estimate_units: 0 }, { error_category: 'network_error' }, { id: 22 }]) {
      vi.restoreAllMocks(); api.rows = [{ ...job(), status: 'succeeded' }]; await component.load(); const count = api.chainCandidateCalls.length;
      const lose = () => Object.assign(api.rows[0], change);
      if (after) vi.spyOn(api, 'passiveRedirectChainCandidates').mockImplementation(async (...args) => { const result = await original(...args); lose(); return result; }); else lose();
      await component.inspectChainCandidates(21); expect(api.chainCandidateCalls).toHaveLength(count + (after ? 1 : 0)); expect(component.candidateReport()).toBeNull(); expect(component.ready()).toBe(false);
    }
    vi.restoreAllMocks(); api.rows = [{ ...job(), status: 'succeeded' }]; await component.load();
    vi.spyOn(api, 'passiveRedirectChain').mockResolvedValue({ status: 200, body: { organization_id: 7, project_id: 10, jobs: api.rows, has_more: false, lookup: null } });
    await component.inspectChainCandidates(21); expect(component.candidateReport()).toBeNull(); expect(component.ready()).toBe(false);
  });
  it('rejects unsafe/missing/not-succeeded/cancelled/error jobs and confines candidate authority to the fixed chain route', async () => {
    const { harness, component } = await screen();
    for (const id of [0, -1, NaN, 9007199254740992, 99]) await component.inspectChainCandidates(id);
    for (const change of [{ status: 'queued' }, { status: 'failed' }, { cancel_requested: true }, { error_category: 'network_error' }]) {
      api.rows = [{ ...job(), status: 'succeeded', ...change }]; await component.load(); await component.inspectChainCandidates(21); }
    expect(api.chainCandidateCalls).toEqual([]);
    for (const family of ['headers', 'tls', 'resources', 'redirects', 'http-redirects']) {
      const current = await harness.navigateByUrl(`/passive-${family}/7/9?passiveObservation=redirect-chain`, PassiveHeaders); await harness.fixture.whenStable();
      await current.inspectChainCandidates(21); expect(api.chainCandidateCalls).toEqual([]);
    }
  });
  it('clears published candidates on edit/refresh/detail/ownership and discards genuinely late GET after edit, route, family or destruction', async () => {
    const { harness, component } = await screen();
    for (const action of [() => component.editUrl(HTTP_ORIGIN + '/edited'), () => component.editPermission(false), () => component.addTarget(),
      () => component.inspect(21), () => component.preview(), () => component.load(), () => component.revoke(component.verifications()[0])]) {
      api.verifications = chainVerifications(); await component.load(); await component.inspectChainCandidates(21); expect(component.candidateReport()).not.toBeNull();
      await action(); expect(component.candidateReport()).toBeNull();
    }
    api.verifications = chainVerifications(); let current = component;
    for (const action of ['edit', 'refresh', 'organization', 'project', 'family', 'destroy']) {
      api.chainCandidatePromise = null; current = await harness.navigateByUrl('/passive-redirect-chain/7/9', PassiveHeaders); await harness.fixture.whenStable();
      await vi.waitFor(() => { expect(current.ready()).toBe(true); expect(current.busy()).toBe(false); }); await current.load();
      let resolve!: (result: ApiResult) => void; api.chainCandidatePromise = new Promise(done => resolve = done); const count = api.chainCandidateCalls.length;
      const waiting = current.inspectChainCandidates(21); await vi.waitFor(() => expect(api.chainCandidateCalls).toHaveLength(count + 1));
      if (action === 'edit') current.editUrl(ORIGIN + '/edited'); else if (action === 'refresh') { current.editPermission(false); await current.load(); }
      else if (action === 'destroy') harness.fixture.destroy();
      else await harness.navigateByUrl(action === 'organization' ? '/passive-redirect-chain/8/9' : action === 'project' ? '/passive-redirect-chain/7/10' : '/passive-redirects/7/9', PassiveHeaders);
      const error = current.error(); resolve(chainCandidateResult()); await waiting; expect(current.candidateReport()).toBeNull(); expect(current.error()).toBe(error);
    }
  });
  it('uses the fixed same-origin/no-store bodyless candidate GET', async () => {
    const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) })); vi.stubGlobal('fetch', fetcher);
    try { TestBed.resetTestingModule(); const real = TestBed.inject(AccountApi); await real.passiveRedirectChainCandidates(7, 9, 21);
      expect(fetcher).toHaveBeenCalledWith('/api/organizations/7/projects/9/passive-redirect-chain/21/candidates/', expect.objectContaining({ method: 'GET', credentials: 'same-origin', cache: 'no-store' }));
      expect((fetcher.mock.calls as unknown as [string, RequestInit][])[0][1].body).toBeUndefined();
    } finally { vi.unstubAllGlobals(); }
  });
});
async function chainFindingResult(saved = false, candidateResult = chainCandidateResult()): Promise<ApiResult> {
  const report = candidateResult.body['candidates'] as any; const method = 'passive-redirect-chain-finding-v1'; const findings = [];
  if (saved) for (const [index, candidate] of report.candidates.entries()) {
    const evidence = { source: 'passive_exact_selected_redirect_chain', job_id: report.job_id,
      binding: Object.fromEntries(['method_version', 'organization_id', 'project_id', 'actor_id', 'source_digest', 'observations', 'collection_permission'].map(key => [key, report.binding[key]])),
      binding_sha256: await sha(report.binding), collection_sha256: await sha(report.collection),
      observed_at: report.collection.observed_at, last_observed_at: report.collection.last_observed_at,
      captures: report.collection.evidence.hops.map((hop: any, i: number) => ({ hop: i, scheme: hop.url.split(':')[0], status: hop.status, observed_at: hop.observed_at })),
      availability: report.availability, fact: candidate.evidence, coverage: report.coverage, interpretation: report.interpretation };
    findings.push({ id: 100 + index, source_passive_redirect_chain_id: report.job_id, detector: candidate.detector, method_version: method,
      subject: report.binding.url, fingerprint: await sha([method, candidate.detector, evidence]), evidence,
      confidence: 'dated_chain_fact_not_risk_severity', detected_at: LATER });
  }
  return { status: 200, body: { organization_id: 7, project_id: 9, candidates: report, candidate_digest: await sha(report), finding_set: {
    method_version: method, project_id: 9, job_id: report.job_id, source_current: true,
    state: findings.length ? 'current_materialized_facts' : 'no_retained_materialized_findings', findings } } };
}
function twoChainCandidates() {
  const detail = chainDetail({ ...chainInput(), url: ORIGIN + '/', target_urls: [HTTP_ORIGIN + '/', CHAIN_OTHER + '/'] }, [ORIGIN + '/', HTTP_ORIGIN + '/']);
  const collection = (detail.body['evidence'] as any).collection; const last = collection.evidence.hops.at(-1);
  collection.evidence.state = 'redirect_loop'; collection.status = last.status = 302; last.target_state = 'permitted_target';
  last.response_location = httpEvidence(302, 'single_classified', 'https', false, true).collection.evidence.response_location;
  return chainCandidateResult(detail);
}
describe('Deliberate original-chain Finding inspection and save', () => {
  let api: ChainFixtureApi;
  beforeEach(() => { api = new ChainFixtureApi(); api.rows = [{ ...job(), status: 'succeeded' }]; api.chainCandidateResult = twoChainCandidates();
    TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] }); });
  async function screen() {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/passive-redirect-chain/7/9?job_id=21&passiveObservation=headers', PassiveHeaders);
    await harness.fixture.whenStable(); await vi.waitFor(() => { expect(component.ready()).toBe(true); expect(component.busy()).toBe(false); });
    harness.detectChanges(); return { harness, component };
  }
  it('requires explicit saved-job inspection and digest-only save, preserves complete compact originals without automatic priority, new work, links or storage', async () => {
    const { harness, component } = await screen(); const storage = vi.spyOn(Storage.prototype, 'setItem');
    expect(api.chainFindingReads).toEqual([]); expect(component.findingInspection()).toBeNull();
    Array.from(harness.routeNativeElement!.querySelectorAll('button')).find(row => row.textContent?.includes('Inspect current original chain findings'))!.click();
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.busy()).toBe(false)); harness.detectChanges();
    expect(api.chainFindingReads).toEqual([21]); expect(api.chainFindingCommands).toEqual([]);
    expect(component.findingInspection()?.findingSet['state']).toBe('no_retained_materialized_findings');
    const report = structuredClone(component.candidateReport()); await component.saveFindings(); harness.detectChanges();
    expect(api.chainFindingCommands).toEqual([[21, await sha(report)]]); expect(component.findingRows()).toHaveLength(2);
    const expected = await chainFindingResult(true, twoChainCandidates()); expect(component.findingInspection()?.findingSet).toEqual(expected.body['finding_set']);
    for (const text of ['dated_chain_fact_not_risk_severity', 'binding_sha256', DATE, LATER, 'no personal attribution', 'Detection time', 'UNVISITED', 'not a repeated response']) expect(harness.routeNativeElement!.textContent).toContain(text);
    expect(harness.routeNativeElement!.textContent).toContain("Inspect this fact's current human judgment");
    expect(api.priorityReads).toEqual([]); expect(api.priorityCommands).toEqual([]);
    expect(api.commands).toEqual([]); expect(api.ownership).toEqual([]); expect(api.previews).toBe(0);
    expect(api.findingReads.concat(api.tlsFindingReads, api.redirectFindingReads, api.resourceFindingReads)).toEqual([]);
    expect(harness.routeNativeElement!.querySelectorAll('a')).toHaveLength(1); expect(harness.routeNativeElement!.querySelector('img, iframe, script')).toBeNull();
    expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
    api.chainFindingResult = expected; await component.inspectFindings(21); (expected.body['finding_set'] as any).findings[0].evidence.captures[0].status = 599;
    expect((component.findingRows()[0]['evidence'] as any).captures[0].status).toBe(302);
  });
  it('fences every original origin and full saved metadata throughout chosen-fact judgment reads, preflight, POST and GET-only recovery', async () => {
    const { component } = await screen(); const facts = api.passiveRedirectChainFindings.bind(api);
    const priority = api.passiveRedirectChainPriority.bind(api); const history = api.passiveRedirectChain.bind(api);
    for (const stage of ['inspect_before', 'inspect_facts', 'inspect_read', 'inspect_history', 'save_before', 'save_facts', 'save_read', 'save_post', 'reconcile_before', 'reconcile_facts', 'reconcile_read'])
      for (const loss of ['role', 'config', 'initial', 'visited', 'unvisited', 'updated', 'metadata']) {
        vi.restoreAllMocks(); api.role = 'owner'; api.verifications = chainVerifications(); api.rows = [{ ...job(), status: 'succeeded' }];
        api.findingsSaved = true; api.priorityDecision = null; api.priorityDrop = false; api.priorityUncertain = false;
        component.editPermission(false); await component.load(); await component.inspectFindings(21);
        if (!stage.startsWith('inspect')) { await component.inspectPriority(100); component.editJudgment('reason', 'Human judgment only'); }
        if (stage.startsWith('reconcile')) { api.priorityDrop = true; await component.savePriority(); expect(component.priorityPending()).not.toBeNull(); }
        const before = api.priorityCommands.length; const reads = api.priorityReads.length;
        const lose = () => {
          if (loss === 'role') api.role = 'member';
          else if (loss === 'config') vi.spyOn(api, 'projectOnboarding').mockResolvedValue({ status: 200, body: { project: {
            id: 9, organization_id: 7, role: 'owner', canonical_origin: ORIGIN, aliases: [HTTP_ORIGIN] } } });
          else if (loss === 'metadata') api.rows[0].updated_at = '2026-01-01T00:00:00.000003+00:00';
          else if (loss === 'updated') api.verifications[2]['updated_at'] = '2026-01-01T00:00:00.000003+00:00';
          else api.verifications.splice(loss === 'initial' ? 0 : loss === 'visited' ? 1 : 2, 1);
        };
        if (stage.endsWith('before')) lose();
        else if (stage.endsWith('facts')) vi.spyOn(api, 'passiveRedirectChainFindings').mockImplementation(async (...args) => { const result = await facts(...args); lose(); return result; });
        else vi.spyOn(api, 'passiveRedirectChainPriority').mockImplementation(async (...args) => {
          const result = await priority(...args);
          if ((args[4] !== undefined) === (stage === 'save_post')) {
            if (stage === 'inspect_history') vi.spyOn(api, 'passiveRedirectChain').mockImplementation(async (...args) => { const result = await history(...args); lose(); return result; });
            else lose();
          }
          return result;
        });
        if (stage.startsWith('inspect')) await component.inspectPriority(100);
        else if (stage.startsWith('save')) await component.savePriority(); else await component.reconcilePriority();
        expect(api.priorityCommands, `${stage}/${loss}`).toHaveLength(before + (stage === 'save_post' ? 1 : 0));
        if (stage.endsWith('before') || stage.endsWith('facts')) expect(api.priorityReads).toHaveLength(reads);
        expect(component.priorityInspection(), `${stage}/${loss}`).toBeNull(); expect(component.priorityPending()).toBeNull();
        expect(component.findingInspection()).toBeNull(); expect(component.candidateReport()).toBeNull(); expect(component.ready()).toBe(false);
      }
  });
  it('binds a deliberate judgment to an original loop fact with three selected origins but one actual capture, including UNVISITED authority', async () => {
    const { harness, component } = await screen();
    const detail = chainDetail({ ...chainInput(), url: ORIGIN + '/', target_urls: [HTTP_ORIGIN + '/', CHAIN_OTHER + '/'] }, [ORIGIN + '/']);
    const collection = (detail.body['evidence'] as any).collection; const hop = collection.evidence.hops[0];
    collection.evidence.state = 'redirect_loop'; collection.status = hop.status = 302; hop.target_state = 'permitted_target';
    hop.response_location = redirectEvidence(302, 'single_classified', 'https', true).collection.evidence.response_location;
    api.chainCandidateResult = chainCandidateResult(detail); api.findingsSaved = true; await component.inspectFindings(21);
    await component.inspectPriority(100); harness.detectChanges();
    expect(component.priorityInspection()).not.toBeNull(); expect(harness.routeNativeElement!.textContent).toContain('UNVISITED');
    expect((component.priorityInspection()!.judgment['source'] as any).finding.evidence.availability).toMatchObject({ selected_urls: 3, observed_hops: 1 });
    component.editJudgment('reason', 'Only this original loop stop'); api.verifications[2]['updated_at'] = '2026-01-01T00:00:00.000003+00:00';
    await component.savePriority(); expect(api.priorityCommands).toEqual([]); expect(component.priorityInspection()).toBeNull(); expect(component.ready()).toBe(false);
  });
  it('validates complete six max-length selected paths through compact full binding/collection hashes and preserves empty/null/no-retained meanings', async () => {
    const { harness, component } = await screen();
    const urls = Array.from({ length: 6 }, (_, i) => (i % 2 ? HTTP_ORIGIN : ORIGIN) + '/' + String(i).repeat(1024 - (i % 2 ? HTTP_ORIGIN : ORIGIN).length - 1));
    const candidates = chainCandidateResult(chainDetail({ ...chainInput(), url: urls[0], target_urls: urls.slice(1) }, urls));
    api.chainFindingResult = await chainFindingResult(true, candidates); await component.inspectFindings(21);
    expect(component.findingRows()).toHaveLength(1); const evidence = component.findingRows()[0]['evidence'] as any;
    expect(evidence.captures).toHaveLength(6); expect(evidence.binding).not.toHaveProperty('target_urls');
    expect(evidence.binding_sha256).toBe(await sha((candidates.body['candidates'] as any).binding));
    expect(new TextEncoder().encode(JSON.stringify(evidence)).length).toBeLessThanOrEqual(4096);
    for (const state of ['terminal_response', 'location_unavailable', 'unsupported_target', 'outside_exact_target_allowlist']) {
      const detail = chainDetail(); const collection = (detail.body['evidence'] as any).collection; const last = collection.evidence.hops.at(-1);
      collection.evidence.state = last.target_state = state;
      if (state !== 'terminal_response') { collection.status = last.status = 302; last.response_location = redirectEvidence(302,
        state === 'location_unavailable' ? 'multiple_fields' : 'single_classified', state === 'location_unavailable' ? null : 'https', state === 'location_unavailable' ? null : false).collection.evidence.response_location; }
      api.chainFindingResult = await chainFindingResult(false, chainCandidateResult(detail)); await component.inspectFindings(21); await component.saveFindings(); harness.detectChanges();
      expect(component.findingInspection()).not.toBeNull(); expect(component.candidateRows()).toEqual([]);
      expect(harness.routeNativeElement!.textContent).toContain('not a clean, secure or whole-site result');
      expect(harness.routeNativeElement!.textContent).toContain('does not mean zero eligible candidates');
    }
    expect(api.chainFindingCommands).toEqual([]);
  });
  it('rejects full envelope/report/source/hash/capture/identity/date and incomplete duplicate or excessive set mutations', async () => {
    const { component } = await screen(); const good = await chainFindingResult(true, twoChainCandidates());
    const mutations: ((b: any) => void)[] = [b => b.candidate_digest = 'a'.repeat(64), b => b.organization_id = 8, b => b.project_id = 10,
      b => b.raw_location = 'private', b => b.candidates.binding.origins.pop(), b => b.candidates.collection.last_observed_at = DATE,
      b => b.candidates.availability.observed_hops = true, b => b.candidates.candidates[0].evidence.transitions[0].to_hop = 2,
      b => b.finding_set.job_id = 22, b => b.finding_set.source_current = 1, b => b.finding_set.state = 'clean',
      b => b.finding_set.method_version = 'passive-redirect-finding-v1', b => b.finding_set.findings.pop(),
      b => b.finding_set.findings.push(b.finding_set.findings[0]), b => b.finding_set.findings[1] = { ...b.finding_set.findings[0], id: 101 },
      b => b.finding_set.findings.reverse(), b => b.finding_set.findings[0].id = true,
      b => b.finding_set.findings[0].source_passive_redirect_chain_id = 22, b => b.finding_set.findings[0].source_passive_redirect_id = 21,
      b => b.finding_set.findings[0].subject += 'other', b => b.finding_set.findings[0].confidence = 'high',
      b => b.finding_set.findings[0].detector = 'invented', b => b.finding_set.findings[0].method_version = 'wrong',
      b => b.finding_set.findings[0].fingerprint = 'a'.repeat(64), b => b.finding_set.findings[0].actor_id = 1,
      b => b.finding_set.findings[0].detected_at = DATE, b => b.finding_set.findings[0].detected_at = '2026-02-30T00:00:00Z',
      b => b.finding_set.findings[0].evidence.source = 'passive_first_response_location',
      b => b.finding_set.findings[0].evidence.binding_sha256 = 'a'.repeat(64), b => b.finding_set.findings[0].evidence.collection_sha256 = 'a'.repeat(64),
      b => b.finding_set.findings[0].evidence.binding.actor_id = 99, b => b.finding_set.findings[0].evidence.binding.target_urls = ['private'],
      b => b.finding_set.findings[0].evidence.captures.pop(), b => b.finding_set.findings[0].evidence.captures[0].hop = true,
      b => b.finding_set.findings[0].evidence.captures[0].scheme = 'http', b => b.finding_set.findings[0].evidence.captures[0].status = 200,
      b => b.finding_set.findings[0].evidence.captures[0].observed_at = LATER, b => b.finding_set.findings[0].evidence.last_observed_at = DATE,
      b => b.finding_set.findings[0].evidence.availability.last_target_metadata = 'unavailable',
      b => b.finding_set.findings[0].evidence.fact.transitions[0].to_hop = 5,
      b => b.finding_set.findings[0].evidence.raw = 'x'.repeat(4097), b => b.finding_set.findings[1].evidence.fact.last_hop = 0];
    for (const mutate of mutations) { await component.load(); api.chainFindingResult = structuredClone(good); mutate(api.chainFindingResult.body);
      await component.inspectFindings(21); expect(component.findingInspection()).toBeNull(); expect(component.candidateReport()).toBeNull(); expect(component.ready()).toBe(false); }
    expect(api.chainFindingCommands).toEqual([]);
  });
  it('fences full original metadata and every verification before/after inspection, pre-save read, POST and reconciliation, including final slow history', async () => {
    const { component } = await screen(); const original = api.passiveRedirectChainFindings.bind(api);
    for (const stage of ['inspect_before', 'inspect_after', 'save_before', 'save_read', 'save_post', 'reconcile_before', 'reconcile_after'])
      for (const loss of ['role', 'config', 'initial', 'visited', 'unvisited', 'updated', 'metadata']) {
        vi.restoreAllMocks(); api.role = 'owner'; api.verifications = chainVerifications(); api.rows = [{ ...job(), status: 'succeeded' }];
        api.findingDrop = false; api.findingUncertain = false; api.findingsSaved = false; await component.load();
        if (stage.startsWith('save') || stage.startsWith('reconcile')) await component.inspectChainCandidates(21);
        if (stage.startsWith('reconcile')) { api.findingDrop = true; await component.saveFindings(); }
        const reads = api.chainFindingReads.length; const writes = api.chainFindingCommands.length;
        const lose = () => { if (loss === 'role') api.role = 'member';
          else if (loss === 'config') vi.spyOn(api, 'projectOnboarding').mockResolvedValue({ status: 200, body: { project: { id: 9, organization_id: 7, role: 'owner', canonical_origin: ORIGIN, aliases: [HTTP_ORIGIN] } } });
          else if (loss === 'metadata') api.rows[0].updated_at = '2026-01-01T00:00:00.000003+00:00';
          else if (loss === 'updated') api.verifications[2]['updated_at'] = '2026-01-01T00:00:00.000003+00:00';
          else api.verifications.splice(loss === 'initial' ? 0 : loss === 'visited' ? 1 : 2, 1); };
        if (stage.endsWith('before')) lose(); else vi.spyOn(api, 'passiveRedirectChainFindings').mockImplementation(async (...args) => {
          const result = await original(...args); if (stage === 'save_post' ? !!args[3] : args[3] === undefined) lose(); return result; });
        // A successful POST response is required to exercise the post-write fence.
        if (stage === 'save_post') api.findingDrop = false;
        await (stage.startsWith('inspect') ? component.inspectFindings(21) : stage.startsWith('save') ? component.saveFindings() : component.reconcileFindings());
        expect(api.chainFindingCommands).toHaveLength(writes + (stage === 'save_post' ? 1 : 0));
        if (stage.endsWith('before')) expect(api.chainFindingReads).toHaveLength(reads);
        expect(component.findingInspection()).toBeNull(); expect(component.findingPending()).toBeNull(); expect(component.candidateReport()).toBeNull(); expect(component.ready()).toBe(false);
      }
    vi.restoreAllMocks(); api.role = 'owner'; api.verifications = chainVerifications(); api.rows = [{ ...job(), status: 'succeeded' }]; await component.load();
    const history = api.passiveRedirectChain.bind(api); let count = 0;
    vi.spyOn(api, 'passiveRedirectChain').mockImplementation(async (...args) => { const result = await history(...args); if (++count === 2) api.verifications.pop(); return result; });
    await component.inspectFindings(21); expect(count).toBe(2); expect(component.findingInspection()).toBeNull(); expect(component.ready()).toBe(false);
  });
  it('keeps original saved metadata frozen across candidate-to-save instead of adopting newer jobs and denies changed report before POST', async () => {
    const { component } = await screen(); await component.inspectChainCandidates(21);
    api.rows[0].updated_at = '2026-01-01T00:00:00.000003+00:00'; await component.saveFindings();
    expect(api.chainFindingCommands).toEqual([]); expect(api.chainFindingReads).toEqual([]); expect(component.ready()).toBe(false);
    api.rows = [{ ...job(), status: 'succeeded' }]; await component.load(); await component.inspectChainCandidates(21);
    const changed = twoChainCandidates(); (changed.body['candidates'] as any).binding.actor_id = 3;
    api.chainFindingResult = await chainFindingResult(false, changed); await component.saveFindings();
    expect(api.chainFindingCommands).toEqual([]); expect(component.findingPending()).toBeNull(); expect(component.error()).toContain('No fact-save command sent');
  });
  it('reconciles only frozen same-job original SHA through GET, distinguishes absence/network from no-op and never automatically retries', async () => {
    const { harness, component } = await screen(); await component.inspectChainCandidates(21); api.findingDrop = true; await component.saveFindings();
    const frozen = structuredClone(component.findingPending()); expect(frozen?.candidateDigest).toBe(await sha(twoChainCandidates().body['candidates']));
    harness.detectChanges(); expect(harness.routeNativeElement!.textContent).toContain('chain-fact save outcome is uncertain');
    await component.saveFindings(); await component.inspectFindings(21); await component.reconcileFindings();
    expect(component.findingPending()).toEqual(frozen); expect(component.message()).toContain('not confirmed no-op'); expect(api.chainFindingCommands).toHaveLength(1);
    vi.spyOn(api, 'passiveRedirectChainFindings').mockRejectedValueOnce(new Error('network')); await component.reconcileFindings();
    expect(component.findingPending()).toEqual(frozen); expect(component.findingInspection()).toBeNull(); vi.restoreAllMocks();
    api.findingsSaved = true; await component.reconcileFindings(); expect(component.findingPending()).toBeNull(); expect(component.message()).toContain('No command replayed');
    expect(api.chainFindingCommands).toHaveLength(1); api.findingDrop = false; api.findingUncertain = true; await component.saveFindings();
    const changed = await chainFindingResult(true, twoChainCandidates()); (changed.body['finding_set'] as any).findings[0].id = 99; api.chainFindingResult = changed;
    await component.reconcileFindings(); expect(component.findingPending()).toBeNull(); expect(component.findingInspection()).toBeNull();
    api.chainFindingResult = null; api.findingsSaved = false; api.findingDrop = true; await component.inspectChainCandidates(21); await component.saveFindings();
    component.discardFindingCommand(); expect(component.findingPending()).toBeNull(); expect(component.message()).toContain('Stored facts may still exist');
  });
  it('clears received denied/malformed/changed lookup and rejects unsafe, missing, cancelled, failed, error and foreign-family jobs', async () => {
    const { harness, component } = await screen();
    for (const status of [401, 403, 404, 409, 200]) { await component.load(); await component.inspectChainCandidates(21); api.findingDrop = true; await component.saveFindings();
      api.chainFindingResult = { status, body: {} }; await component.reconcileFindings(); expect(component.findingPending()).toBeNull(); api.chainFindingResult = null; }
    api.findingDrop = false; await component.load(); const count = api.chainFindingReads.length;
    for (const id of [0, -1, NaN, 9007199254740992, 99]) await component.inspectFindings(id);
    for (const change of [{ status: 'queued' }, { status: 'failed' }, { cancel_requested: true }, { error_category: 'network_error' }]) {
      api.rows = [{ ...job(), status: 'succeeded', ...change }]; await component.load(); await component.inspectFindings(21); }
    expect(api.chainFindingReads).toHaveLength(count); api.rows = [{ ...job(), status: 'succeeded' }];
    for (const family of ['headers', 'tls', 'resources', 'redirects', 'http-redirects']) {
      const current = await harness.navigateByUrl(`/passive-${family}/7/9?passiveObservation=redirect-chain`, PassiveHeaders); await harness.fixture.whenStable();
      current.candidateReport.set(twoChainCandidates().body['candidates'] as any); await current.saveFindings();
      expect(api.chainFindingReads).toHaveLength(count); }
  });
  it('clears all facts and uncertainty on edits/refresh/detail/candidate/ownership and drops genuinely late GET/POST/reconcile across scope-family-destroy', async () => {
    const { harness, component } = await screen();
    for (const action of [() => component.editUrl(ORIGIN + '/edited'), () => component.editPermission(false), () => component.addTarget(),
      () => component.inspect(21), () => component.inspectChainCandidates(21), () => component.load(), () => component.revoke(component.verifications()[0])]) {
      api.verifications = chainVerifications(); await component.load(); await component.inspectChainCandidates(21); api.findingUncertain = true;
      await component.saveFindings(); expect(component.findingPending()).not.toBeNull(); await action(); expect(component.findingPending()).toBeNull(); expect(component.findingInspection()).toBeNull(); }
    api.verifications = chainVerifications(); let current = component;
    for (const stage of ['read', 'post', 'reconcile']) for (const action of ['edit', 'refresh', 'organization', 'project', 'family', 'destroy']) {
      if (action === 'destroy' && stage !== 'reconcile') continue;
      api.chainFindingPromise = null; api.chainFindingPostPromise = null; api.findingUncertain = false; api.findingsSaved = false;
      current = await harness.navigateByUrl('/passive-redirect-chain/7/9', PassiveHeaders); await harness.fixture.whenStable();
      await vi.waitFor(() => { expect(current.ready()).toBe(true); expect(current.busy()).toBe(false); }); await current.load();
      if (stage !== 'read') await current.inspectChainCandidates(21);
      if (stage === 'reconcile') { api.findingUncertain = true; await current.saveFindings(); }
      let resolve!: (result: ApiResult) => void; const pending = new Promise<ApiResult>(done => resolve = done);
      if (stage === 'post') api.chainFindingPostPromise = pending; else api.chainFindingPromise = pending;
      const reads = api.chainFindingReads.length; const writes = api.chainFindingCommands.length;
      const waiting = stage === 'read' ? current.inspectFindings(21) : stage === 'post' ? current.saveFindings() : current.reconcileFindings();
      await vi.waitFor(() => expect(stage === 'post' ? api.chainFindingCommands.length : api.chainFindingReads.length).toBe((stage === 'post' ? writes : reads) + 1));
      if (action === 'edit') current.editUrl(ORIGIN + '/edited');
      else if (action === 'refresh') { current.editPermission(false); await current.load(); }
      else if (action === 'destroy') harness.fixture.destroy();
      else await harness.navigateByUrl(action === 'organization' ? '/passive-redirect-chain/8/9' : action === 'project' ? '/passive-redirect-chain/7/10' : '/passive-redirects/7/9', PassiveHeaders);
      const error = current.error(); resolve(await chainFindingResult(true, twoChainCandidates())); await waiting;
      expect(current.findingInspection()).toBeNull(); expect(current.findingPending()).toBeNull(); expect(current.candidateReport()).toBeNull(); expect(current.error()).toBe(error);
      if (action === 'destroy') break;
    }
  });
  it('uses fixed bodyless no-store same-origin GET and exact SHA-only CSRF POST', async () => {
    const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) })); vi.stubGlobal('fetch', fetcher);
    try { TestBed.resetTestingModule(); const real = TestBed.inject(AccountApi); await real.passiveRedirectChainFindings(7, 9, 21); await real.passiveRedirectChainFindings(7, 9, 21, 'a'.repeat(64));
      const calls = (fetcher.mock.calls as unknown as [string, RequestInit][]).filter(([path]) => path.startsWith('/api/'));
      expect(calls.map(([path]) => path)).toEqual(Array(2).fill('/api/organizations/7/projects/9/passive-redirect-chain/21/findings/'));
      expect(calls[0][1].method).toBe('GET'); expect(calls[0][1].body).toBeUndefined(); expect(calls[1][1].method).toBe('POST');
      expect(calls[1][1].body).toBe(JSON.stringify({ candidate_digest: 'a'.repeat(64) })); expect(calls[1][1].headers).toHaveProperty('X-CSRFToken');
      expect(calls.every(([, options]) => options.cache === 'no-store' && options.credentials === 'same-origin')).toBe(true);
    } finally { vi.unstubAllGlobals(); }
  });
});
describe('Deliberate exact permitted redirect-chain native consumers', () => {
  let api: ChainFixtureApi;
  beforeEach(() => { api = new ChainFixtureApi(); TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] }); });
  async function screen() {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/passive-redirect-chain/7/9?passiveObservation=headers&target_urls=ignored', PassiveHeaders);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.ready()).toBe(true)); harness.detectChanges(); return { harness, component };
  }
  function choose(component: PassiveHeaders, data = chainInput()) {
    component.editUrl(data.url); while (component.targetUrls().length) component.removeTarget(0);
    for (const url of data.target_urls) { component.addTarget(); component.editTarget(component.targetUrls().length - 1, url); }
    component.editPermission(true);
  }
  it.each(['en', 'tr'] as const)('requires independent explicit target controls and unchecked permission; freezes full original SHA and sends only the fixed exact command in %s', async (language) => {
    api.savedProductLanguage = language;
    const { harness, component } = await screen(); const storage = vi.spyOn(Storage.prototype, 'setItem');
    expect(component.permission()).toBe(false); expect(component.targetUrls()).toEqual([]); expect(api.commands).toEqual([]);
    component.editUrl(HTTP_ORIGIN + '/'); await component.preview(); expect(api.previews).toBe(0);
    component.addTarget(); harness.detectChanges();
    const input = harness.routeNativeElement!.querySelector<HTMLInputElement>('#chain-target-0')!;
    expect(harness.routeNativeElement!.querySelector('label[for="chain-target-0"]')).not.toBeNull();
    input.value = ORIGIN + '/'; input.dispatchEvent(new Event('input', { bubbles: true })); expect(component.permission()).toBe(false);
    choose(component); await component.preview(); retainDraftLanguage(harness, component, api, language); const frozen = structuredClone(component.selection()!); expect(frozen.selection_digest).toBe(await sha(frozen.selection));
    expect((frozen.selection.binding['origins'] as unknown[]).length).toBe(3); await component.launch();
    expect(api.commands).toEqual([{ ...chainInput(), selection_digest: frozen.selection_digest, idempotency_key: expect.any(String) }]);
    expect(api.families.every(row => row === 'redirect-chain')).toBe(true); expect(component.pending()).toBeNull(); expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
  });
  it('rejects duplicate, unconfigured, noncanonical, oversized and unsafe exact targets and grants no more than five controls', async () => {
    const { component } = await screen();
    for (const url of [HTTP_ORIGIN + '/', ORIGIN + ':443/', ORIGIN + ':81/', ORIGIN + '/?', ORIGIN + '/#', ORIGIN + '/?x=y',
      'https://user@security.example.invalid/', 'HTTPS://security.example.invalid/', ORIGIN + '/a\\b', ORIGIN + '/a/../',
      'https://foreign.example.invalid/', ORIGIN + '/' + 'x'.repeat(1024), '']) {
      choose(component, { ...chainInput(), target_urls: [url] }); await component.preview(); expect(component.selection()).toBeNull();
    }
    choose(component, { ...chainInput(), target_urls: [ORIGIN + '/', ORIGIN + '/'] }); await component.preview(); expect(component.selection()).toBeNull();
    choose(component, { ...chainInput(), target_urls: Array.from({ length: 5 }, (_, i) => ORIGIN + '/' + i) }); component.addTarget(); expect(component.targetUrls()).toHaveLength(5);
    await component.preview(); expect(component.selection()).not.toBeNull(); component.removeTarget(0); expect(component.selection()).toBeNull(); expect(component.permission()).toBe(false);
    choose(component, { ...chainInput(), target_urls: [] }); await component.preview(); expect(component.selection()).not.toBeNull(); expect(api.commands).toEqual([]);
  });
  it('validates the entire original selection, independent origin order/IDs/dates, hidden SHA and real declaration rather than visited hops', async () => {
    const { component } = await screen(); const mutations: ((s: any) => void)[] = [s => s.method = 'passive-http-redirect-collection-v1',
      s => s.binding.method_version = 'passive-header-source-v1', s => s.binding.actor_id = true, s => s.binding.collection_permission = 1,
      s => s.binding.observations = ['response_location'], s => s.binding.target_urls.reverse(), s => s.binding.source_digest = 'B'.repeat(64),
      s => s.binding.origin = ORIGIN, s => s.binding.origins.pop(), s => s.binding.origins.reverse(), s => s.binding.origins[2].verification_id = 11,
      s => s.binding.origins[2].verified_at = LATER, s => s.binding.origins[2].verified_at = '2026-01-01T00:00:00.000001Z',
      s => s.binding.origins[2].raw = 'private', s => s.binding.organization_id = 8, s => s.binding.project_id = 10];
    choose(component); await component.preview(); const good = await api.preview();
    for (const mutate of mutations) { api.previewResult = structuredClone(good); mutate(api.previewResult.body['selection']);
      api.previewResult.body['selection_digest'] = await sha(api.previewResult.body['selection']); choose(component); await component.preview(); expect(component.selection()).toBeNull(); }
    api.previewResult = structuredClone(good); api.previewResult.body['selection_digest'] = 'a'.repeat(64); choose(component); await component.preview(); expect(component.selection()).toBeNull();
    api.previewResult = null; choose(component); await component.preview(); api.changed = true; await component.launch(); expect(api.commands).toEqual([]); expect(component.selection()).toBeNull();
  });
  it('checks full current role/configuration and EVERY original verification before and after preview, command, lookup and detail, including unvisited origin updates', async () => {
    const { component } = await screen(); const original = api.passiveRedirectChain.bind(api);
    for (const action of ['preview', 'command', 'lookup', 'detail']) for (const after of [false, true]) for (const loss of ['role', 'config', 'unvisited', 'updated']) {
      vi.restoreAllMocks(); api.role = 'owner'; api.verifications = chainVerifications(); api.uncertain = false; await component.load(); choose(component);
      if (action === 'command' || action === 'lookup') await component.preview();
      if (action === 'lookup') { api.uncertain = true; await component.launch(); }
      const lose = () => { if (loss === 'role') api.role = 'member'; else if (loss === 'config') vi.spyOn(api, 'projectOnboarding').mockResolvedValue({ status: 200, body: { project: {
        id: 9, organization_id: 7, role: 'owner', canonical_origin: ORIGIN, aliases: [HTTP_ORIGIN] } } });
        else if (loss === 'unvisited') api.verifications.pop(); else api.verifications[2]['updated_at'] = '2026-01-01T00:00:00.000003+00:00'; };
      if (after) vi.spyOn(api, 'passiveRedirectChain').mockImplementation(async (...args) => { const result = await original(...args);
        if (action === 'preview' ? args[5] : action === 'command' ? args[2] !== undefined && !args[5] : action === 'lookup' ? !!args[4] : !!args[3]) lose(); return result; }); else lose();
      api.uncertain = false; await (action === 'preview' ? component.preview() : action === 'command' ? component.launch() : action === 'lookup' ? component.reconcile() : component.inspect(21));
      expect(component.selection()).toBeNull(); expect(component.pending()).toBeNull(); expect(component.evidence()).toBeNull(); expect(component.ready()).toBe(false);
    }
    vi.restoreAllMocks();
  });
  it('uses GET-only frozen own-key uncertainty without retry, distinguishes empty lookup from no-op, and permits cancellation/history after origin loss', async () => {
    const { harness, component } = await screen(); choose(component); await component.preview(); api.drop = true; await component.launch();
    const frozen = structuredClone(component.pending()!); await component.reconcile(); expect(api.lookups).toEqual([frozen.key]); expect(component.pending()).toEqual(frozen);
    await component.retry(); await component.launch(); await component.load(); expect(api.commands).toHaveLength(1); harness.detectChanges();
    expect(harness.routeNativeElement!.textContent).not.toContain('Deliberately retry same command'); expect(component.message()).toContain('remains unknown');
    component.discardHttpCommand(); expect(component.pending()).toBeNull(); api.drop = false; api.detail = null; api.rows = [job()]; api.verifications = [verification()]; await component.load();
    api.uncertain = true; await component.cancel(21); expect(component.pending()?.jobId).toBe(21); await component.reconcile();
    expect(component.pending()).toBeNull(); expect(component.selected()?.cancel_requested).toBe(true); expect(api.commands).toEqual([frozen.data, {}]);
  });
  it('retains only memory on failed GET but clears received denied/malformed uncertainty and late authority loss', async () => {
    const { component } = await screen(); const original = api.passiveRedirectChain.bind(api);
    for (const status of [401, 403, 404, 409, 200]) {
      api.uncertain = true; await component.load(); choose(component); await component.preview(); await component.launch();
      vi.spyOn(api, 'passiveRedirectChain').mockResolvedValue({ status, body: {} }); await component.reconcile(); expect(component.pending()).toBeNull(); expect(component.ready()).toBe(false); vi.restoreAllMocks();
    }
    await component.load(); choose(component); await component.preview(); await component.launch(); const frozen = structuredClone(component.pending());
    vi.spyOn(api, 'passiveRedirectChain').mockImplementation(async (...args) => { if (args[4]) throw new Error('network'); return original(...args); });
    await component.reconcile(); expect(component.pending()).toEqual(frozen); vi.restoreAllMocks(); api.verifications.pop(); await component.reconcile(); expect(component.pending()).toBeNull();
  });
  it('preserves one–six selected hop URLs/date/status and full original unvisited binding without links, Findings or inferred current/browser/security authority', async () => {
    const { harness, component } = await screen(); await component.inspect(21); expect(component.evidence()).not.toBeNull(); harness.detectChanges();
    for (const text of [DATE, LATER, 'UNVISITED', 'not observations', 'No current availability', 'authenticated HTTP identity', 'terminal_response']) expect(harness.routeNativeElement!.textContent).toContain(text);
    expect(harness.routeNativeElement!.querySelectorAll('a')).toHaveLength(1); expect(harness.routeNativeElement!.querySelector('img, iframe, script')).toBeNull();
    (api.detail!.body['evidence'] as any).binding.source_digest = 'c'.repeat(64); expect((component.evidence()!['binding'] as any).source_digest).toBe('b'.repeat(64));
    const urls = Array.from({ length: 6 }, (_, i) => HTTP_ORIGIN + '/' + String(i).repeat(1024 - HTTP_ORIGIN.length - 1));
    const data = { ...chainInput(), url: urls[0], target_urls: urls.slice(1) }; api.detail = chainDetail(data, urls);
    expect(new TextEncoder().encode(JSON.stringify((api.detail.body['evidence'] as any).collection)).length).toBeGreaterThan(8192);
    await component.inspect(21); expect(component.evidence()).not.toBeNull();
    await component.inspectCandidates(21); await component.inspectResourceCandidates(21); await component.inspectTlsCandidates(21); await component.inspectRedirectCandidates(21); await component.inspectFindings(21); await component.saveFindings();
    expect(api.candidateCalls.concat(api.resourceCandidateCalls, api.tlsCandidateCalls, api.redirectCandidateCalls)).toEqual([]); expect(api.commands).toEqual([]);
  });
  it('retains unknown, terminal, unsupported, outside, loop and budget stops as coverage; accepts only original compatible transitions', async () => {
    const { component } = await screen();
    for (const state of ['terminal_response', 'location_unavailable', 'unsupported_target', 'outside_exact_target_allowlist', 'redirect_loop', 'redirect_limit']) {
      const result = chainDetail(); const info = (result.body['evidence'] as any).collection; const last = info.evidence.hops.at(-1);
      info.evidence.state = state; last.target_state = state.startsWith('redirect_') ? 'permitted_target' : state;
      if (state !== 'terminal_response') {
        info.status = last.status = 302; last.response_location = redirectEvidence(302, state === 'location_unavailable' ? 'multiple_fields' : 'single_classified',
          state === 'location_unavailable' ? null : state === 'redirect_loop' ? 'http' : 'https', state === 'location_unavailable' ? null : false).collection.evidence.response_location;
      }
      api.detail = result; await component.inspect(21); expect(component.evidence(), state).not.toBeNull();
    }
    api.detail = chainDetail({ ...chainInput(), url: ORIGIN + '/', target_urls: [] }, [ORIGIN + '/']); await component.inspect(21); expect(component.evidence()).not.toBeNull();
  });
  it('rejects exact envelopes/bindings/nested family/date/status/type/privacy/unique-hop/transition/stop/final inconsistencies', async () => {
    const { component } = await screen(); const mutations: ((v: any) => void)[] = [v => v.raw = 'private', v => v.source_current = 1, v => v.job_id = true,
      v => delete v.binding, v => v.binding.target_urls.pop(), v => v.binding.origins[2].verified_at = LATER, v => v.binding.origins[2].verification_id = true,
      v => v.collection.method = 'passive-redirect-evidence-v1', v => v.collection.raw = '<img onerror=x>', v => v.collection.final_url = HTTP_ORIGIN + '/',
      v => v.collection.status = true, v => v.collection.status = 302, v => v.collection.observed_at = LATER, v => v.collection.last_observed_at = DATE,
      v => v.collection.evidence.state = 'permitted_target', v => v.collection.evidence.state = 'redirect_loop', v => v.collection.evidence.coverage = 'whole_site',
      v => v.collection.evidence.hops.reverse(), v => v.collection.evidence.hops.push(v.collection.evidence.hops[0]), v => v.collection.evidence.hops = [],
      v => v.collection.evidence.hops[0].target_state = 'terminal_response', v => v.collection.evidence.hops[0].response_location.same_hostname_default_https = false];
    for (const index of [0, 1]) for (const change of [(h: any) => h.url += '?', (h: any) => h.url = CHAIN_OTHER + '/unselected', (h: any) => h.status = '302',
      (h: any) => h.status = 600, (h: any) => h.observed_at = '2026-02-30T00:00:00.000001+00:00', (h: any) => h.observed_at = '2026-01-01T00:00:00.000001Z',
      (h: any) => h.observed_at = '2026-01-01T00:00:00.000000+00:00', (h: any) => h.response_location.response_status = true,
      (h: any) => h.response_location.redirect_status = 1, (h: any) => h.response_location.raw_location = 'private',
      (h: any) => h.response_location.method_version = 'wrong-family', (h: any) => h.response_location.same_origin = 1,
    ]) mutations.push(v => change(v.collection.evidence.hops[index]));
    for (const mutate of mutations) { await component.load(); api.detail = chainDetail(); mutate(api.detail.body['evidence']); await component.inspect(21);
      expect(component.evidence()).toBeNull(); expect(component.selected()).toBeNull(); expect(component.ready()).toBe(false); }
  });
  it('clears all target/source/permission/memory on route-family-scope-destroy and discards genuinely late preview/detail/command responses on edits', async () => {
    const { harness, component } = await screen(); choose(component); let resolve!: (row: ApiResult) => void;
    api.previewPromise = new Promise(done => resolve = done); const preview = component.preview(); await vi.waitFor(() => expect(api.previews).toBe(1));
    component.editTarget(1, CHAIN_OTHER + '/edited'); resolve(await api.preview()); await preview; expect(component.selection()).toBeNull(); expect(component.permission()).toBe(false);
    api.previewPromise = null; choose(component); await component.preview(); const original = api.passiveRedirectChain.bind(api);
    vi.spyOn(api, 'passiveRedirectChain').mockImplementation(async (...args) => args[2] !== undefined && !args[5]
      ? new Promise(done => { api.commands.push(structuredClone(args[2]!)); resolve = done; }) : original(...args));
    const sending = component.launch(); await vi.waitFor(() => expect(api.commands).toHaveLength(1)); component.editUrl(HTTP_ORIGIN + '/edited');
    resolve({ status: 202, body: { organization_id: 7, project_id: 9, job: job() } }); await sending; expect(component.selected()).toBeNull(); expect(component.pending()).toBeNull(); vi.restoreAllMocks();
    for (const path of ['/passive-redirect-chain/8/9', '/passive-redirect-chain/7/10', '/passive-http-redirects/7/9', 'destroy']) {
      api.detailPromise = null; const current = await harness.navigateByUrl('/passive-redirect-chain/7/9', PassiveHeaders); await harness.fixture.whenStable();
      await vi.waitFor(() => { expect(current.ready()).toBe(true); expect(current.busy()).toBe(false); }); choose(current);
      const requests = vi.spyOn(api, 'passiveRedirectChain');
      api.detailPromise = new Promise(done => resolve = done); const reading = current.inspect(21); await vi.waitFor(() => expect(requests.mock.calls.some(args => args[3] === 21)).toBe(true));
      if (path === 'destroy') harness.fixture.destroy(); else await harness.navigateByUrl(path, PassiveHeaders);
      resolve(chainDetail()); await reading; expect(current.evidence()).toBeNull(); expect(current.pending()).toBeNull(); expect(current.permission()).toBe(false); expect(current.targetUrls()).toEqual([]);
      requests.mockRestore();
    }
  });
  it('uses fixed bodyless private GET/encoded own-key and CSRF POST routes; query data and unsafe scope IDs grant no family switch', async () => {
    const project = vi.spyOn(api, 'projectOnboarding'); const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/passive-redirect-chain/7/9007199254740992', PassiveHeaders); await harness.fixture.whenStable(); expect(project).not.toHaveBeenCalled();
    const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) })); vi.stubGlobal('fetch', fetcher);
    try { TestBed.resetTestingModule(); const real = TestBed.inject(AccountApi);
      await real.passiveRedirectChain(7, 9); await real.passiveRedirectChain(7, 9, undefined, undefined, 'key&extra=x');
      await real.passiveRedirectChain(7, 9, chainInput(), undefined, undefined, true); await real.passiveRedirectChain(7, 9, chainInput());
      await real.passiveRedirectChain(7, 9, undefined, 21); await real.passiveRedirectChain(7, 9, {}, 21);
      const calls = (fetcher.mock.calls as unknown as [string, RequestInit][]).filter(([path]) => path.startsWith('/api/'));
      expect(calls.map(([path]) => path)).toEqual(['', '?idempotency_key=key%26extra%3Dx', 'selection/', '', '21/', '21/'].map(suffix => '/api/organizations/7/projects/9/passive-redirect-chain/' + suffix));
      expect(calls.map(([, options]) => options.method)).toEqual(['GET', 'GET', 'POST', 'POST', 'GET', 'POST']);
      expect(calls.every(([, options]) => options.credentials === 'same-origin' && options.cache === 'no-store')).toBe(true);
      for (const [, options] of calls) { if (options.method === 'GET') expect(options.body).toBeUndefined(); else expect(options.headers).toHaveProperty('X-CSRFToken'); }
    } finally { vi.unstubAllGlobals(); }
  });
});

const redirectBinding = () => ({ ...binding(), method_version: 'passive-redirect-source-v1', observations: ['response_location'] });
function redirectEvidence(status = 302, state = 'single_classified', scheme: string | null = 'http', same: boolean | null = false) {
  const meaning = 'one_response_location_metadata_not_followed_chain_https_upgrade_browser_behavior_or_target_authority';
  return { job_id: 21, source_current: true, collection: { method: 'passive-redirect-evidence-v1', url: ORIGIN + '/', status,
    observed_at: DATE, interpretation: meaning, evidence: { method_version: 'passive-redirect-response-v1', observed_at: DATE,
      coverage: 'one_original_first_https_response_only', interpretation: 'location_metadata_not_followed_chain_https_upgrade_browser_behavior_or_target_authority',
      response_location: { method_version: 'passive-response-location-v1', state: 'observed', response_status: status,
        redirect_status: [301, 302, 303, 307, 308].includes(status), location_state: state, target_scheme: scheme, same_origin: same,
        coverage: 'one_complete_original_response_status_and_location_fields_only', interpretation: meaning } } } };
}

function responsePairResult(): ApiResult {
  const https = redirectEvidence(200, 'single_unclassified', null, null).collection;
  https.observed_at = LATER; https.evidence.observed_at = LATER;
  return { status: 200, body: { organization_id: 7, project_id: 9, comparison: {
    method_version: 'passive-original-http-https-pair-v1', organization_id: 7, project_id: 9, source_current: true,
    http: { job_id: 21, binding: httpBinding(), collection: httpEvidence().collection },
    https: { job_id: 22, binding: { ...redirectBinding(), actor_id: 2 }, collection: https },
    coverage: 'two_independently_verified_same_host_default_port_exact_source_path_original_responses_only',
    interpretation: 'two_separate_dated_responses_not_location_target_path_followed_upgrade_browser_behavior_current_https_availability_or_authenticated_http_identity',
  } } };
}
class PairFixtureApi extends FixtureApi {
  httpsRows = [{ ...job(), id: 22, status: 'succeeded' }]; httpsReads = 0;
  pairReads: number[][] = []; pairResult: ApiResult | null = null; pairPromise: Promise<ApiResult> | null = null;
  constructor() { super(); this.httpRedirects = true; this.rows = [{ ...job(), status: 'succeeded' }]; this.verifications = [verification(), httpVerification()]; }
  override async passiveRedirects(org: number, project: number, data?: Record<string, unknown>, id?: number, key?: string, preview = false): Promise<ApiResult> {
    if (data !== undefined || id !== undefined || key !== undefined || preview) throw new Error('Pair must only read saved HTTPS history');
    this.httpsReads++;
    return { status: 200, body: { organization_id: org, project_id: project, jobs: this.httpsRows, has_more: false, lookup: null } };
  }
  async passiveHttpHttpsComparison(org: number, project: number, http: number, https: number): Promise<ApiResult> {
    this.pairReads.push([org, project, http, https]); return this.pairPromise || this.pairResult || responsePairResult();
  }
}
describe('Deliberate independent original HTTP and HTTPS saved-response pair', () => {
  let api: PairFixtureApi;
  beforeEach(() => { api = new PairFixtureApi(); TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] }); });
  async function screen() {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/passive-http-redirects/7/9?http_job_id=21&https_job_id=22&passiveObservation=redirects', PassiveHeaders);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.ready()).toBe(true)); harness.detectChanges(); return { harness, component };
  }
  async function select(component: PassiveHeaders) {
    await component.refreshHttpsHistory(); component.choosePairJob('http', '21'); component.choosePairJob('https', '22');
  }
  it.each(['en', 'tr'] as const)('requires explicit independent saved-job choices/history and renders original actors/dates/status/null without collection, links, storage or automatic pair reads in %s', async (language) => {
    api.savedProductLanguage = language;
    const { harness, component } = await screen(); const storage = vi.spyOn(Storage.prototype, 'setItem');
    expect(api.httpsReads).toBe(0); expect(api.pairReads).toEqual([]); expect(component.pairHttpId()).toBe(0); expect(component.pairHttpsId()).toBe(0);
    await component.compareResponses(); expect(api.pairReads).toEqual([]); await component.refreshHttpsHistory(); harness.detectChanges();
    for (const [id, value] of [['pair-http-job', '21'], ['pair-https-job', '22']]) {
      const input = harness.routeNativeElement!.querySelector<HTMLSelectElement>('#' + id)!;
      expect(harness.routeNativeElement!.querySelector(`label[for="${id}"]`)).not.toBeNull();
      input.value = value; input.dispatchEvent(new Event('change', { bubbles: true }));
    }
    retainDraftLanguage(harness, component, api, language);
    expect(api.pairReads).toEqual([]);
    harness.routeNativeElement!.querySelector<HTMLSelectElement>('#pair-http-job')!.closest('form')!.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.busy()).toBe(false)); harness.detectChanges();
    expect(component.responsePair()).not.toBeNull(); expect(api.pairReads).toEqual([[7, 9, 21, 22]]); expect(component.frozenPair()).toBeNull();
    const texts = language === 'tr' ? [DATE, LATER, 'Özgün aktör 1', 'Özgün aktör 2', 'bağımsız doğrulama 12', 'bağımsız doğrulama 11',
      'yanıt durumu 302', 'yanıt durumu 200', 'Kimliği doğrulanmamış düz metin HTTP', 'Ayrı varsayılan doğrulanmış HTTPS', 'hedef yolunu açıklayamaz',
      'zincir veya önce/sonra nedensel sonucu değildir', 'Güncel HTTPS kullanılabilirliği', 'null kalır', 'single_unclassified']
      : [DATE, LATER, 'Original actor 1', 'Original actor 2', 'independent verification 12', 'independent verification 11',
      'response status 302', 'response status 200', 'Unauthenticated plaintext HTTP', 'Separately default-validated HTTPS', 'cannot reveal its target path',
      'not a chain', 'No current HTTPS availability', 'remains null', 'single_unclassified'];
    for (const text of texts) expect(harness.routeNativeElement!.textContent).toContain(text);
    expect([...harness.routeNativeElement!.querySelectorAll('pre')].every(node => node.getAttribute('lang') === 'en')).toBe(true);
    expect(harness.routeNativeElement!.querySelectorAll('a')).toHaveLength(1); expect(harness.routeNativeElement!.querySelector('img, script, iframe')).toBeNull();
    expect(api.commands).toEqual([]); expect(api.ownership).toEqual([]); expect(api.previews).toBe(0);
    expect(api.redirectFindingReads.concat(api.findingReads, api.tlsFindingReads, api.resourceFindingReads)).toEqual([]);
    expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
  });
  it('accepts either original capture order, distinct original actors and independently unknown Location syntax instead of inferring a followed upgrade', async () => {
    const { component } = await screen();
    for (const httpLater of [false, true]) for (const state of ['absent', 'present_empty', 'multiple_fields', 'single_unclassified', 'single_classified']) {
      await select(component); const result = responsePairResult(); const pair = result.body['comparison'] as any;
      pair.http.collection = httpEvidence(404, state, state === 'single_classified' ? 'http' : null, state === 'single_classified' ? true : null, state === 'single_classified' ? false : null).collection;
      pair.http.collection.observed_at = httpLater ? LATER : DATE; pair.http.collection.evidence.observed_at = pair.http.collection.observed_at;
      pair.https.collection.observed_at = httpLater ? DATE : LATER; pair.https.collection.evidence.observed_at = pair.https.collection.observed_at;
      api.pairResult = result; await component.compareResponses(); expect(component.responsePair()).not.toBeNull();
      pair.http.collection.status = 599; expect((component.responsePair()?.['http'] as any).collection.status).toBe(404);
    }
  });
  it('rejects strict envelopes, independent binding/family/date/status/bool-null/private shapes and source-path mismatches for BOTH originals', async () => {
    const { component } = await screen();
    const mutations: ((p: any) => void)[] = [p => p.source_current = 1, p => p.organization_id = 8, p => p.project_id = 10,
      p => p.method_version = 'followed-upgrade', p => p.coverage = 'whole_site', p => p.interpretation = 'secure', p => p.raw = 'private',
      p => p.http.job_id = 22, p => p.https.job_id = 21, p => p.https.binding.verification_id = 12,
      p => { p.https.collection.url += 'different'; p.https.binding.url = p.https.collection.url; },
      p => p.http.collection.evidence.response_location.same_hostname_default_https = 1,
      p => p.http.collection.evidence.response_location.same_origin = true,
      p => p.https.collection.evidence.response_location.same_hostname_default_https = false];
    for (const scheme of ['http', 'https']) for (const mutate of [
      (r: any) => r.job_id = true, (r: any) => r.binding.actor_id = true, (r: any) => r.binding.actor_id = 0,
      (r: any) => r.binding.method_version = 'passive-header-source-v1', (r: any) => r.binding.observations = ['response_headers'],
      (r: any) => r.binding.collection_permission = 1, (r: any) => r.binding.verified_at = LATER,
      (r: any) => r.binding.origin += ':443', (r: any) => r.binding.url += 'other', (r: any) => r.binding.source_digest = 'B'.repeat(64),
      (r: any) => r.binding.raw_token = 'private', (r: any) => r.collection.method = 'passive-header-collection-v1',
      (r: any) => r.collection.url += '?', (r: any) => r.collection.url += '#', (r: any) => r.collection.url += '/../',
      (r: any) => r.collection.status = true, (r: any) => r.collection.status = '302', (r: any) => r.collection.status = 600,
      (r: any) => r.collection.observed_at = '2026-02-30T00:00:00.000001+00:00', (r: any) => r.collection.observed_at = '2026-01-01T00:00:00.000001Z',
      (r: any) => r.collection.observed_at = '2026-01-01T00:00:00.000003+00:00', (r: any) => r.collection.observed_at = '2026-01-01T00:00:00.000000+00:00',
      (r: any) => r.collection.evidence.observed_at = DATE === r.collection.observed_at ? LATER : DATE,
      (r: any) => r.collection.evidence.response_location.redirect_status = 1, (r: any) => r.collection.evidence.response_location.response_status = 599,
      (r: any) => r.collection.evidence.response_location.same_origin = 1, (r: any) => r.collection.evidence.raw_location = '<img onerror=x>',
    ]) mutations.push(p => mutate(p[scheme]));
    // A verification at LATER is valid for the HTTPS capture at LATER; force it beyond capture for this negative.
    mutations.push(p => p.https.binding.verified_at = '2026-01-01T00:00:00.000003+00:00');
    for (const mutate of mutations) {
      await component.load(); await select(component); const result = responsePairResult(); mutate(result.body['comparison']); api.pairResult = result;
      await component.compareResponses(); expect(component.responsePair()).toBeNull(); expect(component.frozenPair()).toBeNull(); expect(component.ready()).toBe(false);
    }
    for (const status of [401, 403, 404, 409, 200]) {
      await component.load(); await select(component); api.pairResult = { status, body: {} }; await component.compareResponses();
      expect(component.responsePair()).toBeNull(); expect(component.pairHttpId()).toBe(0); expect(component.pairHttpsId()).toBe(0);
    }
  });
  it('rechecks full current configured origins/role/BOTH verification records before and after pair GET and discards late authority loss', async () => {
    const { component } = await screen(); const original = api.passiveHttpHttpsComparison.bind(api);
    for (const after of [false, true]) for (const lose of ['role', 'config', 'http-lost', 'https-lost', 'http-date', 'https-date', 'http-updated', 'https-updated']) {
      vi.restoreAllMocks(); api.role = 'owner'; api.verifications = [verification(), httpVerification()]; await component.load(); await select(component);
      const count = api.pairReads.length;
      const loss = () => {
        if (lose === 'role') api.role = 'member';
        else if (lose === 'config') vi.spyOn(api, 'projectOnboarding').mockResolvedValue({ status: 200, body: { project: { id: 9, organization_id: 7, role: 'owner', canonical_origin: ORIGIN, aliases: [] } } });
        else { const index = lose.startsWith('https') ? 0 : 1;
          if (lose.endsWith('lost')) api.verifications.splice(index, 1);
          else api.verifications[index][lose.endsWith('date') ? 'verified_at' : 'updated_at'] = '2026-01-01T00:00:00.000003+00:00'; }
      };
      if (after) vi.spyOn(api, 'passiveHttpHttpsComparison').mockImplementation(async (...args) => { const result = await original(...args); loss(); return result; });
      else loss();
      await component.compareResponses(); expect(api.pairReads).toHaveLength(count + (after ? 1 : 0)); expect(component.responsePair()).toBeNull();
      expect(component.frozenPair()).toBeNull(); expect(component.ready()).toBe(false); expect(component.verifications()).toEqual([]);
    }
    vi.restoreAllMocks();
  });
  it('pins full selected saved metadata before and after GET, denying cancellations, failed states, dates, units and foreign or malformed history', async () => {
    const { component } = await screen(); const original = api.passiveHttpHttpsComparison.bind(api);
    for (const after of [false, true]) for (const scheme of ['http', 'https']) for (const change of [
      { cancel_requested: true }, { status: 'failed' }, { updated_at: '2026-01-01T00:00:00.000003+00:00' }, { estimate_units: 0 }, { error_category: 'network_error' },
    ]) {
      vi.restoreAllMocks(); api.rows = [{ ...job(), status: 'succeeded' }]; api.httpsRows = [{ ...job(), id: 22, status: 'succeeded' }];
      await component.load(); await select(component); const count = api.pairReads.length;
      const loss = () => Object.assign((scheme === 'http' ? api.rows : api.httpsRows)[0], change);
      if (after) vi.spyOn(api, 'passiveHttpHttpsComparison').mockImplementation(async (...args) => { const result = await original(...args); loss(); return result; }); else loss();
      await component.compareResponses(); expect(api.pairReads).toHaveLength(count + (after ? 1 : 0)); expect(component.responsePair()).toBeNull(); expect(component.ready()).toBe(false);
    }
    vi.restoreAllMocks(); api.rows = [{ ...job(), status: 'succeeded' }]; api.httpsRows = [{ ...job(), id: 22, status: 'succeeded' }];
    await component.load(); await select(component); vi.spyOn(api, 'passiveRedirects').mockResolvedValue({ status: 200, body: {
      organization_id: 7, project_id: 10, jobs: api.httpsRows, has_more: false, lookup: null } });
    await component.compareResponses(); expect(component.responsePair()).toBeNull(); expect(component.httpsJobs()).toEqual([]);
  });
  it('offers only independent succeeded noncancelled saved jobs, rejects unsafe/noncanonical/missing IDs and never grants pair authority to another fixed family', async () => {
    const { harness, component } = await screen(); await select(component);
    for (const value of ['0', '-1', 'true', '021', '21.0', '21&extra=x', '9007199254740992', '99']) {
      component.choosePairJob('http', value); expect(component.pairHttpId()).toBe(0); await component.compareResponses(); expect(api.pairReads).toEqual([]);
    }
    api.httpsRows = [{ ...job(), id: 22, status: 'failed' }, { ...job(), id: 23, status: 'succeeded', cancel_requested: true }, { ...job(), id: 24 }];
    await component.refreshHttpsHistory(); expect(component.pairJobs('https')).toEqual([]); component.choosePairJob('https', '22'); expect(component.pairHttpsId()).toBe(0);
    for (const family of ['headers', 'resources', 'tls', 'redirects']) {
      const current = await harness.navigateByUrl(`/passive-${family}/7/9?passiveObservation=http-redirects`, PassiveHeaders); await harness.fixture.whenStable();
      const reads = api.httpsReads; await current.refreshHttpsHistory(); current.choosePairJob('http', '21'); current.choosePairJob('https', '22'); await current.compareResponses();
      expect(api.httpsReads).toBe(reads); expect(api.pairReads).toEqual([]); harness.detectChanges();
      expect(harness.routeNativeElement!.textContent).not.toContain('Two independently saved original HTTP and HTTPS');
    }
  });
  it('clears pair choices/results on edits, inspection, preview, refresh and ownership changes', async () => {
    const { component } = await screen();
    for (const action of [() => component.editUrl(HTTP_ORIGIN + '/'), () => component.editOrigin(HTTP_ORIGIN), () => component.editPermission(false),
      () => component.inspect(21), () => component.preview(), () => component.load(), () => component.refreshHttpsHistory(), () => component.revoke(component.verifications()[0])]) {
      api.verifications = [verification(), httpVerification()]; await component.load(); await select(component); await component.compareResponses(); expect(component.responsePair()).not.toBeNull();
      await action(); expect(component.responsePair()).toBeNull(); expect(component.frozenPair()).toBeNull(); expect(component.pairHttpId()).toBe(0); expect(component.pairHttpsId()).toBe(0);
    }
  });
  it('freezes both IDs/full original metadata only in memory and discards genuinely late responses after edit, scope/family/route changes and destruction', async () => {
    const view = await screen(); const harness = view.harness; let component = view.component;
    for (const action of ['edit', 'choose', 'organization', 'project', 'family', 'destroy']) {
      api.pairPromise = null; component = await harness.navigateByUrl('/passive-http-redirects/7/9', PassiveHeaders); await harness.fixture.whenStable(); await component.load(); await select(component);
      let resolve!: (row: ApiResult) => void; api.pairPromise = new Promise(done => resolve = done); const count = api.pairReads.length;
      const waiting = component.compareResponses(); await vi.waitFor(() => expect(api.pairReads).toHaveLength(count + 1));
      expect(component.frozenPair()).toEqual({ http: api.rows[0], https: api.httpsRows[0] });
      if (action === 'edit') component.editPermission(false);
      else if (action === 'choose') component.choosePairJob('http', '0');
      else if (action === 'destroy') harness.fixture.destroy();
      else await harness.navigateByUrl(action === 'organization' ? '/passive-http-redirects/8/9' : action === 'project' ? '/passive-http-redirects/7/10' : '/passive-redirects/7/9', PassiveHeaders);
      const error = component.error(); resolve(responsePairResult()); await waiting;
      expect(component.responsePair()).toBeNull(); expect(component.frozenPair()).toBeNull(); expect(component.error()).toBe(error);
    }
  });
  it('uses only the fixed bodyless exact two-ID GET with private same-origin/no-store fetch', async () => {
    const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) })); vi.stubGlobal('fetch', fetcher);
    try { TestBed.resetTestingModule(); await TestBed.inject(AccountApi).passiveHttpHttpsComparison(7, 9, 21, 22);
      expect(fetcher.mock.calls).toEqual([['/api/organizations/7/projects/9/passive-http-redirects/comparison/?http_job_id=21&https_job_id=22', {
        method: 'GET', headers: {}, body: undefined, credentials: 'same-origin', cache: 'no-store' }]]);
    } finally { vi.unstubAllGlobals(); }
  });
});
function redirectCandidateReport(item = redirectEvidence()) {
  const location = item.collection.evidence.response_location; const classified = location.location_state === 'single_classified';
  return { job_id: 21, source_current: true, method_version: 'passive-redirect-candidates-v1', binding: redirectBinding(), collection: item.collection,
    availability: { target_metadata: classified ? 'observed' : 'unavailable' },
    coverage: 'one_original_first_https_response_classified_location_metadata_only',
    interpretation: 'dated_http_scheme_location_reference_not_followed_redirect_downgrade_https_upgrade_browser_behavior_severity_or_target_authority',
    candidates: classified && location.target_scheme === 'http' ? [{ detector: 'http_scheme_location_reference_candidate', evidence: {
      response_status: location.response_status, redirect_status: location.redirect_status, location_state: location.location_state,
      target_scheme: location.target_scheme, same_origin: location.same_origin } }] : [] };
}

async function redirectFindingResult(saved = false, report = redirectCandidateReport()): Promise<ApiResult> {
  const findings = [];
  if (saved) for (const candidate of report.candidates) {
    const evidence = { source: 'passive_first_response_location', job_id: report.job_id, binding: report.binding,
      collection_sha256: await sha(report.collection), observed_at: report.collection.observed_at, status: report.collection.status,
      availability: report.availability, fact: candidate.evidence, coverage: report.coverage, interpretation: report.interpretation };
    findings.push({ id: 100, source_passive_redirect_id: report.job_id, detector: candidate.detector, method_version: 'passive-redirect-finding-v1',
      subject: report.collection.url, fingerprint: await sha(['passive-redirect-finding-v1', candidate.detector, evidence]), evidence,
      confidence: 'dated_location_fact_not_risk_severity', detected_at: LATER });
  }
  return { status: 200, body: { organization_id: 7, project_id: 9, candidates: report, candidate_digest: await sha(report),
    finding_set: { method_version: 'passive-redirect-finding-v1', project_id: 9, job_id: report.job_id, source_current: true,
      state: findings.length ? 'current_materialized_facts' : 'no_retained_materialized_findings', findings } } };
}

describe('Separate exact first-response Location native consumers', () => {
  let api: FixtureApi;
  beforeEach(() => { api = new FixtureApi(); api.redirects = true;
    TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] }); });
  async function screen() {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/passive-redirects/7/9', PassiveHeaders);
    await harness.fixture.whenStable(); harness.detectChanges(); return { harness, component };
  }
  async function preview(component: PassiveHeaders) { component.editUrl(ORIGIN + '/'); component.editPermission(true); await component.preview(); }
  function detail(item = redirectEvidence()) {
    return { status: 200, body: { organization_id: 7, project_id: 9, job: { ...job(), status: 'succeeded' }, evidence: item } };
  }
  function candidates(report = redirectCandidateReport()): ApiResult {
    return { status: 200, body: { organization_id: 7, project_id: 9, candidates: report } };
  }
  it('independently reads and deliberately saves one exact original Location fact without new work, browser storage or attribution', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen(); await component.load(); harness.detectChanges();
    const storage = vi.spyOn(Storage.prototype, 'setItem'); expect(api.redirectFindingReads).toEqual([]);
    expect(harness.routeNativeElement!.textContent).toContain('Inspect current original Location findings (no save)');
    const report = redirectCandidateReport(redirectEvidence(200)); api.redirectFindingResult = await redirectFindingResult(false, report);
    await component.inspectFindings(21); harness.detectChanges(); expect(api.redirectFindingCommands).toEqual([]);
    expect(component.findingInspection()?.findingSet['state']).toBe('no_retained_materialized_findings');
    expect(harness.routeNativeElement!.textContent).toContain('does not mean zero eligible candidates');
    const read = api.passiveRedirectFindings.bind(api);
    vi.spyOn(api, 'passiveRedirectFindings').mockImplementation(async (...args) => args[3] ? redirectFindingResult(true, report).then(result => {
      api.redirectFindingCommands.push([args[2], args[3]!]); return result;
    }) : read(...args));
    await component.saveFindings(); harness.detectChanges(); expect(api.redirectFindingCommands).toEqual([[21, await sha(report)]]);
    expect(component.findingPending()).toBeNull(); expect(component.findingInspection()?.findingSet['findings']).toHaveLength(1);
    for (const text of [DATE, LATER, 'HTTP 200', 'common redirect status: false', 'dated_location_fact_not_risk_severity',
      'no personal attribution', 'Detection time', 'no site request', 'target lookup/follow']) expect(harness.routeNativeElement!.textContent).toContain(text);
    const result = await redirectFindingResult(true, report); api.redirectFindingResult = result; await component.inspectFindings(21);
    (result.body['finding_set'] as any).findings[0].evidence.fact.response_status = 599;
    expect((component.findingInspection()?.findingSet['findings'] as any[])[0].evidence.fact.response_status).toBe(200);
    expect(api.commands).toEqual([]); expect(api.findingReads).toEqual([]); expect(api.resourceFindingReads).toEqual([]); expect(api.tlsFindingReads).toEqual([]);
    expect(storage).not.toHaveBeenCalled(); storage.mockRestore(); vi.restoreAllMocks();
  });
  it('preserves original classification unknown-null and HTTPS eligible-empty versus absent retained sets without an empty save', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen();
    for (const state of ['absent', 'present_empty', 'multiple_fields', 'single_unclassified', 'single_classified']) {
      const report = redirectCandidateReport(redirectEvidence(200, state, state === 'single_classified' ? 'https' : null, state === 'single_classified' ? true : null));
      api.redirectFindingResult = await redirectFindingResult(false, report); await component.inspectFindings(21); harness.detectChanges();
      expect(component.findingInspection()).not.toBeNull(); expect(component.candidateRows()).toEqual([]); await component.saveFindings();
      expect(harness.routeNativeElement!.textContent).toContain('No retained materialized findings');
      expect(harness.routeNativeElement!.textContent).toContain(state === 'single_classified' ? 'Original classified HTTPS reference' : 'Original target metadata unknown');
    }
    expect(api.redirectFindingCommands).toEqual([]); api.redirectFindingResult = { status: 409, body: {} }; await component.inspectFindings(21);
    expect(component.findingInspection()).toBeNull(); expect(component.candidateReport()).toBeNull(); expect(component.ready()).toBe(false);
  });
  it('rejects original SHA, max1 compact Location identity, status-real-boolean-classification availability/date/fact tampering', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { component } = await screen();
    const mutations: ((b: any) => void)[] = [
      b => b.candidate_digest = 'a'.repeat(64), b => b.organization_id = 99, b => b.raw_location = 'private',
      b => b.candidates.availability.target_metadata = 'unavailable', b => b.candidates.binding.observations = ['response_headers'],
      b => b.candidates.collection.status = true, b => b.candidates.collection.evidence.response_location.redirect_status = 1,
      b => b.finding_set.job_id = 99, b => b.finding_set.source_current = 1, b => b.finding_set.method_version = 'passive-resource-finding-v1',
      b => b.finding_set.state = 'secure', b => b.finding_set.findings.push(b.finding_set.findings[0]),
      b => b.finding_set.findings[0].id = true, b => b.finding_set.findings[0].source_passive_redirect_id = 99,
      b => b.finding_set.findings[0].source_passive_tls_id = 21, b => b.finding_set.findings[0].subject += 'other',
      b => b.finding_set.findings[0].confidence = 'high', b => b.finding_set.findings[0].fingerprint = 'a'.repeat(64),
      b => b.finding_set.findings[0].detected_at = '2025-01-01T00:00:00Z', b => b.finding_set.findings[0].detected_at = '2026-02-30T00:00:00Z',
      b => b.finding_set.findings[0].evidence.collection_sha256 = 'a'.repeat(64), b => b.finding_set.findings[0].evidence.source = 'passive_response_headers',
      b => b.finding_set.findings[0].evidence.status = 200, b => b.finding_set.findings[0].evidence.availability.target_metadata = 'unavailable',
      b => b.finding_set.findings[0].evidence.fact.redirect_status = 1, b => b.finding_set.findings[0].evidence.fact.response_status = 200,
      b => b.finding_set.findings[0].evidence.fact.same_origin = true, b => b.finding_set.findings[0].evidence.fact.target_scheme = 'https',
      b => b.finding_set.findings[0].evidence.raw_location = 'private', b => b.finding_set.findings[0].actor_id = 1,
    ];
    for (const mutate of mutations) { const result = await redirectFindingResult(true); mutate(result.body); api.redirectFindingResult = result;
      await component.inspectFindings(21); expect(component.findingInspection()).toBeNull(); expect(component.candidateReport()).toBeNull(); }
    for (const result of [await headerFindingResult(true), await resourceFindingResult(true), await tlsFindingResult(true)]) {
      api.redirectFindingResult = result; await component.inspectFindings(21); expect(component.findingInspection()).toBeNull();
    }
    expect(api.redirectFindingCommands).toEqual([]);
  });
  it('rechecks original role/configuration/verification immediately before POST and after late success, and denies changed original reports', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { component } = await screen(); const read = api.passiveRedirectFindings.bind(api);
    for (const afterPost of [false, true]) for (const lose of [() => api.role = 'member', () => api.verifications = [], () => api.verifications[0]['verified_at'] = LATER,
      () => vi.spyOn(api, 'projectOnboarding').mockImplementation(async (org, project) => ({ status: 200, body: { project: {
        id: project, organization_id: org, role: 'owner', canonical_origin: ORIGIN, aliases: ['https://other.example.invalid'] } } }))]) {
      api.role = 'owner'; api.verifications = [verification()]; await component.load(); await component.inspectRedirectCandidates(21);
      const count = api.redirectFindingCommands.length;
      vi.spyOn(api, 'passiveRedirectFindings').mockImplementation(async (...args) => { const result = await read(...args); if (!!args[3] === afterPost) lose(); return result; });
      await component.saveFindings(); expect(api.redirectFindingCommands).toHaveLength(count + (afterPost ? 1 : 0));
      expect(component.findingInspection()).toBeNull(); expect(component.findingPending()).toBeNull(); expect(component.candidateReport()).toBeNull();
      expect(component.ready()).toBe(false); vi.restoreAllMocks();
    }
    api.role = 'owner'; api.verifications = [verification()]; await component.load(); await component.inspectRedirectCandidates(21);
    const changed = redirectCandidateReport(); changed.binding.actor_id = 2; api.redirectFindingResult = await redirectFindingResult(false, changed);
    const count = api.redirectFindingCommands.length; await component.saveFindings(); expect(api.redirectFindingCommands).toHaveLength(count);
    expect(component.error()).toContain('No fact-save command sent');
  });
  it('freezes original same-job SHA/set in memory and reconciles complete sets without replay or caller attribution; rejects changed sets', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen(); await component.inspectRedirectCandidates(21);
    api.findingUncertain = true; await component.saveFindings(); const frozen = structuredClone(component.findingPending());
    expect(frozen?.candidateDigest).toBe(await sha(redirectCandidateReport())); expect(frozen?.job.id).toBe(21);
    harness.detectChanges(); expect(harness.routeNativeElement!.textContent).toContain('Location-fact save outcome is uncertain');
    await component.saveFindings(); await component.inspectFindings(21); expect(api.redirectFindingCommands).toHaveLength(1);
    await component.reconcileFindings(); expect(component.findingPending()).toBeNull(); expect(api.redirectFindingReads).toEqual([21, 21]);
    expect(api.redirectFindingCommands).toHaveLength(1); expect(component.message()).toContain('does not identify who saved it');
    await component.saveFindings(); expect(component.findingPending()?.findingSet['state']).toBe('current_materialized_facts');
    const changed = await redirectFindingResult(true); (changed.body['finding_set'] as any).findings[0].id = 101;
    api.redirectFindingResult = changed; await component.reconcileFindings(); expect(component.findingPending()).toBeNull(); expect(component.findingInspection()).toBeNull();
    expect(component.error()).toContain('changed or became unavailable');
  });
  it('keeps absent-set/network uncertainty distinct from no-op, clears changed or denied lookups and allows deliberate discard', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { component } = await screen(); await component.inspectRedirectCandidates(21); api.findingDrop = true;
    await component.saveFindings(); const frozen = structuredClone(component.findingPending()); await component.reconcileFindings();
    expect(component.findingPending()).toEqual(frozen); expect(component.message()).toContain('not confirmed no-op');
    api.redirectFindingPromise = Promise.reject(new Error('lookup unavailable')); await component.reconcileFindings();
    expect(component.findingPending()).toEqual(frozen); expect(component.findingInspection()).toBeNull(); expect(api.redirectFindingCommands).toHaveLength(1);
    api.redirectFindingPromise = null; const changed = redirectCandidateReport(); changed.binding.actor_id = 2;
    api.redirectFindingResult = await redirectFindingResult(false, changed); await component.reconcileFindings(); expect(component.findingPending()).toBeNull();
    api.redirectFindingResult = null; await component.inspectRedirectCandidates(21); await component.saveFindings();
    api.redirectFindingResult = { status: 403, body: {} }; await component.reconcileFindings(); expect(component.findingPending()).toBeNull(); expect(component.ready()).toBe(false);
    api.redirectFindingResult = null; await component.load(); await component.inspectRedirectCandidates(21); await component.saveFindings(); component.discardFindingCommand();
    expect(component.findingPending()).toBeNull(); expect(component.message()).toContain('Stored facts may still exist');
  });
  it('clears Location facts/uncertainty on edits, operations, ownership, scope-family-route-destroy and discards late GET/POST replies', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const view = await screen(); const harness = view.harness; let component = view.component;
    for (const action of [() => component.editOrigin(ORIGIN), () => component.editPermission(false), () => component.editUrl(ORIGIN + '/'),
      () => component.inspect(21), () => component.inspectRedirectCandidates(21), () => component.preview(), () => component.load(), () => component.revoke(component.verifications()[0])]) {
      api.verifications = [verification()]; await component.load(); await component.inspectRedirectCandidates(21); api.findingUncertain = true;
      await component.saveFindings(); expect(component.findingPending()).not.toBeNull(); await action();
      expect(component.findingPending()).toBeNull(); expect(component.findingInspection()).toBeNull();
    }
    api.verifications = [verification()]; await component.load(); let resolve!: (result: ApiResult) => void;
    api.redirectFindingPromise = new Promise(done => resolve = done); const editing = component.inspectFindings(21);
    component.editPermission(false); resolve(await redirectFindingResult(true)); await editing; expect(component.findingInspection()).toBeNull(); api.redirectFindingPromise = null;
    await component.inspectRedirectCandidates(21); api.findingUncertain = false; api.redirectFindingPostPromise = new Promise(done => resolve = done);
    const count = api.redirectFindingCommands.length; const saving = component.saveFindings();
    for (let i = 0; i < 100 && api.redirectFindingCommands.length === count; i++) await new Promise(done => setTimeout(done, 0));
    expect(api.redirectFindingCommands).toHaveLength(count + 1); await harness.navigateByUrl('/passive-redirects/7/10', PassiveHeaders); await harness.fixture.whenStable();
    const error = component.error(); resolve({ status: 403, body: {} }); await saving;
    expect(component.error()).toBe(error); expect(component.findingPending()).toBeNull(); api.redirectFindingPostPromise = null;
    component = await harness.navigateByUrl('/passive-redirects/7/9', PassiveHeaders); await harness.fixture.whenStable();
    api.redirectFindingPromise = new Promise(done => resolve = done); const family = component.inspectFindings(21);
    await harness.navigateByUrl('/passive-tls/7/9', PassiveHeaders); resolve(await redirectFindingResult(true)); await family; expect(component.findingInspection()).toBeNull();
    api.redirectFindingPromise = null; component = await harness.navigateByUrl('/passive-redirects/7/9', PassiveHeaders); await harness.fixture.whenStable();
    api.redirectFindingPromise = new Promise(done => resolve = done); const destroying = component.inspectFindings(21);
    harness.fixture.destroy(); resolve(await redirectFindingResult(true)); await destroying; expect(component.findingInspection()).toBeNull(); expect(component.findingPending()).toBeNull();
  });
  it('keeps commands family-fixed and uses only bodyless GET or SHA-only CSRF POST for Location', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const harness = await RouterTestingHarness.create();
    for (const family of ['headers', 'resources', 'tls']) {
      const component = await harness.navigateByUrl(`/passive-${family}/7/9?passiveObservation=redirects`, PassiveHeaders); await harness.fixture.whenStable();
      component.candidateReport.set(redirectCandidateReport()); await component.saveFindings(); harness.detectChanges();
      expect(harness.routeNativeElement!.textContent).not.toContain('Explicitly save this original Location fact');
    }
    expect(api.redirectFindingReads).toEqual([]); expect(api.redirectFindingCommands).toEqual([]);
    const component = await harness.navigateByUrl('/passive-redirects/7/9', PassiveHeaders); await harness.fixture.whenStable();
    for (const report of [headerCandidateReport(), resourceCandidateReport(), tlsCandidateReport()]) { component.candidateReport.set(report); await component.saveFindings(); }
    expect(api.redirectFindingReads).toEqual([]);
    const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) })); vi.stubGlobal('fetch', fetcher);
    TestBed.resetTestingModule(); const real = TestBed.inject(AccountApi); await real.passiveRedirectFindings(7, 9, 21); await real.passiveRedirectFindings(7, 9, 21, 'a'.repeat(64));
    const calls = fetcher.mock.calls as unknown as [string, RequestInit][];
    expect(calls.map(([path]) => path)).toEqual(['/api/organizations/7/projects/9/passive-redirects/21/findings/', '/_allauth/browser/v1/auth/session', '/api/organizations/7/projects/9/passive-redirects/21/findings/']);
    expect(calls[0][1].method).toBe('GET'); expect(calls[0][1].body).toBeUndefined(); expect(calls[2][1].method).toBe('POST');
    expect(calls[2][1].body).toBe(JSON.stringify({ candidate_digest: 'a'.repeat(64) })); expect(calls[2][1].headers).toHaveProperty('X-CSRFToken');
    expect(calls.every(([, options]) => options.cache === 'no-store' && options.credentials === 'same-origin')).toBe(true); vi.unstubAllGlobals();
  });
  it.each(['en', 'tr'] as const)('deliberately inspects cloned original HTTP references without automatic reads, target links, saves, units or priority in %s', async (language) => {
    api.savedProductLanguage = language;
    api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen();
    await component.load(); harness.detectChanges();
    expect(api.redirectCandidateCalls).toEqual([]); const storage = vi.spyOn(Storage.prototype, 'setItem');
    const report = redirectCandidateReport(redirectEvidence(200)); api.redirectCandidateResult = candidates(report);
    const button = [...harness.routeNativeElement!.querySelectorAll('button')].find(row => row.textContent!.includes(language === 'tr' ? 'Özgün HTTP şemalı Location' : 'Inspect original HTTP-scheme Location'))!;
    button.click(); await harness.fixture.whenStable(); harness.detectChanges();
    expect(api.redirectCandidateCalls).toEqual([21]); expect(component.candidateRows()).toHaveLength(1);
    for (const text of [DATE, 'HTTP 200', language === 'tr' ? 'yaygın yönlendirme durumu: false' : 'common redirect status: false',
      language === 'tr' ? 'aynı köken: false' : 'same-origin: false',
      language === 'tr' ? "HTTPS'ten HTTP'ye geçişi kanıtlamaz" : 'does not prove a redirect downgrade',
      language === 'tr' ? 'bulgu kaydetme' : 'Finding save', language === 'tr' ? 'Ham hedef bağlantısı yok' : 'No raw target link']) {
      expect(harness.routeNativeElement!.textContent).toContain(text);
    }
    const originalCandidates = structuredClone(component.candidateReport());
    const captionNode = [...harness.routeNativeElement!.querySelectorAll('li > span')].find(row => row.textContent === component.candidateText(component.candidateRows()[0]))!;
    expect(captionNode.getAttribute('lang')).toBe(language);
    retainDraftLanguage(harness, component, api, language);
    expect(component.candidateReport()).toEqual(originalCandidates);
    expect(harness.routeNativeElement!.querySelector('pre[lang="en"]')?.textContent).toContain(JSON.stringify(component.candidateReport(), null, 2));
    report.candidates[0].evidence.response_status = 599; expect(component.candidateRows()[0].evidence['response_status']).toBe(200);
    expect(api.findingReads).toEqual([]); expect(api.resourceFindingReads).toEqual([]); expect(api.tlsFindingReads).toEqual([]);
    expect(api.findingCommands).toEqual([]); expect(api.resourceFindingCommands).toEqual([]); expect(api.tlsFindingCommands).toEqual([]);
    expect(api.commands).toEqual([]); expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
    expect(harness.routeNativeElement!.querySelector('img, script, iframe')).toBeNull();
    expect(harness.routeNativeElement!.querySelectorAll('a')).toHaveLength(1);
    expect(api.redirectFindingReads).toEqual([]); expect(api.redirectFindingCommands).toEqual([]);
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Bu özgün Location olgusunu açıkça kaydedin' : 'Explicitly save this original Location fact');
  });
  it('keeps all original status and unknown classification/null versus HTTPS eligible-empty meanings distinct', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen();
    for (const status of [200, 201, 300, 301, 302, 303, 304, 307, 308, 404, 599]) {
      for (const state of ['absent', 'present_empty', 'multiple_fields', 'single_unclassified']) {
        api.redirectCandidateResult = candidates(redirectCandidateReport(redirectEvidence(status, state, null, null)));
        await component.inspectRedirectCandidates(21); harness.detectChanges();
        expect(component.candidateReport()).not.toBeNull(); expect(component.candidateRows()).toEqual([]);
        expect(harness.routeNativeElement!.textContent).toContain('Original target metadata unknown');
        expect(harness.routeNativeElement!.textContent).not.toContain('has no eligible HTTP-scheme candidate');
      }
      for (const [scheme, sameOrigin] of [['http', false], ['https', false], ['https', true]] as const) {
        api.redirectCandidateResult = candidates(redirectCandidateReport(redirectEvidence(status, 'single_classified', scheme, sameOrigin)));
        await component.inspectRedirectCandidates(21); expect(component.candidateReport()).not.toBeNull();
        expect(component.candidateRows()).toHaveLength(scheme === 'http' ? 1 : 0);
      }
    }
    harness.detectChanges(); expect(harness.routeNativeElement!.textContent).toContain('Original classified HTTPS reference has no eligible HTTP-scheme candidate');
    expect(harness.routeNativeElement!.textContent).toContain('not a secure or whole-site result');
  });
  it('rejects complete report-binding-date-status-real-boolean-classification-null and candidate-fact tampering', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { component } = await screen();
    const mutations: ((r: any) => void)[] = [
      r => r.job_id = 99, r => r.source_current = 1, r => r.method_version = 'passive-tls-candidates-v1', r => r.coverage = 'followed_chain',
      r => r.interpretation = 'secure', r => r.raw_location = 'private', r => r.binding.actor_id = true, r => r.binding.project_id = 99,
      r => r.binding.method_version = 'passive-header-source-v1', r => r.binding.observations = ['response_headers'],
      r => r.binding.collection_permission = 1, r => r.binding.origin = 'https://foreign.example.invalid', r => r.binding.verified_at = LATER,
      r => r.binding.url = ORIGIN + '/other', r => r.binding.source_digest = 'bad',
      r => r.collection.observed_at = '2026-01-01T00:00:00.000001Z', r => r.collection.observed_at = '2026-02-30T00:00:00.000001+00:00',
      r => r.collection.observed_at = '2026-01-01T00:00:00.000003+00:00', r => r.collection.method = 'passive-redirect-collection-v1',
      r => r.collection.status = true, r => r.collection.status = '302', r => r.collection.status = 199, r => r.collection.status = 600,
      r => r.collection.evidence.observed_at = LATER, r => r.collection.evidence.response_location.response_status = 301,
      r => r.collection.evidence.response_location.redirect_status = 1, r => r.collection.evidence.response_location.redirect_status = false,
      r => r.collection.evidence.response_location.target_scheme = 'ftp', r => r.collection.evidence.response_location.target_scheme = null,
      r => r.collection.evidence.response_location.same_origin = true, r => r.collection.evidence.response_location.same_origin = 0,
      r => r.collection.evidence.response_location.same_origin = null, r => r.collection.evidence.response_location.location_state = 'absent',
      r => r.availability.target_metadata = 'unavailable', r => r.availability.extra = true, r => r.candidates[0].evidence.response_status = 200,
      r => r.candidates[0].evidence.redirect_status = 1, r => r.candidates[0].evidence.same_origin = 0,
      r => r.candidates[0].evidence.target_scheme = 'https', r => r.candidates[0].evidence.raw_target = 'private',
      r => r.candidates[0].detector = 'downgrade', r => r.candidates = [], r => r.candidates.push(r.candidates[0]),
    ];
    for (const mutate of mutations) { const report = redirectCandidateReport(); mutate(report); api.redirectCandidateResult = candidates(report);
      await component.inspectRedirectCandidates(21); expect(component.candidateReport()).toBeNull(); }
    for (const state of ['absent', 'present_empty', 'multiple_fields', 'single_unclassified']) {
      for (const [scheme, sameOrigin] of [['https', null], [null, false]] as const) {
        api.redirectCandidateResult = candidates(redirectCandidateReport(redirectEvidence(200, state, scheme, sameOrigin)));
        await component.inspectRedirectCandidates(21); expect(component.candidateReport()).toBeNull();
      }
    }
    api.redirectCandidateResult = { ...candidates(), body: { ...candidates().body, project_id: 99 } };
    await component.inspectRedirectCandidates(21); expect(component.candidateReport()).toBeNull(); expect(api.commands).toEqual([]);
  });
  it('rechecks fresh role, configured scope and exact original verification before display and fully clears authority loss', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { component } = await screen(); const read = api.passiveRedirectCandidates.bind(api);
    for (const lose of [() => api.role = 'viewer', () => api.verifications = [], () => api.verifications[0]['verified_at'] = LATER,
      () => api.verifications[0]['state'] = 'pending']) {
      api.role = 'owner'; api.verifications = [verification()]; await component.load();
      vi.spyOn(api, 'passiveRedirectCandidates').mockImplementation(async (org, project, id) => { const result = await read(org, project, id); lose(); return result; });
      await component.inspectRedirectCandidates(21); expect(component.candidateReport()).toBeNull(); expect(component.ready()).toBe(false);
      expect(component.origins()).toEqual([]); expect(component.verifications()).toEqual([]); vi.restoreAllMocks();
    }
    api.role = 'owner'; api.verifications = [verification()]; await component.load();
    vi.spyOn(api, 'projectOnboarding').mockImplementation((org, project) => Promise.resolve({ status: 200, body: { project: {
      id: project, organization_id: org, role: 'owner', canonical_origin: ORIGIN, aliases: ['https://added.example.invalid'] } } }));
    await component.inspectRedirectCandidates(21); expect(component.candidateReport()).toBeNull(); expect(component.ready()).toBe(false); vi.restoreAllMocks();
  });
  it('clears on edits, operations, ownership, denied refresh and late scope-family-route-destroy responses', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen();
    for (const clear of [() => component.editOrigin(ORIGIN), () => component.editUrl(ORIGIN + '/'), () => component.editPermission(false),
      () => component.inspect(21), () => component.preview(), () => component.load(), () => component.revoke(component.verifications()[0])]) {
      api.verifications = [verification()]; await component.load(); await component.inspectRedirectCandidates(21); expect(component.candidateReport()).not.toBeNull();
      await clear(); expect(component.candidateReport()).toBeNull();
    }
    api.verifications = [verification()]; await component.load();
    for (const status of [401, 403, 404, 409]) { api.redirectCandidateResult = { status, body: {} }; await component.inspectRedirectCandidates(21);
      expect(component.ready()).toBe(false); expect(component.candidateReport()).toBeNull(); await component.load(); }
    api.redirectCandidateResult = null; let resolve!: (r: ApiResult) => void;
    api.redirectCandidatePromise = new Promise(done => resolve = done); const edited = component.inspectRedirectCandidates(21);
    component.editUrl(ORIGIN + '/edited'); resolve(candidates()); await edited; expect(component.candidateReport()).toBeNull();
    api.redirectCandidatePromise = new Promise(done => resolve = done); const scoped = component.inspectRedirectCandidates(21);
    await harness.navigateByUrl('/passive-redirects/7/10', PassiveHeaders); resolve(candidates()); await scoped; expect(component.candidateReport()).toBeNull();
    api.redirectCandidatePromise = null; await harness.navigateByUrl('/passive-redirects/7/9', PassiveHeaders); await harness.fixture.whenStable();
    api.redirectCandidatePromise = new Promise(done => resolve = done); const family = component.inspectRedirectCandidates(21);
    await harness.navigateByUrl('/passive-tls/7/9', PassiveHeaders); resolve(candidates()); await family; expect(component.candidateReport()).toBeNull();
    api.redirectCandidatePromise = null; const current = await harness.navigateByUrl('/passive-redirects/7/9', PassiveHeaders); await harness.fixture.whenStable();
    api.redirectCandidatePromise = new Promise(done => resolve = done); const destroyed = current.inspectRedirectCandidates(21);
    harness.fixture.destroy(); resolve(candidates()); await destroyed; expect(current.candidateReport()).toBeNull(); expect(current.ready()).toBe(false);
  });
  it('denies unsafe/missing/failed/cancelled jobs, other families and query-family authority without calling the Location endpoint', async () => {
    const { harness, component } = await screen();
    for (const row of [job(), { ...job(), status: 'failed' }, { ...job(), status: 'succeeded', cancel_requested: true }]) {
      api.rows = [row]; await component.load(); await component.inspectRedirectCandidates(21);
    }
    await component.inspectRedirectCandidates(0); await component.inspectRedirectCandidates(9007199254740992); await component.inspectRedirectCandidates(99);
    api.rows = [{ ...job(), status: 'succeeded' }];
    for (const family of ['headers', 'resources', 'tls']) {
      const current = await harness.navigateByUrl(`/passive-${family}/7/9?passiveObservation=redirects`, PassiveHeaders); await harness.fixture.whenStable();
      await current.inspectRedirectCandidates(21); harness.detectChanges(); expect(current.candidateReport()).toBeNull();
      expect(harness.routeNativeElement!.textContent).not.toContain('Inspect original HTTP-scheme Location review candidate');
    }
    expect(api.redirectCandidateCalls).toEqual([]);
  });
  it('uses only the fixed bodyless same-origin no-store Location candidate GET', async () => {
    const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) })); vi.stubGlobal('fetch', fetcher);
    TestBed.resetTestingModule(); const real = TestBed.inject(AccountApi); await real.passiveRedirectCandidates(7, 9, 21);
    expect(fetcher.mock.calls).toEqual([['/api/organizations/7/projects/9/passive-redirects/21/candidates/', {
      method: 'GET', headers: {}, body: undefined, credentials: 'same-origin', cache: 'no-store' }]]); vi.unstubAllGlobals();
  });
  it.each(['en', 'tr'] as const)('requires independent unchecked permission and fresh exact binding, reusing ownership without granting target authority in %s', async (language) => {
    api.savedProductLanguage = language;
    const { harness, component } = await screen(); const storage = vi.spyOn(Storage.prototype, 'setItem');
    expect(component.permission()).toBe(false); component.editUrl(ORIGIN + '/'); await component.preview(); expect(api.previews).toBe(0);
    component.editOrigin(ORIGIN); await component.createChallenge(); expect(component.challenge()?.content).toBe('a'.repeat(43));
    await component.verify(component.verifications()[0]); expect(component.challenge()).toBeNull(); expect(component.message()).toContain('not proof');
    await component.revoke(component.verifications()[0]); expect(api.ownership.map(row => row[0])).toEqual(['POST', 'POST', 'DELETE']);
    for (const url of [ORIGIN + '/?q=x', ORIGIN + '/#x', ORIGIN + ':444/', 'https://foreign.example.invalid/', 'javascript:evil()']) {
      component.editUrl(url); component.editPermission(true); await component.preview(); expect(component.selection()).toBeNull();
    }
    await preview(component); retainDraftLanguage(harness, component, api, language); api.changed = true; await component.launch(); expect(api.commands).toEqual([]);
    api.changed = false; await preview(component); const frozen = structuredClone(component.selection()); await component.launch();
    expect(api.commands[0]['observations']).toEqual(['response_location']); expect(api.commands[0]['url']).toBe(ORIGIN + '/');
    expect(api.commands[0]['selection_digest']).toBe(frozen!.selection_digest); expect(api.families.every(value => value === 'redirects')).toBe(true);
    expect(storage).not.toHaveBeenCalled(); storage.mockRestore(); harness.detectChanges();
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'hedefini takip etmeden' : 'without following its target');
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Başlık, TLS veya kaynak izni bu ayrı ilk yanıt Location gözlemine izin vermez' : 'Header, TLS or resource permission does not authorize');
  });
  it('freezes own original uncertain command, reconciles without replay, deliberately retries only unchanged source, and cancels separately', async () => {
    const { component } = await screen(); await preview(component); api.uncertain = true; await component.launch();
    const frozen = structuredClone(component.pending()); await component.reconcile(); expect(component.pending()).toBeNull();
    expect(api.lookups).toEqual([frozen!.key]); expect(api.commands.length).toBe(1);
    api.uncertain = false; api.rows = []; await component.load(); await preview(component); api.drop = true; await component.launch();
    const unsaved = structuredClone(component.pending()); await component.reconcile(); api.changed = true; await component.retry();
    expect(api.commands.length).toBe(2); expect(component.pending()).toEqual(unsaved);
    api.changed = false; await component.reconcile(); api.drop = false; await component.retry(); expect(api.commands[2]).toEqual(api.commands[1]);
    await component.load(); api.uncertain = true; await component.cancel(21); expect(component.pending()?.jobId).toBe(21);
    await component.reconcile(); expect(component.pending()).toBeNull(); expect(component.selected()?.cancel_requested).toBe(true);
    expect(api.commands).toHaveLength(4); expect(api.commands[3]).toEqual({});
  });
  it('preserves all original status-cardinality-classification-null combinations and capture microseconds without target links', async () => {
    const { harness, component } = await screen();
    for (const status of [200, 201, 300, 301, 302, 303, 304, 307, 308, 404, 599]) {
      for (const state of ['absent', 'present_empty', 'multiple_fields', 'single_unclassified']) {
        api.detail = detail(redirectEvidence(status, state, null, null)); await component.inspect(21); expect(component.evidence()).not.toBeNull();
      }
      for (const [scheme, same] of [['http', false], ['https', false], ['https', true]] as const) {
        api.detail = detail(redirectEvidence(status, 'single_classified', scheme, same)); await component.inspect(21); expect(component.evidence()).not.toBeNull();
      }
    }
    api.detail = detail(redirectEvidence(200, 'single_unclassified', null, null)); await component.inspect(21); harness.detectChanges();
    for (const text of [DATE, 'single_unclassified', 'Null is not zero', 'no target permission', 'not prove a followed redirect']) expect(harness.routeNativeElement!.textContent).toContain(text);
    expect(harness.routeNativeElement!.querySelector('img, script, iframe')).toBeNull(); expect(api.commands).toEqual([]);
    api.detail = { status: 200, body: { ...detail().body, evidence: null } }; await component.inspect(21); expect(component.evidence()).toBeNull();
  });
  it('withholds family substitutions/raw fields, invalid dates/statuses, missing or partial captures and nonboolean or impossible classifications', async () => {
    const { component } = await screen(); const bad: ApiResult[] = [{ status: 403, body: {} }];
    for (const changes of [{ project_id: 99 }, { raw_location: 'private' }]) { const row = detail(); Object.assign(row.body, changes); bad.push(row); }
    for (const changes of [{ id: 99 }, { status: 'failed' }, { cancel_requested: true }]) { const row = detail(); Object.assign(row.body.job, changes); bad.push(row); }
    for (const changes of [{ method: 'passive-redirect-collection-v1' }, { url: 'https://foreign.example.invalid/' }, { url: ORIGIN + '/?x=y' },
      { status: true }, { status: '302' }, { status: 199 }, { status: 600 }, { observed_at: '2026-01-01T00:00:00.000001Z' },
      { observed_at: '2026-02-30T00:00:00.000001+00:00' }, { observed_at: '2026-01-01T00:00:00.000003+00:00' },
      { observed_at: '2026-01-01T00:00:00.000000+00:00' }, { raw_body: 'private' }, { interpretation: 'secure' }]) {
      const row = detail(); Object.assign(row.body.evidence.collection, changes); bad.push(row);
    }
    for (const changes of [{ method_version: 'passive-resource-response-v1' }, { observed_at: LATER }, { coverage: 'whole_page' }, { headers: {} }]) {
      const row = detail(); Object.assign(row.body.evidence.collection.evidence, changes); bad.push(row);
    }
    for (const changes of [{ state: 'unavailable' }, { response_status: 301 }, { response_status: true }, { redirect_status: 1 },
      { redirect_status: false }, { location_state: 'secure' }, { location_state: 'absent' }, { target_scheme: 'ftp' },
      { target_scheme: null }, { same_origin: true }, { same_origin: 0 }, { same_origin: null }, { raw_location: 'private' }]) {
      const row = detail(); Object.assign(row.body.evidence.collection.evidence.response_location, changes); bad.push(row);
    }
    for (const state of ['absent', 'present_empty', 'multiple_fields', 'single_unclassified']) {
      bad.push(detail(redirectEvidence(200, state, 'https', null)), detail(redirectEvidence(200, state, null, false)));
    }
    for (const row of bad) { api.detail = row; await component.inspect(21); expect(component.selected()).toBeNull(); expect(component.evidence()).toBeNull(); }
  });
  it('rejects hidden source/permission family substitutions and full digest mismatches before any command', async () => {
    const { component } = await screen();
    for (const changes of [{ method_version: 'passive-resource-source-v1' }, { observations: ['response_headers'] },
      { observations: ['response_location', 'response_headers'] }, { collection_permission: 1 }, { url: ORIGIN + '/other' },
      { origin: ORIGIN + ':443' }, { raw_location_digest: 'a'.repeat(64) }]) {
      api.previewResult = await api.preview(); const selection = api.previewResult.body['selection'] as Record<string, unknown>;
      Object.assign(selection['binding'] as object, changes); api.previewResult.body['selection_digest'] = await sha(selection);
      await preview(component); expect(component.selection()).toBeNull();
    }
    api.previewResult = await api.preview(); api.previewResult.body['selection_digest'] = 'a'.repeat(64); await preview(component);
    expect(component.selection()).toBeNull(); expect(api.commands).toEqual([]);
  });
  it('clears independent permission/frozen uncertainty/late evidence on edit, scope-family change, denied refresh and destruction', async () => {
    const { harness, component } = await screen(); await preview(component); component.editUrl(ORIGIN + '/new');
    expect(component.permission()).toBe(false); expect(component.selection()).toBeNull();
    let resolve!: (row: ApiResult) => void; api.previewPromise = new Promise(done => resolve = done);
    component.editUrl(ORIGIN + '/'); component.editPermission(true); const waiting = component.preview(); component.editOrigin(ORIGIN);
    resolve(await api.preview()); await waiting; expect(component.selection()).toBeNull();
    api.previewPromise = null; await preview(component); api.uncertain = true; await component.launch(); expect(component.pending()).not.toBeNull();
    await harness.navigateByUrl('/passive-redirects/7/10', PassiveHeaders); await harness.fixture.whenStable();
    expect(component.pending()).toBeNull(); expect(component.permission()).toBe(false);
    await harness.navigateByUrl('/passive-redirects/7/9', PassiveHeaders); await harness.fixture.whenStable();
    let resolveDetail!: (row: ApiResult) => void; api.detailPromise = new Promise(done => resolveDetail = done); const reading = component.inspect(21);
    await harness.navigateByUrl('/passive-resources/7/9', PassiveHeaders); resolveDetail(detail()); await reading; expect(component.evidence()).toBeNull();
    api.redirects = false; api.resources = true; api.detailPromise = null; api.deny = true; await component.load(); expect(component.ready()).toBe(false);
    harness.fixture.destroy(); expect(component.origins()).toEqual([]); expect(component.evidence()).toBeNull();
  });
  it('uses fixed same-origin no-store CSRF-capable routes/encoded own-key requests and denies unsafe IDs/query family authority', async () => {
    const project = vi.spyOn(api, 'projectOnboarding'); const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/passive-redirects/7/9007199254740992', PassiveHeaders); await harness.fixture.whenStable(); expect(project).not.toHaveBeenCalled();
    await harness.navigateByUrl('/passive-redirects/7/9?passiveObservation=tls', PassiveHeaders); await harness.fixture.whenStable();
    expect(api.families).toEqual(['redirects']); expect(api.commands).toEqual([]);
    const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) })); vi.stubGlobal('fetch', fetcher);
    TestBed.resetTestingModule(); const real = TestBed.inject(AccountApi);
    await real.passiveRedirects(7, 9, undefined, undefined, 'key&extra=x'); await real.passiveRedirects(7, 9, { url: ORIGIN + '/' }, undefined, undefined, true);
    await real.passiveRedirects(7, 9, undefined, 21); await real.passiveRedirects(7, 9, {}, 21);
    const calls = fetcher.mock.calls as unknown as [string, RequestInit][];
    expect(calls.map(([path]) => path)).toEqual(['/api/organizations/7/projects/9/passive-redirects/?idempotency_key=key%26extra%3Dx',
      '/_allauth/browser/v1/auth/session', '/api/organizations/7/projects/9/passive-redirects/selection/', '/api/organizations/7/projects/9/passive-redirects/21/',
      '/_allauth/browser/v1/auth/session', '/api/organizations/7/projects/9/passive-redirects/21/']);
    expect(calls.every(([, options]) => options.cache === 'no-store' && options.credentials === 'same-origin')).toBe(true);
    expect(calls[2][1].method).toBe('POST'); expect(calls[5][1].headers).toHaveProperty('X-CSRFToken'); vi.unstubAllGlobals();
  });
});

const resourceBinding = () => ({ ...binding(), method_version: 'passive-resource-source-v1', observations: ['static_resource_references'] });
function resourceEvidence() {
  return { job_id: 21, source_current: true, collection: { method: 'passive-resource-evidence-v1', url: ORIGIN + '/', status: 200,
    observed_at: DATE, interpretation: 'one_complete_response_literal_candidates_not_browser_requests_or_whole_page_mixed_content_security',
    evidence: { method_version: 'passive-resource-response-v1', observed_at: DATE, coverage: 'one_complete_length_framed_utf8_html_response_only',
      interpretation: 'literal_candidates_not_browser_requests_or_whole_page_mixed_content_security', resource_references: {
        method_version: 'passive-static-resource-references-v1', state: 'observed', reason: '', coverage: 'selected_literal_static_resource_attributes_only',
        selected_attributes: ['script/src', 'iframe/src', 'img/src', 'link[stylesheet|preload|modulepreload]/href'],
        excluded: 'navigation_css_srcset_javascript_dynamic_media_inert_rawtext_and_foreign_descendants',
        interpretation: 'literal_reference_candidates_not_browser_requests_mixed_content_policy_or_whole_page_security',
        counts: { inspected_attributes: 3, http_absolute: 1, https_absolute: 1, unclassified: 1 } as Record<string, number | null>,
      } } } };
}
function resourceCandidateReport() {
  const collection = resourceEvidence().collection; const refs = collection.evidence.resource_references;
  return { job_id: 21, source_current: true, method_version: 'passive-resource-candidates-v1', binding: resourceBinding(), collection,
    state: 'original_lexical_review_candidates', reason: '', coverage: 'selected_literal_static_resource_attributes_only',
    interpretation: 'dated_literal_http_reference_candidate_not_browser_requests_mixed_content_policy_severity_or_whole_page_security',
    candidates: [{ detector: 'literal_http_resource_reference_candidate', evidence: {
      counts: structuredClone(refs.counts), selected_attributes: [...refs.selected_attributes], excluded: refs.excluded } }] };
}

async function resourceFindingResult(saved = false, report = resourceCandidateReport()): Promise<ApiResult> {
  const findings = [];
  if (saved) for (const candidate of report.candidates) {
    const evidence = { source: 'passive_static_resource_references', job_id: report.job_id, binding: structuredClone(report.binding),
      collection_sha256: await sha(report.collection), observed_at: report.collection.observed_at, status: report.collection.status,
      fact: structuredClone(candidate.evidence), coverage: report.coverage, interpretation: report.interpretation };
    findings.push({ id: 100, source_passive_resource_id: report.job_id, detector: candidate.detector, method_version: 'passive-resource-finding-v1',
      subject: report.collection.url, fingerprint: await sha(['passive-resource-finding-v1', candidate.detector, evidence]), evidence,
      confidence: 'dated_literal_fact_not_risk_severity', detected_at: LATER });
  }
  return { status: 200, body: { organization_id: 7, project_id: 9, candidates: report, candidate_digest: await sha(report),
    finding_set: { method_version: 'passive-resource-finding-v1', project_id: 9, job_id: report.job_id, source_current: true,
      state: findings.length ? 'current_materialized_facts' : 'no_retained_materialized_findings', findings } } };
}

describe('Separate exact passive resource native consumers', () => {
  let api: FixtureApi;
  beforeEach(() => {
    api = new FixtureApi(); api.resources = true;
    TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] });
  });
  async function screen() {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/passive-resources/7/9', PassiveHeaders);
    await harness.fixture.whenStable(); harness.detectChanges(); return { harness, component };
  }
  async function preview(component: PassiveHeaders) { component.editUrl(ORIGIN + '/'); component.editPermission(true); await component.preview(); }
  function detail(item = resourceEvidence()) {
    return { status: 200, body: { organization_id: 7, project_id: 9, job: { ...job(), status: 'succeeded' }, evidence: item } };
  }
  async function candidateScreen() {
    const view = await screen(); api.rows = [{ ...job(), status: 'succeeded' }]; await view.component.load(); view.harness.detectChanges(); return view;
  }
  function candidateResult(report = resourceCandidateReport()): ApiResult {
    return { status: 200, body: { organization_id: 7, project_id: 9, candidates: report } };
  }
  it.each(['en', 'tr'] as const)('deliberately inspects original dated literal HTTP facts without automatic reads, site work, saves or priority in %s', async (language) => {
    api.savedProductLanguage = language;
    const { harness, component } = await candidateScreen(); const storage = vi.spyOn(Storage.prototype, 'setItem');
    expect(api.resourceCandidateCalls).toEqual([]); expect(component.candidateReport()).toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Özgün gerçek HTTP kaynak inceleme adayını inceleyin' : 'Inspect original literal HTTP resource review candidate');
    await component.inspectResourceCandidates(21); harness.detectChanges(); expect(api.resourceCandidateCalls).toEqual([21]);
    expect(component.candidateReport()).toEqual(resourceCandidateReport());
    for (const text of [DATE, 'HTTP 200', language === 'tr' ? '1 açık HTTP başvurusu; incelenen seçili öznitelik sayısı: 3' : '1 explicit HTTP references among 3 inspected selected attributes',
      language === 'tr' ? '1 açık HTTPS ve 1 sınıflandırılmamış' : '1 explicit HTTPS and 1 unclassified',
      language === 'tr' ? 'tarayıcı isteği' : 'not browser requests', language === 'tr' ? 'karma içerik politikası' : 'mixed-content policy',
      language === 'tr' ? 'Gezinme, CSS, srcset' : 'Navigation, CSS, srcset', language === 'tr' ? 'site isteği yok' : 'no site request']) expect(harness.routeNativeElement!.textContent).toContain(text);
    const originalCandidates = structuredClone(component.candidateReport());
    const captionNode = [...harness.routeNativeElement!.querySelectorAll('li > span')].find(row => row.textContent === component.candidateText(component.candidateRows()[0]))!;
    expect(captionNode.getAttribute('lang')).toBe(language);
    retainDraftLanguage(harness, component, api, language);
    expect(component.candidateReport()).toEqual(originalCandidates);
    expect(harness.routeNativeElement!.querySelector('pre[lang="en"]')?.textContent).toContain(JSON.stringify(component.candidateReport(), null, 2));
    expect(harness.routeNativeElement!.textContent).not.toContain('Explicitly save these original header facts');
    expect(harness.routeNativeElement!.querySelector('img, script, iframe')).toBeNull();
    expect(api.findingReads).toEqual([]); expect(api.findingCommands).toEqual([]); expect(api.commands).toEqual([]);
    expect(api.resourceFindingReads).toEqual([]); expect(api.resourceFindingCommands).toEqual([]);
    expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
    for (const row of [{ ...job() }, { ...job(), status: 'failed' }, { ...job(), status: 'succeeded', cancel_requested: true }]) {
      api.rows = [row]; await component.load(); await component.inspectResourceCandidates(21);
    }
    await component.inspectResourceCandidates(99); await component.inspectResourceCandidates(9007199254740992);
    expect(api.resourceCandidateCalls).toEqual([21]);
  });
  it('keeps observed empty and unclassified counts separate from all original lexical-unavailable/null reasons and denied reads', async () => {
    const { harness, component } = await candidateScreen();
    for (const unclassified of [0, 1000]) {
      const report = resourceCandidateReport(); report.collection.evidence.resource_references.counts = {
        inspected_attributes: unclassified, http_absolute: 0, https_absolute: 0, unclassified };
      report.candidates = []; api.resourceCandidateResult = candidateResult(report);
      await component.inspectResourceCandidates(21); harness.detectChanges(); expect(component.candidateReport()).not.toBeNull();
      expect(harness.routeNativeElement!.textContent).toContain('No eligible literal HTTP review candidate');
      expect(harness.routeNativeElement!.textContent).not.toContain('Original lexical evaluation unavailable');
    }
    for (const reason of ['invalid_body', 'ambiguous_markup', 'reference_limit']) {
      const report = resourceCandidateReport(); Object.assign(report.collection.evidence.resource_references, {
        state: 'unavailable', reason, counts: { inspected_attributes: null, http_absolute: null, https_absolute: null, unclassified: null } });
      report.state = 'original_lexical_evaluation_unavailable'; report.reason = reason; report.candidates = [];
      api.resourceCandidateResult = candidateResult(report); await component.inspectResourceCandidates(21); harness.detectChanges();
      expect(component.candidateReport()).not.toBeNull(); expect(harness.routeNativeElement!.textContent).toContain(`Original lexical evaluation unavailable · ${reason}`);
      expect(harness.routeNativeElement!.textContent).toContain('All counts remain null');
      expect(harness.routeNativeElement!.textContent).not.toContain('No eligible literal HTTP review candidate');
    }
    api.resourceCandidateResult = { status: 409, body: {} }; await component.inspectResourceCandidates(21); harness.detectChanges();
    expect(component.candidateReport()).toBeNull(); expect(component.ready()).toBe(false); expect(component.error()).toContain('Missing is not zero candidates');
  });
  it('rejects substituted scopes/families, raw or partial shapes, dates, counts and candidate/report disagreements', async () => {
    const { component } = await candidateScreen();
    const changes: ((report: Record<string, any>) => void)[] = [
      r => r['job_id'] = 99, r => r['source_current'] = 1, r => r['method_version'] = 'passive-header-candidates-v1',
      r => r['binding'].organization_id = 99, r => r['binding'].project_id = 99, r => r['binding'].actor_id = true,
      r => r['binding'].method_version = 'passive-header-source-v1', r => r['binding'].observations = ['response_headers'],
      r => r['binding'].collection_permission = 1, r => r['binding'].origin += ':443', r => r['binding'].url += 'other',
      r => r['binding'].source_digest = 'invalid', r => r['binding'].verified_at = LATER, r => r['binding'].raw_body_digest = 'private',
      r => r['collection'].status = 302, r => r['collection'].status = true, r => r['collection'].url += '?x=y',
      r => r['collection'].method = 'passive-header-collection-v1', r => r['collection'].raw_body = 'private',
      r => r['collection'].observed_at = '2026-02-30T00:00:00.000001+00:00', r => r['collection'].observed_at = '2026-01-01T00:00:00.000001Z',
      r => r['collection'].observed_at = '2026-01-01T00:00:00.000000+00:00', r => r['collection'].observed_at = '2026-01-01T00:00:00.000003+00:00',
      r => r['collection'].evidence.observed_at = LATER, r => r['collection'].evidence.coverage = 'whole_page',
      r => r['collection'].evidence.resource_references.counts.http_absolute = true,
      r => r['collection'].evidence.resource_references.counts.http_absolute = '1',
      r => r['collection'].evidence.resource_references.counts.http_absolute = 1.5,
      r => r['collection'].evidence.resource_references.counts.http_absolute = -1,
      r => r['collection'].evidence.resource_references.counts.http_absolute = 1001,
      r => r['collection'].evidence.resource_references.counts.inspected_attributes = 2,
      r => r['collection'].evidence.resource_references.selected_attributes = ['img/src'],
      r => r['collection'].evidence.resource_references.excluded = '', r => r['collection'].evidence.resource_references.resource_urls = ['private'],
      r => r['state'] = 'original_lexical_evaluation_unavailable', r => r['reason'] = 'reference_limit', r => r['coverage'] = 'whole_page',
      r => r['interpretation'] = 'secure', r => r['severity'] = 'critical', r => r['candidates'] = [],
      r => r['candidates'].push(r['candidates'][0]), r => r['candidates'][0].detector = 'invented',
      r => r['candidates'][0].evidence.counts.http_absolute = 2, r => r['candidates'][0].evidence.counts.unclassified = 0,
      r => r['candidates'][0].evidence.selected_attributes = ['img/src'], r => r['candidates'][0].evidence.excluded = '',
      r => r['candidates'][0].evidence.raw_url = 'private',
    ];
    for (const change of changes) {
      const report = resourceCandidateReport(); change(report); api.resourceCandidateResult = candidateResult(report);
      await component.inspectResourceCandidates(21); expect(component.candidateReport()).toBeNull();
    }
    for (const mutate of [(r: ApiResult) => r.body['project_id'] = 99, (r: ApiResult) => r.body['raw'] = 'private',
      (r: ApiResult) => r.body['candidates'] = null]) {
      const row = candidateResult(); mutate(row); api.resourceCandidateResult = row; await component.inspectResourceCandidates(21); expect(component.candidateReport()).toBeNull();
    }
    const unavailable = resourceCandidateReport(); Object.assign(unavailable.collection.evidence.resource_references, {
      state: 'unavailable', reason: 'ambiguous_markup', counts: { inspected_attributes: null, http_absolute: 0, https_absolute: null, unclassified: null } });
    Object.assign(unavailable, { state: 'original_lexical_evaluation_unavailable', reason: 'ambiguous_markup', candidates: [] });
    api.resourceCandidateResult = candidateResult(unavailable); await component.inspectResourceCandidates(21); expect(component.candidateReport()).toBeNull();
    expect(api.commands).toEqual([]);
  });
  it('owns fresh candidate facts and clears on every edit, inspection, preview, ownership operation and role/scope refresh', async () => {
    const { component } = await candidateScreen(); const report = resourceCandidateReport(); api.resourceCandidateResult = candidateResult(report);
    await component.inspectResourceCandidates(21); report.candidates[0].evidence.counts['http_absolute'] = 99;
    expect(component.candidateRows()[0].evidence['counts']).toHaveProperty('http_absolute', 1); api.resourceCandidateResult = null;
    for (const action of [() => component.editUrl(ORIGIN + '/'), () => component.editOrigin(ORIGIN), () => component.editPermission(false),
      () => component.inspect(21), () => component.preview(), () => component.createChallenge()]) {
      component.editOrigin(ORIGIN); await component.inspectResourceCandidates(21); expect(component.candidateReport()).not.toBeNull();
      await action(); expect(component.candidateReport()).toBeNull(); api.verifications = [verification()];
    }
    await component.inspectResourceCandidates(21); api.role = 'member'; await component.load(); expect(component.candidateReport()).toBeNull(); expect(component.ready()).toBe(false);
  });
  it('withholds late valid resource replies after fresh role, configured origin or original verification loss', async () => {
    const { component } = await candidateScreen(); const read = api.passiveResourceCandidates.bind(api);
    for (const change of [() => api.role = 'member', () => api.verifications = [], () => api.verifications[0]['verified_at'] = LATER]) {
      api.role = 'owner'; api.verifications = [verification()]; await component.load();
      vi.spyOn(api, 'passiveResourceCandidates').mockImplementation(async (...args) => { const result = await read(...args); change(); return result; });
      await component.inspectResourceCandidates(21); expect(component.candidateReport()).toBeNull(); expect(component.ready()).toBe(false); vi.restoreAllMocks();
    }
    api.verifications = [verification()]; await component.load();
    const project = api.projectOnboarding.bind(api);
    vi.spyOn(api, 'passiveResourceCandidates').mockImplementation(async (...args) => {
      const result = await read(...args); vi.spyOn(api, 'projectOnboarding').mockImplementation(async (...ids) => {
        const row = await project(...ids); row.body.project.canonical_origin = 'https://other.example.invalid'; return row;
      }); return result;
    });
    await component.inspectResourceCandidates(21); expect(component.candidateReport()).toBeNull(); expect(component.ready()).toBe(false);
  });
  it('discards late success/denial on edits, route scope/family changes and destruction without reviving facts', async () => {
    const view = await candidateScreen(); const harness = view.harness; let component = view.component; let resolve!: (result: ApiResult) => void;
    api.resourceCandidatePromise = new Promise(done => resolve = done); const editing = component.inspectResourceCandidates(21);
    component.editUrl(ORIGIN + '/edited'); resolve(candidateResult()); await editing; expect(component.candidateReport()).toBeNull();
    api.resourceCandidatePromise = new Promise(done => resolve = done); const scope = component.inspectResourceCandidates(21);
    await harness.navigateByUrl('/passive-resources/7/10', PassiveHeaders); await harness.fixture.whenStable();
    const currentError = component.error(); resolve({ status: 403, body: {} }); await scope;
    expect(component.candidateReport()).toBeNull(); expect(component.error()).toBe(currentError);
    api.resourceCandidatePromise = null; component = await harness.navigateByUrl('/passive-resources/7/9', PassiveHeaders); await harness.fixture.whenStable();
    api.resourceCandidatePromise = new Promise(done => resolve = done); const family = component.inspectResourceCandidates(21);
    await harness.navigateByUrl('/passive-tls/7/9', PassiveHeaders); resolve(candidateResult()); await family; expect(component.candidateReport()).toBeNull();
    api.resourceCandidatePromise = null; component = await harness.navigateByUrl('/passive-resources/7/9', PassiveHeaders); await harness.fixture.whenStable(); await component.load();
    await component.inspectResourceCandidates(21); expect(component.candidateReport()).not.toBeNull();
    api.resourceCandidatePromise = new Promise(done => resolve = done); const destroying = component.inspectResourceCandidates(21);
    harness.fixture.destroy(); resolve(candidateResult()); await destroying; expect(component.candidateReport()).toBeNull(); expect(component.ready()).toBe(false);
  });
  it('keeps resource candidate authority server-fixed and uses only the same-origin no-store bodyless GET', async () => {
    const harness = await RouterTestingHarness.create(); api.rows = [{ ...job(), status: 'succeeded' }];
    for (const family of ['headers', 'tls', 'redirects']) {
      const component = await harness.navigateByUrl(`/passive-${family}/7/9?passiveObservation=resources`, PassiveHeaders);
      await harness.fixture.whenStable(); harness.detectChanges(); await component.inspectResourceCandidates(21);
      expect(component.candidateReport()).toBeNull(); expect(harness.routeNativeElement!.textContent).not.toContain('Inspect original literal HTTP resource review candidate');
    }
    expect(api.resourceCandidateCalls).toEqual([]);
    const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) })); vi.stubGlobal('fetch', fetcher);
    TestBed.resetTestingModule(); await TestBed.inject(AccountApi).passiveResourceCandidates(7, 9, 21);
    expect(fetcher.mock.calls).toEqual([['/api/organizations/7/projects/9/passive-resources/21/candidates/', {
      method: 'GET', headers: {}, body: undefined, credentials: 'same-origin', cache: 'no-store' }]]); vi.unstubAllGlobals();
  });
  it('independently reads current resource facts and explicitly saves only the freshly unchanged original SHA without site work or storage', async () => {
    const { harness, component } = await candidateScreen(); const storage = vi.spyOn(Storage.prototype, 'setItem');
    expect(api.resourceFindingReads).toEqual([]); expect(api.resourceFindingCommands).toEqual([]);
    expect(harness.routeNativeElement!.textContent).toContain('Inspect current original resource findings (no save)');
    await component.inspectFindings(21); harness.detectChanges();
    expect(component.findingInspection()?.findingSet['state']).toBe('no_retained_materialized_findings');
    expect(harness.routeNativeElement!.textContent).toContain('does not mean zero eligible candidates');
    const original = structuredClone(component.candidateReport()); await component.saveFindings(); harness.detectChanges();
    expect(api.resourceFindingCommands).toEqual([[21, await sha(original)]]); expect(component.findingPending()).toBeNull();
    expect(component.findingInspection()?.findingSet['state']).toBe('current_materialized_facts');
    for (const text of ['no personal attribution', 'Detection time', DATE, LATER, 'dated_literal_fact_not_risk_severity', 'not browser requests']) {
      expect(harness.routeNativeElement!.textContent).toContain(text);
    }
    expect(api.findingReads).toEqual([]); expect(api.findingCommands).toEqual([]); expect(api.commands).toEqual([]);
    expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
    const result = await resourceFindingResult(true); api.resourceFindingResult = result; await component.inspectFindings(21);
    (result.body['finding_set'] as any).findings[0].evidence.fact.counts.http_absolute = 99;
    expect((component.findingInspection()?.findingSet['findings'] as any)[0].evidence.fact.counts.http_absolute).toBe(1);
  });
  it('preserves lexical-null, observed-empty, unclassified-only, absent sets and unavailable reads without sending an empty save', async () => {
    const { harness, component } = await candidateScreen();
    for (const unclassified of [0, 1000]) {
      const report = resourceCandidateReport(); report.collection.evidence.resource_references.counts = {
        inspected_attributes: unclassified, http_absolute: 0, https_absolute: 0, unclassified }; report.candidates = [];
      api.resourceFindingResult = await resourceFindingResult(false, report); await component.inspectFindings(21); await component.saveFindings(); harness.detectChanges();
      expect(component.findingInspection()).not.toBeNull(); expect(harness.routeNativeElement!.textContent).toContain('No eligible literal HTTP review candidate');
      expect(harness.routeNativeElement!.textContent).toContain('No retained materialized findings');
    }
    for (const reason of ['invalid_body', 'ambiguous_markup', 'reference_limit']) {
      const report = resourceCandidateReport(); Object.assign(report.collection.evidence.resource_references, {
        state: 'unavailable', reason, counts: { inspected_attributes: null, http_absolute: null, https_absolute: null, unclassified: null } });
      report.state = 'original_lexical_evaluation_unavailable'; report.reason = reason; report.candidates = [];
      api.resourceFindingResult = await resourceFindingResult(false, report); await component.inspectFindings(21); await component.saveFindings(); harness.detectChanges();
      expect(component.findingInspection()).not.toBeNull(); expect(harness.routeNativeElement!.textContent).toContain(`Original lexical evaluation unavailable · ${reason}`);
      expect(harness.routeNativeElement!.textContent).not.toContain('No eligible literal HTTP review candidate');
    }
    expect(api.resourceFindingCommands).toEqual([]); api.resourceFindingResult = { status: 409, body: {} }; await component.inspectFindings(21);
    expect(component.findingInspection()).toBeNull(); expect(component.candidateReport()).toBeNull(); expect(component.ready()).toBe(false);
  });
  it('rejects original SHA/report and full compact source-family-fingerprint-date-count identity tampering', async () => {
    const { component } = await candidateScreen();
    const mutations: ((body: Record<string, any>) => void)[] = [
      b => b['candidate_digest'] = 'a'.repeat(64), b => b['project_id'] = 99, b => b['raw_html'] = 'private',
      b => b['candidates'].state = 'original_lexical_evaluation_unavailable', b => b['candidates'].reason = 'reference_limit',
      b => b['candidates'].binding.observations = ['response_headers'], b => b['candidates'].source_current = 1,
      b => b['candidates'].collection.observed_at = '2026-01-01T00:00:00.000001Z', b => b['candidates'].collection.status = true,
      b => b['candidates'].candidates[0].evidence.counts.http_absolute = 2,
      b => b['finding_set'].job_id = 99, b => b['finding_set'].project_id = 99, b => b['finding_set'].source_current = 1,
      b => b['finding_set'].method_version = 'passive-header-finding-v1', b => b['finding_set'].state = 'secure',
      b => b['finding_set'].findings.push(structuredClone(b['finding_set'].findings[0])),
      b => b['finding_set'].findings[0].id = true, b => b['finding_set'].findings[0].source_passive_resource_id = 99,
      b => b['finding_set'].findings[0].source_passive_header_id = 21, b => b['finding_set'].findings[0].method_version = 'passive-header-finding-v1',
      b => b['finding_set'].findings[0].detector = 'invented', b => b['finding_set'].findings[0].subject += 'other',
      b => b['finding_set'].findings[0].confidence = 'dated_response_fact_not_risk_severity', b => b['finding_set'].findings[0].fingerprint = 'a'.repeat(64),
      b => b['finding_set'].findings[0].detected_at = '2026-02-30T00:00:00Z', b => b['finding_set'].findings[0].detected_at = '2025-01-01T00:00:00Z',
      b => b['finding_set'].findings[0].evidence.source = 'passive_response_headers', b => b['finding_set'].findings[0].evidence.collection_sha256 = 'a'.repeat(64),
      b => b['finding_set'].findings[0].evidence.binding.actor_id = 99, b => b['finding_set'].findings[0].evidence.observed_at = LATER,
      b => b['finding_set'].findings[0].evidence.status = true, b => b['finding_set'].findings[0].evidence.fact.counts.http_absolute = 2,
      b => b['finding_set'].findings[0].evidence.fact.selected_attributes = ['img/src'], b => b['finding_set'].findings[0].evidence.fact.excluded = '',
      b => b['finding_set'].findings[0].evidence.raw_url = 'private', b => b['finding_set'].findings[0].actor_id = 1,
    ];
    for (const mutate of mutations) {
      const result = await resourceFindingResult(true); mutate(result.body); api.resourceFindingResult = result;
      await component.inspectFindings(21); expect(component.findingInspection()).toBeNull(); expect(component.candidateReport()).toBeNull();
    }
    api.resourceFindingResult = await headerFindingResult(true); await component.inspectFindings(21); expect(component.findingInspection()).toBeNull();
    expect(api.resourceFindingCommands).toEqual([]);
  });
  it('requires unchanged original facts and fresh role/configuration/verification both before POST and after late success', async () => {
    const { component } = await candidateScreen(); const originalRead = api.passiveResourceFindings.bind(api);
    for (const change of [() => api.role = 'member', () => api.verifications = [], () => api.verifications[0]['verified_at'] = LATER]) {
      api.role = 'owner'; api.verifications = [verification()]; await component.load(); await component.inspectResourceCandidates(21);
      vi.spyOn(api, 'passiveResourceFindings').mockImplementation(async (...args) => { const result = await originalRead(...args); change(); return result; });
      await component.saveFindings(); expect(api.resourceFindingCommands).toEqual([]); expect(component.findingPending()).toBeNull(); expect(component.ready()).toBe(false);
      vi.restoreAllMocks();
    }
    api.role = 'owner'; api.verifications = [verification()]; await component.load(); await component.inspectResourceCandidates(21);
    const changed = resourceCandidateReport(); changed.binding.actor_id = 2; api.resourceFindingResult = await resourceFindingResult(false, changed);
    await component.saveFindings(); expect(api.resourceFindingCommands).toEqual([]); expect(component.error()).toContain('No fact-save command sent');
    api.resourceFindingResult = null; await component.inspectResourceCandidates(21);
    vi.spyOn(api, 'passiveResourceFindings').mockImplementation(async (...args) => { const result = await originalRead(...args); if (args[3]) api.role = 'member'; return result; });
    await component.saveFindings(); expect(api.resourceFindingCommands).toHaveLength(1); expect(api.findingsSaved).toBe(true);
    expect(component.findingInspection()).toBeNull(); expect(component.findingPending()).toBeNull(); expect(component.candidateReport()).toBeNull();
    expect(component.ready()).toBe(false); expect(component.error()).toContain('stored facts may still exist'); vi.restoreAllMocks();
  });
  it('freezes only the original job/report/SHA/set in memory and reconciles without replay or caller attribution', async () => {
    const { harness, component } = await candidateScreen(); await component.inspectResourceCandidates(21);
    api.findingUncertain = true; await component.saveFindings(); const frozen = structuredClone(component.findingPending());
    expect(frozen?.candidateDigest).toBe(await sha(resourceCandidateReport())); expect(frozen?.job.id).toBe(21);
    expect(component.candidateReport()).toBeNull(); harness.detectChanges(); expect(harness.routeNativeElement!.textContent).toContain('literal resource-fact save outcome is uncertain');
    await component.saveFindings(); await component.inspectFindings(21); expect(api.resourceFindingCommands).toHaveLength(1);
    await component.reconcileFindings(); expect(component.findingPending()).toBeNull(); expect(api.resourceFindingReads).toEqual([21, 21]);
    expect(api.resourceFindingCommands).toHaveLength(1); harness.detectChanges(); expect(harness.routeNativeElement!.textContent).toContain('does not identify who saved it');
    await component.saveFindings(); const retained = structuredClone(component.findingPending());
    const changedSet = await resourceFindingResult(true); (changedSet.body['finding_set'] as any).findings[0].id = 101;
    api.resourceFindingResult = changedSet; await component.reconcileFindings(); expect(retained?.findingSet['state']).toBe('current_materialized_facts');
    expect(component.findingPending()).toBeNull(); expect(component.findingInspection()).toBeNull(); expect(component.error()).toContain('changed or became unavailable');
  });
  it('keeps absent-set and network uncertainty distinct from a confirmed no-op, clears changed original reports and permits only deliberate discard', async () => {
    const { component } = await candidateScreen(); await component.inspectResourceCandidates(21); api.findingDrop = true;
    await component.saveFindings(); const frozen = structuredClone(component.findingPending()); await component.reconcileFindings();
    expect(component.findingPending()).toEqual(frozen); expect(component.message()).toContain('not confirmed no-op');
    api.resourceFindingPromise = Promise.reject(new Error('lookup unavailable')); await component.reconcileFindings();
    expect(component.findingPending()).toEqual(frozen); expect(component.findingInspection()).toBeNull(); expect(api.resourceFindingCommands).toHaveLength(1);
    api.resourceFindingPromise = null; const changed = resourceCandidateReport(); changed.binding.actor_id = 2;
    api.resourceFindingResult = await resourceFindingResult(false, changed); await component.reconcileFindings();
    expect(component.findingPending()).toBeNull(); expect(component.findingInspection()).toBeNull();
    api.resourceFindingResult = null; await component.inspectResourceCandidates(21); await component.saveFindings(); component.discardFindingCommand();
    expect(component.findingPending()).toBeNull(); expect(component.message()).toContain('Stored facts may still exist'); expect(api.resourceFindingCommands).toHaveLength(2);
  });
  it('clears facts and uncertain commands across edits, operations, ownership, scope-family changes, destruction and late success/denial', async () => {
    const view = await candidateScreen(); const harness = view.harness; let component = view.component;
    for (const action of [() => component.editUrl(ORIGIN + '/'), () => component.editOrigin(ORIGIN), () => component.editPermission(false),
      () => component.inspect(21), () => component.inspectResourceCandidates(21), () => component.preview(), () => component.load(), () => component.revoke(component.verifications()[0])]) {
      api.verifications = [verification()]; await component.load(); await component.inspectResourceCandidates(21); api.findingUncertain = true;
      await component.saveFindings(); expect(component.findingPending()).not.toBeNull(); await action();
      expect(component.findingPending()).toBeNull(); expect(component.findingInspection()).toBeNull();
    }
    api.verifications = [verification()]; await component.load(); let resolve!: (result: ApiResult) => void;
    api.resourceFindingPromise = new Promise(done => resolve = done); const editing = component.inspectFindings(21);
    component.editPermission(false); resolve(await resourceFindingResult(true)); await editing; expect(component.findingInspection()).toBeNull(); api.resourceFindingPromise = null;
    await component.inspectResourceCandidates(21); api.findingUncertain = false;
    api.resourceFindingPostPromise = new Promise(done => resolve = done); const sent = api.resourceFindingCommands.length; const saving = component.saveFindings();
    for (let i = 0; i < 100 && api.resourceFindingCommands.length === sent; i++) await new Promise(done => setTimeout(done, 0));
    expect(api.resourceFindingCommands.length).toBe(sent + 1); expect(component.findingPending()).not.toBeNull();
    await harness.navigateByUrl('/passive-resources/7/10', PassiveHeaders); await harness.fixture.whenStable(); const error = component.error();
    resolve({ status: 403, body: {} }); await saving; expect(component.error()).toBe(error); expect(component.findingPending()).toBeNull();
    api.resourceFindingPostPromise = null; component = await harness.navigateByUrl('/passive-resources/7/9', PassiveHeaders); await harness.fixture.whenStable();
    api.resourceFindingPromise = new Promise(done => resolve = done); const family = component.inspectFindings(21);
    await harness.navigateByUrl('/passive-tls/7/9', PassiveHeaders); resolve(await resourceFindingResult(true)); await family; expect(component.findingInspection()).toBeNull();
    api.resourceFindingPromise = null; component = await harness.navigateByUrl('/passive-resources/7/9', PassiveHeaders); await harness.fixture.whenStable();
    api.resourceFindingPromise = new Promise(done => resolve = done); const destroying = component.inspectFindings(21);
    harness.fixture.destroy(); resolve(await resourceFindingResult(true)); await destroying; expect(component.findingInspection()).toBeNull(); expect(component.findingPending()).toBeNull();
  });
  it('uses family-correct fixed GET/SHA-only CSRF POST and never grants TLS/Location Finding authority through query or injected reports', async () => {
    const harness = await RouterTestingHarness.create(); api.rows = [{ ...job(), status: 'succeeded' }];
    for (const family of ['tls', 'redirects']) {
      const component = await harness.navigateByUrl(`/passive-${family}/7/9?passiveObservation=resources`, PassiveHeaders); await harness.fixture.whenStable();
      component.candidateReport.set(resourceCandidateReport()); await component.inspectFindings(21); await component.saveFindings(); await component.reconcileFindings(); harness.detectChanges();
      expect(harness.routeNativeElement!.textContent).not.toContain('Inspect current original resource findings');
    }
    expect(api.resourceFindingReads).toEqual([]); expect(api.resourceFindingCommands).toEqual([]); expect(api.findingReads).toEqual([]); expect(api.findingCommands).toEqual([]);
    const component = await harness.navigateByUrl('/passive-resources/7/9', PassiveHeaders); await harness.fixture.whenStable();
    component.candidateReport.set(headerCandidateReport()); await component.saveFindings(); expect(api.resourceFindingReads).toEqual([]);
    const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) })); vi.stubGlobal('fetch', fetcher);
    TestBed.resetTestingModule(); const real = TestBed.inject(AccountApi); await real.passiveResourceFindings(7, 9, 21); await real.passiveResourceFindings(7, 9, 21, 'a'.repeat(64));
    const calls = fetcher.mock.calls as unknown as [string, RequestInit][];
    expect(calls.map(([path]) => path)).toEqual(['/api/organizations/7/projects/9/passive-resources/21/findings/', '/_allauth/browser/v1/auth/session', '/api/organizations/7/projects/9/passive-resources/21/findings/']);
    expect(calls[0][1].method).toBe('GET'); expect(calls[0][1].body).toBeUndefined(); expect(calls[2][1].method).toBe('POST');
    expect(calls[2][1].body).toBe(JSON.stringify({ candidate_digest: 'a'.repeat(64) })); expect(calls[2][1].headers).toHaveProperty('X-CSRFToken');
    expect(calls.every(([, options]) => options.cache === 'no-store' && options.credentials === 'same-origin')).toBe(true); vi.unstubAllGlobals();
  });
  it.each(['en', 'tr'] as const)('reuses actual ownership but requires independently unchecked transient-body consent and fixed resource-only commands in %s', async (language) => {
    api.savedProductLanguage = language;
    const { harness, component } = await screen(); const storage = vi.spyOn(Storage.prototype, 'setItem');
    expect(component.permission()).toBe(false); component.editUrl(ORIGIN + '/'); await component.preview(); expect(api.previews).toBe(0);
    component.editOrigin(ORIGIN); await component.createChallenge(); expect(component.challenge()?.content).toBe('a'.repeat(43));
    await component.verify(component.verifications()[0]); expect(component.challenge()).toBeNull(); expect(component.message()).toContain('not proof');
    await component.revoke(component.verifications()[0]); expect(api.ownership.map(row => row[0])).toEqual(['POST', 'POST', 'DELETE']);
    for (const url of [ORIGIN + '/?q=x', ORIGIN + '/#x', ORIGIN + ':444/', 'https://foreign.example.invalid/', 'javascript:evil()']) {
      component.editUrl(url); component.editPermission(true); await component.preview(); expect(component.selection()).toBeNull();
    }
    await preview(component); retainDraftLanguage(harness, component, api, language); api.changed = true; await component.launch(); expect(api.commands).toEqual([]);
    api.changed = false; await preview(component); const frozen = structuredClone(component.selection()); await component.launch();
    expect(api.commands[0]['observations']).toEqual(['static_resource_references']); expect(api.commands[0]['url']).toBe(ORIGIN + '/');
    expect(api.commands[0]['selection_digest']).toBe(frozen!.selection_digest); expect(api.commands[0]).not.toHaveProperty('origin');
    expect(api.families.every(value => value === 'resources')).toBe(true); expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
    harness.detectChanges(); expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Başlık veya TLS izni bu ayrı geçici gövde gözlemine izin vermez' : 'Header or TLS permission does not authorize');
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'geçici yorumlamak' : 'transiently interpret');
  });
  it('freezes original resource command through fresh own-key lookup and only deliberately retries unchanged unsaved commands', async () => {
    const { component } = await screen(); await preview(component); api.uncertain = true; await component.launch();
    const frozen = structuredClone(component.pending()); await component.reconcile();
    expect(component.pending()).toBeNull(); expect(api.lookups).toEqual([frozen!.key]); expect(api.commands.length).toBe(1);
    api.uncertain = false; api.rows = []; await component.load(); await preview(component); api.drop = true; await component.launch();
    const unsaved = structuredClone(component.pending()); await component.reconcile(); api.changed = true; await component.retry();
    expect(api.commands.length).toBe(2); expect(component.pending()).toEqual(unsaved);
    api.changed = false; await component.reconcile(); api.drop = false; await component.retry(); expect(api.commands[2]).toEqual(api.commands[1]);
    await component.load(); api.uncertain = true; await component.cancel(21); expect(component.pending()?.jobId).toBe(21);
    await component.reconcile(); expect(component.pending()).toBeNull(); expect(component.selected()?.cancel_requested).toBe(true);
    expect(api.commands).toHaveLength(4); expect(api.commands[3]).toEqual({});
  });
  it('preserves original microseconds, bounded counts and all lexical null reasons with explicit limited coverage', async () => {
    const { harness, component } = await screen(); api.detail = detail(); await component.inspect(21); expect(component.evidence()).not.toBeNull();
    for (const count of [0, 1000]) {
      const row = detail(); Object.assign(row.body.evidence.collection.evidence.resource_references.counts,
        { inspected_attributes: count, http_absolute: count, https_absolute: 0, unclassified: 0 });
      api.detail = row; await component.inspect(21); expect(component.evidence()).not.toBeNull();
    }
    for (const reason of ['invalid_body', 'ambiguous_markup', 'reference_limit']) {
      const item = resourceEvidence(); Object.assign(item.collection.evidence.resource_references,
        { state: 'unavailable', reason, counts: { inspected_attributes: null, http_absolute: null, https_absolute: null, unclassified: null } });
      api.detail = detail(item); await component.inspect(21); expect(component.evidence()).not.toBeNull();
    }
    harness.detectChanges(); const text = harness.routeNativeElement!.textContent;
    for (const fragment of [DATE, 'reference_limit', 'null is not zero', 'not browser requests', 'whole-page mixed-content proof', 'srcset']) expect(text).toContain(fragment);
    expect(harness.routeNativeElement!.querySelector('img, script, iframe')).toBeNull(); expect(api.commands).toEqual([]);
    api.detail = { status: 200, body: { ...detail().body, evidence: null } }; await component.inspect(21); expect(component.evidence()).toBeNull();
  });
  it('withholds family substitutions, raw fields, invalid original dates and altered transport or lexical shapes', async () => {
    const { component } = await screen(); const bad: ApiResult[] = [{ status: 403, body: {} }];
    for (const changes of [{ project_id: 99 }, { raw_html: 'private' }]) { const row = detail(); Object.assign(row.body, changes); bad.push(row); }
    for (const changes of [{ id: 99 }, { cancel_requested: true }, { status: 'failed' }, { error_category: '<img onerror=x>' }]) {
      const row = detail(); Object.assign(row.body.job, changes); bad.push(row);
    }
    for (const changes of [{ method: 'passive-resource-collection-v1' }, { url: 'https://foreign.example.invalid/' }, { url: ORIGIN + '/?x=y' },
      { status: 302 }, { observed_at: '2026-01-01T00:00:00.000001Z' }, { observed_at: '2026-02-30T00:00:00.000001+00:00' },
      { observed_at: '2026-01-01T00:00:00.000003+00:00' }, { observed_at: '2026-01-01T00:00:00.000000+00:00' },
      { raw_body: '<img onerror=x>' }, { resource_urls: ['private'] }, { interpretation: 'secure' }]) {
      const row = detail(); Object.assign(row.body.evidence.collection, changes); bad.push(row);
    }
    for (const changes of [{ method_version: 'passive-response-headers-v1' }, { observed_at: LATER }, { coverage: 'whole_page' }, { headers: {} }]) {
      const row = detail(); Object.assign(row.body.evidence.collection.evidence, changes); bad.push(row);
    }
    for (const changes of [{ selected_attributes: ['img/src'] }, { excluded: '' }, { interpretation: 'secure' }, { urls: ['private'] },
      { state: 'unavailable' }, { reason: 'reference_limit' }, { method_version: 'passive-response-headers-v1' }]) {
      const row = detail(); Object.assign(row.body.evidence.collection.evidence.resource_references, changes); bad.push(row);
    }
    for (const row of bad) { api.detail = row; await component.inspect(21); expect(component.selected()).toBeNull(); expect(component.evidence()).toBeNull(); }
  });
  it('rejects noninteger, boolean, string, overflow, inconsistent and partial unavailable counts instead of coercing them', async () => {
    const { component } = await screen();
    for (const change of [{ inspected_attributes: 2 }, { http_absolute: true }, { http_absolute: '1' }, { http_absolute: 1.5 },
      { http_absolute: -1 }, { http_absolute: 1001 }, { http_absolute: null }, { raw: 1 }]) {
      const row = detail(); Object.assign(row.body.evidence.collection.evidence.resource_references.counts, change);
      api.detail = row; await component.inspect(21); expect(component.evidence()).toBeNull();
    }
    for (const reason of ['body_incomplete', 'body_unavailable', '', 'network_error']) {
      const row = detail(); Object.assign(row.body.evidence.collection.evidence.resource_references,
        { state: 'unavailable', reason, counts: { inspected_attributes: null, http_absolute: null, https_absolute: null, unclassified: null } });
      api.detail = row; await component.inspect(21); expect(component.evidence()).toBeNull();
    }
    const partial = detail(); Object.assign(partial.body.evidence.collection.evidence.resource_references,
      { state: 'unavailable', reason: 'ambiguous_markup', counts: { inspected_attributes: null, http_absolute: 1, https_absolute: null, unclassified: null } });
    api.detail = partial; await component.inspect(21); expect(component.evidence()).toBeNull();
  });
  it('rejects mixed bindings and full-selection digest mismatches before granting resource command authority', async () => {
    const { component } = await screen();
    for (const changes of [{ method_version: 'passive-header-source-v1' }, { method_version: 'passive-tls-source-v1' },
      { observations: ['response_headers'] }, { observations: ['static_resource_references', 'response_headers'] },
      { collection_permission: 1 }, { url: ORIGIN + '/other' }, { origin: ORIGIN + ':443' }, { raw_body_digest: 'a'.repeat(64) }]) {
      api.previewResult = await api.preview(); const selection = api.previewResult.body['selection'] as Record<string, unknown>;
      Object.assign(selection['binding'] as object, changes); api.previewResult.body['selection_digest'] = await sha(selection);
      await preview(component); expect(component.selection()).toBeNull();
    }
    api.previewResult = await api.preview(); api.previewResult.body['selection_digest'] = 'a'.repeat(64); await preview(component);
    expect(component.selection()).toBeNull(); expect(api.commands).toEqual([]);
  });
  it('clears resource consent, frozen uncertainty and evidence on edits, family/scope changes, denial and destruction; discards late work', async () => {
    const { harness, component } = await screen(); await preview(component); component.editUrl(ORIGIN + '/new');
    expect(component.permission()).toBe(false); expect(component.selection()).toBeNull();
    let resolve!: (row: ApiResult) => void; api.previewPromise = new Promise(done => resolve = done);
    component.editUrl(ORIGIN + '/'); component.editPermission(true); const waiting = component.preview(); component.editOrigin(ORIGIN);
    resolve(await api.preview()); await waiting; expect(component.selection()).toBeNull();
    api.previewPromise = null; await preview(component); api.uncertain = true; await component.launch(); expect(component.pending()).not.toBeNull();
    await harness.navigateByUrl('/passive-resources/7/10', PassiveHeaders); await harness.fixture.whenStable();
    expect(component.pending()).toBeNull(); expect(component.permission()).toBe(false);
    await harness.navigateByUrl('/passive-resources/7/9', PassiveHeaders); await harness.fixture.whenStable();
    let resolveDetail!: (row: ApiResult) => void; api.detailPromise = new Promise(done => resolveDetail = done); const reading = component.inspect(21);
    await harness.navigateByUrl('/passive-tls/7/9', PassiveHeaders); resolveDetail(detail()); await reading;
    expect(component.evidence()).toBeNull(); expect(component.ready()).toBe(false);
    api.resources = false; api.tls = true; api.detailPromise = null; api.deny = true; await component.load(); expect(component.ready()).toBe(false);
    harness.fixture.destroy(); expect(component.origins()).toEqual([]); expect(component.evidence()).toBeNull();
  });
  it('uses fixed resource routes and CSRF/no-store encoded requests; unsafe IDs and query family fields grant no authority', async () => {
    const project = vi.spyOn(api, 'projectOnboarding'); const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/passive-resources/7/9007199254740992', PassiveHeaders); await harness.fixture.whenStable(); expect(project).not.toHaveBeenCalled();
    await harness.navigateByUrl('/passive-resources/7/9?passiveObservation=tls', PassiveHeaders); await harness.fixture.whenStable();
    expect(api.families).toEqual(['resources']); expect(api.commands).toEqual([]);
    const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) })); vi.stubGlobal('fetch', fetcher);
    TestBed.resetTestingModule(); const real = TestBed.inject(AccountApi);
    await real.passiveResources(7, 9, undefined, undefined, 'key&extra=x'); await real.passiveResources(7, 9, { url: ORIGIN + '/' }, undefined, undefined, true);
    await real.passiveResources(7, 9, undefined, 21); await real.passiveResources(7, 9, {}, 21);
    const calls = fetcher.mock.calls as unknown as [string, RequestInit][];
    expect(calls.map(([path]) => path)).toEqual(['/api/organizations/7/projects/9/passive-resources/?idempotency_key=key%26extra%3Dx',
      '/_allauth/browser/v1/auth/session', '/api/organizations/7/projects/9/passive-resources/selection/', '/api/organizations/7/projects/9/passive-resources/21/',
      '/_allauth/browser/v1/auth/session', '/api/organizations/7/projects/9/passive-resources/21/']);
    expect(calls.every(([, options]) => options.cache === 'no-store' && options.credentials === 'same-origin')).toBe(true);
    expect(calls[2][1].method).toBe('POST'); expect(calls[5][1].headers).toHaveProperty('X-CSRFToken'); vi.unstubAllGlobals();
  });
});
