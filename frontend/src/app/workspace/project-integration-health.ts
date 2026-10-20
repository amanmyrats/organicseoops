import { Component, Input, OnChanges, OnDestroy, signal, SimpleChanges } from '@angular/core';
import { draftProductLanguage } from '../product-language';
import { AccountApi } from '../account/account-api';
import { calendar, microseconds } from './utc-date';

const sourceLabels = {
  csv_only: 'CSV-only source; API synchronization is not recorded here',
  api_sync_metadata: 'Retained API sync metadata; current provider readiness is not established',
  reconnect_required: 'Recorded provider authorization requires reconnection',
  disconnected: 'Disconnected; this record alone does not establish why',
  unavailable: 'Connection unavailable', scope_unavailable: 'Current exact project scope unavailable',
  authorization_unavailable: 'Current selected source authorization unavailable',
  exact_origin_attribution_unavailable: 'GA4 exact-origin attribution unavailable; no project reporting evidence',
};
const statusLabels = { idle: 'Idle', running: 'Running', waiting_provider: 'Waiting for provider',
  succeeded: 'Recorded sync succeeded within its bounded coverage', partially_succeeded: 'Partially succeeded',
  failed: 'Recorded sync failed', unavailable: 'Recorded sync unavailable' };
const categories = ['', 'quota_limited', 'partial_coverage', 'handler_failed', 'request_outcome_unknown',
  'authorization_unavailable', 'property_unavailable', 'authorization_rejected', 'reauthorization_required',
  'source_revoked', 'cancelled', 'malformed_response', 'unclassified_failure'];
type Sync = { status: keyof typeof statusLabels; quota_state: string; last_attempt_at: string | null;
  last_success_at: string | null; fresh_through: string | null; error_category: string };
type Row = { connection_id: number; provider: 'google_search_console' | 'google_analytics_4' | 'yandex_webmaster';
  connection_state: 'active' | 'disconnected' | 'unavailable'; source_state: keyof typeof sourceLabels; sync: Sync | null };
type Health = { method_version: string; scope: string; project_id: number; assessed_at: string; rows: Row[]; has_more: boolean };

@Component({
  selector: 'app-project-integration-health',
  template: `
    <section [attr.lang]="uiLanguage()" aria-labelledby="integration-health-title">
      <h2 id="integration-health-title">{{ t("Recorded integration health metadata") }}</h2>
      <p>{{ t("Inspect retained connection and sync records. Dates and status do not establish current provider readiness, complete collection, stale integrations or a confirmed SEO regression.") }}</p>
      <p>{{ t("Inspection does not send alerts, save alert consent, reconnect sources, retry synchronization or start paid analysis.") }}</p>
      <button type="button" [disabled]="busy()" (click)="inspect()">{{ t("Inspect / refresh integration metadata") }}</button>
      @if (busy()) { <p role="status">{{ t("Checking this project's integration metadata.") }}</p> }
      @if (error()) { <p role="alert">{{ t("Integration metadata is unavailable for this project. No synchronization or alert was requested.") }}</p> }
      @if (health(); as result) {
        <p>{{ t("Server assessment") }} {{ result.assessed_at }} (UTC).</p>
        @if (!result.rows.length) { <p role="status">{{ t("No retained connections in this view. Missing evidence is not a healthy-integration or zero-outcome result.") }}</p> }
        <ul>@for (row of result.rows; track row.connection_id) {
          <li>{{ t("Connection") }} {{ row.connection_id }} · <span lang="en">{{ row.provider === 'google_search_console' ? 'Google Search Console' : row.provider === 'yandex_webmaster' ? 'Yandex Webmaster' : 'Google Analytics 4' }}</span> · {{ t("stored connection state") }} <span lang="en">{{ row.connection_state }}</span>.
            <p>{{ sourceLabel(row.source_state) }}.</p>
            @if (row.sync; as sync) {
              <p>{{ statusLabel(sync.status) }}. {{ t("Recorded quota state:") }} <span lang="en">{{ sync.quota_state }}</span>.</p>
              <p>{{ t("Last recorded attempt:") }} {{ sync.last_attempt_at || t("not recorded") }}{{ sync.last_attempt_at ? ' (UTC)' : '' }}.</p>
              @if (sync.last_success_at) { <p>{{ t("Last recorded successful collection:") }} {{ sync.last_success_at }} (UTC).</p> }
              @else { <p>{{ t("No successful collection timestamp recorded; historical completeness is unknown.") }}</p> }
              <p>{{ t("Recorded fresh-through source calendar day:") }} {{ sync.fresh_through || t("unavailable") }}. {{ t("This can be newer than the latest older-backfill coverage.") }}</p>
              @if (sync.error_category) { <p>{{ t("Stored category:") }} <span lang="en">{{ sync.error_category.replaceAll('_', ' ') }}</span>; {{ t("no raw provider error is shown.") }}</p> }
            } @else if (row.provider === 'google_search_console' && row.source_state !== 'csv_only') {
              <p>{{ t("No sync cursor recorded. This is not a failed sync or proof that data was never collected.") }}</p>
            }
          </li>
        }</ul>
        @if (result.has_more) { <p>{{ t("Only the first 50 retained connections by identifier are shown; additional connections exist.") }}</p> }
      }
    </section>`,
  styles: `section { margin-block: 1.2rem; border-top: 1px solid #b9cfd5; }
    li { margin-block: 0.6rem; overflow-wrap: anywhere; }`,
})
export class ProjectIntegrationHealth implements OnChanges, OnDestroy {
  @Input() organizationId = 0;
  @Input() projectId = 0;
  @Input() language: 'en' | 'tr' = 'en';
  uiLanguage() { return draftProductLanguage(this.language); }
  t(text: string) { return this.uiLanguage() === 'tr' ? integrationHealthTurkish[text] ?? text : text; }
  readonly health = signal<Health | null>(null);
  readonly busy = signal(false);
  readonly error = signal(false);
  private generation = 0;
  constructor(private readonly api: AccountApi) {}
  ngOnChanges(changes?: SimpleChanges) {
    if (!changes || changes['organizationId'] || changes['projectId']) this.clear();
  }
  ngOnDestroy() { this.clear(); }
  private clear() { this.generation++; this.health.set(null); this.busy.set(false); this.error.set(false); }
  sourceLabel(state: Row['source_state']) { return this.t(sourceLabels[state]); }
  statusLabel(status: Sync['status']) { return this.t(statusLabels[status]); }

  async inspect() {
    this.clear();
    const generation = this.generation, organization = this.organizationId, project = this.projectId;
    if (![organization, project].every(id => Number.isSafeInteger(id) && id > 0)) { this.error.set(true); return; }
    const current = () => generation === this.generation && organization === this.organizationId && project === this.projectId;
    this.busy.set(true);
    try {
      const result = await this.api.projectIntegrationHealth(organization, project);
      if (!current()) return;
      const health = result.status === 200 ? readHealth(result.body, project) : null;
      if (!health) throw new Error();
      this.health.set(structuredClone(health));
    } catch { if (current()) this.error.set(true); }
    finally { if (current()) this.busy.set(false); }
  }
}

function readHealth(body: Record<string, unknown>, project: number): Health | null {
  const assessed = microseconds(body['assessed_at']);
  if (Object.keys(body).sort().join(',') !== 'assessed_at,has_more,method_version,project_id,rows,scope'
      || body['project_id'] !== project || body['method_version'] !== 'integration-health-metadata-v1'
      || body['scope'] !== 'bounded_connection_sync_metadata_not_readiness_staleness_regression_or_delivery_authority'
      || assessed === null || !Array.isArray(body['rows']) || body['rows'].length > 50
      || typeof body['has_more'] !== 'boolean' || body['has_more'] && body['rows'].length !== 50) return null;
  let previous = 0;
  for (const row of body['rows']) {
    if (!row || typeof row !== 'object' || Array.isArray(row)
        || Object.keys(row).sort().join(',') !== 'connection_id,connection_state,provider,source_state,sync'
        || !Number.isSafeInteger(row.connection_id) || row.connection_id <= previous
        || !['google_search_console', 'google_analytics_4', 'yandex_webmaster'].includes(row.provider)
        || !['active', 'disconnected', 'unavailable'].includes(row.connection_state)
        || typeof row.source_state !== 'string' || !Object.hasOwn(sourceLabels, row.source_state)) return null;
    previous = row.connection_id;
    if (row.provider === 'google_analytics_4') {
      if (row.source_state !== 'exact_origin_attribution_unavailable' || row.sync !== null) return null;
      continue;
    }
    if (row.source_state === 'exact_origin_attribution_unavailable'
        || row.connection_state !== 'active' && ![row.connection_state, 'reconnect_required'].includes(row.source_state)
        || row.connection_state === 'active' && ['disconnected', 'unavailable'].includes(row.source_state)
        || row.source_state === 'csv_only' && row.sync !== null) return null;
    if (row.sync === null) continue;
    const sync = row.sync;
    if (!sync || typeof sync !== 'object' || Array.isArray(sync)
        || Object.keys(sync).sort().join(',') !== 'error_category,fresh_through,last_attempt_at,last_success_at,quota_state,status'
        || typeof sync.status !== 'string' || !Object.hasOwn(statusLabels, sync.status)
        || !['available', 'limited', 'exhausted', 'unavailable'].includes(sync.quota_state)
        || typeof sync.error_category !== 'string' || !categories.includes(sync.error_category)
        || ['idle', 'running', 'succeeded'].includes(sync.status) && sync.error_category !== ''
        || ['failed', 'partially_succeeded', 'unavailable'].includes(sync.status) && !sync.error_category
        || sync.fresh_through !== null && calendar(sync.fresh_through) === null) return null;
    for (const field of ['last_attempt_at', 'last_success_at']) {
      if (sync[field] === null) continue;
      const date = microseconds(sync[field]);
      if (date === null || date > assessed) return null;
    }
  }
  return body as Health;
}

const integrationHealthTurkish: Readonly<Record<string, string>> = {
  "Recorded integration health metadata": "Kaydedilmiş entegrasyon sağlığı meta verileri",
  "Inspect retained connection and sync records. Dates and status do not establish current provider readiness, complete collection, stale integrations or a confirmed SEO regression.": "Saklanmış bağlantı ve senkronizasyon kayıtlarını inceleyin. Tarihler ve durum; güncel sağlayıcı hazırlığını, tam toplamayı, güncelliğini yitirmiş entegrasyonları veya doğrulanmış SEO gerilemesini kanıtlamaz.",
  "Inspection does not send alerts, save alert consent, reconnect sources, retry synchronization or start paid analysis.": "İnceleme uyarı göndermez, uyarı onayını kaydetmez, kaynakları yeniden bağlamaz, senkronizasyonu yeniden denemez veya ücretli analiz başlatmaz.",
  "Inspect / refresh integration metadata": "Entegrasyon meta verilerini incele / yenile",
  "Checking this project's integration metadata.": "Bu projenin entegrasyon meta verileri kontrol ediliyor.",
  "Integration metadata is unavailable for this project. No synchronization or alert was requested.": "Bu proje için entegrasyon meta verileri kullanılamıyor. Senkronizasyon veya uyarı istenmedi.",
  "Server assessment": "Sunucu değerlendirmesi",
  "No retained connections in this view. Missing evidence is not a healthy-integration or zero-outcome result.": "Bu görünümde saklanmış bağlantı yok. Eksik kanıt, sağlıklı entegrasyon veya sıfır sonuç anlamına gelmez.",
  "Connection": "Bağlantı",
  "stored connection state": "kayıtlı bağlantı durumu",
  "Recorded quota state:": "Kaydedilmiş kota durumu:",
  "Last recorded attempt:": "Son kaydedilmiş deneme:",
  "not recorded": "kaydedilmemiş",
  "Last recorded successful collection:": "Son kaydedilmiş başarılı toplama:",
  "No successful collection timestamp recorded; historical completeness is unknown.": "Başarılı toplama zaman damgası kaydedilmemiş; geçmiş kapsamın tamlığı bilinmiyor.",
  "Recorded fresh-through source calendar day:": "Kaydedilmiş güncellik sınırı kaynak takvim günü:",
  "unavailable": "kullanılamıyor",
  "This can be newer than the latest older-backfill coverage.": "Bu, en son eski tarih tamamlama kapsamından daha yeni olabilir.",
  "Stored category:": "Kayıtlı kategori:",
  "no raw provider error is shown.": "ham sağlayıcı hatası gösterilmez.",
  "No sync cursor recorded. This is not a failed sync or proof that data was never collected.": "Senkronizasyon imleci kaydedilmemiş. Bu, başarısız senkronizasyon veya verinin hiç toplanmadığının kanıtı değildir.",
  "Only the first 50 retained connections by identifier are shown; additional connections exist.": "Yalnızca kimliğe göre ilk 50 saklanmış bağlantı gösteriliyor; başka bağlantılar var.",
  "CSV-only source; API synchronization is not recorded here": "Yalnızca CSV kaynağı; API senkronizasyonu burada kaydedilmez",
  "Retained API sync metadata; current provider readiness is not established": "Saklanmış API senkronizasyon meta verileri; güncel sağlayıcı hazırlığı kanıtlanmış değildir",
  "Recorded provider authorization requires reconnection": "Kaydedilmiş sağlayıcı yetkilendirmesi yeniden bağlantı gerektiriyor",
  "Disconnected; this record alone does not establish why": "Bağlantı kesilmiş; bu kayıt tek başına nedenini kanıtlamaz",
  "Connection unavailable": "Bağlantı kullanılamıyor",
  "Current exact project scope unavailable": "Güncel tam proje kapsamı kullanılamıyor",
  "Current selected source authorization unavailable": "Güncel seçili kaynak yetkilendirmesi kullanılamıyor",
  "GA4 exact-origin attribution unavailable; no project reporting evidence": "GA4 tam kaynak kökeni ilişkilendirmesi kullanılamıyor; proje raporlama kanıtı yok",
  "Idle": "Boşta",
  "Running": "Çalışıyor",
  "Waiting for provider": "Sağlayıcı bekleniyor",
  "Recorded sync succeeded within its bounded coverage": "Kaydedilmiş senkronizasyon, sınırlı kapsamı içinde başarılı oldu",
  "Partially succeeded": "Kısmen başarılı oldu",
  "Recorded sync failed": "Kaydedilmiş senkronizasyon başarısız oldu",
  "Recorded sync unavailable": "Kaydedilmiş senkronizasyon kullanılamıyor"
};
