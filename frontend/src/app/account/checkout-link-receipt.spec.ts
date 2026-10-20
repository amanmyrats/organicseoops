import { createHash } from 'node:crypto';
import { TestBed } from '@angular/core/testing';
import { vi } from 'vitest';
import { AccountApi, ApiResult } from './account-api';
import { CheckoutLinkReceipt } from './checkout-link-receipt';
import { environment } from '../../environments/environment';

const LINK = `${window.location.origin}/account/billing/checkout?_ptxn=txn_${'c'.repeat(26)}`;
const ago = (seconds: number) => new Date(Date.now() - seconds * 1000).toISOString();
function source() {
  return { method: 'checkout-link-delivery-source-v1', organization_id: 7, actor_id: 1, attempt_id: 91,
    request_actor_id: 1, environment: 'sandbox', offer_version: 'agency-launch-v1', product_id: `pro_${'a'.repeat(26)}`,
    price_id: `pri_${'b'.repeat(26)}`, transaction_id: `txn_${'c'.repeat(26)}`, created_at: ago(120), sent_at: ago(100),
    seller_id: 4, seller_rotated_at: ago(180), checkout_url: LINK, payment_confirmed: false,
    interpretation: 'current_link_receipt_eligibility_not_delivered_link_or_provider_page_or_payment_proof' };
}
const hash = (value: Record<string, unknown>) => createHash('sha256')
  .update(JSON.stringify(Object.fromEntries(Object.keys(value).sort().map(key => [key, value[key]])))
    .replace(/[\u007f-\uffff]/g, char => `\\u${char.charCodeAt(0).toString(16).padStart(4, '0')}`)).digest('hex');
class ReceiptApi {
  original = source(); digest = hash(this.original); reads: number[][] = []; commands: (number | string)[][] = [];
  saved: Record<string, unknown> | null = null;
  current = true; lose = false; drop = false; readResult: ApiResult | null = null; wait: Promise<ApiResult> | null = null;
  challenge() { return { method: 'checkout-link-receipt-v1', source: structuredClone(this.original), source_digest: this.digest,
    proof: 'fixture:proof:signature', expires_at: new Date(Date.now() + 180000).toISOString() }; }
  result(org = 7, attempt = 91): ApiResult {
    return structuredClone({ status: 200, body: { method: 'checkout-link-receipt-v1', organization_id: org,
      attempt_id: attempt, payment_confirmed: false, receipt: this.saved, challenge: this.saved || !this.current ? null : this.challenge() } });
  }
  checkoutLinkReceipt(org: number, attempt: number): Promise<ApiResult> {
    this.reads.push([org, attempt]); return this.wait || Promise.resolve(this.readResult || this.result(org, attempt));
  }
  acknowledgeCheckoutLink(org: number, attempt: number, proof: string): Promise<ApiResult> {
    this.commands.push([org, attempt, proof]);
    const receipt = { method: 'checkout-link-receipt-v1', attempt_id: attempt, source_digest: this.digest,
      acknowledged_at: ago(1), state: 'acknowledged', payment_confirmed: false,
      interpretation: 'owner_browser_acknowledged_link_not_provider_page_or_payment_proof' };
    if (!this.drop) this.saved = receipt;
    return this.lose || this.drop ? Promise.reject(new Error('Unknown fixture response')) : Promise.resolve({ status: 200, body: receipt });
  }
}

describe('Prospective exact owner/browser checkout link receipt', () => {
  let api: ReceiptApi;
  beforeEach(() => { api = new ReceiptApi(); TestBed.configureTestingModule({ providers: [{ provide: AccountApi, useValue: api }] }); });
  afterEach(() => vi.useRealTimers());
  function screen(language: 'en' | 'tr' = 'en') {
    const fixture = TestBed.createComponent(CheckoutLinkReceipt);
    fixture.componentRef.setInput('organizationId', 7); fixture.componentRef.setInput('attemptId', 91);
    fixture.componentRef.setInput('checkoutUrl', LINK); fixture.componentRef.setInput('language', language); fixture.detectChanges();
    return { fixture, component: fixture.componentInstance };
  }
  it.each(['en', 'tr'] as const)('does no automatic read/acknowledgment, validates the exact dated digest/link and requires deliberate checkbox consent (%s)', async (language) => {
    const { fixture, component } = screen(language); expect(api.reads).toEqual([]); expect(api.commands).toEqual([]);
    await component.inspect(); fixture.detectChanges(); expect(api.reads).toEqual([[7, 91]]);
    expect(fixture.nativeElement.textContent).toContain(LINK); expect(fixture.nativeElement.textContent).toContain(api.digest);
    expect(fixture.nativeElement.textContent).not.toContain('fixture:proof:signature');
    expect(fixture.nativeElement.querySelectorAll('h2').length).toBe(1);
    expect(fixture.nativeElement.querySelector('section').getAttribute('lang')).toBe(language);
    expect(fixture.nativeElement.querySelector('section').getAttribute('aria-label')).toBe(language === 'tr' ? 'Ödeme bağlantısı alındısı' : 'Checkout link receipt');
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'ücretli erişimi veya ilk kez dönüşümü kanıtlamaz' : 'paid access or a first-ever conversion');
    const original = component.challenge();
    fixture.componentRef.setInput('language', language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
    expect(component.challenge()).toEqual(original); expect(api.reads).toEqual([[7, 91]]); expect(api.commands).toEqual([]);
    fixture.componentRef.setInput('language', language); fixture.detectChanges();
    expect([...fixture.nativeElement.querySelectorAll('[lang="en"]')].some((item: Element) => item.textContent === LINK)).toBe(true);
    await component.acknowledge(); expect(api.commands).toEqual([]);
    const consent = fixture.nativeElement.querySelector('input[type="checkbox"]') as HTMLInputElement;
    expect(consent.closest('label')!.textContent).toContain(language === 'tr' ? 'ilgili ödeme bağlantısını aldım' : 'exact application payment link');
    consent.checked = true; consent.dispatchEvent(new Event('change'));
    await component.acknowledge(); fixture.detectChanges();
    expect(api.commands).toEqual([[7, 91, 'fixture:proof:signature']]);
    expect(component.receipt()?.source_digest).toBe(api.digest); expect(component.challenge()).toBeNull();
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Hiçbir ödeme doğrulanmadı' : 'No payment is confirmed');
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Saklanan faturalandırma geçmişidir' : 'Retained billing history');
    const receipt = component.receipt(), reads = api.reads.length;
    const status = fixture.nativeElement.querySelector('p[role="status"][lang]') as HTMLParagraphElement;
    expect(component.message()).toBe('First browser link acknowledgment recorded. No payment is confirmed.');
    fixture.componentRef.setInput('language', language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('p[role="status"][lang]')).toBe(status);
    expect(status.lang).toBe(language === 'tr' ? 'en' : 'tr'); expect(status.textContent).toBe(component.t(component.message()));
    expect(component.receipt()).toBe(receipt); expect(api.reads).toHaveLength(reads); expect(api.commands).toHaveLength(1);

  });
  it('guards the receipt language with English default invalid and fresh production fallback', () => {
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    try {
      for (const mode of ['default', 'invalid', 'production'] as const) {
        buildEnvironment.production = mode === 'production';
        const { fixture } = screen(mode === 'production' ? 'tr' : 'en');
        if (mode === 'invalid') { fixture.componentRef.setInput('language', ['tr']); fixture.detectChanges(); }
        expect(fixture.nativeElement.querySelector('section').getAttribute('lang')).toBe('en');
        expect(fixture.nativeElement.textContent).toContain('Browser link receipt');
        expect(fixture.nativeElement.textContent).not.toContain('incelenmemiş Türkçe');
        expect(api.reads).toEqual([]); expect(api.commands).toEqual([]); fixture.destroy();
      }
    } finally { buildEnvironment.production = production; }
  });
  it('lost response with a recorded receipt is resolved by exact GET without acknowledgment replay', async () => {
    const { component } = screen(); await component.inspect(); component.consented.set(true); api.lose = true;
    await component.acknowledge(); expect(component.unknown()).toBe(true); expect(component.canRetry()).toBe(false);
    await component.acknowledge(true); expect(api.commands.length).toBe(1);
    await component.lookup(); expect(component.unknown()).toBe(false); expect(component.receipt()).not.toBeNull();
    expect(api.commands.length).toBe(1); expect(api.reads.every(pair => pair[0] === 7 && pair[1] === 91)).toBe(true);
  });
  it.each(['en', 'tr'] as const)('lost unrecorded acknowledgment permits only deliberate same-proof retry after exact lookup and fresh source recheck (%s)', async (language) => {
    const { fixture, component } = screen(language); await component.inspect(); component.consented.set(true); api.drop = true;
    await component.acknowledge(); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Ödeme isteği veya onay otomatik olarak tekrarlanmaz' : 'No payment request or acknowledgment is replayed automatically');
    expect(fixture.nativeElement.querySelector('[role="alert"]').textContent).toContain(language === 'tr' ? 'alındıyı sorgulayın' : 'Look up the exact saved receipt');
    const alert = fixture.nativeElement.querySelector('[role="alert"]') as HTMLParagraphElement;
    const reads = api.reads.length, challenge = component.challenge();
    expect(component.error()).toBe('Acknowledgment could not be confirmed. Look up the exact saved receipt before any deliberate retry.');
    fixture.componentRef.setInput('language', language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role="alert"]')).toBe(alert);
    expect(alert.textContent).toBe(component.t(component.error())); expect(alert.lang).toBe(language === 'tr' ? 'en' : 'tr');
    expect(component.challenge()).toBe(challenge); expect(component.unknown()).toBe(true); expect(component.canRetry()).toBe(false);
    expect(api.reads).toHaveLength(reads); expect(api.commands).toHaveLength(1);
    fixture.componentRef.setInput('language', language); fixture.detectChanges();

    await component.acknowledge(true); expect(api.commands.length).toBe(1);
    const lookup = [...fixture.nativeElement.querySelectorAll('button')].find((item: Element) => item.textContent === (language === 'tr' ? 'Bu onayın kaydını sorgula' : 'Look up this exact acknowledgment')) as HTMLButtonElement;
    lookup.click(); await vi.waitFor(() => expect(component.busy()).toBe(false)); fixture.detectChanges();
    expect(component.canRetry()).toBe(true); expect(api.commands.length).toBe(1);
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Süresi dolmamış aynı onay bilerek yeniden denenebilir' : 'same unexpired acknowledgment may be retried deliberately');
    const message = component.message(), lookupReads = api.reads.length;
    const status = fixture.nativeElement.querySelector('p[role="status"][lang]') as HTMLParagraphElement;
    fixture.componentRef.setInput('language', language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
    expect(status.textContent).toBe(component.t(message)); expect(component.message()).toBe(message); expect(component.canRetry()).toBe(true);
    expect(api.reads).toHaveLength(lookupReads); expect(api.commands).toHaveLength(1);
    fixture.componentRef.setInput('language', language); fixture.detectChanges();

    api.drop = false;
    const retry = [...fixture.nativeElement.querySelectorAll('button')].find((item: Element) => item.textContent === (language === 'tr' ? 'Sorgulamadan sonra süresi dolmamış aynı onayı yeniden dene' : 'Retry the same unexpired acknowledgment after lookup')) as HTMLButtonElement;
    retry.click(); await vi.waitFor(() => expect(component.busy()).toBe(false)); fixture.detectChanges();
    expect(api.commands).toEqual([[7, 91, 'fixture:proof:signature'], [7, 91, 'fixture:proof:signature']]);
    expect(component.unknown()).toBe(false); expect(component.receipt()).not.toBeNull();
  });
  it('foreign/malformed/digest/date/payment/link responses never become receipt sources or commands', async () => {
    const { component } = screen();
    const bad: ApiResult[] = [
      { ...api.result(), body: { ...api.result().body, organization_id: 999 } },
      { ...api.result(), body: { ...api.result().body, payment_confirmed: true } },
      { ...api.result(), body: { ...api.result().body, challenge: { ...api.challenge(), source_digest: 'a'.repeat(64) } } },
      { ...api.result(), body: { ...api.result().body, challenge: { ...api.challenge(), proof: 'x'.repeat(4097) } } },
    ];
    for (const edit of [{ actor_id: true }, { sent_at: 'no-date' }, { created_at: new Date(Date.now() + 60000).toISOString() },
      { checkout_url: LINK + '&foreign=1' }, { interpretation: '<script>bad</script>' }, { environment: 'other' },
      ...['environment', 'product_id', 'price_id', 'transaction_id'].map(key =>
        ({ [key]: [(api.original as Record<string, unknown>)[key]] }))]) {
      const changed = { ...api.original, ...edit };
      bad.push({ ...api.result(), body: { ...api.result().body, challenge: { ...api.challenge(), source: changed, source_digest: hash(changed) } } });
    }
    for (const result of bad) { api.readResult = result; await component.inspect();
      expect(component.challenge()).toBeNull(); expect(component.error()).not.toBe(''); }
    expect(api.commands).toEqual([]);
  });
  it('fresh role/source loss stops acknowledgment before POST and null-link paid history is read-only', async () => {
    const { fixture, component } = screen(); await component.inspect(); component.consented.set(true);
    api.current = false; await component.acknowledge(); expect(api.commands).toEqual([]); expect(component.challenge()).toBeNull();
    api.current = true; await component.inspect(); component.consented.set(true);
    api.original.actor_id = 2; api.digest = hash(api.original); await component.acknowledge(); expect(api.commands).toEqual([]);
    fixture.componentRef.setInput('checkoutUrl', null); fixture.detectChanges();
    await component.inspect(); expect(component.challenge()).toBeNull(); expect(api.commands).toEqual([]);
    api.saved = { method: 'checkout-link-receipt-v1', attempt_id: 91, source_digest: api.digest, acknowledged_at: ago(300),
      state: 'acknowledged', payment_confirmed: false, interpretation: 'owner_browser_acknowledged_link_not_provider_page_or_payment_proof' };
    await component.inspect(); expect(component.receipt()).not.toBeNull(); expect(component.challenge()).toBeNull();
  });
  it.each(['en', 'tr'] as const)('expiry clears proof eligibility and unknown lookup cannot replay an expired acknowledgment (%s)', async (language) => {
    vi.useFakeTimers(); const { fixture, component } = screen(language); await component.inspect(); component.consented.set(true); api.drop = true;
    await component.acknowledge(); const original = Date.now();
    vi.spyOn(Date, 'now').mockReturnValue(original + 301000);
    vi.advanceTimersByTime(301000); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Alındı kanıtının süresi doldu' : 'Receipt proof expired');
    await component.lookup(); expect(component.canRetry()).toBe(false); await component.acknowledge(true);
    expect(api.commands.length).toBe(1); vi.restoreAllMocks();
  });
  it('scope change and destruction clear source/unknown command and reject late reads', async () => {
    const { fixture, component } = screen(); await component.inspect(); component.consented.set(true); api.drop = true;
    await component.acknowledge(); expect(component.unknown()).toBe(true);
    let finish!: (value: ApiResult) => void; api.wait = new Promise(resolve => { finish = resolve; });
    const pending = component.lookup(); const old = api.result();
    fixture.componentRef.setInput('organizationId', 8); fixture.componentRef.setInput('attemptId', 92); fixture.detectChanges();
    finish(old); await pending; expect(component.unknown()).toBe(false); expect(component.challenge()).toBeNull(); expect(component.receipt()).toBeNull();
    api.wait = null; await component.acknowledge(true); expect(api.commands.length).toBe(1);
    api.wait = new Promise(resolve => { finish = resolve; }); const late = component.inspect(); fixture.destroy();
    finish(api.result(8, 92)); await late; expect(component.challenge()).toBeNull(); expect(component.receipt()).toBeNull();
  });
});
