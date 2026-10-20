import { TestBed } from '@angular/core/testing';
import { DOCUMENT } from '@angular/common';
import { vi } from 'vitest';
import { AccountApi } from '../account/account-api';
import { environment } from '../../environments/environment';
import { ProjectCruxHistory } from './project-crux-history';

export function cruxResponse() {
  const periods = [{ start: '2026-08-01', end: '2026-08-28', eligible_days: 'unknown', calendar_days: 28 },
    { start: '2026-08-08', end: '2026-09-04', eligible_days: 'unknown', calendar_days: 28 }];
  return { status: 200, body: { method_version: 'current-crux-history-threshold-source-v1', project_id: 9,
    observation_id: 75, job_id: 72, assessed_at: '2026-10-03T01:00:00.000002Z',
    collected_at: '2026-09-28T01:00:00Z', raw_sha256: 'a'.repeat(64), state: 'available_original_field_history',
    source_method: 'crux-p75-v1', form_factor: 'PHONE', requested_grain: 'page', observed_grain: 'page',
    origin_fallback: false, url_normalization: 'none', collection_timezone: 'PST_fixed_UTC_minus_8', source_period_count: 2,
    comparisons: ['LCP', 'INP', 'CLS'].map((metric, index) => ({ metric, state: 'threshold_worsening_candidate',
      unit: index === 2 ? 'unitless' : 'ms', observations: periods.map((period, current) => ({ ...{ period },
        state: 'observed', p75: index === 2 ? current ? '0.3' : '0.1' : current ? 4500 : 100,
        grade: current ? 'poor' : 'good' })), overlap_calendar_days: 21, period_contract: 'weekly_28_day_windows',
      sample_count: 'unknown', interpretation: 'field_threshold_candidate_not_confirmed_seo_regression_or_causal_change' })) } };
}
function policyResponse() {
  const { assessed_at, ...source } = cruxResponse().body;
  return { status: 200, body: { method_version: 'material-crux-threshold-candidate-v1', source, assessed_at,
    state: 'assessed_original_field_threshold_candidates', source_fingerprint: 'b'.repeat(64),
    interpretation: 'product_material_change_heuristic_not_statistical_seo_regression_causality_consent_or_delivery',
    rows: ['LCP', 'INP', 'CLS'].map((metric, index) => ({ metric, unit: index === 2 ? 'unitless' : 'ms',
      state: 'material_threshold_worsening_candidate', minimum_absolute_increase: ['500', '50', '0.05'][index],
      minimum_relative_increase_fraction: '0.20', absolute_increase: index === 2 ? '0.2' : '4400',
      absolute_floor_met: true as boolean | null, relative_floor_met: true as boolean | null,
      sample_sufficiency: 'unknown', statistical_significance: 'unknown' })) } };
}
function setup() {
  const api = { projectCruxHistory: vi.fn<(...args: number[]) => Promise<{ status: number; body: Record<string, unknown> }>>(async () => cruxResponse()),
    projectCruxMaterialPolicy: vi.fn<(...args: number[]) => Promise<{ status: number; body: Record<string, unknown> }>>(async () => policyResponse()) };
  TestBed.configureTestingModule({ providers: [{ provide: AccountApi, useValue: api }] });
  const fixture = TestBed.createComponent(ProjectCruxHistory), component = fixture.componentInstance;
  component.organizationId = 7; component.projectId = 9;
  component.job = { id: 72, strategy: 'mobile', grain: 'page' };
  component.observation = { id: 75, source: 'crux_history', collected_at: '2026-09-28T01:00:00Z',
    result: { requested_grain: 'page', observed_grain: 'page', origin_fallback: false, url_normalization: 'none' } };
  fixture.detectChanges(); return { api, fixture, component };
}

describe('Deliberate original CrUX history inspection', () => {
  it.each(['en', 'tr'] as const)('uses the actual fixed private material-policy GET only on explicit inspection, with cloned evidence and truthful heuristics (%s)', async (language) => {
    const { api, fixture, component } = setup();
    fixture.componentRef.setInput('language', language); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('section').getAttribute('lang')).toBe(language);
    const response = policyResponse(); api.projectCruxMaterialPolicy.mockResolvedValue(response);
    expect(api.projectCruxMaterialPolicy).not.toHaveBeenCalled();
    fixture.nativeElement.querySelectorAll('button')[1].click(); await fixture.whenStable(); fixture.detectChanges();
    expect(api.projectCruxMaterialPolicy).toHaveBeenCalledExactlyOnceWith(7, 9, 75);
    expect(api.projectCruxHistory).not.toHaveBeenCalled(); expect(component.error()).toBe(false);
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? '%20 göreli artış' : '20% relative increase');
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? '21 takvim günü' : '21 calendar days');
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'bağımsız olarak doğrulayamaz' : 'cannot independently authenticate');
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'istatistiksel anlamlılık bilinmiyor' : 'statistical significance are unknown');
    expect(fixture.nativeElement.querySelector('span[lang="en"]').textContent).toBe('PHONE');
    const buildEnvironment = environment as { production: boolean }, previous = buildEnvironment.production;
    try {
      buildEnvironment.production = true;
      const production = TestBed.createComponent(ProjectCruxHistory);
      production.componentRef.setInput('language', 'tr'); production.detectChanges();
      expect(production.nativeElement.querySelector('section').getAttribute('lang')).toBe('en');
      expect(production.nativeElement.textContent).toContain('Inspect / refresh CrUX material policy');
      production.destroy();
    } finally { buildEnvironment.production = previous; }
    response.body.rows[0].state = 'PRIVATE'; response.body.source.comparisons[0].observations[0].period.start = 'PRIVATE';
    expect(component.policy()!.rows[0].state).toBe('material_threshold_worsening_candidate');
    expect(component.history()!.comparisons[0].observations[0].period.start).toBe('2026-08-01');
    await component.inspect(); expect(component.policy()).toBeNull();
    api.projectCruxMaterialPolicy.mockResolvedValue({ status: 503, body: { private: 'PRIVATE_PROVIDER_BODY' } });
    await component.inspect(true); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role="alert"]').textContent)
      .toContain(language === 'tr' ? 'CrUX kanıtları kullanılamıyor' : 'CrUX evidence is unavailable');
    expect(fixture.nativeElement.textContent).not.toContain('PRIVATE_PROVIDER_BODY');
  });
  it('calls the real AccountApi material endpoint without client floor, recipient or date authority', async () => {
    const fetcher = vi.fn(async () => ({ status: 200, json: async () => policyResponse().body }));
    TestBed.configureTestingModule({ providers: [{ provide: DOCUMENT, useValue: { defaultView: { fetch: fetcher } } }] });
    await TestBed.inject(AccountApi).projectCruxMaterialPolicy(7, 9, 75);
    expect(fetcher).toHaveBeenCalledExactlyOnceWith('/api/organizations/7/projects/9/crux-history/75/material-policy/', {
      method: 'GET', headers: {}, body: undefined, credentials: 'same-origin', cache: 'no-store' });
  });
  it('checks exact inclusive floors and suppresses small crossings, relative misses and large within-grade changes', async () => {
    const { api, component } = setup();
    for (const [index, previous, current, grades, state, increase, absolute, relative] of [
      [0, 2500, 3000, ['good', 'needs_improvement'], 'material_threshold_worsening_candidate', '500', true, true],
      [1, 200, 250, ['good', 'needs_improvement'], 'material_threshold_worsening_candidate', '50', true, true],
      [2, '0.10', '0.15', ['good', 'needs_improvement'], 'material_threshold_worsening_candidate', '0.05', true, true],
      [0, 2500, 2999, ['good', 'needs_improvement'], 'below_material_change_floor', '499', false, false],
      [0, 4000, 4500, ['needs_improvement', 'poor'], 'below_material_change_floor', '500', true, false],
      [0, 1000, 2000, ['good', 'good'], 'no_threshold_worsening_observed', null, null, null],
      [2, '0.1', '0.149999999999999999', ['good', 'needs_improvement'], 'below_material_change_floor', '0.049999999999999999', false, true],
      [2, '0.1', '0.150000000000000001', ['good', 'needs_improvement'], 'material_threshold_worsening_candidate', '0.050000000000000001', true, true],
      [2, '0.25', '0.30', ['needs_improvement', 'poor'], 'material_threshold_worsening_candidate', '0.05', true, true],
      [2, '0.25', '0.299999999999999999', ['needs_improvement', 'poor'], 'below_material_change_floor', '0.049999999999999999', false, false],
      [2, '0E+999999', '0.15', ['good', 'needs_improvement'], 'unknown_relative_zero_baseline', null, null, null],
      [2, '1E-100000', '0.15', ['good', 'needs_improvement'], 'unknown_exact_numeric_precision', null, null, null],
      [2, '1E-60', '0.15', ['good', 'needs_improvement'], 'material_threshold_worsening_candidate', '0.14' + '9'.repeat(58), true, true],
      [2, '1E-61', '0.15', ['good', 'needs_improvement'], 'unknown_exact_numeric_precision', null, null, null],
    ] as const) {
      const response = policyResponse(), comparison = response.body.source.comparisons[index], row = response.body.rows[index];
      comparison.observations[0].p75 = previous; comparison.observations[1].p75 = current;
      comparison.observations.forEach((value, i) => value.grade = grades[i]);
      comparison.state = state === 'no_threshold_worsening_observed' ? state : 'threshold_worsening_candidate';
      Object.assign(row, { state, absolute_increase: increase, absolute_floor_met: absolute, relative_floor_met: relative });
      api.projectCruxMaterialPolicy.mockResolvedValue(response); await component.inspect(true);
      expect(component.error(), String([previous, current])).toBe(false);
      expect(component.policy()!.rows[index].state).toBe(state);
    }
  });
  it('retains missing latest, incomparable actual periods and unknown legacy without reconstructed policy rows', async () => {
    const { api, component, fixture } = setup();
    const missing = policyResponse();
    Object.assign(missing.body.source.comparisons[0].observations[1], { p75: null, grade: 'unknown', state: 'unavailable' });
    missing.body.source.comparisons[0].state = 'unknown_insufficient_eligible_periods';
    Object.assign(missing.body.rows[0], { state: 'unknown_insufficient_eligible_periods', absolute_increase: null, absolute_floor_met: null, relative_floor_met: null });
    api.projectCruxMaterialPolicy.mockResolvedValue(missing); await component.inspect(true); expect(component.error()).toBe(false);
    const incomparable = policyResponse();
    for (const [index, comparison] of incomparable.body.source.comparisons.entries()) {
      Object.assign(comparison.observations[1].period, { end: '2026-09-03', calendar_days: 27 });
      Object.assign(comparison, { state: 'incomparable_source_periods', period_contract: 'not_comparable' });
      Object.assign(incomparable.body.rows[index], { state: 'incomparable_source_periods', absolute_increase: null, absolute_floor_met: null, relative_floor_met: null });
    }
    api.projectCruxMaterialPolicy.mockResolvedValue(incomparable); await component.inspect(true); expect(component.error()).toBe(false);
    const legacy = policyResponse(), source: Record<string, unknown> = legacy.body.source;
    for (const field of ['source_method', 'form_factor', 'requested_grain', 'observed_grain', 'origin_fallback', 'url_normalization', 'collection_timezone', 'source_period_count']) delete source[field];
    Object.assign(source, { state: 'unknown_original_raw_integrity', raw_sha256: null, comparisons: [] });
    legacy.body.state = 'unknown_original_raw_integrity'; legacy.body.rows = [];
    api.projectCruxMaterialPolicy.mockResolvedValue(legacy); await component.inspect(true); fixture.detectChanges();
    expect(component.error()).toBe(false); expect(component.policy()!.rows).toEqual([]);
    expect(fixture.nativeElement.textContent).toContain('no material comparison reconstructed');
  });
  it('rejects corrupted policy and nested original evidence privately, including rounded deltas and false eligibility', async () => {
    const { api, component, fixture } = setup();
    const invalid: Record<string, unknown>[] = [];
    for (const delta of [{ method_version: 'v2' }, { state: 'unknown' }, { interpretation: 'significant' },
      { source_fingerprint: 'A'.repeat(64) }, { source_fingerprint: null }, { assessed_at: '2026-02-30T00:00:00Z' },
      { assessed_at: '2026-09-28T00:59:59.999999Z' }, { rows: [] }, { source: [] }, { source: null }, { private: 'PRIVATE' }]) invalid.push({ ...policyResponse().body, ...delta });
    for (const delta of [{ assessed_at: '2026-10-03T01:00:00Z' }, { project_id: 10 }, { job_id: 73 }, { observation_id: 76 },
      { collected_at: '2026-09-28T01:00:00.000001Z' }, { form_factor: 'TABLET' }, { raw_sha256: null }, { private: 'PRIVATE' }]) {
      const body = policyResponse().body; Object.assign(body.source, delta); invalid.push(body);
    }
    for (const delta of [{ metric: 'TTFB' }, { unit: 'score' }, { state: 'toString' }, { minimum_absolute_increase: '499' },
      { minimum_relative_increase_fraction: '0.2' }, { sample_sufficiency: 'known' }, { statistical_significance: 'confirmed' },
      { absolute_increase: '4399' }, { absolute_increase: 4400 }, { absolute_increase: 'Infinity' }, { absolute_increase: '1E+999999999' },
      { absolute_floor_met: false }, { relative_floor_met: null }, { private: 'PRIVATE' }]) {
      const body = policyResponse().body; Object.assign(body.rows[0], delta); invalid.push(body);
    }
    const rounded = policyResponse().body;
    Object.assign(rounded.source.comparisons[2].observations[1], { p75: '0.149999999999999999', grade: 'needs_improvement' });
    Object.assign(rounded.rows[2], { state: 'material_threshold_worsening_candidate', absolute_increase: '0.05' }); invalid.push(rounded);
    const duplicate = policyResponse().body; duplicate.rows[2] = duplicate.rows[1]; invalid.push(duplicate);
    for (const body of invalid) { api.projectCruxMaterialPolicy.mockResolvedValue({ status: 200, body }); await component.inspect(true);
      expect(component.error()).toBe(true); expect(component.history()).toBeNull(); expect(component.policy()).toBeNull(); expect(component.busy()).toBe(false); }
    for (const status of [401, 403, 404, 409, 429]) { api.projectCruxMaterialPolicy.mockResolvedValue({ status, body: { message: 'PRIVATE' } });
      await component.inspect(true); expect(component.error()).toBe(true); }
    api.projectCruxMaterialPolicy.mockRejectedValue(new Error('PRIVATE')); await component.inspect(true); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).not.toContain('PRIVATE');
  });
  it('clears cross-inspection overlaps, changed original scope, parent invalidation and destroyed late policy reads', async () => {
    const { api, component, fixture } = setup(); await component.inspect(true);
    let resolve!: (value: ReturnType<typeof policyResponse>) => void;
    api.projectCruxMaterialPolicy.mockImplementation(() => new Promise(done => resolve = done));
    const first = component.inspect(true), finishFirst = resolve; expect(component.policy()).toBeNull();
    await component.inspect(); finishFirst(policyResponse()); await first;
    expect(component.policy()).toBeNull(); expect(component.history()).not.toBeNull();
    let originalResolve!: (value: ReturnType<typeof cruxResponse>) => void;
    api.projectCruxHistory.mockImplementation(() => new Promise(done => originalResolve = done));
    const original = component.inspect(), material = component.inspect(true);
    originalResolve(cruxResponse()); await original; expect(component.busy()).toBe(true); expect(component.history()).toBeNull();
    resolve(policyResponse()); await material; expect(component.policy()).not.toBeNull();
    for (const mutate of [() => component.organizationId++, () => component.projectId++, () => component.job!.id++,
      () => component.observation!.id++, () => component.observation!.collected_at = '2026-09-28T01:00:00.000001Z',
      () => component.observation!.result['observed_grain'] = 'origin', () => component.revision++]) {
      const pending = component.inspect(true); mutate(); resolve(policyResponse()); await pending;
      expect(component.policy()).toBeNull(); expect(component.history()).toBeNull(); expect(component.busy()).toBe(false);
    }
    const refresh = component.inspect(true); component.ngOnChanges(); resolve(policyResponse()); await refresh;
    expect(component.policy()).toBeNull();
    const destroyed = component.inspect(true); fixture.destroy(); resolve(policyResponse()); await destroyed;
    expect(component.policy()).toBeNull(); expect(component.busy()).toBe(false);
  });
  it('denies invalid original selections before a policy request or loading state', async () => {
    const { api, component } = setup();
    for (const value of [0, -1, NaN, 2 ** 53]) {
      for (const field of ['organizationId', 'projectId'] as const) { const original = component[field]; component[field] = value;
        await component.inspect(true); expect(component.error()).toBe(true); expect(component.busy()).toBe(false); component[field] = original; }
    }
    component.observation!.source = 'crux_current'; await component.inspect(true);
    expect(api.projectCruxMaterialPolicy).not.toHaveBeenCalled(); expect(component.policy()).toBeNull();
  });
  it('uses the actual AccountApi fixed GET with no body or query authority and private browser caching', async () => {
    const fetcher = vi.fn(async () => ({ status: 200, json: async () => cruxResponse().body }));
    TestBed.configureTestingModule({ providers: [{ provide: DOCUMENT, useValue: { defaultView: { fetch: fetcher } } }] });
    await TestBed.inject(AccountApi).projectCruxHistory(7, 9, 75);
    expect(fetcher).toHaveBeenCalledExactlyOnceWith('/api/organizations/7/projects/9/crux-history/75/', {
      method: 'GET', headers: {}, body: undefined, credentials: 'same-origin', cache: 'no-store' });
  });
  it.each(['en', 'tr'] as const)('reads only explicitly, clones original periods and distinguishes candidates, missing, incomparable and legacy evidence (%s)', async (language) => {
    const { api, fixture, component } = setup();
    fixture.componentRef.setInput('language', language); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('section').getAttribute('lang')).toBe(language); expect(api.projectCruxHistory).not.toHaveBeenCalled();
    const response = cruxResponse(); api.projectCruxHistory.mockResolvedValue(response);
    fixture.nativeElement.querySelector('button').click(); await fixture.whenStable(); fixture.detectChanges();
    expect(api.projectCruxHistory).toHaveBeenCalledWith(7, 9, 75);
    expect(component.error()).toBe(false); expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? '21 takvim günü' : '21 calendar days');
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'laboratuvar puanları değildir' : 'not lab scores');
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'doğrulanmış SEO gerilemesini' : 'confirmed SEO regression');
    response.body.comparisons[0].observations[0].period.start = 'private mutation';
    expect(component.history()?.comparisons[0].observations[0].period.start).toBe('2026-08-01');
    const missing = cruxResponse();
    missing.body.comparisons[0].observations[1] = { ...missing.body.comparisons[0].observations[1], p75: null as unknown as number,
      grade: 'unknown', state: 'unavailable' }; missing.body.comparisons[0].state = 'unknown_insufficient_eligible_periods';
    api.projectCruxHistory.mockResolvedValue(missing); await component.inspect(); fixture.detectChanges();
    expect(component.error()).toBe(false); expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Bilinmiyor: yetersiz uygun dönem' : 'Unknown: insufficient eligible periods');
    const incomparable = cruxResponse();
    for (const row of incomparable.body.comparisons) {
      row.observations[1].period = { ...row.observations[1].period, end: '2026-09-03', calendar_days: 27 };
      row.period_contract = 'not_comparable'; row.state = 'incomparable_source_periods';
    }
    api.projectCruxHistory.mockResolvedValue(incomparable); await component.inspect(); fixture.detectChanges();
    expect(component.error()).toBe(false); expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? '27 dahil takvim günü' : '27 inclusive calendar days');
    const separate = cruxResponse();
    for (const row of separate.body.comparisons) {
      row.observations[1].period = { start: '2026-09-01', end: '2026-09-27', eligible_days: 'unknown', calendar_days: 27 };
      row.period_contract = 'not_comparable'; row.overlap_calendar_days = 0; row.state = 'incomparable_source_periods';
    }
    api.projectCruxHistory.mockResolvedValue(separate); await component.inspect(); expect(component.error()).toBe(false);
    const single = cruxResponse(); single.body.source_period_count = 1;
    for (const row of single.body.comparisons) { row.observations = row.observations.slice(0, 1);
      row.period_contract = 'not_comparable'; row.overlap_calendar_days = null as unknown as number;
      row.state = 'unknown_insufficient_eligible_periods'; }
    api.projectCruxHistory.mockResolvedValue(single); await component.inspect(); expect(component.error()).toBe(false);
    const legacy: Record<string, unknown> = { ...cruxResponse().body, state: 'unknown_original_raw_integrity', raw_sha256: null, comparisons: [] };
    for (const key of ['source_method', 'form_factor', 'requested_grain', 'observed_grain', 'origin_fallback',
      'url_normalization', 'collection_timezone', 'source_period_count']) delete legacy[key];
    api.projectCruxHistory.mockResolvedValue({ status: 200, body: legacy }); await component.inspect(); fixture.detectChanges();
    expect(component.error()).toBe(false); expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Karşılaştırma yeniden oluşturulmadı' : 'No comparison was reconstructed');
  });

  it('rejects wrong scope, dates, shapes, dimensions, original periods and typed metric/grade/state corruption privately', async () => {
    const { api, fixture, component } = setup();
    const invalid: Record<string, unknown>[] = [];
    for (const delta of [{ project_id: 10 }, { job_id: true }, { observation_id: 76 }, { method_version: 'v2' },
      { raw_sha256: null }, { raw_sha256: 'A'.repeat(64) }, { state: 'unknown' }, { credential: 'PRIVATE' },
      { collected_at: '2026-09-28T01:00:00.000001Z' }, { assessed_at: '2026-09-28T00:59:59.999999Z' },
      { assessed_at: '2026-02-30T00:00:00Z' }, { collected_at: '2026-09-28T01:00:00.1234567Z' },
      { form_factor: 'DESKTOP' }, { observed_grain: 'origin' }, { origin_fallback: true }, { requested_grain: 'origin' },
      { url_normalization: 'provider_normalized' }, { collection_timezone: 'UTC' }, { source_period_count: 0 },
      { source_period_count: 41 }, { source_period_count: true }, { comparisons: [] }]) invalid.push({ ...cruxResponse().body, ...delta });
    for (const delta of [{ metric: 'TTFB' }, { state: 'toString' }, { unit: 'score' }, { sample_count: 0 },
      { period_contract: 'not_comparable' }, { overlap_calendar_days: 20 }, { interpretation: 'causal' }, { private_body: 'PRIVATE' }]) {
      const body = cruxResponse().body; Object.assign(body.comparisons[0], delta); invalid.push(body);
    }
    for (const delta of [{ p75: '4500' }, { p75: true }, { p75: -1 }, { p75: 10000001 }, { p75: NaN },
      { grade: 'good' }, { state: 'unavailable' }, { period: { start: '2026-02-30', end: '2026-08-28', eligible_days: 'unknown', calendar_days: 28 } },
      { period: { start: '2026-08-08', end: '2026-09-04', eligible_days: 28, calendar_days: 28 } }]) {
      const body = cruxResponse().body; Object.assign(body.comparisons[0].observations[1], delta); invalid.push(body);
    }
    for (const value of ['0.100000000000000001', '0.250000000000000001', 'NaN', 'Infinity', '-1', '100.1', '123456789012345678901']) {
      const body = cruxResponse().body; body.comparisons[2].observations[1].p75 = value;
      body.comparisons[2].observations[1].grade = value.startsWith('0.1') ? 'good' : 'needs_improvement'; invalid.push(body);
    }
    const dates = cruxResponse().body;
    dates.comparisons[0].observations[1].period.end = '2026-09-28'; invalid.push(dates);
    const duplicate = cruxResponse().body; duplicate.comparisons[2] = duplicate.comparisons[1]; invalid.push(duplicate);
    for (const body of invalid) { api.projectCruxHistory.mockResolvedValue({ status: 200, body }); await component.inspect();
      expect(component.history()).toBeNull(); expect(component.error()).toBe(true); expect(component.busy()).toBe(false); }
    for (const status of [401, 403, 404, 409, 429]) {
      api.projectCruxHistory.mockResolvedValue({ status, body: { message: 'PRIVATE provider error' } }); await component.inspect();
      expect(component.error()).toBe(true);
    }
    api.projectCruxHistory.mockRejectedValue(new Error('PRIVATE')); await component.inspect(); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).not.toContain('PRIVATE');
  });

  it('preserves exact decimal edges, unknown missing periods and device/origin/normalization dimensions', async () => {
    const { api, component } = setup();
    for (const [p75, grade] of [['0.100000000000000001', 'needs_improvement'], ['0.250000000000000001', 'poor'],
      ['1E-100000', 'good'], ['0E+999999', 'good'], ['0.25', 'needs_improvement'], ['-0', 'good'], ['100', 'poor']]) {
      const response = cruxResponse(); response.body.comparisons[2].observations[1].p75 = p75;
      response.body.comparisons[2].observations[1].grade = grade;
      response.body.comparisons[2].state = grade === 'good' ? 'no_threshold_worsening_observed' : 'threshold_worsening_candidate';
      api.projectCruxHistory.mockResolvedValue(response); await component.inspect(); expect(component.error()).toBe(false);
    }
    component.job!.strategy = 'tablet'; component.observation!.result['observed_grain'] = 'origin';
    component.observation!.result['origin_fallback'] = true;
    const origin = cruxResponse(); origin.body.form_factor = 'TABLET'; origin.body.observed_grain = 'origin'; origin.body.origin_fallback = true;
    api.projectCruxHistory.mockResolvedValue(origin); await component.inspect(); expect(component.error()).toBe(false);
    component.job!.strategy = 'desktop'; component.observation!.result['observed_grain'] = 'page';
    component.observation!.result['origin_fallback'] = false; component.observation!.result['url_normalization'] = 'provider_normalized';
    const normalized = cruxResponse(); normalized.body.form_factor = 'DESKTOP'; normalized.body.url_normalization = 'provider_normalized';
    api.projectCruxHistory.mockResolvedValue(normalized); await component.inspect(); expect(component.error()).toBe(false);
  });

  it('clears overlapping refresh and discards mutated original scope, parent invalidation and destroyed late responses', async () => {
    const { api, fixture, component } = setup(); await component.inspect();
    let resolve!: (value: ReturnType<typeof cruxResponse>) => void;
    api.projectCruxHistory.mockImplementation(() => new Promise(done => resolve = done));
    const first = component.inspect(), finishFirst = resolve; expect(component.history()).toBeNull();
    const second = component.inspect(); finishFirst(cruxResponse()); await first; expect(component.busy()).toBe(true);
    resolve(cruxResponse()); await second; expect(component.history()).not.toBeNull();
    for (const mutate of [() => component.organizationId++, () => component.projectId++, () => component.job!.id++,
      () => component.observation!.id++, () => component.observation!.collected_at = '2026-09-28T01:00:00.000001Z',
      () => component.observation!.result['observed_grain'] = 'origin', () => component.revision++]) {
      const pending = component.inspect(); mutate(); resolve(cruxResponse()); await pending;
      expect(component.history()).toBeNull(); expect(component.busy()).toBe(false);
    }
    const refresh = component.inspect(); component.ngOnChanges(); resolve(cruxResponse()); await refresh; expect(component.history()).toBeNull();
    const destroyed = component.inspect(); fixture.destroy(); resolve(cruxResponse()); await destroyed;
    expect(component.history()).toBeNull(); expect(component.busy()).toBe(false);
  });

  it('denies invalid identities and selection before a request or loading state', async () => {
    const { api, component } = setup();
    for (const value of [0, -1, NaN, 2 ** 53]) {
      for (const field of ['organizationId', 'projectId'] as const) { const original = component[field]; component[field] = value;
        await component.inspect(); expect(component.error()).toBe(true); expect(component.busy()).toBe(false); component[field] = original; }
      component.observation!.id = value; await component.inspect(); expect(component.busy()).toBe(false); component.observation!.id = 75;
    }
    component.observation!.source = 'crux_current'; await component.inspect();
    expect(component.history()).toBeNull(); expect(api.projectCruxHistory).not.toHaveBeenCalled();
  });
});
