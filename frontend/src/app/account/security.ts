import { Component, computed, effect, ElementRef, OnInit, signal, ViewChild } from '@angular/core';
import { Title } from '@angular/platform-browser';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { AccountApi, AuthenticatorInfo, SessionInfo } from './account-api';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';

@Component({
  selector: 'app-security',
  imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="account-card security-card" aria-labelledby="security-title">
      <p class="eyebrow">{{ t("Personal settings") }}</p>
      <h1 id="security-title">{{ t("Security and sessions") }}</h1>
      <p><a routerLink="/app">{{ t("Return to the workspace") }}</a></p>
      @if (uiLanguage() === 'tr') {
        <p role="status">{{ t("Unreviewed Turkish Security draft in local development. Remaining application areas remain English; bilingual approval is pending.") }}</p>
      }
      @if (message()) { <p class="form-status" role="status">{{ t(message()) }}</p> }
      @if (error()) { <p #errorSummary class="form-status error" role="alert" tabindex="-1">{{ t(error()) }}</p> }

      <section aria-labelledby="password-title">
        <h2 id="password-title">{{ t("Change password") }}</h2>
        <p>{{ t("Changing your password signs out every session, including this one.") }}</p>
        <form (submit)="changePassword($event)">
          <label for="current-password">{{ t("Current password") }}</label>
          <input id="current-password" name="current-password" type="password" autocomplete="current-password" required />
          <label for="security-new-password">{{ t("New password") }}</label>
          <input id="security-new-password" name="new-password" type="password" autocomplete="new-password" minlength="12" required />
          <label for="security-new-password-confirm">{{ t("Confirm new password") }}</label>
          <input id="security-new-password-confirm" name="confirmation" type="password" autocomplete="new-password" minlength="12" required
            [attr.aria-invalid]="passwordConfirmationError() ? 'true' : null"
            [attr.aria-describedby]="passwordConfirmationError() ? 'security-password-confirm-error' : null"
            (input)="passwordConfirmationError.set(false)" />
          @if (passwordConfirmationError()) {
            <p id="security-password-confirm-error" class="field-error">{{ t("The new password confirmation does not match.") }}</p>
          }
          <button type="submit" [disabled]="submitting()">{{ t("Change password") }}</button>
        </form>
      </section>

      <section aria-labelledby="email-title">
        <h2 id="email-title">{{ t("Change email address") }}</h2>
        <p>{{ t("Your current address stays active until the new one is verified. We notify the old address after the change.") }}</p>
        <form (submit)="changeEmail($event)">
          <label for="new-email">{{ t("New email address") }}</label>
          <input id="new-email" name="email" type="email" autocomplete="email" required />
          <label for="email-change-password">{{ t("Current password") }}</label>
          <input id="email-change-password" name="password" type="password" autocomplete="current-password" required />
          <button type="submit" [disabled]="submitting()">{{ t("Send verification email") }}</button>
        </form>
      </section>

      <section aria-labelledby="language-title">
        <h2 id="language-title">{{ t("Product language preference") }}</h2>
        <p>{{ t("Your project SEO target languages are separate. Application translations and bilingual review remain unfinished.") }}</p>
        @if (languageLoading()) { <p role="status">{{ t("Loading language preference.") }}</p> }
        @else if (languageFailed()) {
          <p role="alert">{{ t("Language preference is unavailable.") }}</p>
          <button type="button" (click)="loadLanguage()">{{ t("Retry loading language preference") }}</button>
        } @else {
          <p>{{ emailLanguage() === 'tr'
            ? t('Critical account, trial and billing emails use unreviewed Turkish drafts in this local development preview.')
            : t('Critical account, trial and billing emails currently remain in English.') }}</p>
          <form (submit)="saveLanguage($event)">
            <label for="product-language">{{ t("Preferred product language") }}</label>
            <select id="product-language" name="product-language" [value]="language()">
              <option value="en">{{ t("English") }}</option>
              <option value="tr">{{ t("Turkish (translations pending)") }}</option>
            </select>
            <button type="submit" [disabled]="submitting()">{{ t("Save language preference") }}</button>
          </form>
        }
      </section>

      @if (staffMfa()) {
        <section aria-labelledby="mfa-title">
          <h2 id="mfa-title">{{ t("Staff two-factor authentication") }}</h2>
          <p><a routerLink="/account/provider-settings">{{ t("Manage platform provider credentials") }}</a></p>
          <p><a routerLink="/account/acquisition">{{ t("Review operational acquisition milestones") }}</a></p>
          @if (mfaRequired) {
            <p class="form-status" role="status">{{ t("Set up two-factor authentication before opening Django Admin.") }}</p>
          }
          @if (!mfaEnrolled()) {
            <p>{{ t("Staff production access requires a time-based code. Add this account to an authenticator app, then enter its six-digit code.") }}</p>
            @if (totpSecret()) {
              <p class="secret-value"><strong>{{ t("Setup key") }}</strong> <code>{{ totpSecret() }}</code></p>
              <p class="field-help">{{ t("Treat this setup key like a password. It disappears after activation.") }}</p>
              <form (submit)="activateMfa($event)">
                <label for="totp-code">{{ t("Authenticator code") }}</label>
                <input id="totp-code" name="code" type="text" inputmode="numeric" autocomplete="one-time-code" required />
                <button type="submit" [disabled]="submitting()">{{ t("Activate two-factor authentication") }}</button>
              </form>
            } @else {
              <button type="button" (click)="beginMfaSetup()" [disabled]="submitting()">{{ t("Generate setup key") }}</button>
            }
          } @else {
            <p>{{ t('Two-factor authentication is active.') }} {{ unusedRecoveryCodes() }} {{ t('recovery codes remain.') }}</p>
            <p>{{ t("Staff cannot disable their own authenticator. This prevents accidental production lockout weakening.") }}</p>
            @if (mfaRequired) { <p><a class="button-link" href="/admin/">{{ t("Continue to Django Admin") }}</a></p> }
            <form (submit)="regenerateRecoveryCodes($event)">
              <label for="mfa-current-password">{{ t("Current password") }}</label>
              <input id="mfa-current-password" name="password" type="password" autocomplete="current-password" required />
              <button type="submit" [disabled]="submitting()">{{ t("Replace recovery codes") }}</button>
            </form>
          }
          @if (recoveryCodes().length) {
            <div class="recovery-codes form-status" role="status">
              <strong>{{ t("Store these recovery codes now") }}</strong>
              <p>{{ t("Each code works once. They will not be shown again.") }}</p>
              <ul>
                @for (code of recoveryCodes(); track code) { <li><code>{{ code }}</code></li> }
              </ul>
            </div>
          }
        </section>
      }

      <section aria-labelledby="sessions-title">
        <h2 id="sessions-title">{{ t("Active sessions") }}</h2>
        @if (loadingSessions()) {
          <p role="status">{{ t("Loading sessions.") }}</p>
        } @else if (!sessions().length) {
          <p>{{ t("No active sessions are available. Sign in again if your session expired.") }}</p>
        } @else {
          <ul class="session-list">
            @for (session of sessions(); track session.id) {
              <li>
                <strong>{{ session.is_current ? t('This session') : (session.user_agent || t('Unknown browser')) }}</strong>
                <span>{{ session.ip }} · {{ t('started') }} {{ formatDate(session.created_at) }}</span>
                @if (!session.is_current) {
                  <button type="button" (click)="revoke(session.id)" [disabled]="submitting()"
                    [attr.aria-label]="t('Revoke session: ') + (session.user_agent || t('Unknown browser'))">{{ t("Revoke") }}</button>
                }
              </li>
            }
          </ul>
          @if (confirmLogoutAll()) {
            <div class="form-status" role="alert">
              <p>{{ t("Sign out every session, including this one?") }}</p>
              <button type="button" class="danger-button" (click)="logoutAll()" [disabled]="submitting()">{{ t("Confirm sign out everywhere") }}</button>
              <button type="button" class="secondary-button" (click)="confirmLogoutAll.set(false)" [disabled]="submitting()">{{ t("Cancel") }}</button>
            </div>
          } @else {
            <button type="button" class="danger-button" (click)="confirmLogoutAll.set(true)" [disabled]="submitting()">{{ t("Sign out everywhere") }}</button>
          }
        }
        @if (sessionsFailed()) { <button type="button" (click)="loadSessions()">{{ t("Retry loading sessions") }}</button> }
      </section>
      <section aria-labelledby="closure-title">
        <h2 id="closure-title">{{ t("Leaving and account closure") }}</h2>
        <p>{{ t("Export your own account details separately from organization project data. The private account file includes your saved email identities, current organization memberships and bounded session/mail diagnostics; it excludes credentials and other members' content. Re-enter your password before downloading it.") }}</p>
        <form (submit)="downloadAccountData($event)">
          <label for="account-export-password">{{ t("Current password") }}</label>
          <input id="account-export-password" name="password" type="password" autocomplete="current-password" required />
          <button type="submit" [disabled]="submitting()">{{ t("Download personal account JSON") }}</button>
        </form>
        <p>{{ t("Leave organizations from the workspace. A last active owner must transfer ownership or close the organization first; leaving never deletes another member's projects.") }}</p>
        @if (accountClosureAvailable()) {
          <p>{{ t("Closing your account disables login and every session immediately. Your email/automatic-trial eligibility and restricted audit identity remain under a separate reviewed erasure policy; this does not erase another member's project or all copies from backups. You cannot sign in again after confirmation.") }}</p>
          <form (submit)="closeAccount($event)">
            <label for="personal-closure-password">{{ t("Current password") }}</label>
            <input id="personal-closure-password" name="password" type="password" autocomplete="current-password" required />
            <label><input name="acknowledge" type="checkbox" required /> {{ t("I understand account access ends now and restricted identity is not yet erased.") }}</label>
            <button type="submit" class="danger-button" [disabled]="submitting()">{{ t("Permanently close personal access") }}</button>
          </form>
        } @else {
          <p>{{ accountRequiresOrgExit() ? t('Leave or close active organizations before personal closure.') : t('Self-service account closure is release-gated.') }}</p>
        }
        <p><a routerLink="/app">{{ t("Review organization ownership") }}</a></p>
      </section>
    </section>
  `,
})
export class Security implements OnInit {
  @ViewChild('errorSummary') private errorSummary?: ElementRef<HTMLElement>;
  readonly sessions = signal<SessionInfo[]>([]);
  readonly loadingSessions = signal(true);
  readonly sessionsFailed = signal(false);
  readonly submitting = signal(false);
  readonly message = signal<SecurityText | ''>('');
  readonly error = signal<SecurityText | ''>('');
  readonly passwordConfirmationError = signal(false);
  readonly confirmLogoutAll = signal(false);
  readonly staffMfa = signal(false);
  readonly mfaEnrolled = signal(false);
  readonly totpSecret = signal('');
  readonly recoveryCodes = signal<string[]>([]);
  readonly unusedRecoveryCodes = signal(0);
  readonly mfaRequired: boolean;
  readonly language = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.language()));
  readonly emailLanguage = signal<'en' | 'tr'>('en');
  readonly languageLoading = signal(true);
  readonly languageFailed = signal(false);
  readonly accountClosureAvailable = signal(false);
  readonly accountRequiresOrgExit = signal(false);

  constructor(private readonly api: AccountApi, private readonly router: Router, route: ActivatedRoute, title: Title) {
    this.mfaRequired = route.snapshot.queryParamMap.get('mfa') === 'required';
    effect(() => title.setTitle(`${this.t('Security and sessions')} — OrganicSEOOps`));
  }

  ngOnInit() {
    void this.loadSessions();
    void this.loadMfa();
    void this.loadLanguage();
    void this.loadAccountClosureStatus();
  }

  async loadAccountClosureStatus() {
    this.accountClosureAvailable.set(false);
    this.accountRequiresOrgExit.set(false);
    try {
      const result = await this.api.personalClosureStatus();
      if (result.status !== 200 || typeof result.body['action_available'] !== 'boolean'
          || typeof result.body['requires_org_exit'] !== 'boolean'
          || result.body['retained_identity'] !== 'restricted_policy_review_not_erased') return;
      this.accountClosureAvailable.set(result.body['action_available']);
      this.accountRequiresOrgExit.set(result.body['requires_org_exit']);
    } catch { /* Keep the irreversible control unavailable if status cannot be checked. */ }
  }

  async closeAccount(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!this.accountClosureAvailable() || this.submitting() || !form.reportValidity()) return;
    if (!new FormData(form).has('acknowledge')) return;
    this.startRequest();
    try {
      const auth = await this.api.reauthenticate(String(new FormData(form).get('password') || ''));
      if (auth.status !== 200) throw new Error();
      const result = await this.api.closePersonalAccount();
      if (result.status !== 202 || result.body['state'] !== 'access_closed'
          || result.body['retained_identity'] !== 'restricted_policy_review_not_erased') throw new Error();
      form.reset(); this.accountClosureAvailable.set(false); this.sessions.set([]);
      this.message.set('Personal access closed; all sessions are invalid. Restricted identity is retained for review and no other organization content was deleted.');
    } catch {
      this.showError('Personal closure outcome unavailable. Do not retry until you verify whether your session is still active.');
    } finally { this.submitting.set(false); }
  }

  async downloadAccountData(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || this.submitting()) return;
    this.startRequest();
    try {
      const password = String(new FormData(form).get('password') || '');
      const reauthenticated = await this.api.reauthenticate(password);
      if (reauthenticated.status !== 200) throw new Error();
      await this.api.personalAccountArchive();
      form.reset();
      this.message.set('Personal account download requested. Your browser saves the JSON file; a refused request displays an error. Organization customer content requires an owner-scoped export.');
    } catch {
      this.showError('Personal account export is unavailable. Recheck your password and session, then retry.');
    } finally { this.submitting.set(false); }
  }

  async loadLanguage() {
    this.languageLoading.set(true);
    this.language.set('en');
    this.emailLanguage.set('en');
    this.languageFailed.set(false);
    try {
      const result = await this.api.productLanguage();
      if (result.status !== 200 || !isProductLanguageResult(result.body)) throw new Error();
      this.language.set(result.body['language']);
      this.emailLanguage.set(result.body['current_email_language']);
    } catch {
      this.languageFailed.set(true);
    } finally {
      this.languageLoading.set(false);
    }
  }

  async saveLanguage(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const selected = new FormData(form).get('product-language');
    if (!form.reportValidity() || (selected !== 'en' && selected !== 'tr') || this.submitting()) return;
    this.startRequest();
    try {
      const result = await this.api.saveProductLanguage(selected);
      if (result.status !== 200 || !isProductLanguageResult(result.body) || result.body['language'] !== selected) {
        throw new Error();
      }
      this.language.set(selected);
      this.emailLanguage.set(result.body['current_email_language']);
      this.message.set(this.emailLanguage() === 'tr'
        ? 'Language preference saved. Critical emails use unreviewed Turkish drafts in local development.'
        : 'Language preference saved. Account emails still display in English.');
    } catch {
      this.showError('Your language preference could not be saved. Try again.');
    } finally {
      this.submitting.set(false);
    }
  }

  async loadMfa() {
    try {
      const result = await this.api.authenticators();
      if (result.status !== 200) return;
      this.staffMfa.set(true);
      const authenticators = Array.isArray(result.body['data'])
        ? result.body['data'].filter(isAuthenticatorInfo) as AuthenticatorInfo[]
        : [];
      this.mfaEnrolled.set(authenticators.some((item) => item.type === 'totp'));
      const recovery = authenticators.find((item) => item.type === 'recovery_codes');
      this.unusedRecoveryCodes.set(recovery?.unused_code_count || 0);
    } catch {
      this.showError('Two-factor authentication status is temporarily unavailable. Refresh and try again.');
    }
  }

  async beginMfaSetup() {
    this.startRequest();
    try {
      const result = await this.api.totpSetup();
      const meta = result.body['meta'];
      const secret = meta && typeof meta === 'object' ? (meta as Record<string, unknown>)['secret'] : undefined;
      if (result.status === 404 && typeof secret === 'string') this.totpSecret.set(secret);
      else this.showError('The setup key could not be generated. Refresh and try again.');
    } catch {
      this.showError('The setup key could not be generated. Refresh and try again.');
    } finally {
      this.submitting.set(false);
    }
  }

  async activateMfa(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || this.submitting()) return;
    this.startRequest();
    try {
      const result = await this.api.activateTotp(String(new FormData(form).get('code')));
      if (result.status !== 200) {
        this.showError('The authenticator code was not accepted. Check it and try again.');
        return;
      }
      this.mfaEnrolled.set(true);
      this.totpSecret.set('');
      const recovery = await this.api.recoveryCodes();
      this.setRecoveryCodes(recovery);
      this.message.set('Two-factor authentication is active. Other sessions were revoked.');
    } catch {
      this.showError('Two-factor authentication could not be activated. Try again.');
    } finally {
      this.submitting.set(false);
    }
  }

  async regenerateRecoveryCodes(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || this.submitting()) return;
    this.startRequest();
    try {
      const reauthenticated = await this.api.reauthenticate(String(new FormData(form).get('password')));
      if (reauthenticated.status !== 200) {
        this.showError('Recovery codes were not changed. Check your password and try again.');
        return;
      }
      const result = await this.api.regenerateRecoveryCodes();
      if (result.status === 200) {
        this.setRecoveryCodes(result);
        this.message.set('Previous recovery codes were replaced and other sessions were revoked.');
        form.reset();
      } else this.showError('Recovery codes could not be replaced. Try again.');
    } catch {
      this.showError('Recovery codes could not be replaced. Try again.');
    } finally {
      this.submitting.set(false);
    }
  }

  async changePassword(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || this.submitting()) return;
    const fields = new FormData(form);
    const password = String(fields.get('new-password'));
    if (password !== String(fields.get('confirmation'))) {
      this.passwordConfirmationError.set(true);
      this.showError('The new password confirmation does not match.');
      return;
    }
    this.startRequest();
    try {
      const result = await this.api.changePassword(String(fields.get('current-password')), password);
      if (result.status === 204) {
        await this.router.navigate(['/account/login'], { queryParams: { changed: 'password' } });
      } else {
        this.showError('Password change failed. Check your current password and the new password requirements.');
      }
    } catch {
      this.showError('Password change is temporarily unavailable. Try again.');
    } finally {
      this.submitting.set(false);
    }
  }

  async changeEmail(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || this.submitting()) return;
    const fields = new FormData(form);
    this.startRequest();
    try {
      const reauthenticated = await this.api.reauthenticate(String(fields.get('password')));
      if (reauthenticated.status !== 200) {
        this.showError('Email change failed. Check your current password and try again.');
        return;
      }
      const result = await this.api.requestEmailChange(String(fields.get('email')));
      if (result.status === 200) {
        this.message.set('Check the new address for a verification link. Your current sign-in email is unchanged until verification.');
        form.reset();
      } else {
        this.showError('Email change failed. Check the address and try again.');
      }
    } catch {
      this.showError('Email change is temporarily unavailable. Try again.');
    } finally {
      this.submitting.set(false);
    }
  }

  async revoke(id: number) {
    this.startRequest();
    try {
      const result = await this.api.endSessions([id]);
      if (result.status === 200) {
        this.setSessions(result);
        this.message.set('The selected session was revoked.');
      } else {
        this.showError('The session could not be revoked. Refresh and try again.');
      }
    } catch {
      this.showError('The session could not be revoked. Refresh and try again.');
    } finally {
      this.submitting.set(false);
    }
  }

  async logoutAll() {
    this.startRequest();
    try {
      const result = await this.api.logoutAll();
      if (result.status === 204) {
        await this.router.navigateByUrl('/account/login');
      } else {
        this.showError('Sessions may still be active. Refresh and try again.');
      }
    } catch {
      this.showError('Sessions may still be active. Refresh and try again.');
    } finally {
      this.submitting.set(false);
    }
  }

  t(key: SecurityText | '') {
    return key && this.uiLanguage() === 'tr' ? securityTurkish[key] : key;
  }

  formatDate(timestamp: number) {
    return new Date(timestamp * 1000).toLocaleString(this.uiLanguage() === 'tr' ? 'tr-TR' : 'en-US');
  }

  async loadSessions() {
    this.loadingSessions.set(true);
    this.sessionsFailed.set(false);
    try {
      const result = await this.api.sessions();
      if (result.status === 200) this.setSessions(result);
      else {
        this.sessionsFailed.set(true);
        this.showError('Your session expired. Sign in again to manage account security.');
      }
    } catch {
      this.sessionsFailed.set(true);
      this.showError('Sessions are temporarily unavailable. Refresh and try again.');
    } finally {
      this.loadingSessions.set(false);
    }
  }

  private setSessions(result: { body: Record<string, unknown> }) {
    const data = result.body['data'];
    this.sessions.set(Array.isArray(data) ? data.filter(isSessionInfo) : []);
  }

  private setRecoveryCodes(result: { body: Record<string, unknown> }) {
    const data = result.body['data'];
    const codes = data && typeof data === 'object' ? (data as Record<string, unknown>)['unused_codes'] : undefined;
    this.recoveryCodes.set(Array.isArray(codes) ? codes.filter((code): code is string => typeof code === 'string') : []);
    this.unusedRecoveryCodes.set(this.recoveryCodes().length);
  }

  private startRequest() {
    this.error.set('');
    this.message.set('');
    this.submitting.set(true);
  }

  private showError(message: SecurityText) {
    this.error.set(message);
    setTimeout(() => this.errorSummary?.nativeElement.focus());
  }
}

function isSessionInfo(value: unknown): value is SessionInfo {
  if (!value || typeof value !== 'object') return false;
  const session = value as Record<string, unknown>;
  return typeof session['id'] === 'number'
    && typeof session['user_agent'] === 'string'
    && typeof session['ip'] === 'string'
    && typeof session['created_at'] === 'number'
    && typeof session['is_current'] === 'boolean';
}

function isAuthenticatorInfo(value: unknown): value is AuthenticatorInfo {
  if (!value || typeof value !== 'object') return false;
  const authenticator = value as Record<string, unknown>;
  return (authenticator['type'] === 'totp' || authenticator['type'] === 'recovery_codes')
    && typeof authenticator['created_at'] === 'number';
}


// Unreviewed local drafts; production uses the English keys.
const securityTurkish = {
  "Personal settings": "Kişisel ayarlar",
  "Security and sessions": "Güvenlik ve oturumlar",
  "Return to the workspace": "Çalışma alanına dön",
  "Change password": "Parolayı değiştir",
  "Changing your password signs out every session, including this one.": "Parolanızı değiştirmek bu oturum dahil tüm oturumları kapatır.",
  "Current password": "Mevcut parola",
  "New password": "Yeni parola",
  "Confirm new password": "Yeni parolayı doğrulayın",
  "The new password confirmation does not match.": "Yeni parola ile doğrulaması eşleşmiyor.",
  "Change email address": "E-posta adresini değiştir",
  "Your current address stays active until the new one is verified. We notify the old address after the change.": "Yeni adres doğrulanana kadar mevcut adresiniz etkin kalır. Değişiklikten sonra eski adresinize bildirim göndeririz.",
  "New email address": "Yeni e-posta adresi",
  "Send verification email": "Doğrulama e-postası gönder",
  "Product language preference": "Ürün dili tercihi",
  "Your project SEO target languages are separate. Application translations and bilingual review remain unfinished.": "Projelerinizin SEO hedef dilleri ayrıdır. Uygulama çevirileri ve iki dilde inceleme henüz tamamlanmadı.",
  "Loading language preference.": "Dil tercihi yükleniyor.",
  "Language preference is unavailable.": "Dil tercihi kullanılamıyor.",
  "Retry loading language preference": "Dil tercihini yüklemeyi yeniden dene",
  "Critical account, trial and billing emails use unreviewed Turkish drafts in this local development preview.": "Bu yerel geliştirme önizlemesinde önemli hesap, deneme ve faturalandırma e-postaları incelenmemiş Türkçe taslaklar kullanır.",
  "Critical account, trial and billing emails currently remain in English.": "Önemli hesap, deneme ve faturalandırma e-postaları şu anda İngilizcedir.",
  "Preferred product language": "Tercih edilen ürün dili",
  "English": "İngilizce",
  "Turkish (translations pending)": "Türkçe (çeviriler tamamlanmadı)",
  "Save language preference": "Dil tercihini kaydet",
  "Staff two-factor authentication": "Personel için iki faktörlü kimlik doğrulama",
  "Manage platform provider credentials": "Platform sağlayıcı kimlik bilgilerini yönet",
  "Review operational acquisition milestones": "Operasyonel müşteri edinme aşamalarını incele",
  "Set up two-factor authentication before opening Django Admin.": "Django Admin’i açmadan önce iki faktörlü kimlik doğrulamayı kurun.",
  "Staff production access requires a time-based code. Add this account to an authenticator app, then enter its six-digit code.": "Personelin üretim ortamına erişimi zamana dayalı bir kod gerektirir. Bu hesabı bir kimlik doğrulama uygulamasına ekleyin ve altı haneli kodunu girin.",
  "Setup key": "Kurulum anahtarı",
  "Treat this setup key like a password. It disappears after activation.": "Bu kurulum anahtarını parola gibi koruyun. Etkinleştirmeden sonra kaybolur.",
  "Authenticator code": "Kimlik doğrulama kodu",
  "Activate two-factor authentication": "İki faktörlü kimlik doğrulamayı etkinleştir",
  "Generate setup key": "Kurulum anahtarı oluştur",
  "Two-factor authentication is active.": "İki faktörlü kimlik doğrulama etkin.",
  "recovery codes remain.": "kurtarma kodu kaldı.",
  "Staff cannot disable their own authenticator. This prevents accidental production lockout weakening.": "Personel kendi kimlik doğrulayıcısını devre dışı bırakamaz. Bu, üretim erişimi korumasının yanlışlıkla zayıflatılmasını önler.",
  "Continue to Django Admin": "Django Admin’e devam et",
  "Replace recovery codes": "Kurtarma kodlarını yenile",
  "Store these recovery codes now": "Bu kurtarma kodlarını şimdi saklayın",
  "Each code works once. They will not be shown again.": "Her kod bir kez kullanılabilir. Kodlar tekrar gösterilmeyecek.",
  "Active sessions": "Etkin oturumlar",
  "Loading sessions.": "Oturumlar yükleniyor.",
  "No active sessions are available. Sign in again if your session expired.": "Etkin oturum yok. Oturumunuzun süresi dolduysa tekrar giriş yapın.",
  "This session": "Bu oturum",
  "Unknown browser": "Bilinmeyen tarayıcı",
  "started": "başlangıç",
  "Revoke session: ": "Oturumu iptal et: ",
  "Revoke": "İptal et",
  "Sign out every session, including this one?": "Bu oturum dahil tüm oturumlardan çıkılsın mı?",
  "Confirm sign out everywhere": "Tüm oturumlardan çıkışı onayla",
  "Cancel": "İptal",
  "Sign out everywhere": "Tüm oturumlardan çık",
  "Retry loading sessions": "Oturumları yüklemeyi yeniden dene",
  "Leaving and account closure": "Ayrılma ve hesap kapatma",
  "Export your own account details separately from organization project data. The private account file includes your saved email identities, current organization memberships and bounded session/mail diagnostics; it excludes credentials and other members' content. Re-enter your password before downloading it.": "Kendi hesap bilgilerinizi kuruluşun proje verilerinden ayrı dışa aktarın. Özel hesap dosyası kayıtlı e-posta kimliklerinizi, mevcut kuruluş üyeliklerinizi ve sınırlı oturum/e-posta tanılama bilgilerini içerir; kimlik bilgilerini ve diğer üyelerin içeriğini içermez. İndirmeden önce parolanızı tekrar girin.",
  "Download personal account JSON": "Kişisel hesap JSON dosyasını indir",
  "Leave organizations from the workspace. A last active owner must transfer ownership or close the organization first; leaving never deletes another member's projects.": "Kuruluşlardan çalışma alanında ayrılabilirsiniz. Son etkin sahip önce sahipliği devretmeli veya kuruluşu kapatmalıdır; ayrılmak başka bir üyenin projelerini silmez.",
  "Closing your account disables login and every session immediately. Your email/automatic-trial eligibility and restricted audit identity remain under a separate reviewed erasure policy; this does not erase another member's project or all copies from backups. You cannot sign in again after confirmation.": "Hesabınızı kapatmak giriş erişimini ve tüm oturumları hemen devre dışı bırakır. E-posta/otomatik deneme uygunluğunuz ve kısıtlı denetim kimliğiniz ayrı, incelenmiş bir silme politikası kapsamında tutulur; bu işlem başka bir üyenin projesini veya yedeklerdeki tüm kopyaları silmez. Onaydan sonra tekrar giriş yapamazsınız.",
  "I understand account access ends now and restricted identity is not yet erased.": "Hesap erişiminin şimdi sona ereceğini ve kısıtlı kimliğin henüz silinmediğini anlıyorum.",
  "Permanently close personal access": "Kişisel erişimi kalıcı olarak kapat",
  "Leave or close active organizations before personal closure.": "Kişisel hesabınızı kapatmadan önce etkin kuruluşlardan ayrılın veya onları kapatın.",
  "Self-service account closure is release-gated.": "Kendi hesabınızı kapatma özelliği yayın onayını bekliyor.",
  "Review organization ownership": "Kuruluş sahipliğini incele",
  "Personal access closed; all sessions are invalid. Restricted identity is retained for review and no other organization content was deleted.": "Kişisel erişim kapatıldı; tüm oturumlar geçersiz. Kısıtlı kimlik inceleme için tutuluyor ve başka kuruluş içeriği silinmedi.",
  "Personal closure outcome unavailable. Do not retry until you verify whether your session is still active.": "Kişisel hesap kapatma sonucu alınamıyor. Oturumunuzun hâlâ etkin olup olmadığını doğrulamadan tekrar denemeyin.",
  "Personal account download requested. Your browser saves the JSON file; a refused request displays an error. Organization customer content requires an owner-scoped export.": "Kişisel hesap indirmesi istendi. Tarayıcınız JSON dosyasını kaydeder; reddedilen istek hata gösterir. Kuruluşun müşteri içeriği için sahip yetkisiyle dışa aktarım gerekir.",
  "Personal account export is unavailable. Recheck your password and session, then retry.": "Kişisel hesap dışa aktarımı kullanılamıyor. Parolanızı ve oturumunuzu kontrol edip tekrar deneyin.",
  "Language preference saved. Critical emails use unreviewed Turkish drafts in local development.": "Dil tercihi kaydedildi. Önemli e-postalar yerel geliştirmede incelenmemiş Türkçe taslaklar kullanır.",
  "Language preference saved. Account emails still display in English.": "Dil tercihi kaydedildi. Hesap e-postaları hâlâ İngilizcedir.",
  "Your language preference could not be saved. Try again.": "Dil tercihiniz kaydedilemedi. Tekrar deneyin.",
  "Two-factor authentication status is temporarily unavailable. Refresh and try again.": "İki faktörlü kimlik doğrulama durumu geçici olarak kullanılamıyor. Sayfayı yenileyip tekrar deneyin.",
  "The setup key could not be generated. Refresh and try again.": "Kurulum anahtarı oluşturulamadı. Sayfayı yenileyip tekrar deneyin.",
  "The authenticator code was not accepted. Check it and try again.": "Kimlik doğrulama kodu kabul edilmedi. Kontrol edip tekrar deneyin.",
  "Two-factor authentication is active. Other sessions were revoked.": "İki faktörlü kimlik doğrulama etkin. Diğer oturumlar iptal edildi.",
  "Two-factor authentication could not be activated. Try again.": "İki faktörlü kimlik doğrulama etkinleştirilemedi. Tekrar deneyin.",
  "Recovery codes were not changed. Check your password and try again.": "Kurtarma kodları değiştirilmedi. Parolanızı kontrol edip tekrar deneyin.",
  "Previous recovery codes were replaced and other sessions were revoked.": "Önceki kurtarma kodları yenilendi ve diğer oturumlar iptal edildi.",
  "Recovery codes could not be replaced. Try again.": "Kurtarma kodları yenilenemedi. Tekrar deneyin.",
  "Password change failed. Check your current password and the new password requirements.": "Parola değiştirilemedi. Mevcut parolanızı ve yeni parola gereksinimlerini kontrol edin.",
  "Password change is temporarily unavailable. Try again.": "Parola değiştirme geçici olarak kullanılamıyor. Tekrar deneyin.",
  "Email change failed. Check your current password and try again.": "E-posta değiştirilemedi. Mevcut parolanızı kontrol edip tekrar deneyin.",
  "Check the new address for a verification link. Your current sign-in email is unchanged until verification.": "Doğrulama bağlantısı için yeni adresinizi kontrol edin. Doğrulamaya kadar mevcut giriş e-postanız değişmez.",
  "Email change failed. Check the address and try again.": "E-posta değiştirilemedi. Adresi kontrol edip tekrar deneyin.",
  "Email change is temporarily unavailable. Try again.": "E-posta değiştirme geçici olarak kullanılamıyor. Tekrar deneyin.",
  "The selected session was revoked.": "Seçilen oturum iptal edildi.",
  "The session could not be revoked. Refresh and try again.": "Oturum iptal edilemedi. Sayfayı yenileyip tekrar deneyin.",
  "Sessions may still be active. Refresh and try again.": "Oturumlar hâlâ etkin olabilir. Sayfayı yenileyip tekrar deneyin.",
  "Your session expired. Sign in again to manage account security.": "Oturumunuzun süresi doldu. Hesap güvenliğini yönetmek için tekrar giriş yapın.",
  "Sessions are temporarily unavailable. Refresh and try again.": "Oturumlar geçici olarak kullanılamıyor. Sayfayı yenileyip tekrar deneyin.",
  "Unreviewed Turkish Security draft in local development. Remaining application areas remain English; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe Güvenlik taslağı. Uygulamanın kalan bölümleri İngilizcedir; iki dilde onay bekleniyor."
} as const;
type SecurityText = keyof typeof securityTurkish;
