import { Title } from '@angular/platform-browser';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { vi } from 'vitest';
import { AccountApi, ApiResult } from '../account/account-api';
import { AuthorityLinkSources } from './authority-link-sources';
import { environment } from '../../environments/environment';

const SOURCE = 'https://publisher.example.invalid/article';
const TARGET = 'https://own.example.invalid/target';
const DATE = '2026-01-01T12:00:00+03:00';
const LATER = '2026-01-02T10:00:00+03:00';
const ANCHOR = 'Literal <img src=x onerror=evil()> anchor';
const COLLECTION = 'authority-static-link-collect-v1';
const URI_COLLECTION = 'authority-static-uri-collect-v1';
const URI_PARSER = 'authority-static-uri-parse-v1';
const mentionSelection = () => ({ review_id: 31, prospect_id: '00000000-0000-4000-8000-000000000002', project_id: 9,
  revision: 3, state: 'approved', quote: ANCHOR, relevance: 'Human <script>literal</script> relevance', assignee_id: 1,
  source_actor_id: 1, reviewer_id: 1, approved_by_id: 1, requested_source_url: SOURCE, final_source_url: SOURCE,
  research_job_id: 41, source_index: 0, retrieved_at: DATE, body_sha256: 'b'.repeat(64), body_size_bytes: 200, source_current: true,
  mention_basis: 'human_selected_quote_in_normalized_bounded_research_text_not_browser_verification' });
const target = () => ({ method: 'authority-own-target-http-v1', project_id: 9, configuration_revision: 2,
  origin: 'https://own.example.invalid', verification_id: 10, verified_at: DATE, crawl_page_id: 11, crawl_run_id: 12, job_id: 13,
  requested_url: TARGET, final_url: TARGET, observed_at: DATE, completed_at: DATE, content_observed_at: DATE,
  status_code: 404, error_category: '', body_sha256: 'a'.repeat(64), raw_artifact_id: 14, raw_body_readback: 'checked',
  reused_from_id: null, redirect_chain: [], coverage: { page_limit: 2, pages_attempted: 2, pages_observed: 2,
    crawl_status: 'succeeded', whole_site: 'not_established' }, state: 'dated_http_missing_destination_candidate',
  external_source: 'customer_reported_not_independently_verified', unlinked_or_lost_link: 'not_established',
  interpretation: 'separate_dated_own_target_http_not_current_site_or_external_link_verification' });
const binding = () => ({ method: 'authority-static-source-authority-v1', project_id: 9, organization_id: 7,
  link_review_id: 21, link_id: '00000000-0000-4000-8000-000000000001', link_revision: 3, link_state: 'approved',
  actor_id: 1, source_actor_id: 1, reviewer_id: 1, approved_by_id: 1, assignee_id: 1, configuration_revision: 2,
  source_url: SOURCE, source_origin: 'https://publisher.example.invalid', target_url: TARGET, target_evidence: target(),
  rights: { use_permission: true, storage_permission: true, not_restricted_provider_copy: true, no_personal_payload: true } });

class SourceApi {
  preference: ApiResult | Error = { status: 200, body: { language: 'en', current_ui_language: 'en', current_email_language: 'en' } };
  async productLanguage(): Promise<ApiResult> { if (this.preference instanceof Error) throw this.preference; return this.preference; }
  rows: Record<string, unknown>[] = []; commands: Record<string, unknown>[] = []; queries: string[] = [];
  canCollect = true; changed = false; unsafe = false; foreign = false; uncertain = false; drop = false;
  detailPromise: Promise<ApiResult> | null = null;
  pairs: number[][] = []; comparisonPromise: Promise<ApiResult> | null = null; incomparable = false;
  mentionRows: Record<string, unknown>[] = [mentionSelection()]; mentionReads: number[][] = [];
  mentionPromise: Promise<ApiResult> | null = null; mentionListPromise: Promise<ApiResult> | null = null; mentionCount = 0;
  destinationReads: number[] = []; destinationPromise: Promise<ApiResult> | null = null; destinationCount = 1;
  context(org: number, project: number, key?: string): ApiResult {
    const current = { ...binding(), assignee_id: this.changed ? 99 : 1, source_url: this.unsafe ? 'javascript:evil()' : SOURCE };
    const jobs = key ? this.rows.filter((row) => row['idempotency_key'] === key) : this.rows;
    return { status: 200, body: { organization_id: org, project_id: this.foreign ? 999 : project,
      can_collect: this.canCollect, can_cancel: this.canCollect, denial_category: this.canCollect ? '' : 'source_or_actor_unavailable',
      candidates: this.canCollect ? [{ link_review_id: 21, binding: current, requires_separate_collection_permission: true }] : [],
      collection_methods: [COLLECTION, URI_COLLECTION],
      candidates_has_more: false, jobs, has_more: false, lookup: key ? jobs.length ? 'found' : 'not_found' : null } };
  }
  authorityLinkSources(org: number, project: number, data?: Record<string, unknown>, id?: number, key?: string): Promise<ApiResult> {
    if (!data) {
      if (id) return this.detailPromise || Promise.resolve({ status: 200, body: { organization_id: org, project_id: project,
        job: this.rows.find((row) => row['id'] === id) } });
      if (key) this.queries.push(key);
      return Promise.resolve(this.context(org, project, key));
    }
    this.commands.push(structuredClone(data));
    if (this.drop) return Promise.reject(new Error('No acknowledgement; fixture unsaved'));
    const row = id ? this.rows.find((row) => row['id'] === id)! : { id: this.rows.length + 1, project_id: project,
      link_review_id: 21, idempotency_key: data['idempotency_key'], status: 'queued', created_at: DATE, updated_at: DATE,
      selection: { method: data['collection_method'] || COLLECTION,
        parser_method: data['collection_method'] === URI_COLLECTION ? URI_PARSER : 'authority-static-link-parse-v1',
        binding: { ...binding(), source_collection_permission: true } }, source_current: true, cancel_requested: false,
      error_category: '', estimate_units: 1, attempted_units: 0, usage: { state: 'reserved', actual_units: 0 },
      evidence: null, evidence_state: 'not_collected' };
    if (id) { row['cancel_requested'] = true; row['status'] = 'cancelled'; } else this.rows.push(row);
    return this.uncertain ? Promise.reject(new Error('Lost acknowledgement')) : Promise.resolve({ status: 202,
      body: { organization_id: org, project_id: project, job: row } });
  }
  collected() {
    const selection = this.rows[0]['selection'] as Record<string, unknown>;
    const uri = selection['method'] === URI_COLLECTION;
    this.rows[0] = { ...this.rows[0], status: 'succeeded', attempted_units: 1, evidence_state: 'current_private_readback_checked',
      evidence: { source_current: true, job_id: 1, step_id: 11, artifact_id: 21, collection: { method: selection['method'], state: 'collected',
        requested_url: SOURCE, url: SOURCE, observed_at: DATE, robots: 'available', redirects: [], evidence: {
          method: selection['parser_method'], source_url: SOURCE, target_url: TARGET, observed_at: DATE,
          href_semantics: uri ? 'bounded_stdlib_uri_reference_join_against_final_source_no_base_no_browser_repair'
            : 'html_character_references_decoded_exact_absolute_href_no_url_resolution',
          body_sha256: 'b'.repeat(64), body_size_bytes: 200, matching_links: [{ parsed_href: TARGET, anchor_text: ANCHOR,
            anchor_text_truncated: false, rel: 'nofollow sponsored', rel_truncated: false }],
          state: uri ? 'observed_resolved_target_in_static_uri_references' : 'observed_absolute_target_in_parsed_html',
          unlinked_or_lost_link: 'not_established', raw_body_retention: 'not_selected_transient_only',
          coverage: { surface: 'returned_static_html_not_rendered', whole_site: 'not_established', browser_visibility: 'unknown',
            anchors_seen: 1, anchors_inspected: 1, matches_seen: 1, anchor_limit_reached: false, matches_capped: false,
            structure_uncertain: false, base_element_seen: false,
            ...(uri ? { unsupported_references: 0, reference_resolution: 'bounded_no_base_stdlib_uri_references' } : {}) } } } } };
  }
  reference(source: Record<string, unknown>, index = 0) {
    const selection = this.rows[index]?.['selection'] as Record<string, unknown> | undefined;
    if (selection?.['method'] === URI_COLLECTION) {
      source['method'] = URI_COLLECTION; source['parser_method'] = URI_PARSER;
      if (source['state'] === 'observed_absolute_target_in_parsed_html') source['state'] = 'observed_resolved_target_in_static_uri_references';
      Object.assign(source['coverage'] as object, { unsupported_references: 0, reference_resolution: 'bounded_no_base_stdlib_uri_references' });
    }
    return source;
  }
  pair(org = 7, project = 9): ApiResult {
    const observation = (id: number, stamp: string, count: number) => this.reference({ job_id: id, step_id: id + 10, artifact_id: id + 20,
      observed_at: stamp, body_sha256: (id === 1 ? 'b' : 'c').repeat(64), body_size_bytes: 200,
      state: this.incomparable && id === 2 ? 'unavailable_ambiguous_markup' : count ? 'observed_absolute_target_in_parsed_html' : 'not_observed_in_bounded_static_html_not_link_loss',
      matching_target_count: count, coverage: { surface: 'returned_static_html_not_rendered', whole_site: 'not_established',
        browser_visibility: 'unknown', anchors_seen: count, anchors_inspected: count, matches_seen: count,
        anchor_limit_reached: false, matches_capped: false, structure_uncertain: this.incomparable && id === 2, base_element_seen: false } }, id - 1);
    return { status: 200, body: { organization_id: org, project_id: project, comparison: { method: 'authority-static-link-comparison-v1', project_id: project,
      collection_method: (this.rows[0]?.['selection'] as Record<string, unknown> | undefined)?.['method'] || COLLECTION,
      parser_method: (this.rows[0]?.['selection'] as Record<string, unknown> | undefined)?.['parser_method'] || 'authority-static-link-parse-v1',
      requested_source_url: SOURCE, final_source_url: SOURCE, target_url: TARGET, previous: observation(1, DATE, 1), current: observation(2, LATER, 0),
      comparable: !this.incomparable, state: this.incomparable ? 'incomparable_ambiguous_or_truncated_coverage' : 'target_markup_not_observed_again_candidate_not_verified_link_loss',
      body_changed: true, source_current: true, unlinked_or_lost_link: 'not_established', site_approval: 'separate_human_workflow',
      interpretation: 'dated_selected_static_document_candidate_not_browser_or_whole_site_or_verified_link_loss_or_causal_proof' } } };
  }
  authorityLinkComparison(org: number, project: number, previous: number, current: number): Promise<ApiResult> {
    this.pairs.push([previous, current]); return this.comparisonPromise || Promise.resolve(this.pair(org, project));
  }
  mentionResult(org = 7, project = 9): ApiResult {
    const selection = mentionSelection(); const count = this.mentionCount;
    const source = this.reference({ ...(this.pair().body['comparison'] as Record<string, unknown>)['current'] as object,
      job_id: 1, link_review_id: 21, body_sha256: selection.body_sha256, observed_at: LATER, matching_target_count: count,
      method: 'authority-static-link-collect-v1', parser_method: 'authority-static-link-parse-v1',
      state: this.incomparable ? 'unavailable_ambiguous_markup' : count ? 'observed_absolute_target_in_parsed_html' : 'not_observed_in_bounded_static_html_not_link_loss',
      coverage: { surface: 'returned_static_html_not_rendered', whole_site: 'not_established', browser_visibility: 'unknown',
        anchors_seen: count, anchors_inspected: count, matches_seen: count, anchor_limit_reached: false, matches_capped: false,
        structure_uncertain: this.incomparable, base_element_seen: false } });
    return { status: 200, body: { organization_id: org, project_id: project, candidate: { method: 'authority-body-matched-mention-v1',
      project_id: project, source_current: true, selection, requested_source_url: SOURCE, final_source_url: SOURCE, target_url: TARGET,
      prospect: Object.fromEntries(['review_id', 'prospect_id', 'revision', 'state', 'quote', 'relevance', 'assignee_id', 'mention_basis']
        .map((key) => [key, selection[key as keyof typeof selection]])),
      research: { method: 'authority-research-evidence-v1', collection_method: 'research-v1', research_job_id: 41, source_index: 0,
        step_id: 42, artifact_id: 43, retrieved_at: DATE, original_response_sha256: selection.body_sha256, source_size_bytes: 200,
        excerpt_truncated: true, coverage: 'selected_bounded_public_page_text_only' }, static: source,
      body_match: 'same_original_response_sha256_and_size_separate_dated_observations', static_coverage_complete: !this.incomparable,
      state: this.incomparable ? 'incomparable_ambiguous_or_truncated_static_coverage' : count ? 'human_mention_with_observed_exact_target_markup'
        : 'human_mention_target_not_observed_candidate_not_verified_unlinked', unlinked_or_lost_link: 'not_established',
      site_or_outreach_approval: 'separate_human_workflows',
      interpretation: 'human_mention_body_matched_static_target_candidate_not_browser_whole_site_index_or_verified_unlinked_or_lost_proof' } } };
  }
  authorityMentionCandidates(org: number, project: number, review?: number, job?: number): Promise<ApiResult> {
    if (review !== undefined) { this.mentionReads.push([review, job!]); return this.mentionPromise || Promise.resolve(this.mentionResult(org, project)); }
    return this.mentionListPromise || Promise.resolve({ status: this.canCollect ? 200 : 403, body: { organization_id: org, project_id: project,
      candidates: this.mentionRows, has_more: false, basis: 'human_selected_mentions_require_exact_body_matched_static_observation_not_verified_unlinked_proof' } });
  }
  destinationResult(org = 7, project = 9): ApiResult {
    const saved = this.rows[0]['selection'] as Record<string, unknown>;
    const bound = (saved['binding'] as Record<string, unknown>)['target_evidence'] as ReturnType<typeof target>;
    const count = this.destinationCount;
    const source = this.reference({ ...(this.mentionResult().body['candidate'] as Record<string, unknown>)['static'] as Record<string, unknown>,
      matching_target_count: count, redirects: [], state: this.incomparable ? 'unavailable_ambiguous_markup'
        : count ? 'observed_absolute_target_in_parsed_html' : 'not_observed_in_bounded_static_html_not_link_loss',
      coverage: { surface: 'returned_static_html_not_rendered', whole_site: 'not_established', browser_visibility: 'unknown',
        anchors_seen: count, anchors_inspected: count, matches_seen: count, anchor_limit_reached: false, matches_capped: false,
        structure_uncertain: this.incomparable, base_element_seen: false } });
    const candidate = !this.incomparable && count > 0 && [404, 410].includes(bound.status_code) && !bound.error_category;
    return { status: 200, body: { organization_id: org, project_id: project, candidate: { method: 'authority-static-destination-candidate-v1',
      project_id: project, source_current: true, selection: structuredClone(saved), requested_source_url: SOURCE, final_source_url: SOURCE,
      target_url: TARGET, target: structuredClone(bound), static: source, static_coverage_complete: !this.incomparable,
      destination_recovery_candidate: candidate, state: this.incomparable ? 'incomparable_ambiguous_or_truncated_static_coverage'
        : candidate ? 'dated_static_target_and_http_missing_destination_candidate' : !count
        ? 'target_not_observed_in_bounded_static_document_not_missing_or_healthy_proof'
        : 'no_dated_missing_destination_candidate_not_current_healthy_or_recovered_link_proof',
      unlinked_or_lost_link: 'not_established', site_or_outreach_approval: 'separate_human_workflows',
      handoff: 'separate_existing_own_page_action_review_required_no_automatic_action_or_approval',
      interpretation: 'separately_dated_static_target_and_own_http_candidate_not_current_broken_inbound_browser_or_causal_proof' } } };
  }
  authorityDestinationCandidate(org: number, project: number, id: number): Promise<ApiResult> {
    this.destinationReads.push(id); return this.destinationPromise || Promise.resolve(this.destinationResult(org, project));
  }
}

describe('Private selected static-link source journey', () => {
  let api: SourceApi;
  beforeEach(() => { api = new SourceApi(); TestBed.configureTestingModule({ providers: [provideRouter([
    { path: 'sources/:organizationId/:projectId', component: AuthorityLinkSources },
  ]), { provide: AccountApi, useValue: api }] }); });
  async function screen(preference: ApiResult | Error = { status: 200, body: { language: 'en', current_ui_language: 'en', current_email_language: 'en' } }) {
    api.preference = preference;
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/sources/7/9', AuthorityLinkSources);
    await harness.fixture.whenStable(); harness.detectChanges(); return { harness, component };
  }
  async function launch(harness: RouterTestingHarness, permission = true, method = COLLECTION) {
    const form = harness.routeNativeElement!.querySelector('form') as HTMLFormElement;
    const select = form.elements.namedItem('source') as HTMLSelectElement; select.value = '21'; select.dispatchEvent(new Event('change'));
    (form.elements.namedItem('permission') as HTMLInputElement).checked = permission;
    (form.elements.namedItem('method') as HTMLSelectElement).value = method;
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); await harness.fixture.whenStable(); harness.detectChanges();
  }
  async function history(language: 'en' | 'tr' = 'en') {
    // Synthetic saved jobs, not remote collection. History metadata has no detail payload.
    await api.authorityLinkSources(7, 9, { idempotency_key: 'saved-pair-previous' });
    await api.authorityLinkSources(7, 9, { idempotency_key: 'saved-pair-current' });
    api.rows = api.rows.map((row) => ({ ...row, status: 'succeeded', attempted_units: 1 }));
    return screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } });
  }
  function choose(harness: RouterTestingHarness, previous = '1', current = '2') {
    for (const [id, value] of [['static-previous', previous], ['static-current', current]]) {
      const input = harness.routeNativeElement!.querySelector('#' + id) as HTMLSelectElement;
      input.value = value; input.dispatchEvent(new Event('change'));
    }
    harness.detectChanges();
  }
  function chooseMention(harness: RouterTestingHarness) {
    for (const [id, value] of [['static-mention', '31'], ['static-mention-job', '1']]) {
      const input = harness.routeNativeElement!.querySelector('#' + id) as HTMLSelectElement;
      input.value = value; input.dispatchEvent(new Event('change'));
    }
    harness.detectChanges();
  }
  it('rejects array source approval and parsed states and nonboolean private current markers while preserving scalar metadata', async () => {
    // Synthetic saved metadata only; no remote collection.
    await api.authorityLinkSources(7, 9, { idempotency_key: 'saved-scalar-source', link_review_id: 21,
      collection_method: COLLECTION, source_collection_permission: true }); api.collected();
    const original = structuredClone(api.rows[0]), selection = original['selection'] as Record<string, unknown>;
    const savedBinding = selection['binding'] as Record<string, unknown>, evidence = original['evidence'] as Record<string, unknown>;
    const context = structuredClone(api.context(7, 9)), candidate = (context.body['candidates'] as Record<string, unknown>[])[0];
    const { component } = await screen();
    const read = vi.spyOn(api, 'authorityLinkSources');
    const detail = (job: Record<string, unknown>): ApiResult => ({ status: 200, body: { organization_id: 7, project_id: 9, job } });
    for (const marker of [[false], [true], 1, 'true', {}, false, null]) {
      read.mockResolvedValue(detail({ ...original, evidence: { ...evidence, source_current: marker } }));
      await component.inspect(1); expect(component.selected()).toBeNull(); expect(component.context()).toBeNull();
      read.mockResolvedValue(detail(original)); await component.inspect(1);
      expect(component.selected()?.evidence?.source_current).toBe(true);
    }
    for (const state of ['approved', 'reported']) {
      read.mockResolvedValue({ ...context, body: { ...context.body, candidates: [{ ...candidate,
        binding: { ...(candidate['binding'] as object), link_state: [state] } }] } });
      await component.load(); expect(component.context()).toBeNull(); expect(component.mentions()).toEqual([]);
      read.mockResolvedValue(detail({ ...original, selection: { ...selection, binding: { ...savedBinding, link_state: [state] } } }));
      await component.inspect(1); expect(component.selected()).toBeNull();
      const scalar = { ...original, selection: { ...selection, binding: { ...savedBinding, link_state: state } } };
      read.mockResolvedValue({ ...context, body: { ...context.body, candidates: [{ ...candidate,
        binding: { ...(candidate['binding'] as object), link_state: state } }], jobs: [scalar] } });
      await component.load(); expect(component.context()).not.toBeNull();
      read.mockResolvedValue(detail(scalar)); await component.inspect(1);
      expect(component.selected()?.selection.binding['link_state']).toBe(state);
    }
    read.mockResolvedValue(context);
    for (const state of ['approved', 'reported']) {
      api.mentionRows = [{ ...mentionSelection(), state: [state] }]; await component.load();
      expect(component.context()).toBeNull(); expect(component.mentions()).toEqual([]);
      api.mentionRows = [{ ...mentionSelection(), state }]; await component.load();
      expect(component.context()).not.toBeNull(); expect(component.mentions()[0].state).toBe(state);
    }
    const collection = evidence['collection'] as Record<string, unknown>, parsed = collection['evidence'] as Record<string, unknown>;
    for (const state of ['observed_absolute_target_in_parsed_html', 'not_observed_in_bounded_static_html_not_link_loss', 'unavailable_ambiguous_markup']) {
      const observed = state === 'observed_absolute_target_in_parsed_html';
      const scalar = { ...parsed, state, matching_links: observed ? parsed['matching_links'] : [],
        coverage: { ...(parsed['coverage'] as object), matches_seen: observed ? 1 : 0, structure_uncertain: state === 'unavailable_ambiguous_markup' } };
      const job = { ...original, evidence: { ...evidence, collection: { ...collection, evidence: scalar } } };
      read.mockResolvedValue(detail({ ...job, evidence: { ...evidence, collection: { ...collection, evidence: { ...scalar, state: [state] } } } }));
      await component.inspect(1); expect(component.selected()).toBeNull();
      read.mockResolvedValue(detail(job)); await component.inspect(1);
      expect((component.selected()?.evidence?.collection['evidence'] as Record<string, unknown>)?.['state']).toBe(state);
    }
    read.mockRestore(); expect(api.commands).toHaveLength(1); expect(api.mentionReads).toEqual([]); expect(api.destinationReads).toEqual([]);
  });

  it.each(['en', 'tr'] as const)('deliberately selects the URI method, preserves literal target/date/digest and denies mismatched private method/base coverage in %s', async (language) => {
    const { harness, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } });
    expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe(language);
    expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe(language === 'tr' ? 'Seçilen statik bağlantı kaynağının doğrulanması' : 'Selected static-link source verification');
    expect(harness.routeNativeElement!.querySelector('#static-method option')!.textContent).toBe(component.t('Literal absolute href only (original v1)'));
    await launch(harness, true, URI_COLLECTION);
    expect(api.commands[0]['collection_method']).toBe(URI_COLLECTION);
    api.collected(); await component.inspect(1); harness.detectChanges();
    expect(component.selected()?.selection.parser_method).toBe(URI_PARSER);
    for (const text of [URI_PARSER, 'observed_resolved_target_in_static_uri_references', ANCHOR, DATE, 'b'.repeat(64),
      language === 'tr' ? 'Etkin bir base öğesi' : 'Any active base', language === 'tr' ? 'Çözümlenen hiçbir hedef getirilmez' : 'No resolved destination is fetched']) expect(harness.routeNativeElement!.textContent).toContain(text);
    expect(harness.routeNativeElement!.querySelector('img, script, iframe')).toBeNull();
    const source = (api.rows[0]['evidence'] as Record<string, unknown>)['collection'] as Record<string, unknown>;
    const evidence = source['evidence'] as Record<string, unknown>;
    const coverage = evidence['coverage'] as Record<string, unknown>;
    source['method'] = COLLECTION; await component.inspect(1); expect(component.selected()).toBeNull();
    source['method'] = URI_COLLECTION;
    Object.assign(coverage, { base_element_seen: true, structure_uncertain: true, reference_resolution: 'unavailable_base_element' });
    evidence['state'] = 'unavailable_base_dependent_references';
    await component.inspect(1); expect(component.selected()).toBeNull(); // Even a base after a match invalidates positives.
    evidence['matching_links'] = []; await component.inspect(1); harness.detectChanges();
    expect(component.selected()).not.toBeNull(); expect(harness.routeNativeElement!.textContent).toContain('unavailable_base_dependent_references');
    coverage['reference_resolution'] = 'browser_resolved'; await component.inspect(1); expect(component.selected()).toBeNull();
  });
  it('freezes the URI method for uncertain lookup/retry and never accepts a literal-v1 acknowledgement or stale source', async () => {
    const { harness, component } = await screen(); api.uncertain = true;
    await launch(harness, true, URI_COLLECTION);
    const frozen = structuredClone(component.pending()); expect(frozen?.method).toBe(URI_COLLECTION);
    const selection = api.rows[0]['selection'] as Record<string, unknown>;
    selection['method'] = COLLECTION; selection['parser_method'] = 'authority-static-link-parse-v1';
    await component.reconcile(); expect(component.pending()).toEqual(frozen); expect(api.commands.length).toBe(1);
    selection['method'] = URI_COLLECTION; selection['parser_method'] = URI_PARSER;
    await component.reconcile(); expect(component.pending()).toBeNull(); expect(api.commands.length).toBe(1);
    api.uncertain = false; api.rows = []; await component.load(); harness.detectChanges();
    api.drop = true; await launch(harness, true, URI_COLLECTION); await component.reconcile();
    expect(component.notFound()).toBe(true); api.drop = false; await component.retry();
    expect(api.commands[2]).toEqual(api.commands[1]); expect(component.pending()).toBeNull();
    await component.load(); harness.detectChanges(); api.changed = true;
    await launch(harness, true, URI_COLLECTION); expect(api.commands.length).toBe(3); expect(component.error()).toContain('No collection command sent');
  });
  it('reads same-method URI history and dated destination candidates but rejects mixed methods and unsupported comparable coverage', async () => {
    await api.authorityLinkSources(7, 9, { idempotency_key: 'saved-uri-before', collection_method: URI_COLLECTION });
    await api.authorityLinkSources(7, 9, { idempotency_key: 'saved-uri-after', collection_method: URI_COLLECTION });
    api.rows = api.rows.map((row) => ({ ...row, status: 'succeeded', attempted_units: 1 }));
    const { harness, component } = await screen(); api.commands = [];
    choose(harness); await component.compare(new Event('submit'));
    expect(component.comparison()?.parser_method).toBe(URI_PARSER);
    chooseMention(harness); await component.readMention(new Event('submit'));
    expect(component.mention()?.static.parser_method).toBe(URI_PARSER);
    await component.inspectDestination(component.context()!.jobs[0]); expect(component.destination()?.destination_recovery_candidate).toBe(true);
    const response = api.destinationResult(); const item = response.body['candidate'] as Record<string, unknown>;
    const source = item['static'] as Record<string, unknown>;
    (source['coverage'] as Record<string, unknown>)['unsupported_references'] = 1;
    api.destinationPromise = Promise.resolve(response);
    await component.inspectDestination(component.context()!.jobs[0]); expect(component.destination()).toBeNull();
    item['static_coverage_complete'] = false; item['destination_recovery_candidate'] = false;
    item['state'] = 'incomparable_ambiguous_or_truncated_static_coverage';
    await component.load(); await component.inspectDestination(component.context()!.jobs[0]);
    expect(component.destination()?.static_coverage_complete).toBe(false);
    await component.load(); harness.detectChanges(); choose(harness);
    const selection = api.rows[1]['selection'] as Record<string, unknown>;
    selection['method'] = COLLECTION; selection['parser_method'] = 'authority-static-link-parse-v1';
    const before = api.pairs.length; await component.compare(new Event('submit')); expect(api.pairs.length).toBe(before);
    expect(component.comparison()).toBeNull(); expect(api.commands).toEqual([]);
  });
  it.each(['en', 'tr'] as const)('explicitly reads a saved dated static-target/404 candidate, preserves separate evidence and navigates to independent site approval without commands in %s', async (language) => {
    const { harness, component } = await history(language); api.commands = []; expect(api.destinationReads).toEqual([]);
    const button = Array.from(harness.routeNativeElement!.querySelectorAll('button')).find((node) => node.textContent!.includes(component.t('Read saved static-target destination candidate')))!;
    button.click(); await harness.fixture.whenStable(); harness.detectChanges();
    expect(api.destinationReads).toEqual([1]); expect(component.destination()?.destination_recovery_candidate).toBe(true);
    const node = harness.routeNativeElement!;
    for (const text of [DATE, LATER, language === 'tr' ? 'HTTP durumu 404' : 'HTTP status 404', language === 'tr' ? 'Tarihli hedef kurtarma adayı' : 'Dated destination-recovery candidate', language === 'tr' ? 'ayrı özgün 404/410' : 'separate original 404/410',
      language === 'tr' ? 'güncel site durumu değil' : 'not the current site state', language === 'tr' ? 'eylem oluşturmaz' : 'creates no action', 'b'.repeat(64)]) expect(node.textContent).toContain(text);
    const destination = component.destination(); const reads = [...api.destinationReads];
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(component.destination()).toBe(destination); expect(api.destinationReads).toEqual(reads); expect(api.commands).toEqual([]);
    component.productLanguage.set(language); harness.detectChanges();
    expect(node.querySelector('a[href="/app/actions/7/9"]')).not.toBeNull(); expect(node.querySelector('img, script, iframe')).toBeNull();
    api.incomparable = true; await component.inspectDestination(component.context()!.jobs[0]); harness.detectChanges();
    expect(component.destination()?.destination_recovery_candidate).toBe(false); expect(node.textContent).toContain(language === 'tr' ? 'Karşılaştırılamaz belirsiz' : 'Incomparable ambiguous');
    api.incomparable = false; api.destinationCount = 0; await component.inspectDestination(component.context()!.jobs[0]);
    expect(component.destination()?.state).toContain('target_not_observed');
    const bound = ((api.rows[0]['selection'] as Record<string, unknown>)['binding'] as Record<string, unknown>)['target_evidence'] as ReturnType<typeof target>;
    bound.status_code = 200; bound.state = 'dated_http_success_not_usefulness_or_link_recovery_proof'; api.destinationCount = 1;
    await component.load(); await component.inspectDestination(component.context()!.jobs[0]); harness.detectChanges();
    expect(component.destination()?.destination_recovery_candidate).toBe(false); expect(node.textContent).toContain(language === 'tr' ? 'sağlıklı güncel siteyi' : 'does not prove a healthy current site');
    await component.load(); expect(component.destination()).toBeNull(); expect(api.commands).toEqual([]);
  });
  it('clears mismatched destination/source/selection/date/coverage and denies fresh role or binding loss without replay or commands', async () => {
    const { harness, component } = await history(); api.commands = [];
    const bad: ApiResult[] = [{ status: 403, body: {} }, { status: 409, body: {} }];
    for (const change of [{ project_id: 99 }, { source_current: false }, { requested_source_url: SOURCE + '/other' },
      { final_source_url: 'javascript:evil()' }, { target_url: TARGET + '/other' }, { selection: {} }, { destination_recovery_candidate: false },
      { state: 'current_broken_inbound_link' }, { site_or_outreach_approval: 'approved' }]) {
      const result = api.destinationResult(); Object.assign(result.body['candidate'] as object, change); bad.push(result);
    }
    for (const change of [{ job_id: 99 }, { observed_at: '2026-01-01T12:00:00' }, { observed_at: '2025-01-01T00:00:00Z' },
      { method: 'unknown' }, { body_size_bytes: 131073 }, { coverage: {} }, { redirects: [{ url: 'https://foreign.example.invalid/', status: 302 }] }]) {
      const result = api.destinationResult(); Object.assign((result.body['candidate'] as Record<string, unknown>)['static'] as object, change); bad.push(result);
    }
    const targetMismatch = api.destinationResult(); ((targetMismatch.body['candidate'] as Record<string, unknown>)['target'] as Record<string, unknown>)['crawl_page_id'] = 99; bad.push(targetMismatch);
    for (const result of bad) {
      await component.load(); api.destinationPromise = Promise.resolve(result);
      await component.inspectDestination(component.context()!.jobs[0]); harness.detectChanges();
      expect(component.destination()).toBeNull(); expect(component.context()).toBeNull(); expect(component.error()).toContain('unavailable is not zero');
      expect(harness.routeNativeElement!.textContent).not.toContain('Dated destination-recovery candidate:');
    }
    api.destinationReads = []; await component.load(); const frozen = component.context()!.jobs[0];
    api.canCollect = false; await component.inspectDestination(frozen); expect(api.destinationReads).toEqual([]);
    api.canCollect = true; await component.load();
    const pending = component.inspectDestination(component.context()!.jobs[0]);
    ((api.rows[0]['selection'] as Record<string, unknown>)['binding'] as Record<string, unknown>)['assignee_id'] = 99;
    await pending; expect(api.destinationReads).toEqual([]); expect(api.commands).toEqual([]);
  });
  it('discards late destination reads and uncertain GET failures without retaining evidence or replaying a command', async () => {
    const { harness, component } = await history(); api.commands = [];
    api.destinationPromise = Promise.reject(new Error('Private read failed')); await component.inspectDestination(component.context()!.jobs[0]);
    expect(component.destination()).toBeNull(); expect(component.pending()).toBeNull(); expect(api.destinationReads).toEqual([1]);
    await component.load(); let resolve!: (result: ApiResult) => void; api.destinationPromise = new Promise((done) => resolve = done);
    const result = api.destinationResult(); const pending = component.inspectDestination(component.context()!.jobs[0]); await Promise.resolve(); await Promise.resolve();
    await harness.navigateByUrl('/sources/7/10', AuthorityLinkSources); resolve(result); await pending;
    expect(component.destination()).toBeNull(); expect(component.pending()).toBeNull(); expect(api.commands).toEqual([]);
  });
  it.each(['en', 'tr'] as const)('deliberately associates frozen human quote and saved static body with literal separate original dates/methods and no command in %s', async (language) => {
    const { harness, component } = await history(language); api.commands = []; const storage = vi.spyOn(Storage.prototype, 'setItem');
    chooseMention(harness); expect(api.mentionReads).toEqual([]);
    const form = harness.routeNativeElement!.querySelector('#static-mention')!.closest('form')!;
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); await harness.fixture.whenStable(); harness.detectChanges();
    expect(api.mentionReads).toEqual([[31, 1]]); expect(component.mention()?.state).toContain('candidate_not_verified_unlinked');
    const node = harness.routeNativeElement!;
    for (const text of [ANCHOR, mentionSelection().relevance, DATE, LATER, 'research-v1', 'authority-static-link-parse-v1',
      component.t('Truncated excerpt'), language === 'tr' ? 'eşleşen ayrıştırılmış hedef sayısı 0' : 'matching parsed target count 0', 'b'.repeat(64), language === 'tr' ? 'ayrı insan iş akışları' : 'separate human workflows']) expect(node.textContent).toContain(text);
    expect(node.querySelector('blockquote span')!.getAttribute('lang')).toBe('');
    const mention = component.mention(); const reads = structuredClone(api.mentionReads);
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(component.mention()).toBe(mention); expect(component.mentionId()).toBe(31); expect(component.mentionJobId()).toBe(1);
    expect((node.querySelector('#static-mention') as HTMLSelectElement).value).toBe('31'); expect(api.mentionReads).toEqual(reads);
    component.productLanguage.set(language); harness.detectChanges();
    expect(node.querySelector('img, script, iframe')).toBeNull(); expect(api.commands).toEqual([]); expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
    api.mentionCount = 1; await component.readMention(new Event('submit')); expect(component.mention()?.state).toContain('observed_exact_target_markup');
    api.incomparable = true; await component.readMention(new Event('submit')); harness.detectChanges();
    expect(component.mention()?.static_coverage_complete).toBe(false); expect(node.textContent).toContain(language === 'tr' ? 'Karşılaştırılamaz belirsiz veya kesilmiş statik kapsam' : 'Incomparable ambiguous or truncated static coverage');
    await component.load(); expect(component.mention()).toBeNull(); expect(component.mentionId()).toBe(0); expect(api.commands).toEqual([]);
  });
  it('rejects mismatched human selection, source, body, dates, methods, scope and coverage instead of presenting unavailable as zero', async () => {
    const { harness, component } = await history(); api.commands = [];
    const bad: ApiResult[] = [{ status: 403, body: {} }, { status: 409, body: {} }];
    for (const [field, changes] of [
      ['', [{ project_id: 99 }, { source_current: false }, { target_url: TARGET + '/other' }, { final_source_url: SOURCE + '/other' },
        { requested_source_url: SOURCE + '/other' }, { body_match: 'url_only' }, { state: 'verified_unlinked' }, { unlinked_or_lost_link: 'verified' }]],
      ['selection', [{ quote: 'changed' }, { revision: 4 }, { assignee_id: 2 }]],
      ['research', [{ retrieved_at: LATER }, { original_response_sha256: 'c'.repeat(64) }, { source_size_bytes: 201 }, { collection_method: 'unknown' }]],
      ['static', [{ job_id: 2 }, { link_review_id: 99 }, { body_sha256: 'c'.repeat(64) }, { body_size_bytes: 201 },
        { observed_at: '2026-01-01T12:00:00' }, { observed_at: '2025-01-01T12:00:00Z' }, { parser_method: 'unknown' }, { matching_target_count: 21 }]],
    ] as const) for (const change of changes) {
      const response = api.mentionResult(); const item = response.body['candidate'] as Record<string, unknown>;
      Object.assign(field ? item[field] as object : item, change); bad.push(response);
    }
    const coverage = api.mentionResult(); ((coverage.body['candidate'] as Record<string, unknown>)['static'] as Record<string, unknown>)['coverage'] = { surface: 'rendered' }; bad.push(coverage);
    for (const response of bad) {
      await component.load(); harness.detectChanges(); chooseMention(harness);
      api.mentionPromise = Promise.resolve(response); await component.readMention(new Event('submit')); harness.detectChanges();
      expect(component.mention()).toBeNull(); expect(component.context()).toBeNull(); expect(component.error()).toContain('unavailable is not zero');
      expect(harness.routeNativeElement!.querySelector('blockquote')).toBeNull();
    }
    expect(api.commands).toEqual([]);
  });
  it('requires fresh exact mention and static authority, rejects failed list/read without replay, and discards late scope responses', async () => {
    const { harness, component } = await history(); api.commands = [];
    chooseMention(harness); api.canCollect = false; await component.readMention(new Event('submit')); expect(api.mentionReads).toEqual([]);
    api.canCollect = true; await component.load(); harness.detectChanges(); chooseMention(harness);
    // Frozen selection must survive mutable transport objects changing during the refresh.
    const refreshing = component.readMention(new Event('submit')); api.mentionRows[0]['assignee_id'] = 2;
    await refreshing; expect(api.mentionReads).toEqual([]);
    api.mentionRows = [mentionSelection()]; await component.load(); harness.detectChanges(); chooseMention(harness);
    const read = api.authorityLinkSources.bind(api);
    const changed = vi.spyOn(api, 'authorityLinkSources').mockImplementation(async (...args) => {
      const result = await read(...args);
      ((api.rows[0]['selection'] as Record<string, unknown>)['binding'] as Record<string, unknown>)['target_url'] = TARGET + '/changed';
      return result;
    });
    await component.readMention(new Event('submit')); expect(api.mentionReads).toEqual([]); changed.mockRestore();
    ((api.rows[0]['selection'] as Record<string, unknown>)['binding'] as Record<string, unknown>)['target_url'] = TARGET;
    await component.load(); harness.detectChanges(); chooseMention(harness);
    api.mentionPromise = Promise.reject(new Error('Read outcome unknown')); await component.readMention(new Event('submit'));
    expect(component.mention()).toBeNull(); expect(component.pending()).toBeNull(); expect(api.mentionReads.length).toBe(1);
    await component.load(); harness.detectChanges(); chooseMention(harness);
    let resolve!: (response: ApiResult) => void; api.mentionPromise = new Promise((done) => resolve = done);
    const pending = component.readMention(new Event('submit')); await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
    await harness.navigateByUrl('/sources/7/10', AuthorityLinkSources); resolve(api.mentionResult()); await pending;
    expect(component.mention()).toBeNull(); expect(component.mentionId()).toBe(0); expect(component.mentionJobId()).toBe(0); expect(api.commands).toEqual([]);
    api.mentionListPromise = Promise.resolve({ status: 403, body: {} }); await component.load(); expect(component.context()).toBeNull();
  });
  it.each(['en', 'tr'] as const)('deliberately reads a frozen saved pair with original dated counts/digests and candidate-not-loss labels; no collection commands in %s', async (language) => {
    const { harness, component } = await history(language); api.commands = []; expect(api.pairs).toEqual([]);
    choose(harness); expect(api.pairs).toEqual([]);
    const form = harness.routeNativeElement!.querySelector('#static-previous')!.closest('form')!;
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); await harness.fixture.whenStable(); harness.detectChanges();
    expect(api.pairs).toEqual([[1, 2]]); expect(api.commands).toEqual([]); expect(component.comparison()?.comparable).toBe(true);
    const node = harness.routeNativeElement!;
    expect(node.textContent).toContain(DATE); expect(node.textContent).toContain(LATER);
    expect(node.textContent).toContain(language === 'tr' ? 'eşleşen ayrıştırılmış hedef sayısı 0' : 'matching parsed target count 0'); expect(node.textContent).toContain('b'.repeat(64));
    expect(node.textContent).toContain('candidate_not_verified_link_loss'); expect(node.textContent).toContain(language === 'tr' ? 'uygulama onayı ayrı kalır' : 'approval remain separate');
    const pair = component.comparison(); const reads = structuredClone(api.pairs);
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(component.comparison()).toBe(pair); expect(component.previousId()).toBe(1); expect(component.currentId()).toBe(2);
    expect((node.querySelector('#static-previous') as HTMLSelectElement).value).toBe('1');
    expect((node.querySelector('#static-current') as HTMLSelectElement).value).toBe('2');
    expect(api.pairs).toEqual(reads); expect(api.commands).toEqual([]);
    component.productLanguage.set(language); harness.detectChanges();
    api.incomparable = true; await component.compare(new Event('submit')); harness.detectChanges();
    expect(component.comparison()?.comparable).toBe(false); expect(node.textContent).toContain(language === 'tr' ? 'Karşılaştırılamaz belirsiz veya kesilmiş kapsam' : 'Incomparable ambiguous or truncated coverage');
    choose(harness, '2', '2'); await component.compare(new Event('submit')); expect(api.pairs.length).toBe(2);
    expect(component.comparison()).toBeNull(); expect(api.commands).toEqual([]);
  });
  it('rejects mismatched pair/source/target/date/current/bounded summaries and clears prior evidence rather than displaying unavailable as zero', async () => {
    const { harness, component } = await history(); api.commands = [];
    const bad: ApiResult[] = [];
    for (const change of [{ project_id: 10 }, { target_url: TARGET + '/wrong' }, { requested_source_url: SOURCE + '/wrong' },
      { final_source_url: 'javascript:evil()' }, { source_current: false }, { state: 'verified_lost_link' }, { unlinked_or_lost_link: 'verified' }]) {
      const response = api.pair(); Object.assign(response.body['comparison'] as object, change); bad.push(response);
    }
    for (const change of [{ job_id: 999 }, { observed_at: '2026-01-01T12:00:00' }, { observed_at: DATE },
      { body_sha256: 'tampered' }, { matching_target_count: 21 }, { body_size_bytes: 131073 }]) {
      const response = api.pair(); Object.assign((response.body['comparison'] as Record<string, unknown>)['current'] as object, change); bad.push(response);
    }
    bad.push({ status: 403, body: {} }, { status: 409, body: {} });
    for (const response of bad) {
      await component.load(); harness.detectChanges(); choose(harness);
      api.comparisonPromise = Promise.resolve(response); await component.compare(new Event('submit')); harness.detectChanges();
      expect(component.comparison()).toBeNull(); expect(component.context()).toBeNull(); expect(component.error()).toContain('unavailable is not zero');
      expect(harness.routeNativeElement!.textContent).not.toContain('matching parsed target count 0');
    }
    expect(api.commands).toEqual([]);
  });
  it('requires fresh exact current pair selections and role, and discards comparison after late scope or refresh', async () => {
    const { harness, component } = await history(); api.commands = [];
    choose(harness); api.canCollect = false; await component.compare(new Event('submit')); expect(api.pairs).toEqual([]);
    api.canCollect = true; await component.load(); harness.detectChanges(); choose(harness);
    const read = api.authorityLinkSources.bind(api);
    const changed = vi.spyOn(api, 'authorityLinkSources').mockImplementation(async (...args) => {
      const result = await read(...args);
      const jobs = result.body['jobs'] as Record<string, unknown>[];
      if (jobs) ((jobs[0]['selection'] as Record<string, unknown>)['binding'] as Record<string, unknown>)['assignee_id'] = 99;
      return result;
    });
    await component.compare(new Event('submit')); expect(api.pairs).toEqual([]); expect(component.context()).toBeNull(); changed.mockRestore();
    // A different frozen binding is also incomparable before issuing the pair read.
    await component.load(); harness.detectChanges(); choose(harness); await component.compare(new Event('submit')); expect(api.pairs).toEqual([]);
    ((api.rows[0]['selection'] as Record<string, unknown>)['binding'] as Record<string, unknown>)['assignee_id'] = 1;
    await component.load(); harness.detectChanges(); choose(harness);
    let resolve!: (response: ApiResult) => void; api.comparisonPromise = new Promise((done) => resolve = done);
    const pending = component.compare(new Event('submit')); await Promise.resolve(); await Promise.resolve();
    await harness.navigateByUrl('/sources/7/10', AuthorityLinkSources); resolve(api.pair()); await pending;
    expect(component.comparison()).toBeNull(); expect(component.previousId()).toBe(0); expect(component.currentId()).toBe(0);
    expect(api.commands).toEqual([]);
  });
  it.each(['en', 'tr'] as const)('requires separate permission, displays bounded static/privacy/source-vs-site labels and renders exact evidence as inert text in %s', async (language) => {
    const { harness, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } }); const storage = vi.spyOn(Storage.prototype, 'setItem');
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Özel seçili statik bağlantı doğrulaması — OrganicSEOOps' : 'Private selected static-link verification — OrganicSEOOps');
    await launch(harness, false); expect(api.commands).toEqual([]);
    const form = harness.routeNativeElement!.querySelector('form') as HTMLFormElement;
    const select = form.elements.namedItem('source') as HTMLSelectElement;
    const permission = form.elements.namedItem('permission') as HTMLInputElement;
    const method = form.elements.namedItem('method') as HTMLSelectElement;
    select.value = '21'; select.dispatchEvent(new Event('change')); permission.checked = true; method.value = URI_COLLECTION;
    const fields = [...new FormData(form).entries()], chosen = component.chosen();
    expect(select.hasAttribute('lang')).toBe(false); expect(select.selectedOptions[0].getAttribute('lang')).toBe('');
    expect(permission.required).toBe(true); expect(permission.parentElement!.textContent).toContain(component.t("I separately have permission to collect this exact selected source's bounded static HTML and retain minimized matching evidence under the disclosed policy. Human/outreach approval does not grant this permission."));
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Private selected static-link verification — OrganicSEOOps' : 'Özel seçili statik bağlantı doğrulaması — OrganicSEOOps');
    expect(harness.routeNativeElement!.querySelector('form')).toBe(form); expect([...new FormData(form).entries()]).toEqual(fields);
    expect(component.chosen()).toBe(chosen); expect(api.commands).toEqual([]);
    component.productLanguage.set(language); harness.detectChanges();
    await launch(harness); expect(api.commands[0]['source_collection_permission']).toBe(true); expect(api.commands[0]['link_review_id']).toBe(21);
    api.collected(); await component.inspect(1); harness.detectChanges();
    const node = harness.routeNativeElement!;
    expect(node.textContent).toContain(ANCHOR); expect(node.textContent).toContain(DATE); expect(node.textContent).toContain('nofollow sponsored');
    expect(node.textContent).toContain(language === 'tr' ? 'Eksik işaretleme' : 'Missing markup never proves'); expect(node.textContent).toContain(language === 'tr' ? '35 günlük yedek' : '35-day backup');
    expect(node.textContent).toContain(language === 'tr' ? 'iletişimi veya web sitesi değişikliğini onaylamaz' : 'does not approve outreach or a website change'); expect(node.querySelector('img, script, iframe')).toBeNull();
    expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
    harness.fixture.destroy(); TestBed.inject(Title).setTitle('Next route — OrganicSEOOps');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); TestBed.tick();
    expect(TestBed.inject(Title).getTitle()).toBe('Next route — OrganicSEOOps');
  });
  it.each(['en', 'tr'] as const)('reconciles an exact frozen uncertain request despite JSONB key order, without replay in %s', async (language) => {
    const { harness, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } }); api.uncertain = true; await launch(harness);
    expect(component.pending()).not.toBeNull(); const key = api.commands[0]['idempotency_key'];
    const pending = component.pending();
    expect(harness.routeNativeElement!.textContent).toContain(component.t('The exact command outcome is uncertain. Its request key and source/target binding are frozen in component memory. No automatic replay.'));
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(component.pending()).toBe(pending); expect(api.commands).toHaveLength(1); expect(api.queries).toEqual([]);
    component.productLanguage.set(language); harness.detectChanges();
    const selection = api.rows[0]['selection'] as Record<string, unknown>;
    selection['binding'] = Object.fromEntries(Object.entries(selection['binding'] as object).reverse());
    await component.reconcile(); expect(component.pending()).toBeNull(); expect(api.commands.length).toBe(1);
    harness.detectChanges(); expect(harness.routeNativeElement!.textContent).toContain(component.t(component.message()));
    expect(api.queries).toEqual([key]); expect(component.message()).toContain('no command replayed');
  });
  it('only deliberately retries an unsaved frozen request after fresh exact source/target/assignee/role checks', async () => {
    const { harness, component } = await screen(); api.drop = true; await launch(harness); const frozen = structuredClone(component.pending());
    await component.reconcile(); expect(component.notFound()).toBe(true);
    api.changed = true; await component.retry(); expect(api.commands.length).toBe(1); expect(component.notFound()).toBe(false);
    api.changed = false; api.canCollect = false; await component.reconcile(); expect(component.notFound()).toBe(false);
    api.canCollect = true; await component.reconcile(); expect(component.notFound()).toBe(true); expect(component.pending()).toEqual(frozen);
    api.drop = false; await component.retry(); expect(api.commands.length).toBe(2); expect(api.commands[1]).toEqual(api.commands[0]);
    expect(component.pending()).toBeNull();
  });
  it('reconciles cancellation from status without replay and clears evidence on unsafe/foreign/late scope', async () => {
    const { harness, component } = await screen(); await launch(harness); api.uncertain = true;
    component.cancel(component.context()!.jobs[0]); await harness.fixture.whenStable(); expect(component.pending()?.jobId).toBe(1);
    await component.reconcile(); expect(component.pending()).toBeNull(); expect(api.commands.length).toBe(2);
    api.unsafe = true; await component.load(); expect(component.context()).toBeNull(); api.unsafe = false;
    api.foreign = true; await component.load(); expect(component.context()).toBeNull(); api.foreign = false; await component.load();
    api.collected(); let resolve!: (response: ApiResult) => void;
    api.detailPromise = new Promise((done) => resolve = done); const pending = component.inspect(1);
    const old: ApiResult = { status: 200, body: { organization_id: 7, project_id: 9, job: api.rows[0] } }; api.rows = [];
    await harness.navigateByUrl('/sources/7/10', AuthorityLinkSources); resolve(old); await pending;
    expect(component.selected()).toBeNull(); expect(component.pending()).toBeNull(); harness.detectChanges();
    expect(harness.routeNativeElement!.textContent).not.toContain(ANCHOR);
  });

  it('keeps invalid unavailable preferences and fresh production static-source interfaces English without commands', async () => {
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    try {
      for (const mode of ['invalid', 'incompatible', 'signed-out', 'unavailable', 'production'] as const) {
        TestBed.resetTestingModule(); api = new SourceApi();
        TestBed.configureTestingModule({ providers: [provideRouter([
          { path: 'sources/:organizationId/:projectId', component: AuthorityLinkSources },
        ]), { provide: AccountApi, useValue: api }] });
        buildEnvironment.production = mode === 'production';
        const preference: ApiResult | Error = mode === 'unavailable' ? new Error('private preference error')
          : mode === 'signed-out' ? { status: 401, body: {} } : { status: 200, body: {
            language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: mode === 'incompatible' ? 'tr' : 'en', current_email_language: 'en' } };
        const { harness, component } = await screen(preference);
        expect(TestBed.inject(Title).getTitle()).toBe('Private selected static-link verification — OrganicSEOOps');
        expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe('Selected static-link source verification');
        expect(harness.routeNativeElement!.textContent).not.toContain('private preference error');
        expect(harness.routeNativeElement!.textContent).not.toContain('incelenmemiş Türkçe');
        if (mode === 'production') expect(component.productLanguage()).toBe('tr');
        api.foreign = true; await component.load(); harness.detectChanges();
        expect(harness.routeNativeElement!.querySelector('[role="alert"]')!.textContent).toBe('Private source history or current authority is unavailable.');
        expect(api.commands).toEqual([]); expect(api.queries).toEqual([]); harness.fixture.destroy();
      }
    } finally { buildEnvironment.production = production; }
  });
});
