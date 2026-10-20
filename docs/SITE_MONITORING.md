# Site monitoring preparation (P13-05a)

[SITE_MONITORING.json](SITE_MONITORING.json) is an offline, secret-free coverage
record for the product's own site. Its origin, responsible owner reference,
review cadence in days and baseline reference are unconfigured. Empty evidence
means unknown. No domain, person, monitoring service, data source or schedule is
selected or activated by this template.

Run `python3 deploy/checks/site_monitoring.py` from the repository root, optionally
passing another record path. Exit 0 means the bounded record has valid shape;
exit 2 means invalid input. The report always says **RELEASE UNVERIFIED**, even
when every required reference is supplied. It never fetches a URL, checks a
provider, reads credentials, configures collection or verifies a human's claim.

Only record opaque `P13MON-...` evidence references, a real UTC `checked_at` date,
an environment (`local`, `staging`, `production`) and a kind (`local_fixture`,
`human_review`, `hosted_observation`). Fixtures must use `local`; hosted evidence
must use staging or production. References within each check must be distinct.
Use a short non-secret owner/role reference, not an email address or credential.
An eventual origin is a lowercase HTTPS hostname without credentials, port,
path, query or fragment. Cadence is 1–365 days. The baseline is null or a dated
evidence reference with the same four fields; measured values, units and source
coverage belong in that referenced evidence. Unknown baseline cannot be recorded
as zero. An actual measured zero needs its own source evidence. Do not place raw
URLs, tokens, customer identifiers, exports or provider responses in this file.

The input is UTF-8 JSON, at most 32 KiB, with a fixed set of fields and checks,
no duplicate JSON keys, and at most four references per check. Supplying references
only removes *reference-coverage* gaps. Local fixtures and staging observations
cannot fill production hosted gaps; human review cannot replace hosted behavior.
Accessibility, approved claims and consent also need separate production human
review references. All original release gates still require independent review
of actual evidence and its coverage, environment, revision and date.

| Check | Evidence must cover |
| --- | --- |
| `public_indexability` | Actual public HTML/metadata, robots/noindex, canonical/locale links, navigation/schema, redirects/404/assets and restricted, non-indexable previews; selected engines/representative URL coverage |
| `sitemap_submission` / `observed_indexing` | Domain ownership and actual sitemap submission separately from dated engine-reported indexing; submission never proves indexing |
| `links` / `availability` | Representative broken-link/status coverage and availability windows, owner and follow-up |
| `search` / `referrals` | Source, periods, scope and attribution gaps kept separate; no invented traffic or funnel linkage |
| `lab_performance` / `field_performance` | Method/date/target for lab results separately from real-user field coverage; absent field data remains unknown |
| `mobile` / `accessibility` | Actual narrow-screen/mobile behavior and human keyboard/assistive-technology review of the selected journeys |
| `approved_claims` | Exact approved public revision, bilingual copy/offer/proof and supported advertised provider/surface claims |
| `consent` | Actual public optional choice, withdrawal/expiry/privacy behavior and reviewed disclosure |
| `app_handoff` / `email_handoff` / `payment_handoff` | Actual public/app routing, delivery/recovery and payment environment/state handoffs separately; no inferred customer conversion |
| `cleanup_scheduler` | Existing hourly purge/Beat singleton and scheduler-delay coverage, including collection disabled |
| `cleanup_queue` | Default worker/queue, bounded continuation, backlog/locked rows and dispatch/worker failures |
| `cleanup_deadline` | Existing 75-minute-from-issuance healthy-operation target, `expired_pending` / `deadline_missed`, and categorical overdue/dispatch-failure alerts; fixture throughput never proves a hosted deadline |
| `content_rollback` | Actual last-approved revision/asset restoration and CDN invalidation/status reconciliation, separate from backend/data rollback |

Reuse [public approval/editing/rollback and cleanup contracts](PUBLIC_CONTENT_WORKFLOW.md),
the [public page map](PUBLIC_PAGE_MAP.md),
[provider readiness](PROVIDER_READINESS.md) and
[deployment checks](../deploy/checks/README.md). The fixed related-record paths
point to the original authorities; this helper does not amend or approve them.
Collection remains off under the existing publication/policy gates. The cleanup
target is conditional on healthy operation; stalled queues/schedulers are gaps.
Existing backups can retain erased records for up to 35 days after active deletion.

P13-05 and the original publication, bilingual, webmaster, provider, CDN,
accessibility, consent/funnel, cleanup and rollback release checks remain
unfinished. If the product site is managed inside the app later, use its own
isolated project. Local template/checker acceptance is preparation only.
