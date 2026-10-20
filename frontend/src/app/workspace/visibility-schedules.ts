import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, OnInit, computed, effect, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi } from '../account/account-api';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';

type Sample = { prompt_set_id: number; prompt_key: string; model_id: number; account_id: number;
  max_output_tokens: number; max_cost_usd: string; acknowledge_api_limits: boolean };
type Policy = { method: string; interval_minutes: number; max_occurrences: number; lifetime_days: number;
  total_max_cost_usd: string; acknowledge_repeat_data_use: boolean };
type Schedule = { id: number; project_id: number; request_key: string; enabled: boolean; sample: Sample; policy: Policy;
  selection: { model_identifier: string; visibility: { revision: number; prompt: { text: string } } };
  expires_at: string; next_run_at: string | null; last_run_at: string | null; queued_occurrences: number;
  skipped_occurrences: number; attempted_units: number; blocked_reason: string; last_error_category: string; job_ids: number[] };
type Set = { id: number; project_id: number; label: string; revision: number; source_current: boolean;
  prompts: { key: string; kind: string; text: string }[]; policy: { max_output_tokens: number; max_cost_usd: string } };
type Model = { id: number; provider_id: number; name: string; identifier: string };
type Account = { id: number; provider_id: number; label: string; source: string };

const visibilitySchedulesTurkish: Record<string, string> = {
  "Private opt-in API-text repeats": "İsteğe bağlı özel API metni tekrarları",
  "Project evidence": "Proje kanıtları",
  "Manual samples and exact answers": "Manuel örnekler ve tam yanıtlar",
  "Human prompt methodology": "İnsan istemi metodolojisi",
  "Native OpenAI Responses API text only, not consumer ChatGPT, global visibility or visits. Exact human prompt is unchanged; no tools, measured citations, device/geolocation controls or guaranteed language. Additional observation surfaces remain unavailable.": "Yerel OpenAI Responses API yalnızca metin; tüketici ChatGPT, küresel görünürlük veya ziyaretler değildir. Tam insan istemi değiştirilmez; araç, ölçülmüş atıf, cihaz/coğrafi konum kontrolleri veya garantili dil yoktur. Ek gözlem yüzeyleri kullanılamaz kalır.",
  "Each schedule starts paused. Separate explicit owner/admin enable authorizes one request/unit per occurrence, daily-to-weekly. At most30 queued occurrences and30 days from creation; canceled slots consume allowance, pause/resume never renews it. Missed slots collapse; manual and scheduled attempts share a24-hour cooldown. Source/model/key/role/entitlement loss, expiry, failure, partial or unknown outcomes pause repeats. No automatic retry, fallback or uncertain replay.": "Her zamanlama duraklatılmış başlar. Sahibin/yöneticinin ayrı, açık etkinleştirmesi günlükten haftalığa her oluşumda bir istek/birime izin verir. En fazla30 kuyruğa alınmış oluşum ve oluşturmadan itibaren30 gün; iptal edilen aralıklar hakkı tüketir, duraklatma/devam ettirme hakkı yenilemez. Kaçırılmış aralıklar birleştirilir; manuel ve zamanlanmış denemeler24saatlik bekleme süresini paylaşır. Kaynak/model/anahtar/rol/hak kaybı, sona erme, başarısızlık, kısmi veya bilinmeyen sonuçlar tekrarları duraklatır. Otomatik yeniden deneme, yedek seçenek veya belirsiz yeniden oynatma yoktur.",
  "Per-request and total USD ceilings are estimates, not guaranteed invoice charges. Private prompts/answers follow organization export/retention/deletion and up to35-day backup expiry after active deletion. store:false is not Zero Data Retention: provider abuse monitoring can retain content up to30 days with exceptions, and prompt caches up to24 hours. Avoid secrets/personal data/customer exports.": "İstek başına ve toplam USD üst sınırları tahminlerdir, garantili fatura ücretleri değildir. Özel istemler/yanıtlar kuruluşun dışa aktarım/saklama/silme ve aktif silmeden sonra en fazla35günlük yedek sona erme politikasına tabidir. store:false Sıfır Veri Saklama değildir: sağlayıcının kötüye kullanım izlemesi içeriği istisnalarla en fazla30 gün, istem önbellekleri en fazla24 saat saklayabilir. Sırlardan/kişisel verilerden/müşteri dışa aktarımlarından kaçının.",
  "Provider data controls": "Sağlayıcı veri kontrolleri",
  ". Real provider/terms/hosted readiness remains unverified.": ". Gerçek sağlayıcı/koşullar/barındırılan ortam hazırlığı henüz doğrulanmamıştır.",
  "Loading current repeat authorizations and choices.": "Güncel tekrar yetkilendirmeleri ve seçenekleri yükleniyor.",
  "Decision outcome uncertain. Commands are frozen; check the exact request key/current state without replay.": "Karar sonucu belirsiz. Komutlar dondurulmuştur; yeniden oynatmadan tam istek anahtarını/güncel durumu kontrol edin.",
  "Reconcile uncertain decision (read only)": "Belirsiz kararı uzlaştırın (salt okunur)",
  "Active project": "Aktif proje",
  "(organization": "(kuruluş",
  ", project": ", proje",
  "New fixed repeat authorization (saved paused)": "Yeni sabit tekrar yetkilendirmesi (duraklatılmış kaydedilir)",
  "Exact-current reviewed set": "Tam güncel incelenmiş küme",
  "Choose methodology": "Metodolojiyi seçin",
  "· revision": "· revizyon",
  "One exact prompt": "Tek tam istem",
  "Choose prompt": "İstemi seçin",
  "Explicit native standard model (no default)": "Açıkça seçilmiş yerel standart model (varsayılan yok)",
  "Choose model": "Model seçin",
  "Matching account": "Eşleşen hesap",
  "Choose account": "Hesap seçin",
  "Per-request output tokens (reviewed ceiling": "İstek başına çıktı tokenleri (incelenmiş üst sınır",
  "Per-request estimated USD ceiling (reviewed": "İstek başına tahmini USD üst sınırı (incelenmiş",
  "Interval in minutes (1440–10080)": "Dakika cinsinden aralık (1440–10080)",
  "Maximum queued occurrences (1–30, no refund for canceled slots)": "Azami kuyruğa alınmış oluşum (1–30, iptal edilen aralıklar için iade yok)",
  "Fixed lifetime in days from creation (1–30; must fit a future slot)": "Oluşturmadan itibaren gün cinsinden sabit ömür (1–30; gelecekteki bir aralığı kapsamalı)",
  "Total estimated USD ceiling (at most100; covers per-request ceiling × all allowed occurrences)": "Toplam tahmini USD üst sınırı (en fazla100; istek başına üst sınır × izin verilen tüm oluşumları kapsar)",
  "I reviewed the exact prompt/selection, repeat costs, fixed allowance/lifetime and provider/private data-use limits.": "Tam istemi/seçimi, tekrar maliyetlerini, sabit hakkı/ömrü ve sağlayıcı/özel veri kullanım sınırlarını inceledim.",
  "Save paused repeat authorization (no request)": "Duraklatılmış tekrar yetkilendirmesini kaydedin (istek yok)",
  "New authorizations require current owner/admin role, current methodology and configured native model/account. Retained history remains readable.": "Yeni yetkilendirmeler güncel sahip/yönetici rolü, güncel metodoloji ve yapılandırılmış yerel model/hesap gerektirir. Saklanan geçmiş okunabilir kalır.",
  "Repeat authorizations": "Tekrar yetkilendirmeleri",
  "Repeat": "Tekrar",
  "· prompt": "· istem",
  ", revision": ", revizyon",
  "· account": "· hesap",
  "Interval": "Aralık",
  "min · queued": "dk · kuyruğa alınan",
  "· attempted units": "· denenen birimler",
  "· skipped": "· atlanan",
  ". Per-request estimated USD": ". İstek başına tahmini USD",
  "· total ceiling": "· toplam üst sınır",
  "· expires": "· sona erme",
  "Next": "Sonraki",
  "· last": "· son",
  "· issue": "· sorun",
  "Pause repeat": "Tekrarı duraklatın:",
  "Explicit enable repeat": "Tekrarı açıkça etkinleştirin:",
  "Authorize future repeat costs/data use within the unchanged deadline/allowance. This does not replay an old attempt.": "Değişmeyen son tarih/hak içinde gelecekteki tekrar maliyetlerine/veri kullanımına izin verin. Bu, eski bir denemeyi yeniden oynatmaz.",
  "Enable next future interval": "Sonraki gelecek aralığı etkinleştirin",
  "Inspect authenticated occurrence": "Kimliği doğrulanmış oluşumu inceleyin:",
  "No repeat authorization recorded.": "Kaydedilmiş tekrar yetkilendirmesi yok.",
  "Load older repeat history": "Daha eski tekrar geçmişini yükleyin",
  "Refresh current role/choices/history (read only)": "Güncel rolü/seçenekleri/geçmişi yenileyin (salt okunur)",
  "enabled": "etkin",
  "paused": "duraklatılmış",
  "not enabled": "etkinleştirilmemiş",
  "no occurrence": "oluşum yok",
  "none recorded": "kaydedilmiş yok",
  "Current repeat choices/history or project role unavailable.": "Güncel tekrar seçenekleri/geçmişi veya proje rolü kullanılamıyor.",
  "Exact repeat state confirmed. No provider call or old occurrence replay was requested.": "Tam tekrar durumu doğrulandı. Sağlayıcı çağrısı veya eski oluşumun yeniden oynatılması istenmedi.",
  "Repeat decision denied. Refresh current role/source/model/key/allowance/lifetime before a new decision.": "Tekrar kararı reddedildi. Yeni bir karardan önce güncel rolü/kaynağı/modeli/anahtarı/hakkı/ömrü yenileyin.",
  "Exact decision still unconfirmed or state changed. No command was replayed.": "Tam karar hâlâ doğrulanmadı veya durum değişti. Komut yeniden oynatılmadı.",
  "Older repeat history unavailable.": "Daha eski tekrar geçmişi kullanılamıyor.",
  "Unreviewed Turkish bounded-repeat interface draft in local development. Human prompts and frozen selection retain their original language; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe sınırlı tekrar arayüzü taslağı. İnsan istemleri ve dondurulmuş seçim özgün dillerini korur; iki dilli onay bekleniyor."
};

@Component({
  selector: 'app-visibility-schedules', imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="repeat-title">
      <h1 id="repeat-title">{{ t("Private opt-in API-text repeats") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish bounded-repeat interface draft in local development. Human prompts and frozen selection retain their original language; bilingual approval is pending.") }}</p> }
      <p><a [routerLink]="['/app/dashboard', organizationId, projectId]">{{ t("Project evidence") }}</a> ·
        <a [routerLink]="['/app/visibility-samples', organizationId, projectId]">{{ t("Manual samples and exact answers") }}</a> ·
        <a [routerLink]="['/app/visibility', organizationId, projectId]">{{ t("Human prompt methodology") }}</a></p>
      <p>{{ t("Native OpenAI Responses API text only, not consumer ChatGPT, global visibility or visits. Exact human prompt is unchanged; no tools, measured citations, device/geolocation controls or guaranteed language. Additional observation surfaces remain unavailable.") }}</p>
      <p>{{ t("Each schedule starts paused. Separate explicit owner/admin enable authorizes one request/unit per occurrence, daily-to-weekly. At most30 queued occurrences and30 days from creation; canceled slots consume allowance, pause/resume never renews it. Missed slots collapse; manual and scheduled attempts share a24-hour cooldown. Source/model/key/role/entitlement loss, expiry, failure, partial or unknown outcomes pause repeats. No automatic retry, fallback or uncertain replay.") }}</p>
      <p>{{ t("Per-request and total USD ceilings are estimates, not guaranteed invoice charges. Private prompts/answers follow organization export/retention/deletion and up to35-day backup expiry after active deletion. store:false is not Zero Data Retention: provider abuse monitoring can retain content up to30 days with exceptions, and prompt caches up to24 hours. Avoid secrets/personal data/customer exports.") }}
        <a href="https://developers.openai.com/api/docs/guides/your-data" target="_blank" rel="noopener noreferrer">{{ t("Provider data controls") }}</a>{{ t(". Real provider/terms/hosted readiness remains unverified.") }}</p>
      @if (loading()) { <p role="status">{{ t("Loading current repeat authorizations and choices.") }}</p> }
      @if (error()) { <p role="alert" [attr.lang]="t(error()) === error() ? 'en' : uiLanguage()">{{ t(error()) }}</p> }
      @if (message()) { <p role="status">{{ t(message()) }}</p> }
      @if (uncertain()) { <p role="alert">{{ t("Decision outcome uncertain. Commands are frozen; check the exact request key/current state without replay.") }}</p>
        <button type="button" [disabled]="busy()" (click)="reconcile()">{{ t("Reconcile uncertain decision (read only)") }}</button> }
      @if (ready()) {
        <p>{{ t("Active project") }} <span lang="">{{ name() }}</span> {{ t("(organization") }} <span lang="en">{{ organizationId }}</span>{{ t(", project") }} <span lang="en">{{ projectId }}</span>).</p>
        @if (canManage() && sets().length && models().length && accounts().length) {
          <form class="repeat-create" (submit)="create($event)">
            <fieldset [disabled]="busy() || uncertain()"><legend>{{ t("New fixed repeat authorization (saved paused)") }}</legend>
              <label for="repeat-set">{{ t("Exact-current reviewed set") }}</label><select id="repeat-set" name="prompt_set_id" required (change)="setId.set(+$any($event.target).value)">
                <option value="">{{ t("Choose methodology") }}</option>@for (row of sets(); track row.id) { <option lang="" [value]="row.id">{{ row.label }} {{ t("· revision") }} {{ row.revision }}</option> }
              </select>
              <label for="repeat-prompt">{{ t("One exact prompt") }}</label><select id="repeat-prompt" name="prompt_key" required>
                <option value="">{{ t("Choose prompt") }}</option>@for (prompt of selectedSet()?.prompts || []; track prompt.key) { <option lang="" [value]="prompt.key">{{ prompt.key }} · {{ prompt.kind }}: {{ prompt.text }}</option> }
              </select>
              <label for="repeat-model">{{ t("Explicit native standard model (no default)") }}</label><select id="repeat-model" name="model_id" required (change)="modelId.set(+$any($event.target).value)">
                <option value="">{{ t("Choose model") }}</option>@for (row of models(); track row.id) { <option lang="" [value]="row.id">{{ row.name }} · {{ row.identifier }}</option> }
              </select>
              <label for="repeat-account">{{ t("Matching account") }}</label><select id="repeat-account" name="account_id" required>
                <option value="">{{ t("Choose account") }}</option>@for (row of matchingAccounts(); track row.id) { <option lang="" [value]="row.id">{{ row.label }} ({{ row.source }})</option> }
              </select>
              <label for="repeat-tokens">{{ t("Per-request output tokens (reviewed ceiling") }} <span lang="en">{{ selectedSet()?.policy?.max_output_tokens }}</span>)</label>
              <input id="repeat-tokens" name="max_output_tokens" type="number" min="1" [max]="selectedSet()?.policy?.max_output_tokens || 256" step="1" required />
              <label for="repeat-cost">{{ t("Per-request estimated USD ceiling (reviewed") }} <span lang="en">{{ selectedSet()?.policy?.max_cost_usd }}</span>)</label>
              <input id="repeat-cost" name="max_cost_usd" inputmode="decimal" maxlength="10" required />
              <label for="repeat-interval">{{ t("Interval in minutes (1440–10080)") }}</label><input id="repeat-interval" name="interval_minutes" type="number" min="1440" max="10080" step="1" required />
              <label for="repeat-count">{{ t("Maximum queued occurrences (1–30, no refund for canceled slots)") }}</label><input id="repeat-count" name="max_occurrences" type="number" min="1" max="30" step="1" required />
              <label for="repeat-lifetime">{{ t("Fixed lifetime in days from creation (1–30; must fit a future slot)") }}</label><input id="repeat-lifetime" name="lifetime_days" type="number" min="1" max="30" step="1" required />
              <label for="repeat-total">{{ t("Total estimated USD ceiling (at most100; covers per-request ceiling × all allowed occurrences)") }}</label><input id="repeat-total" name="total_max_cost_usd" inputmode="decimal" maxlength="10" required />
              <label><input name="acknowledge" type="checkbox" required /> {{ t("I reviewed the exact prompt/selection, repeat costs, fixed allowance/lifetime and provider/private data-use limits.") }}</label>
              <button type="submit">{{ t("Save paused repeat authorization (no request)") }}</button>
            </fieldset>
          </form>
        } @else { <p>{{ t("New authorizations require current owner/admin role, current methodology and configured native model/account. Retained history remains readable.") }}</p> }
        <h2>{{ t("Repeat authorizations") }}</h2>
        <ul>@for (row of schedules(); track row.id) {
          <li><h3>{{ t("Repeat") }} <span lang="en">{{ row.id }}</span> — {{ row.enabled ? t("enabled") : t("paused") }}</h3>
            <p><span lang="en">{{ row.policy.method }}</span> {{ t("· prompt") }} <span lang="en">{{ row.sample.prompt_key }}</span>{{ t(", revision") }} <span lang="en">{{ row.selection.visibility.revision }}</span> · <span lang="en">{{ row.selection.model_identifier }}</span> {{ t("· account") }} <span lang="en">{{ row.sample.account_id }}</span>.</p>
            <pre><span lang="">{{ row.selection.visibility.prompt.text }}</span></pre>
            <p>{{ t("Interval") }} <span lang="en">{{ row.policy.interval_minutes }}</span> {{ t("min · queued") }} <span lang="en">{{ row.queued_occurrences }}</span>/<span lang="en">{{ row.policy.max_occurrences }}</span> {{ t("· attempted units") }} <span lang="en">{{ row.attempted_units }}</span> {{ t("· skipped") }} <span lang="en">{{ row.skipped_occurrences }}</span>{{ t(". Per-request estimated USD") }} <span lang="en">{{ row.sample.max_cost_usd }}</span> {{ t("· total ceiling") }} <span lang="en">{{ row.policy.total_max_cost_usd }}</span> {{ t("· expires") }} <span lang="en">{{ row.expires_at }}</span>.</p>
            <p>{{ t("Next") }} <span [attr.lang]="row.next_run_at ? 'en' : uiLanguage()">{{ row.next_run_at || t("not enabled") }}</span> {{ t("· last") }} <span [attr.lang]="row.last_run_at ? 'en' : uiLanguage()">{{ row.last_run_at || t("no occurrence") }}</span> {{ t("· issue") }} <span [attr.lang]="row.last_error_category || row.blocked_reason ? 'en' : uiLanguage()">{{ row.last_error_category || row.blocked_reason || t("none recorded") }}</span>.</p>
            @if (canManage()) {
              @if (row.enabled) { <button type="button" [disabled]="busy() || uncertain()" (click)="change(row, false)">{{ t("Pause repeat") }} <span lang="en">{{ row.id }}</span></button> }
              @else { <form (submit)="enable($event, row)"><fieldset [disabled]="busy() || uncertain() || !!row.blocked_reason"><legend>{{ t("Explicit enable repeat") }} <span lang="en">{{ row.id }}</span></legend>
                <label><input type="checkbox" name="acknowledge" required /> {{ t("Authorize future repeat costs/data use within the unchanged deadline/allowance. This does not replay an old attempt.") }}</label>
                <button type="submit">{{ t("Enable next future interval") }}</button></fieldset></form> }
            }
            <ul>@for (id of row.job_ids; track id) { <li><a [routerLink]="['/app/visibility-samples', organizationId, projectId, id]">{{ t("Inspect authenticated occurrence") }} <span lang="en">{{ id }}</span></a></li> }</ul>
          </li>
        } @empty { <li>{{ t("No repeat authorization recorded.") }}</li> }</ul>
        @if (hasMore()) { <button type="button" [disabled]="busy() || uncertain()" (click)="more()">{{ t("Load older repeat history") }}</button> }
      }
      <button type="button" [disabled]="busy()" (click)="load()">{{ t("Refresh current role/choices/history (read only)") }}</button>
    </section>`,
  styles: `label { display:block; margin-block:.6rem .2rem } input:not([type=checkbox]),select { width:min(100%,42rem); max-width:100% } fieldset { min-width:0 } pre { white-space:pre-wrap } section,li { overflow-wrap:anywhere } button { margin-block:.6rem }`,
})
export class VisibilitySchedules implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  t(text: string) { return this.uiLanguage() === 'tr' ? visibilitySchedulesTurkish[text] ?? text : text; }
  organizationId = 0; projectId = 0; private generation = 0; private cursor: number | null = null;
  readonly loading = signal(true); readonly ready = signal(false); readonly busy = signal(false); readonly error = signal(''); readonly message = signal('');
  readonly canManage = signal(false); readonly name = signal(''); readonly sets = signal<Set[]>([]);
  readonly models = signal<Model[]>([]); readonly accounts = signal<Account[]>([]); readonly setId = signal(0); readonly modelId = signal(0);
  readonly schedules = signal<Schedule[]>([]); readonly hasMore = signal(false); readonly uncertain = signal(false);
  private pending: { id: number; body: Record<string, unknown>; original: Schedule | null } | null = null;
  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi, private readonly destroy: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t('Private opt-in API-text repeats')} — OrganicSEOOps`));
  }
  ngOnInit() { void this.loadProductLanguage(); this.route.paramMap.pipe(takeUntilDestroyed(this.destroy)).subscribe((params) => {
    this.organizationId = Number(params.get('organizationId')); this.projectId = Number(params.get('projectId'));
    this.pending = null; this.uncertain.set(false); void this.load();
  }); this.destroy.onDestroy(() => ++this.generation); }
  private async loadProductLanguage() {
    try {
      const result = await this.api.productLanguage();
      if (!this.destroy.destroyed && result.status === 200 && isProductLanguageResult(result.body)) {
        this.productLanguage.set(result.body['language']);
      }
    } catch { /* Keep English when the private preference is unavailable. */ }
  }
  selectedSet() { return this.sets().find((row) => row.id === this.setId()); }
  matchingAccounts() { return this.accounts().filter((row) => row.provider_id === this.models().find((model) => model.id === this.modelId())?.provider_id); }
  private valid(row: Schedule) { return row && Number.isSafeInteger(row.id) && row.project_id === this.projectId
    && row.policy?.method === 'visibility-repeat-schedule-v1' && typeof row.selection?.visibility?.prompt?.text === 'string'
    && typeof row.enabled === 'boolean' && Array.isArray(row.job_ids); }
  async load() {
    const generation = ++this.generation; this.loading.set(true); this.ready.set(false); this.busy.set(false); this.error.set('');
    this.canManage.set(false); this.name.set(''); this.sets.set([]); this.models.set([]); this.accounts.set([]); this.schedules.set([]);
    this.setId.set(0); this.modelId.set(0); this.cursor = null; this.hasMore.set(false);
    try {
      const context = await this.api.projectOnboarding(this.organizationId, this.projectId);
      if (generation !== this.generation) return;
      const project = context.body['project'] as Record<string, unknown>;
      if (context.status !== 200 || project?.['id'] !== this.projectId || project['organization_id'] !== this.organizationId
          || typeof project['role'] !== 'string' || !['owner', 'admin', 'member', 'viewer'].includes(project['role'])) throw new Error();
      const choices = await this.api.visibilitySamples(this.organizationId, this.projectId);
      const result = await this.api.visibilitySchedules(this.organizationId, this.projectId);
      if (generation !== this.generation) return;
      if (choices.status !== 200 || choices.body['project_id'] !== this.projectId || result.status !== 200
        || result.body['project_id'] !== this.projectId || result.body['method'] !== 'visibility-repeat-schedule-v1'
        || !['prompt_sets', 'models', 'accounts'].every((key) => Array.isArray(choices.body[key]))
        || !Array.isArray(result.body['schedules']) || !(result.body['schedules'] as Schedule[]).every((row) => this.valid(row))
        || (choices.body['prompt_sets'] as Set[]).some((row) => row.project_id !== this.projectId)) throw new Error();
      this.name.set(String(project['name'])); this.canManage.set(['owner', 'admin'].includes(project['role']));
      this.sets.set((choices.body['prompt_sets'] as Set[]).filter((row) => row.source_current));
      this.models.set(choices.body['models'] as Model[]); this.accounts.set(choices.body['accounts'] as Account[]);
      this.schedules.set(result.body['schedules'] as Schedule[]); this.cursor = result.body['next_before_id'] as number | null;
      this.hasMore.set(result.body['has_more'] === true); this.ready.set(true);
    } catch { if (generation === this.generation) this.error.set('Current repeat choices/history or project role unavailable.'); }
    finally { if (generation === this.generation) this.loading.set(false); }
  }
  async create(event: SubmitEvent) {
    event.preventDefault(); const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || this.busy() || this.uncertain() || !this.canManage()) return;
    const fields = new FormData(form); const sample: Sample = { prompt_set_id: this.setId(), prompt_key: String(fields.get('prompt_key')),
      model_id: this.modelId(), account_id: Number(fields.get('account_id')), max_output_tokens: Number(fields.get('max_output_tokens')),
      max_cost_usd: String(fields.get('max_cost_usd')), acknowledge_api_limits: true };
    if (!this.selectedSet()?.prompts.some((row) => row.key === sample.prompt_key) || !this.matchingAccounts().some((row) => row.id === sample.account_id)
      || fields.get('acknowledge') !== 'on') return;
    const body = { sample, interval_minutes: Number(fields.get('interval_minutes')), max_occurrences: Number(fields.get('max_occurrences')),
      lifetime_days: Number(fields.get('lifetime_days')), total_max_cost_usd: String(fields.get('total_max_cost_usd')),
      acknowledge_repeat_data_use: true, idempotency_key: crypto.randomUUID() };
    await this.command({ id: 0, body, original: null });
  }
  async enable(event: SubmitEvent, row: Schedule) {
    event.preventDefault(); const form = event.currentTarget as HTMLFormElement;
    if (form.reportValidity() && new FormData(form).get('acknowledge') === 'on') await this.change(row, true);
  }
  async change(row: Schedule, enabled: boolean) {
    if (!this.valid(row) || enabled && row.blocked_reason) return;
    await this.command({ id: row.id, body: { enabled, acknowledge_repeat_data_use: enabled }, original: row });
  }
  private matches(row: Schedule, pending: NonNullable<VisibilitySchedules['pending']>) {
    if (!this.valid(row)) return false;
    if (pending.original) return row.id === pending.id && row.enabled === pending.body['enabled']
      && JSON.stringify(row.sample) === JSON.stringify(pending.original.sample) && JSON.stringify(row.policy) === JSON.stringify(pending.original.policy)
      && row.expires_at === pending.original.expires_at;
    const sample = pending.body['sample'] as Sample;
    return row.request_key === pending.body['idempotency_key'] && !row.enabled
      && Object.entries(sample).every(([key, value]) => row.sample[key as keyof Sample] === value)
      && ['interval_minutes', 'max_occurrences', 'lifetime_days'].every((key) => row.policy[key as keyof Policy] === pending.body[key])
      && Number(row.policy.total_max_cost_usd) === Number(pending.body['total_max_cost_usd']);
  }
  private accept(row: Schedule) { this.schedules.update((rows) => [row, ...rows.filter((item) => item.id !== row.id)]);
    this.pending = null; this.uncertain.set(false); this.message.set('Exact repeat state confirmed. No provider call or old occurrence replay was requested.'); }
  private async command(pending: NonNullable<VisibilitySchedules['pending']>) {
    if (this.busy() || this.uncertain() || !this.canManage() || !this.ready()) return;
    this.pending = pending; this.busy.set(true); this.error.set(''); const generation = this.generation;
    try {
      const response = await this.api.visibilitySchedules(this.organizationId, this.projectId, pending.id, pending.body);
      if (generation !== this.generation) return;
      if (response.status >= 400 && response.status < 500) { this.pending = null; this.error.set('Repeat decision denied. Refresh current role/source/model/key/allowance/lifetime before a new decision.'); return; }
      const row = response.body['schedule'] as Schedule;
      if (response.status !== (pending.id ? 200 : 201) || response.body['project_id'] !== this.projectId || !this.matches(row, pending)) throw new Error();
      this.accept(row);
    } catch { if (generation === this.generation) this.uncertain.set(true); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  async reconcile() {
    const pending = this.pending; if (!pending || this.busy()) return;
    this.busy.set(true); const generation = this.generation;
    try {
      const response = await this.api.visibilitySchedules(this.organizationId, this.projectId, pending.id, undefined,
        pending.id ? {} : { request_key: String(pending.body['idempotency_key']) });
      if (generation !== this.generation) return;
      const row = (pending.id ? response.body['schedule'] : (response.body['schedules'] as Schedule[] | undefined)?.[0]) as Schedule;
      if (response.status !== 200 || response.body['project_id'] !== this.projectId || !this.matches(row, pending)) throw new Error();
      this.accept(row);
    } catch { if (generation === this.generation) this.error.set('Exact decision still unconfirmed or state changed. No command was replayed.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  async more() {
    if (this.cursor === null || this.busy() || this.uncertain()) return;
    const generation = this.generation; this.busy.set(true);
    try {
      const response = await this.api.visibilitySchedules(this.organizationId, this.projectId, 0, undefined, { before_id: String(this.cursor) });
      if (generation !== this.generation) return;
      const rows = response.body['schedules'] as Schedule[];
      if (response.status !== 200 || response.body['project_id'] !== this.projectId || !Array.isArray(rows) || !rows.every((row) => this.valid(row))) throw new Error();
      this.schedules.update((existing) => [...existing, ...rows.filter((row) => !existing.some((item) => item.id === row.id))]);
      this.cursor = response.body['next_before_id'] as number | null; this.hasMore.set(response.body['has_more'] === true);
    } catch { if (generation === this.generation) this.error.set('Older repeat history unavailable.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
}
