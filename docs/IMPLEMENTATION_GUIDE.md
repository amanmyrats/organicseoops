# OrganicSEOOps Implementation Guide

**D437 — current user instruction (2026-10-19): implementation only.** Work only on genuinely unfinished local implementation. Preserve completed archived work and skip cards whose remaining work is testing, evidence reconciliation or release validation. Do not run tests, test maintenance, builds, type/lint checks, scans, runtime validation or final acceptance until the user explicitly requests testing. Do not add tests during this phase. Record new code as implemented but untested; keep automated/manual/external acceptance pending. Existing authorization, tenant isolation, validation, human approval and external-operation limits still apply. D437 overrides earlier automatic-check requirements and test-based continuation triggers.

D429 targets all already-planned local implementation/automated acceptance under [plan §0](PROJECT_PLAN.md#0-first-working-release--frozen-scope-d426). Finish the current R05/R06 automated stage, then existing roadmap P/TOOL contracts. Human/external gates remain separate. Original contracts/evidence are preserved in the archives; per-slice command packets are not automatic checks to replay.

P16-01 adds explicit selected Python call observations (D443), implemented but untested/default disabled: one exact-commit user-selected .py file, <=240 ASCII path characters/6 segments/128KiB, offline ast parsing of four fixed literal call patterns, <=50000 nodes/100 retained locations and explicit missing/syntax/omitted coverage. No source execution, retained snippets, OSV/model/agent request or vulnerability/clean-security claim. API/native/history/export, path-digest uncertainty keys and maximum16 GitHub-attempt accounting are wired; existing consent/inventory/declared-pin/npm-lock/Yandex/SERP and archived completed work remain credited. **Next undone:** P16-01 coding-agent integration and P16-02 reviewed patches/repository-check/PR implementation, subject to existing dependency/security gates. Migrations0018–0021 remain unapplied; all automated/manual/isolation/security/provider acceptance is pending. No tests or checks were added/run. Do not redo completed portions or acceptance-only cards. D437 defers every check and the marked isolation/security gate; no actual repository/provider/Docker/agent/scanning operation is selected. [Checkpoint](IMPLEMENTATION_STATE.md), [selected-source preparation](REPOSITORY_ANALYSIS.md#selected-python-call-observations).

## 1. Start Or Resume In Any Model

Read AGENTS.md, the checkpoint, active R/P/TOOL card and current local status. Read only matching plan/decision sections, selected archived contract and named source/tests. After the basic automated stage, classify the full documented inventory once in the Local completion table; do not repeat that inventory or audit unrelated code every session. Use CONTINUE.md for continuation.

Reconcile the checkpoint once; preserve partial edits, operation ownership and user changes. Complete the current R05/R06 automated stage first; existing lifecycle/roadmap work is then authorized under D429, not a new speculative feature. If another session owns an operation, avoid its actual files/DB/services and do independent work permitted by the current stage first. D428 permits only CONTINUE.md's same-session terminal-receipt wait when none remains; no progress polling or duplicate run.

## 2. Document Responsibilities And Precedence

The latest user direction/plan §0 control scope. The ledger's Local completion table owns current requirement/card classification and verified local implementation/automated status; R rows own basic-release acceptance, TODO owns scope/release checkboxes, and the checkpoint owns current operation/next action. Archives retain original contracts/evidence, not current acceptance. Mixed manual/external gates stay open separately.

## 3. Required Reading And Resource Routing

Use [the document map](../.agents/references/project-documents.md). SEO/source/crawl/content changes require the shared SEO rule/map; account/public/billing/UX/closure changes require the SaaS rule/map. Read relevant canonical sections on demand; the complete plan is a specification, not a per-session reading assignment. Reviewer invocation follows `AGENTS.md` and `.agents/README.md`; native adapters keep their existing assignments and permissions.

## 4. Execution Order And Release Gates

First finish the current R05 repair/R06 automated result; reconcile implemented basics rather than rebuilding them. Then work existing phase1–16/3A/11A/TOOL local contracts in dependency order under D429. Reuse focused-checked prerequisites with their evidence limits; known failed security/migration/data-loss contracts still block actual dependents. A human/external gate does not block unrelated local work. Keep existing IDs and no speculative features/suffixes.

Finish the already-selected R06 automated stage without postponement for roadmap work. Keep its unavailable manual walkthrough unfinished; after local automated closure, classify all existing documented requirements once and continue authorized roadmap coding even if that manual gate remains. At full local coding/focused/review closure, select final current-source automated validation under D375/D423/D425 and reuse only still-valid evidence. Exhaustion/pause now requires no dependency-ready planned local work or required operation across the full scope, with actual unresolved gates listed. Context/tool limits remain ordinary handoffs.

D428's basic sequence remains: backend result → tested R05 repair → named failures/invalidated evidence → walkthrough or explicit manual/tool gate. D429 then continues all existing local contracts under [CONTINUE.md](../CONTINUE.md#complete-all-planned-local-work-d429); small patch/test/card/basic-stage completion is not a stopping point. Unchanged waits/browser failures do not trigger scans/tests/history writes. Guidance updates never establish application acceptance.

## 5. Coding Contract For Every Task

Make the smallest complete repair across its actual callers/tests/config. Reuse the house patterns, standard library and installed dependencies. No framework, generic provider abstraction, speculative model, vector database, visual workflow engine, performance rewrite without a core failure, or unrelated cleanup.

Preserve organization/project scoping through every API/job/artifact/cache/export; server permissions separate from entitlements; transactional race-sensitive invariants; validated bounded input/output; private storage and redacted secrets; OAuth/source identity; SSRF protections; original source dates/coverage; durable jobs, cancellation, idempotency and exactly-once budget settlement. External/model input is untrusted. Missing data is unavailable, and before/after is not causation. Human approval remains tied to the reviewed revision.

Keep API/workers/Beat/database/broker/proxy separate, Angular public HTML/native CSS prerendered and app CSR. No production Node renderer. Preserve accessible labels/focus/keyboard/error states and visible project context. Keep existing exact dependency pins, lockfiles, migration ordering and local environment/credential/volume conventions in AGENTS.md; no bootstrap secrets in customer settings.

## 6. Verification And Definition Of Done

D427: inspect existing owning tests before adding cases. Reuse meaningful coverage when it already verifies the changed contract; otherwise briefly name the uncovered failure/risk and extend the owning case/spec with the smallest observable-behavior check. No automatic spec per edit/helper/field, mandatory red-first cycle, duplicate layer assertions, coverage-percentage target or speculative case catalogue. Trivial/behavior-preserving changes use appropriate static/type/manual checks; untested non-trivial logic and genuine sensitive risks still require meaningful automated coverage. Stop adding tests when the changed behavior/risk is covered. Keep existing assertions and final validation; no speculative coverage or test cleanup merely to reduce counts; selected D429 roadmap contracts get their actual needed checks.

Apply D375/D423/D425: exact changed-behavior tests/types during coding; relevant regression once for a stable coherent flow; full validation at the already-selected R06 stage, full-roadmap local coding closure or explicit request. Never replay old command packets. Backend runtime uses one initial `./backend-dev.sh status`, existing healthy services, exact `quicktest` cases and conditional allowlisted `quickmanage` checks; frontend/docs-only work needs no backend startup. Reload changed workers once before affected runtime evidence; rebuild only for a real dependency/configuration/checkpoint need.

Track separately: **implementation** (`unchecked`, `needs_fix`, `implemented`); **focused verification** (`pending`, `pass/reused`, `failed`); **final acceptance** (`R06 pending`, `pass`, `failed`); and **external readiness** (`R07 unverified`, with named blockers). Do not upgrade historical statuses or a focused pass to final/public readiness. A core card closes coding when its scoped contract is implemented and focused checks/source review are valid; it still awaits R06 acceptance. Required migration safety, security/data-loss boundaries and known failures are never deferred past their actual dependency.

Use marked original review scopes and existing genuine current source coverage. Invoke `security-reviewer` only for an active R/P/TOOL card's Security review gate, including its selected original archived contract, or a direct user request, once after focused evidence; repeat only for unresolved critical findings or material trust-boundary redesign. This preserves D077's marked-card allowlist, not a review of every roadmap card. Bounded specialist review is selective; actual file/symbol/line proof is required. Unavailable tools mean review unavailable, with parent fallback separate and required independent coverage pending. Reviewers do not run tests.

R06 checks the recorded current candidate and practical core journey. Collect genuine terminal results, repair named failures and rerun only invalidated coverage. R07 preserves actual provider/public/legal/hosted checks and no real customer/provider/deployment claim follows from fixtures.

## 7. Durable Checkpoint And Recovery Protocol

D131 exhaustion-pause follows [CONTINUE.md](../CONTINUE.md#complete-all-planned-local-work-d429): pause only after dependency-ready D429 local work and required operations are exhausted; context/tool interruptions require an ordinary handoff. Host invocation and D431/D436 timer-only Sol 6.1/medium selection with Fast disabled for the main coder and all subagents, plus D434 active-coding gate with idle/input-wait eligibility and D435 unattended recommended-choice/native question-tool suppression, live in [.agents/README.md](../.agents/README.md#local-unattended-codex-continuation). TOOL-03’s 2026-10-12 repair explicitly connects new timer TUIs to the watched local daemon with project cwd; old embedded configured clients remain blocking until normal exit, and unknown activity never becomes idle by timeout.

Keep only authorization, active R/P/TOOL card/one next action, paths/evidence, unfinished operations/gates and external effects. Update at a coherent slice or genuine handoff, not every tool call. Archive detailed receipts once; ordinary repairs need no decision narrative. The ledger's current local inventory reports per-phase/overall implementation and automated-acceptance ratios only after complete classification; preserve full totals and named human/external exclusions rather than manipulating archived percentages.

On hard interruption, inspect actual source/operation state before replay. Unknown results remain unknown. Credentials/volumes/dev services stay in place. Never overwrite another session's partial work or signal its operation merely because the milestone changed.

## 8. Unresolved Decision Register

Existing offer/provider/locale/retention choices remain in the plan and named historical decisions. R07 records actual missing approvals/evidence; do not invent legal terms, activate disabled closure, change chosen model/provider or ask for secrets to implement locally. No new product decisions are required for an honest unavailable state in the basic local flow.

## 9. Source Coverage And Maintenance

Use plan §0 and the Local completion table for the current basic-then-full local scope. Preserve archives, original IDs/anchors, gates and evidence. TODO summarizes all already-planned local phases and separate manual/external work. Do not erase requirements/code/assertions/failures, shrink the denominator or label unsupported capabilities done to make percentages reach 100%.


### Default continuation policy (D068)

Historical reference: [original section](IMPLEMENTATION_GUIDE_ARCHIVE_2026-10-10.md#default-continuation-policy-d068); D426 and the current guide control execution.

### Copy-paste prompt: begin implementation

Historical reference: [original section](IMPLEMENTATION_GUIDE_ARCHIVE_2026-10-10.md#copy-paste-prompt-begin-implementation); D426 and the current guide control execution.

### Copy-paste prompt: continue after interruption or change of model

Historical reference: [original section](IMPLEMENTATION_GUIDE_ARCHIVE_2026-10-10.md#copy-paste-prompt-continue-after-interruption-or-change-of-model); D426 and the current guide control execution.

### Copy-paste prompt: checkpoint now

Historical reference: [original section](IMPLEMENTATION_GUIDE_ARCHIVE_2026-10-10.md#copy-paste-prompt-checkpoint-now); D426 and the current guide control execution.

### Practical execution lanes

Historical reference: [original section](IMPLEMENTATION_GUIDE_ARCHIVE_2026-10-10.md#practical-execution-lanes); D426 and the current guide control execution.

### Named milestone checks

Historical reference: [original section](IMPLEMENTATION_GUIDE_ARCHIVE_2026-10-10.md#named-milestone-checks); D426 and the current guide control execution.

### 5.1 Before changing files

Historical reference: [original section](IMPLEMENTATION_GUIDE_ARCHIVE_2026-10-10.md#51-before-changing-files); D426 and the current guide control execution.

### 5.2 Source layout and dependencies

Historical reference: [original section](IMPLEMENTATION_GUIDE_ARCHIVE_2026-10-10.md#52-source-layout-and-dependencies); D426 and the current guide control execution.

### 5.3 Ownership, API and persistence

Historical reference: [original section](IMPLEMENTATION_GUIDE_ARCHIVE_2026-10-10.md#53-ownership-api-and-persistence); D426 and the current guide control execution.

### 5.4 Jobs, costs, integrations and SEO

Historical reference: [original section](IMPLEMENTATION_GUIDE_ARCHIVE_2026-10-10.md#54-jobs-costs-integrations-and-seo); D426 and the current guide control execution.

### 5.5 Frontend and customer experience

Historical reference: [original section](IMPLEMENTATION_GUIDE_ARCHIVE_2026-10-10.md#55-frontend-and-customer-experience); D426 and the current guide control execution.

### 5.6 Specialist security review gates

Historical reference: [original section](IMPLEMENTATION_GUIDE_ARCHIVE_2026-10-10.md#56-specialist-security-review-gates); D426 and the current guide control execution.

### Task states

Historical reference: [original section](IMPLEMENTATION_GUIDE_ARCHIVE_2026-10-10.md#task-states); D426 and the current guide control execution.

### Checkpoint cadence

Historical reference: [original section](IMPLEMENTATION_GUIDE_ARCHIVE_2026-10-10.md#checkpoint-cadence); D426 and the current guide control execution.

### Resume reconciliation, including a hard crash

Historical reference: [original section](IMPLEMENTATION_GUIDE_ARCHIVE_2026-10-10.md#resume-reconciliation-including-a-hard-crash); D426 and the current guide control execution.
