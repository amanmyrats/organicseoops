import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, effect, OnInit, signal, computed } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi } from '../account/account-api';
import { environment } from '../../environments/environment';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';

type Source = { id: number; provider: string; state: string; scope_current: boolean; data_status?: string;
  latest_import?: { status: string; coverage_state: string; date_end: string; source_completeness: string } | null;
  sync?: { status: string; quota_state: string; fresh_through: string | null; error_category: string } | null };
type Finding = { id: number; subject: string; detector: string; method_version: string; confidence: string;
  source_current: boolean; detected_at: string; review: { priority: string; estimated_effort: string;
    business_relevance: string; review_reason: string } | null };
type Action = { action_id: string; state: string; action_kind: string; source_current: boolean;
  affected_urls: string[]; acceptance_criteria: string; implemented_at: string | null };
type Local = { location_label: string; eligibility: string; source_current: boolean };

@Component({
  selector: 'app-project-dashboard',
  imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="dashboard-title">
      <h1 id="dashboard-title">{{ t("What matters, why, and the next human action") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish dashboard interface draft in local development. Stored source/status values and other screens remain English; bilingual approval is pending.") }}</p> }
      <p><a routerLink="/app">{{ t("Return to organization and project selection") }}</a></p>
      @if (loading()) { <p role="status">{{ t("Loading this project's evidence. Earlier project data is cleared.") }}</p> }
      @if (error()) { <p role="alert">{{ t(error()) }}</p> }
      @if (!loading() && !error()) {
        <p><strong lang="">{{ projectName() }}</strong>. {{ t("Current source observations, human priorities and actions appear separately. No composite SEO score, universal rank, guaranteed outcome, inferred conversion or automatic fix is calculated.") }}</p>
        <p>{{ t("Organization access:") }} <span lang="en">{{ accessState() || 'unavailable' }}</span>. {{ t("Trial expiry or read-only access is not evidence deletion or a reason to start new paid work.") }}</p>
        @if (accessError()) { <p role="alert">{{ t("Entitlement state unavailable; do not assume this project can launch work.") }}</p> }
        <nav [attr.aria-label]="t('Project review destinations')">
          <a lang="en" [routerLink]="['/app/yandex', organizationId, projectId]">Import and inspect Yandex Webmaster exports</a>
          <a lang="en" [routerLink]="['/app/serp', organizationId, projectId]">Track and inspect scheduled search-result observations</a>
          <a lang="en" [routerLink]="['/app/repositories', organizationId, projectId]">Manage explicit read-only repository connections</a>
          <a lang="en" [routerLink]="['/app/repository-analysis', organizationId, projectId]">Collect read-only repository observations</a>
          <a [routerLink]="['/app/onboarding', organizationId, projectId]">{{ t("Review source configuration and full findings") }}</a>
          <a [routerLink]="['/app/first-audit', organizationId, projectId]">{{ t("Review first-audit progress and bounded next actions") }}</a>
          <a [routerLink]="['/app/intent', organizationId, projectId]">{{ t("Review intent/page mapping") }}</a>
          <a [routerLink]="['/app/actions', organizationId, projectId]">{{ t("Review assigned actions and outcomes") }}</a>
          <a [routerLink]="['/app/local', organizationId, projectId]">{{ t("Review user-entered local business facts") }}</a>
          <a [routerLink]="['/app/local-feedback', organizationId, projectId]">{{ t("Review independent website feedback and exact human replies") }}</a>
          <a [routerLink]="['/app/local-visibility', organizationId, projectId]">{{ t("Review manual local organic-link observations") }}</a>
          <a [routerLink]="['/app/business-profile', organizationId, projectId]">{{ t("Authorized response-only Google profile/reviews") }}</a>
          <a [routerLink]="['/app/reports', organizationId, projectId]">{{ t("Export project evidence and manage report shares") }}</a>
          <a [routerLink]="['/app/ai-text', organizationId, projectId]">{{ t("Inspect separately budgeted AI jobs and known/estimated costs") }}</a>
          <a [routerLink]="['/app/research', organizationId, projectId]">{{ t("Research a selected topic from approved sources") }}</a>
          <a [routerLink]="['/app/authority-prospects', organizationId, projectId]">{{ t("Review human authority prospects from exact stored research") }}</a>
          <a [routerLink]="['/app/authority-links', organizationId, projectId]">{{ t("Review independent human link reports and separate own-target recovery evidence") }}</a>
          <a [routerLink]="['/app/authority-link-sources', organizationId, projectId]">{{ t("Request separately permissioned selected static-link verification") }}</a>
          <a [routerLink]="['/app/competitor-page-destinations', organizationId, projectId]">{{ t("Inspect separately selected competitor page same-origin references") }}</a>
          <a [routerLink]="['/app/competitor-lighthouse', organizationId, projectId]">{{ t("Inspect a separately selected competitor Lighthouse lab sample") }}</a>
          <a [routerLink]="['/app/competitor-page-formats', organizationId, projectId]">{{ t("Inspect separately selected competitor static content-element counts") }}</a>
          <a [routerLink]="['/app/competitor-page-dates', organizationId, projectId]">{{ t("Inspect separately selected competitor page article date declarations") }}</a>
          <a [routerLink]="['/app/competitor-page-headings', organizationId, projectId]">{{ t("Inspect separately selected competitor page literal headings") }}</a>
          <a [routerLink]="['/app/competitor-heading-topics', organizationId, projectId]">{{ t("Review unverified topic hypotheses from one saved heading observation") }}</a>
          <a [routerLink]="['/app/competitor-pages', organizationId, projectId]">{{ t("Inspect separately selected competitor page metadata") }}</a>
          <a [routerLink]="['/app/competitor-roots', organizationId, projectId]">{{ t("Inspect separately selected competitor root metadata") }}</a>
          <a [routerLink]="['/app/competitor-schema-roots', organizationId, projectId]">{{ t("Inspect separately selected competitor schema type labels") }}</a>
          <a [routerLink]="['/app/competitor-links-roots', organizationId, projectId]">{{ t("Inspect separately selected competitor root link categories") }}</a>
          <a [routerLink]="['/app/topics', organizationId, projectId]">{{ t("Discover and review source-backed topic candidates") }}</a>
          <a [routerLink]="['/app/visibility', organizationId, projectId]">{{ t("Review API-only visibility prompt methodology") }}</a>
          <a [routerLink]="['/app/visibility-samples', organizationId, projectId]">{{ t("Inspect private manual API-only answer samples") }}</a>
          <a [routerLink]="['/app/visibility-schedules', organizationId, projectId]">{{ t("Manage separate opt-in bounded API repeats") }}</a>
          <a [routerLink]="['/app/visibility-history', organizationId, projectId]">{{ t("Compare like-for-like API observation history") }}</a>
          <a [routerLink]="['/app/visibility-manual', organizationId, projectId]">{{ t("Review separate independently permitted human answer reports") }}</a>
          <a [routerLink]="['/app/visibility-discoverability', organizationId, projectId]">{{ t("Review source-supported discoverability proposals") }}</a>
          <a [routerLink]="['/app/bot-logs', organizationId, projectId]">{{ t("Inspect authorized partial bot-log requests") }}</a>
          <a [routerLink]="['/app/passive-headers', organizationId, projectId]">{{ t("Verify exact origin and explicitly inspect public response headers") }}</a>
          <a [routerLink]="['/app/passive-tls', organizationId, projectId]">{{ t("Separately permit and inspect one exact TLS handshake") }}</a>
          <a [routerLink]="['/app/passive-resources', organizationId, projectId]">{{ t("Separately permit and inspect static resource-reference candidates") }}</a>
          <a [routerLink]="['/app/passive-redirects', organizationId, projectId]">{{ t("Separately permit and inspect first-response Location metadata") }}</a>
          <a [routerLink]="['/app/passive-http-redirects', organizationId, projectId]">{{ t("Separately verify and inspect plaintext HTTP Location metadata") }}</a>
          <a [routerLink]="['/app/passive-redirect-chain', organizationId, projectId]">{{ t("Separately permit exact redirect targets and inspect a bounded original chain") }}</a>
          <a [routerLink]="['/app/briefs', organizationId, projectId]">{{ t("Review private sourced content briefs") }}</a>
          <a [routerLink]="['/app/content', organizationId, projectId]">{{ t("Write and review private content revisions") }}</a>
          <a [routerLink]="['/app/content-lifecycle', organizationId, projectId]">{{ t("Review substantive content quality and separate human lifecycle proposals") }}</a>
          @if (!environment.production) { <a [routerLink]="['/app/jobs', organizationId, projectId]">{{ t("Diagnostic job progress (development)") }}</a> }
        </nav>
        <section aria-labelledby="sources-title">
          <h2 id="sources-title">{{ t("Sources and freshness") }}</h2>
          <label for="source-filter">{{ t("Filter sources by availability") }}</label>
          <select id="source-filter" [value]="sourceFilter()" (change)="sourceFilter.set($any($event.target).value)">
            <option value="all">{{ t("All source states") }}</option><option value="current">{{ t("Current scope") }}</option>
            <option value="unavailable">{{ t("Disconnected, stale or unavailable") }}</option>
          </select>
          <label for="provider-filter">{{ t("Filter by recorded provider") }}</label>
          <select id="provider-filter" [value]="providerFilter()" (change)="providerFilter.set($any($event.target).value)">
            <option value="all">{{ t("All providers") }}</option>
            @for (provider of providerChoices(); track provider) { <option lang="en" [value]="provider">{{ provider }}</option> }
          </select>
          @if (sourceError()) { <p role="alert">{{ t("Source status unavailable; no missing source is treated as zero activity.") }}</p> }
          @else if (!sources().length) { <p>{{ t("No source record is connected. Manual onboarding and labeled CSV evidence remain possible where configured.") }}</p> }
          @else {
            @if (!filteredSources().length) { <p>{{ t("No sources match this filter; other source states remain available above.") }}</p> }
            <ul>@for (source of filteredSources(); track source.id) {
              <li><span lang="en">{{ source.provider }} · {{ source.state }}</span> · {{ t(source.scope_current ? 'current project scope' : 'stale/foreign scope unavailable') }}.
                @if (source.latest_import) { <span> {{ t("Latest file") }} <span lang="en">{{ source.latest_import.status }} / {{ source.latest_import.coverage_state }}</span>, {{ t("through") }} {{ source.latest_import.date_end }}. {{ t("Provider completeness") }} <span lang="en">{{ source.latest_import.source_completeness }}</span>.</span> }
                @if (source.sync) { <span> {{ t("API sync") }} <span lang="en">{{ source.sync.status }}</span>; {{ t("reported fresh through") }} {{ source.sync.fresh_through || t('unknown') }}; {{ t("quota") }} <span lang="en">{{ source.sync.quota_state || 'unknown' }}</span>; {{ t("error") }} <span lang="en">{{ source.sync.error_category }}</span>{{ source.sync.error_category ? '' : t('none recorded') }}.</span> }
                @if (source.data_status) { <span> <span lang="en">{{ source.data_status }}</span> — {{ t("conversion attribution is unavailable.") }}</span> }
              </li>
            }</ul>
          }
        </section>
        <section aria-labelledby="priorities-title">
          <h2 id="priorities-title">{{ t("Evidence candidates and human priority") }}</h2>
          <p>{{ t("Observed rising/declining rows are only recorded comparable source candidates, not complete traffic trends. No provider access or sufficiently complete history is inferred from an empty list.") }}</p>
          <label for="priority-filter">{{ t("Filter human-reviewed priority") }}</label>
          <select id="priority-filter" [value]="priorityFilter()" (change)="priorityFilter.set($any($event.target).value)">
            <option value="all">{{ t("All priorities") }}</option><option value="high">{{ t("High") }}</option><option value="medium">{{ t("Medium") }}</option>
            <option value="low">{{ t("Low") }}</option><option value="unprioritized">{{ t("Not reviewed") }}</option>
          </select>
          <label for="finding-date-filter">{{ t("Finding recorded on or after this UTC date") }}</label>
          <input id="finding-date-filter" type="date" [value]="findingSince()" (change)="findingSince.set($any($event.target).value)" />
          @if (findingError()) { <p role="alert">{{ t("Finding evidence unavailable; this is not “no issues found”.") }}</p> }
          @else if (!findings().length) { <p>{{ t("No stored finding candidates for this project. No clean audit is implied.") }}</p> }
          @else {
            @if (!filteredFindings().length) { <p>{{ t("No finding candidate matches this filter; do not infer a clean audit.") }}</p> }
            <ul>@for (finding of filteredFindings(); track finding.id) {
              <li><strong lang="">{{ finding.subject }}</strong> · <span lang="en">{{ finding.detector }}</span>.
                @if (finding.review) { {{ t("Human priority") }} <span lang="en">{{ finding.review.priority }}</span>, {{ t("effort") }} <span lang="en">{{ finding.review.estimated_effort }}</span>, {{ t("business relevance") }} <span lang="en">{{ finding.review.business_relevance }}</span>. }
                @else { {{ t("Not prioritized by a human") }}. }
                {{ t(finding.source_current ? 'Source current.' : 'Historical source; review unavailable.') }}
                <details><summary>{{ t("Why is this a candidate?") }}</summary>
                  <p>{{ t("Detector") }} <span lang="en">{{ finding.method_version }} · {{ finding.confidence }}</span> · {{ t("recorded") }} {{ finding.detected_at }}.
                    @if (finding.review) { <span> {{ t("Human review:") }} <span lang="">{{ finding.review.review_reason }}</span></span> }
                    {{ t("This is source-limited evidence, not a proven cause or action approval.") }}</p>
                </details>
              </li>
            }</ul>
          }
          @if (findingTruncated()) { <p>{{ t("Only the 50 most recent finding candidates are shown. Use the detailed evidence screen for context.") }}</p> }
        </section>
        <section aria-labelledby="actions-title">
          <h2 id="actions-title">{{ t("Manual actions and outcome limits") }}</h2>
          <label for="action-filter">{{ t("Filter manual action state") }}</label>
          <select id="action-filter" [value]="actionFilter()" (change)="actionFilter.set($any($event.target).value)">
            <option value="all">{{ t("All states") }}</option><option value="proposed">{{ t("Proposed") }}</option>
            <option value="accepted">{{ t("Accepted") }}</option><option value="in_progress">{{ t("In progress") }}</option>
            <option value="implemented">{{ t("Implementation logged") }}</option><option value="verified">{{ t("Technical review recorded") }}</option>
            <option value="outcome_reviewed">{{ t("Outcome reviewed") }}</option><option value="dismissed">{{ t("Dismissed") }}</option>
          </select>
          @if (actionError()) { <p role="alert">{{ t("Action history unavailable; no implementation or outcome can be assumed.") }}</p> }
          @else if (!actions().length) { <p>{{ t("No approved or recorded human action yet; a candidate is not an implementation.") }}</p> }
          @else {
            @if (!filteredActions().length) { <p>{{ t("No action has this recorded state.") }}</p> }
            <ul>@for (action of filteredActions(); track action.action_id) {
              <li><span lang="en">{{ action.action_kind }} · {{ action.state }}</span> · {{ t(action.source_current ? 'current source' : 'stale source') }}.
                <span lang="">{{ action.affected_urls.join(', ') }}</span> · {{ t("criteria:") }} <span lang="">{{ action.acceptance_criteria }}</span>.
                {{ t(action.implemented_at ? 'Implementation logged, outcome unproven without comparable follow-up.' : 'No implementation date.') }}
                <a [routerLink]="['/app/actions', organizationId, projectId]">{{ t("Inspect approval and change history") }}</a>
                @if (action.implemented_at) { <a [routerLink]="['/app/outcomes', organizationId, projectId, action.action_id]">{{ t("Inspect source-limited follow-up") }}</a> }
              </li>
            }</ul>
          }
        </section>
        <section aria-labelledby="local-title">
          <h2 id="local-title">{{ t("Local business context") }}</h2>
          @if (localError()) { <p role="alert">{{ t("Manual business review unavailable.") }}</p> }
          @else if (!locals().length) { <p>{{ t("No user-entered local assessment. Missing listing/profile facts are unknown, not an inconsistency.") }}</p> }
          @else { <p>{{ locals().length }} {{ t("manual review location(s). Provider profile eligibility and reviews remain unverified; changed configuration makes an older review stale.") }}</p> }
        </section>
        <details>
          <summary>{{ t("Evidence and measurement glossary") }}</summary>
          <dl><dt>{{ t("Candidate") }}</dt><dd>{{ t("A versioned source observation needing human review, not an approved change.") }}</dd>
            <dt>{{ t("Unknown") }}</dt><dd>{{ t("Missing, unavailable, disconnected or incomplete evidence; never a measured zero or a clean audit.") }}</dd>
            <dt>{{ t("Source freshness") }}</dt><dd>{{ t("A reported date/coverage from one property or export; not complete search demand.") }}</dd>
            <dt>{{ t("Implementation vs verification") }}</dt><dd>{{ t("Manual change log and later technical recheck are distinct. Search before/after changes are not causal proof.") }}</dd>
            <dt>{{ t("Cost and progress") }}</dt><dd>{{ t("Review per-source jobs and usage in onboarding; estimated AI spend is not a provider-reported actual charge.") }}</dd>
          </dl>
        </details>
      }
    </section>
  `,
  styles: `
    nav { display: flex; flex-wrap: wrap; gap: 0.75rem 1.25rem; }
    section { padding-block: 1rem; border-top: 1px solid #b9cfd5; overflow-wrap: anywhere; }
    li { margin-block: 0.7rem; }
  `,
})
export class ProjectDashboard implements OnInit {
  readonly environment = environment;
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  t(text: string) { return this.uiLanguage() === 'tr' ? dashboardTurkish[text] ?? text : text; }
  readonly loading = signal(true);
  readonly error = signal('');
  readonly projectName = signal('');
  readonly accessState = signal('');
  readonly accessError = signal(false);
  readonly sourceError = signal(false);
  readonly findingError = signal(false);
  readonly actionError = signal(false);
  readonly localError = signal(false);
  readonly sources = signal<Source[]>([]);
  readonly findings = signal<Finding[]>([]);
  readonly actions = signal<Action[]>([]);
  readonly locals = signal<Local[]>([]);
  readonly findingTruncated = signal(false);
  readonly sourceFilter = signal('all');
  readonly providerFilter = signal('all');
  readonly priorityFilter = signal('all');
  readonly findingSince = signal('');
  readonly actionFilter = signal('all');
  organizationId = 0;
  projectId = 0;
  private generation = 0;

  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi,
              private readonly destroyRef: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t('Evidence and action dashboard')} — OrganicSEOOps`));
  }

  ngOnInit() {
    void this.loadProductLanguage();
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      this.organizationId = Number(params.get('organizationId'));
      this.projectId = Number(params.get('projectId'));
      this.generation++;
      this.projectName.set(''); this.sources.set([]); this.findings.set([]); this.actions.set([]); this.locals.set([]);
      this.accessState.set(''); this.accessError.set(false);
      this.sourceError.set(false); this.findingError.set(false); this.actionError.set(false); this.localError.set(false);
      this.error.set(''); this.loading.set(true);
      this.sourceFilter.set('all'); this.providerFilter.set('all');
      this.priorityFilter.set('all'); this.findingSince.set(''); this.actionFilter.set('all');
      if (Number.isSafeInteger(this.organizationId) && this.organizationId > 0
          && Number.isSafeInteger(this.projectId) && this.projectId > 0) void this.load();
      else { this.loading.set(false); this.error.set('Select a current authorized project.'); }
    });
  }

  private async loadProductLanguage() {
    try {
      const result = await this.api.productLanguage();
      if (!this.destroyRef.destroyed && result.status === 200 && isProductLanguageResult(result.body)) {
        this.productLanguage.set(result.body['language']);
      }
    } catch { /* Keep English when the private preference is unavailable. */ }
  }

  async load() {
    const generation = ++this.generation;
    this.loading.set(true); this.error.set('');
    this.projectName.set(''); this.sources.set([]); this.findings.set([]); this.actions.set([]); this.locals.set([]);
    this.accessState.set(''); this.accessError.set(false);
    this.sourceError.set(false); this.findingError.set(false);
    this.actionError.set(false); this.localError.set(false); this.findingTruncated.set(false);
    try {
      const project = await this.api.projectOnboarding(this.organizationId, this.projectId);
      if (generation !== this.generation) return;
      const details = project.body['project'] as Record<string, unknown> | undefined;
      if (project.status !== 200 || details?.['id'] !== this.projectId
          || details['organization_id'] !== this.organizationId || typeof details['name'] !== 'string') throw new Error();
      this.projectName.set(details['name']);
      const [sources, findings, actions, locals, organizations] = await Promise.allSettled([
        this.api.projectSources(this.organizationId, this.projectId),
        this.api.projectFindings(this.organizationId, this.projectId),
        this.api.projectActions(this.organizationId, this.projectId),
        this.api.localAssessments(this.organizationId, this.projectId),
        this.api.organizations(),
      ]);
      if (generation !== this.generation) return;
      if (sources.status === 'fulfilled' && sources.value.status === 200
          && sources.value.body['project_id'] === this.projectId
          && Array.isArray(sources.value.body['sources'])) {
        this.sources.set((sources.value.body['sources'] as Record<string, unknown>[])
          .filter((row) => Number.isSafeInteger(row['id']) && typeof row['provider'] === 'string'
            && typeof row['state'] === 'string' && typeof row['scope_current'] === 'boolean')
          .map((row) => row as Source));
      } else this.sourceError.set(true);
      if (findings.status === 'fulfilled' && findings.value.status === 200
          && findings.value.body['project_id'] === this.projectId
          && Array.isArray(findings.value.body['findings'])) {
        this.findings.set((findings.value.body['findings'] as Record<string, unknown>[])
          .filter((row) => Number.isSafeInteger(row['id']) && typeof row['subject'] === 'string'
            && typeof row['detector'] === 'string' && typeof row['source_current'] === 'boolean')
          .map((row) => row as Finding));
        this.findingTruncated.set(findings.value.body['has_more'] === true);
      } else this.findingError.set(true);
      if (actions.status === 'fulfilled' && actions.value.status === 200
          && actions.value.body['project_id'] === this.projectId
          && Array.isArray(actions.value.body['actions'])) {
        this.actions.set((actions.value.body['actions'] as Record<string, unknown>[])
          .filter((row) => typeof row['action_id'] === 'string' && typeof row['state'] === 'string'
            && Array.isArray(row['affected_urls']) && typeof row['source_current'] === 'boolean')
          .map((row) => row as Action));
      } else this.actionError.set(true);
      if (locals.status === 'fulfilled' && locals.value.status === 200
          && locals.value.body['project_id'] === this.projectId
          && Array.isArray(locals.value.body['assessments'])) {
        this.locals.set((locals.value.body['assessments'] as Record<string, unknown>[])
          .filter((row) => typeof row['location_label'] === 'string'
            && typeof row['eligibility'] === 'string' && typeof row['source_current'] === 'boolean')
          .map((row) => row as Local));
      } else this.localError.set(true);
      if (organizations.status === 'fulfilled' && organizations.value.status === 200
          && Array.isArray(organizations.value.body['organizations'])) {
        const owned = (organizations.value.body['organizations'] as Record<string, unknown>[])
          .find((row) => row['id'] === this.organizationId);
        if (owned && typeof owned['access_state'] === 'string' && ['unavailable', 'pending_review', 'active', 'read_only', 'suspended']
          .includes(owned['access_state'])) this.accessState.set(owned['access_state']);
        else this.accessError.set(true);
      } else this.accessError.set(true);
    } catch {
      if (generation === this.generation) this.error.set('Dashboard context is unavailable for this project.');
    } finally {
      if (generation === this.generation) this.loading.set(false);
    }
  }

  filteredSources() {
    return this.sources().filter((item) => (this.providerFilter() === 'all' || item.provider === this.providerFilter())
      && (this.sourceFilter() === 'all'
        || this.sourceFilter() === 'current' && item.scope_current && item.state === 'active'
        || this.sourceFilter() === 'unavailable' && (!item.scope_current || item.state !== 'active'
          || item.data_status === 'exact_origin_attribution_unavailable')));
  }

  providerChoices() { return [...new Set(this.sources().map((item) => item.provider))]; }

  filteredFindings() {
    return this.findings().filter((item) => (!this.findingSince() || item.detected_at.slice(0, 10) >= this.findingSince())
      && (this.priorityFilter() === 'all'
        || this.priorityFilter() === 'unprioritized' && !item.review
        || item.review?.priority === this.priorityFilter()));
  }

  filteredActions() {
    return this.actions().filter((item) => this.actionFilter() === 'all' || item.state === this.actionFilter());
  }
}

const dashboardTurkish: Readonly<Record<string, string>> = {
  "Evidence and action dashboard": "Kanıt ve eylem panosu",
  "What matters, why, and the next human action": "Önemli olanlar, nedenleri ve insanın sonraki adımı",
  "Unreviewed Turkish dashboard interface draft in local development. Stored source/status values and other screens remain English; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe pano arayüzü taslağı. Kayıtlı kaynak/durum değerleri ve diğer ekranlar İngilizce kalır; iki dilli onay bekleniyor.",
  "Return to organization and project selection": "Kuruluş ve proje seçimine dön",
  "Loading this project's evidence. Earlier project data is cleared.": "Bu projenin kanıtları yükleniyor. Önceki proje verileri temizlendi.",
  "Current source observations, human priorities and actions appear separately. No composite SEO score, universal rank, guaranteed outcome, inferred conversion or automatic fix is calculated.": "Güncel kaynak gözlemleri, insan öncelikleri ve eylemler ayrı gösterilir. Birleşik SEO puanı, evrensel sıralama, garantili sonuç, çıkarımsal dönüşüm veya otomatik düzeltme hesaplanmaz.",
  "Organization access:": "Kuruluş erişimi:",
  "Trial expiry or read-only access is not evidence deletion or a reason to start new paid work.": "Deneme süresinin bitmesi veya salt okunur erişim, kanıtların silinmesi ya da yeni ücretli iş başlatma nedeni değildir.",
  "Entitlement state unavailable; do not assume this project can launch work.": "Yetki durumu kullanılamıyor; bu projenin iş başlatabildiğini varsaymayın.",
  "Project review destinations": "Proje inceleme bağlantıları",
  "Review source configuration and full findings": "Kaynak yapılandırmasını ve tüm bulguları incele",
  "Review first-audit progress and bounded next actions": "İlk denetim ilerlemesini ve sınırlı sonraki adımları incele",
  "Review intent/page mapping": "Niyet/sayfa eşlemesini incele",
  "Review assigned actions and outcomes": "Atanmış eylemleri ve sonuçları incele",
  "Review user-entered local business facts": "Kullanıcının girdiği yerel işletme bilgilerini incele",
  "Review independent website feedback and exact human replies": "Bağımsız web sitesi geri bildirimini ve insanların tam yanıtlarını incele",
  "Review manual local organic-link observations": "Elle kaydedilen yerel organik bağlantı gözlemlerini incele",
  "Authorized response-only Google profile/reviews": "Yetkilendirilmiş, yalnızca yanıtlama amaçlı Google profili/yorumları",
  "Export project evidence and manage report shares": "Proje kanıtlarını dışa aktar ve rapor paylaşımlarını yönet",
  "Inspect separately budgeted AI jobs and known/estimated costs": "Ayrı bütçelenmiş yapay zekâ işlerini ve bilinen/tahmini maliyetleri incele",
  "Research a selected topic from approved sources": "Seçili konuyu onaylı kaynaklardan araştır",
  "Review human authority prospects from exact stored research": "Saklanmış araştırmanın aynısından insanın değerlendireceği otorite adaylarını incele",
  "Review independent human link reports and separate own-target recovery evidence": "Bağımsız insan bağlantı raporlarını ve kendi hedefinize ait ayrı kurtarma kanıtlarını incele",
  "Request separately permissioned selected static-link verification": "Ayrıca izin verilmiş seçili statik bağlantı doğrulaması iste",
  "Inspect separately selected competitor page same-origin references": "Ayrıca seçilmiş rakip sayfasının aynı kökenli referanslarını incele",
  "Inspect a separately selected competitor Lighthouse lab sample": "Ayrıca seçilmiş rakip Lighthouse laboratuvar örneğini incele",
  "Inspect separately selected competitor static content-element counts": "Ayrıca seçilmiş rakip statik içerik öğesi sayılarını incele",
  "Inspect separately selected competitor page article date declarations": "Ayrıca seçilmiş rakip sayfasının makale tarihi beyanlarını incele",
  "Inspect separately selected competitor page literal headings": "Ayrıca seçilmiş rakip sayfasının aynen kaydedilmiş başlıklarını incele",
  "Review unverified topic hypotheses from one saved heading observation": "Kaydedilmiş tek başlık gözleminden doğrulanmamış konu varsayımlarını incele",
  "Inspect separately selected competitor page metadata": "Ayrıca seçilmiş rakip sayfasının meta verilerini incele",
  "Inspect separately selected competitor root metadata": "Ayrıca seçilmiş rakip kök sayfasının meta verilerini incele",
  "Inspect separately selected competitor schema type labels": "Ayrıca seçilmiş rakip şema türü etiketlerini incele",
  "Inspect separately selected competitor root link categories": "Ayrıca seçilmiş rakip kök bağlantı kategorilerini incele",
  "Discover and review source-backed topic candidates": "Kaynak destekli konu adaylarını keşfet ve incele",
  "Review API-only visibility prompt methodology": "Yalnızca API görünürlük istemi yöntemini incele",
  "Inspect private manual API-only answer samples": "Özel, elle kaydedilmiş yalnızca API yanıt örneklerini incele",
  "Manage separate opt-in bounded API repeats": "Ayrı ve isteğe bağlı sınırlı API tekrarlarını yönet",
  "Compare like-for-like API observation history": "Aynı koşullardaki API gözlem geçmişini karşılaştır",
  "Review separate independently permitted human answer reports": "Bağımsız olarak izin verilmiş ayrı insan yanıt raporlarını incele",
  "Review source-supported discoverability proposals": "Kaynak destekli keşfedilebilirlik önerilerini incele",
  "Inspect authorized partial bot-log requests": "Yetkilendirilmiş kısmi bot günlüğü isteklerini incele",
  "Verify exact origin and explicitly inspect public response headers": "Tam kökeni doğrula ve açıkça herkese açık yanıt başlıklarını incele",
  "Separately permit and inspect one exact TLS handshake": "Tek ve tam TLS el sıkışmasına ayrıca izin ver ve incele",
  "Separately permit and inspect static resource-reference candidates": "Statik kaynak referansı adaylarına ayrıca izin ver ve incele",
  "Separately permit and inspect first-response Location metadata": "İlk yanıtın Location meta verilerine ayrıca izin ver ve incele",
  "Separately verify and inspect plaintext HTTP Location metadata": "Düz metin HTTP Location meta verilerini ayrıca doğrula ve incele",
  "Separately permit exact redirect targets and inspect a bounded original chain": "Tam yönlendirme hedeflerine ayrıca izin ver ve sınırlı özgün zinciri incele",
  "Review private sourced content briefs": "Özel ve kaynaklı içerik özetlerini incele",
  "Write and review private content revisions": "Özel içerik revizyonlarını yaz ve incele",
  "Review substantive content quality and separate human lifecycle proposals": "Esaslı içerik kalitesini ve ayrı insan yaşam döngüsü önerilerini incele",
  "Diagnostic job progress (development)": "Tanısal iş ilerlemesi (geliştirme)",
  "Sources and freshness": "Kaynaklar ve güncellik",
  "Filter sources by availability": "Kaynakları kullanılabilirliğe göre filtrele",
  "All source states": "Tüm kaynak durumları",
  "Current scope": "Güncel kapsam",
  "Disconnected, stale or unavailable": "Bağlantısı kesilmiş, eski veya kullanılamayan",
  "Filter by recorded provider": "Kayıtlı sağlayıcıya göre filtrele",
  "All providers": "Tüm sağlayıcılar",
  "Source status unavailable; no missing source is treated as zero activity.": "Kaynak durumu kullanılamıyor; eksik kaynak sıfır etkinlik sayılmaz.",
  "No source record is connected. Manual onboarding and labeled CSV evidence remain possible where configured.": "Bağlı kaynak kaydı yok. Yapılandırıldığı yerde elle başlangıç ve etiketli CSV kanıtları kullanılabilir.",
  "No sources match this filter; other source states remain available above.": "Bu filtreye uyan kaynak yok; diğer kaynak durumları yukarıda kullanılabilir.",
  "current project scope": "güncel proje kapsamı",
  "stale/foreign scope unavailable": "eski/başka kapsam kullanılamıyor",
  "Latest file": "Son dosya",
  "through": "şu tarihe kadar",
  "Provider completeness": "Sağlayıcı bütünlüğü",
  "API sync": "API eşitlemesi",
  "reported fresh through": "bildirilen güncellik tarihi",
  "unknown": "bilinmiyor",
  "quota": "kota",
  "error": "hata",
  "none recorded": "kaydedilmemiş",
  "conversion attribution is unavailable.": "dönüşüm ilişkilendirmesi kullanılamıyor.",
  "Evidence candidates and human priority": "Kanıt adayları ve insan önceliği",
  "Observed rising/declining rows are only recorded comparable source candidates, not complete traffic trends. No provider access or sufficiently complete history is inferred from an empty list.": "Gözlenen artan/azalan satırlar yalnızca kaydedilmiş karşılaştırılabilir kaynak adaylarıdır; tam trafik eğilimleri değildir. Boş listeden sağlayıcı erişimi veya yeterince tam geçmiş çıkarılmaz.",
  "Filter human-reviewed priority": "İnsan tarafından incelenmiş önceliği filtrele",
  "All priorities": "Tüm öncelikler",
  "High": "Yüksek",
  "Medium": "Orta",
  "Low": "Düşük",
  "Not reviewed": "İncelenmemiş",
  "Finding recorded on or after this UTC date": "Bu UTC tarihinde veya sonrasında kaydedilmiş bulgu",
  "Finding evidence unavailable; this is not “no issues found”.": "Bulgu kanıtları kullanılamıyor; bu, “sorun bulunmadı” demek değildir.",
  "No stored finding candidates for this project. No clean audit is implied.": "Bu proje için saklanmış bulgu adayı yok. Sorunsuz denetim sonucu ima edilmez.",
  "No finding candidate matches this filter; do not infer a clean audit.": "Bu filtreye uyan bulgu adayı yok; sorunsuz denetim sonucu çıkarmayın.",
  "Human priority": "İnsan önceliği",
  "effort": "çaba",
  "business relevance": "işle ilgisi",
  "Not prioritized by a human": "İnsan tarafından önceliklendirilmemiş",
  "Source current.": "Kaynak güncel.",
  "Historical source; review unavailable.": "Geçmiş kaynak; inceleme kullanılamıyor.",
  "Why is this a candidate?": "Bu neden bir aday?",
  "Detector": "Tespit yöntemi",
  "recorded": "kaydedilme tarihi",
  "Human review:": "İnsan incelemesi:",
  "This is source-limited evidence, not a proven cause or action approval.": "Bu, kaynakla sınırlı kanıttır; kanıtlanmış neden veya eylem onayı değildir.",
  "Only the 50 most recent finding candidates are shown. Use the detailed evidence screen for context.": "Yalnızca en son 50 bulgu adayı gösterilir. Bağlam için ayrıntılı kanıt ekranını kullanın.",
  "Manual actions and outcome limits": "Elle yapılan eylemler ve sonuç sınırları",
  "Filter manual action state": "Elle yapılan eylem durumunu filtrele",
  "All states": "Tüm durumlar",
  "Proposed": "Önerilmiş",
  "Accepted": "Kabul edilmiş",
  "In progress": "Devam ediyor",
  "Implementation logged": "Uygulama kaydedilmiş",
  "Technical review recorded": "Teknik inceleme kaydedilmiş",
  "Outcome reviewed": "Sonuç incelenmiş",
  "Dismissed": "Reddedilmiş",
  "Action history unavailable; no implementation or outcome can be assumed.": "Eylem geçmişi kullanılamıyor; uygulama veya sonuç varsayılamaz.",
  "No approved or recorded human action yet; a candidate is not an implementation.": "Henüz onaylı veya kaydedilmiş insan eylemi yok; aday, uygulama değildir.",
  "No action has this recorded state.": "Bu kayıtlı durumda eylem yok.",
  "current source": "güncel kaynak",
  "stale source": "eski kaynak",
  "criteria:": "ölçütler:",
  "Implementation logged, outcome unproven without comparable follow-up.": "Uygulama kaydedilmiş; karşılaştırılabilir takip olmadan sonuç kanıtlanmamıştır.",
  "No implementation date.": "Uygulama tarihi yok.",
  "Inspect approval and change history": "Onay ve değişiklik geçmişini incele",
  "Inspect source-limited follow-up": "Kaynakla sınırlı takibi incele",
  "Local business context": "Yerel işletme bağlamı",
  "Manual business review unavailable.": "Elle yapılan işletme incelemesi kullanılamıyor.",
  "No user-entered local assessment. Missing listing/profile facts are unknown, not an inconsistency.": "Kullanıcının girdiği yerel değerlendirme yok. Eksik listeleme/profil bilgileri bilinmez; tutarsızlık sayılmaz.",
  "manual review location(s). Provider profile eligibility and reviews remain unverified; changed configuration makes an older review stale.": "elle incelenen konum. Sağlayıcı profili uygunluğu ve yorumları doğrulanmamıştır; değişen yapılandırma eski incelemeyi geçersiz kılar.",
  "Evidence and measurement glossary": "Kanıt ve ölçüm sözlüğü",
  "Candidate": "Aday",
  "A versioned source observation needing human review, not an approved change.": "İnsan incelemesi gerektiren sürümlenmiş kaynak gözlemi; onaylanmış değişiklik değildir.",
  "Unknown": "Bilinmiyor",
  "Missing, unavailable, disconnected or incomplete evidence; never a measured zero or a clean audit.": "Eksik, kullanılamayan, bağlantısı kesilmiş veya tamamlanmamış kanıt; asla ölçülmüş sıfır veya sorunsuz denetim sonucu değildir.",
  "Source freshness": "Kaynak güncelliği",
  "A reported date/coverage from one property or export; not complete search demand.": "Tek mülk veya dışa aktarımdan bildirilen tarih/kapsam; tam arama talebi değildir.",
  "Implementation vs verification": "Uygulama ve doğrulama",
  "Manual change log and later technical recheck are distinct. Search before/after changes are not causal proof.": "Elle tutulan değişiklik kaydı ile sonraki teknik yeniden kontrol ayrıdır. Aramadaki önce/sonra değişimleri nedensellik kanıtı değildir.",
  "Cost and progress": "Maliyet ve ilerleme",
  "Review per-source jobs and usage in onboarding; estimated AI spend is not a provider-reported actual charge.": "Başlangıçta kaynak başına işleri ve kullanımı inceleyin; tahmini yapay zekâ harcaması, sağlayıcının bildirdiği gerçek ücret değildir.",
  "Select a current authorized project.": "Güncel ve yetkili bir proje seçin.",
  "Dashboard context is unavailable for this project.": "Bu proje için pano bağlamı kullanılamıyor."
};
