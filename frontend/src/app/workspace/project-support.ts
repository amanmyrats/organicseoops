import { Component, HostListener, Input, OnChanges, OnDestroy, signal, SimpleChanges } from '@angular/core';
import { draftProductLanguage } from '../product-language';
import { AccountApi } from '../account/account-api';
import { microseconds } from './utc-date';

type Summary = { id: number; category: string; job_id: number | null; created_at: string; status: string; revision: number };
type Detail = Summary & { question: string; updates: { revision: number; status: string; response: string; created_at: string }[]; updates_has_more: boolean };
type Command = { request_key: string; category: string; question: string; job_id: number | null; no_sensitive_data: true; expected_actor_id: number };
const categories = ['job', 'account_billing', 'data_sources', 'accessibility', 'other'];
const statuses = ['received', 'in_progress', 'resolved'];
const scope = 'own_retained_support_records_not_email_delivery_staff_response_or_job_access_authority';

@Component({
  selector: 'app-project-support',
  template: `
    <section [attr.lang]="uiLanguage()" aria-labelledby="support-title">
      <h2 id="support-title">{{ t("Your private project support requests") }}</h2>
      <p>{{ t("Only you, while you have current project access, and explicitly permitted MFA-authenticated support staff can inspect your request. The organization owner can include it in a customer export. Do not include credentials, personal customer details, logs or copied exports. Attachments and automatic email delivery are unavailable.") }}</p>
      <p>{{ t("Received means stored as a support record. It is not a staff response, email delivery or promised response time. A support status does not retry a job or fix a website.") }}</p>
      <form (submit)="submit($event)">
        <label for="support-category">{{ t("Question category") }}</label>
        <select id="support-category" name="category" [value]="category()" [disabled]="busy() || !!pending()" (change)="edit('category', $any($event.target).value)">
          @for (value of categories; track value) { <option [value]="value" [selected]="value === category()">{{ t(value.replaceAll('_', ' ')) }}</option> }
        </select>
        <label for="support-question">{{ t("Plain-text question (up to 2,000 characters; no sensitive data)") }}</label>
        <textarea lang="" id="support-question" name="question" rows="5" maxlength="2000" required [value]="question()" [disabled]="busy() || !!pending()" (input)="edit('question', $any($event.target).value)"></textarea>
        <label for="support-request-job">{{ t("Optional retained job ID in this project") }}</label>
        <input id="support-request-job" name="job" inputmode="numeric" pattern="[1-9][0-9]{0,15}" maxlength="16" [value]="job()" [disabled]="busy() || !!pending()" (input)="edit('job', $any($event.target).value)" />
        <label><input type="checkbox" name="declaration" [checked]="declared()" [disabled]="busy() || !!pending()" (change)="edit('declaration', $any($event.target).checked)" /> {{ t("I confirm this question contains no sensitive data and I want to store it in this project's support records.") }}</label>
        @if (!pending()) { <button type="submit" [disabled]="busy()">{{ t("Submit this support request once") }}</button> }
      </form>
      <button type="button" [disabled]="busy()" (click)="refresh()">{{ t("Inspect / refresh your request history") }}</button>
      @if (pending()) {
        <p role="status">{{ t("Submission is not confirmed. The original command and key are held only in this page's memory. Refresh current own history; nothing is retried automatically.") }}</p>
        <button type="button" [disabled]="busy() || !retryReady()" (click)="retry()">{{ t("Explicitly retry the unchanged request and key") }}</button>
        <button type="button" [disabled]="busy()" (click)="discard()">{{ t("Discard local uncertain command (stored records remain)") }}</button>
      }
      @if (busy()) { <p role="status">{{ t("Checking current private support context.") }}</p> }
      @if (error()) { <p role="alert">{{ t(error()) }}</p> }
      @if (history(); as retained) {
        @if (!retained.length) { <p>{{ t("No retained requests of yours in this project.") }}</p> }
        <ul>@for (row of retained; track row.id) {
          <li>{{ t("Request") }} {{ row.id }} · <span>{{ t(row.category.replaceAll('_', ' ')) }}</span> · <span>{{ t(row.status.replaceAll('_', ' ')) }}</span> · {{ t("created") }} {{ row.created_at }} (UTC).
            <button type="button" [disabled]="busy()" (click)="inspect(row.id)">{{ t("Inspect request") }} {{ row.id }} {{ t("and responses") }}</button></li>
        }</ul>
        @if (hasMore()) { <p>{{ t("Only your newest twenty requests are shown. Earlier retained records remain available through exact authorized IDs and the organization owner's export.") }}</p> }
      }
      @if (detail(); as row) {
        <h3>{{ t("Request") }} {{ row.id }} · <span>{{ t(row.status.replaceAll('_', ' ')) }}</span> · {{ t("revision") }} {{ row.revision }}</h3>
        <pre lang="">{{ row.question }}</pre>
        @if (row.job_id !== null) { <p>{{ t("Minimized job reference") }} {{ row.job_id }}; {{ t("no detailed job payload was copied.") }}</p> }
        @for (update of row.updates; track update.revision) {
          <p>{{ t("Staff response revision") }} {{ update.revision }} · <span>{{ t(update.status.replaceAll('_', ' ')) }}</span> · {{ update.created_at }} (UTC).</p><pre lang="">{{ update.response }}</pre>
        } @empty { <p>{{ t("No retained staff response yet.") }}</p> }
        @if (row.updates_has_more) { <p>{{ t("Only the newest twenty responses are shown. Earlier retained history remains in the owner's export.") }}</p> }
      }
    </section>
  `,
  styles: `section { margin-block:1.2rem; border-top:1px solid #b9cfd5; } form { display:grid; gap:0.6rem; max-width:40rem; }
    textarea { box-sizing:border-box; width:100%; } p, li, pre { overflow-wrap:anywhere; } pre { white-space:pre-wrap; } button { margin:0.4rem; }`,
})
export class ProjectSupport implements OnChanges, OnDestroy {
  @Input() organizationId = 0;
  @Input() projectId = 0;
  @Input() language: 'en' | 'tr' = 'en';
  uiLanguage() { return draftProductLanguage(this.language); }
  t(text: string) { return this.uiLanguage() === 'tr' ? supportTurkish[text] ?? text : text; }
  readonly categories = categories;
  readonly category = signal('other'); readonly question = signal(''); readonly job = signal(''); readonly declared = signal(false);
  readonly history = signal<Summary[] | null>(null); readonly hasMore = signal(false); readonly detail = signal<Detail | null>(null);
  readonly busy = signal(false); readonly error = signal(''); readonly pending = signal<Command | null>(null); readonly retryReady = signal(false);
  private generation = 0;
  private actor = 0;
  private pendingScope: [number, number] | null = null;
  constructor(private readonly api: AccountApi) {}
  ngOnChanges(changes?: SimpleChanges) {
    if (!changes || changes['organizationId'] || changes['projectId']) this.clear();
  }
  ngOnDestroy() { this.clear(); }
  @HostListener('window:pagehide') hide() { this.clear(); }
  @HostListener('document:visibilitychange') visibility() { if (document.hidden) this.clear(); }

  private clear() {
    this.generation++; this.actor = 0; this.pendingScope = null; this.category.set('other'); this.question.set(''); this.job.set(''); this.declared.set(false);
    this.history.set(null); this.hasMore.set(false); this.detail.set(null); this.busy.set(false); this.error.set(''); this.pending.set(null); this.retryReady.set(false);
  }
  discard() { this.clear(); this.error.set('Local uncertain command discarded. A stored request may still exist; inspect current own history before starting another.'); }
  edit(field: 'category' | 'question' | 'job' | 'declaration', value: string | boolean) {
    if (this.pending()) return;
    this.generation++; this.detail.set(null); this.history.set(null); this.error.set(''); this.busy.set(false); this.retryReady.set(false);
    if (field === 'declaration') this.declared.set(value === true);
    else { this[field].set(String(value)); if (field === 'question' || field === 'job' || field === 'category') this.declared.set(false); }
  }
  private validScope() { return [this.organizationId, this.projectId].every(safeId); }
  private begin() {
    const generation = ++this.generation, organization = this.organizationId, project = this.projectId;
    this.detail.set(null); this.error.set(''); this.retryReady.set(false); this.busy.set(true);
    return { organization, project, current: () => generation === this.generation && organization === this.organizationId && project === this.projectId };
  }
  private acceptActor(actor: number) {
    if (this.actor && this.actor !== actor || this.pending() && this.pending()!.expected_actor_id !== actor) {
      this.clear(); this.error.set('Account context changed. Previous question and uncertain command were cleared.'); return false;
    }
    this.actor = actor; return true;
  }
  async refresh() {
    if (this.busy()) return;
    this.history.set(null);
    if (!this.validScope()) { this.clear(); this.error.set('Choose an authorized project.'); return; }
    const task = this.begin();
    try {
      const result = await this.api.projectSupportRequests(task.organization, task.project);
      if (!task.current()) return;
      const value = result.status === 200 ? readHistory(result.body, task.project) : null;
      if (!value) throw new Error();
      if (!this.acceptActor(value.actor)) return;
      this.history.set(value.rows); this.hasMore.set(value.more); this.retryReady.set(this.pending() !== null);
    } catch { if (task.current()) this.error.set('Your request history is unavailable. No submission was retried.'); }
    finally { if (task.current()) this.busy.set(false); }
  }
  async inspect(id: number) {
    if (this.busy()) return;
    if (!this.validScope() || !safeId(id)) { this.detail.set(null); this.error.set('Choose an exact authorized request.'); return; }
    const task = this.begin();
    try {
      const result = await this.api.projectSupportRequest(task.organization, task.project, id);
      if (!task.current()) return;
      const value = result.status === 200 ? readDetail(result.body, task.project) : null;
      if (!value || value.row?.id !== id) throw new Error();
      if (!this.acceptActor(value.actor)) return;
      this.detail.set(value.row);
    } catch { if (task.current()) this.error.set('That own request is unavailable in the current project context.'); }
    finally { if (task.current()) this.busy.set(false); }
  }
  async submit(event?: Event) {
    event?.preventDefault();
    if (this.busy() || this.pending()) return;
    const job = this.job() === '' ? null : /^[1-9]\d{0,15}$/.test(this.job()) ? Number(this.job()) : NaN;
    if (!this.validScope() || !categories.includes(this.category()) || !plainText(this.question()) || !this.declared() || job !== null && !safeId(job)) {
      this.error.set('Choose a project, bounded plain-text question/category/optional job and explicitly confirm no sensitive data.'); return;
    }
    const question = this.question(), category = this.category(), task = this.begin();
    try {
      const result = await this.api.projectSupportRequests(task.organization, task.project);
      if (!task.current()) return;
      const value = result.status === 200 ? readHistory(result.body, task.project) : null;
      if (!value) throw new Error();
      if (!this.acceptActor(value.actor)) return;
      const command: Command = { request_key: crypto.randomUUID(), question, category, job_id: job,
        no_sensitive_data: true, expected_actor_id: value.actor };
      this.busy.set(false); await this.send(command);
    } catch { if (task.current()) this.error.set('Current own context is unavailable. No support submission was made.'); }
    finally { if (task.current()) this.busy.set(false); }
  }
  async retry() { if (!this.busy() && this.pending() && this.retryReady()) await this.send(this.pending()!); }
  private async send(command: Command) {
    if (!this.validScope() || this.pendingScope && (this.pendingScope[0] !== this.organizationId || this.pendingScope[1] !== this.projectId)) {
      this.clear(); this.error.set('Project context changed. Previous command cleared.'); return;
    }
    this.pendingScope = [this.organizationId, this.projectId];
    this.pending.set(structuredClone(command)); this.history.set(null);
    const task = this.begin();
    try {
      const result = await this.api.createProjectSupportRequest(task.organization, task.project, structuredClone(command));
      if (!task.current()) return;
      const value = result.status === 200 ? readDetail(result.body, task.project) : null;
      if (!value || value.actor !== command.expected_actor_id || !value.row || value.row.question !== command.question
        || value.row.category !== command.category || value.row.job_id !== command.job_id) throw new Error();
      this.pending.set(null); this.pendingScope = null; this.detail.set(value.row); this.declared.set(false);
    } catch { if (task.current()) this.error.set('Submission not confirmed. Inspect current own history before any explicit unchanged-key retry.'); }
    finally { if (task.current()) this.busy.set(false); }
  }
}

function safeId(value: unknown): value is number { return typeof value === 'number' && Number.isSafeInteger(value) && value > 0; }
function object(value: unknown): value is Record<string, unknown> { return !!value && typeof value === 'object' && !Array.isArray(value); }
function keys(value: Record<string, unknown>, expected: string[]) { return Object.keys(value).sort().join(',') === expected.sort().join(','); }
function plainText(value: unknown): value is string {
  return typeof value === 'string' && !!value.trim() && Array.from(value).length <= 2000 && new TextEncoder().encode(value).length <= 8000
    && !/[\p{Cc}\p{Cf}\p{Cs}]/u.test(value.replaceAll('\n', '').replaceAll('\t', ''));
}
function envelope(body: Record<string, unknown>, project: number) {
  return body['method_version'] === 'own-project-support-request-v2' && body['project_id'] === project && body['scope'] === scope && safeId(body['actor_id']);
}
function readSummary(value: unknown, detail = false): Summary | null {
  if (!object(value) || !keys(value, ['id', 'category', 'job_id', 'created_at', 'status', 'revision',
    ...(detail ? ['question', 'updates', 'updates_has_more'] : [])]) || !safeId(value['id'])
    || typeof value['category'] !== 'string' || !categories.includes(value['category']) || value['job_id'] !== null && !safeId(value['job_id'])
    || typeof value['status'] !== 'string' || !statuses.includes(value['status']) || typeof value['revision'] !== 'number'
    || !Number.isInteger(value['revision']) || value['revision'] < 0 || value['revision'] >= 2 ** 31
    || value['revision'] === 0 && value['status'] !== 'received' || microseconds(value['created_at']) === null) return null;
  return structuredClone(value) as Summary;
}
function readHistory(body: Record<string, unknown>, project: number) {
  if (!keys(body, ['method_version', 'project_id', 'actor_id', 'scope', 'requests', 'has_more']) || !envelope(body, project)
    || !Array.isArray(body['requests']) || body['requests'].length > 20 || typeof body['has_more'] !== 'boolean'
    || body['has_more'] && body['requests'].length !== 20) return null;
  const rows: Summary[] = [];
  for (const value of body['requests']) {
    const row = readSummary(value), previous = rows.at(-1);
    if (!row || rows.some(saved => saved.id === row.id) || previous && (microseconds(row.created_at)! > microseconds(previous.created_at)!
      || microseconds(row.created_at) === microseconds(previous.created_at) && row.id >= previous.id)) return null;
    rows.push(row);
  }
  return { actor: body['actor_id'] as number, rows, more: body['has_more'] };
}
function readDetail(body: Record<string, unknown>, project: number) {
  if (!keys(body, ['method_version', 'project_id', 'actor_id', 'scope', 'request']) || !envelope(body, project)) return null;
  if (body['request'] === null) return { actor: body['actor_id'] as number, row: null };
  const row = readSummary(body['request'], true) as Detail | null;
  if (!row || !plainText(row.question) || !Array.isArray(row.updates) || row.updates.length > 20 || typeof row.updates_has_more !== 'boolean'
    || row.updates_has_more && row.updates.length !== 20 || !row.updates.length && (row.revision !== 0 || row.updates_has_more)) return null;
  let later = null as bigint | null, revision = row.revision;
  for (const update of row.updates) {
    if (!object(update) || !keys(update, ['revision', 'status', 'response', 'created_at']) || update.revision !== revision
      || !Number.isInteger(update.revision) || update.revision < 1 || !statuses.includes(update.status) || !plainText(update.response)) return null;
    const date = microseconds(update.created_at);
    if (date === null || date < microseconds(row.created_at)! || later !== null && date > later) return null;
    later = date; revision--;
  }
  if (row.updates.length && (row.status !== row.updates[0].status || !row.updates_has_more && revision !== 0 || row.updates_has_more && revision < 1)) return null;
  return { actor: body['actor_id'] as number, row };
}

const supportTurkish: Readonly<Record<string, string>> = {
  "job": "İş",
  "account billing": "Hesap ve faturalama",
  "data sources": "Veri kaynakları",
  "accessibility": "Erişilebilirlik",
  "other": "Diğer",
  "received": "Alındı",
  "in progress": "İşlem sürüyor",
  "resolved": "Çözüldü",
  "Your private project support requests": "Özel proje destek talepleriniz",
  "Only you, while you have current project access, and explicitly permitted MFA-authenticated support staff can inspect your request. The organization owner can include it in a customer export. Do not include credentials, personal customer details, logs or copied exports. Attachments and automatic email delivery are unavailable.": "Güncel proje erişiminiz varken yalnızca siz ve açıkça yetkilendirilmiş, MFA ile kimliği doğrulanmış destek personeli talebinizi inceleyebilir. Kuruluş sahibi bunu müşteri dışa aktarımına dahil edebilir. Kimlik bilgileri, müşterilerin kişisel bilgileri, günlükler veya kopyalanmış dışa aktarımlar eklemeyin. Ekler ve otomatik e-posta teslimatı kullanılamıyor.",
  "Received means stored as a support record. It is not a staff response, email delivery or promised response time. A support status does not retry a job or fix a website.": "Alındı durumu, destek kaydı olarak saklandı demektir. Personel yanıtı, e-posta teslimatı veya taahhüt edilmiş yanıt süresi değildir. Destek durumu bir işi yeniden denemez veya web sitesini düzeltmez.",
  "Question category": "Soru kategorisi",
  "Plain-text question (up to 2,000 characters; no sensitive data)": "Düz metin soru (en fazla 2.000 karakter; hassas veri eklemeyin)",
  "Optional retained job ID in this project": "Bu projedeki isteğe bağlı saklanmış iş kimliği",
  "I confirm this question contains no sensitive data and I want to store it in this project's support records.": "Bu sorunun hassas veri içermediğini ve bu projenin destek kayıtlarında saklanmasını istediğimi onaylıyorum.",
  "Submit this support request once": "Bu destek talebini bir kez gönder",
  "Inspect / refresh your request history": "Talep geçmişinizi incele / yenile",
  "Submission is not confirmed. The original command and key are held only in this page's memory. Refresh current own history; nothing is retried automatically.": "Gönderim doğrulanmadı. Özgün komut ve anahtar yalnızca bu sayfanın belleğinde tutulur. Güncel kendi geçmişinizi yenileyin; hiçbir şey otomatik yeniden denenmez.",
  "Explicitly retry the unchanged request and key": "Değişmemiş talebi ve anahtarı açıkça yeniden dene",
  "Discard local uncertain command (stored records remain)": "Yerel belirsiz komutu sil (saklanmış kayıtlar kalır)",
  "Checking current private support context.": "Güncel özel destek bağlamı kontrol ediliyor.",
  "No retained requests of yours in this project.": "Bu projede size ait saklanmış talep yok.",
  "Request": "Talep",
  "created": "oluşturulma",
  "Inspect request": "Talebi incele",
  "and responses": "ve yanıtları",
  "Only your newest twenty requests are shown. Earlier retained records remain available through exact authorized IDs and the organization owner's export.": "Yalnızca en yeni yirmi talebiniz gösteriliyor. Önceki saklanmış kayıtlara tam yetkili kimlikler ve kuruluş sahibinin dışa aktarımı üzerinden erişilebilir.",
  "revision": "sürüm",
  "Minimized job reference": "Asgari iş referansı",
  "no detailed job payload was copied.": "ayrıntılı iş verileri kopyalanmadı.",
  "Staff response revision": "Personel yanıtı sürümü",
  "No retained staff response yet.": "Henüz saklanmış personel yanıtı yok.",
  "Only the newest twenty responses are shown. Earlier retained history remains in the owner's export.": "Yalnızca en yeni yirmi yanıt gösteriliyor. Önceki saklanmış geçmiş, kuruluş sahibinin dışa aktarımında kalır.",
  "Local uncertain command discarded. A stored request may still exist; inspect current own history before starting another.": "Yerel belirsiz komut silindi. Saklanmış bir talep hâlâ var olabilir; başka bir talep başlatmadan önce güncel kendi geçmişinizi inceleyin.",
  "Account context changed. Previous question and uncertain command were cleared.": "Hesap bağlamı değişti. Önceki soru ve belirsiz komut temizlendi.",
  "Choose an authorized project.": "Yetkili olduğunuz bir proje seçin.",
  "Your request history is unavailable. No submission was retried.": "Talep geçmişiniz kullanılamıyor. Hiçbir gönderim yeniden denenmedi.",
  "Choose an exact authorized request.": "Tam yetkili bir talep seçin.",
  "That own request is unavailable in the current project context.": "Bu talebiniz güncel proje bağlamında kullanılamıyor.",
  "Choose a project, bounded plain-text question/category/optional job and explicitly confirm no sensitive data.": "Bir proje, sınırlı düz metin soru, kategori ve isteğe bağlı iş seçin; hassas veri bulunmadığını açıkça onaylayın.",
  "Current own context is unavailable. No support submission was made.": "Güncel kendi bağlamınız kullanılamıyor. Destek talebi gönderilmedi.",
  "Project context changed. Previous command cleared.": "Proje bağlamı değişti. Önceki komut temizlendi.",
  "Submission not confirmed. Inspect current own history before any explicit unchanged-key retry.": "Gönderim doğrulanmadı. Aynı anahtarla açık yeniden denemeden önce güncel kendi geçmişinizi inceleyin."
};
