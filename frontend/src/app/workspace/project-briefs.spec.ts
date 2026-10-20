import { Title } from '@angular/platform-browser';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { vi } from 'vitest';
import { AccountApi, ApiResult } from '../account/account-api';
import { ProjectBriefs } from './project-briefs';
import { environment } from '../../environments/environment';

const brief = { id: 75, project_id: 9, research_job_id: 72, action_review_id: 73,
  created_at: '2026-01-01T00:00:00Z', size_bytes: 240, sha256: '1'.repeat(64),
  review_state: 'draft_human_review_required_no_site_change' };
const draft = { version: 'content-brief-v1', approval: brief.review_state, project_id: 9, research_job_id: 72,
  action_review_id: 73, scope: 'human_authored_structure_and_unverified_ai_interpretation_not_publication',
  topic: 'Human topic', angle: 'Human angle', audience: 'unknown_not_entered', business_goal: 'Human business goal',
  desired_action: '', meta_description: '', title_options: ['Human title'], outline: ['Human heading'], questions: [] as string[],
  relevant_internal_links: ['https://source.example.invalid/page'], research_summary_to_verify: 'Unverified interpretation',
  claims_to_verify: [{ text: 'Unverified claim', quote: 'Original quotation', source_index: 0 }],
  sources: [{ index: 0, state: 'collected', url: 'https://source.example.invalid/page', title: 'Original source',
    sha256: 'a'.repeat(64), retrieved_at: '2026-01-01T00:00:00Z' }],
  source_coverage: 'collected_selected_sources_only', action_revision: 1, page_kind: 'existing_unverified' };
function context(role: unknown): ApiResult {
  return { status: 200, body: { project: { id: 9, organization_id: 7, name: 'Synthetic project', role } } };
}

async function screen(preference: ApiResult | Error = { status: 200, body: { language: 'en', current_ui_language: 'en', current_email_language: 'en' } }) {
  const api = {
    productLanguage: vi.fn(async (): Promise<ApiResult> => { if (preference instanceof Error) throw preference; return preference; }),
    projectOnboarding: vi.fn(async (): Promise<ApiResult> => context('member')),
    projectBriefs: vi.fn(async (): Promise<ApiResult> => ({ status: 200, body: { project_id: 9, briefs: [brief], has_more: true } })),
    projectResearch: vi.fn(async () => ({ status: 200, body: { project_id: 9,
      jobs: [{ id: 72, project_id: 9, topic: 'Human topic', status: 'succeeded' }] } })),
    projectActions: vi.fn(async () => ({ status: 200, body: { project_id: 9, actions: [{
      action_id: '00000000-0000-4000-8000-000000000002', revision: 1, state: 'accepted', action_kind: 'refresh',
      source_current: true, source_id: 1, source_type: 'intent', affected_urls: ['https://source.example.invalid/page'] }] } })),
    projectBrief: vi.fn(async () => ({ status: 200, body: { project_id: 9, brief, draft } })),
    createProjectBrief: vi.fn(),
  };
  TestBed.configureTestingModule({ providers: [provideRouter([]), { provide: AccountApi, useValue: api },
    { provide: ActivatedRoute, useValue: { paramMap: of(convertToParamMap({ organizationId: '7', projectId: '9' })) } }] });
  const fixture = TestBed.createComponent(ProjectBriefs); fixture.detectChanges();
  await vi.waitFor(() => expect(fixture.componentInstance.loading()).toBe(false)); fixture.detectChanges();
  return { api, fixture, component: fixture.componentInstance };
}

describe('Current private brief creation authority and resources', () => {
  it('offers only positive scalar completed research choices for private briefs', async () => {
    const { api, fixture, component } = await screen();
    const row = { id: 72, project_id: 9, topic: 'Human topic', status: 'succeeded' };
    try {
      for (const change of [{ id: 0 }, { id: [72] }, { project_id: 10 }, { topic: [] }, { topic: '' },
        { topic: 'x'.repeat(241) }, { status: ['succeeded'] }, { status: 'running' }]) {
        api.projectResearch.mockResolvedValue({ status: 200, body: { project_id: 9, jobs: [{ ...row, ...change }] } } as never);
        await component.load(); fixture.detectChanges(); expect(component.research(), JSON.stringify(change)).toEqual([]);
        expect(fixture.nativeElement.querySelector('form')).toBeNull();
      }
      for (const status of ['succeeded', 'partially_succeeded']) {
        const valid = { ...row, status, topic: '  ' + '😀'.repeat(240) + '  ' };
        api.projectResearch.mockResolvedValue({ status: 200, body: { project_id: 9, jobs: [valid] } });
        await component.load(); fixture.detectChanges(); expect(component.research()).toEqual([valid]);
        expect(fixture.nativeElement.querySelector('form')).not.toBeNull();
      }
      expect(api.createProjectBrief).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it('withholds malformed brief action choices before URL rendering while preserving current accepted scalar sources', async () => {
    const { api, fixture, component } = await screen(); const row = component.actions()[0];
    try {
      for (const change of [{ action_id: '' }, { action_id: ['00000000-0000-4000-8000-000000000002'] }, { action_id: 'invalid' },
        { revision: 0 }, { revision: 32768 }, { state: ['accepted'] }, { state: 'proposed' }, { source_current: [true] },
        { source_id: 0 }, { source_type: ['intent'] }, { source_type: 'unknown' }, { action_kind: ['refresh'] },
        { action_kind: 'unselected' }, { affected_urls: null }, { affected_urls: 'https://source.example.invalid/page' },
        { affected_urls: [null] }, { affected_urls: [] }, { affected_urls: ['', ''] },
        { affected_urls: ['https://source.example.invalid/a', 'https://source.example.invalid/b', 'https://source.example.invalid/c'] }]) {
        api.projectActions.mockResolvedValue({ status: 200, body: { project_id: 9, actions: [{ ...row, ...change }] } } as never);
        await component.load(); expect(component.actions(), JSON.stringify(change)).toEqual([]); fixture.detectChanges();
        expect(fixture.nativeElement.querySelector('form')).toBeNull();
      }
      for (const state of ['accepted', 'in_progress', 'implemented', 'verified', 'outcome_reviewed']) {
        for (const action_kind of ['keep', 'refresh', 'merge', 'redirect', 'retire', 'create']) {
          const valid = { ...row, state, action_kind, revision: state === 'accepted' ? 1 : 32767,
            source_type: action_kind === 'create' ? 'opportunity' : 'intent' };
          api.projectActions.mockResolvedValue({ status: 200, body: { project_id: 9, actions: [valid] } });
          await component.load(); fixture.detectChanges(); expect(component.actions()).toEqual([valid]);
        }
      }
      expect(api.createProjectBrief).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it.each(['en', 'tr'] as const)('permits full Unicode brief sections and rejects each exact human input overflow before saving in %s', async (language) => {
    const { api, fixture, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } });
    const form = fixture.nativeElement.querySelector('form') as HTMLFormElement;
    const input = (name: string) => form.elements.namedItem(name) as HTMLInputElement | HTMLTextAreaElement;
    const setSources = () => { input('research_job_id').value = '72'; input('action_id').value = component.actions()[0].action_id; };
    const lengths = { title_options: 160, outline: 160, questions: 160, angle: 500, meta_description: 320, desired_action: 240 };
    const maximum = { title_options: Array(3).fill('😀'.repeat(160)).join('\n'),
      outline: Array(12).fill('😀'.repeat(160)).join('\n'), questions: Array(10).fill('😀'.repeat(160)).join('\n'),
      angle: '😀'.repeat(500), meta_description: '😀'.repeat(320), desired_action: '😀'.repeat(240) };
    api.createProjectBrief.mockResolvedValue({ status: 201, body: { project_id: 9, brief } });
    try {
      setSources();
      for (const [name, value] of Object.entries(maximum)) {
        input(name).value = value; expect(input(name).maxLength, name).toBeGreaterThanOrEqual(value.length);
      }
      expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Özel, kaynaklı içerik özetleri — OrganicSEOOps' : 'Private sourced content briefs — OrganicSEOOps');
      expect(fixture.nativeElement.querySelector('section').getAttribute('lang')).toBe(language);
      expect(form.querySelector('label[for="brief-research"]')!.textContent).toBe(language === 'tr' ? 'Araştırma işi' : 'Research job');
      expect(form.querySelector('label[for="brief-angle"]')!.textContent).toBe(language === 'tr' ? 'İnsanın seçtiği yaklaşım (en fazla 500 karakter)' : 'Human-selected angle (up to 500 characters)');
      expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'doğrulanmamış yorumlar' : 'unverified interpretations');
      expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'web sitesini değiştirmez' : 'change a website');
      const reads = api.projectBriefs.mock.calls.length;
      component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
      expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Private sourced content briefs — OrganicSEOOps' : 'Özel, kaynaklı içerik özetleri — OrganicSEOOps');
      expect(fixture.nativeElement.querySelector('form')).toBe(form);
      expect(input('research_job_id').value).toBe('72'); expect(input('action_id').value).toBe(component.actions()[0].action_id);
      for (const [name, value] of Object.entries(maximum)) expect(input(name).value).toBe(value);
      expect(api.projectBriefs).toHaveBeenCalledTimes(reads); expect(api.createProjectBrief).not.toHaveBeenCalled();
      component.productLanguage.set(language); fixture.detectChanges();
      await component.create({ preventDefault() {}, target: form } as unknown as Event);
      expect(api.createProjectBrief).toHaveBeenCalledTimes(1);
      fixture.detectChanges(); expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Özel, onaylanmamış içerik özeti kaydedildi' : 'Private unapproved brief saved');
      expect(input('angle').value).toBe('');
      expect(api.createProjectBrief.mock.calls[0][2]).toMatchObject({ title_options: Array(3).fill('😀'.repeat(160)),
        outline: Array(12).fill('😀'.repeat(160)), questions: Array(10).fill('😀'.repeat(160)),
        angle: maximum.angle, meta_description: maximum.meta_description, desired_action: maximum.desired_action });
      for (const [name, limit] of Object.entries(lengths)) {
        setSources();
        for (const key of Object.keys(lengths)) input(key).value = key === 'questions' || key === 'meta_description' || key === 'desired_action' ? '' : 'Human draft';
        input(name).value = '😀'.repeat(limit + 1);
        await component.create({ preventDefault() {}, target: form } as unknown as Event);
        expect(api.createProjectBrief, name).toHaveBeenCalledTimes(1); expect(component.message()).toContain('characters');
        fixture.detectChanges(); expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'her taslak satırı 1–160' : '1–160 characters per draft line');
      }
      setSources();
      for (const key of Object.keys(lengths)) input(key).value = key === 'questions' || key === 'meta_description' || key === 'desired_action' ? '' : 'Human draft';
      await component.create({ preventDefault() {}, target: form } as unknown as Event);
      expect(api.createProjectBrief).toHaveBeenCalledTimes(2);
    } finally { fixture.destroy(); }
  });

  it('rejects malformed private brief draft fields and original scope before restoring a canonical human draft', async () => {
    const { api, fixture, component } = await screen();
    try {
      for (const change of [{ project_id: 10 }, { research_job_id: 71 }, { action_review_id: 74 }, { scope: ['human_authored_structure_and_unverified_ai_interpretation_not_publication'] },
        { topic: [] }, { topic: 'x'.repeat(241) }, { angle: {} }, { audience: [] }, { audience: 'x'.repeat(501) },
        { business_goal: null }, { business_goal: 'x'.repeat(241) },
        { desired_action: [] }, { meta_description: {} }, { source_coverage: ['partial'] }, { source_coverage: 'complete_site' },
        { action_revision: 0 }, { action_revision: 32768 }, { page_kind: ['proposed'] }, { page_kind: 'article' },
        { title_options: [null] }, { title_options: [] }, { title_options: ['x'.repeat(161)] }, { outline: [null] },
        { questions: null }, { questions: [{}] }, { relevant_internal_links: null }, { relevant_internal_links: [null] },
        { research_summary_to_verify: [] }, { research_summary_to_verify: 'x'.repeat(3001) }]) {
        await component.open(75); expect(component.draft()).not.toBeNull();
        api.projectBrief.mockResolvedValueOnce({ status: 200, body: { project_id: 9, brief, draft: { ...draft, ...change } } } as never);
        await component.open(75); expect(component.draft(), JSON.stringify(change)).toBeNull();
        expect(component.selectedBriefId()).toBe(0); fixture.detectChanges();
      }
      const valid = { ...draft, topic: '  ' + '😀'.repeat(240) + '  ', angle: '😀'.repeat(500),
        title_options: ['😀'.repeat(160)], outline: ['😀'.repeat(160)], questions: ['😀'.repeat(160)],
        meta_description: '😀'.repeat(320), desired_action: '😀'.repeat(240), audience: '😀'.repeat(500), business_goal: '😀'.repeat(240) };
      api.projectBrief.mockResolvedValueOnce({ status: 200, body: { project_id: 9, brief, draft: valid } });
      await component.open(75); fixture.detectChanges(); expect(component.draft()).toEqual(valid);
      const unknown = { ...draft, audience: 'unknown_not_entered', business_goal: 'unknown_not_entered' };
      api.projectBrief.mockResolvedValueOnce({ status: 200, body: { project_id: 9, brief, draft: unknown } });
      await component.open(75); expect(component.draft()).toEqual(unknown);
      expect(component.selectedBriefId()).toBe(75); expect(component.downloadUrl()).toContain('/projects/9/briefs/75/download/');
      expect(api.createProjectBrief).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it.each(['en', 'tr'] as const)('rejects malformed brief source metadata and unlinked claims while preserving historical partial sources in %s', async (language) => {
    const { api, fixture, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } }); const source = draft.sources[0]; const claim = draft.claims_to_verify[0];
    try {
      for (const change of [{ sources: [null] }, { sources: [] }, { sources: [{ ...source, index: [0] }] },
        { sources: [{ ...source, state: ['collected'] }] }, { sources: [{ ...source, title: [] }] },
        { sources: [{ ...source, sha256: 'bad' }] }, { sources: [{ ...source, url: [] }] },
        { sources: [{ ...source, retrieved_at: [] }] }, { sources: [{ index: 0, state: 'unavailable' }] },
        { sources: [source, source] }, { claims_to_verify: [null] }, { claims_to_verify: [] },
        { claims_to_verify: [{ ...claim, source_index: 1 }] }, { claims_to_verify: [{ ...claim, text: [] }] },
        { claims_to_verify: [{ ...claim, quote: [] }] }, { claims_to_verify: [{ ...claim, quote: 'x'.repeat(301) }] }]) {
        api.projectBrief.mockResolvedValueOnce({ status: 200, body: { project_id: 9, brief, draft: { ...draft, ...change } } } as never);
        await component.open(75); expect(component.draft(), JSON.stringify(change)).toBeNull(); fixture.detectChanges();
      }
      const partial = { ...draft, source_coverage: 'partial', sources: [source, { index: 1, state: 'unavailable' }],
        research_summary_to_verify: '😀'.repeat(3000), claims_to_verify: [{ text: '😀'.repeat(500), quote: '😀'.repeat(300), source_index: 0 }] };
      api.projectBrief.mockResolvedValueOnce({ status: 200, body: { project_id: 9, brief, draft: partial } } as never);
      await component.open(75); fixture.detectChanges(); expect(component.draft()).toEqual(partial);
      expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Bu iddiayı bağımsız olarak doğrulayın' : 'Verify this claim independently');
      expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'hiçbir sayfayı yayımlamaz' : 'No page is published');
      expect(fixture.nativeElement.querySelector('q[lang=""]')!.textContent).toBe(partial.claims_to_verify[0].quote);
      expect(fixture.nativeElement.querySelector('a[lang=""][rel="noopener noreferrer"]')!.textContent).toBe(source.title);
      expect(fixture.nativeElement.textContent).toContain('partial');
      expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'kullanılamıyor' : 'unavailable');
      expect(fixture.nativeElement.querySelector('script')).toBeNull();
      const retained = component.draft(), download = component.downloadUrl(), reads = api.projectBrief.mock.calls.length;
      component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
      expect(component.draft()).toBe(retained); expect(component.downloadUrl()).toBe(download);
      expect(api.projectBrief).toHaveBeenCalledTimes(reads); component.productLanguage.set(language); fixture.detectChanges();
      const unlinked = { ...partial, claims_to_verify: [{ ...claim, source_index: 1 }] };
      api.projectBrief.mockResolvedValueOnce({ status: 200, body: { project_id: 9, brief, draft: unlinked } } as never);
      await component.open(75); expect(component.draft()).toBeNull(); expect(component.selectedBriefId()).toBe(0);
      expect(api.createProjectBrief).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it('requires primitive creation roles while preserving all valid project roles', async () => {
    const { api, fixture, component } = await screen();
    try {
      for (const role of [['owner'], ['admin'], ['member'], ['viewer'], 'owner', 'admin', 'member', 'viewer']) {
        api.projectOnboarding.mockResolvedValue(context(role)); await component.load(); fixture.detectChanges();
        expect(component.canCreate(), JSON.stringify(role)).toBe(typeof role === 'string' && role !== 'viewer');
      }
      expect(component.briefs()[0].review_state).toBe(brief.review_state); expect(api.createProjectBrief).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it('clears old role/source/history/export selections during pending and denied refresh before restoring valid sources', async () => {
    const { api, fixture, component } = await screen(); await component.open(75);
    expect(component.selectedBriefId()).toBe(75); expect(component.draft()).not.toBeNull();
    let release!: (value: ApiResult) => void;
    api.projectOnboarding.mockReturnValueOnce(new Promise(resolve => { release = resolve; }));
    const refresh = component.load();
    try {
      expect(component.canCreate()).toBe(false); expect(component.research()).toEqual([]); expect(component.actions()).toEqual([]);
      expect(component.briefs()).toEqual([]); expect(component.hasMore()).toBe(false);
      expect(component.selectedBriefId()).toBe(0); expect(component.draft()).toBeNull();
      release({ status: 403, body: {} }); await refresh; fixture.detectChanges();
      expect(component.canCreate()).toBe(false); expect(fixture.nativeElement.querySelector('form')).toBeNull();
      await component.load(); expect(component.canCreate()).toBe(true); expect(component.research()[0].id).toBe(72);
      expect(component.actions()[0].state).toBe('accepted'); expect(component.briefs()[0].id).toBe(75);
      api.projectBriefs.mockResolvedValue({ status: 403, body: {} }); await component.load();
      expect(component.canCreate()).toBe(false); expect(component.briefs()).toEqual([]); expect(component.research()).toEqual([]);
      expect(component.actions()).toEqual([]); expect(api.createProjectBrief).not.toHaveBeenCalled();
    } finally { release({ status: 403, body: {} }); await refresh; fixture.destroy(); }
  });

  it('makes no protected source follow-up reads after pending metadata arrives on a destroyed brief screen', async () => {
    const { api, fixture, component } = await screen();
    let release!: (value: ApiResult) => void;
    api.projectOnboarding.mockReturnValueOnce(new Promise(resolve => { release = resolve; }));
    const reads = [api.projectBriefs.mock.calls.length, api.projectResearch.mock.calls.length, api.projectActions.mock.calls.length];
    const reload = component.load(); fixture.destroy(); release(context('member')); await reload;
    expect([api.projectBriefs.mock.calls.length, api.projectResearch.mock.calls.length, api.projectActions.mock.calls.length]).toEqual(reads);
    expect(component.canCreate()).toBe(false); expect(component.briefs()).toEqual([]); expect(api.createProjectBrief).not.toHaveBeenCalled();
  });

  it.each(['en', 'tr'] as const)('withholds a foreign nested brief under a matching root scope and preserves valid private draft inspection in %s', async (language) => {
    const { api, fixture, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } });
    try {
      api.projectBrief.mockResolvedValue({ status: 200, body: { project_id: 9, brief: { ...brief, project_id: 10 }, draft } });
      await component.open(75); fixture.detectChanges();
      expect(component.draft()).toBeNull(); expect(component.selectedBriefId()).toBe(0);
      expect(component.message()).toContain('Private brief unavailable');
      expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Özel içerik özeti kullanılamıyor' : 'Private brief unavailable');
      api.projectBrief.mockResolvedValue({ status: 200, body: { project_id: 9, brief, draft } });
      await component.open(75); fixture.detectChanges();
      expect(component.draft()?.approval).toBe(brief.review_state); expect(component.selectedBriefId()).toBe(75);
      expect(fixture.nativeElement.querySelector('a[download]').getAttribute('href')).toBe(component.downloadUrl());
      expect(fixture.nativeElement.querySelector('a[download]').textContent).toContain(language === 'tr' ? 'onaylanmamış JSON' : 'unapproved JSON');
      expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'İstenen okuyucu eylemi: girilmedi' : 'Desired reader action: not entered');
      expect(fixture.nativeElement.querySelector('q[lang=""]')!.textContent).toBe(draft.claims_to_verify[0].quote);
      expect(fixture.nativeElement.querySelector('span[lang="en"]')!.textContent).toBe(brief.created_at);
      expect(api.projectBrief).toHaveBeenLastCalledWith(7, 9, 75); expect(api.createProjectBrief).not.toHaveBeenCalled();
    } finally { fixture.destroy(); }
  });

  it('withholds nonpositive source references and mismatched create scope while accepting a legitimate unapproved new brief', async () => {
    const { api, fixture, component } = await screen();
    try {
      for (const change of [{ research_job_id: 0 }, { research_job_id: -1 }, { action_review_id: 0 }, { action_review_id: -1 }]) {
        const row = { ...brief, ...change };
        api.projectBriefs.mockResolvedValue({ status: 200, body: { project_id: 9, briefs: [row], has_more: false } });
        await component.load(); expect(component.briefs(), JSON.stringify(change)).toEqual([]);
        api.projectBrief.mockResolvedValue({ status: 200, body: { project_id: 9, brief: row, draft } });
        await component.open(75); expect(component.draft()).toBeNull();
      }
      api.projectBriefs.mockResolvedValue({ status: 200, body: { project_id: 9, briefs: [brief], has_more: false } }); await component.load();
      const form = document.createElement('form'); vi.spyOn(form, 'reportValidity').mockReturnValue(true);
      for (const [name, value] of Object.entries({ research_job_id: '72', action_id: '00000000-0000-4000-8000-000000000002',
        title_options: 'Human title', outline: 'Human heading', angle: 'Human angle' })) {
        const input = document.createElement('input'); input.name = name; input.value = value; form.append(input);
      }
      const event = { preventDefault: vi.fn(), target: form } as unknown as Event;
      for (const body of [{ project_id: 8, brief: { ...brief, id: 76 } }, { project_id: 9, brief: { ...brief, id: 76, research_job_id: 0 } }]) {
        api.createProjectBrief.mockResolvedValue({ status: 201, body }); await component.create(event);
        expect(component.briefs()).toEqual([brief]); expect(component.draft()).toBeNull();
        expect(component.message()).toContain('Brief outcome unavailable');
      }
      expect(api.createProjectBrief).toHaveBeenCalledTimes(2);
      const created = { ...brief, id: 76 };
      api.createProjectBrief.mockResolvedValue({ status: 201, body: { project_id: 9, brief: created } });
      api.projectBrief.mockResolvedValue({ status: 200, body: { project_id: 9, brief: created, draft } });
      await component.create(event); expect(api.createProjectBrief).toHaveBeenCalledTimes(3);
      expect(component.briefs()[0].id).toBe(76); expect(component.selectedBriefId()).toBe(76);
      expect(component.draft()?.approval).toBe(brief.review_state);
    } finally { fixture.destroy(); }
  });
  it('keeps invalid unavailable preferences and fresh production briefs English without creating drafts', async () => {
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    try {
      for (const mode of ['invalid', 'incompatible', 'signed-out', 'unavailable', 'production'] as const) {
        TestBed.resetTestingModule(); buildEnvironment.production = mode === 'production';
        const preference: ApiResult | Error = mode === 'unavailable' ? new Error('private preference error')
          : mode === 'signed-out' ? { status: 401, body: {} } : { status: 200, body: {
            language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: mode === 'incompatible' ? 'tr' : 'en', current_email_language: 'en' } };
        const { api, fixture, component } = await screen(preference);
        await fixture.whenStable(); fixture.detectChanges();
        expect(TestBed.inject(Title).getTitle()).toBe('Private sourced content briefs — OrganicSEOOps');
        expect(fixture.nativeElement.querySelector('section').getAttribute('lang')).toBe('en');
        expect(fixture.nativeElement.querySelector('h1').textContent).toBe('Private sourced content briefs');
        expect(fixture.nativeElement.textContent).not.toContain('private preference error');
        expect(fixture.nativeElement.textContent).not.toContain('incelenmemiş Türkçe');
        if (mode === 'production') expect(component.productLanguage()).toBe('tr');
        api.projectOnboarding.mockResolvedValue({ status: 403, body: {} }); await component.load(); fixture.detectChanges();
        expect(fixture.nativeElement.querySelector('[role="alert"]').textContent).toContain('brief history is unavailable');
        expect(api.createProjectBrief).not.toHaveBeenCalled(); fixture.destroy();
      }
    } finally { buildEnvironment.production = production; }
  });

});
