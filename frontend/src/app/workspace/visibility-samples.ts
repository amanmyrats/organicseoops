import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, OnInit, computed, effect, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi } from '../account/account-api';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';

type Prompt = { key: string; kind: string; text: string; intent_review_id: number };
type PromptSet = { id: number; project_id: number; set_id: string; revision: number; label: string; source_current: boolean;
  market: string; language: string; prompts: Prompt[]; policy: { max_output_tokens: number; max_cost_usd: string };
  repeat_available_at: Record<string, string | null> };
type Model = { id: number; provider_id: number; name: string; identifier: string; max_output_tokens: number | null };
type Account = { id: number; provider_id: number; label: string; source: string };
type Usage = { request_status: string; input_tokens: number | null; output_tokens: number | null;
  estimated_cost_usd: string | null; reported_cost_usd: string | null; duration_ms: number | null };
type Evidence = { answer: string; collected_at: string; provider_status: string; returned_model: string | null;
  evaluation: string; citation_measurement: string; collection_eligible: boolean; delivery_limit: string };
type Job = { id: number; project_id: number; status: string; error_category: string; prompt_key: string; prompt_kind: string;
  repeat_context?: { method: string; schedule_id: number | null; scheduled_for: string | null };
  revision: number; set_id: string; prompt_set_id: number; model_identifier: string; account_id: number;
  source_current: boolean; collection_state: string; repeat_available_at: string | null; attempted_units: number;
  cancel_requested: boolean; estimated_max_cost_usd: string | null; updated_at: string; usage: Usage | null;
  methodology: { prompt: Prompt; context: { market: string; language: string } } | null; evidence: Evidence | null };
type Match = { kind: string; entity: string; start: number; end: number; decision: string; note: string };
type Rate = { numerator: number | null; denominator: number; percent: string | null; state: string };
type Review = { id: number; job_id: number; project_id: number; revision: number; matches: Match[]; evaluated: boolean;
  review_note: string; factual_notes: { start: number; end: number; note: string }[]; created_at: string };
type RateGroup = { requested_model: string; returned_model: string | null; account_id: number; sample_ids: number[];
  repeat_policy?: { method: string; interval_minutes: number } | null;
  eligible_sample_ids: number[]; exclusions: Record<string, number>; prompt_mix: Record<string, number>;
  mention_rate: Rate; citation_rate: Rate; neutral_branded_rates: Record<string, Rate>; competitor_mention_rates: Record<string, Rate> };
type EntityPreview = { project_id: number; job_id: number; method: string; context: { configuration_revision: number;
  brand_aliases: string[]; project_domains: string[]; competitor_domains: string[]; business_facts: string };
  candidates: { matches: Match[]; links: { text: string; safe_syntax: boolean; citation: string }[]; has_more: boolean };
  latest: Review | null; history: Review[]; history_has_more: boolean; collection_eligible: boolean;
  rates: { scope: string; has_more: boolean; groups: RateGroup[] } };

const visibilitySamplesTurkish: Record<string, string> = {
  "Private API-only sample evidence": "Özel yalnızca API örnek kanıtları",
  "Private API-only answer samples": "Yalnızca API'ye ait özel yanıt örnekleri",
  "Return to project evidence": "Proje kanıtlarına dönün",
  "Review prompt methodology": "İstem metodolojisini inceleyin",
  "Comparable observation history": "Karşılaştırılabilir gözlem geçmişi",
  "Separate opt-in bounded repeats": "Ayrı, isteğe bağlı sınırlı tekrarlar",
  "Native OpenAI Responses text-only output, not consumer ChatGPT observations, global visibility, measured demand or visits. Exact human prompt text is sent unchanged: no hidden brand/audience injection, conversation, retrieval or tools. Citation measurement and device/geolocation controls are unavailable; market/language are requested human context, not guaranteed settings.": "Yerel OpenAI Responses yalnızca metin çıktısı; tüketici ChatGPT gözlemleri, küresel görünürlük, ölçülmüş talep veya ziyaretler değildir. Tam insan istemi metni değiştirilmeden gönderilir: gizli marka/hedef kitle ekleme, konuşma, bilgi getirme veya araç yoktur. Atıf ölçümü ve cihaz/coğrafi konum kontrolleri kullanılamaz; pazar/dil istenen insan bağlamıdır, garantili ayarlar değildir.",
  "One explicit standard-access model/account and up to one attempted request/internal unit. Repeat manually at least24hours per set/prompt, including failed/uncertain attempts and corrections. This manual command never enables a repeat schedule, fallback, retry or background research. Token and estimated USD ceilings do not guarantee actual provider charges. Provider terms/live readiness remain unverified.": "Açıkça seçilmiş tek bir standart erişimli model/hesap ve en fazla bir istek denemesi/dahili birim. Başarısız/belirsiz denemeler ve düzeltmeler dahil, her küme/istem için en az24saat arayla manuel tekrar. Bu manuel komut hiçbir zaman tekrar zamanlaması, yedek seçenek, yeniden deneme veya arka plan araştırması etkinleştirmez. Token ve tahmini USD üst sınırları gerçek sağlayıcı ücretlerini garanti etmez. Sağlayıcı koşulları/canlı hazırlık henüz doğrulanmamıştır.",
  "Prompts/answers are private customer data under organization export/retention/deletion and up to35-day backup expiry after active deletion. store:false does not establish provider Zero Data Retention; abuse monitoring may retain content up to30days with legal/safety exceptions, and prompt caches may retain application state up to24hours. Do not submit secrets, personal data or customer exports.": "İstemler/yanıtlar kuruluşun dışa aktarım/saklama/silme ve aktif silmeden sonra en fazla35günlük yedek sona erme politikasına tabi özel müşteri verileridir. store:false sağlayıcının Sıfır Veri Saklamasını kanıtlamaz; kötüye kullanım izlemesi içeriği yasal/güvenlik istisnalarıyla en fazla30gün saklayabilir ve istem önbellekleri uygulama durumunu en fazla24saat saklayabilir. Sırları, kişisel verileri veya müşteri dışa aktarımlarını göndermeyin.",
  "Provider data controls": "Sağlayıcı veri kontrolleri",
  "Loading current project samples and choices.": "Güncel proje örnekleri ve seçenekleri yükleniyor.",
  "Active project:": "Aktif proje:",
  "(organization": "(kuruluş",
  ", project": ", proje",
  "Exact-current reviewed prompt set": "Tam güncel incelenmiş istem kümesi",
  "Choose reviewed methodology": "İncelenmiş metodolojiyi seçin",
  "· revision": "· revizyon",
  "One unchanged human prompt (separate neutral/branded group)": "Değiştirilmemiş tek insan istemi (ayrı tarafsız/markalı grup)",
  "Choose one prompt": "Bir istem seçin",
  "Intent review": "Niyet incelemesi",
  "Repeat available at": "Tekrarın kullanılabileceği zaman",
  ". The server also enforces in-flight exclusion.": ". Sunucu ayrıca eşzamanlı işlem dışlamasını uygular.",
  "Explicit native standard-access text model (no default)": "Açıkça seçilmiş yerel standart erişimli metin modeli (varsayılan yok)",
  "Choose a model": "Bir model seçin",
  "Matching credential account": "Eşleşen kimlik bilgisi hesabı",
  "Choose an account": "Bir hesap seçin",
  "Output-token ceiling (within reviewed limit": "Çıktı tokeni üst sınırı (incelenmiş sınır içinde",
  "Maximum estimated USD (within reviewed ceiling": "Azami tahmini USD (incelenmiş üst sınır içinde",
  "I reviewed the exact prompt, selected account/model, one-attempt costs, privacy and API-only measurement limits.": "Tam istemi, seçilen hesabı/modeli, tek deneme maliyetlerini, gizliliği ve yalnızca API ölçüm sınırlarını inceledim.",
  "Reserve one unit and collect one API sample": "Bir birim ayırın ve bir API örneği toplayın",
  "New samples require launch permission, a current reviewed methodology and configured native standard-access model/account. Historical evidence remains viewable with current project-read access.": "Yeni örnekler başlatma izni, güncel incelenmiş metodoloji ve yapılandırılmış yerel standart erişimli model/hesap gerektirir. Geçmiş kanıtlar güncel proje okuma erişimiyle görüntülenebilir.",
  "Recent sample attempts": "Son örnek denemeleri",
  "Collection leaves answers unevaluated; only a separate human review supplies eligible mention-rate observations. Failed, incomplete, cancelled and unknown attempts are separate from completed evidence.": "Toplama yanıtları değerlendirilmemiş bırakır; yalnızca ayrı bir insan incelemesi anılma oranına uygun gözlemler sağlar. Başarısız, eksik, iptal edilmiş ve bilinmeyen denemeler tamamlanmış kanıtlardan ayrıdır.",
  "Sample": "Örnek",
  ") · revision": ") · revizyon",
  "Inspect sample": "Örneği inceleyin:",
  "No sample attempts recorded.": "Kaydedilmiş örnek denemesi yok.",
  "Choices/history are bounded to100 models/accounts and20 sets/recent samples.": "Seçenekler/geçmiş100 model/hesap ve20 küme/son örnekle sınırlıdır.",
  "Repeat context": "Tekrar bağlamı",
  "· schedule": "· zamanlama",
  "· occurrence": "· oluşum",
  "· source/model/actor": "· kaynak/model/aktör",
  "attempted unit ·": "denenen birim ·",
  "Collection issue:": "Toplama sorunu:",
  ". No automatic replay.": ". Otomatik yeniden oynatma yok.",
  "Requested model": "İstenen model",
  ", account": ", hesap",
  ". Preflight estimated USD": ". Ön kontrol tahmini USD",
  ". Repeat available at": ". Tekrarın kullanılabileceği zaman",
  "Exact methodology": "Tam metodoloji",
  ", revision": ", revizyon",
  ", prompt": ", istem",
  "· requested": "· istenen",
  "(not applied controls).": "(uygulanan kontroller değil).",
  "Provider request": "Sağlayıcı isteği",
  "· input/output tokens": "· girdi/çıktı tokenleri",
  "· duration": "· süre",
  "ms. Token-based estimated USD": "ms. Token tabanlı tahmini USD",
  "· provider-reported charge": "· sağlayıcının bildirdiği ücret",
  "No provider attempt recorded.": "Kaydedilmiş sağlayıcı denemesi yok.",
  "Private exact answer · collected": "Özel tam yanıt · toplandı",
  "· provider": "· sağlayıcı",
  "· returned model": "· döndürülen model",
  ". Citation measurement": ". Atıf ölçümü",
  ". URLs/markup below are untrusted plain text, never fetched or rendered as HTML.": ". Aşağıdaki URL'ler/işaretleme güvenilmeyen düz metindir; hiçbir zaman getirilmez veya HTML olarak oluşturulmaz.",
  "Answer evidence unavailable; this is not a negative mention/citation observation.": "Yanıt kanıtı kullanılamıyor; bu olumsuz anılma/atıf gözlemi değildir.",
  "Correctable entity evidence and sample denominators": "Düzeltilebilir varlık kanıtları ve örnek paydaları",
  "Lexical candidates are uncertain until human review, not provider identity/factual verification. Spans use original Unicode codepoints; start is inclusive and end exclusive. Domains match only exact configured hosts: no redirect/subdomain equivalence or citation evidence is inferred. Human-reviewed competitor names resolve to configured domains.": "Sözcüksel adaylar insan incelemesine kadar belirsizdir; sağlayıcı kimliği/olgusal doğrulama değildir. Aralıklar özgün Unicode kod noktalarını kullanır; başlangıç dahil, bitiş hariçtir. Alan adları yalnızca tam yapılandırılmış ana bilgisayarlarla eşleşir: yönlendirme/alt alan adı eşdeğerliği veya atıf kanıtı çıkarılmaz. İnsan tarafından incelenmiş rakip adları yapılandırılmış alan adlarıyla eşleştirilir.",
  "Original answer brand aliases": "Özgün yanıt marka takma adları",
  "; project domains": "; proje alan adları",
  ". Current review competitor domains": ". Güncel inceleme rakip alan adları",
  "· configuration": "· yapılandırma",
  "Factual comparison:": "Olgusal karşılaştırma:",
  ". Human factual concerns below remain unverified; project configuration/answer text is not an approved business-fact registry.": ". Aşağıdaki insanın bildirdiği olgusal kaygılar doğrulanmamıştır; proje yapılandırması/yanıt metni onaylanmış iş bilgileri kaydı değildir.",
  "Candidates exceed100 spans/50 links. Extraction coverage is truncated; this sample cannot establish an evaluated negative.": "Adaylar100 aralığı/50 bağlantıyı aşıyor. Çıkarım kapsamı kesilmiştir; bu örnek değerlendirilmiş bir olumsuz sonucu kanıtlayamaz.",
  "Text link": "Metin bağlantısı",
  "Append a human correction to revision": "Revizyona bir insan düzeltmesi ekleyin:",
  ". Inspect the whole exact answer above, resolve every candidate and add missed aliases/spans. An unresolved match excludes the answer from rates.": ". Yukarıdaki tam yanıtın tamamını inceleyin, her adayı çözümleyin ve kaçırılmış takma adları/aralıkları ekleyin. Çözümlenmemiş eşleşme yanıtı oranlardan dışlar.",
  "Entity span": "Varlık aralığı",
  "Kind": "Tür",
  "Resolved entity (project_brand for brand; configured exact domain for competitor)": "Çözümlenmiş varlık (marka için project_brand; rakip için yapılandırılmış tam alan adı)",
  "Start Unicode-codepoint index (inclusive)": "Başlangıç Unicode kod noktası indeksi (dahil)",
  "End Unicode-codepoint index (exclusive)": "Bitiş Unicode kod noktası indeksi (hariç)",
  "Human decision": "İnsan kararı",
  "Human alias/domain decision rationale": "İnsan takma ad/alan adı kararı gerekçesi",
  "Remove span": "Aralığı kaldırın:",
  "Add a missed human entity/alias span": "Kaçırılmış insan varlığı/takma ad aralığı ekleyin",
  "I reviewed the complete valid collected answer, including absence and all uncertain aliases. Uncertain matches still keep the denominator unavailable.": "Yokluk ve tüm belirsiz takma adlar dahil, tam geçerli toplanmış yanıtı inceledim. Belirsiz eşleşmeler paydayı hâlâ kullanılamaz tutar.",
  "Full-answer evaluation/correction rationale": "Tam yanıt değerlendirmesi/düzeltme gerekçesi",
  "Optional factual-uncertainty evidence (JSON array, up to10 {start,end,note}; no verified-fact claims)": "İsteğe bağlı olgusal belirsizlik kanıtı (JSON dizisi, en fazla10 {start,end,note}; doğrulanmış olgu iddiası yok)",
  "Save immutable human entity review (no provider call)": "Değiştirilemez insan varlığı incelemesini kaydedin (sağlayıcı çağrısı yok)",
  "Owner/admin role is required to correct/evaluate answer evidence.": "Yanıt kanıtlarını düzeltmek/değerlendirmek için sahip/yönetici rolü gerekir.",
  "Human correction history": "İnsan düzeltmesi geçmişi",
  "Revision": "Revizyon",
  "No human evaluation exists; no valid negative can be inferred.": "İnsan değerlendirmesi yok; geçerli bir olumsuz sonuç çıkarılamaz.",
  "Only20 latest correction revisions are shown.": "Yalnızca son20 düzeltme revizyonu gösterilir.",
  "Rates for this exact methodology revision": "Bu tam metodoloji revizyonunun oranları",
  "Scope:": "Kapsam:",
  ". Groups keep requested model revision/account, reported model and entity context separate. A brand or exact project-domain mention counts once per eligible human-evaluated answer; repeated spans do not increase the rate. No global chat coverage, competitor market share or visits is measured.": ". Gruplar istenen model revizyonunu/hesabı, bildirilen modeli ve varlık bağlamını ayrı tutar. Marka veya tam proje alan adı anılması, uygun insan tarafından değerlendirilmiş yanıt başına bir kez sayılır; tekrarlanan aralıklar oranı artırmaz. Küresel sohbet kapsamı, rakip pazar payı veya ziyaretler ölçülmez.",
  "Only100 latest attempts are included; older samples are outside these denominators.": "Yalnızca son100 deneme dahildir; eski örnekler bu paydaların dışındadır.",
  "· returned": "· döndürülen",
  "· account": "· hesap",
  "attempts ·": "deneme ·",
  "Eligible sample IDs:": "Uygun örnek kimlikleri:",
  ". Mention rate": ". Anılma oranı",
  ". Citation rate unavailable, denominator": ". Atıf oranı kullanılamıyor, payda",
  "; no citation-capable observations.": "; atıf ölçümüne uygun gözlem yok.",
  "prompt group:": "istem grubu:",
  "Observed prompt mix": "Gözlenen istem dağılımı",
  ". Exclusions": ". Dışlamalar",
  "Configured competitor": "Yapılandırılmış rakip",
  "sampled mention rate": "örneklenmiş anılma oranı",
  "; not global share.": "; küresel pay değil.",
  "Refresh sample status": "Örnek durumunu yenileyin",
  "Request cancellation": "İptal isteyin",
  "Refresh current choices/history": "Güncel seçenekleri/geçmişi yenileyin",
  "no previous attempt recorded": "önceki deneme kaydedilmemiş",
  "choose set": "küme seçin",
  "manual": "manuel",
  "none": "yok",
  "manual request": "manuel istek",
  "current": "güncel",
  "changed or revoked": "değişti veya iptal edildi",
  "unknown": "bilinmiyor",
  "no attempt recorded": "deneme kaydedilmemiş",
  "not reported": "bildirilmedi",
  "Completed collection; still unevaluated.": "Toplama tamamlandı; hâlâ değerlendirilmemiş.",
  "Ineligible/partial collection; not a valid negative.": "Uygun olmayan/kısmi toplama; geçerli bir olumsuz sonuç değil.",
  "none configured": "yapılandırılmış yok",
  "safe syntax only; not fetched": "yalnızca güvenli sözdizimi; getirilmedi",
  "unsafe/unsupported syntax; not fetched": "güvensiz/desteklenmeyen sözdizimi; getirilmedi",
  "human evaluated; uncertainty still excluded": "insan tarafından değerlendirildi; belirsizlik hâlâ dışlanır",
  "unevaluated": "değerlendirilmemiş",
  "unreported": "bildirilmemiş",
  "unavailable": "kullanılamıyor",
  "Current project sample choices/history unavailable or access revoked.": "Güncel proje örnek seçenekleri/geçmişi kullanılamıyor veya erişim iptal edildi.",
  "One sample queued. Refresh status; no automatic repeat/fallback.": "Bir örnek kuyruğa alındı. Durumu yenileyin; otomatik tekrar/yedek seçenek yok.",
  "Sample outcome unconfirmed. Inspect history or retry unchanged input with the same request key; never automatically replay.": "Örnek sonucu doğrulanmadı. Geçmişi inceleyin veya aynı istek anahtarıyla değiştirilmemiş girdiyi yeniden deneyin; hiçbir zaman otomatik yeniden oynatmayın.",
  "Cancellation confirmed/requested. A started attempt still costs one unit; collected evidence stays private and unevaluated.": "İptal doğrulandı/istendi. Başlatılmış deneme yine bir birim maliyetlidir; toplanmış kanıtlar özel ve değerlendirilmemiş kalır.",
  "Sample status/evidence unavailable. Refresh current project before retrying.": "Örnek durumu/kanıtı kullanılamıyor. Yeniden denemeden önce güncel projeyi yenileyin.",
  "Entity review/rates unavailable; collection evidence remains separate. Refresh before correcting.": "Varlık incelemesi/oranları kullanılamıyor; toplama kanıtları ayrı kalır. Düzeltmeden önce yenileyin.",
  "Factual uncertainty notes must be a bounded JSON array of start/end/note; no verified-fact claims.": "Olgusal belirsizlik notları sınırlı bir start/end/note JSON dizisi olmalıdır; doğrulanmış olgu iddiası yok.",
  "Immutable human correction saved. Rates count each eligible answer once; unresolved/partial/unsupported observations remain excluded.": "Değiştirilemez insan düzeltmesi kaydedildi. Oranlar her uygun yanıtı bir kez sayar; çözümlenmemiş/kısmi/desteklenmeyen gözlemler dışlanır.",
  "Review not confirmed. Inspect current revision/entity configuration, exact Unicode spans and complete collection. Retry unchanged review with the same request key.": "İnceleme doğrulanmadı. Güncel revizyonu/varlık yapılandırmasını, tam Unicode aralıklarını ve eksiksiz toplamayı inceleyin. Değiştirilmemiş incelemeyi aynı istek anahtarıyla yeniden deneyin.",
  "Unreviewed Turkish API sample interface draft in local development. Human prompts, answers and provider evidence retain their original language; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe API örneği arayüzü taslağı. İnsan istemleri, yanıtlar ve sağlayıcı kanıtları özgün dillerini korur; iki dilli onay bekleniyor."
};

@Component({
  selector: 'app-visibility-samples', imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="sample-title">
      <h1 id="sample-title">{{ t("Private API-only answer samples") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish API sample interface draft in local development. Human prompts, answers and provider evidence retain their original language; bilingual approval is pending.") }}</p> }
      <p><a [routerLink]="['/app/dashboard', organizationId, projectId]">{{ t("Return to project evidence") }}</a> ·
        <a [routerLink]="['/app/visibility', organizationId, projectId]">{{ t("Review prompt methodology") }}</a> ·
        <a [routerLink]="['/app/visibility-history', organizationId, projectId]">{{ t("Comparable observation history") }}</a> ·
        <a [routerLink]="['/app/visibility-schedules', organizationId, projectId]">{{ t("Separate opt-in bounded repeats") }}</a></p>
      <p>{{ t("Native OpenAI Responses text-only output, not consumer ChatGPT observations, global visibility, measured demand or visits. Exact human prompt text is sent unchanged: no hidden brand/audience injection, conversation, retrieval or tools. Citation measurement and device/geolocation controls are unavailable; market/language are requested human context, not guaranteed settings.") }}</p>
      <p>{{ t("One explicit standard-access model/account and up to one attempted request/internal unit. Repeat manually at least24hours per set/prompt, including failed/uncertain attempts and corrections. This manual command never enables a repeat schedule, fallback, retry or background research. Token and estimated USD ceilings do not guarantee actual provider charges. Provider terms/live readiness remain unverified.") }}</p>
      <p>{{ t("Prompts/answers are private customer data under organization export/retention/deletion and up to35-day backup expiry after active deletion. store:false does not establish provider Zero Data Retention; abuse monitoring may retain content up to30days with legal/safety exceptions, and prompt caches may retain application state up to24hours. Do not submit secrets, personal data or customer exports.") }}
        <a href="https://developers.openai.com/api/docs/guides/your-data" target="_blank" rel="noopener noreferrer">{{ t("Provider data controls") }}</a>.</p>
      @if (loading()) { <p role="status">{{ t("Loading current project samples and choices.") }}</p> }
      @if (error()) { <p role="alert" [attr.lang]="t(error()) === error() ? 'en' : uiLanguage()">{{ t(error()) }}</p> }
      @if (message()) { <p role="status">{{ t(message()) }}</p> }
      @if (ready()) {
        <p>{{ t("Active project:") }} <span lang="">{{ name() }}</span> {{ t("(organization") }} <span lang="en">{{ organizationId }}</span>{{ t(", project") }} <span lang="en">{{ projectId }}</span>).</p>
        @if (canLaunch() && currentSets().length && models().length && accounts().length) {
          <form (submit)="sample($event)">
            <label for="sample-set">{{ t("Exact-current reviewed prompt set") }}</label><select id="sample-set" name="prompt_set_id" required (change)="chooseSet(+$any($event.target).value)">
              <option value="">{{ t("Choose reviewed methodology") }}</option>@for (row of currentSets(); track row.id) {
                <option lang="" [value]="row.id" [selected]="row.id === selectedSetId()">{{ row.label }} {{ t("· revision") }} {{ row.revision }} · {{ row.market }}/{{ row.language }}</option>
              }
            </select>
            <label for="sample-prompt">{{ t("One unchanged human prompt (separate neutral/branded group)") }}</label><select id="sample-prompt" name="prompt_key" required (change)="promptKey.set($any($event.target).value)">
              <option value="">{{ t("Choose one prompt") }}</option>@for (row of selectedSet()?.prompts || []; track row.key) {
                <option lang="en" [value]="row.key" [selected]="row.key === promptKey()">{{ row.key }} · {{ row.kind }}</option>
              }
            </select>
            @if (selectedPrompt(); as prompt) { <p>{{ t("Intent review") }} <span lang="en">{{ prompt.intent_review_id }}</span> · <span lang="en">{{ prompt.kind }}</span>:</p><pre><span lang="">{{ prompt.text }}</span></pre>
              <p>{{ t("Repeat available at") }} <span [attr.lang]="selectedSet()?.repeat_available_at?.[prompt.key] ? 'en' : uiLanguage()">{{ selectedSet()?.repeat_available_at?.[prompt.key] || t("no previous attempt recorded") }}</span>{{ t(". The server also enforces in-flight exclusion.") }}</p> }
            <label for="sample-model">{{ t("Explicit native standard-access text model (no default)") }}</label><select id="sample-model" name="model_id" required (change)="modelId.set(+$any($event.target).value)">
              <option value="">{{ t("Choose a model") }}</option>@for (row of models(); track row.id) { <option lang="" [value]="row.id">{{ row.name }} · {{ row.identifier }}</option> }
            </select>
            <label for="sample-account">{{ t("Matching credential account") }}</label><select id="sample-account" name="account_id" required>
              <option value="">{{ t("Choose an account") }}</option>@for (row of matchingAccounts(); track row.id) { <option lang="" [value]="row.id">{{ row.label }} ({{ row.source }})</option> }
            </select>
            <label for="sample-tokens">{{ t("Output-token ceiling (within reviewed limit") }} <span lang="en">{{ tokenLimit() }}</span>)</label><input id="sample-tokens" name="max_output_tokens" type="number" min="1" [max]="tokenLimit()" required step="1" />
            <label for="sample-cost">{{ t("Maximum estimated USD (within reviewed ceiling") }} <span [attr.lang]="selectedSet()?.policy?.max_cost_usd ? 'en' : uiLanguage()">{{ selectedSet()?.policy?.max_cost_usd || t("choose set") }}</span>)</label><input id="sample-cost" name="max_cost_usd" required inputmode="decimal" maxlength="10" pattern="[0-9]{1,3}(\\.[0-9]{1,6})?" />
            <label><input type="checkbox" name="acknowledge" required /> {{ t("I reviewed the exact prompt, selected account/model, one-attempt costs, privacy and API-only measurement limits.") }}</label>
            <button type="submit" [disabled]="busy()">{{ t("Reserve one unit and collect one API sample") }}</button>
          </form>
        } @else { <p>{{ t("New samples require launch permission, a current reviewed methodology and configured native standard-access model/account. Historical evidence remains viewable with current project-read access.") }}</p> }
        <h2>{{ t("Recent sample attempts") }}</h2>
          <p>{{ t("Collection leaves answers unevaluated; only a separate human review supplies eligible mention-rate observations. Failed, incomplete, cancelled and unknown attempts are separate from completed evidence.") }}</p>
        <ul>@for (row of jobs(); track row.id) {
          <li>{{ t("Sample") }} <span lang="en">{{ row.id }}</span> · <span lang="en">{{ row.status }}</span> · <span lang="en">{{ row.prompt_key }}</span> (<span lang="en">{{ row.prompt_kind }}</span>{{ t(") · revision") }} <span lang="en">{{ row.revision }}</span> · <span lang="en">{{ row.model_identifier }}</span> · <span lang="en">{{ row.collection_state }}</span>
            <button type="button" [disabled]="busy()" (click)="inspect(row.id)">{{ t("Inspect sample") }} <span lang="en">{{ row.id }}</span></button></li>
        } @empty { <li>{{ t("No sample attempts recorded.") }}</li> }</ul>
        @if (hasMore()) { <p>{{ t("Choices/history are bounded to100 models/accounts and20 sets/recent samples.") }}</p> }
        @if (job(); as row) {
          <h2>{{ t("Sample") }} <span lang="en">{{ row.id }}</span> — <span lang="en">{{ row.status }}</span></h2>
          <p>{{ t("Repeat context") }} <span [attr.lang]="row.repeat_context?.method ? 'en' : uiLanguage()">{{ row.repeat_context?.method || t("manual") }}</span> {{ t("· schedule") }} <span [attr.lang]="row.repeat_context?.schedule_id !== null && row.repeat_context?.schedule_id !== undefined ? 'en' : uiLanguage()">{{ row.repeat_context?.schedule_id ?? t("none") }}</span> {{ t("· occurrence") }} <span [attr.lang]="row.repeat_context?.scheduled_for ? 'en' : uiLanguage()">{{ row.repeat_context?.scheduled_for || t("manual request") }}</span>.</p>
          <p role="status"><span lang="en">{{ row.collection_state }}</span> {{ t("· source/model/actor") }} {{ row.source_current ? t("current") : t("changed or revoked") }} · <span lang="en">{{ row.attempted_units }}</span> {{ t("attempted unit ·") }} <span lang="en">{{ row.updated_at }}</span>.</p>
          @if (row.error_category) { <p role="alert">{{ t("Collection issue:") }} <span lang="en">{{ row.error_category }}</span>{{ t(". No automatic replay.") }}</p> }
          <p>{{ t("Requested model") }} <span lang="en">{{ row.model_identifier }}</span>{{ t(", account") }} <span lang="en">{{ row.account_id }}</span>{{ t(". Preflight estimated USD") }} <span [attr.lang]="row.estimated_max_cost_usd !== null && row.estimated_max_cost_usd !== undefined ? 'en' : uiLanguage()">{{ row.estimated_max_cost_usd ?? t("unknown") }}</span>{{ t(". Repeat available at") }} <span [attr.lang]="row.repeat_available_at ? 'en' : uiLanguage()">{{ row.repeat_available_at || t("no attempt recorded") }}</span>.</p>
          @if (row.methodology; as method) { <p>{{ t("Exact methodology") }} <span lang="en">{{ row.set_id }}</span>{{ t(", revision") }} <span lang="en">{{ row.revision }}</span>{{ t(", prompt") }} <span lang="en">{{ row.prompt_key }}</span> {{ t("· requested") }} <span lang="">{{ method.context.market }}</span>/<span lang="en">{{ method.context.language }}</span> {{ t("(not applied controls).") }}</p><pre><span lang="">{{ method.prompt.text }}</span></pre> }
          @if (row.usage; as usage) { <p>{{ t("Provider request") }} <span lang="en">{{ usage.request_status }}</span> {{ t("· input/output tokens") }} <span [attr.lang]="usage.input_tokens !== null && usage.input_tokens !== undefined ? 'en' : uiLanguage()">{{ usage.input_tokens ?? t("unknown") }}</span>/<span [attr.lang]="usage.output_tokens !== null && usage.output_tokens !== undefined ? 'en' : uiLanguage()">{{ usage.output_tokens ?? t("unknown") }}</span> {{ t("· duration") }} <span [attr.lang]="usage.duration_ms !== null && usage.duration_ms !== undefined ? 'en' : uiLanguage()">{{ usage.duration_ms ?? t("unknown") }}</span> {{ t("ms. Token-based estimated USD") }} <span [attr.lang]="usage.estimated_cost_usd !== null && usage.estimated_cost_usd !== undefined ? 'en' : uiLanguage()">{{ usage.estimated_cost_usd ?? t("unknown") }}</span> {{ t("· provider-reported charge") }} <span [attr.lang]="usage.reported_cost_usd !== null && usage.reported_cost_usd !== undefined ? 'en' : uiLanguage()">{{ usage.reported_cost_usd ?? t("unknown") }}</span>.</p> }
          @else { <p>{{ t("No provider attempt recorded.") }}</p> }
          @if (row.evidence; as evidence) {
            <p>{{ t("Private exact answer · collected") }} <span lang="en">{{ evidence.collected_at }}</span> {{ t("· provider") }} <span lang="en">{{ evidence.provider_status }}</span> {{ t("· returned model") }} <span [attr.lang]="evidence.returned_model ? 'en' : uiLanguage()">{{ evidence.returned_model || t("not reported") }}</span>.
              {{ evidence.collection_eligible ? t("Completed collection; still unevaluated.") : t("Ineligible/partial collection; not a valid negative.") }} <span lang="en">{{ evidence.delivery_limit }}</span>{{ t(". Citation measurement") }} <span lang="en">{{ evidence.citation_measurement }}</span>{{ t(". URLs/markup below are untrusted plain text, never fetched or rendered as HTML.") }}</p>
            <pre lang="" class="answer"><span lang="">{{ evidence.answer }}</span></pre>
          } @else { <p>{{ t("Answer evidence unavailable; this is not a negative mention/citation observation.") }}</p> }
          @if (entityError()) { <p role="alert" [attr.lang]="t(entityError()) === entityError() ? 'en' : uiLanguage()">{{ t(entityError()) }}</p> }
          @if (entities(); as preview) {
            <h3>{{ t("Correctable entity evidence and sample denominators") }}</h3>
            <p>{{ t("Lexical candidates are uncertain until human review, not provider identity/factual verification. Spans use original Unicode codepoints; start is inclusive and end exclusive. Domains match only exact configured hosts: no redirect/subdomain equivalence or citation evidence is inferred. Human-reviewed competitor names resolve to configured domains.") }}</p>
            <p>{{ t("Original answer brand aliases") }} <span lang="">{{ preview.context.brand_aliases.join(', ') }}</span>{{ t("; project domains") }} <span lang="en">{{ preview.context.project_domains.join(', ') }}</span>{{ t(". Current review competitor domains") }} <span [attr.lang]="preview.context.competitor_domains.length ? 'en' : uiLanguage()">{{ preview.context.competitor_domains.join(', ') || t("none configured") }}</span> {{ t("· configuration") }} <span lang="en">{{ preview.context.configuration_revision }}</span>.</p>
            <p>{{ t("Factual comparison:") }} <span lang="">{{ preview.context.business_facts }}</span>{{ t(". Human factual concerns below remain unverified; project configuration/answer text is not an approved business-fact registry.") }}</p>
            @if (preview.candidates.has_more) { <p role="alert">{{ t("Candidates exceed100 spans/50 links. Extraction coverage is truncated; this sample cannot establish an evaluated negative.") }}</p> }
            <ul>@for (link of preview.candidates.links; track $index) {
              <li>{{ t("Text link") }} {{ link.safe_syntax ? t("safe syntax only; not fetched") : t("unsafe/unsupported syntax; not fetched") }} · <span lang="en">{{ link.citation }}</span><pre><span lang="">{{ link.text }}</span></pre></li>
            }</ul>
            @if (canReview()) {
              <form class="entity-review" (submit)="saveReview($event)">
                <p>{{ t("Append a human correction to revision") }} <span lang="en">{{ preview.latest?.revision || 0 }}</span>{{ t(". Inspect the whole exact answer above, resolve every candidate and add missed aliases/spans. An unresolved match excludes the answer from rates.") }}</p>
                @for (match of matchDrafts(); track $index; let i = $index) {
                  <fieldset><legend>{{ t("Entity span") }} <span lang="en">{{ i + 1 }}</span>: <span lang="">{{ spanText(match) }}</span></legend>
                    <label [for]="'entity-kind-' + i">{{ t("Kind") }}</label><select [id]="'entity-kind-' + i" (change)="changeMatch(i, 'kind', $any($event.target).value)">
                      @for (kind of matchKinds; track kind) { <option lang="en" [value]="kind" [selected]="match.kind === kind">{{ kind }}</option> }
                    </select>
                    <label [for]="'entity-name-' + i">{{ t("Resolved entity (project_brand for brand; configured exact domain for competitor)") }}</label><input lang="" [id]="'entity-name-' + i" required maxlength="253" [value]="match.entity" (input)="changeMatch(i, 'entity', $any($event.target).value)" />
                    <label [for]="'entity-start-' + i">{{ t("Start Unicode-codepoint index (inclusive)") }}</label><input [id]="'entity-start-' + i" type="number" min="0" [max]="answerLength()" step="1" required [value]="match.start" (input)="changeMatch(i, 'start', +$any($event.target).value)" />
                    <label [for]="'entity-end-' + i">{{ t("End Unicode-codepoint index (exclusive)") }}</label><input [id]="'entity-end-' + i" type="number" min="1" [max]="answerLength()" step="1" required [value]="match.end" (input)="changeMatch(i, 'end', +$any($event.target).value)" />
                    <label [for]="'entity-decision-' + i">{{ t("Human decision") }}</label><select [id]="'entity-decision-' + i" (change)="changeMatch(i, 'decision', $any($event.target).value)">
                      @for (decision of matchDecisions; track decision) { <option lang="en" [value]="decision" [selected]="match.decision === decision">{{ decision }}</option> }
                    </select>
                    <label [for]="'entity-note-' + i">{{ t("Human alias/domain decision rationale") }}</label><input lang="" [id]="'entity-note-' + i" required maxlength="240" [value]="match.note" (input)="changeMatch(i, 'note', $any($event.target).value)" />
                    <button type="button" [disabled]="busy()" (click)="removeMatch(i)">{{ t("Remove span") }} <span lang="en">{{ i + 1 }}</span></button>
                  </fieldset>
                }
                <button type="button" [disabled]="busy() || matchDrafts().length >= 100" (click)="addMatch()">{{ t("Add a missed human entity/alias span") }}</button>
                <label for="entity-evaluated"><input id="entity-evaluated" name="evaluated" type="checkbox" [checked]="preview.latest?.evaluated || false" [disabled]="!preview.collection_eligible || preview.candidates.has_more" />
                  {{ t("I reviewed the complete valid collected answer, including absence and all uncertain aliases. Uncertain matches still keep the denominator unavailable.") }}</label>
                <label for="entity-review-note">{{ t("Full-answer evaluation/correction rationale") }}</label><textarea lang="" id="entity-review-note" name="review_note" required maxlength="500" [value]="preview.latest?.review_note || ''"></textarea>
                <label for="entity-factual-notes">{{ t("Optional factual-uncertainty evidence (JSON array, up to10 {start,end,note}; no verified-fact claims)") }}</label><textarea lang="" id="entity-factual-notes" name="factual_notes" maxlength="4000" rows="3" [value]="factualDraft()"></textarea>
                <button type="submit" [disabled]="busy()">{{ t("Save immutable human entity review (no provider call)") }}</button>
              </form>
            } @else { <p>{{ t("Owner/admin role is required to correct/evaluate answer evidence.") }}</p> }
            <h4>{{ t("Human correction history") }}</h4>
            <ul>@for (review of preview.history; track review.id) { <li>{{ t("Revision") }} <span lang="en">{{ review.revision }}</span> · <span lang="en">{{ review.created_at }}</span> · {{ review.evaluated ? t("human evaluated; uncertainty still excluded") : t("unevaluated") }} · <span lang="">{{ review.review_note }}</span></li> }
              @empty { <li>{{ t("No human evaluation exists; no valid negative can be inferred.") }}</li> }</ul>
            @if (preview.history_has_more) { <p>{{ t("Only20 latest correction revisions are shown.") }}</p> }
            <h4>{{ t("Rates for this exact methodology revision") }}</h4>
            <p>{{ t("Scope:") }} <span lang="en">{{ preview.rates.scope }}</span>{{ t(". Groups keep requested model revision/account, reported model and entity context separate. A brand or exact project-domain mention counts once per eligible human-evaluated answer; repeated spans do not increase the rate. No global chat coverage, competitor market share or visits is measured.") }}</p>
            @if (preview.rates.has_more) { <p>{{ t("Only100 latest attempts are included; older samples are outside these denominators.") }}</p> }
            @for (group of preview.rates.groups; track $index) {
              <details open><summary><span lang="en">{{ group.requested_model }}</span> {{ t("· returned") }} <span [attr.lang]="group.returned_model ? 'en' : uiLanguage()">{{ group.returned_model || t("unreported") }}</span> {{ t("· account") }} <span lang="en">{{ group.account_id }}</span> · <span lang="en">{{ group.sample_ids.length }}</span> {{ t("attempts ·") }} <span [attr.lang]="group.repeat_policy?.method ? 'en' : uiLanguage()">{{ group.repeat_policy?.method || t("manual") }}</span></summary>
                <p>{{ t("Eligible sample IDs:") }} <span [attr.lang]="group.eligible_sample_ids.length ? 'en' : uiLanguage()">{{ group.eligible_sample_ids.join(', ') || t("none") }}</span>{{ t(". Mention rate") }} <span lang="en">{{ group.mention_rate.numerator }}</span>/<span lang="en">{{ group.mention_rate.denominator }}</span> — <span [attr.lang]="group.mention_rate.percent === null ? uiLanguage() : 'en'">{{ group.mention_rate.percent === null ? t("unavailable") : group.mention_rate.percent + '%' }}</span>{{ t(". Citation rate unavailable, denominator") }} <span lang="en">{{ group.citation_rate.denominator }}</span>{{ t("; no citation-capable observations.") }}</p>
                <ul>@for (item of rateEntries(group.neutral_branded_rates); track item[0]) { <li><span lang="en">{{ item[0] }}</span> {{ t("prompt group:") }} <span lang="en">{{ item[1].numerator }}</span>/<span lang="en">{{ item[1].denominator }}</span> · <span [attr.lang]="item[1].percent === null ? uiLanguage() : 'en'">{{ item[1].percent === null ? t("unavailable") : item[1].percent + '%' }}</span></li> }</ul>
                <p>{{ t("Observed prompt mix") }} <span lang="en">{{ counts(group.prompt_mix) }}</span>{{ t(". Exclusions") }} <span [attr.lang]="counts(group.exclusions) ? 'en' : uiLanguage()">{{ counts(group.exclusions) || t("none") }}</span>.</p>
                <ul>@for (item of rateEntries(group.competitor_mention_rates); track item[0]) { <li>{{ t("Configured competitor") }} <span lang="en">{{ item[0] }}</span> {{ t("sampled mention rate") }} <span lang="en">{{ item[1].numerator }}</span>/<span lang="en">{{ item[1].denominator }}</span> · <span [attr.lang]="item[1].percent === null ? uiLanguage() : 'en'">{{ item[1].percent === null ? t("unavailable") : item[1].percent + '%' }}</span>{{ t("; not global share.") }}</li> }</ul>
              </details>
            }
          }
          <button type="button" [disabled]="busy()" (click)="inspect(row.id)">{{ t("Refresh sample status") }}</button>
          @if (canLaunch() && ['queued', 'running'].includes(row.status) && !row.cancel_requested) {
            <button type="button" [disabled]="busy()" (click)="inspect(row.id, true)">{{ t("Request cancellation") }}</button>
          }
        }
      }
      <button type="button" [disabled]="busy()" (click)="load()">{{ t("Refresh current choices/history") }}</button>
    </section>`,
  styles: `label { display:block; margin-block:.6rem .2rem } input:not([type=checkbox]),select,textarea { width:min(100%,42rem); max-width:100% } fieldset { min-width:0 } pre { white-space:pre-wrap } section,li { overflow-wrap:anywhere } button { margin:.6rem .6rem .6rem 0 }`,
})
export class VisibilitySamples implements OnInit {
  readonly documentTitle = signal('Private API-only answer samples');
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  t(text: string) { return this.uiLanguage() === 'tr' ? visibilitySamplesTurkish[text] ?? text : text; }
  organizationId = 0; projectId = 0; private generation = 0; private selectedJobId = 0; private pending = { input: '', key: '' };
  readonly loading = signal(true); readonly ready = signal(false); readonly busy = signal(false); readonly error = signal(''); readonly message = signal('');
  readonly name = signal(''); readonly canLaunch = signal(false); readonly sets = signal<PromptSet[]>([]);
  readonly models = signal<Model[]>([]); readonly accounts = signal<Account[]>([]); readonly jobs = signal<Job[]>([]); readonly job = signal<Job | null>(null);
  readonly hasMore = signal(false); readonly selectedSetId = signal(0); readonly promptKey = signal(''); readonly modelId = signal(0);
  readonly canReview = signal(false); readonly entities = signal<EntityPreview | null>(null); readonly entityError = signal('');
  readonly matchDrafts = signal<Match[]>([]); readonly factualDraft = signal('[]');
  readonly matchKinds = ['brand', 'competitor', 'project_domain', 'competitor_domain', 'other_domain']; readonly matchDecisions = ['uncertain', 'confirmed', 'rejected'];
  private pendingReview = { input: '', key: '' };
  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi, private readonly destroy: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t(this.documentTitle())} — OrganicSEOOps`));
  }
  ngOnInit() { void this.loadProductLanguage(); this.route.paramMap.pipe(takeUntilDestroyed(this.destroy)).subscribe((params) => {
    this.organizationId = Number(params.get('organizationId')); this.projectId = Number(params.get('projectId')); this.selectedJobId = Number(params.get('jobId'));
    this.documentTitle.set(params.has('jobId') ? 'Private API-only sample evidence' : 'Private API-only answer samples');
    this.pending = { input: '', key: '' }; void this.load();
  }); this.destroy.onDestroy(() => ++this.generation); }
  private async loadProductLanguage() {
    try {
      const result = await this.api.productLanguage();
      if (!this.destroy.destroyed && result.status === 200 && isProductLanguageResult(result.body)) {
        this.productLanguage.set(result.body['language']);
      }
    } catch { /* Keep English when the private preference is unavailable. */ }
  }
  currentSets() { return this.sets().filter((row) => row.source_current); }
  selectedSet() { return this.currentSets().find((row) => row.id === this.selectedSetId()); }
  selectedPrompt() { return this.selectedSet()?.prompts.find((row) => row.key === this.promptKey()); }
  chooseSet(id: number) { this.selectedSetId.set(id); this.promptKey.set(''); }
  matchingAccounts() { const model = this.models().find((row) => row.id === this.modelId()); return model ? this.accounts().filter((row) => row.provider_id === model.provider_id) : []; }
  tokenLimit() { return Math.min(256, this.selectedSet()?.policy.max_output_tokens ?? 256, this.models().find((row) => row.id === this.modelId())?.max_output_tokens ?? 256); }
  async load() {
    const generation = ++this.generation; this.loading.set(true); this.ready.set(false); this.error.set(''); this.message.set(''); this.busy.set(false);
    this.name.set(''); this.canLaunch.set(false); this.sets.set([]); this.models.set([]); this.accounts.set([]); this.jobs.set([]); this.job.set(null);
    this.selectedSetId.set(0); this.promptKey.set(''); this.modelId.set(0);
    this.canReview.set(false); this.entities.set(null); this.entityError.set(''); this.matchDrafts.set([]); this.factualDraft.set('[]'); this.pendingReview = { input: '', key: '' };
    try {
      const context = await this.api.projectOnboarding(this.organizationId, this.projectId);
      if (generation !== this.generation) return;
      const project = context.body['project'] as Record<string, unknown> | undefined;
      if (context.status !== 200 || project?.['id'] !== this.projectId || project['organization_id'] !== this.organizationId
          || typeof project['role'] !== 'string' || !['owner', 'admin', 'member', 'viewer'].includes(project['role'])) throw new Error();
      const response = await this.api.visibilitySamples(this.organizationId, this.projectId); const body = response.body;
      if (generation !== this.generation) return;
      if (response.status !== 200 || body['project_id'] !== this.projectId || body['method'] !== 'visibility-text-collection-v1'
        || body['surface'] !== 'openai_responses_text' || body['automatic_schedule'] !== false || body['live_verified'] !== false
        || !['models', 'accounts', 'prompt_sets', 'jobs'].every((key) => Array.isArray(body[key]))
        || (body['prompt_sets'] as PromptSet[]).some((row) => row.project_id !== this.projectId)
        || (body['jobs'] as Job[]).some((row) => row.project_id !== this.projectId)) throw new Error();
      this.name.set(String(project['name'])); this.canLaunch.set(['owner', 'admin', 'member'].includes(project['role']));
      this.canReview.set(['owner', 'admin'].includes(project['role']));
      this.sets.set(body['prompt_sets'] as PromptSet[]); this.models.set(body['models'] as Model[]); this.accounts.set(body['accounts'] as Account[]);
      this.jobs.set(body['jobs'] as Job[]); this.hasMore.set(body['has_more'] === true); this.ready.set(true);
      if (Number.isSafeInteger(this.selectedJobId) && this.selectedJobId > 0) await this.inspect(this.selectedJobId);
    } catch { if (generation === this.generation) this.error.set('Current project sample choices/history unavailable or access revoked.'); }
    finally { if (generation === this.generation) this.loading.set(false); }
  }
  async sample(event: SubmitEvent) {
    event.preventDefault(); const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || this.busy() || !this.canLaunch() || !this.selectedPrompt()) return;
    const fields = new FormData(form); const accountId = Number(fields.get('account_id'));
    if (fields.get('acknowledge') !== 'on' || !this.matchingAccounts().some((row) => row.id === accountId)) return;
    const data = { prompt_set_id: this.selectedSetId(), prompt_key: this.promptKey(), model_id: this.modelId(), account_id: accountId,
      max_output_tokens: Number(fields.get('max_output_tokens')), max_cost_usd: String(fields.get('max_cost_usd')), acknowledge_api_limits: true };
    const input = JSON.stringify([this.organizationId, this.projectId, data]);
    if (input !== this.pending.input) this.pending = { input, key: crypto.randomUUID() };
    const generation = this.generation; this.busy.set(true); this.error.set('');
    try {
      const response = await this.api.visibilitySamples(this.organizationId, this.projectId, 0, { ...data, idempotency_key: this.pending.key });
      if (generation !== this.generation) return;
      const row = this.readJob(response.body['job']);
      if (response.status !== 202 || response.body['project_id'] !== this.projectId || !row) { this.error.set(String(response.body['code'] || 'sample_not_confirmed') + ': check current methodology/model/account, budget and24h repeat policy. Retry unchanged inputs with the same request key or inspect history.'); return; }
      this.job.set(row); this.jobs.update((rows) => [row, ...rows.filter((item) => item.id !== row.id)].slice(0, 20));
      this.message.set('One sample queued. Refresh status; no automatic repeat/fallback.'); form.reset(); this.selectedSetId.set(0); this.promptKey.set(''); this.modelId.set(0);
      this.pending = { input: '', key: '' };
      if (row.evidence) await this.loadEntities(row.id, generation);
    } catch { if (generation === this.generation) this.error.set('Sample outcome unconfirmed. Inspect history or retry unchanged input with the same request key; never automatically replay.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  async inspect(id: number, cancel = false) {
    if (this.busy() || cancel && !this.canLaunch()) return;
    const generation = this.generation; this.busy.set(true); this.error.set(''); this.job.set(null);
    this.entities.set(null); this.entityError.set(''); this.matchDrafts.set([]);
    try {
      const response = await this.api.visibilitySamples(this.organizationId, this.projectId, id, cancel ? {} : undefined);
      if (generation !== this.generation) return;
      const row = this.readJob(response.body['job']);
      if (response.status !== 200 || response.body['project_id'] !== this.projectId || !row || row.id !== id) throw new Error();
      this.job.set(row); this.jobs.update((rows) => rows.map((item) => item.id === id ? { ...row, evidence: null, methodology: null } : item));
      if (cancel) this.message.set('Cancellation confirmed/requested. A started attempt still costs one unit; collected evidence stays private and unevaluated.');
      if (row.evidence) await this.loadEntities(row.id, generation);
    } catch { if (generation === this.generation) this.error.set('Sample status/evidence unavailable. Refresh current project before retrying.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  private readJob(value: unknown): Job | null {
    const row = value as Job | null;
    return row && Number.isSafeInteger(row.id) && row.project_id === this.projectId && typeof row.status === 'string'
      && (row.evidence === null || typeof row.evidence?.answer === 'string' && row.evidence.answer.length <= 4000
        && row.evidence.evaluation === 'unevaluated' && row.evidence.citation_measurement === 'unavailable') ? row : null;
  }
  answerLength() { return Array.from(this.job()?.evidence?.answer || '').length; }
  spanText(row: Match) { return Array.from(this.job()?.evidence?.answer || '').slice(row.start, row.end).join(''); }
  changeMatch(index: number, field: keyof Match, value: string | number) { this.matchDrafts.update((rows) => rows.map((row, i) => i === index ? { ...row, [field]: value } : row)); }
  removeMatch(index: number) { this.matchDrafts.update((rows) => rows.filter((_, i) => i !== index)); }
  addMatch() { if (this.matchDrafts().length < 100) this.matchDrafts.update((rows) => [...rows, { kind: 'brand', entity: 'project_brand', start: 0, end: 1, decision: 'uncertain', note: '' }]); }
  counts(value: Record<string, number>) { return Object.entries(value).map(([key, count]) => key + ': ' + count).join(', '); }
  rateEntries(value: Record<string, Rate>) { return Object.entries(value); }
  private acceptEntities(value: unknown, id: number): boolean {
    const preview = value as EntityPreview;
    if (!preview || preview.project_id !== this.projectId || preview.job_id !== id || preview.method !== 'visibility-entities-v1'
      || !Array.isArray(preview.candidates?.matches) || !Array.isArray(preview.history) || !Array.isArray(preview.rates?.groups)) return false;
    this.entities.set(preview); this.matchDrafts.set((preview.latest?.matches ?? preview.candidates.matches).map((row) => ({ ...row })));
    this.factualDraft.set(JSON.stringify(preview.latest?.factual_notes ?? [], null, 2)); return true;
  }
  private async loadEntities(id: number, generation: number) {
    try {
      const response = await this.api.visibilityEntities(this.organizationId, this.projectId, id);
      if (generation !== this.generation || this.job()?.id !== id) return;
      if (response.status !== 200 || !this.acceptEntities(response.body, id)) throw new Error();
    } catch { if (generation === this.generation && this.job()?.id === id) this.entityError.set('Entity review/rates unavailable; collection evidence remains separate. Refresh before correcting.'); }
  }
  async saveReview(event: SubmitEvent) {
    event.preventDefault(); const form = event.currentTarget as HTMLFormElement; const job = this.job(); const preview = this.entities();
    if (!form.reportValidity() || this.busy() || !this.canReview() || !job || !preview) return;
    const fields = new FormData(form); let facts: unknown;
    try { facts = JSON.parse(String(fields.get('factual_notes') || '[]')); if (!Array.isArray(facts)) throw new Error(); }
    catch { this.entityError.set('Factual uncertainty notes must be a bounded JSON array of start/end/note; no verified-fact claims.'); return; }
    const data = { expected_revision: preview.latest?.revision ?? 0, expected_configuration_revision: preview.context.configuration_revision,
      matches: this.matchDrafts(), evaluated: fields.has('evaluated'), review_note: String(fields.get('review_note')), factual_notes: facts };
    const input = JSON.stringify([this.projectId, job.id, data]); if (input !== this.pendingReview.input) this.pendingReview = { input, key: crypto.randomUUID() };
    const generation = this.generation; this.busy.set(true); this.entityError.set('');
    try {
      const response = await this.api.visibilityEntities(this.organizationId, this.projectId, job.id, { ...data, request_key: this.pendingReview.key });
      if (generation !== this.generation || this.job()?.id !== job.id) return;
      if (response.status !== 201 || !this.acceptEntities(response.body, job.id)) throw new Error();
      this.pendingReview = { input: '', key: '' }; this.message.set('Immutable human correction saved. Rates count each eligible answer once; unresolved/partial/unsupported observations remain excluded.');
    } catch { if (generation === this.generation) this.entityError.set('Review not confirmed. Inspect current revision/entity configuration, exact Unicode spans and complete collection. Retry unchanged review with the same request key.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
}
