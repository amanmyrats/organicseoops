import { Component, DestroyRef, ElementRef, HostListener, OnInit, ViewChild, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi } from '../account/account-api';

type Sample = { engine: string; query: string; location_code: number; language_code: string; device: string; origin: string; max_cost_usd: string };
type Row = { rank_group: number; rank_absolute: number; url: string; domain: string; matches_origin: boolean };
type Evidence = { method: string; provider: string; provider_task_id: string; observed_at: string; collected_at: string;
  os: string; source_sha256: string; features: string[]; rows: Row[] };
type Job = { id: number; project_id: number; status: string; request_key: string; selection: Sample; scheduled_for: string | null;
  source_current: boolean; created_at: string; error_category: string; cancel_requested: boolean; attempted: boolean;
  reported_cost_usd: string | null; evidence: Evidence | null };
type Schedule = { id: number; project_id: number; request_key: string; enabled: boolean; sample: Sample;
  policy: { interval_minutes: number; max_occurrences: number; total_max_cost_usd: string };
  expires_at: string; queued_occurrences: number; skipped_occurrences: number; blocked_reason: string; last_error_category: string; next_run_at: string | null };
type Capabilities = { provider: string; engine: string; revision: number; locations: Record<string, string>; languages: Record<string, string>;
  depth: number; estimated_task_cost_usd: string; reviewed_until: string; hard_provider_cost_cap: boolean };
type Page = { project_id: number; method: string; can_manage: boolean; can_collect: boolean; capabilities: Capabilities | null;
  origins: string[]; history_started_at: string | null; jobs: Job[]; next_before: number | null; schedules: Schedule[]; next_schedule_before: number | null };
type Candidate = { domain: string; engine: string; location_code: number; language_code: string; device: string; origin: string; queries: string[]; job_ids: number[] };
type Overlap = { project_id: number; method: string; inspected_jobs: number; history_truncated: boolean; candidates: Candidate[]; has_more: boolean; approval_required: boolean };
const METHOD = 'dataforseo-google-top10-v1';
const validId = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value > 0;
const text = (value: unknown): value is string => typeof value === 'string';

@Component({
  selector: 'app-project-serp', imports: [RouterLink],
  template: `
    <section class="workspace-panel" lang="en" aria-labelledby="serp-title">
      <h1 id="serp-title">Search-result observations and schedules</h1>
      <p><a [routerLink]="['/app/dashboard', organizationId, projectId]">Return to project dashboard</a></p>
      <p>DataForSEO Google organic observations are separate from webmaster average position. Each paid request observes returned top-ten organic results
        for one query, location, language and device. This is not a universal or personalized rank. A missing match means not observed here, not unranked.</p>
      @if (error()) { <p role="alert">{{ error() }}</p> }
      @if (message()) { <p role="status">{{ message() }}</p> }
      @if (loading()) { <p role="status">Loading current private project access and history.</p> }
      @if (page(); as data) {
        <p>Successful tracking history starts {{ data.history_started_at ?? 'with the first successful observation' }}.
          This live endpoint cannot backfill earlier dates. Missed slots remain gaps.</p>
        @if (data.capabilities; as capability) {
          <p>Estimated provider cost USD{{ capability.estimated_task_cost_usd }} per request; review expires {{ capability.reviewed_until }}.
            This is estimated exposure, not a provider-enforced spending cap. Only reviewed location/language codes are available.
            Search operators, deeper results and paid AI extras are unavailable.</p>
          @if (data.can_collect && data.can_manage) {
            <form #selectionForm (submit)="submit($event)">
              <label for="serp-query">Tracked query</label><input id="serp-query" name="query" maxlength="200" required>
              <label for="serp-origin">Exact project origin to match</label><select id="serp-origin" name="origin" required>
                @for (origin of data.origins; track origin) { <option [value]="origin">{{ origin }}</option> }
              </select>
              <label for="serp-location">Provider location</label><select id="serp-location" name="location" required>
                @for (item of entries(capability.locations); track item[0]) { <option [value]="item[0]">{{ item[1] }} · {{ item[0] }}</option> }
              </select>
              <label for="serp-language">Provider language</label><select id="serp-language" name="language" required>
                @for (item of entries(capability.languages); track item[0]) { <option [value]="item[0]">{{ item[1] }} · {{ item[0] }}</option> }
              </select>
              <label for="serp-device">Device</label><select id="serp-device" name="device"><option value="desktop">Desktop · Windows</option><option value="mobile">Mobile · Android</option></select>
              <label for="serp-cost">Reserved estimated exposure per request, USD</label>
              <input id="serp-cost" name="cost" type="number" min="0.000001" max="1000" step="0.000001" required [value]="capability.estimated_task_cost_usd">
              <label for="serp-mode">Collection choice</label><select id="serp-mode" name="mode"><option value="observe">One observation now</option><option value="create_schedule">Create a paused finite schedule</option></select>
              <fieldset><legend>New schedule bounds (used only for a schedule)</legend>
                <label for="serp-interval">Interval</label><select id="serp-interval" name="interval"><option value="1440">Daily</option><option value="10080">Weekly</option></select>
                <label for="serp-occurrences">Maximum paid occurrences</label><input id="serp-occurrences" name="occurrences" type="number" min="1" max="30" value="7">
                <label for="serp-lifetime">Fixed lifetime, days</label><input id="serp-lifetime" name="lifetime" type="number" min="2" max="30" value="14">
                <label for="serp-total">Total estimated exposure, USD</label><input id="serp-total" name="total" type="number" min="0.000001" max="1000" step="0.000001">
              </fieldset>
              <p>Accepted requests consume reserved monthly exposure even if cancelled or unsuccessful. Schedules reserve each slot when queued,
                stop on failure or lost access, and never buy missed observations in bulk.</p>
              <label><input name="acknowledge" type="checkbox" required> I authorize sending this query and dimensions to DataForSEO and accept estimated paid exposure. Actual charges can differ.</label>
              <button type="submit" [disabled]="busy() || loading()">Record selected collection decision</button>
            </form>
          } @else { <p>Paid collection requires current manager access and an active organization allowance. Historical evidence remains available to readers.</p> }
        } @else { <p>The platform operator must configure encrypted provider credentials, reviewed capabilities, pricing and a monthly exposure budget in the protected staff interface.</p> }
        <h2>Observation history</h2>
        <ul>@for (job of data.jobs; track job.id) {
          <li>Observation {{ job.id }} · {{ job.status }} · {{ job.selection.query }} · {{ job.selection.engine }} · location {{ job.selection.location_code }}
            · {{ job.selection.language_code }} · {{ job.selection.device }} · {{ job.created_at }}
            <p>Request key {{ job.request_key }}. {{ job.attempted ? 'Provider request attempted' : 'No recorded paid attempt' }}.
              Provider-reported cost USD{{ job.reported_cost_usd ?? 'unknown' }}. {{ job.error_category }}
              @if (job.scheduled_for) { Scheduled slot {{ job.scheduled_for }}. }</p>
            @if (job.source_current) { <button type="button" [disabled]="busy()" (click)="inspect(job.id)">Inspect observation {{ job.id }}</button> }
            @else { <p>The original origin is no longer configured; evidence is withheld.</p> }
            @if (data.can_manage && (job.status === 'queued' || job.status === 'running')) {
              <button type="button" [disabled]="busy()" (click)="cancel(job.id)">Cancel observation {{ job.id }}</button>
              @if (job.cancel_requested) { <p>Cancellation requested. An already sent request can still be charged.</p> }
            }
          </li>
        } @empty { <li>No observations on this page.</li> }</ul>
        @if (data.next_before !== null) { <button type="button" [disabled]="busy()" (click)="load(data.next_before, scheduleBefore)">Older observations</button> }
        <h2>Finite schedules</h2>
        <ul>@for (schedule of data.schedules; track schedule.id) {
          <li>Schedule {{ schedule.id }} · {{ schedule.sample.query }} · {{ schedule.sample.engine }} · {{ schedule.sample.location_code }}
            · {{ schedule.sample.language_code }} · {{ schedule.sample.device }} · {{ schedule.sample.origin }}
            <p>{{ schedule.enabled ? 'Enabled' : 'Paused' }}; expires {{ schedule.expires_at }}; next slot {{ schedule.next_run_at ?? 'not enabled' }};
              queued {{ schedule.queued_occurrences }}/{{ schedule.policy.max_occurrences }}; missed {{ schedule.skipped_occurrences }}.
              Total estimated exposure USD{{ schedule.policy.total_max_cost_usd }}. {{ schedule.blocked_reason || schedule.last_error_category }}</p>
            @if (data.can_manage) {
              <form (submit)="toggle($event, schedule)">
                @if (!schedule.enabled) { <label><input name="acknowledge" type="checkbox" required> I authorize future paid requests under these unchanged bounds.</label> }
                <button type="submit" [disabled]="busy() || !schedule.enabled && (!data.can_collect || !!schedule.blocked_reason)">{{ schedule.enabled ? 'Pause schedule' : 'Enable schedule' }} {{ schedule.id }}</button>
              </form>
            }
          </li>
        } @empty { <li>No schedules on this page.</li> }</ul>
        @if (data.next_schedule_before !== null) { <button type="button" [disabled]="busy()" (click)="load(before, data.next_schedule_before)">Older schedules</button> }
        @if (before !== null || scheduleBefore !== null) { <button type="button" [disabled]="busy()" (click)="load()">Newest history</button> }
      }
      @if (selected(); as job) {
        @if (job.evidence; as evidence) {
          <h2>Observation {{ job.id }} · {{ evidence.observed_at }}</h2>
          <p>Provider task {{ evidence.provider_task_id }}; collected {{ evidence.collected_at }}; {{ evidence.os }}.
            Features: {{ evidence.features.join(', ') || 'none returned' }}. Non-organic features are labels, not organic ranks.</p>
          <div class="table-scroll" role="region" aria-label="SERP organic observations" tabindex="0"><table>
            <caption>Returned organic top-ten rows; exact origin matches are marked</caption>
            <thead><tr><th scope="col">Organic rank</th><th scope="col">Absolute result position</th><th scope="col">Observed URL</th><th scope="col">Exact origin match</th></tr></thead>
            <tbody>@for (row of evidence.rows; track row.rank_group) { <tr><td>{{ row.rank_group }}</td><td>{{ row.rank_absolute }}</td><td>{{ row.url }}</td><td>{{ row.matches_origin ? 'Yes' : 'No' }}</td></tr> }
            @empty { <tr><td colspan="4">No organic rows returned; rank is unavailable.</td></tr> }</tbody>
          </table></div><p>Private response fingerprint {{ evidence.source_sha256 }}. Raw responses are not retained.</p>
        } @else { <p>Observation {{ job.id }} has no deliverable result yet. {{ job.error_category }}</p> }
      }
      <h2>Reviewable search competitors</h2>
      <button type="button" [disabled]="busy() || loading() || !page()" (click)="overlap()">Inspect bounded SERP overlap evidence</button>
      @if (candidates(); as data) {
        <p>Inspected {{ data.inspected_jobs }} of at most100 successful observations from the last90 days. {{ data.history_truncated ? 'Older records are excluded.' : '' }}
          Domains appear for at least two distinct tracked queries within the same dimensions. This is not market share or proof of competition.
          Review source observations before adding a competitor in project configuration; this screen adds none automatically.</p>
        <ul>@for (item of data.candidates; track $index) {
          <li>{{ item.domain }} · {{ item.engine }} · {{ item.location_code }} · {{ item.language_code }} · {{ item.device }} · {{ item.origin }}.
            Queries: {{ item.queries.join('; ') }}. Source observation IDs: {{ item.job_ids.join(', ') }}.</li>
        } @empty { <li>No supported overlap candidates in this bounded sample.</li> }</ul>
        @if (data.has_more) { <p>Only the first20 candidates are shown.</p> }
      }
      <button type="button" [disabled]="busy() || loading()" (click)="load(before, scheduleBefore)">Refresh current access and history</button>
    </section>`,
  styles: `section { overflow-wrap:anywhere } form { display:grid; gap:.6rem; max-width:48rem } fieldset { display:grid; gap:.5rem } li { margin-block:1rem } button { margin:.4rem } .table-scroll { overflow:auto } table { border-collapse:collapse } th,td { border:1px solid currentColor; padding:.5rem; text-align:start; vertical-align:top }`,
})
export class ProjectSerp implements OnInit {
  @ViewChild('selectionForm') form?: ElementRef<HTMLFormElement>;
  organizationId = 0; projectId = 0; before: number | null = null; scheduleBefore: number | null = null;
  private generation = 0;
  readonly page = signal<Page | null>(null); readonly selected = signal<Job | null>(null); readonly candidates = signal<Overlap | null>(null);
  readonly loading = signal(false); readonly busy = signal(false); readonly error = signal(''); readonly message = signal('');
  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi, private readonly destroy: DestroyRef) {}
  ngOnInit() {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroy)).subscribe((params) => {
      this.clear(); this.organizationId = Number(params.get('organizationId')); this.projectId = Number(params.get('projectId')); void this.load();
    });
    this.destroy.onDestroy(() => this.clear());
  }
  entries(values: Record<string, string>) { return Object.entries(values); }
  private clear() {
    ++this.generation; this.form?.nativeElement.reset(); this.page.set(null); this.selected.set(null); this.candidates.set(null);
    this.loading.set(false); this.busy.set(false); this.error.set(''); this.message.set('');
  }
  private current(generation: number) { return generation === this.generation && !document.hidden && !this.destroy.destroyed; }
  @HostListener('document:visibilitychange') hidden() {
    if (document.hidden) { this.clear(); this.message.set('Private data cleared while hidden. Refresh access to continue.'); }
  }
  private validSample(sample: Sample) {
    return sample && sample.engine === 'google' && text(sample.query) && validId(sample.location_code) && text(sample.language_code)
      && ['desktop', 'mobile'].includes(sample.device) && text(sample.origin) && text(sample.max_cost_usd);
  }
  private validJob(job: Job) {
    return job && validId(job.id) && job.project_id === this.projectId && this.validSample(job.selection) && text(job.status)
      && text(job.request_key) && text(job.created_at) && typeof job.source_current === 'boolean'
      && (job.evidence === null || job.source_current && job.evidence.method === METHOD && job.evidence.provider === 'dataforseo'
        && text(job.evidence.observed_at) && text(job.evidence.provider_task_id) && text(job.evidence.source_sha256)
        && Array.isArray(job.evidence.features) && job.evidence.features.length <= 200 && job.evidence.features.every(text)
        && Array.isArray(job.evidence.rows) && job.evidence.rows.length <= 10
        && job.evidence.rows.every((row) => row && validId(row.rank_group) && validId(row.rank_absolute) && text(row.url) && text(row.domain) && typeof row.matches_origin === 'boolean'));
  }
  private validSchedule(row: Schedule) {
    return row && validId(row.id) && row.project_id === this.projectId && this.validSample(row.sample) && typeof row.enabled === 'boolean'
      && text(row.request_key) && text(row.expires_at) && row.policy && validId(row.policy.interval_minutes)
      && validId(row.policy.max_occurrences) && text(row.policy.total_max_cost_usd) && Number.isSafeInteger(row.queued_occurrences)
      && Number.isSafeInteger(row.skipped_occurrences) && text(row.blocked_reason) && text(row.last_error_category);
  }
  async load(before: number | null = null, scheduleBefore: number | null = null) {
    this.clear(); this.before = before; this.scheduleBefore = scheduleBefore;
    if (document.hidden || this.destroy.destroyed || !validId(this.organizationId) || !validId(this.projectId)) return;
    const generation = this.generation; this.loading.set(true);
    try {
      const query: Record<string, string> = {};
      if (before !== null) query['before'] = String(before);
      if (scheduleBefore !== null) query['schedule_before'] = String(scheduleBefore);
      const response = await this.api.serp(this.organizationId, this.projectId, 0, undefined, query);
      if (!this.current(generation)) return;
      const data = response.body as unknown as Page;
      const labels = (value: Record<string, string>) => value && typeof value === 'object' && !Array.isArray(value)
        && Object.keys(value).length <= 100 && Object.values(value).every(text);
      if (response.status !== 200 || data.project_id !== this.projectId || data.method !== METHOD
        || typeof data.can_manage !== 'boolean' || typeof data.can_collect !== 'boolean'
        || !Array.isArray(data.origins) || data.origins.length > 100 || !data.origins.every(text)
        || !Array.isArray(data.jobs) || data.jobs.length > 20 || !data.jobs.every((job) => this.validJob(job) && job.evidence === null)
        || !Array.isArray(data.schedules) || data.schedules.length > 20 || !data.schedules.every((row) => this.validSchedule(row))
        || ![data.next_before, data.next_schedule_before].every((value) => value === null || validId(value))
        || data.capabilities !== null && (data.capabilities.provider !== 'dataforseo' || data.capabilities.engine !== 'google'
          || !validId(data.capabilities.revision) || data.capabilities.depth !== 10 || !labels(data.capabilities.locations)
          || !labels(data.capabilities.languages) || !text(data.capabilities.estimated_task_cost_usd))) throw new Error();
      this.page.set(data);
    } catch { if (this.current(generation)) this.error.set('Private SERP history unavailable. Refresh current project access.'); }
    finally { if (this.current(generation)) this.loading.set(false); }
  }
  async submit(event: Event) {
    event.preventDefault();
    const page = this.page(); const capability = page?.capabilities;
    if (this.busy() || !page?.can_collect || !page.can_manage || !capability || document.hidden) return;
    const form = new FormData(event.target as HTMLFormElement);
    const sample: Sample = { engine: 'google', query: String(form.get('query') ?? ''), origin: String(form.get('origin') ?? ''),
      location_code: Number(form.get('location')), language_code: String(form.get('language') ?? ''),
      device: String(form.get('device') ?? ''), max_cost_usd: String(form.get('cost') ?? '') };
    const command = String(form.get('mode'));
    const body: Record<string, unknown> = { command, sample, revision: capability.revision, acknowledge_paid_requests: form.get('acknowledge') === 'on' };
    if (command === 'create_schedule') Object.assign(body, { interval_minutes: Number(form.get('interval')),
      max_occurrences: Number(form.get('occurrences')), lifetime_days: Number(form.get('lifetime')), total_max_cost_usd: String(form.get('total') ?? '') });
    const generation = this.generation; this.busy.set(true); this.selected.set(null); this.candidates.set(null); this.error.set('');
    try {
      const stable = { ...body }; delete stable['revision'];
      const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(stable)));
      if (!this.current(generation)) return;
      const fingerprint = `${this.organizationId}:${this.projectId}:` + Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, '0')).join('');
      const key = this.api.serpPendingRequests.get(fingerprint) ?? crypto.randomUUID();
      this.api.serpPendingRequests.set(fingerprint, key); body['request_key'] = key;
      const response = await this.api.serp(this.organizationId, this.projectId, 0, body);
      const job = response.body['job'] as Job | undefined; const schedule = response.body['schedule'] as Schedule | undefined;
      if (response.body['project_id'] !== this.projectId || response.body['method'] !== METHOD
        || !(command === 'observe' ? response.status === 202 && job && this.validJob(job) && job.request_key === key
          : response.status === 200 && schedule && this.validSchedule(schedule) && schedule.request_key === key)) throw new Error();
      this.api.serpPendingRequests.delete(fingerprint);
      if (!this.current(generation)) return;
      await this.load();
      if (this.current(generation + 1)) this.message.set(command === 'observe' ? 'Observation recorded. Refresh history for completion. Unknown outcomes are never retried automatically.' : 'Paused finite schedule recorded. Review its bounds and explicitly enable it below.');
    } catch { if (this.current(generation)) this.error.set('Collection decision unconfirmed. Refresh history; submitting the same unchanged selection keeps its request key, including after navigation.'); }
    finally { if (this.current(generation)) this.busy.set(false); }
  }
  async inspect(jobId: number) {
    if (this.busy() || document.hidden || !this.page()) return;
    const generation = this.generation; this.busy.set(true); this.selected.set(null); this.candidates.set(null); this.error.set('');
    try {
      const response = await this.api.serp(this.organizationId, this.projectId, jobId);
      if (!this.current(generation)) return;
      const job = response.body['job'] as Job;
      if (response.status !== 200 || response.body['project_id'] !== this.projectId || response.body['method'] !== METHOD || !this.validJob(job) || job.id !== jobId) throw new Error();
      this.selected.set(job);
    } catch { if (this.current(generation)) this.error.set('Observation unavailable. Refresh current source and project access.'); }
    finally { if (this.current(generation)) this.busy.set(false); }
  }
  async cancel(jobId: number) { await this.control({ command: 'cancel' }, jobId); }
  async toggle(event: Event, schedule: Schedule) {
    event.preventDefault();
    const form = new FormData(event.target as HTMLFormElement);
    await this.control({ command: 'set_schedule', schedule_id: schedule.id, enabled: !schedule.enabled,
      acknowledge_paid_requests: form.get('acknowledge') === 'on' });
  }
  private async control(body: Record<string, unknown>, jobId = 0) {
    if (this.busy() || document.hidden || !this.page()?.can_manage) return;
    const generation = this.generation; this.busy.set(true); this.selected.set(null); this.candidates.set(null); this.error.set('');
    try {
      const response = await this.api.serp(this.organizationId, this.projectId, jobId, body);
      if (!this.current(generation)) return;
      if (response.status !== 200 || response.body['project_id'] !== this.projectId || response.body['method'] !== METHOD) throw new Error();
      await this.load(this.before, this.scheduleBefore);
    } catch { if (this.current(generation)) this.error.set('Control decision unconfirmed. Refresh schedule and observation status.'); }
    finally { if (this.current(generation)) this.busy.set(false); }
  }
  async overlap() {
    if (this.busy() || document.hidden || !this.page()) return;
    const generation = this.generation; this.busy.set(true); this.candidates.set(null); this.selected.set(null); this.error.set('');
    try {
      const response = await this.api.serpOverlap(this.organizationId, this.projectId);
      if (!this.current(generation)) return;
      const data = response.body as unknown as Overlap;
      if (response.status !== 200 || data.project_id !== this.projectId || data.method !== METHOD || data.approval_required !== true
        || !Number.isSafeInteger(data.inspected_jobs) || data.inspected_jobs > 100 || !Array.isArray(data.candidates) || data.candidates.length > 20
        || !data.candidates.every((item) => item && text(item.domain) && text(item.engine) && validId(item.location_code) && text(item.language_code)
          && text(item.device) && text(item.origin) && Array.isArray(item.queries) && item.queries.length <= 100 && item.queries.every(text)
          && Array.isArray(item.job_ids) && item.job_ids.length <= 100 && item.job_ids.every(validId))) throw new Error();
      this.candidates.set(data);
    } catch { if (this.current(generation)) this.error.set('Bounded overlap evidence unavailable. Refresh current project access.'); }
    finally { if (this.current(generation)) this.busy.set(false); }
  }
}
