import { Title } from '@angular/platform-browser';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { vi } from 'vitest';
import { AccountApi, ApiResult } from '../account/account-api';
import { BusinessProfile } from './business-profile';
import { environment } from '../../environments/environment';

class SourceApi {
  language: 'en' | 'tr' = 'en';
  productLanguage(): Promise<ApiResult> { return Promise.resolve({ status: 200, body: {
    language: this.language, current_ui_language: 'en', current_email_language: 'en' } }); }
  requests: Record<string, unknown>[] = []; pending: Promise<ApiResult> | null = null;
  current = true; role: unknown = 'owner'; revision = 0; foreign = false; queries: string[] = [];
  projectOnboarding(org: number, project: number) { return Promise.resolve({ status: 200, body: {
    project: { id: project, organization_id: org, name: 'Synthetic business project', role: this.role } } }); }
  projectBusinessProfile(org: number, project: number, data?: Record<string, unknown>, requestKey?: string): Promise<ApiResult> {
    if (requestKey) this.queries.push(requestKey);
    if (!data) return Promise.resolve({ status: 200, body: { organization_id: org, project_id: this.foreign ? 999 : project,
      policy_version: 'business-profile-response-only-v1', memory_seconds: 900, configured: true, configuration_revision: 4,
      verified_origins: ['https://local.example.invalid'], assessments: [{ id: 21, business_name: 'Customer facts', profile_url: 'https://maps.example.invalid/selected' }],
      grants: [{ id: 31, project_id: project, state: this.revision ? 'active' : 'pending_selection', revision: this.revision,
        source_current: this.current, read_available: this.current, revoke_available: true,
        selection: { account_name: 'accounts/123', location_name: 'locations/456', assessment_id: 21, configuration_revision: 4,
          origin: 'https://local.example.invalid', authorize_business: true } }], grants_has_more: false, assessments_has_more: false,
      attempts: requestKey ? [{ id: 51, project_id: project, operation: 'read', status: 'running', error_category: '',
        cancel_requested: false, reserved_units: 4, actual_units: 0, usage_state: 'reserved' }] : [], attempts_has_more: false } });
    this.requests.push(data);
    if (data['action'] === 'read') { this.revision = 1; return this.pending || Promise.resolve(this.result(project)); }
    return Promise.resolve({ status: 200, body: { project_id: project, state: 'revoked' } });
  }
  result(project = 9): ApiResult { return { status: 200, body: { project_id: project, job_id: 51, grant_id: 31, grant_revision: 1,
    policy_version: 'business-profile-response-only-v1', collected_at: new Date().toISOString(),
    expires_at: new Date(Date.now() + 900_000).toISOString(), result: {
      profile: { name: 'locations/456', title: 'Unchanged <script> &amp; business', metadata: { mapsUri: 'https://maps.example.invalid/selected' } },
      reviews: { reviews: [{ reviewId: 'original-review', comment: 'Original <img src=x onerror=evil()> text',
        reviewer: { displayName: 'Original reviewer', profilePhotoUrl: 'https://untrusted.example.invalid/photo' } }], nextPageToken: 'original-token' },
      coverage: 'first_page_only_not_complete_history', ranking: 'unavailable', device: 'unsupported', geolocation: 'unsupported',
      direct_writes: 'unavailable', other_platforms: 'unavailable' } } }; }
}

describe('Private response-only Business Profile lifecycle', () => {
  let api: SourceApi;
  beforeEach(() => { api = new SourceApi(); TestBed.configureTestingModule({ providers: [provideRouter([
    { path: 'business/:organizationId/:projectId', component: BusinessProfile },
    { path: 'away', component: BusinessProfile },
  ]), { provide: AccountApi, useValue: api }] }); });
  afterEach(() => vi.useRealTimers());
  async function screen() {
    const harness = await RouterTestingHarness.create();
    const component = await harness.navigateByUrl('/business/7/9', BusinessProfile);
    await harness.fixture.whenStable(); harness.detectChanges(); return { harness, component };
  }
  function submit(harness: RouterTestingHarness) {
    const form = harness.routeNativeElement!.querySelector('section[aria-label] form')!;
    (form.querySelector('input') as HTMLInputElement).checked = true;
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  }
  it.each(['en', 'tr'] as const)('requires explicit read acceptance, renders original metadata as inert attributed text and clears by fifteen minutes (%s)', async (language) => {
    api.language = language;
    const { harness, component } = await screen();
    const storage = vi.spyOn(Storage.prototype, 'setItem');
    const element = harness.routeNativeElement!;
    expect(element.querySelector('[aria-labelledby="gbp-title"]')?.getAttribute('lang')).toBe(language);
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Özel Google İşletme Profili okuyucusu — OrganicSEOOps' : 'Private Google Business Profile reader — OrganicSEOOps');
    expect(element.querySelector('h1')?.textContent).toBe(language === 'tr' ? 'Özel Google İşletme Profili okuyucusu' : 'Private Google Business Profile reader');
    expect(element.textContent).toContain(language === 'tr' ? 'Özellik koşulları ve gizlilik' : 'Feature Terms and privacy');
    expect(element.textContent).toContain(language === 'tr' ? 'bu özellik yalnızca okur' : 'this feature only reads');
    expect(element.textContent).toContain(language === 'tr' ? 'en fazla on beş dakika' : 'at most fifteen minutes');
    expect(element.textContent).toContain(language === 'tr' ? 'veritabanımızda, önbellekte, günlüklerde' : 'database, cache, logs');
    expect(element.textContent).toContain(language === 'tr' ? 'İlk yirmi hesap' : 'First twenty accounts');
    expect(element.querySelector('section[aria-label]')?.getAttribute('aria-label')).toBe(language === 'tr' ? 'İşletme yetkilendirmesi 31' : 'Business grant 31');
    expect(element.querySelector('section[aria-label] [lang="en"]')?.textContent).toBe('pending_selection');
    expect(element.querySelector('p [lang=""]')?.textContent).toBe('Synthetic business project');
    const consent = element.querySelector('form')!;
    consent.querySelector<HTMLSelectElement>('[name="assessment"]')!.value = '21';
    consent.querySelector<HTMLSelectElement>('[name="origin"]')!.value = 'https://local.example.invalid';
    consent.querySelector<HTMLInputElement>('[name="account"]')!.value = 'accounts/123';
    consent.querySelector<HTMLInputElement>('[name="location"]')!.value = 'locations/456';
    consent.querySelector<HTMLInputElement>('[name="authority"]')!.checked = true;
    const source = vi.spyOn(api, 'projectBusinessProfile');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Private Google Business Profile reader — OrganicSEOOps' : 'Özel Google İşletme Profili okuyucusu — OrganicSEOOps');
    expect(element.querySelector('form')).toBe(consent);
    expect(consent.querySelector<HTMLSelectElement>('[name="assessment"]')!.value).toBe('21');
    expect(consent.querySelector<HTMLInputElement>('[name="account"]')!.value).toBe('accounts/123');
    expect(consent.querySelector<HTMLInputElement>('[name="authority"]')!.checked).toBe(true);
    expect(source).not.toHaveBeenCalled(); component.productLanguage.set(language); harness.detectChanges();
    expect(consent.querySelector('[name="assessment"]')?.getAttribute('lang')).toBe('');
    expect(consent.querySelector('[name="account"]')?.getAttribute('lang')).toBe('en');
    source.mockRestore();
    expect(harness.routeNativeElement!.querySelector('a[href="https://policies.google.com/privacy"]')).toBeTruthy();
    harness.routeNativeElement!.querySelector('section[aria-label] form')!.dispatchEvent(new Event('submit', { cancelable: true }));
    expect(api.requests).toEqual([]);
    vi.useFakeTimers(); submit(harness); await Promise.resolve(); harness.detectChanges();
    expect(api.requests[0]['accepted']).toBe(true); expect(component.result()).not.toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain('Unchanged <script> &amp; business');
    expect(harness.routeNativeElement!.textContent).toContain('Original reviewer');
    expect(harness.routeNativeElement!.querySelector('script, img, iframe')).toBeNull();
    expect(storage).not.toHaveBeenCalled();
    const delivered = component.result(); const key = component.requestKey(); const count = api.requests.length;
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(component.result()).toBe(delivered); expect(component.requestKey()).toBe(key); expect(api.requests).toHaveLength(count);
    component.productLanguage.set(language); harness.detectChanges();
    expect(Array.from(element.querySelectorAll('pre')).every(node => node.getAttribute('lang') === '')).toBe(true);
    expect(element.querySelector('pre')?.textContent).toBe(JSON.stringify(delivered!.profile, null, 2));
    expect(element.querySelectorAll('pre')[1]?.textContent).toBe(JSON.stringify(delivered!.reviews, null, 2));
    expect(element.textContent).toContain(language === 'tr' ? 'Yalnızca ilk sayfa için kısmi kapsam' : 'First-page-only partial coverage');
    await vi.advanceTimersByTimeAsync(900_001); harness.detectChanges();
    expect(component.result()).toBeNull(); expect(harness.routeNativeElement!.textContent).not.toContain('Original reviewer');
    expect(element.textContent).toContain(language === 'tr' ? 'sonuçlarının süresi doldu ve temizlendi' : 'results expired and were cleared');
    storage.mockRestore();
    harness.fixture.destroy(); vi.useRealTimers();
    TestBed.inject(Title).setTitle('Next route — OrganicSEOOps');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); TestBed.tick();
    expect(TestBed.inject(Title).getTitle()).toBe('Next route — OrganicSEOOps');
  });
  it('discards late data on clear, hide, scope reuse and source loss without replaying reads', async () => {
    const { harness, component } = await screen(); let resolve!: (result: ApiResult) => void;
    api.pending = new Promise((done) => resolve = done); submit(harness); component.clear(); resolve(api.result()); await Promise.resolve();
    expect(component.result()).toBeNull(); api.pending = null; submit(harness); await Promise.resolve();
    expect(component.result()).not.toBeNull(); window.dispatchEvent(new Event('pagehide')); expect(component.result()).toBeNull();
    submit(harness); await Promise.resolve(); api.current = false; await component.checkSource(); expect(component.result()).toBeNull();
    api.current = true; api.pending = new Promise((done) => resolve = done); submit(harness);
    await harness.navigateByUrl('/business/7/10', BusinessProfile); resolve(api.result()); await Promise.resolve();
    expect(component.result()).toBeNull(); expect(api.requests.every((request) => request['action'] === 'read')).toBe(true);
  });
  it.each(['en', 'tr'] as const)('rejects foreign/expired results and reconciles uncertain requests through metadata only (%s)', async (language) => {
    api.language = language;
    const { harness, component } = await screen(); api.pending = Promise.resolve(api.result(999));
    submit(harness); await Promise.resolve(); expect(component.result()).toBeNull();
    const expired = api.result(); expired.body['expires_at'] = new Date(Date.now() - 1).toISOString(); api.pending = Promise.resolve(expired);
    submit(harness); await Promise.resolve(); expect(component.result()).toBeNull();
    const count = api.requests.length; const key = component.requestKey(); await component.reconcile(); harness.detectChanges();
    expect(api.requests.length).toBe(count); expect(api.queries).toEqual([key]); expect(component.result()).toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'İstek 51' : 'Request 51');
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Yalnızca meta veri içeren deneme durumu' : 'Metadata-only attempt status');
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'kayıtlı hata yok' : 'no recorded error');
    expect(Array.from(harness.routeNativeElement!.querySelectorAll('[lang="en"]')).some(node => node.textContent?.includes('read · running'))).toBe(true);
    expect(harness.routeNativeElement!.querySelector('pre')).toBeNull(); await component.cancel(51);
    expect(api.requests.at(-1)).toEqual({ action: 'cancel', job_id: 51 }); expect(component.result()).toBeNull();
    api.foreign = true; await component.load(); harness.detectChanges(); expect(component.status()).toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'işletme sahibi/yönetici erişimi iptal edildi' : 'owner/admin access revoked');
    if (language === 'tr') {
      api.foreign = false; const preference = vi.spyOn(api, 'productLanguage');
      async function reload() {
        await harness.navigateByUrl('/away', BusinessProfile); await harness.navigateByUrl('/business/7/9', BusinessProfile);
        await harness.fixture.whenStable(); harness.detectChanges(); return harness.routeNativeElement!;
      }
      for (const result of [
        { status: 503, body: { language: 'tr', current_ui_language: 'en', current_email_language: 'en' } },
        { status: 200, body: { language: ['tr'], current_ui_language: 'en', current_email_language: 'en' } },
        { status: 200, body: { language: 'tr', current_ui_language: 'tr', current_email_language: 'en' } },
      ]) {
        preference.mockResolvedValue(result);
        expect((await reload()).querySelector('[aria-labelledby="gbp-title"]')?.getAttribute('lang')).toBe('en');
        expect(TestBed.inject(Title).getTitle()).toBe('Private Google Business Profile reader — OrganicSEOOps');
      }
      preference.mockRejectedValue(new Error('private preference unavailable')); const fallback = await reload();
      expect(fallback.querySelector('[aria-labelledby="gbp-title"]')?.getAttribute('lang')).toBe('en');
      expect(TestBed.inject(Title).getTitle()).toBe('Private Google Business Profile reader — OrganicSEOOps');
      expect(fallback.textContent).not.toContain('private preference unavailable'); preference.mockRestore();
      const buildEnvironment = environment as { production: boolean }; const production = buildEnvironment.production;
      try {
        buildEnvironment.production = true; const productionElement = await reload();
        expect(harness.routeDebugElement!.componentInstance.productLanguage()).toBe('tr');
        expect(productionElement.querySelector('[aria-labelledby="gbp-title"]')?.getAttribute('lang')).toBe('en');
        expect(TestBed.inject(Title).getTitle()).toBe('Private Google Business Profile reader — OrganicSEOOps');
        expect(productionElement.querySelector('h1')?.textContent).toBe('Private Google Business Profile reader');
        expect(productionElement.textContent).not.toContain('iki dilli onay bekleniyor');
      } finally { buildEnvironment.production = production; }
    }
  });
  it('denies malformed or non-manager roles before any business-source request', async () => {
    api.role = 'member'; const source = vi.spyOn(api, 'projectBusinessProfile');
    const { component, harness } = await screen();
    for (const role of ['member', 'viewer', ['owner'], ['admin'], null, {}, 'other']) {
      api.role = role; component.result.set(api.result().body['result'] as NonNullable<ReturnType<BusinessProfile['result']>>);
      await component.load(); harness.detectChanges();
      expect(component.status()).toBeNull(); expect(component.result()).toBeNull();
      expect(component.error()).toContain('owner/admin'); expect(source).not.toHaveBeenCalled();
      expect(harness.routeNativeElement?.querySelector('form')).toBeNull();
    }
    for (const role of ['owner', 'admin']) {
      api.role = role; await component.load(); expect(component.status()).not.toBeNull(); expect(component.error()).toBe('');
    }
    expect(source.mock.calls).toHaveLength(2); expect(api.requests).toEqual([]); source.mockRestore();
  });
});
