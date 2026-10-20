import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { vi } from 'vitest';
import { AccountApi, ApiResult } from './account-api';
import { Acquisition } from './acquisition';

const fields = ['eligible_organizations', 'mature_organizations', 'observed_within_window', 'not_observed_within_window',
  'immature_organizations', 'unknown_paid_coverage', 'unassigned_unknown_trial'];
function body(state = 'available'): Record<string, unknown> {
  return { method: 'retained-monthly-trial-paid-window-v1', basis: 'current_retained_original_operational_sources', grain: 'organization',
    month: '2026-09', starts_at: '2026-09-01T00:00:00+00:00', ends_at: '2026-10-01T00:00:00+00:00',
    assessed_at: '2026-10-02T12:00:00.123456+00:00', window_days: 37, collection_limit: 500, minimum_cell: 5,
    rates_available: false, state, ...Object.fromEntries(fields.map((key, index) => [key, state === 'available' ? [15, 10, 5, 5, 5, 0, 0][index] : null])) };
}

function setup(language: 'en' | 'tr' = 'en') {
  const api = { productLanguage: vi.fn(async () => ({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } })), acquisitionMilestones: vi.fn(async () => ({ status: 403, body: {} })),
    trialPaidCohort: vi.fn<(_month: string) => Promise<ApiResult>>(async () => ({ status: 200, body: body() })) };
  TestBed.configureTestingModule({ providers: [provideRouter([]), { provide: AccountApi, useValue: api }] });
  const fixture = TestBed.createComponent(Acquisition); fixture.detectChanges();
  return { api, fixture, component: fixture.componentInstance };
}

describe('Deliberate private retained monthly window counts', () => {
  it.each(['en', 'tr'] as const)('uses the native month/default control only on explicit inspection and displays exclusions without a rate in %s', async (language) => {
    const { api, fixture, component } = setup(language); await fixture.whenStable(); fixture.detectChanges();
    expect(api.trialPaidCohort).not.toHaveBeenCalled();
    const button = Array.from(fixture.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>)
      .find(node => node.textContent!.includes(language === 'tr' ? 'Saklanan aylık aralık' : 'Inspect retained monthly'))!;
    button.click(); await fixture.whenStable(); fixture.detectChanges();
    expect(api.trialPaidCohort).toHaveBeenCalledWith('');
    expect(component.cohort()?.counts.map(row => row.value)).toEqual([15, 10, 5, 5, 5, 0, 0]);
    expect(fixture.nativeElement.textContent).toContain((language === 'tr' ? 'Dondurulmuş sunucu değerlendirmesi: ' : 'Frozen server assessment: ') + '2026-10-02T12:00:00.123456+00:00');
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Olgun ve kapsamı bilinen payda' : 'Mature known-coverage denominator');
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Oran hesaplanmaz' : 'No rate is calculated');
    const retained = component.cohort(); component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
    expect(component.cohort()).toBe(retained); expect(api.trialPaidCohort).toHaveBeenCalledTimes(1);
    component.productLanguage.set(language); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('section').getAttribute('lang')).toBe(language);
    expect(fixture.nativeElement.querySelector('span[lang="en"]').textContent).toBe('2026-09');
    const input = fixture.nativeElement.querySelector('#trial-paid-cohort-month') as HTMLInputElement;
    input.value = '2026-08'; input.dispatchEvent(new Event('input'));
    expect(component.cohort()).toBeNull();
    const august = { ...body(), month: '2026-08', starts_at: '2026-08-01T00:00:00+00:00', ends_at: '2026-09-01T00:00:00+00:00' };
    api.trialPaidCohort.mockResolvedValue({ status: 200, body: august });
    await component.loadCohort(); expect(component.cohort()?.month).toBe('2026-08');
  });

  it.each(['en', 'tr'] as const)('keeps suppressed, overflow and empty mature denominators distinct with no partial counts or percentages in %s', async (language) => {
    const { api, fixture, component } = setup(language); await fixture.whenStable(); fixture.detectChanges();
    for (const [state, text] of [['suppressed', language === 'tr' ? 'Sayılar gizlendi' : 'Counts suppressed'], ['capacity_exceeded', language === 'tr' ? 'Kesilmiş bir payda gösterilmez' : 'No truncated denominator']]) {
      api.trialPaidCohort.mockResolvedValue({ status: 200, body: body(state) });
      await component.loadCohort(); fixture.detectChanges();
      expect(component.cohort()?.counts).toEqual([]); expect(fixture.nativeElement.textContent).toContain(text);
      expect(fixture.nativeElement.querySelector('#trial-paid-cohort-title')?.parentElement?.querySelector('table')).toBeNull();
    }
    const empty = { ...body(), ...Object.fromEntries(fields.map(key => [key, 0])) };
    api.trialPaidCohort.mockResolvedValue({ status: 200, body: empty });
    await component.loadCohort(); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Olgun ve kapsamı bilinen payda yok. Yüzde mevcut değil.' : 'No mature known-coverage denominator. No percentage is available.');
    api.trialPaidCohort.mockResolvedValue({ status: 403, body: { private_detail: 'PRIVATE_BACKEND_ERROR' } });
    await component.loadCohort(); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Aylık aralık sayıları kullanılamıyor veya hatalı biçimde.' : 'Monthly window counts unavailable or malformed.');
    expect(fixture.nativeElement.textContent).not.toContain('PRIVATE_BACKEND_ERROR');
  });

  it('rejects wrong methods, scope, UTC dates, month bounds, count equations, small complementary cells and null leakage', async () => {
    const { api, component, fixture } = setup();
    const invalid: Record<string, unknown>[] = [
      { method: 'wrong' }, { basis: 'lifetime' }, { grain: 'user' }, { month: '2026-08' }, { window_days: 30 },
      { minimum_cell: 1 }, { collection_limit: 501 }, { rates_available: true }, { source_digest: 'private' },
      { starts_at: '2026-09-02T00:00:00+00:00' }, { ends_at: '2026-10-01T00:00:00.000001+00:00' },
      { assessed_at: '2026-10-02T12:00:00' }, { assessed_at: '2026-02-30T12:00:00+00:00' },
      { assessed_at: '2026-09-30T23:59:59.999999+00:00' }, { assessed_at: '9999-10-02T12:00:00+00:00' },
      { eligible_organizations: 16 }, { mature_organizations: 9 }, { observed_within_window: 1, not_observed_within_window: 9 },
      { eligible_organizations: 500, immature_organizations: 490, unassigned_unknown_trial: 5 },
      { unknown_paid_coverage: true }, { state: 'suppressed', ...Object.fromEntries(fields.map(key => [key, null])), mature_organizations: 10 },
      ...['available', 'suppressed', 'capacity_exceeded'].map(state => ({ state: [state],
        ...Object.fromEntries(fields.map(key => [key, null])) })),
      { state: 'unknown' },
    ];
    for (const delta of invalid) {
      api.trialPaidCohort.mockResolvedValue({ status: 200, body: { ...body(), ...delta } });
      await component.loadCohort(); expect(component.cohort(), JSON.stringify(delta)).toBeNull();
      expect(component.cohortError()).toContain('malformed');
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('#trial-paid-cohort-title')?.parentElement?.querySelector('table')).toBeNull();
    }
    component.cohortMonth.set('2026-08');
    api.trialPaidCohort.mockResolvedValue({ status: 200, body: body() });
    await component.loadCohort(); expect(component.cohort()).toBeNull();
  });

  it('clears saved evidence on denied refresh and discards late edited, refreshed, superseded and destroyed responses', async () => {
    const { api, fixture, component } = setup();
    await component.loadCohort(); expect(component.cohort()).not.toBeNull();
    api.trialPaidCohort.mockResolvedValue({ status: 403, body: { message: 'PRIVATE_BACKEND_ERROR' } });
    await component.loadCohort(); expect(component.cohort()).toBeNull();
    fixture.detectChanges(); expect(fixture.nativeElement.textContent).not.toContain('PRIVATE_BACKEND_ERROR');
    for (const invalidate of [() => component.setCohortMonth({ target: { value: '' } } as unknown as Event),
                             () => component.load(), () => component.ngOnDestroy()]) {
      let resolve!: (result: ApiResult) => void;
      api.trialPaidCohort.mockImplementation(() => new Promise(done => resolve = done));
      const pending = component.loadCohort(); await invalidate(); resolve({ status: 200, body: body() }); await pending;
      expect(component.cohort()).toBeNull(); expect(component.cohortLoading()).toBe(false);
    }
    let oldResolve!: (result: ApiResult) => void;
    api.trialPaidCohort.mockImplementationOnce(() => new Promise(done => oldResolve = done));
    const old = component.loadCohort();
    api.trialPaidCohort.mockResolvedValueOnce({ status: 200, body: body('suppressed') });
    await component.loadCohort(); oldResolve({ status: 200, body: body() }); await old;
    expect(component.cohort()?.state).toBe('suppressed');
    fixture.destroy(); expect(component.cohort()).toBeNull();
  });

  it('uses the real AccountApi private GET/no-store transport and encodes explicit month scope', async () => {
    const fetcher = vi.fn(async (_path: string, _options: RequestInit) => ({ status: 200, json: async () => body() }));
    const api = new AccountApi({ defaultView: { fetch: fetcher }, cookie: '' } as unknown as Document);
    await api.trialPaidCohort(); await api.trialPaidCohort('2026-09'); await api.trialPaidCohort('2026-09?private');
    expect(fetcher.mock.calls.map(call => call[0])).toEqual(['/api/platform/acquisition/trial-paid-cohorts/',
      '/api/platform/acquisition/trial-paid-cohorts/2026-09/', '/api/platform/acquisition/trial-paid-cohorts/2026-09%3Fprivate/']);
    for (const call of fetcher.mock.calls)
      expect(call[1]).toMatchObject({ method: 'GET', credentials: 'same-origin', cache: 'no-store', body: undefined });
  });
});
