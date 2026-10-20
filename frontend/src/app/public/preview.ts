import { DOCUMENT } from '@angular/common';
import { Component, inject, OnDestroy } from '@angular/core';
import { Meta } from '@angular/platform-browser';
import { ActivatedRoute, RouterLink } from '@angular/router';

@Component({
  selector: 'app-preview',
  imports: [RouterLink],
  template: `
    <section [attr.lang]="language">
    <nav aria-label="Language / Dil">
      <a routerLink="/preview" lang="en" [attr.aria-current]="language === 'en' ? 'page' : null">English</a>
      · <a routerLink="/preview/tr" lang="tr" [attr.aria-current]="language === 'tr' ? 'page' : null">Türkçe (taslak)</a>
    </nav>
    @if (language === 'tr') {
      <h1>Geliştirme durumu</h1>
      <p>Bu Türkçe metin, iki dilli insan incelemesi bekleyen bir taslaktır. Türkçe uygulama ve e-posta desteğinin hazır olduğunu göstermez.</p>
      <p>Ön yüzün temel yapısı geliştiriliyor. Bu ön izleme müşteri verisi veya ölçülmüş SEO sonuçları içermez.</p>
      <p>Ön izleme sayfaları derleme sırasında HTML olarak oluşturulur. Hesap ve uygulama ön izlemeleri tarayıcınızda yüklenir. Seçili yerel arayüzlerin incelenmemiş Türkçe taslakları vardır; kapsam kısmidir ve üretim ortamı İngilizce kullanır.</p>
      <p>Ürün özellikleri, teklifler ve herkese açık lansman hâlâ hazırlanıyor.</p>
      <h2 id="terms">Geliştirme koşulları</h2>
      <p>Yerel ön izleme hesapları yalnızca yetkili geliştirme ve test içindir. Kuruluş, deneme süresi, abonelik veya hizmet taahhüdü oluşturmazlar.</p>
      <h2 id="privacy">Gizlilik bildirimi</h2>
      <p>Yerel ön izleme, hesap doğrulama ve oturum açma için e-posta adresi kullanır. Müşteri verisi girmeyin. Üretim ortamının saklama, destek ve iletişim bilgileri lansmandan önce yayımlanacaktır.</p>
      <a routerLink="/">İngilizce ön izleme ana sayfasına dön</a>
    } @else {
    <h1>Development status</h1>
    <p>This copy awaits bilingual human review. The Turkish draft does not establish Turkish application or email availability.</p>
    <p>The frontend foundation is being built. This preview contains no customer data or measured SEO results.</p>
    <p>Public preview pages are generated as HTML at build time. Account and application previews load in your browser. Selected local interfaces have unreviewed Turkish drafts; coverage is partial and production uses English.</p>
    <p>Product features, offers and the public launch are still being prepared.</p>
    <h2 id="terms">Development terms</h2>
    <p>Local preview accounts are for authorized development and testing only. They do not create an organization, trial, subscription or service commitment.</p>
    <h2 id="privacy">Privacy notice</h2>
    <p>The local preview uses an email address for account verification and sign-in. Do not enter customer data. Production retention, support and contact details will be published before launch.</p>
    <a routerLink="/">Return to the preview home</a>
    }
    </section>
  `,
})
export class Preview implements OnDestroy {
  readonly language = inject(ActivatedRoute).snapshot.data['language'] === 'tr' ? 'tr' : 'en';
  private readonly document = inject(DOCUMENT);
  private readonly meta = inject(Meta);

  constructor() {
    this.document.documentElement.lang = this.language;
    this.meta.updateTag({ name: 'description', content: this.language === 'tr'
      ? 'OrganicSEOOps geliştirme durumu: insan incelemesi bekleyen Türkçe taslak. Herkese açık deneme ve ödeme sunulmaz.'
      : 'OrganicSEOOps development status: unreviewed locale drafts. Public trials and payments are not open.' });
  }

  ngOnDestroy() {
    // A direct prerendered Turkish entry also starts with Turkish metadata.
    this.document.documentElement.lang = 'en';
    this.meta.updateTag({ name: 'description', content:
      'Development preview of an SEO evidence workflow for agency teams. Public trials and payments are not open.' });
  }
}
