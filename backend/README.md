# Backend development

Django 6.1.1, DRF 3.18.1 and psycopg 3.3.6; direct dependencies are in
`requirements.in` and the resolved Linux dependency pins are in `requirements.txt`.
`accounts.User` is configured before the initial migration. P02-01/P02-02 use pinned
django-allauth headless browser APIs for registration, mandatory verification,
cookie-session login/logout, one-hour single-use recovery, recent reauthentication,
verified email changes and tracked sessions. Thin project endpoints provide generic
verification status/resend, explicit password change and authoritative logout-all.
P02-03–P02-05 add organization/project membership, restricted project access,
normalized domain aliases, explicit role/action checks, digest-only invitations,
accepted ownership transfer, last-owner and suspension guards, team/audit APIs
and project-bound artifact helpers. P03-01 provides inspect-only Django Admin
for existing tenancy records; audited staff suspension uses scoped APIs. P03-02
adds staff-only TOTP/recovery codes and current-session MFA assurance for production
Admin/platform operations. Production email delivery and commercial access remain later cards.
Celery transport/queues and Gunicorn/WhiteNoise serving are configured under D052.
Structured request logging and private artifact foundations are configured under D057.
P04-01–P04-05 add durable project-scoped job/step/evidence/schedule records,
commit-safe Redis/default-queue delivery, DEBUG-only scoped diagnostic endpoints
and a local Angular progress/schedule view. Internal usage reservations bound
units and active slots even for zero-cost diagnostics; singleton Beat enables
only explicitly requested cost-free local schedules and bounded recovery.
These are not commercial allowances. No production provider job or usage billing
is enabled. See D069–D073 and P3A-08 for entitlement gates.
P06-01 adds project-owned resumable onboarding configuration and a private scoped
API; source choices remain intent only and the synthetic preview creates no job,
artifact or usage record. See D074. Real connectors/imports remain P06-02 onward.
P07-01 adds the shared SSRF-safe HTTP/TLS fetch path plus fail-closed robots and
bounded sitemap discovery under D076. P07-02/D078 adds project/job-owned immutable
HTTP crawl observations, private raw HTML, conditional reuse, bounded extraction,
host pacing and resumable crawl-queue execution. P07-03/D079 adds capped selective
raw/rendered comparison through a separate networkless Playwright service with
immutable partial/unknown evidence. These expose no customer endpoint, and no real
remote customer crawl or render has run; deeper diagnostics remain P07-04 onward.
P12-01/D082 adds private owner/admin exact-origin HTTP-file challenge APIs,
digest-only verification evidence and zero-unit audit-queue verification through
the bounded safe fetcher. Future passive-security work must use the reusable current
verified-scope authorization check; no passive observations or real remote verification
are enabled by this foundation.
Service definitions and verified local Docker procedures are in the
[local service guide](../deploy/README.md).

For everyday source-mounted development, run `./backend-dev.sh setup` once from
the project root, then `./backend-dev.sh` on later starts. API Python edits reload
without rebuilding; use `restart-workers` for Celery/Beat code, `migrate` for
reviewed migrations and `rebuild` only after dependency or Dockerfile changes.
Use `./backend-dev.sh makemigrations APP` when generating an application migration;
only that app receives a temporary writable mount.
During edits, `./backend-dev.sh quicktest TEST_LABEL...` runs focused tests inside
the already-running target-runtime API container and retains the Django test
database between runs. It requires a label, never starts services and fails if
another wrapper-managed backend test owns the shared database. Use
`./backend-dev.sh manage test TEST_LABEL --noinput` to recreate a suspect retained
database. `./backend-dev.sh quickmanage ...` similarly reuses the running API for
allowlisted read-only `check`, `showmigrations`, `makemigrations --check --dry-run`
and `migrate --check` commands; state-changing variants are rejected. Explicit
`makemigrations`, `migrate` and `restart-workers` commands retain their existing
review/startup behavior. `./backend-dev.sh test` remains the fresh full acceptance path against
the isolated development PostgreSQL service, selected only for final validation or explicit user request under AGENTS.md D423/D425. The `quicktest` wrapper does not narrow broad app labels: choose exact affected methods/cases and reuse unchanged evidence. This workflow does not use an
installed host PostgreSQL.

## Environment and dependencies

Private settings live here in `.env` (local) and `.env.prod` (production), with
the tracked template at `../.env.example`. Both private files are Git-ignored.
The root `backend-dev.sh` loads `.env` through Compose for API/workers/Beat and
management commands. Production selects `.env.prod` explicitly with
`docker compose --env-file backend/.env.prod -f compose.yaml ...` from the root;
its initial blank secrets and placeholder origin must be configured before use.
Production also requires `MFA_ENCRYPTION_KEYS` with comma-separated Fernet keys,
newest first; retain old keys during rotation until all factors are reenrolled.
Development derives a local-only key when this setting is blank.
Angular public configuration lives separately in `frontend/src/environments/`.

### Run Django on the host

`config.settings` automatically reads `backend/.env` for direct host commands;
environment variables already supplied by the shell take precedence. Docker
services use explicitly supplied Compose values instead. Host production commands
must set `DJANGO_ENV=production` or `DJANGO_DEBUG=0` and supply production settings
explicitly; `.env.prod` is never loaded automatically.

Install the locked requirements in `backend/.venv` as below. To use the *same
isolated development database and Redis* without a Dockerized API, run from the
repository root:

```bash
./backend-dev.sh down           # if the full dev stack is already running; keeps data
./backend-dev.sh infrastructure # starts only isolated PostgreSQL and Redis
cd backend
.venv/bin/python manage.py migrate --check
.venv/bin/python manage.py runserver 127.0.0.1:18000
```

With the venv activated, `python3 manage.py runserver 127.0.0.1:18000` is equivalent.
`python manage.py runserver` without an address also works on Django's default
`127.0.0.1:8000`; use `18000` to work with Angular's existing local proxy.
The host connects to dev PostgreSQL on `127.0.0.1:15432` and Redis on
`127.0.0.1:16379` (loopback-only); installed host PostgreSQL on5432 remains
independent. This is host-run Django with Dockerized infrastructure. For wholly
host-provided infrastructure, start an explicitly dedicated database and broker
and override `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`,
`POSTGRES_PASSWORD`, `DJANGO_CACHE_URL` and `CELERY_BROKER_URL` in your shell.
Never point this project at an unrelated host database. To switch back, stop the
host server and run `./backend-dev.sh` from the repository root.

The target Python 3.13.15/PostgreSQL 18.6 (D049) passed the full backend suite in
Docker during P01-04 (D053). Earlier non-Docker checks used Python 3.12.3/PostgreSQL
16.15 under D051; those local instructions remain useful, but the old Python
micro version is not a production recommendation. D086 restored the pinned
official Redis8.10.2 image locally and checked the retained AOF/broker and scanner.

D056's prepared Alpine images passed the same suite and vulnerability gate.
The API image contains a build-validated pip-free virtualenv; use requirements
and rebuild to change dependencies rather than installing into a live container.
The commands below remain valid for a normal local development venv. Existing
Bookworm databases require [logical migration](../deploy/postgres/README.md)
before adopting the new PostgreSQL definition; the running user stack is untouched.

From `backend/`, create a virtual environment using the intended installed Python
interpreter, then install the lock. On the current host the explicit interpreter
is `/usr/bin/python3`; this avoids pyenv trying to select the absent target from
`.python-version`:

```bash
/usr/bin/python3 -m venv .venv
.venv/bin/python -m pip install pip==26.2.1
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
```

For updates, edit `requirements.in`, resolve in a clean virtual environment, and
review `pip freeze` against the lock. The lock was resolved on Python3.12.3 and
verified on the target Python3.13.15, including the Alpine musllinux wheel set.

## Isolated PostgreSQL without Docker

Use a dedicated development cluster, not an unrelated host database. These
commands are for the available PostgreSQL 16 binaries on this host. Initialization
is a **one-time** step; if the directory exists, inspect its state instead of
initializing over it. The directory is private, local connections use OS peer
authentication, and TCP is disabled.

```bash
mkdir -m 700 /tmp/opencode/organicseoops-p01-03
/usr/lib/postgresql/16/bin/initdb \
  -D /tmp/opencode/organicseoops-p01-03/data \
  --auth-local=peer --auth-host=reject --encoding=UTF8 --locale=C.UTF-8
/usr/lib/postgresql/16/bin/pg_ctl \
  -D /tmp/opencode/organicseoops-p01-03/data \
  -l /tmp/opencode/organicseoops-p01-03/postgres.log \
  -o "-c listen_addresses='' -c unix_socket_directories='/tmp/opencode/organicseoops-p01-03' -c unix_socket_permissions=0700 -p 55432" \
  -w start
/usr/lib/postgresql/16/bin/createdb \
  -h /tmp/opencode/organicseoops-p01-03 -p 55432 organicseoops
```

For an existing cluster use `pg_ctl -D ... status`, then the same start command
if stopped. To stop this cluster only:

```bash
/usr/lib/postgresql/16/bin/pg_ctl \
  -D /tmp/opencode/organicseoops-p01-03/data -m fast -w stop
```

The `/tmp` cluster is disposable development data and may disappear on reboot;
persistent development volumes belong to P01-04. Tests create/drop only
`test_organicseoops` on the explicitly configured server.

## Settings, migrations and checks

Settings automatically load `.env` for host commands unless a container/production
environment is supplied. The older private-cluster procedure above is historical;
if intentionally using that cluster, override its connection details explicitly.
From `backend/`:

```bash
export DJANGO_DEBUG=1
export DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
export POSTGRES_HOST=/tmp/opencode/organicseoops-p01-03
export POSTGRES_PORT=55432
export POSTGRES_DB=organicseoops
export POSTGRES_USER="$(id -un)"
unset POSTGRES_PASSWORD

.venv/bin/python manage.py check
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py test accounts config tenancy --noinput
.venv/bin/python checks/runtime_smoke.py
```

`DJANGO_SECRET_KEY`, `POSTGRES_HOST`, `POSTGRES_DB`, and `POSTGRES_USER` are required.
`POSTGRES_PASSWORD` is needed for password-authenticated servers; this local
peer-authenticated socket does not need it. `DJANGO_DEBUG` defaults to off, which
enables HTTPS redirects and secure cookies. Set trusted CSRF origins explicitly
with comma-separated `DJANGO_CSRF_TRUSTED_ORIGINS` when necessary; no CORS origins
are enabled. Production host/proxy/email/HSTS/MFA configuration remains later work.
The console email backend is for local development only. The secret in `.env`
remains stable for persistent sessions. Do not source `.env.prod` during local work.

## Logging and private artifacts

Application records are compact JSON on stdout. `X-Request-ID` is accepted only
in a bounded safe format; otherwise Django generates one and returns it on the
response. Request logs omit URLs, framework request paths are replaced, and a
central formatter redacts cookie/auth/OAuth/CSRF/signed-URL values. Provider code
must still log fixed event/error categories rather than raw responses; regex
redaction is defense in depth, not permission to log provider payloads.

`config.artifacts.save_private_artifact()` and `read_private_artifact()` are
internal building blocks, not endpoints. They buffer at most the configured limit,
accept only configured JSON/CSV/HTML/plain-text content and private owner-export ZIP
parts, generate opaque keys, reject
unsafe/download keys and expose generic storage failures. Local Compose shares a
private volume between API/workers; unit tests use in-memory storage. S3 mode uses
django-storages1.14.6/boto31.43.98 and IAM's default credential chain.
`tenancy.save_project_artifact()` and `read_project_artifact()` now bind these keys
to an exact persisted organization/project namespace, but remain internal. Future
API/job/share callers must still resolve and recheck actor access before every read.
Owner-captured ZIP parts use `organizations/<org>/exports/<snapshot>/` in that same
private bucket. Keep `application/zip` in the backend artifact-type configuration;
the owner snapshot endpoint fails closed without it. These bounded copies are
removed with the organization's active data, including older S3 versions.
Capture is dispatched after reservation to the audit worker; the owner sees a
PREPARING status and must reopen the manifest only after READY. A broker or
worker failure is not retried blindly: stale reservations become FAILED for
scoped owner cleanup, and READY requires private part readback verification.
The audit worker spools only the bounded ZIP to its private `/tmp` tmpfs before
writing parts; this does not increase the current archive limits or create a
complete all-size customer export.
An owner may instead select `source-parts-v2`. This explicitly sequential format
uses initial per-table high-water/count windows, <=50-row pages and lexical
visible-object traversal, copying one configured-size artifact per audit task
into independent <=8MiB ZIPs (`data` and `source.json`). It has no whole-ZIP
32MiB/5,000-row/1,000-object ceiling. Its manifest is paginated (50 descriptors)
and records observations/exclusions rather than promising an atomic DB/S3 view;
concurrent record-count loss fails capture and later/new source changes remain
outside the recorded windows. Committed stage boundaries can be redispatched
after broker failure, but an interrupted unknown write becomes FAILED and uses
the same scoped version cleanup. READY parts are readback-verified. The final
digest is a SHA256 descriptor chain, beginning with32 zero bytes and hashing
`previous_digest_bytes + canonical_descriptor_json` in position order; descriptors
contain position, size_bytes, sha256 and source, using sorted keys, UTF-8,
unescaped Unicode and compact JSON separators. It is not a concatenated ZIP hash.
An owner may also select `coherent-parts-v3`, using the same reservation, task,
private storage, descriptor chain and paginated manifest. One original PostgreSQL
view and protected visible-object window stay live through final readback and
READY; fresh owner and original logfile lineage checks also apply at delivery.
Rows and parts stay bounded without a whole-export row/object/byte ceiling, but
the original capture must finish within540 seconds. Lost/expired views cannot be
resumed. Durable write intents prevent replay or cleanup of uncertain writes,
even if their objects are currently absent. All formats share the three-capture
limit. Each v2/v3 download is an independent ZIP, not a concatenated archive.
No format is a full legal/account/backup export or enables closure.

Run `collectstatic` before the suite: the static-serving check deliberately uses
the collected manifest with DEBUG disabled. The smoke runner starts/stops the
installed Gunicorn on an ephemeral loopback socket and checks actual HTTP
health/admin/hashed static/404. It requires the running isolated database and
environment above; no persistent API process is left behind.

`CELERY_BROKER_URL` defaults to the private Compose service `redis://redis:6379/0`.
Set it explicitly for non-Docker workers; never point development at an unrelated
broker. Django checks do not connect to the broker. The four declared queues are
`default`, `ai`, `crawl`, and `audit`; unknown queues and non-JSON payloads are
rejected. There are no business tasks or periodic schedules yet, and no Celery
result backend: durable application job state belongs to Phase 4. The Celery
test uses only in-memory transport, not a live Redis server or worker.

To use the development admin:

```bash
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

The interactive command prompts for email/password. Do not put a real password in
shell arguments or committed files. Sign in through the Angular account page, open
Security and sessions, add the manual TOTP setup key to an authenticator, verify a
code, and store the recovery codes when shown. Staff access is `/admin/`; production
Admin and platform operations require an MFA-authenticated session, and normal users
cannot manage authenticators or enter Admin.

If a staff user loses both TOTP and recovery codes, verify the recovery request and
have a different active superuser run:

```bash
./backend-dev.sh manage reset_staff_mfa locked@example.com \
  --actor operator@example.com --confirm-email locked@example.com \
  --reason "Approved support ticket reference"
```

The command reveals no replacement secret. It removes the target's factors, revokes
sessions, records actor/target/reason, and requires normal password login plus fresh
enrollment. Never use ad hoc database edits. Public deployment is still gated on
production email/routing, manual accessibility validation, Redis restoration and the
remaining release checklist.

## Contracts

- Email identifiers are trimmed and lowercased across the entire address. Dots
  and plus tags remain distinct. Manager authentication (sync/async), model/form
  validation and ordinary saves share this rule. Normalize before uniqueness
  validation in future registration/email-change entry points.
- PostgreSQL's unique email field and canonical-value check protect concurrent
  and bypass writes. Bulk/raw/queryset writes must supply already-normalized,
  nonempty, whitespace-free values; database errors must not become public
  registration responses. Ordinary saves validate email syntax with Django.
- Password hashing, admin forms, sessions and CSRF use Django's implementations.
  DRF views require session authentication by default; future endpoints also
  need explicit tenant/role checks.
- `GET /api/health/` is anonymous, uncached and exempt from HTTPS redirect for
  internal health probes. It returns `200 {"status":"ok"}` when `SELECT 1`
  succeeds, or `503 {"status":"unavailable"}` on database failure. It reveals
  no database details. Other methods return 405. This is database connectivity,
  not migration/worker/provider readiness.
- Tests cover normalization/validation, duplicate/racing/bypass writes, inactive
  login denial, supported superuser creation, real admin login/CSRF, safe admin
  password editing, custom-user database references, health/default API denial,
  Celery routing/JSON acceptance and collected admin static serving.

See the [checkpoint](../docs/IMPLEMENTATION_STATE.md) for actual verification and
the [task ledger](../docs/IMPLEMENTATION_TASKS.md) for remaining foundations.
