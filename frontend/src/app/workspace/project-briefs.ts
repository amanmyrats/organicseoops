import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, effect, OnInit, computed, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi } from '../account/account-api';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';
import { environment } from '../../environments/environment';

type Brief = { id: number; project_id: number; research_job_id: number; action_review_id: number;
  created_at: string; size_bytes: number; sha256: string; review_state: string };
type Research = { id: number; project_id: number; topic: string; status: string };
type Action = { action_id: string; revision: number; state: string; action_kind: string; source_current: boolean;
  source_id: number; source_type: string; affected_urls: string[] };
type Draft = { version: string; topic: string; angle: string; title_options: string[]; outline: string[];
  questions: string[]; relevant_internal_links: string[]; research_summary_to_verify: string;
  claims_to_verify: { text: string; quote: string; source_index: number }[];
  sources: { index: number; state: string; title?: string; url?: string; sha256?: string; retrieved_at?: string }[];
  approval: string; source_coverage: string; action_revision: number; page_kind: string;
  audience?: string; business_goal?: string; desired_action?: string; meta_description?: string };

const projectBriefsTurkish: Record<string, string> = {
  "Private sourced content briefs": "Özel, kaynaklı içerik özetleri",
  "Unreviewed Turkish brief interface draft in local development. Human drafts, sources and AI interpretations retain their original language; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe içerik özeti arayüzü taslağı. İnsan taslakları, kaynaklar ve yapay zekâ yorumları özgün dillerini korur; iki dilli onay bekleniyor.",
  "Return to research and source evidence": "Araştırma ve kaynak kanıtlarına dönün",
  "Open the private content studio": "Özel içerik stüdyosunu açın",
  "Active project": "Etkin proje",
  ". A brief requires completed source-linked research and a current accepted human action. Titles, angle, headings and questions are entered by a person; AI summaries and quotes remain": ". Bir içerik özeti, tamamlanmış kaynak bağlantılı araştırma ve güncel, kabul edilmiş insan eylemi gerektirir. Başlıkları, yaklaşımı, bölüm başlıklarını ve soruları bir insan girer; yapay zekâ özetleri ve alıntıları",
  "unverified interpretations": "doğrulanmamış yorumlar olarak kalır",
  ". Briefs never approve publication, generate fake business facts or change a website.": ". İçerik özetleri hiçbir zaman yayını onaylamaz, sahte işletme bilgileri üretmez veya bir web sitesini değiştirmez.",
  "Loading current project source and brief history.": "Güncel proje kaynağı ve içerik özeti geçmişi yükleniyor.",
  "First collect research with an interpretation and accept a human action. Incomplete sources cannot support a new brief.": "Önce yorum içeren araştırmayı toplayın ve bir insan eylemini kabul edin. Eksik kaynaklar yeni bir içerik özetini destekleyemez.",
  "Research job": "Araştırma işi",
  "Select source-linked research": "Kaynak bağlantılı araştırma seçin",
  "· job": "· iş",
  "Latest accepted human action": "En son kabul edilen insan eylemi",
  "Select action; its project/mapping must match the research": "Eylem seçin; projesi/eşleştirmesi araştırmayla eşleşmelidir",
  "· revision": "· sürüm",
  "Title options (1–3, one per line)": "Başlık seçenekleri (1–3, her satıra bir tane)",
  "Human-selected angle (up to 500 characters)": "İnsanın seçtiği yaklaşım (en fazla 500 karakter)",
  "Human draft meta description (optional, up to 320 characters)": "İnsan taslağı meta açıklaması (isteğe bağlı, en fazla 320 karakter)",
  "Desired reader action (optional; verify against actual business service)": "İstenen okuyucu eylemi (isteğe bağlı; gerçek işletme hizmetiyle doğrulayın)",
  "Useful outline headings (1–12, one per line)": "Yararlı taslak bölüm başlıkları (1–12, her satıra bir tane)",
  "Questions to verify (up to 10, one per line; optional)": "Doğrulanacak sorular (en fazla 10, her satıra bir tane; isteğe bağlı)",
  "Save private unapproved brief": "Özel, onaylanmamış içerik özetini kaydedin",
  "You may read existing briefs but cannot create a new one.": "Mevcut içerik özetlerini okuyabilirsiniz ancak yenisini oluşturamazsınız.",
  "Recent private draft history": "Son özel taslak geçmişi",
  "Refresh": "Yenileyin",
  "No private sourced brief exists for this project.": "Bu proje için özel, kaynaklı içerik özeti yok.",
  "Brief": "İçerik özeti",
  "· research": "· araştırma",
  "· private SHA-256": "· özel SHA-256",
  "Inspect draft": "Taslağı inceleyin",
  "Only the 20 most recent brief revisions are shown.": "Yalnızca en son 20 içerik özeti sürümü gösterilir.",
  "Unapproved brief": "Onaylanmamış içerik özeti",
  "· source coverage": "· kaynak kapsamı",
  "· action revision": "· eylem sürümü",
  "· page": "· sayfa",
  "Human angle:": "İnsan yaklaşımı:",
  "Audience:": "Hedef kitle:",
  "unknown": "bilinmiyor",
  "· user-entered business goal:": "· kullanıcının girdiği işletme hedefi:",
  "Desired reader action:": "İstenen okuyucu eylemi:",
  "not entered": "girilmedi",
  "Human draft meta description:": "İnsan taslağı meta açıklaması:",
  "Download this private unapproved JSON brief": "Bu özel, onaylanmamış JSON içerik özetini indirin",
  "Human title options": "İnsan başlık seçenekleri",
  "Human outline": "İnsan taslağı",
  "Questions needing answers": "Yanıt bekleyen sorular",
  "Human-selected action page(s), not verified internal-link opportunities": "İnsanın seçtiği eylem sayfaları; doğrulanmış dahili bağlantı fırsatları değildir",
  "Research interpretation to verify": "Doğrulanacak araştırma yorumu",
  "· source": "· kaynak",
  "· excerpt": "· alıntı",
  ". Verify this claim independently.": ". Bu iddiayı bağımsız olarak doğrulayın.",
  "Explicit selected research sources": "Açıkça seçilen araştırma kaynakları",
  "Source": "Kaynak",
  "unavailable": "kullanılamıyor",
  "No structured data is suggested without a human fact/eligibility review. No page is published by this brief.": "İnsan doğruluk/uygunluk incelemesi olmadan yapılandırılmış veri önerilmez. Bu içerik özeti hiçbir sayfayı yayımlamaz.",
  "Select a current project.": "Güncel bir proje seçin.",
  "Current project brief history is unavailable or access was revoked.": "Güncel proje içerik özeti geçmişi kullanılamıyor veya erişim iptal edildi.",
  "Use current sources, 1–160 characters per draft line, a 1–500 character angle, up to 320 for the meta description and 240 for the desired action.": "Güncel kaynaklar kullanın; her taslak satırı 1–160, yaklaşım 1–500, meta açıklaması en fazla 320 ve istenen eylem en fazla 240 karakter olmalıdır.",
  "Private unapproved brief saved; sources and claims still require human verification.": "Özel, onaylanmamış içerik özeti kaydedildi; kaynaklar ve iddialar hâlâ insan doğrulaması gerektirir.",
  "Brief outcome unavailable. Refresh history before creating another revision.": "İçerik özeti sonucu kullanılamıyor. Başka bir sürüm oluşturmadan önce geçmişi yenileyin.",
  "Private brief unavailable or its integrity/permission changed.": "Özel içerik özeti kullanılamıyor veya bütünlüğü/izni değişti."
};

@Component({
  selector: 'app-project-briefs',
  imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="brief-title">
      <h1 id="brief-title">{{ t("Private sourced content briefs") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish brief interface draft in local development. Human drafts, sources and AI interpretations retain their original language; bilingual approval is pending.") }}</p> }
      <p><a [routerLink]="['/app/research', organizationId, projectId]">{{ t("Return to research and source evidence") }}</a></p>
      <p><a [routerLink]="['/app/content', organizationId, projectId]">{{ t("Open the private content studio") }}</a></p>
      <p>{{ t("Active project") }} <span lang="">{{ projectName() }}</span>{{ t(". A brief requires completed source-linked research and a current accepted human action. Titles, angle, headings and questions are entered by a person; AI summaries and quotes remain") }} <strong>{{ t("unverified interpretations") }}</strong>{{ t(". Briefs never approve publication, generate fake business facts or change a website.") }}</p>
      @if (loading()) { <p role="status">{{ t("Loading current project source and brief history.") }}</p> }
      @if (error()) { <p role="alert" [attr.lang]="t(error()) === error() ? 'en' : uiLanguage()">{{ t(error()) }}</p> }
      @if (!loading() && !error()) {
        @if (canCreate()) {
          @if (!research().length || !actions().length) { <p>{{ t("First collect research with an interpretation and accept a human action. Incomplete sources cannot support a new brief.") }}</p> }
          @else {
            <form (submit)="create($event)">
              <label for="brief-research">{{ t("Research job") }}</label>
              <select lang="" id="brief-research" name="research_job_id" required>
                <option value="" [attr.lang]="uiLanguage()">{{ t("Select source-linked research") }}</option>
                @for (job of research(); track job.id) {
                  <option lang="" [value]="job.id">{{ job.topic }} · {{ job.status }} {{ t("· job") }} {{ job.id }}</option>
                }
              </select>
              <label for="brief-action">{{ t("Latest accepted human action") }}</label>
              <select lang="en" id="brief-action" name="action_id" required>
                <option value="" [attr.lang]="uiLanguage()">{{ t("Select action; its project/mapping must match the research") }}</option>
                @for (action of actions(); track action.action_id) {
                  <option lang="en" [value]="action.action_id">{{ action.action_kind }} · {{ action.state }} {{ t("· revision") }} {{ action.revision }} · {{ action.affected_urls.join(', ') }}</option>
                }
              </select>
              <label for="brief-titles">{{ t("Title options (1–3, one per line)") }}</label>
              <textarea lang="" id="brief-titles" name="title_options" rows="3" maxlength="962" required></textarea>
              <label for="brief-angle">{{ t("Human-selected angle (up to 500 characters)") }}</label>
              <textarea lang="" id="brief-angle" name="angle" maxlength="1000" required></textarea>
              <label for="brief-meta">{{ t("Human draft meta description (optional, up to 320 characters)") }}</label>
              <textarea lang="" id="brief-meta" name="meta_description" maxlength="640"></textarea>
              <label for="brief-goal">{{ t("Desired reader action (optional; verify against actual business service)") }}</label>
              <input lang="" id="brief-goal" name="desired_action" maxlength="480" />
              <label for="brief-outline">{{ t("Useful outline headings (1–12, one per line)") }}</label>
              <textarea lang="" id="brief-outline" name="outline" rows="6" maxlength="3851" required></textarea>
              <label for="brief-questions">{{ t("Questions to verify (up to 10, one per line; optional)") }}</label>
              <textarea lang="" id="brief-questions" name="questions" rows="4" maxlength="3209"></textarea>
              <button type="submit" [disabled]="busy()">{{ t("Save private unapproved brief") }}</button>
            </form>
          }
        } @else { <p>{{ t("You may read existing briefs but cannot create a new one.") }}</p> }
        <section aria-labelledby="brief-history-title">
          <h2 id="brief-history-title">{{ t("Recent private draft history") }}</h2>
          <button type="button" (click)="load()" [disabled]="busy()">{{ t("Refresh") }}</button>
          @if (!briefs().length) { <p>{{ t("No private sourced brief exists for this project.") }}</p> }
          <ul>@for (brief of briefs(); track brief.id) {
            <li>{{ t("Brief") }} {{ brief.id }} · <span lang="en">{{ brief.created_at }}</span> {{ t("· research") }} {{ brief.research_job_id }} {{ t("· private SHA-256") }} <span lang="en">{{ brief.sha256 }}</span>
              <button type="button" [disabled]="busy()" (click)="open(brief.id)">{{ t("Inspect draft") }} {{ brief.id }}</button></li>
          }</ul>
          @if (hasMore()) { <p>{{ t("Only the 20 most recent brief revisions are shown.") }}</p> }
        </section>
        @if (draft(); as current) {
          <section aria-labelledby="draft-title">
            <h2 id="draft-title">{{ t("Unapproved brief") }} <span lang="">{{ current.topic }}</span></h2>
            <p role="status"><span lang="en">{{ current.approval }}</span> {{ t("· source coverage") }} <span lang="en">{{ current.source_coverage }}</span> {{ t("· action revision") }} {{ current.action_revision }} {{ t("· page") }} <span lang="en">{{ current.page_kind }}</span>.</p>
            <p>{{ t("Human angle:") }} <span lang="">{{ current.angle }}</span></p>
            <p>{{ t("Audience:") }} <span [attr.lang]="current.audience ? '' : uiLanguage()">{{ current.audience || t('unknown') }}</span> {{ t("· user-entered business goal:") }} <span [attr.lang]="current.business_goal ? '' : uiLanguage()">{{ current.business_goal || t('unknown') }}</span>.
              {{ t("Desired reader action:") }} <span [attr.lang]="current.desired_action ? '' : uiLanguage()">{{ current.desired_action || t('not entered') }}</span>.</p>
            <p>{{ t("Human draft meta description:") }} <span [attr.lang]="current.meta_description ? '' : uiLanguage()">{{ current.meta_description || t('not entered') }}</span>.</p>
            <a [href]="downloadUrl()" download>{{ t("Download this private unapproved JSON brief") }}</a>
            <h3>{{ t("Human title options") }}</h3><ol>@for (title of current.title_options; track $index) { <li lang="">{{ title }}</li> }</ol>
            <h3>{{ t("Human outline") }}</h3><ol>@for (heading of current.outline; track $index) { <li lang="">{{ heading }}</li> }</ol>
            <h3>{{ t("Questions needing answers") }}</h3><ul>@for (question of current.questions; track $index) { <li lang="">{{ question }}</li> }</ul>
            <h3>{{ t("Human-selected action page(s), not verified internal-link opportunities") }}</h3>
            <ul>@for (url of current.relevant_internal_links; track url) { <li lang="">{{ url }}</li> }</ul>
            <h3>{{ t("Research interpretation to verify") }}</h3><p lang="">{{ current.research_summary_to_verify }}</p>
            <ol>@for (claim of current.claims_to_verify; track $index) {
              <li><span lang="">{{ claim.text }}</span> {{ t("· source") }} {{ claim.source_index + 1 }} {{ t("· excerpt") }} <q lang="">{{ claim.quote }}</q>{{ t(". Verify this claim independently.") }}</li>
            }</ol>
            <h3>{{ t("Explicit selected research sources") }}</h3>
            <ol>@for (source of current.sources; track source.index) {
              <li>{{ t("Source") }} {{ source.index + 1 }} · <span lang="en">{{ source.state }}</span> · <span [attr.lang]="source.retrieved_at ? 'en' : uiLanguage()">{{ source.retrieved_at || t('unavailable') }}</span>.
                @if (source.url) { @if (safeSourceUrl(source.url); as href) { <a [href]="href" target="_blank" rel="noopener noreferrer" lang="">{{ source.title || href }}</a> } }
                @if (source.sha256) { <span lang="en"> SHA-256 {{ source.sha256 }}.</span> }
              </li>
            }</ol>
            <p>{{ t("No structured data is suggested without a human fact/eligibility review. No page is published by this brief.") }}</p>
          </section>
        }
        @if (message()) { <p role="status" [attr.lang]="t(message()) === message() ? 'en' : uiLanguage()">{{ t(message()) }}</p> }
      }
    </section>
  `,
  styles: `label {display:block;margin-block:.7rem .2rem} textarea,select {max-width:100%;width:min(100%,42rem)} section {overflow-wrap:anywhere} button {margin:.6rem .6rem .6rem 0}`,
})
export class ProjectBriefs implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  t(text: string) { return this.uiLanguage() === 'tr' ? projectBriefsTurkish[text] ?? text : text; }
  organizationId = 0;
  projectId = 0;
  private generation = 0;
  private opening = 0;
  readonly selectedBriefId = signal(0);
  readonly loading = signal(true);
  readonly busy = signal(false);
  readonly error = signal('');
  readonly message = signal('');
  readonly projectName = signal('');
  readonly canCreate = signal(false);
  readonly research = signal<Research[]>([]);
  readonly actions = signal<Action[]>([]);
  readonly briefs = signal<Brief[]>([]);
  readonly hasMore = signal(false);
  readonly draft = signal<Draft | null>(null);

  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi,
              private readonly destroy: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t('Private sourced content briefs')} — OrganicSEOOps`));
    destroy.onDestroy(() => { this.generation++; this.opening++; }); }

  ngOnInit() {
    void this.loadProductLanguage();
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroy)).subscribe((params) => {
      this.organizationId = Number(params.get('organizationId')); this.projectId = Number(params.get('projectId'));
      this.generation++;
      this.projectName.set(''); this.canCreate.set(false); this.error.set(''); this.message.set('');
      this.research.set([]); this.actions.set([]); this.briefs.set([]); this.hasMore.set(false); this.draft.set(null);
      this.selectedBriefId.set(0);
      this.busy.set(false);
      if (Number.isSafeInteger(this.organizationId) && this.organizationId > 0
          && Number.isSafeInteger(this.projectId) && this.projectId > 0) void this.load();
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

  safeSourceUrl(value: string) {
    if (typeof value !== 'string') return '';
    try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password
      && !url.search && !url.hash && (!url.port || url.port === '443') ? url.href : ''; }
    catch { return ''; }
  }

  private validDraft(value: unknown, brief: Brief): value is Draft {
    const draft = value as Draft & { project_id: number; research_job_id: number; action_review_id: number; scope: string } | null;
    if (!draft || Array.isArray(draft) || draft.version !== 'content-brief-v1'
      || draft.project_id !== this.projectId || draft.research_job_id !== brief.research_job_id
      || draft.action_review_id !== brief.action_review_id
      || draft.scope !== 'human_authored_structure_and_unverified_ai_interpretation_not_publication'
      || draft.approval !== 'draft_human_review_required_no_site_change'
      || !['partial', 'collected_selected_sources_only'].includes(draft.source_coverage)
      || !Number.isSafeInteger(draft.action_revision) || draft.action_revision < 1 || draft.action_revision > 32767
      || !['existing_unverified', 'proposed', 'human_selected_action_page'].includes(draft.page_kind)
      || typeof draft.topic !== 'string' || !draft.topic.trim() || Array.from(draft.topic.trim()).length > 240
      || typeof draft.angle !== 'string' || !draft.angle.trim() || Array.from(draft.angle.trim()).length > 500
      || typeof draft.audience !== 'string' || Array.from(draft.audience).length > 500
      || typeof draft.business_goal !== 'string' || Array.from(draft.business_goal).length > 240
      || typeof draft.desired_action !== 'string' || Array.from(draft.desired_action).length > 240
      || typeof draft.meta_description !== 'string' || Array.from(draft.meta_description).length > 320
      || !Array.isArray(draft.title_options) || !draft.title_options.length || draft.title_options.length > 3
      || !Array.isArray(draft.outline) || !draft.outline.length || draft.outline.length > 12
      || !Array.isArray(draft.questions) || draft.questions.length > 10
      || ![...draft.title_options, ...draft.outline, ...draft.questions].every((line) => typeof line === 'string'
        && !!line.trim() && Array.from(line.trim()).length <= 160)
      || !Array.isArray(draft.relevant_internal_links) || !draft.relevant_internal_links.length || draft.relevant_internal_links.length > 2
      || !draft.relevant_internal_links.every((url) => typeof url === 'string' && !!url)
      || typeof draft.research_summary_to_verify !== 'string' || !draft.research_summary_to_verify
      || Array.from(draft.research_summary_to_verify).length > 3000
      || !Array.isArray(draft.sources) || !draft.sources.length || draft.sources.length > 5
      || !draft.sources.every((source, position) => source && Number.isSafeInteger(source.index) && source.index >= 0 && source.index < 5
        && (!position || source.index > draft.sources[position - 1].index)
        && (source.url === undefined || typeof source.url === 'string' && !!this.safeSourceUrl(source.url))
        && (source.title === undefined || typeof source.title === 'string' && Array.from(source.title).length <= 240)
        && (source.sha256 === undefined || typeof source.sha256 === 'string' && /^[0-9a-f]{64}$/.test(source.sha256))
        && (source.retrieved_at === undefined || typeof source.retrieved_at === 'string')
        && (source.state === 'unavailable' || source.state === 'collected' && typeof source.url === 'string'
          && typeof source.title === 'string' && typeof source.sha256 === 'string' && typeof source.retrieved_at === 'string'))
      || !draft.sources.some((source) => source.state === 'collected')
      || !Array.isArray(draft.claims_to_verify) || !draft.claims_to_verify.length || draft.claims_to_verify.length > 10
      || !draft.claims_to_verify.every((claim) => claim && typeof claim.text === 'string' && !!claim.text
        && Array.from(claim.text).length <= 500 && typeof claim.quote === 'string' && !!claim.quote.trim()
        && Array.from(claim.quote.trim()).length <= 300 && Number.isSafeInteger(claim.source_index)
        && draft.sources.some((source) => source.index === claim.source_index && source.state === 'collected'))) return false;
    return true;
  }

  downloadUrl() {
    return `${environment.apiBase}/organizations/${this.organizationId}/projects/${this.projectId}/briefs/${this.selectedBriefId()}/download/`;
  }

  async load() {
    const generation = ++this.generation;
    this.loading.set(true); this.error.set(''); this.draft.set(null);
    this.canCreate.set(false); this.research.set([]); this.actions.set([]); this.briefs.set([]);
    this.hasMore.set(false); this.selectedBriefId.set(0);
    try {
      const context = await this.api.projectOnboarding(this.organizationId, this.projectId);
      if (generation !== this.generation) return;
      const project = context.body['project'] as Record<string, unknown> | undefined;
      if (context.status !== 200 || project?.['id'] !== this.projectId || project['organization_id'] !== this.organizationId) throw new Error();
      this.projectName.set(String(project['name']));
      this.canCreate.set(typeof project['role'] === 'string' && ['owner', 'admin', 'member'].includes(project['role']));
      const [briefs, research, actions] = await Promise.all([
        this.api.projectBriefs(this.organizationId, this.projectId),
        this.api.projectResearch(this.organizationId, this.projectId),
        this.api.projectActions(this.organizationId, this.projectId),
      ]);
      if (generation !== this.generation) return;
      if (briefs.status !== 200 || briefs.body['project_id'] !== this.projectId || !Array.isArray(briefs.body['briefs'])) throw new Error();
      this.briefs.set((briefs.body['briefs'] as Brief[]).filter(isBrief).filter((row) => row.project_id === this.projectId));
      this.hasMore.set(briefs.body['has_more'] === true);
      if (research.status === 200 && research.body['project_id'] === this.projectId && Array.isArray(research.body['jobs'])) {
        this.research.set((research.body['jobs'] as Research[]).filter((row) => row && row.project_id === this.projectId
          && ['succeeded', 'partially_succeeded'].includes(row.status) && Number.isSafeInteger(row.id) && row.id > 0
          && typeof row.topic === 'string' && !!row.topic.trim() && Array.from(row.topic.trim()).length <= 240));
      }
      if (actions.status === 200 && actions.body['project_id'] === this.projectId && Array.isArray(actions.body['actions'])) {
        this.actions.set((actions.body['actions'] as Action[]).filter((row) => row && row.source_current === true
          && ['accepted', 'in_progress', 'implemented', 'verified', 'outcome_reviewed'].includes(row.state)
          && typeof row.action_id === 'string' && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(row.action_id)
          && Number.isSafeInteger(row.revision) && row.revision > 0 && row.revision <= 32767
          && ['intent', 'opportunity'].includes(row.source_type) && Number.isSafeInteger(row.source_id) && row.source_id > 0
          && ['keep', 'refresh', 'merge', 'redirect', 'retire', 'create'].includes(row.action_kind)
          && Array.isArray(row.affected_urls) && row.affected_urls.length >= 1 && row.affected_urls.length <= 2
          && row.affected_urls.every((value) => typeof value === 'string' && !!value)));
      }
    } catch { if (generation === this.generation) { this.canCreate.set(false); this.error.set('Current project brief history is unavailable or access was revoked.'); } }
    finally { if (generation === this.generation) this.loading.set(false); }
  }

  async create(event: Event) {
    event.preventDefault();
    const form = event.target as HTMLFormElement;
    if (!this.canCreate() || this.busy() || !form.reportValidity()) return;
    const fields = new FormData(form);
    const list = (name: string) => String(fields.get(name) || '').split('\n').map((value) => value.trim()).filter(Boolean);
    const researchJob = Number(fields.get('research_job_id'));
    const action = String(fields.get('action_id'));
    const titles = list('title_options'), outline = list('outline'), questions = list('questions');
    const angle = String(fields.get('angle') || ''); const meta = String(fields.get('meta_description') || '');
    const desiredAction = String(fields.get('desired_action') || '');
    if (!this.research().some((row) => row.id === researchJob) || !this.actions().some((row) => row.action_id === action)
        || !titles.length || titles.length > 3 || !outline.length || outline.length > 12 || questions.length > 10
        || [...titles, ...outline, ...questions].some((value) => Array.from(value).length > 160)
        || !angle.trim() || Array.from(angle.trim()).length > 500 || Array.from(meta).length > 320
        || Array.from(desiredAction).length > 240) {
      this.message.set('Use current sources, 1–160 characters per draft line, a 1–500 character angle, up to 320 for the meta description and 240 for the desired action.'); return;
    }
    const generation = this.generation;
    this.busy.set(true); this.message.set('');
    try {
      const result = await this.api.createProjectBrief(this.organizationId, this.projectId, {
        request_key: crypto.randomUUID().replaceAll('-', ''), research_job_id: researchJob, action_id: action,
        title_options: titles, angle, outline, questions,
        meta_description: meta, desired_action: desiredAction,
      });
      if (generation !== this.generation) return;
      if (result.status !== 201 || result.body['project_id'] !== this.projectId || !isBrief(result.body['brief'])
          || (result.body['brief'] as Brief).project_id !== this.projectId) throw new Error();
      const brief = result.body['brief'] as Brief;
      this.briefs.set([brief, ...this.briefs()].slice(0, 20));
      form.reset();
      this.message.set('Private unapproved brief saved; sources and claims still require human verification.');
      await this.open(brief.id);
    } catch { if (generation === this.generation) this.message.set('Brief outcome unavailable. Refresh history before creating another revision.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }

  async open(id: number) {
    if (!Number.isSafeInteger(id) || id <= 0) return;
    const generation = this.generation;
    const opening = ++this.opening;
    this.draft.set(null); this.selectedBriefId.set(0);
    try {
      const result = await this.api.projectBrief(this.organizationId, this.projectId, id);
      if (generation !== this.generation || opening !== this.opening) return;
      const draft = result.body['draft'] as Draft | undefined;
      if (result.status !== 200 || result.body['project_id'] !== this.projectId || !isBrief(result.body['brief'])
          || (result.body['brief'] as Brief).project_id !== this.projectId
          || (result.body['brief'] as Brief).id !== id || !this.validDraft(draft, result.body['brief'] as Brief)) throw new Error();
      this.draft.set(draft);
      this.selectedBriefId.set(id);
    } catch { if (generation === this.generation && opening === this.opening) this.message.set('Private brief unavailable or its integrity/permission changed.'); }
  }
}

function isBrief(value: unknown): value is Brief {
  if (!value || typeof value !== 'object') return false;
  const brief = value as Record<string, unknown>;
  return Number.isSafeInteger(brief['id']) && Number(brief['id']) > 0
    && Number.isSafeInteger(brief['project_id']) && Number.isSafeInteger(brief['research_job_id']) && Number(brief['research_job_id']) > 0
    && Number.isSafeInteger(brief['action_review_id']) && Number(brief['action_review_id']) > 0 && typeof brief['created_at'] === 'string'
    && Number.isSafeInteger(brief['size_bytes']) && Number(brief['size_bytes']) > 0
    && typeof brief['sha256'] === 'string' && /^[0-9a-f]{64}$/.test(brief['sha256'])
    && brief['review_state'] === 'draft_human_review_required_no_site_change';
}
