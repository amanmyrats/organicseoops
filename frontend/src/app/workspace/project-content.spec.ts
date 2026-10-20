import { Title } from '@angular/platform-browser';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { BehaviorSubject } from 'rxjs';
import { vi } from 'vitest';
import { AccountApi, ApiResult } from '../account/account-api';
import { ProjectContent } from './project-content';
import { environment } from '../../environments/environment';

const revision = { id: 81, item_id: 80, project_id: 9, revision: 2, brief_id: 75,
  title: 'Synthetic human text', body: '<script>inert()</script>', meta_description: '', kind: 'blog',
  state: 'review', reason: 'Exact text review', created_at: '2026-01-01T00:00:00Z', actor_id: 1,
  reviewed_revision_id: null, approved_by_id: null, approved_at: null, generating_job_id: null,
  publication_url: '', published_at: null };
const briefEvidence = { version: 'content-brief-v1', project_id: 9, research_job_id: 72, action_review_id: 74,
  scope: 'human_authored_structure_and_unverified_ai_interpretation_not_publication',
  approval: 'draft_human_review_required_no_site_change', source_coverage: 'collected_selected_sources_only',
  topic: 'Synthetic content source', angle: 'Human angle', audience: 'User-entered audience',
  business_goal: 'User-entered goal', action_revision: 2, outline: ['Human heading'],
  research_summary_to_verify: 'Unverified source interpretation',
  claims_to_verify: [{ text: 'Unverified claim', quote: '<script>quoted()</script>', source_index: 0 }],
  sources: [{ index: 0, state: 'collected', url: 'https://source.example.invalid/article', title: 'Synthetic source',
    sha256: 'a'.repeat(64), retrieved_at: '2026-09-30T10:00:00Z' }] };
const generationJob = { id: 101, project_id: 9, status: 'queued', brief_id: 75, kind: 'blog', platform: '',
  source_current: true, estimate_units: 1, attempted_units: 0, cancel_requested: false, error_category: '',
  estimated_max_cost_usd: null, draft: null, usage: null };

function context(role: unknown): ApiResult {
  return { status: 200, body: { project: { id: 9, organization_id: 7, name: 'Synthetic project', role } } };
}

async function screen(preference: ApiResult | Error = { status: 200, body: { language: 'en', current_ui_language: 'en', current_email_language: 'en' } }) {
  const route = new BehaviorSubject(convertToParamMap({ organizationId: '7', projectId: '9' }));
  const api = {
    productLanguage: vi.fn(async (): Promise<ApiResult> => { if (preference instanceof Error) throw preference; return preference; }),
    projectOnboarding: vi.fn(async (): Promise<ApiResult> => context('owner')),
    projectBriefs: vi.fn(async (): Promise<ApiResult> => ({ status: 200, body: { project_id: 9,
      briefs: [{ id: 75, project_id: 9, research_job_id: 72, created_at: '2026-01-01T00:00:00Z' }] } })),
    projectResearch: vi.fn(async (): Promise<ApiResult> => ({ status: 200, body: { project_id: 9, models: [], accounts: [] } })),
    contentGeneration: vi.fn(async (_org: number, _project: number, _jobId = 0, _cancel = false): Promise<ApiResult> => ({ status: 200, body: { project_id: 9, jobs: [] } })),
    projectContent: vi.fn(async (_org: number, _project: number, item = 0): Promise<ApiResult> => ({ status: 200,
      body: item ? { project_id: 9, current: revision, history: [revision], next_before: null,
        brief: null, source_state: 'private_brief_unavailable' }
        : { project_id: 9, items: [revision], next_before: null } })),
    saveProjectContent: vi.fn(), generateProjectContent: vi.fn(),
  };
  TestBed.configureTestingModule({ providers: [provideRouter([]), { provide: AccountApi, useValue: api },
    { provide: ActivatedRoute, useValue: { paramMap: route.asObservable() } }] });
  const fixture = TestBed.createComponent(ProjectContent); fixture.detectChanges();
  await vi.waitFor(() => expect(fixture.componentInstance.loading()).toBe(false));
  return { api, fixture, component: fixture.componentInstance, route };
}

function commandEvent(fields: Record<string, string> = {}) {
  const form = document.createElement('form'); vi.spyOn(form, 'reportValidity').mockReturnValue(true);
  for (const [name, value] of Object.entries(fields)) {
    const input = document.createElement(name === 'body' ? 'textarea' : 'input'); input.name = name; input.value = value; form.append(input);
  }
  return { preventDefault: vi.fn(), target: form } as unknown as Event;
}

describe('Content studio private brief evidence', () => {
  it('withholds malformed studio brief provenance and human fields while preserving historical Unicode evidence', async () => {
    const { api, fixture, component } = await screen();
    const show = async (brief: unknown, source_state = 'current_review_still_required') => {
      api.projectContent.mockResolvedValue({ status: 200, body: { project_id: 9, current: revision,
        history: [revision], brief, source_state } });
      await component.open(80); fixture.detectChanges();
    };
    try {
      await show(briefEvidence); expect(component.evidence()).toEqual(briefEvidence);
      for (const change of [{ project_id: 10 }, { project_id: [9] }, { version: ['content-brief-v1'] },
        { research_job_id: [72] }, { research_job_id: 0 }, { research_job_id: 73 }, { action_review_id: true },
        { action_review_id: 0 }, { action_revision: [2] }, { action_revision: 32768 },
        { scope: 'publication_approved' }, { approval: ['draft_human_review_required_no_site_change'] },
        { source_coverage: ['partial'] }, { source_coverage: 'complete_site' }, { topic: {} }, { topic: ' ' },
        { topic: '😀'.repeat(241) }, { angle: [] }, { angle: '😀'.repeat(501) }, { audience: [] },
        { audience: '😀'.repeat(501) }, { business_goal: {} }, { business_goal: '😀'.repeat(241) },
        { outline: [] }, { outline: Array(13).fill('Heading') }, { outline: [null] }, { outline: [' '] },
        { outline: ['😀'.repeat(161)] }, { research_summary_to_verify: [] },
        { research_summary_to_verify: '😀'.repeat(3001) }]) {
        await show({ ...briefEvidence, ...change });
        expect(component.evidence(), JSON.stringify(change)).toBeNull();
        expect(component.current()).toEqual(revision);
        expect(fixture.nativeElement.textContent).toContain('Private source brief is unavailable');
      }
      // Older source briefs may be outside the current inventory page.
      component.briefs.set([]);
      const historical = { ...briefEvidence, source_coverage: 'partial', topic: '😀'.repeat(240),
        angle: '😀'.repeat(500), audience: '😀'.repeat(500), business_goal: '😀'.repeat(240),
        outline: ['😀'.repeat(160)], research_summary_to_verify: '😀'.repeat(3000) };
      await show(historical, 'stale_prepare_new_brief_before_review');
      expect(component.evidence()).toEqual(historical);
      expect(component.sourceState()).toBe('stale_prepare_new_brief_before_review');
      expect(fixture.nativeElement.querySelector('script')).toBeNull();
      expect(api.saveProjectContent).not.toHaveBeenCalled(); expect(api.generateProjectContent).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it('requires aware original studio source retrieval dates while retaining historical missing observations', async () => {
    const { api, fixture, component } = await screen(); const source = briefEvidence.sources[0];
    const show = async (brief: unknown) => {
      api.projectContent.mockResolvedValue({ status: 200, body: { project_id: 9, current: revision,
        history: [revision], brief, source_state: 'stale_prepare_new_brief_before_review' } });
      await component.open(80); fixture.detectChanges();
    };
    try {
      for (const retrieved_at of ['yesterday', '2026-01-01', '2026-01-01T00:00:00', '2026-01-01T25:00:00Z']) {
        await show({ ...briefEvidence, sources: [{ ...source, retrieved_at }] }); expect(component.evidence(), retrieved_at).toBeNull();
        await show({ ...briefEvidence, source_coverage: 'partial', sources: [source, { index: 1, state: 'unavailable', retrieved_at }] });
        expect(component.evidence()).toBeNull(); expect(component.current()).toEqual(revision);
      }
      for (const retrieved_at of ['2026-01-01T00:00:00Z', '2026-01-01T00:00:00.123456+00:00', '2026-01-01T05:00:00.123456+05:00']) {
        const brief = { ...briefEvidence, source_coverage: 'partial', sources: [{ ...source, retrieved_at },
          { index: 1, state: 'unavailable' }, { index: 2, state: 'unavailable', retrieved_at }] };
        await show(brief); expect(component.evidence()).toEqual(brief); expect(fixture.nativeElement.textContent).toContain(retrieved_at);
        expect(fixture.nativeElement.textContent).toContain('retrieval unavailable');
        expect(component.sourceState()).toBe('stale_prepare_new_brief_before_review');
        expect(fixture.nativeElement.querySelector('script')).toBeNull();
      }
      expect(api.saveProjectContent).not.toHaveBeenCalled(); expect(api.generateProjectContent).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it('requires scalar current or stale studio brief status and withholds unknown or unavailable evidence', async () => {
    const { api, fixture, component } = await screen();
    const show = async (source_state: unknown, brief: unknown = briefEvidence) => {
      api.projectContent.mockResolvedValue({ status: 200, body: { project_id: 9, current: revision,
        history: [revision], brief, source_state } }); await component.open(80); fixture.detectChanges();
    };
    try {
      for (const state of [['current_review_still_required'], ['stale_prepare_new_brief_before_review'],
        {}, null, undefined, 'approved', 'private_brief_unavailable']) {
        await show(state); expect(component.evidence(), JSON.stringify(state)).toBeNull();
        expect(component.sourceState()).toBe('private_brief_unavailable'); expect(component.current()).toEqual(revision);
      }
      for (const state of ['current_review_still_required', 'stale_prepare_new_brief_before_review']) {
        await show(state); expect(component.evidence()).toEqual(briefEvidence); expect(component.sourceState()).toBe(state);
        await show(state, null); expect(component.evidence()).toBeNull(); expect(component.sourceState()).toBe('private_brief_unavailable');
      }
      expect(api.saveProjectContent).not.toHaveBeenCalled(); expect(api.generateProjectContent).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it('clears previous studio source status and evidence during pending history reads and after rejected delivery', async () => {
    const { api, fixture, component } = await screen();
    api.projectContent.mockResolvedValue({ status: 200, body: { project_id: 9, current: revision,
      history: [revision], brief: briefEvidence, source_state: 'current_review_still_required' } });
    await component.open(80);
    let release!: (value: ApiResult) => void;
    api.projectContent.mockReturnValueOnce(new Promise(resolve => { release = resolve; }));
    const pending = component.open(80, 2);
    try {
      expect(component.evidence()).toBeNull(); expect(component.sourceState()).toBe('');
      expect(component.current()).toEqual(revision);
      release({ status: 403, body: {} }); await pending; fixture.detectChanges();
      expect(component.evidence()).toBeNull(); expect(component.sourceState()).toBe('');
      expect(component.message()).toContain('Content revision unavailable');
    } finally { release({ status: 403, body: {} }); await pending; fixture.destroy(); }
  });

  it('rejects malformed studio brief sources and unlinked claims without losing original partial quotes and indices', async () => {
    const { api, fixture, component } = await screen();
    const source = briefEvidence.sources[0], claim = briefEvidence.claims_to_verify[0];
    const show = async (brief: unknown) => {
      api.projectContent.mockResolvedValue({ status: 200, body: { project_id: 9, current: revision,
        history: [revision], brief, source_state: 'stale_prepare_new_brief_before_review' } });
      await component.open(80); fixture.detectChanges();
    };
    try {
      for (const change of [{ sources: [] }, { sources: [null] }, { sources: [{ ...source, index: [0] }] },
        { sources: [source, source] }, { sources: [{ ...source, state: ['collected'] }] },
        { sources: [{ ...source, index: 5 }] }, { sources: [{ ...source, url: ['https://source.example.invalid/article'] }] },
        { sources: [{ ...source, url: 'javascript:alert(1)' }] }, { sources: [{ ...source, url: 'https://source.example.invalid/article?secret=1' }] },
        { sources: [{ ...source, title: [] }] }, { sources: [{ ...source, title: '😀'.repeat(241) }] },
        { sources: [{ ...source, sha256: 'invalid' }] }, { sources: [{ ...source, retrieved_at: [] }] },
        { sources: [{ ...source, retrieved_at: '' }] }, { sources: [{ index: 0, state: 'unavailable' }] },
        { claims_to_verify: [] }, { claims_to_verify: [null] }, { claims_to_verify: Array(11).fill(claim) },
        { claims_to_verify: [{ ...claim, text: [] }] }, { claims_to_verify: [{ ...claim, text: '😀'.repeat(501) }] },
        { claims_to_verify: [{ ...claim, quote: [] }] }, { claims_to_verify: [{ ...claim, quote: ' ' }] },
        { claims_to_verify: [{ ...claim, quote: '😀'.repeat(301) }] }, { claims_to_verify: [{ ...claim, source_index: [0] }] },
        { claims_to_verify: [{ ...claim, source_index: 1 }] }]) {
        await show({ ...briefEvidence, ...change }); expect(component.evidence(), JSON.stringify(change)).toBeNull();
      }
      const historical = { ...briefEvidence, source_coverage: 'partial', sources: [{ index: 0, state: 'unavailable' },
        { ...source, index: 2, title: '😀'.repeat(240) }],
        claims_to_verify: [{ ...claim, source_index: 2, text: '😀'.repeat(500), quote: '😀'.repeat(300) },
          { ...claim, source_index: 2 }] };
      await show(historical); expect(component.evidence()).toEqual(historical);
      const panel = fixture.nativeElement.querySelector('#content-brief-title').parentElement;
      expect(panel.textContent).toContain('source 3'); expect(panel.textContent).toContain('<script>quoted()</script>');
      expect(panel.querySelector('script')).toBeNull(); expect(panel.querySelector('a').href).toBe(source.url);
      expect(panel.textContent).toContain('Human verification required');
      await show({ ...historical, claims_to_verify: [{ ...claim, source_index: 0 }] }); expect(component.evidence()).toBeNull();
    } finally { fixture.destroy(); }
  });
});

describe('Content studio current human role', () => {
  it('requires scalar roles for editing and exact-current approval while preserving valid role controls', async () => {
    const { api, fixture, component } = await screen();
    try {
      for (const role of [['owner'], ['admin'], ['member'], ['viewer'], {}, null, undefined, 'unknown']) {
        api.projectOnboarding.mockResolvedValue(context(role)); await component.load(); fixture.detectChanges();
        expect(component.canEdit(), JSON.stringify(role)).toBe(false); expect(component.canApprove()).toBe(false);
        expect(fixture.nativeElement.querySelector('#content-state')).toBeNull();
        await component.save(commandEvent()); await component.generate(commandEvent());
        expect(api.saveProjectContent).not.toHaveBeenCalled(); expect(api.generateProjectContent).not.toHaveBeenCalled();
      }
      for (const role of ['owner', 'admin', 'member', 'viewer']) {
        api.projectOnboarding.mockResolvedValue(context(role)); await component.load(); await component.open(80); fixture.detectChanges();
        expect(component.canEdit()).toBe(role !== 'viewer');
        expect(component.canApprove()).toBe(['owner', 'admin'].includes(role));
        expect(component.states().includes('approved')).toBe(['owner', 'admin'].includes(role));
        expect(component.states().includes('archived')).toBe(['owner', 'admin'].includes(role));
        expect(fixture.nativeElement.querySelector('#content-state') !== null).toBe(role !== 'viewer');
        expect(fixture.nativeElement.querySelector('script')).toBeNull();
        expect(component.current()?.body).toBe('<script>inert()</script>');
      }
    } finally { fixture.destroy(); }
  });

  it('withholds old writing and approval while refreshing and after denied metadata', async () => {
    const { api, fixture, component } = await screen();
    let release!: (value: ApiResult) => void;
    api.projectOnboarding.mockReturnValueOnce(new Promise(resolve => { release = resolve; }));
    const refresh = component.load();
    try {
      expect(component.loading()).toBe(true); expect(component.canEdit()).toBe(false); expect(component.canApprove()).toBe(false);
      await component.save(commandEvent()); await component.generate(commandEvent());
      expect(api.saveProjectContent).not.toHaveBeenCalled(); expect(api.generateProjectContent).not.toHaveBeenCalled();
      release({ status: 403, body: {} }); await refresh; fixture.detectChanges();
      expect(component.canEdit()).toBe(false); expect(component.canApprove()).toBe(false);
      expect(component.error()).toContain('access revoked'); expect(fixture.nativeElement.querySelector('form')).toBeNull();
      await component.load(); expect(component.canEdit()).toBe(true); expect(component.canApprove()).toBe(true);
    } finally { release({ status: 403, body: {} }); await refresh; fixture.destroy(); }
  });

  it('rejects array or inherited transition keys before showing current text and preserves every scalar content state', async () => {
    const { api, fixture, component } = await screen();
    const transitions: Record<string, string[]> = {
      idea: ['research', 'brief', 'draft', 'archived'], research: ['brief', 'draft', 'archived'], brief: ['draft', 'archived'],
      draft: ['draft', 'review', 'archived'], review: ['draft', 'approved', 'archived'],
      approved: ['draft', 'published', 'archived'], published: ['draft', 'archived'], archived: ['draft'],
    };
    try {
      for (const state of [...Object.keys(transitions).map(state => [state]), 'constructor', 'toString', '__proto__']) {
        api.projectContent.mockResolvedValue({ status: 200, body: { project_id: 9,
          current: { ...revision, state }, history: [revision], next_before: null } });
        await component.open(80); fixture.detectChanges();
        expect(component.current(), JSON.stringify(state)).toBeNull();
        expect(fixture.nativeElement.querySelector('section[aria-labelledby="content-preview-title"]')).toBeNull();
        expect(component.message()).toContain('Content revision unavailable');
      }
      for (const [state, next] of Object.entries(transitions)) {
        const approval = ['approved', 'published'].includes(state)
          ? { reviewed_revision_id: 79, approved_by_id: 1, approved_at: '2026-01-01T00:00:00Z' } : {};
        api.projectContent.mockResolvedValue({ status: 200, body: { project_id: 9,
          current: { ...revision, state, ...approval, ...(state === 'published'
            ? { publication_url: 'https://project.example.invalid/page', published_at: '2026-01-01T00:00:00Z' } : {}) },
          history: [revision], next_before: null } });
        await component.open(80); fixture.detectChanges();
        expect(component.current()?.state).toBe(state); expect(component.states()).toEqual(next);
        expect(fixture.nativeElement.querySelector('script')).toBeNull();
      }
      expect(api.saveProjectContent).not.toHaveBeenCalled(); expect(api.generateProjectContent).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it('rejects malformed model tiers/account sources/pricing and preserves unknown-disabled and free-consent controls', async () => {
    const { api, fixture, component } = await screen();
    const model = { id: 3, provider_id: 5, name: 'Synthetic model', price_known: true,
      privacy_policy_url: 'https://policy.example.invalid', max_output_tokens: 200 };
    const account = { id: 4, provider_id: 5, label: 'Synthetic account' };
    const catalog = (tier: unknown, source: unknown, price: unknown = true): ApiResult => ({ status: 200, body: { project_id: 9,
      models: [{ ...model, access_tier: tier, price_known: price }], accounts: [{ ...account, source }] } });
    try {
      for (const [tier, source, price] of [
        [['unknown'], 'platform', true], [['standard'], 'organization', true], [['free'], 'organization', true],
        [undefined, 'organization', true], ['unrecognized', 'organization', true],
        ['standard', ['platform'], true], ['standard', ['organization'], true], ['standard', 'unrecognized', true],
        ['standard', 'organization', [true]],
      ]) {
        api.projectResearch.mockResolvedValue(catalog(tier, source, price)); await component.load(); fixture.detectChanges();
        expect(component.models(), JSON.stringify([tier, source, price])).toEqual([]); expect(component.accounts()).toEqual([]);
        expect(fixture.nativeElement.querySelector('#generation-model')).toBeNull();
      }
      for (const [tier, source] of [['unknown', 'platform'], ['standard', 'organization'], ['free', 'organization']]) {
        api.projectResearch.mockResolvedValue(catalog(tier, source)); await component.load(); fixture.detectChanges();
        const select = fixture.nativeElement.querySelector('#generation-model') as HTMLSelectElement;
        expect(select.querySelector<HTMLOptionElement>('option[value="3"]')!.disabled).toBe(tier === 'unknown');
        component.selectedModel.set(3); fixture.detectChanges();
        expect((fixture.nativeElement.querySelector('input[name="allow_free"]') as HTMLInputElement | null)?.required ?? false).toBe(tier === 'free');
        expect(fixture.nativeElement.querySelector('#generation-account').textContent).toContain(source);
      }
      expect(api.generateProjectContent).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it('withholds malformed studio catalogue scalars before model or account selection', async () => {
    const { api, fixture, component } = await screen();
    const model = { id: 3, provider_id: 5, name: 'Synthetic model', access_tier: 'standard', price_known: true,
      privacy_policy_url: '', max_output_tokens: 200 };
    const account = { id: 4, provider_id: 5, label: 'Synthetic account', source: 'organization' };
    const cases: [string, string, unknown[]][] = [
      ['model', 'id', [0, -1, 1.5, '3', [3], true, null, undefined, Number.MAX_SAFE_INTEGER + 1]],
      ['model', 'provider_id', [0, -1, '5', [5], {}, null, Number.MAX_SAFE_INTEGER + 1]],
      ['model', 'name', [[], {}, null, undefined, '', ' ', 'a'.repeat(121), '😀'.repeat(121)]],
      ['model', 'max_output_tokens', [0, -1, 1.5, '200', [200], {}, undefined, 10000001]],
      ['model', 'privacy_policy_url', [[], {}, null, undefined, 'javascript:alert(1)', 'http://policy.example.invalid',
        'https://user:password@policy.example.invalid', 'https://policy.example.invalid/?token=private',
        'https://policy.example.invalid/#private', 'https://policy.example.invalid/' + 'a'.repeat(1024)]],
      ['account', 'id', [0, -1, 1.5, '4', [4], true, null, undefined, Number.MAX_SAFE_INTEGER + 1]],
      ['account', 'provider_id', [0, -1, '5', [5], {}, null, Number.MAX_SAFE_INTEGER + 1]],
      ['account', 'label', [[], {}, null, undefined, '', ' ', 'a'.repeat(81), '😀'.repeat(81)]],
    ];
    try {
      for (const [kind, field, values] of cases) for (const value of values) {
        api.projectResearch.mockResolvedValue({ status: 200, body: { project_id: 9,
          models: [kind === 'model' ? { ...model, [field]: value } : model],
          accounts: [kind === 'account' ? { ...account, [field]: value } : account] } });
        await component.load(); fixture.detectChanges();
        expect(component.models(), `${kind}.${field}=${JSON.stringify(value)}`).toEqual([]);
        expect(component.accounts()).toEqual([]); expect(component.selectedModel()).toBe(0);
        expect(fixture.nativeElement.querySelector('#generation-model')).toBeNull();
      }
      api.projectResearch.mockResolvedValue({ status: 200, body: { project_id: 9,
        models: [{ ...model, access_tier: 'free' }], accounts: [account] } });
      await component.load(); expect(component.models()).toEqual([]); expect(component.accounts()).toEqual([]);
      expect(api.generateProjectContent).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it('preserves Unicode studio catalogue bounds, nullable model caps and exact provider-account choices', async () => {
    const { api, fixture, component } = await screen();
    const prefix = 'https://policy.example.invalid/';
    const policy = prefix + '😀'.repeat(1024 - prefix.length);
    const account = { id: 4, provider_id: 5, label: '😀'.repeat(80), source: 'organization' };
    try {
      for (const cap of [null, 1, 10000000]) for (const tier of ['unknown', 'standard', 'free']) {
        const model = { id: 3, provider_id: 5, name: '😀'.repeat(120), access_tier: tier, price_known: true,
          privacy_policy_url: tier === 'free' ? policy : '', max_output_tokens: cap };
        api.projectResearch.mockResolvedValue({ status: 200, body: { project_id: 9,
          models: [model, { ...model, id: 6, provider_id: 7, name: '<script>inert()</script>' }],
          accounts: [account, { ...account, id: 8, provider_id: 7, label: '<script>inert()</script>', source: 'platform' }] } });
        await component.load(); component.selectedModel.set(3); fixture.detectChanges();
        expect(component.models()[0]).toEqual(model); expect(component.generationAccounts()).toEqual([account]);
        const element = fixture.nativeElement as HTMLElement;
        expect(element.querySelector('script')).toBeNull();
        expect(element.querySelector<HTMLOptionElement>('#generation-model option[value="3"]')!.disabled).toBe(tier === 'unknown');
        expect(element.querySelector<HTMLInputElement>('input[name="allow_free"]')?.required ?? false).toBe(tier === 'free');
        if (tier === 'free') expect(element.querySelector<HTMLAnchorElement>('a[target="_blank"]')!.href).toBe(new URL(policy).href);
        component.selectedModel.set(6); fixture.detectChanges();
        expect(component.generationAccounts().map(row => row.id)).toEqual([8]);
        expect(element.querySelector('#generation-account')!.textContent).toContain('<script>inert()</script>');
      }
      for (const [kind, field, value] of [
        ['model', 'name', '😀'.repeat(121)], ['account', 'label', '😀'.repeat(81)], ['model', 'privacy_policy_url', policy + '😀'],
      ]) {
        const model = { id: 3, provider_id: 5, name: 'Model', access_tier: 'free', price_known: true,
          privacy_policy_url: policy, max_output_tokens: null };
        api.projectResearch.mockResolvedValue({ status: 200, body: { project_id: 9,
          models: [kind === 'model' ? { ...model, [field]: value } : model],
          accounts: [kind === 'account' ? { ...account, [field]: value } : account] } });
        await component.load(); expect(component.models()).toEqual([]); expect(component.accounts()).toEqual([]);
      }
      expect(api.generateProjectContent).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it('enforces studio request and selected model output caps before queuing a draft', async () => {
    const { api, fixture, component } = await screen();
    const catalog = (cap: number | null): ApiResult => ({ status: 200, body: { project_id: 9,
      models: [{ id: 3, provider_id: 5, name: 'Model', access_tier: 'standard', price_known: true,
        privacy_policy_url: '', max_output_tokens: cap }],
      accounts: [{ id: 4, provider_id: 5, label: 'Account', source: 'platform' }] } });
    const event = (tokens: string) => commandEvent({ brief_id: '75', account_id: '4', kind: 'blog', max_output_tokens: tokens, max_cost_usd: '0.1' });
    api.generateProjectContent.mockResolvedValue({ status: 202, body: { project_id: 9, job: generationJob } });
    try {
      for (const [cap, tokens] of [[200, '201'], [128, '129'], [1, '128'], [null, '127'], [null, '2049'],
        [null, '128.5'], [null, 'NaN'], [null, 'Infinity'], [null, '']] as [number | null, string][]) {
        api.projectResearch.mockResolvedValue(catalog(cap)); await component.load(); component.selectedModel.set(3);
        await component.generate(event(tokens));
        expect(api.generateProjectContent, `${cap}/${tokens}`).not.toHaveBeenCalled();
        expect(component.busy()).toBe(false); expect(component.generationJob()).toBeNull();
      }
      for (const [cap, tokens] of [[128, '128'], [200, '200'], [null, '2048'], [10000000, '2048']] as [number | null, string][]) {
        api.projectResearch.mockResolvedValue(catalog(cap)); await component.load(); component.selectedModel.set(3); fixture.detectChanges();
        expect((fixture.nativeElement.querySelector('#generation-tokens') as HTMLInputElement).max).toBe(String(Math.min(cap ?? 2048, 2048)));
        await component.generate(event(tokens));
        expect(api.generateProjectContent.mock.calls.at(-1)![2].max_output_tokens).toBe(Number(tokens));
        expect(api.generateProjectContent.mock.calls.at(-1)![2].allow_free).toBe(false);
      }
      expect(api.generateProjectContent).toHaveBeenCalledTimes(4);
    } finally { fixture.destroy(); }
  });

  it.each(['en', 'tr'] as const)('requires deliberate studio free-tier consent and preserves standard model selection in %s', async (language) => {
    const { api, fixture, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } });
    const event = (consent: boolean) => commandEvent({ brief_id: '75', account_id: '4', kind: 'blog', max_output_tokens: '128',
      max_cost_usd: '0.1', ...(consent ? { allow_free: 'on' } : {}) });
    const catalog = (tier: string): ApiResult => ({ status: 200, body: { project_id: 9,
      models: [{ id: 3, provider_id: 5, name: 'Model', access_tier: tier, price_known: true,
        privacy_policy_url: 'https://policy.example.invalid/', max_output_tokens: 200 }],
      accounts: [{ id: 4, provider_id: 5, label: 'Account', source: 'organization' }] } });
    api.generateProjectContent.mockResolvedValue({ status: 202, body: { project_id: 9, job: generationJob } });
    try {
      api.projectResearch.mockResolvedValue(catalog('free')); await component.load(); component.selectedModel.set(3);
      fixture.detectChanges();
      const form = fixture.nativeElement.querySelector('section[aria-labelledby="content-generation-title"] form') as HTMLFormElement;
      const consent = form.querySelector<HTMLInputElement>('input[name="allow_free"]')!;
      expect(consent.required).toBe(true); expect(consent.checked).toBe(false);
      expect(consent.parentElement!.textContent).toContain(component.t("I explicitly permit this free-tier model's data use for this request."));
      expect(fixture.nativeElement.textContent).toContain(component.t('Free-tier terms may allow training or retention of confidential data.'));
      expect(form.querySelector<HTMLAnchorElement>('a')?.href).toBe('https://policy.example.invalid/');
      expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Özel içerik stüdyosu — OrganicSEOOps' : 'Private content studio — OrganicSEOOps');
      consent.checked = true;
      component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
      expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Private content studio — OrganicSEOOps' : 'Özel içerik stüdyosu — OrganicSEOOps');
      expect(fixture.nativeElement.querySelector('section[aria-labelledby="content-generation-title"] form')).toBe(form);
      expect(form.querySelector('input[name="allow_free"]')).toBe(consent); expect(consent.checked).toBe(true);
      expect(component.selectedModel()).toBe(3); expect(api.generateProjectContent).not.toHaveBeenCalled();
      component.productLanguage.set(language); fixture.detectChanges();
      await component.generate(event(false)); expect(api.generateProjectContent).not.toHaveBeenCalled();
      await component.generate(event(true)); expect(api.generateProjectContent).toHaveBeenCalledTimes(1);
      expect(api.generateProjectContent.mock.calls[0][2].allow_free).toBe(true);
      api.projectResearch.mockResolvedValue(catalog('standard')); await component.load(); component.selectedModel.set(3);
      await component.generate(event(true)); expect(api.generateProjectContent).toHaveBeenCalledTimes(2);
      expect(api.generateProjectContent.mock.calls[1][2].allow_free).toBe(false);
      expect(api.generateProjectContent.mock.calls[1][2].model_id).toBe(3);
      expect(api.generateProjectContent.mock.calls[1][2].account_id).toBe(4);
    } finally { fixture.destroy(); }
    TestBed.inject(Title).setTitle('Next route — OrganicSEOOps');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); TestBed.tick();
    expect(TestBed.inject(Title).getTitle()).toBe('Next route — OrganicSEOOps');
  });

  it('clears stale catalog and selection on refresh and refuses a priced unknown tier without a generation request', async () => {
    const { api, fixture, component } = await screen();
    api.projectResearch.mockResolvedValue({ status: 200, body: { project_id: 9,
      models: [{ id: 3, provider_id: 5, name: 'Synthetic unknown model', access_tier: 'unknown', price_known: true,
        privacy_policy_url: '', max_output_tokens: 200 }],
      accounts: [{ id: 4, provider_id: 5, label: 'Synthetic account', source: 'organization' }] } });
    await component.load(); component.selectedModel.set(3);
    const event = commandEvent(), form = event.target as HTMLFormElement;
    for (const [name, value] of Object.entries({ account_id: '4', brief_id: '75', kind: 'blog', max_output_tokens: '128', max_cost_usd: '0.1' })) {
      const input = document.createElement('input'); input.name = name; input.value = value; form.append(input);
    }
    try {
      await component.generate(event); expect(api.generateProjectContent).not.toHaveBeenCalled();
      let release!: (result: ApiResult) => void;
      api.projectResearch.mockReturnValueOnce(new Promise(resolve => { release = resolve; }));
      const reads = api.projectResearch.mock.calls.length;
      const refresh = component.load();
      expect(component.models()).toEqual([]); expect(component.accounts()).toEqual([]); expect(component.selectedModel()).toBe(0);
      await vi.waitFor(() => expect(api.projectResearch.mock.calls.length).toBe(reads + 1));
      release({ status: 403, body: {} }); await refresh;
      expect(component.models()).toEqual([]); expect(component.accounts()).toEqual([]);
      fixture.detectChanges(); expect(fixture.nativeElement.querySelector('#generation-model')).toBeNull();
    } finally { fixture.destroy(); }
  });

  it('withholds malformed studio brief creation dates and preserves raw aware catalogue snapshots', async () => {
    const { api, fixture, component } = await screen();
    const brief = { id: 75, project_id: 9, research_job_id: 72, created_at: '2026-01-01T00:00:00Z' };
    try {
      for (const created_at of ['yesterday', '2026-01-01', '2026-01-01T00:00:00', '2026-01-01T25:00:00Z']) {
        api.projectBriefs.mockResolvedValue({ status: 200, body: { project_id: 9, briefs: [{ ...brief, created_at }] } });
        await component.load(); fixture.detectChanges(); expect(component.briefs(), created_at).toEqual([]);
        expect(fixture.nativeElement.querySelector('#content-brief')).toBeNull();
        expect(fixture.nativeElement.querySelector('#generation-brief')).toBeNull();
      }
      for (const created_at of ['2026-01-01T00:00:00Z', '2026-01-01T00:00:00.123456+00:00', '2026-01-01T05:00:00.123456+05:00']) {
        const valid = { ...brief, created_at };
        api.projectBriefs.mockResolvedValue({ status: 200, body: { project_id: 9, briefs: [valid] } });
        await component.load(); fixture.detectChanges(); expect(component.briefs()).toEqual([valid]);
        expect(fixture.nativeElement.querySelector('#content-brief').textContent).toContain(created_at);
        await component.open(80); expect(component.hasCurrentBrief()).toBe(true);
      }
      expect(api.saveProjectContent).not.toHaveBeenCalled(); expect(api.generateProjectContent).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it('withholds malformed scoped studio brief choices and preserves valid source and older-current provenance', async () => {
    const { api, fixture, component } = await screen();
    const brief = { id: 75, project_id: 9, research_job_id: 72, created_at: '2026-01-01T00:00:00Z' };
    try {
      for (const change of [
        ...[0, -1, 1.5, '75', [75], null, undefined, Number.MAX_SAFE_INTEGER + 1].map(id => ({ id })),
        ...[0, -1, 1.5, '72', [72], null, undefined, Number.MAX_SAFE_INTEGER + 1].map(research_job_id => ({ research_job_id })),
        ...[[], {}, null, undefined, '', '  '].map(created_at => ({ created_at })),
        { project_id: 10 },
      ]) {
        api.projectBriefs.mockResolvedValue({ status: 200, body: { project_id: 9, briefs: [{ ...brief, ...change }] } });
        await component.load(); fixture.detectChanges();
        expect(component.briefs(), JSON.stringify(change)).toEqual([]);
        expect(fixture.nativeElement.querySelector('#content-brief')).toBeNull();
        expect(fixture.nativeElement.querySelector('#generation-brief')).toBeNull();
      }
      api.projectBriefs.mockResolvedValue({ status: 200, body: { project_id: 9,
        briefs: [null, { ...brief, id: 0 }, brief] } });
      await component.load(); fixture.detectChanges(); expect(component.briefs()).toEqual([brief]);
      expect(fixture.nativeElement.querySelector('#content-brief').textContent).toContain('research 72');
      await component.open(80); expect(component.hasCurrentBrief()).toBe(true);
      api.projectContent.mockResolvedValue({ status: 200, body: { project_id: 9, current: { ...revision, brief_id: 76 }, history: [revision] } });
      await component.open(80); fixture.detectChanges(); expect(component.hasCurrentBrief()).toBe(false);
      expect(fixture.nativeElement.querySelector('#content-brief option[value="76"]').textContent).toContain('older snapshot');
      for (const result of [{ status: 403, body: {} }, { status: 200, body: { project_id: 10, briefs: [brief] } }]) {
        api.projectBriefs.mockResolvedValue(result); await component.load(); expect(component.briefs()).toEqual([]);
      }
      expect(api.saveProjectContent).not.toHaveBeenCalled(); expect(api.generateProjectContent).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it('rejects malformed studio revision identities in inventory and current inspection', async () => {
    const { api, fixture, component } = await screen();
    const cases: [string, unknown[]][] = [
      ...['id', 'item_id', 'brief_id', 'actor_id'].map(field => [field, [0, -1, 1.5, '81', [81], null, undefined, Number.MAX_SAFE_INTEGER + 1]] as [string, unknown[]]),
      ['revision', [0, -1, 1.5, '2', [2], null, undefined, 2147483648]],
      ['state', [['review'], 'constructor', 'toString', '__proto__', null, undefined]],
      ['kind', [['blog'], 'unsupported', null, undefined]],
    ];
    try {
      for (const [field, values] of cases) for (const value of values) {
        const row = { ...revision, [field]: value };
        api.projectContent.mockResolvedValue({ status: 200, body: { project_id: 9, items: [row], current: row, history: [row] } });
        await component.load(); expect(component.items(), `${field}=${JSON.stringify(value)}`).toEqual([]);
        await component.open(80); expect(component.current()).toBeNull(); expect(component.history()).toEqual([]);
      }
      for (const kind of component.kinds) for (const number of [1, 2147483647]) {
        const row = { ...revision, kind, revision: number, brief_id: Number.MAX_SAFE_INTEGER, actor_id: Number.MAX_SAFE_INTEGER };
        api.projectContent.mockResolvedValue({ status: 200, body: { project_id: 9, items: [row], current: row, history: [row] } });
        await component.load(); expect(component.items()).toEqual([row]);
        await component.open(80); expect(component.current()).toEqual(row);
      }
      expect(api.saveProjectContent).not.toHaveBeenCalled(); expect(api.generateProjectContent).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it('filters malformed revision history and keeps wrong-scope or wrong-item save acknowledgments uncertain', async () => {
    const { api, fixture, component } = await screen();
    const older = { ...revision, id: 79, revision: 1, state: 'draft' };
    api.projectContent.mockResolvedValue({ status: 200, body: { project_id: 9, current: revision,
      history: [null, { ...older, actor_id: 0 }, { ...older, state: ['draft'] }, { ...older, item_id: 90 },
        { ...older, project_id: 10 }, older] } });
    try {
      await component.open(80); fixture.detectChanges();
      expect(component.current()).toEqual(revision); expect(component.history()).toEqual([older]);
      component.comparison.set(component.history()[0]); fixture.detectChanges();
      expect(fixture.nativeElement.textContent).toContain('Compared revision 1'); expect(fixture.nativeElement.querySelector('script')).toBeNull();
      for (const body of [
        { project_id: 10, revision: { ...revision, revision: 3 } },
        ...[{ id: 0 }, { item_id: 0 }, { item_id: 90 }, { brief_id: 0 }, { actor_id: 0 }, { revision: 0 }, { kind: ['blog'] }, { state: ['draft'] }]
          .map(change => ({ project_id: 9, revision: { ...revision, revision: 3, ...change } })),
      ]) {
        const reads = api.projectContent.mock.calls.length;
        api.saveProjectContent.mockResolvedValue({ status: 201, body });
        await component.save(commandEvent({ state: 'draft', brief_id: '75', kind: 'blog', title: 'Human text', body: 'Exact text', reason: 'Human correction' }));
        expect(api.projectContent.mock.calls.length, JSON.stringify(body)).toBe(reads);
        expect(component.current()).toEqual(revision); expect(component.saveError()).toContain('outcome is unknown');
        expect(component.busy()).toBe(false);
      }
      const saved = { ...revision, revision: 3, state: 'draft' };
      api.saveProjectContent.mockResolvedValue({ status: 201, body: { project_id: 9, revision: saved } });
      api.projectContent.mockResolvedValue({ status: 200, body: { project_id: 9, items: [saved], current: saved, history: [older, saved] } });
      const reads = api.projectContent.mock.calls.length;
      await component.save(commandEvent({ state: 'draft', brief_id: '75', kind: 'blog', title: 'Human text', body: 'Exact text', reason: 'Human correction' }));
      expect(api.projectContent.mock.calls.length).toBe(reads + 2); expect(component.current()).toEqual(saved);
      expect(component.saveError()).toBe(''); expect(component.message()).toContain('revision saved');
    } finally { fixture.destroy(); }
  });

  it.each(['en', 'tr'] as const)('permits full Unicode studio human text and refuses each exact overflow before saving in %s', async (language) => {
    const { api, fixture, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } });
    const form = fixture.nativeElement.querySelector('section[aria-labelledby="content-draft-title"] form') as HTMLFormElement;
    const input = (name: string) => form.elements.namedItem(name) as HTMLInputElement | HTMLTextAreaElement;
    const limits = { title: 240, body: 30000, meta_description: 320, reason: 500 };
    const maximum = { title: '😀'.repeat(240), body: '😀'.repeat(30000), meta_description: '😀'.repeat(320), reason: '😀'.repeat(500) };
    api.saveProjectContent.mockResolvedValue({ status: 201, body: { project_id: 9, revision } });
    try {
      input('brief_id').value = '75'; input('state').value = 'draft';
      for (const [name, value] of Object.entries(maximum)) {
        input(name).value = value; expect(input(name).maxLength, name).toBeGreaterThanOrEqual(value.length);
      }
      expect(fixture.nativeElement.querySelector('section').getAttribute('lang')).toBe(language);
      expect(fixture.nativeElement.querySelector('h1').textContent).toBe(language === 'tr' ? 'Özel içerik stüdyosu' : 'Private content studio');
      expect(fixture.nativeElement.querySelector('label[for="content-title-input"]').textContent).toContain('240');
      expect(fixture.nativeElement.querySelector('#content-body').getAttribute('lang')).toBe('');
      expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'iki dilli onay bekleniyor' : 'Editing approved content clears approval');
      const reads = api.projectContent.mock.calls.length;
      component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('form')).toBe(form);
      for (const [name, value] of Object.entries(maximum)) expect(input(name).value).toBe(value);
      expect(api.projectContent.mock.calls.length).toBe(reads); expect(api.saveProjectContent).not.toHaveBeenCalled();
      component.productLanguage.set(language); fixture.detectChanges();
      await component.save({ preventDefault() {}, target: form } as unknown as Event);
      expect(api.saveProjectContent).toHaveBeenCalledTimes(1); expect(api.saveProjectContent.mock.calls[0][3]).toMatchObject(maximum);
      fixture.detectChanges();
      const status = fixture.nativeElement.querySelector('section[aria-labelledby="content-title"] > p[role="status"][lang]') as HTMLParagraphElement;
      const english = 'Immutable draft revision saved. No live page changed.';
      expect(component.message()).toBe(english); expect(status.lang).toBe(language);
      expect(status.textContent).toBe(language === 'tr' ? 'Değiştirilemez draft revizyonu kaydedildi. Canlı sayfa değişmedi.' : english);
      const current = component.current(), calls = api.projectContent.mock.calls.length;
      input('reason').value = 'Unsubmitted human rationale'; input('reason').focus();
      component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('section[aria-labelledby="content-title"] > p[role="status"][lang]')).toBe(status);
      expect(status.lang).toBe(language === 'tr' ? 'en' : 'tr');
      expect(status.textContent).toContain(language === 'tr' ? 'No live page changed' : 'Canlı sayfa değişmedi');
      expect(component.message()).toBe(english); expect(component.current()).toBe(current);
      expect(input('reason').value).toBe('Unsubmitted human rationale'); expect(document.activeElement).toBe(input('reason'));
      expect(api.projectContent.mock.calls.length).toBe(calls); expect(api.saveProjectContent).toHaveBeenCalledTimes(1);
      component.productLanguage.set(language); fixture.detectChanges();
      component.newItem();
      for (const [name, limit] of Object.entries(limits)) {
        await component.save(commandEvent({ state: 'draft', brief_id: '75', kind: 'blog', title: 'Human title', reason: 'Human rationale',
          body: '', meta_description: '', [name]: '😀'.repeat(limit + 1) }));
        expect(api.saveProjectContent, name).toHaveBeenCalledTimes(1); expect(component.saveError()).toContain('characters');
        expect(component.busy()).toBe(false); fixture.detectChanges();
        expect(fixture.nativeElement.querySelector('#content-save-error').textContent).toBe(component.t(component.saveError()));
      }
      for (const name of ['title', 'reason']) {
        await component.save(commandEvent({ state: 'draft', brief_id: '75', kind: 'blog', title: 'Human title', reason: 'Human rationale', [name]: '   ' }));
        expect(api.saveProjectContent, name).toHaveBeenCalledTimes(1);
      }
      await component.save(commandEvent({ state: 'draft', brief_id: '75', kind: 'blog', title: '  Human title  ', reason: '  Human rationale  ',
        body: '  Exact body\n', meta_description: 'Optional description' }));
      expect(api.saveProjectContent).toHaveBeenCalledTimes(2);
      expect(api.saveProjectContent.mock.calls[1][3]).toMatchObject({ title: 'Human title', reason: 'Human rationale', body: '  Exact body\n' });
    } finally { fixture.destroy(); }
  });

  it('withholds malformed revision text in current history and acknowledgment while inventory remains metadata-only', async () => {
    const { api, fixture, component } = await screen();
    const cases: [string, unknown[]][] = [
      ['title', [[], {}, null, undefined, '', ' ', 'a'.repeat(241), '😀'.repeat(241)]],
      ['reason', [[], {}, null, undefined, '', ' ', 'a'.repeat(501), '😀'.repeat(501)]],
      ['body', [[], {}, null, undefined, '', ' ', 'a'.repeat(30001), '😀'.repeat(30001)]],
      ['meta_description', [[], {}, null, undefined, 'a'.repeat(321), '😀'.repeat(321)]],
    ];
    const older = { ...revision, id: 79, revision: 1, state: 'draft' };
    const { body: _body, meta_description: _meta, ...summary } = revision;
    try {
      api.projectContent.mockResolvedValue({ status: 200, body: { project_id: 9, items: [summary] } });
      await component.load(); expect(component.items()).toEqual([summary]);
      for (const [field, values] of cases) for (const value of values) {
        const bad = { ...revision, [field]: value };
        api.projectContent.mockResolvedValue({ status: 200, body: { project_id: 9, items: [bad], current: bad, history: [bad] } });
        if (field === 'title' || field === 'reason') { await component.inventory(); expect(component.items()).toEqual([]); }
        await component.open(80); expect(component.current(), `${field}=${JSON.stringify(value)}`).toBeNull();
        api.projectContent.mockResolvedValue({ status: 200, body: { project_id: 9, current: revision, history: [bad, older] } });
        await component.open(80); expect(component.history()).toEqual([older]);
        const reads = api.projectContent.mock.calls.length;
        api.saveProjectContent.mockResolvedValue({ status: 201, body: { project_id: 9, revision: bad } });
        await component.save(commandEvent({ state: 'draft', brief_id: '75', kind: 'blog', title: 'Human text', body: 'Exact text', reason: 'Human correction' }));
        expect(api.projectContent.mock.calls.length).toBe(reads); expect(component.current()).toEqual(revision);
        expect(component.saveError()).toContain('outcome is unknown');
      }
    } finally { fixture.destroy(); }
  });

  it.each(['en', 'tr'] as const)('preserves full Unicode revision text, empty drafts and inert original comparisons in %s', async (language) => {
    const { api, fixture, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } });
    const current = { ...revision, title: '😀'.repeat(240), reason: '😀'.repeat(500), body: '😀'.repeat(30000), meta_description: '😀'.repeat(320) };
    const older = { ...revision, id: 79, revision: 1, state: 'draft', body: '', meta_description: '' };
    const { body: _body, meta_description: _meta, ...summary } = current;
    api.projectContent.mockResolvedValue({ status: 200, body: { project_id: 9, items: [summary], current, history: [older, current], brief: briefEvidence, source_state: 'current_review_still_required' } });
    try {
      await component.load(); expect(component.items()).toEqual([summary]); await component.open(80); fixture.detectChanges();
      expect(component.current()).toEqual(current); expect(component.history()).toEqual([older, current]);
      expect((fixture.nativeElement.querySelector('#content-body') as HTMLTextAreaElement).value).toBe(current.body);
      component.comparison.set(older); fixture.detectChanges(); expect(fixture.nativeElement.textContent).toContain(component.t('Compared revision') + ' 1');
      expect(fixture.nativeElement.querySelector('script')).toBeNull();
      expect(fixture.nativeElement.querySelector('q').textContent).toBe(briefEvidence.claims_to_verify[0].quote);
      expect(fixture.nativeElement.querySelector('q span').getAttribute('lang')).toBe('');
      expect(fixture.nativeElement.textContent).toContain(component.t('. Human verification required.'));
      component.nextState.set('approved'); fixture.detectChanges();
      const factReview = fixture.nativeElement.querySelector('input[name="fact_review"]') as HTMLInputElement;
      expect(factReview.required).toBe(true); expect(factReview.checked).toBe(false);
      expect(factReview.parentElement!.textContent).toContain(component.t('I reviewed this exact current revision, citations, original expertise and factual claims. Unsupported claims remain omitted or clearly unverified.'));
      factReview.checked = true;
      const reads = api.projectContent.mock.calls.length, url = component.downloadUrl();
      component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('input[name="fact_review"]')).toBe(factReview); expect(factReview.checked).toBe(true);
      expect(component.current()).toEqual(current); expect(component.comparison()).toEqual(older);
      expect(component.evidence()).toEqual(briefEvidence); expect(component.downloadUrl()).toBe(url);
      expect(api.projectContent.mock.calls.length).toBe(reads);
      component.productLanguage.set(language); fixture.detectChanges();
      api.projectContent.mockResolvedValue({ status: 200, body: { project_id: 9, current: older, history: [older] } });
      await component.open(80); expect(component.current()).toEqual(older);
      expect(api.saveProjectContent).not.toHaveBeenCalled(); expect(api.generateProjectContent).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it('rejects malformed nullable studio revision references and incomplete approval across existing readers', async () => {
    const { api, fixture, component } = await screen();
    try {
      const changes = ['generating_job_id', 'reviewed_revision_id', 'approved_by_id'].flatMap(field =>
        [0, -1, true, [81], '81', {}, undefined, Number.MAX_SAFE_INTEGER + 1].map(value => ({ [field]: value })));
      changes.push({ approved_at: [] }, { approved_at: '' }, { approved_at: '2026-01-01T00:00:00Z' },
        { reviewed_revision_id: 79, approved_by_id: 1 }, { state: 'approved' }, { state: 'published' });
      for (const change of changes) {
        const bad = { ...revision, ...change };
        api.projectContent.mockResolvedValue({ status: 200, body: { project_id: 9, items: [bad], current: bad, history: [bad] } });
        await component.load(); expect(component.items(), JSON.stringify(change)).toEqual([]);
        await component.open(80); expect(component.current(), JSON.stringify(change)).toBeNull();
        api.projectContent.mockResolvedValue({ status: 200, body: { project_id: 9, current: revision, history: [bad, revision] } });
        await component.open(80); expect(component.history()).toEqual([revision]);
        api.saveProjectContent.mockResolvedValue({ status: 201, body: { project_id: 9, revision: bad } });
        const reads = api.projectContent.mock.calls.length;
        await component.save(commandEvent({ brief_id: '75', kind: 'blog', title: revision.title, body: revision.body,
          meta_description: '', state: 'draft', reason: 'Human change' }));
        expect(api.projectContent.mock.calls.length).toBe(reads); expect(component.saveError()).toContain('outcome is unknown');
      }
    } finally { fixture.destroy(); }
  });

  it('retains null human provenance, positive generation and complete historical approval references', async () => {
    const { api, fixture, component } = await screen();
    const approved = { ...revision, id: 82, revision: 3, state: 'approved', reviewed_revision_id: 81,
      approved_by_id: 1, approved_at: '2026-01-01T00:00:00Z' };
    try {
      for (const current of [revision, { ...revision, generating_job_id: 101 }, approved,
        { ...approved, state: 'published', publication_url: 'https://project.example.invalid/page', published_at: '2026-01-01T00:00:00Z' },
        { ...approved, state: 'archived' }, { ...revision, state: 'archived' }]) {
        const { body: _body, meta_description: _meta, ...summary } = current;
        api.projectContent.mockResolvedValue({ status: 200, body: { project_id: 9, items: [summary], current, history: [revision, current] } });
        await component.load(); expect(component.items()).toEqual([summary]);
        await component.open(80); fixture.detectChanges(); expect(component.current()).toEqual(current);
        expect(component.history()).toEqual([revision, current]); expect(fixture.nativeElement.querySelector('script')).toBeNull();
      }
      const draft = { ...revision, state: 'draft', publication_url: 'https://project.example.invalid/page', published_at: '2026-01-01T00:00:00Z' };
      api.saveProjectContent.mockResolvedValue({ status: 201, body: { project_id: 9, revision: draft } });
      api.projectContent.mockResolvedValue({ status: 200, body: { project_id: 9, current: draft, history: [draft], items: [draft] } });
      await component.save(commandEvent({ brief_id: '75', kind: 'blog', title: draft.title, body: draft.body,
        meta_description: '', state: 'draft', reason: 'Human change clears approval, historical publication retained' }));
      expect(component.current()).toEqual(draft); expect(component.saveError()).toBe('');
    } finally { fixture.destroy(); }
  });

  it('withholds malformed studio revision dates and unpaired publication metadata on original readers', async () => {
    const { api, fixture, component } = await screen();
    const approved = { ...revision, state: 'approved', reviewed_revision_id: 79, approved_by_id: 1, approved_at: '2026-01-01T00:00:00Z' };
    const publication_url = 'https://project.example.invalid/page', published_at = '2026-01-01T00:00:00Z';
    try {
      const cases = [
        ...[null, [], '', 'yesterday', '2026-01-01', '2026-01-01T00:00:00', '2026-01-01T25:00:00Z'].map(created_at => ({ ...revision, created_at })),
        ...[[], 'yesterday', '2026-01-01T00:00:00'].map(approved_at => ({ ...approved, approved_at })),
        ...[undefined, [], 'yesterday', '2026-01-01T00:00:00'].map(published_at => ({ ...revision, publication_url, published_at })),
        ...[[], null, ' ', '😀'.repeat(513)].map(publication_url => ({ ...revision, publication_url, published_at })),
        { ...revision, publication_url, published_at: null }, { ...revision, publication_url: '', published_at },
        { ...approved, state: 'published' },
      ];
      for (const bad of cases) {
        api.projectContent.mockResolvedValue({ status: 200, body: { project_id: 9, items: [bad], current: bad, history: [bad] } });
        await component.load(); expect(component.items(), JSON.stringify(bad)).toEqual([]);
        await component.open(80); expect(component.current(), JSON.stringify(bad)).toBeNull();
        api.projectContent.mockResolvedValue({ status: 200, body: { project_id: 9, current: revision, history: [bad, revision] } });
        await component.open(80); expect(component.history()).toEqual([revision]);
        api.saveProjectContent.mockResolvedValue({ status: 201, body: { project_id: 9, revision: bad } });
        const reads = api.projectContent.mock.calls.length;
        await component.save(commandEvent({ brief_id: '75', kind: 'blog', title: revision.title, body: revision.body,
          meta_description: '', state: 'draft', reason: 'Human change' }));
        expect(api.projectContent.mock.calls.length).toBe(reads); expect(component.saveError()).toContain('outcome is unknown');
      }
    } finally { fixture.destroy(); }
  });

  it('preserves original aware studio timestamps and historical publication pairs after approval clears', async () => {
    const { api, fixture, component } = await screen();
    const publication_url = 'http://project.example.invalid/' + '😀'.repeat(240);
    const created_at = '2026-01-01T01:02:03.123456+05:00', published_at = '2025-12-31T20:00:00.123456+00:00';
    const approved = { ...revision, created_at, state: 'approved', reviewed_revision_id: 79, approved_by_id: 1,
      approved_at: '2025-12-31T20:00:00Z' };
    try {
      for (const current of [revision, approved, { ...approved, state: 'published', publication_url, published_at },
        { ...approved, state: 'archived', publication_url, published_at },
        { ...revision, state: 'draft', created_at, publication_url, published_at }]) {
        const { body: _body, meta_description: _meta, ...summary } = current;
        api.projectContent.mockResolvedValue({ status: 200, body: { project_id: 9, items: [summary], current, history: [revision, current] } });
        await component.load(); expect(component.items()).toEqual([summary]); await component.open(80); fixture.detectChanges();
        expect(component.current()).toEqual(current); expect(component.history()).toEqual([revision, current]);
        expect(fixture.nativeElement.querySelector('script')).toBeNull();
      }
      expect(api.saveProjectContent).not.toHaveBeenCalled(); expect(api.generateProjectContent).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it('requires positive original studio pagination cursors and preserves deliberate older record reads', async () => {
    const { api, fixture, component } = await screen();
    const response = (next_before: unknown) => ({ status: 200, body: { project_id: 9, items: [revision],
      current: revision, history: [revision], next_before } });
    try {
      for (const cursor of [null, undefined, 0, -1, -10, '2', [2], {}, 1.5, NaN, Number.MAX_SAFE_INTEGER + 1]) {
        api.projectContent.mockResolvedValue(response(cursor)); await component.inventory(); await component.open(80); fixture.detectChanges();
        expect(component.nextItems(), JSON.stringify(cursor)).toBeNull(); expect(component.nextHistory()).toBeNull();
        expect(fixture.nativeElement.textContent).not.toContain('Older content records');
        expect(fixture.nativeElement.textContent).not.toContain('Older revisions');
      }
      api.projectContent.mockResolvedValue(response(2147483648)); await component.inventory(); await component.open(80);
      expect(component.nextItems()).toBe(2147483648); expect(component.nextHistory()).toBeNull();
      api.projectContent.mockResolvedValue(response(Number.MAX_SAFE_INTEGER)); await component.inventory();
      expect(component.nextItems()).toBe(Number.MAX_SAFE_INTEGER);
      api.projectContent.mockResolvedValue(response(2147483647)); await component.open(80); expect(component.nextHistory()).toBe(2147483647);
      api.projectContent.mockResolvedValue(response(80)); await component.inventory(); fixture.detectChanges();
      const olderItems = Array.from(fixture.nativeElement.querySelectorAll('button')) as HTMLButtonElement[];
      olderItems.find(button => button.textContent === 'Older content records')!.click();
      await fixture.whenStable(); expect(api.projectContent).toHaveBeenLastCalledWith(7, 9, 0, 80);
      api.projectContent.mockResolvedValue(response(1)); await component.open(80); fixture.detectChanges();
      const olderHistory = Array.from(fixture.nativeElement.querySelectorAll('button')) as HTMLButtonElement[];
      olderHistory.find(button => button.textContent === 'Older revisions')!.click();
      await fixture.whenStable(); expect(api.projectContent).toHaveBeenLastCalledWith(7, 9, 80, 1);
      expect(component.current()).toEqual(revision); expect(api.saveProjectContent).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it('rejects malformed manual publication URL syntax while retaining original historical HTTP and Unicode paths', async () => {
    const { api, fixture, component } = await screen();
    const published_at = '2026-01-01T00:00:00Z';
    try {
      for (const publication_url of ['javascript:alert(1)', 'mailto:user@example.invalid', '/relative', 'https:/project.example.invalid/page',
        'https://user:pass@project.example.invalid/page', 'https://project.example.invalid/page?secret=1',
        'https://project.example.invalid/page#fragment', 'https://project.example.invalid/\\page',
        'https://project.example.invalid/with space', 'https://project.example.invalid/line\n',
        'data:text/html,<script>bad()</script>', 'https://', 'https:///project.example.invalid/page', 'https:////project.example.invalid/page']) {
        const bad = { ...revision, publication_url, published_at };
        api.projectContent.mockResolvedValue({ status: 200, body: { project_id: 9, items: [bad], current: bad, history: [bad] } });
        await component.load(); expect(component.items(), publication_url).toEqual([]); await component.open(80); expect(component.current()).toBeNull();
        api.projectContent.mockResolvedValue({ status: 200, body: { project_id: 9, current: revision, history: [bad, revision] } });
        await component.open(80); expect(component.history()).toEqual([revision]);
        api.saveProjectContent.mockResolvedValue({ status: 201, body: { project_id: 9, revision: bad } });
        const reads = api.projectContent.mock.calls.length;
        await component.save(commandEvent({ brief_id: '75', kind: 'blog', title: revision.title, body: revision.body,
          meta_description: '', state: 'draft', reason: 'Human change' }));
        expect(api.projectContent.mock.calls.length).toBe(reads); expect(component.saveError()).toContain('outcome is unknown');
      }
      for (const publication_url of ['http://project.example.invalid:8080/page', 'https://project.example.invalid/page',
        'https://project.example.invalid/İstanbul/😀', 'https://project.example.invalid/%3F%23',
        'http://project.example.invalid/' + '😀'.repeat(240)]) {
        const current = { ...revision, publication_url, published_at };
        api.projectContent.mockResolvedValue({ status: 200, body: { project_id: 9, items: [current], current, history: [current] } });
        await component.load(); await component.open(80); fixture.detectChanges();
        expect(component.items()).toEqual([current]); expect(component.current()).toEqual(current); expect(component.history()).toEqual([current]);
        expect(component.current()?.publication_url).toBe(publication_url); expect(fixture.nativeElement.textContent).toContain(publication_url);
        expect(fixture.nativeElement.querySelector('script')).toBeNull();
      }
    } finally { fixture.destroy(); }
  });

  it.each(['en', 'tr'] as const)('rejects invalid or future manual publication dates before becoming busy and preserves past local-time reports in %s', async (language) => {
    const { api, fixture, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } });
    const approved = { ...revision, state: 'approved', reviewed_revision_id: 79, approved_by_id: 1, approved_at: '2026-01-01T00:00:00Z' };
    api.projectContent.mockResolvedValue({ status: 200, body: { project_id: 9, current: approved, history: [approved] } });
    const local = '2026-01-01T10:30', url = 'https://project.example.invalid/page';
    const fields = { state: 'published', brief_id: '75', kind: 'blog', title: approved.title, body: approved.body,
      reason: 'Actual manual publication report', publication_url: url, published_at: local };
    const clock = vi.spyOn(Date, 'now').mockReturnValue(Date.parse('2026-02-01T00:00:00Z'));
    try {
      await component.open(80); component.nextState.set('published'); fixture.detectChanges();
      const urlInput = fixture.nativeElement.querySelector('#content-publication-url') as HTMLInputElement;
      const dateInput = fixture.nativeElement.querySelector('#content-publication-date') as HTMLInputElement;
      urlInput.value = url; dateInput.value = local;
      expect(urlInput.required).toBe(true); expect(dateInput.type).toBe('datetime-local'); expect(dateInput.required).toBe(true);
      expect(fixture.nativeElement.textContent).toContain(component.t('Record an actual manual publication only. This does not call a CMS or change the page.'));
      component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('#content-publication-url')).toBe(urlInput); expect(urlInput.value).toBe(url);
      expect(fixture.nativeElement.querySelector('#content-publication-date')).toBe(dateInput); expect(dateInput.value).toBe(local);
      expect(api.saveProjectContent).not.toHaveBeenCalled(); component.productLanguage.set(language); fixture.detectChanges();
      for (const change of [
        ...['', 'not-a-date', '2027-01-01T10:30', '9999-12-31T23:59'].map(published_at => ({ published_at })),
        { publication_url: '' }, { publication_url: url + 'a'.repeat(512) },
      ]) {
        await expect(component.save(commandEvent({ ...fields, ...change }))).resolves.toBeUndefined();
        expect(api.saveProjectContent).not.toHaveBeenCalled(); expect(component.busy()).toBe(false);
        expect(component.current()).toEqual(approved); expect(component.saveError()).toContain('publication');
      }
      const published = { ...approved, revision: 3, state: 'published', publication_url: url, published_at: new Date(local).toISOString() };
      api.saveProjectContent.mockResolvedValue({ status: 201, body: { project_id: 9, revision: published } });
      api.projectContent.mockResolvedValue({ status: 200, body: { project_id: 9, items: [published], current: published, history: [approved, published] } });
      await component.save(commandEvent(fields)); expect(api.saveProjectContent).toHaveBeenCalledTimes(1);
      expect(api.saveProjectContent.mock.calls[0][3]).toMatchObject({ publication_url: url, published_at: new Date(local).toISOString(), expected_revision: 2 });
      expect(component.current()).toEqual(published); expect(component.busy()).toBe(false);
      fixture.detectChanges();
      const status = fixture.nativeElement.querySelector('section[aria-labelledby="content-title"] > p[role="status"][lang]') as HTMLParagraphElement;
      expect(component.message()).toBe('Immutable published revision saved. No live page changed.');
      expect(status.lang).toBe(language);
      expect(status.textContent).toBe(language === 'tr'
        ? 'Değiştirilemez published revizyonu kaydedildi. Canlı sayfa değişmedi.' : component.message());
      const draft = { ...published, revision: 4, state: 'draft', reviewed_revision_id: null, approved_by_id: null, approved_at: null };
      api.saveProjectContent.mockResolvedValue({ status: 201, body: { project_id: 9, revision: draft } });
      api.projectContent.mockResolvedValue({ status: 200, body: { project_id: 9, items: [draft], current: draft, history: [draft, published] } });
      await component.save(commandEvent({ ...fields, state: 'draft', published_at: 'not-a-date' }));
      expect(api.saveProjectContent).toHaveBeenCalledTimes(2);
      expect(api.saveProjectContent.mock.calls[1][3]).not.toHaveProperty('published_at');
      expect(api.saveProjectContent.mock.calls[1][3]).not.toHaveProperty('publication_url');
    } finally { clock.mockRestore(); fixture.destroy(); }
  });

  it('stops saved-content follow-up reads when the route changes during inventory refresh', async () => {
    const { api, fixture, component, route } = await screen();
    api.saveProjectContent.mockResolvedValue({ status: 201, body: { project_id: 9, revision } });
    let release!: (result: ApiResult) => void;
    api.projectContent.mockReturnValueOnce(new Promise(resolve => { release = resolve; }));
    const before = api.projectContent.mock.calls.length;
    const save = component.save(commandEvent({ state: 'draft', brief_id: '75', kind: 'blog', title: 'Human text', reason: 'Manual draft' }));
    await vi.waitFor(() => expect(api.projectContent.mock.calls.length).toBe(before + 1));
    route.next(convertToParamMap({ organizationId: '7', projectId: '10' }));
    await vi.waitFor(() => expect(component.loading()).toBe(false));
    release({ status: 200, body: { project_id: 9, items: [revision], next_before: null } });
    try {
      await save;
      expect(api.projectContent.mock.calls.length).toBe(before + 1);
      expect(api.saveProjectContent).toHaveBeenCalledTimes(1);
      expect(component.current()).toBeNull(); expect(component.canEdit()).toBe(false);
      expect(component.message()).toBe(''); expect(component.error()).toContain('access revoked');
    } finally { fixture.destroy(); }
  });

  it('makes no follow-up reads for a save response received after the studio is destroyed', async () => {
    const { api, fixture, component } = await screen();
    let release!: (result: ApiResult) => void;
    api.saveProjectContent.mockReturnValueOnce(new Promise(resolve => { release = resolve; }));
    const before = api.projectContent.mock.calls.length;
    const save = component.save(commandEvent({ state: 'draft', brief_id: '75', kind: 'blog', title: 'Human text', reason: 'Manual draft' }));
    expect(api.saveProjectContent).toHaveBeenCalledTimes(1);
    fixture.destroy(); release({ status: 201, body: { project_id: 9, revision } }); await save;
    expect(api.projectContent.mock.calls.length).toBe(before); expect(component.current()).toBeNull();
    expect(component.message()).toBe('');
  });

  it('withholds malformed generation states, provider observations and draft approval claims on list/detail refresh', async () => {
    const { api, fixture, component } = await screen();
    const states = ['queued', 'running', 'waiting_provider', 'succeeded', 'failed', 'cancelled', 'partially_succeeded'];
    const usage = { request_status: 'unknown', estimated_cost_usd: null, reported_cost_usd: null, input_tokens: null, output_tokens: null };
    try {
      for (const change of [
        ...states.map(status => ({ status: [status] })),
        ...['attempted', 'completed', 'failed', 'unknown'].map(request_status => ({ usage: { ...usage, request_status: [request_status] } })),
        ...[['unverified_draft_human_review_required'], 'approved'].map(review_state => ({ draft: { item_id: 80, review_state } })),
        { source_current: [true] }, { cancel_requested: [false] },
      ]) {
        const row = { ...generationJob, ...change };
        api.contentGeneration.mockResolvedValue({ status: 200, body: { project_id: 9, jobs: [row], job: row } });
        await component.load(); expect(component.generationJobs(), JSON.stringify(change)).toEqual([]);
        await component.inspectGeneration(101); fixture.detectChanges();
        expect(component.generationJob()).toBeNull(); expect(component.message()).toContain('Generation status unavailable');
      }
      for (const status of states) {
        const row = { ...generationJob, status, usage };
        api.contentGeneration.mockResolvedValue({ status: 200, body: { project_id: 9, jobs: [row], job: row } });
        await component.load(); await component.inspectGeneration(101); fixture.detectChanges();
        expect(component.generationJobs()[0].status).toBe(status); expect(component.generationJob()?.status).toBe(status);
        expect(component.generationJob()?.usage?.reported_cost_usd).toBeNull();
      }
      for (const request_status of ['attempted', 'completed', 'failed', 'unknown']) {
        const row = { ...generationJob, status: 'succeeded', usage: { ...usage, request_status },
          draft: { item_id: 80, review_state: 'unverified_draft_human_review_required' } };
        api.contentGeneration.mockResolvedValue({ status: 200, body: { project_id: 9, job: row } });
        await component.inspectGeneration(101); fixture.detectChanges();
        expect(component.generationJob()?.usage?.request_status).toBe(request_status);
        expect(fixture.nativeElement.textContent).toContain('unverified_draft_human_review_required');
      }
      api.contentGeneration.mockResolvedValue({ status: 200, body: { project_id: 8, job: generationJob } });
      await component.inspectGeneration(101); expect(component.generationJob()).toBeNull();
      api.contentGeneration.mockResolvedValue({ status: 403, body: {} }); await component.load();
      expect(component.generationJobs()).toEqual([]); expect(component.generationJob()).toBeNull();
      expect(api.generateProjectContent).not.toHaveBeenCalled();
      expect(api.contentGeneration.mock.calls.every(call => call.length < 4 || call[3] === false)).toBe(true);
    } finally { fixture.destroy(); }
  });

  it('withholds malformed studio generation provenance, counters and usage scalars across all readers', async () => {
    const { api, fixture, component } = await screen();
    api.projectResearch.mockResolvedValue({ status: 200, body: { project_id: 9,
      models: [{ id: 3, provider_id: 5, name: 'Model', access_tier: 'standard', price_known: true,
        privacy_policy_url: '', max_output_tokens: 200 }],
      accounts: [{ id: 4, provider_id: 5, label: 'Account', source: 'platform' }] } });
    const usage = { request_status: 'unknown', estimated_cost_usd: null, reported_cost_usd: null, input_tokens: null, output_tokens: null };
    const cases: [string, unknown[]][] = [
      ['brief_id', [0, -1, 1.5, '75', [75], null, undefined]],
      ['kind', [['blog'], {}, null, undefined, 'unsupported', 'social', 'social_series']],
      ['platform', [['x'], {}, null, undefined, 'unsupported', 'x']],
      ['estimate_units', [0, 2, '1', [1], null, undefined]],
      ['attempted_units', [-1, 2, 0.5, '0', [0], null, undefined]],
      ['error_category', [[], {}, null, undefined, 'a'.repeat(65), '😀'.repeat(65)]],
      ['estimated_max_cost_usd', [[], [0], {}, 0, true, undefined]],
    ];
    const invalid: Record<string, unknown>[] = cases.flatMap(([field, values]) => values.map(value => ({ ...generationJob, [field]: value })));
    for (const field of ['estimated_cost_usd', 'reported_cost_usd']) for (const value of [[], [0], {}, 0, true, undefined]) {
      invalid.push({ ...generationJob, usage: { ...usage, [field]: value } });
    }
    for (const field of ['input_tokens', 'output_tokens']) for (const value of [-1, 0.5, 100000001, '0', [0], {}, true, undefined]) {
      invalid.push({ ...generationJob, usage: { ...usage, [field]: value } });
    }
    const event = commandEvent({ account_id: '4', brief_id: '75', kind: 'blog', max_output_tokens: '128', max_cost_usd: '0.1' });
    try {
      for (const row of invalid) {
        api.contentGeneration.mockResolvedValue({ status: 200, body: { project_id: 9, jobs: [row], job: row } });
        await component.load(); expect(component.generationJobs(), JSON.stringify(row)).toEqual([]);
        await component.inspectGeneration(101); expect(component.generationJob()).toBeNull();
        component.selectedModel.set(3);
        api.generateProjectContent.mockResolvedValue({ status: 202, body: { project_id: 9, job: row } });
        await component.generate(event); expect(component.generationJob()).toBeNull(); expect(component.generationJobs()).toEqual([]);
        expect(component.message()).toContain('Draft request unavailable');
      }
      const keys = api.generateProjectContent.mock.calls.map(call => call[2].idempotency_key);
      expect(new Set(keys).size).toBe(1); expect(keys.length).toBe(invalid.length);
      expect(api.contentGeneration.mock.calls.every(call => call.length < 4 || !call[3])).toBe(true);
    } finally { fixture.destroy(); }
  });

  it.each(['en', 'tr'] as const)('preserves canonical studio generation kinds, nullable costs and observed token boundaries in %s', async (language) => {
    const { api, fixture, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } });
    try {
      const pairs = [...component.kinds.filter(kind => !['social', 'social_series'].includes(kind)).map(kind => [kind, '']),
        ...component.platforms.map(platform => ['social', platform])];
      for (const [kind, platform] of pairs) {
        const row = { ...generationJob, kind, platform, attempted_units: 1, error_category: '😀'.repeat(64), estimated_max_cost_usd: '0.000000',
          usage: { request_status: 'unknown', estimated_cost_usd: '0.000000', reported_cost_usd: '0.123456', input_tokens: 0, output_tokens: 100000000 } };
        api.contentGeneration.mockResolvedValue({ status: 200, body: { project_id: 9, jobs: [row], job: row } });
        await component.load(); await component.inspectGeneration(101); fixture.detectChanges();
        expect(component.generationJobs()[0]).toEqual(row); expect(component.generationJob()).toEqual(row);
        expect(fixture.nativeElement.textContent).toContain(component.t('· tokens') + ' 0 / 100000000');
        expect(fixture.nativeElement.textContent).toContain(component.t('· provider-reported USD') + ' 0.123456');
      }
      const row = { ...generationJob, usage: { request_status: 'unknown', estimated_cost_usd: null, reported_cost_usd: null, input_tokens: null, output_tokens: null } };
      api.contentGeneration.mockResolvedValue({ status: 200, body: { project_id: 9, job: row } });
      await component.inspectGeneration(101); fixture.detectChanges();
      expect(component.generationJob()).toEqual(row); expect(fixture.nativeElement.textContent).toContain(component.t('· tokens') + ' ' + component.t('unknown') + ' / ' + component.t('unknown'));
      expect(fixture.nativeElement.textContent).toContain(component.t('· provider-reported USD') + ' ' + component.t('unknown'));
      const calls = api.contentGeneration.mock.calls.length;
      component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
      expect(component.generationJob()).toEqual(row); expect(api.contentGeneration.mock.calls.length).toBe(calls);
      expect(api.generateProjectContent).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it.each(['en', 'tr'] as const)('keeps malformed generation acknowledgments uncertain and preserves the exact request key for a deliberate recovery in %s', async (language) => {
    const { api, fixture, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } });
    api.projectResearch.mockResolvedValue({ status: 200, body: { project_id: 9,
      models: [{ id: 3, provider_id: 5, name: 'Synthetic standard model', access_tier: 'standard', price_known: true,
        privacy_policy_url: '', max_output_tokens: 200 }],
      accounts: [{ id: 4, provider_id: 5, label: 'Synthetic account', source: 'organization' }] } });
    await component.load(); component.selectedModel.set(3);
    const event = commandEvent({ account_id: '4', brief_id: '75', kind: 'blog', max_output_tokens: '128', max_cost_usd: '0.1' });
    try {
      for (const body of [
        { project_id: 9, job: { ...generationJob, status: ['queued'] } },
        { project_id: 8, job: generationJob },
      ]) {
        api.generateProjectContent.mockResolvedValue({ status: 202, body }); await component.generate(event);
        expect(component.generationJob()).toBeNull(); expect(component.generationJobs()).toEqual([]);
        expect(component.message()).toContain('Draft request unavailable');
      }
      fixture.detectChanges();
      const status = fixture.nativeElement.querySelector('section[aria-labelledby="content-title"] > p[role="status"][lang]') as HTMLParagraphElement;
      const english = 'Draft request unavailable (202). Check source, model and allowance; refresh history before retrying.';
      expect(component.message()).toBe(english); expect(status.lang).toBe(language);
      expect(status.textContent).toBe(language === 'tr'
        ? 'Taslak isteği kullanılamıyor (202). Kaynağı, modeli ve kullanım hakkını kontrol edin; tekrar denemeden önce geçmişi yenileyin.' : english);
      component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
      expect(api.generateProjectContent).toHaveBeenCalledTimes(2);
      expect(fixture.nativeElement.querySelector('section[aria-labelledby="content-title"] > p[role="status"][lang]')).toBe(status);
      expect(status.lang).toBe(language === 'tr' ? 'en' : 'tr'); expect(component.message()).toBe(english);
      expect(status.textContent).toContain(language === 'tr' ? 'refresh history before retrying' : 'tekrar denemeden önce geçmişi yenileyin');
      component.productLanguage.set(language); fixture.detectChanges();
      const key = api.generateProjectContent.mock.calls[0][2].idempotency_key;
      expect(api.generateProjectContent.mock.calls[1][2].idempotency_key).toBe(key);
      api.generateProjectContent.mockResolvedValue({ status: 202, body: { project_id: 9, job: generationJob } });
      await component.generate(event);
      expect(api.generateProjectContent).toHaveBeenCalledTimes(3);
      expect(api.generateProjectContent.mock.calls[2][2].idempotency_key).toBe(key);
      expect(component.generationJob()?.status).toBe('queued'); expect(component.generationJob()?.usage).toBeNull();
      expect(component.message()).toContain('One unverified draft queued'); fixture.detectChanges();
      expect(fixture.nativeElement.textContent).toContain(component.t(component.message()));
      expect(status.textContent).toContain(language === 'tr' ? 'Doğrulanmamış bir taslak kuyruğa alındı' : 'One unverified draft queued');
    } finally { fixture.destroy(); }
  });

  it('keeps invalid unavailable preferences and fresh production content studio English without commands', async () => {
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    try {
      for (const mode of ['invalid', 'incompatible', 'signed-out', 'unavailable', 'production'] as const) {
        TestBed.resetTestingModule(); buildEnvironment.production = mode === 'production';
        const preference: ApiResult | Error = mode === 'unavailable' ? new Error('private preference error')
          : mode === 'signed-out' ? { status: 401, body: {} } : { status: 200, body: {
            language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: mode === 'incompatible' ? 'tr' : 'en', current_email_language: 'en' } };
        const { api, fixture, component } = await screen(preference);
        await fixture.whenStable(); fixture.detectChanges();
        expect(fixture.nativeElement.querySelector('section').getAttribute('lang')).toBe('en');
        expect(TestBed.inject(Title).getTitle()).toBe('Private content studio — OrganicSEOOps');
        expect(fixture.nativeElement.querySelector('h1').textContent).toBe('Private content studio');
        expect(fixture.nativeElement.textContent).not.toContain('private preference error');
        expect(fixture.nativeElement.textContent).not.toContain('incelenmemiş Türkçe');
        if (mode === 'production') expect(component.productLanguage()).toBe('tr');
        api.projectOnboarding.mockResolvedValue({ status: 403, body: {} }); await component.load(); fixture.detectChanges();
        expect(fixture.nativeElement.querySelector('[role="alert"]').textContent).toBe('Project content unavailable or access revoked.');
        expect(api.saveProjectContent).not.toHaveBeenCalled(); expect(api.generateProjectContent).not.toHaveBeenCalled(); fixture.destroy();
      }
    } finally { buildEnvironment.production = production; }
  });
});
