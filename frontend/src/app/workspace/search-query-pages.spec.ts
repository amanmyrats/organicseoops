import { Title } from '@angular/platform-browser';
import { createHash } from 'node:crypto';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { AccountApi, ApiResult } from '../account/account-api';
import { SearchQueryPages } from './search-query-pages';
import { environment } from '../../environments/environment';

const ORIGIN = 'https://paired.example.invalid';
const QUERY = 'Özgün <img src=x onerror=evil()> query';
const ago = (minutes: number) => new Date(Date.now() - minutes * 60000).toISOString();
const reportDay = new Date(Date.now() - 5 * 86400000).toISOString().slice(0, 10);
function sorted(value: unknown): unknown {
  return Array.isArray(value) ? value.map(sorted) : value && typeof value === 'object'
    ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, row]) => [key, sorted(row)])) : value;
}
function fixture() {
  const result = { method: 'gsc-query-page-parse-v1', property: ORIGIN, day: reportDay, dimensions: ['query', 'page'],
    search_type: 'web', timezone: 'America/Los_Angeles', requested_aggregation: 'auto', response_aggregation: 'byPage',
    source_coverage: 'bounded_query_page_top_rows_only', provider_completeness: 'not_established', hidden_queries: 'unknown',
    start_row: 0, rows_returned: 2, omitted_pages: 0, truncated: false, next_start_row: null,
    observations: [1, 2].map((index) => ({ query: QUERY, page: ORIGIN + '/service-' + index, clicks: 2, impressions: 8, ctr: '0.25', position: '4.125' })),
    interpretation: 'paired_observations_not_proven_cannibalization_rank_or_complete_demand' };
  const hash = createHash('sha256').update(JSON.stringify(sorted(result))).digest('hex');
  const meta = { id: 31, start_row: 0, result_sha256: hash, collected_at: ago(20) };
  const job = { id: 21, status: 'succeeded', day: reportDay, property: ORIGIN, grant_revision: 2, created_at: ago(30),
    source_current: true, requests_attempted: 2, pages_recorded: 1, error_category: '', snapshots: [meta] };
  return { method: 'gsc-query-page-overlap-v1', organization_id: 7, project_id: 9, connection_id: 11,
    job, pages: [{ ...meta, result }], candidates: [{ query: QUERY, classification: 'positive_same_query_distinct_page_candidate',
      evidence: [0, 1].map((index) => ({ snapshot_id: meta.id, result_sha256: hash, row_index: index })) }],
    candidate_state: 'positive_overlap_candidates', candidates_truncated: false,
    provider_completeness: 'not_established', hidden_queries: 'unknown',
    interpretation: 'human_review_only_not_proven_intent_conflict_causal_loss_live_rank_complete_demand_or_deletion' };
}
class PairedApi {
  preference: ApiResult | Error = { status: 200, body: { language: 'en', current_ui_language: 'en', current_email_language: 'en' } };
  async productLanguage(): Promise<ApiResult> { if (this.preference instanceof Error) throw this.preference; return this.preference; }
  info = fixture(); role = 'owner'; sourceCurrent = true; grantRevision = 2;
  detailReads: number[] = []; commands: Record<string, unknown>[] = []; keys: string[] = [];
  losePost = false; missing = false; detailPromise: Promise<ApiResult> | null = null;
  mutateAfterDetail?: () => void;
  projectOnboarding(org: number, project: number): Promise<ApiResult> {
    return Promise.resolve({ status: 200, body: { project: { id: project, organization_id: org, name: 'Synthetic paired project',
      canonical_origin: ORIGIN, aliases: [], role: this.role } } });
  }
  projectSources(_org: number, project: number): Promise<ApiResult> {
    return Promise.resolve({ status: 200, body: { project_id: project, sources: [{ id: 11, provider: 'google_search_console',
      property: ORIGIN, state: 'active', scope_current: this.sourceCurrent, scope_kind: 'exact_origin_url_prefix',
      query_page_available: this.sourceCurrent, query_page_grant_id: 12, query_page_grant_revision: this.grantRevision }] } });
  }
  searchConsoleQueryPages(org: number, project: number, connection: number, data?: Record<string, unknown>, id?: number, key?: string): Promise<ApiResult> {
    if (data) {
      this.commands.push(structuredClone(data));
      if (this.losePost) return Promise.reject(new Error('Lost acknowledgment'));
      return Promise.resolve({ status: 202, body: { project_id: project, connection_id: connection, job_id: 21, report: 'query_page', max_requests: 3 } });
    }
    if (key) { this.keys.push(key); return Promise.resolve({ status: 200, body: { organization_id: org, project_id: project,
      connection_id: connection, request_key: key, job: this.missing ? null : structuredClone(this.info.job) } }); }
    if (id) {
      this.detailReads.push(id); const result = this.detailPromise || Promise.resolve({ status: 200, body: structuredClone(this.info) });
      this.mutateAfterDetail?.(); return result;
    }
    return Promise.resolve({ status: 200, body: { organization_id: org, project_id: project, connection_id: connection,
      report: 'query_page', jobs: [structuredClone(this.info.job)], has_more: false } });
  }
  cancelSearchConsoleSync(): Promise<ApiResult> { return Promise.resolve({ status: 202, body: {} }); }
}
describe('Genuine private paired query-page journey', () => {
  let api: PairedApi;
  beforeEach(() => { api = new PairedApi(); TestBed.configureTestingModule({ providers: [provideRouter([
    { path: 'pairs/:organizationId/:projectId', component: SearchQueryPages },
  ]), { provide: AccountApi, useValue: api }] }); });
  async function screen(preference: ApiResult | Error = { status: 200, body: { language: 'en', current_ui_language: 'en', current_email_language: 'en' } }) {
    api.preference = preference;
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/pairs/7/9', SearchQueryPages);
    await harness.fixture.whenStable(); harness.detectChanges(); return { harness, component };
  }
  async function chosen(language: 'en' | 'tr' = 'en') {
    const result = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } }); result.component.choose(11); await result.component.history(); result.component.chooseJob(21); return result;
  }
  async function submit(harness: RouterTestingHarness) {
    harness.detectChanges(); const form = harness.routeNativeElement!.querySelector('form') as HTMLFormElement;
    (form.elements.namedItem('day') as HTMLInputElement).value = reportDay;
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); await harness.fixture.whenStable(); harness.detectChanges();
  }
  it.each(['en', 'tr'] as const)('requires deliberate source/job reads then validates actual paired digest and renders literal source dates/candidates without commands in %s', async (language) => {
    const { harness, component } = await chosen(language);
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Özel gerçek sorgu–sayfa kanıtı — OrganicSEOOps' : 'Private genuine query–page evidence — OrganicSEOOps');
    expect(api.detailReads).toEqual([]); expect(api.commands).toEqual([]); expect(component.evidence()).toBeNull();
    await component.inspect(); harness.detectChanges();
    expect(component.evidence()?.candidates.length).toBe(1); expect(api.detailReads).toEqual([21]); expect(api.commands).toEqual([]);
    const element = harness.routeNativeElement!;
    expect(element.textContent).toContain(QUERY); expect(element.querySelector('img')).toBeNull();
    expect(element.textContent).toContain(language === 'tr' ? 'gizli sorgular bilinmiyor' : 'hidden queries unknown'); expect(element.textContent).toContain(language === 'tr' ? 'canlı sıralama değil' : 'not live rank');
    expect(element.textContent).toContain(api.info.pages[0].collected_at); expect(element.textContent).toContain(api.info.pages[0].result_sha256);
    expect(element.querySelector('section')!.getAttribute('lang')).toBe(language);
    expect(element.querySelector('h1')!.textContent).toBe(language === 'tr' ? 'Gerçek eşlenmiş Search Console sorgu–sayfa kanıtı' : 'Genuine paired Search Console query–page evidence');
    expect(element.querySelector('ul[aria-label="' + component.t('Actual paired rows') + '"]')).not.toBeNull();
    expect(element.querySelector('span[lang=""]')!.getAttribute('lang')).toBe('');
    expect(element.querySelector('#paired-job option[value="21"]')!.getAttribute('lang')).toBe('en');
    const evidence = component.evidence(), reads = [...api.detailReads];
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Private genuine query–page evidence — OrganicSEOOps' : 'Özel gerçek sorgu–sayfa kanıtı — OrganicSEOOps');
    expect(component.evidence()).toBe(evidence); expect(component.sourceId()).toBe(11); expect(component.jobId()).toBe(21);
    expect((element.querySelector('#paired-source') as HTMLSelectElement).value).toBe('11');
    expect((element.querySelector('#paired-job') as HTMLSelectElement).value).toBe('21');
    expect(api.detailReads).toEqual(reads); expect(api.commands).toEqual([]);
    expect(element.querySelector('a[href="/app/intent/7/9"]')).not.toBeNull();
    harness.fixture.destroy(); TestBed.inject(Title).setTitle('Next route — OrganicSEOOps');
    component.productLanguage.set(language); TestBed.tick();
    expect(TestBed.inject(Title).getTitle()).toBe('Next route — OrganicSEOOps');
  });
  it('rejects changed bytes, false candidate associations and misleading complete coverage despite successful GET', async () => {
    const { component } = await chosen(); api.info.pages[0].result.observations[0].clicks = 3;
    await component.inspect(); expect(component.evidence()).toBeNull();
    api.info = fixture(); await component.history(); component.chooseJob(21); api.info.candidates[0].evidence[0].row_index = 1;
    await component.inspect(); expect(component.evidence()).toBeNull();
    api.info = fixture(); await component.history(); component.chooseJob(21); api.info.provider_completeness = 'complete';
    await component.inspect(); expect(component.evidence()).toBeNull(); expect(api.commands).toEqual([]);
  });
  it('denies source scope, original dates, grant/latest metadata and role loss during delivery', async () => {
    const { component } = await chosen(); api.info.pages[0].collected_at = new Date(Date.now() + 60000).toISOString();
    await component.inspect(); expect(component.evidence()).toBeNull();
    api.info = fixture(); await component.history(); component.chooseJob(21); api.mutateAfterDetail = () => { api.role = 'viewer'; };
    await component.inspect(); expect(component.evidence()).toBeNull();
    api.role = 'owner'; api.mutateAfterDetail = () => { api.info.job.source_current = false; };
    await component.history(); component.chooseJob(21); await component.inspect(); expect(component.evidence()).toBeNull();
    expect(api.commands).toEqual([]);
  });
  it.each(['en', 'tr'] as const)('freezes exact source grant/day and dispatches once only after fresh role and source checks in %s', async (language) => {
    const { harness, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } }); component.choose(11); harness.detectChanges();
    const form = harness.routeNativeElement!.querySelector('form') as HTMLFormElement;
    const day = form.elements.namedItem('day') as HTMLInputElement; day.value = reportDay;
    expect(day.required).toBe(true); expect(day.type).toBe('date');
    expect(form.querySelector('button')!.textContent).toBe(component.t('Request this exact paired report (up to 3 units)'));
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(harness.routeNativeElement!.querySelector('form')).toBe(form); expect(day.value).toBe(reportDay);
    expect(component.sourceId()).toBe(11); expect(api.commands).toEqual([]);
    component.productLanguage.set(language); harness.detectChanges(); await submit(harness);
    expect(api.commands.length).toBe(1); expect(api.commands[0]).toMatchObject({ day: reportDay, grant_id: 12, grant_revision: 2 });
    expect(api.detailReads).toEqual([]); expect(component.evidence()).toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain(component.t(component.message()));
    api.grantRevision = 3; await submit(harness); expect(api.commands.length).toBe(1);
  });
  it.each(['en', 'tr'] as const)('reconciles uncertain POST using exact GET only and deliberate retry preserves the original key in %s', async (language) => {
    const { harness, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } }); component.choose(11); api.losePost = true; await submit(harness);
    expect(api.commands.length).toBe(1); expect(component.pending()).not.toBeNull();
    const pending = component.pending();
    expect(harness.routeNativeElement!.textContent).toContain(component.t("Request acknowledgment is uncertain. Exact source, day and key are frozen in this component's memory only. No automatic replay."));
    expect(harness.routeNativeElement!.querySelector('[role="alert"]')!.textContent).toBe(component.t(component.error()));
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(component.pending()).toBe(pending); expect(api.commands).toHaveLength(1); expect(api.keys).toEqual([]);
    component.productLanguage.set(language); harness.detectChanges();
    api.missing = true; await component.reconcile(); expect(api.commands.length).toBe(1);
    expect(api.keys).toEqual([String(api.commands[0]['idempotency_key'])]); expect(component.notFound()).toBe(true);
    api.losePost = false; await component.retry(); expect(api.commands.length).toBe(2); expect(api.commands[1]).toEqual(api.commands[0]);
    expect(component.pending()).toBeNull(); expect(api.detailReads).toEqual([]);
  });
  it('current source loss prevents uncertain retry and late route responses cannot restore private evidence', async () => {
    const { harness, component } = await chosen(); api.losePost = true; await submit(harness); api.missing = true;
    await component.reconcile(); api.sourceCurrent = false; await component.retry(); expect(api.commands.length).toBe(1);
    await harness.navigateByUrl('/pairs/7/10', SearchQueryPages); await harness.fixture.whenStable();
    api.sourceCurrent = true; await component.load(); component.choose(11); await component.history(); component.chooseJob(21);
    let resolve!: (value: ApiResult) => void; api.detailPromise = new Promise((done) => { resolve = done; });
    const pending = component.inspect();
    for (let index = 0; index < 10 && !api.detailReads.length; index++) await new Promise((done) => setTimeout(done, 0));
    await harness.navigateByUrl('/pairs/7/11', SearchQueryPages); resolve({ status: 200, body: structuredClone(api.info) }); await pending;
    expect(component.evidence()).toBeNull(); expect(component.pending()).toBeNull();
  });

  it('keeps invalid unavailable preferences and fresh production paired interfaces English without commands', async () => {
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    try {
      for (const mode of ['invalid', 'incompatible', 'signed-out', 'unavailable', 'production'] as const) {
        TestBed.resetTestingModule(); api = new PairedApi();
        TestBed.configureTestingModule({ providers: [provideRouter([
          { path: 'pairs/:organizationId/:projectId', component: SearchQueryPages },
        ]), { provide: AccountApi, useValue: api }] });
        buildEnvironment.production = mode === 'production';
        const preference: ApiResult | Error = mode === 'unavailable' ? new Error('private preference error')
          : mode === 'signed-out' ? { status: 401, body: {} } : { status: 200, body: {
            language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: mode === 'incompatible' ? 'tr' : 'en', current_email_language: 'en' } };
        const { harness, component } = await screen(preference);
        expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe('en');
        expect(TestBed.inject(Title).getTitle()).toBe('Private genuine query–page evidence — OrganicSEOOps');
        expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe('Genuine paired Search Console query–page evidence');
        expect(harness.routeNativeElement!.textContent).not.toContain('private preference error');
        expect(harness.routeNativeElement!.textContent).not.toContain('incelenmemiş Türkçe');
        if (mode === 'production') expect(component.productLanguage()).toBe('tr');
        api.role = 'viewer'; await component.load(); harness.detectChanges();
        expect(harness.routeNativeElement!.querySelector('[role="alert"]')!.textContent).toBe('Current owner/admin source scope unavailable. Refresh before proceeding.');
        expect(api.commands).toEqual([]); expect(api.keys).toEqual([]); harness.fixture.destroy();
      }
    } finally { buildEnvironment.production = production; }
  });
});
