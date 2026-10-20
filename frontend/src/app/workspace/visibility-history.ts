import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, OnInit, computed, effect, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi } from '../account/account-api';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';

type Observation = { id: number; project_id: number; comparison_key: string; context: Record<string, unknown>;
  schedule_id?: number | null; scheduled_for?: string | null;
  status: string; error_category: string; created_at: string; collected_at: string | null; evaluation: string;
  review_revision: number | null; reviewed_at: string | null; changes_from_prior_page_observation: string[];
  prior_context: string; answer_evidence_available: boolean };
type History = { method: string; project_id: number; observations: Observation[]; comparison_groups: { key: string; sample_ids: number[] }[];
  has_more: boolean; next_before_id: number | null; rate_scope: string;
  referrals: { status: string; visits: null; conversions: null; revenue: null; reason: string } };

const visibilityHistoryTurkish: Record<string, string> = {
  "Private comparable API observation history": "Özel karşılaştırılabilir API gözlem geçmişi",
  "Private like-for-like API observation history": "Özel aynı koşullu API gözlem geçmişi",
  "Project evidence": "Proje kanıtları",
  "Prompt methodology": "İstem metodolojisi",
  "Samples and exact-methodology rates": "Örnekler ve tam metodoloji oranları",
  "Source-supported discoverability proposals": "Kaynakla desteklenen keşfedilebilirlik önerileri",
  "Separate human reports and denominators": "Ayrı insan raporları ve paydalar",
  "Native API samples are not consumer ChatGPT sessions, global share, visits or causal improvement. Changed prompt, model, account, token ceiling or entity-review context creates a different comparison group. History-page groups are not rate denominators. Inspect sample evidence for exact-methodology eligible IDs, numerators and denominators.": "Yerel API örnekleri tüketici ChatGPT oturumları, küresel pay, ziyaretler veya nedensel iyileşme değildir. Değişen istem, model, hesap, token üst sınırı veya varlık inceleme bağlamı farklı bir karşılaştırma grubu oluşturur. Geçmiş sayfası grupları oran paydaları değildir. Tam metodolojiye uygun kimlikler, paylar ve paydalar için örnek kanıtını inceleyin.",
  "Loading private observation page.": "Özel gözlem sayfası yükleniyor.",
  "Active project:": "Aktif proje:",
  "(organization": "(kuruluş",
  ", project": ", proje",
  "Identifiable AI referrals — unavailable": "Tanımlanabilir AI yönlendirmeleri — kullanılamıyor",
  "No authorized exact-origin analytics/referrer/campaign grain. Visits, conversions and revenue are unavailable, not zero. Direct/unknown traffic and answer mentions never create inferred AI visits. Consent, missing referrers and attribution gaps limit any future source.": "Yetkilendirilmiş tam kökenli analitik/yönlendiren/kampanya ayrıntı düzeyi yok. Ziyaretler, dönüşümler ve gelir kullanılamıyor; sıfır değildir. Doğrudan/bilinmeyen trafik ve yanıt anmaları hiçbir zaman çıkarımla AI ziyaretleri oluşturmaz. Onay, eksik yönlendirenler ve ilişkilendirme boşlukları gelecekteki kaynakları sınırlar.",
  "Dated observations (up to20 on this page)": "Tarihli gözlemler (bu sayfada en fazla20)",
  "Comparison groups on this page:": "Bu sayfadaki karşılaştırma grupları:",
  ". Older-page context is not inferred. Latest human corrections annotate original collection dates retrospectively; they do not rewrite collection time.": ". Eski sayfa bağlamı çıkarılmaz. Son insan düzeltmeleri özgün toplama tarihlerini geriye dönük açıklar; toplama zamanını yeniden yazmaz.",
  "Sample": "Örnek",
  "Attempt created": "Deneme oluşturuldu",
  ". Original collection": ". Özgün toplama",
  "unavailable": "kullanılamıyor",
  ". Latest human review": ". Son insan incelemesi",
  "not reviewed": "incelenmedi",
  "· revision": "· revizyon",
  "none": "yok",
  "Repeat schedule": "Tekrar zamanlaması",
  "none; manual": "yok; manuel",
  "· occurrence": "· oluşum",
  "manual request": "manuel istek",
  "Collection issue:": "Toplama sorunu:",
  "; not a valid negative.": "; geçerli bir olumsuz sonuç değildir.",
  "Comparable context key:": "Karşılaştırılabilir bağlam anahtarı:",
  "Predecessor not loaded on this page; changes are unknown.": "Önceki gözlem bu sayfada yüklenmedi; değişiklikler bilinmiyor.",
  "Changes from observed predecessor on this page:": "Bu sayfada gözlenen önceki gözlemden değişiklikler:",
  "none; same comparable context": "yok; aynı karşılaştırılabilir bağlam",
  "Exact comparison settings (not applied location/language guarantees)": "Tam karşılaştırma ayarları (uygulanan konum/dil garantisi değil)",
  "unavailable / unreviewed": "kullanılamıyor / incelenmedi",
  "Answer evidence": "Yanıt kanıtı",
  "recorded; inspect private evidence": "kaydedildi; özel kanıtı inceleyin",
  "unavailable; not a negative observation": "kullanılamıyor; olumsuz gözlem değil",
  ". Citation measurement unavailable on this no-tool surface.": ". Bu araçsız yüzeyde atıf ölçümü kullanılamıyor.",
  "Inspect authenticated sample": "Kimliği doğrulanmış örneği inceleyin:",
  "and its denominators": "ve paydaları",
  "No observation attempts on this page. Visibility remains unavailable.": "Bu sayfada gözlem denemesi yok. Görünürlük kullanılamaz kalır.",
  "Load older observation page": "Daha eski gözlem sayfasını yükleyin",
  "Return to newest page": "En yeni sayfaya dönün",
  "Refresh this history page": "Bu geçmiş sayfasını yenileyin",
  "History unavailable or project access denied/revoked. Refresh to recheck the current scope.": "Geçmiş kullanılamıyor veya proje erişimi reddedildi/iptal edildi. Güncel kapsamı yeniden kontrol etmek için yenileyin.",
  "Unreviewed Turkish API observation-history interface draft in local development. Original context fields and evidence retain their original language; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe API gözlem geçmişi arayüzü taslağı. Özgün bağlam alanları ve kanıtlar özgün dillerini korur; iki dilli onay bekleniyor."
};

@Component({
  selector: 'app-visibility-history', imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="history-title">
      <h1 id="history-title">{{ t("Private like-for-like API observation history") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish API observation-history interface draft in local development. Original context fields and evidence retain their original language; bilingual approval is pending.") }}</p> }
      <p><a [routerLink]="['/app/dashboard', organizationId, projectId]">{{ t("Project evidence") }}</a> ·
        <a [routerLink]="['/app/visibility', organizationId, projectId]">{{ t("Prompt methodology") }}</a> ·
        <a [routerLink]="['/app/visibility-samples', organizationId, projectId]">{{ t("Samples and exact-methodology rates") }}</a> ·
        <a [routerLink]="['/app/visibility-discoverability', organizationId, projectId]">{{ t("Source-supported discoverability proposals") }}</a> ·
        <a [routerLink]="['/app/visibility-manual', organizationId, projectId]">{{ t("Separate human reports and denominators") }}</a></p>
      <p>{{ t("Native API samples are not consumer ChatGPT sessions, global share, visits or causal improvement. Changed prompt, model, account, token ceiling or entity-review context creates a different comparison group. History-page groups are not rate denominators. Inspect sample evidence for exact-methodology eligible IDs, numerators and denominators.") }}</p>
      @if (loading()) { <p role="status">{{ t("Loading private observation page.") }}</p> }
      @if (error()) { <p role="alert" [attr.lang]="t(error()) === error() ? 'en' : uiLanguage()">{{ t(error()) }}</p> }
      @if (history(); as page) {
        <p>{{ t("Active project:") }} <span lang="">{{ name() }}</span> {{ t("(organization") }} <span lang="en">{{ organizationId }}</span>{{ t(", project") }} <span lang="en">{{ projectId }}</span>).</p>
        <h2>{{ t("Identifiable AI referrals — unavailable") }}</h2>
        <p>{{ t("No authorized exact-origin analytics/referrer/campaign grain. Visits, conversions and revenue are unavailable, not zero. Direct/unknown traffic and answer mentions never create inferred AI visits. Consent, missing referrers and attribution gaps limit any future source.") }}</p>
        <h2>{{ t("Dated observations (up to20 on this page)") }}</h2>
        <p>{{ t("Comparison groups on this page:") }} <span lang="en">{{ page.comparison_groups.length }}</span>{{ t(". Older-page context is not inferred. Latest human corrections annotate original collection dates retrospectively; they do not rewrite collection time.") }}</p>
        <ol>@for (row of page.observations; track row.id) {
          <li><h3>{{ t("Sample") }} <span lang="en">{{ row.id }}</span> · <span lang="en">{{ row.status }}</span> · <span lang="en">{{ row.evaluation }}</span></h3>
            <p>{{ t("Attempt created") }} <span lang="en">{{ row.created_at }}</span>{{ t(". Original collection") }} <span [attr.lang]="row.collected_at ? 'en' : uiLanguage()">{{ row.collected_at || t("unavailable") }}</span>{{ t(". Latest human review") }} <span [attr.lang]="row.reviewed_at ? 'en' : uiLanguage()">{{ row.reviewed_at || t("not reviewed") }}</span> {{ t("· revision") }} <span [attr.lang]="row.review_revision !== null && row.review_revision !== undefined ? 'en' : uiLanguage()">{{ row.review_revision ?? t("none") }}</span>.</p>
            <p>{{ t("Repeat schedule") }} <span [attr.lang]="row.schedule_id !== null && row.schedule_id !== undefined ? 'en' : uiLanguage()">{{ row.schedule_id ?? t("none; manual") }}</span> {{ t("· occurrence") }} <span [attr.lang]="row.scheduled_for ? 'en' : uiLanguage()">{{ row.scheduled_for || t("manual request") }}</span>.</p>
            @if (row.error_category) { <p>{{ t("Collection issue:") }} <span lang="en">{{ row.error_category }}</span>{{ t("; not a valid negative.") }}</p> }
            <p>{{ t("Comparable context key:") }} <span lang="en">{{ row.comparison_key }}</span>.</p>
            @if (row.prior_context === 'not_loaded') { <p>{{ t("Predecessor not loaded on this page; changes are unknown.") }}</p> }
            @else { <p>{{ t("Changes from observed predecessor on this page:") }} <span [attr.lang]="row.changes_from_prior_page_observation.length ? 'en' : uiLanguage()">{{ changes(row) || t("none; same comparable context") }}</span>.</p> }
            <details><summary>{{ t("Exact comparison settings (not applied location/language guarantees)") }}</summary>
              <dl>@for (entry of settings(row); track entry[0]) { <dt><span lang="en">{{ label(entry[0]) }}</span></dt><dd><span [attr.lang]="entry[1] === null ? uiLanguage() : ''">{{ entry[1] ?? t("unavailable / unreviewed") }}</span></dd> }</dl>
            </details>
            <p>{{ t("Answer evidence") }} {{ row.answer_evidence_available ? t("recorded; inspect private evidence") : t("unavailable; not a negative observation") }}{{ t(". Citation measurement unavailable on this no-tool surface.") }}</p>
            <a [routerLink]="['/app/visibility-samples', organizationId, projectId, row.id]">{{ t("Inspect authenticated sample") }} <span lang="en">{{ row.id }}</span> {{ t("and its denominators") }}</a>
          </li>
        } @empty { <li>{{ t("No observation attempts on this page. Visibility remains unavailable.") }}</li> }</ol>
        @if (page.has_more) { <button type="button" [disabled]="loading()" (click)="load(page.next_before_id)">{{ t("Load older observation page") }}</button> }
        @if (beforeId !== null) { <button type="button" [disabled]="loading()" (click)="load()">{{ t("Return to newest page") }}</button> }
      }
      <button type="button" [disabled]="loading()" (click)="load(beforeId)">{{ t("Refresh this history page") }}</button>
    </section>`,
  styles: `section,li { overflow-wrap:anywhere } li { margin-block:1rem } dt { font-weight:600 } dd { margin-block-end:.5rem } button { margin:.6rem .6rem .6rem 0 }`,
})
export class VisibilityHistory implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  t(text: string) { return this.uiLanguage() === 'tr' ? visibilityHistoryTurkish[text] ?? text : text; }
  organizationId = 0; projectId = 0; beforeId: number | null = null; private generation = 0;
  readonly history = signal<History | null>(null); readonly name = signal(''); readonly error = signal(''); readonly loading = signal(true);
  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi, private readonly destroy: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t('Private comparable API observation history')} — OrganicSEOOps`));
  }
  ngOnInit() {
    void this.loadProductLanguage();
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroy)).subscribe((params) => {
      this.organizationId = Number(params.get('organizationId')); this.projectId = Number(params.get('projectId')); void this.load();
    }); this.destroy.onDestroy(() => ++this.generation);
  }
  private async loadProductLanguage() {
    try {
      const result = await this.api.productLanguage();
      if (!this.destroy.destroyed && result.status === 200 && isProductLanguageResult(result.body)) {
        this.productLanguage.set(result.body['language']);
      }
    } catch { /* Keep English when the private preference is unavailable. */ }
  }
  label(field: string) { return field.replaceAll('_', ' '); }
  settings(row: Observation) { return Object.entries(row.context).map(([key, value]) => [key, value !== null && typeof value === 'object' ? JSON.stringify(value) : value] as const); }
  changes(row: Observation) { return row.changes_from_prior_page_observation.map((field) => this.label(field)).join(', '); }
  async load(before: number | null = null) {
    const generation = ++this.generation; this.beforeId = before;
    this.history.set(null); this.name.set(''); this.error.set(''); this.loading.set(true);
    try {
      const context = await this.api.projectOnboarding(this.organizationId, this.projectId);
      if (generation !== this.generation) return;
      const project = context.body['project'] as Record<string, unknown> | undefined;
      if (context.status !== 200 || project?.['id'] !== this.projectId || project['organization_id'] !== this.organizationId) throw new Error();
      const response = await this.api.visibilityHistory(this.organizationId, this.projectId, before); const page = response.body as unknown as History;
      if (generation !== this.generation) return;
      if (response.status !== 200 || page.project_id !== this.projectId || page.method !== 'visibility-history-v1'
        || !Array.isArray(page.observations) || page.observations.length > 20 || !Array.isArray(page.comparison_groups)
        || page.observations.some((row, index, rows) => row.project_id !== this.projectId || !Number.isSafeInteger(row.id) || row.id < 1
          || before !== null && row.id >= before || index > 0 && row.id >= rows[index - 1].id
          || typeof row.comparison_key !== 'string' || !row.context || !Array.isArray(row.changes_from_prior_page_observation))
        || page.referrals?.status !== 'unavailable' || page.referrals.visits !== null || page.referrals.conversions !== null || page.referrals.revenue !== null
        || (page.has_more ? !page.observations.length || page.next_before_id !== page.observations.at(-1)?.id : page.next_before_id !== null)) throw new Error();
      this.name.set(String(project['name'])); this.history.set(page);
    } catch { if (generation === this.generation) this.error.set('History unavailable or project access denied/revoked. Refresh to recheck the current scope.'); }
    finally { if (generation === this.generation) this.loading.set(false); }
  }
}
