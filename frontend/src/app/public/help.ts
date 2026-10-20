import { DOCUMENT } from '@angular/common';
import { Component, inject, OnDestroy } from '@angular/core';
import { Meta } from '@angular/platform-browser';
import { ActivatedRoute, RouterLink } from '@angular/router';

const helpTurkish: Record<string, string> = {
  "Read contact and support limits": "İletişim ve destek sınırlarını okuyun",
  "Help and methodology": "Yardım ve metodoloji",
  "Unreviewed local English/Turkish help draft. Bilingual human approval and public release are pending. Public trials and payments are not open.": "İncelenmemiş yerel İngilizce/Türkçe yardım taslağı. İki dilli insan onayı ve herkese açık yayımlama bekleniyor. Herkese açık deneme ve ödeme sunulmaz.",
  "Getting started": "Başlarken",
  "Use a local preview account only for authorized development and testing. Select the organization and project before reviewing a source or running a job. Organizations own access and billing; projects separate domain evidence. Do not enter customer data in this preview.": "Yerel ön izleme hesabını yalnızca yetkili geliştirme ve test için kullanın. Kaynak incelemeden veya iş çalıştırmadan önce kuruluşu ve projeyi seçin. Erişim ve faturalandırma kuruluşlara aittir; projeler alan adı kanıtlarını ayırır. Bu ön izlemeye müşteri verisi girmeyin.",
  "Sources and coverage": "Kaynaklar ve kapsam",
  "Inspect the source, property, date range and coverage before comparing results. A CSV import is supplied data, not a live connection. Missing or partial data is not zero. Source access, available history and provider limits require separate verification; a connected source does not establish complete coverage.": "Sonuçları karşılaştırmadan önce kaynağı, mülkü, tarih aralığını ve kapsamı inceleyin. CSV içe aktarımı sağlanan veridir; canlı bağlantı değildir. Eksik veya kısmi veri sıfır değildir. Kaynak erişimi, kullanılabilir geçmiş ve sağlayıcı sınırları ayrıca doğrulanmalıdır; bağlı bir kaynak eksiksiz kapsam göstermez.",
  "Evidence and human approval": "Kanıt ve insan onayı",
  "Keep observations, calculations, estimates and AI drafts separate. Inspect original evidence and limitations before accepting a recommendation. Content and remediation require human approval. A recorded change or before/after comparison alone does not prove a search outcome or causation.": "Gözlemleri, hesaplamaları, tahminleri ve yapay zekâ taslaklarını ayrı tutun. Öneriyi kabul etmeden önce özgün kanıtları ve sınırlamaları inceleyin. İçerik ve düzeltme işlemleri insan onayı gerektirir. Kaydedilmiş değişiklik veya öncesi/sonrası karşılaştırması tek başına arama sonucunu veya nedenselliği kanıtlamaz.",
  "Jobs, cancellation and retry": "İşler, iptal ve yeniden deneme",
  "Check the project, job identifier, stage and error before retrying. Queued, running, partial, failed and canceled states are different. Cancellation is a request, not proof that work stopped or costs were refunded. After an uncertain response, inspect the existing job or command status before an explicit retry; do not assume a new submission is safe.": "Yeniden denemeden önce projeyi, iş kimliğini, aşamayı ve hatayı kontrol edin. Sırada, çalışıyor, kısmi, başarısız ve iptal edilmiş durumları farklıdır. İptal bir istektir; işin durduğunu veya maliyetlerin iade edildiğini kanıtlamaz. Belirsiz yanıt sonrasında açıkça yeniden denemeden önce mevcut işi veya komut durumunu inceleyin; yeni gönderimin güvenli olduğunu varsaymayın.",
  "Accounts, billing and retention": "Hesaplar, faturalandırma ve saklama",
  "Account access, organization ownership, subscriptions and project permissions are separate. Ask the current organization owner about billing and organization exports. A checkout link or browser return does not confirm paid access. An export is not proof of complete legal disclosure, and a closure status is not proof of hosted deletion or backup expiry. Reviewed commercial and retention terms remain pending for public release.": "Hesap erişimi, kuruluş sahipliği, abonelikler ve proje izinleri ayrıdır. Faturalandırma ve kuruluş dışa aktarımları için güncel kuruluş sahibine başvurun. Ödeme bağlantısı veya tarayıcı dönüşü ücretli erişimi doğrulamaz. Dışa aktarım eksiksiz yasal açıklamayı kanıtlamaz; kapatma durumu barındırılan verilerin silindiğini veya yedeklerin süresinin dolduğunu kanıtlamaz. İncelenmiş ticari ve saklama koşulları herkese açık yayımlama için bekleniyor.",
  "Accessibility and support limits": "Erişilebilirlik ve destek sınırları",
  "Core keyboard, narrow-screen and assistive-technology acceptance remains unverified. This draft provides no public support endpoint or response-time commitment. In an authorized local support flow, use safe project/job identifiers and a concise problem description. Never include passwords, API keys, OAuth tokens or private exports. Turkish product and support coverage remains partial and unreviewed.": "Temel klavye, dar ekran ve yardımcı teknoloji kabulü henüz doğrulanmadı. Bu taslak herkese açık destek adresi veya yanıt süresi taahhüdü sunmaz. Yetkili yerel destek akışında güvenli proje/iş kimlikleri ve kısa sorun açıklaması kullanın. Parola, API anahtarı, OAuth belirteci veya özel dışa aktarım eklemeyin. Türkçe ürün ve destek kapsamı kısmi ve incelenmemiştir.",
  "Inspect a synthetic action example": "Sentetik aksiyon örneğini inceleyin",
  "Read development status": "Geliştirme durumunu okuyun",
  "Read local terms draft": "Yerel koşullar taslağını okuyun",
  "Read local privacy draft": "Yerel gizlilik taslağını okuyun",
  "Return to the development home": "Geliştirme ana sayfasına dön"
};

@Component({
  selector: 'app-help',
  imports: [RouterLink],
  template: `
    <article class="help-draft" [attr.lang]="language">
      <nav aria-label="Language / Dil">
        <a routerLink="/preview/help" lang="en" [attr.aria-current]="language === 'en' ? 'page' : null">English</a>
        · <a routerLink="/preview/tr/help" lang="tr" [attr.aria-current]="language === 'tr' ? 'page' : null">Türkçe (taslak)</a>
      </nav>
      <p role="status">{{ t("Unreviewed local English/Turkish help draft. Bilingual human approval and public release are pending. Public trials and payments are not open.") }}</p>
      <h1>{{ t("Help and methodology") }}</h1>
      <section aria-labelledby="help-0"><h2 id="help-0">{{ t("Getting started") }}</h2><p>{{ t("Use a local preview account only for authorized development and testing. Select the organization and project before reviewing a source or running a job. Organizations own access and billing; projects separate domain evidence. Do not enter customer data in this preview.") }}</p></section>
      <section aria-labelledby="help-1"><h2 id="help-1">{{ t("Sources and coverage") }}</h2><p>{{ t("Inspect the source, property, date range and coverage before comparing results. A CSV import is supplied data, not a live connection. Missing or partial data is not zero. Source access, available history and provider limits require separate verification; a connected source does not establish complete coverage.") }}</p></section>
      <section aria-labelledby="help-2"><h2 id="help-2">{{ t("Evidence and human approval") }}</h2><p>{{ t("Keep observations, calculations, estimates and AI drafts separate. Inspect original evidence and limitations before accepting a recommendation. Content and remediation require human approval. A recorded change or before/after comparison alone does not prove a search outcome or causation.") }}</p></section>
      <section aria-labelledby="help-3"><h2 id="help-3">{{ t("Jobs, cancellation and retry") }}</h2><p>{{ t("Check the project, job identifier, stage and error before retrying. Queued, running, partial, failed and canceled states are different. Cancellation is a request, not proof that work stopped or costs were refunded. After an uncertain response, inspect the existing job or command status before an explicit retry; do not assume a new submission is safe.") }}</p></section>
      <section aria-labelledby="help-4"><h2 id="help-4">{{ t("Accounts, billing and retention") }}</h2><p>{{ t("Account access, organization ownership, subscriptions and project permissions are separate. Ask the current organization owner about billing and organization exports. A checkout link or browser return does not confirm paid access. An export is not proof of complete legal disclosure, and a closure status is not proof of hosted deletion or backup expiry. Reviewed commercial and retention terms remain pending for public release.") }}</p></section>
      <section aria-labelledby="help-5"><h2 id="help-5">{{ t("Accessibility and support limits") }}</h2><p>{{ t("Core keyboard, narrow-screen and assistive-technology acceptance remains unverified. This draft provides no public support endpoint or response-time commitment. In an authorized local support flow, use safe project/job identifiers and a concise problem description. Never include passwords, API keys, OAuth tokens or private exports. Turkish product and support coverage remains partial and unreviewed.") }}</p></section>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/contact' : '/preview/contact'">{{ t("Read contact and support limits") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/sample-report' : '/sample-report'">{{ t("Inspect a synthetic action example") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/terms' : '/preview/terms'">{{ t("Read local terms draft") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/privacy' : '/preview/privacy'">{{ t("Read local privacy draft") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr' : '/preview'">{{ t("Read development status") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/home' : '/'">{{ t("Return to the development home") }}</a></p>
    </article>
  `,
  styles: `
    .help-draft { max-width: 52rem; margin-inline: auto; color: #182b36; overflow-wrap: anywhere; }
    nav { display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 1.5rem; }
    section { border-top: 1px solid #b9cfd5; padding-block: 1rem; }
  `,
})
export class Help implements OnDestroy {
  readonly language = inject(ActivatedRoute).snapshot.data['language'] === 'tr' ? 'tr' : 'en';
  private readonly document = inject(DOCUMENT);
  private readonly meta = inject(Meta);
  t(text: string) { return this.language === 'tr' ? helpTurkish[text] ?? text : text; }

  constructor() {
    this.document.documentElement.lang = this.language;
    this.meta.updateTag({ name: 'description', content: this.language === 'tr'
      ? 'OrganicSEOOps yardım ve metodoloji: incelenmemiş Türkçe taslak; kaynak, kanıt, iş, hesap ve destek sınırları.'
      : 'OrganicSEOOps help and methodology: unreviewed local draft covering sources, evidence, jobs, accounts and support limits.' });
  }

  ngOnDestroy() {
    this.document.documentElement.lang = 'en';
    this.meta.updateTag({ name: 'description', content:
      'Development preview of an SEO evidence workflow for agency teams. Public trials and payments are not open.' });
  }
}
