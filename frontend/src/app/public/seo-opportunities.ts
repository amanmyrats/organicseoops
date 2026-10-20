import { DOCUMENT } from '@angular/common';
import { Component, inject, OnDestroy } from '@angular/core';
import { Meta } from '@angular/platform-browser';
import { ActivatedRoute, RouterLink } from '@angular/router';

const opportunitiesTurkish: Record<string, string> = {
  "Read the content and keyword workflow": "İçerik ve anahtar kelime iş akışını okuyun",
  "Review SEO opportunities before turning them into team work": "SEO fırsatlarını ekip işine dönüştürmeden önce inceleyin",
  "Unreviewed local English/Turkish opportunities draft. Bilingual human approval and public release are pending. No customer results are shown. Public trials and payments are not open.": "İncelenmemiş yerel İngilizce/Türkçe fırsatlar taslağı. İki dilli insan onayı ve herkese açık yayımlama bekleniyor. Müşteri sonuçları gösterilmez. Herkese açık deneme ve ödeme sunulmaz.",
  "Inspect the source behind each finding": "Her bulgunun kaynağını inceleyin",
  "Retain the project, source snapshot, observation date, affected URLs and coverage limits with each finding. Bounded crawl observations and permitted search reports support source-limited candidates, not a complete diagnosis. Separate query and page exports do not establish a joint query-page relationship or prove cannibalization. A genuine paired report can support an overlap candidate for review, not an automatic merge or deletion.": "Her bulguyla birlikte projeyi, kaynak görüntüsünü, gözlem tarihini, etkilenen URL’leri ve kapsam sınırlarını koruyun. Sınırlı tarama gözlemleri ve izinli arama raporları eksiksiz teşhis yerine kaynakla sınırlı adayları destekler. Ayrı sorgu ve sayfa dışa aktarımları ortak sorgu-sayfa ilişkisini kurmaz veya yamyamlaşmayı kanıtlamaz. Gerçek eşleşmiş rapor, otomatik birleştirme veya silme yerine incelenecek örtüşme adayını destekleyebilir.",
  "Make priority, confidence and effort reviewable": "Öncelik, güven ve eforu incelenebilir tutun",
  "Review severity, evidence confidence, estimated effort and business relevance before choosing a small next-action list. Deterministic checks retain their evidence; AI interpretation or draft recommendations remain separate and reviewable. Missing publication dates or exact-origin conversion evidence keep the corresponding source-dependent checks unavailable. Missing data is not zero, proof of low value or a guaranteed opportunity.": "Küçük bir sonraki aksiyon listesi seçmeden önce önem derecesini, kanıt güvenini, tahmini eforu ve işle ilgisini inceleyin. Deterministik kontroller kanıtlarını korur; yapay zekâ yorumu veya taslak öneriler ayrı ve incelenebilir kalır. Eksik yayımlanma tarihleri veya tam kaynak adresine bağlı dönüşüm kanıtı, ilgili kaynağa bağlı kontrolleri kullanılamaz durumda tutar. Eksik veri sıfır, düşük değer kanıtı veya garantili fırsat değildir.",
  "Assign work and record approved changes": "İş atayın ve onaylanan değişiklikleri kaydedin",
  "An authorized team chooses the action, responsible teammate, affected pages and acceptance criteria. Content and remediation require human approval by an authorized owner or admin within project access. Proposed, accepted, in-progress and implemented work are separate from technical verification and outcome review. Record the actual implementation date and change summary. A saved recommendation or approval does not edit a customer site.": "Yetkili ekip aksiyonu, sorumlu ekip üyesini, etkilenen sayfaları ve kabul ölçütlerini seçer. İçerik ve düzeltmeler proje erişimi kapsamında yetkili sahip veya yönetici tarafından insan onayı gerektirir. Önerilen, kabul edilen, devam eden ve uygulanan işler teknik doğrulama ve sonuç incelemesinden ayrıdır. Gerçek uygulama tarihini ve değişiklik özetini kaydedin. Kaydedilmiş öneri veya onay müşteri sitesini düzenlemez.",
  "Verify the change, then compare observed outcomes": "Değişikliği doğrulayın, ardından gözlemlenen sonuçları karşılaştırın",
  "Recheck the intended technical change against actual observations. Missing or failed pages are unknown, not fixed. Compare explicit baseline and follow-up windows only with compatible project, source and metric definitions. A missing row in a top-rows export is unknown, not zero. Keep reporting delay, incomplete periods, seasonality, tracking changes and concurrent work visible. Insufficient history is inconclusive; before-and-after changes do not prove causal uplift. Conversion and revenue remain unavailable without a supported exact-project source. This local draft is not a live-provider or customer-ready capability claim.": "Amaçlanan teknik değişikliği gerçek gözlemlerle tekrar kontrol edin. Eksik veya başarısız sayfalar düzeltilmiş değil, bilinmiyor durumundadır. Açık başlangıç ve takip dönemlerini yalnızca uyumlu proje, kaynak ve metrik tanımlarıyla karşılaştırın. En üst satırlar dışa aktarımında eksik satır sıfır değil, bilinmiyor durumundadır. Raporlama gecikmesini, eksik dönemleri, mevsimselliği, izleme değişikliklerini ve eşzamanlı işleri görünür tutun. Yetersiz geçmiş kesin sonuca izin vermez; öncesi ve sonrası değişiklikler nedensel artışı kanıtlamaz. Desteklenen tam proje kaynağı olmadan dönüşüm ve gelir kullanılamaz durumda kalır. Bu yerel taslak canlı sağlayıcı veya müşteriye hazır yetenek iddiası değildir.",
  "Inspect a synthetic action example": "Sentetik aksiyon örneğini inceleyin",
  "Read technical audit evidence limits": "Teknik denetim kanıtlarının sınırlarını okuyun",
  "Inspect source scope and readiness": "Kaynak kapsamını ve hazırlığını inceleyin",
  "Return to the development home": "Geliştirme ana sayfasına dön"
};

@Component({
  selector: 'app-seo-opportunities',
  imports: [RouterLink],
  template: `
    <article class="opportunities-draft" [attr.lang]="language">
      <nav aria-label="Language / Dil">
        <a routerLink="/preview/seo-opportunities" lang="en" [attr.aria-current]="language === 'en' ? 'page' : null">English</a>
        · <a routerLink="/preview/tr/seo-opportunities" lang="tr" [attr.aria-current]="language === 'tr' ? 'page' : null">Türkçe (taslak)</a>
      </nav>
      <p role="status">{{ t("Unreviewed local English/Turkish opportunities draft. Bilingual human approval and public release are pending. No customer results are shown. Public trials and payments are not open.") }}</p>
      <h1>{{ t("Review SEO opportunities before turning them into team work") }}</h1>
      <section aria-labelledby="opportunities-0"><h2 id="opportunities-0">{{ t("Inspect the source behind each finding") }}</h2><p>{{ t("Retain the project, source snapshot, observation date, affected URLs and coverage limits with each finding. Bounded crawl observations and permitted search reports support source-limited candidates, not a complete diagnosis. Separate query and page exports do not establish a joint query-page relationship or prove cannibalization. A genuine paired report can support an overlap candidate for review, not an automatic merge or deletion.") }}</p></section>
      <section aria-labelledby="opportunities-1"><h2 id="opportunities-1">{{ t("Make priority, confidence and effort reviewable") }}</h2><p>{{ t("Review severity, evidence confidence, estimated effort and business relevance before choosing a small next-action list. Deterministic checks retain their evidence; AI interpretation or draft recommendations remain separate and reviewable. Missing publication dates or exact-origin conversion evidence keep the corresponding source-dependent checks unavailable. Missing data is not zero, proof of low value or a guaranteed opportunity.") }}</p></section>
      <section aria-labelledby="opportunities-2"><h2 id="opportunities-2">{{ t("Assign work and record approved changes") }}</h2><p>{{ t("An authorized team chooses the action, responsible teammate, affected pages and acceptance criteria. Content and remediation require human approval by an authorized owner or admin within project access. Proposed, accepted, in-progress and implemented work are separate from technical verification and outcome review. Record the actual implementation date and change summary. A saved recommendation or approval does not edit a customer site.") }}</p></section>
      <section aria-labelledby="opportunities-3"><h2 id="opportunities-3">{{ t("Verify the change, then compare observed outcomes") }}</h2><p>{{ t("Recheck the intended technical change against actual observations. Missing or failed pages are unknown, not fixed. Compare explicit baseline and follow-up windows only with compatible project, source and metric definitions. A missing row in a top-rows export is unknown, not zero. Keep reporting delay, incomplete periods, seasonality, tracking changes and concurrent work visible. Insufficient history is inconclusive; before-and-after changes do not prove causal uplift. Conversion and revenue remain unavailable without a supported exact-project source. This local draft is not a live-provider or customer-ready capability claim.") }}</p></section>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/content-and-keywords' : '/preview/content-and-keywords'">{{ t("Read the content and keyword workflow") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/sample-report' : '/sample-report'">{{ t("Inspect a synthetic action example") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/technical-seo-audits' : '/preview/technical-seo-audits'">{{ t("Read technical audit evidence limits") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/data-sources' : '/preview/data-sources'">{{ t("Inspect source scope and readiness") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/home' : '/'">{{ t("Return to the development home") }}</a></p>
    </article>
  `,
  styles: `
    .opportunities-draft { max-width: 52rem; margin-inline: auto; color: #182b36; overflow-wrap: anywhere; }
    nav { display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 1.5rem; }
    section { border-top: 1px solid #b9cfd5; padding-block: 1rem; }
  `,
})
export class SeoOpportunities implements OnDestroy {
  readonly language = inject(ActivatedRoute).snapshot.data['language'] === 'tr' ? 'tr' : 'en';
  private readonly document = inject(DOCUMENT);
  private readonly meta = inject(Meta);
  t(text: string) { return this.language === 'tr' ? opportunitiesTurkish[text] ?? text : text; }

  constructor() {
    this.document.documentElement.lang = this.language;
    this.meta.updateTag({ name: 'description', content: this.language === 'tr'
      ? 'OrganicSEOOps SEO fırsatları: incelenmemiş Türkçe taslak; kaynak kanıtı, insan önceliklendirmesi ve sonuç sınırları.'
      : 'OrganicSEOOps SEO opportunities: unreviewed local draft about source evidence, human prioritization and outcome limits.' });
  }

  ngOnDestroy() {
    this.document.documentElement.lang = 'en';
    this.meta.updateTag({ name: 'description', content:
      'Development preview of an SEO evidence workflow for agency teams. Public trials and payments are not open.' });
  }
}
