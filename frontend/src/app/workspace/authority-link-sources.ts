import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, OnInit, computed, effect, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi, ApiResult } from '../account/account-api';
import { isTarget, safeUrl, same } from './authority-links';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';

type Binding = Record<string, unknown> & { project_id: number; organization_id: number; link_review_id: number;
  source_url: string; source_origin: string; target_url: string; target_evidence: unknown };
type Candidate = { link_review_id: number; binding: Binding; requires_separate_collection_permission: boolean };
type Selection = { method: string; parser_method: string; binding: Binding };
type Job = { id: number; project_id: number; link_review_id: number; idempotency_key: string; selection: Selection;
  status: string; created_at: string; updated_at: string; source_current: boolean; cancel_requested: boolean;
  error_category: string; estimate_units: number; attempted_units: number; evidence_state: string;
  evidence: { collection: Record<string, unknown>; source_current: boolean } | null;
  usage: { state: string; actual_units: number } | null };
type Context = { organization_id: number; project_id: number; can_collect: boolean; can_cancel: boolean; denial_category: string;
  candidates: Candidate[]; candidates_has_more: boolean; jobs: Job[]; has_more: boolean; lookup: string | null; collection_methods: string[] };
type Pending = { data: Record<string, unknown>; binding: Binding; method: string; jobId?: number; key: string };
type Observation = Record<string, unknown> & { job_id: number; step_id: number; artifact_id: number; observed_at: string; body_sha256: string;
  body_size_bytes: number; state: string; matching_target_count: number; coverage: Record<string, unknown> };
type Comparison = { method: string; project_id: number; requested_source_url: string; final_source_url: string; target_url: string;
  collection_method: string; parser_method: string;
  previous: Observation; current: Observation; comparable: boolean; state: string; body_changed: boolean; source_current: boolean;
  unlinked_or_lost_link: string; site_approval: string; interpretation: string };
type MentionSelection = { review_id: number; prospect_id: string; project_id: number; revision: number; state: string;
  quote: string; relevance: string; assignee_id: number; source_actor_id: number; reviewer_id: number; approved_by_id: number;
  requested_source_url: string; final_source_url: string; research_job_id: number; source_index: number; retrieved_at: string;
  body_sha256: string; body_size_bytes: number; source_current: boolean; mention_basis: string };
type Mention = { selection: MentionSelection; requested_source_url: string; final_source_url: string; target_url: string;
  research: Record<string, unknown>; static: Observation & { link_review_id: number; method: string; parser_method: string };
  state: string; static_coverage_complete: boolean };
type Destination = { selection: Selection; requested_source_url: string; final_source_url: string; target_url: string;
  target: Record<string, unknown>; static: Observation & { method: string; parser_method: string; redirects: unknown[] };
  static_coverage_complete: boolean; destination_recovery_candidate: boolean; state: string };
const positive = (value: unknown) => Number.isSafeInteger(value) && Number(value) > 0;
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const aware = (value: unknown) => typeof value === 'string' && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const COLLECTION = 'authority-static-link-collect-v1';
const PARSER = 'authority-static-link-parse-v1';
const URI_COLLECTION = 'authority-static-uri-collect-v1';
const URI_PARSER = 'authority-static-uri-parse-v1';
const parserMethod = (method: unknown) => method === COLLECTION ? PARSER : method === URI_COLLECTION ? URI_PARSER : null;
const MENTION_BASIS = 'human_selected_quote_in_normalized_bounded_research_text_not_browser_verification';

const authorityLinkSourcesTurkish: Record<string, string> = {
  "Private selected static-link verification": "Özel seçili statik bağlantı doğrulaması",
  "Selected static-link source verification": "Seçilen statik bağlantı kaynağının doğrulanması",
  "Organization": "Kuruluş",
  "· project": "· proje",
  "Human link reports and separate own-site recovery review": "İnsan bağlantı bildirimleri ve ayrı kendi site kurtarma incelemesi",
  "Project evidence": "Proje kanıtları",
  "Separately request one permitted external source from the unchanged latest human-approved verification activity. Robots denial or unknown stops collection. Only bounded static HTML is inspected: first 1,000 anchors, up to 20 exact own-target matches. Missing markup never proves an unlinked mention or lost link. Browser/CSS visibility, whole-site coverage and ranking benefit are unknown.": "Değişmemiş, insan tarafından en son onaylanan doğrulama faaliyetinden izin verilen tek bir dış kaynağı ayrıca isteyin. Robots reddi veya belirsizliği toplamayı durdurur. Yalnızca sınırlı statik HTML incelenir: ilk 1.000 bağlantı öğesi, en fazla 20 tam kendi hedef eşleşmesi. Eksik işaretleme, bağlantısız bahsedilmeyi veya kaybolmuş bağlantıyı hiçbir zaman kanıtlamaz. Tarayıcı/CSS görünürlüğü, tüm site kapsamı ve sıralama faydası bilinmiyor.",
  "One internal operation unit is reserved; an attempted or uncertain operation consumes it. This is not a provider charge. No recursive crawl, rendering, AI, sending or automatic schedule. Raw HTML, robots and unrelated links/text remain transient. Minimized evidence follows private export, 90-day retained access after lapse, active deletion within 30 days of closure/expiry and up to 35-day backup rotation after active deletion.": "Bir dahili işlem birimi ayrılır; denenmiş veya belirsiz işlem bu birimi tüketir. Bu, sağlayıcı ücreti değildir. Özyinelemeli tarama, işleme, yapay zekâ, gönderim veya otomatik zamanlama yoktur. Ham HTML, robots ve ilgisiz bağlantılar/metin geçici kalır. En aza indirilmiş kanıt; özel dışa aktarma, erişim süresi bittikten sonra 90 günlük saklanan erişim, kapatma/süre bitiminden sonra 30 gün içinde aktif silme ve aktif silmeden sonra en fazla 35 günlük yedek rotasyonuna tabidir.",
  "Loading current source eligibility and private job history.": "Güncel kaynak uygunluğu ve özel iş geçmişi yükleniyor.",
  "The exact command outcome is uncertain. Its request key and source/target binding are frozen in component memory. No automatic replay.": "Tam komut sonucu belirsiz. İstek anahtarı ve kaynak/hedef bağı bileşen belleğinde sabitlenir. Otomatik yeniden yürütme yoktur.",
  "Check exact uncertain command": "Tam belirsiz komutu kontrol edin",
  "Deliberately retry the same checked command": "Aynı kontrol edilmiş komutu bilinçli olarak tekrar deneyin",
  "Refresh authority and job status": "Yetkiyi ve iş durumunu yenileyin",
  "New collection unavailable:": "Yeni toplama kullanılamıyor:",
  ". Retained job metadata remains private; current-use evidence may be unavailable.": ". Saklanan iş üst verileri özel kalır; güncel kullanım kanıtı kullanılamayabilir.",
  "No current eligible human-approved verification source. Review the exact source and configured allow/block origins first.": "İnsanın onayladığı güncel uygun doğrulama kaynağı yok. Önce tam kaynağı ve yapılandırılmış izinli/engelli kökenleri inceleyin.",
  "Deliberate separately permissioned collection": "Ayrıca izin verilmiş bilinçli toplama",
  "Exact current approved human source": "İnsanın onayladığı tam güncel kaynak",
  "Select one source": "Bir kaynak seçin",
  "Review": "İnceleme",
  "Static reference interpretation": "Statik referans yorumlama",
  "Literal absolute href only (original v1)": "Yalnızca değişmez mutlak href (özgün v1)",
  "Bounded HTTPS URI references against final source URL (no base)": "Son kaynak URL'sine göre sınırlı HTTPS URI referansları (base yok)",
  "The URI method uses bounded standard-library joining, not browser URL repair. Publisher-relative references stay on the publisher. Any active base makes evidence unavailable; unsupported references make history and candidates incomparable. No resolved destination is fetched. Different methods cannot be compared or reinterpreted.": "URI yöntemi, tarayıcı URL düzeltmesi yerine sınırlı standart kitaplık birleştirmesi kullanır. Yayıncıya göreli referanslar yayıncıda kalır. Etkin bir base öğesi kanıtı kullanılamaz kılar; desteklenmeyen referanslar geçmişi ve adayları karşılaştırılamaz kılar. Çözümlenen hiçbir hedef getirilmez. Farklı yöntemler karşılaştırılamaz veya yeniden yorumlanamaz.",
  "Source": "Kaynak",
  "→ exact own target": "→ tam kendi hedefi",
  "Exact current human actors, rights, configuration and separate own-target HTTP evidence": "Tam güncel insan aktörleri, haklar, yapılandırma ve ayrı kendi hedef HTTP kanıtı",
  "I separately have permission to collect this exact selected source's bounded static HTML and retain minimized matching evidence under the disclosed policy. Human/outreach approval does not grant this permission.": "Bu seçilen tam kaynağın sınırlı statik HTML'sini toplamak ve açıklanan politika kapsamında en aza indirilmiş eşleşme kanıtını saklamak için ayrıca iznim var. İnsan/iletişim onayı bu izni vermez.",
  "Reserve 1 unit and request selected static source": "1 birim ayırın ve seçilen statik kaynağı isteyin",
  "Eligibility is limited to the newest 20 approved human activities.": "Uygunluk, insanın onayladığı en yeni 20 faaliyetle sınırlıdır.",
  "Private selected-source jobs": "Özel seçilmiş kaynak işleri",
  "No selected static-source collection jobs.": "Seçilen statik kaynak toplama işi yok.",
  "Only the latest 20 jobs are shown.": "Yalnızca en son 20 iş gösterilir.",
  "Job": "İş",
  "· human review": "· insan incelemesi",
  "· attempted operation units": "· denenmiş işlem birimleri",
  "Inspect exact job evidence": "Tam iş kanıtını inceleyin",
  "Read saved static-target destination candidate": "Kayıtlı statik hedefin hedef adayını okuyun",
  "Request cancellation": "İptal isteyin",
  "Associate a human mention with one saved static observation": "İnsanın seçtiği bahsedilmeyi kayıtlı tek bir statik gözlemle ilişkilendirin",
  "Choose both records deliberately. This private read makes no collection request and reserves no units. Exact requested/final source, original body digest and byte size must match; static collection must not predate research.": "Her iki kaydı bilinçli olarak seçin. Bu özel okuma toplama isteği yapmaz ve birim ayırmaz. İstenen/son kaynağın tamamı, özgün gövde özeti ve bayt boyutu eşleşmelidir; statik toplama araştırmadan önce olmamalıdır.",
  "No current approved human mention selections. Review a quote-backed mention prospect first.": "İnsanın onayladığı güncel bahsedilme seçimi yok. Önce alıntıya dayalı bir bahsedilme fırsatını inceleyin.",
  "Only the newest 20 approved mention activities are considered.": "Yalnızca onaylanmış en yeni 20 bahsedilme faaliyeti dikkate alınır.",
  "Current approved human mention": "İnsanın onayladığı güncel bahsedilme",
  "Choose human mention": "İnsanın seçtiği bahsedilmeyi seçin",
  "Saved static observation job": "Kayıtlı statik gözlem işi",
  "Choose saved job": "Kayıtlı işi seçin",
  "Read exact body-matched mention candidate": "Tam gövde eşleşmeli bahsedilme adayını okuyun",
  "Compare two saved selected-source observations": "Kayıtlı iki seçilmiş kaynak gözlemini karşılaştırın",
  "Choose previous and current jobs deliberately. Original collection dates must increase and the exact source, final URL, target, method and authority binding must match. This read does not collect a source or reserve units.": "Önceki ve güncel işleri bilinçli olarak seçin. Özgün toplama tarihleri artmalı; tam kaynak, son URL, hedef, yöntem ve yetki bağı eşleşmelidir. Bu okuma kaynak toplamaz veya birim ayırmaz.",
  "Previous observation job": "Önceki gözlem işi",
  "Choose previous job": "Önceki işi seçin",
  "Current observation job": "Güncel gözlem işi",
  "Choose current job": "Güncel işi seçin",
  "Read exact dated pair": "Tam tarihli çifti okuyun",
  "Saved static-target and dated destination evidence": "Kayıtlı statik hedef ve tarihli hedef kanıtı",
  "Requested source": "İstenen kaynak",
  "· final source": "· son kaynak",
  "→ exact target": "→ tam hedef",
  "Static job": "Statik iş",
  "· original collection": "· özgün toplama",
  "· matching parsed target count": "· eşleşen ayrıştırılmış hedef sayısı",
  "Static body SHA-256": "Statik gövde SHA-256",
  "bytes · step": "bayt · adım",
  "· private artifact": "· özel dosya",
  "Original source redirects:": "Özgün kaynak yönlendirmeleri:",
  "Separate original own-target HTTP observation": "Ayrı özgün kendi hedef HTTP gözlemi",
  "HTTP status": "HTTP durumu",
  "· original observation": "· özgün gözlem",
  "· crawl completed": "· tarama tamamlandı",
  ". This is dated evidence, not the current site state.": ". Bu, güncel site durumu değil, tarihli kanıttır.",
  "Original target scope, private readback, redirects and crawl coverage": "Özgün hedef kapsamı, özel geri okuma, yönlendirmeler ve tarama kapsamı",
  "Incomparable ambiguous or truncated static coverage; no supported destination-recovery conclusion.": "Karşılaştırılamaz belirsiz veya kesilmiş statik kapsam; desteklenen bir hedef kurtarma sonucu yok.",
  "Dated destination-recovery candidate: parsed exact-target markup and a separate original 404/410. Review whether restoring a useful destination is appropriate.": "Tarihli hedef kurtarma adayı: ayrıştırılmış tam hedef işaretlemesi ve ayrı özgün 404/410. Yararlı bir hedefi geri getirmenin uygun olup olmadığını inceleyin.",
  ". No supported dated missing-destination candidate; this does not prove a healthy current site or a recovered link.": ". Desteklenen tarihli eksik hedef adayı yok; bu, sağlıklı güncel siteyi veya kurtarılmış bağlantıyı kanıtlamaz.",
  "No current broken inbound link, browser visibility, verified unlinked/lost link or causal outcome is established. This read reserves no units, creates no action and approves no outreach or site change.": "Güncel bozuk gelen bağlantı, tarayıcı görünürlüğü, doğrulanmış bağlantısız/kaybolmuş bağlantı veya nedensel sonuç kanıtlanmaz. Bu okuma birim ayırmaz, eylem oluşturmaz ve iletişimi veya site değişikliğini onaylamaz.",
  "Separately select and approve an existing genuine own-page action; inspect implementation and technical follow-up": "Mevcut gerçek kendi sayfa eylemini ayrıca seçin ve onaylayın; uygulamayı ve teknik takibi inceleyin",
  "Human mention and separately dated static target evidence": "İnsanın seçtiği bahsedilme ve ayrı tarihli statik hedef kanıtı",
  "Original human-selected quote": "İnsanın seçtiği özgün alıntı",
  "Human relevance:": "İnsan ilgililik değerlendirmesi:",
  "· assignee": "· atanan kişi",
  "· review": "· inceleme",
  "revision": "sürüm",
  ". This normalized bounded-text selection is not automatic brand or browser verification.": ". Bu normalleştirilmiş sınırlı metin seçimi, otomatik marka veya tarayıcı doğrulaması değildir.",
  "Research retrieval": "Araştırma alımı",
  "· job": "· iş",
  "· source index": "· kaynak indeksi",
  "· step": "· adım",
  "Research coverage": "Araştırma kapsamı",
  "; unrelated excerpt is excluded.": "; ilgisiz alıntı dışarıda bırakılır.",
  "Separate original static observation": "Ayrı özgün statik gözlem",
  "· collection time": "· toplama zamanı",
  "Both original bodies: SHA-256": "Her iki özgün gövde: SHA-256",
  "bytes. Byte-equivalent separately returned documents do not verify a browser-visible mention.": "bayt. Bayt olarak eşdeğer ayrı döndürülen belgeler, tarayıcıda görünür bahsedilmeyi doğrulamaz.",
  "Incomparable ambiguous or truncated static coverage; no verified absence.": "Karşılaştırılamaz belirsiz veya kesilmiş statik kapsam; doğrulanmış yokluk yok.",
  ". Bounded candidate only, never independently verified unlinked or lost links.": ". Yalnızca sınırlı aday; hiçbir zaman bağımsız doğrulanmış bağlantısız veya kaybolmuş bağlantı değil.",
  "Browser visibility, whole-site/index coverage and causal outcomes are not established. Original human mention approval, outreach permission and own-site implementation approval remain separate human workflows.": "Tarayıcı görünürlüğü, tüm site/dizin kapsamı ve nedensel sonuçlar kanıtlanmaz. Özgün insan bahsedilme onayı, iletişim izni ve kendi site uygulama onayı ayrı insan iş akışları olarak kalır.",
  "Dated selected-source comparison": "Tarihli seçilmiş kaynak karşılaştırması",
  "Exact collection method": "Tam toplama yöntemi",
  "Incomparable ambiguous or truncated coverage. Counts describe bounded parsed markup, not verified absence or link loss.": "Karşılaştırılamaz belirsiz veya kesilmiş kapsam. Sayılar, doğrulanmış yokluğu veya bağlantı kaybını değil, sınırlı ayrıştırılmış işaretlemeyi tanımlar.",
  ". This is a bounded static-document candidate, never independently verified link loss.": ". Bu, sınırlı statik belge adayıdır; hiçbir zaman bağımsız doğrulanmış bağlantı kaybı değil.",
  "Original body digest": "Özgün gövde özeti",
  "; this does not establish a causal outcome.": "; bu, nedensel sonuç kanıtlamaz.",
  "job": "iş",
  "Original collection time": "Özgün toplama zamanı",
  "Body SHA-256": "Gövde SHA-256",
  "Browser visibility, whole-site/index coverage and independently verified unlinked/lost links are not established. Original human report, outreach decision and own-site implementation approval remain separate.": "Tarayıcı görünürlüğü, tüm site/dizin kapsamı ve bağımsız doğrulanmış bağlantısız/kaybolmuş bağlantılar kanıtlanmaz. Özgün insan bildirimi, iletişim kararı ve kendi site uygulama onayı ayrı kalır.",
  "Exact job": "Tam iş",
  "Updated": "Güncellendi",
  ". Completed/unknown attempts are never automatically replayed. This collection does not approve outreach or a website change.": ". Tamamlanmış/belirsiz denemeler hiçbir zaman otomatik yeniden yürütülmez. Bu toplama iletişimi veya web sitesi değişikliğini onaylamaz.",
  "Independently collected static markup, not a browser-visible link": "Bağımsız toplanmış statik işaretleme; tarayıcıda görünür bağlantı değil",
  "Parsed anchor text and rel are literal untrusted text. Missing or ambiguous markup is not independently verified link loss. Original human report and dated own-target HTTP/site-action approval remain separate.": "Ayrıştırılmış bağlantı metni ve rel, değişmez güvenilmeyen metindir. Eksik veya belirsiz işaretleme, bağımsız doğrulanmış bağlantı kaybı değildir. Özgün insan bildirimi ve tarihli kendi hedef HTTP/site eylemi onayı ayrı kalır.",
  "No current private source observation available. Failed, stale, denied and unknown are not zero links.": "Güncel özel kaynak gözlemi kullanılamıyor. Başarısız, eski, reddedilmiş ve belirsiz, sıfır bağlantı demek değildir.",
  "Current source at refresh": "Yenileme anında güncel kaynak",
  "Source/current-use unavailable": "Kaynak/güncel kullanım kullanılamıyor",
  "unavailable": "kullanılamıyor",
  "Truncated excerpt": "Kesilmiş alıntı",
  "Bounded excerpt": "Sınırlı alıntı",
  "changed": "değişti",
  "unchanged": "değişmedi",
  "Previous": "Önceki",
  "Current": "Güncel",
  "Select an authorized organization and project.": "Yetkili bir kuruluş ve proje seçin.",
  "Exact dated destination/current authority unavailable. Refresh history; unavailable is not zero or current broken/healthy link proof.": "Tam tarihli hedef/güncel yetki kullanılamıyor. Geçmişi yenileyin; kullanılamaması sıfır veya güncel bozuk/sağlıklı bağlantı kanıtı değildir.",
  "Exact body-matched mention/current authority unavailable. Refresh and deliberately select again; unavailable is not zero or verified unlinked proof.": "Tam gövde eşleşmeli bahsedilme/güncel yetki kullanılamıyor. Yenileyin ve yeniden bilinçli olarak seçin; kullanılamaması sıfır veya doğrulanmış bağlantısızlık kanıtı değildir.",
  "Exact dated pair/current authority unavailable. Refresh history; unavailable is not zero or verified link loss.": "Tam tarihli çift/güncel yetki kullanılamıyor. Geçmişi yenileyin; kullanılamaması sıfır veya doğrulanmış bağlantı kaybı değildir.",
  "Private source history or current authority is unavailable.": "Özel kaynak geçmişi veya güncel yetki kullanılamıyor.",
  "Exact current source readback unavailable; refresh authority.": "Tam güncel kaynak geri okuması kullanılamıyor; yetkiyi yenileyin.",
  "Command denied; refresh current authority before another decision.": "Komut reddedildi; başka karar vermeden önce güncel yetkiyi yenileyin.",
  "Exact command recorded. Refresh to check progress; no outreach or website change authorized.": "Tam komut kaydedildi. İlerlemeyi kontrol etmek için yenileyin; iletişim veya web sitesi değişikliği yetkilendirilmedi.",
  "Current exact source, method or authority changed. No collection command sent; refresh before another decision.": "Güncel tam kaynak, yöntem veya yetki değişti. Toplama komutu gönderilmedi; başka karar vermeden önce yenileyin.",
  "Command outcome uncertain. Check the exact request before continuing; no automatic replay.": "Komut sonucu belirsiz. Devam etmeden önce tam isteği kontrol edin; otomatik yeniden yürütme yoktur.",
  "No matching job found. Fresh exact source, target and authority match; deliberate same-command retry is available.": "Eşleşen iş bulunamadı. Yeni tam kaynak, hedef ve yetki eşleşiyor; aynı komutu bilinçli olarak tekrar deneme kullanılabilir.",
  "Command reconciled from authoritative status; no command replayed.": "Komut yetkili durumdan uzlaştırıldı; komut yeniden yürütülmedi.",
  "Exact outcome/current binding unavailable. No command replayed.": "Tam sonuç/güncel bağ kullanılamıyor. Komut yeniden yürütülmedi.",
  "Unreviewed Turkish static-link source interface draft in local development. Human quotes and source text retain their original language; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe statik bağlantı kaynağı arayüzü taslağı. İnsan alıntıları ve kaynak metni özgün dillerini korur; iki dilli onay bekleniyor."
};

@Component({
  selector: 'app-authority-link-sources', imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="source-title">
      <h1 id="source-title">{{ t("Selected static-link source verification") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish static-link source interface draft in local development. Human quotes and source text retain their original language; bilingual approval is pending.") }}</p> }
      <p>{{ t("Organization") }} <span lang="en">{{ organizationId }}</span> {{ t("· project") }} <span lang="en">{{ projectId }}</span> ·
        <a [routerLink]="['/app/authority-links', organizationId, projectId]">{{ t("Human link reports and separate own-site recovery review") }}</a> ·
        <a [routerLink]="['/app/dashboard', organizationId, projectId]">{{ t("Project evidence") }}</a></p>
      <p>{{ t("Separately request one permitted external source from the unchanged latest human-approved verification activity. Robots denial or unknown stops collection. Only bounded static HTML is inspected: first 1,000 anchors, up to 20 exact own-target matches. Missing markup never proves an unlinked mention or lost link. Browser/CSS visibility, whole-site coverage and ranking benefit are unknown.") }}</p>
      <p>{{ t("One internal operation unit is reserved; an attempted or uncertain operation consumes it. This is not a provider charge. No recursive crawl, rendering, AI, sending or automatic schedule. Raw HTML, robots and unrelated links/text remain transient. Minimized evidence follows private export, 90-day retained access after lapse, active deletion within 30 days of closure/expiry and up to 35-day backup rotation after active deletion.") }}</p>
      @if (loading()) { <p role="status">{{ t("Loading current source eligibility and private job history.") }}</p> }
      @if (error()) { <p role="alert" [attr.lang]="t(error()) === error() ? 'en' : uiLanguage()">{{ t(error()) }}</p> }
      @if (message()) { <p role="status" [attr.lang]="t(message()) === message() ? 'en' : uiLanguage()">{{ t(message()) }}</p> }
      @if (pending()) {
        <p>{{ t("The exact command outcome is uncertain. Its request key and source/target binding are frozen in component memory. No automatic replay.") }}</p>
        <button type="button" (click)="reconcile()" [disabled]="busy()">{{ t("Check exact uncertain command") }}</button>
        @if (notFound()) { <button type="button" (click)="retry()" [disabled]="busy()">{{ t("Deliberately retry the same checked command") }}</button> }
      } @else { <button type="button" (click)="load()" [disabled]="busy() || loading()">{{ t("Refresh authority and job status") }}</button> }
      @if (context(); as info) {
        @if (!info.can_collect) { <p>{{ t("New collection unavailable:") }} <span lang="en">{{ info.denial_category }}</span>{{ t(". Retained job metadata remains private; current-use evidence may be unavailable.") }}</p> }
        @if (info.can_collect && !pending()) {
          @if (!info.candidates.length) { <p>{{ t("No current eligible human-approved verification source. Review the exact source and configured allow/block origins first.") }}</p> }
          @else {
            <form (submit)="launch($event)"><fieldset [disabled]="busy()"><legend>{{ t("Deliberate separately permissioned collection") }}</legend>
              <label for="static-source">{{ t("Exact current approved human source") }}</label>
              <select id="static-source" name="source" required (change)="choose($event)"><option value="" [attr.lang]="uiLanguage()">{{ t("Select one source") }}</option>
                @for (row of info.candidates; track row.link_review_id) { <option lang="" [value]="row.link_review_id">{{ t("Review") }} {{ row.link_review_id }} · {{ row.binding.source_url }}</option> }
              </select>
              <label for="static-method">{{ t("Static reference interpretation") }}</label>
              <select id="static-method" name="method" required>
                <option value="authority-static-link-collect-v1">{{ t("Literal absolute href only (original v1)") }}</option>
                <option value="authority-static-uri-collect-v1">{{ t("Bounded HTTPS URI references against final source URL (no base)") }}</option>
              </select>
              <p>{{ t("The URI method uses bounded standard-library joining, not browser URL repair. Publisher-relative references stay on the publisher. Any active base makes evidence unavailable; unsupported references make history and candidates incomparable. No resolved destination is fetched. Different methods cannot be compared or reinterpreted.") }}</p>
              @if (chosen(); as row) {
                <p>{{ t("Source") }} <a [href]="safeUrl(row.binding.source_url)" target="_blank" rel="noopener noreferrer"><span lang="">{{ row.binding.source_url }}</span></a> {{ t("→ exact own target") }} <a [href]="safeUrl(row.binding.target_url)" target="_blank" rel="noopener noreferrer"><span lang="">{{ row.binding.target_url }}</span></a>.</p>
                <details><summary>{{ t("Exact current human actors, rights, configuration and separate own-target HTTP evidence") }}</summary><pre><span lang="en">{{ json(row.binding) }}</span></pre></details>
              }
              <label><input type="checkbox" name="permission" required />{{ t("I separately have permission to collect this exact selected source's bounded static HTML and retain minimized matching evidence under the disclosed policy. Human/outreach approval does not grant this permission.") }}</label>
              <button type="submit" [disabled]="!chosen()">{{ t("Reserve 1 unit and request selected static source") }}</button>
            </fieldset></form>
          }
        }
        @if (info.candidates_has_more) { <p>{{ t("Eligibility is limited to the newest 20 approved human activities.") }}</p> }
        <h2>{{ t("Private selected-source jobs") }}</h2>
        @if (!info.jobs.length) { <p>{{ t("No selected static-source collection jobs.") }}</p> }
        @if (info.has_more) { <p>{{ t("Only the latest 20 jobs are shown.") }}</p> }
        <ul>@for (job of info.jobs; track job.id) {
          <li>{{ t("Job") }} <span lang="en">{{ job.id }}</span> · <span lang="en">{{ job.selection.method }}</span> / <span lang="en">{{ job.selection.parser_method }}</span> {{ t("· human review") }} <span lang="en">{{ job.link_review_id }}</span> · <span lang="en">{{ job.status }}</span> {{ t("· attempted operation units") }} <span lang="en">{{ job.attempted_units }}</span> ·
            {{ job.source_current ? t("Current source at refresh") : t("Source/current-use unavailable") }} · <span lang="en">{{ job.error_category }}</span>
            <button type="button" (click)="inspect(job.id)" [disabled]="busy() || !!pending()">{{ t("Inspect exact job evidence") }}</button>
            @if (info.can_collect && job.status === 'succeeded' && job.source_current) {
              <button type="button" (click)="inspectDestination(job)" [disabled]="busy() || !!pending()">{{ t("Read saved static-target destination candidate") }}</button>
            }
            @if (info.can_cancel && ['queued', 'running'].includes(job.status)) {
              <button type="button" (click)="cancel(job)" [disabled]="busy() || !!pending() || job.cancel_requested">{{ t("Request cancellation") }}</button>
            }
          </li>
        }</ul>
        @if (info.can_collect && !pending()) {
          <form (submit)="readMention($event)"><fieldset [disabled]="busy() || loading()"><legend>{{ t("Associate a human mention with one saved static observation") }}</legend>
            <p>{{ t("Choose both records deliberately. This private read makes no collection request and reserves no units. Exact requested/final source, original body digest and byte size must match; static collection must not predate research.") }}</p>
            @if (!mentions().length) { <p>{{ t("No current approved human mention selections. Review a quote-backed mention prospect first.") }}</p> }
            @if (mentionsHasMore()) { <p>{{ t("Only the newest 20 approved mention activities are considered.") }}</p> }
            <label for="static-mention">{{ t("Current approved human mention") }}</label>
            <select id="static-mention" name="mention" required [value]="mentionId() || ''" (change)="chooseMention($event, true)">
              <option value="" [attr.lang]="uiLanguage()">{{ t("Choose human mention") }}</option>
              @for (row of mentions(); track row.review_id) { <option lang="" [value]="row.review_id">{{ t("Review") }} {{ row.review_id }} · {{ row.quote }}</option> }
            </select>
            <label for="static-mention-job">{{ t("Saved static observation job") }}</label>
            <select id="static-mention-job" name="mentionJob" required [value]="mentionJobId() || ''" (change)="chooseMention($event, false)">
              <option value="" [attr.lang]="uiLanguage()">{{ t("Choose saved job") }}</option>
              @for (job of info.jobs; track job.id) { @if (job.status === 'succeeded' && job.source_current) {
                <option lang="" [value]="job.id">{{ t("Job") }} {{ job.id }} · {{ job.selection.binding.source_url }} → {{ job.selection.binding.target_url }}</option>
              } }
            </select>
            <button type="submit" [disabled]="!mentionId() || !mentionJobId()">{{ t("Read exact body-matched mention candidate") }}</button>
          </fieldset></form>
          <form (submit)="compare($event)"><fieldset [disabled]="busy()"><legend>{{ t("Compare two saved selected-source observations") }}</legend>
            <p>{{ t("Choose previous and current jobs deliberately. Original collection dates must increase and the exact source, final URL, target, method and authority binding must match. This read does not collect a source or reserve units.") }}</p>
            <label for="static-previous">{{ t("Previous observation job") }}</label>
            <select id="static-previous" name="previous" required [value]="previousId() || ''" (change)="choosePair($event, true)">
              <option value="" [attr.lang]="uiLanguage()">{{ t("Choose previous job") }}</option>
              @for (job of info.jobs; track job.id) { @if (job.status === 'succeeded' && job.source_current) {
                <option lang="" [value]="job.id">{{ t("Job") }} {{ job.id }} · {{ job.selection.binding.source_url }} → {{ job.selection.binding.target_url }}</option>
              } }
            </select>
            <label for="static-current">{{ t("Current observation job") }}</label>
            <select id="static-current" name="current" required [value]="currentId() || ''" (change)="choosePair($event, false)">
              <option value="" [attr.lang]="uiLanguage()">{{ t("Choose current job") }}</option>
              @for (job of info.jobs; track job.id) { @if (job.status === 'succeeded' && job.source_current) {
                <option lang="" [value]="job.id">{{ t("Job") }} {{ job.id }} · {{ job.selection.binding.source_url }} → {{ job.selection.binding.target_url }}</option>
              } }
            </select>
            <button type="submit" [disabled]="!previousId() || !currentId() || previousId() === currentId()">{{ t("Read exact dated pair") }}</button>
          </fieldset></form>
        }
      }
      @if (destination(); as item) {
        <h2>{{ t("Saved static-target and dated destination evidence") }}</h2>
        <p>{{ t("Requested source") }} <span lang="">{{ item.requested_source_url }}</span> {{ t("· final source") }} <span lang="">{{ item.final_source_url }}</span> {{ t("→ exact target") }} <span lang="">{{ item.target_url }}</span>.</p>
        <p>{{ t("Static job") }} <span lang="en">{{ item.static.job_id }}</span> {{ t("· original collection") }} <span lang="en">{{ item.static.observed_at }}</span> · <span lang="en">{{ item.static.method }}</span> / <span lang="en">{{ item.static.parser_method }}</span> {{ t("· matching parsed target count") }} <span lang="en">{{ item.static.matching_target_count }}</span> · <span lang="en">{{ item.static.state }}</span>.</p>
        <p>{{ t("Static body SHA-256") }} <span lang="en">{{ item.static.body_sha256 }}</span> · <span lang="en">{{ item.static.body_size_bytes }}</span> {{ t("bytes · step") }} <span lang="en">{{ item.static.step_id }}</span> {{ t("· private artifact") }} <span lang="en">{{ item.static.artifact_id }}</span>.</p>
        <pre><span lang="en">{{ json(item.static.coverage) }}</span></pre><p>{{ t("Original source redirects:") }} <span lang="en">{{ json(item.static.redirects) }}</span></p>
        <h3>{{ t("Separate original own-target HTTP observation") }}</h3>
        <p>{{ t("HTTP status") }} <span [attr.lang]="item.target['status_code'] === null || item.target['status_code'] === undefined ? uiLanguage() : 'en'">{{ item.target['status_code'] ?? t("unavailable") }}</span> {{ t("· original observation") }} <span lang="en">{{ item.target['observed_at'] }}</span> {{ t("· crawl completed") }} <span lang="en">{{ item.target['completed_at'] }}</span> ·
          <span lang="en">{{ item.target['method'] }}</span> · <span lang="en">{{ item.target['state'] }}</span>{{ t(". This is dated evidence, not the current site state.") }}</p>
        <details><summary>{{ t("Original target scope, private readback, redirects and crawl coverage") }}</summary><pre><span lang="en">{{ json(item.target) }}</span></pre></details>
        @if (!item.static_coverage_complete) { <p role="status">{{ t("Incomparable ambiguous or truncated static coverage; no supported destination-recovery conclusion.") }}</p> }
        @else if (item.destination_recovery_candidate) { <p role="status">{{ t("Dated destination-recovery candidate: parsed exact-target markup and a separate original 404/410. Review whether restoring a useful destination is appropriate.") }}</p> }
        @else { <p role="status"><span lang="en">{{ item.state }}</span>{{ t(". No supported dated missing-destination candidate; this does not prove a healthy current site or a recovered link.") }}</p> }
        <p>{{ t("No current broken inbound link, browser visibility, verified unlinked/lost link or causal outcome is established. This read reserves no units, creates no action and approves no outreach or site change.") }}</p>
        <a [routerLink]="['/app/actions', organizationId, projectId]">{{ t("Separately select and approve an existing genuine own-page action; inspect implementation and technical follow-up") }}</a>
      }
      @if (mention(); as item) {
        <h2>{{ t("Human mention and separately dated static target evidence") }}</h2>
        <p>{{ t("Requested source") }} <span lang="">{{ item.requested_source_url }}</span> {{ t("· final source") }} <span lang="">{{ item.final_source_url }}</span> {{ t("→ exact target") }} <span lang="">{{ item.target_url }}</span>.</p>
        <h3>{{ t("Original human-selected quote") }}</h3><blockquote><span lang="">{{ item.selection.quote }}</span></blockquote>
        <p>{{ t("Human relevance:") }} <span lang="">{{ item.selection.relevance }}</span> {{ t("· assignee") }} <span lang="en">{{ item.selection.assignee_id }}</span> {{ t("· review") }} <span lang="en">{{ item.selection.review_id }}</span>
          {{ t("revision") }} <span lang="en">{{ item.selection.revision }}</span> · <span lang="en">{{ item.selection.state }}</span>{{ t(". This normalized bounded-text selection is not automatic brand or browser verification.") }}</p>
        <p>{{ t("Research retrieval") }} <span lang="en">{{ item.selection.retrieved_at }}</span> · <span lang="en">{{ item.research['method'] }}</span> / <span lang="en">{{ item.research['collection_method'] }}</span> {{ t("· job") }} <span lang="en">{{ item.selection.research_job_id }}</span> {{ t("· source index") }} <span lang="en">{{ item.selection.source_index }}</span> {{ t("· step") }} <span lang="en">{{ item.research['step_id'] }}</span> {{ t("· private artifact") }} <span lang="en">{{ item.research['artifact_id'] }}</span>.</p>
        <p>{{ t("Research coverage") }} <span lang="en">{{ item.research['coverage'] }}</span> · {{ item.research['excerpt_truncated'] ? t("Truncated excerpt") : t("Bounded excerpt") }}{{ t("; unrelated excerpt is excluded.") }}</p>
        <h3>{{ t("Separate original static observation") }}</h3>
        <p>{{ t("Job") }} <span lang="en">{{ item.static.job_id }}</span> {{ t("· collection time") }} <span lang="en">{{ item.static.observed_at }}</span> · <span lang="en">{{ item.static.method }}</span> / <span lang="en">{{ item.static.parser_method }}</span> {{ t("· step") }} <span lang="en">{{ item.static.step_id }}</span> {{ t("· private artifact") }} <span lang="en">{{ item.static.artifact_id }}</span> {{ t("· matching parsed target count") }} <span lang="en">{{ item.static.matching_target_count }}</span> · <span lang="en">{{ item.static.state }}</span>.</p>
        <p>{{ t("Both original bodies: SHA-256") }} <span lang="en">{{ item.selection.body_sha256 }}</span> · <span lang="en">{{ item.selection.body_size_bytes }}</span> {{ t("bytes. Byte-equivalent separately returned documents do not verify a browser-visible mention.") }}</p>
        <pre><span lang="en">{{ json(item.static.coverage) }}</span></pre>
        @if (!item.static_coverage_complete) { <p role="status">{{ t("Incomparable ambiguous or truncated static coverage; no verified absence.") }}</p> }
        @else { <p role="status"><span lang="en">{{ item.state }}</span>{{ t(". Bounded candidate only, never independently verified unlinked or lost links.") }}</p> }
        <p>{{ t("Browser visibility, whole-site/index coverage and causal outcomes are not established. Original human mention approval, outreach permission and own-site implementation approval remain separate human workflows.") }}</p>
      }
      @if (comparison(); as pair) {
        <h2>{{ t("Dated selected-source comparison") }}</h2>
        <p>{{ t("Exact collection method") }} <span lang="en">{{ pair.collection_method }}</span> / <span lang="en">{{ pair.parser_method }}</span>.</p>
        <p>{{ t("Requested source") }} <span lang="">{{ pair.requested_source_url }}</span> {{ t("· final source") }} <span lang="">{{ pair.final_source_url }}</span> {{ t("→ exact target") }} <span lang="">{{ pair.target_url }}</span>.</p>
        @if (!pair.comparable) { <p role="status">{{ t("Incomparable ambiguous or truncated coverage. Counts describe bounded parsed markup, not verified absence or link loss.") }}</p> }
        @else { <p role="status"><span lang="en">{{ pair.state }}</span>{{ t(". This is a bounded static-document candidate, never independently verified link loss.") }}</p> }
        <p>{{ t("Original body digest") }} {{ pair.body_changed ? t("changed") : t("unchanged") }}{{ t("; this does not establish a causal outcome.") }}</p>
        @for (observation of [pair.previous, pair.current]; track observation.job_id) {
          <h3>{{ observation.job_id === pair.previous.job_id ? t("Previous") : t("Current") }} {{ t("job") }} <span lang="en">{{ observation.job_id }}</span></h3>
          <p>{{ t("Original collection time") }} <span lang="en">{{ observation.observed_at }}</span> {{ t("· matching parsed target count") }} <span lang="en">{{ observation.matching_target_count }}</span> · <span lang="en">{{ observation.state }}</span>.</p>
          <p>{{ t("Body SHA-256") }} <span lang="en">{{ observation.body_sha256 }}</span> · <span lang="en">{{ observation.body_size_bytes }}</span> {{ t("bytes · step") }} <span lang="en">{{ observation.step_id }}</span> {{ t("· private artifact") }} <span lang="en">{{ observation.artifact_id }}</span>.</p>
          <pre><span lang="en">{{ json(observation.coverage) }}</span></pre>
        }
        <p>{{ t("Browser visibility, whole-site/index coverage and independently verified unlinked/lost links are not established. Original human report, outreach decision and own-site implementation approval remain separate.") }}</p>
      }
      @if (selected(); as job) {
        <h2>{{ t("Exact job") }} <span lang="en">{{ job.id }}</span> · <span lang="en">{{ job.status }}</span></h2>
        <p>{{ t("Updated") }} <span lang="en">{{ job.updated_at }}</span> · <span lang="en">{{ job.evidence_state }}</span> · <span lang="en">{{ job.error_category }}</span>{{ t(". Completed/unknown attempts are never automatically replayed. This collection does not approve outreach or a website change.") }}</p>
        @if (job.evidence; as evidence) {
          <h3>{{ t("Independently collected static markup, not a browser-visible link") }}</h3>
          <pre><span lang="en">{{ json(evidence.collection) }}</span></pre>
          <p>{{ t("Parsed anchor text and rel are literal untrusted text. Missing or ambiguous markup is not independently verified link loss. Original human report and dated own-target HTTP/site-action approval remain separate.") }}</p>
        } @else { <p>{{ t("No current private source observation available. Failed, stale, denied and unknown are not zero links.") }}</p> }
      }
    </section>`,
  styles: `form, fieldset { display: grid; gap: .6rem; } form { max-width: 48rem; margin-block: 1rem; }
    pre { white-space: pre-wrap; overflow-wrap: anywhere; } li { margin-block: 1rem; } select { max-width: 100%; min-width: 0; }`,
})
export class AuthorityLinkSources implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  t(text: string) { return this.uiLanguage() === 'tr' ? authorityLinkSourcesTurkish[text] ?? text : text; }
  readonly context = signal<Context | null>(null); readonly selected = signal<Job | null>(null);
  readonly chosen = signal<Candidate | null>(null); readonly pending = signal<Pending | null>(null);
  readonly busy = signal(false); readonly loading = signal(false); readonly notFound = signal(false);
  readonly error = signal(''); readonly message = signal('');
  readonly previousId = signal(0); readonly currentId = signal(0); readonly comparison = signal<Comparison | null>(null);
  readonly mentions = signal<MentionSelection[]>([]); readonly mentionsHasMore = signal(false);
  readonly mentionId = signal(0); readonly mentionJobId = signal(0); readonly mention = signal<Mention | null>(null);
  readonly destination = signal<Destination | null>(null);
  protected organizationId = 0; protected projectId = 0; protected readonly safeUrl = safeUrl;
  private generation = 0;
  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi, private readonly destroyRef: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t('Private selected static-link verification')} — OrganicSEOOps`));
    destroyRef.onDestroy(() => { this.generation++; this.clear(); });
  }
  ngOnInit() {
    void this.loadProductLanguage();
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      this.generation++; this.clear(); this.busy.set(false); this.loading.set(false); this.message.set(''); this.error.set('');
      this.organizationId = Number(params.get('organizationId')); this.projectId = Number(params.get('projectId'));
      if (positive(this.organizationId) && positive(this.projectId)) void this.load();
      else this.error.set('Select an authorized organization and project.');
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
  json(value: unknown) { return JSON.stringify(value, null, 2); }
  private clear() { this.context.set(null); this.selected.set(null); this.chosen.set(null); this.pending.set(null); this.notFound.set(false);
    this.previousId.set(0); this.currentId.set(0); this.comparison.set(null);
    this.mentions.set([]); this.mentionsHasMore.set(false); this.mentionId.set(0); this.mentionJobId.set(0); this.mention.set(null); this.destination.set(null); }
  private binding(value: unknown): value is Binding {
    if (!object(value)) return false;
    const rights = value['rights'];
    return value['method'] === 'authority-static-source-authority-v1' && value['project_id'] === this.projectId
      && value['organization_id'] === this.organizationId && positive(value['link_review_id'])
      && ['actor_id', 'source_actor_id', 'reviewer_id', 'approved_by_id', 'assignee_id', 'link_revision'].every((key) => positive(value[key]))
      && typeof value['link_state'] === 'string' && ['approved', 'reported'].includes(value['link_state']) && !!safeUrl(value['source_url']) && !!safeUrl(value['target_url'])
      && new URL(String(value['source_url'])).origin === value['source_origin']
      && new URL(String(value['source_url'])).hostname !== new URL(String(value['target_url'])).hostname
      && isTarget(value['target_evidence'], this.projectId) && value['target_evidence'].requested_url === value['target_url']
      && value['target_evidence'].configuration_revision === value['configuration_revision']
      && object(rights) && ['use_permission', 'storage_permission', 'not_restricted_provider_copy', 'no_personal_payload']
        .every((key) => rights[key] === true);
  }
  private job(value: unknown): value is Job {
    if (!object(value)) return false;
    const row = value as unknown as Job;
    if (!(positive(row.id) && row.project_id === this.projectId && positive(row.link_review_id)
      && typeof row.idempotency_key === 'string' && /^[A-Za-z0-9][A-Za-z0-9._-]{7,63}$/.test(row.idempotency_key)
      && ['queued', 'running', 'succeeded', 'failed', 'cancelled'].includes(row.status) && aware(row.created_at) && aware(row.updated_at)
      && typeof row.source_current === 'boolean' && typeof row.cancel_requested === 'boolean' && typeof row.error_category === 'string'
      && row.estimate_units === 1 && [0, 1].includes(row.attempted_units) && object(row.selection)
      && !!parserMethod(row.selection.method) && row.selection.parser_method === parserMethod(row.selection.method) && this.binding(row.selection.binding)
      && row.selection.binding.link_review_id === row.link_review_id && row.selection.binding['source_collection_permission'] === true)) return false;
    if (row.evidence === null) return ['not_collected', 'retained_current_use_unavailable'].includes(row.evidence_state);
    if (!object(row.evidence) || row.evidence.source_current !== true || !row.source_current || row.status !== 'succeeded'
      || row.evidence_state !== 'current_private_readback_checked' || !object(row.evidence.collection)) return false;
    const source = row.evidence.collection;
    if (source['method'] !== row.selection.method || source['state'] !== 'collected' || source['requested_url'] !== row.selection.binding.source_url
      || !safeUrl(source['url']) || new URL(String(source['url'])).origin !== row.selection.binding.source_origin || !aware(source['observed_at'])
      || !object(source['evidence'])) return false;
    const evidence = source['evidence']; const coverage = evidence['coverage']; const links = evidence['matching_links'];
    const uri = row.selection.parser_method === URI_PARSER;
    return evidence['method'] === row.selection.parser_method && evidence['source_url'] === source['url'] && evidence['target_url'] === row.selection.binding.target_url
      && evidence['observed_at'] === source['observed_at'] && typeof evidence['body_sha256'] === 'string' && /^[a-f0-9]{64}$/.test(evidence['body_sha256'])
      && positive(evidence['body_size_bytes']) && Number(evidence['body_size_bytes']) <= 131072
      && evidence['unlinked_or_lost_link'] === 'not_established' && evidence['raw_body_retention'] === 'not_selected_transient_only'
      && typeof evidence['state'] === 'string'
      && [uri ? 'observed_resolved_target_in_static_uri_references' : 'observed_absolute_target_in_parsed_html',
        'not_observed_in_bounded_static_html_not_link_loss', 'unavailable_ambiguous_markup', ...(uri ? ['unavailable_base_dependent_references'] : [])].includes(evidence['state'])
      && object(coverage) && coverage['surface'] === 'returned_static_html_not_rendered' && coverage['browser_visibility'] === 'unknown'
      && Number.isSafeInteger(coverage['anchors_inspected']) && Number(coverage['anchors_inspected']) <= 1000
      && Array.isArray(links) && links.length <= 20
      && (!uri || evidence['href_semantics'] === 'bounded_stdlib_uri_reference_join_against_final_source_no_base_no_browser_repair'
        && this.observation({ ...row.evidence, ...evidence, matching_target_count: links.length }, row.id, false, URI_PARSER))
      && links.every((link) => object(link) && link['parsed_href'] === row.selection.binding.target_url
        && typeof link['anchor_text'] === 'string' && link['anchor_text'].length <= 240 && typeof link['rel'] === 'string' && link['rel'].length <= 100
        && typeof link['anchor_text_truncated'] === 'boolean' && typeof link['rel_truncated'] === 'boolean');
  }
  private readContext(response: ApiResult): Context {
    const info = response.body as unknown as Context;
    if (response.status !== 200 || info.organization_id !== this.organizationId || info.project_id !== this.projectId
      || typeof info.can_collect !== 'boolean' || typeof info.can_cancel !== 'boolean' || typeof info.denial_category !== 'string'
      || !same(info.collection_methods, [COLLECTION, URI_COLLECTION])
      || !Array.isArray(info.candidates) || info.candidates.length > 20 || !info.candidates.every((row) => object(row)
        && row.requires_separate_collection_permission === true && this.binding(row.binding)
        && row.link_review_id === row.binding.link_review_id && !Object.hasOwn(row.binding, 'source_collection_permission'))
      || !Array.isArray(info.jobs) || info.jobs.length > 20 || !info.jobs.every((row) => this.job(row))
      || typeof info.has_more !== 'boolean' || typeof info.candidates_has_more !== 'boolean') throw new Error();
    return info;
  }
  private readJob(response: ApiResult, id?: number): Job {
    const row = response.body['job'];
    if (![200, 202].includes(response.status) || response.body['organization_id'] !== this.organizationId
      || response.body['project_id'] !== this.projectId || !this.job(row) || id !== undefined && row.id !== id) throw new Error();
    return row;
  }
  private readComparison(response: ApiResult, previous: Job, current: Job): Comparison {
    const pair = response.body['comparison'];
    if (response.status !== 200 || response.body['organization_id'] !== this.organizationId || response.body['project_id'] !== this.projectId
      || !object(pair) || pair['method'] !== 'authority-static-link-comparison-v1' || pair['project_id'] !== this.projectId
      || pair['collection_method'] !== previous.selection.method || pair['parser_method'] !== previous.selection.parser_method
      || !same(previous.selection.method, current.selection.method) || !same(previous.selection.parser_method, current.selection.parser_method)
      || pair['source_current'] !== true || pair['requested_source_url'] !== previous.selection.binding.source_url
      || pair['target_url'] !== previous.selection.binding.target_url || !safeUrl(pair['final_source_url'])
      || new URL(String(pair['final_source_url'])).origin !== previous.selection.binding.source_origin
      || pair['unlinked_or_lost_link'] !== 'not_established' || pair['site_approval'] !== 'separate_human_workflow'
      || pair['interpretation'] !== 'dated_selected_static_document_candidate_not_browser_or_whole_site_or_verified_link_loss_or_causal_proof'
      || typeof pair['comparable'] !== 'boolean' || typeof pair['body_changed'] !== 'boolean') throw new Error();
    if (!this.observation(pair['previous'], previous.id, pair['comparable'], previous.selection.parser_method)
      || !this.observation(pair['current'], current.id, pair['comparable'], current.selection.parser_method)) throw new Error();
    const before = pair['previous']; const after = pair['current'];
    const state = !pair['comparable'] ? 'incomparable_ambiguous_or_truncated_coverage' : before.matching_target_count > 0
      ? after.matching_target_count > 0 ? 'target_markup_observed_again' : 'target_markup_not_observed_again_candidate_not_verified_link_loss'
      : after.matching_target_count > 0 ? 'target_markup_now_observed' : 'target_markup_not_observed_in_either_bounded_document_not_unlinked_proof';
    if (Date.parse(before.observed_at) >= Date.parse(after.observed_at) || pair['state'] !== state
      || pair['body_changed'] !== (before.body_sha256 !== after.body_sha256)) throw new Error();
    return pair as unknown as Comparison;
  }
  private observation(value: unknown, id: number, complete: boolean, parser: string): value is Observation {
      if (!object(value) || value['job_id'] !== id || !positive(value['step_id']) || !positive(value['artifact_id']) || !aware(value['observed_at'])
        || typeof value['body_sha256'] !== 'string' || !/^[a-f0-9]{64}$/.test(value['body_sha256'])
        || !positive(value['body_size_bytes']) || Number(value['body_size_bytes']) > 131072
        || !Number.isSafeInteger(value['matching_target_count']) || Number(value['matching_target_count']) < 0 || Number(value['matching_target_count']) > 20
        || !object(value['coverage'])) return false;
      const coverage = value['coverage'];
      const uri = parser === URI_PARSER;
      if (![PARSER, URI_PARSER].includes(parser) || uri && (!Number.isSafeInteger(coverage['unsupported_references'])
        || Number(coverage['unsupported_references']) < 0 || Number(coverage['unsupported_references']) > Number(coverage['anchors_inspected'])
        || coverage['reference_resolution'] !== (coverage['base_element_seen'] ? 'unavailable_base_element' : 'bounded_no_base_stdlib_uri_references')
        || coverage['base_element_seen'] && (!coverage['structure_uncertain'] || value['matching_target_count'] !== 0)
        || complete && Number(coverage['unsupported_references']) > 0)) return false;
      return coverage['surface'] === 'returned_static_html_not_rendered' && coverage['whole_site'] === 'not_established'
        && coverage['browser_visibility'] === 'unknown'
        && ['anchor_limit_reached', 'matches_capped', 'structure_uncertain', 'base_element_seen'].every((key) => typeof coverage[key] === 'boolean')
        && ['anchors_seen', 'anchors_inspected', 'matches_seen'].every((key) => Number.isSafeInteger(coverage[key]) && Number(coverage[key]) >= 0 && Number(coverage[key]) <= 131072)
        && coverage['anchors_inspected'] === Math.min(Number(coverage['anchors_seen']), 1000)
        && coverage['anchor_limit_reached'] === (Number(coverage['anchors_seen']) > 1000)
        && coverage['matches_capped'] === (Number(coverage['matches_seen']) > 20)
        && Number(value['matching_target_count']) <= Number(coverage['matches_seen']) && Number(coverage['matches_seen']) <= Number(coverage['anchors_inspected'])
        && value['state'] === (uri && coverage['base_element_seen'] ? 'unavailable_base_dependent_references'
          : coverage['structure_uncertain'] ? 'unavailable_ambiguous_markup' : Number(value['matching_target_count']) > 0
          ? uri ? 'observed_resolved_target_in_static_uri_references' : 'observed_absolute_target_in_parsed_html'
          : 'not_observed_in_bounded_static_html_not_link_loss')
        && (!complete || !coverage['structure_uncertain'] && !coverage['anchor_limit_reached'] && !coverage['matches_capped']);
  }
  private mentionSelection(value: unknown): value is MentionSelection {
    if (!object(value)) return false;
    return value['project_id'] === this.projectId && value['source_current'] === true && value['mention_basis'] === MENTION_BASIS
      && ['review_id', 'revision', 'assignee_id', 'source_actor_id', 'reviewer_id', 'approved_by_id', 'research_job_id'].every((key) => positive(value[key]))
      && typeof value['prospect_id'] === 'string' && /^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/.test(value['prospect_id'])
      && typeof value['state'] === 'string' && ['approved', 'reported'].includes(value['state'])
      && ([['quote', 1000], ['relevance', 500]] as const).every(([key, limit]) => typeof value[key] === 'string'
        && (value[key] as string).trim().length > 0 && (value[key] as string).length <= Number(limit))
      && !!safeUrl(value['requested_source_url']) && !!safeUrl(value['final_source_url'])
      && new URL(String(value['requested_source_url'])).origin === new URL(String(value['final_source_url'])).origin
      && Number.isSafeInteger(value['source_index']) && Number(value['source_index']) >= 0 && Number(value['source_index']) < 5
      && aware(value['retrieved_at']) && Date.parse(String(value['retrieved_at'])) <= Date.now()
      && typeof value['body_sha256'] === 'string' && /^[a-f0-9]{64}$/.test(value['body_sha256'])
      && positive(value['body_size_bytes']) && Number(value['body_size_bytes']) <= 131072;
  }
  private readDestination(response: ApiResult, job: Job): Destination {
    const item = response.body['candidate']; const binding = job.selection.binding;
    if (response.status !== 200 || response.body['organization_id'] !== this.organizationId || response.body['project_id'] !== this.projectId
      || !object(item) || item['method'] !== 'authority-static-destination-candidate-v1' || item['project_id'] !== this.projectId
      || item['source_current'] !== true || !same(item['selection'], job.selection)
      || item['requested_source_url'] !== binding.source_url || item['target_url'] !== binding.target_url
      || !safeUrl(item['final_source_url']) || new URL(String(item['final_source_url'])).origin !== binding.source_origin
      || !isTarget(item['target'], this.projectId) || !same(item['target'], binding.target_evidence)
      || typeof item['static_coverage_complete'] !== 'boolean' || typeof item['destination_recovery_candidate'] !== 'boolean'
      || !this.observation(item['static'], job.id, item['static_coverage_complete'], job.selection.parser_method)
      || item['unlinked_or_lost_link'] !== 'not_established' || item['site_or_outreach_approval'] !== 'separate_human_workflows'
      || item['handoff'] !== 'separate_existing_own_page_action_review_required_no_automatic_action_or_approval'
      || item['interpretation'] !== 'separately_dated_static_target_and_own_http_candidate_not_current_broken_inbound_browser_or_causal_proof') throw new Error();
    const source = item['static']; const target = item['target'];
    const redirects = source['redirects'];
    const candidate = item['static_coverage_complete'] && source.matching_target_count > 0 && !target.error_category && [404, 410].includes(target.status_code!);
    if (source['method'] !== job.selection.method || source['parser_method'] !== job.selection.parser_method
      || Date.parse(source.observed_at) < Math.max(Date.parse(target.observed_at), Date.parse(target.completed_at)) || Date.parse(source.observed_at) > Date.now()
      || !Array.isArray(redirects) || redirects.length > 2 || !redirects.every((hop) => object(hop) && !!safeUrl(hop['url'])
        && new URL(String(hop['url'])).origin === binding.source_origin && [301, 302, 303, 307, 308].includes(Number(hop['status'])))
      || item['destination_recovery_candidate'] !== candidate || item['state'] !== (!item['static_coverage_complete']
        ? 'incomparable_ambiguous_or_truncated_static_coverage' : candidate ? 'dated_static_target_and_http_missing_destination_candidate'
        : !source.matching_target_count ? 'target_not_observed_in_bounded_static_document_not_missing_or_healthy_proof'
        : 'no_dated_missing_destination_candidate_not_current_healthy_or_recovered_link_proof')) throw new Error();
    return item as unknown as Destination;
  }
  async inspectDestination(job: Job) {
    if (this.busy() || this.loading() || this.pending() || !this.context()?.can_collect || job.status !== 'succeeded' || !job.source_current) return;
    const frozen = structuredClone(job); const generation = ++this.generation;
    this.destination.set(null); this.mention.set(null); this.comparison.set(null); this.selected.set(null); this.busy.set(true); this.error.set('');
    try {
      const fresh = await this.api.authorityLinkSources(this.organizationId, this.projectId);
      if (generation !== this.generation) return;
      const info = this.readContext(fresh);
      if (!info.can_collect || !info.jobs.some((row) => row.id === frozen.id && row.status === 'succeeded' && row.source_current
        && same(row.selection, frozen.selection))) throw new Error();
      this.context.set(info);
      const result = await this.api.authorityDestinationCandidate(this.organizationId, this.projectId, frozen.id);
      if (generation === this.generation) this.destination.set(this.readDestination(result, frozen));
    } catch { if (generation === this.generation) { this.clear(); this.error.set('Exact dated destination/current authority unavailable. Refresh history; unavailable is not zero or current broken/healthy link proof.'); } }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  private readMentions(response: ApiResult): MentionSelection[] {
    const rows = response.body['candidates'];
    if (response.status !== 200 || response.body['organization_id'] !== this.organizationId || response.body['project_id'] !== this.projectId
      || response.body['basis'] !== 'human_selected_mentions_require_exact_body_matched_static_observation_not_verified_unlinked_proof'
      || typeof response.body['has_more'] !== 'boolean' || !Array.isArray(rows) || rows.length > 20
      || !rows.every((row) => this.mentionSelection(row)) || new Set(rows.map((row) => row.review_id)).size !== rows.length) throw new Error();
    return rows;
  }
  private readMentionCandidate(response: ApiResult, selection: MentionSelection, job: Job): Mention {
    const item = response.body['candidate'];
    if (response.status !== 200 || response.body['organization_id'] !== this.organizationId || response.body['project_id'] !== this.projectId
      || !object(item) || item['method'] !== 'authority-body-matched-mention-v1' || item['project_id'] !== this.projectId
      || item['source_current'] !== true || !same(item['selection'], selection)
      || item['requested_source_url'] !== selection.requested_source_url || item['requested_source_url'] !== job.selection.binding.source_url
      || item['final_source_url'] !== selection.final_source_url || item['target_url'] !== job.selection.binding.target_url
      || item['body_match'] !== 'same_original_response_sha256_and_size_separate_dated_observations'
      || item['unlinked_or_lost_link'] !== 'not_established' || item['site_or_outreach_approval'] !== 'separate_human_workflows'
      || item['interpretation'] !== 'human_mention_body_matched_static_target_candidate_not_browser_whole_site_index_or_verified_unlinked_or_lost_proof'
      || typeof item['static_coverage_complete'] !== 'boolean' || !object(item['prospect']) || !object(item['research'])
      || !this.observation(item['static'], job.id, item['static_coverage_complete'], job.selection.parser_method)) throw new Error();
    if (!same(item['prospect'], Object.fromEntries(['review_id', 'prospect_id', 'revision', 'state', 'quote', 'relevance', 'assignee_id', 'mention_basis']
      .map((key) => [key, selection[key as keyof MentionSelection]])))) throw new Error();
    const research = item['research']; const source = item['static'];
    if (research['method'] !== 'authority-research-evidence-v1' || research['collection_method'] !== 'research-v1'
      || research['research_job_id'] !== selection.research_job_id || research['source_index'] !== selection.source_index
      || !positive(research['step_id']) || !positive(research['artifact_id']) || research['retrieved_at'] !== selection.retrieved_at
      || research['original_response_sha256'] !== selection.body_sha256 || research['source_size_bytes'] !== selection.body_size_bytes
      || typeof research['excerpt_truncated'] !== 'boolean' || research['coverage'] !== 'selected_bounded_public_page_text_only'
      || source['link_review_id'] !== job.link_review_id || source['method'] !== job.selection.method || source['parser_method'] !== job.selection.parser_method
      || source.body_sha256 !== selection.body_sha256 || source.body_size_bytes !== selection.body_size_bytes
      || Date.parse(source.observed_at) < Date.parse(selection.retrieved_at) || Date.parse(source.observed_at) > Date.now()
      || item['state'] !== (!item['static_coverage_complete'] ? 'incomparable_ambiguous_or_truncated_static_coverage'
        : source.matching_target_count ? 'human_mention_with_observed_exact_target_markup' : 'human_mention_target_not_observed_candidate_not_verified_unlinked')) throw new Error();
    return item as unknown as Mention;
  }
  chooseMention(event: Event, human: boolean) {
    if (this.busy() || this.loading()) return;
    (human ? this.mentionId : this.mentionJobId).set(Number((event.target as HTMLSelectElement).value));
    this.mention.set(null); this.error.set('');
  }
  async readMention(event: Event) {
    event.preventDefault();
    if (this.busy() || this.loading() || this.pending() || !this.context()?.can_collect) return;
    const selected = this.mentions().find((row) => row.review_id === this.mentionId());
    const job = this.context()!.jobs.find((row) => row.id === this.mentionJobId());
    if (!selected || !job || job.status !== 'succeeded' || !job.source_current) return;
    const frozen = structuredClone({ selected, job }); const generation = ++this.generation;
    this.destination.set(null); this.mention.set(null); this.comparison.set(null); this.selected.set(null); this.busy.set(true); this.error.set('');
    try {
      const fresh = await this.api.authorityLinkSources(this.organizationId, this.projectId);
      if (generation !== this.generation) return;
      const info = this.readContext(fresh);
      if (!info.can_collect || !info.jobs.some((row) => row.id === job.id && row.status === 'succeeded'
        && row.source_current && same(row.selection, frozen.job.selection))) throw new Error();
      const list = await this.api.authorityMentionCandidates(this.organizationId, this.projectId);
      if (generation !== this.generation) return;
      const rows = this.readMentions(list);
      if (!rows.some((row) => same(row, frozen.selected)) || frozen.selected.requested_source_url !== frozen.job.selection.binding.source_url) throw new Error();
      this.context.set(info); this.mentions.set(rows); this.mentionsHasMore.set(list.body['has_more'] as boolean);
      const result = await this.api.authorityMentionCandidates(this.organizationId, this.projectId, frozen.selected.review_id, frozen.job.id);
      if (generation !== this.generation) return;
      if (this.mentionId() !== frozen.selected.review_id || this.mentionJobId() !== frozen.job.id) throw new Error();
      this.mention.set(this.readMentionCandidate(result, frozen.selected, frozen.job));
    } catch { if (generation === this.generation) { this.clear(); this.error.set('Exact body-matched mention/current authority unavailable. Refresh and deliberately select again; unavailable is not zero or verified unlinked proof.'); } }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  choosePair(event: Event, previous: boolean) {
    if (this.busy()) return;
    (previous ? this.previousId : this.currentId).set(Number((event.target as HTMLSelectElement).value));
    this.comparison.set(null); this.error.set('');
  }
  async compare(event: Event) {
    event.preventDefault();
    if (this.busy() || this.loading() || this.pending() || !this.context()?.can_collect) return;
    const rows = this.context()!.jobs;
    const previous = rows.find((row) => row.id === this.previousId()); const current = rows.find((row) => row.id === this.currentId());
    if (!previous || !current || previous.id === current.id || [previous, current].some((row) => row.status !== 'succeeded' || !row.source_current)) return;
    const frozen = structuredClone([previous, current]);
    const generation = ++this.generation; this.destination.set(null); this.mention.set(null); this.comparison.set(null); this.selected.set(null); this.busy.set(true); this.error.set('');
    try {
      const fresh = await this.api.authorityLinkSources(this.organizationId, this.projectId);
      if (generation !== this.generation) return;
      const info = this.readContext(fresh);
      if (!info.can_collect || !frozen.every((job) => info.jobs.some((row) => row.id === job.id && row.status === 'succeeded'
        && row.source_current && same(row.selection, job.selection)))) throw new Error();
      const bindings = frozen.map((job) => { const binding = { ...job.selection.binding }; delete binding['actor_id']; return binding; });
      if (!same(bindings[0], bindings[1]) || frozen[0].selection.method !== frozen[1].selection.method
        || frozen[0].selection.parser_method !== frozen[1].selection.parser_method) throw new Error();
      this.context.set(info);
      const result = await this.api.authorityLinkComparison(this.organizationId, this.projectId, previous.id, current.id);
      if (generation !== this.generation) return;
      if (this.previousId() !== previous.id || this.currentId() !== current.id) throw new Error();
      this.comparison.set(this.readComparison(result, frozen[0], frozen[1]));
    } catch { if (generation === this.generation) { this.clear(); this.error.set('Exact dated pair/current authority unavailable. Refresh history; unavailable is not zero or verified link loss.'); } }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  async load() {
    if (this.busy() || this.pending()) return;
    const generation = ++this.generation; this.clear(); this.loading.set(true); this.error.set('');
    try { const result = await this.api.authorityLinkSources(this.organizationId, this.projectId);
      if (generation !== this.generation) return;
      const info = this.readContext(result);
      if (info.can_collect) {
        const list = await this.api.authorityMentionCandidates(this.organizationId, this.projectId);
        if (generation !== this.generation) return;
        this.mentions.set(this.readMentions(list)); this.mentionsHasMore.set(list.body['has_more'] as boolean);
      }
      this.context.set(info);
    } catch { if (generation === this.generation) { this.clear(); this.error.set('Private source history or current authority is unavailable.'); } }
    finally { if (generation === this.generation) this.loading.set(false); }
  }
  choose(event: Event) { this.chosen.set(this.context()?.candidates.find((row) => String(row.link_review_id) === (event.target as HTMLSelectElement).value) || null); }
  launch(event: Event) {
    event.preventDefault(); const form = event.target as HTMLFormElement; const candidate = this.chosen();
    if (this.busy() || this.pending() || !this.context()?.can_collect || !candidate || !form.reportValidity()
      || !new FormData(form).has('permission')) return;
    const key = crypto.randomUUID();
    const method = new FormData(form).get('method');
    if (typeof method !== 'string' || !parserMethod(method) || !this.context()!.collection_methods.includes(method)) return;
    void this.send(structuredClone({ key, binding: candidate.binding, method,
      data: { idempotency_key: key, link_review_id: candidate.link_review_id, source_collection_permission: true, collection_method: method } }));
  }
  async inspect(id: number) {
    if (this.busy() || this.pending()) return;
    const generation = ++this.generation; this.destination.set(null); this.mention.set(null); this.selected.set(null); this.comparison.set(null); this.busy.set(true);
    try { const result = await this.api.authorityLinkSources(this.organizationId, this.projectId, undefined, id);
      if (generation === this.generation) this.selected.set(this.readJob(result, id));
    } catch { if (generation === this.generation) { this.clear(); this.error.set('Exact current source readback unavailable; refresh authority.'); } }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  cancel(job: Job) {
    if (this.busy() || this.pending() || !this.context()?.can_cancel || !['queued', 'running'].includes(job.status)) return;
    const binding = structuredClone(job.selection.binding); delete binding['source_collection_permission'];
    void this.send({ key: job.idempotency_key, binding, method: job.selection.method, jobId: job.id, data: {} });
  }
  private matches(job: Job, pending: Pending) {
    const binding = { ...job.selection.binding }; delete binding['source_collection_permission'];
    return job.idempotency_key === pending.key && job.link_review_id === pending.binding.link_review_id && same(binding, pending.binding)
      && job.selection.method === pending.method && job.selection.parser_method === parserMethod(pending.method)
      && (pending.jobId === undefined || job.id === pending.jobId);
  }
  private async send(command: Pending) {
    const generation = this.generation; this.destination.set(null); this.mention.set(null); this.comparison.set(null); this.selected.set(null); this.pending.set(command); this.busy.set(true); this.notFound.set(false); this.error.set(''); this.message.set('');
    let attempted = false;
    try {
      if (command.jobId === undefined) {
        const response = await this.api.authorityLinkSources(this.organizationId, this.projectId);
        if (generation !== this.generation) return;
        const info = this.readContext(response);
        if (!info.can_collect || !info.collection_methods.includes(command.method)
          || !info.candidates.some((row) => same(row.binding, command.binding))) throw new Error();
        this.context.set(info);
      }
      attempted = true;
      const result = await this.api.authorityLinkSources(this.organizationId, this.projectId, command.data, command.jobId);
      if (generation !== this.generation) return;
      if ([400, 401, 403, 404, 409, 413, 429].includes(result.status)) { this.clear(); this.error.set('Command denied; refresh current authority before another decision.'); return; }
      const job = this.readJob(result, command.jobId);
      if (!this.matches(job, command) || command.jobId !== undefined && !(job.cancel_requested || job.status === 'cancelled')) throw new Error();
      this.pending.set(null); this.busy.set(false); await this.load();
      if (generation + 1 === this.generation) this.message.set('Exact command recorded. Refresh to check progress; no outreach or website change authorized.');
    } catch { if (generation === this.generation) {
      if (!attempted) { this.clear(); this.error.set('Current exact source, method or authority changed. No collection command sent; refresh before another decision.'); }
      else this.message.set('Command outcome uncertain. Check the exact request before continuing; no automatic replay.');
    } }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  async reconcile() {
    const command = this.pending(); if (!command || this.busy()) return;
    const generation = this.generation; this.busy.set(true); this.notFound.set(false);
    try {
      const result = await this.api.authorityLinkSources(this.organizationId, this.projectId, undefined, command.jobId,
        command.jobId === undefined ? command.key : undefined);
      if (generation !== this.generation) return;
      if (command.jobId !== undefined) {
        const job = this.readJob(result, command.jobId);
        if (!this.matches(job, command) || !(job.cancel_requested || job.status === 'cancelled')) throw new Error();
      } else {
        const info = this.readContext(result);
        if (info.lookup === 'not_found' && !info.jobs.length && info.can_collect && info.collection_methods.includes(command.method)
          && info.candidates.some((row) => same(row.binding, command.binding))) {
          this.context.set(info); this.notFound.set(true); this.message.set('No matching job found. Fresh exact source, target and authority match; deliberate same-command retry is available.'); return;
        }
        if (info.lookup !== 'found' || info.jobs.length !== 1 || !this.matches(info.jobs[0], command)) throw new Error();
      }
      this.pending.set(null); this.busy.set(false); await this.load();
      if (generation + 1 === this.generation) this.message.set('Command reconciled from authoritative status; no command replayed.');
    } catch { if (generation === this.generation) { this.context.set(null); this.selected.set(null); this.chosen.set(null); this.message.set('Exact outcome/current binding unavailable. No command replayed.'); } }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  async retry() {
    const command = this.pending(); if (!command || command.jobId !== undefined || !this.notFound() || this.busy()) return;
    const generation = this.generation; await this.reconcile();
    if (generation === this.generation && this.pending() === command && this.notFound()) await this.send(command);
  }
}
