import { Title } from '@angular/platform-browser';
import { Component, computed, DestroyRef, effect, ElementRef, inject, OnInit, signal, ViewChild } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';
import { AccountApi } from './account-api';

const registrationTurkish: Record<string, string> = {
  "Start with an account": "Bir hesapla başlayın",
  "Create your account": "Hesabınızı oluşturun",
  "Unreviewed Turkish registration interface draft in local development. Bilingual approval is pending; unavailable preference reads fall back to English. Linked local terms and privacy drafts are also unreviewed.": "Yerel geliştirmede incelenmemiş Türkçe kayıt arayüzü taslağı. İki dilli onay bekleniyor; tercih okunamıyorsa İngilizceye dönülür. Bağlantılı yerel koşullar ve gizlilik taslakları da incelenmemiştir.",
  "We will send a verification link before you can sign in.": "Oturum açabilmeniz için önce bir doğrulama bağlantısı göndereceğiz.",
  "Email address": "E-posta adresi",
  "Password": "Parola",
  "Use at least 12 characters. Avoid common, entirely numeric, or personally similar passwords.": "En az 12 karakter kullanın. Yaygın, tamamen sayısal veya kişisel bilgilerinize benzeyen parolalardan kaçının.",
  "Confirm password": "Parolayı doğrulayın",
  "The password confirmation does not match.": "Parola doğrulaması eşleşmiyor.",
  "I understand this is a local development account and have read the": "Yerel geliştirme hesabı açtığımı ve aşağıdaki metinleri okuduğumu anlıyorum:",
  "local terms draft": "yerel koşullar taslağı",
  "and": "ve",
  "local privacy draft": "yerel gizlilik taslağı",
  "These local drafts are not an approved contract or privacy notice. This acknowledgment is for an authorized local development account, not a public offer.": "Bu yerel taslaklar onaylı sözleşme veya gizlilik bildirimi değildir. Bu bildirim yetkili yerel geliştirme hesabı içindir; herkese açık teklif değildir.",
  "Creating account…": "Hesap oluşturuluyor…",
  "Create account": "Hesap oluştur",
  "Already registered?": "Zaten kayıtlı mısınız?",
  "Sign in": "Oturum aç",
  "Account creation failed. Check the email and password requirements, then try again.": "Hesap oluşturulamadı. E-posta ve parola gereksinimlerini kontrol edip tekrar deneyin.",
  "Account creation is temporarily unavailable. Try again.": "Hesap oluşturma geçici olarak kullanılamıyor. Tekrar deneyin."
};

@Component({
  selector: 'app-register',
  imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="account-card" aria-labelledby="register-title">
      <p class="eyebrow">{{ t("Start with an account") }}</p>
      <h1 id="register-title">{{ t("Create your account") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish registration interface draft in local development. Bilingual approval is pending; unavailable preference reads fall back to English. Linked local terms and privacy drafts are also unreviewed.") }}</p> }
      <p>{{ t("We will send a verification link before you can sign in.") }}</p>

      @if (error()) {
        <div #errorSummary class="form-status error" role="alert" tabindex="-1">{{ t(error()) }}</div>
      }

      <form (submit)="submit($event)">
        <label for="email">{{ t("Email address") }}</label>
        <input id="email" name="email" type="email" autocomplete="email" required />

        <label for="password">{{ t("Password") }}</label>
        <input id="password" name="password" type="password" autocomplete="new-password" minlength="12" required aria-describedby="password-help" />
        <p id="password-help" class="field-help">{{ t("Use at least 12 characters. Avoid common, entirely numeric, or personally similar passwords.") }}</p>

        <label for="password-confirm">{{ t("Confirm password") }}</label>
        <input #confirmationInput id="password-confirm" name="password-confirm" type="password" autocomplete="new-password" minlength="12" required
          [attr.aria-invalid]="confirmationError() ? 'true' : null" [attr.aria-describedby]="confirmationError() ? 'password-confirm-error' : null"
          (input)="clearConfirmationError($event)" />
        @if (confirmationError()) {
          <p id="password-confirm-error" class="field-error">{{ t("The password confirmation does not match.") }}</p>
        }

        <div class="check-row">
          <input id="development-terms" name="development-terms" type="checkbox" required aria-describedby="development-policy-help" />
          <label for="development-terms">{{ t("I understand this is a local development account and have read the") }} <a [routerLink]="uiLanguage() === 'tr' ? '/preview/tr/terms' : '/preview/terms'">{{ t("local terms draft") }}</a> {{ t("and") }} <a [routerLink]="uiLanguage() === 'tr' ? '/preview/tr/privacy' : '/preview/privacy'">{{ t("local privacy draft") }}</a>.</label>
        </div>
        <p id="development-policy-help" class="field-help">{{ t("These local drafts are not an approved contract or privacy notice. This acknowledgment is for an authorized local development account, not a public offer.") }}</p>

        <button type="submit" [disabled]="submitting()">{{ t(submitting() ? 'Creating account…' : 'Create account') }}</button>
      </form>

      <p class="account-alternate">{{ t("Already registered?") }} <a routerLink="/account/login">{{ t("Sign in") }}</a>.</p>
    </section>
  `,
})
export class Register implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  private readonly destroyRef = inject(DestroyRef);
  t(text: string) { return this.uiLanguage() === 'tr' ? registrationTurkish[text] ?? text : text; }
  @ViewChild('confirmationInput') private confirmationInput?: ElementRef<HTMLInputElement>;
  @ViewChild('errorSummary') private errorSummary?: ElementRef<HTMLElement>;
  readonly error = signal('');
  readonly confirmationError = signal(false);
  readonly submitting = signal(false);

  private readonly confirmationValidity = effect(() => {
    if (this.confirmationError()) {
      this.confirmationInput?.nativeElement.setCustomValidity(this.t('The password confirmation does not match.'));
    }
  });

  constructor(private readonly api: AccountApi, private readonly router: Router, title: Title) {
    effect(() => title.setTitle(`${this.t('Create account')} — OrganicSEOOps`));
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
    const email = String(fields.get('email'));
    const password = String(fields.get('password'));
    if (password !== String(fields.get('password-confirm'))) {
      const confirmation = form.elements.namedItem('password-confirm') as HTMLInputElement;
      confirmation.setCustomValidity(this.t('The password confirmation does not match.'));
      this.confirmationError.set(true);
      this.showError('The password confirmation does not match.');
      return;
    }

    this.error.set('');
    this.submitting.set(true);
    try {
      const result = await this.api.signup(email, password);
      if (result.status === 200 || this.api.hasPendingVerification(result)) {
        await this.router.navigate(['/account/verify'], { queryParams: { to: maskEmail(email) } });
      } else {
        this.showError('Account creation failed. Check the email and password requirements, then try again.');
      }
    } catch {
      this.showError('Account creation is temporarily unavailable. Try again.');
    } finally {
      this.submitting.set(false);
    }
  }

  private showError(message: string) {
    this.error.set(message);
    setTimeout(() => this.errorSummary?.nativeElement.focus());
  }

  clearConfirmationError(event: Event) {
    (event.currentTarget as HTMLInputElement).setCustomValidity('');
    this.confirmationError.set(false);
  }
}

function maskEmail(email: string) {
  const [local, domain] = email.trim().split('@');
  if (!local || !domain) return '';
  return `${local.slice(0, 1)}${'*'.repeat(Math.min(Math.max(local.length - 1, 1), 5))}@${domain}`;
}
