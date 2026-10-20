import { Title } from '@angular/platform-browser';
import { Component, computed, effect, DestroyRef, ElementRef, inject, OnDestroy, OnInit, signal, ViewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { AccountApi, ApiResult, JobInfo, JobScheduleInfo, JobStepInfo } from '../account/account-api';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';
import { environment } from '../../environments/environment';

const jobDashboardTurkish: Record<string, string> = {
  "Diagnostic jobs": "Tanılama işleri",
  "Diagnostic job progress": "Tanılama işi ilerlemesi",
  "Local development diagnostics": "Yerel geliştirme tanılamaları",
  "Project job progress": "Proje işi ilerlemesi",
  "Return to organization and project context": "Kuruluş ve proje bağlamına dönün",
  "Unreviewed Turkish diagnostic-job interface draft in local development. Job states, UTC dates and technical evidence remain English; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe tanılama işi arayüzü taslağı. İş durumları, UTC tarihleri ve teknik kanıtlar İngilizce kalır; iki dilli onay bekleniyor.",
  "Diagnostic jobs are unavailable here.": "Burada tanılama işleri kullanılamıyor.",
  "Loading authorized project jobs.": "Yetkili proje işleri yükleniyor.",
  "Active project": "Etkin proje",
  "Recent diagnostic jobs": "Son tanılama işleri",
  "No diagnostic jobs for this project yet.": "Bu proje için henüz tanılama işi yok.",
  "Job": "İş",
  "Refresh jobs": "İşleri yenileyin",
  "Only the first 100 recent jobs are shown.": "Yalnızca son 100 iş gösterilir.",
  "Diagnostic schedules": "Tanılama zamanlamaları",
  "Schedules are local-only, cost-free and paused when first created. Missed runs do not accumulate.": "Zamanlamalar yalnızca yereldir, ücretsizdir ve ilk oluşturulduğunda duraklatılır. Kaçırılan çalıştırmalar birikmez.",
  "Schedules are unavailable. Refresh to check their current state.": "Zamanlamalar kullanılamıyor. Güncel durumlarını kontrol etmek için yenileyin.",
  "No diagnostic schedules for this project.": "Bu proje için tanılama zamanlaması yok.",
  "Schedule": "Zamanlama",
  "Enabled": "Etkin",
  "Paused": "Duraklatılmış",
  "· every": "· her",
  "minutes": "dakikada",
  "· next": "· sonraki",
  "· last": "· son",
  "· skipped": "· atlanan",
  "missed runs": "kaçırılmış çalıştırma",
  "· issue": "· sorun",
  "Pause schedule": "Zamanlamayı duraklatın",
  "Enable schedule": "Zamanlamayı etkinleştirin",
  "Only the first 100 recent schedules are shown.": "Yalnızca son 100 zamanlama gösterilir.",
  "Synthetic sample for future runs": "Gelecekteki çalıştırmalar için sentetik örnek",
  "Frequency": "Sıklık",
  "Hourly": "Saatlik",
  "Daily": "Günlük",
  "Weekly": "Haftalık",
  "Save paused schedule": "Duraklatılmış zamanlamayı kaydedin",
  "Run a cost-free diagnostic": "Ücretsiz tanılama çalıştırın",
  "This local check uses synthetic text, no external provider and zero diagnostic units. It does not analyze a website.": "Bu yerel kontrol sentetik metin kullanır; harici sağlayıcı kullanmaz ve sıfır tanılama birimi tüketir. Bir web sitesini analiz etmez.",
  "Short synthetic sample": "Kısa sentetik örnek",
  "Simulate a partial result": "Kısmi sonucu simüle edin",
  "Run diagnostic": "Tanılama çalıştırın",
  "Progress:": "İlerleme:",
  "%. Last updated": "%. Son güncelleme",
  "Waiting for a provider response. Results may be partial.": "Sağlayıcı yanıtı bekleniyor. Sonuçlar kısmi olabilir.",
  "Cancellation requested. A stage may still finish before it stops.": "İptal istendi. Durmadan önce bir aşama tamamlanabilir.",
  "Job issue:": "İş sorunu:",
  ". Inspect completed stages or retry when permitted.": ". Tamamlanan aşamaları inceleyin veya izin verildiğinde yeniden deneyin.",
  "Issue:": "Sorun:",
  "Work has not recorded a stage yet.": "İş henüz bir aşama kaydetmedi.",
  "Additional evidence is available beyond the first 100 records.": "İlk 100 kaydın ötesinde ek kanıt mevcuttur.",
  "Structured diagnostic output": "Yapılandırılmış tanılama çıktısı",
  "Sources": "Kaynaklar",
  "View source": "Kaynağı görüntüleyin",
  "Request cancellation": "İptal isteyin",
  "Retry as a new job": "Yeni iş olarak yeniden deneyin",
  "Choose valid organization, project and job IDs.": "Geçerli kuruluş, proje ve iş kimlikleri seçin.",
  "Internal diagnostic concurrency is full. Wait for active work to settle, then retry.": "Dahili eşzamanlı tanılama kapasitesi dolu. Etkin işlerin sonuçlanmasını bekleyin, sonra yeniden deneyin.",
  "Diagnostic could not start. Check access and sample, then retry.": "Tanılama başlatılamadı. Erişimi ve örneği kontrol edin, sonra yeniden deneyin.",
  "The request outcome is unknown. Retry with the same sample to avoid duplicate work.": "İstek sonucu bilinmiyor. Yinelenen işleri önlemek için aynı örnekle yeniden deneyin.",
  "Cancellation requested; a stage may still finish.": "İptal istendi; bir aşama yine de tamamlanabilir.",
  "Diagnostic cancelled.": "Tanılama iptal edildi.",
  "Cancellation could not be confirmed. Refresh the job status.": "İptal doğrulanamadı. İş durumunu yenileyin.",
  "Cancellation outcome is unknown. Refresh before trying again.": "İptal sonucu bilinmiyor. Yeniden denemeden önce yenileyin.",
  "Retry could not start. Refresh the job and check access.": "Yeniden deneme başlatılamadı. İşi yenileyin ve erişimi kontrol edin.",
  "Retry outcome is unknown. Try again from this job to reuse the same request.": "Yeniden deneme sonucu bilinmiyor. Aynı isteği kullanmak için bu işten yeniden deneyin.",
  "Diagnostic schedule saved paused. Enable it when ready; no missed runs will replay.": "Tanılama zamanlaması duraklatılmış olarak kaydedildi. Hazır olduğunuzda etkinleştirin; kaçırılan çalıştırmalar tekrarlanmaz.",
  "Schedule could not be saved. Check the sample and project access.": "Zamanlama kaydedilemedi. Örneği ve proje erişimini kontrol edin.",
  "Schedule outcome is unknown. Retry with the same sample to avoid duplicates.": "Zamanlama sonucu bilinmiyor. Yinelemeleri önlemek için aynı örnekle yeniden deneyin.",
  "Schedule enabled. The next run starts after the chosen interval.": "Zamanlama etkinleştirildi. Sonraki çalıştırma seçilen aralıktan sonra başlar.",
  "Schedule paused. Existing job evidence remains available.": "Zamanlama duraklatıldı. Mevcut iş kanıtları erişilebilir kalır.",
  "Schedule access changed. Refresh project context before trying again.": "Zamanlama erişimi değişti. Yeniden denemeden önce proje bağlamını yenileyin.",
  "Schedule status could not be changed. Refresh to check the current state.": "Zamanlama durumu değiştirilemedi. Güncel durumu kontrol etmek için yenileyin.",
  "Schedule update outcome is unknown. Refresh before trying again.": "Zamanlama güncellemesinin sonucu bilinmiyor. Yeniden denemeden önce yenileyin.",
  "This project is unavailable. Return to the workspace to review access.": "Bu proje kullanılamıyor. Erişimi incelemek için çalışma alanına dönün.",
  "Project jobs are temporarily unavailable. Try again.": "Proje işleri geçici olarak kullanılamıyor. Yeniden deneyin.",
  "Jobs could not be loaded. Refresh or review project access.": "İşler yüklenemedi. Yenileyin veya proje erişimini inceleyin.",
  "Jobs are temporarily unavailable. Refresh to retry.": "İşler geçici olarak kullanılamıyor. Yeniden denemek için yenileyin.",
  "Job access changed or the job is unavailable. Return to the workspace.": "İş erişimi değişti veya iş kullanılamıyor. Çalışma alanına dönün.",
  "Job progress is temporarily unavailable. Previously shown evidence may be stale. Refresh to retry.": "İş ilerlemesi geçici olarak kullanılamıyor. Önceden gösterilen kanıt güncel olmayabilir. Yeniden denemek için yenileyin."
};

@Component({
  selector: 'app-job-dashboard',
  imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-shell" aria-labelledby="jobs-title">
      <p class="eyebrow">{{ t("Local development diagnostics") }}</p>
      <h1 id="jobs-title">{{ t("Project job progress") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish diagnostic-job interface draft in local development. Job states, UTC dates and technical evidence remain English; bilingual approval is pending.") }}</p> }
      <a routerLink="/app">{{ t("Return to organization and project context") }}</a>
      @if (error()) { <p #errorSummary class="form-status error" role="alert" tabindex="-1">{{ t(error()) }}</p> }
      @if (message()) { <p class="form-status" role="status">{{ t(message()) }}</p> }

      @if (environment.production) {
        <p>{{ t("Diagnostic jobs are unavailable here.") }}</p>
      } @else if (loading()) {
        <p role="status">{{ t("Loading authorized project jobs.") }}</p>
      } @else if (projectName()) {
        <div class="scope-summary"><strong>{{ t("Active project") }}</strong><span><span lang="">{{ projectName() }}</span></span></div>
        <section class="workspace-panel" aria-labelledby="recent-jobs-title">
          <h2 id="recent-jobs-title">{{ t("Recent diagnostic jobs") }}</h2>
          @if (!jobs().length) { <p>{{ t("No diagnostic jobs for this project yet.") }}</p> }
          <ul>
            @for (job of jobs(); track job.id) {
              <li><a [routerLink]="['/app/jobs', organizationId, projectId, job.id]">{{ t("Job") }} {{ job.id }}: <span lang="en">{{ statusLabel(job.status) }}</span></a></li>
            }
          </ul>
          <button type="button" (click)="refresh()" [disabled]="busy()">{{ t("Refresh jobs") }}</button>
          @if (hasMore()) { <p>{{ t("Only the first 100 recent jobs are shown.") }}</p> }
        </section>

        <section class="workspace-panel" aria-labelledby="diagnostic-schedules-title">
          <h2 id="diagnostic-schedules-title">{{ t("Diagnostic schedules") }}</h2>
          <p>{{ t("Schedules are local-only, cost-free and paused when first created. Missed runs do not accumulate.") }}</p>
          @if (schedulesFailed()) { <p role="alert">{{ t("Schedules are unavailable. Refresh to check their current state.") }}</p> }
          @else if (!schedules().length) { <p>{{ t("No diagnostic schedules for this project.") }}</p> }
          <ul>
            @for (schedule of schedules(); track schedule.id) {
              <li>
                <strong>{{ t("Schedule") }} {{ schedule.id }}:</strong> {{ t(schedule.enabled ? 'Enabled' : 'Paused') }}
                {{ t("· every") }} {{ schedule.interval_minutes }} {{ t("minutes") }}
                @if (schedule.next_run_at) { <span> {{ t("· next") }} <span lang="en">{{ schedule.next_run_at }}</span></span> }
                @if (schedule.last_run_at) { <span> {{ t("· last") }} <span lang="en">{{ schedule.last_run_at }}</span></span> }
                @if (schedule.skipped_occurrences) { <span> {{ t("· skipped") }} {{ schedule.skipped_occurrences }} {{ t("missed runs") }}</span> }
                @if (schedule.last_error_category) { <span> {{ t("· issue") }} <span lang="en">{{ schedule.last_error_category }}</span></span> }
                @if (canLaunch()) {
                  <button type="button" (click)="toggleSchedule(schedule)" [disabled]="busy()">
                    {{ t(schedule.enabled ? 'Pause schedule' : 'Enable schedule') }}
                  </button>
                }
              </li>
            }
          </ul>
          @if (scheduleHasMore()) { <p>{{ t("Only the first 100 recent schedules are shown.") }}</p> }
          @if (canLaunch()) {
            <form (submit)="createSchedule($event)">
              <label for="schedule-sample">{{ t("Synthetic sample for future runs") }}</label>
              <input id="schedule-sample" name="sample" maxlength="100" required />
              <label for="schedule-interval">{{ t("Frequency") }}</label>
              <select id="schedule-interval" name="interval">
                <option value="60">{{ t("Hourly") }}</option>
                <option value="1440">{{ t("Daily") }}</option>
                <option value="10080">{{ t("Weekly") }}</option>
              </select>
              <button type="submit" [disabled]="busy()">{{ t("Save paused schedule") }}</button>
            </form>
          }
        </section>

        @if (canLaunch()) {
          <section class="workspace-panel" aria-labelledby="new-job-title">
            <h2 id="new-job-title">{{ t("Run a cost-free diagnostic") }}</h2>
            <p>{{ t("This local check uses synthetic text, no external provider and zero diagnostic units. It does not analyze a website.") }}</p>
            <form (submit)="create($event)">
              <label for="diagnostic-sample">{{ t("Short synthetic sample") }}</label>
              <input id="diagnostic-sample" name="sample" maxlength="100" required />
              <label class="check-row" for="diagnostic-partial">
                <input id="diagnostic-partial" name="partial" type="checkbox" /> {{ t("Simulate a partial result") }}
              </label>
              <button type="submit" [disabled]="busy()">{{ t("Run diagnostic") }}</button>
            </form>
          </section>
        }

        @if (job(); as current) {
          <section class="workspace-panel" aria-labelledby="job-detail-title">
            <h2 id="job-detail-title">{{ t("Job") }} {{ current.id }} — <span lang="en">{{ statusLabel(current.status) }}</span></h2>
            <p role="status">{{ t("Progress:") }} {{ current.progress_percent }}{{ t("%. Last updated") }} <span lang="en">{{ current.updated_at }}</span>.</p>
            @if (current.status === 'waiting_provider') { <p>{{ t("Waiting for a provider response. Results may be partial.") }}</p> }
            @if (current.cancel_requested && current.status !== 'cancelled') {
              <p role="status">{{ t("Cancellation requested. A stage may still finish before it stops.") }}</p>
            }
            @if (current.error_category) { <p role="alert">{{ t("Job issue:") }} <span lang="en">{{ current.error_category }}</span>{{ t(". Inspect completed stages or retry when permitted.") }}</p> }
            @if (current.steps?.length) {
              <ol>
                @for (step of current.steps; track step.sequence) {
                  <li><strong><span lang="">{{ step.name }}</span></strong> — <span lang="en">{{ step.status }}</span>, {{ step.progress_percent }}%
                    @if (step.error_category) { <span>{{ t("Issue:") }} <span lang="en">{{ step.error_category }}</span></span> }
                  </li>
                }
              </ol>
            } @else { <p>{{ t("Work has not recorded a stage yet.") }}</p> }
            @if (current.has_more) { <p>{{ t("Additional evidence is available beyond the first 100 records.") }}</p> }
            @if (current.output && outputText(current.output)) {
              <h3>{{ t("Structured diagnostic output") }}</h3>
              <pre lang="">{{ outputText(current.output) }}</pre>
            }
            @if (current.citations?.length) {
              <h3>{{ t("Sources") }}</h3>
              <ul>
                @for (citation of current.citations; track citation.id) {
                  <li><span lang="">{{ citation.source_title }}</span> (<span lang="en">{{ citation.observed_at }}</span>)
                    @if (citation.source_url) { <a [href]="citation.source_url" rel="noopener noreferrer">{{ t("View source") }}</a> }
                  </li>
                }
              </ul>
            }
            @if (canLaunch() && isActive(current.status) && !current.cancel_requested) {
              <button type="button" class="danger-button" (click)="cancel()" [disabled]="busy()">{{ t("Request cancellation") }}</button>
            }
            @if (canLaunch() && isRetryable(current.status)) {
              <button type="button" (click)="retry()" [disabled]="busy()">{{ t("Retry as a new job") }}</button>
            }
          </section>
        }
      }
    </section>
  `,
})
export class JobDashboard implements OnInit, OnDestroy {
  @ViewChild('errorSummary') private errorSummary?: ElementRef<HTMLElement>;
  readonly documentTitle = signal('Diagnostic jobs');
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  t(text: string) { return this.uiLanguage() === 'tr' ? jobDashboardTurkish[text] ?? text : text; }
  readonly environment = environment;
  readonly projectName = signal('');
  readonly role = signal('viewer');
  readonly jobs = signal<JobInfo[]>([]);
  readonly schedules = signal<JobScheduleInfo[]>([]);
  readonly schedulesFailed = signal(false);
  readonly scheduleHasMore = signal(false);
  readonly job = signal<JobInfo | null>(null);
  readonly hasMore = signal(false);
  readonly loading = signal(true);
  readonly busy = signal(false);
  readonly error = signal('');
  readonly message = signal('');
  organizationId = 0;
  projectId = 0;
  private jobId = 0;
  private generation = 0;
  private timer?: ReturnType<typeof setTimeout>;
  private pendingCreate = { input: '', key: '' };
  private pendingRetry = { jobId: 0, key: '' };
  private pendingSchedule = { input: '', key: '' };
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);

  constructor(private readonly api: AccountApi, private readonly router: Router, title: Title) {
    effect(() => title.setTitle(`${this.t(this.documentTitle())} — OrganicSEOOps`));
  }

  ngOnInit() {
    void this.loadProductLanguage();
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      this.organizationId = Number(params.get('organizationId'));
      this.projectId = Number(params.get('projectId'));
      this.jobId = Number(params.get('jobId'));
      this.documentTitle.set(params.has('jobId') ? 'Diagnostic job progress' : 'Diagnostic jobs');
      this.clearContext();
      if (environment.production) { this.loading.set(false); return; }
      if (Number.isSafeInteger(this.organizationId) && this.organizationId > 0
        && Number.isSafeInteger(this.projectId) && this.projectId > 0
        && (params.get('jobId') === null || Number.isSafeInteger(this.jobId) && this.jobId > 0)) void this.loadContext(this.generation);
      else { this.loading.set(false); this.showError('Choose valid organization, project and job IDs.'); }
    });
  }

  private async loadProductLanguage() {
    try {
      const result = await this.api.productLanguage();
      if (!this.destroyRef.destroyed && result.status === 200 && isProductLanguageResult(result.body)) {
        this.productLanguage.set(result.body['language']);
      }
    } catch { /* Keep English when the private preference is unavailable. */ }
  }

  ngOnDestroy() { this.clearContext(); }

  canLaunch() { return this.role() === 'owner' || this.role() === 'admin' || this.role() === 'member'; }
  isActive(status: JobInfo['status']) { return status === 'queued' || status === 'running' || status === 'waiting_provider'; }
  isRetryable(status: JobInfo['status']) { return status === 'failed' || status === 'cancelled' || status === 'partially_succeeded'; }
  statusLabel(status: JobInfo['status']) { return status.replaceAll('_', ' '); }
  outputText(output: Record<string, unknown>) { return Object.keys(output).length ? JSON.stringify(output, null, 2) : ''; }

  refresh() {
    clearTimeout(this.timer);
    const generation = ++this.generation;
    this.projectName.set('');
    this.role.set('viewer');
    this.jobs.set([]);
    this.job.set(null);
    this.loading.set(true);
    void this.loadContext(generation);
  }

  async create(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || this.busy() || !this.canLaunch()) return;
    const fields = new FormData(form);
    const sample = String(fields.get('sample'));
    const partial = fields.get('partial') === 'on';
    const input = JSON.stringify([this.organizationId, this.projectId, sample, partial]);
    if (this.pendingCreate.input !== input) this.pendingCreate = { input, key: crypto.randomUUID() };
    const generation = this.generation;
    const organizationId = this.organizationId;
    const projectId = this.projectId;
    this.busy.set(true);
    try {
      const result = await this.api.createDiagnostic(organizationId, projectId, sample, partial, this.pendingCreate.key);
      if (generation !== this.generation) return;
      const job = readJob(result.body['job']);
      if (result.status === 202 && job && job.project_id === projectId) {
        this.pendingCreate = { input: '', key: '' };
        await this.router.navigate(['/app/jobs', organizationId, projectId, job.id]);
      } else if (result.status === 429) this.showError('Internal diagnostic concurrency is full. Wait for active work to settle, then retry.');
      else this.showError('Diagnostic could not start. Check access and sample, then retry.');
    } catch { if (generation === this.generation) this.showError('The request outcome is unknown. Retry with the same sample to avoid duplicate work.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }

  async cancel() {
    const current = this.job();
    if (!current || !this.canLaunch() || this.busy()) return;
    const generation = this.generation;
    const organizationId = this.organizationId;
    const projectId = this.projectId;
    this.busy.set(true);
    try {
      const result = await this.api.cancelJob(organizationId, projectId, current.id);
      if (generation !== this.generation) return;
      if (result.status === 200 || result.status === 202) {
        this.message.set(result.status === 202 ? 'Cancellation requested; a stage may still finish.' : 'Diagnostic cancelled.');
        await this.loadDetail(this.generation);
      } else this.showError('Cancellation could not be confirmed. Refresh the job status.');
    } catch { if (generation === this.generation) this.showError('Cancellation outcome is unknown. Refresh before trying again.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }

  async retry() {
    const current = this.job();
    if (!current || !this.isRetryable(current.status) || !this.canLaunch() || this.busy()) return;
    if (this.pendingRetry.jobId !== current.id) this.pendingRetry = { jobId: current.id, key: crypto.randomUUID() };
    const generation = this.generation;
    const organizationId = this.organizationId;
    const projectId = this.projectId;
    this.busy.set(true);
    try {
      const result = await this.api.retryJob(organizationId, projectId, current.id, this.pendingRetry.key);
      if (generation !== this.generation) return;
      const next = readJob(result.body['job']);
      if (result.status === 202 && next && next.project_id === projectId) {
        this.pendingRetry = { jobId: 0, key: '' };
        await this.router.navigate(['/app/jobs', organizationId, projectId, next.id]);
      } else if (result.status === 429) this.showError('Internal diagnostic concurrency is full. Wait for active work to settle, then retry.');
      else this.showError('Retry could not start. Refresh the job and check access.');
    } catch { if (generation === this.generation) this.showError('Retry outcome is unknown. Try again from this job to reuse the same request.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }

  async createSchedule(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || !this.canLaunch() || this.busy()) return;
    const fields = new FormData(form);
    const sample = String(fields.get('sample'));
    const interval = Number(fields.get('interval'));
    const input = JSON.stringify([this.organizationId, this.projectId, sample, interval]);
    if (this.pendingSchedule.input !== input) this.pendingSchedule = { input, key: crypto.randomUUID() };
    const generation = this.generation;
    const organizationId = this.organizationId;
    const projectId = this.projectId;
    this.busy.set(true);
    try {
      const result = await this.api.createDiagnosticSchedule(organizationId, projectId, sample, interval, this.pendingSchedule.key);
      if (generation !== this.generation) return;
      if (result.status === 201 && readSchedule(result.body['schedule'])) {
        this.pendingSchedule = { input: '', key: '' };
        form.reset();
        await this.loadSchedules(generation);
        this.message.set('Diagnostic schedule saved paused. Enable it when ready; no missed runs will replay.');
      } else this.showError('Schedule could not be saved. Check the sample and project access.');
    } catch { if (generation === this.generation) this.showError('Schedule outcome is unknown. Retry with the same sample to avoid duplicates.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }

  async toggleSchedule(schedule: JobScheduleInfo) {
    if (!this.canLaunch() || this.busy()) return;
    const generation = this.generation;
    this.busy.set(true);
    try {
      const result = await this.api.setDiagnosticSchedule(this.organizationId, this.projectId, schedule.id, !schedule.enabled);
      if (generation !== this.generation) return;
      const updated = readSchedule(result.body['schedule']);
      if (result.status === 200 && updated && updated.project_id === this.projectId) {
        this.schedules.update((items) => items.map((item) => item.id === updated.id ? updated : item));
        this.message.set(updated.enabled ? 'Schedule enabled. The next run starts after the chosen interval.' : 'Schedule paused. Existing job evidence remains available.');
      } else if (result.status === 403 || result.status === 404) {
        this.schedules.set([]);
        this.showError('Schedule access changed. Refresh project context before trying again.');
      } else this.showError('Schedule status could not be changed. Refresh to check the current state.');
    } catch { if (generation === this.generation) this.showError('Schedule update outcome is unknown. Refresh before trying again.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }

  private clearContext() {
    this.generation++;
    clearTimeout(this.timer);
    this.projectName.set('');
    this.role.set('viewer');
    this.jobs.set([]);
    this.schedules.set([]);
    this.schedulesFailed.set(false);
    this.scheduleHasMore.set(false);
    this.job.set(null);
    this.hasMore.set(false);
    this.loading.set(true);
    this.busy.set(false);
    this.error.set('');
    this.message.set('');
    this.pendingCreate = { input: '', key: '' };
    this.pendingRetry = { jobId: 0, key: '' };
    this.pendingSchedule = { input: '', key: '' };
  }

  private async loadContext(generation: number) {
    try {
      const result = await this.api.projects(this.organizationId);
      if (generation !== this.generation) return;
      if (result.status === 401) return void this.router.navigateByUrl('/account/login');
      const projects = result.body['projects'];
      const project = Array.isArray(projects) ? projects.find((item) => item?.id === this.projectId) : undefined;
      const organization = result.body['organization'];
      if (result.status !== 200 || !project || !organization || typeof organization !== 'object'
        || (organization as Record<string, unknown>)['id'] !== this.organizationId
        || project.organization_id !== this.organizationId) {
        return this.showError('This project is unavailable. Return to the workspace to review access.');
      }
      this.projectName.set(typeof project.name === 'string' ? project.name : 'Project');
      this.role.set(typeof (organization as Record<string, unknown>)['role'] === 'string'
        ? String((organization as Record<string, unknown>)['role']) : 'viewer');
      await this.loadJobs(generation);
      if (generation !== this.generation) return;
      await this.loadSchedules(generation);
      if (generation !== this.generation) return;
      if (this.jobId) await this.loadDetail(generation);
    } catch {
      if (generation === this.generation) this.showError('Project jobs are temporarily unavailable. Try again.');
    } finally {
      if (generation === this.generation) this.loading.set(false);
    }
  }

  private async loadJobs(generation: number) {
    try {
      const result = await this.api.jobs(this.organizationId, this.projectId);
      if (generation !== this.generation) return;
      if (result.status !== 200) {
        this.jobs.set([]);
        this.job.set(null);
        return this.showError('Jobs could not be loaded. Refresh or review project access.');
      }
      const values = result.body['jobs'];
      this.jobs.set(Array.isArray(values) ? values.map(readJob).filter((value): value is JobInfo => value !== null) : []);
      this.hasMore.set(result.body['has_more'] === true);
    } catch { if (generation === this.generation) this.showError('Jobs are temporarily unavailable. Refresh to retry.'); }
  }

  private async loadSchedules(generation: number) {
    try {
      const result = await this.api.jobSchedules(this.organizationId, this.projectId);
      if (generation !== this.generation) return;
      if (result.status !== 200) {
        this.schedules.set([]);
        this.schedulesFailed.set(true);
        return;
      }
      const rows = result.body['schedules'];
      this.schedules.set(Array.isArray(rows) ? rows.map(readSchedule)
        .filter((item): item is JobScheduleInfo => item !== null && item.project_id === this.projectId) : []);
      this.scheduleHasMore.set(result.body['has_more'] === true);
      this.schedulesFailed.set(false);
    } catch {
      if (generation === this.generation) {
        this.schedules.set([]);
        this.schedulesFailed.set(true);
      }
    }
  }

  private async loadDetail(generation: number) {
    clearTimeout(this.timer);
    try {
      const result = await this.api.jobDetails(this.organizationId, this.projectId, this.jobId);
      if (generation !== this.generation) return;
      if (result.status === 401) return void this.router.navigateByUrl('/account/login');
      const job = readJob(result.body['job']);
      if (result.status !== 200 || !job || job.project_id !== this.projectId || job.id !== this.jobId) {
        this.job.set(null);
        this.jobs.set([]);
        return this.showError('Job access changed or the job is unavailable. Return to the workspace.');
      }
      this.job.set(job);
      if (this.isActive(job.status)) this.timer = setTimeout(() => void this.loadDetail(generation), 2000);
    } catch {
      if (generation === this.generation) this.showError('Job progress is temporarily unavailable. Previously shown evidence may be stale. Refresh to retry.');
    }
  }

  private showError(message: string) {
    this.error.set(message);
    const generation = this.generation;
    setTimeout(() => {
      if (!this.destroyRef.destroyed && generation === this.generation && this.error()) this.errorSummary?.nativeElement.focus();
    });
  }
}

function readJob(value: unknown): JobInfo | null {
  if (!value || typeof value !== 'object') return null;
  const item = value as Record<string, unknown>;
  const states = ['queued', 'running', 'waiting_provider', 'succeeded', 'failed', 'cancelled', 'partially_succeeded'];
  if (typeof item['id'] !== 'number' || typeof item['project_id'] !== 'number'
    || typeof item['status'] !== 'string' || !states.includes(item['status']) || typeof item['progress_percent'] !== 'number'
    || item['progress_percent'] < 0 || item['progress_percent'] > 100
    || typeof item['error_category'] !== 'string' || typeof item['updated_at'] !== 'string') return null;
  const steps = item['steps'];
  const citations = item['citations'];
  return {
    id: item['id'], project_id: item['project_id'], status: item['status'] as JobInfo['status'],
    progress_percent: item['progress_percent'], error_category: item['error_category'],
    updated_at: item['updated_at'], retry_of: typeof item['retry_of'] === 'number' ? item['retry_of'] : null,
    cancel_requested: item['cancel_requested'] === true,
    output: item['output'] && typeof item['output'] === 'object' ? item['output'] as Record<string, unknown> : undefined,
    steps: Array.isArray(steps) ? steps.filter((step): step is JobStepInfo => step && typeof step.name === 'string'
      && typeof step.sequence === 'number' && typeof step.status === 'string' && typeof step.progress_percent === 'number'
      && typeof step.error_category === 'string') : undefined,
    citations: Array.isArray(citations) ? citations.filter((citation) => citation && typeof citation.id === 'number'
      && typeof citation.source_title === 'string' && typeof citation.source_url === 'string'
      && typeof citation.observed_at === 'string') : undefined,
    has_more: item['has_more'] === true,
  };
}

function readSchedule(value: unknown): JobScheduleInfo | null {
  if (!value || typeof value !== 'object') return null;
  const item = value as Record<string, unknown>;
  return typeof item['id'] === 'number' && typeof item['project_id'] === 'number'
    && typeof item['enabled'] === 'boolean' && typeof item['interval_minutes'] === 'number'
    && typeof item['skipped_occurrences'] === 'number' && typeof item['last_error_category'] === 'string'
    && (item['next_run_at'] === null || typeof item['next_run_at'] === 'string')
    && (item['last_run_at'] === null || typeof item['last_run_at'] === 'string')
    ? {
      id: item['id'], project_id: item['project_id'], enabled: item['enabled'], interval_minutes: item['interval_minutes'],
      next_run_at: item['next_run_at'], last_run_at: item['last_run_at'],
      skipped_occurrences: item['skipped_occurrences'], last_error_category: item['last_error_category'],
    } : null;
}
