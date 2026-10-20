import { Component, HostListener, Input, OnChanges, OnDestroy, signal } from '@angular/core';
import { AccountApi } from '../account/account-api';

export type YandexSyncGrant = { id: number; origin: string; revision: number; state: string; refresh_unknown: boolean;
  suggested_start: string; suggested_end: string; cursor: { status: string; error_category: string; quota_state: string;
    retry_after: string | null; anchor_start: string | null; next_start: string | null; contiguous_reported_through: string | null } | null };
type Metrics = { date: string; source_timestamp: string; TOTAL_SHOWS: number | null; TOTAL_CLICKS: number | null;
  AVG_SHOW_POSITION: string | null; AVG_CLICK_POSITION: string | null };
type Evidence = { method: string; provider: string; origin: string; date_start: string; date_end: string;
  device: string; calendar: string; coverage: string; complete_window: boolean; rows: Metrics[] };
type Sync = { id: number; project_id: number; grant_id: number; status: string; created_at: string;
  date_start: string; date_end: string; source_current: boolean; error_category: string; cancel_requested: boolean; evidence: Evidence | null };
type History = { project_id: number; method: string; jobs: Sync[]; next_before: number | null };

@Component({
  selector: 'app-project-yandex-sync',
  template: `
    <section lang="en" aria-labelledby="yandex-sync-title">
      <h2 id="yandex-sync-title">Yandex aggregate API history</h2>
      <p>Separate site-level daily indicators for all devices. These are not query/page pairs, final coverage, indexing proof or Google measurements.
        Dates retain the offset returned by Yandex; missing days and indicators are unavailable, not zero.</p>
      @if (error()) { <p role="alert">{{ error() }}</p> }
      @if (message()) { <p role="status">{{ message() }}</p> }
      @if (loading()) { <p role="status">Loading current private sync history.</p> }
      @if (canManage) {
        @for (grant of grants; track grant.id) {
          @if (grant.state === 'active' && !grant.refresh_unknown) {
            <h3>{{ grant.origin }}</h3>
            @if (grant.cursor; as cursor) {
              <p>Cursor {{ cursor.status }} · quota {{ cursor.quota_state }} · contiguous reported window
                {{ cursor.anchor_start ?? 'unavailable' }} through {{ cursor.contiguous_reported_through ?? 'unavailable' }}.
                Next requested start {{ cursor.next_start ?? 'unavailable' }}. This records returned daily show/click counts; positions may be unavailable. Provider finality is not established.</p>
              @if (cursor.error_category) { <p>Last attempt: {{ cursor.error_category }}. Retry no earlier than {{ cursor.retry_after ?? 'the source throttle interval' }}.</p> }
            }
            <form (submit)="start($event, grant)">
              <label [for]="'yandex-sync-start-' + grant.id">Inclusive source-calendar start</label>
              <input [id]="'yandex-sync-start-' + grant.id" name="start" type="date" required [value]="grant.suggested_start">
              <label [for]="'yandex-sync-end-' + grant.id">Inclusive source-calendar end</label>
              <input [id]="'yandex-sync-end-' + grant.id" name="end" type="date" required [value]="grant.suggested_end">
              <p>At most31 days per request within the local90-day bound. Provider history availability is not guaranteed.
                Submit successive windows to backfill; gaps or partial windows do not advance the contiguous cursor.</p>
              <button type="submit" [disabled]="busy() || loading()">Request one bounded sync · maximum1 internal unit</button>
            </form>
          }
        }
      }
      @if (history(); as data) {
        <h3>Separate API sync history</h3>
        <ul>@for (job of data.jobs; track job.id) {
          <li>Sync {{ job.id }} · {{ job.status }} · {{ job.date_start }} through {{ job.date_end }} · {{ job.created_at }}
            @if (job.error_category) { <p>Recorded result: {{ job.error_category }}.</p> }
            @if (!job.source_current) { <p>Original source authority unavailable; observations are withheld.</p> }
            @if (job.source_current && (job.status === 'succeeded' || job.status === 'partially_succeeded')) {
              <button type="button" [disabled]="busy()" (click)="inspect(job.id)">Inspect sync {{ job.id }}</button>
            }
            @if (canManage && (job.status === 'queued' || job.status === 'running')) {
              <button type="button" [disabled]="busy()" (click)="cancel(job.id)">Cancel sync {{ job.id }}</button>
            }
          </li>
        } @empty { <li>No syncs on this page. No traffic or coverage is inferred.</li> }</ul>
        @if (data.next_before !== null) { <button type="button" [disabled]="busy()" (click)="load(data.next_before)">Older API syncs</button> }
        @if (before !== null) { <button type="button" [disabled]="busy()" (click)="load()">Newest API syncs</button> }
      }
      @if (selected(); as evidence) {
        <h3>{{ evidence.origin }} · {{ evidence.date_start }} through {{ evidence.date_end }}</h3>
        <p>{{ evidence.complete_window ? 'Show/click counts returned for every requested day' : 'Partial or empty provider coverage' }}.
          Source offsets are preserved; averages are not combined and may be unavailable even when all daily counts returned. Missing rows and values remain unknown.</p>
        <div class="table-scroll" role="region" aria-label="Yandex aggregate history rows" tabindex="0">
          <table><caption>Provider daily aggregate indicators, device ALL</caption>
            <thead><tr><th scope="col">Source timestamp</th><th scope="col">Shows</th><th scope="col">Clicks</th><th scope="col">Average show position</th><th scope="col">Average click position</th></tr></thead>
            <tbody>@for (row of evidence.rows; track row.date) {
              <tr><td>{{ row.source_timestamp }}</td><td>{{ row.TOTAL_SHOWS ?? 'Unavailable' }}</td><td>{{ row.TOTAL_CLICKS ?? 'Unavailable' }}</td><td>{{ row.AVG_SHOW_POSITION ?? 'Unavailable' }}</td><td>{{ row.AVG_CLICK_POSITION ?? 'Unavailable' }}</td></tr>
            } @empty { <tr><td colspan="5">No returned rows. This does not establish zero activity.</td></tr> }</tbody>
          </table>
        </div>
      }
      <button type="button" [disabled]="busy() || loading()" (click)="load(before)">Refresh private API history</button>
    </section>`,
  styles: `section { overflow-wrap:anywhere } form { display:grid; gap:.6rem; max-width:44rem } button { margin:.5rem } .table-scroll { overflow:auto } table { border-collapse:collapse } th,td { border:1px solid currentColor; padding:.5rem; text-align:start }`,
})
export class ProjectYandexSync implements OnChanges, OnDestroy {
  @Input() organizationId = 0; @Input() projectId = 0; @Input() canManage = false; @Input() grants: YandexSyncGrant[] = [];
  @Input() requestKeys = new Map<string, string>();
  readonly history = signal<History | null>(null); readonly selected = signal<Evidence | null>(null);
  readonly busy = signal(false); readonly loading = signal(false); readonly error = signal(''); readonly message = signal('');
  before: number | null = null; private generation = 0; private destroyed = false;
  constructor(private readonly api: AccountApi) {}
  ngOnChanges() { this.clear(); void this.load(); }
  ngOnDestroy() { this.destroyed = true; this.clear(); }
  private clear() { ++this.generation; this.history.set(null); this.selected.set(null); this.busy.set(false); this.loading.set(false); this.error.set(''); this.message.set(''); }
  @HostListener('document:visibilitychange') hidden() { if (document.hidden) this.clear(); }
  private current(generation: number) { return generation === this.generation && !this.destroyed && !document.hidden; }
  private validJob(value: unknown): value is Sync {
    if (!value || typeof value !== 'object') return false;
    const job = value as Sync;
    return Number.isSafeInteger(job.id) && job.id > 0 && job.project_id === this.projectId
      && Number.isSafeInteger(job.grant_id) && job.grant_id > 0 && typeof job.source_current === 'boolean'
      && typeof job.status === 'string' && typeof job.date_start === 'string' && typeof job.date_end === 'string'
      && (!job.evidence || job.source_current && ['succeeded', 'partially_succeeded'].includes(job.status)
        && job.evidence.method === 'yandex-site-history-v1' && job.evidence.provider === 'yandex_webmaster'
        && job.evidence.device === 'ALL' && typeof job.evidence.origin === 'string'
        && Array.isArray(job.evidence.rows) && job.evidence.rows.length <= 31
        && job.evidence.rows.every((row) => row && typeof row.date === 'string' && typeof row.source_timestamp === 'string'
          && [row.TOTAL_SHOWS, row.TOTAL_CLICKS].every((value) => value === null || Number.isSafeInteger(value) && value >= 0)
          && [row.AVG_SHOW_POSITION, row.AVG_CLICK_POSITION].every((value) => value === null || typeof value === 'string')));
  }
  async load(before: number | null = null) {
    this.clear(); this.before = before;
    if (document.hidden || this.destroyed || ![this.organizationId, this.projectId].every((id) => Number.isSafeInteger(id) && id > 0)) return;
    const generation = this.generation; this.loading.set(true);
    try {
      const response = await this.api.yandexSyncs(this.organizationId, this.projectId, 0, before);
      if (!this.current(generation)) return;
      const data = response.body as unknown as History;
      if (response.status !== 200 || data.project_id !== this.projectId || data.method !== 'yandex-site-history-v1'
        || !Array.isArray(data.jobs) || data.jobs.length > 20 || !data.jobs.every((job) => this.validJob(job) && job.evidence === null)
        || data.next_before !== null && (!Number.isSafeInteger(data.next_before) || data.next_before < 1)) throw new Error();
      this.history.set(data);
    } catch { if (this.current(generation)) this.error.set('API history unavailable. Refresh current project and source access.'); }
    finally { if (this.current(generation)) this.loading.set(false); }
  }
  async start(event: Event, grant: YandexSyncGrant) {
    event.preventDefault();
    if (this.busy() || document.hidden || !this.canManage || grant.refresh_unknown || grant.state !== 'active') return;
    const data = new FormData(event.target as HTMLFormElement);
    const start = String(data.get('start') ?? ''); const end = String(data.get('end') ?? '');
    const fingerprint = JSON.stringify([this.organizationId, this.projectId, grant.id, start, end]);
    let key = this.requestKeys.get(fingerprint);
    if (!key) { key = crypto.randomUUID(); this.requestKeys.set(fingerprint, key); }
    const generation = this.generation; this.busy.set(true); this.selected.set(null); this.error.set('');
    try {
      const response = await this.api.startYandexSync(this.organizationId, this.projectId,
        { grant_id: grant.id, revision: grant.revision, date_start: start, date_end: end, request_key: key });
      if (!this.current(generation)) return;
      if (response.status !== 202 || response.body['project_id'] !== this.projectId || !this.validJob(response.body['job'])) throw new Error();
      this.requestKeys.delete(fingerprint);
      await this.load();
      if (this.current(generation + 1)) this.message.set('Sync recorded. Refresh history for worker completion and refresh the project connection status for the next cursor window.');
    } catch { if (this.current(generation)) this.error.set('Sync was not confirmed. Refresh history and grant status before another selection.'); }
    finally { if (this.current(generation)) this.busy.set(false); }
  }
  async inspect(id: number) {
    if (this.busy() || document.hidden || this.destroyed) return;
    const generation = this.generation; this.busy.set(true); this.selected.set(null); this.error.set('');
    try {
      const response = await this.api.yandexSyncs(this.organizationId, this.projectId, id);
      if (!this.current(generation)) return;
      const job = response.body['job'];
      if (response.status !== 200 || response.body['project_id'] !== this.projectId || !this.validJob(job) || job.id !== id || !job.evidence) throw new Error();
      this.selected.set(job.evidence);
    } catch { if (this.current(generation)) { this.history.set(null); this.error.set('Current API observations unavailable. Refresh source access.'); } }
    finally { if (this.current(generation)) this.busy.set(false); }
  }
  async cancel(id: number) {
    if (this.busy() || document.hidden || this.destroyed || !this.canManage) return;
    const generation = this.generation; this.busy.set(true); this.selected.set(null); this.error.set('');
    try {
      const response = await this.api.yandexSyncs(this.organizationId, this.projectId, id, null, true);
      if (!this.current(generation)) return;
      if (response.status !== 200 || response.body['project_id'] !== this.projectId) throw new Error();
      await this.load(this.before);
    } catch { if (this.current(generation)) this.error.set('Cancellation is unconfirmed. Refresh private sync history.'); }
    finally { if (this.current(generation)) this.busy.set(false); }
  }
}
