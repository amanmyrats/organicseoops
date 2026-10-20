import { TestBed } from '@angular/core/testing';
import { AccountApi } from './account-api';
import { vi } from 'vitest';
import { environment } from '../../environments/environment';
import { YouTubeSettings } from './youtube-settings';

describe('Dedicated YouTube staff settings', () => {
  it.each(['en', 'tr'] as const)('rejects non-scalar configuration states and withholds key controls and metadata in %s', async (language) => {
    let state: unknown = 'active';
    const api = { productLanguage: async () => ({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } }), platformYouTubeKey: async () => ({ status: 200,
      body: { state, api_project: 'client-project', daily_limit: 5 } }) };
    TestBed.configureTestingModule({ providers: [{ provide: AccountApi, useValue: api }] });
    const fixture = TestBed.createComponent(YouTubeSettings); fixture.detectChanges();
    await fixture.whenStable(); fixture.detectChanges();
    expect(fixture.componentInstance.state()).toBe('active');
    for (const value of ['active', 'revoked', 'unconfigured']) {
      state = [value];
      await fixture.componentInstance.load(); fixture.detectChanges();
      expect(fixture.componentInstance.state()).toBe('denied');
      expect(fixture.componentInstance.project()).toBe('');
      expect(fixture.componentInstance.limit()).toBeNull();
      expect(fixture.nativeElement.querySelector('form')).toBeNull();
      expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'ayarları kullanılamıyor' : 'settings unavailable');
      state = value;
      await fixture.componentInstance.load(); fixture.detectChanges();
      expect(fixture.componentInstance.state()).toBe(value);
      expect(fixture.componentInstance.project()).toBe('client-project');
      expect(fixture.nativeElement.querySelector('section').getAttribute('lang')).toBe(language);
      expect(fixture.nativeElement.querySelector('span[lang="en"]').textContent).toBe(value);
    }
  });

  it.each(['en', 'tr'] as const)('keeps the client project immutable and clears attempted secrets with native revoke confirmation in %s', async (language) => {
    const saved: Record<string, unknown>[] = []; let allowSave = false; let revoked = false; let removals = 0;
    const api = { productLanguage: async () => ({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } }), platformYouTubeKey: async (method = 'GET', data?: Record<string, unknown>) => {
      if (method === 'POST') { saved.push(data!); return allowSave ? { status: 200, body: { configured: true } } : { status: 403, body: {} }; }
      if (method === 'DELETE') { removals++; revoked = true; return { status: 200, body: {} }; }
      return { status: 200, body: { state: revoked ? 'revoked' : 'active', api_project: 'client-project', daily_limit: 5 } };
    } };
    TestBed.configureTestingModule({ providers: [{ provide: AccountApi, useValue: api }] });
    const fixture = TestBed.createComponent(YouTubeSettings); fixture.detectChanges();
    await Promise.resolve(); fixture.detectChanges();
    const form = fixture.nativeElement.querySelector('form') as HTMLFormElement;
    const key = form.elements.namedItem('api_key') as HTMLInputElement;
    const project = form.elements.namedItem('api_project') as HTMLInputElement;
    expect(project.readOnly).toBe(true); expect(project.value).toBe('client-project');
    key.value = 'fixture_dedicated_youtube_key';
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await Promise.resolve(); fixture.detectChanges();
    expect(saved[0]['api_project']).toBe('client-project'); expect(key.value).toBe('');
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Güncel MFA' : 'current MFA');
    expect(project.getAttribute('lang')).toBe('en');
    expect(fixture.nativeElement.querySelector('label[for="youtube-api-key"]').textContent).toContain(language === 'tr' ? 'yalnızca yazılır' : 'write-only');
    allowSave = true; key.value = 'fixture_replacement_key';
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(fixture.componentInstance.busy()).toBe(false)); fixture.detectChanges();
    expect(key.value).toBe(''); expect(saved).toHaveLength(2); expect(saved[1]['api_project']).toBe('client-project');
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Sağlayıcının hazır olduğu doğrulanmamıştır' : 'Provider readiness remains unverified');
    expect(fixture.nativeElement.textContent).not.toContain('fixture_replacement_key');
    const button = (text: string) => [...fixture.nativeElement.querySelectorAll('button')].find((node: unknown) => (node as HTMLButtonElement).textContent === text) as HTMLButtonElement;
    button(language === 'tr' ? 'YouTube anahtarını iptal edin' : 'Revoke YouTube key').click(); fixture.detectChanges();
    expect(removals).toBe(0);
    expect(fixture.nativeElement.querySelector('[role="alert"]').textContent).toContain(language === 'tr' ? 'gelecekteki YouTube aramaları engellensin' : 'block future YouTube searches');
    button(language === 'tr' ? 'İptal' : 'Cancel').click(); fixture.detectChanges(); expect(removals).toBe(0);
    button(language === 'tr' ? 'YouTube anahtarını iptal edin' : 'Revoke YouTube key').click(); fixture.detectChanges();
    button(language === 'tr' ? 'YouTube anahtarı iptalini onaylayın' : 'Confirm YouTube revoke').click();
    await vi.waitFor(() => expect(fixture.componentInstance.state()).toBe('revoked')); fixture.detectChanges();
    expect(removals).toBe(1); expect(fixture.componentInstance.project()).toBe('client-project'); expect(fixture.componentInstance.limit()).toBe(5);
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Günlük kullanım ve API projesi kimliği korundu' : 'Daily usage and API project identity retained');
  });
  it('retains the latest YouTube-key refresh when an older response succeeds or fails later', async () => {
    let response: Promise<{ status: number; body: Record<string, unknown> }> = Promise.resolve({ status: 200,
      body: { state: 'active', api_project: 'client-project', daily_limit: 5 } });
    const api = { productLanguage: async () => ({ status: 200, body: { language: 'en', current_ui_language: 'en', current_email_language: 'en' } }),
      platformYouTubeKey: () => response };
    TestBed.configureTestingModule({ providers: [{ provide: AccountApi, useValue: api }] });
    const fixture = TestBed.createComponent(YouTubeSettings); fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
    for (const outcome of ['success', 'failure']) {
      let complete!: (value: { status: number; body: Record<string, unknown> }) => void, fail!: (reason: Error) => void;
      response = new Promise((resolve, reject) => { complete = resolve; fail = reject; });
      const stale = fixture.componentInstance.load();
      response = Promise.resolve({ status: 200, body: { state: 'revoked', api_project: 'client-project', daily_limit: 9 } });
      await fixture.componentInstance.load(); fixture.detectChanges();
      if (outcome === 'success') complete({ status: 200, body: { state: 'active', api_project: 'client-project', daily_limit: 5 } });
      else fail(new Error('private outdated transport detail'));
      await stale; fixture.detectChanges();
      expect(fixture.componentInstance.state()).toBe('revoked'); expect(fixture.componentInstance.limit()).toBe(9);
      expect(fixture.nativeElement.querySelector('span[lang="en"]').textContent).toBe('revoked');
      expect(fixture.nativeElement.textContent).not.toContain('private outdated transport detail');
    }
  });

  it('keeps staff YouTube-key invalid preferences and fresh production English', async () => {
    const api = { productLanguage: vi.fn(), platformYouTubeKey: vi.fn(async () => ({ status: 403, body: {} })) };
    TestBed.configureTestingModule({ providers: [{ provide: AccountApi, useValue: api }] });
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    try {
      for (const body of [{}, { language: ['tr'], current_ui_language: 'en', current_email_language: 'en' },
        { language: 'tr', current_ui_language: 'tr', current_email_language: 'tr' }]) {
        api.productLanguage.mockResolvedValue({ status: 200, body });
        const fixture = TestBed.createComponent(YouTubeSettings); fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
        expect(fixture.componentInstance.productLanguage()).toBe('en');
        expect(fixture.nativeElement.querySelector('section').getAttribute('lang')).toBe('en'); fixture.destroy();
      }
      api.productLanguage.mockRejectedValue(new Error('private language error'));
      const failed = TestBed.createComponent(YouTubeSettings); failed.detectChanges(); await failed.whenStable(); failed.detectChanges();
      expect(failed.componentInstance.productLanguage()).toBe('en'); expect(failed.nativeElement.textContent).not.toContain('private language error'); failed.destroy();
      buildEnvironment.production = true;
      api.productLanguage.mockResolvedValue({ status: 200, body: { language: 'tr', current_ui_language: 'en', current_email_language: 'en' } });
      const fixture = TestBed.createComponent(YouTubeSettings); fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
      expect(fixture.componentInstance.productLanguage()).toBe('tr');
      expect(fixture.nativeElement.querySelector('section').getAttribute('lang')).toBe('en');
      expect(fixture.nativeElement.querySelector('h2').textContent).toBe('Dedicated YouTube public-search key');
      expect(fixture.nativeElement.textContent).toContain('Check staff permissions and current MFA.'); fixture.destroy();
    } finally { buildEnvironment.production = production; }
  });
});
