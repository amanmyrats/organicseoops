import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, effect, OnInit, signal, computed } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi } from '../account/account-api';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';

type Candidate = { id: number; query: string; detector: string };
type Review = { review_id: number; cluster_id: string; revision: number; label: string; market: string; language: string;
  intent: string; page_kind: string; preferred_page: string; reason: string; source_finding_ids: number[];
  manual_topics: string[]; source_terms: string[]; source_kind: string;
  proposed_action: string; action_reason: string; affected_page: string; proposal_state: string;
  source_current: boolean; page_attribution: string; created_at: string };

function isReview(value: unknown): value is Review {
  if (!value || typeof value !== 'object') return false;
  const row = value as Record<string, unknown>;
  return Number.isSafeInteger(row['review_id']) && typeof row['cluster_id'] === 'string' && Number.isSafeInteger(row['revision'])
    && typeof row['label'] === 'string' && typeof row['market'] === 'string'
    && typeof row['language'] === 'string' && typeof row['intent'] === 'string'
    && typeof row['page_kind'] === 'string' && typeof row['preferred_page'] === 'string'
    && typeof row['reason'] === 'string' && Array.isArray(row['source_finding_ids'])
    && row['source_finding_ids'].every((id: unknown) => Number.isSafeInteger(id))
    && Array.isArray(row['manual_topics']) && row['manual_topics'].every((item: unknown) => typeof item === 'string')
    && Array.isArray(row['source_terms']) && row['source_terms'].every((item: unknown) => typeof item === 'string')
    && typeof row['source_kind'] === 'string'
    && ['manual_seed_no_search_observation', 'csv_query_candidate_not_joined_to_page'].includes(row['source_kind'])
    && typeof row['proposed_action'] === 'string' && typeof row['action_reason'] === 'string'
    && typeof row['affected_page'] === 'string' && row['proposal_state'] === 'unapproved_human_proposal'
    && typeof row['source_current'] === 'boolean'
    && row['page_attribution'] === 'human_selected_no_joint_query_page_evidence'
    && typeof row['created_at'] === 'string';
}

@Component({
  selector: 'app-intent-mapping',
  imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="intent-title">
      <h1 id="intent-title">{{ t("Review intent and preferred pages") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish intent-mapping interface draft in local development. Stored source/status values and other screens remain English; bilingual approval is pending.") }}</p> }
      <p><a routerLink="/app">{{ t("Return to workspace") }}</a></p>
      <p><a [routerLink]="['/app/actions', organizationId, projectId]">{{ t("Review human-approved action progress and manual change history") }}</a></p>
      <p>{{ t("Queries come from source-limited, complete Search Console CSV findings.") }} <strong>{{ t("These separate exports do not show which page appeared for a query or prove cannibalization.") }}</strong> {{ t("Your chosen page and intent are a human mapping, not a ranking or conversion observation.") }}</p>
      @if (loading()) { <p role="status">{{ t("Loading current project source and mapping reviews.") }}</p> }
      @if (error()) { <p role="alert">{{ t(error()) }}</p> }
      @if (!loading() && !error()) {
        <p>{{ t("Configured market:") }} <span lang="">{{ market() }}</span>{{ market() ? '' : t('not set') }}. {{ t("Selected SEO languages:") }} <span lang="en">{{ languages().join(', ') }}</span>{{ languages().length ? '' : t('not set') }}.</p>
        <button type="button" (click)="load()" [disabled]="busy()">{{ t("Refresh source and reviews") }}</button>
        @if (truncated()) { <p>{{ t("Only the first 50 current review groups and findings are shown.") }}</p> }
        @if (!clusters().length) { <p>{{ t("No intent/page mapping has been reviewed for this project.") }}</p> }
        <ul [attr.aria-label]="t('Human-reviewed intent mapping')">
          @for (review of clusters(); track review.cluster_id) {
            <li>
              <h2><span lang="">{{ review.label }}</span> · {{ t("revision") }} {{ review.revision }}</h2>
              <p><span lang="">{{ review.market }}</span> / <span lang="en">{{ review.language }}</span> · {{ t("intent:") }} <span lang="en">{{ review.intent }}</span> · {{ t("page:") }} <span lang="en">{{ review.page_kind }}</span>
                @if (review.preferred_page) { <span lang=""> {{ review.preferred_page }}</span> }
              </p>
              <p>{{ t("Query/page relationship: human-selected; no joint source evidence.") }} {{ t(review.source_current ? 'Query source current for review.' : 'Historical or revoked query source; editing unavailable.') }}</p>
              @if (review.source_current) {
                <p>{{ t(review.source_kind === 'manual_seed_no_search_observation' ? 'Manually entered project topics (no search observations)' : 'Source query candidates') }}: <span lang="">{{ review.source_terms.join(', ') }}</span></p>
              }
              <p>{{ t("Reason:") }} <span lang="">{{ review.reason }}</span></p>
              <p>{{ t("Human action proposal:") }} <span lang="en">{{ review.proposed_action }}</span> {{ t("(not approved or executed).") }}
                @if (review.affected_page) { <span>{{ t("Possible affected source page:") }} <span lang="">{{ review.affected_page }}</span>.</span> }
                @if (review.action_reason) { <span> {{ t("Rationale:") }} <span lang="">{{ review.action_reason }}</span></span> }
              </p>
              @if (review.source_current) { <a [routerLink]="['/app/research', organizationId, projectId]" [queryParams]="{mapping: review.review_id}">{{ t("Research this reviewed intent mapping") }}</a> }
              <button type="button" (click)="history(review.cluster_id)">{{ t("Inspect correction history") }}</button>
              @if (canManage() && review.source_current) {
                <button type="button" (click)="edit(review)">{{ t("Correct this mapping") }}</button>
              }
            </li>
          }
        </ul>
        @if (historyRows().length) {
          <section aria-labelledby="history-title">
            <h2 id="history-title">{{ t("Previous reviewed revisions") }}</h2>
            <ol>
              @for (row of historyRows(); track row.cluster_id + ':' + row.revision) {
                <li>{{ t("Revision") }} {{ row.revision }} · {{ row.created_at }} · <span lang="">{{ row.label }}</span> · <span lang="en">{{ row.intent }} · {{ row.page_kind }}</span> · <span lang="">{{ row.reason }}</span> · {{ t("action proposal") }} <span lang="en">{{ row.proposed_action }}</span> {{ t("(not approved)") }}</li>
              }
            </ol>
          </section>
        }
        @if (canManage()) {
          <section aria-labelledby="intent-form-title">
            <h2 id="intent-form-title">{{ t(editing() ? 'Correct the selected mapping' : 'Create a human mapping') }}</h2>
            <p>{{ t("Review an existing relevant page before proposing a new one. Merge, redirect and retire remain unapproved proposals; no page is changed or removed here.") }}</p>
            @if ((!candidates().length && !seedTopics().length) || !languages().length || !market()) {
              <p>{{ t("Set a project market/language and record complete query findings or user-entered seed topics before mapping.") }}</p>
            } @else {
              <form (submit)="save($event)">
                <fieldset><legend>{{ t("Select up to ten current query findings (measured source candidates)") }}</legend>
                  @for (candidate of candidates(); track candidate.id) {
                    <label><input type="checkbox" [checked]="selected().includes(candidate.id)" (change)="toggle(candidate.id)" />
                      <span lang="">{{ candidate.query }}</span> · <span lang="en">{{ candidate.detector }}</span></label>
                  }
                </fieldset>
                <fieldset><legend>{{ t("Or select current project seed topics (not measured search queries)") }}</legend>
                  @for (topic of seedTopics(); track topic) {
                    <label><input type="checkbox" [checked]="selectedTopics().includes(topic)" (change)="toggleTopic(topic)" />
                      <span lang="">{{ topic }}</span></label>
                  }
                </fieldset>
                <label for="intent-label">{{ t("Cluster name") }}</label>
                <input lang="" id="intent-label" name="label" maxlength="120" required [value]="editing()?.label || ''" />
                <label for="intent-language">{{ t("Project SEO language") }}</label>
                <select id="intent-language" name="language" required>
                  @for (language of languages(); track language) { <option lang="en" [value]="language" [selected]="language === editing()?.language">{{ language }}</option> }
                </select>
                <label for="intent-kind">{{ t("Reviewed intent") }}</label>
                <select id="intent-kind" name="intent">
                  @for (kind of intentKinds; track kind) { <option lang="en" [value]="kind" [selected]="kind === editing()?.intent">{{ kind }}</option> }
                </select>
                <label for="page-kind">{{ t("Preferred page state") }}</label>
                <select id="page-kind" name="page_kind">
                  @for (kind of pageKinds; track kind) { <option lang="en" [value]="kind" [selected]="kind === editing()?.page_kind">{{ kind }}</option> }
                </select>
                <label for="preferred-page">{{ t("Existing-unverified or proposed project page (leave blank when unmapped)") }}</label>
                <input lang="" id="preferred-page" name="preferred_page" type="url" maxlength="512" [value]="editing()?.preferred_page || ''" />
                <label for="intent-reason">{{ t("Why this human mapping fits the query evidence") }}</label>
                <textarea lang="" id="intent-reason" name="reason" required maxlength="500">{{ editing()?.reason || '' }}</textarea>
                <label for="intent-action">{{ t("Optional human action proposal (never applies a website change)") }}</label>
                <select id="intent-action" name="proposed_action" [value]="proposedAction()" (change)="proposedAction.set($any($event.target).value)">
                  @for (action of actionKinds; track action) { <option lang="en" [value]="action">{{ action }}</option> }
                </select>
                <label for="intent-affected-page">{{ t("Affected source page for merge/redirect proposals (same project; otherwise blank)") }}</label>
                <input lang="" id="intent-affected-page" name="affected_page" type="url" maxlength="512" [value]="editing()?.affected_page || ''" />
                <label for="intent-action-reason">{{ t("Reason for the optional action (required when selected)") }}</label>
                <textarea lang="" id="intent-action-reason" name="action_reason" maxlength="500" [required]="proposedAction() !== 'unselected'">{{ editing()?.action_reason || '' }}</textarea>
                <button type="submit" [disabled]="busy() || (!selected().length && !selectedTopics().length)">{{ t("Save reviewed mapping revision") }}</button>
                @if (editing()) { <button type="button" (click)="cancelEdit()">{{ t("Cancel correction") }}</button> }
              </form>
            }
          </section>
        }
        @if (message()) { <p role="status">{{ t(message()) }}</p> }
      }
    </section>
  `,
  styles: `
    fieldset { display: grid; gap: 0.5rem; }
    form { display: grid; gap: 0.6rem; max-width: 45rem; }
    li { margin-block: 1.25rem; }
  `,
})
export class IntentMapping implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  t(text: string) { return this.uiLanguage() === 'tr' ? intentTurkish[text] ?? text : text; }
  readonly intentKinds = ['unknown', 'informational', 'commercial', 'navigational', 'transactional', 'local', 'mixed'];
  readonly pageKinds = ['unmapped', 'existing_unverified', 'proposed'];
  readonly actionKinds = ['unselected', 'keep', 'refresh', 'merge', 'redirect', 'retire', 'create'];
  readonly loading = signal(true);
  readonly error = signal('');
  readonly message = signal('');
  readonly market = signal('');
  readonly languages = signal<string[]>([]);
  readonly canManage = signal(false);
  readonly candidates = signal<Candidate[]>([]);
  readonly seedTopics = signal<string[]>([]);
  readonly clusters = signal<Review[]>([]);
  readonly historyRows = signal<Review[]>([]);
  readonly truncated = signal(false);
  readonly selected = signal<number[]>([]);
  readonly selectedTopics = signal<string[]>([]);
  readonly editing = signal<Review | null>(null);
  readonly proposedAction = signal('unselected');
  readonly busy = signal(false);
  private generation = 0;
  private requestKey = '';
  organizationId = 0;
  projectId = 0;

  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi,
              private readonly destroyRef: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t('Source-aware intent mapping')} — OrganicSEOOps`));
  }

  ngOnInit() {
    void this.loadProductLanguage();
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      this.organizationId = Number(params.get('organizationId'));
      this.projectId = Number(params.get('projectId'));
      this.reset();
      if (Number.isSafeInteger(this.organizationId) && this.organizationId > 0
          && Number.isSafeInteger(this.projectId) && this.projectId > 0) void this.load();
      else { this.loading.set(false); this.error.set('Select an authorized project.'); }
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

  private reset() {
    this.generation++;
    this.clusters.set([]);
    this.candidates.set([]);
    this.selected.set([]);
    this.selectedTopics.set([]);
    this.editing.set(null);
    this.proposedAction.set('unselected');
    this.historyRows.set([]);
    this.canManage.set(false);
    this.market.set('');
    this.languages.set([]);
    this.seedTopics.set([]);
    this.truncated.set(false);
    this.requestKey = '';
    this.busy.set(false);
    this.message.set('');
    this.error.set('');
    this.loading.set(true);
  }

  async load() {
    const generation = ++this.generation;
    this.loading.set(true);
    this.error.set('');
    this.clusters.set([]);
    this.candidates.set([]);
    this.seedTopics.set([]);
    this.canManage.set(false);
    this.historyRows.set([]);
    try {
      const [onboarding, findings, clusters] = await Promise.all([
        this.api.projectOnboarding(this.organizationId, this.projectId),
        this.api.projectFindings(this.organizationId, this.projectId),
        this.api.intentClusters(this.organizationId, this.projectId),
      ]);
      if (generation !== this.generation) return;
      if ([onboarding.status, findings.status, clusters.status].some((status) => status !== 200)
          || !onboarding.body['project'] || !onboarding.body['configuration']
          || findings.body['project_id'] !== this.projectId || clusters.body['project_id'] !== this.projectId
          || !Array.isArray(findings.body['findings']) || !Array.isArray(clusters.body['clusters'])) throw new Error();
      const project = onboarding.body['project'] as Record<string, unknown>;
      const config = onboarding.body['configuration'] as Record<string, unknown>;
      if (project['id'] !== this.projectId || project['organization_id'] !== this.organizationId
          || typeof project['role'] !== 'string' || !['owner', 'admin', 'member', 'viewer'].includes(project['role'])
          || config['project_id'] !== this.projectId
          || typeof config['target_country'] !== 'string' || !Array.isArray(config['target_languages'])
          || !config['target_languages'].every((value: unknown) => typeof value === 'string')
          || !Array.isArray(config['seed_topics'])
          || !config['seed_topics'].every((value: unknown) => typeof value === 'string')) throw new Error();
      const rows = (clusters.body['clusters'] as unknown[]);
      if (!rows.every(isReview)) throw new Error();
      this.market.set(config['target_country']);
      this.languages.set(config['target_languages']);
      this.seedTopics.set(config['seed_topics']);
      this.canManage.set(['owner', 'admin'].includes(project['role']));
      this.clusters.set(rows as Review[]);
      this.truncated.set(findings.body['has_more'] === true || clusters.body['has_more'] === true);
      this.candidates.set((findings.body['findings'] as Record<string, unknown>[])
        .filter((row) => Number.isSafeInteger(row['id']) && row['source_current'] === true
          && Number.isSafeInteger(row['source_metric_id']) && typeof row['subject'] === 'string'
          && row['evidence'] && typeof row['evidence'] === 'object'
          && (row['evidence'] as Record<string, unknown>)['dimension'] === 'query')
        .slice(0, 50).map((row) => ({ id: Number(row['id']), query: String(row['subject']),
          detector: String(row['detector']) })));
    } catch {
      if (generation === this.generation) this.error.set('Intent evidence is unavailable for this project or session.');
    } finally {
      if (generation === this.generation) this.loading.set(false);
    }
  }

  toggle(id: number) {
    const ids = this.selected();
    this.selected.set(ids.includes(id) ? ids.filter((value) => value !== id)
      : ids.length < 10 ? [...ids, id] : ids);
    if (this.selected().length) this.selectedTopics.set([]);
  }

  toggleTopic(topic: string) {
    const topics = this.selectedTopics();
    this.selectedTopics.set(topics.includes(topic) ? topics.filter((value) => value !== topic)
      : topics.length < 10 ? [...topics, topic] : topics);
    if (this.selectedTopics().length) this.selected.set([]);
  }

  edit(review: Review) {
    this.editing.set(review);
    this.proposedAction.set(review.proposed_action);
    this.selected.set(review.source_finding_ids.filter((id) => this.candidates().some((item) => item.id === id)));
    this.selectedTopics.set(review.manual_topics.filter((topic) => this.seedTopics().includes(topic)));
    this.message.set('Correcting a stored human decision; original revisions remain inspectable.');
    this.requestKey = '';
  }

  cancelEdit() { this.editing.set(null); this.proposedAction.set('unselected'); this.selected.set([]); this.selectedTopics.set([]); this.requestKey = ''; this.message.set(''); }

  async history(clusterId: string) {
    const generation = this.generation;
    this.historyRows.set([]);
    try {
      const response = await this.api.intentClusterHistory(this.organizationId, this.projectId, clusterId);
      if (generation !== this.generation) return;
      if (response.status !== 200 || response.body['project_id'] !== this.projectId
          || !Array.isArray(response.body['history']) || !(response.body['history'] as unknown[]).every(isReview)) throw new Error();
      this.historyRows.set(response.body['history'] as Review[]);
    } catch {
      if (generation === this.generation) this.message.set('Correction history is unavailable. Refresh this project.');
    }
  }

  async save(event: Event) {
    event.preventDefault();
    if (this.busy() || !this.canManage()
        || this.selected().length + this.selectedTopics().length < 1
        || this.selected().length + this.selectedTopics().length > 10) return;
    const form = event.target as HTMLFormElement;
    if (!form.reportValidity()) return;
    const values = new FormData(form);
    const current = this.editing();
    const generation = this.generation;
    this.requestKey ||= crypto.randomUUID();
    const data: Record<string, unknown> = {
      request_key: this.requestKey, label: String(values.get('label') || ''),
      source_finding_ids: this.selected(), manual_topics: this.selectedTopics(),
      intent: String(values.get('intent') || ''),
      page_kind: String(values.get('page_kind') || ''), preferred_page: String(values.get('preferred_page') || ''),
      reason: String(values.get('reason') || ''), language: String(values.get('language') || ''),
      proposed_action: String(values.get('proposed_action') || ''),
      affected_page: String(values.get('affected_page') || ''),
      action_reason: String(values.get('action_reason') || ''),
    };
    if (current) data['expected_revision'] = current.revision;
    this.busy.set(true);
    this.message.set('');
    try {
      const result = await this.api.saveIntentCluster(this.organizationId, this.projectId, data, current?.cluster_id);
      if (generation !== this.generation) return;
      const row = result.body['cluster'];
      if (![200, 201].includes(result.status) || result.body['project_id'] !== this.projectId || !isReview(row)
          || row.revision !== (current ? current.revision + 1 : 1)
          || current && row.cluster_id !== current.cluster_id) throw new Error();
      this.requestKey = '';
      this.selected.set([]);
      this.selectedTopics.set([]);
      this.editing.set(null);
      this.proposedAction.set('unselected');
      form.reset();
      this.busy.set(false);
      await this.load();
      if (generation + 1 === this.generation) this.message.set('Human mapping saved. Query/page attribution is still unverified.');
    } catch {
      if (generation === this.generation) this.message.set('Mapping outcome is unknown or changed. Refresh before retrying with the same request.');
    } finally {
      if (generation === this.generation) this.busy.set(false);
    }
  }
}

const intentTurkish: Readonly<Record<string, string>> = {
  "Source-aware intent mapping": "Kaynakları dikkate alan niyet eşlemesi",
  "Review intent and preferred pages": "Niyet ve tercih edilen sayfaları incele",
  "Unreviewed Turkish intent-mapping interface draft in local development. Stored source/status values and other screens remain English; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe niyet eşleme arayüzü taslağı. Kayıtlı kaynak/durum değerleri ve diğer ekranlar İngilizce kalır; iki dilli onay bekleniyor.",
  "Return to workspace": "Çalışma alanına dön",
  "Review human-approved action progress and manual change history": "İnsan tarafından onaylanmış eylem ilerlemesini ve elle tutulan değişiklik geçmişini incele",
  "Queries come from source-limited, complete Search Console CSV findings.": "Sorgular, kaynakla sınırlı ve tam Search Console CSV bulgularından gelir.",
  "These separate exports do not show which page appeared for a query or prove cannibalization.": "Bu ayrı dışa aktarımlar bir sorguda hangi sayfanın göründüğünü göstermez ve anahtar kelime yamyamlığını kanıtlamaz.",
  "Your chosen page and intent are a human mapping, not a ranking or conversion observation.": "Seçtiğiniz sayfa ve niyet, insan eşlemesidir; sıralama veya dönüşüm gözlemi değildir.",
  "Loading current project source and mapping reviews.": "Güncel proje kaynağı ve eşleme incelemeleri yükleniyor.",
  "Configured market:": "Yapılandırılmış pazar:",
  "Selected SEO languages:": "Seçili SEO dilleri:",
  "not set": "ayarlanmamış",
  "Refresh source and reviews": "Kaynağı ve incelemeleri yenile",
  "Only the first 50 current review groups and findings are shown.": "Yalnızca ilk 50 güncel inceleme grubu ve bulgu gösterilir.",
  "No intent/page mapping has been reviewed for this project.": "Bu proje için incelenmiş niyet/sayfa eşlemesi yok.",
  "Human-reviewed intent mapping": "İnsan tarafından incelenmiş niyet eşlemesi",
  "revision": "revizyon",
  "intent:": "niyet:",
  "page:": "sayfa:",
  "Query/page relationship: human-selected; no joint source evidence.": "Sorgu/sayfa ilişkisi: insan tarafından seçilmiş; ortak kaynak kanıtı yok.",
  "Query source current for review.": "Sorgu kaynağı inceleme için güncel.",
  "Historical or revoked query source; editing unavailable.": "Geçmiş veya iptal edilmiş sorgu kaynağı; düzenleme kullanılamıyor.",
  "Manually entered project topics (no search observations)": "Elle girilmiş proje konuları (arama gözlemi yok)",
  "Source query candidates": "Kaynak sorgu adayları",
  "Reason:": "Gerekçe:",
  "Human action proposal:": "İnsan eylem önerisi:",
  "(not approved or executed).": "(onaylanmamış veya uygulanmamış).",
  "Possible affected source page:": "Etkilenebilecek kaynak sayfa:",
  "Rationale:": "Açıklama:",
  "Research this reviewed intent mapping": "İncelenmiş bu niyet eşlemesini araştır",
  "Inspect correction history": "Düzeltme geçmişini incele",
  "Correct this mapping": "Bu eşlemeyi düzelt",
  "Previous reviewed revisions": "Önceki incelenmiş revizyonlar",
  "Revision": "Revizyon",
  "action proposal": "eylem önerisi",
  "(not approved)": "(onaylanmamış)",
  "Correct the selected mapping": "Seçili eşlemeyi düzelt",
  "Create a human mapping": "İnsan eşlemesi oluştur",
  "Review an existing relevant page before proposing a new one. Merge, redirect and retire remain unapproved proposals; no page is changed or removed here.": "Yeni sayfa önermeden önce mevcut ilgili sayfayı inceleyin. Birleştirme, yönlendirme ve yayından kaldırma onaylanmamış önerilerdir; burada hiçbir sayfa değiştirilmez veya kaldırılmaz.",
  "Set a project market/language and record complete query findings or user-entered seed topics before mapping.": "Eşlemeden önce proje pazarı/dili ayarlayın ve tam sorgu bulgularını veya kullanıcının girdiği başlangıç konularını kaydedin.",
  "Select up to ten current query findings (measured source candidates)": "En fazla on güncel sorgu bulgusu seçin (ölçülmüş kaynak adayları)",
  "Or select current project seed topics (not measured search queries)": "Veya güncel proje başlangıç konularını seçin (ölçülmüş arama sorguları değildir)",
  "Cluster name": "Küme adı",
  "Project SEO language": "Proje SEO dili",
  "Reviewed intent": "İncelenmiş niyet",
  "Preferred page state": "Tercih edilen sayfa durumu",
  "Existing-unverified or proposed project page (leave blank when unmapped)": "Mevcut ve doğrulanmamış veya önerilen proje sayfası (eşlenmemişse boş bırakın)",
  "Why this human mapping fits the query evidence": "Bu insan eşlemesi sorgu kanıtlarına neden uyuyor",
  "Optional human action proposal (never applies a website change)": "İsteğe bağlı insan eylem önerisi (asla web sitesi değişikliği uygulamaz)",
  "Affected source page for merge/redirect proposals (same project; otherwise blank)": "Birleştirme/yönlendirme önerileri için etkilenen kaynak sayfa (aynı proje; diğer durumlarda boş)",
  "Reason for the optional action (required when selected)": "İsteğe bağlı eylemin gerekçesi (seçildiğinde zorunlu)",
  "Save reviewed mapping revision": "İncelenmiş eşleme revizyonunu kaydet",
  "Cancel correction": "Düzeltmeyi iptal et",
  "Select an authorized project.": "Yetkili bir proje seçin.",
  "Intent evidence is unavailable for this project or session.": "Bu proje veya oturum için niyet kanıtları kullanılamıyor.",
  "Correcting a stored human decision; original revisions remain inspectable.": "Kaydedilmiş insan kararı düzeltiliyor; özgün revizyonlar incelenebilir durumda kalır.",
  "Correction history is unavailable. Refresh this project.": "Düzeltme geçmişi kullanılamıyor. Bu projeyi yenileyin.",
  "Human mapping saved. Query/page attribution is still unverified.": "İnsan eşlemesi kaydedildi. Sorgu/sayfa ilişkilendirmesi hâlâ doğrulanmamış.",
  "Mapping outcome is unknown or changed. Refresh before retrying with the same request.": "Eşleme sonucu bilinmiyor veya değişmiş. Aynı istekle yeniden denemeden önce yenileyin."
};
