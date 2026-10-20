import { Component, inject, input } from '@angular/core';
import { AnalyticsConsent } from './analytics-consent';

const analyticsExplanations = [
  [
    "Optional first-party acquisition analytics is off unless you allow it. Necessary sign-in, billing and customer work do not depend on this choice.",
    "İzin vermediğiniz sürece isteğe bağlı birinci taraf edinim analitiği kapalıdır. Gerekli oturum açma, faturalama ve müşteri işlemleri bu tercihe bağlı değildir."
  ],
  [
    "Current draft routes collect no analytics. Reviewed public routes additionally require a checked server publication policy. Explicit allow can start one original fifteen-minute server consent epoch, kept only in this open page's memory; there is no automatic renewal. Reload, leaving the page or moving to an unapproved/private route resets it. No analytics cookies, browser storage, visitor identifiers or account/customer-data linkage are used.",
    "Mevcut taslak yollar analitik toplamaz. İncelenmiş herkese açık yollar ayrıca doğrulanmış bir sunucu yayımlama politikası gerektirir. Açık izin, yalnızca bu açık sayfanın belleğinde tutulan ilk on beş dakikalık sunucu onay dönemini başlatabilir; otomatik yenileme yoktur. Yeniden yükleme, sayfadan ayrılma veya onaylanmamış/özel bir yola geçme bunu sıfırlar. Analitik çerezleri, tarayıcı depolaması, ziyaretçi tanımlayıcıları veya hesap/müşteri verisi bağlantısı kullanılmaz."
  ],
  [
    "Only browser-reported approved route/locale and fixed CTA first server receipts are counted, once per epoch; these are not unique visitors or verified views/clicks. Reject/reset requests erasure of that epoch's observations. Expired records are excluded immediately and removed within seventy-five minutes of issuance under healthy cleanup. Database backups may retain them for up to thirty-five days after active deletion. An unconfirmed response is never automatically replayed; expiry and cleanup still apply.",
    "Yalnızca tarayıcının bildirdiği onaylı yol/dil ve sabit eylem çağrısının ilk sunucu alındıları dönem başına bir kez sayılır; bunlar benzersiz ziyaretçiler veya doğrulanmış görüntülemeler/tıklamalar değildir. Reddetme/sıfırlama, o dönemin gözlemlerinin silinmesini ister. Süresi dolan kayıtlar hemen hesaplama dışında tutulur ve sağlıklı temizleme altında oluşturulmalarından itibaren yetmiş beş dakika içinde kaldırılır. Veritabanı yedekleri, etkin silmeden sonra bunları otuz beş güne kadar tutabilir. Doğrulanmamış yanıt asla otomatik olarak tekrar gönderilmez; süre sonu ve temizleme yine geçerlidir."
  ]
];

const analyticsTurkish: Record<string, string> = {
  "Analytics preferences": "Analitik tercihleri",
  "Reject optional analytics": "İsteğe bağlı analitiği reddet",
  "Allow optional analytics": "İsteğe bağlı analitiğe izin ver",
  "Reset choice": "Tercihi sıfırla",
  "No choice — optional analytics is off.": "Tercih yok — isteğe bağlı analitik kapalı.",
  "Rejected — optional analytics is off.": "Reddedildi — isteğe bağlı analitik kapalı.",
  "Allowed for this open page only — no analytics collected in this preview.": "Yalnızca bu açık sayfa için izin verildi — bu ön izlemede analitik toplanmaz.",
  "Analytics is off. Withdrawal could not be confirmed; original expiry and cleanup still apply.": "Analitik kapalı. Geri çekme doğrulanamadı; ilk süre sonu ve temizleme yine geçerlidir.",
  "Requesting an optional fifteen-minute consent epoch.": "İsteğe bağlı on beş dakikalık onay dönemi isteniyor.",
  "Original consent epoch expired — allow again explicitly to start a new one.": "İlk onay döneminin süresi doldu — yenisini başlatmak için yeniden açıkça izin verin.",
  "Optional analytics enabled for this original fifteen-minute epoch.": "İsteğe bağlı analitik bu ilk on beş dakikalık dönem için etkin.",
  "Consent epoch unavailable or unconfirmed — no automatic retry or renewal. Analytics is off.": "Onay dönemi kullanılamıyor veya doğrulanmadı — otomatik yeniden deneme veya yenileme yoktur. Analitik kapalı.",
  "Original consent epoch expired — analytics is off.": "İlk onay döneminin süresi doldu — analitik kapalı.",
  "Observation unavailable or unconfirmed — it will not be replayed automatically.": "Gözlem kullanılamıyor veya doğrulanmadı — otomatik olarak tekrar gönderilmez."
};

@Component({
  selector: 'app-analytics-preferences',
  template: `
    <details [attr.lang]="language()">
      <summary>{{ t("Analytics preferences") }}</summary>
      @for (copy of explanations; track $index) { <p>{{ copy[language() === 'tr' ? 1 : 0] }}</p> }
      <div class="choices">
        <button type="button" (click)="consent.choose(false)">{{ t("Reject optional analytics") }}</button>
        <button type="button" (click)="consent.choose(true)">{{ t("Allow optional analytics") }}</button>
        <button type="button" (click)="consent.reset()">{{ t("Reset choice") }}</button>
      </div>
      <p role="status">{{ t(consent.status()) }}</p>
    </details>
  `,
  styles: `
    details { margin-block: 1rem; }
    summary { cursor: pointer; }
    .choices { display: flex; flex-wrap: wrap; gap: 0.75rem; }
    button { padding: 0.6rem 0.8rem; font: inherit; }
  `,
})
export class AnalyticsPreferences {
  readonly explanations = analyticsExplanations;
  readonly consent = inject(AnalyticsConsent);
  readonly language = input<'en' | 'tr'>('en');
  t(text: string) { return this.language() === 'tr' ? analyticsTurkish[text] ?? text : text; }
}
