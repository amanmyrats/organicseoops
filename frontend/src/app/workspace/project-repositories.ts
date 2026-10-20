import { Component, DestroyRef, ElementRef, HostListener, OnInit, ViewChild, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi } from '../account/account-api';

type Connection = { id: number; project_id: number; repository: string; repository_id: number; commit_sha: string;
  state: string; revision: number; expires_at: string; source_current: boolean; created_at: string;
  can_report_revoked: boolean; revocation_evidence: string; permissions: { contents: string; metadata: string } };
type UnknownExchange = { id: number; repository: string; repository_id: number; commit_sha: string; can_report_revoked: boolean };
type Page = { project_id: number; method: string; can_manage: boolean; application_configured: boolean;
  analysis_available: boolean; connections: Connection[]; next_before: number | null;
  unknown_exchanges: UnknownExchange[]; has_more_unknown: boolean };
const validId = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value > 0;

@Component({
  selector: 'app-project-repositories', imports: [RouterLink],
  template: `
    <section class="workspace-panel" lang="en" aria-labelledby="repository-title">
      <h1 id="repository-title">Explicit read-only repository connections</h1>
      <p><a [routerLink]="['/app/dashboard', organizationId, projectId]">Return to project dashboard</a></p>
      <p>Authorize only a GitHub repository you may share and the exact commit you select. Credentials remain encrypted on the server.
        A connection grants no write, pull-request, merge or deployment permission. GitHub App access must be Contents:read and Metadata:read only.</p>
      <p>Connecting does not download, clone, scan or execute repository code or instructions.
        <a [routerLink]="['/app/repository-analysis', organizationId, projectId]">Select a separate read-only dependency or source observation</a> when isolated analysis is enabled.</p>
      @if (loading()) { <p role="status">Loading private project access and connection history.</p> }
      @if (error()) { <p role="alert">{{ error() }}</p> }
      @if (message()) { <p role="status">{{ message() }}</p> }
      @if (page(); as data) {
        @if (!data.analysis_available) { <p>Repository observations are disabled pending operator isolation configuration.</p> }
        @if (data.can_manage && data.application_configured) {
          <form #consentForm (submit)="connect($event)">
            <label for="repository-name">GitHub owner/repository</label><input id="repository-name" name="repository" maxlength="140" required autocomplete="off">
            <label for="repository-id">GitHub numeric repository ID</label><input id="repository-id" name="repository_id" type="number" min="1" step="1" required>
            <p>Use the repository's GitHub ID, not an installation or project ID. The callback verifies both name and ID; a redirect/rename does not silently change the selection.</p>
            <label for="repository-commit">Exact commit SHA (40 lowercase hexadecimal characters)</label><input id="repository-commit" name="commit_sha" minlength="40" maxlength="40" pattern="[0-9a-f]{40}" required autocomplete="off">
            <label><input name="acknowledge" type="checkbox" required> I am authorized to share this exact repository revision and authorize read-only access for this project.</label>
            <p>Continue to GitHub to choose an account. Install the operator's read-only GitHub App on the selected repository first.
              User credentials expire within eight hours and are not refreshed automatically. Expiry stops use but does not confirm remote grant revocation.</p>
            <button type="submit" [disabled]="busy() || loading()">Continue to GitHub for read-only consent</button>
          </form>
        } @else if (!data.application_configured) { <p>The platform operator has not configured the GitHub App yet.</p> }
        <h2>Repository connection history</h2>
        <p>Source status reflects the last consent proof and current local authority. Provider access, permissions and the exact commit must be rechecked before future code collection.</p>
        <ul>@for (row of data.connections; track row.id) {
          <li>Connection {{ row.id }} · {{ row.repository }} · repository ID {{ row.repository_id }} · {{ row.state }}
            <p>Commit {{ row.commit_sha }}. Credential expiry {{ row.expires_at }}. {{ row.source_current ? 'Local source authority current' : 'Source use unavailable' }}.</p>
            @if (row.revocation_evidence) { <p>Revocation evidence: {{ row.revocation_evidence }}.</p> }
            @if (data.can_manage && row.state !== 'revoked') {
              <p>Disconnect disables local use and requests deletion of this connection's access token only. Refresh-token revocation remains unconfirmed
                until GitHub reports revoked authorization or you report completed revocation in GitHub settings. A failed or expired-token response stays pending.</p>
              <button type="button" [disabled]="busy() || loading()" (click)="disconnect(row)">Disconnect connection {{ row.id }}</button>
              @if (row.can_report_revoked) {
                <form (submit)="report($event, row.id, false)">
                  <p>If automatic revocation cannot finish, revoke the application's access in the authorizing GitHub account's Settings → Applications first.
                    Revoking app authorization in GitHub also stops this user's app connections in other projects. This records your report, not provider confirmation.</p>
                  <label><input name="confirmed" type="checkbox" required> I completed remote revocation of this GitHub app authorization.</label>
                  <label [for]="'repository-password-' + row.id">Current OrganicSEOOps password</label>
                  <input [id]="'repository-password-' + row.id" name="password" type="password" autocomplete="current-password" required>
                  <button type="submit" [disabled]="busy() || loading()">Record completed remote revocation for connection {{ row.id }}</button>
                </form>
              } @else if (row.state === 'revocation_pending') { <p>Refresh after the ten-minute in-flight fence before reporting completed remote revocation.</p> }
            }
          </li>
        } @empty { <li>No connections on this page.</li> }</ul>
        @if (data.next_before !== null) { <button type="button" [disabled]="busy() || loading()" (click)="load(data.next_before)">Older connections</button> }
        @if (before !== null) { <button type="button" [disabled]="busy() || loading()" (click)="load()">Newest connections</button> }
        <h2>Unknown consent exchanges</h2>
        <p>An interrupted exchange is not presumed failed or repeated. Resolve it in the authorizing GitHub account before recording completed revocation.</p>
        <ul>@for (row of data.unknown_exchanges; track row.id) {
          <li>Consent {{ row.id }} · {{ row.repository }} · {{ row.commit_sha }}
            @if (data.can_manage && row.can_report_revoked) {
              <form (submit)="report($event, row.id, true)">
                <label><input name="confirmed" type="checkbox" required> I completed remote revocation of this app's authorization in the authorizing GitHub account.</label>
                <label [for]="'repository-unknown-password-' + row.id">Current OrganicSEOOps password</label>
                <input [id]="'repository-unknown-password-' + row.id" name="password" type="password" autocomplete="current-password" required>
                <button type="submit" [disabled]="busy() || loading()">Record completed revocation for consent {{ row.id }}</button>
              </form>
            } @else { <p>Current manager access and the ten-minute in-flight fence are required.</p> }
          </li>
        } @empty { <li>No unresolved exchange is listed.</li> }</ul>
        @if (data.has_more_unknown) { <p>Only the newest20 unknown exchanges are shown. Resolve and refresh to reach older ones.</p> }
      }
      <button type="button" [disabled]="busy() || loading()" (click)="load(before)">Refresh current access and connections</button>
    </section>`,
  styles: `section { overflow-wrap:anywhere } form { display:grid; gap:.65rem; max-width:48rem } li { margin-block:1.1rem } button { margin:.4rem }`,
})
export class ProjectRepositories implements OnInit {
  @ViewChild('consentForm') consentForm?: ElementRef<HTMLFormElement>;
  organizationId = 0; projectId = 0; before: number | null = null;
  private generation = 0;
  readonly page = signal<Page | null>(null); readonly loading = signal(false); readonly busy = signal(false);
  readonly error = signal(''); readonly message = signal('');
  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi, private readonly destroy: DestroyRef) {}
  ngOnInit() {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroy)).subscribe((params) => {
      this.clear(); this.organizationId = Number(params.get('organizationId')); this.projectId = Number(params.get('projectId')); void this.load();
    });
    this.destroy.onDestroy(() => this.clear());
  }
  private clear() {
    ++this.generation; this.consentForm?.nativeElement.reset(); this.page.set(null); this.loading.set(false);
    this.busy.set(false); this.error.set(''); this.message.set('');
  }
  private current(generation: number) { return generation === this.generation && !document.hidden && !this.destroy.destroyed; }
  @HostListener('document:visibilitychange') hidden() {
    if (document.hidden) { this.clear(); this.message.set('Private data cleared while hidden. Refresh access to continue.'); }
  }
  async load(before: number | null = null) {
    this.clear(); this.before = before;
    if (document.hidden || this.destroy.destroyed || !validId(this.organizationId) || !validId(this.projectId)) return;
    const generation = this.generation; this.loading.set(true);
    try {
      const response = await this.api.repositoryConnections(this.organizationId, this.projectId, before);
      if (!this.current(generation)) return;
      const data = response.body as unknown as Page;
      const source = (row: UnknownExchange) => row && validId(row.id) && typeof row.repository === 'string'
        && validId(row.repository_id) && typeof row.commit_sha === 'string' && /^[0-9a-f]{40}$/.test(row.commit_sha);
      if (response.status !== 200 || data.project_id !== this.projectId || data.method !== 'github-readonly-consent-v1'
        || typeof data.can_manage !== 'boolean' || typeof data.application_configured !== 'boolean' || typeof data.analysis_available !== 'boolean'
        || !Array.isArray(data.connections) || data.connections.length > 20
        || !data.connections.every((row) => source(row) && row.project_id === this.projectId
          && ['active', 'revocation_pending', 'revoked'].includes(row.state) && Number.isSafeInteger(row.revision) && row.revision >= 0
          && typeof row.source_current === 'boolean' && typeof row.can_report_revoked === 'boolean' && typeof row.expires_at === 'string'
          && typeof row.revocation_evidence === 'string' && row.permissions?.contents === 'read' && row.permissions.metadata === 'read')
        || !Array.isArray(data.unknown_exchanges) || data.unknown_exchanges.length > 20
        || !data.unknown_exchanges.every((row) => source(row) && typeof row.can_report_revoked === 'boolean')
        || typeof data.has_more_unknown !== 'boolean' || data.next_before !== null && !validId(data.next_before)) throw new Error();
      this.page.set(data);
    } catch { if (this.current(generation)) this.error.set('Repository connections unavailable. Refresh current project access.'); }
    finally { if (this.current(generation)) this.loading.set(false); }
  }
  async connect(event: Event) {
    event.preventDefault();
    if (this.busy() || document.hidden || !this.page()?.can_manage || !this.page()?.application_configured) return;
    const form = new FormData(event.target as HTMLFormElement);
    const generation = this.generation; this.busy.set(true); this.error.set('');
    try {
      const response = await this.api.repositoryConsent(this.organizationId, this.projectId, {
        repository: String(form.get('repository') ?? ''), repository_id: Number(form.get('repository_id')),
        commit_sha: String(form.get('commit_sha') ?? ''), acknowledge_read_only_access: form.get('acknowledge') === 'on' });
      if (!this.current(generation)) return;
      if (response.status !== 200 || response.body['project_id'] !== this.projectId || typeof response.body['authorization_url'] !== 'string') throw new Error();
      const url = new URL(response.body['authorization_url']);
      if (url.origin !== 'https://github.com' || url.pathname !== '/login/oauth/authorize' || url.username || url.password || url.hash
        || url.searchParams.get('scope') !== 'offline_access' || url.searchParams.get('code_challenge_method') !== 'S256') throw new Error();
      window.location.assign(url.href);
    } catch { if (this.current(generation)) this.error.set('Consent was not confirmed. Refresh connections; do not assume an interrupted exchange failed.'); }
    finally { if (this.current(generation)) this.busy.set(false); }
  }
  async disconnect(row: Connection) {
    if (this.busy() || document.hidden || !this.page()?.can_manage) return;
    const generation = this.generation; this.busy.set(true); this.error.set('');
    try {
      const response = await this.api.repositoryDisconnect(this.organizationId, this.projectId, row.id, row.revision);
      if (!this.current(generation)) return;
      if (response.status !== 200 || response.body['project_id'] !== this.projectId || response.body['grant_id'] !== row.id
        || !['revoked', 'revocation_pending'].includes(String(response.body['state']))) throw new Error();
      await this.load(this.before);
      if (this.current(generation + 1)) this.message.set('Disconnect result recorded. Review remaining connection and remote-revocation state.');
    } catch { if (this.current(generation)) this.error.set('Disconnect remains unconfirmed. Refresh; pending connections cannot be used.'); }
    finally { if (this.current(generation)) this.busy.set(false); }
  }
  async report(event: Event, sourceId: number, unknown: boolean) {
    event.preventDefault();
    if (this.busy() || document.hidden || !this.page()?.can_manage) return;
    const form = event.target as HTMLFormElement; const data = new FormData(form);
    if (data.get('confirmed') !== 'on') return;
    const generation = this.generation; this.busy.set(true); this.error.set('');
    try {
      const auth = await this.api.reauthenticate(String(data.get('password') ?? ''));
      form.reset();
      if (!this.current(generation)) return;
      if (auth.status !== 200) throw new Error();
      const response = await this.api.repositoryReportRevoked(this.organizationId, this.projectId, sourceId, unknown);
      if (!this.current(generation)) return;
      if (response.status !== 200 || response.body['project_id'] !== this.projectId
        || response.body['state'] !== (unknown ? 'user_reported_revoked_not_provider_verified' : 'revoked')) throw new Error();
      await this.load(this.before);
      if (this.current(generation + 1)) this.message.set('Your completed remote revocation was recorded as a human report, not provider verification.');
    } catch { if (this.current(generation)) this.error.set('Revocation report was not confirmed. Refresh access and inspect pending state.'); }
    finally { if (this.current(generation)) this.busy.set(false); }
  }
}
