import { Title } from '@angular/platform-browser';
import { DOCUMENT } from '@angular/common';
import { Component, computed, effect, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';
import { AccountApi } from '../account/account-api';

type Video = { kind: string; id: { kind: string; videoId: string }; snippet: {
  publishedAt: string; channelId: string; title: string; channelTitle: string } };
type Page = { kind: string; regionCode: string; nextPageToken?: string; items: Video[] };

function readPage(value: unknown): Page | null {
  if (!value || typeof value !== 'object') return null;
  const page = value as Page;
  return page.kind === 'youtube#searchListResponse' && typeof page.regionCode === 'string'
    && page.regionCode.length === 2 && /^[A-Z]{2}$/.test(page.regionCode)
    && (!('nextPageToken' in page) || typeof page.nextPageToken === 'string'
      && page.nextPageToken.length >= 1 && page.nextPageToken.length <= 512 && !/[^!-~]/.test(page.nextPageToken))
    && Array.isArray(page.items) && page.items.length <= 20 && page.items.every((row) => row?.kind === 'youtube#searchResult'
      && row.id?.kind === 'youtube#video' && typeof row.id.videoId === 'string'
      && row.id.videoId.length === 11 && /^[A-Za-z0-9_-]{11}$/.test(row.id.videoId)
      && row.snippet && ['publishedAt', 'channelId', 'title', 'channelTitle'].every((key) =>
        typeof row.snippet[key as keyof Video['snippet']] === 'string')) ? page : null;
}

const projectYouTubeTurkish: Record<string, string> = {
  "Separate YouTube public-video search": "Ayrı YouTube herkese açık video araması",
  "YouTube public-video search": "YouTube herkese açık video araması",
  "Unreviewed Turkish project YouTube interface draft in local development. Provider values and request error codes retain their source form; bilingual Terms/privacy approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe proje YouTube arayüzü taslağı. Sağlayıcı değerleri ve istek hata kodları özgün biçimlerini korur; iki dilli Koşullar/gizlilik onayı bekleniyor.",
  "Return to topic review": "Konu incelemesine dönün",
  "Configure project seeds and languages": "Proje başlangıç ifadelerini ve dillerini yapılandırın",
  "Checking project source selection.": "Proje kaynak seçimi kontrol ediliyor.",
  "Active project:": "Etkin proje:",
  "(organization": "(kuruluş",
  "). Separate YouTube API metadata, in original provider order. No topic/demand/popularity/competition score or AI/research/content handoff. Live access, policy/legal and bilingual release review remain unverified.": "). Ayrı YouTube API meta verileri, özgün sağlayıcı sırasıyla gösterilir. Konu/talep/popülerlik/rekabet puanı veya yapay zekâ/araştırma/içerik aktarımı yoktur. Canlı erişim, politika/hukuk ve iki dilli yayın incelemesi doğrulanmamıştır.",
  "YouTube feature Terms and privacy — development draft": "YouTube özelliği Koşulları ve gizlilik — geliştirme taslağı",
  "This feature uses YouTube API Services. By using it you agree to be bound by the": "Bu özellik YouTube API Hizmetlerini kullanır. Kullanarak aşağıdaki koşullara bağlı olmayı kabul edersiniz:",
  "YouTube Terms of Service": "YouTube Hizmet Şartları",
  "and this feature's Terms/privacy disclosure (": "ve bu özelliğin Koşullar/gizlilik açıklaması (",
  "Google Privacy Policy": "Google Gizlilik Politikası",
  "We send the selected seed, publication window, language preference and optional viewability region to Google, using the platform's key and server network address. No private YouTube account/OAuth data is requested. Returned titles, video/channel identifiers and dates are shown only to you in this screen's memory, for at most fifteen minutes. We do not store them in database, artifacts, logs, exports or backups, share them with AI, or use them to derive metrics. No videos, thumbnails, embeds, adverts or media are loaded here.": "Seçilen başlangıç ifadesini, yayın aralığını, dil tercihini ve isteğe bağlı görüntülenebilirlik bölgesini platformun anahtarı ve sunucu ağ adresiyle Google'a göndeririz. Özel YouTube hesap/OAuth verisi istenmez. Dönen başlıklar, video/kanal kimlikleri ve tarihler yalnızca size, bu ekranın belleğinde en fazla on beş dakika gösterilir. Bunları veritabanı, dosya, günlük, dışa aktarma veya yedeklerde saklamaz, yapay zekâ ile paylaşmaz veya ölçüm türetmek için kullanmayız. Burada video, küçük resim, gömülü içerik, reklam veya medya yüklenmez.",
  "Only your selected inputs, versioned acceptance, actor/project, request status and internal-unit usage are retained in existing private operational records under the organization's retention policy. Private account session/CSRF cookies secure this request; this feature adds no browser storage or tracking cookies. Clear results below to discard this screen's data; leaving/hiding/reloading also clears it. This does not delete anything on YouTube. Following a YouTube link opens YouTube under Google's policies.": "Yalnızca seçtiğiniz girdiler, sürümlü kabul, işlemi yapan kullanıcı/proje, istek durumu ve dahili birim kullanımı kuruluşun saklama politikası kapsamında mevcut özel operasyon kayıtlarında tutulur. Özel hesap oturumu/CSRF çerezleri bu isteği korur; bu özellik tarayıcı depolaması veya izleme çerezi eklemez. Bu ekranın verilerini atmak için aşağıdan sonuçları temizleyin; ayrılmak/gizlemek/yeniden yüklemek de temizler. Bu işlem YouTube'da hiçbir şeyi silmez. Bir YouTube bağlantısını izlemek YouTube'u Google'ın politikaları kapsamında açar.",
  "Our first-page twenty-result, one/seven-day and configured-seed/language bounds are OrganicSEOOps limits, not YouTube limits. Region selects video viewability, not topic geography; relevance language is a preference, not a guaranteed result language. Empty/top-N results do not establish no demand or complete coverage.": "İlk sayfada yirmi sonuç, bir/yedi gün ve yapılandırılmış başlangıç ifadesi/dil sınırları YouTube sınırları değil OrganicSEOOps sınırlarıdır. Bölge konu coğrafyasını değil video görüntülenebilirliğini seçer; alaka dili bir tercihtir, sonuç dilinin garantisi değildir. Boş/ilk N sonuçlar talep olmadığını veya tam kapsamı kanıtlamaz.",
  "Open full YouTube": "YouTube'un tamamını açın",
  "Unavailable: a dedicated staff YouTube key is not configured. Other source discovery remains independent.": "Kullanılamıyor: özel personel YouTube anahtarı yapılandırılmamış. Diğer kaynak keşifleri bağımsız kalır.",
  "Your role is read-only; it cannot run a source search.": "Rolünüz salt okunurdur; kaynak araması yapamaz.",
  "Configure a supported plain seed and SEO language first.": "Önce desteklenen düz bir başlangıç ifadesi ve SEO dili yapılandırın.",
  "Current configured seed": "Güncel yapılandırılmış başlangıç ifadesi",
  "Choose a seed": "Başlangıç ifadesi seçin",
  "Relevance-language preference": "Alaka dili tercihi",
  "Choose a language": "Dil seçin",
  "Optional video-viewability country code (two uppercase letters)": "İsteğe bağlı video görüntülenebilirlik ülke kodu (iki büyük harf)",
  "Publication window": "Yayın aralığı",
  "Last one day": "Son bir gün",
  "Last seven days": "Son yedi gün",
  "I agree to the YouTube Terms and this feature's Terms/privacy disclosure above.": "YouTube Şartlarını ve yukarıdaki bu özelliğin Koşullar/gizlilik açıklamasını kabul ediyorum.",
  "One internal unit per accepted request, shared client quota, at most ten seconds, no automatic retry/paging. Failed or discarded requests may consume that unit. Existing commercial allowances and expiry apply.": "Kabul edilen istek başına bir dahili birim, paylaşılan istemci kotası ve en fazla on saniye; otomatik yeniden deneme/sayfalama yoktur. Başarısız veya atılan istekler bu birimi tüketebilir. Mevcut ticari haklar ve sona erme koşulları geçerlidir.",
  "Search YouTube once": "YouTube'da bir kez arayın",
  "Requesting one bounded YouTube page. No other source job is affected.": "Tek bir sınırlı YouTube sayfası isteniyor. Başka hiçbir kaynak işi etkilenmez.",
  "Clear / discard YouTube results": "YouTube sonuçlarını temizleyin / atın",
  "Results discarded. An in-flight request may still consume its unit.": "Sonuçlar atıldı. Devam eden istek yine de birimini tüketebilir.",
  "YouTube search results": "YouTube arama sonuçları",
  "Collected": "Toplanma",
  "· requested region": "· istenen bölge",
  "· returned region": "· dönen bölge",
  "· requested language": "· istenen dil",
  "· clear by": "· son temizleme zamanı",
  ". Original metadata, not verified business facts.": ". Özgün meta veriler; doğrulanmış işletme bilgileri değildir.",
  "provider default": "sağlayıcı varsayılanı",
  "This selected request returned no videos; no market-demand conclusion.": "Bu seçilen istek video döndürmedi; pazar talebi hakkında sonuç çıkarılamaz.",
  "Additional pages may exist. This bounded feature does not request them.": "Ek sayfalar olabilir. Bu sınırlı özellik onları istemez.",
  "Official Google Trends remains unavailable: no supported public endpoint/schema is configured. No scraper.": "Resmî Google Trends kullanılamıyor: desteklenen herkese açık uç nokta/şema yapılandırılmamış. Kazıyıcı yoktur.",
  "Refresh current project selection (clears results)": "Güncel proje seçimini yenileyin (sonuçları temizler)",
  "YouTube screen data cleared.": "YouTube ekran verileri temizlendi.",
  "YouTube results expired and were cleared.": "YouTube sonuçlarının süresi doldu ve temizlendi.",
  "Current project/source unavailable or access revoked.": "Güncel proje/kaynak kullanılamıyor veya erişim iptal edildi.",
  "Request outcome unavailable. No result retained and no automatic retry; usage may have been consumed.": "İstek sonucu kullanılamıyor. Sonuç saklanmadı ve otomatik yeniden deneme yoktur; kullanım hakkı tüketilmiş olabilir."
};

@Component({
  selector: 'app-project-youtube', imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="youtube-title">
      <h1 id="youtube-title">{{ t("YouTube public-video search") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish project YouTube interface draft in local development. Provider values and request error codes retain their source form; bilingual Terms/privacy approval is pending.") }}</p> }
      <p><a [routerLink]="['/app/topics', organizationId, projectId]">{{ t("Return to topic review") }}</a> ·
        <a [routerLink]="['/app/onboarding', organizationId, projectId]">{{ t("Configure project seeds and languages") }}</a></p>
      @if (loading()) { <p role="status">{{ t("Checking project source selection.") }}</p> }
      @if (error()) { <p role="alert" [attr.lang]="textLanguage(error())">{{ t(error()) }}</p> }
      @if (message()) { <p role="status">{{ t(message()) }}</p> }
      @if (!loading() && ready()) {
        <p>{{ t("Active project:") }} <span lang="">{{ projectName() }}</span> {{ t("(organization") }} {{ organizationId }}{{ t("). Separate YouTube API metadata, in original provider order. No topic/demand/popularity/competition score or AI/research/content handoff. Live access, policy/legal and bilingual release review remain unverified.") }}</p>
        <section aria-labelledby="youtube-privacy-title">
          <h2 id="youtube-privacy-title">{{ t("YouTube feature Terms and privacy — development draft") }}</h2>
          <p>{{ t("This feature uses YouTube API Services. By using it you agree to be bound by the") }}
            <a href="https://www.youtube.com/t/terms" target="_blank" rel="noopener noreferrer">{{ t("YouTube Terms of Service") }}</a>
            {{ t("and this feature's Terms/privacy disclosure (") }}<span lang="en">{{ policyVersion() }}</span>).
            <a href="https://policies.google.com/privacy" target="_blank" rel="noopener noreferrer">{{ t("Google Privacy Policy") }}</a>.</p>
          <p>{{ t("We send the selected seed, publication window, language preference and optional viewability region to Google, using the platform's key and server network address. No private YouTube account/OAuth data is requested. Returned titles, video/channel identifiers and dates are shown only to you in this screen's memory, for at most fifteen minutes. We do not store them in database, artifacts, logs, exports or backups, share them with AI, or use them to derive metrics. No videos, thumbnails, embeds, adverts or media are loaded here.") }}</p>
          <p>{{ t("Only your selected inputs, versioned acceptance, actor/project, request status and internal-unit usage are retained in existing private operational records under the organization's retention policy. Private account session/CSRF cookies secure this request; this feature adds no browser storage or tracking cookies. Clear results below to discard this screen's data; leaving/hiding/reloading also clears it. This does not delete anything on YouTube. Following a YouTube link opens YouTube under Google's policies.") }}</p>
          <p>{{ t("Our first-page twenty-result, one/seven-day and configured-seed/language bounds are OrganicSEOOps limits, not YouTube limits. Region selects video viewability, not topic geography; relevance language is a preference, not a guaranteed result language. Empty/top-N results do not establish no demand or complete coverage.") }}
            <a href="https://www.youtube.com/" target="_blank" rel="noopener noreferrer">{{ t("Open full YouTube") }}</a>.</p>
        </section>
        @if (!configured()) { <p>{{ t("Unavailable: a dedicated staff YouTube key is not configured. Other source discovery remains independent.") }}</p> }
        @else if (!canSearch()) { <p>{{ t("Your role is read-only; it cannot run a source search.") }}</p> }
        @else if (!phrases().length || !languages().length) { <p>{{ t("Configure a supported plain seed and SEO language first.") }}</p> }
        @else {
          <form (submit)="search($event)">
            <label for="youtube-phrase">{{ t("Current configured seed") }}</label><select id="youtube-phrase" name="phrase" required>
              <option value="">{{ t("Choose a seed") }}</option>@for (phrase of phrases(); track phrase) { <option [value]="phrase" lang="">{{ phrase }}</option> }
            </select>
            <label for="youtube-language">{{ t("Relevance-language preference") }}</label><select id="youtube-language" name="language" required>
              <option value="">{{ t("Choose a language") }}</option>@for (language of languages(); track language) { <option [value]="language" lang="en">{{ language }}</option> }
            </select>
            <label for="youtube-region">{{ t("Optional video-viewability country code (two uppercase letters)") }}</label>
            <input id="youtube-region" name="region" pattern="[A-Z]{2}" maxlength="2" autocomplete="off" />
            <label for="youtube-days">{{ t("Publication window") }}</label><select id="youtube-days" name="days"><option value="1">{{ t("Last one day") }}</option><option value="7">{{ t("Last seven days") }}</option></select>
            <label><input name="accepted" type="checkbox" required /> {{ t("I agree to the YouTube Terms and this feature's Terms/privacy disclosure above.") }}</label>
            <p>{{ t("One internal unit per accepted request, shared client quota, at most ten seconds, no automatic retry/paging. Failed or discarded requests may consume that unit. Existing commercial allowances and expiry apply.") }}</p>
            <button type="submit" [disabled]="busy()">{{ t("Search YouTube once") }}</button>
          </form>
        }
        @if (busy()) { <p role="status">{{ t("Requesting one bounded YouTube page. No other source job is affected.") }}</p> }
        <button type="button" (click)="clear('Results discarded. An in-flight request may still consume its unit.')">{{ t("Clear / discard YouTube results") }}</button>
        @if (page(); as result) {
          <h2>{{ t("YouTube search results") }}</h2>
          <p>{{ t("Collected") }} <span lang="en">{{ collectedAt() }}</span> {{ t("· requested region") }} <span [attr.lang]="requestedRegion() ? 'en' : uiLanguage()">{{ requestedRegion() || t('provider default') }}</span> {{ t("· returned region") }} <span lang="en">{{ result.regionCode }}</span> {{ t("· requested language") }} <span lang="en">{{ requestedLanguage() }}</span> {{ t("· clear by") }} <span lang="en">{{ expiresAt() }}</span>{{ t(". Original metadata, not verified business facts.") }}</p>
          <ol>@for (video of result.items; track $index) {
            <li><a [href]="videoUrl(video.id.videoId)" target="_blank" rel="noopener noreferrer"><span lang="">{{ video.snippet.title }}</span></a>
              <p><span lang="">{{ video.snippet.channelTitle }}</span> · <span lang="en">{{ video.snippet.channelId }}</span> · <span lang="en">{{ video.snippet.publishedAt }}</span></p></li>
          } @empty { <li>{{ t("This selected request returned no videos; no market-demand conclusion.") }}</li> }</ol>
          @if (result.nextPageToken) { <p>{{ t("Additional pages may exist. This bounded feature does not request them.") }}</p> }
        }
        <p>{{ t("Official Google Trends remains unavailable: no supported public endpoint/schema is configured. No scraper.") }}</p>
      }
      <button type="button" (click)="load()" [disabled]="busy()">{{ t("Refresh current project selection (clears results)") }}</button>
    </section>`,
  styles: `label { display:block; margin-block:.6rem .2rem } input:not([type=checkbox]), select { max-width:100%; width:min(100%,42rem) } section,li { overflow-wrap:anywhere } button { margin:.6rem .6rem .6rem 0 }`,
})
export class ProjectYouTube implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  textLanguage(text: string) {
    return Object.hasOwn(projectYouTubeTurkish, text) || this.errorDraft()?.message === text ? this.uiLanguage() : 'en';
  }
  t(text: string) {
    if (this.textLanguage(text) !== 'tr') return text;
    const draft = this.errorDraft();
    return draft?.message === text ? draft.translation : projectYouTubeTurkish[text];
  }
  private setDraftError(message: string, translation: string) {
    this.errorDraft.set({ message, translation });
    this.error.set(message);
  }
  private readonly document = inject(DOCUMENT); private readonly destroy = inject(DestroyRef);
  private generation = 0; private timer: ReturnType<typeof setTimeout> | undefined;
  organizationId = 0; projectId = 0;
  readonly loading = signal(true); readonly ready = signal(false); readonly busy = signal(false);
  readonly error = signal(''); readonly message = signal(''); readonly projectName = signal('');
  private readonly errorDraft = signal<{ message: string; translation: string } | null>(null);
  readonly configured = signal(false); readonly canSearch = signal(false); readonly policyVersion = signal('');
  readonly phrases = signal<string[]>([]); readonly languages = signal<string[]>([]); readonly page = signal<Page | null>(null);
  readonly collectedAt = signal(''); readonly expiresAt = signal(''); readonly requestedRegion = signal(''); readonly requestedLanguage = signal('');
  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi, title: Title) {
    effect(() => title.setTitle(`${this.t('Separate YouTube public-video search')} — OrganicSEOOps`));
  }
  ngOnInit() {
    void this.loadProductLanguage();
    const hide = () => this.clear('YouTube screen data cleared.');
    const visibility = () => { if (this.document.hidden) hide(); };
    this.document.addEventListener('visibilitychange', visibility); this.document.defaultView?.addEventListener('pagehide', hide);
    this.destroy.onDestroy(() => {
      this.clear(); this.document.removeEventListener('visibilitychange', visibility);
      this.document.defaultView?.removeEventListener('pagehide', hide);
    });
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroy)).subscribe((params) => {
      this.organizationId = Number(params.get('organizationId')); this.projectId = Number(params.get('projectId')); void this.load();
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
  videoUrl(id: string) { return typeof id === 'string' && id.length === 11 && /^[A-Za-z0-9_-]{11}$/.test(id) ? `https://www.youtube.com/watch?v=${id}` : ''; }
  clear(message = '') {
    ++this.generation; if (this.timer) clearTimeout(this.timer); this.timer = undefined;
    this.page.set(null); this.collectedAt.set(''); this.expiresAt.set(''); this.requestedRegion.set(''); this.requestedLanguage.set('');
    this.busy.set(false); this.loading.set(false); this.message.set(message);
  }
  async load() {
    this.clear(); const generation = this.generation;
    this.loading.set(true); this.ready.set(false); this.error.set(''); this.errorDraft.set(null); this.projectName.set(''); this.canSearch.set(false);
    this.configured.set(false); this.phrases.set([]); this.languages.set([]); this.policyVersion.set('');
    try {
      if (![this.organizationId, this.projectId].every((id) => Number.isSafeInteger(id) && id > 0)) throw new Error();
      const context = await this.api.projectOnboarding(this.organizationId, this.projectId);
      if (generation !== this.generation) return;
      const project = context.body['project'] as Record<string, unknown> | undefined;
      if (context.status !== 200 || project?.['id'] !== this.projectId || project['organization_id'] !== this.organizationId
        || typeof project['role'] !== 'string' || !['owner', 'admin', 'member', 'viewer'].includes(project['role'])) throw new Error();
      this.projectName.set(String(project['name'])); this.canSearch.set(['owner', 'admin', 'member'].includes(project['role']));
      const response = await this.api.projectYouTube(this.organizationId, this.projectId); const body = response.body;
      if (generation !== this.generation) return;
      if (response.status !== 200 || body['project_id'] !== this.projectId || body['policy_version'] !== 'youtube-response-only-v1'
        || body['memory_seconds'] !== 900 || body['live_verified'] !== false || typeof body['configured'] !== 'boolean'
        || !Array.isArray(body['phrases']) || !body['phrases'].every((item: unknown) => typeof item === 'string')
        || !Array.isArray(body['languages']) || !body['languages'].every((item: unknown) => typeof item === 'string')) throw new Error();
      this.phrases.set(body['phrases']); this.languages.set(body['languages']); this.configured.set(body['configured']);
      this.policyVersion.set(String(body['policy_version'])); this.ready.set(true);
    } catch { if (generation === this.generation) this.error.set('Current project/source unavailable or access revoked.'); }
    finally { if (generation === this.generation) this.loading.set(false); }
  }
  async search(event: SubmitEvent) {
    event.preventDefault(); const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || this.busy() || !this.canSearch() || !this.configured() || !this.ready()) return;
    const fields = new FormData(form);
    if (fields.get('accepted') !== 'on') return;
    const selection = { phrase: String(fields.get('phrase')), relevance_language: String(fields.get('language')),
      region_code: String(fields.get('region')) || null, days: Number(fields.get('days')) };
    this.clear(); const generation = this.generation; this.busy.set(true); this.error.set(''); this.errorDraft.set(null);
    try {
      const response = await this.api.projectYouTube(this.organizationId, this.projectId, {
        selection, accepted: true, policy_version: this.policyVersion(), request_key: crypto.randomUUID() });
      if (generation !== this.generation) return;
      const body = response.body; const page = readPage(body['page']);
      const expiry = Date.parse(String(body['expires_at'])); const remaining = expiry - Date.now();
      if (response.status !== 200 || body['project_id'] !== this.projectId || body['source'] !== 'youtube' || !page
        || !Number.isFinite(remaining) || remaining <= 0 || remaining > 900_000) {
        this.setDraftError(`YouTube search unavailable (${String(body['code'] || 'request_not_confirmed')}). No automatic retry; no result retained.`,
          `YouTube araması kullanılamıyor (${String(body['code'] || 'request_not_confirmed')}). Otomatik yeniden deneme yoktur; sonuç saklanmadı.`); return;
      }
      this.page.set(page); this.collectedAt.set(String(body['collected_at'])); this.expiresAt.set(String(body['expires_at']));
      this.requestedRegion.set(selection.region_code || ''); this.requestedLanguage.set(selection.relevance_language);
      this.timer = setTimeout(() => this.clear('YouTube results expired and were cleared.'), remaining);
    } catch { if (generation === this.generation) this.error.set('Request outcome unavailable. No result retained and no automatic retry; usage may have been consumed.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
}
