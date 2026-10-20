import { Title } from '@angular/platform-browser';
import { Location } from '@angular/common';
import { Component, computed, DestroyRef, effect, ElementRef, inject, OnInit, signal, ViewChild } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';
import { AccountApi } from './account-api';

type VerificationState = 'loading' | 'pending' | 'verified' | 'expired' | 'used' | 'invalid';

const verificationTurkish: Record<string, string> = {
  "Verify email": "E-postayı doğrula",
  "Email verification": "E-posta doğrulaması",
  "Unreviewed Turkish email-verification interface draft in local development. Bilingual approval is pending; signed-out or unavailable preference falls back to English.": "Yerel geliştirmede incelenmemiş Türkçe e-posta doğrulama arayüzü taslağı. İki dilli onay bekleniyor; oturum kapalıysa veya tercih kullanılamıyorsa İngilizceye dönülür.",
  "Verifying…": "Doğrulanıyor…",
  "Verify email address": "E-posta adresini doğrula",
  "Request a new verification email": "Yeni bir doğrulama e-postası iste",
  "Continue to sign in": "Oturum açmaya devam et",
  "Checking your link": "Bağlantınız kontrol ediliyor",
  "Confirm your email address": "E-posta adresinizi doğrulayın",
  "Email address verified": "E-posta adresi doğrulandı",
  "This link has expired": "Bu bağlantının süresi doldu",
  "This link was already used": "Bu bağlantı zaten kullanıldı",
  "This link is not valid": "Bu bağlantı geçerli değil",
  "Please wait while we check this verification link.": "Bu doğrulama bağlantısını kontrol ederken lütfen bekleyin.",
  "Confirm to finish verifying your account. No organization or trial will be created yet.": "Hesabınızı doğrulamayı tamamlamak için onaylayın. Henüz kuruluş veya deneme süresi oluşturulmayacak.",
  "Your account is verified. You can now sign in.": "Hesabınız doğrulandı. Artık oturum açabilirsiniz.",
  "Request a new email to continue securely.": "Güvenli biçimde devam etmek için yeni bir e-posta isteyin.",
  "Your address may already be verified. Try signing in or request a new email if needed.": "Adresiniz zaten doğrulanmış olabilir. Oturum açmayı deneyin veya gerekirse yeni bir e-posta isteyin.",
  "The link may be incomplete. Request a new email to continue.": "Bağlantı eksik olabilir. Devam etmek için yeni bir e-posta isteyin."
};

@Component({
  selector: 'app-verify-email',
  imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="account-card" aria-labelledby="verification-title" [attr.aria-busy]="state() === 'loading' || submitting()">
      <p class="eyebrow">{{ t("Email verification") }}</p>
      <h1 #resultHeading id="verification-title" tabindex="-1">{{ t(heading()) }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish email-verification interface draft in local development. Bilingual approval is pending; signed-out or unavailable preference falls back to English.") }}</p> }
      <p aria-live="polite" [attr.role]="state() === 'expired' || state() === 'invalid' ? 'alert' : 'status'">{{ t(message()) }}</p>

      @if (state() === 'pending') {
        <button type="button" (click)="confirm()" [disabled]="submitting()">{{ t(submitting() ? 'Verifying…' : 'Verify email address') }}</button>
      } @else if (state() === 'expired' || state() === 'invalid') {
        <a class="button-link" routerLink="/account/verify">{{ t("Request a new verification email") }}</a>
      } @else if (state() === 'verified' || state() === 'used') {
        <a class="button-link" routerLink="/account/login">{{ t("Continue to sign in") }}</a>
      }
    </section>
  `,
})
export class VerifyEmail implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  private readonly destroyRef = inject(DestroyRef);
  t(text: string) { return this.uiLanguage() === 'tr' ? verificationTurkish[text] ?? text : text; }
  private readonly route = inject(ActivatedRoute);
  private readonly location = inject(Location);
  @ViewChild('resultHeading') private resultHeading?: ElementRef<HTMLElement>;
  readonly state = signal<VerificationState>('loading');
  readonly submitting = signal(false);
  private readonly key = this.route.snapshot.fragment || '';

  constructor(private readonly api: AccountApi, title: Title) {
    effect(() => title.setTitle(`${this.t('Verify email')} — OrganicSEOOps`));
  }

  async ngOnInit() {
    if (this.key) this.location.replaceState('/account/verify-email');
    void this.loadProductLanguage();
    try {
      const result = await this.api.verificationStatus(this.key);
      const state = result.body['state'];
      this.state.set(typeof state === 'string' && ['pending', 'expired', 'used', 'invalid'].includes(state) ? state as VerificationState : 'invalid');
    } catch {
      this.state.set('invalid');
    }
    this.focusResult();
  }

  private async loadProductLanguage() {
    try {
      const result = await this.api.productLanguage();
      if (!this.destroyRef.destroyed && result.status === 200 && isProductLanguageResult(result.body)) {
        this.productLanguage.set(result.body['language']);
      }
    } catch { /* Keep English when the private preference is unavailable. */ }
  }

  async confirm() {
    if (this.submitting()) return;
    this.submitting.set(true);
    try {
      await this.api.confirmVerification(this.key);
      const status = await this.api.verificationStatus(this.key);
      this.state.set(status.body['state'] === 'used' ? 'verified' : 'invalid');
    } catch {
      this.state.set('invalid');
    } finally {
      this.submitting.set(false);
      this.focusResult();
    }
  }

  heading() {
    return {
      loading: 'Checking your link',
      pending: 'Confirm your email address',
      verified: 'Email address verified',
      expired: 'This link has expired',
      used: 'This link was already used',
      invalid: 'This link is not valid',
    }[this.state()];
  }

  message() {
    return {
      loading: 'Please wait while we check this verification link.',
      pending: 'Confirm to finish verifying your account. No organization or trial will be created yet.',
      verified: 'Your account is verified. You can now sign in.',
      expired: 'Request a new email to continue securely.',
      used: 'Your address may already be verified. Try signing in or request a new email if needed.',
      invalid: 'The link may be incomplete. Request a new email to continue.',
    }[this.state()];
  }

  private focusResult() {
    queueMicrotask(() => this.resultHeading?.nativeElement.focus());
  }
}
