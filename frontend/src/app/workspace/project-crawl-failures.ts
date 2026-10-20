import { Component, Input, OnChanges, OnDestroy, signal, SimpleChanges } from '@angular/core';
import { draftProductLanguage } from '../product-language';
import { AccountApi } from '../account/account-api';
import { microseconds } from './utc-date';

type Failure = { job_id: number; source_method: 'crawl-http-v1' | 'crawl-http-v2'; created_at: string;
  status_updated_at: string; failure_category: 'handler_failed' | 'crawl_deadline' | 'robots_unavailable' | 'crawl_incomplete' | 'unclassified_failure' };
type History = { method_version: string; scope: string; project_id: number; assessed_at: string; rows: Failure[]; has_more: boolean };

@Component({
  selector: 'app-project-crawl-failures',
  template: `
    <section [attr.lang]="uiLanguage()" aria-labelledby="crawl-failures-title">
      <h2 id="crawl-failures-title">{{ t("Retained failed crawl jobs") }}</h2>
      <p>{{ t("Inspect this project's recorded failed crawl jobs only. Historical failures are not confirmed current incidents, SEO regressions or clean-site evidence. Successful, partial, cancelled and other job types are outside this view.") }}</p>
      <p>{{ t("Creation and status-update times are separate; an update is not a proven first-failure or completion time. Inspection does not send an alert, save alert consent, retry work or start paid analysis.") }}</p>
      <button type="button" [disabled]="busy()" (click)="inspect()">{{ t("Inspect / refresh retained crawl failures") }}</button>
      @if (busy()) { <p role="status">{{ t("Checking retained failed crawl jobs.") }}</p> }
      @if (error()) { <p role="alert">{{ t("Retained crawl failures are unavailable for this project. No send or retry was requested.") }}</p> }
      @if (history(); as result) {
        <p>{{ t("Server assessment") }} {{ result.assessed_at }} (UTC). {{ t("Supported stored methods:") }} <span lang="en">crawl-http-v1</span> {{ t("and") }} <span lang="en">crawl-http-v2</span>.</p>
        @if (!result.rows.length) { <p role="status">{{ t("No matching retained failures. This does not establish a clean site or absence of current issues.") }}</p> }
        <ul>@for (row of result.rows; track row.job_id) {
          <li>{{ t("Job") }} {{ row.job_id }} · {{ categoryLabel(row.failure_category) }} · <span lang="en">{{ row.source_method }}</span>.
            {{ t("Created") }} {{ row.created_at }} (UTC); {{ t("status updated") }} {{ row.status_updated_at }} (UTC).</li>
        }</ul>
        @if (result.has_more) { <p>{{ t("Only the newest 20 matching retained failures are shown; older matching records exist.") }}</p> }
      }
    </section>`,
  styles: `section { margin-block: 1.2rem; border-top: 1px solid #b9cfd5; }
    li { margin-block: 0.6rem; overflow-wrap: anywhere; }`,
})
export class ProjectCrawlFailures implements OnChanges, OnDestroy {
  @Input() organizationId = 0;
  @Input() projectId = 0;
  @Input() language: 'en' | 'tr' = 'en';
  uiLanguage() { return draftProductLanguage(this.language); }
  t(text: string) { return this.uiLanguage() === 'tr' ? crawlFailuresTurkish[text] ?? text : text; }
  readonly history = signal<History | null>(null);
  readonly busy = signal(false);
  readonly error = signal(false);
  private generation = 0;
  constructor(private readonly api: AccountApi) {}
  ngOnChanges(changes?: SimpleChanges) {
    if (!changes || changes['organizationId'] || changes['projectId']) this.clear();
  }
  ngOnDestroy() { this.clear(); }
  private clear() { this.generation++; this.history.set(null); this.busy.set(false); this.error.set(false); }

  categoryLabel(category: Failure['failure_category']) {
    return this.t({ handler_failed: 'Crawl worker failed', crawl_deadline: 'Crawl deadline reached',
      robots_unavailable: 'Robots source unavailable', crawl_incomplete: 'Crawl incomplete',
      unclassified_failure: 'Unclassified stored failure; details unavailable' }[category]);
  }

  async inspect() {
    this.clear();
    const generation = this.generation, organization = this.organizationId, project = this.projectId;
    if (![organization, project].every(id => Number.isSafeInteger(id) && id > 0)) {
      this.error.set(true); return;
    }
    const current = () => generation === this.generation && organization === this.organizationId && project === this.projectId;
    this.busy.set(true);
    try {
      const result = await this.api.projectCrawlFailures(organization, project);
      if (!current()) return;
      const history = result.status === 200 ? readHistory(result.body, project) : null;
      if (!history) throw new Error();
      this.history.set(structuredClone(history));
    } catch { if (current()) this.error.set(true); }
    finally { if (current()) this.busy.set(false); }
  }
}

function readHistory(body: Record<string, unknown>, project: number): History | null {
  const assessed = microseconds(body['assessed_at']);
  if (Object.keys(body).sort().join(',') !== 'assessed_at,has_more,method_version,project_id,rows,scope'
      || body['project_id'] !== project || body['method_version'] !== 'retained-crawl-failures-v1'
      || body['scope'] !== 'retained_failed_crawl_jobs_not_current_incident_regression_or_retry_authority'
      || assessed === null || !Array.isArray(body['rows']) || body['rows'].length > 20
      || typeof body['has_more'] !== 'boolean' || body['has_more'] && body['rows'].length !== 20) return null;
  const ids = new Set<number>(); let previous: bigint | null = null, previousId = Infinity;
  for (const row of body['rows']) {
    if (!row || typeof row !== 'object' || Array.isArray(row)
        || Object.keys(row).sort().join(',') !== 'created_at,failure_category,job_id,source_method,status_updated_at'
        || !Number.isSafeInteger(row.job_id) || row.job_id < 1 || ids.has(row.job_id)
        || !['crawl-http-v1', 'crawl-http-v2'].includes(row.source_method)
        || typeof row.failure_category !== 'string'
        || !['handler_failed', 'crawl_deadline', 'robots_unavailable', 'crawl_incomplete', 'unclassified_failure'].includes(row.failure_category)) return null;
    const created = microseconds(row.created_at), updated = microseconds(row.status_updated_at);
    if (created === null || updated === null || created > updated || updated > assessed
        || previous !== null && (updated > previous || updated === previous && row.job_id >= previousId)) return null;
    ids.add(row.job_id); previous = updated; previousId = row.job_id;
  }
  return body as History;
}

const crawlFailuresTurkish: Readonly<Record<string, string>> = {
  "Retained failed crawl jobs": "Saklanmış başarısız tarama işleri",
  "Inspect this project's recorded failed crawl jobs only. Historical failures are not confirmed current incidents, SEO regressions or clean-site evidence. Successful, partial, cancelled and other job types are outside this view.": "Yalnızca bu projenin kaydedilmiş başarısız tarama işlerini inceleyin. Geçmiş hatalar, doğrulanmış güncel olaylar, SEO gerilemeleri veya sorunsuz site kanıtı değildir. Başarılı, kısmi, iptal edilmiş ve diğer iş türleri bu görünümün dışındadır.",
  "Creation and status-update times are separate; an update is not a proven first-failure or completion time. Inspection does not send an alert, save alert consent, retry work or start paid analysis.": "Oluşturulma ve durum güncelleme zamanları ayrıdır; bir güncelleme, ilk hata veya tamamlanma zamanını kanıtlamaz. İnceleme uyarı göndermez, uyarı onayını kaydetmez, işi yeniden denemez veya ücretli analiz başlatmaz.",
  "Inspect / refresh retained crawl failures": "Saklanmış tarama hatalarını incele / yenile",
  "Checking retained failed crawl jobs.": "Saklanmış başarısız tarama işleri kontrol ediliyor.",
  "Retained crawl failures are unavailable for this project. No send or retry was requested.": "Bu proje için saklanmış tarama hataları kullanılamıyor. Gönderim veya yeniden deneme istenmedi.",
  "Server assessment": "Sunucu değerlendirmesi",
  "Supported stored methods:": "Desteklenen kayıtlı yöntemler:",
  "and": "ve",
  "No matching retained failures. This does not establish a clean site or absence of current issues.": "Eşleşen saklanmış hata yok. Bu, sitenin sorunsuz olduğunu veya güncel sorunların bulunmadığını kanıtlamaz.",
  "Job": "İş",
  "Created": "Oluşturulma",
  "status updated": "durum güncellemesi",
  "Only the newest 20 matching retained failures are shown; older matching records exist.": "Yalnızca en yeni 20 eşleşen saklanmış hata gösteriliyor; daha eski eşleşen kayıtlar var.",
  "Crawl worker failed": "Tarama çalışanı başarısız oldu",
  "Crawl deadline reached": "Tarama zaman sınırına ulaşıldı",
  "Robots source unavailable": "Robots kaynağı kullanılamıyor",
  "Crawl incomplete": "Tarama tamamlanmadı",
  "Unclassified stored failure; details unavailable": "Sınıflandırılmamış kayıtlı hata; ayrıntılar kullanılamıyor"
};
