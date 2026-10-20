import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, effect, OnInit, computed, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { combineLatest } from 'rxjs';
import { AccountApi } from '../account/account-api';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';
import type { TopicReview } from './project-topics';

type Model = { id: number; provider_id: number; name: string; access_tier: string; max_output_tokens: number | null;
  price_known: boolean; privacy_policy_url: string };
type Account = { id: number; provider_id: number; label: string; source: string };
type History = { id: number; project_id: number; status: string; topic: string; updated_at: string };
type Source = { index: number; state: string; url?: string; title?: string; excerpt?: string;
  sha256?: string; retrieved_at?: string; error_category?: string };
type Claim = { text: string; source_index: number; quote: string };
type ResearchJob = { id: number; project_id: number; status: string; topic: string; updated_at: string;
  error_category: string; estimate_units: number; attempted_units: number; cancel_requested: boolean;
  estimated_max_cost_usd: string | null; context_current: boolean; usage: { request_status: string;
    estimated_cost_usd: string | null; reported_cost_usd: string | null } | null;
  evidence: { coverage: string; sources: Source[]; synthesis_state: string;
    synthesis: { summary: string; claims: Claim[] } | null; provider_search: string } | null };

const projectResearchTurkish: Record<string, string> = {
  "Sourced topic research": "Kaynaklı konu araştırması",
  "Research a project topic with explicit sources": "Bir proje konusunu açık kaynaklarla araştırın",
  "Unreviewed Turkish research interface draft in local development. Provider values and source/AI text retain their original language; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe araştırma arayüzü taslağı. Sağlayıcı değerleri ve kaynak/yapay zekâ metinleri özgün dillerini korur; iki dilli onay bekleniyor.",
  "Return to project evidence": "Proje kanıtlarına dönün",
  "Draft a source-linked brief from completed research and a human-accepted action": "Tamamlanan araştırma ve bir insanın kabul ettiği eylemden kaynak bağlantılı bir içerik özeti taslağı hazırlayın",
  "Review exact stored quotes as human authority prospects (not verified backlinks)": "Saklanan birebir alıntıları insan incelemesiyle otorite fırsatları olarak değerlendirin (doğrulanmış geri bağlantılar değildir)",
  "Checking project research context.": "Proje araştırma bağlamı kontrol ediliyor.",
  "Active project:": "Etkin proje:",
  "(organization": "(kuruluş",
  "). Only configured approved HTTPS origins may be fetched. Provide up to five explicit page URLs; this job does not search the web or infer that sources are complete. Excerpts and AI interpretations are untrusted, require human fact review and cannot publish content.": "). Yalnızca yapılandırılmış, onaylanmış HTTPS kaynaklarına erişilebilir. En fazla beş açık sayfa URL’si girin; bu iş web’de arama yapmaz veya kaynakların eksiksiz olduğunu varsaymaz. Alıntılar ve yapay zekâ yorumları güvenilir kabul edilmez, insanlar tarafından doğruluk incelemesi gerektirir ve içerik yayımlayamaz.",
  "Authenticated exact-current topic review": "Kimliği doğrulanmış, tam güncel konu incelemesi",
  "· revision": "· sürüm",
  "· human": "· insan",
  "judgment.": "değerlendirmesi.",
  "Topic, language and mapping are bound to this review; URL parameters are only a selection request.": "Konu, dil ve eşleştirme bu incelemeye bağlıdır; URL parametreleri yalnızca bir seçim isteğidir.",
  "Use standalone editable topic instead": "Bunun yerine bağımsız, düzenlenebilir konu kullanın",
  "Up to six internal units may be reserved (one per selected source and one model attempt). Estimated USD ceiling is operator-price-based, not a provider charge. A failed or uncertain request is never replayed automatically.": "En fazla altı dahili birim ayrılabilir (seçilen her kaynak için bir ve model denemesi için bir). Tahmini USD üst sınırı operatör fiyatına dayanır, sağlayıcı ücreti değildir. Başarısız veya sonucu belirsiz bir istek asla otomatik olarak tekrarlanmaz.",
  "No eligible priced structured-output model and account are configured. Configure them before requesting synthesis.": "Uygun, fiyatı belirli bir yapılandırılmış çıktı modeli ve hesap yapılandırılmamış. Sentez istemeden önce bunları yapılandırın.",
  "Selected topic (up to 240 characters)": "Seçilen konu (en fazla 240 karakter)",
  "Current reviewed intent/page mapping (optional)": "Güncel, incelenmiş niyet/sayfa eşleştirmesi (isteğe bağlı)",
  "Standalone user-selected topic": "Kullanıcının seçtiği bağımsız konu",
  "(revision": "(sürüm",
  "Project SEO language": "Proje SEO dili",
  "Select a configured language": "Yapılandırılmış bir dil seçin",
  "Explicit approved HTTPS source URLs, one per line (maximum five; no query strings)": "Açık, onaylanmış HTTPS kaynak URL’leri, her satıra bir tane (en fazla beş; sorgu dizeleri olmadan)",
  "Priced structured-output model": "Fiyatı belirli yapılandırılmış çıktı modeli",
  "Choose a model": "Bir model seçin",
  " — price unavailable": " — fiyat kullanılamıyor",
  "Matching provider account": "Eşleşen sağlayıcı hesabı",
  "Choose an account": "Bir hesap seçin",
  "Free-model retention, training, rate and reliability may differ. Review the": "Ücretsiz modelin saklama, eğitim, hız sınırları ve güvenilirliği farklı olabilir. İnceleyin:",
  "provider data-use policy": "sağlayıcının veri kullanım politikası",
  "I explicitly opt in to free-tier processing for this request.": "Bu istek için ücretsiz katmanda işlemeyi açıkça kabul ediyorum.",
  "Maximum output tokens (128–2048)": "En fazla çıktı belirteci (128–2048)",
  "Maximum estimated USD cost (greater than zero, up to 100)": "En fazla tahmini USD maliyeti (sıfırdan büyük, en fazla 100)",
  "Reserve work and collect sources": "İş için birim ayırın ve kaynakları toplayın",
  "You may view research evidence but cannot launch research for this project.": "Araştırma kanıtlarını görüntüleyebilirsiniz ancak bu proje için araştırma başlatamazsınız.",
  "Recent research jobs": "Son araştırma işleri",
  "Refresh project jobs": "Proje işlerini yenileyin",
  "No research job is recorded for this project.": "Bu proje için kayıtlı araştırma işi yok.",
  "Inspect job": "İşi inceleyin",
  "Only the 20 most recent jobs are shown.": "Yalnızca en son 20 iş gösterilir.",
  "Job": "İş",
  "Updated": "Güncellenme",
  "; attempted units": "; denenen birimler",
  "of up to": "/ en fazla",
  "Estimated maximum USD": "Tahmini en fazla USD",
  "; provider reported charge": "; sağlayıcının bildirdiği ücret",
  "unknown": "bilinmiyor",
  "The current mapping or project configuration changed. These are historical observations; refresh sources before using them.": "Güncel eşleştirme veya proje yapılandırması değişti. Bunlar geçmiş gözlemlerdir; kullanmadan önce kaynakları yenileyin.",
  "Issue:": "Sorun:",
  ". Missing evidence is not a negative finding.": ". Eksik kanıt olumsuz bir bulgu değildir.",
  "Provider attempt:": "Sağlayıcı denemesi:",
  "; estimated from reported tokens USD": "; bildirilen belirteçlerden tahmini USD",
  "Refresh this job": "Bu işi yenileyin",
  "Request cancellation": "İptal isteyin",
  "Coverage:": "Kapsam:",
  ". Source collection was limited to explicitly selected URLs; provider search": ". Kaynak toplama açıkça seçilen URL’lerle sınırlıydı; sağlayıcı araması",
  "Source": "Kaynak",
  "date unavailable": "tarih kullanılamıyor",
  "Observed byte SHA-256": "Gözlemlenen bayt SHA-256",
  ". Excerpt (not verified as fact):": ". Alıntı (doğruluğu teyit edilmedi):",
  "unavailable": "kullanılamıyor",
  "AI interpretation · requires human review": "Yapay zekâ yorumu · insan incelemesi gerektirir",
  "· source": "· kaynak",
  "· exact excerpt:": "· birebir alıntı:",
  ". Verify before using this claim.": ". Bu iddiayı kullanmadan önce doğrulayın.",
  "No AI synthesis is available; source collection alone does not establish a conclusion.": "Yapay zekâ sentezi yok; yalnızca kaynak toplamak bir sonuç ortaya koymaz.",
  "Select a current project.": "Güncel bir proje seçin.",
  "Invalid topic selection. Return to topic review and choose current evidence.": "Geçersiz konu seçimi. Konu incelemesine dönün ve güncel kanıt seçin.",
  "Selected topic review or source changed or is unavailable. Return to topic review; research is blocked until a current selection is loaded.": "Seçilen konu incelemesi veya kaynak değişti ya da kullanılamıyor. Konu incelemesine dönün; güncel seçim yüklenene kadar araştırma engellenir.",
  "Current project research context is unavailable or access was revoked.": "Güncel proje araştırma bağlamı kullanılamıyor veya erişim iptal edildi.",
  "Choose a topic of 1–240 characters.": "1–240 karakterlik bir konu seçin.",
  "Choose up to five approved sources and a permitted model budget.": "En fazla beş onaylı kaynak ve izin verilen bir model bütçesi seçin.",
  "Research queued. Refresh this job to check collection and synthesis; a provider attempt cannot be replayed blindly.": "Araştırma kuyruğa alındı. Toplama ve sentezi kontrol etmek için bu işi yenileyin; sağlayıcı denemesi kontrolsüzce tekrarlanamaz.",
  "Research request unavailable. Refresh history before creating another request.": "Araştırma isteği kullanılamıyor. Başka bir istek oluşturmadan önce geçmişi yenileyin.",
  "Research job unavailable or permission was revoked.": "Araştırma işi kullanılamıyor veya izin iptal edildi.",
  "Cancellation requested; the worker rechecks at source and synthesis boundaries.": "İptal istendi; işleyici kaynak ve sentez sınırlarında yeniden kontrol eder.",
  "Cancellation outcome unavailable; refresh job status.": "İptal sonucu kullanılamıyor; iş durumunu yenileyin."
};

@Component({
  selector: 'app-project-research',
  imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="research-title">
      <h1 id="research-title">{{ t("Research a project topic with explicit sources") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish research interface draft in local development. Provider values and source/AI text retain their original language; bilingual approval is pending.") }}</p> }
      <a [routerLink]="['/app/dashboard', organizationId, projectId]">{{ t("Return to project evidence") }}</a>
      <p><a [routerLink]="['/app/briefs', organizationId, projectId]">{{ t("Draft a source-linked brief from completed research and a human-accepted action") }}</a></p>
      <p><a [routerLink]="['/app/authority-prospects', organizationId, projectId]">{{ t("Review exact stored quotes as human authority prospects (not verified backlinks)") }}</a></p>
      @if (loading()) { <p role="status">{{ t("Checking project research context.") }}</p> }
      @if (error()) { <p role="alert" [attr.lang]="t(error()) === error() ? 'en' : uiLanguage()">{{ t(error()) }}</p> }
      @if (!loading() && !error()) {
        <p>{{ t("Active project:") }} <span lang="">{{ projectName() }}</span> {{ t("(organization") }} {{ organizationId }}{{ t("). Only configured approved HTTPS origins may be fetched. Provide up to five explicit page URLs; this job does not search the web or infer that sources are complete. Excerpts and AI interpretations are untrusted, require human fact review and cannot publish content.") }}</p>
        @if (topicReview(); as review) {
          <p>{{ t("Authenticated exact-current topic review") }} {{ review.id }} {{ t("· revision") }} {{ review.revision }} {{ t("· human") }} <span lang="en">{{ review.classification }}</span> {{ t("judgment.") }}
            {{ t("Topic, language and mapping are bound to this review; URL parameters are only a selection request.") }}</p>
          <button type="button" (click)="detachTopic()" [disabled]="busy()">{{ t("Use standalone editable topic instead") }}</button>
        }
        @if (handoffError()) { <p role="alert" [attr.lang]="t(handoffError()) === handoffError() ? 'en' : uiLanguage()">{{ t(handoffError()) }}</p> }
        @if (canLaunch()) {
          <p>{{ t("Up to six internal units may be reserved (one per selected source and one model attempt). Estimated USD ceiling is operator-price-based, not a provider charge. A failed or uncertain request is never replayed automatically.") }}</p>
          @if (!models().length || !accounts().length) { <p>{{ t("No eligible priced structured-output model and account are configured. Configure them before requesting synthesis.") }}</p> }
          @else {
            <form (submit)="create($event)">
              <label for="research-topic">{{ t("Selected topic (up to 240 characters)") }}</label>
              <input id="research-topic" lang="" name="topic" maxlength="480" required [value]="selectedTopic()" [readOnly]="!!topicReview()" />
              <label for="research-mapping">{{ t("Current reviewed intent/page mapping (optional)") }}</label>
              <select id="research-mapping" lang="" name="mapping_id" (change)="selectMapping($event)" [disabled]="!!topicReview()">
                <option value="" [selected]="selectedMapping() === null" [attr.lang]="uiLanguage()">{{ t("Standalone user-selected topic") }}</option>
                @for (mapping of mappings(); track mapping.review_id) {
                  <option lang="" [value]="mapping.review_id" [selected]="mapping.review_id === selectedMapping()">{{ mapping.label }} · {{ mapping.language }} · {{ mapping.page_kind }} {{ t("(revision") }} {{ mapping.revision }})</option>
                }
              </select>
              <label for="research-language">{{ t("Project SEO language") }}</label>
              <select lang="en" id="research-language" name="language" required [disabled]="!!topicReview()">
                <option value="" [attr.lang]="uiLanguage()">{{ t("Select a configured language") }}</option>
                @for (language of languages(); track language) { <option lang="en" [value]="language" [selected]="language === selectedLanguage()">{{ language }}</option> }
              </select>
              <label for="research-urls">{{ t("Explicit approved HTTPS source URLs, one per line (maximum five; no query strings)") }}</label>
              <textarea id="research-urls" lang="" name="source_urls" rows="5" maxlength="5200" required [value]="selectedSources()"></textarea>
              <label for="research-model">{{ t("Priced structured-output model") }}</label>
              <select id="research-model" lang="" name="model_id" required (change)="selectModel($event)">
                <option value="" [attr.lang]="uiLanguage()">{{ t("Choose a model") }}</option>
                @for (model of models(); track model.id) {
                  <option lang="" [value]="model.id" [disabled]="!model.price_known || model.access_tier === 'unknown'">{{ model.name }} ({{ model.access_tier }}){{ model.price_known ? '' : t(' — price unavailable') }}</option>
                }
              </select>
              <label for="research-account">{{ t("Matching provider account") }}</label>
              <select id="research-account" lang="" name="account_id" required>
                <option value="" [attr.lang]="uiLanguage()">{{ t("Choose an account") }}</option>
                @for (account of availableAccounts(); track account.id) { <option lang="" [value]="account.id">{{ account.label }} ({{ account.source }})</option> }
              </select>
              @if (selectedModelTier() === 'free') {
                <p>{{ t("Free-model retention, training, rate and reliability may differ. Review the") }}
                  <a [href]="selectedPolicy()" target="_blank" rel="noopener noreferrer">{{ t("provider data-use policy") }}</a>.</p>
                <label for="research-free"><input id="research-free" type="checkbox" name="allow_free" required />{{ t("I explicitly opt in to free-tier processing for this request.") }}</label>
              }
              <label for="research-tokens">{{ t("Maximum output tokens (128–2048)") }}</label>
              <input id="research-tokens" name="max_output_tokens" type="number" min="128" max="2048" value="512" required />
              <label for="research-cost">{{ t("Maximum estimated USD cost (greater than zero, up to 100)") }}</label>
              <input id="research-cost" name="max_cost_usd" inputmode="decimal" pattern="[0-9]{1,3}(\\.[0-9]{1,6})?" required />
              <button type="submit" [disabled]="busy() || !!handoffError()">{{ t("Reserve work and collect sources") }}</button>
            </form>
          }
        } @else { <p>{{ t("You may view research evidence but cannot launch research for this project.") }}</p> }
        <section aria-labelledby="research-history-title">
          <h2 id="research-history-title">{{ t("Recent research jobs") }}</h2>
          <button type="button" [disabled]="busy()" (click)="load()">{{ t("Refresh project jobs") }}</button>
          @if (!history().length) { <p>{{ t("No research job is recorded for this project.") }}</p> }
          <ul>@for (item of history(); track item.id) {
            <li><span lang="">{{ item.topic }}</span> · <span lang="en">{{ item.status }} · {{ item.updated_at }}</span>
              <button type="button" [disabled]="busy()" (click)="open(item.id)">{{ t("Inspect job") }} {{ item.id }}</button></li>
          }</ul>
          @if (hasMore()) { <p>{{ t("Only the 20 most recent jobs are shown.") }}</p> }
        </section>
        @if (job(); as current) {
          <section aria-labelledby="research-result-title">
            <h2 id="research-result-title">{{ t("Job") }} {{ current.id }} · <span lang="en">{{ current.status }}</span></h2>
            <p role="status">{{ t("Updated") }} <span lang="en">{{ current.updated_at }}</span>{{ t("; attempted units") }} {{ current.attempted_units }} {{ t("of up to") }} {{ current.estimate_units }}.
              {{ t("Estimated maximum USD") }} {{ current.estimated_max_cost_usd ?? t('unknown') }}{{ t("; provider reported charge") }} {{ current.usage?.reported_cost_usd ?? t('unknown') }}.</p>
            @if (!current.context_current) { <p role="alert">{{ t("The current mapping or project configuration changed. These are historical observations; refresh sources before using them.") }}</p> }
            @if (current.error_category) { <p role="alert">{{ t("Issue:") }} <span lang="en">{{ current.error_category }}</span>{{ t(". Missing evidence is not a negative finding.") }}</p> }
            @if (current.usage) { <p>{{ t("Provider attempt:") }} <span lang="en">{{ current.usage.request_status }}</span>{{ t("; estimated from reported tokens USD") }} {{ current.usage.estimated_cost_usd ?? t('unknown') }}.</p> }
            <button type="button" (click)="open(current.id)" [disabled]="busy()">{{ t("Refresh this job") }}</button>
            @if (canLaunch() && ['queued', 'running'].includes(current.status) && !current.cancel_requested) {
              <button type="button" (click)="cancel()" [disabled]="busy()">{{ t("Request cancellation") }}</button>
            }
            @if (current.evidence; as evidence) {
              <p>{{ t("Coverage:") }} <span lang="en">{{ evidence.coverage }}</span>{{ t(". Source collection was limited to explicitly selected URLs; provider search") }} <span lang="en">{{ evidence.provider_search }}</span>.</p>
              <ol>@for (source of evidence.sources; track source.index) {
                <li>{{ t("Source") }} {{ source.index + 1 }} · <span lang="en">{{ source.state }}</span> · <span [attr.lang]="source.retrieved_at ? 'en' : uiLanguage()">{{ source.retrieved_at || t('date unavailable') }}</span>.
                  @if (source.state === 'collected' && source.url && source.sha256) {
                    @if (safeSourceUrl(source.url); as href) { <a [href]="href" target="_blank" rel="noopener noreferrer" lang="">{{ source.title || source.url }}</a> }
                    <p>{{ t("Observed byte SHA-256") }} <span lang="en">{{ source.sha256 }}</span>{{ t(". Excerpt (not verified as fact):") }} <span lang="">{{ source.excerpt }}</span></p>
                  } @else { <span [attr.lang]="source.error_category ? 'en' : uiLanguage()"> {{ source.error_category || t('unavailable') }}.</span> }
                </li>
              }</ol>
              @if (evidence.synthesis; as synthesis) {
                <h3>{{ t("AI interpretation · requires human review") }}</h3>
                <p lang="">{{ synthesis.summary }}</p>
                <ol>@for (claim of synthesis.claims; track $index) {
                  <li><span lang="">{{ claim.text }}</span> {{ t("· source") }} {{ claim.source_index + 1 }} {{ t("· exact excerpt:") }} <q lang="">{{ claim.quote }}</q>{{ t(". Verify before using this claim.") }}</li>
                }</ol>
              } @else { <p>{{ t("No AI synthesis is available; source collection alone does not establish a conclusion.") }}</p> }
            }
          </section>
        }
        @if (message()) { <p role="status" [attr.lang]="t(message()) === message() ? 'en' : uiLanguage()">{{ t(message()) }}</p> }
      }
    </section>
  `,
  styles: `label { display:block; margin-block:.6rem .2rem } input, textarea, select { max-width:100%; width:min(100%,42rem) } section { overflow-wrap:anywhere } button { margin:.6rem .6rem .6rem 0 }`,
})
export class ProjectResearch implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  t(text: string) { return this.uiLanguage() === 'tr' ? projectResearchTurkish[text] ?? text : text; }
  organizationId = 0;
  projectId = 0;
  private generation = 0;
  readonly loading = signal(true);
  readonly busy = signal(false);
  readonly error = signal('');
  readonly message = signal('');
  readonly projectName = signal('');
  readonly canLaunch = signal(false);
  readonly models = signal<Model[]>([]);
  readonly accounts = signal<Account[]>([]);
  readonly languages = signal<string[]>([]);
  readonly mappings = signal<{ review_id: number; label: string; language: string; page_kind: string; revision: number }[]>([]);
  readonly selectedModel = signal<number | null>(null);
  readonly selectedMapping = signal<number | null>(null);
  readonly selectedTopic = signal('');
  readonly selectedLanguage = signal('');
  readonly selectedSources = signal('');
  readonly topicReview = signal<TopicReview | null>(null);
  readonly handoffError = signal('');
  readonly history = signal<History[]>([]);
  readonly hasMore = signal(false);
  readonly job = signal<ResearchJob | null>(null);

  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi,
              private readonly destroy: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t('Sourced topic research')} — OrganicSEOOps`));
    destroy.onDestroy(() => { this.generation++; }); }

  ngOnInit() {
    void this.loadProductLanguage();
    combineLatest([this.route.paramMap, this.route.queryParamMap]).pipe(takeUntilDestroyed(this.destroy)).subscribe(([params]) => {
      this.organizationId = Number(params.get('organizationId'));
      this.projectId = Number(params.get('projectId'));
      this.generation++;
      this.projectName.set(''); this.canLaunch.set(false); this.models.set([]); this.accounts.set([]);
      this.languages.set([]); this.mappings.set([]); this.selectedModel.set(null); this.selectedMapping.set(null);
      this.selectedTopic.set(''); this.selectedLanguage.set(''); this.selectedSources.set(''); this.topicReview.set(null); this.handoffError.set(''); this.history.set([]); this.hasMore.set(false);
      this.job.set(null); this.error.set(''); this.message.set(''); this.busy.set(false);
      if (Number.isSafeInteger(this.organizationId) && this.organizationId > 0 && Number.isSafeInteger(this.projectId) && this.projectId > 0) void this.load();
      else { this.loading.set(false); this.error.set('Select a current project.'); }
    });
  }

  private async loadProductLanguage() {
    try {
      const result = await this.api.productLanguage();
      if (!this.destroy.destroyed && result.status === 200 && isProductLanguageResult(result.body)) {
        this.productLanguage.set(result.body['language']);
      }
    } catch { /* Keep English when the private preference is unavailable. */ }
  }

  selectedModelTier() { return this.models().find((model) => model.id === this.selectedModel())?.access_tier; }
  selectedPolicy() { return this.models().find((model) => model.id === this.selectedModel())?.privacy_policy_url || ''; }
  availableAccounts() { return this.accounts().filter((account) => account.provider_id === this.models().find((model) => model.id === this.selectedModel())?.provider_id); }
  safeSourceUrl(value: string) { return safeSourceUrl(value); }
  selectModel(event: Event) { this.selectedModel.set(Number((event.target as HTMLSelectElement).value) || null); }
  selectMapping(event: Event) {
    const mapping = this.mappings().find((row) => row.review_id === Number((event.target as HTMLSelectElement).value));
    this.selectedMapping.set(mapping?.review_id ?? null);
    if (mapping) { this.selectedTopic.set(mapping.label); this.selectedLanguage.set(mapping.language); }
  }
  detachTopic() { this.topicReview.set(null); this.handoffError.set(''); }

  async load() {
    const generation = ++this.generation;
    this.loading.set(true); this.error.set(''); this.job.set(null);
    this.canLaunch.set(false); this.models.set([]); this.accounts.set([]); this.selectedModel.set(null);
    this.history.set([]); this.hasMore.set(false);
    this.topicReview.set(null); this.handoffError.set(''); this.selectedSources.set('');
    this.selectedMapping.set(null); this.selectedTopic.set(''); this.selectedLanguage.set(''); this.mappings.set([]);
    try {
      const context = await this.api.projectOnboarding(this.organizationId, this.projectId);
      if (generation !== this.generation) return;
      const project = context.body['project'] as Record<string, unknown> | undefined;
      if (context.status !== 200 || project?.['id'] !== this.projectId || project['organization_id'] !== this.organizationId
        || typeof project['role'] !== 'string' || !['owner', 'admin', 'member', 'viewer'].includes(project['role'])) throw new Error();
      this.projectName.set(String(project['name']));
      this.canLaunch.set(typeof project['role'] === 'string' && ['owner', 'admin', 'member'].includes(project['role']));
      const [response, reviews] = await Promise.all([this.api.projectResearch(this.organizationId, this.projectId),
        this.api.intentClusters(this.organizationId, this.projectId)]);
      if (generation !== this.generation) return;
      const body = response.body;
      if (response.status !== 200 || body['project_id'] !== this.projectId || !Array.isArray(body['models'])
          || !Array.isArray(body['accounts']) || !Array.isArray(body['languages']) || !Array.isArray(body['jobs'])
          || body['source_scope'] !== 'explicit_configured_https_origins_only') throw new Error();
      this.models.set((body['models'] as Model[]).filter((item) => item && Number.isSafeInteger(item.id) && item.id > 0
        && Number.isSafeInteger(item.provider_id) && item.provider_id > 0
        && typeof item.name === 'string' && !!item.name.trim() && Array.from(item.name).length <= 120
        && (item.max_output_tokens === null || Number.isSafeInteger(item.max_output_tokens) && item.max_output_tokens >= 1 && item.max_output_tokens <= 10000000)
        && typeof item.privacy_policy_url === 'string' && Array.from(item.privacy_policy_url).length <= 1024
        && (item.privacy_policy_url === '' ? item.access_tier !== 'free' : !!this.safeSourceUrl(item.privacy_policy_url))
        && typeof item.access_tier === 'string' && ['unknown', 'standard', 'free'].includes(item.access_tier) && typeof item.price_known === 'boolean'));
      this.accounts.set((body['accounts'] as Account[]).filter((item) => item && Number.isSafeInteger(item.id) && item.id > 0
        && Number.isSafeInteger(item.provider_id) && item.provider_id > 0
        && typeof item.label === 'string' && !!item.label.trim() && Array.from(item.label).length <= 80
        && typeof item.source === 'string' && ['platform', 'organization'].includes(item.source)));
      this.languages.set((body['languages'] as unknown[]).filter((item): item is string => typeof item === 'string'));
      this.history.set((body['jobs'] as History[]).filter((item) => item && Number.isSafeInteger(item.id) && item.id > 0
        && item.project_id === this.projectId
        && typeof item.status === 'string' && ['queued', 'running', 'waiting_provider', 'succeeded', 'failed', 'cancelled', 'partially_succeeded'].includes(item.status)
        && typeof item.topic === 'string' && typeof item.updated_at === 'string'));
      this.hasMore.set(body['has_more'] === true);
      if (reviews.status === 200 && reviews.body['project_id'] === this.projectId && Array.isArray(reviews.body['clusters'])) {
        this.mappings.set((reviews.body['clusters'] as Record<string, unknown>[]).filter((row) => row && row['source_current'] === true
          && Number.isSafeInteger(row['review_id']) && Number(row['review_id']) > 0
          && typeof row['label'] === 'string' && !!row['label'].trim() && Array.from(row['label']).length <= 120
          && typeof row['language'] === 'string' && ['unmapped', 'proposed', 'existing_unverified'].includes(row['page_kind'] as string)
          && Number.isSafeInteger(row['revision']) && Number(row['revision']) > 0 && Number(row['revision']) <= 32767) as { review_id: number; label: string; language: string;
            page_kind: string; revision: number }[]);
      }
      const requested = Number(this.route.snapshot.queryParamMap.get('mapping'));
      const selected = this.mappings().find((item) => item.review_id === requested);
      if (selected) { this.selectedMapping.set(selected.review_id); this.selectedTopic.set(selected.label); this.selectedLanguage.set(selected.language); }
      const requestedReview = this.route.snapshot.queryParamMap.get('topic_review');
      if (requestedReview !== null) {
        const id = Number(requestedReview);
        if (!Number.isSafeInteger(id) || id < 1) {
          this.handoffError.set('Invalid topic selection. Return to topic review and choose current evidence.');
        } else {
          const result = await this.api.projectTopicReview(this.organizationId, this.projectId, id);
          if (generation !== this.generation) return;
          const review = result.body['review'] as TopicReview | undefined;
          const evidence = result.body['evidence'] as Record<string, unknown> | undefined;
          if (result.status !== 200 || result.body['project_id'] !== this.projectId || result.body['source_current'] !== true
            || review?.id !== id || review.project_id !== this.projectId || !this.languages().includes(review.language)
            || !Number.isSafeInteger(review.revision) || review.revision < 1 || review.revision > 2147483647
            || typeof review.classification !== 'string' || !['unknown', 'trending', 'evergreen'].includes(review.classification)
            || typeof review.label !== 'string' || !review.label.trim() || Array.from(review.label).length > 240
            || review.intent_review_id !== null && !this.mappings().some((row) => row.review_id === review.intent_review_id)) {
            this.selectedTopic.set(''); this.selectedMapping.set(null); this.selectedLanguage.set('');
            this.handoffError.set('Selected topic review or source changed or is unavailable. Return to topic review; research is blocked until a current selection is loaded.');
          } else {
            this.topicReview.set(review); this.selectedTopic.set(review.label); this.selectedLanguage.set(review.language); this.selectedMapping.set(review.intent_review_id);
            this.selectedSources.set(typeof evidence?.['url'] === 'string' ? this.safeSourceUrl(evidence['url']) : '');
          }
        }
      }
    } catch { if (generation === this.generation) { this.canLaunch.set(false); this.error.set('Current project research context is unavailable or access was revoked.'); } }
    finally { if (generation === this.generation) this.loading.set(false); }
  }

  async create(event: Event) {
    event.preventDefault();
    const form = event.target as HTMLFormElement;
    if (this.busy() || !this.canLaunch() || this.handoffError() || !form.reportValidity()) return;
    const input = new FormData(form);
    const topic = this.topicReview()?.label ?? String(input.get('topic') || '').trim();
    if (!topic || Array.from(topic).length > 240) { this.message.set('Choose a topic of 1–240 characters.'); return; }
    const sources = String(input.get('source_urls') || '').split('\n').map((item) => item.trim()).filter(Boolean);
    const model = this.models().find((item) => item.id === Number(input.get('model_id')));
    const account = this.availableAccounts().find((item) => item.id === Number(input.get('account_id')));
    const tokens = Number(input.get('max_output_tokens'));
    if (!sources.length || sources.length > 5 || !model?.price_known || model.access_tier === 'unknown' || !account || account.provider_id !== model.provider_id || !Number.isSafeInteger(tokens)
        || tokens < 128 || tokens > 2048 || (model.max_output_tokens !== null && tokens > model.max_output_tokens)
        || model.access_tier === 'free' && !input.has('allow_free')) { this.message.set('Choose up to five approved sources and a permitted model budget.'); return; }
    const generation = this.generation;
    this.busy.set(true); this.message.set('');
    try {
      const result = await this.api.queueProjectResearch(this.organizationId, this.projectId, {
        topic, language: this.topicReview()?.language ?? String(input.get('language') || ''),
        mapping_id: this.topicReview() ? this.topicReview()!.intent_review_id : input.get('mapping_id') ? Number(input.get('mapping_id')) : null, source_urls: sources,
        ...(this.topicReview() ? { topic_review_id: this.topicReview()!.id } : {}),
        model_id: model.id, account_id: account.id, max_output_tokens: tokens,
        max_cost_usd: String(input.get('max_cost_usd')), allow_free: model.access_tier === 'free',
        idempotency_key: crypto.randomUUID().replaceAll('-', ''),
      });
      if (generation !== this.generation) return;
      const job = result.body['job'];
      if (result.status !== 202 || result.body['project_id'] !== this.projectId || !isJob(job, this.projectId)) throw new Error();
      this.job.set(job); this.message.set('Research queued. Refresh this job to check collection and synthesis; a provider attempt cannot be replayed blindly.');
    } catch { if (generation === this.generation) this.message.set('Research request unavailable. Refresh history before creating another request.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }

  async open(id: number) {
    if (this.busy() || !Number.isSafeInteger(id) || id <= 0) return;
    const generation = this.generation;
    this.busy.set(true); this.message.set('');
    try {
      const response = await this.api.projectResearchJob(this.organizationId, this.projectId, id);
      if (generation !== this.generation) return;
      if (response.status !== 200 || response.body['project_id'] !== this.projectId
        || !isJob(response.body['job'], this.projectId) || response.body['job'].id !== id) throw new Error();
      this.job.set(response.body['job']);
    } catch { if (generation === this.generation) { this.job.set(null); this.message.set('Research job unavailable or permission was revoked.'); } }
    finally { if (generation === this.generation) this.busy.set(false); }
  }

  async cancel() {
    const current = this.job();
    if (!current || this.busy() || !this.canLaunch()) return;
    const generation = this.generation;
    this.busy.set(true); this.message.set('');
    try {
      const response = await this.api.projectResearchJob(this.organizationId, this.projectId, current.id, true);
      if (generation !== this.generation) return;
      if (response.status !== 200 || response.body['project_id'] !== this.projectId
        || !isJob(response.body['job'], this.projectId) || response.body['job'].id !== current.id) throw new Error();
      this.job.set(response.body['job']); this.message.set('Cancellation requested; the worker rechecks at source and synthesis boundaries.');
    } catch { if (generation === this.generation) { this.job.set(null); this.message.set('Cancellation outcome unavailable; refresh job status.'); } }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
}

function isJob(value: unknown, projectId: number): value is ResearchJob {
  if (!value || typeof value !== 'object') return false;
  const job = value as Record<string, unknown>;
  const usage = job['usage'] as Record<string, unknown> | null;
  return Number.isSafeInteger(job['id']) && Number(job['id']) > 0 && job['project_id'] === projectId
    && typeof job['status'] === 'string' && ['queued', 'running', 'succeeded', 'failed', 'cancelled', 'partially_succeeded'].includes(job['status'])
    && typeof job['topic'] === 'string' && typeof job['updated_at'] === 'string'
    && typeof job['error_category'] === 'string'
    && Number.isSafeInteger(job['estimate_units']) && Number(job['estimate_units']) >= 2 && Number(job['estimate_units']) <= 6
    && Number.isSafeInteger(job['attempted_units']) && Number(job['attempted_units']) >= 0 && Number(job['attempted_units']) <= Number(job['estimate_units'])
    && (job['estimated_max_cost_usd'] === null || typeof job['estimated_max_cost_usd'] === 'string')
    && typeof job['cancel_requested'] === 'boolean' && typeof job['context_current'] === 'boolean'
    && (usage === null || !!usage && typeof usage === 'object' && typeof usage['request_status'] === 'string'
      && ['attempted', 'completed', 'failed', 'unknown'].includes(usage['request_status'])
      && (usage['estimated_cost_usd'] === null || typeof usage['estimated_cost_usd'] === 'string')
      && (usage['reported_cost_usd'] === null || typeof usage['reported_cost_usd'] === 'string'))
    && (job['evidence'] === null || isEvidence(job['evidence'], Number(job['estimate_units']) - 1));
}

function safeSourceUrl(value: unknown) {
  if (typeof value !== 'string') return '';
  try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password
    && !url.search && !url.hash && (!url.port || url.port === '443') ? url.href : ''; }
  catch { return ''; }
}

function isEvidence(value: unknown, sourceCount: number): boolean {
  if (!value || typeof value !== 'object') return false;
  const evidence = value as Record<string, unknown>;
  if (typeof evidence['coverage'] !== 'string' || !['no_sources', 'partial', 'collected_selected_sources_only'].includes(evidence['coverage'])
    || evidence['provider_search'] !== 'not_used_explicit_urls_only' || !Array.isArray(evidence['sources'])
    || evidence['sources'].length > sourceCount) return false;
  const sources = evidence['sources'] as Record<string, unknown>[];
  if (!sources.every((source, position) => source && Number.isSafeInteger(source['index']) && Number(source['index']) >= 0
    && Number(source['index']) < sourceCount && (position === 0 || Number(source['index']) > Number(sources[position - 1]['index']))
    && (source['state'] === 'unavailable' ? typeof source['error_category'] === 'string'
      && (source['retrieved_at'] === undefined || typeof source['retrieved_at'] === 'string')
      : source['state'] === 'collected' && typeof source['url'] === 'string' && source['url'].length <= 1024 && !!safeSourceUrl(source['url'])
      && typeof source['title'] === 'string' && Array.from(source['title']).length <= 240
      && typeof source['excerpt'] === 'string' && source['excerpt'].length > 0 && Array.from(source['excerpt']).length <= 2048
      && typeof source['sha256'] === 'string' && /^[a-f0-9]{64}$/.test(source['sha256'])
      && typeof source['retrieved_at'] === 'string' && !!source['retrieved_at']))) return false;
  if (evidence['synthesis'] === null) return evidence['synthesis_state'] === 'unavailable';
  const synthesis = evidence['synthesis'] as Record<string, unknown> | undefined;
  return evidence['synthesis_state'] === 'ai_draft_requires_human_review' && !!synthesis
    && typeof synthesis['summary'] === 'string' && synthesis['summary'].length > 0 && Array.from(synthesis['summary']).length <= 3000
    && Array.isArray(synthesis['claims']) && synthesis['claims'].length > 0 && synthesis['claims'].length <= 10
    && synthesis['claims'].every((claim: Record<string, unknown>) => {
      if (!claim || typeof claim['text'] !== 'string' || !claim['text'].length || Array.from(claim['text']).length > 500
        || !Number.isSafeInteger(claim['source_index']) || typeof claim['quote'] !== 'string'
        || !claim['quote'].trim() || Array.from(claim['quote'].trim()).length > 300) return false;
      const source = sources.find((row) => row['index'] === claim['source_index'] && row['state'] === 'collected');
      return !!source && (source['excerpt'] as string).includes(claim['quote']);
    });
}
