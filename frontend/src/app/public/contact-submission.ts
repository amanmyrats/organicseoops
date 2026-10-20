import { isPlatformBrowser } from '@angular/common';
import { Component, HostListener, Input, OnChanges, OnDestroy, PLATFORM_ID, inject, signal } from '@angular/core';

type Command = { request_key: string; category: string; language: 'en' | 'tr'; reply_email: string;
  question: string; no_sensitive_data: true };
const scope = 'stored_contact_not_email_delivery_or_staff_response';
const record = (value: unknown): Record<string, unknown> | null => value !== null
  && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;

@Component({
  selector: 'app-contact-submission',
  template: `
    <section [attr.lang]="language" aria-labelledby="contact-intake-title">
      <h2 id="contact-intake-title">{{ t('Configured local contact test') }}</h2>
      <p>{{ t('Use synthetic details only in this development preview. Intake is disabled until reviewed retention is configured. Stored does not mean email delivery, verified identity, staff response or a response-time promise. No attachment is accepted.') }}</p>
      <p role="status" aria-live="polite">{{ t(status()) }}</p>
      @if (state() === 'idle') {
        <button type="button" [disabled]="busy()" (click)="open()">{{ t('Check configured local intake') }}</button>
      }
      @if (state() === 'ready' || state() === 'uncertain') {
        <form #form (submit)="$event.preventDefault(); submit(form)">
          <fieldset [disabled]="busy() || state() !== 'ready'">
            <legend>{{ t('One safe contact question') }}</legend>
            <label for="contact-category">{{ t('Category') }}</label>
            <select id="contact-category" name="category" required>
              <option value="sales">{{ t('Sales') }}</option><option value="support">{{ t('Support') }}</option>
              <option value="privacy">{{ t('Privacy') }}</option><option value="accessibility">{{ t('Accessibility') }}</option>
            </select>
            <label for="contact-email">{{ t('Reply email (unverified)') }}</label>
            <input id="contact-email" name="reply_email" type="email" maxlength="254" autocomplete="email" required>
            <label for="contact-question">{{ t('Plain-text question (up to 2,000 characters)') }}</label>
            <textarea id="contact-question" name="question" maxlength="2000" required></textarea>
            <label><input name="no_sensitive_data" type="checkbox" required>
              {{ t('I want to store this question and confirm it contains no passwords, keys, tokens, customer details, raw logs or private exports.') }}</label>
            <button type="submit">{{ t('Store this contact question once') }}</button>
          </fieldset>
        </form>
      }
      @if (state() === 'uncertain') {
        <p>{{ t('The original question and key are held only in this page memory. Nothing is retried automatically. Leaving clears local details; a stored request may remain. Do not start a duplicate with a new key.') }}</p>
        <button type="button" [disabled]="busy()" (click)="inspect()">{{ t('Check own original receipt') }}</button>
        @if (absent()) {
          <button type="button" [disabled]="busy()" (click)="retry()">{{ t('Explicitly retry unchanged question and key') }}</button>
        }
      }
    </section>
  `,
  styles: `
    section { border-top: 1px solid #b9cfd5; padding-block: 1rem; }
    fieldset { display: grid; gap: .75rem; min-width: 0; }
    input, select, textarea, button { font: inherit; max-width: 100%; }
    textarea { min-height: 8rem; }
    button { margin-block: .5rem; }
  `,
})
export class ContactSubmission implements OnChanges, OnDestroy {
  @Input() language: 'en' | 'tr' = 'en';
  readonly state = signal<'idle' | 'ready' | 'uncertain' | 'stored' | 'expired'>('idle');
  readonly busy = signal(false);
  readonly absent = signal(false);
  readonly status = signal('Local intake has not been opened.');
  private readonly browser = isPlatformBrowser(inject(PLATFORM_ID));
  private context: { csrf: string; scope: string; deadline: number } | null = null;
  private command: Command | null = null;
  private generation = 0;
  t(text: string) { return this.language === 'tr' ? turkish[text] ?? text : text; }

  ngOnChanges() { this.clear(); }
  ngOnDestroy() { this.clear(); }
  @HostListener('window:pagehide') clear() {
    this.generation++; this.context = null; this.command = null;
    this.state.set('idle'); this.busy.set(false); this.absent.set(false);
    this.status.set('Local intake has not been opened.');
  }

  private async request(action: 'csrf' | 'create' | 'receipt', body?: unknown) {
    const result = await fetch(`/api/public-contact/${action}/`, {
      method: action === 'csrf' ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store',
      redirect: 'error', referrerPolicy: 'no-referrer', signal: AbortSignal.timeout(10_000),
      ...(body === undefined ? {} : { body: JSON.stringify(body), headers: {
        'Content-Type': 'application/json', 'X-CSRFToken': this.context?.csrf ?? '',
        'X-Contact-Scope': this.context?.scope ?? '',
      } }),
    });
    if (!result.ok) throw new Error();
    return record(await result.json());
  }

  async open() {
    if (!this.browser || this.busy() || this.state() !== 'idle') return;
    const generation = this.generation;
    this.busy.set(true);
    try {
      const result = await this.request('csrf');
      if (generation !== this.generation) return;
      if (!result || Object.keys(result).length !== 3 || typeof result['csrfToken'] !== 'string'
          || !/^[A-Za-z0-9]{64}$/.test(result['csrfToken']) || typeof result['scope_hint'] !== 'string'
          || !/^[0-9a-f]{64}$/.test(result['scope_hint']) || !Number.isSafeInteger(result['expires_at'])
          || (result['expires_at'] as number) * 1000 <= Date.now()) throw new Error();
      this.context = { csrf: result['csrfToken'], scope: result['scope_hint'], deadline: (result['expires_at'] as number) * 1000 };
      this.state.set('ready'); this.status.set('Configured local intake is open for this original browser scope.');
    } catch {
      if (generation === this.generation) this.status.set('Local intake is unavailable or unconfigured. No question was submitted.');
    } finally { if (generation === this.generation) this.busy.set(false); }
  }

  async submit(form: HTMLFormElement) {
    if (this.busy() || this.state() !== 'ready' || !this.current() || !form.reportValidity()) return;
    const values = new FormData(form);
    this.command = { request_key: crypto.randomUUID(), category: String(values.get('category')),
      language: this.language, reply_email: String(values.get('reply_email')), question: String(values.get('question')),
      no_sensitive_data: true };
    this.state.set('uncertain'); this.absent.set(false);
    await this.send();
  }

  private current() {
    if (this.context && Date.now() < this.context.deadline) return true;
    this.context = null; this.command = null; this.absent.set(false); this.state.set('expired');
    this.status.set('Original browser scope expired or unavailable. No automatic renewal or retry; a stored record may remain.');
    return false;
  }

  private received(value: unknown) {
    const row = record(value), keys = ['request_key', 'status', 'created_at', 'expires_at', 'scope'];
    if (!row || Object.keys(row).length !== keys.length || !keys.every(key => key in row)
        || row['request_key'] !== this.command?.request_key || row['status'] !== 'received' || row['scope'] !== scope
        || typeof row['created_at'] !== 'string' || typeof row['expires_at'] !== 'string') throw new Error();
    const created = Date.parse(row['created_at']), expires = Date.parse(row['expires_at']);
    if (!Number.isFinite(created) || !Number.isFinite(expires) || created > Date.now()
        || expires <= created || expires <= Date.now()) throw new Error();
    this.command = null; this.absent.set(false); this.state.set('stored');
    this.status.set('Received means stored only. Reply email is unverified; delivery and staff response are not confirmed.');
  }

  private async send() {
    if (!this.command || !this.current()) return;
    const generation = this.generation;
    this.busy.set(true); this.absent.set(false);
    try {
      const result = await this.request('create', this.command);
      if (generation === this.generation && this.current()) this.received(result);
    } catch {
      if (generation === this.generation && this.current())
        this.status.set('Submission is uncertain. Check own original receipt before any explicit unchanged retry.');
    } finally { if (generation === this.generation) this.busy.set(false); }
  }

  async inspect() {
    if (this.busy() || this.state() !== 'uncertain' || !this.command || !this.current()) return;
    const generation = this.generation;
    this.busy.set(true); this.absent.set(false);
    try {
      const result = await this.request('receipt', { request_key: this.command.request_key });
      if (generation !== this.generation || !this.current()) return;
      if (!result || Object.keys(result).length !== 1 || !('receipt' in result)) throw new Error();
      if (result['receipt'] === null) {
        this.absent.set(true); this.status.set('No stored receipt found in the original browser scope. An explicit unchanged retry is available.');
      } else this.received(result['receipt']);
    } catch {
      if (generation === this.generation && this.current())
        this.status.set('Own receipt is unavailable or unconfirmed. No submission was retried.');
    } finally { if (generation === this.generation) this.busy.set(false); }
  }

  async retry() {
    if (!this.busy() && this.state() === 'uncertain' && this.absent() && this.current()) await this.send();
  }
}

const turkish: Record<string, string> = {
  'Configured local contact test': 'Yapılandırılmış yerel iletişim testi',
  'Use synthetic details only in this development preview. Intake is disabled until reviewed retention is configured. Stored does not mean email delivery, verified identity, staff response or a response-time promise. No attachment is accepted.': 'Bu geliştirme ön izlemesinde yalnızca sentetik bilgiler kullanın. İncelenmiş saklama süresi yapılandırılana kadar gönderim kapalıdır. Kaydedilmiş durum e-posta teslimatı, doğrulanmış kimlik, personel yanıtı veya yanıt süresi taahhüdü değildir. Ek kabul edilmez.',
  'Check configured local intake': 'Yapılandırılmış yerel gönderimi kontrol et',
  'One safe contact question': 'Tek bir güvenli iletişim sorusu',
  'Category': 'Kategori', 'Sales': 'Satış', 'Support': 'Destek', 'Privacy': 'Gizlilik', 'Accessibility': 'Erişilebilirlik',
  'Reply email (unverified)': 'Yanıt e-postası (doğrulanmamış)',
  'Plain-text question (up to 2,000 characters)': 'Düz metin soru (en fazla 2.000 karakter)',
  'I want to store this question and confirm it contains no passwords, keys, tokens, customer details, raw logs or private exports.': 'Bu soruyu saklamak istiyorum ve parola, anahtar, belirteç, müşteri bilgisi, ham günlük veya özel dışa aktarım içermediğini onaylıyorum.',
  'Store this contact question once': 'Bu iletişim sorusunu bir kez kaydet',
  'The original question and key are held only in this page memory. Nothing is retried automatically. Leaving clears local details; a stored request may remain. Do not start a duplicate with a new key.': 'Özgün soru ve anahtar yalnızca bu sayfanın belleğinde tutulur. Hiçbir şey otomatik yeniden denenmez. Sayfadan ayrılmak yerel bilgileri temizler; kaydedilmiş talep kalabilir. Yeni anahtarla yinelenen talep başlatmayın.',
  'Check own original receipt': 'Kendi özgün alındı kaydını kontrol et',
  'Explicitly retry unchanged question and key': 'Değişmemiş soruyu ve anahtarı açıkça yeniden dene',
  'Local intake has not been opened.': 'Yerel gönderim açılmadı.',
  'Configured local intake is open for this original browser scope.': 'Yapılandırılmış yerel gönderim bu özgün tarayıcı kapsamı için açık.',
  'Local intake is unavailable or unconfigured. No question was submitted.': 'Yerel gönderim kullanılamıyor veya yapılandırılmamış. Hiçbir soru gönderilmedi.',
  'Original browser scope expired or unavailable. No automatic renewal or retry; a stored record may remain.': 'Özgün tarayıcı kapsamı sona erdi veya kullanılamıyor. Otomatik yenileme veya yeniden deneme yok; kaydedilmiş kayıt kalabilir.',
  'Received means stored only. Reply email is unverified; delivery and staff response are not confirmed.': 'Alındı durumu yalnızca kaydedildi demektir. Yanıt e-postası doğrulanmamış; teslimat ve personel yanıtı doğrulanmadı.',
  'Submission is uncertain. Check own original receipt before any explicit unchanged retry.': 'Gönderim belirsiz. Değişmemiş gönderimi açıkça yeniden denemeden önce kendi özgün alındı kaydını kontrol edin.',
  'No stored receipt found in the original browser scope. An explicit unchanged retry is available.': 'Özgün tarayıcı kapsamında saklanan alındı kaydı bulunamadı. Değişmemiş gönderimi açıkça yeniden denemek mümkün.',
  'Own receipt is unavailable or unconfirmed. No submission was retried.': 'Kendi alındı kaydı kullanılamıyor veya doğrulanmadı. Hiçbir gönderim yeniden denenmedi.',
};
