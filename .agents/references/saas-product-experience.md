# SaaS Journey And UX Reference Map

Use [the canonical plan](../../docs/PROJECT_PLAN.md) for product decisions and [the backlog](../../TODO.md) for implementation status. This file routes context and supporting standards; it does not select unresolved business terms.

| Topic | Canonical sections |
| --- | --- |
| Public homepage, features, pricing, demo, help, and trust pages | 2.1: Public Website And Customer Journey; 23.6: Navigation And Public/App Boundaries |
| Launch audience, value proposition, concrete URLs, keyword intent, and page CTAs | 2.2: Launch Audience And Public Page Map |
| Sample reports/case studies, editing ownership, previews, approval, rebuilds, and rollback | 2.3: Proof Of Value And Marketing Content Operations |
| Product markets/languages, translated pages, locale URLs, and support coverage | 2.4: Launch Markets And Localization |
| Roles, billing ownership, project access, and approval permissions | 6.2–6.3: Roles and Authorization Contract |
| Verification, recovery, invitations, sessions, MFA, ownership, export, and closure | 7: Authentication And Account Lifecycle, including 7.3–7.4; 28: Security Requirements |
| Company administration and platform support/superadmin | 8.1: Customer Organization Administration; 8.2: Platform Support And Operational Administration |
| Automatic trial, subscription lifecycle, signed events, and quota/expiry enforcement | 9.1–9.3: Automatic Free Trial, Paid Subscription Lifecycle, Billing Reliability And Usage Enforcement |
| Short onboarding, demos, first results, and activation | 10.1: Progressive Onboarding And First Value |
| Understandable UI, failure states, navigation, and accessibility | 23: Frontend Architecture And UI, especially 23.5–23.6 |
| Public custom HTML/CSS, prerendered routes, CSR, static hosting, redirects, and cache refresh | 23.7: Static Rendering And Public Page Contract; 25.1–25.2: GitHub Actions Requirements and Static Public Pages And CSR Hosting Requirements; decision D039 |
| Notifications, weekly reports/shares, help/support, and delivery permissions | 29.1: Customer Notifications, Reports, And Support |
| Acquisition funnel definitions, cohorts, authoritative conversion, attribution, and consent | 29.2: Acquisition-To-Revenue Measurement |
| Product-domain webmaster setup, live SEO/funnel checks, and provider access/cost readiness | 34.2: First-Party Website SEO And Provider Readiness |
| Commercial milestone, public-launch checks, and undecided terms | 33: Delivery Roadmap (Phase 2A); 34.1: Public SaaS Launch Acceptance; 35: Quality And Acceptance Principles; 37: Open Decisions For Implementation Time |

[D036](../../docs/DECISIONS.md) moves trials/billing into public-launch readiness. TODO Phase 3A implements that milestone alongside the account, job, and data phases; later scale work refines rather than introduces subscriptions. D095-D098 select the planned offer and lifecycle policy; Paddle approval/sandbox, global legal/privacy and Turkish accounting review, cost/source validation and deletion/restore evidence remain open.

[D040](../../docs/DECISIONS.md) requires concrete launch specifications and readiness evidence in that same milestone and TODO Phase 13 deployment checks. D087–D098 record accepted audience, intended hosts, locale and offer direction; approved live URLs/content/proof, analytics/consent tooling and real provider budgets still require their own evidence. D103 lets configurable UI and deployment-preparation code precede actual domain/provider/AWS access.

## Supporting Standards And Provider Documentation

Reviewed for this planning update on 2026-09-21; recheck current official requirements during implementation. A reference does not select a vendor, guarantee compliance, or authorize preview dependencies.

- [OWASP forgot-password guidance](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html): non-enumeration, reset-token expiry/single use, trusted reset URLs, and post-reset session handling. Use framework-supported primitives.
- [W3C WCAG 2.2 quick reference](https://www.w3.org/WAI/WCAG22/quickref/): use Level A/AA criteria for keyboard/focus, forms/authentication, contrast, reflow, status announcements, and other applicable accessibility checks.
- [Angular rendering guidance](https://angular.dev/guide/ssr#generate-a-fully-static-application): documents fully static output and build-time prerendering without a production Node server. The same guide covers route-level client/prerender modes and notes that prerender redirects use metadata rather than HTTP status redirects; verify static-host/CDN behavior separately. Recheck selected-version support at scaffold time.
- [Stripe Checkout free trials](https://docs.stripe.com/payments/checkout/free-trials): reference for a possible hosted trial/checkout integration, not a selected billing provider or card policy.
- [Stripe webhook guidance](https://docs.stripe.com/webhooks): raw-body signature verification, replay protection, duplicate/out-of-order delivery, and asynchronous processing. Confirm equivalent guarantees for whichever provider is selected.

For AI-answer visibility, crawler roles, and referral measurement limits, use [the SEO/AI source map](seo-data-sources.md).
