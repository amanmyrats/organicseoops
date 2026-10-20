import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, ElementRef, HostListener, OnInit, ViewChild, computed, effect, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi } from '../account/account-api';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';

type Group = { agent: string; identity: string; known_url: string | null; request_count: number; status_counts: Record<string, number>; first_seen: string; last_seen: string };
type Summary = { origin: string; rows_seen: number; window: { start: string; end: string }; groups: Group[] };
type Import = { id: number; project_id: number; status: string; created_at: string; updated_at: string; source_current: boolean; error_category: string;
  cancel_requested: boolean; inventory_id: number | null; crawl_run_id: number | null;
  evidence: { summary: Summary; request_candidates: { unmatched_inventory_requests: number; redirect_or_error_requests: number };
    inventory_families: { agent: string; representative_inventory_url: string; known_urls: number; request_count: number; redirect_or_error_requests: number }[] } | null };
type Inventory = { id: number; crawl_run_id: number; observed_at: string; origins: { origin: string; url_count: number }[] };
type Page = { project_id: number; method: string; can_manage: boolean; origins: string[]; inventories: Inventory[]; jobs: Import[]; next_before: number | null };

const botLogsTurkish: Record<string, string> = {
  "Private authorized bot-log observations": "Özel yetkilendirilmiş bot günlüğü gözlemleri",
  "Project evidence": "Proje kanıtları",
  "Ownership, sources and indexation": "Sahiplik, kaynaklar ve dizine ekleme",
  "Discoverability proposals": "Keşfedilebilirlik önerileri",
  "Partial customer-supplied request counts, not analytics visits, users or verified bot identities. Imports are separate observations: overlapping files must not be added as total traffic. Missing requests never prove that a URL was never visited. Bot requests and HTTP success never prove indexing, citations or training membership.": "Müşterinin sağladığı kısmi istek sayıları; analitik ziyaretler, kullanıcılar veya doğrulanmış bot kimlikleri değil. İçe aktarmalar ayrı gözlemlerdir: örtüşen dosyalar toplam trafik olarak eklenmemelidir. Eksik istekler, URL'nin hiç ziyaret edilmediğini kanıtlamaz. Bot istekleri ve HTTP başarısı; dizine ekleme, atıf veya eğitim verisine dahil olmayı kanıtlamaz.",
  "OAI-SearchBot: search/retrieval. GPTBot: potential training. ChatGPT-User: user-triggered actions; robots may not apply and it is not search inclusion evidence.": "OAI-SearchBot: arama/erişim. GPTBot: olası eğitim. ChatGPT-User: kullanıcının tetiklediği eylemler; robots geçerli olmayabilir ve aramaya dahil olma kanıtı değildir.",
  "Official guidance, reviewed2026-10-01": "Resmî rehber, incelenme tarihi2026-10-01",
  "Only derived counts, HTTP statuses, first/last UTC times and existing inventory paths are stored. Raw logs, IPs, cookies, query/fragment values, referrers, full user agents and unmatched paths are discarded before job staging. Derived evidence follows customer retention/export/deletion: 90-day retained access after lapse, active deletion within30days after that or closure, then up to35days of backup rotation. Closure activation and legal release review remain unfinished.": "Yalnızca türetilmiş sayılar, HTTP durumları, ilk/son UTC zamanları ve mevcut envanter yolları saklanır. Ham günlükler, IP'ler, çerezler, sorgu/parça değerleri, yönlendirenler, tam kullanıcı aracı dizeleri ve eşleşmeyen yollar iş hazırlığından önce atılır. Türetilmiş kanıt müşteri saklama/dışa aktarma/silmeye tabidir: erişim süresi bittikten sonra 90 günlük saklanan erişim, bundan veya kapatmadan sonraki30gün içinde aktif silme, ardından en fazla35gün yedek rotasyonu. Kapatma etkinleştirmesi ve yasal yayın incelemesi tamamlanmadı.",
  "Loading current private logfile sources.": "Güncel özel günlük dosyası kaynakları yükleniyor.",
  "Submitting one minimized import request. No automatic resubmission.": "Tek en aza indirilmiş içe aktarma isteği gönderiliyor. Otomatik yeniden gönderim yoktur.",
  "Active project": "Aktif proje",
  "· organization": "· kuruluş",
  "· project": "· proje",
  "Read-only role: owner/admin current ownership and logfile authorization are required for uploads.": "Salt okunur rol: yüklemeler için sahip/yönetici güncel sahipliği ve günlük dosyası yetkilendirmesi gerekir.",
  "No currently verified origin and authorized existing indexation inventory. Use project onboarding to verify ownership and build no-fetch evidence from a completed crawl.": "Şu anda doğrulanmış köken ve yetkilendirilmiş mevcut dizine ekleme envanteri yok. Sahipliği doğrulamak ve tamamlanan taramadan getirme yapmadan kanıt oluşturmak için proje başlangıcını kullanın.",
  "Exact currently verified origin": "Tam güncel doğrulanmış köken",
  "Existing server-owned indexation inventory": "Mevcut sunucuya ait dizine ekleme envanteri",
  "Coverage start (aware ISO8601, e.g. UTC Z)": "Kapsam başlangıcı (saat dilimli ISO8601, örn. UTC Z)",
  "Exclusive coverage end (aware ISO8601; no future time)": "Hariç kapsam bitişi (saat dilimli ISO8601; gelecekte zaman yok)",
  "UTF-8 JSONL export (at most1MiB/1,000 rows;8KiB per row)": "UTF-8 JSONL dışa aktarma (en fazla1MiB/1.000 satır; satır başına8KiB)",
  "Each row requires timestamp, exact origin, relative target, integer HTTP status and user_agent. Other log formats are unsupported. Only up to40 clean inventory URLs may label retained paths; all unmatched paths collapse. Window at most7days; summaries at most100groups/24KiB.": "Her satır zaman damgası, tam köken, göreli hedef, tamsayı HTTP durumu ve user_agent gerektirir. Diğer günlük biçimleri desteklenmez. En fazla40 temiz envanter URL'si saklanan yolları etiketleyebilir; tüm eşleşmeyen yollar birleştirilir. Pencere en fazla7gün; özetler en fazla100grup/24KiB.",
  "I am authorized to use these logs for this exact origin and confirm partial coverage and the minimized-data policy.": "Bu günlükleri bu tam köken için kullanmaya yetkiliyim; kısmi kapsamı ve en aza indirilmiş veri politikasını onaylıyorum.",
  "Import once · maximum1 internal unit · no provider call": "Bir kez içe aktarın · en fazla1 dahili birim · sağlayıcı çağrısı yok",
  "Separate import history (up to20 per page)": "Ayrı içe aktarma geçmişi (sayfa başına en fazla20)",
  "Import": "İçe aktarma",
  "Created": "Oluşturuldu",
  "· updated": "· güncellendi",
  "Import unavailable:": "İçe aktarma kullanılamıyor:",
  ". Check role, origin and allowance before a fresh authorized request.": ". Yeni yetkilendirilmiş istekten önce rolü, kökeni ve kullanım hakkını kontrol edin.",
  "Historical/stale or revoked source authority; private path evidence withheld.": "Tarihsel/eski veya iptal edilmiş kaynak yetkisi; özel yol kanıtı gösterilmez.",
  "Cancellation requested.": "İptal istendi.",
  "Waiting for bounded offline processing. Status is refreshed while this page is visible.": "Sınırlı çevrimdışı işleme bekleniyor. Bu sayfa görünürken durum yenilenir.",
  "Cancel import": "İçe aktarmayı iptal edin",
  "Exact origin": "Tam köken",
  "· partial window [": "· kısmi pencere [",
  ") UTC ·": ") UTC ·",
  "requests.": "istek.",
  "requests unmatched to the selected inventory (paths not retained);": "istek seçilen envanterle eşleşmiyor (yollar saklanmaz);",
  "redirect/error requests. Distribution candidates, not proven crawl waste.": "yönlendirme/hata isteği. Dağılım adayları; kanıtlanmış tarama israfı değil.",
  "Known-inventory families group the same first path segment, per agent. Unknown paths never contribute a retained family label.": "Bilinen envanter aileleri, aracı başına aynı ilk yol bölümünü gruplar. Bilinmeyen yollar saklanan aile etiketine katkıda bulunmaz.",
  "· family represented by existing URL": "· aileyi temsil eden mevcut URL",
  "known URLs ·": "bilinen URL ·",
  "partial requests,": "kısmi istek,",
  "redirect/error candidates; not proven waste.": "yönlendirme/hata adayı; kanıtlanmış israf değil.",
  "· user-agent-only unverified ·": "· yalnızca kullanıcı aracı, doğrulanmamış ·",
  "requests (": "istek (",
  "per declared hour; partial sample). First": "beyan edilen saat başına; kısmi örnek). İlk",
  "· last": "· son",
  "UTC. HTTP counts": "UTC. HTTP sayıları",
  "Inspect separate crawl/indexation evidence for this exact source": "Bu tam kaynak için ayrı tarama/dizine ekleme kanıtını inceleyin",
  "No imports on this history page. Bot activity is unavailable, not zero.": "Bu geçmiş sayfasında içe aktarma yok. Bot etkinliği kullanılamıyor; sıfır değildir.",
  "Older import page": "Daha eski içe aktarma sayfası",
  "Newest import page": "En yeni içe aktarma sayfası",
  "Separate current crawl and engine evidence (never inferred from logs)": "Ayrı güncel tarama ve motor kanıtı (günlüklerden hiçbir zaman çıkarılmaz)",
  "Refresh current authority and history": "Güncel yetkiyi ve geçmişi yenileyin",
  "unmatched path not retained": "eşleşmeyen yol saklanmadı",
  "Private evidence cleared while hidden. Refresh to recheck authority.": "Özel kanıt gizliyken temizlendi. Yetkiyi yeniden kontrol etmek için yenileyin.",
  "Log history unavailable or project access denied/revoked. Refresh current scope.": "Günlük geçmişi kullanılamıyor veya proje erişimi reddedildi/iptal edildi. Güncel kapsamı yenileyin.",
  "Status unavailable. Refresh history before resubmitting; the import may already exist.": "Durum kullanılamıyor. Yeniden göndermeden önce geçmişi yenileyin; içe aktarma zaten mevcut olabilir.",
  "Choose a JSONL file up to1MiB, matching current origin/inventory, and authorize its use.": "En fazla1MiB JSONL dosyası, eşleşen güncel köken/envanter seçin ve kullanımını yetkilendirin.",
  "Upload denied, invalid, allowance reached or response unknown. Refresh history before a new request; never automatically resend raw logs.": "Yükleme reddedildi, geçersiz, kullanım hakkına ulaşıldı veya yanıt bilinmiyor. Yeni istekten önce geçmişi yenileyin; ham günlükleri hiçbir zaman otomatik yeniden göndermeyin.",
  "Cancellation unavailable; refresh current status.": "İptal kullanılamıyor; güncel durumu yenileyin.",
  "Current indexation handoff unavailable; no state can be inferred from logs.": "Güncel dizine ekleme devri kullanılamıyor; günlüklerden durum çıkarılamaz.",
  "Unreviewed Turkish bot-log interface draft in local development. Source names and paths retain their original language; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe bot günlüğü arayüzü taslağı. Kaynak adları ve yollar özgün dillerini korur; iki dilli onay bekleniyor."
};

@Component({
  selector: 'app-bot-logs', imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="bot-log-title">
      <h1 id="bot-log-title">{{ t("Private authorized bot-log observations") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish bot-log interface draft in local development. Source names and paths retain their original language; bilingual approval is pending.") }}</p> }
      <p><a [routerLink]="['/app/dashboard', organizationId, projectId]">{{ t("Project evidence") }}</a> ·
        <a [routerLink]="['/app/onboarding', organizationId, projectId]">{{ t("Ownership, sources and indexation") }}</a> ·
        <a [routerLink]="['/app/visibility-discoverability', organizationId, projectId]">{{ t("Discoverability proposals") }}</a></p>
      <p>{{ t("Partial customer-supplied request counts, not analytics visits, users or verified bot identities. Imports are separate observations: overlapping files must not be added as total traffic. Missing requests never prove that a URL was never visited. Bot requests and HTTP success never prove indexing, citations or training membership.") }}</p>
      <p>{{ t("OAI-SearchBot: search/retrieval. GPTBot: potential training. ChatGPT-User: user-triggered actions; robots may not apply and it is not search inclusion evidence.") }}
        <a href="https://developers.openai.com/api/docs/bots" target="_blank" rel="noopener noreferrer">{{ t("Official guidance, reviewed2026-10-01") }}</a>.</p>
      <p>{{ t("Only derived counts, HTTP statuses, first/last UTC times and existing inventory paths are stored. Raw logs, IPs, cookies, query/fragment values, referrers, full user agents and unmatched paths are discarded before job staging. Derived evidence follows customer retention/export/deletion: 90-day retained access after lapse, active deletion within30days after that or closure, then up to35days of backup rotation. Closure activation and legal release review remain unfinished.") }}</p>
      @if (loading()) { <p role="status">{{ t("Loading current private logfile sources.") }}</p> }
      @if (busy()) { <p role="status">{{ t("Submitting one minimized import request. No automatic resubmission.") }}</p> }
      @if (error()) { <p role="alert" [attr.lang]="t(error()) === error() ? 'en' : uiLanguage()">{{ t(error()) }}</p> }
      @if (message()) { <p role="status" [attr.lang]="textLanguage(message())">{{ t(message()) }}</p> }
      @if (page(); as data) {
        <p>{{ t("Active project") }} <span lang="">{{ name() }}</span> {{ t("· organization") }} <span lang="en">{{ organizationId }}</span> {{ t("· project") }} <span lang="en">{{ projectId }}</span>.</p>
        @if (!data.can_manage) { <p>{{ t("Read-only role: owner/admin current ownership and logfile authorization are required for uploads.") }}</p> }
        @else if (!data.inventories.length || !data.origins.length) { <p>{{ t("No currently verified origin and authorized existing indexation inventory. Use project onboarding to verify ownership and build no-fetch evidence from a completed crawl.") }}</p> }
        @else {
          <form #uploadForm (submit)="upload($event)">
            <label for="log-origin">{{ t("Exact currently verified origin") }}</label><select id="log-origin" name="origin" required>
              @for (origin of data.origins; track origin) { <option lang="" [value]="origin">{{ origin }}</option> }
            </select>
            <label for="log-inventory">{{ t("Existing server-owned indexation inventory") }}</label><select id="log-inventory" name="inventory" required>
              @for (item of data.inventories; track item.id) { <option lang="en" [value]="item.id">Inventory {{ item.id }} · crawl {{ item.crawl_run_id }} · {{ item.observed_at }}</option> }
            </select>
            <label for="log-start">{{ t("Coverage start (aware ISO8601, e.g. UTC Z)") }}</label><input lang="en" id="log-start" name="start" type="text" required maxlength="40" placeholder="2026-09-30T00:00:00Z">
            <label for="log-end">{{ t("Exclusive coverage end (aware ISO8601; no future time)") }}</label><input lang="en" id="log-end" name="end" type="text" required maxlength="40" placeholder="2026-10-01T00:00:00Z">
            <label for="log-file">{{ t("UTF-8 JSONL export (at most1MiB/1,000 rows;8KiB per row)") }}</label><input lang="" id="log-file" name="file" type="file" accept=".jsonl,.ndjson,application/x-ndjson" required>
            <p>{{ t("Each row requires timestamp, exact origin, relative target, integer HTTP status and user_agent. Other log formats are unsupported. Only up to40 clean inventory URLs may label retained paths; all unmatched paths collapse. Window at most7days; summaries at most100groups/24KiB.") }}</p>
            <label><input name="authorize" type="checkbox" required> {{ t("I am authorized to use these logs for this exact origin and confirm partial coverage and the minimized-data policy.") }}</label>
            <button type="submit" [disabled]="busy() || loading()">{{ t("Import once · maximum1 internal unit · no provider call") }}</button>
          </form>
        }
        <h2>{{ t("Separate import history (up to20 per page)") }}</h2>
        <ul>@for (row of data.jobs; track row.id) {
          <li><h3>{{ t("Import") }} <span lang="en">{{ row.id }}</span> · <span lang="en">{{ row.status }}</span></h3><p>{{ t("Created") }} <span lang="en">{{ row.created_at }}</span> {{ t("· updated") }} <span lang="en">{{ row.updated_at }}</span>.</p>
            @if (row.error_category) { <p>{{ t("Import unavailable:") }} <span lang="en">{{ row.error_category }}</span>{{ t(". Check role, origin and allowance before a fresh authorized request.") }}</p> }
            @if (!row.source_current) { <p>{{ t("Historical/stale or revoked source authority; private path evidence withheld.") }}</p> }
            @if (row.cancel_requested) { <p>{{ t("Cancellation requested.") }}</p> }
            @if (row.status === 'queued' || row.status === 'running') {
              <p role="status">{{ t("Waiting for bounded offline processing. Status is refreshed while this page is visible.") }}</p>
              @if (data.can_manage) { <button type="button" [disabled]="busy()" (click)="cancel(row.id)">{{ t("Cancel import") }} <span lang="en">{{ row.id }}</span></button> }
            }
            @if (row.evidence; as evidence) {
              <p>{{ t("Exact origin") }} <span lang="">{{ evidence.summary.origin }}</span> {{ t("· partial window [") }}<span lang="en">{{ evidence.summary.window.start }}</span>, <span lang="en">{{ evidence.summary.window.end }}</span>{{ t(") UTC ·") }} <span lang="en">{{ evidence.summary.rows_seen }}</span> {{ t("requests.") }}</p>
              <p><span lang="en">{{ evidence.request_candidates.unmatched_inventory_requests }}</span> {{ t("requests unmatched to the selected inventory (paths not retained);") }}
                <span lang="en">{{ evidence.request_candidates.redirect_or_error_requests }}</span> {{ t("redirect/error requests. Distribution candidates, not proven crawl waste.") }}</p>
              <p>{{ t("Known-inventory families group the same first path segment, per agent. Unknown paths never contribute a retained family label.") }}</p>
              <ul>@for (family of evidence.inventory_families; track $index) {
                <li><span lang="en">{{ family.agent }}</span> {{ t("· family represented by existing URL") }} <span lang="">{{ family.representative_inventory_url }}</span> · <span lang="en">{{ family.known_urls }}</span> {{ t("known URLs ·") }}
                  <span lang="en">{{ family.request_count }}</span> {{ t("partial requests,") }} <span lang="en">{{ family.redirect_or_error_requests }}</span> {{ t("redirect/error candidates; not proven waste.") }}</li>
              }</ul>
              <ul>@for (group of evidence.summary.groups; track $index) {
                <li><span lang="en">{{ group.agent }}</span> {{ t("· user-agent-only unverified ·") }} <span [attr.lang]="group.known_url ? '' : uiLanguage()">{{ group.known_url || t("unmatched path not retained") }}</span> · <span lang="en">{{ group.request_count }}</span> {{ t("requests (") }}<span lang="en">{{ frequency(group, evidence.summary) }}</span> {{ t("per declared hour; partial sample). First") }} <span lang="en">{{ group.first_seen }}</span> {{ t("· last") }} <span lang="en">{{ group.last_seen }}</span> {{ t("UTC. HTTP counts") }} <span lang="en">{{ statuses(group) }}</span>.</li>
              }</ul>
              <button type="button" [disabled]="busy()" (click)="indexation(row)">{{ t("Inspect separate crawl/indexation evidence for this exact source") }}</button>
            }
          </li>
        } @empty { <li>{{ t("No imports on this history page. Bot activity is unavailable, not zero.") }}</li> }</ul>
        @if (data.next_before !== null) { <button type="button" [disabled]="busy() || loading()" (click)="load(data.next_before)">{{ t("Older import page") }}</button> }
        @if (before !== null) { <button type="button" [disabled]="busy() || loading()" (click)="load()">{{ t("Newest import page") }}</button> }
      }
      @if (indexationReport()) { <details open><summary>{{ t("Separate current crawl and engine evidence (never inferred from logs)") }}</summary><pre><span lang="en">{{ indexationReport() }}</span></pre></details> }
      <button type="button" [disabled]="busy() || loading()" (click)="load(before)">{{ t("Refresh current authority and history") }}</button>
    </section>`,
  styles: `section,li { overflow-wrap:anywhere } form { display:grid; gap:.65rem; max-width:46rem } li { margin-block:1rem } pre { white-space:pre-wrap } button { margin:.5rem .5rem .5rem 0 }`,
})
export class BotLogs implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  private readonly messageDraft = signal<{ message: string; translation: string } | null>(null);
  textLanguage(text: string) {
    return Object.hasOwn(botLogsTurkish, text) || this.messageDraft()?.message === text ? this.uiLanguage() : 'en';
  }
  t(text: string) {
    if (this.textLanguage(text) !== 'tr') return text;
    const draft = this.messageDraft();
    return draft?.message === text ? draft.translation : botLogsTurkish[text];
  }
  private setDraftMessage(message: string, translation: string) {
    this.messageDraft.set({ message, translation });
    this.message.set(message);
  }
  @ViewChild('uploadForm') uploadForm?: ElementRef<HTMLFormElement>;
  organizationId = 0; projectId = 0; before: number | null = null; private generation = 0; private timer: ReturnType<typeof setTimeout> | null = null;
  readonly page = signal<Page | null>(null); readonly name = signal(''); readonly error = signal(''); readonly message = signal('');
  readonly loading = signal(true); readonly busy = signal(false); readonly indexationReport = signal('');
  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi, private readonly destroy: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t('Private authorized bot-log observations')} — OrganicSEOOps`));
  }
  ngOnInit() {
    void this.loadProductLanguage();
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroy)).subscribe((params) => {
      this.organizationId = Number(params.get('organizationId')); this.projectId = Number(params.get('projectId')); this.clear(); void this.load();
    }); this.destroy.onDestroy(() => this.clear());
  }
  private async loadProductLanguage() {
    try {
      const result = await this.api.productLanguage();
      if (!this.destroy.destroyed && result.status === 200 && isProductLanguageResult(result.body)) {
        this.productLanguage.set(result.body['language']);
      }
    } catch { /* Keep English when the private preference is unavailable. */ }
  }
  private clear() {
    ++this.generation; if (this.timer !== null) clearTimeout(this.timer); this.timer = null;
    this.page.set(null); this.name.set(''); this.indexationReport.set(''); this.busy.set(false); this.message.set(''); this.messageDraft.set(null);
    this.uploadForm?.nativeElement.reset();
  }
  @HostListener('document:visibilitychange') hidden() { if (document.hidden) { this.clear(); this.loading.set(false); this.error.set('Private evidence cleared while hidden. Refresh to recheck authority.'); } }
  statuses(row: Group) { return Object.entries(row.status_counts).map(([code, count]) => `${code}: ${count}`).join(', '); }
  frequency(row: Group, summary: Summary) { return (row.request_count / ((Date.parse(summary.window.end) - Date.parse(summary.window.start)) / 3600000)).toFixed(2); }
  private acceptJob(row: Import) { return row.project_id === this.projectId && Number.isSafeInteger(row.id) && row.id > 0
    && (!row.evidence || row.source_current && row.status === 'succeeded' && Array.isArray(row.evidence.summary?.groups) && row.evidence.summary.groups.length <= 100); }
  async load(before: number | null = null) {
    this.clear(); const generation = this.generation; this.before = before; this.loading.set(true); this.error.set('');
    try {
      const context = await this.api.projectOnboarding(this.organizationId, this.projectId);
      if (generation !== this.generation) return;
      const project = context.body['project'] as Record<string, unknown> | undefined;
      if (context.status !== 200 || project?.['id'] !== this.projectId || project['organization_id'] !== this.organizationId) throw new Error();
      const response = await this.api.botLogs(this.organizationId, this.projectId, 0, before); const page = response.body as unknown as Page;
      if (generation !== this.generation) return;
      if (response.status !== 200 || page.project_id !== this.projectId || page.method !== 'bot-log-jsonl-v1'
        || !Array.isArray(page.jobs) || page.jobs.length > 20 || page.jobs.some((row) => !this.acceptJob(row))
        || !Array.isArray(page.inventories) || !Array.isArray(page.origins) || page.inventories.length > 20 || page.origins.length > 20) throw new Error();
      this.page.set(page); this.name.set(String(project['name'])); this.poll(generation);
    } catch { if (generation === this.generation) this.error.set('Log history unavailable or project access denied/revoked. Refresh current scope.'); }
    finally { if (generation === this.generation) this.loading.set(false); }
  }
  private poll(generation: number) {
    const active = this.page()?.jobs.find((row) => row.status === 'queued' || row.status === 'running');
    if (!active || document.hidden) return;
    this.timer = setTimeout(async () => {
      try {
        const response = await this.api.botLogs(this.organizationId, this.projectId, active.id);
        if (generation !== this.generation) return;
        const row = response.body['job'] as Import;
        if (response.status !== 200 || response.body['project_id'] !== this.projectId || row?.id !== active.id || !this.acceptJob(row)) throw new Error();
        this.page.update((page) => page ? { ...page, jobs: page.jobs.map((old) => old.id === row.id ? row : old) } : null); this.poll(generation);
      } catch { if (generation === this.generation) { this.page.set(null); this.indexationReport.set(''); this.error.set('Status unavailable. Refresh history before resubmitting; the import may already exist.'); } }
    }, 3000);
  }
  async upload(event: Event) {
    event.preventDefault(); const form = event.target as HTMLFormElement;
    if (this.busy() || !this.page()?.can_manage || !form.reportValidity()) return;
    const fields = new FormData(form); const file = fields.get('file') as File; const inventory = Number(fields.get('inventory')); const origin = String(fields.get('origin'));
    if (!file || !file.size || file.size > 1048576 || !fields.has('authorize') || !this.page()?.inventories.some((item) => item.id === inventory && item.origins.some((value) => value.origin === origin))) {
      this.error.set('Choose a JSONL file up to1MiB, matching current origin/inventory, and authorize its use.'); return;
    }
    const generation = this.generation; this.busy.set(true); this.error.set(''); this.indexationReport.set('');
    try {
      const response = await this.api.uploadBotLogs(this.organizationId, this.projectId, file, {
        'X-Log-Origin': origin, 'X-Log-Inventory': String(inventory), 'X-Log-Start': String(fields.get('start')),
        'X-Log-End': String(fields.get('end')), 'X-Log-Authorization': 'true', 'X-Log-Request': crypto.randomUUID() });
      if (generation !== this.generation) return;
      const job = response.body['job'] as Import;
      if (response.status !== 202 || response.body['project_id'] !== this.projectId || !job || !this.acceptJob(job)) throw new Error();
      form.reset(); await this.load(); if (this.generation === generation + 1) this.setDraftMessage(`Import ${job.id} staged as minimized evidence; raw logfile discarded.`,
        `İçe aktarma ${job.id}, asgariye indirilmiş kanıt olarak hazırlandı; ham günlük dosyası atıldı.`);
    } catch { if (generation === this.generation) { this.page.set(null); this.error.set('Upload denied, invalid, allowance reached or response unknown. Refresh history before a new request; never automatically resend raw logs.'); } }
    finally { form.reset(); if (generation === this.generation) this.busy.set(false); }
  }
  async cancel(id: number) {
    const generation = this.generation; this.busy.set(true); this.error.set('');
    try { const response = await this.api.botLogs(this.organizationId, this.projectId, id, null, true);
      if (generation !== this.generation) return; if (response.status !== 200 || response.body['project_id'] !== this.projectId) throw new Error();
      await this.load(this.before);
    } catch { if (generation === this.generation) { this.page.set(null); this.error.set('Cancellation unavailable; refresh current status.'); } }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  async indexation(row: Import) {
    if (!row.source_current || !row.crawl_run_id || this.busy()) return;
    const generation = this.generation; this.busy.set(true); this.error.set(''); this.indexationReport.set('');
    try { const response = await this.api.indexationEvidence(this.organizationId, this.projectId, row.crawl_run_id);
      if (generation !== this.generation) return;
      const report = response.body['report'] as Record<string, unknown> | null;
      if (response.status !== 200 || response.body['project_id'] !== this.projectId || report?.['crawl_run_id'] !== row.crawl_run_id) throw new Error();
      this.indexationReport.set(JSON.stringify(report, null, 2));
    } catch { if (generation === this.generation) this.error.set('Current indexation handoff unavailable; no state can be inferred from logs.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
}
