import { Title } from '@angular/platform-browser';
import { Component, computed, DestroyRef, effect, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';
import { AccountApi } from '../account/account-api';
import { environment } from '../../environments/environment';
import { ProjectSummaryPreference } from './project-summary-preference';
import { ProjectCrawlFailures } from './project-crawl-failures';
import { ProjectIntegrationHealth } from './project-integration-health';
import { ProjectAlertPreference } from './project-alert-preference';
import { ProjectCruxAlertPreference } from './project-crux-alert-preference';
import { ProjectJobReference } from './project-job-reference';
import { ProjectSupport } from './project-support';

type Finding = { id: number; subject: string; source_current: boolean };
type Report = { id: number; format: 'csv' | 'json'; created_at: string; size_bytes: number;
  source_counts: { findings: number; actions: number; outcomes: number } };
type Share = { id: number; report_id: number; intended_recipient: string; expires_at: string;
  state: 'active' | 'revoked' | 'expired' };

@Component({
  selector: 'app-project-reports',
  imports: [RouterLink, ProjectSummaryPreference, ProjectCrawlFailures, ProjectIntegrationHealth, ProjectAlertPreference, ProjectCruxAlertPreference, ProjectJobReference, ProjectSupport],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="reports-title">
      <h1 id="reports-title">{{ t("Private project evidence reports") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish report, notification and support interface draft in local development. Provider values and customer text are not translated; bilingual approval is pending.") }}</p> }
      <p><a [routerLink]="['/app/dashboard', organizationId, projectId]">{{ t("Return to project dashboard") }}</a></p>
      <p>{{ t("Exports contain only the selected project findings and their recorded source-limited evidence. They are snapshots, not complete traffic reports or proof of causal improvement. Access to authenticated downloads is checked again for each request.") }}</p>
      @if (loading()) { <p role="status">{{ t("Loading current project report permissions.") }}</p> }
      @if (error()) { <p role="alert">{{ t(error()) }}</p> }
      @if (!loading() && !error()) {
        <section [attr.lang]="uiLanguage()" aria-labelledby="project-help-title">
          <h2 id="project-help-title">{{ t("Help, evidence terms and data handling") }}</h2>
          <details><summary>{{ t("How should I interpret missing data and evidence?") }}</summary>
            <p>{{ t("Not checked, unavailable and no issue observed are different states. Missing source data is not zero traffic or a passing audit. Inspect the original source, collection dates, method and coverage before choosing an action.") }}</p>
            <dl><dt>{{ t("Coverage and freshness") }}</dt><dd>{{ t("Coverage describes what was actually inspected; collection and source dates describe when. A partial crawl or provider top-row report is not the whole site or complete history. No recorded success does not establish an arbitrary stale-age threshold.") }}</dd>
              <dt>{{ t("Measured, observed, estimated and AI-interpreted") }}</dt><dd>{{ t("First-party source measurements, public observations, third-party estimates and AI explanations have different evidence limits. An AI explanation does not replace source rows, and provider scores are not universal measurements.") }}</dd>
              <dt>{{ t("Crawlability, indexability and indexed status") }}</dt><dd>{{ t("A successful fetch is not proof of indexing. Observed crawl/robots/canonical signals remain distinct from a search engine's dated indexing report.") }}</dd>
              <dt>{{ t("Lab results and CrUX field data") }}</dt><dd>{{ t("Lighthouse is a controlled lab observation. CrUX is aggregated real-user field data with its own periods and coverage. Missing or overlapping field samples do not prove a passing result or statistically confirmed regression.") }}</dd>
              <dt>{{ t("Position and outcomes") }}</dt><dd>{{ t("Search Console average position is an aggregate, not an exact point-in-time rank. Approval, implementation, technical verification and an observed search change are separate; before/after changes do not prove causal uplift.") }}</dd>
            </dl>
          </details>
          <details><summary>{{ t("What do job, notification and support states mean?") }}</summary>
            <p>{{ t("A job's operational status and last record update are not an SEO outcome or proof of incident/completion time. Use only a known minimized project job ID with a bounded question; do not attach raw errors, credentials, customer details, logs or exports.") }}</p>
            <p>{{ t("A received support request means stored locally, not staff response or email delivery. Optional notification preferences record your intent; current configuration, source, recipient permission and entitlement gates still apply. Transport acceptance is not inbox delivery or reading. After an uncertain submission, inspect current history before an explicit unchanged-key retry; nothing is retried by this help.") }}</p>
          </details>
          <details><summary>{{ t("What happens on expiry, cancellation or closure?") }}</summary>
            <p>{{ t("The selected policy permits 90 days of read-only retained results, authorized export and recovery after trial expiry or effective paid-service lapse/cancellation. Customer content is then due for active-system deletion within 30 days. Deliberate owner organization closure disables access and work immediately, with active-store deletion due within 30 days of closure.") }}</p>
            <p>{{ t("Customer-bearing backups have a separate maximum 35-day rotation after active deletion. These are policy bounds, not proof that a hosted deletion or backup expiry happened. Already downloaded copies cannot be remotely erased. Restricted billing, fraud, security, audit and legal records require separately reviewed retention.") }}</p>
            <p>{{ t("Subscription cancellation, organization closure and personal account access shutdown are different actions. Personal closure must preserve organization ownership and does not prove complete identity erasure. Available controls and their release gates are shown on the current destination screens; help does not activate a close action or deletion timer.") }}</p>
          </details>
          <details><summary>{{ t("Where can I inspect exports and available account controls?") }}</summary>
            <p>{{ t("Project report downloads use current project-read permission. Organization customer exports and closure/billing controls require the current organization owner. A bounded archive or sequential source-parts capture is not a complete legal, financial or backup export, and sequential observations are not a point-in-time snapshot. Download and verify applicable exports before deliberate closure; closure disables their access.") }}</p>
            @if (organizationOwner()) {
              <ul><li><a [routerLink]="['/app/export', organizationId]">{{ t("Owner customer-export inventory and private capture parts") }}</a></li>
                <li><a [routerLink]="['/app/closure-status', organizationId]">{{ t("Owner current retention/closure status and available controls") }}</a></li>
                <li><a [routerLink]="['/app/billing', organizationId]">{{ t("Owner current subscription and billing recovery") }}</a></li></ul>
            } @else { <p>{{ t("Ask the current organization owner to inspect organization-wide export, closure or billing controls. Project access does not grant those permissions.") }}</p> }
            <p><a routerLink="/account/security">{{ t("Your own security, personal JSON export and access-closure status") }}</a></p>
          </details>
        </section>
        <h2>{{ t("Create a bounded evidence snapshot") }}</h2>
        @if (findingError()) { <p role="alert">{{ t("Current finding sources are unavailable; no export can be created from missing evidence.") }}</p> }
        @else if (!findings().length) { <p>{{ t("No stored source findings to select. An empty result does not mean no issue exists.") }}</p> }
        @else {
          <form (submit)="createReport($event)">
            <fieldset><legend>{{ t("Select up to 20 findings from this project") }}</legend>
              @for (finding of findings(); track finding.id) {
                <label><input type="checkbox" [checked]="selected().includes(finding.id)" [disabled]="!finding.source_current || (selected().length >= 20 && !selected().includes(finding.id))"
                  (change)="selectFinding(finding.id, $any($event.target).checked)" />
                  <span lang="">{{ finding.subject }}</span> · {{ t(finding.source_current ? 'current source' : 'stale source; not selectable') }}</label>
              }
            </fieldset>
            <label for="report-format">{{ t("Download format") }}</label>
            <select id="report-format" name="format"><option value="csv">{{ t("Spreadsheet-safe CSV") }}</option><option value="json">{{ t("JSON") }}</option></select>
            <button type="submit" [disabled]="busy() || !selected().length">{{ t("Create private snapshot") }}</button>
          </form>
        }
        <section aria-labelledby="saved-reports-title"><h2 id="saved-reports-title">{{ t("Saved private reports") }}</h2>
          @if (!reports().length) { <p>{{ t("No report snapshots have been created for this project.") }}</p> }
          <ul>@for (report of reports(); track report.id) {
            <li>{{ t("Report") }} {{ report.id }} · {{ report.created_at }} · <span lang="en">{{ report.format }}</span> · {{ report.size_bytes }} {{ t("bytes") }} ·
              {{ report.source_counts.findings }} {{ t("finding(s),") }} {{ report.source_counts.actions }} {{ t("action(s),") }} {{ report.source_counts.outcomes }} {{ t("outcome(s).") }}
              <a [href]="downloadUrl(report)" download>{{ t("Download (current project permission required)") }}</a>
            </li>
          }</ul>
        </section>
        @if (canShare()) {
          <section aria-labelledby="shares-title"><h2 id="shares-title">{{ t("Optional external report shares") }}</h2>
            <p>{{ t("Anyone holding a link can download the selected report without signing in until the earlier of expiry, revocation or loss of your sharing permission. The intended recipient is a disclosure record, not an email-identity check. Already downloaded copies cannot be erased. No email is sent automatically.") }}</p>
            @if (shareError()) { <p role="alert">{{ t("Share history is unavailable; do not assume an earlier link was revoked.") }}</p> }
            @if (reports().length) {
              <form (submit)="createShare($event)">
                <label for="share-report">{{ t("Exactly one private report") }}</label>
                <select id="share-report" name="report" required>
                  @for (report of reports(); track report.id) { <option [value]="report.id">{{ t("Report") }} {{ report.id }} · {{ report.created_at }} ({{ report.format }})</option> }
                </select>
                <label for="share-recipient">{{ t("Intended recipient email (not verified or automatically delivered)") }}</label>
                <input id="share-recipient" lang="" name="recipient" type="email" required maxlength="254" />
                <label for="share-hours">{{ t("Expiry in hours (1–168)") }}</label>
                <input id="share-hours" name="hours" type="number" min="1" max="168" value="24" required />
                <label><input name="acknowledge" type="checkbox" required /> {{ t("I understand this is a bearer link: anyone who obtains it may download this report until access ends.") }}</label>
                <button type="submit" [disabled]="busy() || shareError()">{{ t("Issue one-time share link") }}</button>
              </form>
            }
            @if (shareLink()) {
              <p role="status">{{ t("Copy this link now; it will not be shown again. It is not sent to the recipient.") }}</p>
              <label for="share-link">{{ t("One-time report link") }}</label><input id="share-link" lang="" readonly [value]="shareLink()" />
            }
            @if (!shares().length && !shareError()) { <p>{{ t("No share history for this project.") }}</p> }
            <ul>@for (share of shares(); track share.id) {
              <li>{{ t("Report") }} {{ share.report_id }} · {{ t("intended recipient") }} <span lang="">{{ share.intended_recipient }}</span> · <span lang="en">{{ share.state }}</span> · {{ t("expires") }} {{ share.expires_at }}.
                @if (share.state === 'active') { <button type="button" [disabled]="busy()" (click)="revoke(share.id)">{{ t("Revoke future access") }}</button> }
              </li>
            }</ul>
          </section>
        }
        @if (message()) { <p role="status">{{ t(message()) }}</p> }
        <div lang="en">
        <app-project-summary-preference [organizationId]="organizationId" [projectId]="projectId" [language]="uiLanguage()" />
        <app-project-alert-preference [organizationId]="organizationId" [projectId]="projectId" [language]="uiLanguage()" />
        <app-project-crux-alert-preference [organizationId]="organizationId" [projectId]="projectId" [language]="uiLanguage()" />
        <app-project-crawl-failures [organizationId]="organizationId" [projectId]="projectId" [language]="uiLanguage()" />
        <app-project-integration-health [organizationId]="organizationId" [projectId]="projectId" [language]="uiLanguage()" />
        <app-project-job-reference [organizationId]="organizationId" [projectId]="projectId" [language]="uiLanguage()" />
        <app-project-support [organizationId]="organizationId" [projectId]="projectId" [language]="uiLanguage()" />
        </div>
      }
    </section>
  `,
  styles: `
    form, fieldset { display: grid; gap: 0.6rem; max-width: 48rem; }
    fieldset label { display: block; overflow-wrap: anywhere; }
    section { margin-block: 1.2rem; border-top: 1px solid #b9cfd5; }
    input[readonly] { max-width: 100%; width: 48rem; }
    li { margin-block: 0.75rem; overflow-wrap: anywhere; }
  `,
})
export class ProjectReports implements OnInit {
  private readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  t(text: string) { return this.uiLanguage() === 'tr' ? reportsTurkish[text] ?? text : text; }
  readonly loading = signal(true);
  readonly error = signal('');
  readonly message = signal('');
  readonly busy = signal(false);
  readonly findingError = signal(false);
  readonly shareError = signal(false);
  readonly canShare = signal(false);
  readonly organizationOwner = signal(false);
  readonly findings = signal<Finding[]>([]);
  readonly selected = signal<number[]>([]);
  readonly reports = signal<Report[]>([]);
  readonly shares = signal<Share[]>([]);
  readonly shareLink = signal('');
  organizationId = 0;
  projectId = 0;
  private generation = 0;

  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi,
              private readonly destroyRef: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t('Private project reports and shares')} — OrganicSEOOps`));
  }

  ngOnInit() {
    void this.loadProductLanguage();
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      this.organizationId = Number(params.get('organizationId'));
      this.projectId = Number(params.get('projectId'));
      this.generation++;
      this.findings.set([]); this.selected.set([]); this.reports.set([]); this.shares.set([]);
      this.shareLink.set(''); this.message.set(''); this.error.set(''); this.canShare.set(false); this.organizationOwner.set(false);
      this.findingError.set(false); this.shareError.set(false); this.busy.set(false);
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

  async load() {
    const generation = ++this.generation;
    this.loading.set(true); this.error.set(''); this.organizationOwner.set(false);
    this.canShare.set(false); this.reports.set([]); this.shares.set([]);
    this.shareLink.set(''); this.shareError.set(false);
    try {
      const project = await this.api.projectOnboarding(this.organizationId, this.projectId);
      if (generation !== this.generation) return;
      const context = project.body['project'] as Record<string, unknown> | undefined;
      if (project.status !== 200 || context?.['id'] !== this.projectId
          || context['organization_id'] !== this.organizationId || typeof context['role'] !== 'string'
          || !['owner', 'admin', 'member', 'viewer'].includes(context['role'])) throw new Error();
      this.canShare.set(['owner', 'admin'].includes(context['role']));
      this.organizationOwner.set(context['role'] === 'owner');
      const [findings, reports, shares] = await Promise.all([
        this.api.projectFindings(this.organizationId, this.projectId),
        this.api.projectReports(this.organizationId, this.projectId),
        this.canShare() ? this.api.projectReportShares(this.organizationId, this.projectId) : Promise.resolve(null),
      ]);
      if (generation !== this.generation) return;
      if (reports.status !== 200 || reports.body['project_id'] !== this.projectId
          || !Array.isArray(reports.body['reports']) || !reports.body['reports'].every(isReport)) throw new Error();
      this.reports.set(reports.body['reports'] as Report[]);
      if (findings.status === 200 && findings.body['project_id'] === this.projectId
          && Array.isArray(findings.body['findings'])) {
        this.findings.set((findings.body['findings'] as Record<string, unknown>[])
          .filter((row) => Number.isSafeInteger(row['id']) && typeof row['subject'] === 'string'
            && typeof row['source_current'] === 'boolean') as Finding[]);
      } else this.findingError.set(true);
      if (shares && shares.status === 200 && Array.isArray(shares.body['shares'])
          && (shares.body['shares'] as unknown[]).every(isShare)) this.shares.set(shares.body['shares'] as Share[]);
      else if (this.canShare()) this.shareError.set(true);
    } catch {
      if (generation === this.generation) this.error.set('Current project report access is unavailable.');
    } finally {
      if (generation === this.generation) this.loading.set(false);
    }
  }

  selectFinding(id: number, checked: boolean) {
    if (!this.findings().some((row) => row.id === id && row.source_current)) return;
    this.selected.set(checked ? [...this.selected(), id].slice(0, 20) : this.selected().filter((value) => value !== id));
  }

  downloadUrl(report: Report) {
    return `${environment.apiBase}/organizations/${this.organizationId}/projects/${this.projectId}/reports/${report.id}/download/`;
  }

  async createReport(event: Event) {
    event.preventDefault();
    if (this.busy() || !this.selected().length) return;
    const generation = this.generation;
    const form = event.target as HTMLFormElement;
    const format = new FormData(form).get('format');
    if (format !== 'csv' && format !== 'json') return;
    this.busy.set(true); this.message.set(''); this.shareLink.set('');
    try {
      const result = await this.api.createProjectReport(this.organizationId, this.projectId, this.selected(), format);
      if (generation !== this.generation) return;
      if (result.status !== 201 || !isReport(result.body['report'])) throw new Error();
      this.reports.set([result.body['report'] as Report, ...this.reports().filter((row) => row.id !== (result.body['report'] as Report).id)].slice(0, 50));
      this.selected.set([]); form.reset();
      this.message.set('Private snapshot saved. Download rechecks your current project access.');
    } catch {
      if (generation === this.generation) this.message.set('Report creation was unavailable. Refresh project evidence before retrying.');
    } finally { if (generation === this.generation) this.busy.set(false); }
  }

  async createShare(event: Event) {
    event.preventDefault();
    if (this.busy() || !this.canShare() || this.shareError()) return;
    const form = event.target as HTMLFormElement;
    if (!form.reportValidity()) return;
    const data = new FormData(form);
    const reportId = Number(data.get('report'));
    const hours = Number(data.get('hours'));
    const recipient = String(data.get('recipient') || '');
    if (!this.reports().some((row) => row.id === reportId)
        || !Number.isSafeInteger(hours) || hours < 1 || hours > 168 || !data.has('acknowledge')) return;
    const generation = this.generation;
    this.busy.set(true); this.shareLink.set(''); this.message.set('');
    try {
      const result = await this.api.createProjectReportShare(this.organizationId, this.projectId,
        reportId, recipient, hours);
      if (generation !== this.generation) return;
      if (result.status !== 201 || !isShare(result.body['share'])
          || typeof result.body['link_path'] !== 'string'
          || !/^\/api\/reports\/shared\/[A-Za-z0-9_-]{43}\/$/.test(result.body['link_path'])) throw new Error();
      this.shares.set([result.body['share'] as Share, ...this.shares()].slice(0, 50));
      this.shareLink.set(`${location.origin}${result.body['link_path']}`);
      form.reset(); this.message.set('Share recorded; copy the one-time bearer link and deliver it only to your intended recipient.');
    } catch {
      if (generation === this.generation) this.message.set('Share outcome unavailable. Inspect share history before issuing another link.');
    } finally { if (generation === this.generation) this.busy.set(false); }
  }

  async revoke(id: number) {
    if (this.busy() || !this.shares().some((row) => row.id === id && row.state === 'active')) return;
    const generation = this.generation;
    this.busy.set(true); this.shareLink.set(''); this.message.set('');
    try {
      const result = await this.api.revokeProjectReportShare(this.organizationId, this.projectId, id);
      if (generation !== this.generation) return;
      if (result.status !== 200 || !isShare(result.body['share'])
          || (result.body['share'] as Share).id !== id || (result.body['share'] as Share).state !== 'revoked') throw new Error();
      this.shares.set(this.shares().map((row) => row.id === id ? result.body['share'] as Share : row));
      this.message.set('Future link access revoked; copies already downloaded cannot be erased.');
    } catch {
      if (generation === this.generation) this.message.set('Revocation outcome unavailable. Refresh share history before relying on it.');
    } finally { if (generation === this.generation) this.busy.set(false); }
  }
}

function isReport(value: unknown): value is Report {
  if (!value || typeof value !== 'object') return false;
  const row = value as Record<string, unknown>;
  return Number.isSafeInteger(row['id']) && Number(row['id']) > 0
    && typeof row['format'] === 'string' && ['csv', 'json'].includes(row['format']) && typeof row['created_at'] === 'string'
    && Number.isSafeInteger(row['size_bytes']) && !!row['source_counts']
    && typeof row['source_counts'] === 'object' && ['findings', 'actions', 'outcomes']
      .every((key) => Number.isSafeInteger((row['source_counts'] as Record<string, unknown>)[key]));
}

function isShare(value: unknown): value is Share {
  if (!value || typeof value !== 'object') return false;
  const row = value as Record<string, unknown>;
  return Number.isSafeInteger(row['id']) && Number(row['id']) > 0
    && Number.isSafeInteger(row['report_id']) && Number(row['report_id']) > 0
    && typeof row['intended_recipient'] === 'string' && typeof row['expires_at'] === 'string'
    && typeof row['state'] === 'string' && ['active', 'revoked', 'expired'].includes(row['state']);
}

const reportsTurkish: Readonly<Record<string, string>> = {
  "Private project reports and shares": "Özel proje raporları ve paylaşımları",
  "Help, evidence terms and data handling": "Yardım, kanıt terimleri ve veri işleme",
  "How should I interpret missing data and evidence?": "Eksik verileri ve kanıtları nasıl yorumlamalıyım?",
  "Not checked, unavailable and no issue observed are different states. Missing source data is not zero traffic or a passing audit. Inspect the original source, collection dates, method and coverage before choosing an action.": "Kontrol edilmedi, kullanılamıyor ve sorun gözlenmedi farklı durumlardır. Eksik kaynak verisi sıfır trafik veya başarılı denetim değildir. Bir eylem seçmeden önce özgün kaynağı, toplama tarihlerini, yöntemi ve kapsamı inceleyin.",
  "Coverage and freshness": "Kapsam ve güncellik",
  "Coverage describes what was actually inspected; collection and source dates describe when. A partial crawl or provider top-row report is not the whole site or complete history. No recorded success does not establish an arbitrary stale-age threshold.": "Kapsam, gerçekte nelerin incelendiğini; toplama ve kaynak tarihleri ise ne zaman incelendiğini açıklar. Kısmi tarama veya sağlayıcının üst satır raporu, tüm site veya tam geçmiş değildir. Kayıtlı başarı olmaması, keyfi bir eskime süresi eşiği belirlemez.",
  "Measured, observed, estimated and AI-interpreted": "Ölçülen, gözlenen, tahmin edilen ve yapay zekâ tarafından yorumlanan",
  "First-party source measurements, public observations, third-party estimates and AI explanations have different evidence limits. An AI explanation does not replace source rows, and provider scores are not universal measurements.": "Birinci taraf kaynak ölçümleri, herkese açık gözlemler, üçüncü taraf tahminleri ve yapay zekâ açıklamaları farklı kanıt sınırlarına sahiptir. Yapay zekâ açıklaması kaynak satırlarının yerine geçmez; sağlayıcı puanları evrensel ölçümler değildir.",
  "Crawlability, indexability and indexed status": "Taranabilirlik, dizine alınabilirlik ve dizin durumu",
  "A successful fetch is not proof of indexing. Observed crawl/robots/canonical signals remain distinct from a search engine's dated indexing report.": "Başarılı sayfa alımı, dizine alınmanın kanıtı değildir. Gözlenen tarama/robots/kanonik sinyalleri, arama motorunun tarihli dizinleme raporundan ayrı kalır.",
  "Lab results and CrUX field data": "Laboratuvar sonuçları ve CrUX saha verileri",
  "Lighthouse is a controlled lab observation. CrUX is aggregated real-user field data with its own periods and coverage. Missing or overlapping field samples do not prove a passing result or statistically confirmed regression.": "Lighthouse kontrollü bir laboratuvar gözlemidir. CrUX kendi dönemleri ve kapsamı olan, birleştirilmiş gerçek kullanıcı saha verisidir. Eksik veya örtüşen saha örnekleri başarılı sonuç veya istatistiksel olarak doğrulanmış gerileme kanıtlamaz.",
  "Position and outcomes": "Konum ve sonuçlar",
  "Search Console average position is an aggregate, not an exact point-in-time rank. Approval, implementation, technical verification and an observed search change are separate; before/after changes do not prove causal uplift.": "Search Console ortalama konumu toplu bir değerdir; belirli bir andaki tam sıralama değildir. Onay, uygulama, teknik doğrulama ve gözlenen arama değişikliği ayrıdır; önce/sonra değişiklikleri nedensel artışı kanıtlamaz.",
  "What do job, notification and support states mean?": "İş, bildirim ve destek durumları ne anlama gelir?",
  "A job's operational status and last record update are not an SEO outcome or proof of incident/completion time. Use only a known minimized project job ID with a bounded question; do not attach raw errors, credentials, customer details, logs or exports.": "Bir işin operasyonel durumu ve son kayıt güncellemesi, SEO sonucu veya olay/tamamlanma zamanı kanıtı değildir. Sınırlı bir soruyla yalnızca bilinen, asgari proje iş kimliğini kullanın; ham hatalar, kimlik bilgileri, müşteri ayrıntıları, günlükler veya dışa aktarımlar eklemeyin.",
  "A received support request means stored locally, not staff response or email delivery. Optional notification preferences record your intent; current configuration, source, recipient permission and entitlement gates still apply. Transport acceptance is not inbox delivery or reading. After an uncertain submission, inspect current history before an explicit unchanged-key retry; nothing is retried by this help.": "Alınan destek isteği, yerel olarak kaydedildiği anlamına gelir; personel yanıtı veya e-posta teslimatı değildir. İsteğe bağlı bildirim tercihleri niyetinizi kaydeder; güncel yapılandırma, kaynak, alıcı izni ve kullanım hakkı koşulları geçerli kalır. İletim kabulü, gelen kutusuna teslim veya okunma değildir. Belirsiz gönderimden sonra, aynı anahtarla açıkça yeniden denemeden önce güncel geçmişi inceleyin; bu yardım hiçbir şeyi yeniden denemez.",
  "What happens on expiry, cancellation or closure?": "Süre dolması, iptal veya kapatma durumunda ne olur?",
  "The selected policy permits 90 days of read-only retained results, authorized export and recovery after trial expiry or effective paid-service lapse/cancellation. Customer content is then due for active-system deletion within 30 days. Deliberate owner organization closure disables access and work immediately, with active-store deletion due within 30 days of closure.": "Seçilen politika, deneme süresi dolduktan veya ücretli hizmet sona erdikten/iptali yürürlüğe girdikten sonra 90 gün salt okunur saklanmış sonuç, yetkili dışa aktarım ve kurtarma sağlar. Müşteri içeriğinin ardından 30 gün içinde etkin sistemden silinmesi gerekir. Sahibinin bilinçli kuruluş kapatma işlemi erişimi ve çalışmayı hemen devre dışı bırakır; etkin depodan silme, kapatma tarihinden itibaren 30 gün içinde yapılmalıdır.",
  "Customer-bearing backups have a separate maximum 35-day rotation after active deletion. These are policy bounds, not proof that a hosted deletion or backup expiry happened. Already downloaded copies cannot be remotely erased. Restricted billing, fraud, security, audit and legal records require separately reviewed retention.": "Müşteri verisi içeren yedekler, etkin silmeden sonra ayrı olarak en fazla 35 günlük dönüşüm süresine sahiptir. Bunlar politika sınırlarıdır; barındırılan sistemde silme veya yedek süresi dolmasının gerçekleştiğinin kanıtı değildir. İndirilmiş kopyalar uzaktan silinemez. Kısıtlı faturalandırma, dolandırıcılık, güvenlik, denetim ve yasal kayıtlar ayrıca incelenmiş saklama gerektirir.",
  "Subscription cancellation, organization closure and personal account access shutdown are different actions. Personal closure must preserve organization ownership and does not prove complete identity erasure. Available controls and their release gates are shown on the current destination screens; help does not activate a close action or deletion timer.": "Abonelik iptali, kuruluş kapatma ve kişisel hesap erişimini kapatma farklı eylemlerdir. Kişisel kapatma kuruluş sahipliğini korumalıdır ve kimliğin tamamen silindiğini kanıtlamaz. Kullanılabilir kontroller ve yayın koşulları güncel hedef ekranlarda gösterilir; yardım bir kapatma eylemini veya silme zamanlayıcısını etkinleştirmez.",
  "Where can I inspect exports and available account controls?": "Dışa aktarımları ve kullanılabilir hesap kontrollerini nerede inceleyebilirim?",
  "Project report downloads use current project-read permission. Organization customer exports and closure/billing controls require the current organization owner. A bounded archive or sequential source-parts capture is not a complete legal, financial or backup export, and sequential observations are not a point-in-time snapshot. Download and verify applicable exports before deliberate closure; closure disables their access.": "Proje raporu indirmeleri güncel proje okuma iznini kullanır. Kuruluş müşteri dışa aktarımları ve kapatma/faturalandırma kontrolleri güncel kuruluş sahibini gerektirir. Sınırlı arşiv veya ardışık kaynak parçaları kaydı tam yasal, finansal veya yedek dışa aktarımı değildir; ardışık gözlemler tek bir anın görüntüsü değildir. Bilinçli kapatmadan önce ilgili dışa aktarımları indirip doğrulayın; kapatma bunlara erişimi devre dışı bırakır.",
  "Owner customer-export inventory and private capture parts": "Sahip için müşteri dışa aktarım envanteri ve özel kayıt parçaları",
  "Owner current retention/closure status and available controls": "Sahip için güncel saklama/kapatma durumu ve kullanılabilir kontroller",
  "Owner current subscription and billing recovery": "Sahip için güncel abonelik ve faturalandırma kurtarma",
  "Ask the current organization owner to inspect organization-wide export, closure or billing controls. Project access does not grant those permissions.": "Kuruluş genelindeki dışa aktarım, kapatma veya faturalandırma kontrollerini incelemesi için güncel kuruluş sahibine başvurun. Proje erişimi bu izinleri vermez.",
  "Your own security, personal JSON export and access-closure status": "Kendi güvenliğiniz, kişisel JSON dışa aktarımınız ve erişim kapatma durumunuz",

  "Private project evidence reports": "Özel proje kanıt raporları",
  "Return to project dashboard": "Proje panosuna dön",
  "Exports contain only the selected project findings and their recorded source-limited evidence. They are snapshots, not complete traffic reports or proof of causal improvement. Access to authenticated downloads is checked again for each request.": "Dışa aktarımlar yalnızca seçilen proje bulgularını ve kayıtlı, kaynakla sınırlı kanıtlarını içerir. Bunlar anlık görüntülerdir; tam trafik raporları veya nedensel iyileşme kanıtı değildir. Kimlik doğrulamalı indirme erişimi her istekte yeniden kontrol edilir.",
  "Unreviewed Turkish report, notification and support interface draft in local development. Provider values and customer text are not translated; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe rapor, bildirim ve destek arayüzü taslağı. Sağlayıcı değerleri ve müşteri metni çevrilmez; iki dilli onay bekleniyor.",
  "Loading current project report permissions.": "Güncel proje raporu izinleri yükleniyor.",
  "Create a bounded evidence snapshot": "Sınırlı bir kanıt anlık görüntüsü oluştur",
  "Current finding sources are unavailable; no export can be created from missing evidence.": "Güncel bulgu kaynakları kullanılamıyor; eksik kanıttan dışa aktarım oluşturulamaz.",
  "No stored source findings to select. An empty result does not mean no issue exists.": "Seçilecek kayıtlı kaynak bulgusu yok. Boş sonuç, sorun olmadığı anlamına gelmez.",
  "Select up to 20 findings from this project": "Bu projeden en fazla 20 bulgu seçin",
  "current source": "güncel kaynak",
  "stale source; not selectable": "eski kaynak; seçilemez",
  "Download format": "İndirme biçimi",
  "Spreadsheet-safe CSV": "Elektronik tablo için güvenli CSV",
  "JSON": "JSON",
  "Create private snapshot": "Özel anlık görüntü oluştur",
  "Saved private reports": "Kaydedilmiş özel raporlar",
  "No report snapshots have been created for this project.": "Bu proje için rapor anlık görüntüsü oluşturulmamış.",
  "Report": "Rapor",
  "bytes": "bayt",
  "finding(s),": "bulgu,",
  "action(s),": "eylem,",
  "outcome(s).": "sonuç.",
  "Download (current project permission required)": "İndir (güncel proje izni gerekir)",
  "Optional external report shares": "İsteğe bağlı harici rapor paylaşımları",
  "Anyone holding a link can download the selected report without signing in until the earlier of expiry, revocation or loss of your sharing permission. The intended recipient is a disclosure record, not an email-identity check. Already downloaded copies cannot be erased. No email is sent automatically.": "Bağlantıya sahip olan herkes, süre dolması, erişimin kaldırılması veya paylaşım izninizin kaybından ilk gerçekleşene kadar seçilen raporu oturum açmadan indirebilir. Hedef alıcı bir açıklama kaydıdır; e-posta kimlik kontrolü değildir. İndirilmiş kopyalar silinemez. Otomatik e-posta gönderilmez.",
  "Share history is unavailable; do not assume an earlier link was revoked.": "Paylaşım geçmişi kullanılamıyor; önceki bağlantının erişiminin kaldırıldığını varsaymayın.",
  "Exactly one private report": "Tam olarak bir özel rapor",
  "Intended recipient email (not verified or automatically delivered)": "Hedef alıcının e-postası (doğrulanmaz veya otomatik gönderilmez)",
  "Expiry in hours (1–168)": "Saat cinsinden süre (1–168)",
  "I understand this is a bearer link: anyone who obtains it may download this report until access ends.": "Bunun bir erişim bağlantısı olduğunu anlıyorum: bağlantıyı elde eden herkes erişim sona erene kadar bu raporu indirebilir.",
  "Issue one-time share link": "Bir kez gösterilen paylaşım bağlantısı oluştur",
  "Copy this link now; it will not be shown again. It is not sent to the recipient.": "Bu bağlantıyı şimdi kopyalayın; tekrar gösterilmez. Alıcıya gönderilmez.",
  "One-time report link": "Bir kez gösterilen rapor bağlantısı",
  "No share history for this project.": "Bu proje için paylaşım geçmişi yok.",
  "intended recipient": "hedef alıcı",
  "expires": "bitiş zamanı",
  "Revoke future access": "Gelecekteki erişimi kaldır",
  "Select an authorized project.": "Yetkili olduğunuz bir proje seçin.",
  "Current project report access is unavailable.": "Güncel proje raporu erişimi kullanılamıyor.",
  "Private snapshot saved. Download rechecks your current project access.": "Özel anlık görüntü kaydedildi. İndirme, güncel proje erişiminizi yeniden kontrol eder.",
  "Report creation was unavailable. Refresh project evidence before retrying.": "Rapor oluşturulamadı. Tekrar denemeden önce proje kanıtlarını yenileyin.",
  "Share recorded; copy the one-time bearer link and deliver it only to your intended recipient.": "Paylaşım kaydedildi; bir kez gösterilen erişim bağlantısını kopyalayın ve yalnızca hedef alıcınıza iletin.",
  "Share outcome unavailable. Inspect share history before issuing another link.": "Paylaşım sonucu kullanılamıyor. Başka bir bağlantı oluşturmadan önce paylaşım geçmişini inceleyin.",
  "Future link access revoked; copies already downloaded cannot be erased.": "Gelecekteki bağlantı erişimi kaldırıldı; indirilmiş kopyalar silinemez.",
  "Revocation outcome unavailable. Refresh share history before relying on it.": "Erişim kaldırma sonucu kullanılamıyor. Buna güvenmeden önce paylaşım geçmişini yenileyin.",
};
