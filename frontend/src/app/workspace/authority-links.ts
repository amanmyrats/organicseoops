import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, OnInit, computed, effect, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi, ApiResult } from '../account/account-api';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';

const POLICY = 'authority-human-link-v1';
type Target = { method: string; project_id: number; configuration_revision: number; origin: string;
  verification_id: number; verified_at: string; crawl_page_id: number; crawl_run_id: number; job_id: number;
  requested_url: string; final_url: string; observed_at: string; completed_at: string; content_observed_at: string;
  status_code: number | null; error_category: string; body_sha256: string; raw_artifact_id: number | null;
  raw_body_readback: string; reused_from_id: number | null; redirect_chain: { url: string; status: number }[];
  coverage: { page_limit: number; pages_attempted: number; pages_observed: number; crawl_status: string; whole_site: string };
  state: string; external_source: string; unlinked_or_lost_link: string; interpretation: string };
type Recovery = { method: string; project_id: number; target_evidence: Target; action_review_id: number;
  action_id: string; action_revision: number; state: string; action_kind: string; affected_urls: string[];
  assignee_id: number; acceptance_criteria: string; opportunity_id: number; finding_id: number; diagnostics_id: number;
  site_approval_review_id: number | null; implemented_at: string | null; interpretation: string };
type Intake = { policy: string; source_kind: string; configuration_revision: number; origin: string; crawl_page_id: number;
  observation_reference: string; source_url: string; target_url: string; observed_at: string; status: string;
  coverage: string; surface: string; href: string; anchor_text: string; rel: string; evidence_note: string;
  use_permission: boolean; storage_permission: boolean; not_restricted_provider_copy: boolean; no_personal_payload: boolean };
type Proposal = { action: string; relevance: string; draft_text: string; outreach_permission: boolean };
type Review = { id: number; link_id: string; project_id: number; revision: number; state: string; intake: Intake;
  target_evidence: Target; proposal: Proposal; recovery_action_review_id: number | null; recovery_evidence: Recovery | Record<string, never>;
  assignee_id: number; reason: string; approved_at: string | null; executed_at: string | null; execution_note: string;
  created_at: string; source_current: boolean; is_latest: boolean; effective_approval: boolean; scope: string; execution_state: string };
type Context = { organization_id: number; project_id: number; policy: string; can_review: boolean; targets: Target[];
  recovery_actions: Recovery[]; assignees: { id: number }[]; candidates_has_more: boolean; reviews: Review[]; has_more: boolean;
  source_basis: string; sending: string; independent_external_verification: string; lost_unlinked_links: string };
type Pending = { data: Record<string, unknown>; linkId?: string; target: Target; recovery: Recovery | Record<string, never> };
const positive = (value: unknown) => Number.isSafeInteger(value) && Number(value) > 0;
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const aware = (value: unknown): value is string => typeof value === 'string'
  && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const uuid = (value: unknown) => typeof value === 'string' && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/.test(value);

export function safeUrl(value: unknown) {
  if (typeof value !== 'string' || /[\s\\]/.test(value)) return '';
  try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password
    && !url.search && !url.hash && (!url.port || url.port === '443') ? url.href : ''; }
  catch { return ''; }
}
export function same(left: unknown, right: unknown): boolean {
  if (left === right) return true;
  if (Array.isArray(left) || Array.isArray(right)) return Array.isArray(left) && Array.isArray(right)
    && left.length === right.length && left.every((value, index) => same(value, right[index]));
  return object(left) && object(right) && Object.keys(left).length === Object.keys(right).length
    && Object.entries(left).every(([key, value]) => Object.hasOwn(right, key) && same(value, right[key]));
}
export function isTarget(value: unknown, project: number): value is Target {
  if (!object(value)) return false;
  const row = value as unknown as Target;
  return row.method === 'authority-own-target-http-v1' && row.project_id === project
    && [row.verification_id, row.crawl_page_id, row.crawl_run_id, row.job_id].every(positive)
    && Number.isSafeInteger(row.configuration_revision) && row.configuration_revision >= 0
    && [row.verified_at, row.observed_at, row.completed_at, row.content_observed_at].every(aware)
    && !!safeUrl(row.origin) && new URL(row.origin).origin === row.origin && !!safeUrl(row.requested_url)
    && new URL(row.requested_url).origin === row.origin
    && (row.final_url === '' || !!safeUrl(row.final_url) && new URL(row.final_url).origin === row.origin)
    && (row.status_code === null || Number.isInteger(row.status_code) && row.status_code >= 100 && row.status_code <= 599)
    && typeof row.error_category === 'string' && typeof row.body_sha256 === 'string'
    && (row.body_sha256 === '' || /^[a-f0-9]{64}$/.test(row.body_sha256))
    && (row.raw_artifact_id === null || positive(row.raw_artifact_id))
    && (row.reused_from_id === null || positive(row.reused_from_id))
    && ['checked', 'not_retained'].includes(row.raw_body_readback)
    && Array.isArray(row.redirect_chain) && row.redirect_chain.length <= 5
    && row.redirect_chain.every((hop) => object(hop) && !!safeUrl(hop.url) && new URL(hop.url).origin === row.origin
      && [301, 302, 303, 307, 308].includes(hop.status))
    && object(row.coverage) && positive(row.coverage.page_limit)
    && [row.coverage.pages_attempted, row.coverage.pages_observed].every((count) => Number.isSafeInteger(count) && count >= 0)
    && ['succeeded', 'partially_succeeded'].includes(row.coverage.crawl_status) && row.coverage.whole_site === 'not_established'
    && ['fetch_failed_or_unavailable_not_broken_proof', 'dated_http_missing_destination_candidate',
      'not_modified_reused_body_not_new_success_status', 'dated_http_success_not_usefulness_or_link_recovery_proof',
      'dated_http_other_status_not_missing_destination_proof'].includes(row.state)
    && row.external_source === 'customer_reported_not_independently_verified' && row.unlinked_or_lost_link === 'not_established'
    && row.interpretation === 'separate_dated_own_target_http_not_current_site_or_external_link_verification';
}
function isRecovery(value: unknown, project: number): value is Recovery {
  if (!object(value)) return false;
  const row = value as unknown as Recovery;
  return row.method === 'authority-own-target-recovery-v1' && row.project_id === project
    && isTarget(row.target_evidence, project) && row.target_evidence.state === 'dated_http_missing_destination_candidate'
    && [row.action_review_id, row.action_revision, row.assignee_id, row.opportunity_id, row.finding_id, row.diagnostics_id].every(positive)
    && uuid(row.action_id) && ['proposed', 'accepted', 'in_progress', 'implemented', 'verified', 'outcome_reviewed'].includes(row.state)
    && ['refresh', 'redirect'].includes(row.action_kind) && Array.isArray(row.affected_urls)
    && row.affected_urls.length === (row.action_kind === 'redirect' ? 2 : 1)
    && row.affected_urls[0] === row.target_evidence.requested_url
    && row.affected_urls.every((url) => !!safeUrl(url) && new URL(url).origin === row.target_evidence.origin)
    && typeof row.acceptance_criteria === 'string'
    && (row.site_approval_review_id === null || positive(row.site_approval_review_id))
    && (row.implemented_at === null || aware(row.implemented_at))
    && row.interpretation === 'existing_separately_approved_own_page_action_not_outreach_or_external_link_recovery_proof';
}
function isIntake(value: unknown, target: Target): value is Intake {
  if (!object(value)) return false;
  const row = value as unknown as Intake;
  const fields = ['policy', 'source_kind', 'configuration_revision', 'origin', 'crawl_page_id', 'observation_reference',
    'source_url', 'target_url', 'observed_at', 'status', 'coverage', 'surface', 'href', 'anchor_text', 'rel', 'evidence_note',
    'use_permission', 'storage_permission', 'not_restricted_provider_copy', 'no_personal_payload'];
  return Object.keys(value).length === fields.length && fields.every((key) => Object.hasOwn(value, key))
    && row.policy === POLICY && row.source_kind === 'customer_manual_link_observation'
    && row.configuration_revision === target.configuration_revision && row.origin === target.origin
    && row.crawl_page_id === target.crawl_page_id && row.target_url === target.requested_url
    && typeof row.observation_reference === 'string' && /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(row.observation_reference)
    && !!safeUrl(row.source_url) && new URL(row.source_url).hostname !== new URL(row.target_url).hostname
    && aware(row.observed_at) && Date.parse(row.observed_at) <= Date.now()
    && ['partial_page', 'complete_document_customer_reported', 'unavailable'].includes(row.coverage)
    && ['html_document', 'rendered_document', 'unknown'].includes(row.surface)
    && ['href', 'anchor_text', 'rel', 'evidence_note'].every((key) => typeof value[key] === 'string')
    && !!row.evidence_note.trim()
    && (row.status === 'observed' && row.href === row.target_url && row.coverage !== 'unavailable' && row.surface !== 'unknown'
      || row.status === 'not_seen_in_inspected_page' && !row.href && !row.anchor_text && !row.rel
        && row.coverage !== 'unavailable' && row.surface !== 'unknown'
      || row.status === 'unavailable' && !row.href && !row.anchor_text && !row.rel && row.coverage === 'unavailable' && row.surface === 'unknown')
    && ['use_permission', 'storage_permission', 'not_restricted_provider_copy', 'no_personal_payload'].every((key) => value[key] === true);
}
function isProposal(value: unknown): value is Proposal {
  return object(value) && Object.keys(value).length === 4
    && typeof value['action'] === 'string' && ['verify_source', 'request_source_correction', 'review_target_recovery'].includes(value['action'])
    && typeof value['relevance'] === 'string' && !!value['relevance'].trim()
    && typeof value['draft_text'] === 'string' && typeof value['outreach_permission'] === 'boolean';
}
function isReview(value: unknown, project: number): value is Review {
  if (!object(value)) return false;
  const row = value as unknown as Review;
  return positive(row.id) && uuid(row.link_id) && row.project_id === project && positive(row.revision) && positive(row.assignee_id)
    && ['draft', 'review', 'approved', 'reported', 'dismissed'].includes(row.state)
    && ['reason', 'execution_note'].every((key) => typeof value[key] === 'string') && aware(row.created_at)
    && ['source_current', 'is_latest', 'effective_approval'].every((key) => typeof value[key] === 'boolean')
    && (row.approved_at === null || aware(row.approved_at)) && (row.executed_at === null || aware(row.executed_at))
    && isTarget(row.target_evidence, project) && isIntake(row.intake, row.target_evidence) && isProposal(row.proposal)
    && (row.proposal.action === 'review_target_recovery'
      ? row.intake.status === 'observed' && isRecovery(row.recovery_evidence, project)
        && row.recovery_evidence.action_review_id === row.recovery_action_review_id
        && same(row.recovery_evidence.target_evidence, row.target_evidence)
      : row.recovery_action_review_id === null && object(row.recovery_evidence) && !Object.keys(row.recovery_evidence).length)
    && row.scope === 'historical_human_link_report_not_independent_link_proof_or_site_approval'
    && ['not_reported', 'customer_reported_manual_activity_not_verified'].includes(row.execution_state)
    && (!row.effective_approval || row.source_current && row.is_latest && ['approved', 'reported'].includes(row.state));
}

const authorityLinksTurkish: Record<string, string> = {
  "Private human link and recovery review": "Özel insan bağlantı ve kurtarma incelemesi",
  "Human link reports and separate destination recovery review": "İnsan bağlantı bildirimleri ve ayrı hedef kurtarma incelemesi",
  "Organization": "Kuruluş",
  "· project": "· proje",
  "Return to project evidence": "Proje kanıtlarına dönün",
  "Research-quote prospects": "Araştırma alıntısına dayalı fırsatlar",
  "Separately request selected static-source verification": "Seçilen statik kaynak doğrulamasını ayrıca isteyin",
  "Separately approve site actions and inspect technical follow-up": "Site eylemlerini ayrıca onaylayın ve teknik takibi inceleyin",
  "External links are independent customer reports, not independently verified crawl or index observations. Even a declared complete-document absence does not prove an unlinked mention or lost link. Own-target HTTP evidence is dated and separate; 404/410 supports useful-destination review, not a current broken inbound-link claim.": "Dış bağlantılar, bağımsız müşteri bildirimleridir; bağımsız doğrulanmış tarama veya dizin gözlemleri değildir. Beyan edilen tam belgede yokluk bile bağlantısız bahsedilmeyi veya kaybolmuş bağlantıyı kanıtlamaz. Kendi hedef HTTP kanıtı tarihli ve ayrıdır; 404/410, güncel bozuk gelen bağlantı iddiasını değil, yararlı hedef incelemesini destekler.",
  "No automatic fetch, AI draft, link creation or sending. Supply no identities, secrets or restricted provider copies. Independent use/storage declarations cover private export, 90-day retained access after lapse, active deletion within 30 days of closure/retention expiry and up to 35-day backup rotation after active deletion.": "Otomatik getirme, yapay zekâ taslağı, bağlantı oluşturma veya gönderim yoktur. Kimlikler, sırlar veya kısıtlı sağlayıcı kopyaları eklemeyin. Bağımsız kullanma/saklama beyanları; özel dışa aktarmayı, erişim süresi bittikten sonra 90 günlük saklanan erişimi, kapatma/saklama süresi bitiminden sonra 30 gün içinde aktif silmeyi ve aktif silmeden sonra en fazla 35 günlük yedek rotasyonunu kapsar.",
  "Loading current target candidates and private human review history.": "Güncel hedef adayları ve özel insan inceleme geçmişi yükleniyor.",
  "Reload current project": "Güncel projeyi yeniden yükleyin",
  "The exact save outcome is uncertain. Command and target/recovery snapshots are frozen in component memory. No automatic replay.": "Tam kayıt sonucu belirsiz. Komut ve hedef/kurtarma anlık görüntüleri bileşen belleğinde sabitlenir. Otomatik yeniden yürütme yoktur.",
  "Check uncertain save": "Belirsiz kaydı kontrol edin",
  "Retry same exact command after current checks": "Güncel kontrollerden sonra aynı tam komutu tekrar deneyin",
  "Refresh current authority and history": "Güncel yetkiyi ve geçmişi yenileyin",
  "Current flags are as of refresh. Every command rechecks scope, source actors, assignee and retention on the server.": "Güncel göstergeler yenileme anına aittir. Her komut, sunucuda kapsamı, kaynak aktörlerini, atanan kişiyi ve saklamayı yeniden kontrol eder.",
  "Only the latest 50 link reviews are shown.": "Yalnızca en son 50 bağlantı incelemesi gösterilir.",
  "No human link reviews recorded for this project.": "Bu proje için insan bağlantı incelemesi kaydedilmedi.",
  "· assignee": "· atanan kişi",
  "· revision": "· sürüm",
  "Inspect exact source, target and history": "Tam kaynağı, hedefi ve geçmişi inceleyin",
  "Exact human revision": "Tam insan sürümü",
  "Original customer-reported external source": "Müşterinin bildirdiği özgün dış kaynak",
  "· original aware observation date": "· saat dilimli özgün gözlem tarihi",
  "· reference": "· referans",
  ". Independent external verification and lost/unlinked links remain unestablished.": ". Bağımsız dış doğrulama ve kaybolmuş/bağlantısız bağlantılar kanıtlanmış değildir.",
  "Literal absolute href:": "Değişmez mutlak href:",
  "Anchor text:": "Bağlantı metni:",
  "Rel:": "Rel:",
  "Human evidence note:": "İnsan kanıt notu:",
  "Exact original report and rights declarations (not legal verification)": "Tam özgün bildirim ve hak beyanları (yasal doğrulama değil)",
  "Separate dated own-target HTTP evidence": "Ayrı tarihli kendi hedef HTTP kanıtı",
  "· observed": "· gözlendi",
  "· HTTP": "· HTTP",
  "Private body readback:": "Özel gövde geri okuması:",
  ". Content date": ". İçerik tarihi",
  "; 304 reuse is not a newly observed success. Whole-site coverage, current usefulness and external link recovery remain unestablished.": "; 304 yeniden kullanımı yeni gözlemlenmiş başarı değildir. Tüm site kapsamı, güncel yararlılık ve dış bağlantı kurtarma kanıtlanmış değildir.",
  "Exact target verification/configuration, redirects, body digest and crawl coverage": "Tam hedef doğrulama/yapılandırma, yönlendirmeler, gövde özeti ve tarama kapsamı",
  "Genuine separate own-page recovery handoff": "Gerçek ayrı kendi sayfa kurtarma devri",
  "Existing page-action review": "Mevcut sayfa eylemi incelemesi",
  ". This human link-review approval never approves or executes a website change. Use the separately accepted page action and its dated technical follow-up; that is not independent external link-recovery proof.": ". Bu insan bağlantı inceleme onayı, web sitesi değişikliğini hiçbir zaman onaylamaz veya uygulamaz. Ayrı kabul edilmiş sayfa eylemini ve onun tarihli teknik takibini kullanın; bu, bağımsız dış bağlantı kurtarma kanıtı değildir.",
  "Exact diagnostic, Finding, Opportunity and independently approved page-action evidence": "Tam tanı, bulgu, fırsat ve bağımsız onaylanmış sayfa eylemi kanıtı",
  "Human relevance and exact proposal": "İnsan ilgililik değerlendirmesi ve tam öneri",
  "· separate manual outreach permission declared:": "· ayrı manuel iletişim izni beyan edildi:",
  "· approved": "· onaylandı",
  "Source/reviewer/assignee authority is stale. New review, approval and manual activity reporting are denied.": "Kaynak/inceleyen/atanan kişi yetkisi eskidir. Yeni inceleme, onay ve manuel faaliyet bildirimi reddedilir.",
  "Actual manual activity reported": "Gerçek manuel faaliyet bildirildi",
  ". Customer-reported, not independently verified or a website execution.": ". Müşteri bildirimi; bağımsız doğrulanmış değil veya web sitesi uygulaması değil.",
  "Separate exact human decision": "Ayrı tam insan kararı",
  "Human decision reason": "İnsan karar gerekçesi",
  "I reviewed the unchanged original report, own-target evidence, separate recovery handoff, proposal and assignee of revision": "Sürümün değişmemiş özgün bildirimini, kendi hedef kanıtını, ayrı kurtarma devrini, önerisini ve atanan kişisini inceledim:",
  ". Approval does not send or change the site.": ". Onay gönderim yapmaz veya siteyi değiştirmez.",
  "Actual manual activity date/time (browser-local timezone, after approval)": "Gerçek manuel faaliyet tarihi/saati (tarayıcının yerel saat dilimi, onaydan sonra)",
  "Actual manual activity note, without private identities": "Gerçek manuel faaliyet notu, özel kimlik bilgisi olmadan",
  "Human dismissal": "İnsan reddetmesi",
  "Dismissal reason": "Reddetme gerekçesi",
  "Dismiss this exact link candidate; approval will be absent.": "Bu bağlantı adayının tamamını reddedin; onay bulunmayacaktır.",
  "Dismiss without activity": "Faaliyet olmadan reddedin",
  "Correct or reopen as a new unapproved draft": "Yeni onaylanmamış taslak olarak düzeltin veya yeniden açın",
  "Immutable source/target/proposal/assignee/approval/activity history (newest 20)": "Değişmez kaynak/hedef/öneri/atanan kişi/onay/faaliyet geçmişi (en yeni 20)",
  "Revision": "Sürüm",
  "· approval": "· onay",
  "Older history exists; this bounded view is incomplete.": "Daha eski geçmiş var; bu sınırlı görünüm eksiktir.",
  "No current verified own-target crawl and eligible assignee available. Inspect source configuration and crawl evidence first; nothing is fetched here.": "Güncel doğrulanmış kendi hedef taraması ve uygun atanan kişi kullanılamıyor. Önce kaynak yapılandırmasını ve tarama kanıtını inceleyin; burada hiçbir şey getirilmez.",
  "Only bounded recent target/recovery/assignee candidates are shown; inventory is partial.": "Yalnızca sınırlı son hedef/kurtarma/atanan kişi adayları gösterilir; envanter kısmidir.",
  "Original external report and separate current own-target evidence": "Özgün dış bildirim ve ayrı güncel kendi hedef kanıtı",
  "Actual current own-target crawl observation": "Gerçek güncel kendi hedef tarama gözlemi",
  "Choose actual stored target": "Gerçek kayıtlı hedefi seçin",
  "Selected exact dated HTTP/verification/configuration/coverage snapshot": "Seçilen tam tarihli HTTP/doğrulama/yapılandırma/kapsam anlık görüntüsü",
  "Opaque independent observation reference (no personal identifier)": "Opak bağımsız gözlem referansı (kişisel tanımlayıcı yok)",
  "Original external HTTPS source URL (no query, fragment or credentials)": "Özgün dış HTTPS kaynak URL'si (sorgu, parça veya kimlik bilgisi yok)",
  "Original aware observation date, including offset (preserved unchanged, e.g. 2026-01-01T12:00:00+03:00)": "Saat dilimi farkı dahil özgün gözlem tarihi (değişmeden korunur, örn. 2026-01-01T12:00:00+03:00)",
  "Customer-reported link state": "Müşterinin bildirdiği bağlantı durumu",
  "Literal absolute href observed": "Değişmez mutlak href gözlendi",
  "Not seen in inspected page (not lost/unlinked proof)": "İncelenen sayfada görülmedi (kaybolmuş/bağlantısız kanıtı değil)",
  "Unavailable": "Kullanılamıyor",
  "Actual human-reported document coverage": "İnsanın bildirdiği gerçek belge kapsamı",
  "Partial page": "Kısmi sayfa",
  "Complete document, customer-reported only": "Tam belge, yalnızca müşteri bildirimi",
  "Inspected document surface": "İncelenen belge yüzeyi",
  "HTML document": "HTML belgesi",
  "Rendered document": "İşlenmiş belge",
  "Unknown (unavailable only)": "Bilinmiyor (yalnızca kullanılamıyorsa)",
  "Observed href must be the unchanged literal absolute selected target. For not-seen/unavailable reports, leave href/anchor/rel empty. Relative/base-dependent hrefs are unsupported.": "Gözlenen href, seçilen hedefin değişmemiş mutlak değeri olmalıdır. Görülmedi/kullanılamıyor bildirimlerinde href/bağlantı metni/rel alanlarını boş bırakın. Göreli/base bağımlı href'ler desteklenmez.",
  "Literal absolute href, if observed": "Gözlendiyse değişmez mutlak href",
  "Literal anchor text, if observed": "Gözlendiyse değişmez bağlantı metni",
  "Literal rel, if observed": "Gözlendiyse değişmez rel",
  "Minimized human evidence note and limitations": "En aza indirilmiş insan kanıt notu ve sınırlamalar",
  "Human proposed activity": "İnsanın önerdiği faaliyet",
  "Human source verification review": "İnsan kaynak doğrulama incelemesi",
  "Request source correction (separate manual outreach permission)": "Kaynak düzeltmesi isteyin (ayrı manuel iletişim izni)",
  "Review useful-target recovery handoff (not website approval)": "Yararlı hedef kurtarma devrini inceleyin (web sitesi onayı değil)",
  "Genuine existing exact-target page-action revision": "Gerçek mevcut tam hedef sayfa eylemi sürümü",
  "Choose separately supported page action": "Ayrıca desteklenen sayfa eylemini seçin",
  "Page action": "Sayfa eylemi",
  "· separate site approval": "· ayrı site onayı",
  "No candidate means recovery handoff is unavailable. No Finding, Opportunity or page action is fabricated here.": "Aday yoksa kurtarma devri kullanılamaz. Burada bulgu, fırsat veya sayfa eylemi uydurulmaz.",
  "Human relevance and useful-destination rationale": "İnsan ilgililik değerlendirmesi ve yararlı hedef gerekçesi",
  "Eligible project assignee": "Uygun proje atanan kişisi",
  "Project user": "Proje kullanıcısı",
  "Optional exact human activity draft, without identities or secrets": "Kimlikler veya sırlar içermeyen isteğe bağlı tam insan faaliyet taslağı",
  "Human draft/correction reason": "İnsan taslak/düzeltme gerekçesi",
  "I independently have permission to use this evidence for this proposal.": "Bu kanıtı bu öneri için kullanmak üzere bağımsız iznim var.",
  "I independently have permission to store it under the disclosed private export/deletion/backup policy.": "Açıklanan özel dışa aktarma/silme/yedek politikası kapsamında saklamak için bağımsız iznim var.",
  "This is not copied restricted or response-only provider content.": "Bu, kısıtlı veya yalnızca yanıtta kullanılan sağlayıcı içeriğinin kopyası değildir.",
  "This minimized report has no personal payload, contact identities or secrets.": "Bu en aza indirilmiş bildirim, kişisel yük, iletişim kimlikleri veya sırlar içermez.",
  "I separately have permission for proposed manual outreach. A reported link does not grant it.": "Önerilen manuel iletişim için ayrı iznim var. Bildirilen bağlantı bu izni vermez.",
  "Save new unapproved human draft revision": "Yeni onaylanmamış insan taslak sürümünü kaydedin",
  "Cancel correction": "Düzeltmeyi iptal edin",
  "Read-only history. Current verified owner/admin authority is required for intake and every human decision.": "Salt okunur geçmiş. Veri girişi ve her insan kararı için güncel doğrulanmış sahip/yönetici yetkisi gerekir.",
  "Current authority at refresh": "Yenileme anında güncel yetki",
  "Stale/unavailable authority": "Eski/kullanılamayan yetki",
  "Absent; not seen/unavailable is not loss": "Yok; görülmedi/kullanılamıyor kayıp demek değildir",
  "Absent": "Yok",
  "Yes; user attestation only": "Evet; yalnızca kullanıcı beyanı",
  "No": "Hayır",
  "Absent; no draft generated": "Yok; taslak üretilmedi",
  "Exact human approval current at refresh": "Tam insan onayı yenileme anında güncel",
  "No current effective approval": "Güncel geçerli onay yok",
  "Send exact human draft to review": "Tam insan taslağını incelemeye gönderin",
  "Approve exact reviewed human activity": "Tam incelenmiş insan faaliyetini onaylayın",
  "Record actual manual activity only": "Yalnızca gerçek manuel faaliyeti kaydedin",
  "Stale authority": "Eski yetki",
  "No activity date": "Faaliyet tarihi yok",
  "New unapproved correction; earlier approval never carries forward": "Yeni onaylanmamış düzeltme; önceki onay hiçbir zaman taşınmaz",
  "Record one independent human link report": "Bağımsız tek bir insan bağlantı bildirimi kaydedin",
  "Select an authorized organization and project.": "Yetkili bir kuruluş ve proje seçin.",
  "Link history or current project/session authority is unavailable.": "Bağlantı geçmişi veya güncel proje/oturum yetkisi kullanılamıyor.",
  "Exact history is unavailable; refresh before another decision.": "Tam geçmiş kullanılamıyor; başka karar vermeden önce yenileyin.",
  "Choose literal independent evidence, original aware date, matching current target/recovery, eligible assignee and affirmative rights. Not-seen/unavailable requires empty href/anchor/rel.": "Değişmez bağımsız kanıt, özgün saat dilimli tarih, eşleşen güncel hedef/kurtarma, uygun atanan kişi ve olumlu haklar seçin. Görülmedi/kullanılamıyor için href/bağlantı metni/rel boş olmalıdır.",
  "Report the actual nonfuture manual activity time after exact human approval.": "Tam insan onayından sonraki gerçek, gelecekte olmayan manuel faaliyet zamanını bildirin.",
  "Exact human decision recorded. No source fetched, outreach sent or website changed.": "Tam insan kararı kaydedildi. Kaynak getirilmedi, iletişim gönderilmedi veya web sitesi değiştirilmedi.",
  "Current authority, exact revision or fields were denied. Refresh before another decision.": "Güncel yetki, tam sürüm veya alanlar reddedildi. Başka karar vermeden önce yenileyin.",
  "Save outcome uncertain; inspect the exact request key before continuing.": "Kayıt sonucu belirsiz; devam etmeden önce tam istek anahtarını inceleyin.",
  "Request reconciled from immutable history; no command replayed.": "İstek değişmez geçmişten uzlaştırıldı; komut yeniden yürütülmedi.",
  "No decision found. Current exact target/recovery/assignee/role match; a deliberate same-command retry is available.": "Karar bulunamadı. Güncel tam hedef/kurtarma/atanan kişi/rol eşleşiyor; aynı komutu bilinçli tekrar deneme kullanılabilir.",
  "Outcome or matching current authority remains unavailable. No command replayed.": "Sonuç veya eşleşen güncel yetki hâlâ kullanılamıyor. Komut yeniden yürütülmedi.",
  "Latest human link reviews": "İnsanın yaptığı son bağlantı incelemeleri",
  "Unreviewed Turkish human link-report interface draft in local development. Human reports and proposals retain their original language; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe insan bağlantı bildirimi arayüzü taslağı. İnsan bildirimleri ve önerileri özgün dillerini korur; iki dilli onay bekleniyor."
};

@Component({
  selector: 'app-authority-links', imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="link-title">
      <h1 id="link-title">{{ t("Human link reports and separate destination recovery review") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish human link-report interface draft in local development. Human reports and proposals retain their original language; bilingual approval is pending.") }}</p> }
      <p>{{ t("Organization") }} <span lang="en">{{ organizationId }}</span> {{ t("· project") }} <span lang="en">{{ projectId }}</span>.
        <a [routerLink]="['/app/dashboard', organizationId, projectId]">{{ t("Return to project evidence") }}</a> ·
        <a [routerLink]="['/app/authority-prospects', organizationId, projectId]">{{ t("Research-quote prospects") }}</a> ·
        <a [routerLink]="['/app/authority-link-sources', organizationId, projectId]">{{ t("Separately request selected static-source verification") }}</a> ·
        <a [routerLink]="['/app/actions', organizationId, projectId]">{{ t("Separately approve site actions and inspect technical follow-up") }}</a></p>
      <p>{{ t("External links are independent customer reports, not independently verified crawl or index observations. Even a declared complete-document absence does not prove an unlinked mention or lost link. Own-target HTTP evidence is dated and separate; 404/410 supports useful-destination review, not a current broken inbound-link claim.") }}</p>
      <p>{{ t("No automatic fetch, AI draft, link creation or sending. Supply no identities, secrets or restricted provider copies. Independent use/storage declarations cover private export, 90-day retained access after lapse, active deletion within 30 days of closure/retention expiry and up to 35-day backup rotation after active deletion.") }}</p>
      @if (loading()) { <p role="status">{{ t("Loading current target candidates and private human review history.") }}</p> }
      @if (error()) { <p role="alert" [attr.lang]="t(error()) === error() ? 'en' : uiLanguage()">{{ t(error()) }}</p> }
      @if (message()) { <p role="status" [attr.lang]="t(message()) === message() ? 'en' : uiLanguage()">{{ t(message()) }}</p> }
      @if (!context() && !pending() && !loading()) { <button type="button" (click)="load()" [disabled]="busy()">{{ t("Reload current project") }}</button> }
      @if (pending()) {
        <p>{{ t("The exact save outcome is uncertain. Command and target/recovery snapshots are frozen in component memory. No automatic replay.") }}</p>
        <button type="button" (click)="reconcile()" [disabled]="busy()">{{ t("Check uncertain save") }}</button>
        @if (notFound()) { <button type="button" (click)="retry()" [disabled]="busy()">{{ t("Retry same exact command after current checks") }}</button> }
      }
      @if (context(); as info) {
        <button type="button" (click)="load()" [disabled]="busy() || !!pending()">{{ t("Refresh current authority and history") }}</button>
        <p>{{ t("Current flags are as of refresh. Every command rechecks scope, source actors, assignee and retention on the server.") }}</p>
        @if (info.has_more) { <p>{{ t("Only the latest 50 link reviews are shown.") }}</p> }
        @if (!info.reviews.length) { <p>{{ t("No human link reviews recorded for this project.") }}</p> }
        <ul [attr.aria-label]="t('Latest human link reviews')">
          @for (row of info.reviews; track row.link_id) {
            <li><span lang="en">{{ row.proposal.action }}</span> {{ t("· assignee") }} <span lang="en">{{ row.assignee_id }}</span> {{ t("· revision") }} <span lang="en">{{ row.revision }}</span> · <span lang="en">{{ row.state }}</span> ·
              {{ row.source_current ? t("Current authority at refresh") : t("Stale/unavailable authority") }}
              <button type="button" (click)="inspect(row.link_id)" [disabled]="busy() || !!pending()">{{ t("Inspect exact source, target and history") }}</button></li>
          }
        </ul>
        @if (selected(); as row) {
          <section aria-labelledby="link-selected-title">
            <h2 id="link-selected-title">{{ t("Exact human revision") }} <span lang="en">{{ row.revision }}</span> · <span lang="en">{{ row.state }}</span></h2>
            <h3>{{ t("Original customer-reported external source") }}</h3>
            <p><a [href]="safeUrl(row.intake.source_url)" target="_blank" rel="noopener noreferrer"><span lang="">{{ row.intake.source_url }}</span></a> {{ t("· original aware observation date") }} <span lang="en">{{ row.intake.observed_at }}</span> {{ t("· reference") }} <span lang="en">{{ row.intake.observation_reference }}</span>.</p>
            <p><span lang="en">{{ row.intake.status }}</span> · <span lang="en">{{ row.intake.surface }}</span> · <span lang="en">{{ row.intake.coverage }}</span>{{ t(". Independent external verification and lost/unlinked links remain unestablished.") }}</p>
            <pre>{{ t("Literal absolute href:") }} <span [attr.lang]="row.intake.href ? '' : uiLanguage()">{{ row.intake.href || t("Absent; not seen/unavailable is not loss") }}</span>
{{ t("Anchor text:") }} <span [attr.lang]="row.intake.anchor_text ? '' : uiLanguage()">{{ row.intake.anchor_text || t("Absent") }}</span>
{{ t("Rel:") }} <span [attr.lang]="row.intake.rel ? '' : uiLanguage()">{{ row.intake.rel || t("Absent") }}</span>
{{ t("Human evidence note:") }} <span lang="">{{ row.intake.evidence_note }}</span></pre>
            <details><summary>{{ t("Exact original report and rights declarations (not legal verification)") }}</summary><pre><span lang="en">{{ json(row.intake) }}</span></pre></details>
            <h3>{{ t("Separate dated own-target HTTP evidence") }}</h3>
            <p><a [href]="safeUrl(row.intake.target_url)" target="_blank" rel="noopener noreferrer"><span lang="">{{ row.intake.target_url }}</span></a> {{ t("· observed") }} <span lang="en">{{ row.target_evidence.observed_at }}</span> {{ t("· HTTP") }} <span [attr.lang]="row.target_evidence.status_code === null || row.target_evidence.status_code === undefined ? uiLanguage() : 'en'">{{ row.target_evidence.status_code ?? t("Unavailable") }}</span> · <span lang="en">{{ row.target_evidence.state }}</span>.</p>
            <p>{{ t("Private body readback:") }} <span lang="en">{{ row.target_evidence.raw_body_readback }}</span>{{ t(". Content date") }} <span lang="en">{{ row.target_evidence.content_observed_at }}</span>{{ t("; 304 reuse is not a newly observed success. Whole-site coverage, current usefulness and external link recovery remain unestablished.") }}</p>
            <details><summary>{{ t("Exact target verification/configuration, redirects, body digest and crawl coverage") }}</summary><pre><span lang="en">{{ json(row.target_evidence) }}</span></pre></details>
            @if (row.recovery_action_review_id) {
              <h3>{{ t("Genuine separate own-page recovery handoff") }}</h3>
              <p>{{ t("Existing page-action review") }} <span lang="en">{{ row.recovery_action_review_id }}</span>{{ t(". This human link-review approval never approves or executes a website change. Use the separately accepted page action and its dated technical follow-up; that is not independent external link-recovery proof.") }}</p>
              <details><summary>{{ t("Exact diagnostic, Finding, Opportunity and independently approved page-action evidence") }}</summary><pre><span lang="en">{{ json(row.recovery_evidence) }}</span></pre></details>
            }
            <h3>{{ t("Human relevance and exact proposal") }}</h3><pre><span lang="">{{ row.proposal.relevance }}</span></pre>
            <p><span lang="en">{{ row.proposal.action }}</span> {{ t("· assignee") }} <span lang="en">{{ row.assignee_id }}</span> {{ t("· separate manual outreach permission declared:") }}
              {{ row.proposal.outreach_permission ? t("Yes; user attestation only") : t("No") }}.</p>
            <pre><span [attr.lang]="row.proposal.draft_text ? '' : uiLanguage()">{{ row.proposal.draft_text || t("Absent; no draft generated") }}</span></pre>
            <p><span lang="">{{ row.reason }}</span> · {{ row.effective_approval ? t("Exact human approval current at refresh") : t("No current effective approval") }} {{ t("· approved") }} <span [attr.lang]="row.approved_at ? 'en' : uiLanguage()">{{ row.approved_at || t("Absent") }}</span>.</p>
            @if (!row.source_current) { <p>{{ t("Source/reviewer/assignee authority is stale. New review, approval and manual activity reporting are denied.") }}</p> }
            @if (row.executed_at) { <p>{{ t("Actual manual activity reported") }} <span lang="en">{{ row.executed_at }}</span>: <span lang="">{{ row.execution_note }}</span>{{ t(". Customer-reported, not independently verified or a website execution.") }}</p> }
            @if (info.can_review && row.source_current && row.is_latest && !pending()) {
              @if (['draft', 'review', 'approved'].includes(row.state)) {
                <form (submit)="decide($event, row.state === 'draft' ? 'review' : row.state === 'review' ? 'approved' : 'reported')">
                  <fieldset [disabled]="busy()"><legend>{{ t("Separate exact human decision") }}</legend>
                    <label for="link-decision-reason">{{ t("Human decision reason") }}</label><textarea lang="" id="link-decision-reason" name="reason" maxlength="500" required></textarea>
                    <label><input name="exact" type="checkbox" required />{{ t("I reviewed the unchanged original report, own-target evidence, separate recovery handoff, proposal and assignee of revision") }} <span lang="en">{{ row.revision }}</span>{{ t(". Approval does not send or change the site.") }}</label>
                    @if (row.state === 'approved') {
                      <label for="link-executed">{{ t("Actual manual activity date/time (browser-local timezone, after approval)") }}</label><input lang="en" id="link-executed" name="executed_at" type="datetime-local" required />
                      <label for="link-execution-note">{{ t("Actual manual activity note, without private identities") }}</label><textarea lang="" id="link-execution-note" name="execution_note" maxlength="500" required></textarea>
                    }
                    <button type="submit" [disabled]="!canAdvance(row)">{{ row.state === 'draft' ? t("Send exact human draft to review") : row.state === 'review' ? t("Approve exact reviewed human activity") : t("Record actual manual activity only") }}</button>
                  </fieldset>
                </form>
                <form (submit)="decide($event, 'dismissed')"><fieldset [disabled]="busy()"><legend>{{ t("Human dismissal") }}</legend>
                  <label for="link-dismiss-reason">{{ t("Dismissal reason") }}</label><textarea lang="" id="link-dismiss-reason" name="reason" maxlength="500" required></textarea>
                  <label><input name="exact" type="checkbox" required />{{ t("Dismiss this exact link candidate; approval will be absent.") }}</label>
                  <button type="submit">{{ t("Dismiss without activity") }}</button>
                </fieldset></form>
              }
            }
            @if (info.can_review && row.is_latest && !pending()) { <button type="button" (click)="edit(row)" [disabled]="busy()">{{ t("Correct or reopen as a new unapproved draft") }}</button> }
          </section>
        }
        @if (historyRows().length) {
          <details><summary>{{ t("Immutable source/target/proposal/assignee/approval/activity history (newest 20)") }}</summary>
            <ol>@for (row of historyRows(); track row.id) {
              <li>{{ t("Revision") }} <span lang="en">{{ row.revision }}</span> · <span lang="en">{{ row.created_at }}</span> · <span lang="en">{{ row.state }}</span> {{ t("· assignee") }} <span lang="en">{{ row.assignee_id }}</span> · <span lang="">{{ row.reason }}</span>.
                <p>{{ row.source_current ? t("Current authority at refresh") : t("Stale authority") }} {{ t("· approval") }} <span [attr.lang]="row.approved_at ? 'en' : uiLanguage()">{{ row.approved_at || t("Absent") }}</span> · <span lang="en">{{ row.execution_state }}</span> · <span [attr.lang]="row.executed_at ? 'en' : uiLanguage()">{{ row.executed_at || t("No activity date") }}</span> · <span lang="">{{ row.execution_note }}</span>.</p>
                <pre><span lang="en">{{ json({ report: row.intake, target: row.target_evidence, proposal: row.proposal, recovery: row.recovery_evidence }) }}</span></pre>
              </li>
            }</ol>@if (historyMore()) { <p>{{ t("Older history exists; this bounded view is incomplete.") }}</p> }
          </details>
        }
        @if (info.can_review && !pending()) {
          <h2>{{ editing() ? t("New unapproved correction; earlier approval never carries forward") : t("Record one independent human link report") }}</h2>
          @if (!info.targets.length || !info.assignees.length) { <p>{{ t("No current verified own-target crawl and eligible assignee available. Inspect source configuration and crawl evidence first; nothing is fetched here.") }}</p> }
          @else {
            @if (info.candidates_has_more) { <p>{{ t("Only bounded recent target/recovery/assignee candidates are shown; inventory is partial.") }}</p> }
            <form (submit)="saveDraft($event)"><fieldset [disabled]="busy()"><legend>{{ t("Original external report and separate current own-target evidence") }}</legend>
              <label for="link-target">{{ t("Actual current own-target crawl observation") }}</label>
              <select id="link-target" name="target" required [value]="targetSelection()" (change)="targetSelection.set($any($event.target).value)">
                <option value="">{{ t("Choose actual stored target") }}</option>
                @for (row of info.targets; track row.crawl_page_id) { <option lang="" [value]="row.crawl_page_id">{{ row.requested_url }} · {{ row.observed_at }} {{ t("· HTTP") }} {{ row.status_code ?? t("Unavailable") }}</option> }
              </select>
              @if (chosenTarget(); as target) { <details><summary>{{ t("Selected exact dated HTTP/verification/configuration/coverage snapshot") }}</summary><pre><span lang="en">{{ json(target) }}</span></pre></details> }
              <label for="link-reference">{{ t("Opaque independent observation reference (no personal identifier)") }}</label><input lang="en" id="link-reference" name="observation_reference" maxlength="64" pattern="[A-Za-z0-9][A-Za-z0-9._-]{0,63}" required [value]="editing()?.intake?.observation_reference || ''" />
              <label for="link-source">{{ t("Original external HTTPS source URL (no query, fragment or credentials)") }}</label><input lang="" id="link-source" name="source_url" type="url" maxlength="1024" required [value]="editing()?.intake?.source_url || ''" />
              <label for="link-observed">{{ t("Original aware observation date, including offset (preserved unchanged, e.g. 2026-01-01T12:00:00+03:00)") }}</label><input lang="en" id="link-observed" name="observed_at" type="text" maxlength="64" required [value]="editing()?.intake?.observed_at || ''" />
              <label for="link-status">{{ t("Customer-reported link state") }}</label><select id="link-status" name="status" [value]="editing()?.intake?.status || 'observed'">
                <option value="observed">{{ t("Literal absolute href observed") }}</option><option value="not_seen_in_inspected_page">{{ t("Not seen in inspected page (not lost/unlinked proof)") }}</option><option value="unavailable">{{ t("Unavailable") }}</option>
              </select>
              <label for="link-coverage">{{ t("Actual human-reported document coverage") }}</label><select id="link-coverage" name="coverage" [value]="editing()?.intake?.coverage || 'partial_page'">
                <option value="partial_page">{{ t("Partial page") }}</option><option value="complete_document_customer_reported">{{ t("Complete document, customer-reported only") }}</option><option value="unavailable">{{ t("Unavailable") }}</option>
              </select>
              <label for="link-surface">{{ t("Inspected document surface") }}</label><select id="link-surface" name="surface" [value]="editing()?.intake?.surface || 'html_document'">
                <option value="html_document">{{ t("HTML document") }}</option><option value="rendered_document">{{ t("Rendered document") }}</option><option value="unknown">{{ t("Unknown (unavailable only)") }}</option>
              </select>
              <p>{{ t("Observed href must be the unchanged literal absolute selected target. For not-seen/unavailable reports, leave href/anchor/rel empty. Relative/base-dependent hrefs are unsupported.") }}</p>
              <label for="link-href">{{ t("Literal absolute href, if observed") }}</label><input lang="" id="link-href" name="href" maxlength="1024" [value]="editing()?.intake?.href || ''" />
              <label for="link-anchor">{{ t("Literal anchor text, if observed") }}</label><textarea lang="" id="link-anchor" name="anchor_text" maxlength="240" [value]="editing()?.intake?.anchor_text || ''"></textarea>
              <label for="link-rel">{{ t("Literal rel, if observed") }}</label><input lang="en" id="link-rel" name="rel" maxlength="100" [value]="editing()?.intake?.rel || ''" />
              <label for="link-evidence">{{ t("Minimized human evidence note and limitations") }}</label><textarea lang="" id="link-evidence" name="evidence_note" maxlength="500" required [value]="editing()?.intake?.evidence_note || ''"></textarea>
              <label for="link-action">{{ t("Human proposed activity") }}</label><select id="link-action" name="action" [value]="actionSelection()" (change)="actionSelection.set($any($event.target).value)">
                <option value="verify_source">{{ t("Human source verification review") }}</option><option value="request_source_correction">{{ t("Request source correction (separate manual outreach permission)") }}</option><option value="review_target_recovery">{{ t("Review useful-target recovery handoff (not website approval)") }}</option>
              </select>
              @if (actionSelection() === 'review_target_recovery') {
                <label for="link-recovery">{{ t("Genuine existing exact-target page-action revision") }}</label><select id="link-recovery" name="recovery_action_review_id" required>
                  <option value="">{{ t("Choose separately supported page action") }}</option>
                  @for (row of recoveryCandidates(); track row.action_review_id) { <option [value]="row.action_review_id" [selected]="row.action_review_id === editing()?.recovery_action_review_id">{{ t("Page action") }} {{ row.action_review_id }} · {{ row.action_kind }} · {{ row.state }} {{ t("· separate site approval") }} {{ row.site_approval_review_id || t("Absent") }}</option> }
                </select><p>{{ t("No candidate means recovery handoff is unavailable. No Finding, Opportunity or page action is fabricated here.") }}</p>
              }
              <label for="link-relevance">{{ t("Human relevance and useful-destination rationale") }}</label><textarea lang="" id="link-relevance" name="relevance" maxlength="500" required [value]="editing()?.proposal?.relevance || ''"></textarea>
              <label for="link-assignee">{{ t("Eligible project assignee") }}</label><select id="link-assignee" name="assignee_id" required>
                @for (row of info.assignees; track row.id) { <option [value]="row.id" [selected]="row.id === editing()?.assignee_id">{{ t("Project user") }} {{ row.id }}</option> }
              </select>
              <label for="link-draft">{{ t("Optional exact human activity draft, without identities or secrets") }}</label><textarea lang="" id="link-draft" name="draft_text" maxlength="2000" [value]="editing()?.proposal?.draft_text || ''"></textarea>
              <label for="link-reason">{{ t("Human draft/correction reason") }}</label><textarea lang="" id="link-reason" name="reason" maxlength="500" required></textarea>
              <label><input name="use_permission" type="checkbox" required />{{ t("I independently have permission to use this evidence for this proposal.") }}</label>
              <label><input name="storage_permission" type="checkbox" required />{{ t("I independently have permission to store it under the disclosed private export/deletion/backup policy.") }}</label>
              <label><input name="not_restricted_provider_copy" type="checkbox" required />{{ t("This is not copied restricted or response-only provider content.") }}</label>
              <label><input name="no_personal_payload" type="checkbox" required />{{ t("This minimized report has no personal payload, contact identities or secrets.") }}</label>
              <label><input name="outreach_permission" type="checkbox" />{{ t("I separately have permission for proposed manual outreach. A reported link does not grant it.") }}</label>
              <button type="submit" [disabled]="!chosenTarget()">{{ t("Save new unapproved human draft revision") }}</button>
              @if (editing()) { <button type="button" (click)="editing.set(null); targetSelection.set(''); actionSelection.set('verify_source')">{{ t("Cancel correction") }}</button> }
            </fieldset></form>
          }
        } @else if (!info.can_review) { <p>{{ t("Read-only history. Current verified owner/admin authority is required for intake and every human decision.") }}</p> }
      }
    </section>
  `,
  styles: `form, fieldset { display: grid; gap: .6rem; } form { max-width: 48rem; margin-block: 1rem; }
    pre { white-space: pre-wrap; overflow-wrap: anywhere; } li { margin-block: 1rem; }
    input, textarea, select { min-width: 0; max-width: 100%; }`,
})
export class AuthorityLinks implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  t(text: string) { return this.uiLanguage() === 'tr' ? authorityLinksTurkish[text] ?? text : text; }
  readonly context = signal<Context | null>(null); readonly selected = signal<Review | null>(null);
  readonly editing = signal<Review | null>(null); readonly historyRows = signal<Review[]>([]); readonly historyMore = signal(false);
  readonly targetSelection = signal(''); readonly actionSelection = signal('verify_source');
  readonly loading = signal(false); readonly busy = signal(false); readonly error = signal(''); readonly message = signal('');
  readonly pending = signal<Pending | null>(null); readonly notFound = signal(false);
  protected organizationId = 0; protected projectId = 0; protected readonly safeUrl = safeUrl;
  private generation = 0; private selectionGeneration = 0;
  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi, private readonly destroyRef: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t('Private human link and recovery review')} — OrganicSEOOps`));
    destroyRef.onDestroy(() => { this.generation++; this.clear(); });
  }
  ngOnInit() {
    void this.loadProductLanguage();
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      this.generation++; this.clear(); this.busy.set(false); this.loading.set(false); this.error.set(''); this.message.set('');
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
  private clear() {
    this.context.set(null); this.selected.set(null); this.editing.set(null); this.historyRows.set([]); this.historyMore.set(false);
    this.pending.set(null); this.notFound.set(false); this.targetSelection.set(''); this.actionSelection.set('verify_source'); this.selectionGeneration++;
  }
  chosenTarget() { return this.context()?.targets.find((row) => String(row.crawl_page_id) === this.targetSelection()); }
  recoveryCandidates() { const target = this.chosenTarget(); return this.context()?.recovery_actions.filter((row) => same(row.target_evidence, target)) || []; }
  canAdvance(row: Review) { return !!row.proposal.draft_text.trim() && (row.proposal.action !== 'request_source_correction'
    || row.intake.status === 'observed' && row.proposal.outreach_permission); }
  private readContext(response: ApiResult): Context {
    const info = response.body as unknown as Context;
    if (response.status !== 200 || info.organization_id !== this.organizationId || info.project_id !== this.projectId
      || info.policy !== POLICY || typeof info.can_review !== 'boolean' || typeof info.candidates_has_more !== 'boolean'
      || info.source_basis !== 'actual_own_target_http_and_separate_page_action_no_external_report'
      || info.sending !== 'unavailable' || info.independent_external_verification !== 'unavailable' || info.lost_unlinked_links !== 'not_established'
      || !Array.isArray(info.targets) || info.targets.length > 20 || !info.targets.every((row) => isTarget(row, this.projectId))
      || !Array.isArray(info.recovery_actions) || info.recovery_actions.length > 20
      || !info.recovery_actions.every((row) => isRecovery(row, this.projectId) && info.targets.some((target) => same(target, row.target_evidence)))
      || !Array.isArray(info.assignees) || info.assignees.length > 20 || !info.assignees.every((row) => !!row && positive(row.id))
      || !Array.isArray(info.reviews) || info.reviews.length > 50 || !info.reviews.every((row) => isReview(row, this.projectId))
      || typeof info.has_more !== 'boolean') throw new Error();
    return info;
  }
  async load() {
    if (this.busy() || this.pending()) return;
    const generation = ++this.generation; this.clear(); this.loading.set(true); this.error.set('');
    try { const response = await this.api.authorityLinks(this.organizationId, this.projectId);
      if (generation === this.generation) this.context.set(this.readContext(response));
    } catch { if (generation === this.generation) this.error.set('Link history or current project/session authority is unavailable.'); }
    finally { if (generation === this.generation) this.loading.set(false); }
  }
  async inspect(id: string) {
    if (this.busy() || this.pending()) return;
    const generation = this.generation; const selection = ++this.selectionGeneration;
    this.selected.set(null); this.historyRows.set([]); this.editing.set(null); this.targetSelection.set(''); this.message.set('');
    try {
      const response = await this.api.authorityLinks(this.organizationId, this.projectId, undefined, id);
      if (generation !== this.generation || selection !== this.selectionGeneration) return;
      const info = this.readContext(response);
      if (!info.reviews.length || info.reviews.length > 20 || info.reviews.some((row) => row.link_id !== id) || !info.reviews[0].is_latest) throw new Error();
      const previous = this.context();
      this.context.set(previous ? { ...info, reviews: previous.reviews, has_more: previous.has_more } : info);
      this.selected.set(info.reviews[0]); this.historyRows.set(info.reviews); this.historyMore.set(info.has_more);
    } catch { if (generation === this.generation && selection === this.selectionGeneration) {
      this.context.set(null); this.message.set('Exact history is unavailable; refresh before another decision.');
    } }
  }
  edit(row: Review) { if (!this.busy() && !this.pending() && this.context()?.can_review && row.is_latest) {
    this.editing.set(row); this.targetSelection.set(String(row.target_evidence.crawl_page_id)); this.actionSelection.set(row.proposal.action);
  } }
  saveDraft(event: Event) {
    event.preventDefault(); const form = event.target as HTMLFormElement; const info = this.context();
    if (this.busy() || this.pending() || !info?.can_review || !form.reportValidity()) return;
    const fields = new FormData(form); const target = info.targets.find((row) => String(row.crawl_page_id) === fields.get('target'));
    if (!target) return;
    const text = (key: string) => String(fields.get(key) || '');
    const intake: Intake = { policy: POLICY, source_kind: 'customer_manual_link_observation', origin: target.origin,
      configuration_revision: target.configuration_revision, crawl_page_id: target.crawl_page_id, target_url: target.requested_url,
      observation_reference: text('observation_reference'), source_url: text('source_url'), observed_at: text('observed_at'),
      status: text('status'), coverage: text('coverage'), surface: text('surface'), href: text('href'), anchor_text: text('anchor_text'),
      rel: text('rel'), evidence_note: text('evidence_note'), use_permission: fields.has('use_permission'), storage_permission: fields.has('storage_permission'),
      not_restricted_provider_copy: fields.has('not_restricted_provider_copy'), no_personal_payload: fields.has('no_personal_payload') };
    const proposal: Proposal = { action: text('action'), relevance: text('relevance'), draft_text: text('draft_text'), outreach_permission: fields.has('outreach_permission') };
    const recovery = proposal.action === 'review_target_recovery'
      ? info.recovery_actions.find((row) => row.action_review_id === Number(fields.get('recovery_action_review_id')) && same(row.target_evidence, target)) : undefined;
    const assignee = Number(fields.get('assignee_id'));
    if (!isIntake(intake, target) || !isProposal(proposal) || !info.assignees.some((row) => row.id === assignee)
      || proposal.action === 'review_target_recovery' && (!recovery || intake.status !== 'observed')) {
      this.error.set('Choose literal independent evidence, original aware date, matching current target/recovery, eligible assignee and affirmative rights. Not-seen/unavailable requires empty href/anchor/rel.'); return;
    }
    const row = this.editing(); const data: Record<string, unknown> = { request_key: crypto.randomUUID(), intake, proposal,
      assignee_id: assignee, recovery_action_review_id: recovery?.action_review_id || null, state: 'draft', reason: text('reason'), executed_at: null, execution_note: '' };
    if (row) data['expected_revision'] = row.revision;
    void this.send(structuredClone({ data, linkId: row?.link_id, target, recovery: recovery || {} }));
  }
  decide(event: Event, state: string) {
    event.preventDefault(); const form = event.target as HTMLFormElement; const row = this.selected();
    if (this.busy() || this.pending() || !this.context()?.can_review || !row?.source_current || !row.is_latest || !form.reportValidity()) return;
    const allowed: Record<string, string[]> = { draft: ['review', 'dismissed'], review: ['approved', 'dismissed'], approved: ['reported', 'dismissed'] };
    const fields = new FormData(form);
    if (!fields.has('exact') || !allowed[row.state]?.includes(state) || state !== 'dismissed' && !this.canAdvance(row)) return;
    const date = state === 'reported' ? new Date(String(fields.get('executed_at'))) : null;
    if (date && (!Number.isFinite(date.getTime()) || date.getTime() > Date.now() || !row.approved_at || date.getTime() < Date.parse(row.approved_at))) {
      this.error.set('Report the actual nonfuture manual activity time after exact human approval.'); return;
    }
    void this.send(structuredClone({ linkId: row.link_id, target: row.target_evidence, recovery: row.recovery_evidence,
      data: { request_key: crypto.randomUUID(), intake: row.intake, proposal: row.proposal, assignee_id: row.assignee_id,
        recovery_action_review_id: row.recovery_action_review_id, expected_revision: row.revision, state,
        reason: String(fields.get('reason') || ''), executed_at: date?.toISOString() || null, execution_note: String(fields.get('execution_note') || '') } }));
  }
  private matchesCommand(row: Review, command: Pending) {
    return (!command.linkId || row.link_id === command.linkId) && row.revision === Number(command.data['expected_revision'] || 0) + 1
      && ['assignee_id', 'recovery_action_review_id', 'state', 'reason', 'execution_note'].every((key) =>
        (row as unknown as Record<string, unknown>)[key] === command.data[key])
      && (row.executed_at === command.data['executed_at'] || aware(row.executed_at) && aware(command.data['executed_at'])
        && Date.parse(row.executed_at) === Date.parse(command.data['executed_at']))
      && same(row.intake, command.data['intake']) && same(row.proposal, command.data['proposal'])
      && same(row.target_evidence, command.target) && same(row.recovery_evidence, command.recovery);
  }
  private candidatesMatch(info: Context, command: Pending) {
    return info.can_review && info.assignees.some((row) => row.id === command.data['assignee_id'])
      && info.targets.some((row) => same(row, command.target))
      && (command.data['recovery_action_review_id'] === null || info.recovery_actions.some((row) => same(row, command.recovery)));
  }
  private async send(command: Pending) {
    const generation = this.generation; this.selectionGeneration++; this.busy.set(true); this.error.set(''); this.message.set(''); this.notFound.set(false); this.pending.set(command);
    try {
      const response = await this.api.authorityLinks(this.organizationId, this.projectId, command.data, command.linkId);
      if (generation !== this.generation) return;
      if ([200, 201].includes(response.status) && response.body['organization_id'] === this.organizationId
        && response.body['project_id'] === this.projectId && isReview(response.body['review'], this.projectId) && this.matchesCommand(response.body['review'], command)) {
        this.pending.set(null); this.busy.set(false); await this.load();
        if (generation + 1 === this.generation) this.message.set('Exact human decision recorded. No source fetched, outreach sent or website changed.');
      } else if ([400, 401, 403, 404, 409, 413, 429].includes(response.status)) {
        this.clear(); this.error.set('Current authority, exact revision or fields were denied. Refresh before another decision.');
      } else this.message.set('Save outcome uncertain; inspect the exact request key before continuing.');
    } catch { if (generation === this.generation) this.message.set('Save outcome uncertain; inspect the exact request key before continuing.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  async reconcile() {
    const command = this.pending(); if (!command || this.busy()) return;
    const generation = this.generation; this.busy.set(true); this.notFound.set(false);
    try {
      const response = await this.api.authorityLinks(this.organizationId, this.projectId, undefined, undefined, String(command.data['request_key']));
      if (generation !== this.generation) return;
      const info = this.readContext(response);
      if (response.body['lookup'] === 'found' && info.reviews.length === 1 && this.matchesCommand(info.reviews[0], command)) {
        this.pending.set(null); this.busy.set(false); await this.load();
        if (generation + 1 === this.generation) this.message.set('Request reconciled from immutable history; no command replayed.');
      } else if (response.body['lookup'] === 'not_found' && !info.reviews.length && this.candidatesMatch(info, command)) {
        if (command.linkId) {
          const history = await this.api.authorityLinks(this.organizationId, this.projectId, undefined, command.linkId);
          if (generation !== this.generation) return;
          const current = this.readContext(history); const latest = current.reviews[0];
          if (!latest || latest.link_id !== command.linkId || !latest.is_latest || latest.revision !== command.data['expected_revision']
            || !this.candidatesMatch(current, command) || command.data['state'] !== 'draft' && !latest.source_current) throw new Error();
        }
        this.context.set(info); this.notFound.set(true); this.message.set('No decision found. Current exact target/recovery/assignee/role match; a deliberate same-command retry is available.');
      } else throw new Error();
    } catch { if (generation === this.generation) {
      this.context.set(null); this.selected.set(null); this.editing.set(null); this.historyRows.set([]); this.targetSelection.set(''); this.notFound.set(false);
      this.message.set('Outcome or matching current authority remains unavailable. No command replayed.');
    } }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  async retry() {
    const command = this.pending(); if (!command || !this.notFound() || this.busy()) return;
    const generation = this.generation;
    await this.reconcile();
    if (generation === this.generation && this.pending() === command && this.notFound() && this.context()
      && this.candidatesMatch(this.context()!, command)) await this.send(command);
  }
}
