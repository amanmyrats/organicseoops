import { Title } from '@angular/platform-browser';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { AccountApi, ApiResult } from '../account/account-api';
import { VisibilityHistory } from './visibility-history';
import { environment } from '../../environments/environment';

class HistoryApi {
  preference: ApiResult | Error = { status: 200, body: { language: 'en', current_ui_language: 'en', current_email_language: 'en' } };
  async productLanguage(): Promise<ApiResult> { if (this.preference instanceof Error) throw this.preference; return this.preference; }
  cursors: (number | null)[] = []; pending: Promise<ApiResult> | null = null; status = 200; foreign = false; empty = false;
  projectOnboarding(org: number, project: number) { return Promise.resolve({ status: 200, body: { project: { id: project, organization_id: org, name: 'Synthetic ' + project, role: 'viewer' } } }); }
  page(project = 9, before: number | null = null): ApiResult {
    const id = before === null ? 8 : 7;
    return { status: this.status, body: { method: 'visibility-history-v1', project_id: this.foreign ? 10 : project,
      observations: this.empty ? [] : [{ id, project_id: project, comparison_key: 'exact-comparison-key',
        context: { requested_model: 'fixture-requested', returned_model: 'fixture-returned', max_output_tokens: 80, entity_context_sha256: '<script>literal</script>', prompt_method: 'api-text-visibility-v1' },
        status: 'succeeded', error_category: '', created_at: '2026-09-30T10:00:00Z', collected_at: '2026-09-30T10:01:00Z',
        evaluation: 'unevaluated', review_revision: 2, reviewed_at: '2026-10-01T11:00:00Z',
        changes_from_prior_page_observation: ['requested_model', 'returned_model', 'max_output_tokens', 'entity_context_sha256'],
        prior_context: before === null ? 'observed_on_this_page' : 'not_loaded', answer_evidence_available: true }],
      comparison_groups: [], has_more: !this.empty && before === null, next_before_id: !this.empty && before === null ? id : null,
      rate_scope: 'history_page_is_not_a_rate_denominator; inspect_exact_methodology_rates_separately',
      referrals: { status: 'unavailable', visits: null, conversions: null, revenue: null, reason: 'no_authorized_exact_origin_analytics_referrer_campaign_grain' } } };
  }
  visibilityHistory(_org: number, project: number, before: number | null) { this.cursors.push(before); return this.pending || Promise.resolve(this.page(project, before)); }
}

describe('Private comparable API history', () => {
  let api: HistoryApi;
  beforeEach(() => { api = new HistoryApi(); TestBed.configureTestingModule({ providers: [
    provideRouter([{ path: 'history/:organizationId/:projectId', component: VisibilityHistory }]), { provide: AccountApi, useValue: api }] }); });
  async function screen(preference: ApiResult | Error = { status: 200, body: { language: 'en', current_ui_language: 'en', current_email_language: 'en' } }) {
    api.preference = preference;
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/history/7/9', VisibilityHistory);
    await harness.fixture.whenStable(); harness.detectChanges(); return { harness, component };
  }
  it.each(['en', 'tr'] as const)('shows settings changes, separate collection/review times and scoped evidence links without inferred rates/referrals in %s', async (language) => {
    const { harness, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } }); const text = harness.routeNativeElement!.textContent!;
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Özel karşılaştırılabilir API gözlem geçmişi — OrganicSEOOps' : 'Private comparable API observation history — OrganicSEOOps');
    expect(text).toContain('requested model, returned model, max output tokens, entity context sha256');
    expect(text).toContain((language === 'tr' ? 'Özgün toplama ' : 'Original collection ') + '2026-09-30T10:01:00Z'); expect(text).toContain((language === 'tr' ? 'Son insan incelemesi ' : 'Latest human review ') + '2026-10-01T11:00:00Z');
    expect(text).toContain(language === 'tr' ? 'Geçmiş sayfası grupları oran paydaları değildir' : 'History-page groups are not rate denominators'); expect(text).toContain(language === 'tr' ? 'kullanılamıyor; sıfır değildir' : 'unavailable, not zero');
    expect(harness.routeNativeElement!.querySelector('a[href="/app/visibility-samples/7/9/8"]')).not.toBeNull();
    expect(text).toContain('<script>literal</script>'); expect(harness.routeNativeElement!.querySelector('script')).toBeNull();
    expect(harness.routeNativeElement!.querySelector('form')).toBeNull();
    expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe(language === 'tr' ? 'Özel aynı koşullu API gözlem geçmişi' : 'Private like-for-like API observation history');
    expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe(language);
    expect(harness.routeNativeElement!.querySelector('dl dt span')!.getAttribute('lang')).toBe('en');
    expect(harness.routeNativeElement!.querySelector('dl dd span')!.getAttribute('lang')).toBe('');
    const dates = [...harness.routeNativeElement!.querySelectorAll('li p span')].filter(row => row.textContent?.includes('2026-'));
    expect(dates).toHaveLength(3); expect(dates.every(row => row.getAttribute('lang') === 'en')).toBe(true);
    const retained = component.history(), reads = [...api.cursors];
    const button = harness.routeNativeElement!.querySelector('button');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Private comparable API observation history — OrganicSEOOps' : 'Özel karşılaştırılabilir API gözlem geçmişi — OrganicSEOOps');
    expect(component.history()).toBe(retained); expect(api.cursors).toEqual(reads); expect(harness.routeNativeElement!.querySelector('button')).toBe(button);
    component.productLanguage.set(language); harness.detectChanges();
    const row = component.history()!.observations[0]; row.collected_at = null; row.reviewed_at = null; row.review_revision = null;
    row.context['requested_model'] = null; row.changes_from_prior_page_observation = [];
    component.history.set({ ...component.history()! }); harness.detectChanges();
    expect(harness.routeNativeElement!.querySelector('dl dd span')!.textContent).toBe(language === 'tr' ? 'kullanılamıyor / incelenmedi' : 'unavailable / unreviewed');
    expect(harness.routeNativeElement!.querySelector('dl dd span')!.getAttribute('lang')).toBe(language);
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'incelenmedi' : 'not reviewed');
    expect(api.cursors).toEqual(reads);
    harness.fixture.destroy(); TestBed.inject(Title).setTitle('Next route — OrganicSEOOps');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); TestBed.tick();
    expect(TestBed.inject(Title).getTitle()).toBe('Next route — OrganicSEOOps');
  });
  it.each(['en', 'tr'] as const)('uses returned keyset cursor, replaces pages and does not infer older-page changes in %s', async (language) => {
    const { harness, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } }); await component.load(component.history()!.next_before_id); harness.detectChanges();
    expect(api.cursors).toEqual([null, 8]); expect(component.history()!.observations.map((row) => row.id)).toEqual([7]);
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Önceki gözlem bu sayfada yüklenmedi' : 'Predecessor not loaded');
    const retained = component.history(), button = harness.routeNativeElement!.querySelector('button');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(component.history()).toBe(retained); expect(component.beforeId).toBe(8); expect(api.cursors).toEqual([null, 8]);
    expect(harness.routeNativeElement!.querySelector('button')).toBe(button);
    component.productLanguage.set(language); harness.detectChanges();
    await component.load(); expect(api.cursors).toEqual([null, 8, null]);
  });
  it('clears late prior-project pages and rejects foreign responses or revoked access', async () => {
    const { harness, component } = await screen(); let resolve!: (value: ApiResult) => void;
    api.pending = new Promise((done) => resolve = done); const late = component.load(8);
    await Promise.resolve(); await Promise.resolve(); api.pending = null;
    await harness.navigateByUrl('/history/7/10', VisibilityHistory); resolve(api.page(9, 8)); await late;
    await harness.fixture.whenStable(); expect(component.history()?.project_id).toBe(10);
    api.foreign = true; await harness.navigateByUrl('/history/7/9', VisibilityHistory); await harness.fixture.whenStable();
    expect(component.history()).toBeNull(); expect(component.error()).toContain('access denied');
    api.foreign = false; api.status = 403; await component.load(); expect(component.history()).toBeNull();
  });
  it('shows empty and network failure without retaining previous private observations', async () => {
    api.empty = true; const { harness, component } = await screen();
    expect(harness.routeNativeElement!.textContent).toContain('No observation attempts');
    api.empty = false; await component.load(); expect(component.history()).not.toBeNull();
    api.pending = Promise.reject(new Error('network')); await component.load();
    expect(component.history()).toBeNull(); expect(component.loading()).toBe(false); expect(component.error()).not.toBe('');
  });
  it('keeps invalid incompatible denied unavailable and production history preferences English', async () => {
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    try {
      for (const mode of ['invalid', 'incompatible', 'signed-out', 'unavailable', 'production'] as const) {
        TestBed.resetTestingModule(); api = new HistoryApi();
        TestBed.configureTestingModule({ providers: [provideRouter([{ path: 'history/:organizationId/:projectId', component: VisibilityHistory }]), { provide: AccountApi, useValue: api }] });
        buildEnvironment.production = mode === 'production';
        const preference: ApiResult | Error = mode === 'unavailable' ? new Error('private preference error') : mode === 'signed-out' ? { status: 401, body: {} }
          : { status: 200, body: { language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: mode === 'incompatible' ? 'tr' : 'en', current_email_language: 'en' } };
        const { harness, component } = await screen(preference);
        expect(TestBed.inject(Title).getTitle()).toBe('Private comparable API observation history — OrganicSEOOps');
        expect(component.uiLanguage()).toBe('en'); expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe('Private like-for-like API observation history');
        expect(harness.routeNativeElement!.textContent).not.toContain('incelenmemiş Türkçe'); expect(harness.routeNativeElement!.textContent).not.toContain('private preference error');
        api.status = 403; await component.load(); harness.detectChanges();
        expect(harness.routeNativeElement!.querySelector('[role=alert]')!.textContent).toBe('History unavailable or project access denied/revoked. Refresh to recheck the current scope.');
        expect(component.history()).toBeNull(); harness.fixture.destroy();
      }
    } finally { buildEnvironment.production = production; }
  });

});
