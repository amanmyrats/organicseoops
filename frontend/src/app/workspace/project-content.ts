import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, OnInit, computed, effect, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi } from '../account/account-api';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';
import { environment } from '../../environments/environment';

type Revision = { id: number; item_id: number; project_id: number; revision: number; brief_id: number;
  title: string; body: string; meta_description: string; kind: string; state: string; reason: string;
  created_at: string; actor_id: number; reviewed_revision_id: number | null; approved_by_id: number | null;
  approved_at: string | null; generating_job_id: number | null; publication_url: string; published_at: string | null };
type Brief = { id: number; project_id: number; research_job_id: number; created_at: string };
type Evidence = { version: string; project_id: number; research_job_id: number; action_review_id: number;
  scope: string; approval: string; source_coverage: string; topic: string; angle: string; audience: string; business_goal: string; action_revision: number;
  outline: string[]; research_summary_to_verify: string; claims_to_verify: { text: string; quote: string; source_index: number }[];
  sources: { index: number; state: string; url?: string; title?: string; sha256?: string; retrieved_at?: string }[] };
type Model = { id: number; provider_id: number; name: string; price_known: boolean; access_tier: string;
  privacy_policy_url: string; max_output_tokens: number | null };
type Account = { id: number; provider_id: number; label: string; source: string };
type GenerationJob = { id: number; project_id: number; status: string; brief_id: number; kind: string;
  platform: string; source_current: boolean; estimate_units: number; attempted_units: number;
  cancel_requested: boolean; error_category: string; estimated_max_cost_usd: string | null;
  draft: { item_id: number; review_state: string } | null;
  usage: { request_status: string; estimated_cost_usd: string | null; reported_cost_usd: string | null;
    input_tokens: number | null; output_tokens: number | null } | null };
const contentKinds = ['blog', 'refresh', 'landing', 'service', 'social', 'social_series', 'newsletter', 'description', 'custom'];
const editorialPlatforms = ['linkedin', 'instagram', 'facebook', 'x'];
const transitions: Record<string, string[]> = {
  idea: ['research', 'brief', 'draft', 'archived'], research: ['brief', 'draft', 'archived'], brief: ['draft', 'archived'],
  draft: ['draft', 'review', 'archived'], review: ['draft', 'approved', 'archived'],
  approved: ['draft', 'published', 'archived'], published: ['draft', 'archived'], archived: ['draft'],
};

const projectContentTurkish: Record<string, string> = {
  "Private content studio": "Özel içerik stüdyosu",
  "Unreviewed Turkish content studio interface draft in local development. Human text, sources and AI drafts retain their original language; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe içerik stüdyosu arayüzü taslağı. İnsan metinleri, kaynaklar ve yapay zekâ taslakları özgün dillerini korur; iki dilli onay bekleniyor.",
  "Active project": "Etkin proje",
  ". Plain text only: markup is displayed as text and never executed. Saving, approval and archival never change a live page. Editing approved content clears approval and requires fresh review.": ". Yalnızca düz metin: işaretleme metin olarak gösterilir ve hiçbir zaman çalıştırılmaz. Kaydetme, onay ve arşivleme canlı bir sayfayı değiştirmez. Onaylanmış içeriği düzenlemek onayı kaldırır ve yeni inceleme gerektirir.",
  "Inspect sourced briefs": "Kaynaklı içerik özetlerini inceleyin",
  "Inspect research evidence": "Araştırma kanıtlarını inceleyin",
  "Review existing-content expertise, facts and lifecycle proposals": "Mevcut içerik uzmanlığını, bilgileri ve yaşam döngüsü önerilerini inceleyin",
  "Loading current project content.": "Güncel proje içeriği yükleniyor.",
  "Reload current project": "Güncel projeyi yeniden yükleyin",
  "Content records": "İçerik kayıtları",
  "Start another content record": "Başka bir içerik kaydı başlatın",
  "No content record exists in this inventory page. Start from a private sourced brief.": "Bu envanter sayfasında içerik kaydı yok. Özel, kaynaklı bir içerik özetiyle başlayın.",
  "· revision": "· sürüm",
  "Inspect record": "Kaydı inceleyin",
  "Older content records": "Daha eski içerik kayıtları",
  "Current revision": "Güncel sürüm",
  "Author/actor": "Yazar/işlemi yapan",
  "· generating job": "· üretim işi",
  "Exact reviewed snapshot": "İncelenen tam anlık görüntü",
  "· approver": "· onaylayan",
  "Last manual publication report:": "Son manuel yayın bildirimi:",
  ". This is neither provider verification nor approval of a later draft. Archival does not remove or deindex that page.": ". Bu, sağlayıcı doğrulaması veya sonraki bir taslağın onayı değildir. Arşivleme bu sayfayı kaldırmaz veya dizinden çıkarmaz.",
  "Export current private text revision as JSON": "Güncel özel metin sürümünü JSON olarak dışa aktarın",
  "Edit or review exact current text": "Güncel metnin tamamını düzenleyin veya inceleyin",
  "New human-authored content": "İnsanın yazdığı yeni içerik",
  "Brief selection is unavailable or empty. Prepare a current sourced brief before writing.": "İçerik özeti seçimi kullanılamıyor veya boş. Yazmadan önce güncel, kaynaklı bir içerik özeti hazırlayın.",
  "Source brief (project, action, research and citations checked on save)": "Kaynak içerik özeti (proje, eylem, araştırma ve alıntılar kayıtta kontrol edilir)",
  "Choose a source brief": "Kaynak içerik özeti seçin",
  "Current source brief": "Güncel kaynak içerik özeti",
  "(older snapshot)": "(daha eski anlık görüntü)",
  "Brief": "İçerik özeti",
  "· research": "· araştırma",
  "Content type": "İçerik türü",
  "Title (required, up to 240 characters)": "Başlık (zorunlu, en fazla 240 karakter)",
  "Native text draft (up to 30,000 characters)": "Düz metin taslağı (en fazla 30.000 karakter)",
  "Verify original business expertise, services, sources and all factual claims. Unsupported statistics, prices, testimonials, credentials, availability or customer stories must be omitted or explicitly marked unverified. Citations are not fact approval.": "Özgün işletme uzmanlığını, hizmetleri, kaynakları ve tüm olgusal iddiaları doğrulayın. Desteklenmeyen istatistikler, fiyatlar, referanslar, yeterlilikler, kullanılabilirlik veya müşteri hikâyeleri çıkarılmalı veya açıkça doğrulanmamış olarak işaretlenmelidir. Alıntılar olgusal onay değildir.",
  "Meta description (optional, up to 320 characters)": "Meta açıklaması (isteğe bağlı, en fazla 320 karakter)",
  "Next state": "Sonraki durum",
  "Human change / review rationale (required, up to 500 characters)": "İnsan değişiklik / inceleme gerekçesi (zorunlu, en fazla 500 karakter)",
  "I reviewed this exact current revision, citations, original expertise and factual claims. Unsupported claims remain omitted or clearly unverified.": "Bu güncel sürümün tamamını, alıntıları, özgün uzmanlığı ve olgusal iddiaları inceledim. Desteklenmeyen iddialar çıkarılmış veya açıkça doğrulanmamış olarak kalır.",
  "Record an actual manual publication only. This does not call a CMS or change the page.": "Yalnızca gerçekleşmiş manuel yayını kaydedin. Bu, bir CMS çağırmaz veya sayfayı değiştirmez.",
  "Exact project publication URL": "Tam proje yayın URL’si",
  "Actual publication date and time (your local timezone)": "Gerçek yayın tarihi ve saati (yerel saat diliminiz)",
  "Save immutable": "Değişmez sürümü kaydedin:",
  "revision": "sürüm",
  "You can inspect retained revisions; writing requires owner, admin or member permission and a source brief.": "Saklanan sürümleri inceleyebilirsiniz; yazmak sahip, yönetici veya üye yetkisi ve kaynak içerik özeti gerektirir.",
  "Source-grounded AI draft or native social variant": "Kaynağa dayalı yapay zekâ taslağı veya platforma özgü sosyal varyant",
  "One internal unit reserves one bounded model attempt. Known provider use is settled even if canceled or rejected. Every generated section, title and metadata remains unverified; original business expertise must be added by a person. A social variant requires the exact current human-approved source and creates a separate unapproved record. No browsing, scheduling, publishing or automatic approval occurs.": "Bir dahili birim, sınırlandırılmış bir model denemesini ayırır. Bilinen sağlayıcı kullanımı iptal veya ret durumunda bile hesaplanır. Üretilen her bölüm, başlık ve meta veri doğrulanmamış olarak kalır; özgün işletme uzmanlığını bir insan eklemelidir. Sosyal varyant, insan onaylı güncel kaynağın tamamını gerektirir ve ayrı, onaylanmamış bir kayıt oluşturur. Tarama, zamanlama, yayın veya otomatik onay yapılmaz.",
  "Current sourced brief": "Güncel kaynaklı içerik özeti",
  "Choose source brief": "Kaynak içerik özeti seçin",
  "Draft content type (social format overrides this to social)": "Taslak içerik türü (sosyal biçim bunu social olarak değiştirir)",
  "Editorial social format (optional; conservative drafting rules, no platform API access)": "Editoryal sosyal biçim (isteğe bağlı; temkinli taslak kuralları, platform API erişimi yok)",
  "Draft from brief only": "Yalnızca içerik özetinden taslak oluşturun",
  "· source revision": "· kaynak sürümü",
  "Your selected structured-output model": "Seçtiğiniz yapılandırılmış çıktı modeli",
  "Choose model; prices and capabilities are checked by the server": "Model seçin; fiyatlar ve yetenekler sunucu tarafından kontrol edilir",
  "Scoped provider account": "Kapsamlı sağlayıcı hesabı",
  "Choose provider account": "Sağlayıcı hesabı seçin",
  "Maximum output tokens (128–2048, also limited by selected model)": "En fazla çıktı token sayısı (128–2048, seçilen modelle de sınırlıdır)",
  "Maximum operator-price-estimated provider cost in USD": "Operatör fiyatıyla tahmin edilen en fazla sağlayıcı maliyeti (USD)",
  "Free-tier terms may allow training or retention of confidential data.": "Ücretsiz katman koşulları gizli verilerle eğitime veya verilerin saklanmasına izin verebilir.",
  "Review provider data policy": "Sağlayıcı veri politikasını inceleyin",
  "I explicitly permit this free-tier model's data use for this request.": "Bu istek için ücretsiz katman modelinin veri kullanımına açıkça izin veriyorum.",
  "Queue one unverified AI draft": "Doğrulanmamış bir yapay zekâ taslağını kuyruğa alın",
  "Generation unavailable: writing permission, sourced brief, configured capable model and scoped provider account are required. Manual content remains available.": "Üretim kullanılamıyor: yazma yetkisi, kaynaklı içerik özeti, yapılandırılmış uygun model ve kapsamlı sağlayıcı hesabı gereklidir. Manuel içerik kullanılabilir olmaya devam eder.",
  "Recent generation jobs": "Son üretim işleri",
  "No generation job is recorded in this project.": "Bu projede üretim işi kayıtlı değil.",
  "Job": "İş",
  "Refresh generation": "Üretimi yenileyin",
  "Generation": "Üretim",
  "· source": "· kaynak",
  "Reserved": "Ayrılan",
  "unit · attempted": "birim · denenen",
  "unit ·": "birim ·",
  ". Estimated maximum USD": ". Tahmini en fazla USD",
  "Provider request": "Sağlayıcı isteği",
  "· tokens": "· tokenlar",
  "· estimated observed USD": "· gözlemlenen tahmini USD",
  "· provider-reported USD": "· sağlayıcının bildirdiği USD",
  "Refresh this generation": "Bu üretimi yenileyin",
  "Request cancellation": "İptal isteyin",
  "Inspect generated unapproved content": "Üretilen onaylanmamış içeriği inceleyin",
  "An unknown provider attempt cannot be replayed. Refresh history before any deliberate new paid request.": "Sonucu bilinmeyen sağlayıcı denemesi yeniden yürütülemez. Bilinçli olarak yeni bir ücretli istek yapmadan önce geçmişi yenileyin.",
  "Safe native-text current draft": "Güvenli düz metin güncel taslak",
  "Source brief and research": "Kaynak içerik özeti ve araştırma",
  "Human brief": "İnsan içerik özeti",
  "· action revision": "· eylem sürümü",
  "Audience": "Hedef kitle",
  "· business goal": "· işletme hedefi",
  "Unverified research interpretation": "Doğrulanmamış araştırma yorumu",
  ". Human verification required.": ". İnsan doğrulaması gereklidir.",
  "Selected source provenance": "Seçilen kaynak kökeni",
  "Private source brief is unavailable. Do not approve text without its evidence.": "Özel kaynak içerik özeti kullanılamıyor. Kanıtı olmadan metni onaylamayın.",
  "Immutable revision history and comparison": "Değişmez sürüm geçmişi ve karşılaştırma",
  "Revision": "Sürüm",
  "Compare revision": "Sürümü karşılaştırın:",
  "to current": "güncel sürümle",
  "Older revisions": "Daha eski sürümler",
  "Compared revision": "Karşılaştırılan sürüm",
  "Title": "Başlık",
  "· type": "· tür",
  "· brief": "· içerik özeti",
  "Meta description": "Meta açıklaması",
  "none; human text": "yok; insan metni",
  "none": "yok",
  "not approved": "onaylanmadı",
  "not reported": "bildirilmedi",
  "operator price recorded": "operatör fiyatı kayıtlı",
  "price unavailable": "fiyat kullanılamıyor",
  "brief draft": "içerik özeti taslağı",
  "cancellation requested": "iptal istendi",
  "no cancellation requested": "iptal istenmedi",
  "current": "güncel",
  "changed/unavailable": "değişti/kullanılamıyor",
  "no failure category": "hata kategorisi yok",
  "unknown": "bilinmiyor",
  "retrieval unavailable": "alınma zamanı kullanılamıyor",
  "Choose a current accessible project.": "Erişilebilir güncel bir proje seçin.",
  "Project content unavailable or access revoked.": "Proje içeriği kullanılamıyor veya erişim iptal edildi.",
  "Current content inventory unavailable; reload before writing.": "Güncel içerik envanteri kullanılamıyor; yazmadan önce yeniden yükleyin.",
  "Content revision unavailable. Reload before further edits.": "İçerik sürümü kullanılamıyor. Başka düzenleme yapmadan önce yeniden yükleyin.",
  "Use 1–240 characters for the title, up to 30,000 for the body, 320 for the meta description and 1–500 for the rationale.": "Başlık için 1–240, gövde için en fazla 30.000, meta açıklaması için 320 ve gerekçe için 1–500 karakter kullanın.",
  "Choose a project publication URL up to 512 characters and an actual publication date and time that is not in the future.": "En fazla 512 karakterlik proje yayın URL’si ve gelecekte olmayan gerçek bir yayın tarihi ve saati seçin.",
  "Save was not accepted or its outcome is unknown. Keep your input; inspect current history before retrying. Changed text needs a draft and fresh review.": "Kayıt kabul edilmedi veya sonucu bilinmiyor. Girdinizi koruyun; tekrar denemeden önce güncel geçmişi inceleyin. Değişen metin, taslak ve yeni inceleme gerektirir.",
  "Save outcome unknown. Inspect history before retrying; your unsaved text is retained here.": "Kayıt sonucu bilinmiyor. Tekrar denemeden önce geçmişi inceleyin; kaydedilmemiş metniniz burada korunur.",
  "Choose a capable model/account and exact-current approved source for a variant.": "Varyant için uygun model/hesap ve güncel onaylanmış kaynağın tamamını seçin.",
  "One unverified draft queued. Refresh its status; no publication or approval was requested.": "Doğrulanmamış bir taslak kuyruğa alındı. Durumunu yenileyin; yayın veya onay istenmedi.",
  "Draft request outcome unknown. Keep the same selection and inspect history before retrying.": "Taslak isteğinin sonucu bilinmiyor. Aynı seçimi koruyun ve tekrar denemeden önce geçmişi inceleyin.",
  "Generation status unavailable or access revoked.": "Üretim durumu kullanılamıyor veya erişim iptal edildi."
};

@Component({
  selector: 'app-project-content', imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="content-title">
      <h1 id="content-title">{{ t("Private content studio") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish content studio interface draft in local development. Human text, sources and AI drafts retain their original language; bilingual approval is pending.") }}</p> }
      <p>{{ t("Active project") }} <span lang="">{{ projectName() }}</span>{{ t(". Plain text only: markup is displayed as text and never executed. Saving, approval and archival never change a live page. Editing approved content clears approval and requires fresh review.") }}</p>
      <p><a [routerLink]="['/app/briefs', organizationId, projectId]">{{ t("Inspect sourced briefs") }}</a> ·
        <a [routerLink]="['/app/research', organizationId, projectId]">{{ t("Inspect research evidence") }}</a> ·
        <a [routerLink]="['/app/content-lifecycle', organizationId, projectId]">{{ t("Review existing-content expertise, facts and lifecycle proposals") }}</a></p>
      @if (loading()) { <p role="status">{{ t("Loading current project content.") }}</p> }
      @if (error()) { <p role="alert" [attr.lang]="t(error()) === error() ? 'en' : uiLanguage()" tabindex="-1" id="content-error">{{ t(error()) }}</p><button (click)="load()" type="button">{{ t("Reload current project") }}</button> }
      @if (saveError()) { <p role="alert" [attr.lang]="t(saveError()) === saveError() ? 'en' : uiLanguage()" tabindex="-1" id="content-save-error">{{ t(saveError()) }}</p> }
      @if (!loading() && !error()) {
        <section aria-labelledby="content-inventory-title">
          <h2 id="content-inventory-title">{{ t("Content records") }}</h2>
          <button type="button" (click)="newItem()" [disabled]="busy()">{{ t("Start another content record") }}</button>
          @if (!items().length) { <p>{{ t("No content record exists in this inventory page. Start from a private sourced brief.") }}</p> }
          <ul>@for (row of items(); track row.item_id) {
            <li><span lang="">{{ row.title }}</span> · <span lang="en">{{ row.kind }}</span> · <span lang="en">{{ row.state }}</span> {{ t("· revision") }} {{ row.revision }}
              <button type="button" (click)="open(row.item_id)" [disabled]="busy()">{{ t("Inspect record") }} <span lang="en">{{ row.item_id }}</span></button></li>
          }</ul>
          @if (nextItems()) { <button type="button" (click)="inventory(nextItems()!)" [disabled]="busy()">{{ t("Older content records") }}</button> }
        </section>
        @if (current(); as row) {
          <h2>{{ t("Current revision") }} <span lang="en">{{ row.revision }}</span> · <span lang="en">{{ row.state }}</span></h2>
          <p>{{ t("Author/actor") }} <span lang="en">{{ row.actor_id }}</span> · <span lang="en">{{ row.created_at }}</span> {{ t("· generating job") }} <span [attr.lang]="row.generating_job_id ? 'en' : uiLanguage()">{{ row.generating_job_id || t("none; human text") }}</span>.</p>
          <p>{{ t("Exact reviewed snapshot") }} <span [attr.lang]="row.reviewed_revision_id ? 'en' : uiLanguage()">{{ row.reviewed_revision_id || t("none") }}</span> {{ t("· approver") }} <span [attr.lang]="row.approved_by_id ? 'en' : uiLanguage()">{{ row.approved_by_id || t("none") }}</span> · <span [attr.lang]="row.approved_at ? 'en' : uiLanguage()">{{ row.approved_at || t("not approved") }}</span>.</p>
          <p>{{ t("Last manual publication report:") }} {{ row.publication_url ? "" : t("none") }}<span lang="">{{ row.publication_url }}</span> · <span [attr.lang]="row.published_at ? 'en' : uiLanguage()">{{ row.published_at || t("not reported") }}</span>{{ t(". This is neither provider verification nor approval of a later draft. Archival does not remove or deindex that page.") }}</p>
          <a [href]="downloadUrl()" download>{{ t("Export current private text revision as JSON") }}</a>
        }
        <section aria-labelledby="content-draft-title">
          <h2 id="content-draft-title">{{ current() ? t("Edit or review exact current text") : t("New human-authored content") }}</h2>
          @if (!briefs().length) { <p>{{ t("Brief selection is unavailable or empty. Prepare a current sourced brief before writing.") }}</p> }
          @if (canEdit() && briefs().length) {
            <form (submit)="save($event)">
              <label for="content-brief">{{ t("Source brief (project, action, research and citations checked on save)") }}</label>
              <select id="content-brief" name="brief_id" required>
                <option value="" [selected]="!current()">{{ t("Choose a source brief") }}</option>
                @if (current() && !hasCurrentBrief()) { <option [value]="current()!.brief_id" selected>{{ t("Current source brief") }} {{ current()!.brief_id }} {{ t("(older snapshot)") }}</option> }
                @for (brief of briefs(); track brief.id) { <option [value]="brief.id" [selected]="brief.id === current()?.brief_id">{{ t("Brief") }} {{ brief.id }} {{ t("· research") }} {{ brief.research_job_id }} · {{ brief.created_at }}</option> }
              </select>
              <label for="content-kind">{{ t("Content type") }}</label>
              <select lang="en" id="content-kind" name="kind">
                @for (kind of kinds; track kind) { <option [value]="kind" [selected]="kind === (current()?.kind || 'blog')">{{ kind }}</option> }
              </select>
              <label for="content-title-input">{{ t("Title (required, up to 240 characters)") }}</label>
              <input lang="" id="content-title-input" name="title" maxlength="480" [value]="current()?.title || ''" required />
              <label for="content-body">{{ t("Native text draft (up to 30,000 characters)") }}</label>
              <textarea lang="" id="content-body" name="body" rows="15" maxlength="60000" [value]="current()?.body || ''" aria-describedby="content-facts"></textarea>
              <p id="content-facts">{{ t("Verify original business expertise, services, sources and all factual claims. Unsupported statistics, prices, testimonials, credentials, availability or customer stories must be omitted or explicitly marked unverified. Citations are not fact approval.") }}</p>
              <label for="content-meta">{{ t("Meta description (optional, up to 320 characters)") }}</label>
              <textarea lang="" id="content-meta" name="meta_description" maxlength="640" [value]="current()?.meta_description || ''"></textarea>
              <label for="content-state">{{ t("Next state") }}</label>
              <select lang="en" id="content-state" name="state" (change)="nextState.set($any($event.target).value)">
                @for (state of states(); track state) { <option [value]="state" [selected]="state === nextState()">{{ state }}</option> }
              </select>
              <label for="content-reason">{{ t("Human change / review rationale (required, up to 500 characters)") }}</label>
              <textarea lang="" id="content-reason" name="reason" maxlength="1000" required></textarea>
              @if (nextState() === 'approved') {
                <label><input type="checkbox" name="fact_review" required /> {{ t("I reviewed this exact current revision, citations, original expertise and factual claims. Unsupported claims remain omitted or clearly unverified.") }}</label>
              }
              @if (nextState() === 'published') {
                <p>{{ t("Record an actual manual publication only. This does not call a CMS or change the page.") }}</p>
                <label for="content-publication-url">{{ t("Exact project publication URL") }}</label>
                <input lang="en" id="content-publication-url" type="url" name="publication_url" maxlength="512" required />
                <label for="content-publication-date">{{ t("Actual publication date and time (your local timezone)") }}</label>
                <input lang="en" id="content-publication-date" type="datetime-local" name="published_at" required />
              }
              <button type="submit" [disabled]="busy()">{{ t("Save immutable") }} <span lang="en">{{ nextState() }}</span> {{ t("revision") }}</button>
            </form>
          } @else { <p>{{ t("You can inspect retained revisions; writing requires owner, admin or member permission and a source brief.") }}</p> }
        </section>
        <section aria-labelledby="content-generation-title">
          <h2 id="content-generation-title">{{ t("Source-grounded AI draft or native social variant") }}</h2>
          <p>{{ t("One internal unit reserves one bounded model attempt. Known provider use is settled even if canceled or rejected. Every generated section, title and metadata remains unverified; original business expertise must be added by a person. A social variant requires the exact current human-approved source and creates a separate unapproved record. No browsing, scheduling, publishing or automatic approval occurs.") }}</p>
          @if (canEdit() && models().length && accounts().length && briefs().length) {
            <form (submit)="generate($event)">
              <label for="generation-brief">{{ t("Current sourced brief") }}</label>
              <select id="generation-brief" name="brief_id" required>
                <option value="">{{ t("Choose source brief") }}</option>
                @for (brief of briefs(); track brief.id) { <option [value]="brief.id" [selected]="brief.id === current()?.brief_id">{{ t("Brief") }} {{ brief.id }}</option> }
              </select>
              <label for="generation-kind">{{ t("Draft content type (social format overrides this to social)") }}</label>
              <select lang="en" id="generation-kind" name="kind">
                @for (kind of kinds; track kind) { @if (kind !== 'social' && kind !== 'social_series') { <option [value]="kind">{{ kind }}</option> } }
              </select>
              <label for="generation-platform">{{ t("Editorial social format (optional; conservative drafting rules, no platform API access)") }}</label>
              <select lang="en" id="generation-platform" name="platform"><option value="" [attr.lang]="uiLanguage()">{{ t("Draft from brief only") }}</option>
                @if (current()?.state === 'approved' || current()?.state === 'published') {
                  @for (platform of platforms; track platform) { <option [value]="platform">{{ platform }} {{ t("· source revision") }} {{ current()!.revision }}</option> }
                }
              </select>
              <label for="generation-model">{{ t("Your selected structured-output model") }}</label>
              <select lang="" id="generation-model" name="model_id" required (change)="selectedModel.set(+$any($event.target).value)">
                <option value="" [attr.lang]="uiLanguage()">{{ t("Choose model; prices and capabilities are checked by the server") }}</option>
                @for (model of models(); track model.id) { <option lang="" [value]="model.id" [disabled]="!model.price_known || model.access_tier === 'unknown'">{{ model.name }} · {{ model.access_tier }} · {{ model.price_known ? t("operator price recorded") : t("price unavailable") }}</option> }
              </select>
              <label for="generation-account">{{ t("Scoped provider account") }}</label>
              <select lang="" id="generation-account" name="account_id" required><option value="" [attr.lang]="uiLanguage()">{{ t("Choose provider account") }}</option>
                @for (account of generationAccounts(); track account.id) { <option lang="" [value]="account.id">{{ account.label }} · {{ account.source }}</option> }
              </select>
              <label for="generation-tokens">{{ t("Maximum output tokens (128–2048, also limited by selected model)") }}</label>
              <input lang="en" id="generation-tokens" type="number" name="max_output_tokens" min="128" [max]="generationTokenLimit()" value="512" required />
              <label for="generation-cost">{{ t("Maximum operator-price-estimated provider cost in USD") }}</label>
              <input lang="en" id="generation-cost" type="number" name="max_cost_usd" min="0.000001" max="100" step="0.000001" value="0.1" required />
              @if (generationModel()?.access_tier === 'free') {
                <p>{{ t("Free-tier terms may allow training or retention of confidential data.") }}
                  @if (safeSource(generationModel()?.privacy_policy_url); as href) { <a [href]="href" target="_blank" rel="noopener noreferrer">{{ t("Review provider data policy") }}</a> }</p>
                <label><input type="checkbox" name="allow_free" required /> {{ t("I explicitly permit this free-tier model's data use for this request.") }}</label>
              }
              <button type="submit" [disabled]="busy()">{{ t("Queue one unverified AI draft") }}</button>
            </form>
          } @else { <p>{{ t("Generation unavailable: writing permission, sourced brief, configured capable model and scoped provider account are required. Manual content remains available.") }}</p> }
          <h3>{{ t("Recent generation jobs") }}</h3>
          @if (!generationJobs().length) { <p>{{ t("No generation job is recorded in this project.") }}</p> }
          <ul>@for (job of generationJobs(); track job.id) {
            <li>{{ t("Job") }} <span lang="en">{{ job.id }}</span> · <span lang="en">{{ job.kind }}</span> · <span [attr.lang]="job.platform ? 'en' : uiLanguage()">{{ job.platform || t("brief draft") }}</span> · <span lang="en">{{ job.status }}</span>
              <button type="button" (click)="inspectGeneration(job.id)" [disabled]="busy()">{{ t("Refresh generation") }} <span lang="en">{{ job.id }}</span></button></li>
          }</ul>
          @if (generationJob(); as job) {
            <p role="status">{{ t("Generation") }} <span lang="en">{{ job.id }}</span> · <span lang="en">{{ job.status }}</span> · {{ job.cancel_requested ? t("cancellation requested") : t("no cancellation requested") }} {{ t("· source") }} {{ job.source_current ? t("current") : t("changed/unavailable") }}.</p>
            <p>{{ t("Reserved") }} <span lang="en">{{ job.estimate_units }}</span> {{ t("unit · attempted") }} <span lang="en">{{ job.attempted_units }}</span> {{ t("unit ·") }} <span [attr.lang]="job.error_category ? 'en' : uiLanguage()">{{ job.error_category || t("no failure category") }}</span>{{ t(". Estimated maximum USD") }} <span [attr.lang]="job.estimated_max_cost_usd ? 'en' : uiLanguage()">{{ job.estimated_max_cost_usd || t("unknown") }}</span>.</p>
            @if (job.usage; as usage) { <p>{{ t("Provider request") }} <span lang="en">{{ usage.request_status }}</span> {{ t("· tokens") }} <span [attr.lang]="usage.input_tokens !== null ? 'en' : uiLanguage()">{{ usage.input_tokens ?? t("unknown") }}</span> / <span [attr.lang]="usage.output_tokens !== null ? 'en' : uiLanguage()">{{ usage.output_tokens ?? t("unknown") }}</span> {{ t("· estimated observed USD") }} <span [attr.lang]="usage.estimated_cost_usd ? 'en' : uiLanguage()">{{ usage.estimated_cost_usd || t("unknown") }}</span> {{ t("· provider-reported USD") }} <span [attr.lang]="usage.reported_cost_usd ? 'en' : uiLanguage()">{{ usage.reported_cost_usd || t("unknown") }}</span>.</p> }
            @if (job.status === 'queued' || job.status === 'running') {
              <button type="button" (click)="inspectGeneration(job.id)" [disabled]="busy()">{{ t("Refresh this generation") }}</button>
              @if (canEdit()) { <button type="button" (click)="inspectGeneration(job.id, true)" [disabled]="busy()">{{ t("Request cancellation") }}</button> }
            }
            @if (job.draft; as draft) { <p><span lang="en">{{ draft.review_state }}</span></p><button type="button" (click)="open(draft.item_id)" [disabled]="busy()">{{ t("Inspect generated unapproved content") }} <span lang="en">{{ draft.item_id }}</span></button> }
            <p>{{ t("An unknown provider attempt cannot be replayed. Refresh history before any deliberate new paid request.") }}</p>
          }
        </section>
        @if (current(); as row) {
          <section aria-labelledby="content-preview-title"><h2 id="content-preview-title">{{ t("Safe native-text current draft") }}</h2><pre><span lang="">{{ row.body }}</span></pre></section>
          <section aria-labelledby="content-brief-title">
            <h2 id="content-brief-title">{{ t("Source brief and research") }}</h2><p role="status" lang="en"><span lang="en">{{ sourceState() }}</span></p>
            @if (evidence(); as brief) {
              <h3>{{ t("Human brief") }}</h3><p><span lang="">{{ brief.topic }}</span> · <span lang="">{{ brief.angle }}</span> {{ t("· action revision") }} <span lang="en">{{ brief.action_revision }}</span>.</p>
              <p>{{ t("Audience") }} <span lang="">{{ brief.audience }}</span> {{ t("· business goal") }} <span lang="">{{ brief.business_goal }}</span>.</p>
              <ol>@for (heading of brief.outline; track $index) { <li><span lang="">{{ heading }}</span></li> }</ol>
              <h3>{{ t("Unverified research interpretation") }}</h3><p><span lang="">{{ brief.research_summary_to_verify }}</span></p>
              <ul>@for (claim of brief.claims_to_verify; track $index) { <li><span lang="">{{ claim.text }}</span> {{ t("· source") }} <span lang="en">{{ claim.source_index + 1 }}</span> · <q><span lang="">{{ claim.quote }}</span></q>{{ t(". Human verification required.") }}</li> }</ul>
              <h3>{{ t("Selected source provenance") }}</h3><ul>@for (source of brief.sources; track source.index) {
                <li><span lang="en">{{ source.state }}</span> · <span [attr.lang]="source.retrieved_at ? 'en' : uiLanguage()">{{ source.retrieved_at || t("retrieval unavailable") }}</span>
                  @if (safeSource(source.url); as href) { <a [href]="href" target="_blank" rel="noopener noreferrer"><span lang="">{{ source.title || href }}</span></a> }</li>
              }</ul>
            } @else { <p>{{ t("Private source brief is unavailable. Do not approve text without its evidence.") }}</p> }
          </section>
          <section aria-labelledby="content-history-title">
            <h2 id="content-history-title">{{ t("Immutable revision history and comparison") }}</h2>
            <ul>@for (old of history(); track old.id) {
              <li>{{ t("Revision") }} {{ old.revision }} · <span lang="en">{{ old.state }}</span> · <span lang="en">{{ old.created_at }}</span> · <span lang="">{{ old.reason }}</span>
                <button type="button" (click)="comparison.set(old)">{{ t("Compare revision") }} <span lang="en">{{ old.revision }}</span> {{ t("to current") }}</button></li>
            }</ul>
            @if (nextHistory()) { <button type="button" (click)="open(row.item_id, nextHistory()!)" [disabled]="busy()">{{ t("Older revisions") }}</button> }
            @if (comparison(); as old) {
              <h3>{{ t("Compared revision") }} <span lang="en">{{ old.revision }}</span> · <span lang="en">{{ old.state }}</span></h3><p>{{ t("Title") }} <span lang="">{{ old.title }}</span> {{ t("· type") }} <span lang="en">{{ old.kind }}</span> {{ t("· brief") }} <span lang="en">{{ old.brief_id }}</span>.</p>
              <p>{{ t("Meta description") }} {{ old.meta_description ? "" : t("none") }}<span lang="">{{ old.meta_description }}</span>.</p><pre><span lang="">{{ old.body }}</span></pre>
              <h3>{{ t("Current revision") }} <span lang="en">{{ row.revision }}</span></h3><p>{{ t("Title") }} <span lang="">{{ row.title }}</span> {{ t("· type") }} <span lang="en">{{ row.kind }}</span> {{ t("· brief") }} <span lang="en">{{ row.brief_id }}</span>.</p>
              <p>{{ t("Meta description") }} {{ row.meta_description ? "" : t("none") }}<span lang="">{{ row.meta_description }}</span>.</p><pre><span lang="">{{ row.body }}</span></pre>
            }
          </section>
        }
      }
      @if (message()) { <p role="status" [attr.lang]="textLanguage(message())">{{ t(message()) }}</p> }
    </section>
  `,
  styles: `section{overflow-wrap:anywhere}label{display:block;margin-block:.8rem .2rem}input:not([type=checkbox]),textarea,select{width:min(100%,46rem);max-width:100%;box-sizing:border-box}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;border:1px solid #71818a;padding:1rem}button{margin:.5rem .5rem .5rem 0}`,
})
export class ProjectContent implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  private readonly messageDraft = signal<{ message: string; translation: string } | null>(null);
  textLanguage(text: string) {
    return Object.hasOwn(projectContentTurkish, text) || this.messageDraft()?.message === text ? this.uiLanguage() : 'en';
  }
  t(text: string) {
    if (this.textLanguage(text) !== 'tr') return text;
    const draft = this.messageDraft();
    return draft?.message === text ? draft.translation : projectContentTurkish[text];
  }
  private setDraftMessage(message: string, translation: string) {
    this.messageDraft.set({ message, translation });
    this.message.set(message);
  }
  organizationId = 0; projectId = 0;
  private generation = 0; private opening = 0;
  private generationRequestKey = crypto.randomUUID().replaceAll('-', '');
  readonly loading = signal(true); readonly busy = signal(false); readonly error = signal(''); readonly message = signal('');
  readonly saveError = signal('');
  readonly projectName = signal(''); readonly canEdit = signal(false); readonly canApprove = signal(false);
  readonly items = signal<Revision[]>([]); readonly briefs = signal<Brief[]>([]); readonly current = signal<Revision | null>(null);
  readonly history = signal<Revision[]>([]); readonly comparison = signal<Revision | null>(null);
  readonly evidence = signal<Evidence | null>(null); readonly sourceState = signal(''); readonly nextState = signal('draft');
  readonly nextItems = signal<number | null>(null); readonly nextHistory = signal<number | null>(null);
  readonly kinds = contentKinds;
  readonly models = signal<Model[]>([]); readonly accounts = signal<Account[]>([]); readonly selectedModel = signal(0);
  readonly generationJobs = signal<GenerationJob[]>([]); readonly generationJob = signal<GenerationJob | null>(null);
  readonly platforms = editorialPlatforms;

  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi, private readonly destroy: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t('Private content studio')} — OrganicSEOOps`));
    destroy.onDestroy(() => { this.generation++; this.opening++; });
  }
  ngOnInit() {
    void this.loadProductLanguage();
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroy)).subscribe((params) => {
      this.organizationId = Number(params.get('organizationId')); this.projectId = Number(params.get('projectId'));
      this.generation++; this.items.set([]); this.briefs.set([]); this.projectName.set(''); this.canEdit.set(false); this.canApprove.set(false);
      this.newItem(); this.busy.set(false); this.error.set(''); this.nextItems.set(null);
      this.models.set([]); this.accounts.set([]); this.selectedModel.set(0); this.generationJobs.set([]); this.generationJob.set(null);
      this.generationRequestKey = crypto.randomUUID().replaceAll('-', '');
      if (Number.isSafeInteger(this.organizationId) && this.organizationId > 0 && Number.isSafeInteger(this.projectId) && this.projectId > 0) void this.load();
      else { this.loading.set(false); this.error.set('Choose a current accessible project.'); }
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
  states() { return (this.current() ? transitions[this.current()!.state] || [] : ['idea', 'research', 'brief', 'draft'])
    .filter((state) => this.canApprove() || !['approved', 'published', 'archived'].includes(state)); }
  hasCurrentBrief() { return this.briefs().some((row) => row.id === this.current()?.brief_id); }
  generationModel() { return this.models().find((row) => row.id === this.selectedModel()); }
  generationAccounts() { return this.accounts().filter((row) => row.provider_id === this.generationModel()?.provider_id); }
  generationTokenLimit() { return Math.min(2048, this.generationModel()?.max_output_tokens ?? 2048); }
  safeSource(value?: string) {
    try { const url = new URL(value || ''); return url.protocol === 'https:' && !url.username && !url.password && !url.search && !url.hash && (!url.port || url.port === '443') ? url.href : ''; }
    catch { return ''; }
  }
  private validEvidence(value: unknown, briefId: number): value is Evidence {
    const brief = value as Evidence | null, known = this.briefs().find(row => row.id === briefId);
    return !!brief && !Array.isArray(brief) && brief.version === 'content-brief-v1' && brief.project_id === this.projectId
      && Number.isSafeInteger(brief.research_job_id) && brief.research_job_id > 0
      && (!known || brief.research_job_id === known.research_job_id)
      && Number.isSafeInteger(brief.action_review_id) && brief.action_review_id > 0
      && Number.isSafeInteger(brief.action_revision) && brief.action_revision >= 1 && brief.action_revision <= 32767
      && brief.scope === 'human_authored_structure_and_unverified_ai_interpretation_not_publication'
      && brief.approval === 'draft_human_review_required_no_site_change'
      && typeof brief.source_coverage === 'string' && ['partial', 'collected_selected_sources_only'].includes(brief.source_coverage)
      && typeof brief.topic === 'string' && !!brief.topic.trim() && Array.from(brief.topic.trim()).length <= 240
      && typeof brief.angle === 'string' && !!brief.angle.trim() && Array.from(brief.angle.trim()).length <= 500
      && typeof brief.audience === 'string' && Array.from(brief.audience).length <= 500
      && typeof brief.business_goal === 'string' && Array.from(brief.business_goal).length <= 240
      && Array.isArray(brief.outline) && brief.outline.length >= 1 && brief.outline.length <= 12
      && brief.outline.every(line => typeof line === 'string' && !!line.trim() && Array.from(line.trim()).length <= 160)
      && typeof brief.research_summary_to_verify === 'string' && !!brief.research_summary_to_verify
      && Array.from(brief.research_summary_to_verify).length <= 3000
      && Array.isArray(brief.sources) && brief.sources.length >= 1 && brief.sources.length <= 5
      && brief.sources.every((source, position) => source && !Array.isArray(source)
        && Number.isSafeInteger(source.index) && source.index >= 0 && source.index < 5
        && (!position || source.index > brief.sources[position - 1].index)
        && (source.url === undefined || typeof source.url === 'string' && !!this.safeSource(source.url))
        && (source.title === undefined || typeof source.title === 'string' && Array.from(source.title).length <= 240)
        && (source.sha256 === undefined || typeof source.sha256 === 'string' && /^[0-9a-f]{64}$/.test(source.sha256))
        && (source.retrieved_at === undefined || awareDate(source.retrieved_at))
        && (source.state === 'unavailable' || source.state === 'collected' && typeof source.url === 'string'
          && typeof source.title === 'string' && typeof source.sha256 === 'string' && typeof source.retrieved_at === 'string'))
      && brief.sources.some(source => source.state === 'collected')
      && Array.isArray(brief.claims_to_verify) && brief.claims_to_verify.length >= 1 && brief.claims_to_verify.length <= 10
      && brief.claims_to_verify.every(claim => claim && !Array.isArray(claim) && typeof claim.text === 'string'
        && !!claim.text && Array.from(claim.text).length <= 500 && typeof claim.quote === 'string' && !!claim.quote.trim()
        && Array.from(claim.quote.trim()).length <= 300 && Number.isSafeInteger(claim.source_index)
        && brief.sources.some(source => source.index === claim.source_index && source.state === 'collected'));
  }
  downloadUrl() { return `${environment.apiBase}/organizations/${this.organizationId}/projects/${this.projectId}/content/${this.current()?.item_id}/download/`; }
  newItem() {
    this.opening++; this.current.set(null); this.history.set([]); this.comparison.set(null); this.evidence.set(null);
    this.nextHistory.set(null); this.sourceState.set(''); this.nextState.set('draft'); this.message.set(''); this.messageDraft.set(null); this.saveError.set('');
  }
  async load() {
    const generation = ++this.generation; this.loading.set(true); this.error.set(''); this.newItem();
    this.canEdit.set(false); this.canApprove.set(false);
    this.models.set([]); this.accounts.set([]); this.selectedModel.set(0);
    this.generationJobs.set([]); this.generationJob.set(null);
    try {
      const context = await this.api.projectOnboarding(this.organizationId, this.projectId);
      if (generation !== this.generation) return;
      const project = context.body['project'] as Record<string, unknown> | undefined;
      if (context.status !== 200 || project?.['id'] !== this.projectId || project['organization_id'] !== this.organizationId) throw new Error();
      this.projectName.set(String(project['name'])); this.canEdit.set(typeof project['role'] === 'string' && ['owner', 'admin', 'member'].includes(project['role']));
      this.canApprove.set(typeof project['role'] === 'string' && ['owner', 'admin'].includes(project['role']));
      const [briefs, models, jobs] = await Promise.all([this.api.projectBriefs(this.organizationId, this.projectId),
        this.api.projectResearch(this.organizationId, this.projectId), this.api.contentGeneration(this.organizationId, this.projectId)]);
      if (generation !== this.generation) return;
      this.briefs.set(briefs.status === 200 && briefs.body['project_id'] === this.projectId && Array.isArray(briefs.body['briefs'])
        ? (briefs.body['briefs'] as Brief[]).filter((row) => row && row.project_id === this.projectId && Number.isSafeInteger(row.id) && row.id > 0
          && Number.isSafeInteger(row.research_job_id) && row.research_job_id > 0 && awareDate(row.created_at)) : []);
      if (models.status === 200 && models.body['project_id'] === this.projectId && Array.isArray(models.body['models']) && Array.isArray(models.body['accounts'])
        && models.body['models'].every(row => row && Number.isSafeInteger(row.id) && row.id > 0
          && Number.isSafeInteger(row.provider_id) && row.provider_id > 0
          && typeof row.name === 'string' && !!row.name.trim() && Array.from(row.name).length <= 120
          && (row.max_output_tokens === null || Number.isSafeInteger(row.max_output_tokens) && row.max_output_tokens >= 1 && row.max_output_tokens <= 10000000)
          && typeof row.privacy_policy_url === 'string' && Array.from(row.privacy_policy_url).length <= 1024
          && (row.privacy_policy_url === '' ? row.access_tier !== 'free' : !!this.safeSource(row.privacy_policy_url))
          && typeof row.access_tier === 'string' && ['unknown', 'standard', 'free'].includes(row.access_tier) && typeof row.price_known === 'boolean')
        && models.body['accounts'].every(row => row && Number.isSafeInteger(row.id) && row.id > 0
          && Number.isSafeInteger(row.provider_id) && row.provider_id > 0
          && typeof row.label === 'string' && !!row.label.trim() && Array.from(row.label).length <= 80
          && typeof row.source === 'string' && ['platform', 'organization'].includes(row.source))) {
        this.models.set(models.body['models'] as Model[]); this.accounts.set(models.body['accounts'] as Account[]);
      }
      if (jobs.status === 200 && jobs.body['project_id'] === this.projectId && Array.isArray(jobs.body['jobs'])) {
        this.generationJobs.set((jobs.body['jobs'] as unknown[]).filter((row): row is GenerationJob => isGenerationJob(row, this.projectId)));
      }
      await this.inventory();
    } catch { if (generation === this.generation) this.error.set('Project content unavailable or access revoked.'); }
    finally { if (generation === this.generation) this.loading.set(false); }
  }
  async inventory(before?: number) {
    const generation = this.generation;
    try {
      const result = await this.api.projectContent(this.organizationId, this.projectId, 0, before);
      if (generation !== this.generation) return;
      if (result.status !== 200 || result.body['project_id'] !== this.projectId || !Array.isArray(result.body['items'])) throw new Error();
      this.items.set((result.body['items'] as Revision[]).filter((row) => hasRevisionIdentity(row, this.projectId)));
      const cursor = result.body['next_before'];
      this.nextItems.set(typeof cursor === 'number' && Number.isSafeInteger(cursor) && cursor > 0 ? cursor : null);
    } catch { if (generation === this.generation) this.error.set('Current content inventory unavailable; reload before writing.'); }
  }
  async open(itemId: number, before?: number) {
    const generation = this.generation, opening = ++this.opening;
    if (!before) this.current.set(null);
    this.evidence.set(null); this.sourceState.set(''); this.comparison.set(null); this.busy.set(true); this.message.set('');
    try {
      const result = await this.api.projectContent(this.organizationId, this.projectId, itemId, before);
      if (generation !== this.generation || opening !== this.opening) return;
      const row = result.body['current'] as Revision;
      if (result.status !== 200 || result.body['project_id'] !== this.projectId || !hasRevisionIdentity(row, this.projectId)
        || row.item_id !== itemId || !hasRevisionText(row) || !Array.isArray(result.body['history'])) throw new Error();
      this.current.set(row); this.history.set((result.body['history'] as Revision[]).filter((old) => hasRevisionIdentity(old, this.projectId) && hasRevisionText(old) && old.item_id === itemId));
      const cursor = result.body['next_before'];
      this.nextHistory.set(typeof cursor === 'number' && Number.isSafeInteger(cursor) && cursor > 0 && cursor <= 2147483647 ? cursor : null);
      const evidence = result.body['brief'], sourceState = result.body['source_state'];
      const readable = typeof sourceState === 'string'
        && ['current_review_still_required', 'stale_prepare_new_brief_before_review'].includes(sourceState)
        && this.validEvidence(evidence, row.brief_id);
      this.evidence.set(readable ? evidence as Evidence : null);
      this.sourceState.set(readable ? sourceState : 'private_brief_unavailable'); this.nextState.set(this.states()[0] || 'draft');
    } catch { if (generation === this.generation && opening === this.opening) this.message.set('Content revision unavailable. Reload before further edits.'); }
    finally { if (generation === this.generation && opening === this.opening) this.busy.set(false); }
  }
  async save(event: Event) {
    event.preventDefault(); const form = event.target as HTMLFormElement;
    if (!this.canEdit() || this.busy() || !form.reportValidity()) return;
    const fields = new FormData(form), state = String(fields.get('state'));
    const row = this.current(); const generation = this.generation; const itemId = row?.item_id || 0;
    if (!this.states().includes(state)) return;
    const title = String(fields.get('title') || '').trim(), body = String(fields.get('body') || '');
    const meta = String(fields.get('meta_description') || ''), reason = String(fields.get('reason') || '').trim();
    if (!title || Array.from(title).length > 240 || Array.from(body).length > 30000
        || Array.from(meta).length > 320 || !reason || Array.from(reason).length > 500) {
      this.saveError.set('Use 1–240 characters for the title, up to 30,000 for the body, 320 for the meta description and 1–500 for the rationale.'); return;
    }
    const publicationUrl = String(fields.get('publication_url') || '');
    const publishedAt = state === 'published' ? new Date(String(fields.get('published_at') || '')) : null;
    if (publishedAt && (!Number.isFinite(publishedAt.getTime()) || publishedAt.getTime() > Date.now()
        || !publicationUrl.trim() || Array.from(publicationUrl).length > 512)) {
      this.saveError.set('Choose a project publication URL up to 512 characters and an actual publication date and time that is not in the future.'); return;
    }
    this.busy.set(true); this.message.set(''); this.saveError.set('');
    const data: Record<string, unknown> = { request_key: crypto.randomUUID().replaceAll('-', ''), brief_id: Number(fields.get('brief_id')),
      kind: String(fields.get('kind')), title, body, meta_description: meta, state, reason };
    if (row) data['expected_revision'] = row.revision;
    if (publishedAt) {
      data['publication_url'] = publicationUrl;
      data['published_at'] = publishedAt.toISOString();
    }
    try {
      const result = await this.api.saveProjectContent(this.organizationId, this.projectId, itemId, data);
      if (generation !== this.generation) return;
      const saved = result.body['revision'] as Revision;
      if (result.status !== 201 || result.body['project_id'] !== this.projectId || !hasRevisionIdentity(saved, this.projectId) || !hasRevisionText(saved)
          || itemId && saved.item_id !== itemId) {
        this.saveError.set('Save was not accepted or its outcome is unknown. Keep your input; inspect current history before retrying. Changed text needs a draft and fresh review.');
        setTimeout(() => { if (generation === this.generation) document.getElementById('content-save-error')?.focus(); }); return;
      }
      await this.inventory();
      if (generation !== this.generation) return;
      await this.open(saved.item_id);
      if (generation === this.generation) this.setDraftMessage(`Immutable ${state} revision saved. No live page changed.`,
        `Değiştirilemez ${state} revizyonu kaydedildi. Canlı sayfa değişmedi.`);
    } catch { if (generation === this.generation) {
      this.saveError.set('Save outcome unknown. Inspect history before retrying; your unsaved text is retained here.');
      setTimeout(() => { if (generation === this.generation) document.getElementById('content-save-error')?.focus(); });
    } }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  async generate(event: Event) {
    event.preventDefault(); const form = event.target as HTMLFormElement;
    if (this.busy() || !this.canEdit() || !form.reportValidity()) return;
    const input = new FormData(form), platform = String(input.get('platform') || '');
    const current = this.current(), model = this.generationModel();
    const account = this.generationAccounts().find((row) => row.id === Number(input.get('account_id')));
    const tokens = Number(input.get('max_output_tokens'));
    if (!model?.price_known || model.access_tier === 'unknown' || !account || !Number.isSafeInteger(tokens)
        || tokens < 128 || tokens > this.generationTokenLimit() || model.access_tier === 'free' && !input.has('allow_free')
        || platform && (!current || !['approved', 'published'].includes(current.state)
        || Number(input.get('brief_id')) !== current.brief_id)) { this.message.set('Choose a capable model/account and exact-current approved source for a variant.'); return; }
    const generation = this.generation; this.busy.set(true); this.message.set('');
    try {
      const response = await this.api.generateProjectContent(this.organizationId, this.projectId, {
        brief_id: Number(input.get('brief_id')), source_revision_id: platform ? current!.id : null,
        kind: platform ? 'social' : String(input.get('kind')), platform, model_id: model.id, account_id: account.id,
        max_output_tokens: tokens, max_cost_usd: String(input.get('max_cost_usd')),
        allow_free: model.access_tier === 'free' && input.has('allow_free'), idempotency_key: this.generationRequestKey,
      });
      if (generation !== this.generation) return;
      const job = response.body['job'];
      if (response.status !== 202 || response.body['project_id'] !== this.projectId || !isGenerationJob(job, this.projectId)) {
        this.setDraftMessage(`Draft request unavailable (${String(response.body['code'] || response.status)}). Check source, model and allowance; refresh history before retrying.`,
          `Taslak isteği kullanılamıyor (${String(response.body['code'] || response.status)}). Kaynağı, modeli ve kullanım hakkını kontrol edin; tekrar denemeden önce geçmişi yenileyin.`); return;
      }
      this.generationRequestKey = crypto.randomUUID().replaceAll('-', '');
      this.generationJob.set(job); this.generationJobs.set([job, ...this.generationJobs().filter((row) => row.id !== job.id)].slice(0, 20));
      this.message.set('One unverified draft queued. Refresh its status; no publication or approval was requested.');
    } catch { if (generation === this.generation) this.message.set('Draft request outcome unknown. Keep the same selection and inspect history before retrying.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  async inspectGeneration(id: number, cancel = false) {
    if (this.busy() || cancel && !this.canEdit()) return;
    const generation = this.generation; this.busy.set(true);
    try {
      const response = await this.api.contentGeneration(this.organizationId, this.projectId, id, cancel);
      if (generation !== this.generation) return;
      const job = response.body['job'];
      if (response.status !== 200 || response.body['project_id'] !== this.projectId || !isGenerationJob(job, this.projectId) || job.id !== id) throw new Error();
      this.generationJob.set(job); this.generationJobs.set(this.generationJobs().map((row) => row.id === id ? job : row));
    } catch { if (generation === this.generation) { this.generationJob.set(null); this.message.set('Generation status unavailable or access revoked.'); } }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
}

function awareDate(value: unknown): value is string {
  return typeof value === 'string' && value.length <= 64
    && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
}

function publicationUrl(value: string) {
  if (!/^https?:\/\/[^/?#]/i.test(value) || /[\s\\\u0000-\u001f]/.test(value)) return false;
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password && !url.search && !url.hash;
  } catch { return false; }
}

function hasRevisionIdentity(value: unknown, projectId: number) {
  if (!value || typeof value !== 'object') return false;
  const row = value as Revision;
  return row.project_id === projectId && [row.id, row.item_id, row.brief_id, row.actor_id].every(id => Number.isSafeInteger(id) && id > 0)
    && Number.isSafeInteger(row.revision) && row.revision >= 1 && row.revision <= 2147483647
    && [row.generating_job_id, row.reviewed_revision_id, row.approved_by_id].every(id => id === null || Number.isSafeInteger(id) && id > 0)
    && (row.reviewed_revision_id === null ? row.approved_by_id === null && row.approved_at === null
      : row.approved_by_id !== null && awareDate(row.approved_at))
    && (!['approved', 'published'].includes(row.state) || row.reviewed_revision_id !== null)
    && awareDate(row.created_at) && (row.published_at === null || awareDate(row.published_at))
    && typeof row.publication_url === 'string' && Array.from(row.publication_url).length <= 512
    && (row.publication_url === '' || publicationUrl(row.publication_url))
    && (row.publication_url === '' ? row.published_at === null : row.published_at !== null)
    && (row.state !== 'published' || row.publication_url !== '')
    && typeof row.state === 'string' && Object.hasOwn(transitions, row.state)
    && typeof row.kind === 'string' && contentKinds.includes(row.kind)
    && typeof row.title === 'string' && !!row.title.trim() && Array.from(row.title).length <= 240
    && typeof row.reason === 'string' && !!row.reason.trim() && Array.from(row.reason).length <= 500;
}

function hasRevisionText(row: Revision) {
  return typeof row.body === 'string' && Array.from(row.body).length <= 30000
    && (!['review', 'approved', 'published'].includes(row.state) || !!row.body.trim())
    && typeof row.meta_description === 'string' && Array.from(row.meta_description).length <= 320;
}

function isGenerationJob(value: unknown, projectId: number): value is GenerationJob {
  if (!value || typeof value !== 'object') return false;
  const row = value as GenerationJob;
  return Number.isSafeInteger(row.id) && row.id > 0 && row.project_id === projectId
    && Number.isSafeInteger(row.brief_id) && row.brief_id > 0
    && typeof row.kind === 'string' && contentKinds.includes(row.kind) && typeof row.platform === 'string'
    && (row.platform === '' ? !['social', 'social_series'].includes(row.kind) : row.kind === 'social' && editorialPlatforms.includes(row.platform))
    && row.estimate_units === 1 && Number.isSafeInteger(row.attempted_units) && row.attempted_units >= 0 && row.attempted_units <= 1
    && typeof row.error_category === 'string' && Array.from(row.error_category).length <= 64
    && (row.estimated_max_cost_usd === null || typeof row.estimated_max_cost_usd === 'string')
    && typeof row.status === 'string' && ['queued', 'running', 'waiting_provider', 'succeeded', 'failed', 'cancelled', 'partially_succeeded'].includes(row.status)
    && typeof row.source_current === 'boolean' && typeof row.cancel_requested === 'boolean'
    && (row.usage === null || !!row.usage && typeof row.usage.request_status === 'string'
      && ['attempted', 'completed', 'failed', 'unknown'].includes(row.usage.request_status)
      && (row.usage.estimated_cost_usd === null || typeof row.usage.estimated_cost_usd === 'string')
      && (row.usage.reported_cost_usd === null || typeof row.usage.reported_cost_usd === 'string')
      && (row.usage.input_tokens === null || Number.isSafeInteger(row.usage.input_tokens) && row.usage.input_tokens >= 0 && row.usage.input_tokens <= 100000000)
      && (row.usage.output_tokens === null || Number.isSafeInteger(row.usage.output_tokens) && row.usage.output_tokens >= 0 && row.usage.output_tokens <= 100000000))
    && (row.draft === null || !!row.draft && Number.isSafeInteger(row.draft.item_id) && row.draft.item_id > 0
      && row.draft.review_state === 'unverified_draft_human_review_required');
}
