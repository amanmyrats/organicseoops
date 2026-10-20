import { Title } from '@angular/platform-browser';
import { JsonPipe } from '@angular/common';
import { Component, DestroyRef, OnInit, computed, effect, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi } from '../account/account-api';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';

type Judgment = { score: number | null; note: string };
export type TopicReview = { id: number; project_id: number; snapshot_id: number; candidate_index: number;
  revision: number; label: string; classification: string; language: string; market: string;
  intent_review_id: number | null; reason: string; created_at: string; judgments: Record<string, Judgment>;
  report: { components: { name: string; score: number | null; maximum: number; basis: string; note?: string }[];
    existing_mapping: { preferred_page: string; page_kind: string; action: string } | null } };
type Evidence = { kind: string; title?: string; query?: string; url?: string; source_feeds?: string[];
  provider?: string; property?: string; click_change?: number; impression_change?: number; attribution_url?: string };
type Candidate = { index: number; evidence: Evidence; review: TopicReview | null };
type Mapping = { review_id: number; label: string; language: string; market: string; page_kind: string;
  preferred_page: string; proposed_action: string; source_current: boolean };
type TopicJob = { id: number; project_id: number; status: string; error_category: string; snapshot_id: number | null;
  estimated_units: number; attempted_units: number; cancel_requested: boolean;
  steps: { name: string; status: string; error_category: string }[] };
const JOB_STATUSES = ['queued', 'running', 'waiting_provider', 'succeeded', 'failed', 'cancelled', 'partially_succeeded'];

const projectTopicsTurkish: Record<string, string> = {
  "Source-aware topic review": "Kaynakları dikkate alan konu incelemesi",
  "Topic discovery and human review": "Konu keşfi ve insan incelemesi",
  "Return to project evidence": "Proje kanıtlarına dönün",
  "Review existing intent/page coverage": "Mevcut amaç/sayfa kapsamını inceleyin",
  "Configure feeds and source access": "Akışları ve kaynak erişimini yapılandırın",
  "Checking current project topic sources.": "Güncel proje konu kaynakları kontrol ediliyor.",
  "Reload project topics": "Proje konularını yeniden yükleyin",
  "Active project:": "Aktif proje:",
  "(organization": "(kuruluş",
  "). First-party comparable query growth is measured; feed items are public observations. Relevance, value, coverage and trending/evergreen classification are human judgments. Competition, volume, ranking potential and duplication/cannibalization proof are unavailable, not zero. No AI classification or automatic publication.": "). Birinci taraf karşılaştırılabilir sorgu artışı ölçülür; akış öğeleri herkese açık gözlemlerdir. İlgililik, değer, kapsam ve trend/kalıcı sınıflandırması insan değerlendirmeleridir. Rekabet, hacim, sıralama potansiyeli ve çoğaltma/anahtar kelime çakışması kanıtı kullanılamıyor; sıfır değildir. Yapay zekâ sınıflandırması veya otomatik yayınlama yoktur.",
  "Choose bounded discovery sources": "Sınırlı keşif kaynaklarını seçin",
  "Reserve one internal unit per feed, query comparison and selected news source (at most seven). Existing allowances and expiry apply.": "Her akış, sorgu karşılaştırması ve seçilen haber kaynağı için bir dahili birim ayırın (en fazla yedi). Mevcut kullanım hakları ve süre bitimi geçerlidir.",
  "Separate YouTube public-video search": "Ayrı YouTube herkese açık video araması",
  "uses its own key/quota and response-only lifecycle. Official Trends remains alpha with no configured supported contract; no unofficial scraping. Missing sources cannot establish zero demand.": "kendi anahtarını/kotasını ve yalnızca yanıt yaşam döngüsünü kullanır. Resmî Trends, yapılandırılmış desteklenen sözleşme olmadan alfa aşamasında kalır; resmî olmayan kazıma yoktur. Eksik kaynaklar sıfır talep kanıtlayamaz.",
  "Configured HTTPS feeds (optional)": "Yapılandırılmış HTTPS akışları (isteğe bağlı)",
  "No approved feed is configured.": "Onaylanmış akış yapılandırılmadı.",
  "Optional first-party query source": "İsteğe bağlı birinci taraf sorgu kaynağı",
  "No query comparison": "Sorgu karşılaştırması yok",
  "Select complete adjacent equal-duration query windows from this same property/search type. The server checks metric/timezone compatibility; hidden-query coverage remains unknown.": "Aynı mülk/arama türünden eksiksiz, bitişik, eşit süreli sorgu pencerelerini seçin. Sunucu metrik/saat dilimi uyumluluğunu kontrol eder; gizli sorgu kapsamı bilinmiyor.",
  "Previous window": "Önceki pencere",
  "Choose previous import": "Önceki içe aktarmayı seçin",
  "· import": "· içe aktarma",
  "Current window": "Güncel pencere",
  "Choose current import": "Güncel içe aktarmayı seçin",
  "Optional GDELT news metadata": "İsteğe bağlı GDELT haber üst verileri",
  "GDELT DOC2 · twenty top metadata records from one publisher, one/seven-day window frozen at queue time. No publisher bodies/images fetched or licensed; dates are provider reported, not verified publication. English/translingual search is not measured project-market or source-language demand. Live provider readiness is unverified.": "GDELT DOC2 · tek yayıncıdan en üst yirmi üst veri kaydı, kuyruğa alma anında sabitlenen bir/yedi günlük pencere. Yayıncı gövdeleri/görselleri getirilmez veya lisanslanmaz; tarihler sağlayıcı bildirimi olup doğrulanmış yayın zamanı değildir. İngilizce/diller arası arama, ölçülen proje pazarı veya kaynak dili talebi değildir. Canlı sağlayıcı hazırlığı doğrulanmadı.",
  "GDELT Project attribution": "GDELT Project atfı",
  "Include one bounded GDELT metadata search": "Tek sınırlı GDELT üst veri aramasını dahil edin",
  "Configured plain seed phrase (English/translingual search)": "Yapılandırılmış düz başlangıç ifadesi (İngilizce/diller arası arama)",
  "Choose a current seed": "Güncel başlangıç ifadesi seçin",
  "Currently allowed HTTPS publisher origin": "Şu anda izin verilen HTTPS yayıncı kökeni",
  "Choose exact publisher": "Tam yayıncıyı seçin",
  "News metadata window": "Haber üst veri penceresi",
  "Last one day": "Son bir gün",
  "Last seven days": "Son yedi gün",
  "Configure a plain English seed phrase and approved publisher origin before selecting news.": "Haber seçmeden önce düz İngilizce başlangıç ifadesi ve onaylanmış yayıncı kökeni yapılandırın.",
  "Reserve and discover selected topics": "Seçilen konular için birim ayırın ve keşfedin",
  "Read-only topic history; your role cannot collect sources or correct reviews.": "Salt okunur konu geçmişi; rolünüz kaynak toplayamaz veya incelemeleri düzeltemez.",
  "Recent discovery jobs": "Son keşif işleri",
  "Refresh sources and jobs": "Kaynakları ve işleri yenileyin",
  "Job": "İş",
  "Inspect discovery": "Keşfi inceleyin",
  "No discovery job recorded.": "Keşif işi kaydedilmedi.",
  "At most ten recent jobs are shown.": "En fazla son on iş gösterilir.",
  "· attempted": "· denenen",
  "of": "/",
  "internal units.": "dahili birim.",
  "; failed sources are unavailable, not negative observations.": "; başarısız kaynaklar kullanılamaz; olumsuz gözlemler değildir.",
  "Refresh discovery status": "Keşif durumunu yenileyin",
  "Cancel discovery": "Keşfi iptal edin",
  "Inspect collected candidates": "Toplanan adayları inceleyin",
  "Immutable source collections": "Değişmez kaynak toplamaları",
  "candidates": "aday",
  "Inspect collection": "Toplamayı inceleyin",
  "No source collection; this does not establish no opportunities.": "Kaynak toplama yok; bu, fırsat olmadığını kanıtlamaz.",
  "Only the twenty most recent collections are shown.": "Yalnızca en son yirmi toplama gösterilir.",
  "Collection coverage / failures / truncation": "Toplama kapsamı / başarısızlıklar / kesilme",
  "Human topic classification filter": "İnsan konu sınıflandırma filtresi",
  "All": "Tümü",
  "Trending": "Trend",
  "Evergreen": "Kalıcı",
  "Unknown / not reviewed": "Bilinmiyor / incelenmedi",
  "Review candidate": "Adayı inceleyin",
  "No candidates in this filter; not a demand measurement.": "Bu filtrede aday yok; talep ölçümü değildir.",
  "Exact candidate evidence and correction history": "Tam aday kanıtı ve düzeltme geçmişi",
  "Observed source page": "Gözlenen kaynak sayfası",
  "Provider-returned news metadata observation, not search demand or verified article facts.": "Sağlayıcının döndürdüğü haber üst veri gözlemi; arama talebi veya doğrulanmış makale bilgileri değildir.",
  "Source: GDELT Project": "Kaynak: GDELT Project",
  ". Publisher content was not fetched; date and source-language/market fit remain unverified.": ". Yayıncı içeriği getirilmedi; tarih ve kaynak dili/pazar uyumu doğrulanmadı.",
  "Measured comparable click change": "Ölçülen karşılaştırılabilir tıklama değişimi",
  "; impression change": "; gösterim değişimi",
  ". Growth is not market-wide demand.": ". Artış, pazarın tümüne ait talep değildir.",
  "Exact stored source / dates / windows": "Tam kayıtlı kaynak / tarihler / pencereler",
  "Source configuration or mapped intent changed. Historical evidence only; recollect sources or select a current mapping before research.": "Kaynak yapılandırması veya eşlenen amaç değişti. Yalnızca tarihsel kanıt; araştırmadan önce kaynakları yeniden toplayın veya güncel eşleme seçin.",
  "Human review": "İnsan incelemesi",
  "· revision": "· sürüm",
  "Components are incomplete and not a comparable overall SEO score. Competition and demand volume unavailable.": "Bileşenler eksiktir ve karşılaştırılabilir genel SEO puanı değildir. Rekabet ve talep hacmi kullanılamıyor.",
  "Human-selected existing coverage:": "İnsanın seçtiği mevcut kapsam:",
  ". Page existence/coverage and query-page attribution are not provider verified.": ". Sayfa varlığı/kapsamı ve sorgu-sayfa atfı sağlayıcı tarafından doğrulanmadı.",
  "No mapped page reviewed; existing coverage remains unknown. Review coverage before proposing new content.": "Eşlenmiş sayfa incelenmedi; mevcut kapsam bilinmiyor. Yeni içerik önermeden önce kapsamı inceleyin.",
  "Research this exact reviewed topic": "Bu incelenmiş tam konuyu araştırın",
  "Human topic label": "İnsan konu etiketi",
  "Human classification (not measured demand)": "İnsan sınıflandırması (ölçülmüş talep değil)",
  "Configured SEO language": "Yapılandırılmış SEO dili",
  "Choose language": "Dil seçin",
  "Current human intent/page mapping (optional; required for known coverage)": "Güncel insan amaç/sayfa eşlemesi (isteğe bağlı; bilinen kapsam için gerekli)",
  "Coverage unknown / no mapping": "Kapsam bilinmiyor / eşleme yok",
  "Human scales: relevance/value/fit 0 low–3 high; coverage 0 little–3 substantial. Each known value needs a reason; unknown is distinct from zero.": "İnsan ölçekleri: ilgililik/değer/uyum 0 düşük–3 yüksek; kapsam 0 az–3 önemli. Her bilinen değer gerekçe gerektirir; bilinmeyen sıfırdan ayrıdır.",
  "· human judgment": "· insan değerlendirmesi",
  "Unknown": "Bilinmiyor",
  "rationale (required for known score)": "gerekçesi (bilinen puan için gerekli)",
  "Human decision / correction rationale": "İnsan kararı / düzeltme gerekçesi",
  "Save immutable human review": "Değişmez insan incelemesini kaydedin",
  "Up to twenty immutable review revisions": "En fazla yirmi değişmez inceleme sürümü",
  "Revision": "Sürüm",
  "Not reviewed.": "İncelenmedi.",
  "Cancellation requested.": "İptal istendi.",
  "unknown": "bilinmiyor",
  "unknown / unavailable": "bilinmiyor / kullanılamıyor",
  " of ": " / ",
  "Current mapping choices unavailable; known coverage requires a current reviewed mapping.": "Güncel eşleme seçenekleri kullanılamıyor; bilinen kapsam, güncel incelenmiş eşleme gerektirir.",
  "Project topic context unavailable or access revoked.": "Proje konu bağlamı kullanılamıyor veya erişim iptal edildi.",
  "Collection unavailable; refresh project sources.": "Toplama kullanılamıyor; proje kaynaklarını yenileyin.",
  "Candidate unavailable or source access revoked.": "Aday kullanılamıyor veya kaynak erişimi iptal edildi.",
  "Use 1–240 characters for the topic label and 1–500 for the decision rationale.": "Konu etiketi için 1–240, karar gerekçesi için 1–500 karakter kullanın.",
  "Use up to 240 characters for each human judgment rationale.": "Her insan değerlendirme gerekçesi için en fazla 240 karakter kullanın.",
  "Each known human judgment needs a rationale.": "Her bilinen insan değerlendirmesi gerekçe gerektirir.",
  "Human review saved; no content or site change approved.": "İnsan incelemesi kaydedildi; içerik veya site değişikliği onaylanmadı.",
  "Review unavailable or changed. Input retained; inspect current history before retrying.": "İnceleme kullanılamıyor veya değişti. Girdi korundu; tekrar denemeden önce güncel geçmişi inceleyin.",
  "Select a configured feed, comparable query pair or bounded news source.": "Yapılandırılmış akış, karşılaştırılabilir sorgu çifti veya sınırlı haber kaynağı seçin.",
  "Discovery queued. Inspect job status before submitting again; collection cannot imply demand or business relevance.": "Keşif kuyruğa alındı. Tekrar göndermeden önce iş durumunu inceleyin; toplama, talep veya iş ilgililiği anlamına gelemez.",
  "Discovery outcome unknown; refresh job history before retrying.": "Keşif sonucu bilinmiyor; tekrar denemeden önce iş geçmişini yenileyin.",
  "Job status/cancellation unavailable; refresh history.": "İş durumu/iptali kullanılamıyor; geçmişi yenileyin.",
  "Cancellation requested; incurred work remains counted.": "İptal istendi; gerçekleşmiş iş sayılmaya devam eder.",
  "Discovery status refreshed.": "Keşif durumu yenilendi.",
  "Discovery unavailable: check source windows, role, allowance and expiry.": "Keşif kullanılamıyor: kaynak pencerelerini, rolü, kullanım hakkını ve süre bitimini kontrol edin.",
  "relevance": "İlgililik",
  "business_value": "İş değeri",
  "geographic_language_fit": "Coğrafi/dil uyumu",
  "existing_coverage": "Mevcut kapsam",
  "trending": "Trend",
  "evergreen": "Kalıcı",
  "Unreviewed Turkish topic interface draft in local development. Human labels and source text retain their original language; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe konu arayüzü taslağı. İnsan etiketleri ve kaynak metni özgün dillerini korur; iki dilli onay bekleniyor."
};

@Component({
  selector: 'app-project-topics', imports: [RouterLink, JsonPipe],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="topics-title">
      <h1 id="topics-title">{{ t("Topic discovery and human review") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish topic interface draft in local development. Human labels and source text retain their original language; bilingual approval is pending.") }}</p> }
      <p><a [routerLink]="['/app/dashboard', organizationId, projectId]">{{ t("Return to project evidence") }}</a> ·
        <a [routerLink]="['/app/intent', organizationId, projectId]">{{ t("Review existing intent/page coverage") }}</a> ·
        <a [routerLink]="['/app/onboarding', organizationId, projectId]">{{ t("Configure feeds and source access") }}</a></p>
      @if (loading()) { <p role="status">{{ t("Checking current project topic sources.") }}</p> }
      @if (error()) { <p role="alert" [attr.lang]="t(error()) === error() ? 'en' : uiLanguage()">{{ t(error()) }}</p><button type="button" (click)="load()">{{ t("Reload project topics") }}</button> }
      @if (!loading() && !error()) {
        <p>{{ t("Active project:") }} <span lang="">{{ projectName() }}</span> {{ t("(organization") }} <span lang="en">{{ organizationId }}</span>{{ t("). First-party comparable query growth is measured; feed items are public observations. Relevance, value, coverage and trending/evergreen classification are human judgments. Competition, volume, ranking potential and duplication/cannibalization proof are unavailable, not zero. No AI classification or automatic publication.") }}</p>
        @if (canEdit()) {
          <section aria-labelledby="topic-sources-title"><h2 id="topic-sources-title">{{ t("Choose bounded discovery sources") }}</h2>
            <p>{{ t("Reserve one internal unit per feed, query comparison and selected news source (at most seven). Existing allowances and expiry apply.") }}
               <a [routerLink]="['/app/youtube', organizationId, projectId]">{{ t("Separate YouTube public-video search") }}</a> {{ t("uses its own key/quota and response-only lifecycle. Official Trends remains alpha with no configured supported contract; no unofficial scraping. Missing sources cannot establish zero demand.") }}</p>
            <form (submit)="discover($event)">
              <fieldset><legend>{{ t("Configured HTTPS feeds (optional)") }}</legend>
                @for (feed of feeds(); track feed; let i = $index) {
                  <label [for]="'topic-feed-' + i"><input [id]="'topic-feed-' + i" name="feeds" type="checkbox" [value]="feed" /><span lang="">{{ feed }}</span></label>
                } @empty { <p>{{ t("No approved feed is configured.") }}</p> }
              </fieldset>
              <label for="topic-connection">{{ t("Optional first-party query source") }}</label>
              <select id="topic-connection" name="connection_id" (change)="connection.set(+$any($event.target).value || null)">
                <option value="">{{ t("No query comparison") }}</option>
                @for (row of connections(); track row.id) { <option lang="" [value]="row.id">{{ row.provider }} · {{ row.property }}</option> }
              </select>
              @if (connection()) {
                <p>{{ t("Select complete adjacent equal-duration query windows from this same property/search type. The server checks metric/timezone compatibility; hidden-query coverage remains unknown.") }}</p>
                <label for="topic-previous">{{ t("Previous window") }}</label><select id="topic-previous" name="previous_import_id" required>
                  <option value="">{{ t("Choose previous import") }}</option>
                  @for (row of selectedImports(); track row.id) { <option lang="" [value]="row.id">{{ row.start }}–{{ row.end }} {{ t("· import") }} {{ row.id }}</option> }
                </select>
                <label for="topic-current">{{ t("Current window") }}</label><select id="topic-current" name="current_import_id" required>
                  <option value="">{{ t("Choose current import") }}</option>
                  @for (row of selectedImports(); track row.id) { <option lang="" [value]="row.id">{{ row.start }}–{{ row.end }} {{ t("· import") }} {{ row.id }}</option> }
                </select>
              }
              @if (news(); as source) {
                <fieldset><legend>{{ t("Optional GDELT news metadata") }}</legend>
                  <p>{{ t("GDELT DOC2 · twenty top metadata records from one publisher, one/seven-day window frozen at queue time. No publisher bodies/images fetched or licensed; dates are provider reported, not verified publication. English/translingual search is not measured project-market or source-language demand. Live provider readiness is unverified.") }}</p>
                  <a href="https://www.gdeltproject.org/" target="_blank" rel="noopener noreferrer">{{ t("GDELT Project attribution") }}</a>
                  @if (source.phrases.length && source.publisher_origins.length) {
                    <label for="topic-news"><input id="topic-news" name="include_news" type="checkbox" (change)="newsEnabled.set($any($event.target).checked)" />{{ t("Include one bounded GDELT metadata search") }}</label>
                    @if (newsEnabled()) {
                      <label for="topic-news-phrase">{{ t("Configured plain seed phrase (English/translingual search)") }}</label><select id="topic-news-phrase" name="news_phrase" required>
                        <option value="">{{ t("Choose a current seed") }}</option>@for (phrase of source.phrases; track phrase) { <option lang="" [value]="phrase">{{ phrase }}</option> }
                      </select>
                      <label for="topic-news-publisher">{{ t("Currently allowed HTTPS publisher origin") }}</label><select id="topic-news-publisher" name="news_publisher" required>
                        <option value="">{{ t("Choose exact publisher") }}</option>@for (origin of source.publisher_origins; track origin) { <option lang="" [value]="origin">{{ origin }}</option> }
                      </select>
                      <label for="topic-news-window">{{ t("News metadata window") }}</label><select id="topic-news-window" name="news_days"><option value="1">{{ t("Last one day") }}</option><option value="7">{{ t("Last seven days") }}</option></select>
                    }
                  } @else { <p>{{ t("Configure a plain English seed phrase and approved publisher origin before selecting news.") }}</p> }
                </fieldset>
              }
              <button type="submit" [disabled]="busy()">{{ t("Reserve and discover selected topics") }}</button>
            </form>
          </section>
        } @else { <p>{{ t("Read-only topic history; your role cannot collect sources or correct reviews.") }}</p> }
        <section aria-labelledby="topic-jobs-title"><h2 id="topic-jobs-title">{{ t("Recent discovery jobs") }}</h2>
          <button type="button" (click)="load()" [disabled]="busy()">{{ t("Refresh sources and jobs") }}</button>
          <ul>@for (row of jobs(); track row.id) {
            <li>{{ t("Job") }} <span lang="en">{{ row.id }}</span> · <span lang="en">{{ row.status }}</span> <button type="button" [disabled]="busy()" (click)="openJob(row.id)">{{ t("Inspect discovery") }} <span lang="en">{{ row.id }}</span></button></li>
          } @empty { <li>{{ t("No discovery job recorded.") }}</li> }</ul><p>{{ t("At most ten recent jobs are shown.") }}</p>
          @if (job(); as current) {
            <p role="status">{{ t("Job") }} <span lang="en">{{ current.id }}</span> · <span lang="en">{{ current.status }}</span> {{ t("· attempted") }} <span lang="en">{{ current.attempted_units }}</span> {{ t("of") }} <span lang="en">{{ current.estimated_units }}</span> {{ t("internal units.") }}
              {{ current.cancel_requested ? t("Cancellation requested.") : '' }}</p>
            @if (current.error_category) { <p role="alert"><span lang="en">{{ current.error_category }}</span>{{ t("; failed sources are unavailable, not negative observations.") }}</p> }
            <ul>@for (step of current.steps; track $index) { <li><span lang="en">{{ step.name }}</span> · <span lang="en">{{ step.status }}</span> · <span lang="en">{{ step.error_category }}</span></li> }</ul>
            <button type="button" [disabled]="busy()" (click)="openJob(current.id)">{{ t("Refresh discovery status") }}</button>
            @if (canEdit() && ['queued', 'running'].includes(current.status) && !current.cancel_requested) {
              <button type="button" [disabled]="busy()" (click)="openJob(current.id, true)">{{ t("Cancel discovery") }}</button>
            }
            @if (current.snapshot_id) { <button type="button" [disabled]="busy()" (click)="openSnapshot(current.snapshot_id)">{{ t("Inspect collected candidates") }}</button> }
          }
        </section>
        <section aria-labelledby="topic-history-title"><h2 id="topic-history-title">{{ t("Immutable source collections") }}</h2>
          <ul>@for (row of snapshots(); track row.id) {
            <li><span lang="en">{{ row.created_at }}</span> · <span lang="en">{{ row.candidate_count }}</span> {{ t("candidates") }} <button type="button" [disabled]="busy()" (click)="openSnapshot(row.id)">{{ t("Inspect collection") }} <span lang="en">{{ row.id }}</span></button></li>
          } @empty { <li>{{ t("No source collection; this does not establish no opportunities.") }}</li> }</ul>
          @if (hasMore()) { <p>{{ t("Only the twenty most recent collections are shown.") }}</p> }
          @if (snapshotId()) {
            <details><summary>{{ t("Collection coverage / failures / truncation") }}</summary><pre><span lang="en">{{ coverage() | json }}</span></pre></details>
            <label for="topic-filter">{{ t("Human topic classification filter") }}</label>
            <select id="topic-filter" (change)="filter.set($any($event.target).value)"><option value="all">{{ t("All") }}</option><option value="trending">{{ t("Trending") }}</option><option value="evergreen">{{ t("Evergreen") }}</option><option value="unknown">{{ t("Unknown / not reviewed") }}</option></select>
            <ul>@for (row of filtered(); track row.index) {
              <li><span lang="">{{ row.review?.label || row.evidence.title || row.evidence.query }}</span> · <span lang="en">{{ row.review?.classification || t("unknown") }}</span> · <span lang="en">{{ row.evidence.kind }}</span>
                <button type="button" [disabled]="busy()" (click)="openCandidate(row.index)">{{ t("Review candidate") }} <span lang="en">{{ row.index + 1 }}</span></button></li>
            } @empty { <li>{{ t("No candidates in this filter; not a demand measurement.") }}</li> }</ul>
          }
        </section>
        @if (candidate(); as selected) {
          <section aria-labelledby="topic-review-title"><h2 id="topic-review-title">{{ t("Exact candidate evidence and correction history") }}</h2>
            <p><span lang="">{{ selected.evidence.title || selected.evidence.query }}</span> · <span lang="en">{{ selected.evidence.kind }}</span></p>
            @if (safeUrl(selected.evidence.url); as url) { <a [href]="url" target="_blank" rel="noopener noreferrer">{{ t("Observed source page") }}</a> }
            @if (selected.evidence.kind === 'provider_news_article') {
              <p>{{ t("Provider-returned news metadata observation, not search demand or verified article facts.") }}
                <a href="https://www.gdeltproject.org/" target="_blank" rel="noopener noreferrer">{{ t("Source: GDELT Project") }}</a>{{ t(". Publisher content was not fetched; date and source-language/market fit remain unverified.") }}</p>
            }
            @if (selected.evidence.kind === 'first_party_query_growth') {
              <p>{{ t("Measured comparable click change") }} <span lang="en">{{ selected.evidence.click_change }}</span>{{ t("; impression change") }} <span lang="en">{{ selected.evidence.impression_change }}</span>.
                <span lang="en">{{ selected.evidence.provider }}</span> · <span lang="">{{ selected.evidence.property }}</span>{{ t(". Growth is not market-wide demand.") }}</p>
            }
            <details><summary>{{ t("Exact stored source / dates / windows") }}</summary><pre><span lang="en">{{ selected.evidence | json }}</span></pre></details>
            @if (!sourceCurrent()) { <p role="alert">{{ t("Source configuration or mapped intent changed. Historical evidence only; recollect sources or select a current mapping before research.") }}</p> }
            @if (currentReview(); as review) {
              <p>{{ t("Human review") }} <span lang="en">{{ review.id }}</span> {{ t("· revision") }} <span lang="en">{{ review.revision }}</span> · <span lang="">{{ review.market }}</span> / <span lang="en">{{ review.language }}</span> · <span lang="en">{{ review.classification }}</span>.</p>
              <ul>@for (part of review.report.components; track part.name) {
                <li><span lang="en">{{ part.name }}</span>: {{ part.score === null ? t("unknown / unavailable") : part.score + t(" of ") + part.maximum }} · <span lang="en">{{ part.basis }}</span> · <span lang="">{{ part.note }}</span></li>
              }</ul>
              <p>{{ t("Components are incomplete and not a comparable overall SEO score. Competition and demand volume unavailable.") }}</p>
              @if (review.report.existing_mapping; as mapping) {
                <p>{{ t("Human-selected existing coverage:") }} <span lang="en">{{ mapping.page_kind }}</span> · <span lang="">{{ mapping.preferred_page }}</span> · <span lang="en">{{ mapping.action }}</span>{{ t(". Page existence/coverage and query-page attribution are not provider verified.") }}</p>
              } @else { <p>{{ t("No mapped page reviewed; existing coverage remains unknown. Review coverage before proposing new content.") }}</p> }
              @if (sourceCurrent()) {
                <a [routerLink]="['/app/research', organizationId, projectId]" [queryParams]="{ topic_review: review.id }">{{ t("Research this exact reviewed topic") }}</a>
              }
            }
            @if (canEdit()) {
              <form (submit)="save($event)">
                <label for="topic-label">{{ t("Human topic label") }}</label><input lang="" id="topic-label" name="label" maxlength="480" required [value]="currentReview()?.label || selected.evidence.title || selected.evidence.query || ''" />
                <label for="topic-class">{{ t("Human classification (not measured demand)") }}</label><select id="topic-class" name="classification">
                  @for (value of ['unknown', 'trending', 'evergreen']; track value) { <option [value]="value" [selected]="value === (currentReview()?.classification || 'unknown')">{{ t(value) }}</option> }
                </select>
                <label for="topic-language">{{ t("Configured SEO language") }}</label><select id="topic-language" name="language" required>
                  <option value="">{{ t("Choose language") }}</option>@for (value of languages(); track value) { <option [value]="value" [selected]="value === currentReview()?.language">{{ value }}</option> }
                </select>
                <label for="topic-mapping">{{ t("Current human intent/page mapping (optional; required for known coverage)") }}</label><select id="topic-mapping" name="intent_review_id">
                  <option value="" [selected]="!currentReview()?.intent_review_id">{{ t("Coverage unknown / no mapping") }}</option>
                  @for (row of mappings(); track row.review_id) { <option lang="" [value]="row.review_id" [selected]="row.review_id === currentReview()?.intent_review_id">{{ row.label }} · {{ row.language }} · {{ row.page_kind }} · {{ row.preferred_page }} · {{ row.proposed_action }}</option> }
                </select>
                <p>{{ t("Human scales: relevance/value/fit 0 low–3 high; coverage 0 little–3 substantial. Each known value needs a reason; unknown is distinct from zero.") }}</p>
                @for (name of humanComponents; track name) {
                  <label [for]="'topic-score-' + name">{{ t(name) }} {{ t("· human judgment") }}</label><select [id]="'topic-score-' + name" [name]="name + '_score'">
                    <option value="" [selected]="currentReview()?.judgments?.[name]?.score == null">{{ t("Unknown") }}</option>
                    @for (score of [0, 1, 2, 3]; track score) { <option [value]="score" [selected]="score === currentReview()?.judgments?.[name]?.score">{{ score }}</option> }
                  </select>
                  <label [for]="'topic-note-' + name">{{ t(name) }} {{ t("rationale (required for known score)") }}</label><textarea lang="" [id]="'topic-note-' + name" [name]="name + '_note'" maxlength="480" [value]="currentReview()?.judgments?.[name]?.note || ''"></textarea>
                }
                <label for="topic-reason">{{ t("Human decision / correction rationale") }}</label><textarea lang="" id="topic-reason" name="reason" maxlength="1000" required [value]="currentReview()?.reason || ''"></textarea>
                <button type="submit" [disabled]="busy()">{{ t("Save immutable human review") }}</button>
              </form>
            }
            <details><summary>{{ t("Up to twenty immutable review revisions") }}</summary><ol>@for (row of history(); track row.id) {
              <li>{{ t("Revision") }} <span lang="en">{{ row.revision }}</span> · <span lang="en">{{ row.created_at }}</span> · <span lang="">{{ row.label }}</span> · <span lang="en">{{ row.classification }}</span> · <span lang="">{{ row.reason }}</span><pre><span lang="en">{{ row.judgments | json }}</span></pre></li>
            } @empty { <li>{{ t("Not reviewed.") }}</li> }</ol></details>
          </section>
        }
      }
      @if (message()) { <p role="status" [attr.lang]="t(message()) === message() ? 'en' : uiLanguage()">{{ t(message()) }}</p> }
      @if (saveError()) { <p role="alert" id="topic-save-error" tabindex="-1" [attr.lang]="t(saveError()) === saveError() ? 'en' : uiLanguage()">{{ t(saveError()) }}</p> }
    </section>
  `,
  styles: `label { display:block; margin-block:.6rem .2rem } input:not([type=checkbox]), textarea, select { width:min(100%,42rem); max-width:100% } section, li { overflow-wrap:anywhere } pre { white-space:pre-wrap } button { margin:.6rem .6rem .6rem 0 } fieldset { min-width:0 }`,
})
export class ProjectTopics implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  t(text: string) { return this.uiLanguage() === 'tr' ? projectTopicsTurkish[text] ?? text : text; }
  organizationId = 0; projectId = 0; private generation = 0;
  readonly loading = signal(true); readonly busy = signal(false); readonly error = signal(''); readonly saveError = signal(''); readonly message = signal('');
  readonly projectName = signal(''); readonly canEdit = signal(false); readonly feeds = signal<string[]>([]); readonly languages = signal<string[]>([]);
  readonly connections = signal<{ id: number; provider: string; property: string }[]>([]);
  readonly imports = signal<{ id: number; connection_id: number; start: string; end: string }[]>([]);
  readonly connection = signal<number | null>(null); readonly mappings = signal<Mapping[]>([]);
  readonly news = signal<{ phrases: string[]; publisher_origins: string[] } | null>(null); readonly newsEnabled = signal(false);
  readonly snapshots = signal<{ id: number; created_at: string; candidate_count: number }[]>([]);
  readonly jobs = signal<{ id: number; status: string }[]>([]); readonly job = signal<TopicJob | null>(null); readonly hasMore = signal(false);
  readonly snapshotId = signal(0); readonly candidates = signal<Candidate[]>([]); readonly candidate = signal<Candidate | null>(null);
  readonly history = signal<TopicReview[]>([]); readonly sourceCurrent = signal(false); readonly coverage = signal<unknown>(null); readonly filter = signal('all');
  readonly humanComponents = ['relevance', 'business_value', 'geographic_language_fit', 'existing_coverage'];

  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi, private readonly destroy: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t('Source-aware topic review')} — OrganicSEOOps`));
    destroy.onDestroy(() => { this.generation++; });
  }
  ngOnInit() {
    void this.loadProductLanguage();
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroy)).subscribe((params) => {
      this.organizationId = Number(params.get('organizationId')); this.projectId = Number(params.get('projectId'));
      void this.load();
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
  currentReview(): TopicReview | null { return this.history()[0] || null; }
  private validEvidence(value: unknown): value is Evidence {
    const row = value as Record<string, unknown> | null;
    if (!row || typeof row !== 'object' || Array.isArray(row)
      || row['evergreen_state'] !== 'unknown' || row['business_relevance'] !== 'not_evaluated') return false;
    if (row['kind'] === 'first_party_query_growth') {
      const windows = row['source_windows'] as Record<string, unknown>[];
      const coverage = row['source_coverage'] as Record<string, unknown> | null;
      return !('title' in row) && !('url' in row) && typeof row['query'] === 'string' && row['query'].length > 0 && Array.from(row['query']).length <= 1000
        && ['provider', 'property', 'search_type'].every((key) => typeof row[key] === 'string')
        && ['connection_id', 'previous_observation_id', 'current_observation_id'].every((key) => Number.isSafeInteger(row[key]) && Number(row[key]) > 0)
        && Number.isSafeInteger(row['click_change']) && Number.isSafeInteger(row['impression_change'])
        && (Number(row['click_change']) > 0 || Number(row['impression_change']) > 0)
        && row['trend_state'] === 'first_party_comparable_growth'
        && Array.isArray(windows) && windows.length === 2 && windows.every((window) => window
          && Number.isSafeInteger(window['import_id']) && Number(window['import_id']) > 0
          && ['start', 'end', 'collected_at'].every((key) => typeof window[key] === 'string'))
        && windows[0]['import_id'] !== windows[1]['import_id'] && !!coverage
        && coverage['source_completeness'] === 'provider_export_unknown' && coverage['hidden_queries'] === 'unknown'
        && coverage['growth_is_not_business_relevance'] === true
        && ['missing_previous_queries', 'unavailable_metrics', 'ambiguous_zero_rows'].every((key) => Number.isSafeInteger(coverage[key]) && Number(coverage[key]) >= 0);
    }
    if (!['public_feed_item', 'provider_news_article'].includes(row['kind'] as string)
      || typeof row['title'] !== 'string' || !row['title'].trim() || Array.from(row['title']).length > 240
      || typeof row['url'] !== 'string' || Array.from(row['url']).length > 2048 || !this.safeUrl(row['url'])
      || !Array.isArray(row['source_feeds']) || !row['source_feeds'].length || row['source_feeds'].length > 5
      || !row['source_feeds'].every((feed) => typeof feed === 'string' && !!feed)
      || row['published_at'] !== null && typeof row['published_at'] !== 'string'
      || !['unknown', 'stale', 'recent'].includes(row['freshness'] as string) || row['trend_state'] !== 'not_measured') return false;
    if (row['kind'] === 'public_feed_item') return row['source_feeds'].every((feed) => Array.from(feed).length <= 512 && !!this.safeUrl(feed));
    const selection = row['news_selection'] as Record<string, unknown> | null;
    return row['provider'] === 'gdelt' && row['attribution_url'] === 'https://www.gdeltproject.org/'
      && typeof row['news_as_of'] === 'string' && row['date_basis'] === 'provider_reported_not_verified_publication'
      && row['market_language'] === 'not_verified_english_translingual_search' && !!selection
      && typeof selection['phrase'] === 'string' && /^[A-Za-z0-9][A-Za-z0-9 -]{1,119}$/.test(selection['phrase'])
      && selection['phrase'] === selection['phrase'].trim()
      && typeof selection['publisher_origin'] === 'string' && !!this.safeUrl(selection['publisher_origin'])
      && new URL(selection['publisher_origin']).origin === selection['publisher_origin']
      && (selection['days'] === 1 || selection['days'] === 7) && row['source_feeds'].length === 1
      && new URL(row['url']).origin === selection['publisher_origin']
      && (() => {
        try {
          const feed = new URL(row['source_feeds'][0]);
          return feed.origin === 'https://api.gdeltproject.org' && feed.pathname === '/api/v2/doc/doc'
            && !!feed.search && !feed.username && !feed.password && !feed.hash;
        } catch { return false; }
      })();
  }
  private validReview(value: unknown, snapshotId: number, index: number): value is TopicReview {
    const row = value as TopicReview | null;
    if (!row || Array.isArray(row) || !Number.isSafeInteger(row.id) || row.id < 1
      || row.project_id !== this.projectId || row.snapshot_id !== snapshotId || row.candidate_index !== index
      || !Number.isSafeInteger(row.revision) || row.revision < 1 || row.revision > 2147483647
      || typeof row.classification !== 'string' || !['unknown', 'trending', 'evergreen'].includes(row.classification)
      || typeof row.label !== 'string' || !row.label.trim() || Array.from(row.label).length > 240
      || typeof row.reason !== 'string' || !row.reason.trim() || Array.from(row.reason).length > 500
      || typeof row.language !== 'string' || !row.language || row.language.length > 35
      || typeof row.market !== 'string' || !row.market || Array.from(row.market).length > 120 || typeof row.created_at !== 'string'
      || row.intent_review_id !== null && (!Number.isSafeInteger(row.intent_review_id) || row.intent_review_id < 1)
      || !row.judgments || typeof row.judgments !== 'object' || Array.isArray(row.judgments)
      || Object.keys(row.judgments).length !== this.humanComponents.length
      || !this.humanComponents.every((name) => {
        const part = row.judgments[name];
        return part && !Array.isArray(part) && Object.keys(part).length === 2
          && typeof part.note === 'string' && Array.from(part.note).length <= 240
          && (part.score === null || Number.isSafeInteger(part.score) && part.score >= 0 && part.score <= 3 && !!part.note.trim());
      }) || row.intent_review_id === null && row.judgments['existing_coverage'].score !== null) return false;
    const report = row.report as TopicReview['report'] & { method: string; snapshot_id: number; candidate_index: number };
    const names = [...this.humanComponents, 'growth', 'freshness', 'evidence', 'competition'];
    if (!report || report.method !== 'topic-review-v1' || report.snapshot_id !== snapshotId || report.candidate_index !== index
      || !Array.isArray(report.components) || report.components.length !== names.length
      || !report.components.every((part, position) => {
        const maximum = ['growth', 'freshness'].includes(names[position]) ? 1 : 3;
        const judgment = row.judgments[names[position]];
        return part && part.name === names[position] && part.maximum === maximum
          && typeof part.basis === 'string' && !!part.basis && part.basis.length <= 160
          && (part.score === null || Number.isSafeInteger(part.score) && part.score >= 0 && part.score <= maximum)
          && (part.name !== 'growth' || part.score === null && part.basis === 'unavailable_feed_is_not_trend_measurement'
            || part.name === 'growth' && part.score === 1 && part.basis === 'one_point_for_observed_comparable_first_party_growth_not_strength')
          && (part.name !== 'freshness' || ['feed_reported_date_at_collection_not_verified_publication_or_current_freshness',
            'provider_reported_date_not_verified_publication_or_current_freshness'].includes(part.basis))
          && (part.name !== 'evidence' || part.score !== null && part.score >= 1
            && part.basis === 'bounded_source_observation_count_not_authority_confidence_or_demand')
          && (part.name !== 'competition' || part.score === null && part.basis === 'unavailable_no_connected_competition_provider')
          && (!judgment || part.score === judgment.score && part.note === judgment.note && part.basis === 'human_judgment_not_measured');
      })) return false;
    const mapping = report.existing_mapping as (NonNullable<TopicReview['report']['existing_mapping']>
      & { id: number; revision: number; evidence: string }) | null;
    return row.intent_review_id === null ? mapping === null : !!mapping && mapping.id === row.intent_review_id
      && Number.isSafeInteger(mapping.revision) && mapping.revision > 0 && mapping.revision <= 32767
      && typeof mapping.preferred_page === 'string' && mapping.evidence === 'human_selected_not_verified_page_coverage'
      && (mapping.page_kind === 'proposed' && mapping.action === 'create'
        || mapping.page_kind === 'existing_unverified' && typeof mapping.action === 'string'
          && ['keep', 'refresh', 'merge', 'redirect', 'retire'].includes(mapping.action));
  }
  selectedImports() { return this.imports().filter((row) => row.connection_id === this.connection()); }
  filtered() { return this.candidates().filter((row) => this.filter() === 'all' || (row.review?.classification || 'unknown') === this.filter()); }
  safeUrl(value?: string) {
    if (typeof value !== 'string') return '';
    try { const url = new URL(value || ''); return url.protocol === 'https:' && !url.username && !url.password && !url.search && !url.hash && (!url.port || url.port === '443') ? url.href : ''; }
    catch { return ''; }
  }
  async load() {
    const generation = ++this.generation;
    this.loading.set(true); this.busy.set(false); this.error.set(''); this.saveError.set(''); this.message.set('');
    this.projectName.set(''); this.canEdit.set(false); this.feeds.set([]); this.languages.set([]); this.connections.set([]); this.imports.set([]);
    this.connection.set(null); this.mappings.set([]); this.snapshots.set([]); this.jobs.set([]); this.job.set(null); this.hasMore.set(false);
    this.news.set(null); this.newsEnabled.set(false);
    this.snapshotId.set(0); this.candidates.set([]); this.candidate.set(null); this.history.set([]); this.sourceCurrent.set(false); this.coverage.set(null); this.filter.set('all');
    try {
      if (![this.organizationId, this.projectId].every((id) => Number.isSafeInteger(id) && id > 0)) throw new Error();
      const context = await this.api.projectOnboarding(this.organizationId, this.projectId);
      if (generation !== this.generation) return;
      const project = context.body['project'] as Record<string, unknown> | undefined;
      if (context.status !== 200 || project?.['id'] !== this.projectId || project['organization_id'] !== this.organizationId
        || typeof project['role'] !== 'string' || !['owner', 'admin', 'member', 'viewer'].includes(project['role'])) throw new Error();
      this.projectName.set(String(project['name']));
      const [response, mappings] = await Promise.all([this.api.projectTopics(this.organizationId, this.projectId), this.api.intentClusters(this.organizationId, this.projectId)]);
      if (generation !== this.generation) return;
      const body = response.body;
      if (response.status !== 200 || body['project_id'] !== this.projectId
        || !['feeds', 'languages', 'connections', 'imports', 'snapshots', 'jobs'].every((key) => Array.isArray(body[key]))
        || !['feeds', 'languages'].every((key) => (body[key] as unknown[]).every((value) => typeof value === 'string'))) throw new Error();
      this.feeds.set(body['feeds'] as string[]); this.languages.set(body['languages'] as string[]);
      this.connections.set((body['connections'] as ReturnType<ProjectTopics['connections']>).filter((row) => row
        && Number.isSafeInteger(row.id) && row.id > 0 && typeof row.provider === 'string' && typeof row.property === 'string'));
      this.imports.set((body['imports'] as ReturnType<ProjectTopics['imports']>).filter((row) => row
        && Number.isSafeInteger(row.id) && row.id > 0 && this.connections().some((source) => source.id === row.connection_id)
        && typeof row.start === 'string' && typeof row.end === 'string'));
      this.snapshots.set((body['snapshots'] as ReturnType<ProjectTopics['snapshots']>).filter((row) => row
        && Number.isSafeInteger(row.id) && row.id > 0 && typeof row.created_at === 'string'
        && Number.isSafeInteger(row.candidate_count) && row.candidate_count >= 0 && row.candidate_count <= 40));
      this.jobs.set((body['jobs'] as ReturnType<ProjectTopics['jobs']>).filter((row) => row && Number.isSafeInteger(row.id)
        && row.id > 0 && typeof row.status === 'string' && JOB_STATUSES.includes(row.status)));
      this.hasMore.set(body['has_more'] === true);
      const news = body['news'] as Record<string, unknown> | undefined;
      if (news?.['provider'] === 'gdelt' && Array.isArray(news['phrases']) && Array.isArray(news['publisher_origins'])) {
        this.news.set({ phrases: news['phrases'].filter((value): value is string => typeof value === 'string'),
          publisher_origins: news['publisher_origins'].filter((value): value is string => typeof value === 'string' && !!this.safeUrl(value)) });
      }
      if (mappings.status === 200 && mappings.body['project_id'] === this.projectId && Array.isArray(mappings.body['clusters'])) {
        this.mappings.set((mappings.body['clusters'] as Mapping[]).filter((row) => row && row.source_current === true
          && Number.isSafeInteger(row.review_id) && row.review_id > 0
          && ['label', 'language', 'market', 'preferred_page'].every((key) => typeof row[key as keyof Mapping] === 'string')
          && (row.page_kind === 'proposed' && row.proposed_action === 'create'
            || row.page_kind === 'existing_unverified' && ['keep', 'refresh', 'merge', 'redirect', 'retire'].includes(row.proposed_action))));
      } else this.message.set('Current mapping choices unavailable; known coverage requires a current reviewed mapping.');
      this.canEdit.set(['owner', 'admin', 'member'].includes(project['role']));
    } catch { if (generation === this.generation) this.error.set('Project topic context unavailable or access revoked.'); }
    finally { if (generation === this.generation) this.loading.set(false); }
  }
  async openSnapshot(id: number) {
    if (this.busy() || !Number.isSafeInteger(id) || id < 1) return;
    const generation = this.generation; this.busy.set(true); this.candidate.set(null); this.history.set([]); this.sourceCurrent.set(false); this.candidates.set([]); this.snapshotId.set(0); this.coverage.set(null); this.saveError.set('');
    try {
      const response = await this.api.projectTopics(this.organizationId, this.projectId, id);
      if (generation !== this.generation) return;
      const rows = response.body['candidates'] as Candidate[];
      if (response.status !== 200 || response.body['project_id'] !== this.projectId || response.body['snapshot_id'] !== id
        || !Array.isArray(rows) || rows.length > 40 || !rows.every((row, index) => row && row.index === index && this.validEvidence(row.evidence)
          && (row.review === null || this.validReview(row.review, id, index)))) throw new Error();
      this.snapshotId.set(id); this.candidates.set(response.body['candidates'] as Candidate[]); this.coverage.set(response.body['coverage']);
    } catch { if (generation === this.generation) this.message.set('Collection unavailable; refresh project sources.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  async openCandidate(index: number) {
    if (this.busy() || !this.candidates().some((row) => row.index === index)) return;
    const generation = this.generation; this.busy.set(true); this.candidate.set(null); this.history.set([]); this.sourceCurrent.set(false); this.saveError.set('');
    try {
      const response = await this.api.projectTopics(this.organizationId, this.projectId, this.snapshotId(), index);
      if (generation !== this.generation) return;
      if (response.status !== 200 || response.body['project_id'] !== this.projectId || response.body['snapshot_id'] !== this.snapshotId() || response.body['candidate_index'] !== index || !this.validEvidence(response.body['evidence']) || !Array.isArray(response.body['history'])) throw new Error();
      const history = response.body['history'] as TopicReview[];
      if (history.length > 20 || !history.every((row, position) => this.validReview(row, this.snapshotId(), index)
        && (!position || row.revision < history[position - 1].revision))
        || new Set(history.map((row) => row.id)).size !== history.length) throw new Error();
      this.history.set(history);
      this.candidate.set({ index, evidence: response.body['evidence'] as Evidence, review: this.currentReview() }); this.sourceCurrent.set(response.body['source_current'] === true);
    } catch { if (generation === this.generation) this.message.set('Candidate unavailable or source access revoked.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  async save(event: Event) {
    event.preventDefault(); const form = event.target as HTMLFormElement; const candidate = this.candidate();
    if (!candidate || !this.canEdit() || this.busy() || !form.reportValidity()) return;
    const fields = new FormData(form); const judgments: Record<string, Judgment> = {};
    const label = String(fields.get('label')).trim(); const reason = String(fields.get('reason')).trim();
    if (!label || Array.from(label).length > 240 || !reason || Array.from(reason).length > 500) {
      this.saveError.set('Use 1–240 characters for the topic label and 1–500 for the decision rationale.'); return;
    }
    for (const name of this.humanComponents) {
      const score = String(fields.get(name + '_score') || ''); const note = String(fields.get(name + '_note') || '').trim();
      if (Array.from(note).length > 240) { this.saveError.set('Use up to 240 characters for each human judgment rationale.'); return; }
      if (score && !note) { this.saveError.set('Each known human judgment needs a rationale.'); return; }
      judgments[name] = { score: score === '' ? null : Number(score), note };
    }
    const generation = this.generation; this.busy.set(true); this.saveError.set('');
    try {
      const response = await this.api.saveProjectTopic(this.organizationId, this.projectId, this.snapshotId(), candidate.index, {
        expected_revision: this.currentReview()?.revision || 0, request_key: crypto.randomUUID().replaceAll('-', ''),
        label, classification: fields.get('classification'), language: fields.get('language'),
        intent_review_id: fields.get('intent_review_id') ? Number(fields.get('intent_review_id')) : null, judgments, reason,
      });
      if (generation !== this.generation) return;
      const review = response.body['review'] as TopicReview | undefined;
      if (response.status !== 201 || response.body['project_id'] !== this.projectId
        || !this.validReview(review, this.snapshotId(), candidate.index)
        || review.revision !== (this.currentReview()?.revision || 0) + 1 || this.history().some((row) => row.id === review.id)) throw new Error();
      this.history.set([review, ...this.history()].slice(0, 20)); this.sourceCurrent.set(true);
      this.candidates.update((rows) => rows.map((row) => row.index === candidate.index ? { ...row, review } : row)); this.message.set('Human review saved; no content or site change approved.');
    } catch { if (generation === this.generation) { this.sourceCurrent.set(false); this.saveError.set('Review unavailable or changed. Input retained; inspect current history before retrying.'); } }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  async discover(event: Event) {
    event.preventDefault(); const form = event.target as HTMLFormElement;
    if (this.busy() || !this.canEdit() || !form.reportValidity()) return;
    const fields = new FormData(form); const feeds = fields.getAll('feeds').map(String);
    if (!feeds.length && !this.connection() && !this.newsEnabled()) { this.message.set('Select a configured feed, comparable query pair or bounded news source.'); return; }
    const generation = this.generation; this.busy.set(true); this.message.set('');
    try {
      const response = await this.api.discoverProjectTopics(this.organizationId, this.projectId, { feeds, connection_id: this.connection(),
        previous_import_id: this.connection() ? Number(fields.get('previous_import_id')) : null,
        current_import_id: this.connection() ? Number(fields.get('current_import_id')) : null,
        ...(this.newsEnabled() ? { news: { phrase: String(fields.get('news_phrase')), publisher_origin: String(fields.get('news_publisher')), days: Number(fields.get('news_days')) } } : {}),
        idempotency_key: crypto.randomUUID().replaceAll('-', '') });
      if (generation !== this.generation) return;
      if (response.status !== 202 || response.body['project_id'] !== this.projectId || !Number.isSafeInteger(response.body['job_id'])
        || Number(response.body['job_id']) <= 0 || typeof response.body['status'] !== 'string' || !JOB_STATUSES.includes(response.body['status'])) {
        this.message.set(String(response.body['code'] || 'Discovery unavailable: check source windows, role, allowance and expiry.')); return;
      }
      this.jobs.update((rows) => [{ id: Number(response.body['job_id']), status: response.body['status'] as string }, ...rows].slice(0, 10));
      this.message.set('Discovery queued. Inspect job status before submitting again; collection cannot imply demand or business relevance.');
    } catch { if (generation === this.generation) this.message.set('Discovery outcome unknown; refresh job history before retrying.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  async openJob(id: number, cancel = false) {
    if (this.busy() || !Number.isSafeInteger(id) || id < 1 || cancel && !this.canEdit()) return;
    const generation = this.generation; this.busy.set(true); this.job.set(null);
    try {
      const response = await this.api.projectTopicJob(this.organizationId, this.projectId, id, cancel);
      if (generation !== this.generation) return;
      const job = response.body['job'] as TopicJob | undefined;
      if (response.status !== 200 || response.body['project_id'] !== this.projectId || job?.project_id !== this.projectId || job.id !== id
        || typeof job.status !== 'string' || !JOB_STATUSES.includes(job.status) || typeof job.cancel_requested !== 'boolean'
        || typeof job.error_category !== 'string' || job.error_category.length > 64
        || job.snapshot_id !== null && (!Number.isSafeInteger(job.snapshot_id) || job.snapshot_id < 1)
        || !Number.isSafeInteger(job.estimated_units) || job.estimated_units < 1 || job.estimated_units > 7
        || !Number.isSafeInteger(job.attempted_units) || job.attempted_units < 0 || job.attempted_units > job.estimated_units
        || !Array.isArray(job.steps) || job.steps.length > 7 || !job.steps.every((step) => step
          && typeof step.name === 'string' && step.name.length > 0 && step.name.length <= 80
          && typeof step.status === 'string' && ['running', 'succeeded', 'failed'].includes(step.status)
          && typeof step.error_category === 'string' && step.error_category.length <= 64)) throw new Error();
      this.job.set(job); this.message.set(cancel ? 'Cancellation requested; incurred work remains counted.' : 'Discovery status refreshed.');
    } catch { if (generation === this.generation) { this.job.set(null); this.message.set('Job status/cancellation unavailable; refresh history.'); } }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
}
