import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, OnInit, computed, effect, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi, ApiResult } from '../account/account-api';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';

const METHOD = 'visibility-human-answer-v1'; const SOURCE = 'customer_owned_manual_answer'; const SURFACE = 'customer_reported_answer';
type Intake = Record<string, string | number | boolean>;
type Match = { kind: string; entity: string; start: number; end: number; decision: string; note: string };
type Observation = { id: number; project_id: number; observation_id: string; revision: number; intake: Intake; reason: string;
  source_current: boolean; is_latest: boolean; evaluated: boolean; matches: Match[]; created_at: string;
  verification_id: number; verified_at: string; actor_id: number;
  basis: string; comparison_context: Record<string, unknown>; preview: { matches: Match[]; has_more: boolean; links: unknown[] } };
type Mapping = { review_id: number; label: string; language: string; market: string; source_current: boolean };
type Context = { organization_id: number; project_id: number; method_version: string; source_kind: string; surface: string;
  can_review: boolean; configuration_revision: number | null; market: string; languages: string[]; brand_aliases: string[];
  verified_origins: string[]; intent_reviews: Mapping[]; observations: Observation[]; has_more: boolean; sources_has_more: boolean };
type Rate = { numerator: number; denominator: number; percent: string | null; state: string };
type RateGroup = { comparison_key: string; context: Record<string, unknown>; report_ids: number[]; eligible_report_ids: number[];
  mention_rate: Rate; statuses: Record<string, number>; exclusions: Record<string, number>; competitor_mention_rates: Record<string, Rate> };
type Rates = { project_id: number; organization_id: number; method: string; surface: string; groups: RateGroup[]; has_more: boolean;
  scope: string; external_cost: null; referrals: null };
type Command = { data: Record<string, unknown>; observationId?: string };
const positive = (value: unknown) => Number.isSafeInteger(value) && Number(value) > 0;
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every((item) => typeof item === 'string');
const flatEqual = (a: Record<string, unknown>, b: Record<string, unknown>) => Object.keys(a).length === Object.keys(b).length && Object.entries(a).every(([key, value]) => b[key] === value);

function isRate(value: unknown, denominator: number): value is Rate {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const row = value as Rate;
  if (row.denominator !== denominator || !Number.isSafeInteger(row.numerator)
    || row.numerator < 0 || row.numerator > denominator) return false;
  if (!denominator) return row.state === 'unavailable' && row.percent === null;
  // Match the source's Decimal half-even rounding using integers in its <=100-report window.
  const scaled = row.numerator * 10000, whole = Math.floor(scaled / denominator), remainder = scaled % denominator;
  const rounded = whole + (remainder * 2 > denominator || remainder * 2 === denominator && whole % 2 === 1 ? 1 : 0);
  return row.state === 'sampled_human_evaluated' && row.percent === (rounded / 100).toFixed(2);
}

function isMatch(value: unknown): value is Match {
  if (!value || typeof value !== 'object') return false;
  const row = value as Match;
  return ['brand', 'competitor', 'project_domain', 'competitor_domain', 'other_domain'].includes(row.kind)
    && typeof row.entity === 'string' && typeof row.note === 'string' && ['confirmed', 'rejected', 'uncertain'].includes(row.decision)
    && Number.isSafeInteger(row.start) && row.start >= 0 && positive(row.end) && row.end > row.start;
}
function isObservation(value: unknown, project: number): value is Observation {
  if (!value || typeof value !== 'object') return false;
  const row = value as Observation; const input = row.intake;
  return positive(row.id) && row.project_id === project && positive(row.revision) && typeof row.observation_id === 'string'
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(row.observation_id)
    && typeof row.reason === 'string' && typeof row.created_at === 'string' && typeof row.source_current === 'boolean'
    && typeof row.is_latest === 'boolean' && typeof row.evaluated === 'boolean' && row.basis === 'human_report_not_consumer_or_provider_verified'
    && positive(row.verification_id) && positive(row.actor_id) && typeof row.verified_at === 'string'
    && !!input && input['method_version'] === METHOD && input['source_kind'] === SOURCE && input['surface'] === SURFACE
    && positive(input['configuration_revision']) && positive(input['intent_review_id']) && positive(input['prompt_version'])
    && ['storage_permission', 'not_response_only_copy', 'no_personal_payload'].every((key) => input[key] === true)
    && ['origin', 'prompt', 'prompt_kind', 'requested_market', 'requested_language', 'source_label', 'observation_reference',
      'observed_at', 'reported_model', 'reported_retrieval', 'applied_location', 'applied_language', 'applied_device', 'status',
      'answer', 'evidence_note'].every((key) => typeof input[key] === 'string')
    && ['complete', 'partial', 'unavailable'].includes(String(input['status']))
    && Array.isArray(row.matches) && row.matches.every(isMatch) && !!row.preview && Array.isArray(row.preview.matches)
    && row.preview.matches.every(isMatch) && typeof row.preview.has_more === 'boolean' && Array.isArray(row.preview.links)
    && !!row.comparison_context && typeof row.comparison_context === 'object';
}

const visibilityManualTurkish: Record<string, string> = {
  "Private permitted human answer reports": "Özel izin verilmiş insan yanıtı raporları",
  "Independently permitted human answer reports": "Bağımsız olarak izin verilmiş insan yanıtı raporları",
  "Organization": "Kuruluş",
  "· project": "· proje",
  "Project evidence": "Proje kanıtları",
  "Review genuine intents": "Gerçek niyetleri inceleyin",
  "Project configuration and ownership": "Proje yapılandırması ve sahiplik",
  "Separate API sample history": "Ayrı API örnek geçmişi",
  "Customer-reported source, model, retrieval and applied context are not independently verified. No consumer account is automated, licensed or verified here. This saves your independently permitted human report; no provider request, job, usage charge or schedule runs. Manual reports and native API samples have separate denominators. Text links are not measured citations; referrals and external costs are unknown.": "Müşterinin bildirdiği kaynak, model, bilgi getirme ve uygulanan bağlam bağımsız olarak doğrulanmamıştır. Burada tüketici hesabı otomatikleştirilmez, lisanslanmaz veya doğrulanmaz. Bu, bağımsız olarak izin verilmiş insan raporunuzu kaydeder; sağlayıcı isteği, iş, kullanım ücreti veya zamanlama çalışmaz. Manuel raporlar ve yerel API örnekleri ayrı paydalara sahiptir. Metin bağlantıları ölçülmüş atıflar değildir; yönlendirmeler ve dış maliyetler bilinmez.",
  "Use only independently authorized prompt/answer evidence. No secrets, personal customer conversations, account identities, screenshots or copies of response-only Google/YouTube API content. Enter coarse applied context or leave it unknown; requested market/language does not prove applied location, language or device. Rights declarations do not grant a provider license; actual terms/privacy remain unverified.": "Yalnızca bağımsız olarak yetkilendirilmiş istem/yanıt kanıtlarını kullanın. Sırlar, kişisel müşteri konuşmaları, hesap kimlikleri, ekran görüntüleri veya yalnızca yanıtta kullanılabilen Google/YouTube API içeriğinin kopyaları dahil edilmez. Uygulanan bağlamı kaba düzeyde girin veya bilinmeyen bırakın; istenen pazar/dil uygulanan konumu, dili veya cihazı kanıtlamaz. Hak beyanları sağlayıcı lisansı vermez; gerçek koşullar/gizlilik henüz doğrulanmamıştır.",
  "Private D098 lifecycle: 90-day retained access after lapse; active deletion within 30 days of closure/retention expiry; customer backups expire up to 35 days after active deletion. Private exports are historical reports, not current-use permission.": "Özel D098 yaşam döngüsü: sona ermeden sonra90gün saklanan erişim; kapanma/saklama süresi sonundan itibaren30gün içinde aktif silme; müşteri yedekleri aktif silmeden sonra en fazla35gün içinde sona erer. Özel dışa aktarımlar geçmiş raporlardır, güncel kullanım izni değildir.",
  "Loading private reports and separate eligible denominators.": "Özel raporlar ve ayrı uygun paydalar yükleniyor.",
  "Save outcome uncertain. The exact command is frozen in component memory; no automatic replay.": "Kaydetme sonucu belirsiz. Tam komut bileşen belleğinde dondurulmuştur; otomatik yeniden oynatma yoktur.",
  "Check uncertain exact request": "Belirsiz tam isteği kontrol edin",
  "Deliberately retry same exact report": "Aynı tam raporu bilinçli olarak yeniden deneyin",
  "Refresh current authority and evidence": "Güncel yetkiyi ve kanıtları yenileyin",
  "Current authority is as of refresh. Every command rechecks verified owner/admin, current intent/configuration and exact verified origin.": "Güncel yetki yenileme anına aittir. Her komut doğrulanmış sahibi/yöneticiyi, güncel niyeti/yapılandırmayı ve tam doğrulanmış kökeni yeniden kontrol eder.",
  "Latest human reports (up to 50)": "Son insan raporları (en fazla50)",
  "No customer answer report exists; visibility is unavailable, not zero.": "Müşteri yanıt raporu yok; görünürlük kullanılamıyor, sıfır değil.",
  "This latest-report view is bounded and incomplete.": "Bu son rapor görünümü sınırlı ve eksiktir.",
  "· revision": "· revizyon",
  "Original observation": "Özgün gözlem",
  "· correction/evaluation recorded": "· kaydedilen düzeltme/değerlendirme",
  "Project-origin authority": "Proje kökeni yetkisi",
  "· verified": "· doğrulandı",
  "· attesting actor": "· beyan eden aktör",
  ". This is website authority, not consumer-answer verification.": ". Bu web sitesi yetkisidir, tüketici yanıtı doğrulaması değildir.",
  "Reported source": "Bildirilen kaynak",
  "/ model": "/ model",
  "/ retrieval": "/ bilgi getirme",
  "Requested": "İstenen",
  ". Applied (customer report):": ". Uygulanan (müşteri bildirimi):",
  "Prompt version": "İstem sürümü",
  "· intent review": "· niyet incelemesi",
  "Exact comparable context, entity spans and safe-syntax link evidence (never fetched)": "Tam karşılaştırılabilir bağlam, varlık aralıkları ve güvenli sözdizimli bağlantı kanıtları (hiçbir zaman getirilmez)",
  "Candidate extraction truncated; an evaluated negative is unavailable.": "Aday çıkarımı kesildi; değerlendirilmiş bir olumsuz sonuç kullanılamaz.",
  "Inspect immutable history": "Değiştirilemez geçmişi inceleyin",
  "Correct report; reset evaluation": "Raporu düzeltin; değerlendirmeyi sıfırlayın",
  "Review exact full-answer entity spans": "Tam yanıtın kesin varlık aralıklarını inceleyin",
  "Immutable original and corrected evidence (newest 20 revisions)": "Değiştirilemez özgün ve düzeltilmiş kanıtlar (en yeni20revizyon)",
  "Revision": "Revizyon",
  "· observed": "· gözlendi",
  "· recorded": "· kaydedildi",
  "Earlier revisions exist; this view is incomplete.": "Daha eski revizyonlar var; bu görünüm eksiktir.",
  "Separate human-report eligible denominators": "Ayrı insan raporunun uygun paydaları",
  ". Latest revision per report counts once; no API pooling, global share, visits or improvement inference. Complete full-answer evaluations only; partial/unavailable, unevaluated, uncertain, truncated or stale reports are excluded. Neutral/branded prompt, exact prompt/version, source/model/intent/retrieval/requested-applied/entity contexts are separate groups.": ". Rapor başına son revizyon bir kez sayılır; API birleştirme, küresel pay, ziyaret veya iyileşme çıkarımı yoktur. Yalnızca eksiksiz tam yanıt değerlendirmeleri; kısmi/kullanılamayan, değerlendirilmemiş, belirsiz, kesilmiş veya güncelliğini yitirmiş raporlar dışlanır. Tarafsız/markalı istem, tam istem/sürüm, kaynak/model/niyet/bilgi getirme/istenen-uygulanan/varlık bağlamları ayrı gruplardır.",
  "No eligible human report denominator; unavailable, not zero.": "Uygun insan raporu paydası yok; kullanılamıyor, sıfır değil.",
  "Latest 100 reports only; this rate window is bounded.": "Yalnızca son100rapor; bu oran penceresi sınırlıdır.",
  "Human sampled mention:": "İnsan örnekli anılma:",
  ". Eligible exact report revision IDs:": ". Uygun tam rapor revizyon kimlikleri:",
  "Exact group context, statuses, exclusions and competitor sample denominators": "Tam grup bağlamı, durumlar, dışlamalar ve rakip örnek paydaları",
  "Citation-capable denominator unavailable. Referrals and external cost unknown, not zero.": "Atıf ölçümüne uygun payda kullanılamıyor. Yönlendirmeler ve dış maliyet bilinmiyor, sıfır değil.",
  "Separate full-answer evaluation of report revision": "Rapor revizyonunun ayrı tam yanıt değerlendirmesi",
  "Inspect the unchanged full answer above. All spans use original Unicode codepoint positions (emoji counts as one), not UTF-16 offsets. Review uncertain candidates, add missing aliases/competitors with exact evidence, or reject ambiguity. Confirmed/rejected/uncertain is a human judgment; domain text must match the exact safe hostname, never a redirect or measured citation. No approved fact registry exists.": "Yukarıdaki değiştirilmemiş tam yanıtı inceleyin. Tüm aralıklar UTF-16 uzaklıkları yerine özgün Unicode kod noktası konumlarını kullanır (emoji bir sayılır). Belirsiz adayları inceleyin, eksik takma adları/rakipleri tam kanıtla ekleyin veya belirsizliği reddedin. Onaylandı/reddedildi/belirsiz bir insan yargısıdır; alan adı metni tam güvenli ana bilgisayarla eşleşmelidir, yönlendirme veya ölçülmüş atıf olamaz. Onaylanmış olgu kaydı yoktur.",
  "Exact human entity evaluation": "Tam insan varlığı değerlendirmesi",
  "Entity matches JSON array: kind, entity, start, end, decision, note (up to 100)": "Varlık eşleşmeleri JSON dizisi: kind, entity, start, end, decision, note (en fazla100)",
  "Full-answer review rationale / factual uncertainty (not verified truth)": "Tam yanıt inceleme gerekçesi / olgusal belirsizlik (doğrulanmış gerçek değil)",
  "I inspected the entire complete answer; evaluate it for the separate human denominator.": "Eksiksiz yanıtın tamamını inceledim; ayrı insan paydası için değerlendirin.",
  "Save immutable human evaluation": "Değiştirilemez insan değerlendirmesini kaydedin",
  "Cancel evaluation": "Değerlendirmeyi iptal edin",
  "Only bounded current source candidates are shown.": "Yalnızca sınırlı güncel kaynak adayları gösterilir.",
  "Exact customer-owned report, unevaluated first": "Tam müşteriye ait rapor, önce değerlendirilmemiş",
  "Exact verified project origin": "Tam doğrulanmış proje kökeni",
  "Exact current customer intent / requested market and language": "Tam güncel müşteri niyeti / istenen pazar ve dil",
  "Choose current intent": "Güncel niyeti seçin",
  "· review": "· inceleme",
  "Prompt group (lexical guard plus your human coverage review)": "İstem grubu (sözcüksel koruma ve insan kapsamı incelemeniz)",
  "Neutral discovery": "Tarafsız keşif",
  "Branded / leading": "Markalı / yönlendirici",
  "Your original human prompt version": "Özgün insan istemi sürümünüz",
  "Customer-reported retrieval mode (not verified)": "Müşterinin bildirdiği bilgi getirme modu (doğrulanmamış)",
  "Customer-reported applied device (unknown allowed)": "Müşterinin bildirdiği uygulanan cihaz (bilinmeyen olabilir)",
  "Actual answer coverage": "Gerçek yanıt kapsamı",
  "Human report/correction reason": "İnsan raporu/düzeltme nedeni",
  "I have independent use/storage rights for this prompt and answer under the disclosed D098 export/retention/backup/deletion lifecycle.": "Bu istem ve yanıt için açıklanan D098 dışa aktarım/saklama/yedekleme/silme yaşam döngüsü kapsamında bağımsız kullanım/saklama haklarım var.",
  "No response-only provider/API content was copied into this record.": "Yalnızca yanıtta kullanılabilen sağlayıcı/API içeriği bu kayda kopyalanmadı.",
  "No secrets, account identities, personal customer conversations or exports are included.": "Sırlar, hesap kimlikleri, kişisel müşteri konuşmaları veya dışa aktarımlar dahil edilmedi.",
  "Save immutable unevaluated human report": "Değiştirilemez değerlendirilmemiş insan raporunu kaydedin",
  "Cancel correction": "Düzeltmeyi iptal edin",
  "Current configured brands/market/language/intents and an exact verified website origin are required. Missing authority is unavailable, not a verified source.": "Güncel yapılandırılmış markalar/pazar/dil/niyetler ve tam doğrulanmış web sitesi kökeni gereklidir. Eksik yetki kullanılamazdır, doğrulanmış kaynak değildir.",
  "Read-only retained history; a current verified owner/admin may supply or evaluate reports.": "Salt okunur saklanan geçmiş; güncel doğrulanmış sahip/yönetici rapor sağlayabilir veya değerlendirebilir.",
  "Current authority at refresh": "Yenileme anında güncel yetki",
  "Stale source or actor authority": "Güncelliğini yitirmiş kaynak veya aktör yetkisi",
  "Human full-answer evaluation": "İnsan tam yanıt değerlendirmesi",
  "Unevaluated report": "Değerlendirilmemiş rapor",
  "Unknown": "Bilinmiyor",
  "Unknown region": "Bilinmeyen bölge",
  "Unknown language": "Bilinmeyen dil",
  "No answer available": "Yanıt kullanılamıyor",
  "Stale authority": "Güncelliğini yitirmiş yetki",
  "Human evaluated": "İnsan tarafından değerlendirildi",
  "Unevaluated": "Değerlendirilmemiş",
  "Unavailable": "Kullanılamıyor",
  "None": "Yok",
  "Correct report; evaluation resets and original evidence remains": "Raporu düzeltin; değerlendirme sıfırlanır ve özgün kanıtlar kalır",
  "Supply one actual independently permitted human answer": "Bağımsız olarak izin verilmiş gerçek tek bir insan yanıtı sağlayın",
  "Exact original human prompt (no hidden brand context)": "Tam özgün insan istemi (gizli marka bağlamı yok)",
  "Exact unchanged answer (blank only when unavailable)": "Tam değiştirilmemiş yanıt (yalnızca kullanılamıyorsa boş)",
  "Human source/tool label (your report, not a verified consumer service)": "İnsan kaynak/araç etiketi (raporunuz, doğrulanmış tüketici hizmeti değil)",
  "Opaque own observation reference (no provider/account/person ID)": "Kendi opak gözlem referansınız (sağlayıcı/hesap/kişi kimliği yok)",
  "Actual observation time with timezone, e.g. 2026-10-02T12:00:00+03:00": "Saat dilimiyle gerçek gözlem zamanı, ör. 2026-10-02T12:00:00+03:00",
  "Customer-reported model label (blank = unknown)": "Müşterinin bildirdiği model etiketi (boş = bilinmiyor)",
  "Customer-reported applied coarse region (blank = unknown)": "Müşterinin bildirdiği uygulanan kaba bölge (boş = bilinmiyor)",
  "Customer-reported applied language tag (blank = unknown)": "Müşterinin bildirdiği uygulanan dil etiketi (boş = bilinmiyor)",
  "Human intent coverage, independence, bias and context limitations": "İnsan niyeti kapsamı, bağımsızlık, yanlılık ve bağlam sınırlamaları",
  "Exact original human prompt": "Tam özgün insan istemi",
  "Exact unchanged customer-reported answer": "Tam değiştirilmemiş müşteri bildirimi yanıtı",
  "Select an authorized project.": "Yetkilendirilmiş bir proje seçin.",
  "Private human evidence/current authority unavailable. Refresh before another report.": "Özel insan kanıtları/güncel yetki kullanılamıyor. Başka bir rapordan önce yenileyin.",
  "Exact current history unavailable. Refresh before another report.": "Tam güncel geçmiş kullanılamıyor. Başka bir rapordan önce yenileyin.",
  "Use a bounded exact-span JSON match array with confirmed/rejected/uncertain decisions and human notes.": "Onaylandı/reddedildi/belirsiz kararları ve insan notlarını içeren sınırlı tam aralıklı JSON eşleşme dizisi kullanın.",
  "Exact immutable human report/evaluation recorded. No provider request or job ran.": "Tam değiştirilemez insan raporu/değerlendirmesi kaydedildi. Sağlayıcı isteği veya iş çalışmadı.",
  "Current source/role/revision or fields denied. Refresh before another report.": "Güncel kaynak/rol/revizyon veya alanlar reddedildi. Başka bir rapordan önce yenileyin.",
  "Outcome uncertain; check the exact request key before another save.": "Sonuç belirsiz; başka bir kaydetmeden önce tam istek anahtarını kontrol edin.",
  "Exact report reconciled from immutable history; no command replayed.": "Tam rapor değiştirilemez geçmişten uzlaştırıldı; komut yeniden oynatılmadı.",
  "No exact record found. Deliberately retry the same command if needed.": "Tam kayıt bulunamadı. Gerekirse aynı komutu bilinçli olarak yeniden deneyin.",
  "Current outcome/authority unavailable; no replay.": "Güncel sonuç/yetki kullanılamıyor; yeniden oynatma yok.",
  "Unreviewed Turkish human-report interface draft in local development. Human prompts, answers and source evidence retain their original language; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe insan raporu arayüzü taslağı. İnsan istemleri, yanıtlar ve kaynak kanıtları özgün dillerini korur; iki dilli onay bekleniyor."
};

@Component({
  selector: 'app-visibility-manual', imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="manual-answer-title">
      <h1 id="manual-answer-title">{{ t("Independently permitted human answer reports") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish human-report interface draft in local development. Human prompts, answers and source evidence retain their original language; bilingual approval is pending.") }}</p> }
      <p>{{ t("Organization") }} <span lang="en">{{ organizationId }}</span> {{ t("· project") }} <span lang="en">{{ projectId }}</span>. <a [routerLink]="['/app/dashboard', organizationId, projectId]">{{ t("Project evidence") }}</a> ·
        <a [routerLink]="['/app/intent', organizationId, projectId]">{{ t("Review genuine intents") }}</a> ·
        <a [routerLink]="['/app/onboarding', organizationId, projectId]">{{ t("Project configuration and ownership") }}</a> ·
        <a [routerLink]="['/app/visibility-history', organizationId, projectId]">{{ t("Separate API sample history") }}</a></p>
      <p>{{ t("Customer-reported source, model, retrieval and applied context are not independently verified. No consumer account is automated, licensed or verified here. This saves your independently permitted human report; no provider request, job, usage charge or schedule runs. Manual reports and native API samples have separate denominators. Text links are not measured citations; referrals and external costs are unknown.") }}</p>
      <p>{{ t("Use only independently authorized prompt/answer evidence. No secrets, personal customer conversations, account identities, screenshots or copies of response-only Google/YouTube API content. Enter coarse applied context or leave it unknown; requested market/language does not prove applied location, language or device. Rights declarations do not grant a provider license; actual terms/privacy remain unverified.") }}</p>
      <p>{{ t("Private D098 lifecycle: 90-day retained access after lapse; active deletion within 30 days of closure/retention expiry; customer backups expire up to 35 days after active deletion. Private exports are historical reports, not current-use permission.") }}</p>
      @if (loading()) { <p role="status">{{ t("Loading private reports and separate eligible denominators.") }}</p> }
      @if (error()) { <p role="alert" [attr.lang]="t(error()) === error() ? 'en' : uiLanguage()">{{ t(error()) }}</p> }
      @if (message()) { <p role="status">{{ t(message()) }}</p> }
      @if (pending()) {
        <p>{{ t("Save outcome uncertain. The exact command is frozen in component memory; no automatic replay.") }}</p>
        <button type="button" [disabled]="busy()" (click)="reconcile()">{{ t("Check uncertain exact request") }}</button>
        @if (notFound()) { <button type="button" [disabled]="busy()" (click)="retry()">{{ t("Deliberately retry same exact report") }}</button> }
      } @else { <button type="button" [disabled]="busy() || loading()" (click)="load()">{{ t("Refresh current authority and evidence") }}</button> }
      @if (context(); as info) {
        <p>{{ t("Current authority is as of refresh. Every command rechecks verified owner/admin, current intent/configuration and exact verified origin.") }}</p>
        <h2>{{ t("Latest human reports (up to 50)") }}</h2>
        @if (!info.observations.length) { <p>{{ t("No customer answer report exists; visibility is unavailable, not zero.") }}</p> }
        @if (info.has_more) { <p>{{ t("This latest-report view is bounded and incomplete.") }}</p> }
        <ul>@for (row of info.observations; track row.observation_id) {
          <li><h3><span lang="">{{ row.intake['observation_reference'] }}</span> {{ t("· revision") }} <span lang="en">{{ row.revision }}</span> · <span lang="en">{{ row.intake['status'] }}</span></h3>
            <p>{{ t("Original observation") }} <span lang="en">{{ row.intake['observed_at'] }}</span> {{ t("· correction/evaluation recorded") }} <span lang="en">{{ row.created_at }}</span>.
              {{ row.source_current ? t("Current authority at refresh") : t("Stale source or actor authority") }} · {{ row.evaluated ? t("Human full-answer evaluation") : t("Unevaluated report") }}.</p>
            <p>{{ t("Project-origin authority") }} <span lang="en">{{ row.verification_id }}</span> {{ t("· verified") }} <span lang="en">{{ row.verified_at }}</span> {{ t("· attesting actor") }} <span lang="en">{{ row.actor_id }}</span>{{ t(". This is website authority, not consumer-answer verification.") }}</p>
            <p>{{ t("Reported source") }} <span lang="">{{ row.intake['source_label'] }}</span> {{ t("/ model") }} <span [attr.lang]="row.intake['reported_model'] ? '' : uiLanguage()">{{ row.intake['reported_model'] || t("Unknown") }}</span> {{ t("/ retrieval") }} <span lang="en">{{ row.intake['reported_retrieval'] }}</span>.</p>
            <p>{{ t("Requested") }} <span lang="">{{ row.intake['requested_market'] }}</span> / <span lang="en">{{ row.intake['requested_language'] }}</span>{{ t(". Applied (customer report):") }} <span [attr.lang]="row.intake['applied_location'] ? '' : uiLanguage()">{{ row.intake['applied_location'] || t("Unknown region") }}</span> / <span [attr.lang]="row.intake['applied_language'] ? 'en' : uiLanguage()">{{ row.intake['applied_language'] || t("Unknown language") }}</span> / <span lang="en">{{ row.intake['applied_device'] }}</span>.</p>
            <p>{{ t("Prompt version") }} <span lang="en">{{ row.intake['prompt_version'] }}</span> · <span lang="en">{{ row.intake['prompt_kind'] }}</span> {{ t("· intent review") }} <span lang="en">{{ row.intake['intent_review_id'] }}</span>.</p>
            <pre [attr.aria-label]="t('Exact original human prompt')"><span lang="">{{ row.intake['prompt'] }}</span></pre>
            <pre [attr.aria-label]="t('Exact unchanged customer-reported answer')"><span [attr.lang]="row.intake['answer'] ? '' : uiLanguage()">{{ row.intake['answer'] || t("No answer available") }}</span></pre>
            <p><span lang="">{{ row.intake['evidence_note'] }}</span> · <span lang="">{{ row.reason }}</span>.</p>
            <details><summary>{{ t("Exact comparable context, entity spans and safe-syntax link evidence (never fetched)") }}</summary>
              <pre><span lang="">{{ json(row.comparison_context) }}</span></pre><pre><span lang="">{{ json(row.matches) }}</span></pre><pre><span lang="">{{ json(row.preview.links) }}</span></pre>
              @if (row.preview.has_more) { <p>{{ t("Candidate extraction truncated; an evaluated negative is unavailable.") }}</p> }
            </details>
            <button type="button" [disabled]="busy() || !!pending()" (click)="inspect(row.observation_id)">{{ t("Inspect immutable history") }}</button>
            @if (info.can_review && row.source_current) {
              <button type="button" [disabled]="busy() || !!pending()" (click)="edit(row)">{{ t("Correct report; reset evaluation") }}</button>
              <button type="button" [disabled]="busy() || !!pending()" (click)="review(row)">{{ t("Review exact full-answer entity spans") }}</button>
            }
          </li>
        }</ul>
        @if (historyRows().length) {
          <details open><summary>{{ t("Immutable original and corrected evidence (newest 20 revisions)") }}</summary>
            <ol>@for (row of historyRows(); track row.id) {
              <li>{{ t("Revision") }} <span lang="en">{{ row.revision }}</span> {{ t("· observed") }} <span lang="en">{{ row.intake['observed_at'] }}</span> {{ t("· recorded") }} <span lang="en">{{ row.created_at }}</span> · <span lang="en">{{ row.intake['status'] }}</span> ·
                {{ row.source_current ? t("Current authority at refresh") : t("Stale authority") }} · {{ row.evaluated ? t("Human evaluated") : t("Unevaluated") }}.
                <pre><span lang="">{{ json(row.intake) }}</span></pre><pre><span lang="">{{ json(row.matches) }}</span></pre><p><span lang="">{{ row.reason }}</span></p></li>
            }</ol>@if (historyMore()) { <p>{{ t("Earlier revisions exist; this view is incomplete.") }}</p> }
          </details>
        }
        @if (rates(); as report) {
          <h2>{{ t("Separate human-report eligible denominators") }}</h2>
          <p><span lang="en">{{ report.scope }}</span>{{ t(". Latest revision per report counts once; no API pooling, global share, visits or improvement inference. Complete full-answer evaluations only; partial/unavailable, unevaluated, uncertain, truncated or stale reports are excluded. Neutral/branded prompt, exact prompt/version, source/model/intent/retrieval/requested-applied/entity contexts are separate groups.") }}</p>
          @if (!report.groups.length) { <p>{{ t("No eligible human report denominator; unavailable, not zero.") }}</p> }
          @if (report.has_more) { <p>{{ t("Latest 100 reports only; this rate window is bounded.") }}</p> }
          <ul>@for (group of report.groups; track group.comparison_key) {
            <li><p>{{ t("Human sampled mention:") }} <span lang="en">{{ group.mention_rate.numerator }}</span> / <span lang="en">{{ group.mention_rate.denominator }}</span> ·
              <span [attr.lang]="group.mention_rate.percent === null ? uiLanguage() : 'en'">{{ group.mention_rate.percent === null ? t("Unavailable") : group.mention_rate.percent + '%' }}</span>{{ t(". Eligible exact report revision IDs:") }} <span [attr.lang]="group.eligible_report_ids.length ? 'en' : uiLanguage()">{{ group.eligible_report_ids.join(', ') || t("None") }}</span>.</p>
              <details><summary>{{ t("Exact group context, statuses, exclusions and competitor sample denominators") }}</summary>
                <pre><span lang="">{{ json(group.context) }}</span></pre><pre><span lang="">{{ json(group.statuses) }}</span></pre><pre><span lang="">{{ json(group.exclusions) }}</span></pre>
                <pre><span lang="">{{ json(group.competitor_mention_rates) }}</span></pre>
              </details></li>
          }</ul><p>{{ t("Citation-capable denominator unavailable. Referrals and external cost unknown, not zero.") }}</p>
        }
        @if (info.can_review && !pending()) {
          @if (reviewing(); as row) {
            <h2>{{ t("Separate full-answer evaluation of report revision") }} <span lang="en">{{ row.revision }}</span></h2>
            <p>{{ t("Inspect the unchanged full answer above. All spans use original Unicode codepoint positions (emoji counts as one), not UTF-16 offsets. Review uncertain candidates, add missing aliases/competitors with exact evidence, or reject ambiguity. Confirmed/rejected/uncertain is a human judgment; domain text must match the exact safe hostname, never a redirect or measured citation. No approved fact registry exists.") }}</p>
            <form (submit)="saveReview($event)"><fieldset [disabled]="busy()"><legend>{{ t("Exact human entity evaluation") }}</legend>
              <label for="manual-matches">{{ t("Entity matches JSON array: kind, entity, start, end, decision, note (up to 100)") }}</label>
              <textarea lang="" id="manual-matches" name="matches" required rows="12" maxlength="32768" [value]="matchDraft()"></textarea>
              <label for="manual-review-reason">{{ t("Full-answer review rationale / factual uncertainty (not verified truth)") }}</label>
              <textarea lang="" id="manual-review-reason" name="reason" required maxlength="500"></textarea>
              <label><input type="checkbox" name="evaluated" [disabled]="row.intake['status'] !== 'complete' || row.preview.has_more" />{{ t("I inspected the entire complete answer; evaluate it for the separate human denominator.") }}</label>
              <button type="submit">{{ t("Save immutable human evaluation") }}</button><button type="button" (click)="cancelEdit()">{{ t("Cancel evaluation") }}</button>
            </fieldset></form>
          } @else if (info.verified_origins.length && info.intent_reviews.length && info.brand_aliases.length && info.market) {
            <h2>{{ editing() ? t("Correct report; evaluation resets and original evidence remains") : t("Supply one actual independently permitted human answer") }}</h2>
            @if (info.sources_has_more) { <p>{{ t("Only bounded current source candidates are shown.") }}</p> }
            <form (submit)="save($event)"><fieldset [disabled]="busy()"><legend>{{ t("Exact customer-owned report, unevaluated first") }}</legend>
              <label for="manual-origin">{{ t("Exact verified project origin") }}</label><select id="manual-origin" name="origin" required>
                @for (origin of info.verified_origins; track origin) { <option lang="en" [value]="origin" [selected]="origin === editing()?.intake?.['origin']">{{ origin }}</option> }
              </select>
              <label for="manual-intent">{{ t("Exact current customer intent / requested market and language") }}</label><select id="manual-intent" name="intent_review_id" required>
                <option value="">{{ t("Choose current intent") }}</option>@for (mapping of availableMappings(); track mapping.review_id) {
                  <option lang="" [value]="mapping.review_id" [selected]="mapping.review_id === editing()?.intake?.['intent_review_id']">{{ mapping.label }} · {{ mapping.market }}/{{ mapping.language }} {{ t("· review") }} {{ mapping.review_id }}</option>
                }
              </select>
              <label for="manual-kind">{{ t("Prompt group (lexical guard plus your human coverage review)") }}</label><select id="manual-kind" name="prompt_kind">
                <option value="neutral" [selected]="editing()?.intake?.['prompt_kind'] !== 'branded'">{{ t("Neutral discovery") }}</option><option value="branded" [selected]="editing()?.intake?.['prompt_kind'] === 'branded'">{{ t("Branded / leading") }}</option>
              </select>
              <label for="manual-version">{{ t("Your original human prompt version") }}</label><input id="manual-version" name="prompt_version" type="number" min="1" max="2147483647" required [value]="editing()?.intake?.['prompt_version'] || 1" />
              @for (field of textFields; track field.key) {
                <label [for]="'manual-' + field.key">{{ t(field.label) }}</label>
                <textarea [attr.lang]="field.key === 'observed_at' || field.key === 'applied_language' ? 'en' : ''" [id]="'manual-' + field.key" [name]="field.key" [required]="field.required" [attr.maxlength]="field.limit" [rows]="field.key === 'answer' ? 6 : 2" [value]="editing()?.intake?.[field.key] || ''"></textarea>
              }
              <label for="manual-retrieval">{{ t("Customer-reported retrieval mode (not verified)") }}</label><select id="manual-retrieval" name="reported_retrieval">
                @for (mode of modes; track mode) { <option lang="en" [value]="mode" [selected]="mode === (editing()?.intake?.['reported_retrieval'] || 'unknown')">{{ mode }}</option> }
              </select>
              <label for="manual-device">{{ t("Customer-reported applied device (unknown allowed)") }}</label><select id="manual-device" name="applied_device">
                @for (device of devices; track device) { <option lang="en" [value]="device" [selected]="device === (editing()?.intake?.['applied_device'] || 'unknown')">{{ device }}</option> }
              </select>
              <label for="manual-status">{{ t("Actual answer coverage") }}</label><select id="manual-status" name="status">
                @for (status of statuses; track status) { <option lang="en" [value]="status" [selected]="status === (editing()?.intake?.['status'] || 'complete')">{{ status }}</option> }
              </select>
              <label for="manual-reason">{{ t("Human report/correction reason") }}</label><textarea lang="" id="manual-reason" name="reason" required maxlength="500"></textarea>
              <label><input type="checkbox" name="storage_permission" required />{{ t("I have independent use/storage rights for this prompt and answer under the disclosed D098 export/retention/backup/deletion lifecycle.") }}</label>
              <label><input type="checkbox" name="not_response_only_copy" required />{{ t("No response-only provider/API content was copied into this record.") }}</label>
              <label><input type="checkbox" name="no_personal_payload" required />{{ t("No secrets, account identities, personal customer conversations or exports are included.") }}</label>
              <button type="submit">{{ t("Save immutable unevaluated human report") }}</button>
              @if (editing()) { <button type="button" (click)="cancelEdit()">{{ t("Cancel correction") }}</button> }
            </fieldset></form>
          } @else { <p>{{ t("Current configured brands/market/language/intents and an exact verified website origin are required. Missing authority is unavailable, not a verified source.") }}</p> }
        } @else if (!info.can_review) { <p>{{ t("Read-only retained history; a current verified owner/admin may supply or evaluate reports.") }}</p> }
      }
    </section>`,
  styles: `form,fieldset { display:grid; gap:.6rem; min-width:0 } form { max-width:48rem } textarea,input,select { min-width:0; max-width:100% } pre { white-space:pre-wrap; overflow-wrap:anywhere } p,li { overflow-wrap:anywhere } li { margin-block:1.5rem }`,
})
export class VisibilityManual implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  t(text: string) { return this.uiLanguage() === 'tr' ? visibilityManualTurkish[text] ?? text : text; }
  readonly textFields = [
    { key: 'prompt', label: 'Exact original human prompt (no hidden brand context)', limit: 500, required: true },
    { key: 'answer', label: 'Exact unchanged answer (blank only when unavailable)', limit: 4000, required: false },
    { key: 'source_label', label: 'Human source/tool label (your report, not a verified consumer service)', limit: 120, required: true },
    { key: 'observation_reference', label: 'Opaque own observation reference (no provider/account/person ID)', limit: 64, required: true },
    { key: 'observed_at', label: 'Actual observation time with timezone, e.g. 2026-10-02T12:00:00+03:00', limit: 64, required: true },
    { key: 'reported_model', label: 'Customer-reported model label (blank = unknown)', limit: 120, required: false },
    { key: 'applied_location', label: 'Customer-reported applied coarse region (blank = unknown)', limit: 240, required: false },
    { key: 'applied_language', label: 'Customer-reported applied language tag (blank = unknown)', limit: 35, required: false },
    { key: 'evidence_note', label: 'Human intent coverage, independence, bias and context limitations', limit: 500, required: true },
  ];
  readonly modes = ['unknown', 'none', 'reported']; readonly devices = ['unknown', 'desktop', 'mobile']; readonly statuses = ['complete', 'partial', 'unavailable'];
  readonly context = signal<Context | null>(null); readonly rates = signal<Rates | null>(null); readonly editing = signal<Observation | null>(null);
  readonly reviewing = signal<Observation | null>(null); readonly matchDraft = signal('[]'); readonly historyRows = signal<Observation[]>([]);
  readonly historyMore = signal(false); readonly loading = signal(false); readonly busy = signal(false); readonly error = signal(''); readonly message = signal('');
  readonly pending = signal<Command | null>(null); readonly notFound = signal(false);
  protected organizationId = 0; protected projectId = 0; private generation = 0; private historyGeneration = 0;
  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi, private readonly destroy: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t('Private permitted human answer reports')} — OrganicSEOOps`));
    destroy.onDestroy(() => { this.generation++; this.clear(); }); }
  ngOnInit() { void this.loadProductLanguage(); this.route.paramMap.pipe(takeUntilDestroyed(this.destroy)).subscribe((params) => {
    this.generation++; this.clear(); this.busy.set(false); this.loading.set(false); this.error.set(''); this.message.set('');
    this.organizationId = Number(params.get('organizationId')); this.projectId = Number(params.get('projectId'));
    if (positive(this.organizationId) && positive(this.projectId)) void this.load(); else this.error.set('Select an authorized project.');
  }); }
  private async loadProductLanguage() {
    try {
      const result = await this.api.productLanguage();
      if (!this.destroy.destroyed && result.status === 200 && isProductLanguageResult(result.body)) {
        this.productLanguage.set(result.body['language']);
      }
    } catch { /* Keep English when the private preference is unavailable. */ }
  }
  json(value: unknown) { return JSON.stringify(value, null, 2); }
  private clear() { this.context.set(null); this.rates.set(null); this.historyRows.set([]); this.historyMore.set(false); this.cancelEdit(); this.pending.set(null); this.notFound.set(false); this.historyGeneration++; }
  cancelEdit() { this.editing.set(null); this.reviewing.set(null); this.matchDraft.set('[]'); }
  availableMappings() { const info = this.context(); return info?.intent_reviews.filter((row) => row.source_current && row.market === info.market && info.languages.includes(row.language)) || []; }
  private read(response: ApiResult): Context {
    const info = response.body as unknown as Context;
    if (response.status !== 200 || info.organization_id !== this.organizationId || info.project_id !== this.projectId || info.method_version !== METHOD
      || info.source_kind !== SOURCE || info.surface !== SURFACE || typeof info.can_review !== 'boolean' || typeof info.has_more !== 'boolean'
      || typeof info.sources_has_more !== 'boolean' || !(info.configuration_revision === null || Number.isSafeInteger(info.configuration_revision))
      || typeof info.market !== 'string' || !strings(info.languages) || !strings(info.brand_aliases) || !strings(info.verified_origins)
      || !Array.isArray(info.intent_reviews) || !info.intent_reviews.every((row) => !!row && positive(row.review_id) && typeof row.label === 'string'
        && typeof row.market === 'string' && typeof row.language === 'string' && typeof row.source_current === 'boolean')
      || !Array.isArray(info.observations) || !info.observations.every((row) => isObservation(row, this.projectId))) throw new Error();
    return info;
  }
  async load() {
    if (this.busy() || this.pending()) return;
    const generation = ++this.generation; this.clear(); this.loading.set(true); this.error.set('');
    try {
      const [response, rates] = await Promise.all([this.api.visibilityManual(this.organizationId, this.projectId), this.api.visibilityManualRates(this.organizationId, this.projectId)]);
      if (generation !== this.generation) return;
      const info = this.read(response); const report = rates.body as unknown as Rates;
      if (rates.status !== 200 || report.organization_id !== this.organizationId || report.project_id !== this.projectId || report.method !== METHOD
        || report.surface !== SURFACE || report.external_cost !== null || report.referrals !== null || typeof report.scope !== 'string'
        || typeof report.has_more !== 'boolean' || !Array.isArray(report.groups) || report.groups.length > 100 || !report.groups.every((group) => !!group
          && typeof group.comparison_key === 'string' && Array.isArray(group.report_ids) && group.report_ids.length > 0
          && group.report_ids.length <= 100 && group.report_ids.every(positive) && new Set(group.report_ids).size === group.report_ids.length
          && Array.isArray(group.eligible_report_ids) && group.eligible_report_ids.every((id) => positive(id) && group.report_ids.includes(id))
          && new Set(group.eligible_report_ids).size === group.eligible_report_ids.length
          && isRate(group.mention_rate, group.eligible_report_ids.length)
          && !!group.competitor_mention_rates && typeof group.competitor_mention_rates === 'object' && !Array.isArray(group.competitor_mention_rates)
          && Object.values(group.competitor_mention_rates).every(rate => isRate(rate, group.eligible_report_ids.length)))) throw new Error();
      this.context.set(info); this.rates.set(report);
    } catch { if (generation === this.generation) this.error.set('Private human evidence/current authority unavailable. Refresh before another report.'); }
    finally { if (generation === this.generation) this.loading.set(false); }
  }
  edit(row: Observation) { if (this.busy() || this.pending() || !this.context()?.can_review || !row.is_latest || !row.source_current) return; this.cancelEdit(); this.editing.set(row); }
  review(row: Observation) { if (this.busy() || this.pending() || !this.context()?.can_review || !row.is_latest || !row.source_current) return;
    this.cancelEdit(); this.reviewing.set(row); this.matchDraft.set(this.json(row.evaluated ? row.matches : row.preview.matches)); }
  async inspect(id: string) {
    if (this.busy() || this.pending()) return;
    const generation = this.generation; const history = ++this.historyGeneration; this.historyRows.set([]); this.cancelEdit();
    try {
      const response = await this.api.visibilityManual(this.organizationId, this.projectId, undefined, id);
      if (generation !== this.generation || history !== this.historyGeneration) return;
      const info = this.read(response);
      if (!info.observations.length || !info.observations[0].is_latest || info.observations.some((row) => row.observation_id !== id)) throw new Error();
      const old = this.context(); if (old) this.context.set({ ...info, observations: old.observations, has_more: old.has_more });
      this.historyRows.set(info.observations); this.historyMore.set(info.has_more);
    } catch { if (generation === this.generation && history === this.historyGeneration) { this.context.set(null); this.rates.set(null); this.error.set('Exact current history unavailable. Refresh before another report.'); } }
  }
  save(event: Event) {
    event.preventDefault(); const form = event.target as HTMLFormElement; const info = this.context();
    if (this.busy() || this.pending() || !info?.can_review || !form.reportValidity()) return;
    const fields = new FormData(form); if (!['storage_permission', 'not_response_only_copy', 'no_personal_payload'].every((key) => fields.has(key))) return;
    const mapping = this.availableMappings().find((row) => row.review_id === Number(fields.get('intent_review_id'))); if (!mapping) return;
    const intake: Intake = { method_version: METHOD, source_kind: SOURCE, surface: SURFACE, configuration_revision: info.configuration_revision!,
      intent_review_id: mapping.review_id, requested_market: info.market, requested_language: mapping.language, prompt_version: Number(fields.get('prompt_version')),
      storage_permission: true, not_response_only_copy: true, no_personal_payload: true };
    for (const key of [...this.textFields.map((field) => field.key), 'origin', 'prompt_kind', 'reported_retrieval', 'applied_device', 'status']) intake[key] = String(fields.get(key) || '');
    const row = this.editing(); const data: Record<string, unknown> = { request_key: crypto.randomUUID(), intake, reason: String(fields.get('reason') || ''), evaluated: false, matches: [] };
    if (row) data['expected_revision'] = row.revision;
    void this.send({ data, observationId: row?.observation_id });
  }
  saveReview(event: Event) {
    event.preventDefault(); const form = event.target as HTMLFormElement; const row = this.reviewing();
    if (this.busy() || this.pending() || !this.context()?.can_review || !row?.source_current || !form.reportValidity()) return;
    const fields = new FormData(form);
    try { const matches: unknown = JSON.parse(String(fields.get('matches')));
      if (!Array.isArray(matches) || matches.length > 100 || !matches.every(isMatch)) throw new Error();
      const evaluated = fields.has('evaluated'); if (evaluated && (row.intake['status'] !== 'complete' || row.preview.has_more)) return;
      void this.send({ observationId: row.observation_id, data: { request_key: crypto.randomUUID(), expected_revision: row.revision,
        intake: row.intake, evaluated, matches, reason: String(fields.get('reason') || '') } });
    } catch { this.error.set('Use a bounded exact-span JSON match array with confirmed/rejected/uncertain decisions and human notes.'); }
  }
  private matches(row: Observation, command: Command) {
    const input = command.data['intake'] as Intake; const matches = command.data['matches'] as Match[];
    return (!command.observationId || row.observation_id === command.observationId) && row.revision === Number(command.data['expected_revision'] || 0) + 1
      && row.reason === command.data['reason'] && row.evaluated === command.data['evaluated'] && flatEqual(input, row.intake)
      && row.matches.length === matches.length && matches.every((match, i) => flatEqual(match as unknown as Record<string, unknown>, row.matches[i] as unknown as Record<string, unknown>));
  }
  private async send(command: Command) {
    const generation = this.generation; this.busy.set(true); this.pending.set(command); this.notFound.set(false); this.message.set(''); this.error.set('');
    try {
      const response = await this.api.visibilityManual(this.organizationId, this.projectId, command.data, command.observationId);
      if (generation !== this.generation) return;
      if ([200, 201].includes(response.status) && response.body['organization_id'] === this.organizationId && response.body['project_id'] === this.projectId
        && isObservation(response.body['observation'], this.projectId) && this.matches(response.body['observation'], command)) {
        this.pending.set(null); this.busy.set(false); await this.load();
        if (generation + 1 === this.generation) this.message.set('Exact immutable human report/evaluation recorded. No provider request or job ran.');
      } else if ([400, 401, 403, 404, 409, 413, 429].includes(response.status)) { this.clear(); this.error.set('Current source/role/revision or fields denied. Refresh before another report.'); }
      else this.message.set('Outcome uncertain; check the exact request key before another save.');
    } catch { if (generation === this.generation) this.message.set('Outcome uncertain; check the exact request key before another save.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  async reconcile() {
    const command = this.pending(); if (!command || this.busy()) return; const generation = this.generation; this.busy.set(true);
    try {
      const response = await this.api.visibilityManual(this.organizationId, this.projectId, undefined, undefined, String(command.data['request_key']));
      if (generation !== this.generation) return;
      const info = this.read(response);
      if (response.body['lookup'] === 'found' && info.observations.length === 1 && this.matches(info.observations[0], command)) {
        this.pending.set(null); this.busy.set(false); await this.load();
        if (generation + 1 === this.generation) this.message.set('Exact report reconciled from immutable history; no command replayed.');
      } else if (response.body['lookup'] === 'not_found' && !info.observations.length && info.can_review) {
        this.notFound.set(true); this.message.set('No exact record found. Deliberately retry the same command if needed.');
      } else throw new Error();
    } catch { if (generation === this.generation) { this.context.set(null); this.rates.set(null); this.historyRows.set([]); this.cancelEdit(); this.notFound.set(false);
      this.message.set('Current outcome/authority unavailable; no replay.'); } }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  retry() { const command = this.pending(); if (command && this.notFound() && !this.busy()) void this.send(command); }
}
