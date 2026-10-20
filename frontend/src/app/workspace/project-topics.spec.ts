import { Title } from '@angular/platform-browser';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { vi } from 'vitest';
import { AccountApi, ApiResult } from '../account/account-api';
import { ProjectTopics } from './project-topics';
import { environment } from '../../environments/environment';

class TopicApi {
  preference: ApiResult | Error = { status: 200, body: { language: 'en', current_ui_language: 'en', current_email_language: 'en' } };
  async productLanguage(): Promise<ApiResult> { if (this.preference instanceof Error) throw this.preference; return this.preference; }
  role: unknown = 'owner';
  pending: Promise<ApiResult> | null = null;
  detail: Record<string, unknown> = { id: 81, project_id: 9, status: 'running', cancel_requested: false,
    error_category: '', snapshot_id: null, estimated_units: 1, attempted_units: 0,
    steps: [{ name: 'Collect configured feed', status: 'running', error_category: '' }] };
  jobPending: Promise<ApiResult> | null = null;
  acknowledgment: ApiResult = { status: 202, body: { project_id: 9, job_id: 81, status: 'queued', estimated_units: 1 } };
  projectOnboarding(org: number, project: number): Promise<ApiResult> {
    return Promise.resolve({ status: 200, body: { project: { id: project, organization_id: org,
      name: 'Synthetic topic project', role: this.role } } });
  }
  projectTopics(_org: number, project: number): Promise<ApiResult> {
    return this.pending || Promise.resolve({ status: 200, body: { project_id: project,
      feeds: ['https://source.example.invalid/rss'], languages: ['en'], connections: [], imports: [],
      snapshots: [{ id: 80, created_at: '2026-10-01T00:00:00Z', candidate_count: 1 }],
      jobs: [{ id: 81, status: 'queued' }], has_more: false,
      news: { provider: 'gdelt', phrases: ['service news'], publisher_origins: ['https://source.example.invalid'] } } });
  }
  intentClusters(_org: number, project: number): Promise<ApiResult> {
    return Promise.resolve({ status: 200, body: { project_id: project, clusters: [] } });
  }
  discoverProjectTopics(): Promise<ApiResult> { return Promise.resolve(this.acknowledgment); }
  saveProjectTopic(): Promise<ApiResult> { return Promise.resolve({ status: 403, body: {} }); }
  projectTopicJob(): Promise<ApiResult> { return this.jobPending || Promise.resolve({ status: 200,
    body: { project_id: 9, job: this.detail } }); }
}

describe('Current project topic controls', () => {
  let api: TopicApi;
  beforeEach(() => {
    api = new TopicApi();
    TestBed.configureTestingModule({ providers: [provideRouter([
      { path: 'topics/:organizationId/:projectId', component: ProjectTopics },
    ]), { provide: AccountApi, useValue: api }] });
  });
  async function screen(preference: ApiResult | Error = { status: 200, body: { language: 'en', current_ui_language: 'en', current_email_language: 'en' } }) {
    api.preference = preference;
    const harness = await RouterTestingHarness.create();
    const component = await harness.navigateByUrl('/topics/7/9', ProjectTopics);
    await vi.waitFor(() => expect(component.loading()).toBe(false)); await harness.fixture.whenStable(); harness.detectChanges();
    return { harness, component };
  }
  function command(form: HTMLFormElement) { return { preventDefault() {}, target: form } as unknown as Event; }

  const evidence = { kind: 'public_feed_item', title: 'Synthetic source topic', url: 'https://source.example.invalid/story',
    source_feeds: ['https://source.example.invalid/rss'], published_at: null, freshness: 'unknown',
    trend_state: 'not_measured', evergreen_state: 'unknown', business_relevance: 'not_evaluated' };
  function review() {
    const judgments = { relevance: { score: 0, note: 'Human assessment' }, business_value: { score: 3, note: 'Human assessment' },
      geographic_language_fit: { score: null, note: '' }, existing_coverage: { score: null, note: '' } };
    return { id: 90, project_id: 9, snapshot_id: 80, candidate_index: 0, revision: 1, label: 'Human topic',
      classification: 'evergreen', language: 'en', market: 'Türkiye', intent_review_id: null,
      created_at: '2026-10-01T00:00:00Z', reason: 'Human judgment only', judgments,
      report: { method: 'topic-review-v1', snapshot_id: 80, candidate_index: 0,
        components: [...Object.entries(judgments).map(([name, part]) => ({ name, ...part, maximum: 3, basis: 'human_judgment_not_measured' })),
          { name: 'growth', score: null, maximum: 1, basis: 'unavailable_feed_is_not_trend_measurement', click_change: null, impression_change: null },
          { name: 'freshness', score: null, maximum: 1, basis: 'feed_reported_date_at_collection_not_verified_publication_or_current_freshness', published_at: null },
          { name: 'evidence', score: 1, maximum: 3, basis: 'bounded_source_observation_count_not_authority_confidence_or_demand' },
          { name: 'competition', score: null, maximum: 3, basis: 'unavailable_no_connected_competition_provider' }],
        assessed_points: 4, available_points: 9, unknown_components: ['geographic_language_fit', 'existing_coverage', 'growth', 'freshness', 'competition'],
        demand_volume: 'unavailable_not_zero', as_of_collection: '2026-10-01T00:00:00Z', existing_mapping: null,
        limitations: 'incomplete_components_not_a_comparable_SEO_score_or_automatic_creation_publication_instruction' } };
  }
  function collection(row: unknown = null, source: unknown = evidence) { return { status: 200, body: { project_id: 9, snapshot_id: 80,
    coverage: { truncated: false }, candidates: [{ index: 0, evidence: source, review: row }] } }; }
  function candidate(history: unknown[], sourceCurrent: unknown = true, source: unknown = evidence) { return { status: 200, body: {
    project_id: 9, snapshot_id: 80, candidate_index: 0, evidence: source, history, source_current: sourceCurrent } }; }

  it('uses Python character limits for human topic review text in summary history and save replies', async () => {
    const { harness, component } = await screen();
    const read = vi.spyOn(api, 'projectTopics'); const save = vi.spyOn(api, 'saveProjectTopic');
    for (const [field, limit] of [['label', 240], ['reason', 500], ['note', 240]] as const) {
      for (const extra of [0, 1]) {
        const text = 'x'.repeat(limit - 1) + '😀' + 'x'.repeat(extra); const row = review();
        if (field === 'note') {
          row.judgments.relevance.note = text;
          row.report.components[0] = { ...row.report.components[0], note: text };
        } else row[field] = text;
        read.mockResolvedValue(collection(row)); await component.openSnapshot(80);
        expect(component.candidates().length, field + extra).toBe(extra ? 0 : 1);
        read.mockResolvedValue(collection()); await component.openSnapshot(80);
        read.mockResolvedValue(candidate([row])); await component.openCandidate(0);
        expect(component.currentReview(), field + extra).toEqual(extra ? null : row);
        read.mockResolvedValue(candidate([])); await component.openCandidate(0); harness.detectChanges();
        const form = harness.routeNativeElement!.querySelector<HTMLFormElement>('#topic-label')!.closest('form')!;
        form.querySelector<HTMLInputElement>('#topic-label')!.value = 'Human topic';
        form.querySelector<HTMLSelectElement>('#topic-language')!.value = 'en';
        form.querySelector<HTMLTextAreaElement>('#topic-reason')!.value = 'Human assessment';
        save.mockResolvedValue({ status: 201, body: { project_id: 9, review: row } });
        const calls = save.mock.calls.length; await component.save(command(form));
        expect(save).toHaveBeenCalledTimes(calls + 1);
        expect(component.currentReview(), field + extra).toEqual(extra ? null : row);
        expect(component.sourceCurrent()).toBe(!extra);
      }
    }
  });

  it('uses Python character limits for original topic candidate titles queries and raw URLs', async () => {
    const { harness, component } = await screen(); const read = vi.spyOn(api, 'projectTopics');
    const origin = 'https://source.example.invalid/';
    for (const [field, limit] of [['title', 240], ['query', 1000], ['url', 2048], ['feed', 512], ['news', 240]] as const) {
      for (const extra of [0, 1]) {
        const prefix = field === 'url' || field === 'feed' ? origin : '';
        const text = prefix + 'x'.repeat(limit - prefix.length - 1) + '😀' + 'x'.repeat(extra);
        const source = field === 'query' ? { ...queryEvidence, query: text }
          : field === 'url' ? { ...evidence, url: text }
          : field === 'feed' ? { ...evidence, source_feeds: [text] }
          : field === 'news' ? { ...newsEvidence, title: text } : { ...evidence, title: text };
        read.mockResolvedValue(collection(null, source)); await component.openSnapshot(80);
        expect(component.candidates().length, field + extra).toBe(extra ? 0 : 1);
        read.mockResolvedValue(collection()); await component.openSnapshot(80);
        read.mockResolvedValue(candidate([], true, source)); await component.openCandidate(0); harness.detectChanges();
        expect(component.candidate()?.evidence || null, field + extra).toEqual(extra ? null : source);
        expect(component.sourceCurrent()).toBe(!extra);
      }
    }
  });

  it('allows full Unicode human input and rejects code-point overflow before saving', async () => {
    const { harness, component } = await screen(); const read = vi.spyOn(api, 'projectTopics');
    const save = vi.spyOn(api, 'saveProjectTopic');
    read.mockResolvedValue(collection()); await component.openSnapshot(80);
    read.mockResolvedValue(candidate([])); await component.openCandidate(0); harness.detectChanges();
    const form = harness.routeNativeElement!.querySelector<HTMLFormElement>('#topic-label')!.closest('form')!;
    const label = form.querySelector<HTMLInputElement>('#topic-label')!;
    const reason = form.querySelector<HTMLTextAreaElement>('#topic-reason')!;
    const note = form.querySelector<HTMLTextAreaElement>('#topic-note-relevance')!;
    form.querySelector<HTMLSelectElement>('#topic-language')!.value = 'en';
    form.querySelector<HTMLSelectElement>('#topic-score-relevance')!.value = '0';
    form.querySelector<HTMLSelectElement>('#topic-score-business_value')!.value = '3';
    form.querySelector<HTMLTextAreaElement>('#topic-note-business_value')!.value = 'Human assessment';
    label.value = '😀'.repeat(240); reason.value = '😀'.repeat(500); note.value = '😀'.repeat(240);
    expect(label.maxLength).toBeGreaterThanOrEqual(label.value.length);
    expect(reason.maxLength).toBeGreaterThanOrEqual(reason.value.length);
    expect(note.maxLength).toBeGreaterThanOrEqual(note.value.length);
    const row = review(); row.label = label.value; row.reason = reason.value;
    row.judgments.relevance.note = note.value; row.report.components[0] = { ...row.report.components[0], note: note.value };
    save.mockResolvedValue({ status: 201, body: { project_id: 9, review: row } });
    await component.save(command(form)); expect(save).toHaveBeenCalledTimes(1);
    expect(save.mock.calls[0].slice(-1)[0]).toMatchObject({ label: row.label, reason: row.reason,
      judgments: { relevance: { note: note.value } } });
    for (const control of [label, reason, ...Array.from(form.querySelectorAll<HTMLTextAreaElement>('[name$="_note"]'))]) {
      const original = control.value; control.value = 'x'.repeat(control === reason ? 501 : 241);
      await component.save(command(form)); expect(save).toHaveBeenCalledTimes(1);
      expect(component.saveError()).toContain('characters'); control.value = original;
    }
  });

  it('preserves Unicode configured market labels within the original review model bound', async () => {
    const { component } = await screen(); const read = vi.spyOn(api, 'projectTopics');
    const row = { ...review(), market: '😀'.repeat(80) };
    read.mockResolvedValue(collection(row)); await component.openSnapshot(80);
    expect(component.candidates()[0]?.review).toEqual(row);
    read.mockResolvedValue(collection({ ...row, market: '😀'.repeat(121) })); await component.openSnapshot(80);
    expect(component.candidates()).toEqual([]);
  });

  it('rejects malformed scoped human reviews in collection summaries and preserves all three scalar classifications', async () => {
    const { component } = await screen(); const read = vi.spyOn(api, 'projectTopics'); const valid = review();
    for (const change of [{ classification: ['evergreen'] }, { classification: 'inferred' }, { id: 0 }, { revision: 0 },
      { project_id: 10 }, { snapshot_id: 81 }, { candidate_index: 1 }, { label: [] }, { language: ['en'] },
      { market: {} }, { reason: [] }, { created_at: null }, { intent_review_id: 0 }, { judgments: null },
      { judgments: { ...valid.judgments, relevance: { score: [0], note: 'Human assessment' } } },
      { judgments: { ...valid.judgments, relevance: { score: 4, note: 'Human assessment' } } },
      { judgments: { ...valid.judgments, relevance: { score: 0, note: '' } } },
      { judgments: { ...valid.judgments, relevance: { score: null, note: [] } } },
      { report: null }, { report: { ...valid.report, snapshot_id: 81 } },
      { report: { ...valid.report, candidate_index: 1 } }, { report: { ...valid.report, method: ['topic-review-v1'] } },
      { report: { ...valid.report, components: [null] } },
      { report: { ...valid.report, components: valid.report.components.map((part) => ({ ...part, score: [part.score] })) } },
      { report: { ...valid.report, existing_mapping: {} } },
      { intent_review_id: 70, report: { ...valid.report, existing_mapping: { id: 70, revision: 32768, page_kind: 'existing_unverified',
        preferred_page: 'https://source.example.invalid/guide', action: 'refresh', evidence: 'human_selected_not_verified_page_coverage' } } },
      { judgments: { ...valid.judgments, existing_coverage: { score: 0, note: 'Human coverage' } },
        report: { ...valid.report, components: valid.report.components.map((part) => part.name === 'existing_coverage'
          ? { ...part, score: 0, note: 'Human coverage' } : part) } },
      ...['growth', 'freshness', 'evidence', 'competition'].map((name) => ({ report: { ...valid.report,
        components: valid.report.components.map((part) => part.name === name ? { ...part, basis: 'fabricated_measured_provenance' } : part) } })),
      { report: { ...valid.report, components: valid.report.components.map((part) => part.name === 'growth'
        ? { ...part, score: 0, basis: 'one_point_for_observed_comparable_first_party_growth_not_strength' } : part) } },
      { report: { ...valid.report, components: valid.report.components.map((part) => part.name === 'evidence' ? { ...part, score: null } : part) } }]) {
      read.mockResolvedValue(collection({ ...valid, ...change })); await component.openSnapshot(80);
      expect(component.snapshotId(), JSON.stringify(change)).toBe(0); expect(component.candidates()).toEqual([]);
      expect(component.currentReview()).toBeNull(); expect(component.sourceCurrent()).toBe(false);
    }
    for (const classification of ['unknown', 'trending', 'evergreen']) {
      const row = { ...valid, classification }; read.mockResolvedValue(collection(row)); await component.openSnapshot(80);
      component.filter.set(classification); expect(component.filtered()[0].review).toEqual(row);
    }
    for (const [name, score, basis] of [
      ['growth', 1, 'one_point_for_observed_comparable_first_party_growth_not_strength'],
      ['freshness', 1, 'provider_reported_date_not_verified_publication_or_current_freshness'],
      ['freshness', 0, 'feed_reported_date_at_collection_not_verified_publication_or_current_freshness'],
    ] as const) {
      const row = { ...valid, report: { ...valid.report, components: valid.report.components.map((part) => part.name === name ? { ...part, score, basis } : part) } };
      read.mockResolvedValue(collection(row)); await component.openSnapshot(80); expect(component.candidates()[0].review).toEqual(row);
    }
    read.mockResolvedValue(collection()); await component.openSnapshot(80);
    component.filter.set('unknown'); expect(component.filtered()[0].review).toBeNull();
  });

  it('rejects malformed candidate history as a whole without promoting an older review or research link', async () => {
    const { harness, component } = await screen(); const read = vi.spyOn(api, 'projectTopics'); const valid = review();
    read.mockResolvedValue(collection()); await component.openSnapshot(80);
    read.mockResolvedValue(candidate([valid])); await component.openCandidate(0); harness.detectChanges();
    expect(component.currentReview()).toEqual(valid); expect(harness.routeNativeElement!.querySelector('a[href*="topic_review"]')).not.toBeNull();
    for (const history of [[null, valid], [{ ...valid, project_id: 10 }, valid], [{ ...valid, classification: ['evergreen'] }, valid],
      [{ ...valid, report: { ...valid.report, components: valid.report.components.map((part) => ({ ...part, basis: [] })) } }, valid],
      [valid, valid], [valid, { ...valid, id: 91, revision: 2 }]]) {
      read.mockResolvedValue(candidate(history)); await component.openCandidate(0); harness.detectChanges();
      expect(component.history(), JSON.stringify(history)).toEqual([]); expect(component.candidate()).toBeNull();
      expect(component.sourceCurrent()).toBe(false); expect(harness.routeNativeElement!.querySelector('a[href*="topic_review"]')).toBeNull();
    }
    read.mockResolvedValue(candidate([valid], [true])); await component.openCandidate(0);
    expect(component.sourceCurrent()).toBe(false);
    read.mockResolvedValue(candidate([])); await component.openCandidate(0);
    expect(component.candidate()?.index).toBe(0); expect(component.currentReview()).toBeNull();
  });

  it.each(['en', 'tr'] as const)('does not accept malformed save reviews or replay writes and preserves known zero, unknown and mapped human coverage in %s', async (language) => {
    const { harness, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } }); expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Kaynakları dikkate alan konu incelemesi — OrganicSEOOps' : 'Source-aware topic review — OrganicSEOOps');
    const read = vi.spyOn(api, 'projectTopics'); const valid = review();
    read.mockResolvedValue(collection()); await component.openSnapshot(80);
    read.mockResolvedValue(candidate([])); await component.openCandidate(0); harness.detectChanges();
    const form = harness.routeNativeElement!.querySelector<HTMLFormElement>('#topic-label')!.closest('form')!;
    form.querySelector<HTMLSelectElement>('#topic-language')!.value = 'en';
    form.querySelector<HTMLTextAreaElement>('#topic-reason')!.value = 'Human judgment only';
    const save = vi.spyOn(api, 'saveProjectTopic');
    expect(form.querySelector('#topic-label')!.getAttribute('lang')).toBe('');
    expect(form.querySelector('#topic-class option[value="evergreen"]')!.textContent).toBe(component.t('evergreen'));
    expect(harness.routeNativeElement!.querySelector('label[for="topic-score-relevance"]')!.textContent).toContain(component.t('relevance'));
    const fields = [...new FormData(form).entries()], selected = component.candidate();
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Source-aware topic review — OrganicSEOOps' : 'Kaynakları dikkate alan konu incelemesi — OrganicSEOOps');
    expect(harness.routeNativeElement!.querySelector('#topic-label')!.closest('form')).toBe(form);
    expect([...new FormData(form).entries()]).toEqual(fields); expect(component.candidate()).toBe(selected);
    expect(save).not.toHaveBeenCalled(); component.productLanguage.set(language); harness.detectChanges();
    for (const change of [{ classification: ['evergreen'] }, { report: null }, { judgments: {} }, { revision: 2 }, { snapshot_id: 81 }]) {
      save.mockResolvedValue({ status: 201, body: { project_id: 9, review: { ...valid, ...change } } });
      const count = save.mock.calls.length; await component.save(command(form)); harness.detectChanges();
      expect(component.currentReview(), JSON.stringify(change)).toBeNull(); expect(component.candidates()[0].review).toBeNull();
      expect(component.sourceCurrent()).toBe(false); expect(component.saveError()).toContain('Input retained');
      expect(harness.routeNativeElement!.querySelector('#topic-save-error')!.textContent).toBe(component.t(component.saveError()));
      component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
      expect([...new FormData(form).entries()]).toEqual(fields); expect(component.saveError()).toContain('Input retained');
      expect(save).toHaveBeenCalledTimes(count + 1); component.productLanguage.set(language); harness.detectChanges();
      expect(save).toHaveBeenCalledTimes(count + 1); expect(harness.routeNativeElement!.querySelector('a[href*="topic_review"]')).toBeNull();
    }
    save.mockResolvedValue({ status: 201, body: { project_id: 9, review: valid } }); await component.save(command(form)); harness.detectChanges();
    expect(component.currentReview()?.judgments['relevance'].score).toBe(0);
    expect(component.currentReview()?.judgments['existing_coverage'].score).toBeNull(); expect(component.sourceCurrent()).toBe(true);
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Rekabet ve talep hacmi kullanılamıyor' : 'Competition and demand volume unavailable');
    const mapped = { ...valid, id: 91, revision: 2, intent_review_id: 70,
      judgments: { ...valid.judgments, existing_coverage: { score: 0, note: 'Human selected mapping' } },
      report: { ...valid.report, components: valid.report.components.map((part) => part.name === 'existing_coverage'
        ? { ...part, score: 0, note: 'Human selected mapping' } : part), existing_mapping: { id: 70, revision: 32767, page_kind: 'existing_unverified',
        preferred_page: 'https://source.example.invalid/guide', action: 'refresh', evidence: 'human_selected_not_verified_page_coverage' } } };
    save.mockResolvedValue({ status: 201, body: { project_id: 9, review: mapped } }); await component.save(command(form));
    expect(component.currentReview()).toEqual(mapped); expect(component.history()).toHaveLength(2); harness.detectChanges();
    const history = component.history(); const calls = save.mock.calls.length;
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(component.history()).toBe(history); expect(component.currentReview()).toEqual(mapped); expect(save).toHaveBeenCalledTimes(calls);
    expect(harness.routeNativeElement!.querySelector('a[href*="topic_review=91"]')).not.toBeNull();
    harness.fixture.destroy(); TestBed.inject(Title).setTitle('Next route — OrganicSEOOps');
    component.productLanguage.set(language); TestBed.tick();
    expect(TestBed.inject(Title).getTitle()).toBe('Next route — OrganicSEOOps');
  });

  const queryEvidence = { kind: 'first_party_query_growth', query: 'Synthetic observed query', connection_id: 11,
    provider: 'google_search_console', property: 'sc-domain:source.example.invalid', search_type: 'web',
    previous_observation_id: 31, current_observation_id: 32, click_change: 0, impression_change: 2,
    source_windows: [{ import_id: 12, start: '2026-09-01', end: '2026-09-07', collected_at: '2026-09-10T00:00:00Z' },
      { import_id: 13, start: '2026-09-08', end: '2026-09-14', collected_at: '2026-09-17T00:00:00Z' }],
    source_coverage: { source_completeness: 'provider_export_unknown', hidden_queries: 'unknown', missing_previous_queries: 0,
      unavailable_metrics: 0, ambiguous_zero_rows: 0, growth_is_not_business_relevance: true },
    trend_state: 'first_party_comparable_growth', evergreen_state: 'unknown', business_relevance: 'not_evaluated' };
  const newsEvidence = { ...evidence, kind: 'provider_news_article', provider: 'gdelt',
    source_feeds: ['https://api.gdeltproject.org/api/v2/doc/doc?query=synthetic'], attribution_url: 'https://www.gdeltproject.org/',
    news_selection: { phrase: 'service news', publisher_origin: 'https://source.example.invalid', days: 7 },
    news_as_of: '2026-10-01T00:00:00Z', date_basis: 'provider_reported_not_verified_publication',
    market_language: 'not_verified_english_translingual_search' };

  it('rejects malformed original candidate evidence and retains separate literal feed news and comparable query provenance', async () => {
    const { component } = await screen(); const read = vi.spyOn(api, 'projectTopics');
    for (const source of [null, { ...evidence, kind: ['public_feed_item'] }, { ...evidence, kind: 'youtube' },
      ...[{ title: ['Synthetic'] }, { url: ['https://source.example.invalid/story'] }, { url: 'javascript:alert(1)' },
        { source_feeds: [null] }, { source_feeds: [] }, { source_feeds: ['javascript:alert(1)'] },
        { source_feeds: ['https://source.example.invalid/rss?forged=1'] }, { published_at: [] }, { freshness: ['unknown'] },
        { trend_state: 'measured_popularity' }, { evergreen_state: ['unknown'] }, { business_relevance: true }].map((change) => ({ ...evidence, ...change })),
      ...[{ query: ['Synthetic'] }, { title: ['Unexpected query title'] }, { url: 'https://source.example.invalid/forged' }, { provider: [] }, { property: {} }, { click_change: ['0'] }, { impression_change: null },
        { click_change: 0.5 }, { connection_id: 0 }, { previous_observation_id: [31] }, { current_observation_id: 0 },
        { source_windows: [null, queryEvidence.source_windows[1]] },
        { source_windows: [{ ...queryEvidence.source_windows[0], import_id: 0 }, queryEvidence.source_windows[1]] },
        { source_coverage: { ...queryEvidence.source_coverage, hidden_queries: ['unknown'] } }].map((change) => ({ ...queryEvidence, ...change })),
      ...[{ provider: ['gdelt'] }, { source_feeds: ['https://unrelated.example.invalid/rss?query=synthetic'] },
        { url: 'https://unrelated.example.invalid/story' }, { attribution_url: [] }, { news_as_of: null }, { news_selection: null },
        { date_basis: 'verified_publication' }].map((change) => ({ ...newsEvidence, ...change }))]) {
      read.mockResolvedValue(collection(null, source)); await component.openSnapshot(80);
      expect(component.snapshotId(), JSON.stringify(source)).toBe(0); expect(component.candidates()).toEqual([]);
      expect(component.coverage()).toBeNull(); expect(component.sourceCurrent()).toBe(false);
    }
    for (const source of [evidence, newsEvidence, queryEvidence, { ...queryEvidence, click_change: -1, impression_change: 2 }]) {
      read.mockResolvedValue(collection(null, source)); await component.openSnapshot(80);
      expect(component.candidates()[0].evidence).toEqual(source);
    }
  });

  it('clears malformed detail evidence before rendering and ignores a retired candidate response', async () => {
    const { harness, component } = await screen(); const catalog = await api.projectTopics(7, 9);
    const read = vi.spyOn(api, 'projectTopics');
    read.mockResolvedValue(collection()); await component.openSnapshot(80);
    for (const source of [null, { ...evidence, title: ['Unsafe topic'] }, { ...queryEvidence, impression_change: ['2'] },
      { ...queryEvidence, title: ['Unexpected query title'] }, { ...queryEvidence, url: 'https://source.example.invalid/forged' },
      { ...evidence, source_feeds: ['javascript:alert(1)'] }, { ...newsEvidence, url: 'https://unrelated.example.invalid/story' }]) {
      read.mockResolvedValue(candidate([review()])); await component.openCandidate(0); harness.detectChanges();
      expect(component.candidate()).not.toBeNull();
      read.mockResolvedValue(candidate([review()], true, source)); await component.openCandidate(0); harness.detectChanges();
      expect(component.candidate(), JSON.stringify(source)).toBeNull(); expect(component.history()).toEqual([]);
      expect(component.sourceCurrent()).toBe(false); expect(harness.routeNativeElement!.querySelector('#topic-label')).toBeNull();
      expect(harness.routeNativeElement!.querySelector('a[href*="topic_review"]')).toBeNull();
    }
    let finish!: (result: ApiResult) => void;
    read.mockReturnValueOnce(new Promise((resolve) => finish = resolve)); const old = component.openCandidate(0);
    read.mockResolvedValue({ status: 200, body: { ...catalog.body, project_id: 10 } });
    await harness.navigateByUrl('/topics/7/10', ProjectTopics); await vi.waitFor(() => expect(component.loading()).toBe(false));
    finish(candidate([review()])); await old;
    expect(component.projectId).toBe(10); expect(component.candidate()).toBeNull(); expect(component.history()).toEqual([]);
  });

  it('keeps bounded ordinal collections and empty evidence distinct and denies invalid collection identities before reading', async () => {
    const { component } = await screen(); const read = vi.spyOn(api, 'projectTopics');
    for (const id of [0, -1, 1.5]) await component.openSnapshot(id);
    expect(read).not.toHaveBeenCalled();
    const rows = Array.from({ length: 40 }, (_, index) => ({ index, evidence: { ...evidence, title: 'Synthetic topic ' + index }, review: null }));
    for (const candidates of [[], rows]) {
      read.mockResolvedValue({ status: 200, body: { project_id: 9, snapshot_id: 80, candidates, coverage: { truncated: true } } });
      await component.openSnapshot(80); expect(component.candidates()).toEqual(candidates); expect(component.snapshotId()).toBe(80);
    }
    for (const candidates of [[{ ...rows[0], index: [0] }], [{ ...rows[0], index: 1 }], [...rows, { ...rows[0], index: 40 }]]) {
      read.mockResolvedValue({ status: 200, body: { project_id: 9, snapshot_id: 80, candidates, coverage: { truncated: true } } });
      await component.openSnapshot(80); expect(component.candidates()).toEqual([]); expect(component.snapshotId()).toBe(0);
    }
  });

  it('refuses malformed configured text arrays before enabling discovery resources', async () => {
    const { component } = await screen(); const catalog = await api.projectTopics(7, 9);
    for (const change of [{ feeds: [['https://source.example.invalid/rss']] }, { feeds: [null] },
      { languages: [['en']] }, { languages: [{}] }]) {
      api.pending = Promise.resolve({ status: 200, body: { ...catalog.body, ...change } });
      await component.load();
      expect(component.error(), JSON.stringify(change)).toContain('unavailable'); expect(component.canEdit()).toBe(false);
      expect(component.feeds()).toEqual([]); expect(component.languages()).toEqual([]);
      expect(component.connections()).toEqual([]); expect(component.snapshots()).toEqual([]);
    }
    api.pending = Promise.resolve(catalog); await component.load();
    expect(component.canEdit()).toBe(true); expect(component.languages()).toEqual(['en']);
    expect(component.feeds()).toEqual(['https://source.example.invalid/rss']);
  });

  it('uses only scalar current source identities, related imports and bounded collection history', async () => {
    const { component } = await screen(); const catalog = await api.projectTopics(7, 9);
    const connection = { id: 11, provider: 'google_search_console', property: 'https://source.example.invalid/' };
    const imported = { id: 12, connection_id: 11, start: '2026-10-01', end: '2026-10-02' };
    const snapshot = { id: 80, created_at: '2026-10-01T00:00:00Z', candidate_count: 0 };
    const body = { ...catalog.body, connections: [connection], imports: [imported], snapshots: [snapshot] };
    for (const [key, valid, changes] of [
      ['connections', connection, [{ id: 0 }, { id: '11' }, { provider: ['google_search_console'] }, { property: {} }]],
      ['imports', imported, [{ id: 0 }, { connection_id: 10 }, { connection_id: [11] }, { start: [] }, { end: null }]],
      ['snapshots', snapshot, [{ id: 0 }, { created_at: [] }, { candidate_count: -1 }, { candidate_count: 41 }, { candidate_count: [0] }]],
    ] as const) {
      for (const change of changes) {
        api.pending = Promise.resolve({ status: 200, body: { ...body, [key]: [valid, { ...valid, ...change }, null] } });
        await component.load();
        expect(key === 'connections' ? component.connections() : key === 'imports' ? component.imports() : component.snapshots(),
          JSON.stringify(change)).toEqual([valid]);
      }
    }
    api.pending = Promise.resolve({ status: 200, body }); await component.load(); component.connection.set(11);
    expect(component.selectedImports()).toEqual([imported]); expect(component.snapshots()).toEqual([snapshot]);
    api.pending = Promise.resolve({ status: 200, body: { ...body, snapshots: [{ ...snapshot, candidate_count: 40 }] } });
    await component.load(); expect(component.snapshots()[0].candidate_count).toBe(40);
  });

  it('offers only scalar current reviewed mapping choices with supported page-action pairs', async () => {
    const { component } = await screen();
    const mapping = { review_id: 91, label: 'Human coverage choice', language: 'en', market: 'Türkiye',
      page_kind: 'existing_unverified', preferred_page: 'https://source.example.invalid/guide',
      proposed_action: 'refresh', source_current: true };
    const read = vi.spyOn(api, 'intentClusters');
    for (const change of [{ source_current: [true] }, { source_current: 'true' }, { source_current: false },
      { review_id: 0 }, { review_id: [91] }, { label: [] }, { language: ['en'] }, { market: {} },
      { preferred_page: [] }, { page_kind: ['existing_unverified'] }, { page_kind: 'unknown' },
      { proposed_action: ['refresh'] }, { proposed_action: 'unknown' }, { proposed_action: 'unselected' },
      { page_kind: 'unmapped' }, { page_kind: 'proposed', proposed_action: 'refresh' },
      { page_kind: 'existing_unverified', proposed_action: 'create' }]) {
      read.mockResolvedValue({ status: 200, body: { project_id: 9, clusters: [mapping, { ...mapping, ...change }] } });
      await component.load(); expect(component.mappings(), JSON.stringify(change)).toEqual([mapping]);
    }
    for (const action of ['keep', 'refresh', 'merge', 'redirect', 'retire', 'create']) {
      const row = { ...mapping, proposed_action: action, page_kind: action === 'create' ? 'proposed' : 'existing_unverified' };
      read.mockResolvedValue({ status: 200, body: { project_id: 9, clusters: [row] } });
      await component.load(); expect(component.mappings()).toEqual([row]);
    }
    for (const result of [{ status: 403, body: {} }, { status: 200, body: { project_id: 10, clusters: [mapping] } },
      { status: 200, body: { clusters: [mapping] } }]) {
      read.mockResolvedValue(result); const refresh = component.load(); expect(component.mappings()).toEqual([]);
      await refresh; expect(component.mappings()).toEqual([]); expect(component.message()).toContain('mapping choices unavailable');
    }
  });

  it('does not read topic or mapping sources when pending project context arrives after destruction', async () => {
    const { harness, component } = await screen();
    let finish!: (result: ApiResult) => void;
    vi.spyOn(api, 'projectOnboarding').mockReturnValueOnce(new Promise((resolve) => finish = resolve));
    const topics = vi.spyOn(api, 'projectTopics'); const mappings = vi.spyOn(api, 'intentClusters');
    const refresh = component.load(); harness.fixture.destroy();
    finish({ status: 200, body: { project: { id: 9, organization_id: 7, name: 'Retired project', role: 'member' } } });
    await refresh;
    expect(topics).not.toHaveBeenCalled(); expect(mappings).not.toHaveBeenCalled();
    expect(component.canEdit()).toBe(false); expect(component.jobs()).toEqual([]); expect(component.feeds()).toEqual([]);
  });

  it('keeps only positive scalar job history identities and supported statuses', async () => {
    const { component } = await screen();
    const catalog = await api.projectTopics(7, 9);
    for (const status of ['queued', 'running', 'waiting_provider', 'succeeded', 'failed', 'cancelled', 'partially_succeeded']) {
      const valid = { id: 81, status };
      for (const row of [{ id: 81, status: [status] }, { id: 0, status }, { id: -1, status },
        { id: 1.5, status }, { id: '81', status }, { id: 81, status: 'unknown' }, null]) {
        api.pending = Promise.resolve({ status: 200, body: { ...catalog.body, jobs: [valid, row] } });
        await component.load(); expect(component.jobs(), JSON.stringify(row)).toEqual([valid]);
      }
    }
  });

  it('rejects malformed job detail fields and clears current detail before refresh', async () => {
    const { component } = await screen();
    const valid = api.detail;
    for (const change of [{ status: ['running'] }, { status: 'unknown' }, { cancel_requested: [false] },
      { error_category: [] }, { snapshot_id: 0 }, { snapshot_id: [80] }, { estimated_units: 0 },
      { estimated_units: 8 }, { attempted_units: -1 }, { attempted_units: 2 }, { attempted_units: 0.5 },
      { steps: [{ name: 'Collect configured feed', status: ['running'], error_category: '' }] },
      { steps: [{ name: [], status: 'running', error_category: '' }] }, { steps: [null] }]) {
      api.detail = { ...valid, ...change }; await component.openJob(81);
      expect(component.job(), JSON.stringify(change)).toBeNull();
    }
    for (const status of ['queued', 'running', 'waiting_provider', 'succeeded', 'failed', 'cancelled', 'partially_succeeded']) {
      for (const step of ['running', 'succeeded', 'failed']) {
        api.detail = { ...valid, status, snapshot_id: 80, attempted_units: 1,
          steps: [{ name: 'Collect configured feed', status: step, error_category: '' }] };
        await component.openJob(81); expect(component.job()?.status).toBe(status);
      }
    }
    let finish!: (result: ApiResult) => void;
    api.jobPending = new Promise((resolve) => finish = resolve);
    const refresh = component.openJob(81); expect(component.job()).toBeNull();
    finish({ status: 403, body: {} }); await refresh;
    expect(component.job()).toBeNull(); expect(component.message()).toContain('unavailable');
    const read = vi.spyOn(api, 'projectTopicJob');
    for (const id of [0, -1, 1.5]) await component.openJob(id);
    expect(read).not.toHaveBeenCalled();
  });

  it.each(['en', 'tr'] as const)('refuses malformed queue acknowledgments without replay and accepts actual scalar states in %s', async (language) => {
    const { harness, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } });
    const form = harness.routeNativeElement!.querySelector('form')!;
    form.querySelector<HTMLInputElement>('[name="feeds"]')!.checked = true;
    const queue = vi.spyOn(api, 'discoverProjectTopics');
    expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe(language);
    expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe(language === 'tr' ? 'Konu keşfi ve insan incelemesi' : 'Topic discovery and human review');
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'iki dilli onay bekleniyor' : 'No AI classification or automatic publication');
    const include = form.querySelector<HTMLInputElement>('#topic-news')!;
    include.checked = true; include.dispatchEvent(new Event('change')); harness.detectChanges();
    form.querySelector<HTMLSelectElement>('#topic-news-phrase')!.value = 'service news';
    form.querySelector<HTMLSelectElement>('#topic-news-publisher')!.value = 'https://source.example.invalid';
    form.querySelector<HTMLSelectElement>('#topic-news-window')!.value = '7';
    const fields = [...new FormData(form).entries()];
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(harness.routeNativeElement!.querySelector('form')).toBe(form); expect([...new FormData(form).entries()]).toEqual(fields);
    expect(component.newsEnabled()).toBe(true); expect(include.checked).toBe(true); expect(queue).not.toHaveBeenCalled();
    component.productLanguage.set(language); harness.detectChanges();
    for (const change of [{ status: ['queued'] }, { status: 'unknown' }, { job_id: 0 }, { job_id: -1 }, { project_id: 10 }]) {
      const before = component.jobs(); const count = queue.mock.calls.length;
      api.acknowledgment = { status: 202, body: { project_id: 9, job_id: 82, status: 'queued', ...change } };
      await component.discover(command(form));
      harness.detectChanges(); expect(harness.routeNativeElement!.textContent).toContain(component.t(component.message()));
      expect(component.jobs(), JSON.stringify(change)).toEqual(before);
      expect(component.message()).not.toContain('Discovery queued'); expect(queue).toHaveBeenCalledTimes(count + 1);
    }
    let jobId = 82;
    for (const status of ['queued', 'running', 'waiting_provider', 'succeeded', 'failed', 'cancelled', 'partially_succeeded']) {
      api.acknowledgment = { status: 202, body: { project_id: 9, job_id: ++jobId, status } };
      await component.discover(command(form)); expect(component.jobs()[0]).toEqual({ id: jobId, status });
      expect(queue).toHaveBeenLastCalledWith(7, 9, expect.objectContaining({ feeds: ['https://source.example.invalid/rss'],
        connection_id: null, previous_import_id: null, current_import_id: null,
        news: { phrase: 'service news', publisher_origin: 'https://source.example.invalid', days: 7 } }));
    }
    let finish!: (result: ApiResult) => void; queue.mockReturnValueOnce(new Promise((resolve) => finish = resolve));
    const pending = component.discover(command(form)), calls = queue.mock.calls.length;
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(component.busy()).toBe(true); expect([...new FormData(form).entries()]).toEqual(fields); expect(queue).toHaveBeenCalledTimes(calls);
    finish({ status: 202, body: { project_id: 9, job_id: 99, status: 'queued' } }); await pending; harness.detectChanges();
    expect(component.jobs()[0].id).toBe(99); expect(queue).toHaveBeenCalledTimes(calls);
    expect(harness.routeNativeElement!.textContent).toContain(component.t(component.message()));
  });

  it('denies malformed roles before source reads and clears prior command resources', async () => {
    const { harness, component } = await screen();
    const form = harness.routeNativeElement!.querySelector('form')!;
    form.querySelector<HTMLInputElement>('[name="feeds"]')!.checked = true;
    const sources = vi.spyOn(api, 'projectTopics'); const mappings = vi.spyOn(api, 'intentClusters');
    const discover = vi.spyOn(api, 'discoverProjectTopics'); const save = vi.spyOn(api, 'saveProjectTopic');
    const job = vi.spyOn(api, 'projectTopicJob');
    for (const role of [['owner'], ['admin'], ['member'], ['viewer'], null, {}, 'unsupported']) {
      api.role = role; sources.mockClear(); mappings.mockClear();
      const refresh = component.load();
      expect(component.canEdit()).toBe(false); expect(component.feeds()).toEqual([]);
      expect(component.jobs()).toEqual([]); expect(component.snapshots()).toEqual([]);
      expect(component.candidate()).toBeNull(); expect(component.history()).toEqual([]);
      await refresh; harness.detectChanges();
      expect(component.error()).toContain('unavailable'); expect(component.canEdit()).toBe(false);
      expect(sources).not.toHaveBeenCalled(); expect(mappings).not.toHaveBeenCalled();
      await component.discover(command(form)); await component.save(command(form)); await component.openJob(81, true);
      expect(discover).not.toHaveBeenCalled(); expect(save).not.toHaveBeenCalled(); expect(job).not.toHaveBeenCalled();
      expect(harness.routeNativeElement!.querySelector('form')).toBeNull();
    }
  });

  it('keeps commands disabled during a pending or rejected source refresh', async () => {
    const { harness, component } = await screen();
    const form = harness.routeNativeElement!.querySelector('form')!;
    form.querySelector<HTMLInputElement>('[name="feeds"]')!.checked = true;
    const discover = vi.spyOn(api, 'discoverProjectTopics'); const job = vi.spyOn(api, 'projectTopicJob');
    for (const result of [{ status: 403, body: {} }, { status: 200, body: { project_id: 10 } }]) {
      let finish!: (value: ApiResult) => void;
      api.pending = new Promise((resolve) => finish = resolve);
      const refresh = component.load(); await Promise.resolve();
      expect(component.loading()).toBe(true); expect(component.canEdit()).toBe(false);
      await component.discover(command(form)); await component.openJob(81, true);
      expect(discover).not.toHaveBeenCalled(); expect(job).not.toHaveBeenCalled();
      finish(result); await refresh; harness.detectChanges();
      expect(component.error()).toContain('unavailable'); expect(component.canEdit()).toBe(false);
      expect(component.feeds()).toEqual([]); expect(component.news()).toBeNull();
      expect(component.jobs()).toEqual([]); expect(component.snapshots()).toEqual([]);
    }
  });

  it('preserves the four scalar roles and ignores an old source response after route reuse', async () => {
    const { harness, component } = await screen();
    for (const role of ['owner', 'admin', 'member', 'viewer']) {
      api.role = role; await component.load(); harness.detectChanges();
      expect(component.error()).toBe(''); expect(component.canEdit()).toBe(role !== 'viewer');
      expect(component.feeds()).toEqual(['https://source.example.invalid/rss']);
      expect(Boolean(harness.routeNativeElement!.querySelector('form'))).toBe(role !== 'viewer');
    }
    api.role = 'owner';
    let finish!: (value: ApiResult) => void;
    api.pending = new Promise((resolve) => finish = resolve);
    const old = component.load(); await Promise.resolve();
    api.pending = null; api.role = 'viewer';
    await harness.navigateByUrl('/topics/7/10', ProjectTopics);
    await vi.waitFor(() => expect(component.loading()).toBe(false)); harness.detectChanges();
    finish({ status: 200, body: { project_id: 9 } }); await old;
    expect(component.projectId).toBe(10); expect(component.error()).toBe(''); expect(component.canEdit()).toBe(false);
    expect(component.jobs()).toEqual([{ id: 81, status: 'queued' }]);
  });

  it('keeps invalid unavailable preferences and fresh production topic interfaces English without commands', async () => {
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    try {
      for (const mode of ['invalid', 'incompatible', 'signed-out', 'unavailable', 'production'] as const) {
        TestBed.resetTestingModule(); api = new TopicApi();
        TestBed.configureTestingModule({ providers: [provideRouter([
          { path: 'topics/:organizationId/:projectId', component: ProjectTopics },
        ]), { provide: AccountApi, useValue: api }] });
        buildEnvironment.production = mode === 'production';
        const discover = vi.spyOn(api, 'discoverProjectTopics'), save = vi.spyOn(api, 'saveProjectTopic');
        const preference: ApiResult | Error = mode === 'unavailable' ? new Error('private preference error')
          : mode === 'signed-out' ? { status: 401, body: {} } : { status: 200, body: {
            language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: mode === 'incompatible' ? 'tr' : 'en', current_email_language: 'en' } };
        const { harness, component } = await screen(preference);
        expect(TestBed.inject(Title).getTitle()).toBe('Source-aware topic review — OrganicSEOOps');
        expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe('Topic discovery and human review');
        expect(harness.routeNativeElement!.textContent).not.toContain('private preference error');
        expect(harness.routeNativeElement!.textContent).not.toContain('incelenmemiş Türkçe');
        if (mode === 'production') expect(component.productLanguage()).toBe('tr');
        api.role = null; await component.load(); harness.detectChanges();
        expect(harness.routeNativeElement!.querySelector('[role="alert"]')!.textContent).toBe('Project topic context unavailable or access revoked.');
        expect(discover).not.toHaveBeenCalled(); expect(save).not.toHaveBeenCalled(); harness.fixture.destroy();
      }
    } finally { buildEnvironment.production = production; }
  });
});
