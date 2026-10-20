# CI and security checks

The check-only workflow is [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml).
It runs on push, pull request and manual dispatch with read-only repository
permissions, no persisted checkout credentials and no deployment. Checkout,
Node, actionlint and Trivy use the D055 pins. Hosted Actions has not run: this
workspace has no Git repository/remote. Local command evidence is below and in
the [checkpoint](../../docs/IMPLEMENTATION_STATE.md).

**Current final roadmap validation remains unfinished.** The recorded R06 basic-stage candidate passed backend2594 and combined frontend1154/build/static/dependency/image checks. Those receipts validate that earlier candidate; subsequent D429 roadmap source changes require affected checks and final current-source validation at full local closure. The [current checkpoint](../../docs/IMPLEMENTATION_STATE.md) records exact source/evidence, incomplete work and operation owners. Historical failures and unknown outcomes stay recorded. D421 splits hosted checks without replacing the default local full runner; see `backend-checks.yml`. Hosted workflows, representative load, manual journeys and public-release gates remain unverified. Reuse passing evidence only where relevant source/configuration remains unchanged.

**Historical local acceptance: D086 image/security follow-up passed.** The current dependency lock and
running isolated-development Alpine image archives pass the unchanged HIGH/CRITICAL
gate; prepared images also pass backend/runtime and synthetic atomic logical-restore/
restart checks. The user's existing Bookworm legacy stack is deliberately unchanged;
it does not inherit these new-image results. Its real migration remains unperformed
and requires the [transition procedure](../postgres/README.md). D086 restored
the pinned Redis8.10.2 image and lean same-version proxy locally; actual
production broker authentication/deployment remains separate.

## Check paths

These are CI/final-validation command routes, not a coding-session checklist. Under AGENTS.md D423/D425, select exact affected check methods/files and relevant syntax checks during coding; defer full discovery, combined frontend checks, image scans and isolated-stack acceptance to their explicit final/state-changing gates and reuse unchanged evidence.

The [site-monitoring template](../../docs/SITE_MONITORING.md) has a standalone
offline gap report: `python3 deploy/checks/site_monitoring.py`. Its exit 0 means
valid shape only; it always reports RELEASE UNVERIFIED and grants no publication,
provider, hosted-cleanup or rollback acceptance. Its focused check is
`python3 -m unittest discover -s deploy/checks -p test_site_monitoring.py`.

| Check | Command / environment |
| --- | --- |
| Frontend | Node 24.21.0/npm 11.19.0; `npm ci --foreground-scripts`, `npm run check`, `npm audit --audit-level=high` in `frontend/` |
| Workflow syntax | Digest-pinned actionlint 1.7.12; explicit `ci.yml`, `backend-checks.yml`, `backend-release.yml` paths under `.github/workflows/` work without a Git repository |
| Check-tool tests | `python -m unittest discover -s deploy/checks -p 'test_*.py'` from root, with PyYAML 6.0.3 from `requirements.txt` in an isolated virtualenv |
| Private CI environment | `python deploy/checks/create_check_env.py backend/.env.ci`; default project `organicseoops-ci`, port18080; optional validated `--project-name`/`--proxy-port`; target must not exist |
| Startup data guard | `python deploy/checks/check_volume_transition.py --env-file PATH` before build/up; read-only, rejects unresolved legacy volumes |
| Backend | Build API/PostgreSQL/renderer/proxy; native pip validation in builder, system/migration/drift checks and `python manage.py test accounts config tenancy jobs providers integrations --noinput`; runtime contains no installer; hosted checks add `--testrunner config.sharded_test_runner.ShardedDiscoverRunner --shard 0` or `1` with all six labels |
| Live stack | `python deploy/checks/compose_smoke.py --env-file PATH` after all services start |
| Synthetic logical restore | `python deploy/checks/restore_smoke.py --env-file PATH` on a fresh disposable target; guards nonempty schemas, tests atomic failure/rollback and successful retry |
| Security | `bash deploy/checks/security.sh PATH` from root while that Compose stack is running |

`create_check_env.py` derives public configuration from `.env.example`, selects
`organicseoops-ci`, generates distinct secrets and creates a 0600 file without
overwriting existing credentials. It does not print secret values. Beat's
singleton name is project-scoped, so CI cannot collide with the development
scheduler. Check environments default to loopback18080; development's template
defaults to18000. Use another explicit `--proxy-port` for concurrent check stacks.
Do not use fresh startup to replace an existing Bookworm database: follow the
startup guard and transition guide first.

The workflow creates private `backend/.env.ci`; local task-specific checks use
ignored `backend/.env.check-TASK` with distinct project/port values. Do not reuse
the persistent dev `.env` or production `.env.prod` for disposable check stacks.
`--profile development` configures the Angular4200 origin; `--profile production`
creates an unconfigured DEBUG=0 template without credentials.

D421 builds/checks the images once and transfers only their Docker archive
through a pinned immutable current-run artifact ID. All consumers verify the
build-output archive SHA before loading and the four original image IDs after
loading; both isolated full-discovery groups must pass before release OIDC.
Malformed, incomplete, empty or failed discovery cannot yield a passing group.
No env files, data volumes or logs enter the image artifact.

The workflow creates a check-only virtualenv under `$RUNNER_TEMP`, not in the
application image. Backend tests use fresh test databases and drop them. The
cleanup step uses `if: always()` and `docker compose ... down`, preserving named
volumes rather than deleting unknown data. Local verification uses the same
commands with an explicit private env path. If rerunning locally with retained
volumes, reuse/reconcile the existing env instead of generating new DB credentials.

## Security gate behavior

Native npm audit includes development dependencies. Trivy 0.74.0 scans the backend
requirements lock and archives of the actual running API/PostgreSQL/Redis/proxy/renderer
image IDs. The host Docker CLI exports those archives; Trivy receives read-only
archives, not the Docker API socket. Archives are temporary and removed on exit.
The named `organicseoops-trivy-cache` volume retains public vulnerability data.

The gate exits nonzero on HIGH/CRITICAL findings (including unfixed findings),
scanner/database errors, or missing required images/services. All image scan
reports are attempted when an earlier vulnerability scan reports findings. Only
the two renderer-only stale-SBOM IDs in [trivy-rendererignore](trivy-rendererignore)
are excluded, after a running-renderer package-absence assertion. No blanket
exemptions or `continue-on-error` are configured. A failed gate
leaves P01-05 unfinished; D086 is not a vulnerability waiver. Lower severities are
outside this baseline failure threshold, not automatically accepted as harmless.

## Verified local results

### Redis and proxy restoration — 2026-09-26 (D086)

- Official Redis8.10.2 image index `sha256:3811787313eba226a2ef38658c6ccb91cd5e110edc89c37767de373120a0e5a0` replaced D054's local8.10.1 exception on isolated dev without removing its AOF volume; version, four broker keys, API health, Celery ping and29 focused PostgreSQL tests passed.
- Refreshed advisory data surfaced one HIGH libexpat finding in the previous full nginx1.30.5 image. The official same-version Alpine-slim index `sha256:32463212baf0e7d91aded2e9b843a4f2b9e017804b8c9d5bae7b51dcef64389c` omits that unused package; targeted dev proxy `nginx -t`, health, Admin redirect, static200 and missing404 passed.
- The **unchanged** `TMPDIR=/tmp/opencode bash deploy/checks/security.sh backend/.env` exited0 against actual running dev images/requirements with zero detected HIGH/CRITICAL findings on all five targets;13 deployment source checks and Compose config passed. Legacy images/data, hosted CI and production deployment were not changed or verified.

### Earlier image checks — 2026-09-24

- `bash deploy/checks/security.sh backend/.env` scanned the current D075
  `requirements.txt` and actual running development API
  `sha256:79c753bb4085a1b48af96883c924e2f93f48e4d1a438b32d26edf16210a1325c`,
  PostgreSQL `sha256:1b5ddce7c49a68209af1b84a712f107280e6565703ac298ceb59175f81abce5a`,
  Redis `sha256:d1e21a26915a35a6eb5d820018cd55adfcda02e02f7d629e1f42df397d5494ad`
  and proxy `sha256:9091d973203906ceea9568d86d7d8b67da9bddf3aed6960fa8dbd58bb8f3595a`
  archives. The gate exited zero with zero HIGH/CRITICAL findings on every target.
- Compose now passes the production-required `MFA_ENCRYPTION_KEYS` value to all
  backend consumers; the development wrapper clears ambient overrides so its
  selected private env remains authoritative. Nine check-tool tests, Bash syntax and
  a production Compose config parse with disposable required values passed; the
  unconfigured private production template still fails closed. The running dev
  containers did not require recreation for this source-only wiring correction.
- Angular's stable direct tooling pins resolve two beta-labelled transitive Babel
  dependencies: `@jridgewell/gen-mapping@0.4.0-beta.0` through
  `@angular/build`/`@babel/generator`, and `gensync@1.0.0-beta.2` through
  `@angular/build`/`@babel/core`. They are development tooling, not hidden direct or
  runtime selections.

## Earlier verified local results — 2026-09-21

### Logging and private artifacts (D057)

- Current API image `sha256:c39a820f7d90afab4621a6d4abaa1a37d79694f9b2ac99bea69b493307e70070`
  passed native dependency validation,20 backend tests,7 check-tool tests, full
  nine-service smoke and the unchanged vulnerability gate with0 findings.
- Live checks wrote through API and read through a worker on the same private
  mode0700 named volume, then deleted the probe. Request-ID JSON logs and API/proxy
  absence of path/query/cookie secret markers passed. Storage type/size/key,
  size-before-open, lazy-backend failure and S3-private-setting tests passed.
- A production frontend build under fake backend/S3 secret markers passed all6
  frontend checks; no marker appeared in generated public output.
- Security reviewer `ses_f3b37ebc0ffes15505s7lT8sMK` found no blocking issue
  after fixes. Remaining gates: no raw provider payload logging; live task marker
  when business tasks exist; real S3 bucket/IAM/Block Public Access validation;
  P02-03 tenant ownership before any artifact endpoint.
- Disposable `organicseoops-ci-p0106` containers, networks and all four volumes
  were removed. Its private env remains under `/tmp/opencode/organicseoops-p01-06/`
  only as local command evidence. The user's nine legacy containers stayed unchanged.

### Remediated definitions (D056)

- Pinned Python3.13.15/PostgreSQL18.6 Alpine3.24 bases retain all application pins.
  Native pip validates a pip-free target virtualenv during build; pip/ensurepip
  runtime code is physically removed. PostgreSQL runs as UID70 without gosu.
- Fresh canonical builds, all10 backend tests, runtime locked-version/tooling
  checks, full nine-service smoke and restart persistence passed on an isolated
  port18080 stack. Seven check-tool tests and actionlint passed; earlier unchanged
  frontend/exact-runtime/fail-fast evidence remains valid.
- A synthetic Bookworm logical dump/restore preserved Unicode users, memberships,
  permissions, migrations and sequence/email-uniqueness behavior on builtin
  C.UTF-8. Populated-target refusal made no changes. A fresh isolated target then
  deliberately failed during post-data index creation; `--single-transaction`
  rolled all application objects back, and the same archive restored cleanly.
- The unchanged Trivy gate exited0 for the backend lock and all four runtime
  image archives:0 HIGH/CRITICAL findings in detected coverage, without ignores.
  Final report: `/tmp/opencode/organicseoops-p01-05-remediation/security-final.log`.
- Tested API ID: `sha256:4efd51f2a66d558d53172374cddf683e774c2d61fb4226bfc383f959e5c05f60`;
  PostgreSQL: `sha256:6348f63bd1d275edd928f8b97de3403158cb1b35354d851ac988241b79aacb14`.
  Redis/nginx IDs remain those in the historical inventory below. Runtime base
  digests are pinned in Dockerfiles/Compose under D056.
- Startup guard rejected the actual legacy development volume using metadata
  only; all nine development IDs/images/start times stayed unchanged. Verification
  containers/networks were cleaned up. Only new atomic fixture volumes were
  removed; remediation volumes/env and all development resources were preserved.
  No real user database was read/exported.

### Earlier functional checks and failed Bookworm gate (historical)

- Exact frontend target: fresh lock install, three router tests, static production
  build and three output tests passed; npm audit reported zero vulnerabilities.
  A disposable generated home page was deliberately corrupted. The static check
  exited 1 and bash fail-fast skipped a subsequent sentinel command. Host source,
  dependencies and generated files were not changed by this rehearsal.
- actionlint and ShellCheck passed. Four check-tool tests passed, including env
  permissions, distinct generated secrets, no secret output and rejected overwrite.
- Fresh isolated CI PostgreSQL schema, ten Django tests and full nine-service
  live smoke passed. A further `build --pull --no-cache api` and repeated affected
  backend tests/smoke also passed, establishing a fresh Python 3.13.15 install
  against PostgreSQL 18.6. Redis remains the D054 local 8.10.1 exception.
- **Security gate failed with exit 1**, including after refreshed same-version
  Python/PostgreSQL pulls and a no-cache backend rebuild. The exact tags were
  already current; refreshing did not remediate the inherited findings.
- CI containers/networks were removed using the workflow cleanup command.
  Original development containers/volumes were preserved. The three CI data
  volumes, scanner cache and private env remain locally for recovery.

### Historical Bookworm scanner findings

Trivy ran at approximately 13:16 UTC on 2026-09-21. Counts are **package/advisory
rows**, not unique vulnerabilities or proven exploitable application paths.

| Target / detected coverage | HIGH | CRITICAL | Result |
| --- | ---: | ---: | --- |
| Backend requirements lock | 0 | 0 | Passed at this threshold |
| Backend Debian 12.15 packages | 55 | 5 | Failed |
| Backend pip-vendored Python inventory | 2 | 0 | Failed |
| PostgreSQL Debian 12.15 packages | 78 | 15 | Failed |
| PostgreSQL `gosu` embedded Go standard library | 21 | 1 | Failed |
| Redis image Alpine 3.23.6 OS packages | 0 | 0 | No findings in detected OS coverage |
| nginx image Alpine 3.24.2 OS packages | 0 | 0 | No findings in detected OS coverage |

Many Debian rows have `affected`, `fix_deferred` or `will_not_fix` status with no
listed fixed version. Examples include `libsqlite3-0`/CVE-2025-7458,
`perl-base`/CVE-2026-13221 and `zlib1g`/CVE-2023-45853. Package/source advisory
mapping, compiled components and actual use paths require official vendor triage;
these counts alone do not prove each finding is exploitable.

The two Python findings are GHSA-6v7p-g79w-8964 for pip-vendored msgpack 1.1.2
(reported fixed in 1.2.1), and CVE-2025-47273 for the vendored setuptools inventory
70.3.0 (reported fixed in 78.1.1). Runtime inspection found msgpack and
`pkg_resources` under `pip/_vendor/`, with standalone msgpack/setuptools absent.
Installing unrelated standalone versions would not replace those copies; assess
the advisory's affected components before choosing a remediation or exception.

The PostgreSQL `gosu` binary embeds Go 1.24.6; its 22 rows include
CVE-2025-68121. Updating an unrelated Go installation would not rebuild that
binary. Prefer a patched official image or a deliberately verified rebuild.

No language-package targets were reported for Redis/nginx, so their zero rows
do not cover every source-built C-server advisory or clear Redis's known
8.10.2 security-patch requirement. Trivy also warned that Alpine 3.24 was absent
from its EOL list. The requirements-only mount skipped license detection; this
was a vulnerability-only scan, not a license assessment.

### Historical evidence and remediation rationale

The final full local log is
`/tmp/opencode/organicseoops-p01-05/security-archive.log`. It can disappear with
temporary-directory cleanup; regenerate it with the commands above rather than
treating that path as an application dependency. It records these image IDs:

- API: `sha256:39ac892e1d37266b018423b8e9c368bc7a74961218bd837b6fe8522378974835`
- PostgreSQL: `sha256:8d76d8de17e883d3995f76252e260bc6b7761e9c23edbf3356b0676d37c49ddb`
- Redis: `sha256:d1e21a26915a35a6eb5d820018cd55adfcda02e02f7d629e1f42df397d5494ad`
- nginx: `sha256:9091d973203906ceea9568d86d7d8b67da9bddf3aed6960fa8dbd58bb8f3595a`

The refreshed Python base digest was
`sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26`;
PostgreSQL's repository digest was
`sha256:3725f4e2499eef5134592b3b4ab79a543ed7f8e533b05b5b637af926630f6650`.
Those runtime-base references were mutable tags. D056's prepared definitions now
pin base digests; locally built image IDs are captured by the runtime scanner.

These findings were remediated in the prepared images through D056's base change
and removal of genuinely unnecessary runtime tooling, retaining native build-time
dependency checks. The legacy running stack is not migrated by that source
change. No advisory exception was used to make the new gate pass. Scanner coverage
limits above still apply, as does D054's Redis requirement.
