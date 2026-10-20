import { DOCUMENT } from '@angular/common';
import { Component, inject, OnDestroy } from '@angular/core';
import { Meta } from '@angular/platform-browser';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AnalyticsConsent } from '../analytics-consent';

const homeTurkish: Record<string, string> = {
  "Read product terms and responsibilities": "Ürün koşullarını ve sorumlulukları okuyun",
  "Read privacy and data choices": "Gizlilik ve veri seçimlerini okuyun",
  "Read cancellation and retained access": "İptal ve korunan erişimi okuyun",
  "Read data handling and current limits": "Veri işlemeyi ve güncel sınırları okuyun",
  "Read accessibility target and evidence": "Erişilebilirlik hedefini ve kanıtları okuyun",
  "Read contact and support limits": "İletişim ve destek sınırlarını okuyun",
  "Read planned pricing and limits": "Planlanan fiyatlandırmayı ve sınırları okuyun",
  "Read the content and keyword workflow": "İçerik ve anahtar kelime iş akışını okuyun",
  "Read the opportunity review workflow": "Fırsat inceleme iş akışını okuyun",
  "Read the airport-transfer use case": "Havalimanı transfer kullanım senaryosunu okuyun",
  "Read the agency team workflow": "Ajans ekibi iş akışını okuyun",
  "Read technical audit evidence limits": "Teknik denetim kanıtlarının sınırlarını okuyun",
  "Inspect source scope and readiness": "Kaynak kapsamını ve hazırlığını inceleyin",
  "Read help and methodology": "Yardım ve metodolojiyi okuyun",
  "OrganicSEOOps · Development preview": "OrganicSEOOps · Geliştirme ön izlemesi",
  "Turn client-site evidence into clearer SEO decisions.": "Müşteri sitelerinin kanıtlarını daha net SEO kararlarına dönüştürün.",
  "A workspace in development for agency teams that audit client sites, review source evidence and plan what to improve next.": "Müşteri sitelerini denetleyen, kaynak kanıtlarını inceleyen ve sonraki iyileştirmeleri planlayan ajans ekipleri için geliştirilmekte olan bir çalışma alanı.",
  "Technical checks, project separation and selected source connections are tested locally. Prioritized findings, outcomes and a customer-ready paid offer are still being built.": "Teknik kontroller, proje ayrımı ve seçili kaynak bağlantıları yerel olarak test edilir. Önceliklendirilmiş bulgular, sonuçlar ve müşteriye hazır ücretli teklif hâlâ geliştiriliyor.",
  "Development preview navigation": "Geliştirme ön izlemesi gezinmesi",
  "Explore account registration": "Hesap kaydını inceleyin",
  "What is available in this preview?": "Bu ön izlemede neler var?",
  "Inspect a synthetic action example": "Sentetik aksiyon örneğini inceleyin",
  "How the proposed workflow treats evidence": "Önerilen iş akışının kanıtları ele alma biçimi",
  "Proposed workflow": "Önerilen iş akışı",
  "Observe": "Gözlemleyin",
  "Decide": "Karar verin",
  "Verify": "Doğrulayın",
  "Keep the source, date and coverage of each check visible.": "Her kontrolün kaynağını, tarihini ve kapsamını görünür tutun.",
  "Review the evidence before assigning a priority.": "Öncelik atamadan önce kanıtları inceleyin.",
  "Record the change before assessing its outcome.": "Sonucunu değerlendirmeden önce değişikliği kaydedin.",
  "This is a workflow illustration, not customer results or a live report.": "Bu bir iş akışı gösterimidir; müşteri sonuçları veya canlı rapor değildir.",
  "Built around separate client projects": "Ayrı müşteri projeleri etrafında kurulur",
  "Agencies can organize sites and team access by project. The current development build uses bounded work and keeps missing data distinct from measured results.": "Ajanslar siteleri ve ekip erişimini projeye göre düzenleyebilir. Mevcut geliştirme sürümü sınırlı işlemler kullanır ve eksik verileri ölçülmüş sonuçlardan ayrı tutar.",
  "Have an existing preview account?": "Mevcut bir ön izleme hesabınız var mı?",
  "Sign in": "Oturum açın",
  ". No public trial or payment is open.": ". Herkese açık deneme veya ödeme sunulmaz.",
  "Unreviewed local English/Turkish home draft. Bilingual human approval and wider product coverage are pending. Public trials and payments are not open.": "İncelenmemiş yerel İngilizce/Türkçe ana sayfa taslağı. İki dilli insan onayı ve ürünün daha geniş dil kapsamı bekleniyor. Herkese açık deneme ve ödeme sunulmaz."
};

@Component({
  selector: 'app-home',
  imports: [RouterLink],
  template: `
    <div class="home-draft" [attr.lang]="language">
      <nav aria-label="Language / Dil">
        <a routerLink="/" lang="en" [attr.aria-current]="language === 'en' ? 'page' : null">English</a>
        · <a routerLink="/preview/tr/home" lang="tr" [attr.aria-current]="language === 'tr' ? 'page' : null">Türkçe (taslak)</a>
      </nav>
      <p role="status">{{ t("Unreviewed local English/Turkish home draft. Bilingual human approval and wider product coverage are pending. Public trials and payments are not open.") }}</p>
      <section class="hero" aria-labelledby="home-title">
        <div>
          <p class="kicker">{{ t("OrganicSEOOps · Development preview") }}</p>
          <h1 id="home-title">{{ t("Turn client-site evidence into clearer SEO decisions.") }}</h1>
          <p class="intro">{{ t("A workspace in development for agency teams that audit client sites, review source evidence and plan what to improve next.") }}</p>
          <p>{{ t("Technical checks, project separation and selected source connections are tested locally. Prioritized findings, outcomes and a customer-ready paid offer are still being built.") }}</p>
          <nav [attr.aria-label]="t('Development preview navigation')">
            <a class="button-link" routerLink="/account/register" (click)="analytics.observe('public_cta_selected', 'public_trial_cta')">{{ t("Explore account registration") }}</a>
            <a [routerLink]="language === 'tr' ? '/preview/tr/terms' : '/preview/terms'">{{ t("Read product terms and responsibilities") }}</a>
            <a [routerLink]="language === 'tr' ? '/preview/tr/privacy' : '/preview/privacy'">{{ t("Read privacy and data choices") }}</a>
            <a [routerLink]="language === 'tr' ? '/preview/tr/cancellation' : '/preview/cancellation'">{{ t("Read cancellation and retained access") }}</a>
            <a [routerLink]="language === 'tr' ? '/preview/tr/data-handling' : '/preview/data-handling'">{{ t("Read data handling and current limits") }}</a>
            <a [routerLink]="language === 'tr' ? '/preview/tr/accessibility' : '/preview/accessibility'">{{ t("Read accessibility target and evidence") }}</a>
            <a [routerLink]="language === 'tr' ? '/preview/tr/contact' : '/preview/contact'">{{ t("Read contact and support limits") }}</a>
            <a [routerLink]="language === 'tr' ? '/preview/tr/pricing' : '/preview/pricing'">{{ t("Read planned pricing and limits") }}</a>
            <a [routerLink]="language === 'tr' ? '/preview/tr/content-and-keywords' : '/preview/content-and-keywords'">{{ t("Read the content and keyword workflow") }}</a>
            <a [routerLink]="language === 'tr' ? '/preview/tr/seo-opportunities' : '/preview/seo-opportunities'">{{ t("Read the opportunity review workflow") }}</a>
            <a [routerLink]="language === 'tr' ? '/preview/tr/airport-transfer-seo' : '/preview/airport-transfer-seo'">{{ t("Read the airport-transfer use case") }}</a>
            <a [routerLink]="language === 'tr' ? '/preview/tr' : '/preview'">{{ t("What is available in this preview?") }}</a>
            <a [routerLink]="language === 'tr' ? '/preview/tr/technical-seo-audits' : '/preview/technical-seo-audits'">{{ t("Read technical audit evidence limits") }}</a>
            <a [routerLink]="language === 'tr' ? '/preview/tr/data-sources' : '/preview/data-sources'">{{ t("Inspect source scope and readiness") }}</a>
            <a [routerLink]="language === 'tr' ? '/preview/tr/seo-agencies' : '/preview/seo-agencies'">{{ t("Read the agency team workflow") }}</a>
            <a [routerLink]="language === 'tr' ? '/preview/tr/help' : '/preview/help'">{{ t("Read help and methodology") }}</a>
            <a [routerLink]="language === 'tr' ? '/preview/tr/sample-report' : '/sample-report'">{{ t("Inspect a synthetic action example") }}</a>
          </nav>
        </div>
        <aside [attr.aria-label]="t('How the proposed workflow treats evidence')">
          <p class="kicker">{{ t("Proposed workflow") }}</p>
          <ol>
            <li><strong>{{ t("Observe") }}</strong><span>{{ t("Keep the source, date and coverage of each check visible.") }}</span></li>
            <li><strong>{{ t("Decide") }}</strong><span>{{ t("Review the evidence before assigning a priority.") }}</span></li>
            <li><strong>{{ t("Verify") }}</strong><span>{{ t("Record the change before assessing its outcome.") }}</span></li>
          </ol>
          <p>{{ t("This is a workflow illustration, not customer results or a live report.") }}</p>
        </aside>
      </section>
      <section class="context" aria-labelledby="context-title">
        <h2 id="context-title">{{ t("Built around separate client projects") }}</h2>
        <p>{{ t("Agencies can organize sites and team access by project. The current development build uses bounded work and keeps missing data distinct from measured results.") }}</p>
        <p>{{ t("Have an existing preview account?") }} <a routerLink="/account/login">{{ t("Sign in") }}</a>{{ t(". No public trial or payment is open.") }}</p>
      </section>
    </div>
  `,
  styles: `
    .home-draft { color: #182b36; }
    .hero { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(17rem, 0.8fr); gap: clamp(2rem, 6vw, 5rem); align-items: center; }
    .kicker { color: #075d70; font-size: 0.8rem; font-weight: 800; letter-spacing: 0.1em; text-transform: uppercase; }
    h1 { max-width: 16ch; margin: 1rem 0 1.5rem; font-size: clamp(2.5rem, 6vw, 4.5rem); }
    .intro { font-size: clamp(1.15rem, 2vw, 1.4rem); font-weight: 600; }
    nav { display: flex; flex-wrap: wrap; align-items: center; gap: 1rem 1.5rem; margin-block: 2rem; }
    aside { padding: clamp(1.2rem, 3vw, 2rem); border: 1px solid #b9cfd5; border-radius: 1rem; background: #eaf4f2; }
    aside ol { display: grid; gap: 1.1rem; margin: 1.2rem 0; padding-left: 1.5rem; }
    aside li { padding-left: 0.3rem; }
    aside li strong, aside li span { display: block; }
    aside li span { color: #405962; }
    aside > p:last-child { margin-bottom: 0; font-size: 0.9rem; }
    .context { margin-top: clamp(3rem, 8vw, 6rem); padding-top: 1.5rem; border-top: 1px solid #c8d5db; }
    .context h2 { max-width: 24ch; line-height: 1.25; font-size: clamp(1.6rem, 3vw, 2.3rem); }
    @media (max-width: 48rem) { .hero { grid-template-columns: 1fr; } }
  `,
})
export class Home implements OnDestroy {
  readonly analytics = inject(AnalyticsConsent);
  readonly language = inject(ActivatedRoute).snapshot.data['language'] === 'tr' ? 'tr' : 'en';
  private readonly document = inject(DOCUMENT);
  private readonly meta = inject(Meta);
  t(text: string) { return this.language === 'tr' ? homeTurkish[text] ?? text : text; }

  constructor() {
    this.document.documentElement.lang = this.language;
    this.meta.updateTag({ name: 'description', content: this.language === 'tr'
      ? 'OrganicSEOOps ajans SEO iş akışı geliştirme ön izlemesi: incelenmemiş Türkçe taslak. Herkese açık deneme ve ödeme sunulmaz.'
      : 'Development preview of an SEO evidence workflow for agency teams. Public trials and payments are not open.' });
  }

  ngOnDestroy() {
    this.document.documentElement.lang = 'en';
    this.meta.updateTag({ name: 'description', content:
      'Development preview of an SEO evidence workflow for agency teams. Public trials and payments are not open.' });
  }
}
