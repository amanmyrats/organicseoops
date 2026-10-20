import { Title } from '@angular/platform-browser';
import { DOCUMENT } from '@angular/common';
import { Component, computed, DestroyRef, effect, ElementRef, inject, Inject, OnInit, signal, ViewChild } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';
import { AccountApi } from './account-api';

const loginTurkish: Record<string, string> = {
  "Account access": "Hesap erişimi",
  "Sign in": "Oturum aç",
  "Unreviewed Turkish sign-in interface draft in local development. Bilingual approval is pending; unavailable preference reads fall back to English.": "Yerel geliştirmede incelenmemiş Türkçe oturum açma arayüzü taslağı. İki dilli onay bekleniyor; tercih okunamıyorsa İngilizceye dönülür.",
  "Use your verified email address to continue to the workspace.": "Çalışma alanına devam etmek için doğrulanmış e-posta adresinizi kullanın.",
  "Your password was changed and all sessions were signed out. Sign in again.": "Parolanız değiştirildi ve tüm oturumlar kapatıldı. Yeniden oturum açın.",
  "Your staff account requires a code from your authenticator app or an unused recovery code.": "Personel hesabınız için kimlik doğrulama uygulamanızdan bir kod veya kullanılmamış kurtarma kodu gerekir.",
  "Authentication code": "Kimlik doğrulama kodu",
  "Checking code…": "Kod kontrol ediliyor…",
  "Continue": "Devam et",
  "Use another account": "Başka bir hesap kullan",
  "Email address": "E-posta adresi",
  "Password": "Parola",
  "Show password": "Parolayı göster",
  "Signing in…": "Oturum açılıyor…",
  "Forgot your password?": "Parolanızı mı unuttunuz?",
  "New to OrganicSEOOps?": "OrganicSEOOps kullanmaya yeni mi başlıyorsunuz?",
  "Create an account": "Hesap oluştur",
  "Sign-in failed. Check your details and try again.": "Oturum açılamadı. Bilgilerinizi kontrol edip tekrar deneyin.",
  "Sign-in is temporarily unavailable. Try again.": "Oturum açma geçici olarak kullanılamıyor. Tekrar deneyin.",
  "The authentication code was not accepted. Check it and try again.": "Kimlik doğrulama kodu kabul edilmedi. Kontrol edip tekrar deneyin.",
  "Code verification is temporarily unavailable. Try again.": "Kod doğrulama geçici olarak kullanılamıyor. Tekrar deneyin."
};

@Component({
  selector: 'app-login',
  imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="account-card" aria-labelledby="login-title">
      <p class="eyebrow">{{ t("Account access") }}</p>
      <h1 id="login-title">{{ t("Sign in") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish sign-in interface draft in local development. Bilingual approval is pending; unavailable preference reads fall back to English.") }}</p> }
      <p>{{ t("Use your verified email address to continue to the workspace.") }}</p>

      @if (passwordChanged) {
        <div class="form-status" role="status">{{ t("Your password was changed and all sessions were signed out. Sign in again.") }}</div>
      }

      @if (error()) {
        <div #errorSummary class="form-status error" role="alert" tabindex="-1">{{ t(error()) }}</div>
      }

      @if (mfaPending()) {
        <form (submit)="submitMfa($event)">
          <p>{{ t("Your staff account requires a code from your authenticator app or an unused recovery code.") }}</p>
          <label for="mfa-code">{{ t("Authentication code") }}</label>
          <input id="mfa-code" name="code" type="text" inputmode="numeric" autocomplete="one-time-code" required autofocus />
          <button type="submit" [disabled]="submitting()">{{ t(submitting() ? 'Checking code…' : 'Continue') }}</button>
        </form>
        <button type="button" class="secondary-button" (click)="mfaPending.set(false)" [disabled]="submitting()">{{ t("Use another account") }}</button>
      } @else {
        <form (submit)="submit($event)">
          <label for="email">{{ t("Email address") }}</label>
          <input id="email" name="email" type="email" autocomplete="email" required />

          <label for="password">{{ t("Password") }}</label>
          <input id="password" name="password" [type]="showPassword() ? 'text' : 'password'" autocomplete="current-password" required />

          <label class="check-row">
            <input type="checkbox" (change)="showPassword.set(!showPassword())" />
            {{ t("Show password") }}
          </label>

          <button type="submit" [disabled]="submitting()">{{ t(submitting() ? 'Signing in…' : 'Sign in') }}</button>
        </form>

        <p><a routerLink="/account/forgot-password">{{ t("Forgot your password?") }}</a></p>
        <p class="account-alternate">{{ t("New to OrganicSEOOps?") }} <a routerLink="/account/register">{{ t("Create an account") }}</a>.</p>
      }
    </section>
  `,
})
export class Login implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  private readonly destroyRef = inject(DestroyRef);
  t(text: string) { return this.uiLanguage() === 'tr' ? loginTurkish[text] ?? text : text; }
  @ViewChild('errorSummary') private errorSummary?: ElementRef<HTMLElement>;
  readonly error = signal('');
  readonly showPassword = signal(false);
  readonly submitting = signal(false);
  readonly mfaPending = signal(false);

  readonly passwordChanged: boolean;
  private readonly returnUrl: string;

  constructor(
    private readonly api: AccountApi,
    private readonly router: Router,
    route: ActivatedRoute,
    @Inject(DOCUMENT) private readonly document: Document,
    title: Title,
  ) {
    effect(() => title.setTitle(`${this.t('Sign in')} — OrganicSEOOps`));
    this.passwordChanged = route.snapshot.queryParamMap.get('changed') === 'password';
    const next = route.snapshot.queryParamMap.get('next') || '';
    this.returnUrl = next.startsWith('/admin/') ? next : '';
  }

  ngOnInit() { void this.loadProductLanguage(); }
  private async loadProductLanguage() {
    try {
      const result = await this.api.productLanguage();
      if (!this.destroyRef.destroyed && result.status === 200 && isProductLanguageResult(result.body)) {
        this.productLanguage.set(result.body['language']);
      }
    } catch { /* Keep English when the private preference is unavailable. */ }
  }

  async submit(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || this.submitting()) return;
    const fields = new FormData(form);
    this.error.set('');
    this.submitting.set(true);
    try {
      const result = await this.api.login(String(fields.get('email')), String(fields.get('password')));
      if (result.status === 200) {
        await this.completeLogin();
      } else if (this.api.hasPendingMfa(result)) {
        this.mfaPending.set(true);
      } else if (this.api.hasPendingVerification(result)) {
        await this.router.navigate(['/account/verify']);
      } else {
        this.showError('Sign-in failed. Check your details and try again.');
      }
    } catch {
      this.showError('Sign-in is temporarily unavailable. Try again.');
    } finally {
      this.submitting.set(false);
    }
  }

  async submitMfa(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || this.submitting()) return;
    this.error.set('');
    this.submitting.set(true);
    try {
      const result = await this.api.authenticateMfa(String(new FormData(form).get('code')));
      if (result.status === 200) {
        await this.completeLogin();
      } else {
        this.showError('The authentication code was not accepted. Check it and try again.');
      }
    } catch {
      this.showError('Code verification is temporarily unavailable. Try again.');
    } finally {
      this.submitting.set(false);
    }
  }

  private showError(message: string) {
    this.error.set(message);
    setTimeout(() => this.errorSummary?.nativeElement.focus());
  }

  private async completeLogin() {
    if (this.returnUrl && this.document.defaultView) {
      this.document.defaultView.location.assign(this.returnUrl);
      return;
    }
    await this.router.navigateByUrl('/app');
  }
}
