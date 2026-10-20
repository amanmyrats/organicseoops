import { Title } from '@angular/platform-browser';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { vi } from 'vitest';
import { AccountApi, ApiResult } from '../account/account-api';
import { BotLogs } from './bot-logs';
import { environment } from '../../environments/environment';

class LogApi {
  preference: ApiResult | Error = { status: 200, body: { language: 'en', current_ui_language: 'en', current_email_language: 'en' } };
  async productLanguage(): Promise<ApiResult> { if (this.preference instanceof Error) throw this.preference; return this.preference; }
  pending: Promise<ApiResult> | null = null; foreign = false; denied = false; empty = false; viewer = false;
  uploads: { file: Blob; headers: Record<string, string> }[] = []; cursors: (number | null)[] = [];
  projectOnboarding(org: number, project: number) { return Promise.resolve({ status: 200, body: { project: { id: project, organization_id: org, name: 'Synthetic ' + project } } }); }
  job(project: number) { return { id: 8, project_id: project, status: 'succeeded', created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:01:00Z',
    source_current: true, error_category: '', cancel_requested: false, inventory_id: 3, crawl_run_id: 4, evidence: { summary: {
      origin: 'https://logs.example.invalid', rows_seen: 1, window: { start: '2026-09-30T00:00:00Z', end: '2026-10-01T00:00:00Z' },
      groups: [{ agent: 'GPTBot', identity: 'user_agent_only_unverified', known_url: 'https://logs.example.invalid/<script>', request_count: 1,
        status_counts: { '404': 1 }, first_seen: '2026-09-30T12:00:00Z', last_seen: '2026-09-30T12:00:00Z' }] },
      request_candidates: { unmatched_inventory_requests: 0, redirect_or_error_requests: 1 }, inventory_families: [] } }; }
  page(project = 9, before: number | null = null): ApiResult { return { status: this.denied ? 403 : 200, body: { project_id: this.foreign ? 99 : project,
    method: 'bot-log-jsonl-v1', can_manage: !this.viewer, origins: ['https://logs.example.invalid'],
    inventories: [{ id: 3, crawl_run_id: 4, observed_at: '2026-09-30T00:00:00Z', origins: [{ origin: 'https://logs.example.invalid', url_count: 1 }] }],
    jobs: this.empty || before !== null ? [] : [this.job(project)], next_before: before === null && !this.empty ? 8 : null } }; }
  botLogs(_org: number, project: number, id: number, before: number | null) { this.cursors.push(before); return this.pending || Promise.resolve(id ? { status: 200, body: { project_id: project, job: this.job(project) } } : this.page(project, before)); }
  uploadBotLogs(_org: number, project: number, file: Blob, headers: Record<string, string>) {
    this.uploads.push({ file, headers }); return this.pending || Promise.resolve({ status: 202, body: { project_id: project, job: this.job(project) } }); }
  indexationEvidence(_org: number, project: number, crawl: number) { return Promise.resolve({ status: 200, body: { project_id: project, report: { crawl_run_id: crawl, engine_indexed_state: 'unknown_no_engine_report' } } }); }
}

describe('Private minimized bot-log consumer', () => {
  let api: LogApi;
  beforeEach(() => { api = new LogApi(); TestBed.configureTestingModule({ providers: [provideRouter([
    { path: 'logs/:organizationId/:projectId', component: BotLogs }]), { provide: AccountApi, useValue: api }] }); });
  afterEach(() => vi.restoreAllMocks());
  async function screen(preference: ApiResult | Error = { status: 200, body: { language: 'en', current_ui_language: 'en', current_email_language: 'en' } }) { api.preference = preference; const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/logs/7/9', BotLogs);
    await harness.fixture.whenStable(); harness.detectChanges(); return { harness, component }; }
  it.each(['en', 'tr'] as const)('renders partial unverified counts as text with separate source handoff and permission-aware native form in %s', async (language) => {
    const { harness, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } }); const text = harness.routeNativeElement!.textContent!;
    expect(text).toContain(language === 'tr' ? 'analitik ziyaretler' : 'not analytics visits'); expect(text).toContain(language === 'tr' ? 'yalnızca kullanıcı aracı, doğrulanmamış' : 'user-agent-only unverified'); expect(text).toContain('404: 1');
    expect(text).toContain(language === 'tr' ? '0.04 beyan edilen saat başına' : '0.04 per declared hour'); expect(harness.routeNativeElement!.querySelector('script')).toBeNull();
    expect(harness.routeNativeElement!.querySelector('input[type=file]')).not.toBeNull();
    expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe(language);
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Özel yetkilendirilmiş bot günlüğü gözlemleri — OrganicSEOOps' : 'Private authorized bot-log observations — OrganicSEOOps');
    expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe(language === 'tr' ? 'Özel yetkilendirilmiş bot günlüğü gözlemleri' : 'Private authorized bot-log observations');
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'iki dilli onay bekleniyor' : 'Closure activation and legal release review remain unfinished');
    const page = component.page(), cursors = [...api.cursors];
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Private authorized bot-log observations — OrganicSEOOps' : 'Özel yetkilendirilmiş bot günlüğü gözlemleri — OrganicSEOOps');
    expect(component.page()).toBe(page); expect(api.cursors).toEqual(cursors); expect(api.uploads).toEqual([]);
    component.productLanguage.set(language); harness.detectChanges();
    await component.indexation(component.page()!.jobs[0]); expect(component.indexationReport()).toContain('unknown_no_engine_report');
    api.viewer = true; await component.load(); harness.detectChanges(); expect(harness.routeNativeElement!.querySelector('form')).toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Salt okunur rol' : 'Read-only role');
    harness.fixture.destroy(); TestBed.inject(Title).setTitle('Next route — OrganicSEOOps');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); TestBed.tick();
    expect(TestBed.inject(Title).getTitle()).toBe('Next route — OrganicSEOOps');
  });
  it('replaces keyset pages, shows empty/network/denied states and clears prior evidence', async () => {
    const { harness, component } = await screen(); await component.load(8); harness.detectChanges();
    expect(api.cursors).toEqual([null, 8]); expect(harness.routeNativeElement!.textContent).toContain('No imports');
    api.denied = true; await component.load(); expect(component.page()).toBeNull(); expect(component.error()).toContain('access denied');
    api.denied = false; api.pending = Promise.reject(new Error('network')); await component.load(); expect(component.page()).toBeNull();
    expect(component.loading()).toBe(false);
  });
  it.each(['en', 'tr'] as const)('submits an opaque bounded file with authorization metadata, clears native file input and never displays raw text in %s', async (language) => {
    const { harness, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } }); const form = harness.routeNativeElement!.querySelector('form')!;
    const fields = new FormData(); const file = new File(['private-raw-log'], 'private-file-name.jsonl'); fields.set('file', file);
    fields.set('origin', 'https://logs.example.invalid'); fields.set('inventory', '3'); fields.set('start', '2026-09-30T00:00:00Z');
    fields.set('end', '2026-10-01T00:00:00Z'); fields.set('authorize', 'on');
    const reset = vi.spyOn(form, 'reset'); vi.spyOn(form, 'reportValidity').mockReturnValue(true);
    const fileInput = form.querySelector<HTMLInputElement>('#log-file')!;
    const authorized = form.elements.namedItem('authorize') as HTMLInputElement; authorized.checked = true;
    (form.elements.namedItem('start') as HTMLInputElement).value = '2026-09-30T00:00:00Z';
    (form.elements.namedItem('end') as HTMLInputElement).value = '2026-10-01T00:00:00Z';
    expect(authorized.required).toBe(true); expect(fileInput.required).toBe(true);
    expect(authorized.parentElement!.textContent).toContain(component.t('I am authorized to use these logs for this exact origin and confirm partial coverage and the minimized-data policy.'));
    expect(form.querySelector('#log-inventory option')!.getAttribute('lang')).toBe('en');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(harness.routeNativeElement!.querySelector('form')).toBe(form); expect(form.querySelector('#log-file')).toBe(fileInput);
    expect(authorized.checked).toBe(true); expect((form.elements.namedItem('start') as HTMLInputElement).value).toBe('2026-09-30T00:00:00Z');
    expect((form.elements.namedItem('end') as HTMLInputElement).value).toBe('2026-10-01T00:00:00Z');
    expect(reset).not.toHaveBeenCalled(); expect(api.uploads).toEqual([]);
    component.productLanguage.set(language); harness.detectChanges();
    vi.spyOn(globalThis, 'FormData').mockImplementation(function () { return fields; });
    await component.upload({ preventDefault() {}, target: form } as unknown as Event); harness.detectChanges();
    expect(api.uploads).toHaveLength(1); expect(api.uploads[0].file.size).toBe(file.size);
    expect(api.uploads[0].headers['X-Log-Authorization']).toBe('true'); expect(api.uploads[0].headers['X-Log-Request']).not.toBe('');
    expect(Object.values(api.uploads[0].headers).join()).not.toContain(file.name); expect(reset).toHaveBeenCalled();
    expect(harness.routeNativeElement!.textContent).not.toContain('private-raw-log');
    const english = 'Import 8 staged as minimized evidence; raw logfile discarded.';
    expect(component.message()).toBe(english);
    const status = harness.routeNativeElement!.querySelector<HTMLParagraphElement>('p[role="status"][lang]')!;
    expect(status.lang).toBe(language);
    expect(status.textContent).toBe(language === 'tr'
      ? 'İçe aktarma 8, asgariye indirilmiş kanıt olarak hazırlandı; ham günlük dosyası atıldı.' : english);
    const calls = [...api.cursors], headers = api.uploads[0].headers, page = component.page();
    const start = form.elements.namedItem('start') as HTMLInputElement;
    start.value = '2026-10-02T00:00:00Z'; start.focus();
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(harness.routeNativeElement!.querySelector('p[role="status"][lang]')).toBe(status);
    expect(status.lang).toBe(language === 'tr' ? 'en' : 'tr');
    expect(status.textContent).toContain(language === 'tr' ? 'raw logfile discarded' : 'ham günlük dosyası atıldı');
    expect(component.message()).toBe(english); expect(component.page()).toBe(page);
    expect(harness.routeNativeElement!.querySelector('form')).toBe(form);
    expect(start.value).toBe('2026-10-02T00:00:00Z'); expect(document.activeElement).toBe(start);
    expect(api.uploads).toHaveLength(1); expect(api.uploads[0].headers).toBe(headers); expect(api.cursors).toEqual(calls);
    await component.load(); harness.detectChanges();
    expect(component.message()).toBe(''); expect(harness.routeNativeElement!.querySelector('p[role="status"][lang]')).toBeNull();
  });
  it('ignores late prior-project responses and rejects foreign history without retaining private paths', async () => {
    const { harness, component } = await screen(); let resolve!: (result: ApiResult) => void;
    api.pending = new Promise((done) => resolve = done); const late = component.load(8);
    await Promise.resolve(); await Promise.resolve(); api.pending = null;
    await harness.navigateByUrl('/logs/7/10', BotLogs); resolve(api.page(9, 8)); await late; await harness.fixture.whenStable();
    expect(component.page()?.project_id).toBe(10); api.foreign = true; await component.load();
    expect(component.page()).toBeNull(); expect(component.indexationReport()).toBe('');
  });

  it('keeps invalid unavailable preferences and fresh production bot-log interfaces English without uploads', async () => {
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    try {
      for (const mode of ['invalid', 'incompatible', 'signed-out', 'unavailable', 'production'] as const) {
        TestBed.resetTestingModule(); api = new LogApi();
        TestBed.configureTestingModule({ providers: [provideRouter([
          { path: 'logs/:organizationId/:projectId', component: BotLogs },
        ]), { provide: AccountApi, useValue: api }] });
        buildEnvironment.production = mode === 'production';
        const preference: ApiResult | Error = mode === 'unavailable' ? new Error('private preference error')
          : mode === 'signed-out' ? { status: 401, body: {} } : { status: 200, body: {
            language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: mode === 'incompatible' ? 'tr' : 'en', current_email_language: 'en' } };
        const { harness, component } = await screen(preference);
        expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe('en');
        expect(TestBed.inject(Title).getTitle()).toBe('Private authorized bot-log observations — OrganicSEOOps');
        expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe('Private authorized bot-log observations');
        expect(harness.routeNativeElement!.textContent).not.toContain('private preference error');
        expect(harness.routeNativeElement!.textContent).not.toContain('incelenmemiş Türkçe');
        if (mode === 'production') expect(component.productLanguage()).toBe('tr');
        api.denied = true; await component.load(); harness.detectChanges();
        expect(harness.routeNativeElement!.querySelector('[role="alert"]')!.textContent).toBe('Log history unavailable or project access denied/revoked. Refresh current scope.');
        expect(api.uploads).toEqual([]); harness.fixture.destroy();
      }
    } finally { buildEnvironment.production = production; }
  });
});
