import { Title } from '@angular/platform-browser';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { vi } from 'vitest';
import { AccountApi, ApiResult } from '../account/account-api';
import { LocalVisibility } from './local-visibility';
import { environment } from '../../environments/environment';

const ID = '00000000-0000-4000-8000-000000000002';
class ObservationApi {
  language: 'en' | 'tr' = 'en';
  productLanguage(): Promise<ApiResult> { return Promise.resolve({ status: 200, body: {
    language: this.language, current_ui_language: 'en', current_email_language: 'en' } }); }
  rows: Record<string, unknown>[] = []; commands: Record<string, unknown>[] = []; queries: string[] = [];
  canReview = true; current = true; uncertain = false; foreign = false; historyPromise: Promise<ApiResult> | null = null;
  result(org = 7, project = 9, observations = this.rows.slice(-1)): ApiResult {
    return { status: 200, body: { organization_id: org, project_id: this.foreign ? 999 : project,
      method_version: 'local-manual-organic-v1', can_review: this.canReview, configuration_revision: 0,
      verified_origins: this.canReview ? ['https://local.example.invalid'] : [], requested_languages: ['en'],
      assessments: this.canReview ? [{ id: 12, business_name: 'Synthetic actual service business', location_label: '', locations: ['Actual service region'] }] : [],
      observations: observations.map((row) => ({ ...row, source_current: this.current, is_latest: row['revision'] === this.rows.length })),
      has_more: false, sources_has_more: false } };
  }
  localVisibility(org: number, project: number, data?: Record<string, unknown>, id?: string, key?: string): Promise<ApiResult> {
    if (!data) {
      if (key) { this.queries.push(key); const rows = this.rows.filter((row) => row['request_key'] === key);
        const result = this.result(org, project, rows); result.body['lookup'] = rows.length ? 'found' : 'not_found'; return Promise.resolve(result); }
      return id && this.historyPromise ? this.historyPromise : Promise.resolve(this.result(org, project, id ? [...this.rows].reverse() : this.rows.slice(-1)));
    }
    this.commands.push(data);
    const row = { ...data, id: this.rows.length + 1, project_id: project, observation_id: id || ID, revision: this.rows.length + 1,
      source_current: true, is_latest: true, created_at: new Date().toISOString(), basis: 'customer_reported_not_provider_verified',
      coverage: 'partial_inspected_organic_set_only', rank_scope: 'human_ordinal_not_universal_or_local_pack_rank' };
    this.rows.push(row);
    return this.uncertain ? Promise.reject(new Error('Lost acknowledgement')) : Promise.resolve({ status: id ? 200 : 201,
      body: { organization_id: org, project_id: project, observation: row } });
  }
}

describe('Private customer-reported local organic observations', () => {
  let api: ObservationApi;
  beforeEach(() => { api = new ObservationApi(); TestBed.configureTestingModule({ providers: [provideRouter([
    { path: 'local/:organizationId/:projectId', component: LocalVisibility },
    { path: 'away', component: LocalVisibility },
  ]), { provide: AccountApi, useValue: api }] }); });
  async function screen() {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/local/7/9', LocalVisibility);
    await harness.fixture.whenStable(); harness.detectChanges(); return { harness, component };
  }
  function fill(harness: RouterTestingHarness, rights = true) {
    const form = harness.routeNativeElement!.querySelector('form') as HTMLFormElement;
    for (const [key, value] of Object.entries({ query: 'Actual query <script>literal</script>', observation_reference: 'own-observation-1',
      observed_at: '2026-10-01T13:00:00+03:00', inspected_count: '5', ordinal: '3', matched_url: 'https://local.example.invalid/own-service',
      evidence_note: 'Own human numerical observation, applied context unknown, partial inspected set.', reason: 'Actual human report' })) {
      (form.elements.namedItem(key) as HTMLInputElement).value = value;
    }
    for (const key of ['storage_permission', 'not_api_derived']) (form.elements.namedItem(key) as HTMLInputElement).checked = rights;
    return form;
  }
  async function submit(harness: RouterTestingHarness, form: HTMLFormElement) {
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); await harness.fixture.whenStable(); harness.detectChanges();
  }
  it.each(['en', 'tr'] as const)('requires independent rights, preserves query/unknown applied context and corrects to null partial/unavailable ordinals (%s)', async (language) => {
    api.language = language;
    const { harness, component } = await screen(); const storage = vi.spyOn(Storage.prototype, 'setItem');
    const element = harness.routeNativeElement!;
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Özel elle yerel organik gözlemler — OrganicSEOOps' : 'Private manual local organic observations — OrganicSEOOps');
    expect(element.querySelector('[aria-labelledby="local-visibility-title"]')?.getAttribute('lang')).toBe(language);
    expect(element.querySelector('h1')?.textContent).toBe(language === 'tr' ? 'Elle yerel organik bağlantı gözlemleri' : 'Manual local organic-link observations');
    expect(element.querySelector('ul')?.getAttribute('aria-label')).toBe(language === 'tr' ? 'En son müşteri yerel gözlem bildirimleri' : 'Latest customer local observation reports');
    expect(element.textContent).toContain(language === 'tr' ? 'sıfır sıralama değildir' : 'not rank zero');
    expect(element.textContent).toContain(language === 'tr' ? 'uygulanan bağlamın kanıtı değildir' : 'not proof of applied context');
    expect(element.textContent).toContain(language === 'tr' ? 'Burada arama çalıştırılmaz' : 'No search is run here');
    expect(element.textContent).toContain(language === 'tr' ? '90 günlük erişim' : '90-day retained access');
    expect(element.textContent).toContain(language === 'tr' ? '30 gün içinde etkin silme' : 'within 30 days');
    expect(element.textContent).toContain(language === 'tr' ? 'en fazla 35 günlük yedekler' : 'up to 35 days');
    expect(element.querySelector('option[value="unknown"]')?.textContent).toBe(language === 'tr' ? 'Bilinmiyor' : 'Unknown');
    for (const name of ['requested_device', 'applied_device', 'status']) {
      expect(element.querySelector(`[name="${name}"]`)?.getAttribute('lang')).toBe('en');
    }
    const unsaved = fill(harness); const reads = vi.spyOn(api, 'localVisibility');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Private manual local organic observations — OrganicSEOOps' : 'Özel elle yerel organik gözlemler — OrganicSEOOps');
    expect(element.querySelector('form')).toBe(unsaved);
    expect((unsaved.elements.namedItem('query') as HTMLInputElement).value).toBe('Actual query <script>literal</script>');
    expect((unsaved.elements.namedItem('storage_permission') as HTMLInputElement).checked).toBe(true);
    expect(component.assessmentId()).toBe(12); expect(component.selectedStatus()).toBe('observed');
    expect(reads).not.toHaveBeenCalled(); component.productLanguage.set(language); harness.detectChanges(); reads.mockRestore();
    for (const name of ['origin', 'requested_location', 'applied_location', 'query', 'observation_reference', 'matched_url', 'evidence_note', 'reason']) {
      expect(unsaved.querySelector(`[name="${name}"]`)?.getAttribute('lang')).toBe('');
    }
    await submit(harness, fill(harness, false)); expect(api.commands).toEqual([]);
    await submit(harness, fill(harness));
    const input = api.commands[0]['intake'] as Record<string, unknown>;
    expect(input['ordinal']).toBe(3); expect(input['requested_location']).toBe('Actual service region');
    expect(input['applied_location']).toBe(''); expect(input['applied_device']).toBe('unknown');
    expect(input['observed_at']).toBe('2026-10-01T13:00:00+03:00');
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Bildirilen insan sıra numarası 3; evrensel sıralama değildir' : 'Reported human ordinal 3, not universal rank');
    expect(harness.routeNativeElement!.querySelector('script, img, iframe')).toBeNull();
    expect(element.textContent).toContain(language === 'tr' ? 'Bölge bilinmiyor' : 'Unknown region');
    expect(element.textContent).toContain(language === 'tr' ? 'Dil bilinmiyor' : 'Unknown language');
    expect(element.textContent).toContain(language === 'tr' ? 'yalnızca kısmi kapsam' : 'partial coverage only');
    expect(element.textContent).toContain(language === 'tr' ? 'arama veya sağlayıcı isteği çalıştırılmadı' : 'no search or provider request ran');
    for (const text of ['Actual query <script>literal</script>', 'Actual service region', 'own-observation-1', 'Own human numerical observation, applied context unknown, partial inspected set.']) {
      expect(Array.from(element.querySelectorAll('[lang=""]')).some(node => node.textContent === text)).toBe(true);
    }
    expect(Array.from(element.querySelectorAll('li [lang="en"]')).some(node => node.textContent === 'unknown')).toBe(true);
    await component.inspect(ID); harness.detectChanges();
    expect(element.querySelector('details summary')?.textContent).toBe(language === 'tr' ? 'Değiştirilemez kaynak/bağlam/zaman/sıra numarası düzeltme geçmişi (en yeni 20)' : 'Immutable source/context/time/ordinal correction history (newest 20)');
    component.edit(component.context()!.observations[0]); harness.detectChanges();
    let form = fill(harness); const status = form.elements.namedItem('status') as HTMLSelectElement;
    status.value = 'not_seen_in_inspected_set'; status.dispatchEvent(new Event('change')); harness.detectChanges();
    await submit(harness, form);
    expect((api.commands[1]['intake'] as Record<string, unknown>)['ordinal']).toBeNull();
    expect((api.commands[1]['intake'] as Record<string, unknown>)['matched_url']).toBe('');
    expect(api.commands[1]['expected_revision']).toBe(1);
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'başka yerdeki görünürlük bilinmiyor' : 'visibility elsewhere is unknown');
    component.edit(component.context()!.observations[0]); harness.detectChanges(); form = fill(harness);
    const unavailable = form.elements.namedItem('status') as HTMLSelectElement;
    unavailable.value = 'unavailable'; unavailable.dispatchEvent(new Event('change')); harness.detectChanges();
    (form.elements.namedItem('inspected_count') as HTMLInputElement).value = '0';
    await submit(harness, form);
    expect((api.commands[2]['intake'] as Record<string, unknown>)['ordinal']).toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Kullanılamıyor; incelenmiş sonuç veya sıralama değeri yok' : 'Unavailable; no inspected results or rank value');
    expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
    component.edit(component.context()!.observations[0]); harness.detectChanges();
    expect(component.selectedStatus()).toBe('unavailable');
    expect(element.textContent).toContain(language === 'tr' ? 'özgün kanıt geçmişte kalır' : 'original evidence remains in history');
    element.querySelector<HTMLButtonElement>('form button[type="button"]')!.click(); harness.detectChanges();
    expect(component.editing()).toBeNull(); expect(component.selectedStatus()).toBe('observed');
    if (language === 'tr') {
      const preference = vi.spyOn(api, 'productLanguage');
      async function reload() {
        await harness.navigateByUrl('/away', LocalVisibility); await harness.navigateByUrl('/local/7/9', LocalVisibility);
        await harness.fixture.whenStable(); harness.detectChanges(); return harness.routeNativeElement!;
      }
      for (const result of [
        { status: 503, body: { language: 'tr', current_ui_language: 'en', current_email_language: 'en' } },
        { status: 200, body: { language: ['tr'], current_ui_language: 'en', current_email_language: 'en' } },
        { status: 200, body: { language: 'tr', current_ui_language: 'tr', current_email_language: 'en' } },
      ]) {
        preference.mockResolvedValue(result);
        expect((await reload()).querySelector('[aria-labelledby="local-visibility-title"]')?.getAttribute('lang')).toBe('en');
        expect(TestBed.inject(Title).getTitle()).toBe('Private manual local organic observations — OrganicSEOOps');
      }
      preference.mockRejectedValue(new Error('private preference unavailable')); const fallback = await reload();
      expect(fallback.querySelector('[aria-labelledby="local-visibility-title"]')?.getAttribute('lang')).toBe('en');
      expect(TestBed.inject(Title).getTitle()).toBe('Private manual local organic observations — OrganicSEOOps');
      expect(fallback.textContent).not.toContain('private preference unavailable'); preference.mockRestore();
      const buildEnvironment = environment as { production: boolean }; const production = buildEnvironment.production;
      try {
        buildEnvironment.production = true; const productionElement = await reload();
        expect(harness.routeDebugElement!.componentInstance.productLanguage()).toBe('tr');
        expect(productionElement.querySelector('[aria-labelledby="local-visibility-title"]')?.getAttribute('lang')).toBe('en');
        expect(TestBed.inject(Title).getTitle()).toBe('Private manual local organic observations — OrganicSEOOps');
        expect(productionElement.querySelector('h1')?.textContent).toBe('Manual local organic-link observations');
        expect(productionElement.textContent).not.toContain('iki dilli onay bekleniyor');
      } finally { buildEnvironment.production = production; }
    }
    const titleOwner = harness.routeDebugElement!.componentInstance as LocalVisibility;
    harness.fixture.destroy(); TestBed.inject(Title).setTitle('Next route — OrganicSEOOps');
    titleOwner.productLanguage.set(titleOwner.productLanguage() === 'tr' ? 'en' : 'tr'); TestBed.tick();
    expect(TestBed.inject(Title).getTitle()).toBe('Next route — OrganicSEOOps');
  });
  it.each(['en', 'tr'] as const)('reconciles transport uncertainty without automatically replaying or searching (%s)', async (language) => {
    api.language = language;
    const { harness, component } = await screen(); api.uncertain = true; await submit(harness, fill(harness));
    expect(component.pending()).not.toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Belirsiz bildirimi kontrol et' : 'Check uncertain report');
    const frozen = component.pending(); const reads = vi.spyOn(api, 'localVisibility');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(component.pending()).toBe(frozen); expect(reads).not.toHaveBeenCalled();
    component.productLanguage.set(language); harness.detectChanges();
    const missing = api.result(7, 9, []); missing.body['lookup'] = 'not_found'; reads.mockResolvedValueOnce(missing);
    await component.reconcile(); harness.detectChanges();
    expect(component.pending()).toBe(frozen); expect(api.commands).toHaveLength(1);
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Aynı bildirimi yeniden dene' : 'Retry the same exact report');
    reads.mockRestore(); await component.reconcile(); harness.detectChanges();
    expect(api.commands.length).toBe(1); expect(api.queries).toEqual([api.commands[0]['request_key']]);
    expect(component.pending()).toBeNull(); expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'komut yeniden çalıştırılmadı' : 'no command replayed');
  });
  it.each(['en', 'tr'] as const)('keeps viewer reports read-only, labels stale source and discards foreign responses (%s)', async (language) => {
    api.language = language;
    api.canReview = false; const { harness, component } = await screen();
    expect(harness.routeNativeElement!.querySelector('form')).toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Salt okunur saklanan insan bildirimleri' : 'Read-only retained human reports');
    api.canReview = true; await component.load(); harness.detectChanges(); await submit(harness, fill(harness));
    api.current = false; await component.load(); harness.detectChanges();
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Güncel olmayan işletme/kaynak/aktör yetkisi' : 'Stale business/source/actor authority');
    api.canReview = false; await component.inspect(ID); harness.detectChanges();
    expect(harness.routeNativeElement!.querySelector('form')).toBeNull();
    api.foreign = true; await component.load(); expect(component.context()).toBeNull();
  });
  it('clears private records and rejects late history when reusing the route for another project', async () => {
    const { harness, component } = await screen(); await submit(harness, fill(harness));
    let resolve!: (value: ApiResult) => void; api.historyPromise = new Promise((done) => resolve = done);
    const history = component.inspect(ID); const old = api.result(7, 9, [...api.rows]);
    api.rows = []; await harness.navigateByUrl('/local/7/10', LocalVisibility); resolve(old); await history;
    expect(component.historyRows()).toEqual([]); expect(component.editing()).toBeNull(); expect(component.pending()).toBeNull();
    harness.detectChanges(); expect(harness.routeNativeElement!.textContent).not.toContain('Actual query <script>literal</script>');
  });
});
