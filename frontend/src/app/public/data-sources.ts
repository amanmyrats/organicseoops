import { DOCUMENT } from '@angular/common';
import { Component, inject, OnDestroy } from '@angular/core';
import { Meta } from '@angular/platform-browser';
import { ActivatedRoute, RouterLink } from '@angular/router';

const sourcesTurkish: Record<string, string> = {
  "SEO data sources, scope and readiness": "SEO veri kaynakları, kapsam ve hazırlık",
  "Unreviewed local English/Turkish source-readiness draft. Bilingual human approval and public release are pending. This matrix is not live availability.": "İncelenmemiş yerel İngilizce/Türkçe kaynak hazırlığı taslağı. İki dilli insan onayı ve herkese açık yayımlama bekleniyor. Bu tablo canlı kullanılabilirliği göstermez.",
  "Development evidence and remaining source gates": "Geliştirme kanıtları ve kalan kaynak gereklilikleri",
  "Source": "Kaynak",
  "Local status": "Yerel durum",
  "Coverage limit": "Kapsam sınırı",
  "Read the evidence before comparing numbers": "Sayıları karşılaştırmadan önce kanıtları okuyun",
  "Check the project, source or property, collected date, reporting window and dimensions. Keep measurements, estimates and AI interpretation separate. Missing, disconnected, partial and stale states are not zero or a passing result. Local fixtures do not establish customer access, quotas, licensing, freshness or public readiness.": "Projeyi, kaynağı veya mülkü, toplanma tarihini, raporlama dönemini ve boyutları kontrol edin. Ölçümleri, tahminleri ve yapay zekâ yorumunu ayrı tutun. Eksik, bağlantısız, kısmi ve eski durumlar sıfır veya başarılı sonuç değildir. Yerel test verileri müşteri erişimini, kotaları, lisanslamayı, güncelliği veya herkese açık hazırlığı göstermez.",
  "Read help and methodology": "Yardım ve metodolojiyi okuyun",
  "Inspect a synthetic action example": "Sentetik aksiyon örneğini inceleyin",
  "Return to the development home": "Geliştirme ana sayfasına dön",
  "Search Console CSV": "Search Console CSV",
  "Local import workflow": "Yerel içe aktarma akışı",
  "Supplied rows and dates; not a live property connection or complete search dataset.": "Sağlanan satırlar ve tarihler; canlı mülk bağlantısı veya eksiksiz arama veri kümesi değildir.",
  "Search Console OAuth and Search Analytics": "Search Console OAuth ve Search Analytics",
  "Local fixture coverage; real source grants and provider acceptance pending": "Yerel test verileriyle kapsam; gerçek kaynak izinleri ve sağlayıcı kabulü bekleniyor",
  "Keep the selected property, dimensions, observation dates and partial coverage visible.": "Seçili mülkü, boyutları, gözlem tarihlerini ve kısmi kapsamı görünür tutun.",
  "Google Analytics": "Google Analytics",
  "Local workflow; real property and measurement-quality review pending": "Yerel iş akışı; gerçek mülk ve ölçüm kalitesi incelemesi bekleniyor",
  "A report does not verify event instrumentation or establish causation.": "Rapor, olay ölçüm kurulumunu doğrulamaz veya nedensellik göstermez.",
  "PageSpeed Insights and CrUX": "PageSpeed Insights ve CrUX",
  "Local fixture coverage; real-provider acceptance pending": "Yerel test verileriyle kapsam; gerçek sağlayıcı kabulü bekleniyor",
  "Keep lab observations and available field data separate; missing field data is unknown.": "Laboratuvar gözlemlerini ve kullanılabilir saha verilerini ayrı tutun; eksik saha verisi bilinmiyor durumundadır.",
  "Other external datasets": "Diğer dış veri kümeleri",
  "Planned or unavailable unless separately supported and verified": "Ayrıca desteklenip doğrulanmadıkça planlı veya kullanılamıyor",
  "A crawl does not establish complete backlinks, search volumes, rankings or competitor traffic.": "Tarama, eksiksiz geri bağlantıları, arama hacimlerini, sıralamaları veya rakip trafiğini göstermez."
};

@Component({
  selector: 'app-data-sources',
  imports: [RouterLink],
  template: `
    <article class="sources-draft" [attr.lang]="language">
      <nav aria-label="Language / Dil">
        <a routerLink="/preview/data-sources" lang="en" [attr.aria-current]="language === 'en' ? 'page' : null">English</a>
        · <a routerLink="/preview/tr/data-sources" lang="tr" [attr.aria-current]="language === 'tr' ? 'page' : null">Türkçe (taslak)</a>
      </nav>
      <p role="status">{{ t("Unreviewed local English/Turkish source-readiness draft. Bilingual human approval and public release are pending. This matrix is not live availability.") }}</p>
      <h1>{{ t("SEO data sources, scope and readiness") }}</h1>
      <table>
        <caption>{{ t("Development evidence and remaining source gates") }}</caption>
        <thead><tr><th scope="col">{{ t("Source") }}</th><th scope="col">{{ t("Local status") }}</th><th scope="col">{{ t("Coverage limit") }}</th></tr></thead>
        <tbody>
          <tr><th scope="row">{{ t("Search Console CSV") }}</th><td>{{ t("Local import workflow") }}</td><td>{{ t("Supplied rows and dates; not a live property connection or complete search dataset.") }}</td></tr>
          <tr><th scope="row">{{ t("Search Console OAuth and Search Analytics") }}</th><td>{{ t("Local fixture coverage; real source grants and provider acceptance pending") }}</td><td>{{ t("Keep the selected property, dimensions, observation dates and partial coverage visible.") }}</td></tr>
          <tr><th scope="row">{{ t("Google Analytics") }}</th><td>{{ t("Local workflow; real property and measurement-quality review pending") }}</td><td>{{ t("A report does not verify event instrumentation or establish causation.") }}</td></tr>
          <tr><th scope="row">{{ t("PageSpeed Insights and CrUX") }}</th><td>{{ t("Local fixture coverage; real-provider acceptance pending") }}</td><td>{{ t("Keep lab observations and available field data separate; missing field data is unknown.") }}</td></tr>
          <tr><th scope="row">{{ t("Other external datasets") }}</th><td>{{ t("Planned or unavailable unless separately supported and verified") }}</td><td>{{ t("A crawl does not establish complete backlinks, search volumes, rankings or competitor traffic.") }}</td></tr>
        </tbody>
      </table>
      <section aria-labelledby="source-limits"><h2 id="source-limits">{{ t("Read the evidence before comparing numbers") }}</h2><p>{{ t("Check the project, source or property, collected date, reporting window and dimensions. Keep measurements, estimates and AI interpretation separate. Missing, disconnected, partial and stale states are not zero or a passing result. Local fixtures do not establish customer access, quotas, licensing, freshness or public readiness.") }}</p></section>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/help' : '/preview/help'">{{ t("Read help and methodology") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/sample-report' : '/sample-report'">{{ t("Inspect a synthetic action example") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/home' : '/'">{{ t("Return to the development home") }}</a></p>
    </article>
  `,
  styles: `
    .sources-draft { max-width: 52rem; margin-inline: auto; color: #182b36; overflow-wrap: anywhere; }
    nav { display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 1.5rem; }
    table { width: 100%; table-layout: fixed; border-collapse: collapse; }
    caption { text-align: left; font-weight: 700; padding-block: 1rem; }
    th, td { text-align: left; vertical-align: top; border-bottom: 1px solid #b9cfd5; padding: clamp(0.3rem, 1vw, 0.75rem); }
    section { margin-top: 2rem; }
  `,
})
export class DataSources implements OnDestroy {
  readonly language = inject(ActivatedRoute).snapshot.data['language'] === 'tr' ? 'tr' : 'en';
  private readonly document = inject(DOCUMENT);
  private readonly meta = inject(Meta);
  t(text: string) { return this.language === 'tr' ? sourcesTurkish[text] ?? text : text; }

  constructor() {
    this.document.documentElement.lang = this.language;
    this.meta.updateTag({ name: 'description', content: this.language === 'tr'
      ? 'OrganicSEOOps veri kaynakları: incelenmemiş Türkçe taslak; yerel geliştirme kanıtları, kapsam ve bekleyen sağlayıcı doğrulaması.'
      : 'OrganicSEOOps data sources: unreviewed local draft; development evidence, coverage and pending provider verification.' });
  }

  ngOnDestroy() {
    this.document.documentElement.lang = 'en';
    this.meta.updateTag({ name: 'description', content:
      'Development preview of an SEO evidence workflow for agency teams. Public trials and payments are not open.' });
  }
}
