import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, OnInit, computed, effect, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi, ApiResult } from '../account/account-api';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';

const POLICY = 'authority-human-prospect-v1';
type Source = { method: string; project_id: number; research_job_id: number; source_index: number; artifact_id: number;
  step_id: number; configuration_revision: number; requested_url: string; url: string; title: string; retrieved_at: string;
  original_response_sha256: string; source_size_bytes: number; excerpt: string; excerpt_truncated: boolean; coverage: string;
  facts: string; link_structure: string; inbound_unlinked_lost_links: string; publication_time: null; outreach_permission: string };
type Intake = { policy: string; research_job_id: number; source_index: number; quote: string; relevance: string;
  proposed_action: string; target_url: string; draft_text: string; use_permission: boolean; storage_permission: boolean; outreach_permission: boolean };
type Review = { id: number; prospect_id: string; project_id: number; revision: number; state: string; intake: Intake;
  source_evidence: Source; assignee_id: number; reason: string; source_current: boolean; is_latest: boolean;
  effective_approval: boolean; approved_at: string | null; executed_at: string | null; execution_note: string; created_at: string;
  scope: string; execution_state: string };
type Context = { organization_id: number; project_id: number; can_review: boolean; policy: string;
  sources: Source[]; assignees: { id: number }[]; sources_has_more: boolean; reviews: Review[]; has_more: boolean };
type Pending = { data: Record<string, unknown>; prospectId?: string };
const positive = (value: unknown) => Number.isSafeInteger(value) && Number(value) > 0;
const sourceKey = (row: Source) => `${row.research_job_id}:${row.source_index}`;

function safeUrl(value: string) {
  try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password
    && !url.search && !url.hash && (!url.port || url.port === '443') ? url.href : ''; }
  catch { return ''; }
}
function isSource(value: unknown, project: number): value is Source {
  if (!value || typeof value !== 'object') return false;
  const row = value as Source;
  return row.method === 'authority-research-evidence-v1' && row.project_id === project && positive(row.research_job_id)
    && Number.isSafeInteger(row.source_index) && row.source_index >= 0 && row.source_index < 5
    && positive(row.artifact_id) && positive(row.step_id) && positive(row.source_size_bytes)
    && Number.isSafeInteger(row.configuration_revision) && typeof row.excerpt_truncated === 'boolean'
    && ['requested_url', 'url', 'title', 'retrieved_at', 'original_response_sha256', 'excerpt']
      .every((key) => typeof (row as unknown as Record<string, unknown>)[key] === 'string')
    && !!safeUrl(row.url) && !!safeUrl(row.requested_url) && /^[a-f0-9]{64}$/.test(row.original_response_sha256)
    && row.coverage === 'selected_bounded_public_page_text_only' && row.facts === 'unverified'
    && row.link_structure === 'unavailable_href_rel_not_retained' && row.inbound_unlinked_lost_links === 'not_established'
    && row.publication_time === null && row.outreach_permission === 'not_established';
}
function isReview(value: unknown, project: number): value is Review {
  if (!value || typeof value !== 'object') return false;
  const row = value as Review; const data = row.intake;
  return positive(row.id) && /^[0-9a-f-]{36}$/.test(row.prospect_id) && row.project_id === project
    && positive(row.revision) && positive(row.assignee_id) && ['draft', 'review', 'approved', 'reported', 'dismissed'].includes(row.state)
    && ['reason', 'execution_note', 'created_at'].every((key) => typeof (row as unknown as Record<string, unknown>)[key] === 'string')
    && ['source_current', 'is_latest', 'effective_approval'].every((key) => typeof (row as unknown as Record<string, unknown>)[key] === 'boolean')
    && (row.approved_at === null || typeof row.approved_at === 'string') && (row.executed_at === null || typeof row.executed_at === 'string')
    && row.scope === 'historical_human_prospect_not_link_proof_or_current_use_permission'
    && ['not_reported', 'customer_reported_not_verified'].includes(row.execution_state)
    && isSource(row.source_evidence, project) && !!data && typeof data === 'object' && data.policy === POLICY
    && data.research_job_id === row.source_evidence.research_job_id && data.source_index === row.source_evidence.source_index
    && data.target_url === row.source_evidence.url && data.use_permission === true && data.storage_permission === true
    && typeof data.outreach_permission === 'boolean' && ['partnership', 'mention', 'digital_pr'].includes(data.proposed_action)
    && ['quote', 'relevance', 'draft_text'].every((key) => typeof (data as unknown as Record<string, unknown>)[key] === 'string')
    && !!data.quote.trim() && row.source_evidence.excerpt.includes(data.quote)
    && (!row.effective_approval || row.is_latest && row.source_current && ['approved', 'reported'].includes(row.state));
}

const authorityProspectsTurkish: Record<string, string> = {
  "Private human authority prospects": "Özel insan otorite adayları",
  "Human authority prospects from stored research": "Kayıtlı araştırmadan insanın belirlediği otorite fırsatları",
  "Unreviewed Turkish authority-prospect interface draft in local development. Human proposals and source excerpts retain their original language; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe otorite fırsatı arayüzü taslağı. İnsan önerileri ve kaynak alıntıları özgün dillerini korur; iki dilli onay bekleniyor.",
  "Return to project evidence": "Proje kanıtlarına dönün",
  "Inspect original research": "Özgün araştırmayı inceleyin",
  "Organization": "Kuruluş",
  "· project": "· proje",
  ". Exact stored public-page quotes support human partnership, mention and digital-PR prospects. Relevance is your judgment. Text does not prove inbound, unlinked or lost links, publication age, complete coverage or permission to contact anyone.": ". Kayıtlı herkese açık sayfalardan tam alıntılar; insanın belirlediği ortaklık, bahsedilme ve dijital PR fırsatlarını destekler. İlgililik sizin değerlendirmenizdir. Metin, gelen, bağlantısız veya kaybolmuş bağlantıları, yayın yaşını, tam kapsamı veya birileriyle iletişim kurma iznini kanıtlamaz.",
  "Review separate independent human link reports and actual own-target recovery evidence": "Ayrı bağımsız insan bağlantı bildirimlerini ve kendi hedefinize ait gerçek kurtarma kanıtını inceleyin",
  ". Research text is never imported as link proof.": ". Araştırma metni hiçbir zaman bağlantı kanıtı olarak içe aktarılmaz.",
  "No automatic fetch, AI draft, link creation or sending. Supply no contact identities, account details or secrets. Private customer records follow 90-day retained access after lapse, deletion within 30 days of closure/retention expiry, and up to 35-day backup rotation after active deletion. Declare independent rights to use and store evidence under that policy.": "Otomatik getirme, yapay zekâ taslağı, bağlantı oluşturma veya gönderim yoktur. İletişim kimlikleri, hesap bilgileri veya sırlar eklemeyin. Özel müşteri kayıtları, erişim süresi bittikten sonra 90 günlük saklanan erişime, kapatma/saklama süresi bitiminden sonraki 30 gün içinde silmeye ve aktif silmeden sonra en fazla 35 günlük yedek rotasyonuna tabidir. Bu politika kapsamında kanıtı kullanma ve saklama konusundaki bağımsız haklarınızı beyan edin.",
  "Loading current sources and private prospect history.": "Güncel kaynaklar ve özel fırsat geçmişi yükleniyor.",
  "Reload current project": "Güncel projeyi yeniden yükleyin",
  "The exact save outcome is uncertain. This command is frozen in component memory; no automatic replay.": "Tam kayıt sonucu belirsiz. Bu komut bileşen belleğinde sabitlenir; otomatik yeniden yürütme yoktur.",
  "Check uncertain save": "Belirsiz kaydı kontrol edin",
  "Retry same exact command": "Aynı tam komutu tekrar deneyin",
  "Refresh current authority and history": "Güncel yetkiyi ve geçmişi yenileyin",
  "Current flags are as of refresh. The server rechecks source, actor, assignee, scope and retention on every decision. Approval is separate from actual manual execution.": "Güncel göstergeler yenileme anına aittir. Sunucu her kararda kaynağı, işlemi yapanı, atanan kişiyi, kapsamı ve saklamayı yeniden kontrol eder. Onay, gerçekleşmiş manuel uygulamadan ayrıdır.",
  "Only the latest 50 prospects are shown.": "Yalnızca en son 50 fırsat gösterilir.",
  "No human prospects recorded for this project.": "Bu proje için insanın belirlediği fırsat kaydedilmedi.",
  "Latest human authority prospects": "İnsanın belirlediği son otorite fırsatları",
  "· assignee": "· atanan kişi",
  "· revision": "· sürüm",
  "Inspect exact source, draft and history": "Tam kaynağı, taslağı ve geçmişi inceleyin",
  "Exact prospect revision": "Tam fırsat sürümü",
  "Research": "Araştırma",
  "· source index": "· kaynak indeksi",
  "· artifact": "· dosya",
  "· retrieved": "· alındı",
  "Exact stored quote": "Tam kayıtlı alıntı",
  "Human relevance and proposal": "İnsan ilgililik değerlendirmesi ve önerisi",
  "· separate outreach permission declared:": "· ayrı iletişim izni beyan edildi:",
  "Exact human draft": "Tam insan taslağı",
  "· approved": "· onaylandı",
  "Source/reviewer/assignee authority is stale. New review, approval and manual-use reporting are denied.": "Kaynak/inceleyen/atanan kişi yetkisi eskidir. Yeni inceleme, onay ve manuel kullanım bildirimi reddedilir.",
  "Manual execution reported": "Manuel uygulama bildirildi",
  ". Not independently verified.": ". Bağımsız olarak doğrulanmadı.",
  "Human decision reason": "İnsan karar gerekçesi",
  "I reviewed the unchanged quote, source target, relevance, assignee and draft of revision": "Sürümün değişmemiş alıntısını, kaynak hedefini, ilgililiğini, atanan kişisini ve taslağını inceledim:",
  ". Approval does not send.": ". Onay gönderim yapmaz.",
  "Actual manual execution date/time (browser-local timezone; after approval)": "Gerçek manuel uygulama tarihi/saati (tarayıcının yerel saat dilimi; onaydan sonra)",
  "Actual manual execution note (no private identities)": "Gerçek manuel uygulama notu (özel kimlik bilgisi yok)",
  "Human dismissal reason": "İnsan reddetme gerekçesi",
  "Dismiss this exact prospect; approval will be absent.": "Bu fırsatın tamamını reddedin; onay bulunmayacaktır.",
  "Dismiss prospect without execution": "Uygulamadan fırsatı reddedin",
  "Correct or reopen as a new unapproved draft": "Yeni onaylanmamış taslak olarak düzeltin veya yeniden açın",
  "Immutable source, assignee, approval and execution history (newest 20)": "Değişmez kaynak, atanan kişi, onay ve uygulama geçmişi (en yeni 20)",
  "Revision": "Sürüm",
  "Human relevance:": "İnsan ilgililik değerlendirmesi:",
  "Exact draft:": "Tam taslak:",
  "Approval": "Onay",
  "Older history exists; this bounded view is incomplete.": "Daha eski geçmiş var; bu sınırlı görünüm eksiktir.",
  "No current stored research source and eligible assignee available. Inspect research/configuration first; no source is fetched here.": "Güncel kayıtlı araştırma kaynağı ve uygun atanan kişi kullanılamıyor. Önce araştırmayı/yapılandırmayı inceleyin; burada kaynak getirilmez.",
  "Only bounded recent source/assignee candidates are shown; inventory is partial.": "Yalnızca sınırlı son kaynak/atanan kişi adayları gösterilir; envanter kısmidir.",
  "Current actual source, human judgment and independent rights": "Güncel gerçek kaynak, insan değerlendirmesi ve bağımsız haklar",
  "Stored research source (target is this exact source page)": "Kayıtlı araştırma kaynağı (hedef bu kaynak sayfasının tamamıdır)",
  "Choose actual evidence": "Gerçek kanıt seçin",
  "· index": "· indeks",
  "· configuration": "· yapılandırma",
  "text.": "metin.",
  "Original response digest": "Özgün yanıt özeti",
  ". Facts, links, publication time and outreach permission remain unestablished.": ". Bilgiler, bağlantılar, yayın zamanı ve iletişim izni kanıtlanmış değildir.",
  "Exact quote from the stored excerpt": "Kayıtlı alıntıdan tam metin",
  "Human business relevance and evidence limitations": "İnsanın işletme ilgililik değerlendirmesi ve kanıt sınırlamaları",
  "Human proposed action (not verified link recovery)": "İnsanın önerdiği eylem (doğrulanmış bağlantı kurtarma değildir)",
  "Relevant partnership": "İlgili ortaklık",
  "Mention prospect (link state unknown)": "Bahsedilme fırsatı (bağlantı durumu bilinmiyor)",
  "Digital PR prospect": "Dijital PR fırsatı",
  "Eligible project assignee": "Uygun proje atanan kişisi",
  "Project user": "Proje kullanıcısı",
  "Optional human draft, without contact identities or secrets": "İsteğe bağlı insan taslağı, iletişim kimliği veya sır içermeden",
  "Human draft/correction reason": "İnsan taslak/düzeltme gerekçesi",
  "I independently have permission to use this evidence for this human proposal.": "Bu insan önerisi için kanıtı kullanmaya bağımsız iznim var.",
  "I independently have permission to store this evidence under the disclosed private export/deletion/backup policy.": "Bu kanıtı açıklanan özel dışa aktarma/silme/yedekleme politikası kapsamında saklamaya bağımsız iznim var.",
  "I independently have permission for the proposed manual outreach; the source quote alone does not grant it. Required before review/approval.": "Önerilen manuel iletişim için bağımsız iznim var; kaynak alıntısı tek başına bu izni vermez. İnceleme/onay öncesinde gereklidir.",
  "Save new unapproved human draft revision": "Yeni onaylanmamış insan taslak sürümünü kaydedin",
  "Cancel correction": "Düzeltmeyi iptal edin",
  "Read-only history. Current verified owner/admin authority is required for intake and every prospect decision.": "Salt okunur geçmiş. Girdi ve her fırsat kararı için güncel doğrulanmış sahip/yönetici yetkisi gereklidir.",
  "Current authority at refresh": "Yenileme anında güncel yetki",
  "Stale/unavailable authority": "Eski/kullanılamayan yetki",
  "Truncated excerpt; wider text unavailable": "Kesilmiş alıntı; daha geniş metin kullanılamıyor",
  "Selected bounded text only": "Yalnızca seçilen sınırlı metin",
  "Yes; user attestation, not independently verified": "Evet; kullanıcı beyanı, bağımsız olarak doğrulanmadı",
  "No": "Hayır",
  "Absent; no draft generated": "Yok; taslak üretilmedi",
  "Exact approval current at refresh": "Tam onay yenileme anında güncel",
  "No current effective approval": "Güncel geçerli onay yok",
  "Absent": "Yok",
  "Send exact draft to human review": "Tam taslağı insan incelemesine gönderin",
  "Approve exact reviewed draft": "İncelenen tam taslağı onaylayın",
  "Record actual manual execution only": "Yalnızca gerçek manuel uygulamayı kaydedin",
  "Stale authority": "Eski yetki",
  "New unapproved correction; earlier approval does not carry forward": "Yeni onaylanmamış düzeltme; önceki onay aktarılmaz",
  "Record one source-supported human prospect": "Kaynak destekli bir insan fırsatı kaydedin",
  "Truncated": "Kesilmiş",
  "Bounded selected": "Sınırlı seçilmiş",
  "Select an authorized organization and project.": "Yetkili bir kuruluş ve proje seçin.",
  "Prospect history or current project/session authority is unavailable.": "Fırsat geçmişi veya güncel proje/oturum yetkisi kullanılamıyor.",
  "Exact history is unavailable; refresh before another decision.": "Tam geçmiş kullanılamıyor; başka karar vermeden önce yenileyin.",
  "Choose an exact unchanged quote from the displayed stored excerpt.": "Gösterilen kayıtlı alıntıdan değişmemiş tam bir metin seçin.",
  "Human decision recorded. No source was fetched or outreach sent.": "İnsan kararı kaydedildi. Kaynak getirilmedi veya iletişim gönderilmedi.",
  "Current authority, exact revision or fields were denied. Refresh before another decision.": "Güncel yetki, tam sürüm veya alanlar reddedildi. Başka karar vermeden önce yenileyin.",
  "Save outcome uncertain; inspect the exact request key before continuing.": "Kayıt sonucu belirsiz; devam etmeden önce tam istek anahtarını inceleyin.",
  "Request reconciled from immutable history; no command replayed.": "İstek değişmez geçmişten uzlaştırıldı; komut yeniden yürütülmedi.",
  "No decision found. You may deliberately retry the same frozen command; server authority is rechecked.": "Karar bulunamadı. Aynı sabitlenmiş komutu bilinçli olarak tekrar deneyebilirsiniz; sunucu yetkisi yeniden kontrol edilir.",
  "Current outcome/authority remains unavailable. No command replayed.": "Güncel sonuç/yetki hâlâ kullanılamıyor. Komut yeniden yürütülmedi."
};

@Component({
  selector: 'app-authority-prospects', imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="authority-title">
      <h1 id="authority-title">{{ t("Human authority prospects from stored research") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish authority-prospect interface draft in local development. Human proposals and source excerpts retain their original language; bilingual approval is pending.") }}</p> }
      <p><a [routerLink]="['/app/dashboard', organizationId, projectId]">{{ t("Return to project evidence") }}</a> · <a [routerLink]="['/app/research', organizationId, projectId]">{{ t("Inspect original research") }}</a></p>
      <p>{{ t("Organization") }} <span lang="en">{{ organizationId }}</span> {{ t("· project") }} <span lang="en">{{ projectId }}</span>{{ t(". Exact stored public-page quotes support human partnership, mention and digital-PR prospects. Relevance is your judgment. Text does not prove inbound, unlinked or lost links, publication age, complete coverage or permission to contact anyone.") }}</p>
      <p><a [routerLink]="['/app/authority-links', organizationId, projectId]">{{ t("Review separate independent human link reports and actual own-target recovery evidence") }}</a>{{ t(". Research text is never imported as link proof.") }}</p>
      <p>{{ t("No automatic fetch, AI draft, link creation or sending. Supply no contact identities, account details or secrets. Private customer records follow 90-day retained access after lapse, deletion within 30 days of closure/retention expiry, and up to 35-day backup rotation after active deletion. Declare independent rights to use and store evidence under that policy.") }}</p>
      @if (loading()) { <p role="status">{{ t("Loading current sources and private prospect history.") }}</p> }
      @if (error()) { <p role="alert" [attr.lang]="t(error()) === error() ? 'en' : uiLanguage()">{{ t(error()) }}</p> }
      @if (message()) { <p role="status" [attr.lang]="t(message()) === message() ? 'en' : uiLanguage()">{{ t(message()) }}</p> }
      @if (!context() && !pending() && !loading()) { <button type="button" (click)="load()" [disabled]="busy()">{{ t("Reload current project") }}</button> }
      @if (pending()) {
        <p>{{ t("The exact save outcome is uncertain. This command is frozen in component memory; no automatic replay.") }}</p>
        <button type="button" (click)="reconcile()" [disabled]="busy()">{{ t("Check uncertain save") }}</button>
        @if (notFound()) { <button type="button" (click)="retry()" [disabled]="busy()">{{ t("Retry same exact command") }}</button> }
      }
      @if (context(); as info) {
        <button type="button" (click)="load()" [disabled]="busy() || !!pending()">{{ t("Refresh current authority and history") }}</button>
        <p>{{ t("Current flags are as of refresh. The server rechecks source, actor, assignee, scope and retention on every decision. Approval is separate from actual manual execution.") }}</p>
        @if (info.has_more) { <p>{{ t("Only the latest 50 prospects are shown.") }}</p> }
        @if (!info.reviews.length) { <p>{{ t("No human prospects recorded for this project.") }}</p> }
        <ul [attr.aria-label]="t('Latest human authority prospects')">
          @for (row of info.reviews; track row.prospect_id) {
            <li><span lang="en">{{ row.intake.proposed_action }}</span> {{ t("· assignee") }} <span lang="en">{{ row.assignee_id }}</span> {{ t("· revision") }} <span lang="en">{{ row.revision }}</span> · <span lang="en">{{ row.state }}</span> · {{ row.source_current ? t("Current authority at refresh") : t("Stale/unavailable authority") }}
              <button type="button" (click)="inspect(row.prospect_id)" [disabled]="busy() || !!pending()">{{ t("Inspect exact source, draft and history") }}</button>
            </li>
          }
        </ul>
        @if (selected(); as row) {
          <section aria-labelledby="authority-selected-title">
            <h2 id="authority-selected-title">{{ t("Exact prospect revision") }} <span lang="en">{{ row.revision }}</span> · <span lang="en">{{ row.state }}</span></h2>
            <p>{{ t("Research") }} <span lang="en">{{ row.intake.research_job_id }}</span> {{ t("· source index") }} <span lang="en">{{ row.intake.source_index }}</span> {{ t("· artifact") }} <span lang="en">{{ row.source_evidence.artifact_id }}</span> {{ t("· retrieved") }} <span lang="en">{{ row.source_evidence.retrieved_at }}</span>.</p>
            <p><a [href]="safeSourceUrl(row.intake.target_url)" target="_blank" rel="noopener noreferrer"><span lang="">{{ row.intake.target_url }}</span></a> · {{ row.source_evidence.excerpt_truncated ? t("Truncated excerpt; wider text unavailable") : t("Selected bounded text only") }}.</p>
            <h3>{{ t("Exact stored quote") }}</h3><pre lang="">{{ row.intake.quote }}</pre>
            <h3>{{ t("Human relevance and proposal") }}</h3><pre lang="">{{ row.intake.relevance }}</pre>
            <p><span lang="en">{{ row.intake.proposed_action }}</span> {{ t("· assignee") }} <span lang="en">{{ row.assignee_id }}</span> {{ t("· separate outreach permission declared:") }} {{ row.intake.outreach_permission ? t("Yes; user attestation, not independently verified") : t("No") }}.</p>
            <h3>{{ t("Exact human draft") }}</h3><pre><span [attr.lang]="row.intake.draft_text ? '' : uiLanguage()">{{ row.intake.draft_text || t("Absent; no draft generated") }}</span></pre>
            <p><span lang="">{{ row.reason }}</span> · {{ row.effective_approval ? t("Exact approval current at refresh") : t("No current effective approval") }} {{ t("· approved") }} <span [attr.lang]="row.approved_at ? 'en' : uiLanguage()">{{ row.approved_at || t("Absent") }}</span>.</p>
            @if (!row.source_current) { <p>{{ t("Source/reviewer/assignee authority is stale. New review, approval and manual-use reporting are denied.") }}</p> }
            @if (row.executed_at) { <p>{{ t("Manual execution reported") }} <span lang="en">{{ row.executed_at }}</span>: <span lang="">{{ row.execution_note }}</span>{{ t(". Not independently verified.") }}</p> }
            @if (info.can_review && row.source_current && row.is_latest && !pending()) {
              @if (['draft', 'review', 'approved'].includes(row.state)) {
                <form (submit)="decide($event, row.state === 'draft' ? 'review' : row.state === 'review' ? 'approved' : 'reported')">
                  <label for="authority-decision-reason">{{ t("Human decision reason") }}</label><textarea lang="" id="authority-decision-reason" name="reason" maxlength="500" required></textarea>
                  <label><input name="exact" type="checkbox" required />{{ t("I reviewed the unchanged quote, source target, relevance, assignee and draft of revision") }} <span lang="en">{{ row.revision }}</span>{{ t(". Approval does not send.") }}</label>
                  @if (row.state === 'approved') {
                    <label for="authority-executed">{{ t("Actual manual execution date/time (browser-local timezone; after approval)") }}</label><input lang="en" id="authority-executed" name="executed_at" type="datetime-local" required />
                    <label for="authority-execution-note">{{ t("Actual manual execution note (no private identities)") }}</label><textarea lang="" id="authority-execution-note" name="execution_note" maxlength="500" required></textarea>
                  }
                  <button type="submit" [disabled]="busy() || !row.intake.draft_text.trim() || !row.intake.outreach_permission">{{ row.state === 'draft' ? t("Send exact draft to human review") : row.state === 'review' ? t("Approve exact reviewed draft") : t("Record actual manual execution only") }}</button>
                </form>
                <form (submit)="decide($event, 'dismissed')">
                  <label for="authority-dismiss-reason">{{ t("Human dismissal reason") }}</label><textarea lang="" id="authority-dismiss-reason" name="reason" maxlength="500" required></textarea>
                  <label><input name="exact" type="checkbox" required />{{ t("Dismiss this exact prospect; approval will be absent.") }}</label>
                  <button type="submit" [disabled]="busy()">{{ t("Dismiss prospect without execution") }}</button>
                </form>
              }
            }
            @if (info.can_review && row.is_latest && !pending()) { <button type="button" (click)="edit(row)" [disabled]="busy()">{{ t("Correct or reopen as a new unapproved draft") }}</button> }
          </section>
        }
        @if (historyRows().length) {
          <details><summary>{{ t("Immutable source, assignee, approval and execution history (newest 20)") }}</summary>
            <ol>@for (row of historyRows(); track row.id) {
              <li>{{ t("Revision") }} <span lang="en">{{ row.revision }}</span> · <span lang="en">{{ row.created_at }}</span> · <span lang="en">{{ row.state }}</span> {{ t("· assignee") }} <span lang="en">{{ row.assignee_id }}</span> · <span lang="">{{ row.reason }}</span>.
                <p><span lang="">{{ row.intake.target_url }}</span> {{ t("· retrieved") }} <span lang="en">{{ row.source_evidence.retrieved_at }}</span> · {{ row.source_current ? t("Current authority at refresh") : t("Stale authority") }}.</p>
                <pre lang="">{{ row.intake.quote }}</pre><pre>{{ t("Human relevance:") }} <span lang="">{{ row.intake.relevance }}</span></pre><pre>{{ t("Exact draft:") }} <span [attr.lang]="row.intake.draft_text ? '' : uiLanguage()">{{ row.intake.draft_text || t("Absent") }}</span></pre>
                <p>{{ t("Approval") }} <span [attr.lang]="row.approved_at ? 'en' : uiLanguage()">{{ row.approved_at || t("Absent") }}</span> · <span lang="en">{{ row.execution_state }}</span> · <span lang="">{{ row.execution_note }}</span>.</p>
              </li>
            }</ol>
            @if (historyMore()) { <p>{{ t("Older history exists; this bounded view is incomplete.") }}</p> }
          </details>
        }
        @if (info.can_review && !pending()) {
          <h2>{{ editing() ? t("New unapproved correction; earlier approval does not carry forward") : t("Record one source-supported human prospect") }}</h2>
          @if (!info.sources.length || !info.assignees.length) { <p>{{ t("No current stored research source and eligible assignee available. Inspect research/configuration first; no source is fetched here.") }}</p> }
          @else {
            @if (info.sources_has_more) { <p>{{ t("Only bounded recent source/assignee candidates are shown; inventory is partial.") }}</p> }
            <form (submit)="saveDraft($event)">
              <fieldset [disabled]="busy()">
                <legend>{{ t("Current actual source, human judgment and independent rights") }}</legend>
                <label for="authority-source">{{ t("Stored research source (target is this exact source page)") }}</label>
                <select lang="" id="authority-source" name="source" required [value]="sourceSelection()" (change)="sourceSelection.set($any($event.target).value)">
                  <option value="" [attr.lang]="uiLanguage()">{{ t("Choose actual evidence") }}</option>
                  @for (row of info.sources; track sourceKey(row)) { <option [value]="sourceKey(row)">{{ t("Research") }} {{ row.research_job_id }} {{ t("· index") }} {{ row.source_index }} · {{ row.title }} · {{ row.retrieved_at }}</option> }
                </select>
                @if (chosenSource(); as source) {
                  <p><a [href]="safeSourceUrl(source.url)" target="_blank" rel="noopener noreferrer"><span lang="">{{ source.url }}</span></a> {{ t("· configuration") }} <span lang="en">{{ source.configuration_revision }}</span> · {{ source.excerpt_truncated ? t("Truncated") : t("Bounded selected") }} {{ t("text.") }}</p>
                  <pre lang="">{{ source.excerpt }}</pre><p>{{ t("Original response digest") }} <span lang="en">{{ source.original_response_sha256 }}</span>{{ t(". Facts, links, publication time and outreach permission remain unestablished.") }}</p>
                }
                <label for="authority-quote">{{ t("Exact quote from the stored excerpt") }}</label><textarea lang="" id="authority-quote" name="quote" maxlength="1000" required [value]="editing()?.intake?.quote || ''"></textarea>
                <label for="authority-relevance">{{ t("Human business relevance and evidence limitations") }}</label><textarea lang="" id="authority-relevance" name="relevance" maxlength="500" required [value]="editing()?.intake?.relevance || ''"></textarea>
                <label for="authority-action">{{ t("Human proposed action (not verified link recovery)") }}</label><select id="authority-action" name="proposed_action" [value]="editing()?.intake?.proposed_action || 'partnership'">
                  <option value="partnership">{{ t("Relevant partnership") }}</option><option value="mention">{{ t("Mention prospect (link state unknown)") }}</option><option value="digital_pr">{{ t("Digital PR prospect") }}</option>
                </select>
                <label for="authority-assignee">{{ t("Eligible project assignee") }}</label><select id="authority-assignee" name="assignee_id" required>
                  @for (row of info.assignees; track row.id) { <option [value]="row.id" [selected]="row.id === editing()?.assignee_id">{{ t("Project user") }} {{ row.id }}</option> }
                </select>
                <label for="authority-draft">{{ t("Optional human draft, without contact identities or secrets") }}</label><textarea lang="" id="authority-draft" name="draft_text" maxlength="2000" [value]="editing()?.intake?.draft_text || ''"></textarea>
                <label for="authority-reason">{{ t("Human draft/correction reason") }}</label><textarea lang="" id="authority-reason" name="reason" maxlength="500" required></textarea>
                <label><input name="use_permission" type="checkbox" required />{{ t("I independently have permission to use this evidence for this human proposal.") }}</label>
                <label><input name="storage_permission" type="checkbox" required />{{ t("I independently have permission to store this evidence under the disclosed private export/deletion/backup policy.") }}</label>
                <label><input name="outreach_permission" type="checkbox" />{{ t("I independently have permission for the proposed manual outreach; the source quote alone does not grant it. Required before review/approval.") }}</label>
                <button type="submit" [disabled]="!chosenSource()">{{ t("Save new unapproved human draft revision") }}</button>
                @if (editing()) { <button type="button" (click)="editing.set(null); sourceSelection.set('')">{{ t("Cancel correction") }}</button> }
              </fieldset>
            </form>
          }
        } @else if (!info.can_review) { <p>{{ t("Read-only history. Current verified owner/admin authority is required for intake and every prospect decision.") }}</p> }
      }
    </section>
  `,
  styles: `form, fieldset { display: grid; gap: .6rem; } form { max-width: 48rem; margin-block: 1rem; }
    pre { white-space: pre-wrap; overflow-wrap: anywhere; } li { margin-block: 1rem; } input, textarea, select { min-width: 0; max-width: 100%; }`,
})
export class AuthorityProspects implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  t(text: string) { return this.uiLanguage() === 'tr' ? authorityProspectsTurkish[text] ?? text : text; }
  readonly context = signal<Context | null>(null); readonly selected = signal<Review | null>(null);
  readonly editing = signal<Review | null>(null); readonly historyRows = signal<Review[]>([]); readonly historyMore = signal(false);
  readonly sourceSelection = signal(''); readonly loading = signal(false); readonly busy = signal(false);
  readonly error = signal(''); readonly message = signal(''); readonly pending = signal<Pending | null>(null); readonly notFound = signal(false);
  protected organizationId = 0; protected projectId = 0;
  protected readonly sourceKey = sourceKey; protected readonly safeSourceUrl = safeUrl;
  private generation = 0; private selectionGeneration = 0;
  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi, private readonly destroyRef: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t('Private human authority prospects')} — OrganicSEOOps`));
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
  private clear() { this.context.set(null); this.selected.set(null); this.editing.set(null); this.historyRows.set([]);
    this.pending.set(null); this.notFound.set(false); this.sourceSelection.set(''); this.selectionGeneration++; }
  chosenSource() { return this.context()?.sources.find((row) => sourceKey(row) === this.sourceSelection()); }
  private readContext(response: ApiResult): Context {
    const info = response.body as unknown as Context;
    if (response.status !== 200 || info.organization_id !== this.organizationId || info.project_id !== this.projectId
        || info.policy !== POLICY || typeof info.can_review !== 'boolean' || typeof info.sources_has_more !== 'boolean'
        || !Array.isArray(info.sources) || info.sources.length > 20 || !info.sources.every((row) => isSource(row, this.projectId))
        || !Array.isArray(info.assignees) || info.assignees.length > 20 || !info.assignees.every((row) => !!row && positive(row.id))
        || !Array.isArray(info.reviews) || info.reviews.length > 50 || !info.reviews.every((row) => isReview(row, this.projectId))
        || typeof info.has_more !== 'boolean') throw new Error();
    return info;
  }
  async load() {
    if (this.busy() || this.pending()) return;
    const generation = ++this.generation; this.clear(); this.loading.set(true); this.error.set('');
    try {
      const response = await this.api.authorityProspects(this.organizationId, this.projectId);
      if (generation === this.generation) this.context.set(this.readContext(response));
    } catch { if (generation === this.generation) this.error.set('Prospect history or current project/session authority is unavailable.'); }
    finally { if (generation === this.generation) this.loading.set(false); }
  }
  async inspect(id: string) {
    if (this.busy() || this.pending()) return;
    const generation = this.generation; const selection = ++this.selectionGeneration;
    this.selected.set(null); this.historyRows.set([]); this.editing.set(null); this.sourceSelection.set(''); this.message.set('');
    try {
      const response = await this.api.authorityProspects(this.organizationId, this.projectId, undefined, id);
      if (generation !== this.generation || selection !== this.selectionGeneration) return;
      const info = this.readContext(response);
      if (!info.reviews.length || info.reviews.some((row) => row.prospect_id !== id) || !info.reviews[0].is_latest) throw new Error();
      const previous = this.context();
      if (previous) this.context.set({ ...info, reviews: previous.reviews, has_more: previous.has_more });
      this.selected.set(info.reviews[0]); this.historyRows.set(info.reviews); this.historyMore.set(info.has_more);
    } catch { if (generation === this.generation && selection === this.selectionGeneration) {
      this.context.set(null); this.message.set('Exact history is unavailable; refresh before another decision.');
    } }
  }
  edit(row: Review) { if (!this.busy() && !this.pending() && this.context()?.can_review && row.is_latest) {
    this.editing.set(row); this.sourceSelection.set(sourceKey(row.source_evidence));
  } }
  saveDraft(event: Event) {
    event.preventDefault(); const form = event.target as HTMLFormElement; const info = this.context();
    if (this.busy() || this.pending() || !info?.can_review || !form.reportValidity()) return;
    const fields = new FormData(form); const source = info.sources.find((row) => sourceKey(row) === fields.get('source'));
    if (!source || !fields.has('use_permission') || !fields.has('storage_permission')) return;
    const intake: Intake = { policy: POLICY, research_job_id: source.research_job_id, source_index: source.source_index,
      target_url: source.url, quote: String(fields.get('quote') || ''), relevance: String(fields.get('relevance') || ''),
      proposed_action: String(fields.get('proposed_action') || ''), draft_text: String(fields.get('draft_text') || ''),
      use_permission: true, storage_permission: true, outreach_permission: fields.has('outreach_permission') };
    if (!intake.quote.trim() || !source.excerpt.includes(intake.quote)) { this.error.set('Choose an exact unchanged quote from the displayed stored excerpt.'); return; }
    const row = this.editing(); const data: Record<string, unknown> = { request_key: crypto.randomUUID(), intake,
      assignee_id: Number(fields.get('assignee_id')), state: 'draft', reason: String(fields.get('reason') || ''), executed_at: null, execution_note: '' };
    if (row) data['expected_revision'] = row.revision;
    void this.send({ data, prospectId: row?.prospect_id });
  }
  decide(event: Event, state: string) {
    event.preventDefault(); const form = event.target as HTMLFormElement; const row = this.selected();
    if (this.busy() || this.pending() || !this.context()?.can_review || !row?.source_current || !row.is_latest || !form.reportValidity()) return;
    const fields = new FormData(form); if (!fields.has('exact')) return;
    const date = state === 'reported' ? new Date(String(fields.get('executed_at'))) : null;
    if (date && !Number.isFinite(date.getTime())) return;
    void this.send({ prospectId: row.prospect_id, data: { request_key: crypto.randomUUID(), intake: { ...row.intake },
      assignee_id: row.assignee_id, expected_revision: row.revision, state, reason: String(fields.get('reason') || ''),
      executed_at: date?.toISOString() || null, execution_note: String(fields.get('execution_note') || '') } });
  }
  private matchesCommand(row: Review, command: Pending) {
    const intake = command.data['intake'] as Record<string, unknown>;
    return (!command.prospectId || row.prospect_id === command.prospectId)
      && row.revision === Number(command.data['expected_revision'] || 0) + 1 && row.assignee_id === command.data['assignee_id']
      && row.state === command.data['state'] && row.reason === command.data['reason'] && row.execution_note === command.data['execution_note']
      && (row.executed_at === command.data['executed_at'] || typeof row.executed_at === 'string'
        && typeof command.data['executed_at'] === 'string' && new Date(row.executed_at).getTime() === new Date(command.data['executed_at']).getTime())
      && Object.keys(intake).length === Object.keys(row.intake).length
      && Object.entries(intake).every(([key, value]) => (row.intake as unknown as Record<string, unknown>)[key] === value);
  }
  private async send(command: Pending) {
    const generation = this.generation; this.busy.set(true); this.error.set(''); this.message.set(''); this.notFound.set(false); this.pending.set(command);
    try {
      const response = await this.api.authorityProspects(this.organizationId, this.projectId, command.data, command.prospectId);
      if (generation !== this.generation) return;
      if ([200, 201].includes(response.status) && response.body['organization_id'] === this.organizationId
          && response.body['project_id'] === this.projectId && isReview(response.body['review'], this.projectId)
          && this.matchesCommand(response.body['review'], command)) {
        this.pending.set(null); this.busy.set(false); await this.load();
        if (generation + 1 === this.generation) this.message.set('Human decision recorded. No source was fetched or outreach sent.');
      } else if ([400, 401, 403, 404, 409, 413, 429].includes(response.status)) {
        this.clear(); this.error.set('Current authority, exact revision or fields were denied. Refresh before another decision.');
      } else this.message.set('Save outcome uncertain; inspect the exact request key before continuing.');
    } catch { if (generation === this.generation) this.message.set('Save outcome uncertain; inspect the exact request key before continuing.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  async reconcile() {
    const command = this.pending(); if (!command || this.busy()) return;
    const generation = this.generation; this.busy.set(true);
    try {
      const response = await this.api.authorityProspects(this.organizationId, this.projectId, undefined, undefined, String(command.data['request_key']));
      if (generation !== this.generation) return;
      const info = this.readContext(response);
      if (response.body['lookup'] === 'found' && info.reviews.length === 1 && this.matchesCommand(info.reviews[0], command)) {
        this.pending.set(null); this.busy.set(false); await this.load();
        if (generation + 1 === this.generation) this.message.set('Request reconciled from immutable history; no command replayed.');
      } else if (response.body['lookup'] === 'not_found' && !info.reviews.length && info.can_review) {
        this.notFound.set(true); this.context.set(info); this.message.set('No decision found. You may deliberately retry the same frozen command; server authority is rechecked.');
      } else throw new Error();
    } catch { if (generation === this.generation) {
      this.context.set(null); this.selected.set(null); this.editing.set(null); this.historyRows.set([]); this.sourceSelection.set(''); this.notFound.set(false);
      this.message.set('Current outcome/authority remains unavailable. No command replayed.');
    } }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  retry() { const command = this.pending(); if (command && this.notFound() && !this.busy()) void this.send(command); }
}
