import { DOCUMENT } from '@angular/common';
import { Component, inject, OnDestroy } from '@angular/core';
import { Meta } from '@angular/platform-browser';
import { ActivatedRoute, RouterLink } from '@angular/router';

const auditsTurkish: Record<string, string> = {
  "Read the opportunity review workflow": "Fırsat inceleme iş akışını okuyun",
  "Technical SEO audits with inspectable evidence": "İncelenebilir kanıtlarla teknik SEO denetimleri",
  "Unreviewed local English/Turkish audit draft. Bilingual human approval and public release are pending. This page contains no customer audit or measured result.": "İncelenmemiş yerel İngilizce/Türkçe denetim taslağı. İki dilli insan onayı ve herkese açık yayımlama bekleniyor. Bu sayfa müşteri denetimi veya ölçülmüş sonuç içermez.",
  "Bounded crawl, explicit coverage": "Sınırlı tarama, açık kapsam",
  "Review only the configured project domains and explicitly selected competitor scope. Record requested and final URLs, observation dates, failures and skipped pages against the actual run limits. A bounded crawl is not a complete site or whole-web dataset; recording an external link does not authorize crawling its destination.": "Yalnızca yapılandırılmış proje alan adlarını ve açıkça seçilmiş rakip kapsamını inceleyin. İstenen ve nihai URL’leri, gözlem tarihlerini, hataları ve atlanan sayfaları gerçek çalıştırma sınırlarıyla birlikte kaydedin. Sınırlı tarama eksiksiz site veya tüm web veri kümesi değildir; dış bağlantıyı kaydetmek hedefini tarama yetkisi vermez.",
  "Raw HTML and selective rendering": "Ham HTML ve seçici render",
  "Keep the original HTTP observation separate from any selected browser-rendered snapshot. Compare content, links, metadata and directives only within the observed sample and budget. Retain rendering failures as unavailable evidence. A browser snapshot does not prove how a search engine rendered the page.": "Özgün HTTP gözlemini seçilmiş tarayıcı render görüntüsünden ayrı tutun. İçeriği, bağlantıları, meta verileri ve yönergeleri yalnızca gözlemlenen örnek ve bütçe içinde karşılaştırın. Render hatalarını kullanılamayan kanıt olarak koruyun. Tarayıcı görüntüsü arama motorunun sayfayı nasıl render ettiğini kanıtlamaz.",
  "Canonicals, links, parameters and schema": "Canonical, bağlantılar, parametreler ve şema",
  "Inspect canonical targets, redirect chains and internal-link structure against recorded source coverage. Unchecked or out-of-scope targets remain unknown. Preserve meaningful URL parameter variants under configured limits. Structured-data syntax or ruleset checks are separate from rich-result eligibility and actual search appearance; none guarantees the next.": "Canonical hedeflerini, yönlendirme zincirlerini ve iç bağlantı yapısını kaydedilmiş kaynak kapsamıyla birlikte inceleyin. Kontrol edilmemiş veya kapsam dışı hedefler bilinmiyor olarak kalır. Anlamlı URL parametre varyantlarını yapılandırılmış sınırlar içinde koruyun. Yapılandırılmış veri sözdizimi veya kural kümesi kontrolleri, zengin sonuç uygunluğundan ve gerçek arama görünümünden ayrıdır; hiçbiri bir sonrakini garanti etmez.",
  "Discovery, crawlability, indexability and indexed status": "Keşif, taranabilirlik, dizine eklenebilirlik ve dizin durumu",
  "Keep discovered URLs, observed crawlability, local indexability signals and engine-reported indexed status separate, with their own source and dates. A successful fetch, sitemap entry or bot visit is not proof of indexing. Missing webmaster or performance data is unknown. Findings require evidence review; remediation needs human approval and later technical verification, with search outcomes measured separately.": "Keşfedilen URL’leri, gözlemlenen taranabilirliği, yerel dizine eklenebilirlik sinyallerini ve arama motorunun bildirdiği dizin durumunu kendi kaynakları ve tarihleriyle ayrı tutun. Başarılı istek, site haritası kaydı veya bot ziyareti dizine eklenme kanıtı değildir. Eksik webmaster veya performans verisi bilinmiyor durumundadır. Bulgular kanıt incelemesi gerektirir; düzeltmeler insan onayı ve sonraki teknik doğrulama gerektirir, arama sonuçları ise ayrıca ölçülür.",
  "Inspect a synthetic action example": "Sentetik aksiyon örneğini inceleyin",
  "Inspect source scope and readiness": "Kaynak kapsamını ve hazırlığını inceleyin",
  "Return to the development home": "Geliştirme ana sayfasına dön"
};

@Component({
  selector: 'app-technical-audits',
  imports: [RouterLink],
  template: `
    <article class="audits-draft" [attr.lang]="language">
      <nav aria-label="Language / Dil">
        <a routerLink="/preview/technical-seo-audits" lang="en" [attr.aria-current]="language === 'en' ? 'page' : null">English</a>
        · <a routerLink="/preview/tr/technical-seo-audits" lang="tr" [attr.aria-current]="language === 'tr' ? 'page' : null">Türkçe (taslak)</a>
      </nav>
      <p role="status">{{ t("Unreviewed local English/Turkish audit draft. Bilingual human approval and public release are pending. This page contains no customer audit or measured result.") }}</p>
      <h1>{{ t("Technical SEO audits with inspectable evidence") }}</h1>
      <section aria-labelledby="audits-0"><h2 id="audits-0">{{ t("Bounded crawl, explicit coverage") }}</h2><p>{{ t("Review only the configured project domains and explicitly selected competitor scope. Record requested and final URLs, observation dates, failures and skipped pages against the actual run limits. A bounded crawl is not a complete site or whole-web dataset; recording an external link does not authorize crawling its destination.") }}</p></section>
      <section aria-labelledby="audits-1"><h2 id="audits-1">{{ t("Raw HTML and selective rendering") }}</h2><p>{{ t("Keep the original HTTP observation separate from any selected browser-rendered snapshot. Compare content, links, metadata and directives only within the observed sample and budget. Retain rendering failures as unavailable evidence. A browser snapshot does not prove how a search engine rendered the page.") }}</p></section>
      <section aria-labelledby="audits-2"><h2 id="audits-2">{{ t("Canonicals, links, parameters and schema") }}</h2><p>{{ t("Inspect canonical targets, redirect chains and internal-link structure against recorded source coverage. Unchecked or out-of-scope targets remain unknown. Preserve meaningful URL parameter variants under configured limits. Structured-data syntax or ruleset checks are separate from rich-result eligibility and actual search appearance; none guarantees the next.") }}</p></section>
      <section aria-labelledby="audits-3"><h2 id="audits-3">{{ t("Discovery, crawlability, indexability and indexed status") }}</h2><p>{{ t("Keep discovered URLs, observed crawlability, local indexability signals and engine-reported indexed status separate, with their own source and dates. A successful fetch, sitemap entry or bot visit is not proof of indexing. Missing webmaster or performance data is unknown. Findings require evidence review; remediation needs human approval and later technical verification, with search outcomes measured separately.") }}</p></section>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/seo-opportunities' : '/preview/seo-opportunities'">{{ t("Read the opportunity review workflow") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/sample-report' : '/sample-report'">{{ t("Inspect a synthetic action example") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/data-sources' : '/preview/data-sources'">{{ t("Inspect source scope and readiness") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/home' : '/'">{{ t("Return to the development home") }}</a></p>
    </article>
  `,
  styles: `
    .audits-draft { max-width: 52rem; margin-inline: auto; color: #182b36; overflow-wrap: anywhere; }
    nav { display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 1.5rem; }
    section { border-top: 1px solid #b9cfd5; padding-block: 1rem; }
  `,
})
export class TechnicalAudits implements OnDestroy {
  readonly language = inject(ActivatedRoute).snapshot.data['language'] === 'tr' ? 'tr' : 'en';
  private readonly document = inject(DOCUMENT);
  private readonly meta = inject(Meta);
  t(text: string) { return this.language === 'tr' ? auditsTurkish[text] ?? text : text; }

  constructor() {
    this.document.documentElement.lang = this.language;
    this.meta.updateTag({ name: 'description', content: this.language === 'tr'
      ? 'OrganicSEOOps teknik SEO denetimleri: incelenmemiş Türkçe taslak; sınırlı tarama ve kaynak kapsamı, müşteri sonucu içermez.'
      : 'OrganicSEOOps technical SEO audits: unreviewed local draft covering bounded crawl and evidence limits, without customer results.' });
  }

  ngOnDestroy() {
    this.document.documentElement.lang = 'en';
    this.meta.updateTag({ name: 'description', content:
      'Development preview of an SEO evidence workflow for agency teams. Public trials and payments are not open.' });
  }
}
