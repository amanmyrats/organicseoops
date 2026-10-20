import { Component, DestroyRef, ElementRef, HostListener, OnInit, ViewChild, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi } from '../account/account-api';

type Grant = { id: number; revision: number; repository: string; repository_id: number; commit_sha: string; expires_at: string; source_current: boolean };
type Dependency = { manifest: string; ecosystem: string; group: string; name: string; constraint: string };
type Lockfile = { status: string; version: number | null; package_entries: number; supported_entries: number;
  retained_unique_packages: number; excluded_entries: number; omitted_unique_packages: number };
type AdvisoryRow = { ecosystem: string; name: string; version: string; dependency_indices: number[];
  advisories: { id: string; modified: string }[]; returned_count: number; complete: boolean };
type AdvisoryResult = { method: string; provider: string; queried_at: string; source_sha256: string | null; state: string;
  queried_packages: number; excluded_declarations: number; skipped_unique_pins: number; rows: AdvisoryRow[] };
type DependencyAnalysis = { method: string; manifests: { name: string; sha256: string }[]; dependencies: Dependency[];
  excluded_or_unsupported: number; lockfile?: Lockfile };
type CodeAnalysis = { method: string; manifests: { name: string; sha256: string }[]; rules: string[];
  coverage: { parse_state: string; line_count: number; node_count: number; observed_patterns: number; retained_observations: number; omitted_observations: number };
  observations: { rule: string; line: number; column: number }[] };
type Evidence = { method: string; tree_sha: string; collected_at: string; cleanup_confirmed: boolean;
  analysis: DependencyAnalysis | null; code_analysis: CodeAnalysis | null;
  advisories: AdvisoryResult | null };
type Job = { id: number; project_id: number; status: string; request_key: string; grant_id: number; operation: string;
  source_path: string | null;
  source: { provider: string; repository: string; repository_id: number; commit_sha: string }; source_current: boolean;
  created_at: string; error_category: string; cancel_requested: boolean; attempted_requests: number; maximum_requests: number;
  attempted_repository_requests: number; attempted_advisory_requests: number;
  cleanup: string; evidence: Evidence | null };
type Page = { project_id: number; method: string; available: boolean; advisories_available: boolean; can_manage: boolean; can_collect: boolean;
  grants: Grant[]; jobs: Job[]; next_before: number | null; next_grant_before: number | null };
const METHOD = 'repository-root-manifests-v1';
const ADVISORY_OPERATION = 'root_pinned_dependency_advisories';
const LOCK_OPERATION = 'root_npm_lockfile_advisories';
const LOCK_METHOD = 'repository-root-npm-lock-v1';
const CODE_OPERATION = 'selected_python_call_observations';
const CODE_METHOD = 'repository-python-call-syntax-v1';
const CODE_RULES = ['eval_call_syntax', 'exec_call_syntax', 'subprocess_shell_true_syntax', 'pickle_load_call_syntax'];
const ADVISORY_OPERATIONS = [ADVISORY_OPERATION, LOCK_OPERATION];
const FILES = ['package.json', 'pyproject.toml', 'requirements.txt'];
const id = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value > 0;
const text = (value: unknown): value is string => typeof value === 'string';
const sha = (value: unknown) => text(value) && /^[0-9a-f]{40}$/.test(value);
const sourcePath = (value: unknown): value is string => text(value) && value.length > 0 && value.length <= 240 && value.endsWith('.py')
  && value.split('/').length <= 6 && value.split('/').every((part) => /^[A-Za-z0-9_][A-Za-z0-9_.-]{0,59}$/.test(part));

@Component({
  selector: 'app-project-repository-analysis', imports: [RouterLink],
  template: `
    <section class="workspace-panel" lang="en" aria-labelledby="repository-analysis-title">
      <h1 id="repository-analysis-title">Read-only repository observations</h1>
      <p><a [routerLink]="['/app/dashboard', organizationId, projectId]">Return to project dashboard</a> ·
        <a [routerLink]="['/app/repositories', organizationId, projectId]">Manage repository consent</a></p>
      <p>Choose declared dependencies from root package.json/pyproject.toml/requirements.txt, or recorded versions from root npm package-lock.json v2/v3,
        or select one Python source file at an authorized GitHub commit. A disposable offline environment parses the selected source. Optional OSV lookup checks supported exact versions.
        Installed files, lockfile/manifest consistency, reachability and whole-repository security remain unassessed.
        Repository scripts, installers and code agents are never executed by these operations.</p>
      <p>Inventory reserves13 internal usage units for at most13 GitHub reads. Declared-pin advisory lookup reserves14 units; the single-lockfile mode reserves12 (11GitHub+1OSV).
        Selected Python analysis reserves10 plus the number of path segments, at most16 GitHub reads, with no OSV/model request.
        Actual attempted requests consume units even if analysis fails or is cancelled.
        Raw manifests are temporary; only filtered structured results and source fingerprints are retained.</p>
      @if (error()) { <p role="alert">{{ error() }}</p> }
      @if (message()) { <p role="status">{{ message() }}</p> }
      @if (loading()) { <p role="status">Loading private project access and analysis history.</p> }
      @if (page(); as data) {
        @if (!data.available) { <p>Collection is disabled until the operator configures the reviewed isolated controller.</p> }
        @if (data.available && data.can_manage && data.can_collect) {
          <form #selectionForm (submit)="submit($event)">
            <label for="analysis-operation">Collection choice</label>
            <select id="analysis-operation" name="operation" (change)="chooseOperation($event)">
              <option value="root_dependency_inventory">Root dependency inventory only</option>
              <option value="root_pinned_dependency_advisories" [disabled]="!data.advisories_available">Inventory and OSV advisory lookup for exact declared pins</option>
              <option value="root_npm_lockfile_advisories" [disabled]="!data.advisories_available">Root npm lockfile and OSV advisory lookup</option>
              <option value="selected_python_call_observations">One Python file: limited static call observations</option>
            </select>
            <label for="analysis-grant">Exact read-only repository consent</label>
            <select id="analysis-grant" name="grant" required>
              <option value="">Choose a current consent</option>
              @for (grant of data.grants; track grant.id) {
                <option [value]="grant.id" [disabled]="!grant.source_current">{{ grant.repository }} · {{ grant.commit_sha }} · consent {{ grant.id }} · expires {{ grant.expires_at }}</option>
              }
            </select>
            @if (operation() === 'root_npm_lockfile_advisories') {
              <p>Read only root package-lock.json, up to512KiB/5000 package entries. Retain up to50 unique supported public-registry package/version pairs,
                including recorded hoisted or nested dependencies. Exclude links, workspaces, ambiguous aliases and git/private/nonstandard tarball records.
                URLs and paths are parsed as text, never fetched or executed. Other lockfile formats remain unavailable.</p>
            }
            @if (operation() === 'selected_python_call_observations') {
              <label for="analysis-source-path">Exact relative Python file path</label>
              <input id="analysis-source-path" name="source_path" maxlength="240" required autocomplete="off" placeholder="src/example.py">
              <p>Select one UTF8 .py file up to128KiB and six path segments. Observe literal eval/exec calls, subprocess shell=True and pickle.load/loads call syntax.
                Aliases, shadowed names, data/control flow and exploitability are not resolved. No code, arguments or snippets are retained; only fixed rule IDs, locations and source fingerprint.
                The file is never imported/executed or sent to a model/OSV. Symlinks/submodules are not followed.</p>
            }
            <label><input name="acknowledge" type="checkbox" required> {{ operation() === 'selected_python_call_observations'
              ? 'I am authorized to share the selected Python file and request only these bounded read-only syntax observations.'
              : operation() === 'root_npm_lockfile_advisories'
              ? 'I authorize this exact commit’s root package-lock.json to be collected and parsed under these read-only limits.'
              : 'I authorize this exact commit’s three supported root manifests to be collected and parsed under these read-only limits.' }}</label>
            @if (operation() === 'root_pinned_dependency_advisories' || operation() === 'root_npm_lockfile_advisories') {
              <p>Send up to50 unique supported exact package names, ecosystems and versions to Google's public OSV service.
                Package names may identify your organization and private technology choices. Only filtered package ecosystem/name/version fields are sent,
                with no separate repository identity/commit fields, raw file or platform access credential.
                Unsupported declarations/lock records and versions are excluded. Returned advisory identifiers can overlap; they are not unique CVE counts or proof of exploitability.</p>
              <label><input name="disclose" type="checkbox" required> I am authorized to disclose these package names/versions to OSV and request this bounded advisory lookup.</label>
            }
            <button type="submit" [disabled]="busy() || loading()">Collect selected analysis</button>
          </form>
        } @else if (!data.can_collect) { <p>New collection requires current manager access and an active organization allowance. History remains available to project readers.</p> }
        <p>Consent and provider access are rechecked before collection and delivery. Source status shown here is from the last refresh.
          Expired or revoked consent withholds results; renew consent and explicitly collect again when needed.</p>
        @if (data.next_grant_before !== null) { <button type="button" [disabled]="busy()" (click)="load(before, data.next_grant_before)">Older active consents</button> }
        <h2>Analysis history</h2>
        <ul>@for (job of data.jobs; track job.id) {
          <li>Analysis {{ job.id }} · {{ job.status }} · {{ job.source.repository }} · {{ job.created_at }}
            <p>{{ job.operation === 'selected_python_call_observations' ? 'Selected Python call-syntax observations'
              : job.operation === 'root_npm_lockfile_advisories' ? 'Root npm lockfile and OSV advisory lookup'
              : job.operation === 'root_pinned_dependency_advisories' ? 'Root inventory and OSV advisory lookup' : 'Root inventory only' }}.</p>
            @if (job.source_path) { <p>Selected file: {{ job.source_path }}.</p> }
            <p>Commit {{ job.source.commit_sha }}. Request key {{ job.request_key }}.
              Attempted requests {{ job.attempted_requests }}/{{ job.maximum_requests }} (GitHub {{ job.attempted_repository_requests }}, OSV {{ job.attempted_advisory_requests }}).
              Disposable environment cleanup: {{ job.cleanup }}. {{ job.error_category }}</p>
            @if (job.cleanup === 'pending') { <p>Cleanup is unconfirmed. This job and further collection remain blocked until the dedicated controller confirms removal.</p> }
            @if (job.source_current) { <button type="button" [disabled]="busy()" (click)="inspect(job.id)">Inspect analysis {{ job.id }}</button> }
            @else { <p>Original repository consent is no longer current; evidence is withheld.</p> }
            @if (data.can_manage && (job.status === 'queued' || job.status === 'running')) {
              <button type="button" [disabled]="busy()" (click)="cancel(job.id)">Cancel analysis {{ job.id }}</button>
              @if (job.cancel_requested) { <p>Cancellation requested. In-flight reads can complete; environment cleanup is still required.</p> }
            }
          </li>
        } @empty { <li>No analysis on this page.</li> }</ul>
        @if (data.next_before !== null) { <button type="button" [disabled]="busy()" (click)="load(data.next_before, grantBefore)">Older analyses</button> }
        @if (before !== null || grantBefore !== null) { <button type="button" [disabled]="busy()" (click)="load()">Newest history and consents</button> }
        @for (key of pending(); track key) { <p>Unconfirmed request {{ key }}. <button type="button" [disabled]="busy()" (click)="find(key)">Look up this request without collecting again</button></p> }
      }
      @if (selected(); as job) {
        <h2>Analysis {{ job.id }} · {{ job.source.repository }}</h2>
        @if (job.evidence; as evidence) {
          <p>Commit {{ job.source.commit_sha }}; tree {{ evidence.tree_sha }}; collected {{ evidence.collected_at }}.
            Cleanup confirmed.</p>
          @if (evidence.code_analysis; as code) {
            <h3>Selected Python syntax observations</h3>
            <p>{{ job.source_path }} · {{ code.coverage.parse_state }}. Rule set: {{ code.rules.join(', ') }}.</p>
            <ul>@for (file of code.manifests; track file.name) { <li>{{ file.name }} · SHA256 {{ file.sha256 }}</li> }</ul>
            @if (code.coverage.parse_state !== 'parsed') { <p>The file was missing or could not be parsed under this Python grammar. Assessment is unavailable.</p> }
            @else {
              <p>Parsed {{ code.coverage.line_count }} lines / {{ code.coverage.node_count }} syntax nodes.
                Observed patterns: {{ code.coverage.observed_patterns }}; retained {{ code.coverage.retained_observations }}; omitted {{ code.coverage.omitted_observations }}.</p>
              @if (code.coverage.omitted_observations) { <p>Only the first100 locations are retained; results are partial.</p> }
              <ul>@for (row of code.observations; track $index) { <li>{{ row.rule }} · line {{ row.line }}, UTF8 byte column {{ row.column }} (one-based).</li> }
                @empty { <li>No listed call pattern was observed. This is not a passing security assessment.</li> }</ul>
              <p>These are literal call-syntax observations requiring human source review. Names may be shadowed; aliases/indirect calls and data/control flow are unassessed.
                No vulnerability, severity, exploitability, fix or approval is established. No repository code was executed.</p>
            }
          }
          @if (evidence.analysis; as analysis) {
          <p>Excluded, unsupported or omitted source items: {{ analysis.excluded_or_unsupported }}.</p>
          <ul>@for (manifest of analysis.manifests; track manifest.name) { <li>{{ manifest.name }} · SHA256 {{ manifest.sha256 }}</li> }
            @empty { <li>No selected supported source file was present. This says nothing about other files.</li> }</ul>
          @if (analysis.lockfile; as lock) {
            @if (lock.status === 'missing') { <p>Root package-lock.json was not present at the selected commit; lockfile dependency assessment is unavailable.</p> }
            @else {
              <p>Lockfile format {{ lock.version }} · {{ lock.status }}. Non-root package entries: {{ lock.package_entries }};
                supported public-registry entries: {{ lock.supported_entries }}; retained unique name/version pairs: {{ lock.retained_unique_packages }}.
                Excluded entries: {{ lock.excluded_entries }}; supported unique pairs beyond the50-pair limit: {{ lock.omitted_unique_packages }}.</p>
              <p>These versions are reported by the selected lockfile. This operation does not read package.json, verify consistency with it or inspect installed packages.</p>
            }
          }
          <div class="table-scroll" role="region" aria-label="Declared root dependencies" tabindex="0"><table>
            <caption>Filtered declared constraints or lockfile-reported versions; presence is not an installed-version assertion</caption>
            <thead><tr><th scope="col">Source file</th><th scope="col">Ecosystem/group</th><th scope="col">Dependency</th><th scope="col">Constraint/reported version</th></tr></thead>
            <tbody>@for (row of analysis.dependencies; track $index) { <tr><td>{{ row.manifest }}</td><td>{{ row.ecosystem }} · {{ row.group }}</td><td>{{ row.name }}</td><td>{{ row.constraint }}</td></tr> }
              @empty { <tr><td colspan="4">No supported dependency records returned. Unsupported/private source records remain gaps.</td></tr> }</tbody>
          </table></div>
          @if (evidence.advisories; as advisory) {
            <h3>OSV advisory matches for supported versions</h3>
            <p>Queried {{ advisory.queried_packages }} unique package versions at {{ advisory.queried_at }}.
              Retained source records without a supported exact query version: {{ advisory.excluded_declarations }}.
              Exact unique pins beyond the50-package bound: {{ advisory.skipped_unique_pins }}.</p>
            @if (advisory.state === 'no_exact_pins') { <p>No supported exact versions were available; no OSV request was sent. Vulnerability status is unavailable.</p> }
            @else if (advisory.state === 'partial') { <p>Coverage is partial. Unsupported declarations, package limits or truncated/provider-paginated results leave gaps.</p> }
            @else { <p>The returned batch is complete only for the queried supported pins. This is not a clean-repository or complete-security result.</p> }
            <p>Advisory IDs are provider-reported matches, with no severity/fix/installed-version/exploitability assertion. Review the source advisories before proposing changes.</p>
            <ul>@for (row of advisory.rows; track $index) {
              <li>{{ row.ecosystem }} · {{ row.name }} · {{ job.operation === 'root_npm_lockfile_advisories' ? 'lockfile-reported version' : 'declared version' }} {{ row.version }}.
                Returned IDs on this provider page: {{ row.returned_count }}. {{ row.complete ? 'All returned IDs retained; no further provider page reported.' : 'Incomplete IDs; pagination or retention limit applies.' }}
                <ul>@for (item of row.advisories; track item.id) { <li>{{ item.id }} · provider record modified {{ item.modified }}</li> }
                  @empty { <li>{{ row.complete ? 'No advisory match returned for this queried pin at collection time.' : 'No retained IDs; coverage is incomplete.' }}</li> }</ul>
              </li>
            } @empty { <li>No packages were queried.</li> }</ul>
            @if (advisory.source_sha256) { <p>Private OSV response fingerprint {{ advisory.source_sha256 }}. No automatic follow-up page or advisory request is made.</p> }
          }
          }
        } @else { <p>No deliverable result is available. {{ job.error_category }}</p> }
      }
      <button type="button" [disabled]="busy() || loading()" (click)="load(before, grantBefore)">Refresh current access and history</button>
    </section>`,
  styles: `section { overflow-wrap:anywhere } form { display:grid; gap:.6rem; max-width:48rem } li { margin-block:1rem } button { margin:.4rem } .table-scroll { overflow:auto } table { border-collapse:collapse } th,td { border:1px solid currentColor; padding:.5rem; text-align:start; vertical-align:top }`,
})
export class ProjectRepositoryAnalysis implements OnInit {
  @ViewChild('selectionForm') form?: ElementRef<HTMLFormElement>;
  organizationId = 0; projectId = 0; before: number | null = null; grantBefore: number | null = null;
  private generation = 0;
  readonly page = signal<Page | null>(null); readonly selected = signal<Job | null>(null);
  readonly operation = signal('root_dependency_inventory');
  readonly loading = signal(false); readonly busy = signal(false); readonly error = signal(''); readonly message = signal('');
  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi, private readonly destroy: DestroyRef) {}
  ngOnInit() {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroy)).subscribe((params) => {
      this.clear(); this.organizationId = Number(params.get('organizationId')); this.projectId = Number(params.get('projectId')); void this.load();
    });
    this.destroy.onDestroy(() => this.clear());
  }
  private clear() {
    ++this.generation; this.form?.nativeElement.reset(); this.page.set(null); this.selected.set(null);
    this.loading.set(false); this.busy.set(false); this.error.set(''); this.message.set(''); this.operation.set('root_dependency_inventory');
  }
  private current(generation: number) { return generation === this.generation && !document.hidden && !this.destroy.destroyed; }
  @HostListener('document:visibilitychange') hidden() {
    if (document.hidden) { this.clear(); this.message.set('Private data cleared while hidden. Refresh access to continue.'); }
  }
  pending() { return [...this.api.repositoryPendingRequests].filter(([scope]) => scope.startsWith(`${this.organizationId}:${this.projectId}:`)).map(([, key]) => key); }
  chooseOperation(event: Event) {
    this.operation.set((event.target as HTMLSelectElement).value);
    for (const name of ['acknowledge', 'disclose']) {
      const input = this.form?.nativeElement.elements.namedItem(name);
      if (input instanceof HTMLInputElement) input.checked = false;
    }
  }
  private validLockfile(value: Lockfile | undefined, count: number) {
    return !!value && ['missing', 'parsed', 'partial'].includes(value.status)
      && [value.package_entries, value.supported_entries, value.retained_unique_packages, value.excluded_entries, value.omitted_unique_packages]
        .every((number) => Number.isSafeInteger(number) && number >= 0 && number <= 5000)
      && value.retained_unique_packages === count && count <= 50
      && value.supported_entries + value.excluded_entries === value.package_entries
      && value.retained_unique_packages + value.omitted_unique_packages <= value.supported_entries
      && (value.status === 'missing' ? value.version === null && value.package_entries === 0 : value.version === 2 || value.version === 3);
  }
  private validAdvisories(value: AdvisoryResult | null, count: number, lockfile = false) {
    const nonnegative = (number: unknown): number is number => typeof number === 'number' && Number.isSafeInteger(number) && number >= 0;
    return !!value && value.method === (lockfile ? 'osv-root-npm-lock-v1' : 'osv-declared-root-pins-v1') && value.provider === 'osv' && text(value.queried_at)
      && ['no_exact_pins', 'partial', 'complete_for_queried_pins'].includes(value.state)
      && nonnegative(value.queried_packages) && value.queried_packages <= 50
      && nonnegative(value.excluded_declarations) && value.excluded_declarations <= count
      && nonnegative(value.skipped_unique_pins) && value.skipped_unique_pins <= count
      && (value.queried_packages === 0 ? value.state === 'no_exact_pins' && value.source_sha256 === null
        : text(value.source_sha256) && /^[0-9a-f]{64}$/.test(value.source_sha256))
      && Array.isArray(value.rows) && value.rows.length === value.queried_packages
      && value.rows.every((row) => row && ['npm', 'PyPI'].includes(row.ecosystem) && text(row.name) && text(row.version)
        && Array.isArray(row.dependency_indices) && row.dependency_indices.length > 0 && row.dependency_indices.length <= count
        && row.dependency_indices.every((index) => nonnegative(index) && index < count)
        && nonnegative(row.returned_count) && typeof row.complete === 'boolean'
        && Array.isArray(row.advisories) && row.advisories.length <= 10 && row.advisories.length <= row.returned_count
        && row.advisories.every((item) => item && text(item.id) && /^[A-Z][A-Za-z0-9._:-]{1,99}$/.test(item.id) && text(item.modified)))
      && value.rows.reduce((sum, row) => sum + row.advisories.length, 0) <= 100;
  }
  private validCode(value: CodeAnalysis | null, path: string | null) {
    if (!value || !sourcePath(path) || !value.coverage) return false;
    const coverage = value.coverage;
    return value.method === CODE_METHOD && Array.isArray(value.rules) && value.rules.length === CODE_RULES.length
      && value.rules.every((rule, index) => rule === CODE_RULES[index])
      && Array.isArray(value.manifests) && value.manifests.length <= 1
      && value.manifests.every((file) => file && file.name === path && /^[0-9a-f]{64}$/.test(file.sha256))
      && ['parsed', 'source_missing', 'syntax_unavailable'].includes(coverage.parse_state)
      && [coverage.line_count, coverage.node_count, coverage.observed_patterns, coverage.retained_observations, coverage.omitted_observations]
        .every((number) => Number.isSafeInteger(number) && number >= 0)
      && coverage.line_count <= 131073 && coverage.node_count <= 50000 && coverage.observed_patterns <= coverage.node_count
      && Array.isArray(value.observations) && value.observations.length <= 100
      && coverage.retained_observations === value.observations.length && coverage.retained_observations === Math.min(100, coverage.observed_patterns)
      && coverage.retained_observations + coverage.omitted_observations === coverage.observed_patterns
      && (coverage.parse_state === 'parsed' ? coverage.node_count > 0 : coverage.node_count === 0 && coverage.observed_patterns === 0)
      && (coverage.parse_state === 'source_missing' ? value.manifests.length === 0 && coverage.line_count === 0 : value.manifests.length === 1)
      && value.observations.every((row) => row && CODE_RULES.includes(row.rule) && Number.isSafeInteger(row.line)
        && row.line > 0 && row.line <= coverage.line_count && Number.isSafeInteger(row.column) && row.column > 0 && row.column <= 131073);
  }
  private validJob(job: Job) {
    const evidence = job?.evidence;
    const lockfile = job?.operation === LOCK_OPERATION;
    const code = job?.operation === CODE_OPERATION;
    const maximum = code ? 10 + (job.source_path?.split('/').length ?? 0) : lockfile ? 12 : job?.operation === ADVISORY_OPERATION ? 14 : 13;
    return job && id(job.id) && job.project_id === this.projectId && id(job.grant_id)
      && ['root_dependency_inventory', CODE_OPERATION, ...ADVISORY_OPERATIONS].includes(job.operation)
      && (code ? sourcePath(job.source_path) : job.source_path === null)
      && ['queued', 'running', 'succeeded', 'failed', 'cancelled'].includes(job.status) && text(job.request_key)
      && job.source?.provider === 'github' && text(job.source.repository) && id(job.source.repository_id) && sha(job.source.commit_sha)
      && typeof job.source_current === 'boolean' && text(job.created_at) && text(job.error_category) && typeof job.cancel_requested === 'boolean'
      && job.maximum_requests === maximum
      && Number.isSafeInteger(job.attempted_requests) && job.attempted_requests >= 0 && job.attempted_requests <= job.maximum_requests
      && Number.isSafeInteger(job.attempted_repository_requests) && job.attempted_repository_requests >= 0 && job.attempted_repository_requests <= (code ? maximum : lockfile ? 11 : 13)
      && Number.isSafeInteger(job.attempted_advisory_requests) && job.attempted_advisory_requests >= 0
      && job.attempted_advisory_requests <= (ADVISORY_OPERATIONS.includes(job.operation) ? 1 : 0)
      && job.attempted_requests === job.attempted_repository_requests + job.attempted_advisory_requests
      && ['not_started', 'pending', 'confirmed'].includes(job.cleanup)
      && (evidence === null || job.source_current && job.status === 'succeeded' && job.cleanup === 'confirmed'
        && evidence.method === METHOD && sha(evidence.tree_sha) && text(evidence.collected_at) && evidence.cleanup_confirmed === true
        && (code ? evidence.analysis === null && evidence.advisories === null && this.validCode(evidence.code_analysis, job.source_path)
        : evidence.code_analysis === null && evidence.analysis?.method === (lockfile ? LOCK_METHOD : METHOD) && Number.isSafeInteger(evidence.analysis.excluded_or_unsupported)
        && evidence.analysis.excluded_or_unsupported >= 0 && evidence.analysis.excluded_or_unsupported <= (lockfile ? 5000 : 3000)
        && Array.isArray(evidence.analysis.manifests) && evidence.analysis.manifests.length <= (lockfile ? 1 : 3)
        && evidence.analysis.manifests.every((row) => row && (lockfile ? row.name === 'package-lock.json' : FILES.includes(row.name)) && /^[0-9a-f]{64}$/.test(row.sha256))
        && Array.isArray(evidence.analysis.dependencies) && evidence.analysis.dependencies.length <= (lockfile ? 50 : 100)
        && evidence.analysis.dependencies.every((row) => row && (lockfile ? row.manifest === 'package-lock.json' && row.ecosystem === 'npm' && row.group === 'lockfile.packages'
          : FILES.includes(row.manifest) && ['npm', 'pypi'].includes(row.ecosystem))
          && [row.group, row.name, row.constraint].every(text))
        && (!lockfile || this.validLockfile(evidence.analysis.lockfile, evidence.analysis.dependencies.length))
        && (ADVISORY_OPERATIONS.includes(job.operation) ? this.validAdvisories(evidence.advisories, evidence.analysis.dependencies.length, lockfile) : evidence.advisories === null)));
  }
  async load(before: number | null = null, grantBefore: number | null = null, requestKey?: string) {
    this.clear(); this.before = before; this.grantBefore = grantBefore;
    if (document.hidden || this.destroy.destroyed || !id(this.organizationId) || !id(this.projectId)) return;
    const generation = this.generation; this.loading.set(true);
    try {
      const query: Record<string, string> = {};
      if (before !== null) query['before'] = String(before);
      if (grantBefore !== null) query['grant_before'] = String(grantBefore);
      if (requestKey) query['request_key'] = requestKey;
      const response = await this.api.repositoryAnalysis(this.organizationId, this.projectId, 0, undefined, query);
      if (!this.current(generation)) return;
      const data = response.body as unknown as Page;
      if (response.status !== 200 || data.project_id !== this.projectId || data.method !== METHOD
        || ![data.available, data.advisories_available, data.can_manage, data.can_collect].every((value) => typeof value === 'boolean')
        || !Array.isArray(data.jobs) || data.jobs.length > 20 || !data.jobs.every((job) => this.validJob(job) && job.evidence === null)
        || !Array.isArray(data.grants) || data.grants.length > 20 || !data.grants.every((grant) => grant && id(grant.id)
          && Number.isSafeInteger(grant.revision) && grant.revision >= 0 && text(grant.repository) && id(grant.repository_id)
          && sha(grant.commit_sha) && text(grant.expires_at) && typeof grant.source_current === 'boolean')
        || ![data.next_before, data.next_grant_before].every((value) => value === null || id(value))) throw new Error();
      this.page.set(data);
      if (requestKey) {
        const found = data.jobs.some((job) => job.request_key === requestKey);
        this.message.set(found ? 'Request found. Inspect its result or refresh for completion.' : 'No committed request found. Resubmit the unchanged consent to keep the same request key.');
        if (found) for (const [scope, key] of this.api.repositoryPendingRequests) {
          if (scope.startsWith(`${this.organizationId}:${this.projectId}:`) && key === requestKey) this.api.repositoryPendingRequests.delete(scope);
        }
      }
    } catch { if (this.current(generation)) this.error.set('Private analysis history unavailable. Refresh current project access.'); }
    finally { if (this.current(generation)) this.loading.set(false); }
  }
  async find(key: string) { if (!this.busy()) await this.load(null, null, key); }
  async submit(event: Event) {
    event.preventDefault();
    const data = this.page();
    if (this.busy() || !data?.available || !data.can_manage || !data.can_collect || document.hidden) return;
    const form = new FormData(event.target as HTMLFormElement);
    const grant = data.grants.find((row) => row.id === Number(form.get('grant')));
    if (!grant?.source_current || form.get('acknowledge') !== 'on') return;
    const operation = String(form.get('operation'));
    if (!['root_dependency_inventory', CODE_OPERATION, ...ADVISORY_OPERATIONS].includes(operation)
      || ADVISORY_OPERATIONS.includes(operation) && (!data.advisories_available || form.get('disclose') !== 'on')) return;
    const path = operation === CODE_OPERATION ? String(form.get('source_path') ?? '') : null;
    if (operation === CODE_OPERATION && !sourcePath(path)) { this.error.set('Select a relative .py path with at most six ASCII path segments and240 characters.'); return; }
    const generation = this.generation; this.busy.set(true); this.selected.set(null); this.error.set('');
    let key = '';
    try {
      let suffix = '';
      if (path !== null) {
        const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(path));
        if (!this.current(generation)) return;
        suffix = ':' + Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
      }
      const scope = `${this.organizationId}:${this.projectId}:${grant.id}:${grant.revision}:${operation}${suffix}`;
      key = this.api.repositoryPendingRequests.get(scope) ?? crypto.randomUUID();
      this.api.repositoryPendingRequests.set(scope, key);
      const body: Record<string, unknown> = { command: 'analyze', grant_id: grant.id, grant_revision: grant.revision,
        operation, acknowledge_read_only_analysis: true, request_key: key };
      if (ADVISORY_OPERATIONS.includes(operation)) body['acknowledge_package_disclosure'] = true;
      if (path !== null) body['source_path'] = path;
      const response = await this.api.repositoryAnalysis(this.organizationId, this.projectId, 0, body);
      if (!this.current(generation)) return;
      const job = response.body['job'] as Job;
      if (response.status !== 202 || response.body['project_id'] !== this.projectId || response.body['method'] !== METHOD
        || !this.validJob(job) || job.request_key !== key || job.grant_id !== grant.id || job.operation !== operation || job.source_path !== path) throw new Error();
      this.api.repositoryPendingRequests.delete(scope);
      await this.load();
      if (this.current(generation + 1)) this.message.set('Analysis request recorded. Refresh history for completion; no collection is retried automatically.');
    } catch { if (this.current(generation)) this.error.set(`Analysis request unconfirmed. Look up request ${key} or resubmit the unchanged consent to reuse its key.`); }
    finally { if (this.current(generation)) this.busy.set(false); }
  }
  async inspect(jobId: number) {
    if (this.busy() || !this.page() || document.hidden) return;
    const generation = this.generation; this.busy.set(true); this.selected.set(null); this.error.set('');
    try {
      const response = await this.api.repositoryAnalysis(this.organizationId, this.projectId, jobId);
      if (!this.current(generation)) return;
      const job = response.body['job'] as Job;
      if (response.status !== 200 || response.body['project_id'] !== this.projectId || response.body['method'] !== METHOD
        || !this.validJob(job) || job.id !== jobId) throw new Error();
      this.selected.set(job);
    } catch { if (this.current(generation)) this.error.set('Result unavailable. Refresh current repository consent and project access.'); }
    finally { if (this.current(generation)) this.busy.set(false); }
  }
  async cancel(jobId: number) {
    if (this.busy() || !this.page()?.can_manage || document.hidden) return;
    const generation = this.generation; this.busy.set(true); this.selected.set(null); this.error.set('');
    try {
      const response = await this.api.repositoryAnalysis(this.organizationId, this.projectId, jobId, { command: 'cancel' });
      if (!this.current(generation)) return;
      const job = response.body['job'] as Job;
      if (response.status !== 200 || response.body['project_id'] !== this.projectId || response.body['method'] !== METHOD
        || !this.validJob(job) || job.id !== jobId) throw new Error();
      await this.load(this.before, this.grantBefore);
      if (this.current(generation + 1)) this.message.set('Cancellation recorded. In-flight collection and cleanup may still be finishing.');
    } catch { if (this.current(generation)) this.error.set('Cancellation unconfirmed. Refresh history before another decision.'); }
    finally { if (this.current(generation)) this.busy.set(false); }
  }
}
