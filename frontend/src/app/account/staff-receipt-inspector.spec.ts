import { TestBed } from '@angular/core/testing';
import { AccountApi, ApiResult } from './account-api';
import { environment } from '../../environments/environment';
import { StaffReceiptInspector } from './staff-receipt-inspector';

function body(): Record<string, unknown> {
  return { method_version: 'exact-staff-retained-paddle-receipt-v1',
    scope: 'retained_global_receipt_not_tenant_paid_truth_lifetime_attempts_or_retry_authority', source_digest: 'a'.repeat(64),
    receipt: { id: 42, environment: 'sandbox', state: 'failed', attempts: 1, error_category: 'timeout',
      received_at: '2026-01-01T00:00:00.000001+00:00', claimed_at: '2026-01-01T00:00:00.000002+00:00',
      retry_after: '9999-01-01T00:00:00+00:00', processed_at: null } };
}

describe('StaffReceiptInspector', () => {
  let result: ApiResult, pending: Promise<ApiResult> | null;
  let calls: unknown[][]; let language: 'en' | 'tr';
  beforeEach(() => {
    result = { status: 200, body: body() }; pending = null; calls = []; language = 'en';
    TestBed.configureTestingModule({ providers: [{ provide: AccountApi, useValue: {
      productLanguage: () => Promise.resolve({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } }),
      inspectPlatformPaddleReceipt: (...args: unknown[]) => { calls.push(args); return pending ?? Promise.resolve(result); },
    } }] });
  });
  function create() {
    const fixture = TestBed.createComponent(StaffReceiptInspector); fixture.detectChanges();
    fixture.componentInstance.edit('receipt', '42'); return fixture;
  }
  it.each(['en', 'tr'] as const)('only deliberately inspects exact receipt and preserves resettable state/future deadline meanings in %s', async (selectedLanguage) => {
    language = selectedLanguage;
    const fixture = create(), component = fixture.componentInstance;
    await fixture.whenStable(); fixture.detectChanges();
    expect(calls).toEqual([]);
    fixture.nativeElement.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await fixture.whenStable(); fixture.detectChanges();
    expect(calls).toEqual([[42, 'investigation']]);
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Kayıtlı alındı 42' : 'Recorded receipt 42');
    for (const explanation of language === 'tr'
      ? ['kuruluş sahipliği', 'işlemin değişiklik yapmadığı', 'toplam geçmiş deneme sayısı değildir', 'sağlayıcı olay zamanları değildir', 'güncel yeniden deneme uygunluğu değildir']
      : ['not organization ownership', 'Succeeded may be a no-op', 'not lifetime attempts', 'not provider occurrence times'])
      expect(fixture.nativeElement.textContent).toContain(explanation);
    expect(component.inspection()?.receipt.claimed_at).toContain('.000002');
    expect(fixture.nativeElement.querySelector('section').getAttribute('lang')).toBe(language);
    expect(fixture.nativeElement.querySelector('label[for="receipt-inspect-reason"]').textContent).toBe(language === 'tr' ? 'Kategorik inceleme nedeni' : 'Categorical investigation reason');
    expect(fixture.nativeElement.querySelector('option[value="customer_request"]').textContent).toBe(language === 'tr' ? 'Müşteri talebi' : 'Customer request');
    expect([...fixture.nativeElement.querySelectorAll('span[lang="en"]')].map((node: unknown) => (node as HTMLElement).textContent)).toEqual(['sandbox', 'failed', 'timeout', '2026-01-01T00:00:00.000001+00:00', '2026-01-01T00:00:00.000002+00:00', '9999-01-01T00:00:00+00:00']);
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Kayıtlı değil' : 'Not recorded');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
    expect(calls).toHaveLength(1); expect(component.inspection()?.receipt.error_category).toBe('timeout');
    component.productLanguage.set(language); fixture.detectChanges();
    (result.body['receipt'] as Record<string, unknown>)['error_category'] = 'private marker';
    expect(component.inspection()?.receipt.error_category).toBe('timeout');
    for (const state of ['pending', 'ignored', 'processing', 'succeeded', 'failed']) {
      const row = structuredClone(body()['receipt']) as Record<string, unknown>;
      Object.assign(row, { state, attempts: ['pending', 'ignored'].includes(state) ? 0 : 1,
        claimed_at: ['pending', 'ignored'].includes(state) ? null : row['claimed_at'], retry_after: null,
        processed_at: state === 'succeeded' ? '2026-01-01T00:00:00.000003+00:00' : null,
        error_category: state === 'failed' ? 'unclassified_failure' : null });
      result = { status: 200, body: { ...body(), receipt: row } };
      await component.inspect(); fixture.detectChanges(); expect(component.inspection()?.receipt.state).toBe(state);
      if (state !== 'failed') expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Kayıt yok' : 'None recorded');
    }
  });
  it('denies unsafe IDs/extras/raw categories and exact original state-null-calendar-microsecond date corruption', async () => {
    const fixture = create(), component = fixture.componentInstance;
    for (const id of ['0', '-1', '1.5', '9007199254740992', 'NaN', '01']) {
      component.edit('receipt', id); await component.inspect(); expect(component.inspection()).toBeNull();
    }
    expect(calls).toEqual([]); component.edit('receipt', '42');
    const original = body(), receipt = original['receipt'] as Record<string, unknown>;
    const bad = [{ ...original, extra: 'private marker' }, { ...original, method_version: 'wrong' },
      { ...original, source_digest: 'bad' }, { ...original, receipt: [] }, ...[
        { id: 43 }, { environment: 'other' }, { attempts: true }, { attempts: 4 }, { state: 'unknown' },
        { attempts: 0 }, { claimed_at: null }, { received_at: null }, { error_category: null },
        { error_category: '<img src=x onerror=alert(1)>' }, { event_id: 'private marker' },
        { received_at: '2026-02-30T00:00:00Z' }, { received_at: '9999-01-01T00:00:00Z' },
        { received_at: '2026-01-01T00:00:00+01:00' }, { claimed_at: '2026-01-01T00:00:00.000000Z' },
        { retry_after: '2026-01-01T00:00:00.000001Z' }, { processed_at: '2026-01-01T00:00:00.000003Z' },
        { state: 'succeeded', error_category: null, retry_after: null, processed_at: null },
        { state: 'succeeded', error_category: null, retry_after: null, processed_at: '2026-01-01T00:00:00.000001Z' },
        { state: 'succeeded', error_category: null, retry_after: null, processed_at: '9999-01-01T00:00:00Z' },
      ].map(change => ({ ...original, receipt: { ...receipt, ...change } }))];
    for (const payload of bad) {
      result = { status: 200, body: payload }; await component.inspect(); fixture.detectChanges();
      expect(component.inspection()).toBeNull(); expect(fixture.nativeElement.querySelector('img')).toBeNull();
      expect(fixture.nativeElement.textContent).not.toContain('private marker');
    }
    result = { status: 403, body: { message: 'raw secret' } }; await component.inspect(); expect(component.error()).not.toContain('raw secret');
  });
  it('clears late results on ID/reason edit, overlap, refresh/parent retry and destroy', async () => {
    for (const action of ['receipt', 'reason', 'overlap', 'clear', 'destroy']) {
      const fixture = create(), component = fixture.componentInstance;
      let resolve!: (value: ApiResult) => void;
      pending = new Promise<ApiResult>(done => resolve = done); const initial = component.inspect();
      if (action === 'receipt') component.edit('receipt', '43');
      if (action === 'reason') component.edit('reason', 'customer_request');
      if (action === 'clear') component.clear();
      if (action === 'destroy') fixture.destroy();
      if (action === 'overlap') { pending = null; result = { status: 409, body: {} }; await component.inspect(); }
      resolve({ status: 200, body: body() }); await initial;
      expect(component.inspection()).toBeNull(); expect(component.busy()).toBe(false); pending = null;
      if (action !== 'destroy') fixture.destroy();
    }
  });
  it('keeps invalid or unavailable billing-receipt inspector preference and fresh production English', async () => {
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
      expect(fixture.nativeElement.querySelector('h3').textContent).toBe('Inspect exact retained billing receipt');
      expect(calls).toEqual([]); fixture.destroy();
    } finally { buildEnvironment.production = production; preference.mockRestore(); }
  });

  it('uses the fixed private CSRF AccountApi POST without any provider/retry/discovery request', async () => {
    const fetcher = vi.fn().mockResolvedValue({ status: 200, json: () => Promise.resolve(body()) });
    const api = new AccountApi({ cookie: 'csrftoken=fixture-csrf', defaultView: { fetch: fetcher } } as unknown as Document);
    await api.inspectPlatformPaddleReceipt(42, 'investigation'); expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher).toHaveBeenNthCalledWith(2, '/api/platform/billing/paddle/receipts/inspect/', {
      method: 'POST', headers: { 'X-CSRFToken': 'fixture-csrf', 'Content-Type': 'application/json' },
      body: JSON.stringify({ receipt_id: 42, reason: 'investigation' }), credentials: 'same-origin', cache: 'no-store',
    });
  });
});
