import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, OnInit, computed, effect, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi, ApiResult } from '../account/account-api';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';
import { safeUrl, same } from './authority-links';

const POLICY = 'content-human-quality-v1';
const positive = (value: unknown) => Number.isSafeInteger(value) && Number(value) > 0;
const object = (value: unknown) => !!value && typeof value === 'object' && !Array.isArray(value);
const aware = (value: unknown): value is string => typeof value === 'string'
  && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const dated = (value: unknown): value is string => aware(value) && Date.parse(value) <= Date.now();
const digest = (value: unknown) => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
function pageUrl(value: unknown) {
  if (typeof value !== 'string' || !/^https?:\/\/[^/?#]/.test(value) || /[\s\\\u0000-\u001f]/.test(value)) return '';
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol)
    && !url.username && !url.password && !url.search && !url.hash
    && value.startsWith(url.origin + '/') ? value : ''; }
  catch { return ''; }
}
type Text = { id: number; project_id: number; item_id: number; revision: number; brief_id: number;
  kind: string; title: string; body: string; meta_description: string; state: string; created_at: string };
type Source = { method: string; project_id: number; configuration_revision: number; source_current: boolean;
  content: { item_id: number; revision_id: number; revision: number; kind: string; title: string; text_sha256: string;
    state: string; actor_id: number; created_at: string; publication_url: string; published_at: string | null;
    publication_basis: string; archive_effect: string };
  brief: { id: number; sha256: string; size_bytes: number; created_at: string; actor_id: number };
  action: { review_id: number; action_id: string; revision: number; affected_urls: string[]; approval: string };
  sources: (Record<string, unknown> & { source_index: number; method?: string; state?: string; retrieved_at: string | null })[];
  expertise: string; service_facts: string; quality_judgment: string; conversion_context: string; interpretation: string };
type Intake = Record<string, unknown> & { policy: string; content_revision_id: number; text_sha256: string;
  reviewed_at: string; judgment: string; substantive_basis: string; quote: string; evidence_note: string;
  expertise_note: string; service_fact_note: string; facts_checked_at: string; proposed_action: string;
  rationale: string; destination_url: string; destination_review: string; user_impact: string };
type Review = { id: number; review_id: string; project_id: number; revision: number; content_revision_id: number;
  state: string; intake: Intake; source_evidence: Source; assignee_id: number; actor_id: number; source_actor_id: number;
  reason: string; reviewed_revision_id: number | null; approved_by_id: number | null; approved_at: string | null;
  executed_at: string | null; execution_note: string; created_at: string; source_current: boolean;
  is_latest: boolean; effective_approval: boolean; scope: string; execution_state: string };
type Context = { organization_id: number; project_id: number; policy: string; can_review: boolean;
  sources: Source[]; assignees: { id: number }[]; sources_has_more: boolean; reviews: Review[]; has_more: boolean;
  source_basis: string; site_action: string };
type Pending = { data: Record<string, unknown>; source: Source; text: Text; reviewId?: string; previous?: Review };
type PairSide = { organization_id: number; project_id: number; source: Source; text: Pick<Text, 'kind' | 'title' | 'body' | 'meta_description'> };
type Pair = { method: string; left: PairSide; right: PairSide; same_native_body: boolean; interpretation: string; site_action: string };
const INTAKE_LIMITS = { reviewed_at: 64, judgment: 64, substantive_basis: 64, quote: 1000, evidence_note: 1000,
  expertise_note: 1000, service_fact_note: 1000, facts_checked_at: 64, proposed_action: 32, rationale: 500,
  destination_url: 512, destination_review: 500, user_impact: 500 } as const;
const INTAKE_TEXT = Object.keys(INTAKE_LIMITS) as (keyof typeof INTAKE_LIMITS)[];
const RIGHTS = ['use_permission', 'storage_permission', 'not_restricted_copy', 'no_personal_payload'];

function validText(value: unknown, limit: number, required = false): value is string {
  return typeof value === 'string' && Array.from(value).length <= limit
    && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f\ud800-\udfff]/u.test(value)
    // Match Python str.strip without changing the original stored text.
    && (!required || /[^\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/u.test(value));
}
function intakeWithinBounds(data: Intake) {
  if (!object(data) || Object.keys(data).length !== 20 || data.policy !== POLICY
    || !positive(data.content_revision_id) || !digest(data.text_sha256) || !RIGHTS.every((key) => data[key] === true)
    || !INTAKE_TEXT.every((key) => validText(data[key], INTAKE_LIMITS[key]))) return false;
  // Python's flat scalar JSON adds one space after each colon and comma.
  return new TextEncoder().encode(JSON.stringify(data)).length + Object.keys(data).length * 2 - 1 <= 16 * 1024;
}
function privateEvidenceWithinBounds(source: Source, intake: Intake) {
  // Match the model's default ASCII-escaped JSON, spacing only structural punctuation.
  const encoded = JSON.stringify({ source, intake })
    .replace(/[\u007f-\uffff]/g, (character) => '\\u' + character.charCodeAt(0).toString(16).padStart(4, '0'))
    .replace(/"(?:\\.|[^"\\])*"|[:,]/g, (token) => token === ':' || token === ',' ? token + ' ' : token);
  return encoded.length <= 32 * 1024;
}

function isSource(value: unknown, project: number): value is Source {
  if (!object(value)) return false;
  const row = value as Source, content = row.content, brief = row.brief, action = row.action;
  return row.method === 'content-lifecycle-source-v1' && row.project_id === project && row.source_current === true
    && Number.isSafeInteger(row.configuration_revision) && row.configuration_revision >= 0
    && !!content && [content.item_id, content.revision_id, content.revision, content.actor_id].every(positive)
    && ['kind', 'title', 'state', 'publication_url'].every((key) => typeof (content as unknown as Record<string, unknown>)[key] === 'string')
    && digest(content.text_sha256) && dated(content.created_at) && (content.published_at === null || dated(content.published_at))
    && (!content.publication_url || !!pageUrl(content.publication_url))
    && content.publication_basis === 'historical_manual_report_not_verified_live_content_or_publication_age'
    && content.archive_effect === 'record_only_no_live_page_removed'
    && !!brief && positive(brief.id) && positive(brief.size_bytes) && positive(brief.actor_id) && digest(brief.sha256)
    && dated(brief.created_at) && Date.parse(brief.created_at) <= Date.parse(content.created_at)
    && !!action && positive(action.review_id) && positive(action.revision)
    && typeof action.action_id === 'string' && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/.test(action.action_id)
    && Array.isArray(action.affected_urls) && action.affected_urls.length > 0 && action.affected_urls.length <= 2
    && action.affected_urls.every((url) => !!pageUrl(url))
    && action.approval === 'separate_existing_page_action_not_content_lifecycle_approval'
    && Array.isArray(row.sources) && row.sources.length > 0 && row.sources.length <= 5
    && row.sources.every((source) => object(source) && Number.isSafeInteger(source.source_index)
      && source.source_index >= 0 && source.source_index < 5 && (source.method === undefined
        ? typeof source.state === 'string' && source.state !== 'collected' && source.retrieved_at === null && source['facts'] === 'unavailable'
        : source.method === 'authority-research-evidence-v1' && positive(source['research_job_id']) && positive(source['step_id'])
          && positive(source['artifact_id']) && positive(source['source_size_bytes']) && dated(source.retrieved_at)
          && Date.parse(source.retrieved_at) <= Date.parse(brief.created_at)
          && digest(source['original_response_sha256']) && !!safeUrl(source['requested_url']) && !!safeUrl(source['url'])
          && typeof source['title'] === 'string' && typeof source['excerpt_truncated'] === 'boolean'
          && source['coverage'] === 'selected_bounded_public_page_text_only' && source['facts'] === 'unverified'))
    && row.sources.some((source) => !!source.method)
    && row.expertise === 'not_recorded_requires_human_evidence' && row.service_facts === 'not_verified_by_research_or_manual_local_assessment'
    && row.quality_judgment === 'not_recorded' && row.conversion_context === 'unavailable_exact_origin_attribution_not_established'
    && row.interpretation === 'saved_native_text_and_dated_sources_not_live_page_quality_or_deletion_recommendation';
}

function validIntakeDeclaration(data: Intake, source: Source) {
  if (!intakeWithinBounds(data) || !privateEvidenceWithinBounds(source, data)
    || !dated(data.reviewed_at) || Date.parse(data.reviewed_at) < Date.parse(source.content.created_at)
    || validText(data.service_fact_note, 1000, true) !== !!data.facts_checked_at
    || data.facts_checked_at && (!dated(data.facts_checked_at) || Date.parse(data.facts_checked_at) > Date.parse(data.reviewed_at))) return false;
  const checked = data.judgment !== 'not_checked';
  if (checked ? !['no_issue_found_in_reviewed_text', 'outdated_claim', 'thin_coverage', 'overlap', 'service_detail_changed'].includes(data.judgment)
    || !['content_claim_check', 'business_expertise_review', 'coverage_review'].includes(data.substantive_basis)
    || !validText(data.quote, 1000, true)
    || !validText(data.evidence_note, 1000, true)
    || data.substantive_basis === 'business_expertise_review' && !(validText(data.expertise_note, 1000, true) || validText(data.service_fact_note, 1000, true))
    || data.judgment === 'service_detail_changed' && !validText(data.service_fact_note, 1000, true)
    : data.substantive_basis !== 'unreviewed' || !!data.quote || !!data.evidence_note) return false;
  if (data.proposed_action === 'unselected') return ![data.rationale, data.destination_url, data.destination_review, data.user_impact].some(Boolean);
  if (!checked || !['keep', 'refresh', 'consolidate', 'redirect', 'retire'].includes(data.proposed_action)
    || !validText(data.rationale, 500, true) || !validText(data.user_impact, 500, true)) return false;
  if (!['consolidate', 'redirect', 'retire'].includes(data.proposed_action)) return !data.destination_url && !data.destination_review;
  const url = pageUrl(data.destination_url);
  // The server checks every configured project origin/alias; a source page is not an origin inventory.
  return !!url && url === data.destination_url && !source.action.affected_urls.includes(url)
    && url !== source.content.publication_url && validText(data.destination_review, 500, true);
}

function isReview(value: unknown, project: number): value is Review {
  if (!object(value)) return false;
  const row = value as Review, data = row.intake;
  const approved = ['approved', 'reported'].includes(row.state);
  return positive(row.id) && typeof row.review_id === 'string' && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/.test(row.review_id)
    && row.project_id === project && [row.revision, row.assignee_id, row.actor_id, row.source_actor_id].every(positive)
    && ['draft', 'review', 'approved', 'reported', 'dismissed'].includes(row.state) && dated(row.created_at)
    && validText(row.reason, 500, true) && validText(row.execution_note, 500, row.state === 'reported')
    && [row.source_current, row.is_latest, row.effective_approval].every((flag) => typeof flag === 'boolean')
    && (approved ? positive(row.reviewed_revision_id) && positive(row.approved_by_id) && dated(row.approved_at)
      : row.reviewed_revision_id === null && row.approved_by_id === null && row.approved_at === null)
    && (row.state === 'reported' ? dated(row.executed_at) && dated(row.approved_at)
      && Date.parse(row.executed_at) >= Date.parse(row.approved_at) && validText(row.execution_note, 500, true)
      : row.executed_at === null && row.execution_note === '')
    && row.execution_state === (row.state === 'reported' ? 'manual_handoff_not_site_implementation_or_outcome' : 'not_reported')
    && row.scope === 'historical_human_content_judgment_not_verified_live_quality_or_site_approval'
    && isSource(row.source_evidence, project) && validIntakeDeclaration(data, row.source_evidence)
    && row.content_revision_id === data.content_revision_id && data.content_revision_id === row.source_evidence.content.revision_id
    && data.text_sha256 === row.source_evidence.content.text_sha256
    && (!['review', 'approved', 'reported'].includes(row.state) || data.proposed_action !== 'unselected')
    && row.effective_approval === (approved && row.source_current && row.is_latest);
}

async function textMatches(value: unknown, source: Source, project: number): Promise<boolean> {
  if (!object(value)) return false;
  const text = value as Text, content = source.content;
  if (text.project_id !== project || text.id !== content.revision_id || text.item_id !== content.item_id
    || text.revision !== content.revision || text.brief_id !== source.brief.id || text.state !== content.state
    || text.created_at !== content.created_at || text.title !== content.title || text.kind !== content.kind
    || typeof text.body !== 'string' || !text.body.trim() || Array.from(text.body).length > 30000 || typeof text.meta_description !== 'string') return false;
  const bytes = new TextEncoder().encode(JSON.stringify({ body: text.body, kind: text.kind, meta_description: text.meta_description, title: text.title }));
  const hash = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, '0')).join('') === content.text_sha256;
}

const contentLifecycleTurkish: Record<string, string> = {
  "Private human content-quality review": "Özel insan içerik kalitesi incelemesi",
  "Existing-content human quality and lifecycle review": "Mevcut içerik için insan kalite ve yaşam döngüsü incelemesi",
  "Unreviewed Turkish content-lifecycle interface draft in local development. Human judgments and source texts retain their original language; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe içerik yaşam döngüsü arayüzü taslağı. İnsan değerlendirmeleri ve kaynak metinleri özgün dillerini korur; iki dilli onay bekleniyor.",
  "Organization": "Kuruluş",
  "· project": "· proje",
  "Content studio": "İçerik stüdyosu",
  "Project evidence": "Proje kanıtları",
  "Separate site action approval, implementation and dated outcomes": "Ayrı site eylemi onayı, uygulama ve tarihli sonuçlar",
  "Saved native text and dated research are not verified live-page quality, publication age, business expertise or service facts. Local business assessments are user-attested. Conversion context is unavailable. Missing facts, age, low traffic or word count alone never justify deletion.": "Kaydedilmiş düz metin ve tarihli araştırma; doğrulanmış canlı sayfa kalitesi, yayın yaşı, işletme uzmanlığı veya hizmet bilgileri değildir. Yerel işletme değerlendirmeleri kullanıcı beyanıdır. Dönüşüm bağlamı kullanılamıyor. Eksik bilgiler, yaş, düşük trafik veya kelime sayısı tek başına silmeyi hiçbir zaman haklı çıkarmaz.",
  "Supply independent first-hand business evidence, no personal identities, secrets or restricted provider copies. Private records follow 90-day retained access after lapse, active deletion within 30 days of closure/expiry and up to 35-day backup rotation after deletion. Approval covers only this exact human judgment and proposal. Manual handoff, live site work and subsequent outcomes are separate. Archiving a record does not remove a live page.": "Bağımsız, birinci el işletme kanıtı sağlayın; kişisel kimlik, sır veya kısıtlı sağlayıcı kopyası eklemeyin. Özel kayıtlar, erişim süresi bittikten sonra 90 günlük saklanan erişime, kapatma/süre bitiminden sonraki 30 gün içinde aktif silmeye ve silmeden sonra en fazla 35 günlük yedek rotasyonuna tabidir. Onay yalnızca bu insan değerlendirmesinin ve önerisinin tamamını kapsar. Manuel devir, canlı site çalışması ve sonraki sonuçlar ayrıdır. Bir kaydı arşivlemek canlı sayfayı kaldırmaz.",
  "Loading current content sources and private human history.": "Güncel içerik kaynakları ve özel insan geçmişi yükleniyor.",
  "Exact save outcome is uncertain. Source, native text and command are frozen in component memory only; no automatic replay.": "Tam kayıt sonucu belirsiz. Kaynak, düz metin ve komut yalnızca bileşen belleğinde sabitlenir; otomatik yeniden yürütme yoktur.",
  "Check exact uncertain save": "Belirsiz kaydın tamamını kontrol edin",
  "Deliberately retry same exact command": "Aynı tam komutu bilinçli olarak tekrar deneyin",
  "Reload current project": "Güncel projeyi yeniden yükleyin",
  "Refresh current sources and history": "Güncel kaynakları ve geçmişi yenileyin",
  "Current flags are as of refresh; every command rechecks current source, exact text, original actors, assignee and latest review.": "Güncel göstergeler yenileme anına aittir; her komut güncel kaynağı, tam metni, özgün işlemi yapanları, atanan kişiyi ve son incelemeyi yeniden kontrol eder.",
  "No human quality review recorded for this project.": "Bu proje için insan kalite incelemesi kaydedilmedi.",
  "Only the latest 50 reviews are shown; inventory is incomplete.": "Yalnızca son 50 inceleme gösterilir; envanter eksiktir.",
  "Latest human content-quality reviews": "Son insan içerik kalitesi incelemeleri",
  "· human": "· insan",
  "· revision": "· sürüm",
  "· assignee": "· atanan kişi",
  "Inspect exact judgment and history": "Değerlendirmenin tamamını ve geçmişi inceleyin",
  "Exact quality revision": "Tam kalite sürümü",
  "Content item": "İçerik kaydı",
  "· exact text revision": "· tam metin sürümü",
  "· digest": "· özet",
  "Responsible assignee": "Sorumlu atanan kişi",
  "· human source actor": "· insan kaynak işlemini yapan",
  "· decision actor": "· karar işlemini yapan",
  "· reviewed": "· incelendi",
  "Exact stored native-text quote": "Saklanan düz metinden tam alıntı",
  "Substantive human judgment": "Esaslı insan değerlendirmesi",
  "First-hand expertise and service facts (human declarations, not independent verification)": "Birinci el uzmanlık ve hizmet bilgileri (insan beyanları; bağımsız doğrulama değildir)",
  "Original fact-check date": "Özgün bilgi kontrol tarihi",
  "Human lifecycle proposal and user-impact review": "İnsan yaşam döngüsü önerisi ve kullanıcı etkisi incelemesi",
  "Distinct reviewed replacement:": "İncelenmiş farklı hedef:",
  "· approval": "· onay",
  "Source/text/reviewer/assignee stale or unavailable. Retained judgment is historical; new approval or handoff is denied.": "Kaynak/metin/inceleyen/atanan kişi eski veya kullanılamıyor. Saklanan değerlendirme geçmişe aittir; yeni onay veya devir reddedilir.",
  "Actual manual handoff reported": "Gerçek manuel devir bildirildi",
  ". Not site implementation or outcome evidence.": ". Site uygulaması veya sonuç kanıtı değildir.",
  "Exact human decision reason": "Tam insan karar gerekçesi",
  "I reviewed the unchanged exact text, source, judgment, assignee, proposal, replacement and user impact of revision": "Sürümün değişmemiş tam metnini, kaynağını, değerlendirmesini, atanan kişisini, önerisini, hedefini ve kullanıcı etkisini inceledim:",
  "Actual manual handoff date/time (browser-local timezone, after approval)": "Gerçek manuel devir tarihi/saati (tarayıcının yerel saat dilimi, onaydan sonra)",
  "Actual manual handoff note (no personal identities)": "Gerçek manuel devir notu (kişisel kimlik yok)",
  "Human dismissal reason": "İnsan reddetme gerekçesi",
  "Dismiss this exact human proposal; approval will be absent.": "Bu insan önerisinin tamamını reddedin; onay bulunmayacaktır.",
  "Dismiss proposal without site work": "Site çalışması yapmadan öneriyi reddedin",
  "Correct or reopen as a new unapproved draft": "Yeni onaylanmamış taslak olarak düzeltin veya yeniden açın",
  "Immutable source, judgment, assignee, approval and handoff history (newest 20)": "Değişmez kaynak, değerlendirme, atanan kişi, onay ve devir geçmişi (en yeni 20)",
  "Revision": "Sürüm",
  "Content": "İçerik",
  "· original human review": "· özgün insan incelemesi",
  "· replacement": "· hedef",
  "· fact date": "· bilgi tarihi",
  "Approval": "Onay",
  "Older history exists; this bounded view is incomplete.": "Daha eski geçmiş var; bu sınırlı görünüm eksiktir.",
  "No current content/private source and eligible assignee available. Inspect studio, original research and configuration first.": "Güncel içerik/özel kaynak ve uygun atanan kişi kullanılamıyor. Önce stüdyoyu, özgün araştırmayı ve yapılandırmayı inceleyin.",
  "Only bounded recent source/assignee candidates are shown; inventory is partial.": "Yalnızca sınırlı son kaynak/atanan kişi adayları gösterilir; envanter kısmidir.",
  "Actual native text, independent human evidence and reviewed proposal": "Gerçek düz metin, bağımsız insan kanıtı ve incelenmiş öneri",
  "Current saved content (corrections keep the same item)": "Güncel kayıtlı içerik (düzeltmeler aynı kaydı korur)",
  "Choose actual content": "Gerçek içerik seçin",
  "· item": "· kayıt",
  "Inspect exact current native text and source": "Güncel düz metnin ve kaynağın tamamını inceleyin",
  "Exact text SHA256": "Tam metin SHA256",
  "· configuration": "· yapılandırma",
  "· private brief": "· özel içerik özeti",
  "Intent/action source pages:": "Niyet/eylem kaynak sayfaları:",
  ". Existing action": ". Mevcut eylem",
  "revision": "sürüm",
  "is independent of this quality proposal.": "bu kalite önerisinden bağımsızdır.",
  "Historical manual publication": "Geçmiş manuel yayın",
  ". Not verified live content or publication age.": ". Doğrulanmış canlı içerik veya yayın yaşı değildir.",
  "Exact native title, body and meta description (inert text)": "Tam düz başlık, gövde ve meta açıklaması (çalıştırılmayan metin)",
  "Original dated private research provenance": "Özgün tarihli özel araştırma kökeni",
  "Source": "Kaynak",
  "· bytes": "· bayt",
  ". Facts unverified.": ". Bilgiler doğrulanmadı.",
  "Original human review timestamp (ISO 8601 with Z or UTC offset; after content date, not future)": "Özgün insan incelemesi zaman damgası (Z veya UTC farkı içeren ISO 8601; içerik tarihinden sonra, gelecekte değil)",
  "Human judgment (never a measured score)": "İnsan değerlendirmesi (hiçbir zaman ölçülmüş puan değildir)",
  "Substantive human basis": "Esaslı insan dayanağı",
  "Original service-fact check timestamp (ISO with UTC offset; required only with service-fact notes, no later than review)": "Özgün hizmet bilgisi kontrol zaman damgası (UTC farkı içeren ISO; yalnızca hizmet bilgisi notlarıyla zorunlu, incelemeden sonra değil)",
  "Human proposed lifecycle action": "İnsanın önerdiği yaşam döngüsü eylemi",
  "Distinct exact-project replacement URL (consolidate/redirect/retire only; no query/fragment)": "Aynı projede farklı hedef URL’si (yalnızca birleştirme/yönlendirme/kaldırma; sorgu/parça yok)",
  "Current eligible project reviewer/assignee": "Güncel uygun proje inceleyeni/atanan kişi",
  "Choose responsible assignee": "Sorumlu atanan kişi seçin",
  "Project user": "Proje kullanıcısı",
  "Human draft/correction reason": "İnsan taslak/düzeltme gerekçesi",
  "Save new unapproved human review revision": "Yeni onaylanmamış insan inceleme sürümünü kaydedin",
  "Cancel correction": "Düzeltmeyi iptal edin",
  "Read-only retained history. Current verified owner/admin authority is required for every human review command.": "Salt okunur saklanan geçmiş. Her insan inceleme komutu için güncel doğrulanmış sahip/yönetici yetkisi gereklidir.",
  "Compare separately authorized saved content": "Ayrı ayrı yetkilendirilmiş kayıtlı içeriği karşılaştırın",
  "First deliberately inspect the active project's exact native text above. Select another actual project you can currently review;": "Önce etkin projenin yukarıdaki düz metninin tamamını bilinçli olarak inceleyin. Şu anda inceleyebileceğiniz başka bir gerçek proje seçin;",
  "inspect your organization/project selectors": "kuruluş/proje seçicilerinizi inceleyin",
  "for its identifiers. Each project's sources and roles are checked independently. No draft is copied, edited, judged thin/overlapping or approved automatically.": "ve tanımlayıcılarını bulun. Her projenin kaynakları ve rolleri bağımsız olarak kontrol edilir. Hiçbir taslak otomatik olarak kopyalanmaz, düzenlenmez, yetersiz/örtüşen olarak değerlendirilmez veya onaylanmaz.",
  "Other independently authorized scope": "Diğer bağımsız yetkilendirilmiş kapsam",
  "Other organization identifier": "Diğer kuruluş tanımlayıcısı",
  "Other saved project identifier": "Diğer kayıtlı proje tanımlayıcısı",
  "Load other project's actual eligible content selections": "Diğer projenin gerçek uygun içerik seçimlerini yükleyin",
  "Other organization": "Diğer kuruluş",
  ". Only bounded latest eligible content is shown.": ". Yalnızca sınırlı en son uygun içerik gösterilir.",
  "No current saved native text/private source is eligible in that project.": "Bu projede uygun güncel kayıtlı düz metin/özel kaynak yok.",
  "Other project's exact current saved content": "Diğer projenin tam güncel kayıtlı içeriği",
  "Choose other exact content": "Diğer tam içeriği seçin",
  "Inspect this exact independently authorized text pair": "Bağımsız yetkilendirilmiş bu tam metin çiftini inceleyin",
  "Current exact saved-text comparison as of read.": "Okuma anındaki güncel tam kayıtlı metin karşılaştırması.",
  "This is not live-page duplication, thinness, plagiarism, complete topic coverage or service verification. Record any substantive human judgment separately in each project.": "Bu; canlı sayfa tekrarı, yetersizlik, intihal, tam konu kapsamı veya hizmet doğrulaması değildir. Esaslı insan değerlendirmelerini her projede ayrı kaydedin.",
  "· content": "· içerik",
  "Original native date": "Özgün düz metin tarihi",
  "· text SHA256": "· metin SHA256",
  "dated": "tarihli",
  "Intent/action pages": "Niyet/eylem sayfaları",
  "· separate action": "· ayrı eylem",
  "· original retrieval": "· özgün alınma zamanı",
  "Review this project's genuine human evidence and proposal separately": "Bu projenin gerçek insan kanıtını ve önerisini ayrı inceleyin",
  "Separate project site approval and dated outcomes": "Ayrı proje site onayı ve tarihli sonuçlar",
  "Current source at refresh": "Yenileme anında güncel kaynak",
  "Stale/unavailable source": "Eski/kullanılamayan kaynak",
  "Not checked; no quote selected": "Kontrol edilmedi; alıntı seçilmedi",
  "Evidence not recorded; unknown": "Kanıt kaydedilmedi; bilinmiyor",
  "Expertise not recorded; unknown": "Uzmanlık kaydedilmedi; bilinmiyor",
  "Service facts not checked; unknown": "Hizmet bilgileri kontrol edilmedi; bilinmiyor",
  "Not recorded": "Kaydedilmedi",
  "No rationale/proposal": "Gerekçe/öneri yok",
  "Not reviewed": "İncelenmedi",
  "Exact approval effective at refresh": "Tam onay yenileme anında geçerli",
  "No current effective approval": "Güncel geçerli onay yok",
  "Absent": "Yok",
  "Send exact proposal to human review": "Tam öneriyi insan incelemesine gönderin",
  "Approve exact reviewed proposal only": "Yalnızca incelenmiş tam öneriyi onaylayın",
  "Record actual manual handoff only": "Yalnızca gerçek manuel devri kaydedin",
  "Historical/stale source": "Geçmiş/eski kaynak",
  "Unknown": "Bilinmiyor",
  "Unapproved correction/reopen; prior approval never carries forward": "Onaylanmamış düzeltme/yeniden açma; önceki onay hiçbir zaman aktarılmaz",
  "Record a substantive human quality review": "Esaslı insan kalite incelemesi kaydedin",
  "Not reported": "Bildirilmedi",
  "Unknown date": "Bilinmeyen tarih",
  "Unavailable": "Kullanılamıyor",
  "Truncated excerpt": "Kesilmiş alıntı",
  "Selected bounded text only": "Yalnızca seçilen sınırlı metin",
  "The two selected native bodies are exactly equal.": "Seçilen iki düz metin gövdesi tamamen eşittir.",
  "The two selected native bodies differ.": "Seçilen iki düz metin gövdesi farklıdır.",
  "Selected bounded evidence": "Seçilen sınırlı kanıt",
  "Exact quote from inspected native title, body or meta description (empty for not checked)": "İncelenen düz başlık, gövde veya meta açıklamasından tam alıntı (kontrol edilmediyse boş)",
  "Substantive human evidence and usefulness/coverage limitations (not traffic or word count alone)": "Esaslı insan kanıtı ve yararlılık/kapsam sınırlamaları (yalnızca trafik veya kelime sayısı değil)",
  "Original independently supplied first-hand business expertise (missing is unknown)": "Bağımsız sağlanan özgün birinci el işletme uzmanlığı (eksikse bilinmiyor)",
  "Independently checked genuine service facts and evidence limitations (human declaration)": "Bağımsız kontrol edilen gerçek hizmet bilgileri ve kanıt sınırlamaları (insan beyanı)",
  "Human lifecycle rationale (required for a proposal)": "İnsan yaşam döngüsü gerekçesi (öneri için zorunlu)",
  "Distinct replacement usefulness/coverage review before consolidation, redirect or retirement": "Birleştirme, yönlendirme veya kaldırmadan önce farklı hedefin yararlılık/kapsam incelemesi",
  "Reviewed reader/user impact and preservation of useful history (required for a proposal)": "İncelenmiş okuyucu/kullanıcı etkisi ve yararlı geçmişin korunması (öneri için zorunlu)",
  "I independently have permission to use this human evidence.": "Bu insan kanıtını kullanmak için bağımsız iznim var.",
  "I independently have permission to store this evidence under the stated private export/deletion/backup policy.": "Bu kanıtı belirtilen özel dışa aktarma/silme/yedekleme politikası kapsamında saklamak için bağımsız iznim var.",
  "This is independent human evidence, not a restricted provider/API-content copy.": "Bu bağımsız insan kanıtıdır; kısıtlı sağlayıcı/API içeriği kopyası değildir.",
  "This contains no personal identities, private contact details or secrets.": "Bu içerik kişisel kimlik, özel iletişim bilgisi veya sır içermez.",
  "Select an authorized organization and project.": "Yetkili bir kuruluş ve proje seçin.",
  "Current content sources, history or project authority unavailable.": "Güncel içerik kaynakları, geçmiş veya proje yetkisi kullanılamıyor.",
  "Exact current native text/source digest or authority changed. Refresh before reviewing.": "Güncel düz metnin/kaynağın tam özeti veya yetkisi değişti. İncelemeden önce yenileyin.",
  "Exact human history unavailable; refresh before another decision.": "Tam insan geçmişi kullanılamıyor; başka karar vermeden önce yenileyin.",
  "Other exact project/source authority unavailable. Refresh both scopes before comparison.": "Diğer tam proje/kaynak yetkisi kullanılamıyor. Karşılaştırmadan önce iki kapsamı da yenileyin.",
  "Exact pair text/source/role/latest authority changed or read failed. No comparison, copy or command retained.": "Tam çift metni/kaynağı/rolü/son yetkisi değişti veya okuma başarısız oldu. Karşılaştırma, kopya veya komut saklanmadı.",
  "Keep bounded human notes within 16 KiB, original aware review/fact dates, an exact stored quote and substantive evidence. Review rationale, distinct replacement and user impact; unchecked is not a proposal.": "İnsan notlarını 16 KiB içinde tutun; özgün saat dilimli inceleme/bilgi tarihleri, tam kayıtlı alıntı ve esaslı kanıt kullanın. Gerekçeyi, farklı hedefi ve kullanıcı etkisini inceleyin; kontrol edilmemiş içerik öneri değildir.",
  "Record an actual manual handoff after approval, no later than now.": "Onaydan sonra gerçekleşmiş, şu andan sonra olmayan manuel devri kaydedin.",
  "Keep human notes within their character limits, review notes within 16 KiB and combined source evidence within 32 KiB. Supply a nonblank reason and actual handoff note; invalid text cannot be saved.": "İnsan notlarını karakter sınırları, inceleme notlarını 16 KiB ve birleşik kaynak kanıtını 32 KiB içinde tutun. Boş olmayan gerekçe ve gerçek devir notu sağlayın; geçersiz metin kaydedilemez.",
  "Current exact content/source/assignee/role or latest review changed. No command sent.": "Güncel tam içerik/kaynak/atanan kişi/rol veya son inceleme değişti. Komut gönderilmedi.",
  "Human quality decision recorded. No website changed.": "İnsan kalite kararı kaydedildi. Hiçbir web sitesi değişmedi.",
  "Exact human decision denied. Refresh current sources and history.": "Tam insan kararı reddedildi. Güncel kaynakları ve geçmişi yenileyin.",
  "Save outcome uncertain. Check the exact request key; no automatic replay.": "Kayıt sonucu belirsiz. Tam istek anahtarını kontrol edin; otomatik yeniden yürütme yoktur.",
  "Exact immutable request reconciled; no command replayed.": "Tam değişmez istek uzlaştırıldı; komut yeniden yürütülmedi.",
  "No recorded decision. Exact source/text/assignee/latest/role match; deliberate same-command retry is available.": "Kaydedilmiş karar yok. Tam kaynak/metin/atanan kişi/son sürüm/rol eşleşiyor; aynı komut bilinçli olarak tekrar denenebilir.",
  "Outcome or current exact authority unavailable. No command replayed.": "Sonuç veya güncel tam yetki kullanılamıyor. Komut yeniden yürütülmedi."
};

@Component({
  selector: 'app-content-lifecycle', imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="quality-title">
      <h1 id="quality-title">{{ t("Existing-content human quality and lifecycle review") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish content-lifecycle interface draft in local development. Human judgments and source texts retain their original language; bilingual approval is pending.") }}</p> }
      <p>{{ t("Organization") }} <span lang="en">{{ organizationId }}</span> {{ t("· project") }} <span lang="en">{{ projectId }}</span> ·
        <a [routerLink]="['/app/content', organizationId, projectId]">{{ t("Content studio") }}</a> ·
        <a [routerLink]="['/app/dashboard', organizationId, projectId]">{{ t("Project evidence") }}</a> ·
        <a [routerLink]="['/app/actions', organizationId, projectId]">{{ t("Separate site action approval, implementation and dated outcomes") }}</a></p>
      <p>{{ t("Saved native text and dated research are not verified live-page quality, publication age, business expertise or service facts. Local business assessments are user-attested. Conversion context is unavailable. Missing facts, age, low traffic or word count alone never justify deletion.") }}</p>
      <p>{{ t("Supply independent first-hand business evidence, no personal identities, secrets or restricted provider copies. Private records follow 90-day retained access after lapse, active deletion within 30 days of closure/expiry and up to 35-day backup rotation after deletion. Approval covers only this exact human judgment and proposal. Manual handoff, live site work and subsequent outcomes are separate. Archiving a record does not remove a live page.") }}</p>
      @if (loading()) { <p role="status">{{ t("Loading current content sources and private human history.") }}</p> }
      @if (error()) { <p role="alert" [attr.lang]="t(error()) === error() ? 'en' : uiLanguage()">{{ t(error()) }}</p> }
      @if (message()) { <p role="status" [attr.lang]="t(message()) === message() ? 'en' : uiLanguage()">{{ t(message()) }}</p> }
      @if (pending()) {
        <p>{{ t("Exact save outcome is uncertain. Source, native text and command are frozen in component memory only; no automatic replay.") }}</p>
        <button type="button" (click)="reconcile()" [disabled]="busy()">{{ t("Check exact uncertain save") }}</button>
        @if (notFound()) { <button type="button" (click)="retry()" [disabled]="busy()">{{ t("Deliberately retry same exact command") }}</button> }
      }
      @if (!context() && !pending() && !loading()) { <button type="button" (click)="load()" [disabled]="busy()">{{ t("Reload current project") }}</button> }
      @if (context(); as info) {
        <button type="button" (click)="load()" [disabled]="busy() || !!pending()">{{ t("Refresh current sources and history") }}</button>
        <p>{{ t("Current flags are as of refresh; every command rechecks current source, exact text, original actors, assignee and latest review.") }}</p>
        @if (!info.reviews.length) { <p>{{ t("No human quality review recorded for this project.") }}</p> }
        @if (info.has_more) { <p>{{ t("Only the latest 50 reviews are shown; inventory is incomplete.") }}</p> }
        <ul [attr.aria-label]="t('Latest human content-quality reviews')">
          @for (row of info.reviews; track row.review_id) {
            <li><span lang="">{{ row.source_evidence.content.title }}</span> {{ t("· human") }} <span lang="en">{{ row.intake.judgment }}</span> · <span lang="en">{{ row.intake.proposed_action }}</span> {{ t("· revision") }} <span lang="en">{{ row.revision }}</span> · <span lang="en">{{ row.state }}</span> {{ t("· assignee") }} <span lang="en">{{ row.assignee_id }}</span> ·
              {{ row.source_current ? t("Current source at refresh") : t("Stale/unavailable source") }}
              <button type="button" (click)="inspect(row.review_id)" [disabled]="busy() || !!pending()">{{ t("Inspect exact judgment and history") }}</button></li>
          }
        </ul>
        @if (selected(); as row) {
          <section aria-labelledby="quality-selected-title">
            <h2 id="quality-selected-title">{{ t("Exact quality revision") }} <span lang="en">{{ row.revision }}</span> · <span lang="en">{{ row.state }}</span></h2>
            <p>{{ t("Content item") }} <span lang="en">{{ row.source_evidence.content.item_id }}</span> {{ t("· exact text revision") }} <span lang="en">{{ row.content_revision_id }}</span> {{ t("· digest") }} <span lang="en">{{ row.intake.text_sha256 }}</span>.</p>
            <p>{{ t("Responsible assignee") }} <span lang="en">{{ row.assignee_id }}</span> {{ t("· human source actor") }} <span lang="en">{{ row.source_actor_id }}</span> {{ t("· decision actor") }} <span lang="en">{{ row.actor_id }}</span> {{ t("· reviewed") }} <span lang="en">{{ row.intake.reviewed_at }}</span>.</p>
            <h3>{{ t("Exact stored native-text quote") }}</h3><pre><span [attr.lang]="row.intake.quote ? '' : uiLanguage()">{{ row.intake.quote || t("Not checked; no quote selected") }}</span></pre>
            <h3>{{ t("Substantive human judgment") }}</h3><p><span lang="en">{{ row.intake.judgment }}</span> · <span lang="en">{{ row.intake.substantive_basis }}</span></p>
            <pre><span [attr.lang]="row.intake.evidence_note ? '' : uiLanguage()">{{ row.intake.evidence_note || t("Evidence not recorded; unknown") }}</span></pre>
            <h3>{{ t("First-hand expertise and service facts (human declarations, not independent verification)") }}</h3>
            <pre><span [attr.lang]="row.intake.expertise_note ? '' : uiLanguage()">{{ row.intake.expertise_note || t("Expertise not recorded; unknown") }}</span></pre>
            <pre><span [attr.lang]="row.intake.service_fact_note ? '' : uiLanguage()">{{ row.intake.service_fact_note || t("Service facts not checked; unknown") }}</span></pre>
            <p>{{ t("Original fact-check date") }} <span [attr.lang]="row.intake.facts_checked_at ? 'en' : uiLanguage()">{{ row.intake.facts_checked_at || t("Not recorded") }}</span>.</p>
            <h3>{{ t("Human lifecycle proposal and user-impact review") }}</h3><p><span lang="en">{{ row.intake.proposed_action }}</span></p>
            <pre><span [attr.lang]="row.intake.rationale ? '' : uiLanguage()">{{ row.intake.rationale || t("No rationale/proposal") }}</span></pre><pre><span [attr.lang]="row.intake.user_impact ? '' : uiLanguage()">{{ row.intake.user_impact || t("Not reviewed") }}</span></pre>
            @if (row.intake.destination_url) {
              <p>{{ t("Distinct reviewed replacement:") }} <a [href]="pageUrl(row.intake.destination_url)" target="_blank" rel="noopener noreferrer"><span lang="">{{ row.intake.destination_url }}</span></a></p>
              <pre lang="">{{ row.intake.destination_review }}</pre>
            }
            <p><span lang="">{{ row.reason }}</span> · {{ row.effective_approval ? t("Exact approval effective at refresh") : t("No current effective approval") }} {{ t("· approval") }} <span [attr.lang]="row.approved_at ? 'en' : uiLanguage()">{{ row.approved_at || t("Absent") }}</span>.</p>
            @if (!row.source_current) { <p>{{ t("Source/text/reviewer/assignee stale or unavailable. Retained judgment is historical; new approval or handoff is denied.") }}</p> }
            @if (row.executed_at) { <p>{{ t("Actual manual handoff reported") }} <span lang="en">{{ row.executed_at }}</span>: <span lang="">{{ row.execution_note }}</span>{{ t(". Not site implementation or outcome evidence.") }}</p> }
            @if (info.can_review && row.source_current && row.is_latest && !pending()) {
              @if (['draft', 'review', 'approved'].includes(row.state)) {
                <form (submit)="decide($event, row.state === 'draft' ? 'review' : row.state === 'review' ? 'approved' : 'reported')">
                  <label for="quality-decision-reason">{{ t("Exact human decision reason") }}</label><textarea lang="" id="quality-decision-reason" name="reason" maxlength="1000" required></textarea>
                  <label><input name="exact" type="checkbox" required />{{ t("I reviewed the unchanged exact text, source, judgment, assignee, proposal, replacement and user impact of revision") }} <span lang="en">{{ row.revision }}</span>.</label>
                  @if (row.state === 'approved') {
                    <label for="quality-handoff-date">{{ t("Actual manual handoff date/time (browser-local timezone, after approval)") }}</label><input lang="en" id="quality-handoff-date" name="executed_at" type="datetime-local" required />
                    <label for="quality-handoff-note">{{ t("Actual manual handoff note (no personal identities)") }}</label><textarea lang="" id="quality-handoff-note" name="execution_note" maxlength="1000" required></textarea>
                  }
                  <button type="submit" [disabled]="busy() || row.intake.proposed_action === 'unselected'">{{ row.state === 'draft' ? t("Send exact proposal to human review") : row.state === 'review' ? t("Approve exact reviewed proposal only") : t("Record actual manual handoff only") }}</button>
                </form>
                <form (submit)="decide($event, 'dismissed')">
                  <label for="quality-dismiss-reason">{{ t("Human dismissal reason") }}</label><textarea lang="" id="quality-dismiss-reason" name="reason" maxlength="1000" required></textarea>
                  <label><input name="exact" type="checkbox" required />{{ t("Dismiss this exact human proposal; approval will be absent.") }}</label>
                  <button type="submit" [disabled]="busy()">{{ t("Dismiss proposal without site work") }}</button>
                </form>
              }
            }
            @if (info.can_review && row.is_latest && !pending()) { <button type="button" (click)="edit(row)" [disabled]="busy()">{{ t("Correct or reopen as a new unapproved draft") }}</button> }
          </section>
        }
        @if (history().length) {
          <details><summary>{{ t("Immutable source, judgment, assignee, approval and handoff history (newest 20)") }}</summary>
            <ol>@for (row of history(); track row.id) {
              <li>{{ t("Revision") }} <span lang="en">{{ row.revision }}</span> · <span lang="en">{{ row.created_at }}</span> · <span lang="en">{{ row.state }}</span> {{ t("· assignee") }} <span lang="en">{{ row.assignee_id }}</span> · <span lang="">{{ row.reason }}</span>.
                <p>{{ t("Content") }} <span lang="en">{{ row.content_revision_id }}</span> {{ t("· original human review") }} <span lang="en">{{ row.intake.reviewed_at }}</span> · {{ row.source_current ? t("Current source at refresh") : t("Historical/stale source") }}.</p>
                <pre lang="">{{ row.intake.quote }}</pre><pre lang="">{{ row.intake.evidence_note }}</pre><pre lang="">{{ row.intake.expertise_note }}</pre><pre lang="">{{ row.intake.service_fact_note }}</pre>
                <p><span lang="en">{{ row.intake.proposed_action }}</span> {{ t("· replacement") }} <span [attr.lang]="row.intake.destination_url ? '' : uiLanguage()">{{ row.intake.destination_url || t("Absent") }}</span> {{ t("· fact date") }} <span [attr.lang]="row.intake.facts_checked_at ? 'en' : uiLanguage()">{{ row.intake.facts_checked_at || t("Unknown") }}</span>.</p>
                <pre lang="">{{ row.intake.rationale }}</pre><pre lang="">{{ row.intake.destination_review }}</pre><pre lang="">{{ row.intake.user_impact }}</pre>
                <p>{{ t("Approval") }} <span [attr.lang]="row.approved_at ? 'en' : uiLanguage()">{{ row.approved_at || t("Absent") }}</span> · <span lang="en">{{ row.execution_state }}</span> · <span [attr.lang]="row.executed_at ? 'en' : uiLanguage()">{{ row.executed_at || t("Absent") }}</span> · <span lang="">{{ row.execution_note }}</span>.</p>
              </li>
            }</ol>
            @if (historyMore()) { <p>{{ t("Older history exists; this bounded view is incomplete.") }}</p> }
          </details>
        }
        @if (info.can_review && !pending()) {
          <h2>{{ editing() ? t("Unapproved correction/reopen; prior approval never carries forward") : t("Record a substantive human quality review") }}</h2>
          @if (!info.sources.length || !info.assignees.length) { <p>{{ t("No current content/private source and eligible assignee available. Inspect studio, original research and configuration first.") }}</p> }
          @else {
            @if (info.sources_has_more) { <p>{{ t("Only bounded recent source/assignee candidates are shown; inventory is partial.") }}</p> }
            <form (submit)="saveDraft($event)">
              <fieldset [disabled]="busy()">
                <legend>{{ t("Actual native text, independent human evidence and reviewed proposal") }}</legend>
                <label for="quality-source">{{ t("Current saved content (corrections keep the same item)") }}</label>
                <select lang="" id="quality-source" name="source" required (change)="choose(+$any($event.target).value)">
                  <option value="" [selected]="!sourceSelection()" [attr.lang]="uiLanguage()">{{ t("Choose actual content") }}</option>
                  @for (source of info.sources; track source.content.revision_id) {
                    @if (!editing() || editing()!.source_evidence.content.item_id === source.content.item_id) {
                      <option [value]="source.content.revision_id" [selected]="sourceSelection() === source.content.revision_id">{{ source.content.title }} {{ t("· item") }} {{ source.content.item_id }} {{ t("· revision") }} {{ source.content.revision }} · {{ source.content.created_at }}</option>
                    }
                  }
                </select>
                <button type="button" (click)="inspectText()" [disabled]="!chosenSource()">{{ t("Inspect exact current native text and source") }}</button>
                @if (inspectedSource(); as source) {
                  <p>{{ t("Exact text SHA256") }} <span lang="en">{{ source.content.text_sha256 }}</span> {{ t("· configuration") }} <span lang="en">{{ source.configuration_revision }}</span> {{ t("· private brief") }} <span lang="en">{{ source.brief.id }}</span> · <span lang="en">{{ source.brief.created_at }}</span>.</p>
                  <p>{{ t("Intent/action source pages:") }} <span lang="">{{ source.action.affected_urls.join(' · ') }}</span>{{ t(". Existing action") }} <span lang="en">{{ source.action.action_id }}</span> {{ t("revision") }} <span lang="en">{{ source.action.revision }}</span> {{ t("is independent of this quality proposal.") }}</p>
                  <p>{{ t("Historical manual publication") }} <span [attr.lang]="source.content.publication_url ? '' : uiLanguage()">{{ source.content.publication_url || t("Not reported") }}</span> · <span [attr.lang]="source.content.published_at ? 'en' : uiLanguage()">{{ source.content.published_at || t("Unknown date") }}</span>{{ t(". Not verified live content or publication age.") }}</p>
                  <h3>{{ t("Exact native title, body and meta description (inert text)") }}</h3>
                  <pre lang="">{{ text()!.title }}</pre><pre lang="">{{ text()!.body }}</pre><pre lang="">{{ text()!.meta_description }}</pre>
                  <h3>{{ t("Original dated private research provenance") }}</h3>
                  <ul>@for (original of source.sources; track original.source_index) {
                    <li>{{ t("Source") }} <span lang="en">{{ original.source_index }}</span> · <span lang="en">{{ original.method || original.state }}</span> · <span [attr.lang]="original.retrieved_at ? 'en' : uiLanguage()">{{ original.retrieved_at || t("Unavailable") }}</span> · <span [attr.lang]="original['coverage'] ? 'en' : uiLanguage()">{{ original['coverage'] || t("Unavailable") }}</span>.
                      @if (original.method) {
                        <p><a [href]="safeUrl(original['url'])" target="_blank" rel="noopener noreferrer"><span lang="">{{ original['title'] }}</span></a> {{ t("· digest") }} <span lang="en">{{ original['original_response_sha256'] }}</span> {{ t("· bytes") }} <span lang="en">{{ original['source_size_bytes'] }}</span> · {{ original['excerpt_truncated'] ? t("Truncated excerpt") : t("Selected bounded text only") }}{{ t(". Facts unverified.") }}</p>
                      }
                    </li>
                  }</ul>
                }
                <label for="quality-reviewed-date">{{ t("Original human review timestamp (ISO 8601 with Z or UTC offset; after content date, not future)") }}</label>
                <input lang="en" id="quality-reviewed-date" name="reviewed_at" type="text" maxlength="64" required placeholder="2026-10-02T12:00:00Z" [value]="editing()?.intake?.reviewed_at || ''" />
                <label for="quality-judgment">{{ t("Human judgment (never a measured score)") }}</label><select lang="en" id="quality-judgment" name="judgment">
                  @for (value of judgments; track value) { <option [value]="value" [selected]="value === (editing()?.intake?.judgment || 'not_checked')">{{ value }}</option> }
                </select>
                <label for="quality-basis">{{ t("Substantive human basis") }}</label><select lang="en" id="quality-basis" name="substantive_basis">
                  @for (value of bases; track value) { <option [value]="value" [selected]="value === (editing()?.intake?.substantive_basis || 'unreviewed')">{{ value }}</option> }
                </select>
                @for (field of noteFields; track field.key) {
                  <label [for]="'quality-' + field.key">{{ t(field.label) }}</label>
                  <textarea lang="" [id]="'quality-' + field.key" [name]="field.key" [attr.maxlength]="field.limit * 2" [value]="editing()?.intake?.[field.key] || ''"></textarea>
                }
                <label for="quality-fact-date">{{ t("Original service-fact check timestamp (ISO with UTC offset; required only with service-fact notes, no later than review)") }}</label>
                <input lang="en" id="quality-fact-date" name="facts_checked_at" type="text" maxlength="64" [value]="editing()?.intake?.facts_checked_at || ''" />
                <label for="quality-action">{{ t("Human proposed lifecycle action") }}</label><select lang="en" id="quality-action" name="proposed_action">
                  @for (value of actions; track value) { <option [value]="value" [selected]="value === (editing()?.intake?.proposed_action || 'unselected')">{{ value }}</option> }
                </select>
                <label for="quality-destination">{{ t("Distinct exact-project replacement URL (consolidate/redirect/retire only; no query/fragment)") }}</label>
                <input lang="en" id="quality-destination" name="destination_url" type="url" maxlength="512" [value]="editing()?.intake?.destination_url || ''" />
                <label for="quality-assignee">{{ t("Current eligible project reviewer/assignee") }}</label><select id="quality-assignee" name="assignee_id" required>
                  <option value="" [selected]="!editing()">{{ t("Choose responsible assignee") }}</option>
                  @for (user of info.assignees; track user.id) { <option [value]="user.id" [selected]="user.id === editing()?.assignee_id">{{ t("Project user") }} {{ user.id }}</option> }
                </select>
                <label for="quality-reason">{{ t("Human draft/correction reason") }}</label><textarea lang="" id="quality-reason" name="reason" maxlength="1000" required></textarea>
                @for (right of rights; track right.key) { <label><input [name]="right.key" type="checkbox" required />{{ t(right.label) }}</label> }
                <button type="submit" [disabled]="!text() || !inspectedSource()">{{ t("Save new unapproved human review revision") }}</button>
                @if (editing()) { <button type="button" (click)="editing.set(null); choose(0)">{{ t("Cancel correction") }}</button> }
              </fieldset>
            </form>
          }
        } @else if (!info.can_review) { <p>{{ t("Read-only retained history. Current verified owner/admin authority is required for every human review command.") }}</p> }
        @if (info.can_review && !pending()) {
          <section aria-labelledby="quality-comparison-title">
            <h2 id="quality-comparison-title">{{ t("Compare separately authorized saved content") }}</h2>
            <p>{{ t("First deliberately inspect the active project's exact native text above. Select another actual project you can currently review;") }}
              <a routerLink="/app">{{ t("inspect your organization/project selectors") }}</a> {{ t("for its identifiers. Each project's sources and roles are checked independently. No draft is copied, edited, judged thin/overlapping or approved automatically.") }}</p>
            <form (submit)="loadOther($event)">
              <fieldset [disabled]="busy()"><legend>{{ t("Other independently authorized scope") }}</legend>
                <label for="quality-other-org">{{ t("Other organization identifier") }}</label><input lang="en" id="quality-other-org" name="other_organization_id" type="number" min="1" step="1" required [value]="organizationId" />
                <label for="quality-other-project">{{ t("Other saved project identifier") }}</label><input lang="en" id="quality-other-project" name="other_project_id" type="number" min="1" step="1" required />
                <button type="submit">{{ t("Load other project's actual eligible content selections") }}</button>
              </fieldset>
            </form>
            @if (other(); as scope) {
              <p>{{ t("Other organization") }} <span lang="en">{{ scope.organizationId }}</span> {{ t("· project") }} <span lang="en">{{ scope.projectId }}</span>{{ t(". Only bounded latest eligible content is shown.") }}</p>
              @if (!scope.info.sources.length) { <p>{{ t("No current saved native text/private source is eligible in that project.") }}</p> }
              @else {
                <label for="quality-other-content">{{ t("Other project's exact current saved content") }}</label>
                <select lang="" id="quality-other-content" [disabled]="busy()" (change)="chooseOther(+$any($event.target).value)">
                  <option value="" [selected]="!otherSelection()" [attr.lang]="uiLanguage()">{{ t("Choose other exact content") }}</option>
                  @for (source of scope.info.sources; track source.content.revision_id) {
                    <option [value]="source.content.revision_id" [selected]="otherSelection() === source.content.revision_id">{{ source.content.title }} {{ t("· item") }} {{ source.content.item_id }} {{ t("· revision") }} {{ source.content.revision }} · {{ source.content.created_at }}</option>
                  }
                </select>
                <button type="button" (click)="compare()" [disabled]="busy() || !inspectedSource() || !text() || !otherSelection()">{{ t("Inspect this exact independently authorized text pair") }}</button>
              }
            }
            @if (comparison(); as pair) {
              <p>{{ t("Current exact saved-text comparison as of read.") }} {{ pair.same_native_body ? t("The two selected native bodies are exactly equal.") : t("The two selected native bodies differ.") }}
                {{ t("This is not live-page duplication, thinness, plagiarism, complete topic coverage or service verification. Record any substantive human judgment separately in each project.") }}</p>
              @for (side of [pair.left, pair.right]; track side.source.content.revision_id) {
                <section><h3>{{ t("Organization") }} <span lang="en">{{ side.organization_id }}</span> {{ t("· project") }} <span lang="en">{{ side.project_id }}</span> {{ t("· content") }} <span lang="en">{{ side.source.content.item_id }}</span> {{ t("revision") }} <span lang="en">{{ side.source.content.revision }}</span></h3>
                  <p>{{ t("Original native date") }} <span lang="en">{{ side.source.content.created_at }}</span> {{ t("· text SHA256") }} <span lang="en">{{ side.source.content.text_sha256 }}</span> {{ t("· private brief") }} <span lang="en">{{ side.source.brief.id }}</span> {{ t("dated") }} <span lang="en">{{ side.source.brief.created_at }}</span> {{ t("· configuration") }} <span lang="en">{{ side.source.configuration_revision }}</span>.</p>
                  <p>{{ t("Intent/action pages") }} <span lang="">{{ side.source.action.affected_urls.join(' · ') }}</span> {{ t("· separate action") }} <span lang="en">{{ side.source.action.action_id }}</span> {{ t("revision") }} <span lang="en">{{ side.source.action.revision }}</span>.</p>
                  <pre lang="">{{ side.text.title }}</pre><pre lang="">{{ side.text.body }}</pre><pre lang="">{{ side.text.meta_description }}</pre>
                  <ul>@for (original of side.source.sources; track original.source_index) {
                    <li>{{ t("Source") }} <span lang="en">{{ original.source_index }}</span> · <span lang="en">{{ original.method || original.state }}</span> {{ t("· original retrieval") }} <span [attr.lang]="original.retrieved_at ? 'en' : uiLanguage()">{{ original.retrieved_at || t("Unavailable") }}</span> · <span [attr.lang]="original['coverage'] ? 'en' : uiLanguage()">{{ original['coverage'] || t("Unavailable") }}</span> {{ t("· digest") }} <span [attr.lang]="original['original_response_sha256'] ? 'en' : uiLanguage()">{{ original['original_response_sha256'] || t("Unavailable") }}</span> · {{ original['excerpt_truncated'] ? t("Truncated excerpt") : t("Selected bounded evidence") }}{{ t(". Facts unverified.") }}</li>
                  }</ul>
                  <p><a [routerLink]="['/app/content-lifecycle', side.organization_id, side.project_id]">{{ t("Review this project's genuine human evidence and proposal separately") }}</a> ·
                    <a [routerLink]="['/app/actions', side.organization_id, side.project_id]">{{ t("Separate project site approval and dated outcomes") }}</a></p>
                </section>
              }
            }
          </section>
        }
      }
    </section>
  `,
  styles: `form, fieldset { display: grid; gap: .6rem; } form { max-width: 48rem; margin-block: 1rem; }
    pre { white-space: pre-wrap; overflow-wrap: anywhere; } li { margin-block: 1rem; } input, textarea, select { min-width: 0; max-width: 100%; }`,
})
export class ContentLifecycle implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  t(text: string) { return this.uiLanguage() === 'tr' ? contentLifecycleTurkish[text] ?? text : text; }
  readonly context = signal<Context | null>(null); readonly selected = signal<Review | null>(null);
  readonly editing = signal<Review | null>(null); readonly history = signal<Review[]>([]); readonly historyMore = signal(false);
  readonly sourceSelection = signal(0); readonly text = signal<Text | null>(null); readonly inspectedSource = signal<Source | null>(null);
  readonly loading = signal(false); readonly busy = signal(false); readonly error = signal(''); readonly message = signal('');
  readonly pending = signal<Pending | null>(null); readonly notFound = signal(false);
  readonly other = signal<{ organizationId: number; projectId: number; info: Context } | null>(null);
  readonly otherSelection = signal(0); readonly comparison = signal<Pair | null>(null);
  organizationId = 0; projectId = 0; protected readonly safeUrl = safeUrl;
  protected readonly pageUrl = pageUrl;
  protected readonly judgments = ['not_checked', 'no_issue_found_in_reviewed_text', 'outdated_claim', 'thin_coverage', 'overlap', 'service_detail_changed'];
  protected readonly bases = ['unreviewed', 'content_claim_check', 'business_expertise_review', 'coverage_review'];
  protected readonly actions = ['unselected', 'keep', 'refresh', 'consolidate', 'redirect', 'retire'];
  protected readonly noteFields = [
    { key: 'quote', label: 'Exact quote from inspected native title, body or meta description (empty for not checked)', limit: 1000 },
    { key: 'evidence_note', label: 'Substantive human evidence and usefulness/coverage limitations (not traffic or word count alone)', limit: 1000 },
    { key: 'expertise_note', label: 'Original independently supplied first-hand business expertise (missing is unknown)', limit: 1000 },
    { key: 'service_fact_note', label: 'Independently checked genuine service facts and evidence limitations (human declaration)', limit: 1000 },
    { key: 'rationale', label: 'Human lifecycle rationale (required for a proposal)', limit: 500 },
    { key: 'destination_review', label: 'Distinct replacement usefulness/coverage review before consolidation, redirect or retirement', limit: 500 },
    { key: 'user_impact', label: 'Reviewed reader/user impact and preservation of useful history (required for a proposal)', limit: 500 },
  ];
  protected readonly rights = [
    { key: 'use_permission', label: 'I independently have permission to use this human evidence.' },
    { key: 'storage_permission', label: 'I independently have permission to store this evidence under the stated private export/deletion/backup policy.' },
    { key: 'not_restricted_copy', label: 'This is independent human evidence, not a restricted provider/API-content copy.' },
    { key: 'no_personal_payload', label: 'This contains no personal identities, private contact details or secrets.' },
  ];
  private generation = 0; private selectionGeneration = 0;
  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi, private readonly destroy: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t('Private human content-quality review')} — OrganicSEOOps`));
    destroy.onDestroy(() => { this.generation++; this.clear(); });
  }
  ngOnInit() {
    void this.loadProductLanguage();
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroy)).subscribe((params) => {
      this.generation++; this.clear(); this.busy.set(false); this.loading.set(false); this.error.set(''); this.message.set('');
      this.organizationId = Number(params.get('organizationId')); this.projectId = Number(params.get('projectId'));
      if (positive(this.organizationId) && positive(this.projectId)) void this.load();
      else this.error.set('Select an authorized organization and project.');
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
  private clearEvidence() {
    this.context.set(null); this.selected.set(null); this.editing.set(null); this.history.set([]);
    this.text.set(null); this.inspectedSource.set(null); this.sourceSelection.set(0); this.selectionGeneration++;
    this.other.set(null); this.otherSelection.set(0); this.comparison.set(null);
  }
  private clear() { this.clearEvidence(); this.pending.set(null); this.notFound.set(false); }
  chosenSource() { return this.context()?.sources.find((row) => row.content.revision_id === this.sourceSelection()); }
  choose(id: number) { if (!this.busy() && !this.pending()) { this.sourceSelection.set(id); this.text.set(null); this.inspectedSource.set(null); this.comparison.set(null); this.selectionGeneration++; } }
  private readContext(response: ApiResult, organization = this.organizationId, project = this.projectId): Context {
    const info = response.body as unknown as Context;
    if (response.status !== 200 || info.organization_id !== organization || info.project_id !== project
      || info.policy !== POLICY || typeof info.can_review !== 'boolean' || typeof info.sources_has_more !== 'boolean'
      || !Array.isArray(info.sources) || info.sources.length > 20 || !info.sources.every((row) => isSource(row, project))
      || !Array.isArray(info.assignees) || info.assignees.length > 20 || !info.assignees.every((row) => row && positive(row.id))
      || !Array.isArray(info.reviews) || info.reviews.length > 50 || !info.reviews.every((row) => isReview(row, project))
      || typeof info.has_more !== 'boolean'
      || info.source_basis !== 'actual_saved_native_text_and_dated_sources_not_verified_live_page_or_service_facts'
      || info.site_action !== 'separate_existing_page_action_approval_implementation_and_outcome_required') throw new Error();
    return structuredClone(info);
  }
  async load() {
    if (this.busy() || this.pending()) return;
    const generation = ++this.generation; this.clear(); this.loading.set(true); this.error.set('');
    try {
      const result = await this.api.contentLifecycle(this.organizationId, this.projectId);
      if (generation === this.generation) this.context.set(this.readContext(result));
    } catch { if (generation === this.generation) this.error.set('Current content sources, history or project authority unavailable.'); }
    finally { if (generation === this.generation) this.loading.set(false); }
  }
  async inspectText() {
    const chosen = this.chosenSource(); if (!chosen || this.busy() || this.pending() || !this.context()?.can_review) return;
    const source = structuredClone(chosen), generation = this.generation, selection = ++this.selectionGeneration;
    this.text.set(null); this.inspectedSource.set(null); this.comparison.set(null); this.busy.set(true); this.error.set('');
    try {
      const response = await this.api.projectContent(this.organizationId, this.projectId, source.content.item_id);
      if (generation !== this.generation || selection !== this.selectionGeneration) return;
      if (response.status !== 200 || response.body['project_id'] !== this.projectId
        || response.body['source_state'] !== 'current_review_still_required'
        || !await textMatches(response.body['current'], source, this.projectId)) throw new Error();
      if (generation !== this.generation || selection !== this.selectionGeneration) return;
      const current = this.readContext(await this.api.contentLifecycle(this.organizationId, this.projectId));
      if (generation !== this.generation || selection !== this.selectionGeneration) return;
      if (!current.can_review || !current.sources.some((row) => same(row, source))) throw new Error();
      this.context.set(current); this.text.set(structuredClone(response.body['current'] as Text)); this.inspectedSource.set(source);
    } catch { if (generation === this.generation && selection === this.selectionGeneration) {
      this.clearEvidence(); this.error.set('Exact current native text/source digest or authority changed. Refresh before reviewing.');
    } }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  async inspect(id: string) {
    if (this.busy() || this.pending()) return;
    const generation = this.generation, selection = ++this.selectionGeneration;
    this.selected.set(null); this.history.set([]); this.editing.set(null); this.text.set(null); this.inspectedSource.set(null);
    this.other.set(null); this.otherSelection.set(0); this.comparison.set(null);
    this.sourceSelection.set(0); this.busy.set(true); this.message.set('');
    try {
      const response = await this.api.contentLifecycle(this.organizationId, this.projectId, undefined, id);
      if (generation !== this.generation || selection !== this.selectionGeneration) return;
      const info = this.readContext(response);
      if (!info.reviews.length || info.reviews.length > 20 || info.reviews.some((row) => row.review_id !== id)
        || !info.reviews[0].is_latest) throw new Error();
      const previous = this.context();
      this.context.set({ ...info, reviews: previous?.reviews || [], has_more: previous?.has_more || false });
      this.selected.set(info.reviews[0]); this.history.set(info.reviews); this.historyMore.set(info.has_more);
    } catch { if (generation === this.generation && selection === this.selectionGeneration) {
      this.clearEvidence(); this.error.set('Exact human history unavailable; refresh before another decision.');
    } }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  async loadOther(event: Event) {
    event.preventDefault(); const form = event.target as HTMLFormElement;
    if (this.busy() || this.pending() || !this.context()?.can_review || !form.reportValidity()) return;
    const fields = new FormData(form), organization = Number(fields.get('other_organization_id')), project = Number(fields.get('other_project_id'));
    if (!positive(organization) || !positive(project)) return;
    const generation = this.generation; this.busy.set(true); this.error.set(''); this.comparison.set(null);
    this.other.set(null); this.otherSelection.set(0);
    try {
      const response = await this.api.contentLifecycle(organization, project);
      if (generation !== this.generation) return;
      const info = this.readContext(response, organization, project);
      if (!info.can_review) throw new Error();
      this.other.set({ organizationId: organization, projectId: project, info });
    } catch { if (generation === this.generation) {
      this.clearEvidence(); this.error.set('Other exact project/source authority unavailable. Refresh both scopes before comparison.');
    } }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  chooseOther(id: number) { if (!this.busy() && !this.pending()) { this.otherSelection.set(id); this.comparison.set(null); } }
  async compare() {
    const left = this.inspectedSource(), scope = this.other(), text = this.text();
    const right = scope?.info.sources.find((row) => row.content.revision_id === this.otherSelection());
    if (this.busy() || this.pending() || !this.context()?.can_review || !left || !right || !scope || !text
      || left.content.revision_id === right.content.revision_id) return;
    const frozen = structuredClone({ left, right, organization: scope.organizationId, project: scope.projectId });
    const generation = this.generation; this.busy.set(true); this.comparison.set(null); this.error.set('');
    try {
      const selections = [{ organization: this.organizationId, project: this.projectId, source: frozen.left },
        { organization: frozen.organization, project: frozen.project, source: frozen.right }];
      for (const side of selections) {
        const response = await this.api.contentLifecycle(side.organization, side.project);
        if (generation !== this.generation) return;
        const current = this.readContext(response, side.organization, side.project);
        if (!current.can_review || !current.sources.some((row) => same(row, side.source))) throw new Error();
      }
      const response = await this.api.contentComparison(this.organizationId, this.projectId, frozen.left.content.revision_id,
        frozen.organization, frozen.project, frozen.right.content.revision_id);
      if (generation !== this.generation) return;
      const pair = response.body['comparison'] as Pair;
      if (response.status !== 200 || response.body['organization_id'] !== this.organizationId || response.body['project_id'] !== this.projectId
        || !object(pair) || pair.method !== 'content-native-comparison-v1'
        || typeof pair.same_native_body !== 'boolean'
        || pair.interpretation !== 'saved_native_text_only_not_live_duplicate_content_thinness_or_service_verification'
        || pair.site_action !== 'separate_human_judgment_and_each_project_action_approval_required') throw new Error();
      for (const [index, side] of [pair.left, pair.right].entries()) {
        const selection = selections[index];
        if (!object(side) || side.organization_id !== selection.organization || side.project_id !== selection.project
          || !same(side.source, selection.source) || !object(side.text) || Object.keys(side.text).length !== 4
          || !await textMatches({ ...side.text, id: side.source.content.revision_id, project_id: side.project_id,
            item_id: side.source.content.item_id, revision: side.source.content.revision, brief_id: side.source.brief.id,
            state: side.source.content.state, created_at: side.source.content.created_at }, selection.source, selection.project)) throw new Error();
        if (generation !== this.generation) return;
      }
      if (pair.same_native_body !== (pair.left.text.body === pair.right.text.body)) throw new Error();
      for (const side of selections) {
        const response = await this.api.contentLifecycle(side.organization, side.project);
        if (generation !== this.generation) return;
        const current = this.readContext(response, side.organization, side.project);
        if (!current.can_review || !current.sources.some((row) => same(row, side.source))) throw new Error();
      }
      this.comparison.set(structuredClone(pair));
    } catch { if (generation === this.generation) {
      this.clearEvidence(); this.error.set('Exact pair text/source/role/latest authority changed or read failed. No comparison, copy or command retained.');
    } }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  edit(row: Review) {
    if (this.busy() || this.pending() || !this.context()?.can_review || !row.is_latest) return;
    this.editing.set(structuredClone(row)); this.choose(0);
  }
  private validIntake(data: Intake, source: Source, text: Text) {
    return validIntakeDeclaration(data, source)
      && (!data.quote || [text.title, text.body, text.meta_description].some((value) => value.includes(data.quote)));
  }
  saveDraft(event: Event) {
    event.preventDefault(); const form = event.target as HTMLFormElement, info = this.context();
    const text = this.text(), source = this.inspectedSource(), previous = this.editing();
    if (this.busy() || this.pending() || !info?.can_review || !text || !source || !form.reportValidity()) return;
    const fields = new FormData(form);
    if (Number(fields.get('source')) !== source.content.revision_id || RIGHTS.some((key) => !fields.has(key))
      || previous && previous.source_evidence.content.item_id !== source.content.item_id) return;
    const intake = { policy: POLICY, content_revision_id: text.id, text_sha256: source.content.text_sha256 } as Intake;
    // FormData replaces lone surrogates; validate original control text instead.
    for (const key of INTAKE_TEXT) intake[key] = (form.elements.namedItem(key) as HTMLInputElement)?.value || '';
    for (const key of RIGHTS) intake[key] = true;
    if (!this.validIntake(intake, source, text)) {
      this.error.set('Keep bounded human notes within 16 KiB, original aware review/fact dates, an exact stored quote and substantive evidence. Review rationale, distinct replacement and user impact; unchecked is not a proposal.'); return;
    }
    const data: Record<string, unknown> = { request_key: crypto.randomUUID(), intake, assignee_id: Number(fields.get('assignee_id')),
      state: 'draft', reason: (form.elements.namedItem('reason') as HTMLTextAreaElement)?.value || '', executed_at: null, execution_note: '' };
    if (previous) data['expected_revision'] = previous.revision;
    void this.prepare(structuredClone({ data, source, text, reviewId: previous?.review_id, previous: previous || undefined }));
  }
  async decide(event: Event, state: string) {
    event.preventDefault(); const form = event.target as HTMLFormElement, previous = this.selected();
    if (this.busy() || this.pending() || !this.context()?.can_review || !previous?.source_current || !previous.is_latest
      || !form.reportValidity()) return;
    const fields = new FormData(form); if (!fields.has('exact')) return;
    const next: Record<string, string[]> = { draft: ['review', 'dismissed'], review: ['approved', 'dismissed'], approved: ['reported', 'dismissed'] };
    if (!next[previous.state]?.includes(state) || state !== 'dismissed' && previous.intake.proposed_action === 'unselected') return;
    const date = state === 'reported' ? new Date(String(fields.get('executed_at'))) : null;
    if (date && (!Number.isFinite(date.getTime()) || date.getTime() > Date.now()
      || !previous.approved_at || date.getTime() < Date.parse(previous.approved_at))) {
      this.error.set('Record an actual manual handoff after approval, no later than now.'); return;
    }
    const command = structuredClone({ source: previous.source_evidence, previous, reviewId: previous.review_id,
      data: { request_key: crypto.randomUUID(), intake: previous.intake, assignee_id: previous.assignee_id,
        expected_revision: previous.revision, state, reason: (form.elements.namedItem('reason') as HTMLTextAreaElement)?.value || '',
        executed_at: date?.toISOString() || null, execution_note: (form.elements.namedItem('execution_note') as HTMLTextAreaElement)?.value || '' } });
    await this.prepare(command);
  }
  private candidatesMatch(info: Context, command: Omit<Pending, 'text'>) {
    return info.can_review && info.sources.some((row) => same(row, command.source))
      && info.assignees.some((row) => row.id === command.data['assignee_id']);
  }
  private async currentCommand(command: Omit<Pending, 'text'>, generation: number): Promise<Text> {
    const history = this.readContext(await this.api.contentLifecycle(this.organizationId, this.projectId, undefined, command.reviewId));
    if (generation !== this.generation || !this.candidatesMatch(history, command)) throw new Error();
    if (command.reviewId) {
      const latest = history.reviews[0], previous = command.previous;
      if (!latest || !previous || latest.review_id !== command.reviewId || !latest.is_latest
        || latest.revision !== command.data['expected_revision'] || latest.id !== previous.id
        || latest.state !== previous.state || latest.assignee_id !== previous.assignee_id
        || !same(latest.intake, previous.intake) || !same(latest.source_evidence, previous.source_evidence)
        || command.data['state'] !== 'draft' && !latest.source_current) throw new Error();
    }
    const response = await this.api.projectContent(this.organizationId, this.projectId, command.source.content.item_id);
    if (generation !== this.generation || response.status !== 200 || response.body['project_id'] !== this.projectId
      || response.body['source_state'] !== 'current_review_still_required'
      || !await textMatches(response.body['current'], command.source, this.projectId)) throw new Error();
    if (generation !== this.generation) throw new Error();
    const final = this.readContext(await this.api.contentLifecycle(this.organizationId, this.projectId, undefined, command.reviewId));
    if (generation !== this.generation || !this.candidatesMatch(final, command)
      || command.reviewId && (!final.reviews[0]?.is_latest || final.reviews[0].id !== command.previous?.id
        || command.data['state'] !== 'draft' && !final.reviews[0].source_current)) throw new Error();
    return structuredClone(response.body['current'] as Text);
  }
  private async prepare(command: Omit<Pending, 'text'> & { text?: Text }) {
    if (!validIntakeDeclaration(command.data['intake'] as Intake, command.source) || !validText(command.data['reason'], 500, true)
      || !validText(command.data['execution_note'], 500, command.data['state'] === 'reported')) {
      this.error.set('Keep human notes within their character limits, review notes within 16 KiB and combined source evidence within 32 KiB. Supply a nonblank reason and actual handoff note; invalid text cannot be saved.'); return;
    }
    const frozen = structuredClone(command), generation = this.generation; this.busy.set(true); this.error.set('');
    try {
      const text = await this.currentCommand(frozen, generation);
      if (generation !== this.generation) return;
      if (frozen.text && !same(text, frozen.text)
        || !this.validIntake(frozen.data['intake'] as Intake, frozen.source, text)) throw new Error();
      await this.send({ ...frozen, text });
    } catch { if (generation === this.generation) {
      this.clearEvidence(); this.error.set('Current exact content/source/assignee/role or latest review changed. No command sent.');
    } }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  private matchesCommand(row: Review, command: Pending) {
    return (!command.reviewId || row.review_id === command.reviewId)
      && row.revision === Number(command.data['expected_revision'] || 0) + 1
      && ['assignee_id', 'state', 'reason', 'execution_note'].every((key) => (row as unknown as Record<string, unknown>)[key] === command.data[key])
      && (row.executed_at === command.data['executed_at'] || aware(row.executed_at) && aware(command.data['executed_at'])
        && Date.parse(row.executed_at) === Date.parse(command.data['executed_at']))
      && same(row.intake, command.data['intake']) && same(row.source_evidence, command.source)
      && (row.state !== 'approved' || row.reviewed_revision_id === command.previous?.id)
      && (row.state !== 'reported' || row.reviewed_revision_id === command.previous?.reviewed_revision_id
        && row.approved_by_id === command.previous?.approved_by_id && row.approved_at === command.previous?.approved_at);
  }
  private async send(command: Pending) {
    const generation = this.generation; this.pending.set(command); this.notFound.set(false); this.message.set('');
    try {
      const response = await this.api.contentLifecycle(this.organizationId, this.projectId, command.data, command.reviewId);
      if (generation !== this.generation) return;
      if ([200, 201].includes(response.status) && response.body['organization_id'] === this.organizationId
        && response.body['project_id'] === this.projectId && isReview(response.body['review'], this.projectId)
        && this.matchesCommand(response.body['review'], command)) {
        this.pending.set(null); this.busy.set(false); await this.load();
        if (generation + 1 === this.generation) this.message.set('Human quality decision recorded. No website changed.');
      } else if ([400, 401, 403, 404, 409, 413, 429].includes(response.status)) {
        this.clear(); this.error.set('Exact human decision denied. Refresh current sources and history.');
      } else { this.clearEvidence(); this.message.set('Save outcome uncertain. Check the exact request key; no automatic replay.'); }
    } catch { if (generation === this.generation) {
      this.clearEvidence(); this.message.set('Save outcome uncertain. Check the exact request key; no automatic replay.');
    } }
  }
  async reconcile() {
    const command = this.pending(); if (!command || this.busy()) return;
    const generation = this.generation; this.busy.set(true); this.notFound.set(false);
    try {
      const response = await this.api.contentLifecycle(this.organizationId, this.projectId, undefined, undefined, String(command.data['request_key']));
      if (generation !== this.generation) return;
      const info = this.readContext(response);
      if (response.body['lookup'] === 'found' && info.reviews.length === 1 && this.matchesCommand(info.reviews[0], command)) {
        this.pending.set(null); this.busy.set(false); await this.load();
        if (generation + 1 === this.generation) this.message.set('Exact immutable request reconciled; no command replayed.');
      } else if (response.body['lookup'] === 'not_found' && !info.reviews.length && this.candidatesMatch(info, command)) {
        const text = await this.currentCommand(command, generation);
        if (generation !== this.generation || !same(text, command.text)) throw new Error();
        this.notFound.set(true); this.message.set('No recorded decision. Exact source/text/assignee/latest/role match; deliberate same-command retry is available.');
      } else throw new Error();
    } catch { if (generation === this.generation) {
      this.clearEvidence(); this.notFound.set(false); this.message.set('Outcome or current exact authority unavailable. No command replayed.');
    } }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  async retry() {
    const command = this.pending(), generation = this.generation;
    if (!command || !this.notFound() || this.busy()) return;
    await this.reconcile();
    if (generation === this.generation && this.pending() === command && this.notFound()) {
      this.busy.set(true);
      try { await this.send(command); }
      finally { if (generation === this.generation) this.busy.set(false); }
    }
  }
}
