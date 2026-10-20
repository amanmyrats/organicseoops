import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, effect, OnInit, signal, computed } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi } from '../account/account-api';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';

type ActionRow = { action_id: string; revision: number; state: string; action_kind: string;
  source_type: string; source_id: number; source_current: boolean; affected_urls: string[];
  assignee_id: number | null; acceptance_criteria: string; reason: string; change_summary: string;
  verification_note: string; outcome_note: string; implemented_at: string | null; verified_at: string | null;
  outcome_reviewed_at: string | null; execution: string; recorded_at?: string };
type SourceOption = { id: string; label: string; actionKind: string };
type Assignee = { userId: number; label: string };
type UsefulnessChallenge = { method: string; source: { method: string; acknowledging_actor_id: number;
  evidence: Record<string, unknown>; interpretation: string }; source_digest: string;
  receipt_proof: string; expires_at: string; acknowledgment_recorded: false };
type UsefulnessSelection = { row: ActionRow; challenge: UsefulnessChallenge };
type UsefulnessHistory = Record<string, unknown> & { source?: Record<string, unknown> };
const ACK_METHOD = 'bounded-audit-usefulness-ack-v1';
const ACK_INTERPRETATION = 'explicit_subjective_useful_next_action_not_implementation_or_seo_outcome';
const ACK_SCOPE = 'historical_organization_first_acknowledgment_within_selected_project_not_current_source_use';
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const sha = (value: unknown) => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const aware = (value: unknown): value is string => typeof value === 'string'
  && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const dated = (value: unknown): value is string => aware(value) && Date.parse(value) <= Date.now();
const exactKeys = (value: Record<string, unknown>, keys: string[]) => Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
function sorted(value: unknown): unknown {
  return object(value) ? Object.fromEntries(Object.keys(value).sort().map(key => [key, sorted(value[key])])) : value;
}
const same = (left: unknown, right: unknown) => JSON.stringify(sorted(left)) === JSON.stringify(sorted(right));
async function declarationDigest(value: Record<string, unknown>) {
  const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(sorted(value))));
  return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, '0')).join('');
}

function isAction(value: unknown): value is ActionRow {
  if (!value || typeof value !== 'object') return false;
  const row = value as Record<string, unknown>;
  return typeof row['action_id'] === 'string' && Number.isSafeInteger(row['revision'])
    && typeof row['state'] === 'string' && typeof row['action_kind'] === 'string'
    && typeof row['source_type'] === 'string' && ['intent', 'opportunity'].includes(row['source_type']) && Number.isSafeInteger(row['source_id'])
    && typeof row['source_current'] === 'boolean' && Array.isArray(row['affected_urls'])
    && row['affected_urls'].every((item: unknown) => typeof item === 'string')
    && (row['assignee_id'] === null || Number.isSafeInteger(row['assignee_id']))
    && ['acceptance_criteria', 'reason', 'change_summary', 'verification_note', 'outcome_note']
      .every((key) => typeof row[key] === 'string')
    && ['implemented_at', 'verified_at', 'outcome_reviewed_at']
      .every((key) => row[key] === null || typeof row[key] === 'string')
    && row['execution'] === 'human_only_no_website_change';
}

const nextStates: Record<string, string[]> = {
  proposed: ['accepted', 'dismissed'], accepted: ['in_progress', 'proposed', 'dismissed'],
  in_progress: ['implemented', 'proposed', 'dismissed'], implemented: ['verified', 'proposed'],
  verified: ['outcome_reviewed', 'proposed'], outcome_reviewed: ['proposed'], dismissed: ['proposed'],
};

@Component({
  selector: 'app-action-workflow',
  imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="actions-title">
      <h1 id="actions-title">{{ t("Assigned SEO actions and manual change history") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish action interface draft in local development. Stored source/status values, mixed source labels and other screens remain English; bilingual approval is pending.") }}</p> }
      <p><a routerLink="/app">{{ t("Return to workspace") }}</a> · <a [routerLink]="['/app/intent', organizationId, projectId]">{{ t("Review intent and page mapping") }}</a></p>
      <p>{{ t("Proposals require an authorized human approval. Implementation, technical verification and observed outcome are separate records. None of these controls changes a website, publishes content or proves uplift.") }}</p>
      @if (loading()) { <p role="status">{{ t("Loading current project actions.") }}</p> }
      @if (error()) { <p role="alert">{{ t(error()) }}</p> }
      @if (!loading() && !error()) {
        <button type="button" (click)="load()" [disabled]="busy()">{{ t("Refresh action history") }}</button>
        @if (!demo()) {
          <button type="button" (click)="inspectUsefulnessHistory()" [disabled]="busy() || usefulnessUnknown()">{{ t("Inspect retained usefulness history for this project") }}</button>
        }
        @if (truncated()) { <p>{{ t("Only the first 50 recent action/source records are shown.") }}</p> }
        @if (!actions().length) { <p>{{ t("No manual action is recorded for this project.") }}</p> }
        <ul [attr.aria-label]="t('Project human action state')">
          @for (row of actions(); track row.action_id) {
            <li>
              <h2><span lang="en">{{ row.action_kind }} · {{ row.state }}</span> · {{ t("revision") }} {{ row.revision }}</h2>
              <p>{{ t("Source:") }} <span lang="en">{{ row.source_type }}</span> {{ t("review") }} {{ row.source_id }} — {{ t(row.source_current ? 'current' : 'historical/revoked; correction requires a current proposal') }}.</p>
              <p>{{ t("Affected project URLs:") }} <span lang="">{{ row.affected_urls.join(', ') }}</span>. {{ t("Assigned user") }} {{ row.assignee_id }}.</p>
              <p>{{ t("Acceptance criteria:") }} <span lang="">{{ row.acceptance_criteria }}</span> · {{ t("Review rationale:") }} <span lang="">{{ row.reason }}</span></p>
              @if (row.implemented_at) { <p>{{ t("Implementation claimed") }} {{ row.implemented_at }}: <span lang="">{{ row.change_summary }}</span>. {{ t("This alone is not verification.") }}</p> }
              @if (row.implemented_at) { <p><a [routerLink]="['/app/outcomes', organizationId, projectId, row.action_id]">{{ t("Inspect source-compatible before/after observations") }}</a></p> }
              @if (row.verified_at) { <p>{{ t("Technical verification reviewed") }} {{ row.verified_at }}: <span lang="">{{ row.verification_note }}</span>.</p> }
              @if (row.outcome_reviewed_at) { <p>{{ t("Outcome reviewed") }} {{ row.outcome_reviewed_at }}: <span lang="">{{ row.outcome_note }}</span>. {{ t("Before/after is not causal proof.") }}</p> }
              <button type="button" (click)="history(row.action_id)" [disabled]="busy()">{{ t("Inspect immutable action revisions") }}</button>
              @if (!demo() && row.state === 'accepted' && row.source_type === 'opportunity' && row.source_current) {
                <button type="button" (click)="inspectAuditSource(row)" [disabled]="busy()">{{ t("Inspect this accepted action's bounded audit source") }}</button>
                @if (canApprove()) {
                  <button type="button" (click)="prepareUsefulness(row)" [disabled]="busy() || usefulnessUnknown()">{{ t("Review this exact action for a usefulness acknowledgment") }}</button>
                }
              }
              @if (row.source_current && (canApprove() || row.assignee_id === currentUserId())) {
                <form (submit)="transition($event, row)" (input)="invalidateActionEvidence()" (change)="invalidateActionEvidence()">
                  <label [for]="'action-next-' + row.action_id">{{ t("Next human state") }}</label>
                  <select [id]="'action-next-' + row.action_id" name="state" required>
                    @for (state of allowedTransitions(row); track state) { <option lang="en" [value]="state">{{ state }}</option> }
                  </select>
                  <label [for]="'action-reason-' + row.action_id">{{ t("Reason for transition") }}</label>
                  <input lang="" [id]="'action-reason-' + row.action_id" name="reason" maxlength="500" required />
                  <label [for]="'action-implementation-' + row.action_id">{{ t("Actual implementation time (when marking implemented)") }}</label>
                  <input [id]="'action-implementation-' + row.action_id" name="implemented_at" type="datetime-local" />
                  <label [for]="'action-summary-' + row.action_id">{{ t("Manual change summary (implementation and later states)") }}</label>
                  <input lang="" [id]="'action-summary-' + row.action_id" name="change_summary" maxlength="500" [value]="row.change_summary" />
                  <label [for]="'action-verify-' + row.action_id">{{ t("Technical verification note (when verifying)") }}</label>
                  <input lang="" [id]="'action-verify-' + row.action_id" name="verification_note" maxlength="500" [value]="row.verification_note" />
                  <label [for]="'action-outcome-' + row.action_id">{{ t("Outcome note (when reviewing outcome; unknown is allowed)") }}</label>
                  <input lang="" [id]="'action-outcome-' + row.action_id" name="outcome_note" maxlength="500" />
                  <button type="submit" [disabled]="busy()">{{ t("Record manual transition") }}</button>
                </form>
              }
            </li>
          }
        </ul>
        @if (auditSourceLoading()) { <p role="status">{{ t("Inspecting current private audit and human decision evidence.") }}</p> }
        @if (auditSourceError()) { <p role="alert">{{ t(auditSourceError()) }}</p> }
        @if (auditSource(); as source) {
          <section aria-labelledby="action-audit-source-title">
            <h2 id="action-audit-source-title">{{ t("Current bounded audit and human acceptance evidence") }}</h2>
            <p>{{ t("Inspection does not establish customer usefulness, accepted first value, first-ever occurrence, current permission to reuse the source, implementation or causal improvement. No job, conversion, new approval or website change is recorded.") }}</p>
            <p>{{ t("Marked audit") }} {{ source['job_id'] }} {{ t("completed") }} {{ source['audit_completed_at'] }}. {{ t("Raw diagnostics") }} {{ source['diagnostics_id'] }} {{ t("observed") }} {{ source['diagnostics_observed_at'] }}; {{ t("finding") }} {{ source['finding_id'] }} {{ t("detected") }} {{ source['finding_detected_at'] }}: <span lang="en">{{ source['detector'] }}</span>.</p>
            <p>{{ t("Human opportunity") }} {{ source['opportunity_id'] }} {{ t("reviewed") }} {{ source['opportunity_reviewed_at'] }}; {{ t("action review") }} {{ source['action_review_id'] }} {{ t("accepted") }} {{ source['action_accepted_at'] }} {{ t("for") }} <span lang="en">{{ source['action_kind'] }}</span>.</p>
            <p>{{ t("Bounded discovered HTTP sample—not the complete site or a clean-site result. Only supported retained UTF-8 raw title/description candidates can supply this evidence.") }}</p>
            <p>{{ t("Audit source SHA-256:") }} <code>{{ source['audit_source_digest'] }}</code>; {{ t("exact decision SHA-256:") }} <code>{{ source['decision_digest'] }}</code>; {{ t("private page SHA-256:") }} <code>{{ source['page_sha256'] }}</code>.</p>
          </section>
        }
        <section aria-labelledby="audit-usefulness-title">
          <h2 id="audit-usefulness-title">{{ t("Optional subjective usefulness acknowledgment") }}</h2>
          <p>{{ t("Organization") }} {{ organizationId }} · {{ t("project") }} {{ projectId }}. {{ t("This declares that the exact bounded raw-metadata audit and human-accepted next action helped identify useful manual work. It does not verify business facts, a clean whole site, implementation or SEO improvement, and does not approve a website change. Inspection records nothing. Older untracked organizations remain unknown.") }}</p>
          @if (usefulnessError()) { <p role="alert">{{ t(usefulnessError()) }}</p> }
          @if (usefulnessMessage()) { <p role="status">{{ t(usefulnessMessage()) }}</p> }
          @if (usefulnessChallenge(); as proof) {
            <p>{{ t("Frozen action") }} {{ proof.row.action_id }} · {{ t("revision") }} {{ proof.row.revision }} · <span lang="en">{{ proof.row.action_kind }}</span> · <span lang="">{{ proof.row.acceptance_criteria }}</span>.</p>
            <p>{{ t("Original audit completed") }} {{ proof.challenge.source['evidence']['audit_completed_at'] }}; {{ t("original action accepted") }} {{ proof.row.recorded_at }}. {{ t("Declaration SHA-256") }} {{ proof.challenge.source_digest }}. {{ t("Proof expires") }} {{ proof.challenge.expires_at }}.</p>
            <label><input type="checkbox" [checked]="usefulnessChecked()" (change)="usefulnessChecked.set($any($event.target).checked)" [disabled]="busy() || usefulnessUnknown()" />
              {{ t("This exact audit and accepted next action helped me identify useful manual work, and I want to record that subjective acknowledgment.") }}</label>
            <button type="button" (click)="acknowledgeUsefulness()" [disabled]="busy() || usefulnessUnknown() || !usefulnessChecked()">{{ t("Record this usefulness acknowledgment") }}</button>
          }
          @if (usefulnessUnknown()) {
            <p>{{ t("The acknowledgment outcome is unknown. No new proof or acknowledgment is issued or replayed automatically.") }}</p>
            <button type="button" (click)="lookupUsefulness()" [disabled]="busy()">{{ t("Look up this exact uncertain usefulness acknowledgment") }}</button>
            @if (usefulnessCanRetry()) {
              <label><input type="checkbox" [checked]="usefulnessChecked()" (change)="usefulnessChecked.set($any($event.target).checked)" [disabled]="busy()" />{{ t("I still want to record the same frozen subjective declaration.") }}</label>
              <button type="button" (click)="acknowledgeUsefulness(true)" [disabled]="busy() || !usefulnessChecked()">{{ t("Retry the same unexpired usefulness proof after lookup") }}</button>
            }
          }
          @if (usefulnessHistory(); as saved) {
            @if (saved['state'] === 'recorded') {
              <p>{{ t("First server usefulness acknowledgment") }} {{ saved['acknowledged_at'] }} · {{ t("tracking began") }} {{ saved['tracking_started_at'] }}. {{ t("Original audit") }} {{ saved.source?.['audit_completed_at'] }}; {{ t("original human acceptance") }} {{ saved.source?.['action_accepted_at'] }}. {{ t("Historical declaration, not current permission to reuse this source or a lifetime conversion count.") }}</p>
              <p>{{ t("Original action") }} {{ saved['action_id'] }} · {{ t("revision") }} {{ saved['revision'] }}. {{ t("Retained source SHA-256") }} {{ saved['source_digest'] }}.</p>
            } @else { <p>{{ t("No retained acknowledgment observed for this selected project; another project's history is not disclosed. Unknown tracking is not zero usefulness.") }}</p> }
          }
        </section>
        @if (historyRows().length) {
          <section aria-labelledby="action-history-title"><h2 id="action-history-title">{{ t("Immutable action history") }}</h2>
            <ol>@for (row of historyRows(); track row.action_id + ':' + row.revision) {
              <li><span lang="en">{{ row.state }}</span> · {{ t("revision") }} {{ row.revision }} · <span lang="">{{ row.reason }}</span> · {{ row.implemented_at || t('no implementation recorded') }}</li>
            }</ol>
          </section>
        }
        @if (canApprove()) {
          <section aria-labelledby="propose-title"><h2 id="propose-title">{{ t("Propose a manual action") }}</h2>
            @if (!sources().length || !assignees().length) {
              <p>{{ t("Review a current intent-page proposal or page-anchored opportunity and an eligible assignee first.") }}</p>
            } @else {
              <form (submit)="create($event)" (input)="invalidateActionEvidence()" (change)="invalidateActionEvidence()">
                <label for="action-source">{{ t("Reviewed source (queries alone are not page evidence)") }}</label>
                <select id="action-source" name="source" required>
                  @for (source of sources(); track source.id) { <option lang="" [value]="source.id">{{ source.label }}</option> }
                </select>
                <label for="action-kind">{{ t("Action for a page opportunity (intent mapping uses its recorded action)") }}</label>
                <select id="action-kind" name="action_kind">
                  @for (kind of actionKinds; track kind) { <option lang="en" [value]="kind">{{ kind }}</option> }
                </select>
                <label for="action-destination">{{ t("Exact project destination for page-opportunity create/merge/redirect only") }}</label>
                <input lang="" id="action-destination" name="destination_page" type="url" maxlength="512" />
                <label for="action-assignee">{{ t("Eligible assignee") }}</label>
                <select id="action-assignee" name="assignee_id" required>
                  @for (person of assignees(); track person.userId) { <option lang="" [value]="person.userId">{{ person.label }}</option> }
                </select>
                <label for="action-criteria">{{ t("Acceptance criteria (what needs doing, not a success claim)") }}</label>
                <textarea lang="" id="action-criteria" name="acceptance_criteria" maxlength="500" required></textarea>
                <label for="action-proposal-reason">{{ t("Reason for the proposed action") }}</label>
                <textarea lang="" id="action-proposal-reason" name="reason" maxlength="500" required></textarea>
                <button type="submit" [disabled]="busy()">{{ t("Save unapproved proposal") }}</button>
              </form>
            }
          </section>
        }
        @if (message()) { <p role="status">{{ t(message()) }}</p> }
      }
    </section>
  `,
  styles: `
    li { margin-block: 1.5rem; }
    form { display: grid; gap: 0.55rem; max-width: 48rem; }
  `,
})
export class ActionWorkflow implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  t(text: string) { return this.uiLanguage() === 'tr' ? actionTurkish[text] ?? text : text; }
  readonly actionKinds = ['keep', 'refresh', 'merge', 'redirect', 'retire', 'create'];
  readonly loading = signal(true);
  readonly error = signal('');
  readonly message = signal('');
  readonly busy = signal(false);
  readonly actions = signal<ActionRow[]>([]);
  readonly historyRows = signal<ActionRow[]>([]);
  readonly sources = signal<SourceOption[]>([]);
  readonly assignees = signal<Assignee[]>([]);
  readonly truncated = signal(false);
  readonly currentUserId = signal(0);
  readonly canApprove = signal(false);
  readonly demo = signal(false);
  readonly auditSource = signal<Record<string, unknown> | null>(null);
  readonly auditSourceError = signal('');
  readonly auditSourceLoading = signal(false);
  readonly usefulnessChallenge = signal<UsefulnessSelection | null>(null);
  readonly usefulnessHistory = signal<UsefulnessHistory | null>(null);
  readonly usefulnessChecked = signal(false);
  readonly usefulnessUnknown = signal(false);
  readonly usefulnessCanRetry = signal(false);
  readonly usefulnessError = signal('');
  readonly usefulnessMessage = signal('');
  private usefulnessEpoch = 0;
  private pendingUsefulness: UsefulnessSelection | null = null;
  private usefulnessExpiry: ReturnType<typeof setTimeout> | null = null;
  organizationId = 0;
  projectId = 0;
  private generation = 0;
  private requestKey = '';
  private pendingOperation = '';

  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi,
              private readonly destroyRef: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t('Human SEO action history')} — OrganicSEOOps`));
    destroyRef.onDestroy(() => { this.generation++; this.clearAuditSource(); this.busy.set(false); });
  }

  private clearAuditSource() {
    this.auditSource.set(null); this.auditSourceError.set(''); this.auditSourceLoading.set(false);
    this.clearUsefulness();
  }

  private clearUsefulness() {
    this.usefulnessEpoch++;
    if (this.usefulnessExpiry) clearTimeout(this.usefulnessExpiry);
    this.usefulnessExpiry = null; this.pendingUsefulness = null;
    this.usefulnessChallenge.set(null); this.usefulnessHistory.set(null); this.usefulnessChecked.set(false);
    this.usefulnessUnknown.set(false); this.usefulnessCanRetry.set(false);
    this.usefulnessError.set(''); this.usefulnessMessage.set('');
  }
  private usefulnessCurrent(epoch: number) { return epoch === this.usefulnessEpoch && !this.destroyRef.destroyed; }
  invalidateActionEvidence() { this.generation++; this.clearAuditSource(); this.busy.set(false); }
  private expireUsefulness(value: UsefulnessSelection) {
    if (this.usefulnessExpiry) clearTimeout(this.usefulnessExpiry);
    this.usefulnessExpiry = setTimeout(() => {
      this.usefulnessChallenge.set(null); this.usefulnessChecked.set(false); this.usefulnessCanRetry.set(false);
      if (this.pendingUsefulness) this.pendingUsefulness.challenge.receipt_proof = '';
      this.usefulnessMessage.set('Original usefulness proof expired. Inspect retained history; no acknowledgment is retried.');
    }, Math.max(0, Date.parse(value.challenge.expires_at) - Date.now()));
  }

  private async currentAuditAction(row: ActionRow, organizationId: number, projectId: number, approving = false) {
    const [history, context] = await Promise.all([this.api.actionHistory(organizationId, projectId, row.action_id),
      this.api.projectOnboarding(organizationId, projectId)]);
    const project = context.body['project'] as Record<string, unknown> | undefined;
    const latest = Array.isArray(history.body['history']) ? history.body['history'][0] : null;
    return history.status === 200 && history.body['project_id'] === projectId && isAction(latest)
      && same(latest, row) && context.status === 200 && project?.['id'] === projectId
      && project['organization_id'] === organizationId
      && (!approving || history.body['current_user_id'] === this.currentUserId()
        && typeof project['role'] === 'string' && ['owner', 'admin'].includes(project['role']))
      && (context.body['configuration'] as Record<string, unknown> | undefined)?.['source_choice'] !== 'synthetic_demo';
  }

  private async readUsefulnessHistory(organizationId: number, projectId: number, epoch: number) {
    const response = await this.api.firstProjectAuditUsefulness(organizationId, projectId);
    if (!this.usefulnessCurrent(epoch)) throw new Error();
    const history = validateUsefulnessHistory(response.body, organizationId, projectId);
    const context = await this.api.projectOnboarding(organizationId, projectId);
    const project = context.body['project'] as Record<string, unknown> | undefined;
    if (response.status !== 200 || !history || context.status !== 200 || project?.['id'] !== projectId
      || project['organization_id'] !== organizationId
      || (context.body['configuration'] as Record<string, unknown> | undefined)?.['source_choice'] === 'synthetic_demo') throw new Error();
    return structuredClone(history);
  }

  async inspectUsefulnessHistory() {
    if (this.busy() || this.loading() || this.error() || this.demo() || this.usefulnessUnknown()) return;
    this.clearUsefulness(); const epoch = this.usefulnessEpoch;
    const organizationId = this.organizationId, projectId = this.projectId;
    this.busy.set(true);
    try {
      const saved = await this.readUsefulnessHistory(organizationId, projectId, epoch);
      if (this.usefulnessCurrent(epoch)) this.usefulnessHistory.set(saved);
    } catch { if (this.usefulnessCurrent(epoch)) this.usefulnessError.set('Retained usefulness history unavailable. Refresh this project.'); }
    finally { if (this.usefulnessCurrent(epoch)) this.busy.set(false); }
  }

  async prepareUsefulness(row: ActionRow) {
    if (this.busy() || this.loading() || this.error() || this.demo() || !this.canApprove() || this.usefulnessUnknown()
      || row.state !== 'accepted' || row.source_type !== 'opportunity' || !row.source_current
      || !this.actions().some(current => same(current, row))) return;
    this.clearUsefulness(); const epoch = this.usefulnessEpoch, frozen = structuredClone(row);
    const organizationId = this.organizationId, projectId = this.projectId;
    this.busy.set(true);
    try {
      if (!await this.currentAuditAction(frozen, organizationId, projectId, true)) throw new Error();
      if (!this.usefulnessCurrent(epoch)) return;
      const result = await this.api.firstProjectAuditUsefulness(organizationId, projectId, frozen.action_id, frozen.revision);
      if (!this.usefulnessCurrent(epoch)) return;
      const challenge = await validateUsefulnessChallenge(result.body, organizationId, projectId, frozen, this.currentUserId());
      if (result.status !== 200 || !challenge || !await this.currentAuditAction(frozen, organizationId, projectId, true)) throw new Error();
      if (!this.usefulnessCurrent(epoch)) return;
      if (Date.parse(challenge.expires_at) <= Date.now()) throw new Error();
      const selection = { row: frozen, challenge };
      this.usefulnessChallenge.set(selection); this.expireUsefulness(selection);
    } catch { if (this.usefulnessCurrent(epoch)) {
      this.usefulnessChallenge.set(null); this.usefulnessError.set('Current usefulness source, actor or proof unavailable or changed. No acknowledgment recorded by inspection.');
    } } finally { if (this.usefulnessCurrent(epoch)) this.busy.set(false); }
  }

  private matchingUsefulness(saved: Record<string, unknown>, selected: UsefulnessSelection) {
    return saved['state'] === 'recorded' && saved['action_id'] === selected.row.action_id
      && saved['revision'] === selected.row.revision && saved['declaration_digest'] === selected.challenge.source_digest
      && same(saved['source'], selected.challenge.source['evidence']);
  }
  private showUsefulness(saved: Record<string, unknown>) {
    this.clearUsefulness(); this.usefulnessHistory.set(saved);
    this.usefulnessMessage.set('Exact original usefulness acknowledgment confirmed in retained history. No website change or SEO improvement is confirmed.');
  }

  async acknowledgeUsefulness(retry = false) {
    const selected = retry ? this.pendingUsefulness : this.usefulnessChallenge();
    if (!selected || this.busy() || !this.usefulnessChecked() || (retry ? !this.usefulnessUnknown()
      || !this.usefulnessCanRetry() : this.usefulnessUnknown())) return;
    const frozen = structuredClone(selected), epoch = this.usefulnessEpoch;
    const organizationId = this.organizationId, projectId = this.projectId;
    this.busy.set(true); this.usefulnessError.set(''); this.usefulnessCanRetry.set(false);
    let sent = false;
    try {
      if (!await this.currentAuditAction(frozen.row, organizationId, projectId, true)) throw new Error();
      if (!this.usefulnessCurrent(epoch)) return;
      if (!frozen.challenge.receipt_proof || Date.parse(frozen.challenge.expires_at) <= Date.now()) throw new Error();
      this.pendingUsefulness = frozen; sent = true;
      const result = await this.api.acknowledgeFirstProjectAuditUsefulness(organizationId, projectId,
        frozen.row.action_id, frozen.row.revision, frozen.challenge.receipt_proof);
      if (!this.usefulnessCurrent(epoch)) return;
      const received = validateUsefulnessHistory(result.body, organizationId, projectId);
      if (result.status !== 200 || !received || !this.matchingUsefulness(received, frozen)
        || !await this.currentAuditAction(frozen.row, organizationId, projectId, true)) throw new Error();
      if (!this.usefulnessCurrent(epoch)) return;
      const saved = await this.readUsefulnessHistory(organizationId, projectId, epoch);
      if (!this.usefulnessCurrent(epoch)) return;
      if (!this.matchingUsefulness(saved, frozen) || !same(saved, received)) throw new Error();
      this.showUsefulness(saved); this.busy.set(false);
    } catch { if (this.usefulnessCurrent(epoch)) {
      this.usefulnessChallenge.set(null); this.usefulnessChecked.set(false);
      if (sent || retry) {
        this.pendingUsefulness = frozen; this.usefulnessUnknown.set(true); this.expireUsefulness(frozen);
        this.usefulnessError.set('Usefulness acknowledgment outcome unknown. Look up exact retained history before any deliberate retry.');
      } else {
        this.clearUsefulness(); this.busy.set(false);
        this.usefulnessError.set('Current action, source authority or original proof changed. Refresh before acknowledging.');
      }
    } } finally { if (this.usefulnessCurrent(epoch)) this.busy.set(false); }
  }

  async lookupUsefulness() {
    const frozen = this.pendingUsefulness;
    if (!frozen || !this.usefulnessUnknown() || this.busy()) return;
    const epoch = this.usefulnessEpoch, organizationId = this.organizationId, projectId = this.projectId;
    this.busy.set(true); this.usefulnessError.set(''); this.usefulnessCanRetry.set(false); this.usefulnessChecked.set(false);
    try {
      const saved = await this.readUsefulnessHistory(organizationId, projectId, epoch);
      if (!this.usefulnessCurrent(epoch)) return;
      if (saved['state'] === 'recorded') {
        if (!this.matchingUsefulness(saved, frozen)) throw new Error();
        this.showUsefulness(saved); this.busy.set(false);
      } else if (saved['state'] === 'not_observed_for_project' && frozen.challenge.receipt_proof
        && Date.parse(frozen.challenge.expires_at) > Date.now()
        && await this.currentAuditAction(frozen.row, organizationId, projectId, true)) {
        if (!this.usefulnessCurrent(epoch)) return;
        this.usefulnessCanRetry.set(Date.parse(frozen.challenge.expires_at) > Date.now());
        this.usefulnessMessage.set('No exact retained acknowledgment found. Only the same original unexpired proof may be retried deliberately; the server revalidates its source.');
      } else this.usefulnessMessage.set('No exact acknowledgment confirmed; original proof or current source is unavailable. No retry allowed.');
    } catch { if (this.usefulnessCurrent(epoch)) this.usefulnessError.set('Exact usefulness lookup unavailable or does not match this declaration. No acknowledgment replayed.'); }
    finally { if (this.usefulnessCurrent(epoch)) this.busy.set(false); }
  }

  ngOnInit() {
    void this.loadProductLanguage();
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      this.organizationId = Number(params.get('organizationId'));
      this.projectId = Number(params.get('projectId'));
      this.generation++;
      this.clearAuditSource(); this.demo.set(false);
      this.actions.set([]); this.historyRows.set([]); this.sources.set([]); this.assignees.set([]);
      this.currentUserId.set(0); this.canApprove.set(false); this.message.set(''); this.error.set('');
      this.busy.set(false); this.requestKey = ''; this.pendingOperation = '';
      if (Number.isSafeInteger(this.organizationId) && this.organizationId > 0
          && Number.isSafeInteger(this.projectId) && this.projectId > 0) void this.load();
      else { this.loading.set(false); this.error.set('Select an authorized project.'); }
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

  allowedTransitions(row: ActionRow) {
    const options = nextStates[row.state] || [];
    return options.filter((state) => ['in_progress', 'implemented'].includes(state)
      ? row.assignee_id === this.currentUserId()
      : this.canApprove());
  }

  async load() {
    const generation = ++this.generation;
    this.clearAuditSource(); this.demo.set(false); this.busy.set(false);
    this.loading.set(true); this.error.set(''); this.historyRows.set([]); this.actions.set([]);
    this.sources.set([]); this.assignees.set([]); this.canApprove.set(false);
    try {
      const [actions, project, intents, findings] = await Promise.all([
        this.api.projectActions(this.organizationId, this.projectId),
        this.api.projectOnboarding(this.organizationId, this.projectId),
        this.api.intentClusters(this.organizationId, this.projectId),
        this.api.projectFindings(this.organizationId, this.projectId),
      ]);
      if (generation !== this.generation) return;
      if ([actions.status, project.status, intents.status, findings.status].some((status) => status !== 200)
          || actions.body['project_id'] !== this.projectId || intents.body['project_id'] !== this.projectId
          || findings.body['project_id'] !== this.projectId || !project.body['project']
          || !Array.isArray(actions.body['actions']) || !Array.isArray(intents.body['clusters'])
          || !Array.isArray(findings.body['findings']) || !Number.isSafeInteger(actions.body['current_user_id'])
          || !(actions.body['actions'] as unknown[]).every(isAction)) throw new Error();
      const info = project.body['project'] as Record<string, unknown>;
      if (info['id'] !== this.projectId || info['organization_id'] !== this.organizationId
          || typeof info['role'] !== 'string' || !['owner', 'admin', 'member', 'viewer'].includes(info['role'])) throw new Error();
      this.currentUserId.set(Number(actions.body['current_user_id']));
      this.demo.set((project.body['configuration'] as Record<string, unknown> | undefined)?.['source_choice'] === 'synthetic_demo');
      this.actions.set(actions.body['actions'] as ActionRow[]);
      this.canApprove.set(['owner', 'admin'].includes(info['role']));
      this.truncated.set(actions.body['has_more'] === true || intents.body['has_more'] === true
        || findings.body['has_more'] === true);
      const sourceOptions: SourceOption[] = [];
      for (const item of intents.body['clusters'] as Record<string, unknown>[]) {
        if (Number.isSafeInteger(item['review_id']) && item['source_current'] === true
            && typeof item['label'] === 'string' && typeof item['proposed_action'] === 'string'
            && item['proposed_action'] !== 'unselected') {
          sourceOptions.push({ id: `intent:${item['review_id']}`, label: `Intent: ${item['label']} (${item['proposed_action']})`,
            actionKind: item['proposed_action'] });
        }
      }
      for (const item of findings.body['findings'] as Record<string, unknown>[]) {
        const review = item['review'];
        if (item['source_current'] === true && typeof item['subject'] === 'string'
            && item['subject'].startsWith('https://') && review && typeof review === 'object'
            && Number.isSafeInteger((review as Record<string, unknown>)['id'])
            && ((item['evidence'] && typeof item['evidence'] === 'object'
                 && (item['evidence'] as Record<string, unknown>)['dimension'] === 'page')
                || Number.isSafeInteger(item['source_diagnostics_id'])
                || Number.isSafeInteger(item['source_indexation_id'])
                || Number.isSafeInteger(item['source_performance_id']))) {
          sourceOptions.push({ id: `opportunity:${(review as Record<string, unknown>)['id']}`,
            label: `Reviewed page finding: ${item['subject']}`, actionKind: '' });
        }
      }
      this.sources.set(sourceOptions.slice(0, 50));
      if (this.canApprove()) {
        const team = await this.api.team(this.organizationId);
        if (generation !== this.generation) return;
        if (team.status === 200 && Array.isArray(team.body['members'])) {
          this.assignees.set((team.body['members'] as Record<string, unknown>[])
            .filter((member) => Number.isSafeInteger(member['user_id']) && typeof member['email'] === 'string'
              && typeof member['role'] === 'string' && ['owner', 'admin', 'member'].includes(member['role'])
              && (info['access_restricted'] !== true || member['role'] === 'owner'
                  || Array.isArray(member['project_ids']) && member['project_ids'].includes(this.projectId)))
            .map((member) => ({ userId: Number(member['user_id']), label: String(member['email']) })));
        }
      }
    } catch {
      if (generation === this.generation) this.error.set('Action evidence is unavailable for this project or session.');
    } finally {
      if (generation === this.generation) this.loading.set(false);
    }
  }

  async history(actionId: string) {
    if (this.busy()) return;
    this.clearAuditSource();
    const generation = this.generation;
    this.historyRows.set([]);
    try {
      const response = await this.api.actionHistory(this.organizationId, this.projectId, actionId);
      if (generation !== this.generation) return;
      if (response.status !== 200 || response.body['project_id'] !== this.projectId
          || !Array.isArray(response.body['history']) || !(response.body['history'] as unknown[]).every(isAction)) throw new Error();
      this.historyRows.set(response.body['history'] as ActionRow[]);
    } catch {
      if (generation === this.generation) this.message.set('Action history unavailable; refresh this project.');
    }
  }

  async inspectAuditSource(row: ActionRow) {
    if (this.busy() || this.loading() || this.error() || this.demo() || row.state !== 'accepted'
        || row.source_type !== 'opportunity' || !row.source_current
        || !this.actions().some((current) => current.action_id === row.action_id && current.revision === row.revision)) return;
    const frozen = structuredClone(row), generation = this.generation;
    const organizationId = this.organizationId, projectId = this.projectId;
    this.clearAuditSource(); this.busy.set(true); this.auditSourceLoading.set(true);
    const current = () => this.currentAuditAction(frozen, organizationId, projectId);
    try {
      if (!await current()) throw new Error();
      if (generation !== this.generation) return;
      const result = await this.api.firstProjectAuditActionSource(organizationId, projectId, frozen.action_id, frozen.revision);
      if (generation !== this.generation) return;
      const source = validateAuditActionSource(result.body, organizationId, projectId, frozen);
      if (result.status !== 200 || !source || !await current()) throw new Error();
      if (generation !== this.generation) return;
      this.auditSource.set(source);
    } catch {
      if (generation === this.generation) {
        this.auditSource.set(null); this.auditSourceError.set('Current accepted audit source unavailable or changed. Refresh the project; unsupported or missing evidence is not first value.');
      }
    } finally { if (generation === this.generation) { this.busy.set(false); this.auditSourceLoading.set(false); } }
  }

  async create(event: Event) {
    event.preventDefault();
    if (this.busy() || !this.canApprove()) return;
    const form = event.target as HTMLFormElement;
    if (!form.reportValidity()) return;
    const values = new FormData(form);
    const source = this.sources().find((item) => item.id === values.get('source'));
    if (!source) return;
    const [sourceType, sourceId] = source.id.split(':');
    const requestKey = this.keyFor(`create:${source.id}`);
    await this.submit({ request_key: requestKey, source_type: sourceType, source_id: Number(sourceId),
      state: 'proposed', action_kind: source.actionKind || String(values.get('action_kind') || ''),
      destination_page: sourceType === 'intent' ? '' : String(values.get('destination_page') || ''),
      assignee_id: Number(values.get('assignee_id')),
      acceptance_criteria: String(values.get('acceptance_criteria') || ''), reason: String(values.get('reason') || ''),
      implemented_at: null, change_summary: '', verification_note: '', outcome_note: '' }, undefined);
  }

  async transition(event: Event, row: ActionRow) {
    event.preventDefault();
    if (this.busy() || !this.allowedTransitions(row).length) return;
    const form = event.target as HTMLFormElement;
    if (!form.reportValidity()) return;
    const values = new FormData(form);
    const state = String(values.get('state') || '');
    if (!this.allowedTransitions(row).includes(state)) return;
    const value = String(values.get('implemented_at') || '');
    if (state === 'implemented' && (!value || !Number.isFinite(new Date(value).getTime()))) {
      this.message.set('Enter the actual implementation date and time before claiming implementation.');
      return;
    }
    const timestamp = state === 'implemented' ? new Date(value).toISOString()
      : ['verified', 'outcome_reviewed'].includes(state) ? row.implemented_at : null;
    const requestKey = this.keyFor(`${row.action_id}:${row.revision}:${state}`);
    await this.submit({ request_key: requestKey, source_type: row.source_type, source_id: row.source_id,
      action_kind: row.action_kind, destination_page: row.source_type === 'opportunity' &&
        (['merge', 'redirect', 'create'].includes(row.action_kind)) ? (row.affected_urls.at(-1) ?? '') : '',
      assignee_id: row.assignee_id, acceptance_criteria: row.acceptance_criteria,
      reason: String(values.get('reason') || ''), state, expected_revision: row.revision,
      implemented_at: timestamp,
      change_summary: ['implemented', 'verified', 'outcome_reviewed'].includes(state)
        ? String(values.get('change_summary') || '') : '',
      verification_note: ['verified', 'outcome_reviewed'].includes(state)
        ? String(values.get('verification_note') || '') : '',
      outcome_note: state === 'outcome_reviewed' ? String(values.get('outcome_note') || '') : '',
    }, row.action_id);
  }

  private keyFor(operation: string) {
    if (this.pendingOperation !== operation) {
      this.requestKey = crypto.randomUUID();
      this.pendingOperation = operation;
    }
    return this.requestKey;
  }

  private async submit(data: Record<string, unknown>, actionId?: string) {
    const generation = this.generation;
    this.clearAuditSource();
    this.busy.set(true); this.message.set('');
    try {
      const response = await this.api.saveAction(this.organizationId, this.projectId, data, actionId);
      if (generation !== this.generation) return;
      const row = response.body['action'];
      if (![200, 201].includes(response.status) || response.body['project_id'] !== this.projectId
          || !isAction(row) || row.state !== data['state']
          || row.revision !== (actionId ? Number(data['expected_revision']) + 1 : 1)) throw new Error();
      this.requestKey = ''; this.pendingOperation = ''; this.busy.set(false);
      await this.load();
      if (generation + 1 === this.generation) this.message.set('Human action revision recorded; no website change was made.');
    } catch {
      if (generation === this.generation) this.message.set('Action outcome unknown or stale. Refresh before retrying with the same request.');
    } finally {
      if (generation === this.generation) this.busy.set(false);
    }
  }
}

function validateAuditActionSource(body: Record<string, unknown>, organizationId: number, projectId: number,
                                  selected: ActionRow): Record<string, unknown> | null {
  const source = body['source'];
  if (body['organization_id'] !== organizationId || body['project_id'] !== projectId
      || body['action_id'] !== selected.action_id || body['revision'] !== selected.revision
      || !source || typeof source !== 'object' || Array.isArray(source)
      || Object.keys(body).length !== 5) return null;
  const value = source as Record<string, unknown>;
  const ids = ['job_id', 'diagnostics_id', 'finding_id', 'opportunity_id', 'action_review_id'];
  const digests = ['audit_source_digest', 'decision_digest', 'page_sha256'];
  const dates = ['audit_completed_at', 'diagnostics_observed_at', 'finding_detected_at', 'opportunity_reviewed_at', 'action_accepted_at'];
  const keys = ['method', 'organization_id', 'project_id', ...ids, ...digests, ...dates,
    'detector', 'action_kind', 'coverage', 'first_value', 'first_ever_occurrence'];
  if (Object.keys(value).length !== keys.length || keys.some((key) => !Object.hasOwn(value, key))
      || value['method'] !== 'bounded-audit-human-action-source-v1'
      || value['organization_id'] !== organizationId || value['project_id'] !== projectId
      || value['opportunity_id'] !== selected.source_id || value['action_kind'] !== selected.action_kind
      || value['action_accepted_at'] !== selected.recorded_at
      || !ids.every((key) => Number.isSafeInteger(value[key]) && Number(value[key]) > 0)
      || !digests.every((key) => typeof value[key] === 'string' && /^[0-9a-f]{64}$/.test(value[key]))
      || !dates.every((key) => typeof value[key] === 'string'
        && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(value[key])
        && Number.isFinite(Date.parse(value[key])) && Date.parse(value[key]) <= Date.now())
      || dates.some((key, index) => index > 0 && Date.parse(String(value[dates[index - 1]])) > Date.parse(String(value[key])))
      || typeof value['detector'] !== 'string' || !/^raw_(?:title|meta_description)_(?:missing|short|excessive)_candidate$/.test(value['detector'])
      || value['coverage'] !== 'bounded_discovered_http_sample_not_complete_site'
      || value['first_value'] !== 'not_established' || value['first_ever_occurrence'] !== 'not_established') return null;
  return value;
}

async function validateUsefulnessChallenge(body: Record<string, unknown>, organizationId: number, projectId: number,
                                            row: ActionRow, actorId: number): Promise<UsefulnessChallenge | null> {
  const proof = structuredClone(body['challenge']);
  if (!exactKeys(body, ['organization_id', 'project_id', 'action_id', 'revision', 'challenge'])
    || body['organization_id'] !== organizationId || body['project_id'] !== projectId
    || body['action_id'] !== row.action_id || body['revision'] !== row.revision || !object(proof)
    || !exactKeys(proof, ['method', 'source', 'source_digest', 'receipt_proof', 'expires_at', 'acknowledgment_recorded'])
    || proof['method'] !== ACK_METHOD || proof['acknowledgment_recorded'] !== false || !sha(proof['source_digest'])
    || typeof proof['receipt_proof'] !== 'string' || !/^[A-Za-z0-9_:-]{1,4096}$/.test(proof['receipt_proof'])
    || !aware(proof['expires_at']) || Date.parse(proof['expires_at']) <= Date.now()
    || Date.parse(proof['expires_at']) > Date.now() + 300000 || !object(proof['source'])) return null;
  const source = proof['source'];
  if (!exactKeys(source, ['method', 'acknowledging_actor_id', 'evidence', 'interpretation'])
    || source['method'] !== ACK_METHOD || source['acknowledging_actor_id'] !== actorId || actorId <= 0
    || source['interpretation'] !== ACK_INTERPRETATION
    || !validateAuditActionSource({ organization_id: organizationId, project_id: projectId,
      action_id: row.action_id, revision: row.revision, source: source['evidence'] }, organizationId, projectId, row)
    || Date.parse(proof['expires_at']) - 300000 < Date.parse(row.recorded_at || '')
    || await declarationDigest(source) !== proof['source_digest']) return null;
  return structuredClone(proof) as UsefulnessChallenge;
}

function validateUsefulnessHistory(body: Record<string, unknown>, organizationId: number, projectId: number): UsefulnessHistory | null {
  const keys = ['method', 'organization_id', 'project_id', 'interpretation', 'scope', 'state'];
  if (body['method'] !== ACK_METHOD || body['organization_id'] !== organizationId || body['project_id'] !== projectId
    || body['interpretation'] !== ACK_INTERPRETATION || body['scope'] !== ACK_SCOPE || typeof body['state'] !== 'string') return null;
  if (['unknown', 'not_observed_for_project'].includes(body['state'])) return exactKeys(body, keys) ? body : null;
  if (body['state'] !== 'recorded' || !exactKeys(body, [...keys, 'acknowledged_at', 'tracking_started_at',
    'source_digest', 'declaration_digest', 'action_id', 'revision', 'source'])
    || !sha(body['source_digest']) || !sha(body['declaration_digest']) || !dated(body['acknowledged_at'])
    || !dated(body['tracking_started_at']) || Date.parse(body['tracking_started_at']) > Date.parse(body['acknowledged_at'])
    || typeof body['action_id'] !== 'string' || !/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(body['action_id'])
    || !Number.isSafeInteger(body['revision']) || Number(body['revision']) < 2 || Number(body['revision']) >= 65535
    || !object(body['source'])) return null;
  const source = body['source'];
  const selected = { action_id: body['action_id'], revision: body['revision'], source_id: source['opportunity_id'],
    action_kind: source['action_kind'], recorded_at: source['action_accepted_at'] } as ActionRow;
  if (typeof source['action_kind'] !== 'string' || !['keep', 'refresh', 'merge', 'redirect', 'retire', 'create'].includes(source['action_kind'])
    || !validateAuditActionSource({ organization_id: organizationId, project_id: projectId,
      action_id: selected.action_id, revision: selected.revision, source }, organizationId, projectId, selected)
    || Date.parse(String(source['audit_completed_at'])) < Date.parse(body['tracking_started_at'])
    || Date.parse(String(source['action_accepted_at'])) > Date.parse(body['acknowledged_at'])) return null;
  return body as UsefulnessHistory;
}

const actionTurkish: Readonly<Record<string, string>> = {
  "Human SEO action history": "İnsan SEO eylem geçmişi",
  "Assigned SEO actions and manual change history": "Atanmış SEO eylemleri ve elle tutulan değişiklik geçmişi",
  "Unreviewed Turkish action interface draft in local development. Stored source/status values, mixed source labels and other screens remain English; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe eylem arayüzü taslağı. Kayıtlı kaynak/durum değerleri, karma kaynak etiketleri ve diğer ekranlar İngilizce kalır; iki dilli onay bekleniyor.",
  "Return to workspace": "Çalışma alanına dön",
  "Review intent and page mapping": "Niyet ve sayfa eşlemesini incele",
  "Proposals require an authorized human approval. Implementation, technical verification and observed outcome are separate records. None of these controls changes a website, publishes content or proves uplift.": "Öneriler yetkili insan onayı gerektirir. Uygulama, teknik doğrulama ve gözlenen sonuç ayrı kayıtlardır. Bu kontrollerin hiçbiri web sitesini değiştirmez, içerik yayımlamaz veya iyileşmeyi kanıtlamaz.",
  "Loading current project actions.": "Güncel proje eylemleri yükleniyor.",
  "Refresh action history": "Eylem geçmişini yenile",
  "Inspect retained usefulness history for this project": "Bu projenin saklanmış yararlılık geçmişini incele",
  "Only the first 50 recent action/source records are shown.": "Yalnızca ilk 50 yakın tarihli eylem/kaynak kaydı gösterilir.",
  "No manual action is recorded for this project.": "Bu proje için elle yapılan eylem kaydı yok.",
  "Project human action state": "Proje insan eylemi durumu",
  "revision": "revizyon",
  "Source:": "Kaynak:",
  "review": "inceleme",
  "current": "güncel",
  "historical/revoked; correction requires a current proposal": "geçmiş/iptal edilmiş; düzeltme güncel öneri gerektirir",
  "Affected project URLs:": "Etkilenen proje URL'leri:",
  "Assigned user": "Atanmış kullanıcı",
  "Acceptance criteria:": "Kabul ölçütleri:",
  "Review rationale:": "İnceleme gerekçesi:",
  "Implementation claimed": "Uygulama beyanı",
  "This alone is not verification.": "Bu tek başına doğrulama değildir.",
  "Inspect source-compatible before/after observations": "Kaynağı uyumlu önce/sonra gözlemlerini incele",
  "Technical verification reviewed": "Teknik doğrulama incelemesi",
  "Outcome reviewed": "Sonuç incelemesi",
  "Before/after is not causal proof.": "Önce/sonra karşılaştırması nedensellik kanıtı değildir.",
  "Inspect immutable action revisions": "Değişmez eylem revizyonlarını incele",
  "Inspect this accepted action's bounded audit source": "Bu kabul edilmiş eylemin sınırlı denetim kaynağını incele",
  "Review this exact action for a usefulness acknowledgment": "Yararlılık beyanı için tam olarak bu eylemi incele",
  "Next human state": "Sonraki insan eylemi durumu",
  "Reason for transition": "Geçiş gerekçesi",
  "Actual implementation time (when marking implemented)": "Gerçek uygulama zamanı (uygulandı olarak işaretlerken)",
  "Manual change summary (implementation and later states)": "Elle yapılan değişiklik özeti (uygulama ve sonraki durumlar)",
  "Technical verification note (when verifying)": "Teknik doğrulama notu (doğrularken)",
  "Outcome note (when reviewing outcome; unknown is allowed)": "Sonuç notu (sonucu incelerken; bilinmeyen kabul edilir)",
  "Record manual transition": "Elle yapılan geçişi kaydet",
  "Inspecting current private audit and human decision evidence.": "Güncel özel denetim ve insan kararı kanıtları inceleniyor.",
  "Current bounded audit and human acceptance evidence": "Güncel sınırlı denetim ve insan kabulü kanıtları",
  "Inspection does not establish customer usefulness, accepted first value, first-ever occurrence, current permission to reuse the source, implementation or causal improvement. No job, conversion, new approval or website change is recorded.": "İnceleme; müşteri yararlılığı, kabul edilmiş ilk değer, ilk kez gerçekleşme, kaynağı yeniden kullanmak için güncel izin, uygulama veya nedensel iyileşme oluşturmaz. İş, dönüşüm, yeni onay veya web sitesi değişikliği kaydedilmez.",
  "Marked audit": "İşaretlenmiş denetim",
  "completed": "tamamlanma tarihi",
  "Raw diagnostics": "Ham tanı verileri",
  "observed": "gözlem tarihi",
  "finding": "bulgu",
  "detected": "tespit tarihi",
  "Human opportunity": "İnsan fırsatı",
  "reviewed": "inceleme tarihi",
  "action review": "eylem incelemesi",
  "accepted": "kabul tarihi",
  "for": "eylem türü",
  "Bounded discovered HTTP sample—not the complete site or a clean-site result. Only supported retained UTF-8 raw title/description candidates can supply this evidence.": "Keşfedilmiş sınırlı HTTP örneği; sitenin tamamı veya sorunsuz site sonucu değildir. Yalnızca desteklenen, saklanmış UTF-8 ham başlık/açıklama adayları bu kanıtı sağlayabilir.",
  "Audit source SHA-256:": "Denetim kaynağı SHA-256:",
  "exact decision SHA-256:": "tam karar SHA-256:",
  "private page SHA-256:": "özel sayfa SHA-256:",
  "Optional subjective usefulness acknowledgment": "İsteğe bağlı öznel yararlılık beyanı",
  "Organization": "Kuruluş",
  "project": "proje",
  "This declares that the exact bounded raw-metadata audit and human-accepted next action helped identify useful manual work. It does not verify business facts, a clean whole site, implementation or SEO improvement, and does not approve a website change. Inspection records nothing. Older untracked organizations remain unknown.": "Bu beyan, tam olarak bu sınırlı ham meta veri denetiminin ve insan tarafından kabul edilmiş sonraki eylemin yararlı elle yapılacak işi belirlemeye yardımcı olduğunu bildirir. İşletme bilgilerini, sitenin tamamının sorunsuzluğunu, uygulamayı veya SEO iyileşmesini doğrulamaz ve web sitesi değişikliğini onaylamaz. İnceleme hiçbir şey kaydetmez. İzlenmemiş eski kuruluşlar bilinmez durumda kalır.",
  "Frozen action": "Sabitlenmiş eylem",
  "Original audit completed": "Özgün denetim tamamlanma tarihi",
  "original action accepted": "özgün eylem kabul tarihi",
  "Declaration SHA-256": "Beyan SHA-256",
  "Proof expires": "Kanıtın sona erme tarihi",
  "This exact audit and accepted next action helped me identify useful manual work, and I want to record that subjective acknowledgment.": "Tam olarak bu denetim ve kabul edilmiş sonraki eylem yararlı elle yapılacak işi belirlememe yardımcı oldu; bu öznel beyanı kaydetmek istiyorum.",
  "Record this usefulness acknowledgment": "Bu yararlılık beyanını kaydet",
  "The acknowledgment outcome is unknown. No new proof or acknowledgment is issued or replayed automatically.": "Beyanın sonucu bilinmiyor. Yeni kanıt veya beyan otomatik olarak oluşturulmaz veya yeniden gönderilmez.",
  "Look up this exact uncertain usefulness acknowledgment": "Tam olarak bu belirsiz yararlılık beyanını sorgula",
  "I still want to record the same frozen subjective declaration.": "Aynı sabitlenmiş öznel beyanı kaydetmek istiyorum.",
  "Retry the same unexpired usefulness proof after lookup": "Sorgulamadan sonra süresi dolmamış aynı yararlılık kanıtını yeniden dene",
  "First server usefulness acknowledgment": "İlk sunucu yararlılık beyanı",
  "tracking began": "izleme başlangıcı",
  "Original audit": "Özgün denetim",
  "original human acceptance": "özgün insan kabulü",
  "Historical declaration, not current permission to reuse this source or a lifetime conversion count.": "Geçmiş beyan; bu kaynağı yeniden kullanmak için güncel izin veya ömür boyu dönüşüm sayısı değildir.",
  "Original action": "Özgün eylem",
  "Retained source SHA-256": "Saklanmış kaynak SHA-256",
  "No retained acknowledgment observed for this selected project; another project's history is not disclosed. Unknown tracking is not zero usefulness.": "Bu seçili proje için saklanmış beyan gözlenmedi; başka projenin geçmişi açıklanmaz. Bilinmeyen izleme sıfır yararlılık değildir.",
  "Immutable action history": "Değişmez eylem geçmişi",
  "no implementation recorded": "uygulama kaydı yok",
  "Propose a manual action": "Elle yapılacak eylem öner",
  "Review a current intent-page proposal or page-anchored opportunity and an eligible assignee first.": "Önce güncel niyet/sayfa önerisini veya sayfaya bağlı fırsatı ve uygun atanacak kişiyi inceleyin.",
  "Reviewed source (queries alone are not page evidence)": "İncelenmiş kaynak (tek başına sorgular sayfa kanıtı değildir)",
  "Action for a page opportunity (intent mapping uses its recorded action)": "Sayfa fırsatı için eylem (niyet eşlemesi kayıtlı eylemini kullanır)",
  "Exact project destination for page-opportunity create/merge/redirect only": "Yalnızca sayfa fırsatı oluşturma/birleştirme/yönlendirme için tam proje hedefi",
  "Eligible assignee": "Uygun atanacak kişi",
  "Acceptance criteria (what needs doing, not a success claim)": "Kabul ölçütleri (yapılması gerekenler; başarı iddiası değildir)",
  "Reason for the proposed action": "Önerilen eylemin gerekçesi",
  "Save unapproved proposal": "Onaylanmamış öneriyi kaydet",
  "Original usefulness proof expired. Inspect retained history; no acknowledgment is retried.": "Özgün yararlılık kanıtının süresi doldu. Saklanmış geçmişi inceleyin; beyan yeniden denenmez.",
  "Retained usefulness history unavailable. Refresh this project.": "Saklanmış yararlılık geçmişi kullanılamıyor. Bu projeyi yenileyin.",
  "Current usefulness source, actor or proof unavailable or changed. No acknowledgment recorded by inspection.": "Güncel yararlılık kaynağı, aktör veya kanıt kullanılamıyor veya değişmiş. İncelemeyle beyan kaydedilmedi.",
  "Exact original usefulness acknowledgment confirmed in retained history. No website change or SEO improvement is confirmed.": "Tam özgün yararlılık beyanı saklanmış geçmişte doğrulandı. Web sitesi değişikliği veya SEO iyileşmesi doğrulanmadı.",
  "Usefulness acknowledgment outcome unknown. Look up exact retained history before any deliberate retry.": "Yararlılık beyanının sonucu bilinmiyor. Bilinçli yeniden denemeden önce tam saklanmış geçmişi sorgulayın.",
  "Current action, source authority or original proof changed. Refresh before acknowledging.": "Güncel eylem, kaynak yetkisi veya özgün kanıt değişmiş. Beyanda bulunmadan önce yenileyin.",
  "No exact retained acknowledgment found. Only the same original unexpired proof may be retried deliberately; the server revalidates its source.": "Tam saklanmış beyan bulunamadı. Yalnızca süresi dolmamış aynı özgün kanıt bilinçli olarak yeniden denenebilir; sunucu kaynağını yeniden doğrular.",
  "No exact acknowledgment confirmed; original proof or current source is unavailable. No retry allowed.": "Tam beyan doğrulanmadı; özgün kanıt veya güncel kaynak kullanılamıyor. Yeniden denemeye izin verilmez.",
  "Exact usefulness lookup unavailable or does not match this declaration. No acknowledgment replayed.": "Tam yararlılık sorgusu kullanılamıyor veya bu beyanla eşleşmiyor. Beyan yeniden gönderilmedi.",
  "Select an authorized project.": "Yetkili bir proje seçin.",
  "Action evidence is unavailable for this project or session.": "Bu proje veya oturum için eylem kanıtları kullanılamıyor.",
  "Action history unavailable; refresh this project.": "Eylem geçmişi kullanılamıyor; bu projeyi yenileyin.",
  "Current accepted audit source unavailable or changed. Refresh the project; unsupported or missing evidence is not first value.": "Güncel kabul edilmiş denetim kaynağı kullanılamıyor veya değişmiş. Projeyi yenileyin; desteklenmeyen veya eksik kanıt ilk değer değildir.",
  "Enter the actual implementation date and time before claiming implementation.": "Uygulama beyanından önce gerçek uygulama tarihini ve saatini girin.",
  "Human action revision recorded; no website change was made.": "İnsan eylemi revizyonu kaydedildi; web sitesinde değişiklik yapılmadı.",
  "Action outcome unknown or stale. Refresh before retrying with the same request.": "Eylem sonucu bilinmiyor veya eski. Aynı istekle yeniden denemeden önce yenileyin."
};
