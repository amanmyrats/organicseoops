import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, OnInit, computed, effect, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi } from '../account/account-api';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';

type Prompt = { key: string; kind: string; text: string; intent_review_id: number };
type PromptSet = { id: number; project_id: number; set_id: string; revision: number; label: string; market: string;
  language: string; prompts: Prompt[]; review_note: string; policy: { max_output_tokens: number; max_cost_usd: string };
  source_current: boolean; created_at: string; collection_available: boolean };
type Mapping = { review_id: number; label: string; language: string; market: string; source_current: boolean };

const visibilityPromptsTurkish: Record<string, string> = {
  "API-only visibility prompt methodology": "Yalnızca API görünürlüğü istem metodolojisi",
  "API-text visibility prompt methodology": "API metni görünürlüğü istem metodolojisi",
  "Return to project evidence": "Proje kanıtlarına dönün",
  "Review genuine customer intents": "Gerçek müşteri niyetlerini inceleyin",
  "Configure brands, market and SEO languages": "Markaları, pazarı ve SEO dillerini yapılandırın",
  "Native OpenAI Responses API text-only methodology; not consumer ChatGPT observations or global AI visibility. Saving a set never calls a provider, selects a model, reserves usage or schedules work.": "Yerel OpenAI Responses API yalnızca metin metodolojisi; tüketici ChatGPT gözlemleri veya küresel AI görünürlüğü değildir. Bir küme kaydetmek hiçbir zaman sağlayıcıyı çağırmaz, model seçmez, kullanım ayırmaz veya iş zamanlamaz.",
  "Select one reviewed prompt for a bounded manual API sample": "Sınırlı manuel API örneği için incelenmiş bir istem seçin",
  "Comparable observation history": "Karşılaştırılabilir gözlem geçmişi",
  "Separate independently permitted human reports": "Bağımsız olarak izin verilmiş ayrı insan raporları",
  "Future samples use one unchanged human-authored prompt per explicit user request, a user-selected standard-access model/account and one internal unit. Repeat only manually, at least 24 hours per set/prompt; no automatic schedule/fallback/retry. No tools, retrieval or citation measurement. Device/location controls are unsupported; requested market/language are human context, not guaranteed applied provider settings. A later sample cannot establish visits or global consumer-chat coverage.": "Gelecekteki örnekler her açık kullanıcı isteğinde değiştirilmemiş, insan tarafından yazılmış tek bir istem, kullanıcının seçtiği standart erişimli model/hesap ve bir dahili birim kullanır. Her küme/istem için en az 24 saat arayla yalnızca manuel tekrar; otomatik zamanlama/yedek seçenek/yeniden deneme yoktur. Araç, bilgi getirme veya atıf ölçümü yoktur. Cihaz/konum kontrolleri desteklenmez; istenen pazar/dil insan bağlamıdır, sağlayıcının uygulayacağı garantili ayarlar değildir. Daha sonraki bir örnek ziyaretleri veya küresel tüketici sohbeti kapsamını kanıtlayamaz.",
  "Private prompts and future answers follow the organization's customer export/retention/deletion/backup policy. Provider store:false is not Zero Data Retention; provider abuse monitoring can retain content up to 30 days with legal/safety exceptions, and prompt caches may retain application state up to 24 hours. Keep secrets, personal data and customer exports out of prompts. Actual account terms/privacy and provider readiness remain unverified.": "Özel istemler ve gelecekteki yanıtlar kuruluşun müşteri dışa aktarım/saklama/silme/yedekleme politikasına tabidir. Sağlayıcı store:false ayarı Sıfır Veri Saklama değildir; sağlayıcının kötüye kullanım izlemesi içeriği yasal/güvenlik istisnalarıyla 30 güne kadar saklayabilir ve istem önbellekleri uygulama durumunu 24 saate kadar saklayabilir. Sırları, kişisel verileri ve müşteri dışa aktarımlarını istemlere koymayın. Gerçek hesap koşulları/gizlilik ve sağlayıcı hazırlığı henüz doğrulanmamıştır.",
  "Provider data controls": "Sağlayıcı veri kontrolleri",
  "Loading current project methodology.": "Güncel proje metodolojisi yükleniyor.",
  "Active project:": "Aktif proje:",
  "(organization": "(kuruluş",
  "). Requested market:": "). İstenen pazar:",
  ". Configured brand aliases:": ". Yapılandırılmış marka takma adları:",
  ". Human review is not measured demand or certified neutrality.": ". İnsan incelemesi ölçülmüş talep veya onaylanmış tarafsızlık değildir.",
  "Reviewed prompt sets": "İncelenmiş istem kümeleri",
  "· revision": "· revizyon",
  "Inspect history for": "Geçmişi inceleyin:",
  "No reviewed methodology. No sample/measurement exists.": "İncelenmiş metodoloji yok. Örnek/ölçüm yoktur.",
  "Only twenty recent sets are shown.": "Yalnızca son yirmi küme gösterilir.",
  "Immutable methodology history": "Değiştirilemez metodoloji geçmişi",
  "Revision": "Revizyon",
  "Requested": "İstenen",
  "· up to": "· en fazla",
  "output tokens/USD": "çıktı tokeni/USD",
  "estimated per future request.": "gelecekteki istek başına tahmin edilir.",
  "· human intent review": "· insan niyeti incelemesi",
  "More than twenty revisions exist; this history page is bounded.": "Yirmiden fazla revizyon var; bu geçmiş sayfası sınırlıdır.",
  "Neutral discovery must omit configured brand/domain terms; branded prompts must name one. This lexical check is conservative, not semantic proof. Explain genuine intent coverage and any leading/bias limits.": "Tarafsız keşif yapılandırılmış marka/alan adı terimlerini içermemeli; markalı istemler bunlardan birini belirtmelidir. Bu sözcüksel kontrol ihtiyatlıdır, anlamsal kanıt değildir. Gerçek niyet kapsamını ve yönlendirme/yanlılık sınırlamalarını açıklayın.",
  "Methodology label": "Metodoloji etiketi",
  "Requested SEO language": "İstenen SEO dili",
  "Choose current language": "Güncel dili seçin",
  "Human prompt": "İnsan istemi",
  "Stable prompt key": "Kalıcı istem anahtarı",
  "Separate group": "Ayrı grup",
  "Neutral discovery": "Tarafsız keşif",
  "Explicitly branded/leading": "Açıkça markalı/yönlendirici",
  "Exact-current human intent review": "Tam güncel insan niyeti incelemesi",
  "Choose current intent coverage": "Güncel niyet kapsamını seçin",
  "· review": "· inceleme",
  "Exact prompt text (unchanged when later sampled)": "Tam istem metni (daha sonra örneklenirken değiştirilmez)",
  "Remove prompt": "İstemi kaldırın:",
  "Add human prompt (up to five)": "İnsan istemi ekleyin (en fazla beş)",
  "Future per-request output-token ceiling (1–256)": "Gelecekteki istek başına çıktı tokeni üst sınırı (1–256)",
  "Future per-request maximum estimated USD (positive, up to 100)": "Gelecekteki istek başına azami tahmini USD (pozitif, en fazla 100)",
  "Human intent coverage and neutrality/bias rationale": "İnsan niyeti kapsamı ve tarafsızlık/yanlılık gerekçesi",
  "I reviewed these intents, separate neutral/branded prompts and API-only privacy/budget/measurement limits.": "Bu niyetleri, ayrı tarafsız/markalı istemleri ve yalnızca API gizlilik/bütçe/ölçüm sınırlarını inceledim.",
  "Save immutable human review (no collection)": "Değiştirilemez insan incelemesini kaydedin (toplama yok)",
  "Prompt review needs owner/admin role and configured current brands, market, languages and intent coverage.": "İstem incelemesi sahip/yönetici rolü ve yapılandırılmış güncel markalar, pazar, diller ve niyet kapsamı gerektirir.",
  "Start a new methodology": "Yeni bir metodoloji başlatın",
  "Refresh current project methodology": "Güncel proje metodolojisini yenileyin",
  "not configured": "yapılandırılmamış",
  "current source context": "güncel kaynak bağlamı",
  "source/methodology changed": "kaynak/metodoloji değişti",
  "current": "güncel",
  "historical/stale": "geçmiş/güncelliğini yitirmiş",
  "Append a reviewed correction": "İncelenmiş bir düzeltme ekleyin",
  "Create a reviewed prompt set": "İncelenmiş bir istem kümesi oluşturun",
  "Current project methodology unavailable or access revoked.": "Güncel proje metodolojisi kullanılamıyor veya erişim iptal edildi.",
  "Methodology history unavailable; refresh current context.": "Metodoloji geçmişi kullanılamıyor; güncel bağlamı yenileyin.",
  "Immutable human methodology saved. No sample collected, no model selected and no usage consumed.": "Değiştirilemez insan metodolojisi kaydedildi. Örnek toplanmadı, model seçilmedi ve kullanım tüketilmedi.",
  "Review not confirmed. Reload latest revision/current intent; check neutral/branded wording, role and budgets.": "İnceleme doğrulanmadı. Son revizyonu/güncel niyeti yeniden yükleyin; tarafsız/markalı ifadeleri, rolü ve bütçeleri kontrol edin.",
  "Unreviewed Turkish prompt-methodology interface draft in local development. Human prompts and source context retain their original language; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe istem metodolojisi arayüzü taslağı. İnsan istemleri ve kaynak bağlamı özgün dillerini korur; iki dilli onay bekleniyor."
};

@Component({
  selector: 'app-visibility-prompts', imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="visibility-title">
      <h1 id="visibility-title">{{ t("API-text visibility prompt methodology") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish prompt-methodology interface draft in local development. Human prompts and source context retain their original language; bilingual approval is pending.") }}</p> }
      <p><a [routerLink]="['/app/dashboard', organizationId, projectId]">{{ t("Return to project evidence") }}</a> ·
        <a [routerLink]="['/app/intent', organizationId, projectId]">{{ t("Review genuine customer intents") }}</a> ·
        <a [routerLink]="['/app/onboarding', organizationId, projectId]">{{ t("Configure brands, market and SEO languages") }}</a></p>
      <p>{{ t("Native OpenAI Responses API text-only methodology; not consumer ChatGPT observations or global AI visibility. Saving a set never calls a provider, selects a model, reserves usage or schedules work.") }}
        <a [routerLink]="['/app/visibility-samples', organizationId, projectId]">{{ t("Select one reviewed prompt for a bounded manual API sample") }}</a> ·
        <a [routerLink]="['/app/visibility-history', organizationId, projectId]">{{ t("Comparable observation history") }}</a> ·
        <a [routerLink]="['/app/visibility-manual', organizationId, projectId]">{{ t("Separate independently permitted human reports") }}</a>.</p>
      <p>{{ t("Future samples use one unchanged human-authored prompt per explicit user request, a user-selected standard-access model/account and one internal unit. Repeat only manually, at least 24 hours per set/prompt; no automatic schedule/fallback/retry. No tools, retrieval or citation measurement. Device/location controls are unsupported; requested market/language are human context, not guaranteed applied provider settings. A later sample cannot establish visits or global consumer-chat coverage.") }}</p>
      <p>{{ t("Private prompts and future answers follow the organization's customer export/retention/deletion/backup policy. Provider store:false is not Zero Data Retention; provider abuse monitoring can retain content up to 30 days with legal/safety exceptions, and prompt caches may retain application state up to 24 hours. Keep secrets, personal data and customer exports out of prompts. Actual account terms/privacy and provider readiness remain unverified.") }}
        <a href="https://developers.openai.com/api/docs/guides/your-data" target="_blank" rel="noopener noreferrer">{{ t("Provider data controls") }}</a>.</p>
      @if (loading()) { <p role="status">{{ t("Loading current project methodology.") }}</p> }
      @if (error()) { <p role="alert" [attr.lang]="t(error()) === error() ? 'en' : uiLanguage()">{{ t(error()) }}</p> }
      @if (message()) { <p role="status">{{ t(message()) }}</p> }
      @if (ready()) {
        <p>{{ t("Active project:") }} <span lang="">{{ name() }}</span> {{ t("(organization") }} <span lang="en">{{ organizationId }}</span>{{ t("). Requested market:") }} <span lang="">{{ market() }}</span>{{ t(". Configured brand aliases:") }} <span [attr.lang]="brands().length ? '' : uiLanguage()">{{ brands().join(', ') || t("not configured") }}</span>{{ t(". Human review is not measured demand or certified neutrality.") }}</p>
        <h2>{{ t("Reviewed prompt sets") }}</h2>
        <ul>@for (row of sets(); track row.set_id) {
          <li><span lang="">{{ row.label }}</span> · <span lang="en">{{ row.language }}</span> {{ t("· revision") }} <span lang="en">{{ row.revision }}</span> · {{ row.source_current ? t("current source context") : t("source/methodology changed") }}
            <button type="button" [disabled]="busy()" (click)="open(row.set_id)">{{ t("Inspect history for") }} <span lang="">{{ row.label }}</span></button></li>
        } @empty { <li>{{ t("No reviewed methodology. No sample/measurement exists.") }}</li> }</ul>
        @if (hasMore()) { <p>{{ t("Only twenty recent sets are shown.") }}</p> }
        @if (history().length) {
          <h2>{{ t("Immutable methodology history") }}</h2>
          @for (row of history(); track row.id) {
            <details><summary>{{ t("Revision") }} <span lang="en">{{ row.revision }}</span> · <span lang="en">{{ row.created_at }}</span> · {{ row.source_current ? t("current") : t("historical/stale") }}</summary>
              <p><span lang="">{{ row.review_note }}</span></p><p>{{ t("Requested") }} <span lang="">{{ row.market }}</span>/<span lang="en">{{ row.language }}</span> {{ t("· up to") }} <span lang="en">{{ row.policy.max_output_tokens }}</span> {{ t("output tokens/USD") }} <span lang="en">{{ row.policy.max_cost_usd }}</span> {{ t("estimated per future request.") }}</p>
              <ul>@for (prompt of row.prompts; track prompt.key) {
                <li><span lang="en">{{ prompt.key }}</span> · <span lang="en">{{ prompt.kind }}</span> {{ t("· human intent review") }} <span lang="en">{{ prompt.intent_review_id }}</span><pre><span lang="">{{ prompt.text }}</span></pre></li>
              }</ul>
            </details>
          }
          @if (historyMore()) { <p>{{ t("More than twenty revisions exist; this history page is bounded.") }}</p> }
        }
        @if (canEdit() && brands().length && market()) {
          <h2>{{ selected() ? t("Append a reviewed correction") : t("Create a reviewed prompt set") }}</h2>
          <p>{{ t("Neutral discovery must omit configured brand/domain terms; branded prompts must name one. This lexical check is conservative, not semantic proof. Explain genuine intent coverage and any leading/bias limits.") }}</p>
          <form (submit)="save($event)">
            <label for="visibility-label">{{ t("Methodology label") }}</label><input lang="" id="visibility-label" name="label" maxlength="120" required [value]="selected()?.label || ''" />
            <label for="visibility-language">{{ t("Requested SEO language") }}</label><select id="visibility-language" name="language" required (change)="language.set($any($event.target).value)">
              <option value="">{{ t("Choose current language") }}</option>@for (item of languages(); track item) { <option lang="en" [value]="item" [selected]="item === language()">{{ item }}</option> }
            </select>
            @for (prompt of drafts(); track $index; let i = $index) {
              <fieldset><legend>{{ t("Human prompt") }} <span lang="en">{{ i + 1 }}</span></legend>
                <label [for]="'visibility-key-' + i">{{ t("Stable prompt key") }}</label><input lang="en" [id]="'visibility-key-' + i" required maxlength="32" pattern="[a-z][a-z0-9_-]{0,31}" [value]="prompt.key" (input)="change(i, 'key', $any($event.target).value)" />
                <label [for]="'visibility-kind-' + i">{{ t("Separate group") }}</label><select [id]="'visibility-kind-' + i" (change)="change(i, 'kind', $any($event.target).value)">
                  <option value="neutral" [selected]="prompt.kind === 'neutral'">{{ t("Neutral discovery") }}</option><option value="branded" [selected]="prompt.kind === 'branded'">{{ t("Explicitly branded/leading") }}</option>
                </select>
                <label [for]="'visibility-intent-' + i">{{ t("Exact-current human intent review") }}</label><select [id]="'visibility-intent-' + i" required (change)="change(i, 'intent_review_id', +$any($event.target).value)">
                  <option value="">{{ t("Choose current intent coverage") }}</option>@for (mapping of availableMappings(); track mapping.review_id) {
                    <option lang="" [value]="mapping.review_id" [selected]="mapping.review_id === prompt.intent_review_id">{{ mapping.label }} {{ t("· review") }} {{ mapping.review_id }}</option>
                  }
                </select>
                <label [for]="'visibility-text-' + i">{{ t("Exact prompt text (unchanged when later sampled)") }}</label><textarea lang="" [id]="'visibility-text-' + i" required maxlength="500" rows="4" [value]="prompt.text" (input)="change(i, 'text', $any($event.target).value)"></textarea>
                <button type="button" [disabled]="drafts().length === 1 || busy()" (click)="remove(i)">{{ t("Remove prompt") }} <span lang="en">{{ i + 1 }}</span></button>
              </fieldset>
            }
            <button type="button" [disabled]="drafts().length >= 5 || busy()" (click)="add()">{{ t("Add human prompt (up to five)") }}</button>
            <label for="visibility-tokens">{{ t("Future per-request output-token ceiling (1–256)") }}</label><input id="visibility-tokens" name="max_output_tokens" type="number" min="1" max="256" step="1" required [value]="selected()?.policy?.max_output_tokens ?? 128" />
            <label for="visibility-cost">{{ t("Future per-request maximum estimated USD (positive, up to 100)") }}</label><input id="visibility-cost" name="max_cost_usd" inputmode="decimal" maxlength="10" pattern="[0-9]{1,3}(\\.[0-9]{1,6})?" required [value]="selected()?.policy?.max_cost_usd || ''" />
            <label for="visibility-review-note">{{ t("Human intent coverage and neutrality/bias rationale") }}</label><textarea lang="" id="visibility-review-note" name="review_note" required maxlength="500" [value]="selected()?.review_note || ''"></textarea>
            <label><input name="acknowledge" type="checkbox" required /> {{ t("I reviewed these intents, separate neutral/branded prompts and API-only privacy/budget/measurement limits.") }}</label>
            <button type="submit" [disabled]="busy()">{{ t("Save immutable human review (no collection)") }}</button>
          </form>
        } @else { <p>{{ t("Prompt review needs owner/admin role and configured current brands, market, languages and intent coverage.") }}</p> }
        <button type="button" [disabled]="busy()" (click)="newSet()">{{ t("Start a new methodology") }}</button>
      }
      <button type="button" [disabled]="busy()" (click)="load()">{{ t("Refresh current project methodology") }}</button>
    </section>`,
  styles: `label { display:block; margin-block:.6rem .2rem } input:not([type=checkbox]),textarea,select { width:min(100%,42rem); max-width:100% } fieldset { min-width:0 } pre { white-space:pre-wrap } section,li { overflow-wrap:anywhere } button { margin:.6rem .6rem .6rem 0 }`,
})
export class VisibilityPrompts implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  t(text: string) { return this.uiLanguage() === 'tr' ? visibilityPromptsTurkish[text] ?? text : text; }
  organizationId = 0; projectId = 0; private generation = 0;
  readonly loading = signal(true); readonly ready = signal(false); readonly busy = signal(false); readonly error = signal(''); readonly message = signal('');
  readonly name = signal(''); readonly market = signal(''); readonly brands = signal<string[]>([]); readonly languages = signal<string[]>([]);
  readonly canEdit = signal(false); readonly sets = signal<PromptSet[]>([]); readonly history = signal<PromptSet[]>([]);
  readonly hasMore = signal(false); readonly historyMore = signal(false); readonly selected = signal<PromptSet | null>(null);
  readonly mappings = signal<Mapping[]>([]); readonly language = signal(''); readonly drafts = signal<Prompt[]>([]);
  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi, private readonly destroy: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t('API-only visibility prompt methodology')} — OrganicSEOOps`));
  }
  ngOnInit() { void this.loadProductLanguage(); this.route.paramMap.pipe(takeUntilDestroyed(this.destroy)).subscribe((params) => {
    this.organizationId = Number(params.get('organizationId')); this.projectId = Number(params.get('projectId')); void this.load();
  }); this.destroy.onDestroy(() => ++this.generation); }
  private async loadProductLanguage() {
    try {
      const result = await this.api.productLanguage();
      if (!this.destroy.destroyed && result.status === 200 && isProductLanguageResult(result.body)) {
        this.productLanguage.set(result.body['language']);
      }
    } catch { /* Keep English when the private preference is unavailable. */ }
  }
  newSet() { this.selected.set(null); this.history.set([]); this.historyMore.set(false); this.language.set(''); this.drafts.set([{ key: 'prompt-1', kind: 'neutral', text: '', intent_review_id: 0 }]); }
  availableMappings() { return this.mappings().filter((row) => row.source_current && row.language === this.language() && row.market === this.market()); }
  change(index: number, field: keyof Prompt, value: string | number) { this.drafts.update((rows) => rows.map((row, i) => i === index ? { ...row, [field]: value } : row)); }
  add() { if (this.drafts().length < 5) this.drafts.update((rows) => [...rows, { key: '', kind: 'neutral', text: '', intent_review_id: 0 }]); }
  remove(index: number) { if (this.drafts().length > 1) this.drafts.update((rows) => rows.filter((_, i) => i !== index)); }
  async load() {
    const generation = ++this.generation; this.loading.set(true); this.ready.set(false); this.busy.set(false); this.error.set(''); this.message.set('');
    this.name.set(''); this.market.set(''); this.brands.set([]); this.languages.set([]); this.canEdit.set(false); this.sets.set([]); this.mappings.set([]); this.newSet();
    try {
      const context = await this.api.projectOnboarding(this.organizationId, this.projectId);
      if (generation !== this.generation) return;
      const project = context.body['project'] as Record<string, unknown> | undefined;
      if (context.status !== 200 || project?.['id'] !== this.projectId || project['organization_id'] !== this.organizationId
          || typeof project['role'] !== 'string' || !['owner', 'admin', 'member', 'viewer'].includes(project['role'])) throw new Error();
      this.name.set(String(project['name'])); this.canEdit.set(['owner', 'admin'].includes(project['role']));
      const response = await this.api.visibilityPrompts(this.organizationId, this.projectId); const body = response.body;
      if (generation !== this.generation) return;
      if (response.status !== 200 || body['project_id'] !== this.projectId || body['method'] !== 'api-text-visibility-v1'
        || body['collection_available'] !== true || !['prompt_sets', 'languages', 'brand_aliases', 'intent_reviews'].every((key) => Array.isArray(body[key]))) throw new Error();
      this.sets.set(body['prompt_sets'] as PromptSet[]); this.languages.set(body['languages'] as string[]); this.brands.set(body['brand_aliases'] as string[]);
      this.market.set(String(body['market'] || '')); this.mappings.set(body['intent_reviews'] as Mapping[]); this.hasMore.set(body['has_more'] === true); this.ready.set(true);
    } catch { if (generation === this.generation) this.error.set('Current project methodology unavailable or access revoked.'); }
    finally { if (generation === this.generation) this.loading.set(false); }
  }
  async open(setId: string) {
    if (this.busy()) return; const generation = this.generation; this.busy.set(true); this.error.set(''); this.newSet();
    try {
      const response = await this.api.visibilityPrompts(this.organizationId, this.projectId, setId);
      if (generation !== this.generation) return;
      const rows = response.body['prompt_sets'] as PromptSet[];
      if (response.status !== 200 || response.body['project_id'] !== this.projectId || !Array.isArray(rows) || !rows.length
        || rows.some((row) => row.project_id !== this.projectId || row.set_id !== setId || row.collection_available !== true)) throw new Error();
      this.history.set(rows); this.historyMore.set(response.body['has_more'] === true); this.selected.set(rows[0]); this.language.set(rows[0].language);
      this.drafts.set(rows[0].prompts.map((row) => ({ ...row })));
    } catch { if (generation === this.generation) this.error.set('Methodology history unavailable; refresh current context.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  async save(event: SubmitEvent) {
    event.preventDefault(); const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || this.busy() || !this.canEdit()) return;
    const fields = new FormData(form); if (fields.get('acknowledge') !== 'on') return;
    const generation = this.generation; const selected = this.selected(); this.busy.set(true); this.error.set('');
    try {
      const data: Record<string, unknown> = { request_key: crypto.randomUUID(), label: String(fields.get('label')),
        language: String(fields.get('language')), prompts: this.drafts(), review_note: String(fields.get('review_note')),
        max_output_tokens: Number(fields.get('max_output_tokens')), max_cost_usd: String(fields.get('max_cost_usd')), acknowledge_api_limits: true };
      if (selected) data['expected_revision'] = selected.revision;
      const response = await this.api.visibilityPrompts(this.organizationId, this.projectId, selected?.set_id || '', data);
      if (generation !== this.generation) return;
      const row = response.body['prompt_set'] as PromptSet | undefined;
      if (response.status !== 201 || response.body['project_id'] !== this.projectId || row?.project_id !== this.projectId || row.collection_available !== true) throw new Error();
      this.busy.set(false); await this.load();
      if (this.generation !== generation + 1) return;
      await this.open(row.set_id);
      if (this.projectId === row.project_id) this.message.set('Immutable human methodology saved. No sample collected, no model selected and no usage consumed.');
    } catch { if (generation === this.generation) this.error.set('Review not confirmed. Reload latest revision/current intent; check neutral/branded wording, role and budgets.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
}
