import { DOCUMENT } from '@angular/common';
import { Component, inject, OnDestroy } from '@angular/core';
import { Meta } from '@angular/platform-browser';
import { ActivatedRoute, RouterLink } from '@angular/router';

const agencyTurkish: Record<string, string> = {
  "Read the opportunity review workflow": "Fırsat inceleme iş akışını okuyun",
  "Read the airport-transfer use case": "Havalimanı transfer kullanım senaryosunu okuyun",
  "SEO workflows for multi-client agency teams": "Çok müşterili ajans ekipleri için SEO iş akışları",
  "Unreviewed local English/Turkish agency draft. Bilingual human approval and public release are pending. No customer results are shown. Public trials and payments are not open.": "İncelenmemiş yerel İngilizce/Türkçe ajans taslağı. İki dilli insan onayı ve herkese açık yayımlama bekleniyor. Müşteri sonuçları gösterilmez. Herkese açık deneme ve ödeme sunulmaz.",
  "Separate client projects, shared organization": "Ayrı müşteri projeleri, ortak kuruluş",
  "Organize each client domain as a separate project, with its own sources, jobs, findings and artifacts. The organization owns memberships, billing, trial and entitlements; adding a project does not start another trial. An agency workspace does not grant access to another organization. Owner-operators and in-house teams use the same model.": "Her müşteri alan adını kendi kaynakları, işleri, bulguları ve çıktılarıyla ayrı bir proje olarak düzenleyin. Üyelikler, faturalandırma, deneme ve kullanım hakları kuruluşa aittir; proje eklemek yeni bir deneme başlatmaz. Ajans çalışma alanı başka bir kuruluşa erişim vermez. İşletme sahipleri ve kurum içi ekipler aynı modeli kullanır.",
  "Team roles and restricted project access": "Ekip rolleri ve kısıtlı proje erişimi",
  "Owner, admin, member and viewer roles have different permissions. Project memberships can restrict team access; the organization owner can access all its projects. Members can prepare research and drafts within their access and budget. Viewers cannot launch jobs or edit drafts. Content and remediation approval belongs to an authorized owner or admin, within project access. Billing and ownership changes remain owner responsibilities.": "Owner, admin, member ve viewer rolleri farklı izinlere sahiptir. Proje üyelikleri ekip erişimini kısıtlayabilir; kuruluş sahibi tüm projelerine erişebilir. Üyeler erişimleri ve bütçeleri kapsamında araştırma ve taslak hazırlayabilir. Görüntüleyiciler iş başlatamaz veya taslak düzenleyemez. İçerik ve düzeltme onayı, proje erişimi kapsamında yetkili sahip veya yöneticiye aittir. Faturalandırma ve sahiplik değişiklikleri kuruluş sahibinin sorumluluğunda kalır.",
  "Review evidence before assigning work": "İş atamadan önce kanıtları inceleyin",
  "Keep sources, observation dates and coverage limits alongside each finding. Review the evidence, assign a responsible teammate and record approved changes. Human approval is required for content and remediation; a draft or recommendation does not change a client site. Verify the implemented change before assessing its search outcome. Missing data and unknown outcomes remain explicit.": "Her bulguyla birlikte kaynakları, gözlem tarihlerini ve kapsam sınırlarını koruyun. Kanıtları inceleyin, sorumlu ekip üyesini atayın ve onaylanan değişiklikleri kaydedin. İçerik ve düzeltmeler insan onayı gerektirir; taslak veya öneri müşteri sitesini değiştirmez. Arama sonucunu değerlendirmeden önce uygulanan değişikliği doğrulayın. Eksik veriler ve bilinmeyen sonuçlar açıkça belirtilir.",
  "Preview scope and readiness": "Ön izleme kapsamı ve hazırlık",
  "This local draft explains the intended agency workflow, not a verified customer-ready service. White labeling, a client portal and automatic reports are not offered here. Source availability depends on configured grants, supported capabilities and release checks. The synthetic sample illustrates a review sequence, not measured client results or guaranteed rankings.": "Bu yerel taslak, doğrulanmış müşteriye hazır bir hizmet yerine amaçlanan ajans iş akışını açıklar. Burada beyaz etiketleme, müşteri portalı ve otomatik raporlar sunulmaz. Kaynak kullanılabilirliği yapılandırılmış izinlere, desteklenen yeteneklere ve yayımlama kontrollerine bağlıdır. Sentetik örnek, ölçülmüş müşteri sonuçları veya garantili sıralamalar yerine inceleme sırasını gösterir.",
  "Inspect a synthetic action example": "Sentetik aksiyon örneğini inceleyin",
  "Read technical audit evidence limits": "Teknik denetim kanıtlarının sınırlarını okuyun",
  "Inspect source scope and readiness": "Kaynak kapsamını ve hazırlığını inceleyin",
  "Return to the development home": "Geliştirme ana sayfasına dön"
};

@Component({
  selector: 'app-seo-agencies',
  imports: [RouterLink],
  template: `
    <article class="agency-draft" [attr.lang]="language">
      <nav aria-label="Language / Dil">
        <a routerLink="/preview/seo-agencies" lang="en" [attr.aria-current]="language === 'en' ? 'page' : null">English</a>
        · <a routerLink="/preview/tr/seo-agencies" lang="tr" [attr.aria-current]="language === 'tr' ? 'page' : null">Türkçe (taslak)</a>
      </nav>
      <p role="status">{{ t("Unreviewed local English/Turkish agency draft. Bilingual human approval and public release are pending. No customer results are shown. Public trials and payments are not open.") }}</p>
      <h1>{{ t("SEO workflows for multi-client agency teams") }}</h1>
      <section aria-labelledby="agency-0"><h2 id="agency-0">{{ t("Separate client projects, shared organization") }}</h2><p>{{ t("Organize each client domain as a separate project, with its own sources, jobs, findings and artifacts. The organization owns memberships, billing, trial and entitlements; adding a project does not start another trial. An agency workspace does not grant access to another organization. Owner-operators and in-house teams use the same model.") }}</p></section>
      <section aria-labelledby="agency-1"><h2 id="agency-1">{{ t("Team roles and restricted project access") }}</h2><p>{{ t("Owner, admin, member and viewer roles have different permissions. Project memberships can restrict team access; the organization owner can access all its projects. Members can prepare research and drafts within their access and budget. Viewers cannot launch jobs or edit drafts. Content and remediation approval belongs to an authorized owner or admin, within project access. Billing and ownership changes remain owner responsibilities.") }}</p></section>
      <section aria-labelledby="agency-2"><h2 id="agency-2">{{ t("Review evidence before assigning work") }}</h2><p>{{ t("Keep sources, observation dates and coverage limits alongside each finding. Review the evidence, assign a responsible teammate and record approved changes. Human approval is required for content and remediation; a draft or recommendation does not change a client site. Verify the implemented change before assessing its search outcome. Missing data and unknown outcomes remain explicit.") }}</p></section>
      <section aria-labelledby="agency-3"><h2 id="agency-3">{{ t("Preview scope and readiness") }}</h2><p>{{ t("This local draft explains the intended agency workflow, not a verified customer-ready service. White labeling, a client portal and automatic reports are not offered here. Source availability depends on configured grants, supported capabilities and release checks. The synthetic sample illustrates a review sequence, not measured client results or guaranteed rankings.") }}</p></section>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/seo-opportunities' : '/preview/seo-opportunities'">{{ t("Read the opportunity review workflow") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/airport-transfer-seo' : '/preview/airport-transfer-seo'">{{ t("Read the airport-transfer use case") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/sample-report' : '/sample-report'">{{ t("Inspect a synthetic action example") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/technical-seo-audits' : '/preview/technical-seo-audits'">{{ t("Read technical audit evidence limits") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/data-sources' : '/preview/data-sources'">{{ t("Inspect source scope and readiness") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/home' : '/'">{{ t("Return to the development home") }}</a></p>
    </article>
  `,
  styles: `
    .agency-draft { max-width: 52rem; margin-inline: auto; color: #182b36; overflow-wrap: anywhere; }
    nav { display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 1.5rem; }
    section { border-top: 1px solid #b9cfd5; padding-block: 1rem; }
  `,
})
export class SeoAgencies implements OnDestroy {
  readonly language = inject(ActivatedRoute).snapshot.data['language'] === 'tr' ? 'tr' : 'en';
  private readonly document = inject(DOCUMENT);
  private readonly meta = inject(Meta);
  t(text: string) { return this.language === 'tr' ? agencyTurkish[text] ?? text : text; }

  constructor() {
    this.document.documentElement.lang = this.language;
    this.meta.updateTag({ name: 'description', content: this.language === 'tr'
      ? 'OrganicSEOOps ajans ekipleri: incelenmemiş Türkçe taslak; proje ayrımı, ekip rolleri ve insan incelemesi.'
      : 'OrganicSEOOps agency teams: unreviewed local draft about separate projects, team roles and human review.' });
  }

  ngOnDestroy() {
    this.document.documentElement.lang = 'en';
    this.meta.updateTag({ name: 'description', content:
      'Development preview of an SEO evidence workflow for agency teams. Public trials and payments are not open.' });
  }
}
