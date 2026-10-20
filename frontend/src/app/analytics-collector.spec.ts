import { TestBed } from '@angular/core/testing';
import { NavigationEnd, provideRouter, Router } from '@angular/router';
import { Subject } from 'rxjs';
import { MockInstance, vi } from 'vitest';
import { ANALYTICS_CONSENT_VERSION, AnalyticsConsent, publicAnalyticsCandidate } from './analytics-consent';

const publication = () => {
  const row = { state: 'approved', editor: 'founder', publisher: 'founder', reviewer: 'Synthetic reviewer',
    reviewedAt: '2026-10-03T00:00:00Z', htmlSha256: 'a'.repeat(64),
    history: [{ reviewer: 'Synthetic reviewer', reviewedAt: '2026-10-03T00:00:00Z', htmlSha256: 'a'.repeat(64) }] };
  return { version: 1, routes: { '': { ...row, alternate: 'tr/' }, 'tr/': { ...row, alternate: '' } } };
};
const inventory = [{ path: '', id: 'HOME', locale: 'en' as const, ctaIds: ['public_trial_cta'] },
  { path: 'tr/', id: 'HOME', locale: 'tr' as const, ctaIds: ['public_trial_cta'] }];
const json = (body: unknown) => Promise.resolve({ ok: true, json: async () => body } as Response);
const issued = () => ({ method: 'public-consent-epoch-v1', consent_version: ANALYTICS_CONSENT_VERSION,
  receipt_proof: 'p'.repeat(43), expires_at: new Date(Date.now() + 15 * 60_000).toISOString(), policy_digest: 'a'.repeat(64) });

describe('Actual memory-only public consent collector', () => {
  afterEach(() => { TestBed.resetTestingModule(); vi.restoreAllMocks(); vi.useRealTimers(); });

  function setup() {
    TestBed.configureTestingModule({ providers: [provideRouter([])] });
    const navigation = new Subject<NavigationEnd>();
    vi.spyOn(TestBed.inject(Router), 'events', 'get').mockReturnValue(navigation);
    const consent = TestBed.inject(AnalyticsConsent);
    // Genuine pure approval fixtures enter the actual native consumer, never the real manifest.
    vi.spyOn(consent, 'candidate').mockImplementation(input => publicAnalyticsCandidate(consent.preference(), input, inventory, publication()));
    const fetch = vi.spyOn(window, 'fetch').mockImplementation((url, options) => {
      if (String(url).endsWith('/csrf/')) return json({ csrfToken: 'c'.repeat(64) });
      if (String(url).endsWith('/grant/')) return json(issued());
      if (String(url).endsWith('/withdraw/')) return json({ method: 'public-consent-epoch-v1', state: 'withdrawn' });
      const event = JSON.parse(String(options?.body)).candidate;
      return json({ method: 'public-observation-receipt-v1', state: 'recorded', event_id: event.event_id,
        route_id: event.route_id, locale: event.locale, occurred_at: new Date().toISOString(),
        ...(event.cta_id ? { cta_id: event.cta_id } : {}) });
    });
    return { consent, fetch, navigation };
  }
  const requests = (fetch: MockInstance<typeof window.fetch>, action: string) =>
    fetch.mock.calls.filter(([url]) => String(url).endsWith('/' + action + '/'));

  it('explicit opt-in grants once and actual minimized page/CTA receipts dedupe, reset erases without browser persistence', async () => {
    const storage = vi.spyOn(Storage.prototype, 'setItem');
    const { consent, fetch } = setup();
    expect(fetch).not.toHaveBeenCalled();
    consent.choose(true);
    await vi.waitFor(() => expect(requests(fetch, 'receipt').length).toBe(1));
    await consent.observe('public_page_view');
    await consent.observe('public_cta_selected', 'public_trial_cta');
    await consent.observe('public_cta_selected', 'public_trial_cta');
    await consent.observe('public_cta_selected', 'borrowed_cta');
    expect(requests(fetch, 'grant').length).toBe(1); expect(requests(fetch, 'receipt').length).toBe(2);
    const [url, options] = requests(fetch, 'receipt')[0];
    expect(url).toBe('/api/public-analytics/receipt/');
    expect(options).toMatchObject({ method: 'POST', cache: 'no-store', credentials: 'same-origin',
      redirect: 'error', referrerPolicy: 'no-referrer', headers: { 'X-CSRFToken': 'c'.repeat(64) } });
    expect(JSON.stringify(options)).not.toMatch(/organization_id|project_id|referrer_url|customer_export|visitor_id/);
    consent.choose(false);
    await vi.waitFor(() => expect(requests(fetch, 'withdraw').length).toBe(1));
    expect(requests(fetch, 'withdraw')[0][1]).toMatchObject({ keepalive: true });
    await consent.observe('public_page_view'); expect(requests(fetch, 'receipt').length).toBe(2);
    expect(storage).not.toHaveBeenCalled();
  });

  it('late grant after rejection/pagehide is withdrawn and never records or reenables choice', async () => {
    const { consent, fetch } = setup();
    let resolve!: (response: Response) => void;
    const grant = issued();
    fetch.mockImplementation((url) => String(url).endsWith('/grant/')
      ? new Promise<Response>(done => resolve = done)
      : json(String(url).endsWith('/csrf/') ? { csrfToken: 'c'.repeat(64) }
        : { method: 'public-consent-epoch-v1', state: 'withdrawn' }));
    consent.choose(true);
    await vi.waitFor(() => expect(resolve).toBeDefined());
    window.dispatchEvent(new Event('pagehide'));
    resolve(await json(grant));
    await vi.waitFor(() => expect(requests(fetch, 'withdraw').length).toBe(1));
    expect(requests(fetch, 'receipt').length).toBe(0); expect(consent.preference()).toBeNull();
    expect(consent.status()).toContain('off');
  });

  it('uncertain receipts have no automatic replay, private navigation clears capability and late response state', async () => {
    const { consent, fetch } = setup();
    const original = fetch.getMockImplementation()!;
    fetch.mockImplementation((url, options) => String(url).endsWith('/receipt/')
      ? Promise.reject(new Error('Synthetic lost response')) : original(url, options));
    consent.choose(true);
    await vi.waitFor(() => expect(consent.status()).toContain('unconfirmed'));
    await consent.observe('public_page_view'); expect(requests(fetch, 'receipt').length).toBe(1);
    vi.spyOn(TestBed.inject(Router), 'url', 'get').mockReturnValue('/account/reset?token=private');
    await consent.observe('public_cta_selected', 'public_trial_cta');
    expect(requests(fetch, 'receipt').length).toBe(1);
    consent.reset(); await vi.waitFor(() => expect(requests(fetch, 'withdraw').length).toBe(1));
    expect(JSON.stringify(fetch.mock.calls)).not.toContain('token=private');
  });

  it('original deadline expires without renewal and malformed grant capability is withdrawn', async () => {
    vi.useFakeTimers();
    const { consent, fetch } = setup();
    consent.choose(true);
    await vi.waitFor(() => expect(requests(fetch, 'receipt').length).toBe(1));
    await vi.advanceTimersByTimeAsync(15 * 60_000);
    expect(consent.preference()).toBeNull(); expect(consent.status()).toContain('expired');
    expect(requests(fetch, 'grant').length).toBe(1);
    await consent.observe('public_page_view'); expect(requests(fetch, 'receipt').length).toBe(1);
    const original = fetch.getMockImplementation()!;
    fetch.mockImplementation((url, options) => String(url).endsWith('/grant/')
      ? json({ ...issued(), expires_at: 'invalid', customer_export: 'private' }) : original(url, options));
    consent.choose(true);
    await vi.waitFor(() => expect(consent.status()).toContain('unconfirmed'));
    expect(requests(fetch, 'withdraw').length).toBe(2); expect(requests(fetch, 'receipt').length).toBe(1);
  });

  it('actual private navigation withdraws known proof and late invalid receipt cannot overwrite the cleared state', async () => {
    const { consent, fetch, navigation } = setup();
    const original = fetch.getMockImplementation()!;
    let resolve!: (response: Response) => void;
    fetch.mockImplementation((url, options) => String(url).endsWith('/receipt/')
      ? new Promise<Response>(done => resolve = done) : original(url, options));
    consent.choose(true);
    await vi.waitFor(() => expect(resolve).toBeDefined());
    vi.spyOn(TestBed.inject(Router), 'url', 'get').mockReturnValue('/account/register');
    navigation.next(new NavigationEnd(1, '/account/register', '/account/register'));
    resolve(await json({ method: 'invalid', customer_export: 'private' }));
    await vi.waitFor(() => expect(requests(fetch, 'withdraw').length).toBe(1));
    expect(consent.preference()).toBeNull(); expect(consent.status()).toContain('off');
    expect(requests(fetch, 'receipt').length).toBe(1);
  });

  it('destruction during an outstanding grant withdraws late proof without observation or renewed consent', async () => {
    const { consent, fetch } = setup();
    const original = fetch.getMockImplementation()!;
    let resolve!: (response: Response) => void;
    fetch.mockImplementation((url, options) => String(url).endsWith('/grant/')
      ? new Promise<Response>(done => resolve = done) : original(url, options));
    consent.choose(true);
    await vi.waitFor(() => expect(resolve).toBeDefined());
    TestBed.resetTestingModule(); resolve(await json(issued()));
    await vi.waitFor(() => expect(requests(fetch, 'withdraw').length).toBe(1));
    expect(consent.preference()).toBeNull(); expect(requests(fetch, 'receipt').length).toBe(0);
  });
});
