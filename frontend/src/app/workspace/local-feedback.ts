import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, OnInit, signal, computed, effect } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi, ApiResult } from '../account/account-api';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';

const POLICY = 'local-owned-feedback-v1';
const SOURCE = 'customer_owned_web_feedback';
type Intake = { policy_version: string; source_kind: string; assessment_id: number; configuration_revision: number;
  source_url: string; feedback_reference: string; received_at: string; feedback_excerpt: string; theme: string;
  reply_draft: string; evidence_note: string; storage_permission: boolean; not_api_derived: boolean };
type Review = { id: number; feedback_id: string; project_id: number; revision: number; state: string; intake: Intake;
  reason: string; source_current: boolean; is_latest: boolean; effective_approval: boolean; approved_at: string | null;
  executed_at: string | null; execution_note: string; created_at: string; coverage: string; execution_state: string };
type Assessment = { id: number; business_name: string; location_label: string; eligibility: string };
type Context = { organization_id: number; project_id: number; can_review: boolean; policy_version: string;
  configuration_revision: number | null; verified_origins: string[]; assessments: Assessment[]; reviews: Review[];
  has_more: boolean; sources_has_more: boolean };
type Pending = { data: Record<string, unknown>; feedbackId?: string };
const positive = (value: unknown) => Number.isSafeInteger(value) && Number(value) > 0;

function isReview(value: unknown, project: number): value is Review {
  if (!value || typeof value !== 'object') return false;
  const row = value as Review; const intake = row.intake;
  return positive(row.id) && /^[0-9a-f-]{36}$/.test(row.feedback_id) && row.project_id === project
    && positive(row.revision) && ['draft', 'review', 'approved', 'reported'].includes(row.state)
    && ['reason', 'execution_note', 'created_at'].every((key) => typeof (row as unknown as Record<string, unknown>)[key] === 'string')
    && ['source_current', 'is_latest', 'effective_approval'].every((key) => typeof (row as unknown as Record<string, unknown>)[key] === 'boolean')
    && (row.approved_at === null || typeof row.approved_at === 'string') && (row.executed_at === null || typeof row.executed_at === 'string')
    && row.coverage === 'selected_customer_supplied_feedback_not_complete_history'
    && ['not_reported', 'customer_reported_not_verified'].includes(row.execution_state)
    && !!intake && typeof intake === 'object' && intake.policy_version === POLICY && intake.source_kind === SOURCE
    && positive(intake.assessment_id) && Number.isSafeInteger(intake.configuration_revision)
    && intake.storage_permission === true && intake.not_api_derived === true
    && ['source_url', 'feedback_reference', 'received_at', 'feedback_excerpt', 'theme', 'reply_draft', 'evidence_note']
      .every((key) => typeof (intake as unknown as Record<string, unknown>)[key] === 'string');
}

@Component({
  selector: 'app-local-feedback', imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="feedback-title">
      <h1 id="feedback-title">{{ t("Customer-owned website feedback and human replies") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t('Unreviewed Turkish independent-feedback interface draft in local development. Stored decision states and other screens remain English; bilingual approval is pending.') }}</p> }
      <p><a routerLink="/app">{{ t("Return to workspace") }}</a> · <a [routerLink]="['/app/local', organizationId, projectId]">{{ t("Review actual business facts") }}</a></p>
      <p>{{ t('Organization') }} {{ organizationId }} · {{ t('project') }} {{ projectId }}. {{ t('One independently customer-owned website feedback item at a time. No Google API content, reviewer identity/contact/rating, automatic collection, AI or provider writes. A selected excerpt is partial customer-supplied evidence, not complete review history or measured theme frequency.') }}</p>
      <p>{{ t("Private customer records follow 90-day retained access after lapse, active deletion within 30 days of closure/retention expiry, and up to 35-day backup rotation after active deletion. Confirm rights to that storage policy. Source/date claims and manual execution remain user reports, not provider verification.") }}</p>
      @if (loading()) { <p role="status">{{ t("Loading this project's private feedback history.") }}</p> }
      @if (error()) { <p role="alert">{{ t(error()) }}</p> }
      @if (message()) { <p role="status">{{ t(message()) }}</p> }
      @if (!context() && !pending() && !loading()) { <button type="button" (click)="load()" [disabled]="busy()">{{ t("Reload current project") }}</button> }
      @if (pending()) {
        <p>{{ t("Save outcome is uncertain. The exact command is frozen in component memory; inspect its request key before another decision.") }}</p>
        <button type="button" (click)="reconcile()" [disabled]="busy()">{{ t("Check uncertain save") }}</button>
        @if (notFound()) { <button type="button" (click)="retry()" [disabled]="busy()">{{ t("Retry the same exact command") }}</button> }
      }
      @if (context(); as info) {
        <button type="button" (click)="load()" [disabled]="busy() || !!pending()">{{ t("Refresh current authority and history") }}</button>
        <p>{{ t("Approval availability is as of the last refresh; the server rechecks current actor, business and source on every decision. Approval does not send a reply. Other platforms/licensed sources and direct writes are unavailable.") }}</p>
        @if (info.has_more) { <p>{{ t("Only the newest 50 feedback items are shown.") }}</p> }
        @if (!info.reviews.length) { <p>{{ t("No customer-owned feedback has been supplied for this project.") }}</p> }
        <ul [attr.aria-label]="t('Latest customer feedback decisions')">
          @for (row of info.reviews; track row.feedback_id) {
            <li><span lang="">{{ row.intake.feedback_reference }}</span> · {{ t('received') }} {{ row.intake.received_at }} · {{ t('revision') }} {{ row.revision }} · <span lang="en">{{ row.state }}</span> · {{ t(row.source_current ? 'Current source at refresh' : 'Stale/unavailable authority') }}
              <button type="button" (click)="inspect(row.feedback_id)" [disabled]="busy() || !!pending()">{{ t("Inspect source, exact text and history") }}</button>
            </li>
          }
        </ul>
        @if (selected(); as row) {
          <section aria-labelledby="feedback-selected-title">
            <h2 id="feedback-selected-title">{{ t('Exact feedback') }} <span lang="">{{ row.intake.feedback_reference }}</span> · {{ t('revision') }} {{ row.revision }}</h2>
            <p>{{ t('Assessment') }} {{ row.intake.assessment_id }} · {{ t('configuration') }} {{ row.intake.configuration_revision }} · {{ t('source') }} <span lang="">{{ row.intake.source_url }}</span> · {{ t('received') }} {{ row.intake.received_at }}.</p>
            <h3>{{ t("Minimized original excerpt") }}</h3><pre lang="">{{ row.intake.feedback_excerpt }}</pre>
            <h3>{{ t("Human theme (not measured frequency)") }}</h3><pre lang="">{{ row.intake.theme }}</pre>@if (!row.intake.theme) { <p>{{ t('Absent; no theme generated') }}</p> }
            <p>{{ t('Independent source evidence/limits:') }} <span lang="">{{ row.intake.evidence_note }}</span></p>
            <h3>{{ t("Exact human reply text") }}</h3><pre lang="">{{ row.intake.reply_draft }}</pre>@if (!row.intake.reply_draft) { <p>{{ t('Absent; no reply generated') }}</p> }
            <p>{{ t('Decision:') }} <span lang="en">{{ row.state }}</span> · <span lang="">{{ row.reason }}</span> · {{ t(row.effective_approval ? 'Exact approval current at refresh; no automated execution' : 'No current effective approval') }}.</p>
            @if (!row.source_current) { <p>{{ t("Source/business/reviewer authority is stale or unavailable. New review, approval and manual-use reporting are denied; a new unapproved source-attested correction may be submitted.") }}</p> }
            @if (row.executed_at) { <p>{{ t('Manual execution reported at') }} {{ row.executed_at }} · <span lang="">{{ row.execution_note }}</span>. {{ t('Not independently verified.') }}</p> }
            @if (info.can_review && row.source_current && row.is_latest && !pending()) {
              @if (row.state !== 'reported') {
                <form (submit)="decide($event, row.state === 'draft' ? 'review' : row.state === 'review' ? 'approved' : 'reported')">
                  <label for="feedback-decision-reason">{{ t("Human decision reason") }}</label><textarea lang="" id="feedback-decision-reason" name="reason" maxlength="500" required></textarea>
                  <label><input type="checkbox" name="exact" required />{{ t('I reviewed the exact source, target and unchanged reply text of revision') }} {{ row.revision }}. {{ t('Approval is not execution.') }}</label>
                  @if (row.state === 'approved') {
                    <label for="feedback-executed">{{ t("Actual manual execution date/time (browser-local timezone; must follow approval)") }}</label>
                    <input lang="" id="feedback-executed" name="executed_at" type="datetime-local" required />
                    <label for="feedback-execution-note">{{ t("Actual manual execution note (no private identifiers)") }}</label>
                    <textarea lang="" id="feedback-execution-note" name="execution_note" maxlength="500" required></textarea>
                  }
                  <button type="submit" [disabled]="busy() || !row.intake.reply_draft.trim()">{{ t(row.state === 'draft' ? 'Send exact draft to human review' : row.state === 'review' ? 'Approve exact reviewed reply' : 'Record actual manual execution only') }}</button>
                </form>
              }
            }
            @if (info.can_review && !pending()) { <button type="button" (click)="edit(row)" [disabled]="busy()">{{ t("Correct source/target/text as a new unapproved draft") }}</button> }
          </section>
        }
        @if (historyRows().length) {
          <details><summary>{{ t("Immutable source/text/approval history (newest 20)") }}</summary>
            <ol>@for (row of historyRows(); track row.id) {
              <li>{{ t('Revision') }} {{ row.revision }} · {{ row.created_at }} · <span lang="en">{{ row.state }}</span> · <span lang="">{{ row.reason }}</span>.
                <p>{{ t('Source') }} <span lang="">{{ row.intake.source_url }}</span> · {{ row.intake.received_at }} · {{ t(row.source_current ? 'Current authority at refresh' : 'Stale authority') }}.</p>
                <pre lang="">{{ row.intake.feedback_excerpt }}</pre><pre>{{ t('Human theme:') }} <span lang="">{{ row.intake.theme }}</span>{{ row.intake.theme ? '' : t('Absent') }}</pre><pre>{{ t('Exact reply:') }} <span lang="">{{ row.intake.reply_draft }}</span>{{ row.intake.reply_draft ? '' : t('Absent') }}</pre>
                <p>{{ t('Approval') }} {{ row.approved_at || t('Absent') }} · <span lang="en">{{ row.execution_state }}</span> · <span lang="">{{ row.execution_note }}</span>.</p>
              </li>
            }</ol>
            @if (historyMore()) { <p>{{ t("Older history exists; this bounded view is incomplete.") }}</p> }
          </details>
        }
        @if (info.can_review && !pending()) {
          <h2>{{ t(editing() ? 'New unapproved correction; earlier approval does not carry forward' : 'Supply independent customer-owned feedback') }}</h2>
          @if (!info.assessments.length || !info.verified_origins.length) {
            <p>{{ t("A current manual business assessment and verified exact HTTPS website origin are required first. GBP eligibility is separate; legitimate hidden-address service areas are supported.") }}</p>
          } @else {
            <p>{{ t('Verified website candidates:') }} <span lang="">{{ info.verified_origins.join(', ') }}</span>. {{ t('Storage/independence rights are still your separate declaration.') }}</p>
            @if (info.sources_has_more) { <p>{{ t("The first 20 business/origin candidates are shown; inventory is partial.") }}</p> }
            <form (submit)="saveDraft($event)">
              <fieldset [disabled]="busy()">
                <legend>{{ t("Exact independent source and human draft") }}</legend>
                <label for="feedback-assessment">{{ t("Latest actual manual business/location") }}</label>
                <select lang="" id="feedback-assessment" name="assessment_id" required>
                  @for (row of info.assessments; track row.id) { <option lang="" [value]="row.id" [selected]="row.id === editing()?.intake?.assessment_id">{{ row.business_name }} · {{ row.location_label }}</option> }
                </select>
                @for (row of info.assessments; track row.id) {
                  <p><span lang="">{{ row.business_name }} · {{ row.location_label }}</span> · {{ t('GBP eligibility:') }} <span lang="en">{{ row.eligibility }}</span> {{ t('(unverified)') }}.</p>
                }
                <p>{{ t('GBP eligibility is unverified. A blank location is a general service area.') }}</p>
                <label for="feedback-source">{{ t("Exact customer-owned website feedback URL (no query/credentials)") }}</label><input lang="" id="feedback-source" name="source_url" type="url" maxlength="1024" required [value]="editing()?.intake?.source_url || ''" />
                <label for="feedback-ref">{{ t("Opaque customer reference (no reviewer identity/contact or provider ID)") }}</label><input lang="" id="feedback-ref" name="feedback_reference" maxlength="64" pattern="[A-Za-z0-9][A-Za-z0-9._-]{0,63}" required [value]="editing()?.intake?.feedback_reference || ''" />
                <label for="feedback-received">{{ t("Received date with timezone (for example 2026-10-01T12:00:00+03:00)") }}</label><input lang="" id="feedback-received" name="received_at" maxlength="64" required [value]="editing()?.intake?.received_at || ''" />
                <label for="feedback-excerpt">{{ t("Minimized original feedback excerpt, without identity/contact details") }}</label><textarea lang="" id="feedback-excerpt" name="feedback_excerpt" maxlength="2000" required [value]="editing()?.intake?.feedback_excerpt || ''"></textarea>
                <label for="feedback-theme">{{ t("Optional human theme") }}</label><textarea lang="" id="feedback-theme" name="theme" maxlength="500" [value]="editing()?.intake?.theme || ''"></textarea>
                <label for="feedback-reply">{{ t("Optional human reply draft") }}</label><textarea lang="" id="feedback-reply" name="reply_draft" maxlength="2000" [value]="editing()?.intake?.reply_draft || ''"></textarea>
                <label for="feedback-evidence">{{ t("Independent source evidence, date and coverage limitations") }}</label><textarea lang="" id="feedback-evidence" name="evidence_note" maxlength="500" required [value]="editing()?.intake?.evidence_note || ''"></textarea>
                <label for="feedback-reason">{{ t("Human draft/correction reason") }}</label><textarea lang="" id="feedback-reason" name="reason" maxlength="500" required></textarea>
                <label><input type="checkbox" name="storage_permission" required />{{ t("I control this independent website feedback and have rights to store it under the disclosed private export/closure/deletion/backup policy.") }}</label>
                <label><input type="checkbox" name="not_api_derived" required />{{ t("This excerpt/theme/reply was not copied or derived from Google/YouTube API content. No reviewer identity/contact or rating fields.") }}</label>
                <button type="submit">{{ t("Save new unapproved human draft revision") }}</button>
                @if (editing()) { <button type="button" (click)="editing.set(null)">{{ t("Cancel correction") }}</button> }
              </fieldset>
            </form>
          }
        } @else if (!info.can_review) { <p>{{ t("Read-only history. Current verified owner/admin authority is required for source intake and every reply decision.") }}</p> }
      }
    </section>
  `,
  styles: `form, fieldset { display: grid; gap: .6rem; } form { max-width: 48rem; margin-block: 1rem; }
    pre { white-space: pre-wrap; overflow-wrap: anywhere; } li { margin-block: 1rem; } input, textarea, select { min-width: 0; max-width: 100%; }`,
})
export class LocalFeedback implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  t(text: string) { return this.uiLanguage() === 'tr' ? localFeedbackTurkish[text] ?? text : text; }
  readonly context = signal<Context | null>(null); readonly selected = signal<Review | null>(null);
  readonly editing = signal<Review | null>(null); readonly historyRows = signal<Review[]>([]); readonly historyMore = signal(false);
  readonly loading = signal(false); readonly busy = signal(false); readonly error = signal(''); readonly message = signal('');
  readonly pending = signal<Pending | null>(null); readonly notFound = signal(false);
  protected organizationId = 0; protected projectId = 0;
  private generation = 0; private selectionGeneration = 0;
  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi, private readonly destroyRef: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t('Private customer-owned feedback review')} — OrganicSEOOps`));
    destroyRef.onDestroy(() => { this.generation++; this.clear(); });
  }
  ngOnInit() {
    void this.loadProductLanguage();
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      this.generation++; this.clear(); this.busy.set(false); this.loading.set(false); this.error.set(''); this.message.set('');
      this.organizationId = Number(params.get('organizationId')); this.projectId = Number(params.get('projectId'));
      if (positive(this.organizationId) && positive(this.projectId)) void this.load();
      else this.error.set('Select an authorized organization and project.');
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
  private clear() { this.context.set(null); this.selected.set(null); this.editing.set(null); this.historyRows.set([]);
    this.pending.set(null); this.notFound.set(false); this.selectionGeneration++; }
  private readContext(response: ApiResult): Context {
    const info = response.body as unknown as Context;
    if (response.status !== 200 || info.organization_id !== this.organizationId || info.project_id !== this.projectId
        || info.policy_version !== POLICY || typeof info.can_review !== 'boolean'
        || !(info.configuration_revision === null || Number.isSafeInteger(info.configuration_revision))
        || !Array.isArray(info.verified_origins) || !info.verified_origins.every((value) => typeof value === 'string')
        || !Array.isArray(info.assessments) || !info.assessments.every((row) => !!row && positive(row.id)
          && ['business_name', 'location_label', 'eligibility'].every((key) => typeof (row as unknown as Record<string, unknown>)[key] === 'string'))
        || !Array.isArray(info.reviews) || !info.reviews.every((row) => isReview(row, this.projectId))
        || typeof info.has_more !== 'boolean' || typeof info.sources_has_more !== 'boolean') throw new Error();
    return info;
  }
  async load() {
    if (this.busy() || this.pending()) return;
    const generation = ++this.generation; this.clear(); this.loading.set(true); this.error.set('');
    try {
      const response = await this.api.localFeedback(this.organizationId, this.projectId);
      if (generation === this.generation) this.context.set(this.readContext(response));
    } catch { if (generation === this.generation) this.error.set('Feedback history or current project/session authority is unavailable.'); }
    finally { if (generation === this.generation) this.loading.set(false); }
  }
  async inspect(id: string) {
    if (this.busy() || this.pending()) return;
    const generation = this.generation; const selection = ++this.selectionGeneration;
    this.selected.set(null); this.historyRows.set([]); this.editing.set(null); this.message.set('');
    try {
      const response = await this.api.localFeedback(this.organizationId, this.projectId, undefined, id);
      if (generation !== this.generation || selection !== this.selectionGeneration) return;
      const info = this.readContext(response);
      if (!info.reviews.length || info.reviews.some((row) => row.feedback_id !== id) || !info.reviews[0].is_latest) throw new Error();
      const previous = this.context();
      if (previous) this.context.set({ ...info, reviews: previous.reviews, has_more: previous.has_more });
      this.selected.set(info.reviews[0]); this.historyRows.set(info.reviews); this.historyMore.set(info.has_more);
    } catch { if (generation === this.generation && selection === this.selectionGeneration) {
      this.context.set(null); this.message.set('Exact history is unavailable; refresh before another decision.');
    } }
  }
  edit(row: Review) { if (!this.busy() && !this.pending() && this.context()?.can_review && row.is_latest) this.editing.set(row); }
  saveDraft(event: Event) {
    event.preventDefault(); const form = event.target as HTMLFormElement; const info = this.context();
    if (this.busy() || this.pending() || !info?.can_review || !form.reportValidity()) return;
    const fields = new FormData(form);
    if (!fields.has('storage_permission') || !fields.has('not_api_derived')) return;
    const intake: Record<string, unknown> = { policy_version: POLICY, source_kind: SOURCE,
      assessment_id: Number(fields.get('assessment_id')), configuration_revision: info.configuration_revision,
      storage_permission: true, not_api_derived: true };
    for (const key of ['source_url', 'feedback_reference', 'received_at', 'feedback_excerpt', 'theme', 'reply_draft', 'evidence_note']) intake[key] = String(fields.get(key) || '');
    const row = this.editing();
    const data: Record<string, unknown> = { request_key: crypto.randomUUID(), intake, state: 'draft', reason: String(fields.get('reason') || ''), executed_at: null, execution_note: '' };
    if (row) data['expected_revision'] = row.revision;
    void this.send({ data, feedbackId: row?.feedback_id });
  }
  decide(event: Event, state: string) {
    event.preventDefault(); const form = event.target as HTMLFormElement; const row = this.selected();
    if (this.busy() || this.pending() || !this.context()?.can_review || !row?.source_current || !row.is_latest || !form.reportValidity()) return;
    const fields = new FormData(form); if (!fields.has('exact')) return;
    const date = state === 'reported' ? new Date(String(fields.get('executed_at'))) : null;
    if (date && !Number.isFinite(date.getTime())) return;
    void this.send({ feedbackId: row.feedback_id, data: { request_key: crypto.randomUUID(), intake: { ...row.intake },
      expected_revision: row.revision, state, reason: String(fields.get('reason') || ''),
      executed_at: date?.toISOString() || null, execution_note: String(fields.get('execution_note') || '') } });
  }
  private async send(command: Pending) {
    const generation = this.generation; this.busy.set(true); this.message.set(''); this.notFound.set(false);
    // Keep the exact in-memory command across transport uncertainty; no automatic replay or browser storage.
    this.pending.set(command);
    try {
      const response = await this.api.localFeedback(this.organizationId, this.projectId, command.data, command.feedbackId);
      if (generation !== this.generation) return;
      if ((response.status === 200 || response.status === 201) && response.body['organization_id'] === this.organizationId
          && response.body['project_id'] === this.projectId && isReview(response.body['review'], this.projectId)
          && this.matchesCommand(response.body['review'], command)) {
        this.pending.set(null); this.busy.set(false); await this.load();
        if (generation + 1 === this.generation) this.message.set('Human decision recorded. No source was fetched or reply sent.');
      } else if ([400, 401, 403, 404, 409, 413, 429].includes(response.status)) {
        this.pending.set(null); this.selected.set(null); this.historyRows.set([]); this.editing.set(null); this.context.set(null);
        this.error.set('Current authority, exact revision or fields were denied. Refresh the project before another decision.');
      } else this.message.set('Save outcome uncertain; check the exact request key before continuing.');
    } catch { if (generation === this.generation) this.message.set('Save outcome uncertain; check the exact request key before continuing.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  private matchesCommand(row: Review, command: Pending) {
    const intake = command.data['intake'] as Record<string, unknown>;
    return (!command.feedbackId || row.feedback_id === command.feedbackId)
      && row.revision === (Number(command.data['expected_revision'] || 0) + 1)
      && row.state === command.data['state'] && row.reason === command.data['reason']
      && (row.executed_at === command.data['executed_at'] || typeof row.executed_at === 'string'
        && typeof command.data['executed_at'] === 'string'
        && new Date(row.executed_at).getTime() === new Date(command.data['executed_at']).getTime())
      && row.execution_note === command.data['execution_note']
      && Object.keys(intake).length === Object.keys(row.intake).length
      && Object.entries(intake).every(([key, value]) => (row.intake as unknown as Record<string, unknown>)[key] === value);
  }
  async reconcile() {
    const command = this.pending(); if (!command || this.busy()) return;
    const generation = this.generation; this.busy.set(true);
    try {
      const response = await this.api.localFeedback(this.organizationId, this.projectId, undefined, undefined, String(command.data['request_key']));
      if (generation !== this.generation) return;
      const info = this.readContext(response);
      if (response.body['lookup'] === 'found' && info.reviews.length === 1 && this.matchesCommand(info.reviews[0], command)) {
        this.pending.set(null); this.busy.set(false); await this.load();
        if (generation + 1 === this.generation) this.message.set('Request reconciled from immutable history; no command replayed.');
      } else if (response.body['lookup'] === 'not_found' && !info.reviews.length && info.can_review) {
        this.notFound.set(true); this.message.set('No recorded decision found. You may deliberately retry the same frozen command.');
      } else throw new Error();
    } catch { if (generation === this.generation) {
      this.context.set(null); this.selected.set(null); this.editing.set(null); this.historyRows.set([]); this.notFound.set(false);
      this.message.set('Current request outcome/authority remains unavailable. No command replayed.');
    } }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  retry() { const command = this.pending(); if (command && this.notFound() && !this.busy()) void this.send(command); }
}

const localFeedbackTurkish: Record<string, string> = {
  "Private customer-owned feedback review": "Özel müşteriye ait geri bildirim incelemesi",
  "GBP eligibility:": "GBP uygunluğu:",
  "(unverified)": "(doğrulanmadı)",
  "Customer-owned website feedback and human replies": "Müşterinin kendi sitesinden geri bildirim ve insan yanıtları",
  "Unreviewed Turkish independent-feedback interface draft in local development. Stored decision states and other screens remain English; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe bağımsız geri bildirim arayüzü taslağı. Kaydedilen karar durumları ve diğer ekranlar İngilizce kalır; iki dilli onay bekleniyor.",
  "Return to workspace": "Çalışma alanına dön",
  "Review actual business facts": "Gerçek işletme bilgilerini incele",
  "Organization": "Kuruluş",
  "project": "proje",
  "One independently customer-owned website feedback item at a time. No Google API content, reviewer identity/contact/rating, automatic collection, AI or provider writes. A selected excerpt is partial customer-supplied evidence, not complete review history or measured theme frequency.": "Her seferinde müşterinin kendi sitesinden bağımsız bir geri bildirim öğesi. Google API içeriği, yorumcu kimliği/iletişim bilgisi/puanı, otomatik toplama, yapay zekâ veya sağlayıcıya yazma yoktur. Seçilen alıntı müşterinin sağladığı kısmi kanıttır; tüm yorum geçmişi veya ölçülmüş tema sıklığı değildir.",
  "Private customer records follow 90-day retained access after lapse, active deletion within 30 days of closure/retention expiry, and up to 35-day backup rotation after active deletion. Confirm rights to that storage policy. Source/date claims and manual execution remain user reports, not provider verification.": "Özel müşteri kayıtlarında süre dolduktan sonra 90 günlük erişim, kapatma/saklama süresi bitiminden itibaren 30 gün içinde etkin silme ve etkin silmeden sonra en fazla 35 günlük yedek döngüsü uygulanır. Bu saklama politikasına ilişkin haklarınızı doğrulayın. Kaynak/tarih beyanları ve elle uygulama kullanıcı bildirimleridir; sağlayıcı doğrulaması değildir.",
  "Loading this project's private feedback history.": "Bu projenin özel geri bildirim geçmişi yükleniyor.",
  "Reload current project": "Güncel projeyi yeniden yükle",
  "Save outcome is uncertain. The exact command is frozen in component memory; inspect its request key before another decision.": "Kaydetme sonucu belirsiz. Aynı komut bileşen belleğinde donduruldu; başka bir karardan önce istek anahtarını inceleyin.",
  "Check uncertain save": "Belirsiz kaydı kontrol et",
  "Retry the same exact command": "Aynı komutu yeniden dene",
  "Refresh current authority and history": "Güncel yetkiyi ve geçmişi yenile",
  "Approval availability is as of the last refresh; the server rechecks current actor, business and source on every decision. Approval does not send a reply. Other platforms/licensed sources and direct writes are unavailable.": "Onay kullanılabilirliği son yenileme anına aittir; sunucu her kararda güncel aktörü, işletmeyi ve kaynağı tekrar kontrol eder. Onay bir yanıt göndermez. Diğer platformlar/lisanslı kaynaklar ve doğrudan yazma kullanılamıyor.",
  "Only the newest 50 feedback items are shown.": "Yalnızca en yeni 50 geri bildirim öğesi gösterilir.",
  "No customer-owned feedback has been supplied for this project.": "Bu proje için müşterinin kendi geri bildirimi henüz sağlanmadı.",
  "Latest customer feedback decisions": "En son müşteri geri bildirim kararları",
  "received": "alındı",
  "revision": "sürüm",
  "Current source at refresh": "Yenileme anında güncel kaynak",
  "Stale/unavailable authority": "Güncel olmayan/kullanılamayan yetki",
  "Inspect source, exact text and history": "Kaynağı, tam metni ve geçmişi incele",
  "Exact feedback": "Tam geri bildirim",
  "Assessment": "Değerlendirme",
  "configuration": "yapılandırma",
  "source": "kaynak",
  "Minimized original excerpt": "Sınırlandırılmış özgün alıntı",
  "Human theme (not measured frequency)": "İnsanın belirlediği tema (ölçülmüş sıklık değildir)",
  "Absent; no theme generated": "Yok; tema üretilmedi",
  "Independent source evidence/limits:": "Bağımsız kaynak kanıtı/sınırları:",
  "Exact human reply text": "İnsan yanıtının tam metni",
  "Absent; no reply generated": "Yok; yanıt üretilmedi",
  "Decision:": "Karar:",
  "Exact approval current at refresh; no automated execution": "Yenileme anında tam onay güncel; otomatik uygulama yok",
  "No current effective approval": "Güncel geçerli onay yok",
  "Source/business/reviewer authority is stale or unavailable. New review, approval and manual-use reporting are denied; a new unapproved source-attested correction may be submitted.": "Kaynak/işletme/inceleyen yetkisi güncel değil veya kullanılamıyor. Yeni inceleme, onay ve elle kullanım bildirimi reddedilir; kaynağı beyan edilmiş yeni bir onaysız düzeltme sunulabilir.",
  "Manual execution reported at": "Elle uygulama bildirildiği zaman",
  "Not independently verified.": "Bağımsız olarak doğrulanmadı.",
  "Human decision reason": "İnsan kararının gerekçesi",
  "I reviewed the exact source, target and unchanged reply text of revision": "Bu sürümün tam kaynağını, hedefini ve değişmemiş yanıt metnini inceledim:",
  "Approval is not execution.": "Onay, uygulama değildir.",
  "Actual manual execution date/time (browser-local timezone; must follow approval)": "Gerçek elle uygulama tarihi/saati (tarayıcının yerel saat dilimi; onaydan sonra olmalı)",
  "Actual manual execution note (no private identifiers)": "Gerçek elle uygulama notu (özel tanımlayıcı yok)",
  "Send exact draft to human review": "Tam taslağı insan incelemesine gönder",
  "Approve exact reviewed reply": "İncelenen tam yanıtı onayla",
  "Record actual manual execution only": "Yalnızca gerçek elle uygulamayı kaydet",
  "Correct source/target/text as a new unapproved draft": "Kaynağı/hedefi/metni yeni bir onaysız taslak olarak düzelt",
  "Immutable source/text/approval history (newest 20)": "Değiştirilemez kaynak/metin/onay geçmişi (en yeni 20)",
  "Revision": "Sürüm",
  "Source": "Kaynak",
  "Current authority at refresh": "Yenileme anında güncel yetki",
  "Stale authority": "Güncel olmayan yetki",
  "Human theme:": "İnsanın belirlediği tema:",
  "Absent": "Yok",
  "Exact reply:": "Tam yanıt:",
  "Approval": "Onay",
  "Older history exists; this bounded view is incomplete.": "Daha eski geçmiş var; bu sınırlı görünüm eksiktir.",
  "New unapproved correction; earlier approval does not carry forward": "Yeni onaysız düzeltme; önceki onay aktarılmaz",
  "Supply independent customer-owned feedback": "Müşterinin kendi sitesinden bağımsız geri bildirim sağla",
  "A current manual business assessment and verified exact HTTPS website origin are required first. GBP eligibility is separate; legitimate hidden-address service areas are supported.": "Önce güncel elle işletme değerlendirmesi ve doğrulanmış tam HTTPS site kökeni gerekir. GBP uygunluğu ayrıdır; meşru gizli adresli hizmet bölgeleri desteklenir.",
  "Verified website candidates:": "Doğrulanmış site adayları:",
  "Storage/independence rights are still your separate declaration.": "Saklama/bağımsızlık hakları hâlâ sizin ayrı beyanınızdır.",
  "The first 20 business/origin candidates are shown; inventory is partial.": "İlk 20 işletme/köken adayı gösterilir; envanter kısmidir.",
  "Exact independent source and human draft": "Tam bağımsız kaynak ve insan taslağı",
  "Latest actual manual business/location": "En son gerçek elle işletme/konum",
  "GBP eligibility is unverified. A blank location is a general service area.": "GBP uygunluğu doğrulanmadı. Boş konum, genel hizmet bölgesidir.",
  "Exact customer-owned website feedback URL (no query/credentials)": "Müşterinin kendi sitesindeki tam geri bildirim URL’si (sorgu/kimlik bilgisi yok)",
  "Opaque customer reference (no reviewer identity/contact or provider ID)": "Opak müşteri referansı (yorumcu kimliği/iletişim bilgisi veya sağlayıcı kimliği yok)",
  "Received date with timezone (for example 2026-10-01T12:00:00+03:00)": "Saat dilimiyle alınma tarihi (örneğin 2026-10-01T12:00:00+03:00)",
  "Minimized original feedback excerpt, without identity/contact details": "Kimlik/iletişim bilgileri olmadan sınırlandırılmış özgün geri bildirim alıntısı",
  "Optional human theme": "İsteğe bağlı insan teması",
  "Optional human reply draft": "İsteğe bağlı insan yanıt taslağı",
  "Independent source evidence, date and coverage limitations": "Bağımsız kaynak kanıtı, tarihi ve kapsam sınırları",
  "Human draft/correction reason": "İnsan taslağı/düzeltme gerekçesi",
  "I control this independent website feedback and have rights to store it under the disclosed private export/closure/deletion/backup policy.": "Bu bağımsız site geri bildirimini kontrol ediyorum ve açıklanan özel dışa aktarma/kapatma/silme/yedekleme politikası kapsamında saklama hakkına sahibim.",
  "This excerpt/theme/reply was not copied or derived from Google/YouTube API content. No reviewer identity/contact or rating fields.": "Bu alıntı/tema/yanıt Google/YouTube API içeriğinden kopyalanmadı veya türetilmedi. Yorumcu kimliği/iletişim bilgisi veya puan alanı yoktur.",
  "Save new unapproved human draft revision": "Yeni onaysız insan taslağı sürümünü kaydet",
  "Cancel correction": "Düzeltmeyi iptal et",
  "Read-only history. Current verified owner/admin authority is required for source intake and every reply decision.": "Salt okunur geçmiş. Kaynak alımı ve her yanıt kararı için güncel doğrulanmış işletme sahibi/yönetici yetkisi gerekir.",
  "Select an authorized organization and project.": "Yetkili bir kuruluş ve proje seçin.",
  "Feedback history or current project/session authority is unavailable.": "Geri bildirim geçmişi veya güncel proje/oturum yetkisi kullanılamıyor.",
  "Exact history is unavailable; refresh before another decision.": "Tam geçmiş kullanılamıyor; başka bir karardan önce yenileyin.",
  "Human decision recorded. No source was fetched or reply sent.": "İnsan kararı kaydedildi. Kaynak alınmadı veya yanıt gönderilmedi.",
  "Current authority, exact revision or fields were denied. Refresh the project before another decision.": "Güncel yetki, tam sürüm veya alanlar reddedildi. Başka bir karardan önce projeyi yenileyin.",
  "Save outcome uncertain; check the exact request key before continuing.": "Kaydetme sonucu belirsiz; devam etmeden önce tam istek anahtarını kontrol edin.",
  "Request reconciled from immutable history; no command replayed.": "İstek değiştirilemez geçmişten uzlaştırıldı; komut yeniden çalıştırılmadı.",
  "No recorded decision found. You may deliberately retry the same frozen command.": "Kayıtlı karar bulunamadı. Aynı dondurulmuş komutu bilinçli olarak yeniden deneyebilirsiniz.",
  "Current request outcome/authority remains unavailable. No command replayed.": "Güncel istek sonucu/yetkisi hâlâ kullanılamıyor. Komut yeniden çalıştırılmadı."
};
