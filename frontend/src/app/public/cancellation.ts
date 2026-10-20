import { DOCUMENT } from '@angular/common';
import { Component, inject, OnDestroy } from '@angular/core';
import { Meta } from '@angular/platform-browser';
import { ActivatedRoute, RouterLink } from '@angular/router';

const cancellationTurkish: Record<string, string> = {
  "Cancellation and retained access": "İptal ve korunan erişim",
  "Unreviewed local English/Turkish cancellation draft. Bilingual human approval, legal review and public release are pending. Public trials and payments are not open. This page cannot cancel a subscription or close an account.": "İncelenmemiş yerel İngilizce/Türkçe iptal taslağı. İki dilli insan onayı, yasal inceleme ve herkese açık yayımlama bekleniyor. Herkese açık deneme ve ödeme sunulmaz. Bu sayfa aboneliği iptal edemez veya hesabı kapatamaz.",
  "Trial and deliberate paid conversion": "Deneme ve bilinçli ücretli geçiş",
  "The selected plan has a 30-day no-card trial; expiry does not start an automatic payment. Deliberate owner checkout during an active trial plans an immediate charge and paid-period start, ending the trial immediately. Unused trial time or units do not delay payment. The planned monthly paid subscription renews automatically with disclosed provider totals and cancellation terms. Actual seller approval, checkout, cost and legal acceptance remain release gates.": "Seçili plan 30 günlük kartsız deneme içerir; bitiş otomatik ödeme başlatmaz. Etkin deneme sırasında sahibin bilinçli ödeme adımı, denemeyi hemen bitirerek anında tahsilat ve ücretli dönem başlangıcı planlar. Kullanılmayan deneme süresi veya birimleri ödemeyi ertelemez. Planlanan aylık ücretli abonelik, açıklanan sağlayıcı toplamları ve iptal koşullarıyla otomatik yenilenir. Gerçek satıcı onayı, ödeme akışı, maliyet ve yasal kabul yayımlama koşullarıdır.",
  "Period-end cancellation and provider truth": "Dönem sonunda iptal ve sağlayıcı kayıtları",
  "The planned default is owner-requested period-end cancellation through the authenticated billing flow and hosted Paddle customer portal. Verified paid access continues through the current period, subject to current permissions and limits. Opening a portal or reporting a request does not prove cancellation: current status and effective dates require verified server-side provider reconciliation. Returning after effective cancellation requires a new checkout. This preview opens no portal, sends no request and grants no billing authority.": "Planlanan varsayılan, kimliği doğrulanmış faturalandırma akışı ve Paddle müşteri portalı üzerinden sahibin istediği dönem sonu iptaldir. Doğrulanmış ücretli erişim, güncel izin ve sınırlar kapsamında mevcut dönem boyunca sürer. Portal açmak veya istek bildirmek iptali kanıtlamaz: güncel durum ve etkin tarihler sunucu tarafında doğrulanmış sağlayıcı mutabakatı gerektirir. Etkin iptalden sonra dönüş yeni ödeme adımı gerektirir. Bu ön izleme portal açmaz, istek göndermez ve faturalandırma yetkisi vermez.",
  "Failed payments, refunds and recovery": "Başarısız ödemeler, iadeler ve kurtarma",
  "The selected failed-renewal policy allows seven calendar days of paid service from the verified provider failure time, within normal limits. After grace ends, costly work stops and recurring schedules pause; retained results, authorized export and payment recovery remain subject to policy. Verified recovery does not replay accumulated schedules or reset consumed usage. Refund and dispute outcomes require reconciled provider truth and applicable reviewed terms; period-end cancellation is not an automatic prorated refund. No refund or consumer-law entitlement is decided by this draft.": "Seçili başarısız yenileme politikası, doğrulanmış sağlayıcı hata zamanından itibaren normal sınırlar içinde yedi takvim günü ücretli hizmet sağlar. Süre bitince maliyetli işler durur ve yinelenen programlar duraklar; korunan sonuçlar, yetkili dışa aktarım ve ödeme kurtarma politikaya tabidir. Doğrulanmış kurtarma biriken programları yeniden çalıştırmaz veya kullanımı sıfırlamaz. İade ve uyuşmazlık sonuçları mutabakatı yapılmış sağlayıcı kayıtları ve geçerli incelenmiş koşullar gerektirir; dönem sonu iptal otomatik orantılı iade değildir. Bu taslak iade veya tüketici hukuku hakkı belirlemez.",
  "Retained results and separate closure": "Korunan sonuçlar ve ayrı kapatma",
  "The selected policy plans 90 days of read-only results and authorized export/recovery after trial expiry or effective subscription lapse, then active customer-content deletion within 30 days. Deliberate owner organization closure plans immediate access/work suspension and active deletion within 30 days. Customer-bearing backups then expire through a maximum 35-day rotation after active deletion. Cancellation, organization closure and personal access shutdown are separate; personal shutdown does not erase shared organization data or prove identity erasure. Self-service closure remains disabled. Complete legal export/exclusion and stored-copy lifetime review, hosted deletion deadlines and backup/restore evidence remain unfinished. Downloaded copies remain with recipients.": "Seçili politika, deneme bitişinden veya aboneliğin etkin sona ermesinden sonra 90 gün salt okunur sonuç ve yetkili dışa aktarım/kurtarma, ardından 30 gün içinde etkin müşteri içeriğinin silinmesini planlar. Sahibin bilinçli kuruluş kapatması erişim/işlerin hemen durmasını ve 30 gün içinde etkin silmeyi planlar. Müşteri içeren yedekler etkin silmeden sonra en fazla 35 günlük döngüde sona erer. İptal, kuruluş kapatma ve kişisel erişimi kapatma ayrıdır; kişisel kapatma paylaşılan kuruluş verisini silmez veya kimliğin silindiğini kanıtlamaz. Self servis kapatma devre dışıdır. Tam yasal dışa aktarım/hariç tutma ve saklanan kopya ömrü incelemesi, barındırılan silme süreleri ve yedek/geri yükleme kanıtları tamamlanmamıştır. İndirilen kopyalar alıcılarında kalır.",
  "Read planned pricing and limits": "Planlanan fiyatlandırmayı ve sınırları okuyun",
  "Read data handling and current limits": "Veri işlemeyi ve güncel sınırları okuyun",
  "Read contact and support limits": "İletişim ve destek sınırlarını okuyun",
  "Return to the development home": "Geliştirme ana sayfasına dönün"
};

@Component({
  selector: 'app-cancellation',
  imports: [RouterLink],
  template: `
    <article class="cancellation-draft" [attr.lang]="language">
      <nav aria-label="Language / Dil">
        <a routerLink="/preview/cancellation" lang="en" [attr.aria-current]="language === 'en' ? 'page' : null">English</a>
        · <a routerLink="/preview/tr/cancellation" lang="tr" [attr.aria-current]="language === 'tr' ? 'page' : null">Türkçe (taslak)</a>
      </nav>
      <h1>{{ t("Cancellation and retained access") }}</h1>
      <p role="status">{{ t("Unreviewed local English/Turkish cancellation draft. Bilingual human approval, legal review and public release are pending. Public trials and payments are not open. This page cannot cancel a subscription or close an account.") }}</p>
      <section aria-labelledby="cancellation-0"><h2 id="cancellation-0">{{ t("Trial and deliberate paid conversion") }}</h2><p>{{ t("The selected plan has a 30-day no-card trial; expiry does not start an automatic payment. Deliberate owner checkout during an active trial plans an immediate charge and paid-period start, ending the trial immediately. Unused trial time or units do not delay payment. The planned monthly paid subscription renews automatically with disclosed provider totals and cancellation terms. Actual seller approval, checkout, cost and legal acceptance remain release gates.") }}</p></section>
      <section aria-labelledby="cancellation-1"><h2 id="cancellation-1">{{ t("Period-end cancellation and provider truth") }}</h2><p>{{ t("The planned default is owner-requested period-end cancellation through the authenticated billing flow and hosted Paddle customer portal. Verified paid access continues through the current period, subject to current permissions and limits. Opening a portal or reporting a request does not prove cancellation: current status and effective dates require verified server-side provider reconciliation. Returning after effective cancellation requires a new checkout. This preview opens no portal, sends no request and grants no billing authority.") }}</p></section>
      <section aria-labelledby="cancellation-2"><h2 id="cancellation-2">{{ t("Failed payments, refunds and recovery") }}</h2><p>{{ t("The selected failed-renewal policy allows seven calendar days of paid service from the verified provider failure time, within normal limits. After grace ends, costly work stops and recurring schedules pause; retained results, authorized export and payment recovery remain subject to policy. Verified recovery does not replay accumulated schedules or reset consumed usage. Refund and dispute outcomes require reconciled provider truth and applicable reviewed terms; period-end cancellation is not an automatic prorated refund. No refund or consumer-law entitlement is decided by this draft.") }}</p></section>
      <section aria-labelledby="cancellation-3"><h2 id="cancellation-3">{{ t("Retained results and separate closure") }}</h2><p>{{ t("The selected policy plans 90 days of read-only results and authorized export/recovery after trial expiry or effective subscription lapse, then active customer-content deletion within 30 days. Deliberate owner organization closure plans immediate access/work suspension and active deletion within 30 days. Customer-bearing backups then expire through a maximum 35-day rotation after active deletion. Cancellation, organization closure and personal access shutdown are separate; personal shutdown does not erase shared organization data or prove identity erasure. Self-service closure remains disabled. Complete legal export/exclusion and stored-copy lifetime review, hosted deletion deadlines and backup/restore evidence remain unfinished. Downloaded copies remain with recipients.") }}</p></section>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/pricing' : '/preview/pricing'">{{ t("Read planned pricing and limits") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/data-handling' : '/preview/data-handling'">{{ t("Read data handling and current limits") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/contact' : '/preview/contact'">{{ t("Read contact and support limits") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/home' : '/'">{{ t("Return to the development home") }}</a></p>
    </article>
  `,
  styles: `
    .cancellation-draft { max-width: 52rem; margin-inline: auto; color: #182b36; overflow-wrap: anywhere; }
    nav { display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 1.5rem; }
    section { border-top: 1px solid #b9cfd5; padding-block: 1rem; }
  `,
})
export class Cancellation implements OnDestroy {
  readonly language = inject(ActivatedRoute).snapshot.data['language'] === 'tr' ? 'tr' : 'en';
  private readonly document = inject(DOCUMENT);
  private readonly meta = inject(Meta);
  t(text: string) { return this.language === 'tr' ? cancellationTurkish[text] ?? text : text; }

  constructor() {
    this.document.documentElement.lang = this.language;
    this.meta.updateTag({ name: 'description', content: this.language === 'tr'
      ? 'OrganicSEOOps iptal: incelenmemiş Türkçe taslak; yasal, sağlayıcı ve barındırılan silme kanıtı bekleniyor.'
      : 'OrganicSEOOps cancellation: unreviewed local draft; legal, provider and hosted deletion evidence are pending.' });
  }

  ngOnDestroy() {
    this.document.documentElement.lang = 'en';
    this.meta.updateTag({ name: 'description', content:
      'Development preview of an SEO evidence workflow for agency teams. Public trials and payments are not open.' });
  }
}
