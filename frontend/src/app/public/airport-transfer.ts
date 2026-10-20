import { DOCUMENT } from '@angular/common';
import { Component, inject, OnDestroy } from '@angular/core';
import { Meta } from '@angular/platform-browser';
import { ActivatedRoute, RouterLink } from '@angular/router';

const transferTurkish: Record<string, string> = {
  "Read the content and keyword workflow": "İçerik ve anahtar kelime iş akışını okuyun",
  "An evidence-led SEO workflow for airport-transfer teams": "Havalimanı transfer ekipleri için kanıta dayalı SEO iş akışı",
  "Unreviewed local English/Turkish transfer use-case draft. Bilingual human approval and public release are pending. No customer data or measured results are shown. Public trials and payments are not open.": "İncelenmemiş yerel İngilizce/Türkçe transfer kullanım senaryosu taslağı. İki dilli insan onayı ve herkese açık yayımlama bekleniyor. Müşteri verisi veya ölçülmüş sonuç gösterilmez. Herkese açık deneme ve ödeme sunulmaz.",
  "Start with measured demand, not assumed languages": "Varsayılan diller yerine ölçülmüş taleple başlayın",
  "The intended use case is an agency team serving airport-transfer businesses in Antalya and Istanbul. Traveler origin countries do not establish search demand or select product languages. Review permitted query and landing-page evidence by language, market, date and source coverage before choosing what to improve. Missing query volume, rankings or conversion data remains unknown.": "Amaçlanan kullanım senaryosu Antalya ve İstanbul’daki havalimanı transfer işletmelerine hizmet veren ajans ekibidir. Yolcuların geldiği ülkeler arama talebini kanıtlamaz veya ürün dillerini belirlemez. İyileştirilecek konuyu seçmeden önce izinli sorgu ve açılış sayfası kanıtlarını dil, pazar, tarih ve kaynak kapsamıyla inceleyin. Eksik sorgu hacmi, sıralama veya dönüşüm verisi bilinmiyor olarak kalır.",
  "Ground local context in real service details": "Yerel bağlamı gerçek hizmet ayrıntılarına dayandırın",
  "Record actual service areas, routes, hours and business details supplied by the authorized team. Keep legitimate service-area and address-display differences visible. A domain, airport or city does not establish eligibility for a business profile. Profile access and edits need supported permission and human approval; neither a profile nor a bot visit proves rankings or bookings.": "Yetkili ekibin sağladığı gerçek hizmet bölgelerini, güzergâhları, çalışma saatlerini ve işletme ayrıntılarını kaydedin. Meşru hizmet bölgesi ve adres gösterim farklılıklarını görünür tutun. Alan adı, havalimanı veya şehir işletme profili uygunluğunu kanıtlamaz. Profil erişimi ve düzenlemeleri desteklenen izin ve insan onayı gerektirir; profil veya bot ziyareti sıralama ya da rezervasyon kanıtı değildir.",
  "Improve useful pages and technical structure": "Yararlı sayfaları ve teknik yapıyı iyileştirin",
  "Review bounded crawl evidence for landing-page structure, internal links, canonicals and language annotations. Map observed queries and intent to existing pages before proposing new content. Airport, city and service pages need distinct useful information grounded in real service details; do not mass-produce near-identical location pages or fabricate locations and reviews. Crawl and source gaps limit the conclusions.": "Açılış sayfası yapısı, iç bağlantılar, canonical ve dil işaretlemeleri için sınırlı tarama kanıtlarını inceleyin. Yeni içerik önermeden önce gözlemlenen sorguları ve niyetleri mevcut sayfalara eşleyin. Havalimanı, şehir ve hizmet sayfaları gerçek hizmet ayrıntılarına dayanan farklı ve yararlı bilgi gerektirir; birbirine çok benzeyen konum sayfalarını toplu üretmeyin veya konum ve yorum uydurmayın. Tarama ve kaynak eksikleri sonuçları sınırlar.",
  "Assign, approve, verify and measure separately": "Atama, onay, doğrulama ve ölçümü ayrı tutun",
  "Keep each client project separate. Review a small evidence-backed action list, assign a teammate and obtain human approval for content or remediation. Record the actual change and verify it technically before comparing outcomes. Seasonal demand, concurrent changes and measurement quality can affect search or booking comparisons; an observed difference does not prove causation. This proposed workflow is not a customer result or a live-provider readiness claim.": "Her müşteri projesini ayrı tutun. Kanıta dayalı küçük bir aksiyon listesini inceleyin, ekip üyesi atayın ve içerik veya düzeltme için insan onayı alın. Sonuçları karşılaştırmadan önce gerçek değişikliği kaydedin ve teknik olarak doğrulayın. Mevsimsel talep, eşzamanlı değişiklikler ve ölçüm kalitesi arama veya rezervasyon karşılaştırmalarını etkileyebilir; gözlemlenen fark nedenselliği kanıtlamaz. Önerilen bu iş akışı müşteri sonucu veya canlı sağlayıcı hazırlığı iddiası değildir.",
  "Inspect a synthetic action example": "Sentetik aksiyon örneğini inceleyin",
  "Read technical audit evidence limits": "Teknik denetim kanıtlarının sınırlarını okuyun",
  "Inspect source scope and readiness": "Kaynak kapsamını ve hazırlığını inceleyin",
  "Read the agency team workflow": "Ajans ekibi iş akışını okuyun",
  "Return to the development home": "Geliştirme ana sayfasına dön"
};

@Component({
  selector: 'app-airport-transfer',
  imports: [RouterLink],
  template: `
    <article class="transfer-draft" [attr.lang]="language">
      <nav aria-label="Language / Dil">
        <a routerLink="/preview/airport-transfer-seo" lang="en" [attr.aria-current]="language === 'en' ? 'page' : null">English</a>
        · <a routerLink="/preview/tr/airport-transfer-seo" lang="tr" [attr.aria-current]="language === 'tr' ? 'page' : null">Türkçe (taslak)</a>
      </nav>
      <p role="status">{{ t("Unreviewed local English/Turkish transfer use-case draft. Bilingual human approval and public release are pending. No customer data or measured results are shown. Public trials and payments are not open.") }}</p>
      <h1>{{ t("An evidence-led SEO workflow for airport-transfer teams") }}</h1>
      <section aria-labelledby="transfer-0"><h2 id="transfer-0">{{ t("Start with measured demand, not assumed languages") }}</h2><p>{{ t("The intended use case is an agency team serving airport-transfer businesses in Antalya and Istanbul. Traveler origin countries do not establish search demand or select product languages. Review permitted query and landing-page evidence by language, market, date and source coverage before choosing what to improve. Missing query volume, rankings or conversion data remains unknown.") }}</p></section>
      <section aria-labelledby="transfer-1"><h2 id="transfer-1">{{ t("Ground local context in real service details") }}</h2><p>{{ t("Record actual service areas, routes, hours and business details supplied by the authorized team. Keep legitimate service-area and address-display differences visible. A domain, airport or city does not establish eligibility for a business profile. Profile access and edits need supported permission and human approval; neither a profile nor a bot visit proves rankings or bookings.") }}</p></section>
      <section aria-labelledby="transfer-2"><h2 id="transfer-2">{{ t("Improve useful pages and technical structure") }}</h2><p>{{ t("Review bounded crawl evidence for landing-page structure, internal links, canonicals and language annotations. Map observed queries and intent to existing pages before proposing new content. Airport, city and service pages need distinct useful information grounded in real service details; do not mass-produce near-identical location pages or fabricate locations and reviews. Crawl and source gaps limit the conclusions.") }}</p></section>
      <section aria-labelledby="transfer-3"><h2 id="transfer-3">{{ t("Assign, approve, verify and measure separately") }}</h2><p>{{ t("Keep each client project separate. Review a small evidence-backed action list, assign a teammate and obtain human approval for content or remediation. Record the actual change and verify it technically before comparing outcomes. Seasonal demand, concurrent changes and measurement quality can affect search or booking comparisons; an observed difference does not prove causation. This proposed workflow is not a customer result or a live-provider readiness claim.") }}</p></section>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/content-and-keywords' : '/preview/content-and-keywords'">{{ t("Read the content and keyword workflow") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/sample-report' : '/sample-report'">{{ t("Inspect a synthetic action example") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/technical-seo-audits' : '/preview/technical-seo-audits'">{{ t("Read technical audit evidence limits") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/data-sources' : '/preview/data-sources'">{{ t("Inspect source scope and readiness") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/seo-agencies' : '/preview/seo-agencies'">{{ t("Read the agency team workflow") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/home' : '/'">{{ t("Return to the development home") }}</a></p>
    </article>
  `,
  styles: `
    .transfer-draft { max-width: 52rem; margin-inline: auto; color: #182b36; overflow-wrap: anywhere; }
    nav { display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 1.5rem; }
    section { border-top: 1px solid #b9cfd5; padding-block: 1rem; }
  `,
})
export class AirportTransfer implements OnDestroy {
  readonly language = inject(ActivatedRoute).snapshot.data['language'] === 'tr' ? 'tr' : 'en';
  private readonly document = inject(DOCUMENT);
  private readonly meta = inject(Meta);
  t(text: string) { return this.language === 'tr' ? transferTurkish[text] ?? text : text; }

  constructor() {
    this.document.documentElement.lang = this.language;
    this.meta.updateTag({ name: 'description', content: this.language === 'tr'
      ? 'OrganicSEOOps havalimanı transfer SEO iş akışı: incelenmemiş Türkçe taslak; gerçek hizmet ayrıntıları ve kanıt sınırları.'
      : 'OrganicSEOOps airport-transfer SEO workflow: unreviewed local draft about real service details and evidence limits.' });
  }

  ngOnDestroy() {
    this.document.documentElement.lang = 'en';
    this.meta.updateTag({ name: 'description', content:
      'Development preview of an SEO evidence workflow for agency teams. Public trials and payments are not open.' });
  }
}
