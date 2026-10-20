# OrganicSEOOps Active Implementation Tasks

D429 targets all already-planned local implementation and automated acceptance. Finish the current R05/R06 automated stage first, then existing roadmap IDs in dependency order. The original contracts/evidence remain in [the dated archive](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md). Archived heading statuses are historical baseline, not current completion; record current local status in the table below and keep human/external gates separate.

## First Working Release

R01–R06 remain the basic-release stage; D429 then authorizes the local parts of existing P/TOOL contracts. R07 records external release evidence. Work in dependency order and reuse valid evidence. Track implementation, focused checks, final automated acceptance and human/external gates separately; implemented never means release-ready. An unavailable manual walkthrough remains unfinished but does not prevent unrelated roadmap coding after the basic automated stage.

| ID | Outcome | Implementation | Focused verification | Final acceptance |
| --- | --- | --- | --- | --- |
| R01 | Account, project and source setup | implemented locally | pass/reused; CSV seam and marked review closed | R06 pending |
| R02 | Bounded audit and first findings | implemented locally | existing integrated/source2 + native1 pass; unchanged evidence reused | R06 pending |
| R03 | Useful dashboard, mapping and action | implemented locally | current integrated fixture pass; native/source evidence reused | R06 pending |
| R04 | Sourced research and readable brief | implemented locally | current integrated fixture pass; native/source evidence reused | R06 pending |
| R05 | Basic SaaS safety and recovery | malformed-format repair applied | source-matched candidate API2 pass; existing safety evidence reused | automated pass; walkthrough pending |
| R06 | Final local validation | selected current candidate | automated checks pass; prior full failures/UNKNOWN retained | walkthrough pending |
| R07 | Actual public release evidence | external/manual gated | not verified | public release blocked |

D427 applies to every R card: inspect/reuse existing owning coverage before writing tests. Add/extend a case only for a concrete uncovered changed contract or risk, recording one brief reason. No automatic spec per edit, ceremonial red-first run or duplicate/speculative coverage. Trivial/behavior-preserving edits use relevant static/type/manual checks; required non-trivial/sensitive checks and R06 acceptance remain.

No new cards/suffixes or features outside the existing specification. Track actual defects, paths/results and next action within the existing card/current local table and checkpoint. No cleanup/refactor merely because code looks large. Historical `done` is not new acceptance; D429 reactivates unfinished local parent/subcard contracts after the basic automated stage, honoring dependencies and accepted supersessions.

### R01 — Account, project and source setup [implemented]

- **Local closure 2026-10-10T17:48:50.872529+00:00:** Existing account/project/source foundations reconciled; missing local CSV source-create/raw-upload API and native seam implemented over existing importer. New API3 and native3 pass, stable inherited backend5/native source-history2 pass, app types pass; one bounded marked Security review complete/no actionable finding/no required unread dependency. Initial retained-DB/client/stub fixture failures and exact commands/hashes in [today’s history](IMPLEMENTATION_HISTORY_2026-10-10.md). DEBUG-only job progress/cancel remains local; R06 final acceptance and R07 hosted/provider readiness pending.

- **Needs:** Reconcile any partial work at a safe boundary; preserve unresolved operations. Foundation/account/tenancy already have local evidence.
- **Scope:** Register/verify/login/recover, create organization/project, show current scope and permissions, configure existing supported source/model settings. Search Console CSV import is a valid initial path; sync remains available when configured. No customer/example project seeding, new provider, model framework or fresh onboarding metrics.
- **Existing ownership:** `backend/accounts/`, `backend/tenancy/`, `backend/integrations/`, `backend/providers/`; Angular account, overview, onboarding and source/provider settings. Reference P02-01–P02-05, P05-01–P05-05, P06-01–P06-06 and their relevant repair evidence only.
- **Close implementation:** A verified user can create/select a project and load correctly scoped source data; disconnected/unconfigured states are usable and truthful. Existing role, CSRF, MFA, secret-redaction and revocation contracts hold.
- **Focused checks:** Exact owning cases for any changed behavior; sensitive authorization/source/credential cases before dependent work. Reuse unchanged passes. Record unresolved source/configuration mismatches here; do not reread every historical card.
- **Security review gate:** Preserve existing P02/P05/P06 marked gates. Reuse genuine current independent coverage; if a changed core trust boundary invalidates it, use one bounded review after focused checks. Missing required coverage remains R06/R07 unfinished, never silently satisfied.

### R02 — Bounded audit and first findings [implemented]

- **Reconciled local closure:** PASS existing integrated/source2/6.830s and original native1/1.57s; no new tests. Existing `first_audit.py`/API/native journey and named P06-07/P08-01a source-flow evidence inspected. No new implementation gap found; current CSV seam changes reach its source-to-findings contract. Reuse existing integrated synthetic journey and source-revocation cases (no new test), plus original native bounded-audit case, as exact stable-flow checks. Integrated fixture also observes unchanged R03/R04/manual-change contracts; optional acquisition/detectors remain deferred.
- **Needs:** R01's implemented, focused-checked contracts; no real provider credential prerequisite for local coding.
- **Scope:** Connect the existing CSV/sync, safe bounded crawl, supported performance observations and finding jobs to a resumable first-audit screen. Show estimate, progress, cancellation, partial results and useful next actions. Missing sources/field data stay unavailable; never manufacture findings or make an actual customer/provider call for local proof.
- **Existing ownership:** `backend/jobs/` crawl/finding/first-audit handlers, integrations and Angular `first-audit.ts`, `project-onboarding.ts`, `job-dashboard.ts`. Reference P04-01–P04-05, P06-03/P06-04/P06-07, P07-01–P07-06, P08-01a.
- **Close implementation:** Synthetic or permitted CSV fixtures traverse the actual source→job→API→screen flow, with bounded scope/cost, restart/cancel and cross-project denial. Unsupported GA4/exact-origin/conversion requirements are displayed as unavailable; do not build new source surfaces to close this milestone.
- **Focused checks:** Changed end-to-end seam and exact relevant fetch, quota, isolation, retry/cancel cases. Existing diagnostic variants need no expansion.
- **Security review gate:** Preserve original crawl/SSRF/job-scope gates; any outstanding required current independent review of the core is retained for R06.

### R03 — Dashboard, mapping and action [implemented]

- **Reconciled 2026-10-10T17:53:36.969160+00:00:** Current scoped sources and named existing contract/focused-review receipts inspected; basic local implementation/focused closure, no further core blocker found. R03/R04 current integrated fixture PASS2/6.830s also verifies their owning source/action/research/brief contracts; R05 unchanged signed/quota/MFA/export/recovery evidence reused. Exact paths/limits in [today’s history](IMPLEMENTATION_HISTORY_2026-10-10.md); R06 final/full/manual and R07 actual readiness remain unverified. No archive-wide or optional completion claim.

- **Needs:** R02's implemented, focused-checked evidence; R01 role context.
- **Scope:** Display prioritized evidence with dates/coverage; map an intent/query to a page; accept/assign an action and record a manual change. Reuse current technical verification, baseline/follow-up and manual local assessment. Insufficient/unsupported data remains inconclusive; no invented uplift, new advanced cohort or detector catalogue.
- **Existing ownership:** `backend/jobs/` findings/intent/action/technical-outcome/local-assessment; Angular `project-dashboard.ts`, `intent-mapping.ts`, `action-workflow.ts`, `action-outcomes.ts`. Reference P08-01a/P08-02/P08-03/P08-04a/P08-05/P08-06.
- **Close implementation:** A user can understand one finding, inspect its evidence, choose an approved next action, log implementation and distinguish technical verification from measured outcome. Relevant empty/error/denied states and keyboard/narrow-screen operation work.
- **Focused checks:** Actual changed mapping/action/approval/read paths and tenant/role boundaries. Preserve existing human approval/revision invalidation.

### R04 — Sourced research and readable brief [implemented]

- **Reconciled 2026-10-10T17:53:36.969160+00:00:** Current scoped sources and named existing contract/focused-review receipts inspected; basic local implementation/focused closure, no further core blocker found. R03/R04 current integrated fixture PASS2/6.830s also verifies their owning source/action/research/brief contracts; R05 unchanged signed/quota/MFA/export/recovery evidence reused. Exact paths/limits in [today’s history](IMPLEMENTATION_HISTORY_2026-10-10.md); R06 final/full/manual and R07 actual readiness remain unverified. No archive-wide or optional completion claim.

- **R06 named failure 2026-10-10T17:56:32.168267+00:00:** Full frontend failed1/1153passed: existing Unicode editable-field spec includes nonexistent audience/business_goal inputs; actual values are research-derived and separately reader-tested. One-line fixture correction complete; exact invalidated case PASS1/1.53s, actual overflow and separate research-derived read assertions retained. Full1153 unchanged passes reused; production build16.184s/static13 PASS; current1154 combined unit coverage accepted within unchanged-source limits. No backend source change/full-backend interruption or suite replay.

- **Needs:** R03's selected action or honest manual opportunity/topic; existing P05 provider/job/cost contracts.
- **Scope:** Use existing research and brief jobs, citations/source dates and human review to produce a readable brief/export. A manual opportunity is sufficient. Competitor observations attach only when already available. No article editor/generator, lifecycle enhancement, social repurposing or research-catalogue expansion.
- **Existing ownership:** `backend/jobs/research.py`, `backend/jobs/content_brief.py`, related APIs/tests; Angular `project-research.ts`, `project-briefs.ts`. Reference P10-01/P10-02 and their existing reader/input repairs. Recover an actual shared/core defect within this card, not a new suffix.
- **Close implementation:** The real local job/API/UI flow produces a sourced brief from labelled synthetic provider fixtures, including no-source/partial/error/cancel states and escaped safe citations. Human review never upgrades unsupported claims into facts.
- **Focused checks:** Changed research/brief contract, citation/trust-boundary and project/revision access cases. Reuse current original journey evidence where unchanged.
- **Security review gate:** Preserve original research/brief/AI-input marked gates and current source coverage; source/model input stays untrusted.

### R05 — Basic SaaS safety and recovery [in_progress]

- **Current receipt 2026-10-11T02:16:14.483482+00:00:** Backend2594 terminal PASS/29856.923s, test DB destroyed/owner absent. Prepared R05 guard/regression applied with exact tested hashes; API2 reused; revised image/packaged918/security PASS. Basic automated stage closed; walkthrough unavailable and full acceptance pending. D429 inventory classification523 cards/693 TODO complete; P02-06 local roadmap continuation active and full parent acceptance pending. [Current checkpoint](IMPLEMENTATION_STATE.md) supersedes older staged/active-operation bullets below.

- **D428 execution instruction 2026-10-11:** Apply the existing prepared export-format guard/regression as soon as the original backend operation genuinely releases its source/DB boundary. Read its patch/receipts, verify original hashes, preserve unrelated changes and confirm applied source equals the tested candidate; reuse valid API2 evidence or run only the changed contract if source/configuration differ. Continue through R06 repairs/validation rather than stopping after patch application. Guidance-only update: no application or acceptance claim.

- **Independent staged verification complete 2026-10-10T18:17:36.874221+00:00:** Private source copy matches frozen candidate plus the prepared scalar guard/test. Existing locked candidate image, separate disposable `test_r05_export_pkznwj7v`, exact new malformed-format + existing normal private capture/current-permission methods **PASS2/5.715s tests/38.403s wall**; test DB removed. Frozen925 workspace hashes unchanged. Host exact-lock preflight lacked fido2 before any DB/test; container mount-permission failure before Django preserved, corrected public-copy readability under private parent and reused existing verified image. API exit/source hashes in private `r05-export-format-fix/isolated-api.exit.json`/`isolated-api-source.json`; [history](IMPLEMENTATION_HISTORY_2026-10-10.md). Apply same checked patch only after full owner717066 terminal; reuse unchanged passing source-bound API evidence and refresh only invalidated final package/image coverage. R05 implementation remains pending application; no full replay/repeated review.

- **R06 review selection 2026-10-10T18:07:53.113834+00:00:** ONE bounded marked Security review for exposed personal/owner export, scoped private capture/download and failed-capture cleanup/recovery. Reuse original focused authorization/CSRF/foreign/revocation/storage-failure fixtures; no source change or duplicate test during active full backend. Do not claim full P02-06 closure/destruction/legal-export review complete; disabled/public remainder stays R07.

- **Reconciled 2026-10-10T17:53:36.969160+00:00:** Current scoped sources and named existing contract/focused-review receipts inspected; basic local implementation/focused closure, no further core blocker found. R03/R04 current integrated fixture PASS2/6.830s also verifies their owning source/action/research/brief contracts; R05 unchanged signed/quota/MFA/export/recovery evidence reused. Exact paths/limits in [today’s history](IMPLEMENTATION_HISTORY_2026-10-10.md); R06 final/full/manual and R07 actual readiness remain unverified. No archive-wide or optional completion claim.

- **R06 concrete defect 2026-10-10T18:09:59.234305+00:00:** Bounded Security review found non-string snapshot `format` list/object triggers TypeError/HTTP500 before writes. One scalar type guard plus smallest existing-class API regression prepared; existing owner/foreign/CSRF/capture tests do not exercise unhashable format. Preserve frozen active backend2594 source/testDB; apply only after genuine terminal receipt, reusing the subsequent isolated API2 pass when hashes/configuration match. No second independent review required. This input fix remains unfinished, not an exhaustion condition. Prepared source/test/patch/receipt in `/tmp/organicseoops-r06-20261010-pkznwj7v/r05-export-format-fix`; staged syntax/extracted guard self-check and isolated API/normal-capture verification pass as recorded above. Production source unchanged, preserve active full owner. No original full/legal review completion claim.

- **Needs:** R01–R04's exposed flow; existing trial/billing/export/staff code.
- **Scope:** Retain safe basic organization trial/usage enforcement, write-only operator configuration, owner billing recovery and existing bounded export. Reconcile current email/security notices and disabled closure states. Missing seller/source/sender configuration must fail safely without paid calls. No fresh staff-inspection dashboards, acquisition metrics, complete large-tenant export framework or new commercial options.
- **Existing ownership:** Accounts/tenancy/providers/jobs enforcement, billing/closure/export/email and their existing Angular screens; deployment templates/runbooks. Reference P3A-05–P3A-08/P3A-10, P02-06, P03-02, P13-01–P13-04, only as applicable to the basic local flow.
- **Close implementation:** Existing trial/paid fixtures enforce quotas and expiry at API/worker boundaries; owner can inspect/recover/export within actual supported limits. Unresolved erasure/legal/retention flows remain disabled and labelled, with their actual remaining prerequisites retained at R07. No data destruction, entitlement bypass or invented counsel approval to satisfy a checklist.
- **Focused checks:** Exact changed signed billing, quota/concurrency, export authorization, account recovery, retention and destructive-data boundaries; no broad packet per repair.
- **Security review gate:** Preserve original P02-06/P3A-06/P3A-07/P3A-08/P3A-10 gates. A disabled/incomplete closure path is not approved for public enablement; required current review remains explicit at R06/R07.

### R06 — Final local validation [in_progress]

- **Current receipt 2026-10-11T02:16:14.483482+00:00:** Backend2594 terminal PASS/29856.923s, test DB destroyed/owner absent. Prepared R05 guard/regression applied with exact tested hashes; API2 reused; revised image/packaged918/security PASS. Basic automated stage closed; walkthrough unavailable and full acceptance pending. D429 inventory classification523 cards/693 TODO complete; P02-06 local roadmap continuation active and full parent acceptance pending. [Current checkpoint](IMPLEMENTATION_STATE.md) supersedes older staged/active-operation bullets below.

- **D428 execution instruction 2026-10-11:** Reconcile the recorded backend owner/result once. Do independent core work first; if none remains and the operation is active, use CONTINUE.md's same-session bounded terminal-receipt wait instead of another unchanged short handoff. After genuine completion, handle named failures, apply the checked R05 repair and refresh only invalidated evidence. Complete the core walkthrough when transport becomes available; do not retry an unchanged transport failure each minute. Mark local acceptance only when required evidence passes; tool/manual gates remain unfinished. No duplicate full suite or timer/launcher change.

- **Resume 2026-10-10T19:03:51+00:00:** Original full driver717066 and repository cwd are present; terminal receipt absent. Candidate backend925/frontend135 and R05 original2/prepared2/executed2 hashes match; isolated API2 exit0 reused. CUA inventory transport fails before a tab/journey. Preserve active source/testDB; no duplicate suite or independent due local task. Required full result and checked repair/package refresh remain actionable; ordinary handoff, launcher active. [History](IMPLEMENTATION_HISTORY_2026-10-10.md).

- **Selected candidate 2026-10-10T17:53:36.969160+00:00:** Primary `/root` owns automatic final validation after R01–R05 local coding/focused closure. Public source/config manifest `/tmp/organicseoops-r06-20261010-pkznwj7v/candidate.json`; full backend/frontend selected once with actual prior eight-hour runtime considered. Independent final scopes and known failed/UNKNOWN history in checkpoint/history. No public readiness; do not relaunch due to session changes.

- **Current final evidence:** Recorded basic candidate backend2594 terminal PASS29856.923s + applied source-matched R05 API regression; revised candidate package/image security PASS. Frontend full1153pass/1fixturefail + repaired exact1pass forms1154 combined coverage (original full exit1 retained); build/static13/audit0/deploy43/workflow5/system/drift/runtime evidence reused within source limits. R06 keyboard/narrow walkthrough remains unavailable and all mixed acceptance checkboxes open. P02-06 current roadmap row/barrier changes have selected focused/source review evidence and defer final current-source package/full automated acceptance to full local coding closure. Full coherent/legal export/closure/security and R07 human/external readiness remain unfinished.

- **Automatic entry:** Once R01–R05 implementation and focused evidence close, select this phase without waiting for deferred expansion or another permission prompt. Do not run it just because a session changed. Record candidate source/configuration, exact scopes, reason and owner once.
- **Acceptance:** Complete required full frontend/backend coverage, relevant production build/static/dependency/image/deployment-template checks, current migrations/runtime smoke, required source reviews and a practical core-journey keyboard/narrow-screen walkthrough. Reuse valid unchanged evidence. No source hashes, successful checks or manual usability results are assumed from history.
- **Established routes:** `npm --prefix frontend run check`; backend full `./backend-dev.sh manage test accounts config tenancy jobs providers integrations --noinput --durations 20 --timing --verbosity 2`. Select other applicable existing routes from `deploy/checks/README.md`, the workflow and backend/frontend guides only for this candidate; maps are not repeated packets. Preserve wrapper DB serialization and any existing operation ownership.
- **Failure handling:** Collect genuine terminal receipts. Repair named failures in owning R cards; rerun affected checks and only invalidated final coverage. Optional existing code cannot hide a known security/data-loss failure; repair or safely gate it, without adding enhancements. Keep previous failed/UNKNOWN runs as historical evidence.
- **Security review gate:** Close required independent-review gaps for the exposed core and materially changed shared boundaries using original gate scopes/current source proof. Reviewers never run tests. Reuse completed valid review coverage; do not invoke the full roster automatically.
- **Done:** Current required local checks and walkthrough pass with recorded limitations. Mark R01–R05 final acceptance and R06 complete together; local readiness does not complete R07 or archive-wide parent cards.

### R07 — Public release evidence [blocked]

- **Needs:** R06 plus authorized real provider/sandbox/hosted/manual/legal/content evidence. Current status is **unverified**; not a continuation coding queue.
- **Preserved gates:** GATE-INTERNAL's actual authorized source journey; GATE-PUBLIC and relevant capability gates; P3A-12/P3A-13/P13-05 and plan §§34.1–34.2. Real email/provider/billing, allowances/costs, approved offer/content/locales/support/accessibility, complete required export/closure/legal/retention, actual CDN/storage/restore/production migration and public-to-paid-to-exit evidence remain mandatory before applicable public exposure.
- **Truthful launch scope:** Advertise only validated shipped capabilities. D429's local implementation authorization does not make unverified AI visibility/competitor/security/connectors launch promises. Missing external evidence stays named; do not request secrets in chat, run paid calls, acquire domains or deploy under local authorization.

## Local Completion

**D437 — current user instruction (2026-10-19): implementation only.** Work only on genuinely unfinished local implementation. Preserve completed archived work and skip cards whose remaining work is testing, evidence reconciliation or release validation. Do not run tests, test maintenance, builds, type/lint checks, scans, runtime validation or final acceptance until the user explicitly requests testing. Do not add tests during this phase. Record new code as implemented but untested; keep automated/manual/external acceptance pending. Existing authorization, tenant isolation, validation, human approval and external-operation limits still apply. D437 overrides earlier automatic-check requirements and test-based continuation triggers.

The verification table is a reconciliation register, not overall coding completion. Preserve archived implementation credit (351 done cards;472 checked TODO requirements) and skip completed source contracts without rerunning them.

D429 inventory classification is complete: **523 existing cards and693 preserved TODO requirements**, each mapped below. The archives are unchanged. This is ownership/scope classification, not fresh acceptance of historical `done` labels. Original Needs/Build/Check, phase context, supersessions and Security review markers remain authoritative at each linked contract. No whole-codebase audit or new card is selected.

`pending` means current implementation/evidence reconciliation is still required; it does not mean the existing code is absent. `blocked` keeps a documented source/condition-dependent local requirement in the denominator. `excluded` is reserved for the exact human/external-only rows listed below. Implementation and automated acceptance have separate columns; a required independent review is part of automated/local acceptance. A mixed row's human gate stays pending after local verification. TODO source line numbers are stable identifiers within the byte-preserved archive, not new task IDs; each TODO counts once even when it maps to several cards. Multiple owners require their applicable local portions together; an original explicit alternative (such as CMS or supported social publication for TODO888) does not require both unselected platforms.

The first classification has **521 local card contracts and689 local TODO requirements**. The two excluded cards and four excluded TODO rows remain in the raw523/693 full-project inventory. Demand/capability-blocked local contracts are retained. Selected P02-06a/P02-06b source/evidence reconciliation verifies2 card implementation/automated contracts; all other rows remain pending/blocked until selected reconciliation; this conservative starting register does not replace existing R01–R06 evidence or claim that implementation disappeared. Update the phase totals as selected rows are verified. Final current-source automated acceptance is selected again only after full local coding/focused/review closure.

| Basic stage | Local implementation | Automated acceptance | Separate remainder | Evidence |
| --- | --- | --- | --- | --- |
| R05 | verified applied repair | verified source-matched API2/package/security | Legal/coherent export/closure remain P02-06/R07 | [Checkpoint](IMPLEMENTATION_STATE.md) |
| R06 | automated stage closed | backend2594 plus API regression, combined frontend1154/build/static and remaining gates pass | Core walkthrough unavailable; public/manual gates unfinished | [Checkpoint](IMPLEMENTATION_STATE.md) |

### Inventory Gate Owners

These names describe original conditions/actions, not additional tasks. Every listed remainder is **pending/unverified**. They never excuse fixture-testable local implementation. The parent agent owns local code and checks; the named person/operator owns the separate action or evidence.

| Remainder/condition | Owner and exact reason |
| --- | --- |
| Git authorization | User: no Git init/commit requested; P01-01 local pins/ignores remain included |
| Manual accessibility | Human/browser/AT reviewer: practical keyboard, screen-reader and narrow-screen evidence; R06 transport unavailable, P08-06b manual-only |
| Live public journey | Founder/release operator: actual deployed/provider end-to-end execution under P3A-13/R07 |
| Live product-site evidence | Product-site operator/content owner: actual domain webmaster verification, sitemap submission, deployed SEO/funnel/preview checks, baseline/owner/cadence and postlaunch observations (TODO867–869); P13-05a offline monitoring remains local |
| Domain/content research | Founder/public-content reviewer: domain/brand availability, licensed or first-party query evidence and approval; draft route/page-map implementation remains local |
| Bilingual review | Founder and bilingual human reviewer: actual English/Turkish public/app/critical-email/support copy approval; configurable localization/drafts remain local |
| Approved proof/publication | Content owner/reviewer: approved measured case studies/publication rights and hosted rollback; clearly labeled sample preparation remains local |
| Commercial/legal readiness | Founder, counsel/accounting and Paddle: actual account/domain/bank/global buyer/legal/retention acceptance; D095–D099 policy and local signed billing remain implemented separately |
| Legal identity/export | Founder/counsel: actual personal identity/repeat-trial retention policy and legal exclusions remain unapproved. Agent: reviewed-policy-gated account cleanup/coherent current-content source evidence retained; complete own-account scalability and final acceptance remain LOCAL pending, not excluded; disabled public activation is not completion |
| Live deletion | Release/storage operator: authorized hosted deadline/version/IAM/backup-expiry/destructive proof; resumable local cleanup and tests remain included/default disabled |
| Production historical cutover | Release operator: actual production trial/billing history cutover, separately authorized migration |
| Provider sandbox | Founder/billing operator: real approved Paddle sandbox lifecycle; signed fixture processing/checkout mapping remain local |
| Sender/domain/copy | Founder/email operator/bilingual reviewer: approved sender, DNS authentication, real/sandbox delivery and actual copy; configurable retry/bounce/notice code remains local |
| Consent design | Founder/privacy reviewer: analytics/consent tool and lawful retention/attribution decisions; safe configured event/dedupe behavior remains local |
| Live attribution | Release/analytics operator: actual public/app/email/checkout handoffs and consent behavior; local linkage fixtures remain included |
| Provider terms/cost/access | Founder/provider operator: actual capabilities/scopes/licensing/retention/current cost/quota and permitted representative jobs; keys alone do not prove readiness |
| Real source grants | Customer/provider operator: real OAuth/property/data/model grants and permitted representative operations; scoped configurable flows and fixtures remain local |
| Exact-origin capability | Agent/provider capability evidence owner: independently verifiable project-origin reporting grain; GA4 hostname/path does not prove scheme/port. P06-05/P08-04b/P11A-04r remain unresolved local source contracts, not credential exclusions |
| Real engine capability | Provider/integration owner: actual supported engine operations and permitted import/sync evidence; provider-specific local contracts remain included |
| Bing demand/capability | Product/integration owner: P06-08 explicitly requires demand and supported access; local work activates on that evidence, credentials alone are not the condition |
| Additional engine demand | Product/integration owner: unspecified additional engine requires concrete demand/capability; specified Yandex contract stays included under P06-09 |
| Official Trends access | Product/integration owner: official supported Trends access/availability; existing permitted news/video paths and local code remain included |
| SERP provider selection | Agent local adapter choice D438: DataForSEO Google source implemented, untested. Product/provider owner retains actual account/terms/licensing/retention/current price/quota and account spending-control evidence; no live readiness claim |
| Commercial data justification | Product/provider owner: commercial justification, supported terms/access for keyword/backlink/optional traffic source; conditional local work remains in denominator |
| Human outreach/action | Authorized customer: actual human review/manual outreach/site recovery; approval/audit/uncertainty enforcement remains local |
| Supported fact/citation surface | Provider/customer evidence owner: permitted citation-capable surface and approved facts; unsupported sources remain unresolved, never manufactured |
| AI live/legal readiness | Founder/provider/privacy operator: actual advertised surface, rights/privacy/hosted/manual evidence; local supported-surface guards remain included |
| Verified ownership/scope | Authorized customer: ownership/passive scope and consent; fixture-tested scope/fetch/approval enforcement remains local; no active scanning authorized |
| Live deployment | Release/cloud operator: actual Actions/ECR/EC2/OIDC/DNS/TLS/S3/CDN/production migration/health evidence; checked templates, routing, migration ordering and rollback remain local |
| Hosted CI | Repository/release operator: actual hosted workflow run; verified local equivalent may satisfy P01-05's local contract |
| Live storage | Storage operator: real private S3/IAM/Block Public Access; private storage fixtures remain local |
| Live restore/alarms | Release/cloud operator: authorized hosted backups/restore/CloudWatch alarms; local restore/atomic rollback and templates remain included |
| Live support operation | Support operator: actual permission-scoped production investigations; safe local records/corrections/diagnostics remain included |
| Requested CMS | Product/customer owner: explicitly requested CMS system plus official capabilities; local approval, idempotency, revocation and records required once selected |
| Supported social platform | Product/customer/provider owner: requested official scheduling/analytics platform and permissions; actual grant/publication separate from local handlers |
| Actual usage evidence | Product/platform operator: sufficient real project/provider/crawl/storage usage before plan/retention refinement; no invented usage or pricing policy |
| Demonstrated scale constraint | Platform operator: measured reliability/load/Compose limitation before RDS/ElastiCache/ECS/scaling; no speculative infrastructure; local rehearsal required when condition activates |
| Real repository grant | Repository owner: explicit actual repo/branch/least-privilege grant and PR operation; authorization/isolation/patch/hostile-input checks are unconditional planned local preparation |
| Human patch review | Repository reviewer: actual review/merge approval; local prevention of merge/deploy and revision-bound approval remains required |
| Recurring tooling need | Project maintainer: repeated workflow beyond current roles before extra implementation skills |
| Concrete adapter need | Project maintainer: demonstrated new host need before additional thin adapter |
| Final hosted validation | Release operator: actual hosted backend groups/transfer/per-job fit; TOOL-01/R06/P11-01dc local acceptance remains mandatory |
| Publication/outcome evidence | Customer/publication owner: actual approved CMS or supported social publication and sufficient comparable outcome data; P08-04 local comparison remains pending independently of social platform selection |
| Installed launcher acceptance | Local operator/agent: reconcile existing permitted host acceptance; D429 does not authorize timer/launcher/model/permission modification |

### Phase Verification Totals

Each cell is verified implementation / verified automated acceptance / local denominator. These are current verified ratios, not historical code-existence estimates. No baseline `done` row automatically enters the numerator. Mixed gates remain pending, and blocked local work stays counted.

These totals count complete local contracts, not individual repairs or passing tests. Evidence recorded within an `in_progress` card can increase while its completed count remains unchanged. Historical recorded completion is 351/523 cards (67.1%) and 472/693 TODO checkboxes (68.1%); those preserved baselines and the current verified totals describe different measures, not a loss of existing implementation.

| Phase | Card contracts I/A/total | TODO requirements I/A/total | Human/external-only cards/TODO |
| --- | --- | --- | --- |
| 0 | 0/0/0 | 0/0/9 | 0/0 |
| 1 | 7/7/7 | 19/19/20 | 0/1 |
| 2 | 7/7/8 | 21/21/26 | 0/0 |
| 3 | 37/37/38 | 42/42/45 | 0/0 |
| 3A | 1/1/43 | 3/3/51 | 1/0 |
| 4 | 7/7/7 | 13/13/17 | 0/0 |
| 5 | 10/10/10 | 11/11/14 | 0/0 |
| 6 | 3/3/17 | 3/3/24 | 0/0 |
| 7 | 6/6/7 | 13/13/18 | 0/0 |
| 8 | 25/25/73 | 24/24/71 | 1/0 |
| 9 | 0/0/12 | 0/0/20 | 0/0 |
| 10 | 0/0/50 | 0/0/54 | 0/0 |
| 11 | 0/0/128 | 0/0/130 | 0/0 |
| 11A | 0/0/13 | 0/0/15 | 0/0 |
| 12 | 0/0/93 | 0/0/98 | 0/0 |
| 13 | 0/0/6 | 0/0/18 | 0/3 |
| 14 | 0/0/2 | 0/0/6 | 0/0 |
| 15 | 0/0/2 | 0/0/5 | 0/0 |
| 16 | 0/0/2 | 0/0/6 | 0/0 |
| Tooling | 0/0/3 | 0/0/42 | 0/0 |
| **Overall** | **103/103/521 (19.77%/19.77%)** | **149/149/689 (21.63%/21.63%)** | **2/4** |

### Existing Card Contracts

Every card links its exact original contract. The TODO column references source lines in the next table; an empty mapping does not exclude the card. `Baseline` is historical only. `Acceptance` includes relevant focused/final automated evidence and required independent review; checks are selected under D375/D423/D425/D427, never automatically replayed from archived command packets.

| Existing card/contract | Baseline | Local implementation | Automated acceptance | Mapped TODO lines | Separate gate/condition |
| --- | --- | --- | --- | --- | --- |
| [P01-01](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p01-01--establish-authorized-workspace-and-version-pins-done) | done | verified | verified | 48, 50, 51 | Git authorization; [current pin/lock and source-bound evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p01-01-current-pin-and-workspace-reconciliation) |
| [P01-02](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p01-02--scaffold-angular-with-static-publiccsr-boundaries-done) | done | verified | verified | 53, 54, 55 | Public/manual/final-package gates unchanged; [source-bound static/CSR evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p01-02-public-static-and-private-csr-reconciliation) |
| [P01-03](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p01-03--scaffold-django-and-the-initial-user-migration-done) | done | verified | verified | 56, 57 | Public/final-package gates unchanged; [current initial-user3 + fresh-schema evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p01-03-current-backend-and-initial-user-reconciliation) |
| [P01-04](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p01-04--separate-local-services-and-environment-configuration-done) | done | verified | verified | 52, 58, 59, 60, 61, 62, 63, 64, 67, 253, 254, 255 | Live deployment/final current-source package/CI gates; [ambient isolation2 + scoped review/evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p01-04-selected-environment-isolation-repair-and-reconciliation) |
| [P01-05](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p01-05--baseline-verification-and-ci-done) | done | verified | verified | 65, 66 | Hosted CI/final current-source acceptance separate; [current workflow3/actionlint/source evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p01-05-current-check-only-ci-and-verification-reconciliation) |
| [P01-06](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p01-06--configuration-logging-and-artifact-access-foundations-done) | done | verified | verified | — | Live storage; [current artifact4/logging source-bound evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p01-06-current-logging-and-private-artifact-reconciliation) |
| [P01-07](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p01-07--customer-flow-wireframes-and-accessible-ui-conventions-done) | done | verified | verified | 69 | Manual accessibility/consumer screens separate; [current design/AA specification evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p01-07-current-design-and-accessibility-specification-reconciliation) |
| [P02-01](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p02-01--registration-verification-and-cookie-authentication-done) | done | verified | verified | 73, 74, 75, 76, 77 | Mail/manual/final gates unchanged; auth audit/race current4 reviewed; [source evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p02-02-sensitive-authentication-audit-and-concurrent-verification-repair) |
| [P02-02](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p02-02--recovery-verified-email-changes-and-session-management-done) | done | verified | verified | 78, 80, 81, 98 | Remaining TODO98 owners/manual/provider/final gates pending; [auth audit/race/source evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p02-02-sensitive-authentication-audit-and-concurrent-verification-repair) |
| [P02-03](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p02-03--organizationproject-model-and-centralized-access-enforcement-done) | done | verified | verified | 82, 83, 86, 87, 88, 89, 94 | Hosted/manual/final gates unchanged; [current tenancy4/source evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p02-03-current-organization-project-and-private-scope-reconciliation) |
| [P02-04](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p02-04--role-matrix-invitations-and-revocation-done) | done | verified | verified | 83, 84, 85, 90, 95, 96, 107, 109 | Hosted/manual/final gates unchanged; [current role2/source evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p02-04-current-role-invitation-and-revocation-reconciliation) |
| [P02-05](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p02-05--ownership-transfer-and-suspension-invariants-done) | done | verified | verified | 91, 92, 95, 97, 102, 107, 110 | Hosted/manual/final gates unchanged; [current ownership3/source evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p02-05-current-ownership-last-owner-and-suspension-reconciliation) |
| [P02-06](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p02-06--export-user-closure-and-organization-closure-blocked) | blocked | in_progress | pending | 93, 236, 408, 98 | READY-copy lifetime local source/focused/review/dev0086/runtime complete; actual legal/export/copy terms + final current-source acceptance pending; [parent source41/current ownership1 + host1](IMPLEMENTATION_HISTORY_2026-10-11.md#p02-06-parent-local-source-and-remaining-gates-reconciliation) |
| [P02-06a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p02-06a--exact-scalar-owner-closure-outcome-states-in_progress) | in_progress | verified | verified | 235 | Parent legal/coherent export gates pending; [source-bound acceptance](IMPLEMENTATION_HISTORY_2026-10-11.md#p02-06ab-deferred-native-acceptance) |
| [P02-06b](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p02-06b--exact-scalar-private-snapshot-states-and-current-history-clearing-in_progress) | in_progress | verified | verified | 235 | Parent legal/coherent export gates pending; [source-bound acceptance](IMPLEMENTATION_HISTORY_2026-10-11.md#p02-06ab-deferred-native-acceptance) |
| [P03-01](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-01--safe-django-admin-and-customer-admin-separation-done) | done | verified | verified | 102, 103, 105, 106, 107 | Feature-owned Admin/manual/hosted gates pending; [current foundation admin1/source evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-01-current-foundation-admin-and-customer-separation-reconciliation) |
| [P03-02](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-02--staff-mfa-recovery-and-production-access-done) | done | verified | verified | 104, 108 | Manual/actual lost-factor authorization/hosted gates pending; [current MFA2/source evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-02-current-staff-mfa-and-controlled-recovery-reconciliation) |
| [P03-03](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03--operational-correction-and-support-workflows-pending) | pending | pending | pending | 111 | Live support operation |
| [P03-03a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03a--minimized-exact-scoped-staff-job-investigation-source-done) | done | verified | verified | 112 | [Current source11/rendered privacy-final-loss2](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03a-and-b-current-scoped-staff-job-investigation-reconciliation); original marked gate retained/full support/manual/final parent pending |
| [P03-03b](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03b--reasoned-exact-scoped-staff-job-admin-consumer-done) | done | verified | verified | 113 | [Current source11/rendered privacy-final-loss2](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03a-and-b-current-scoped-staff-job-investigation-reconciliation); original marked gate retained/full support/manual/final parent pending |
| [P03-03c](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03c--separate-exact-scoped-internal-unit-reservation-source-done) | done | verified | verified | 114 | [Current scoped usage/AI source6/rendered semantics2](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03c-through-f-current-staff-internal-unit-and-original-ai-reconciliation); original marked gates retained/full operational/manual/final parent pending |
| [P03-03d](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03d--reasoned-scoped-internal-unit-usage-admin-done) | done | verified | verified | 115 | [Current scoped usage/AI source6/rendered semantics2](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03c-through-f-current-staff-internal-unit-and-original-ai-reconciliation); original marked gates retained/full operational/manual/final parent pending |
| [P03-03e](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03e--separate-original-ai-usagecost-observation-source-done) | done | verified | verified | 117 | [Current scoped usage/AI source6/rendered semantics2](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03c-through-f-current-staff-internal-unit-and-original-ai-reconciliation); original marked gates retained/full operational/manual/final parent pending |
| [P03-03f](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03f--reasoned-scoped-original-ai-observation-admin-done) | done | verified | verified | 118 | [Current scoped usage/AI source6/rendered semantics2](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03c-through-f-current-staff-internal-unit-and-original-ai-reconciliation); original marked gates retained/full operational/manual/final parent pending |
| [P03-03g](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03g--exact-organization-notice-transport-source-done) | done | verified | verified | 120 | [Current notice source/native9/private Admin-API1](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03g-and-h-current-organization-notice-transport-reconciliation); original marked gate retained/full operational-mail/manual/final pending |
| [P03-03h](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03h--complete-scoped-organization-notice-investigation-consumers-done) | done | verified | verified | 121 | [Current notice source/native9/private Admin-API1](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03g-and-h-current-organization-notice-transport-reconciliation); original marked gate retained/full operational-mail/manual/final pending |
| [P03-03i](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03i--exact-current-account-mail-record-source-done) | done | verified | verified | 123 | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03i-and-j-current-exact-account-mail-reconciliation) |
| [P03-03j](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03j--complete-exact-account-mail-investigation-consumers-done) | done | verified | verified | 124 | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03i-and-j-current-exact-account-mail-reconciliation) |
| [P03-03k](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03k--existing-suppression-clearance-final-assurance-recovery-done) | done | verified | verified | 126 | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03k-through-m-current-suppression-and-feedback-reconciliation) |
| [P03-03l](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03l--exact-retained-suppression-and-first-feedback-source-done) | done | verified | verified | 128 | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03k-through-m-current-suppression-and-feedback-reconciliation) |
| [P03-03m](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03m--complete-exact-suppression-feedback-investigation-consumers-done) | done | verified | verified | 129 | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03k-through-m-current-suppression-and-feedback-reconciliation) |
| [P03-03n](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03n--existing-trial-correction-request-and-final-state-assurance-done) | done | verified | verified | 131 | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03n-through-q-current-trial-correction-billing-retry-and-receipt-reconciliation) |
| [P03-03o](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03o--existing-signed-billing-receipt-retry-final-assurance-done) | done | verified | verified | 133 | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03n-through-q-current-trial-correction-billing-retry-and-receipt-reconciliation) |
| [P03-03p](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03p--exact-retained-signed-billing-receipt-source-done) | done | verified | verified | 135 | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03n-through-q-current-trial-correction-billing-retry-and-receipt-reconciliation) |
| [P03-03q](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03q--complete-exact-billing-receipt-investigation-consumers-done) | done | verified | verified | 136 | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03n-through-q-current-trial-correction-billing-retry-and-receipt-reconciliation) |
| [P03-03r](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03r--exact-admin-consumer-for-existing-trial-corrections-done) | done | verified | verified | 138 | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03r-through-t-current-exact-trial-admin-reconciliation) |
| [P03-03s](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03s--exact-retained-organization-trial-source-done) | done | verified | verified | 140 | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03r-through-t-current-exact-trial-admin-reconciliation) |
| [P03-03t](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03t--exact-trial-admin-investigation-consumer-done) | done | verified | verified | 141 | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03r-through-t-current-exact-trial-admin-reconciliation) |
| [P03-03u](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03u--exact-retained-linked-subscription-source-done) | done | verified | verified | 143 | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03u-through-z-current-subscription-archive-and-cancellation-reconciliation) |
| [P03-03v](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03v--exact-linked-subscription-admin-consumer-done) | done | verified | verified | 144 | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03u-through-z-current-subscription-archive-and-cancellation-reconciliation) |
| [P03-03w](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03w--exact-retained-archived-subscription-source-done) | done | verified | verified | 146 | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03u-through-z-current-subscription-archive-and-cancellation-reconciliation) |
| [P03-03x](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03x--exact-archived-subscription-admin-consumer-done) | done | verified | verified | 147 | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03u-through-z-current-subscription-archive-and-cancellation-reconciliation) |
| [P03-03y](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03y--exact-retained-closure-cancellation-source-done) | done | verified | verified | 149 | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03u-through-z-current-subscription-archive-and-cancellation-reconciliation) |
| [P03-03z](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03z--exact-closure-cancellation-admin-consumer-done) | done | verified | verified | 150 | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03u-through-z-current-subscription-archive-and-cancellation-reconciliation) |
| [P03-03aa](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03aa--exact-retained-checkout-attempt-source-done) | done | verified | verified | 152 | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03aa-through-ai-current-checkout-retry-link-and-first-active-reconciliation) |
| [P03-03ab](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03ab--exact-checkout-attempt-admin-consumer-done) | done | verified | verified | 153 | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03aa-through-ai-current-checkout-retry-link-and-first-active-reconciliation) |
| [P03-03ac](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03ac--exact-admin-consumer-for-existing-signed-receipt-retry-done) | done | verified | verified | 155 | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03aa-through-ai-current-checkout-retry-link-and-first-active-reconciliation) |
| [P03-03ad](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03ad--existing-checkout-link-capture-final-integrity-recovery-done) | done | verified | verified | 157 | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03aa-through-ai-current-checkout-retry-link-and-first-active-reconciliation) |
| [P03-03ae](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03ae--exact-retained-checkout-link-acknowledgment-source-done) | done | verified | verified | 159 | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03aa-through-ai-current-checkout-retry-link-and-first-active-reconciliation) |
| [P03-03af](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03af--exact-retained-checkout-link-admin-consumer-done) | done | verified | verified | 160 | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03aa-through-ai-current-checkout-retry-link-and-first-active-reconciliation) |
| [P03-03ag](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03ag--existing-first-active-historical-reader-final-integrity-done) | done | verified | verified | 162 | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03aa-through-ai-current-checkout-retry-link-and-first-active-reconciliation) |
| [P03-03ah](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03ah--exact-retained-first-active-staff-source-done) | done | verified | verified | 164 | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03aa-through-ai-current-checkout-retry-link-and-first-active-reconciliation) |
| [P03-03ai](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03ai--exact-retained-first-active-admin-consumer-done) | done | verified | verified | 165 | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03aa-through-ai-current-checkout-retry-link-and-first-active-reconciliation) |
| [P3A-01](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-01--select-audience-product-domain-and-public-page-map-blocked) | blocked | pending | pending | 169, 170 | Domain/content research |
| [P3A-02](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-02--marketlanguage-coverage-and-locale-contract-blocked) | blocked | in_progress | pending | 171, 172, 173 | Saved private preference172 verified; partial EN/TR local drafts with strict English production/failure fallback and unchanged native source/command/approval boundaries.617 distinct scoped cases/types/bounded source reviews across application and mapped public drafts through TERMS, corrected HELP/CONTACT discovery and registration policy links. [Latest title receipt](IMPLEMENTATION_HISTORY_2026-10-12.md#p3a-02-original-authority-document-titles); [earlier scopes](IMPLEMENTATION_HISTORY_2026-10-11.md). Wider application/bilingual/support/final current-source acceptance unfinished; TODO171/173 remain open. |
| [P3A-03](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-03--proof-material-and-public-content-operations-done) | done | verified | verified | 174, 175 | Approved proof/publication  [Current local evidence](IMPLEMENTATION_HISTORY_2026-10-15.md#p3a-03-current-local-verification) |
| [P3A-04](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-04--decide-commercial-offer-provider-and-retention-policies-blocked) | blocked | pending | pending | 177, 226 | Commercial/legal readiness |
| [P3A-05](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-05--exactly-once-trial-and-entitlement-lifecycle-pending) | in_progress | in_progress | pending | 229, 232, 237, 246 | Production historical cutover |
| [P3A-06](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-06--hosted-checkout-portal-and-provider-state-mapping-blocked) | blocked | in_progress | in_progress | 236, 238, 239, 240, 241 | Provider sandbox |
| [P3A-06a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-06a--persist-inert-organization-subscription-identity-and-block-post-checkout-trial-extension-done) | done | pending | pending | — | Owning parent/phase gates unchanged |
| [P3A-06b](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-06b--fail-closed-on-linked-subscription-across-trial-entry-and-costly-work-done) | done | pending | pending | — | Owning parent/phase gates unchanged |
| [P3A-06c](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-06c--exact-scalar-owner-checkout-operational-states-in_progress) | in_progress | pending | pending | — | Owning parent/phase gates unchanged |
| [P3A-07](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-07--signed-billing-events-and-reconciliation-done) | done | in_progress | in_progress | 236, 238, 241, 242, 243, 246, 98 | Provider sandbox |
| [P3A-08a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-08a--enforce-positive-unit-trial-work-done) | done | in_progress | in_progress | — | Owning parent/phase gates unchanged |
| [P3A-08b](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-08b--enforce-trial-project-and-member-limits-done) | done | in_progress | in_progress | — | Owning parent/phase gates unchanged |
| [P3A-08](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-08--complete-commercial-api-scheduler-and-worker-enforcement-done) | done | in_progress | in_progress | 236, 239, 244, 261, 265 | Owning parent/phase gates unchanged |
| [P3A-09](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-09--build-public-pages-and-static-seo-contract-blocked) | blocked | in_progress | pending | 68, 173, 178, 179, 180, 181, 182 | Mapped drafts through TERMS; CONTACT focused/source/runtime contracts retained. Approved runtime/metadata/postbuild review-record/clean-build/CDN/CSR contracts focused/source checked;624 selected cases, build298.06kB. Whole/final/bilingual/legal/manual/public unfinished. [Latest receipt](IMPLEMENTATION_HISTORY_2026-10-12.md#p3a-09-approved-runtime-metadata-and-clean-build-publication). Real approvals/hosted product-site evidence gated. |
| [P3A-10](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-10--production-transactional-email-and-lifecycle-communications-blocked) | blocked | in_progress | in_progress | 73, 79, 245 | Sender/domain/copy |
| [P3A-11a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11a--capture-first-primary-email-verification-time-done) | done | pending | pending | 183 | Owning parent/phase gates unchanged |
| [P3A-11b](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11b--capture-prospective-self-service-registration-origin-done) | done | pending | pending | — | Owning parent/phase gates unchanged |
| [P3A-11](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11--acquisition-funnel-and-consent-aware-attribution-blocked) | blocked | in_progress | in_progress | 195, 196 | Consent design; Live attribution |
| [P3A-11c](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11c--retained-first-human-action-acceptance-aggregate-done) | done | pending | pending | 183 | Owning parent/phase gates unchanged |
| [P3A-11d](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11d--prospective-confirmed-browser-receipt-of-a-checkout-link-done) | done | pending | pending | 184 | Owning parent/phase gates unchanged |
| [P3A-11e](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11e--prospective-first-active-paid-entitlement-source-done) | done | pending | pending | 185 | Owning parent/phase gates unchanged |
| [P3A-11f](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11f--prospective-bounded-first-audit-request-provenance-done) | done | pending | pending | — | Owning parent/phase gates unchanged |
| [P3A-11g](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11g--prospective-first-bounded-audit-completion-source-done) | done | pending | pending | 186 | Owning parent/phase gates unchanged |
| [P3A-11h](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11h--current-bounded-audit-human-action-evidence-discovery-done) | done | pending | pending | 187 | Owning parent/phase gates unchanged |
| [P3A-11i](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11i--deliberate-private-current-audit-action-source-inspection-done) | done | pending | pending | 188 | Owning parent/phase gates unchanged |
| [P3A-11j](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11j--explicit-prospective-bounded-audit-usefulness-acknowledgment-done) | done | pending | pending | 189 | Owning parent/phase gates unchanged |
| [P3A-11k](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11k--retained-first-usefulness-server-timing-inspection-done) | done | pending | pending | 195 | Owning parent/phase gates unchanged |
| [P3A-11l](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11l--first-party-optional-consent-and-public-candidate-boundary-done) | done | pending | pending | 197 | Owning parent/phase gates unchanged |
| [P3A-11m](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11m--checked-minimized-public-analytics-publication-policy-done) | done | pending | pending | 198 | Owning parent/phase gates unchanged |
| [P3A-11n](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11n--minimized-pinned-policy-public-observation-source-done) | done | pending | pending | 199 | Owning parent/phase gates unchanged |
| [P3A-11o](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11o--prospective-unlinked-public-consent-epoch-observations-done) | done | pending | pending | 200 | Owning parent/phase gates unchanged |
| [P3A-11p](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11p--retained-organization-age-at-first-paid-server-observation-timing-done) | done | pending | pending | 217 | Owning parent/phase gates unchanged |
| [P3A-11q](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11q--audited-original-trial-activation-source-discovery-done) | done | pending | pending | 221 | Owning parent/phase gates unchanged |
| [P3A-11r](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11r--original-audited-trial-to-first-paid-server-timing-done) | done | pending | pending | 223 | Owning parent/phase gates unchanged |
| [P3A-11s](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11s--fixed-original-trial-paid-observation-window-source-done) | done | pending | pending | 227 | Owning parent/phase gates unchanged |
| [P3A-11t](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11t--private-original-trial-paid-window-inspector-done) | done | pending | pending | 230 | Owning parent/phase gates unchanged |
| [P3A-11u](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11u--complete-retained-monthly-trial-paid-window-source-done) | done | pending | pending | 233 | Owning parent/phase gates unchanged |
| [P3A-11v](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11v--private-retained-monthly-trial-paid-window-inspection-in_progress) | in_progress | pending | pending | 234, 235 | Owning parent/phase gates unchanged |
| [P3A-11w](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11w--exact-operational-milestone-grain-and-unavailable-public-source-in_progress) | in_progress | pending | pending | — | Owning parent/phase gates unchanged |
| [P3A-11x](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11x--exact-scalar-checkout-link-source-metadata-in_progress) | in_progress | pending | pending | — | Owning parent/phase gates unchanged |
| [P3A-11y](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11y--exact-scalar-owner-paid-history-and-trial-activation-source-in_progress) | in_progress | pending | pending | — | Owning parent/phase gates unchanged |
| [P3A-11z](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11z--scalar-first-audit-launch-and-retained-operational-history-in_progress) | in_progress | pending | pending | 235 | Owning parent/phase gates unchanged |
| [P3A-12](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-12--advertised-provider-readiness-and-budget-evidence-blocked) | blocked | pending | pending | 176, 220, 226, 238, 275, 276, 297, 298, 331, 332, 333 | Provider terms/cost/access |
| [P3A-13](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-13--public-saas-end-to-end-release-gate-pending) | pending | excluded | excluded | 238, 246, 247 | Live public journey |
| [P04-01](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p04-01--durable-job-schema-and-explicit-handler-contract-done) | done | verified | verified | 251, 252, 262 | Feature-owned dispatch/API/scheduling gates pending; [current durable job/diagnostic1 + scheduler1](IMPLEMENTATION_HISTORY_2026-10-11.md#p04-01-current-durable-job-and-handler-reconciliation) |
| [P04-02](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p04-02--transaction-safe-dispatch-and-recoverable-execution-done) | done | verified | verified | 253, 258, 259, 263, 98 | Whole-roadmap/provider/manual gates pending; [scoped atomic audit5 + independent review/dev/runtime](IMPLEMENTATION_HISTORY_2026-10-11.md#p04-02-scoped-atomic-job-admission-and-cancellation-audits) |
| [P04-03](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p04-03--job-apis-and-accessible-progress-ui-done) | done | verified | verified | 256, 257, 259, 262 | P04-03 current API/native/full source-bound evidence; [receipt](IMPLEMENTATION_HISTORY_2026-10-11.md#p04-03-current-diagnostic-api-progress-and-native-repairs-reconciliation)/manual/provider/final gates separate |
| [P04-03a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p04-03a--exact-diagnostic-job-status-and-requested-detail-identity-in_progress) | in_progress | verified | verified | 267 | P04-03 scalar/exact detail guards + R06 full source-bound evidence; [receipt](IMPLEMENTATION_HISTORY_2026-10-11.md#p04-03-current-diagnostic-api-progress-and-native-repairs-reconciliation)/manual/provider/final gates separate |
| [P04-03b](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p04-03b--diagnostic-route-ids-and-exact-organizationproject-metadata-in_progress) | in_progress | verified | verified | 269 | P04-03 exact context/route/stale-chain guards + R06 full source-bound evidence; [receipt](IMPLEMENTATION_HISTORY_2026-10-11.md#p04-03-current-diagnostic-api-progress-and-native-repairs-reconciliation)/manual/provider/final gates separate |
| [P04-04](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p04-04--atomic-usage-and-concurrency-controls-done) | done | verified | verified | 260, 264 | P04-04 unchanged atomic usage/R06 + current admission audit5 evidence; [receipt](IMPLEMENTATION_HISTORY_2026-10-11.md#p04-04-current-atomic-internal-usage-reconciliation)/manual/provider/final gates separate |
| [P04-05](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p04-05--schedules-stage-reauthorization-and-operational-recovery-done) | done | verified | verified | 251, 255, 258, 261, 264 | [Nested due-run1/current source-bound recovery](IMPLEMENTATION_HISTORY_2026-10-11.md#p04-05-current-schedule-stage-authorization-and-recovery-reconciliation); actual provider/commercial/manual/final gates pending |
| [P05-01](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p05-01--provider-credentials-model-catalog-and-capabilities-done) | done | verified | verified | 273, 274, 277 | [Current source-bound foundation and completed prior marked gate](IMPLEMENTATION_HISTORY_2026-10-11.md#p05-01-current-provider-credential-and-capability-foundation-reconciliation); real access/terms/cost/manual/final separate |
| [P05-02](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p05-02--native-openai-and-compatible-endpoint-adapters-done) | done | verified | verified | 275, 276 | [Current model-selected/no-replay2 + unchanged adapter/R06](IMPLEMENTATION_HISTORY_2026-10-11.md#p05-02-current-adapter-and-model-selected-consumer-reconciliation); actual provider/manual/final gates separate |
| [P05-04a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p05-04a--exact-native-ai-job-and-provider-request-scalar-states-in_progress) | in_progress | verified | verified | 285 | [Current source-bound routing/cost/native/full/review evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p05-04-current-ai-usage-cost-and-scalar-observability-reconciliation); actual provider/manual/final and conditional background/batch separate |
| [P05-05](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p05-05--protected-platform-and-organization-credential-entry-ui-done) | done | verified | verified | 274, 282 | [Current credential/source-bound full native scalar evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p05-05-current-write-only-credential-ui-and-native-scalar-repairs-reconciliation); original marked gate retained, actual provider/seller/YouTube/manual/final pending |
| [P05-05a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p05-05a--exact-scalar-states-in-existing-verificationprovider-screens-in_progress) | in_progress | verified | verified | 235 | [Current credential/source-bound full native scalar evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p05-05-current-write-only-credential-ui-and-native-scalar-repairs-reconciliation); original marked gate retained, actual provider/seller/YouTube/manual/final pending |
| [P05-05b](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p05-05b--strict-provideraccountmodel-and-seller-row-enums-in_progress) | in_progress | verified | verified | — | [Current credential/source-bound full native scalar evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p05-05-current-write-only-credential-ui-and-native-scalar-repairs-reconciliation); original marked gate retained, actual provider/seller/YouTube/manual/final pending |
| [P05-05c](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p05-05c--dedicated-youtube-configuration-exact-scalar-state-in_progress) | in_progress | verified | verified | — | [Current credential/source-bound full native scalar evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p05-05-current-write-only-credential-ui-and-native-scalar-repairs-reconciliation); original marked gate retained, actual provider/seller/YouTube/manual/final pending |
| [P05-03](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p05-03--routing-fallbacks-and-model-configuration-ui-done) | done | verified | verified | 273, 276, 278, 279, 281, 282, 283, 286 | [Current source-bound routing/cost/native/full/review evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p05-03-current-routing-free-tier-and-catalog-scalar-reconciliation); actual provider/manual/final and conditional background/batch separate |
| [P05-03a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p05-03a--exact-scalar-model-tieraccount-source-native-catalog-in_progress) | in_progress | verified | verified | 284 | [Current source-bound routing/cost/native/full/review evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p05-03-current-routing-free-tier-and-catalog-scalar-reconciliation); actual provider/manual/final and conditional background/batch separate |
| [P05-04](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p05-04--usage-cost-and-provider-observability-done) | done | verified | verified | 273, 279, 280 | [Current source-bound routing/cost/native/full/review evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p05-04-current-ai-usage-cost-and-scalar-observability-reconciliation); actual provider/manual/final and conditional background/batch separate |
| [P06-01](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-01--project-configuration-and-resumable-onboarding-shell-done) | done | in_progress | in_progress | 290, 291, 292, 294, 295, 307 | Owning parent/phase gates unchanged |
| [P06-01a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-01a--scalar-onboarding-progress-and-scoped-saved-configuration-in_progress) | in_progress | in_progress | in_progress | 235 | Owning parent/phase gates unchanged |
| [P06-02](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-02--small-source-aware-connection-and-sync-contract-done) | done | verified | verified | 299, 300, 301, 311, 312 | [Current local contract evidence](IMPLEMENTATION_HISTORY_2026-10-16.md#p06-02-current-local-source-contract-verified); broader engine/mapping/consumer TODO owners unfinished |
| [P06-03](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-03--search-console-csv-import-done) | done | verified | verified | 296 | [Current local CSV source/check evidence](IMPLEMENTATION_HISTORY_2026-10-16.md#p06-03-current-local-csv-contract-verified); final/manual/provider gates separate |
| [P06-04](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-04--google-oauth-and-search-console-synchronization-done) | done | in_progress | in_progress | 292, 297, 298, 302, 308 | Real source grants |
| [P06-04a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-04a--scalar-existing-source-and-google-grant-scope-metadata-in_progress) | in_progress | pending | pending | 235 | Owning parent/phase gates unchanged |
| [P06-04b](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-04b--scalar-default-and-reviewed-query-brand-labels-in_progress) | in_progress | pending | pending | 235 | Owning parent/phase gates unchanged |
| [P06-04c](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-04c--scalar-search-console-sync-state-and-exact-acknowledgment-identity-in_progress) | in_progress | pending | pending | 235 | Owning parent/phase gates unchanged |
| [P06-04d](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-04d--scalar-indexed-version-coverage-job-and-source-labels-in_progress) | in_progress | pending | pending | 235 | Owning parent/phase gates unchanged |
| [P06-04e](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-04e--scalar-backfill-and-daily-schedule-metadatacurrent-refresh-in_progress) | in_progress | pending | pending | 235 | Owning parent/phase gates unchanged |
| [P06-05](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-05--ga4-synchronization-and-measurement-quality-blocked) | blocked | blocked | blocked | 303, 304, 305, 330, 726 | Exact-origin capability; Real source grants |
| [P06-05a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-05a--scalar-supported-analytics-grant-and-manual-review-metadata-in_progress) | in_progress | pending | pending | 235 | Owning parent/phase gates unchanged |
| [P06-05b](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-05b--scalar-historical-analytics-job-metadata-in_progress) | in_progress | pending | pending | 235 | Owning parent/phase gates unchanged |
| [P06-06](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-06--brand-segments-and-integration-status-ui-done) | done | verified | verified | 292, 306, 308 | Current original brand/status source + backend4/native3 verified; global final and real provider gates separate |
| [P06-07](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-07--budgeted-first-audit-and-first-value-journey-blocked) | blocked | in_progress | in_progress | 169, 195, 257, 293 | Current private retry/progress + focused/source review complete; whole/final/first-value successors/manual/source gates pending |
| [P06-08](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-08--bing-webmaster-connector-pending) | pending | blocked | blocked | 309 | Bing demand/capability |
| [P06-09](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-09--yandex-and-demand-driven-webmaster-extensions-pending) | in_progress | implemented; CSV/OAuth/bounded API sync, untested | deferred by D437 | 310, 313 | Real engine capability; Additional engine demand |
| [P07-01](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p07-01--bounded-remote-fetching-robots-and-sitemap-discovery-done) | done | verified | verified | 317, 319, 321 | Current original safe-fetch source/exact8 verified; prior marked review retained; global final separate |
| [P07-02](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p07-02--http-first-crawler-and-immutable-observations-done) | done | verified | verified | 317, 318, 319, 320, 322, 323, 324 | Current original crawler + repaired pre-send authority/focused/review/runtime verified; global final separate |
| [P07-03](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p07-03--selective-isolated-rendering-and-rawrendered-comparison-done) | done | verified | verified | 325, 326 | Current renderer/protocol/actual synthetic Chromium/runtime verified; original marked review retained; global final separate |
| [P07-04](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p07-04--canonicals-link-graph-url-variants-and-schema-diagnostics-done) | done | verified | verified | 322, 327, 328, 329, 331 | Current original diagnostics/source/owning4 and existing configuration/native evidence verified; global final separate |
| [P07-05](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p07-05--evidence-aware-indexation-reconciliation-done) | done | verified | verified | 330, 331 | Current original source/API5/native2 verified; actual provider/manual/final separate |
| [P07-06](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p07-06--pagespeed-and-crux-currenthistory-collection-done) | done | verified | verified | 332, 333, 334 | Current original performance source/focused/review/runtime/native verified; actual provider/final separate |
| [P07-06a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p07-06a--scalar-performance-job-and-parsed-source-metadata-in_progress) | in_progress | in_progress | in_progress | 235 | Owning parent/phase gates unchanged |
| [P08-01](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-01--deterministic-findings-and-opportunity-evidence-blocked) | blocked | blocked | blocked | 311, 312, 343, 344, 345, 346 | Exact-origin capability |
| [P08-01a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-01a--verified-source-limited-findings-substrate-done) | done | verified | verified | 340, 341, 342, 347 | Current original source-limited candidate/review/backend9/native3 verified; richer source and global final gates separate |
| [P08-01b](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-01b--source-dependent-candidate-gaps-blocked) | blocked | blocked | blocked | 347 | Exact-origin capability |
| [P08-01bq](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-01bq--genuine-search-console-querypage-source-and-overlap-candidates-done) | done | verified | verified | — | Current paired source/readback/export/deletion6/native10 verified; parent source gaps/global final/provider separate |
| [P08-01c](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-01c--scalar-candidate-preview-and-human-opportunity-review-metadata-in_progress) | in_progress | in_progress | in_progress | 235 | Owning parent/phase gates unchanged |
| [P08-02](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-02--intent-clusters-and-pageaction-mapping-done) | done | verified | verified | 350, 351 | Current original human mapping/source/revision/API5/native5 verified; global final separate |
| [P08-02a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-02a--scalar-intent-mapping-roles-and-source-kind-evidence-in_progress) | in_progress | in_progress | in_progress | 235 | Owning parent/phase gates unchanged |
| [P08-03](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-03--assigned-action-workflow-and-manual-change-logging-done) | done | verified | verified | 351, 352, 353 | Current original manual action/source/role/revision/API4/native4 verified; global final separate |
| [P08-03a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-03a--exact-scalar-action-source-and-retained-usefulness-metadata-in_progress) | in_progress | in_progress | in_progress | 235 | Owning parent/phase gates unchanged |
| [P08-03b](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-03b--exact-scalar-current-approval-and-assignee-roles-in_progress) | in_progress | in_progress | in_progress | 235 | Owning parent/phase gates unchanged |
| [P08-04](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-04--baselines-technical-verification-and-outcome-comparisons-blocked) | blocked | pending | pending | 351, 353, 888 | Exact-origin capability |
| [P08-04a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-04a--source-limited-page-and-crawl-action-follow-up-done) | done | verified | verified | 354, 355 | Owning parent/phase gates unchanged |
| [P08-04b](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-04b--conversionrevenue-attribution-context-blocked) | blocked | blocked | blocked | 355 | Exact-origin capability |
| [P08-04c](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-04c--scalar-action-comparison-roles-and-refreshed-authority-in_progress) | in_progress | in_progress | in_progress | 235 | Final current frontend pending; focused scalar role/refresh evidence retained |
| [P08-05](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-05--early-manual-local-assessment-done) | done | verified | verified | 356 | Owning parent/phase gates unchanged |
| [P08-05a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-05a--scalar-manual-local-review-roles-and-location-digest-in_progress) | in_progress | in_progress | in_progress | 235 | Owning parent/phase gates unchanged |
| [P08-06](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-06--plain-language-dashboard-and-opportunity-screens-blocked) | blocked | pending | pending | 348, 349, 357, 358, 359, 412 | Manual accessibility |
| [P08-06a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-06a--source-aware-text-first-project-dashboard-done) | done | verified | verified | 357 | Owning parent/phase gates unchanged |
| [P08-06b](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-06b--manual-dashboard-usability-and-accessibility-evidence-blocked) | blocked | excluded | excluded | 357 | Manual accessibility |
| [P08-06c](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-06c--exact-scalar-displayed-organization-access-state-in_progress) | in_progress | in_progress | in_progress | 235 | Owning parent/phase gates unchanged |
| [P08-07](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07--scheduled-summaries-alerts-and-preferences-pending) | pending | pending | pending | 360 | Sender/domain/copy |
| [P08-07a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07a--retained-private-report-weekly-summary-source-done) | done | verified | verified | 367 | Owning parent/phase gates unchanged |
| [P08-07b](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07b--default-off-self-owned-project-summary-preference-done) | done | verified | verified | 368 | Owning parent/phase gates unchanged |
| [P08-07b1](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07b1--enforce-existing-own-preference-get-rate-budget-done) | done | verified | verified | 372 | Owning parent/phase gates unchanged |
| [P08-07c](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07c--current-optional-weekly-delivery-source-eligibility-done) | done | verified | verified | 369 | Owning parent/phase gates unchanged |
| [P08-07d](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07d--optional-weekly-delivery-dedupe-and-uncertain-send-kernel-done) | done | verified | verified | 370 | Owning parent/phase gates unchanged |
| [P08-07e](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07e--default-queue-bounded-optional-weekly-discovery-done) | done | verified | verified | 371 | Owning parent/phase gates unchanged |
| [P08-07f](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07f--read-only-own-optional-weekly-delivery-history-source-done) | done | verified | verified | 373 | Owning parent/phase gates unchanged |
| [P08-07g](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07g--strict-private-own-weekly-delivery-history-get-done) | done | verified | verified | 374 | Owning parent/phase gates unchanged |
| [P08-07h](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07h--explicit-native-own-history-and-truthful-rollout-availability-done) | done | verified | verified | 375 | Owning parent/phase gates unchanged |
| [P08-07i](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07i--retained-failed-crawl-job-alert-source-prerequisite-done) | done | verified | verified | 376 | Owning parent/phase gates unchanged |
| [P08-07j](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07j--strict-private-retained-crawl-failure-get-done) | done | verified | verified | 377 | Owning parent/phase gates unchanged |
| [P08-07k](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07k--deliberate-native-retained-crawl-failure-inspector-done) | done | verified | verified | 378 | Owning parent/phase gates unchanged |
| [P08-07l](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07l--bounded-read-only-integration-health-metadata-source-done) | done | verified | verified | 379 | Owning parent/phase gates unchanged |
| [P08-07m](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07m--strict-private-integration-health-metadata-get-done) | done | verified | verified | 380 | Owning parent/phase gates unchanged |
| [P08-07n](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07n--deliberate-native-integration-health-metadata-inspector-done) | done | verified | verified | 381 | Owning parent/phase gates unchanged |
| [P08-07o](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07o--independent-default-off-own-project-alert-intent-done) | done | verified | verified | 382 | Owning parent/phase gates unchanged |
| [P08-07p](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07p--current-daily-crawl-failure-candidate-source-binding-done) | done | in_progress | in_progress | 383 | Owning parent/phase gates unchanged |
| [P08-07q](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07q--prospective-revision-bound-google-reconnect-audit-metadata-done) | done | pending | pending | 384 | Owning parent/phase gates unchanged |
| [P08-07r](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07r--current-daily-reconnect-candidate-source-binding-done) | done | pending | pending | 385 | Owning parent/phase gates unchanged |
| [P08-07s](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07s--one-day-complete-operational-digest-source-pin-done) | done | pending | pending | 386 | Owning parent/phase gates unchanged |
| [P08-07t](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07t--optional-daily-operational-digest-and-related-episode-dedupe-kernel-done) | done | pending | pending | 387 | Owning parent/phase gates unchanged |
| [P08-07u](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07u--default-queue-bounded-optional-daily-digest-discovery-done) | done | pending | pending | 388 | Owning parent/phase gates unchanged |
| [P08-07v](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07v--read-only-own-daily-operational-delivery-history-source-done) | done | pending | pending | 389 | Owning parent/phase gates unchanged |
| [P08-07w](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07w--strict-private-own-daily-delivery-history-get-done) | done | pending | pending | 390 | Owning parent/phase gates unchanged |
| [P08-07x](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07x--native-own-daily-history-and-truthful-rollout-availability-done) | done | pending | pending | 391 | Owning parent/phase gates unchanged |
| [P08-07y](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07y--prospective-original-performance-raw-response-digest-done) | done | pending | pending | 361 | Owning parent/phase gates unchanged |
| [P08-07z](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07z--exact-current-genuine-crux-history-threshold-candidate-source-done) | done | pending | pending | 362 | Owning parent/phase gates unchanged |
| [P08-07aa](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07aa--strict-private-exact-crux-candidate-source-get-done) | done | pending | pending | 363 | Owning parent/phase gates unchanged |
| [P08-07ab](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07ab--deliberate-native-exact-crux-history-inspector-done) | done | pending | pending | 364 | Owning parent/phase gates unchanged |
| [P08-07ac](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07ac--versioned-material-crux-threshold-candidate-filter-done) | done | pending | pending | 365 | Owning parent/phase gates unchanged |
| [P08-07ad](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07ad--strict-private-exact-crux-material-policy-get-done) | done | pending | pending | 366 | Owning parent/phase gates unchanged |
| [P08-07ae](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07ae--deliberate-native-exact-crux-material-policy-inspector-done) | done | pending | pending | 392 | Owning parent/phase gates unchanged |
| [P08-07af](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07af--genuine-observed-crux-source-period-episode-identity-done) | done | pending | pending | 393 | Owning parent/phase gates unchanged |
| [P08-07ag](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07ag--independent-default-off-own-crux-alert-intent-modelservice-done) | done | pending | pending | 394 | Owning parent/phase gates unchanged |
| [P08-07ah](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07ah--strict-private-own-crux-intent-getpost-done) | done | pending | pending | 395 | Owning parent/phase gates unchanged |
| [P08-07ai](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07ai--separate-native-own-crux-optional-intent-form-done) | done | pending | pending | 396 | Owning parent/phase gates unchanged |
| [P08-07aj](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07aj--current-exact-crux-recipient-and-collection-day-source-binding-done) | done | pending | pending | 397 | Owning parent/phase gates unchanged |
| [P08-07ak](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07ak--complete-newest-observed-crux-collection-and-daily-digest-pin-done) | done | pending | pending | 398 | Owning parent/phase gates unchanged |
| [P08-07al](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07al--independent-default-off-crux-delivery-and-related-sql-claims-done) | done | pending | pending | 399 | Owning parent/phase gates unchanged |
| [P08-07am](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07am--bounded-default-queue-crux-delivery-worker-consumer-done) | done | pending | pending | 400 | Owning parent/phase gates unchanged |
| [P08-07an](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07an--independent-own-retained-crux-delivery-history-source-done) | done | pending | pending | 401 | Owning parent/phase gates unchanged |
| [P08-07ao](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07ao--strict-private-own-crux-delivery-history-get-done) | done | pending | pending | 402 | Owning parent/phase gates unchanged |
| [P08-07ap](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07ap--native-own-crux-history-and-truthful-configured-availability-done) | done | pending | pending | 403 | Owning parent/phase gates unchanged |
| [P08-08](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-08--safe-exports-and-authenticatedexpiring-report-shares-done) | done | verified | verified | 408, 412 | Owning parent/phase gates unchanged |
| [P08-08a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-08a--final-private-report-and-share-delivery-authority-recovery-done) | done | verified | verified | 407 | Owning parent/phase gates unchanged |
| [P08-08b](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-08b--exact-scalar-private-reportshare-metadata-and-refresh-clearing-in_progress) | in_progress | in_progress | in_progress | 235 | Owning parent/phase gates unchanged |
| [P08-09](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-09--contextual-help-support-and-retention-visibility-pending) | pending | pending | pending | 409 | Live support operation |
| [P08-09a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-09a--minimized-retained-project-job-support-reference-source-done) | done | pending | pending | 404 | Owning parent/phase gates unchanged |
| [P08-09b](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-09b--strict-private-exact-retained-job-reference-get-done) | done | pending | pending | 405 | Owning parent/phase gates unchanged |
| [P08-09c](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-09c--deliberate-native-minimized-project-job-reference-inspector-done) | done | pending | pending | 406 | Owning parent/phase gates unchanged |
| [P08-09d](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-09d--immutable-own-project-support-request-kernel-and-customer-lifecycle-done) | done | pending | pending | — | Owning parent/phase gates unchanged |
| [P08-09e](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-09e--private-customer-support-journey-and-audited-scoped-staff-admin-done) | done | pending | pending | — | Owning parent/phase gates unchanged |
| [P08-09f](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-09f--native-contextual-faqglossary-and-retention-control-discovery-done) | done | pending | pending | — | Owning parent/phase gates unchanged |
| [P09-01](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p09-01--query-growth-topics-safe-rss-and-normalization-done) | done | pending | pending | 416, 417, 424 | Owning parent/phase gates unchanged |
| [P09-02](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p09-02--supported-news-video-and-trends-integrations-done) | done | pending | pending | 418, 419, 420, 422, 423 | Official Trends access; Real source grants |
| [P09-02a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p09-02a--exact-current-project-youtube-role-in_progress) | in_progress | pending | pending | 235 | Owning parent/phase gates unchanged |
| [P09-02b](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p09-02b--scalar-response-only-youtube-page-fields-in_progress) | in_progress | pending | pending | 421 | Owning parent/phase gates unchanged |
| [P09-03](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p09-03--topic-scoring-and-research-entry-points-done) | done | pending | pending | 424, 425, 435 | Owning parent/phase gates unchanged |
| [P09-03a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p09-03a--scalar-topic-review-role-and-confirmed-source-controls-in_progress) | in_progress | pending | pending | 426 | Owning parent/phase gates unchanged |
| [P09-03b](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p09-03b--exact-topic-job-history-detail-and-queue-acknowledgment-in_progress) | in_progress | pending | pending | 427 | Owning parent/phase gates unchanged |
| [P09-03c](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p09-03c--retire-pending-topic-loads-on-screen-destruction-in_progress) | in_progress | pending | pending | 427 | Owning parent/phase gates unchanged |
| [P09-03d](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p09-03d--scalar-current-topic-mapping-choices-in_progress) | in_progress | pending | pending | 428 | Owning parent/phase gates unchanged |
| [P09-03e](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p09-03e--scalar-topic-source-catalogue-and-collection-history-in_progress) | in_progress | pending | pending | 429 | Owning parent/phase gates unchanged |
| [P09-03f](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p09-03f--scalar-scoped-human-topic-review-responses-in_progress) | in_progress | pending | pending | 430 | Owning parent/phase gates unchanged |
| [P09-03g](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p09-03g--scalar-original-topic-candidate-evidence-in_progress) | in_progress | pending | pending | 430, 431 | Owning parent/phase gates unchanged |
| [P09-03h](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p09-03h--unicode-human-topic-review-text-limits-in_progress) | in_progress | pending | pending | 432 | Owning parent/phase gates unchanged |
| [P09-03i](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p09-03i--unicode-original-topic-candidate-bounds-in_progress) | in_progress | pending | pending | 433 | Owning parent/phase gates unchanged |
| [P09-03j](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p09-03j--unicode-topic-review-form-and-configured-market-in_progress) | in_progress | pending | pending | 434 | Owning parent/phase gates unchanged |
| [P10-01](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-01--sourced-opportunitytopic-research-done) | done | pending | pending | 319, 439, 452 | Owning parent/phase gates unchanged |
| [P10-01a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-01a--exact-scalar-current-project-research-history-in_progress) | in_progress | pending | pending | 440 | Owning parent/phase gates unchanged |
| [P10-01b](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-01b--native-research-rolecatalog-and-current-selection-guards-in_progress) | in_progress | pending | pending | 441 | Owning parent/phase gates unchanged |
| [P10-01c](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-01c--exact-research-job-statedetail-identity-and-destruction-fence-in_progress) | in_progress | pending | pending | 442 | Owning parent/phase gates unchanged |
| [P10-01d](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-01d--scalar-reviewed-topic-research-handoff-metadata-in_progress) | in_progress | pending | pending | 443 | Owning parent/phase gates unchanged |
| [P10-01e](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-01e--positive-scalar-current-research-mapping-choices-in_progress) | in_progress | pending | pending | 444 | Owning parent/phase gates unchanged |
| [P10-01f](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-01f--exact-supported-research-project-role-before-reads-in_progress) | in_progress | pending | pending | 451 | Owning parent/phase gates unchanged |
| [P10-01g](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-01g--scalar-research-modelaccount-catalogue-and-nullable-output-caps-in_progress) | in_progress | pending | pending | 450 | Owning parent/phase gates unchanged |
| [P10-01h](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-01h--scalar-research-job-counters-errors-and-nullable-cost-display-in_progress) | in_progress | pending | pending | 449 | Owning parent/phase gates unchanged |
| [P10-01i](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-01i--bounded-scalar-research-sources-and-exact-excerpt-linked-interpretations-in_progress) | in_progress | pending | pending | 448 | Owning parent/phase gates unchanged |
| [P10-01j](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-01j--match-submitted-research-model-and-provider-account-in_progress) | in_progress | pending | pending | 447 | Owning parent/phase gates unchanged |
| [P10-01k](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-01k--python-character-bounds-for-research-handoff-labels-and-policy-urls-in_progress) | in_progress | pending | pending | 445 | Owning parent/phase gates unchanged |
| [P10-01l](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-01l--full-unicode-research-topic-input-in_progress) | in_progress | pending | pending | 446 | Owning parent/phase gates unchanged |
| [P10-02](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-02--structured-content-briefs-and-internal-release-proof-done) | done | pending | pending | 458, 484 | Owning parent/phase gates unchanged |
| [P10-02a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-02a--current-brief-creation-roleresources-and-destruction-fences-in_progress) | in_progress | pending | pending | 453 | Owning parent/phase gates unchanged |
| [P10-02b](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-02b--exact-brief-acknowledgment-scope-and-positive-source-references-in_progress) | in_progress | pending | pending | 457 | Owning parent/phase gates unchanged |
| [P10-02c](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-02c--scalar-current-brief-source-choices-in_progress) | in_progress | pending | pending | 454 | Owning parent/phase gates unchanged |
| [P10-02d](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-02d--exact-unicode-human-brief-input-bounds-in_progress) | in_progress | pending | pending | 455 | Owning parent/phase gates unchanged |
| [P10-02e](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-02e--scoped-bounded-private-brief-draft-responses-in_progress) | in_progress | pending | pending | 456 | Owning parent/phase gates unchanged |
| [P10-03](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03--content-items-revisions-approval-and-studio-done) | done | pending | pending | 459, 468, 475, 476, 483, 484 | Owning parent/phase gates unchanged |
| [P10-03a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03a--exact-scalar-studio-roles-and-current-refresh-authority-in_progress) | in_progress | pending | pending | 474 | Owning parent/phase gates unchanged |
| [P10-03b](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03b--exact-native-content-revision-transition-keys-in_progress) | in_progress | pending | pending | — | Owning parent/phase gates unchanged |
| [P10-03c](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03c--stale-studio-save-chain-and-component-destruction-fences-in_progress) | in_progress | pending | pending | — | Owning parent/phase gates unchanged |
| [P10-03d](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03d--unicode-human-content-editor-input-bounds-in_progress) | in_progress | pending | pending | 473 | Owning parent/phase gates unchanged |
| [P10-03e](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03e--scalar-scoped-studio-brief-choice-provenance-in_progress) | in_progress | pending | pending | 472 | Owning parent/phase gates unchanged |
| [P10-03f](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03f--scalar-content-revision-identities-across-existing-readers-in_progress) | in_progress | pending | pending | 471 | Owning parent/phase gates unchanged |
| [P10-03g](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03g--guard-manual-publication-date-before-busy-state-in_progress) | in_progress | pending | pending | 470 | Owning parent/phase gates unchanged |
| [P10-03h](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03h--bounded-native-revision-title-rationale-and-text-readers-in_progress) | in_progress | pending | pending | 469 | Owning parent/phase gates unchanged |
| [P10-03i](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03i--original-private-studio-brief-evidence-guards-in_progress) | in_progress | pending | pending | 460 | Owning parent/phase gates unchanged |
| [P10-03j](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03j--exact-private-brief-source-status-and-pending-read-clearing-in_progress) | in_progress | pending | pending | 461 | Owning parent/phase gates unchanged |
| [P10-03k](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03k--nullable-original-generation-and-human-approval-references-in_progress) | in_progress | pending | pending | 462 | Owning parent/phase gates unchanged |
| [P10-03l](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03l--aware-revision-dates-and-paired-manual-publication-metadata-in_progress) | in_progress | pending | pending | 463 | Owning parent/phase gates unchanged |
| [P10-03m](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03m--positive-original-inventory-and-revision-pagination-cursors-in_progress) | in_progress | pending | pending | 464 | Owning parent/phase gates unchanged |
| [P10-03n](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03n--literal-manual-publication-url-syntax-in-revision-readers-in_progress) | in_progress | pending | pending | 465 | Owning parent/phase gates unchanged |
| [P10-03o](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03o--aware-original-private-brief-source-retrieval-dates-in_progress) | in_progress | pending | pending | 466 | Owning parent/phase gates unchanged |
| [P10-03p](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03p--aware-original-source-brief-catalogue-creation-dates-in_progress) | in_progress | pending | pending | 467 | Owning parent/phase gates unchanged |
| [P10-04](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-04--draft-generation-and-platform-specific-social-variants-done) | done | pending | pending | 477, 482, 483 | Owning parent/phase gates unchanged |
| [P10-04a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-04a--exact-native-content-model-tieraccount-source-and-catalog-refresh-in_progress) | in_progress | pending | pending | 481 | Owning parent/phase gates unchanged |
| [P10-04b](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-04b--native-generation-state-usage-and-unapproved-draft-evidence-in_progress) | in_progress | pending | pending | — | Owning parent/phase gates unchanged |
| [P10-04c](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-04c--content-studio-modelaccount-catalogue-scalar-metadata-in_progress) | in_progress | pending | pending | 480 | Owning parent/phase gates unchanged |
| [P10-04d](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-04d--generation-request-token-limits-and-explicit-free-consent-in_progress) | in_progress | pending | pending | 479 | Owning parent/phase gates unchanged |
| [P10-04e](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-04e--scalar-generation-job-provenance-counters-and-usage-display-in_progress) | in_progress | pending | pending | 478 | Owning parent/phase gates unchanged |
| [P10-05](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-05--content-inventory-expertise-and-lifecycle-review-done) | done | pending | pending | 489, 495, 496, 497 | Owning parent/phase gates unchanged |
| [P10-05a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-05a--full-unicode-exact-native-text-lifecycle-body-bound-in_progress) | in_progress | pending | pending | 488 | Owning parent/phase gates unchanged |
| [P10-05b](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-05b--unicode-and-serialized-byte-bounds-for-human-lifecycle-commands-in_progress) | in_progress | pending | pending | 487 | Owning parent/phase gates unchanged |
| [P10-05c](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-05c--full-human-lifecycle-review-declaration-readers-in_progress) | in_progress | pending | pending | 486 | Owning parent/phase gates unchanged |
| [P10-05d](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-05d--combined-private-human-review-evidence-ceiling-in_progress) | in_progress | pending | pending | 485 | Owning parent/phase gates unchanged |
| [P11-01](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01--approved-competitors-and-bounded-public-comparison-in_progress) | in_progress | pending | pending | 603, 605, 608, 614, 625, 626, 628 | Real source grants |
| [P11-01a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01a--current-explicitly-selected-competitor-source-done) | done | pending | pending | 603 | Owning parent/phase gates unchanged |
| [P11-01b](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01b--minimized-original-static-competitor-metadata-done) | done | pending | pending | 606 | Owning parent/phase gates unchanged |
| [P11-01c](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01c--protected-original-single-competitor-document-producer-done) | done | pending | pending | 611 | Owning parent/phase gates unchanged |
| [P11-01d](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01d--once-only-private-competitor-root-job-done) | done | pending | pending | 609 | Owning parent/phase gates unchanged |
| [P11-01e](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01e--complete-private-competitor-root-apinative-delivery-done) | done | pending | pending | 609, 610 | Owning parent/phase gates unchanged |
| [P11-01f](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01f--original-same-root-static-competitor-comparison-done) | done | pending | pending | — | Owning parent/phase gates unchanged |
| [P11-01g](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01g--exact-private-same-root-comparison-delivery-done) | done | pending | pending | 618 | Owning parent/phase gates unchanged |
| [P11-01h](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01h--original-static-pair-synthesis-source-done) | done | pending | pending | 619 | Owning parent/phase gates unchanged |
| [P11-01i](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01i--bounded-cited-static-pair-ai-interpretations-done) | done | pending | pending | 620 | Owning parent/phase gates unchanged |
| [P11-01j](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01j--owning-provider-source-transfer-checkpoints-done) | done | pending | pending | 595 | Owning parent/phase gates unchanged |
| [P11-01k](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01k--once-only-original-pair-configured-synthesis-job-done) | done | pending | pending | 596, 597, 598 | Owning parent/phase gates unchanged |
| [P11-01l](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01l--complete-private-original-pair-synthesis-consumers-done) | done | pending | pending | 599, 600, 601 | Owning parent/phase gates unchanged |
| [P11-01m](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01m--original-static-json-ld-type-projection-done) | done | pending | pending | 593 | Owning parent/phase gates unchanged |
| [P11-01n](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01n--protected-original-schema-root-producer-done) | done | pending | pending | 591 | Owning parent/phase gates unchanged |
| [P11-01o](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01o--original-competitor-lifecycle-final-metadata-authority-done) | done | pending | pending | 589 | Owning parent/phase gates unchanged |
| [P11-01p](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01p--original-comparison-final-pair-metadata-authority-done) | done | pending | pending | 587 | Owning parent/phase gates unchanged |
| [P11-01q](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01q--original-private-rootpair-api-final-metadata-authority-done) | done | pending | pending | 585 | Owning parent/phase gates unchanged |
| [P11-01r](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01r--original-synthesis-source-final-pair-pins-authority-done) | done | pending | pending | 583 | Owning parent/phase gates unchanged |
| [P11-01s](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01s--configured-selection-final-row-original-pair-authority-done) | done | pending | pending | 581 | Owning parent/phase gates unchanged |
| [P11-01t](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01t--original-private-synthesis-final-own-metadata-authority-done) | done | pending | pending | 579 | Owning parent/phase gates unchanged |
| [P11-01u](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01u--private-synthesis-api-final-metadata-authority-done) | done | pending | pending | 577 | Owning parent/phase gates unchanged |
| [P11-01v](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01v--original-root-final-private-byte-readback-done) | done | pending | pending | 506 | Owning parent/phase gates unchanged |
| [P11-01w](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01w--once-only-private-competitor-schema-root-job-done) | done | pending | pending | 507 | Owning parent/phase gates unchanged |
| [P11-01x](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01x--complete-private-competitor-schema-root-consumers-done) | done | pending | pending | 508 | Owning parent/phase gates unchanged |
| [P11-01y](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01y--minimized-original-static-competitor-link-categories-done) | done | pending | pending | 509 | Owning parent/phase gates unchanged |
| [P11-01z](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01z--protected-original-competitor-root-link-producer-done) | done | pending | pending | 510 | Owning parent/phase gates unchanged |
| [P11-01aa](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01aa--once-only-private-competitor-root-link-job-done) | done | pending | pending | 511 | Owning parent/phase gates unchanged |
| [P11-01ab](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ab--complete-private-competitor-root-link-consumers-done) | done | pending | pending | 512 | Owning parent/phase gates unchanged |
| [P11-01ac](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ac--current-explicitly-selected-non-root-competitor-page-source-done) | done | pending | pending | 513 | Owning parent/phase gates unchanged |
| [P11-01ad](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ad--protected-original-selected-competitor-page-metadata-producer-done) | done | pending | pending | 514 | Owning parent/phase gates unchanged |
| [P11-01ae](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ae--once-only-private-exact-selected-competitor-page-lifecycle-done) | done | pending | pending | 515 | Owning parent/phase gates unchanged |
| [P11-01af](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01af--fixed-private-exact-competitor-page-api-and-native-commands-done) | done | pending | pending | 516 | Owning parent/phase gates unchanged |
| [P11-01ag](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ag--final-all-original-cancellation-fence-for-saved-competitor-pairs-done) | done | pending | pending | 517 | Owning parent/phase gates unchanged |
| [P11-01ah](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ah--read-only-original-same-uri-selected-competitor-page-comparisons-done) | done | pending | pending | 518 | Owning parent/phase gates unchanged |
| [P11-01ai](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ai--complete-fixed-privatenative-original-selected-page-comparisons-done) | done | pending | pending | 519 | Owning parent/phase gates unchanged |
| [P11-01aj](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01aj--read-only-original-schema-root-label-comparisons-done) | done | pending | pending | 520 | Owning parent/phase gates unchanged |
| [P11-01ak](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ak--complete-fixed-privatenative-original-schema-root-comparisons-done) | done | pending | pending | 521 | Owning parent/phase gates unchanged |
| [P11-01al](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01al--read-only-original-link-root-category-comparisons-done) | done | pending | pending | 522 | Owning parent/phase gates unchanged |
| [P11-01am](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01am--complete-fixed-privatenative-original-link-root-comparisons-done) | done | pending | pending | 523 | Owning parent/phase gates unchanged |
| [P11-01an](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01an--minimized-literal-original-static-competitor-headings-done) | done | pending | pending | 524 | Owning parent/phase gates unchanged |
| [P11-01ao](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ao--protected-exact-selected-page-literal-heading-producer-done) | done | pending | pending | 525 | Owning parent/phase gates unchanged |
| [P11-01ap](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ap--once-only-private-original-selected-page-heading-observations-done) | done | pending | pending | 526 | Owning parent/phase gates unchanged |
| [P11-01aq](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01aq--complete-fixed-privatenative-selected-page-heading-observations-done) | done | pending | pending | 527 | Owning parent/phase gates unchanged |
| [P11-01ar](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ar--read-only-original-same-uri-heading-textorder-comparisons-done) | done | pending | pending | 528 | Owning parent/phase gates unchanged |
| [P11-01as](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01as--complete-fixed-privatenative-original-heading-comparisons-done) | done | pending | pending | 529 | Owning parent/phase gates unchanged |
| [P11-01at](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01at--original-bounded-same-origin-static-destination-references-done) | done | pending | pending | 530 | Owning parent/phase gates unchanged |
| [P11-01au](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01au--protected-original-selected-page-destination-reference-producer-done) | done | pending | pending | 531 | Owning parent/phase gates unchanged |
| [P11-01av](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01av--once-only-private-original-selected-page-reference-observations-done) | done | pending | pending | 532 | Owning parent/phase gates unchanged |
| [P11-01aw](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01aw--complete-fixed-privatenative-selected-page-reference-observations-done) | done | pending | pending | 533 | Owning parent/phase gates unchanged |
| [P11-01ax](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ax--read-only-original-same-uri-supported-reference-comparisons-done) | done | pending | pending | 534 | Owning parent/phase gates unchanged |
| [P11-01ay](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ay--complete-fixed-privatenative-original-reference-pairs-done) | done | pending | pending | 535 | Owning parent/phase gates unchanged |
| [P11-01az](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01az--original-saved-heading-pair-ai-input-and-indexed-citations-done) | done | pending | pending | 536 | Owning parent/phase gates unchanged |
| [P11-01ba](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ba--read-only-fixed-original-heading-pair-model-selection-done) | done | pending | pending | 537 | Owning parent/phase gates unchanged |
| [P11-01bb](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bb--once-only-private-original-heading-pair-synthesis-done) | done | pending | pending | 538 | Owning parent/phase gates unchanged |
| [P11-01bc](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bc--complete-fixed-privatenative-original-heading-pair-synthesis-done) | done | pending | pending | 539 | Owning parent/phase gates unchanged |
| [P11-01bd](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bd--pure-bounded-original-publicationupdate-declarations-done) | done | pending | pending | 540 | Owning parent/phase gates unchanged |
| [P11-01be](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01be--protected-exact-page-article-date-declaration-producer-done) | done | pending | pending | 541 | Owning parent/phase gates unchanged |
| [P11-01bf](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bf--once-only-private-original-article-date-declarations-done) | done | pending | pending | 542 | Owning parent/phase gates unchanged |
| [P11-01bg](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bg--complete-fixed-privatenative-article-date-declaration-consumers-done) | done | pending | pending | 543 | Owning parent/phase gates unchanged |
| [P11-01bh](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bh--read-only-original-same-uri-article-date-declaration-comparisons-done) | done | pending | pending | 545 | Owning parent/phase gates unchanged |
| [P11-01bi](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bi--complete-fixed-privatenative-original-date-declaration-pairs-done) | done | pending | pending | 547 | Owning parent/phase gates unchanged |
| [P11-01bj](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bj--pure-bounded-original-selected-uri-lighthouse-lab-evidence-done) | done | pending | pending | 549 | Owning parent/phase gates unchanged |
| [P11-01bk](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bk--current-read-only-selected-competitor-lighthouse-source-done) | done | pending | pending | 551 | Owning parent/phase gates unchanged |
| [P11-01bl](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bl--read-only-selected-competitor-lighthouse-credential-preparation-done) | done | pending | pending | 553 | Owning parent/phase gates unchanged |
| [P11-01bm](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bm--protected-fixed-host-competitor-lighthouse-transport-done) | done | pending | pending | 555 | Owning parent/phase gates unchanged |
| [P11-01bn](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bn--protected-current-source-key-robots-competitor-lighthouse-producer-done) | done | pending | pending | 557 | Owning parent/phase gates unchanged |
| [P11-01bo](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bo--once-only-private-selected-competitor-lighthouse-audit-done) | done | pending | pending | 559 | Owning parent/phase gates unchanged |
| [P11-01bp](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bp--complete-fixed-privatenative-competitor-lighthouse-consumers-done) | done | pending | pending | 561 | Owning parent/phase gates unchanged |
| [P11-01bq](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bq--original-saved-lighthouse-lab-pair-arithmetic-source-done) | done | pending | pending | 563 | Owning parent/phase gates unchanged |
| [P11-01br](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01br--complete-original-lighthouse-lab-pair-apinative-consumers-done) | done | pending | pending | 565 | Owning parent/phase gates unchanged |
| [P11-01bs](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bs--original-single-heading-ai-topic-hypothesis-input-done) | done | pending | pending | 567 | Owning parent/phase gates unchanged |
| [P11-01bt](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bt--original-single-heading-topic-model-preparation-in_progress) | in_progress | pending | pending | 568 | Owning parent/phase gates unchanged |
| [P11-01bu](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bu--once-only-private-single-heading-topic-hypotheses-in_progress) | in_progress | pending | pending | 569 | Owning parent/phase gates unchanged |
| [P11-01bv](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bv--complete-single-heading-topic-apinative-consumers-in_progress) | in_progress | pending | pending | 570 | Owning parent/phase gates unchanged |
| [P11-01bw](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bw--two-saved-page-static-reference-structure-in_progress) | in_progress | pending | pending | 571 | Owning parent/phase gates unchanged |
| [P11-01bx](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bx--private-two-saved-page-reference-consumers-in_progress) | in_progress | pending | pending | 572 | Owning parent/phase gates unchanged |
| [P11-01by](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01by--literal-saved-topic-hypothesis-comparison-source-in_progress) | in_progress | pending | pending | 573 | Owning parent/phase gates unchanged |
| [P11-01bz](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bz--shared-private-synthesis-final-reader-recovery-in_progress) | in_progress | pending | pending | 575 | Owning parent/phase gates unchanged |
| [P11-01ca](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ca--private-saved-topic-hypothesis-comparison-consumers-in_progress) | in_progress | pending | pending | 574 | Owning parent/phase gates unchanged |
| [P11-01cb](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cb--original-observation-and-reference-terminal-reader-recovery-in_progress) | in_progress | pending | pending | 662 | Owning parent/phase gates unchanged |
| [P11-01cc](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cc--dated-static-and-lab-pair-terminal-reader-recovery-in_progress) | in_progress | pending | pending | 663 | Owning parent/phase gates unchanged |
| [P11-01cd](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cd--original-ai-source-packet-terminal-reader-recovery-in_progress) | in_progress | pending | pending | 664 | Owning parent/phase gates unchanged |
| [P11-01ce](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ce--shared-model-preparation-terminal-reader-recovery-in_progress) | in_progress | pending | pending | 665 | Owning parent/phase gates unchanged |
| [P11-01cf](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cf--literal-saved-destination-inventory-source-in_progress) | in_progress | pending | pending | 666 | Owning parent/phase gates unchanged |
| [P11-01cg](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cg--private-saved-destination-inventory-consumers-in_progress) | in_progress | pending | pending | 667 | Owning parent/phase gates unchanged |
| [P11-01ch](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ch--bounded-static-content-element-counts-in_progress) | in_progress | pending | pending | 668 | Owning parent/phase gates unchanged |
| [P11-01ci](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ci--fixed-protected-static-content-element-producer-in_progress) | in_progress | pending | pending | 670 | Owning parent/phase gates unchanged |
| [P11-01cj](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cj--once-only-private-static-content-element-lifecycle-in_progress) | in_progress | pending | pending | 672 | Owning parent/phase gates unchanged |
| [P11-01ck](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ck--complete-private-static-content-element-consumers-in_progress) | in_progress | pending | pending | 674 | Owning parent/phase gates unchanged |
| [P11-01cl](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cl--original-static-content-element-pair-source-in_progress) | in_progress | pending | pending | 676 | Owning parent/phase gates unchanged |
| [P11-01cm](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cm--fixed-private-static-content-element-pair-consumers-in_progress) | in_progress | pending | pending | 678 | Owning parent/phase gates unchanged |
| [P11-01cn](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cn--actual-final-private-reader-authority-discovery-in_progress) | in_progress | pending | pending | 680 | Owning parent/phase gates unchanged |
| [P11-01co](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01co--final-capture-validation-metadata-discovery-in_progress) | in_progress | pending | pending | 681 | Owning parent/phase gates unchanged |
| [P11-01cp](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cp--original-two-page-static-element-source-in_progress) | in_progress | pending | pending | 682 | Owning parent/phase gates unchanged |
| [P11-01cq](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cq--complete-private-two-page-static-element-consumers-in_progress) | in_progress | pending | pending | 683 | Owning parent/phase gates unchanged |
| [P11-01cr](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cr--pure-stored-article-date-literal-candidates-in_progress) | in_progress | pending | pending | 684 | Owning parent/phase gates unchanged |
| [P11-01cs](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cs--current-private-original-date-literal-candidates-in_progress) | in_progress | pending | pending | 685 | Owning parent/phase gates unchanged |
| [P11-01ct](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ct--complete-private-saved-date-syntax-candidate-consumers-in_progress) | in_progress | pending | pending | 686 | Owning parent/phase gates unchanged |
| [P11-01cu](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cu--original-dated-date-candidate-arithmetic-source-in_progress) | in_progress | pending | pending | 687 | Owning parent/phase gates unchanged |
| [P11-01cv](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cv--complete-private-dated-date-candidate-interval-consumers-in_progress) | in_progress | pending | pending | 688 | Owning parent/phase gates unchanged |
| [P11-01cw](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cw--two-saved-page-literal-heading-count-source-in_progress) | in_progress | pending | pending | 689 | Owning parent/phase gates unchanged |
| [P11-01cx](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cx--complete-private-two-page-heading-count-consumers-in_progress) | in_progress | pending | pending | 690 | Owning parent/phase gates unchanged |
| [P11-01cy](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cy--saved-topic-comparison-terminal-authority-discovery-in_progress) | in_progress | pending | pending | 692 | Owning parent/phase gates unchanged |
| [P11-01cz](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cz--debug-disabled-saved-topic-read-timing-and-query-evidence-in_progress) | in_progress | pending | pending | 694 | Owning parent/phase gates unchanged |
| [P11-01da](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01da--saved-topic-guarded-reader-call-cost-trace-in_progress) | in_progress | pending | pending | 696 | Owning parent/phase gates unchanged |
| [P11-01db](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01db--one-transient-validated-source-frame-per-private-synthesis-reader-in_progress) | in_progress | pending | pending | 698 | Owning parent/phase gates unchanged |
| [P11-01dc](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01dc--current-competitor-app-ready-automated-validation-in_progress) | in_progress | pending | pending | 699, 870 | Owning parent/phase gates unchanged |
| [P11-01dd](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01dd--one-fresh-joined-organization-authority-query-in_progress) | in_progress | pending | pending | 703 | Owning parent/phase gates unchanged |
| [P11-01de](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01de--exact-synthesis-catalog-and-historical-metadata-scalars-in_progress) | in_progress | pending | pending | 235 | Owning parent/phase gates unchanged |
| [P11-02](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-02--serp-api-and-scheduled-rank-observations-pending) | in_progress | implemented; configurable SERP/schedules/native, untested | deferred by D437 | 513, 607, 622, 625, 626, 628 | SERP provider selection |
| [P11-03](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-03--external-keyword-backlinks-and-optional-traffic-estimates-pending) | pending | blocked | blocked | 513, 617, 621, 623, 624, 625, 626, 628 | Commercial data justification |
| [P11-04](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-04--authority-and-link-recovery-opportunity-management-in_progress) | in_progress | pending | pending | 643, 645 | Human outreach/action |
| [P11-04a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-04a--existing-source-human-authority-prospects-done) | done | pending | pending | — | Owning parent/phase gates unchanged |
| [P11-04b](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-04b--source-supported-link-verification-and-recovery-in_progress) | in_progress | pending | pending | — | Human outreach/action |
| [P11-04c](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-04c--scalar-human-link-proposal-action-metadata-in_progress) | in_progress | pending | pending | 235 | Owning parent/phase gates unchanged |
| [P11-04d](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-04d--scalar-selected-link-source-and-human-mention-states-in_progress) | in_progress | pending | pending | 235 | Owning parent/phase gates unchanged |
| [P11-04bv](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-04bv--selected-static-html-link-verification-source-done) | done | pending | pending | — | Owning parent/phase gates unchanged |
| [P11-04bh](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-04bh--comparable-selected-source-link-observation-history-done) | done | pending | pending | — | Owning parent/phase gates unchanged |
| [P11-04bm](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-04bm--body-matched-existing-source-mention-candidates-done) | done | pending | pending | — | Owning parent/phase gates unchanged |
| [P11-04br](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-04br--saved-static-target-destination-recovery-candidates-done) | done | pending | pending | — | Owning parent/phase gates unchanged |
| [P11-04bu](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-04bu--explicit-bounded-static-uri-reference-observations-done) | done | pending | pending | — | Owning parent/phase gates unchanged |
| [P11-05](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-05--authorized-local-profiles-reviews-and-local-visibility-done) | done | pending | pending | — | Real source grants |
| [P11-05a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-05a--authorized-response-only-gbp-profile-and-review-reader-done) | done | pending | pending | 640, 641 | Real source grants |
| [P11-05b](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-05b--source-permitted-review-themes-and-reviewed-reply-proposals-done) | done | pending | pending | — | Real source grants |
| [P11-05c](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-05c--supported-location-specific-local-visibility-observations-done) | done | pending | pending | 642 | Real source grants |
| [P11-05d](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-05d--scalar-manager-roles-before-response-only-business-profile-status-in_progress) | in_progress | pending | pending | 235 | Owning parent/phase gates unchanged |
| [P11-06](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-06--optional-authorized-bot-log-imports-done) | done | pending | pending | 659, 660 | Owning parent/phase gates unchanged |
| [P11A-01](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11a-01--supported-surfaces-and-versioned-prompt-methodology-done) | done | pending | pending | 717, 718 | Provider terms/cost/access |
| [P11A-02](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11a-02--evidence-preserving-answer-collection-done) | done | pending | pending | 718, 722 | Provider terms/cost/access |
| [P11A-02s](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11a-02s--scheduled-repeats-and-additional-observation-surfaces-done) | done | pending | pending | 719, 721, 722 | Provider terms/cost/access |
| [P11A-02sa](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11a-02sa--finite-opt-in-native-api-text-repeats-done) | done | pending | pending | 720 | Owning parent/phase gates unchanged |
| [P11A-02sb](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11a-02sb--additional-licensed-or-human-reported-observations-done) | done | pending | pending | 721 | Owning parent/phase gates unchanged |
| [P11A-02sb1](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11a-02sb1--consistent-native-human-report-mention-percentages-in_progress) | in_progress | pending | pending | 707 | Owning parent/phase gates unchanged |
| [P11A-02sb2](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11a-02sb2--exact-scalar-human-observation-identifiers-in_progress) | in_progress | pending | pending | 708 | Owning parent/phase gates unchanged |
| [P11A-03](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11a-03--correctable-entity-extraction-and-deterministic-rates-done) | done | pending | pending | 723, 724 | Supported fact/citation surface |
| [P11A-04](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11a-04--like-for-like-history-referrals-and-discoverability-blocked) | blocked | pending | pending | 726 | Exact-origin capability |
| [P11A-04a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11a-04a--source-independent-history-and-discoverability-done) | done | pending | pending | 725, 727 | Owning parent/phase gates unchanged |
| [P11A-04r](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11a-04r--identifiable-ai-referrals-from-an-exact-origin-source-blocked) | blocked | blocked | blocked | 726 | Exact-origin capability |
| [P11A-05](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11a-05--ai-visibility-release-and-truthful-claims-done) | done | pending | pending | 717, 729, 730 | AI live/legal readiness |
| [P11A-05a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11a-05a--scalar-roles-across-the-supported-api-visibility-journey-in_progress) | in_progress | pending | pending | 235 | Owning parent/phase gates unchanged |
| [P12-01](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-01--ownership-verification-and-passive-audit-scope-done) | done | pending | pending | 826, 847 | Verified ownership/scope |
| [P12-02](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02--passive-httpstlsheadercontent-findings-pending) | pending | pending | pending | 827, 829, 844, 845, 846 | Verified ownership/scope |
| [P12-02a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02a--pure-minimized-response-header-interpretation-done) | done | pending | pending | 827 | Owning parent/phase gates unchanged |
| [P12-02b](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02b--exact-current-passive-header-source-binding-done) | done | pending | pending | 828 | Owning parent/phase gates unchanged |
| [P12-02c](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02c--protected-transient-first-response-header-transport-done) | done | pending | pending | 824 | Owning parent/phase gates unchanged |
| [P12-02d](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02d--once-only-manual-passive-header-collector-and-private-evidence-done) | done | pending | pending | 815 | Owning parent/phase gates unchanged |
| [P12-02e](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02e--private-passive-header-customer-consumers-done) | done | pending | pending | 816 | Owning parent/phase gates unchanged |
| [P12-02f](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02f--pure-minimized-peer-certificate-date-interpretation-done) | done | pending | pending | 817 | Owning parent/phase gates unchanged |
| [P12-02g](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02g--separate-current-certificatetls-exact-origin-source-done) | done | pending | pending | 818 | Owning parent/phase gates unchanged |
| [P12-02h](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02h--protected-minimized-handshake-only-tls-transport-done) | done | pending | pending | 819 | Owning parent/phase gates unchanged |
| [P12-02i](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02i--strict-original-minimized-tls-evidence-contract-done) | done | pending | pending | 820 | Owning parent/phase gates unchanged |
| [P12-02j](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02j--once-only-manual-tls-collectorprivate-evidence-done) | done | pending | pending | 821 | Owning parent/phase gates unchanged |
| [P12-02k](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02k--private-deliberate-tls-customer-consumers-done) | done | pending | pending | 822 | Owning parent/phase gates unchanged |
| [P12-02l](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02l--pure-selected-static-resource-reference-candidates-done) | done | pending | pending | 843 | Owning parent/phase gates unchanged |
| [P12-02m](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02m--independent-current-static-resource-exact-url-source-done) | done | pending | pending | 842 | Owning parent/phase gates unchanged |
| [P12-02n](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02n--protected-complete-length-framed-static-resource-transport-done) | done | pending | pending | 841 | Owning parent/phase gates unchanged |
| [P12-02o](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02o--strict-original-minimized-static-resource-evidence-done) | done | pending | pending | 840 | Owning parent/phase gates unchanged |
| [P12-02p](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02p--once-only-manual-static-resource-collectorprivate-evidence-done) | done | pending | pending | 838 | Owning parent/phase gates unchanged |
| [P12-02q](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02q--private-deliberate-static-resource-customer-consumers-done) | done | pending | pending | 839 | Owning parent/phase gates unchanged |
| [P12-02r](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02r--pure-original-first-response-location-metadata-done) | done | pending | pending | 834, 837 | Owning parent/phase gates unchanged |
| [P12-02s](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02s--independent-current-first-response-location-source-done) | done | pending | pending | 835 | Owning parent/phase gates unchanged |
| [P12-02t](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02t--protected-original-first-response-location-transport-done) | done | pending | pending | 836, 837 | Owning parent/phase gates unchanged |
| [P12-02u](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02u--strict-original-minimized-private-location-evidence-done) | done | pending | pending | 813 | Owning parent/phase gates unchanged |
| [P12-02v](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02v--once-only-manual-location-collectorprivate-evidence-done) | done | pending | pending | 810 | Owning parent/phase gates unchanged |
| [P12-02w](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02w--private-deliberate-location-customer-consumers-done) | done | pending | pending | 811 | Owning parent/phase gates unchanged |
| [P12-02x](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02x--pure-original-response-header-review-candidates-done) | done | pending | pending | 806 | Owning parent/phase gates unchanged |
| [P12-02y](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02y--current-private-original-header-candidate-source-done) | done | pending | pending | 807 | Owning parent/phase gates unchanged |
| [P12-02z](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02z--exact-private-header-candidate-get-consumer-done) | done | pending | pending | 808 | Owning parent/phase gates unchanged |
| [P12-02aa](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02aa--deliberate-native-original-header-candidate-inspection-done) | done | pending | pending | — | Owning parent/phase gates unchanged |
| [P12-02ab](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ab--genuine-private-header-finding-relation-and-materialization-done) | done | pending | pending | 774 | Owning parent/phase gates unchanged |
| [P12-02ac](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ac--exact-private-header-finding-getpost-commands-done) | done | pending | pending | 775, 776 | Owning parent/phase gates unchanged |
| [P12-02ad](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ad--deliberate-native-header-finding-materializationcurrent-inspection-done) | done | pending | pending | — | Owning parent/phase gates unchanged |
| [P12-02ae](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ae--pure-original-static-resource-review-candidate-done) | done | pending | pending | 777 | Owning parent/phase gates unchanged |
| [P12-02af](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02af--current-private-original-resource-candidate-source-done) | done | pending | pending | 778 | Owning parent/phase gates unchanged |
| [P12-02ag](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ag--exact-private-resource-candidate-get-consumer-done) | done | pending | pending | 779, 780 | Owning parent/phase gates unchanged |
| [P12-02ah](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ah--deliberate-native-original-resource-candidate-inspection-done) | done | pending | pending | — | Owning parent/phase gates unchanged |
| [P12-02ai](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ai--compact-original-resource-finding-recipes-done) | done | pending | pending | 781 | Owning parent/phase gates unchanged |
| [P12-02aj](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02aj--genuine-private-resource-finding-relation-and-lifecycle-done) | done | pending | pending | 782 | Owning parent/phase gates unchanged |
| [P12-02ak](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ak--exact-private-resource-finding-getpost-commands-done) | done | pending | pending | 783, 804 | Owning parent/phase gates unchanged |
| [P12-02al](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02al--deliberate-native-resource-finding-commandscurrent-inspection-done) | done | pending | pending | — | Owning parent/phase gates unchanged |
| [P12-02am](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02am--pure-original-certificate-date-and-negotiated-version-review-candidates-done) | done | pending | pending | 784 | Owning parent/phase gates unchanged |
| [P12-02an](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02an--current-private-original-tls-candidate-source-done) | done | pending | pending | 785 | Owning parent/phase gates unchanged |
| [P12-02ao](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ao--exact-private-tls-candidate-get-consumer-done) | done | pending | pending | 786 | Owning parent/phase gates unchanged |
| [P12-02ap](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ap--deliberate-native-original-tls-candidate-inspection-done) | done | pending | pending | — | Owning parent/phase gates unchanged |
| [P12-02aq](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02aq--compact-original-tls-finding-recipes-done) | done | pending | pending | 787 | Owning parent/phase gates unchanged |
| [P12-02ar](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ar--genuine-private-tls-finding-relation-and-lifecycle-done) | done | pending | pending | 788 | Owning parent/phase gates unchanged |
| [P12-02as](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02as--exact-private-tls-finding-getpost-commands-done) | done | pending | pending | 789 | Owning parent/phase gates unchanged |
| [P12-02at](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02at--deliberate-native-tls-finding-commands-and-uncertainty-done) | done | pending | pending | 790 | Owning parent/phase gates unchanged |
| [P12-02au](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02au--pure-original-http-scheme-location-review-candidate-done) | done | pending | pending | 791 | Owning parent/phase gates unchanged |
| [P12-02av](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02av--current-private-original-location-candidate-source-done) | done | pending | pending | 792 | Owning parent/phase gates unchanged |
| [P12-02aw](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02aw--exact-private-original-location-candidate-get-consumer-done) | done | pending | pending | 793 | Owning parent/phase gates unchanged |
| [P12-02ax](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ax--deliberate-native-original-location-candidate-inspection-done) | done | pending | pending | 794 | Owning parent/phase gates unchanged |
| [P12-02ay](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ay--compact-original-location-finding-recipes-done) | done | pending | pending | 795 | Owning parent/phase gates unchanged |
| [P12-02az](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02az--genuine-private-original-location-finding-relationlifecycle-done) | done | pending | pending | 796 | Owning parent/phase gates unchanged |
| [P12-02ba](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ba--exact-private-original-location-finding-commands-done) | done | pending | pending | 797 | Owning parent/phase gates unchanged |
| [P12-02bb](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bb--deliberate-native-original-location-finding-commands-done) | done | pending | pending | 798 | Owning parent/phase gates unchanged |
| [P12-02bc](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bc--exact-private-passive-finding-human-review-source-done) | done | pending | pending | 799 | Owning parent/phase gates unchanged |
| [P12-02bd](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bd--private-source-bound-human-passive-prioritization-backend-done) | done | pending | pending | 800 | Owning parent/phase gates unchanged |
| [P12-02be](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02be--exact-private-human-passive-priority-commands-done) | done | pending | pending | 801 | Owning parent/phase gates unchanged |
| [P12-02bf](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bf--deliberate-native-private-passive-human-prioritization-done) | done | pending | pending | 802 | Owning parent/phase gates unchanged |
| [P12-02bg](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bg--pure-original-http-response-location-metadata-done) | done | pending | pending | 772 | Owning parent/phase gates unchanged |
| [P12-02bh](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bh--independent-current-exact-verified-http-location-source-done) | done | pending | pending | 768 | Owning parent/phase gates unchanged |
| [P12-02bi](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bi--protected-original-first-response-http-location-transport-done) | done | pending | pending | 769 | Owning parent/phase gates unchanged |
| [P12-02bj](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bj--strict-original-minimized-private-http-location-evidence-done) | done | pending | pending | 770 | Owning parent/phase gates unchanged |
| [P12-02bk](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bk--restore-final-private-passive-byte-and-commercial-fences-done) | done | pending | pending | 766 | Owning parent/phase gates unchanged |
| [P12-02bl](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bl--pin-exact-intended-passive-attempt-and-final-metadata-done) | done | pending | pending | 756 | Owning parent/phase gates unchanged |
| [P12-02bm](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bm--once-only-independently-permitted-private-http-location-collector-done) | done | pending | pending | 757 | Owning parent/phase gates unchanged |
| [P12-02bn](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bn--complete-deliberate-private-http-location-consumers-done) | done | pending | pending | 758, 763, 764 | Owning parent/phase gates unchanged |
| [P12-02bo](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bo--independent-original-http-and-https-response-pair-done) | done | pending | pending | 759 | Owning parent/phase gates unchanged |
| [P12-02bp](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bp--deliberate-private-original-httphttps-pair-delivery-done) | done | pending | pending | 760, 762 | Owning parent/phase gates unchanged |
| [P12-02bq](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bq--scope-original-passive-review-metadata-before-pinning-done) | done | pending | pending | 761 | Owning parent/phase gates unchanged |
| [P12-02br](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02br--current-exact-permitted-redirect-chain-source-done) | done | pending | pending | 833 | Owning parent/phase gates unchanged |
| [P12-02bs](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bs--pure-fresh-exact-target-location-resolution-done) | done | pending | pending | 832 | Owning parent/phase gates unchanged |
| [P12-02bt](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bt--protected-explicit-header-only-exact-target-chain-transport-done) | done | pending | pending | 831 | Owning parent/phase gates unchanged |
| [P12-02bu](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bu--strict-original-minimized-multi-hop-evidence-done) | done | pending | pending | 830 | Owning parent/phase gates unchanged |
| [P12-02bv](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bv--once-only-exact-redirect-chain-collector-and-private-lifecycle-done) | done | pending | pending | 850 | Owning parent/phase gates unchanged |
| [P12-02bw](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bw--complete-exact-chain-private-api-and-deliberate-native-consumers-done) | done | pending | pending | 851 | Owning parent/phase gates unchanged |
| [P12-02bx](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bx--pure-original-selected-chain-review-candidates-done) | done | pending | pending | 754 | Owning parent/phase gates unchanged |
| [P12-02by](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02by--current-private-original-chain-candidate-source-done) | done | pending | pending | 752 | Owning parent/phase gates unchanged |
| [P12-02bz](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bz--fixed-private-original-chain-candidate-get-done) | done | pending | pending | 748 | Owning parent/phase gates unchanged |
| [P12-02ca](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ca--deliberate-original-chain-candidate-native-inspector-done) | done | pending | pending | 749 | Owning parent/phase gates unchanged |
| [P12-02cb](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02cb--compact-original-selected-chain-finding-recipes-done) | done | pending | pending | 750 | Owning parent/phase gates unchanged |
| [P12-02cc](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02cc--genuine-original-chain-finding-persistence-and-current-source-done) | done | pending | pending | 744 | Owning parent/phase gates unchanged |
| [P12-02cd](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02cd--fixed-private-original-chain-finding-api-done) | done | pending | pending | 745 | Owning parent/phase gates unchanged |
| [P12-02ce](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ce--deliberate-original-chain-finding-native-consumer-done) | done | pending | pending | 746 | Owning parent/phase gates unchanged |
| [P12-02cf](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02cf--shared-passive-review-source-final-authority-recovery-done) | done | pending | pending | 742 | Owning parent/phase gates unchanged |
| [P12-02cg](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02cg--current-genuine-chain-finding-review-source-done) | done | pending | pending | 740 | Owning parent/phase gates unchanged |
| [P12-02ch](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ch--passive-human-decision-final-row-authority-recovery-done) | done | pending | pending | 738 | Owning parent/phase gates unchanged |
| [P12-02ci](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ci--explicit-original-chain-immutable-human-decisions-done) | done | pending | pending | 734, 736 | Owning parent/phase gates unchanged |
| [P12-02cj](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02cj--fixed-private-original-chain-human-priority-api-done) | done | pending | pending | 734, 735 | Owning parent/phase gates unchanged |
| [P12-02ck](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ck--deliberate-native-chain-human-judgment-delivery-done) | done | pending | pending | 734 | Owning parent/phase gates unchanged |
| [P12-02cl](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02cl--primitive-passive-current-owneradmin-role-in_progress) | in_progress | pending | pending | 235 | Owning parent/phase gates unchanged |
| [P12-02cm](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02cm--scalar-passive-saved-metadata-and-ownership-acknowledgment-in_progress) | in_progress | pending | pending | 235 | Owning parent/phase gates unchanged |
| [P13-01](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p13-01--environment-topology-secrets-and-aws-identities-done) | done | pending | pending | 245, 876, 877 | Live deployment |
| [P13-02](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p13-02--static-frontend-deployment-and-real-cdn-routing-blocked) | blocked | pending | pending | 178, 179, 180, 181, 182, 859, 860, 861, 862, 863, 864, 865, 866 | Live deployment; Bilingual review |
| [P13-03](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p13-03--backend-image-release-migrations-and-health-rollback-done) | done | pending | pending | 245, 872, 873, 874, 875 | Live deployment |
| [P13-04](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p13-04--backup-restoration-retention-and-operational-alarms-done) | done | pending | pending | 176, 878, 879 | Live deletion; Live restore/alarms |
| [P13-05](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p13-05--product-sites-own-seo-funnel-and-launch-monitoring-pending) | pending | pending | pending | 867, 868, 869 | Live product-site evidence |
| [P13-05a](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p13-05a--secret-free-site-monitoring-template-and-offline-coverage-report-done) | done | pending | pending | 699, 870, 871 | Owning parent/phase gates unchanged |
| [P14-01](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p14-01--requested-cms-connection-and-approval-controlled-publication-pending) | pending | blocked | blocked | 883, 884, 885, 888 | Requested CMS |
| [P14-02](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p14-02--official-social-scheduling-and-first-party-analytics-pending) | pending | blocked | blocked | 886, 887, 888 | Supported social platform |
| [P15-01](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p15-01--refine-allowances-cost-and-retention-from-actual-use-pending) | pending | blocked | blocked | 892 | Actual usage evidence |
| [P15-02](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p15-02--managed-data-services-and-independent-workerapi-scaling-pending) | pending | blocked | blocked | 893, 894, 895, 896 | Demonstrated scale constraint |
| [P16-01](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p16-01--explicit-repository-connection-and-isolated-analysis-pending) | in_progress | partial; consent/dependency modes/selected Python syntax observations implemented, coding agent pending | deferred by D437 | 848, 900, 901, 902, 905 | Real repository grant |
| [P16-02](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p16-02--proposed-patches-repository-checks-and-human-reviewed-prs-pending) | pending | pending | pending | 903, 904 | Real repository grant; Human patch review |
| [TOOL-01](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#tool-01--ground-implementation-guidance-in-real-source-patterns-done) | done | pending | pending | 36, 37, 38, 39, 40, 41, 42, 43, 44, 870, 909, 910, 911, 927, 928, 929, 930, 935, 936, 937, 946, 947, 948, 949, 950 | Owning parent/phase gates unchanged |
| [TOOL-02](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#tool-02--register-universal-roles-and-upgrade-sol-subagents-done) | done | pending | pending | 912, 913, 914, 915, 916, 917, 918, 919, 920, 921, 922, 923, 924, 925, 926, 931, 932, 933, 934 | Owning parent/phase gates unchanged |
| [TOOL-03](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#tool-03--local-unattended-fresh-session-continuation-done) | done | pending | pending | 938, 939, 940, 941, 942, 943, 944, 945 | Installed launcher acceptance |

### Preserved TODO Ownership

The source column links each byte-preserved phase and names its exact line; the short label is for navigation, with the full original requirement authoritative. All693 requirements are retained, including superseded history mapped to its current owner. D048 replaces Phase0's historical stop-before-code stage; D095–D099 select no-card trials (TODO232's otherwise branch); TOOL routing supersessions map to current TOOL-02/D430, never to obsolete adapter settings. Historical percentages/checkmarks are untouched. No duplicate owner reference creates an extra requirement.

| TODO source line and requirement | Owning existing cards | Local implementation | Automated acceptance | Separate gate/condition |
| --- | --- | --- | --- | --- |
| [L36](../TODO_ARCHIVE_2026-10-10.md#phase-0-documentation-checkpoint) Select the working name OrganicSEOOps. | TOOL-01 | pending | pending | Owning parent/phase gates unchanged |
| [L37](../TODO_ARCHIVE_2026-10-10.md#phase-0-documentation-checkpoint) Record the complete product and technical plan. | TOOL-01 | pending | pending | Owning parent/phase gates unchanged |
| [L38](../TODO_ARCHIVE_2026-10-10.md#phase-0-documentation-checkpoint) Record accepted decisions and rationale. | TOOL-01 | pending | pending | Owning parent/phase gates unchanged |
| [L39](../TODO_ARCHIVE_2026-10-10.md#phase-0-documentation-checkpoint) Establish persistent project and agent guidance. | TOOL-01 | pending | pending | Owning parent/phase gates unchanged |
| [L40](../TODO_ARCHIVE_2026-10-10.md#phase-0-documentation-checkpoint) Confirm that frontend deployment uses GitHub Actions, S3, and CloudFront. | TOOL-01 | pending | pending | Owning parent/phase gates unchanged |
| [L41](../TODO_ARCHIVE_2026-10-10.md#phase-0-documentation-checkpoint) Confirm separate containers for API, workers, Beat, PostgreSQL, Redis, and proxy. | TOOL-01 | pending | pending | Owning parent/phase gates unchanged |
| [L42](../TODO_ARCHIVE_2026-10-10.md#phase-0-documentation-checkpoint) Select Angular 22 and Django 6.1 as the framework release lines (D041). | TOOL-01 | pending | pending | Owning parent/phase gates unchanged |
| [L43](../TODO_ARCHIVE_2026-10-10.md#phase-0-documentation-checkpoint) Prepare dependency-aware implementation task cards, source coverage, verification instructions, and provider-n… | TOOL-01 | pending | pending | Owning parent/phase gates unchanged |
| [L44](../TODO_ARCHIVE_2026-10-10.md#phase-0-documentation-checkpoint) Stop before creating application or runtime code. | TOOL-01 | pending | pending | Owning parent/phase gates unchanged |
| [L48](../TODO_ARCHIVE_2026-10-10.md#phase-1-repository-and-runtime-scaffold) Initialize the Git repository when explicitly requested. | P01-01 | excluded | excluded | Git authorization |
| [L50](../TODO_ARCHIVE_2026-10-10.md#phase-1-repository-and-runtime-scaffold) Confirm the latest stable compatible releases within Angular 22 and Django 6.1, plus compatible Angular CLI, N… | P01-01 | verified | verified | Git authorization |
| [L51](../TODO_ARCHIVE_2026-10-10.md#phase-1-repository-and-runtime-scaffold) Record exact selected version pins in docs/DECISIONS.md (D049). | P01-01 | verified | verified | Git authorization |
| [L52](../TODO_ARCHIVE_2026-10-10.md#phase-1-repository-and-runtime-scaffold) Restore official pinned Redis8.10.2 security-patch image and rerun local broker and unchanged vulnerability ch… | P01-04 | verified | verified | Live deployment |
| [L53](../TODO_ARCHIVE_2026-10-10.md#phase-1-repository-and-runtime-scaffold) Create frontend/ with Angular 22 and a matching Angular CLI. | P01-02 | verified | verified | Owning parent/phase gates unchanged |
| [L54](../TODO_ARCHIVE_2026-10-10.md#phase-1-repository-and-runtime-scaffold) Configure fully static frontend output with explicit prerendered-public and CSR account/app route inventory, n… | P01-02 | verified | verified | Owning parent/phase gates unchanged |
| [L55](../TODO_ARCHIVE_2026-10-10.md#phase-1-repository-and-runtime-scaffold) Isolate custom HTML/native-CSS public components from lazy-loaded account/app code; no authenticated UI librar… | P01-02 | verified | verified | Owning parent/phase gates unchanged |
| [L56](../TODO_ARCHIVE_2026-10-10.md#phase-1-repository-and-runtime-scaffold) Create backend/ with Django 6.1 and compatible DRF. | P01-03 | verified | verified | Owning parent/phase gates unchanged |
| [L57](../TODO_ARCHIVE_2026-10-10.md#phase-1-repository-and-runtime-scaffold) Create the custom email-based Django user model before the first application migration. | P01-03 | verified | verified | Owning parent/phase gates unchanged |
| [L58](../TODO_ARCHIVE_2026-10-10.md#phase-1-repository-and-runtime-scaffold) Create .env.example without secrets. | P01-04 | verified | verified | Live deployment |
| [L59](../TODO_ARCHIVE_2026-10-10.md#phase-1-repository-and-runtime-scaffold) Move backend local/production/check env flows under backend/, add Angular local/production environment repla… | P01-04 | verified | verified | Live deployment |
| [L60](../TODO_ARCHIVE_2026-10-10.md#phase-1-repository-and-runtime-scaffold) Allow direct host Django to auto-load backend/.env and reach the isolated dev database/broker via loopback p… | P01-04 | verified | verified | Live deployment |
| [L61](../TODO_ARCHIVE_2026-10-10.md#phase-1-repository-and-runtime-scaffold) Create a backend Docker image reusable by API, worker, and Beat containers (build and nonroot/read-only runtim… | P01-04 | verified | verified | Live deployment |
| [L62](../TODO_ARCHIVE_2026-10-10.md#phase-1-repository-and-runtime-scaffold) Create separate Compose services for proxy, API, worker-default, worker-ai, worker-crawl, worker-audit, Beat, … | P01-04 | verified | verified | Live deployment |
| [L63](../TODO_ARCHIVE_2026-10-10.md#phase-1-repository-and-runtime-scaffold) Add private service networking and persistent development volumes (private ports/networks and PostgreSQL/Redis… | P01-04 | verified | verified | Live deployment |
| [L64](../TODO_ARCHIVE_2026-10-10.md#phase-1-repository-and-runtime-scaffold) Add API, PostgreSQL, and Redis health checks (all eight configured container health checks passed; Beat runnin… | P01-04 | verified | verified | Live deployment |
| [L65](../TODO_ARCHIVE_2026-10-10.md#phase-1-repository-and-runtime-scaffold) Add minimal backend and frontend verification commands (local evidence D050/D051; exact-target CI remains pend… | P01-05 | verified | verified | Hosted CI |
| [L66](../TODO_ARCHIVE_2026-10-10.md#phase-1-repository-and-runtime-scaffold) Add basic CI checks without production deployment (workflow-equivalent local checks and unchanged security gat… | P01-05 | verified | verified | Hosted CI |
| [L67](../TODO_ARCHIVE_2026-10-10.md#phase-1-repository-and-runtime-scaffold) Add an isolated source-mounted backend development workflow and Angular API proxy that reuse dedicated images/… | P01-04 | verified | verified | Live deployment |
| [L68](../TODO_ARCHIVE_2026-10-10.md#phase-1-repository-and-runtime-scaffold) Define public/account/onboarding/dashboard/billing wireframes and reusable typography, spacing, colors, forms,… | P3A-09 | pending | pending | Bilingual review; Live product-site evidence |
| [L69](../TODO_ARCHIVE_2026-10-10.md#phase-1-repository-and-runtime-scaffold) Define WCAG 2.2 AA acceptance and keyboard/screen-reader/narrow-screen checks for core customer journeys (D058… | P01-07 | verified | verified | Manual accessibility |
| [L73](../TODO_ARCHIVE_2026-10-10.md#phase-2-authentication-and-tenancy) Implement email registration (P02-01/D059; production delivery remains P3A-10). | P02-01, P3A-10 | in_progress | in_progress | P02-01 local registration verified; P3A-10 delivery parent pending; sender/domain/copy |
| [L74](../TODO_ARCHIVE_2026-10-10.md#phase-2-authentication-and-tenancy) Implement email verification. | P02-01 | verified | verified | Owning parent/phase gates unchanged |
| [L75](../TODO_ARCHIVE_2026-10-10.md#phase-2-authentication-and-tenancy) Add throttled verification resend and expired/used/invalid/already-verified states without duplicating organiz… | P02-01 | verified | verified | Owning parent/phase gates unchanged |
| [L76](../TODO_ARCHIVE_2026-10-10.md#phase-2-authentication-and-tenancy) Implement secure cookie login and logout. | P02-01 | verified | verified | Owning parent/phase gates unchanged |
| [L77](../TODO_ARCHIVE_2026-10-10.md#phase-2-authentication-and-tenancy) Implement CSRF handling for the Angular SPA. | P02-01 | verified | verified | Owning parent/phase gates unchanged |
| [L78](../TODO_ARCHIVE_2026-10-10.md#phase-2-authentication-and-tenancy) Implement password reset and password change (P02-02/D061). | P02-02 | verified | verified | Owning parent/phase gates unchanged |
| [L79](../TODO_ARCHIVE_2026-10-10.md#phase-2-authentication-and-tenancy) Use non-enumerating recovery responses and expiring single-use reset tokens; revoke sessions after reset and n… | P3A-10 | in_progress | in_progress | Sender/domain/copy |
| [L80](../TODO_ARCHIVE_2026-10-10.md#phase-2-authentication-and-tenancy) Add trusted-origin reset links, token-redacted logs, verified email changes, session listing/revocation, and l… | P02-02 | verified | verified | Owning parent/phase gates unchanged |
| [L81](../TODO_ARCHIVE_2026-10-10.md#phase-2-authentication-and-tenancy) Add login and current account-sensitive-action throttling (extend with later sensitive actions on their owning… | P02-02 | verified | verified | Owning parent/phase gates unchanged |
| [L82](../TODO_ARCHIVE_2026-10-10.md#phase-2-authentication-and-tenancy) Implement organizations (P02-03/D064). | P02-03 | verified | verified | Owning parent/phase gates unchanged |
| [L83](../TODO_ARCHIVE_2026-10-10.md#phase-2-authentication-and-tenancy) Implement owner, admin, member, and viewer membership records, fail-closed reads and non-owner role mutation (… | P02-03, P02-04 | verified | verified | P02-03 reads/records and P02-04 role mutations verified |
| [L84](../TODO_ARCHIVE_2026-10-10.md#phase-2-authentication-and-tenancy) Implement invitations and acceptance (P02-04/D065). | P02-04 | verified | verified | Owning parent/phase gates unchanged |
| [L85](../TODO_ARCHIVE_2026-10-10.md#phase-2-authentication-and-tenancy) Handle invitation expiry/revocation/replay/wrong-account acceptance with verified identity and inviter privile… | P02-04 | verified | verified | Owning parent/phase gates unchanged |
| [L86](../TODO_ARCHIVE_2026-10-10.md#phase-2-authentication-and-tenancy) Implement projects with one canonical primary domain (P02-03/D064). | P02-03 | verified | verified | Owning parent/phase gates unchanged |
| [L87](../TODO_ARCHIVE_2026-10-10.md#phase-2-authentication-and-tenancy) Implement optional aliases and restricted project membership (P02-03/D064). | P02-03 | verified | verified | Owning parent/phase gates unchanged |
| [L88](../TODO_ARCHIVE_2026-10-10.md#phase-2-authentication-and-tenancy) Create organization and project selectors in Angular with visible active context and stale-response isolation … | P02-03 | verified | verified | Owning parent/phase gates unchanged |
| [L89](../TODO_ARCHIVE_2026-10-10.md#phase-2-authentication-and-tenancy) Enforce tenant-scoped querysets and object permissions for current organization/project APIs and artifact wrap… | P02-03 | verified | verified | Owning parent/phase gates unchanged |
| [L90](../TODO_ARCHIVE_2026-10-10.md#phase-2-authentication-and-tenancy) Encode the Section 6.3 role/action matrix for jobs, approvals, integrations, team access, billing, exports/sha… | P02-04 | verified | verified | Owning parent/phase gates unchanged |
| [L91](../TODO_ARCHIVE_2026-10-10.md#phase-2-authentication-and-tenancy) Protect the last active owner under concurrent changes and implement accepted ownership transfer with re-authe… | P02-05 | verified | verified | Owning parent/phase gates unchanged |
| [L92](../TODO_ARCHIVE_2026-10-10.md#phase-2-authentication-and-tenancy) Distinguish account/organization suspension from closure/expiry; block operations in existing sessions, revoke… | P02-05 | verified | verified | Owning parent/phase gates unchanged |
| [L93](../TODO_ARCHIVE_2026-10-10.md#phase-2-authentication-and-tenancy) Implement separate user closure and complete organization closure/export workflows, including billing cancella… | P02-06 | pending | pending | Legal identity/export; Live deletion |
| [L94](../TODO_ARCHIVE_2026-10-10.md#phase-2-authentication-and-tenancy) Add P02-03 cross-organization, cross-project, nested-ID, artifact and restricted-access tests; extend them wit… | P02-03 | verified | verified | Owning parent/phase gates unchanged |
| [L95](../TODO_ARCHIVE_2026-10-10.md#phase-2-authentication-and-tenancy) Check permission revocation during future jobs/export/delivery; ownership races and immediate account/organiza… | P02-05, P02-04 | in_progress | in_progress | Current P02-04/05 foundation verified; future jobs/export/delivery require owning-card reconciliation |
| [L96](../TODO_ARCHIVE_2026-10-10.md#phase-2-authentication-and-tenancy) Record invitation, membership-role/removal and restricted-project-access audit events (P02-04/D065). | P02-04 | verified | verified | Owning parent/phase gates unchanged |
| [L97](../TODO_ARCHIVE_2026-10-10.md#phase-2-authentication-and-tenancy) Add scoped ownership-transfer/leave and staff suspension audit events (P02-05/D066). | P02-05 | verified | verified | Owning parent/phase gates unchanged |
| [L98](../TODO_ARCHIVE_2026-10-10.md#phase-2-authentication-and-tenancy) Extend audit events to remaining sensitive authentication, closure and later billing/job actions on their owni… | P02-02, P02-06, P3A-07, P04-02 | in_progress | in_progress | Sensitive-auth and scoped admission/cancel/retry audits verified; closure/billing owners pending |
| [L102](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Configure Django Admin for user inspection and account status; use audited, permission-scoped suspension APIs … | P03-01, P02-05 | verified | verified | Owning parent/phase gates unchanged |
| [L103](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Configure inspect-only organization, membership, invitation, project, domain, transfer and audit administratio… | P03-01 | verified | verified | Owning parent/phase gates unchanged |
| [L104](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Encrypt current staff MFA seeds with rotatable production keys and exclude secret fields from Admin/log/audit … | P03-02 | verified | verified | Owning parent/phase gates unchanged |
| [L105](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Add filtering and search for current user, organization, invitation, project and audit records (P03-01/D067); … | P03-01 | verified | verified | Owning parent/phase gates unchanged |
| [L106](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Add job, usage and integration administration as those models become available (current audit-event inspection… | P03-01 | in_progress | in_progress | Foundation Admin verified; feature-owned jobs/usage/integration Admin current acceptance remains pending |
| [L107](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Keep current customer team, project and ownership administration in Angular; customers cannot enter Django Adm… | P02-04, P02-05, P03-01 | verified | verified | Owning parent/phase gates unchanged |
| [L108](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Add required platform-superadmin TOTP/recovery, current-session assurance and controlled lost-factor reset wit… | P03-02 | verified | verified | Owning parent/phase gates unchanged |
| [L109](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Extend current company/team/access/ownership screens with integration recovery, audit history, approval/assign… | P02-04, P02-05 | pending | pending | Owning parent/phase gates unchanged |
| [L110](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Add permission-scoped audited user/organization suspension/reactivation with reasons and before/after records … | P02-05 | verified | verified | P02-05 current ownership3 + unchanged R06 staff permission/reason/rollback/before-after auditing evidence; actual support/hosted gate separate |
| [L111](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Add trial-extension/entitlement correction, billing-reconciliation, job/email failure and provider-cost invest… | P03-03 | pending | pending | Live support operation |
| [L112](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Implement/check D209/P03-03a minimized exact-scoped job/step investigation source with separate current staff … | P03-03a | verified | verified | Current scoped source/native privacy/render-loss owning evidence verified; full operational parent pending |
| [L113](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Implement/check D209/P03-03b exact-scoped private reasoned JobRun Admin/deny generic JobStep discovery: focuse… | P03-03b | verified | verified | Current scoped source/native privacy/render-loss owning evidence verified; full operational parent pending |
| [L114](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Implement/check D210/P03-03c separate exact-scoped internal-unit reservation source/permission/session-MFA/pay… | P03-03c | verified | verified | Current separate scoped scalar/source/rendered semantic privacy acceptance verified; full operational parent pending |
| [L115](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Implement/check D210/P03-03d explicit separate usage action in the existing scoped job Admin form/independent … | P03-03d | verified | verified | Current separate scoped scalar/source/rendered semantic privacy acceptance verified; full operational parent pending |
| [L117](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Implement/check D211/P03-03e separate original AI usage/cost observation source: owning6/job-usage17 PostgreSQ… | P03-03e | verified | verified | Current separate scoped scalar/source/rendered semantic privacy acceptance verified; full operational parent pending |
| [L118](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Implement/check D211/P03-03f third independent scoped Admin action/generic AI denial: owning-consumer18 Postgr… | P03-03f | verified | verified | Current separate original AI observation/source/rendered semantic privacy acceptance verified; full operational parent pending |
| [L120](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Implement/check D212/P03-03g exact organization notice transport source: owning5/notice-feedback20 PostgreSQL2… | P03-03g | verified | verified | Current exact organization notice scalar/private consumer source-bound acceptance verified; no mail or retry authority |
| [L121](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Implement/check D212/P03-03h complete exact notice Admin/private POST/native and legacy global GET410: focused… | P03-03h | verified | verified | Current exact organization notice scalar/private consumer source-bound acceptance verified; no mail or retry authority |
| [L123](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Implement/check D213/P03-03i exact current account-mail source: owning6/final affected39 PostgreSQL98.839s/sys… | P03-03i | verified | verified | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03i-and-j-current-exact-account-mail-reconciliation) |
| [L124](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Implement/check D213/P03-03j complete exact private Admin/API/native account-mail consumers/global GET410: ini… | P03-03j | verified | verified | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03i-and-j-current-exact-account-mail-reconciliation) |
| [L126](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Restore D214/P03-03k existing suppression clearance: genuine red1→owning-feedback11/final affected61 PostgreSQ… | P03-03k | verified | verified | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03k-through-m-current-suppression-and-feedback-reconciliation) |
| [L128](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Implement/check D215/P03-03l exact retained GLOBAL suppression/first feedback source: owning17/final affected7… | P03-03l | verified | verified | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03k-through-m-current-suppression-and-feedback-reconciliation) |
| [L129](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Complete D215/P03-03m exact suppression-feedback consumers: focused21/final affected72 PostgreSQL191.701s/full… | P03-03m | verified | verified | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03k-through-m-current-suppression-and-feedback-reconciliation) |
| [L131](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Restore D216/P03-03n existing trial approval/extension request-bound current change-only/session-MFA and post-… | P03-03n | verified | verified | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03n-through-q-current-trial-correction-billing-retry-and-receipt-reconciliation) |
| [L133](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Restore D217/P03-03o existing signed billing receipt retry request-bound/change-only/MFA/full original pending… | P03-03o | verified | verified | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03n-through-q-current-trial-correction-billing-retry-and-receipt-reconciliation) |
| [L135](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Implement/check D218/P03-03p exact retained GLOBAL signed receipt source: owning7/final affected91 PostgreSQL1… | P03-03p | verified | verified | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03n-through-q-current-trial-correction-billing-retry-and-receipt-reconciliation) |
| [L136](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Complete D218/P03-03q exact private reasoned Admin/API/native/generic receipt discovery denial: focused19/fina… | P03-03q | verified | verified | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03n-through-q-current-trial-correction-billing-retry-and-receipt-reconciliation) |
| [L138](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Implement/check D219/P03-03r exact private confirmed Django Admin approval/extension consumer: owning6/final a… | P03-03r | verified | verified | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03r-through-t-current-exact-trial-admin-reconciliation) |
| [L140](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Implement/check D220/P03-03s exact retained organization/trial observation source: final owning6 PostgreSQL10.… | P03-03s | verified | verified | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03r-through-t-current-exact-trial-admin-reconciliation) |
| [L141](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Complete D220/P03-03t exact private reasoned trial Admin: focused17/final owning6/final affected90 PostgreSQL1… | P03-03t | verified | verified | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03r-through-t-current-exact-trial-admin-reconciliation) |
| [L143](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Implement/check D221/P03-03u exact retained linked-subscription source: owning7+affected101 PostgreSQL180.797s… | P03-03u | verified | verified | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03u-through-z-current-subscription-archive-and-cancellation-reconciliation) |
| [L144](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Complete D221/P03-03v exact private reasoned subscription Admin: focused11/final affected105 PostgreSQL294.079… | P03-03v | verified | verified | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03u-through-z-current-subscription-archive-and-cancellation-reconciliation) |
| [L146](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Implement/check D222/P03-03w exact retained archived-subscription source: owning5/final affected94 PostgreSQL1… | P03-03w | verified | verified | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03u-through-z-current-subscription-archive-and-cancellation-reconciliation) |
| [L147](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Complete D222/P03-03x separate exact private reasoned archived-subscription Admin: focused9/affected47 Postgre… | P03-03x | verified | verified | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03u-through-z-current-subscription-archive-and-cancellation-reconciliation) |
| [L149](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Implement/check D223/P03-03y exact retained closure-cancellation source: owning4/final affected53 PostgreSQL97… | P03-03y | verified | verified | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03u-through-z-current-subscription-archive-and-cancellation-reconciliation) |
| [L150](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Complete D223/P03-03z exact private reasoned cancellation Admin: focused8/final affected66 PostgreSQL135.921s/… | P03-03z | verified | verified | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03u-through-z-current-subscription-archive-and-cancellation-reconciliation) |
| [L152](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Implement/check D224/P03-03aa exact retained checkout source: owning5/final5 PostgreSQL10.242s/affected98 Post… | P03-03aa | verified | verified | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03aa-through-ai-current-checkout-retry-link-and-first-active-reconciliation) |
| [L153](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Complete D224/P03-03ab exact private checkout Admin: focused9 PostgreSQL26.733s/affected97 PostgreSQL230.270s/… | P03-03ab | verified | verified | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03aa-through-ai-current-checkout-retry-link-and-first-active-reconciliation) |
| [L155](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Complete D225/P03-03ac exact confirmed change-only signed-receipt retry Admin: focused17 PostgreSQL30.881s/96 … | P03-03ac | verified | verified | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03aa-through-ai-current-checkout-retry-link-and-first-active-reconciliation) |
| [L157](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Restore D226/P03-03ad original checkout-link capture post-audit and post-serialization current-source/proof/fu… | P03-03ad | verified | verified | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03aa-through-ai-current-checkout-retry-link-and-first-active-reconciliation) |
| [L159](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Implement/check D227/P03-03ae exact retained checkout-link acknowledgment source: owning4 PostgreSQL7.295s/aff… | P03-03ae | verified | verified | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03aa-through-ai-current-checkout-retry-link-and-first-active-reconciliation) |
| [L160](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Complete D227/P03-03af exact private reasoned checkout-link Admin: focused8 PostgreSQL22.460s/affected77 Postg… | P03-03af | verified | verified | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03aa-through-ai-current-checkout-retry-link-and-first-active-reconciliation) |
| [L162](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Restore D228/P03-03ag shared first-active historical reader final integrity: red1→owning5 PostgreSQL8.415s/129… | P03-03ag | verified | verified | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03aa-through-ai-current-checkout-retry-link-and-first-active-reconciliation) |
| [L164](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Implement/check D229/P03-03ah exact retained first-active staff source: owning5 PostgreSQL13.050s/affected94 P… | P03-03ah | verified | verified | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03aa-through-ai-current-checkout-retry-link-and-first-active-reconciliation) |
| [L165](../TODO_ARCHIVE_2026-10-10.md#phase-3-platform-superadmin) Complete D229/P03-03ai exact private first-active Admin: focused9 PostgreSQL30.467s/affected85 PostgreSQL217.5… | P03-03ai | verified | verified | Separate manual/external parent gates unchanged; [current source/check evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p03-03aa-through-ai-current-checkout-retry-link-and-first-active-reconciliation) |
| [L169](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Complete P3A-01 launch positioning: D088 selects airport-transfer businesses serving Antalya/Istanbul, D089 se… | P3A-01, P06-07 | pending | pending | Domain/content research; Manual accessibility; Real source grants |
| [L170](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Complete and approve the working public page map: routes/locales, qualitative intent hypotheses, metadata, CTA… | P3A-01 | pending | pending | Domain/content research |
| [L171](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Complete P3A-02 localization: D092 selects English/Turkish product coverage, D093 selects unprefixed English/… | P3A-02 | pending | pending | Bilingual review |
| [L172](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Persist a private per-user en/tr **future** product-language preference with English fallback and a truthf… | P3A-02 | verified | verified | Saved private preference/English production fallback and truthful local-draft status verified by current API/native/source review; bilingual launch approval separate; [current evidence](IMPLEMENTATION_HISTORY_2026-10-11.md#p3a-02-unpublished-locale-routing-and-recipient-email-drafts) |
| [L173](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Implement draft-safe public routes and language preference locally without requiring domain acquisition or fin… | P3A-02, P3A-09 | pending | pending | Bilingual review; Bilingual review; Live product-site evidence |
| [L174](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Prepare a clearly labeled realistic sample report; publish case studies only when measured baseline/change/out… | P3A-03 | verified | verified | Approved proof/publication  [Current local evidence](IMPLEMENTATION_HISTORY_2026-10-15.md#p3a-03-current-local-verification) |
| [L175](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Complete D109 repository-authored public content publication: founder editor/publisher and bilingual human rev… | P3A-03 | verified | verified | Approved proof/publication  [Current local evidence](IMPLEMENTATION_HISTORY_2026-10-15.md#p3a-03-current-local-verification) |
| [L176](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Complete D095-D098 commercial readiness: the 30-day no-card trial, one USD 149 Agency offer, bounded allowance… | P3A-12, P13-04 | pending | pending | Provider terms/cost/access; Live deletion; Live restore/alarms |
| [L177](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Record working payout/customer-market, failed-payment, refund/chargeback and retained-access/export/deletion/b… | P3A-04 | pending | pending | Commercial/legal readiness |
| [L178](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Build public homepage, accurate feature/use-case pages, pricing/terms, labeled demo/sample report, help/FAQ/co… | P3A-09, P13-02 | pending | pending | Bilingual review; Live product-site evidence; Live deployment; Bilingual review |
| [L179](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Design elegant responsive public pages with semantic HTML/native CSS and accessible lightweight interactions; … | P3A-09, P13-02 | pending | pending | Bilingual review; Live product-site evidence; Live deployment; Bilingual review |
| [L180](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Make intended public pages indexable/performance-conscious with metadata/canonicals/sitemaps; keep private/acc… | P3A-09, P13-02 | pending | pending | Bilingual review; Live product-site evidence; Live deployment; Bilingual review |
| [L181](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Ensure generated public HTML contains primary content, crawlable links, metadata, and applicable truthful sche… | P3A-09, P13-02 | pending | pending | Bilingual review; Live product-site evidence; Live deployment; Bilingual review |
| [L182](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Complete public/app delivery details: D091 selects one static frontend at organicseoops.com for public/accou… | P3A-09, P13-02 | pending | pending | Bilingual review; Live product-site evidence; Live deployment; Bilingual review |
| [L183](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Complete acquisition measurement: D102/D110 and plan §29.2 define authoritative milestone grains/first-occurre… | P3A-11a, P3A-11c | pending | pending | Owning parent/phase gates unchanged |
| [L184](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Locally implement prospective owner/browser exact checkout-link acknowledgment and retained checkout-attempt a… | P3A-11d | pending | pending | Owning parent/phase gates unchanged |
| [L185](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Locally implement prospectively tracked first active paid server observation and retained organization aggrega… | P3A-11e | pending | pending | Owning parent/phase gates unchanged |
| [L186](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Locally implement prospective bounded first-audit operational completion history (P3A-11g/D144): birth-only/no… | P3A-11g | pending | pending | Owning parent/phase gates unchanged |
| [L187](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Check D145/P3A-11h actual current marked bounded crawl→same-run UTF-8 raw-metadata finding/latest human Opport… | P3A-11h | pending | pending | Owning parent/phase gates unchanged |
| [L188](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Add D146/P3A-11i deliberate private exact-action/revision current source inspection in the existing native act… | P3A-11i | pending | pending | Owning parent/phase gates unchanged |
| [L189](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Implement D147/P3A-11j explicit subjective usefulness acknowledgment over the exact current supported bounded … | P3A-11j | pending | pending | Owning parent/phase gates unchanged |
| [L195](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Add D148/P3A-11k retained organization-age-at-first-server-subjective-acknowledgment timing source/private GET… | P3A-11k, P3A-11, P06-07 | in_progress | in_progress | Consent design; Live attribution; Manual accessibility; Real source grants |
| [L196](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Validate source attribution across public/app hosts, verification links, and hosted checkout; use verified bac… | P3A-11 | in_progress | in_progress | Consent design; Live attribution |
| [L197](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Implement D149/P3A-11l first-party optional analytics consent/default-off native controls and canonical-public… | P3A-11l | pending | pending | Owning parent/phase gates unchanged |
| [L198](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Check D150/P3A-11m minimized publication-policy compiler→strict backend parser against actual full generated-H… | P3A-11m | pending | pending | Owning parent/phase gates unchanged |
| [L199](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Check D151/P3A-11n pure minimized native-candidate→pinned-policy public observation source; final21(75.939s)/2… | P3A-11n | pending | pending | Owning parent/phase gates unchanged |
| [L200](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Locally implement D152/P3A-11o prospective unlinked fifteen-minute consent-epoch/browser-reported route-CTA fi… | P3A-11o | pending | pending | Owning parent/phase gates unchanged |
| [L217](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Implement D153/P3A-11p original organization-age-at-first-paid-server-observation timing over genuine D141 res… | P3A-11p | pending | pending | Owning parent/phase gates unchanged |
| [L220](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Record dated access/approval, capability/scope, quota/cost, terms/retention, owner and representative-job read… | P3A-12 | pending | pending | Provider terms/cost/access |
| [L221](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Check D154/P3A-11q genuine audited original trial activation source: matching automatic eligibility/grant or s… | P3A-11q | pending | pending | Owning parent/phase gates unchanged |
| [L223](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Implement D155/P3A-11r original audited trial-start→first immutable paid server observation timing/original so… | P3A-11r | pending | pending | Owning parent/phase gates unchanged |
| [L226](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Set trial/plan allowances against supported provider/crawl/AI budgets and AI-visibility sample cadence; do not… | P3A-04, P3A-12 | pending | pending | Commercial/legal readiness; Provider terms/cost/access |
| [L227](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Check D156/P3A-11s fixed original trial-start→start+37-day half-open paid-server-observation source maturity o… | P3A-11s | pending | pending | Owning parent/phase gates unchanged |
| [L229](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Grant automatic organization trials exactly once after email verification and eligible organization creation; … | P3A-05 | in_progress | in_progress | Production historical cutover |
| [L230](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Implement D157/P3A-11t strict private owner original trial paid-window GET/native deliberate frozen source ins… | P3A-11t | pending | pending | Owning parent/phase gates unchanged |
| [L232](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) If the selected policy requires a card upfront, complete hosted payment setup before trial eligibility/clock s… | P3A-05 | in_progress | in_progress | Production historical cutover |
| [L233](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Check D158/P3A-11u complete retained monthly original-trial paid-window source: real current staff/MFA authori… | P3A-11u | pending | pending | Owning parent/phase gates unchanged |
| [L234](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Implement D159/P3A-11v strict private staff default/exact completed-month GET and deliberate native retained-c… | P3A-11v | pending | pending | Owning parent/phase gates unchanged |
| [L235](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Current native recovery2026-10-10 P3A-11v/w/x/y/P05-05a–c focused checks and app types pass; x/y bounded Billi… | P3A-11v, P05-05a, P02-06a, P02-06b, P08-08b, P08-06c, P08-03a, P08-03b, P08-04c, P08-02a, P08-05a, P3A-11z, P11-05d, P11A-05a, P06-04a, P06-04b, P08-01c, P06-05a, P07-06a, P06-01a, P06-04c, P06-04d, P06-04e, P06-05b, P11-04c, P11-04d, P09-02a, P12-02cl, P11-01de, P12-02cm | pending | pending | Owning parent/phase gates unchanged |
| [L236](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Complete commercial trial/paid lifecycle and retained results/export states; locally verified P3A-07/P3A-08 no… | P3A-07, P3A-08, P3A-06, P02-06 | in_progress | in_progress | Provider sandbox; Legal identity/export; Live deletion |
| [L237](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Show the owner the recorded local trial state, exact browser-local end time, accepted limits, settled actual u… | P3A-05 | in_progress | in_progress | Production historical cutover |
| [L238](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Complete hosted checkout/customer billing portal acceptance without storing raw card data; P3A-06/P3A-07 local… | P3A-06, P3A-07, P3A-12, P3A-13 | in_progress | in_progress | Provider sandbox; Provider terms/cost/access |
| [L239](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Add MFA-protected write-only staff Paddle seller/catalog/webhook configuration, owner-facing hosted checkout/r… | P3A-06, P3A-08 | in_progress | in_progress | Provider sandbox |
| [L240](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Add locally checked sandbox/live staff seller/catalog configuration with separate encrypted API/webhook secret… | P3A-06 | in_progress | in_progress | Provider sandbox |
| [L241](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Cover renewal, failed payment/retries/notices, upgrade/downgrade effective dates, invoices/payment methods, ca… | P3A-06, P3A-07 | in_progress | in_progress | Provider sandbox |
| [L242](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Verify webhook raw-body signatures/replay protection, persist/deduplicate events, handle asynchronous retries/… | P3A-07 | in_progress | in_progress | Provider sandbox |
| [L243](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Locally verify Paddle raw-body signed receipts, unique event ID, bounded default-worker retry/recovery and cur… | P3A-07 | in_progress | in_progress | Provider sandbox |
| [L244](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Wire local API, Search Console scheduler/backfill and worker commercial entitlement gates into atomic usage re… | P3A-08 | in_progress | in_progress | Owning parent/phase gates unchanged |
| [L245](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Configure transactional email and sender authentication, delivery retries/bounces/complaints, and security/tri… | P3A-10, P13-01, P13-03 | in_progress | in_progress | Sender/domain/copy; Live deployment |
| [L246](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Test trial duplication/races, quota concurrency, expiry during work, forged/replayed/late billing events, and … | P3A-05, P3A-07, P3A-13 | in_progress | in_progress | Production historical cutover; Provider sandbox |
| [L247](../TODO_ARCHIVE_2026-10-10.md#phase-3a-commercial-readiness-public-launch-requirement) Verify the complete public journey, accessible customer/admin screens, support access, and export/closure poli… | P3A-13 | pending | pending | Owning parent/phase gates unchanged |
| [L251](../TODO_ARCHIVE_2026-10-10.md#phase-4-job-platform) Implement scoped JobRun, JobStep, Artifact, SourceCitation and inactive JobSchedule records (P04-01/D069; sche… | P04-01, P04-05 | verified | verified | Current scoped diagnostic schema/dispatch/schedule/stage owning evidence verified |
| [L252](../TODO_ARCHIVE_2026-10-10.md#phase-4-job-platform) Define queued, running, waiting_provider, succeeded, failed, cancelled, and partially_succeeded … | P04-01 | verified | verified | Owning parent/phase gates unchanged |
| [L253](../TODO_ARCHIVE_2026-10-10.md#phase-4-job-platform) Configure Redis and Celery for current internal diagnostic work (P01-04/P04-02; real handler-specific routing … | P01-04, P04-02 | verified | verified | Live deployment |
| [L254](../TODO_ARCHIVE_2026-10-10.md#phase-4-job-platform) Configure default, AI, crawl, and audit worker queues (P01-04; only cost-free diagnostic dispatches on default… | P01-04 | verified | verified | Live deployment |
| [L255](../TODO_ARCHIVE_2026-10-10.md#phase-4-job-platform) Configure one Celery Beat scheduler and bounded dev diagnostic due/recovery ticks (P01-04/P04-05; production r… | P01-04, P04-05 | verified | verified | Live deployment |
| [L256](../TODO_ARCHIVE_2026-10-10.md#phase-4-job-platform) Implement scoped creation/status/cancellation/retry APIs for the local diagnostic job (P04-03/D071; real handl… | P04-03 | verified | verified | Current owning source-bound automated acceptance verified; manual/provider/final gates separate |
| [L257](../TODO_ARCHIVE_2026-10-10.md#phase-4-job-platform) Implement local diagnostic Angular polling/progress/partial-state UI with stale-scope and network-failure hand… | P04-03, P06-07 | in_progress | in_progress | Diagnostic API/progress and budget boundary verified; remaining first-audit/stage owners pending |
| [L258](../TODO_ARCHIVE_2026-10-10.md#phase-4-job-platform) Add current diagnostic idempotency, bounded timeouts, post-commit reconciliation and a durable cancellation ch… | P04-02, P04-05 | verified | verified | Current scoped diagnostic schema/dispatch/schedule/stage owning evidence verified |
| [L259](../TODO_ARCHIVE_2026-10-10.md#phase-4-job-platform) Add provider-specific transient retries, cost-aware external idempotency and cancellation checks with each rea… | P04-02, P04-03 | in_progress | in_progress | P04-02 dispatch/audit boundary verified; remaining recovery/provider owners pending |
| [L260](../TODO_ARCHIVE_2026-10-10.md#phase-4-job-platform) Add internal project/provider/organization unit and concurrency ceilings with atomic reservations and idempote… | P04-04 | verified | verified | Current owning source-bound automated acceptance verified; manual/provider/final gates separate |
| [L261](../TODO_ARCHIVE_2026-10-10.md#phase-4-job-platform) Recover genuinely stuck running jobs and settle real external-provider costs once their handlers exist (P04-05… | P04-05, P3A-08 | in_progress | in_progress | P04-05 known diagnostic recovery verified; real external-cost/commercial owner pending |
| [L262](../TODO_ARCHIVE_2026-10-10.md#phase-4-job-platform) Store authoritative P04-01 job state and diagnostic evidence in PostgreSQL; user-facing status APIs follow P04… | P04-01, P04-03 | verified | verified | Current owning source-bound automated acceptance verified; manual/provider/final gates separate |
| [L263](../TODO_ARCHIVE_2026-10-10.md#phase-4-job-platform) Persist default-queue diagnostic dispatch after transaction commit, dedupe repeated deliveries and reconcile b… | P04-02 | verified | verified | Current admission/idempotency/broker-recovery audit5/source review complete |
| [L264](../TODO_ARCHIVE_2026-10-10.md#phase-4-job-platform) Recheck current organization/actor/project status and internal reservation at diagnostic dispatch and stage2; … | P04-04, P04-05 | verified | verified | Current scoped diagnostic schema/dispatch/schedule/stage owning evidence verified |
| [L265](../TODO_ARCHIVE_2026-10-10.md#phase-4-job-platform) Connect accepted commercial entitlements and provider-specific incurred usage to all future handler and delive… | P3A-08 | in_progress | in_progress | Owning parent/phase gates unchanged |
| [L267](../TODO_ARCHIVE_2026-10-10.md#phase-4-job-platform) P04-03a current diagnostic job status/requested-ID recovery: TWO guards, seven array/scalar state cases and ex… | P04-03a | verified | verified | Current owning source-bound automated acceptance verified; manual/provider/final gates separate |
| [L269](../TODO_ARCHIVE_2026-10-10.md#phase-4-job-platform) P04-03b native diagnostic scope/stale-chain recovery: safe route IDs/exact org+project metadata/current role w… | P04-03b | verified | verified | Current owning source-bound automated acceptance verified; manual/provider/final gates separate |
| [L273](../TODO_ARCHIVE_2026-10-10.md#phase-5-ai-providers-and-routing) Implement provider, provider-account, model, bounded routing-policy and AI request usage/cost-observation reco… | P05-01, P05-03, P05-04 | verified | verified | Current scoped AI selection/routing/cost/native owning source-bound acceptance verified; real provider/manual/final separate |
| [L274](../TODO_ARCHIVE_2026-10-10.md#phase-5-ai-providers-and-routing) Store the original platform-funded provider secret references with rotation/revocation and redacted administra… | P05-01, P05-05 | verified | verified | Current platform-reference/write-only encrypted ownership/revocation/source gates verified; live access separate |
| [L275](../TODO_ARCHIVE_2026-10-10.md#phase-5-ai-providers-and-routing) Complete native OpenAI adapter plus a bounded internal model-selected AI text job on the dedicated worker with… | P05-02, P3A-12 | in_progress | in_progress | P05-02 adapter/real local consumer verified; routing/readiness owner pending; actual provider access separate |
| [L276](../TODO_ARCHIVE_2026-10-10.md#phase-5-ai-providers-and-routing) Complete the OpenAI-compatible adapter's configuration and customer-facing routing/fallback controls locally (… | P05-02, P05-03, P3A-12 | in_progress | in_progress | P05-02 adapter/real local consumer verified; routing/readiness owner pending; actual provider access separate |
| [L277](../TODO_ARCHIVE_2026-10-10.md#phase-5-ai-providers-and-routing) Record and enforce provider model capabilities instead of assuming every model supports every feature (P05-01/… | P05-01 | verified | verified | Current catalog/evidence/capability guards source-bound to R06; actual provider evidence separate |
| [L278](../TODO_ARCHIVE_2026-10-10.md#phase-5-ai-providers-and-routing) Implement optional system AI-text defaults, project overrides and explicit job selection without seeding a mod… | P05-03 | verified | verified | Current scoped AI selection/routing/cost/native owning source-bound acceptance verified; real provider/manual/final separate |
| [L279](../TODO_ARCHIVE_2026-10-10.md#phase-5-ai-providers-and-routing) Implement preflight-only same-provider standard-access fallbacks, bounded time/token limits and estimated per-… | P05-04, P05-03 | verified | verified | Current scoped AI selection/routing/cost/native owning source-bound acceptance verified; real provider/manual/final separate |
| [L280](../TODO_ARCHIVE_2026-10-10.md#phase-5-ai-providers-and-routing) Record current AI text job/model/provider, nullable reported tokens, known tool/search use, request duration, … | P05-04 | verified | verified | Current scoped AI selection/routing/cost/native owning source-bound acceptance verified; real provider/manual/final separate |
| [L281](../TODO_ARCHIVE_2026-10-10.md#phase-5-ai-providers-and-routing) Add staff model/capability/price and system-routing UI plus owner/admin project-routing and explicit model-sel… | P05-03 | verified | verified | Current scoped AI selection/routing/cost/native owning source-bound acceptance verified; real provider/manual/final separate |
| [L282](../TODO_ARCHIVE_2026-10-10.md#phase-5-ai-providers-and-routing) Finish protected write-only operator and organization owner/admin AI/performance key and Google OAuth app cred… | P05-05, P05-03 | verified | verified | Current scoped AI selection/routing/cost/native owning source-bound acceptance verified; real provider/manual/final separate |
| [L283](../TODO_ARCHIVE_2026-10-10.md#phase-5-ai-providers-and-routing) Add a public data-use policy link and explicit per-job opt-in for free-tier models; free/unknown access never … | P05-03 | verified | verified | Current scoped AI selection/routing/cost/native owning source-bound acceptance verified; real provider/manual/final separate |
| [L284](../TODO_ARCHIVE_2026-10-10.md#phase-5-ai-providers-and-routing) P05-03a current native catalog tier/source recovery: TWO scalar guards/five malformed arrays, unknown option d… | P05-03a | verified | verified | Current scoped AI selection/routing/cost/native owning source-bound acceptance verified; real provider/manual/final separate |
| [L285](../TODO_ARCHIVE_2026-10-10.md#phase-5-ai-providers-and-routing) P05-04a current native AI detail/history states: FIVE scalar guards/owning2+app types pass with malformed-arra… | P05-04a | verified | verified | Current scoped AI selection/routing/cost/native owning source-bound acceptance verified; real provider/manual/final separate |
| [L286](../TODO_ARCHIVE_2026-10-10.md#phase-5-ai-providers-and-routing) Evaluate OpenAI background and batch execution only if a concrete suitable job requires them; the current boun… | P05-03 | pending | pending | Conditional local pending: no suitable current bounded-text job demands background/batch; agent/provider capability owner evaluates on real demand; stays in denominator |
| [L290](../TODO_ARCHIVE_2026-10-10.md#phase-6-project-onboarding-and-integrations) Collect project market, language, timezone, audience, offer, goals, voice, seeds, and prohibited topics (P06-0… | P06-01 | in_progress | in_progress | Owning parent/phase gates unchanged |
| [L291](../TODO_ARCHIVE_2026-10-10.md#phase-6-project-onboarding-and-integrations) Start with website/country/language/business goal plus optional source intent; progressively collect advanced … | P06-01 | in_progress | in_progress | Owning parent/phase gates unchanged |
| [L292](../TODO_ARCHIVE_2026-10-10.md#phase-6-project-onboarding-and-integrations) Save/resume onboarding and provide clearly labeled synthetic demo data isolated from live projects and usage (… | P06-01, P06-06, P06-04 | in_progress | in_progress | Real source grants |
| [L293](../TODO_ARCHIVE_2026-10-10.md#phase-6-project-onboarding-and-integrations) Deliver a budgeted first audit with progress/partial results and a small evidence-backed next-action list; tra… | P06-07 | in_progress | in_progress | Manual accessibility; Real source grants |
| [L294](../TODO_ARCHIVE_2026-10-10.md#phase-6-project-onboarding-and-integrations) Add competitor configuration (P06-01/D074). | P06-01 | in_progress | in_progress | Owning parent/phase gates unchanged |
| [L295](../TODO_ARCHIVE_2026-10-10.md#phase-6-project-onboarding-and-integrations) Add source-domain allow and block lists (P06-01/D074). | P06-01 | in_progress | in_progress | Owning parent/phase gates unchanged |
| [L296](../TODO_ARCHIVE_2026-10-10.md#phase-6-project-onboarding-and-integrations) Add Google Search Console CSV validation and import (P06-03; private fixture-only, no public activation). | P06-03 | verified | verified | [Current local CSV source/check evidence](IMPLEMENTATION_HISTORY_2026-10-16.md#p06-03-current-local-csv-contract-verified); final/manual/provider gates separate |
| [L297](../TODO_ARCHIVE_2026-10-10.md#phase-6-project-onboarding-and-integrations) Complete Google OAuth connection management and scoped domain-wide/URL-prefix property handling with operator … | P06-04, P3A-12 | pending | pending | Real source grants; Provider terms/cost/access |
| [L298](../TODO_ARCHIVE_2026-10-10.md#phase-6-project-onboarding-and-integrations) Complete Search Console API synchronization, bounded backfill/scheduled freshness, indexed-version inspection/… | P06-04, P3A-12 | pending | pending | Real source grants; Provider terms/cost/access |
| [L299](../TODO_ARCHIVE_2026-10-10.md#phase-6-project-onboarding-and-integrations) Define the small webmaster connector boundary and source-aware metric mappings, retaining provider/property id… | P06-02 | in_progress | in_progress | Owning parent/phase gates unchanged |
| [L300](../TODO_ARCHIVE_2026-10-10.md#phase-6-project-onboarding-and-integrations) Add the small exact-origin connection/import-provenance/sync-cursor contract with explicit capabilities, dimen… | P06-02 | verified | verified | [Current exact local source contract](IMPLEMENTATION_HISTORY_2026-10-16.md#p06-02-current-local-source-contract-verified) |
| [L301](../TODO_ARCHIVE_2026-10-10.md#phase-6-project-onboarding-and-integrations) Support multiple engine/property connections per project with domain-scope validation and source-specific uniq… | P06-02 | in_progress | in_progress | Owning parent/phase gates unchanged |
| [L302](../TODO_ARCHIVE_2026-10-10.md#phase-6-project-onboarding-and-integrations) Add per-connection cursors, bounded Search Console backfills, one-per-connection daily schedules, quota handli… | P06-04 | pending | pending | Real source grants |
| [L303](../TODO_ARCHIVE_2026-10-10.md#phase-6-project-onboarding-and-integrations) Add exact-origin-attributed GA4 Data API synchronization; the locally checked hostname-only transport/worker i… | P06-05 | pending | pending | Exact-origin capability; Real source grants |
| [L304](../TODO_ARCHIVE_2026-10-10.md#phase-6-project-onboarding-and-integrations) Record conversion definitions, event/value mappings, attribution settings, currency/timezone, and manual instr… | P06-05 | pending | pending | Exact-origin capability; Real source grants |
| [L305](../TODO_ARCHIVE_2026-10-10.md#phase-6-project-onboarding-and-integrations) Surface duplicate/missing-event concerns, consent/reporting gaps, modeling where identified, and tracking chan… | P06-05 | pending | pending | Exact-origin capability; Real source grants |
| [L306](../TODO_ARCHIVE_2026-10-10.md#phase-6-project-onboarding-and-integrations) Configure brand aliases and reviewable branded/non-branded/unclassified query segments with query-coverage lim… | P06-06 | verified | verified | Current original brand/status source + backend4/native3 verified; global final and real provider gates separate |
| [L307](../TODO_ARCHIVE_2026-10-10.md#phase-6-project-onboarding-and-integrations) Capture real business locations/service areas, contact details, hours, profile links, and eligibility notes fo… | P06-01 | in_progress | in_progress | Owning parent/phase gates unchanged |
| [L308](../TODO_ARCHIVE_2026-10-10.md#phase-6-project-onboarding-and-integrations) Add current CSV connection status, import history and scoped disable/re-enable in onboarding (P06-06); P06-04 … | P06-06, P06-04 | pending | pending | Real source grants |
| [L309](../TODO_ARCHIVE_2026-10-10.md#phase-6-project-onboarding-and-integrations) Add Bing Webmaster Tools only after core Google integrations work. | P06-08 | pending | pending | Bing demand/capability |
| [L310](../TODO_ARCHIVE_2026-10-10.md#phase-6-project-onboarding-and-integrations) Add Yandex Webmaster after core Google integrations work; verify official API/export access, authentication, a… | P06-09 | implemented; CSV/OAuth/API sync, untested | deferred by D437 | Real engine capability; Additional engine demand |
| [L311](../TODO_ARCHIVE_2026-10-10.md#phase-6-project-onboarding-and-integrations) Make search dashboards and opportunity detectors engine-aware; preserve metric definitions and gate unsupporte… | P06-02, P08-01 | in_progress | in_progress | Exact-origin capability |
| [L312](../TODO_ARCHIVE_2026-10-10.md#phase-6-project-onboarding-and-integrations) Verify multi-engine record isolation, sync independence, capability gating, and unavailable-versus-zero handli… | P06-02, P08-01 | in_progress | in_progress | Exact-origin capability |
| [L313](../TODO_ARCHIVE_2026-10-10.md#phase-6-project-onboarding-and-integrations) Add further webmaster connectors when project demand and supported access justify them, reusing existing integ… | P06-09 | blocked | blocked | Additional engine demand |
| [L317](../TODO_ARCHIVE_2026-10-10.md#phase-7-safe-crawl-and-performance-collection) Implement bounded sitemap and robots.txt fetching with fail-closed discovery states (P07-01/D076; crawl-run pe… | P07-01, P07-02 | verified | verified | Current original crawler + repaired pre-send authority/focused/review/runtime verified; global final separate |
| [L318](../TODO_ARCHIVE_2026-10-10.md#phase-7-safe-crawl-and-performance-collection) Implement the HTTP-first project crawler (P07-02/D078). | P07-02 | verified | verified | Current original crawler + repaired pre-send authority/focused/review/runtime verified; global final separate |
| [L319](../TODO_ARCHIVE_2026-10-10.md#phase-7-safe-crawl-and-performance-collection) Enforce explicit project/selected-competitor target scopes; record external links without unrestricted recursi… | P07-01, P07-02, P10-01 | in_progress | in_progress | Owning parent/phase gates unchanged |
| [L320](../TODO_ARCHIVE_2026-10-10.md#phase-7-safe-crawl-and-performance-collection) Add host rate limits and crawl budgets (P07-02/D078). | P07-02 | verified | verified | Current original crawler + repaired pre-send authority/focused/review/runtime verified; global final separate |
| [L321](../TODO_ARCHIVE_2026-10-10.md#phase-7-safe-crawl-and-performance-collection) Add SSRF, redirect, response-size, timeout, port, and scheme protections (P07-01/D076). | P07-01 | verified | verified | Current original safe-fetch source/exact8 verified; prior marked review retained; global final separate |
| [L322](../TODO_ARCHIVE_2026-10-10.md#phase-7-safe-crawl-and-performance-collection) Parse metadata, headings, canonicals, robots, hreflang, links, and structured-data candidates (P07-02/D078; va… | P07-02, P07-04 | verified | verified | Current original diagnostics/source/owning4 and existing configuration/native evidence verified; global final separate |
| [L323](../TODO_ARCHIVE_2026-10-10.md#phase-7-safe-crawl-and-performance-collection) Record redirect chains, status codes, content hashes, and failures (P07-02/D078). | P07-02 | verified | verified | Current original crawler + repaired pre-send authority/focused/review/runtime verified; global final separate |
| [L324](../TODO_ARCHIVE_2026-10-10.md#phase-7-safe-crawl-and-performance-collection) Store bounded raw HTML through private artifact storage, using S3 in production configuration (P07-02/D078; no… | P07-02 | verified | verified | Current original crawler + repaired pre-send authority/focused/review/runtime verified; global final separate |
| [L325](../TODO_ARCHIVE_2026-10-10.md#phase-7-safe-crawl-and-performance-collection) Add budgeted browser rendering for JavaScript-dependent pages or requested raw-versus-rendered diagnostics, pr… | P07-03 | verified | verified | Current renderer/protocol/actual synthetic Chromium/runtime verified; original marked review retained; global final separate |
| [L326](../TODO_ARCHIVE_2026-10-10.md#phase-7-safe-crawl-and-performance-collection) Compare raw/rendered content, links, metadata, canonicals, and directives while reporting rendering failures a… | P07-03 | verified | verified | Current renderer/protocol/actual synthetic Chromium/runtime verified; original marked review retained; global final separate |
| [L327](../TODO_ARCHIVE_2026-10-10.md#phase-7-safe-crawl-and-performance-collection) Check in-scope canonical targets and internal-link depth; reconcile orphan candidates with available sitemap i… | P07-04 | verified | verified | Current original diagnostics/source/owning4 and existing configuration/native evidence verified; global final separate |
| [L328](../TODO_ARCHIVE_2026-10-10.md#phase-7-safe-crawl-and-performance-collection) Handle pagination, facets, and query parameters with project-specific rules and budgets that preserve meaningf… | P07-04 | verified | verified | Current original diagnostics/source/owning4 and existing configuration/native evidence verified; global final separate |
| [L329](../TODO_ARCHIVE_2026-10-10.md#phase-7-safe-crawl-and-performance-collection) Validate bounded structured-data syntax/type-shape requirements and visible-content consistency; keep rich-res… | P07-04 | verified | verified | Current original diagnostics/source/owning4 and existing configuration/native evidence verified; global final separate |
| [L330](../TODO_ARCHIVE_2026-10-10.md#phase-7-safe-crawl-and-performance-collection) Reconcile sitemap/crawl and available exact-URL engine indexing observations, keeping discovered, crawlable, i… | P06-05, P07-05 | in_progress | in_progress | Exact-origin capability; Real source grants; Real engine capability |
| [L331](../TODO_ARCHIVE_2026-10-10.md#phase-7-safe-crawl-and-performance-collection) Add meaningful checks for crawl traps, canonical targets, rendering differences, and unknown/conflicting index… | P07-04, P07-05, P3A-12 | in_progress | in_progress | Real engine capability; Provider terms/cost/access |
| [L332](../TODO_ARCHIVE_2026-10-10.md#phase-7-safe-crawl-and-performance-collection) Finish project-scoped PageSpeed Insights audit trigger/status and lab UI using P07-06's fixture-tested transpo… | P07-06, P3A-12 | in_progress | in_progress | Real source grants; Provider terms/cost/access |
| [L333](../TODO_ARCHIVE_2026-10-10.md#phase-7-safe-crawl-and-performance-collection) Finish CrUX current/history configuration and field UI using P07-06's fixture-tested transport/evidence; real … | P07-06, P3A-12 | in_progress | in_progress | Real source grants; Provider terms/cost/access |
| [L334](../TODO_ARCHIVE_2026-10-10.md#phase-7-safe-crawl-and-performance-collection) Keep lab and field data clearly distinguished in storage and UI (P07-06). | P07-06 | verified | verified | Current original performance source/focused/review/runtime/native verified; actual provider/final separate |
| [L340](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Detect source-limited 4–20 average-position **candidates**, never observed universal rank (P08-01a). | P08-01a | verified | verified | Current original source-limited candidate/review/backend9/native3 verified; richer source and global final gates separate |
| [L341](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Detect high-impression/low-CTR **candidates** on compatible complete rows (P08-01a). | P08-01a | verified | verified | Current original source-limited candidate/review/backend9/native3 verified; richer source and global final gates separate |
| [L342](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Detect adjacent-window declining/growing query/page observations where the same source/dimension is comparable… | P08-01a | verified | verified | Current original source-limited candidate/review/backend9/native3 verified; richer source and global final gates separate |
| [L343](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Detect keyword cannibalization candidates. | P08-01 | pending | pending | Exact-origin capability |
| [L344](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Detect metadata, status, redirect, canonical, robots, sitemap, hreflang, and internal-link issues. | P08-01 | pending | pending | Exact-origin capability |
| [L345](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Detect stale, duplicate, and weakly linked content candidates. | P08-01 | pending | pending | Exact-origin capability |
| [L346](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Combine GA4 conversion context where available. | P08-01 | pending | pending | Exact-origin capability |
| [L347](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Preserve provenance, immutable source snapshots and method version for implemented P08-01a findings; source-de… | P08-01a, P08-01b | in_progress | in_progress | Exact-origin capability |
| [L348](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Implement impact, confidence, effort, business-value, status, and filtering UI. | P08-06 | pending | pending | Manual accessibility |
| [L349](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Add AI-assisted grouping and explanations without hiding deterministic evidence. | P08-06 | pending | pending | Manual accessibility |
| [L350](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Add reviewable human intent/query clusters mapped to existing-unverified/proposed pages by project, market and… | P08-02 | verified | verified | Current original human mapping/source/revision/API5/native5 verified; global final separate |
| [L351](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Allow explicit human keep/refresh/merge/redirect/retire/create **unapproved proposals** with reason/source/des… | P08-02, P08-03, P08-04 | in_progress | in_progress | Exact-origin capability |
| [L352](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Add project-owned assignee/action states, approval/revision history, manual implementation/verification/outcom… | P08-03 | verified | verified | Current original manual action/source/role/revision/API4/native4 verified; global final separate |
| [L353](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Link changes to content revisions or external tickets where available and verify fixes separately through foll… | P08-03, P08-04 | in_progress | in_progress | Exact-origin capability |
| [L354](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Preserve immutable, source-limited before/after page CSV and bounded crawl observations for implemented action… | P08-04a | verified | verified | Owning parent/phase gates unchanged |
| [L355](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Show source-compatible observed search and conditional conversion/revenue changes without causal claims: P08-0… | P08-04a, P08-04b | pending | pending | Exact-origin capability |
| [L356](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Add P08-05 project-scoped manual local business/listing/eligibility review from current user-entered configura… | P08-05 | verified | verified | Owning parent/phase gates unchanged |
| [L357](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Complete P08-06 dashboard usability: P08-06a text-first project source/findings/intent/action/local status wit… | P08-06, P08-06a, P08-06b | pending | pending | Manual accessibility |
| [L358](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Specify empty/loading/demo/disconnected/stale/partial/failed/access-denied/quota/expiry states and distinguish… | P08-06 | pending | pending | Manual accessibility |
| [L359](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Provide estimated credits/cost, clear progress/cancel/retry, accessible forms/charts/tables, and consistent fi… | P08-06 | pending | pending | Manual accessibility |
| [L360](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Add weekly summaries/scheduled reports and deduplicated regression/integration/job alerts with user/project pr… | P08-07 | pending | pending | Sender/domain/copy |
| [L361](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Implement D186/P08-07y original canonical raw SHA256 on genuine performance insertion: owning16 actual cases/a… | P08-07y | pending | pending | Owning parent/phase gates unchanged |
| [L362](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Check D187/P08-07z exact-current genuine CrUX history source: owning8/final49 PostgreSQL158.258s/system-curren… | P08-07z | pending | pending | Owning parent/phase gates unchanged |
| [L363](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Add D188/P08-07aa strict private exact-project CrUX candidate GET: owning3/final14 PostgreSQL57.805s/system-cu… | P08-07aa | pending | pending | Owning parent/phase gates unchanged |
| [L364](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Finish D189/P08-07ab deliberate native exact CrUX history inspection: owning+routed135/final271 Angular54.04s/… | P08-07ab | pending | pending | Owning parent/phase gates unchanged |
| [L365](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Check D190/P08-07ac genuine material CrUX threshold candidate filter: owning5 PostgreSQL24.383s/affected z-aa1… | P08-07ac | pending | pending | Owning parent/phase gates unchanged |
| [L366](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Check D191/P08-07ad strict private exact-source material-policy GET: owning3 PostgreSQL13.324s/affected16 Post… | P08-07ad | pending | pending | Owning parent/phase gates unchanged |
| [L367](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Check D161/P08-07a retained private report weekly-summary source: server-frozen previous completed UTC report-… | P08-07a | verified | verified | Owning parent/phase gates unchanged |
| [L368](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Implement D162/P08-07b default-off own-user/project email off/weekly intent/revision-fenced private API/native… | P08-07b | verified | verified | Owning parent/phase gates unchanged |
| [L369](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Check D163/P08-07c current weekly preference/primary-reader/suppression/effective-entitlement→retained report … | P08-07c | verified | verified | Owning parent/phase gates unchanged |
| [L370](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Implement D164/P08-07d default-off optional weekly delivery kernel: unique project/recipient/completed-week id… | P08-07d | verified | verified | Owning parent/phase gates unchanged |
| [L371](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Implement D165/P08-07e default-queue current-week opt-in discovery:20-preference complete keyset/high-water pa… | P08-07e | verified | verified | Owning parent/phase gates unchanged |
| [L372](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Restore D166/P08-07b1 existing own preference GET user/IP budget: actual red1→owning6 PostgreSQL15.074s/affect… | P08-07b1 | verified | verified | Owning parent/phase gates unchanged |
| [L373](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Check D167/P08-07f read-only own-user/project newest20 weekly delivery history/safe IDs-week-dates-fixed state… | P08-07f | verified | verified | Owning parent/phase gates unchanged |
| [L374](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Implement D168/P08-07g strict private own summary-deliveries GET/current reader/server-only source/no query-bo… | P08-07g | verified | verified | Owning parent/phase gates unchanged |
| [L375](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Implement D169/P08-07h explicit native own weekly history/strict UTC state and late-scope clearing plus truthf… | P08-07h | verified | verified | Owning parent/phase gates unchanged |
| [L376](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Implement D170/P08-07i read-only retained failed-crawl source/current final reader+source/minimized fixed fail… | P08-07i | verified | verified | Owning parent/phase gates unchanged |
| [L377](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Implement D171/P08-07j strict private retained crawl-failures GET/current exact-project reader/server source/n… | P08-07j | verified | verified | Owning parent/phase gates unchanged |
| [L378](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Implement D172/P08-07k explicit native retained crawl-failure inspection/strict original UTC microsecond dates… | P08-07k | verified | verified | Owning parent/phase gates unchanged |
| [L379](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Check D173/P08-07l bounded read-only current-project integration-health metadata/original connection-scope-gra… | P08-07l | verified | verified | Owning parent/phase gates unchanged |
| [L380](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Implement D174/P08-07m strict private integration-health GET/current exact-project reader/no additional input/… | P08-07m | verified | verified | Owning parent/phase gates unchanged |
| [L381](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Implement D175/P08-07n deliberate native integration-health inspection/strict minimized fixed states/original … | P08-07n | verified | verified | Owning parent/phase gates unchanged |
| [L382](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Implement D176/P08-07o independent default-off own project alert intent: email off/daily/selected crawl_failur… | P08-07o | verified | verified | Owning parent/phase gates unchanged |
| [L383](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Check D177/P08-07p current own daily crawl-failure candidate source: previous completed UTC status-update day/… | P08-07p | pending | pending | Owning parent/phase gates unchanged |
| [L384](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Check D178/P08-07q prospective actual Google reconnect audit method/resulting revision, genuine worker denial/… | P08-07q | pending | pending | Owning parent/phase gates unchanged |
| [L385](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Check D179/P08-07r current daily integration_health intent/current recipient→prospective reconnect audit/curre… | P08-07r | pending | pending | Owning parent/phase gates unchanged |
| [L386](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Check D180/P08-07s one-day full operational source pin over actual p/r/current intent:19 PostgreSQL62.159s/fin… | P08-07s | pending | pending | Owning parent/phase gates unchanged |
| [L387](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Implement D181/P08-07t default-off own daily operational digest/child related-episode SQL dedupe kernel: ownin… | P08-07t | pending | pending | Owning parent/phase gates unchanged |
| [L388](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Add D182/P08-07u default-queue bounded daily discovery: owning4/final24 PostgreSQL225.272s/topology7/config ru… | P08-07u | pending | pending | Owning parent/phase gates unchanged |
| [L389](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Check D183/P08-07v own read-only daily history:17 PostgreSQL73.953s/system-current-all-app drift/loaded unregi… | P08-07v | pending | pending | Owning parent/phase gates unchanged |
| [L390](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Add D184/P08-07w strict private own daily-history GET:14 PostgreSQL68.911s/system-current-drift/loaded fixed r… | P08-07w | pending | pending | Owning parent/phase gates unchanged |
| [L391](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Complete D185/P08-07x native own daily history/truthful configured availability:138 owning+routed/final264 Ang… | P08-07x | pending | pending | Owning parent/phase gates unchanged |
| [L392](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Implement D192/P08-07ae deliberate native exact material-policy inspection in the existing CrUX history panel,… | P08-07ae | pending | pending | Owning parent/phase gates unchanged |
| [L393](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Check D193/P08-07af material-only genuine observed-source/metric/period-pair opaque identities stable across r… | P08-07af | pending | pending | Owning parent/phase gates unchanged |
| [L394](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Implement D194/P08-07ag independent default-off own material-CrUX email off/daily intent model/service/revisio… | P08-07ag | pending | pending | Owning parent/phase gates unchanged |
| [L395](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Implement D195/P08-07ah strict private own CrUX preference GET/CSRF revision-fenced POST/exact bounded JSON/in… | P08-07ah | pending | pending | Owning parent/phase gates unchanged |
| [L396](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Complete D196/P08-07ai separate native own CrUX off/daily intent form/fixed GET-POST/strict cloned original sc… | P08-07ai | pending | pending | Owning parent/phase gates unchanged |
| [L397](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Check D197/P08-07aj exact genuine CrUX observation/current independent daily intent-original date/verified pri… | P08-07aj | pending | pending | Owning parent/phase gates unchanged |
| [L398](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Check D198/P08-07ak complete retained100/fetch101 CrUX collection/newest collection+ID raw-validated observed-… | P08-07ak | pending | pending | Owning parent/phase gates unchanged |
| [L399](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Implement/check D199/P08-07al independent default-off CrUX daily delivery/related SQL claims/full current sour… | P08-07al | pending | pending | Owning parent/phase gates unchanged |
| [L400](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Implement/check D200/P08-07am independent default-queue CrUX scan/send/hourly/default-worker-only rollout0/cur… | P08-07am | pending | pending | Owning parent/phase gates unchanged |
| [L401](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Implement/check D201/P08-07an independent own retained CrUX transport history: final15 PostgreSQL130.173s/syst… | P08-07an | pending | pending | Owning parent/phase gates unchanged |
| [L402](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Implement/check D202/P08-07ao fixed strict private own CrUX transport-history GET: final13 PostgreSQL56.044s/s… | P08-07ao | pending | pending | Owning parent/phase gates unchanged |
| [L403](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Implement/check D203/P08-07ap native own CrUX transport-history/truthful configured availability/SAME API-defa… | P08-07ap | pending | pending | Owning parent/phase gates unchanged |
| [L404](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Implement/check D204/P08-09a minimized retained exact-project job support reference: final10 PostgreSQL17.689s… | P08-09a | pending | pending | Owning parent/phase gates unchanged |
| [L405](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Implement/check D205/P08-09b strict private exact retained job-reference GET: final13 PostgreSQL18.233s/system… | P08-09b | pending | pending | Owning parent/phase gates unchanged |
| [L406](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Implement/check D206/P08-09c explicit native exact job-reference inspector/fixed private GET/strict cloned sco… | P08-09c | pending | pending | Owning parent/phase gates unchanged |
| [L407](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Restore D160/P08-08a final current reader/original report/share expiry-revocation-creator-entitlement checks a… | P08-08a | verified | verified | Owning parent/phase gates unchanged |
| [L408](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Add private project report snapshots/exports and authenticated downloads; owner/admin-created external shares … | P08-08, P02-06 | in_progress | in_progress | Legal identity/export; Live deletion |
| [L409](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Add help/FAQ/support requests using safe job/request IDs, permission-scoped support records, and visible expor… | P08-09 | pending | pending | Live support operation |
| [L412](../TODO_ARCHIVE_2026-10-10.md#phase-8-seo-findings-and-opportunities) Check keyboard/screen-reader usability, basic accessibility automation, report-share revocation, notification … | P08-06, P08-08 | pending | pending | Manual accessibility |
| [L416](../TODO_ARCHIVE_2026-10-10.md#phase-9-trends-and-topic-discovery) Add source-aware Search Console query-growth topic signals with hidden/ambiguous coverage and comparable windo… | P09-01 | pending | pending | Owning parent/phase gates unchanged |
| [L417](../TODO_ARCHIVE_2026-10-10.md#phase-9-trends-and-topic-discovery) Add configurable safe RSS/Atom sources and bounded discover_topics collection (P09-01; private fixture-only,… | P09-01 | pending | pending | Owning parent/phase gates unchanged |
| [L418](../TODO_ARCHIVE_2026-10-10.md#phase-9-trends-and-topic-discovery) Select GDELT DOC 2.0 ArticleList RSS for bounded, attributed news metadata (D117); connector/UI accepted local… | P09-02 | pending | pending | Official Trends access; Real source grants |
| [L419](../TODO_ARCHIVE_2026-10-10.md#phase-9-trends-and-topic-discovery) Locally check configured GDELT metadata discovery/current review/UI, one-unit budget, independent-source parti… | P09-02 | pending | pending | Official Trends access; Real source grants |
| [L420](../TODO_ARCHIVE_2026-10-10.md#phase-9-trends-and-topic-discovery) Add separate bounded YouTube public-video metadata search for explicitly selected current project seeds/langua… | P09-02 | pending | pending | Official Trends access; Real source grants |
| [L421](../TODO_ARCHIVE_2026-10-10.md#phase-9-trends-and-topic-discovery) P09-02b current native response recovery: region/video/token RED3→owning6 and app types pass; parent actual-so… | P09-02b | pending | pending | Owning parent/phase gates unchanged |
| [L422](../TODO_ARCHIVE_2026-10-10.md#phase-9-trends-and-topic-discovery) Apply for or integrate official Google Trends API access when available. | P09-02 | blocked | blocked | Official Trends access |
| [L423](../TODO_ARCHIVE_2026-10-10.md#phase-9-trends-and-topic-discovery) Do not depend on unofficial Google Trends scraping (P09-02). Current limited alpha page exposes no supported p… | P09-02 | pending | pending | Official Trends access; Real source grants |
| [L424](../TODO_ARCHIVE_2026-10-10.md#phase-9-trends-and-topic-discovery) Normalize and deduplicate first-party/query and public-feed topic candidates without conflating event/source i… | P09-01, P09-03 | pending | pending | Owning parent/phase gates unchanged |
| [L425](../TODO_ARCHIVE_2026-10-10.md#phase-9-trends-and-topic-discovery) Implement inspectable topic relevance/value/geographic-language/coverage human judgments and separate determin… | P09-03 | pending | pending | Owning parent/phase gates unchanged |
| [L426](../TODO_ARCHIVE_2026-10-10.md#phase-9-trends-and-topic-discovery) P09-03a current topic role/source confirmation: genuine RED2→new3+original lifecycle1 and app types pass; boun… | P09-03a | pending | pending | Owning parent/phase gates unchanged |
| [L427](../TODO_ARCHIVE_2026-10-10.md#phase-9-trends-and-topic-discovery) P09-03b exact topic job consumers: genuine RED3→owning6+original topic journey1/types pass; Jobs source review… | P09-03b, P09-03c | pending | pending | Owning parent/phase gates unchanged |
| [L428](../TODO_ARCHIVE_2026-10-10.md#phase-9-trends-and-topic-discovery) P09-03d current mapping choices: current-flag RED1→exact1/types pass; bounded Django actual producer review co… | P09-03d | pending | pending | Owning parent/phase gates unchanged |
| [L429](../TODO_ARCHIVE_2026-10-10.md#phase-9-trends-and-topic-discovery) P09-03e source catalogue/history recovery: text/source-ID/import lineage/snapshot-count RED2→exact2/types/pare… | P09-03e | pending | pending | Owning parent/phase gates unchanged |
| [L430](../TODO_ARCHIVE_2026-10-10.md#phase-9-trends-and-topic-discovery) P09-03f full human review responses: canonical summary/history/save RED3→focus3/types; source review mapping/p… | P09-03f, P09-03g | pending | pending | Owning parent/phase gates unchanged |
| [L431](../TODO_ARCHIVE_2026-10-10.md#phase-9-trends-and-topic-discovery) P09-03g original candidate evidence: null/scalar/detail/request-ID RED3→focus3/types pass; actual feed/news/qu… | P09-03g | pending | pending | Owning parent/phase gates unchanged |
| [L432](../TODO_ARCHIVE_2026-10-10.md#phase-9-trends-and-topic-discovery) P09-03h Unicode human-review responses: exact emoji at-limit/one-over across collection/history/save PASS1 and… | P09-03h | pending | pending | Owning parent/phase gates unchanged |
| [L433](../TODO_ARCHIVE_2026-10-10.md#phase-9-trends-and-topic-discovery) P09-03i original candidate Unicode: owning1/types/parent actual producer proof pass; title/query/raw URL/feed … | P09-03i | pending | pending | Owning parent/phase gates unchanged |
| [L434](../TODO_ARCHIVE_2026-10-10.md#phase-9-trends-and-topic-discovery) P09-03j human Unicode input/configured market: RED2→owning2/types/parent criteria, coherent changed-save+origi… | P09-03j | pending | pending | Owning parent/phase gates unchanged |
| [L435](../TODO_ARCHIVE_2026-10-10.md#phase-9-trends-and-topic-discovery) Separate human trending/evergreen/unknown classifications in the private topic filter UI (P09-03; classificati… | P09-03 | pending | pending | Owning parent/phase gates unchanged |
| [L439](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) Implement bounded sourced topic-research jobs from explicitly user-selected configured HTTPS sources, with one… | P10-01 | pending | pending | Owning parent/phase gates unchanged |
| [L440](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-01a current research history scalar/current-refresh recovery: owning1/types pass, actual five-field root+r… | P10-01a | pending | pending | Owning parent/phase gates unchanged |
| [L441](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-01b research launch/catalog/current selection recovery: owning4+original handoff/source2/types/Jobs clean,… | P10-01b | pending | pending | Owning parent/phase gates unchanged |
| [L442](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-01c research job scalar/usage/exact-root-ID/destruction recovery: owning7+original private-source1/types/J… | P10-01c | pending | pending | Owning parent/phase gates unchanged |
| [L443](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-01d reviewed-topic research handoff display: array classification RED1→exact1/types pass, bounded revision… | P10-01d | pending | pending | Owning parent/phase gates unchanged |
| [L444](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-01e current research mapping choices: zero-ID unsolicited prefill RED1→focus1/types; actual field-limit so… | P10-01e | pending | pending | Owning parent/phase gates unchanged |
| [L445](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-01k Unicode current topic/mapping labels and policy URLs: RED2→three guards/focus2/types/parent actual pro… | P10-01k | pending | pending | Owning parent/phase gates unchanged |
| [L446](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-01l full Unicode research topic input: genuine native-cap RED1→owning1/types/parent source accepted; exact… | P10-01l | pending | pending | Owning parent/phase gates unchanged |
| [L447](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-01j exact submitted model/account provider pairing: RED1→one guard/owning1/types/parent actual server crit… | P10-01j | pending | pending | Owning parent/phase gates unchanged |
| [L448](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-01i nested sources/excerpt-linked interpretations: RED3→owning3/types, scalar bounded source/claim/current… | P10-01i | pending | pending | Owning parent/phase gates unchanged |
| [L449](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-01h research displayed counters/error/nullable costs: RED1→owning1/types/parent source; exact affected ori… | P10-01h | pending | pending | Owning parent/phase gates unchanged |
| [L450](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-01g model/account scalar catalogue and nullable output caps: new3 RED→PASS/types/original2/Jobs source com… | P10-01g | pending | pending | Owning parent/phase gates unchanged |
| [L451](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-01f exact research project roles before reads: RED1→new1+original scalar-role1/types/parent actual role-so… | P10-01f | pending | pending | Owning parent/phase gates unchanged |
| [L452](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) Store and display the complete selected source list, retrieval provenance, capped evidence and citations for l… | P10-01 | pending | pending | Owning parent/phase gates unchanged |
| [L453](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-02a current brief role/source/history/export/destruction recovery: effective owning4+original brief1/types… | P10-02a | pending | pending | Owning parent/phase gates unchanged |
| [L454](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-02c brief source choices: genuine RED2→owning2/types; bounded Django source review ONE finding repaired/cl… | P10-02c | pending | pending | Owning parent/phase gates unchanged |
| [L455](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-02d human brief input: RED1→owning1/types/parent actual input criteria; full Unicode maxima/one-over pre-P… | P10-02d | pending | pending | Owning parent/phase gates unchanged |
| [L456](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-02e bounded private draft responses: genuine RED2→owning2/types; current source/claims/historical meaning … | P10-02e | pending | pending | Owning parent/phase gates unchanged |
| [L457](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-02b brief source IDs/create projection recovery: genuine RED1→exact1/types/parent source criteria pass, no… | P10-02b | pending | pending | Owning parent/phase gates unchanged |
| [L458](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) Implement private structured content briefs over actual selected research/mapping/action revisions, with human… | P10-02 | pending | pending | Owning parent/phase gates unchanged |
| [L459](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) Implement project-owned content items and immutable text/state revisions (P10-03 local). | P10-03 | pending | pending | Owning parent/phase gates unchanged |
| [L460](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-03i private studio brief evidence: genuine RED2→focus2/types/Django clean/original studio1 accepted; full … | P10-03i | pending | pending | Owning parent/phase gates unchanged |
| [L461](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-03j private source status: genuine RED2→focus2/types/parent producer-lifecycle criteria accepted; full fro… | P10-03j | pending | pending | Owning parent/phase gates unchanged |
| [L462](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-03k nullable original generation/approval references: new2/types/affected original2 pass, bounded Django c… | P10-03k | pending | pending | Owning parent/phase gates unchanged |
| [L463](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-03l aware dates/scalar publication pairs: genuine RED1→new2/types/parent serializer-model criteria accepte… | P10-03l | pending | pending | Owning parent/phase gates unchanged |
| [L464](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-03m positive inventory/history cursors: genuine RED1→focus1/types/parent producer-query criteria accepted;… | P10-03m | pending | pending | Owning parent/phase gates unchanged |
| [L465](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-03n literal manual report URLs: genuine RED1→focus1/parent missing-origin RED1→recovery1/types, original r… | P10-03n | pending | pending | Owning parent/phase gates unchanged |
| [L466](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-03o private source dates: genuine RED1→focus1/types/parent original producer-copy criteria accepted; full … | P10-03o | pending | pending | Owning parent/phase gates unchanged |
| [L467](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-03p catalogue dates: genuine RED1→focus1/types/parent actual summary criteria/current coherent private rea… | P10-03p | pending | pending | Owning parent/phase gates unchanged |
| [L468](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) Support blog, refresh, landing page, service page, social post/series, newsletter, description and custom cont… | P10-03 | pending | pending | Owning parent/phase gates unchanged |
| [L469](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-03h revision text: genuine RED1/PASS1→new2/types/parent producer criteria/affected3 pass; metadata-only in… | P10-03h | pending | pending | Owning parent/phase gates unchanged |
| [L470](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-03g manual publication inputs: genuine RangeError RED1→exact1/types/parent actual date/URL/approval criter… | P10-03g | pending | pending | Owning parent/phase gates unchanged |
| [L471](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-03f revision identities: genuine RED2→shared guard/new2/types/Django clean/affected4 pass; valid mixed his… | P10-03f | pending | pending | Owning parent/phase gates unchanged |
| [L472](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-03e source-brief choices: genuine RED1→exact1/types/parent producer/scope criteria, malformed provenance/r… | P10-03e | pending | pending | Owning parent/phase gates unchanged |
| [L473](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-03d Unicode human editor input: genuine native-cap RED1→exact1/types/parent producer criteria; full Python… | P10-03d | pending | pending | Owning parent/phase gates unchanged |
| [L474](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-03a/b/c native studio role/current-refresh, exact transition-key and stale-save/destruction recovery: owni… | P10-03a | pending | pending | Owning parent/phase gates unchanged |
| [L475](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) Implement draft, review, exact-reviewed human approval, manual publication-report and archive/reopen states (P… | P10-03 | pending | pending | Owning parent/phase gates unchanged |
| [L476](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) Add a private native-text editor separating research, brief, draft, sources, revision history and safe text co… | P10-03 | pending | pending | Owning parent/phase gates unchanged |
| [L477](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) Keep every generated section/title/metadata unverified and require exact stored source quotes plus human factu… | P10-04 | pending | pending | Owning parent/phase gates unchanged |
| [L478](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-04e scalar generation provenance/counters/cost/token readers: genuine RED1→new2/types/Jobs clean/affected3… | P10-04e | pending | pending | Owning parent/phase gates unchanged |
| [L479](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-04d studio request limits/model cap and explicit free opt-in: new2 RED→PASS/types/parent producer criteria… | P10-04d | pending | pending | Owning parent/phase gates unchanged |
| [L480](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-04c studio model/account catalogue scalar metadata: new2 RED→PASS/types/Jobs no findings; Unicode/null cap… | P10-04c | pending | pending | Owning parent/phase gates unchanged |
| [L481](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-04a/b current studio catalog/generation evidence recovery: scalar tier/account source/price boolean/curren… | P10-04a | pending | pending | Owning parent/phase gates unchanged |
| [L482](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) Generate separate unapproved native editorial social variants from exact-current approved content for LinkedIn… | P10-04 | pending | pending | Owning parent/phase gates unchanged |
| [L483](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) Keep publication manual-report or private JSON-export based initially (P10-03/P10-04; no remote publishing). | P10-03, P10-04 | pending | pending | Owning parent/phase gates unchanged |
| [L484](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) Link briefs and drafts to the exact selected intent/page mapping and action revisions so existing-page improve… | P10-02, P10-03 | pending | pending | Owning parent/phase gates unchanged |
| [L485](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-05d combined review evidence: active exact model32KiB ASCII-escaped source/intake ceiling/valid16KiB fixtu… | P10-05d | pending | pending | Owning parent/phase gates unchanged |
| [L486](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-05c review readers: genuine RED1→focus3/types/bounded Django source finding closed; raw Unicode replacemen… | P10-05c | pending | pending | Owning parent/phase gates unchanged |
| [L487](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-05b human command bounds: RED3→focus3/types/parent producer criteria/original human-uncertain-retry3 pass;… | P10-05b | pending | pending | Owning parent/phase gates unchanged |
| [L488](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) P10-05a Unicode exact lifecycle body: genuine RED1→focus1/types/parent Python-hash criteria/current human+pair… | P10-05a | pending | pending | Owning parent/phase gates unchanged |
| [L489](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) Add an actual saved-content inventory with original source/fact-review dates, responsible reviewers, independe… | P10-05 | pending | pending | Owning parent/phase gates unchanged |
| [L495](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) Record substantive human outdated/thin/overlap/service-change judgments and keep/refresh/consolidate/redirect/… | P10-05 | pending | pending | Owning parent/phase gates unchanged |
| [L496](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) Require explicit replacement and user-impact review before exact human approval of consolidation/redirect/reti… | P10-05 | pending | pending | Owning parent/phase gates unchanged |
| [L497](../TODO_ARCHIVE_2026-10-10.md#phase-10-research-and-content) Support independently authorized cross-project native-text comparison without copying drafts, genuine human lo… | P10-05 | pending | pending | Owning parent/phase gates unchanged |
| [L506](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Restore D320/P11-01v original root capture actual private-byte readback: owning12/89.841s+affected49 PostgreSQ… | P11-01v | pending | pending | Owning parent/phase gates unchanged |
| [L507](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D321/P11-01w separately named once-only private schema-root crawl job/positive1 competitor_sou… | P11-01w | pending | pending | Owning parent/phase gates unchanged |
| [L508](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Complete D321/P11-01x exact separately budgeted private/native schema consumers/frozen source/null-empty lexic… | P11-01x | pending | pending | Owning parent/phase gates unchanged |
| [L509](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D327/P11-01y pure original static link category counts/strict byte-date-integrity/no-base URI/… | P11-01y | pending | pending | Owning parent/phase gates unchanged |
| [L510](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D328/P11-01z separately versioned protected original link-root producer over unchanged c/n tra… | P11-01z | pending | pending | Owning parent/phase gates unchanged |
| [L511](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D329/P11-01aa separately named private once-only link-root/crawl/positive1 job over checked th… | P11-01aa | pending | pending | Owning parent/phase gates unchanged |
| [L512](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Complete D330/P11-01ab independently budgeted fixed private/native original count-only link consumers/frozen c… | P11-01ab | pending | pending | Owning parent/phase gates unchanged |
| [L513](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D331/P11-01ac read-only exact selected non-root same-origin competitor URL/current complete a … | P11-01ac, P11-02, P11-03 | pending | pending | SERP provider selection; Commercial data justification |
| [L514](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D332/P11-01ad fixed protected original exact selected competitor page metadata producer over e… | P11-01ad | pending | pending | Owning parent/phase gates unchanged |
| [L515](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D333/P11-01ae fixed private selected-page once-only job over original lifecycle/models; exact … | P11-01ae | pending | pending | Owning parent/phase gates unchanged |
| [L516](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D334/P11-01af fixed private exact competitor-page API/static native commands/four independent … | P11-01af | pending | pending | Owning parent/phase gates unchanged |
| [L517](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Verify/fix D335/P11-01ag final second saved-pair source read cancelling first original: genuine private compar… | P11-01ag | pending | pending | Owning parent/phase gates unchanged |
| [L518](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D336/P11-01ah read-only same-exact-URI original selected-page comparisons after ag acceptance;… | P11-01ah | pending | pending | Owning parent/phase gates unchanged |
| [L519](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D337/P11-01ai full fixed private/native same-URI selected-page comparison consumers: GET-only … | P11-01ai | pending | pending | Owning parent/phase gates unchanged |
| [L520](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D338/P11-01aj read-only original schema-root lexical label pairs over current shared kernel: a… | P11-01aj | pending | pending | Owning parent/phase gates unchanged |
| [L521](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D339/P11-01ak fixed GET-only private/native original schema-root comparisons: existing schema … | P11-01ak | pending | pending | Owning parent/phase gates unchanged |
| [L522](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D340/P11-01al read-only original link-root category pairs: protected saved same-source origina… | P11-01al | pending | pending | Owning parent/phase gates unchanged |
| [L523](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D341/P11-01am full fixed GET-only private/native original link-root comparisons/existing link … | P11-01am | pending | pending | Owning parent/phase gates unchanged |
| [L524](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D342/P11-01an pure original static heading text/order prerequisite: complete original byte/dat… | P11-01an | pending | pending | Owning parent/phase gates unchanged |
| [L525](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D343/P11-01ao fixed protected exact selected-page heading producer over current page binding/t… | P11-01ao | pending | pending | Owning parent/phase gates unchanged |
| [L526](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D344/D345/P11-01ap fifth fixed once-only private selected-page heading family: exact URL/three… | P11-01ap | pending | pending | Owning parent/phase gates unchanged |
| [L527](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D346/P11-01aq complete fixed private/native selected-page headings: four independent budgets/e… | P11-01aq | pending | pending | Owning parent/phase gates unchanged |
| [L528](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D347/P11-01ar pure read-only saved original same-URI heading pairs: two genuine private origin… | P11-01ar | pending | pending | Owning parent/phase gates unchanged |
| [L529](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D348/P11-01as complete fixed private/native original heading pair GET/existing independent rea… | P11-01as | pending | pending | Owning parent/phase gates unchanged |
| [L530](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D349/P11-01at pure original same-origin static destination-reference inventory: reuse strict o… | P11-01at | pending | pending | Owning parent/phase gates unchanged |
| [L531](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D350/P11-01au protected exact selected-page destination-reference producer over original _col… | P11-01au | pending | pending | Owning parent/phase gates unchanged |
| [L532](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D351/P11-01av sixth fixed private original selected-page reference job over current once-only … | P11-01av | pending | pending | Owning parent/phase gates unchanged |
| [L533](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D352/P11-01aw complete fixed private/native selected-page reference commands/four independent … | P11-01aw | pending | pending | Owning parent/phase gates unchanged |
| [L534](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D353/P11-01ax pure saved original same-URI reference pair: exact two genuine private originals… | P11-01ax | pending | pending | Owning parent/phase gates unchanged |
| [L535](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D354/P11-01ay complete fixed saved original reference-pair GET/native consumers: existing refe… | P11-01ay | pending | pending | Owning parent/phase gates unchanged |
| [L536](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D355/P11-01az unregistered separately permissioned original saved heading-pair AI input/indexe… | P11-01az | pending | pending | Owning parent/phase gates unchanged |
| [L537](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D356/P11-01ba fixed read-only heading-pair model/account/budget selection using az original so… | P11-01ba | pending | pending | Owning parent/phase gates unchanged |
| [L538](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D357/P11-01bb once-only private original heading-pair synthesis over accepted source/model/ind… | P11-01bb | pending | pending | Owning parent/phase gates unchanged |
| [L539](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D358/P11-01bc complete fixed private/native original heading synthesis using original source-m… | P11-01bc | pending | pending | Owning parent/phase gates unchanged |
| [L540](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D359/P11-01bd pure bounded original publication/update declaration source; preserve original b… | P11-01bd | pending | pending | Owning parent/phase gates unchanged |
| [L541](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D360/P11-01be protected exact selected-page article-date declarations using existing current s… | P11-01be | pending | pending | Owning parent/phase gates unchanged |
| [L542](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D361/P11-01bf once-only private exact-page article-date declarations/positive1 unit/committed … | P11-01bf | pending | pending | Owning parent/phase gates unchanged |
| [L543](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Complete D362/P11-01bg locally2026-10-08: bg/D362 complete local fixed date consumers accepted effective API8 … | P11-01bg | pending | pending | Owning parent/phase gates unchanged |
| [L545](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Complete D363/P11-01bh locally2026-10-08: bh/D363 read-only original same-URI date declarations accepted effec… | P11-01bh | pending | pending | Owning parent/phase gates unchanged |
| [L547](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Complete D364/P11-01bi locally2026-10-08: bi/D364 complete fixed private/native original Date pairs accepted A… | P11-01bi | pending | pending | Owning parent/phase gates unchanged |
| [L549](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Complete D365/P11-01bj locally2026-10-08: bj/D365 pure exact-URI Lighthouse source accepted pure6/0.062s51309+… | P11-01bj | pending | pending | Owning parent/phase gates unchanged |
| [L551](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Complete D366/P11-01bk locally2026-10-08: bk/D366 current read-only Lighthouse permission-device source accept… | P11-01bk | pending | pending | Owning parent/phase gates unchanged |
| [L553](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Complete D367/P11-01bl locally2026-10-08: bl/D367 read-only Lighthouse credential preparation accepted effecti… | P11-01bl | pending | pending | Owning parent/phase gates unchanged |
| [L555](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Complete D368/P11-01bm locally2026-10-08: bm/D368 protected fixed PSI transport accepted owning8/0.189s81275 (… | P11-01bm | pending | pending | Owning parent/phase gates unchanged |
| [L557](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Complete D369/P11-01bn locally2026-10-08: bn/D369 protected full current Lighthouse producer accepted effectiv… | P11-01bn | pending | pending | Owning parent/phase gates unchanged |
| [L559](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Complete D370/P11-01bo locally2026-10-08: bo/D370 once-only private Lighthouse audit accepted effective own13+… | P11-01bo | pending | pending | Owning parent/phase gates unchanged |
| [L561](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Complete D371/P11-01bp locally2026-10-08: bp/D371 complete fixed private/native Lighthouse consumers accepted … | P11-01bp | pending | pending | Owning parent/phase gates unchanged |
| [L563](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Complete D372/P11-01bq locally2026-10-08: bq/D372 original saved Lighthouse pair source accepted owning8/503.4… | P11-01bq | pending | pending | Owning parent/phase gates unchanged |
| [L565](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Complete D373/P11-01br locally2026-10-08: br/D373 complete fixed Lighthouse pair consumers accepted effective … | P11-01br | pending | pending | Owning parent/phase gates unchanged |
| [L567](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement/check D374/P11-01bs original single-heading topic-hypothesis source (owning7/affected24/runtime/priv… | P11-01bs | pending | pending | Owning parent/phase gates unchanged |
| [L568](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D377/P11-01bt original single-heading model/account/budget preparation: focused5/old positives2 and actual-sou… | P11-01bt | pending | pending | Owning parent/phase gates unchanged |
| [L569](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D378/P11-01bu once-only private topic job: focused6/old positives2, actual-source Jobs review and genuine CUST… | P11-01bu | pending | pending | Owning parent/phase gates unchanged |
| [L570](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D380/P11-01bv complete single-heading topic API/native consumers: effective API6/new native28/affected compone… | P11-01bv | pending | pending | Owning parent/phase gates unchanged |
| [L571](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D382/P11-01bw two saved-page static reference structure: genuine focused6/78.086s and actual-source SEO review… | P11-01bw | pending | pending | Owning parent/phase gates unchanged |
| [L572](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D383/P11-01bx fixed private/native two saved-page reference consumers: selected after bw focused evidence; API… | P11-01bx | pending | pending | Owning parent/phase gates unchanged |
| [L573](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D384/P11-01by literal saved topic-hypothesis comparison: selected after complete focused reference feature acc… | P11-01by | pending | pending | Owning parent/phase gates unchanged |
| [L574](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D386/P11-01ca fixed private/native saved-topic comparison consumers selected BEFORE edits over by/bz focused e… | P11-01ca | pending | pending | Owning parent/phase gates unchanged |
| [L575](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D385/P11-01bz shared private synthesis last-reader recovery: selected before edits; genuine red1/five losses, … | P11-01bz | pending | pending | Owning parent/phase gates unchanged |
| [L577](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Restore D319/P11-01u private synthesis API final-metadata authority locally2026-10-07: red16/406.099s→owning6/… | P11-01u | pending | pending | Owning parent/phase gates unchanged |
| [L579](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Restore D318/P11-01t original private synthesis final-own-metadata authority locally2026-10-07: red21/671.715s… | P11-01t | pending | pending | Owning parent/phase gates unchanged |
| [L581](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Restore D317/P11-01s configured-selection final-row original-pair authority locally2026-10-07: red7→owning5/75… | P11-01s | pending | pending | Owning parent/phase gates unchanged |
| [L583](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Restore D316/P11-01r original synthesis-source final-pair-pins authority locally2026-10-07: red7→owning9/60.59… | P11-01r | pending | pending | Owning parent/phase gates unchanged |
| [L585](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Restore D315/P11-01q original private root/pair API last-metadata authority locally2026-10-07: red10→owning4/4… | P11-01q | pending | pending | Owning parent/phase gates unchanged |
| [L587](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Restore D314/P11-01p original comparison last-pair-metadata authority locally2026-10-07: red6→owning5/50.081s→… | P11-01p | pending | pending | Owning parent/phase gates unchanged |
| [L589](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Restore D313/P11-01o original competitor core last-metadata delivery/capture boundaries locally2026-10-07: red… | P11-01o | pending | pending | Owning parent/phase gates unchanged |
| [L591](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Complete D312/P11-01n separately versioned protected schema-root producer locally2026-10-07: definitive56 Post… | P11-01n | pending | pending | Owning parent/phase gates unchanged |
| [L593](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Complete D311/P11-01m pure original-static bounded JSON-LD type projection locally2026-10-07: focused12/owning… | P11-01m | pending | pending | Owning parent/phase gates unchanged |
| [L595](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Complete D283/P11-01j opt-in owning provider transfer checkpoints locally2026-10-06: owning13/affected74 Postg… | P11-01j | pending | pending | Owning parent/phase gates unchanged |
| [L596](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Complete D284–D286/P11-01k–l compact original-pair/model-budget selection, positive-unit once-only private syn… | P11-01k | pending | pending | Owning parent/phase gates unchanged |
| [L597](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Check D284/k compact selection slice locally2026-10-06: four owning/final affected47 PostgreSQL231.161s/system… | P11-01k | pending | pending | Owning parent/phase gates unchanged |
| [L598](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Complete D285/k once-only configured synthesis/private lifecycle locally2026-10-06: owning9 PostgreSQL1101.063… | P11-01k | pending | pending | Owning parent/phase gates unchanged |
| [L599](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Check D286/l fixed private synthesis API slice locally2026-10-06: five owning within affected40 PostgreSQL748.… | P11-01l | pending | pending | Owning parent/phase gates unchanged |
| [L600](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Check D286/l deliberate native synthesis slice locally2026-10-06: competitor70/full514 Angular37 files/product… | P11-01l | pending | pending | Owning parent/phase gates unchanged |
| [L601](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Complete D286/P11-01l locally2026-10-06: SAME single marked h–l review no actionable findings/no unread depend… | P11-01l | pending | pending | Owning parent/phase gates unchanged |
| [L603](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Complete D274/P11-01a current explicitly selected competitor source prerequisite: owning8 PostgreSQL2.009s/aff… | P11-01a, P11-01 | pending | pending | Real source grants |
| [L605](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Allow manual competitor creation and approval. | P11-01 | pending | pending | Real source grants |
| [L606](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Complete D275/P11-01b pure minimized original static metadata prerequisite: six owning/affected51 PostgreSQL16… | P11-01b | pending | pending | Owning parent/phase gates unchanged |
| [L607](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Select a compliant SERP API provider. | P11-02 | implemented; DataForSEO configurable, untested | deferred by D437 | SERP provider selection |
| [L608](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Add public competitor crawling with strict rate limits. | P11-01 | pending | pending | Real source grants |
| [L609](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Complete D277/P11-01d separate once-only positive1-unit competitor root JobRun/private minimized CUSTOMER evid… | P11-01d, P11-01e | pending | pending | Owning parent/phase gates unchanged |
| [L610](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Complete D278/P11-01e private competitor-root delivery locally2026-10-06: competitor native24/full468 Angular3… | P11-01e | pending | pending | Owning parent/phase gates unchanged |
| [L611](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Complete D276/P11-01c protected original single-root producer locally: thirteen own/focused37, broad147 actual… | P11-01c | pending | pending | Owning parent/phase gates unchanged |
| [L614](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Compare topic coverage, public structure, metadata, schema, links, freshness, and result formats. | P11-01 | pending | pending | Real source grants |
| [L617](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Add estimated keyword, backlink, and authority providers only when commercially justified. | P11-03 | blocked | blocked | Commercial data justification |
| [L618](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Complete D280/P11-01g exact private original competitor-pair delivery locally2026-10-06: native40/full484 Angu… | P11-01g | pending | pending | Owning parent/phase gates unchanged |
| [L619](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Complete D281/P11-01h original static pair synthesis-source prerequisite locally2026-10-06: owning4/affected39… | P11-01h | pending | pending | Owning parent/phase gates unchanged |
| [L620](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Complete D282/P11-01i bounded closed cited-output schema/validator locally2026-10-06: owning8/affected h-f-b-r… | P11-01i | pending | pending | Owning parent/phase gates unchanged |
| [L621](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Add keyword discovery and search-volume/difficulty data with provider definitions, market scope, and freshness… | P11-03 | pending | pending | Commercial data justification |
| [L622](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Add scheduled rank tracking by engine, keyword, location, language, and device through a SERP API; distinguish… | P11-02 | implemented; DataForSEO configurable, untested | deferred by D437 | SERP provider selection |
| [L623](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Add inbound backlink/referring-domain and anchor analysis through an external index, preserving coverage limit… | P11-03 | pending | pending | Commercial data justification |
| [L624](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Add optional provider-based competitor traffic estimates; do not infer actual traffic from public page crawls. | P11-03 | blocked | blocked | Commercial data justification |
| [L625](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Store dated crawl/provider/rank snapshots for historical comparisons and supported backfills; show collection … | P11-01, P11-02, P11-03 | pending | pending | Real source grants; SERP provider selection; Commercial data justification |
| [L626](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Label third-party traffic/volume estimates and authority/difficulty scores appropriately; disclose the coverag… | P11-01, P11-02, P11-03 | pending | pending | Real source grants; SERP provider selection; Commercial data justification |
| [L628](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Distinguish measured analytics, observed crawl/SERP results, provider estimates/scores, and unavailable data t… | P11-01, P11-02, P11-03 | pending | pending | Real source grants; SERP provider selection; Commercial data justification |
| [L640](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Add selected authorized GBP profile/review reading and independent owned-website human feedback/reply workflow… | P11-05a | pending | pending | Real source grants |
| [L641](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Implement P11-05a's separate authorized GBP consent/profile/review reader and response-only private lifecycle … | P11-05a | pending | pending | Real source grants |
| [L642](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Add selected manual Google organic-link own-website observations with actual requested business location/langu… | P11-05c | pending | pending | Real source grants |
| [L643](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Identify relevant partnerships, unlinked mentions, broken inbound destinations, lost-link candidates, and digi… | P11-04 | pending | pending | Human outreach/action |
| [L645](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Verify authority candidates and retain evidence, owner, proposed action, and disposition; use human-reviewed d… | P11-04 | pending | pending | Human outreach/action |
| [L659](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Add optional bounded authorized server/CDN JSONL log imports after core indexation diagnostics, retaining only… | P11-06 | pending | pending | Owning parent/phase gates unchanged |
| [L660](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) Report UA-only unverified bot labels, partial request frequency/status/UTC last seen and existing-inventory-fa… | P11-06 | pending | pending | Owning parent/phase gates unchanged |
| [L662](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D387/P11-01cb original observation/reference terminal-reader recovery: selected before edits after ca coherent… | P11-01cb | pending | pending | Owning parent/phase gates unchanged |
| [L663](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D388/P11-01cc dated static/Lighthouse pair terminal-reader recovery selected before edits after cb focus9/Jobs… | P11-01cc | pending | pending | Owning parent/phase gates unchanged |
| [L664](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D389/P11-01cd original AI source-packet terminal-reader recovery selected before edits after cb–cc coherent18/… | P11-01cd | pending | pending | Owning parent/phase gates unchanged |
| [L665](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D390/P11-01ce shared model-preparation terminal-reader recovery selected before edits after cd focus5/Jobs; ge… | P11-01ce | pending | pending | Owning parent/phase gates unchanged |
| [L666](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D391/P11-01cf literal saved destination inventory source selected before edits after stable recovery; exact fi… | P11-01cf | pending | pending | Owning parent/phase gates unchanged |
| [L667](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D392/P11-01cg fixed inventory focus/API6/native395/types/ONE marked source reviews/radio semantic recovery/coh… | P11-01cg | pending | pending | Owning parent/phase gates unchanged |
| [L668](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D393/P11-01ch pure content-element parser/tests0664/AST2/owning6+improved direct encoder-cap1 PASS; bounded SE… | P11-01ch | pending | pending | Owning parent/phase gates unchanged |
| [L670](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D394/P11-01ci fixed unregistered protected content-element producer0664/AST2/genuine injected owning6/16.494s … | P11-01ci | pending | pending | Owning parent/phase gates unchanged |
| [L672](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D395/P11-01cj separately registered private content-element lifecycle/test0664/AST7 written; initial method-le… | P11-01cj | pending | pending | Owning parent/phase gates unchanged |
| [L674](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D396/P11-01ck fixed API effective6/app type PASS; native source-tests/spec20076/effective15 PASS (14 initial+e… | P11-01ck | pending | pending | Owning parent/phase gates unchanged |
| [L676](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D397/P11-01cl original static content-element pair source: owning7/157.159s/SEO-Jobs/current consumers/coheren… | P11-01cl | pending | pending | Owning parent/phase gates unchanged |
| [L678](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D398/P11-01cm fixed private content-element pair consumers: current API7/native19/types/ONE marked reviews/sha… | P11-01cm | pending | pending | Owning parent/phase gates unchanged |
| [L680](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D399/P11-01cn actual final private-reader recovery: genuine red1/FAIL4→TWO-line shared repair/AST2/focus2/51.2… | P11-01cn | pending | pending | Owning parent/phase gates unchanged |
| [L681](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D400/P11-01co final capture-validation metadata: red1/14.858s/FAIL4→ONE-line guard/AST2/focus2/21.061s/Jobs/co… | P11-01co | pending | pending | Owning parent/phase gates unchanged |
| [L682](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D401/P11-01cp original two-page static element source: source6/AST3/SEO-Jobs/full cq consumers/ONE marked gate… | P11-01cp | pending | pending | Owning parent/phase gates unchanged |
| [L683](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D402/P11-01cq complete private two-page static element consumers: API8/sensitive guard recovery3+1/native16/ta… | P11-01cq | pending | pending | Owning parent/phase gates unchanged |
| [L684](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D403/P11-01cr pure date-literal candidates: pure6/.070s/AST2/SEO plus complete ct consumers/current source-coh… | P11-01cr | pending | pending | Owning parent/phase gates unchanged |
| [L685](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D404/P11-01cs current private Date candidate source: effective6/AST2/Jobs plus complete ct gate/coherent-runti… | P11-01cs | pending | pending | Owning parent/phase gates unchanged |
| [L686](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D405/P11-01ct complete saved-Date candidate consumers: API5/50.812s/effective newnative14/types/ONE marked Sec… | P11-01ct | pending | pending | Owning parent/phase gates unchanged |
| [L687](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D406/P11-01cu original dated Date-candidate arithmetic source: genuine source6/123.186s/AST2/actual SEO-Jobs a… | P11-01cu | pending | pending | Owning parent/phase gates unchanged |
| [L688](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D407/P11-01cv complete private Date interval consumers: effectiveAPI6/native14/types/ONE complete Security-Ang… | P11-01cv | pending | pending | Owning parent/phase gates unchanged |
| [L689](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D408/P11-01cw two-page literal heading counts: source6/114.976s/AST3/oldkernel2/28.269s/actual SEO-Jobs accept… | P11-01cw | pending | pending | Owning parent/phase gates unchanged |
| [L690](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D409/P11-01cx complete private two-page heading counts selected before edits: fixed Heading GET/budget/current… | P11-01cx | pending | pending | Owning parent/phase gates unchanged |
| [L692](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D410/P11-01cy selected saved-topic source/API actual terminal original metadata/pin authority discovery with g… | P11-01cy | pending | pending | Owning parent/phase gates unchanged |
| [L694](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D411/P11-01cz selected DEBUG=False genuine Topic API healthy/read-latency-query count and former terminal mode… | P11-01cz | pending | pending | Owning parent/phase gates unchanged |
| [L696](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D412/P11-01da fixed numeric trace1/125.075s PASS/healthy34.235s27,714SQL/16synthesis-32Heading reads/model-rev… | P11-01da | pending | pending | Owning parent/phase gates unchanged |
| [L698](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D413/P11-01db genuine source1+sensitive6/ONE complete marked Security-Jobs-parent/19,794SQL≤22,000/healthy25.2… | P11-01db | pending | pending | Owning parent/phase gates unchanged |
| [L699](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D414/P11-01dc app-ready: prior frontend991/build/static13/audit0 (before current native repairs)/deployment-re… | P11-01dc, P13-05a | pending | pending | Owning parent/phase gates unchanged |
| [L703](../TODO_ARCHIVE_2026-10-10.md#phase-11-competitor-intelligence) D419/P11-01dd joined authority focus/ONE marked Security-Django-parent/coherent/reload-runtime/private43/nativ… | P11-01dd | pending | pending | Owning parent/phase gates unchanged |
| [L707](../TODO_ARCHIVE_2026-10-10.md#phase-11a-bounded-ai-visibility) P11A-02sb1 current native human-rate consistency recovery: 0/1→100.00 genuine red, original source half-even/c… | P11A-02sb1 | pending | pending | Owning parent/phase gates unchanged |
| [L708](../TODO_ARCHIVE_2026-10-10.md#phase-11a-bounded-ai-visibility) P11A-02sb2 human report scalar/canonical UUID recovery: genuine new RED2→list/history and uncertain-ACK/indepe… | P11A-02sb2 | pending | pending | Owning parent/phase gates unchanged |
| [L717](../TODO_ARCHIVE_2026-10-10.md#phase-11a-bounded-ai-visibility) Select initial supported platforms/collection surfaces and verify provider terms, capabilities, evidence reten… | P11A-01, P11A-05 | pending | pending | Provider terms/cost/access; AI live/legal readiness |
| [L718](../TODO_ARCHIVE_2026-10-10.md#phase-11a-bounded-ai-visibility) Create project/market/language-scoped immutable human-reviewed prompt sets with separate neutral discovery/bra… | P11A-01, P11A-02 | pending | pending | Provider terms/cost/access |
| [L719](../TODO_ARCHIVE_2026-10-10.md#phase-11a-bounded-ai-visibility) Locally implement bounded D127 native repeats and D128 independently permitted human input with exact prompt/s… | P11A-02s | pending | pending | Provider terms/cost/access |
| [L720](../TODO_ARCHIVE_2026-10-10.md#phase-11a-bounded-ai-visibility) Complete D127 separate opt-in native repeats (P11A-02sa): paused-first owner/admin enable, frozen source/model… | P11A-02sa | pending | pending | Owning parent/phase gates unchanged |
| [L721](../TODO_ARCHIVE_2026-10-10.md#phase-11a-bounded-ai-visibility) Complete selected D128 clearly labeled customer-reported human answer workflow/current authority/private nativ… | P11A-02sb, P11A-02s | pending | pending | Provider terms/cost/access |
| [L722](../TODO_ARCHIVE_2026-10-10.md#phase-11a-bounded-ai-visibility) Complete initial D120 manual native API-text collection with >=24-hour per-set/prompt cooldown, one attempt/un… | P11A-02, P11A-02s | pending | pending | Provider terms/cost/access |
| [L723](../TODO_ARCHIVE_2026-10-10.md#phase-11a-bounded-ai-visibility) Add P11A-03 exact Unicode-codepoint brand/domain/configured-competitor candidates and human alias/span correct… | P11A-03 | pending | pending | Supported fact/citation surface |
| [L724](../TODO_ARCHIVE_2026-10-10.md#phase-11a-bounded-ai-visibility) Compute P11A-03 deterministic sampled mention rates with explicit eligible IDs/numerators/denominators, neutra… | P11A-03 | pending | pending | Supported fact/citation surface |
| [L725](../TODO_ARCHIVE_2026-10-10.md#phase-11a-bounded-ai-visibility) Show P11A-04a like-for-like private keyset history with exact prompt/model/account/token/entity-context groups… | P11A-04a | pending | pending | Owning parent/phase gates unchanged |
| [L726](../TODO_ARCHIVE_2026-10-10.md#phase-11a-bounded-ai-visibility) Classify identifiable AI referrals in authorized analytics with versioned source rules and attribution/coverag… | P11A-04r, P06-05, P11A-04 | pending | pending | Exact-origin capability; Exact-origin capability; Real source grants |
| [L727](../TODO_ARCHIVE_2026-10-10.md#phase-11a-bounded-ai-visibility) Add P11A-04a crawler/content/entity/source discoverability proposals with exact stored diagnostics/findings, h… | P11A-04a | pending | pending | Owning parent/phase gates unchanged |
| [L729](../TODO_ARCHIVE_2026-10-10.md#phase-11a-bounded-ai-visibility) Gate AI-visibility marketing/release on actual platform coverage, evidence, failure states, budgets, and hones… | P11A-05 | pending | pending | AI live/legal readiness |
| [L730](../TODO_ARCHIVE_2026-10-10.md#phase-11a-bounded-ai-visibility) Complete P11A-05's supported D120 **local** integrated journey and declared-surface/public-claim guard prepara… | P11A-05 | pending | pending | AI live/legal readiness |
| [L734](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D310 original-chain human judgment delivery locally2026-10-07: ci73 backend/cj33 private API/ck focus… | P12-02ci, P12-02cj, P12-02ck | pending | pending | Owning parent/phase gates unchanged |
| [L735](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D310/P12-02cj API-only2026-10-07: genuine owning7 plus definitive fresh test-DB original APIs/config2… | P12-02cj | pending | pending | Owning parent/phase gates unchanged |
| [L736](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D310/P12-02ci backend-only exact-source original-chain immutable judgment2026-10-06: owning8/original… | P12-02ci | pending | pending | Owning parent/phase gates unchanged |
| [L738](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D309/P12-02ch original shared human-decision final-row authority recovery2026-10-06: genuine32 red→12… | P12-02ch | pending | pending | Owning parent/phase gates unchanged |
| [L740](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D308/P12-02cg fifth fixed genuine current chain Finding review-source prerequisite2026-10-06: owning8… | P12-02cg | pending | pending | Owning parent/phase gates unchanged |
| [L742](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D307/P12-02cf shared original four-family human-review source final-authority recovery2026-10-06: gen… | P12-02cf | pending | pending | Owning parent/phase gates unchanged |
| [L744](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D305/P12-02cc genuine chain Finding persistence/current reader2026-10-06:190 distinct PostgreSQL owni… | P12-02cc | pending | pending | Owning parent/phase gates unchanged |
| [L745](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D306/P12-02cd fixed private chain Finding API2026-10-06: owning6/444.962s+affected35/666.437s =41 dis… | P12-02cd | pending | pending | Owning parent/phase gates unchanged |
| [L746](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D306/P12-02ce deliberate native exact original chain fact/source inspector/full clearing2026-10-06: f… | P12-02ce | pending | pending | Owning parent/phase gates unchanged |
| [L748](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D303/P12-02bz API-only fixed current chain candidate GET2026-10-06: definitive39 PostgreSQL351.598s/s… | P12-02bz | pending | pending | Owning parent/phase gates unchanged |
| [L749](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D303/P12-02ca original-chain candidate native inspector2026-10-06: focused166/full554 Angular37 files… | P12-02ca | pending | pending | Owning parent/phase gates unchanged |
| [L750](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D304/P12-02cb pure compact original selected-chain Finding recipes2026-10-06: owning5/9.061s+affected… | P12-02cb | pending | pending | Owning parent/phase gates unchanged |
| [L752](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D302/P12-02by current private original chain candidate source2026-10-06: owning4/48.698s+affected ori… | P12-02by | pending | pending | Owning parent/phase gates unchanged |
| [L754](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D301/P12-02bx pure original selected-chain review candidates2026-10-06: owning5/7.591s+affected origi… | P12-02bx | pending | pending | Owning parent/phase gates unchanged |
| [L756](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D292/P12-02bl exact intended shared passive rows/preserved exception pins locally2026-10-06: red2/six… | P12-02bl | pending | pending | Owning parent/phase gates unchanged |
| [L757](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D293/P12-02bm independent HTTP once-only private audit collector locally2026-10-06: owning8/64.911s/a… | P12-02bm | pending | pending | Owning parent/phase gates unchanged |
| [L758](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D293/P12-02bn separate fixed private/API/native HTTP commands: native138/full526 Angular/build-static… | P12-02bn | pending | pending | Owning parent/phase gates unchanged |
| [L759](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D294/P12-02bo read-only independent original HTTP+HTTPS response pair: owning5/final48 PostgreSQL310.… | P12-02bo | pending | pending | Owning parent/phase gates unchanged |
| [L760](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete P12-02bp deliberate private/native original HTTP+HTTPS pair delivery: passive147/full535 Angular/buil… | P12-02bp | pending | pending | Owning parent/phase gates unchanged |
| [L761](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D295/P12-02bq shared current scoped metadata-before-pin repair across original candidate/Finding/huma… | P12-02bq | pending | pending | Owning parent/phase gates unchanged |
| [L762](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Check bp API-only locally2026-10-06: owning5/final39 PostgreSQL302.636s/system-current-no drift/loaded fixed b… | P12-02bp | pending | pending | Owning parent/phase gates unchanged |
| [L763](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Check bn native slice locally2026-10-06: passive138/full526 Angular37 files/production17.601s/four prerenders/… | P12-02bn | pending | pending | Owning parent/phase gates unchanged |
| [L764](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Check D293/bn API-only slice locally2026-10-06: owning5/36.251s/prior36 actual affected passes/final five coll… | P12-02bn | pending | pending | Owning parent/phase gates unchanged |
| [L766](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D291/P12-02bk shared passive final private-byte readback and post-source/final-metadata commercial ex… | P12-02bk | pending | pending | Owning parent/phase gates unchanged |
| [L768](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D288/P12-02bh independent exact verified HTTP Location source: six owning/final43 PostgreSQL81.128s/s… | P12-02bh | pending | pending | Owning parent/phase gates unchanged |
| [L769](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D289/P12-02bi protected original HTTP-first-response transport: nine owning/shared150 PostgreSQL100.5… | P12-02bi | pending | pending | Owning parent/phase gates unchanged |
| [L770](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D290/P12-02bj strict pure original private8KiB HTTP Location evidence: six owning/initial31 PostgreSQ… | P12-02bj | pending | pending | Owning parent/phase gates unchanged |
| [L772](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D287/P12-02bg separate pure original HTTP response Location metadata prerequisite locally2026-10-06: … | P12-02bg | pending | pending | Owning parent/phase gates unchanged |
| [L774](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D251/P12-02ab genuine protected header JobRun Finding relation/private explicit idempotent materializ… | P12-02ab | pending | pending | Owning parent/phase gates unchanged |
| [L775](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D252/P12-02ac/ad fixed private original-digest-bound header Finding GET/CSRF POST and deliberate stri… | P12-02ac | pending | pending | Owning parent/phase gates unchanged |
| [L776](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) P12-02ac API-only: six initial owning plus corrected role fixture/final affected42 PostgreSQL439.623s/system-c… | P12-02ac | pending | pending | Owning parent/phase gates unchanged |
| [L777](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D253/P12-02ae pure original literal HTTP resource-reference review candidate: owning5/focused2… | P12-02ae | pending | pending | Owning parent/phase gates unchanged |
| [L778](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D254/P12-02af current private original resource-candidate source: owning4/focused13/refined or… | P12-02af | pending | pending | Owning parent/phase gates unchanged |
| [L779](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D255/P12-02ag/ah fixed exact private resource-candidate GET/current final fence and deliberate strict… | P12-02ag | pending | pending | Owning parent/phase gates unchanged |
| [L780](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) P12-02ag API-only: final owning/four APIs/header candidates-Finding commands/af44 PostgreSQL655.778s/system-cu… | P12-02ag | pending | pending | Owning parent/phase gates unchanged |
| [L781](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D256/P12-02ai compact original resource Finding recipe prerequisite: owning5/focused16 Postgre… | P12-02ai | pending | pending | Owning parent/phase gates unchanged |
| [L782](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D257/P12-02aj genuine protected original resource Finding relation/SQL one-source/org-first materiali… | P12-02aj | pending | pending | Owning parent/phase gates unchanged |
| [L783](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D258/P12-02ak/al exact private resource Finding original-SHA GET/POST/independent budgets/full post-s… | P12-02ak | pending | pending | Owning parent/phase gates unchanged |
| [L784](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D259/P12-02am pure original TLS date-window/actual TLSv1-or-v1.1 review candidates, independen… | P12-02am | pending | pending | Owning parent/phase gates unchanged |
| [L785](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D260/P12-02an fixed current private original TLS candidate source/full original metadata-cance… | P12-02an | pending | pending | Owning parent/phase gates unchanged |
| [L786](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D261/P12-02ao/ap exact private TLS candidate GET/original maintained read budget/strict native origin… | P12-02ao | pending | pending | Owning parent/phase gates unchanged |
| [L787](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D262/P12-02aq compact original TLS Finding recipes: owning5/focused20 PostgreSQL11.054s/final … | P12-02aq | pending | pending | Owning parent/phase gates unchanged |
| [L788](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D263/P12-02ar genuine protected TLS JobRun Finding lifecycle: owning40/ordinary94/CUSTOMER55/final97 … | P12-02ar | pending | pending | Owning parent/phase gates unchanged |
| [L789](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D264/P12-02as fixed TLS Finding GET/CSRF SHA-only POST/independent budgets/full post-serialization ro… | P12-02as | pending | pending | Owning parent/phase gates unchanged |
| [L790](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D264/P12-02at deliberate native TLS Finding compact original date-version validation/fresh original s… | P12-02at | pending | pending | Owning parent/phase gates unchanged |
| [L791](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D265/P12-02au pure original HTTP-scheme Location-reference review candidate: owning5/focused26… | P12-02au | pending | pending | Owning parent/phase gates unchanged |
| [L792](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D266/P12-02av fixed current original Location-candidate source: owning4/focused17/final origin… | P12-02av | pending | pending | Owning parent/phase gates unchanged |
| [L793](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D267/P12-02aw exact original Location candidate GET/original maintained read budget: focused19/final … | P12-02aw | pending | pending | Owning parent/phase gates unchanged |
| [L794](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D267/P12-02ax deliberate native original Location candidate inspection: native85/full403 Angular-buil… | P12-02ax | pending | pending | Owning parent/phase gates unchanged |
| [L795](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D268/P12-02ay pure compact original Location Finding recipes: owning5/focused20/final original Locati… | P12-02ay | pending | pending | Owning parent/phase gates unchanged |
| [L796](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D269/P12-02az genuine protected original Location Finding lifecycle: owning16/four-family56/ordinary7… | P12-02az | pending | pending | Owning parent/phase gates unchanged |
| [L797](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D270/P12-02ba fixed private Location Finding GET/SHA-only POST/two independent budgets/full post-seri… | P12-02ba | pending | pending | Owning parent/phase gates unchanged |
| [L798](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D270/P12-02bb deliberate native original Location Finding current/save/reconcile: native93/full411 An… | P12-02bb | pending | pending | Owning parent/phase gates unchanged |
| [L799](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D271/P12-02bc exact private passive Finding human-review source: owning20 PostgreSQL297.926s/affected… | P12-02bc | pending | pending | Owning parent/phase gates unchanged |
| [L800](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D272/P12-02bd private source-bound human passive prioritization backend: final owning25 PostgreSQL137… | P12-02bd | pending | pending | Owning parent/phase gates unchanged |
| [L801](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D273/P12-02be exact private four-family human priority GET/CSRF POST/eight independent budgets/full o… | P12-02be | pending | pending | Owning parent/phase gates unchanged |
| [L802](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D273/P12-02bf deliberate native exact-Finding human judgment/optimistic correction/frozen source-revi… | P12-02bf | pending | pending | Owning parent/phase gates unchanged |
| [L804](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) P12-02ak API-only: focused18/refined owning7+header commands/two candidate APIs/four original APIs/af/resource… | P12-02ak | pending | pending | Owning parent/phase gates unchanged |
| [L806](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D248/P12-02x pure original header candidates: five owning/focused14/final collector-findings31… | P12-02x | pending | pending | Owning parent/phase gates unchanged |
| [L807](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D249/P12-02y current private candidate source: owning4/x5 focused9/final four APIs+collector-s… | P12-02y | pending | pending | Owning parent/phase gates unchanged |
| [L808](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D250/P12-02z-aa fixed private candidate GET/existing header-read budget and deliberate strict native … | P12-02z | pending | pending | Owning parent/phase gates unchanged |
| [L810](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D247/P12-02v positive1unit once-only manual Location collector: seven owning/focused36/final a… | P12-02v | pending | pending | Owning parent/phase gates unchanged |
| [L811](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D247/P12-02w fixed private/native independent Location consumers: API21/native33/full351 Angular-buil… | P12-02w | pending | pending | Owning parent/phase gates unchanged |
| [L813](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D246/P12-02u strict original8KiB private Location evidence: six owning/focused34 PostgreSQL27.… | P12-02u | pending | pending | Owning parent/phase gates unchanged |
| [L815](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D233/P12-02d positive1unit original-source-bound manual collector/private evidence/audit worke… | P12-02d | pending | pending | Owning parent/phase gates unchanged |
| [L816](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D233/P12-02e strict private/native explicit passive-header consumers: expanded API6/full focused21 Po… | P12-02e | pending | pending | Owning parent/phase gates unchanged |
| [L817](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D234/P12-02f pure transient original certificate GMT-date interpretation: six owning fixtures/… | P12-02f | pending | pending | Owning parent/phase gates unchanged |
| [L818](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D235/P12-02g separate exact-origin certificate_dates+negotiated_tls independent permission/cur… | P12-02g | pending | pending | Owning parent/phase gates unchanged |
| [L819](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D235/P12-02h protected handshake-only minimized dates/actual negotiated TLS-cipher/default hos… | P12-02h | pending | pending | Owning parent/phase gates unchanged |
| [L820](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D236/P12-02i strict original8KiB TLS evidence: initial owning4/affected32 PostgreSQL47.204s/fi… | P12-02i | pending | pending | Owning parent/phase gates unchanged |
| [L821](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D237/P12-02j once-only positive1unit manual TLS collector: TEN owning/affected145 PostgreSQL86… | P12-02j | pending | pending | Owning parent/phase gates unchanged |
| [L822](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D237/P12-02k strict private/native separate TLS consumers: focused21 PostgreSQL76.823s/native18/full3… | P12-02k | pending | pending | Owning parent/phase gates unchanged |
| [L824](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D232/P12-02c opt-in protected exact-HTTPS first-response minimized header transport: corrected… | P12-02c | pending | pending | Owning parent/phase gates unchanged |
| [L826](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Require project ownership verification for sensitive checks (P12-01/D082; initial exact-origin HTTP-file evide… | P12-01 | pending | pending | Verified ownership/scope |
| [L827](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D230/P12-02a pure bounded multi-value response-header/cookie-flag parser: owning5+existing sco… | P12-02a, P12-02 | pending | pending | Verified ownership/scope |
| [L828](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D231/P12-02b exact current D082-bound header source: owning4+original verifier/race15 PostgreS… | P12-02b | pending | pending | Owning parent/phase gates unchanged |
| [L829](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Check HTTPS and redirect behavior. | P12-02 | pending | pending | Verified ownership/scope |
| [L830](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D299/P12-02bu pure strict24KiB original minimized chain evidence: owning+original validators19… | P12-02bu | pending | pending | Owning parent/phase gates unchanged |
| [L831](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D298/P12-02bt protected opt-in header-only exact-target chain transport: owning18/11.804s/prot… | P12-02bt | pending | pending | Owning parent/phase gates unchanged |
| [L832](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D297/P12-02bs pure fresh exact-target Location resolver: owning+original parser20/0.154s/affec… | P12-02bs | pending | pending | Owning parent/phase gates unchanged |
| [L833](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D296/P12-02br read-only exact permitted redirect-chain source: owning4/11.715s+25 actual origi… | P12-02br | pending | pending | Owning parent/phase gates unchanged |
| [L834](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D243/P12-02r pure original bounded first-response Location metadata: owning6/final53 PostgreSQ… | P12-02r | pending | pending | Owning parent/phase gates unchanged |
| [L835](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D244/P12-02s independent current exact-URL/response_location source: owning4/original b-g-m-ve… | P12-02s | pending | pending | Owning parent/phase gates unchanged |
| [L836](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D245/P12-02t independent protected original first-response Location transport: owning7/focused… | P12-02t | pending | pending | Owning parent/phase gates unchanged |
| [L837](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Check final D243/r conservative raw URI-character/bracket grammar after t: final r/t/resource evidence/source/… | P12-02r, P12-02t | pending | pending | Owning parent/phase gates unchanged |
| [L838](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D242/P12-02p positive1unit once-only static resource collector: seven owning/focused29/definit… | P12-02p | pending | pending | Owning parent/phase gates unchanged |
| [L839](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D242/P12-02q fixed private/native independent resource consumers: focused21/native26/full344 Angular-… | P12-02q | pending | pending | Owning parent/phase gates unchanged |
| [L840](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D241/P12-02o strict original8KiB resource evidence: owning5/final affected38 PostgreSQL75.080s… | P12-02o | pending | pending | Owning parent/phase gates unchanged |
| [L841](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D240/P12-02n protected complete length-framed UTF-8 HTML resource transport: owning8/focused41… | P12-02n | pending | pending | Owning parent/phase gates unchanged |
| [L842](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D239/P12-02m independent exact-URL static resource observation source: owning4/original b-g-ve… | P12-02m | pending | pending | Owning parent/phase gates unchanged |
| [L843](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Implement/check D238/P12-02l pure minimized original complete-body selected static resource-reference candidat… | P12-02l | pending | pending | Owning parent/phase gates unchanged |
| [L844](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Check certificate expiry and basic TLS observations. | P12-02 | pending | pending | Verified ownership/scope |
| [L845](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Detect mixed content and missing security headers. | P12-02 | pending | pending | Verified ownership/scope |
| [L846](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Report public cookie flags and exposed server information carefully. | P12-02 | pending | pending | Verified ownership/scope |
| [L847](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Avoid exploit attempts, credential attacks, broad port scans, and active vulnerability scans. | P12-01 | pending | pending | Verified ownership/scope |
| [L848](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Add repository dependency scanning only after an authorized repository connection exists. | P16-01 | implemented supported exact declared/root npm-lock versions via OSV, untested; other coverage unavailable | deferred by D437 | Real repository grant |
| [L850](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D300/P12-02bv fixed once-only exact-chain positive1-unit audit collector/private lifecycle and chain-… | P12-02bv | pending | pending | Owning parent/phase gates unchanged |
| [L851](../TODO_ARCHIVE_2026-10-10.md#phase-12-passive-security-observations) Complete D300/P12-02bw fixed private chain consumers2026-10-06: API57 accepted; native158/full546 Angular37 fi… | P12-02bw | pending | pending | Owning parent/phase gates unchanged |
| [L859](../TODO_ARCHIVE_2026-10-10.md#phase-13-deployment) Create a GitHub Actions frontend workflow using npm ci and production builds. | P13-02 | pending | pending | Live deployment; Bilingual review |
| [L860](../TODO_ARCHIVE_2026-10-10.md#phase-13-deployment) Configure GitHub OIDC access to AWS. | P13-02 | pending | pending | Live deployment; Bilingual review |
| [L861](../TODO_ARCHIVE_2026-10-10.md#phase-13-deployment) Upload all generated HTML, including nested prerendered pages and the CSR entry document, plus runtime configu… | P13-02 | pending | pending | Live deployment; Bilingual review |
| [L862](../TODO_ARCHIVE_2026-10-10.md#phase-13-deployment) Upload content-hashed assets with long immutable caching. | P13-02 | pending | pending | Live deployment; Bilingual review |
| [L863](../TODO_ARCHIVE_2026-10-10.md#phase-13-deployment) Configure CloudFront HTTPS, public-route-to-static-HTML resolution, and account/app-only CSR fallback with rea… | P13-02 | pending | pending | Live deployment; Bilingual review |
| [L864](../TODO_ARCHIVE_2026-10-10.md#phase-13-deployment) Configure canonical-host/path and retired-URL HTTP redirects plus a real public 404 page without a Node render… | P13-02 | pending | pending | Live deployment; Bilingual review |
| [L865](../TODO_ARCHIVE_2026-10-10.md#phase-13-deployment) Invalidate changed HTML/runtime configuration after successful uploads, including nested prerendered routes. | P13-02 | pending | pending | Live deployment; Bilingual review |
| [L866](../TODO_ARCHIVE_2026-10-10.md#phase-13-deployment) Check direct public/app deep links, JavaScript-disabled public content, metadata/sitemaps, public 404/redirect… | P13-02 | pending | pending | Live deployment; Bilingual review |
| [L867](../TODO_ARCHIVE_2026-10-10.md#phase-13-deployment) Verify the final product domain in relevant webmaster tools and submit its production sitemap; inspect represe… | P13-05 | excluded | excluded | Live product-site evidence |
| [L868](../TODO_ARCHIVE_2026-10-10.md#phase-13-deployment) Check protected/non-indexed previews versus production indexability, approved page/offer claims, acquisition/c… | P13-05 | excluded | excluded | Live product-site evidence |
| [L869](../TODO_ARCHIVE_2026-10-10.md#phase-13-deployment) Record the product site's SEO/performance baseline, monitoring owner/cadence, and post-launch indexation/broke… | P13-05 | excluded | excluded | Live product-site evidence |
| [L870](../TODO_ARCHIVE_2026-10-10.md#phase-13-deployment) Current D414/D419: older4075166 FAILED97/ERROR181/2586/22105.351s remains history. Current392862 FAILED5/ERROR… | TOOL-01, P11-01dc, P13-05a | pending | pending | Final hosted validation |
| [L871](../TODO_ARCHIVE_2026-10-10.md#phase-13-deployment) D420/P13-05a local secret-free monitoring template/offline report complete2026-10-10 under D423: fixed20 cover… | P13-05a | pending | pending | Owning parent/phase gates unchanged |
| [L872](../TODO_ARCHIVE_2026-10-10.md#phase-13-deployment) Build the backend image in GitHub Actions and push it to ECR. | P13-03 | pending | pending | Live deployment |
| [L873](../TODO_ARCHIVE_2026-10-10.md#phase-13-deployment) Deploy backend images to EC2 using SSM or controlled SSH. | P13-03 | pending | pending | Live deployment |
| [L874](../TODO_ARCHIVE_2026-10-10.md#phase-13-deployment) Run migrations as an explicit deployment step. | P13-03 | pending | pending | Live deployment |
| [L875](../TODO_ARCHIVE_2026-10-10.md#phase-13-deployment) Verify application health after deployment. | P13-03 | pending | pending | Live deployment |
| [L876](../TODO_ARCHIVE_2026-10-10.md#phase-13-deployment) Configure encrypted EBS persistence and private service networking. | P13-01 | pending | pending | Live deployment |
| [L877](../TODO_ARCHIVE_2026-10-10.md#phase-13-deployment) Configure private S3 artifact and backup storage. | P13-01 | pending | pending | Live deployment |
| [L878](../TODO_ARCHIVE_2026-10-10.md#phase-13-deployment) Configure daily PostgreSQL backups and document restoration. | P13-04 | pending | pending | Live deletion; Live restore/alarms |
| [L879](../TODO_ARCHIVE_2026-10-10.md#phase-13-deployment) Configure CloudWatch logs and initial alarms. | P13-04 | pending | pending | Live deletion; Live restore/alarms |
| [L883](../TODO_ARCHIVE_2026-10-10.md#phase-14-publishing-and-social-integrations) Add CMS integrations only for systems required by users. | P14-01 | blocked | blocked | Requested CMS |
| [L884](../TODO_ARCHIVE_2026-10-10.md#phase-14-publishing-and-social-integrations) Add approval-controlled publishing. | P14-01 | blocked | blocked | Requested CMS |
| [L885](../TODO_ARCHIVE_2026-10-10.md#phase-14-publishing-and-social-integrations) Track publication destinations, URLs, and timestamps. | P14-01 | blocked | blocked | Requested CMS |
| [L886](../TODO_ARCHIVE_2026-10-10.md#phase-14-publishing-and-social-integrations) Add social scheduling only where official APIs and permissions permit. | P14-02 | blocked | blocked | Supported social platform |
| [L887](../TODO_ARCHIVE_2026-10-10.md#phase-14-publishing-and-social-integrations) Import first-party social analytics where practical. | P14-02 | blocked | blocked | Supported social platform |
| [L888](../TODO_ARCHIVE_2026-10-10.md#phase-14-publishing-and-social-integrations) Compare post-publication search and conversion performance. | P08-04; P14-01 or P14-02 | pending | pending | Publication/outcome evidence |
| [L892](../TODO_ARCHIVE_2026-10-10.md#phase-15-usage-based-refinement-and-scale) Refine existing organization plans/allowances and retention from real project/crawl/storage/provider usage; la… | P15-01 | blocked | blocked | Actual usage evidence |
| [L893](../TODO_ARCHIVE_2026-10-10.md#phase-15-usage-based-refinement-and-scale) Move PostgreSQL to RDS when reliability or load justifies it. | P15-02 | blocked | blocked | Demonstrated scale constraint |
| [L894](../TODO_ARCHIVE_2026-10-10.md#phase-15-usage-based-refinement-and-scale) Move Redis to ElastiCache when reliability or load justifies it. | P15-02 | blocked | blocked | Demonstrated scale constraint |
| [L895](../TODO_ARCHIVE_2026-10-10.md#phase-15-usage-based-refinement-and-scale) Scale API and workers independently behind appropriate AWS services. | P15-02 | blocked | blocked | Demonstrated scale constraint |
| [L896](../TODO_ARCHIVE_2026-10-10.md#phase-15-usage-based-refinement-and-scale) Consider ECS only when Compose operation becomes a real limitation. | P15-02 | blocked | blocked | Demonstrated scale constraint |
| [L900](../TODO_ARCHIVE_2026-10-10.md#phase-16-repository-aware-remediation) Design explicit repository authorization. | P16-01 | implemented, untested | deferred by D437 | Real repository grant |
| [L901](../TODO_ARCHIVE_2026-10-10.md#phase-16-repository-aware-remediation) Run OpenCode or another coding agent only in isolated temporary environments. | P16-01 | partial; offline dependency/Python syntax parsers implemented, coding-agent integration pending | deferred by D437 | Real repository grant |
| [L902](../TODO_ARCHIVE_2026-10-10.md#phase-16-repository-aware-remediation) Use least-privilege repository credentials. | P16-01 | implemented read-only consent/collector, untested | deferred by D437 | Real repository grant |
| [L903](../TODO_ARCHIVE_2026-10-10.md#phase-16-repository-aware-remediation) Produce patches or pull requests rather than direct deployment. | P16-02 | pending | pending | Real repository grant; Human patch review |
| [L904](../TODO_ARCHIVE_2026-10-10.md#phase-16-repository-aware-remediation) Require human review. | P16-02 | pending | pending | Real repository grant; Human patch review |
| [L905](../TODO_ARCHIVE_2026-10-10.md#phase-16-repository-aware-remediation) Audit all repository access and generated changes. | P16-01 | partial; consent/scoped source/read-attempt/dependency and Python analysis/cleanup audit implemented, generated changes pending | deferred by D437 | Real repository grant |
| [L909](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Establish .agents/ as the provider-neutral home for shared rules, skills, and references. | TOOL-01 | pending | pending | Owning parent/phase gates unchanged |
| [L910](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Add a portable documentation-maintenance skill for the current checkpoint. | TOOL-01 | pending | pending | Owning parent/phase gates unchanged |
| [L911](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Add a thin CLAUDE.md adapter to the shared AGENTS.md guidance. | TOOL-01 | pending | pending | Owning parent/phase gates unchanged |
| [L912](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Add provider-neutral read-only SEO and architecture/plan reviewer roles under .agents/roles/ (D035). | TOOL-02 | pending | pending | Owning parent/phase gates unchanged |
| [L913](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Add thin OpenCode subagent adapters with explicit tool restrictions. | TOOL-02 | pending | pending | Owning parent/phase gates unchanged |
| [L914](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Assign initial explicit reviewer models following AirportTransfer (D038); D046 restored fixed Sol/high after D… | TOOL-02 | pending | pending | Owning parent/phase gates unchanged |
| [L915](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Document reviewer invocation, host-specific registration, and validation commands in .agents/README.md. | TOOL-02 | pending | pending | Owning parent/phase gates unchanged |
| [L916](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Validate OpenCode discovery and effective read-only permissions for both reviewer adapters with OpenCode 1.18.… | TOOL-02 | pending | pending | Owning parent/phase gates unchanged |
| [L917](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Verify both pinned models in the local catalog and resolved model/variant assignments with opencode debug age… | TOOL-02 | pending | pending | Owning parent/phase gates unchanged |
| [L918](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Assign the built-in explore subagent to openai/gpt-5.6-luna with low reasoning in project opencode.json… | TOOL-02 | pending | pending | Owning parent/phase gates unchanged |
| [L919](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Add six provider-neutral read-only specialist roles and OpenCode adapters during the documentation checkpoint:… | TOOL-02 | pending | pending | Owning parent/phase gates unchanged |
| [L920](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Configure initial current-model inheritance for all six specialists and plan-reviewer (D045); superseded by … | TOOL-02 | pending | pending | Owning parent/phase gates unchanged |
| [L921](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Validate the initial D045 discovery, read-only permissions, and absent model/variant overrides with OpenCode 1… | TOOL-02 | pending | pending | Owning parent/phase gates unchanged |
| [L922](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Initially pin all six specialists and plan-reviewer to openai/gpt-5.6-sol/high (D046); D047 replaces Ang… | TOOL-02 | pending | pending | Owning parent/phase gates unchanged |
| [L923](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Verify D046 effective model/variant assignments and read-only permissions with OpenCode 1.18.31, retaining SEO… | TOOL-02 | pending | pending | Owning parent/phase gates unchanged |
| [L924](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Assign routine Angular reviews to Luna/low and document targeted on-demand specialist use with parent-led esca… | TOOL-02 | pending | pending | Owning parent/phase gates unchanged |
| [L925](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Verify D047 routing, retained read-only permissions, and documentation consistency with OpenCode 1.18.31 and t… | TOOL-02 | pending | pending | Owning parent/phase gates unchanged |
| [L926](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Gate security reviews by explicit task-ledger markers, one bounded post-check review per gate without unattend… | TOOL-02 | pending | pending | Owning parent/phase gates unchanged |
| [L927](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Validate D375/D376 guidance follow-up2026-10-08: focused static/link/adapter checks pass for eight roles/24 re… | TOOL-01 | pending | pending | Owning parent/phase gates unchanged |
| [L928](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) D423 scheduling correction2026-10-10: synchronized canonical guidance/plan/backlog/guide/cards/checkpoint; sta… | TOOL-01 | pending | pending | Owning parent/phase gates unchanged |
| [L929](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) At the explicitly selected final app-ready/release validation phase, run D375/D423 full acceptance and complet… | TOOL-01 | pending | pending | Owning parent/phase gates unchanged |
| [L930](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Enrich all eight reviewer roles with actual source ownership and verified command routing (TOOL-01); implement… | TOOL-01 | pending | pending | Owning parent/phase gates unchanged |
| [L931](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Register the same eight shared roles in OpenCode, Codex, and Claude and upgrade Sol to 6.1 (D114/TOOL-02): TOM… | TOOL-02 | pending | pending | Owning parent/phase gates unchanged |
| [L932](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Assign security to GPT-6 Luna/medium and SEO to GPT-6 Luna/high in OpenCode and Codex (D133): routing document… | TOOL-02 | pending | pending | Owning parent/phase gates unchanged |
| [L933](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Restore the five GPT-6.1 Sol reviewers medium→high in OpenCode/Codex (D424/TOOL-02): all24 adapters parse/eigh… | TOOL-02 | pending | pending | Owning parent/phase gates unchanged |
| [L934](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Change the five GPT-6.1 Sol reviewers from high to medium in OpenCode/Codex (D422/TOOL-02): 24 adapters parse … | TOOL-02 | pending | pending | Owning parent/phase gates unchanged |
| [L935](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Require universal maintenance for instructions, agents, subagents, skills, and references in project-local AG… | TOOL-01 | pending | pending | Owning parent/phase gates unchanged |
| [L936](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Leave primary model/reasoning selection to the coding tool or personal defaults across all sibling projects (D… | TOOL-01 | pending | pending | Owning parent/phase gates unchanged |
| [L937](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Add an Angular implementation/review skill only if repeated frontend work demonstrates a workflow beyond the c… | TOOL-01 | blocked | blocked | Recurring tooling need |
| [L938](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Install local ten-minute idle-only fresh OpenCode continuation (D124/TOOL-03): activity/subagent tracking, una… | TOOL-03 | pending | pending | Installed launcher acceptance |
| [L939](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Complete D322/TOOL-03 follow-up: compact active checkpoint with byte-identical dated history and switch the ex… | TOOL-03 | pending | pending | Installed launcher acceptance |
| [L940](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Complete D323/TOOL-03 global no-approval/full-access follow-up2026-10-07: only two approved personal TOML keys… | TOOL-03 | pending | pending | Installed launcher acceptance |
| [L941](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Complete D325/TOOL-03 one-minute idle checks/native codex exec auto-closing scheduled terminals2026-10-07: f… | TOOL-03 | pending | pending | Installed launcher acceptance |
| [L942](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Complete D326/TOOL-03 retain-five automatic terminal runs/private logs: native-exec wrapper with owned identit… | TOOL-03 | pending | pending | Installed launcher acceptance |
| [L943](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Complete D379/TOOL-03 interactive host continuation: focused launcher/native-PTY/Ctrl+C/GNOME/last-five owners… | TOOL-03 | pending | pending | Installed launcher acceptance |
| [L944](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Complete D381/TOOL-03 idle managed interactive windows allow fresh timer launches: focused idle/startup/identi… | TOOL-03 | pending | pending | D434 coding-activity/idle-input-wait guard supersedes D433; installed launcher acceptance |
| [L945](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Add durable work-exhaustion pause before unattended terminal launches (D131/TOOL-03): explicit resume and back… | TOOL-03 | pending | pending | Installed launcher acceptance |
| [L946](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Add a Django/DRF tenancy skill only if repeated backend work demonstrates a workflow beyond the current role/c… | TOOL-01 | blocked | blocked | Recurring tooling need |
| [L947](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Add job/provider or deployment skills only if repeated work demonstrates a workflow beyond the current role/ch… | TOOL-01 | blocked | blocked | Recurring tooling need |
| [L948](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Clarify D324 necessary subagent routing2026-10-07: parent proactively invokes relevant existing read-only suba… | TOOL-01 | pending | pending | Owning parent/phase gates unchanged |
| [L949](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Keep the current reviewer subagents read-only by default; preserve that default for future specialists. | TOOL-01 | pending | pending | Owning parent/phase gates unchanged |
| [L950](../TODO_ARCHIVE_2026-10-10.md#agent-tooling) Add further provider-specific adapters only when needed; keep them thin and credentials outside the repository… | TOOL-01 | blocked | blocked | Concrete adapter need |

### Existing Gate Rollups And Next Selection

P13-05's local monitoring portion rolls up the existing P13-05a evidence; do not invent another monitoring feature or equate it with TODO867–869 live evidence. TODO870 additionally maps TOOL-01/R06 and P11-01dc full-validation evidence, not just offline monitoring. Conditional tooling additions apply only to TODO937/946/947/950; mandatory existing guidance and final validation are unconditional local requirements.

The archived release checklists add acceptance criteria to owning cards rather than duplicate scope:

| Existing gate | Local owning contracts | Separate unverified remainder |
| --- | --- | --- |
| GATE-FOUNDATION | P01-01–P01-07, P02-01–P02-05, P03-01; current checks/source-bound reviews | Hosted CI/production evidence as specified |
| GATE-INTERNAL | P04/P05, P06/P07, P08-01–P08-06, P10-01/P10-02; scope/retry/cancel/quota checks | Permitted real sources and practical usability; no credential request for local code |
| GATE-PUBLIC | TOOL-01 final validation/review, P3A-05–P3A-11, P02-06/P03-03/P08/P13 local boundaries | P3A-13/R07 deployed/legal/content/sandbox/email/restore/public journey |
| GATE-AI | P11A-01–P11A-05 applicable supported-surface local contracts | Actual provider/surface/legal/privacy/hosted/manual evidence; unsupported surfaces unresolved |

The one-time classification is finished. Subsequent work reads only the selected original contract, dependencies and affected source/evidence. P02-06a/P02-06b native repair automated acceptance is reconciled against the completed R06 source manifest/full frontend coverage and their focused independent reviews; no source edit or check replay. TODO235 is composite and remains pending until its other owners reconcile. P02-06 coherent/personal identity/own-account growth and marked source reviews have local evidence; parent source-contract/final current-source automated acceptance remains unfinished; its default-disabled release gates are preserved. Earlier pending rows need selected evidence reconciliation, not rebuilding or a new full-suite trigger. Continue to the earliest dependency-ready unfinished original local contract after that reconciliation; the checkpoint carries the exact next step.

## Historical Card Index

The following headings retain old links, IDs and archived labels. D429 authorizes their existing local contracts after the basic automated stage; the Local completion table controls current work/status, not a historical label. Read only the selected contract/evidence plus dependencies. The original archived cards still describe required human/external acceptance separately; no new pass is inferred.

## Ledger Conventions

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#ledger-conventions).

## Phase 1 — Repository And Runtime Scaffold

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#phase-1--repository-and-runtime-scaffold).

### P01-01 — Establish authorized workspace and version pins [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p01-01--establish-authorized-workspace-and-version-pins-done).

### P01-02 — Scaffold Angular with static public/CSR boundaries [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p01-02--scaffold-angular-with-static-publiccsr-boundaries-done).

### P01-03 — Scaffold Django and the initial user migration [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p01-03--scaffold-django-and-the-initial-user-migration-done).

### P01-04 — Separate local services and environment configuration [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p01-04--separate-local-services-and-environment-configuration-done).

### P01-05 — Baseline verification and CI [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p01-05--baseline-verification-and-ci-done).

### P01-06 — Configuration, logging and artifact access foundations [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p01-06--configuration-logging-and-artifact-access-foundations-done).

### P01-07 — Customer flow wireframes and accessible UI conventions [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p01-07--customer-flow-wireframes-and-accessible-ui-conventions-done).

## Phase 2 — Authentication And Tenancy

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#phase-2--authentication-and-tenancy).

### P02-01 — Registration, verification and cookie authentication [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p02-01--registration-verification-and-cookie-authentication-done).

### P02-02 — Recovery, verified email changes and session management [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p02-02--recovery-verified-email-changes-and-session-management-done).

### P02-03 — Organization/project model and centralized access enforcement [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p02-03--organizationproject-model-and-centralized-access-enforcement-done).

### P02-04 — Role matrix, invitations and revocation [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p02-04--role-matrix-invitations-and-revocation-done).

### P02-05 — Ownership transfer and suspension invariants [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p02-05--ownership-transfer-and-suspension-invariants-done).

### P02-06 — Export, user closure and organization closure [blocked]

2026-10-15 configurable READY-copy lifetime locally complete: all three formats, nullable immutable reviewed deadline, current delivery denial, bounded version-aware cleanup, native expiry state and unset configuration; focused4/affected5/native1/topology3/types/drift/independent Django+marked Security/dev0086/runtime PASS. Parent remains unfinished with legal-export and final-current-source gates. [Receipt](IMPLEMENTATION_HISTORY_2026-10-15.md#p02-06-reviewed-ready-copy-lifetime).

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p02-06--export-user-closure-and-organization-closure-blocked).

### P02-06a — Exact scalar owner closure outcome states [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p02-06a--exact-scalar-owner-closure-outcome-states-in_progress).

### P02-06b — Exact scalar private snapshot states and current history clearing [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p02-06b--exact-scalar-private-snapshot-states-and-current-history-clearing-in_progress).

## Phase 3 — Platform Superadmin

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#phase-3--platform-superadmin).

### P03-01 — Safe Django Admin and customer admin separation [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-01--safe-django-admin-and-customer-admin-separation-done).

### P03-02 — Staff MFA, recovery and production access [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-02--staff-mfa-recovery-and-production-access-done).

### P03-03 — Operational correction and support workflows [pending]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03--operational-correction-and-support-workflows-pending).

### P03-03a — Minimized exact-scoped staff job investigation source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03a--minimized-exact-scoped-staff-job-investigation-source-done).

### P03-03b — Reasoned exact-scoped staff job Admin consumer [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03b--reasoned-exact-scoped-staff-job-admin-consumer-done).

### P03-03c — Separate exact-scoped internal-unit reservation source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03c--separate-exact-scoped-internal-unit-reservation-source-done).

### P03-03d — Reasoned scoped internal-unit usage Admin [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03d--reasoned-scoped-internal-unit-usage-admin-done).

### P03-03e — Separate original AI usage/cost observation source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03e--separate-original-ai-usagecost-observation-source-done).

### P03-03f — Reasoned scoped original AI observation Admin [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03f--reasoned-scoped-original-ai-observation-admin-done).

### P03-03g — Exact organization notice transport source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03g--exact-organization-notice-transport-source-done).

### P03-03h — Complete scoped organization notice investigation consumers [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03h--complete-scoped-organization-notice-investigation-consumers-done).

### P03-03i — Exact current account-mail record source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03i--exact-current-account-mail-record-source-done).

### P03-03j — Complete exact account-mail investigation consumers [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03j--complete-exact-account-mail-investigation-consumers-done).

### P03-03k — Existing suppression clearance final-assurance recovery [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03k--existing-suppression-clearance-final-assurance-recovery-done).

### P03-03l — Exact retained suppression and first feedback source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03l--exact-retained-suppression-and-first-feedback-source-done).

### P03-03m — Complete exact suppression-feedback investigation consumers [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03m--complete-exact-suppression-feedback-investigation-consumers-done).

### P03-03n — Existing trial correction request and final-state assurance [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03n--existing-trial-correction-request-and-final-state-assurance-done).

### P03-03o — Existing signed billing receipt retry final assurance [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03o--existing-signed-billing-receipt-retry-final-assurance-done).

### P03-03p — Exact retained signed billing receipt source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03p--exact-retained-signed-billing-receipt-source-done).

### P03-03q — Complete exact billing receipt investigation consumers [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03q--complete-exact-billing-receipt-investigation-consumers-done).

### P03-03r — Exact Admin consumer for existing trial corrections [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03r--exact-admin-consumer-for-existing-trial-corrections-done).

### P03-03s — Exact retained organization trial source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03s--exact-retained-organization-trial-source-done).

### P03-03t — Exact trial Admin investigation consumer [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03t--exact-trial-admin-investigation-consumer-done).

### P03-03u — Exact retained linked subscription source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03u--exact-retained-linked-subscription-source-done).

### P03-03v — Exact linked subscription Admin consumer [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03v--exact-linked-subscription-admin-consumer-done).

### P03-03w — Exact retained archived subscription source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03w--exact-retained-archived-subscription-source-done).

### P03-03x — Exact archived subscription Admin consumer [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03x--exact-archived-subscription-admin-consumer-done).

### P03-03y — Exact retained closure cancellation source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03y--exact-retained-closure-cancellation-source-done).

### P03-03z — Exact closure cancellation Admin consumer [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03z--exact-closure-cancellation-admin-consumer-done).

### P03-03aa — Exact retained checkout attempt source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03aa--exact-retained-checkout-attempt-source-done).

### P03-03ab — Exact checkout attempt Admin consumer [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03ab--exact-checkout-attempt-admin-consumer-done).

### P03-03ac — Exact Admin consumer for existing signed receipt retry [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03ac--exact-admin-consumer-for-existing-signed-receipt-retry-done).

### P03-03ad — Existing checkout link capture final-integrity recovery [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03ad--existing-checkout-link-capture-final-integrity-recovery-done).

### P03-03ae — Exact retained checkout link acknowledgment source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03ae--exact-retained-checkout-link-acknowledgment-source-done).

### P03-03af — Exact retained checkout link Admin consumer [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03af--exact-retained-checkout-link-admin-consumer-done).

### P03-03ag — Existing first-active historical reader final integrity [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03ag--existing-first-active-historical-reader-final-integrity-done).

### P03-03ah — Exact retained first-active staff source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03ah--exact-retained-first-active-staff-source-done).

### P03-03ai — Exact retained first-active Admin consumer [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p03-03ai--exact-retained-first-active-admin-consumer-done).

## Phase 3A — Commercial Readiness

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#phase-3a--commercial-readiness).

### P3A-01 — Select audience, product domain and public page map [blocked]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-01--select-audience-product-domain-and-public-page-map-blocked).

### P3A-02 — Market/language coverage and locale contract [blocked]

P3A-02 optional weekly/operational/CrUX recipient-language drafts complete locally: focused6 PASS15.948s, Jobs source review clear, reload healthy and actual delivery flags disabled. Production English; bilingual/final acceptance remains open. [Receipt](IMPLEMENTATION_HISTORY_2026-10-15.md#notification-draft-terminal-receipt).


P3A-02 original private workspace titles now have local evidence across all37 components/53 fixed route rows; earlier11 account components retained. Latest12 components/eight exact scopes focused46/types8/nonmetadata preservation12/eight bounded independent UI source reviews PASS; sample assertion and diagnostic test-compile failures retained/repaired. Existing cases extended only; scoped612/whole ratios unchanged. P3A-02/TODO171/173/final/bilingual/manual/public remain unfinished. Original P3A-09 CONTACT configured local submission preparation next, with live destination/staffing/legal/delivery separate. [Latest receipt](IMPLEMENTATION_HISTORY_2026-10-12.md#p3a-02-original-multi-profile-document-titles).

Original Security document title component-scoped Title effect/owning4/types/bounded UI source review PASS; initial deferred-mock timeout repaired/retained. No new distinct cases; scoped612/whole ratios unchanged. [Receipt](IMPLEMENTATION_HISTORY_2026-10-12.md#p3a-02-original-security-document-title). Original sign-in/registration/recovery/reset titles focused13/types/bounded UI review PASS. [Receipt](IMPLEMENTATION_HISTORY_2026-10-12.md#p3a-02-original-sign-in-registration-and-password-document-titles). Original verification/resend/invitation titles focused9/types/bounded UI source review PASS. [Receipt](IMPLEMENTATION_HISTORY_2026-10-12.md#p3a-02-original-verification-resend-and-invitation-document-titles). Original provider-settings/acquisition/checkout titles focused9/types/bounded UI review PASS. [Receipt](IMPLEMENTATION_HISTORY_2026-10-12.md#p3a-02-original-operator-acquisition-and-checkout-document-titles). Original Overview/onboarding/organization-billing titles focused9/types/bounded UI review/source-preservation14 PASS. [Receipt](IMPLEMENTATION_HISTORY_2026-10-12.md#p3a-02-original-core-workspace-document-titles). All11 account route identities and core workspace3 have local title evidence; remaining workspace metadata and whole current-source/bilingual/manual acceptance unfinished. D427 extended existing language-switch/fallback/production cases for the uncovered document-title contract; no new distinct case/spec. AIText title now checked; remaining workspace titles continue.

Original checkout/receipt caption repair: raw English fixed notices now translate only at current-language render. Extended owning pasted/invalid and receipt consent/saved/unknown/lookup cases PASS16 (route5/receipt11); app types/source-preservation4+9/bounded independent UI review PASS. No new distinct draft cases; current599, whole P3A-02/current-source/manual/public acceptance unfinished. [Receipt](IMPLEMENTATION_HISTORY_2026-10-11.md#p3a-02-original-checkout-and-receipt-current-language-captions).

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-02--marketlanguage-coverage-and-locale-contract-blocked).

### P3A-03 — Proof material and public-content operations [done]

Current local authoring/sample contract verified against current source and three existing focused cases; real approvals/publication/hosted rollback remain pending. [Receipt](IMPLEMENTATION_HISTORY_2026-10-15.md#p3a-03-current-local-verification).

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-03--proof-material-and-public-content-operations-done).

### P3A-04 — Decide commercial offer, provider and retention policies [blocked]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-04--decide-commercial-offer-provider-and-retention-policies-blocked).

### P3A-05 — Exactly-once trial and entitlement lifecycle [pending]

Current grant/eligibility/owner projection source reconciled; exact bootstrap/concurrency/post-paid extension/server-time expiry4 PASS11.730s. Existing08 composition evidence reused; no new code/test. Retained/export02-06, final and production historical-cutover acceptance stay open. [Receipt](IMPLEMENTATION_HISTORY_2026-10-16.md#p3a-05-current-grantprojection-result).

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-05--exactly-once-trial-and-entitlement-lifecycle-pending).

### P3A-06 — Hosted checkout, portal and provider-state mapping [blocked]

Current fresh/replay READY response now uses existing saved-link authority fence. Source-loss/no-repost regression + existing owner/unknown API3 PASS6.255s; parent source review complete, independent Billing final repair review complete/no actionable finding. Prior focused API/race/portal4 and native06c1 PASS. No provider call; whole/final/review/export gates remain open. [Receipt](IMPLEMENTATION_HISTORY_2026-10-16.md#p3a-06-checkout-response-current-source-repair).

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-06--hosted-checkout-portal-and-provider-state-mapping-blocked).

### P3A-06a — Persist inert organization subscription identity and block post-checkout trial extension [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-06a--persist-inert-organization-subscription-identity-and-block-post-checkout-trial-extension-done).

### P3A-06b — Fail closed on linked subscription across trial entry and costly work [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-06b--fail-closed-on-linked-subscription-across-trial-entry-and-costly-work-done).

### P3A-06c — Exact scalar owner checkout operational states [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-06c--exact-scalar-owner-checkout-operational-states-in_progress).

### P3A-07 — Signed billing events and reconciliation [done]

Current adjustment worker-claim gap repaired using existing claim and atomic receipt-success helpers. Extended owning refund/chargeback case covers lost claim and persistence rollback. Focused2 PASS2.458s, stable affected4 PASS3.475s; required reload healthy/task registration on four workers, independent Billing repair review complete/no actionable finding. Whole/final/provider acceptance stays open. [Receipt](IMPLEMENTATION_HISTORY_2026-10-16.md#p3a-07-adjustment-claim-focused-result).

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-07--signed-billing-events-and-reconciliation-done).

### P3A-08a — Enforce positive-unit trial work [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-08a--enforce-positive-unit-trial-work-done).

### P3A-08b — Enforce trial project and member limits [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-08b--enforce-trial-project-and-member-limits-done).

### P3A-08 — Complete commercial API, scheduler and worker enforcement [done]

Current source flow reconciled; exact trial/paid concurrent budget, stage/expiry/grace, project/member and adverse schedule cases PASS7/12.033s. No source/test change. Local flow focused-checked; whole/final and current final/provider acceptance remain pending. [Receipt](IMPLEMENTATION_HISTORY_2026-10-16.md#p3a-08-current-sensitive-contract-result).

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-08--complete-commercial-api-scheduler-and-worker-enforcement-done).

### P3A-09 — Build public pages and static SEO contract [blocked]

P3A-09 approved metadata startup/navigation, inert reviewed fragments, unbundled publication records and build-derived CDN inventory are locally checked. Native consent/collector14 PASS2.25s, compiler/guard10 PASS12.331s, generated3 PASS1.493s, CDN4 PASS, app/spec types PASS; build36 PASS19.168s/298.06kB below unchanged300/400kB limits. Isolated synthetic Angular clean approved rebuild3 PASS9.072s preserved both final reviewed hashes and actual release CLI/CSR/error guard. Independent SEO source findings resolved. Real config/approvals remain empty/draft; final whole-current/manual/bilingual/legal/hosted/public gates stay open.624 selected owning cases; whole68/521 and107/689 unchanged. [Receipt](IMPLEMENTATION_HISTORY_2026-10-12.md#p3a-09-approved-runtime-metadata-and-clean-build-publication).

CONTACT configured local input/store/API/native/persisted-MFA scoped staff/expiry cleanup complete for their focused/source/runtime contracts. Default-off/unset reviewed retention; actual rows0. Kernel8/dev0085 reused; API5/native6/types2/build36/generated4/draft guards2 PASS, staff3/cleanup+queue4/topology1/source reviews/ONE task reload+four-worker/default queue/hourly Beat/disabled API503 probes terminal. Three source findings remediated (rate config/replacement authority/older discovery); initial test/tool failures stay in receipts. Native5 new distinct cases617; whole68/521+107/689 unchanged because parent/associated TODO local contracts remain unfinished. [API/native](IMPLEMENTATION_HISTORY_2026-10-12.md#p3a-09-original-contact-browser-api-and-native-uncertainty), [staff/cleanup/runtime](IMPLEMENTATION_HISTORY_2026-10-12.md#p3a-09-original-contact-scoped-staff-and-expiry-operations), [kernel](IMPLEMENTATION_HISTORY_2026-10-12.md#p3a-09-original-contact-input-and-persistence-prerequisite).

The earlier71-byte warning and unconditional-cleanup limitation are resolved by the receipt above. Required final whole-current source acceptance and actual founder/bilingual/copy/URL/legal/browser/host approvals remain unverified; publication stays gated. Continue dependency-ready original local contracts, including P02-06's configurable export-policy/READY-copy lifetime remainder. [Checkpoint](IMPLEMENTATION_STATE.md#2-exact-next-action).

Original CANCELLATION paired noindex draft/HOME links/native3/types/build32/generated17+CDN3/guards2/bounded billing source review PASS;610 scoped cases, initial299.53kB. Legal/provider/hosted deletion/manual/public gates and whole-card/final acceptance unfinished; whole ratios unchanged. [Receipt](IMPLEMENTATION_HISTORY_2026-10-12.md#p3a-09-local-paired-cancellation-draft).

Original DATA-HANDLING paired noindex draft/HOME discovery/native3+corrected1/app-spec types/build30/generated19+corrected3/guards2/bounded integration source review PASS;609 scoped cases, initial299.38kB. OAuth wording corrected to Google API grants versus local imports; legal/export/closure/hosted/public gates and whole ratios unchanged/unfinished. [Receipt](IMPLEMENTATION_HISTORY_2026-10-12.md#p3a-09-local-paired-data-handling-draft).

Original DATA-HANDLING paired noindex draft/HOME links/native3/types/build30/generated16+CDN3/guards2/bounded UI source review PASS;609 scoped cases, initial299.38kB. Legal/export/disabled closure/hosted deletion/manual/public gates remain unfinished; whole ratios/card/final acceptance unchanged. [Receipt](IMPLEMENTATION_HISTORY_2026-10-12.md#p3a-09-local-paired-data-handling-draft).

Original ACCESSIBILITY paired noindex draft/HOME+CONTACT links/native4/types/build28/generated15+CDN3/guards2/bounded UI source review PASS;608 scoped cases, initial299.22kB. Manual/bilingual/public conformance unfinished; whole ratios/card/full acceptance unchanged. [Receipt](IMPLEMENTATION_HISTORY_2026-10-11.md#p3a-09-local-paired-accessibility-draft).

Original CONTACT paired noindex draft/HOME+HELP links/native4/types/build26/generated14+CDN3/guards2/bounded UI source review PASS;607 scoped cases, initial299.07kB. Public-submission contract remains unfinished; owner-confirmed public destination/service facts pending. Whole ratios/card/full/manual/public acceptance unchanged. [Receipt](IMPLEMENTATION_HISTORY_2026-10-11.md#p3a-09-local-paired-contact-draft).

Original PRICING paired noindex draft/HOME links/native3/types/build24/generated13+CDN3/guards2/bounded billing source review PASS;606 distinct scoped cases, initial298.93kB. Whole ratios/card/final/manual/bilingual/public acceptance unfinished/unchanged. [Receipt](IMPLEMENTATION_HISTORY_2026-10-11.md#p3a-09-local-paired-pricing-draft).

Original CONTENT paired noindex draft/HOME+TRANSFER+OPPORTUNITIES links/native4+repaired1/types/build22/generated12+CDN3/guards2/bounded SEO copy review PASS.605 distinct scoped draft cases; initial298.80kB under unchanged budget. Failed initial assertion retained; only test wording corrected to actual full sentence. Whole ratios/card/final/manual/public acceptance remain unfinished/unchanged. [Receipt](IMPLEMENTATION_HISTORY_2026-10-11.md#p3a-09-local-paired-content-draft).

Original OPPORTUNITIES paired noindex draft/HOME+AGENCY+AUDITS links/native5/types/build20/generated11+CDN3/guards2/bounded SEO copy review PASS;604 distinct scoped draft cases, initial298.58kB. Whole ratios/card/public/manual acceptance unchanged/unfinished. [Receipt](IMPLEMENTATION_HISTORY_2026-10-11.md#p3a-09-local-paired-opportunities-draft).

Original TRANSFER paired noindex draft/HOME+AGENCY discovery/native4/types/build18/generated10+CDN3/guards2/bounded SEO copy review PASS.603 distinct scoped draft cases, initial298.41kB; whole local/card/public acceptance and ratios remain unfinished/unchanged. [Receipt](IMPLEMENTATION_HISTORY_2026-10-11.md#p3a-09-local-paired-transfer-draft).

Original AGENCY paired noindex draft/HOME links/native3/types/build16/generated9+CDN3/guards2/bounded independent UI review PASS; initial298.22kB under unchanged budget.602 distinct scoped draft cases; P3A-09/P3A-02/TODO171/173 and whole ratios remain unfinished/unchanged. [Receipt](IMPLEMENTATION_HISTORY_2026-10-11.md#p3a-09-local-paired-agency-draft).

Measured public initial-budget repair complete: existing lazy route-module pattern/root private precedence/leaf public locale, exact15 descriptors preserved. Native public9+footer1/types/build14/generated8+CDN3/guards2/deeper Angular-criteria review PASS; initial300.50→298.07kB clears300kB warning, thresholds unchanged. No new distinct cases or whole-contract claim. [Receipt](IMPLEMENTATION_HISTORY_2026-10-11.md#p3a-09-measured-public-initial-bundle-lazy-route-repair).

Original AUDITS paired preview/HOME discovery/native3/types/build14/generated8+CDN3/guards2/SEO copy review complete. Build exit0 has initial300.50kB warning (504bytes over300kB; under400kB error); measured public-lazy follow-up above complete at298.07kB.601 distinct draft cases (+one AUDITS); whole contract/ratios unfinished/unchanged. [Receipt](IMPLEMENTATION_HISTORY_2026-10-11.md#p3a-09-local-paired-audits-draft).

Original SOURCES paired preview matrix/HOME discovery/native3/types/build12/generated7+CDN3/guards2/SEO source review PASS. Real-provider/property/measurement acceptance and published source URLs remain unverified/absent.600 distinct draft route cases (+one SOURCES); whole contract/ratios unfinished/unchanged. [Receipt](IMPLEMENTATION_HISTORY_2026-10-11.md#p3a-09-local-paired-sources-draft).

Current local slice: paired `/preview/help` and `/preview/tr/help` HELP drafts under D103/P3A-02 focused3/types/build10-generated/static9/repaired draft guards2/bounded independent UI source review PASS. Initial guard failures retained, repaired only missing draft manifest entries. Six truthful semantic guidance sections and HOME discovery; public `/help`–`/tr/yardim` excluded, analytics authority unchanged. One new distinct paired route draft case (current599); whole contract/ratios remain pending/unchanged. [Receipt](IMPLEMENTATION_HISTORY_2026-10-11.md#p3a-09-local-paired-help-draft).

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-09--build-public-pages-and-static-seo-contract-blocked).

### P3A-10 — Production transactional email and lifecycle communications [blocked]

Current account/notice/feedback source reconciled; exact unknown/suppressed, recipient locale/production fallback, revoked recipient and commit/dedupe4 PASS1.850s. No source/test change or real mail. Whole/final/bilingual/actual SES/hosted acceptance unfinished. [Receipt](IMPLEMENTATION_HISTORY_2026-10-16.md#p3a-10-current-local-recoveryrecipient-result).

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-10--production-transactional-email-and-lifecycle-communications-blocked).

### P3A-11a — Capture first primary-email verification time [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11a--capture-first-primary-email-verification-time-done).

### P3A-11b — Capture prospective self-service registration origin [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11b--capture-prospective-self-service-registration-origin-done).

### P3A-11 — Acquisition funnel and consent-aware attribution [blocked]

Current retained/consent kernel source reconciled; exact aggregate/anonymous receipt-withdrawal/intake/expiry4 PASS1.216s. No source change or collection enabled. Whole/suffixes/final/approved-public/source-consumer acceptance pending. [Receipt](IMPLEMENTATION_HISTORY_2026-10-16.md#p3a-11-current-retainedconsent-kernel-result).

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11--acquisition-funnel-and-consent-aware-attribution-blocked).

### P3A-11c — Retained first human-action acceptance aggregate [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11c--retained-first-human-action-acceptance-aggregate-done).

### P3A-11d — Prospective confirmed browser receipt of a checkout link [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11d--prospective-confirmed-browser-receipt-of-a-checkout-link-done).

### P3A-11e — Prospective first-active paid entitlement source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11e--prospective-first-active-paid-entitlement-source-done).

### P3A-11f — Prospective bounded first-audit request provenance [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11f--prospective-bounded-first-audit-request-provenance-done).

### P3A-11g — Prospective first bounded-audit completion source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11g--prospective-first-bounded-audit-completion-source-done).

### P3A-11h — Current bounded-audit human-action evidence discovery [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11h--current-bounded-audit-human-action-evidence-discovery-done).

### P3A-11i — Deliberate private current audit-action source inspection [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11i--deliberate-private-current-audit-action-source-inspection-done).

### P3A-11j — Explicit prospective bounded-audit usefulness acknowledgment [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11j--explicit-prospective-bounded-audit-usefulness-acknowledgment-done).

### P3A-11k — Retained first-usefulness server timing inspection [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11k--retained-first-usefulness-server-timing-inspection-done).

### P3A-11l — First-party optional consent and public candidate boundary [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11l--first-party-optional-consent-and-public-candidate-boundary-done).

### P3A-11m — Checked minimized public analytics publication policy [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11m--checked-minimized-public-analytics-publication-policy-done).

### P3A-11n — Minimized pinned-policy public observation source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11n--minimized-pinned-policy-public-observation-source-done).

### P3A-11o — Prospective unlinked public consent-epoch observations [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11o--prospective-unlinked-public-consent-epoch-observations-done).

### P3A-11p — Retained organization-age-at-first-paid-server-observation timing [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11p--retained-organization-age-at-first-paid-server-observation-timing-done).

### P3A-11q — Audited original trial activation source discovery [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11q--audited-original-trial-activation-source-discovery-done).

### P3A-11r — Original audited trial-to-first-paid server timing [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11r--original-audited-trial-to-first-paid-server-timing-done).

### P3A-11s — Fixed original trial paid-observation window source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11s--fixed-original-trial-paid-observation-window-source-done).

### P3A-11t — Private original trial paid-window inspector [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11t--private-original-trial-paid-window-inspector-done).

### P3A-11u — Complete retained monthly trial paid-window source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11u--complete-retained-monthly-trial-paid-window-source-done).

### P3A-11v — Private retained monthly trial paid-window inspection [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11v--private-retained-monthly-trial-paid-window-inspection-in_progress).

### P3A-11w — Exact operational milestone grain and unavailable public source [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11w--exact-operational-milestone-grain-and-unavailable-public-source-in_progress).

### P3A-11x — Exact scalar checkout-link source metadata [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11x--exact-scalar-checkout-link-source-metadata-in_progress).

### P3A-11y — Exact scalar owner paid-history and trial-activation source [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11y--exact-scalar-owner-paid-history-and-trial-activation-source-in_progress).

### P3A-11z — Scalar first-audit launch and retained operational history [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-11z--scalar-first-audit-launch-and-retained-operational-history-in_progress).

### P3A-12 — Advertised provider readiness and budget evidence [blocked]

Current readiness static3/CLI PASS; nine providers and separate AI visibility surface remain unverified/unclaimable, GA4 origin contract blocked, no real evidence supplied. Local preparation checked; actual readiness/cost/terms/public acceptance remains pending. [Receipt](IMPLEMENTATION_HISTORY_2026-10-16.md#p3a-12-current-preparation-result).

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-12--advertised-provider-readiness-and-budget-evidence-blocked).

### P3A-13 — Public SaaS end-to-end release gate [pending]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p3a-13--public-saas-end-to-end-release-gate-pending).

## Phase 4 — Job Platform

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#phase-4--job-platform).

### P04-01 — Durable job schema and explicit handler contract [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p04-01--durable-job-schema-and-explicit-handler-contract-done).

### P04-02 — Transaction-safe dispatch and recoverable execution [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p04-02--transaction-safe-dispatch-and-recoverable-execution-done).

### P04-03 — Job APIs and accessible progress UI [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p04-03--job-apis-and-accessible-progress-ui-done).

### P04-03a — Exact diagnostic job status and requested detail identity [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p04-03a--exact-diagnostic-job-status-and-requested-detail-identity-in_progress).

### P04-03b — Diagnostic route IDs and exact organization/project metadata [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p04-03b--diagnostic-route-ids-and-exact-organizationproject-metadata-in_progress).

### P04-04 — Atomic usage and concurrency controls [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p04-04--atomic-usage-and-concurrency-controls-done).

### P04-05 — Schedules, stage reauthorization and operational recovery [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p04-05--schedules-stage-reauthorization-and-operational-recovery-done).

## Phase 5 — AI Providers And Routing

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#phase-5--ai-providers-and-routing).

### P05-01 — Provider credentials, model catalog and capabilities [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p05-01--provider-credentials-model-catalog-and-capabilities-done).

### P05-02 — Native OpenAI and compatible endpoint adapters [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p05-02--native-openai-and-compatible-endpoint-adapters-done).

### P05-04a — Exact native AI job and provider-request scalar states [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p05-04a--exact-native-ai-job-and-provider-request-scalar-states-in_progress).

### P05-05 — Protected platform and organization credential-entry UI [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p05-05--protected-platform-and-organization-credential-entry-ui-done).

### P05-05a — Exact scalar states in existing verification/provider screens [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p05-05a--exact-scalar-states-in-existing-verificationprovider-screens-in_progress).

### P05-05b — Strict provider/account/model and seller row enums [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p05-05b--strict-provideraccountmodel-and-seller-row-enums-in_progress).

### P05-05c — Dedicated YouTube configuration exact scalar state [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p05-05c--dedicated-youtube-configuration-exact-scalar-state-in_progress).

### P05-03 — Routing, fallbacks and model configuration UI [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p05-03--routing-fallbacks-and-model-configuration-ui-done).

### P05-03a — Exact scalar model-tier/account-source native catalog [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p05-03a--exact-scalar-model-tieraccount-source-native-catalog-in_progress).

### P05-04 — Usage, cost and provider observability [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p05-04--usage-cost-and-provider-observability-done).

## Phase 6 — Onboarding And Integrations

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#phase-6--onboarding-and-integrations).

### P06-01 — Project configuration and resumable onboarding shell [done]

Current configuration flow reconciled; existing backend2 PASS5.873s and native6 PASS440ms. No source/test/build change. Whole/01a final frontend/manual acceptance pending. [Receipt](IMPLEMENTATION_HISTORY_2026-10-16.md#p06-01-current-resumable-configuration-result).

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-01--project-configuration-and-resumable-onboarding-shell-done).

### P06-01a — Scalar onboarding progress and scoped saved configuration [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-01a--scalar-onboarding-progress-and-scoped-saved-configuration-in_progress).

### P06-02 — Small source-aware connection and sync contract [done]

Current original small local contract verified against models/services and four exact scope/capability/provenance/cursor cases PASS5.666s. TODO300 verified; broader mapping/engine/consumer TODO owners remain in_progress. No code change or provider call. [Receipt](IMPLEMENTATION_HISTORY_2026-10-16.md#p06-02-current-local-source-contract-verified).

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-02--small-source-aware-connection-and-sync-contract-done).

### P06-03 — Search Console CSV import [done]

Current local importer/TODO296 verified using source review and exact normal/replay/property/malformed/current-policy4 PASS6.929s. No source/test change or real source operation; global final/manual/provider acceptance separate. [Receipt](IMPLEMENTATION_HISTORY_2026-10-16.md#p06-03-current-local-csv-contract-verified).

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-03--search-console-csv-import-done).

### P06-04 — Google OAuth and Search Console synchronization [done]

Current callback final authority-loss repair reuses encrypted disabled revocable-grant retention after rollback. Existing owning case extended; focused3 PASS4.206s and independent Jobs review no actionable finding. No new case/schema/provider call; broader04/suffix/final/native/live acceptance remains unfinished. [Receipt](IMPLEMENTATION_HISTORY_2026-10-16.md#p06-04-callback-final-authority-loss-recovery).

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-04--google-oauth-and-search-console-synchronization-done).

### P06-04a — Scalar existing-source and Google-grant scope metadata [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-04a--scalar-existing-source-and-google-grant-scope-metadata-in_progress).

### P06-04b — Scalar default and reviewed query brand labels [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-04b--scalar-default-and-reviewed-query-brand-labels-in_progress).

### P06-04c — Scalar Search Console sync state and exact acknowledgment identity [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-04c--scalar-search-console-sync-state-and-exact-acknowledgment-identity-in_progress).

### P06-04d — Scalar indexed-version coverage job and source labels [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-04d--scalar-indexed-version-coverage-job-and-source-labels-in_progress).

### P06-04e — Scalar backfill and daily-schedule metadata/current refresh [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-04e--scalar-backfill-and-daily-schedule-metadatacurrent-refresh-in_progress).

### P06-05 — GA4 synchronization and measurement quality [blocked]

Current official schema/compatibility and independent SEO review do not establish session-first exact-origin landing grain from event pageLocation; keep source blocked in denominator. Existing queue/worker/history-denial2 PASS1.611s. No source change/enablement or real provider call; unrelated06-06 continues. [Evidence](IMPLEMENTATION_HISTORY_2026-10-16.md#p06-05-supported-origin-evidence-and-retained-guard).

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-05--ga4-synchronization-and-measurement-quality-blocked).

### P06-05a — Scalar supported Analytics grant and manual-review metadata [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-05a--scalar-supported-analytics-grant-and-manual-review-metadata-in_progress).

### P06-05b — Scalar historical Analytics job metadata [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-05b--scalar-historical-analytics-job-metadata-in_progress).

### P06-06 — Brand segments and integration status UI [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-06--brand-segments-and-integration-status-ui-done).

### P06-07 — Budgeted first audit and first-value journey [blocked]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-07--budgeted-first-audit-and-first-value-journey-blocked).

### P06-08 — Bing Webmaster connector [pending]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-08--bing-webmaster-connector-pending).

### P06-09 — Yandex and demand-driven webmaster extensions [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p06-09--yandex-and-demand-driven-webmaster-extensions-pending).

D437 implementation slice written (untested): bounded official advanced query-by-URL CSV intake, immutable per-project job evidence, separate history/readback and private UI. Existing jobs/usage/audit/lifecycle are reused; raw uploads are not retained. Limits100rows/24KiB parsed evidence,1MiB upload; unsupported/overflow input fails rather than truncates. Source calendar timezone unspecified; missing rows unknown. OAuth auth-code/PKCE, encrypted device-token grants, exact verified origin/host, write-only MFA staff configuration, private connect/status/revoke and closure/deletion/inventory controls are written, untested; source migration0018 is unapplied. Unknown exchanges remain durable until explicit human-reported remote revocation, never automatic timeout/retry. Independent Jobs source review findings were corrected; this is not executed acceptance. The remaining local aggregate API-history/refresh/cursor/backfill flow is now written: existing IntegrationConnection/SyncCursor/JobRun/usage, date-only device-ALL source mapping with returned timestamp offsets,31-day windows within a local90-day bound (not guaranteed provider retention), gap-aware count-window cursor, private history/detail/cancel UI, quota throttle and stale-job recovery. Unknown refreshes retain cleanup gates and explicit human-reported remote-revocation recovery. Generic source/health/onboarding/export paths are provider-aware. Source migration0019 is also unapplied/unverified. This closes the selected existing local coding scope; full card stays in_progress for unrun automated/manual/real-provider acceptance and unspecified additional engines stay demand-gated. No tests/checks added/run.

## Phase 7 — Safe Crawl And Performance Collection

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#phase-7--safe-crawl-and-performance-collection).

### P07-01 — Bounded remote fetching, robots and sitemap discovery [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p07-01--bounded-remote-fetching-robots-and-sitemap-discovery-done).

### P07-02 — HTTP-first crawler and immutable observations [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p07-02--http-first-crawler-and-immutable-observations-done).

### P07-03 — Selective isolated rendering and raw/rendered comparison [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p07-03--selective-isolated-rendering-and-rawrendered-comparison-done).

### P07-04 — Canonicals, link graph, URL variants and schema diagnostics [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p07-04--canonicals-link-graph-url-variants-and-schema-diagnostics-done).

### P07-05 — Evidence-aware indexation reconciliation [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p07-05--evidence-aware-indexation-reconciliation-done).

### P07-06 — PageSpeed and CrUX current/history collection [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p07-06--pagespeed-and-crux-currenthistory-collection-done).

### P07-06a — Scalar performance job and parsed-source metadata [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p07-06a--scalar-performance-job-and-parsed-source-metadata-in_progress).

## Phase 8 — Findings, Actions, Outcomes And Customer Operations

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#phase-8--findings-actions-outcomes-and-customer-operations).

### P08-01 — Deterministic findings and opportunity evidence [blocked]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-01--deterministic-findings-and-opportunity-evidence-blocked).

### P08-01a — Verified source-limited findings substrate [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-01a--verified-source-limited-findings-substrate-done).

### P08-01b — Source-dependent candidate gaps [blocked]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-01b--source-dependent-candidate-gaps-blocked).

### P08-01bq — Genuine Search Console query–page source and overlap candidates [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-01bq--genuine-search-console-querypage-source-and-overlap-candidates-done).

### P08-01c — Scalar candidate preview and human opportunity review metadata [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-01c--scalar-candidate-preview-and-human-opportunity-review-metadata-in_progress).

### P08-02 — Intent clusters and page/action mapping [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-02--intent-clusters-and-pageaction-mapping-done).

### P08-02a — Scalar intent mapping roles and source-kind evidence [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-02a--scalar-intent-mapping-roles-and-source-kind-evidence-in_progress).

### P08-03 — Assigned action workflow and manual change logging [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-03--assigned-action-workflow-and-manual-change-logging-done).

### P08-03a — Exact scalar action source and retained usefulness metadata [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-03a--exact-scalar-action-source-and-retained-usefulness-metadata-in_progress).

### P08-03b — Exact scalar current approval and assignee roles [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-03b--exact-scalar-current-approval-and-assignee-roles-in_progress).

### P08-04 — Baselines, technical verification and outcome comparisons [blocked]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-04--baselines-technical-verification-and-outcome-comparisons-blocked).

### P08-04a — Source-limited page and crawl action follow-up [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-04a--source-limited-page-and-crawl-action-follow-up-done).

### P08-04b — Conversion/revenue attribution context [blocked]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-04b--conversionrevenue-attribution-context-blocked).

### P08-04c — Scalar action comparison roles and refreshed authority [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-04c--scalar-action-comparison-roles-and-refreshed-authority-in_progress).

### P08-05 — Early manual local assessment [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-05--early-manual-local-assessment-done).

### P08-05a — Scalar manual local-review roles and location digest [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-05a--scalar-manual-local-review-roles-and-location-digest-in_progress).

### P08-06 — Plain-language dashboard and opportunity screens [blocked]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-06--plain-language-dashboard-and-opportunity-screens-blocked).

### P08-06a — Source-aware text-first project dashboard [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-06a--source-aware-text-first-project-dashboard-done).

### P08-06b — Manual dashboard usability and accessibility evidence [blocked]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-06b--manual-dashboard-usability-and-accessibility-evidence-blocked).

### P08-06c — Exact scalar displayed organization access state [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-06c--exact-scalar-displayed-organization-access-state-in_progress).

### P08-07 — Scheduled summaries, alerts and preferences [pending]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07--scheduled-summaries-alerts-and-preferences-pending).

### P08-07a — Retained private report weekly-summary source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07a--retained-private-report-weekly-summary-source-done).

### P08-07b — Default-off self-owned project summary preference [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07b--default-off-self-owned-project-summary-preference-done).

### P08-07b1 — Enforce existing own preference GET rate budget [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07b1--enforce-existing-own-preference-get-rate-budget-done).

### P08-07c — Current optional weekly delivery source eligibility [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07c--current-optional-weekly-delivery-source-eligibility-done).

### P08-07d — Optional weekly delivery dedupe and uncertain-send kernel [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07d--optional-weekly-delivery-dedupe-and-uncertain-send-kernel-done).

### P08-07e — Default-queue bounded optional weekly discovery [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07e--default-queue-bounded-optional-weekly-discovery-done).

### P08-07f — Read-only own optional weekly delivery history source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07f--read-only-own-optional-weekly-delivery-history-source-done).

### P08-07g — Strict private own weekly delivery history GET [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07g--strict-private-own-weekly-delivery-history-get-done).

### P08-07h — Explicit native own history and truthful rollout availability [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07h--explicit-native-own-history-and-truthful-rollout-availability-done).

### P08-07i — Retained failed crawl job alert-source prerequisite [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07i--retained-failed-crawl-job-alert-source-prerequisite-done).

### P08-07j — Strict private retained crawl-failure GET [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07j--strict-private-retained-crawl-failure-get-done).

### P08-07k — Deliberate native retained crawl-failure inspector [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07k--deliberate-native-retained-crawl-failure-inspector-done).

### P08-07l — Bounded read-only integration-health metadata source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07l--bounded-read-only-integration-health-metadata-source-done).

### P08-07m — Strict private integration-health metadata GET [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07m--strict-private-integration-health-metadata-get-done).

### P08-07n — Deliberate native integration-health metadata inspector [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07n--deliberate-native-integration-health-metadata-inspector-done).

### P08-07o — Independent default-off own project alert intent [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07o--independent-default-off-own-project-alert-intent-done).

### P08-07p — Current daily crawl-failure candidate source binding [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07p--current-daily-crawl-failure-candidate-source-binding-done).

### P08-07q — Prospective revision-bound Google reconnect audit metadata [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07q--prospective-revision-bound-google-reconnect-audit-metadata-done).

### P08-07r — Current daily reconnect candidate source binding [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07r--current-daily-reconnect-candidate-source-binding-done).

### P08-07s — One-day complete operational digest source pin [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07s--one-day-complete-operational-digest-source-pin-done).

### P08-07t — Optional daily operational digest and related-episode dedupe kernel [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07t--optional-daily-operational-digest-and-related-episode-dedupe-kernel-done).

### P08-07u — Default-queue bounded optional daily digest discovery [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07u--default-queue-bounded-optional-daily-digest-discovery-done).

### P08-07v — Read-only own daily operational delivery history source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07v--read-only-own-daily-operational-delivery-history-source-done).

### P08-07w — Strict private own daily delivery history GET [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07w--strict-private-own-daily-delivery-history-get-done).

### P08-07x — Native own daily history and truthful rollout availability [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07x--native-own-daily-history-and-truthful-rollout-availability-done).

### P08-07y — Prospective original performance raw-response digest [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07y--prospective-original-performance-raw-response-digest-done).

### P08-07z — Exact-current genuine CrUX history threshold candidate source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07z--exact-current-genuine-crux-history-threshold-candidate-source-done).

### P08-07aa — Strict private exact CrUX candidate source GET [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07aa--strict-private-exact-crux-candidate-source-get-done).

### P08-07ab — Deliberate native exact CrUX history inspector [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07ab--deliberate-native-exact-crux-history-inspector-done).

### P08-07ac — Versioned material CrUX threshold candidate filter [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07ac--versioned-material-crux-threshold-candidate-filter-done).

### P08-07ad — Strict private exact CrUX material-policy GET [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07ad--strict-private-exact-crux-material-policy-get-done).

### P08-07ae — Deliberate native exact CrUX material-policy inspector [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07ae--deliberate-native-exact-crux-material-policy-inspector-done).

### P08-07af — Genuine observed CrUX source-period episode identity [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07af--genuine-observed-crux-source-period-episode-identity-done).

### P08-07ag — Independent default-off own CrUX alert intent model/service [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07ag--independent-default-off-own-crux-alert-intent-modelservice-done).

### P08-07ah — Strict private own CrUX intent GET/POST [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07ah--strict-private-own-crux-intent-getpost-done).

### P08-07ai — Separate native own CrUX optional intent form [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07ai--separate-native-own-crux-optional-intent-form-done).

### P08-07aj — Current exact CrUX recipient and collection-day source binding [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07aj--current-exact-crux-recipient-and-collection-day-source-binding-done).

### P08-07ak — Complete newest observed CrUX collection and daily digest pin [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07ak--complete-newest-observed-crux-collection-and-daily-digest-pin-done).

### P08-07al — Independent default-off CrUX delivery and related SQL claims [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07al--independent-default-off-crux-delivery-and-related-sql-claims-done).

### P08-07am — Bounded default-queue CrUX delivery worker consumer [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07am--bounded-default-queue-crux-delivery-worker-consumer-done).

### P08-07an — Independent own retained CrUX delivery history source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07an--independent-own-retained-crux-delivery-history-source-done).

### P08-07ao — Strict private own CrUX delivery history GET [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07ao--strict-private-own-crux-delivery-history-get-done).

### P08-07ap — Native own CrUX history and truthful configured availability [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-07ap--native-own-crux-history-and-truthful-configured-availability-done).

### P08-08 — Safe exports and authenticated/expiring report shares [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-08--safe-exports-and-authenticatedexpiring-report-shares-done).

### P08-08a — Final private report and share delivery authority recovery [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-08a--final-private-report-and-share-delivery-authority-recovery-done).

### P08-08b — Exact scalar private report/share metadata and refresh clearing [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-08b--exact-scalar-private-reportshare-metadata-and-refresh-clearing-in_progress).

### P08-09 — Contextual help, support and retention visibility [pending]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-09--contextual-help-support-and-retention-visibility-pending).

### P08-09a — Minimized retained project job support-reference source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-09a--minimized-retained-project-job-support-reference-source-done).

### P08-09b — Strict private exact retained job-reference GET [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-09b--strict-private-exact-retained-job-reference-get-done).

### P08-09c — Deliberate native minimized project-job reference inspector [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-09c--deliberate-native-minimized-project-job-reference-inspector-done).

### P08-09d — Immutable own-project support request kernel and CUSTOMER lifecycle [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-09d--immutable-own-project-support-request-kernel-and-customer-lifecycle-done).

### P08-09e — Private customer support journey and audited scoped staff Admin [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-09e--private-customer-support-journey-and-audited-scoped-staff-admin-done).

### P08-09f — Native contextual FAQ/glossary and retention-control discovery [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p08-09f--native-contextual-faqglossary-and-retention-control-discovery-done).

## Phase 9 — Trends And Topic Discovery

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#phase-9--trends-and-topic-discovery).

### P09-01 — Query-growth topics, safe RSS and normalization [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p09-01--query-growth-topics-safe-rss-and-normalization-done).

### P09-02 — Supported news, video and Trends integrations [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p09-02--supported-news-video-and-trends-integrations-done).

### P09-02a — Exact current-project YouTube role [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p09-02a--exact-current-project-youtube-role-in_progress).

### P09-02b — Scalar response-only YouTube page fields [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p09-02b--scalar-response-only-youtube-page-fields-in_progress).

### P09-03 — Topic scoring and research entry points [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p09-03--topic-scoring-and-research-entry-points-done).

### P09-03a — Scalar topic-review role and confirmed source controls [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p09-03a--scalar-topic-review-role-and-confirmed-source-controls-in_progress).

### P09-03b — Exact topic job history, detail and queue acknowledgment [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p09-03b--exact-topic-job-history-detail-and-queue-acknowledgment-in_progress).

### P09-03c — Retire pending topic loads on screen destruction [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p09-03c--retire-pending-topic-loads-on-screen-destruction-in_progress).

### P09-03d — Scalar current topic mapping choices [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p09-03d--scalar-current-topic-mapping-choices-in_progress).

### P09-03e — Scalar topic source catalogue and collection history [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p09-03e--scalar-topic-source-catalogue-and-collection-history-in_progress).

### P09-03f — Scalar scoped human topic review responses [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p09-03f--scalar-scoped-human-topic-review-responses-in_progress).

### P09-03g — Scalar original topic candidate evidence [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p09-03g--scalar-original-topic-candidate-evidence-in_progress).

## Phase 10 — Research And Content

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#phase-10--research-and-content).

### P09-03h — Unicode human topic-review text limits [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p09-03h--unicode-human-topic-review-text-limits-in_progress).

### P09-03i — Unicode original topic candidate bounds [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p09-03i--unicode-original-topic-candidate-bounds-in_progress).

### P09-03j — Unicode topic review form and configured market [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p09-03j--unicode-topic-review-form-and-configured-market-in_progress).

### P10-01 — Sourced opportunity/topic research [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-01--sourced-opportunitytopic-research-done).

### P10-01a — Exact scalar current-project research history [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-01a--exact-scalar-current-project-research-history-in_progress).

### P10-01b — Native research role/catalog and current selection guards [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-01b--native-research-rolecatalog-and-current-selection-guards-in_progress).

### P10-01c — Exact research job state/detail identity and destruction fence [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-01c--exact-research-job-statedetail-identity-and-destruction-fence-in_progress).

### P10-01d — Scalar reviewed-topic research handoff metadata [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-01d--scalar-reviewed-topic-research-handoff-metadata-in_progress).

### P10-01e — Positive scalar current research mapping choices [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-01e--positive-scalar-current-research-mapping-choices-in_progress).

### P10-01f — Exact supported research project role before reads [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-01f--exact-supported-research-project-role-before-reads-in_progress).

### P10-01g — Scalar research model/account catalogue and nullable output caps [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-01g--scalar-research-modelaccount-catalogue-and-nullable-output-caps-in_progress).

### P10-01h — Scalar research job counters, errors and nullable cost display [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-01h--scalar-research-job-counters-errors-and-nullable-cost-display-in_progress).

### P10-01i — Bounded scalar research sources and exact excerpt-linked interpretations [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-01i--bounded-scalar-research-sources-and-exact-excerpt-linked-interpretations-in_progress).

### P10-01j — Match submitted research model and provider account [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-01j--match-submitted-research-model-and-provider-account-in_progress).

### P10-01k — Python character bounds for research handoff labels and policy URLs [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-01k--python-character-bounds-for-research-handoff-labels-and-policy-urls-in_progress).

### P10-01l — Full Unicode research topic input [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-01l--full-unicode-research-topic-input-in_progress).

### P10-02 — Structured content briefs and internal release proof [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-02--structured-content-briefs-and-internal-release-proof-done).

### P10-02a — Current brief creation role/resources and destruction fences [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-02a--current-brief-creation-roleresources-and-destruction-fences-in_progress).

### P10-02b — Exact brief acknowledgment scope and positive source references [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-02b--exact-brief-acknowledgment-scope-and-positive-source-references-in_progress).

### P10-02c — Scalar current brief source choices [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-02c--scalar-current-brief-source-choices-in_progress).

### P10-02d — Exact Unicode human brief input bounds [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-02d--exact-unicode-human-brief-input-bounds-in_progress).

### P10-02e — Scoped bounded private brief draft responses [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-02e--scoped-bounded-private-brief-draft-responses-in_progress).

### P10-03 — Content items, revisions, approval and studio [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03--content-items-revisions-approval-and-studio-done).

### P10-03a — Exact scalar studio roles and current refresh authority [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03a--exact-scalar-studio-roles-and-current-refresh-authority-in_progress).

### P10-03b — Exact native content revision transition keys [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03b--exact-native-content-revision-transition-keys-in_progress).

### P10-03c — Stale studio save-chain and component destruction fences [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03c--stale-studio-save-chain-and-component-destruction-fences-in_progress).

### P10-03d — Unicode human content editor input bounds [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03d--unicode-human-content-editor-input-bounds-in_progress).

### P10-03e — Scalar scoped studio brief-choice provenance [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03e--scalar-scoped-studio-brief-choice-provenance-in_progress).

### P10-03f — Scalar content revision identities across existing readers [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03f--scalar-content-revision-identities-across-existing-readers-in_progress).

### P10-03g — Guard manual publication date before busy state [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03g--guard-manual-publication-date-before-busy-state-in_progress).

### P10-03h — Bounded native revision title, rationale and text readers [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03h--bounded-native-revision-title-rationale-and-text-readers-in_progress).

### P10-03i — Original private studio brief evidence guards [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03i--original-private-studio-brief-evidence-guards-in_progress).

### P10-03j — Exact private brief source status and pending-read clearing [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03j--exact-private-brief-source-status-and-pending-read-clearing-in_progress).

### P10-03k — Nullable original generation and human approval references [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03k--nullable-original-generation-and-human-approval-references-in_progress).

### P10-03l — Aware revision dates and paired manual publication metadata [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03l--aware-revision-dates-and-paired-manual-publication-metadata-in_progress).

### P10-03m — Positive original inventory and revision pagination cursors [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03m--positive-original-inventory-and-revision-pagination-cursors-in_progress).

### P10-03n — Literal manual publication URL syntax in revision readers [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03n--literal-manual-publication-url-syntax-in-revision-readers-in_progress).

### P10-03o — Aware original private brief source retrieval dates [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03o--aware-original-private-brief-source-retrieval-dates-in_progress).

### P10-03p — Aware original source-brief catalogue creation dates [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-03p--aware-original-source-brief-catalogue-creation-dates-in_progress).

### P10-04 — Draft generation and platform-specific social variants [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-04--draft-generation-and-platform-specific-social-variants-done).

### P10-04a — Exact native content model tier/account source and catalog refresh [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-04a--exact-native-content-model-tieraccount-source-and-catalog-refresh-in_progress).

### P10-04b — Native generation state, usage and unapproved draft evidence [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-04b--native-generation-state-usage-and-unapproved-draft-evidence-in_progress).

### P10-04c — Content-studio model/account catalogue scalar metadata [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-04c--content-studio-modelaccount-catalogue-scalar-metadata-in_progress).

### P10-04d — Generation request token limits and explicit free consent [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-04d--generation-request-token-limits-and-explicit-free-consent-in_progress).

### P10-04e — Scalar generation job provenance, counters and usage display [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-04e--scalar-generation-job-provenance-counters-and-usage-display-in_progress).

### P10-05 — Content inventory, expertise and lifecycle review [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-05--content-inventory-expertise-and-lifecycle-review-done).

### P10-05a — Full Unicode exact native-text lifecycle body bound [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-05a--full-unicode-exact-native-text-lifecycle-body-bound-in_progress).

### P10-05b — Unicode and serialized-byte bounds for human lifecycle commands [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-05b--unicode-and-serialized-byte-bounds-for-human-lifecycle-commands-in_progress).

### P10-05c — Full human lifecycle review declaration readers [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-05c--full-human-lifecycle-review-declaration-readers-in_progress).

### P10-05d — Combined private human review evidence ceiling [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p10-05d--combined-private-human-review-evidence-ceiling-in_progress).

## Phase 11 — Competitors And Expanded Sources

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#phase-11--competitors-and-expanded-sources).

### P11-01 — Approved competitors and bounded public comparison [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01--approved-competitors-and-bounded-public-comparison-in_progress).

### P11-01a — Current explicitly selected competitor source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01a--current-explicitly-selected-competitor-source-done).

### P11-01b — Minimized original static competitor metadata [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01b--minimized-original-static-competitor-metadata-done).

### P11-01c — Protected original single competitor document producer [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01c--protected-original-single-competitor-document-producer-done).

### P11-01d — Once-only private competitor root job [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01d--once-only-private-competitor-root-job-done).

### P11-01e — Complete private competitor root API/native delivery [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01e--complete-private-competitor-root-apinative-delivery-done).

### P11-01f — Original same-root static competitor comparison [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01f--original-same-root-static-competitor-comparison-done).

### P11-01g — Exact private same-root comparison delivery [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01g--exact-private-same-root-comparison-delivery-done).

### P11-01h — Original static pair synthesis source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01h--original-static-pair-synthesis-source-done).

### P11-01i — Bounded cited static pair AI interpretations [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01i--bounded-cited-static-pair-ai-interpretations-done).

### P11-01j — Owning provider source-transfer checkpoints [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01j--owning-provider-source-transfer-checkpoints-done).

### P11-01k — Once-only original-pair configured synthesis job [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01k--once-only-original-pair-configured-synthesis-job-done).

### P11-01l — Complete private original-pair synthesis consumers [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01l--complete-private-original-pair-synthesis-consumers-done).

### P11-01m — Original static JSON-LD type projection [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01m--original-static-json-ld-type-projection-done).

### P11-01n — Protected original schema root producer [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01n--protected-original-schema-root-producer-done).

### P11-01o — Original competitor lifecycle final-metadata authority [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01o--original-competitor-lifecycle-final-metadata-authority-done).

### P11-01p — Original comparison final-pair-metadata authority [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01p--original-comparison-final-pair-metadata-authority-done).

### P11-01q — Original private root/pair API final-metadata authority [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01q--original-private-rootpair-api-final-metadata-authority-done).

### P11-01r — Original synthesis-source final-pair-pins authority [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01r--original-synthesis-source-final-pair-pins-authority-done).

### P11-01s — Configured selection final-row original-pair authority [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01s--configured-selection-final-row-original-pair-authority-done).

### P11-01t — Original private synthesis final-own-metadata authority [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01t--original-private-synthesis-final-own-metadata-authority-done).

### P11-01u — Private synthesis API final-metadata authority [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01u--private-synthesis-api-final-metadata-authority-done).

### P11-01v — Original root final private-byte readback [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01v--original-root-final-private-byte-readback-done).

### P11-01w — Once-only private competitor schema root job [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01w--once-only-private-competitor-schema-root-job-done).

### P11-01x — Complete private competitor schema root consumers [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01x--complete-private-competitor-schema-root-consumers-done).

### P11-01y — Minimized original static competitor link categories [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01y--minimized-original-static-competitor-link-categories-done).

### P11-01z — Protected original competitor root link producer [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01z--protected-original-competitor-root-link-producer-done).

### P11-01aa — Once-only private competitor root link job [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01aa--once-only-private-competitor-root-link-job-done).

### P11-01ab — Complete private competitor root link consumers [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ab--complete-private-competitor-root-link-consumers-done).

### P11-01ac — Current explicitly selected non-root competitor page source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ac--current-explicitly-selected-non-root-competitor-page-source-done).

### P11-01ad — Protected original selected competitor page metadata producer [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ad--protected-original-selected-competitor-page-metadata-producer-done).

### P11-01ae — Once-only private exact selected competitor page lifecycle [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ae--once-only-private-exact-selected-competitor-page-lifecycle-done).

### P11-01af — Fixed private exact competitor page API and native commands [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01af--fixed-private-exact-competitor-page-api-and-native-commands-done).

### P11-01ag — Final all-original cancellation fence for saved competitor pairs [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ag--final-all-original-cancellation-fence-for-saved-competitor-pairs-done).

### P11-01ah — Read-only original same-URI selected competitor page comparisons [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ah--read-only-original-same-uri-selected-competitor-page-comparisons-done).

### P11-01ai — Complete fixed private/native original selected-page comparisons [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ai--complete-fixed-privatenative-original-selected-page-comparisons-done).

### P11-01aj — Read-only original schema-root label comparisons [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01aj--read-only-original-schema-root-label-comparisons-done).

### P11-01ak — Complete fixed private/native original schema-root comparisons [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ak--complete-fixed-privatenative-original-schema-root-comparisons-done).

### P11-01al — Read-only original link-root category comparisons [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01al--read-only-original-link-root-category-comparisons-done).

### P11-01am — Complete fixed private/native original link-root comparisons [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01am--complete-fixed-privatenative-original-link-root-comparisons-done).

### P11-01an — Minimized literal original static competitor headings [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01an--minimized-literal-original-static-competitor-headings-done).

### P11-01ao — Protected exact selected-page literal-heading producer [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ao--protected-exact-selected-page-literal-heading-producer-done).

### P11-01ap — Once-only private original selected-page heading observations [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ap--once-only-private-original-selected-page-heading-observations-done).

### P11-01aq — Complete fixed private/native selected-page heading observations [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01aq--complete-fixed-privatenative-selected-page-heading-observations-done).

### P11-01ar — Read-only original same-URI heading text/order comparisons [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ar--read-only-original-same-uri-heading-textorder-comparisons-done).

### P11-01as — Complete fixed private/native original heading comparisons [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01as--complete-fixed-privatenative-original-heading-comparisons-done).

### P11-01at — Original bounded same-origin static destination references [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01at--original-bounded-same-origin-static-destination-references-done).

### P11-01au — Protected original selected-page destination-reference producer [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01au--protected-original-selected-page-destination-reference-producer-done).

### P11-01av — Once-only private original selected-page reference observations [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01av--once-only-private-original-selected-page-reference-observations-done).

### P11-01aw — Complete fixed private/native selected-page reference observations [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01aw--complete-fixed-privatenative-selected-page-reference-observations-done).

### P11-01ax — Read-only original same-URI supported reference comparisons [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ax--read-only-original-same-uri-supported-reference-comparisons-done).

### P11-01ay — Complete fixed private/native original reference pairs [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ay--complete-fixed-privatenative-original-reference-pairs-done).

### P11-01az — Original saved heading-pair AI input and indexed citations [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01az--original-saved-heading-pair-ai-input-and-indexed-citations-done).

### P11-01ba — Read-only fixed original heading-pair model selection [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ba--read-only-fixed-original-heading-pair-model-selection-done).

### P11-01bb — Once-only private original heading-pair synthesis [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bb--once-only-private-original-heading-pair-synthesis-done).

### P11-01bc — Complete fixed private/native original heading-pair synthesis [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bc--complete-fixed-privatenative-original-heading-pair-synthesis-done).

### P11-01bd — Pure bounded original publication/update declarations [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bd--pure-bounded-original-publicationupdate-declarations-done).

### P11-01be — Protected exact-page article-date declaration producer [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01be--protected-exact-page-article-date-declaration-producer-done).

### P11-01bf — Once-only private original article-date declarations [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bf--once-only-private-original-article-date-declarations-done).

### P11-01bg — Complete fixed private/native article-date declaration consumers [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bg--complete-fixed-privatenative-article-date-declaration-consumers-done).

### P11-01bh — Read-only original same-URI article-date declaration comparisons [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bh--read-only-original-same-uri-article-date-declaration-comparisons-done).

### P11-01bi — Complete fixed private/native original date-declaration pairs [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bi--complete-fixed-privatenative-original-date-declaration-pairs-done).

### P11-01bj — Pure bounded original selected-URI Lighthouse lab evidence [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bj--pure-bounded-original-selected-uri-lighthouse-lab-evidence-done).

### P11-01bk — Current read-only selected competitor Lighthouse source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bk--current-read-only-selected-competitor-lighthouse-source-done).

### P11-01bl — Read-only selected competitor Lighthouse credential preparation [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bl--read-only-selected-competitor-lighthouse-credential-preparation-done).

### P11-01bm — Protected fixed-host competitor Lighthouse transport [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bm--protected-fixed-host-competitor-lighthouse-transport-done).

### P11-01bn — Protected current source-key-robots competitor Lighthouse producer [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bn--protected-current-source-key-robots-competitor-lighthouse-producer-done).

### P11-01bo — Once-only private selected competitor Lighthouse audit [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bo--once-only-private-selected-competitor-lighthouse-audit-done).

### P11-01bp — Complete fixed private/native competitor Lighthouse consumers [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bp--complete-fixed-privatenative-competitor-lighthouse-consumers-done).

### P11-01bq — Original saved Lighthouse lab pair arithmetic source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bq--original-saved-lighthouse-lab-pair-arithmetic-source-done).

### P11-01br — Complete original Lighthouse lab pair API/native consumers [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01br--complete-original-lighthouse-lab-pair-apinative-consumers-done).

### P11-01bs — Original single-heading AI topic-hypothesis input [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bs--original-single-heading-ai-topic-hypothesis-input-done).

### P11-01bt — Original single-heading topic model preparation [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bt--original-single-heading-topic-model-preparation-in_progress).

### P11-01bu — Once-only private single-heading topic hypotheses [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bu--once-only-private-single-heading-topic-hypotheses-in_progress).

### P11-01bv — Complete single-heading topic API/native consumers [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bv--complete-single-heading-topic-apinative-consumers-in_progress).

### P11-01bw — Two saved-page static reference structure [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bw--two-saved-page-static-reference-structure-in_progress).

### P11-01bx — Private two saved-page reference consumers [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bx--private-two-saved-page-reference-consumers-in_progress).

### P11-01by — Literal saved topic-hypothesis comparison source [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01by--literal-saved-topic-hypothesis-comparison-source-in_progress).

### P11-01bz — Shared private synthesis final-reader recovery [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01bz--shared-private-synthesis-final-reader-recovery-in_progress).

### P11-01ca — Private saved topic-hypothesis comparison consumers [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ca--private-saved-topic-hypothesis-comparison-consumers-in_progress).

### P11-01cb — Original observation and reference terminal-reader recovery [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cb--original-observation-and-reference-terminal-reader-recovery-in_progress).

### P11-01cc — Dated static and lab pair terminal-reader recovery [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cc--dated-static-and-lab-pair-terminal-reader-recovery-in_progress).

### P11-01cd — Original AI source-packet terminal-reader recovery [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cd--original-ai-source-packet-terminal-reader-recovery-in_progress).

### P11-01ce — Shared model-preparation terminal-reader recovery [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ce--shared-model-preparation-terminal-reader-recovery-in_progress).

### P11-01cf — Literal saved destination inventory source [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cf--literal-saved-destination-inventory-source-in_progress).

### P11-01cg — Private saved destination inventory consumers [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cg--private-saved-destination-inventory-consumers-in_progress).

### P11-01ch — Bounded static content-element counts [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ch--bounded-static-content-element-counts-in_progress).

### P11-01ci — Fixed protected static content-element producer [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ci--fixed-protected-static-content-element-producer-in_progress).

### P11-01cj — Once-only private static content-element lifecycle [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cj--once-only-private-static-content-element-lifecycle-in_progress).

### P11-01ck — Complete private static content-element consumers [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ck--complete-private-static-content-element-consumers-in_progress).

### P11-01cl — Original static content-element pair source [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cl--original-static-content-element-pair-source-in_progress).

### P11-01cm — Fixed private static content-element pair consumers [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cm--fixed-private-static-content-element-pair-consumers-in_progress).

### P11-01cn — Actual final private-reader authority discovery [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cn--actual-final-private-reader-authority-discovery-in_progress).

### P11-01co — Final capture-validation metadata discovery [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01co--final-capture-validation-metadata-discovery-in_progress).

### P11-01cp — Original two-page static element source [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cp--original-two-page-static-element-source-in_progress).

### P11-01cq — Complete private two-page static element consumers [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cq--complete-private-two-page-static-element-consumers-in_progress).

### P11-01cr — Pure stored article-date literal candidates [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cr--pure-stored-article-date-literal-candidates-in_progress).

### P11-01cs — Current private original date-literal candidates [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cs--current-private-original-date-literal-candidates-in_progress).

### P11-01ct — Complete private saved-Date syntax candidate consumers [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01ct--complete-private-saved-date-syntax-candidate-consumers-in_progress).

### P11-01cu — Original dated Date-candidate arithmetic source [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cu--original-dated-date-candidate-arithmetic-source-in_progress).

### P11-01cv — Complete private dated Date-candidate interval consumers [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cv--complete-private-dated-date-candidate-interval-consumers-in_progress).

### P11-01cw — Two saved-page literal heading-count source [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cw--two-saved-page-literal-heading-count-source-in_progress).

### P11-01cx — Complete private two-page heading-count consumers [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cx--complete-private-two-page-heading-count-consumers-in_progress).

### P11-01cy — Saved-topic comparison terminal-authority discovery [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cy--saved-topic-comparison-terminal-authority-discovery-in_progress).

### P11-01cz — Debug-disabled saved-topic read timing and query evidence [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01cz--debug-disabled-saved-topic-read-timing-and-query-evidence-in_progress).

### P11-01da — Saved-topic guarded reader call-cost trace [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01da--saved-topic-guarded-reader-call-cost-trace-in_progress).

### P11-01db — One transient validated source frame per private synthesis reader [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01db--one-transient-validated-source-frame-per-private-synthesis-reader-in_progress).

### P11-01dc — Current competitor app-ready automated validation [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01dc--current-competitor-app-ready-automated-validation-in_progress).

### P11-01dd — One fresh joined organization authority query [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01dd--one-fresh-joined-organization-authority-query-in_progress).

### P11-01de — Exact synthesis catalog and historical metadata scalars [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-01de--exact-synthesis-catalog-and-historical-metadata-scalars-in_progress).

### P11-02 — SERP API and scheduled rank observations [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-02--serp-api-and-scheduled-rank-observations-pending).

Local implementation2026-10-19 (D438/D437): DataForSEO Google one-query/top10 provider adapter, staff write-only encrypted credentials/reviewed location+language/price/monthly exposure, explicit exact project-origin/device observations and paused-by-default finite schedules. Immutable existing JobRun/JobStep/JobSchedule/usage, dedicated task/recovery, private API/native history/detail/cancel, dates/gaps and bounded reviewable overlap evidence are wired; customer lifecycle reused, global reservation counters survive deletion/rotation. Parent corrected independent Jobs source findings on deletion-reset budgets, stranded quota and provider-busy schedule disabling/starvation. Source migration0020 unapplied/unverified. No test additions/runs, syntax/type/lint/build/scans/runtime probes or provider effects. All automated/manual/external acceptance stays open; actual provider terms/access/spending readiness remains owner-gated. [Receipt](IMPLEMENTATION_HISTORY_2026-10-19.md#p11-02-serp-observations-and-finite-schedules-untested), [operator notes](PROVIDER_READINESS.md#serp-local-implementation--not-provider-readiness).

### P11-03 — External keyword, backlinks and optional traffic estimates [pending]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-03--external-keyword-backlinks-and-optional-traffic-estimates-pending).

### P11-04 — Authority and link-recovery opportunity management [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-04--authority-and-link-recovery-opportunity-management-in_progress).

### P11-04a — Existing-source human authority prospects [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-04a--existing-source-human-authority-prospects-done).

### P11-04b — Source-supported link verification and recovery [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-04b--source-supported-link-verification-and-recovery-in_progress).

### P11-04c — Scalar human link proposal action metadata [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-04c--scalar-human-link-proposal-action-metadata-in_progress).

### P11-04d — Scalar selected link-source and human-mention states [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-04d--scalar-selected-link-source-and-human-mention-states-in_progress).

### P11-04bv — Selected static-HTML link verification source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-04bv--selected-static-html-link-verification-source-done).

### P11-04bh — Comparable selected-source link observation history [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-04bh--comparable-selected-source-link-observation-history-done).

### P11-04bm — Body-matched existing-source mention candidates [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-04bm--body-matched-existing-source-mention-candidates-done).

### P11-04br — Saved static-target destination-recovery candidates [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-04br--saved-static-target-destination-recovery-candidates-done).

### P11-04bu — Explicit bounded static URI-reference observations [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-04bu--explicit-bounded-static-uri-reference-observations-done).

### P11-05 — Authorized local profiles, reviews and local visibility [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-05--authorized-local-profiles-reviews-and-local-visibility-done).

### P11-05a — Authorized response-only GBP profile and review reader [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-05a--authorized-response-only-gbp-profile-and-review-reader-done).

### P11-05b — Source-permitted review themes and reviewed reply proposals [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-05b--source-permitted-review-themes-and-reviewed-reply-proposals-done).

### P11-05c — Supported location-specific local visibility observations [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-05c--supported-location-specific-local-visibility-observations-done).

### P11-05d — Scalar manager roles before response-only Business Profile status [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-05d--scalar-manager-roles-before-response-only-business-profile-status-in_progress).

### P11-06 — Optional authorized bot-log imports [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11-06--optional-authorized-bot-log-imports-done).

## Phase 11A — Bounded AI Visibility

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#phase-11a--bounded-ai-visibility).

### P11A-01 — Supported surfaces and versioned prompt methodology [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11a-01--supported-surfaces-and-versioned-prompt-methodology-done).

### P11A-02 — Evidence-preserving answer collection [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11a-02--evidence-preserving-answer-collection-done).

### P11A-02s — Scheduled repeats and additional observation surfaces [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11a-02s--scheduled-repeats-and-additional-observation-surfaces-done).

### P11A-02sa — Finite opt-in native API-text repeats [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11a-02sa--finite-opt-in-native-api-text-repeats-done).

### P11A-02sb — Additional licensed or human-reported observations [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11a-02sb--additional-licensed-or-human-reported-observations-done).

### P11A-02sb1 — Consistent native human-report mention percentages [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11a-02sb1--consistent-native-human-report-mention-percentages-in_progress).

### P11A-02sb2 — Exact scalar human observation identifiers [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11a-02sb2--exact-scalar-human-observation-identifiers-in_progress).

### P11A-03 — Correctable entity extraction and deterministic rates [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11a-03--correctable-entity-extraction-and-deterministic-rates-done).

### P11A-04 — Like-for-like history, referrals and discoverability [blocked]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11a-04--like-for-like-history-referrals-and-discoverability-blocked).

### P11A-04a — Source-independent history and discoverability [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11a-04a--source-independent-history-and-discoverability-done).

### P11A-04r — Identifiable AI referrals from an exact-origin source [blocked]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11a-04r--identifiable-ai-referrals-from-an-exact-origin-source-blocked).

### P11A-05 — AI visibility release and truthful claims [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11a-05--ai-visibility-release-and-truthful-claims-done).

### P11A-05a — Scalar roles across the supported API visibility journey [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p11a-05a--scalar-roles-across-the-supported-api-visibility-journey-in_progress).

## Phase 12 — Passive Security Observations

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#phase-12--passive-security-observations).

### P12-01 — Ownership verification and passive audit scope [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-01--ownership-verification-and-passive-audit-scope-done).

### P12-02 — Passive HTTPS/TLS/header/content findings [pending]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02--passive-httpstlsheadercontent-findings-pending).

### P12-02a — Pure minimized response-header interpretation [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02a--pure-minimized-response-header-interpretation-done).

### P12-02b — Exact current passive header source binding [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02b--exact-current-passive-header-source-binding-done).

### P12-02c — Protected transient first-response header transport [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02c--protected-transient-first-response-header-transport-done).

### P12-02d — Once-only manual passive-header collector and private evidence [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02d--once-only-manual-passive-header-collector-and-private-evidence-done).

### P12-02e — Private passive-header customer consumers [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02e--private-passive-header-customer-consumers-done).

### P12-02f — Pure minimized peer-certificate date interpretation [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02f--pure-minimized-peer-certificate-date-interpretation-done).

### P12-02g — Separate current certificate/TLS exact-origin source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02g--separate-current-certificatetls-exact-origin-source-done).

### P12-02h — Protected minimized handshake-only TLS transport [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02h--protected-minimized-handshake-only-tls-transport-done).

### P12-02i — Strict original minimized TLS evidence contract [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02i--strict-original-minimized-tls-evidence-contract-done).

### P12-02j — Once-only manual TLS collector/private evidence [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02j--once-only-manual-tls-collectorprivate-evidence-done).

### P12-02k — Private deliberate TLS customer consumers [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02k--private-deliberate-tls-customer-consumers-done).

### P12-02l — Pure selected static resource-reference candidates [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02l--pure-selected-static-resource-reference-candidates-done).

### P12-02m — Independent current static-resource exact-URL source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02m--independent-current-static-resource-exact-url-source-done).

### P12-02n — Protected complete length-framed static resource transport [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02n--protected-complete-length-framed-static-resource-transport-done).

### P12-02o — Strict original minimized static resource evidence [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02o--strict-original-minimized-static-resource-evidence-done).

### P12-02p — Once-only manual static resource collector/private evidence [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02p--once-only-manual-static-resource-collectorprivate-evidence-done).

### P12-02q — Private deliberate static resource customer consumers [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02q--private-deliberate-static-resource-customer-consumers-done).

### P12-02r — Pure original first-response Location metadata [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02r--pure-original-first-response-location-metadata-done).

### P12-02s — Independent current first-response Location source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02s--independent-current-first-response-location-source-done).

### P12-02t — Protected original first-response Location transport [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02t--protected-original-first-response-location-transport-done).

### P12-02u — Strict original minimized private Location evidence [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02u--strict-original-minimized-private-location-evidence-done).

### P12-02v — Once-only manual Location collector/private evidence [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02v--once-only-manual-location-collectorprivate-evidence-done).

### P12-02w — Private deliberate Location customer consumers [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02w--private-deliberate-location-customer-consumers-done).

### P12-02x — Pure original response-header review candidates [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02x--pure-original-response-header-review-candidates-done).

### P12-02y — Current private original header-candidate source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02y--current-private-original-header-candidate-source-done).

### P12-02z — Exact private header-candidate GET consumer [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02z--exact-private-header-candidate-get-consumer-done).

### P12-02aa — Deliberate native original header-candidate inspection [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02aa--deliberate-native-original-header-candidate-inspection-done).

### P12-02ab — Genuine private header Finding relation and materialization [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ab--genuine-private-header-finding-relation-and-materialization-done).

### P12-02ac — Exact private header Finding GET/POST commands [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ac--exact-private-header-finding-getpost-commands-done).

### P12-02ad — Deliberate native header Finding materialization/current inspection [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ad--deliberate-native-header-finding-materializationcurrent-inspection-done).

### P12-02ae — Pure original static-resource review candidate [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ae--pure-original-static-resource-review-candidate-done).

### P12-02af — Current private original resource-candidate source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02af--current-private-original-resource-candidate-source-done).

### P12-02ag — Exact private resource-candidate GET consumer [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ag--exact-private-resource-candidate-get-consumer-done).

### P12-02ah — Deliberate native original resource-candidate inspection [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ah--deliberate-native-original-resource-candidate-inspection-done).

### P12-02ai — Compact original resource Finding recipes [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ai--compact-original-resource-finding-recipes-done).

### P12-02aj — Genuine private resource Finding relation and lifecycle [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02aj--genuine-private-resource-finding-relation-and-lifecycle-done).

### P12-02ak — Exact private resource Finding GET/POST commands [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ak--exact-private-resource-finding-getpost-commands-done).

### P12-02al — Deliberate native resource Finding commands/current inspection [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02al--deliberate-native-resource-finding-commandscurrent-inspection-done).

### P12-02am — Pure original certificate-date and negotiated-version review candidates [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02am--pure-original-certificate-date-and-negotiated-version-review-candidates-done).

### P12-02an — Current private original TLS-candidate source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02an--current-private-original-tls-candidate-source-done).

### P12-02ao — Exact private TLS-candidate GET consumer [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ao--exact-private-tls-candidate-get-consumer-done).

### P12-02ap — Deliberate native original TLS-candidate inspection [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ap--deliberate-native-original-tls-candidate-inspection-done).

### P12-02aq — Compact original TLS Finding recipes [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02aq--compact-original-tls-finding-recipes-done).

### P12-02ar — Genuine private TLS Finding relation and lifecycle [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ar--genuine-private-tls-finding-relation-and-lifecycle-done).

### P12-02as — Exact private TLS Finding GET/POST commands [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02as--exact-private-tls-finding-getpost-commands-done).

### P12-02at — Deliberate native TLS Finding commands and uncertainty [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02at--deliberate-native-tls-finding-commands-and-uncertainty-done).

### P12-02au — Pure original HTTP-scheme Location review candidate [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02au--pure-original-http-scheme-location-review-candidate-done).

### P12-02av — Current private original Location-candidate source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02av--current-private-original-location-candidate-source-done).

### P12-02aw — Exact private original Location-candidate GET consumer [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02aw--exact-private-original-location-candidate-get-consumer-done).

### P12-02ax — Deliberate native original Location-candidate inspection [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ax--deliberate-native-original-location-candidate-inspection-done).

### P12-02ay — Compact original Location Finding recipes [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ay--compact-original-location-finding-recipes-done).

### P12-02az — Genuine private original Location Finding relation/lifecycle [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02az--genuine-private-original-location-finding-relationlifecycle-done).

### P12-02ba — Exact private original Location Finding commands [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ba--exact-private-original-location-finding-commands-done).

### P12-02bb — Deliberate native original Location Finding commands [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bb--deliberate-native-original-location-finding-commands-done).

### P12-02bc — Exact private passive Finding human-review source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bc--exact-private-passive-finding-human-review-source-done).

### P12-02bd — Private source-bound human passive prioritization backend [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bd--private-source-bound-human-passive-prioritization-backend-done).

### P12-02be — Exact private human passive priority commands [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02be--exact-private-human-passive-priority-commands-done).

### P12-02bf — Deliberate native private passive human prioritization [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bf--deliberate-native-private-passive-human-prioritization-done).

### P12-02bg — Pure original HTTP response Location metadata [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bg--pure-original-http-response-location-metadata-done).

### P12-02bh — Independent current exact verified HTTP Location source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bh--independent-current-exact-verified-http-location-source-done).

### P12-02bi — Protected original first-response HTTP Location transport [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bi--protected-original-first-response-http-location-transport-done).

### P12-02bj — Strict original minimized private HTTP Location evidence [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bj--strict-original-minimized-private-http-location-evidence-done).

### P12-02bk — Restore final private passive byte and commercial fences [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bk--restore-final-private-passive-byte-and-commercial-fences-done).

### P12-02bl — Pin exact intended passive attempt and final metadata [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bl--pin-exact-intended-passive-attempt-and-final-metadata-done).

### P12-02bm — Once-only independently permitted private HTTP Location collector [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bm--once-only-independently-permitted-private-http-location-collector-done).

### P12-02bn — Complete deliberate private HTTP Location consumers [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bn--complete-deliberate-private-http-location-consumers-done).

### P12-02bo — Independent original HTTP and HTTPS response pair [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bo--independent-original-http-and-https-response-pair-done).

### P12-02bp — Deliberate private original HTTP/HTTPS pair delivery [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bp--deliberate-private-original-httphttps-pair-delivery-done).

### P12-02bq — Scope original passive review metadata before pinning [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bq--scope-original-passive-review-metadata-before-pinning-done).

### P12-02br — Current exact permitted redirect-chain source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02br--current-exact-permitted-redirect-chain-source-done).

### P12-02bs — Pure fresh exact-target Location resolution [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bs--pure-fresh-exact-target-location-resolution-done).

### P12-02bt — Protected explicit header-only exact-target chain transport [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bt--protected-explicit-header-only-exact-target-chain-transport-done).

### P12-02bu — Strict original minimized multi-hop evidence [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bu--strict-original-minimized-multi-hop-evidence-done).

### P12-02bv — Once-only exact redirect-chain collector and private lifecycle [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bv--once-only-exact-redirect-chain-collector-and-private-lifecycle-done).

### P12-02bw — Complete exact-chain private API and deliberate native consumers [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bw--complete-exact-chain-private-api-and-deliberate-native-consumers-done).

### P12-02bx — Pure original selected-chain review candidates [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bx--pure-original-selected-chain-review-candidates-done).

### P12-02by — Current private original chain candidate source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02by--current-private-original-chain-candidate-source-done).

### P12-02bz — Fixed private original-chain candidate GET [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02bz--fixed-private-original-chain-candidate-get-done).

### P12-02ca — Deliberate original-chain candidate native inspector [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ca--deliberate-original-chain-candidate-native-inspector-done).

### P12-02cb — Compact original selected-chain Finding recipes [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02cb--compact-original-selected-chain-finding-recipes-done).

### P12-02cc — Genuine original-chain Finding persistence and current source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02cc--genuine-original-chain-finding-persistence-and-current-source-done).

### P12-02cd — Fixed private original-chain Finding API [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02cd--fixed-private-original-chain-finding-api-done).

### P12-02ce — Deliberate original-chain Finding native consumer [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ce--deliberate-original-chain-finding-native-consumer-done).

### P12-02cf — Shared passive review source final-authority recovery [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02cf--shared-passive-review-source-final-authority-recovery-done).

### P12-02cg — Current genuine chain Finding review source [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02cg--current-genuine-chain-finding-review-source-done).

### P12-02ch — Passive human decision final-row authority recovery [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ch--passive-human-decision-final-row-authority-recovery-done).

### P12-02ci — Explicit original-chain immutable human decisions [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ci--explicit-original-chain-immutable-human-decisions-done).

### P12-02cj — Fixed private original-chain human priority API [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02cj--fixed-private-original-chain-human-priority-api-done).

### P12-02ck — Deliberate native chain human judgment delivery [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02ck--deliberate-native-chain-human-judgment-delivery-done).

### P12-02cl — Primitive passive current-owner/admin role [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02cl--primitive-passive-current-owneradmin-role-in_progress).

### P12-02cm — Scalar passive saved metadata and ownership acknowledgment [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p12-02cm--scalar-passive-saved-metadata-and-ownership-acknowledgment-in_progress).

## Phase 13 — Deployment And Operations

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#phase-13--deployment-and-operations).

### P13-01 — Environment topology, secrets and AWS identities [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p13-01--environment-topology-secrets-and-aws-identities-done).

### P13-02 — Static frontend deployment and real CDN routing [blocked]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p13-02--static-frontend-deployment-and-real-cdn-routing-blocked).

### P13-03 — Backend image release, migrations and health rollback [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p13-03--backend-image-release-migrations-and-health-rollback-done).

### P13-04 — Backup, restoration, retention and operational alarms [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p13-04--backup-restoration-retention-and-operational-alarms-done).

### P13-05 — Product site's own SEO, funnel and launch monitoring [pending]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p13-05--product-sites-own-seo-funnel-and-launch-monitoring-pending).

### P13-05a — Secret-free site monitoring template and offline coverage report [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p13-05a--secret-free-site-monitoring-template-and-offline-coverage-report-done).

## Phase 14 — Publishing And Social Integrations

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#phase-14--publishing-and-social-integrations).

### P14-01 — Requested CMS connection and approval-controlled publication [pending]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p14-01--requested-cms-connection-and-approval-controlled-publication-pending).

### P14-02 — Official social scheduling and first-party analytics [pending]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p14-02--official-social-scheduling-and-first-party-analytics-pending).

## Phase 15 — Usage-Based Refinement And Scale

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#phase-15--usage-based-refinement-and-scale).

### P15-01 — Refine allowances, cost and retention from actual use [pending]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p15-01--refine-allowances-cost-and-retention-from-actual-use-pending).

### P15-02 — Managed data services and independent worker/API scaling [pending]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p15-02--managed-data-services-and-independent-workerapi-scaling-pending).

## Phase 16 — Repository-Aware Remediation

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#phase-16--repository-aware-remediation).

### P16-01 — Explicit repository connection and isolated analysis [in_progress]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p16-01--explicit-repository-connection-and-isolated-analysis-pending).

2026-10-19 D439/D437: missing GitHub App source authorization is implemented, untested: exact project/actor/session/repository ID/name/commit PKCE, short-lived encrypted credentials/read-only installation proof, staff write-only configuration, token-specific disconnect, signed revocation, human recovery and private native controls. Secret inventory/closure/deletion includes new records; organization-owner recovery covers unknown consents after project-retention expiry. Independent tenancy source findings on cross-project grant revocation and expired-project cleanup were corrected; reread found no further issue in those corrections. Migration0021 is unapplied. No tests/checks/runtime/migration or real source/analysis operation. **Still undone:** disposable isolated runner and resource/network/secret limits; scoped collector/jobs/artifacts/API/native analysis; original independent Security review gate and all automated/manual/provider acceptance. Consent does not collect/execute code. [Receipt](IMPLEMENTATION_HISTORY_2026-10-19.md#p16-01-repository-consent-and-lifecycle-untested), [D439](DECISIONS.md#d439-read-only-github-repository-consent-before-isolated-analysis).

2026-10-19 D440 supersedes the previous slice's missing-runner status: initial exact-commit root package.json/pyproject.toml/requirements.txt collection and offline declared-dependency parser are written, untested/default disabled. New dedicated rootless Engine/controller and runner, strict resource/network/storage/output limits, bounded13 durable GitHub attempts/usage, immutable source/method, cancellation/cleanup/recovery and private API/native history/results/request-key lookup are wired into existing jobs/lifecycle/export/settings. Dedicated controller remains a container on a separate rootless host; no Docker socket/credentials enter disposable analysis. Advisory Jobs/Deployment source review found a partial tar-upload race; ordered final readiness marker corrected it. Original marked Security gate is deferred, not satisfied by advisories. [Runbook](REPOSITORY_ANALYSIS.md), [receipt](IMPLEMENTATION_HISTORY_2026-10-19.md#p16-01-isolated-root-manifest-analysis-untested). **Still undone:** broader authorized dependency/code scanning beyond this declared-manifest inventory; P16-02 coding-agent patches/checks/PRs; all automated/manual/isolation/security/provider acceptance. No new migration, test/test addition/build/type/lint/syntax/scan/runtime/provider/repository/Docker operation; earlier migrations remain unapplied. No installed-version/CVE/whole-repository/readiness claim or verified-count increase.


2026-10-20 D441/P16-01 preceding slice: optional OSV dependency advisory lookup is implemented, untested/default disabled, reusing original consent/parser/controller/job/cleanup/private delivery. Exact declared pins only, separate explicit metadata-disclosure consent and frozen review reference; one <=50-query fixed-host batch, <=14 actual request units (13GitHub+1OSV), no automatic follow-up, <=100 retained provider IDs with timestamps/receipt/fingerprint and explicit no-exact-pin/partial/pagination/retention gaps. Native/API/history/usage/export and deployment knobs are wired. Bounded Jobs source advisory found no actionable backend issue; no tests/checks/provider requests or acceptance. Broader resolved/transitive/code analysis and P16-02 agent patch/check/PR remain absent; marked Security/actual containment/privacy/provider/manual gates stay open. [Receipt](IMPLEMENTATION_HISTORY_2026-10-20.md#p16-01-explicit-osv-advisory-lookup-untested), [D441](DECISIONS.md#d441-explicit-osv-advisory-lookup-for-supported-exact-declared-root-pins).

2026-10-20 D442: separate bounded root npm package-lock.json v2/v3 analysis/advisory source is implemented, untested/default disabled. One exact-commit512KiB file, <=5000 entries/50 unique supported public-registry versions, explicit missing/excluded/omitted counts, strict data-only path/name/version/tarball profile and no installs/URL following. Frozen parser/advisory methods,11GitHub+1OSV maximum12-unit accounting, blob-only larger transport/envelope limit, source/disclosure UI acknowledgements/reset, mode-scoped keys and private export/provenance are wired; old modes retain limits. Bounded Jobs source advisory reported no actionable backend defect, with UI outside review; no tests/checks/scans/runtime/provider/container operations. Actual/formal Security/provider/privacy/manual acceptance and code/agent/P16-02 remain open. [Receipt](IMPLEMENTATION_HISTORY_2026-10-20.md#p16-01-root-npm-lockfile-advisories-untested), [D442](DECISIONS.md#d442-bounded-root-npm-lockfile-advisory-analysis).

2026-10-20 D443: selected Python call observations are implemented, untested/default disabled. Explicit exact-commit .py path<=240 ASCII characters/6 segments and regular file<=128KiB, nonrecursive path-only Git traversal rejecting symlinks/submodules, offline ast-only parser with no imports/execution. Four fixed literal syntax rules, <=50000 nodes/100 retained sorted locations, SHA256/line/UTF8-byte columns and missing/syntax/omitted coverage; no snippets/arguments/identifiers or vulnerability/clean-security inference. Maximum10+segments<=16 GitHub attempts, no OSV/model/agent send; code cleanup step17 and fixed-name lookup avoid collision with attempts13–16. Existing private API/native/history/export and path-digest uncertainty keys are wired. Bounded Jobs source advisory found no actionable backend defect; UI parent-inspected, formal isolation/Security/automated/manual/provider acceptance still pending. No tests/checks/runtime/provider/repository/container operations. L901 coding-agent integration/P16-02 patches/checks/PRs remain genuinely undone. [Receipt](IMPLEMENTATION_HISTORY_2026-10-20.md#p16-01-selected-python-call-observations-untested), [D443](DECISIONS.md#d443-selected-python-call-syntax-observations).

### P16-02 — Proposed patches, repository checks and human-reviewed PRs [pending]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#p16-02--proposed-patches-repository-checks-and-human-reviewed-prs-pending).

## Agent Tooling Follow-Up

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#agent-tooling-follow-up).

### TOOL-01 — Ground implementation guidance in real source patterns [done]

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#tool-01--ground-implementation-guidance-in-real-source-patterns-done).

### TOOL-02 — Register universal roles and upgrade Sol subagents [done]

Current routing: D430 supersedes D424; the five GPT-6.1 Sol reviewers use medium reasoning in Codex/OpenCode. This bounded settings update does not close the pending whole TOOL-02 contract in the Local completion table. Validation receipt: [reviewer guide](../.agents/README.md#opencode).

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#tool-02--register-universal-roles-and-upgrade-sol-subagents-done).

### TOOL-03 — Local unattended fresh-session continuation [done]

D436 user-requested speed change complete2026-10-12: Fast disabled for the main coder and every subagent of future timer sessions; explicit default-tier/false-feature CLI overrides replace D432. Exact command/owning guards, native configuration and prompt-free three-model standard-speed probes, eight unchanged inheriting role configs and timer cadence checks PASS. Existing sessions not restarted; actual inference/served tier and whole TOOL-03 acceptance remain unverified. Initial probe/check setup failures and concurrent global-tier change recorded in [host validation](../.agents/README.md#local-unattended-codex-continuation); local ratios unchanged.

2026-10-12 host repair complete: user asks for the solution to overnight missing-status skips. CLI configuration overrides selected an embedded server outside the watcher’s shared daemon. Future timer TUIs explicitly connect to that watched local Unix endpoint with explicit project cwd; only the exact endpoint is exempted from the remote guard. Legacy nonremote config/profile/feature clients block even when another idle thread exists. D427 selection: existing cases lacked trusted monitored-endpoint/native visibility and legacy embedded-client coverage; extended owning command/activity assertions, including attached-profile and post-`--` prompt parsing regressions found by deployment review. `check-codex.py`, `check-idle-launch.py`, `check-status.py`, `check.py` and changed Python syntax PASS; prompt-free native TUI exposes an idle project thread and Sol6.1/medium/Fast. Deployment reviewer reread both fixes with no remaining actionable finding; no tests/operational APIs by reviewer. `check.py` initial D124 checkpoint-reference failure followed concurrent compaction; restored receipt and rerun PASS, no weakened assertion. D124/D131/activity/startup/locks/retention/one-minute/global-config controls unchanged. Probe-only sessions exited; no existing session interruption, inference/application test or timer restart. Redacted doctor diagnostics did perform provider HTTP/WebSocket connectivity checks without inference. Native automatic launch after this change and actual served tier/tool availability remain unverified; whole TOOL-03 acceptance/ratios pending. Source snapshots/check/review receipt `/tmp/organicseoops-timer-status-0bdvyxpg/`; [host route](../.agents/README.md#local-unattended-codex-continuation).

Current host guard: D434 supersedes D433; idle/input-waiting timer sessions permit a fresh launch, active coding/subagents still block. Restore D381 managed-idle/startup/native-child checks; preserve native activeFlags and permit only exact waitingOnUserInput, retaining approval/unknown/error/unavailable blockers. D427 gap: existing protocol/guard cases discarded/omitted waiting flags; extend those owning cases plus repeated active no-launch/idle-wait eligibility. Focused protocol/activity/idle-launch cases and bounded deployment source review PASS. D435 strengthens unattended prompt choices and adds timer-only native optional question-tool false override; existing exact command/prompt/activity/pause checks and native config-layer probe PASS (live inference/tool availability unmeasured). D431/D436 timer-only Sol 6.1/medium with Fast disabled for all agents, one-minute cadence, D124/D131 pause/startup/lock controls and retention unchanged. This bounded correction does not close whole TOOL-03 acceptance/ratios or establish the original overlap cause. Host paths and receipt: [continuation guide](../.agents/README.md#local-unattended-codex-continuation).

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#tool-03--local-unattended-fresh-session-continuation-done).

## Release Evidence Checklists

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#release-evidence-checklists).

### GATE-FOUNDATION

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#gate-foundation).

### GATE-INTERNAL

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#gate-internal).

### GATE-PUBLIC

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#gate-public).

### GATE-AI

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#gate-ai).

## Complete Source-To-Execution Coverage

Historical reference: [original section](IMPLEMENTATION_TASKS_ARCHIVE_2026-10-10.md#complete-source-to-execution-coverage).
