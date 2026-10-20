import { TestBed } from '@angular/core/testing';
import { AccountApi, ApiResult } from './account-api';
import { environment } from '../../environments/environment';
import { StaffFeedbackInspector } from './staff-feedback-inspector';

function body(): Record<string, unknown> {
  return { method_version: 'scoped-staff-retained-email-feedback-v1', user_id: 7, email_address_id: 9,
    scope: 'current_record_first_feedback_not_original_recipient_provider_occurrence_current_applicability_or_clearance_authority', source_digest: 'a'.repeat(64),
    suppression: { id: 19, reason: 'permanent_bounce', created_at: '2026-01-01T00:00:00.000002+00:00' },
    feedback: { id: 21, kind: 'permanent_bounce', received_at: '2026-01-01T00:00:00.000001+00:00' } };
}

describe('StaffFeedbackInspector', () => {
  let result: ApiResult, pending: Promise<ApiResult> | null;
  let calls: unknown[][]; let language: 'en' | 'tr';
  beforeEach(() => {
    result = { status: 200, body: body() }; pending = null; calls = []; language = 'en';
    TestBed.configureTestingModule({ providers: [{ provide: AccountApi, useValue: {
      productLanguage: () => Promise.resolve({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } }),
      inspectPlatformEmailFeedback: (...args: unknown[]) => { calls.push(args); return pending ?? Promise.resolve(result); },
    } }] });
  });
  function create() {
    const fixture = TestBed.createComponent(StaffFeedbackInspector); fixture.detectChanges();
    fixture.componentInstance.edit('user', '7'); fixture.componentInstance.edit('address', '9'); fixture.componentInstance.edit('suppression', '19');
    return fixture;
  }
  it.each(['en', 'tr'] as const)('requests only deliberate exact linkage and preserves first receipt/local dates without clearance in %s', async (selectedLanguage) => {
    language = selectedLanguage;
    const fixture = create(), component = fixture.componentInstance;
    await fixture.whenStable(); fixture.detectChanges();
    expect(calls).toEqual([]);
    fixture.nativeElement.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await fixture.whenStable(); fixture.detectChanges();
    expect(calls).toEqual([[7, 9, 19, 'investigation']]);
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Engelleme 19' : 'Suppression 19');
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'özgün alıcının, sağlayıcı olayının' : 'not proof of the original recipient');
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'SES olay zamanları değildir' : 'not SES event times');
    expect(component.inspection()?.feedback.received_at).toContain('.000001');
    expect(fixture.nativeElement.querySelector('section').getAttribute('lang')).toBe(language);
    expect(fixture.nativeElement.querySelector('label[for="feedback-inspect-reason"]').textContent).toBe(language === 'tr' ? 'Kategorik inceleme nedeni' : 'Categorical investigation reason');
    expect(fixture.nativeElement.querySelector('option[value="customer_request"]').textContent).toBe(language === 'tr' ? 'Müşteri talebi' : 'Customer request');
    expect([...fixture.nativeElement.querySelectorAll('span[lang="en"]')].map((node: unknown) => (node as HTMLElement).textContent)).toEqual(['permanent_bounce', '2026-01-01T00:00:00.000002+00:00', 'permanent_bounce', '2026-01-01T00:00:00.000001+00:00']);
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'ilk bağlantılı alındı kaydının yerini almaz' : 'does not replace the first linked receipt');
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'kısıtlıdır; silinmiş değildir' : 'restricted, not erased');
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'ayrı izin gerektirir' : 'separately permitted');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
    expect(calls).toHaveLength(1); expect(component.inspection()?.feedback.kind).toBe('permanent_bounce');
    component.productLanguage.set(language); fixture.detectChanges();
    (result.body['feedback'] as Record<string, unknown>)['kind'] = 'private marker';
    expect(component.inspection()?.feedback.kind).toBe('permanent_bounce');
    component.edit('address', '10'); fixture.detectChanges();
    expect(component.inspection()).toBeNull(); expect(fixture.nativeElement.textContent).not.toContain(language === 'tr' ? 'Engelleme 19' : 'Suppression 19');
    component.edit('address', '9'); result = { status: 200, body: body() };
    Object.assign(result.body['suppression'] as object, { reason: 'complaint' });
    Object.assign(result.body['feedback'] as object, { kind: 'complaint' });
    await component.inspect(); expect(component.inspection()?.feedback.kind).toBe('complaint');
  });
  it('denies unsafe scope, extra payloads, mismatch, raw kinds and invalid original UTC microsecond date order', async () => {
    const fixture = create(), component = fixture.componentInstance;
    for (const id of ['0', '-1', '1.5', '9007199254740992', 'NaN', '01']) {
      component.edit('suppression', id); await component.inspect(); expect(component.inspection()).toBeNull();
    }
    expect(calls).toEqual([]); component.edit('suppression', '19');
    const original = body(), suppression = original['suppression'] as Record<string, unknown>, feedback = original['feedback'] as Record<string, unknown>;
    const bad = [{ ...original, user_id: 8 }, { ...original, email_address_id: 10 }, { ...original, extra: 'private marker' },
      { ...original, source_digest: 'bad' }, { ...original, feedback: [] }, ...[
        { id: 20 }, { reason: '<img src=x onerror=alert(1)>' }, { address: 'private marker' },
        { created_at: '2026-02-30T00:00:00Z' }, { created_at: '9999-01-01T00:00:00Z' },
        { created_at: '2026-01-01T00:00:00+01:00' }, { created_at: '2026-01-01T00:00:00.000000Z' },
      ].map(change => ({ ...original, suppression: { ...suppression, ...change } })), ...[
        { id: true }, { id: 0 }, { id: 2 ** 53 }, { kind: 'complaint' }, { event_id: 'private marker' },
        { received_at: null }, { received_at: '2026-01-01T00:00:00.000003Z' }, { received_at: '2026-02-30T00:00:00Z' },
      ].map(change => ({ ...original, feedback: { ...feedback, ...change } }))];
    for (const payload of bad) {
      result = { status: 200, body: payload }; await component.inspect(); fixture.detectChanges();
      expect(component.inspection()).toBeNull(); expect(fixture.nativeElement.querySelector('img')).toBeNull();
      expect(fixture.nativeElement.textContent).not.toContain('private marker');
    }
    result = { status: 403, body: { message: 'raw secret' } }; await component.inspect();
    expect(component.error()).not.toContain('raw secret');
  });
  it('clears late results on every scope/reason edit, overlap, parent clearance and destroy', async () => {
    for (const action of ['user', 'address', 'suppression', 'reason', 'overlap', 'clear', 'destroy']) {
      const fixture = create(), component = fixture.componentInstance;
      let resolve!: (value: ApiResult) => void;
      pending = new Promise<ApiResult>(done => resolve = done); const initial = component.inspect();
      if (action === 'user') component.edit('user', '8');
      if (action === 'address') component.edit('address', '10');
      if (action === 'suppression') component.edit('suppression', '20');
      if (action === 'reason') component.edit('reason', 'customer_request');
      if (action === 'clear') component.clear();
      if (action === 'destroy') fixture.destroy();
      if (action === 'overlap') { pending = null; result = { status: 409, body: {} }; await component.inspect(); }
      resolve({ status: 200, body: body() }); await initial;
      expect(component.inspection()).toBeNull(); expect(component.busy()).toBe(false); pending = null;
      if (action !== 'destroy') fixture.destroy();
    }
  });
  it('keeps invalid or unavailable feedback inspector preference and fresh production English', async () => {
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
      expect(fixture.nativeElement.querySelector('h3').textContent).toBe('Inspect exact retained suppression and first feedback');
      expect(calls).toEqual([]); fixture.destroy();
    } finally { buildEnvironment.production = production; preference.mockRestore(); }
  });

  it('uses fixed private CSRF AccountApi POST and never global discovery', async () => {
    const fetcher = vi.fn().mockResolvedValue({ status: 200, json: () => Promise.resolve(body()) });
    const api = new AccountApi({ cookie: 'csrftoken=fixture-csrf', defaultView: { fetch: fetcher } } as unknown as Document);
    await api.inspectPlatformEmailFeedback(7, 9, 19, 'investigation');
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher).toHaveBeenNthCalledWith(2, '/api/platform/email/suppressions/inspect/', {
      method: 'POST', headers: { 'X-CSRFToken': 'fixture-csrf', 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: 7, email_address_id: 9, suppression_id: 19, reason: 'investigation' }), credentials: 'same-origin', cache: 'no-store',
    });
  });
});
