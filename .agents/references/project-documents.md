# Project Document Map

Use this map to load only the context needed for the task.

| File | Authority | Read when |
| --- | --- | --- |
| `AGENTS.md` | Always-applicable project instructions | Every agent session |
| `docs/PROJECT_PLAN.md` | Canonical product and technical direction | Planning or implementation affects behavior, architecture, scope, or delivery |
| `docs/DECISIONS.md` | Current choice and index to byte-preserved historical choices | Making, replacing, or checking a decision |
| `TODO.md` | Basic-release checklist and D429 full planned local-completion scope | Selecting/closing basic or existing roadmap local work; separating manual/external gates |
| `docs/IMPLEMENTATION_GUIDE.md` | Execution contracts, context routing, dependencies, and start/resume protocol | Preparing, starting, or resuming implementation with any model |
| `docs/IMPLEMENTATION_TASKS.md` | Basic R outcomes, current Local completion table and preserved roadmap ID/contract index | Selecting current R/P/TOOL local work, mapping TODO requirements/exclusions and source-bound evidence; old labels are historical |
| `docs/IMPLEMENTATION_STATE.md` | Compact current checkpoint, active verification, unresolved operations, blockers, next step and history index | Every implementation start/resume, meaningful slice completion, and handoff; replace superseded summaries |
| `docs/IMPLEMENTATION_STATE_ARCHIVE_*.md` and dated implementation history | Preserved historical handoffs/check evidence; does not override current state | Only when the active task needs specific historical evidence |
| `README.md` | Short human entry point | Project status or canonical links change |
| `.agents/rules/seo-data-and-integrations.md` | Task-specific SEO requirements | Data/connectors, crawl/indexation, intent mapping, outcomes, local SEO, authority, content lifecycle, or AI visibility change |
| `.agents/references/seo-data-sources.md` | Map to canonical SEO capability sections | Locating scope, source/measurement limitations, review boundaries, extensibility, or delivery priorities |
| `.agents/rules/saas-product-experience.md` | Task-specific SaaS lifecycle and UX requirements | Public pages/positioning, localization, acquisition/readiness, accounts/admin, trials/billing, onboarding, accessibility, reports/support, or closure change |
| `.agents/references/saas-product-experience.md` | Canonical SaaS section map and supporting standards | Locating lifecycle/UX requirements, launch decisions, or official auth/payment/accessibility guidance |
| `.agents/README.md` | Shared resource and reviewer usage guide | Invoking, validating, or adapting reviewer subagents |
| `.agents/roles/` | Provider-neutral reviewer instructions | Delegating planning or specialist review; use the roster in `.agents/README.md` |
| `.opencode/agents/` | OpenCode registration and tool permissions | Changing native subagent discovery or access |
| `.codex/agents/`, `.claude/agents/` | Native adapters loading the same shared reviewer roles | Changing Codex or Claude discovery, model settings, or read-only boundaries |
| `opencode.json` | Project OpenCode host overrides | Inspecting current host-specific agent configuration; not application behavior |

Precedence for project direction:

1. The user's latest explicit decision.
2. `docs/PROJECT_PLAN.md` as updated to reflect that decision.
3. `docs/DECISIONS.md` for decision history and rationale.
4. `TODO.md` for execution status.

The ledger's current Local completion table tracks requirement/card classification and verified local implementation/automated acceptance; R rows retain basic-release/manual/public gates. The checkpoint records one active substep/operation. D429 selects the full existing local scope after current R05/R06 automated closure, while old labels/receipts remain source-bound historical evidence. Reconcile the selected card rather than inferring completion from a stale checkpoint.

If these disagree, follow the latest explicit decision and synchronize the affected documents.

D429: Start with the compact checkpoint/current R/P/TOOL card and plan §0. Finish the current basic automated stage first, then use the existing roadmap contracts and complete TODO as the inventory. Classify documents once; subsequent sessions read only selected contracts/source/evidence. [Archive index](../../docs/IMPLEMENTATION_ARCHIVES.md) preserves snapshots; percentages/statuses there are never edited to claim current100% completion.
