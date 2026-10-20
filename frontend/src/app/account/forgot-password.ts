import { Title } from '@angular/platform-browser';
import { Component, computed, DestroyRef, effect, ElementRef, inject, OnInit, signal, ViewChild } from '@angular/core';
import { RouterLink } from '@angular/router';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';
import { AccountApi } from './account-api';

const recoveryTurkish: Record<string, string> = {
  "Reset password": "Parolayı sıfırla",
  "Account recovery": "Hesap kurtarma",
  "Reset your password": "Parolanızı sıfırlayın",
  "Unreviewed Turkish password-recovery interface draft in local development. Bilingual approval is pending; unavailable preference reads fall back to English.": "Yerel geliştirmede incelenmemiş Türkçe parola kurtarma arayüzü taslağı. İki dilli onay bekleniyor; tercih okunamıyorsa İngilizceye dönülür.",
  "Enter your email address. If recovery is available, we will send a link that expires in one hour.": "E-posta adresinizi girin. Kurtarma kullanılabiliyorsa bir saat sonra süresi dolan bir bağlantı göndereceğiz.",
  "Email address": "E-posta adresi",
  "Requesting…": "İstek gönderiliyor…",
  "Send reset link": "Sıfırlama bağlantısı gönder",
  "Return to sign in": "Oturum açmaya dön",
  "If recovery is available, a reset link has been sent. Check your email.": "Kurtarma kullanılabiliyorsa bir sıfırlama bağlantısı gönderildi. E-postanızı kontrol edin.",
  "Please wait before requesting another reset link.": "Başka bir sıfırlama bağlantısı istemeden önce lütfen bekleyin.",
  "Password recovery is temporarily unavailable. Try again.": "Parola kurtarma geçici olarak kullanılamıyor. Tekrar deneyin."
};

@Component({
  selector: 'app-forgot-password',
  imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="account-card" aria-labelledby="recovery-title">
      <p class="eyebrow">{{ t("Account recovery") }}</p>
      <h1 id="recovery-title">{{ t("Reset your password") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish password-recovery interface draft in local development. Bilingual approval is pending; unavailable preference reads fall back to English.") }}</p> }
      <p>{{ t("Enter your email address. If recovery is available, we will send a link that expires in one hour.") }}</p>

      @if (message()) {
        <div #status class="form-status" role="status" tabindex="-1">{{ t(message()) }}</div>
      }
      @if (error()) {
        <div #status class="form-status error" role="alert" tabindex="-1">{{ t(error()) }}</div>
      }

      <form (submit)="submit($event)">
        <label for="recovery-email">{{ t("Email address") }}</label>
        <input id="recovery-email" name="email" type="email" autocomplete="email" required />
        <button type="submit" [disabled]="submitting()">{{ t(submitting() ? 'Requesting…' : 'Send reset link') }}</button>
      </form>

      <p class="account-alternate"><a routerLink="/account/login">{{ t("Return to sign in") }}</a>.</p>
    </section>
  `,
})
export class ForgotPassword implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  private readonly destroyRef = inject(DestroyRef);
  t(text: string) { return this.uiLanguage() === 'tr' ? recoveryTurkish[text] ?? text : text; }
  @ViewChild('status') private status?: ElementRef<HTMLElement>;
  readonly message = signal('');
  readonly error = signal('');
  readonly submitting = signal(false);

  constructor(private readonly api: AccountApi, title: Title) {
    effect(() => title.setTitle(`${this.t('Reset password')} — OrganicSEOOps`));
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
    this.message.set('');
    this.error.set('');
    this.submitting.set(true);
    try {
      const email = String(new FormData(form).get('email'));
      const result = await this.api.requestPasswordReset(email);
      if (result.status === 200) {
        this.message.set('If recovery is available, a reset link has been sent. Check your email.');
        form.reset();
      } else if (result.status === 429) {
        this.error.set('Please wait before requesting another reset link.');
      } else {
        this.error.set('Password recovery is temporarily unavailable. Try again.');
      }
    } catch {
      this.error.set('Password recovery is temporarily unavailable. Try again.');
    } finally {
      this.submitting.set(false);
      setTimeout(() => this.status?.nativeElement.focus());
    }
  }
}
