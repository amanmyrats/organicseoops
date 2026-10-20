import { Title } from '@angular/platform-browser';
import { createHash } from 'node:crypto';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { vi } from 'vitest';
import { AccountApi, ApiResult } from '../account/account-api';
import { ContentLifecycle } from './content-lifecycle';
import { environment } from '../../environments/environment';

const ID = '00000000-0000-4000-8000-000000000001';
const QUOTE = 'Original details <img src=x onerror=evil()> &amp; require human evidence.';
const ago = (minutes: number) => new Date(Date.now() - minutes * 60000).toISOString();
function native(project = 9) {
  return { id: 44, project_id: project, item_id: 33, revision: 1, brief_id: 22, state: 'draft',
    created_at: ago(120), kind: 'service', title: 'Synthetic genuine-service draft', body: QUOTE, meta_description: 'Unverified <script>literal</script>' };
}
function source(text: ReturnType<typeof native>) {
  const hash = createHash('sha256').update(JSON.stringify({ body: text.body, kind: text.kind,
    meta_description: text.meta_description, title: text.title })).digest('hex');
  return { method: 'content-lifecycle-source-v1', project_id: text.project_id, configuration_revision: 1,
    source_current: true, content: { item_id: text.item_id, revision_id: text.id, revision: text.revision,
      kind: text.kind, title: text.title, text_sha256: hash, state: text.state, actor_id: 1, created_at: text.created_at,
      publication_url: '', published_at: null, publication_basis: 'historical_manual_report_not_verified_live_content_or_publication_age',
      archive_effect: 'record_only_no_live_page_removed' },
    brief: { id: text.brief_id, sha256: 'b'.repeat(64), size_bytes: 200, created_at: ago(180), actor_id: 1 },
    action: { review_id: 11, action_id: ID, revision: 1, affected_urls: ['https://own.example.invalid/service'],
      approval: 'separate_existing_page_action_not_content_lifecycle_approval' },
    sources: [{ source_index: 0, method: 'authority-research-evidence-v1', research_job_id: 10, step_id: 12,
      artifact_id: 13, source_size_bytes: 300, original_response_sha256: 'a'.repeat(64), retrieved_at: ago(240),
      requested_url: 'https://source.example.invalid/article', url: 'https://source.example.invalid/article', title: 'Synthetic original source',
      excerpt_truncated: true, coverage: 'selected_bounded_public_page_text_only', facts: 'unverified' }],
    expertise: 'not_recorded_requires_human_evidence', service_facts: 'not_verified_by_research_or_manual_local_assessment',
    quality_judgment: 'not_recorded', conversion_context: 'unavailable_exact_origin_attribution_not_established',
    interpretation: 'saved_native_text_and_dated_sources_not_live_page_quality_or_deletion_recommendation' };
}
class QualityApi {
  preference: ApiResult | Error = { status: 200, body: { language: 'en', current_ui_language: 'en', current_email_language: 'en' } };
  async productLanguage(): Promise<ApiResult> { if (this.preference instanceof Error) throw this.preference; return this.preference; }
  text = native(); evidence = source(this.text); rows: Record<string, unknown>[] = [];
  otherText = { ...native(10), id: 45, item_id: 34, brief_id: 23, title: 'Independent other-project title' };
  otherEvidence = source(this.otherText); canOtherReview = true; pairReads: number[][] = [];
  pairPromise: Promise<ApiResult> | null = null;
  commands: Record<string, unknown>[] = []; keys: string[] = []; reads = 0; detailReads = 0;
  canReview = true; current = true; assignee = true; drop = false; lost = false; foreign = false;
  detailPromise: Promise<ApiResult> | null = null;
  result(org = 7, project = 9, rows = this.rows.slice(-1)): ApiResult {
    const canReview = this.canReview && (project !== 10 || this.canOtherReview);
    return { status: 200, body: structuredClone({ organization_id: org, project_id: this.foreign ? 999 : project,
      policy: 'content-human-quality-v1', can_review: canReview,
      sources: this.current && canReview ? [project === 10 ? this.otherEvidence : this.evidence] : [], assignees: this.assignee && canReview ? [{ id: 2 }] : [],
      sources_has_more: false, reviews: rows.map((row) => ({ ...row, source_current: this.current,
        is_latest: row['revision'] === this.rows.length,
        effective_approval: this.current && row['revision'] === this.rows.length && ['approved', 'reported'].includes(String(row['state'])) })),
      has_more: false, source_basis: 'actual_saved_native_text_and_dated_sources_not_verified_live_page_or_service_facts',
      site_action: 'separate_existing_page_action_approval_implementation_and_outcome_required' }) };
  }
  projectContent(_org: number, project: number, item: number): Promise<ApiResult> {
    this.detailReads++;
    return this.detailPromise || Promise.resolve({ status: 200, body: { project_id: project,
      current: structuredClone(this.text), source_state: 'current_review_still_required', history: [] } });
  }
  contentLifecycle(org: number, project: number, data?: Record<string, unknown>, id?: string, key?: string): Promise<ApiResult> {
    if (!data) {
      this.reads++;
      if (key) {
        this.keys.push(key); const rows = this.rows.filter((row) => row['request_key'] === key);
        const result = this.result(org, project, rows); result.body['lookup'] = rows.length ? 'found' : 'not_found';
        return Promise.resolve(result);
      }
      return Promise.resolve(this.result(org, project, project === 10 ? [] : id ? [...this.rows].reverse() : this.rows.slice(-1)));
    }
    this.commands.push(structuredClone(data));
    const approved = ['approved', 'reported'].includes(String(data['state']));
    const previous = this.rows.at(-1);
    const row = { ...structuredClone(data), id: this.rows.length + 1, review_id: id || ID, project_id: project,
      revision: this.rows.length + 1, content_revision_id: 44, source_evidence: structuredClone(this.evidence), actor_id: 1, source_actor_id: 1,
      reviewed_revision_id: approved ? data['state'] === 'approved' ? previous!['id'] : previous!['reviewed_revision_id'] : null,
      approved_by_id: approved ? 1 : null, approved_at: data['state'] === 'reported' ? previous!['approved_at'] : approved ? ago(2) : null,
      created_at: ago(1), source_current: this.current, is_latest: true, effective_approval: this.current && approved,
      scope: 'historical_human_content_judgment_not_verified_live_quality_or_site_approval',
      execution_state: data['executed_at'] ? 'manual_handoff_not_site_implementation_or_outcome' : 'not_reported' };
    if (!this.drop) this.rows.push(row);
    return this.lost || this.drop ? Promise.reject(new Error('Lost acknowledgment'))
      : Promise.resolve({ status: id ? 200 : 201, body: { organization_id: org, project_id: project, review: row } });
  }
  contentComparison(org: number, project: number, revision: number, otherOrg: number, otherProject: number, otherRevision: number): Promise<ApiResult> {
    this.pairReads.push([org, project, revision, otherOrg, otherProject, otherRevision]);
    const text = (row: typeof this.text) => ({ kind: row.kind, title: row.title, body: row.body, meta_description: row.meta_description });
    return this.pairPromise || Promise.resolve({ status: 200, body: structuredClone({ organization_id: org, project_id: project,
      comparison: { method: 'content-native-comparison-v1',
        left: { organization_id: org, project_id: project, source: this.evidence, text: text(this.text) },
        right: { organization_id: otherOrg, project_id: otherProject, source: this.otherEvidence, text: text(this.otherText) },
        same_native_body: this.text.body === this.otherText.body,
        interpretation: 'saved_native_text_only_not_live_duplicate_content_thinness_or_service_verification',
        site_action: 'separate_human_judgment_and_each_project_action_approval_required' } }) });
  }
}

describe('Private exact native-text human quality journey', () => {
  let api: QualityApi;
  beforeEach(() => { api = new QualityApi(); TestBed.configureTestingModule({ providers: [provideRouter([
    { path: 'quality/:organizationId/:projectId', component: ContentLifecycle },
  ]), { provide: AccountApi, useValue: api }] }); });
  async function screen(preference: ApiResult | Error = { status: 200, body: { language: 'en', current_ui_language: 'en', current_email_language: 'en' } }) {
    api.preference = preference;
    const harness = await RouterTestingHarness.create();
    const component = await harness.navigateByUrl('/quality/7/9', ContentLifecycle);
    await harness.fixture.whenStable(); harness.detectChanges(); return { harness, component };
  }
  async function inspectText(harness: RouterTestingHarness, component: ContentLifecycle) {
    const select = harness.routeNativeElement!.querySelector('[name="source"]') as HTMLSelectElement;
    select.value = '44'; select.dispatchEvent(new Event('change')); harness.detectChanges();
    await component.inspectText(); harness.detectChanges();
  }
  function fill(harness: RouterTestingHarness, rights = true) {
    const form = harness.routeNativeElement!.querySelector('form:has([name="quote"])') as HTMLFormElement;
    for (const [key, value] of Object.entries({ reviewed_at: ago(10), judgment: 'thin_coverage', substantive_basis: 'business_expertise_review',
      quote: QUOTE, evidence_note: 'Human review: missing useful first-hand limitations and coverage.', expertise_note: 'Original business operator reports actual reader questions.',
      service_fact_note: '', facts_checked_at: '', proposed_action: 'refresh', rationale: 'Add genuinely useful first-hand detail.',
      destination_url: '', destination_review: '', user_impact: 'Preserve useful history and answer real reader needs.', assignee_id: '2', reason: 'Human exact review.' })) {
      (form.elements.namedItem(key) as HTMLInputElement).value = value;
    }
    for (const key of ['use_permission', 'storage_permission', 'not_restricted_copy', 'no_personal_payload']) {
      (form.elements.namedItem(key) as HTMLInputElement).checked = rights;
    }
    return form;
  }
  async function submit(harness: RouterTestingHarness, form: HTMLFormElement) {
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect((harness.routeDebugElement!.componentInstance as ContentLifecycle).busy()).toBe(false));
    await harness.fixture.whenStable(); harness.detectChanges();
  }
  async function decision(harness: RouterTestingHarness, component: ContentLifecycle, dismiss = false) {
    await component.inspect(ID); harness.detectChanges();
    const forms = harness.routeNativeElement!.querySelectorAll('form:has([name="exact"])');
    const form = forms[dismiss ? 1 : 0] as HTMLFormElement;
    (form.elements.namedItem('reason') as HTMLTextAreaElement).value = 'Reviewed exactly this unchanged proposal.';
    (form.elements.namedItem('exact') as HTMLInputElement).checked = true;
    return form;
  }
  async function chooseOther(harness: RouterTestingHarness, component: ContentLifecycle) {
    const form = harness.routeNativeElement!.querySelector('form:has([name="other_project_id"])') as HTMLFormElement;
    (form.elements.namedItem('other_organization_id') as HTMLInputElement).value = '8';
    (form.elements.namedItem('other_project_id') as HTMLInputElement).value = '10';
    await submit(harness, form);
    const select = harness.routeNativeElement!.querySelector('#quality-other-content') as HTMLSelectElement;
    select.value = '45'; select.dispatchEvent(new Event('change')); harness.detectChanges();
  }
  it('accepts full Unicode lifecycle bodies through exact inspection and both comparison sides without relaxing digests', async () => {
    const { harness, component } = await screen(); const body = '😀'.repeat(30000);
    api.text = { ...api.text, body }; api.evidence = source(api.text);
    api.otherText = { ...api.otherText, body }; api.otherEvidence = source(api.otherText);
    await component.load(); harness.detectChanges(); await inspectText(harness, component);
    expect(component.text()).not.toBeNull(); expect(component.text()!.body).toBe(body); expect(component.error()).toBe('');
    await chooseOther(harness, component); await component.compare(); harness.detectChanges();
    expect(component.comparison()).not.toBeNull(); expect(api.pairReads).toEqual([[7, 9, 44, 8, 10, 45]]);
    expect(harness.routeNativeElement!.textContent).toContain('two selected native bodies are exactly equal');
    api.text = { ...api.text, body: body + '😀' }; api.evidence = source(api.text);
    await component.load(); harness.detectChanges(); await inspectText(harness, component);
    expect(component.text()).toBeNull(); expect(component.error()).toContain('digest or authority changed');
    api.text = { ...api.text, body }; api.evidence = source(api.text);
    await component.load(); harness.detectChanges();
    api.text.body = '😁' + body.slice(2);
    await inspectText(harness, component); expect(component.text()).toBeNull(); expect(component.context()).toBeNull();
    expect(api.commands).toEqual([]); expect(harness.routeNativeElement!.querySelector('img, script, iframe')).toBeNull();
  });

  it.each(['en', 'tr'] as const)('bounds each human lifecycle field in Unicode characters before source preflight and preserves exact maximum notes in %s', async (language) => {
    api.text.body = QUOTE + '😀'.repeat(1001) + 'a'.repeat(1001); api.evidence = source(api.text);
    const { harness, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } });
    for (const [key, limit] of Object.entries({ quote: 1000, evidence_note: 1000, expertise_note: 1000,
      service_fact_note: 1000, rationale: 500, destination_review: 500, user_impact: 500, reason: 500 })) {
      api.rows = []; await component.load(); harness.detectChanges(); await inspectText(harness, component);
      const form = fill(harness), input = form.elements.namedItem(key) as HTMLTextAreaElement;
      expect(input.maxLength).toBe(limit * 2);
      if (key === 'service_fact_note') (form.elements.namedItem('facts_checked_at') as HTMLInputElement).value = ago(20);
      if (key === 'destination_review') {
        (form.elements.namedItem('proposed_action') as HTMLSelectElement).value = 'consolidate';
        (form.elements.namedItem('destination_url') as HTMLInputElement).value = 'https://own.example.invalid/replacement';
      }
      input.value = 'a'.repeat(limit + 1);
      const before = [api.reads, api.detailReads, api.commands.length];
      await submit(harness, form); expect([api.reads, api.detailReads, api.commands.length]).toEqual(before);
      expect(component.pending()).toBeNull(); expect(component.busy()).toBe(false);
      expect(harness.routeNativeElement!.querySelector('[role="alert"]')!.textContent).toBe(component.t(component.error()));
      input.value = '😀'.repeat(limit); await submit(harness, form);
      expect(api.commands.length).toBe(before[2] + 1); expect(component.pending()).toBeNull();
      const command = api.commands.at(-1)!;
      expect(key === 'reason' ? command[key] : (command['intake'] as Record<string, unknown>)[key]).toBe('😀'.repeat(limit));
    }
  });

  it('enforces the original default-spaced 16KiB lifecycle intake boundary before source preflight', async () => {
    api.text.body = '漢'.repeat(1000); api.evidence = source(api.text);
    const { harness, component } = await screen(); await inspectText(harness, component);
    const form = fill(harness);
    const values = { quote: '漢'.repeat(1000), evidence_note: '漢'.repeat(1000), expertise_note: '漢'.repeat(1000),
      service_fact_note: '漢'.repeat(1000), facts_checked_at: ago(20), rationale: '"'.repeat(500), user_impact: '"'.repeat(500),
      proposed_action: 'consolidate', destination_url: 'https://own.example.invalid/' + 'a'.repeat(484),
      destination_review: '漢'.repeat(244) + '"'.repeat(256) };
    for (const [key, value] of Object.entries(values)) (form.elements.namedItem(key) as HTMLInputElement).value = value;
    const expected = { policy: 'content-human-quality-v1', content_revision_id: 44, text_sha256: api.evidence.content.text_sha256,
      reviewed_at: (form.elements.namedItem('reviewed_at') as HTMLInputElement).value, judgment: 'thin_coverage',
      substantive_basis: 'business_expertise_review', ...values, use_permission: true, storage_permission: true,
      not_restricted_copy: true, no_personal_payload: true };
    expect(new TextEncoder().encode(JSON.stringify(expected)).length).toBe(16345);
    expect(values.destination_url.length).toBe(512);
    expect(form.reportValidity()).toBe(true);
    const note = form.elements.namedItem('destination_review') as HTMLTextAreaElement;
    note.value = '漢'.repeat(245) + '"'.repeat(255);
    const before = [api.reads, api.detailReads, api.commands.length];
    await submit(harness, form); expect([api.reads, api.detailReads, api.commands.length]).toEqual(before);
    expect(component.pending()).toBeNull();
    note.value = values.destination_review; await submit(harness, form);
    expect(component.error()).toBe('');
    expect(api.commands.length).toBe(1); expect(component.pending()).toBeNull();
    // Python gives intake16,384 bytes and combined private evidence31,029 bytes for this fixture.
    const intake = api.commands[0]['intake'] as Record<string, unknown>;
    expect(new TextEncoder().encode(JSON.stringify(intake)).length).toBe(16345);
    expect(intake['destination_review']).toBe(values.destination_review);
  });

  it('enforces the exact ASCII-escaped combined lifecycle evidence ceiling before preflight and historical delivery', async () => {
    api.text.body = '😀'.repeat(1000); api.evidence = source(api.text);
    const { harness, component } = await screen(); await inspectText(harness, component);
    const form = fill(harness);
    for (const [key, value] of Object.entries({ quote: '😀'.repeat(1000), expertise_note: '😀'.repeat(1000),
      evidence_note: '😀'.repeat(500) + 'a'.repeat(164) })) (form.elements.namedItem(key) as HTMLTextAreaElement).value = value;
    const before = [api.reads, api.detailReads, api.commands.length];
    await submit(harness, form); expect([api.reads, api.detailReads, api.commands.length]).toEqual(before);
    const note = form.elements.namedItem('evidence_note') as HTMLTextAreaElement;
    // Independently measured Python default JSON source+intake is32,768 bytes; one more ASCII byte is denied.
    note.value = '😀'.repeat(500) + 'a'.repeat(163); await submit(harness, form);
    expect(api.commands.length).toBe(1); expect(component.pending()).toBeNull();
    const stored = structuredClone(api.rows[0]);
    (api.rows[0]['intake'] as Record<string, unknown>)['evidence_note'] = note.value + 'a';
    await component.load(); expect(component.context()).toBeNull();
    await component.inspect(ID); expect(component.selected()).toBeNull();
    api.rows = [stored]; await component.inspect(ID); expect(component.selected()).not.toBeNull();
    (api.rows[0]['intake'] as Record<string, unknown>)['evidence_note'] = '😀'.repeat(500) + 'a'.repeat(150) + '\",:\t';
    await component.inspect(ID); expect(component.selected()).not.toBeNull();
    expect(component.selected()!.intake.evidence_note).toBe('😀'.repeat(500) + 'a'.repeat(150) + '\",:\t');
    expect(api.commands.length).toBe(1);
  });

  it('bounds human lifecycle reasons and handoff notes without trimming evidence or sending invalid text', async () => {
    const { harness, component } = await screen(); await inspectText(harness, component);
    const form = fill(harness), reason = form.elements.namedItem('reason') as HTMLTextAreaElement;
    for (const value of ['\u0085', '\u0000', '\ud800', 'a'.repeat(501)]) {
      reason.value = value; const before = [api.reads, api.detailReads, api.commands.length];
      await submit(harness, form); expect([api.reads, api.detailReads, api.commands.length]).toEqual(before);
    }
    reason.value = '\ufeff'; await submit(harness, form);
    expect(api.commands.length).toBe(1); expect(api.commands[0]['reason']).toBe('\ufeff');
    for (const state of ['review', 'approved', 'reported']) {
      const next = await decision(harness, component), input = next.elements.namedItem('reason') as HTMLTextAreaElement;
      expect(input.maxLength).toBe(1000);
      input.value = '😀'.repeat(500);
      if (state === 'reported') {
        const date = new Date(Date.now() - 60000); date.setSeconds(0, 0);
        (next.elements.namedItem('executed_at') as HTMLInputElement).value = new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
        const note = next.elements.namedItem('execution_note') as HTMLTextAreaElement;
        expect(note.maxLength).toBe(1000);
        for (const value of ['\u0085', '\u0000', '\udc00', 'a'.repeat(501)]) {
          note.value = value; const before = [api.reads, api.detailReads, api.commands.length];
          await submit(harness, next); expect([api.reads, api.detailReads, api.commands.length]).toEqual(before);
        }
        note.value = '😀'.repeat(500);
      } else {
        input.value = 'a'.repeat(501); const before = [api.reads, api.detailReads, api.commands.length];
        await submit(harness, next); expect([api.reads, api.detailReads, api.commands.length]).toEqual(before);
        input.value = '😀'.repeat(500);
      }
      await submit(harness, next); expect(api.commands.at(-1)!['state']).toBe(state); expect(component.pending()).toBeNull();
      expect(api.commands.at(-1)!['reason']).toBe('😀'.repeat(500));
    }
    expect(api.commands.at(-1)!['execution_note']).toBe('😀'.repeat(500));
    expect(harness.routeNativeElement!.querySelector('img, script, iframe')).toBeNull();
  });

  it('rejects malformed human declarations in lifecycle catalogue and exact history while keeping lawful stale judgments readable', async () => {
    const { harness, component } = await screen(); await inspectText(harness, component); await submit(harness, fill(harness));
    const original = structuredClone(api.rows[0]);
    const changes: Record<string, unknown>[] = [
      { judgment: 'verified_live_quality' }, { judgment: ['thin_coverage'] }, { substantive_basis: 'word_count' },
      { quote: '' }, { evidence_note: '\u0085' }, { expertise_note: '' }, { service_fact_note: 'Fact without date' },
      { facts_checked_at: ago(20) }, { proposed_action: 'delete' }, { rationale: '' }, { user_impact: '' },
      { proposed_action: 'unselected' }, { proposed_action: 'retire' }, { destination_review: 'Unexpected replacement claim' },
      { quote: 'a'.repeat(1001) }, { evidence_note: '\u0000' }, { evidence_note: '\ud800' },
      { no_personal_payload: 1 }, { text_sha256: '0'.repeat(64) },
      { expertise_note: '😀'.repeat(1000), evidence_note: '😀'.repeat(1000), service_fact_note: '😀'.repeat(1000),
        facts_checked_at: ago(20), rationale: '😀'.repeat(500), user_impact: '😀'.repeat(500) },
    ];
    for (const delta of changes) {
      api.rows = [{ ...structuredClone(original), intake: { ...(original['intake'] as object), ...delta } }];
      await component.load(); expect(component.context() === null, Object.keys(delta).join(',')).toBe(true);
      await component.inspect(ID); expect(component.selected()).toBeNull(); expect(component.history()).toEqual([]);
    }
    for (const reason of ['', '\u0085', 'a'.repeat(501), '\ud800']) {
      api.rows = [{ ...structuredClone(original), reason }]; await component.load(); expect(component.context()).toBeNull();
    }
    api.rows = [structuredClone(original)]; api.current = false; await component.inspect(ID);
    expect(component.selected()).not.toBeNull(); expect(component.selected()!.effective_approval).toBe(false);
    expect(component.selected()!.intake.quote).toBe(QUOTE);
    api.rows[0]['intake'] = { ...(original['intake'] as object), judgment: 'not_checked', substantive_basis: 'unreviewed',
      quote: '', evidence_note: '', proposed_action: 'unselected', rationale: '', user_impact: '' };
    await component.inspect(ID); expect(component.selected()).not.toBeNull();
    api.rows[0]['state'] = 'review'; await component.inspect(ID); expect(component.selected()).toBeNull();
    expect(api.commands.length).toBe(1);
  });

  it('keeps malformed human lifecycle acknowledgments and request-key readbacks uncertain without replay', async () => {
    const { harness, component } = await screen(); await inspectText(harness, component);
    const original = api.contentLifecycle.bind(api);
    const spy = vi.spyOn(api, 'contentLifecycle').mockImplementation(async (...args) => {
      const response = structuredClone(await original(...args));
      if (args[2]) (response.body['review'] as Record<string, unknown>)['reason'] = '\u0085';
      return response;
    });
    const form = fill(harness);
    (form.elements.namedItem('reason') as HTMLTextAreaElement).value = 'Original human reason.';
    await submit(harness, form); expect(component.pending()).not.toBeNull(); expect(component.context()).toBeNull();
    spy.mockRestore(); const stored = structuredClone(api.rows[0]);
    api.rows[0]['reason'] = '\u0085'; await component.reconcile();
    expect(component.pending()).not.toBeNull(); expect(component.notFound()).toBe(false); expect(api.commands.length).toBe(1);
    api.rows = [stored]; await component.reconcile(); expect(component.pending()).toBeNull(); expect(api.commands.length).toBe(1);
    expect(api.keys).toEqual([api.commands[0]['request_key'], api.commands[0]['request_key']]);
  });

  it('preserves original Unicode replacement declarations through lifecycle catalogue history and acknowledgment', async () => {
    const { harness, component } = await screen(); await inspectText(harness, component); await submit(harness, fill(harness));
    const original = structuredClone(api.rows[0]);
    for (const destination of ['https://own.example.invalid/café', 'https://own.example.invalid/путь', 'https://own.example.invalid/a/../café%2Fraw']) {
      api.rows = [{ ...structuredClone(original), intake: { ...(original['intake'] as object), proposed_action: 'consolidate',
        destination_url: destination, destination_review: 'Independent useful replacement review.' } }];
      await component.load(); expect(component.context() !== null).toBe(true);
      await component.inspect(ID); expect(component.selected() !== null).toBe(true);
      expect(component.selected()!.intake.destination_url).toBe(destination);
    }
    api.rows = []; await component.load(); harness.detectChanges(); await inspectText(harness, component);
    const form = fill(harness), destination = 'https://own.example.invalid/café';
    (form.elements.namedItem('proposed_action') as HTMLSelectElement).value = 'consolidate';
    (form.elements.namedItem('destination_url') as HTMLInputElement).value = destination;
    (form.elements.namedItem('destination_review') as HTMLTextAreaElement).value = 'Independent useful replacement review.';
    await submit(harness, form); expect(component.pending()).toBeNull(); expect(api.commands.length).toBe(2);
    expect((api.commands[1]['intake'] as Record<string, unknown>)['destination_url']).toBe(destination);
  });

  it.each(['en', 'tr'] as const)('requires deliberate current text inspection and independent rights; keeps markup literal and exact approval/handoff/correction separate in %s', async (language) => {
    const { harness, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } }); const storage = vi.spyOn(Storage.prototype, 'setItem');
    expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe(language);
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Özel insan içerik kalitesi incelemesi — OrganicSEOOps' : 'Private human content-quality review — OrganicSEOOps');
    expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe(language === 'tr' ? 'Mevcut içerik için insan kalite ve yaşam döngüsü incelemesi' : 'Existing-content human quality and lifecycle review');
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'iki dilli onay bekleniyor' : 'Missing facts, age, low traffic or word count alone never justify deletion');
    expect(harness.routeNativeElement!.querySelector('ul')!.getAttribute('aria-label')).toBe(component.t('Latest human content-quality reviews'));
    expect(api.detailReads).toBe(0); await submit(harness, fill(harness)); expect(api.commands).toEqual([]);
    await inspectText(harness, component);
    expect(component.text()).not.toBeNull(); expect(harness.routeNativeElement!.textContent).toContain(QUOTE);
    expect(harness.routeNativeElement!.querySelector('img, script, iframe')).toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain(component.t('Truncated excerpt'));
    await submit(harness, fill(harness, false)); expect(api.commands).toEqual([]);
    const draft = fill(harness);
    expect(draft.querySelector('textarea[name="quote"]')!.getAttribute('lang')).toBe('');
    expect(draft.querySelector<HTMLInputElement>('input[name="storage_permission"]')!.required).toBe(true);
    expect(draft.querySelector<HTMLInputElement>('input[name="storage_permission"]')!.parentElement!.textContent).toBe(component.t('I independently have permission to store this evidence under the stated private export/deletion/backup policy.'));
    const snapshot = new FormData(draft), reads = [api.reads, api.detailReads];
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Private human content-quality review — OrganicSEOOps' : 'Özel insan içerik kalitesi incelemesi — OrganicSEOOps');
    expect(harness.routeNativeElement!.querySelector('form:has([name="quote"])')).toBe(draft);
    expect([...new FormData(draft).entries()]).toEqual([...snapshot.entries()]); expect([api.reads, api.detailReads]).toEqual(reads);
    expect(component.text()!.body).toBe(QUOTE); expect(api.commands).toEqual([]);
    component.productLanguage.set(language); harness.detectChanges();
    await submit(harness, draft); expect(component.error()).toBe(''); expect(api.commands[0]['state']).toBe('draft');
    expect(api.commands[0]['assignee_id']).toBe(2); const intake = api.commands[0]['intake'];
    await submit(harness, await decision(harness, component)); expect(api.commands[1]['state']).toBe('review');
    await submit(harness, await decision(harness, component)); expect(api.commands[2]['state']).toBe('approved');
    expect(api.commands[2]['intake']).toEqual(intake); expect(api.commands[2]['executed_at']).toBeNull();
    const report = await decision(harness, component); const date = new Date(Date.now() - 60000);
    date.setSeconds(0, 0); const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    (report.elements.namedItem('executed_at') as HTMLInputElement).value = local;
    (report.elements.namedItem('execution_note') as HTMLTextAreaElement).value = 'Actual separate manual review handoff.';
    const exact = report.querySelector<HTMLInputElement>('input[name="exact"]')!;
    expect(exact.required).toBe(true); expect(exact.checked).toBe(true);
    expect(report.querySelector('button')!.textContent).toContain(component.t('Record actual manual handoff only'));
    const current = component.selected();
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(report.elements.namedItem('exact')).toBe(exact); expect(exact.checked).toBe(true);
    expect((report.elements.namedItem('executed_at') as HTMLInputElement).value).toBe(local);
    expect((report.elements.namedItem('execution_note') as HTMLTextAreaElement).value).toBe('Actual separate manual review handoff.');
    expect(component.selected()).toEqual(current); expect(api.commands).toHaveLength(3);
    component.productLanguage.set(language); harness.detectChanges();
    await submit(harness, report); expect(api.commands[3]['state']).toBe('reported');
    await component.inspect(ID); harness.detectChanges(); expect(harness.routeNativeElement!.textContent).toContain(component.t('. Not site implementation or outcome evidence.'));
    component.edit(component.selected()!); harness.detectChanges(); await inspectText(harness, component);
    const correction = fill(harness); (correction.elements.namedItem('expertise_note') as HTMLTextAreaElement).value = 'Corrected human evidence.';
    await submit(harness, correction); expect(api.commands[4]['state']).toBe('draft');
    expect(api.commands[4]['expected_revision']).toBe(4); expect(api.commands[4]['executed_at']).toBeNull();
    expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
    harness.fixture.destroy(); TestBed.inject(Title).setTitle('Next route — OrganicSEOOps');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); TestBed.tick();
    expect(TestBed.inject(Title).getTitle()).toBe('Next route — OrganicSEOOps');
  });
  it('rejects invented quotes, naive/future/inverted dates and destructive proposals without distinct reviewed replacement/user impact', async () => {
    const { harness, component } = await screen(); await inspectText(harness, component);
    for (const changes of [{ quote: 'Invented claim' }, { reviewed_at: '2026-01-01T12:00:00' }, { reviewed_at: ago(-5) },
      { reviewed_at: ago(200) }, { service_fact_note: 'Human fact evidence.', facts_checked_at: ago(5) },
      { proposed_action: 'retire' }, { proposed_action: 'redirect', destination_url: 'https://own.example.invalid/service', destination_review: 'Reviewed.' },
      { proposed_action: 'consolidate', destination_url: 'https://own.example.invalid/replacement?arbitrary=1', destination_review: 'Reviewed.' },
      { proposed_action: 'retire', destination_url: 'https://own.example.invalid/replacement', destination_review: '' }]) {
      const form = fill(harness);
      for (const [key, value] of Object.entries(changes)) (form.elements.namedItem(key) as HTMLInputElement).value = value;
      await submit(harness, form); expect(api.commands).toEqual([]);
    }
    const form = fill(harness); (form.elements.namedItem('proposed_action') as HTMLSelectElement).value = 'consolidate';
    (form.elements.namedItem('destination_url') as HTMLInputElement).value = 'https://own.example.invalid/replacement';
    (form.elements.namedItem('destination_review') as HTMLTextAreaElement).value = 'Human reviewed genuine replacement coverage.';
    await submit(harness, form); expect((api.commands[0]['intake'] as Record<string, unknown>)['proposed_action']).toBe('consolidate');
  });
  it('supports honest unchecked drafts and dismissal/reopen without transferring approval', async () => {
    const { harness, component } = await screen(); await inspectText(harness, component);
    const form = fill(harness);
    for (const [key, value] of Object.entries({ judgment: 'not_checked', substantive_basis: 'unreviewed', quote: '', evidence_note: '',
      proposed_action: 'unselected', rationale: '', user_impact: '' })) (form.elements.namedItem(key) as HTMLInputElement).value = value;
    await submit(harness, form); await component.inspect(ID); harness.detectChanges();
    const reviewButton = harness.routeNativeElement!.querySelector('form:has([name="exact"]) button') as HTMLButtonElement;
    expect(reviewButton.disabled).toBe(true);
    await submit(harness, await decision(harness, component, true)); expect(api.commands[1]['state']).toBe('dismissed');
    await component.inspect(ID); component.edit(component.selected()!); harness.detectChanges();
    await inspectText(harness, component); await submit(harness, fill(harness));
    expect(api.commands[2]['state']).toBe('draft'); expect(api.commands[2]['expected_revision']).toBe(2);
    expect(api.rows[2]['approved_at']).toBeNull();
  });
  it.each(['en', 'tr'] as const)('reconciles exact lost acknowledgments despite JSONB field ordering without a replay or browser storage in %s', async (language) => {
    const { harness, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } }); await inspectText(harness, component); api.lost = true;
    await submit(harness, fill(harness)); const frozen = structuredClone(component.pending());
    expect(frozen).not.toBeNull(); expect(component.context()).toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain(component.t('Save outcome uncertain. Check the exact request key; no automatic replay.'));
    const reads = [api.reads, api.detailReads];
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(component.pending()).toEqual(frozen); expect(api.commands).toHaveLength(1);
    expect([api.reads, api.detailReads]).toEqual(reads); component.productLanguage.set(language); harness.detectChanges();
    api.rows[0]['intake'] = Object.fromEntries(Object.entries(api.rows[0]['intake'] as object).reverse());
    await component.reconcile(); expect(api.commands.length).toBe(1);
    expect(api.keys).toEqual([api.commands[0]['request_key']]); expect(component.pending()).toBeNull();
    expect(component.message()).toContain('no command replayed'); harness.detectChanges();
    expect(harness.routeNativeElement!.textContent).toContain(component.t(component.message()));
    expect(api.commands[0]['intake']).toEqual(frozen!.data['intake']);
  });
  it('allows only deliberate same-command retry after a fresh exact source/text/assignee/latest/role check', async () => {
    const { harness, component } = await screen(); await inspectText(harness, component); api.drop = true;
    await submit(harness, fill(harness)); const frozen = structuredClone(component.pending());
    await component.reconcile(); expect(component.notFound()).toBe(true); expect(api.commands.length).toBe(1);
    api.assignee = false; await component.retry(); expect(api.commands.length).toBe(1); expect(component.notFound()).toBe(false);
    api.assignee = true; await component.reconcile(); expect(component.notFound()).toBe(true);
    const originalBody = api.text.body; api.text.body = 'Changed after prior reconciliation';
    await component.retry(); expect(api.commands.length).toBe(1); expect(component.notFound()).toBe(false);
    api.text.body = originalBody; await component.reconcile(); api.drop = false; await component.retry();
    expect(api.commands.length).toBe(2); expect(api.commands[1]).toEqual(api.commands[0]);
    expect(api.commands[1]).toEqual(frozen!.data); expect(component.pending()).toBeNull();
  });
  it('rejects mismatched acknowledgment and historical reconciliation; never retries a superseded exact revision', async () => {
    const { harness, component } = await screen(); await inspectText(harness, component);
    const method = api.contentLifecycle.bind(api);
    const spy = vi.spyOn(api, 'contentLifecycle').mockImplementation(async (org, project, data, id, key) => {
      const response = await method(org, project, data, id, key);
      if (data) (response.body['review'] as Record<string, unknown>)['reason'] = 'Different judgment';
      return response;
    });
    await submit(harness, fill(harness)); expect(component.pending()).not.toBeNull();
    api.rows[0]['reason'] = 'Different judgment'; await component.reconcile();
    expect(component.pending()).not.toBeNull(); expect(component.notFound()).toBe(false); expect(api.commands.length).toBe(1);
    api.rows[0]['reason'] = api.commands[0]['reason']; await component.reconcile(); expect(component.pending()).toBeNull(); spy.mockRestore();
    const form = await decision(harness, component); api.drop = true; await submit(harness, form);
    await component.reconcile(); expect(component.notFound()).toBe(true);
    api.rows.push({ ...structuredClone(api.rows[0]), id: 2, revision: 2, request_key: 'another-human-revision' });
    await component.retry(); expect(component.notFound()).toBe(false); expect(api.commands.length).toBe(2);
  });
  it('denies digest/source/date/revision/foreign/role mismatches and revocation during text read before any command', async () => {
    const { harness, component } = await screen();
    const original = structuredClone(api.text), evidence = structuredClone(api.evidence);
    for (const edit of [() => { api.text.body = 'Tampered body'; }, () => { api.text.id = 999; },
      () => { api.text.project_id = 999; }, () => { api.text.created_at = ago(1); }]) {
      api.text = structuredClone(original); await component.load(); harness.detectChanges(); edit();
      await inspectText(harness, component); expect(component.text()).toBeNull(); expect(component.context()).toBeNull();
    }
    api.text = original;
    for (const edit of [() => { api.evidence.content.text_sha256 = 'bad'; },
      () => { api.evidence.sources[0].retrieved_at = ago(1); }, () => { api.evidence.sources[0].url = 'javascript:evil()'; },
      () => { api.evidence.content.archive_effect = 'live_removed'; }]) {
      api.evidence = structuredClone(evidence); edit(); await component.load(); expect(component.context()).toBeNull();
    }
    api.evidence = evidence; api.evidence.action.affected_urls[0] = 'http://own.example.invalid/service';
    await component.load(); harness.detectChanges(); await inspectText(harness, component); expect(component.text()).not.toBeNull();
    api.foreign = true; await component.load(); expect(component.context()).toBeNull();
    api.foreign = false; api.canReview = false; await component.load(); harness.detectChanges();
    expect(harness.routeNativeElement!.querySelector('form')).toBeNull();
    api.canReview = true; await component.load(); harness.detectChanges(); await inspectText(harness, component);
    vi.spyOn(api, 'projectContent').mockImplementation(async (_org, project) => {
      api.canReview = false; return { status: 200, body: { project_id: project, current: api.text, source_state: 'current_review_still_required' } };
    });
    await submit(harness, fill(harness)); expect(api.commands).toEqual([]); expect(component.context()).toBeNull();
    expect(component.error()).toContain('No command sent');
  });
  it.each(['en', 'tr'] as const)('preserves readable stale human history with no effective decision and discards late text after route reuse in %s', async (language) => {
    const { harness, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } }); await inspectText(harness, component); await submit(harness, fill(harness));
    api.current = false; await component.inspect(ID); harness.detectChanges();
    expect(harness.routeNativeElement!.textContent).toContain(component.t('Source/text/reviewer/assignee stale or unavailable. Retained judgment is historical; new approval or handoff is denied.'));
    expect(harness.routeNativeElement!.querySelector('[name="exact"]')).toBeNull();
    expect(component.selected()!.effective_approval).toBe(false);
    const selected = component.selected(), history = component.history(), reads = [api.reads, api.detailReads];
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(component.selected()).toEqual(selected); expect(component.history()).toEqual(history);
    expect([api.reads, api.detailReads]).toEqual(reads); expect(harness.routeNativeElement!.querySelector('[name="exact"]')).toBeNull();
    component.productLanguage.set(language); harness.detectChanges();
    api.current = true; await component.load(); harness.detectChanges(); component.choose(44);
    let resolve!: (value: ApiResult) => void; api.detailPromise = new Promise((done) => resolve = done);
    const pending = component.inspectText(); const old = { status: 200, body: { project_id: 9, current: api.text, source_state: 'current_review_still_required' } };
    api.rows = []; api.detailPromise = null; await harness.navigateByUrl('/quality/7/10', ContentLifecycle);
    resolve(old); await pending; harness.detectChanges();
    expect(component.text()).toBeNull(); expect(component.selected()).toBeNull(); expect(component.pending()).toBeNull();
    expect(component.history()).toEqual([]); expect(harness.routeNativeElement!.textContent).not.toContain(QUOTE);
  });
  it.each(['en', 'tr'] as const)('deliberately compares exact separately authorized project sources and literal native texts with no copy or command in %s', async (language) => {
    const { harness, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } }); await inspectText(harness, component);
    await chooseOther(harness, component); expect(api.pairReads).toEqual([]);
    await component.compare(); harness.detectChanges();
    expect(api.pairReads).toEqual([[7, 9, 44, 8, 10, 45]]); expect(api.commands).toEqual([]);
    expect(component.comparison()).not.toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain(component.t('The two selected native bodies are exactly equal.'));
    expect(harness.routeNativeElement!.textContent).toContain(component.t('Organization') + ' 8 ' + component.t('· project') + ' 10');
    expect(harness.routeNativeElement!.textContent).toContain('Independent other-project title');
    expect(harness.routeNativeElement!.querySelector('img, script, iframe')).toBeNull();
    expect(harness.routeNativeElement!.querySelector('a[href="/app/actions/8/10"]')).not.toBeNull();
    const pair = structuredClone(component.comparison()), reads = [api.reads, api.detailReads, api.pairReads.length];
    expect(harness.routeNativeElement!.querySelector('section[aria-labelledby="quality-comparison-title"] pre')!.getAttribute('lang')).toBe('');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(component.comparison()).toEqual(pair); expect(component.text()!.body).toBe(QUOTE);
    expect([api.reads, api.detailReads, api.pairReads.length]).toEqual(reads); expect(api.commands).toEqual([]);
    component.productLanguage.set(language); harness.detectChanges();
    component.chooseOther(0); expect(component.comparison()).toBeNull();
  });
  it('rejects foreign/malformed pair sources, digests, dates and equal-body claims without saving or replaying', async () => {
    const { harness, component } = await screen();
    const original = api.contentComparison.bind(api);
    for (const mutate of [
      (pair: Record<string, any>) => { pair['right'].organization_id = 999; },
      (pair: Record<string, any>) => { pair['right'].source.content.revision_id = 999; },
      (pair: Record<string, any>) => { pair['right'].source.brief.created_at = ago(1); },
      (pair: Record<string, any>) => { pair['right'].text.body = 'Different undigested native text'; },
      (pair: Record<string, any>) => { pair['same_native_body'] = false; },
    ]) {
      await component.load(); harness.detectChanges(); await inspectText(harness, component); await chooseOther(harness, component);
      const spy = vi.spyOn(api, 'contentComparison').mockImplementation(async (...args) => {
        const response = await original(...args); mutate(response.body['comparison'] as Record<string, any>); return response;
      });
      await component.compare(); expect(component.comparison()).toBeNull(); expect(component.context()).toBeNull();
      expect(component.pending()).toBeNull(); spy.mockRestore();
    }
    expect(api.commands).toEqual([]);
  });
  it('rechecks each current source/role after private pair reads and clears uncertain or late pair evidence', async () => {
    const { harness, component } = await screen(); await inspectText(harness, component); await chooseOther(harness, component);
    api.canOtherReview = false; await component.compare(); expect(api.pairReads).toEqual([]); expect(component.comparison()).toBeNull();
    api.canOtherReview = true; await component.load(); harness.detectChanges(); await inspectText(harness, component); await chooseOther(harness, component);
    const original = api.contentComparison.bind(api);
    const revoke = vi.spyOn(api, 'contentComparison').mockImplementation(async (...args) => {
      const response = await original(...args); api.canReview = false; return response;
    });
    await component.compare(); expect(component.comparison()).toBeNull(); expect(component.context()).toBeNull(); revoke.mockRestore();
    api.canReview = true; await component.load(); harness.detectChanges(); await inspectText(harness, component); await chooseOther(harness, component);
    api.pairPromise = Promise.reject(new Error('Unknown GET result')); await component.compare(); expect(component.comparison()).toBeNull();
    expect(component.pending()).toBeNull(); api.pairPromise = null;
    await component.load(); harness.detectChanges(); await inspectText(harness, component); await chooseOther(harness, component);
    const old = await original(7, 9, 44, 8, 10, 45); let resolve!: (value: ApiResult) => void;
    api.pairPromise = new Promise((done) => resolve = done); const pending = component.compare();
    await vi.waitFor(() => expect(api.pairReads.length).toBe(4));
    await harness.navigateByUrl('/quality/7/10', ContentLifecycle); resolve(old); await pending; harness.detectChanges();
    expect(component.comparison()).toBeNull(); expect(component.other()).toBeNull(); expect(component.text()).toBeNull();
    expect(harness.routeNativeElement!.textContent).not.toContain('two selected native bodies are exactly equal'); expect(api.commands).toEqual([]);
  });

  it('keeps invalid unavailable preferences and fresh production lifecycle English without decisions or pair reads', async () => {
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    try {
      for (const mode of ['invalid', 'incompatible', 'signed-out', 'unavailable', 'production'] as const) {
        TestBed.resetTestingModule(); api = new QualityApi();
        TestBed.configureTestingModule({ providers: [provideRouter([
          { path: 'quality/:organizationId/:projectId', component: ContentLifecycle },
        ]), { provide: AccountApi, useValue: api }] });
        buildEnvironment.production = mode === 'production';
        const preference: ApiResult | Error = mode === 'unavailable' ? new Error('private preference error')
          : mode === 'signed-out' ? { status: 401, body: {} } : { status: 200, body: {
            language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: mode === 'incompatible' ? 'tr' : 'en', current_email_language: 'en' } };
        const { harness, component } = await screen(preference);
        expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe('en');
        expect(TestBed.inject(Title).getTitle()).toBe('Private human content-quality review — OrganicSEOOps');
        expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe('Existing-content human quality and lifecycle review');
        expect(harness.routeNativeElement!.textContent).not.toContain('private preference error');
        expect(harness.routeNativeElement!.textContent).not.toContain('incelenmemiş Türkçe');
        if (mode === 'production') expect(component.productLanguage()).toBe('tr');
        api.foreign = true; await component.load(); harness.detectChanges();
        expect(harness.routeNativeElement!.querySelector('[role="alert"]')!.textContent).toBe('Current content sources, history or project authority unavailable.');
        expect(api.commands).toEqual([]); expect(api.pairReads).toEqual([]); expect(api.detailReads).toBe(0);
        api.foreign = false; harness.fixture.destroy();
      }
    } finally { buildEnvironment.production = production; }
  });
});
