import { Title } from '@angular/platform-browser';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { vi } from 'vitest';
import { AccountApi, ApiResult } from '../account/account-api';
import { AuthorityProspects } from './authority-prospects';
import { environment } from '../../environments/environment';

const ID = '00000000-0000-4000-8000-000000000001';
const QUOTE = 'Evidence <img src=x onerror=evil()> &amp; exact text';
const source = (project = 9) => ({ method: 'authority-research-evidence-v1', project_id: project,
  research_job_id: 11, source_index: 0, step_id: 22, artifact_id: 33, configuration_revision: 1,
  requested_url: 'https://source.example.invalid/article', url: 'https://source.example.invalid/article', title: 'Synthetic source',
  retrieved_at: '2026-10-01T12:00:00+03:00', original_response_sha256: 'a'.repeat(64), source_size_bytes: 200,
  excerpt: QUOTE, excerpt_truncated: true, coverage: 'selected_bounded_public_page_text_only', facts: 'unverified',
  link_structure: 'unavailable_href_rel_not_retained', inbound_unlinked_lost_links: 'not_established', publication_time: null,
  outreach_permission: 'not_established' });
class ProspectApi {
  preference: ApiResult | Error = { status: 200, body: { language: 'en', current_ui_language: 'en', current_email_language: 'en' } };
  async productLanguage(): Promise<ApiResult> { if (this.preference instanceof Error) throw this.preference; return this.preference; }
  commands: Record<string, unknown>[] = []; rows: Record<string, unknown>[] = []; queries: string[] = [];
  canReview = true; current = true; foreign = false; uncertain = false; unsafeSource = false;
  historyPromise: Promise<ApiResult> | null = null;
  result(org = 7, project = 9, reviews = this.rows.slice(-1)): ApiResult {
    return { status: 200, body: { organization_id: org, project_id: this.foreign ? 999 : project,
      policy: 'authority-human-prospect-v1', can_review: this.canReview,
      sources: this.canReview && this.current ? [{ ...source(project), url: this.unsafeSource ? 'javascript:evil()' : source(project).url }] : [],
      assignees: this.canReview ? [{ id: 1 }, { id: 2 }] : [], sources_has_more: false,
      reviews: reviews.map((row) => ({ ...row, source_current: this.current, is_latest: row['revision'] === this.rows.length,
        effective_approval: this.current && row['revision'] === this.rows.length && ['approved', 'reported'].includes(String(row['state'])) })), has_more: false } };
  }
  authorityProspects(org: number, project: number, data?: Record<string, unknown>, id?: string, key?: string): Promise<ApiResult> {
    if (!data) {
      if (key) {
        this.queries.push(key); const reviews = this.rows.filter((row) => row['request_key'] === key);
        const result = this.result(org, project, reviews); result.body['lookup'] = reviews.length ? 'found' : 'not_found';
        return Promise.resolve(result);
      }
      return id && this.historyPromise ? this.historyPromise : Promise.resolve(this.result(org, project, id ? [...this.rows].reverse() : this.rows.slice(-1)));
    }
    this.commands.push(data);
    const row = { ...data, id: this.rows.length + 1, prospect_id: id || ID, project_id: project,
      revision: this.rows.length + 1, source_evidence: source(project), source_current: this.current, is_latest: true,
      effective_approval: this.current && ['approved', 'reported'].includes(String(data['state'])),
      approved_at: ['approved', 'reported'].includes(String(data['state'])) ? new Date().toISOString() : null,
      created_at: new Date().toISOString(), scope: 'historical_human_prospect_not_link_proof_or_current_use_permission',
      execution_state: data['executed_at'] ? 'customer_reported_not_verified' : 'not_reported' };
    this.rows.push(row);
    return this.uncertain ? Promise.reject(new Error('Lost acknowledgement')) : Promise.resolve({ status: id ? 200 : 201,
      body: { organization_id: org, project_id: project, review: row } });
  }
}

describe('Private exact research-quote human prospect journey', () => {
  let api: ProspectApi;
  beforeEach(() => { api = new ProspectApi(); TestBed.configureTestingModule({ providers: [provideRouter([
    { path: 'authority/:organizationId/:projectId', component: AuthorityProspects },
  ]), { provide: AccountApi, useValue: api }] }); });
  async function screen(preference: ApiResult | Error = { status: 200, body: { language: 'en', current_ui_language: 'en', current_email_language: 'en' } }) {
    api.preference = preference;
    const harness = await RouterTestingHarness.create();
    const component = await harness.navigateByUrl('/authority/7/9', AuthorityProspects);
    await harness.fixture.whenStable(); harness.detectChanges(); return { harness, component };
  }
  function fillDraft(harness: RouterTestingHarness, rights = true, outreach = true) {
    const form = harness.routeNativeElement!.querySelector('form:has([name="quote"])') as HTMLFormElement;
    const select = form.elements.namedItem('source') as HTMLSelectElement; select.value = '11:0'; select.dispatchEvent(new Event('change'));
    for (const [key, value] of Object.entries({ quote: QUOTE, relevance: 'Human relevance; incomplete coverage only.',
      proposed_action: 'mention', assignee_id: '2', draft_text: 'Exact human draft <script>literal</script>', reason: 'Human decision' })) {
      (form.elements.namedItem(key) as HTMLInputElement).value = value;
    }
    for (const key of ['use_permission', 'storage_permission']) (form.elements.namedItem(key) as HTMLInputElement).checked = rights;
    (form.elements.namedItem('outreach_permission') as HTMLInputElement).checked = outreach;
    return form;
  }
  async function submit(harness: RouterTestingHarness, form: HTMLFormElement) {
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.detectChanges();
  }
  async function decision(harness: RouterTestingHarness, component: AuthorityProspects, dismiss = false) {
    await component.inspect(ID); harness.detectChanges();
    const forms = harness.routeNativeElement!.querySelectorAll('form:has([name="exact"])');
    const form = forms[dismiss ? 1 : 0] as HTMLFormElement;
    (form.elements.namedItem('reason') as HTMLTextAreaElement).value = 'Human reviewed exactly this revision.';
    (form.elements.namedItem('exact') as HTMLInputElement).checked = true;
    return form;
  }
  it.each(['en', 'tr'] as const)('requires independent rights, fixed exact quote/target and unchanged assignee/text approval; execution stays separate in %s', async (language) => {
    const { harness, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } }); const storage = vi.spyOn(Storage.prototype, 'setItem');
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Özel insan otorite adayları — OrganicSEOOps' : 'Private human authority prospects — OrganicSEOOps');
    expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe(language);
    expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe(language === 'tr' ? 'Kayıtlı araştırmadan insanın belirlediği otorite fırsatları' : 'Human authority prospects from stored research');
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'iki dilli onay bekleniyor' : 'No automatic fetch, AI draft, link creation or sending');
    expect(harness.routeNativeElement!.querySelector('ul')!.getAttribute('aria-label')).toBe(component.t('Latest human authority prospects'));
    await submit(harness, fillDraft(harness, false)); expect(api.commands).toEqual([]);
    const invented = fillDraft(harness); (invented.elements.namedItem('quote') as HTMLTextAreaElement).value = 'Invented link evidence';
    await submit(harness, invented); expect(api.commands).toEqual([]); expect(component.error()).toContain('exact unchanged quote');
    expect(harness.routeNativeElement!.querySelector('[role="alert"]')!.textContent).toBe(component.t(component.error()));
    const draft = fillDraft(harness), snapshot = [...new FormData(draft).entries()];
    expect(draft.querySelector('textarea[name="quote"]')!.getAttribute('lang')).toBe('');
    expect(draft.querySelector<HTMLInputElement>('input[name="storage_permission"]')!.required).toBe(true);
    expect(draft.querySelector<HTMLInputElement>('input[name="outreach_permission"]')!.required).toBe(false);
    expect(draft.querySelector<HTMLInputElement>('input[name="outreach_permission"]')!.parentElement!.textContent).toBe(component.t('I independently have permission for the proposed manual outreach; the source quote alone does not grant it. Required before review/approval.'));
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Private human authority prospects — OrganicSEOOps' : 'Özel insan otorite adayları — OrganicSEOOps');
    expect(harness.routeNativeElement!.querySelector('form:has([name="quote"])')).toBe(draft);
    expect([...new FormData(draft).entries()]).toEqual(snapshot); expect(api.commands).toEqual([]); expect(component.sourceSelection()).toBe('11:0');
    component.productLanguage.set(language); harness.detectChanges();
    await submit(harness, draft); expect(api.commands[0]['state']).toBe('draft');
    expect(api.commands[0]['assignee_id']).toBe(2); const intake = api.commands[0]['intake'];
    expect((intake as Record<string, unknown>)['target_url']).toBe(source().url);
    await submit(harness, await decision(harness, component)); expect(api.commands[1]['state']).toBe('review');
    await submit(harness, await decision(harness, component)); expect(api.commands[2]['state']).toBe('approved');
    expect(api.commands[2]['intake']).toEqual(intake); expect(api.commands[2]['assignee_id']).toBe(2);
    expect(api.commands[2]['executed_at']).toBeNull(); await component.inspect(ID); harness.detectChanges();
    expect(harness.routeNativeElement!.textContent).toContain(QUOTE);
    expect(harness.routeNativeElement!.textContent).toContain('Exact human draft <script>literal</script>');
    expect(harness.routeNativeElement!.querySelector('script, img, iframe')).toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? '35 günlük yedek' : '35-day backup');
    expect(harness.routeNativeElement!.textContent).toContain(component.t('Truncated excerpt; wider text unavailable'));
    const report = await decision(harness, component);
    (report.elements.namedItem('executed_at') as HTMLInputElement).value = '2026-10-01T14:30';
    (report.elements.namedItem('execution_note') as HTMLTextAreaElement).value = 'Actual manual execution reported.';
    const exact = report.querySelector<HTMLInputElement>('input[name="exact"]')!;
    expect(exact.required).toBe(true); expect(report.querySelector('button')!.textContent).toBe(component.t('Record actual manual execution only'));
    expect(exact.parentElement!.textContent).toContain(component.t('. Approval does not send.'));
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(report.elements.namedItem('exact')).toBe(exact); expect(exact.checked).toBe(true);
    expect((report.elements.namedItem('executed_at') as HTMLInputElement).value).toBe('2026-10-01T14:30');
    expect((report.elements.namedItem('execution_note') as HTMLTextAreaElement).value).toBe('Actual manual execution reported.');
    expect(api.commands).toHaveLength(3); component.productLanguage.set(language); harness.detectChanges();
    await submit(harness, report); expect(api.commands[3]['state']).toBe('reported');
    expect(api.commands[3]['executed_at']).toBe(new Date('2026-10-01T14:30').toISOString());
    await component.inspect(ID); component.edit(component.selected()!); harness.detectChanges();
    const correction = fillDraft(harness); (correction.elements.namedItem('draft_text') as HTMLTextAreaElement).value = 'Changed draft';
    await submit(harness, correction); expect(api.commands[4]['state']).toBe('draft'); expect(api.commands[4]['expected_revision']).toBe(4);
    expect(api.commands[4]['executed_at']).toBeNull(); expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
    harness.fixture.destroy(); TestBed.inject(Title).setTitle('Next route — OrganicSEOOps');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); TestBed.tick();
    expect(TestBed.inject(Title).getTitle()).toBe('Next route — OrganicSEOOps');
  });
  it.each(['en', 'tr'] as const)('keeps declared outreach permission separate and supports dismissal/reopen without approval in %s', async (language) => {
    const { harness, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } }); await submit(harness, fillDraft(harness, true, false));
    await component.inspect(ID); harness.detectChanges();
    const button = harness.routeNativeElement!.querySelector('form:has([name="executed_at"]), form:has([name="exact"]) button') as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(harness.routeNativeElement!.textContent).toContain(component.t('No'));
    const selected = component.selected(), history = component.historyRows();
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(button.disabled).toBe(true); expect(component.selected()).toEqual(selected); expect(component.historyRows()).toEqual(history);
    expect(component.selected()!.intake.outreach_permission).toBe(false); expect(api.commands).toHaveLength(1);
    component.productLanguage.set(language); harness.detectChanges();
    await submit(harness, await decision(harness, component, true)); expect(api.commands[1]['state']).toBe('dismissed');
    await component.inspect(ID); component.edit(component.selected()!); harness.detectChanges();
    await submit(harness, fillDraft(harness)); expect(api.commands[2]['state']).toBe('draft'); expect(api.commands[2]['expected_revision']).toBe(2);
  });
  it.each(['en', 'tr'] as const)('reconciles a lost acknowledgement exactly without replay and rejects mismatched immutable acknowledgement in %s', async (language) => {
    const { harness, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } }); api.uncertain = true;
    await submit(harness, fillDraft(harness)); expect(component.pending()).not.toBeNull();
    const pending = structuredClone(component.pending());
    expect(harness.routeNativeElement!.textContent).toContain(component.t('The exact save outcome is uncertain. This command is frozen in component memory; no automatic replay.'));
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(component.pending()).toEqual(pending); expect(api.commands).toHaveLength(1); expect(api.queries).toEqual([]);
    component.productLanguage.set(language); harness.detectChanges();
    await component.reconcile(); expect(api.commands.length).toBe(1); expect(api.queries).toEqual([api.commands[0]['request_key']]);
    expect(component.pending()).toBeNull(); expect(component.message()).toContain('no command replayed'); harness.detectChanges();
    expect(harness.routeNativeElement!.textContent).toContain(component.t(component.message()));
    api.rows = []; api.commands = []; api.uncertain = false; await component.load(); harness.detectChanges();
    const save = api.authorityProspects.bind(api);
    vi.spyOn(api, 'authorityProspects').mockImplementation(async (org, project, data, id, key) => {
      const result = await save(org, project, data, id, key);
      if (data) (result.body['review'] as Record<string, unknown>)['assignee_id'] = 1;
      return result;
    });
    await submit(harness, fillDraft(harness)); expect(component.pending()).not.toBeNull();
    await component.reconcile(); expect(component.pending()).not.toBeNull(); expect(component.notFound()).toBe(false);
    expect(api.commands.length).toBe(1);
  });
  it('keeps history read-only after role/source loss and denies unsafe/foreign candidate payloads and unknown replay', async () => {
    api.canReview = false; const { harness, component } = await screen(); expect(harness.routeNativeElement!.querySelector('form')).toBeNull();
    api.canReview = true; await component.load(); harness.detectChanges(); await submit(harness, fillDraft(harness));
    api.current = false; await component.inspect(ID); harness.detectChanges();
    expect(harness.routeNativeElement!.querySelector('[name="exact"]')).toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain('manual-use reporting are denied');
    api.canReview = false; await component.inspect(ID); harness.detectChanges(); expect(harness.routeNativeElement!.querySelector('form')).toBeNull();
    api.canReview = true; api.current = true; api.rows = []; api.unsafeSource = true; await component.load(); expect(component.context()).toBeNull();
    api.unsafeSource = false; api.foreign = true; await component.load(); expect(component.context()).toBeNull();
    api.foreign = false; await component.load(); harness.detectChanges(); api.uncertain = true;
    await submit(harness, fillDraft(harness)); api.rows = []; api.canReview = false; await component.reconcile();
    component.retry(); expect(component.notFound()).toBe(false); expect(api.commands.length).toBe(2);
  });
  it('discards late project/history responses and clears private evidence on route reuse', async () => {
    const { harness, component } = await screen(); await submit(harness, fillDraft(harness));
    let resolve!: (value: ApiResult) => void; api.historyPromise = new Promise((done) => resolve = done);
    const pending = component.inspect(ID); const old = api.result(7, 9, [...api.rows]);
    api.rows = []; await harness.navigateByUrl('/authority/7/10', AuthorityProspects); resolve(old); await pending;
    expect(component.selected()).toBeNull(); expect(component.historyRows()).toEqual([]); expect(component.editing()).toBeNull();
    expect(component.pending()).toBeNull(); harness.detectChanges(); expect(harness.routeNativeElement!.textContent).not.toContain(QUOTE);
  });

  it('keeps invalid unavailable preferences and fresh production authority prospects English without commands', async () => {
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    try {
      for (const mode of ['invalid', 'incompatible', 'signed-out', 'unavailable', 'production'] as const) {
        TestBed.resetTestingModule(); api = new ProspectApi();
        TestBed.configureTestingModule({ providers: [provideRouter([
          { path: 'authority/:organizationId/:projectId', component: AuthorityProspects },
        ]), { provide: AccountApi, useValue: api }] });
        buildEnvironment.production = mode === 'production';
        const preference: ApiResult | Error = mode === 'unavailable' ? new Error('private preference error')
          : mode === 'signed-out' ? { status: 401, body: {} } : { status: 200, body: {
            language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: mode === 'incompatible' ? 'tr' : 'en', current_email_language: 'en' } };
        const { harness, component } = await screen(preference);
        expect(TestBed.inject(Title).getTitle()).toBe('Private human authority prospects — OrganicSEOOps');
        expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe('Human authority prospects from stored research');
        expect(harness.routeNativeElement!.textContent).not.toContain('private preference error');
        expect(harness.routeNativeElement!.textContent).not.toContain('incelenmemiş Türkçe');
        if (mode === 'production') expect(component.productLanguage()).toBe('tr');
        api.foreign = true; await component.load(); harness.detectChanges();
        expect(harness.routeNativeElement!.querySelector('[role="alert"]')!.textContent).toBe('Prospect history or current project/session authority is unavailable.');
        expect(api.commands).toEqual([]); expect(api.queries).toEqual([]); harness.fixture.destroy();
      }
    } finally { buildEnvironment.production = production; }
  });
});
