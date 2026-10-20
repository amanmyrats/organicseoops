import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, effect, OnInit, signal, computed } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi } from '../account/account-api';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';

type Deletion = { source: string; state: string; eligible_at: string; due_at: string;
  completed_at: string | null; error_category: string; backup_latest_expiry_bound_at: string | null };
type Cancellation = { state: string; error_category: string };
type Closure = { organization_id: number; state: 'open' | 'closed' | 'retention_cleanup';
  closed_at: string | null; close_action_available: boolean; deletion: Deletion | null;
  billing_cancellation: Cancellation | null;
  remote_revocation_pending: { search_console: number; analytics: number; business_profile?: number; yandex?: number; repository?: number };
  repository_unknown_exchanges?: { id: number; can_report_revoked: boolean }[];
  pending_grants: { search_console: number[]; analytics: number[]; business_profile?: number[]; yandex?: number[]; repository?: number[] }; limitations: string };

function isClosure(value: unknown, organizationId: number): value is Closure {
  if (!value || typeof value !== 'object') return false;
  const row = value as Record<string, unknown>;
  const deletion = row['deletion'] as Record<string, unknown> | null;
  const billing = row['billing_cancellation'] as Record<string, unknown> | null;
  const remote = row['remote_revocation_pending'] as Record<string, unknown> | undefined;
  const pending = row['pending_grants'] as Record<string, unknown> | undefined;
  return row['organization_id'] === organizationId
    && typeof row['state'] === 'string' && ['open', 'closed', 'retention_cleanup'].includes(row['state'])
    && typeof row['close_action_available'] === 'boolean'
    && (row['repository_unknown_exchanges'] === undefined || Array.isArray(row['repository_unknown_exchanges'])
      && row['repository_unknown_exchanges'].length <= 20 && row['repository_unknown_exchanges'].every((item: unknown) => {
        if (!item || typeof item !== 'object') return false;
        const consent = item as Record<string, unknown>;
        return Number.isSafeInteger(consent['id']) && Number(consent['id']) > 0 && typeof consent['can_report_revoked'] === 'boolean';
      }))
    && (row['closed_at'] === null || typeof row['closed_at'] === 'string')
    && (deletion === null || !!deletion && typeof deletion['state'] === 'string'
      && typeof deletion['source'] === 'string' && typeof deletion['eligible_at'] === 'string'
      && typeof deletion['due_at'] === 'string' && typeof deletion['error_category'] === 'string')
    && (billing === null || !!billing && typeof billing['state'] === 'string'
      && typeof billing['error_category'] === 'string')
    && !!remote && Number.isSafeInteger(remote['search_console'])
    && Number.isSafeInteger(remote['analytics']) && !!pending
    && (remote['repository'] === undefined || Number.isSafeInteger(remote['repository']) && Number(remote['repository']) >= 0)
    && (pending['repository'] === undefined || Array.isArray(pending['repository']) && pending['repository'].length <= 20
      && pending['repository'].every((id) => Number.isSafeInteger(id) && Number(id) > 0))
    && (remote['yandex'] === undefined || Number.isSafeInteger(remote['yandex']) && Number(remote['yandex']) >= 0)
    && (pending['yandex'] === undefined || Array.isArray(pending['yandex']) && pending['yandex'].length <= 20
      && pending['yandex'].every((id) => Number.isSafeInteger(id) && Number(id) > 0))
    && (remote['business_profile'] === undefined || Number.isSafeInteger(remote['business_profile']) && Number(remote['business_profile']) >= 0)
    && (pending['business_profile'] === undefined || Array.isArray(pending['business_profile'])
      && pending['business_profile'].length <= 20
      && pending['business_profile'].every((id) => Number.isSafeInteger(id) && Number(id) > 0))
    && ['search_console', 'analytics'].every((provider) => Array.isArray(pending[provider])
      && (pending[provider] as unknown[]).length <= 20
      && (pending[provider] as unknown[]).every((id) => Number.isSafeInteger(id) && Number(id) > 0))
    && typeof row['limitations'] === 'string';
}

const organizationClosureTurkish: Record<string, string> = {
  "Organization retention and closure status": "Kuruluş saklama ve kapatma durumu",
  "Organization": "Kuruluş",
  "retention and closure status": "saklama ve kapatma durumu",
  "Return to organization selection": "Kuruluş seçimine dön",
  "Checking current closure permissions and status.": "Güncel kapatma izinleri ve durum kontrol ediliyor.",
  "Current state:": "Güncel durum:",
  "Owner closure recorded": "Sahip kapatması kaydedildi",
  "Retention source": "Saklama kaynağı",
  "Active deletion stage": "Etkin silme aşaması",
  "Eligible to start": "Başlamaya uygun tarih",
  "Active-store deadline": "Aktif depolama son tarihi",
  "Completed on this system": "Bu sistemde tamamlanma tarihi",
  "not confirmed": "doğrulanmadı",
  "Review category": "İnceleme kategorisi",
  "none recorded": "kayıt yok",
  "Backup expiry policy ceiling:": "Yedek sona erme politikası üst sınırı:",
  "after active deletion. This is a policy bound, not proof that any hosted backup version is gone.": "aktif silme sonrasında. Bu bir politika sınırıdır; barındırılan herhangi bir yedek sürümün silindiğinin kanıtı değildir.",
  "No active deletion record exists. This is not proof that content has been deleted.": "Etkin silme kaydı yok. Bu, içeriğin silindiğinin kanıtı değildir.",
  "Provider subscription cancellation:": "Sağlayıcı abonelik iptali:",
  "no recorded error": "kayıtlı hata yok",
  "Billing is not confirmed canceled until provider reconciliation succeeds.": "Sağlayıcı mutabakatı başarıyla tamamlanana kadar faturalamanın iptali doğrulanmış sayılmaz.",
  "Current password before a read-only provider status check": "Salt okunur sağlayıcı durum kontrolünden önce güncel parola",
  "Check provider cancellation without sending another cancel request": "Başka iptal isteği göndermeden sağlayıcı iptalini kontrol et",
  "Remote source revocation still pending:": "Uzak kaynak erişimini kaldırma hâlâ beklemede:",
  "unavailable": "kullanılamıyor",
  "Review one pending provider grant": "Bekleyen bir sağlayıcı yetkisini incele",
  "Only a confirmed remote response clears the stored refresh credential. An unknown provider outcome must be reconciled; repeating a request cannot prove the first one failed.": "Saklanan yenileme kimlik bilgisi yalnızca doğrulanmış bir uzak yanıtla temizlenir. Bilinmeyen sağlayıcı sonucu mutabakatla çözülmelidir; bir isteği tekrarlamak ilkinin başarısız olduğunu kanıtlamaz.",
  "Current pending source grant": "Güncel bekleyen kaynak yetkisi",
  "Search Console grant": "Search Console yetkisi",
  "Analytics grant": "Analytics yetkisi",
  "Business Profile grant": "Business Profile yetkisi",
  "Current password": "Güncel parola",
  "Attempt the selected remote revocation": "Seçilen uzak erişimi kaldırmayı dene",
  "Permanently close organization access": "Kuruluş erişimini kalıcı olarak kapat",
  "Closing immediately disables member access, jobs, schedules, integrations and live report links. A provider subscription cancellation may need reconciliation; storage and database deletion is tracked for the accepted 30-day active-store window, with customer-bearing backups retained for a separate maximum rotation after active deletion. Already downloaded copies cannot be erased. Download and verify available exports before closing; after closure they are inaccessible.": "Kapatma; üye erişimini, işleri, zamanlamaları, entegrasyonları ve canlı rapor bağlantılarını hemen devre dışı bırakır. Sağlayıcı abonelik iptali mutabakat gerektirebilir; depolama ve veritabanı silme işlemleri kabul edilen 30 günlük aktif depolama aralığı için izlenir. Müşteri verisi içeren yedekler, aktif silmeden sonra ayrı bir azami dönüşüm süresi boyunca saklanır. İndirilmiş kopyalar silinemez. Kapatmadan önce mevcut dışa aktarımları indirin ve doğrulayın; kapatma sonrasında erişilemezler.",
  "I understand this action is irreversible and provider/backup outcomes require verification.": "Bu işlemin geri alınamaz olduğunu ve sağlayıcı/yedek sonuçlarının doğrulama gerektirdiğini anlıyorum.",
  "Confirm permanent organization closure": "Kuruluşun kalıcı olarak kapatılmasını onayla",
  "Self-service organization closure is release-gated. Owner export and retained-result access still follow current permissions.": "Kuruluşun kullanıcı tarafından kapatılması yayın onayına bağlıdır. Sahip dışa aktarımı ve saklanan sonuçlara erişim hâlâ güncel izinlere tabidir.",
  "Select a current authorized organization.": "Güncel ve yetkili bir kuruluş seçin.",
  "Closure or retention status unavailable for this organization.": "Bu kuruluşun kapatma veya saklama durumu kullanılamıyor.",
  "Closure was accepted, but status could not be refreshed. Inspect the status before any retry.": "Kapatma kabul edildi ancak durum yenilenemedi. Yeniden denemeden önce durumu inceleyin.",
  "Organization access closed. Inspect cleanup and provider status here; completed downloads cannot be erased.": "Kuruluş erişimi kapatıldı. Temizleme ve sağlayıcı durumunu burada inceleyin; tamamlanmış indirmeler silinemez.",
  "Closure outcome unavailable. Refresh the status before retrying; never assume a provider request failed.": "Kapatma sonucu kullanılamıyor. Yeniden denemeden önce durumu yenileyin; sağlayıcı isteğinin başarısız olduğunu asla varsaymayın.",
  "Provider cancellation observed. Inspect local billing and deletion records for remaining work.": "Sağlayıcı iptali gözlemlendi. Kalan işler için yerel faturalama ve silme kayıtlarını inceleyin.",
  "Provider cancellation is still unconfirmed. No second cancellation request was sent.": "Sağlayıcı iptali hâlâ doğrulanmadı. İkinci iptal isteği gönderilmedi.",
  "Provider reconciliation unavailable. No second cancellation request was sent; inspect status before retrying.": "Sağlayıcı mutabakatı kullanılamıyor. İkinci iptal isteği gönderilmedi; yeniden denemeden önce durumu inceleyin.",
  "Provider grant revocation confirmed. Check remaining closure status and sources.": "Sağlayıcı yetkisinin kaldırılması doğrulandı. Kalan kapatma durumunu ve kaynakları kontrol edin.",
  "Remote revocation remains unconfirmed; the stored encrypted token remains pending for review.": "Uzak erişimin kaldırılması hâlâ doğrulanmadı; saklanan şifreli belirteç inceleme için beklemede kalır.",
  "Remote revocation outcome unavailable. Review current status before retrying.": "Uzak erişimi kaldırma sonucu kullanılamıyor. Yeniden denemeden önce güncel durumu inceleyin.",
  "Unreviewed Turkish organization-closure interface draft in local development. Stored source/state values and other screens remain English; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe kuruluş kapatma arayüzü taslağı. Saklanan kaynak/durum değerleri ve diğer ekranlar İngilizce kalır; iki dilde onay bekleniyor."
};

@Component({
  selector: 'app-organization-closure-status',
  imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="closure-status-title">
      <h1 id="closure-status-title">{{ t("Organization") }} {{ organizationId }} {{ t("retention and closure status") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish organization-closure interface draft in local development. Stored source/state values and other screens remain English; bilingual approval is pending.") }}</p> }
      <p><a routerLink="/app">{{ t("Return to organization selection") }}</a></p>
      @if (loading()) { <p role="status">{{ t("Checking current closure permissions and status.") }}</p> }
      @if (error()) { <p role="alert" [attr.lang]="textLanguage(error())">{{ t(error()) }}</p> }
      @if (message()) { <p role="status" [attr.lang]="textLanguage(message())">{{ t(message()) }}</p> }
      @if (!loading() && !error() && status(); as record) {
        <p><strong>{{ t("Current state:") }}</strong>{{ ' ' }}<span lang="en">{{ record.state }}</span>.
          @if (record.closed_at) { <span>{{ t("Owner closure recorded") }} <span lang="en">{{ record.closed_at }}</span>.</span> }
        </p>
        @if (record.deletion; as deletion) {
          <dl><dt>{{ t("Retention source") }}</dt><dd lang="en">{{ deletion.source }}</dd>
            <dt>{{ t("Active deletion stage") }}</dt><dd lang="en">{{ deletion.state }}</dd>
            <dt>{{ t("Eligible to start") }}</dt><dd lang="en">{{ deletion.eligible_at }}</dd>
            <dt>{{ t("Active-store deadline") }}</dt><dd lang="en">{{ deletion.due_at }}</dd>
            <dt>{{ t("Completed on this system") }}</dt><dd>@if (deletion.completed_at) { <span lang="en">{{ deletion.completed_at }}</span> } @else { {{ t("not confirmed") }} }</dd>
            <dt>{{ t("Review category") }}</dt><dd>@if (deletion.error_category) { <span lang="en">{{ deletion.error_category }}</span> } @else { {{ t("none recorded") }} }</dd>
          </dl>
          @if (deletion.backup_latest_expiry_bound_at) {
            <p>{{ t("Backup expiry policy ceiling:") }} <span lang="en">{{ deletion.backup_latest_expiry_bound_at }}</span> {{ t("after active deletion. This is a policy bound, not proof that any hosted backup version is gone.") }}</p>
          }
        } @else { <p>{{ t("No active deletion record exists. This is not proof that content has been deleted.") }}</p> }
        @if (record.billing_cancellation; as cancellation) {
          <p>{{ t("Provider subscription cancellation:") }} <span lang="en">{{ cancellation.state }}</span> ·
            @if (cancellation.error_category) { <span lang="en">{{ cancellation.error_category }}</span> } @else { {{ t("no recorded error") }} }. {{ t("Billing is not confirmed canceled until provider reconciliation succeeds.") }}</p>
          @if (cancellation.state === 'unknown' || cancellation.state === 'sending') {
            <form (submit)="reconcileBilling($event)">
              <label for="billing-reconcile-password">{{ t("Current password before a read-only provider status check") }}</label>
              <input id="billing-reconcile-password" lang="" type="password" name="password" autocomplete="current-password" required />
              <button type="submit" [disabled]="busy()">{{ t("Check provider cancellation without sending another cancel request") }}</button>
            </form>
          }
        }
        <p>{{ t("Remote source revocation still pending:") }} Search Console {{ record.remote_revocation_pending.search_console }}, Analytics {{ record.remote_revocation_pending.analytics }}, Business Profile {{ record.remote_revocation_pending.business_profile ?? t('unavailable') }}, Yandex {{ record.remote_revocation_pending.yandex ?? t('unavailable') }}. <span lang="en">GitHub repositories {{ record.remote_revocation_pending.repository ?? 'unavailable' }}.</span></p>
        @if (record.pending_grants.search_console.length || record.pending_grants.analytics.length || record.pending_grants.business_profile?.length || record.pending_grants.yandex?.length || record.pending_grants.repository?.length) {
          <section aria-labelledby="remote-revoke-title">
            <h2 id="remote-revoke-title">{{ t("Review one pending provider grant") }}</h2>
            <p>{{ t("Only a confirmed remote response clears the stored refresh credential. An unknown provider outcome must be reconciled; repeating a request cannot prove the first one failed.") }}</p>
            <form (submit)="revokeGrant($event)">
              <label for="pending-grant">{{ t("Current pending source grant") }}</label>
              <select id="pending-grant" name="grant" required>
                @for (id of record.pending_grants.search_console; track id) {
                  <option [value]="'search_console:' + id">{{ t("Search Console grant") }} {{ id }}</option>
                }
                @for (id of record.pending_grants.analytics; track id) {
                  <option [value]="'analytics:' + id">{{ t("Analytics grant") }} {{ id }}</option>
                }
                @for (id of record.pending_grants.repository || []; track id) {
                  <option lang="en" [value]="'repository:' + id">GitHub repository grant {{ id }}</option>
                }
                @for (id of record.pending_grants.yandex || []; track id) {
                  <option lang="en" [value]="'yandex:' + id">Yandex grant {{ id }}</option>
                }
                @for (id of record.pending_grants.business_profile || []; track id) {
                  <option [value]="'business_profile:' + id">{{ t("Business Profile grant") }} {{ id }}</option>
                }
              </select>
              <p lang="en">Automatic GitHub disconnect deletes only the selected connection's access token. Refresh revocation stays unconfirmed. To finish cleanup, revoke the app in the authorizing GitHub account first, then record your completed action below. That manual GitHub action also stops this user's app connections in other projects; the report is not provider confirmation.</p>
              <label lang="en"><input name="repository_reported" type="checkbox"> For a selected GitHub grant only: I already completed remote revocation in GitHub Settings → Applications. Record my report instead of an API attempt.</label>
              <label for="grant-revoke-password">{{ t("Current password") }}</label>
              <input id="grant-revoke-password" lang="" type="password" name="password" autocomplete="current-password" required />
              <button type="submit" [disabled]="busy()">{{ t("Attempt the selected remote revocation") }}</button>
            </form>
          </section>
        }
        @if (record.repository_unknown_exchanges?.length) {
          <section lang="en" aria-labelledby="repository-unknown-closure-title">
            <h2 id="repository-unknown-closure-title">Resolve unknown GitHub consent before deletion</h2>
            <p>Unknown token issuance remains unresolved even after project access expires. Revoke the application's authorization in the authorizing GitHub account first.
              That GitHub action can stop this user's app connections in other projects. This records your completed action, not provider confirmation.</p>
            @for (consent of record.repository_unknown_exchanges || []; track consent.id) {
              @if (consent.can_report_revoked) {
                <form (submit)="reportRepositoryConsent($event, consent.id)">
                  <label><input name="confirmed" type="checkbox" required> I completed remote GitHub app-authorization revocation for consent {{ consent.id }}.</label>
                  <label [for]="'closure-repository-password-' + consent.id">Current password</label>
                  <input [id]="'closure-repository-password-' + consent.id" name="password" type="password" autocomplete="current-password" required>
                  <button type="submit" [disabled]="busy()">Record completed revocation for consent {{ consent.id }}</button>
                </form>
              } @else { <p>Consent {{ consent.id }} is still inside the ten-minute in-flight fence.</p> }
            }
            <p>At most20 unresolved consents are shown. Resolve and refresh to reach older records. This recovery requires current organization ownership and a closed or eligible deletion state.</p>
          </section>
        }
        <p lang="">{{ record.limitations }}</p>
        @if (record.close_action_available && record.state === 'open') {
          <section aria-labelledby="close-organization-title">
            <h2 id="close-organization-title">{{ t("Permanently close organization access") }}</h2>
            <p>{{ t("Closing immediately disables member access, jobs, schedules, integrations and live report links. A provider subscription cancellation may need reconciliation; storage and database deletion is tracked for the accepted 30-day active-store window, with customer-bearing backups retained for a separate maximum rotation after active deletion. Already downloaded copies cannot be erased. Download and verify available exports before closing; after closure they are inaccessible.") }}</p>
            <form (submit)="close($event)">
              <label for="closure-password">{{ t("Current password") }}</label>
              <input id="closure-password" lang="" type="password" name="password" autocomplete="current-password" required />
              <label><input type="checkbox" name="acknowledge" required /> {{ t("I understand this action is irreversible and provider/backup outcomes require verification.") }}</label>
              <button type="submit" class="danger-button" [disabled]="busy()">{{ t("Confirm permanent organization closure") }}</button>
            </form>
          </section>
        } @else if (record.state === 'open') {
          <p>{{ t("Self-service organization closure is release-gated. Owner export and retained-result access still follow current permissions.") }}</p>
        }
      }
    </section>
  `,
  styles: `
    dt { font-weight: 700; }
    dd { margin: 0 0 0.65rem; overflow-wrap: anywhere; }
  `,
})
export class OrganizationClosureStatus implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  textLanguage(text: string) { return Object.hasOwn(organizationClosureTurkish, text) ? this.uiLanguage() : 'en'; }
  t(text: string) { return this.textLanguage(text) === 'tr' ? organizationClosureTurkish[text] : text; }
  readonly loading = signal(true);
  readonly error = signal('');
  readonly status = signal<Closure | null>(null);
  readonly busy = signal(false);
  readonly message = signal('');
  organizationId = 0;
  private generation = 0;

  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi,
              private readonly destroyRef: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t('Organization retention and closure status')} — OrganicSEOOps`));
  }

  ngOnInit() {
    void this.loadProductLanguage();
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      this.organizationId = Number(params.get('organizationId'));
      this.generation++;
      this.status.set(null); this.error.set(''); this.loading.set(true); this.message.set(''); this.busy.set(false);
      if (Number.isSafeInteger(this.organizationId) && this.organizationId > 0) void this.load();
      else { this.loading.set(false); this.error.set("Select a current authorized organization."); }
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

  async load() {
    const generation = ++this.generation;
    this.loading.set(true); this.error.set(''); this.status.set(null);
    try {
      const response = await this.api.organizationClosureStatus(this.organizationId);
      if (generation !== this.generation) return;
      if (response.status !== 200 || !isClosure(response.body, this.organizationId)) throw new Error();
      this.status.set(response.body as unknown as Closure);
    } catch {
      if (generation === this.generation) this.error.set("Closure or retention status unavailable for this organization.");
    } finally { if (generation === this.generation) this.loading.set(false); }
  }

  async close(event: Event) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (this.busy() || !this.status()?.close_action_available || !form.reportValidity()) return;
    const data = new FormData(form);
    if (!data.has('acknowledge')) return;
    const generation = this.generation;
    this.busy.set(true); this.message.set('');
    let reloaded = false;
    try {
      const auth = await this.api.reauthenticate(String(data.get('password') || ''));
      if (generation !== this.generation) return;
      if (auth.status !== 200) throw new Error();
      const response = await this.api.organizationClose(this.organizationId);
      if (generation !== this.generation) return;
      if (response.status !== 202 || response.body['organization_id'] !== this.organizationId
          || typeof response.body['state'] !== 'string'
          || !['closed', 'closed_cleanup_review', 'closed_billing_review'].includes(response.body['state'])
          || response.body['status_path'] !== `/api/organizations/${this.organizationId}/closure-status/`
          || response.body['backup_expiry'] !== 'policy_only_unverified') throw new Error();
      form.reset();
      await this.load();
      reloaded = true;
      if (generation + 1 === this.generation) this.message.set(this.error()
        ? "Closure was accepted, but status could not be refreshed. Inspect the status before any retry."
        : "Organization access closed. Inspect cleanup and provider status here; completed downloads cannot be erased.");
    } catch {
      if (generation === this.generation) this.message.set("Closure outcome unavailable. Refresh the status before retrying; never assume a provider request failed.");
    } finally { if (generation + (reloaded ? 1 : 0) === this.generation) this.busy.set(false); }
  }

  async reconcileBilling(event: Event) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const state = this.status()?.billing_cancellation?.state;
    if (this.busy() || !form.reportValidity() || state !== 'unknown' && state !== 'sending') return;
    const generation = this.generation;
    this.busy.set(true); this.message.set('');
    let reloaded = false;
    try {
      const auth = await this.api.reauthenticate(String(new FormData(form).get('password') || ''));
      if (generation !== this.generation) return;
      if (auth.status !== 200) throw new Error();
      const checked = await this.api.organizationReconcileClosureBilling(this.organizationId);
      if (generation !== this.generation) return;
      if (checked.status !== 200 || checked.body['organization_id'] !== this.organizationId
          || typeof checked.body['state'] !== 'string' || !['unknown', 'confirmed', 'sending'].includes(checked.body['state'])
          || checked.body['status_path'] !== `/api/organizations/${this.organizationId}/closure-status/`) throw new Error();
      form.reset();
      await this.load();
      reloaded = true;
      if (generation + 1 === this.generation) this.message.set(checked.body['state'] === 'confirmed'
        ? "Provider cancellation observed. Inspect local billing and deletion records for remaining work."
        : "Provider cancellation is still unconfirmed. No second cancellation request was sent.");
    } catch {
      if (generation === this.generation) this.message.set("Provider reconciliation unavailable. No second cancellation request was sent; inspect status before retrying.");
    } finally { if (generation + (reloaded ? 1 : 0) === this.generation) this.busy.set(false); }
  }

  async reportRepositoryConsent(event: Event, consentId: number) {
    event.preventDefault();
    if (this.busy() || !this.status()?.repository_unknown_exchanges?.some((row) => row.id === consentId && row.can_report_revoked)) return;
    const form = event.target as HTMLFormElement; const data = new FormData(form);
    if (data.get('confirmed') !== 'on') return;
    const generation = this.generation; this.busy.set(true); this.message.set('');
    let reloaded = false;
    try {
      const auth = await this.api.reauthenticate(String(data.get('password') ?? ''));
      form.reset();
      if (generation !== this.generation) return;
      if (auth.status !== 200) throw new Error();
      const response = await this.api.organizationReportRepositoryConsentRevoked(this.organizationId, consentId);
      if (generation !== this.generation) return;
      if (response.status !== 200 || response.body['organization_id'] !== this.organizationId
          || response.body['state'] !== 'human_reported_not_provider_verified') throw new Error();
      await this.load(); reloaded = true;
      if (generation + 1 === this.generation) this.message.set('Your completed GitHub revocation was recorded as a human report, not provider verification.');
    } catch { if (generation === this.generation) this.message.set('Consent recovery unconfirmed. Refresh closure/deletion state and inspect the exact consent.'); }
    finally { if (generation + (reloaded ? 1 : 0) === this.generation) this.busy.set(false); }
  }

  async revokeGrant(event: Event) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (this.busy() || !this.status() || !form.reportValidity()) return;
    const formData = new FormData(form);
    const selected = String(formData.get('grant') || '');
    const [provider, value] = selected.split(':');
    const grantId = Number(value);
    if ((provider !== 'search_console' && provider !== 'analytics' && provider !== 'business_profile' && provider !== 'yandex' && provider !== 'repository')
        || !Number.isSafeInteger(grantId) || grantId < 1
        || !this.status()!.pending_grants[provider]?.includes(grantId)) return;
    const generation = this.generation;
    this.busy.set(true); this.message.set('');
    let reloaded = false;
    try {
      const auth = await this.api.reauthenticate(String(formData.get('password') || ''));
      if (generation !== this.generation) return;
      if (auth.status !== 200) throw new Error();
      const reported = provider === 'repository' && formData.get('repository_reported') === 'on';
      const result = await this.api.organizationRevokePendingGrant(this.organizationId, provider, grantId, reported);
      if (generation !== this.generation) return;
      if (result.status !== 200 || result.body['organization_id'] !== this.organizationId
          || result.body['provider'] !== provider
          || typeof result.body['state'] !== 'string' || !['revoked', 'revocation_pending'].includes(result.body['state'])
          || result.body['status_path'] !== `/api/organizations/${this.organizationId}/closure-status/`) throw new Error();
      form.reset();
      await this.load();
      reloaded = true;
      if (generation + 1 === this.generation) this.message.set(result.body['state'] === 'revoked'
        ? reported ? "Your completed GitHub revocation was recorded; provider confirmation remains unverified." : "Provider grant revocation confirmed. Check remaining closure status and sources."
        : "Remote revocation remains unconfirmed; the stored encrypted token remains pending for review.");
    } catch {
      if (generation === this.generation) this.message.set("Remote revocation outcome unavailable. Review current status before retrying.");
    } finally { if (generation + (reloaded ? 1 : 0) === this.generation) this.busy.set(false); }
  }
}
