import { Title } from '@angular/platform-browser';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { AccountApi, ApiResult } from '../account/account-api';
import { VisibilitySamples } from './visibility-samples';
import { environment } from '../../environments/environment';

class SampleApi {
  preference: ApiResult | Error = { status: 200, body: { language: 'en', current_ui_language: 'en', current_email_language: 'en' } };
  async productLanguage(): Promise<ApiResult> { if (this.preference instanceof Error) throw this.preference; return this.preference; }
  requests: Record<string, unknown>[] = []; role: unknown = 'owner'; pending: Promise<ApiResult> | null = null; failLaunch = false;
  reviewRequests: Record<string, unknown>[] = []; reviewRevision = 0;
  answer = ' Exact <script>attack</script> javascript:evil https://127.0.0.1/ answer ';
  prompt = { key: 'neutral', kind: 'neutral', text: ' Human question <script>literal</script> ', intent_review_id: 7 };
  projectOnboarding(org: number, project: number) { return Promise.resolve({ status: 200, body: {
    project: { id: project, organization_id: org, name: 'Synthetic project ' + project, role: this.role } } }); }
  job(project = 9) { return { id: 8, project_id: project, status: 'succeeded', error_category: '', prompt_key: 'neutral', prompt_kind: 'neutral',
    revision: 1, set_id: 'synthetic-set', prompt_set_id: 1, model_identifier: 'chosen-fixture-model', account_id: 3,
    source_current: true, collection_state: 'collected_unevaluated', repeat_available_at: '2026-10-02T00:00:00Z', attempted_units: 1,
    cancel_requested: false, estimated_max_cost_usd: '0.001', updated_at: '2026-10-01T00:00:00Z',
    usage: { request_status: 'completed', input_tokens: 12, output_tokens: 8, estimated_cost_usd: '0.00002', reported_cost_usd: null, duration_ms: 40 },
    methodology: { prompt: this.prompt, context: { market: 'Turkey', language: 'en' } },
    evidence: { answer: this.answer, collected_at: '2026-10-01T00:00:00Z',
      provider_status: 'completed', returned_model: 'fixture-snapshot', evaluation: 'unevaluated', citation_measurement: 'unavailable', collection_eligible: true, delivery_limit: '' } }; }
  visibilitySamples(_org: number, project: number, jobId = 0, data?: Record<string, unknown>): Promise<ApiResult> {
    if (data && !jobId) { this.requests.push(data); if (this.failLaunch) return Promise.reject(new Error('uncertain network')); }
    if (jobId || data) return this.pending || Promise.resolve({ status: data && !jobId ? 202 : 200, body: { project_id: project, job: this.job(project) } });
    return Promise.resolve({ status: 200, body: { project_id: project, method: 'visibility-text-collection-v1', surface: 'openai_responses_text', automatic_schedule: false, live_verified: false,
      models: [{ id: 2, provider_id: 1, name: 'Synthetic model', identifier: 'chosen-fixture-model', max_output_tokens: 256 }],
      accounts: [{ id: 3, provider_id: 1, label: 'Synthetic account', source: 'organization' }],
      prompt_sets: [{ id: 1, project_id: project, set_id: 'synthetic-set', revision: 1, label: 'Human methodology', source_current: true,
        market: 'Turkey', language: 'en', prompts: [this.prompt], policy: { max_output_tokens: 128, max_cost_usd: '0.05' }, repeat_available_at: { neutral: null } }],
      jobs: project === 9 ? [{ ...this.job(), methodology: null, evidence: null }] : [], has_more: false } });
  }
  visibilityEntities(_org: number, project: number, jobId: number, data?: Record<string, unknown>): Promise<ApiResult> {
    if (data) { this.reviewRequests.push(data); this.reviewRevision++; }
    const matches = [{ kind: 'brand', entity: 'project_brand', start: 2, end: 17, decision: 'uncertain', note: 'Review lexical candidate.' }];
    const latest = data ? { id: 5, project_id: project, job_id: jobId, revision: this.reviewRevision, matches: data['matches'],
      evaluated: data['evaluated'], review_note: data['review_note'], factual_notes: data['factual_notes'], created_at: '2026-10-01T01:00:00Z' } : null;
    const count = data?.['evaluated'] ? 1 : 0;
    const rate = { numerator: count, denominator: count, percent: count ? '100.00' : null, state: count ? 'sampled_human_evaluated' : 'unavailable' };
    return Promise.resolve({ status: data ? 201 : 200, body: { project_id: project, job_id: jobId, method: 'visibility-entities-v1',
      context: { configuration_revision: 2, brand_aliases: ['Synthetic Brand'], project_domains: ['example.invalid'], competitor_domains: [], business_facts: 'unavailable_no_approved_fact_registry' },
      candidates: { matches, links: [], has_more: false }, latest, history: latest ? [latest] : [], history_has_more: false, collection_eligible: true,
      rates: { scope: 'latest_100_sample_jobs_of_this_exact_methodology_revision', has_more: false, groups: [{ requested_model: 'chosen-fixture-model', returned_model: 'fixture-snapshot', account_id: 3,
        sample_ids: [8], eligible_sample_ids: count ? [8] : [], exclusions: count ? {} : { unevaluated: 1 }, prompt_mix: { neutral: 1, branded: 0 }, mention_rate: rate,
        citation_rate: { numerator: null, denominator: 0, percent: null, state: 'unavailable' }, neutral_branded_rates: { neutral: rate }, competitor_mention_rates: {} }] } } });
  }
}

describe('Private manual API-only sample consumer', () => {
  let api: SampleApi;
  beforeEach(() => { api = new SampleApi(); TestBed.configureTestingModule({ providers: [
    provideRouter([{ path: 'samples/:organizationId/:projectId', component: VisibilitySamples },
      { path: 'samples/:organizationId/:projectId/:jobId', component: VisibilitySamples }]), { provide: AccountApi, useValue: api }] }); });
  async function screen(language: 'en' | 'tr' = 'en') {
    api.preference = { status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } };
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/samples/7/9', VisibilitySamples);
    await harness.fixture.whenStable(); harness.detectChanges(); return { harness, component };
  }
  function fill(harness: RouterTestingHarness, component: VisibilitySamples) {
    component.chooseSet(1); component.promptKey.set('neutral'); component.modelId.set(2); harness.detectChanges();
    const form = harness.routeNativeElement!.querySelector('form')!;
    (form.elements.namedItem('prompt_set_id') as HTMLSelectElement).value = '1';
    (form.elements.namedItem('prompt_key') as HTMLSelectElement).value = 'neutral';
    (form.elements.namedItem('model_id') as HTMLSelectElement).value = '2';
    (form.elements.namedItem('account_id') as HTMLSelectElement).value = '3';
    (form.elements.namedItem('max_output_tokens') as HTMLInputElement).value = '100';
    (form.elements.namedItem('max_cost_usd') as HTMLInputElement).value = '0.01';
    (form.elements.namedItem('acknowledge') as HTMLInputElement).checked = true;
    return form;
  }
  it('rejects malformed visibility roles before source reads and preserves scalar role permissions', async () => {
    const { component, harness } = await screen(); const source = vi.spyOn(api, 'visibilitySamples');
    for (const role of ['owner', 'admin', 'member', 'viewer']) {
      const reads = source.mock.calls.length; api.role = [role]; await component.load(); harness.detectChanges();
      expect(component.canLaunch()).toBe(false); expect(component.canReview()).toBe(false); expect(component.ready()).toBe(false);
      expect(component.error()).not.toBe(''); expect(component.jobs()).toEqual([]); expect(component.job()).toBeNull();
      expect(source.mock.calls).toHaveLength(reads); expect(harness.routeNativeElement?.querySelector('form')).toBeNull();
      api.role = role; await component.load(); expect(component.ready()).toBe(true); expect(component.error()).toBe('');
      expect(component.jobs()).toHaveLength(1); expect(component.canLaunch()).toBe(role !== 'viewer');
      expect(component.canReview()).toBe(role === 'owner' || role === 'admin');
    }
    expect(api.requests).toEqual([]); expect(api.reviewRequests).toEqual([]); source.mockRestore();
  });

  it.each(['en', 'tr'] as const)('requires explicit unchanged methodology/model/account/budget, shows exact plain evidence and unknown charge in %s', async (language) => {
    const { harness, component } = await screen(language);
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? "Yalnızca API'ye ait özel yanıt örnekleri — OrganicSEOOps" : 'Private API-only answer samples — OrganicSEOOps');
    expect(component.selectedSetId()).toBe(0); expect(component.modelId()).toBe(0);
    const form = fill(harness, component);
    const choices = [...form.querySelectorAll('select, input')]; const values = new FormData(form);
    const sets = component.sets(), prompt = component.selectedPrompt(); const reads = vi.spyOn(api, 'visibilitySamples');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Private API-only answer samples — OrganicSEOOps' : "Yalnızca API'ye ait özel yanıt örnekleri — OrganicSEOOps");
    expect(harness.routeNativeElement!.querySelector('form')).toBe(form);
    expect([...form.querySelectorAll('select, input')]).toEqual(choices); expect([...new FormData(form)]).toEqual([...values]);
    expect(component.sets()).toBe(sets); expect(component.selectedPrompt()).toBe(prompt); expect(component.modelId()).toBe(2);
    expect(reads).not.toHaveBeenCalled(); expect(api.requests).toEqual([]);
    component.productLanguage.set(language); harness.detectChanges(); reads.mockRestore();
    expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe(language);
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.detectChanges();
    expect(api.requests[0]).toMatchObject({ prompt_set_id: 1, prompt_key: 'neutral', model_id: 2, account_id: 3,
      max_output_tokens: 100, max_cost_usd: '0.01', acknowledge_api_limits: true });
    expect(api.requests[0]['prompt']).toBeUndefined(); // Server resolves immutable exact text, never browser-supplied hidden context.
    expect(harness.routeNativeElement!.textContent).toContain(' Exact <script>attack</script> javascript:evil https://127.0.0.1/ answer ');
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'sağlayıcının bildirdiği ücret bilinmiyor' : 'provider-reported charge unknown');
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'tüketici ChatGPT gözlemleri' : 'not consumer ChatGPT');
    expect(harness.routeNativeElement!.querySelector('pre.answer')!.getAttribute('lang')).toBe('');
    const job = component.job(), entities = component.entities(), answer = harness.routeNativeElement!.querySelector('pre.answer');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(component.job()).toBe(job); expect(component.entities()).toBe(entities); expect(api.requests).toHaveLength(1);
    expect(harness.routeNativeElement!.querySelector('pre.answer')).toBe(answer);
    expect(harness.routeNativeElement!.querySelector('script')).toBeNull();
    expect(harness.routeNativeElement!.querySelector('a[href="https://127.0.0.1/"]')).toBeNull();
    harness.fixture.destroy(); TestBed.inject(Title).setTitle('Next route — OrganicSEOOps');
    component.productLanguage.set(language); TestBed.tick();
    expect(TestBed.inject(Title).getTitle()).toBe('Next route — OrganicSEOOps');
  });
  it.each(['en', 'tr'] as const)('retains one request key on an uncertain launch and clears private late evidence on route reuse in %s', async (language) => {
    const { harness, component } = await screen(language); api.failLaunch = true;
    const form = fill(harness, component);
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); await harness.fixture.whenStable(); harness.detectChanges();
    const values = [...new FormData(form)], key = api.requests[0]['idempotency_key'];
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(harness.routeNativeElement!.querySelector('form')).toBe(form); expect([...new FormData(form)]).toEqual(values);
    expect(api.requests).toHaveLength(1); expect(api.requests[0]['idempotency_key']).toBe(key);
    expect(harness.routeNativeElement!.querySelector('[role=alert]')!.textContent).toContain(language === 'tr' ? 'Sample outcome unconfirmed.' : 'Örnek sonucu doğrulanmadı.');
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); await harness.fixture.whenStable(); harness.detectChanges();
    expect(api.requests.length).toBe(2); expect(api.requests[1]['idempotency_key']).toBe(api.requests[0]['idempotency_key']);
    let resolve!: (result: ApiResult) => void; api.pending = new Promise((done) => resolve = done);
    const pending = component.inspect(8); await harness.navigateByUrl('/samples/7/10', VisibilitySamples);
    resolve({ status: 200, body: { project_id: 9, job: api.job(9) } }); await pending; await harness.fixture.whenStable(); harness.detectChanges();
    expect(component.job()).toBeNull(); expect(component.jobs()).toEqual([]);
    expect(harness.routeNativeElement!.textContent).not.toContain('attack');
  });
  it('keeps viewers read-only and rejects wrong-project detail', async () => {
    api.role = 'viewer'; const { harness, component } = await screen();
    expect(harness.routeNativeElement!.querySelector('form')).toBeNull();
    api.pending = Promise.resolve({ status: 200, body: { project_id: 10, job: api.job(10) } });
    await component.inspect(8); harness.detectChanges(); expect(component.job()).toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain('Sample status/evidence unavailable');
  });
  it('resolves a history sample-ID handoff through authenticated scoped detail rather than URL evidence', async () => {
    api.role = 'viewer'; const harness = await RouterTestingHarness.create();
    const component = await harness.navigateByUrl('/samples/7/9/8', VisibilitySamples);
    await vi.waitFor(() => expect(component.entities()?.job_id).toBe(8));
    await harness.fixture.whenStable(); harness.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe('Private API-only sample evidence — OrganicSEOOps');
    component.productLanguage.set('tr'); harness.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe('Özel yalnızca API örnek kanıtları — OrganicSEOOps');
    expect(component.job()?.id).toBe(8); expect(component.entities()?.job_id).toBe(8);
    expect(harness.routeNativeElement!.querySelector('form')).toBeNull();
    api.pending = Promise.resolve({ status: 200, body: { project_id: 10, job: api.job(10) } });
    await harness.navigateByUrl('/samples/7/9/999', VisibilitySamples); await vi.waitFor(() => expect(component.busy()).toBe(false)); await harness.fixture.whenStable();
    expect(component.job()).toBeNull(); expect(component.entities()).toBeNull();
    harness.detectChanges(); expect(TestBed.inject(Title).getTitle()).toBe('Özel yalnızca API örnek kanıtları — OrganicSEOOps');
    api.preference = { status: 200, body: { language: 'tr', current_ui_language: 'en', current_email_language: 'en' } };
    await harness.navigateByUrl('/samples/7/9', VisibilitySamples); await harness.fixture.whenStable(); harness.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe("Yalnızca API'ye ait özel yanıt örnekleri — OrganicSEOOps");
  });
  it.each(['en', 'tr'] as const)('shows codepoint evidence and uncertain denominators, then saves a separate immutable human correction in %s', async (language) => {
    api.answer = '😀 Synthetic Brand'; const { harness, component } = await screen(language);
    await component.inspect(8); harness.detectChanges();
    expect(component.spanText(component.matchDrafts()[0])).toBe('Synthetic Brand');
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Anılma oranı 0/0 — kullanılamıyor' : 'Mention rate 0/0 — unavailable');
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Atıf oranı kullanılamıyor' : 'Citation rate unavailable');
    const decision = harness.routeNativeElement!.querySelector<HTMLSelectElement>('#entity-decision-0')!;
    decision.value = 'confirmed'; decision.dispatchEvent(new Event('change', { bubbles: true }));
    const form = harness.routeNativeElement!.querySelector<HTMLFormElement>('.entity-review')!;
    (form.elements.namedItem('evaluated') as HTMLInputElement).checked = true;
    (form.elements.namedItem('review_note') as HTMLTextAreaElement).value = 'Human reviewed complete exact answer and name meaning.';
    const factual = form.elements.namedItem('factual_notes') as HTMLTextAreaElement;
    const facts = '[{"start":2,"end":17,"note":"Unverified human concern"}]'; factual.value = facts;
    const nodes = [...form.querySelectorAll('input, select, textarea')], values = [...new FormData(form)];
    const drafts = component.matchDrafts(), entities = component.entities(), job = component.job();
    const reads = vi.spyOn(api, 'visibilityEntities');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(harness.routeNativeElement!.querySelector('.entity-review')).toBe(form);
    expect([...form.querySelectorAll('input, select, textarea')]).toEqual(nodes); expect([...new FormData(form)]).toEqual(values);
    expect(harness.routeNativeElement!.querySelector('#entity-decision-0')).toBe(decision); expect(decision.value).toBe('confirmed');
    expect(factual.value).toBe(facts); expect(component.matchDrafts()).toBe(drafts); expect(component.entities()).toBe(entities); expect(component.job()).toBe(job);
    expect(reads).not.toHaveBeenCalled(); expect(api.reviewRequests).toEqual([]); expect(api.requests).toEqual([]);
    component.productLanguage.set(language); harness.detectChanges(); reads.mockRestore();
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.detectChanges();
    expect(api.reviewRequests[0]).toMatchObject({ expected_revision: 0, expected_configuration_revision: 2, evaluated: true });
    expect((api.reviewRequests[0]['matches'] as { start: number; end: number; decision: string }[])[0]).toMatchObject({ start: 2, end: 17, decision: 'confirmed' });
    expect(api.reviewRequests[0]['factual_notes']).toEqual(JSON.parse(facts));
    expect(api.reviewRequests[0]['request_key']).toEqual(expect.any(String));
    expect(api.requests.length).toBe(0); // Review does not collect or consume provider work.
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Anılma oranı 1/1 — 100.00%' : 'Mention rate 1/1 — 100.00%');
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Atıf oranı kullanılamıyor, payda 0' : 'Citation rate unavailable, denominator 0');
    expect(component.entities()?.latest?.revision).toBe(1);
  });
  it('keeps malformed denied unavailable and production sample preferences English', async () => {
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    try {
      for (const mode of ['invalid', 'incompatible', 'signed-out', 'unavailable', 'production'] as const) {
        TestBed.resetTestingModule(); api = new SampleApi(); buildEnvironment.production = mode === 'production';
        api.preference = mode === 'unavailable' ? new Error('private preference error') : mode === 'signed-out' ? { status: 401, body: {} }
          : { status: 200, body: { language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: mode === 'incompatible' ? 'tr' : 'en', current_email_language: 'en' } };
        TestBed.configureTestingModule({ providers: [provideRouter([{ path: 'samples/:organizationId/:projectId', component: VisibilitySamples }]), { provide: AccountApi, useValue: api }] });
        const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/samples/7/9', VisibilitySamples);
        await harness.fixture.whenStable(); harness.detectChanges();
        expect(TestBed.inject(Title).getTitle()).toBe('Private API-only answer samples — OrganicSEOOps');
        expect(component.uiLanguage()).toBe('en'); expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe('Private API-only answer samples');
        expect(harness.routeNativeElement!.textContent).not.toContain('incelenmemiş Türkçe'); expect(harness.routeNativeElement!.textContent).not.toContain('private preference error');
        api.role = ['owner']; await component.load(); harness.detectChanges();
        expect(harness.routeNativeElement!.querySelector('[role=alert]')!.textContent).toBe('Current project sample choices/history unavailable or access revoked.');
        expect(component.ready()).toBe(false); expect(api.requests).toEqual([]); expect(api.reviewRequests).toEqual([]); harness.fixture.destroy();
      }
    } finally { buildEnvironment.production = production; }
  });

});
