import { DOCUMENT } from '@angular/common';
import { Component, inject, OnDestroy } from '@angular/core';
import { Meta } from '@angular/platform-browser';
import { ActivatedRoute, RouterLink } from '@angular/router';

const contentTurkish: Record<string, string> = {
  "Plan content and keywords around page intent": "İçeriği ve anahtar kelimeleri sayfa niyetine göre planlayın",
  "Unreviewed local English/Turkish content workflow draft. Bilingual human approval and public release are pending. No customer results are shown. Public trials and payments are not open.": "İncelenmemiş yerel İngilizce/Türkçe içerik iş akışı taslağı. İki dilli insan onayı ve herkese açık yayımlama bekleniyor. Müşteri sonuçları gösterilmez. Herkese açık deneme ve ödeme sunulmaz.",
  "Map intent before deciding to create a page": "Sayfa oluşturmaya karar vermeden önce niyeti eşleyin",
  "Review observed queries, existing pages and permitted source evidence within the project, market and language. Choose a preferred existing or proposed page and keep human corrections visible. Separate query and page exports do not establish a query-page relationship. A human mapping without joint evidence must say so; keyword overlap alone does not prove cannibalization. Missing volume, difficulty or rankings remains unknown.": "Gözlemlenen sorguları, mevcut sayfaları ve izinli kaynak kanıtlarını proje, pazar ve dil kapsamında inceleyin. Tercih edilen mevcut veya önerilen sayfayı seçin ve insan düzeltmelerini görünür tutun. Ayrı sorgu ve sayfa dışa aktarımları sorgu-sayfa ilişkisini kurmaz. Ortak kanıt olmadan yapılan insan eşlemesi bunu belirtmelidir; anahtar kelime örtüşmesi tek başına yamyamlaşmayı kanıtlamaz. Eksik hacim, zorluk veya sıralama bilinmiyor olarak kalır.",
  "Choose keep, refresh or create using evidence": "Kanıtlarla koruma, yenileme veya oluşturma kararı verin",
  "Assess intent fit, useful coverage, actual business details and available performance evidence before defaulting to a new article. Existing-page refresh may be the better action. Low traffic or word count alone is not a deletion or quality verdict. Merge, redirect and retire proposals need destination and user-impact review; archiving a content record does not remove or deindex a live page.": "Yeni makaleye yönelmeden önce niyet uyumunu, yararlı kapsamı, gerçek işletme ayrıntılarını ve mevcut performans kanıtlarını değerlendirin. Mevcut sayfayı yenilemek daha uygun aksiyon olabilir. Düşük trafik veya kelime sayısı tek başına silme ya da kalite kararı değildir. Birleştirme, yönlendirme ve kaldırma önerileri hedef ve kullanıcı etkisi incelemesi gerektirir; içerik kaydını arşivlemek canlı sayfayı kaldırmaz veya dizinden çıkarmaz.",
  "Collect sources, then prepare a reviewable brief": "Kaynakları toplayın, ardından incelenebilir içerik özeti hazırlayın",
  "Link the selected mapping and accepted human action to source-linked research before preparing a brief. Keep source URLs, retrieval dates, coverage limits, citations and claims needing verification visible. A person supplies the angle, headings, questions and intended audience; AI interpretations remain separate from source facts. Missing or partial sources must stay labeled. Citations alone do not establish original expertise, verified service details or content quality.": "İçerik özeti hazırlamadan önce seçilen eşlemeyi ve kabul edilmiş insan aksiyonunu kaynak bağlantılı araştırmaya bağlayın. Kaynak URL’lerini, alınma tarihlerini, kapsam sınırlarını, atıfları ve doğrulanması gereken iddiaları görünür tutun. Yaklaşımı, bölüm başlıklarını, soruları ve hedef kitleyi bir insan sağlar; yapay zekâ yorumları kaynak olgularından ayrı kalır. Eksik veya kısmi kaynaklar etiketli kalmalıdır. Atıflar tek başına özgün uzmanlığı, doğrulanmış hizmet ayrıntılarını veya içerik kalitesini kanıtlamaz.",
  "Preserve revisions and human approval": "Sürümleri ve insan onayını koruyun",
  "Generated text remains an unverified draft. Do not invent statistics, testimonials, credentials, prices, availability or customer stories; omit unsupported claims or mark them for verification. Keep source material, brief, draft, revisions and exact-text human review distinct. Content and remediation require authorized human approval. Approval and a reported publication are separate from an actual site change and later technical or search-outcome verification. This draft does not offer automatic publishing or a live-provider readiness guarantee.": "Üretilen metin doğrulanmamış taslak olarak kalır. İstatistik, müşteri yorumu, yetkinlik, fiyat, kullanılabilirlik veya müşteri hikâyesi uydurmayın; desteklenmeyen iddiaları çıkarın veya doğrulama için işaretleyin. Kaynak materyali, içerik özeti, taslak, sürümler ve tam metne yönelik insan incelemesini ayrı tutun. İçerik ve düzeltmeler yetkili insan onayı gerektirir. Onay ve bildirilen yayımlama, gerçek site değişikliğinden ve sonraki teknik veya arama sonucu doğrulamasından ayrıdır. Bu taslak otomatik yayımlama veya canlı sağlayıcı hazırlığı garantisi sunmaz.",
  "Inspect a synthetic action example": "Sentetik aksiyon örneğini inceleyin",
  "Read the opportunity review workflow": "Fırsat inceleme iş akışını okuyun",
  "Read the airport-transfer use case": "Havalimanı transfer kullanım senaryosunu okuyun",
  "Return to the development home": "Geliştirme ana sayfasına dön"
};

@Component({
  selector: 'app-content-keywords',
  imports: [RouterLink],
  template: `
    <article class="content-draft" [attr.lang]="language">
      <nav aria-label="Language / Dil">
        <a routerLink="/preview/content-and-keywords" lang="en" [attr.aria-current]="language === 'en' ? 'page' : null">English</a>
        · <a routerLink="/preview/tr/content-and-keywords" lang="tr" [attr.aria-current]="language === 'tr' ? 'page' : null">Türkçe (taslak)</a>
      </nav>
      <p role="status">{{ t("Unreviewed local English/Turkish content workflow draft. Bilingual human approval and public release are pending. No customer results are shown. Public trials and payments are not open.") }}</p>
      <h1>{{ t("Plan content and keywords around page intent") }}</h1>
      <section aria-labelledby="content-0"><h2 id="content-0">{{ t("Map intent before deciding to create a page") }}</h2><p>{{ t("Review observed queries, existing pages and permitted source evidence within the project, market and language. Choose a preferred existing or proposed page and keep human corrections visible. Separate query and page exports do not establish a query-page relationship. A human mapping without joint evidence must say so; keyword overlap alone does not prove cannibalization. Missing volume, difficulty or rankings remains unknown.") }}</p></section>
      <section aria-labelledby="content-1"><h2 id="content-1">{{ t("Choose keep, refresh or create using evidence") }}</h2><p>{{ t("Assess intent fit, useful coverage, actual business details and available performance evidence before defaulting to a new article. Existing-page refresh may be the better action. Low traffic or word count alone is not a deletion or quality verdict. Merge, redirect and retire proposals need destination and user-impact review; archiving a content record does not remove or deindex a live page.") }}</p></section>
      <section aria-labelledby="content-2"><h2 id="content-2">{{ t("Collect sources, then prepare a reviewable brief") }}</h2><p>{{ t("Link the selected mapping and accepted human action to source-linked research before preparing a brief. Keep source URLs, retrieval dates, coverage limits, citations and claims needing verification visible. A person supplies the angle, headings, questions and intended audience; AI interpretations remain separate from source facts. Missing or partial sources must stay labeled. Citations alone do not establish original expertise, verified service details or content quality.") }}</p></section>
      <section aria-labelledby="content-3"><h2 id="content-3">{{ t("Preserve revisions and human approval") }}</h2><p>{{ t("Generated text remains an unverified draft. Do not invent statistics, testimonials, credentials, prices, availability or customer stories; omit unsupported claims or mark them for verification. Keep source material, brief, draft, revisions and exact-text human review distinct. Content and remediation require authorized human approval. Approval and a reported publication are separate from an actual site change and later technical or search-outcome verification. This draft does not offer automatic publishing or a live-provider readiness guarantee.") }}</p></section>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/sample-report' : '/sample-report'">{{ t("Inspect a synthetic action example") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/seo-opportunities' : '/preview/seo-opportunities'">{{ t("Read the opportunity review workflow") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/airport-transfer-seo' : '/preview/airport-transfer-seo'">{{ t("Read the airport-transfer use case") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/home' : '/'">{{ t("Return to the development home") }}</a></p>
    </article>
  `,
  styles: `
    .content-draft { max-width: 52rem; margin-inline: auto; color: #182b36; overflow-wrap: anywhere; }
    nav { display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 1.5rem; }
    section { border-top: 1px solid #b9cfd5; padding-block: 1rem; }
  `,
})
export class ContentKeywords implements OnDestroy {
  readonly language = inject(ActivatedRoute).snapshot.data['language'] === 'tr' ? 'tr' : 'en';
  private readonly document = inject(DOCUMENT);
  private readonly meta = inject(Meta);
  t(text: string) { return this.language === 'tr' ? contentTurkish[text] ?? text : text; }

  constructor() {
    this.document.documentElement.lang = this.language;
    this.meta.updateTag({ name: 'description', content: this.language === 'tr'
      ? 'OrganicSEOOps içerik ve anahtar kelime iş akışı: incelenmemiş Türkçe taslak; niyet eşleme, kaynaklı özetler ve insan incelemesi.'
      : 'OrganicSEOOps content and keyword workflow: unreviewed local draft about intent mapping, sourced briefs and human review.' });
  }

  ngOnDestroy() {
    this.document.documentElement.lang = 'en';
    this.meta.updateTag({ name: 'description', content:
      'Development preview of an SEO evidence workflow for agency teams. Public trials and payments are not open.' });
  }
}
