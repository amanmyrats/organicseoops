import { Component, DestroyRef, input, OnChanges, signal, computed, SimpleChanges } from '@angular/core';
import { AccountApi } from './account-api';
import { draftProductLanguage } from '../product-language';

const METHOD = 'checkout-link-receipt-v1';
const positive = (value: unknown) => Number.isSafeInteger(value) && Number(value) > 0;
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const aware = (value: unknown): value is string => typeof value === 'string'
  && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const dated = (value: unknown): value is string => aware(value) && Date.parse(value) <= Date.now();
const digest = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const SOURCE_KEYS = ['method', 'organization_id', 'actor_id', 'attempt_id', 'request_actor_id', 'environment',
  'offer_version', 'product_id', 'price_id', 'transaction_id', 'created_at', 'sent_at', 'seller_id',
  'seller_rotated_at', 'checkout_url', 'payment_confirmed', 'interpretation'].sort();
type Challenge = { method: string; source: Record<string, unknown>; source_digest: string; proof: string; expires_at: string };
type Receipt = { method: string; attempt_id: number; source_digest: string; acknowledged_at: string;
  state: string; payment_confirmed: false; interpretation: string };
type Inspection = { receipt: Receipt | null; challenge: Challenge | null };
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

async function sourceDigest(source: Record<string, unknown>) {
  const json = JSON.stringify(Object.fromEntries(Object.keys(source).sort().map(key => [key, source[key]])))
    .replace(/[\u007f-\uffff]/g, char => `\\u${char.charCodeAt(0).toString(16).padStart(4, '0')}`);
  const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(json));
  return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, '0')).join('');
}

const checkoutReceiptTurkish: Record<string, string> = {
  "Checkout link receipt": "Ödeme bağlantısı alındısı",
  "Browser link receipt · organization": "Tarayıcı bağlantı alındısı · kuruluş",
  "attempt": "girişim",
  "This optional record means the current owner acknowledged obtaining this application's payment link. It does not prove Paddle loaded, payment, paid access or a first-ever conversion. Older attempts remain unknown.": "Bu isteğe bağlı kayıt, mevcut sahibin bu uygulamanın ödeme bağlantısını aldığını onayladığı anlamına gelir. Paddle’ın yüklendiğini, ödemeyi, ücretli erişimi veya ilk kez dönüşümü kanıtlamaz. Eski girişimler bilinmiyor olarak kalır.",
  "Inspect this exact saved link receipt": "Kaydedilen bu bağlantının alındısını incele",
  "Checking the current owner and exact saved attempt.": "Mevcut sahip ve kaydedilen ilgili girişim kontrol ediliyor.",
  "First browser acknowledgment:": "İlk tarayıcı onayı:",
  "source SHA256": "kaynak SHA256",
  "Retained billing history, not current payment status.": "Saklanan faturalandırma geçmişidir; mevcut ödeme durumu değildir.",
  "Original attempt": "Özgün girişim",
  "provider request": "sağlayıcı isteği",
  "Exact application link:": "İlgili uygulama bağlantısı:",
  "Receipt proof expires at": "Alındı kanıtının sona erme zamanı:",
  "Inspection records no acknowledgment.": "İnceleme, onay kaydetmez.",
  "I obtained this exact application payment link and want to record its browser receipt.": "Bu uygulamanın ilgili ödeme bağlantısını aldım ve tarayıcı alındısını kaydetmek istiyorum.",
  "Acknowledge obtaining this link": "Bu bağlantının alındığını onayla",
  "The acknowledgment outcome is unknown. No payment request or acknowledgment is replayed automatically.": "Onayın sonucu bilinmiyor. Ödeme isteği veya onay otomatik olarak tekrarlanmaz.",
  "Look up this exact acknowledgment": "Bu onayın kaydını sorgula",
  "Retry the same unexpired acknowledgment after lookup": "Sorgulamadan sonra süresi dolmamış aynı onayı yeniden dene",
  "Receipt proof expired. Inspect saved history; no acknowledgment is retried.": "Alındı kanıtının süresi doldu. Kaydedilen geçmişi inceleyin; onay yeniden denenmez.",
  "First browser link acknowledgment recorded. No payment is confirmed.": "İlk tarayıcı bağlantı onayı kaydedildi. Hiçbir ödeme doğrulanmadı.",
  "No acknowledged receipt. A current unpaid link source is unavailable; older attempts remain unknown.": "Onaylanmış alındı yok. Güncel, ödenmemiş bağlantı kaynağı kullanılamıyor; eski girişimler bilinmiyor olarak kalır.",
  "Receipt inspection is unavailable. Refresh owner billing status.": "Alındı incelemesi kullanılamıyor. Kuruluş sahibinin faturalandırma durumunu yenileyin.",
  "Acknowledgment could not be confirmed. Look up the exact saved receipt before any deliberate retry.": "Onay doğrulanamadı. Bilerek yeniden denemeden önce ilgili kaydedilmiş alındıyı sorgulayın.",
  "Current owner, exact link source or proof changed. Inspect billing status before acknowledging.": "Mevcut sahip, ilgili bağlantı kaynağı veya kanıt değişti. Onaylamadan önce faturalandırma durumunu inceleyin.",
  "No saved receipt found. The same unexpired acknowledgment may be retried deliberately.": "Kaydedilmiş alındı bulunamadı. Süresi dolmamış aynı onay bilerek yeniden denenebilir.",
  "No matching receipt found. The original proof or current source is unavailable; no retry is allowed.": "Eşleşen alındı bulunamadı. Özgün kanıt veya güncel kaynak kullanılamıyor; yeniden denemeye izin verilmez.",
  "Exact receipt lookup is unavailable. No acknowledgment was replayed.": "İlgili alındı sorgulaması kullanılamıyor. Hiçbir onay tekrarlanmadı.",
  "Unreviewed Turkish browser-link receipt interface draft in local development; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe tarayıcı bağlantı alındısı arayüzü taslağı; iki dilde onay bekleniyor."
};

@Component({
  selector: 'app-checkout-link-receipt',
  template: `
    <section [attr.lang]="uiLanguage()" [attr.aria-label]="t('Checkout link receipt')">
      <h2>{{ t("Browser link receipt · organization") }} {{ organizationId() }} · {{ t("attempt") }} {{ attemptId() }}</h2>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish browser-link receipt interface draft in local development; bilingual approval is pending.") }}</p> }
      <p>{{ t("This optional record means the current owner acknowledged obtaining this application's payment link. It does not prove Paddle loaded, payment, paid access or a first-ever conversion. Older attempts remain unknown.") }}</p>
      <button type="button" (click)="inspect()" [disabled]="busy() || unknown()">{{ t("Inspect this exact saved link receipt") }}</button>
      @if (busy()) { <p role="status">{{ t("Checking the current owner and exact saved attempt.") }}</p> }
      @if (error()) { <p role="alert" [attr.lang]="uiLanguage()">{{ t(error()) }}</p> }
      @if (message()) { <p role="status" [attr.lang]="uiLanguage()">{{ t(message()) }}</p> }
      @if (receipt(); as saved) {
        <p>{{ t("First browser acknowledgment:") }} <span lang="en">{{ saved.acknowledged_at }}</span> · {{ t("source SHA256") }} <span lang="en">{{ saved.source_digest }}</span>.
          {{ t("Retained billing history, not current payment status.") }}</p>
      }
      @if (challenge(); as current) {
        <p>{{ t("Original attempt") }} <span lang="en">{{ current.source['created_at'] }}</span> · {{ t("provider request") }} <span lang="en">{{ current.source['sent_at'] }}</span> ·
          <span lang="en">{{ current.source['environment'] }}</span> · <span lang="en">{{ current.source['offer_version'] }}</span>.</p>
        <p>{{ t("Exact application link:") }} <span lang="en">{{ current.source['checkout_url'] }}</span> · {{ t("source SHA256") }} <span lang="en">{{ current.source_digest }}</span>.</p>
        <p>{{ t("Receipt proof expires at") }} <span lang="en">{{ current.expires_at }}</span>. {{ t("Inspection records no acknowledgment.") }}</p>
        <label><input type="checkbox" [checked]="consented()" (change)="consented.set($any($event.target).checked)" [disabled]="busy() || unknown()" />
          {{ t("I obtained this exact application payment link and want to record its browser receipt.") }}</label>
        <button type="button" (click)="acknowledge()" [disabled]="busy() || unknown() || !consented()">{{ t("Acknowledge obtaining this link") }}</button>
      }
      @if (unknown()) {
        <p>{{ t("The acknowledgment outcome is unknown. No payment request or acknowledgment is replayed automatically.") }}</p>
        <button type="button" (click)="lookup()" [disabled]="busy()">{{ t("Look up this exact acknowledgment") }}</button>
        @if (canRetry()) {
          <button type="button" (click)="acknowledge(true)" [disabled]="busy()">{{ t("Retry the same unexpired acknowledgment after lookup") }}</button>
        }
      }
    </section>
  `,
})
export class CheckoutLinkReceipt implements OnChanges {
  readonly language = input<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.language()));
  t(text: string) { return this.uiLanguage() === 'tr' ? checkoutReceiptTurkish[text] ?? text : text; }
  readonly organizationId = input.required<number>();
  readonly attemptId = input.required<number>();
  readonly checkoutUrl = input<string | null>(null);
  readonly challenge = signal<Challenge | null>(null);
  readonly receipt = signal<Receipt | null>(null);
  readonly busy = signal(false);
  readonly consented = signal(false);
  readonly unknown = signal(false);
  readonly canRetry = signal(false);
  readonly error = signal('');
  readonly message = signal('');
  private epoch = 0;
  private pending: Challenge | null = null;
  private expiry: ReturnType<typeof setTimeout> | null = null;

  constructor(private readonly api: AccountApi, private readonly destroyRef: DestroyRef) {
    destroyRef.onDestroy(() => this.reset());
  }
  ngOnChanges(changes?: SimpleChanges) {
    if (!changes || changes['organizationId'] || changes['attemptId'] || changes['checkoutUrl']) this.reset();
  }
  private reset() {
    ++this.epoch; if (this.expiry) clearTimeout(this.expiry); this.expiry = null;
    this.pending = null; this.challenge.set(null); this.receipt.set(null); this.busy.set(false);
    this.consented.set(false); this.unknown.set(false); this.canRetry.set(false); this.error.set(''); this.message.set('');
  }
  private current(epoch: number) { return epoch === this.epoch && !this.destroyRef.destroyed; }
  private receiptValue(value: unknown): Receipt {
    if (!object(value) || value['method'] !== METHOD || value['attempt_id'] !== this.attemptId()
      || !digest(value['source_digest']) || !dated(value['acknowledged_at']) || value['state'] !== 'acknowledged'
      || value['payment_confirmed'] !== false
      || value['interpretation'] !== 'owner_browser_acknowledged_link_not_provider_page_or_payment_proof') throw new Error();
    return structuredClone(value) as Receipt;
  }
  private async read(): Promise<Inspection> {
    const org = this.organizationId(), attempt = this.attemptId(), link = this.checkoutUrl();
    if (!positive(org) || !positive(attempt)) throw new Error();
    const response = await this.api.checkoutLinkReceipt(org, attempt), row = response.body;
    if (response.status !== 200 || row['method'] !== METHOD || row['organization_id'] !== org
      || row['attempt_id'] !== attempt || row['payment_confirmed'] !== false) throw new Error();
    const receipt = row['receipt'] === null ? null : this.receiptValue(row['receipt']);
    if (receipt) { if (row['challenge'] !== null) throw new Error(); return { receipt, challenge: null }; }
    if (row['challenge'] === null || !link) return { receipt: null, challenge: null };
    const value = structuredClone(row['challenge']);
    if (!object(value) || !object(value['source'])) throw new Error();
    const source = value['source'];
    if (value['method'] !== METHOD || !digest(value['source_digest']) || typeof value['proof'] !== 'string'
      || !/^[A-Za-z0-9_:-]{1,4096}$/.test(value['proof']) || !aware(value['expires_at'])
      || Date.parse(value['expires_at']) <= Date.now() || Date.parse(value['expires_at']) > Date.now() + 300000
      || !same(Object.keys(source).sort(), SOURCE_KEYS) || source['method'] !== 'checkout-link-delivery-source-v1'
      || source['organization_id'] !== org || source['attempt_id'] !== attempt
      || ![source['actor_id'], source['request_actor_id'], source['seller_id']].every(positive)
      || typeof source['environment'] !== 'string' || !['sandbox', 'live'].includes(source['environment'])
      || source['offer_version'] !== 'agency-launch-v1'
      || typeof source['product_id'] !== 'string' || !/^pro_[a-z0-9]{26}$/.test(source['product_id'])
      || typeof source['price_id'] !== 'string' || !/^pri_[a-z0-9]{26}$/.test(source['price_id'])
      || typeof source['transaction_id'] !== 'string' || !/^txn_[a-z0-9]{26}$/.test(source['transaction_id'])
      || source['payment_confirmed'] !== false
      || source['checkout_url'] !== link || link !== `${window.location.origin}/account/billing/checkout?_ptxn=${source['transaction_id']}`
      || !dated(source['created_at']) || !dated(source['sent_at']) || !dated(source['seller_rotated_at'])
      || Date.parse(source['created_at']) > Date.parse(source['sent_at'])
      || source['interpretation'] !== 'current_link_receipt_eligibility_not_delivered_link_or_provider_page_or_payment_proof'
      || await sourceDigest(source) !== value['source_digest']) throw new Error();
    return { receipt: null, challenge: value as Challenge };
  }
  private expire(value: Challenge) {
    if (this.expiry) clearTimeout(this.expiry);
    this.expiry = setTimeout(() => {
      this.challenge.set(null); this.consented.set(false); this.canRetry.set(false);
      if (this.pending) this.pending.proof = '';
      this.message.set("Receipt proof expired. Inspect saved history; no acknowledgment is retried.");
    }, Math.max(0, Date.parse(value.expires_at) - Date.now()));
  }
  private saved(value: Receipt) {
    if (this.expiry) clearTimeout(this.expiry); this.expiry = null;
    this.pending = null; this.unknown.set(false); this.canRetry.set(false); this.consented.set(false);
    this.challenge.set(null); this.receipt.set(value); this.message.set("First browser link acknowledgment recorded. No payment is confirmed.");
  }
  async inspect() {
    if (this.busy() || this.unknown()) return;
    const epoch = ++this.epoch; this.busy.set(true); this.error.set(''); this.message.set(''); this.challenge.set(null); this.receipt.set(null); this.consented.set(false);
    try {
      const result = await this.read(); if (!this.current(epoch)) return;
      if (result.receipt) this.saved(result.receipt);
      else if (result.challenge) { this.challenge.set(result.challenge); this.expire(result.challenge); }
      else this.message.set("No acknowledged receipt. A current unpaid link source is unavailable; older attempts remain unknown.");
    } catch { if (this.current(epoch)) this.error.set("Receipt inspection is unavailable. Refresh owner billing status."); }
    finally { if (this.current(epoch)) this.busy.set(false); }
  }
  async acknowledge(retry = false) {
    const selected = retry ? this.pending : this.challenge();
    if (!selected || this.busy() || (retry ? !this.unknown() || !this.canRetry() : this.unknown() || !this.consented())) return;
    const frozen = structuredClone(selected), epoch = this.epoch;
    this.busy.set(true); this.error.set(''); this.canRetry.set(false);
    let sent = false;
    try {
      const current = await this.read(); if (!this.current(epoch)) return;
      if (current.receipt) {
        if (current.receipt.source_digest !== frozen.source_digest) throw new Error();
        this.saved(current.receipt); return;
      }
      if (!current.challenge || current.challenge.source_digest !== frozen.source_digest
        || !same(current.challenge.source, frozen.source) || !frozen.proof || Date.parse(frozen.expires_at) <= Date.now()) throw new Error();
      this.pending = frozen; sent = true;
      const response = await this.api.acknowledgeCheckoutLink(this.organizationId(), this.attemptId(), frozen.proof);
      if (!this.current(epoch)) return;
      if (response.status !== 200) { sent = false; throw new Error(); }
      const received = this.receiptValue(response.body);
      if (received.source_digest !== frozen.source_digest || Date.parse(received.acknowledged_at) < Date.parse(String(frozen.source['sent_at']))) throw new Error();
      const verified = await this.read(); if (!this.current(epoch)) return;
      if (!verified.receipt || !same(verified.receipt, received)) throw new Error();
      this.saved(verified.receipt);
    } catch {
      if (!this.current(epoch)) return;
      this.challenge.set(null); this.consented.set(false);
      if (sent || retry) { this.pending = frozen; this.unknown.set(true); this.expire(frozen);
        this.error.set("Acknowledgment could not be confirmed. Look up the exact saved receipt before any deliberate retry."); }
      else { this.pending = null; this.error.set("Current owner, exact link source or proof changed. Inspect billing status before acknowledging."); }
    } finally { if (this.current(epoch)) this.busy.set(false); }
  }
  async lookup() {
    const frozen = this.pending; if (!frozen || !this.unknown() || this.busy()) return;
    const epoch = this.epoch; this.busy.set(true); this.error.set(''); this.canRetry.set(false);
    try {
      const result = await this.read(); if (!this.current(epoch)) return;
      if (result.receipt) {
        if (result.receipt.source_digest !== frozen.source_digest) throw new Error();
        this.saved(result.receipt);
      } else if (result.challenge && result.challenge.source_digest === frozen.source_digest
        && same(result.challenge.source, frozen.source) && !!frozen.proof && Date.parse(frozen.expires_at) > Date.now()) {
        this.canRetry.set(true); this.message.set("No saved receipt found. The same unexpired acknowledgment may be retried deliberately.");
      } else this.message.set("No matching receipt found. The original proof or current source is unavailable; no retry is allowed.");
    } catch { if (this.current(epoch)) this.error.set("Exact receipt lookup is unavailable. No acknowledgment was replayed."); }
    finally { if (this.current(epoch)) this.busy.set(false); }
  }
}
