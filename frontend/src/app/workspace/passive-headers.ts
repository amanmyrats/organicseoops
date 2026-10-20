import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, OnInit, computed, effect, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi, ApiResult } from '../account/account-api';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';
import { microseconds } from './utc-date';
import { safeUrl, same } from './authority-links';

type Row = Record<string, unknown>;
type Job = { id: number; status: string; created_at: string; updated_at: string; cancel_requested: boolean; estimate_units: number; error_category: string };
type Verification = { id: number; project_id: number; origin: string; method: string; state: string; challenge_path: string;
  created_at: string; updated_at: string; verified_at: string | null; revoked_at: string | null };
type Preview = { selection: Row & { binding: Row }; selection_digest: string };
type Pending = { data: Row; preview: Preview; key: string; jobId?: number };
type HeaderCandidate = { detector: string; evidence: Row };
type FindingInspection = { job: Job; report: Row; candidateDigest: string; findingSet: Row };
type PriorityInspection = { original: FindingInspection; findingId: number; judgment: Row };
type PriorityPending = PriorityInspection & { command: Row };
type ResponsePair = { http: Job; https: Job };
const PAIR_MEANING = 'two_separate_dated_responses_not_location_target_path_followed_upgrade_browser_behavior_current_https_availability_or_authenticated_http_identity';
const PATH = '/.well-known/organicseoops-verification.txt';
const METHOD = 'passive-header-collection-v1';
const TLS_METHOD = 'passive-tls-collection-v1';
const RESOURCE_METHOD = 'passive-resource-collection-v1';
const REDIRECT_METHOD = 'passive-redirect-collection-v1';
const HTTP_REDIRECT_METHOD = 'passive-http-redirect-collection-v1';
const CHAIN_METHOD = 'passive-exact-redirect-chain-evidence-v1';
const CHAIN_SOURCE_MEANING = 'explicit_exact_url_allowlist_not_observed_chain_network_job_or_commercial_reservation';
const CHAIN_MEANING = 'dated_exact_selected_responses_not_browser_behavior_current_availability_authenticated_http_identity_or_security_verdict';
const TARGET_STATES = ['permitted_target', 'terminal_response', 'location_unavailable', 'unsupported_target', 'outside_exact_target_allowlist'];
const HTTP_MEANING = 'plaintext_http_location_metadata_not_authenticated_identity_observed_https_followed_upgrade_browser_behavior_or_target_authority';
const HTTP_LOCATION_MEANING = 'one_http_response_location_metadata_not_observed_https_followed_upgrade_browser_behavior_or_target_authority';
const REDIRECT_MEANING = 'one_response_location_metadata_not_followed_chain_https_upgrade_browser_behavior_or_target_authority';
const REDIRECT_TRANSPORT_MEANING = 'location_metadata_not_followed_chain_https_upgrade_browser_behavior_or_target_authority';
const RESOURCE_MEANING = 'one_complete_response_literal_candidates_not_browser_requests_or_whole_page_mixed_content_security';
const RESOURCE_TRANSPORT_MEANING = 'literal_candidates_not_browser_requests_or_whole_page_mixed_content_security';
const RESOURCE_COUNTS = ['inspected_attributes', 'http_absolute', 'https_absolute', 'unclassified'];
const RESOURCE_ATTRIBUTES = ['script/src', 'iframe/src', 'img/src', 'link[stylesheet|preload|modulepreload]/href'];
const TLS_MEANING = 'one_validated_handshake_not_all_supported_tls_configuration_revocation_or_exploitability';
const TLS_TRANSPORT_MEANING = 'negotiated_parameters_not_all_supported_configuration_revocation_or_exploitability';
const DATE_MEANING = 'reported_dates_not_tls_chain_hostname_revocation_validation_or_server_identity';
const SOURCE_MEANING = 'current_source_binding_not_network_job_commercial_reservation_or_observation_authority';
const MEANING = 'one_public_response_not_policy_effectiveness_tls_configuration_redirect_behavior_or_exploitability';
const HEADER_MEANING = 'header_presence_and_explicit_cookie_flags_not_policy_effectiveness_browser_acceptance_or_exploitability';
const HEADERS = ['strict-transport-security', 'content-security-policy', 'content-security-policy-report-only', 'x-frame-options',
  'x-content-type-options', 'referrer-policy', 'server', 'x-powered-by'];
const COOKIES = ['observed_fields', 'parsed_fields', 'unclassified_fields', 'without_secure', 'without_httponly', 'without_recognized_samesite'];
const PRIORITIES = ['unprioritized', 'low', 'medium', 'high'];
const EFFORTS = ['unknown', 'small', 'medium', 'large'];
const RELEVANCES = ['unknown', 'low', 'medium', 'high'];
const ERRORS = ['', 'invalid_header_observation', 'invalid_url', 'outside_scope', 'non_public_address', 'dns_error', 'timeout', 'network_error',
  'response_headers_unavailable', 'request_outcome_unknown', 'handler_failed', 'cancel_requested', 'source_scope_changed', 'usage_unreserved',
  'broker_unavailable', 'internal_capacity', 'trial_unavailable', 'trial_units_exhausted', 'paid_unavailable', 'billing_review_hold',
  'paid_period_changed', 'paid_units_exhausted', 'actor_revoked', 'unclassified_failure', 'invalid_tls_observation', 'tls_observation_failed',
  'invalid_resource_observation', 'resource_body_unavailable', 'incomplete_response_body', 'response_too_large', 'invalid_content_encoding', 'invalid_redirect_observation'];
const object = (value: unknown): value is Row => !!value && typeof value === 'object' && !Array.isArray(value);
const exact = (value: unknown, keys: string[]): value is Row => object(value) && same(Object.keys(value).sort(), [...keys].sort());
const positive = (value: unknown) => Number.isSafeInteger(value) && Number(value) > 0;
const digest = (value: unknown) => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const dated = (value: unknown) => { const stamp = microseconds(value); return stamp !== null && stamp <= BigInt(Date.now()) * 1000n; };
const ordered = (before: unknown, after: unknown) => dated(before) && dated(after) && microseconds(before)! <= microseconds(after)!;
const canonicalDate = (value: unknown) => typeof value === 'string' && /\.\d{6}\+00:00$/.test(value) && microseconds(value) !== null;
function canonical(value: unknown): unknown {
  return Array.isArray(value) ? value.map(canonical) : object(value)
    ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value;
}
async function selectionDigest(value: unknown) {
  const encoded = JSON.stringify(canonical(value)).replace(/[\u007f-\uffff]/g, char => `\\u${char.charCodeAt(0).toString(16).padStart(4, '0')}`);
  const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(encoded));
  return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, '0')).join('');
}
function safeHttpUrl(value: unknown) {
  if (typeof value !== 'string' || /[\s\\?#]/.test(value)) return '';
  try { const url = new URL(value); return url.protocol === 'http:' && !url.username && !url.password && !url.port ? url.href : ''; }
  catch { return ''; }
}

const passiveTurkish: Record<string, string> = {
  "Private exact response-header observations": "Özel tam yanıt başlığı gözlemleri",
  "Private exact TLS handshake observations": "Özel tam TLS el sıkışması gözlemleri",
  "Private exact static resource candidates": "Özel tam statik kaynak adayları",
  "Private exact first-response Location metadata": "Özel tam ilk yanıt Location meta verileri",
  "Private plaintext HTTP Location metadata": "Özel düz metin HTTP Location meta verileri",
  "Private exact permitted redirect chain": "Özel tam izin verilmiş yönlendirme zinciri",
  "Organization": "Kuruluş",
  "· project": "· proje",
  "Project evidence": "Proje kanıtları",
  "Owner/admin only. Independently configure and verify EVERY selected HTTP or HTTPS origin, including targets never visited. Separately permit one exact initial URL and zero–five distinct exact target URLs. The allowlist is permission, not a predicted chain. Follow only fresh single Location references matching those exact URLs, at most five redirects and six header-only responses. Stop before unknown, unsupported, outside-allowlist, loop or budget targets. No bodies, probes, cookies, browser execution, active scanning or automatic schedule. HTTPS uses default hostname and chain validation; plaintext HTTP is unauthenticated. Failed TLS is never retried without validation.": "Yalnızca sahip/yönetici. Ziyaret edilmeyen hedefler dahil seçilen HER HTTP veya HTTPS kökenini bağımsız olarak yapılandırıp doğrulayın. Bir tam başlangıç URL'sine ve sıfır–beş farklı tam hedef URL'sine ayrı izin verin. İzin listesi tahmini zincir değildir. Yalnızca bu tam URL'lerle eşleşen yeni tek Location başvurularını takip edin; en fazla beş yönlendirme ve altı yalnızca başlık yanıtı. Bilinmeyen, desteklenmeyen, liste dışı, döngü veya bütçe hedeflerinden önce durun. Gövde, sonda, çerez, tarayıcı çalıştırma, aktif tarama veya otomatik zamanlama yoktur. HTTPS varsayılan ana bilgisayar ve zincir doğrulamasını kullanır; düz metin HTTP kimliği doğrulanmamıştır. Başarısız TLS, doğrulama olmadan yeniden denenmez.",
  "Owner/admin only. One independently configured and verified exact HTTP first response with separate permission. HTTP is unauthenticated plaintext, not authenticated server identity. HTTPS verification never authorizes its HTTP counterpart. Only original status, Location cardinality and syntactic scheme, same-origin and same-host default-HTTPS reference metadata are retained. No body reading, target lookup or follow, HTTPS counterpart request, browser execution, active scanning or automatic schedule. A syntactic HTTPS reference is not observed HTTPS availability, a followed upgrade, browser behavior, target permission or a secure verdict.": "Yalnızca sahip/yönetici. Ayrı izinle bağımsız yapılandırılmış ve doğrulanmış tek bir tam HTTP ilk yanıtı. HTTP kimliği doğrulanmamış düz metindir, doğrulanmış sunucu kimliği değildir. HTTPS doğrulaması HTTP karşılığına izin vermez. Yalnızca özgün durum, Location alan sayısı ve sözdizimsel şema, aynı köken ve aynı ana bilgisayar varsayılan HTTPS başvuru üst verisi saklanır. Gövde okuma, hedef arama veya takip, HTTPS karşılığı isteği, tarayıcı çalıştırma, aktif tarama veya otomatik zamanlama yoktur. Sözdizimsel HTTPS başvurusu gözlemlenmiş HTTPS kullanılabilirliği, takip edilmiş yükseltme, tarayıcı davranışı, hedef izni veya güvenli hükmü değildir.",
  "Owner/admin only. One independently permitted exact HTTPS first response, using default hostname and chain validation. No body reading, Location target lookup or follow, HTTP upgrade probe, browser execution, active scanning or automatic schedule. Only original status, Location field cardinality, classified HTTP/HTTPS scheme and syntactic same-origin metadata are retained. Classification is not target eligibility, a followed chain, HTTPS upgrade behavior, browser behavior, security severity or a whole-site result.": "Yalnızca sahip/yönetici. Varsayılan ana bilgisayar ve zincir doğrulamasıyla bağımsız izin verilmiş tek tam HTTPS ilk yanıtı. Gövde okuma, Location hedef arama veya takip, HTTP yükseltme sondası, tarayıcı çalıştırma, aktif tarama veya otomatik zamanlama yoktur. Yalnızca özgün durum, Location alan sayısı, sınıflandırılmış HTTP/HTTPS şeması ve sözdizimsel aynı köken üst verisi saklanır. Sınıflandırma hedef uygunluğu, takip edilmiş zincir, HTTPS yükseltme davranışı, tarayıcı davranışı, güvenlik önem derecesi veya tüm site sonucu değildir.",
  "Owner/admin only. One independently permitted exact HTTPS URL and one bounded complete UTF-8 HTML response, interpreted transiently. Default hostname and chain validation; no redirects, subresource requests, browser execution, active scanning or automatic schedule. Only literal script/src, iframe/src, img/src and stylesheet/preload/modulepreload link/href candidates are counted. Navigation, CSS, srcset, JavaScript, dynamic and media references, inert/raw-text and foreign descendants are excluded. These are not browser requests, browser mixed-content policy, whole-page security, vulnerability proof or a score.": "Yalnızca sahip/yönetici. Bağımsız izin verilmiş tek tam HTTPS URL'si ve geçici yorumlanan tek sınırlı eksiksiz UTF-8 HTML yanıtı. Varsayılan ana bilgisayar ve zincir doğrulaması; yönlendirme, alt kaynak isteği, tarayıcı çalıştırma, aktif tarama veya otomatik zamanlama yoktur. Yalnızca gerçek script/src, iframe/src, img/src ve stylesheet/preload/modulepreload link/href adayları sayılır. Gezinme, CSS, srcset, JavaScript, dinamik ve medya başvuruları, etkisiz/ham metin ve yabancı alt öğeler dışlanır. Bunlar tarayıcı isteği, tarayıcı karma içerik politikası, tüm sayfa güvenliği, açıklık kanıtı veya puan değildir.",
  "Owner/admin only. One separately permitted exact HTTPS-origin handshake using default hostname and chain validation. No HTTP requests, redirects, protocol inventory, cipher probing, active scanning or automatic schedule. Expired, untrusted or mismatched certificates fail categorically; TLS is never relaxed to inspect them. Negotiated parameters are not the whole configuration, revocation status, server identity proof or exploitability.": "Yalnızca sahip/yönetici. Varsayılan ana bilgisayar ve zincir doğrulamasıyla ayrı izin verilmiş tek tam HTTPS kökeni el sıkışması. HTTP isteği, yönlendirme, protokol envanteri, şifre sondası, aktif tarama veya otomatik zamanlama yoktur. Süresi dolmuş, güvenilmeyen veya eşleşmeyen sertifikalar kesin olarak başarısız olur; TLS bunları incelemek için gevşetilmez. Müzakere edilen parametreler tüm yapılandırma, iptal durumu, sunucu kimliği kanıtı veya istismar edilebilirlik değildir.",
  "Owner/admin only. One explicitly permitted HTTPS response; no redirects followed, HTTP probes, body reading, login cookies, active scanning or automatic schedule. Presence is not policy effectiveness, certificate/TLS configuration, redirect behavior, whole-site security or exploitability.": "Yalnızca sahip/yönetici. Açıkça izin verilmiş tek HTTPS yanıtı; yönlendirme takibi, HTTP sondası, gövde okuma, giriş çerezleri, aktif tarama veya otomatik zamanlama yoktur. Varlık politika etkinliği, sertifika/TLS yapılandırması, yönlendirme davranışı, tüm site güvenliği veya istismar edilebilirlik değildir.",
  "One internal operation unit is reserved. An attempted or uncertain request consumes it; this is not a provider charge.": "Bir dahili işlem birimi ayrılır. Denenmiş veya belirsiz istek bunu tüketir; bu sağlayıcı ücreti değildir.",
  "Minimized private evidence follows export/closure policy: 90-day retained access after lapse, active deletion within 30 days of closure/expiry, up to 35-day backup rotation after active deletion.": "Asgariye indirilmiş özel kanıt dışa aktarım/kapanma politikasını izler: sona ermeden sonra 90 gün saklanan erişim, kapanma/süre sonundan itibaren 30 gün içinde aktif silme, aktif silmeden sonra en fazla 35 günlük yedek rotasyonu.",
  "Checking exact current source and private state.": "Tam güncel kaynak ve özel durum kontrol ediliyor.",
  "Refresh current ownership and private history": "Güncel sahipliği ve özel geçmişi yenileyin",
  "Existing ownership, observations and original facts": "Mevcut sahiplik, gözlemler ve özgün olgular",
  "Exact-origin HTTP-file ownership": "Tam köken HTTP dosyası sahipliği",
  "Configured": "Yapılandırılmış",
  "origin": "köken",
  "Choose exact origin": "Tam köken seçin",
  "Creating or rotating a challenge removes prior verification for this origin. Deploy the exact plain-text file yourself; the application never deploys it.": "Doğrulama oluşturmak veya yenilemek bu kökenin önceki doğrulamasını kaldırır. Tam düz metin dosyasını kendiniz yayımlayın; uygulama bunu yayımlamaz.",
  "Create or rotate exact HTTP-file challenge": "Tam HTTP dosyası doğrulamasını oluşturun veya yenileyin",
  "Shown once, only in this page's memory. Place these exact contents at": "Bir kez, yalnızca bu sayfanın belleğinde gösterilir. Bu tam içeriği şu adrese koyun:",
  "with HTTP 200 and no redirect.": "HTTP 200 ve yönlendirme olmadan.",
  "· original verification": "· özgün doğrulama",
  "· updated": "· güncellendi",
  "I deployed the file; request exact ownership check": "Dosyayı yayımladım; tam sahiplik kontrolünü isteyin",
  "Revoke this exact origin": "Bu tam kökeni iptal edin",
  "No retained ownership record. No verified source is implied.": "Saklanan sahiplik kaydı yok. Doğrulanmış kaynak ima edilmez.",
  "Only the first 100 ownership records are shown.": "Yalnızca ilk 100 sahiplik kaydı gösteriliyor.",
  "Selected exact origin:": "Seçilen tam köken:",
  ". Header permission does not authorize a TLS observation.": ". Başlık izni TLS gözlemine izin vermez.",
  "Canonical": "Kanonik",
  "URL without query, fragment, credentials or custom port": "sorgu, parça, kimlik bilgisi veya özel bağlantı noktası içermeyen URL",
  "Header or TLS permission does not authorize this separate transient-body observation.": "Başlık veya TLS izni bu ayrı geçici gövde gözlemine izin vermez.",
  "Header, TLS or resource permission does not authorize this separate first-response Location observation.": "Başlık, TLS veya kaynak izni bu ayrı ilk yanıt Location gözlemine izin vermez.",
  "HTTPS Location, header, TLS or resource permission does not authorize this separate HTTP observation.": "HTTPS Location, başlık, TLS veya kaynak izni bu ayrı HTTP gözlemine izin vermez.",
  "Every selected origin must be independently configured and verified. Other passive permissions and saved Location syntax grant no chain authority.": "Seçilen her köken bağımsız yapılandırılıp doğrulanmalıdır. Diğer pasif izinler ve kaydedilen Location sözdizimi zincir yetkisi vermez.",
  "Exact permitted target URL": "Tam izin verilmiş hedef URL",
  "Remove target": "Hedefi kaldırın",
  "Add independently permitted exact target (maximum 5)": "Bağımsız izin verilmiş tam hedef ekleyin (en fazla 5)",
  "Preview exact current verified source (no site request)": "Tam güncel doğrulanmış kaynağı önizleyin (site isteği yok)",
  "Exact": "Tam",
  "All original selected origins and verification dates are in the frozen binding, including targets that may never be visited.": "Ziyaret edilmeyebilecek hedefler dahil tüm özgün seçilen kökenler ve doğrulama tarihleri dondurulmuş bağlamadadır.",
  "Verification": "Doğrulama",
  "· original date": "· özgün tarih",
  "Frozen original source binding and selection digest": "Dondurulmuş özgün kaynak bağlaması ve seçim özeti",
  "Reserve 1 unit and request this exact": "1 birim ayırın ve bu tam gözlemi isteyin:",
  "The exact command outcome is uncertain. Binding and request key are frozen in component memory. No automatic replay.": "Tam komut sonucu belirsiz. Bağlama ve istek anahtarı bileşen belleğinde dondurulmuştur. Otomatik yeniden oynatma yoktur.",
  "Look up exact original command": "Tam özgün komutu arayın",
  "Deliberately retry same command after fresh source check": "Yeni kaynak kontrolünden sonra aynı komutu bilinçli olarak yeniden deneyin",
  "Discard local uncertainty; a saved job may exist": "Yerel belirsizliği atın; kaydedilmiş bir iş olabilir",
  "Private": "Özel",
  "-job metadata": "iş üst verisi",
  "No retained": "Saklanan",
  "jobs. Missing is not a clean security result.": "iş yok. Eksiklik temiz güvenlik sonucu değildir.",
  "Only the latest 20 jobs are shown.": "Yalnızca son 20 iş gösteriliyor.",
  "Job": "İş",
  "· created": "· oluşturuldu",
  "Inspect exact private job": "Tam özel işi inceleyin",
  "Inspect original header review candidates": "Özgün başlık inceleme adaylarını inceleyin",
  "Inspect current original header findings (no save)": "Güncel özgün başlık bulgularını inceleyin (kaydetme yok)",
  "Inspect original literal HTTP resource review candidate": "Özgün gerçek HTTP kaynak inceleme adayını inceleyin",
  "Inspect current original resource findings (no save)": "Güncel özgün kaynak bulgularını inceleyin (kaydetme yok)",
  "Inspect original certificate-date and negotiated-version review candidates": "Özgün sertifika tarihi ve müzakere edilen sürüm inceleme adaylarını inceleyin",
  "Inspect current original TLS findings (no save)": "Güncel özgün TLS bulgularını inceleyin (kaydetme yok)",
  "Inspect original HTTP-scheme Location review candidate": "Özgün HTTP şemalı Location inceleme adayını inceleyin",
  "Inspect current original Location findings (no save)": "Güncel özgün Location bulgularını inceleyin (kaydetme yok)",
  "Inspect original chain transition and stop review candidates": "Özgün zincir geçişi ve durma inceleme adaylarını inceleyin",
  "Inspect current original chain findings (no save)": "Güncel özgün zincir bulgularını inceleyin (kaydetme yok)",
  "Request cancellation": "İptal isteyin",
  "Two independently saved original HTTP and HTTPS responses": "Bağımsız kaydedilmiş iki özgün HTTP ve HTTPS yanıtı",
  "Choose two retained succeeded jobs deliberately. Reading a pair makes no site request or new unit reservation. The source URLs must have the same host, default ports and exact source path. Either capture order is allowed. Minimized HTTP Location syntax cannot reveal its target path or prove that the selected HTTPS URL was followed.": "Saklanan başarılı iki işi bilinçli olarak seçin. Çifti okumak site isteği veya yeni birim ayırma yapmaz. Kaynak URL'lerinin ana bilgisayarı, varsayılan bağlantı noktaları ve tam kaynak yolu aynı olmalıdır. Her iki yakalama sırası kabul edilir. Asgariye indirilmiş HTTP Location sözdizimi hedef yolunu açıklayamaz veya seçilen HTTPS URL'sinin takip edildiğini kanıtlayamaz.",
  "Refresh separately saved HTTPS Location history (no collection)": "Ayrı kaydedilmiş HTTPS Location geçmişini yenileyin (toplama yok)",
  "Only the latest 20 HTTPS jobs are shown.": "Yalnızca son 20 HTTPS işi gösteriliyor.",
  "Explicit independent saved-job pair": "Açık bağımsız kaydedilmiş iş çifti",
  "Original plaintext HTTP job": "Özgün düz metin HTTP işi",
  "Choose saved succeeded HTTP job": "Kaydedilmiş başarılı HTTP işi seçin",
  "Separately collected default-validated HTTPS job": "Ayrı toplanmış varsayılan doğrulanmış HTTPS işi",
  "Choose saved succeeded HTTPS job": "Kaydedilmiş başarılı HTTPS işi seçin",
  "Read these two original saved responses": "Bu iki özgün kaydedilmiş yanıtı okuyun",
  "Separate original dated responses · no followed upgrade or current availability claim": "Ayrı özgün tarihli yanıtlar · takip edilmiş yükseltme veya güncel kullanılabilirlik iddiası yok",
  "· original job": "· özgün iş",
  "Original actor": "Özgün aktör",
  "· independent verification": "· bağımsız doğrulama",
  "at": "tarih",
  "· capture": "· yakalama",
  "· response status": "· yanıt durumu",
  "These are two separate dated observations, not a chain or before/after causal result. No current HTTPS availability, authenticated HTTP identity, browser behavior, target permission or security verdict is established. Absent, empty, multiple or unclassified Location metadata remains null, not zero or a clean result. No raw Location target/path or target link is available. A failed or unavailable job cannot form an observed pair.": "Bunlar iki ayrı tarihli gözlemdir, zincir veya önce/sonra nedensel sonucu değildir. Güncel HTTPS kullanılabilirliği, doğrulanmış HTTP kimliği, tarayıcı davranışı, hedef izni veya güvenlik hükmü kurulmaz. Yok, boş, çoklu veya sınıflandırılmamış Location üst verisi null kalır, sıfır veya temiz sonuç değildir. Ham Location hedefi/yolu veya hedef bağlantısı yoktur. Başarısız veya kullanılamayan iş gözlemlenmiş çift oluşturamaz.",
  "Exact job": "Tam iş",
  "Original selected response URLs, UTC microseconds, status and stop coverage are preserved. Only captured hops were observed; selected UNVISITED targets remain permissions, not observations. Unknown Location metadata remains null. Loop, budget, unsupported and outside-allowlist stops do not establish the target path from minimized syntax. No current availability, browser behavior, authenticated HTTP identity, security verdict, Finding or report authority is established. No raw target link is available.": "Özgün seçilen yanıt URL'leri, UTC mikrosaniyeleri, durum ve durma kapsamı korunur. Yalnızca yakalanan atlamalar gözlemlendi; seçilen ZİYARET EDİLMEMİŞ hedefler izindir, gözlem değildir. Bilinmeyen Location üst verisi null kalır. Döngü, bütçe, desteklenmeyen ve liste dışı durmalar asgariye indirilmiş sözdiziminden hedef yolunu belirlemez. Güncel kullanılabilirlik, tarayıcı davranışı, doğrulanmış HTTP kimliği, güvenlik hükmü, bulgu veya rapor yetkisi kurulmaz. Ham hedef bağlantısı yoktur.",
  "Original local UTC microseconds and plaintext response status are preserved, not authenticated server identity. Common redirect status is independent of Location syntax. A same-host default-HTTPS reference is syntactic only, not observed HTTPS availability or a followed upgrade. Absent, empty, multiple and unclassified fields keep scheme, same-origin and counterpart metadata null. Null is not zero or a secure verdict. No raw target link or current target permission is available.": "Özgün yerel UTC mikrosaniyeleri ve düz metin yanıt durumu korunur; doğrulanmış sunucu kimliği değildir. Yaygın yönlendirme durumu Location sözdiziminden bağımsızdır. Aynı ana bilgisayar varsayılan HTTPS başvurusu yalnızca sözdizimseldir, gözlemlenmiş HTTPS kullanılabilirliği veya takip edilmiş yükseltme değildir. Yok, boş, çoklu ve sınıflandırılmamış alanlar şema, aynı köken ve karşılık üst verisini null tutar. Null sıfır veya güvenli hükmü değildir. Ham hedef bağlantısı veya güncel hedef izni yoktur.",
  "Original UTC microseconds and response status are preserved. Common redirect status does not prove a followed redirect. Absent, empty, multiple and single-unclassified Location fields remain distinct; all target metadata is null unless classified. Same origin means only the original scheme, host and effective port; it supplies no target permission or DNS evidence. Null is not zero, secure or a clean result. No raw target link is available.": "Özgün UTC mikrosaniyeleri ve yanıt durumu korunur. Yaygın yönlendirme durumu takip edilmiş yönlendirmeyi kanıtlamaz. Yok, boş, çoklu ve tek sınıflandırılmamış Location alanları ayrı kalır; sınıflandırılmadıkça tüm hedef üst verisi null olur. Aynı köken yalnızca özgün şema, ana bilgisayar ve etkin bağlantı noktasıdır; hedef izni veya DNS kanıtı sağlamaz. Null sıfır, güvenli veya temiz sonuç değildir. Ham hedef bağlantısı yoktur.",
  "Original UTC microseconds are preserved. Counts are bounded literal candidates in selected attributes only, not browser requests or whole-page mixed-content proof. Unclassified is not insecure or secure. Lexically unavailable evidence keeps all counts null; null is not zero or a clean result.": "Özgün UTC mikrosaniyeleri korunur. Sayılar yalnızca seçilen özniteliklerdeki sınırlı gerçek adaylardır; tarayıcı isteği veya tüm sayfa karma içerik kanıtı değildir. Sınıflandırılmamış, güvensiz veya güvenli değildir. Sözcüksel olarak kullanılamayan kanıt tüm sayıları null tutar; null sıfır veya temiz sonuç değildir.",
  "Original UTC microseconds are preserved. Certificate dates use inclusive original reported bounds; remaining_microseconds is an exact signed decimal string, not rounded days or a warning threshold. Null/unavailable is not zero or a secure verdict. Only the negotiated version and cipher are shown, not all supported configuration or revocation evidence.": "Özgün UTC mikrosaniyeleri korunur. Sertifika tarihleri özgün bildirilen sınırları dahil eder; remaining_microseconds tam işaretli ondalık dizgedir, yuvarlanmış gün veya uyarı eşiği değildir. Null/kullanılamayan sıfır veya güvenli hükmü değildir. Yalnızca müzakere edilen sürüm ve şifre gösterilir; tüm desteklenen yapılandırma veya iptal kanıtı değildir.",
  "Cookie counts concern explicitly parsed fields in this one response. Unsupported fields remain unclassified, not insecure or secure verdicts.": "Çerez sayıları bu tek yanıtta açıkça ayrıştırılan alanlarla ilgilidir. Desteklenmeyen alanlar sınıflandırılmamış kalır, güvensiz veya güvenli hükümleri değildir.",
  "No current private observation available. Failed, cancelled, unknown or uncollected is not zero findings.": "Güncel özel gözlem yok. Başarısız, iptal edilmiş, bilinmeyen veya toplanmamış, sıfır bulgu değildir.",
  "Original chain transition and stop review candidates · job": "Özgün zincir geçişi ve durma inceleme adayları · iş",
  "Originally selected URLs:": "Özgün seçilen URL'ler:",
  "· actually captured responses:": "· gerçekten yakalanan yanıtlar:",
  "· last target syntax:": "· son hedef sözdizimi:",
  "· original stop:": "· özgün durma:",
  "Original first capture": "Özgün ilk yakalama",
  "· last capture": "· son yakalama",
  ". Hop indices are zero-based; dates and status remain in the original collection below. Selected UNVISITED targets are permissions, not observations.": ". Atlama dizinleri sıfır tabanlıdır; tarihler ve durum aşağıdaki özgün toplamada kalır. Seçilen ZİYARET EDİLMEMİŞ hedefler izindir, gözlem değildir.",
  "No eligible transition or loop/budget-stop candidates in these original captured responses. This is not a clean, secure or whole-site result.": "Bu özgün yakalanan yanıtlarda uygun geçiş veya döngü/bütçe durma adayı yok. Bu temiz, güvenli veya tüm site sonucu değildir.",
  "Last target syntax is unknown; scheme and same-origin remain null, not zero or a secure verdict.": "Son hedef sözdizimi bilinmiyor; şema ve aynı köken null kalır, sıfır veya güvenli hükmü değildir.",
  "A stopped loop is not a repeated response; a budget stop is incomplete coverage, not a broken destination. Unknown, unsupported and outside-allowlist targets were not followed. Minimized syntax cannot reconstruct raw Location target paths. No current availability, browser behavior, authenticated HTTP identity, severity, approval or target authority is established. Inspection makes no site request, new unit reservation, Finding save, human prioritization or general report/share grant. No raw target link is available.": "Durdurulmuş döngü tekrarlanan yanıt değildir; bütçe durması eksik kapsamdır, bozuk hedef değildir. Bilinmeyen, desteklenmeyen ve liste dışı hedefler takip edilmedi. Asgariye indirilmiş sözdizimi ham Location hedef yollarını yeniden kuramaz. Güncel kullanılabilirlik, tarayıcı davranışı, doğrulanmış HTTP kimliği, önem derecesi, onay veya hedef yetkisi kurulmaz. İnceleme site isteği, yeni birim ayırma, bulgu kaydetme, insan önceliklendirmesi veya genel rapor/paylaşım yetkisi vermez. Ham hedef bağlantısı yoktur.",
  "Full original selected binding, dated response status, index facts, availability and stop coverage": "Tam özgün seçilen bağlama, tarihli yanıt durumu, dizin olguları, kullanılabilirlik ve durma kapsamı",
  "Explicitly save these original chain facts": "Bu özgün zincir olgularını açıkça kaydedin",
  "Saving existing facts makes no site request, target follow or new unit reservation, human priority, approval or general report/share availability.": "Mevcut olguları kaydetmek site isteği, hedef takibi veya yeni birim ayırma, insan önceliği, onay veya genel rapor/paylaşım kullanılabilirliği sağlamaz.",
  "Original Location review candidates · job": "Özgün Location inceleme adayları · iş",
  "Original observation": "Özgün gözlem",
  "· HTTP": "· HTTP",
  ". Target metadata:": ". Hedef üst verisi:",
  "· Location fields:": "· Location alanları:",
  "Original target metadata unknown. Target scheme and same-origin remain null; absent, empty, multiple or unclassified fields are not zero candidates or a secure verdict.": "Özgün hedef üst verisi bilinmiyor. Hedef şema ve aynı köken null kalır; yok, boş, çoklu veya sınıflandırılmamış alanlar sıfır aday veya güvenli hükmü değildir.",
  "Original classified HTTPS reference has no eligible HTTP-scheme candidate. This is not a secure or whole-site result.": "Özgün sınıflandırılmış HTTPS başvurusunun uygun HTTP şemalı adayı yok. Bu güvenli veya tüm site sonucu değildir.",
  "A common redirect status is a literal original status flag, not proof of followed redirection, downgrade, HTTPS upgrade, browser behavior, severity or target authority. Same-origin is only a syntactic scheme, host and effective-port comparison. No raw target link is available. Inspection makes no site request, new unit reservation, Finding save or human prioritization.": "Yaygın yönlendirme durumu özgün gerçek durum bayrağıdır; takip edilmiş yönlendirme, düşürme, HTTPS yükseltme, tarayıcı davranışı, önem derecesi veya hedef yetkisi kanıtı değildir. Aynı köken yalnızca sözdizimsel şema, ana bilgisayar ve etkin bağlantı noktası karşılaştırmasıdır. Ham hedef bağlantısı yoktur. İnceleme site isteği, yeni birim ayırma, bulgu kaydetme veya insan önceliklendirmesi yapmaz.",
  "Original minimized binding, date, status, classification, availability and coverage": "Özgün asgari bağlama, tarih, durum, sınıflandırma, kullanılabilirlik ve kapsam",
  "Explicitly save this original Location fact": "Bu özgün Location olgusunu açıkça kaydedin",
  "Saving existing facts makes no site request, target lookup/follow or new unit reservation, human priority, approval or general report/share availability.": "Mevcut olguları kaydetmek site isteği, hedef arama/takip veya yeni birim ayırma, insan önceliği, onay veya genel rapor/paylaşım kullanılabilirliği sağlamaz.",
  "Original certificate-date and negotiated-version review candidates · job": "Özgün sertifika tarihi ve müzakere edilen sürüm inceleme adayları · iş",
  "· exact origin": "· tam köken",
  ". Dated literal facts only, not supported server configuration, revocation, browser behavior, severity, approval or exploitability.": ". Yalnızca tarihli gerçek olgular; desteklenen sunucu yapılandırması, iptal, tarayıcı davranışı, önem derecesi, onay veya istismar edilebilirlik değildir.",
  "Certificate dates:": "Sertifika tarihleri:",
  "· actual negotiated version:": "· gerçek müzakere edilen sürüm:",
  ". Each unavailable value remains independently unknown, not zero candidates or a secure verdict.": ". Kullanılamayan her değer bağımsız bilinmeyen kalır, sıfır aday veya güvenli hükmü değildir.",
  "No eligible review candidates among the available original date/version observations. Unavailable evidence is still unknown; this is not a clean or whole-site result.": "Mevcut özgün tarih/sürüm gözlemlerinde uygun inceleme adayı yok. Kullanılamayan kanıt hâlâ bilinmiyor; bu temiz veya tüm site sonucu değildir.",
  "Reported interval bounds are inclusive; remaining_microseconds is the exact signed decimal string, without rounding or a warning threshold. Cipher metadata is not the actual negotiated version. Inspection makes no site request, handshake, unit reservation, fact save or human prioritization.": "Bildirilen aralık sınırları dahildir; remaining_microseconds yuvarlama veya uyarı eşiği olmadan tam işaretli ondalık dizgedir. Şifre üst verisi gerçek müzakere edilen sürüm değildir. İnceleme site isteği, el sıkışması, birim ayırma, olgu kaydetme veya insan önceliklendirmesi yapmaz.",
  "Original minimized binding, dates, negotiated parameters, availability and coverage": "Özgün asgari bağlama, tarihler, müzakere edilen parametreler, kullanılabilirlik ve kapsam",
  "Explicitly save these original TLS facts": "Bu özgün TLS olgularını açıkça kaydedin",
  "Saving existing facts makes no handshake, site request or new unit reservation, human priority, approval or general report/share availability.": "Mevcut olguları kaydetmek el sıkışması, site isteği veya yeni birim ayırma, insan önceliği, onay veya genel rapor/paylaşım kullanılabilirliği sağlamaz.",
  "Original literal resource review candidates · job": "Özgün gerçek kaynak inceleme adayları · iş",
  ". Dated literal facts only, not browser requests, mixed-content policy, severity, approval, whole-page security or a score.": ". Yalnızca tarihli gerçek olgular; tarayıcı isteği, karma içerik politikası, önem derecesi, onay, tüm sayfa güvenliği veya puan değildir.",
  "Original lexical evaluation unavailable ·": "Özgün sözcüksel değerlendirme kullanılamıyor ·",
  ". All counts remain null; unavailable is not zero candidates or a clean result.": ". Tüm sayılar null kalır; kullanılamayan sıfır aday veya temiz sonuç değildir.",
  "No eligible literal HTTP review candidate in this original selected-attribute observation. Unclassified is not secure or insecure; this is not a clean or whole-page result.": "Bu özgün seçilmiş öznitelik gözleminde uygun gerçek HTTP inceleme adayı yok. Sınıflandırılmamış, güvenli veya güvensiz değildir; bu temiz veya tüm sayfa sonucu değildir.",
  "Only script/src, iframe/src, img/src and stylesheet/preload/modulepreload link/href are selected. Navigation, CSS, srcset, JavaScript, dynamic/media, inert/raw-text and foreign descendants are excluded. Inspection makes no site request, new unit reservation, fact save or human prioritization.": "Yalnızca script/src, iframe/src, img/src ve stylesheet/preload/modulepreload link/href seçilir. Gezinme, CSS, srcset, JavaScript, dinamik/medya, etkisiz/ham metin ve yabancı alt öğeler dışlanır. İnceleme site isteği, yeni birim ayırma, olgu kaydetme veya insan önceliklendirmesi yapmaz.",
  "Original minimized binding, date, status, coverage and lexical counts": "Özgün asgari bağlama, tarih, durum, kapsam ve sözcüksel sayılar",
  "Explicitly save this original literal resource fact": "Bu özgün gerçek kaynak olgusunu açıkça kaydedin",
  "Saving existing facts makes no site request or new unit reservation, human priority, approval or general report/share availability.": "Mevcut olguları kaydetmek site isteği veya yeni birim ayırma, insan önceliği, onay veya genel rapor/paylaşım kullanılabilirliği sağlamaz.",
  "Original response-header review candidates · job": "Özgün yanıt başlığı inceleme adayları · iş",
  "These dated facts are review candidates, not severity, approval, policy effectiveness, browser behavior or exploitability. Report-only CSP does not provide enforcement. Multiple fields do not prove invalidity or nonempty policy. Unsupported cookie fields remain unclassified and do not contribute missing-flag counts.": "Bu tarihli olgular inceleme adaylarıdır; önem derecesi, onay, politika etkinliği, tarayıcı davranışı veya istismar edilebilirlik değildir. Yalnızca raporlayan CSP uygulama sağlamaz. Çoklu alanlar geçersizliği veya dolu politikayı kanıtlamaz. Desteklenmeyen çerez alanları sınıflandırılmamış kalır ve eksik bayrak sayılarına katkı yapmaz.",
  "No eligible review candidates in this original bounded response. This is not a clean, secure or whole-site result.": "Bu özgün sınırlı yanıtta uygun inceleme adayı yok. Bu temiz, güvenli veya tüm site sonucu değildir.",
  "Original minimized source, date, status and candidate facts": "Özgün asgari kaynak, tarih, durum ve aday olguları",
  "Explicitly save these original header facts": "Bu özgün başlık olgularını açıkça kaydedin",
  "Current private materialized facts · original job": "Güncel özel oluşturulmuş olgular · özgün iş",
  "Original candidate SHA256": "Özgün aday SHA256",
  ". Detection time is the materialization date, separate from the original observation.": ". Tespit zamanı oluşturma tarihidir, özgün gözlemden ayrıdır.",
  "No retained materialized findings. This does not mean zero eligible candidates, a clean security result or a confirmed no-op command.": "Saklanan oluşturulmuş bulgu yok. Bu sıfır uygun aday, temiz güvenlik sonucu veya doğrulanmış etkisiz komut demek değildir.",
  "A complete original fact set is currently retained. This does not identify who saved it or assign risk severity.": "Eksiksiz özgün olgu kümesi şu anda saklanıyor. Bu kimin kaydettiğini belirlemez veya risk önem derecesi atamaz.",
  "Original compact finding identities, dates and facts": "Özgün kısa bulgu kimlikleri, tarihler ve olgular",
  "Finding": "Bulgu",
  "· detected": "· tespit edildi",
  "Inspect this fact's current human judgment": "Bu olgunun güncel insan yargısını inceleyin",
  "Human judgment · Finding": "İnsan yargısı · Bulgu",
  "Human priority, effort and business relevance are judgments, not measured risk severity, a recommendation, approval or a page action. No site request or new unit reservation. The opaque source SHA binds hidden server provenance; this browser cannot independently reconstruct it.": "İnsan önceliği, çaba ve iş ilgisi yargıdır; ölçülmüş risk önem derecesi, öneri, onay veya sayfa eylemi değildir. Site isteği veya yeni birim ayırma yoktur. Opak kaynak SHA gizli sunucu kökenini bağlar; tarayıcı bunu bağımsız yeniden kuramaz.",
  "Current retained judgment · revision": "Güncel saklanan yargı · revizyon",
  "· reviewed": "· incelendi",
  "· priority": "· öncelik",
  "· effort": "· çaba",
  "· relevance": "· ilgi",
  "No retained current human judgment. This is distinct from an explicit human unprioritized decision.": "Saklanan güncel insan yargısı yok. Bu açık insan önceliklendirilmemiş kararından farklıdır.",
  "Selected original fact and server source binding": "Seçilen özgün olgu ve sunucu kaynak bağlaması",
  "Explicit human judgment or correction": "Açık insan yargısı veya düzeltmesi",
  "Human priority": "İnsan önceliği",
  "Estimated effort": "Tahmini çaba",
  "Business relevance": "İş ilgisi",
  "Human review reason (required, at most 240 characters)": "İnsan inceleme gerekçesi (zorunlu, en fazla 240 karakter)",
  "Explicitly save this source-bound human judgment": "Bu kaynağa bağlı insan yargısını açıkça kaydedin",
  "This judgment has reached the maximum revision; another correction is unavailable.": "Bu yargı en yüksek revizyona ulaştı; başka düzeltme kullanılamıyor.",
  "The human judgment command outcome is uncertain. Original job, fact, source SHA, expected revision and fields are frozen only in this page's memory. No automatic POST replay.": "İnsan yargısı komut sonucu belirsiz. Özgün iş, olgu, kaynak SHA, beklenen revizyon ve alanlar yalnızca bu sayfanın belleğinde dondurulmuştur. Otomatik POST yeniden oynatma yoktur.",
  "Read the same fact's current human judgment (no replay)": "Aynı olgunun güncel insan yargısını okuyun (yeniden oynatma yok)",
  "Discard local uncertainty; a stored judgment may exist": "Yerel belirsizliği atın; saklanan yargı olabilir",
  "The original": "Özgün",
  "save outcome is uncertain. Its job, original report and SHA remain frozen only in this page's memory. No automatic POST replay.": "kaydetme sonucu belirsiz. İşi, özgün raporu ve SHA yalnızca bu sayfanın belleğinde dondurulmuştur. Otomatik POST yeniden oynatma yoktur.",
  "Read the same original job and current fact set": "Aynı özgün işi ve güncel olgu kümesini okuyun",
  "Discard local uncertainty; stored facts may still exist": "Yerel belirsizliği atın; saklanan olgular hâlâ olabilir",
  "Exact permitted redirect-chain observations": "Tam izin verilmiş yönlendirme zinciri gözlemleri",
  "Exact plaintext HTTP Location metadata": "Tam düz metin HTTP Location üst verisi",
  "Exact first-response Location metadata": "Tam ilk yanıt Location üst verisi",
  "Exact static resource-reference candidates": "Tam statik kaynak başvurusu adayları",
  "Exact certificate-date and negotiated TLS observations": "Tam sertifika tarihi ve müzakere edilen TLS gözlemleri",
  "Exact public response-header observations": "Tam genel yanıt başlığı gözlemleri",
  "Only explicitly selected URLs, original dated response status and minimized Location syntax are retained, never raw Location values, headers, bodies or their digests.": "Yalnızca açıkça seçilen URL'ler, özgün tarihli yanıt durumu ve asgari Location sözdizimi saklanır; ham Location değerleri, başlıklar, gövdeler veya özetleri saklanmaz.",
  "Raw Location values, target URLs, headers, bodies and their digests are not retained.": "Ham Location değerleri, hedef URL'leri, başlıklar, gövdeler ve özetleri saklanmaz.",
  "Raw HTML, resource URLs, headers and their digests are not retained.": "Ham HTML, kaynak URL'leri, başlıklar ve özetleri saklanmaz.",
  "Raw certificates, identities, certificate links and their digests are not retained.": "Ham sertifikalar, kimlikler, sertifika bağlantıları ve özetleri saklanmaz.",
  "Raw cookies, policies, server values and body are not retained.": "Ham çerezler, politikalar, sunucu değerleri ve gövde saklanmaz.",
  "HTTP or HTTPS": "HTTP veya HTTPS",
  "HTTP": "HTTP",
  "HTTPS": "HTTPS",
  "not verified": "doğrulanmadı",
  "Separate deliberate exact-chain permission": "Ayrı bilinçli tam zincir izni",
  "Separate deliberate HTTP Location permission": "Ayrı bilinçli HTTP Location izni",
  "Separate deliberate Location permission": "Ayrı bilinçli Location izni",
  "Separate deliberate static-resource permission": "Ayrı bilinçli statik kaynak izni",
  "Separate deliberate certificate/TLS permission": "Ayrı bilinçli sertifika/TLS izni",
  "Separate deliberate header permission": "Ayrı bilinçli başlık izni",
  "Exact initial URL and independently permitted targets · redirect_chain only": "Tam başlangıç URL'si ve bağımsız izin verilmiş hedefler · yalnızca redirect_chain",
  "One exact HTTP URL · http_response_location only": "Tek tam HTTP URL'si · yalnızca http_response_location",
  "One exact HTTPS URL · response_location only": "Tek tam HTTPS URL'si · yalnızca response_location",
  "One exact HTTPS URL · static_resource_references only": "Tek tam HTTPS URL'si · yalnızca static_resource_references",
  "One exact HTTPS origin · certificate_dates and negotiated_tls only": "Tek tam HTTPS kökeni · yalnızca certificate_dates ve negotiated_tls",
  "One exact HTTPS URL · response_headers only": "Tek tam HTTPS URL'si · yalnızca response_headers",
  "Choose a configured origin above": "Yukarıda yapılandırılmış bir köken seçin",
  "initial HTTP or HTTPS": "başlangıç HTTP veya HTTPS",
  "I independently have permission to request the exact initial URL and EVERY listed target, follow only those exact targets and retain selected URLs with minimized dated response metadata.": "Tam başlangıç URL'sini ve listelenen HER hedefi istemek, yalnızca bu tam hedefleri takip etmek ve seçilen URL'leri asgari tarihli yanıt üst verisiyle saklamak için bağımsız iznim var.",
  "I independently have permission to request this exact public plaintext HTTP response and retain only minimized status and Location syntax, without requesting or following any target or HTTPS counterpart.": "Bu tam genel düz metin HTTP yanıtını istemek ve herhangi bir hedefi veya HTTPS karşılığını istemeden veya takip etmeden yalnızca asgari durum ve Location sözdizimini saklamak için bağımsız iznim var.",
  "I independently have permission to request this exact public first HTTPS response and retain only minimized status and Location metadata, without following its target.": "Bu tam genel ilk HTTPS yanıtını istemek ve hedefini takip etmeden yalnızca asgari durum ve Location üst verisini saklamak için bağımsız iznim var.",
  "I independently have permission to request and transiently interpret this exact public HTML body and retain only minimized static resource-reference observations.": "Bu tam genel HTML gövdesini istemek ve geçici yorumlamak, yalnızca asgari statik kaynak başvurusu gözlemlerini saklamak için bağımsız iznim var.",
  "I independently have permission to request this exact origin handshake and retain its minimized certificate-date and negotiated TLS observations.": "Bu tam köken el sıkışmasını istemek ve asgari sertifika tarihi ve müzakere edilen TLS gözlemlerini saklamak için bağımsız iznim var.",
  "I explicitly have permission to request this exact public response and retain its minimized header observations.": "Bu tam genel yanıtı istemek ve asgari başlık gözlemlerini saklamak için açık iznim var.",
  "URL": "URL",
  "bounded chain": "sınırlı zincir",
  "Unauthenticated plaintext HTTP": "Kimliği doğrulanmamış düz metin HTTP",
  "Separately default-validated HTTPS": "Ayrı varsayılan doğrulanmış HTTPS",
  "chain-fact": "zincir olgusu",
  "Location-fact": "Location olgusu",
  "TLS-fact": "TLS olgusu",
  "literal resource-fact": "gerçek kaynak olgusu",
  "header-fact": "başlık olgusu",
  "Choose an authorized exact organization and project.": "Yetkili tam kuruluş ve proje seçin.",
  "Separate saved HTTPS history/current scope unavailable. No collection requested.": "Ayrı kaydedilmiş HTTPS geçmişi/güncel kapsam kullanılamıyor. Toplama istenmedi.",
  "Original independent pair/current source or saved metadata unavailable. Missing is not zero or a security verdict. Refresh and choose again.": "Özgün bağımsız çift/güncel kaynak veya kaydedilmiş üst veri kullanılamıyor. Eksiklik sıfır veya güvenlik hükmü değildir. Yenileyip tekrar seçin.",
  "Current owner/admin source and private history are unavailable.": "Güncel sahip/yönetici kaynağı ve özel geçmiş kullanılamıyor.",
  "Exact current verified source, explicit permission or collection allowance unavailable. No command sent.": "Tam güncel doğrulanmış kaynak, açık izin veya toplama hakkı kullanılamıyor. Komut gönderilmedi.",
  "Exact command acknowledged. Refresh metadata or deliberately inspect private evidence.": "Tam komut alındı. Üst veriyi yenileyin veya özel kanıtı bilinçli inceleyin.",
  "Command outcome uncertain. Look up the exact original command; no automatic replay.": "Komut sonucu belirsiz. Tam özgün komutu arayın; otomatik yeniden oynatma yoktur.",
  "Current source changed. No collection command sent; preview again.": "Güncel kaynak değişti. Toplama komutu gönderilmedi; yeniden önizleyin.",
  "No saved own-actor request at this lookup; the original outcome remains unknown. No replay.": "Bu aramada kendi aktörünüze ait kaydedilmiş istek yok; özgün sonuç bilinmiyor. Yeniden oynatma yoktur.",
  "No saved own-actor request at this lookup. Retry requires a fresh unchanged exact source.": "Bu aramada kendi aktörünüze ait kaydedilmiş istek yok. Yeniden deneme yeni değişmemiş tam kaynak gerektirir.",
  "Exact original command reconciled; no command replayed.": "Tam özgün komut uzlaştırıldı; komut yeniden oynatılmadı.",
  "Current lookup denied or changed; local uncertainty cleared. A saved job may exist. No replay.": "Güncel arama reddedildi veya değişti; yerel belirsizlik temizlendi. Kaydedilmiş iş olabilir. Yeniden oynatma yoktur.",
  "Exact current lookup unavailable; command remains uncertain.": "Tam güncel arama kullanılamıyor; komut belirsiz kalır.",
  "Local uncertainty discarded; a saved job may exist. No command replayed.": "Yerel belirsizlik atıldı; kaydedilmiş iş olabilir. Komut yeniden oynatılmadı.",
  "Exact private evidence/current source unavailable. Missing is not zero findings.": "Tam özel kanıt/güncel kaynak kullanılamıyor. Eksiklik sıfır bulgu değildir.",
  "Original header review candidates/current source unavailable. Missing is not zero candidates.": "Özgün başlık inceleme adayları/güncel kaynak kullanılamıyor. Eksiklik sıfır aday değildir.",
  "Original resource review candidates/current source unavailable. Missing is not zero candidates.": "Özgün kaynak inceleme adayları/güncel kaynak kullanılamıyor. Eksiklik sıfır aday değildir.",
  "Original TLS review candidates/current source unavailable. Missing is not zero candidates.": "Özgün TLS inceleme adayları/güncel kaynak kullanılamıyor. Eksiklik sıfır aday değildir.",
  "Original Location review candidates/current source unavailable. Missing is not zero candidates.": "Özgün Location inceleme adayları/güncel kaynak kullanılamıyor. Eksiklik sıfır aday değildir.",
  "Original chain candidates/current every-origin source or saved metadata unavailable. Missing is not zero candidates. Refresh and choose again.": "Özgün zincir adayları/güncel her köken kaynağı veya kaydedilmiş üst veri kullanılamıyor. Eksiklik sıfır aday değildir. Yenileyip tekrar seçin.",
  "Current role, ownership or project scope unavailable. Original facts and local uncertainty cleared; stored facts may still exist. No replay.": "Güncel rol, sahiplik veya proje kapsamı kullanılamıyor. Özgün olgular ve yerel belirsizlik temizlendi; saklanan olgular hâlâ olabilir. Yeniden oynatma yoktur.",
  "Current original findings/source unavailable. Missing is not zero or a confirmed no-op.": "Güncel özgün bulgular/kaynak kullanılamıyor. Eksiklik sıfır veya doğrulanmış etkisiz işlem değildir.",
  "Current original source/authority unavailable. No fact-save command sent; inspect again.": "Güncel özgün kaynak/yetki kullanılamıyor. Olgu kaydetme komutu gönderilmedi; tekrar inceleyin.",
  "Current original source/authority denied the save. Inspect again; no automatic replay.": "Güncel özgün kaynak/yetki kaydetmeyi reddetti. Tekrar inceleyin; otomatik yeniden oynatma yoktur.",
  "The complete original fact set is currently retained; no personal attribution, human priority or site action is implied.": "Eksiksiz özgün olgu kümesi şu anda saklanıyor; kişisel atıf, insan önceliği veya site eylemi ima edilmez.",
  "Original fact-save outcome uncertain. Read the same job/set; no automatic POST replay.": "Özgün olgu kaydetme sonucu belirsiz. Aynı işi/kümeyi okuyun; otomatik POST yeniden oynatma yoktur.",
  "Current original source or role changed. No fact-save command sent; inspect again.": "Güncel özgün kaynak veya rol değişti. Olgu kaydetme komutu gönderilmedi; tekrar inceleyin.",
  "Current same-job source/set unavailable. Local uncertainty cleared; stored facts may still exist. No replay.": "Güncel aynı iş kaynağı/kümesi kullanılamıyor. Yerel belirsizlik temizlendi; saklanan olgular hâlâ olabilir. Yeniden oynatma yoktur.",
  "Current complete original fact set inspected. This does not identify who saved it. No command replayed.": "Güncel eksiksiz özgün olgu kümesi incelendi. Bu kimin kaydettiğini belirlemez. Komut yeniden oynatılmadı.",
  "No retained set at this current read. The earlier save outcome remains uncertain; this is not confirmed no-op or zero eligible candidates. No replay.": "Bu güncel okumada saklanan küme yok. Önceki kaydetme sonucu belirsiz kalır; doğrulanmış etkisiz işlem veya sıfır uygun aday değildir. Yeniden oynatma yoktur.",
  "Original same-job source/set changed or became unavailable. Local uncertainty cleared; stored facts may still exist. No replay.": "Özgün aynı iş kaynağı/kümesi değişti veya kullanılamaz oldu. Yerel belirsizlik temizlendi; saklanan olgular hâlâ olabilir. Yeniden oynatma yoktur.",
  "Current lookup outcome unavailable; original memory-only save remains uncertain. No replay.": "Güncel arama sonucu kullanılamıyor; yalnızca bellekteki özgün kaydetme belirsiz kalır. Yeniden oynatma yoktur.",
  "Local uncertainty discarded. Stored facts may still exist; independently inspect the current original job before another explicit save.": "Yerel belirsizlik atıldı. Saklanan olgular hâlâ olabilir; başka açık kaydetmeden önce güncel özgün işi bağımsız inceleyin.",
  "Current exact fact or human judgment unavailable. Inspect the original job again.": "Güncel tam olgu veya insan yargısı kullanılamıyor. Özgün işi tekrar inceleyin.",
  "Choose bounded human judgments and a nonempty review reason of at most 240 characters.": "Sınırlı insan yargıları ve en fazla 240 karakterlik boş olmayan inceleme gerekçesi seçin.",
  "Current source-bound human judgment inspected. No personal attribution, severity or site approval is implied.": "Güncel kaynağa bağlı insan yargısı incelendi. Kişisel atıf, önem derecesi veya site onayı ima edilmez.",
  "Human judgment command outcome uncertain. Read the same original fact; no automatic POST replay.": "İnsan yargısı komut sonucu belirsiz. Aynı özgün olguyu okuyun; otomatik POST yeniden oynatma yoktur.",
  "Original source, current human revision or authority changed. Local judgment cleared; inspect again. No replay.": "Özgün kaynak, güncel insan revizyonu veya yetki değişti. Yerel yargı temizlendi; tekrar inceleyin. Yeniden oynatma yoktur.",
  "Current retained matching human judgment inspected; this does not identify who saved it. No command replayed.": "Güncel saklanan eşleşen insan yargısı incelendi; bu kimin kaydettiğini belirlemez. Komut yeniden oynatılmadı.",
  "No matching new judgment at this read. The earlier command remains uncertain, not confirmed no-op. No replay.": "Bu okumada eşleşen yeni yargı yok. Önceki komut belirsiz kalır, doğrulanmış etkisiz işlem değildir. Yeniden oynatma yoktur.",
  "A different current human revision requires fresh deliberate inspection and review. Local command cleared; no replay or attribution.": "Farklı güncel insan revizyonu yeni bilinçli inceleme gerektirir. Yerel komut temizlendi; yeniden oynatma veya atıf yoktur.",
  "Original source or current judgment unavailable or changed. Local uncertainty cleared; a stored judgment may exist. No replay.": "Özgün kaynak veya güncel yargı kullanılamıyor veya değişti. Yerel belirsizlik temizlendi; saklanan yargı olabilir. Yeniden oynatma yoktur.",
  "Current lookup unavailable; the original memory-only human command remains uncertain. No replay.": "Güncel arama kullanılamıyor; yalnızca bellekteki özgün insan komutu belirsiz kalır. Yeniden oynatma yoktur.",
  "Local human command discarded. A stored judgment may exist; inspect the original fact before a new deliberate review.": "Yerel insan komutu atıldı. Saklanan yargı olabilir; yeni bilinçli incelemeden önce özgün olguyu inceleyin.",
  "Ownership check queued, not proof of verification. Refresh current state; no check replayed automatically.": "Sahiplik kontrolü kuyruğa alındı, doğrulama kanıtı değildir. Güncel durumu yenileyin; kontrol otomatik yeniden oynatılmadı.",
  "Deploy the once-shown exact file, then explicitly request the ownership check.": "Bir kez gösterilen tam dosyayı yayımlayın, sonra sahiplik kontrolünü açıkça isteyin.",
  "Exact origin verification revoked.": "Tam köken doğrulaması iptal edildi.",
  "Ownership command outcome uncertain or denied. Refresh exact state; no automatic replay. A lost challenge cannot be retrieved; rotate deliberately if needed.": "Sahiplik komut sonucu belirsiz veya reddedildi. Tam durumu yenileyin; otomatik yeniden oynatma yoktur. Kaybolan doğrulama içeriği tekrar getirilemez; gerekirse bilinçli yenileyin.",
  "handshake": "el sıkışması",
  "response": "yanıt",
  "Actually adjacent original HTTPS→HTTP captured hop indices:": "Gerçekte bitişik özgün HTTPS→HTTP yakalanmış adım indeksleri:",
  ". Plaintext HTTP is unauthenticated; this is not current availability or browser behavior.": ". Düz metin HTTP kimliği doğrulanmamıştır; bu güncel kullanılabilirlik veya tarayıcı davranışı değildir.",
  "Original": "Özgün",
  "stopping fact ·": "durma olgusu ·",
  "captured responses · last zero-based hop": "yakalanmış yanıt · son sıfır tabanlı adım",
  ". No stopped target response is implied.": ". Durulan hedeften bir yanıt alındığı ima edilmez.",
  "Original HTTP-scheme Location reference · HTTP": "Özgün HTTP şemalı Location başvurusu · HTTP",
  "· common redirect status:": "· yaygın yönlendirme durumu:",
  "· same-origin:": "· aynı köken:",
  ". This reference was not followed; it does not prove a redirect downgrade.": ". Bu başvuru takip edilmedi; bir yönlendirmede HTTPS'ten HTTP'ye geçişi kanıtlamaz.",
  "Actual original negotiated version:": "Gerçek özgün müzakere edilen sürüm:",
  ". This is not a supported-protocol inventory or cipher protocol label.": ". Bu desteklenen protokol envanteri veya şifre protokol etiketi değildir.",
  "Reported certificate interval": "Bildirilen sertifika aralığı",
  "to": "ile",
  ". This is an original reported-date fact, not current certificate validation.": ". Bu özgün bildirilen tarih olgusudur, güncel sertifika doğrulaması değildir.",
  "explicit HTTP references among": "açık HTTP başvurusu; incelenen seçili öznitelik sayısı:",
  "inspected selected attributes;": ";",
  "explicit HTTPS and": "açık HTTPS ve",
  "unclassified references. These counts do not prove browser requests or mixed-content policy.": "sınıflandırılmamış başvuru. Bu sayılar tarayıcı isteklerini veya karma içerik politikasını kanıtlamaz.",
  "absent in this response": "bu yanıtta yok",
  "one empty field": "tek boş alan",
  "one nonempty disclosure field": "tek boş olmayan bilgi ifşa alanı",
  "; report-only CSP:": "; yalnızca raporlayan CSP:",
  "of": "/",
  "parsed public cookie fields without": "ayrıştırılmış herkese açık çerez alanında bulunmayan bayrak:",
  "recognized SameSite": "tanınan SameSite",
  "unclassified fields excluded.": "sınıflandırılmamış alan dışlandı.",
  "Unreviewed Turkish passive-observation interface draft in local development. Original evidence values remain unchanged; human review reasons retain their original language. Bilingual approval and wider product coverage are pending.": "Yerel geliştirmede incelenmemiş Türkçe pasif gözlem arayüzü taslağı. Özgün kanıt değerleri değişmeden kalır; insan inceleme gerekçeleri özgün dillerini korur. İki dilli onay ve ürünün daha geniş dil kapsamı bekleniyor."
};

@Component({
  selector: 'app-passive-headers', imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="headers-title">
      <h1 id="headers-title">{{ chain ? t("Exact permitted redirect-chain observations") : httpRedirects ? t("Exact plaintext HTTP Location metadata") : redirects ? t("Exact first-response Location metadata") : resources ? t("Exact static resource-reference candidates") : tls ? t("Exact certificate-date and negotiated TLS observations") : t("Exact public response-header observations") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish passive-observation interface draft in local development. Original evidence values remain unchanged; human review reasons retain their original language. Bilingual approval and wider product coverage are pending.") }}</p> }
      <p>{{ t("Organization") }} <span lang="en">{{ organizationId }}</span> {{ t("· project") }} <span lang="en">{{ projectId }}</span> · <a [routerLink]="['/app/dashboard', organizationId, projectId]">{{ t("Project evidence") }}</a></p>
      @if (chain) {
        <p>{{ t("Owner/admin only. Independently configure and verify EVERY selected HTTP or HTTPS origin, including targets never visited. Separately permit one exact initial URL and zero–five distinct exact target URLs. The allowlist is permission, not a predicted chain. Follow only fresh single Location references matching those exact URLs, at most five redirects and six header-only responses. Stop before unknown, unsupported, outside-allowlist, loop or budget targets. No bodies, probes, cookies, browser execution, active scanning or automatic schedule. HTTPS uses default hostname and chain validation; plaintext HTTP is unauthenticated. Failed TLS is never retried without validation.") }}</p>
      } @else if (httpRedirects) {
        <p>{{ t("Owner/admin only. One independently configured and verified exact HTTP first response with separate permission. HTTP is unauthenticated plaintext, not authenticated server identity. HTTPS verification never authorizes its HTTP counterpart. Only original status, Location cardinality and syntactic scheme, same-origin and same-host default-HTTPS reference metadata are retained. No body reading, target lookup or follow, HTTPS counterpart request, browser execution, active scanning or automatic schedule. A syntactic HTTPS reference is not observed HTTPS availability, a followed upgrade, browser behavior, target permission or a secure verdict.") }}</p>
      } @else if (redirects) {
        <p>{{ t("Owner/admin only. One independently permitted exact HTTPS first response, using default hostname and chain validation. No body reading, Location target lookup or follow, HTTP upgrade probe, browser execution, active scanning or automatic schedule. Only original status, Location field cardinality, classified HTTP/HTTPS scheme and syntactic same-origin metadata are retained. Classification is not target eligibility, a followed chain, HTTPS upgrade behavior, browser behavior, security severity or a whole-site result.") }}</p>
      } @else if (resources) {
        <p>{{ t("Owner/admin only. One independently permitted exact HTTPS URL and one bounded complete UTF-8 HTML response, interpreted transiently. Default hostname and chain validation; no redirects, subresource requests, browser execution, active scanning or automatic schedule. Only literal script/src, iframe/src, img/src and stylesheet/preload/modulepreload link/href candidates are counted. Navigation, CSS, srcset, JavaScript, dynamic and media references, inert/raw-text and foreign descendants are excluded. These are not browser requests, browser mixed-content policy, whole-page security, vulnerability proof or a score.") }}</p>
      } @else if (tls) {
        <p>{{ t("Owner/admin only. One separately permitted exact HTTPS-origin handshake using default hostname and chain validation. No HTTP requests, redirects, protocol inventory, cipher probing, active scanning or automatic schedule. Expired, untrusted or mismatched certificates fail categorically; TLS is never relaxed to inspect them. Negotiated parameters are not the whole configuration, revocation status, server identity proof or exploitability.") }}</p>
      } @else { <p>{{ t("Owner/admin only. One explicitly permitted HTTPS response; no redirects followed, HTTP probes, body reading, login cookies, active scanning or automatic schedule. Presence is not policy effectiveness, certificate/TLS configuration, redirect behavior, whole-site security or exploitability.") }}</p>
      }
      <p>{{ t("One internal operation unit is reserved. An attempted or uncertain request consumes it; this is not a provider charge.") }}
        {{ chain ? t("Only explicitly selected URLs, original dated response status and minimized Location syntax are retained, never raw Location values, headers, bodies or their digests.") : redirects || httpRedirects ? t("Raw Location values, target URLs, headers, bodies and their digests are not retained.") : resources ? t("Raw HTML, resource URLs, headers and their digests are not retained.") : tls ? t("Raw certificates, identities, certificate links and their digests are not retained.") : t("Raw cookies, policies, server values and body are not retained.") }} {{ t("Minimized private evidence follows export/closure policy: 90-day retained access after lapse, active deletion within 30 days of closure/expiry, up to 35-day backup rotation after active deletion.") }}</p>
      @if (busy()) { <p role="status">{{ t("Checking exact current source and private state.") }}</p> }
      @if (error()) { <p role="alert">{{ t(error()) }}</p> }
      @if (message()) { <p role="status">{{ t(message()) }}</p> }
      <button type="button" (click)="load()" [disabled]="busy() || !!pending() || !!priorityPending()">{{ t("Refresh current ownership and private history") }}</button>
      @if (ready()) {
        <fieldset class="observation-controls" [disabled]="!!priorityPending()"><legend>{{ t("Existing ownership, observations and original facts") }}</legend>
        <h2>{{ t("Exact-origin HTTP-file ownership") }}</h2>
        <label for="header-origin">{{ t("Configured") }} {{ chain ? t("HTTP or HTTPS") : httpRedirects ? t("HTTP") : t("HTTPS") }} {{ t("origin") }}</label>
        <select id="header-origin" [value]="origin()" (change)="editOrigin($any($event.target).value)" [disabled]="busy() || !!pending()">
          <option value="">{{ t("Choose exact origin") }}</option>@for (item of selectableOrigins; track item) { <option lang="en" [value]="item">{{ item }}</option> }
        </select>
        <p>{{ t("Creating or rotating a challenge removes prior verification for this origin. Deploy the exact plain-text file yourself; the application never deploys it.") }}</p>
        <button type="button" (click)="createChallenge()" [disabled]="busy() || !!pending() || !origin()">{{ t("Create or rotate exact HTTP-file challenge") }}</button>
        @if (challenge(); as item) {
          <p>{{ t("Shown once, only in this page's memory. Place these exact contents at") }} <span lang="en">{{ item.origin }}</span><span lang="en">{{ challengePath }}</span> {{ t("with HTTP 200 and no redirect.") }}</p>
          <pre lang="en"><span lang="en">{{ item.content }}</span></pre>
        }
        <ul>@for (row of verifications(); track row.id) {
          <li><span lang="en">{{ row.origin }}</span> · <span lang="en">{{ row.state }}</span> {{ t("· original verification") }} <span [attr.lang]="row.verified_at ? 'en' : uiLanguage()">{{ row.verified_at || t("not verified") }}</span> {{ t("· updated") }} <span lang="en">{{ row.updated_at }}</span>
            @if (row.state === 'pending' && selectableOrigins.includes(row.origin)) {
              <button type="button" (click)="verify(row)" [disabled]="busy() || !!pending()">{{ t("I deployed the file; request exact ownership check") }}</button>
            }
            @if (row.state !== 'revoked') { <button type="button" (click)="revoke(row)" [disabled]="busy() || !!pending()">{{ t("Revoke this exact origin") }}</button> }
          </li>
        }</ul>
        @if (!verifications().length) { <p>{{ t("No retained ownership record. No verified source is implied.") }}</p> }
        @if (verificationsMore()) { <p>{{ t("Only the first 100 ownership records are shown.") }}</p> }
        <h2>{{ chain ? t("Separate deliberate exact-chain permission") : httpRedirects ? t("Separate deliberate HTTP Location permission") : redirects ? t("Separate deliberate Location permission") : resources ? t("Separate deliberate static-resource permission") : tls ? t("Separate deliberate certificate/TLS permission") : t("Separate deliberate header permission") }}</h2>
        <form (submit)="preview($event)"><fieldset [disabled]="busy() || !!pending()"><legend>{{ chain ? t("Exact initial URL and independently permitted targets · redirect_chain only") : httpRedirects ? t("One exact HTTP URL · http_response_location only") : redirects ? t("One exact HTTPS URL · response_location only") : resources ? t("One exact HTTPS URL · static_resource_references only") : tls ? t("One exact HTTPS origin · certificate_dates and negotiated_tls only") : t("One exact HTTPS URL · response_headers only") }}</legend>
          @if (tls) { <p>{{ t("Selected exact origin:") }} <span [attr.lang]="origin() ? 'en' : uiLanguage()">{{ origin() || t("Choose a configured origin above") }}</span>{{ t(". Header permission does not authorize a TLS observation.") }}</p> }
          @else {
          <label for="header-url">{{ t("Canonical") }} {{ chain ? t("initial HTTP or HTTPS") : httpRedirects ? t("HTTP") : t("HTTPS") }} {{ t("URL without query, fragment, credentials or custom port") }}</label>
          <input lang="en" id="header-url" name="url" type="url" required maxlength="1024" [value]="url()" (input)="editUrl($any($event.target).value)" />
          @if (resources) { <p>{{ t("Header or TLS permission does not authorize this separate transient-body observation.") }}</p> }
          @if (redirects) { <p>{{ t("Header, TLS or resource permission does not authorize this separate first-response Location observation.") }}</p> }
          @if (httpRedirects) { <p>{{ t("HTTPS Location, header, TLS or resource permission does not authorize this separate HTTP observation.") }}</p> }
          @if (chain) {
            <p>{{ t("Every selected origin must be independently configured and verified. Other passive permissions and saved Location syntax grant no chain authority.") }}</p>
            @for (target of targetUrls(); track $index) {
              <label [for]="'chain-target-' + $index">{{ t("Exact permitted target URL") }} <span lang="en">{{ $index + 1 }}</span></label>
              <input lang="en" [id]="'chain-target-' + $index" [name]="'target-' + $index" type="url" required maxlength="1024" [value]="target" (input)="editTarget($index, $any($event.target).value)" />
              <button type="button" (click)="removeTarget($index)">{{ t("Remove target") }} <span lang="en">{{ $index + 1 }}</span></button>
            }
            <button type="button" (click)="addTarget()" [disabled]="targetUrls().length >= 5">{{ t("Add independently permitted exact target (maximum 5)") }}</button>
          }
          }
          <label><input name="permission" type="checkbox" [checked]="permission()" (change)="editPermission($any($event.target).checked)" required />
            {{ chain ? t("I independently have permission to request the exact initial URL and EVERY listed target, follow only those exact targets and retain selected URLs with minimized dated response metadata.") : httpRedirects ? t("I independently have permission to request this exact public plaintext HTTP response and retain only minimized status and Location syntax, without requesting or following any target or HTTPS counterpart.") : redirects ? t("I independently have permission to request this exact public first HTTPS response and retain only minimized status and Location metadata, without following its target.") : resources ? t("I independently have permission to request and transiently interpret this exact public HTML body and retain only minimized static resource-reference observations.") : tls ? t("I independently have permission to request this exact origin handshake and retain its minimized certificate-date and negotiated TLS observations.") : t("I explicitly have permission to request this exact public response and retain its minimized header observations.") }}</label>
          <button type="submit">{{ t("Preview exact current verified source (no site request)") }}</button>
        </fieldset></form>
        @if (selection(); as info) {
          <p>{{ t("Exact") }} {{ tls ? t("origin") : t("URL") }} <span lang="en">{{ info.selection.binding[tls ? 'origin' : 'url'] }}</span>.</p>
          @if (chain) { <p>{{ t("All original selected origins and verification dates are in the frozen binding, including targets that may never be visited.") }}</p> }
          @else { <p>{{ t("Verification") }} <span lang="en">{{ info.selection.binding['verification_id'] }}</span> {{ t("· original date") }} <span lang="en">{{ info.selection.binding['verified_at'] }}</span>.</p> }
          <details><summary>{{ t("Frozen original source binding and selection digest") }}</summary><pre lang="en"><span lang="en">{{ json(info) }}</span></pre></details>
          <button type="button" (click)="launch()" [disabled]="busy() || !!pending()">{{ t("Reserve 1 unit and request this exact") }} {{ chain ? t("bounded chain") : tls ? t("handshake") : t("response") }}</button>
        }
        @if (pending()) {
          <p>{{ t("The exact command outcome is uncertain. Binding and request key are frozen in component memory. No automatic replay.") }}</p>
          <button type="button" (click)="reconcile()" [disabled]="busy()">{{ t("Look up exact original command") }}</button>
          @if (!getOnlyUncertainty && notFound() && !pending()!.jobId) { <button type="button" (click)="retry()" [disabled]="busy()">{{ t("Deliberately retry same command after fresh source check") }}</button> }
          @if (getOnlyUncertainty) { <button type="button" (click)="discardHttpCommand()" [disabled]="busy()">{{ t("Discard local uncertainty; a saved job may exist") }}</button> }
        }
        <h2>{{ t("Private") }} <span lang="en">{{ family }}</span>{{ t("-job metadata") }}</h2>
        @if (!jobs().length) { <p>{{ t("No retained") }} <span lang="en">{{ family }}</span> {{ t("jobs. Missing is not a clean security result.") }}</p> }
        @if (hasMore()) { <p>{{ t("Only the latest 20 jobs are shown.") }}</p> }
        <ul>@for (job of jobs(); track job.id) {
          <li>{{ t("Job") }} <span lang="en">{{ job.id }}</span> · <span lang="en">{{ job.status }}</span> {{ t("· created") }} <span lang="en">{{ job.created_at }}</span> {{ t("· updated") }} <span lang="en">{{ job.updated_at }}</span> · <span lang="en">{{ job.error_category }}</span>
            <button type="button" (click)="inspect(job.id)" [disabled]="busy() || !!pending()">{{ t("Inspect exact private job") }}</button>
            @if (family === 'headers' && job.status === 'succeeded' && !job.cancel_requested) {
              <button type="button" (click)="inspectCandidates(job.id)" [disabled]="busy() || !!pending()">{{ t("Inspect original header review candidates") }}</button>
              <button type="button" (click)="inspectFindings(job.id)" [disabled]="busy() || !!pending() || !!findingPending()">{{ t("Inspect current original header findings (no save)") }}</button>
            }
            @if (resources && job.status === 'succeeded' && !job.cancel_requested) {
              <button type="button" (click)="inspectResourceCandidates(job.id)" [disabled]="busy() || !!pending()">{{ t("Inspect original literal HTTP resource review candidate") }}</button>
              <button type="button" (click)="inspectFindings(job.id)" [disabled]="busy() || !!pending() || !!findingPending()">{{ t("Inspect current original resource findings (no save)") }}</button>
            }
            @if (tls && job.status === 'succeeded' && !job.cancel_requested) {
              <button type="button" (click)="inspectTlsCandidates(job.id)" [disabled]="busy() || !!pending()">{{ t("Inspect original certificate-date and negotiated-version review candidates") }}</button>
              <button type="button" (click)="inspectFindings(job.id)" [disabled]="busy() || !!pending() || !!findingPending()">{{ t("Inspect current original TLS findings (no save)") }}</button>
            }
            @if (redirects && job.status === 'succeeded' && !job.cancel_requested) {
              <button type="button" (click)="inspectRedirectCandidates(job.id)" [disabled]="busy() || !!pending()">{{ t("Inspect original HTTP-scheme Location review candidate") }}</button>
              <button type="button" (click)="inspectFindings(job.id)" [disabled]="busy() || !!pending() || !!findingPending()">{{ t("Inspect current original Location findings (no save)") }}</button>
            }
            @if (chain && job.status === 'succeeded' && !job.cancel_requested && job.error_category === '') {
              <button type="button" (click)="inspectChainCandidates(job.id)" [disabled]="busy() || !!pending()">{{ t("Inspect original chain transition and stop review candidates") }}</button>
              <button type="button" (click)="inspectFindings(job.id)" [disabled]="busy() || !!pending() || !!findingPending()">{{ t("Inspect current original chain findings (no save)") }}</button>
            }
            @if (['queued', 'running'].includes(job.status) && !job.cancel_requested) {
              <button type="button" (click)="cancel(job.id)" [disabled]="busy() || !!pending()">{{ t("Request cancellation") }}</button>
            }
          </li>
        }</ul>
        @if (httpRedirects) {
          <h2>{{ t("Two independently saved original HTTP and HTTPS responses") }}</h2>
          <p>{{ t("Choose two retained succeeded jobs deliberately. Reading a pair makes no site request or new unit reservation. The source URLs must have the same host, default ports and exact source path. Either capture order is allowed. Minimized HTTP Location syntax cannot reveal its target path or prove that the selected HTTPS URL was followed.") }}</p>
          <button type="button" (click)="refreshHttpsHistory()" [disabled]="busy() || !!pending()">{{ t("Refresh separately saved HTTPS Location history (no collection)") }}</button>
          @if (httpsHasMore()) { <p>{{ t("Only the latest 20 HTTPS jobs are shown.") }}</p> }
          <form (submit)="compareResponses($event)"><fieldset [disabled]="busy() || !!pending()"><legend>{{ t("Explicit independent saved-job pair") }}</legend>
            <label for="pair-http-job">{{ t("Original plaintext HTTP job") }}</label>
            <select id="pair-http-job" [value]="pairHttpId()" (change)="choosePairJob('http', $any($event.target).value)">
              <option value="0">{{ t("Choose saved succeeded HTTP job") }}</option>
              @for (job of pairJobs('http'); track job.id) { <option [attr.lang]="uiLanguage()" [value]="job.id">{{ t("Job") }} {{ job.id }} {{ t("· created") }} {{ job.created_at }} {{ t("· updated") }} {{ job.updated_at }}</option> }
            </select>
            <label for="pair-https-job">{{ t("Separately collected default-validated HTTPS job") }}</label>
            <select id="pair-https-job" [value]="pairHttpsId()" (change)="choosePairJob('https', $any($event.target).value)">
              <option value="0">{{ t("Choose saved succeeded HTTPS job") }}</option>
              @for (job of pairJobs('https'); track job.id) { <option [attr.lang]="uiLanguage()" [value]="job.id">{{ t("Job") }} {{ job.id }} {{ t("· created") }} {{ job.created_at }} {{ t("· updated") }} {{ job.updated_at }}</option> }
            </select>
            <button type="submit" [disabled]="!pairHttpId() || !pairHttpsId() || pairHttpId() === pairHttpsId()">{{ t("Read these two original saved responses") }}</button>
          </fieldset></form>
          @if (responsePair(); as pair) {
            <h3>{{ t("Separate original dated responses · no followed upgrade or current availability claim") }}</h3>
            @for (scheme of ['http', 'https']; track scheme) {
              <h4>{{ scheme === 'http' ? t("Unauthenticated plaintext HTTP") : t("Separately default-validated HTTPS") }} {{ t("· original job") }} <span lang="en">{{ $any(pair[scheme])['job_id'] }}</span></h4>
              <p>{{ t("Original actor") }} <span lang="en">{{ $any(pair[scheme])['binding']['actor_id'] }}</span> {{ t("· independent verification") }} <span lang="en">{{ $any(pair[scheme])['binding']['verification_id'] }}</span>
                {{ t("at") }} <span lang="en">{{ $any(pair[scheme])['binding']['verified_at'] }}</span> {{ t("· capture") }} <span lang="en">{{ $any(pair[scheme])['collection']['observed_at'] }}</span>
                {{ t("· response status") }} <span lang="en">{{ $any(pair[scheme])['collection']['status'] }}</span>.</p>
              <pre lang="en"><span lang="en">{{ json(pair[scheme]) }}</span></pre>
            }
            <p>{{ t("These are two separate dated observations, not a chain or before/after causal result. No current HTTPS availability, authenticated HTTP identity, browser behavior, target permission or security verdict is established. Absent, empty, multiple or unclassified Location metadata remains null, not zero or a clean result. No raw Location target/path or target link is available. A failed or unavailable job cannot form an observed pair.") }}</p>
          }
        }
        @if (selected(); as job) {
          <h3>{{ t("Exact job") }} <span lang="en">{{ job.id }}</span> · <span lang="en">{{ job.status }}</span></h3>
          @if (evidence(); as item) { <pre lang="en"><span lang="en">{{ json(item) }}</span></pre>
            @if (chain) { <p>{{ t("Original selected response URLs, UTC microseconds, status and stop coverage are preserved. Only captured hops were observed; selected UNVISITED targets remain permissions, not observations. Unknown Location metadata remains null. Loop, budget, unsupported and outside-allowlist stops do not establish the target path from minimized syntax. No current availability, browser behavior, authenticated HTTP identity, security verdict, Finding or report authority is established. No raw target link is available.") }}</p> }
            @else if (httpRedirects) { <p>{{ t("Original local UTC microseconds and plaintext response status are preserved, not authenticated server identity. Common redirect status is independent of Location syntax. A same-host default-HTTPS reference is syntactic only, not observed HTTPS availability or a followed upgrade. Absent, empty, multiple and unclassified fields keep scheme, same-origin and counterpart metadata null. Null is not zero or a secure verdict. No raw target link or current target permission is available.") }}</p> }
            @else if (redirects) { <p>{{ t("Original UTC microseconds and response status are preserved. Common redirect status does not prove a followed redirect. Absent, empty, multiple and single-unclassified Location fields remain distinct; all target metadata is null unless classified. Same origin means only the original scheme, host and effective port; it supplies no target permission or DNS evidence. Null is not zero, secure or a clean result. No raw target link is available.") }}</p> }
            @else if (resources) { <p>{{ t("Original UTC microseconds are preserved. Counts are bounded literal candidates in selected attributes only, not browser requests or whole-page mixed-content proof. Unclassified is not insecure or secure. Lexically unavailable evidence keeps all counts null; null is not zero or a clean result.") }}</p> }
            @else if (tls) { <p>{{ t("Original UTC microseconds are preserved. Certificate dates use inclusive original reported bounds; remaining_microseconds is an exact signed decimal string, not rounded days or a warning threshold. Null/unavailable is not zero or a secure verdict. Only the negotiated version and cipher are shown, not all supported configuration or revocation evidence.") }}</p> }
            @else { <p>{{ t("Cookie counts concern explicitly parsed fields in this one response. Unsupported fields remain unclassified, not insecure or secure verdicts.") }}</p> }
          } @else { <p>{{ t("No current private observation available. Failed, cancelled, unknown or uncollected is not zero findings.") }}</p> }
        }
        @if (candidateReport(); as report) {
          @if (chain && report['method_version'] === 'passive-redirect-chain-candidates-v1') {
            <h2>{{ t("Original chain transition and stop review candidates · job") }} <span lang="en">{{ report['job_id'] }}</span></h2>
            <p>{{ t("Originally selected URLs:") }} <span lang="en">{{ $any(report['availability'])['selected_urls'] }}</span> {{ t("· actually captured responses:") }} <span lang="en">{{ $any(report['availability'])['observed_hops'] }}</span>
              {{ t("· last target syntax:") }} <span lang="en">{{ $any(report['availability'])['last_target_metadata'] }}</span> {{ t("· original stop:") }} <span lang="en">{{ $any(report['collection'])['evidence']['state'] }}</span>.</p>
            <p>{{ t("Original first capture") }} <span lang="en">{{ $any(report['collection'])['observed_at'] }}</span> {{ t("· last capture") }} <span lang="en">{{ $any(report['collection'])['last_observed_at'] }}</span>{{ t(". Hop indices are zero-based; dates and status remain in the original collection below. Selected UNVISITED targets are permissions, not observations.") }}</p>
            <ul>@for (item of candidateRows(); track item.detector) { <li><span [attr.lang]="uiLanguage()">{{ candidateText(item) }}</span></li> }</ul>
            @if (!candidateRows().length) { <p>{{ t("No eligible transition or loop/budget-stop candidates in these original captured responses. This is not a clean, secure or whole-site result.") }}</p> }
            @if ($any(report['availability'])['last_target_metadata'] === 'unavailable') { <p>{{ t("Last target syntax is unknown; scheme and same-origin remain null, not zero or a secure verdict.") }}</p> }
            <p>{{ t("A stopped loop is not a repeated response; a budget stop is incomplete coverage, not a broken destination. Unknown, unsupported and outside-allowlist targets were not followed. Minimized syntax cannot reconstruct raw Location target paths. No current availability, browser behavior, authenticated HTTP identity, severity, approval or target authority is established. Inspection makes no site request, new unit reservation, Finding save, human prioritization or general report/share grant. No raw target link is available.") }}</p>
            <details><summary>{{ t("Full original selected binding, dated response status, index facts, availability and stop coverage") }}</summary><pre lang="en"><span lang="en">{{ json(report) }}</span></pre></details>
            <button type="button" (click)="saveFindings()" [disabled]="busy() || !!pending() || !!findingPending() || !candidateRows().length">{{ t("Explicitly save these original chain facts") }}</button>
            <p>{{ t("Saving existing facts makes no site request, target follow or new unit reservation, human priority, approval or general report/share availability.") }}</p>
          } @else if (redirects && report['method_version'] === 'passive-redirect-candidates-v1') {
            <h2>{{ t("Original Location review candidates · job") }} <span lang="en">{{ report['job_id'] }}</span></h2>
            <p>{{ t("Original observation") }} <span lang="en">{{ $any(report['collection'])['observed_at'] }}</span> {{ t("· HTTP") }} <span lang="en">{{ $any(report['collection'])['status'] }}</span>{{ t(". Target metadata:") }} <span lang="en">{{ $any(report['availability'])['target_metadata'] }}</span> {{ t("· Location fields:") }} <span lang="en">{{ $any(report['collection'])['evidence']['response_location']['location_state'] }}</span>.</p>
            @if ($any(report['availability'])['target_metadata'] === 'unavailable') {
              <p>{{ t("Original target metadata unknown. Target scheme and same-origin remain null; absent, empty, multiple or unclassified fields are not zero candidates or a secure verdict.") }}</p>
            } @else {
              <ul>@for (item of candidateRows(); track item.detector) { <li><span [attr.lang]="uiLanguage()">{{ candidateText(item) }}</span></li> }</ul>
              @if (!candidateRows().length) { <p>{{ t("Original classified HTTPS reference has no eligible HTTP-scheme candidate. This is not a secure or whole-site result.") }}</p> }
            }
            <p>{{ t("A common redirect status is a literal original status flag, not proof of followed redirection, downgrade, HTTPS upgrade, browser behavior, severity or target authority. Same-origin is only a syntactic scheme, host and effective-port comparison. No raw target link is available. Inspection makes no site request, new unit reservation, Finding save or human prioritization.") }}</p>
            <details><summary>{{ t("Original minimized binding, date, status, classification, availability and coverage") }}</summary><pre lang="en"><span lang="en">{{ json(report) }}</span></pre></details>
            <button type="button" (click)="saveFindings()" [disabled]="busy() || !!pending() || !!findingPending() || !candidateRows().length">{{ t("Explicitly save this original Location fact") }}</button>
            <p>{{ t("Saving existing facts makes no site request, target lookup/follow or new unit reservation, human priority, approval or general report/share availability.") }}</p>
          } @else if (tls && report['method_version'] === 'passive-tls-candidates-v1') {
            <h2>{{ t("Original certificate-date and negotiated-version review candidates · job") }} <span lang="en">{{ report['job_id'] }}</span></h2>
            <p>{{ t("Original observation") }} <span lang="en">{{ $any(report['collection'])['observed_at'] }}</span> {{ t("· exact origin") }} <span lang="en">{{ $any(report['collection'])['origin'] }}</span>{{ t(". Dated literal facts only, not supported server configuration, revocation, browser behavior, severity, approval or exploitability.") }}</p>
            <p>{{ t("Certificate dates:") }} <span lang="en">{{ $any(report['availability'])['certificate_dates'] }}</span> {{ t("· actual negotiated version:") }} <span lang="en">{{ $any(report['availability'])['negotiated_version'] }}</span>{{ t(". Each unavailable value remains independently unknown, not zero candidates or a secure verdict.") }}</p>
            <ul>@for (item of candidateRows(); track item.detector) { <li><span [attr.lang]="uiLanguage()">{{ candidateText(item) }}</span></li> }</ul>
            @if (!candidateRows().length) { <p>{{ t("No eligible review candidates among the available original date/version observations. Unavailable evidence is still unknown; this is not a clean or whole-site result.") }}</p> }
            <p>{{ t("Reported interval bounds are inclusive; remaining_microseconds is the exact signed decimal string, without rounding or a warning threshold. Cipher metadata is not the actual negotiated version. Inspection makes no site request, handshake, unit reservation, fact save or human prioritization.") }}</p>
            <details><summary>{{ t("Original minimized binding, dates, negotiated parameters, availability and coverage") }}</summary><pre lang="en"><span lang="en">{{ json(report) }}</span></pre></details>
            <button type="button" (click)="saveFindings()" [disabled]="busy() || !!pending() || !!findingPending() || !candidateRows().length">{{ t("Explicitly save these original TLS facts") }}</button>
            <p>{{ t("Saving existing facts makes no handshake, site request or new unit reservation, human priority, approval or general report/share availability.") }}</p>
          } @else if (resources && report['method_version'] === 'passive-resource-candidates-v1') {
            <h2>{{ t("Original literal resource review candidates · job") }} <span lang="en">{{ report['job_id'] }}</span></h2>
            <p>{{ t("Original observation") }} <span lang="en">{{ $any(report['collection'])['observed_at'] }}</span> {{ t("· HTTP") }} <span lang="en">{{ $any(report['collection'])['status'] }}</span>{{ t(". Dated literal facts only, not browser requests, mixed-content policy, severity, approval, whole-page security or a score.") }}</p>
            @if (report['state'] === 'original_lexical_evaluation_unavailable') {
              <p>{{ t("Original lexical evaluation unavailable ·") }} <span lang="en">{{ report['reason'] }}</span>{{ t(". All counts remain null; unavailable is not zero candidates or a clean result.") }}</p>
            } @else {
              <ul>@for (item of candidateRows(); track item.detector) { <li><span [attr.lang]="uiLanguage()">{{ candidateText(item) }}</span></li> }</ul>
              @if (!candidateRows().length) { <p>{{ t("No eligible literal HTTP review candidate in this original selected-attribute observation. Unclassified is not secure or insecure; this is not a clean or whole-page result.") }}</p> }
            }
            <p>{{ t("Only script/src, iframe/src, img/src and stylesheet/preload/modulepreload link/href are selected. Navigation, CSS, srcset, JavaScript, dynamic/media, inert/raw-text and foreign descendants are excluded. Inspection makes no site request, new unit reservation, fact save or human prioritization.") }}</p>
            <details><summary>{{ t("Original minimized binding, date, status, coverage and lexical counts") }}</summary><pre lang="en"><span lang="en">{{ json(report) }}</span></pre></details>
            <button type="button" (click)="saveFindings()" [disabled]="busy() || !!pending() || !!findingPending() || !candidateRows().length">{{ t("Explicitly save this original literal resource fact") }}</button>
            <p>{{ t("Saving existing facts makes no site request or new unit reservation, human priority, approval or general report/share availability.") }}</p>
          } @else if (family === 'headers' && report['method_version'] === 'passive-header-candidates-v1') {
          <h2>{{ t("Original response-header review candidates · job") }} <span lang="en">{{ report['job_id'] }}</span></h2>
          <p>{{ t("These dated facts are review candidates, not severity, approval, policy effectiveness, browser behavior or exploitability. Report-only CSP does not provide enforcement. Multiple fields do not prove invalidity or nonempty policy. Unsupported cookie fields remain unclassified and do not contribute missing-flag counts.") }}</p>
          <ul>@for (item of candidateRows(); track item.detector) { <li><span [attr.lang]="uiLanguage()">{{ candidateText(item) }}</span></li> }</ul>
          @if (!candidateRows().length) { <p>{{ t("No eligible review candidates in this original bounded response. This is not a clean, secure or whole-site result.") }}</p> }
          <details><summary>{{ t("Original minimized source, date, status and candidate facts") }}</summary><pre lang="en"><span lang="en">{{ json(report) }}</span></pre></details>
          <button type="button" (click)="saveFindings()" [disabled]="busy() || !!pending() || !!findingPending() || !candidateRows().length">{{ t("Explicitly save these original header facts") }}</button>
          <p>{{ t("Saving existing facts makes no site request or new unit reservation, human priority, approval or general report/share availability.") }}</p>
          }
        }
        @if (findingInspection(); as info) {
          <h2>{{ t("Current private materialized facts · original job") }} <span lang="en">{{ info.job.id }}</span></h2>
          <p>{{ t("Original candidate SHA256") }} <span lang="en">{{ info.candidateDigest }}</span>{{ t(". Detection time is the materialization date, separate from the original observation.") }}</p>
          @if (info.findingSet['state'] === 'no_retained_materialized_findings') {
            <p>{{ t("No retained materialized findings. This does not mean zero eligible candidates, a clean security result or a confirmed no-op command.") }}</p>
          } @else {
            <p>{{ t("A complete original fact set is currently retained. This does not identify who saved it or assign risk severity.") }}</p>
          }
          <details><summary>{{ t("Original compact finding identities, dates and facts") }}</summary><pre lang="en"><span lang="en">{{ json(info.findingSet) }}</span></pre></details>
          <ul>@for (finding of findingRows(); track finding['id']) {
            <li>{{ t("Finding") }} <span lang="en">{{ finding['id'] }}</span> · <span lang="en">{{ finding['detector'] }}</span> {{ t("· detected") }} <span lang="en">{{ finding['detected_at'] }}</span>
              <button type="button" (click)="inspectPriority($any(finding['id']))" [disabled]="busy() || !!pending() || !!findingPending() || !!priorityPending()">{{ t("Inspect this fact's current human judgment") }}</button>
            </li>
          }</ul>
        }
        </fieldset>
        @if (priorityInspection(); as info) {
          <h3>{{ t("Human judgment · Finding") }} <span lang="en">{{ info.findingId }}</span> {{ t("· original job") }} <span lang="en">{{ info.original.job.id }}</span></h3>
          <p>{{ t("Human priority, effort and business relevance are judgments, not measured risk severity, a recommendation, approval or a page action. No site request or new unit reservation. The opaque source SHA binds hidden server provenance; this browser cannot independently reconstruct it.") }}</p>
          @if (info.judgment['decision']; as decision) {
            <p>{{ t("Current retained judgment · revision") }} <span lang="en">{{ $any(decision)['revision'] }}</span> {{ t("· reviewed") }} <span lang="en">{{ info.judgment['reviewed_at'] }}</span> {{ t("· priority") }} <span lang="en">{{ $any(decision)['priority'] }}</span> {{ t("· effort") }} <span lang="en">{{ $any(decision)['estimated_effort'] }}</span> {{ t("· relevance") }} <span lang="en">{{ $any(decision)['business_relevance'] }}</span>.</p>
            <p><span lang="">{{ $any(decision)['review_reason'] }}</span></p>
          } @else { <p>{{ t("No retained current human judgment. This is distinct from an explicit human unprioritized decision.") }}</p> }
          <details><summary>{{ t("Selected original fact and server source binding") }}</summary><pre lang="en"><span lang="en">{{ json(info.judgment['source']) }}</span></pre></details>
          <form (submit)="savePriority($event)"><fieldset [disabled]="busy() || !!priorityPending() || !priorityCanSave()"><legend>{{ t("Explicit human judgment or correction") }}</legend>
            <label for="passive-priority">{{ t("Human priority") }}</label>
            <select id="passive-priority" [value]="humanPriority()" (change)="editJudgment('priority', $any($event.target).value)">@for (value of priorities; track value) { <option lang="en" [value]="value">{{ value }}</option> }</select>
            <label for="passive-effort">{{ t("Estimated effort") }}</label>
            <select id="passive-effort" [value]="humanEffort()" (change)="editJudgment('estimated_effort', $any($event.target).value)">@for (value of efforts; track value) { <option lang="en" [value]="value">{{ value }}</option> }</select>
            <label for="passive-relevance">{{ t("Business relevance") }}</label>
            <select id="passive-relevance" [value]="humanRelevance()" (change)="editJudgment('business_relevance', $any($event.target).value)">@for (value of relevances; track value) { <option lang="en" [value]="value">{{ value }}</option> }</select>
            <label for="passive-reason">{{ t("Human review reason (required, at most 240 characters)") }}</label>
            <textarea lang="" id="passive-reason" required maxlength="240" [value]="humanReason()" (input)="editJudgment('reason', $any($event.target).value)"></textarea>
            <button type="submit">{{ t("Explicitly save this source-bound human judgment") }}</button>
          </fieldset></form>
          @if (!priorityCanSave()) { <p>{{ t("This judgment has reached the maximum revision; another correction is unavailable.") }}</p> }
        }
        @if (priorityPending()) {
          <p>{{ t("The human judgment command outcome is uncertain. Original job, fact, source SHA, expected revision and fields are frozen only in this page's memory. No automatic POST replay.") }}</p>
          <button type="button" (click)="reconcilePriority()" [disabled]="busy()">{{ t("Read the same fact's current human judgment (no replay)") }}</button>
          <button type="button" (click)="discardPriorityCommand()" [disabled]="busy()">{{ t("Discard local uncertainty; a stored judgment may exist") }}</button>
        }
        @if (findingPending()) {
          <p>{{ t("The original") }} {{ chain ? t("chain-fact") : redirects ? t("Location-fact") : tls ? t("TLS-fact") : resources ? t("literal resource-fact") : t("header-fact") }} {{ t("save outcome is uncertain. Its job, original report and SHA remain frozen only in this page's memory. No automatic POST replay.") }}</p>
          <button type="button" (click)="reconcileFindings()" [disabled]="busy()">{{ t("Read the same original job and current fact set") }}</button>
          <button type="button" (click)="discardFindingCommand()" [disabled]="busy()">{{ t("Discard local uncertainty; stored facts may still exist") }}</button>
        }
      }
    </section>`,
  styles: `fieldset { display: grid; gap: .6rem; max-width: 48rem; margin-block: 1rem; } input, select { min-width: 0; max-width: 100%; }
    fieldset.observation-controls { display: block; border: 0; padding: 0; max-width: none; min-width: 0; }
    pre { white-space: pre-wrap; overflow-wrap: anywhere; } li { margin-block: .8rem; }`,
})
export class PassiveHeaders implements OnInit {
  readonly documentTitle = signal('Private exact response-header observations');
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  t(text: string) { return this.uiLanguage() === 'tr' ? passiveTurkish[text] ?? text : text; }
  readonly ready = signal(false); readonly busy = signal(false); readonly error = signal(''); readonly message = signal('');
  readonly origins = signal<string[]>([]); readonly origin = signal(''); readonly url = signal(''); readonly permission = signal(false);
  readonly targetUrls = signal<string[]>([]);
  readonly verifications = signal<Verification[]>([]); readonly verificationsMore = signal(false);
  readonly challenge = signal<{ origin: string; content: string } | null>(null); readonly challengePath = PATH;
  readonly selection = signal<Preview | null>(null); readonly pending = signal<Pending | null>(null); readonly notFound = signal(false);
  readonly jobs = signal<Job[]>([]); readonly hasMore = signal(false); readonly selected = signal<Job | null>(null); readonly evidence = signal<Row | null>(null);
  readonly httpsJobs = signal<Job[]>([]); readonly httpsHasMore = signal(false);
  readonly pairHttpId = signal(0); readonly pairHttpsId = signal(0); readonly responsePair = signal<Row | null>(null);
  readonly frozenPair = signal<ResponsePair | null>(null);
  readonly candidateReport = signal<Row | null>(null);
  readonly findingInspection = signal<FindingInspection | null>(null); readonly findingPending = signal<FindingInspection | null>(null);
  private chainCandidateJob: Job | null = null;
  readonly priorityInspection = signal<PriorityInspection | null>(null); readonly priorityPending = signal<PriorityPending | null>(null);
  readonly humanPriority = signal('unprioritized'); readonly humanEffort = signal('unknown'); readonly humanRelevance = signal('unknown'); readonly humanReason = signal('');
  readonly priorities = PRIORITIES; readonly efforts = EFFORTS; readonly relevances = RELEVANCES;
  protected organizationId = 0; protected projectId = 0; protected family: 'headers' | 'tls' | 'resources' | 'redirects' | 'http-redirects' | 'redirect-chain' = 'headers'; private epoch = 0;
  protected get tls() { return this.family === 'tls'; }
  protected get resources() { return this.family === 'resources'; }
  protected get redirects() { return this.family === 'redirects'; }
  protected get httpRedirects() { return this.family === 'http-redirects'; }
  protected get chain() { return this.family === 'redirect-chain'; }
  protected get getOnlyUncertainty() { return this.httpRedirects || this.chain; }
  protected get selectableOrigins() { return this.httpRedirects ? this.origins().filter(origin => origin.startsWith('http://')) : this.origins(); }
  private get method() { return this.chain ? CHAIN_METHOD : this.httpRedirects ? HTTP_REDIRECT_METHOD : this.redirects ? REDIRECT_METHOD : this.resources ? RESOURCE_METHOD : this.tls ? TLS_METHOD : METHOD; }
  private get observations() { return this.chain ? ['redirect_chain'] : this.httpRedirects ? ['http_response_location'] : this.redirects ? ['response_location'] : this.resources ? ['static_resource_references'] : this.tls ? ['certificate_dates', 'negotiated_tls'] : ['response_headers']; }
  constructor(private readonly api: AccountApi, private readonly route: ActivatedRoute, private readonly destroyRef: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t(this.documentTitle())} — OrganicSEOOps`));
    destroyRef.onDestroy(() => this.reset());
  }
  ngOnInit() {
    void this.loadProductLanguage();
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(params => {
      // Fixed route data selects independent API commands; no input/query can switch permission families.
      const family = this.route.snapshot.data['passiveObservation'];
      this.family = family === 'tls' || family === 'resources' || family === 'redirects' || family === 'http-redirects' || family === 'redirect-chain' ? family : 'headers';
      this.documentTitle.set(
        this.chain ? 'Private exact permitted redirect chain' :
        this.httpRedirects ? 'Private plaintext HTTP Location metadata' :
        this.redirects ? 'Private exact first-response Location metadata' :
        this.resources ? 'Private exact static resource candidates' :
        this.tls ? 'Private exact TLS handshake observations' :
        'Private exact response-header observations');
      this.reset(); this.organizationId = Number(params.get('organizationId')); this.projectId = Number(params.get('projectId'));
      if (positive(this.organizationId) && positive(this.projectId)) void this.load();
      else this.error.set('Choose an authorized exact organization and project.');
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
  private request(data?: Row, id?: number, key?: string, selection = false) {
    return this.chain ? this.api.passiveRedirectChain(this.organizationId, this.projectId, data, id, key, selection)
      : this.httpRedirects ? this.api.passiveHttpRedirects(this.organizationId, this.projectId, data, id, key, selection)
      : this.redirects ? this.api.passiveRedirects(this.organizationId, this.projectId, data, id, key, selection)
      : this.resources ? this.api.passiveResources(this.organizationId, this.projectId, data, id, key, selection)
      : this.tls ? this.api.passiveTls(this.organizationId, this.projectId, data, id, key, selection)
      : this.api.passiveHeaders(this.organizationId, this.projectId, data, id, key, selection);
  }
  private reset() {
    this.clearFindings();
    ++this.epoch; this.ready.set(false); this.busy.set(false); this.error.set(''); this.message.set(''); this.origins.set([]);
    this.origin.set(''); this.url.set(''); this.permission.set(false); this.verifications.set([]); this.verificationsMore.set(false);
    this.targetUrls.set([]);
    this.challenge.set(null); this.selection.set(null); this.pending.set(null); this.notFound.set(false);
    this.jobs.set([]); this.hasMore.set(false); this.selected.set(null); this.evidence.set(null); this.candidateReport.set(null);
  }
  private clearFindings() { this.chainCandidateJob = null; this.clearPair(); this.clearPriority(); this.findingInspection.set(null); this.findingPending.set(null); }
  private clearPair() {
    this.pairHttpId.set(0); this.pairHttpsId.set(0); this.responsePair.set(null); this.frozenPair.set(null);
    this.httpsJobs.set([]); this.httpsHasMore.set(false);
  }
  private clearPriority() {
    this.priorityInspection.set(null); this.priorityPending.set(null);
    this.humanPriority.set('unprioritized'); this.humanEffort.set('unknown'); this.humanRelevance.set('unknown'); this.humanReason.set('');
  }
  private requestFindings(id: number, candidateDigest?: string) {
    if (this.chain) return this.api.passiveRedirectChainFindings(this.organizationId, this.projectId, id, candidateDigest);
    if (this.redirects) return this.api.passiveRedirectFindings(this.organizationId, this.projectId, id, candidateDigest);
    if (this.tls) return this.api.passiveTlsFindings(this.organizationId, this.projectId, id, candidateDigest);
    if (this.resources) return this.api.passiveResourceFindings(this.organizationId, this.projectId, id, candidateDigest);
    if (this.family === 'headers') return this.api.passiveHeaderFindings(this.organizationId, this.projectId, id, candidateDigest);
    throw new Error();
  }
  private edit() { this.clearFindings(); ++this.epoch; this.busy.set(false); this.selection.set(null); this.pending.set(null); this.notFound.set(false);
    this.selected.set(null); this.evidence.set(null); this.candidateReport.set(null); this.challenge.set(null); this.error.set(''); this.message.set(''); }
  editOrigin(value: string) { this.edit(); this.origin.set(this.selectableOrigins.includes(value) ? value : ''); this.url.set(this.origin() ? this.origin() + '/' : ''); this.permission.set(false); }
  editUrl(value: string) { this.edit(); this.url.set(value); this.permission.set(false); }
  editPermission(value: boolean) { this.edit(); this.permission.set(value === true); }
  addTarget() { if (this.chain && !this.busy() && !this.pending() && this.targetUrls().length < 5) { this.edit(); this.targetUrls.update(rows => [...rows, '']); this.permission.set(false); } }
  editTarget(index: number, value: string) {
    if (!this.chain || !Number.isInteger(index) || index < 0 || index >= this.targetUrls().length) return;
    this.edit(); this.targetUrls.update(rows => rows.map((row, i) => i === index ? value : row)); this.permission.set(false);
  }
  removeTarget(index: number) {
    if (!this.chain || this.busy() || this.pending() || !Number.isInteger(index) || index < 0 || index >= this.targetUrls().length) return;
    this.edit(); this.targetUrls.update(rows => rows.filter((_row, i) => i !== index)); this.permission.set(false);
  }
  private scope(result: ApiResult, status = 200) {
    if (result.status !== status || result.body['organization_id'] !== this.organizationId || result.body['project_id'] !== this.projectId) throw new Error();
    return result.body;
  }
  private verification(value: unknown): Verification {
    if (!exact(value, ['id', 'project_id', 'origin', 'method', 'state', 'challenge_path', 'verified_at', 'revoked_at', 'created_at', 'updated_at'])
      || !positive(value['id']) || value['project_id'] !== this.projectId || !this.canonicalOrigin(value['origin'])
      || value['method'] !== 'http_file' || value['challenge_path'] !== PATH || !ordered(value['created_at'], value['updated_at'])
      || typeof value['state'] !== 'string' || !['pending', 'verified', 'revoked'].includes(value['state'])
      || value['verified_at'] !== null && (!ordered(value['created_at'], value['verified_at']) || !ordered(value['verified_at'], value['updated_at']))
      || value['revoked_at'] !== null && (!ordered(value['created_at'], value['revoked_at']) || !ordered(value['revoked_at'], value['updated_at']))
      || value['state'] === 'pending' && (value['verified_at'] !== null || value['revoked_at'] !== null)
      || value['state'] === 'verified' && (value['verified_at'] === null || value['revoked_at'] !== null)
      || value['state'] === 'revoked' && value['revoked_at'] === null) throw new Error();
    return structuredClone(value) as Verification;
  }
  private canonicalOrigin(value: unknown): value is string { return typeof value === 'string' && value.length <= 255
    && (safeUrl(value) === value + '/' || this.getOnlyUncertainty && safeHttpUrl(value) === value + '/') && new URL(value).origin === value; }
  private job(value: unknown): Job {
    if (!exact(value, ['id', 'status', 'created_at', 'updated_at', 'cancel_requested', 'estimate_units', 'error_category']) || !positive(value['id'])
      || typeof value['status'] !== 'string' || !['queued', 'running', 'succeeded', 'failed', 'cancelled'].includes(value['status']) || !ordered(value['created_at'], value['updated_at'])
      || typeof value['cancel_requested'] !== 'boolean' || value['estimate_units'] !== 1
      || typeof value['error_category'] !== 'string' || !ERRORS.includes(value['error_category'])) throw new Error();
    return structuredClone(value) as Job;
  }
  private list(result: ApiResult, key: string | null = null) {
    const row = this.scope(result);
    if (!exact(row, ['organization_id', 'project_id', 'jobs', 'has_more', 'lookup']) || !Array.isArray(row['jobs']) || row['jobs'].length > 20
      || typeof row['has_more'] !== 'boolean' || row['lookup'] !== key) throw new Error();
    const jobs = row['jobs'].map(value => this.job(value));
    if (new Set(jobs.map(job => job.id)).size !== jobs.length || jobs.some((job, i) => i > 0 && jobs[i - 1].id <= job.id)
      || row['has_more'] && jobs.length !== 20 || key !== null && (jobs.length > 1 || row['has_more'])) throw new Error();
    return { jobs, more: row['has_more'] };
  }
  pairJobs(scheme: string) {
    return (scheme === 'http' ? this.jobs() : this.httpsJobs()).filter(job => job.status === 'succeeded' && !job.cancel_requested && job.error_category === '');
  }
  choosePairJob(scheme: 'http' | 'https', value: string) {
    if (!this.httpRedirects || !this.ready() || this.pending()) return;
    ++this.epoch; this.busy.set(false); this.responsePair.set(null); this.frozenPair.set(null);
    this.selection.set(null); this.selected.set(null); this.evidence.set(null); this.challenge.set(null); this.permission.set(false);
    this.error.set(''); this.message.set('');
    const id = /^[1-9]\d*$/.test(value) && positive(Number(value)) && this.pairJobs(scheme).some(job => job.id === Number(value)) ? Number(value) : 0;
    (scheme === 'http' ? this.pairHttpId : this.pairHttpsId).set(id);
  }
  async refreshHttpsHistory() {
    if (!this.httpRedirects || !this.ready() || this.busy() || this.pending()) return;
    this.edit(); const epoch = this.epoch; this.busy.set(true);
    try {
      if (!await this.currentProjectScope(epoch) || epoch !== this.epoch) return;
      const result = await this.api.passiveRedirects(this.organizationId, this.projectId);
      if (epoch !== this.epoch) return; const history = this.list(result);
      if (!await this.currentProjectScope(epoch) || epoch !== this.epoch) return;
      this.httpsJobs.set(history.jobs); this.httpsHasMore.set(history.more);
    } catch { if (epoch === this.epoch) { this.reset(); this.error.set('Separate saved HTTPS history/current scope unavailable. No collection requested.'); } }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  private async currentPairScope(epoch: number) {
    if (!await this.currentProjectScope(epoch) || epoch !== this.epoch) return false;
    const result = await this.api.originVerifications(this.organizationId, this.projectId);
    if (epoch !== this.epoch) return false;
    if (result.status !== 200 || !exact(result.body, ['verifications', 'has_more']) || !Array.isArray(result.body['verifications'])
      || result.body['verifications'].length > 100 || result.body['has_more'] !== this.verificationsMore()) this.findingAuthorityLost();
    const records = result.body['verifications'].map(value => this.verification(value));
    if (!same(records, this.verifications()) || !records.some(http => http.state === 'verified' && http.origin.startsWith('http://')
      && this.origins().includes(http.origin) && records.some(https => https.state === 'verified' && https.origin === 'https' + http.origin.slice(4)
        && this.origins().includes(https.origin)))) this.findingAuthorityLost();
    return this.currentProjectScope(epoch);
  }
  private async currentPairMetadata(pair: ResponsePair, epoch: number) {
    const http = await this.api.passiveHttpRedirects(this.organizationId, this.projectId);
    if (epoch !== this.epoch) return false; const httpJobs = this.list(http).jobs;
    const https = await this.api.passiveRedirects(this.organizationId, this.projectId);
    if (epoch !== this.epoch) return false; const httpsJobs = this.list(https).jobs;
    if (!same(httpJobs.find(job => job.id === pair.http.id), pair.http) || !same(httpsJobs.find(job => job.id === pair.https.id), pair.https)) throw new Error();
    return this.currentPairScope(epoch);
  }
  private validateResponsePair(result: ApiResult, pair: ResponsePair): Row {
    const row = this.scope(result); const value = row['comparison'];
    if (!exact(row, ['organization_id', 'project_id', 'comparison'])
      || !exact(value, ['method_version', 'organization_id', 'project_id', 'source_current', 'http', 'https', 'coverage', 'interpretation'])
      || new TextEncoder().encode(JSON.stringify(value)).length > 24576 || value['method_version'] !== 'passive-original-http-https-pair-v1'
      || value['organization_id'] !== this.organizationId || value['project_id'] !== this.projectId || value['source_current'] !== true
      || value['coverage'] !== 'two_independently_verified_same_host_default_port_exact_source_path_original_responses_only'
      || value['interpretation'] !== PAIR_MEANING) throw new Error();
    for (const scheme of ['http', 'https'] as const) {
      const item = value[scheme];
      if (!exact(item, ['job_id', 'binding', 'collection'])) throw new Error();
      this.validateRedirectEvidence({ job_id: item['job_id'], source_current: true, collection: item['collection'] }, pair[scheme], scheme === 'http');
      const collection = item['collection'] as Row; const binding = item['binding'];
      this.validateBinding(binding, { url: collection['url'] }, scheme === 'http' ? 'http-redirects' : 'redirects');
      if (!object(binding) || !canonicalDate(binding['verified_at']) || !ordered(binding['verified_at'], collection['observed_at'])
        || !this.verifications().some(record => record.id === binding['verification_id'] && record.state === 'verified'
          && record.origin === binding['origin'] && record.verified_at === binding['verified_at'])) throw new Error();
    }
    const http = value['http'] as Row; const https = value['https'] as Row;
    if ((https['collection'] as Row)['url'] !== 'https' + String((http['collection'] as Row)['url']).slice(4)
      || (http['binding'] as Row)['verification_id'] === (https['binding'] as Row)['verification_id']) throw new Error();
    return structuredClone(value);
  }
  async compareResponses(event?: Event) {
    event?.preventDefault();
    if (!this.httpRedirects || !this.ready() || this.busy() || this.pending()) return;
    const http = this.pairJobs('http').find(job => job.id === this.pairHttpId());
    const https = this.pairJobs('https').find(job => job.id === this.pairHttpsId());
    this.responsePair.set(null); this.frozenPair.set(null);
    if (!http || !https || http.id === https.id) return;
    const pair = structuredClone({ http, https }); const epoch = ++this.epoch;
    this.frozenPair.set(pair); this.busy.set(true); this.error.set(''); this.message.set('');
    this.selection.set(null); this.selected.set(null); this.evidence.set(null); this.challenge.set(null); this.permission.set(false);
    try {
      if (!await this.currentPairScope(epoch) || epoch !== this.epoch) return;
      if (!await this.currentPairMetadata(pair, epoch) || epoch !== this.epoch) return;
      const result = await this.api.passiveHttpHttpsComparison(this.organizationId, this.projectId, pair.http.id, pair.https.id);
      if (epoch !== this.epoch) return; const value = this.validateResponsePair(result, pair);
      if (!await this.currentPairMetadata(pair, epoch) || epoch !== this.epoch) return;
      this.responsePair.set(value);
    } catch { if (epoch === this.epoch) { this.reset(); this.error.set('Original independent pair/current source or saved metadata unavailable. Missing is not zero or a security verdict. Refresh and choose again.'); } }
    finally { if (epoch === this.epoch) { this.frozenPair.set(null); this.busy.set(false); } }
  }
  async load() {
    if (this.busy() || this.pending() || this.priorityPending() || !positive(this.organizationId) || !positive(this.projectId)) return;
    this.reset(); const epoch = this.epoch; this.busy.set(true);
    try {
      const project = await this.api.projectOnboarding(this.organizationId, this.projectId); if (epoch !== this.epoch) return;
      const row = project.body['project'];
      if (project.status !== 200 || !object(row) || row['id'] !== this.projectId || row['organization_id'] !== this.organizationId
        || typeof row['role'] !== 'string' || !['owner', 'admin'].includes(row['role']) || !this.canonicalOrigin(row['canonical_origin']) || !Array.isArray(row['aliases'])
        || row['aliases'].length > 100 || !row['aliases'].every(value => this.canonicalOrigin(value))) throw new Error();
      const origins = [row['canonical_origin'], ...row['aliases']] as string[];
      const verification = await this.api.originVerifications(this.organizationId, this.projectId); if (epoch !== this.epoch) return;
      if (verification.status !== 200 || !exact(verification.body, ['verifications', 'has_more']) || !Array.isArray(verification.body['verifications'])
        || verification.body['verifications'].length > 100 || typeof verification.body['has_more'] !== 'boolean') throw new Error();
      const records = verification.body['verifications'].map(value => this.verification(value));
      if (new Set(records.map(item => item.id)).size !== records.length || new Set(records.map(item => item.origin)).size !== records.length) throw new Error();
      const history = await this.request(); if (epoch !== this.epoch) return;
      const list = this.list(history);
      this.origins.set(origins); this.verifications.set(records); this.verificationsMore.set(verification.body['has_more']);
      if (this.chain && (!await this.currentChainScope(null, epoch) || epoch !== this.epoch)) return;
      this.jobs.set(list.jobs); this.hasMore.set(list.more); this.ready.set(true);
    } catch { if (epoch === this.epoch) { this.reset(); this.error.set('Current owner/admin source and private history are unavailable.'); } }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  private data(): Row {
    if (this.chain) {
      if (!this.ready() || !this.permission()) throw new Error();
      const data = { url: this.url(), target_urls: [...this.targetUrls()], observations: this.observations, collection_permission: true };
      this.chainUrls(data); return data;
    }
    if (this.tls) {
      if (!this.ready() || !this.permission() || !this.canonicalOrigin(this.origin()) || this.origin().length > 255 || !this.origins().includes(this.origin())) throw new Error();
      return { origin: this.origin(), observations: this.observations, collection_permission: true };
    }
    const url = this.url();
    if (!this.ready() || !this.permission() || !url || (this.httpRedirects ? safeHttpUrl(url) : safeUrl(url)) !== url || url.length > 1024 || /[?#]/.test(url)
      || !this.origins().includes(new URL(url).origin)) throw new Error();
    return { url, observations: this.observations, collection_permission: true };
  }
  private chainUrls(data: Row): string[] {
    if (!Array.isArray(data['target_urls']) || data['target_urls'].length > 5) throw new Error();
    const urls = [data['url'], ...data['target_urls']];
    if (urls.some(url => typeof url !== 'string' || url.length > 1024 || /[?#]/.test(url)
      || (url.startsWith('http://') ? safeHttpUrl(url) : safeUrl(url)) !== url || !this.origins().includes(new URL(url).origin))
      || new Set(urls).size !== urls.length) throw new Error();
    return urls as string[];
  }
  private validateChainBinding(binding: unknown, data: Row) {
    if (!exact(binding, ['method_version', 'organization_id', 'project_id', 'actor_id', 'url', 'target_urls', 'observations',
      'collection_permission', 'origins', 'source_digest', 'interpretation']) || binding['method_version'] !== 'passive-redirect-chain-source-v1'
      || binding['organization_id'] !== this.organizationId || binding['project_id'] !== this.projectId || !positive(binding['actor_id'])
      || binding['url'] !== data['url'] || !same(binding['target_urls'], data['target_urls']) || !same(binding['observations'], ['redirect_chain'])
      || binding['collection_permission'] !== true || !digest(binding['source_digest']) || binding['interpretation'] !== CHAIN_SOURCE_MEANING) throw new Error();
    const origins = [...new Set(this.chainUrls(binding).map(url => new URL(url).origin))];
    const rows = binding['origins'];
    if (!Array.isArray(rows) || rows.length !== origins.length || new Set(rows.map(row => object(row) ? row['verification_id'] : null)).size !== rows.length) throw new Error();
    rows.forEach((row, index) => {
      if (!exact(row, ['origin', 'verification_id', 'verified_at']) || row['origin'] !== origins[index] || !positive(row['verification_id'])
        || typeof row['verified_at'] !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.(?!000000)\d{6})?\+00:00$/.test(row['verified_at'])
        || !dated(row['verified_at']) || !this.verifications().some(record => record.id === row['verification_id'] && record.origin === row['origin']
          && record.state === 'verified' && record.verified_at === row['verified_at'])) throw new Error();
    });
  }
  private async currentChainScope(data: Row | null, epoch: number) {
    if (!await this.currentProjectScope(epoch) || epoch !== this.epoch) return false;
    const result = await this.api.originVerifications(this.organizationId, this.projectId);
    if (epoch !== this.epoch) return false;
    if (result.status !== 200 || !exact(result.body, ['verifications', 'has_more']) || !Array.isArray(result.body['verifications'])
      || result.body['verifications'].length > 100 || result.body['has_more'] !== this.verificationsMore()) this.findingAuthorityLost();
    let records: Verification[];
    try { records = result.body['verifications'].map(value => this.verification(value)); }
    catch { this.findingAuthorityLost(); }
    if (!same(records, this.verifications())) this.findingAuthorityLost();
    if (data) {
      const origins = [...new Set(this.chainUrls(data).map(url => new URL(url).origin))];
      if (origins.some(origin => !records.some(record => record.origin === origin && record.state === 'verified'))) this.findingAuthorityLost();
      if (Object.hasOwn(data, 'method_version')) this.validateChainBinding(data, data);
    }
    return this.currentProjectScope(epoch);
  }
  private async readPreview(data: Row): Promise<Preview> {
    const epoch = this.epoch;
    if (this.chain && (!await this.currentChainScope(data, epoch) || epoch !== this.epoch)) throw new Error();
    const result = await this.request(data, undefined, undefined, true);
    if (epoch !== this.epoch) throw new Error();
    if (this.getOnlyUncertainty && result.status !== 200) this.findingAuthorityLost();
    const row = this.scope(result); const selection = row['selection'];
    if (!exact(row, ['organization_id', 'project_id', 'selection', 'selection_digest', 'estimate_units']) || row['estimate_units'] !== 1
      || !exact(selection, ['method', 'binding']) || selection['method'] !== this.method || !digest(row['selection_digest'])) throw new Error();
    const binding = selection['binding'];
    this.validateBinding(binding, data);
    if (await selectionDigest(selection) !== row['selection_digest']) throw new Error();
    if (epoch !== this.epoch) throw new Error();
    if (this.getOnlyUncertainty && (!await this.currentOriginalScope({ binding }, epoch) || epoch !== this.epoch)) throw new Error();
    return structuredClone({ selection, selection_digest: row['selection_digest'] }) as Preview;
  }
  private validateBinding(binding: unknown, data: Row, family = this.family) {
    if (family === 'redirect-chain') { this.validateChainBinding(binding, data); return; }
    const tls = family === 'tls'; const http = family === 'http-redirects';
    const observations = http ? ['http_response_location'] : family === 'redirects' ? ['response_location'] : family === 'resources' ? ['static_resource_references'] : tls ? ['certificate_dates', 'negotiated_tls'] : ['response_headers'];
    if (!exact(binding, ['method_version', 'organization_id', 'project_id', 'actor_id', 'origin', ...(tls ? [] : ['url']), 'observations', 'collection_permission',
      'verification_id', 'verified_at', 'source_digest', 'interpretation']) || binding['method_version'] !== (http ? 'passive-http-redirect-source-v1' : family === 'redirects' ? 'passive-redirect-source-v1' : family === 'resources' ? 'passive-resource-source-v1' : tls ? 'passive-tls-source-v1' : 'passive-header-source-v1')
      || binding['organization_id'] !== this.organizationId || binding['project_id'] !== this.projectId || !positive(binding['actor_id'])
      || (tls ? binding['origin'] !== data['origin'] : binding['url'] !== data['url'] || binding['origin'] !== new URL(String(data['url'])).origin)
      || !same(binding['observations'], observations)
      || binding['collection_permission'] !== true || !positive(binding['verification_id']) || !dated(binding['verified_at']) || !digest(binding['source_digest'])
       || binding['interpretation'] !== SOURCE_MEANING) throw new Error();
    if (http && !this.verifications().some(row => row.id === binding['verification_id'] && row.origin === binding['origin']
      && row.state === 'verified' && row.verified_at === binding['verified_at'])) this.findingAuthorityLost();
  }
  async preview(event?: Event) {
    event?.preventDefault(); if (this.busy() || this.pending() || this.priorityPending()) return;
    this.clearFindings();
    this.selection.set(null); this.selected.set(null); this.evidence.set(null); this.candidateReport.set(null); const epoch = ++this.epoch; this.busy.set(true); this.error.set('');
    try { const info = await this.readPreview(this.data()); if (epoch === this.epoch) this.selection.set(info); }
    catch { if (epoch === this.epoch) this.error.set('Exact current verified source, explicit permission or collection allowance unavailable. No command sent.'); }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  async launch() {
    if (this.busy() || this.pending() || this.priorityPending() || !this.selection()) return;
    const info = structuredClone(this.selection()!); const data = this.data(); const key = crypto.randomUUID();
    await this.send({ preview: info, key, data: { ...data, selection_digest: info.selection_digest, idempotency_key: key } });
  }
  private acknowledgement(result: ApiResult, id?: number) {
    const row = this.scope(result, 202); if (!exact(row, ['organization_id', 'project_id', 'job'])) throw new Error();
    const job = this.job(row['job']); if (id !== undefined && job.id !== id) throw new Error(); return job;
  }
  private async send(command: Pending) {
    this.clearFindings();
    const epoch = ++this.epoch; this.busy.set(true); this.error.set(''); this.selected.set(null); this.evidence.set(null); this.candidateReport.set(null); this.notFound.set(false);
    let sent = false; let received = false;
    try {
      if (this.getOnlyUncertainty && command.jobId && (!await this.currentProjectScope(epoch) || epoch !== this.epoch)) return;
      if (!command.jobId) {
        const fresh = await this.readPreview(this.tls
          ? { origin: command.data['origin'], observations: this.observations, collection_permission: true }
          : { url: command.data['url'], ...(this.chain ? { target_urls: command.data['target_urls'] } : {}), observations: this.observations, collection_permission: true });
        if (epoch !== this.epoch) return;
        if (!same(fresh, command.preview)) throw new Error();
      }
      this.pending.set(structuredClone(command)); sent = true;
      const result = await this.request(command.jobId ? {} : command.data, command.jobId);
      if (epoch !== this.epoch) return;
      received = true;
      if (this.getOnlyUncertainty && (!await (command.jobId ? this.currentProjectScope(epoch) : this.currentOriginalScope({ binding: command.preview.selection.binding }, epoch)) || epoch !== this.epoch)) return;
      const job = this.acknowledgement(result, command.jobId); this.pending.set(null); this.selection.set(null); this.selected.set(job);
      this.message.set('Exact command acknowledged. Refresh metadata or deliberately inspect private evidence.');
    } catch { if (epoch === this.epoch) { if (this.getOnlyUncertainty && (!sent || received)) this.reset();
      this.error.set(sent ? 'Command outcome uncertain. Look up the exact original command; no automatic replay.'
        : 'Current source changed. No collection command sent; preview again.'); } }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  async reconcile() {
    if (this.busy() || this.priorityPending() || !this.pending()) return;
    this.clearFindings();
    const command = structuredClone(this.pending()!); const epoch = ++this.epoch; this.busy.set(true); this.notFound.set(false); this.error.set(''); this.candidateReport.set(null);
    let received = false;
    try {
      if (this.getOnlyUncertainty && (!await (command.jobId ? this.currentProjectScope(epoch) : this.currentOriginalScope({ binding: command.preview.selection.binding }, epoch)) || epoch !== this.epoch)) return;
      if (command.jobId) {
        const result = await this.request(undefined, command.jobId);
        received = true;
        if (epoch !== this.epoch) return; const row = this.scope(result);
        if (this.getOnlyUncertainty && !exact(row, ['organization_id', 'project_id', 'job', 'evidence'])) throw new Error();
        if (this.getOnlyUncertainty && (!await this.currentProjectScope(epoch) || epoch !== this.epoch)) return;
        const job = this.job(row['job']);
        if (job.id !== command.jobId || !job.cancel_requested && !['cancelled', 'succeeded', 'failed'].includes(job.status)) throw new Error();
        this.selected.set(job);
      } else {
        const result = await this.request(undefined, undefined, command.key);
        received = true;
        if (epoch !== this.epoch) return; const list = this.list(result, command.key);
        if (this.getOnlyUncertainty && (!await this.currentOriginalScope({ binding: command.preview.selection.binding }, epoch) || epoch !== this.epoch)) return;
        if (!list.jobs.length) { this.notFound.set(true); this.message.set(this.getOnlyUncertainty
          ? 'No saved own-actor request at this lookup; the original outcome remains unknown. No replay.'
          : 'No saved own-actor request at this lookup. Retry requires a fresh unchanged exact source.'); return; }
        this.selected.set(list.jobs[0]);
      }
      this.pending.set(null); this.selection.set(null); this.message.set('Exact original command reconciled; no command replayed.');
    } catch { if (epoch === this.epoch) { if (this.getOnlyUncertainty && received) this.reset();
      this.selected.set(null); this.evidence.set(null); this.error.set(this.getOnlyUncertainty && received
        ? 'Current lookup denied or changed; local uncertainty cleared. A saved job may exist. No replay.'
        : 'Exact current lookup unavailable; command remains uncertain.'); } }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  async retry() { if (!this.getOnlyUncertainty && !this.busy() && this.notFound() && this.pending() && !this.pending()!.jobId) await this.send(structuredClone(this.pending()!)); }
  discardHttpCommand() { if (this.getOnlyUncertainty && !this.busy()) { this.edit(); this.permission.set(false); this.message.set('Local uncertainty discarded; a saved job may exist. No command replayed.'); } }
  async cancel(id: number) {
    if (this.busy() || this.pending() || this.priorityPending() || !positive(id) || !this.jobs().some(job => job.id === id && ['queued', 'running'].includes(job.status) && !job.cancel_requested)) return;
    await this.send({ jobId: id, key: '', data: {}, preview: { selection: { binding: {} }, selection_digest: '' } });
  }
  async inspect(id: number) {
    if (this.busy() || this.pending() || this.priorityPending() || !positive(id) || !this.ready()) return;
    this.clearFindings();
    const epoch = ++this.epoch; this.busy.set(true); this.selected.set(null); this.evidence.set(null); this.candidateReport.set(null); this.error.set('');
    try {
      if (this.getOnlyUncertainty && (!await (this.chain ? this.currentChainScope(null, epoch) : this.currentProjectScope(epoch)) || epoch !== this.epoch)) return;
      const result = await this.request(undefined, id); if (epoch !== this.epoch) return;
      const row = this.scope(result); if (!exact(row, ['organization_id', 'project_id', 'job', 'evidence'])) throw new Error();
      const job = this.job(row['job']); if (job.id !== id) throw new Error();
      const evidence = row['evidence']; if (evidence !== null) this.validateEvidence(evidence, job);
      if (this.chain && (!await (evidence === null ? this.currentProjectScope(epoch) : this.currentOriginalScope(evidence as Row, epoch)) || epoch !== this.epoch)) return;
      if (this.httpRedirects) {
        if (evidence !== null) {
          const source = (evidence as Row)['collection'] as Row;
          const verified = this.verifications().find(item => item.origin === new URL(String(source['url'])).origin && item.state === 'verified');
          if (!verified || !ordered(verified.verified_at, source['observed_at'])) this.findingAuthorityLost();
          if (!await this.currentOriginalScope({ binding: { verification_id: verified.id, origin: verified.origin, verified_at: verified.verified_at } }, epoch) || epoch !== this.epoch) return;
        } else if (!await this.currentProjectScope(epoch) || epoch !== this.epoch) return;
      }
      this.selected.set(job); this.evidence.set(evidence === null ? null : structuredClone(evidence) as Row);
    } catch { if (epoch === this.epoch) { if (this.getOnlyUncertainty) this.reset(); this.selection.set(null); this.error.set('Exact private evidence/current source unavailable. Missing is not zero findings.'); } }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  private validateEvidence(value: unknown, job: Job) {
    if (this.chain) { this.validateChainEvidence(value, job); return; }
    if (this.redirects || this.httpRedirects) { this.validateRedirectEvidence(value, job); return; }
    if (this.resources) { this.validateResourceEvidence(value, job); return; }
    if (this.tls) { this.validateTlsEvidence(value, job); return; }
    if (!exact(value, ['job_id', 'collection', 'source_current']) || value['job_id'] !== job.id || value['source_current'] !== true || job.status !== 'succeeded'
      || job.cancel_requested || !exact(value['collection'], ['method', 'url', 'status', 'observed_at', 'evidence', 'interpretation'])) throw new Error();
    const source = value['collection'];
    if (source['method'] !== METHOD || source['interpretation'] !== MEANING || !Number.isInteger(source['status']) || Number(source['status']) < 200 || Number(source['status']) > 599
      || typeof source['url'] !== 'string' || safeUrl(source['url']) !== source['url'] || !this.origins().includes(new URL(source['url']).origin)
      || !ordered(job.created_at, source['observed_at']) || !ordered(source['observed_at'], job.updated_at)) throw new Error();
    const info = source['evidence'];
    if (!exact(info, ['method_version', 'state', 'coverage', 'interpretation', 'headers', 'cookies']) || info['method_version'] !== 'passive-response-headers-v1'
      || info['state'] !== 'observed' || info['coverage'] !== 'one_complete_original_response_header_sequence_only' || info['interpretation'] !== HEADER_MEANING
      || !exact(info['headers'], HEADERS) || !Object.values(info['headers']).every(value => typeof value === 'string' && ['absent', 'present_empty', 'present_nonempty', 'multiple_fields'].includes(value))
      || !exact(info['cookies'], COOKIES) || !Object.values(info['cookies']).every(value => Number.isInteger(value) && Number(value) >= 0 && Number(value) <= 100)) throw new Error();
    const cookies = info['cookies']; const parsed = Number(cookies['parsed_fields']);
    if (Number(cookies['observed_fields']) !== parsed + Number(cookies['unclassified_fields']) || COOKIES.slice(3).some(key => Number(cookies[key]) > parsed)
      || Number(cookies['observed_fields']) + Object.values(info['headers']).reduce<number>((sum, value) => sum + (value === 'absent' ? 0 : value === 'multiple_fields' ? 2 : 1), 0) > 100) throw new Error();
  }
  candidateRows(): HeaderCandidate[] { return this.candidateReport()?.['candidates'] as HeaderCandidate[] ?? []; }
  candidateText(item: HeaderCandidate) {
    const facts = item.evidence;
    if (this.chain) return item.detector === 'observed_https_to_http_transition_candidate'
      ? `${this.t('Actually adjacent original HTTPS→HTTP captured hop indices:')} ${(facts['transitions'] as Row[]).map(pair => `${pair['from_hop']}→${pair['to_hop']}`).join(', ')}${this.t('. Plaintext HTTP is unauthenticated; this is not current availability or browser behavior.')}`
      : `${this.t('Original')} ${facts['state']} ${this.t('stopping fact ·')} ${facts['observed_hops']} ${this.t('captured responses · last zero-based hop')} ${facts['last_hop']}${this.t('. No stopped target response is implied.')}`;
    if (this.redirects) return `${this.t('Original HTTP-scheme Location reference · HTTP')} ${facts['response_status']} ${this.t('· common redirect status:')} ${facts['redirect_status']} ${this.t('· same-origin:')} ${facts['same_origin']}${this.t('. This reference was not followed; it does not prove a redirect downgrade.')}`;
    if (this.tls) return item.detector === 'negotiated_tlsv1_or_tlsv1_1_candidate'
      ? `${this.t('Actual original negotiated version:')} ${facts['version']}${this.t('. This is not a supported-protocol inventory or cipher protocol label.')}`
      : `${this.t('Reported certificate interval')} ${facts['not_before']} ${this.t('to')} ${facts['not_after']}: ${facts['position']}; remaining_microseconds ${facts['remaining_microseconds']}${this.t('. This is an original reported-date fact, not current certificate validation.')}`;
    if (this.resources) {
      const counts = facts['counts'] as Row;
      return `${counts['http_absolute']} ${this.t('explicit HTTP references among')} ${counts['inspected_attributes']} ${this.t('inspected selected attributes;')} ${counts['https_absolute']} ${this.t('explicit HTTPS and')} ${counts['unclassified']} ${this.t('unclassified references. These counts do not prove browser requests or mixed-content policy.')}`;
    }
    if (facts['header']) return `${facts['header']}: ${this.t(facts['state'] === 'absent' ? 'absent in this response' : facts['state'] === 'present_empty' ? 'one empty field' : 'one nonempty disclosure field')}${facts['report_only_state'] ? `${this.t('; report-only CSP:')} ${facts['report_only_state']}` : ''}.`;
    const flag = facts['flag'] === 'without_secure' ? 'Secure' : facts['flag'] === 'without_httponly' ? 'HttpOnly' : this.t('recognized SameSite');
    return `${facts['count']} ${this.t('of')} ${facts['parsed_fields']} ${this.t('parsed public cookie fields without')} ${flag}; ${facts['unclassified_fields']} ${this.t('unclassified fields excluded.')}`;
  }
  async inspectCandidates(id: number) {
    const job = this.jobs().find(row => row.id === id);
    if (this.family !== 'headers' || this.busy() || this.pending() || this.priorityPending() || !positive(id) || !this.ready()
      || !job || job.status !== 'succeeded' || job.cancel_requested) return;
    const original = structuredClone(job); const epoch = ++this.epoch;
    this.clearFindings();
    this.busy.set(true); this.candidateReport.set(null); this.selected.set(null); this.evidence.set(null); this.error.set('');
    try {
      const result = await this.api.passiveHeaderCandidates(this.organizationId, this.projectId, id);
      if (epoch !== this.epoch) return;
      const row = this.scope(result);
      if (!exact(row, ['organization_id', 'project_id', 'candidates'])) throw new Error();
      const report = this.validateCandidates(row['candidates'], original);
      this.candidateReport.set(report);
    } catch { if (epoch === this.epoch) this.error.set('Original header review candidates/current source unavailable. Missing is not zero candidates.'); }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  private validateCandidates(value: unknown, original: Job): Row {
      const report = value;
      if (!exact(report, ['job_id', 'source_current', 'method_version', 'binding', 'collection', 'coverage', 'candidates', 'interpretation'])
        || report['method_version'] !== 'passive-header-candidates-v1'
        || report['coverage'] !== 'one_original_response_selected_header_categories_and_parsed_cookie_subset_only'
        || report['interpretation'] !== 'dated_response_review_candidates_not_severity_policy_effectiveness_browser_behavior_or_exploitability') throw new Error();
      this.validateEvidence({ job_id: report['job_id'], source_current: report['source_current'], collection: report['collection'] }, original);
      const collection = report['collection'] as Row; const binding = report['binding'];
      if (typeof collection['url'] !== 'string' || collection['url'].length > 1024 || /[?#]/.test(collection['url'])) throw new Error();
      this.validateBinding(binding, { url: collection['url'] });
      if (!object(binding) || !ordered(binding['verified_at'], collection['observed_at'])) throw new Error();
      const info = collection['evidence'] as Row; const headers = info['headers'] as Row; const cookies = info['cookies'] as Row;
      const expected: HeaderCandidate[] = [];
      for (const header of [HEADERS[0], HEADERS[1], ...HEADERS.slice(3, 6)]) {
        const state = headers[header];
        if (state === 'absent' || state === 'present_empty') expected.push({ detector: `response_${header.replaceAll('-', '_')}_${state}_candidate`,
          evidence: { header, state, ...(header === 'content-security-policy' ? { report_only_state: headers[HEADERS[2]] } : {}) } });
      }
      for (const header of HEADERS.slice(6)) {
        if (headers[header] === 'present_nonempty') expected.push({ detector: `response_${header.replaceAll('-', '_')}_disclosure_candidate`, evidence: { header, state: 'present_nonempty' } });
      }
      for (const flag of COOKIES.slice(3)) {
        if (Number(cookies[flag]) > 0) expected.push({ detector: `parsed_public_cookie_${flag}_candidate`, evidence: { flag, count: cookies[flag],
          parsed_fields: cookies['parsed_fields'], observed_fields: cookies['observed_fields'], unclassified_fields: cookies['unclassified_fields'] } });
      }
      if (!same(report['candidates'], expected)) throw new Error();
      return structuredClone(report);
  }
  async inspectResourceCandidates(id: number) {
    const job = this.jobs().find(row => row.id === id);
    if (!this.resources || this.busy() || this.pending() || this.priorityPending() || !this.ready() || !positive(id)
      || !job || job.status !== 'succeeded' || job.cancel_requested) return;
    const original = structuredClone(job); const epoch = ++this.epoch;
    this.clearFindings(); this.busy.set(true); this.candidateReport.set(null); this.selection.set(null);
    this.selected.set(null); this.evidence.set(null); this.error.set(''); this.message.set('');
    try {
      const result = await this.api.passiveResourceCandidates(this.organizationId, this.projectId, id);
      if (epoch !== this.epoch) return;
      if (result.status !== 200) { this.reset(); this.error.set('Original resource review candidates/current source unavailable. Missing is not zero candidates.'); return; }
      const row = this.scope(result);
      if (!exact(row, ['organization_id', 'project_id', 'candidates'])) throw new Error();
      const report = this.validateResourceCandidates(row['candidates'], original);
      if (!await this.currentOriginalScope(report, epoch) || epoch !== this.epoch) return;
      this.candidateReport.set(report);
    } catch { if (epoch === this.epoch) this.error.set('Original resource review candidates/current source unavailable. Missing is not zero candidates.'); }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  private validateResourceCandidates(value: unknown, original: Job): Row {
    if (!exact(value, ['job_id', 'source_current', 'method_version', 'binding', 'collection', 'state', 'reason', 'coverage', 'candidates', 'interpretation'])
      || value['method_version'] !== 'passive-resource-candidates-v1'
      || value['interpretation'] !== 'dated_literal_http_reference_candidate_not_browser_requests_mixed_content_policy_severity_or_whole_page_security') throw new Error();
    this.validateResourceEvidence({ job_id: value['job_id'], source_current: value['source_current'], collection: value['collection'] }, original);
    const collection = value['collection'] as Row; const binding = value['binding'];
    this.validateBinding(binding, { url: collection['url'] });
    if (!object(binding) || !ordered(binding['verified_at'], collection['observed_at'])) throw new Error();
    const refs = (collection['evidence'] as Row)['resource_references'] as Row; const counts = refs['counts'] as Row;
    const observed = refs['state'] === 'observed';
    const expected = observed && Number(counts['http_absolute']) > 0 ? [{ detector: 'literal_http_resource_reference_candidate',
      evidence: { counts, selected_attributes: refs['selected_attributes'], excluded: refs['excluded'] } }] : [];
    if (value['state'] !== (observed ? 'original_lexical_review_candidates' : 'original_lexical_evaluation_unavailable')
      || value['reason'] !== refs['reason'] || value['coverage'] !== refs['coverage'] || !same(value['candidates'], expected)) throw new Error();
    return structuredClone(value);
  }
  async inspectTlsCandidates(id: number) {
    const job = this.jobs().find(row => row.id === id);
    if (!this.tls || this.busy() || this.pending() || this.priorityPending() || !this.ready() || !positive(id)
      || !job || job.status !== 'succeeded' || job.cancel_requested) return;
    const original = structuredClone(job); const epoch = ++this.epoch;
    this.clearFindings(); this.busy.set(true); this.candidateReport.set(null); this.selection.set(null);
    this.selected.set(null); this.evidence.set(null); this.error.set(''); this.message.set('');
    try {
      const result = await this.api.passiveTlsCandidates(this.organizationId, this.projectId, id);
      if (epoch !== this.epoch) return;
      if (result.status !== 200) { this.reset(); this.error.set('Original TLS review candidates/current source unavailable. Missing is not zero candidates.'); return; }
      const row = this.scope(result);
      if (!exact(row, ['organization_id', 'project_id', 'candidates'])) throw new Error();
      const report = this.validateTlsCandidates(row['candidates'], original);
      if (!await this.currentOriginalScope(report, epoch) || epoch !== this.epoch) return;
      this.candidateReport.set(report);
    } catch { if (epoch === this.epoch) this.error.set('Original TLS review candidates/current source unavailable. Missing is not zero candidates.'); }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  private validateTlsCandidates(value: unknown, original: Job): Row {
    if (!exact(value, ['job_id', 'source_current', 'method_version', 'binding', 'collection', 'availability', 'coverage', 'candidates', 'interpretation'])
      || value['method_version'] !== 'passive-tls-candidates-v1'
      || value['coverage'] !== 'one_original_reported_certificate_date_interval_and_actual_negotiated_version_only'
      || value['interpretation'] !== 'dated_reported_dates_and_negotiated_version_candidates_not_supported_configuration_revocation_browser_behavior_or_exploitability') throw new Error();
    this.validateTlsEvidence({ job_id: value['job_id'], source_current: value['source_current'], collection: value['collection'] }, original);
    const collection = value['collection'] as Row; const binding = value['binding'];
    this.validateBinding(binding, { origin: collection['origin'] });
    if (!object(binding) || !ordered(binding['verified_at'], collection['observed_at'])) throw new Error();
    const info = collection['evidence'] as Row; const dates = info['certificate_dates'] as Row; const version = (info['negotiated_tls'] as Row)['version'];
    const expected: HeaderCandidate[] = [];
    if (dates['state'] === 'observed' && dates['position'] !== 'within_reported_window') expected.push({
      detector: 'reported_certificate_date_outside_window_candidate', evidence: Object.fromEntries(
        ['not_before', 'not_after', 'position', 'remaining_microseconds'].map(key => [key, dates[key]])) });
    if (version === 'TLSv1' || version === 'TLSv1.1') expected.push({ detector: 'negotiated_tlsv1_or_tlsv1_1_candidate', evidence: { version } });
    if (!same(value['availability'], { certificate_dates: dates['state'], negotiated_version: version === null ? 'unavailable' : 'observed' })
      || !same(value['candidates'], expected)) throw new Error();
    return structuredClone(value);
  }
  async inspectRedirectCandidates(id: number) {
    const job = this.jobs().find(row => row.id === id);
    if (!this.redirects || this.busy() || this.pending() || this.priorityPending() || !this.ready() || !positive(id)
      || !job || job.status !== 'succeeded' || job.cancel_requested) return;
    const original = structuredClone(job); const epoch = ++this.epoch;
    this.clearFindings(); this.busy.set(true); this.candidateReport.set(null); this.selection.set(null);
    this.selected.set(null); this.evidence.set(null); this.error.set(''); this.message.set('');
    try {
      const result = await this.api.passiveRedirectCandidates(this.organizationId, this.projectId, id);
      if (epoch !== this.epoch) return;
      if (result.status !== 200) { this.reset(); this.error.set('Original Location review candidates/current source unavailable. Missing is not zero candidates.'); return; }
      const row = this.scope(result);
      if (!exact(row, ['organization_id', 'project_id', 'candidates'])) throw new Error();
      const report = this.validateRedirectCandidates(row['candidates'], original);
      if (!await this.currentOriginalScope(report, epoch) || epoch !== this.epoch) return;
      this.candidateReport.set(report);
    } catch { if (epoch === this.epoch) this.error.set('Original Location review candidates/current source unavailable. Missing is not zero candidates.'); }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  private validateRedirectCandidates(value: unknown, original: Job): Row {
    if (!exact(value, ['job_id', 'source_current', 'method_version', 'binding', 'collection', 'availability', 'coverage', 'candidates', 'interpretation'])
      || value['method_version'] !== 'passive-redirect-candidates-v1'
      || value['coverage'] !== 'one_original_first_https_response_classified_location_metadata_only'
      || value['interpretation'] !== 'dated_http_scheme_location_reference_not_followed_redirect_downgrade_https_upgrade_browser_behavior_severity_or_target_authority') throw new Error();
    this.validateRedirectEvidence({ job_id: value['job_id'], source_current: value['source_current'], collection: value['collection'] }, original);
    const collection = value['collection'] as Row; const binding = value['binding'];
    this.validateBinding(binding, { url: collection['url'] });
    if (!object(binding) || !ordered(binding['verified_at'], collection['observed_at'])) throw new Error();
    const location = (collection['evidence'] as Row)['response_location'] as Row;
    const classified = location['location_state'] === 'single_classified';
    const expected = classified && location['target_scheme'] === 'http' ? [{ detector: 'http_scheme_location_reference_candidate',
      evidence: Object.fromEntries(['response_status', 'redirect_status', 'location_state', 'target_scheme', 'same_origin'].map(key => [key, location[key]])) }] : [];
    if (!same(value['availability'], { target_metadata: classified ? 'observed' : 'unavailable' }) || !same(value['candidates'], expected)) throw new Error();
    return structuredClone(value);
  }
  private async currentChainMetadata(original: Job, binding: Row | null, epoch: number) {
    const result = await this.request();
    if (epoch !== this.epoch) return false;
    if (!same(this.list(result).jobs.find(job => job.id === original.id), original)) throw new Error();
    return this.currentChainScope(binding, epoch);
  }
  async inspectChainCandidates(id: number) {
    const job = this.jobs().find(row => row.id === id);
    if (!this.chain || this.busy() || this.pending() || this.priorityPending() || !this.ready() || !positive(id)
      || !job || job.status !== 'succeeded' || job.cancel_requested || job.error_category !== '') return;
    const original = structuredClone(job); const epoch = ++this.epoch;
    this.clearFindings(); this.busy.set(true); this.candidateReport.set(null); this.selection.set(null);
    this.selected.set(null); this.evidence.set(null); this.challenge.set(null); this.permission.set(false); this.error.set(''); this.message.set('');
    try {
      if (!await this.currentChainScope(null, epoch) || epoch !== this.epoch) return;
      if (!await this.currentChainMetadata(original, null, epoch) || epoch !== this.epoch) return;
      const result = await this.api.passiveRedirectChainCandidates(this.organizationId, this.projectId, original.id);
      if (epoch !== this.epoch) return;
      const row = this.scope(result);
      if (!exact(row, ['organization_id', 'project_id', 'candidates'])) throw new Error();
      const report = this.validateChainCandidates(row['candidates'], original);
      if (!await this.currentChainMetadata(original, report['binding'] as Row, epoch) || epoch !== this.epoch) return;
      this.chainCandidateJob = structuredClone(original);
      this.candidateReport.set(report);
    } catch { if (epoch === this.epoch) { this.reset(); this.error.set('Original chain candidates/current every-origin source or saved metadata unavailable. Missing is not zero candidates. Refresh and choose again.'); } }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  private validateChainCandidates(value: unknown, original: Job): Row {
    if (!exact(value, ['job_id', 'source_current', 'method_version', 'binding', 'collection', 'availability', 'coverage', 'candidates', 'interpretation'])
      || value['method_version'] !== 'passive-redirect-chain-candidates-v1'
      || value['coverage'] !== 'original_selected_adjacent_scheme_transitions_and_transport_stop_only'
      || value['interpretation'] !== 'dated_selected_scheme_transitions_and_stop_facts_not_current_availability_browser_behavior_authenticated_http_identity_severity_or_target_authority') throw new Error();
    this.validateChainEvidence({ job_id: value['job_id'], source_current: value['source_current'], binding: value['binding'], collection: value['collection'] }, original);
    const binding = value['binding'] as Row; const info = (value['collection'] as Row)['evidence'] as Row; const hops = info['hops'] as Row[];
    const transitions = hops.slice(0, -1).flatMap((hop, index) => String(hop['url']).startsWith('https://') && String(hops[index + 1]['url']).startsWith('http://')
      ? [{ from_hop: index, to_hop: index + 1 }] : []);
    const expected: HeaderCandidate[] = [];
    if (transitions.length) expected.push({ detector: 'observed_https_to_http_transition_candidate', evidence: { transitions } });
    if (info['state'] === 'redirect_loop' || info['state'] === 'redirect_limit') expected.push({
      detector: info['state'] === 'redirect_loop' ? 'redirect_chain_loop_stop_candidate' : 'redirect_chain_budget_stop_candidate',
      evidence: { state: info['state'], observed_hops: hops.length, last_hop: hops.length - 1 } });
    if (!same(value['availability'], { selected_urls: 1 + (binding['target_urls'] as string[]).length, observed_hops: hops.length,
      last_target_metadata: (hops.at(-1)!['response_location'] as Row)['location_state'] === 'single_classified' ? 'observed' : 'unavailable' })
      || !same(value['candidates'], expected)) throw new Error();
    return structuredClone(value);
  }
  private async validateFindings(result: ApiResult, job: Job): Promise<FindingInspection> {
    const row = this.scope(result);
    if (!exact(row, ['organization_id', 'project_id', 'candidates', 'candidate_digest', 'finding_set']) || !digest(row['candidate_digest'])) throw new Error();
    const report = this.chain ? this.validateChainCandidates(row['candidates'], job) : this.redirects ? this.validateRedirectCandidates(row['candidates'], job) : this.tls ? this.validateTlsCandidates(row['candidates'], job)
      : this.resources ? this.validateResourceCandidates(row['candidates'], job) : this.validateCandidates(row['candidates'], job);
    if (await selectionDigest(report) !== row['candidate_digest']) throw new Error();
    const set = row['finding_set']; const candidates = report['candidates'] as HeaderCandidate[]; const collection = report['collection'] as Row;
    const method = this.chain ? 'passive-redirect-chain-finding-v1' : this.redirects ? 'passive-redirect-finding-v1' : this.tls ? 'passive-tls-finding-v1' : this.resources ? 'passive-resource-finding-v1' : 'passive-header-finding-v1';
    const sourceField = this.chain ? 'source_passive_redirect_chain_id' : this.redirects ? 'source_passive_redirect_id' : this.tls ? 'source_passive_tls_id' : this.resources ? 'source_passive_resource_id' : 'source_passive_header_id';
    if (!exact(set, ['method_version', 'project_id', 'job_id', 'source_current', 'state', 'findings'])
      || set['method_version'] !== method || set['project_id'] !== this.projectId || set['job_id'] !== job.id
      || set['source_current'] !== true || !Array.isArray(set['findings']) || set['findings'].length > (this.chain || this.tls ? 2 : this.resources || this.redirects ? 1 : 10)
      || set['state'] !== (set['findings'].length ? 'current_materialized_facts' : 'no_retained_materialized_findings')
      || set['findings'].length && set['findings'].length !== candidates.length) throw new Error();
    const collectionSha = await selectionDigest(collection); const detectors = new Set<string>(); let lastId = 0;
    for (const [index, finding] of set['findings'].entries()) {
      if (!exact(finding, ['id', sourceField, 'detector', 'method_version', 'subject', 'fingerprint', 'evidence', 'confidence', 'detected_at'])
        || !positive(finding['id']) || Number(finding['id']) <= lastId || finding[sourceField] !== job.id
        || finding['method_version'] !== method || finding['subject'] !== collection[this.tls ? 'origin' : 'url']
        || finding['confidence'] !== (this.chain ? 'dated_chain_fact_not_risk_severity' : this.redirects ? 'dated_location_fact_not_risk_severity' : this.tls ? 'dated_tls_fact_not_risk_severity' : this.resources ? 'dated_literal_fact_not_risk_severity' : 'dated_response_fact_not_risk_severity') || !digest(finding['fingerprint'])
        || !ordered(collection[this.chain ? 'last_observed_at' : 'observed_at'], finding['detected_at'])) throw new Error();
      const candidate = candidates.find(item => item.detector === finding['detector']);
      if (!candidate || detectors.has(candidate.detector) || this.tls && candidate.detector !== candidates[index].detector) throw new Error();
      const binding = report['binding'] as Row;
      const expected = this.chain ? { source: 'passive_exact_selected_redirect_chain', job_id: job.id,
        binding: Object.fromEntries(['method_version', 'organization_id', 'project_id', 'actor_id', 'source_digest', 'observations', 'collection_permission'].map(key => [key, binding[key]])),
        binding_sha256: await selectionDigest(binding), collection_sha256: collectionSha,
        observed_at: collection['observed_at'], last_observed_at: collection['last_observed_at'],
        captures: ((collection['evidence'] as Row)['hops'] as Row[]).map((hop, index) => ({ hop: index, scheme: String(hop['url']).split(':', 1)[0], status: hop['status'], observed_at: hop['observed_at'] })),
        availability: report['availability'], fact: candidate.evidence, coverage: report['coverage'], interpretation: report['interpretation'] }
        : { source: this.redirects ? 'passive_first_response_location' : this.tls ? 'passive_certificate_dates_and_negotiated_tls' : this.resources ? 'passive_static_resource_references' : 'passive_response_headers', job_id: job.id, binding: report['binding'], collection_sha256: collectionSha,
        observed_at: collection['observed_at'], ...(this.tls ? { availability: report['availability'] } : { status: collection['status'] }),
        ...(this.redirects ? { availability: report['availability'] } : {}),
        fact: candidate.evidence, coverage: report['coverage'], interpretation: report['interpretation'] };
      if (!same(finding['evidence'], expected) || await selectionDigest([method, candidate.detector, expected]) !== finding['fingerprint']) throw new Error();
      if (this.chain && new TextEncoder().encode(JSON.stringify(canonical(expected))).length > 4096) throw new Error();
      lastId = Number(finding['id']); detectors.add(candidate.detector);
    }
    return structuredClone({ job, report, candidateDigest: row['candidate_digest'], findingSet: set }) as FindingInspection;
  }
  private async currentProjectScope(epoch: number) {
    const result = await this.api.projectOnboarding(this.organizationId, this.projectId);
    if (epoch !== this.epoch) return false;
    const project = result.body['project'];
    if (result.status !== 200 || !object(project) || project['id'] !== this.projectId || project['organization_id'] !== this.organizationId
      || typeof project['role'] !== 'string' || !['owner', 'admin'].includes(project['role']) || !Array.isArray(project['aliases'])
      || !same([project['canonical_origin'], ...project['aliases']], this.origins())) this.findingAuthorityLost();
    return true;
  }
  private async currentOriginalScope(report: Row, epoch: number) {
    if (this.chain) return this.currentChainScope(report['binding'] as Row, epoch);
    if (!await this.currentProjectScope(epoch) || epoch !== this.epoch) return false;
    const binding = report['binding'] as Row;
    const records = await this.api.originVerifications(this.organizationId, this.projectId);
    if (epoch !== this.epoch) return false;
    if (records.status !== 200 || !exact(records.body, ['verifications', 'has_more']) || !Array.isArray(records.body['verifications'])
      || records.body['verifications'].length > 100 || typeof records.body['has_more'] !== 'boolean') this.findingAuthorityLost();
    let verified: Verification | undefined;
    try { verified = records.body['verifications'].map(value => this.verification(value)).find(row => row.id === binding['verification_id']); }
    catch { this.findingAuthorityLost(); }
    if (!verified || verified.state !== 'verified' || verified.origin !== binding['origin'] || verified.verified_at !== binding['verified_at']) this.findingAuthorityLost();
    if (this.httpRedirects && !same(verified, this.verifications().find(row => row.id === verified!.id))) this.findingAuthorityLost();
    return true;
  }
  private findingAuthorityLost(): never {
    this.reset(); this.error.set('Current role, ownership or project scope unavailable. Original facts and local uncertainty cleared; stored facts may still exist. No replay.');
    throw new Error();
  }
  private async currentFindingScope(job: Job, report: Row | null, epoch: number) {
    if (!this.chain) return report ? this.currentOriginalScope(report, epoch) : true;
    try { return await this.currentChainMetadata(job, report ? report['binding'] as Row : null, epoch); }
    catch { if (epoch === this.epoch) this.findingAuthorityLost(); return false; }
  }
  async inspectFindings(id: number) {
    const job = this.jobs().find(row => row.id === id);
    if (!['headers', 'resources', 'tls', 'redirects', 'redirect-chain'].includes(this.family) || this.busy() || this.pending() || this.findingPending() || this.priorityPending() || !this.ready() || !positive(id)
      || !job || job.status !== 'succeeded' || job.cancel_requested || this.chain && job.error_category !== '') return;
    this.clearFindings(); this.candidateReport.set(null); this.selection.set(null); this.selected.set(null); this.evidence.set(null);
    const original = structuredClone(job); const epoch = ++this.epoch; this.busy.set(true); this.error.set(''); this.message.set('');
    try {
      if (!await this.currentFindingScope(original, null, epoch) || epoch !== this.epoch) return;
      const result = await this.requestFindings(id); if (epoch !== this.epoch) return;
      if ([401, 403, 404, 409].includes(result.status)) { this.reset(); this.error.set('Current original findings/source unavailable. Missing is not zero or a confirmed no-op.'); return; }
      const info = await this.validateFindings(result, original); if (epoch !== this.epoch) return;
      if (!await this.currentFindingScope(original, info.report, epoch) || epoch !== this.epoch) return;
      if (this.chain) this.chainCandidateJob = structuredClone(original);
      this.findingInspection.set(info); this.candidateReport.set(structuredClone(info.report));
    } catch { if (epoch === this.epoch) { if (this.chain) this.reset(); else this.clearFindings(); this.candidateReport.set(null); this.error.set('Current original findings/source unavailable. Missing is not zero or a confirmed no-op.'); } }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  async saveFindings() {
    const report = this.candidateReport(); const job = this.chain ? this.chainCandidateJob : this.jobs().find(row => row.id === report?.['job_id']);
    if (!['headers', 'resources', 'tls', 'redirects', 'redirect-chain'].includes(this.family) || this.busy() || this.pending() || this.findingPending() || this.priorityPending() || !this.ready() || !report
      || !job || job.status !== 'succeeded' || job.cancel_requested || this.chain && job.error_category !== '' || !this.candidateRows().length) return;
    const original = structuredClone(report); const originalJob = structuredClone(job); const epoch = ++this.epoch;
    this.clearFindings(); this.candidateReport.set(null); this.selection.set(null); this.selected.set(null); this.evidence.set(null);
    this.busy.set(true); this.error.set(''); this.message.set(''); let sent = false;
    try {
      if (this.chain) this.validateChainCandidates(original, originalJob);
      else if (this.redirects) this.validateRedirectCandidates(original, originalJob);
      else if (this.tls) this.validateTlsCandidates(original, originalJob);
      else if (this.resources) this.validateResourceCandidates(original, originalJob); else this.validateCandidates(original, originalJob);
      if (!await this.currentFindingScope(originalJob, original, epoch) || epoch !== this.epoch) return;
      const read = await this.requestFindings(originalJob.id); if (epoch !== this.epoch) return;
      if ([401, 403, 404, 409].includes(read.status)) { this.reset(); this.error.set('Current original source/authority unavailable. No fact-save command sent; inspect again.'); return; }
      const fresh = await this.validateFindings(read, originalJob); if (epoch !== this.epoch) return;
      if (!same(fresh.report, original)) throw new Error();
      if (!await this.currentFindingScope(originalJob, original, epoch) || epoch !== this.epoch) return;
      this.findingPending.set(structuredClone(fresh)); sent = true;
      const result = await this.requestFindings(originalJob.id, fresh.candidateDigest);
      if (epoch !== this.epoch) return;
      if (this.chain && (!await this.currentFindingScope(originalJob, original, epoch) || epoch !== this.epoch)) return;
      if ([401, 403, 404, 409].includes(result.status)) { this.reset(); this.error.set('Current original source/authority denied the save. Inspect again; no automatic replay.'); return; }
      const info = await this.validateFindings(result, originalJob); if (epoch !== this.epoch) return;
      if (!same(info.report, original) || info.findingSet['state'] !== 'current_materialized_facts') throw new Error();
      if (!await this.currentFindingScope(originalJob, original, epoch) || epoch !== this.epoch) return;
      if (this.chain) this.chainCandidateJob = structuredClone(originalJob);
      this.findingPending.set(null); this.findingInspection.set(info); this.candidateReport.set(structuredClone(info.report));
      this.message.set('The complete original fact set is currently retained; no personal attribution, human priority or site action is implied.');
    } catch { if (epoch === this.epoch) {
      this.findingInspection.set(null); this.candidateReport.set(null);
      this.error.set(sent ? 'Original fact-save outcome uncertain. Read the same job/set; no automatic POST replay.' : 'Current original source or role changed. No fact-save command sent; inspect again.');
    } }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  async reconcileFindings() {
    if (!['headers', 'resources', 'tls', 'redirects', 'redirect-chain'].includes(this.family) || this.busy() || !this.findingPending() || !this.ready()) return;
    const frozen = structuredClone(this.findingPending()!); const epoch = ++this.epoch;
    this.findingInspection.set(null); this.candidateReport.set(null); this.error.set(''); this.message.set(''); this.busy.set(true); let received = false;
    try {
      if (this.chain && (!await this.currentFindingScope(frozen.job, frozen.report, epoch) || epoch !== this.epoch)) return;
      const result = await this.requestFindings(frozen.job.id); if (epoch !== this.epoch) return;
      received = true;
      if (result.status !== 200) { this.reset(); this.error.set('Current same-job source/set unavailable. Local uncertainty cleared; stored facts may still exist. No replay.'); return; }
      const info = await this.validateFindings(result, frozen.job); if (epoch !== this.epoch) return;
      if (info.candidateDigest !== frozen.candidateDigest || !same(info.report, frozen.report)
        || frozen.findingSet['state'] === 'current_materialized_facts' && !same(info.findingSet, frozen.findingSet)) throw new Error();
      if (!await this.currentFindingScope(frozen.job, info.report, epoch) || epoch !== this.epoch) return;
      this.findingInspection.set(info);
      if (info.findingSet['state'] === 'current_materialized_facts') {
        if (this.chain) this.chainCandidateJob = structuredClone(frozen.job);
        this.findingPending.set(null); this.candidateReport.set(structuredClone(info.report));
        this.message.set('Current complete original fact set inspected. This does not identify who saved it. No command replayed.');
      } else this.message.set('No retained set at this current read. The earlier save outcome remains uncertain; this is not confirmed no-op or zero eligible candidates. No replay.');
    } catch { if (epoch === this.epoch) {
      if (received) this.clearFindings();
      this.candidateReport.set(null); this.error.set(received ? 'Original same-job source/set changed or became unavailable. Local uncertainty cleared; stored facts may still exist. No replay.'
        : 'Current lookup outcome unavailable; original memory-only save remains uncertain. No replay.');
    } }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  discardFindingCommand() {
    if (this.busy()) return;
    this.edit(); this.message.set('Local uncertainty discarded. Stored facts may still exist; independently inspect the current original job before another explicit save.');
  }
  findingRows(): Row[] { return this.findingInspection()?.findingSet['findings'] as Row[] ?? []; }
  priorityCanSave() {
    const info = this.priorityInspection(); const decision = info?.judgment['decision'] as Row | null;
    return !!info && (decision === null || Number(decision?.['revision']) < 65535);
  }
  editJudgment(field: string, value: string) {
    if (this.busy() || this.priorityPending() || !this.priorityInspection()) return;
    ++this.epoch; this.error.set(''); this.message.set('');
    if (field === 'priority') this.humanPriority.set(value);
    else if (field === 'estimated_effort') this.humanEffort.set(value);
    else if (field === 'business_relevance') this.humanRelevance.set(value);
    else if (field === 'reason') this.humanReason.set(value);
  }
  private requestPriority(id: number, findingId: number, data?: Row) {
    if (this.chain) return this.api.passiveRedirectChainPriority(this.organizationId, this.projectId, id, findingId, data);
    if (this.redirects) return this.api.passiveRedirectPriority(this.organizationId, this.projectId, id, findingId, data);
    if (this.tls) return this.api.passiveTlsPriority(this.organizationId, this.projectId, id, findingId, data);
    if (this.resources) return this.api.passiveResourcePriority(this.organizationId, this.projectId, id, findingId, data);
    return this.api.passiveHeaderPriority(this.organizationId, this.projectId, id, findingId, data);
  }
  private validatePriority(result: ApiResult, original: FindingInspection, findingId: number): Row {
    const row = this.scope(result); const value = row['prioritization'];
    const finding = (original.findingSet['findings'] as Row[]).find(item => item['id'] === findingId);
    if (!finding || !exact(row, ['organization_id', 'project_id', 'prioritization'])
      || !exact(value, ['method_version', 'source', 'decision', 'reviewed_at', 'interpretation'])
      || value['method_version'] !== 'passive-human-prioritization-v1'
      || value['interpretation'] !== 'human_priority_not_measured_risk_severity_recommendation_approval_or_page_action') throw new Error();
    const source = value['source'];
    if (!exact(source, ['method_version', 'organization_id', 'project_id', 'job_id', 'source_current', 'finding', 'source_sha256', 'interpretation'])
      || source['method_version'] !== 'passive-finding-review-source-v1' || source['organization_id'] !== this.organizationId
      || source['project_id'] !== this.projectId || source['job_id'] !== original.job.id || source['source_current'] !== true
      || !digest(source['source_sha256']) || !same(source['finding'], finding)
      || source['interpretation'] !== 'original_passive_fact_for_human_prioritization_not_severity_approval_or_page_action') throw new Error();
    const decision = value['decision'];
    if (decision === null) { if (value['reviewed_at'] !== null) throw new Error(); }
    else if (!exact(decision, ['id', 'revision', 'priority', 'estimated_effort', 'business_relevance', 'review_reason'])
      || !positive(decision['id']) || !Number.isInteger(decision['revision']) || Number(decision['revision']) < 1 || Number(decision['revision']) > 65535
      || typeof decision['priority'] !== 'string' || !PRIORITIES.includes(decision['priority'])
      || typeof decision['estimated_effort'] !== 'string' || !EFFORTS.includes(decision['estimated_effort'])
      || typeof decision['business_relevance'] !== 'string' || !RELEVANCES.includes(decision['business_relevance']) || typeof decision['review_reason'] !== 'string'
      || !decision['review_reason'].length || decision['review_reason'] !== decision['review_reason'].trim()
      || [...decision['review_reason']].length > 240 || !ordered(finding['detected_at'], value['reviewed_at'])) throw new Error();
    return structuredClone(value);
  }
  private async currentPriority(info: PriorityInspection, epoch: number) {
    if (!await this.currentFindingScope(info.original.job, info.original.report, epoch) || epoch !== this.epoch) return null;
    const facts = await this.requestFindings(info.original.job.id); if (epoch !== this.epoch) return null;
    const fresh = await this.validateFindings(facts, info.original.job); if (epoch !== this.epoch) return null;
    if (!same(fresh, info.original)) throw new Error();
    if (this.chain && (!await this.currentFindingScope(info.original.job, info.original.report, epoch) || epoch !== this.epoch)) return null;
    const result = await this.requestPriority(info.original.job.id, info.findingId); if (epoch !== this.epoch) return null;
    const judgment = this.validatePriority(result, info.original, info.findingId);
    if (!await this.currentFindingScope(info.original.job, info.original.report, epoch) || epoch !== this.epoch) return null;
    return judgment;
  }
  private showPriority(info: PriorityInspection) {
    this.priorityPending.set(null); this.priorityInspection.set(structuredClone(info));
    this.findingInspection.set(structuredClone(info.original)); this.candidateReport.set(structuredClone(info.original.report));
    const decision = info.judgment['decision'] as Row | null;
    this.humanPriority.set(String(decision?.['priority'] ?? 'unprioritized')); this.humanEffort.set(String(decision?.['estimated_effort'] ?? 'unknown'));
    this.humanRelevance.set(String(decision?.['business_relevance'] ?? 'unknown')); this.humanReason.set(String(decision?.['review_reason'] ?? ''));
  }
  async inspectPriority(findingId: number) {
    const original = this.findingInspection();
    if (!['headers', 'resources', 'tls', 'redirects', 'redirect-chain'].includes(this.family) || this.busy() || this.pending() || this.findingPending() || this.priorityPending() || !this.ready() || !original || !positive(findingId)
      || !(original.findingSet['findings'] as Row[]).some(row => row['id'] === findingId)) return;
    const info = structuredClone({ original, findingId, judgment: {} }); this.clearPriority();
    const epoch = ++this.epoch; this.busy.set(true); this.error.set(''); this.message.set('');
    try {
      const judgment = await this.currentPriority(info, epoch); if (!judgment || epoch !== this.epoch) return;
      this.showPriority({ ...info, judgment });
    } catch { if (epoch === this.epoch) { this.clearFindings(); this.candidateReport.set(null); this.error.set('Current exact fact or human judgment unavailable. Inspect the original job again.'); } }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  async savePriority(event?: Event) {
    event?.preventDefault();
    if (!['headers', 'resources', 'tls', 'redirects', 'redirect-chain'].includes(this.family) || this.busy() || this.pending() || this.findingPending() || this.priorityPending() || !this.ready() || !this.priorityCanSave()) return;
    const info = structuredClone(this.priorityInspection()!); const reason = this.humanReason().trim();
    if (!PRIORITIES.includes(this.humanPriority()) || !EFFORTS.includes(this.humanEffort()) || !RELEVANCES.includes(this.humanRelevance())
      || !reason || [...reason].length > 240) { this.error.set('Choose bounded human judgments and a nonempty review reason of at most 240 characters.'); return; }
    const decision = info.judgment['decision'] as Row | null;
    const command = { source_sha256: (info.judgment['source'] as Row)['source_sha256'], expected_revision: decision?.['revision'] ?? 0,
      priority: this.humanPriority(), estimated_effort: this.humanEffort(), business_relevance: this.humanRelevance(), reason };
    const epoch = ++this.epoch; this.busy.set(true); this.error.set(''); this.message.set(''); let sent = false; let received = false;
    try {
      const fresh = await this.currentPriority(info, epoch); if (!fresh || epoch !== this.epoch) return;
      if (!same(fresh, info.judgment)) throw new Error();
      this.priorityPending.set(structuredClone({ ...info, command })); this.priorityInspection.set(null);
      sent = true; const result = await this.requestPriority(info.original.job.id, info.findingId, command); if (epoch !== this.epoch) return;
      received = true; const judgment = this.validatePriority(result, info.original, info.findingId); const saved = judgment['decision'] as Row | null;
      if (!same(judgment['source'], info.judgment['source']) || !saved || saved['revision'] !== Number(command.expected_revision) + 1
        || saved['priority'] !== command.priority || saved['estimated_effort'] !== command.estimated_effort
        || saved['business_relevance'] !== command.business_relevance || saved['review_reason'] !== reason
        || decision && (saved['id'] === decision['id'] || !ordered(info.judgment['reviewed_at'], judgment['reviewed_at']))) throw new Error();
      if (!await this.currentFindingScope(info.original.job, info.original.report, epoch) || epoch !== this.epoch) return;
      this.showPriority({ ...info, judgment }); this.message.set('Current source-bound human judgment inspected. No personal attribution, severity or site approval is implied.');
    } catch { if (epoch === this.epoch) {
      if (!sent || received) { this.clearFindings(); this.candidateReport.set(null); }
      this.error.set(sent && !received ? 'Human judgment command outcome uncertain. Read the same original fact; no automatic POST replay.'
        : 'Original source, current human revision or authority changed. Local judgment cleared; inspect again. No replay.');
    } }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  async reconcilePriority() {
    if (!['headers', 'resources', 'tls', 'redirects', 'redirect-chain'].includes(this.family) || this.busy() || !this.priorityPending() || !this.ready()) return;
    const frozen = structuredClone(this.priorityPending()!); const epoch = ++this.epoch;
    this.busy.set(true); this.error.set(''); this.message.set(''); let received = false;
    try {
      // A network failure leaves only frozen memory; any received invalid/foreign source clears it.
      if (!await this.currentFindingScope(frozen.original.job, frozen.original.report, epoch) || epoch !== this.epoch) return;
      const facts = await this.requestFindings(frozen.original.job.id); if (epoch !== this.epoch) return;
      received = true; const fresh = await this.validateFindings(facts, frozen.original.job); if (epoch !== this.epoch) return;
      if (!same(fresh, frozen.original)) throw new Error();
      if (this.chain && (!await this.currentFindingScope(frozen.original.job, frozen.original.report, epoch) || epoch !== this.epoch)) return;
      received = false; const result = await this.requestPriority(frozen.original.job.id, frozen.findingId); if (epoch !== this.epoch) return;
      received = true; const judgment = this.validatePriority(result, frozen.original, frozen.findingId);
      if (!same(judgment['source'], frozen.judgment['source'])) throw new Error();
      if (!await this.currentFindingScope(frozen.original.job, frozen.original.report, epoch) || epoch !== this.epoch) return;
      const decision = judgment['decision'] as Row | null; const command = frozen.command;
      const previous = frozen.judgment['decision'] as Row | null;
      if (decision && previous && Number(decision['revision']) > Number(previous['revision'])
        && (decision['id'] === previous['id'] || !ordered(frozen.judgment['reviewed_at'], judgment['reviewed_at']))) throw new Error();
      const matches = decision && decision['revision'] === Number(command['expected_revision']) + 1
        && decision['priority'] === command['priority'] && decision['estimated_effort'] === command['estimated_effort']
        && decision['business_relevance'] === command['business_relevance'] && decision['review_reason'] === command['reason'];
      if (matches) {
        this.showPriority({ original: frozen.original, findingId: frozen.findingId, judgment });
        this.message.set('Current retained matching human judgment inspected; this does not identify who saved it. No command replayed.');
      } else if (same(judgment, frozen.judgment)) {
        this.message.set('No matching new judgment at this read. The earlier command remains uncertain, not confirmed no-op. No replay.');
      } else {
        this.clearFindings(); this.candidateReport.set(null);
        this.message.set('A different current human revision requires fresh deliberate inspection and review. Local command cleared; no replay or attribution.');
      }
    } catch { if (epoch === this.epoch) {
      if (received) { this.clearFindings(); this.candidateReport.set(null); }
      this.error.set(received ? 'Original source or current judgment unavailable or changed. Local uncertainty cleared; a stored judgment may exist. No replay.'
        : 'Current lookup unavailable; the original memory-only human command remains uncertain. No replay.');
    } }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  discardPriorityCommand() {
    if (this.busy()) return;
    this.edit(); this.message.set('Local human command discarded. A stored judgment may exist; inspect the original fact before a new deliberate review.');
  }
  private validateTlsEvidence(value: unknown, job: Job) {
    if (!exact(value, ['job_id', 'collection', 'source_current']) || value['job_id'] !== job.id || value['source_current'] !== true
      || job.status !== 'succeeded' || job.cancel_requested || !exact(value['collection'], ['method', 'origin', 'observed_at', 'evidence', 'interpretation'])) throw new Error();
    const source = value['collection']; const observed = source['observed_at'];
    if (source['method'] !== 'passive-tls-evidence-v1' || source['interpretation'] !== TLS_MEANING || !this.canonicalOrigin(source['origin'])
      || !this.origins().includes(source['origin']) || !canonicalDate(observed) || !ordered(job.created_at, observed) || !ordered(observed, job.updated_at)) throw new Error();
    const info = source['evidence'];
    if (!exact(info, ['method_version', 'origin', 'observed_at', 'certificate_dates', 'negotiated_tls', 'coverage', 'interpretation'])
      || info['method_version'] !== 'passive-tls-handshake-v1' || info['origin'] !== source['origin'] || info['observed_at'] !== observed
      || info['coverage'] !== 'one_default_context_hostname_chain_validated_handshake_only' || info['interpretation'] !== TLS_TRANSPORT_MEANING) throw new Error();
    const dates = info['certificate_dates'];
    if (!exact(dates, ['method_version', 'coverage', 'interpretation', 'observed_at', 'state', 'not_before', 'not_after', 'position', 'remaining_microseconds'])
      || dates['method_version'] !== 'passive-peer-certificate-dates-v1' || dates['coverage'] !== 'one_original_peer_certificate_reported_date_interval_only'
      || dates['interpretation'] !== DATE_MEANING || dates['observed_at'] !== observed) throw new Error();
    if (dates['state'] === 'unavailable') {
      if (['not_before', 'not_after', 'position', 'remaining_microseconds'].some(key => dates[key] !== null)) throw new Error();
    } else if (dates['state'] === 'observed') {
      if (!canonicalDate(dates['not_before']) || !canonicalDate(dates['not_after'])) throw new Error();
      const start = microseconds(dates['not_before'])!; const end = microseconds(dates['not_after'])!; const stamp = microseconds(observed)!;
      const position = stamp < start ? 'before_reported_window' : stamp > end ? 'after_reported_window' : 'within_reported_window';
      if (start > end || start % 1000000n !== 0n || end % 1000000n !== 0n || dates['position'] !== position
        || typeof dates['remaining_microseconds'] !== 'string' || dates['remaining_microseconds'] !== String(end - stamp)) throw new Error();
    } else throw new Error();
    const negotiated = info['negotiated_tls'];
    if (!exact(negotiated, ['version', 'cipher']) || negotiated['version'] !== null && (typeof negotiated['version'] !== 'string'
      || !['TLSv1', 'TLSv1.1', 'TLSv1.2', 'TLSv1.3'].includes(negotiated['version']))) throw new Error();
    const cipher = negotiated['cipher'];
    if (cipher !== null && (!exact(cipher, ['name', 'secret_bits']) || typeof cipher['name'] !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(cipher['name'])
      || !Number.isInteger(cipher['secret_bits']) || Number(cipher['secret_bits']) < 1 || Number(cipher['secret_bits']) > 512)) throw new Error();
  }
  private validateResourceEvidence(value: unknown, job: Job) {
    if (!exact(value, ['job_id', 'collection', 'source_current']) || value['job_id'] !== job.id || value['source_current'] !== true
      || job.status !== 'succeeded' || job.cancel_requested || !exact(value['collection'], ['method', 'url', 'status', 'observed_at', 'evidence', 'interpretation'])) throw new Error();
    const source = value['collection']; const observed = source['observed_at']; const url = source['url'];
    if (source['method'] !== 'passive-resource-evidence-v1' || source['interpretation'] !== RESOURCE_MEANING || source['status'] !== 200
      || typeof url !== 'string' || url.length > 1024 || safeUrl(url) !== url || /[?#]/.test(url) || !this.origins().includes(new URL(url).origin)
      || !canonicalDate(observed) || !ordered(job.created_at, observed) || !ordered(observed, job.updated_at)) throw new Error();
    const info = source['evidence'];
    if (!exact(info, ['method_version', 'observed_at', 'coverage', 'interpretation', 'resource_references'])
      || info['method_version'] !== 'passive-resource-response-v1' || info['observed_at'] !== observed
      || info['coverage'] !== 'one_complete_length_framed_utf8_html_response_only' || info['interpretation'] !== RESOURCE_TRANSPORT_MEANING) throw new Error();
    const refs = info['resource_references'];
    if (!exact(refs, ['method_version', 'state', 'reason', 'coverage', 'selected_attributes', 'excluded', 'interpretation', 'counts'])
      || refs['method_version'] !== 'passive-static-resource-references-v1' || refs['coverage'] !== 'selected_literal_static_resource_attributes_only'
      || !same(refs['selected_attributes'], RESOURCE_ATTRIBUTES) || refs['excluded'] !== 'navigation_css_srcset_javascript_dynamic_media_inert_rawtext_and_foreign_descendants'
      || refs['interpretation'] !== 'literal_reference_candidates_not_browser_requests_mixed_content_policy_or_whole_page_security'
      || !exact(refs['counts'], RESOURCE_COUNTS)) throw new Error();
    const counts = refs['counts'];
    if (refs['state'] === 'observed') {
      if (refs['reason'] !== '' || Object.values(counts).some(value => !Number.isInteger(value) || Number(value) < 0 || Number(value) > 1000)
        || counts['inspected_attributes'] !== Number(counts['http_absolute']) + Number(counts['https_absolute']) + Number(counts['unclassified'])) throw new Error();
    } else if (refs['state'] === 'unavailable') {
      if (typeof refs['reason'] !== 'string' || !['invalid_body', 'ambiguous_markup', 'reference_limit'].includes(refs['reason']) || Object.values(counts).some(value => value !== null)) throw new Error();
    } else throw new Error();
  }
  private validateRedirectEvidence(value: unknown, job: Job, http = this.httpRedirects) {
    if (!exact(value, ['job_id', 'collection', 'source_current']) || value['job_id'] !== job.id || value['source_current'] !== true
      || job.status !== 'succeeded' || job.cancel_requested || !exact(value['collection'], ['method', 'url', 'status', 'observed_at', 'evidence', 'interpretation'])) throw new Error();
    const source = value['collection']; const observed = source['observed_at']; const url = source['url']; const status = source['status'];
    if (source['method'] !== (http ? 'passive-http-redirect-evidence-v1' : 'passive-redirect-evidence-v1')
      || source['interpretation'] !== (http ? HTTP_MEANING : REDIRECT_MEANING)
      || !Number.isInteger(status) || Number(status) < 200 || Number(status) > 599
      || typeof url !== 'string' || url.length > 1024 || (http ? safeHttpUrl(url) : safeUrl(url)) !== url || /[?#]/.test(url) || !this.origins().includes(new URL(url).origin)
      || !canonicalDate(observed) || !ordered(job.created_at, observed) || !ordered(observed, job.updated_at)) throw new Error();
    const info = source['evidence'];
    if (!exact(info, ['method_version', 'observed_at', 'coverage', 'interpretation', 'response_location'])
      || info['method_version'] !== (http ? 'passive-http-redirect-response-v1' : 'passive-redirect-response-v1') || info['observed_at'] !== observed
      || info['coverage'] !== (http ? 'one_original_first_http_response_only' : 'one_original_first_https_response_only')
      || info['interpretation'] !== (http ? HTTP_MEANING : REDIRECT_TRANSPORT_MEANING)) throw new Error();
    this.validateLocation(info['response_location'], status, http);
  }
  private validateLocation(location: unknown, status: unknown, http: boolean) {
    if (!exact(location, ['method_version', 'state', 'response_status', 'redirect_status', 'location_state', 'target_scheme', 'same_origin',
      ...(http ? ['same_hostname_default_https'] : []), 'coverage', 'interpretation'])
      || location['method_version'] !== (http ? 'passive-http-response-location-v1' : 'passive-response-location-v1') || location['state'] !== 'observed' || location['response_status'] !== status
      || typeof location['redirect_status'] !== 'boolean' || location['redirect_status'] !== [301, 302, 303, 307, 308].includes(Number(status))
      || location['coverage'] !== 'one_complete_original_response_status_and_location_fields_only'
      || location['interpretation'] !== (http ? HTTP_LOCATION_MEANING : REDIRECT_MEANING)) throw new Error();
    if (location['location_state'] === 'single_classified') {
      if (typeof location['target_scheme'] !== 'string' || !['http', 'https'].includes(location['target_scheme'])
        || typeof location['same_origin'] !== 'boolean'
        || location['target_scheme'] === (http ? 'https' : 'http') && location['same_origin']
        || http && (typeof location['same_hostname_default_https'] !== 'boolean'
          || location['target_scheme'] === 'http' && location['same_hostname_default_https'])) throw new Error();
    } else if (typeof location['location_state'] !== 'string' || !['absent', 'present_empty', 'multiple_fields', 'single_unclassified'].includes(location['location_state'])
      || location['target_scheme'] !== null || location['same_origin'] !== null
      || http && location['same_hostname_default_https'] !== null) throw new Error();
  }
  private validateChainEvidence(value: unknown, job: Job) {
    if (!exact(value, ['job_id', 'collection', 'source_current', 'binding']) || value['job_id'] !== job.id || value['source_current'] !== true
      || job.status !== 'succeeded' || job.cancel_requested || job.error_category !== '' || !object(value['binding'])
      || !exact(value['collection'], ['method', 'url', 'final_url', 'status', 'observed_at', 'last_observed_at', 'evidence', 'interpretation'])) throw new Error();
    const binding = value['binding']; this.validateChainBinding(binding, binding);
    const source = value['collection']; const info = source['evidence']; const allowed = this.chainUrls(binding);
    if (new TextEncoder().encode(JSON.stringify(source)).length > 24576 || source['method'] !== CHAIN_METHOD || source['url'] !== binding['url']
      || source['interpretation'] !== CHAIN_MEANING || !exact(info, ['method_version', 'hops', 'state', 'coverage', 'interpretation'])
      || info['method_version'] !== 'passive-exact-redirect-chain-response-v1' || info['coverage'] !== 'at_most_six_selected_original_header_responses_only'
      || info['interpretation'] !== CHAIN_MEANING || typeof info['state'] !== 'string'
      || ![...TARGET_STATES.slice(1), 'redirect_loop', 'redirect_limit'].includes(info['state'])
      || !Array.isArray(info['hops']) || info['hops'].length < 1 || info['hops'].length > 6) throw new Error();
    const hops = info['hops']; const seen: string[] = []; let previous: Row | null = null;
    const matches = (location: Row, current: string, target: string) => {
      const from = new URL(current); const to = new URL(target);
      return location['target_scheme'] === to.protocol.slice(0, -1) && location['same_origin'] === (from.origin === to.origin)
        && (from.protocol !== 'http:' || location['same_hostname_default_https'] === (to.protocol === 'https:' && from.hostname === to.hostname));
    };
    for (const hop of hops) {
      if (!exact(hop, ['url', 'status', 'observed_at', 'response_location', 'target_state']) || typeof hop['url'] !== 'string'
        || !allowed.includes(hop['url']) || seen.includes(hop['url']) || !Number.isInteger(hop['status']) || Number(hop['status']) < 200 || Number(hop['status']) > 599
        || !canonicalDate(hop['observed_at']) || !ordered(job.created_at, hop['observed_at']) || !ordered(hop['observed_at'], job.updated_at)
        || (binding['origins'] as Row[]).some(row => !ordered(row['verified_at'], hop['observed_at']))
        || typeof hop['target_state'] !== 'string' || !TARGET_STATES.includes(hop['target_state'])) throw new Error();
      this.validateLocation(hop['response_location'], hop['status'], hop['url'].startsWith('http://'));
      const location = hop['response_location'] as Row; const state = hop['target_state'];
      if (!location['redirect_status'] ? state !== 'terminal_response' : location['location_state'] !== 'single_classified'
        ? state !== 'location_unavailable' : !['permitted_target', 'unsupported_target', 'outside_exact_target_allowlist'].includes(state)) throw new Error();
      if (previous ? previous['target_state'] !== 'permitted_target' || !ordered(previous['observed_at'], hop['observed_at'])
        || !matches(previous['response_location'] as Row, previous['url'] as string, hop['url']) : hop['url'] !== binding['url']) throw new Error();
      seen.push(hop['url']); previous = hop;
    }
    const last = previous!; const stop = info['state'];
    if (stop === 'redirect_loop' || stop === 'redirect_limit') {
      const candidates = stop === 'redirect_loop' ? seen : allowed.filter(url => !seen.includes(url));
      if (last['target_state'] !== 'permitted_target' || !candidates.some(url => matches(last['response_location'] as Row, last['url'] as string, url))) throw new Error();
    } else if (stop !== last['target_state']) throw new Error();
    if (source['final_url'] !== last['url'] || !Number.isInteger(source['status']) || source['status'] !== last['status']
      || source['observed_at'] !== hops[0]['observed_at'] || source['last_observed_at'] !== last['observed_at']) throw new Error();
  }
  async createChallenge() { if (!this.origins().includes(this.origin())) return; await this.ownership('create', this.origin()); }
  async verify(row: Verification) { if (row.state !== 'pending' || !this.origins().includes(row.origin)) return; await this.ownership('verify', row.origin, row.id); }
  async revoke(row: Verification) { if (row.state === 'revoked') return; await this.ownership('revoke', row.origin, row.id); }
  private async ownership(action: string, origin: string, id?: number) {
    if (this.busy() || this.pending() || this.priorityPending() || !this.ready()) return;
    this.edit(); const epoch = this.epoch; this.busy.set(true);
    if (this.getOnlyUncertainty) this.permission.set(false);
    try {
      const result = await this.api.originVerifications(this.organizationId, this.projectId, action === 'revoke' ? 'DELETE' : 'POST',
        action === 'create' ? { origin } : action === 'verify' ? { idempotency_key: crypto.randomUUID() } : undefined, id);
      if (epoch !== this.epoch) return;
      if (result.status !== (action === 'create' ? 201 : action === 'verify' ? 202 : 200)) throw new Error();
      const verification = this.verification(result.body['verification']); if (verification.origin !== origin || id !== undefined && verification.id !== id) throw new Error();
      if (action === 'create') {
        const challenge = result.body['challenge']; if (!exact(challenge, ['path', 'content']) || challenge['path'] !== PATH
          || typeof challenge['content'] !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(challenge['content']) || verification.state !== 'pending') throw new Error();
        this.challenge.set({ origin, content: challenge['content'] });
      } else if (action === 'revoke' && (verification.state !== 'revoked' || typeof result.body['revoked'] !== 'boolean')) throw new Error();
      else if (action === 'verify' && (!object(result.body['job']) || !positive(result.body['job']['id'])
        || result.body['job']['handler'] !== 'verify_project_origin' || typeof result.body['job']['status'] !== 'string'
        || !['queued', 'running', 'succeeded', 'failed', 'cancelled'].includes(result.body['job']['status']))) throw new Error();
      this.verifications.update(rows => [...rows.filter(row => row.id !== verification.id), verification]);
      this.message.set(action === 'verify' ? 'Ownership check queued, not proof of verification. Refresh current state; no check replayed automatically.'
        : action === 'create' ? 'Deploy the once-shown exact file, then explicitly request the ownership check.' : 'Exact origin verification revoked.');
    } catch { if (epoch === this.epoch) { this.challenge.set(null); this.message.set('Ownership command outcome uncertain or denied. Refresh exact state; no automatic replay. A lost challenge cannot be retrieved; rotate deliberately if needed.'); } }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
}
