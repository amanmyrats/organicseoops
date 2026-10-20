import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, effect, OnInit, signal, computed } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi } from '../account/account-api';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';

type Provider = { id: number; name: string; kind: 'openai' | 'openai_compatible' };
type Account = { id: number; provider_id: number; label: string; state: 'active' | 'revoked'; stored: boolean };

const organizationProviderTurkish: Record<string, string> = {
  "Organization AI credentials": "Kuruluş AI kimlik bilgileri",
  "Back to organization and project context": "Kuruluş ve proje bağlamına dön",
  "Organization AI provider credentials": "Kuruluşun AI sağlayıcı kimlik bilgileri",
  "Only organization owners and admins can configure a supported provider key. Your saved key will never be shown again. Model selection and supported capabilities are configured separately.": "Desteklenen sağlayıcı anahtarını yalnızca kuruluş sahipleri ve yöneticileri yapılandırabilir. Kaydedilen anahtarınız bir daha gösterilmez. Model seçimi ve desteklenen yetenekler ayrı olarak yapılandırılır.",
  "Loading provider accounts.": "Sağlayıcı hesapları yükleniyor.",
  "Provider credentials are unavailable for this organization or role.": "Bu kuruluş veya rol için sağlayıcı kimlik bilgileri kullanılamıyor.",
  "Refresh accounts": "Hesapları yenile",
  "Only the first 100 providers or accounts are shown.": "Yalnızca ilk 100 sağlayıcı veya hesap gösteriliyor.",
  "Add an organization-owned key": "Kuruluşa ait bir anahtar ekle",
  "Provider": "Sağlayıcı",
  "Account label": "Hesap etiketi",
  "Provider API key": "Sağlayıcı API anahtarı",
  "Save key": "Anahtarı kaydet",
  "No enabled AI providers are available yet.": "Henüz etkin AI sağlayıcısı yok.",
  "Replace an organization key": "Kuruluş anahtarını değiştir",
  "Account": "Hesap",
  "Replacement API key": "Yeni API anahtarı",
  "Replace key": "Anahtarı değiştir",
  "Disconnect": "Bağlantıyı kes",
  "Stop future use of this organization key?": "Bu kuruluş anahtarının gelecekteki kullanımını durdurmak istiyor musunuz?",
  "Confirm disconnect": "Bağlantıyı kesmeyi onayla",
  "Cancel": "Vazgeç",
  "Organization performance API key": "Kuruluş performans API anahtarı",
  "Use your own restricted PageSpeed/CrUX key for this organization's audited sites. A missing key may use available platform funding; revoking an organization key stops fallback until you replace it.": "Bu kuruluşun denetlenen siteleri için size ait kısıtlı PageSpeed/CrUX anahtarını kullanın. Anahtar yoksa mevcut platform finansmanı kullanılabilir; kuruluş anahtarını kaldırmak, değiştirene kadar alternatif platform kullanımını durdurur.",
  "Loading performance key status.": "Performans anahtarı durumu yükleniyor.",
  "Performance key settings are unavailable.": "Performans anahtarı ayarları kullanılamıyor.",
  "Organization key:": "Kuruluş anahtarı:",
  "Performance API key": "Performans API anahtarı",
  "Save organization key": "Kuruluş anahtarını kaydet",
  "Stop queued and future performance requests using this key?": "Bu anahtarı kullanan kuyruktaki ve gelecekteki performans isteklerini durdurmak istiyor musunuz?",
  "Confirm revoke": "Kaldırmayı onayla",
  "Revoke organization key": "Kuruluş anahtarını kaldır",
  "Unknown provider": "Bilinmeyen sağlayıcı",
  "Organization performance key saved.": "Kuruluş performans anahtarı kaydedildi.",
  "Performance key was not saved. Check your role and configuration.": "Performans anahtarı kaydedilmedi. Rolünüzü ve yapılandırmayı kontrol edin.",
  "Organization key revoked. Replace it before running another audit.": "Kuruluş anahtarı kaldırıldı. Başka bir denetim çalıştırmadan önce değiştirin.",
  "Revocation could not be confirmed. Refresh before trying again.": "Anahtarın kaldırılması doğrulanamadı. Yeniden denemeden önce yenileyin.",
  "Provider accounts are unavailable. Retry the load.": "Sağlayıcı hesapları kullanılamıyor. Yüklemeyi yeniden deneyin.",
  "Credential saved.": "Kimlik bilgisi kaydedildi.",
  "Choose an available account.": "Kullanılabilir bir hesap seçin.",
  "Credential replaced.": "Kimlik bilgisi değiştirildi.",
  "Key disconnected. Future provider jobs cannot use it.": "Anahtarın bağlantısı kesildi. Gelecekteki sağlayıcı işleri bunu kullanamaz.",
  "Disconnect outcome is unknown. Refresh before retrying.": "Bağlantıyı kesme sonucu bilinmiyor. Yeniden denemeden önce yenileyin.",
  "Credential was not saved. Check your role and configuration.": "Kimlik bilgisi kaydedilmedi. Rolünüzü ve yapılandırmayı kontrol edin.",
  "Unreviewed Turkish organization-provider-key interface draft in local development. Stored provider/status values and other screens remain English; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe kuruluş sağlayıcı anahtarı arayüzü taslağı. Saklanan sağlayıcı/durum değerleri ve diğer ekranlar İngilizce kalır; iki dilde onay bekleniyor."
};

@Component({
  selector: 'app-organization-provider-accounts',
  imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="org-credentials-title">
      <p><a routerLink="/app">{{ t("Back to organization and project context") }}</a></p>
      <h1 id="org-credentials-title">{{ t("Organization AI provider credentials") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish organization-provider-key interface draft in local development. Stored provider/status values and other screens remain English; bilingual approval is pending.") }}</p> }
      <p>{{ t("Only organization owners and admins can configure a supported provider key. Your saved key will never be shown again. Model selection and supported capabilities are configured separately.") }}</p>
      @if (message()) { <p role="status" [attr.lang]="textLanguage(message())">{{ t(message()) }}</p> }
      @if (error()) { <p role="alert" [attr.lang]="textLanguage(error())">{{ t(error()) }}</p> }
      @if (loading()) { <p role="status">{{ t("Loading provider accounts.") }}</p> }
      @if (!loading() && denied()) { <p>{{ t("Provider credentials are unavailable for this organization or role.") }}</p> }
      @if (!loading() && !denied()) {
        <button type="button" (click)="load()" [disabled]="busy()">{{ t("Refresh accounts") }}</button>
        @if (hasMore()) { <p>{{ t("Only the first 100 providers or accounts are shown.") }}</p> }
        @if (providers().length) {
          <form (submit)="create($event)">
            <h2>{{ t("Add an organization-owned key") }}</h2>
            <label for="org-provider-id">{{ t("Provider") }}</label>
            <select lang="" id="org-provider-id" name="provider_id" required>
              @for (provider of providers(); track provider.id) {
                <option [value]="provider.id">{{ provider.name }} ({{ provider.kind }})</option>
              }
            </select>
            <label for="org-provider-label">{{ t("Account label") }}</label>
            <input lang="" id="org-provider-label" name="label" required maxlength="80" />
            <label for="org-provider-key">{{ t("Provider API key") }}</label>
            <input id="org-provider-key" name="secret" lang="" type="password" autocomplete="new-password" required />
            <button type="submit" [disabled]="busy()">{{ t("Save key") }}</button>
          </form>
        } @else { <p>{{ t("No enabled AI providers are available yet.") }}</p> }
        @if (activeAccounts().length) {
          <form (submit)="rotate($event)">
            <h2>{{ t("Replace an organization key") }}</h2>
            <label for="org-rotate-account">{{ t("Account") }}</label>
            <select lang="" id="org-rotate-account" name="account_id" required>
              @for (account of activeAccounts(); track account.id) {
                <option [value]="account.id">{{ account.label }} — {{ providerName(account.provider_id) }}</option>
              }
            </select>
            <label for="org-replacement-key">{{ t("Replacement API key") }}</label>
            <input id="org-replacement-key" name="secret" lang="" type="password" autocomplete="new-password" required />
            <button type="submit" [disabled]="busy()">{{ t("Replace key") }}</button>
          </form>
          <h2>{{ t("Disconnect") }}</h2>
          @for (account of activeAccounts(); track account.id) {
            <div>
              <span lang="">{{ account.label }} — {{ providerName(account.provider_id) }}</span>
              @if (confirmRevoke() === account.id) {
                <p role="alert">{{ t("Stop future use of this organization key?") }}</p>
                <button type="button" (click)="revoke(account)" [disabled]="busy()">{{ t("Confirm disconnect") }}</button>
                <button type="button" (click)="confirmRevoke.set(null)" [disabled]="busy()">{{ t("Cancel") }}</button>
              } @else {
                <button type="button" (click)="confirmRevoke.set(account.id)" [disabled]="busy()">{{ t("Disconnect") }} <span lang="">{{ account.label }}</span></button>
              }
            </div>
          }
        }
        <section aria-labelledby="org-performance-title">
          <h2 id="org-performance-title">{{ t("Organization performance API key") }}</h2>
          <p>{{ t("Use your own restricted PageSpeed/CrUX key for this organization's audited sites. A missing key may use available platform funding; revoking an organization key stops fallback until you replace it.") }}</p>
          @if (performanceState() === 'loading') { <p role="status">{{ t("Loading performance key status.") }}</p> }
          @else if (performanceState() === 'denied') { <p>{{ t("Performance key settings are unavailable.") }}</p> }
          @else {
            <p role="status">{{ t("Organization key:") }} <span lang="en">{{ performanceState() }}</span></p>
            <form (submit)="savePerformance($event)">
              <label for="organization-performance-key">{{ t("Performance API key") }}</label>
              <input id="organization-performance-key" name="api_key" lang="" type="password" autocomplete="new-password" maxlength="200" required />
              <button type="submit" [disabled]="busy()">{{ t("Save organization key") }}</button>
            </form>
            @if (performanceState() === 'active') {
              @if (confirmPerformanceRevoke()) {
                <p role="alert">{{ t("Stop queued and future performance requests using this key?") }}</p>
                <button type="button" (click)="revokePerformance()" [disabled]="busy()">{{ t("Confirm revoke") }}</button>
                <button type="button" (click)="confirmPerformanceRevoke.set(false)" [disabled]="busy()">{{ t("Cancel") }}</button>
              } @else {
                <button type="button" (click)="confirmPerformanceRevoke.set(true)" [disabled]="busy()">{{ t("Revoke organization key") }}</button>
              }
            }
          }
        </section>
      }
    </section>
  `,
})
export class OrganizationProviderAccounts implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  textLanguage(text: string) { return Object.hasOwn(organizationProviderTurkish, text) ? this.uiLanguage() : 'en'; }
  t(text: string) { return this.textLanguage(text) === 'tr' ? organizationProviderTurkish[text] : text; }
  readonly organizationId = signal(0);
  readonly providers = signal<Provider[]>([]);
  readonly accounts = signal<Account[]>([]);
  readonly loading = signal(true);
  readonly denied = signal(false);
  readonly busy = signal(false);
  readonly hasMore = signal(false);
  readonly message = signal('');
  readonly error = signal('');
  readonly confirmRevoke = signal<number | null>(null);
  readonly performanceState = signal<'loading' | 'denied' | 'unconfigured' | 'active' | 'revoked'>('loading');
  readonly confirmPerformanceRevoke = signal(false);
  private requestId = 0;
  private performanceRequestId = 0;

  constructor(private readonly api: AccountApi, private readonly route: ActivatedRoute,
              private readonly destroyRef: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t('Organization AI credentials')} — OrganicSEOOps`));
  }

  ngOnInit() {
    void this.loadProductLanguage();
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const id = Number(params.get('organizationId'));
      this.organizationId.set(Number.isSafeInteger(id) && id > 0 ? id : 0);
      this.providers.set([]);
      this.accounts.set([]);
      this.confirmRevoke.set(null);
      this.performanceState.set('loading');
      this.confirmPerformanceRevoke.set(false);
      this.error.set('');
      this.message.set('');
      void this.load();
      void this.loadPerformance();
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

  activeAccounts() { return this.accounts().filter((row) => row.state === 'active'); }
  providerName(id: number) { return this.providers().find((row) => row.id === id)?.name || "Unknown provider"; }

  async loadPerformance() {
    const org = this.organizationId();
    const request = ++this.performanceRequestId;
    if (!org) { this.performanceState.set('denied'); return; }
    try {
      const result = await this.api.organizationPerformanceKey(org);
      if (request !== this.performanceRequestId || org !== this.organizationId()) return;
      const state = result.body['state'];
      this.performanceState.set(result.status === 200 && typeof state === 'string' && ['unconfigured', 'active', 'revoked'].includes(state)
        ? state as 'unconfigured' | 'active' | 'revoked' : 'denied');
    } catch {
      if (request === this.performanceRequestId) this.performanceState.set('denied');
    }
  }

  async savePerformance(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const org = this.organizationId();
    if (!org || !form.reportValidity() || this.busy()) return;
    const key = String(new FormData(form).get('api_key'));
    this.busy.set(true);
    this.error.set('');
    try {
      const response = await this.api.setOrganizationPerformanceKey(org, key);
      if (org !== this.organizationId()) return;
      if (response.status !== 200) throw new Error();
      form.reset();
      this.message.set("Organization performance key saved.");
      await this.loadPerformance();
    } catch {
      if (org === this.organizationId()) this.error.set("Performance key was not saved. Check your role and configuration.");
    } finally {
      const field = form.elements.namedItem('api_key') as HTMLInputElement | null;
      if (field) field.value = '';
      this.busy.set(false);
    }
  }

  async revokePerformance() {
    const org = this.organizationId();
    if (!org || this.busy() || !this.confirmPerformanceRevoke()) return;
    this.busy.set(true);
    this.error.set('');
    try {
      const response = await this.api.revokeOrganizationPerformanceKey(org);
      if (org !== this.organizationId()) return;
      if (response.status !== 200) throw new Error();
      this.confirmPerformanceRevoke.set(false);
      this.message.set("Organization key revoked. Replace it before running another audit.");
      await this.loadPerformance();
    } catch {
      if (org === this.organizationId()) this.error.set("Revocation could not be confirmed. Refresh before trying again.");
    } finally { this.busy.set(false); }
  }

  async load() {
    const organizationId = this.organizationId();
    const request = ++this.requestId;
    if (!organizationId) { this.denied.set(true); this.loading.set(false); return; }
    this.loading.set(true);
    this.denied.set(true);
    this.providers.set([]);
    this.accounts.set([]);
    try {
      const result = await this.api.organizationProviderAccounts(organizationId);
      if (request !== this.requestId || organizationId !== this.organizationId()) return;
      if ([401, 403, 404].includes(result.status)) {
        this.denied.set(true);
        this.providers.set([]);
        this.accounts.set([]);
      } else if (result.status === 200 && Array.isArray(result.body['providers'])
        && result.body['providers'].every(isProvider) && Array.isArray(result.body['accounts'])
        && result.body['accounts'].every(isAccount) && typeof result.body['has_more'] === 'boolean') {
        this.denied.set(false);
        this.providers.set(result.body['providers'] as Provider[]);
        this.accounts.set(result.body['accounts'] as Account[]);
        this.hasMore.set(result.body['has_more']);
        this.error.set('');
      } else this.error.set("Provider accounts are unavailable. Retry the load.");
    } catch {
      if (request === this.requestId) this.error.set("Provider accounts are unavailable. Retry the load.");
    } finally {
      if (request === this.requestId) this.loading.set(false);
    }
  }

  async create(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || this.busy()) return;
    const data = new FormData(form);
    const secret = String(data.get('secret'));
    const org = this.organizationId();
    await this.save(form, org, () => this.api.addOrganizationProviderAccount(
      org, Number(data.get('provider_id')), String(data.get('label')), secret), "Credential saved.");
  }

  async rotate(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || this.busy()) return;
    const data = new FormData(form);
    const account = this.activeAccounts().find((row) => row.id === Number(data.get('account_id')));
    if (!account) { this.error.set("Choose an available account."); return; }
    const org = this.organizationId();
    const secret = String(data.get('secret'));
    await this.save(form, org, () => this.api.setOrganizationProviderCredential(org, account.id, secret),
      "Credential replaced.");
  }

  async revoke(account: Account) {
    const org = this.organizationId();
    if (!org || this.busy() || this.confirmRevoke() !== account.id) return;
    this.busy.set(true);
    this.error.set('');
    try {
      const result = await this.api.revokeOrganizationProviderCredential(org, account.id);
      if (org !== this.organizationId()) return;
      if (result.status !== 200) throw new Error();
      this.confirmRevoke.set(null);
      this.message.set("Key disconnected. Future provider jobs cannot use it.");
      await this.load();
    } catch { if (org === this.organizationId()) this.error.set("Disconnect outcome is unknown. Refresh before retrying."); }
    finally { this.busy.set(false); }
  }

  private async save(form: HTMLFormElement, org: number, action: () => ReturnType<AccountApi['organizationProviderAccounts']>,
                     success: string) {
    if (!org) return;
    this.busy.set(true);
    this.error.set('');
    try {
      const result = await action();
      if (org !== this.organizationId()) return;
      if (result.status !== 200 && result.status !== 201) throw new Error();
      form.reset();
      this.message.set(success);
      await this.load();
    } catch {
      if (org === this.organizationId()) this.error.set("Credential was not saved. Check your role and configuration.");
    } finally {
      const field = form.elements.namedItem('secret') as HTMLInputElement | null;
      if (field) field.value = '';
      this.busy.set(false);
    }
  }
}

function isProvider(value: unknown): value is Provider {
  if (!value || typeof value !== 'object') return false;
  const row = value as Record<string, unknown>;
  return Number.isSafeInteger(row['id']) && Number(row['id']) > 0 && typeof row['name'] === 'string'
    && typeof row['kind'] === 'string' && ['openai', 'openai_compatible'].includes(row['kind']);
}

function isAccount(value: unknown): value is Account {
  if (!value || typeof value !== 'object') return false;
  const row = value as Record<string, unknown>;
  return Number.isSafeInteger(row['id']) && Number(row['id']) > 0
    && Number.isSafeInteger(row['provider_id']) && Number(row['provider_id']) > 0
    && typeof row['label'] === 'string' && typeof row['state'] === 'string' && ['active', 'revoked'].includes(row['state'])
    && typeof row['stored'] === 'boolean';
}
