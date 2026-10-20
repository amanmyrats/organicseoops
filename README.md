# OrganicSEOOps

Repository: [amanmyrats/organicseoops](https://github.com/amanmyrats/organicseoops).

Current work follows [D437](docs/DECISIONS.md#d437-implementation-only-until-the-user-requests-testing): unfinished implementation only; all testing waits for an explicit user request. Completed archived implementation is preserved.

A multi-project SEO application for turning source data and site audits into evidenced actions and sourced content briefs.

## Current Status

The current target is **all already-planned local coding and automated acceptance** (D429), with human/external tasks reported separately. Finish the current basic R05 repair/R06 automated stage first, then continue existing roadmap cards in dependency order. Current-source acceptance and public/provider/deployment readiness remain unfinished. The basic flow is:

Account → organization/project → Search Console import or configured sync → bounded audit → useful findings → approved action → sourced research → readable brief.

See [scope/release gates](TODO.md), [current local-completion tracking](docs/IMPLEMENTATION_TASKS.md#local-completion), [basic R contracts](docs/IMPLEMENTATION_TASKS.md#first-working-release) and [current handoff](docs/IMPLEMENTATION_STATE.md). CONTINUE.md directs basic-then-full local completion; no new features/cards beyond the agreed plan. A 100% local report needs classified requirements and verified evidence; it does not establish public readiness.

## Local Development

Use `./backend-dev.sh setup` for first-time setup; subsequent backend sessions follow the reusable loop in [the service guide](deploy/README.md#isolated-local-development). Inspect status once only when backend runtime is needed and reuse healthy services/volumes. Start the frontend with `npm --prefix frontend start` after dependencies are installed; full checks belong to the selected R06 or final full-local acceptance phase, not startup.

Private configuration lives in `backend/.env` / `backend/.env.prod`; root `.env.example` is secret-free. Public Angular values live in `frontend/src/environments/`. See [backend](backend/README.md), [frontend](frontend/README.md), [service](deploy/README.md) and [database transition](deploy/postgres/README.md) guides before changing runtime state.

## Documents

- [Canonical specification and frozen scope](docs/PROJECT_PLAN.md#0-first-working-release--frozen-scope-d426)
- [Current decision and historical index](docs/DECISIONS.md#d429-complete-all-already-planned-local-work-with-separate-human-and-external-gates)
- [Short implementation guide](docs/IMPLEMENTATION_GUIDE.md)
- [Agent guidance](AGENTS.md) and [shared reviewer resources](.agents/README.md)
- [Historical evidence archives](docs/IMPLEMENTATION_ARCHIVES.md)

History is preserved for contracts, failures and audit evidence; it is not the daily coding queue. Example customer domains are never seeded or crawled by an agent. Users create projects and select their actual sources/models through scoped UI. Local fixtures do not activate real providers, public offers, payments or deployment.

## Canonical Documents

See the current scope/status and canonical document links above. D429 selects the current basic automated stage, then all existing planned local work; human/public evidence remains separate.

## Example Customer Projects

See the current scope/status and canonical document links above. D429 selects the current basic automated stage, then all existing planned local work; human/public evidence remains separate.

## Agreed Direction

See the current scope/status and canonical document links above. D429 selects the current basic automated stage, then all existing planned local work; human/public evidence remains separate.

## Next Milestone

See the current scope/status and canonical document links above. D429 selects the current basic automated stage, then all existing planned local work; human/public evidence remains separate.
