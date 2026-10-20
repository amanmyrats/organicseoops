import { Component, Input, OnChanges, OnDestroy, signal, SimpleChanges } from '@angular/core';
import { draftProductLanguage } from '../product-language';
import { AccountApi } from '../account/account-api';
import { DailyDelivery, DailyHistory, readDailyTransportHistory } from './daily-transport-history';

type Frequency = 'off' | 'daily';
type Preference = { channel: 'email'; source_family: 'crux_material'; frequency: Frequency;
  revision: number; delivery_state: 'rollout_off' | 'enabled_optional' };

@Component({
  selector: 'app-project-crux-alert-preference',
  template: `
    <section [attr.lang]="uiLanguage()" aria-labelledby="crux-preference-title">
      <h2 id="crux-preference-title">{{ t("Your optional material CrUX alert intent") }}</h2>
      <p>{{ t("This setting belongs only to you in this project, independently of weekly summaries, operational alerts and optional analytics. It does not change required account, security or billing notices.") }}</p>
      <p>{{ t("Saving optional intent does not directly schedule or send mail, collect sources or run paid analysis. Daily intent is not daily sending or confirmation of your current eligibility or live email readiness. Optional discovery uses newest genuine observed sources collected in the previous completed UTC day, after your independent intent, with current verified primary email, project access, suppression, entitlement and related metric-period deduplication checks. Older days are not replayed.") }}</p>
      <p>{{ t("Material candidates require a worsening p75 grade and both at least 20% relative increase and an absolute increase of 500 ms LCP, 50 ms INP or 0.05 unitless CLS. These are product heuristics, not provider noise floors or statistical significance. Original weekly 28-day windows overlap; eligible-day and sample counts remain unknown. Candidates are not confirmed SEO regressions or causal outcomes.") }}</p>
      @if (busy()) { <p role="status">{{ t("Checking your own CrUX intent.") }}</p> }
      @if (error()) { <p role="alert">{{ t(error()) }}</p> }
      @if (saved(); as preference) {
        <p>{{ t("Saved CrUX email frequency:") }} <span lang="en">{{ preference.frequency }}</span>.</p>
        @if (preference.delivery_state === 'rollout_off') {
          <p>{{ t("CrUX delivery rollout is off. Stored daily intent remains; no optional CrUX mail is sent while off.") }}</p>
        } @else {
          <p>{{ t("Optional CrUX discovery is enabled by configuration. Only saved daily intent with eligible current sources and recipient may send. This is not confirmation of live email readiness or your current eligibility.") }}</p>
        }
        <form (submit)="save($event)">
          <label for="crux-alert-frequency">{{ t("Your optional material CrUX email frequency for this project") }}</label>
          <select id="crux-alert-frequency" name="frequency" [value]="choice()" [disabled]="busy()"
            (change)="edit($any($event.target).value)">
            <option value="off">{{ t("Off (default)") }}</option><option value="daily">{{ t("Daily (optional material-candidate intent)") }}</option>
          </select>
          <button type="submit" [disabled]="busy()">{{ t("Save my CrUX intent") }}</button>
        </form>
      }
      <button type="button" [disabled]="busy()" (click)="load()">{{ t("Refresh my saved CrUX intent") }}</button>
      @if (message()) { <p role="status">{{ t(message()) }}</p> }
      <h3>{{ t("Your retained CrUX transport history") }}</h3>
      <p>{{ t("Inspect only your own CrUX records in this project. History is not current eligibility, recipient delivery or reading, a confirmed regression or an SEO outcome. Unknown sends are not replayed.") }}</p>
      <button type="button" [disabled]="busy() || historyBusy() || !saved()" (click)="inspectHistory()">{{ t("Inspect / refresh my CrUX history") }}</button>
      @if (historyBusy()) { <p role="status">{{ t("Checking your retained CrUX transport history.") }}</p> }
      @if (historyError()) { <p role="alert">{{ t("Your retained CrUX transport history is unavailable. No send or retry was requested.") }}</p> }
      @if (history(); as retained) {
        @if (!retained.rows.length) { <p role="status">{{ t("No retained own CrUX records. This does not establish delivery or a zero SEO outcome.") }}</p> }
        <ul>@for (row of retained.rows; track row.id) {
          <li>{{ t("Record") }} {{ row.id }} · {{ t("completed collection-coverage day") }} {{ row.day_start }} {{ t("(UTC), not source-period occurrence time") }} · {{ stateLabel(row.state) }}.
            {{ t("Created") }} {{ row.created_at }} (UTC).
            @if (row.attempted_at) { {{ t("Attempt recorded") }} {{ row.attempted_at }} (UTC). }
            @if (row.accepted_at) { {{ t("Transport accepted") }} {{ row.accepted_at }} {{ t("(UTC), not delivered or read.") }} }
          </li>
        }</ul>
        @if (retained.has_more) { <p>{{ t("Only the newest 20 retained own CrUX records are shown; older records exist.") }}</p> }
      }
    </section>
  `,
  styles: `section { margin-block: 1.2rem; border-top: 1px solid #b9cfd5; }
    form { display: grid; gap: 0.6rem; max-width: 36rem; } p, label, li { overflow-wrap: anywhere; } li { margin-block: 0.6rem; }`,
})
export class ProjectCruxAlertPreference implements OnChanges, OnDestroy {
  @Input() organizationId = 0;
  @Input() projectId = 0;
  @Input() language: 'en' | 'tr' = 'en';
  uiLanguage() { return draftProductLanguage(this.language); }
  t(text: string) { return this.uiLanguage() === 'tr' ? cruxAlertTurkish[text] ?? text : text; }
  readonly choice = signal<Frequency>('off');
  readonly saved = signal<Preference | null>(null);
  readonly busy = signal(false);
  readonly error = signal('');
  readonly message = signal('');
  readonly history = signal<DailyHistory | null>(null);
  readonly historyBusy = signal(false);
  readonly historyError = signal(false);
  private generation = 0;
  private historyGeneration = 0;
  private loadedScope: { organization: number; project: number } | null = null;

  constructor(private readonly api: AccountApi) {}
  ngOnChanges(changes?: SimpleChanges) {
    if (!changes || changes['organizationId'] || changes['projectId']) void this.load();
  }
  ngOnDestroy() { this.generation++; this.clear(); this.busy.set(false); }

  private clear() {
    this.saved.set(null); this.choice.set('off'); this.loadedScope = null;
    this.error.set(''); this.message.set('');
    this.clearHistory();
  }

  private clearHistory() {
    this.historyGeneration++; this.history.set(null); this.historyBusy.set(false); this.historyError.set(false);
  }

  private hasLoadedScope() {
    if (this.loadedScope?.organization === this.organizationId && this.loadedScope.project === this.projectId) return true;
    this.generation++; this.clear(); this.busy.set(false);
    this.error.set('Choose an authorized project and refresh your own CrUX intent before saving.');
    return false;
  }

  edit(value: string) {
    if (this.busy() || !this.hasLoadedScope() || !this.saved() || value !== 'off' && value !== 'daily') return;
    this.choice.set(value); this.error.set(''); this.message.set('');
    this.clearHistory();
  }

  async load() {
    const generation = ++this.generation, organization = this.organizationId, project = this.projectId;
    this.clear(); this.busy.set(false);
    if (![organization, project].every(id => Number.isSafeInteger(id) && id > 0)) {
      this.error.set('Choose an authorized project before reading your CrUX intent.'); return;
    }
    const current = () => generation === this.generation && organization === this.organizationId && project === this.projectId;
    this.busy.set(true);
    try {
      const result = await this.api.projectCruxAlertPreference(organization, project);
      if (!current()) return;
      const preference = result.status === 200 ? readPreference(result.body, project) : null;
      if (!preference) throw new Error();
      this.saved.set(preference); this.choice.set(preference.frequency); this.loadedScope = { organization, project };
    } catch {
      if (current()) { this.clear(); this.error.set('Your own CrUX intent is unavailable. Refresh before saving.'); }
    } finally { if (current()) this.busy.set(false); }
  }

  async save(event: Event) {
    event.preventDefault();
    if (this.busy() || !this.hasLoadedScope()) return;
    const saved = this.saved(), frequency = this.choice();
    if (!saved) return;
    this.clearHistory();
    if (saved.revision >= 2 ** 31 - 1 || frequency !== 'off' && frequency !== 'daily') {
      this.error.set('Your current CrUX intent needs review before saving.'); return;
    }
    const generation = this.generation, organization = this.loadedScope!.organization, project = this.loadedScope!.project;
    const current = () => generation === this.generation && organization === this.organizationId && project === this.projectId;
    const expected = saved.revision + (frequency !== saved.frequency ? 1 : 0);
    this.busy.set(true); this.error.set(''); this.message.set('');
    try {
      const result = await this.api.saveProjectCruxAlertPreference(organization, project, frequency, saved.revision);
      if (!current()) return;
      const preference = result.status === 200 ? readPreference(result.body, project) : null;
      if (!preference || preference.frequency !== frequency || preference.revision !== expected) throw new Error();
      this.saved.set(preference);
      this.message.set('CrUX intent saved. This save did not directly schedule or send an optional digest.');
    } catch {
      if (current()) {
        this.clear(); this.error.set('Save outcome unavailable. Refresh your saved CrUX intent before another change; no automatic retry occurs.');
      }
    } finally { if (current()) this.busy.set(false); }
  }
  stateLabel(state: DailyDelivery['state']) {
    return this.t({ queued: 'Queued, not sent', sending: 'Sending durably committed; outcome pending',
      transport_accepted: 'Transport accepted', skipped: 'Skipped: current source or recipient changed',
      unknown: 'Unknown transport outcome; no replay' }[state]);
  }

  async inspectHistory() {
    if (this.busy() || !this.hasLoadedScope() || !this.saved()) return;
    this.clearHistory();
    const organization = this.loadedScope!.organization, project = this.loadedScope!.project;
    if (![organization, project].every(id => Number.isSafeInteger(id) && id > 0)) {
      this.historyError.set(true); return;
    }
    const generation = this.historyGeneration, revision = this.saved()!.revision;
    const current = () => generation === this.historyGeneration && organization === this.organizationId
      && project === this.projectId && revision === this.saved()?.revision;
    this.historyBusy.set(true);
    try {
      const result = await this.api.projectCruxAlertDeliveries(organization, project);
      if (!current()) return;
      const retained = result.status === 200 ? readDailyTransportHistory(result.body, project,
        'own-daily-crux-delivery-history-v1',
        'own_retained_crux_transport_history_not_recipient_delivery_read_regression_or_current_eligibility') : null;
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
  if (Object.keys(row).sort().join(',') !== 'channel,delivery_state,frequency,revision,source_family'
      || row['channel'] !== 'email' || row['source_family'] !== 'crux_material'
      || row['delivery_state'] !== 'rollout_off' && row['delivery_state'] !== 'enabled_optional'
      || row['frequency'] !== 'off' && row['frequency'] !== 'daily'
      || !Number.isSafeInteger(row['revision']) || Number(row['revision']) < 0 || Number(row['revision']) >= 2 ** 31
      || row['revision'] === 0 && row['frequency'] !== 'off') return null;
  return structuredClone(row) as Preference;
}

const cruxAlertTurkish: Readonly<Record<string, string>> = {
  "Your optional material CrUX alert intent": "İsteğe bağlı önemli CrUX uyarı niyetiniz",
  "This setting belongs only to you in this project, independently of weekly summaries, operational alerts and optional analytics. It does not change required account, security or billing notices.": "Bu ayar, haftalık özetlerden, operasyonel uyarılardan ve isteğe bağlı analizlerden bağımsız olarak bu projede yalnızca size aittir. Zorunlu hesap, güvenlik veya faturalandırma bildirimlerini değiştirmez.",
  "Saving optional intent does not directly schedule or send mail, collect sources or run paid analysis. Daily intent is not daily sending or confirmation of your current eligibility or live email readiness. Optional discovery uses newest genuine observed sources collected in the previous completed UTC day, after your independent intent, with current verified primary email, project access, suppression, entitlement and related metric-period deduplication checks. Older days are not replayed.": "İsteğe bağlı niyeti kaydetmek doğrudan e-posta planlamaz veya göndermez, kaynak toplamaz ya da ücretli analiz çalıştırmaz. Günlük niyet, günlük gönderim veya güncel uygunluğunuzun ya da canlı e-posta hazırlığının doğrulanması değildir. İsteğe bağlı keşif, bağımsız niyetinizden sonra önceki tamamlanmış UTC gününde toplanan en yeni gerçek gözlem kaynaklarını kullanır; güncel doğrulanmış birincil e-posta, proje erişimi, gönderim engeli, kullanım hakkı ve ilgili metrik-dönem tekrarlarını önleme kontrolleri uygulanır. Eski günler tekrarlanmaz.",
  "Material candidates require a worsening p75 grade and both at least 20% relative increase and an absolute increase of 500 ms LCP, 50 ms INP or 0.05 unitless CLS. These are product heuristics, not provider noise floors or statistical significance. Original weekly 28-day windows overlap; eligible-day and sample counts remain unknown. Candidates are not confirmed SEO regressions or causal outcomes.": "Önemli değişiklik adayları için p75 sınıfının kötüleşmesi, en az %20 göreli artış ve ayrıca LCP için 500 ms, INP için 50 ms veya CLS için birimsiz 0.05 mutlak artış gerekir. Bunlar ürünün pratik eşikleridir; sağlayıcının gürültü eşikleri veya istatistiksel anlamlılık değildir. Özgün haftalık 28 günlük pencereler örtüşür; uygun gün ve örnek sayıları bilinmiyor. Adaylar, doğrulanmış SEO gerilemeleri veya nedensel sonuçlar değildir.",
  "Checking your own CrUX intent.": "Kendi CrUX niyetiniz kontrol ediliyor.",
  "Saved CrUX email frequency:": "Kaydedilmiş CrUX e-posta sıklığı:",
  "CrUX delivery rollout is off. Stored daily intent remains; no optional CrUX mail is sent while off.": "CrUX teslimatı etkinleştirilmemiş. Kaydedilmiş günlük niyet korunur; kapalıyken isteğe bağlı CrUX e-postası gönderilmez.",
  "Optional CrUX discovery is enabled by configuration. Only saved daily intent with eligible current sources and recipient may send. This is not confirmation of live email readiness or your current eligibility.": "İsteğe bağlı CrUX keşfi yapılandırmayla etkinleştirilmiş. Yalnızca uygun güncel kaynaklar ve alıcıyla kaydedilmiş günlük niyet gönderime uygun olabilir. Bu, canlı e-posta hazırlığının veya güncel uygunluğunuzun doğrulanması değildir.",
  "Your optional material CrUX email frequency for this project": "Bu proje için isteğe bağlı önemli CrUX e-posta sıklığınız",
  "Off (default)": "Kapalı (varsayılan)",
  "Daily (optional material-candidate intent)": "Günlük (isteğe bağlı önemli değişiklik adayı niyeti)",
  "Save my CrUX intent": "CrUX niyetimi kaydet",
  "Refresh my saved CrUX intent": "Kaydedilmiş CrUX niyetimi yenile",
  "Your retained CrUX transport history": "Saklanmış CrUX iletim geçmişiniz",
  "Inspect only your own CrUX records in this project. History is not current eligibility, recipient delivery or reading, a confirmed regression or an SEO outcome. Unknown sends are not replayed.": "Bu projede yalnızca kendi CrUX kayıtlarınızı inceleyin. Geçmiş, güncel uygunluk, alıcıya teslim veya okunma, doğrulanmış gerileme ya da SEO sonucu değildir. Sonucu bilinmeyen gönderimler tekrarlanmaz.",
  "Inspect / refresh my CrUX history": "CrUX geçmişimi incele / yenile",
  "Checking your retained CrUX transport history.": "Saklanmış CrUX iletim geçmişiniz kontrol ediliyor.",
  "Your retained CrUX transport history is unavailable. No send or retry was requested.": "Saklanmış CrUX iletim geçmişiniz kullanılamıyor. Gönderim veya yeniden deneme istenmedi.",
  "No retained own CrUX records. This does not establish delivery or a zero SEO outcome.": "Size ait saklanmış CrUX kayıtları yok. Bu, teslimatı veya sıfır SEO sonucunu kanıtlamaz.",
  "Record": "Kayıt",
  "completed collection-coverage day": "tamamlanmış toplama kapsamı günü",
  "(UTC), not source-period occurrence time": "(UTC), kaynak döneminin gerçekleşme zamanı değildir",
  "Created": "Oluşturulma",
  "Attempt recorded": "Deneme kaydı",
  "Transport accepted": "İletim kabul edildi",
  "(UTC), not delivered or read.": "(UTC), teslim edildi veya okundu anlamına gelmez.",
  "Only the newest 20 retained own CrUX records are shown; older records exist.": "Yalnızca size ait saklanmış en yeni 20 CrUX kaydı gösteriliyor; daha eski kayıtlar var.",
  "Choose an authorized project and refresh your own CrUX intent before saving.": "Kaydetmeden önce yetkili olduğunuz bir proje seçin ve kendi CrUX niyetinizi yenileyin.",
  "Choose an authorized project before reading your CrUX intent.": "CrUX niyetinizi okumadan önce yetkili olduğunuz bir proje seçin.",
  "Your own CrUX intent is unavailable. Refresh before saving.": "Kendi CrUX niyetiniz kullanılamıyor. Kaydetmeden önce yenileyin.",
  "Your current CrUX intent needs review before saving.": "Kaydetmeden önce güncel CrUX niyetinizin incelenmesi gerekiyor.",
  "CrUX intent saved. This save did not directly schedule or send an optional digest.": "CrUX niyeti kaydedildi. Bu kayıt doğrudan isteğe bağlı özet planlamadı veya göndermedi.",
  "Save outcome unavailable. Refresh your saved CrUX intent before another change; no automatic retry occurs.": "Kaydetme sonucu kullanılamıyor. Başka bir değişiklik yapmadan önce kaydedilmiş CrUX niyetinizi yenileyin; otomatik yeniden deneme yapılmaz.",
  "Queued, not sent": "Kuyrukta, gönderilmedi",
  "Sending durably committed; outcome pending": "Gönderim kalıcı olarak kaydedildi; sonuç bekleniyor",
  "Skipped: current source or recipient changed": "Atlandı: güncel kaynak veya alıcı değişti",
  "Unknown transport outcome; no replay": "İletim sonucu bilinmiyor; tekrar gönderilmez"
};
