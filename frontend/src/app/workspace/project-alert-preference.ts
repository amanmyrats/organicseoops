import { Component, Input, OnChanges, OnDestroy, signal, SimpleChanges } from '@angular/core';
import { draftProductLanguage } from '../product-language';
import { AccountApi } from '../account/account-api';
import { DailyDelivery as Delivery, DailyHistory as History, readDailyTransportHistory } from './daily-transport-history';

type Frequency = 'off' | 'daily';
type Family = 'crawl_failure' | 'integration_health';
type Preference = { channel: 'email'; frequency: Frequency; source_families: Family[];
  revision: number; delivery_state: 'rollout_off' | 'enabled_optional' };
const families: Family[] = ['crawl_failure', 'integration_health'];

@Component({
  selector: 'app-project-alert-preference',
  template: `
    <section [attr.lang]="uiLanguage()" aria-labelledby="alert-preference-title">
      <h2 id="alert-preference-title">{{ t("Your optional project alert preference") }}</h2>
      <p>{{ t("This setting belongs only to you in this project, independently of weekly summaries and optional analytics. It does not change required account, security or billing notices.") }}</p>
      <p>{{ t("Saving daily intent does not directly schedule or send mail, run paid analysis or replay old failures. Optional operational digests use selected retained root crawl failure updates and Search Console reconnect-required records from the previous completed UTC day, with current verified primary email, project access, suppression, entitlement, exact source and related-episode deduplication checks.") }}</p>
      <p>{{ t("Crawl failures are retained operational records, not current incidents or important severity. Integration health is connection/sync metadata, not proof of age-based staleness or live readiness. These families do not establish a confirmed SEO regression.") }}</p>
      @if (busy()) { <p role="status">{{ t("Checking your own alert preference.") }}</p> }
      @if (error()) { <p role="alert">{{ t(error()) }}</p> }
      @if (saved(); as preference) {
        <p>{{ t("Saved alert email frequency:") }} <span lang="en">{{ preference.frequency }}</span>. {{ t("Selected source families:") }} {{ familyNames(preference.source_families) }}.</p>
        @if (preference.delivery_state === 'rollout_off') {
          <p>{{ t("Daily operational digest rollout is off. Stored daily intent remains; no optional daily mail is sent while off.") }}</p>
        } @else {
          <p>{{ t("Optional daily discovery is enabled by configuration. Only saved daily intent with eligible current sources and recipient may send. This is not confirmation of live email readiness or your current eligibility.") }}</p>
        }
        <form (submit)="save($event)">
          <label for="alert-frequency">{{ t("Your optional alert email frequency for this project") }}</label>
          <select id="alert-frequency" name="frequency" [value]="choice()" [disabled]="busy()"
            (change)="editFrequency($any($event.target).value)">
            <option value="off">{{ t("Off (default)") }}</option><option value="daily">{{ t("Daily (optional operational digest intent)") }}</option>
          </select>
          <fieldset [disabled]="busy()"><legend>{{ t("Your operational source families") }}</legend>
            <label><input type="checkbox" name="crawl_failure" [checked]="selected().includes('crawl_failure')"
              (change)="editFamily('crawl_failure', $any($event.target).checked)" /> {{ t("Retained crawl failures") }}</label>
            <label><input type="checkbox" name="integration_health" [checked]="selected().includes('integration_health')"
              (change)="editFamily('integration_health', $any($event.target).checked)" /> {{ t("Integration connection/sync health") }}</label>
          </fieldset>
          <p>{{ t("Daily intent requires at least one selected family. Off may retain selections; no optional alert mail is authorized while off.") }}</p>
          <button type="submit" [disabled]="busy()">{{ t("Save my alert preference") }}</button>
        </form>
      }
      <button type="button" [disabled]="busy()" (click)="load()">{{ t("Refresh my saved alert preference") }}</button>
      @if (message()) { <p role="status">{{ t(message()) }}</p> }
      <h3>{{ t("Your retained daily transport history") }}</h3>
      <p>{{ t("Inspect only your own records in this project. History is not current eligibility, recipient delivery or reading, an incident assessment or an SEO outcome. Unknown sends are not replayed.") }}</p>
      <button type="button" [disabled]="busy() || historyBusy() || !saved()" (click)="inspectHistory()">{{ t("Inspect / refresh my daily history") }}</button>
      @if (historyBusy()) { <p role="status">{{ t("Checking your retained daily transport history.") }}</p> }
      @if (historyError()) { <p role="alert">{{ t("Your retained daily transport history is unavailable. No send or retry was requested.") }}</p> }
      @if (history(); as retained) {
        @if (!retained.rows.length) { <p role="status">{{ t("No retained own daily records. This does not establish delivery or a zero SEO outcome.") }}</p> }
        <ul>@for (row of retained.rows; track row.id) {
          <li>{{ t("Record") }} {{ row.id }} · {{ t("completed source-coverage day") }} {{ row.day_start }} (UTC) · {{ stateLabel(row.state) }}.
            {{ t("Created") }} {{ row.created_at }} (UTC).
            @if (row.attempted_at) { {{ t("Attempt recorded") }} {{ row.attempted_at }} (UTC). }
            @if (row.accepted_at) { {{ t("Transport accepted") }} {{ row.accepted_at }} {{ t("(UTC), not delivered or read.") }} }
          </li>
        }</ul>
        @if (retained.has_more) { <p>{{ t("Only the newest 20 retained own records are shown; older records exist.") }}</p> }
      }
    </section>
  `,
  styles: `section { margin-block: 1.2rem; border-top: 1px solid #b9cfd5; }
    form, fieldset { display: grid; gap: 0.6rem; max-width: 36rem; }
    p, label, li { overflow-wrap: anywhere; } li { margin-block: 0.6rem; }`,
})
export class ProjectAlertPreference implements OnChanges, OnDestroy {
  @Input() organizationId = 0;
  @Input() projectId = 0;
  @Input() language: 'en' | 'tr' = 'en';
  uiLanguage() { return draftProductLanguage(this.language); }
  t(text: string) { return this.uiLanguage() === 'tr' ? alertTurkish[text] ?? text : text; }
  readonly choice = signal<Frequency>('off');
  readonly selected = signal<Family[]>([]);
  readonly saved = signal<Preference | null>(null);
  readonly busy = signal(false);
  readonly error = signal('');
  readonly message = signal('');
  readonly history = signal<History | null>(null);
  readonly historyBusy = signal(false);
  readonly historyError = signal(false);
  private generation = 0;
  private historyGeneration = 0;

  constructor(private readonly api: AccountApi) {}
  ngOnChanges(changes?: SimpleChanges) {
    if (!changes || changes['organizationId'] || changes['projectId']) void this.load();
  }
  ngOnDestroy() { this.generation++; this.clear(); this.busy.set(false); }

  private clear() {
    this.saved.set(null); this.choice.set('off'); this.selected.set([]);
    this.error.set(''); this.message.set('');
    this.clearHistory();
  }

  private clearHistory() {
    this.historyGeneration++; this.history.set(null); this.historyBusy.set(false); this.historyError.set(false);
  }

  editFrequency(value: string) {
    if (this.busy() || !this.saved() || value !== 'off' && value !== 'daily') return;
    this.choice.set(value); this.error.set(''); this.message.set('');
    this.clearHistory();
  }

  editFamily(family: Family, checked: boolean) {
    if (this.busy() || !this.saved() || !families.includes(family) || typeof checked !== 'boolean') return;
    this.selected.set(families.filter(item => item === family ? checked : this.selected().includes(item)));
    this.error.set(''); this.message.set('');
    this.clearHistory();
  }

  familyNames(values: Family[]) {
    return values.map(value => this.t(value === 'crawl_failure' ? 'retained crawl failures' : 'integration health')).join(', ') || this.t('none');
  }

  async load() {
    const generation = ++this.generation, organization = this.organizationId, project = this.projectId;
    this.clear(); this.busy.set(false);
    if (![organization, project].every(id => Number.isSafeInteger(id) && id > 0)) {
      this.error.set('Choose an authorized project before reading your alert preference.'); return;
    }
    const current = () => generation === this.generation && organization === this.organizationId && project === this.projectId;
    this.busy.set(true);
    try {
      const result = await this.api.projectAlertPreference(organization, project);
      if (!current()) return;
      const preference = result.status === 200 ? readPreference(result.body, project) : null;
      if (!preference) throw new Error();
      this.saved.set(preference); this.choice.set(preference.frequency); this.selected.set([...preference.source_families]);
    } catch {
      if (current()) { this.clear(); this.error.set('Your own alert preference is unavailable. Refresh before saving.'); }
    } finally { if (current()) this.busy.set(false); }
  }

  async save(event: Event) {
    event.preventDefault();
    const saved = this.saved();
    if (this.busy() || !saved) return;
    const frequency = this.choice(), selected = [...this.selected()];
    this.clearHistory();
    if (frequency === 'daily' && !selected.length) {
      this.error.set('Choose at least one source family for daily intent.'); return;
    }
    const generation = this.generation, organization = this.organizationId, project = this.projectId;
    const current = () => generation === this.generation && organization === this.organizationId && project === this.projectId;
    const expected = saved.revision + (frequency !== saved.frequency || selected.join(',') !== saved.source_families.join(',') ? 1 : 0);
    this.busy.set(true); this.error.set(''); this.message.set('');
    try {
      const result = await this.api.saveProjectAlertPreference(organization, project, frequency, selected, saved.revision);
      if (!current()) return;
      const preference = result.status === 200 ? readPreference(result.body, project) : null;
      if (!preference || preference.frequency !== frequency || preference.revision !== expected
          || preference.source_families.join(',') !== selected.join(',')) throw new Error();
      this.saved.set(preference);
      this.message.set('Alert intent saved. This save did not directly schedule or send an optional digest.');
    } catch {
      if (current()) {
        this.clear(); this.error.set('Save outcome unavailable. Refresh your saved alert preference before another change; no automatic retry occurs.');
      }
    } finally { if (current()) this.busy.set(false); }
  }

  stateLabel(state: Delivery['state']) {
    return this.t({ queued: 'Queued, not sent', sending: 'Sending durably committed; outcome pending',
      transport_accepted: 'Transport accepted', skipped: 'Skipped: current source or recipient changed',
      unknown: 'Unknown transport outcome; no replay' }[state]);
  }

  async inspectHistory() {
    if (this.busy() || !this.saved()) return;
    this.clearHistory();
    const organization = this.organizationId, project = this.projectId;
    if (![organization, project].every(id => Number.isSafeInteger(id) && id > 0)) {
      this.historyError.set(true); return;
    }
    const generation = this.historyGeneration, revision = this.saved()!.revision;
    const current = () => generation === this.historyGeneration && organization === this.organizationId
      && project === this.projectId && revision === this.saved()?.revision;
    this.historyBusy.set(true);
    try {
      const result = await this.api.projectAlertDeliveries(organization, project);
      if (!current()) return;
      const retained = result.status === 200 ? readDailyTransportHistory(result.body, project,
        'own-daily-operational-delivery-history-v1',
        'own_retained_transport_history_not_recipient_delivery_read_incident_or_current_eligibility') : null;
      if (!retained) throw new Error();
      this.history.set(retained);
    } catch { if (current()) this.historyError.set(true); }
    finally { if (current()) this.historyBusy.set(false); }
  }
}

function readPreference(body: Record<string, unknown>, project: number): Preference | null {
  if (Object.keys(body).sort().join(',') !== 'preference,project_id' || body['project_id'] !== project) return null;
  const value = body['preference'];
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const row = value as Record<string, unknown>;
  const selected = row['source_families'];
  if (Object.keys(row).sort().join(',') !== 'channel,delivery_state,frequency,revision,source_families'
      || row['channel'] !== 'email' || row['delivery_state'] !== 'rollout_off' && row['delivery_state'] !== 'enabled_optional'
      || row['frequency'] !== 'off' && row['frequency'] !== 'daily'
      || !Number.isSafeInteger(row['revision']) || Number(row['revision']) < 0 || Number(row['revision']) >= 2 ** 31
      || !Array.isArray(selected) || selected.length > 2
      || selected.some(family => typeof family !== 'string' || !families.includes(family as Family))
      || selected.join(',') !== families.filter(family => selected.includes(family)).join(',')
      || row['frequency'] === 'daily' && !selected.length
      || row['revision'] === 0 && (row['frequency'] !== 'off' || selected.length)) return null;
  return structuredClone(row) as Preference;
}

const alertTurkish: Readonly<Record<string, string>> = {
  "Off (default)": "Kapalı (varsayılan)",
  "Record": "Kayıt",
  "Created": "Oluşturulma zamanı",
  "Attempt recorded": "Kaydedilmiş deneme zamanı",
  "Transport accepted": "İletim kabul edildi",
  "(UTC), not delivered or read.": "(UTC), teslim edildi veya okundu anlamına gelmez.",
  "Only the newest 20 retained own records are shown; older records exist.": "Yalnızca size ait saklanmış en yeni 20 kayıt gösteriliyor; daha eski kayıtlar var.",
  "Queued, not sent": "Kuyrukta, gönderilmedi",
  "Sending durably committed; outcome pending": "Gönderim kalıcı olarak kaydedildi; sonuç bekleniyor",
  "Skipped: current source or recipient changed": "Atlandı: güncel kaynak veya alıcı değişti",
  "Unknown transport outcome; no replay": "İletim sonucu bilinmiyor; tekrar gönderilmez",
  "Your optional project alert preference": "İsteğe bağlı proje uyarısı tercihiniz",
  "This setting belongs only to you in this project, independently of weekly summaries and optional analytics. It does not change required account, security or billing notices.": "Bu ayar, haftalık özetlerden ve isteğe bağlı analizlerden bağımsız olarak bu projede yalnızca size aittir. Zorunlu hesap, güvenlik veya faturalandırma bildirimlerini değiştirmez.",
  "Saving daily intent does not directly schedule or send mail, run paid analysis or replay old failures. Optional operational digests use selected retained root crawl failure updates and Search Console reconnect-required records from the previous completed UTC day, with current verified primary email, project access, suppression, entitlement, exact source and related-episode deduplication checks.": "Günlük niyeti kaydetmek doğrudan e-posta planlamaz veya göndermez, ücretli analiz çalıştırmaz veya eski hataları tekrarlamaz. İsteğe bağlı operasyon özetleri, önceki tamamlanmış UTC günündeki seçili saklanmış temel tarama hatası güncellemelerini ve Search Console yeniden bağlantı gerektiren kayıtlarını kullanır; güncel doğrulanmış birincil e-posta, proje erişimi, gönderim engelleme, kullanım hakkı, tam kaynak ve ilgili olayın tekrarını önleme kontrolleri uygulanır.",
  "Crawl failures are retained operational records, not current incidents or important severity. Integration health is connection/sync metadata, not proof of age-based staleness or live readiness. These families do not establish a confirmed SEO regression.": "Tarama hataları saklanmış operasyon kayıtlarıdır; güncel olaylar veya önemli ciddiyet düzeyi değildir. Entegrasyon sağlığı bağlantı/senkronizasyon meta verisidir; yaşa bağlı eskime veya canlı hazırlık kanıtı değildir. Bu kaynak aileleri doğrulanmış SEO gerilemesini kanıtlamaz.",
  "Checking your own alert preference.": "Kendi uyarı tercihiniz kontrol ediliyor.",
  "Saved alert email frequency:": "Kaydedilmiş uyarı e-posta sıklığı:",
  "Selected source families:": "Seçili kaynak aileleri:",
  "Daily operational digest rollout is off. Stored daily intent remains; no optional daily mail is sent while off.": "Günlük operasyon özeti etkinleştirilmemiş. Saklanmış günlük niyet korunur; kapalıyken isteğe bağlı günlük e-posta gönderilmez.",
  "Optional daily discovery is enabled by configuration. Only saved daily intent with eligible current sources and recipient may send. This is not confirmation of live email readiness or your current eligibility.": "İsteğe bağlı günlük keşif yapılandırmayla etkinleştirilmiş. Yalnızca uygun güncel kaynaklar ve alıcıyla kaydedilmiş günlük niyet gönderime uygun olabilir. Bu, canlı e-posta hazırlığının veya güncel uygunluğunuzun doğrulanması değildir.",
  "Your optional alert email frequency for this project": "Bu proje için isteğe bağlı uyarı e-posta sıklığınız",
  "Daily (optional operational digest intent)": "Günlük (isteğe bağlı operasyon özeti niyeti)",
  "Your operational source families": "Operasyonel kaynak aileleriniz",
  "Retained crawl failures": "Saklanmış tarama hataları",
  "Integration connection/sync health": "Entegrasyon bağlantı/senkronizasyon sağlığı",
  "Daily intent requires at least one selected family. Off may retain selections; no optional alert mail is authorized while off.": "Günlük niyet için en az bir seçili kaynak ailesi gerekir. Kapalı durum seçimleri koruyabilir; kapalıyken isteğe bağlı uyarı e-postasına izin verilmez.",
  "Save my alert preference": "Uyarı tercihimi kaydet",
  "Refresh my saved alert preference": "Kaydedilmiş uyarı tercihimi yenile",
  "Your retained daily transport history": "Saklanmış günlük iletim geçmişiniz",
  "Inspect only your own records in this project. History is not current eligibility, recipient delivery or reading, an incident assessment or an SEO outcome. Unknown sends are not replayed.": "Bu projede yalnızca kendi kayıtlarınızı inceleyin. Geçmiş, güncel uygunluk, alıcıya teslim veya okunma, olay değerlendirmesi ya da SEO sonucu değildir. Sonucu bilinmeyen gönderimler tekrarlanmaz.",
  "Inspect / refresh my daily history": "Günlük geçmişimi incele / yenile",
  "Checking your retained daily transport history.": "Saklanmış günlük iletim geçmişiniz kontrol ediliyor.",
  "Your retained daily transport history is unavailable. No send or retry was requested.": "Saklanmış günlük iletim geçmişiniz kullanılamıyor. Gönderim veya yeniden deneme istenmedi.",
  "No retained own daily records. This does not establish delivery or a zero SEO outcome.": "Size ait saklanmış günlük kayıt yok. Bu, teslimatı veya sıfır SEO sonucunu kanıtlamaz.",
  "completed source-coverage day": "tamamlanmış kaynak kapsamı günü",
  "retained crawl failures": "saklanmış tarama hataları",
  "integration health": "entegrasyon sağlığı",
  "none": "yok",
  "Choose an authorized project before reading your alert preference.": "Uyarı tercihinizi okumadan önce yetkili olduğunuz bir proje seçin.",
  "Your own alert preference is unavailable. Refresh before saving.": "Kendi uyarı tercihiniz kullanılamıyor. Kaydetmeden önce yenileyin.",
  "Choose at least one source family for daily intent.": "Günlük niyet için en az bir kaynak ailesi seçin.",
  "Alert intent saved. This save did not directly schedule or send an optional digest.": "Uyarı niyeti kaydedildi. Bu kayıt doğrudan isteğe bağlı özet planlamadı veya göndermedi.",
  "Save outcome unavailable. Refresh your saved alert preference before another change; no automatic retry occurs.": "Kaydetme sonucu kullanılamıyor. Başka bir değişiklik yapmadan önce kaydedilmiş uyarı tercihinizi yenileyin; otomatik yeniden deneme yapılmaz.",
};
