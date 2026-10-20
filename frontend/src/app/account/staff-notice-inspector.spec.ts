import { TestBed } from '@angular/core/testing';
import { AccountApi, ApiResult } from './account-api';
import { environment } from '../../environments/environment';
import { StaffNoticeInspector } from './staff-notice-inspector';

function body(): Record<string, unknown> {
  return { method_version: 'scoped-staff-organization-notice-v1', organization_id: 7,
    scope: 'recorded_transport_not_inbox_delivery_current_eligibility_reissue_billing_or_account_mail_authority', source_digest: 'a'.repeat(64),
    notice: { id: 17, kind: 'trial_ending', state: 'unknown', manual_retries: 0,
      created_at: '2026-01-01T00:00:00.000001+00:00', attempted_at: '2026-01-01T00:00:00.000002+00:00', sent_at: null } };
}

describe('StaffNoticeInspector', () => {
  let result: ApiResult, pending: Promise<ApiResult> | null;
  let calls: unknown[][]; let language: 'en' | 'tr';
  beforeEach(() => {
    result = { status: 200, body: body() }; pending = null; calls = []; language = 'en';
    TestBed.configureTestingModule({ providers: [{ provide: AccountApi, useValue: {
      productLanguage: () => Promise.resolve({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } }),
      inspectPlatformNotice: (...args: unknown[]) => { calls.push(args); return pending ?? Promise.resolve(result); },
    } }] });
  });
  function create() {
    const fixture = TestBed.createComponent(StaffNoticeInspector); fixture.detectChanges();
    fixture.componentInstance.edit('organization', '7'); fixture.componentInstance.edit('notice', '17');
    return fixture;
  }
  it.each(['en', 'tr'] as const)('makes only an explicit scoped inspection, clones original microseconds and shows inert transport history in %s', async (selectedLanguage) => {
    language = selectedLanguage;
    const fixture = create(), component = fixture.componentInstance;
    await fixture.whenStable(); fixture.detectChanges();
    expect(calls).toEqual([]);
    fixture.nativeElement.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await fixture.whenStable(); fixture.detectChanges();
    expect(calls).toEqual([[7, 17, 'investigation']]);
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Bildirim 17' : 'Notice 17');
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'gelen kutusuna teslim' : 'not inbox delivery');
    expect(component.inspection()?.notice.created_at).toContain('.000001');
    expect(fixture.nativeElement.querySelector('section').getAttribute('lang')).toBe(language);
    expect(fixture.nativeElement.querySelector('label[for="notice-inspect-reason"]').textContent).toBe(language === 'tr' ? 'Kategorik inceleme nedeni' : 'Categorical investigation reason');
    expect(fixture.nativeElement.querySelector('option[value="customer_request"]').textContent).toBe(language === 'tr' ? 'Müşteri talebi' : 'Customer request');
    expect([...fixture.nativeElement.querySelectorAll('span[lang="en"]')].map((node: unknown) => (node as HTMLElement).textContent)).toEqual(expect.arrayContaining(['trial_ending', 'unknown', '2026-01-01T00:00:00.000001+00:00']));
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Kayıtlı kabul yok' : 'No recorded acceptance');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
    expect(calls).toHaveLength(1); expect(component.inspection()?.notice.state).toBe('unknown');
    component.productLanguage.set(language); fixture.detectChanges();
    (result.body['notice'] as Record<string, unknown>)['state'] = 'private marker';
    expect(component.inspection()?.notice.state).toBe('unknown');
    component.edit('notice', '18'); fixture.detectChanges();
    expect(component.inspection()).toBeNull(); expect(fixture.nativeElement.textContent).not.toContain(language === 'tr' ? 'Bildirim 17' : 'Notice 17');
  });
  it('rejects unsafe scope, extra fields, raw categories, invalid dates, shapes and mismatched original IDs', async () => {
    const fixture = create(), component = fixture.componentInstance;
    for (const id of ['0', '-1', '1.5', '9007199254740992', 'NaN', '01']) {
      component.edit('notice', id); await component.inspect(); expect(component.inspection()).toBeNull();
    }
    expect(calls).toEqual([]); component.edit('notice', '17');
    const original = body(), row = original['notice'] as Record<string, unknown>;
    const bad = [{ ...original, organization_id: 8 }, { ...original, extra: 'private marker' },
      { ...original, source_digest: 'bad' }, ...[
        { id: 18 }, { state: '<img src=x onerror=alert(1)>' }, { kind: 'private marker' }, { manual_retries: true },
        { manual_retries: 2 }, { created_at: '2026-02-30T00:00:00Z' }, { created_at: '9999-01-01T00:00:00Z' },
        { created_at: '2026-01-01T00:00:00+01:00' }, { attempted_at: '2026-01-01T00:00:00.000000Z' },
        { state: 'queued' }, { state: 'sent' }, { sent_at: '2026-01-01T00:00:00.000001Z' }, { error_category: 'raw secret' },
      ].map(change => ({ ...original, notice: { ...row, ...change } }))];
    for (const payload of bad) {
      result = { status: 200, body: payload }; await component.inspect(); fixture.detectChanges();
      expect(component.inspection()).toBeNull(); expect(fixture.nativeElement.querySelector('img')).toBeNull();
      expect(fixture.nativeElement.textContent).not.toContain('private marker');
    }
    result = { status: 403, body: { message: 'raw secret' } }; await component.inspect();
    expect(component.error()).not.toContain('raw secret');
  });
  it('clears late responses after scope or reason edits, overlapping refresh and destruction', async () => {
    for (const action of ['scope', 'reason', 'overlap', 'destroy']) {
      const fixture = create(), component = fixture.componentInstance;
      let resolve!: (value: ApiResult) => void;
      pending = new Promise<ApiResult>(done => resolve = done);
      const initial = component.inspect();
      if (action === 'scope') component.edit('organization', '8');
      if (action === 'reason') component.edit('reason', 'customer_request');
      if (action === 'destroy') fixture.destroy();
      if (action === 'overlap') {
        pending = null; result = { status: 409, body: {} }; await component.inspect();
      }
      resolve({ status: 200, body: body() }); await initial;
      expect(component.inspection()).toBeNull(); expect(component.busy()).toBe(false); pending = null;
      if (action !== 'destroy') fixture.destroy();
    }
  });
  it('keeps invalid or unavailable notice-inspector preference and fresh production English', async () => {
    const api = TestBed.inject(AccountApi), preference = vi.spyOn(api, 'productLanguage');
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    try {
      for (const body of [{}, { language: ['tr'], current_ui_language: 'en', current_email_language: 'en' },
        { language: 'tr', current_ui_language: 'tr', current_email_language: 'tr' }]) {
        preference.mockResolvedValue({ status: 200, body });
        const fixture = create(); await fixture.whenStable(); fixture.detectChanges();
        expect(fixture.componentInstance.productLanguage()).toBe('en');
        expect(fixture.nativeElement.querySelector('section').getAttribute('lang')).toBe('en'); fixture.destroy();
      }
      preference.mockRejectedValue(new Error('private preference error'));
      const failed = create(); await failed.whenStable(); failed.detectChanges();
      expect(failed.componentInstance.productLanguage()).toBe('en'); expect(failed.nativeElement.textContent).not.toContain('private preference error'); failed.destroy();
      buildEnvironment.production = true;
      preference.mockResolvedValue({ status: 200, body: { language: 'tr', current_ui_language: 'en', current_email_language: 'en' } });
      const fixture = create(); await fixture.whenStable(); fixture.detectChanges();
      expect(fixture.componentInstance.productLanguage()).toBe('tr');
      expect(fixture.nativeElement.querySelector('section').getAttribute('lang')).toBe('en');
      expect(fixture.nativeElement.querySelector('h3').textContent).toBe('Inspect exact organization notice transport');
      expect(calls).toEqual([]); fixture.destroy();
    } finally { buildEnvironment.production = production; preference.mockRestore(); }
  });

  it('uses the fixed CSRF-capable AccountApi POST rather than legacy global discovery', async () => {
    const fetcher = vi.fn().mockResolvedValue({ status: 200, json: () => Promise.resolve(body()) });
    const api = new AccountApi({ cookie: 'csrftoken=fixture-csrf', defaultView: { fetch: fetcher } } as unknown as Document);
    await api.inspectPlatformNotice(7, 17, 'investigation');
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher).toHaveBeenNthCalledWith(2, '/api/platform/notices/inspect/', {
      method: 'POST', headers: { 'X-CSRFToken': 'fixture-csrf', 'Content-Type': 'application/json' },
      body: JSON.stringify({ organization_id: 7, notice_id: 17, reason: 'investigation' }), credentials: 'same-origin', cache: 'no-store',
    });
  });
});
