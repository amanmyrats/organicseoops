# Account And Application Experience Foundation

Status: P01-07 implementation reference. This specifies authenticated account/app
flows before screen implementation. The canonical product rules remain in
[PROJECT_PLAN.md](PROJECT_PLAN.md), especially Sections6–10 and23.

## 1. Scope And Boundaries

This document covers account entry, organization/project onboarding, the app
shell and dashboard, billing discovery/recovery, and organization settings. It
does not select prices, trial duration, card policy, currencies, retention,
markets, final copy, or an authenticated UI library. Those choices keep their
existing task/decision gates.

Final public marketing wireframes remain P3A-09 after P3A-01 positioning and page
mapping. Public pages keep semantic custom HTML/CSS and must not import app themes
or controls. These wireframes do not claim implemented authentication, billing,
tenancy, integrations, analysis, or accessibility.

## 2. Information Architecture

The signed-in shell always identifies the active organization and project before
showing project data. Switching either clears stale private screen state and
reloads authorization. Controls hidden for a role remain server-enforced.

Project navigation:

- Overview
- Opportunities
- Audits
- Content
- Competitors and AI visibility
- Integrations
- Project settings

Organization navigation:

- Projects
- Team and access
- Usage
- Billing
- Organization settings and audit history

Personal navigation:

- Profile
- Security and sessions
- Notifications
- Sign out

Only shipped, permitted capabilities appear. A disabled control is used for a
temporary state such as quota or an operation in progress, not to advertise an
unavailable future feature. Permission-denied destinations are omitted from
navigation; direct navigation receives a clear denied page with a safe return.

## 3. Application Shell Wireframes

### Desktop

```text
+ Skip to content ----------------------------------------------------+
| OrganicSEOOps | Organization [Acme v] | Project [example.com v] | Me |
+----------------+----------------------------------------------------+
| Overview       | Breadcrumbs                     Freshness / status |
| Opportunities  | H1 + plain-language summary                       |
| Audits         | Context alerts: trial/quota/partial/stale          |
| Content        |                                                    |
| Competitors    | Primary content                                   |
| Integrations   | Evidence and action panels                         |
| Settings       |                                                    |
|                | Persistent job status region when relevant         |
+----------------+----------------------------------------------------+
```

The context selectors are labels plus controls, not ambiguous logos. Breadcrumbs
never replace the page heading. Trial/quota notices link to Usage or Billing only
when the user can act; other roles get the owner/contact explanation.

### Narrow Screen And 400% Reflow

```text
+ Skip to content -------------------------+
| OrganicSEOOps                    [Menu]   |
| Organization: Acme [Change]              |
| Project: example.com [Change]             |
+------------------------------------------+
| Breadcrumbs                               |
| H1                                        |
| Status / next action                      |
|                                           |
| Single-column content                     |
| Evidence before secondary actions         |
+------------------------------------------+
```

At320 CSS pixels there is no two-dimensional page scroll. Navigation opens as a
keyboard-operable modal or disclosure, closes with Escape, returns focus to its
trigger and does not trap focus after close. Tables may scroll inside a labeled
region when preserving columns is essential; provide a row-detail or text summary
instead of shrinking content below readability.

## 4. Account Flows

### Registration And Verification

```text
Register -> generic accepted result -> verification pending
         -> verified link -> organization setup
         -> expired/invalid/used/already verified -> specific safe recovery
Invitation link -> matching verified login/registration -> review invite -> accept
```

Registration uses email, password, password confirmation, terms/privacy links and
one clear submit action. Password requirements are visible before failure. Paste,
autofill and password managers work. Submission keeps non-secret valid fields and
moves focus to an error summary on validation failure.

Pending verification shows the destination address in a privacy-conscious form,
resend cooldown/status, change-address/login options and no claim that an
organization/trial exists. Resend, replay, invitation and verification outcomes
use one status heading and a clear next action. Unknown-account recovery remains
non-enumerating.

### Login, Recovery And Sessions

```text
Login -> intended allowlisted app route or onboarding
      -> unverified -> verification recovery
      -> suspended/expired session -> explanation and permitted recovery
Forgot password -> same generic result for known/unknown email
Reset link -> new password -> sessions revoked -> normal login
```

Login exposes email, password, show-password, forgot-password and registration.
Authentication errors use an `aria-live` status and never reveal account existence.
Security settings group password change, pending verified-email change, active
sessions, revoke one, logout all and account closure. Staff additionally receive
TOTP enrollment and one-time recovery-code controls; customer MFA remains a separate
rollout choice. Destructive actions require
reauthentication/confirmation and explain organization ownership prerequisites.

## 5. Organization And Project Onboarding

Onboarding is resumable and reports progress by named steps, not color alone.

```text
1 Verified account
2 Organization name/review -> one eligible trial result, if applicable
3 Website + country/language + primary goal
4 Review canonical origin and bounded first-audit estimate
5 Connect source / import file / skip with explanation / synthetic demo
6 First job progress -> partial/failure/retry/cancel or real first findings
7 Select a supported action -> Overview
```

Organization setup explains whether the user is creating an organization or
joining an invitation. It never promises a trial until authoritative eligibility
is known and never asks for invented payment terms.

Project setup asks only website, target country/language and primary business goal
initially. Show normalized origin before creation. Advanced competitors, brand
voice, schedules, provider routing and budgets move to optional settings. Each
source option states requested access and expected value. Skip/unavailable paths
still permit a bounded crawl/import where supported.

Before expensive work, show scope, page/credit/cost estimate, allowance remaining,
expected stages and cancel behavior. Progress names the current stage, elapsed
state and last update. Partial results remain inspectable. The results screen shows
up to three evidence-backed priorities when available; it never fabricates rows to
fill a layout.

## 6. Overview And Evidence Flow

Overview answers in this order:

1. Is data connected, current and complete enough to interpret?
2. What changed in search/conversion/site health for the selected period?
3. Which evidence-backed actions matter now?
4. What was recently changed, verified, or left inconclusive?

Every metric includes source, date range, freshness, unit and comparison basis.
Charts have an adjacent text summary and accessible data table. SEO, conversion
and AI-visibility observations remain distinct. An opportunity detail leads from
plain-language finding to evidence, limitations, history, proposed action, cost,
approval and later verification/outcome. The default action never hides evidence.

## 7. Billing, Usage And Organization Settings

Billing is organization-scoped and owner-only. The shell may show plan/trial/usage
status to other permitted roles, but payment methods, checkout, invoices, spend
caps, organization export and closure follow the role matrix.

Billing layout order:

1. Current authoritative service state and exact effective/end date
2. Usage/allowances and blocked capabilities
3. Available recovery, hosted checkout or billing-portal action
4. Invoices/receipts and billing details when the provider supports them
5. Cancellation/reactivation consequences and retained access/export

Pending payment, active, scheduled cancellation, failed payment/grace, expired,
read-only and suspended are distinct. A checkout-return page says processing until
server reconciliation confirms service. Unknown prices, proration, refunds,
retention and card policy are not filled with placeholder promises.

Organization settings groups company details, projects, team/invitations/project
access, integrations, usage/spend caps, audit history, export, ownership transfer
and closure. Billing and destructive actions are visually separated. Member rows
show role and project access in text; menus expose only authorized actions. The
last-owner rule and pending transfer acceptance are explained before confirmation.

## 8. Visual And Component Conventions

The app starts from the scaffold's restrained system-font baseline; this is not a
final brand redesign.

| Concern | Convention |
| --- | --- |
| Type | Native system sans; body16px/1.5 minimum; compact labels14px; headings use a clear1.2–1.33 ratio and never rely on size alone for hierarchy |
| Measure | Prose45–70 characters; operational tables use available width |
| Spacing |4px base scale:4,8,12,16,24,32,48,64; controls use at least8px internal and16px related-group spacing |
| Color | Semantic tokens, not raw component colors: canvas `#f7f9fa`, text `#182b36`, action/link `#075d70`, focus `#974700`; success/warning/danger/info need text/icon labels and verified contrast |
| Focus |3px visible outline with4px offset or equivalent; never removed or hidden under sticky UI |
| Shape | Modest consistent radius; borders/shadows indicate grouping, not decoration hierarchy |
| Motion | Functional and brief; honor reduced motion; no status depends on animation |

Forms use visible persistent labels, optional/required text, field help before the
input, inline error after it and an error summary linked to invalid controls.
Submit stays named for the outcome, disables only during the active submission and
announces success/failure. Do not clear recoverable values or permit accidental
duplicate submissions.

Buttons use one primary action per region, ordinary secondary actions and text
links for navigation. Destructive actions state the object and consequence. Icon
buttons require accessible names and at least24 by24 CSS-pixel targets, with larger
touch spacing where practical.

Tables use a caption, semantic headers/scope, stable sort announcement, explicit
empty state and row action names containing the row subject. Pagination/filter
state is visible and resettable. Dialogs have a heading, initial logical focus,
contained tab order, Escape behavior unless a destructive operation is committed,
and focus return.

Public and app tokens live in separate style entry points. A later authenticated
component library must reproduce these contracts and remain lazy-loaded; library
defaults are not accessibility acceptance.

## 9. Required State Contract

| State | Required presentation and action |
| --- | --- |
| Loading | Preserve heading/context; use named status/skeleton; announce delayed completion without stealing focus |
| Empty/new | Explain why empty, prerequisite and one permitted next action; do not show zero as success |
| Demo | Persistent “synthetic demo” label; isolated from live data, usage and export |
| Disconnected | Name source and last successful data time; reconnect or alternative import by permission |
| Stale | Show observed-through date and interpretation warning; refresh action if allowed |
| Partial | Show completed and failed coverage separately; preserve useful results and retry only valid stages |
| Error/failed job | Safe error/request/job ID, impact, retained input/result and allowed retry/support action |
| Denied | State missing access without leaking object existence; return to authorized scope/contact owner |
| Quota reached | Name resource, used/allowed/time window and owner recovery; preserve results/export where allowed |
| Trial/entitlement expired | Read-only retained results plus permitted billing recovery/export; no new costly work |
| Insufficient history | State required comparison/history and earliest useful date; do not render a passing score |
| No issue found | Name what was checked, scope and time; distinct from not checked/unavailable |
| Suspended/session expired | Explain allowed login/support/billing/export recovery without exposing private stale state |

State messages use `role=status` for non-urgent updates and `role=alert` only when
immediate attention is needed. Repeated polling does not repeatedly announce the
same text.

## 10. WCAG 2.2 AA Acceptance

Each implemented screen inherits these checks and adds feature-specific checks:

- One logical H1, semantic landmarks and a first-focus skip link; document title
  identifies the page and active context where safe.
- Full operation with keyboard alone. Focus order follows reading order, focus is
  visible/not obscured, route/dialog focus moves deliberately, and focus returns
  after overlays or failed submissions.
- Text contrast is at least4.5:1 (3:1 for applicable large text); UI/focus graphics
  meet3:1. Status never uses color alone.
- Reflow at320 CSS pixels and400% zoom has no page-level two-dimensional scroll;
  text spacing overrides do not clip or overlap content.
- Controls have programmatic names, roles, values and instructions. Error summary,
  field association, status announcements and correction suggestions work with a
  screen reader. Repeated-entry data can be selected or auto-populated where safe.
- Authentication permits paste/autofill/password managers and avoids unnecessary
  memory/cognitive tests. Timeouts warn and offer extension where security permits.
- Pointer targets meet WCAG2.2 minimum sizing/spacing; drag, hover and complex
  gestures have simple alternatives.
- Tables expose captions/headers; charts expose equivalent summary/table data;
  SVG/icons/images have appropriate text alternatives or are decorative.
- Narrow and desktop checks cover loading, success, validation, denial, partial,
  quota and expiry, not only the happy path.

Minimum manual matrix: current Chrome and Firefox desktop keyboard; a320px viewport
at400% reflow; one current mobile browser; NVDA+Firefox or VoiceOver+Safari for
labels, errors, status and dialog/table navigation. Add the smallest automated
Angular accessibility check when real interactive screens exist; automation does
not replace the manual matrix.

## 11. Practical Usability Scripts

Run these with a first-time keyboard user and again at narrow width:

1. Register, understand verification status, recover from an expired link and
   reach the correct next step without creating duplicate organization/trial state.
2. Create an organization/project, skip an unavailable integration, understand the
   bounded first job and resume after partial failure.
3. From Overview, identify freshness, open one finding, inspect its evidence and
   limitations, then choose an allowed action without mistaking missing data for success.
4. Switch organization/project and confirm context, heading, data and navigation
   all change together with no stale private content.
5. As owner, find trial/plan end, usage, invoices/recovery and cancellation/export;
   as member/viewer, understand why owner-only actions are absent or denied.
6. Invite/manage a member, inspect project access, and find ownership transfer or
   closure consequences without risking the last-owner invariant.

Acceptance records screen/build, role, data state, viewport/input/assistive tool,
task outcome, blocking issue and follow-up owner. Later feature cards must reference
the applicable rows/scripts rather than claiming generic accessibility compliance.

## 12. Implementation And Evidence Handoff

P01-07 accepted the design/test contract rather than rendered screens. P02-01
through P02-05 now implement registration, verification, login, recovery,
email-change, session controls, organization/project context, team access, accepted
ownership transfer and suspension states with automated semantic, error/focus/state/
stale-response checks. P02-01–P02-04 recorded320px browser renders; P02-05 has
automated interaction/build checks but no new browser/screen-reader acceptance claim.
P06-01 now implements the resumable named-step onboarding and source alternatives
with automated state/focus/stale-response checks and a labeled static demo; no new
manual narrow-browser or assistive-technology acceptance is claimed. The evidence
dashboard remains a later owning card and must record its own results.

| Owning cards | Required contract and evidence |
| --- | --- |
| P02-01 | Registration/verification/login states; labels/autofill/error summary/status; keyboard+narrow rendered tests |
| P02-02 | Recovery/email/session/closure entry; token-safe paths, reauthentication, focus and non-enumerating errors |
| P02-03–P02-04 | App shell, selectors, context reset, permission navigation/direct denial, team tables and mobile menu focus return |
| P02-05 | Ownership proposal/acceptance/cancel and leave confirmation; suspended account/organization access, reauthentication and last-owner errors |
| P04-03 | Local diagnostic job create/status/cancel/retry, waiting/partial/error states, role denial, polling stop and stale-scope isolation (automated; no new manual narrow/browser/assistive claim) |
| P04-05 | Paused-first cost-free schedule creation, next/last run, skipped-run/capacity/access states and pause/resume controls (automated; manual narrow/assistive results not claimed) |
| P3A-05–P3A-08 | Trial/billing/usage states, owner-only actions, pending reconciliation, quota/expiry/read-only recovery |
| P06-01/P06-07 | Resumable project onboarding, source alternatives, bounded-job estimate/progress/partial/retry and first action |
| P08-06 | Overview/evidence/action flow, freshness/limitations, all applicable state rows and chart table alternatives |
| P3A-09 | Separate final public wireframes and public keyboard/reflow acceptance after positioning/page decisions |

Minimum component checks render each applicable state, assert semantic heading and
landmarks, accessible control names/error associations, stable context during
loading/switching, status announcements without repetition, and role-appropriate
actions. Manual acceptance then runs the Section10 matrix and Section11 scripts.
