import { Title } from '@angular/platform-browser';
import { Component, computed, DestroyRef, effect, inject, OnDestroy, OnInit, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';
import { AccountApi } from './account-api';

const milestoneLabels = {
  public_page_view: 'Public page view',
  public_cta_selected: 'Public CTA selected',
  registration_succeeded: 'Self-service registration',
  email_verified: 'First primary email verification',
  trial_activated: 'Audited trial activation',
  first_import_succeeded: 'Organization’s first complete nonempty CSV import',
  first_audit_succeeded: 'Prospective first subjective bounded-audit usefulness acknowledgment per organization',
  first_action_accepted: 'First retained human-accepted action per organization',
  checkout_initiated: 'Prospective owner/browser link acknowledgment per checkout attempt',
  paid_activation_confirmed: 'Prospective first active paid server observation per organization',
} as const;

type MilestoneId = keyof typeof milestoneLabels;
type Milestone = { id: MilestoneId; label: string; count: number | null; state: 'derivable' | 'unavailable'; grain?: string };
const cohortLabels = {
  eligible_organizations: 'Organizations with an original trial start in this month',
  mature_organizations: 'Mature known-coverage denominator',
  observed_within_window: 'Within-window first paid server-observation numerator',
  not_observed_within_window: 'Mature without a within-window first observation',
  immature_organizations: 'Excluded — full follow-up has not elapsed',
  unknown_paid_coverage: 'Excluded — unknown paid tracking coverage',
  unassigned_unknown_trial: 'Globally unassigned — no provable original trial start',
} as const;
type CohortInspection = { month: string; assessedAt: string; state: 'available' | 'suppressed' | 'capacity_exceeded';
  counts: { label: string; value: number }[] };

const acquisitionTurkish: Record<string, string> = {
  "Operational acquisition milestones": "Operasyonel edinim aşamaları",
  "Return to security settings": "Güvenlik ayarlarına dön",
  "Platform-superadmin view only. Counts come from": "Yalnızca platform süper yöneticisi görünümü. Sayılar",
  "currently retained records": "halen saklanan kayıtlardan",
  ", not a lifetime funnel or anonymous visitor tracking. Invited users are not self-service registrations. No conversion rates, attribution, customer identifiers or independently verified business-outcome claim is available.": " gelir; tüm geçmişi kapsayan bir dönüşüm hunisi veya anonim ziyaretçi takibi değildir. Davet edilen kullanıcılar kendi kendine kaydolmuş sayılmaz. Dönüşüm oranları, ilişkilendirme, müşteri kimlikleri veya bağımsız doğrulanmış iş sonucu iddiası mevcut değildir.",
  "Human-action acceptance counts each organization once from retained approval history, even after progress, correction or dismissal. Multiple projects or reacceptance do not add another organization. Customer-history deletion can reduce counts. Acceptance is not site implementation or SEO improvement.": "İnsan eylemi kabulü, ilerleme, düzeltme veya reddetme sonrasında bile saklanan onay geçmişinden her kuruluşu bir kez sayar. Birden fazla proje veya yeniden kabul başka bir kuruluş eklemez. Müşteri geçmişinin silinmesi sayıları azaltabilir. Kabul, sitede uygulama veya SEO iyileşmesi değildir.",
  "Checkout receipt counts each prospectively acknowledged attempt once, including a later recheckout in the same organization. Ready transactions, inspection and old attempts are not receipts. Restricted billing receipts survive customer-content erasure. Browser acknowledgment does not prove provider-page loading, payment, paid access or first-ever conversion.": "Ödeme bağlantısı alındı kayıtları, aynı kuruluştaki sonraki yeniden ödeme girişimi dahil ileriye dönük onaylanan her girişimi bir kez sayar. Hazır işlemler, inceleme ve eski girişimler alındı kaydı değildir. Kısıtlı faturalama alındı kayıtları müşteri içeriğinin silinmesinden sonra korunur. Tarayıcı onayı sağlayıcı sayfasının yüklenmesini, ödemeyi, ücretli erişimi veya ilk dönüşümü kanıtlamaz.",
  "Paid observations count each prospectively tracked organization once from immutable signed/reconciled history. The occurrence is the first committed active server observation, not provider activation time or current access. Renewal, recovery and recheckout do not add another organization; old or incomplete tracking remains unknown. Restricted billing history survives customer-content erasure. This is not a lifetime conversion rate.": "Ücretli erişim gözlemleri, değişmez imzalı veya mutabakat yapılmış geçmişten ileriye dönük izlenen her kuruluşu bir kez sayar. Olay, sağlayıcı etkinleştirme zamanı veya mevcut erişim değil, kaydedilen ilk aktif sunucu gözlemidir. Yenileme, kurtarma ve yeniden ödeme başka bir kuruluş eklemez; eski veya eksik takip bilinmiyor olarak kalır. Kısıtlı faturalama geçmişi müşteri içeriğinin silinmesinden sonra korunur. Bu, tüm geçmişi kapsayan bir dönüşüm oranı değildir.",
  "Useful bounded-audit declarations count each prospectively tracked organization once from an explicit customer acknowledgment over the exact supported audit and human-accepted next action. First server acknowledgment time is separate from original audit and action dates. Approval, operational completion and inspection alone are not usefulness. Old/null tracking remains unknown. Later progress, reprioritization, original-role loss or multiple projects do not add a count. Customer-history erasure can reduce this retained count. A subjective declaration is not a clean site, business-fact verification, implementation or SEO improvement; it supplies no consent-aware funnel or lifetime first-value rate.": "Yararlı sınırlı denetim beyanları, desteklenen tam denetim ve insan tarafından kabul edilen sonraki eylem için açık müşteri onayıyla ileriye dönük izlenen her kuruluşu bir kez sayar. İlk sunucu onay zamanı özgün denetim ve eylem tarihlerinden ayrıdır. Yalnızca onay, operasyonel tamamlanma ve inceleme yararlılık değildir. Eski veya boş takip bilinmiyor olarak kalır. Sonraki ilerleme, öncelik değişikliği, özgün rolün kaybı veya birden fazla proje sayıyı artırmaz. Müşteri geçmişinin silinmesi bu saklanan sayıyı azaltabilir. Öznel beyan, temiz bir site, iş gerçeği doğrulaması, uygulama veya SEO iyileşmesi değildir; rızayı dikkate alan dönüşüm hunisi veya tüm geçmişi kapsayan ilk değer oranı sağlamaz.",
  "Loading milestone availability.": "Aşama kullanılabilirliği yükleniyor.",
  "Refresh retained-record counts": "Saklanan kayıt sayılarını yenile",
  "Acquisition-v1 operational records; stages have different user, organization and checkout-attempt grains": "Acquisition-v1 operasyonel kayıtlar; aşamalar farklı kullanıcı, kuruluş ve ödeme girişimi ölçüm birimlerine sahiptir",
  "Milestone": "Aşama",
  "Retained count or availability": "Saklanan sayı veya kullanılabilirlik",
  "Separate short-lived public observations": "Ayrı kısa süreli genel sayfa gözlemleri",
  "Deliberate staff-MFA inspection only. These browser-reported consent-epoch/approved-route/locale counts, with fixed CTA where applicable, never join the operational grains above. They are not unique visitors, verified views/clicks, conversions or cohorts. Withdrawal and original fifteen-minute expiry reduce counts immediately; active cleanup targets seventy-five minutes from issuance under healthy operation. Backups may retain records up to thirty-five days after active deletion. Disabled or missing publication policy is unavailable, not zero.": "Yalnızca personel MFA ile bilinçli inceleme. Gerektiğinde sabit CTA içeren, tarayıcının bildirdiği rıza dönemi, onaylı rota ve dil sayıları yukarıdaki operasyonel ölçüm birimleriyle hiçbir zaman birleştirilmez. Bunlar tekil ziyaretçiler, doğrulanmış görüntülemeler veya tıklamalar, dönüşümler ya da kohortlar değildir. Rızanın geri çekilmesi ve özgün on beş dakikalık sürenin dolması sayıları hemen azaltır; sağlıklı çalışmada aktif temizleme, düzenlenme anından itibaren yetmiş beş dakikayı hedefler. Yedekler aktif silinmeden sonra kayıtları otuz beş güne kadar tutabilir. Devre dışı veya eksik yayın politikası sıfır değil, kullanılamaz durumudur.",
  "Inspect retained public counts": "Saklanan genel sayfa sayılarını incele",
  "Inspecting current unexpired public observations.": "Süresi dolmamış mevcut genel sayfa gözlemleri inceleniyor.",
  "Current unexpired public consent epochs; no operational linkage or funnel rate": "Güncel ve süresi dolmamış genel sayfa rıza dönemleri; operasyonel bağlantı veya dönüşüm hunisi oranı yok",
  "Observation": "Gözlem",
  "Retained monthly trial paid-window counts": "Saklanan aylık deneme ücretli gözlem aralığı sayıları",
  "Deliberate staff-MFA inspection of one completed UTC month of original audited trial starts. Only known prospective paid coverage with the full thirty-seven-day follow-up enters the denominator; early payment does not make a trial mature. First paid server observations at the exact window end or later are outside. Unknown paid coverage and immature organizations are exclusions. Missing original trial proof is globally unassigned, not assigned by organization birth.": "Özgün denetlenmiş deneme başlangıçlarının tamamlanmış bir UTC ayını personel MFA ile bilinçli inceleme. Yalnızca tam otuz yedi günlük takibi tamamlamış, bilinen ileriye dönük ücretli erişim kapsamı paydaya girer; erken ödeme denemeyi olgunlaştırmaz. Aralığın tam bitişindeki veya sonrasındaki ilk ücretli erişim sunucu gözlemleri dışarıdadır. Bilinmeyen ücretli kapsam ve olgunlaşmamış kuruluşlar dışlamadır. Eksik özgün deneme kanıtı küresel olarak atanmamıştır; kuruluşun oluşturulma tarihine göre atanmaz.",
  "Closed and suspended organizations remain included while their restricted originals are retained; customer-content erasure alone preserves restricted billing history, and original-source erasure can reduce counts. All counts are withheld together if any nonzero outcome or exclusion cell is below five. This is not anonymization, a lifetime or consent-aware funnel, anonymous linkage, provider activation time, current access or a business outcome. No rate is calculated.": "Kapatılmış ve askıya alınmış kuruluşlar kısıtlı özgün kayıtları saklandığı sürece dahil kalır; yalnızca müşteri içeriğinin silinmesi kısıtlı faturalama geçmişini korur ve özgün kaynağın silinmesi sayıları azaltabilir. Sıfır olmayan herhangi bir sonuç veya dışlama hücresi beşin altındaysa tüm sayılar birlikte gizlenir. Bu anonimleştirme, tüm geçmişi kapsayan veya rızayı dikkate alan dönüşüm hunisi, anonim bağlantı, sağlayıcı etkinleştirme zamanı, mevcut erişim veya iş sonucu değildir. Oran hesaplanmaz.",
  "Completed UTC trial-start month (optional)": "Tamamlanmış UTC deneme başlangıç ayı (isteğe bağlı)",
  "Leave empty for the previous completed UTC calendar month. Counts are from a complete retained organization scan, limited to five hundred; overflow is unavailable.": "Önceki tamamlanmış UTC takvim ayı için boş bırakın. Sayılar beş yüz kuruluşla sınırlı tam saklanan kuruluş taramasından gelir; sınır aşımı kullanılamaz.",
  "Inspect retained monthly window counts": "Saklanan aylık aralık sayılarını incele",
  "Inspecting complete retained originals with current staff MFA.": "Güncel personel MFA ile saklanan özgün kayıtların tamamı inceleniyor.",
  "Counts suppressed — a nonzero cell is below five. No count or percentage is disclosed.": "Sayılar gizlendi — sıfır olmayan bir hücre beşin altında. Sayı veya yüzde açıklanmaz.",
  "Unavailable — complete collection exceeds five hundred organizations. No truncated denominator is shown.": "Kullanılamıyor — tam koleksiyon beş yüz kuruluşu aşıyor. Kesilmiş bir payda gösterilmez.",
  "Retained organization-grained fixed thirty-seven-day window; exclusions are not a conversion rate": "Kuruluş ölçüm birimli saklanan sabit otuz yedi günlük aralık; dışlamalar dönüşüm oranı değildir",
  "Source classification": "Kaynak sınıflandırması",
  "Retained organizations": "Saklanan kuruluşlar",
  "No mature known-coverage denominator. No percentage is available.": "Olgun ve kapsamı bilinen payda yok. Yüzde mevcut değil.",
  "Public page view": "Genel sayfa görüntüleme",
  "Public CTA selected": "Genel sayfa CTA seçimi",
  "Self-service registration": "Kendi kendine kayıt",
  "First primary email verification": "İlk birincil e-posta doğrulaması",
  "Audited trial activation": "Denetlenmiş deneme etkinleştirmesi",
  "Organization’s first complete nonempty CSV import": "Kuruluşun ilk tamamlanmış ve boş olmayan CSV içe aktarması",
  "Prospective first subjective bounded-audit usefulness acknowledgment per organization": "Kuruluş başına ileriye dönük ilk öznel sınırlı denetim yararlılık onayı",
  "First retained human-accepted action per organization": "Kuruluş başına saklanan ilk insan tarafından kabul edilmiş eylem",
  "Prospective owner/browser link acknowledgment per checkout attempt": "Ödeme girişimi başına ileriye dönük sahip veya tarayıcı bağlantı onayı",
  "Prospective first active paid server observation per organization": "Kuruluş başına ileriye dönük ilk aktif ücretli erişim sunucu gözlemi",
  "Organizations with an original trial start in this month": "Bu ay özgün deneme başlangıcı olan kuruluşlar",
  "Mature known-coverage denominator": "Olgun ve kapsamı bilinen payda",
  "Within-window first paid server-observation numerator": "Aralık içinde ilk ücretli erişim sunucu gözlemi payı",
  "Mature without a within-window first observation": "Aralık içinde ilk gözlemi bulunmayan olgun kuruluşlar",
  "Excluded — full follow-up has not elapsed": "Dışlandı — tam takip süresi geçmedi",
  "Excluded — unknown paid tracking coverage": "Dışlandı — ücretli erişim takip kapsamı bilinmiyor",
  "Globally unassigned — no provable original trial start": "Küresel olarak atanmamış — kanıtlanabilir özgün deneme başlangıcı yok",
  "Unreviewed Turkish acquisition-inspection interface draft in local development. Bilingual approval is pending; unavailable preference reads fall back to English.": "Yerel geliştirmede incelenmemiş Türkçe edinim inceleme arayüzü taslağı. İki dilli onay bekleniyor; tercih okunamıyorsa İngilizceye dönülür.",
  "Unavailable — no accepted source or consent contract": "Kullanılamıyor — kabul edilmiş kaynak veya rıza sözleşmesi yok",
  "Unavailable — publication policy is off": "Kullanılamıyor — yayın politikası kapalı",
  "Cleanup:": "Temizleme:",
  "Deadline missed — investigate cleanup worker/backlog.": "Son tarih aşıldı — temizleme çalışanını ve bekleyen işleri inceleyin.",
  "Expired records pending removal.": "Süresi dolmuş kayıtlar kaldırılmayı bekliyor.",
  "No expired backlog observed.": "Süresi dolmuş bekleyen kayıt gözlenmedi.",
  "UTC month:": "UTC ayı:",
  "Frozen server assessment:": "Dondurulmuş sunucu değerlendirmesi:",
  "Browser-reported page first server receipts": "Tarayıcı tarafından bildirilen sayfanın ilk sunucu alındı kayıtları",
  "Browser-reported fixed CTA first server receipts": "Tarayıcı tarafından bildirilen sabit CTA ilk sunucu alındı kayıtları",
  "Monthly window counts unavailable or malformed. Inspect a completed UTC month with a current staff-MFA session.": "Aylık aralık sayıları kullanılamıyor veya hatalı biçimde. Güncel personel MFA oturumuyla tamamlanmış bir UTC ayını inceleyin.",
  "Public observation counts unavailable or malformed. Inspect with a current staff-MFA session.": "Genel sayfa gözlem sayıları kullanılamıyor veya hatalı biçimde. Güncel personel MFA oturumuyla inceleyin.",
  "Milestones are unavailable for this account or session. Sign in with staff MFA and try again.": "Bu hesap veya oturum için aşamalar kullanılamıyor. Personel MFA ile oturum açıp tekrar deneyin."
};

@Component({
  selector: 'app-acquisition',
  imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="account-card" aria-labelledby="acquisition-title">
      <h1 id="acquisition-title">{{ t("Operational acquisition milestones") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish acquisition-inspection interface draft in local development. Bilingual approval is pending; unavailable preference reads fall back to English.") }}</p> }
      <p><a routerLink="/account/security">{{ t("Return to security settings") }}</a></p>
      <p>{{ t("Platform-superadmin view only. Counts come from") }} <strong>{{ t("currently retained records") }}</strong>{{ t(", not a lifetime funnel or anonymous visitor tracking. Invited users are not self-service registrations. No conversion rates, attribution, customer identifiers or independently verified business-outcome claim is available.") }}</p>
      <p>{{ t("Human-action acceptance counts each organization once from retained approval history, even after progress, correction or dismissal. Multiple projects or reacceptance do not add another organization. Customer-history deletion can reduce counts. Acceptance is not site implementation or SEO improvement.") }}</p>
      <p>{{ t("Checkout receipt counts each prospectively acknowledged attempt once, including a later recheckout in the same organization. Ready transactions, inspection and old attempts are not receipts. Restricted billing receipts survive customer-content erasure. Browser acknowledgment does not prove provider-page loading, payment, paid access or first-ever conversion.") }}</p>
      <p>{{ t("Paid observations count each prospectively tracked organization once from immutable signed/reconciled history. The occurrence is the first committed active server observation, not provider activation time or current access. Renewal, recovery and recheckout do not add another organization; old or incomplete tracking remains unknown. Restricted billing history survives customer-content erasure. This is not a lifetime conversion rate.") }}</p>
      <p>{{ t("Useful bounded-audit declarations count each prospectively tracked organization once from an explicit customer acknowledgment over the exact supported audit and human-accepted next action. First server acknowledgment time is separate from original audit and action dates. Approval, operational completion and inspection alone are not usefulness. Old/null tracking remains unknown. Later progress, reprioritization, original-role loss or multiple projects do not add a count. Customer-history erasure can reduce this retained count. A subjective declaration is not a clean site, business-fact verification, implementation or SEO improvement; it supplies no consent-aware funnel or lifetime first-value rate.") }}</p>
      @if (loading()) { <p role="status">{{ t("Loading milestone availability.") }}</p> }
      @if (error()) { <p role="alert">{{ t(error()) }}</p> }
      @if (!loading() && !error()) {
        <button type="button" (click)="load()">{{ t("Refresh retained-record counts") }}</button>
        <table>
          <caption>{{ t("Acquisition-v1 operational records; stages have different user, organization and checkout-attempt grains") }}</caption>
          <thead><tr><th scope="col">{{ t("Milestone") }}</th><th scope="col">{{ t("Retained count or availability") }}</th></tr></thead>
          <tbody>
            @for (item of milestones(); track item.id) {
              <tr><th scope="row">{{ t(item.label) }}</th><td>
                @if (item.state === 'derivable') { {{ item.count }} (<span lang="en">{{ item.grain }}</span>) }
                @else { {{ t("Unavailable — no accepted source or consent contract") }} }
              </td></tr>
            }
          </tbody>
        </table>
      }
      <section aria-labelledby="public-observations-title">
        <h2 id="public-observations-title">{{ t("Separate short-lived public observations") }}</h2>
        <p>{{ t("Deliberate staff-MFA inspection only. These browser-reported consent-epoch/approved-route/locale counts, with fixed CTA where applicable, never join the operational grains above. They are not unique visitors, verified views/clicks, conversions or cohorts. Withdrawal and original fifteen-minute expiry reduce counts immediately; active cleanup targets seventy-five minutes from issuance under healthy operation. Backups may retain records up to thirty-five days after active deletion. Disabled or missing publication policy is unavailable, not zero.") }}</p>
        <button type="button" (click)="loadPublic()" [disabled]="publicLoading()">{{ t("Inspect retained public counts") }}</button>
        @if (publicLoading()) { <p role="status">{{ t("Inspecting current unexpired public observations.") }}</p> }
        @if (publicError()) { <p role="alert">{{ t(publicError()) }}</p> }
        @if (publicRows().length) {
          <table><caption>{{ t("Current unexpired public consent epochs; no operational linkage or funnel rate") }}</caption>
            <thead><tr><th scope="col">{{ t("Observation") }}</th><th scope="col">{{ t("Retained count or availability") }}</th></tr></thead>
            <tbody>@for (item of publicRows(); track item.id) {
              <tr><th scope="row">{{ t(item.label) }}</th><td>{{ item.count === null ? t('Unavailable — publication policy is off') : item.count }} (<span lang="en">{{ item.grain }}</span>)</td></tr>
            }</tbody>
          </table>
          <p role="status">{{ t("Cleanup:") }} {{ t(publicCleanup()?.deadline_missed ? 'Deadline missed — investigate cleanup worker/backlog.'
            : publicCleanup()?.expired_pending ? 'Expired records pending removal.' : 'No expired backlog observed.') }}</p>
        }
      </section>
      <section aria-labelledby="trial-paid-cohort-title">
        <h2 id="trial-paid-cohort-title">{{ t("Retained monthly trial paid-window counts") }}</h2>
        <p>{{ t("Deliberate staff-MFA inspection of one completed UTC month of original audited trial starts. Only known prospective paid coverage with the full thirty-seven-day follow-up enters the denominator; early payment does not make a trial mature. First paid server observations at the exact window end or later are outside. Unknown paid coverage and immature organizations are exclusions. Missing original trial proof is globally unassigned, not assigned by organization birth.") }}</p>
        <p>{{ t("Closed and suspended organizations remain included while their restricted originals are retained; customer-content erasure alone preserves restricted billing history, and original-source erasure can reduce counts. All counts are withheld together if any nonzero outcome or exclusion cell is below five. This is not anonymization, a lifetime or consent-aware funnel, anonymous linkage, provider activation time, current access or a business outcome. No rate is calculated.") }}</p>
        <label for="trial-paid-cohort-month">{{ t("Completed UTC trial-start month (optional)") }}</label>
        <input id="trial-paid-cohort-month" type="month" [value]="cohortMonth()" (input)="setCohortMonth($event)" aria-describedby="trial-paid-cohort-default">
        <p id="trial-paid-cohort-default">{{ t("Leave empty for the previous completed UTC calendar month. Counts are from a complete retained organization scan, limited to five hundred; overflow is unavailable.") }}</p>
        <button type="button" (click)="loadCohort()" [disabled]="cohortLoading()">{{ t("Inspect retained monthly window counts") }}</button>
        @if (cohortLoading()) { <p role="status">{{ t("Inspecting complete retained originals with current staff MFA.") }}</p> }
        @if (cohortError()) { <p role="alert">{{ t(cohortError()) }}</p> }
        @if (cohort(); as inspection) {
          <p>{{ t("UTC month:") }} <span lang="en">{{ inspection.month }}</span>. {{ t("Frozen server assessment:") }} <span lang="en">{{ inspection.assessedAt }}</span>.</p>
          @if (inspection.state === 'suppressed') { <p role="status">{{ t("Counts suppressed — a nonzero cell is below five. No count or percentage is disclosed.") }}</p> }
          @else if (inspection.state === 'capacity_exceeded') { <p role="status">{{ t("Unavailable — complete collection exceeds five hundred organizations. No truncated denominator is shown.") }}</p> }
          @else {
            <table><caption>{{ t("Retained organization-grained fixed thirty-seven-day window; exclusions are not a conversion rate") }}</caption>
              <thead><tr><th scope="col">{{ t("Source classification") }}</th><th scope="col">{{ t("Retained organizations") }}</th></tr></thead>
              <tbody>@for (row of inspection.counts; track row.label) { <tr><th scope="row">{{ t(row.label) }}</th><td>{{ row.value }}</td></tr> }</tbody>
            </table>
            @if (inspection.counts[1].value === 0) { <p role="status">{{ t("No mature known-coverage denominator. No percentage is available.") }}</p> }
          }
        }
      </section>
    </section>
  `,
  styles: `
    table { width: 100%; border-collapse: collapse; }
    th, td { text-align: left; border-bottom: 1px solid #b9cfd5; padding: 0.65rem; }
  `,
})
export class Acquisition implements OnInit, OnDestroy {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  private readonly destroyRef = inject(DestroyRef);
  t(text: string) { return this.uiLanguage() === 'tr' ? acquisitionTurkish[text] ?? text : text; }
  readonly loading = signal(true);
  readonly error = signal('');
  readonly milestones = signal<Milestone[]>([]);
  private generation = 0;
  readonly publicLoading = signal(false);
  readonly publicError = signal('');
  readonly publicRows = signal<Milestone[]>([]);
  readonly publicCleanup = signal<{ expired_pending: boolean; deadline_missed: boolean } | null>(null);
  private publicGeneration = 0;
  readonly cohortMonth = signal('');
  readonly cohortLoading = signal(false);
  readonly cohortError = signal('');
  readonly cohort = signal<CohortInspection | null>(null);
  private cohortGeneration = 0;

  constructor(private readonly api: AccountApi, title: Title) {
    effect(() => title.setTitle(`${this.t('Operational acquisition milestones')} — OrganicSEOOps`));
  }

  ngOnInit() { void this.loadProductLanguage(); void this.load(); }
  ngOnDestroy() { this.generation++; this.publicGeneration++; this.publicRows.set([]); this.publicCleanup.set(null); this.clearCohort(); }

  private async loadProductLanguage() {
    try {
      const result = await this.api.productLanguage();
      if (!this.destroyRef.destroyed && result.status === 200 && isProductLanguageResult(result.body)) {
        this.productLanguage.set(result.body['language']);
      }
    } catch { /* Keep English when the private preference is unavailable. */ }
  }

  private clearCohort() {
    this.cohortGeneration++; this.cohort.set(null); this.cohortError.set(''); this.cohortLoading.set(false);
  }

  setCohortMonth(event: Event) {
    this.clearCohort(); this.cohortMonth.set((event.target as HTMLInputElement).value);
  }

  async loadCohort() {
    this.clearCohort();
    const generation = this.cohortGeneration, month = this.cohortMonth();
    this.cohortLoading.set(true);
    try {
      if (month && !/^[0-9]{4}-(0[1-9]|1[0-2])$/.test(month)) throw new Error();
      const response = await this.api.trialPaidCohort(month);
      if (generation !== this.cohortGeneration || month !== this.cohortMonth()) return;
      const body = structuredClone(response.body), selected = body['month'], assessment = body['assessed_at'];
      if (response.status !== 200 || Object.keys(body).length !== 19
          || body['method'] !== 'retained-monthly-trial-paid-window-v1' || body['basis'] !== 'current_retained_original_operational_sources'
          || body['grain'] !== 'organization' || body['window_days'] !== 37 || body['collection_limit'] !== 500
          || body['minimum_cell'] !== 5 || body['rates_available'] !== false || typeof selected !== 'string'
          || !/^[0-9]{4}-(0[1-9]|1[0-2])$/.test(selected) || month && selected !== month
          || typeof assessment !== 'string' || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?\+00:00$/.test(assessment)) throw new Error();
      const assessed = Date.parse(assessment), start = Date.parse(selected + '-01T00:00:00Z');
      const end = new Date(start); end.setUTCMonth(end.getUTCMonth() + 1);
      if (!Number.isFinite(assessed) || assessed > Date.now() || !Number.isFinite(start)
          || new Date(assessed).toISOString().slice(0, 19) !== assessment.slice(0, 19)
          || body['starts_at'] !== selected + '-01T00:00:00+00:00'
          || body['ends_at'] !== end.toISOString().slice(0, 19) + '+00:00' || end.getTime() > assessed) throw new Error();
      if (!month) {
        const previous = new Date(assessed); previous.setUTCDate(1); previous.setUTCMonth(previous.getUTCMonth() - 1);
        if (selected !== previous.toISOString().slice(0, 7)) throw new Error();
      }
      const state = body['state'];
      if (typeof state !== 'string' || !['available', 'suppressed', 'capacity_exceeded'].includes(state)) throw new Error();
      const values = Object.keys(cohortLabels).map(key => body[key]);
      if (state === 'available') {
        if (!values.every(value => Number.isSafeInteger(value) && Number(value) >= 0 && Number(value) <= 500)) throw new Error();
        const [eligible, mature, observed, outside, immature, unknown, unassigned] = values as number[];
        if (eligible !== mature + immature + unknown || mature !== observed + outside || eligible + unassigned > 500
            || [observed, outside, immature, unknown, unassigned].some(value => value > 0 && value < 5)) throw new Error();
      } else if (!values.every(value => value === null)) throw new Error();
      this.cohort.set({ month: selected, assessedAt: assessment, state: state as CohortInspection['state'],
        counts: state === 'available' ? Object.values(cohortLabels).map((label, index) => ({ label, value: Number(values[index]) })) : [] });
    } catch {
      if (generation === this.cohortGeneration)
        this.cohortError.set('Monthly window counts unavailable or malformed. Inspect a completed UTC month with a current staff-MFA session.');
    } finally { if (generation === this.cohortGeneration) this.cohortLoading.set(false); }
  }

  async loadPublic() {
    const generation = ++this.publicGeneration;
    this.publicLoading.set(true); this.publicError.set(''); this.publicRows.set([]); this.publicCleanup.set(null);
    try {
      const response = await this.api.publicAnalyticsObservations();
      if (generation !== this.publicGeneration) return;
      const body = response.body, cleanup = body['cleanup'] as Record<string, unknown> | null;
      const records = body['milestones'] as Record<string, Record<string, unknown>> | null;
      if (response.status !== 200 || Object.keys(body).length !== 5 || body['dictionary_version'] !== 'acquisition-v1'
          || body['basis'] !== 'current_unexpired_public_consent_epochs' || body['funnel_rates_available'] !== false
          || !cleanup || Object.keys(cleanup).length !== 2 || typeof cleanup['expired_pending'] !== 'boolean'
          || typeof cleanup['deadline_missed'] !== 'boolean' || !records || Object.keys(records).length !== 2) throw new Error();
      const rows: Milestone[] = [];
      for (const id of ['public_page_view', 'public_cta_selected'] as const) {
        const row = records[id], grain = 'consent_epoch_route_locale' + (id === 'public_cta_selected' ? '_cta' : '');
        if (!row || Object.keys(row).length !== 3 || row['grain'] !== grain
            || !(row['state'] === 'unavailable' && row['count'] === null
              || row['state'] === 'derivable' && Number.isSafeInteger(row['count']) && Number(row['count']) >= 0)) throw new Error();
        rows.push({ id, label: id === 'public_page_view' ? 'Browser-reported page first server receipts' : 'Browser-reported fixed CTA first server receipts',
          state: row['state'] as Milestone['state'], count: row['count'] as number | null, grain });
      }
      this.publicRows.set(rows);
      this.publicCleanup.set({ expired_pending: cleanup['expired_pending'], deadline_missed: cleanup['deadline_missed'] });
    } catch {
      if (generation === this.publicGeneration)
        this.publicError.set('Public observation counts unavailable or malformed. Inspect with a current staff-MFA session.');
    } finally { if (generation === this.publicGeneration) this.publicLoading.set(false); }
  }

  async load() {
    this.clearCohort();
    const generation = ++this.generation;
    this.loading.set(true);
    this.error.set('');
    try {
      const response = await this.api.acquisitionMilestones();
      if (generation !== this.generation) return;
      const body = response.body;
      if (response.status !== 200 || body['dictionary_version'] !== 'acquisition-v1'
          || body['basis'] !== 'current_retained_operational_records' || body['funnel_rates_available'] !== false
          || !body['milestones'] || typeof body['milestones'] !== 'object') throw new Error();
      const records = body['milestones'] as Record<string, unknown>;
      const rows: Milestone[] = [];
      for (const [id, label] of Object.entries(milestoneLabels) as [MilestoneId, string][]) {
        const row = records[id];
        if (!row || typeof row !== 'object') throw new Error();
        const value = row as Record<string, unknown>;
        const grain = id === 'public_page_view' || id === 'public_cta_selected' ? null
          : id === 'registration_succeeded' || id === 'email_verified' ? 'user'
          : id === 'checkout_initiated' ? 'checkout_attempt' : 'organization';
        if (grain !== null && value['grain'] === grain && value['state'] === 'derivable'
            && Number.isSafeInteger(value['count']) && Number(value['count']) >= 0) {
          rows.push({ id, label, state: 'derivable', count: Number(value['count']), grain });
        } else if (value['state'] === 'unavailable' && value['count'] === null) {
          rows.push({ id, label, state: 'unavailable', count: null });
        } else throw new Error();
      }
      this.milestones.set(rows);
    } catch {
      if (generation !== this.generation) return;
      this.milestones.set([]);
      this.error.set('Milestones are unavailable for this account or session. Sign in with staff MFA and try again.');
    } finally {
      if (generation === this.generation) this.loading.set(false);
    }
  }
}
