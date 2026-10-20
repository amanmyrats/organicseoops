import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, effect, OnInit, signal, computed } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi } from './account-api';
import { CheckoutLinkReceipt } from './checkout-link-receipt';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';

type PaddleClient = {
  Environment: { set(environment: 'sandbox'): void };
  Initialize(options: { token: string }): void;
  Checkout: { open(options: { transactionId: string }): void };
};

type Checkout = { organization_id: number; attempt_id: number; transaction_id: string; checkout_url: string;
  environment: 'sandbox' | 'live'; client_token: string; payment_confirmed: false };

const checkoutPageTurkish: Record<string, string> = {
  "Hosted checkout": "Barındırılan ödeme işlemi",
  "Review Paddle checkout": "Paddle ödeme işlemini incele",
  "Back to organization context": "Kuruluş bağlamına dön",
  "Agency is USD 149 per month before Paddle-calculated tax and localization. Confirm the actual currency, tax, total and monthly renewal at Paddle before paying. Paying during your trial ends the trial immediately; unused time and units do not carry over. Cancellation takes effect at period end.": "Agency, Paddle tarafından hesaplanan vergi ve yerelleştirme öncesinde ayda 149 USD’dir. Ödemeden önce gerçek para birimini, vergiyi, toplamı ve aylık yenilemeyi Paddle’da doğrulayın. Deneme sırasında ödeme yapmak denemeyi hemen sona erdirir; kullanılmayan süre ve birimler devredilmez. İptal dönem sonunda geçerli olur.",
  "A checkout URL or Paddle success screen never activates service here. Paid status is confirmed only after the server reconciles provider billing events. Return to your organization to check status.": "Ödeme URL’si veya Paddle başarı ekranı burada hizmeti etkinleştirmez. Ücretli durum yalnızca sunucu sağlayıcının faturalandırma olaylarını mutabakatla doğruladıktan sonra onaylanır. Durumu kontrol etmek için kuruluşunuza dönün.",
  "Verifying this checkout for the current owner.": "Bu ödeme işlemi mevcut sahip için doğrulanıyor.",
  "Organization": "Kuruluş",
  "attempt": "girişim",
  "No payment has been confirmed.": "Hiçbir ödeme doğrulanmadı.",
  "Open Paddle payment review": "Paddle ödeme incelemesini aç",
  "This payment link is invalid. Return to your organization billing page.": "Bu ödeme bağlantısı geçersiz. Kuruluşunuzun faturalandırma sayfasına dönün.",
  "This checkout is unavailable for your current account. Return to billing and refresh status.": "Bu ödeme işlemi mevcut hesabınız için kullanılamıyor. Faturalandırmaya dönün ve durumu yenileyin.",
  "Review the price and tax inside Paddle. Return here to check verified billing status afterward.": "Fiyatı ve vergiyi Paddle içinde inceleyin. Ardından doğrulanmış faturalandırma durumunu kontrol etmek için buraya dönün.",
  "Paddle checkout could not be opened. No payment was confirmed here. Refresh billing status.": "Paddle ödeme işlemi açılamadı. Burada hiçbir ödeme doğrulanmadı. Faturalandırma durumunu yenileyin.",
  "Unreviewed Turkish checkout-review interface draft in local development. Provider values and other screens remain English; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe ödeme inceleme arayüzü taslağı. Sağlayıcı değerleri ve diğer ekranlar İngilizce kalır; iki dilde onay bekleniyor."
};

@Component({
  selector: 'app-checkout-page',
  imports: [RouterLink, CheckoutLinkReceipt],
  template: `
    <section [attr.lang]="uiLanguage()" class="account-card" aria-labelledby="checkout-title">
      <h1 id="checkout-title">{{ t("Review Paddle checkout") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish checkout-review interface draft in local development. Provider values and other screens remain English; bilingual approval is pending.") }}</p> }
      <p><a routerLink="/app">{{ t("Back to organization context") }}</a></p>
      <p>{{ t("Agency is USD 149 per month before Paddle-calculated tax and localization. Confirm the actual currency, tax, total and monthly renewal at Paddle before paying. Paying during your trial ends the trial immediately; unused time and units do not carry over. Cancellation takes effect at period end.") }}</p>
      <p>{{ t("A checkout URL or Paddle success screen never activates service here. Paid status is confirmed only after the server reconciles provider billing events. Return to your organization to check status.") }}</p>
      @if (loading()) { <p role="status">{{ t("Verifying this checkout for the current owner.") }}</p> }
      @if (error()) { <p role="alert" [attr.lang]="uiLanguage()">{{ t(error()) }}</p> }
      @if (message()) { <p role="status" [attr.lang]="uiLanguage()">{{ t(message()) }}</p> }
      @if (!loading() && checkout(); as current) {
        <p>{{ t("Organization") }} {{ current.organization_id }} · {{ t("attempt") }} {{ current.attempt_id }} · <span lang="en">{{ current.environment }}</span>.
          {{ t("No payment has been confirmed.") }}</p>
        <button type="button" (click)="openPaddle()" [disabled]="busy()">{{ t("Open Paddle payment review") }}</button>
        <app-checkout-link-receipt [language]="uiLanguage()" [organizationId]="current.organization_id" [attemptId]="current.attempt_id" [checkoutUrl]="current.checkout_url" />
      }
    </section>
  `,
})
export class CheckoutPage implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  t(text: string) { return this.uiLanguage() === 'tr' ? checkoutPageTurkish[text] ?? text : text; }
  readonly loading = signal(true);
  readonly busy = signal(false);
  readonly checkout = signal<Checkout | null>(null);
  readonly error = signal('');
  readonly message = signal('');
  private requestId = 0;
  // ponytail: one Paddle.js initialization per page; reload before switching sellers in one browser tab.
  private static initializedToken = '';

  constructor(private readonly api: AccountApi, private readonly route: ActivatedRoute,
              private readonly destroyRef: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t('Hosted checkout')} — OrganicSEOOps`));
  }

  ngOnInit() {
    void this.loadProductLanguage();
    this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(params => {
      const transactionId = params.get('_ptxn');
      const request = ++this.requestId;
      this.checkout.set(null); this.message.set(''); this.error.set(''); this.loading.set(true);
      if (params.keys.length !== 1 || params.getAll('_ptxn').length !== 1
        || !transactionId || !/^txn_[a-z0-9]{26}$/.test(transactionId)) {
        this.error.set("This payment link is invalid. Return to your organization billing page.");
        this.loading.set(false); return;
      }
      void this.load(transactionId, request);
    });
  }

  private async loadProductLanguage() {
    try {
      const result = await this.api.productLanguage();
      if (!this.destroyRef.destroyed && result.status === 200 && isProductLanguageResult(result.body)) {
        this.productLanguage.set(result.body['language']);
      }
    } catch { /* Keep English when the private preference is unavailable. */ }
  }

  private async load(transactionId: string, request: number) {
    try {
      const result = await this.api.resolveCheckoutTransaction(transactionId);
      if (request !== this.requestId) return;
      const row = result.body;
      const environment = row['environment'];
      const token = row['client_token'];
      if (result.status !== 200 || row['transaction_id'] !== transactionId
        || !Number.isSafeInteger(row['organization_id']) || Number(row['organization_id']) < 1
        || !Number.isSafeInteger(row['attempt_id']) || Number(row['attempt_id']) < 1
        || row['payment_confirmed'] !== false || (environment !== 'sandbox' && environment !== 'live')
        || typeof token !== 'string'
        || !new RegExp(`^${environment === 'sandbox' ? 'test' : 'live'}_[A-Za-z0-9]{27}$`).test(token)
        || row['checkout_url'] !== `${window.location.origin}/account/billing/checkout?_ptxn=${transactionId}`) throw new Error();
      this.checkout.set(row as unknown as Checkout);
    } catch {
      if (request === this.requestId) this.error.set("This checkout is unavailable for your current account. Return to billing and refresh status.");
    } finally { if (request === this.requestId) this.loading.set(false); }
  }

  async openPaddle() {
    const current = this.checkout();
    if (!current || this.loading() || this.busy()) return;
    this.busy.set(true); this.error.set('');
    try {
      const paddle = await this.loadScript();
      if (this.destroyRef.destroyed || current !== this.checkout()) return;
      if (CheckoutPage.initializedToken && CheckoutPage.initializedToken !== current.client_token) throw new Error();
      if (!CheckoutPage.initializedToken) {
        if (current.environment === 'sandbox') paddle.Environment.set('sandbox');
        paddle.Initialize({ token: current.client_token });
        CheckoutPage.initializedToken = current.client_token;
      }
      paddle.Checkout.open({ transactionId: current.transaction_id });
      this.message.set("Review the price and tax inside Paddle. Return here to check verified billing status afterward.");
    } catch { this.error.set("Paddle checkout could not be opened. No payment was confirmed here. Refresh billing status."); }
    finally { this.busy.set(false); }
  }

  private loadScript(): Promise<PaddleClient> {
    const target = window as Window & { Paddle?: PaddleClient };
    if (target.Paddle) return Promise.resolve(target.Paddle);
    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = 'https://cdn.paddle.com/paddle/v2/paddle.js';
      script.async = true;
      script.referrerPolicy = 'no-referrer';
      script.onload = () => target.Paddle ? resolve(target.Paddle) : reject(new Error());
      script.onerror = () => { script.remove(); reject(new Error()); };
      document.head.append(script);
    });
  }
}
