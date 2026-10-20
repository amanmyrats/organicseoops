import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, OnInit, computed, effect, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi } from '../account/account-api';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';

type Source = { id: number; project_id: number; crawl_run_id: number; observed_at: string; coverage: string; source_current: boolean };
type Proposal = { id: number; project_id: number; subject: string; detector: string; evidence: unknown; source_current: boolean;
  proposal: string; detected_at: string; approval: string; review: { id: number; revision: number; priority: string; reason: string } | null };
type Concern = { project_id: number; job_id: number; review_id: number; review_revision: number; reviewed_at: string;
  collected_at: string | null; source_current: boolean; text: string; note: string; proposal: string };
type Content = { project_id: number; item_id: number; revision_id: number; revision: number; title: string; state: string;
  brief_id: number; reviewed_revision_id: number | null; created_at: string; proposal: string };
type Evidence = { method: string; project_id: number; diagnostics: Source[]; selected_diagnostics_id: number | null;
  proposals: Proposal[]; human_factual_concerns: Concern[]; content_revisions: Content[]; has_more: boolean };

const discoverabilityTurkish: Record<string, string> = {
  "Private discoverability proposals": "Özel keşfedilebilirlik önerileri",
  "Source-supported discoverability proposals": "Kaynakla desteklenen keşfedilebilirlik önerileri",
  "Project evidence": "Proje kanıtları",
  "API history": "API geçmişi",
  "Human action approval and follow-up": "İnsan eylem onayı ve takip",
  "Stored bounded crawl/content/human evidence only. No fetch, automatic site change or placement guarantee. Human prioritization below is not approval: propose an assigned action and approve its exact scope separately. Robots access, bot visits, schema and experimental files never prove inclusion, citations or training membership.": "Yalnızca saklanan sınırlı tarama/içerik/insan kanıtı. Getirme, otomatik site değişikliği veya yerleştirme garantisi yoktur. Aşağıdaki insan önceliklendirmesi onay değildir: atanmış eylem önerin ve tam kapsamını ayrı onaylayın. Robots erişimi, bot ziyaretleri, şema ve deneysel dosyalar dahil olmayı, atıfları veya eğitim verisine dahil olmayı hiçbir zaman kanıtlamaz.",
  "Provider crawler purposes — access evidence unavailable": "Sağlayıcı tarayıcı amaçları — erişim kanıtı kullanılamıyor",
  "OAI-SearchBot: search/retrieval, separate from training.": "OAI-SearchBot: arama/erişim, eğitimden ayrı.",
  "GPTBot: potential training, independent from search.": "GPTBot: olası eğitim, aramadan bağımsız.",
  "ChatGPT-User: user-triggered actions; robots rules may not apply. Not search inclusion evidence.": "ChatGPT-User: kullanıcı tarafından tetiklenen eylemler; robots kuralları geçerli olmayabilir. Aramaya dahil olma kanıtı değildir.",
  "Current crawl records do not preserve agent-specific robots rules. Generic crawl robots status and Google/Bing meta directives cannot establish any of these agents' access. Independently verified bot visits and credible external mentions are unavailable.": "Güncel tarama kayıtları aracıya özgü robots kurallarını korumaz. Genel tarama robots durumu ve Google/Bing meta yönergeleri bu aracıların erişimini kanıtlayamaz. Bağımsız doğrulanmış bot ziyaretleri ve güvenilir dış anmalar kullanılamıyor.",
  "Optional authorized partial logs (UA-only unverified)": "İsteğe bağlı yetkilendirilmiş kısmi günlükler (yalnızca UA, doğrulanmamış)",
  "Official provider guidance (reviewed2026-10-01)": "Resmî sağlayıcı rehberi (incelenme tarihi2026-10-01)",
  "Loading private project sources.": "Özel proje kaynakları yükleniyor.",
  "Active project:": "Aktif proje:",
  "(organization": "(kuruluş",
  ", project": ", proje",
  "Bounded view:20 diagnostics/latest answer reviews/content items and100 selected findings. Omitted evidence is unknown.": "Sınırlı görünüm:20 tanılama/son yanıt incelemesi/içerik öğesi ve100 seçilen bulgu. Gösterilmeyen kanıt bilinmiyor.",
  "Stored crawl observations": "Saklanan tarama gözlemleri",
  "Choose an immutable diagnostics snapshot": "Değişmez tanılama anlık görüntüsü seçin",
  "Choose source evidence": "Kaynak kanıtı seçin",
  "No completed stored diagnostics. Missing evidence is not a clean audit.": "Tamamlanmış saklanan tanılama yok. Eksik kanıt temiz denetim değildir.",
  "Record existing technical candidates from this snapshot (no fetch, no approval)": "Bu anlık görüntüden mevcut teknik adayları kaydedin (getirme yok, onay yok)",
  "Finding": "Bulgu",
  "· recorded": "· kaydedildi",
  "current project source": "güncel proje kaynağı",
  "historical/revoked; new review unavailable": "tarihsel/iptal edilmiş; yeni inceleme kullanılamıyor",
  "Exact stored source evidence": "Tam saklanan kaynak kanıtı",
  "Human priority": "İnsan önceliği",
  "· revision": "· revizyon",
  ". This is not an approved website change.": ". Bu onaylanmış web sitesi değişikliği değildir.",
  "Unprioritized": "Önceliklendirilmedi",
  "Low": "Düşük",
  "Medium": "Orta",
  "High": "Yüksek",
  "Estimated human effort": "Tahmini insan çabası",
  "Unknown": "Bilinmiyor",
  "Small": "Küçük",
  "Large": "Büyük",
  "Human business relevance": "İnsan iş ilgililiği",
  "Source-based human rationale": "Kaynağa dayalı insan gerekçesi",
  "Save human priority, then propose a separately approved action": "İnsan önceliğini kaydedin, ardından ayrı onaylı eylem önerin",
  "No recorded technical proposals for the selected source. Choose a stored snapshot and explicitly record candidates; absence here does not prove accessibility or AI visibility.": "Seçilen kaynak için kaydedilmiş teknik öneri yok. Saklanan anlık görüntü seçin ve adayları açıkça kaydedin; buradaki yokluk erişilebilirliği veya AI görünürlüğünü kanıtlamaz.",
  "Human factual concerns — not verified business truth": "İnsan olgusal kaygıları — doğrulanmış iş gerçeği değil",
  "No approved business-fact registry exists. Check business records and original expertise before changing content; missing concerns are not factual approval.": "Onaylanmış iş gerçeği kaydı yok. İçeriği değiştirmeden önce iş kayıtlarını ve özgün uzmanlığı kontrol edin; eksik kaygılar olgusal onay değildir.",
  "Sample": "Örnek",
  "· collection": "· toplama",
  "unknown": "bilinmiyor",
  "· human review": "· insan incelemesi",
  "revision": "revizyon",
  "current context": "güncel bağlam",
  "historical/changed context": "tarihsel/değişmiş bağlam",
  "Inspect authenticated exact answer and correction": "Kimliği doğrulanmış tam yanıtı ve düzeltmeyi inceleyin",
  "No latest human factual-concern evidence in this bounded view.": "Bu sınırlı görünümde son insan olgusal kaygı kanıtı yok.",
  "Exact current content records — live-page quality unverified": "Tam güncel içerik kayıtları — canlı sayfa kalitesi doğrulanmadı",
  "· item": "· öğe",
  "(record": "(kayıt",
  ". Linked brief": ". Bağlı brief",
  "· exact reviewed text record": "· tam incelenmiş metin kaydı",
  "none": "yok",
  "Inspect content, linked brief/sources and human review": "İçeriği, bağlı brief/kaynakları ve insan incelemesini inceleyin",
  "No stored content revisions. Genuine usefulness/entity accuracy remains unknown.": "Saklanan içerik revizyonu yok. Gerçek yararlılık/varlık doğruluğu bilinmeyen kalır.",
  "Refresh current source scope": "Güncel kaynak kapsamını yenileyin",
  "Discoverability source evidence unavailable or access revoked. Refresh current scope.": "Keşfedilebilirlik kaynak kanıtı kullanılamıyor veya erişim iptal edildi. Güncel kapsamı yenileyin.",
  "Human decision not confirmed. Reload source/current review before retrying; no website change or approval occurred.": "İnsan kararı doğrulanmadı. Yeniden denemeden önce kaynağı/güncel incelemeyi yeniden yükleyin; web sitesi değişikliği veya onay gerçekleşmedi.",
  "Unreviewed Turkish discoverability interface draft in local development. Source text and metadata retain their original language; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe keşfedilebilirlik arayüzü taslağı. Kaynak metni ve meta veriler özgün dillerini korur; iki dilli onay bekleniyor."
};

@Component({
  selector: 'app-visibility-discoverability', imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="discoverability-title">
      <h1 id="discoverability-title">{{ t("Source-supported discoverability proposals") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish discoverability interface draft in local development. Source text and metadata retain their original language; bilingual approval is pending.") }}</p> }
      <p><a [routerLink]="['/app/dashboard', organizationId, projectId]">{{ t("Project evidence") }}</a> ·
        <a [routerLink]="['/app/visibility-history', organizationId, projectId]">{{ t("API history") }}</a> ·
        <a [routerLink]="['/app/actions', organizationId, projectId]">{{ t("Human action approval and follow-up") }}</a></p>
      <p>{{ t("Stored bounded crawl/content/human evidence only. No fetch, automatic site change or placement guarantee. Human prioritization below is not approval: propose an assigned action and approve its exact scope separately. Robots access, bot visits, schema and experimental files never prove inclusion, citations or training membership.") }}</p>
      <h2>{{ t("Provider crawler purposes — access evidence unavailable") }}</h2>
      <ul><li>{{ t("OAI-SearchBot: search/retrieval, separate from training.") }}</li><li>{{ t("GPTBot: potential training, independent from search.") }}</li>
        <li>{{ t("ChatGPT-User: user-triggered actions; robots rules may not apply. Not search inclusion evidence.") }}</li></ul>
      <p>{{ t("Current crawl records do not preserve agent-specific robots rules. Generic crawl robots status and Google/Bing meta directives cannot establish any of these agents' access. Independently verified bot visits and credible external mentions are unavailable.") }}
        <a [routerLink]="['/app/bot-logs', organizationId, projectId]">{{ t("Optional authorized partial logs (UA-only unverified)") }}</a>.
        <a href="https://developers.openai.com/api/docs/bots" target="_blank" rel="noopener noreferrer">{{ t("Official provider guidance (reviewed2026-10-01)") }}</a>.</p>
      @if (loading()) { <p role="status">{{ t("Loading private project sources.") }}</p> }
      @if (error()) { <p role="alert" [attr.lang]="t(error()) === error() ? 'en' : uiLanguage()">{{ t(error()) }}</p> }
      @if (evidence(); as data) {
        <p>{{ t("Active project:") }} <span lang="">{{ name() }}</span> {{ t("(organization") }} <span lang="en">{{ organizationId }}</span>{{ t(", project") }} <span lang="en">{{ projectId }}</span>).</p>
        @if (data.has_more) { <p>{{ t("Bounded view:20 diagnostics/latest answer reviews/content items and100 selected findings. Omitted evidence is unknown.") }}</p> }
        <h2>{{ t("Stored crawl observations") }}</h2>
        <label for="discoverability-source">{{ t("Choose an immutable diagnostics snapshot") }}</label>
        <select id="discoverability-source" [disabled]="busy()" (change)="load(+$any($event.target).value || null)">
          <option value="">{{ t("Choose source evidence") }}</option>@for (source of data.diagnostics; track source.id) {
            <option lang="en" [value]="source.id" [selected]="source.id === selectedId">Diagnostics {{ source.id }} · crawl {{ source.crawl_run_id }} · {{ source.observed_at }} · {{ source.coverage }} · {{ source.source_current ? 'current scope' : 'historical/revoked' }}</option>
          }
        </select>
        @if (!data.diagnostics.length) { <p>{{ t("No completed stored diagnostics. Missing evidence is not a clean audit.") }}</p> }
        @if (canReview() && selectedSource()?.source_current) {
          <button type="button" [disabled]="busy()" (click)="materialize()">{{ t("Record existing technical candidates from this snapshot (no fetch, no approval)") }}</button>
        }
        <ul>@for (row of data.proposals; track row.id) {
          <li><h3>{{ t("Finding") }} <span lang="en">{{ row.id }}</span> · <span lang="en">{{ row.detector }}</span></h3><p><span lang="">{{ row.subject }}</span> {{ t("· recorded") }} <span lang="en">{{ row.detected_at }}</span> · {{ row.source_current ? t("current project source") : t("historical/revoked; new review unavailable") }}.</p>
            <p><span lang="">{{ row.proposal }}</span></p><details><summary>{{ t("Exact stored source evidence") }}</summary><pre lang="">{{ sourceText(row.evidence) }}</pre></details>
            @if (row.review) { <p>{{ t("Human priority") }} <span lang="en">{{ row.review.priority }}</span> {{ t("· revision") }} <span lang="en">{{ row.review.revision }}</span> · <span lang="">{{ row.review.reason }}</span>{{ t(". This is not an approved website change.") }}</p> }
            @if (canReview() && row.source_current) {
              <form (submit)="review($event, row)">
                <label [for]="'discoverability-priority-' + row.id">{{ t("Human priority") }}</label><select [id]="'discoverability-priority-' + row.id" name="priority" required>
                  <option value="unprioritized">{{ t("Unprioritized") }}</option><option value="low">{{ t("Low") }}</option><option value="medium">{{ t("Medium") }}</option><option value="high">{{ t("High") }}</option></select>
                <label [for]="'discoverability-effort-' + row.id">{{ t("Estimated human effort") }}</label><select [id]="'discoverability-effort-' + row.id" name="effort"><option value="unknown">{{ t("Unknown") }}</option><option value="small">{{ t("Small") }}</option><option value="medium">{{ t("Medium") }}</option><option value="large">{{ t("Large") }}</option></select>
                <label [for]="'discoverability-value-' + row.id">{{ t("Human business relevance") }}</label><select [id]="'discoverability-value-' + row.id" name="value"><option value="unknown">{{ t("Unknown") }}</option><option value="low">{{ t("Low") }}</option><option value="medium">{{ t("Medium") }}</option><option value="high">{{ t("High") }}</option></select>
                <label [for]="'discoverability-reason-' + row.id">{{ t("Source-based human rationale") }}</label><textarea lang="" [id]="'discoverability-reason-' + row.id" name="reason" required maxlength="240"></textarea>
                <button type="submit" [disabled]="busy()">{{ t("Save human priority, then propose a separately approved action") }}</button>
              </form>
            }
          </li>
        } @empty { <li>{{ t("No recorded technical proposals for the selected source. Choose a stored snapshot and explicitly record candidates; absence here does not prove accessibility or AI visibility.") }}</li> }</ul>
        <h2>{{ t("Human factual concerns — not verified business truth") }}</h2>
        <p>{{ t("No approved business-fact registry exists. Check business records and original expertise before changing content; missing concerns are not factual approval.") }}</p>
        <ul>@for (row of data.human_factual_concerns; track row.review_id + ':' + $index) {
          <li>{{ t("Sample") }} <span lang="en">{{ row.job_id }}</span> {{ t("· collection") }} <span [attr.lang]="row.collected_at ? 'en' : uiLanguage()">{{ row.collected_at || t("unknown") }}</span> {{ t("· human review") }} <span lang="en">{{ row.reviewed_at }}</span> {{ t("revision") }} <span lang="en">{{ row.review_revision }}</span> · {{ row.source_current ? t("current context") : t("historical/changed context") }}.
            <pre><span lang="">{{ row.text }}</span></pre><p><span lang="">{{ row.note }}</span></p><p><span lang="">{{ row.proposal }}</span></p>
            <a [routerLink]="['/app/visibility-samples', organizationId, projectId, row.job_id]">{{ t("Inspect authenticated exact answer and correction") }}</a></li>
        } @empty { <li>{{ t("No latest human factual-concern evidence in this bounded view.") }}</li> }</ul>
        <h2>{{ t("Exact current content records — live-page quality unverified") }}</h2>
        <ul>@for (row of data.content_revisions; track row.item_id) {
          <li><span lang="">{{ row.title }}</span> {{ t("· item") }} <span lang="en">{{ row.item_id }}</span> {{ t("revision") }} <span lang="en">{{ row.revision }}</span> {{ t("(record") }} <span lang="en">{{ row.revision_id }}</span>) · <span lang="en">{{ row.state }}</span> · <span lang="en">{{ row.created_at }}</span>{{ t(". Linked brief") }} <span lang="en">{{ row.brief_id }}</span> {{ t("· exact reviewed text record") }} <span [attr.lang]="row.reviewed_revision_id === null ? uiLanguage() : 'en'">{{ row.reviewed_revision_id ?? t("none") }}</span>.<p><span lang="">{{ row.proposal }}</span></p>
            <a [routerLink]="['/app/content', organizationId, projectId]">{{ t("Inspect content, linked brief/sources and human review") }}</a></li>
        } @empty { <li>{{ t("No stored content revisions. Genuine usefulness/entity accuracy remains unknown.") }}</li> }</ul>
      }
      <button type="button" [disabled]="loading() || busy()" (click)="load(selectedId)">{{ t("Refresh current source scope") }}</button>
    </section>`,
  styles: `section,li { overflow-wrap:anywhere } pre { white-space:pre-wrap } form { display:grid; gap:.5rem; max-width:42rem } button { margin:.6rem .6rem .6rem 0 } select { max-width:100% }`,
})
export class VisibilityDiscoverability implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  t(text: string) { return this.uiLanguage() === 'tr' ? discoverabilityTurkish[text] ?? text : text; }
  organizationId = 0; projectId = 0; selectedId: number | null = null; private generation = 0;
  readonly loading = signal(true); readonly busy = signal(false); readonly error = signal(''); readonly name = signal('');
  readonly evidence = signal<Evidence | null>(null); readonly canReview = signal(false);
  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi, private readonly destroy: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t('Private discoverability proposals')} — OrganicSEOOps`));
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
  sourceText(value: unknown) { return JSON.stringify(value, null, 2); }
  selectedSource() { return this.evidence()?.diagnostics.find((row) => row.id === this.selectedId); }
  async load(id: number | null = null) {
    const generation = ++this.generation; this.selectedId = id; this.loading.set(true); this.busy.set(false); this.error.set('');
    this.evidence.set(null); this.name.set(''); this.canReview.set(false);
    try {
      const context = await this.api.projectOnboarding(this.organizationId, this.projectId);
      if (generation !== this.generation) return;
      const project = context.body['project'] as Record<string, unknown> | undefined;
      if (context.status !== 200 || project?.['id'] !== this.projectId || project['organization_id'] !== this.organizationId
          || typeof project['role'] !== 'string' || !['owner', 'admin', 'member', 'viewer'].includes(project['role'])) throw new Error();
      const response = await this.api.visibilityDiscoverability(this.organizationId, this.projectId, id); const data = response.body as unknown as Evidence;
      if (generation !== this.generation) return;
      if (response.status !== 200 || data.project_id !== this.projectId || data.method !== 'visibility-discoverability-v1' || data.selected_diagnostics_id !== id
        || !['diagnostics', 'proposals', 'human_factual_concerns', 'content_revisions'].every((key) => Array.isArray(response.body[key])
          && (response.body[key] as { project_id: number }[]).every((row) => row.project_id === this.projectId))) throw new Error();
      this.name.set(String(project['name'])); this.canReview.set(['owner', 'admin'].includes(project['role'])); this.evidence.set(data);
    } catch { if (generation === this.generation) this.error.set('Discoverability source evidence unavailable or access revoked. Refresh current scope.'); }
    finally { if (generation === this.generation) this.loading.set(false); }
  }
  async materialize() {
    if (this.busy() || !this.canReview() || !this.selectedSource()?.source_current || !this.selectedId) return;
    await this.write(() => this.api.recordTechnicalFindings(this.organizationId, this.projectId, this.selectedId!));
  }
  async review(event: SubmitEvent, row: Proposal) {
    event.preventDefault(); const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || this.busy() || !this.canReview() || !row.source_current) return;
    const fields = new FormData(form);
    await this.write(() => this.api.reviewFinding(this.organizationId, this.projectId, row.id, row.review?.revision ?? 0,
      String(fields.get('priority')), String(fields.get('effort')), String(fields.get('value')), String(fields.get('reason'))));
  }
  private async write(request: () => ReturnType<AccountApi['reviewFinding']>) {
    const generation = this.generation; const id = this.selectedId; this.busy.set(true); this.error.set('');
    try {
      const response = await request(); if (generation !== this.generation) return;
      if (response.status !== 201 || response.body['project_id'] !== this.projectId) throw new Error();
      await this.load(id);
    } catch { if (generation === this.generation) { this.evidence.set(null); this.error.set('Human decision not confirmed. Reload source/current review before retrying; no website change or approval occurred.'); } }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
}
