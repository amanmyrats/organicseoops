import { DOCUMENT } from '@angular/common';
import { Component, inject, OnDestroy } from '@angular/core';
import { Meta } from '@angular/platform-browser';
import { ActivatedRoute, RouterLink } from '@angular/router';

const accessibilityTurkish: Record<string, string> = {
  "Accessibility target and current evidence": "Erişilebilirlik hedefi ve güncel kanıtlar",
  "Unreviewed local English/Turkish accessibility draft. Bilingual human approval and public release are pending. This is not a compliance or certification claim. Public trials and payments are not open.": "İncelenmemiş yerel İngilizce/Türkçe erişilebilirlik taslağı. İki dilli insan onayı ve herkese açık yayımlama bekleniyor. Bu, uygunluk veya sertifikasyon iddiası değildir. Herkese açık deneme ve ödeme sunulmaz.",
  "Our planned accessibility target": "Planlanan erişilebilirlik hedefimiz",
  "The product targets WCAG 2.2 AA across public, account, project and organization journeys. The intended experience includes semantic headings and landmarks, labeled native controls, keyboard operation and visible focus, readable contrast, status and error text, responsive reflow and text alternatives to visual information. A target, component library or successful build does not establish conformance.": "Ürün; herkese açık, hesap, proje ve kuruluş akışlarında WCAG 2.2 AA seviyesini hedefler. Amaçlanan deneyim anlamsal başlık ve bölgeleri, etiketli yerel kontrolleri, klavye kullanımını ve görünür odağı, okunabilir karşıtlığı, durum ve hata metinlerini, duyarlı yeniden akışı ve görsel bilgilere metin alternatiflerini kapsar. Hedef, bileşen kütüphanesi veya başarılı derleme uygunluğu kanıtlamaz.",
  "Reading this local preview": "Bu yerel ön izlemeyi okuma",
  "Public draft pages use native links, semantic headings and text content in generated HTML. Use the Skip to content link in the page shell and the explicit English/Turkish draft switch. Keyboard focus has a visible outline; page links wrap rather than requiring hover-only navigation. The layout uses flexible widths and wrapping text. These implementation choices do not prove keyboard, zoom, screen-reader or browser compatibility for every journey. No automatic language redirect or accessibility overlay is offered.": "Herkese açık taslak sayfalar, oluşturulan HTML içinde yerel bağlantılar, anlamsal başlıklar ve metin içerikleri kullanır. Sayfa kabuğundaki İçeriğe geç bağlantısını ve açık İngilizce/Türkçe taslak geçişini kullanın. Klavye odağının görünür çerçevesi vardır; sayfa bağlantıları yalnızca üzerine gelmeye bağlı gezinme yerine satırlara yayılır. Düzen esnek genişlikler ve satırlara sığan metin kullanır. Bu uygulama tercihleri her akışta klavye, yakınlaştırma, ekran okuyucu veya tarayıcı uyumluluğunu kanıtlamaz. Otomatik dil yönlendirmesi veya erişilebilirlik katmanı sunulmaz.",
  "Automated evidence and unverified journeys": "Otomatik kanıtlar ve doğrulanmamış akışlar",
  "Selected local automated checks cover route content, explicit locale switching, metadata cleanup, generated HTML, draft publication guards and static-host routing fixtures. These are scoped checks, not a whole-product accessibility audit or live-host acceptance. Core account → project → import → audit → finding/action → research/brief → export keyboard and assistive-technology walkthroughs remain unverified, including 320 CSS-pixel and 400% reflow checks. No tested browser/screen-reader matrix, accessibility certification or public acceptance is established by this page.": "Seçili yerel otomatik kontroller yol içeriğini, açık dil geçişini, meta veri temizliğini, oluşturulan HTML’yi, taslak yayımlama korumalarını ve statik barındırma yönlendirme testlerini kapsar. Bunlar kapsamlı ürün erişilebilirlik denetimi veya canlı barındırma kabulü değil, sınırlı kontrollerdir. Temel hesap → proje → içe aktarım → denetim → bulgu/aksiyon → araştırma/özet → dışa aktarım klavye ve yardımcı teknoloji incelemeleri, 320 CSS piksel ve %400 yeniden akış kontrolleri dahil, doğrulanmamıştır. Bu sayfa test edilmiş tarayıcı/ekran okuyucu matrisi, erişilebilirlik sertifikasyonu veya herkese açık kabul oluşturmaz.",
  "Describe a barrier without sensitive data": "Hassas veri olmadan engeli açıklama",
  "For an authorized local support request, describe the page or task, the action attempted, the observed barrier and the result expected. If relevant, state the browser, assistive technology and zoom setting you used; those details are observations, not proof that the product has tested that setup. Include only safe project/job references you may access. Never include passwords, keys, tokens, personal customer details, raw logs or private exports. The contact draft explains the existing private project-support flow; no public inbox or response-time commitment is available.": "Yetkili yerel destek isteğinde sayfayı veya görevi, denenen aksiyonu, gözlemlenen engeli ve beklenen sonucu açıklayın. İlgiliyse kullandığınız tarayıcıyı, yardımcı teknolojiyi ve yakınlaştırma ayarını belirtin; bu ayrıntılar gözlemdir, ürünün o kurulumu test ettiğini kanıtlamaz. Yalnızca erişim izniniz olan güvenli proje/iş referanslarını ekleyin. Parola, anahtar, belirteç, müşterilerin kişisel bilgileri, ham günlük veya özel dışa aktarım eklemeyin. İletişim taslağı mevcut özel proje destek akışını açıklar; herkese açık gelen kutusu veya yanıt süresi taahhüdü yoktur.",
  "Read contact and support limits": "İletişim ve destek sınırlarını okuyun",
  "Read help and methodology": "Yardım ve metodolojiyi okuyun",
  "Return to the development home": "Geliştirme ana sayfasına dönün"
};

@Component({
  selector: 'app-accessibility',
  imports: [RouterLink],
  template: `
    <article class="accessibility-draft" [attr.lang]="language">
      <nav aria-label="Language / Dil">
        <a routerLink="/preview/accessibility" lang="en" [attr.aria-current]="language === 'en' ? 'page' : null">English</a>
        · <a routerLink="/preview/tr/accessibility" lang="tr" [attr.aria-current]="language === 'tr' ? 'page' : null">Türkçe (taslak)</a>
      </nav>
      <h1>{{ t("Accessibility target and current evidence") }}</h1>
      <p role="status">{{ t("Unreviewed local English/Turkish accessibility draft. Bilingual human approval and public release are pending. This is not a compliance or certification claim. Public trials and payments are not open.") }}</p>
      <section aria-labelledby="accessibility-0"><h2 id="accessibility-0">{{ t("Our planned accessibility target") }}</h2><p>{{ t("The product targets WCAG 2.2 AA across public, account, project and organization journeys. The intended experience includes semantic headings and landmarks, labeled native controls, keyboard operation and visible focus, readable contrast, status and error text, responsive reflow and text alternatives to visual information. A target, component library or successful build does not establish conformance.") }}</p></section>
      <section aria-labelledby="accessibility-1"><h2 id="accessibility-1">{{ t("Reading this local preview") }}</h2><p>{{ t("Public draft pages use native links, semantic headings and text content in generated HTML. Use the Skip to content link in the page shell and the explicit English/Turkish draft switch. Keyboard focus has a visible outline; page links wrap rather than requiring hover-only navigation. The layout uses flexible widths and wrapping text. These implementation choices do not prove keyboard, zoom, screen-reader or browser compatibility for every journey. No automatic language redirect or accessibility overlay is offered.") }}</p></section>
      <section aria-labelledby="accessibility-2"><h2 id="accessibility-2">{{ t("Automated evidence and unverified journeys") }}</h2><p>{{ t("Selected local automated checks cover route content, explicit locale switching, metadata cleanup, generated HTML, draft publication guards and static-host routing fixtures. These are scoped checks, not a whole-product accessibility audit or live-host acceptance. Core account → project → import → audit → finding/action → research/brief → export keyboard and assistive-technology walkthroughs remain unverified, including 320 CSS-pixel and 400% reflow checks. No tested browser/screen-reader matrix, accessibility certification or public acceptance is established by this page.") }}</p></section>
      <section aria-labelledby="accessibility-3"><h2 id="accessibility-3">{{ t("Describe a barrier without sensitive data") }}</h2><p>{{ t("For an authorized local support request, describe the page or task, the action attempted, the observed barrier and the result expected. If relevant, state the browser, assistive technology and zoom setting you used; those details are observations, not proof that the product has tested that setup. Include only safe project/job references you may access. Never include passwords, keys, tokens, personal customer details, raw logs or private exports. The contact draft explains the existing private project-support flow; no public inbox or response-time commitment is available.") }}</p></section>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/contact' : '/preview/contact'">{{ t("Read contact and support limits") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/help' : '/preview/help'">{{ t("Read help and methodology") }}</a></p>
      <p><a [routerLink]="language === 'tr' ? '/preview/tr/home' : '/'">{{ t("Return to the development home") }}</a></p>
    </article>
  `,
  styles: `
    .accessibility-draft { max-width: 52rem; margin-inline: auto; color: #182b36; overflow-wrap: anywhere; }
    nav { display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 1.5rem; }
    section { border-top: 1px solid #b9cfd5; padding-block: 1rem; }
  `,
})
export class Accessibility implements OnDestroy {
  readonly language = inject(ActivatedRoute).snapshot.data['language'] === 'tr' ? 'tr' : 'en';
  private readonly document = inject(DOCUMENT);
  private readonly meta = inject(Meta);
  t(text: string) { return this.language === 'tr' ? accessibilityTurkish[text] ?? text : text; }

  constructor() {
    this.document.documentElement.lang = this.language;
    this.meta.updateTag({ name: 'description', content: this.language === 'tr'
      ? 'OrganicSEOOps erişilebilirlik hedefi ve kanıtlar: incelenmemiş Türkçe taslak; manuel kabul ve uygunluk doğrulanmamıştır.'
      : 'OrganicSEOOps accessibility target and evidence: unreviewed local draft; manual acceptance and conformance are unverified.' });
  }

  ngOnDestroy() {
    this.document.documentElement.lang = 'en';
    this.meta.updateTag({ name: 'description', content:
      'Development preview of an SEO evidence workflow for agency teams. Public trials and payments are not open.' });
  }
}
