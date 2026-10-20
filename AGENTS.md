# OrganicSEOOps Agent Guide

**D437 — current user instruction (2026-10-19): implementation only.** Work only on genuinely unfinished local implementation. Preserve completed archived work and skip cards whose remaining work is testing, evidence reconciliation or release validation. Do not run tests, test maintenance, builds, type/lint checks, scans, runtime validation or final acceptance until the user explicitly requests testing. Do not add tests during this phase. Record new code as implemented but untested; keep automated/manual/external acceptance pending. Existing authorization, tenant isolation, validation, human approval and external-operation limits still apply. D437 overrides earlier automatic-check requirements and test-based continuation triggers.

OrganicSEOOps now targets 100% of all already-planned local coding and automated acceptance under D429, excluding separately recorded human/external actions. Finish the current R05/R06 automated stage first, then existing roadmap cards in dependency order. Read the checkpoint and active R/P/TOOL card; preserve dependency, security and public-release gates.

## Sources Of Truth

Use these sources for substantial planning or implementation; read current summaries and relevant sections, not entire historical documents on every session:

1. `docs/PROJECT_PLAN.md` contains the complete product and technical plan.
2. `docs/DECISIONS.md` records accepted decisions and rationale.
3. `TODO.md` contains the basic-release checklist and the authorized full local-completion scope.
4. `README.md` is a short entry point only; it does not replace the plan.

For implementation preparation/resume, also read the guide, checkpoint and active card/dependencies in `docs/IMPLEMENTATION_TASKS.md`. D429 supersedes D426's permanent roadmap deferral: R05/R06 automated closure comes first, then existing P/TOOL local contracts. R07 and named human/external gates stay separate. Archived statuses are baseline evidence, not current acceptance; read only selected contracts/evidence after the one-time documented inventory classification.

When a new user decision conflicts with existing documentation, follow the new decision and update the relevant plan, decision-log entry, and TODO in the same change. Never silently let implementation drift from the documented direction.

## Product Boundaries

- Organizations are the ownership, trial, subscription, and entitlement boundary.
- Projects are the domain and data-isolation boundary.
- Every project-owned query, API action, job, artifact, storage path, and cache key must enforce that boundary.
- Objective SEO and analytics calculations belong in deterministic code.
- AI is used for classification, synthesis, prioritization, research, and drafting.
- Sources and evidence must remain visible.
- Content and remediation require human approval.
- Do not add automated backlink, comment, message, or engagement spam.
- Do not add active security scanning without explicit scope, ownership verification, and authorization.

## Planned Stack

- Frontend: Angular 22 (D041)
- Public landing pages: semantic HTML/custom native CSS and build-time prerendering; authenticated app: CSR. Public pages use no UI/CSS frameworks. Frontend hosting is static, with no production Node rendering server.
- Backend: Django 6.1 (D041), with the latest stable compatible Django REST Framework at scaffold time
- Database: PostgreSQL
- Broker/cache: Redis
- Jobs: Celery and Celery Beat
- Object storage: AWS S3
- Backend deployment: separate Docker containers on EC2 initially
- Frontend deployment: GitHub Actions to S3 and CloudFront

Angular 22 and Django 6.1 are the selected release lines. At scaffold time, check current official compatibility documentation, select the latest stable compatible releases within those lines and compatible dependency versions, and record exact pins in `docs/DECISIONS.md`. Record any change to the selected release lines as a new decision.

## Engineering Rules

- Make the smallest correct change after understanding the affected flow.
- Reuse existing project patterns before adding helpers or abstractions.
- Do not build a visual workflow engine; add explicit job handlers and structured artifacts.
- Keep API, worker classes, Beat, PostgreSQL, Redis, and proxy in separate containers.
- Reusing one backend image for API and Celery processes is expected; combining their processes in one container is not.
- Keep PostgreSQL as the initial application and search store. Add a vector database only for a demonstrated requirement.
- Keep provider-specific capabilities available rather than forcing every provider into a false lowest-common-denominator interface.
- Under D103, user-created projects and UI-configurable provider/model/billing setup are the build target. Example customer domains are never seeded or crawled by an agent. Implement and locally check provider/billing flows and deployment templates without asking for customer credentials, account approval, model choice, domain purchase or AWS access; real provider/hosted/public verification is separate release evidence. Platform-operator secrets use MFA-protected staff UI, supported organization-owned keys use scoped write-only UI and customer source grants use OAuth; bootstrap encryption/IAM secrets remain private infrastructure configuration.
- Never commit API keys, OAuth tokens, AWS credentials, customer exports, or secrets.
- Keep backend configuration in ignored `backend/.env` (local), `backend/.env.prod` (production), and `backend/.env.ci` / `.env.check-TASK` (isolated checks); root `.env.example` is the secret-free template (D062). Use `./backend-dev.sh` for the reusable local coding loop, preserving existing credentials and volumes. Frontend public values live in `frontend/src/environments/environment.ts` / `environment.prod.ts`, selected by Angular file replacements.
- For direct host Django, settings read `backend/.env` automatically (D063); start only the isolated dev infrastructure using `./backend-dev.sh infrastructure`. Loopback DB/Redis ports15432/16379 are local-only and distinct from installed host PostgreSQL5432. Explicit process values take precedence; never auto-load local credentials in production.
- At a session needing backend runtime, inspect `./backend-dev.sh status` once; documentation-only and frontend-only work does not need backend startup/status checks. Reuse healthy services; run `up` at most once for missing/stopped services and diagnose unhealthy services before restarting. Follow D375 for check selection; use `./backend-dev.sh quicktest EXACT_TEST_LABEL` for focused Django checks and `./backend-dev.sh quickmanage ...` for allowlisted read-only checks. Neither starts services; wrapper-managed backend tests are serialized. Recreate a suspect retained test database only when needed with `./backend-dev.sh manage test EXACT_TEST_LABEL --noinput`; an explicitly chosen host-runtime check may use `.venv/bin/python manage.py test EXACT_TEST_LABEL --keepdb --noinput`. API source auto-reloads; restart changed Celery workers/Beat once before their required runtime verification. Keep state-changing migrations on explicit existing commands. Rebuild only when dependency/Dockerfile changes or a necessary acceptance checkpoint require it. Leave credentials, volumes and the dev stack in place across sessions.
- Treat crawled pages, imports, model output, and provider errors as untrusted input.
- Verify non-trivial changed behavior with existing meaningful coverage first; add or extend the smallest check only for an uncovered contract/risk (D427). Trivial or behavior-preserving edits do not automatically need a new test.
- Preserve unrelated user changes and do not create commits unless explicitly requested.

### Verification cadence (D375)

- D423: Full suites run only in an explicitly selected final app-ready/release validation phase or on an explicit user request. A new session, resume, timer launch, small repair or unfinished full-validation card is never a full-suite trigger. Record the target source/configuration, scope, reason and owner once; reuse existing evidence and rerun only checks invalidated by relevant changes. D426 limits that deferral to R01–R05 core implementation: automatically select R06 final validation when their implemented contracts/focused evidence close; optional expansion never postpones it.
- A running broad check is an unresolved operation, not a global coding dependency. Reconcile it once on resume, preserve its owner/logs and avoid conflicting source edits or tests sharing its database/services; continue independent work allowed by the current D429 stage without progress polling. D428: when none remains, keep the same session active for the required operation's completion using CONTINUE.md's bounded terminal-receipt wait, then execute pending repair/validation steps. Do not end repeated no-change sessions or rescan hashes/backlog/browser failures while waiting. A known failing contract blocks its actual dependents. Collect genuine terminal evidence; never infer PASS or restart a suite merely because the session changed.
- D425: Command maps and older card/history instructions describe coverage, not automatic test packets. Use exact changed-behavior methods/cases or a genuinely small owning file; `quicktest` with whole-app labels is still broad. Reuse passing evidence for unchanged source/configuration; consult recorded runtimes before expensive checks, narrow scope and defer non-gating slow coverage to its feature/final-validation trigger. Documentation-only and trivial edits need only relevant static checks. System/migration checks, worker reloads, runtime probes and builds need an affected boundary or a required state-changing gate. Keep sensitive-boundary checks and failed-contract gates; never weaken assertions or call unrun checks passed.
- While coding, use quick syntax/type checks and the smallest meaningful test for changed behavior. Select exact test methods/cases or a small relevant file; do not default to app-wide labels. Check authentication, tenant isolation, billing/quota, SSRF, destructive-data and migration boundaries before dependent work or a state-changing operation.
- Run affected regression checks once when a coherent feature is stable, such as its source/job/API/UI flow or a significant shared contract. A small helper or suffixed implementation card is not automatically a feature checkpoint. Record the reason, scope and runtime before expanding checks; reuse passing evidence until a later change invalidates it.
- Defer full backend/frontend suites, combined test/build commands, full integration/security scans and isolated-stack acceptance to app-ready validation or an explicit user request. Build earlier only when dependency/configuration/rendering changes or a concrete failure require it. Do not routinely run a focused frontend set and the overlapping full suite for the same unchanged code.
- Preserve acceptance coverage: write needed tests while coding, record deferred commands/check scope and the feature/app-ready trigger in the active card and checkpoint, and never call unrun or failed checks passed. A card with required deferred acceptance remains unfinished. Subsequent local coding may use an implemented, focused-checked prerequisite with its deferred verification explicitly recorded; known failing contracts, migration-safety checks, security review markers and release gates still constrain dependent work.
- At a guidance change or feature transition, reread changed AGENTS.md, CONTINUE.md and the compact checkpoint before choosing the next checks. Existing sessions may retain cached native adapter instructions; start new reviewer sessions with the updated adapter and verify source access rather than assuming reload.
- Full validation is required before release-ready claims. Source reviews can follow focused checks without waiting for full suites; reviewers do not run tests. Reviewer check-command maps are available routes, not instructions to execute broad suites after every slice.

### Test additions (D427)

- Inspect the affected existing tests before writing more. Reuse an existing meaningful case when it already covers the changed behavior; existing coverage satisfies the non-trivial-logic check requirement. Extend the owning case/spec only for a concrete uncovered failure or new contract.
- Before adding a test, state briefly in the active R card/checkpoint which real behavior could fail and why existing coverage misses it. This is a short selection reason, not a new card, report, approval or coverage audit.
- Do not require a new test/spec file for every edit, helper, validation field or session, or a red-first run merely to demonstrate test-first procedure. Copy/style/text changes and behavior-preserving moves use relevant static/type or manual checks; meaningful untested branches, parsers, calculations and jobs still need the smallest automated behavior check.
- Test observable results at the owning layer. Use representative normal/failure/boundary cases; avoid duplicate combinations, private implementation assertions and copies of backend validation in UI tests unless the UI has distinct submission/rendering behavior to protect. Reuse fixtures; create a new spec file only for a genuinely new independently owned flow.
- Keep necessary authentication, tenant isolation, billing/quota/concurrency, SSRF, migrations, destructive-data, input-trust and approval checks. No numeric test cap or coverage percentage target overrides these risks. A discovered relevant bug needs regression coverage if existing tests miss it.
- Stop adding cases once the changed contract and actual risk are covered. D429 permits the selected existing roadmap contract's needed checks, not speculative edge-case catalogues or unchanged-code coverage expansion. Do not delete/weaken assertions or skip failures to save time; redundant test cleanup remains outside scope unless it blocks delivery. Complete current R06 automated validation and select final current-source automated acceptance at full local coding closure.

## Implementation Checkpoints

- Record the user's implementation authorization and scope in `docs/IMPLEMENTATION_STATE.md`; preparing implementation documents alone does not authorize scaffolding. Git initialization and commits require their own explicit request.
- Continuation follows CONTINUE.md under D429: finish the current R05/R06 automated stage, then all already-planned local P/TOOL contracts in dependency order. No new cards/suffixes or unplanned features; core defects stay in their R card. Completing a card/basic milestone is not a stopping point. Human/external gates block their actual dependents/exposure, not unrelated code. Preserve D103's local configurable/provider/deployment-preparation work without requesting secrets or making real paid/customer/deployment calls.
- D435: In unattended scheduled sessions, resolve routine choices with the recommended/best-practice option, then an evidence-based default or first suitable option; record the choice and continue without optional input questions or waiting for confirmation. Record genuine human/external gates and continue other authorized local work without inventing facts/credentials/approval.
- At actual exhaustion of all dependency-ready planned local coding/automated checks under D429/D375/D423/D425, with no required operation active, follow CONTINUE.md's exhaustion-pause protocol after final documentation updates (D131); local adapter commands live in .agents/README.md. Report unresolved local work honestly; human/external/conditional exclusions need a named owner/reason. Context/tool limits and actionable work require an ordinary handoff, not exhaustion.
- Before substantial implementation edits, record the active task and bounded next step. After each meaningful code/check slice and before interruption or handoff, update the checkpoint with actual paths, commands/results, incomplete work, blockers and external effects.
- Keep current R/P/TOOL local implementation/automated acceptance and TODO requirements synchronized in the ledger's Local completion table. Classify the whole inventory once; report per-phase/overall verified-local ratios only with complete coverage, retaining unclassified/blocked local requirements in the denominator and listing human/external exclusions. Mixed release checkboxes stay open until all their required gates pass. Archived totals/statuses, R06 walkthrough and R07 readiness remain separate; required unrun/failed checks never count as passes.
- On resume, reconcile the checkpoint against the actual workspace, migrations, processes and external operation state. Preserve unrelated edits; recover unverified work before starting another slice. Never blindly repeat an operation whose outcome is unknown.
- Keep handoffs provider-neutral and secret-free. Session todo tools and chat history are not durable substitutes for these files. Under D322, keep `docs/IMPLEMENTATION_STATE.md` as a compact current handoff: replace superseded summaries, link dated same-directory archives for historical evidence, and load archives only as needed. Preserve unresolved operations, acceptance gates and the exact authorization rows; do not prepend accumulating historical narratives.

## Documentation Rules

- `docs/PROJECT_PLAN.md` remains comprehensive and canonical.
- Append accepted choices to `docs/DECISIONS.md`; D426 keeps earlier entries in its linked byte-preserved archive/index. Archive history rather than deleting evidence; ordinary fixes/check receipts need no new architecture decision.
- Update TODO as R/roadmap local contracts start and finish; keep new unplanned ideas outside continuation.
- Keep README concise and point to detailed documents.
- Avoid duplicating large sections of the plan into agent files, skills, or provider-specific configuration.
- Before changing planning documents or agent guidance, read and follow `.agents/rules/documentation.md`.

## Shared Agent Resources

- `.agents/rules/` contains task-specific requirements.
- `.agents/skills/` contains provider-neutral Agent Skills workflows loaded on demand.
- `.agents/references/` contains supporting context and document maps.
- `.agents/roles/` contains authoritative provider-neutral read-only reviewer instructions; `.agents/README.md` documents the roster, invocation, and portability. `.opencode/agents/`, `.codex/agents/`, and `.claude/agents/` register the same eight roles with host-specific settings (D114).
- For SEO planning or implementation (data sources, crawling/indexation, intent mapping, outcomes, local SEO, authority, content lifecycle, or AI visibility), read `.agents/rules/seo-data-and-integrations.md` and `.agents/references/seo-data-sources.md`.
- For public SaaS journeys/launch positioning, localization, acquisition measurement/readiness, authentication/admin, trials/billing, onboarding, UX/accessibility, notifications/reports/support, or closure/retention, read `.agents/rules/saas-product-experience.md` and `.agents/references/saas-product-experience.md`.
- `CLAUDE.md` is a thin compatibility adapter that imports this file.

Do not assume arbitrary rule or reference directories are loaded automatically. Read a file when this guide, a matching skill, or the task directs you to it.

## Agent Tooling

The provider-neutral documentation-maintenance skill and eight read-only reviewers are available (D045): `seo-reviewer`, `plan-reviewer`, `django-tenancy-reviewer`, `angular-ui-reviewer`, `jobs-integrations-reviewer`, `billing-entitlements-reviewer`, `security-reviewer`, and `deployment-reviewer`. Keep shared instructions in `.agents/roles/` and native registration/permissions in thin adapters. OpenCode and Codex routine Angular review uses GPT-5.6 Luna with `low` reasoning (D047); security uses GPT-6 Luna with `medium` reasoning and SEO uses GPT-6 Luna with `high` reasoning (D133); the other four specialists and `plan-reviewer` use GPT-6.1 Sol with `medium` reasoning (D430, superseding D424). Exploration retains its documented assignment; Claude adapters inherit the invoking Claude model. Under D324, proactively trigger the relevant existing read-only subagents whenever a required review gate or substantive specialist risk makes delegation necessary; do not wait for the user to request each review or ask permission to delegate within authorized scope. Give each subagent a bounded question, relevant paths and current evidence; the parent owns edits, checks and final decisions. Use subagents selectively, never the full roster automatically after every change; routine edits and straightforward checks stay with the parent. Under D077, `security-reviewer` is stricter: invoke it only for a task-ledger **Security review gate** or a direct user request, once after focused checks; unmarked cards, routine remediation, and continuation between cards must not trigger it. The parent routes complex Angular rendering, authentication, or accessibility to an appropriate deeper reviewer with the Angular criteria; see `.agents/README.md`. Shared roles name current source ownership/check routes, but missing or unrun evidence never authorizes scaffolding or establishes verification. Add implementation skills or write-capable coding specialists only for a demonstrated recurring workflow.

### Reviewer file access (D376)

Use native file-read/search tools first. When a host exposes local reading only through a command tool, reviewers may use simple bounded inspection commands: `pwd`, `rg --files` within supplied directories, `rg -n -- PATTERN FILE...`, `cat -- FILE...`, `sed -n 'START,ENDp' -- FILE`, `head -n N -- FILE`, `tail -n N -- FILE`, or `nl -ba -- FILE`. Read only project guidance, named non-secret source/tests and direct dependencies needed for the supplied review. Do not use shell chaining, pipelines, redirects, command substitution, executable search options, interpreters, application commands, tests, scans, writes, operational APIs, credentials or customer exports. This narrow reading exception does not authorize arbitrary shell execution, change native tool permissions or override a host denial.

The first actual review on a host/session must demonstrate source access by citing a supplied file, symbol and line range; the same read can start the substantive review without an extra agent. Every report identifies inspected paths and unread required dependencies. If reading is unavailable, return `review unavailable: source access blocked`, identify the conflicting tool/instruction, and never report a clean review. The parent may use the shared criteria directly and continue authorized local coding, but records that as parent review with independent review pending. Required independent review remains a release gate; historical unavailable reviews are not retroactively validated. Native read-only settings and prompt restrictions are different controls: check effective permissions when the host exposes them and do not claim enforced isolation from configuration alone.

## Universal Agent Resource Maintenance

1. Every creation or modification of agent instructions, agents, subagents, skills, or references must remain universal across coding agents. Read applicable root/module `AGENTS.md` files and existing agent resources first, including `.agents/README.md` where present; reuse or extend suitable resources.
2. Keep canonical rules in root/module `AGENTS.md`, shared skills and references under `.agents/`, and authoritative subagent behavior in `.agents/roles/<role>.md`. Resolve shared resource paths from the repository root; never duplicate project knowledge or role behavior in vendor adapters.
3. Write shared guidance in plain, provider-neutral Markdown with explicit paths and a direct file-reading workflow. Do not require vendor-specific commands, model identifiers, or automatic discovery. Keep skill frontmatter portable with `name` and `description`; each `SKILL.md` must work when read directly.
4. For every new core subagent, add matching `.opencode/agents/<role>.md`, `.codex/agents/<role>.toml`, and `.claude/agents/<role>.md` registrations in the same change. Each must explicitly load `AGENTS.md` and the same shared role file. Keep existing registrations aligned when modifying a role; use host-required naming conventions such as Codex underscores.
5. Keep tool-specific entry points as thin imports or pointers: `CLAUDE.md` imports its adjacent `AGENTS.md`, and other tools must reach the same canonical guidance. Model IDs, permissions, tool access, and budgets belong in native adapters; supported models may differ by host. Preserve existing access boundaries and keep specialists read-only by default.
6. Validate syntax, portable skill metadata, referenced files, imports, and matching core-role coverage. Check native discovery and effective settings where tools are available; accurately report unavailable or unrun checks.
7. Update affected task routing, references, compatibility documentation, and the `.agents/README.md` roster together when adding or moving resources. Document genuinely host-specific exceptions and their reason; they must not silently replace or omit a core-role adapter.
8. Leave primary-agent model and reasoning selection to the coding tool's current session or personal defaults. Do not pin a primary model or reasoning level in project configs or primary-agent adapters unless the user explicitly requests a project override. D431/D436 are the explicit host-only exception: one-minute timer-started Codex sessions use GPT-6.1 Sol/medium with Fast mode disabled for the main coder and all subagents in the installed launcher; other primary defaults remain unchanged. D434 supersedes D433: idle/waiting-input timer sessions permit fresh launches; actively coding project sessions/subagents still block. Explicit specialist subagent model and reasoning assignments remain allowed.

When agent tooling is introduced:

- Keep shared role instructions provider-neutral.
- Keep provider-specific files as thin adapters.
- Keep project-approved model assignments in host adapters and shared role instructions provider-neutral.
- Make specialist subagents read-only by default.
- Keep provider credentials and personal preferences outside the repository.
- Make free-model use explicit opt-in and do not send confidential data by default.
