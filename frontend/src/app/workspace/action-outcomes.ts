import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, effect, OnInit, signal, computed } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi } from '../account/account-api';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';

type Source = { id: number; label: string };
type Export = { id: number; date_start: string; date_end: string; created_at: string };
type Metric = { state: string; previous: string | null; current: string | null;
  absolute_change: string | null; relative_change: string | null };
type Outcome = { id: number; action_revision: number; source_current: boolean; recorded_at: string;
  report: { page: string; implementation_date: string; coverage: string; reporting_lag_days: number;
    gap_days: number; before: { import_id: number; start: string; end: string };
    after: { import_id: number; start: string; end: string }; search_metrics: Record<string, Metric>;
    conversion: { state: string }; interpretation: string } };
type CrawlChoice = { id: number; completed_at: string };
type Technical = { id: number; action_revision: number; report: { interpretation: string;
  previous: { crawl_run_id: number; completed_at: string };
  current: { crawl_run_id: number; completed_at: string };
  urls: { url: string; state: string; previous: { status_code: number | null; title: string } | null;
    current: { status_code: number | null; title: string } | null;
    changes: Record<string, { previous: unknown; current: unknown }> | null }[] } };

function isOutcome(value: unknown, actionId: string): value is Outcome {
  if (!value || typeof value !== 'object') return false;
  const row = value as Record<string, unknown>;
  if (!Number.isSafeInteger(row['id']) || row['action_id'] !== actionId
      || !Number.isSafeInteger(row['action_revision']) || typeof row['source_current'] !== 'boolean'
      || typeof row['recorded_at'] !== 'string' || !row['report'] || typeof row['report'] !== 'object') return false;
  const report = row['report'] as Record<string, unknown>;
  return report['method_version'] === 'gsc-csv-page-outcome-v1'
    && report['interpretation'] === 'observed_comparable_page_rows_not_causal_uplift'
    && typeof report['page'] === 'string' && typeof report['implementation_date'] === 'string'
    && typeof report['coverage'] === 'string' && Number.isSafeInteger(report['reporting_lag_days'])
    && Number.isSafeInteger(report['gap_days']) && !!report['before'] && !!report['after']
    && !!report['search_metrics'] && typeof report['search_metrics'] === 'object'
    && !!report['conversion'] && typeof report['conversion'] === 'object'
    && (report['conversion'] as Record<string, unknown>)['state'] === 'unavailable_no_exact_origin_ga4_source';
}

function isTechnical(value: unknown, actionId: string): value is Technical {
  if (!value || typeof value !== 'object') return false;
  const item = value as Record<string, unknown>;
  if (!Number.isSafeInteger(item['id']) || item['action_id'] !== actionId
      || !Number.isSafeInteger(item['action_revision']) || !item['report']
      || typeof item['report'] !== 'object') return false;
  const report = item['report'] as Record<string, unknown>;
  return report['method_version'] === 'action-crawl-observation-v1'
    && report['interpretation'] === 'observed_technical_state_not_automatic_verification_or_causal_outcome'
    && !!report['previous'] && !!report['current'] && Array.isArray(report['urls'])
    && report['urls'].every((row: unknown) => row && typeof row === 'object'
      && typeof (row as Record<string, unknown>)['url'] === 'string'
      && typeof (row as Record<string, unknown>)['state'] === 'string');
}

@Component({
  selector: 'app-action-outcomes',
  imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="outcome-title">
      <h1 id="outcome-title">{{ t("Source-limited action comparison") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish outcome-comparison interface draft in local development. Stored source/status values and other screens remain English; bilingual approval is pending.") }}</p> }
      <p><a [routerLink]="['/app/actions', organizationId, projectId]">{{ t("Return to manual action history") }}</a></p>
      <p>{{ t("Only complete, same-property page-only Search Console CSV rows in equal windows bracketing the logged implementation can be compared. Export omissions are unknown, not zero; raw before/after changes do not prove this action caused improvement. GA4 conversion and revenue remain unavailable without an exact-origin source.") }}</p>
      <p>{{ t("CTR values and their absolute changes are fractions (0.016 means 1.6%); a zero baseline has no relative percentage. Search Console average position is not an observed universal rank.") }}</p>
      @if (loading()) { <p role="status">{{ t("Loading project action and source status.") }}</p> }
      @if (error()) { <p role="alert">{{ t(error()) }}</p> }
      @if (!loading() && !error()) {
        @if (!outcomes().length) { <p>{{ t("No comparable before/after source snapshot has been recorded for this action.") }}</p> }
        @for (outcome of outcomes(); track outcome.id) {
          <section [attr.aria-labelledby]="'comparison-heading-' + outcome.id">
            <h2 [id]="'comparison-heading-' + outcome.id">{{ t("Page observation · action revision") }} {{ outcome.action_revision }}</h2>
            <p><span lang="">{{ outcome.report.page }}</span> · {{ t("human implementation") }} {{ outcome.report.implementation_date }}.
              {{ t("Baseline") }} {{ outcome.report.before.start }}–{{ outcome.report.before.end }} ({{ t("export") }} {{ outcome.report.before.import_id }});
              {{ t("follow-up") }} {{ outcome.report.after.start }}–{{ outcome.report.after.end }} ({{ t("export") }} {{ outcome.report.after.import_id }}).
              {{ outcome.report.gap_days }} {{ t("unmeasured days between the two windows; follow-up reporting lag") }} {{ outcome.report.reporting_lag_days }} {{ t("days.") }}
            </p>
            <p>{{ t("Source coverage:") }} <span lang="en">{{ outcome.report.coverage }}</span>. {{ t(outcome.source_current ? 'Connection currently scoped.' : 'Historical or revoked source; do not infer current visibility.') }}</p>
            <table>
              <caption>{{ t("Observed web page metrics; zero baseline has no relative percentage") }}</caption>
              <thead><tr><th scope="col">{{ t("Metric") }}</th><th scope="col">{{ t("Before") }}</th><th scope="col">{{ t("After") }}</th><th scope="col">{{ t("Absolute change") }}</th><th scope="col">{{ t("Relative change") }}</th></tr></thead>
              <tbody>
                @for (metric of metricNames; track metric) {
                  <tr><th scope="row">{{ t(metric === 'average_position' ? 'Source average position (not a universal rank)' : metric) }}</th>
                    <td>{{ outcome.report.search_metrics[metric]?.previous ?? t('unknown') }}</td>
                    <td>{{ outcome.report.search_metrics[metric]?.current ?? t('unknown') }}</td>
                    <td>{{ outcome.report.search_metrics[metric]?.absolute_change ?? t('unknown') }}</td>
                    <td>{{ outcome.report.search_metrics[metric]?.relative_change ?? t(outcome.report.search_metrics[metric]?.state === 'zero_baseline' ? 'undefined from zero' : 'unknown') }}</td>
                  </tr>
                }
              </tbody>
            </table>
            <p>{{ t("Conversions and revenue: unavailable. Interpretation: observed change only; no causal uplift.") }}</p>
          </section>
        }
        @if (truncated()) { <p>{{ t("Only the first 20 outcome revisions are shown.") }}</p> }
        <section aria-labelledby="technical-comparison-title">
          <h2 id="technical-comparison-title">{{ t("Crawl-observed technical follow-up") }}</h2>
          <p>{{ t("Compare two completed project crawls bracketing the logged change. A missing or failed page is unknown, not a fix. Title, HTTP/canonical and robots differences are observations, not approval or causal proof.") }}</p>
          @if (technicalError()) { <p role="alert">{{ t("Technical crawl history is unavailable for this project.") }}</p> }
          @if (!technical().length && !technicalError()) { <p>{{ t("No bounded technical follow-up has been recorded.") }}</p> }
          @for (snapshot of technical(); track snapshot.id) {
            <article>
              <h3>{{ t("Action revision") }} {{ snapshot.action_revision }} · {{ t("before crawl") }} {{ snapshot.report.previous.crawl_run_id }}, {{ t("after crawl") }} {{ snapshot.report.current.crawl_run_id }}</h3>
              @for (row of snapshot.report.urls; track row.url) {
                <p><span lang="">{{ row.url }}</span>: <span lang="en">{{ row.state }}</span>. HTTP {{ row.previous?.status_code ?? t('unknown') }} {{ t("before and") }} {{ row.current?.status_code ?? t('unknown') }} {{ t("after.") }}
                  {{ t("Titles:") }} <span [attr.lang]="row.previous?.title == null ? uiLanguage() : ''">{{ row.previous?.title ?? t('unknown') }}</span> → <span [attr.lang]="row.current?.title == null ? uiLanguage() : ''">{{ row.current?.title ?? t('unknown') }}</span>. {{ t("No automatic technical verification claim.") }}</p>
              }
            </article>
          }
          @if (canManage() && crawls().length >= 2) {
            <form (submit)="recordTechnical($event)">
              <label for="before-crawl">{{ t("Completed crawl before the actual implementation") }}</label>
              <select id="before-crawl" name="before" required>
                @for (item of crawls(); track item.id) { <option [value]="item.id">{{ item.completed_at }} · {{ t("crawl") }} {{ item.id }}</option> }
              </select>
              <label for="after-crawl">{{ t("Completed crawl after the actual implementation") }}</label>
              <select id="after-crawl" name="after" required>
                @for (item of crawls(); track item.id) { <option [value]="item.id">{{ item.completed_at }} · {{ t("crawl") }} {{ item.id }}</option> }
              </select>
              <button type="submit" [disabled]="busy()">{{ t("Record observed technical comparison") }}</button>
            </form>
          }
        </section>
        @if (canManage()) {
          <section aria-labelledby="record-outcome-title"><h2 id="record-outcome-title">{{ t("Record one source-qualified comparison") }}</h2>
            @if (!sources().length) { <p>{{ t("No currently scoped CSV source is available; do not infer zero results.") }}</p> }
            @else {
              <label for="outcome-source">{{ t("Current project CSV property") }}</label>
              <select id="outcome-source" (change)="selectSource($event)">
                <option value="">{{ t("Select a source") }}</option>
                @for (source of sources(); track source.id) { <option lang="" [value]="source.id">{{ source.label }}</option> }
              </select>
              @if (sourceLoading()) { <p role="status">{{ t("Loading recorded page-only exports.") }}</p> }
              @if (sourceError()) { <p role="alert">{{ t("Page exports unavailable; refresh current source permissions.") }}</p> }
              @if (imports().length) {
                <form (submit)="record($event)">
                  <label for="before-import">{{ t("Pre-implementation page export") }}</label>
                  <select id="before-import" name="before" required>
                    @for (item of imports(); track item.id) { <option [value]="item.id">{{ item.date_start }}–{{ item.date_end }} · {{ t("imported") }} {{ item.created_at }}</option> }
                  </select>
                  <label for="after-import">{{ t("Post-implementation page export") }}</label>
                  <select id="after-import" name="after" required>
                    @for (item of imports(); track item.id) { <option [value]="item.id">{{ item.date_start }}–{{ item.date_end }} · {{ t("imported") }} {{ item.created_at }}</option> }
                  </select>
                  <button type="submit" [disabled]="busy()">{{ t("Check and save an immutable source comparison") }}</button>
                </form>
              } @else if (selectedSource()) { <p>{{ t("No complete page-only exports are available for comparison.") }}</p> }
            }
          </section>
        }
        @if (message()) { <p role="status">{{ t(message()) }}</p> }
      }
    </section>
  `,
  styles: `
    section { margin-block: 1.2rem; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 0.5rem; text-align: left; border-bottom: 1px solid #b9cfd5; }
    form { display: grid; gap: 0.6rem; max-width: 50rem; }
  `,
})
export class ActionOutcomes implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  t(text: string) { return this.uiLanguage() === 'tr' ? outcomeTurkish[text] ?? text : text; }
  readonly metricNames = ['clicks', 'impressions', 'ctr', 'average_position'];
  readonly loading = signal(true);
  readonly error = signal('');
  readonly message = signal('');
  readonly busy = signal(false);
  readonly canManage = signal(false);
  readonly outcomes = signal<Outcome[]>([]);
  readonly sources = signal<Source[]>([]);
  readonly imports = signal<Export[]>([]);
  readonly selectedSource = signal(0);
  readonly sourceLoading = signal(false);
  readonly sourceError = signal(false);
  readonly truncated = signal(false);
  readonly technical = signal<Technical[]>([]);
  readonly technicalError = signal(false);
  readonly crawls = signal<CrawlChoice[]>([]);
  organizationId = 0;
  projectId = 0;
  private actionId = '';
  private generation = 0;

  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi,
              private readonly destroyRef: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t('Source-limited action outcomes')} — OrganicSEOOps`));
  }

  ngOnInit() {
    void this.loadProductLanguage();
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      this.organizationId = Number(params.get('organizationId'));
      this.projectId = Number(params.get('projectId'));
      this.actionId = String(params.get('actionId') || '');
      this.generation++;
      this.outcomes.set([]); this.sources.set([]); this.imports.set([]); this.selectedSource.set(0);
      this.technical.set([]); this.technicalError.set(false); this.crawls.set([]);
      this.sourceLoading.set(false); this.sourceError.set(false);
      this.message.set(''); this.error.set(''); this.canManage.set(false); this.busy.set(false);
      if (Number.isSafeInteger(this.organizationId) && this.organizationId > 0
          && Number.isSafeInteger(this.projectId) && this.projectId > 0
          && /^[0-9a-f-]{36}$/.test(this.actionId)) void this.load();
      else { this.loading.set(false); this.error.set('Select a current project action.'); }
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
    this.loading.set(true); this.error.set(''); this.canManage.set(false); this.outcomes.set([]); this.sources.set([]);
    this.imports.set([]); this.selectedSource.set(0); this.sourceLoading.set(false); this.sourceError.set(false);
    this.technical.set([]); this.technicalError.set(false); this.crawls.set([]);
    try {
      const [history, outcome, project, sources] = await Promise.all([
        this.api.actionHistory(this.organizationId, this.projectId, this.actionId),
        this.api.actionOutcomes(this.organizationId, this.projectId, this.actionId),
        this.api.projectOnboarding(this.organizationId, this.projectId),
        this.api.projectSources(this.organizationId, this.projectId),
      ]);
      if (generation !== this.generation) return;
      if ([history.status, outcome.status, project.status, sources.status].some((status) => status !== 200)
          || [history.body, outcome.body, sources.body].some((body) => body['project_id'] !== this.projectId)
          || !Array.isArray(history.body['history']) || !history.body['history'].length
          || !project.body['project'] || !Array.isArray(outcome.body['outcomes'])
          || !(outcome.body['outcomes'] as unknown[]).every((row) => isOutcome(row, this.actionId))
          || !Array.isArray(sources.body['sources'])) throw new Error();
      const details = project.body['project'] as Record<string, unknown>;
      if (details['id'] !== this.projectId || details['organization_id'] !== this.organizationId
          || typeof details['role'] !== 'string' || !['owner', 'admin', 'member', 'viewer'].includes(details['role'])) throw new Error();
      this.canManage.set(['owner', 'admin'].includes(details['role']));
      this.outcomes.set(outcome.body['outcomes'] as Outcome[]);
      this.truncated.set(outcome.body['has_more'] === true);
      this.sources.set((sources.body['sources'] as Record<string, unknown>[])
        .filter((row) => Number.isSafeInteger(row['id']) && row['provider'] === 'google_search_console'
          && row['state'] === 'active' && row['scope_current'] === true
          && row['csv_import_supported'] === true && typeof row['property'] === 'string')
        .map((row) => ({ id: Number(row['id']), label: String(row['property']) })));
      try {
        const [technical, inventory] = await Promise.all([
          this.api.actionTechnicalOutcomes(this.organizationId, this.projectId, this.actionId),
          this.api.indexationEvidence(this.organizationId, this.projectId),
        ]);
        if (generation !== this.generation) return;
        if ([technical.status, inventory.status].some((status) => status !== 200)
            || technical.body['project_id'] !== this.projectId || inventory.body['project_id'] !== this.projectId
            || !Array.isArray(technical.body['snapshots']) || !Array.isArray(inventory.body['crawls'])
            || !(technical.body['snapshots'] as unknown[]).every((row) => isTechnical(row, this.actionId))) throw new Error();
        this.technical.set(technical.body['snapshots'] as Technical[]);
        this.crawls.set((inventory.body['crawls'] as Record<string, unknown>[])
          .filter((row) => Number.isSafeInteger(row['id']) && typeof row['completed_at'] === 'string')
          .map((row) => ({ id: Number(row['id']), completed_at: String(row['completed_at']) })));
      } catch {
        if (generation === this.generation) this.technicalError.set(true);
      }
    } catch {
      if (generation === this.generation) this.error.set('Comparable action evidence is unavailable for this project.');
    } finally {
      if (generation === this.generation) this.loading.set(false);
    }
  }

  async selectSource(event: Event) {
    const selected = Number((event.target as HTMLSelectElement).value);
    this.imports.set([]); this.sourceError.set(false);
    this.selectedSource.set(this.sources().some((row) => row.id === selected) ? selected : 0);
    if (!this.selectedSource()) return;
    const generation = this.generation;
    this.sourceLoading.set(true);
    try {
      const response = await this.api.sourceImportHistory(this.organizationId, this.projectId, selected);
      if (generation !== this.generation || this.selectedSource() !== selected) return;
      if (response.status !== 200 || response.body['project_id'] !== this.projectId
          || response.body['connection_id'] !== selected || !Array.isArray(response.body['imports'])) throw new Error();
      this.imports.set((response.body['imports'] as Record<string, unknown>[])
        .filter((row) => Number.isSafeInteger(row['id']) && row['status'] === 'succeeded'
          && row['coverage_state'] === 'complete' && row['row_errors'] === 0
          && Array.isArray(row['observation_dimensions']) && row['observation_dimensions'].length === 1
          && row['observation_dimensions'][0] === 'page'
          && ['date_start', 'date_end', 'created_at'].every((field) => typeof row[field] === 'string'))
        .map((row) => ({ id: Number(row['id']), date_start: String(row['date_start']),
          date_end: String(row['date_end']), created_at: String(row['created_at']) })));
    } catch {
      if (generation === this.generation) this.sourceError.set(true);
    } finally {
      if (generation === this.generation && this.selectedSource() === selected) this.sourceLoading.set(false);
    }
  }

  async record(event: Event) {
    event.preventDefault();
    if (!this.canManage() || this.busy() || !this.selectedSource()) return;
    const form = event.target as HTMLFormElement;
    if (!form.reportValidity()) return;
    const fields = new FormData(form);
    const previous = Number(fields.get('before'));
    const current = Number(fields.get('after'));
    if (previous === current || !this.imports().some((item) => item.id === previous)
        || !this.imports().some((item) => item.id === current)) {
      this.message.set('Choose distinct complete before and after page exports.');
      return;
    }
    const generation = this.generation;
    this.busy.set(true); this.message.set('');
    try {
      const response = await this.api.recordPageOutcome(this.organizationId, this.projectId, this.actionId,
        this.selectedSource(), previous, current);
      if (generation !== this.generation) return;
      if (response.status !== 201 || response.body['project_id'] !== this.projectId
          || !isOutcome(response.body['outcome'], this.actionId)) throw new Error();
      this.busy.set(false);
      await this.load();
      if (generation + 1 === this.generation) this.message.set('Source-qualified comparison saved. The observed change is not causal proof.');
    } catch {
      if (generation === this.generation) this.message.set('Comparison outcome unknown or incompatible. Refresh before retrying the same source window.');
    } finally {
      if (generation === this.generation) this.busy.set(false);
    }
  }

  async recordTechnical(event: Event) {
    event.preventDefault();
    if (!this.canManage() || this.busy()) return;
    const form = event.target as HTMLFormElement;
    if (!form.reportValidity()) return;
    const values = new FormData(form);
    const before = Number(values.get('before'));
    const after = Number(values.get('after'));
    if (before === after || !this.crawls().some((row) => row.id === before)
        || !this.crawls().some((row) => row.id === after)) {
      this.message.set('Choose two different completed project crawls.');
      return;
    }
    const generation = this.generation;
    this.busy.set(true); this.message.set('');
    try {
      const response = await this.api.recordTechnicalOutcome(this.organizationId, this.projectId,
        this.actionId, before, after);
      if (generation !== this.generation) return;
      if (response.status !== 201 || response.body['project_id'] !== this.projectId
          || !isTechnical(response.body['snapshot'], this.actionId)) throw new Error();
      this.busy.set(false);
      await this.load();
      if (generation + 1 === this.generation) this.message.set('Crawl observations recorded; no technical fix or SEO outcome is assumed.');
    } catch {
      if (generation === this.generation) this.message.set('Technical comparison unavailable or outcome unknown; refresh before retrying.');
    } finally {
      if (generation === this.generation) this.busy.set(false);
    }
  }
}

const outcomeTurkish: Readonly<Record<string, string>> = {
  "Source-limited action outcomes": "Kaynakla sınırlı eylem sonuçları",
  "Source-limited action comparison": "Kaynakla sınırlı eylem karşılaştırması",
  "Unreviewed Turkish outcome-comparison interface draft in local development. Stored source/status values and other screens remain English; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe sonuç karşılaştırma arayüzü taslağı. Kayıtlı kaynak/durum değerleri ve diğer ekranlar İngilizce kalır; iki dilli onay bekleniyor.",
  "Return to manual action history": "Elle yapılan eylem geçmişine dön",
  "Only complete, same-property page-only Search Console CSV rows in equal windows bracketing the logged implementation can be compared. Export omissions are unknown, not zero; raw before/after changes do not prove this action caused improvement. GA4 conversion and revenue remain unavailable without an exact-origin source.": "Yalnızca kaydedilmiş uygulamanın öncesini ve sonrasını kapsayan eşit dönemlerdeki tam, aynı mülke ait, yalnızca sayfa boyutlu Search Console CSV satırları karşılaştırılabilir. Dışa aktarım eksikleri bilinmez; sıfır değildir. Ham önce/sonra değişimleri bu eylemin iyileşmeye neden olduğunu kanıtlamaz. Tam köken kaynağı olmadan GA4 dönüşüm ve gelir verileri kullanılamaz.",
  "CTR values and their absolute changes are fractions (0.016 means 1.6%); a zero baseline has no relative percentage. Search Console average position is not an observed universal rank.": "CTR değerleri ve mutlak değişimleri kesirdir (0,016 %1,6 demektir); sıfır başlangıç değerinin göreli yüzdesi yoktur. Search Console ortalama konumu gözlenmiş evrensel sıralama değildir.",
  "Loading project action and source status.": "Proje eylemi ve kaynak durumu yükleniyor.",
  "No comparable before/after source snapshot has been recorded for this action.": "Bu eylem için karşılaştırılabilir önce/sonra kaynak anlık görüntüsü kaydedilmemiş.",
  "Page observation · action revision": "Sayfa gözlemi · eylem revizyonu",
  "human implementation": "insan uygulaması",
  "Baseline": "Başlangıç dönemi",
  "export": "dışa aktarım",
  "follow-up": "takip dönemi",
  "unmeasured days between the two windows; follow-up reporting lag": "iki dönem arasındaki ölçülmemiş gün; takip raporlama gecikmesi",
  "days.": "gün.",
  "Source coverage:": "Kaynak kapsamı:",
  "Connection currently scoped.": "Bağlantı güncel kapsamda.",
  "Historical or revoked source; do not infer current visibility.": "Geçmiş veya iptal edilmiş kaynak; güncel görünürlük sonucu çıkarmayın.",
  "Observed web page metrics; zero baseline has no relative percentage": "Gözlenen web sayfası ölçümleri; sıfır başlangıç değerinin göreli yüzdesi yoktur",
  "Metric": "Ölçüm",
  "Before": "Önce",
  "After": "Sonra",
  "Absolute change": "Mutlak değişim",
  "Relative change": "Göreli değişim",
  "Source average position (not a universal rank)": "Kaynak ortalama konumu (evrensel sıralama değildir)",
  "clicks": "tıklamalar",
  "impressions": "gösterimler",
  "ctr": "CTR",
  "unknown": "bilinmiyor",
  "undefined from zero": "sıfırdan tanımsız",
  "Conversions and revenue: unavailable. Interpretation: observed change only; no causal uplift.": "Dönüşümler ve gelir: kullanılamıyor. Yorum: yalnızca gözlenen değişim; nedensel iyileşme yok.",
  "Only the first 20 outcome revisions are shown.": "Yalnızca ilk 20 sonuç revizyonu gösterilir.",
  "Crawl-observed technical follow-up": "Taramada gözlenen teknik takip",
  "Compare two completed project crawls bracketing the logged change. A missing or failed page is unknown, not a fix. Title, HTTP/canonical and robots differences are observations, not approval or causal proof.": "Kaydedilmiş değişikliğin öncesini ve sonrasını kapsayan iki tamamlanmış proje taramasını karşılaştırın. Eksik veya başarısız sayfa bilinmez; düzeltme değildir. Başlık, HTTP/kanonik ve robots farkları gözlemdir; onay veya nedensellik kanıtı değildir.",
  "Technical crawl history is unavailable for this project.": "Bu proje için teknik tarama geçmişi kullanılamıyor.",
  "No bounded technical follow-up has been recorded.": "Sınırlı teknik takip kaydedilmemiş.",
  "Action revision": "Eylem revizyonu",
  "before crawl": "önceki tarama",
  "after crawl": "sonraki tarama",
  "before and": "önce ve",
  "after.": "sonra.",
  "Titles:": "Başlıklar:",
  "No automatic technical verification claim.": "Otomatik teknik doğrulama iddiası yok.",
  "Completed crawl before the actual implementation": "Gerçek uygulamadan önce tamamlanmış tarama",
  "Completed crawl after the actual implementation": "Gerçek uygulamadan sonra tamamlanmış tarama",
  "crawl": "tarama",
  "Record observed technical comparison": "Gözlenen teknik karşılaştırmayı kaydet",
  "Record one source-qualified comparison": "Kaynak koşullarını karşılayan tek karşılaştırma kaydet",
  "No currently scoped CSV source is available; do not infer zero results.": "Güncel kapsamda CSV kaynağı yok; sıfır sonuç çıkarımı yapmayın.",
  "Current project CSV property": "Güncel proje CSV mülkü",
  "Select a source": "Kaynak seçin",
  "Loading recorded page-only exports.": "Kaydedilmiş yalnızca sayfa boyutlu dışa aktarımlar yükleniyor.",
  "Page exports unavailable; refresh current source permissions.": "Sayfa dışa aktarımları kullanılamıyor; güncel kaynak izinlerini yenileyin.",
  "Pre-implementation page export": "Uygulama öncesi sayfa dışa aktarımı",
  "Post-implementation page export": "Uygulama sonrası sayfa dışa aktarımı",
  "imported": "içe aktarılma tarihi",
  "Check and save an immutable source comparison": "Değişmez kaynak karşılaştırmasını kontrol et ve kaydet",
  "No complete page-only exports are available for comparison.": "Karşılaştırma için tam ve yalnızca sayfa boyutlu dışa aktarım yok.",
  "Select a current project action.": "Güncel proje eylemi seçin.",
  "Comparable action evidence is unavailable for this project.": "Bu proje için karşılaştırılabilir eylem kanıtları kullanılamıyor.",
  "Choose distinct complete before and after page exports.": "Farklı ve tam önce/sonra sayfa dışa aktarımları seçin.",
  "Source-qualified comparison saved. The observed change is not causal proof.": "Kaynak koşullarını karşılayan karşılaştırma kaydedildi. Gözlenen değişim nedensellik kanıtı değildir.",
  "Comparison outcome unknown or incompatible. Refresh before retrying the same source window.": "Karşılaştırma sonucu bilinmiyor veya uyumsuz. Aynı kaynak dönemini yeniden denemeden önce yenileyin.",
  "Choose two different completed project crawls.": "İki farklı tamamlanmış proje taraması seçin.",
  "Crawl observations recorded; no technical fix or SEO outcome is assumed.": "Tarama gözlemleri kaydedildi; teknik düzeltme veya SEO sonucu varsayılmaz.",
  "Technical comparison unavailable or outcome unknown; refresh before retrying.": "Teknik karşılaştırma kullanılamıyor veya sonuç bilinmiyor; yeniden denemeden önce yenileyin."
};
