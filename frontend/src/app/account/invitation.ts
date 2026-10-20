import { Title } from '@angular/platform-browser';
import { Location } from '@angular/common';
import { Component, computed, DestroyRef, effect, ElementRef, inject, OnInit, signal, ViewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';
import { AccountApi } from './account-api';

type InvitationState = 'ready' | 'submitting' | 'accepted' | 'signed_out' | 'wrong_identity' | 'suspended' | 'unavailable' | 'conflict' | 'invalid';

const invitationTurkish: Record<string, string> = {
  "Organization invitation": "Kuruluş daveti",
  "Unreviewed Turkish invitation interface draft in local development. Bilingual approval is pending; signed-out or unavailable preference falls back to English.": "Yerel geliştirmede incelenmemiş Türkçe davet arayüzü taslağı. İki dilli onay bekleniyor; oturum kapalıysa veya tercih kullanılamıyorsa İngilizceye dönülür.",
  "Accept invitation": "Daveti kabul et",
  "Accepting your invitation.": "Davetiniz kabul ediliyor.",
  "Open the workspace": "Çalışma alanını aç",
  "Sign in, then reopen the invitation link": "Oturum açıp davet bağlantısını yeniden açın",
  "Sign out to switch account": "Hesap değiştirmek için oturumu kapat",
  "Return to the workspace": "Çalışma alanına dön",
  "Join the organization": "Kuruluşa katılın",
  "Accepting invitation": "Davet kabul ediliyor",
  "Invitation accepted": "Davet kabul edildi",
  "Sign in required": "Oturum açmanız gerekiyor",
  "Use the invited account": "Davet edilen hesabı kullanın",
  "Organization suspended": "Kuruluş askıya alındı",
  "Invitation unavailable": "Davet kullanılamıyor",
  "Membership changed": "Üyelik değişti",
  "Invitation link unavailable": "Davet bağlantısı kullanılamıyor",
  "Accept with the currently signed-in, verified email address. This does not create or reset a trial.": "Şu anda oturum açmış olduğunuz doğrulanmış e-posta adresiyle kabul edin. Bu işlem deneme süresi oluşturmaz veya sıfırlamaz.",
  "Please wait while access is checked.": "Erişim kontrol edilirken lütfen bekleyin.",
  "Your organization access is ready.": "Kuruluş erişiminiz hazır.",
  "Sign in with the invited account, then reopen the original invitation link.": "Davet edilen hesapla oturum açıp özgün davet bağlantısını yeniden açın.",
  "This invitation belongs to a different verified email address.": "Bu davet başka bir doğrulanmış e-posta adresine aittir.",
  "This organization is suspended. Try again after support restores access.": "Bu kuruluş askıya alındı. Destek erişimi yeniden sağladıktan sonra tekrar deneyin.",
  "This invitation is invalid, expired, revoked, or already unavailable.": "Bu davet geçersiz, süresi dolmuş, iptal edilmiş veya zaten kullanılamaz durumda.",
  "Your membership changed after this invitation was sent. Ask an organization owner to review access.": "Bu davet gönderildikten sonra üyeliğiniz değişti. Bir kuruluş sahibinden erişimi incelemesini isteyin.",
  "The invitation could not be checked. Ask the inviter for a new link.": "Davet kontrol edilemedi. Daveti gönderenden yeni bir bağlantı isteyin."
};

@Component({
  selector: 'app-invitation',
  imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="account-card" aria-labelledby="invitation-title" [attr.aria-busy]="state() === 'submitting'">
      <p class="eyebrow">{{ t("Organization invitation") }}</p>
      <h1 #heading id="invitation-title" tabindex="-1">{{ t(title()) }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish invitation interface draft in local development. Bilingual approval is pending; signed-out or unavailable preference falls back to English.") }}</p> }
      <p [attr.role]="state() === 'accepted' || state() === 'ready' ? 'status' : 'alert'">{{ t(message()) }}</p>

      @if (state() === 'ready') {
        <button type="button" (click)="accept()">{{ t("Accept invitation") }}</button>
      } @else if (state() === 'submitting') {
        <p role="status">{{ t("Accepting your invitation.") }}</p>
      } @else if (state() === 'accepted') {
        <a class="button-link" routerLink="/app">{{ t("Open the workspace") }}</a>
      } @else if (state() === 'signed_out') {
        <a class="button-link" routerLink="/account/login">{{ t("Sign in, then reopen the invitation link") }}</a>
      } @else if (state() === 'wrong_identity') {
        <button type="button" (click)="switchAccount()">{{ t("Sign out to switch account") }}</button>
      } @else {
        <a class="button-link" routerLink="/app">{{ t("Return to the workspace") }}</a>
      }
    </section>
  `,
})
export class Invitation implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  t(text: string) { return this.uiLanguage() === 'tr' ? invitationTurkish[text] ?? text : text; }
  private readonly route = inject(ActivatedRoute);
  private readonly location = inject(Location);
  private readonly destroyRef = inject(DestroyRef);
  @ViewChild('heading') private heading?: ElementRef<HTMLElement>;
  readonly state = signal<InvitationState>('ready');
  private token = '';

  constructor(private readonly api: AccountApi, title: Title) {
    effect(() => title.setTitle(`${this.t('Organization invitation')} — OrganicSEOOps`));
  }

  ngOnInit() {
    this.route.fragment.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((fragment) => {
      this.token = fragment || '';
      this.state.set(this.token ? 'ready' : 'invalid');
      if (this.token) this.location.replaceState('/account/invitation');
      this.focusHeading();
    });
    void this.loadProductLanguage();
  }

  private async loadProductLanguage() {
    try {
      const result = await this.api.productLanguage();
      if (!this.destroyRef.destroyed && result.status === 200 && isProductLanguageResult(result.body)) {
        this.productLanguage.set(result.body['language']);
      }
    } catch { /* Keep English when the private preference is unavailable. */ }
  }

  async switchAccount() {
    try {
      const result = await this.api.logout();
      this.state.set(result.status === 401 || (result.status >= 200 && result.status < 300) ? 'signed_out' : 'invalid');
    } catch {
      this.state.set('invalid');
    }
    this.focusHeading();
  }

  async accept() {
    if (!this.token || this.state() !== 'ready') return;
    this.state.set('submitting');
    try {
      const result = await this.api.acceptInvitation(this.token);
      if (result.status === 200) this.state.set('accepted');
      else if (result.status === 401) this.state.set('signed_out');
      else if (result.status === 403) this.state.set(result.body['errors'] instanceof Array
        && (result.body['errors'] as { code?: string }[])[0]?.code === 'suspended' ? 'suspended' : 'wrong_identity');
      else if (result.status === 409) this.state.set('conflict');
      else if (result.status === 404 || result.status === 410) this.state.set('unavailable');
      else this.state.set('invalid');
    } catch {
      this.state.set('invalid');
    }
    this.focusHeading();
  }

  title() {
    return {
      ready: 'Join the organization',
      submitting: 'Accepting invitation',
      accepted: 'Invitation accepted',
      signed_out: 'Sign in required',
      wrong_identity: 'Use the invited account',
      suspended: 'Organization suspended',
      unavailable: 'Invitation unavailable',
      conflict: 'Membership changed',
      invalid: 'Invitation link unavailable',
    }[this.state()];
  }

  message() {
    return {
      ready: 'Accept with the currently signed-in, verified email address. This does not create or reset a trial.',
      submitting: 'Please wait while access is checked.',
      accepted: 'Your organization access is ready.',
      signed_out: 'Sign in with the invited account, then reopen the original invitation link.',
      wrong_identity: 'This invitation belongs to a different verified email address.',
      suspended: 'This organization is suspended. Try again after support restores access.',
      unavailable: 'This invitation is invalid, expired, revoked, or already unavailable.',
      conflict: 'Your membership changed after this invitation was sent. Ask an organization owner to review access.',
      invalid: 'The invitation could not be checked. Ask the inviter for a new link.',
    }[this.state()];
  }

  private focusHeading() {
    queueMicrotask(() => this.heading?.nativeElement.focus());
  }
}
