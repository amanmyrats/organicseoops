import { Title } from '@angular/platform-browser';
import { Component, computed, DestroyRef, effect, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';
import { AccountApi, AIRoutingPolicyInfo, readAIRoutingPolicy } from '../account/account-api';

type ModelChoice = { id: number; provider_id: number; name: string; identifier: string; max_output_tokens: number | null;
  access_tier: 'unknown' | 'standard' | 'free'; price_known: boolean; privacy_policy_url: string };
type AccountChoice = { id: number; provider_id: number; label: string; source: 'platform' | 'organization' };
type AIUsageInfo = { provider_id: number; model_id: number; operation_version: string;
  request_status: 'attempted' | 'completed' | 'failed' | 'unknown'; error_category: string;
  input_tokens: number | null; output_tokens: number | null; duration_ms: number | null;
  estimated_cost_usd: string | null; reported_cost_usd: string | null;
  provider_request_id: string; provider_response_id: string;
  web_search_used: boolean; tool_call_count: number };
type AIHistoryRow = { id: number; status: string; updated_at: string; model_id: number | null;
  request_status: string; attempted_units: number;
  estimated_cost_usd: string | null; reported_cost_usd: string | null };
type AIJob = { id: number; project_id: number; status: string; error_category: string; text: string;
  attempted_units: number; cancel_requested: boolean; updated_at: string; estimated_max_cost_usd: string | null;
  routing_source: 'explicit' | 'project' | 'system'; fallback_index: number; usage: AIUsageInfo | null };

const aiTextTurkish: Record<string, string> = {
  "Unreviewed Turkish AI-text interface draft in local development. Stored status, provider and routing values remain English; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe yapay zekâ metin arayüzü taslağı. Kayıtlı durum, sağlayıcı ve yönlendirme değerleri İngilizce kalır; iki dilli onay bekleniyor.",
  "AI text job": "Yapay zekâ metin işi",
  "AI text": "Yapay zekâ metni",
  "Select a model for this project": "Bu proje için bir model seçin",
  "Return to project context": "Proje bağlamına dönün",
  "Loading project and available models.": "Proje ve kullanılabilir modeller yükleniyor.",
  "Active project": "Etkin proje",
  "organization": "kuruluş",
  "Each request reserves at most one trial/internal unit and up to 256 output tokens. Model price evidence is operator-entered; the request's estimated USD ceiling is not a provider-reported actual charge. Missing credentials, unverified price or access tier, or an exhausted trial stops the request. A default exists only after authorized staff or project settings select one.": "Her istek en fazla bir deneme/dahili birim ve 256 çıktı belirteci ayırır. Model fiyatı kanıtını operatör girer; isteğin tahmini USD üst sınırı, sağlayıcının bildirdiği gerçek ücret değildir. Eksik kimlik bilgileri, doğrulanmamış fiyat veya erişim düzeyi ya da tükenmiş deneme isteği durdurur. Varsayılan ancak yetkili personel veya proje ayarları seçtiğinde oluşur.",
  "Effective": "Geçerli",
  "system": "sistem",
  "project": "proje",
  "default:": "varsayılanı:",
  "same-provider preflight fallback(s),": "aynı sağlayıcıda istek öncesi yedek model,",
  "up to": "en fazla",
  "tokens, estimated USD": "belirteç, tahmini USD",
  "and": "ve",
  "seconds. A failed provider request never triggers fallback.": "saniye. Başarısız bir sağlayıcı isteği asla yedek modele geçiş başlatmaz.",
  "No automatic AI text default is configured. Select a model and account explicitly.": "Otomatik yapay zekâ metin varsayılanı yapılandırılmamış. Model ve hesabı açıkça seçin.",
  "No enabled text model and provider account are configured for this project.": "Bu proje için etkin metin modeli ve sağlayıcı hesabı yapılandırılmamış.",
  "Model": "Model",
  "Choose a model": "Bir model seçin",
  "Use": "Kullan:",
  "default": "varsayılan",
  "(price or access unverified)": "(fiyat veya erişim doğrulanmamış)",
  "Credential account": "Kimlik bilgisi hesabı",
  "Choose an account": "Bir hesap seçin",
  "Text to process (maximum 2000 characters)": "İşlenecek metin (en fazla 2000 karakter)",
  "Maximum output tokens": "En fazla çıktı belirteci",
  "Maximum estimated USD cost for this request (up to 100, not an actual charge)": "Bu istek için en fazla tahmini USD maliyeti (100’e kadar, gerçek ücret değildir)",
  "Free/contributor access may have different retention, training, rate-limit and reliability terms. Read the": "Ücretsiz/katkıda bulunan erişiminin saklama, eğitim, hız sınırı ve güvenilirlik koşulları farklı olabilir. Gizli proje metnini kullanmadan önce",
  "provider data-use policy": "sağlayıcının veri kullanım politikasını",
  "before using confidential project text.": "okuyun.",
  "I explicitly opt in to this free-tier data use for this request.": "Bu isteğin ücretsiz erişim düzeyindeki veri kullanımına açıkça onay veriyorum.",
  "Reserve one unit and request text": "Bir birim ayırın ve metin isteyin",
  "You may view this project but cannot launch AI work.": "Bu projeyi görüntüleyebilirsiniz ancak yapay zekâ işi başlatamazsınız.",
  "Project AI text default": "Proje yapay zekâ metin varsayılanı",
  "Current project setting:": "Geçerli proje ayarı:",
  "revision": "revizyon",
  "Remove the project override? The verified system default, if configured, will apply.": "Proje geçersiz kılması kaldırılsın mı? Yapılandırılmışsa doğrulanmış sistem varsayılanı uygulanır.",
  "Confirm removal": "Kaldırmayı onaylayın",
  "Cancel": "İptal",
  "Remove project default": "Proje varsayılanını kaldırın",
  "No project override; the system default applies if configured.": "Proje geçersiz kılması yok; yapılandırılmışsa sistem varsayılanı uygulanır.",
  "Only priced standard-access models on one provider/account can be used automatically. The fallback order applies before any provider request and never retries a paid or unknown outcome.": "Yalnızca tek sağlayıcı/hesaptaki fiyatı bilinen standart erişimli modeller otomatik kullanılabilir. Yedek model sırası herhangi bir sağlayıcı isteğinden önce uygulanır; ücretli veya sonucu bilinmeyen bir istek asla yeniden denenmez.",
  "Primary model": "Birincil model",
  "Matching provider account": "Eşleşen sağlayıcı hesabı",
  "Same-provider fallback models (up to two)": "Aynı sağlayıcıdaki yedek modeller (en fazla iki)",
  "Maximum output tokens (1–256)": "En fazla çıktı belirteci (1–256)",
  "Maximum estimated USD cost per request (up to 100)": "İstek başına en fazla tahmini USD maliyeti (100’e kadar)",
  "Timeout in seconds (1–30)": "Saniye cinsinden zaman aşımı (1–30)",
  "Save project default": "Proje varsayılanını kaydedin",
  "Recent AI requests for this project": "Bu projenin son yapay zekâ istekleri",
  "Refresh recent requests": "Son istekleri yenileyin",
  "Recent requests are unavailable. Retry the refresh.": "Son istekler kullanılamıyor. Yenilemeyi tekrar deneyin.",
  "No AI requests have been recorded for this project.": "Bu proje için yapay zekâ isteği kaydedilmemiş.",
  "Job": "İş",
  "provider request": "sağlayıcı isteği",
  "attempted unit;": "denenen birim;",
  "estimated from reported tokens USD": "bildirilen belirteçlerden tahmini USD",
  "provider-reported charge": "sağlayıcının bildirdiği ücret",
  "Inspect job": "İşi inceleyin",
  "Only the 20 most recent AI requests are shown.": "Yalnızca en son 20 yapay zekâ isteği gösterilir.",
  "Last updated": "Son güncelleme",
  "Attempted units:": "Denenen birimler:",
  "Estimated request budget: USD": "Tahmini istek bütçesi: USD",
  "(actual provider charge unknown).": "(gerçek sağlayıcı ücreti bilinmiyor).",
  "Cancellation requested.": "İptal istendi.",
  "Routing:": "Yönlendirme:",
  ", preflight choice": ", istek öncesi seçim",
  "Request issue:": "İstek sorunu:",
  "Provider request:": "Sağlayıcı isteği:",
  "operation": "işlem",
  "Reported input tokens:": "Bildirilen girdi belirteçleri:",
  "output tokens:": "çıktı belirteçleri:",
  "request duration:": "istek süresi:",
  "Estimated USD cost from reported tokens and operator-entered prices:": "Bildirilen belirteçler ve operatörün girdiği fiyatlardan tahmini USD maliyeti:",
  "Provider-reported charge:": "Sağlayıcının bildirdiği ücret:",
  "Provider request ID:": "Sağlayıcı istek kimliği:",
  "Web search used:": "Web araması kullanıldı:",
  "tool calls:": "araç çağrıları:",
  "yes": "evet",
  "no": "hayır",
  "No provider attempt is recorded for this job yet.": "Bu iş için henüz sağlayıcı denemesi kaydedilmemiş.",
  "Refresh job status": "İş durumunu yenileyin",
  "Request cancellation": "İptal isteyin",
  "Project or model selection is unavailable. Return to project context and retry.": "Proje veya model seçimi kullanılamıyor. Proje bağlamına dönüp tekrar deneyin.",
  "unknown": "bilinmiyor",
  "Unavailable model": "Kullanılamayan model",
  "Choose an authorized project.": "Yetkili bir proje seçin.",
  "Project or AI catalog is unavailable.": "Proje veya yapay zekâ kataloğu kullanılamıyor.",
  "Choose a matching model and credential account.": "Eşleşen bir model ve kimlik bilgisi hesabı seçin.",
  "Job queued. Refresh its status; no provider call runs inside this browser request.": "İş kuyruğa alındı. Durumunu yenileyin; bu tarayıcı isteğinin içinde sağlayıcı çağrısı çalışmaz.",
  "Job could not be confirmed. Retry unchanged inputs to avoid duplicate work.": "İş doğrulanamadı. Yinelenen işi önlemek için girdileri değiştirmeden tekrar deneyin.",
  "Choose a matching account and at most two fallbacks.": "Eşleşen bir hesap ve en fazla iki yedek model seçin.",
  "Project default saved. Current authorization and model cost are rechecked at each request.": "Proje varsayılanı kaydedildi. Her istekte güncel yetki ve model maliyeti yeniden kontrol edilir.",
  "Project default not saved. Refresh and check model, account and revision.": "Proje varsayılanı kaydedilmedi. Yenileyip modeli, hesabı ve revizyonu kontrol edin.",
  "Project override removed; the system default now applies if available.": "Proje geçersiz kılması kaldırıldı; varsa artık sistem varsayılanı uygulanır.",
  "Removal outcome is unknown. Refresh before retrying.": "Kaldırma sonucu bilinmiyor. Tekrar denemeden önce yenileyin.",
  "Job status is unavailable. Refresh before retrying.": "İş durumu kullanılamıyor. Tekrar denemeden önce yenileyin.",
  "Job detail is unavailable for this project.": "Bu proje için iş ayrıntısı kullanılamıyor.",
  "Cancellation confirmed or requested; a current attempt may still finish.": "İptal doğrulandı veya istendi; sürmekte olan deneme yine de tamamlanabilir.",
  "Cancellation outcome is unknown. Refresh before retrying.": "İptal sonucu bilinmiyor. Tekrar denemeden önce yenileyin.",
};

@Component({
  selector: 'app-ai-text',
  imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-shell" aria-labelledby="ai-text-title">
      <p class="eyebrow">{{ t("AI text") }}</p>
      <h1 id="ai-text-title">{{ t("Select a model for this project") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish AI-text interface draft in local development. Stored status, provider and routing values remain English; bilingual approval is pending.") }}</p> }
      <a routerLink="/app">{{ t("Return to project context") }}</a>
      @if (error()) { <p role="alert" class="form-status error">{{ t(error()) }}</p> }
      @if (message()) { <p role="status">{{ t(message()) }}</p> }
      @if (loading()) { <p role="status">{{ t("Loading project and available models.") }}</p> }
      @else if (projectName()) {
        <p class="scope-summary"><strong>{{ t("Active project") }}</strong> <span lang="">{{ projectName() }}</span> ({{ t("organization") }} {{ organizationId }})</p>
        <p>{{ t("Each request reserves at most one trial/internal unit and up to 256 output tokens. Model price evidence is operator-entered; the request's estimated USD ceiling is not a provider-reported actual charge. Missing credentials, unverified price or access tier, or an exhausted trial stops the request. A default exists only after authorized staff or project settings select one.") }}</p>
        @if (effectivePolicy(); as policy) {
          <p role="status">{{ t("Effective") }} {{ policy.project_id === null ? t('system') : t('project') }} {{ t("default:") }}
            <span lang="">{{ modelName(policy.model_id) }}</span>; {{ policy.fallback_model_ids.length }} {{ t("same-provider preflight fallback(s),") }}
            {{ t("up to") }} {{ policy.max_output_tokens }} {{ t("tokens, estimated USD") }} {{ policy.max_cost_usd }} {{ t("and") }}
            {{ policy.timeout_seconds }} {{ t("seconds. A failed provider request never triggers fallback.") }}</p>
        } @else { <p>{{ t("No automatic AI text default is configured. Select a model and account explicitly.") }}</p> }
        @if (canLaunch()) {
          @if (!models().length || !accounts().length) {
            <p>{{ t("No enabled text model and provider account are configured for this project.") }}</p>
          } @else {
            <form (submit)="submit($event)">
              <label for="ai-model">{{ t("Model") }}</label>
              <select id="ai-model" name="model_id" required (change)="selectModel($event)">
                <option value="">{{ t("Choose a model") }}</option>
                @if (effectivePolicy()) { <option value="default">{{ t("Use") }} {{ effectivePolicy()!.project_id === null ? t('system') : t('project') }} {{ t("default") }}</option> }
                @for (model of models(); track model.id) {
                  <option lang="" [value]="model.id" [disabled]="!model.price_known || model.access_tier === 'unknown'">
                    {{ model.name }} — {{ model.identifier }}
                    @if (!model.price_known || model.access_tier === 'unknown') { {{ t("(price or access unverified)") }} }
                  </option>
                }
              </select>
              <label for="ai-account">{{ t("Credential account") }}</label>
              <select id="ai-account" name="account_id" [required]="selectedModel() !== null" [disabled]="selectedModel() === null">
                <option value="">{{ t("Choose an account") }}</option>
                @for (account of availableAccounts(); track account.id) {
                  <option lang="" [value]="account.id">{{ account.label }} ({{ account.source }})</option>
                }
              </select>
              <label for="ai-prompt">{{ t("Text to process (maximum 2000 characters)") }}</label>
              <textarea lang="" id="ai-prompt" name="prompt" required minlength="1" maxlength="2000"></textarea>
              <label for="ai-tokens">{{ t("Maximum output tokens") }}</label>
              <input id="ai-tokens" name="max_output_tokens" type="number" min="1" [max]="tokenLimit()" value="100" required />
              <label for="ai-max-cost">{{ t("Maximum estimated USD cost for this request (up to 100, not an actual charge)") }}</label>
              <input lang="en" id="ai-max-cost" name="max_cost_usd" inputmode="decimal" pattern="[0-9]{1,3}(\\.[0-9]{1,6})?" maxlength="10" required />
              @if (selectedModelTier() === 'free') {
                <p role="alert">{{ t("Free/contributor access may have different retention, training, rate-limit and reliability terms. Read the") }} <a [href]="selectedPrivacyPolicy()" rel="noopener noreferrer" target="_blank">{{ t("provider data-use policy") }}</a>
                  {{ t("before using confidential project text.") }}</p>
                <label for="ai-free-consent"><input id="ai-free-consent" name="allow_free" type="checkbox" required />
                  {{ t("I explicitly opt in to this free-tier data use for this request.") }}</label>
              }
              <button type="submit" [disabled]="busy()">{{ t("Reserve one unit and request text") }}</button>
            </form>
          }
        } @else { <p>{{ t("You may view this project but cannot launch AI work.") }}</p> }
        @if (canManage() && standardModels().length) {
          <section class="workspace-panel" aria-labelledby="project-route-title">
            <h2 id="project-route-title">{{ t("Project AI text default") }}</h2>
            @if (projectPolicy(); as policy) {
              <p>{{ t("Current project setting:") }} <span lang="">{{ modelName(policy.model_id) }}</span>; {{ t("revision") }} {{ policy.revision }}.</p>
              @if (confirmRemovePolicy()) {
                <p role="alert">{{ t("Remove the project override? The verified system default, if configured, will apply.") }}</p>
                <button type="button" (click)="removeProjectRoute()" [disabled]="busy()">{{ t("Confirm removal") }}</button>
                <button type="button" (click)="confirmRemovePolicy.set(false)" [disabled]="busy()">{{ t("Cancel") }}</button>
              } @else {
                <button type="button" (click)="confirmRemovePolicy.set(true)" [disabled]="busy()">{{ t("Remove project default") }}</button>
              }
            } @else { <p>{{ t("No project override; the system default applies if configured.") }}</p> }
            <p>{{ t("Only priced standard-access models on one provider/account can be used automatically. The fallback order applies before any provider request and never retries a paid or unknown outcome.") }}</p>
            <form (submit)="saveProjectRoute($event)">
              <label for="project-route-model">{{ t("Primary model") }}</label>
              <select id="project-route-model" name="model_id" required (change)="selectPolicyModel($event)">
                <option value="">{{ t("Choose a model") }}</option>
                @for (model of standardModels(); track model.id) {
                  <option lang="" [value]="model.id">{{ model.name }} — {{ model.identifier }}</option>
                }
              </select>
              <label for="project-route-account">{{ t("Matching provider account") }}</label>
              <select id="project-route-account" name="account_id" required>
                <option value="">{{ t("Choose an account") }}</option>
                @for (account of policyAccounts(); track account.id) {
                  <option lang="" [value]="account.id">{{ account.label }} ({{ account.source }})</option>
                }
              </select>
              <label for="project-route-fallbacks">{{ t("Same-provider fallback models (up to two)") }}</label>
              <select id="project-route-fallbacks" name="fallback_model_ids" multiple size="3">
                @for (model of policyFallbacks(); track model.id) {
                  <option lang="" [value]="model.id">{{ model.name }} — {{ model.identifier }}</option>
                }
              </select>
              <label for="project-route-tokens">{{ t("Maximum output tokens (1–256)") }}</label>
              <input id="project-route-tokens" name="max_output_tokens" type="number" min="1" max="256" value="100" required />
              <label for="project-route-cost">{{ t("Maximum estimated USD cost per request (up to 100)") }}</label>
              <input lang="en" id="project-route-cost" name="max_cost_usd" inputmode="decimal" pattern="[0-9]{1,3}(\\.[0-9]{1,6})?" maxlength="10" required />
              <label for="project-route-timeout">{{ t("Timeout in seconds (1–30)") }}</label>
              <input id="project-route-timeout" name="timeout_seconds" type="number" min="1" max="30" value="30" required />
              <button type="submit" [disabled]="busy()">{{ t("Save project default") }}</button>
            </form>
          </section>
        }
        <section class="workspace-panel" aria-labelledby="ai-history-title">
          <h2 id="ai-history-title">{{ t("Recent AI requests for this project") }}</h2>
          <button type="button" (click)="loadHistory()" [disabled]="busy()">{{ t("Refresh recent requests") }}</button>
          @if (historyFailed()) { <p role="alert">{{ t("Recent requests are unavailable. Retry the refresh.") }}</p> }
          @else if (!history().length) { <p>{{ t("No AI requests have been recorded for this project.") }}</p> }
          <ul>
            @for (entry of history(); track entry.id) {
              <li>{{ t("Job") }} {{ entry.id }} — <span lang="en">{{ entry.status }}</span>; {{ t("provider request") }} <span lang="en">{{ entry.request_status }}</span>;
                {{ entry.attempted_units }} {{ t("attempted unit;") }}
                {{ t("estimated from reported tokens USD") }} {{ entry.estimated_cost_usd ?? t('unknown') }};
                {{ t("provider-reported charge") }} {{ entry.reported_cost_usd ?? t('unknown') }}.
                <button type="button" (click)="openHistory(entry)" [disabled]="busy()">{{ t("Inspect job") }} {{ entry.id }}</button>
              </li>
            }
          </ul>
          @if (historyHasMore()) { <p>{{ t("Only the 20 most recent AI requests are shown.") }}</p> }
        </section>
        @if (job(); as current) {
          <section class="workspace-panel" aria-labelledby="ai-job-title">
            <h2 id="ai-job-title">{{ t("Job") }} {{ current.id }} — <span lang="en">{{ current.status }}</span></h2>
            <p role="status">{{ t("Last updated") }} <span lang="en">{{ current.updated_at }}</span>. {{ t("Attempted units:") }} {{ current.attempted_units }}.
              @if (current.estimated_max_cost_usd !== null) { {{ t("Estimated request budget: USD") }} {{ current.estimated_max_cost_usd }} {{ t("(actual provider charge unknown).") }} }
              @if (current.cancel_requested) { {{ t("Cancellation requested.") }} }
            </p>
            <p>{{ t("Routing:") }} <span lang="en">{{ current.routing_source }}</span>@if (current.fallback_index) { {{ t(", preflight choice") }} {{ current.fallback_index + 1 }} }.</p>
            @if (current.error_category) { <p role="alert">{{ t("Request issue:") }} <span lang="en">{{ current.error_category }}</span></p> }
            @if (current.usage; as usage) {
              <p>{{ t("Provider request:") }} <span lang="en">{{ usage.request_status }}</span>@if (usage.error_category) { (<span lang="en">{{ usage.error_category }}</span>) }.
                {{ t("Model") }} {{ usage.model_id }}; {{ t("operation") }} <span lang="en">{{ usage.operation_version }}</span>.</p>
              <p>{{ t("Reported input tokens:") }} {{ usage.input_tokens ?? t('unknown') }}; {{ t("output tokens:") }}
                {{ usage.output_tokens ?? t('unknown') }}; {{ t("request duration:") }}
                {{ usage.duration_ms === null ? t('unknown') : usage.duration_ms + ' ms' }}.</p>
              <p>{{ t("Estimated USD cost from reported tokens and operator-entered prices:") }}
                {{ usage.estimated_cost_usd ?? t('unknown') }}. {{ t("Provider-reported charge:") }}
                {{ usage.reported_cost_usd ?? t('unknown') }}.</p>
              @if (usage.provider_request_id) { <p>{{ t("Provider request ID:") }} <span lang="en">{{ usage.provider_request_id }}</span></p> }
              <p>{{ t("Web search used:") }} {{ usage.web_search_used ? t('yes') : t('no') }}; {{ t("tool calls:") }} {{ usage.tool_call_count }}.</p>
            } @else { <p>{{ t("No provider attempt is recorded for this job yet.") }}</p> }
            @if (current.status === 'succeeded') { <pre lang="">{{ current.text }}</pre> }
            <button type="button" (click)="refresh()" [disabled]="busy()">{{ t("Refresh job status") }}</button>
            @if (canLaunch() && (current.status === 'queued' || current.status === 'running') && !current.cancel_requested) {
              <button type="button" (click)="cancel()" [disabled]="busy()">{{ t("Request cancellation") }}</button>
            }
          </section>
        }
      } @else { <p>{{ t("Project or model selection is unavailable. Return to project context and retry.") }}</p> }
    </section>
  `,
})
export class AIText implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  t(text: string) { return this.uiLanguage() === 'tr' ? aiTextTurkish[text] ?? text : text; }
  readonly loading = signal(true);
  readonly busy = signal(false);
  readonly projectName = signal('');
  readonly role = signal('viewer');
  readonly models = signal<ModelChoice[]>([]);
  readonly accounts = signal<AccountChoice[]>([]);
  readonly projectPolicy = signal<AIRoutingPolicyInfo | null>(null);
  readonly effectivePolicy = signal<AIRoutingPolicyInfo | null>(null);
  readonly policyModelId = signal<number | null>(null);
  readonly confirmRemovePolicy = signal(false);
  readonly selectedModel = signal<number | null>(null);
  readonly job = signal<AIJob | null>(null);
  readonly history = signal<AIHistoryRow[]>([]);
  readonly historyFailed = signal(false);
  readonly historyHasMore = signal(false);
  readonly error = signal('');
  readonly message = signal('');
  organizationId = 0;
  projectId = 0;
  private generation = 0;
  private historyRequest = 0;
  private pending = { input: '', key: '' };
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);

  constructor(private readonly api: AccountApi, title: Title) {
    effect(() => title.setTitle(`${this.t('AI text job')} — OrganicSEOOps`));
  }

  ngOnInit() {
    void this.loadProductLanguage();
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      this.generation++;
      this.historyRequest++;
      this.organizationId = Number(params.get('organizationId'));
      this.projectId = Number(params.get('projectId'));
      this.projectName.set(''); this.models.set([]); this.accounts.set([]); this.selectedModel.set(null);
      this.projectPolicy.set(null); this.effectivePolicy.set(null); this.policyModelId.set(null);
      this.confirmRemovePolicy.set(false);
      this.job.set(null); this.message.set(''); this.error.set(''); this.busy.set(false);
      this.history.set([]); this.historyFailed.set(false); this.historyHasMore.set(false);
      this.pending = { input: '', key: '' }; this.loading.set(true);
      if (Number.isSafeInteger(this.organizationId) && this.organizationId > 0
        && Number.isSafeInteger(this.projectId) && this.projectId > 0) {
        void this.load(this.generation);
        void this.loadHistory();
      }
      else { this.loading.set(false); this.error.set('Choose an authorized project.'); }
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

  canLaunch() { return ['owner', 'admin', 'member'].includes(this.role()); }
  canManage() { return ['owner', 'admin'].includes(this.role()); }
  modelName(id: number) { return this.models().find((row) => row.id === id)?.name ?? this.t('Unavailable model'); }
  standardModels() { return this.models().filter((row) => row.access_tier === 'standard' && row.price_known); }
  policyAccounts() {
    const model = this.models().find((row) => row.id === this.policyModelId());
    return model ? this.accounts().filter((row) => row.provider_id === model.provider_id) : [];
  }
  policyFallbacks() {
    const model = this.models().find((row) => row.id === this.policyModelId());
    return model ? this.standardModels().filter((row) => row.provider_id === model.provider_id && row.id !== model.id) : [];
  }
  selectPolicyModel(event: Event) { this.policyModelId.set(Number((event.target as HTMLSelectElement).value) || null); }
  availableAccounts() {
    const model = this.models().find((row) => row.id === this.selectedModel());
    return model ? this.accounts().filter((row) => row.provider_id === model.provider_id) : [];
  }
  tokenLimit() { return Math.min(256, this.selectedModel() === null && this.effectivePolicy()
    ? this.effectivePolicy()!.max_output_tokens
    : this.models().find((row) => row.id === this.selectedModel())?.max_output_tokens ?? 256); }
  selectedModelTier() { return this.models().find((row) => row.id === this.selectedModel())?.access_tier ?? 'unknown'; }
  selectedPrivacyPolicy() { return this.models().find((row) => row.id === this.selectedModel())?.privacy_policy_url ?? ''; }
  selectModel(event: Event) { this.selectedModel.set(Number((event.target as HTMLSelectElement).value) || null); }

  private async load(generation: number) {
    const orgId = this.organizationId;
    const projectId = this.projectId;
    try {
      const [projects, catalog, routing] = await Promise.all([
        this.api.projects(orgId), this.api.projectAITextCatalog(orgId, projectId), this.api.projectAIRouting(orgId, projectId),
      ]);
      if (generation !== this.generation) return;
      const project = projects.status === 200 && Array.isArray(projects.body['projects'])
        ? (projects.body['projects'] as Record<string, unknown>[]).find((row) => row['id'] === projectId && row['organization_id'] === orgId)
        : null;
      if (!project || typeof project['name'] !== 'string' || typeof project['role'] !== 'string'
        || catalog.status !== 200 || !Array.isArray(catalog.body['models'])
        || !catalog.body['models'].every(isModel) || !Array.isArray(catalog.body['accounts'])
        || !catalog.body['accounts'].every(isAccount) || catalog.body['cost_status'] !== 'unknown'
        || routing.status !== 200
        || (routing.body['policy'] !== null && !readAIRoutingPolicy(routing.body['policy']))
        || (routing.body['effective'] !== null && !readAIRoutingPolicy(routing.body['effective']))) throw new Error();
      const own = readAIRoutingPolicy(routing.body['policy']);
      const effective = readAIRoutingPolicy(routing.body['effective']);
      if (own && own.project_id !== projectId || effective && effective.project_id !== null && effective.project_id !== projectId) throw new Error();
      this.projectName.set(project['name']);
      this.role.set(project['role']);
      this.models.set(catalog.body['models'] as ModelChoice[]);
      this.accounts.set(catalog.body['accounts'] as AccountChoice[]);
      this.projectPolicy.set(own);
      this.effectivePolicy.set(effective);
    } catch { if (generation === this.generation) this.error.set('Project or AI catalog is unavailable.'); }
    finally { if (generation === this.generation) this.loading.set(false); }
  }

  async submit(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || !this.canLaunch() || this.busy()) return;
    const fields = new FormData(form);
    const useDefault = fields.get('model_id') === 'default';
    const modelId = useDefault ? null : Number(fields.get('model_id'));
    const accountId = useDefault ? null : Number(fields.get('account_id'));
    const selected = this.models().find((row) => row.id === modelId);
    if (useDefault ? !this.effectivePolicy() : (modelId !== this.selectedModel() || !selected?.price_known
      || selected.access_tier === 'unknown' || !this.availableAccounts().some((row) => row.id === accountId))) {
      this.error.set('Choose a matching model and credential account.'); return;
    }
    const data = { model_id: modelId, account_id: accountId, prompt: String(fields.get('prompt')),
      max_output_tokens: Number(fields.get('max_output_tokens')), max_cost_usd: String(fields.get('max_cost_usd')),
      allow_free: !useDefault && selected?.access_tier === 'free' && fields.has('allow_free') };
    const input = JSON.stringify([this.organizationId, this.projectId, data]);
    if (this.pending.input !== input) this.pending = { input, key: crypto.randomUUID() };
    const generation = this.generation;
    this.busy.set(true); this.error.set('');
    try {
      const result = await this.api.createAIText(this.organizationId, this.projectId,
        { ...data, idempotency_key: this.pending.key });
      if (generation !== this.generation) return;
      const job = readJob(result.body['job']);
      if (result.status !== 202 || !job || job.project_id !== this.projectId) throw new Error();
      this.job.set(job); this.pending = { input: '', key: '' };
      this.message.set('Job queued. Refresh its status; no provider call runs inside this browser request.');
      form.reset(); this.selectedModel.set(null);
      void this.loadHistory();
    } catch { if (generation === this.generation) this.error.set('Job could not be confirmed. Retry unchanged inputs to avoid duplicate work.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }

  async saveProjectRoute(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || !this.canManage() || this.busy()) return;
    const fields = new FormData(form);
    const modelId = Number(fields.get('model_id'));
    const accountId = Number(fields.get('account_id'));
    const fallbacks = fields.getAll('fallback_model_ids').map(Number);
    if (modelId !== this.policyModelId() || !this.policyAccounts().some((row) => row.id === accountId)
      || fallbacks.length > 2) { this.error.set('Choose a matching account and at most two fallbacks.'); return; }
    const generation = this.generation;
    this.busy.set(true); this.error.set('');
    try {
      const result = await this.api.saveProjectAIRouting(this.organizationId, this.projectId, {
        model_id: modelId, account_id: accountId, fallback_model_ids: fallbacks,
        max_output_tokens: Number(fields.get('max_output_tokens')),
        max_cost_usd: String(fields.get('max_cost_usd')),
        timeout_seconds: Number(fields.get('timeout_seconds')), revision: this.projectPolicy()?.revision ?? 0,
        policy_id: this.projectPolicy()?.id ?? null,
      });
      if (generation !== this.generation) return;
      const policy = readAIRoutingPolicy(result.body['policy']);
      if (result.status !== 200 || !policy || policy.project_id !== this.projectId) throw new Error();
      this.projectPolicy.set(policy); this.effectivePolicy.set(policy);
      this.policyModelId.set(null); form.reset();
      this.message.set('Project default saved. Current authorization and model cost are rechecked at each request.');
    } catch { if (generation === this.generation) this.error.set('Project default not saved. Refresh and check model, account and revision.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }

  async removeProjectRoute() {
    const policy = this.projectPolicy();
    if (!policy || !this.confirmRemovePolicy() || !this.canManage() || this.busy()) return;
    const generation = this.generation;
    this.busy.set(true); this.error.set('');
    try {
      const result = await this.api.removeProjectAIRouting(this.organizationId, this.projectId, policy.revision, policy.id);
      if (generation !== this.generation) return;
      const effective = readAIRoutingPolicy(result.body['effective']);
      if (result.status !== 200 || result.body['removed'] !== true || result.body['policy'] !== null
        || result.body['effective'] !== null && (effective?.project_id !== null)) throw new Error();
      this.projectPolicy.set(null); this.effectivePolicy.set(effective); this.confirmRemovePolicy.set(false);
      this.message.set('Project override removed; the system default now applies if available.');
    } catch { if (generation === this.generation) this.error.set('Removal outcome is unknown. Refresh before retrying.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }

  async refresh() {
    const job = this.job();
    if (!job || this.busy()) return;
    const generation = this.generation;
    this.busy.set(true);
    try {
      const result = await this.api.aiTextJob(this.organizationId, this.projectId, job.id);
      if (generation !== this.generation) return;
      const updated = readJob(result.body['job']);
      if (result.status !== 200 || updated?.project_id !== this.projectId || updated.id !== job.id) throw new Error();
      this.job.set(updated); this.error.set('');
    } catch { if (generation === this.generation) this.error.set('Job status is unavailable. Refresh before retrying.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }

  async loadHistory() {
    const generation = this.generation;
    const request = ++this.historyRequest;
    const organizationId = this.organizationId;
    const projectId = this.projectId;
    try {
      const result = await this.api.aiTextHistory(organizationId, projectId);
      if (generation !== this.generation || request !== this.historyRequest) return;
      if (result.status !== 200 || !Array.isArray(result.body['jobs']) || result.body['jobs'].length > 20
        || !result.body['jobs'].every(isHistoryRow) || typeof result.body['has_more'] !== 'boolean') throw new Error();
      this.history.set(result.body['jobs'] as AIHistoryRow[]);
      this.historyHasMore.set(result.body['has_more']);
      this.historyFailed.set(false);
    } catch {
      if (generation === this.generation && request === this.historyRequest) {
        this.history.set([]); this.historyFailed.set(true);
      }
    }
  }

  async openHistory(entry: AIHistoryRow) {
    if (this.busy() || !this.history().some((row) => row.id === entry.id)) return;
    const generation = this.generation;
    this.busy.set(true);
    try {
      const result = await this.api.aiTextJob(this.organizationId, this.projectId, entry.id);
      if (generation !== this.generation) return;
      const job = readJob(result.body['job']);
      if (result.status !== 200 || job?.project_id !== this.projectId || job.id !== entry.id) throw new Error();
      this.job.set(job); this.error.set('');
    } catch { if (generation === this.generation) this.error.set('Job detail is unavailable for this project.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }

  async cancel() {
    const job = this.job();
    if (!job || !this.canLaunch() || this.busy()) return;
    const generation = this.generation;
    this.busy.set(true);
    try {
      const result = await this.api.cancelAIText(this.organizationId, this.projectId, job.id);
      if (generation !== this.generation) return;
      const updated = readJob(result.body['job']);
      if (result.status !== 200 || updated?.project_id !== this.projectId || updated.id !== job.id) throw new Error();
      this.job.set(updated); this.message.set('Cancellation confirmed or requested; a current attempt may still finish.');
    } catch { if (generation === this.generation) this.error.set('Cancellation outcome is unknown. Refresh before retrying.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
}

function isModel(value: unknown): value is ModelChoice {
  if (!value || typeof value !== 'object') return false;
  const row = value as Record<string, unknown>;
  return Number.isSafeInteger(row['id']) && Number(row['id']) > 0
    && Number.isSafeInteger(row['provider_id']) && Number(row['provider_id']) > 0
    && typeof row['name'] === 'string' && typeof row['identifier'] === 'string'
    && (row['max_output_tokens'] === null || Number.isSafeInteger(row['max_output_tokens']))
    && typeof row['access_tier'] === 'string' && ['unknown', 'standard', 'free'].includes(row['access_tier'])
    && typeof row['price_known'] === 'boolean' && typeof row['privacy_policy_url'] === 'string';
}

function isAccount(value: unknown): value is AccountChoice {
  if (!value || typeof value !== 'object') return false;
  const row = value as Record<string, unknown>;
  return Number.isSafeInteger(row['id']) && Number(row['id']) > 0
    && Number.isSafeInteger(row['provider_id']) && Number(row['provider_id']) > 0
    && typeof row['label'] === 'string' && typeof row['source'] === 'string' && ['platform', 'organization'].includes(row['source']);
}

function readJob(value: unknown): AIJob | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  return Number.isSafeInteger(row['id']) && Number(row['id']) > 0
    && Number.isSafeInteger(row['project_id']) && Number(row['project_id']) > 0
    && typeof row['status'] === 'string' && ['queued', 'running', 'succeeded', 'failed', 'cancelled'].includes(row['status'])
    && typeof row['error_category'] === 'string' && typeof row['text'] === 'string' && row['text'].length <= 4000
    && Number.isSafeInteger(row['attempted_units']) && typeof row['cancel_requested'] === 'boolean'
    && (row['estimated_max_cost_usd'] === null || typeof row['estimated_max_cost_usd'] === 'string')
    && typeof row['routing_source'] === 'string' && ['explicit', 'project', 'system'].includes(row['routing_source'])
    && Number.isSafeInteger(row['fallback_index']) && Number(row['fallback_index']) >= 0
    && (row['usage'] === null || readAIUsage(row['usage']) !== null)
    && typeof row['updated_at'] === 'string' ? row as AIJob : null;
}

function readAIUsage(value: unknown): AIUsageInfo | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  const tokens = (item: unknown) => item === null || Number.isSafeInteger(item) && Number(item) >= 0;
  return Number.isSafeInteger(row['provider_id']) && Number(row['provider_id']) > 0
    && Number.isSafeInteger(row['model_id']) && Number(row['model_id']) > 0
    && typeof row['operation_version'] === 'string' && row['operation_version'].length <= 40
    && typeof row['request_status'] === 'string' && ['attempted', 'completed', 'failed', 'unknown'].includes(row['request_status'])
    && typeof row['error_category'] === 'string' && row['error_category'].length <= 64
    && tokens(row['input_tokens']) && tokens(row['output_tokens']) && tokens(row['duration_ms'])
    && (row['estimated_cost_usd'] === null || typeof row['estimated_cost_usd'] === 'string')
    && (row['reported_cost_usd'] === null || typeof row['reported_cost_usd'] === 'string')
    && typeof row['provider_request_id'] === 'string' && row['provider_request_id'].length <= 128
    && typeof row['provider_response_id'] === 'string' && row['provider_response_id'].length <= 128
    && typeof row['web_search_used'] === 'boolean' && tokens(row['tool_call_count'])
    ? row as unknown as AIUsageInfo : null;
}

function isHistoryRow(value: unknown): value is AIHistoryRow {
  if (!value || typeof value !== 'object') return false;
  const row = value as Record<string, unknown>;
  return Number.isSafeInteger(row['id']) && Number(row['id']) > 0
    && typeof row['status'] === 'string' && ['queued', 'running', 'succeeded', 'failed', 'cancelled'].includes(row['status'])
    && typeof row['updated_at'] === 'string'
    && (row['model_id'] === null || Number.isSafeInteger(row['model_id']))
    && typeof row['request_status'] === 'string' && ['not_attempted', 'attempted', 'completed', 'failed', 'unknown'].includes(row['request_status'])
    && (row['attempted_units'] === 0 || row['attempted_units'] === 1)
    && (row['estimated_cost_usd'] === null || typeof row['estimated_cost_usd'] === 'string')
    && (row['reported_cost_usd'] === null || typeof row['reported_cost_usd'] === 'string');
}
