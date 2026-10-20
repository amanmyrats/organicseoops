---
name: maintain-project-docs
description: Maintain OrganicSEOOps planning documents and synchronize accepted decisions across the plan, decision log, backlog, README, and agent guidance. Use when changing product scope, architecture, milestones, or repository instructions; do not use for application implementation.
---

# Maintain Project Documents

1. Read `AGENTS.md`, `.agents/references/project-documents.md`, and `.agents/rules/documentation.md`.
2. Read only the canonical documents relevant to the requested change.
   For SEO scope (including AI visibility/referrals), also read `.agents/rules/seo-data-and-integrations.md` and `.agents/references/seo-data-sources.md`. Keep source limits, measurement assumptions, review boundaries, and delivery priorities aligned across the plan and backlog.
   For public/customer journeys, auth/admin, trials/billing, UX/accessibility, reports/support, or closure, read `.agents/rules/saas-product-experience.md` and `.agents/references/saas-product-experience.md`. Separate accepted lifecycle requirements from unresolved trial/payment/retention terms; update public-launch gates and historical replacements together.
   For launch specifications, route audience/page mapping, proof/content operations, localization, funnel measurement, and provider/first-party SEO readiness through those same references. Record the requirement without inventing the audience, URLs/keywords, languages, owners, vendors, or measured results; keep decision tasks and release evidence aligned.
3. Apply the smallest complete documentation change that records the current direction and its history.
4. Check that status, links, decision numbering, and affected backlog items agree.
   For execution/handoff changes, also synchronize `docs/IMPLEMENTATION_GUIDE.md`, affected `docs/IMPLEMENTATION_TASKS.md` cards/dependencies, and `docs/IMPLEMENTATION_STATE.md`. Preserve explicit authorization, partial/unverified work, and actual check evidence; documentation preparation does not start implementation.
   For reviewer tooling changes, also check `.agents/README.md`, shared roles, and host adapters; keep portable instructions separate from host-specific permissions and validate discovery using the documented commands.
5. Report any unresolved conflict; do not invent a product decision to hide it.
