import { Title } from '@angular/platform-browser';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { vi } from 'vitest';
import { AccountApi, ApiResult } from '../account/account-api';
import { environment } from '../../environments/environment';
import { ProjectYouTube } from './project-youtube';

class SourceApi {
  role: unknown = 'owner';
  language: 'en' | 'tr' = 'en';
  productLanguage(): Promise<ApiResult> { return Promise.resolve({ status: 200, body: { language: this.language, current_ui_language: 'en', current_email_language: 'en' } }); }
  requests: Record<string, unknown>[] = [];
  pending: Promise<ApiResult> | null = null;
  projectOnboarding(org: number, project: number) { return Promise.resolve({ status: 200, body: {
    project: { id: project, organization_id: org, name: 'Synthetic video project', role: this.role } } }); }
  projectYouTube(_org: number, project: number, data?: Record<string, unknown>): Promise<ApiResult> {
    if (!data) return Promise.resolve({ status: 200, body: { project_id: project, configured: true,
      policy_version: 'youtube-response-only-v1', memory_seconds: 900, live_verified: false,
      phrases: ['service news'], languages: ['en'] } });
    this.requests.push(data);
    return this.pending || Promise.resolve(this.result(project));
  }
  result(project = 9): ApiResult { return { status: 200, body: { project_id: project, source: 'youtube',
    collected_at: new Date().toISOString(), expires_at: new Date(Date.now() + 900_000).toISOString(),
    page: { kind: 'youtube#searchListResponse', regionCode: 'US', nextPageToken: 'not-persisted', items: [
      { kind: 'youtube#searchResult', id: { kind: 'youtube#video', videoId: 'video_12345' }, snippet: {
        title: 'Unchanged <script> &amp; title', channelTitle: 'Synthetic channel', channelId: 'UC' + 'x'.repeat(22), publishedAt: '2026-09-30T01:02:03Z' } } ] } } }; }
}

describe('Response-only YouTube lifecycle', () => {
  let api: SourceApi;
  beforeEach(() => {
    api = new SourceApi();
    TestBed.configureTestingModule({ providers: [provideRouter([
      { path: 'youtube/:organizationId/:projectId', component: ProjectYouTube },
    ]), { provide: AccountApi, useValue: api }] });
  });
  afterEach(() => vi.useRealTimers());
  async function screen() {
    const harness = await RouterTestingHarness.create();
    const component = await harness.navigateByUrl('/youtube/7/9', ProjectYouTube);
    await Promise.resolve(); await Promise.resolve(); harness.detectChanges();
    return { harness, component };
  }
  function submit(harness: RouterTestingHarness) {
    const form = harness.routeNativeElement!.querySelector('form')!;
    (form.elements.namedItem('phrase') as HTMLSelectElement).value = 'service news';
    (form.elements.namedItem('language') as HTMLSelectElement).value = 'en';
    (form.elements.namedItem('region') as HTMLInputElement).value = 'TR';
    (form.elements.namedItem('accepted') as HTMLInputElement).checked = true;
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  }
  it.each(['regionCode', 'videoId', 'nextPageToken'])('rejects malformed %s without retaining a page or retrying', async (field) => {
    const { harness, component } = await screen();
    const original = field === 'regionCode' ? 'US' : field === 'videoId' ? 'video_12345' : 'not-persisted';
    const invalid: unknown[] = [[original], null, {}, 1, true, '', original + '\n'];
    if (field === 'nextPageToken') invalid.push('contains space', 'x'.repeat(513), 'é');
    for (const value of invalid) {
      api.pending = null; submit(harness); await Promise.resolve(); harness.detectChanges();
      expect(component.page()).not.toBeNull();
      const response = api.result(); const page = response.body['page'] as Record<string, unknown>;
      if (field === 'videoId') {
        const items = page['items'] as { id: Record<string, unknown> }[]; items[0].id['videoId'] = value;
      } else page[field] = value;
      api.pending = Promise.resolve(response);
      const count = api.requests.length;
      submit(harness); expect(component.page()).toBeNull();
      await Promise.resolve(); harness.detectChanges();
      expect(component.page()).toBeNull(); expect(component.busy()).toBe(false);
      expect(component.error()).toContain('No automatic retry');
      expect(api.requests).toHaveLength(count + 1);
      expect(harness.routeNativeElement!.textContent).not.toContain('Synthetic channel');
      expect(harness.routeNativeElement!.textContent).not.toContain('Additional pages may exist');
      expect(harness.routeNativeElement!.querySelector('a[href^="https://www.youtube.com/watch?v="]')).toBeNull();
    }
    for (const token of [undefined, '!', '~'.repeat(512)]) {
      const response = api.result(); const page = response.body['page'] as Record<string, unknown>;
      if (token === undefined) delete page['nextPageToken']; else page['nextPageToken'] = token;
      api.pending = Promise.resolve(response); submit(harness); await Promise.resolve(); harness.detectChanges();
      expect(component.page()).toEqual(page);
      expect(harness.routeNativeElement!.textContent!.includes('Additional pages may exist')).toBe(token !== undefined);
    }
  });
  it('requires a scalar current project role before reading source metadata or enabling search', async () => {
    const { harness, component } = await screen();
    submit(harness); await Promise.resolve();
    expect(component.page()).not.toBeNull();
    const staleForm = harness.routeNativeElement!.querySelector('form')!;
    const source = vi.spyOn(api, 'projectYouTube');
    for (const role of [['owner'], ['admin'], ['member'], ['viewer'], null, {}, 'unknown']) {
      api.role = role; source.mockClear();
      const refresh = component.load();
      expect(component.page()).toBeNull(); expect(component.canSearch()).toBe(false);
      expect(component.configured()).toBe(false); expect(component.phrases()).toEqual([]);
      await refresh; harness.detectChanges();
      expect(component.ready()).toBe(false); expect(component.canSearch()).toBe(false);
      expect(component.languages()).toEqual([]); expect(component.policyVersion()).toBe('');
      expect(source).not.toHaveBeenCalled();
      await component.search({ preventDefault() {}, currentTarget: staleForm } as unknown as SubmitEvent);
      expect(source).not.toHaveBeenCalled(); expect(api.requests).toHaveLength(1);
    }
    for (const role of ['owner', 'admin', 'member', 'viewer']) {
      api.role = role; source.mockClear(); await component.load(); harness.detectChanges();
      expect(component.ready()).toBe(true); expect(component.configured()).toBe(true);
      expect(component.canSearch()).toBe(role !== 'viewer');
      expect(source).toHaveBeenCalledExactlyOnceWith(7, 9);
      expect(Boolean(harness.routeNativeElement!.querySelector('form'))).toBe(role !== 'viewer');
    }
  });
  it.each(['en', 'tr'] as const)('requires acceptance, preserves literal metadata/provider scope and clears on expiry without storage in %s', async (language) => {
    api.language = language;
    const { harness, component } = await screen();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Ayrı YouTube herkese açık video araması — OrganicSEOOps' : 'Separate YouTube public-video search — OrganicSEOOps');
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'YouTube özelliği Koşulları ve gizlilik' : 'YouTube feature Terms and privacy');
    expect(harness.routeNativeElement!.querySelector('a[href="https://www.youtube.com/t/terms"]')).toBeTruthy();
    const storage = vi.spyOn(Storage.prototype, 'setItem');
    const form = harness.routeNativeElement!.querySelector('form')!;
    expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe(language);
    expect(form.querySelector('label[for="youtube-phrase"]')!.textContent).toBe(language === 'tr' ? 'Güncel yapılandırılmış başlangıç ifadesi' : 'Current configured seed');
    expect(form.querySelector('label[for="youtube-language"]')!.textContent).toBe(language === 'tr' ? 'Alaka dili tercihi' : 'Relevance-language preference');
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'talep olmadığını veya tam kapsamı kanıtlamaz' : 'no demand or complete coverage');
    (form.elements.namedItem('phrase') as HTMLSelectElement).value = 'service news';
    (form.elements.namedItem('language') as HTMLSelectElement).value = 'en';
    const source = vi.spyOn(api, 'projectYouTube');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Separate YouTube public-video search — OrganicSEOOps' : 'Ayrı YouTube herkese açık video araması — OrganicSEOOps');
    expect((form.elements.namedItem('phrase') as HTMLSelectElement).value).toBe('service news');
    expect((form.elements.namedItem('language') as HTMLSelectElement).value).toBe('en');
    expect(source).not.toHaveBeenCalled();
    component.productLanguage.set(language); harness.detectChanges();
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    expect(api.requests.length).toBe(0);
    vi.useFakeTimers(); submit(harness); await Promise.resolve(); harness.detectChanges();
    expect(api.requests[0]['accepted']).toBe(true);
    expect(api.requests[0]['selection']).toEqual({ phrase: 'service news', relevance_language: 'en', region_code: 'TR', days: 1 });
    expect(api.requests[0]['policy_version']).toBe('youtube-response-only-v1');
    const retained = component.page(), expiry = component.expiresAt(), calls = api.requests.length;
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(component.page()).toBe(retained); expect(component.expiresAt()).toBe(expiry); expect(api.requests).toHaveLength(calls);
    component.productLanguage.set(language); harness.detectChanges();
    expect(harness.routeNativeElement!.querySelector('span[lang=""]')!.textContent).toBe('Synthetic video project');
    expect(component.page()?.regionCode).toBe('US'); expect(component.requestedRegion()).toBe('TR');
    expect(harness.routeNativeElement!.textContent).toContain('Unchanged <script> &amp; title');
    expect(harness.routeNativeElement!.querySelector('script')).toBeNull();
    expect(harness.routeNativeElement!.querySelector('a[href="https://www.youtube.com/watch?v=video_12345"]')).toBeTruthy();
    expect(storage).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(900_001); harness.detectChanges();
    expect(component.page()).toBeNull(); expect(harness.routeNativeElement!.textContent).not.toContain('Synthetic channel');
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'süresi doldu ve temizlendi' : 'results expired and were cleared');
    storage.mockRestore();
    harness.fixture.destroy(); TestBed.inject(Title).setTitle('Next route — OrganicSEOOps');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); TestBed.tick();
    expect(TestBed.inject(Title).getTitle()).toBe('Next route — OrganicSEOOps');
  });
  it.each(['en', 'tr'] as const)('discards late responses on clear, pagehide and route reuse, and refuses expired or foreign responses in %s', async (language) => {
    api.language = language;
    const { harness, component } = await screen();
    let resolve!: (result: ApiResult) => void;
    api.pending = new Promise((done) => resolve = done);
    submit(harness); component.clear(); resolve(api.result()); await Promise.resolve();
    expect(component.page()).toBeNull();
    api.pending = null; submit(harness); await Promise.resolve(); expect(component.page()).not.toBeNull();
    window.dispatchEvent(new Event('pagehide')); expect(component.page()).toBeNull(); harness.detectChanges();
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'ekran verileri temizlendi' : 'screen data cleared');
    api.pending = new Promise((done) => resolve = done); submit(harness);
    await harness.navigateByUrl('/youtube/7/10', ProjectYouTube);
    resolve(api.result()); await Promise.resolve(); await Promise.resolve(); harness.detectChanges();
    expect(component.page()).toBeNull(); expect(harness.routeNativeElement!.textContent).not.toContain('Synthetic channel');
    api.pending = Promise.resolve(api.result(9)); submit(harness); await Promise.resolve();
    expect(component.page()).toBeNull();
    const expired = api.result(10); expired.body['expires_at'] = new Date(Date.now() - 1).toISOString();
    api.pending = Promise.resolve(expired); submit(harness); await Promise.resolve();
    expect(component.page()).toBeNull();
    harness.detectChanges();
    const root = harness.routeNativeElement!, alert = root.querySelector<HTMLParagraphElement>('[role="alert"]')!;
    const english = 'YouTube search unavailable (request_not_confirmed). No automatic retry; no result retained.';
    expect(component.error()).toBe(english);
    expect(alert.lang).toBe(language);
    expect(alert.textContent).toBe(language === 'tr'
      ? 'YouTube araması kullanılamıyor (request_not_confirmed). Otomatik yeniden deneme yoktur; sonuç saklanmadı.' : english);
    const input = root.querySelector<HTMLInputElement>('#youtube-region')!, form = input.closest('form')!;
    input.value = 'US'; input.focus(); const count = api.requests.length;
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(root.querySelector('[role="alert"]')).toBe(alert);
    expect(alert.lang).toBe(language === 'tr' ? 'en' : 'tr');
    expect(alert.textContent).toContain(language === 'tr' ? 'No automatic retry' : 'Otomatik yeniden deneme yoktur');
    expect(component.error()).toBe(english); expect(input.value).toBe('US');
    expect(root.querySelector('form')).toBe(form); expect(document.activeElement).toBe(input);
    expect(api.requests).toHaveLength(count);
    const rejected = api.result(10); rejected.status = 429; rejected.body['code'] = '<quota>&Unicode-İ';
    api.pending = Promise.resolve(rejected); submit(harness); await Promise.resolve(); harness.detectChanges();
    expect(component.error()).toContain('(<quota>&Unicode-İ)');
    expect(alert.textContent).toContain('(<quota>&Unicode-İ)'); expect(alert.querySelector('quota')).toBeNull();
    api.pending = Promise.reject(new Error('private provider error'));
    submit(harness); await Promise.resolve(); harness.detectChanges();
    expect(alert.textContent).toContain(language === 'tr' ? 'Request outcome unavailable' : 'İstek sonucu kullanılamıyor');
    expect(alert.textContent).not.toContain('<quota>'); expect(alert.textContent).not.toContain('private provider error');
  });
  it('keeps invalid unavailable preferences and fresh production YouTube English without searching', async () => {
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    const preference = vi.spyOn(api, 'productLanguage');
    try {
      for (const mode of ['invalid', 'incompatible', 'signed-out', 'unavailable', 'production'] as const) {
        TestBed.resetTestingModule();
        buildEnvironment.production = mode === 'production';
        if (mode === 'unavailable') preference.mockRejectedValue(new Error('private preference error'));
        else preference.mockResolvedValue(mode === 'signed-out' ? { status: 401, body: {} } : { status: 200, body: {
          language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: mode === 'incompatible' ? 'tr' : 'en', current_email_language: 'en' } });
        TestBed.configureTestingModule({ providers: [provideRouter([
          { path: 'youtube/:organizationId/:projectId', component: ProjectYouTube },
        ]), { provide: AccountApi, useValue: api }] });
        const { harness, component } = await screen();
        await harness.fixture.whenStable(); harness.detectChanges();
        expect(TestBed.inject(Title).getTitle()).toBe('Separate YouTube public-video search — OrganicSEOOps');
        expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe('YouTube public-video search');
        expect(harness.routeNativeElement!.textContent).not.toContain('private preference error');
        expect(harness.routeNativeElement!.textContent).not.toContain('incelenmemiş Türkçe');
        if (mode === 'production') expect(component.productLanguage()).toBe('tr');
        expect(api.requests).toEqual([]);
        if (mode === 'production') {
          api.pending = Promise.resolve({ status: 429, body: { code: 'quota_exhausted' } });
          submit(harness); await Promise.resolve(); harness.detectChanges();
          const alert = harness.routeNativeElement!.querySelector<HTMLParagraphElement>('[role="alert"]')!;
          expect(alert.lang).toBe('en');
          expect(alert.textContent).toBe('YouTube search unavailable (quota_exhausted). No automatic retry; no result retained.');
        }
        harness.fixture.destroy();
      }
    } finally { buildEnvironment.production = production; }
  });
});
