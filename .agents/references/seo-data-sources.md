# SEO Data Source Map

This is a navigation aid, not a second specification. Read the relevant sections of [the canonical plan](../../docs/PROJECT_PLAN.md).

| Question | Canonical sections |
| --- | --- |
| What does targeted crawling cover compared with Semrush/Ahrefs-style datasets? | 11.6: Targeted Crawling And External SEO Data; 12: Site Crawling |
| Where do keyword, backlink, rank, competitor traffic, and historical data come from? | 11.4–11.6: Search And Competitor Sources, Truth And Confidence Labels, Targeted Crawling And External SEO Data; 17: Competitor Intelligence |
| How do Google, Bing, Yandex, and later webmaster connectors coexist and scale? | 11.1: First-Party Sources; 11.7: Extensible Webmaster Integrations; 19: Job Architecture |
| How are multi-engine records isolated and interpreted? | 6: Tenancy And Ownership; 11.7: Extensible Webmaster Integrations; 21.2–21.3: Integrations And Credentials, Website And Analytics |
| How are conversion quality, attribution, and branded queries handled? | 11.8: Analytics Quality And Measurement Context |
| How are rendering, canonical targets, parameters, schema, indexation, and bot logs interpreted? | 12.1: Deeper Technical Diagnostics; 12.2: Indexation And Bot Visibility |
| How do keywords map to pages and actions, and how are changes evaluated? | 13.1: Search Intent And Keyword-To-Page Mapping; 13.2: Action, Change, And Outcome Tracking |
| What belongs in local SEO and ethical authority building? | 13.3: Local SEO; 17.1: Authority Building And Link Recovery |
| How should existing content be reviewed, refreshed, consolidated, or retired? | 18.5: Content Quality And Lifecycle Management |
| What does AI-answer visibility measure, and what are the sample/API/referral limits? | 17.2.1: Sampled Answer Monitoring; 17.2.2: Identifiable AI Referral Traffic |
| How are AI crawler access and discoverability recommendations interpreted? | 17.2.3: Discoverability And Improvement Guidance; 12: Site Crawling |
| How is OrganicSEOOps' own public site positioned, mapped to search intent, evidenced, and localized? | 2.2: Launch Audience And Public Page Map; 2.3: Proof Of Value And Marketing Content Operations; 2.4: Launch Markets And Localization |
| How are product-site acquisition, SEO launch monitoring, and advertised integrations validated? | 29.2: Acquisition-To-Revenue Measurement; 34.2: First-Party Website SEO And Provider Readiness; decision D040 |
| When should these capabilities ship and how should they be checked? | 33: Delivery Roadmap; 34: First Useful Release; 35: Quality And Acceptance Principles; TODO phases 6–8, 10, 11, and 11A; public-launch dependencies in Phase 3A |

Accepted choices are recorded in [D032–D034](../../docs/DECISIONS.md), with D103 separating local implementation from real-provider release checks. Progress and remaining work live in [the backlog](../../TODO.md). Prioritize intent/page mapping, action/outcome tracking, and deeper crawl/indexation diagnostics after data foundations, with analytics-quality context and early local SEO assessment. Check official provider contracts when implementation begins; actual account access, licensing, costs and historical coverage require evidence before advertising or production use.

[D037](../../docs/DECISIONS.md) adds bounded AI visibility (plan Phase 7A; TODO Phase 11A). Public feature claims and cost/retention controls must also follow [the SaaS journey map](saas-product-experience.md) and D036's public-launch requirements.

D040's launch page/proof/localization and first-party SEO work belongs to TODO Phase 3A and Phase 13; it is separate from importing analytics for customer websites and from later customer CMS publishing.

## AI Visibility Provider Reference

- [OpenAI crawler documentation](https://developers.openai.com/api/docs/bots), reviewed 2026-09-21: OAI-SearchBot concerns search, GPTBot concerns potential training use, and ChatGPT-User concerns user-triggered actions. The controls are not interchangeable. Recheck current provider guidance, user agents, and supported verification mechanisms at implementation time; do not hard-code published IP lists from this planning checkpoint.
- The project's sampled-observation methodology and API-versus-consumer distinction are product measurement requirements in Section 17.2, not a claim that any provider exposes universal chat-visibility analytics. Verify each chosen provider's collection/retention capabilities before integration.
