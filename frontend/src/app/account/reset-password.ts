import { Title } from '@angular/platform-browser';
import { Location } from '@angular/common';
import { Component, computed, DestroyRef, effect, ElementRef, inject, OnInit, signal, ViewChild } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';
import { AccountApi } from './account-api';

type ResetState = 'loading' | 'ready' | 'complete' | 'invalid';

const resetTurkish: Record<string, string> = {
  "Choose new password": "Yeni bir parola seçin",
  "Account recovery": "Hesap kurtarma",
  "Unreviewed Turkish password-reset interface draft in local development. Bilingual approval is pending; unavailable preference reads fall back to English.": "Yerel geliştirmede incelenmemiş Türkçe parola sıfırlama arayüzü taslağı. İki dilli onay bekleniyor; tercih okunamıyorsa İngilizceye dönülür.",
  "Checking your reset link.": "Sıfırlama bağlantınız kontrol ediliyor.",
  "Choose a new password. Completing this reset signs out every existing session.": "Yeni bir parola seçin. Bu sıfırlamayı tamamlamak mevcut tüm oturumları kapatır.",
  "New password": "Yeni parola",
  "Use at least 12 characters. Avoid common, entirely numeric, or personally similar passwords.": "En az 12 karakter kullanın. Yaygın, tamamen sayısal veya kişisel bilgilerinize benzeyen parolalardan kaçının.",
  "Confirm new password": "Yeni parolayı doğrulayın",
  "The password confirmation does not match.": "Parola doğrulaması eşleşmiyor.",
  "Resetting…": "Sıfırlanıyor…",
  "Reset password": "Parolayı sıfırla",
  "Your password has been reset and existing sessions have been signed out.": "Parolanız sıfırlandı ve mevcut oturumlar kapatıldı.",
  "Sign in with the new password": "Yeni parolayla oturum aç",
  "This reset link is invalid, expired, or already used.": "Bu sıfırlama bağlantısı geçersiz, süresi dolmuş veya zaten kullanılmış.",
  "Request a new reset link": "Yeni sıfırlama bağlantısı iste",
  "Password reset is temporarily unavailable. Try again.": "Parola sıfırlama geçici olarak kullanılamıyor. Tekrar deneyin.",
  "Checking your reset link": "Sıfırlama bağlantınız kontrol ediliyor",
  "Choose a new password": "Yeni bir parola seçin",
  "Password reset complete": "Parola sıfırlama tamamlandı",
  "Reset link unavailable": "Sıfırlama bağlantısı kullanılamıyor"
};

@Component({
  selector: 'app-reset-password',
  imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="account-card" aria-labelledby="reset-title" [attr.aria-busy]="state() === 'loading' || submitting()">
      <p class="eyebrow">{{ t("Account recovery") }}</p>
      <h1 #heading id="reset-title" tabindex="-1">{{ t(title()) }}</h1>

      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish password-reset interface draft in local development. Bilingual approval is pending; unavailable preference reads fall back to English.") }}</p> }

      @if (error()) { <div class="form-status error" role="alert">{{ t(error()) }}</div> }
      @if (state() === 'loading') {
        <p role="status">{{ t("Checking your reset link.") }}</p>
      } @else if (state() === 'ready') {
        <p>{{ t("Choose a new password. Completing this reset signs out every existing session.") }}</p>
        <form (submit)="submit($event)">
          <label for="new-password">{{ t("New password") }}</label>
          <input id="new-password" name="password" type="password" autocomplete="new-password" minlength="12" required aria-describedby="reset-password-help" />
          <p id="reset-password-help" class="field-help">{{ t("Use at least 12 characters. Avoid common, entirely numeric, or personally similar passwords.") }}</p>

          <label for="new-password-confirm">{{ t("Confirm new password") }}</label>
          <input #confirmationInput id="new-password-confirm" name="confirmation" type="password" autocomplete="new-password" minlength="12" required
            [attr.aria-invalid]="confirmationError() ? 'true' : null"
            [attr.aria-describedby]="confirmationError() ? 'reset-password-confirm-error' : null"
            (input)="confirmationError.set(false)" />
          @if (confirmationError()) {
            <p id="reset-password-confirm-error" class="field-error">{{ t("The password confirmation does not match.") }}</p>
          }
          <button type="submit" [disabled]="submitting()">{{ t(submitting() ? 'Resetting…' : 'Reset password') }}</button>
        </form>
      } @else if (state() === 'complete') {
        <p role="status">{{ t("Your password has been reset and existing sessions have been signed out.") }}</p>
        <a class="button-link" routerLink="/account/login">{{ t("Sign in with the new password") }}</a>
      } @else {
        <p role="alert">{{ t("This reset link is invalid, expired, or already used.") }}</p>
        <a class="button-link" routerLink="/account/forgot-password">{{ t("Request a new reset link") }}</a>
      }
    </section>
  `,
})
export class ResetPassword implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  private readonly destroyRef = inject(DestroyRef);
  t(text: string) { return this.uiLanguage() === 'tr' ? resetTurkish[text] ?? text : text; }
  private readonly route = inject(ActivatedRoute);
  private readonly location = inject(Location);
  @ViewChild('heading') private heading?: ElementRef<HTMLElement>;
  @ViewChild('confirmationInput') private confirmationInput?: ElementRef<HTMLInputElement>;
  readonly state = signal<ResetState>('loading');
  readonly error = signal('');
  readonly confirmationError = signal(false);
  readonly submitting = signal(false);
  private readonly key = this.route.snapshot.fragment || '';

  constructor(private readonly api: AccountApi, title: Title) {
    effect(() => title.setTitle(`${this.t('Choose new password')} — OrganicSEOOps`));
  }

  async ngOnInit() {
    if (this.key) this.location.replaceState('/account/reset-password');
    void this.loadProductLanguage();
    try {
      const result = await this.api.passwordResetInfo(this.key);
      this.state.set(result.status === 200 ? 'ready' : 'invalid');
    } catch {
      this.state.set('invalid');
    }
    this.focusHeading();
  }

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
    const password = String(fields.get('password'));
    if (password !== String(fields.get('confirmation'))) {
      this.confirmationError.set(true);
      this.error.set('The password confirmation does not match.');
      setTimeout(() => this.confirmationInput?.nativeElement.focus());
      return;
    }
    this.error.set('');
    this.submitting.set(true);
    try {
      const result = await this.api.resetPassword(this.key, password);
      if (result.status === 401 || result.status === 200) {
        this.state.set('complete');
        form.reset();
      } else if (result.status === 400) {
        this.state.set('invalid');
      } else {
        this.error.set('Password reset is temporarily unavailable. Try again.');
      }
    } catch {
      this.error.set('Password reset is temporarily unavailable. Try again.');
    } finally {
      this.submitting.set(false);
      this.focusHeading();
    }
  }

  title() {
    return {
      loading: 'Checking your reset link',
      ready: 'Choose a new password',
      complete: 'Password reset complete',
      invalid: 'Reset link unavailable',
    }[this.state()];
  }

  private focusHeading() {
    queueMicrotask(() => this.heading?.nativeElement.focus());
  }
}
