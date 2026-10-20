import { Title } from '@angular/platform-browser';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { vi } from 'vitest';
import { AccountApi, ApiResult } from '../account/account-api';
import { VisibilityManual } from './visibility-manual';
import { environment } from '../../environments/environment';

const ID = '00000000-0000-4000-8000-000000000002';
class ManualApi {
  preference: ApiResult | Error = { status: 200, body: { language: 'en', current_ui_language: 'en', current_email_language: 'en' } };
  async productLanguage(): Promise<ApiResult> { if (this.preference instanceof Error) throw this.preference; return this.preference; }
  rows: Record<string, unknown>[] = []; commands: Record<string, unknown>[] = []; queries: string[] = [];
  canReview = true; current = true; uncertain = false; foreign = false; historyPromise: Promise<ApiResult> | null = null;
  result(org = 7, project = 9, observations = this.rows.slice(-1)): ApiResult {
    return { status: 200, body: { organization_id: org, project_id: this.foreign ? 999 : project,
      method_version: 'visibility-human-answer-v1', source_kind: 'customer_owned_manual_answer', surface: 'customer_reported_answer',
      can_review: this.canReview, configuration_revision: 1, market: 'Turkey', languages: ['en'], brand_aliases: ['Synthetic Brand'],
      verified_origins: this.canReview ? ['https://manual.example.invalid'] : [],
      intent_reviews: this.canReview ? [{ review_id: 12, label: 'Actual human intent', language: 'en', market: 'Turkey', source_current: true }] : [],
      observations: observations.map((row) => ({ ...row, source_current: this.current, is_latest: row['revision'] === this.rows.length })),
      has_more: false, sources_has_more: false } };
  }
  visibilityManual(org: number, project: number, data?: Record<string, unknown>, id?: string, key?: string): Promise<ApiResult> {
    if (!data) {
      if (key) { this.queries.push(key); const rows = this.rows.filter((row) => row['request_key'] === key);
        const result = this.result(org, project, rows); result.body['lookup'] = rows.length ? 'found' : 'not_found'; return Promise.resolve(result); }
      return id && this.historyPromise ? this.historyPromise : Promise.resolve(this.result(org, project, id ? [...this.rows].reverse() : this.rows.slice(-1)));
    }
    this.commands.push(data);
    const row = { ...structuredClone(data), id: this.rows.length + 1, project_id: project, observation_id: id || ID,
      revision: this.rows.length + 1, source_current: true, is_latest: true, created_at: new Date().toISOString(),
      verification_id: 23, verified_at: '2026-10-01T12:00:00+00:00', actor_id: 21,
      basis: 'human_report_not_consumer_or_provider_verified', comparison_context: { source_label: 'Human tool', reported_model: '', applied_location: '' },
      preview: { matches: [{ kind: 'brand', entity: 'project_brand', start: 2, end: 17, decision: 'uncertain', note: 'Inspect full answer.' }], links: [], has_more: false } };
    this.rows.push(row);
    return this.uncertain ? Promise.reject(new Error('Lost acknowledgement')) : Promise.resolve({ status: id ? 200 : 201,
      body: { organization_id: org, project_id: project, observation: row } });
  }
  visibilityManualRates(org: number, project: number): Promise<ApiResult> {
    const row = this.rows.at(-1); const intake = row?.['intake'] as Record<string, unknown> | undefined;
    const denominator = row?.['evaluated'] && intake?.['status'] === 'complete' && this.current ? 1 : 0;
    return Promise.resolve({ status: 200, body: { organization_id: org, project_id: this.foreign ? 999 : project,
      method: 'visibility-human-answer-v1', surface: 'customer_reported_answer', external_cost: null, referrals: null,
      scope: 'latest_100_current_report_revisions_not_all_chats_or_api_samples', has_more: false,
      groups: row ? [{ comparison_key: 'manual-source-key', context: row['comparison_context'], report_ids: [row['id']],
        eligible_report_ids: denominator ? [row['id']] : [], statuses: { complete: 1 }, exclusions: denominator ? {} : { unevaluated: 1 },
        mention_rate: { numerator: denominator, denominator, percent: denominator ? '100.00' : null, state: denominator ? 'sampled_human_evaluated' : 'unavailable' },
        competitor_mention_rates: {} }] : [] } });
  }
}

describe('Separate independently permitted human answer evidence', () => {
  let api: ManualApi;
  beforeEach(() => { api = new ManualApi(); TestBed.configureTestingModule({ providers: [provideRouter([
    { path: 'manual/:organizationId/:projectId', component: VisibilityManual },
  ]), { provide: AccountApi, useValue: api }] }); });
  async function screen(language: 'en' | 'tr' = 'en') {
    api.preference = { status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } };
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/manual/7/9', VisibilityManual);
    await harness.fixture.whenStable(); harness.detectChanges(); return { harness, component };
  }
  function fill(harness: RouterTestingHarness, rights = true) {
    const form = harness.routeNativeElement!.querySelector('form') as HTMLFormElement;
    for (const [key, value] of Object.entries({ intent_review_id: '12', prompt: 'Actual intent <script>literal</script>',
      answer: '😀 Synthetic Brand <script>literal</script>', source_label: 'Human tool', observation_reference: 'own-human-1',
      observed_at: '2026-10-02T13:00:00+03:00', evidence_note: 'Independent permitted report; unknown applied context.', reason: 'Actual human report' })) {
      (form.elements.namedItem(key) as HTMLInputElement).value = value;
    }
    for (const key of ['storage_permission', 'not_response_only_copy', 'no_personal_payload']) (form.elements.namedItem(key) as HTMLInputElement).checked = rights;
    return form;
  }
  async function submit(harness: RouterTestingHarness, form: HTMLFormElement) {
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); await harness.fixture.whenStable(); harness.detectChanges();
  }
  it.each(['en', 'tr'] as const)('requires independent rights, preserves exact unknown context and separates intake/evaluation/correction denominators in %s', async (language) => {
    const { harness, component } = await screen(language);
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Özel izin verilmiş insan yanıtı raporları — OrganicSEOOps' : 'Private permitted human answer reports — OrganicSEOOps');
    const storage = vi.spyOn(Storage.prototype, 'setItem');
    await submit(harness, fill(harness, false)); expect(api.commands).toEqual([]);
    const intakeForm = fill(harness), controls = [...intakeForm.querySelectorAll('textarea, input, select')];
    const values = [...new FormData(intakeForm)], context = component.context(), reads = vi.spyOn(api, 'visibilityManual');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Private permitted human answer reports — OrganicSEOOps' : 'Özel izin verilmiş insan yanıtı raporları — OrganicSEOOps');
    expect(harness.routeNativeElement!.querySelector('form')).toBe(intakeForm);
    expect([...intakeForm.querySelectorAll('textarea, input, select')]).toEqual(controls); expect([...new FormData(intakeForm)]).toEqual(values);
    expect(component.context()).toBe(context); expect(reads).not.toHaveBeenCalled(); expect(api.commands).toEqual([]);
    component.productLanguage.set(language); harness.detectChanges(); reads.mockRestore();
    expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe(language);
    await submit(harness, intakeForm);
    const input = api.commands[0]['intake'] as Record<string, unknown>;
    expect(input['reported_model']).toBe(''); expect(input['applied_location']).toBe(''); expect(input['applied_device']).toBe('unknown');
    expect(input['observed_at']).toBe('2026-10-02T13:00:00+03:00'); expect(api.commands[0]['evaluated']).toBe(false);
    expect(harness.routeNativeElement!.querySelector('script, img, iframe')).toBeNull();
    const answer = harness.routeNativeElement!.querySelector(`pre[aria-label="${component.t('Exact unchanged customer-reported answer')}"]`)!;
    expect(answer.textContent).toBe(input['answer']); expect(answer.querySelector('span')!.getAttribute('lang')).toBe('');
    expect(harness.routeNativeElement!.querySelector('details pre span')!.getAttribute('lang')).toBe('');
    expect(component.rates()!.groups[0].mention_rate.denominator).toBe(0);
    component.review(component.context()!.observations[0]); harness.detectChanges();
    let form = harness.routeNativeElement!.querySelector('form') as HTMLFormElement;
    (form.elements.namedItem('matches') as HTMLTextAreaElement).value = JSON.stringify([{ kind: 'brand', entity: 'project_brand', start: 2, end: 17, decision: 'confirmed', note: 'Exact full answer human review.' }]);
    (form.elements.namedItem('reason') as HTMLInputElement).value = 'Full-answer meaning checked';
    (form.elements.namedItem('evaluated') as HTMLInputElement).checked = true;
    const reviewNodes = [...form.querySelectorAll('textarea, input')], reviewValues = [...new FormData(form)];
    const reviewing = component.reviewing(), rates = component.rates(); const commands = api.commands.length;
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(harness.routeNativeElement!.querySelector('form')).toBe(form); expect([...form.querySelectorAll('textarea, input')]).toEqual(reviewNodes);
    expect([...new FormData(form)]).toEqual(reviewValues); expect(component.reviewing()).toBe(reviewing); expect(component.rates()).toBe(rates);
    expect(api.commands).toHaveLength(commands); component.productLanguage.set(language); harness.detectChanges();
    await submit(harness, form); expect(api.commands[1]['expected_revision']).toBe(1); expect(api.commands[1]['evaluated']).toBe(true);
    expect(component.rates()!.groups[0].mention_rate.denominator).toBe(1);
    component.edit(component.context()!.observations[0]); harness.detectChanges(); form = fill(harness);
    (form.elements.namedItem('status') as HTMLSelectElement).value = 'partial';
    const correction = component.editing(), correctedValues = [...new FormData(form)];
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(harness.routeNativeElement!.querySelector('form')).toBe(form); expect([...new FormData(form)]).toEqual(correctedValues);
    expect(component.editing()).toBe(correction); expect(api.commands).toHaveLength(2);
    component.productLanguage.set(language); harness.detectChanges(); await submit(harness, form);
    expect(api.commands[2]['evaluated']).toBe(false); expect(api.commands[2]['matches']).toEqual([]);
    expect(component.rates()!.groups[0].mention_rate.percent).toBeNull();
    await component.inspect(ID); harness.detectChanges(); const history = component.historyRows(), details = harness.routeNativeElement!.querySelector('details[open]');
    const readHistory = vi.spyOn(api, 'visibilityManual');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(component.historyRows()).toBe(history); expect(harness.routeNativeElement!.querySelector('details[open]')).toBe(details);
    expect(readHistory).not.toHaveBeenCalled(); expect(api.commands).toHaveLength(3); readHistory.mockRestore();
    expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
    harness.fixture.destroy(); TestBed.inject(Title).setTitle('Next route — OrganicSEOOps');
    component.productLanguage.set(language); TestBed.tick();
    expect(TestBed.inject(Title).getTitle()).toBe('Next route — OrganicSEOOps');
  });
  it.each(['en', 'tr'] as const)('freezes lost acknowledgements and reconciles exact JSONB-reordered spans without replay in %s', async (language) => {
    const { harness, component } = await screen(language); api.uncertain = true; await submit(harness, fill(harness));
    expect(component.pending()).not.toBeNull(); const frozen = component.pending(), reads = [...api.queries];
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(component.pending()).toBe(frozen); expect(api.commands).toHaveLength(1); expect(api.queries).toEqual(reads);
    expect(harness.routeNativeElement!.querySelector('form')).toBeNull();
    component.productLanguage.set(language); harness.detectChanges(); await component.reconcile(); harness.detectChanges();
    expect(api.commands.length).toBe(1); expect(api.queries).toEqual([api.commands[0]['request_key']]);
    expect(component.pending()).toBeNull(); expect(component.message()).toContain('no command replayed');
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'komut yeniden oynatılmadı' : 'no command replayed');
    api.uncertain = false; component.review(component.context()!.observations[0]); harness.detectChanges();
    const form = harness.routeNativeElement!.querySelector('form') as HTMLFormElement;
    (form.elements.namedItem('reason') as HTMLInputElement).value = 'Uncertain alias review';
    api.uncertain = true; await submit(harness, form);
    const matches = api.rows.at(-1)!['matches'] as Record<string, unknown>[];
    api.rows.at(-1)!['matches'] = matches.map((row) => Object.fromEntries(Object.entries(row).reverse()));
    await component.reconcile(); expect(api.commands.length).toBe(2); expect(component.pending()).toBeNull();
  });
  it('shows retained viewer/stale evidence read-only and rejects foreign responses', async () => {
    api.canReview = false; const { harness, component } = await screen(); expect(harness.routeNativeElement!.querySelector('form')).toBeNull();
    api.canReview = true; await component.load(); harness.detectChanges(); await submit(harness, fill(harness));
    api.current = false; await component.load(); harness.detectChanges();
    expect(harness.routeNativeElement!.textContent).toContain('Stale source or actor authority');
    component.review(component.context()!.observations[0]); expect(component.reviewing()).toBeNull();
    api.canReview = false; await component.inspect(ID); harness.detectChanges(); expect(harness.routeNativeElement!.querySelector('form')).toBeNull();
    api.foreign = true; await component.load(); expect(component.context()).toBeNull(); expect(component.rates()).toBeNull();
  });
  it('rejects inconsistent human mention percentages and preserves exact source rounding and unavailable denominators', async () => {
    const { harness, component } = await screen(); await submit(harness, fill(harness));
    const result = await api.visibilityManualRates(7, 9);
    const groups = result.body['groups'] as Record<string, unknown>[];
    const group = groups[0];
    const rate = (numerator: number, denominator: number, percent: string | null) =>
      ({ numerator, denominator, percent, state: denominator ? 'sampled_human_evaluated' : 'unavailable' });
    const counted = (numerator: number, denominator: number, percent: string | null) => ({ ...group,
      report_ids: Array.from({ length: denominator || 1 }, (_, i) => i + 1),
      eligible_report_ids: Array.from({ length: denominator }, (_, i) => i + 1), mention_rate: rate(numerator, denominator, percent) });
    const read = vi.spyOn(api, 'visibilityManualRates');
    for (const invalid of [
      counted(0, 1, '100.00'), counted(0, 0, '0.00'), counted(1, 1, null), counted(1, 1, '100.0'),
      counted(1, 32, '3.13'), counted(1, 101, '0.99'),
      { ...counted(1, 1, '100.00'), report_ids: [1, 1] },
      { ...counted(1, 2, '50.00'), eligible_report_ids: [1, 1] },
      { ...counted(1, 1, '100.00'), mention_rate: { ...rate(1, 1, '100.00'), state: ['sampled_human_evaluated'] } },
      { ...counted(1, 1, '100.00'), competitor_mention_rates: { 'competitor.example.invalid': rate(0, 1, '100.00') } },
    ]) {
      read.mockResolvedValue({ status: 200, body: { ...result.body, groups: [invalid] } });
      await component.load(); harness.detectChanges();
      expect(component.rates(), JSON.stringify(invalid)).toBeNull(); expect(component.context()).toBeNull();
      expect(harness.routeNativeElement!.textContent).toContain('evidence/current authority unavailable');
    }
    for (const valid of [counted(0, 0, null), counted(0, 1, '0.00'), counted(1, 3, '33.33'),
      counted(1, 32, '3.12'), counted(3, 32, '9.38'), counted(1, 1, '100.00'),
      { ...counted(1, 3, '33.33'), competitor_mention_rates: { 'competitor.example.invalid': rate(0, 3, '0.00') } },
      { ...counted(0, 0, null), competitor_mention_rates: { 'competitor.example.invalid': rate(0, 0, null) } }]) {
      read.mockResolvedValue({ status: 200, body: { ...result.body, groups: [valid] } });
      await component.load(); expect(component.rates()).not.toBeNull();
    }
    expect(api.commands).toHaveLength(1);
  });
  it('clears private form/evidence and ignores late history across route reuse', async () => {
    const { harness, component } = await screen(); await submit(harness, fill(harness));
    let resolve!: (value: ApiResult) => void; api.historyPromise = new Promise((done) => resolve = done);
    const history = component.inspect(ID); const old = api.result(7, 9, [...api.rows]);
    api.rows = []; await harness.navigateByUrl('/manual/7/10', VisibilityManual); resolve(old); await history;
    expect(component.historyRows()).toEqual([]); expect(component.editing()).toBeNull(); expect(component.reviewing()).toBeNull(); expect(component.pending()).toBeNull();
    harness.detectChanges(); expect(harness.routeNativeElement!.querySelector('pre[aria-label="Exact unchanged customer-reported answer"]')).toBeNull();
  });
  it('rejects mismatched acknowledgements and refuses unknown replay after current-role loss', async () => {
    const { harness, component } = await screen();
    const save = api.visibilityManual.bind(api);
    vi.spyOn(api, 'visibilityManual').mockImplementation(async (org, project, data, id, key) => {
      const response = await save(org, project, data, id, key);
      if (data) { const row = response.body['observation'] as Record<string, unknown>;
        response.body['observation'] = { ...row, intake: { ...(row['intake'] as Record<string, unknown>), answer: 'Changed acknowledgement' } }; }
      return response;
    });
    await submit(harness, fill(harness)); expect(component.pending()).not.toBeNull(); expect(api.commands).toHaveLength(1);
    await component.reconcile(); expect(component.pending()).toBeNull(); expect(api.commands).toHaveLength(1);
    api.uncertain = true; harness.detectChanges(); const form = fill(harness);
    (form.elements.namedItem('observation_reference') as HTMLInputElement).value = 'other-uncertain'; await submit(harness, form);
    api.rows = []; api.canReview = false; await component.reconcile();
    expect(component.notFound()).toBe(false); component.retry(); expect(api.commands).toHaveLength(2);
    expect(component.context()).toBeNull(); expect(component.pending()).not.toBeNull();
  });
  it('rejects array and noncanonical human observation identifiers before exposing current evidence or forms', async () => {
    const { harness, component } = await screen(); await submit(harness, fill(harness));
    const row = api.rows[0];
    for (const observation_id of [[ID], '0'.repeat(36), '-'.repeat(36)]) {
      api.rows = [{ ...row, observation_id }]; await component.load(); harness.detectChanges();
      expect(component.context(), JSON.stringify(observation_id)).toBeNull(); expect(component.rates()).toBeNull();
      expect(harness.routeNativeElement!.querySelector('form')).toBeNull();
      expect(component.error()).toContain('evidence/current authority unavailable');
    }
    api.rows = [row]; await component.load(); await component.inspect(ID); harness.detectChanges();
    expect(component.context()?.observations[0].observation_id).toBe(ID);
    expect(component.historyRows()[0].observation_id).toBe(ID); expect(api.commands).toHaveLength(1);
  });
  it('keeps array-ID acknowledgments uncertain until independent scalar source lookup without replay', async () => {
    const { harness, component } = await screen();
    const original = api.visibilityManual.bind(api);
    vi.spyOn(api, 'visibilityManual').mockImplementation(async (org, project, data, id, key) => {
      const response = await original(org, project, data, id, key);
      if (data) {
        const row = response.body['observation'] as Record<string, unknown>;
        response.body['observation'] = { ...row, observation_id: [ID] };
      }
      return response;
    });
    await submit(harness, fill(harness));
    expect(component.pending()).not.toBeNull(); expect(api.commands).toHaveLength(1);
    expect(component.context()?.observations).toEqual([]); expect(component.rates()?.groups).toEqual([]);
    await component.reconcile(); harness.detectChanges();
    expect(component.pending()).toBeNull(); expect(api.commands).toHaveLength(1);
    expect(component.context()?.observations[0].observation_id).toBe(ID); expect(api.queries).toHaveLength(1);
  });
  it('keeps malformed denied unavailable and production human-report preferences English', async () => {
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    try {
      for (const mode of ['invalid', 'incompatible', 'signed-out', 'unavailable', 'production'] as const) {
        TestBed.resetTestingModule(); api = new ManualApi(); buildEnvironment.production = mode === 'production';
        api.preference = mode === 'unavailable' ? new Error('private preference error') : mode === 'signed-out' ? { status: 401, body: {} }
          : { status: 200, body: { language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: mode === 'incompatible' ? 'tr' : 'en', current_email_language: 'en' } };
        TestBed.configureTestingModule({ providers: [provideRouter([{ path: 'manual/:organizationId/:projectId', component: VisibilityManual }]), { provide: AccountApi, useValue: api }] });
        const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/manual/7/9', VisibilityManual);
        await harness.fixture.whenStable(); harness.detectChanges();
        expect(TestBed.inject(Title).getTitle()).toBe('Private permitted human answer reports — OrganicSEOOps');
        expect(component.uiLanguage()).toBe('en'); expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe('Independently permitted human answer reports');
        expect(harness.routeNativeElement!.textContent).not.toContain('incelenmemiş Türkçe'); expect(harness.routeNativeElement!.textContent).not.toContain('private preference error');
        api.foreign = true; await component.load(); harness.detectChanges();
        expect(harness.routeNativeElement!.querySelector('[role=alert]')!.textContent).toBe('Private human evidence/current authority unavailable. Refresh before another report.');
        expect(component.context()).toBeNull(); expect(api.commands).toEqual([]); harness.fixture.destroy();
      }
    } finally { buildEnvironment.production = production; }
  });

});
