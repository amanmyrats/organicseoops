import { Component, computed, DestroyRef, inject, OnDestroy, OnInit, signal } from '@angular/core';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';
import { AccountApi } from './account-api';
import { microseconds } from '../workspace/utc-date';

type Delivery = { id: number; state: string; attempted_at: string; finished_at: string | null };
type Inspection = { method_version: string; user_id: number; email_address_id: number;
  scope: string; source_digest: string; delivery: Delivery };

const staffMailTurkish: Record<string, string> = {
  "Inspect exact current account-mail record": "Güncel hesap e-postasının tam kaydını inceleyin",
  "Unreviewed Turkish staff account-mail inspection interface draft in local development. Stored state and UTC timestamps remain English; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe personel hesap e-postası inceleme arayüzü taslağı. Kayıtlı durum ve UTC zaman damgaları İngilizce kalır; iki dilli onay bekleniyor.",
  "Use IDs already obtained through authorized support. Both user and account-mail view permissions and current session MFA are required. Each inspection is audited; no address, purpose, message or token is shown.": "Yetkili destek yoluyla önceden alınmış kimlikleri kullanın. Kullanıcı ve hesap e-postası görüntüleme izinlerinin ikisi de ve güncel oturum MFA doğrulaması gerekir. Her inceleme denetim kaydına alınır; adres, amaç, mesaj veya belirteç gösterilmez.",
  "Current user ID": "Güncel kullanıcı kimliği",
  "Address record ID": "Adres kaydı kimliği",
  "Delivery record ID": "Gönderim kaydı kimliği",
  "Categorical investigation reason": "Kategorik inceleme nedeni",
  "Investigation": "İnceleme",
  "Customer request": "Müşteri talebi",
  "Inspect / refresh recorded account mail": "Kayıtlı hesap e-postasını inceleyin / yenileyin",
  "Checking this exact retained record.": "Saklanan bu tam kayıt kontrol ediliyor.",
  "Delivery": "Gönderim",
  "current user": "güncel kullanıcı",
  "address record": "adres kaydı",
  "recorded transport state": "kayıtlı aktarım durumu",
  "Attempt recorded (UTC)": "Deneme kaydı (UTC)",
  "Attempt finish recorded (UTC)": "Denemenin bitiş kaydı (UTC)",
  "No recorded finish": "Kayıtlı bitiş yok",
  "Current record linkage is not proof of the original recipient or message purpose. Transport returned is not inbox delivery or a read receipt. Attempted or unknown may already have sent mail; a suppressed record does not prove current suppression. Verification and reset tokens cannot be replayed here. Inspection never sends mail or grants recovery or resend eligibility. Retained inactive or access-closed target history is restricted, not erased.": "Güncel kayıt bağlantısı, özgün alıcının veya mesaj amacının kanıtı değildir. Aktarımın tamamlanıp geri dönmesi, gelen kutusuna teslim veya okundu bilgisi değildir. Denenmiş veya durumu bilinmeyen gönderimlerde e-posta zaten gönderilmiş olabilir; engellenmiş gönderim kaydı güncel engellemenin kanıtı değildir. Doğrulama ve sıfırlama belirteçleri burada yeniden kullanılamaz. İnceleme asla e-posta göndermez veya kurtarma ya da yeniden gönderim uygunluğu sağlamaz. Saklanan etkin olmayan veya erişimi kapatılmış hedef geçmişi kısıtlıdır; silinmiş değildir.",
  "Choose exact positive user, address record and delivery IDs and a categorical reason.": "Tam pozitif kullanıcı, adres kaydı ve gönderim kimlikleri ile kategorik neden seçin.",
  "Current scoped account-mail inspection is unavailable. No recovery or send was requested.": "Güncel kapsamlı hesap e-postası incelemesi kullanılamıyor. Kurtarma veya gönderim istenmedi."
};

@Component({
  selector: 'app-staff-mail-inspector',
  template: `
    <section [attr.lang]="uiLanguage()" aria-labelledby="staff-mail-title">
      <h3 id="staff-mail-title">{{ t("Inspect exact current account-mail record") }}</h3>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish staff account-mail inspection interface draft in local development. Stored state and UTC timestamps remain English; bilingual approval is pending.") }}</p> }
      <p>{{ t("Use IDs already obtained through authorized support. Both user and account-mail view permissions and current session MFA are required. Each inspection is audited; no address, purpose, message or token is shown.") }}</p>
      <form (submit)="inspect($event)">
        <label for="mail-inspect-user">{{ t("Current user ID") }}</label>
        <input id="mail-inspect-user" required inputmode="numeric" pattern="[1-9][0-9]{0,15}" maxlength="16"
          [value]="userId()" (input)="edit('user', $any($event.target).value)" />
        <label for="mail-inspect-address">{{ t("Address record ID") }}</label>
        <input id="mail-inspect-address" required inputmode="numeric" pattern="[1-9][0-9]{0,15}" maxlength="16"
          [value]="addressId()" (input)="edit('address', $any($event.target).value)" />
        <label for="mail-inspect-delivery">{{ t("Delivery record ID") }}</label>
        <input id="mail-inspect-delivery" required inputmode="numeric" pattern="[1-9][0-9]{0,15}" maxlength="16"
          [value]="deliveryId()" (input)="edit('delivery', $any($event.target).value)" />
        <label for="mail-inspect-reason">{{ t("Categorical investigation reason") }}</label>
        <select id="mail-inspect-reason" [value]="reason()" (change)="edit('reason', $any($event.target).value)">
          <option value="investigation">{{ t("Investigation") }}</option><option value="customer_request">{{ t("Customer request") }}</option>
        </select>
        <button type="submit" [disabled]="busy()">{{ t("Inspect / refresh recorded account mail") }}</button>
      </form>
      @if (busy()) { <p role="status">{{ t("Checking this exact retained record.") }}</p> }
      @if (error()) { <p role="alert">{{ t(error()) }}</p> }
      @if (inspection(); as retained) {
        <p>{{ t("Delivery") }} {{ retained.delivery.id }} · {{ t("current user") }} {{ retained.user_id }} · {{ t("address record") }} {{ retained.email_address_id }} · {{ t("recorded transport state") }} <span lang="en">{{ retained.delivery.state }}</span>.</p>
        <dl><dt>{{ t("Attempt recorded (UTC)") }}</dt><dd><span lang="en">{{ retained.delivery.attempted_at }}</span></dd>
          <dt>{{ t("Attempt finish recorded (UTC)") }}</dt><dd>@if (retained.delivery.finished_at) { <span lang="en">{{ retained.delivery.finished_at }}</span> } @else { {{ t("No recorded finish") }} }</dd></dl>
      }
      <p>{{ t("Current record linkage is not proof of the original recipient or message purpose. Transport returned is not inbox delivery or a read receipt. Attempted or unknown may already have sent mail; a suppressed record does not prove current suppression. Verification and reset tokens cannot be replayed here. Inspection never sends mail or grants recovery or resend eligibility. Retained inactive or access-closed target history is restricted, not erased.") }}</p>
    </section>
  `,
  styles: `form { display: grid; gap: .6rem; max-width: 36rem; } p, dd { overflow-wrap: anywhere; }`,
})
export class StaffMailInspector implements OnInit, OnDestroy {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  private readonly destroyRef = inject(DestroyRef);
  t(text: string) { return this.uiLanguage() === 'tr' ? staffMailTurkish[text] ?? text : text; }
  readonly userId = signal('');
  readonly addressId = signal('');
  readonly deliveryId = signal('');
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
  edit(field: 'user' | 'address' | 'delivery' | 'reason', value: string) {
    this.clear();
    if (field === 'user') this.userId.set(value);
    else if (field === 'address') this.addressId.set(value);
    else if (field === 'delivery') this.deliveryId.set(value);
    else this.reason.set(value);
  }
  async inspect(event?: Event) {
    event?.preventDefault(); this.clear();
    const generation = this.generation, user = this.userId(), address = this.addressId(), delivery = this.deliveryId(), reason = this.reason();
    const ids = [user, address, delivery].map(value => /^[1-9]\d{0,15}$/.test(value) ? Number(value) : NaN);
    if (!ids.every(value => Number.isSafeInteger(value) && value > 0) || !['investigation', 'customer_request'].includes(reason)) {
      this.error.set('Choose exact positive user, address record and delivery IDs and a categorical reason.'); return;
    }
    const current = () => generation === this.generation && user === this.userId() && address === this.addressId() && delivery === this.deliveryId() && reason === this.reason();
    this.busy.set(true);
    try {
      const response = await this.api.inspectPlatformAccountMail(ids[0], ids[1], ids[2], reason);
      if (!current()) return;
      const retained = response.status === 200 ? readInspection(response.body, ids[0], ids[1], ids[2]) : null;
      if (!retained) throw new Error();
      this.inspection.set(retained);
    } catch { if (current()) this.error.set('Current scoped account-mail inspection is unavailable. No recovery or send was requested.'); }
    finally { if (current()) this.busy.set(false); }
  }
}

function readInspection(body: Record<string, unknown>, userId: number, addressId: number, deliveryId: number): Inspection | null {
  if (Object.keys(body).sort().join(',') !== 'delivery,email_address_id,method_version,scope,source_digest,user_id'
    || body['method_version'] !== 'scoped-staff-current-account-mail-v1' || body['user_id'] !== userId || body['email_address_id'] !== addressId
    || body['scope'] !== 'current_record_linkage_not_original_recipient_purpose_inbox_current_suppression_or_resend_authority'
    || typeof body['source_digest'] !== 'string' || !/^[a-f0-9]{64}$/.test(body['source_digest'])) return null;
  const row = body['delivery'];
  if (!row || typeof row !== 'object' || Array.isArray(row)) return null;
  const value = row as Record<string, unknown>;
  if (Object.keys(value).sort().join(',') !== 'attempted_at,finished_at,id,state' || value['id'] !== deliveryId
    || typeof value['state'] !== 'string' || !['attempted', 'transport_returned', 'unknown', 'suppressed'].includes(value['state'])) return null;
  const attempted = microseconds(value['attempted_at']), finished = value['finished_at'] === null ? null : microseconds(value['finished_at']);
  const now = BigInt(Date.now()) * 1000n;
  if (attempted === null || attempted > now || value['finished_at'] !== null && finished === null
    || (value['state'] === 'attempted') !== (value['finished_at'] === null)
    || finished !== null && (finished < attempted || finished > now)) return null;
  return structuredClone(body) as Inspection;
}
