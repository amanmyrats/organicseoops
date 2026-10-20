import { DOCUMENT } from '@angular/common';
import { Component, inject, OnDestroy } from '@angular/core';
import { Meta } from '@angular/platform-browser';
import { ActivatedRoute, RouterLink } from '@angular/router';

@Component({
  selector: 'app-not-found',
  imports: [RouterLink],
  template: `
    <section [attr.lang]="language">
      <nav aria-label="Language / Dil">
        <a routerLink="/404" lang="en" [attr.aria-current]="language === 'en' ? 'page' : null">English</a>
        · <a routerLink="/preview/tr/404" lang="tr" [attr.aria-current]="language === 'tr' ? 'page' : null">Türkçe (taslak)</a>
      </nav>
      @if (language === 'tr') {
        <p role="status">İncelenmemiş yerel Türkçe taslak. İki dilli insan onayı ve herkese açık yayımlama bekleniyor.</p>
        <h1>Sayfa bulunamadı</h1>
        <p>Bu adres geliştirme ön izlemesinde bir sayfayla eşleşmiyor.</p>
        <a routerLink="/preview/tr/home">Türkçe ön izleme ana sayfasına dön</a>
      } @else {
        <p role="status">Unreviewed local page draft. Bilingual human approval and public release are pending.</p>
        <h1>Page not found</h1>
        <p>This address does not match a page in the development preview.</p>
        <a routerLink="/">Return to the preview home</a>
      }
    </section>
  `,
})
export class NotFound implements OnDestroy {
  readonly language = inject(ActivatedRoute).snapshot.data['language'] === 'tr' ? 'tr' : 'en';
  private readonly document = inject(DOCUMENT);
  private readonly meta = inject(Meta);

  constructor() {
    this.document.documentElement.lang = this.language;
    this.meta.updateTag({ name: 'description', content: this.language === 'tr'
      ? 'OrganicSEOOps sayfa bulunamadı ön izlemesi: incelenmemiş Türkçe taslak.'
      : 'OrganicSEOOps page not found development preview: unreviewed local draft.' });
  }

  ngOnDestroy() {
    this.document.documentElement.lang = 'en';
    this.meta.updateTag({ name: 'description', content:
      'Development preview of an SEO evidence workflow for agency teams. Public trials and payments are not open.' });
  }
}
