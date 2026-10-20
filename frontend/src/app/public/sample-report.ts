import { DOCUMENT } from '@angular/common';
import { Component, inject, OnDestroy } from '@angular/core';
import { Meta } from '@angular/platform-browser';
import { ActivatedRoute, RouterLink } from '@angular/router';

const sampleTurkish: Record<string, string> = {
  "Synthetic development example · No customer website or measured result": "Sentetik geliştirme örneği · Müşteri sitesi veya ölçülmüş sonuç yok",
  "From source evidence to a reviewable SEO action": "Kaynak kanıtından incelenebilir bir SEO aksiyonuna",
  "This example illustrates a possible agency review. Every number and URL below is invented for this local demonstration. It is not a connected Search Console property, an audit of a real business, or an outcome claim.": "Bu örnek olası bir ajans incelemesini gösterir. Aşağıdaki tüm sayılar ve URL bu yerel gösterim için kurgulanmıştır. Bu, bağlı bir Search Console mülkü, gerçek bir işletmenin denetimi veya sonuç iddiası değildir.",
  "1. Source and coverage": "1. Kaynak ve kapsam",
  "Illustrative input:": "Örnek girdi:",
  "a hypothetical Search Console CSV query export for": "varsayımsal bir Search Console CSV sorgu dışa aktarımı; örnek alan adı:",
  ", one property and a 28-day window. An export may omit anonymized queries and cannot by itself join a query to a page.": "; tek mülk ve 28 günlük dönem. Dışa aktarım anonimleştirilmiş sorguları içermeyebilir ve tek başına bir sorguyu bir sayfayla eşleştiremez.",
  "Synthetic query row; not observed search performance": "Sentetik sorgu satırı; gözlemlenmiş arama performansı değildir",
  "Query": "Sorgu",
  "Impressions": "Gösterimler",
  "Clicks": "Tıklamalar",
  "CTR": "TO",
  "2. Finding and priority to review": "2. İncelenecek bulgu ve öncelik",
  "A comparatively low click-through rate for this": "Bu",
  "synthetic": "sentetik",
  "query could prompt a review. The export does not prove which page appeared, why people did not click, or that changing a title would help. Priority remains a human decision after confirming page intent, coverage and business relevance.": "sorgunun görece düşük tıklama oranı bir incelemeye yol açabilir. Dışa aktarım hangi sayfanın göründüğünü, insanların neden tıklamadığını veya başlık değiştirmenin yararlı olacağını kanıtlamaz. Sayfa niyeti, kapsam ve işle ilgisi doğrulandıktan sonra öncelik bir insan kararı olarak kalır.",
  "3. Proposed action": "3. Önerilen aksiyon",
  "Ask the authorized team to check the actual landing page, its search appearance and title against the query's intent. Record any approved change, affected URL and implementation date. Nothing in this example edits or publishes a customer page.": "Yetkili ekipten gerçek açılış sayfasını, arama görünümünü ve başlığını sorgunun niyetiyle karşılaştırmasını isteyin. Onaylanan değişikliği, etkilenen URL ve uygulama tarihini kaydedin. Bu örnek müşteri sayfasını düzenlemez veya yayımlamaz.",
  "4. Verification and outcome limit": "4. Doğrulama ve sonuç sınırı",
  "Technical verification:": "Teknik doğrulama:",
  "recheck the intended page, indexability and title after the change.": "değişiklikten sonra hedeflenen sayfayı, dizine eklenebilirliğini ve başlığını tekrar kontrol edin.",
  "Search outcome: unknown.": "Arama sonucu: bilinmiyor.",
  "A comparable, complete follow-up source window and measurement-quality review would still be needed. Before/after numbers alone would not prove causation.": "Karşılaştırılabilir, eksiksiz bir takip kaynak dönemi ve ölçüm kalitesi incelemesi yine gerekli olacaktır. Öncesi/sonrası sayıları tek başına nedenselliği kanıtlamaz.",
  "Return to the development home": "İngilizce geliştirme ana sayfasına dön",
  "Unreviewed local English/Turkish draft. Bilingual human approval and public release are pending. Original synthetic query and values below remain English.": "İncelenmemiş yerel İngilizce/Türkçe taslak. İki dilli insan onayı ve herkese açık yayımlama bekleniyor. Aşağıdaki özgün sentetik sorgu ve değerler İngilizce kalır."
};

@Component({
  selector: 'app-sample-report',
  imports: [RouterLink],
  template: `
    <article class="sample" [attr.lang]="language">
      <nav aria-label="Language / Dil">
        <a routerLink="/sample-report" lang="en" [attr.aria-current]="language === 'en' ? 'page' : null">English</a>
        · <a routerLink="/preview/tr/sample-report" lang="tr" [attr.aria-current]="language === 'tr' ? 'page' : null">Türkçe (taslak)</a>
      </nav>
      <p role="status">{{ t("Unreviewed local English/Turkish draft. Bilingual human approval and public release are pending. Original synthetic query and values below remain English.") }}</p>
      <p class="badge">{{ t("Synthetic development example · No customer website or measured result") }}</p>
      <h1>{{ t("From source evidence to a reviewable SEO action") }}</h1>
      <p>{{ t("This example illustrates a possible agency review. Every number and URL below is invented for this local demonstration. It is not a connected Search Console property, an audit of a real business, or an outcome claim.") }}</p>

      <section aria-labelledby="evidence-title">
        <h2 id="evidence-title">{{ t("1. Source and coverage") }}</h2>
        <p><strong>{{ t("Illustrative input:") }}</strong> {{ t("a hypothetical Search Console CSV query export for") }} <code lang="en">sample.example.invalid</code>{{ t(", one property and a 28-day window. An export may omit anonymized queries and cannot by itself join a query to a page.") }}</p>
        <table>
          <caption>{{ t("Synthetic query row; not observed search performance") }}</caption>
          <thead><tr><th scope="col">{{ t("Query") }}</th><th scope="col">{{ t("Impressions") }}</th><th scope="col">{{ t("Clicks") }}</th><th scope="col">{{ t("CTR") }}</th></tr></thead>
          <tbody><tr><th scope="row" lang="en">airport transfer example</th><td lang="en">1,200</td><td lang="en">24</td><td lang="en">2%</td></tr></tbody>
        </table>
      </section>

      <section aria-labelledby="finding-title">
        <h2 id="finding-title">{{ t("2. Finding and priority to review") }}</h2>
        <p>{{ t("A comparatively low click-through rate for this") }} <em>{{ t("synthetic") }}</em> {{ t("query could prompt a review. The export does not prove which page appeared, why people did not click, or that changing a title would help. Priority remains a human decision after confirming page intent, coverage and business relevance.") }}</p>
      </section>

      <section aria-labelledby="action-title">
        <h2 id="action-title">{{ t("3. Proposed action") }}</h2>
        <p>{{ t("Ask the authorized team to check the actual landing page, its search appearance and title against the query's intent. Record any approved change, affected URL and implementation date. Nothing in this example edits or publishes a customer page.") }}</p>
      </section>

      <section aria-labelledby="outcome-title">
        <h2 id="outcome-title">{{ t("4. Verification and outcome limit") }}</h2>
        <p><strong>{{ t("Technical verification:") }}</strong> {{ t("recheck the intended page, indexability and title after the change.") }} <strong>{{ t("Search outcome: unknown.") }}</strong> {{ t("A comparable, complete follow-up source window and measurement-quality review would still be needed. Before/after numbers alone would not prove causation.") }}</p>
      </section>

      <p><a routerLink="/">{{ t("Return to the development home") }}</a></p>
    </article>
  `,
  styles: `
    .sample { max-width: 52rem; margin-inline: auto; padding: clamp(1rem, 4vw, 3rem); color: #182b36; }
    .badge { font-weight: 700; color: #075d70; }
    section { border-top: 1px solid #b9cfd5; padding-block: 1rem; }
    table { width: 100%; border-collapse: collapse; margin-block: 1rem; }
    th, td { text-align: left; border-bottom: 1px solid #b9cfd5; padding: 0.6rem; }
    code { overflow-wrap: anywhere; }
  `,
})
export class SampleReport implements OnDestroy {
  readonly language = inject(ActivatedRoute).snapshot.data['language'] === 'tr' ? 'tr' : 'en';
  private readonly document = inject(DOCUMENT);
  private readonly meta = inject(Meta);
  t(text: string) { return this.language === 'tr' ? sampleTurkish[text] ?? text : text; }

  constructor() {
    this.document.documentElement.lang = this.language;
    this.meta.updateTag({ name: 'description', content: this.language === 'tr'
      ? 'OrganicSEOOps sentetik SEO aksiyonu örneği: incelenmemiş Türkçe taslak; müşteri verisi veya ölçülmüş sonuç içermez.'
      : 'OrganicSEOOps synthetic SEO action example: unreviewed draft, without customer data or measured results.' });
  }

  ngOnDestroy() {
    this.document.documentElement.lang = 'en';
    this.meta.updateTag({ name: 'description', content:
      'Development preview of an SEO evidence workflow for agency teams. Public trials and payments are not open.' });
  }
}
