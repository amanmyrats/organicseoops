import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, OnInit, signal, computed, effect } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';
import { AccountApi } from '../account/account-api';

type Job = { id: number; handler: string; status: string; error_category: string; estimated_units: number;
  attempted_units: number; cancel_requested: boolean; created_at: string; updated_at: string;
  retry_supported?: boolean; steps_has_more?: boolean; steps?: { sequence: number; name: string; status: string;
    progress_percent: number; error_category: string }[] };
type Import = { id: number; state: string; coverage: string; row_errors: number; recorded_at: string };
type Candidate = { id: number; subject: string; detector: string; source_id: number; confidence: string;
  priority: string; detected_at: string };
type Completion = { state: 'unknown' | 'not_observed_for_project' | 'recorded'; job_id?: number;
  source_digest?: string; observed_at?: string; tracking_started_at?: string; page_limit?: number;
  pages_observed?: number; successful_html_pages?: number; robots_status?: string; discovery_truncated?: boolean };
const completionScope = 'historical_organization_first_bounded_completion_within_selected_project_not_current_use_or_first_value';
type Timing = { state: string; tracking_started_at?: string; acknowledged_at?: string;
  source_digest?: string; elapsed_milliseconds?: number };

@Component({
  selector: 'app-first-audit',
  imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="first-audit-title">
      <h1 id="first-audit-title">{{ t("First project audit: evidence before action") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish first-audit interface draft in local development. Stored source/status values and other screens remain English; bilingual approval is pending.") }}</p> }
      <p><a [routerLink]="['/app/onboarding', organizationId, projectId]">{{ t("Return to project source setup") }}</a></p>
      @if (loading()) { <p role="status">{{ t("Checking this project's sources, work and findings.") }}</p> }
      @if (error()) { <p role="alert">{{ t(error()) }}</p> }
      @if (!loading() && !error()) {
        <p>{{ t("Active project") }} <span lang="">{{ projectName() }}</span>. {{ t("This is a guided, bounded view of the current project—not a full-site audit or a universal score. An empty source or finding does not mean a clean website, indexed pages or zero conversions.") }}</p>
        @if (demo()) { <p role="status">{{ t("Isolated synthetic demo mode: live source records and work are not shown or launched here.") }}
          <a routerLink="/sample-report">{{ t("View the clearly labeled synthetic sample; no job or usage is created") }}</a>.</p> }
        <button type="button" (click)="load()" [disabled]="busy()">{{ t("Refresh current status") }}</button>
        <section aria-labelledby="first-source-title">
          <h2 id="first-source-title">{{ t("1. Import or connect a first-party source") }}</h2>
          @if (imports().length) {
            <ul>@for (item of imports(); track item.id) {
              <li>{{ t("Import") }} {{ item.id }} · <span lang="en">{{ item.state }}</span> · {{ t("coverage") }} <span lang="en">{{ item.coverage }}</span> · {{ t("row errors") }} {{ item.row_errors }} · {{ item.recorded_at }}.</li>
            }</ul>
          } @else { <p>{{ t("No project source import recorded. Search query coverage and business conversion remain unknown.") }}</p> }
          <a [routerLink]="['/app/onboarding', organizationId, projectId]">{{ t("Connect or import a permitted source and inspect its actual coverage") }}</a>
        </section>
        <section aria-labelledby="first-crawl-title">
          <h2 id="first-crawl-title">{{ t("2. Inspect a budgeted project crawl") }}</h2>
          <p>{{ t("One to five HTTP-first project pages (one internal unit reserved per attempted page). The crawler checks project scope, cancellation and trial/budget at dispatch and safe stages; a crawl is not indexing evidence. URLs come from this project's current canonical origin and safe discovery. No example domain or synthetic demo is sent to a live fetcher by this screen.") }}</p>
          @if (canLaunch()) {
            <form (submit)="start($event)">
              <label for="first-page-budget">{{ t("Maximum project pages to attempt (1–5)") }}</label>
              <input id="first-page-budget" name="page_limit" type="number" min="1" max="5" value="3" required />
              <button type="submit" [disabled]="busy()">{{ t("Reserve page budget and start scoped crawl") }}</button>
            </form>
          } @else { <p>{{ t("Current role can review evidence but cannot start or cancel work.") }}</p> }
          @if (!crawls().length) { <p>{{ t("No crawl has been requested. Technical issues are not yet checked.") }}</p> }
          @else {
            <ul>@for (job of crawls(); track job.id) {
              <li>{{ t("Audit") }} {{ job.id }} · <span lang="en">{{ job.status }}</span> · {{ job.attempted_units }} {{ t("recorded units from up to") }} {{ job.estimated_units }} {{ t("reserved") }} · {{ job.updated_at }}.
                @if (job.error_category) { <span> <span lang="en">{{ job.error_category }}</span>; {{ t("results may be partial or unknown.") }}</span> }
                <button type="button" (click)="refresh(job.id)" [disabled]="busy()">{{ t("Refresh audit") }} {{ job.id }}</button>
                @if (canLaunch() && ['queued', 'running'].includes(job.status) && !job.cancel_requested) {
                  <button type="button" (click)="cancel(job.id)" [disabled]="busy()">{{ t("Request cancellation") }}</button>
                }
                @if (canLaunch() && job.retry_supported && ['failed', 'cancelled', 'partially_succeeded'].includes(job.status)) {
                  <button type="button" (click)="retry(job.id)" [disabled]="busy()">{{ t("Retry this bounded audit with the same page budget") }}</button>
                }
                @if (job.steps?.length) {
                  <ol>@for (step of job.steps; track step.sequence) {
                    <li><span lang="en">{{ step.name }} · {{ step.status }}</span> · {{ step.progress_percent }}%
                      @if (step.error_category) { <span lang="en">{{ step.error_category }}</span> }
                    </li>
                  }</ol>
                  @if (job.steps_has_more) { <p>{{ t("More recorded stages are outside this bounded view.") }}</p> }
                }
              </li>
            }</ul>
          }
          <a [routerLink]="['/app/onboarding', organizationId, projectId]">{{ t("Inspect technical and indexation observations, then record only actual finding candidates") }}</a>
          @if (!demo()) {
            <section aria-labelledby="first-completion-title">
              <h3 id="first-completion-title">{{ t("Saved bounded-completion history") }}</h3>
              <p>{{ t("Historical operational completion, not current permission to reuse its source, an accepted first-value result, or a clean or complete website. Inspection starts no crawl and records no conversion.") }}</p>
              <button type="button" (click)="inspectCompletion()" [disabled]="busy()">{{ t("Inspect saved bounded completion") }}</button>
              @if (historyLoading()) { <p role="status">{{ t("Inspecting retained private completion evidence.") }}</p> }
              @if (historyError()) { <p role="alert">{{ t(historyError()) }}</p> }
              @if (completion(); as saved) {
                @if (saved.state === 'recorded') {
                  <p role="status">{{ t("Recorded historical audit") }} {{ saved.job_id }}. {{ t("Original server observation") }} {{ saved.observed_at }}; {{ t("prospective tracking began") }} {{ saved.tracking_started_at }}.</p>
                  <p>{{ saved.pages_observed }} {{ t("observed pages within a") }} {{ saved.page_limit }}{{ t("-page budget;") }} {{ saved.successful_html_pages }} {{ t("same-job successful HTML pages. Bounded discovered HTTP sample—not the complete site.") }} {{ t("Robots") }} <span lang="en">{{ saved.robots_status }}</span>; {{ t("discovery truncated") }} <span lang="en">{{ saved.discovery_truncated }}</span>.</p>
                  <p>{{ t("Original source SHA-256:") }} <code>{{ saved.source_digest }}</code></p>
                } @else if (saved.state === 'not_observed_for_project') {
                  <p role="status">{{ t("No first bounded completion observed for this selected project. Other-project history is not disclosed; this does not mean no work occurred or a clean website.") }}</p>
                } @else { <p role="status">{{ t("Historical tracking coverage is unknown. No completion, zero-result or first-value inference is available.") }}</p> }
              }
            </section>
          }
        </section>
        <section aria-labelledby="first-performance-title">
          <h2 id="first-performance-title">{{ t("3. Optional separate performance observations") }}</h2>
          @if (performance().length) {
            <ul>@for (job of performance(); track job.id) {
              <li>{{ t("Audit") }} {{ job.id }} · <span lang="en">{{ job.status }}</span> · {{ t("up to") }} {{ job.estimated_units }} {{ t("reserved units.") }} @if (job.error_category) { <span lang="en">{{ job.error_category }}</span> } @else { {{ t("See lab/field coverage in source history.") }} }</li>
            }</ul>
          } @else { <p>{{ t("No lab or field observation recorded. Performance remains unknown; a configured provider key and budget are required for a new audit.") }}</p> }
          <a [routerLink]="['/app/onboarding', organizationId, projectId]">{{ t("Select available PageSpeed lab or CrUX field evidence separately") }}</a>
        </section>
        <section aria-labelledby="first-findings-title">
          <h2 id="first-findings-title">{{ t("4. Up to three current evidence-backed next-action candidates") }}</h2>
          @if (candidateState() === 'source_unavailable') { <p role="alert">{{ t("Finding source is unavailable; this does not mean no issues were found.") }}</p> }
          @else if (!candidates().length) { <p>{{ t("No current candidate from the loaded bounded source window. More project data or an explicit detector review may be needed; nothing is fabricated to fill a list.") }}</p> }
          @else {
            <ol>@for (finding of candidates(); track finding.id) {
              <li><span lang="">{{ finding.subject }}</span> · <span lang="en">{{ finding.detector }} · {{ finding.confidence }}</span> · {{ t("source") }} {{ finding.source_id }} · {{ finding.detected_at }}.
                {{ t("Human priority:") }} <span lang="en">{{ finding.priority }}</span>. {{ t("Candidate only: no automatic fix or causal improvement claim.") }}
                <a [routerLink]="['/app/onboarding', organizationId, projectId]">{{ t("Inspect full evidence and human review") }}</a>
              </li>
            }</ol>
            @if (candidatesTruncated()) { <p>{{ t("More candidates or incomplete window: this is not an exhaustive priority list.") }}</p> }
          }
          <p><a [routerLink]="['/app/intent', organizationId, projectId]">{{ t("Map selected query intent to an existing or proposed page") }}</a>;
            <a [routerLink]="['/app/actions', organizationId, projectId]">{{ t("assign and review a human action") }}</a>;
            <a [routerLink]="['/app/research', organizationId, projectId]">{{ t("collect explicit source research") }}</a>;
            <a [routerLink]="['/app/briefs', organizationId, projectId]">{{ t("draft a sourced brief") }}</a>.</p>
        </section>
        @if (!demo()) {
          <section aria-labelledby="first-usefulness-timing-title">
            <h2 id="first-usefulness-timing-title">{{ t("Retained server usefulness timing") }}</h2>
            <p>{{ t("Organization") }} {{ organizationId }} · {{ t("project") }} {{ projectId }}. {{ t("Organization age at the first server subjective usefulness acknowledgment, not audit runtime, work duration, time from registration or trial, actual time-to-business-value, a lifetime or cohort conversion rate. The original audit and human-action dates are separate. Inspection starts no job and records no acknowledgment, approval or analytics event.") }}</p>
            <button type="button" (click)="inspectUsefulnessTiming()" [disabled]="busy()">{{ t("Inspect saved server usefulness timing") }}</button>
            @if (timingLoading()) { <p role="status">{{ t("Inspecting retained original timing and private source integrity.") }}</p> }
            @if (timingError()) { <p role="alert">{{ t(timingError()) }}</p> }
            @if (usefulnessTiming(); as timing) {
              @if (timing.state === 'recorded') {
                <p>{{ t("Original organization tracking began") }} {{ timing.tracking_started_at }}; {{ t("first server subjective acknowledgment") }} {{ timing.acknowledged_at }}.</p>
                <p>{{ t("Elapsed organization age:") }} {{ timing.elapsed_milliseconds }} {{ t("whole milliseconds, rounded down.") }} {{ t("Original source SHA-256:") }} <code>{{ timing.source_digest }}</code>. {{ t("Historical declaration, not current permission to reuse its source or proof of business value.") }}</p>
              } @else { <p>{{ t("No recorded timing for this selected project; tracking or another project's history remains unknown. No duration or zero-value inference is available.") }}</p> }
            }
            <a [routerLink]="['/app/actions', organizationId, projectId]">{{ t("Inspect actual accepted audit-action evidence and the separate optional subjective declaration") }}</a>
          </section>
        }
        @if (message()) { <p role="status">{{ t(message()) }}</p> }
      }
    </section>
  `,
  styles: `section {overflow-wrap:anywhere;border-top:1px solid #b9cfd5;padding-block:1rem} button {margin:.5rem .5rem .5rem 0} label {display:block}`,
})
export class FirstAudit implements OnInit {
  organizationId = 0;
  projectId = 0;
  private generation = 0;
  private pendingRetries = new Map<number, string>();
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  t(text: string) { return this.uiLanguage() === 'tr' ? firstAuditTurkish[text] ?? text : text; }
  readonly projectName = signal('');
  readonly loading = signal(true);
  readonly busy = signal(false);
  readonly error = signal('');
  readonly message = signal('');
  readonly canLaunch = signal(false);
  readonly demo = signal(false);
  readonly imports = signal<Import[]>([]);
  readonly crawls = signal<Job[]>([]);
  readonly performance = signal<Job[]>([]);
  readonly candidates = signal<Candidate[]>([]);
  readonly candidateState = signal('');
  readonly candidatesTruncated = signal(false);
  readonly completion = signal<Completion | null>(null);
  readonly historyLoading = signal(false);
  readonly historyError = signal('');
  readonly usefulnessTiming = signal<Timing | null>(null);
  readonly timingLoading = signal(false);
  readonly timingError = signal('');

  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi,
              private readonly destroy: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t('Budgeted first project audit')} — OrganicSEOOps`));
    destroy.onDestroy(() => { this.generation++; this.clearCompletion(); this.busy.set(false); });
  }

  private clearCompletion() {
    this.completion.set(null); this.historyError.set(''); this.historyLoading.set(false);
    this.usefulnessTiming.set(null); this.timingLoading.set(false); this.timingError.set('');
  }

  ngOnInit() {
    void this.loadProductLanguage();
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroy)).subscribe((params) => {
      this.organizationId = Number(params.get('organizationId')); this.projectId = Number(params.get('projectId'));
      this.generation++;
      this.pendingRetries.clear();
      this.clearCompletion();
      this.projectName.set(''); this.canLaunch.set(false); this.error.set(''); this.message.set('');
      this.imports.set([]); this.crawls.set([]); this.performance.set([]); this.candidates.set([]);
      this.candidateState.set(''); this.candidatesTruncated.set(false); this.busy.set(false);
      this.demo.set(false);
      if (Number.isSafeInteger(this.organizationId) && this.organizationId > 0
          && Number.isSafeInteger(this.projectId) && this.projectId > 0) void this.load();
      else { this.loading.set(false); this.error.set('Choose a current authorized project.'); }
    });
  }

  private async loadProductLanguage() {
    try {
      const result = await this.api.productLanguage();
      if (!this.destroy.destroyed && result.status === 200 && isProductLanguageResult(result.body)) {
        this.productLanguage.set(result.body['language']);
      }
    } catch { /* Keep English when the private preference is unavailable. */ }
  }

  async load() {
    const generation = ++this.generation;
    this.clearCompletion(); this.busy.set(false);
    this.demo.set(false); this.canLaunch.set(false);
    this.loading.set(true); this.error.set('');
    this.imports.set([]); this.crawls.set([]); this.performance.set([]); this.candidates.set([]);
    try {
      const context = await this.api.projectOnboarding(this.organizationId, this.projectId);
      if (generation !== this.generation) return;
      const project = context.body['project'] as Record<string, unknown> | undefined;
      if (context.status !== 200 || project?.['id'] !== this.projectId || project['organization_id'] !== this.organizationId
          || typeof project['role'] !== 'string' || !['owner', 'admin', 'member', 'viewer'].includes(project['role'])) throw new Error();
      this.projectName.set(String(project['name']));
      this.canLaunch.set(['owner', 'admin', 'member'].includes(project['role']));
      const status = await this.api.firstProjectAudit(this.organizationId, this.projectId);
      if (generation !== this.generation) return;
      const data = status.body;
      if (status.status !== 200 || data['project_id'] !== this.projectId || data['scope'] !== 'current_bounded_project_sources_not_a_complete_audit'
          || !Array.isArray(data['crawl']) || !Array.isArray(data['performance']) || !Array.isArray(data['imports'])
          || !Array.isArray(data['candidates'])) throw new Error();
      this.imports.set((data['imports'] as Import[]).filter((row) => Number.isSafeInteger(row.id)).slice(0, 10));
      this.crawls.set((data['crawl'] as Job[]).filter(isJob).slice(0, 10));
      this.performance.set((data['performance'] as Job[]).filter(isJob).slice(0, 10));
      this.candidates.set((data['candidates'] as Candidate[]).filter((row) => Number.isSafeInteger(row.id)
        && typeof row.subject === 'string' && Number.isSafeInteger(row.source_id)).slice(0, 3));
      this.candidateState.set(String(data['candidate_state']));
      this.candidatesTruncated.set(data['candidates_truncated'] === true);
      this.demo.set(data['mode'] === 'synthetic_demo_separate_no_live_observation');
      if (this.demo()) this.canLaunch.set(false);
    } catch { if (generation === this.generation) this.error.set('Current audit context is unavailable. No missing result is a clean audit.'); }
    finally { if (generation === this.generation) this.loading.set(false); }
  }

  async inspectCompletion() {
    if (this.busy() || this.loading() || this.error() || this.demo()) return;
    const generation = this.generation, organizationId = this.organizationId, projectId = this.projectId;
    this.clearCompletion(); this.historyLoading.set(true); this.busy.set(true);
    try {
      const result = await this.api.firstProjectAuditCompletion(organizationId, projectId);
      if (generation !== this.generation) return;
      const history = validateCompletion(result.body, organizationId, projectId);
      if (result.status !== 200 || !history || this.demo()) throw new Error();
      this.completion.set(history);
    } catch {
      if (generation === this.generation) {
        this.completion.set(null); this.historyError.set('Saved completion unavailable or needs review. Refresh current project context; no missing result proves first value or a clean site.');
      }
    } finally {
      if (generation === this.generation) { this.historyLoading.set(false); this.busy.set(false); }
    }
  }

  async inspectUsefulnessTiming() {
    if (this.busy() || this.loading() || this.error() || this.demo()) return;
    const generation = this.generation, organizationId = this.organizationId, projectId = this.projectId;
    this.clearCompletion(); this.timingLoading.set(true); this.busy.set(true);
    try {
      const result = await this.api.firstProjectAuditUsefulnessTiming(organizationId, projectId);
      if (generation !== this.generation) return;
      const timing = validateUsefulnessTiming(result.body, organizationId, projectId);
      if (result.status !== 200 || !timing) throw new Error();
      const context = await this.api.projectOnboarding(organizationId, projectId);
      if (generation !== this.generation) return;
      const project = context.body['project'] as Record<string, unknown> | undefined;
      if (context.status !== 200 || project?.['id'] !== projectId || project['organization_id'] !== organizationId
        || (context.body['configuration'] as Record<string, unknown> | undefined)?.['source_choice'] === 'synthetic_demo') throw new Error();
      this.usefulnessTiming.set(structuredClone(timing));
    } catch { if (generation === this.generation) {
      this.usefulnessTiming.set(null); this.timingError.set('Retained server timing unavailable or needs review. Refresh this project; unknown history supplies no duration.');
    } } finally { if (generation === this.generation) { this.timingLoading.set(false); this.busy.set(false); } }
  }

  async start(event: Event) {
    event.preventDefault();
    const form = event.target as HTMLFormElement;
    if (this.busy() || !this.canLaunch() || !form.reportValidity()) return;
    const pages = Number(new FormData(form).get('page_limit'));
    if (!Number.isSafeInteger(pages) || pages < 1 || pages > 5) return;
    const generation = this.generation;
    this.clearCompletion();
    this.busy.set(true); this.message.set('');
    try {
      const result = await this.api.startFirstProjectAudit(this.organizationId, this.projectId, pages);
      if (generation !== this.generation) return;
      const job = result.body['job'];
      if (result.status !== 202 || result.body['project_id'] !== this.projectId || !isJob(job)
          || job.estimated_units !== pages || job.handler !== 'crawl_site') throw new Error();
      this.crawls.set([job, ...this.crawls().filter((entry) => entry.id !== job.id)].slice(0, 10));
      this.message.set('Bounded project crawl queued; refresh its actual stage results and source evidence before selecting any action.');
    } catch { if (generation === this.generation) this.message.set('Audit request outcome unavailable. Refresh status before trying a new request.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }

  async refresh(id: number, cancel = false) {
    if (this.busy() || !this.crawls().some((job) => job.id === id)) return;
    const generation = this.generation;
    this.clearCompletion();
    this.busy.set(true); this.message.set('');
    try {
      const result = await this.api.firstProjectAuditJob(this.organizationId, this.projectId, id, cancel);
      if (generation !== this.generation) return;
      const job = result.body['job'];
      if (![200, 202].includes(result.status) || result.body['project_id'] !== this.projectId || !isJob(job) || job.id !== id) throw new Error();
      this.crawls.set(this.crawls().map((entry) => entry.id === id ? job : entry));
      this.message.set(cancel ? 'Cancellation requested or confirmed; inspect this job before retrying.' : 'Job status refreshed; inspect detailed observations in project onboarding.');
    } catch { if (generation === this.generation) this.message.set('Crawl status unavailable or project access revoked.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }

  cancel(id: number) { void this.refresh(id, true); }

  async retry(id: number) {
    const original = this.crawls().find(job => job.id === id);
    if (this.busy() || this.loading() || this.error() || !this.canLaunch() || !original
      || original.handler !== 'crawl_site' || original.retry_supported !== true
      || !['failed', 'cancelled', 'partially_succeeded'].includes(original.status)) return;
    if (!this.pendingRetries.has(id)) this.pendingRetries.set(id, crypto.randomUUID());
    const generation = this.generation, organizationId = this.organizationId, projectId = this.projectId;
    this.clearCompletion(); this.busy.set(true); this.message.set('');
    try {
      const result = await this.api.retryFirstProjectAudit(organizationId, projectId, id, this.pendingRetries.get(id)!);
      if (generation !== this.generation) return;
      const job = result.body['job'];
      if (result.status !== 202 || result.body['project_id'] !== projectId || !isJob(job)
        || job.id === id || job.handler !== 'crawl_site' || job.estimated_units !== original.estimated_units) throw new Error();
      this.pendingRetries.delete(id);
      this.crawls.set([job, ...this.crawls().filter(entry => entry.id !== job.id)].slice(0, 10));
      this.message.set('Bounded audit retry queued with its original page budget; inspect actual evidence before selecting any action.');
    } catch { if (generation === this.generation) this.message.set('Audit retry outcome unavailable. Refresh status; retrying this same audit reuses the same request.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
}

function validateUsefulnessTiming(body: Record<string, unknown>, organizationId: number, projectId: number): Timing | null {
  const keys = ['method', 'organization_id', 'project_id', 'state', 'interpretation', 'precision'];
  if (body['method'] !== 'bounded-audit-usefulness-timing-v1' || body['organization_id'] !== organizationId
    || body['project_id'] !== projectId || typeof body['state'] !== 'string'
    || body['interpretation'] !== 'organization_age_at_first_server_subjective_ack_not_business_value_time'
    || body['precision'] !== 'whole_milliseconds_rounded_down') return null;
  if (body['state'] === 'recorded') {
    keys.push('tracking_started_at', 'acknowledged_at', 'source_digest', 'elapsed_milliseconds');
    const dates = [body['tracking_started_at'], body['acknowledged_at']];
    if (!dates.every(value => typeof value === 'string'
      && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(value)
      && Number.isFinite(Date.parse(value)) && Date.parse(value) <= Date.now())
      || !Number.isSafeInteger(body['elapsed_milliseconds']) || Number(body['elapsed_milliseconds']) < 0
      || typeof body['source_digest'] !== 'string' || !/^[a-f0-9]{64}$/.test(body['source_digest'])) return null;
    // Python retains microseconds; truncating both dates to JS milliseconds can overcount by one.
    const micros = (value: string) => BigInt(Date.parse(value)) * 1000n
      + BigInt(Number((value.match(/\.(\d{1,6})/)?.[1] || '').padEnd(6, '0')) % 1000);
    const elapsed = micros(String(dates[1])) - micros(String(dates[0]));
    if (elapsed < 0n || elapsed / 1000n !== BigInt(Number(body['elapsed_milliseconds']))) return null;
  } else if (!['unknown', 'not_observed_for_project'].includes(body['state'])) return null;
  if (Object.keys(body).length !== keys.length || keys.some(key => !Object.hasOwn(body, key))) return null;
  return body as Timing;
}

function isJob(value: unknown): value is Job {
  if (!value || typeof value !== 'object') return false;
  const job = value as Record<string, unknown>;
  return Number.isSafeInteger(job['id']) && Number(job['id']) > 0
    && typeof job['handler'] === 'string' && ['crawl_site', 'audit_performance'].includes(job['handler'])
    && typeof job['status'] === 'string' && typeof job['error_category'] === 'string'
    && Number.isSafeInteger(job['estimated_units']) && Number.isSafeInteger(job['attempted_units'])
    && typeof job['cancel_requested'] === 'boolean'
    && (job['retry_supported'] === undefined || typeof job['retry_supported'] === 'boolean')
    && (job['steps_has_more'] === undefined || typeof job['steps_has_more'] === 'boolean')
    && (job['steps'] === undefined || Array.isArray(job['steps']) && job['steps'].length <= 20
      && job['steps'].every(step => step && typeof step === 'object'
        && Number.isSafeInteger(step.sequence) && step.sequence > 0 && typeof step.name === 'string'
        && typeof step.status === 'string' && typeof step.error_category === 'string'
        && Number.isSafeInteger(step.progress_percent) && step.progress_percent >= 0 && step.progress_percent <= 100));
}

function validateCompletion(value: Record<string, unknown>, organizationId: number, projectId: number): Completion | null {
  if (value['method'] !== 'bounded-first-audit-completion-v1' || value['scope'] !== completionScope
      || value['organization_id'] !== organizationId || value['project_id'] !== projectId
      || typeof value['state'] !== 'string') return null;
  const keys = ['method', 'scope', 'organization_id', 'project_id', 'state'];
  if (value['state'] === 'recorded') {
    keys.push('job_id', 'source_digest', 'observed_at', 'tracking_started_at', 'page_limit', 'pages_observed',
      'successful_html_pages', 'coverage', 'robots_status', 'discovery_truncated');
    const dated = (date: unknown): date is string => typeof date === 'string'
      && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(date)
      && Number.isFinite(Date.parse(date)) && Date.parse(date) <= Date.now();
    if (!Number.isSafeInteger(value['job_id']) || Number(value['job_id']) < 1
        || typeof value['source_digest'] !== 'string' || !/^[0-9a-f]{64}$/.test(value['source_digest'])
        || !dated(value['tracking_started_at']) || !dated(value['observed_at'])
        || Date.parse(value['tracking_started_at']) > Date.parse(value['observed_at'])
        || !['page_limit', 'pages_observed', 'successful_html_pages'].every((key) => Number.isSafeInteger(value[key]) && Number(value[key]) >= 1)
        || Number(value['page_limit']) > 5 || Number(value['pages_observed']) > Number(value['page_limit'])
        || Number(value['successful_html_pages']) > Number(value['pages_observed'])
        || value['coverage'] !== 'bounded_discovered_http_sample_not_complete_site'
        || typeof value['robots_status'] !== 'string' || !['available', 'missing'].includes(value['robots_status'])
        || typeof value['discovery_truncated'] !== 'boolean') return null;
  } else if (!['unknown', 'not_observed_for_project'].includes(value['state'])) return null;
  if (Object.keys(value).length !== keys.length || keys.some((key) => !Object.hasOwn(value, key))) return null;
  return value as Completion;
}

const firstAuditTurkish: Readonly<Record<string, string>> = {
  "Retry this bounded audit with the same page budget": "Bu sınırlı denetimi aynı sayfa bütçesiyle yeniden dene",
  "More recorded stages are outside this bounded view.": "Kaydedilmiş diğer aşamalar bu sınırlı görünümün dışındadır.",
  "Bounded audit retry queued with its original page budget; inspect actual evidence before selecting any action.": "Sınırlı denetim özgün sayfa bütçesiyle yeniden sıraya alındı; bir eylem seçmeden önce gerçek kanıtı inceleyin.",
  "Audit retry outcome unavailable. Refresh status; retrying this same audit reuses the same request.": "Denetimi yeniden denemenin sonucu bilinmiyor. Durumu yenileyin; aynı denetimi yeniden denemek aynı isteği kullanır.",
  "Budgeted first project audit": "Bütçeli ilk proje denetimi",
  "First project audit: evidence before action": "İlk proje denetimi: eylemden önce kanıt",
  "Unreviewed Turkish first-audit interface draft in local development. Stored source/status values and other screens remain English; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe ilk denetim arayüzü taslağı. Kayıtlı kaynak/durum değerleri ve diğer ekranlar İngilizce kalır; iki dilli onay bekleniyor.",
  "Return to project source setup": "Proje kaynak kurulumuna dön",
  "Checking this project's sources, work and findings.": "Bu projenin kaynakları, işleri ve bulguları kontrol ediliyor.",
  "Active project": "Etkin proje",
  "This is a guided, bounded view of the current project—not a full-site audit or a universal score. An empty source or finding does not mean a clean website, indexed pages or zero conversions.": "Bu, güncel projenin yönlendirilmiş ve sınırlı görünümüdür; tüm site denetimi veya evrensel puan değildir. Boş kaynak veya bulgu, sorunsuz web sitesi, dizine eklenmiş sayfalar veya sıfır dönüşüm anlamına gelmez.",
  "Isolated synthetic demo mode: live source records and work are not shown or launched here.": "Yalıtılmış sentetik demo modu: canlı kaynak kayıtları ve işler burada gösterilmez veya başlatılmaz.",
  "View the clearly labeled synthetic sample; no job or usage is created": "Açıkça etiketlenmiş sentetik örneği görüntüle; iş veya kullanım oluşturulmaz",
  "Refresh current status": "Güncel durumu yenile",
  "1. Import or connect a first-party source": "1. Birinci taraf kaynağını içe aktarın veya bağlayın",
  "Import": "İçe aktarma",
  "coverage": "kapsam",
  "row errors": "satır hataları",
  "No project source import recorded. Search query coverage and business conversion remain unknown.": "Proje kaynağı içe aktarımı kaydedilmemiş. Arama sorgusu kapsamı ve işletme dönüşümü bilinmiyor.",
  "Connect or import a permitted source and inspect its actual coverage": "İzinli bir kaynağı bağlayın veya içe aktarın ve gerçek kapsamını inceleyin",
  "2. Inspect a budgeted project crawl": "2. Bütçeli proje taramasını inceleyin",
  "One to five HTTP-first project pages (one internal unit reserved per attempted page). The crawler checks project scope, cancellation and trial/budget at dispatch and safe stages; a crawl is not indexing evidence. URLs come from this project's current canonical origin and safe discovery. No example domain or synthetic demo is sent to a live fetcher by this screen.": "Öncelikle HTTP ile bir ila beş proje sayfası (denenen her sayfa için bir iç birim ayrılır). Tarayıcı, gönderimde ve güvenli aşamalarda proje kapsamını, iptali ve deneme/bütçeyi kontrol eder; tarama, dizine eklenme kanıtı değildir. URL’ler bu projenin güncel kanonik kökeninden ve güvenli keşiften gelir. Bu ekran, örnek alan adı veya sentetik demoyu canlı getiriciye göndermez.",
  "Maximum project pages to attempt (1–5)": "Denenebilecek en fazla proje sayfası (1–5)",
  "Reserve page budget and start scoped crawl": "Sayfa bütçesini ayır ve kapsamlı proje taramasını başlat",
  "Current role can review evidence but cannot start or cancel work.": "Güncel rol kanıtı inceleyebilir ancak iş başlatamaz veya iptal edemez.",
  "No crawl has been requested. Technical issues are not yet checked.": "Tarama istenmemiş. Teknik sorunlar henüz kontrol edilmedi.",
  "Audit": "Denetim",
  "recorded units from up to": "kaydedilmiş birim; en fazla",
  "reserved": "ayrıldı",
  "results may be partial or unknown.": "sonuçlar kısmi veya bilinmiyor olabilir.",
  "Refresh audit": "Denetimi yenile",
  "Request cancellation": "İptal iste",
  "Inspect technical and indexation observations, then record only actual finding candidates": "Teknik ve dizine eklenme gözlemlerini inceleyin, ardından yalnızca gerçek bulgu adaylarını kaydedin",
  "Saved bounded-completion history": "Kaydedilmiş sınırlı tamamlanma geçmişi",
  "Historical operational completion, not current permission to reuse its source, an accepted first-value result, or a clean or complete website. Inspection starts no crawl and records no conversion.": "Geçmiş operasyonel tamamlanma; kaynağı yeniden kullanmak için güncel izin, kabul edilmiş ilk değer sonucu veya sorunsuz ya da tam web sitesi değildir. İnceleme tarama başlatmaz ve dönüşüm kaydetmez.",
  "Inspect saved bounded completion": "Kaydedilmiş sınırlı tamamlanmayı incele",
  "Inspecting retained private completion evidence.": "Saklanmış özel tamamlanma kanıtı inceleniyor.",
  "Recorded historical audit": "Kaydedilmiş geçmiş denetim",
  "Original server observation": "Özgün sunucu gözlemi",
  "prospective tracking began": "ileriye dönük izleme başlangıcı",
  "observed pages within a": "gözlemlenen sayfa;",
  "-page budget;": " sayfalık bütçe;",
  "same-job successful HTML pages. Bounded discovered HTTP sample—not the complete site.": "aynı işte başarılı HTML sayfası. Keşfedilmiş sınırlı HTTP örneği; tüm site değildir.",
  "Robots": "Robots",
  "discovery truncated": "keşif kısıtlandı",
  "Original source SHA-256:": "Özgün kaynak SHA-256:",
  "No first bounded completion observed for this selected project. Other-project history is not disclosed; this does not mean no work occurred or a clean website.": "Bu seçili proje için ilk sınırlı tamamlanma gözlemlenmemiş. Diğer projenin geçmişi açıklanmaz; bu, iş yapılmadığı veya web sitesinin sorunsuz olduğu anlamına gelmez.",
  "Historical tracking coverage is unknown. No completion, zero-result or first-value inference is available.": "Geçmiş izleme kapsamı bilinmiyor. Tamamlanma, sıfır sonuç veya ilk değer çıkarımı yapılamaz.",
  "3. Optional separate performance observations": "3. İsteğe bağlı ayrı performans gözlemleri",
  "up to": "en fazla",
  "reserved units.": "ayrılmış birim.",
  "See lab/field coverage in source history.": "Kaynak geçmişindeki laboratuvar/saha kapsamına bakın.",
  "No lab or field observation recorded. Performance remains unknown; a configured provider key and budget are required for a new audit.": "Laboratuvar veya saha gözlemi kaydedilmemiş. Performans bilinmiyor; yeni denetim için yapılandırılmış sağlayıcı anahtarı ve bütçe gerekir.",
  "Select available PageSpeed lab or CrUX field evidence separately": "Kullanılabilir PageSpeed laboratuvar veya CrUX saha kanıtını ayrı ayrı seçin",
  "4. Up to three current evidence-backed next-action candidates": "4. En fazla üç güncel, kanıta dayalı sonraki eylem adayı",
  "Finding source is unavailable; this does not mean no issues were found.": "Bulgu kaynağı kullanılamıyor; bu, sorun bulunmadığı anlamına gelmez.",
  "No current candidate from the loaded bounded source window. More project data or an explicit detector review may be needed; nothing is fabricated to fill a list.": "Yüklenen sınırlı kaynak penceresinde güncel aday yok. Daha fazla proje verisi veya açık dedektör incelemesi gerekebilir; listeyi doldurmak için hiçbir şey uydurulmaz.",
  "source": "kaynak",
  "Human priority:": "İnsan önceliği:",
  "Candidate only: no automatic fix or causal improvement claim.": "Yalnızca aday: otomatik düzeltme veya nedensel iyileşme iddiası yok.",
  "Inspect full evidence and human review": "Tam kanıtı ve insan incelemesini inceleyin",
  "More candidates or incomplete window: this is not an exhaustive priority list.": "Daha fazla aday veya eksik pencere: bu, tüm öncelikleri kapsayan bir liste değildir.",
  "Map selected query intent to an existing or proposed page": "Seçilen sorgu niyetini mevcut veya önerilen sayfayla eşleştir",
  "assign and review a human action": "bir insan eylemi atayın ve inceleyin",
  "collect explicit source research": "açık kaynak araştırması toplayın",
  "draft a sourced brief": "kaynaklı kısa taslak hazırlayın",
  "Retained server usefulness timing": "Saklanmış sunucu yararlılık zamanlaması",
  "Organization": "Kuruluş",
  "project": "proje",
  "Organization age at the first server subjective usefulness acknowledgment, not audit runtime, work duration, time from registration or trial, actual time-to-business-value, a lifetime or cohort conversion rate. The original audit and human-action dates are separate. Inspection starts no job and records no acknowledgment, approval or analytics event.": "Sunucudaki ilk öznel yararlılık beyanında kuruluş yaşıdır; denetim çalışma süresi, iş süresi, kayıt veya denemeden itibaren süre, gerçek işletme değerine ulaşma süresi, yaşam boyu veya kohort dönüşüm oranı değildir. Özgün denetim ve insan eylemi tarihleri ayrıdır. İnceleme iş başlatmaz ve beyan, onay veya analiz olayı kaydetmez.",
  "Inspect saved server usefulness timing": "Kaydedilmiş sunucu yararlılık zamanlamasını incele",
  "Inspecting retained original timing and private source integrity.": "Saklanmış özgün zamanlama ve özel kaynak bütünlüğü inceleniyor.",
  "Original organization tracking began": "Özgün kuruluş izlemesinin başlangıcı",
  "first server subjective acknowledgment": "ilk sunucu öznel beyanı",
  "Elapsed organization age:": "Geçen kuruluş yaşı:",
  "whole milliseconds, rounded down.": "tam milisaniye, aşağı yuvarlanmış.",
  "Historical declaration, not current permission to reuse its source or proof of business value.": "Geçmiş beyan; kaynağı yeniden kullanmak için güncel izin veya işletme değerinin kanıtı değildir.",
  "No recorded timing for this selected project; tracking or another project's history remains unknown. No duration or zero-value inference is available.": "Bu seçili proje için kaydedilmiş zamanlama yok; izleme veya başka projenin geçmişi bilinmiyor. Süre veya sıfır değer çıkarımı yapılamaz.",
  "Inspect actual accepted audit-action evidence and the separate optional subjective declaration": "Gerçek kabul edilmiş denetim-eylem kanıtını ve ayrı isteğe bağlı öznel beyanı inceleyin",
  "Choose a current authorized project.": "Yetkili olduğunuz güncel bir proje seçin.",
  "Current audit context is unavailable. No missing result is a clean audit.": "Güncel denetim bağlamı kullanılamıyor. Eksik sonuç, sorunsuz denetim değildir.",
  "Saved completion unavailable or needs review. Refresh current project context; no missing result proves first value or a clean site.": "Kaydedilmiş tamamlanma kullanılamıyor veya inceleme gerekiyor. Güncel proje bağlamını yenileyin; eksik sonuç ilk değeri veya sorunsuz siteyi kanıtlamaz.",
  "Retained server timing unavailable or needs review. Refresh this project; unknown history supplies no duration.": "Saklanmış sunucu zamanlaması kullanılamıyor veya inceleme gerekiyor. Bu projeyi yenileyin; bilinmeyen geçmiş süre sağlamaz.",
  "Bounded project crawl queued; refresh its actual stage results and source evidence before selecting any action.": "Sınırlı proje taraması kuyruğa alındı; eylem seçmeden önce gerçek aşama sonuçlarını ve kaynak kanıtını yenileyin.",
  "Audit request outcome unavailable. Refresh status before trying a new request.": "Denetim isteğinin sonucu kullanılamıyor. Yeni bir istek denemeden önce durumu yenileyin.",
  "Crawl status unavailable or project access revoked.": "Tarama durumu kullanılamıyor veya proje erişimi kaldırılmış.",
  "Cancellation requested or confirmed; inspect this job before retrying.": "İptal istendi veya doğrulandı; yeniden denemeden önce bu işi inceleyin.",
  "Job status refreshed; inspect detailed observations in project onboarding.": "İş durumu yenilendi; ayrıntılı gözlemleri proje kurulumunda inceleyin."
};
