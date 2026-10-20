import { Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';
import { AccountApi } from './account-api';

const youtubeKeyTurkish: Record<string, string> = {
  "Dedicated YouTube public-search key": "Özel YouTube herkese açık arama anahtarı",
  "Unreviewed Turkish staff YouTube-key interface draft in local development. Stored key states and API-project IDs remain English; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe personel YouTube anahtarı arayüzü taslağı. Kayıtlı anahtar durumları ve API projesi kimlikleri İngilizce kalır; iki dilli onay bekleniyor.",
  "Current staff MFA is required, including in development. Use this API Client's one Google API project; project identity cannot change after the first save. No customer BYOK or AI/performance/OAuth fallback.": "Geliştirme dahil güncel personel MFA doğrulaması gerekir. Bu API istemcisinin tek Google API projesini kullanın; proje kimliği ilk kayıttan sonra değiştirilemez. Müşteriye ait anahtar veya yapay zekâ/performans/OAuth yedek seçeneği yoktur.",
  "The daily ceiling is shared by all tenants and resets at Pacific midnight. Rotation/revocation never resets request usage. At most one request runs at a time; failures consume the conservative request allowance. Actual quota, provider access and policy/legal review remain unverified.": "Günlük üst sınır tüm kiracılar tarafından paylaşılır ve Pasifik saatine göre gece yarısında sıfırlanır. Anahtar yenileme/iptal istek kullanımını asla sıfırlamaz. Aynı anda en fazla bir istek çalışır; başarısızlıklar ihtiyatlı istek hakkını tüketir. Gerçek kota, sağlayıcı erişimi ve politika/hukuk incelemesi doğrulanmamıştır.",
  "Loading dedicated YouTube configuration.": "Özel YouTube yapılandırması yükleniyor.",
  "YouTube settings unavailable. Check staff permissions and current MFA.": "YouTube ayarları kullanılamıyor. Personel izinlerini ve güncel MFA doğrulamasını kontrol edin.",
  "YouTube key:": "YouTube anahtarı:",
  "ceiling": "üst sınır",
  "not configured": "yapılandırılmamış",
  "requests/day.": "istek/gün.",
  "This API Client's Google API project ID": "Bu API istemcisinin Google API projesi kimliği",
  "Dedicated replacement YouTube API key (write-only)": "Özel yedek YouTube API anahtarı (yalnızca yazılır)",
  "Conservative client-wide daily Search Queries ceiling (1–100)": "İstemci genelinde ihtiyatlı günlük arama sorgusu üst sınırı (1–100)",
  "Save dedicated YouTube key": "Özel YouTube anahtarını kaydedin",
  "Remove the saved key and block future YouTube searches?": "Kayıtlı anahtar kaldırılsın ve gelecekteki YouTube aramaları engellensin mi?",
  "Confirm YouTube revoke": "YouTube anahtarı iptalini onaylayın",
  "Cancel": "İptal",
  "Revoke YouTube key": "YouTube anahtarını iptal edin",
  "Refresh YouTube settings": "YouTube ayarlarını yenileyin",
  "Dedicated YouTube key saved. Provider readiness remains unverified.": "Özel YouTube anahtarı kaydedildi. Sağlayıcının hazır olduğu doğrulanmamıştır.",
  "YouTube key was not confirmed. Check current MFA, original API project and encryption.": "YouTube anahtarı doğrulanamadı. Güncel MFA doğrulamasını, özgün API projesini ve şifrelemeyi kontrol edin.",
  "YouTube key removed. Daily usage and API project identity retained.": "YouTube anahtarı kaldırıldı. Günlük kullanım ve API projesi kimliği korundu.",
  "YouTube revocation was not confirmed. Refresh current staff status.": "YouTube anahtarı iptali doğrulanamadı. Güncel personel durumunu yenileyin.",
};

@Component({
  selector: 'app-youtube-settings',
  template: `
    <section [attr.lang]="uiLanguage()" aria-labelledby="youtube-settings-title">
      <h2 id="youtube-settings-title">{{ t("Dedicated YouTube public-search key") }}</h2>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish staff YouTube-key interface draft in local development. Stored key states and API-project IDs remain English; bilingual approval is pending.") }}</p> }
      <p>{{ t("Current staff MFA is required, including in development. Use this API Client's one Google API project; project identity cannot change after the first save. No customer BYOK or AI/performance/OAuth fallback.") }}</p>
      <p>{{ t("The daily ceiling is shared by all tenants and resets at Pacific midnight. Rotation/revocation never resets request usage. At most one request runs at a time; failures consume the conservative request allowance. Actual quota, provider access and policy/legal review remain unverified.") }}</p>
      @if (error()) { <p role="alert">{{ t(error()) }}</p> }
      @if (message()) { <p role="status">{{ t(message()) }}</p> }
      @if (state() === 'loading') { <p role="status">{{ t("Loading dedicated YouTube configuration.") }}</p> }
      @else if (state() === 'denied') { <p>{{ t("YouTube settings unavailable. Check staff permissions and current MFA.") }}</p> }
      @else {
        <p role="status">{{ t("YouTube key:") }} <span lang="en">{{ state() }}</span> · {{ t("ceiling") }} {{ limit() ?? t('not configured') }} {{ t("requests/day.") }}</p>
        <form (submit)="save($event)">
          <label for="youtube-api-project">{{ t("This API Client's Google API project ID") }}</label>
          <input lang="en" id="youtube-api-project" name="api_project" required maxlength="30" pattern="[a-z][a-z0-9-]{4,28}[a-z0-9]" [value]="project()" [readOnly]="!!project()" />
          <label for="youtube-api-key">{{ t("Dedicated replacement YouTube API key (write-only)") }}</label>
          <input id="youtube-api-key" name="api_key" type="password" autocomplete="new-password" required maxlength="200" />
          <label for="youtube-daily-limit">{{ t("Conservative client-wide daily Search Queries ceiling (1–100)") }}</label>
          <input id="youtube-daily-limit" name="daily_limit" type="number" min="1" max="100" step="1" required [value]="limit()" />
          <button type="submit" [disabled]="busy()">{{ t("Save dedicated YouTube key") }}</button>
        </form>
        @if (state() === 'active') {
          @if (confirmRevoke()) {
            <p role="alert">{{ t("Remove the saved key and block future YouTube searches?") }}</p>
            <button type="button" (click)="revoke()" [disabled]="busy()">{{ t("Confirm YouTube revoke") }}</button>
            <button type="button" (click)="confirmRevoke.set(false)" [disabled]="busy()">{{ t("Cancel") }}</button>
          } @else { <button type="button" (click)="confirmRevoke.set(true)" [disabled]="busy()">{{ t("Revoke YouTube key") }}</button> }
        }
      }
      <button type="button" (click)="load()" [disabled]="busy()">{{ t("Refresh YouTube settings") }}</button>
    </section>`,
})
export class YouTubeSettings implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  private readonly destroyRef = inject(DestroyRef);
  t(text: string) { return this.uiLanguage() === 'tr' ? youtubeKeyTurkish[text] ?? text : text; }
  private loadRequest = 0;
  readonly state = signal('loading'); readonly project = signal(''); readonly limit = signal<number | null>(null);
  readonly busy = signal(false); readonly error = signal(''); readonly message = signal(''); readonly confirmRevoke = signal(false);
  constructor(private readonly api: AccountApi) {}
  ngOnInit() { void this.loadProductLanguage(); void this.load(); }
  private async loadProductLanguage() {
    try {
      const result = await this.api.productLanguage();
      if (!this.destroyRef.destroyed && result.status === 200 && isProductLanguageResult(result.body)) {
        this.productLanguage.set(result.body['language']);
      }
    } catch { /* Keep English when the private preference is unavailable. */ }
  }
  async load() {
    const request = ++this.loadRequest;
    this.state.set('loading'); this.project.set(''); this.limit.set(null);
    try {
      const response = await this.api.platformYouTubeKey();
      if (request !== this.loadRequest || this.destroyRef.destroyed) return;
      const data = response.body;
      if (response.status !== 200 || typeof data['state'] !== 'string' || !['active', 'revoked', 'unconfigured'].includes(data['state'])
        || typeof data['api_project'] !== 'string' || !(data['daily_limit'] === null ||
          Number.isInteger(data['daily_limit']) && Number(data['daily_limit']) >= 1 && Number(data['daily_limit']) <= 100)) throw new Error();
      this.state.set(data['state']); this.project.set(data['api_project']); this.limit.set(data['daily_limit'] as number | null);
    } catch { if (request === this.loadRequest && !this.destroyRef.destroyed) this.state.set('denied'); }
  }
  async save(event: SubmitEvent) {
    event.preventDefault(); const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || this.busy()) return;
    const fields = new FormData(form); this.busy.set(true); this.error.set('');
    try {
      const response = await this.api.platformYouTubeKey('POST', { api_project: String(fields.get('api_project')),
        api_key: String(fields.get('api_key')), daily_limit: Number(fields.get('daily_limit')) });
      if (response.status !== 200 || response.body['configured'] !== true) throw new Error();
      this.message.set('Dedicated YouTube key saved. Provider readiness remains unverified.'); await this.load();
    } catch { this.error.set('YouTube key was not confirmed. Check current MFA, original API project and encryption.'); }
    finally { (form.elements.namedItem('api_key') as HTMLInputElement).value = ''; this.busy.set(false); }
  }
  async revoke() {
    if (!this.confirmRevoke() || this.busy()) return;
    this.busy.set(true); this.error.set('');
    try {
      const response = await this.api.platformYouTubeKey('DELETE');
      if (response.status !== 200) throw new Error();
      this.confirmRevoke.set(false); this.message.set('YouTube key removed. Daily usage and API project identity retained.'); await this.load();
    } catch { this.error.set('YouTube revocation was not confirmed. Refresh current staff status.'); }
    finally { this.busy.set(false); }
  }
}
