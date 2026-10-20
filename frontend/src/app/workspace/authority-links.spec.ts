import { Title } from '@angular/platform-browser';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { vi } from 'vitest';
import { AccountApi, ApiResult } from '../account/account-api';
import { AuthorityLinks } from './authority-links';
import { environment } from '../../environments/environment';

const ID = '00000000-0000-4000-8000-000000000001';
const SOURCE = 'https://publisher.example.invalid/article';
const URL = 'https://own.example.invalid/target';
const DATE = '2026-01-01T12:00:00+03:00';
const ANCHOR = 'Literal <img src=x onerror=evil()> &amp; anchor';
const target = (project = 9) => ({ method: 'authority-own-target-http-v1', project_id: project, configuration_revision: 1,
  origin: 'https://own.example.invalid', verification_id: 10, verified_at: '2025-12-01T00:00:00+00:00',
  crawl_page_id: 11, crawl_run_id: 12, job_id: 13, crawl_method: 'http-crawl-v1', requested_url: URL, final_url: URL,
  observed_at: '2026-01-01T08:00:00+00:00', completed_at: '2026-01-01T08:01:00+00:00',
  content_observed_at: '2026-01-01T08:00:00+00:00', status_code: 404 as number | null, error_category: '', body_sha256: 'a'.repeat(64),
  raw_artifact_id: 14 as number | null, raw_body_readback: 'checked', reused_from_id: null as number | null, redirect_chain: [],
  coverage: { page_limit: 2, pages_attempted: 2, pages_observed: 2, crawl_status: 'succeeded', whole_site: 'not_established' },
  state: 'dated_http_missing_destination_candidate', external_source: 'customer_reported_not_independently_verified',
  unlinked_or_lost_link: 'not_established', interpretation: 'separate_dated_own_target_http_not_current_site_or_external_link_verification' });
const recovery = (project = 9) => ({ method: 'authority-own-target-recovery-v1', project_id: project, target_evidence: target(project),
  action_review_id: 21, action_id: '00000000-0000-4000-8000-000000000002', action_revision: 2, state: 'accepted', action_kind: 'refresh',
  affected_urls: [URL], assignee_id: 2, acceptance_criteria: 'Review genuine own-target useful destination separately.',
  opportunity_id: 22, finding_id: 23, diagnostics_id: 24, site_approval_review_id: 21, implemented_at: null,
  interpretation: 'existing_separately_approved_own_page_action_not_outreach_or_external_link_recovery_proof' });

class LinkApi {
  preference: ApiResult | Error = { status: 200, body: { language: 'en', current_ui_language: 'en', current_email_language: 'en' } };
  async productLanguage(): Promise<ApiResult> { if (this.preference instanceof Error) throw this.preference; return this.preference; }
  commands: Record<string, unknown>[] = []; rows: Record<string, unknown>[] = []; queries: string[] = [];
  canReview = true; current = true; uncertain = false; dropSave = false; foreign = false;
  changedTarget = false; changedRecovery = false; unsafe = false; assignees = [1, 2];
  historyPromise: Promise<ApiResult> | null = null;
  result(org = 7, project = 9, reviews = this.rows.slice(-1)): ApiResult {
    const destination = { ...target(project), verification_id: this.changedTarget ? 99 : 10,
      requested_url: this.unsafe ? 'javascript:evil()' : URL };
    const handoff = { ...recovery(project), action_revision: this.changedRecovery ? 3 : 2, target_evidence: destination };
    return { status: 200, body: { organization_id: org, project_id: this.foreign ? 999 : project, policy: 'authority-human-link-v1',
      can_review: this.canReview, targets: this.canReview && this.current ? [destination] : [],
      recovery_actions: this.canReview && this.current ? [handoff] : [], assignees: this.canReview ? this.assignees.map((id) => ({ id })) : [],
      candidates_has_more: false, has_more: false, source_basis: 'actual_own_target_http_and_separate_page_action_no_external_report',
      sending: 'unavailable', independent_external_verification: 'unavailable', lost_unlinked_links: 'not_established',
      reviews: reviews.map((row) => ({ ...row, source_current: this.current, is_latest: row['revision'] === this.rows.length,
        effective_approval: this.current && row['revision'] === this.rows.length && ['approved', 'reported'].includes(String(row['state'])) })) } };
  }
  authorityLinks(org: number, project: number, data?: Record<string, unknown>, id?: string, key?: string): Promise<ApiResult> {
    if (!data) {
      if (key) {
        this.queries.push(key); const reviews = this.rows.filter((row) => row['request_key'] === key);
        const result = this.result(org, project, reviews); result.body['lookup'] = reviews.length ? 'found' : 'not_found'; return Promise.resolve(result);
      }
      return id && this.historyPromise ? this.historyPromise : Promise.resolve(this.result(org, project, id ? [...this.rows].reverse() : this.rows.slice(-1)));
    }
    this.commands.push(structuredClone(data));
    if (this.dropSave) return Promise.reject(new Error('Outcome unknown; fixture did not persist'));
    const row = { ...structuredClone(data), id: this.rows.length + 1, link_id: id || ID, project_id: project, revision: this.rows.length + 1,
      target_evidence: target(project), recovery_evidence: data['recovery_action_review_id'] ? recovery(project) : {},
      source_current: this.current, is_latest: true, effective_approval: this.current && ['approved', 'reported'].includes(String(data['state'])),
      approved_at: ['approved', 'reported'].includes(String(data['state'])) ? '2026-01-02T00:00:00+00:00' : null,
      created_at: '2026-01-02T00:00:00+00:00', scope: 'historical_human_link_report_not_independent_link_proof_or_site_approval',
      execution_state: data['executed_at'] ? 'customer_reported_manual_activity_not_verified' : 'not_reported' };
    this.rows.push(row);
    return this.uncertain ? Promise.reject(new Error('Lost acknowledgement')) : Promise.resolve({ status: id ? 200 : 201,
      body: { organization_id: org, project_id: project, review: row } });
  }
}

describe('Private literal human link and separate own-target recovery journey', () => {
  let api: LinkApi;
  beforeEach(() => { api = new LinkApi(); TestBed.configureTestingModule({ providers: [provideRouter([
    { path: 'links/:organizationId/:projectId', component: AuthorityLinks },
  ]), { provide: AccountApi, useValue: api }] }); });
  async function screen(preference: ApiResult | Error = { status: 200, body: { language: 'en', current_ui_language: 'en', current_email_language: 'en' } }) {
    api.preference = preference;
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/links/7/9', AuthorityLinks);
    await harness.fixture.whenStable(); harness.detectChanges(); return { harness, component };
  }
  function fillDraft(harness: RouterTestingHarness, action = 'verify_source', rights = true, outreach = false) {
    let form = harness.routeNativeElement!.querySelector('form:has([name="observation_reference"])') as HTMLFormElement;
    const select = form.elements.namedItem('target') as HTMLSelectElement; select.value = '11'; select.dispatchEvent(new Event('change'));
    const activity = form.elements.namedItem('action') as HTMLSelectElement; activity.value = action; activity.dispatchEvent(new Event('change'));
    harness.detectChanges(); form = harness.routeNativeElement!.querySelector('form:has([name="observation_reference"])') as HTMLFormElement;
    for (const [key, value] of Object.entries({ observation_reference: 'independent-report-1', source_url: SOURCE, observed_at: DATE,
      status: 'observed', coverage: 'partial_page', surface: 'html_document', href: URL, anchor_text: ANCHOR, rel: 'nofollow sponsored',
      evidence_note: 'Independent human report only; not verified externally.', relevance: 'Useful target; separate site approval.',
      assignee_id: '2', draft_text: 'Literal human draft <script>not executable</script>', reason: 'Human draft reason' })) {
      (form.elements.namedItem(key) as HTMLInputElement).value = value;
    }
    if (action === 'review_target_recovery') (form.elements.namedItem('recovery_action_review_id') as HTMLSelectElement).value = '21';
    for (const key of ['use_permission', 'storage_permission', 'not_restricted_provider_copy', 'no_personal_payload'])
      (form.elements.namedItem(key) as HTMLInputElement).checked = rights;
    (form.elements.namedItem('outreach_permission') as HTMLInputElement).checked = outreach;
    return form;
  }
  async function submit(harness: RouterTestingHarness, form: HTMLFormElement) {
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); await harness.fixture.whenStable(); harness.detectChanges();
  }
  async function decision(harness: RouterTestingHarness, component: AuthorityLinks, dismiss = false) {
    await component.inspect(ID); harness.detectChanges();
    const form = harness.routeNativeElement!.querySelectorAll('form:has([name="exact"])')[dismiss ? 1 : 0] as HTMLFormElement;
    (form.elements.namedItem('reason') as HTMLTextAreaElement).value = 'Human reviewed unchanged source, target and assignee.';
    (form.elements.namedItem('exact') as HTMLInputElement).checked = true; return form;
  }
  it('rejects array human link actions in current and exact history while preserving scalar recovery requirements', async () => {
    const { harness, component } = await screen();
    await submit(harness, fillDraft(harness, 'verify_source'));
    const original = structuredClone(api.rows[0]), proposal = original['proposal'] as Record<string, unknown>;
    expect(api.commands).toHaveLength(1);
    for (const action of ['verify_source', 'request_source_correction', 'review_target_recovery']) {
      const malformed = { ...original, proposal: { ...proposal, action: [action] } };
      api.rows = [malformed]; await component.load(); harness.detectChanges();
      expect(component.context()).toBeNull(); expect(component.selected()).toBeNull(); expect(component.historyRows()).toEqual([]);
      expect(component.error()).toContain('Link history or current project/session authority is unavailable');
      api.rows = [original]; await component.load(); await component.inspect(ID);
      expect(component.selected()?.proposal.action).toBe('verify_source');
      api.rows = [malformed]; await component.inspect(ID);
      expect(component.context()).toBeNull(); expect(component.selected()).toBeNull(); expect(component.historyRows()).toEqual([]);
      expect(component.message()).toContain('Exact history is unavailable');
      api.rows = [original]; await component.load();
    }
    expect(api.commands).toHaveLength(1);
    for (const action of ['verify_source', 'request_source_correction', 'review_target_recovery']) {
      api.rows = []; await component.load(); harness.detectChanges();
      await submit(harness, fillDraft(harness, action, true, true));
      expect(component.pending()).toBeNull(); await component.inspect(ID);
      expect(component.selected()?.proposal.action).toBe(action);
      expect(component.selected()?.recovery_action_review_id).toBe(action === 'review_target_recovery' ? 21 : null);
      if (action === 'review_target_recovery') expect(component.selected()?.recovery_evidence).toEqual(recovery());
    }
    expect(api.commands).toHaveLength(4);
  });

  it.each(['en', 'tr'] as const)('requires original literal rights/source/date, preserves exact recovery approval and separates manual reporting/corrections in %s', async (language) => {
    const { harness, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } }); const storage = vi.spyOn(Storage.prototype, 'setItem');
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Özel insan bağlantı ve kurtarma incelemesi — OrganicSEOOps' : 'Private human link and recovery review — OrganicSEOOps');
    expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe(language);
    expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe(language === 'tr' ? 'İnsan bağlantı bildirimleri ve ayrı hedef kurtarma incelemesi' : 'Human link reports and separate destination recovery review');
    expect(harness.routeNativeElement!.querySelector('ul')!.getAttribute('aria-label')).toBe(component.t('Latest human link reviews'));
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'iki dilli onay bekleniyor' : 'No automatic fetch, AI draft, link creation or sending');
    await submit(harness, fillDraft(harness, 'review_target_recovery', false)); expect(api.commands).toEqual([]);
    const relative = fillDraft(harness); (relative.elements.namedItem('href') as HTMLInputElement).value = '/target';
    await submit(harness, relative); expect(api.commands).toEqual([]); expect(component.error()).toContain('literal independent evidence');
    const naive = fillDraft(harness); (naive.elements.namedItem('observed_at') as HTMLInputElement).value = '2026-01-01T12:00:00';
    await submit(harness, naive); expect(api.commands).toEqual([]);
    harness.detectChanges(); expect(harness.routeNativeElement!.querySelector('[role="alert"]')!.textContent).toBe(component.t(component.error()));
    const draft = fillDraft(harness, 'review_target_recovery'), fields = [...new FormData(draft).entries()];
    const permission = draft.elements.namedItem('storage_permission') as HTMLInputElement;
    const outreach = draft.elements.namedItem('outreach_permission') as HTMLInputElement;
    expect(permission.required).toBe(true); expect(outreach.required).toBe(false);
    expect(outreach.parentElement!.textContent).toBe(component.t('I separately have permission for proposed manual outreach. A reported link does not grant it.'));
    expect(draft.querySelector('[name="draft_text"]')!.getAttribute('lang')).toBe('');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Private human link and recovery review — OrganicSEOOps' : 'Özel insan bağlantı ve kurtarma incelemesi — OrganicSEOOps');
    expect(harness.routeNativeElement!.querySelector('form:has([name="observation_reference"])')).toBe(draft);
    expect([...new FormData(draft).entries()]).toEqual(fields); expect(component.targetSelection()).toBe('11');
    expect(component.actionSelection()).toBe('review_target_recovery'); expect(api.commands).toEqual([]);
    component.productLanguage.set(language); harness.detectChanges();
    await submit(harness, draft); const intake = api.commands[0]['intake']; const proposal = api.commands[0]['proposal'];
    expect((intake as Record<string, unknown>)['observed_at']).toBe(DATE); expect((intake as Record<string, unknown>)['href']).toBe(URL);
    expect(api.commands[0]['recovery_action_review_id']).toBe(21);
    await submit(harness, await decision(harness, component)); expect(api.commands[1]['state']).toBe('review');
    await submit(harness, await decision(harness, component)); expect(api.commands[2]['state']).toBe('approved');
    expect(api.commands[2]['intake']).toEqual(intake); expect(api.commands[2]['proposal']).toEqual(proposal);
    expect(api.commands[2]['assignee_id']).toBe(2); expect(api.commands[2]['executed_at']).toBeNull();
    await component.inspect(ID); harness.detectChanges(); const body = harness.routeNativeElement!;
    expect(body.textContent).toContain(ANCHOR); expect(body.textContent).toContain(DATE); expect(body.textContent).toContain('nofollow sponsored');
    expect(body.textContent).toContain(language === 'tr' ? 'web sitesi değişikliğini hiçbir zaman onaylamaz veya uygulamaz' : 'never approves or executes a website change'); expect(body.textContent).toContain(language === 'tr' ? '35 günlük yedek' : '35-day backup');
    expect(body.querySelector('script, img, iframe')).toBeNull();
    const report = await decision(harness, component); (report.elements.namedItem('executed_at') as HTMLInputElement).value = '2026-01-03T12:00';
    (report.elements.namedItem('execution_note') as HTMLTextAreaElement).value = 'Actual human recovery handoff only.';
    const exact = report.elements.namedItem('exact') as HTMLInputElement;
    expect(exact.required).toBe(true); expect(exact.parentElement!.textContent).toContain(component.t('. Approval does not send or change the site.'));
    expect(report.querySelector('button')!.textContent).toBe(component.t('Record actual manual activity only'));
    const selected = component.selected(), history = component.historyRows(), reportFields = [...new FormData(report).entries()];
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(report.elements.namedItem('exact')).toBe(exact); expect(exact.checked).toBe(true); expect([...new FormData(report).entries()]).toEqual(reportFields);
    expect(component.selected()).toBe(selected); expect(component.historyRows()).toBe(history); expect(api.commands).toHaveLength(3);
    component.productLanguage.set(language); harness.detectChanges();
    await submit(harness, report); expect(api.commands[3]['state']).toBe('reported');
    expect(api.commands[3]['executed_at']).toBe(new Date('2026-01-03T12:00').toISOString());
    await component.inspect(ID); component.edit(component.selected()!); harness.detectChanges();
    const correction = fillDraft(harness); (correction.elements.namedItem('draft_text') as HTMLTextAreaElement).value = 'Changed text';
    await submit(harness, correction); expect(api.commands[4]['state']).toBe('draft'); expect(api.commands[4]['expected_revision']).toBe(4);
    expect(api.commands[4]['executed_at']).toBeNull(); expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
    harness.fixture.destroy(); TestBed.inject(Title).setTitle('Next route — OrganicSEOOps');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); TestBed.tick();
    expect(TestBed.inject(Title).getTitle()).toBe('Next route — OrganicSEOOps');
  });
  it.each(['en', 'tr'] as const)('does not infer loss from complete-declared absence and keeps source-correction outreach permission separate in %s', async (language) => {
    const { harness, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } }); const absent = fillDraft(harness);
    for (const [key, value] of Object.entries({ status: 'not_seen_in_inspected_page', coverage: 'complete_document_customer_reported', href: '', anchor_text: '', rel: '' }))
      (absent.elements.namedItem(key) as HTMLInputElement).value = value;
    await submit(harness, absent); await component.inspect(ID); harness.detectChanges();
    expect(component.selected()?.intake.href).toBe(''); expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'bağlantısız bahsedilmeyi veya kaybolmuş bağlantıyı kanıtlamaz' : 'does not prove an unlinked mention or lost link');
    const dismissal = await decision(harness, component, true); await submit(harness, dismissal); expect(api.commands[1]['state']).toBe('dismissed');
    await component.inspect(ID); component.edit(component.selected()!); harness.detectChanges();
    await submit(harness, fillDraft(harness, 'request_source_correction', true, false));
    await component.inspect(ID); harness.detectChanges();
    const button = harness.routeNativeElement!.querySelector('form:has([name="exact"]) button') as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    const selected = component.selected(); component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(component.selected()).toBe(selected); expect(component.selected()?.proposal.outreach_permission).toBe(false);
    expect(button.disabled).toBe(true); expect(api.commands).toHaveLength(3);
    component.productLanguage.set(language); harness.detectChanges();
    const denied = await decision(harness, component); await submit(harness, denied); expect(api.commands.length).toBe(3);
    component.edit(component.selected()!); harness.detectChanges(); await submit(harness, fillDraft(harness, 'request_source_correction', true, true));
    await submit(harness, await decision(harness, component)); expect(api.commands[4]['state']).toBe('review');
  });
  it.each(['en', 'tr'] as const)('reconciles exact stored evidence across JSONB key order without replay and rejects mismatched acknowledgement in %s', async (language) => {
    const { harness, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } }); api.uncertain = true; await submit(harness, fillDraft(harness, 'review_target_recovery'));
    expect(component.pending()).not.toBeNull();
    const pending = component.pending();
    expect(harness.routeNativeElement!.textContent).toContain(component.t('The exact save outcome is uncertain. Command and target/recovery snapshots are frozen in component memory. No automatic replay.'));
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(component.pending()).toBe(pending); expect(api.commands).toHaveLength(1); expect(api.queries).toEqual([]);
    component.productLanguage.set(language); harness.detectChanges();
    const row = api.rows[0]; row['intake'] = Object.fromEntries(Object.entries(row['intake'] as object).reverse());
    row['target_evidence'] = Object.fromEntries(Object.entries(row['target_evidence'] as object).reverse());
    await component.reconcile(); expect(component.pending()).toBeNull(); expect(api.commands.length).toBe(1);
    harness.detectChanges(); expect(harness.routeNativeElement!.textContent).toContain(component.t(component.message()));
    expect(api.queries).toEqual([api.commands[0]['request_key']]); expect(component.message()).toContain('no command replayed');
    api.rows = []; api.commands = []; api.uncertain = false; await component.load(); harness.detectChanges();
    const send = api.authorityLinks.bind(api);
    vi.spyOn(api, 'authorityLinks').mockImplementation(async (org, project, data, id, key) => {
      const result = await send(org, project, data, id, key);
      if (data) (result.body['review'] as Record<string, unknown>)['target_evidence'] = { ...target(project), verified_at: '2025-12-02T00:00:00+00:00' };
      return result;
    });
    await submit(harness, fillDraft(harness)); expect(component.pending()).not.toBeNull(); await component.reconcile();
    expect(component.pending()).not.toBeNull(); expect(component.notFound()).toBe(false); expect(api.commands.length).toBe(1);
  });
  it('only explicitly retries a frozen command after fresh exact target/recovery/assignee/role checks', async () => {
    const { harness, component } = await screen(); api.dropSave = true;
    await submit(harness, fillDraft(harness, 'review_target_recovery')); const frozen = structuredClone(component.pending());
    await component.reconcile(); expect(component.notFound()).toBe(true); expect(api.commands.length).toBe(1);
    api.changedRecovery = true; await component.retry(); expect(api.commands.length).toBe(1); expect(component.notFound()).toBe(false);
    api.changedRecovery = false; api.changedTarget = true; await component.reconcile(); expect(component.notFound()).toBe(false);
    api.changedTarget = false; api.assignees = [1]; await component.reconcile(); expect(component.notFound()).toBe(false);
    api.assignees = [1, 2]; api.canReview = false; await component.reconcile(); expect(component.notFound()).toBe(false);
    api.canReview = true; await component.reconcile(); expect(component.notFound()).toBe(true);
    expect(component.pending()).toEqual(frozen); api.dropSave = false; await component.retry();
    expect(api.commands.length).toBe(2); expect(api.commands[1]).toEqual(api.commands[0]); expect(component.pending()).toBeNull();
  });
  it('keeps stale/role-lost history inert and rejects unsafe/foreign candidates and late route responses', async () => {
    api.canReview = false; const { harness, component } = await screen(); expect(harness.routeNativeElement!.querySelector('form')).toBeNull();
    api.canReview = true; await component.load(); harness.detectChanges(); await submit(harness, fillDraft(harness));
    api.current = false; await component.inspect(ID); harness.detectChanges(); expect(harness.routeNativeElement!.querySelector('[name="exact"]')).toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain('manual activity reporting are denied');
    api.canReview = false; await component.inspect(ID); harness.detectChanges(); expect(harness.routeNativeElement!.querySelector('form')).toBeNull();
    api.canReview = true; api.current = true; api.rows = []; api.unsafe = true; await component.load(); expect(component.context()).toBeNull();
    api.unsafe = false; api.foreign = true; await component.load(); expect(component.context()).toBeNull();
    api.foreign = false; await component.load(); harness.detectChanges(); await submit(harness, fillDraft(harness));
    let resolve!: (value: ApiResult) => void; api.historyPromise = new Promise((done) => resolve = done);
    const pending = component.inspect(ID); const old = api.result(7, 9, [...api.rows]); api.rows = [];
    await harness.navigateByUrl('/links/7/10', AuthorityLinks); resolve(old); await pending; harness.detectChanges();
    expect(component.selected()).toBeNull(); expect(component.historyRows()).toEqual([]); expect(component.editing()).toBeNull();
    expect(component.pending()).toBeNull(); expect(harness.routeNativeElement!.textContent).not.toContain(ANCHOR);
  });

  it('keeps invalid unavailable preferences and fresh production human-link interfaces English without commands', async () => {
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    try {
      for (const mode of ['invalid', 'incompatible', 'signed-out', 'unavailable', 'production'] as const) {
        TestBed.resetTestingModule(); api = new LinkApi();
        TestBed.configureTestingModule({ providers: [provideRouter([
          { path: 'links/:organizationId/:projectId', component: AuthorityLinks },
        ]), { provide: AccountApi, useValue: api }] });
        buildEnvironment.production = mode === 'production';
        const preference: ApiResult | Error = mode === 'unavailable' ? new Error('private preference error')
          : mode === 'signed-out' ? { status: 401, body: {} } : { status: 200, body: {
            language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: mode === 'incompatible' ? 'tr' : 'en', current_email_language: 'en' } };
        const { harness, component } = await screen(preference);
        expect(TestBed.inject(Title).getTitle()).toBe('Private human link and recovery review — OrganicSEOOps');
        expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe('Human link reports and separate destination recovery review');
        expect(harness.routeNativeElement!.textContent).not.toContain('private preference error');
        expect(harness.routeNativeElement!.textContent).not.toContain('incelenmemiş Türkçe');
        if (mode === 'production') expect(component.productLanguage()).toBe('tr');
        api.foreign = true; await component.load(); harness.detectChanges();
        expect(harness.routeNativeElement!.querySelector('[role="alert"]')!.textContent).toBe('Link history or current project/session authority is unavailable.');
        expect(api.commands).toEqual([]); expect(api.queries).toEqual([]); harness.fixture.destroy();
      }
    } finally { buildEnvironment.production = production; }
  });
});
