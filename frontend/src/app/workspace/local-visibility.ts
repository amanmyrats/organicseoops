import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, OnInit, signal, computed, effect } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi, ApiResult } from '../account/account-api';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';

const METHOD = 'local-manual-organic-v1'; const SOURCE = 'customer_manual_organic_observation';
type Intake = { method_version: string; source_kind: string; platform: string; surface: string; assessment_id: number;
  configuration_revision: number; origin: string; observation_reference: string; query: string; observed_at: string;
  requested_location: string; requested_language: string; requested_device: string; applied_location: string;
  applied_language: string; applied_device: string; inspection_limit: number; inspected_count: number;
  status: string; ordinal: number | null; matched_url: string; evidence_note: string; storage_permission: boolean; not_api_derived: boolean };
type Observation = { id: number; project_id: number; observation_id: string; revision: number; intake: Intake; reason: string;
  source_current: boolean; is_latest: boolean; created_at: string; basis: string; coverage: string; rank_scope: string };
type Assessment = { id: number; business_name: string; location_label: string; locations: string[] };
type Context = { organization_id: number; project_id: number; method_version: string; can_review: boolean;
  configuration_revision: number | null; assessments: Assessment[]; verified_origins: string[]; requested_languages: string[];
  observations: Observation[]; has_more: boolean; sources_has_more: boolean };
type Command = { data: Record<string, unknown>; observationId?: string };
const positive = (value: unknown) => Number.isSafeInteger(value) && Number(value) > 0;
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every((item) => typeof item === 'string');

function isObservation(value: unknown, project: number): value is Observation {
  if (!value || typeof value !== 'object') return false;
  const row = value as Observation; const input = row.intake;
  return positive(row.id) && row.project_id === project && positive(row.revision) && /^[0-9a-f-]{36}$/.test(row.observation_id)
    && typeof row.reason === 'string' && typeof row.created_at === 'string'
    && typeof row.source_current === 'boolean' && typeof row.is_latest === 'boolean'
    && row.basis === 'customer_reported_not_provider_verified' && row.coverage === 'partial_inspected_organic_set_only'
    && row.rank_scope === 'human_ordinal_not_universal_or_local_pack_rank'
    && !!input && typeof input === 'object' && input.method_version === METHOD && input.source_kind === SOURCE
    && input.platform === 'google_search' && input.surface === 'organic_links' && positive(input.assessment_id)
    && Number.isSafeInteger(input.configuration_revision) && input.storage_permission === true && input.not_api_derived === true
    && ['origin', 'observation_reference', 'query', 'observed_at', 'requested_location', 'requested_language', 'requested_device',
      'applied_location', 'applied_language', 'applied_device', 'matched_url', 'evidence_note'].every((key) =>
        typeof (input as unknown as Record<string, unknown>)[key] === 'string')
    && Number.isSafeInteger(input.inspection_limit) && input.inspection_limit >= 1 && input.inspection_limit <= 20
    && Number.isSafeInteger(input.inspected_count) && input.inspected_count >= 0 && input.inspected_count <= input.inspection_limit
    && (input.status === 'observed' ? positive(input.ordinal) && Number(input.ordinal) <= input.inspected_count && !!input.matched_url
      : ['not_seen_in_inspected_set', 'unavailable'].includes(input.status) && input.ordinal === null && input.matched_url === ''
        && (input.status === 'unavailable' ? input.inspected_count === 0 : input.inspected_count > 0));
}

@Component({
  selector: 'app-local-visibility', imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="local-visibility-title">
      <h1 id="local-visibility-title">{{ t("Manual local organic-link observations") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t('Unreviewed Turkish manual local-visibility interface draft in local development. Stored context/status values and other screens remain English; bilingual approval is pending.') }}</p> }
      <p>{{ t('Organization') }} {{ organizationId }} · {{ t('project') }} {{ projectId }}. <a routerLink="/app">{{ t("Return to workspace") }}</a> · <a [routerLink]="['/app/local', organizationId, projectId]">{{ t("Review actual business facts") }}</a></p>
      <p>{{ t("Customer-reported Google Search organic links only. A human ordinal among inspected links is not universal rank, Google Maps/local-pack position, Search Console average position or provider verification. No search is run here. Other engines/surfaces, API/GBP imports, automatic scheduling, screenshots/snippets/competitor inventories, AI and paid collection are unavailable.") }}</p>
      <p>{{ t("Requested location/language/device is not proof of applied context. Use only a coarse reported region, never a personal address, precise observer location, account identity, IP or cookie. Unknown applied context stays unknown; observations from different contexts are not aggregated or compared as like-for-like measurements.") }}</p>
      <p>{{ t("Independent customer reports follow private D098 export/closure/deletion: 90-day retained access after lapse, active deletion within 30 days of closure/retention expiry, backups up to 35 days after active deletion. Confirm your storage rights. Exported history is not verified rank evidence.") }}</p>
      @if (loading()) { <p role="status">{{ t("Loading this project's private observation history.") }}</p> }
      @if (error()) { <p role="alert">{{ t(error()) }}</p> }
      @if (message()) { <p role="status">{{ t(message()) }}</p> }
      @if (pending()) {
        <p>{{ t("Save outcome uncertain. The exact report is frozen in component memory; check the request before another save.") }}</p>
        <button type="button" (click)="reconcile()" [disabled]="busy()">{{ t("Check uncertain report") }}</button>
        @if (notFound()) { <button type="button" (click)="retry()" [disabled]="busy()">{{ t("Retry the same exact report") }}</button> }
      } @else { <button type="button" (click)="load()" [disabled]="busy() || loading()">{{ t("Refresh current authority and reports") }}</button> }
      @if (context(); as info) {
        <p>{{ t("Current source status is as of refresh. Every save rechecks current actor, latest actual business/configuration, location/language and verified exact website.") }}</p>
        @if (info.has_more) { <p>{{ t("Newest 50 observation revisions only; history is partial.") }}</p> }
        @if (!info.observations.length) { <p>{{ t("No manual local observations supplied. This is unavailable, not rank zero.") }}</p> }
        <ul [attr.aria-label]="t('Latest customer local observation reports')">
          @for (row of info.observations; track row.observation_id) {
            <li>
              <h2><span lang="">{{ row.intake.observation_reference }}</span> · {{ row.intake.observed_at }} · {{ t('correction revision') }} {{ row.revision }}</h2>
              <p>{{ t('Query:') }} <span lang="">{{ row.intake.query }}</span>. {{ t('Google Search · organic links · customer report, not provider verified.') }}</p>
              <p>{{ t('Requested:') }} <span lang="">{{ row.intake.requested_location }}</span> / <span lang="en">{{ row.intake.requested_language }} / {{ row.intake.requested_device }}</span>.</p>
              <p>{{ t('Applied (customer-reported):') }} <span lang="">{{ row.intake.applied_location }}</span>{{ row.intake.applied_location ? '' : t('Unknown region') }} / <span lang="en">{{ row.intake.applied_language }}</span>{{ row.intake.applied_language ? '' : t('Unknown language') }} / <span lang="en">{{ row.intake.applied_device }}</span>.</p>
              <p>{{ describe(row) }} {{ t('Inspected') }} {{ row.intake.inspected_count }} {{ t('of declared maximum') }} {{ row.intake.inspection_limit }} {{ t('organic links; partial coverage only.') }}</p>
              <p>{{ t('Own matched URL:') }} <span lang="">{{ row.intake.matched_url }}</span>{{ row.intake.matched_url ? '' : t('None reported') }}. {{ t('Evidence/limits:') }} <span lang="">{{ row.intake.evidence_note }}</span>.</p>
              <p>{{ t(row.source_current ? 'Current source at refresh' : 'Stale business/source/actor authority') }} · <span lang="">{{ row.reason }}</span>.</p>
              <button type="button" (click)="inspect(row.observation_id)" [disabled]="busy() || !!pending()">{{ t("Inspect immutable correction history") }}</button>
              @if (info.can_review) { <button type="button" (click)="edit(row)" [disabled]="busy() || !!pending()">{{ t("Correct this customer report") }}</button> }
            </li>
          }
        </ul>
        @if (historyRows().length) {
          <details open><summary>{{ t("Immutable source/context/time/ordinal correction history (newest 20)") }}</summary>
            <ol>@for (row of historyRows(); track row.id) {
              <li>{{ t('Revision') }} {{ row.revision }} · {{ row.created_at }} · <span lang="">{{ row.reason }}</span> · {{ t(row.source_current ? 'Current authority at refresh' : 'Stale authority') }}.
                <p>{{ row.intake.observed_at }} · <span lang="">{{ row.intake.query }}</span> · {{ t('requested') }} <span lang="">{{ row.intake.requested_location }}</span> / <span lang="en">{{ row.intake.requested_language }} / {{ row.intake.requested_device }}</span>.</p>
                <p>{{ t('Applied') }} <span lang="">{{ row.intake.applied_location }}</span>{{ row.intake.applied_location ? '' : t('Unknown region') }} / <span lang="en">{{ row.intake.applied_language }}</span>{{ row.intake.applied_language ? '' : t('Unknown language') }} / <span lang="en">{{ row.intake.applied_device }}</span>. {{ describe(row) }}</p>
                <p>{{ t('Inspected') }} {{ row.intake.inspected_count }} / {{ t('bound') }} {{ row.intake.inspection_limit }} · <span lang="">{{ row.intake.matched_url }}</span>{{ row.intake.matched_url ? '' : t('No matched URL') }} · <span lang="">{{ row.intake.evidence_note }}</span>.</p>
              </li>
            }</ol>
            @if (historyMore()) { <p>{{ t("Earlier corrections exist; this bounded view is incomplete.") }}</p> }
          </details>
        }
        @if (info.can_review && !pending()) {
          <h2>{{ t(editing() ? 'Correct the exact manual report; original evidence remains in history' : 'Supply one actual customer observation') }}</h2>
          @if (!info.assessments.length || !info.verified_origins.length) {
            <p>{{ t("A current actual manual business assessment and verified exact HTTPS website origin are required. Missing evidence does not establish a location or profile.") }}</p>
          } @else {
            @if (info.sources_has_more) { <p>{{ t("First 20 current business/origin candidates only.") }}</p> }
            <form (submit)="save($event)"><fieldset [disabled]="busy()">
              <legend>{{ t("Independent customer-reported Google organic-link observation (no automatic search)") }}</legend>
              <label for="visibility-assessment">{{ t("Actual manual business (blank location = general service area)") }}</label><select lang="" id="visibility-assessment" name="assessment_id" (change)="selectAssessment($event)" required>
                @for (row of info.assessments; track row.id) { <option lang="" [value]="row.id" [selected]="row.id === assessmentId()">{{ row.business_name }} · {{ row.location_label }}</option> }
              </select>
              <label for="visibility-origin">{{ t("Exact verified own-website origin") }}</label><select lang="" id="visibility-origin" name="origin" required>
                @for (origin of info.verified_origins; track origin) { <option lang="" [value]="origin" [selected]="origin === editing()?.intake?.origin">{{ origin }}</option> }
              </select>
              <label for="visibility-location">{{ t("Requested actual configured business location/service area") }}</label><select lang="" id="visibility-location" name="requested_location" required>
                @for (location of locations(); track location) { <option lang="" [value]="location" [selected]="location === editing()?.intake?.requested_location">{{ location }}</option> }
              </select>
              <label for="visibility-language">{{ t("Requested configured language (or unknown)") }}</label><select lang="en" id="visibility-language" name="requested_language"><option [attr.lang]="uiLanguage()" value="unknown">{{ t("Unknown") }}</option>
                @for (language of info.requested_languages; track language) { <option [value]="language" [selected]="language === editing()?.intake?.requested_language">{{ language }}</option> }
              </select>
              <label for="visibility-device">{{ t("Requested device context") }}</label><select lang="en" id="visibility-device" name="requested_device">
                @for (device of devices; track device) { <option [value]="device" [selected]="device === editing()?.intake?.requested_device">{{ device }}</option> }
              </select>
              <label for="visibility-applied-location">{{ t("Applied coarse region (customer report; blank = unknown)") }}</label><input lang="" id="visibility-applied-location" name="applied_location" maxlength="240" [value]="editing()?.intake?.applied_location || ''" />
              <label for="visibility-applied-language">{{ t("Applied language tag (blank = unknown)") }}</label><input lang="en" id="visibility-applied-language" name="applied_language" maxlength="35" [value]="editing()?.intake?.applied_language || ''" />
              <label for="visibility-applied-device">{{ t("Applied device (customer report; not controlled by us)") }}</label><select lang="en" id="visibility-applied-device" name="applied_device">
                @for (device of devices; track device) { <option [value]="device" [selected]="device === editing()?.intake?.applied_device">{{ device }}</option> }
              </select>
              <label for="visibility-query">{{ t("Actual human query") }}</label><input lang="" id="visibility-query" name="query" maxlength="240" required [value]="editing()?.intake?.query || ''" />
              <label for="visibility-reference">{{ t("Opaque own observation reference (no provider/account/person ID)") }}</label><input lang="" id="visibility-reference" name="observation_reference" pattern="[A-Za-z0-9][A-Za-z0-9._-]{0,63}" maxlength="64" required [value]="editing()?.intake?.observation_reference || ''" />
              <label for="visibility-date">{{ t("Actual observed date with timezone") }}</label><input lang="" id="visibility-date" name="observed_at" maxlength="64" required placeholder="2026-10-01T12:00:00+03:00" [value]="editing()?.intake?.observed_at || ''" />
              <label for="visibility-limit">{{ t("Declared inspected-link bound (1–20)") }}</label><input lang="" id="visibility-limit" name="inspection_limit" type="number" min="1" max="20" required [value]="editing()?.intake?.inspection_limit || 10" />
              <label for="visibility-count">{{ t("Actual inspected count (0 only for unavailable)") }}</label><input lang="" id="visibility-count" name="inspected_count" type="number" min="0" max="20" required [value]="editing()?.intake?.inspected_count ?? 1" />
              <label for="visibility-status">{{ t("Reported coverage outcome") }}</label><select lang="en" id="visibility-status" name="status" (change)="selectStatus($event)">
                @for (status of statuses; track status) { <option [value]="status" [selected]="status === selectedStatus()">{{ status }}</option> }
              </select>
              <label for="visibility-ordinal">{{ t("Human ordinal among actually inspected organic links (not universal rank)") }}</label><input lang="" id="visibility-ordinal" name="ordinal" type="number" min="1" max="20" [required]="selectedStatus() === 'observed'" [disabled]="selectedStatus() !== 'observed'" [value]="editing()?.intake?.ordinal ?? ''" />
              <label for="visibility-match">{{ t("Matched exact own-website URL (no query/credentials)") }}</label><input lang="" id="visibility-match" name="matched_url" type="url" maxlength="1024" [required]="selectedStatus() === 'observed'" [disabled]="selectedStatus() !== 'observed'" [value]="editing()?.intake?.matched_url || ''" />
              <label for="visibility-note">{{ t("Minimized independent evidence and coverage/context limitations (no copied result content)") }}</label><textarea lang="" id="visibility-note" name="evidence_note" maxlength="500" required [value]="editing()?.intake?.evidence_note || ''"></textarea>
              <label for="visibility-reason">{{ t("Human report/correction reason") }}</label><textarea lang="" id="visibility-reason" name="reason" maxlength="500" required></textarea>
              <label><input type="checkbox" name="storage_permission" required />{{ t("I have independent rights to store this own numerical observation under the disclosed private export/retention/deletion/backup policy.") }}</label>
              <label><input type="checkbox" name="not_api_derived" required />{{ t("No API/GBP content, snippets/screenshots, competitor inventories or private observer identifiers were copied or used.") }}</label>
              <button type="submit">{{ t("Save immutable customer report (no search run)") }}</button>
              @if (editing()) { <button type="button" (click)="cancelEdit()">{{ t("Cancel correction") }}</button> }
            </fieldset></form>
          }
        } @else if (!info.can_review) { <p>{{ t("Read-only retained human reports; current verified owner/admin is required to supply or correct evidence.") }}</p> }
      }
    </section>
  `,
  styles: `form, fieldset { display: grid; gap: .6rem; } form { max-width: 48rem; } li { margin-block: 1.5rem; }
    p { overflow-wrap: anywhere; } input, textarea, select { min-width: 0; max-width: 100%; }`,
})
export class LocalVisibility implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  t(text: string) { return this.uiLanguage() === 'tr' ? localVisibilityTurkish[text] ?? text : text; }
  readonly devices = ['unknown', 'desktop', 'mobile']; readonly statuses = ['observed', 'not_seen_in_inspected_set', 'unavailable'];
  readonly context = signal<Context | null>(null); readonly editing = signal<Observation | null>(null);
  readonly historyRows = signal<Observation[]>([]); readonly historyMore = signal(false); readonly assessmentId = signal(0);
  readonly selectedStatus = signal('observed'); readonly loading = signal(false); readonly busy = signal(false);
  readonly error = signal(''); readonly message = signal(''); readonly pending = signal<Command | null>(null); readonly notFound = signal(false);
  protected organizationId = 0; protected projectId = 0; private generation = 0; private historyGeneration = 0;
  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi, private readonly destroyRef: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t('Private manual local organic observations')} — OrganicSEOOps`));
    destroyRef.onDestroy(() => { this.generation++; this.clear(); });
  }
  ngOnInit() { void this.loadProductLanguage(); this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
    this.generation++; this.clear(); this.busy.set(false); this.loading.set(false); this.error.set(''); this.message.set('');
    this.organizationId = Number(params.get('organizationId')); this.projectId = Number(params.get('projectId'));
    if (positive(this.organizationId) && positive(this.projectId)) void this.load(); else this.error.set('Select an authorized project.');
  }); }
  private async loadProductLanguage() {
    try {
      const result = await this.api.productLanguage();
      if (!this.destroyRef.destroyed && result.status === 200 && isProductLanguageResult(result.body)) {
        this.productLanguage.set(result.body['language']);
      }
    } catch { /* Keep English when the private preference is unavailable. */ }
  }
  private clear() { this.context.set(null); this.editing.set(null); this.historyRows.set([]); this.pending.set(null); this.notFound.set(false); this.historyGeneration++; }
  describe(row: Observation) { return row.intake.status === 'observed' ? `${this.t('Reported human ordinal')} ${row.intake.ordinal}${this.t(', not universal rank.')}`
    : row.intake.status === 'unavailable' ? this.t('Unavailable; no inspected results or rank value.') : this.t('Not seen in this partial inspected set; visibility elsewhere is unknown.'); }
  locations() { return this.context()?.assessments.find((row) => row.id === this.assessmentId())?.locations || []; }
  selectAssessment(event: Event) { this.assessmentId.set(Number((event.target as HTMLSelectElement).value)); }
  selectStatus(event: Event) { this.selectedStatus.set((event.target as HTMLSelectElement).value); }
  cancelEdit() { this.editing.set(null); this.selectedStatus.set('observed'); }
  private read(response: ApiResult): Context {
    const info = response.body as unknown as Context;
    if (response.status !== 200 || info.organization_id !== this.organizationId || info.project_id !== this.projectId
        || info.method_version !== METHOD || typeof info.can_review !== 'boolean'
        || !(info.configuration_revision === null || Number.isSafeInteger(info.configuration_revision))
        || !strings(info.verified_origins) || !strings(info.requested_languages) || typeof info.has_more !== 'boolean' || typeof info.sources_has_more !== 'boolean'
        || !Array.isArray(info.assessments) || !info.assessments.every((row) => !!row && positive(row.id)
          && typeof row.business_name === 'string' && typeof row.location_label === 'string' && strings(row.locations))
        || !Array.isArray(info.observations) || !info.observations.every((row) => isObservation(row, this.projectId))) throw new Error();
    return info;
  }
  async load() {
    if (this.busy() || this.pending()) return;
    const generation = ++this.generation; this.clear(); this.loading.set(true); this.error.set('');
    try { const response = await this.api.localVisibility(this.organizationId, this.projectId);
      if (generation === this.generation) { const info = this.read(response); this.context.set(info); this.assessmentId.set(info.assessments[0]?.id || 0); this.selectedStatus.set('observed'); }
    } catch { if (generation === this.generation) this.error.set('Local observation history or current project/session authority is unavailable.'); }
    finally { if (generation === this.generation) this.loading.set(false); }
  }
  edit(row: Observation) {
    if (this.busy() || this.pending() || !this.context()?.can_review || !row.is_latest) return;
    this.editing.set(row); this.selectedStatus.set(row.intake.status);
    this.assessmentId.set(this.context()!.assessments.some((source) => source.id === row.intake.assessment_id)
      ? row.intake.assessment_id : this.context()!.assessments[0]?.id || 0);
  }
  async inspect(id: string) {
    if (this.busy() || this.pending()) return;
    const generation = this.generation; const history = ++this.historyGeneration; this.historyRows.set([]); this.editing.set(null);
    try {
      const response = await this.api.localVisibility(this.organizationId, this.projectId, undefined, id);
      if (generation !== this.generation || history !== this.historyGeneration) return;
      const info = this.read(response);
      if (!info.observations.length || info.observations.some((row) => row.observation_id !== id) || !info.observations[0].is_latest) throw new Error();
      const old = this.context(); if (old) this.context.set({ ...info, observations: old.observations, has_more: old.has_more });
      this.historyRows.set(info.observations); this.historyMore.set(info.has_more);
    } catch { if (generation === this.generation && history === this.historyGeneration) { this.context.set(null); this.message.set('Exact history unavailable. Refresh before another report.'); } }
  }
  save(event: Event) {
    event.preventDefault(); const form = event.target as HTMLFormElement; const info = this.context();
    if (this.busy() || this.pending() || !info?.can_review || !form.reportValidity()) return;
    const fields = new FormData(form); if (!fields.has('storage_permission') || !fields.has('not_api_derived')) return;
    const intake: Record<string, unknown> = { method_version: METHOD, source_kind: SOURCE, platform: 'google_search', surface: 'organic_links',
      assessment_id: Number(fields.get('assessment_id')), configuration_revision: info.configuration_revision, storage_permission: true, not_api_derived: true,
      inspection_limit: Number(fields.get('inspection_limit')), inspected_count: Number(fields.get('inspected_count')),
      ordinal: this.selectedStatus() === 'observed' ? Number(fields.get('ordinal')) : null };
    for (const key of ['origin', 'observation_reference', 'query', 'observed_at', 'requested_location', 'requested_language', 'requested_device',
      'applied_location', 'applied_language', 'applied_device', 'status', 'matched_url', 'evidence_note']) intake[key] = String(fields.get(key) || '');
    const row = this.editing(); const data: Record<string, unknown> = { request_key: crypto.randomUUID(), intake, reason: String(fields.get('reason') || '') };
    if (row) data['expected_revision'] = row.revision;
    void this.send({ data, observationId: row?.observation_id });
  }
  private matches(row: Observation, command: Command) {
    const intake = command.data['intake'] as Record<string, unknown>;
    return (!command.observationId || row.observation_id === command.observationId) && row.reason === command.data['reason']
      && row.revision === Number(command.data['expected_revision'] || 0) + 1 && Object.keys(intake).length === Object.keys(row.intake).length
      && Object.entries(intake).every(([key, value]) => (row.intake as unknown as Record<string, unknown>)[key] === value);
  }
  private async send(command: Command) {
    const generation = this.generation; this.busy.set(true); this.pending.set(command); this.notFound.set(false); this.message.set('');
    try {
      const response = await this.api.localVisibility(this.organizationId, this.projectId, command.data, command.observationId);
      if (generation !== this.generation) return;
      if ([200, 201].includes(response.status) && response.body['organization_id'] === this.organizationId && response.body['project_id'] === this.projectId
          && isObservation(response.body['observation'], this.projectId) && this.matches(response.body['observation'], command)) {
        this.pending.set(null); this.busy.set(false); await this.load();
        if (generation + 1 === this.generation) this.message.set('Exact human report recorded; no search or provider request ran.');
      } else if ([400, 401, 403, 404, 409, 413, 429].includes(response.status)) { this.clear(); this.error.set('Current scope/revision or fields denied. Refresh before another report.'); }
      else this.message.set('Save outcome uncertain; check the exact request key.');
    } catch { if (generation === this.generation) this.message.set('Save outcome uncertain; check the exact request key.'); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  async reconcile() {
    const command = this.pending(); if (!command || this.busy()) return;
    const generation = this.generation; this.busy.set(true);
    try {
      const response = await this.api.localVisibility(this.organizationId, this.projectId, undefined, undefined, String(command.data['request_key']));
      if (generation !== this.generation) return;
      const info = this.read(response);
      if (response.body['lookup'] === 'found' && info.observations.length === 1 && this.matches(info.observations[0], command)) {
        this.pending.set(null); this.busy.set(false); await this.load();
        if (generation + 1 === this.generation) this.message.set('Report reconciled from immutable history; no command replayed.');
      } else if (response.body['lookup'] === 'not_found' && !info.observations.length && info.can_review) {
        this.notFound.set(true); this.message.set('No recorded report found; deliberately retry the same exact report if needed.');
      } else throw new Error();
    } catch { if (generation === this.generation) { this.context.set(null); this.historyRows.set([]); this.editing.set(null); this.notFound.set(false);
      this.message.set('Current report outcome/authority unavailable; no replay.'); } }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  retry() { const command = this.pending(); if (command && this.notFound() && !this.busy()) void this.send(command); }
}

const localVisibilityTurkish: Record<string, string> = {
  "Private manual local organic observations": "Özel elle yerel organik gözlemler",
  "Manual local organic-link observations": "Elle yerel organik bağlantı gözlemleri",
  "Unreviewed Turkish manual local-visibility interface draft in local development. Stored context/status values and other screens remain English; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe elle yerel görünürlük arayüzü taslağı. Kaydedilen bağlam/durum değerleri ve diğer ekranlar İngilizce kalır; iki dilli onay bekleniyor.",
  "Organization": "Kuruluş",
  "project": "proje",
  "Return to workspace": "Çalışma alanına dön",
  "Review actual business facts": "Gerçek işletme bilgilerini incele",
  "Customer-reported Google Search organic links only. A human ordinal among inspected links is not universal rank, Google Maps/local-pack position, Search Console average position or provider verification. No search is run here. Other engines/surfaces, API/GBP imports, automatic scheduling, screenshots/snippets/competitor inventories, AI and paid collection are unavailable.": "Yalnızca müşterinin bildirdiği Google Arama organik bağlantıları. İncelenen bağlantılar arasındaki insan sıra numarası evrensel sıralama, Google Haritalar/yerel paket konumu, Search Console ortalama konumu veya sağlayıcı doğrulaması değildir. Burada arama çalıştırılmaz. Diğer motorlar/yüzeyler, API/GBP içe aktarımları, otomatik zamanlama, ekran görüntüleri/alıntılar/rakip envanterleri, yapay zekâ ve ücretli toplama kullanılamıyor.",
  "Requested location/language/device is not proof of applied context. Use only a coarse reported region, never a personal address, precise observer location, account identity, IP or cookie. Unknown applied context stays unknown; observations from different contexts are not aggregated or compared as like-for-like measurements.": "İstenen konum/dil/cihaz, uygulanan bağlamın kanıtı değildir. Yalnızca kabaca bildirilen bir bölge kullanın; kişisel adres, gözlemcinin kesin konumu, hesap kimliği, IP veya çerez kullanmayın. Bilinmeyen uygulanan bağlam bilinmeyen olarak kalır; farklı bağlamlardaki gözlemler birleştirilmez veya eşdeğer ölçümler olarak karşılaştırılmaz.",
  "Independent customer reports follow private D098 export/closure/deletion: 90-day retained access after lapse, active deletion within 30 days of closure/retention expiry, backups up to 35 days after active deletion. Confirm your storage rights. Exported history is not verified rank evidence.": "Bağımsız müşteri bildirimleri özel D098 dışa aktarma/kapatma/silme politikasını izler: süre dolduktan sonra 90 günlük erişim, kapatma/saklama süresi bitiminden itibaren 30 gün içinde etkin silme, etkin silmeden sonra en fazla 35 günlük yedekler. Saklama haklarınızı doğrulayın. Dışa aktarılan geçmiş, doğrulanmış sıralama kanıtı değildir.",
  "Loading this project's private observation history.": "Bu projenin özel gözlem geçmişi yükleniyor.",
  "Save outcome uncertain. The exact report is frozen in component memory; check the request before another save.": "Kaydetme sonucu belirsiz. Aynı bildirim bileşen belleğinde donduruldu; başka bir kayıttan önce isteği kontrol edin.",
  "Check uncertain report": "Belirsiz bildirimi kontrol et",
  "Retry the same exact report": "Aynı bildirimi yeniden dene",
  "Refresh current authority and reports": "Güncel yetkiyi ve bildirimleri yenile",
  "Current source status is as of refresh. Every save rechecks current actor, latest actual business/configuration, location/language and verified exact website.": "Güncel kaynak durumu yenileme anına aittir. Her kayıtta güncel aktör, en son gerçek işletme/yapılandırma, konum/dil ve doğrulanmış tam site tekrar kontrol edilir.",
  "Newest 50 observation revisions only; history is partial.": "Yalnızca en yeni 50 gözlem sürümü; geçmiş kısmidir.",
  "No manual local observations supplied. This is unavailable, not rank zero.": "Elle yerel gözlem sağlanmadı. Bu, kullanılamıyor demektir; sıfır sıralama değildir.",
  "Latest customer local observation reports": "En son müşteri yerel gözlem bildirimleri",
  "correction revision": "düzeltme sürümü",
  "Query:": "Sorgu:",
  "Google Search · organic links · customer report, not provider verified.": "Google Arama · organik bağlantılar · müşteri bildirimi; sağlayıcı tarafından doğrulanmadı.",
  "Requested:": "İstenen:",
  "Applied (customer-reported):": "Uygulanan (müşteri bildirimi):",
  "Unknown region": "Bölge bilinmiyor",
  "Unknown language": "Dil bilinmiyor",
  "Reported human ordinal": "Bildirilen insan sıra numarası",
  ", not universal rank.": "; evrensel sıralama değildir.",
  "Unavailable; no inspected results or rank value.": "Kullanılamıyor; incelenmiş sonuç veya sıralama değeri yok.",
  "Not seen in this partial inspected set; visibility elsewhere is unknown.": "Bu kısmi incelenmiş kümede görülmedi; başka yerdeki görünürlük bilinmiyor.",
  "Inspected": "İncelenen",
  "of declared maximum": "beyan edilen en fazla",
  "organic links; partial coverage only.": "organik bağlantı; yalnızca kısmi kapsam.",
  "Own matched URL:": "Eşleşen kendi URL’si:",
  "None reported": "Bildirilmedi",
  "Evidence/limits:": "Kanıt/sınırlar:",
  "Current source at refresh": "Yenileme anında güncel kaynak",
  "Stale business/source/actor authority": "Güncel olmayan işletme/kaynak/aktör yetkisi",
  "Inspect immutable correction history": "Değiştirilemez düzeltme geçmişini incele",
  "Correct this customer report": "Bu müşteri bildirimini düzelt",
  "Immutable source/context/time/ordinal correction history (newest 20)": "Değiştirilemez kaynak/bağlam/zaman/sıra numarası düzeltme geçmişi (en yeni 20)",
  "Revision": "Sürüm",
  "Current authority at refresh": "Yenileme anında güncel yetki",
  "Stale authority": "Güncel olmayan yetki",
  "requested": "istenen",
  "Applied": "Uygulanan",
  "bound": "sınır",
  "No matched URL": "Eşleşen URL yok",
  "Earlier corrections exist; this bounded view is incomplete.": "Daha eski düzeltmeler var; bu sınırlı görünüm eksiktir.",
  "Correct the exact manual report; original evidence remains in history": "Tam elle bildirimi düzelt; özgün kanıt geçmişte kalır",
  "Supply one actual customer observation": "Bir gerçek müşteri gözlemi sağla",
  "A current actual manual business assessment and verified exact HTTPS website origin are required. Missing evidence does not establish a location or profile.": "Güncel gerçek elle işletme değerlendirmesi ve doğrulanmış tam HTTPS site kökeni gerekir. Eksik kanıt bir konumu veya profili kanıtlamaz.",
  "First 20 current business/origin candidates only.": "Yalnızca ilk 20 güncel işletme/köken adayı.",
  "Independent customer-reported Google organic-link observation (no automatic search)": "Bağımsız müşterinin bildirdiği Google organik bağlantı gözlemi (otomatik arama yok)",
  "Actual manual business (blank location = general service area)": "Gerçek elle işletme (boş konum = genel hizmet bölgesi)",
  "Exact verified own-website origin": "Doğrulanmış tam kendi site kökeni",
  "Requested actual configured business location/service area": "İstenen gerçek yapılandırılmış işletme konumu/hizmet bölgesi",
  "Requested configured language (or unknown)": "İstenen yapılandırılmış dil (veya bilinmiyor)",
  "Unknown": "Bilinmiyor",
  "Requested device context": "İstenen cihaz bağlamı",
  "Applied coarse region (customer report; blank = unknown)": "Uygulanan genel bölge (müşteri bildirimi; boş = bilinmiyor)",
  "Applied language tag (blank = unknown)": "Uygulanan dil etiketi (boş = bilinmiyor)",
  "Applied device (customer report; not controlled by us)": "Uygulanan cihaz (müşteri bildirimi; tarafımızca kontrol edilmiyor)",
  "Actual human query": "Gerçek insan sorgusu",
  "Opaque own observation reference (no provider/account/person ID)": "Opak kendi gözlem referansı (sağlayıcı/hesap/kişi kimliği yok)",
  "Actual observed date with timezone": "Saat dilimiyle gerçek gözlem tarihi",
  "Declared inspected-link bound (1–20)": "Beyan edilen incelenmiş bağlantı sınırı (1–20)",
  "Actual inspected count (0 only for unavailable)": "Gerçek incelenen sayı (0 yalnızca kullanılamıyor için)",
  "Reported coverage outcome": "Bildirilen kapsam sonucu",
  "Human ordinal among actually inspected organic links (not universal rank)": "Gerçekte incelenen organik bağlantılar arasında insan sıra numarası (evrensel sıralama değildir)",
  "Matched exact own-website URL (no query/credentials)": "Eşleşen tam kendi site URL’si (sorgu/kimlik bilgisi yok)",
  "Minimized independent evidence and coverage/context limitations (no copied result content)": "Sınırlandırılmış bağımsız kanıt ve kapsam/bağlam sınırları (kopyalanmış sonuç içeriği yok)",
  "Human report/correction reason": "İnsan bildirimi/düzeltme gerekçesi",
  "I have independent rights to store this own numerical observation under the disclosed private export/retention/deletion/backup policy.": "Bu kendi sayısal gözlemimi açıklanan özel dışa aktarma/saklama/silme/yedekleme politikası kapsamında saklamak için bağımsız haklara sahibim.",
  "No API/GBP content, snippets/screenshots, competitor inventories or private observer identifiers were copied or used.": "API/GBP içeriği, alıntılar/ekran görüntüleri, rakip envanterleri veya özel gözlemci tanımlayıcıları kopyalanmadı veya kullanılmadı.",
  "Save immutable customer report (no search run)": "Değiştirilemez müşteri bildirimini kaydet (arama çalıştırılmaz)",
  "Cancel correction": "Düzeltmeyi iptal et",
  "Read-only retained human reports; current verified owner/admin is required to supply or correct evidence.": "Salt okunur saklanan insan bildirimleri; kanıt sağlamak veya düzeltmek için güncel doğrulanmış işletme sahibi/yönetici gerekir.",
  "Select an authorized project.": "Yetkili bir proje seçin.",
  "Local observation history or current project/session authority is unavailable.": "Yerel gözlem geçmişi veya güncel proje/oturum yetkisi kullanılamıyor.",
  "Exact history unavailable. Refresh before another report.": "Tam geçmiş kullanılamıyor. Başka bir bildirimden önce yenileyin.",
  "Exact human report recorded; no search or provider request ran.": "Tam insan bildirimi kaydedildi; arama veya sağlayıcı isteği çalıştırılmadı.",
  "Current scope/revision or fields denied. Refresh before another report.": "Güncel kapsam/sürüm veya alanlar reddedildi. Başka bir bildirimden önce yenileyin.",
  "Save outcome uncertain; check the exact request key.": "Kaydetme sonucu belirsiz; tam istek anahtarını kontrol edin.",
  "Report reconciled from immutable history; no command replayed.": "Bildirim değiştirilemez geçmişten uzlaştırıldı; komut yeniden çalıştırılmadı.",
  "No recorded report found; deliberately retry the same exact report if needed.": "Kayıtlı bildirim bulunamadı; gerekirse aynı bildirimi bilinçli olarak yeniden deneyin.",
  "Current report outcome/authority unavailable; no replay.": "Güncel bildirim sonucu/yetkisi kullanılamıyor; yeniden çalıştırma yok."
};
