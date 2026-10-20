import { DOCUMENT } from '@angular/common';
import { Component, inject, OnDestroy } from '@angular/core';
import { Meta } from '@angular/platform-browser';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ContactSubmission } from './contact-submission';

const contactTurkish: Record<string, string> = {
  "Read accessibility target and evidence": "Erişilebilirlik hedefini ve kanıtları okuyun",
  "Contact and support in this development preview": "Bu geliştirme ön izlemesinde iletişim ve destek",
  "Unreviewed local English/Turkish contact draft. Bilingual human approval and public release are pending. There is no public contact submission channel in this draft. Public trials and payments are not open.": "İncelenmemiş yerel İngilizce/Türkçe iletişim taslağı. İki dilli insan onayı ve herkese açık yayımlama bekleniyor. Bu taslakta herkese açık iletişim gönderim kanalı yoktur. Herkese açık deneme ve ödeme sunulmaz.",
  "Prepare a safe question": "Güvenli bir soru hazırlayın",
  "Describe the product-access, source, job, billing, privacy or accessibility question briefly. Include only safe request/job identifiers from a project you may access, the observed state and the action you expected. Do not send passwords, API keys, OAuth tokens, personal customer details, raw logs or copied private exports. A support reference does not grant access to a job or another project. Until configured local intake is deliberately opened below, this page collects no question or attachment.": "Ürün erişimi, kaynak, iş, faturalandırma, gizlilik veya erişilebilirlik sorunuzu kısaca açıklayın. Yalnızca erişim izniniz olan projeden güvenli istek/iş kimliklerini, gözlemlenen durumu ve beklediğiniz aksiyonu ekleyin. Parola, API anahtarı, OAuth belirteci, müşterilerin kişisel bilgileri, ham günlük veya kopyalanmış özel dışa aktarım göndermeyin. Destek referansı bir işe veya başka projeye erişim yetkisi vermez. Aşağıdaki yapılandırılmış yerel gönderim bilinçli olarak açılana kadar bu sayfa soru veya ek toplamaz.",
  "Private project support for authorized preview accounts": "Yetkili ön izleme hesapları için özel proje desteği",
  "For authorized local testing, sign in with an existing preview account, choose the correct organization and project, then open its reports page and Your private project support requests. The existing flow stores a deliberate plain-text question with a no-sensitive-data acknowledgment and optional retained job ID. Only its creator with current project access and explicitly permitted MFA-authenticated support staff can inspect the request; the organization owner can include it in a customer export. It is not an anonymous public contact form. Do not enter real customer data for this preview.": "Yetkili yerel test için mevcut ön izleme hesabıyla oturum açın, doğru kuruluşu ve projeyi seçin, ardından raporlar sayfasındaki Özel proje destek istekleriniz bölümünü açın. Mevcut akış, hassas veri içermediği onayı ve isteğe bağlı saklanan iş kimliğiyle bilinçli gönderilen düz metin soruyu kaydeder. İsteği yalnızca güncel proje erişimi olan oluşturan kişi ve açıkça yetkilendirilmiş MFA ile doğrulanmış destek personeli inceleyebilir; kuruluş sahibi isteği müşteri dışa aktarımına dahil edebilir. Bu, anonim herkese açık iletişim formu değildir. Bu ön izlemeye gerçek müşteri verisi girmeyin.",
  "Stored status is not delivery or resolution": "Kaydedilmiş durum, teslimat veya çözüm değildir",
  "Received means stored as a support record, not staff response, email delivery or a promised response time. Inspect your own request history and retained responses in the same project. Attachments and automatic support email delivery are unavailable. A support status does not retry a job, fix a website or confirm deletion. After an uncertain submission, inspect current history before explicitly retrying the unchanged request and key; do not send a duplicate with a new key.": "Alındı durumu destek kaydı olarak saklandığı anlamına gelir; personel yanıtı, e-posta teslimatı veya taahhüt edilen yanıt süresi değildir. Aynı projede kendi istek geçmişinizi ve saklanan yanıtları inceleyin. Ekler ve otomatik destek e-postası teslimatı kullanılamaz. Destek durumu bir işi yeniden denemez, web sitesini düzeltmez veya silmeyi doğrulamaz. Belirsiz gönderimden sonra değişmemiş isteği ve anahtarı açıkça yeniden denemeden önce güncel geçmişi inceleyin; yeni anahtarla yinelenen gönderim yapmayın.",
  "Public contact and language readiness": "Herkese açık iletişim ve dil hazırlığı",
  "A public sales, privacy or accessibility contact destination, staffed service and approved disclosures remain pending owner confirmation. No address, response-time commitment or emergency service is supplied here. English and Turkish are the planned product/support languages; actual coverage and bilingual human approval remain unfinished. Core keyboard, narrow-screen and assistive-technology acceptance is still unverified. Read the available help and preview-status pages while these public routes remain unpublished.": "Herkese açık satış, gizlilik veya erişilebilirlik iletişim hedefi, personelli hizmet ve onaylı açıklamalar sahibin onayını bekliyor. Burada adres, yanıt süresi taahhüdü veya acil hizmet sunulmaz. İngilizce ve Türkçe planlanan ürün/destek dilleridir; gerçek kapsam ve iki dilli insan onayı tamamlanmamıştır. Temel klavye, dar ekran ve yardımcı teknoloji kabulü hâlâ doğrulanmamıştır. Bu herkese açık yollar yayımlanmamışken mevcut yardım ve ön izleme durumu sayfalarını okuyun.",
  "Sign in to an existing preview account": "Mevcut ön izleme hesabıyla oturum açın",
  "Read help and methodology": "Yardım ve metodolojiyi okuyun",
  "Read development status": "Geliştirme durumunu okuyun",
  "Read local terms draft": "Yerel koşullar taslağını okuyun",
  "Read local privacy draft": "Yerel gizlilik taslağını okuyun",
  "Return to the development home": "Geliştirme ana sayfasına dönün"
};

@Component({
  selector: 'app-contact',
  imports: [RouterLink, ContactSubmission],
  template: `
    <article class="contact-draft" [attr.lang]="language">
      <nav aria-label="Language / Dil">
        <a routerLink="/preview/contact" lang="en" [attr.aria-current]="language === 'en' ? 'page' : null">English</a>
        · <a routerLink="/preview/tr/contact" lang="tr" [attr.aria-current]="language === 'tr' ? 'page' : null">Türkçe (taslak)</a>
      </nav>
      <h1>{{ t("Contact and support in this development preview") }}</h1>
      <p role="status">{{ t("Unreviewed local English/Turkish contact draft. Bilingual human approval and public release are pending. There is no public contact submission channel in this draft. Public trials and payments are not open.") }}</p>
      <section aria-labelledby="contact-0"><h2 id="contact-0">{{ t("Prepare a safe question") }}</h2><p>{{ t("Describe the product-access, source, job, billing, privacy or accessibility question briefly. Include only safe request/job identifiers from a project you may access, the observed state and the action you expected. Do not send passwords, API keys, OAuth tokens, personal customer details, raw logs or copied private exports. A support reference does not grant access to a job or another project. Until configured local intake is deliberately opened below, this page collects no question or attachment.") }}</p></section>
      <section aria-labelledby="contact-1"><h2 id="contact-1">{{ t("Private project support for authorized preview accounts") }}</h2><p>{{ t("For authorized local testing, sign in with an existing preview account, choose the correct organization and project, then open its reports page and Your private project support requests. The existing flow stores a deliberate plain-text question with a no-sensitive-data acknowledgment and optional retained job ID. Only its creator with current project access and explicitly permitted MFA-authenticated support staff can inspect the request; the organization owner can include it in a customer export. It is not an anonymous public contact form. Do not enter real customer data for this preview.") }}</p></section>
      <section aria-labelledby="contact-2"><h2 id="contact-2">{{ t("Stored status is not delivery or resolution") }}</h2><p>{{ t("Received means stored as a support record, not staff response, email delivery or a promised response time. Inspect your own request history and retained responses in the same project. Attachments and automatic support email delivery are unavailable. A support status does not retry a job, fix a website or confirm deletion. After an uncertain submission, inspect current history before explicitly retrying the unchanged request and key; do not send a duplicate with a new key.") }}</p></section>
      <section aria-labelledby="contact-3"><h2 id="contact-3">{{ t("Public contact and language readiness") }}</h2><p>{{ t("A public sales, privacy or accessibility contact destination, staffed service and approved disclosures remain pending owner confirmation. No address, response-time commitment or emergency service is supplied here. English and Turkish are the planned product/support languages; actual coverage and bilingual human approval remain unfinished. Core keyboard, narrow-screen and assistive-technology acceptance is still unverified. Read the available help and preview-status pages while these public routes remain unpublished.") }}</p></section>
      <app-contact-submission [language]="language" />
      <p><a routerLink="/account/login">{{ t("Sign in to an existing preview account") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/accessibility' : '/preview/accessibility'">{{ t("Read accessibility target and evidence") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/help' : '/preview/help'">{{ t("Read help and methodology") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/terms' : '/preview/terms'">{{ t("Read local terms draft") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/privacy' : '/preview/privacy'">{{ t("Read local privacy draft") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr' : '/preview'">{{ t("Read development status") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/home' : '/'">{{ t("Return to the development home") }}</a></p>
    </article>
  `,
  styles: `
    .contact-draft { max-width: 52rem; margin-inline: auto; color: #182b36; overflow-wrap: anywhere; }
    nav { display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 1.5rem; }
    section { border-top: 1px solid #b9cfd5; padding-block: 1rem; }
  `,
})
export class Contact implements OnDestroy {
  readonly language = inject(ActivatedRoute).snapshot.data['language'] === 'tr' ? 'tr' : 'en';
  private readonly document = inject(DOCUMENT);
  private readonly meta = inject(Meta);
  t(text: string) { return this.language === 'tr' ? contactTurkish[text] ?? text : text; }

  constructor() {
    this.document.documentElement.lang = this.language;
    this.meta.updateTag({ name: 'description', content: this.language === 'tr'
      ? 'OrganicSEOOps iletişim ve destek: incelenmemiş Türkçe taslak; herkese açık iletişim kanalı ve yanıt taahhüdü yoktur.'
      : 'OrganicSEOOps contact and support: unreviewed local draft; no public contact channel or response commitment.' });
  }

  ngOnDestroy() {
    this.document.documentElement.lang = 'en';
    this.meta.updateTag({ name: 'description', content:
      'Development preview of an SEO evidence workflow for agency teams. Public trials and payments are not open.' });
  }
}
