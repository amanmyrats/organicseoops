# Documentation Rule

Apply this rule when changing planning documents, decisions, milestones, repository guidance, or agent resources.

- Read `.agents/references/project-documents.md` before editing.
- Keep `docs/PROJECT_PLAN.md` as the comprehensive current source of truth.
- Append accepted decisions to `docs/DECISIONS.md`; preserve superseded decisions and record their replacement.
- Update `TODO.md` when a phase, milestone, or tooling status changes.
- Keep affected implementation task cards/dependencies and guide gates aligned with canonical changes. During implementation, persist active progress/check evidence in `docs/IMPLEMENTATION_STATE.md`; task and TODO completion require verified acceptance, not a session summary alone.
- Update `README.md` only when its short status or document links change.
- Update `AGENTS.md` when always-applicable working guidance changes.
- Resolve contradictions in the same change instead of leaving documents out of sync.
- Link to canonical material instead of copying large sections into rules, skills, or references.
- Do not create application or runtime code while the project remains at the documentation checkpoint unless the user explicitly starts implementation.

## D429 Local Completion And Preserved Archives

D429 supersedes D426's permanent roadmap deferral: finish current R05/R06 automated work first, then all already-planned local P/TOOL contracts. Keep the checkpoint compact with one active card; the ledger's Local completion table tracks the classified full inventory, current local implementation/automated evidence and human/external exclusions. R06 walkthrough/R07 public readiness and mixed release checkboxes remain separate. Do not mark archived unresolved work done or rewrite historical percentages. Read selected contracts and relevant sections, preserve existing IDs/anchors/dependencies and add no new features/suffixes. Local ratios require complete inventory coverage and genuine evidence; unclassified/blocked work stays unfinished and exclusions need owner/reason. Ordinary repair receipts belong in checkpoint/history, not repeated plan/decision narratives.
