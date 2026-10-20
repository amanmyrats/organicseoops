import { Component, DestroyRef, ElementRef, HostListener, OnInit, ViewChild, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi } from '../account/account-api';
import { ProjectYandexSync, type YandexSyncGrant } from './project-yandex-sync';

type Row = { date: string; host: string; url: string; query: string; region: string;
  clicks: number; impressions: number; ranking: string | null };
type Evidence = { provider: string; method: string; origin: string; date_start: string; date_end: string;
  source_sha256: string; timezone: string; coverage: string; rows: Row[] };
type Import = { id: number; project_id: number; handler: string; status: string; created_at: string;
  updated_at: string; error_category: string; source_current: boolean; cancel_requested: boolean; evidence: Evidence | null };
type Page = { project_id: number; method: string; can_import: boolean; origins: string[]; jobs: Import[]; next_before: number | null };
type Grant = YandexSyncGrant & { expires_at: string; scope: string; can_report_refresh_revoked: boolean };
type UnknownExchange = { id: number; origin: string; created_at: string; can_report_revoked: boolean };
type Consent = { project_id: number; can_manage: boolean; application_configured: boolean; has_more: boolean; grants: Grant[]; unknown_exchanges: UnknownExchange[] };

@Component({
  selector: 'app-project-yandex',
  imports: [RouterLink, ProjectYandexSync],
  template: `
    <section class="workspace-panel" lang="en" aria-labelledby="yandex-title">
      <h1 id="yandex-title">Yandex Webmaster exports and API history</h1>
      <p><a [routerLink]="['/app/dashboard', organizationId, projectId]">Return to project dashboard</a></p>
      <p>Import an authorized advanced query-by-URL CSV export. Yandex data stays separate from Google data.
        Connect a verified origin with read-only Yandex consent for bounded aggregate history. Indexing and sitemap operations are unavailable here.</p>
      <p><a href="https://yandex.ru/support/webmaster/en/service/queries-export" target="_blank" rel="noopener noreferrer">Official export instructions (opens a new tab)</a></p>
      @if (loading()) { <p role="status">Loading current project access and import history.</p> }
      @if (error()) { <p role="alert">{{ error() }}</p> }
      @if (message()) { <p role="status">{{ message() }}</p> }
      @if (page(); as data) {
        <h2>Yandex connection</h2>
        @if (consent(); as auth) {
          @if (auth.can_manage && auth.application_configured) {
            <form (submit)="connect($event)">
              <label for="yandex-consent-origin">Origin to authorize</label>
              <select id="yandex-consent-origin" name="origin" required>
                @for (origin of data.origins; track origin) { <option [value]="origin">{{ origin }}</option> }
              </select>
              <p>Continue to Yandex to grant read-only site-information access. The selected origin must be verified in Yandex Webmaster.
                Tokens stay encrypted on the server. API history uses separate, explicitly budgeted requests below.</p>
              <button type="submit" [disabled]="busy() || loading()">Continue to Yandex</button>
            </form>
          } @else if (!auth.application_configured) { <p>The platform operator has not configured the Yandex application yet. CSV imports remain available.</p> }
          <ul>@for (grant of auth.grants; track grant.id) {
            <li>{{ grant.origin }} · {{ grant.state }} · token expiry {{ grant.expires_at }}
              @if (auth.can_manage && grant.state !== 'revoked' && !grant.refresh_unknown) {
                <button type="button" [disabled]="busy() || loading()" (click)="disconnect(grant)">Disconnect grant {{ grant.id }}</button>
              }
              @if (grant.state === 'revocation_pending') { <p>Local use is disabled. Remote revocation remains unconfirmed; retry disconnect.</p> }
              @if (grant.refresh_unknown) {
                <p role="status">Token refresh is pending or has an unknown outcome. Local source use is disabled; it will not retry automatically.</p>
                @if (auth.can_manage && grant.can_report_refresh_revoked) {
                  <form (submit)="reportRevoked($event, grant.id, true)">
                    <p>Revoke this application's access in the authorizing Yandex account first. This records your report, not provider verification.</p>
                    <label><input name="confirmed" type="checkbox" required> I completed remote revocation in the authorizing Yandex account.</label>
                    <label [for]="'yandex-refresh-password-' + grant.id">Current OrganicSEOOps password</label>
                    <input [id]="'yandex-refresh-password-' + grant.id" name="password" type="password" autocomplete="current-password" required>
                    <button type="submit" [disabled]="busy() || loading()">Record completed remote revocation</button>
                  </form>
                } @else { <p>Wait at least ten minutes from refresh initiation, then refresh connection status before recording completed remote revocation.</p> }
              }
            </li>
          } @empty { <li>No active or pending Yandex grants.</li> }</ul>
          @if (auth.has_more) { <p>Only the newest 20 active or pending grants are shown. Disconnect and refresh to reach older pending records.</p> }
          <app-project-yandex-sync [organizationId]="organizationId" [projectId]="projectId"
            [canManage]="auth.can_manage" [grants]="auth.grants" [requestKeys]="syncRequestKeys" />
          @for (exchange of auth.unknown_exchanges; track exchange.id) {
            <p role="status">Consent {{ exchange.id }} for {{ exchange.origin }} has an unknown token-exchange outcome.
              It may have issued a remote token. This state does not expire automatically and blocks application rotation and customer deletion.</p>
            @if (auth.can_manage && exchange.can_report_revoked) {
              <form (submit)="reportRevoked($event, exchange.id)">
                <p>In the Yandex account that authorized this request, revoke this application's access on the data-access rights page first.
                  This records your report, not independent provider verification.</p>
                <label><input type="checkbox" name="confirmed" required> I completed remote revocation in the authorizing Yandex account.</label>
                <label [for]="'yandex-report-password-' + exchange.id">Current OrganicSEOOps password</label>
                <input [id]="'yandex-report-password-' + exchange.id" name="password" type="password" autocomplete="current-password" required>
                <button type="submit" [disabled]="busy() || loading()">Record completed remote revocation</button>
              </form>
            } @else if (!exchange.can_report_revoked) { <p>Wait at least ten minutes after the exchange started, then refresh before recording completed remote revocation.</p> }
          }
        } @else { <p>Connection status unavailable. Refresh before starting or disconnecting consent.</p> }
        @if (data.can_import) {
          <form #uploadForm (submit)="upload($event)">
            <label for="yandex-origin">Exact project origin</label>
            <select id="yandex-origin" name="origin" required>
              @for (origin of data.origins; track origin) { <option [value]="origin">{{ origin }}</option> }
            </select>
            <label for="yandex-start">Inclusive export start</label><input id="yandex-start" name="start" type="date" required>
            <label for="yandex-end">Inclusive export end</label><input id="yandex-end" name="end" type="date" required>
            <label for="yandex-file">UTF-8 CSV export</label><input id="yandex-file" name="file" type="file" accept=".csv,text/csv" required>
            <p>At most 1 MiB, 100 rows and 24 KiB of parsed evidence; split larger exports before uploading.
              Use the eight official English or Russian headers, comma or semicolon separators and YYYY-MM-DD dates.
              Required columns: Date, Host, URL, Query, Region, Clicks, Impressions, Ranking.
              Every URL and host must match the selected origin. Raw CSV and file names are not stored.</p>
            <label><input name="authorized" type="checkbox" required> I am authorized to import this Yandex export for this project.</label>
            <button type="submit" [disabled]="busy() || loading()">Import · maximum 1 internal unit</button>
          </form>
        } @else { <p>Importing requires current project management and job-launch access. Existing evidence remains available to project readers.</p> }
        <h2>Import history</h2>
        <ul>@for (job of data.jobs; track job.id) {
          <li>Import {{ job.id }} · {{ job.status }} · {{ job.created_at }}
            @if (job.error_category) { <p>Import unavailable: {{ job.error_category }}. Check access and allowance before a new upload.</p> }
            @if (!job.source_current) { <p>Original uploader authority or project origin is no longer current. Evidence is withheld.</p> }
            @if (job.cancel_requested) { <p>Cancellation requested.</p> }
            @if (job.status === 'succeeded' && job.source_current) {
              <button type="button" [disabled]="busy()" (click)="inspect(job.id)">Inspect import {{ job.id }}</button>
            }
            @if ((job.status === 'queued' || job.status === 'running') && data.can_import) {
              <button type="button" [disabled]="busy()" (click)="cancel(job.id)">Cancel import {{ job.id }}</button>
            }
          </li>
        } @empty { <li>No imports on this page. Missing data is unknown, not zero traffic.</li> }</ul>
        @if (data.next_before !== null) { <button type="button" [disabled]="busy()" (click)="load(data.next_before)">Older imports</button> }
        @if (before !== null) { <button type="button" [disabled]="busy()" (click)="load()">Newest imports</button> }
      }
      @if (selected(); as job) {
        @if (job.evidence; as evidence) {
          <h2>Import {{ job.id }} · {{ evidence.origin }}</h2>
          <p>{{ evidence.date_start }} through {{ evidence.date_end }}, inclusive · {{ evidence.rows.length }} exported rows.
            Source calendar timezone is unspecified. This may be a filtered, partial export, not complete search coverage.
            Region and ranking retain Yandex definitions. Missing ranking is unavailable; averages are not combined.</p>
          <p>Method: {{ evidence.method }} · SHA-256: {{ evidence.source_sha256 }} · imported {{ job.created_at }}.
            These are customer-supplied observations, not verified live provider access or indexing proof.</p>
          <div class="table-scroll" role="region" aria-label="Yandex export rows" tabindex="0">
            <table><caption>Original date, URL, query and region grain</caption>
              <thead><tr><th scope="col">Date</th><th scope="col">URL</th><th scope="col">Query</th><th scope="col">Region</th><th scope="col">Clicks</th><th scope="col">Impressions</th><th scope="col">Ranking</th></tr></thead>
              <tbody>@for (row of evidence.rows.slice(rowPage() * 20, (rowPage() + 1) * 20); track $index) {
                <tr><td>{{ row.date }}</td><td>{{ row.url }}</td><td>{{ row.query }}</td><td>{{ row.region }}</td><td>{{ row.clicks }}</td><td>{{ row.impressions }}</td><td>{{ row.ranking ?? 'Unavailable' }}</td></tr>
              }</tbody>
            </table>
          </div>
          <p>Rows {{ rowPage() * 20 + 1 }}–{{ endRow(evidence) }} of {{ evidence.rows.length }}.</p>
          <button type="button" [disabled]="rowPage() === 0" (click)="rowPage.set(rowPage() - 1)">Previous rows</button>
          <button type="button" [disabled]="(rowPage() + 1) * 20 >= evidence.rows.length" (click)="rowPage.set(rowPage() + 1)">Next rows</button>
        }
      }
      <button type="button" [disabled]="busy() || loading()" (click)="load(before)">Refresh access and history</button>
    </section>`,
  styles: `section { overflow-wrap:anywhere } form { display:grid; gap:.65rem; max-width:46rem } li { margin-block:1rem } button { margin:.5rem } .table-scroll { overflow:auto } table { border-collapse:collapse } th,td { padding:.5rem; border:1px solid currentColor; text-align:start; vertical-align:top }`,
})
export class ProjectYandex implements OnInit {
  @ViewChild('uploadForm') uploadForm?: ElementRef<HTMLFormElement>;
  organizationId = 0; projectId = 0; before: number | null = null;
  private generation = 0;
  private pending: { fingerprint: string; key: string } | null = null;
  readonly syncRequestKeys = new Map<string, string>();
  readonly page = signal<Page | null>(null); readonly selected = signal<Import | null>(null);
  readonly consent = signal<Consent | null>(null);
  readonly loading = signal(false); readonly busy = signal(false); readonly error = signal(''); readonly message = signal('');
  readonly rowPage = signal(0);
  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi, private readonly destroy: DestroyRef) {}
  ngOnInit() {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroy)).subscribe((params) => {
      this.clear(); this.pending = null;
      this.syncRequestKeys.clear();
      this.organizationId = Number(params.get('organizationId')); this.projectId = Number(params.get('projectId'));
      void this.load();
    });
    this.destroy.onDestroy(() => this.clear());
  }
  private clear() {
    ++this.generation; this.page.set(null); this.selected.set(null); this.consent.set(null); this.rowPage.set(0);
    this.busy.set(false); this.loading.set(false); this.error.set(''); this.message.set('');
    this.uploadForm?.nativeElement.reset();
  }
  @HostListener('document:visibilitychange') hidden() {
    if (document.hidden) { this.clear(); this.message.set('Private data cleared while hidden. Refresh to recheck access.'); }
  }
  endRow(evidence: Evidence) { return Math.min((this.rowPage() + 1) * 20, evidence.rows.length); }
  private validJob(value: unknown): value is Import {
    if (!value || typeof value !== 'object') return false;
    const job = value as Import;
    return Number.isSafeInteger(job.id) && job.id > 0 && job.project_id === this.projectId
      && job.handler === 'import_yandex_webmaster_csv' && typeof job.source_current === 'boolean'
      && typeof job.status === 'string' && typeof job.created_at === 'string'
      && (!job.evidence || job.status === 'succeeded' && job.source_current
        && job.evidence.provider === 'yandex_webmaster' && job.evidence.method === 'yandex-query-url-csv-v1'
        && this.page()?.origins.includes(job.evidence.origin) === true
        && Array.isArray(job.evidence.rows) && job.evidence.rows.length <= 100
        && job.evidence.rows.every((row) => row && typeof row.date === 'string' && typeof row.url === 'string'
          && typeof row.query === 'string' && typeof row.region === 'string'
          && Number.isSafeInteger(row.clicks) && row.clicks >= 0 && Number.isSafeInteger(row.impressions) && row.impressions >= 0
          && (row.ranking === null || typeof row.ranking === 'string')));
  }
  async load(before: number | null = null) {
    if (document.hidden || this.destroy.destroyed) { this.clear(); return; }
    if (![this.organizationId, this.projectId].every((id) => Number.isSafeInteger(id) && id > 0)) {
      this.clear(); this.error.set('Choose a valid organization and project.'); return;
    }
    this.clear(); this.before = before; const generation = this.generation; this.loading.set(true);
    try {
      const [response, consentResponse] = await Promise.all([
        this.api.yandexImports(this.organizationId, this.projectId, 0, before),
        this.api.yandexGrants(this.organizationId, this.projectId).catch(() => null),
      ]);
      if (generation !== this.generation || document.hidden || this.destroy.destroyed) return;
      const page = response.body as unknown as Page;
      if (response.status !== 200 || page.project_id !== this.projectId || page.method !== 'yandex-query-url-csv-v1'
        || typeof page.can_import !== 'boolean' || !Array.isArray(page.origins) || page.origins.length > 100
        || !page.origins.every((origin) => typeof origin === 'string') || !Array.isArray(page.jobs) || page.jobs.length > 20
        || !page.jobs.every((job) => this.validJob(job) && job.evidence === null)
        || page.next_before !== null && (!Number.isSafeInteger(page.next_before) || page.next_before < 1)) throw new Error();
      this.page.set(page);
      const auth = consentResponse?.body as unknown as Consent | undefined;
      if (consentResponse?.status === 200 && auth?.project_id === this.projectId && typeof auth.can_manage === 'boolean'
        && typeof auth.application_configured === 'boolean' && typeof auth.has_more === 'boolean'
        && Array.isArray(auth.grants) && auth.grants.length <= 20
        && Array.isArray(auth.unknown_exchanges) && auth.unknown_exchanges.length <= 20
        && auth.unknown_exchanges.every((item) => Number.isSafeInteger(item.id) && item.id > 0 && typeof item.origin === 'string'
          && typeof item.created_at === 'string' && typeof item.can_report_revoked === 'boolean')
        && auth.grants.every((grant) => Number.isSafeInteger(grant.id) && grant.id > 0
          && typeof grant.origin === 'string' && Number.isSafeInteger(grant.revision) && grant.revision >= 0
          && ['active', 'reconnect_required', 'revocation_pending', 'revoked'].includes(grant.state)
          && typeof grant.refresh_unknown === 'boolean' && typeof grant.can_report_refresh_revoked === 'boolean'
          && typeof grant.suggested_start === 'string' && typeof grant.suggested_end === 'string'
          && (grant.cursor === null || typeof grant.cursor === 'object')
          && grant.scope === 'webmaster:hostinfo' && typeof grant.expires_at === 'string')) this.consent.set(auth);
    } catch { if (generation === this.generation) this.error.set('Import history unavailable. Refresh to recheck project access.'); }
    finally { if (generation === this.generation) this.loading.set(false); }
  }
  async connect(event: Event) {
    event.preventDefault();
    if (this.busy() || document.hidden || this.destroy.destroyed || !this.consent()?.can_manage) return;
    const origin = String(new FormData(event.target as HTMLFormElement).get('origin') ?? '');
    if (!this.page()?.origins.includes(origin)) return;
    const generation = this.generation; this.busy.set(true); this.error.set(''); this.selected.set(null);
    try {
      const response = await this.api.startYandexConsent(this.organizationId, this.projectId, origin);
      if (generation !== this.generation || document.hidden || this.destroy.destroyed) return;
      const value = response.body['authorization_url'];
      if (response.status !== 200 || typeof value !== 'string') throw new Error();
      const url = new URL(value);
      if (url.origin !== 'https://oauth.yandex.ru' || url.pathname !== '/authorize' || url.hash || url.username || url.password
        || url.searchParams.get('scope') !== 'webmaster:hostinfo' || url.searchParams.get('code_challenge_method') !== 'S256') throw new Error();
      window.location.assign(url.href);
    } catch { if (generation === this.generation) this.error.set('Consent could not be started. Refresh access, origin and connection configuration.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  async disconnect(grant: Grant) {
    if (this.busy() || document.hidden || this.destroy.destroyed || !this.consent()?.can_manage) return;
    const generation = this.generation; this.busy.set(true); this.error.set(''); this.selected.set(null);
    try {
      const response = await this.api.revokeYandexGrant(this.organizationId, this.projectId, grant.id, grant.revision);
      if (generation !== this.generation || document.hidden || this.destroy.destroyed) return;
      await this.load(this.before);
      if (generation + 1 === this.generation) this.message.set(response.status === 200
        ? 'Disconnect recorded. Review the current grant state.' : 'Disconnect is unconfirmed. Review pending status before retrying.');
    } catch {
      if (generation === this.generation) { this.consent.set(null); this.error.set('Disconnect is unconfirmed. Refresh connection status before retrying.'); }
    } finally { if (generation === this.generation) this.busy.set(false); }
  }
  async reportRevoked(event: Event, intentId: number, refresh = false) {
    event.preventDefault();
    if (this.busy() || document.hidden || this.destroy.destroyed || !this.consent()?.can_manage
      || !(refresh ? this.consent()?.grants.some((item) => item.id === intentId && item.refresh_unknown && item.can_report_refresh_revoked)
        : this.consent()?.unknown_exchanges.some((item) => item.id === intentId && item.can_report_revoked))) return;
    const form = event.target as HTMLFormElement; const data = new FormData(form);
    if (data.get('confirmed') !== 'on' || !form.reportValidity()) return;
    const generation = this.generation; this.busy.set(true); this.error.set(''); this.selected.set(null);
    try {
      const auth = await this.api.reauthenticate(String(data.get('password') ?? ''));
      form.reset();
      if (generation !== this.generation || document.hidden || this.destroy.destroyed) return;
      if (auth.status !== 200) throw new Error();
      const response = refresh ? await this.api.reportYandexRefreshRevoked(this.organizationId, this.projectId, intentId)
        : await this.api.reportYandexExchangeRevoked(this.organizationId, this.projectId, intentId);
      if (generation !== this.generation || document.hidden || this.destroy.destroyed) return;
      if (response.status !== 200 || response.body['project_id'] !== this.projectId
        || response.body['state'] !== 'user_reported_revoked_not_provider_verified') throw new Error();
      await this.load(this.before);
      if (generation + 1 === this.generation) this.message.set('Your completed-revocation report was recorded. Actual provider verification remains separate.');
    } catch { if (generation === this.generation) this.error.set('Revocation report was not confirmed. Reauthenticate and refresh the exchange status.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  async inspect(id: number) {
    if (this.busy() || document.hidden || this.destroy.destroyed) return;
    const generation = this.generation; this.busy.set(true); this.selected.set(null); this.error.set('');
    try {
      const response = await this.api.yandexImports(this.organizationId, this.projectId, id);
      if (generation !== this.generation || document.hidden || this.destroy.destroyed) return;
      const job = response.body['job'];
      if (response.status !== 200 || response.body['project_id'] !== this.projectId || !this.validJob(job) || job.id !== id || !job.evidence) throw new Error();
      this.rowPage.set(0); this.selected.set(job);
    } catch { if (generation === this.generation) { this.page.set(null); this.error.set('Evidence unavailable. Refresh to recheck current access and origin.'); } }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  async upload(event: Event) {
    event.preventDefault(); if (this.busy() || document.hidden || this.destroy.destroyed || !this.page()?.can_import) return;
    const form = event.target as HTMLFormElement; const data = new FormData(form); const file = data.get('file');
    if (!(file instanceof File) || file.size < 1 || file.size > 1048576 || data.get('authorized') !== 'on') {
      this.error.set('Choose an authorized CSV file of at most 1 MiB.'); return;
    }
    const origin = String(data.get('origin') ?? ''); const start = String(data.get('start') ?? ''); const end = String(data.get('end') ?? '');
    if (!this.page()?.origins.includes(origin) || !/^\d{4}-\d{2}-\d{2}$/.test(start) || !/^\d{4}-\d{2}-\d{2}$/.test(end)) return;
    const generation = this.generation; this.busy.set(true); this.selected.set(null); this.error.set(''); this.message.set('');
    try {
      const bytes = await file.arrayBuffer();
      const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), (byte) => byte.toString(16).padStart(2, '0')).join('');
      if (generation !== this.generation || document.hidden || this.destroy.destroyed) return;
      const fingerprint = JSON.stringify([this.organizationId, this.projectId, origin, start, end, hash]);
      const pending = this.pending?.fingerprint === fingerprint ? this.pending : { fingerprint, key: crypto.randomUUID() };
      this.pending = pending;
      const response = await this.api.uploadYandex(this.organizationId, this.projectId, new Blob([bytes]), {
        'X-Yandex-Origin': origin, 'X-Yandex-Start': start, 'X-Yandex-End': end,
        'X-Yandex-Authorization': 'true', 'X-Yandex-Request': pending.key,
      });
      if (generation !== this.generation || document.hidden || this.destroy.destroyed) return;
      const job = response.body['job'];
      if (response.status !== 202 || response.body['project_id'] !== this.projectId || !this.validJob(job)) {
        throw new Error(typeof response.body['error'] === 'string' ? response.body['error'] : 'Import could not be confirmed. Refresh history before another upload.');
      }
      form.reset(); await this.load();
      if (generation + 1 === this.generation) this.message.set(`Import ${job.id} recorded. Refresh history for worker completion.`);
    } catch (error) {
      if (generation === this.generation) this.error.set(error instanceof Error ? error.message : 'Import could not be confirmed. Refresh history before another upload.');
    } finally { if (generation === this.generation) this.busy.set(false); }
  }
  async cancel(id: number) {
    if (this.busy() || document.hidden || this.destroy.destroyed) return;
    const generation = this.generation; this.busy.set(true); this.error.set(''); this.selected.set(null);
    try {
      const response = await this.api.yandexImports(this.organizationId, this.projectId, id, null, true);
      if (generation !== this.generation || document.hidden || this.destroy.destroyed) return;
      if (response.status !== 200) throw new Error();
      await this.load(this.before);
    } catch { if (generation === this.generation) this.error.set('Cancellation could not be confirmed. Refresh history.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
}
