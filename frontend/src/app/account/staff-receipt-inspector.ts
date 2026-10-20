import { Component, computed, DestroyRef, inject, OnDestroy, OnInit, signal } from '@angular/core';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';
import { AccountApi } from './account-api';
import { microseconds } from '../workspace/utc-date';

type Inspection = { method_version: string; scope: string; source_digest: string;
  receipt: { id: number; environment: string; state: string; attempts: number; error_category: string | null;
    received_at: string; claimed_at: string | null; retry_after: string | null; processed_at: string | null } };

const staffReceiptTurkish: Record<string, string> = {
  "Inspect exact retained billing receipt": "Saklanan faturalama alındısının tam kaydını inceleyin",
  "Unreviewed Turkish staff billing-receipt inspection interface draft in local development. Stored environment/state/error category and UTC timestamps remain English; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe personel faturalama alındısı inceleme arayüzü taslağı. Kayıtlı ortam/durum/hata kategorisi ve UTC zaman damgaları İngilizce kalır; iki dilli onay bekleniyor.",
  "Use an exact receipt ID obtained through authorized support. Separate receipt view permission and current session MFA are required. Each inspection is audited; no event IDs, entity IDs, customer identities, payloads or raw digests are shown.": "Yetkili destek yoluyla alınmış tam alındı kimliğini kullanın. Ayrı alındı görüntüleme izni ve güncel oturum MFA doğrulaması gerekir. Her inceleme denetim kaydına alınır; olay kimlikleri, varlık kimlikleri, müşteri kimlikleri, veri içerikleri veya ham özetler gösterilmez.",
  "Retained billing receipt ID": "Saklanan faturalama alındısı kimliği",
  "Categorical investigation reason": "Kategorik inceleme nedeni",
  "Investigation": "İnceleme",
  "Customer request": "Müşteri talebi",
  "Inspect / refresh retained receipt": "Saklanan alındıyı inceleyin / yenileyin",
  "Checking this exact retained receipt.": "Saklanan bu tam alındı kontrol ediliyor.",
  "Recorded receipt": "Kayıtlı alındı",
  "Recorded environment": "Kayıtlı ortam",
  "Recorded state": "Kayıtlı durum",
  "Current resettable attempt count": "Güncel sıfırlanabilir deneme sayısı",
  "Recorded error category": "Kayıtlı hata kategorisi",
  "None recorded": "Kayıt yok",
  "Received locally (UTC)": "Yerel alınma kaydı (UTC)",
  "Current claim recorded (UTC)": "Güncel işleme alınma kaydı (UTC)",
  "Recorded retry deadline (UTC)": "Kayıtlı yeniden deneme tarihi (UTC)",
  "Processed locally (UTC)": "Yerel işlenme kaydı (UTC)",
  "Not recorded": "Kayıtlı değil",
  "This GLOBAL record is not organization ownership, current paid truth or retry authority. Succeeded may be a no-op. Attempts are the current resettable counter, not lifetime attempts. Null dates never prove no earlier work. These local record dates are not provider occurrence times; a future retry deadline is not current retry eligibility. Inspection never contacts Paddle, requeues or changes billing; separately permitted reviewed retry remains independent.": "Bu genel kayıt kuruluş sahipliği, güncel ücretli erişimin doğrulanmış durumu veya yeniden deneme yetkisi değildir. Başarılı durum işlemin değişiklik yapmadığı anlamına gelebilir. Denemeler güncel sıfırlanabilir sayaçtır; toplam geçmiş deneme sayısı değildir. Boş tarihler daha önce işlem yapılmadığını asla kanıtlamaz. Bu yerel kayıt tarihleri sağlayıcı olay zamanları değildir; gelecekteki yeniden deneme tarihi güncel yeniden deneme uygunluğu değildir. İnceleme asla Paddle ile iletişim kurmaz, yeniden kuyruğa almaz veya faturalamayı değiştirmez; ayrıca izin verilen incelenmiş yeniden deneme işlemi bağımsızdır.",
  "Choose an exact positive receipt ID and a categorical reason.": "Tam pozitif alındı kimliği ve kategorik neden seçin.",
  "Current exact receipt inspection is unavailable. No retry or billing change was requested.": "Güncel tam alındı incelemesi kullanılamıyor. Yeniden deneme veya faturalama değişikliği istenmedi."
};

@Component({
  selector: 'app-staff-receipt-inspector',
  template: `
    <section [attr.lang]="uiLanguage()" aria-labelledby="staff-receipt-title">
      <h3 id="staff-receipt-title">{{ t("Inspect exact retained billing receipt") }}</h3>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish staff billing-receipt inspection interface draft in local development. Stored environment/state/error category and UTC timestamps remain English; bilingual approval is pending.") }}</p> }
      <p>{{ t("Use an exact receipt ID obtained through authorized support. Separate receipt view permission and current session MFA are required. Each inspection is audited; no event IDs, entity IDs, customer identities, payloads or raw digests are shown.") }}</p>
      <form (submit)="inspect($event)">
        <label for="receipt-inspect-id">{{ t("Retained billing receipt ID") }}</label>
        <input id="receipt-inspect-id" required inputmode="numeric" pattern="[1-9][0-9]{0,15}" maxlength="16"
          [value]="receiptId()" (input)="edit('receipt', $any($event.target).value)" />
        <label for="receipt-inspect-reason">{{ t("Categorical investigation reason") }}</label>
        <select id="receipt-inspect-reason" [value]="reason()" (change)="edit('reason', $any($event.target).value)">
          <option value="investigation">{{ t("Investigation") }}</option><option value="customer_request">{{ t("Customer request") }}</option>
        </select>
        <button type="submit" [disabled]="busy()">{{ t("Inspect / refresh retained receipt") }}</button>
      </form>
      @if (busy()) { <p role="status">{{ t("Checking this exact retained receipt.") }}</p> }
      @if (error()) { <p role="alert">{{ t(error()) }}</p> }
      @if (inspection(); as retained) {
        <p>{{ t("Recorded receipt") }} {{ retained.receipt.id }}.</p>
        <dl><dt>{{ t("Recorded environment") }}</dt><dd><span lang="en">{{ retained.receipt.environment }}</span></dd>
          <dt>{{ t("Recorded state") }}</dt><dd><span lang="en">{{ retained.receipt.state }}</span></dd>
          <dt>{{ t("Current resettable attempt count") }}</dt><dd>{{ retained.receipt.attempts }}</dd>
          <dt>{{ t("Recorded error category") }}</dt><dd>@if (retained.receipt.error_category) { <span lang="en">{{ retained.receipt.error_category }}</span> } @else { {{ t("None recorded") }} }</dd>
          <dt>{{ t("Received locally (UTC)") }}</dt><dd><span lang="en">{{ retained.receipt.received_at }}</span></dd>
          <dt>{{ t("Current claim recorded (UTC)") }}</dt><dd>@if (retained.receipt.claimed_at) { <span lang="en">{{ retained.receipt.claimed_at }}</span> } @else { {{ t("Not recorded") }} }</dd>
          <dt>{{ t("Recorded retry deadline (UTC)") }}</dt><dd>@if (retained.receipt.retry_after) { <span lang="en">{{ retained.receipt.retry_after }}</span> } @else { {{ t("Not recorded") }} }</dd>
          <dt>{{ t("Processed locally (UTC)") }}</dt><dd>@if (retained.receipt.processed_at) { <span lang="en">{{ retained.receipt.processed_at }}</span> } @else { {{ t("Not recorded") }} }</dd></dl>
      }
      <p>{{ t("This GLOBAL record is not organization ownership, current paid truth or retry authority. Succeeded may be a no-op. Attempts are the current resettable counter, not lifetime attempts. Null dates never prove no earlier work. These local record dates are not provider occurrence times; a future retry deadline is not current retry eligibility. Inspection never contacts Paddle, requeues or changes billing; separately permitted reviewed retry remains independent.") }}</p>
    </section>
  `,
  styles: `form { display: grid; gap: .6rem; max-width: 36rem; } p, dd { overflow-wrap: anywhere; }`,
})
export class StaffReceiptInspector implements OnInit, OnDestroy {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  private readonly destroyRef = inject(DestroyRef);
  t(text: string) { return this.uiLanguage() === 'tr' ? staffReceiptTurkish[text] ?? text : text; }
  readonly receiptId = signal('');
  readonly reason = signal('investigation');
  readonly inspection = signal<Inspection | null>(null);
  readonly busy = signal(false);
  readonly error = signal('');
  private generation = 0;
  constructor(private readonly api: AccountApi) {}
  ngOnInit() { void this.loadProductLanguage(); }
  private async loadProductLanguage() {
    try {
      const result = await this.api.productLanguage();
      if (!this.destroyRef.destroyed && result.status === 200 && isProductLanguageResult(result.body)) {
        this.productLanguage.set(result.body['language']);
      }
    } catch { /* Keep English when the private preference is unavailable. */ }
  }
  ngOnDestroy() { this.clear(); }
  clear() { this.generation++; this.inspection.set(null); this.busy.set(false); this.error.set(''); }
  edit(field: 'receipt' | 'reason', value: string) {
    this.clear();
    if (field === 'receipt') this.receiptId.set(value); else this.reason.set(value);
  }
  async inspect(event?: Event) {
    event?.preventDefault(); this.clear();
    const generation = this.generation, receipt = this.receiptId(), reason = this.reason();
    const id = /^[1-9]\d{0,15}$/.test(receipt) ? Number(receipt) : NaN;
    if (!Number.isSafeInteger(id) || id <= 0 || !['investigation', 'customer_request'].includes(reason)) {
      this.error.set('Choose an exact positive receipt ID and a categorical reason.'); return;
    }
    const current = () => generation === this.generation && receipt === this.receiptId() && reason === this.reason();
    this.busy.set(true);
    try {
      const response = await this.api.inspectPlatformPaddleReceipt(id, reason);
      if (!current()) return;
      const retained = response.status === 200 ? readInspection(response.body, id) : null;
      if (!retained) throw new Error();
      this.inspection.set(retained);
    } catch { if (current()) this.error.set('Current exact receipt inspection is unavailable. No retry or billing change was requested.'); }
    finally { if (current()) this.busy.set(false); }
  }
}

function readInspection(body: Record<string, unknown>, receiptId: number): Inspection | null {
  if (Object.keys(body).sort().join(',') !== 'method_version,receipt,scope,source_digest'
    || body['method_version'] !== 'exact-staff-retained-paddle-receipt-v1'
    || body['scope'] !== 'retained_global_receipt_not_tenant_paid_truth_lifetime_attempts_or_retry_authority'
    || typeof body['source_digest'] !== 'string' || !/^[a-f0-9]{64}$/.test(body['source_digest'])) return null;
  const raw = body['receipt'];
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const row = raw as Record<string, unknown>;
  if (Object.keys(row).sort().join(',') !== 'attempts,claimed_at,environment,error_category,id,processed_at,received_at,retry_after,state'
    || row['id'] !== receiptId || !['sandbox', 'live'].includes(String(row['environment']))
    || typeof row['environment'] !== 'string' || typeof row['state'] !== 'string'
    || !['pending', 'ignored', 'processing', 'failed', 'succeeded'].includes(row['state'])
    || typeof row['attempts'] !== 'number' || !Number.isInteger(row['attempts']) || row['attempts'] < 0 || row['attempts'] > 3) return null;
  const received = microseconds(row['received_at']), claim = microseconds(row['claimed_at']),
    retry = microseconds(row['retry_after']), processed = microseconds(row['processed_at']), now = BigInt(Date.now()) * 1000n;
  if (received === null || received > now
    || ['claimed_at', 'retry_after', 'processed_at'].some(key => row[key] !== null && microseconds(row[key]) === null)
    || claim !== null && (claim < received || claim > now)
    || retry !== null && (claim === null || retry < claim)
    || processed !== null && (claim === null || processed < claim || processed > now)) return null;
  const state = row['state'], category = row['error_category'];
  if (['pending', 'ignored'].includes(state) && (row['attempts'] !== 0 || claim !== null || retry !== null || processed !== null)
    || ['processing', 'failed', 'succeeded'].includes(state) && (row['attempts'] < 1 || claim === null)
    || state !== 'failed' && (category !== null || retry !== null)
    || state === 'failed' && (typeof category !== 'string' || !['quota_limited', 'provider_unavailable', 'timeout', 'network_error',
      'dns_error', 'identity_review', 'authorization_unavailable', 'worker_lost', 'unclassified_failure'].includes(category))
    || state === 'succeeded' && processed === null || state !== 'succeeded' && processed !== null) return null;
  return structuredClone(body) as Inspection;
}
