import { Component, Input, OnChanges, OnDestroy, signal, SimpleChanges } from '@angular/core';
import { draftProductLanguage } from '../product-language';
import { AccountApi } from '../account/account-api';
import { microseconds } from './utc-date';

type JobReference = { id: number; status: string; created_at: string; updated_at: string };
type Reference = { method_version: string; project_id: number; scope: string; state: string; job: JobReference | null };
const statuses = ['queued', 'running', 'waiting_provider', 'succeeded', 'failed', 'cancelled', 'partially_succeeded'];

@Component({
  selector: 'app-project-job-reference',
  template: `
    <section [attr.lang]="uiLanguage()" aria-labelledby="job-reference-title">
      <h2 id="job-reference-title">{{ t("Inspect a minimized project job reference") }}</h2>
      <p>{{ t("Use a job ID already obtained from this project. Inspection reads retained operational status and original record dates only, without customer inputs, outputs, raw errors or logs. Current project access is required.") }}</p>
      <p>{{ t("This does not submit a support request, send mail, retry a job or collect new sources. A job status is not an SEO outcome; the last record update is not proof of completion or incident time.") }}</p>
      <form (submit)="inspect($event)">
        <label for="support-job-id">{{ t("Retained job ID in this project") }}</label>
        <input id="support-job-id" name="job_id" inputmode="numeric" pattern="[1-9][0-9]{0,15}" maxlength="16" required
          [value]="jobId()" (input)="edit($any($event.target).value)" />
        <button type="submit" [disabled]="busy()">{{ t("Inspect / refresh this job reference") }}</button>
      </form>
      @if (busy()) { <p role="status">{{ t("Checking the selected retained project job reference.") }}</p> }
      @if (error()) { <p role="alert">{{ t(error()) }}</p> }
      @if (reference(); as retained) {
        @if (retained.job; as row) {
          <p>{{ t("Job reference") }} {{ row.id }} · {{ t("operational status") }} <span lang="en">{{ row.status.replaceAll('_', ' ') }}</span>.</p>
          <dl><dt>{{ t("Original job record creation (UTC)") }}</dt><dd>{{ row.created_at }}</dd>
            <dt>{{ t("Last job record update (UTC), not completion time") }}</dt><dd>{{ row.updated_at }}</dd></dl>
        } @else {
          <p role="status">{{ t("No retained job reference is available in this project for that ID. Missing history does not mean a successful job or a zero SEO result.") }}</p>
        }
      }
    </section>
  `,
  styles: `section { margin-block: 1.2rem; border-top: 1px solid #b9cfd5; }
    form { display: grid; gap: 0.6rem; max-width: 36rem; } p, dd { overflow-wrap: anywhere; }`,
})
export class ProjectJobReference implements OnChanges, OnDestroy {
  @Input() organizationId = 0;
  @Input() projectId = 0;
  @Input() language: 'en' | 'tr' = 'en';
  uiLanguage() { return draftProductLanguage(this.language); }
  t(text: string) { return this.uiLanguage() === 'tr' ? jobReferenceTurkish[text] ?? text : text; }
  readonly jobId = signal('');
  readonly reference = signal<Reference | null>(null);
  readonly busy = signal(false);
  readonly error = signal('');
  private generation = 0;

  constructor(private readonly api: AccountApi) {}
  ngOnChanges(changes?: SimpleChanges) {
    if (!changes || changes['organizationId'] || changes['projectId']) this.edit('');
  }
  ngOnDestroy() { this.edit(''); }

  edit(value: string) {
    this.generation++; this.jobId.set(value); this.reference.set(null); this.error.set(''); this.busy.set(false);
  }

  async inspect(event?: Event) {
    event?.preventDefault();
    const generation = ++this.generation, organization = this.organizationId, project = this.projectId, input = this.jobId();
    this.reference.set(null); this.error.set(''); this.busy.set(false);
    const job = /^[1-9]\d{0,15}$/.test(input) ? Number(input) : NaN;
    if (![organization, project, job].every(value => Number.isSafeInteger(value) && value > 0)) {
      this.error.set('Choose an authorized project and one exact positive job ID before inspecting.'); return;
    }
    const current = () => generation === this.generation && organization === this.organizationId
      && project === this.projectId && input === this.jobId();
    this.busy.set(true);
    try {
      const result = await this.api.projectSupportJobReference(organization, project, job);
      if (!current()) return;
      const retained = result.status === 200 ? readReference(result.body, project, job) : null;
      if (!retained) throw new Error();
      this.reference.set(retained);
    } catch { if (current()) this.error.set('The selected job reference is unavailable. No support request, send or retry was requested.'); }
    finally { if (current()) this.busy.set(false); }
  }
}

function readReference(body: Record<string, unknown>, project: number, job: number): Reference | null {
  if (Object.keys(body).sort().join(',') !== 'job,method_version,project_id,scope,state' || body['project_id'] !== project
      || body['method_version'] !== 'retained-project-job-support-reference-v1'
      || body['scope'] !== 'retained_operational_job_reference_not_completion_incident_seo_outcome_or_retry_authority') return null;
  if (body['state'] === 'unavailable_no_retained_project_job') return body['job'] === null ? structuredClone(body) as Reference : null;
  const row = body['job'];
  if (body['state'] !== 'retained_job_reference' || !row || typeof row !== 'object' || Array.isArray(row)) return null;
  const value = row as Record<string, unknown>;
  if (Object.keys(value).sort().join(',') !== 'created_at,id,status,updated_at' || value['id'] !== job
      || typeof value['status'] !== 'string' || !statuses.includes(value['status'])) return null;
  const created = microseconds(value['created_at']), updated = microseconds(value['updated_at']);
  if (created === null || updated === null || updated < created) return null;
  return structuredClone(body) as Reference;
}

const jobReferenceTurkish: Readonly<Record<string, string>> = {
  "Inspect a minimized project job reference": "Asgari proje iş referansını inceleyin",
  "Use a job ID already obtained from this project. Inspection reads retained operational status and original record dates only, without customer inputs, outputs, raw errors or logs. Current project access is required.": "Bu projeden zaten alınmış bir iş kimliği kullanın. İnceleme yalnızca saklanmış operasyonel durumu ve özgün kayıt tarihlerini okur; müşteri girdileri, çıktılar, ham hatalar veya günlükler dahil değildir. Güncel proje erişimi gerekir.",
  "This does not submit a support request, send mail, retry a job or collect new sources. A job status is not an SEO outcome; the last record update is not proof of completion or incident time.": "Bu işlem destek talebi göndermez, e-posta göndermez, işi yeniden denemez veya yeni kaynak toplamaz. İş durumu bir SEO sonucu değildir; son kayıt güncellemesi tamamlanma veya olay zamanının kanıtı değildir.",
  "Retained job ID in this project": "Bu projedeki saklanmış iş kimliği",
  "Inspect / refresh this job reference": "Bu iş referansını incele / yenile",
  "Checking the selected retained project job reference.": "Seçili saklanmış proje iş referansı kontrol ediliyor.",
  "Job reference": "İş referansı",
  "operational status": "operasyonel durum",
  "Original job record creation (UTC)": "Özgün iş kaydı oluşturulma zamanı (UTC)",
  "Last job record update (UTC), not completion time": "Son iş kaydı güncellemesi (UTC), tamamlanma zamanı değildir",
  "No retained job reference is available in this project for that ID. Missing history does not mean a successful job or a zero SEO result.": "Bu projede bu kimlik için saklanmış iş referansı yok. Eksik geçmiş, başarılı iş veya sıfır SEO sonucu anlamına gelmez.",
  "Choose an authorized project and one exact positive job ID before inspecting.": "İncelemeden önce yetkili olduğunuz bir proje ve tek bir tam pozitif iş kimliği seçin.",
  "The selected job reference is unavailable. No support request, send or retry was requested.": "Seçili iş referansı kullanılamıyor. Destek talebi, gönderim veya yeniden deneme istenmedi."
};
