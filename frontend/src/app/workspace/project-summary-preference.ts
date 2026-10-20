import { Component, Input, OnChanges, OnDestroy, signal, SimpleChanges } from '@angular/core';
import { draftProductLanguage } from '../product-language';
import { AccountApi } from '../account/account-api';
import { calendar, microseconds } from './utc-date';

type Frequency = 'off' | 'weekly';
type Preference = { channel: 'email'; frequency: Frequency; revision: number; delivery_state: 'rollout_off' | 'enabled_optional' };
type Delivery = { id: number; week_start: string; created_at: string; attempted_at: string | null;
  accepted_at: string | null; state: 'queued' | 'sending' | 'transport_accepted' | 'skipped' | 'unknown'; error_category: string };
type History = { method_version: string; project_id: number; scope: string; rows: Delivery[]; has_more: boolean };

@Component({
  selector: 'app-project-summary-preference',
  template: `
    <section [attr.lang]="uiLanguage()" aria-labelledby="summary-preference-title">
      <h2 id="summary-preference-title">{{ t("Your optional project summary preference") }}</h2>
      <p>{{ t("This setting belongs only to you in this project. Saving a preference does not directly schedule or send mail.") }}</p>
      <p>{{ t("Optional summaries use selected private reports from the previous completed UTC report-creation week, not proof of SEO changes that week. No older-week backlog or paid analysis is started to fill a summary. Access, verified primary email, suppression and entitlement are checked at delivery. This setting does not change required account, security or billing notices.") }}</p>
      @if (busy()) { <p role="status">{{ t("Checking your current summary preference.") }}</p> }
      @if (error()) { <p role="alert">{{ t(error()) }}</p> }
      @if (revision() !== null) {
        <p>{{ t("Saved email frequency:") }} <span lang="en">{{ savedFrequency() }}</span>.</p>
        @if (deliveryState() === 'rollout_off') {
          <p>{{ t("Weekly delivery rollout is off. Saved weekly intent is retained; no optional weekly mail is sent while off.") }}</p>
        } @else {
          <p>{{ t("Optional weekly discovery is enabled by configuration. Only saved weekly intent with a current eligible report and recipient may send. This is not confirmation of live email readiness or your current eligibility.") }}</p>
        }
        <form (submit)="save($event)">
          <label for="summary-frequency">{{ t("Your optional email frequency for this project") }}</label>
          <select id="summary-frequency" name="frequency" [value]="choice()" [disabled]="busy()"
            (change)="edit($any($event.target).value)">
            <option value="off">{{ t("Off (default)") }}</option><option value="weekly">{{ t("Weekly (optional intent)") }}</option>
          </select>
          <button type="submit" [disabled]="busy()">{{ t("Save my preference") }}</button>
        </form>
      }
      <button type="button" [disabled]="busy()" (click)="load()">{{ t("Refresh my saved preference") }}</button>
      @if (message()) { <p role="status">{{ t(message()) }}</p> }
      <h3>{{ t("Your retained weekly transport history") }}</h3>
      <p>{{ t("Inspect only your own records in this project. History is not current eligibility, recipient delivery or reading, or an SEO outcome. Unknown sends are not replayed.") }}</p>
      <button type="button" [disabled]="busy() || historyBusy() || revision() === null" (click)="inspectHistory()">{{ t("Inspect / refresh my weekly history") }}</button>
      @if (historyBusy()) { <p role="status">{{ t("Checking your retained weekly transport history.") }}</p> }
      @if (historyError()) { <p role="alert">{{ t("Your retained weekly transport history is unavailable. No send or retry was requested.") }}</p> }
      @if (history(); as retained) {
        @if (!retained.rows.length) { <p role="status">{{ t("No retained own weekly records. This does not establish delivery or a zero SEO outcome.") }}</p> }
        <ul>@for (row of retained.rows; track row.id) {
          <li>{{ t("Record") }} {{ row.id }} · {{ t("completed report-creation week starting") }} {{ row.week_start }} (UTC) · {{ stateLabel(row.state) }}.
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
    form { display: grid; gap: 0.6rem; max-width: 36rem; }
    li { margin-block: 0.6rem; overflow-wrap: anywhere; }`,
})
export class ProjectSummaryPreference implements OnChanges, OnDestroy {
  @Input() organizationId = 0;
  @Input() projectId = 0;
  @Input() language: 'en' | 'tr' = 'en';
  uiLanguage() { return draftProductLanguage(this.language); }
  t(text: string) { return this.uiLanguage() === 'tr' ? summaryTurkish[text] ?? text : text; }
  readonly choice = signal<Frequency>('off');
  readonly savedFrequency = signal<Frequency>('off');
  readonly revision = signal<number | null>(null);
  readonly busy = signal(false);
  readonly error = signal('');
  readonly message = signal('');
  readonly deliveryState = signal<Preference['delivery_state'] | null>(null);
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
    this.choice.set('off'); this.savedFrequency.set('off'); this.revision.set(null);
    this.error.set(''); this.message.set('');
    this.deliveryState.set(null); this.clearHistory();
  }

  private clearHistory() {
    this.historyGeneration++; this.history.set(null); this.historyBusy.set(false); this.historyError.set(false);
  }

  edit(value: string) {
    if (this.busy() || (value !== 'off' && value !== 'weekly')) return;
    this.choice.set(value); this.error.set(''); this.message.set('');
    this.clearHistory();
  }

  async load() {
    const generation = ++this.generation, organization = this.organizationId, project = this.projectId;
    this.clear(); this.busy.set(true);
    try {
      if (![organization, project].every((id) => Number.isSafeInteger(id) && id > 0)) throw new Error();
      const result = await this.api.projectSummaryPreference(organization, project);
      if (generation !== this.generation) return;
      if (result.status !== 200 || result.body['project_id'] !== project
          || Object.keys(result.body).sort().join(',') !== 'preference,project_id'
          || !isPreference(result.body['preference'])) throw new Error();
      const preference = result.body['preference'];
      this.revision.set(preference.revision); this.savedFrequency.set(preference.frequency); this.choice.set(preference.frequency);
      this.deliveryState.set(preference.delivery_state);
    } catch {
      if (generation === this.generation) { this.clear(); this.error.set('Your current project preference is unavailable. Refresh before saving.'); }
    } finally { if (generation === this.generation) this.busy.set(false); }
  }

  async save(event: Event) {
    event.preventDefault();
    const revision = this.revision();
    if (this.busy() || revision === null) return;
    const generation = this.generation, project = this.projectId, frequency = this.choice();
    const expected = revision + (frequency !== this.savedFrequency() ? 1 : 0);
    this.clearHistory();
    this.busy.set(true); this.error.set(''); this.message.set('');
    try {
      const result = await this.api.saveProjectSummaryPreference(this.organizationId, project, frequency, revision);
      if (generation !== this.generation) return;
      if (result.status !== 200 || result.body['project_id'] !== project
          || Object.keys(result.body).sort().join(',') !== 'preference,project_id'
          || !isPreference(result.body['preference']) || result.body['preference'].frequency !== frequency
          || result.body['preference'].revision !== expected) throw new Error();
      this.revision.set(expected); this.savedFrequency.set(frequency);
      this.deliveryState.set(result.body['preference'].delivery_state);
      this.message.set('Preference saved. This save did not directly schedule or send a summary email.');
    } catch {
      if (generation === this.generation) {
        this.clear(); this.error.set('Save outcome unavailable. Refresh your saved preference before making another change; no automatic retry occurs.');
      }
    } finally { if (generation === this.generation) this.busy.set(false); }
  }

  stateLabel(state: Delivery['state']) {
    return this.t({ queued: 'Queued, not sent', sending: 'Sending durably committed; outcome pending',
      transport_accepted: 'Transport accepted', skipped: 'Skipped: current source or recipient changed',
      unknown: 'Unknown transport outcome; no replay' }[state]);
  }

  async inspectHistory() {
    if (this.busy() || this.revision() === null) return;
    this.clearHistory();
    const generation = this.historyGeneration, organization = this.organizationId, project = this.projectId,
      revision = this.revision();
    const current = () => generation === this.historyGeneration && organization === this.organizationId
      && project === this.projectId && revision === this.revision();
    this.historyBusy.set(true);
    try {
      const result = await this.api.projectSummaryDeliveries(organization, project);
      if (!current()) return;
      const history = result.status === 200 ? readHistory(result.body, project) : null;
      if (!history) throw new Error();
      this.history.set(structuredClone(history));
    } catch { if (current()) this.historyError.set(true); }
    finally { if (current()) this.historyBusy.set(false); }
  }
}

function isPreference(value: unknown): value is Preference {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const row = value as Record<string, unknown>;
  return Object.keys(row).sort().join(',') === 'channel,delivery_state,frequency,revision'
    && row['channel'] === 'email' && (row['delivery_state'] === 'rollout_off' || row['delivery_state'] === 'enabled_optional')
    && (row['frequency'] === 'off' || row['frequency'] === 'weekly')
    && Number.isSafeInteger(row['revision']) && Number(row['revision']) >= 0 && Number(row['revision']) < 2 ** 31
    && (Number(row['revision']) > 0 || row['frequency'] === 'off');
}

function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function readHistory(body: Record<string, unknown>, project: number): History | null {
  if (Object.keys(body).sort().join(',') !== 'has_more,method_version,project_id,rows,scope'
      || body['project_id'] !== project || body['method_version'] !== 'own-weekly-delivery-history-v1'
      || body['scope'] !== 'own_retained_transport_history_not_recipient_delivery_read_or_current_eligibility'
      || !Array.isArray(body['rows']) || body['rows'].length > 20 || typeof body['has_more'] !== 'boolean'
      || body['has_more'] && body['rows'].length !== 20) return null;
  const ids = new Set<number>(); let previousWeek = Infinity;
  for (const row of body['rows']) {
    if (!record(row) || Object.keys(row).sort().join(',') !== 'accepted_at,attempted_at,created_at,error_category,id,state,week_start'
        || !Number.isSafeInteger(row['id']) || Number(row['id']) < 1 || ids.has(Number(row['id']))
        || typeof row['error_category'] !== 'string') return null;
    const week = calendar(row['week_start']), created = microseconds(row['created_at']),
      attempted = microseconds(row['attempted_at']), accepted = microseconds(row['accepted_at']);
    if (week === null || new Date(week).getUTCDay() !== 1 || week >= previousWeek || created === null
        || row['attempted_at'] !== null && attempted === null || row['accepted_at'] !== null && accepted === null
        || attempted !== null && attempted < created || accepted !== null && (attempted === null || accepted < attempted)) return null;
    const state = row['state'], category = row['error_category'];
    if (state === 'queued' ? attempted !== null || accepted !== null || category !== ''
      : state === 'sending' ? attempted === null || accepted !== null || category !== ''
      : state === 'transport_accepted' ? attempted === null || accepted === null || category !== ''
      : state === 'skipped' ? attempted === null || accepted !== null || category !== 'current_source_or_recipient_changed'
      : state === 'unknown' ? attempted === null || accepted !== null || !['delivery_uncertain', 'worker_outcome_unknown'].includes(String(category))
      : true) return null;
    ids.add(Number(row['id'])); previousWeek = week;
  }
  return body as History;
}

const summaryTurkish: Readonly<Record<string, string>> = {
  "Your optional project summary preference": "İsteğe bağlı proje özeti tercihiniz",
  "This setting belongs only to you in this project. Saving a preference does not directly schedule or send mail.": "Bu ayar, bu projede yalnızca size aittir. Tercihi kaydetmek doğrudan e-posta planlamaz veya göndermez.",
  "Optional summaries use selected private reports from the previous completed UTC report-creation week, not proof of SEO changes that week. No older-week backlog or paid analysis is started to fill a summary. Access, verified primary email, suppression and entitlement are checked at delivery. This setting does not change required account, security or billing notices.": "İsteğe bağlı özetler, önceki tamamlanmış UTC rapor oluşturma haftasındaki seçili özel raporları kullanır; o haftaki SEO değişikliklerinin kanıtı değildir. Özeti doldurmak için daha eski haftaların birikmiş işleri veya ücretli analiz başlatılmaz. Teslimat sırasında erişim, doğrulanmış birincil e-posta, gönderim engelleme ve kullanım hakkı kontrol edilir. Bu ayar zorunlu hesap, güvenlik veya faturalandırma bildirimlerini değiştirmez.",
  "Checking your current summary preference.": "Güncel özet tercihiniz kontrol ediliyor.",
  "Saved email frequency:": "Kaydedilmiş e-posta sıklığı:",
  "Weekly delivery rollout is off. Saved weekly intent is retained; no optional weekly mail is sent while off.": "Haftalık teslimat etkinleştirilmemiş. Kaydedilmiş haftalık niyet korunur; kapalıyken isteğe bağlı haftalık e-posta gönderilmez.",
  "Optional weekly discovery is enabled by configuration. Only saved weekly intent with a current eligible report and recipient may send. This is not confirmation of live email readiness or your current eligibility.": "İsteğe bağlı haftalık keşif yapılandırmayla etkinleştirilmiş. Yalnızca güncel uygun rapor ve alıcıyla kaydedilmiş haftalık niyet gönderime uygun olabilir. Bu, canlı e-posta hazırlığının veya güncel uygunluğunuzun doğrulanması değildir.",
  "Your optional email frequency for this project": "Bu proje için isteğe bağlı e-posta sıklığınız",
  "Off (default)": "Kapalı (varsayılan)",
  "Weekly (optional intent)": "Haftalık (isteğe bağlı niyet)",
  "Save my preference": "Tercihimi kaydet",
  "Refresh my saved preference": "Kaydedilmiş tercihimi yenile",
  "Your retained weekly transport history": "Saklanmış haftalık iletim geçmişiniz",
  "Inspect only your own records in this project. History is not current eligibility, recipient delivery or reading, or an SEO outcome. Unknown sends are not replayed.": "Bu projede yalnızca kendi kayıtlarınızı inceleyin. Geçmiş, güncel uygunluk, alıcıya teslim veya okunma ya da SEO sonucu değildir. Sonucu bilinmeyen gönderimler tekrarlanmaz.",
  "Inspect / refresh my weekly history": "Haftalık geçmişimi incele / yenile",
  "Checking your retained weekly transport history.": "Saklanmış haftalık iletim geçmişiniz kontrol ediliyor.",
  "Your retained weekly transport history is unavailable. No send or retry was requested.": "Saklanmış haftalık iletim geçmişiniz kullanılamıyor. Gönderim veya yeniden deneme istenmedi.",
  "No retained own weekly records. This does not establish delivery or a zero SEO outcome.": "Size ait saklanmış haftalık kayıt yok. Bu, teslimatı veya sıfır SEO sonucunu kanıtlamaz.",
  "Record": "Kayıt",
  "completed report-creation week starting": "başlangıcı belirtilen tamamlanmış rapor oluşturma haftası",
  "Created": "Oluşturulma zamanı",
  "Attempt recorded": "Kaydedilmiş deneme zamanı",
  "Transport accepted": "İletim kabul edildi",
  "(UTC), not delivered or read.": "(UTC), teslim edildi veya okundu anlamına gelmez.",
  "Only the newest 20 retained own records are shown; older records exist.": "Yalnızca size ait saklanmış en yeni 20 kayıt gösteriliyor; daha eski kayıtlar var.",
  "Your current project preference is unavailable. Refresh before saving.": "Güncel proje tercihiniz kullanılamıyor. Kaydetmeden önce yenileyin.",
  "Preference saved. This save did not directly schedule or send a summary email.": "Tercih kaydedildi. Bu kayıt doğrudan özet e-postası planlamadı veya göndermedi.",
  "Save outcome unavailable. Refresh your saved preference before making another change; no automatic retry occurs.": "Kaydetme sonucu kullanılamıyor. Başka bir değişiklik yapmadan önce kaydedilmiş tercihinizi yenileyin; otomatik yeniden deneme yapılmaz.",
  "Queued, not sent": "Kuyrukta, gönderilmedi",
  "Sending durably committed; outcome pending": "Gönderim kalıcı olarak kaydedildi; sonuç bekleniyor",
  "Skipped: current source or recipient changed": "Atlandı: güncel kaynak veya alıcı değişti",
  "Unknown transport outcome; no replay": "İletim sonucu bilinmiyor; tekrar gönderilmez",
};
