import { Component, computed, DestroyRef, inject, OnDestroy, OnInit, signal } from '@angular/core';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';
import { AccountApi } from './account-api';
import { microseconds } from '../workspace/utc-date';

type Inspection = { method_version: string; user_id: number; email_address_id: number; scope: string; source_digest: string;
  suppression: { id: number; reason: string; created_at: string }; feedback: { id: number; kind: string; received_at: string } };

const staffFeedbackTurkish: Record<string, string> = {
  "Inspect exact retained suppression and first feedback": "Saklanan engelleme ve ilk geri bildirimin tam kaydını inceleyin",
  "Unreviewed Turkish staff feedback-inspection interface draft in local development. Stored reason/kind and local UTC timestamps remain English; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe personel geri bildirim inceleme arayüzü taslağı. Kayıtlı neden/tür ve yerel UTC zaman damgaları İngilizce kalır; iki dilli onay bekleniyor.",
  "Use IDs already obtained through authorized support. User, suppression and feedback view permissions and current session MFA are required. Each inspection is audited; no addresses, event IDs, payloads or raw digests are shown.": "Yetkili destek yoluyla önceden alınmış kimlikleri kullanın. Kullanıcı, engelleme ve geri bildirim görüntüleme izinleri ve güncel oturum MFA doğrulaması gerekir. Her inceleme denetim kaydına alınır; adresler, olay kimlikleri, veri içerikleri veya ham özetler gösterilmez.",
  "Current user ID": "Güncel kullanıcı kimliği",
  "Address record ID": "Adres kaydı kimliği",
  "Suppression record ID": "Engelleme kaydı kimliği",
  "Categorical investigation reason": "Kategorik inceleme nedeni",
  "Investigation": "İnceleme",
  "Customer request": "Müşteri talebi",
  "Inspect / refresh retained feedback": "Saklanan geri bildirimi inceleyin / yenileyin",
  "Checking this exact retained record.": "Saklanan bu tam kayıt kontrol ediliyor.",
  "Suppression": "Engelleme",
  "current user": "güncel kullanıcı",
  "address record": "adres kaydı",
  "first feedback": "ilk geri bildirim",
  "Recorded suppression reason": "Kayıtlı engelleme nedeni",
  "Suppression created locally (UTC)": "Engellemenin yerel oluşturulma kaydı (UTC)",
  "First linked feedback kind": "İlk bağlantılı geri bildirim türü",
  "Feedback received locally (UTC)": "Geri bildirimin yerel alınma kaydı (UTC)",
  "Current record linkage is not proof of the original recipient, provider occurrence, current suppression applicability or clearance eligibility. These are local record dates, not SES event times. Later feedback does not replace the first linked receipt. Retained inactive or access-closed history is restricted, not erased. Inspection never clears, sends or replays mail; reviewed clearance remains separately permitted.": "Güncel kayıt bağlantısı, özgün alıcının, sağlayıcı olayının, engellemenin güncel uygulanabilirliğinin veya kaldırma uygunluğunun kanıtı değildir. Bunlar yerel kayıt tarihleridir; SES olay zamanları değildir. Sonraki geri bildirim ilk bağlantılı alındı kaydının yerini almaz. Saklanan etkin olmayan veya erişimi kapatılmış geçmiş kısıtlıdır; silinmiş değildir. İnceleme asla engellemeyi kaldırmaz, e-posta göndermez veya yeniden oynatmaz; incelenmiş kaldırma işlemi ayrı izin gerektirir.",
  "Choose exact positive user, address record and suppression IDs and a categorical reason.": "Tam pozitif kullanıcı, adres kaydı ve engelleme kimlikleri ile kategorik neden seçin.",
  "Current scoped feedback inspection is unavailable. No clearance or send was requested.": "Güncel kapsamlı geri bildirim incelemesi kullanılamıyor. Engellemeyi kaldırma veya gönderim istenmedi."
};

@Component({
  selector: 'app-staff-feedback-inspector',
  template: `
    <section [attr.lang]="uiLanguage()" aria-labelledby="staff-feedback-title">
      <h3 id="staff-feedback-title">{{ t("Inspect exact retained suppression and first feedback") }}</h3>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish staff feedback-inspection interface draft in local development. Stored reason/kind and local UTC timestamps remain English; bilingual approval is pending.") }}</p> }
      <p>{{ t("Use IDs already obtained through authorized support. User, suppression and feedback view permissions and current session MFA are required. Each inspection is audited; no addresses, event IDs, payloads or raw digests are shown.") }}</p>
      <form (submit)="inspect($event)">
        <label for="feedback-inspect-user">{{ t("Current user ID") }}</label>
        <input id="feedback-inspect-user" required inputmode="numeric" pattern="[1-9][0-9]{0,15}" maxlength="16"
          [value]="userId()" (input)="edit('user', $any($event.target).value)" />
        <label for="feedback-inspect-address">{{ t("Address record ID") }}</label>
        <input id="feedback-inspect-address" required inputmode="numeric" pattern="[1-9][0-9]{0,15}" maxlength="16"
          [value]="addressId()" (input)="edit('address', $any($event.target).value)" />
        <label for="feedback-inspect-suppression">{{ t("Suppression record ID") }}</label>
        <input id="feedback-inspect-suppression" required inputmode="numeric" pattern="[1-9][0-9]{0,15}" maxlength="16"
          [value]="suppressionId()" (input)="edit('suppression', $any($event.target).value)" />
        <label for="feedback-inspect-reason">{{ t("Categorical investigation reason") }}</label>
        <select id="feedback-inspect-reason" [value]="reason()" (change)="edit('reason', $any($event.target).value)">
          <option value="investigation">{{ t("Investigation") }}</option><option value="customer_request">{{ t("Customer request") }}</option>
        </select>
        <button type="submit" [disabled]="busy()">{{ t("Inspect / refresh retained feedback") }}</button>
      </form>
      @if (busy()) { <p role="status">{{ t("Checking this exact retained record.") }}</p> }
      @if (error()) { <p role="alert">{{ t(error()) }}</p> }
      @if (inspection(); as retained) {
        <p>{{ t("Suppression") }} {{ retained.suppression.id }} · {{ t("current user") }} {{ retained.user_id }} · {{ t("address record") }} {{ retained.email_address_id }} · {{ t("first feedback") }} {{ retained.feedback.id }}.</p>
        <dl><dt>{{ t("Recorded suppression reason") }}</dt><dd><span lang="en">{{ retained.suppression.reason }}</span></dd>
          <dt>{{ t("Suppression created locally (UTC)") }}</dt><dd><span lang="en">{{ retained.suppression.created_at }}</span></dd>
          <dt>{{ t("First linked feedback kind") }}</dt><dd><span lang="en">{{ retained.feedback.kind }}</span></dd>
          <dt>{{ t("Feedback received locally (UTC)") }}</dt><dd><span lang="en">{{ retained.feedback.received_at }}</span></dd></dl>
      }
      <p>{{ t("Current record linkage is not proof of the original recipient, provider occurrence, current suppression applicability or clearance eligibility. These are local record dates, not SES event times. Later feedback does not replace the first linked receipt. Retained inactive or access-closed history is restricted, not erased. Inspection never clears, sends or replays mail; reviewed clearance remains separately permitted.") }}</p>
    </section>
  `,
  styles: `form { display: grid; gap: .6rem; max-width: 36rem; } p, dd { overflow-wrap: anywhere; }`,
})
export class StaffFeedbackInspector implements OnInit, OnDestroy {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  private readonly destroyRef = inject(DestroyRef);
  t(text: string) { return this.uiLanguage() === 'tr' ? staffFeedbackTurkish[text] ?? text : text; }
  readonly userId = signal('');
  readonly addressId = signal('');
  readonly suppressionId = signal('');
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
  edit(field: 'user' | 'address' | 'suppression' | 'reason', value: string) {
    this.clear();
    if (field === 'user') this.userId.set(value);
    else if (field === 'address') this.addressId.set(value);
    else if (field === 'suppression') this.suppressionId.set(value);
    else this.reason.set(value);
  }
  async inspect(event?: Event) {
    event?.preventDefault(); this.clear();
    const generation = this.generation, user = this.userId(), address = this.addressId(), suppression = this.suppressionId(), reason = this.reason();
    const ids = [user, address, suppression].map(value => /^[1-9]\d{0,15}$/.test(value) ? Number(value) : NaN);
    if (!ids.every(value => Number.isSafeInteger(value) && value > 0) || !['investigation', 'customer_request'].includes(reason)) {
      this.error.set('Choose exact positive user, address record and suppression IDs and a categorical reason.'); return;
    }
    const current = () => generation === this.generation && user === this.userId() && address === this.addressId() && suppression === this.suppressionId() && reason === this.reason();
    this.busy.set(true);
    try {
      const response = await this.api.inspectPlatformEmailFeedback(ids[0], ids[1], ids[2], reason);
      if (!current()) return;
      const retained = response.status === 200 ? readInspection(response.body, ids[0], ids[1], ids[2]) : null;
      if (!retained) throw new Error();
      this.inspection.set(retained);
    } catch { if (current()) this.error.set('Current scoped feedback inspection is unavailable. No clearance or send was requested.'); }
    finally { if (current()) this.busy.set(false); }
  }
}

function readInspection(body: Record<string, unknown>, userId: number, addressId: number, suppressionId: number): Inspection | null {
  if (Object.keys(body).sort().join(',') !== 'email_address_id,feedback,method_version,scope,source_digest,suppression,user_id'
    || body['method_version'] !== 'scoped-staff-retained-email-feedback-v1' || body['user_id'] !== userId || body['email_address_id'] !== addressId
    || body['scope'] !== 'current_record_first_feedback_not_original_recipient_provider_occurrence_current_applicability_or_clearance_authority'
    || typeof body['source_digest'] !== 'string' || !/^[a-f0-9]{64}$/.test(body['source_digest'])) return null;
  const raw = [body['suppression'], body['feedback']];
  if (raw.some(value => !value || typeof value !== 'object' || Array.isArray(value))) return null;
  const [suppression, feedback] = raw as Record<string, unknown>[];
  if (Object.keys(suppression).sort().join(',') !== 'created_at,id,reason' || suppression['id'] !== suppressionId
    || typeof suppression['reason'] !== 'string' || !['permanent_bounce', 'complaint'].includes(suppression['reason'])
    || Object.keys(feedback).sort().join(',') !== 'id,kind,received_at' || feedback['kind'] !== suppression['reason']
    || typeof feedback['id'] !== 'number' || !Number.isSafeInteger(feedback['id']) || feedback['id'] <= 0) return null;
  const created = microseconds(suppression['created_at']), received = microseconds(feedback['received_at']);
  const now = BigInt(Date.now()) * 1000n;
  if (created === null || received === null || received > created || created > now) return null;
  return structuredClone(body) as Inspection;
}
