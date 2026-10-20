import { Title } from '@angular/platform-browser';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { vi } from 'vitest';
import { AccountApi, ApiResult } from '../account/account-api';
import { ProjectResearch } from './project-research';
import { environment } from '../../environments/environment';

const history = { id: 72, project_id: 9, status: 'succeeded', topic: 'Actual stored research topic', updated_at: '2026-01-01T00:00:00Z' };
const detail = { ...history, estimate_units: 6, attempted_units: 0, cancel_requested: false, context_current: true,
  error_category: '', evidence: null, estimated_max_cost_usd: null, usage: null };
const source = { index: 0, state: 'collected', requested_url: 'https://source.example.invalid/page',
  url: 'https://source.example.invalid/page', title: 'Synthetic source', excerpt: 'Original provisional evidence.',
  sha256: 'a'.repeat(64), retrieved_at: '2026-01-01T00:00:00Z', size_bytes: 100, excerpt_truncated: false,
  evidence: 'public_page_text_not_verified_fact', artifact_id: 81 };
const evidence = { method: 'research-v1', coverage: 'collected_selected_sources_only', sources: [source],
  provider_search: 'not_used_explicit_urls_only', synthesis_state: 'ai_draft_requires_human_review',
  synthesis: { summary: 'Review this interpretation.', claims: [{ text: 'Provisional interpretation.', source_index: 0, quote: 'provisional evidence' }] } };
function catalog(jobs: unknown[], projectId = 9): ApiResult {
  return { status: 200, body: { project_id: projectId, models: [], accounts: [], languages: ['en'], jobs,
    has_more: true, source_scope: 'explicit_configured_https_origins_only' } };
}

async function screen(topicReviewId?: string, preference: ApiResult | Error = { status: 200, body: { language: 'en', current_ui_language: 'en', current_email_language: 'en' } }) {
  const queryParamMap = convertToParamMap(topicReviewId === undefined ? {} : { topic_review: topicReviewId });
  const api = {
    productLanguage: vi.fn(async (): Promise<ApiResult> => { if (preference instanceof Error) throw preference; return preference; }),
    projectOnboarding: vi.fn(async (): Promise<ApiResult> => ({ status: 200, body: { project: {
      id: 9, organization_id: 7, name: 'Synthetic project', role: 'viewer' } } })),
    projectResearch: vi.fn(async (): Promise<ApiResult> => catalog([history])),
    intentClusters: vi.fn(async (): Promise<ApiResult> => ({ status: 200, body: { project_id: 9, clusters: [] } })),
    queueProjectResearch: vi.fn(), projectResearchJob: vi.fn(),
    projectTopicReview: vi.fn(async (): Promise<ApiResult> => ({ status: 403, body: {} })),
  };
  TestBed.configureTestingModule({ providers: [provideRouter([]), { provide: AccountApi, useValue: api },
    { provide: ActivatedRoute, useValue: { paramMap: of(convertToParamMap({ organizationId: '7', projectId: '9' })),
      queryParamMap: of(queryParamMap), snapshot: { queryParamMap } } }] });
  const fixture = TestBed.createComponent(ProjectResearch); fixture.detectChanges();
  await vi.waitFor(() => expect(fixture.componentInstance.loading()).toBe(false)); fixture.detectChanges();
  return { api, fixture, component: fixture.componentInstance };
}

describe('Exact project research source history', () => {
  it.each(['en', 'tr'] as const)('allows full Unicode research topic input and denies topic overflow before queueing in %s', async (language) => {
    const { api, fixture, component } = await screen(undefined, { status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } });
    const model = { id: 3, provider_id: 5, name: 'Synthetic model', access_tier: 'free', price_known: true,
      max_output_tokens: null, privacy_policy_url: 'https://policy.example.invalid/' };
    const account = { id: 4, provider_id: 5, label: 'Synthetic account', source: 'platform' };
    api.projectOnboarding.mockResolvedValue({ status: 200, body: { project: { id: 9, organization_id: 7, name: 'Synthetic', role: 'owner' } } });
    api.projectResearch.mockResolvedValue({ ...catalog([]), body: { ...catalog([]).body, models: [model], accounts: [account] } });
    await component.load(); component.selectedModel.set(3); fixture.detectChanges();
    const form = fixture.nativeElement.querySelector('form') as HTMLFormElement;
    const topic = form.querySelector<HTMLInputElement>('#research-topic')!;
    topic.value = '😀'.repeat(240);
    form.querySelector<HTMLSelectElement>('#research-language')!.value = 'en';
    form.querySelector<HTMLSelectElement>('#research-model')!.value = '3';
    form.querySelector<HTMLSelectElement>('#research-account')!.value = '4';
    form.querySelector<HTMLTextAreaElement>('#research-urls')!.value = source.url;
    form.querySelector<HTMLInputElement>('#research-cost')!.value = '0.01';
    form.querySelector<HTMLInputElement>('#research-tokens')!.value = '512';
    form.querySelector<HTMLInputElement>('[name="allow_free"]')!.checked = true;
    api.queueProjectResearch.mockResolvedValue({ status: 202, body: { project_id: 9, job: { ...detail, id: 73, status: 'queued' } } });
    try {
      expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Kaynaklı konu araştırması — OrganicSEOOps' : 'Sourced topic research — OrganicSEOOps');
      expect(fixture.nativeElement.querySelector('section').getAttribute('lang')).toBe(language);
      expect(form.querySelector('label[for="research-topic"]')!.textContent).toBe(language === 'tr' ? 'Seçilen konu (en fazla 240 karakter)' : 'Selected topic (up to 240 characters)');
      expect(form.querySelector('label[for="research-language"]')!.textContent).toBe(language === 'tr' ? 'Proje SEO dili' : 'Project SEO language');
      expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'sağlayıcı ücreti değildir' : 'not a provider charge');
      expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'asla otomatik olarak tekrarlanmaz' : 'never replayed automatically');
      expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'içerik yayımlayamaz' : 'cannot publish content');
      expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Ücretsiz modelin saklama' : 'Free-model retention');
      expect(topic.getAttribute('lang')).toBe('');
      expect(form.querySelector<HTMLAnchorElement>('a[rel="noopener noreferrer"]')!.href).toBe(model.privacy_policy_url);
      expect(form.querySelector<HTMLInputElement>('[name="allow_free"]')!.required).toBe(true);
      const reads = api.projectResearch.mock.calls.length;
      component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
      expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Sourced topic research — OrganicSEOOps' : 'Kaynaklı konu araştırması — OrganicSEOOps');
      expect(fixture.nativeElement.querySelector('form')).toBe(form);
      expect(topic.value).toBe('😀'.repeat(240));
      expect(form.querySelector<HTMLSelectElement>('#research-language')!.value).toBe('en');
      expect(form.querySelector<HTMLSelectElement>('#research-model')!.value).toBe('3');
      expect(form.querySelector<HTMLSelectElement>('#research-account')!.value).toBe('4');
      expect(form.querySelector<HTMLTextAreaElement>('#research-urls')!.value).toBe(source.url);
      expect(form.querySelector<HTMLInputElement>('#research-cost')!.value).toBe('0.01');
      expect(form.querySelector<HTMLInputElement>('[name="allow_free"]')!.checked).toBe(true);
      expect(api.projectResearch).toHaveBeenCalledTimes(reads); expect(api.queueProjectResearch).not.toHaveBeenCalled();
      component.productLanguage.set(language); fixture.detectChanges();
      form.querySelector<HTMLInputElement>('[name="allow_free"]')!.checked = false;
      await component.create({ preventDefault() {}, target: form } as unknown as Event);
      expect(api.queueProjectResearch).not.toHaveBeenCalled();
      form.querySelector<HTMLInputElement>('[name="allow_free"]')!.checked = true;
      expect(topic.maxLength).toBeGreaterThanOrEqual(topic.value.length);
      await component.create({ preventDefault() {}, target: form } as unknown as Event);
      expect(api.queueProjectResearch).toHaveBeenCalledTimes(1);
      expect(api.queueProjectResearch.mock.calls[0][2]).toMatchObject({ topic: topic.value, language: 'en', source_urls: [source.url], model_id: 3, account_id: 4, max_output_tokens: 512, max_cost_usd: '0.01', allow_free: true });
      fixture.detectChanges(); expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Araştırma kuyruğa alındı' : 'Research queued');
      for (const value of ['x'.repeat(241), '😀'.repeat(241), '   ']) {
        topic.value = value; await component.create({ preventDefault() {}, target: form } as unknown as Event);
        expect(api.queueProjectResearch).toHaveBeenCalledTimes(1); expect(component.message()).toContain('240 characters');
        fixture.detectChanges(); expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? '1–240 karakterlik' : '1–240 characters');
      }
      component.topicReview.set({ id: 90, project_id: 9, revision: 1, label: '😀'.repeat(240), language: 'en',
        classification: 'evergreen', intent_review_id: null, snapshot_id: 80, candidate_index: 0, market: 'Türkiye',
        reason: 'Human assessment', created_at: '2026-10-01T00:00:00Z', judgments: {},
        report: { components: [], existing_mapping: null } });
      fixture.detectChanges();
      expect(topic.readOnly).toBe(true); expect(form.querySelector<HTMLSelectElement>('#research-language')!.disabled).toBe(true);
      expect(form.querySelector<HTMLSelectElement>('#research-mapping')!.disabled).toBe(true);
      const retained = component.topicReview(); component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
      expect(component.topicReview()).toBe(retained); expect(topic.readOnly).toBe(true);
      component.productLanguage.set(language); fixture.detectChanges();
      topic.value = 'ignored form value'; await component.create({ preventDefault() {}, target: form } as unknown as Event);
      expect(api.queueProjectResearch).toHaveBeenCalledTimes(2);
      expect(api.queueProjectResearch.mock.calls[1][2]).toMatchObject({ topic: component.topicReview()!.label, topic_review_id: 90 });
    } finally { fixture.destroy(); }
  });

  it('preserves Python character bounds for current research topic and mapping handoff labels', async () => {
    const { api, fixture, component } = await screen('90');
    const mapping = { review_id: 91, revision: 1, label: 'x'.repeat(119) + '🙂', language: 'en', page_kind: 'unmapped', source_current: true };
    const review = { id: 90, project_id: 9, revision: 1, label: 'x'.repeat(239) + '🙂', language: 'en', classification: 'evergreen', intent_review_id: 91 };
    const load = async (label: string, mappingLabel: string) => {
      api.intentClusters.mockResolvedValue({ status: 200, body: { project_id: 9, clusters: [{ ...mapping, label: mappingLabel }] } });
      api.projectTopicReview.mockResolvedValue({ status: 200, body: { project_id: 9, source_current: true, review: { ...review, label }, evidence: {} } });
      await component.load();
    };
    try {
      await load(review.label, mapping.label); expect(component.topicReview()).toEqual(review); expect(component.mappings()).toEqual([mapping]);
      expect(component.selectedMapping()).toBe(91); expect(component.selectedTopic()).toBe(review.label); expect(component.handoffError()).toBe('');
      await load(review.label + 'x', mapping.label); expect(component.topicReview()).toBeNull(); expect(component.handoffError()).toContain('changed');
      await load(review.label, mapping.label + 'x'); expect(component.mappings()).toEqual([]); expect(component.topicReview()).toBeNull();
      expect(component.selectedMapping()).toBeNull(); expect(api.queueProjectResearch).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it('preserves Python policy URL character limits without weakening safe free-tier links', async () => {
    const { api, fixture, component } = await screen();
    api.projectOnboarding.mockResolvedValue({ status: 200, body: { project: { id: 9, organization_id: 7, name: 'Synthetic project', role: 'member' } } });
    const prefix = 'https://policy.example.invalid/';
    const url = prefix + 'x'.repeat(1024 - prefix.length - 1) + '🙂';
    const model = { id: 3, provider_id: 5, name: 'Synthetic model', access_tier: 'free', price_known: true, max_output_tokens: null, privacy_policy_url: url };
    const load = async (privacy_policy_url: string) => {
      api.projectResearch.mockResolvedValue({ ...catalog([]), body: { ...catalog([]).body, models: [{ ...model, privacy_policy_url }],
        accounts: [{ id: 4, provider_id: 5, label: 'Synthetic account', source: 'organization' }] } });
      await component.load(); component.selectedModel.set(3); fixture.detectChanges();
    };
    try {
      await load(url); expect(component.models()).toEqual([model]); expect(component.selectedPolicy()).toBe(url);
      expect(fixture.nativeElement.querySelector('a[rel="noopener noreferrer"]').href).toBe(new URL(url).href);
      expect(fixture.nativeElement.querySelector('#research-free').required).toBe(true);
      for (const invalid of [url + 'x', url + '?private=1', url + '#private']) {
        await load(invalid); expect(component.models()).toEqual([]); expect(component.selectedPolicy()).toBe('');
      }
      expect(api.queueProjectResearch).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it('matches the submitted research model provider to its account despite stale form selection', async () => {
    const { api, fixture, component } = await screen();
    api.projectOnboarding.mockResolvedValue({ status: 200, body: { project: { id: 9, organization_id: 7, name: 'Synthetic project', role: 'member' } } });
    const model = { id: 3, provider_id: 5, name: 'Synthetic model', access_tier: 'standard', price_known: true, max_output_tokens: null, privacy_policy_url: '' };
    const account = { id: 4, provider_id: 5, label: 'Synthetic account', source: 'organization' };
    api.projectResearch.mockResolvedValue({ ...catalog([]), body: { ...catalog([]).body,
      models: [model, { ...model, id: 30, provider_id: 6 }], accounts: [account, { ...account, id: 40, provider_id: 6 }] } });
    await component.load();
    const form = document.createElement('form'); vi.spyOn(form, 'reportValidity').mockReturnValue(true);
    for (const [name, value] of Object.entries({ topic: 'Synthetic topic', language: 'en', source_urls: source.url,
      model_id: '3', account_id: '4', max_output_tokens: '128', max_cost_usd: '0.1' })) {
      const input = document.createElement('input'); input.name = name; input.value = value; form.append(input);
    }
    const submit = () => component.create({ preventDefault: vi.fn(), target: form } as unknown as Event);
    const modelInput = form.elements.namedItem('model_id') as HTMLInputElement;
    const accountInput = form.elements.namedItem('account_id') as HTMLInputElement;
    api.queueProjectResearch.mockResolvedValue({ status: 202, body: { project_id: 9, job: { ...detail, id: 73, status: 'queued' } } });
    try {
      for (const [selected, submitted, accountId] of [[30, 3, 40], [3, 30, 4]]) {
        component.selectedModel.set(selected); modelInput.value = String(submitted); accountInput.value = String(accountId);
        await submit(); expect(api.queueProjectResearch).not.toHaveBeenCalled(); expect(component.message()).toContain('permitted model budget');
      }
      for (const [modelId, accountId] of [[3, 4], [30, 40]]) {
        component.selectedModel.set(modelId); modelInput.value = String(modelId); accountInput.value = String(accountId);
        await submit(); expect(api.queueProjectResearch).toHaveBeenCalledTimes(1);
        expect(api.queueProjectResearch.mock.calls[0][2]).toMatchObject({ model_id: modelId, account_id: accountId });
        api.queueProjectResearch.mockClear();
      }
    } finally { fixture.destroy(); }
  });

  it('preserves Python character limits for Unicode research text and catalogue labels', async () => {
    const { api, fixture, component } = await screen();
    const atLimit = (limit: number) => 'x'.repeat(limit - 1) + '🙂';
    const quote = atLimit(300);
    const original = { ...source, title: atLimit(240), excerpt: quote + 'x'.repeat(1748) };
    const synthesis = { summary: atLimit(3000), claims: [{ text: atLimit(500), source_index: 0, quote }] };
    const valid = { ...evidence, sources: [original], synthesis };
    const read = async (value: unknown) => {
      api.projectResearchJob.mockResolvedValue({ status: 200, body: { project_id: 9, job: { ...detail, estimate_units: 2, evidence: value } } });
      await component.open(72);
    };
    try {
      await read(valid); expect(component.job()?.evidence).toEqual(valid);
      for (const value of [{ ...valid, sources: [{ ...original, title: original.title + 'x' }] },
        { ...valid, sources: [{ ...original, excerpt: original.excerpt + 'x' }] },
        { ...valid, synthesis: { ...synthesis, summary: synthesis.summary + 'x' } },
        { ...valid, synthesis: { ...synthesis, claims: [{ ...synthesis.claims[0], text: synthesis.claims[0].text + 'x' }] } },
        { ...valid, synthesis: { ...synthesis, claims: [{ ...synthesis.claims[0], quote: quote + 'x' }] } }]) {
        await read(value); expect(component.job()).toBeNull();
      }
      const model = { id: 3, provider_id: 5, name: atLimit(120), access_tier: 'standard', price_known: true, max_output_tokens: null, privacy_policy_url: '' };
      const account = { id: 4, provider_id: 5, label: atLimit(80), source: 'organization' };
      const load = async (name: string, label: string) => {
        api.projectResearch.mockResolvedValue({ ...catalog([]), body: { ...catalog([]).body, models: [{ ...model, name }], accounts: [{ ...account, label }] } });
        await component.load();
      };
      await load(model.name, account.label); expect(component.models()).toEqual([model]); expect(component.accounts()).toEqual([account]);
      await load(model.name + 'x', account.label); expect(component.models()).toEqual([]); expect(component.accounts()).toEqual([account]);
      await load(model.name, account.label + 'x'); expect(component.models()).toEqual([model]); expect(component.accounts()).toEqual([]);
    } finally { fixture.destroy(); }
  });

  it('rejects malformed bounded research source evidence before rendering nested rows', async () => {
    const { api, fixture, component } = await screen();
    const read = async (value: unknown) => {
      api.projectResearchJob.mockResolvedValue({ status: 200, body: { project_id: 9, job: { ...detail, estimate_units: 2, evidence: value } } });
      await component.open(72); fixture.detectChanges();
    };
    try {
      const changes = [{ sources: [null] }, { sources: [source, source] }, { sources: Array(6).fill(source) },
        { coverage: ['partial'] }, { coverage: 'whole_web' }, { provider_search: ['not_used_explicit_urls_only'] },
        { provider_search: 'web_searched' }, { synthesis_state: ['ai_draft_requires_human_review'] }];
      const sourceChanges = [{ index: [0] }, { index: -1 }, { index: 0.5 }, { index: 1 }, { state: ['collected'] },
        { state: 'verified_fact' }, { url: [source.url] }, { url: 'javascript:alert(1)' }, { url: source.url + '?private=1' },
        { title: [] }, { title: 'x'.repeat(241) }, { excerpt: [] }, { excerpt: '' }, { excerpt: 'x'.repeat(2049) },
        { sha256: ['a'.repeat(64)] }, { sha256: 'missing' }, { retrieved_at: [] }, { retrieved_at: undefined },
        { state: 'unavailable', error_category: [] }];
      for (const change of [...changes, ...sourceChanges.map(change => ({ sources: [{ ...source, ...change }] }))]) {
        await read(evidence); expect(component.job()).not.toBeNull();
        await read({ ...evidence, ...change }); expect(component.job(), JSON.stringify(change)).toBeNull();
        expect(component.message()).toContain('unavailable'); expect(fixture.nativeElement.textContent).not.toContain(source.excerpt);
      }
      expect(api.queueProjectResearch).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it('rejects malformed research interpretations and claims without exact collected indexed excerpts', async () => {
    const { api, fixture, component } = await screen();
    const read = async (synthesis: unknown, synthesis_state: unknown = 'ai_draft_requires_human_review') => {
      api.projectResearchJob.mockResolvedValue({ status: 200, body: { project_id: 9, job: { ...detail, estimate_units: 2,
        evidence: { ...evidence, synthesis, synthesis_state } } } });
      await component.open(72); fixture.detectChanges();
    };
    const claim = evidence.synthesis.claims[0];
    try {
      const changes = [{ summary: [] }, { summary: '' }, { summary: 'x'.repeat(3001) }, { claims: null }, { claims: [] },
        { claims: [null] }, { claims: Array(11).fill(claim) },
        ...[{ text: [] }, { text: '' }, { text: 'x'.repeat(501) }, { source_index: [0] }, { source_index: -1 },
          { source_index: 0.5 }, { source_index: 1 }, { quote: [] }, { quote: ' ' }, { quote: 'x'.repeat(301) },
          { quote: 'Not in the original excerpt' }].map(change => ({ claims: [{ ...claim, ...change }] }))];
      for (const change of changes) {
        await read({ ...evidence.synthesis, ...change }); expect(component.job(), JSON.stringify(change)).toBeNull();
      }
      await read(null); expect(component.job()).toBeNull();
      await read(evidence.synthesis, 'unavailable'); expect(component.job()).toBeNull();
      const title = '<img src=x onerror=alert(1)>';
      await read({ summary: title, claims: [{ ...claim, text: title }] });
      expect(component.job()).not.toBeNull(); expect(fixture.nativeElement.textContent).toContain(title);
      expect(fixture.nativeElement.querySelector('img')).toBeNull(); expect(fixture.nativeElement.querySelector('q').textContent).toBe(claim.quote);
    } finally { fixture.destroy(); }
  });

  it.each(['en', 'tr'] as const)('preserves research no-source partial interrupted and historical evidence without inventing synthesis in %s', async (language) => {
    const { api, fixture, component } = await screen(undefined, { status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } });
    const unavailable = { index: 1, state: 'unavailable', requested_url: 'https://source.example.invalid/other', error_category: 'source_outcome_unknown' };
    const cases = [
      { ...evidence, coverage: 'no_sources', sources: [], synthesis_state: 'unavailable', synthesis: null },
      { ...evidence, coverage: 'partial', sources: [source, unavailable], synthesis_state: 'unavailable', synthesis: null },
      { ...evidence, coverage: 'partial', sources: [source, unavailable] },
      { ...evidence, coverage: 'collected_selected_sources_only', sources: [source, { ...source, index: 1 }] },
    ];
    try {
      for (const value of cases) {
        api.projectResearchJob.mockResolvedValue({ status: 200, body: { project_id: 9, job: { ...detail, estimate_units: 3, context_current: false, evidence: value } } });
        await component.open(72); fixture.detectChanges(); expect(component.job()?.evidence).toEqual(value);
        expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'geçmiş gözlemlerdir' : 'historical observations');
        expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'sağlayıcının bildirdiği ücret bilinmiyor' : 'provider reported charge unknown');
        if (value.sources.some(row => row.state === 'unavailable')) expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'tarih kullanılamıyor' : 'date unavailable');
        if (value.synthesis === null) expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Yapay zekâ sentezi yok' : 'No AI synthesis is available');
        if (value.synthesis) {
          expect(fixture.nativeElement.querySelector('q[lang=""]')!.textContent).toBe('provisional evidence');
          expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'insan incelemesi gerektirir' : 'requires human review');
          expect(fixture.nativeElement.textContent).toContain(value.synthesis.summary);
        }
        const retained = component.job(), reads = api.projectResearchJob.mock.calls.length;
        component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
        expect(component.job()).toBe(retained); expect(api.projectResearchJob).toHaveBeenCalledTimes(reads);
        component.productLanguage.set(language); fixture.detectChanges();
        expect(fixture.nativeElement.querySelector('script')).toBeNull();
      }
      for (const sources of [[source, source], [{ ...source, index: 1 }, source]]) {
        api.projectResearchJob.mockResolvedValue({ status: 200, body: { project_id: 9, job: { ...detail, estimate_units: 3, evidence: { ...evidence, sources } } } });
        await component.open(72); expect(component.job()).toBeNull();
      }
      api.projectResearchJob.mockResolvedValue({ status: 200, body: { project_id: 9, job: { ...detail, estimate_units: 3,
        evidence: { ...evidence, sources: [source, unavailable], synthesis: { ...evidence.synthesis, claims: [{ ...evidence.synthesis.claims[0], source_index: 1 }] } } } } });
      await component.open(72); expect(component.job()).toBeNull();
      expect(api.queueProjectResearch).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it('rejects malformed research counters errors and nullable charges across read queue and cancel responses', async () => {
    const { api, fixture, component } = await screen();
    const usage = { request_status: 'unknown', estimated_cost_usd: null, reported_cost_usd: null };
    const response = (job: unknown, status = 200): ApiResult => ({ status, body: { project_id: 9, job } });
    try {
      for (const change of [{ estimate_units: [6] }, { estimate_units: '6' }, { estimate_units: 1 }, { estimate_units: 7 },
        { attempted_units: [0] }, { attempted_units: '0' }, { attempted_units: -1 }, { attempted_units: 0.5 }, { attempted_units: 7 },
        { error_category: [] }, { error_category: undefined }, { estimated_max_cost_usd: ['0.1'] }, { estimated_max_cost_usd: undefined },
        { usage: { ...usage, estimated_cost_usd: [] } }, { usage: { ...usage, estimated_cost_usd: undefined } },
        { usage: { ...usage, reported_cost_usd: ['0.01'] } }, { usage: { ...usage, reported_cost_usd: undefined } }]) {
        component.job.set(detail); api.projectResearchJob.mockResolvedValue(response({ ...detail, ...change }));
        await component.open(72); fixture.detectChanges();
        expect(component.job(), JSON.stringify(change)).toBeNull(); expect(component.message()).toContain('unavailable');
        expect(fixture.nativeElement.textContent).not.toContain('Updated ' + history.updated_at);
      }
      for (const attempted_units of [0, 1, 6]) {
        for (const cost of [null, '0.000000', '0.010000']) {
          const job = { ...detail, attempted_units, estimated_max_cost_usd: cost, usage: { ...usage, estimated_cost_usd: cost, reported_cost_usd: cost } };
          api.projectResearchJob.mockResolvedValue(response(job)); await component.open(72); fixture.detectChanges();
          expect(component.job()).toEqual(job); expect(fixture.nativeElement.textContent).toContain('provider reported charge ' + (cost ?? 'unknown'));
        }
      }
      component.canLaunch.set(true); component.job.set(detail);
      api.projectResearchJob.mockResolvedValue(response({ ...detail, attempted_units: [0] })); await component.cancel();
      expect(component.job()).toBeNull(); expect(component.message()).toContain('outcome unavailable');
      const form = document.createElement('form'); vi.spyOn(form, 'reportValidity').mockReturnValue(true);
      for (const [name, value] of Object.entries({ topic: 'Synthetic topic', language: 'en', source_urls: 'https://source.example.invalid/page',
        model_id: '3', account_id: '4', max_output_tokens: '128', max_cost_usd: '0.1' })) {
        const input = document.createElement('input'); input.name = name; input.value = value; form.append(input);
      }
      component.models.set([{ id: 3, provider_id: 5, name: 'Synthetic model', access_tier: 'standard', price_known: true, max_output_tokens: null, privacy_policy_url: '' }]);
      component.accounts.set([{ id: 4, provider_id: 5, label: 'Synthetic account', source: 'organization' }]); component.selectedModel.set(3);
      api.queueProjectResearch.mockResolvedValue(response({ ...detail, id: 73, status: 'queued', estimated_max_cost_usd: ['0.1'] }, 202));
      await component.create({ preventDefault: vi.fn(), target: form } as unknown as Event);
      expect(component.job()).toBeNull(); expect(component.message()).toContain('Refresh history'); expect(api.queueProjectResearch).toHaveBeenCalledTimes(1);
    } finally { fixture.destroy(); }
  });

  it('filters malformed research model scalars while preserving canonical nullable and small output caps', async () => {
    const { api, fixture, component } = await screen();
    const model = { id: 3, provider_id: 5, name: 'Synthetic model', access_tier: 'standard', price_known: true,
      max_output_tokens: 200, privacy_policy_url: '' };
    const setModels = (models: unknown[]) => api.projectResearch.mockResolvedValue({ ...catalog([]), body: { ...catalog([]).body, models } });
    try {
      for (const change of [{ provider_id: [5] }, { provider_id: 0 }, { provider_id: -1 }, { provider_id: 1.5 },
        { provider_id: Number.MAX_SAFE_INTEGER + 1 }, { provider_id: undefined }, { name: ['Synthetic model'] },
        { name: '  ' }, { name: 'x'.repeat(121) }, { max_output_tokens: [128] }, { max_output_tokens: '128' },
        { max_output_tokens: undefined }, { max_output_tokens: NaN }, { max_output_tokens: 0 },
        { max_output_tokens: -1 }, { max_output_tokens: 128.5 }, { max_output_tokens: 10000001 },
        { privacy_policy_url: [] }, { privacy_policy_url: undefined }, { privacy_policy_url: 'javascript:alert(1)' },
        { privacy_policy_url: 'http://policy.example.invalid/' }, { privacy_policy_url: 'https://user:pass@policy.example.invalid/' },
        { privacy_policy_url: 'https://policy.example.invalid/?private=1' }, { privacy_policy_url: 'https://policy.example.invalid/#private' },
        { privacy_policy_url: 'https://policy.example.invalid:444/' }, { privacy_policy_url: 'https://policy.example.invalid/' + 'x'.repeat(1024) },
        { access_tier: 'free', privacy_policy_url: '' }]) {
        setModels([model, { ...model, id: 30, ...change }, null]); await component.load();
        expect(component.models(), JSON.stringify(change)).toEqual([model]); expect(component.error()).toBe('');
      }
      for (const max_output_tokens of [null, 1, 127, 128, 2048, 10000000]) {
        const row = { ...model, max_output_tokens }; setModels([row]); await component.load();
        expect(component.models()).toEqual([row]);
      }
      for (const access_tier of ['unknown', 'standard', 'free']) {
        const row = { ...model, access_tier, privacy_policy_url: 'https://policy.example.invalid/data-use' };
        setModels([row]); await component.load(); component.selectedModel.set(3);
        expect(component.models()).toEqual([row]); expect(component.selectedPolicy()).toBe(row.privacy_policy_url);
      }
      expect(api.queueProjectResearch).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it('filters malformed research account scalars and pairs only genuine provider identities', async () => {
    const { api, fixture, component } = await screen();
    const model = { id: 3, provider_id: 5, name: 'Synthetic model', access_tier: 'standard', price_known: true,
      max_output_tokens: null, privacy_policy_url: '' };
    const account = { id: 4, provider_id: 5, label: 'Synthetic account', source: 'organization' };
    const setAccounts = (accounts: unknown[]) => api.projectResearch.mockResolvedValue({ ...catalog([]), body: { ...catalog([]).body, models: [model], accounts } });
    try {
      for (const change of [{ provider_id: [5] }, { provider_id: undefined }, { provider_id: 0 }, { provider_id: -1 },
        { provider_id: 5.5 }, { provider_id: Number.MAX_SAFE_INTEGER + 1 }, { label: ['Synthetic account'] },
        { label: undefined }, { label: '' }, { label: '  ' }, { label: 'x'.repeat(81) }]) {
        setAccounts([account, { ...account, id: 40, ...change }, null]); await component.load(); component.selectedModel.set(3);
        expect(component.accounts(), JSON.stringify(change)).toEqual([account]); expect(component.availableAccounts()).toEqual([account]);
      }
      for (const source of ['platform', 'organization']) {
        const row = { ...account, source, label: '<img src=x onerror=alert(1)>' };
        setAccounts([row, { ...account, id: 40, provider_id: 6 }]); await component.load(); component.selectedModel.set(3);
        expect(component.accounts()).toHaveLength(2); expect(component.availableAccounts()).toEqual([row]);
      }
      component.selectedModel.set(null); expect(component.availableAccounts()).toEqual([]);
      expect(api.queueProjectResearch).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it('enforces research request caps and free consent after validated model catalogue selection', async () => {
    const { api, fixture, component } = await screen();
    api.projectOnboarding.mockResolvedValue({ status: 200, body: { project: { id: 9, organization_id: 7, name: 'Synthetic project', role: 'member' } } });
    const model = { id: 3, provider_id: 5, name: 'Synthetic model', access_tier: 'standard', price_known: true,
      max_output_tokens: 200, privacy_policy_url: '' };
    const account = { id: 4, provider_id: 5, label: 'Synthetic account', source: 'organization' };
    const select = async (change: Record<string, unknown> = {}) => {
      api.projectResearch.mockResolvedValue({ ...catalog([]), body: { ...catalog([]).body, models: [{ ...model, ...change }], accounts: [account] } });
      await component.load(); component.selectedModel.set(3);
    };
    const form = document.createElement('form'); vi.spyOn(form, 'reportValidity').mockReturnValue(true);
    for (const [name, value] of Object.entries({ topic: 'Synthetic topic', language: 'en', source_urls: 'https://source.example.invalid/page',
      model_id: '3', account_id: '4', max_output_tokens: '128', max_cost_usd: '0.1' })) {
      const input = document.createElement('input'); input.name = name; input.value = value; form.append(input);
    }
    const submit = () => component.create({ preventDefault: vi.fn(), target: form } as unknown as Event);
    const tokens = form.elements.namedItem('max_output_tokens') as HTMLInputElement;
    api.queueProjectResearch.mockResolvedValue({ status: 202, body: { project_id: 9, job: { ...detail, id: 73, status: 'queued' } } });
    try {
      for (const change of [{ max_output_tokens: {} }, { max_output_tokens: 1 }, { max_output_tokens: 127 },
        { access_tier: 'unknown' }, { price_known: false }, { access_tier: 'free', privacy_policy_url: 'https://policy.example.invalid/' }]) {
        await select(change); await submit(); expect(api.queueProjectResearch, JSON.stringify(change)).not.toHaveBeenCalled();
      }
      await select();
      for (const value of ['127', '201', '2049', '128.5']) { tokens.value = value; await submit(); expect(api.queueProjectResearch).not.toHaveBeenCalled(); }
      for (const max_output_tokens of [null, 128, 2048, 10000000]) {
        await select({ max_output_tokens }); tokens.value = String(max_output_tokens === 128 ? 128 : 2048); await submit();
        expect(api.queueProjectResearch).toHaveBeenCalledTimes(1);
        expect(api.queueProjectResearch.mock.calls[0][2]).toMatchObject({ model_id: 3, account_id: 4, max_output_tokens: Number(tokens.value), allow_free: false });
        api.queueProjectResearch.mockClear();
      }
      await select({ access_tier: 'free', privacy_policy_url: 'https://policy.example.invalid/', max_output_tokens: null });
      const consent = document.createElement('input'); consent.name = 'allow_free'; consent.type = 'checkbox'; form.append(consent);
      await submit(); expect(api.queueProjectResearch).not.toHaveBeenCalled();
      consent.checked = true; await submit(); expect(api.queueProjectResearch).toHaveBeenCalledTimes(1);
      expect(api.queueProjectResearch.mock.calls[0][2]).toMatchObject({ allow_free: true, max_output_tokens: 2048 });
      fixture.detectChanges(); expect(fixture.nativeElement.querySelector('#research-free').required).toBe(true);
    } finally { fixture.destroy(); }
  });

  it.each(['en', 'tr'] as const)('rejects malformed reviewed-topic handoff metadata before research and preserves all scalar human classifications in %s', async (language) => {
    const { api, fixture, component } = await screen('90', { status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } });
    const valid = { id: 90, project_id: 9, snapshot_id: 80, candidate_index: 0, revision: 1,
      label: 'Synthetic reviewed topic', classification: 'unknown', language: 'en', market: 'Türkiye',
      intent_review_id: null, judgments: {}, report: {}, reason: 'Human review only', created_at: '2026-10-01T00:00:00Z' };
    api.projectOnboarding.mockResolvedValue({ status: 200, body: { project: {
      id: 9, organization_id: 7, name: 'Synthetic project', role: 'member' } } });
    api.projectResearch.mockResolvedValue({ ...catalog([]), body: { ...catalog([]).body,
      models: [{ id: 3, provider_id: 5, name: 'Synthetic model', access_tier: 'standard', price_known: true, max_output_tokens: 200, privacy_policy_url: '' }],
      accounts: [{ id: 4, provider_id: 5, label: 'Synthetic account', source: 'organization' }] } });
    const source = { kind: 'public_feed_item', url: 'https://source.example.invalid/story' };
    const response = (review: unknown): ApiResult => ({ status: 200, body: { project_id: 9, source_current: true, evidence: source, review } });
    const form = document.createElement('form'); vi.spyOn(form, 'reportValidity').mockReturnValue(true);
    for (const [name, value] of Object.entries({ topic: 'Synthetic reviewed topic', language: 'en', source_urls: source.url,
      model_id: '3', account_id: '4', max_output_tokens: '128', max_cost_usd: '0.1' })) {
      const input = document.createElement('input'); input.name = name; input.value = value; form.append(input);
    }
    try {
      for (const change of [{ classification: ['unknown'] }, { classification: 'measured_demand' }, { revision: [1] },
        { revision: 0 }, { revision: 1.5 }, { revision: 2147483648 }, { label: '' }, { label: '  ' }, { label: 'x'.repeat(241) }]) {
        api.projectTopicReview.mockResolvedValue(response(valid)); await component.load();
        expect(component.topicReview()).toEqual(valid); expect(component.handoffError()).toBe('');
        api.projectTopicReview.mockResolvedValue(response({ ...valid, ...change })); await component.load(); fixture.detectChanges();
        expect(component.topicReview(), JSON.stringify(change)).toBeNull(); expect(component.handoffError()).toContain('changed');
        expect(component.selectedTopic()).toBe(''); expect(component.selectedLanguage()).toBe(''); expect(component.selectedMapping()).toBeNull();
        expect(fixture.nativeElement.textContent).not.toContain(language === 'tr' ? 'Kimliği doğrulanmış, tam güncel konu incelemesi' : 'Authenticated exact-current topic review');
        expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'güncel seçim yüklenene kadar araştırma engellenir' : 'research is blocked until a current selection is loaded');
        component.selectedModel.set(3); await component.create({ preventDefault: vi.fn(), target: form } as unknown as Event);
        expect(api.queueProjectResearch).not.toHaveBeenCalled();
      }
      for (const classification of ['unknown', 'trending', 'evergreen']) {
        api.projectTopicReview.mockResolvedValue(response({ ...valid, classification })); await component.load(); fixture.detectChanges();
        expect(component.topicReview()?.classification).toBe(classification); expect(component.handoffError()).toBe('');
        expect(component.selectedTopic()).toBe(valid.label); expect(component.selectedLanguage()).toBe('en');
        expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'insan ' + classification + ' değerlendirmesi' : 'human ' + classification + ' judgment');
        expect(fixture.nativeElement.querySelector('span[lang="en"]')!.textContent).toBe(classification);
      }
    } finally { fixture.destroy(); }
  });

  it('keeps only positive scalar current research mappings without selecting a zero identity by default', async () => {
    const { api, fixture, component } = await screen();
    const valid = { review_id: 91, revision: 1, label: 'Synthetic human mapping', language: 'en', market: 'Türkiye',
      page_kind: 'unmapped', preferred_page: '', proposed_action: 'unselected', source_current: true };
    const choices = (clusters: unknown[]): ApiResult => ({ status: 200, body: { project_id: 9, clusters } });
    try {
      api.intentClusters.mockResolvedValue(choices([{ ...valid, review_id: 0 }])); await component.load();
      expect(component.selectedMapping()).toBeNull(); expect(component.selectedTopic()).toBe(''); expect(component.mappings()).toEqual([]);
      for (const change of [{ review_id: 0 }, { review_id: -1 }, { review_id: [91] }, { revision: 0 }, { revision: 32768 },
        { revision: [1] }, { label: '  ' }, { label: 'x'.repeat(121) }, { language: ['en'] },
        { page_kind: ['unmapped'] }, { page_kind: 'inferred' }, { source_current: [true] }]) {
        api.intentClusters.mockResolvedValue(choices([valid, { ...valid, ...change }, null])); await component.load(); fixture.detectChanges();
        expect(component.mappings(), JSON.stringify(change)).toEqual([valid]); expect(component.error()).toBe('');
        expect(component.selectedMapping()).toBeNull(); expect(component.selectedTopic()).toBe('');
      }
      for (const page_kind of ['unmapped', 'proposed', 'existing_unverified']) {
        const row = { ...valid, page_kind, revision: 32767, preferred_page: page_kind === 'unmapped' ? '' : 'https://source.example.invalid/page' };
        api.intentClusters.mockResolvedValue(choices([row])); await component.load(); expect(component.mappings()).toEqual([row]);
      }
      vi.spyOn(TestBed.inject(ActivatedRoute).snapshot.queryParamMap, 'get').mockImplementation((key) => key === 'mapping' ? '91' : null);
      api.intentClusters.mockResolvedValue(choices([valid])); await component.load();
      expect(component.selectedMapping()).toBe(91); expect(component.selectedTopic()).toBe(valid.label);
      let finish!: (result: ApiResult) => void; const reads = api.intentClusters.mock.calls.length;
      api.intentClusters.mockReturnValueOnce(new Promise((resolve) => finish = resolve)); const refresh = component.load();
      expect(component.mappings()).toEqual([]); expect(component.selectedMapping()).toBeNull();
      await vi.waitFor(() => expect(api.intentClusters.mock.calls.length).toBe(reads + 1));
      finish({ status: 403, body: {} }); await refresh;
      expect(component.mappings()).toEqual([]); expect(api.queueProjectResearch).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it('denies unsupported project roles before research mapping and reviewed-topic reads and preserves all four scalar roles', async () => {
    const { api, fixture, component } = await screen('90');
    const context = (role: unknown): ApiResult => ({ status: 200, body: { project: {
      id: 9, organization_id: 7, name: 'Synthetic project', role } } });
    try {
      for (const role of [['owner'], ['admin'], ['member'], ['viewer'], null, {}, 'unsupported']) {
        api.projectOnboarding.mockResolvedValue(context('owner')); await component.load();
        expect(component.history()).toEqual([history]); expect(component.canLaunch()).toBe(true);
        api.projectOnboarding.mockResolvedValue(context(role));
        api.projectResearch.mockClear(); api.intentClusters.mockClear(); api.projectTopicReview.mockClear();
        const refresh = component.load(); expect(component.canLaunch()).toBe(false); expect(component.history()).toEqual([]);
        expect(component.models()).toEqual([]); expect(component.mappings()).toEqual([]); expect(component.topicReview()).toBeNull();
        await refresh; fixture.detectChanges();
        expect(component.error(), JSON.stringify(role)).toContain('unavailable');
        expect(api.projectResearch).not.toHaveBeenCalled(); expect(api.intentClusters).not.toHaveBeenCalled();
        expect(api.projectTopicReview).not.toHaveBeenCalled(); expect(api.queueProjectResearch).not.toHaveBeenCalled();
      }
      for (const role of ['owner', 'admin', 'member', 'viewer']) {
        api.projectOnboarding.mockResolvedValue(context(role)); api.projectResearch.mockClear();
        await component.load(); expect(component.error()).toBe(''); expect(component.history()).toEqual([history]);
        expect(component.canLaunch()).toBe(role !== 'viewer'); expect(api.projectResearch).toHaveBeenCalledTimes(1);
      }
    } finally { fixture.destroy(); }
  });

  it('shows only scalar current-project source rows and clears stale history during refresh', async () => {
    const { api, fixture, component } = await screen();
    try {
      expect(component.history()).toEqual([history]); expect(component.hasMore()).toBe(true);
      expect(fixture.nativeElement.textContent).toContain(history.topic);
      expect(fixture.nativeElement.textContent).not.toContain('No research job is recorded');
      expect(component.canLaunch()).toBe(false);
      for (const status of ['queued', 'running', 'waiting_provider', 'succeeded', 'failed', 'cancelled', 'partially_succeeded']) {
        api.projectResearch.mockResolvedValue(catalog([{ ...history, status }])); await component.load();
        expect(component.history()[0].status).toBe(status);
      }
      for (const row of [{ id: 72, status: 'succeeded', topic: history.topic, updated_at: history.updated_at },
        { ...history, project_id: 8 }, { ...history, id: 0 }, { ...history, id: 72.5 },
        { ...history, status: ['succeeded'] }, { ...history, topic: ['Invented label'] }, { ...history, updated_at: [] }]) {
        api.projectResearch.mockResolvedValue(catalog([row])); await component.load();
        expect(component.history(), JSON.stringify(row)).toEqual([]);
      }
      api.projectResearch.mockResolvedValue(catalog([{ ...history, project_id: 9 }])); await component.load();
      expect(component.history()[0].id).toBe(72);
      api.projectResearch.mockResolvedValue(catalog([history], 8)); await component.load();
      expect(component.history()).toEqual([]); expect(component.hasMore()).toBe(false);
      api.projectResearch.mockResolvedValue(catalog([history])); await component.load();
      let release!: (result: ApiResult) => void;
      api.projectResearch.mockReturnValueOnce(new Promise(resolve => { release = resolve; }));
      const reads = api.projectResearch.mock.calls.length, refresh = component.load();
      expect(component.history()).toEqual([]); expect(component.hasMore()).toBe(false);
      await vi.waitFor(() => expect(api.projectResearch.mock.calls.length).toBe(reads + 1));
      release({ status: 403, body: {} }); await refresh; fixture.detectChanges();
      expect(component.history()).toEqual([]); expect(component.error()).toContain('access was revoked');
      expect(api.projectResearchJob).not.toHaveBeenCalled(); expect(api.queueProjectResearch).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it('requires a scalar launch role and preserves owner/admin/member/viewer controls', async () => {
    const { api, fixture, component } = await screen();
    try {
      for (const role of [['owner'], ['admin'], ['member'], ['viewer'], 'owner', 'admin', 'member', 'viewer']) {
        api.projectOnboarding.mockResolvedValue({ status: 200, body: { project: { id: 9, organization_id: 7, name: 'Synthetic project', role } } });
        await component.load();
        expect(component.canLaunch(), JSON.stringify(role)).toBe(typeof role === 'string' && role !== 'viewer');
      }
      expect(api.queueProjectResearch).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it('filters malformed model tiers/account sources/pricing and preserves unknown-disabled and free-consent controls', async () => {
    const { api, fixture, component } = await screen();
    api.projectOnboarding.mockResolvedValue({ status: 200, body: { project: { id: 9, organization_id: 7, name: 'Synthetic project', role: 'member' } } });
    const model = { id: 3, provider_id: 5, name: 'Synthetic model', max_output_tokens: 200, privacy_policy_url: 'https://policy.example.invalid' };
    const account = { id: 4, provider_id: 5, label: 'Synthetic account' };
    const setCatalog = (tier: unknown, source: unknown, price: unknown = true) => api.projectResearch.mockResolvedValue({
      ...catalog([]), body: { ...catalog([]).body, models: [{ ...model, access_tier: tier, price_known: price }], accounts: [{ ...account, source }] } });
    try {
      for (const tier of [['unknown'], ['standard'], ['free']]) {
        setCatalog(tier, 'organization'); await component.load(); expect(component.models(), JSON.stringify(tier)).toEqual([]);
      }
      for (const source of [['platform'], ['organization']]) {
        setCatalog('standard', source); await component.load(); expect(component.accounts(), JSON.stringify(source)).toEqual([]);
      }
      setCatalog('standard', 'organization', [true]); await component.load(); expect(component.models()).toEqual([]);
      for (const tier of ['unknown', 'standard', 'free']) {
        setCatalog(tier, 'organization'); await component.load(); fixture.detectChanges();
        const select = fixture.nativeElement.querySelector('#research-model') as HTMLSelectElement;
        expect(select.querySelector<HTMLOptionElement>('option[value="3"]')!.disabled).toBe(tier === 'unknown');
        component.selectedModel.set(3); fixture.detectChanges();
        expect((fixture.nativeElement.querySelector('#research-free') as HTMLInputElement | null)?.required ?? false).toBe(tier === 'free');
      }
      setCatalog('unknown', 'organization'); await component.load(); component.selectedModel.set(3);
      const form = document.createElement('form'); vi.spyOn(form, 'reportValidity').mockReturnValue(true);
      for (const [name, value] of Object.entries({ topic: 'Actual human topic', language: 'en', source_urls: 'https://source.example.invalid/page',
        model_id: '3', account_id: '4', max_output_tokens: '128', max_cost_usd: '0.1' })) {
        const input = document.createElement('input'); input.name = name; input.value = value; form.append(input);
      }
      await component.create({ preventDefault: vi.fn(), target: form } as unknown as Event);
      expect(api.queueProjectResearch).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it('withholds previous launch role and catalog selection during refresh and after denied source context', async () => {
    const { api, fixture, component } = await screen();
    api.projectOnboarding.mockResolvedValue({ status: 200, body: { project: { id: 9, organization_id: 7, name: 'Synthetic project', role: 'member' } } });
    api.projectResearch.mockResolvedValue({ ...catalog([]), body: { ...catalog([]).body,
      models: [{ id: 3, provider_id: 5, name: 'Synthetic model', access_tier: 'standard', price_known: true, max_output_tokens: 200, privacy_policy_url: '' }],
      accounts: [{ id: 4, provider_id: 5, label: 'Synthetic account', source: 'organization' }] } });
    await component.load(); component.selectedModel.set(3);
    let release!: (result: ApiResult) => void;
    api.projectOnboarding.mockReturnValueOnce(new Promise(resolve => { release = resolve; }));
    const refresh = component.load();
    try {
      expect(component.canLaunch()).toBe(false); expect(component.models()).toEqual([]); expect(component.accounts()).toEqual([]);
      expect(component.selectedModel()).toBeNull();
      release({ status: 403, body: {} }); await refresh;
      expect(component.canLaunch()).toBe(false); expect(component.models()).toEqual([]); expect(component.accounts()).toEqual([]);
      api.projectResearch.mockResolvedValue({ status: 403, body: {} }); await component.load();
      expect(component.canLaunch()).toBe(false); expect(component.models()).toEqual([]); expect(component.accounts()).toEqual([]);
      expect(api.queueProjectResearch).not.toHaveBeenCalled();
    } finally { release({ status: 403, body: {} }); await refresh; fixture.destroy(); }
  });

  it('withholds malformed job and provider states and exact foreign detail/cancellation identities', async () => {
    const { api, fixture, component } = await screen();
    const states = ['queued', 'running', 'succeeded', 'failed', 'cancelled', 'partially_succeeded'];
    const usage = { request_status: 'unknown', estimated_cost_usd: null, reported_cost_usd: null };
    try {
      for (const change of [...states.map(status => ({ status: [status] })),
        ...['attempted', 'completed', 'failed', 'unknown'].map(request_status => ({ usage: { ...usage, request_status: [request_status] } }))]) {
        api.projectResearchJob.mockResolvedValue({ status: 200, body: { project_id: 9, job: { ...detail, ...change } } });
        await component.open(72); expect(component.job(), JSON.stringify(change)).toBeNull();
      }
      for (const status of states) {
        api.projectResearchJob.mockResolvedValue({ status: 200, body: { project_id: 9, job: { ...detail, status, usage } } });
        await component.open(72); expect(component.job()?.status).toBe(status); expect(component.job()?.usage?.reported_cost_usd).toBeNull();
      }
      for (const request_status of ['attempted', 'completed', 'failed', 'unknown']) {
        api.projectResearchJob.mockResolvedValue({ status: 200, body: { project_id: 9, job: { ...detail, usage: { ...usage, request_status } } } });
        await component.open(72); expect(component.job()?.usage?.request_status).toBe(request_status);
      }
      for (const body of [{ project_id: 8, job: detail }, { project_id: 9, job: { ...detail, id: 73 } }]) {
        api.projectResearchJob.mockResolvedValue({ status: 200, body }); await component.open(72); expect(component.job()).toBeNull();
      }
      api.projectOnboarding.mockResolvedValue({ status: 200, body: { project: { id: 9, organization_id: 7, name: 'Synthetic project', role: 'member' } } });
      await component.load();
      api.projectResearchJob.mockResolvedValue({ status: 200, body: { project_id: 9, job: { ...detail, status: 'queued' } } }); await component.open(72);
      api.projectResearchJob.mockResolvedValue({ status: 200, body: { project_id: 9, job: { ...detail, id: 73, status: 'cancelled' } } });
      await component.cancel(); expect(api.projectResearchJob).toHaveBeenLastCalledWith(7, 9, 72, true); expect(component.job()).toBeNull();
      expect(api.queueProjectResearch).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it('refuses malformed queue acknowledgments without automatically replaying and accepts a legitimate new job ID', async () => {
    const { api, fixture, component } = await screen();
    api.projectOnboarding.mockResolvedValue({ status: 200, body: { project: { id: 9, organization_id: 7, name: 'Synthetic project', role: 'member' } } });
    api.projectResearch.mockResolvedValue({ ...catalog([]), body: { ...catalog([]).body,
      models: [{ id: 3, provider_id: 5, name: 'Synthetic model', access_tier: 'standard', price_known: true, max_output_tokens: 200, privacy_policy_url: '' }],
      accounts: [{ id: 4, provider_id: 5, label: 'Synthetic account', source: 'organization' }] } });
    await component.load(); component.selectedModel.set(3);
    const form = document.createElement('form'); vi.spyOn(form, 'reportValidity').mockReturnValue(true);
    for (const [name, value] of Object.entries({ topic: 'Human topic', language: 'en', source_urls: 'https://source.example.invalid/page',
      model_id: '3', account_id: '4', max_output_tokens: '128', max_cost_usd: '0.1' })) {
      const input = document.createElement('input'); input.name = name; input.value = value; form.append(input);
    }
    const event = { preventDefault: vi.fn(), target: form } as unknown as Event;
    try {
      for (const body of [{ project_id: 9, job: { ...detail, status: ['queued'] } }, { project_id: 8, job: detail }]) {
        api.queueProjectResearch.mockResolvedValue({ status: 202, body }); await component.create(event);
        expect(component.job()).toBeNull(); expect(component.message()).toContain('Research request unavailable');
      }
      expect(api.queueProjectResearch).toHaveBeenCalledTimes(2);
      api.queueProjectResearch.mockResolvedValue({ status: 202, body: { project_id: 9, job: { ...detail, id: 73, status: 'queued' } } });
      await component.create(event); expect(component.job()?.id).toBe(73); expect(api.queueProjectResearch).toHaveBeenCalledTimes(3);
      expect(component.job()?.usage).toBeNull(); expect(component.message()).toContain('Research queued');
    } finally { fixture.destroy(); }
  });

  it('stops protected follow-up reads when pending project metadata arrives after destruction', async () => {
    const { api, fixture, component } = await screen();
    let release!: (value: ApiResult) => void;
    api.projectOnboarding.mockReturnValueOnce(new Promise(resolve => { release = resolve; }));
    const reads = [api.projectResearch.mock.calls.length, api.intentClusters.mock.calls.length];
    const reload = component.load(); fixture.destroy();
    release({ status: 200, body: { project: { id: 9, organization_id: 7, name: 'Synthetic project', role: 'member' } } }); await reload;
    expect([api.projectResearch.mock.calls.length, api.intentClusters.mock.calls.length]).toEqual(reads);
    expect(component.canLaunch()).toBe(false); expect(component.history()).toEqual([]); expect(api.queueProjectResearch).not.toHaveBeenCalled();
  });
  it('keeps invalid unavailable preferences and fresh production research English without queueing', async () => {
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    try {
      for (const mode of ['invalid', 'incompatible', 'signed-out', 'unavailable', 'production'] as const) {
        TestBed.resetTestingModule(); buildEnvironment.production = mode === 'production';
        const preference: ApiResult | Error = mode === 'unavailable' ? new Error('private preference error')
          : mode === 'signed-out' ? { status: 401, body: {} } : { status: 200, body: {
            language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: mode === 'incompatible' ? 'tr' : 'en', current_email_language: 'en' } };
        const { api, fixture, component } = await screen(undefined, preference);
        await fixture.whenStable(); fixture.detectChanges();
        expect(TestBed.inject(Title).getTitle()).toBe('Sourced topic research — OrganicSEOOps');
        expect(fixture.nativeElement.querySelector('section').getAttribute('lang')).toBe('en');
        expect(fixture.nativeElement.querySelector('h1').textContent).toBe('Research a project topic with explicit sources');
        expect(fixture.nativeElement.textContent).not.toContain('private preference error');
        expect(fixture.nativeElement.textContent).not.toContain('incelenmemiş Türkçe');
        if (mode === 'production') expect(component.productLanguage()).toBe('tr');
        api.projectOnboarding.mockResolvedValue({ status: 403, body: {} }); await component.load(); fixture.detectChanges();
        expect(fixture.nativeElement.querySelector('[role="alert"]').textContent).toContain('research context is unavailable');
        expect(api.queueProjectResearch).not.toHaveBeenCalled(); fixture.destroy();
      }
    } finally { buildEnvironment.production = production; }
  });

});
