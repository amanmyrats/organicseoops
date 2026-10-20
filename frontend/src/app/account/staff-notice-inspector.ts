import { Component, computed, DestroyRef, inject, OnDestroy, OnInit, signal } from '@angular/core';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';
import { AccountApi } from './account-api';
import { microseconds } from '../workspace/utc-date';

type Notice = { id: number; kind: string; state: string; manual_retries: number;
  created_at: string; attempted_at: string | null; sent_at: string | null };
type Inspection = { method_version: string; organization_id: number; scope: string; source_digest: string; notice: Notice };

const staffNoticeTurkish: Record<string, string> = {
  "Inspect exact organization notice transport": "Kuruluş bildiriminin tam aktarım kaydını inceleyin",
  "Unreviewed Turkish staff notice-inspection interface draft in local development. Stored kind/state and UTC timestamps remain English; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe personel bildirim inceleme arayüzü taslağı. Kayıtlı tür/durum ve UTC zaman damgaları İngilizce kalır; iki dilli onay bekleniyor.",
  "Use IDs already obtained through authorized support. Both organization and notice view permissions and current session MFA are required. Each inspection is audited; no address, body, raw error, account mail or billing source is shown.": "Yetkili destek yoluyla önceden alınmış kimlikleri kullanın. Kuruluş ve bildirim görüntüleme izinlerinin ikisi de ve güncel oturum MFA doğrulaması gerekir. Her inceleme denetim kaydına alınır; adres, içerik, ham hata, hesap e-postası veya faturalama kaynağı gösterilmez.",
  "Organization ID": "Kuruluş kimliği",
  "Notice ID": "Bildirim kimliği",
  "Categorical investigation reason": "Kategorik inceleme nedeni",
  "Investigation": "İnceleme",
  "Customer request": "Müşteri talebi",
  "Inspect / refresh recorded notice": "Kayıtlı bildirimi inceleyin / yenileyin",
  "Checking this exact retained notice.": "Saklanan bu tam bildirim kontrol ediliyor.",
  "Notice": "Bildirim",
  "organization": "kuruluş",
  "recorded kind": "kayıtlı tür",
  "recorded transport state": "kayıtlı aktarım durumu",
  "Created (UTC)": "Oluşturulma (UTC)",
  "Attempt recorded (UTC)": "Deneme kaydı (UTC)",
  "Transport acceptance recorded (UTC)": "Aktarım kabulü kaydı (UTC)",
  "Recorded manual reissues": "Kayıtlı manuel yeniden gönderimler",
  "No recorded attempt": "Kayıtlı deneme yok",
  "No recorded acceptance": "Kayıtlı kabul yok",
  "Sent is recorded transport acceptance, not inbox delivery or a read receipt. Sending or unknown may already have sent mail; missing acceptance is not proof of no mail. The retry count is history, not current eligibility or consent. Inspection never requeues, recovers or sends mail; any separately acknowledged reissue may duplicate an earlier send.": "Sent, kayıtlı aktarım kabulüdür; gelen kutusuna teslim veya okundu bilgisi değildir. Sending veya unknown durumunda e-posta zaten gönderilmiş olabilir; kabul kaydının olmaması e-posta gönderilmediğinin kanıtı değildir. Yeniden deneme sayısı geçmiş kaydıdır; güncel uygunluk veya onay değildir. İnceleme asla yeniden kuyruğa almaz, kurtarma işlemi yapmaz veya e-posta göndermez; ayrıca onaylanan herhangi bir yeniden gönderim önceki gönderimi yineleyebilir.",
  "Choose one exact positive organization and notice ID and a categorical reason.": "Bir tam pozitif kuruluş ve bildirim kimliği ile kategorik neden seçin.",
  "Current scoped notice inspection is unavailable. No reissue or send was requested.": "Güncel kapsamlı bildirim incelemesi kullanılamıyor. Yeniden gönderim veya gönderim istenmedi.",
};

@Component({
  selector: 'app-staff-notice-inspector',
  template: `
    <section [attr.lang]="uiLanguage()" aria-labelledby="staff-notice-title">
      <h3 id="staff-notice-title">{{ t("Inspect exact organization notice transport") }}</h3>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish staff notice-inspection interface draft in local development. Stored kind/state and UTC timestamps remain English; bilingual approval is pending.") }}</p> }
      <p>{{ t("Use IDs already obtained through authorized support. Both organization and notice view permissions and current session MFA are required. Each inspection is audited; no address, body, raw error, account mail or billing source is shown.") }}</p>
      <form (submit)="inspect($event)">
        <label for="notice-inspect-organization">{{ t("Organization ID") }}</label>
        <input id="notice-inspect-organization" required inputmode="numeric" pattern="[1-9][0-9]{0,15}" maxlength="16"
          [value]="organization()" (input)="edit('organization', $any($event.target).value)" />
        <label for="notice-inspect-id">{{ t("Notice ID") }}</label>
        <input id="notice-inspect-id" required inputmode="numeric" pattern="[1-9][0-9]{0,15}" maxlength="16"
          [value]="noticeId()" (input)="edit('notice', $any($event.target).value)" />
        <label for="notice-inspect-reason">{{ t("Categorical investigation reason") }}</label>
        <select id="notice-inspect-reason" [value]="reason()" (change)="edit('reason', $any($event.target).value)">
          <option value="investigation">{{ t("Investigation") }}</option><option value="customer_request">{{ t("Customer request") }}</option>
        </select>
        <button type="submit" [disabled]="busy()">{{ t("Inspect / refresh recorded notice") }}</button>
      </form>
      @if (busy()) { <p role="status">{{ t("Checking this exact retained notice.") }}</p> }
      @if (error()) { <p role="alert">{{ t(error()) }}</p> }
      @if (inspection(); as retained) {
        <p>{{ t("Notice") }} {{ retained.notice.id }} · {{ t("organization") }} {{ retained.organization_id }} · {{ t("recorded kind") }} <span lang="en">{{ retained.notice.kind }}</span> · {{ t("recorded transport state") }} <span lang="en">{{ retained.notice.state }}</span>.</p>
        <dl><dt>{{ t("Created (UTC)") }}</dt><dd><span lang="en">{{ retained.notice.created_at }}</span></dd>
          <dt>{{ t("Attempt recorded (UTC)") }}</dt><dd>@if (retained.notice.attempted_at) { <span lang="en">{{ retained.notice.attempted_at }}</span> } @else { {{ t("No recorded attempt") }} }</dd>
          <dt>{{ t("Transport acceptance recorded (UTC)") }}</dt><dd>@if (retained.notice.sent_at) { <span lang="en">{{ retained.notice.sent_at }}</span> } @else { {{ t("No recorded acceptance") }} }</dd>
          <dt>{{ t("Recorded manual reissues") }}</dt><dd>{{ retained.notice.manual_retries }}</dd></dl>
      }
      <p>{{ t("Sent is recorded transport acceptance, not inbox delivery or a read receipt. Sending or unknown may already have sent mail; missing acceptance is not proof of no mail. The retry count is history, not current eligibility or consent. Inspection never requeues, recovers or sends mail; any separately acknowledged reissue may duplicate an earlier send.") }}</p>
    </section>
  `,
  styles: `form { display: grid; gap: .6rem; max-width: 36rem; } p, dd { overflow-wrap: anywhere; }`,
})
export class StaffNoticeInspector implements OnInit, OnDestroy {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  private readonly destroyRef = inject(DestroyRef);
  t(text: string) { return this.uiLanguage() === 'tr' ? staffNoticeTurkish[text] ?? text : text; }
  readonly organization = signal('');
  readonly noticeId = signal('');
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
  edit(field: 'organization' | 'notice' | 'reason', value: string) {
    this.clear();
    if (field === 'organization') this.organization.set(value);
    else if (field === 'notice') this.noticeId.set(value);
    else this.reason.set(value);
  }
  async inspect(event?: Event) {
    event?.preventDefault(); this.clear();
    const generation = this.generation, organization = this.organization(), notice = this.noticeId(), reason = this.reason();
    const orgId = /^[1-9]\d{0,15}$/.test(organization) ? Number(organization) : NaN;
    const noticeId = /^[1-9]\d{0,15}$/.test(notice) ? Number(notice) : NaN;
    if (![orgId, noticeId].every(value => Number.isSafeInteger(value) && value > 0) || !['investigation', 'customer_request'].includes(reason)) {
      this.error.set('Choose one exact positive organization and notice ID and a categorical reason.'); return;
    }
    const current = () => generation === this.generation && organization === this.organization() && notice === this.noticeId() && reason === this.reason();
    this.busy.set(true);
    try {
      const response = await this.api.inspectPlatformNotice(orgId, noticeId, reason);
      if (!current()) return;
      const retained = response.status === 200 ? readInspection(response.body, orgId, noticeId) : null;
      if (!retained) throw new Error();
      this.inspection.set(retained);
    } catch { if (current()) this.error.set('Current scoped notice inspection is unavailable. No reissue or send was requested.'); }
    finally { if (current()) this.busy.set(false); }
  }
}

function readInspection(body: Record<string, unknown>, orgId: number, noticeId: number): Inspection | null {
  if (Object.keys(body).sort().join(',') !== 'method_version,notice,organization_id,scope,source_digest'
    || body['method_version'] !== 'scoped-staff-organization-notice-v1' || body['organization_id'] !== orgId
    || body['scope'] !== 'recorded_transport_not_inbox_delivery_current_eligibility_reissue_billing_or_account_mail_authority'
    || typeof body['source_digest'] !== 'string' || !/^[a-f0-9]{64}$/.test(body['source_digest'])) return null;
  const row = body['notice'];
  if (!row || typeof row !== 'object' || Array.isArray(row)) return null;
  const value = row as Record<string, unknown>;
  if (Object.keys(value).sort().join(',') !== 'attempted_at,created_at,id,kind,manual_retries,sent_at,state' || value['id'] !== noticeId
    || typeof value['kind'] !== 'string' || !['trial_ending', 'trial_units_exhausted', 'payment_failed', 'paid_units_exhausted'].includes(value['kind'])
    || typeof value['state'] !== 'string' || !['queued', 'sending', 'sent', 'unknown', 'skipped'].includes(value['state'])
    || ![0, 1].includes(value['manual_retries'] as number)) return null;
  const created = microseconds(value['created_at']), attempted = value['attempted_at'] === null ? null : microseconds(value['attempted_at']);
  const sent = value['sent_at'] === null ? null : microseconds(value['sent_at']), now = BigInt(Date.now()) * 1000n;
  if (created === null || created > now || value['attempted_at'] !== null && attempted === null || value['sent_at'] !== null && sent === null
    || (value['state'] === 'queued') !== (value['attempted_at'] === null) || (value['state'] === 'sent') !== (value['sent_at'] !== null)
    || attempted !== null && (attempted < created || attempted > now) || sent !== null && (attempted === null || sent < attempted || sent > now)) return null;
  return structuredClone(body) as Inspection;
}
