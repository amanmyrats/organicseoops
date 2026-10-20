import { Title } from '@angular/platform-browser';
import { Component, computed, DestroyRef, effect, ElementRef, inject, OnInit, signal, ViewChild } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';
import { AccountApi } from './account-api';

const verificationResendTurkish: Record<string, string> = {
  "Verify email": "E-postayı doğrula",
  "One step left": "Bir adım kaldı",
  "Check your email": "E-postanızı kontrol edin",
  "Unreviewed Turkish verification-resend interface draft in local development. Bilingual approval is pending; unavailable preference reads fall back to English.": "Yerel geliştirmede incelenmemiş Türkçe doğrulama e-postasını yeniden isteme arayüzü taslağı. İki dilli onay bekleniyor; tercih okunamıyorsa İngilizceye dönülür.",
  "Use the verification link sent to": "Şuraya gönderilen doğrulama bağlantısını kullanın:",
  "your email address": "e-posta adresiniz",
  "Creating an account has not created an organization or trial.": "Hesap oluşturmak kuruluş veya deneme süresi oluşturmadı.",
  "Need another link? Enter your email address": "Başka bir bağlantı mı gerekiyor? E-posta adresinizi girin",
  "Requesting…": "İsteniyor…",
  "Resend verification email": "Doğrulama e-postasını yeniden iste",
  "Return to sign in": "Oturum açmaya dön",
  "Please wait before requesting another verification email.": "Başka bir doğrulama e-postası istemeden önce lütfen bekleyin.",
  "If verification is available, a new email has been sent.": "Doğrulama kullanılabiliyorsa yeni bir e-posta gönderildi.",
  "The request could not be completed. Check the email address and try again.": "İstek tamamlanamadı. E-posta adresini kontrol edip tekrar deneyin.",
  "Verification email is temporarily unavailable. Try again.": "Doğrulama e-postası geçici olarak kullanılamıyor. Tekrar deneyin."
};

@Component({
  selector: 'app-verification-pending',
  imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="account-card" aria-labelledby="verify-title">
      <p class="eyebrow">{{ t("One step left") }}</p>
      <h1 id="verify-title">{{ t("Check your email") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish verification-resend interface draft in local development. Bilingual approval is pending; unavailable preference reads fall back to English.") }}</p> }
      <p>{{ t("Use the verification link sent to") }} @if (destination()) { <span lang="">{{ destination() }}</span> } @else { {{ t("your email address") }} }. {{ t("Creating an account has not created an organization or trial.") }}</p>

      @if (status()) {
        <div #statusMessage class="form-status" [class.error]="failed()" role="status" tabindex="-1">{{ t(status()) }}</div>
      }

      <form (submit)="resend($event)">
        <label for="resend-email">{{ t("Need another link? Enter your email address") }}</label>
        <input id="resend-email" name="email" type="email" autocomplete="email" required />
        <button type="submit" [disabled]="submitting()">{{ t(submitting() ? 'Requesting…' : 'Resend verification email') }}</button>
      </form>

      <p class="account-alternate"><a routerLink="/account/login">{{ t("Return to sign in") }}</a></p>
    </section>
  `,
})
export class VerificationPending implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  private readonly destroyRef = inject(DestroyRef);
  t(text: string) { return this.uiLanguage() === 'tr' ? verificationResendTurkish[text] ?? text : text; }
  private readonly route = inject(ActivatedRoute);
  @ViewChild('statusMessage') private statusMessage?: ElementRef<HTMLElement>;
  readonly destination = signal(safeDestination(this.route.snapshot.queryParamMap.get('to')));
  readonly status = signal('');
  readonly failed = signal(false);
  readonly submitting = signal(false);

  constructor(private readonly api: AccountApi, title: Title) {
    effect(() => title.setTitle(`${this.t('Verify email')} — OrganicSEOOps`));
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

  async resend(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || this.submitting()) return;
    const email = String(new FormData(form).get('email'));
    this.status.set('');
    this.submitting.set(true);
    try {
      const result = await this.api.resendVerification(email);
      this.failed.set(result.status === 429 || result.status >= 400);
      this.status.set(result.status === 429
        ? 'Please wait before requesting another verification email.'
        : result.status < 400
          ? 'If verification is available, a new email has been sent.'
          : 'The request could not be completed. Check the email address and try again.');
    } catch {
      this.failed.set(true);
      this.status.set('Verification email is temporarily unavailable. Try again.');
    } finally {
      this.submitting.set(false);
      setTimeout(() => this.statusMessage?.nativeElement.focus());
    }
  }
}

function safeDestination(value: string | null) {
  return value && /^[^@\s]{1,6}\*+@[a-z0-9.-]+\.[a-z]{2,}$/i.test(value) ? value : '';
}
