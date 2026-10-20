import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, OnInit, computed, effect, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi, ApiResult, ProjectInfo, ProjectSourceInfo } from '../account/account-api';
import { same } from './authority-links';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';

const positive = (value: unknown) => Number.isSafeInteger(value) && Number(value) > 0;
const integer = (value: unknown) => Number.isSafeInteger(value) && Number(value) >= 0;
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const digest = (value: unknown) => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const dated = (value: unknown): value is string => typeof value === 'string' && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value)
  && Number.isFinite(Date.parse(value)) && Date.parse(value) <= Date.now();
const day = (value: unknown): value is string => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)
  && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
const states = ['queued', 'running', 'succeeded', 'partially_succeeded', 'cancelled', 'failed'];
type Snapshot = { id: number; start_row: number; result_sha256: string; collected_at: string };
type Job = { id: number; status: string; day: string; property: string; grant_revision: number; created_at: string;
  source_current: boolean; requests_attempted: number; pages_recorded: number; error_category: string; snapshots: Snapshot[] };
type Observation = { query: string; page: string; clicks: number; impressions: number; ctr: string; position: string };
type Page = Snapshot & { result: Record<string, unknown> & { day: string; timezone: string; observations: Observation[] } };
type Candidate = { query: string; evidence: { snapshot_id: number; result_sha256: string; row_index: number }[]; classification: string };
type Evidence = { job: Job; pages: Page[]; candidates: Candidate[]; candidate_state: string; candidates_truncated: boolean };
type Pending = { source: ProjectSourceInfo; data: Record<string, unknown> };
function identity(source: ProjectSourceInfo) {
  return { id: source.id, provider: source.provider, property: source.property, state: source.state,
    scope_current: source.scope_current, scope_kind: source.scope_kind, query_page_available: source.query_page_available,
    query_page_grant_id: source.query_page_grant_id, query_page_grant_revision: source.query_page_grant_revision };
}
function sorted(value: unknown): unknown {
  return Array.isArray(value) ? value.map(sorted) : object(value)
    ? Object.fromEntries(Object.keys(value).sort().map((key) => [key, sorted(value[key])])) : value;
}
async function sha256(value: unknown) {
  const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(sorted(value))));
  return Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, '0')).join('');
}
function ownPage(value: unknown, origin: string) {
  if (typeof value !== 'string' || value.length > 2048 || /[\s\\]/.test(value)) return false;
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && url.origin === origin
    && !url.username && !url.password && !url.search && !url.hash && url.href === value; }
  catch { return false; }
}
function isJob(value: unknown): value is Job {
  if (!object(value)) return false;
  const row = value as unknown as Job;
  return positive(row.id) && states.includes(row.status) && day(row.day) && typeof row.property === 'string'
    && integer(row.grant_revision) && dated(row.created_at) && typeof row.source_current === 'boolean'
    && integer(row.requests_attempted) && row.requests_attempted <= 3 && integer(row.pages_recorded) && row.pages_recorded <= 2
    && typeof row.error_category === 'string' && Array.isArray(row.snapshots) && row.snapshots.length <= 2
    && row.snapshots.every((page, index) => page && positive(page.id) && page.start_row === index * 100
      && digest(page.result_sha256) && dated(page.collected_at) && Date.parse(page.collected_at) >= Date.parse(row.created_at));
}

const searchQueryPagesTurkish: Record<string, string> = {
  "Private genuine query–page evidence": "Özel gerçek sorgu–sayfa kanıtı",
  "Genuine paired Search Console query–page evidence": "Gerçek eşlenmiş Search Console sorgu–sayfa kanıtı",
  "Organization": "Kuruluş",
  "· project": "· proje",
  "Source setup": "Kaynak kurulumu",
  "Separate human intent and preferred-page review": "Ayrı insan amaç ve tercih edilen sayfa incelemesi",
  "Separate site action approval and dated outcomes": "Ayrı site eylemi onayı ve tarihli sonuçlar",
  "Actual ordered query and page keys from the same report, never joined independent exports. One finalized Pacific-source day aged 3–90 days, web search, automatic request aggregation and actual byPage evidence. URL-prefix exact origins only; domain-wide paired reports are unavailable. At most three attempted internal units, two 100-row pages, no automatic paging beyond that ceiling or recurring collection.": "Aynı rapordan gerçek sıralı sorgu ve sayfa anahtarları; bağımsız dışa aktarmalar asla birleştirilmez. 3–90 gün yaşında tek kesinleşmiş Pasifik kaynak günü, web araması, otomatik istek toplulaştırması ve gerçek byPage kanıtı. Yalnızca URL öneki tam kökenleri; alanın tamamına ait eşlenmiş raporlar kullanılamıyor. En fazla üç denenmiş dahili birim, iki 100 satırlık sayfa; bu sınırın ötesinde otomatik sayfalama veya tekrarlanan toplama yoktur.",
  "Hidden queries and provider completeness remain unknown. Average position is not live rank. Positive same-query/distinct-page observations are human-review candidates, not proven intent conflict, causal traffic loss, complete demand or deletion justification. Publication-age and exact-origin conversion evidence remain unavailable.": "Gizli sorgular ve sağlayıcı bütünlüğü bilinmiyor. Ortalama konum canlı sıralama değildir. Aynı sorgu/farklı sayfa olumlu gözlemleri, insan inceleme adaylarıdır; kanıtlanmış amaç çatışması, nedensel trafik kaybı, tam talep veya silme gerekçesi değildir. Yayın yaşı ve tam köken dönüşüm kanıtı kullanılamıyor.",
  "Checking current source, saved job and private evidence.": "Güncel kaynak, kayıtlı iş ve özel kanıt kontrol ediliyor.",
  "Refresh current project and sources": "Güncel projeyi ve kaynakları yenileyin",
  "Request acknowledgment is uncertain. Exact source, day and key are frozen in this component's memory only. No automatic replay.": "İstek alındı bilgisi belirsiz. Tam kaynak, gün ve anahtar yalnızca bu bileşenin belleğinde sabitlenir. Otomatik yeniden yürütme yoktur.",
  "Look up this exact saved request": "Bu kayıtlı tam isteği arayın",
  "Deliberately retry the same exact request": "Aynı tam isteği bilinçli olarak tekrar deneyin",
  "No current configured URL-prefix query–page source is available. Check source setup; missing data is not zero.": "Güncel yapılandırılmış URL öneki sorgu–sayfa kaynağı kullanılamıyor. Kaynak kurulumunu kontrol edin; eksik veri sıfır değildir.",
  "Actual current URL-prefix source": "Gerçek güncel URL öneki kaynağı",
  "Choose one source": "Tek kaynak seçin",
  "· connection": "· bağlantı",
  "· grant revision": "· izin sürümü",
  "Deliberate bounded paired collection": "Bilinçli sınırlı eşlenmiş toplama",
  "Finalized Pacific reporting day": "Kesinleşmiş Pasifik raporlama günü",
  "Request this exact paired report (up to 3 units)": "Bu tam eşlenmiş raporu isteyin (en fazla 3 birim)",
  "Refresh saved paired jobs only": "Yalnızca kayıtlı eşlenmiş işleri yenileyin",
  "Exact saved paired job": "Tam kayıtlı eşlenmiş iş",
  "Choose saved evidence": "Kayıtlı kanıtı seçin",
  "Job": "İş",
  "Inspect exact private paired evidence": "Tam özel eşlenmiş kanıtı inceleyin",
  "attempted requests ·": "denenen istek ·",
  "pages ·": "sayfa ·",
  "Cancel this request": "Bu isteği iptal edin",
  "No saved paired jobs loaded. Refresh saved jobs explicitly; this does not collect data.": "Kayıtlı eşlenmiş iş yüklenmedi. Kayıtlı işleri açıkça yenileyin; bu, veri toplamaz.",
  "Only the newest 20 jobs are shown; history coverage is incomplete.": "Yalnızca en yeni 20 iş gösterilir; geçmiş kapsamı eksiktir.",
  "Exact private job": "Tam özel iş",
  "Source": "Kaynak",
  "· original grant revision": "· özgün izin sürümü",
  ". Current as of checked readback, not a lasting authorization.": ". Kontrol edilmiş geri okuma anında güncel; kalıcı yetkilendirme değil.",
  "Actual source snapshot": "Gerçek kaynak anlık görüntüsü",
  "· offset": "· ofset",
  "Collected": "Toplandı",
  "· SHA256": "· SHA256",
  "· provider rows": "· sağlayıcı satırları",
  "· unsafe/outside-origin rows omitted": "· atlanan güvensiz/köken dışı satırlar",
  ". Provider completeness not established; hidden queries unknown.": ". Sağlayıcı bütünlüğü kanıtlanmadı; gizli sorgular bilinmiyor.",
  "· clicks": "· tıklama",
  "· impressions": "· gösterim",
  "· CTR fraction": "· CTR oranı",
  "· average position": "· ortalama konum",
  "(not live rank).": "(canlı sıralama değil).",
  "Bounded positive overlap candidates": "Sınırlı olumlu örtüşme adayları",
  "No positive overlap in inspected bounded rows; this is not evidence of absence or zero demand.": "İncelenen sınırlı satırlarda olumlu örtüşme yok; bu, yokluk veya sıfır talep kanıtı değildir.",
  "· same exact query on distinct own pages, human review only.": "· farklı kendi sayfalarında aynı tam sorgu, yalnızca insan incelemesi.",
  "Snapshot": "Anlık görüntü",
  "· row": "· satır",
  "Only the first 20 positive candidate groups are shown.": "Yalnızca ilk 20 olumlu aday grubu gösterilir.",
  "No intent mapping, action, approval or site change was created by inspection. Review business intent and page usefulness independently.": "İnceleme; amaç eşlemesi, eylem, onay veya site değişikliği oluşturmadı. İş amacını ve sayfa yararlılığını bağımsız inceleyin.",
  "no reported error": "bildirilen hata yok",
  "local row ceiling reached": "yerel satır sınırına ulaşıldı",
  "local ceiling not reported": "yerel sınır bildirilmedi",
  "Choose an authorized project.": "Yetkili bir proje seçin.",
  "Current owner/admin source scope unavailable. Refresh before proceeding.": "Güncel sahip/yönetici kaynak kapsamı kullanılamıyor. Devam etmeden önce yenileyin.",
  "Saved metadata or current source unavailable; no provider request was made.": "Kayıtlı üst veriler veya güncel kaynak kullanılamıyor; sağlayıcı isteği yapılmadı.",
  "Exact current source, saved metadata, original dates or paired digest changed. No usable evidence; refresh.": "Tam güncel kaynak, kayıtlı üst veriler, özgün tarihler veya eşlenmiş özet değişti. Kullanılabilir kanıt yok; yenileyin.",
  "Choose a finalized Pacific reporting day.": "Kesinleşmiş bir Pasifik raporlama günü seçin.",
  "Paired request saved. Explicitly refresh saved jobs for progress; no automatic collection or inspection.": "Eşlenmiş istek kaydedildi. İlerleme için kayıtlı işleri açıkça yenileyin; otomatik toplama veya inceleme yoktur.",
  "Request denied, stale source, invalid finalized day or allowance reached. Refresh source state.": "İstek reddedildi, kaynak eski, kesinleşmiş gün geçersiz veya kullanım hakkına ulaşıldı. Kaynak durumunu yenileyin.",
  "Request acknowledgment uncertain. Look up the exact request before deliberate retry.": "İstek alındı bilgisi belirsiz. Bilinçli tekrar denemeden önce tam isteği arayın.",
  "Source or role changed before dispatch; no request sent.": "Kaynak veya rol gönderimden önce değişti; istek gönderilmedi.",
  "No saved request found at this check; only deliberate same-key retry is available.": "Bu kontrolde kayıtlı istek bulunamadı; yalnızca aynı anahtarla bilinçli tekrar deneme kullanılabilir.",
  "Exact saved request reconciled without replay.": "Kayıtlı tam istek yeniden yürütülmeden uzlaştırıldı.",
  "Exact acknowledgment or current source unavailable. No replay.": "Tam alındı bilgisi veya güncel kaynak kullanılamıyor. Yeniden yürütme yoktur.",
  "Cancellation requested; explicitly refresh saved status.": "İptal istendi; kayıtlı durumu açıkça yenileyin.",
  "Cancellation acknowledgment unavailable; refresh saved status before another action.": "İptal alındı bilgisi kullanılamıyor; başka eylemden önce kayıtlı durumu yenileyin.",
  "Cancellation outcome unavailable. Inspect saved status; no automatic retry.": "İptal sonucu kullanılamıyor. Kayıtlı durumu inceleyin; otomatik tekrar deneme yoktur.",
  "Saved paired request status": "Kayıtlı eşlenmiş istek durumu",
  "Actual paired rows": "Gerçek eşlenmiş satırlar",
  "Unreviewed Turkish paired query-page interface draft in local development. Queries and source text retain their original language; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe eşlenmiş sorgu-sayfa arayüzü taslağı. Sorgular ve kaynak metni özgün dillerini korur; iki dilli onay bekleniyor."
};

@Component({
  selector: 'app-search-query-pages', imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="paired-title">
      <h1 id="paired-title">{{ t("Genuine paired Search Console query–page evidence") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish paired query-page interface draft in local development. Queries and source text retain their original language; bilingual approval is pending.") }}</p> }
      <p>{{ t("Organization") }} <span lang="en">{{ organizationId }}</span> {{ t("· project") }} <span lang="en">{{ projectId }}</span> · <span lang="">{{ project()?.name }}</span> · <span lang="">{{ project()?.canonical_origin }}</span>.</p>
      <p><a [routerLink]="['/app/onboarding', organizationId, projectId]">{{ t("Source setup") }}</a> ·
        <a [routerLink]="['/app/intent', organizationId, projectId]">{{ t("Separate human intent and preferred-page review") }}</a> ·
        <a [routerLink]="['/app/actions', organizationId, projectId]">{{ t("Separate site action approval and dated outcomes") }}</a></p>
      <p>{{ t("Actual ordered query and page keys from the same report, never joined independent exports. One finalized Pacific-source day aged 3–90 days, web search, automatic request aggregation and actual byPage evidence. URL-prefix exact origins only; domain-wide paired reports are unavailable. At most three attempted internal units, two 100-row pages, no automatic paging beyond that ceiling or recurring collection.") }}</p>
      <p>{{ t("Hidden queries and provider completeness remain unknown. Average position is not live rank. Positive same-query/distinct-page observations are human-review candidates, not proven intent conflict, causal traffic loss, complete demand or deletion justification. Publication-age and exact-origin conversion evidence remain unavailable.") }}</p>
      @if (loading() || busy()) { <p role="status">{{ t("Checking current source, saved job and private evidence.") }}</p> }
      @if (error()) { <p role="alert" [attr.lang]="t(error()) === error() ? 'en' : uiLanguage()">{{ t(error()) }}</p> }
      @if (message()) { <p role="status" [attr.lang]="t(message()) === message() ? 'en' : uiLanguage()">{{ t(message()) }}</p> }
      <button type="button" (click)="load()" [disabled]="busy() || loading() || !!pending()">{{ t("Refresh current project and sources") }}</button>
      @if (pending()) {
        <p>{{ t("Request acknowledgment is uncertain. Exact source, day and key are frozen in this component's memory only. No automatic replay.") }}</p>
        <button type="button" (click)="reconcile()" [disabled]="busy()">{{ t("Look up this exact saved request") }}</button>
        @if (notFound()) { <button type="button" (click)="retry()" [disabled]="busy()">{{ t("Deliberately retry the same exact request") }}</button> }
      }
      @if (project()) {
        @if (!sources().length) { <p>{{ t("No current configured URL-prefix query–page source is available. Check source setup; missing data is not zero.") }}</p> }
        <label for="paired-source">{{ t("Actual current URL-prefix source") }}</label>
        <select id="paired-source" (change)="choose(+$any($event.target).value)" [disabled]="busy() || !!pending()">
          <option value="0" [selected]="!sourceId()">{{ t("Choose one source") }}</option>
          @for (source of sources(); track source.id) { <option lang="" [value]="source.id" [selected]="source.id === sourceId()">{{ source.property }} {{ t("· connection") }} {{ source.id }} {{ t("· grant revision") }} {{ source.query_page_grant_revision }}</option> }
        </select>
        @if (chosen(); as source) {
          <form (submit)="start($event)"><fieldset [disabled]="busy() || !!pending()"><legend>{{ t("Deliberate bounded paired collection") }}</legend>
            <label for="paired-day">{{ t("Finalized Pacific reporting day") }}</label><input lang="en" id="paired-day" name="day" type="date" required />
            <button type="submit">{{ t("Request this exact paired report (up to 3 units)") }}</button>
          </fieldset></form>
          <button type="button" (click)="history()" [disabled]="busy() || !!pending()">{{ t("Refresh saved paired jobs only") }}</button>
          @if (jobs().length) {
            <label for="paired-job">{{ t("Exact saved paired job") }}</label><select id="paired-job" (change)="chooseJob(+$any($event.target).value)" [disabled]="busy() || !!pending()">
              <option value="0" [selected]="!jobId()">{{ t("Choose saved evidence") }}</option>
              @for (job of jobs(); track job.id) { <option lang="en" [value]="job.id" [selected]="job.id === jobId()">Job {{ job.id }} · {{ job.day }} · {{ job.status }} · {{ job.source_current ? 'current at refresh' : 'stale/unavailable' }}</option> }
            </select>
            <button type="button" (click)="inspect()" [disabled]="busy() || !!pending() || !jobId()">{{ t("Inspect exact private paired evidence") }}</button>
            <ul [attr.aria-label]="t('Saved paired request status')">@for (job of jobs(); track job.id) {
              <li>{{ t("Job") }} <span lang="en">{{ job.id }}</span> · <span lang="en">{{ job.status }}</span> · <span lang="en">{{ job.day }}</span> · <span lang="en">{{ job.requests_attempted }}</span> {{ t("attempted requests ·") }} <span lang="en">{{ job.pages_recorded }}</span> {{ t("pages ·") }} <span [attr.lang]="job.error_category ? 'en' : uiLanguage()">{{ job.error_category || t("no reported error") }}</span>.
                @if (job.status === 'queued' || job.status === 'running') { <button type="button" (click)="cancel(job.id)" [disabled]="busy() || !!pending()">{{ t("Cancel this request") }}</button> }</li>
            }</ul>
          } @else { <p>{{ t("No saved paired jobs loaded. Refresh saved jobs explicitly; this does not collect data.") }}</p> }
          @if (historyMore()) { <p>{{ t("Only the newest 20 jobs are shown; history coverage is incomplete.") }}</p> }
        }
      }
      @if (evidence(); as info) {
        <h2>{{ t("Exact private job") }} <span lang="en">{{ info.job.id }}</span> · <span lang="en">{{ info.job.day }}</span> · <span lang="en">{{ info.job.status }}</span></h2>
        <p>{{ t("Source") }} <span lang="">{{ info.job.property }}</span> {{ t("· original grant revision") }} <span lang="en">{{ info.job.grant_revision }}</span>{{ t(". Current as of checked readback, not a lasting authorization.") }}</p>
        @for (page of info.pages; track page.id) {
          <h3>{{ t("Actual source snapshot") }} <span lang="en">{{ page.id }}</span> {{ t("· offset") }} <span lang="en">{{ page.start_row }}</span></h3>
          <p>{{ t("Collected") }} <span lang="en">{{ page.collected_at }}</span> · <span lang="en">{{ page.result.timezone }}</span> {{ t("· SHA256") }} <span lang="en">{{ page.result_sha256 }}</span> {{ t("· provider rows") }} <span lang="en">{{ page.result['rows_returned'] }}</span> {{ t("· unsafe/outside-origin rows omitted") }} <span lang="en">{{ page.result['omitted_pages'] }}</span> ·
            {{ page.result['truncated'] ? t("local row ceiling reached") : t("local ceiling not reported") }}{{ t(". Provider completeness not established; hidden queries unknown.") }}</p>
          <ul [attr.aria-label]="t('Actual paired rows')">@for (row of page.result.observations; track $index) {
            <li><span><span lang="">{{ row.query }}</span></span> → <span><span lang="">{{ row.page }}</span></span> {{ t("· clicks") }} <span lang="en">{{ row.clicks }}</span> {{ t("· impressions") }} <span lang="en">{{ row.impressions }}</span> {{ t("· CTR fraction") }} <span lang="en">{{ row.ctr }}</span> {{ t("· average position") }} <span lang="en">{{ row.position }}</span> {{ t("(not live rank).") }}</li>
          }</ul>
        }
        <h2>{{ t("Bounded positive overlap candidates") }}</h2>
        @if (!info.candidates.length) { <p>{{ t("No positive overlap in inspected bounded rows; this is not evidence of absence or zero demand.") }}</p> }
        <ul>@for (candidate of info.candidates; track candidate.query) {
          <li><span><span lang="">{{ candidate.query }}</span></span> {{ t("· same exact query on distinct own pages, human review only.") }}
            <ul>@for (ref of candidate.evidence; track ref.snapshot_id + ':' + ref.row_index) {
              <li>{{ t("Snapshot") }} <span lang="en">{{ ref.snapshot_id }}</span> {{ t("· row") }} <span lang="en">{{ ref.row_index }}</span> {{ t("· SHA256") }} <span lang="en">{{ ref.result_sha256 }}</span>.</li>
            }</ul></li>
        }</ul>
        @if (info.candidates_truncated) { <p>{{ t("Only the first 20 positive candidate groups are shown.") }}</p> }
        <p>{{ t("No intent mapping, action, approval or site change was created by inspection. Review business intent and page usefulness independently.") }}</p>
      }
    </section>`,
  styles: `form, fieldset { display: grid; gap: .6rem; margin-block: 1rem; } li { overflow-wrap: anywhere; margin-block: .7rem; } select, input { min-width: 0; max-width: 100%; }`,
})
export class SearchQueryPages implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  t(text: string) { return this.uiLanguage() === 'tr' ? searchQueryPagesTurkish[text] ?? text : text; }
  readonly project = signal<ProjectInfo | null>(null); readonly sources = signal<ProjectSourceInfo[]>([]);
  readonly sourceId = signal(0); readonly jobId = signal(0); readonly jobs = signal<Job[]>([]); readonly historyMore = signal(false);
  readonly evidence = signal<Evidence | null>(null); readonly loading = signal(false); readonly busy = signal(false);
  readonly error = signal(''); readonly message = signal(''); readonly pending = signal<Pending | null>(null); readonly notFound = signal(false);
  organizationId = 0; projectId = 0; private generation = 0;
  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi, private readonly destroy: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t('Private genuine query–page evidence')} — OrganicSEOOps`));
    destroy.onDestroy(() => { this.generation++; this.clear(); this.pending.set(null); });
  }
  ngOnInit() {
    void this.loadProductLanguage();
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroy)).subscribe((params) => {
      this.generation++; this.clear(); this.pending.set(null); this.notFound.set(false); this.busy.set(false); this.loading.set(false);
      this.organizationId = Number(params.get('organizationId')); this.projectId = Number(params.get('projectId'));
      if (positive(this.organizationId) && positive(this.projectId)) void this.load(); else this.error.set('Choose an authorized project.');
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
  private clear() { this.project.set(null); this.sources.set([]); this.sourceId.set(0); this.jobId.set(0); this.jobs.set([]); this.evidence.set(null); }
  chosen() { return this.sources().find((source) => source.id === this.sourceId()); }
  choose(id: number) { if (!this.busy() && !this.pending()) { this.sourceId.set(id); this.jobId.set(0); this.jobs.set([]); this.evidence.set(null); } }
  chooseJob(id: number) { if (!this.busy() && !this.pending()) { this.jobId.set(id); this.evidence.set(null); } }
  private async current() {
    const [setup, response] = await Promise.all([this.api.projectOnboarding(this.organizationId, this.projectId), this.api.projectSources(this.organizationId, this.projectId)]);
    const project = setup.body['project'] as ProjectInfo;
    if (setup.status !== 200 || !project || project.id !== this.projectId || project.organization_id !== this.organizationId
      || !['owner', 'admin'].includes(project.role) || !Array.isArray(project.aliases)
      || response.status !== 200 || response.body['project_id'] !== this.projectId || !Array.isArray(response.body['sources'])) throw new Error();
    const sources = (response.body['sources'] as ProjectSourceInfo[]).filter((source) => source.query_page_available === true);
    if (sources.length > 50 || !sources.every((source) => positive(source.id) && source.provider === 'google_search_console'
      && source.state === 'active' && source.scope_current && source.scope_kind === 'exact_origin_url_prefix'
      && [project.canonical_origin, ...project.aliases].includes(source.property)
      && positive(source.query_page_grant_id) && integer(source.query_page_grant_revision))) throw new Error();
    return structuredClone({ project, sources });
  }
  async load() {
    if (this.busy() || this.pending()) return;
    const generation = ++this.generation; this.clear(); this.loading.set(true); this.error.set(''); this.message.set('');
    try { const current = await this.current(); if (generation === this.generation) { this.project.set(current.project); this.sources.set(current.sources); } }
    catch { if (generation === this.generation) this.error.set('Current owner/admin source scope unavailable. Refresh before proceeding.'); }
    finally { if (generation === this.generation) this.loading.set(false); }
  }
  private readHistory(response: ApiResult, source: ProjectSourceInfo): Job[] {
    const body = response.body;
    if (response.status !== 200 || body['organization_id'] !== this.organizationId || body['project_id'] !== this.projectId
      || body['connection_id'] !== source.id || body['report'] !== 'query_page' || typeof body['has_more'] !== 'boolean'
      || !Array.isArray(body['jobs']) || body['jobs'].length > 20 || !body['jobs'].every(isJob)) throw new Error();
    this.historyMore.set(body['has_more']); return structuredClone(body['jobs'] as Job[]);
  }
  private async preflight(source: ProjectSourceInfo) {
    const context = await this.current();
    if (!context.sources.some((row) => same(identity(row), identity(source)))) throw new Error();
    return context;
  }
  async history() {
    const source = this.chosen(); if (!source || this.busy() || this.pending()) return;
    const frozen = structuredClone(source), generation = this.generation; this.busy.set(true); this.evidence.set(null); this.error.set('');
    try {
      await this.preflight(frozen); if (generation !== this.generation) return;
      const response = await this.api.searchConsoleQueryPages(this.organizationId, this.projectId, frozen.id);
      if (generation !== this.generation) return;
      const jobs = this.readHistory(response, frozen); await this.preflight(frozen);
      if (generation === this.generation) { this.jobs.set(jobs); this.jobId.set(0); }
    } catch { if (generation === this.generation) { this.jobs.set([]); this.error.set('Saved metadata or current source unavailable; no provider request was made.'); } }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  private async validateEvidence(response: ApiResult, source: ProjectSourceInfo, frozen: Job): Promise<Evidence> {
    const info = response.body as unknown as Evidence, body = response.body;
    if (response.status !== 200 || body['organization_id'] !== this.organizationId || body['project_id'] !== this.projectId
      || body['connection_id'] !== source.id || body['method'] !== 'gsc-query-page-overlap-v1' || !isJob(info.job)
      || !same(info.job, frozen) || !info.job.source_current || info.job.property !== source.property
      || info.job.grant_revision !== source.query_page_grant_revision || !['succeeded', 'partially_succeeded'].includes(info.job.status)
      || body['provider_completeness'] !== 'not_established' || body['hidden_queries'] !== 'unknown'
      || body['interpretation'] !== 'human_review_only_not_proven_intent_conflict_causal_loss_live_rank_complete_demand_or_deletion'
      || !Array.isArray(info.pages) || !info.pages.length || info.pages.length !== frozen.snapshots.length || info.pages.length > 2) throw new Error();
    const seen = new Set<string>(), groups = new Map<string, Candidate['evidence']>();
    for (const [index, page] of info.pages.entries()) {
      const meta = frozen.snapshots[index], result = page.result;
      if (!page || page.id !== meta.id || page.start_row !== meta.start_row || page.result_sha256 !== meta.result_sha256
        || !dated(page.collected_at) || Date.parse(page.collected_at) !== Date.parse(meta.collected_at) || !object(result)
        || result['method'] !== 'gsc-query-page-parse-v1' || result['property'] !== source.property || result.day !== frozen.day
        || result['start_row'] !== page.start_row || !same(result['dimensions'], ['query', 'page']) || result['search_type'] !== 'web'
        || result.timezone !== 'America/Los_Angeles' || result['requested_aggregation'] !== 'auto'
        || ![null, 'byPage'].includes(result['response_aggregation'] as string | null)
        || result['source_coverage'] !== 'bounded_query_page_top_rows_only' || result['provider_completeness'] !== 'not_established'
        || result['hidden_queries'] !== 'unknown' || !Array.isArray(result.observations) || result.observations.length > 100
        || !integer(result['rows_returned']) || Number(result['rows_returned']) > 100 || !integer(result['omitted_pages'])
        || Number(result['rows_returned']) !== result.observations.length + Number(result['omitted_pages'])
        || Number(result['rows_returned']) > 0 && result['response_aggregation'] !== 'byPage'
        || result['truncated'] !== (result['rows_returned'] === 100 && page.start_row === 100)
        || result['next_start_row'] !== (result['rows_returned'] === 100 && page.start_row === 0 ? 100 : null)
        || index === 1 && info.pages[0].result['next_start_row'] !== 100 || await sha256(result) !== page.result_sha256) throw new Error();
      for (const [rowIndex, row] of result.observations.entries()) {
        const key = JSON.stringify([row.query, row.page]);
        if (typeof row.query !== 'string' || !row.query.trim() || row.query.length > 1000 || /[\u0000-\u001f]/.test(row.query)
          || !ownPage(row.page, source.property) || !integer(row.clicks) || !integer(row.impressions) || row.clicks > row.impressions
          || typeof row.ctr !== 'string' || !Number.isFinite(Number(row.ctr)) || Number(row.ctr) < 0 || Number(row.ctr) > 1
          || typeof row.position !== 'string' || !Number.isFinite(Number(row.position)) || Number(row.position) < 0 || seen.has(key)) throw new Error();
        seen.add(key);
        if (row.impressions > 0) { const refs = groups.get(row.query) || []; refs.push({ snapshot_id: page.id, result_sha256: page.result_sha256, row_index: rowIndex }); groups.set(row.query, refs); }
      }
    }
    const candidates = Array.from(groups, ([query, refs]) => ({ query, evidence: refs, classification: 'positive_same_query_distinct_page_candidate' })).filter((row) => row.evidence.length > 1);
    if (!same(info.candidates, candidates.slice(0, 20)) || info.candidates_truncated !== (candidates.length > 20)
      || info.candidate_state !== (candidates.length ? 'positive_overlap_candidates' : 'no_positive_overlap_in_bounded_rows_not_absence')) throw new Error();
    return structuredClone(info);
  }
  async inspect() {
    const source = this.chosen(), job = this.jobs().find((row) => row.id === this.jobId());
    if (!source || !job || this.busy() || this.pending() || !job.source_current) return;
    const frozen = structuredClone({ source, job }), generation = this.generation; this.busy.set(true); this.evidence.set(null); this.error.set('');
    try {
      await this.preflight(frozen.source); if (generation !== this.generation) return;
      const before = this.readHistory(await this.api.searchConsoleQueryPages(this.organizationId, this.projectId, frozen.source.id), frozen.source);
      if (generation !== this.generation) return;
      if (!before.some((row) => same(row, frozen.job))) throw new Error();
      const result = await this.api.searchConsoleQueryPages(this.organizationId, this.projectId, frozen.source.id, undefined, frozen.job.id);
      if (generation !== this.generation) return;
      const info = await this.validateEvidence(result, frozen.source, frozen.job); if (generation !== this.generation) return;
      const after = this.readHistory(await this.api.searchConsoleQueryPages(this.organizationId, this.projectId, frozen.source.id), frozen.source);
      if (generation !== this.generation) return;
      if (!after.some((row) => same(row, frozen.job))) throw new Error();
      await this.preflight(frozen.source); if (generation === this.generation) this.evidence.set(info);
    } catch { if (generation === this.generation) { this.evidence.set(null); this.jobs.set([]); this.error.set('Exact current source, saved metadata, original dates or paired digest changed. No usable evidence; refresh.'); } }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  async start(event: Event) {
    event.preventDefault(); const source = this.chosen(); if (!source || this.busy() || this.pending()) return;
    const selectedDay = new FormData(event.target as HTMLFormElement).get('day'); if (!day(selectedDay)) { this.error.set('Choose a finalized Pacific reporting day.'); return; }
    await this.send({ source: structuredClone(source), data: { day: selectedDay, grant_id: source.query_page_grant_id,
      grant_revision: source.query_page_grant_revision, idempotency_key: crypto.randomUUID() } });
  }
  private async send(command: Pending) {
    const frozen = structuredClone(command), generation = this.generation; this.busy.set(true); this.evidence.set(null); this.error.set(''); this.notFound.set(false);
    let attempted = false;
    try {
      await this.preflight(frozen.source); if (generation !== this.generation) return;
      attempted = true;
      const response = await this.api.searchConsoleQueryPages(this.organizationId, this.projectId, frozen.source.id, frozen.data);
      if (generation !== this.generation) return;
      if (response.status === 202 && positive(response.body['job_id']) && response.body['project_id'] === this.projectId
        && response.body['connection_id'] === frozen.source.id && response.body['report'] === 'query_page' && response.body['max_requests'] === 3) {
        this.pending.set(null); this.jobs.set([]); this.message.set('Paired request saved. Explicitly refresh saved jobs for progress; no automatic collection or inspection.');
      } else if ([400, 401, 403, 404, 409, 429].includes(response.status)) { this.pending.set(null); this.error.set('Request denied, stale source, invalid finalized day or allowance reached. Refresh source state.'); }
      else throw new Error();
    } catch { if (generation === this.generation) { if (attempted) this.pending.set(frozen); this.error.set(attempted ? 'Request acknowledgment uncertain. Look up the exact request before deliberate retry.' : 'Source or role changed before dispatch; no request sent.'); } }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  async reconcile() {
    const command = this.pending(); if (!command || this.busy()) return;
    const frozen = structuredClone(command), generation = this.generation; this.busy.set(true); this.evidence.set(null); this.error.set('');
    try {
      await this.preflight(frozen.source); if (generation !== this.generation) return;
      const response = await this.api.searchConsoleQueryPages(this.organizationId, this.projectId, frozen.source.id, undefined, undefined, String(frozen.data['idempotency_key']));
      if (generation !== this.generation) return;
      if (response.status !== 200 || response.body['project_id'] !== this.projectId || response.body['organization_id'] !== this.organizationId
        || response.body['connection_id'] !== frozen.source.id || response.body['request_key'] !== frozen.data['idempotency_key']) throw new Error();
      const saved = response.body['job'];
      if (saved !== null && (!isJob(saved) || saved.day !== frozen.data['day'] || saved.property !== frozen.source.property
        || saved.grant_revision !== frozen.data['grant_revision'] || !saved.source_current)) throw new Error();
      await this.preflight(frozen.source); if (generation !== this.generation) return;
      if (saved === null) { this.notFound.set(true); this.message.set('No saved request found at this check; only deliberate same-key retry is available.'); }
      else { this.pending.set(null); this.notFound.set(false); this.jobs.set([structuredClone(saved as Job)]); this.message.set('Exact saved request reconciled without replay.'); }
    } catch { if (generation === this.generation) { this.notFound.set(false); this.error.set('Exact acknowledgment or current source unavailable. No replay.'); } }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  async retry() { const command = this.pending(); if (command && this.notFound() && !this.busy()) await this.send(command); }
  async cancel(id: number) {
    const source = this.chosen(); if (!source || this.busy() || this.pending()) return;
    const frozen = structuredClone(source), generation = this.generation; this.busy.set(true); this.evidence.set(null);
    try { await this.preflight(frozen); if (generation !== this.generation) return;
      const response = await this.api.cancelSearchConsoleSync(this.organizationId, this.projectId, frozen.id, id);
      if (generation === this.generation) { this.jobs.set([]); this.message.set(response.status === 202 ? 'Cancellation requested; explicitly refresh saved status.' : 'Cancellation acknowledgment unavailable; refresh saved status before another action.'); }
    } catch { if (generation === this.generation) this.error.set('Cancellation outcome unavailable. Inspect saved status; no automatic retry.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
}
