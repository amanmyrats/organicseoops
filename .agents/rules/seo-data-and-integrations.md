# SEO Data And Integration Rule

Apply when planning or implementing SEO data, crawling/indexation, intent mapping, action/outcome tracking, local SEO, authority building, content lifecycle, AI visibility/referrals, or related dashboards. Read [the source map](../references/seo-data-sources.md) and its relevant canonical sections first.

- Crawl only configured project domains/aliases and explicitly selected competitors. Recording an external link does not authorize recursive whole-web crawling.
- Never infer complete inbound backlinks, keyword volumes, difficulty, rankings, or competitor traffic from page content alone. Use the appropriate first-party or external source and expose its limits.
- Preserve provenance, observation dates, scope, coverage gaps, and provider-specific score definitions. Distinguish measurements, observations, estimates, AI interpretation, and unavailable data; missing is not zero.
- Keep webmaster integrations extensible beyond Google to Bing, Yandex, and other supported engines. Reuse project-scoped connections, jobs, and sync records with small provider-specific handlers.
- Retain provider/property identity and metric dimensions through storage, uniqueness keys, jobs, detectors, and UI. Normalize only comparable data; do not silently combine different engine semantics.
- Check current official provider capability/access contracts during implementation and exercise them with local fixtures; actual account access is release evidence under D103, not a coding prerequisite. Gate unsupported operations and preserve provider-specific authentication, quotas, history, and freshness behavior.
- Isolate sync checkpoints, retries, backfills, and failures by connection/property and project; scale existing workers based on measured load.
- Map intent/query clusters to existing or proposed pages and evidence-backed actions before defaulting to new content; keep classifications reviewable and project/market/language scoped.
- Track ownership, approval, actual implementation dates, verification evidence, and outcomes separately. Manual change logging must work before publishing or repository integrations.
- Preserve analytics-quality and attribution context, comparable baseline/follow-up windows, branded-query coverage, and inconclusive outcomes. Before/after changes alone do not establish causation.
- Budget raw/rendered comparisons and parameter crawling; preserve network protections and meaningful URL variants. Distinguish schema validity from rich-result eligibility or appearance.
- Keep discovered, crawlable, indexable, and engine-reported indexed states separate with timestamps and unknowns. Bot visits and successful fetches are not indexing proof; optional logs require authorization, redaction, and coverage labels.
- Ground local SEO in real business/service details and profile eligibility. Keep location-specific visibility scoped; do not generate doorway pages, fabricated locations, or reviews.
- Use authority research for relevant partnerships, mentions, link recovery, and digital PR with manually reviewed/executed outreach, not automated link creation or bulk messaging.
- Require original business expertise and current facts in content review. Do not recommend deletion solely for low traffic; preserve approval and destination checks for merges, redirects, and retirement.
- Treat AI visibility as budgeted samples with versioned prompt sets, evidence, exact collection surfaces/models/modes, and explicit eligible denominators. Keep neutral and branded prompts separate; failures/unsupported samples are not negative observations.
- Do not equate API answers with consumer chat experiences, sampled mention/citation rates with global visibility, or mentions with referral visits. Keep identifiable referrals and their analytics/attribution gaps separate.
- Distinguish search/retrieval crawlers, training crawlers, and user-triggered fetch agents using current official provider guidance. Access or bot visits do not prove inclusion, citations, or training membership; never guarantee AI placement.
- For public claims, trial costs/quotas, accessible reports, or customer-facing integration states, also follow `.agents/rules/saas-product-experience.md`.
- For the product's own public SEO, use the accepted audience/page map and actual language coverage; keep locale equivalents, canonicals, prerender inventory, and sitemaps consistent. Do not fabricate keyword targets or evidence-backed case studies from a page category alone.
- Treat first-party website launch monitoring and provider-readiness evidence as actual checks, not assumed consequences of a deployment or API key. Keep product-domain measurements project-scoped and distinguish search submission, observed indexing, and unknown coverage.

The canonical plan controls scope and phasing. This rule does not start implementation or require a generic connector framework.
