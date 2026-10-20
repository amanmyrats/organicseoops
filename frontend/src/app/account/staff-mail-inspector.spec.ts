import { TestBed } from '@angular/core/testing';
import { AccountApi, ApiResult } from './account-api';
import { environment } from '../../environments/environment';
import { StaffMailInspector } from './staff-mail-inspector';

function body(): Record<string, unknown> {
  return { method_version: 'scoped-staff-current-account-mail-v1', user_id: 7, email_address_id: 9,
    scope: 'current_record_linkage_not_original_recipient_purpose_inbox_current_suppression_or_resend_authority', source_digest: 'a'.repeat(64),
    delivery: { id: 21, state: 'unknown', attempted_at: '2026-01-01T00:00:00.000001+00:00', finished_at: '2026-01-01T00:00:00.000002+00:00' } };
}

describe('StaffMailInspector', () => {
  let result: ApiResult, pending: Promise<ApiResult> | null;
  let calls: unknown[][]; let language: 'en' | 'tr';
  beforeEach(() => {
    result = { status: 200, body: body() }; pending = null; calls = []; language = 'en';
    TestBed.configureTestingModule({ providers: [{ provide: AccountApi, useValue: {
      productLanguage: () => Promise.resolve({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } }),
      inspectPlatformAccountMail: (...args: unknown[]) => { calls.push(args); return pending ?? Promise.resolve(result); },
    } }] });
  });
  function create() {
    const fixture = TestBed.createComponent(StaffMailInspector); fixture.detectChanges();
    fixture.componentInstance.edit('user', '7'); fixture.componentInstance.edit('address', '9'); fixture.componentInstance.edit('delivery', '21');
    return fixture;
  }
  it.each(['en', 'tr'] as const)('requests only deliberate exact current linkage and preserves original transport dates without replay in %s', async (selectedLanguage) => {
    language = selectedLanguage;
    const fixture = create(), component = fixture.componentInstance;
    await fixture.whenStable(); fixture.detectChanges();
    expect(calls).toEqual([]);
    fixture.nativeElement.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await fixture.whenStable(); fixture.detectChanges();
    expect(calls).toEqual([[7, 9, 21, 'investigation']]);
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Gönderim 21' : 'Delivery 21');
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'özgün alıcının veya mesaj amacının kanıtı değildir' : 'not proof of the original recipient');
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'burada yeniden kullanılamaz' : 'cannot be replayed');
    expect(component.inspection()?.delivery.attempted_at).toContain('.000001');
    expect(fixture.nativeElement.querySelector('section').getAttribute('lang')).toBe(language);
    expect(fixture.nativeElement.querySelector('label[for="mail-inspect-reason"]').textContent).toBe(language === 'tr' ? 'Kategorik inceleme nedeni' : 'Categorical investigation reason');
    expect(fixture.nativeElement.querySelector('option[value="customer_request"]').textContent).toBe(language === 'tr' ? 'Müşteri talebi' : 'Customer request');
    expect([...fixture.nativeElement.querySelectorAll('span[lang="en"]')].map((node: unknown) => (node as HTMLElement).textContent)).toEqual(['unknown', '2026-01-01T00:00:00.000001+00:00', '2026-01-01T00:00:00.000002+00:00']);
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'kısıtlıdır; silinmiş değildir' : 'restricted, not erased');
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'engellenmiş gönderim kaydı güncel engellemenin kanıtı değildir' : 'a suppressed record does not prove current suppression');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
    expect(calls).toHaveLength(1); expect(component.inspection()?.delivery.state).toBe('unknown');
    component.productLanguage.set(language); fixture.detectChanges();
    (result.body['delivery'] as Record<string, unknown>)['state'] = 'private marker';
    expect(component.inspection()?.delivery.state).toBe('unknown');
    component.edit('address', '10'); fixture.detectChanges();
    expect(component.inspection()).toBeNull(); expect(fixture.nativeElement.textContent).not.toContain(language === 'tr' ? 'Gönderim 21' : 'Delivery 21');
    for (const state of ['attempted', 'transport_returned', 'suppressed']) {
      component.edit('address', '9'); result = { status: 200, body: body() };
      Object.assign(result.body['delivery'] as object, { state, finished_at: state === 'attempted' ? null : '2026-01-01T00:00:00.000002Z' });
      await component.inspect(); fixture.detectChanges(); expect(component.inspection()?.delivery.state).toBe(state);
      if (state === 'attempted') expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Kayıtlı bitiş yok' : 'No recorded finish');
    }
  });
  it('denies unsafe scope, extra purpose, mismatched IDs, raw states and invalid original date/null shape', async () => {
    const fixture = create(), component = fixture.componentInstance;
    for (const id of ['0', '-1', '1.5', '9007199254740992', 'NaN', '01']) {
      component.edit('delivery', id); await component.inspect(); expect(component.inspection()).toBeNull();
    }
    expect(calls).toEqual([]); component.edit('delivery', '21');
    const original = body(), row = original['delivery'] as Record<string, unknown>;
    const bad = [{ ...original, user_id: 8 }, { ...original, email_address_id: 10 }, { ...original, extra: 'private marker' },
      { ...original, source_digest: 'bad' }, ...[
        { id: 22 }, { state: '<img src=x onerror=alert(1)>' }, { purpose: 'private marker' },
        { attempted_at: '2026-02-30T00:00:00Z' }, { attempted_at: '9999-01-01T00:00:00Z' },
        { attempted_at: '2026-01-01T00:00:00+01:00' }, { finished_at: '2026-01-01T00:00:00.000000Z' },
        { state: 'attempted' }, { finished_at: null }, { finished_at: '9999-01-01T00:00:00Z' },
      ].map(change => ({ ...original, delivery: { ...row, ...change } }))];
    for (const payload of bad) {
      result = { status: 200, body: payload }; await component.inspect(); fixture.detectChanges();
      expect(component.inspection()).toBeNull(); expect(fixture.nativeElement.querySelector('img')).toBeNull();
      expect(fixture.nativeElement.textContent).not.toContain('private marker');
    }
    result = { status: 403, body: { message: 'raw secret' } }; await component.inspect();
    expect(component.error()).not.toContain('raw secret');
  });
  it('clears late original responses on every scope/reason edit, overlapping refresh and destroy', async () => {
    for (const action of ['user', 'address', 'delivery', 'reason', 'overlap', 'destroy']) {
      const fixture = create(), component = fixture.componentInstance;
      let resolve!: (value: ApiResult) => void;
      pending = new Promise<ApiResult>(done => resolve = done); const initial = component.inspect();
      if (action === 'user') component.edit('user', '8');
      if (action === 'address') component.edit('address', '10');
      if (action === 'delivery') component.edit('delivery', '22');
      if (action === 'reason') component.edit('reason', 'customer_request');
      if (action === 'destroy') fixture.destroy();
      if (action === 'overlap') { pending = null; result = { status: 409, body: {} }; await component.inspect(); }
      resolve({ status: 200, body: body() }); await initial;
      expect(component.inspection()).toBeNull(); expect(component.busy()).toBe(false); pending = null;
      if (action !== 'destroy') fixture.destroy();
    }
  });
  it('keeps invalid or unavailable account-mail inspector preference and fresh production English', async () => {
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
      expect(fixture.nativeElement.querySelector('h3').textContent).toBe('Inspect exact current account-mail record');
      expect(calls).toEqual([]); fixture.destroy();
    } finally { buildEnvironment.production = production; preference.mockRestore(); }
  });

  it('uses the fixed private CSRF AccountApi POST and never global GET discovery', async () => {
    const fetcher = vi.fn().mockResolvedValue({ status: 200, json: () => Promise.resolve(body()) });
    const api = new AccountApi({ cookie: 'csrftoken=fixture-csrf', defaultView: { fetch: fetcher } } as unknown as Document);
    await api.inspectPlatformAccountMail(7, 9, 21, 'investigation');
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher).toHaveBeenNthCalledWith(2, '/api/platform/email/deliveries/inspect/', {
      method: 'POST', headers: { 'X-CSRFToken': 'fixture-csrf', 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: 7, email_address_id: 9, delivery_id: 21, reason: 'investigation' }), credentials: 'same-origin', cache: 'no-store',
    });
  });
});
