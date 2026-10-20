# Local service configuration

Local container/CI acceptance passed on 2026-09-21 under D053–D057, including
remediated Alpine images, structured logging/private artifact checks, runtime/security checks and synthetic
atomic restore/persistence. Python3.13.15/PostgreSQL18.6 are retained; Redis8.10.1
is the local-only exception below. The active legacy stack is not upgraded; read
the transition warning before any startup. See the checkpoint for exact evidence.
This is loopback-only development HTTP, not a production deployment configuration.

## Service boundaries

| Service | Process / responsibility |
| --- | --- |
| `proxy` | nginx; only loopback publication, development default `127.0.0.1:8080` |
| `api` | Gunicorn WSGI; Django Admin and API; WhiteNoise serves collected admin assets |
| `worker-default`, `worker-ai`, `worker-crawl`, `worker-audit` | Separate Celery processes, each consuming only its named queue |
| `beat` | One Celery scheduler; initially empty schedule |
| `renderer` | Networkless non-root Playwright/Chromium process; only bounded request/result spools are shared with `worker-crawl` |
| `postgres` | PostgreSQL; dedicated persistent volume |
| `redis` | Private local broker; AOF persistence and no eviction |

API/workers/Beat use the same nonroot, read-only backend image. API/workers share
the private `artifact-data` volume at a mode0700 directory; Beat also mounts it for
one consistent image definition but does not write artifacts. Beat has a separate
persistent schedule volume. Its fixed
container name prevents accidental Compose scaling; never launch another Beat
against the same broker. Worker health checks use destination-specific ping.
The API runtime contains no pip/ensurepip; dependencies are validated by native
pip in the builder. PostgreSQL starts as UID70 without a root-switch helper.
The renderer uses its own pinned glibc image, no network/backend environment/data
or artifact mount, and only the two spool volumes shared with `worker-crawl`.

The internal `data` network contains PostgreSQL/Redis and their backend clients.
The base stack does not publish database ports. The explicit development override
also attaches the two infrastructure services to an isolated `host-access` bridge
and publishes only `127.0.0.1:15432` (PostgreSQL) and `127.0.0.1:16379` (Redis)
for direct host Python. No production port publication is added.
Backend processes have explicit outbound connectivity; the proxy reaches only
the API on the `edge` network. The base stack publishes only the proxy port;
the development-only DB/Redis publications above remain loopback-bound. Redis
protected mode is deliberately disabled for these local clients; do not reuse
this unauthenticated configuration in production.

D086 replaced D054's former local exception with pinned official Redis8.10.2.
The retained isolated dev AOF volume, four Celery workers and unchanged
HIGH/CRITICAL scanner passed locally. Production broker authentication and
deployment checks remain separate; the user's legacy stack was not upgraded.

nginx forwards the original Host (including development port), overwrites proxy
headers and resolves replacement API containers through Docker DNS. Django
health checks prove database connectivity, not migration/worker/provider
readiness. Actual API-to-Redis access, four worker queues and all eight container
health checks passed; Beat's running state/single instance and schedule volume
were checked separately (it has no healthcheck).
nginx access logging remains off so raw query tokens are not duplicated. Django
and Celery application records use JSON stdout with validated request IDs, safe
request-path replacement and centralized cookie/token/provider-error redaction.

## Environment

The root `.env.example` is the shared, secret-free backend template (D062).
Private backend files live in `backend/`: `.env` for local development and
`.env.prod` for production. Both are ignored by Git and should have mode0600.
`./backend-dev.sh setup` creates local credentials only for a fresh stack and an
unconfigured production file if absent. Existing credentials are never overwritten.
Production starts with DEBUG=0, blank secrets/hosts and an invalid placeholder
frontend origin; fill it with separate production values before deployment.
Compose rejects blank required secrets. Do not print resolved Compose configuration.

For production mail, set `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`
with `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` and a
verified `DEFAULT_FROM_EMAIL` in the private production env. Django requires
authenticated STARTTLS and a non-local relay with a ten-second timeout; only the
API and default notification worker receive these fields. Other workers and Beat
are configured with the disabled mail backend. This is configuration preflight,
not a sender-domain, actual delivery or bounce check; those remain P3A-10 work.

### SES feedback preparation (D104)

Optional weekly summaries (D169) remain disabled by default via
`WEEKLY_SUMMARY_DELIVERY_ENABLED=0`. Use the **same value** in the private API
app-host and default-worker host environments; Compose passes it only to those
two services. Recreate both affected services after an authorized configuration
change, without rebuilding images. Beat only dispatches discovery; AI/crawl/audit/
Beat receive neither this flag nor SMTP credentials. The private preference API
reports `rollout_off` or `enabled_optional` as configured availability, not live
email readiness or recipient eligibility. Saving own weekly intent does not
directly send mail; current recipient/source/suppression/entitlement fences,
completed UTC report-creation week dedupe and unknown-no-replay remain required.
No older-week backlog or paid analysis fills a digest. Keep rollout off until
actual SES/bilingual/manual/public release evidence is accepted. Own retained
transport history stays read-only and is not proof of inbox delivery/reading.

Optional daily operational digests (D181/D182/D185) independently default to
`ALERT_DIGEST_DELIVERY_ENABLED=0`, with the **same value** on API and default worker
only. Recreate the API after an authorized flag change, without rebuilding. Hourly Beat
dispatches bounded current-day/high-water discovery; it carries no alert flag or
SMTP credentials. The native preference reports `rollout_off` or `enabled_optional`
as configured availability, not live readiness or current eligibility. Explicit
own-history inspection never requests sending or retry. Reservations
pin original full source metadata and current recipient, dedupe actual related
episodes across days, and consume skipped claims as well as sent/unknown claims.
Sending is committed before SMTP; uncertainty is never replayed. No older-day
backlog or new paid analysis is run. Keep rollout off for the remaining consumer
and actual SES/bilingual/manual/public gates; this kernel is not an incident,
severity, stale-age, confirmed-regression or inbox-delivery guarantee.

The ordinary Compose stack has **no SES feedback queue environment**. Place
`worker-default` on a separate EC2 host/instance profile, using only the
`deploy/compose.feedback-worker.yaml` overlay and a private ignored backend
environment there. Start only `worker-default` with `--no-deps`; the app host
starts API, Beat and other workers without `worker-default`. Both hosts need
private authenticated DB/Redis connectivity and protected artifact access,
which P13-01/P13-03 must prepare and check before any deployment. Do not use a
single host instance profile with SQS rights for a multi-service Compose stack:
other containers can also reach IMDS. Keep the application-host role unable
to read/delete the feedback queue, and restrict the dedicated worker-host role
to `ses-feedback-worker-policy.json` plus its separately reviewed job/artifact
permissions. An environment-variable omission alone is **not IAM isolation**.

`ses-feedback-stack.json` is an unapplied CloudFormation template for a
dedicated SNS standard topic, exact SES identity/account publisher policy,
encrypted SQS source and dead-letter queues, five-receive redrive and
non-raw SNS→SQS subscription. Its standalone topic/queue/worker policy files
make those boundaries independently inspectable. Only an SES-verified sender
identity may publish; the queue accepts only that SNS topic; no public webhook
receives SNS messages. On the isolated worker set the stack output queue URL,
topic ARN and same `AWS_REGION`; blank values keep polling disabled. Configure
SES bounce/complaint feedback for the exact identity and leave original email
headers disabled. Before launch, verify SES sender identity, SPF/DKIM/DMARC,
the actual topic and queue policies, hosted task-role isolation from API/Beat/
other workers, poison-message DLQ behavior and sender/recipient recovery in an
authorized sandbox. Templates and fixtures do not establish those results.

### Prepared frontend and private-storage identities (P13-01)

`frontend-origin-stack.json` is an **unapplied** private S3 bucket, OAC and
CloudFront distribution template. It forwards only `/api/*`, `/_allauth/*`,
MFA-protected `/admin/*` and Admin asset `/static/*`
to an HTTPS Django origin with zero cache TTL, all viewer cookies/query/headers
**including the public Host**, and a no-store response policy; Django must see
the root browser Host to validate exact OAuth callback URLs and session CSRF.
The origin policy adds CloudFront-generated viewer address. The production
nginx proxy trusts it only behind the ALB and passes one viewer IP to Django;
ordinary requests without this header fail. Register signed Paddle webhooks
at the canonical root-host `/api/*` path through CloudFront, not as a direct
API-host bypass.
For a build's exact public route inventory, `npm run build` emits the checked
`frontend/dist/organicseoops/frontend-origin-stack.json` outside the uploaded
browser directory. It derives only static route-function paths from that build,
preserving this template's other settings. Prepare the origin infrastructure
from this generated artifact for the same release; the publication guard rejects
an absent/stale artifact before deployment credentials. Generation is not an
actual CloudFront update or authorization to deploy. `publication.js` is mutable
postbuild public review configuration, uploaded with revalidation before HTML,
never immutable-cache or bundled into hashed Angular assets.

Public/CSR deep-link
resolution now uses a default-behavior CloudFront Function: only the known
development prerenders map to their nested HTML, extensionless account/app
paths map to the CSR shell, and unknown extensionless public paths return a
minimal noindex HTTP404 without a global error rewrite. The OAC principal has
S3 ListBucket on this *frontend bucket only*, scoped to the one distribution,
so a missing static asset returns S3 HTTP404 instead of403 without altering
API 403s; the static function always rewrites `/` to `/index.html` and never
passes a bucket-list request through to S3. Noncanonical accepted static Hosts
receive a 308 to the parameterized public alias with ordinary repeated query
parameters preserved. Hosted 404/listing/asset and redirect checks, reviewed
retired-URL mappings, cache budgets and changed-HTML invalidation remain
P13-02. Do not invent old/replacement paths before publication review. The
selected certificate must be valid for the viewer alias in
us-east-1, and the API origin needs a separate valid HTTPS certificate that
covers both public and API hostnames. `api-origin-alb-stack.json` prepares an
HTTPS ALB restricted to CloudFront's managed origin-facing prefix list and an
API-instance port80 security group reachable only from the ALB.
`compose.production-app.yaml` binds `nginx.production.conf` to the private VPC
IP for that ALB target. Django permits only the public and API hosts; never
trust arbitrary `X-Forwarded-Host`. Root-host OAuth callback URLs traverse
`/api/*`; real headers, signed webhook bytes and IPv4/IPv6 throttling require
deployed checks. No DNS, certificate, distribution, bucket or ALB exists.

`backend-host-roles-stack.json` prepares **separate** SSM-capable application
and feedback EC2 instance profiles: app-host IAM explicitly denies the exact
feedback queue, feedback-host IAM allows only that queue plus reviewed
artifact-prefix and ECR-pull policies. `api-origin-alb-stack.json` first
creates an empty HTTPS target group and an ALB restricted to CloudFront's
origin-facing prefix list; `backend-host-stack.json` then prepares two
private-subnet instances with distinct profiles, no public IP/SSH ingress,
IMDSv2-required encrypted root EBS and a separately retained encrypted
PostgreSQL data volume attached to the app host. The feedback host may reach
app-host private15432/16379 only by its security group, with TLS/SCRAM/ACL
still enforced inside the containers. After app host/proxy/migration checks,
a controlled update registers the app instance as the ALB target. Changing a
target, detaching a retained volume or restoring a database requires explicit
status/backup checks; never repeat an operation with unknown outcome. Public
DNS/ACM/target health, EBS mount/filesystem, SSM/VPC endpoints and real
instance-profile deny/allow tests remain authorized hosted work, not local
template acceptance.

Local preparation order: render the private app-host and feedback-host Compose
overrides with synthetic VPC IPs, authenticated TLS URLs and placeholder CA
paths using `config --quiet`; run the source checks and validate the separate
nginx production file with `nginx -t`. This does not start services. During a
separately authorized hosted release, create/verify the private buckets and
roles, targetless ALB/security groups, then private EC2 instances and retained
data volume in the selected availability zone. Provision/mount encrypted EBS,
certificates with correct Docker service/IP SANs, UID-readable keys and private
Redis ACL *before* attaching real DB/Redis ports. Ensure app and feedback host
private routes, ECR/S3/SSM access and broker isolation; never put Redis/DB or
EC2 SSH on a public listener. Validate migrations as a controlled one-off
operation after a recoverable backup, start only the intended processes and
register the healthy app instance as the ALB target. Verify the unauthenticated
health check, root-host cookies/CSRF/OAuth/MFA, signed webhook bytes,
CloudFront-generated IPv4/IPv6 viewer address, distinct per-user throttling,
S3 anonymous denial and SES queue IAM **denial** from all non-feedback hosts.
Keep the prior image and retained volume until explicit restore/rollback
evidence passes; application rollback must not assume database rollback is
safe. Unregister an unhealthy target before restoring an older compatible
image. CFN `Retain` preserves PostgreSQL EBS and buckets when a stack is
removed: list/check those retained resources separately, do not auto-delete
customer data or silently retry a failed stack update.

`iam-frontend-deploy-trust.json` accepts only GitHub's OIDC audience and one
configured repository/production branch; `iam-frontend-deploy-policy.json`
limits S3 object update to that frontend bucket and invalidation to its one
distribution. Set the real owner/repository/branch/account only during the
authorized deployment preparation; no Git remote or branch is assumed now.
`.github/workflows/frontend-deploy.yml` is unapplied: matching frontend/source
pushes run it only on the repository's configured exact `PRODUCTION_BRANCH`;
manual dispatches must use that branch as well. Set repository variables
`PRODUCTION_BRANCH`, `AWS_REGION`,
`FRONTEND_BUCKET_NAME`, `FRONTEND_DISTRIBUTION_ID` and
`FRONTEND_DEPLOY_ROLE_ARN` and `FRONTEND_PUBLIC_ORIGIN` to match the exact-branch
OIDC role/policy and verified canonical HTTPS frontend alias before
an authorized run. It checks/builds with pinned Node/npm and refuses the
current draft/noindex routes through `frontend/checks/publication-guard.mjs`
before requesting AWS credentials. The guard requires the human-recorded
reviewed HTML SHA256 for **every** public route and genuine reciprocal EN/TR
route records; the provider-readiness guard separately rejects claimed
unverified integrations ([evidence ledger](../docs/PROVIDER_READINESS.md)).
The repo currently has no such approval and release correctly
fails. See [public content workflow](../docs/PUBLIC_CONTENT_WORKFLOW.md). It
uploads immutable hashed JS/CSS first, revalidating other files next, and
then all nested prerendered/CSR HTML while deleting removed HTML; an upload
error stops before the invalidation. It waits for the distribution's
invalidation after upload. Keep the previous versioned frontend objects and
distribution configuration for a controlled content rollback; rerun only
after reconciling an unknown upload/invalidation result and inspect the
generated HTML/asset manifest first. Local `test_frontend_delivery.py` uses
fake AWS commands only; no GitHub or AWS workflow was run.

[Site-monitoring preparation](../docs/SITE_MONITORING.md) records fixed public
SEO, availability, performance, consent/handoffs, cleanup and rollback coverage
without selecting an origin/owner or enabling collection. Run its standalone
offline report with `python3 deploy/checks/site_monitoring.py`; reference coverage
never establishes release verification or replaces the existing approvals.

`private-storage-stack.json` separately prepares retained, encrypted and
Block-Public-Access artifact, backup and versioned release-bundle buckets. Only
the scoped CI role writes `releases/*` to the release bucket; the distinct
app and feedback instance profiles can read just that prefix without access to
customer artifacts or backups through this release grant. `iam-backend-deploy-policy.json`
restricts image push to the four reviewed ECR repositories and SSM SendCommand to the two
reviewed instance IDs and AWS shell document; read-back is region-restricted.
The existing exact-branch GitHub OIDC trust document applies to a separately
created backend CI role as well as the narrower frontend role. Backup versions use a conservative
30-day current/1-day noncurrent rule; P13-04 still owns actual backup jobs,
deletion timing, restores and confirmation of D098's maximum post-deletion
backup window. `backend-ecr-stack.json` prepares private encrypted,
immutable-tag backend, isolated renderer, PostgreSQL and proxy ECR repositories with scan-on-push
and bounded untagged retention;
P13-03 owns actual CI image build/push and rollback. The operator supplies
the selected repository ARNs to the scoped host roles.
`iam-backend-artifacts-policy.json` grants only the private
artifact prefix to the API/worker roles, and
`iam-backend-image-pull-policy.json` grants pull from one ECR repository.
The versioned artifact bucket retains current project files until an authorized
deletion pass; its one-day noncurrent-version lifecycle is only a fallback.
The app-host role has scoped `ListBucketVersions`/`DeleteObjectVersion` plus
`DeleteObject` for exact artifact-prefix cleanup. The feedback worker has only
scoped `DeleteObject` for transient files, not version enumeration/deletion.
`tenancy.artifacts.delete_closed_project_artifact_batch` requires a persisted
closed/suspended organization and exact project ownership; its 100-version
passes remove old versions and delete markers, including previously hidden
objects, and re-list before a retry after an unknown result. Bounded owner
snapshot copies under `organizations/<org>/exports/<snapshot>/` use the same
private artifact bucket; the deletion runner also removes their scoped versions
and markers before database cleanup. A current owner may discard only a FAILED
capture in bounded app-host passes, never a READY copy or another tenant's path.
Production artifact-type configuration must allow `application/zip` for this
capture while keeping the bucket private. This is a local
fixture-checked capability, not a scheduled deletion or proof of actual S3
object/version expiry. Verify deployed IAM denials, remaining versions and
active-store/backup deadlines before claiming D098 retention acceptance.
The separate app-host `organicseoops-customer-deletion.service`/`.timer` is
staged but **must not be enabled until** complete owner export, OAuth revoke,
DB cleanup and the marked P02-06 security gate pass. Once authorized, its
daily 03:30 UTC pass checks the retained EBS mount and exact healthy app API,
then invokes `process_customer_deletions --execute --limit 10`; no customer
names/identifiers enter its stdout. The command cannot run on the feedback
host, refuses implicit execution, and records incomplete/blocked work for
review. Reconcile unknown storage/provider outcomes before repeating a
manual operation; locally checked timers/fixtures are not a production
deletion-deadline or bucket-version audit.

READY-copy expiry is separate from source-data retention. Leave
`CUSTOMER_EXPORT_COPY_POLICY_REFERENCE` and `CUSTOMER_EXPORT_COPY_LIFETIME_DAYS`
unset until the policy owner approves a reference and positive whole-day duration.
The API validates configuration; the audit worker stamps its current reviewed
policy on each newly completed capture (all three formats). Deploy matching
configuration to both. Existing captures receive no retrospective expiry, and
later configuration changes cannot extend or remove a stored deadline.
At that deadline, manifests and part downloads are denied even if cleanup is
late. History shows expired copies with cleanup potentially pending; downloaded
customer copies and backups are not remotely erased. Manifests explicitly deny
legal-export completeness and list restricted billing/audit, credentials and
hidden storage/backup exclusions. Counsel owns any additional legal inclusion
and disclosure requirements; this setting does not certify them.

The default-queue hourly `tenancy.purge_expired_customer_copies` task attempts
at most20 expired READY copies, at most10 objects/versions per copy. It shares
the organization lock with capture/closure, refuses unresolved coherent writes,
and retains metadata/occupied slots until the exact prefix has no remaining
versions or markers. Storage failure rotates the attempted copy behind others;
next scheduled passes resume cleanup. Monitor pending/failed counts and task
health before making hosted removal-time claims. Apply additive tenancy0086
before deploying readers/workers; legacy expiry remains null. A rollback must
preserve recorded deadlines and references, since dropping those columns would
remove their access/cleanup authority. Actual S3, backup and deadline proof
remain unverified; no policy duration is selected by this runbook.

Account identity cleanup is a separate staff action at
`/admin/accounts/user/identity-cleanup/`, requiring current session MFA,
`accounts.change_user`, an exact already-closed account ID and the configured
policy reference. Configure `PERSONAL_IDENTITY_ERASURE_POLICY_REFERENCE` and
`PERSONAL_IDENTITY_TRIAL_RETENTION_DAYS` only from reviewed retention terms;
both are empty by default. Keep `PERSONAL_IDENTITY_RETENTION_KEY` private,
random and stable (at least32 characters), including through deployments and
backup restores while fingerprints remain. Missing or mismatched keys deny
new automatic trials when unexpired restricted fingerprints exist. The policy
and key are forwarded only to the API container; expiry workers need no key.
A key change requires reconciliation, never deleting fingerprints to bypass it.
The action removes account email/authentication/diagnostics, preserves the
inactive user ID for source/audit lineage, and keeps only keyed verified-address
trial fingerprints for the configured duration. It does not erase independent
organizations' invitations, report recipients, content or restricted history,
and does not certify legal erasure or backup expiry. Both self-service closure
switches remain disabled pending their release gates. Fingerprints cease to
affect eligibility at their exact deadline; the fixed default-queue hourly
`accounts.purge_retained_trial_identities` task deletes at most1000 expired
rows per pass and rechecks deadlines before deleting. Hosted task health,
backlog/deadline monitoring and backup expiry remain release evidence.
Migration `accounts.0008` adds email/session lifecycle guards against stale
child writes. Conflicting in-flight writes may abort safely. Do not roll this
migration back on retained accounts without first preserving and reconciling
the restricted fingerprints and erased-state lineage; its schema reverse
drops the new table and guards.
No template means objects are anonymously inaccessible until an actual
bucket-policy and IAM denial test passes on authorized AWS.

The D105 feedback worker must use its **own EC2 instance role** and the
dedicated `deploy/compose.feedback-worker.yaml` override. Put its PostgreSQL
and Redis CA files on that host as private read-only mounts. The private
PostgreSQL IP must present a certificate valid for verify-full; broker and
cache URLs must use authenticated `rediss://` with
`ssl_cert_reqs=required&ssl_ca_certs=/run/organicseoops/redis-ca.pem`. The
worker uses S3 artifacts, not an app-host local Docker volume. The app host
role additionally needs `iam-app-host-deny-feedback.json`; the worker host
role needs the exact queue policy and separately scoped artifact/image rights.
The app host runs API, proxy, Beat, AI/crawl/audit and private DB/Redis
services **without** worker-default; the feedback host runs **only**
worker-default with `--no-deps` and private authenticated VPC endpoints.
`compose.production-private.yaml` and `compose.production-app.yaml` locally
prepare VPC-IP-bound PostgreSQL TLS/SCRAM and Redis TLS/private ACL containers
with app-host verify-full/`rediss://`/S3 startup checks. Private cert/key/ACL
files, SANs and actual EC2/security-group/volume layout must be supplied and
verified before any hosted run. PostgreSQL UID70 must read a mode0600 key;
mount the retained encrypted EBS volume at `PRIVATE_POSTGRES_EBS_MOUNT` and put
the UID70-owned `PRIVATE_POSTGRES_DATA_DIR` **under that real mount**. The
production Compose bind replaces the base Docker-named PostgreSQL volume;
confirm restored/new data on the retained volume before starting Postgres.
the Redis server user needs its private TLS key and a disabled default ACL
user with separately scoped app/health credentials. Backend S3 artifacts must
replace cross-host local volumes. Synthetic environment/Compose checks confirm
only file shape/startup preflight, not TLS negotiation, VPC routes, Redis ACL
capabilities, encrypted EBS or cross-instance IAM denial.

Compose reads the explicitly selected file and injects process environment values;
it does not discover `backend/.env` automatically. The dev wrapper selects it for
you. For production configuration validation (no startup):

```bash
docker compose --env-file backend/.env.prod -f compose.yaml \
  -f deploy/compose.production-private.yaml -f deploy/compose.production-app.yaml config --quiet
```

The separate worker-host file is `backend/.env.feedback.prod` with only
`deploy/compose.feedback-worker.yaml` as its override and a distinct IAM role.
Both Compose validations select configuration only: TLS, email, cloud/storage
and release gates still require their deployment work. Never load the
development override for production or start the base stack without the
app-host private/TLS overrides.

P13-03's `deploy/compose.release.yaml` selects **one reviewed backend ECR
image by digest** via `BACKEND_IMAGE=...@sha256:...` on both hosts. The app
and private-data overrides also require `RENDERER_IMAGE=...@sha256:...`,
`POSTGRES_IMAGE=...@sha256:...` and app-only `PROXY_IMAGE=...@sha256:...`
for the renderer, database and proxy. The host release bundle must include
`renderer/seccomp_profile.json`. Include the release override
after the appropriate app or separate feedback-host override on every
production Compose command; use `--no-build` for `up` and `--no-deps` for
one-off API migration/feedback-worker start so the base development build and
unwanted base services cannot start. Do not start the new image until its
digest, known migration compatibility, recoverable backup and current service
state are recorded; treat migrations as an explicit one-off controlled step.
`bash deploy/backend-release.sh app` requires host-specific `ENV_FILE`, exact
backend/renderer/PostgreSQL/proxy image digests,
an existing UID70-owned PostgreSQL directory on the
verified EBS mount, `BACKUP_VERIFIED=1` and `ORIGIN_DRAINED=1` after external
backup/ALB verification. It checks Compose config and pulls all four images before
one-off `migrate`, then starts only the app-host services including renderer
and waits for their health;
run `bash deploy/backend-release.sh feedback` separately on its EC2 host after
app database/API migration succeeds. Feedback uses `--no-deps` and starts
only worker-default. On failed or unknown migration, image start or hosted
health, stop and inspect applied migrations, target state, backups and existing
jobs; do not repeat or automatically reverse the schema. Restore a previously
known compatible image by digest only after checking schema compatibility.
Hosted CI/SSM execution and recovery/compatibility proof remain P13-03 release
checks. Local fake-Docker checks are not an ECR pull, hosted backup, deployment
or production migration.

The prepared `.github/workflows/backend-release.yml` runs only for the exact
configured production branch. It tests source and built backend/renderer/PostgreSQL/proxy images
in a disposable CI stack (including vulnerability scanning), pushes immutable
ECR tags and records digests, then uploads a checksum-recorded secret-free
Compose/proxy/renderer-seccomp bundle to the private `releases/<commit>.tar.gz`
key. Pushes **stage only**. An explicitly selected manual release requires
verified backup and drained ALB origin; SSM waits for app migration/health
before sending any command to the feedback worker host. Repository variables:
`PRODUCTION_BRANCH`, `AWS_REGION`, `AWS_ACCOUNT_ID`, `BACKEND_DEPLOY_ROLE_ARN`,
`BACKEND_REPOSITORY_URI`, `RENDERER_REPOSITORY_URI`,
`POSTGRES_REPOSITORY_URI`, `PROXY_REPOSITORY_URI`, `RELEASE_BUCKET_NAME`,
`APP_INSTANCE_ID` and `FEEDBACK_INSTANCE_ID`. The backend deploy role uses
the same exact-branch OIDC trust as the frontend role but the separate
`iam-backend-deploy-policy.json`; do not combine their policies.

D421 replaces the single backend validation job after the local full run
exceeded360 minutes. CI and release call `backend-checks.yml`: it builds,
checks migrations, smokes and scans four images once, then runs two exhaustive
module groups of all six apps on isolated runners (360 minutes each, neither
cancelled when its sibling fails). The ordinary local full runner is unchanged.

The build uploads only a Docker image archive. Its immutable current-run
artifact ID, archive SHA and four image IDs reach every consumer through job
outputs. Consumers verify SHA before loading and all four local tags afterward;
no rebuild is permitted. Release first checks the configured production branch,
destinations and manual backup/drain inputs, requires every validation job,
then verifies the exact archive again before AWS authentication or pushes.
Actual hosted transfer, every group’s duration and release behavior remain
unverified. A balanced test count does not prove balanced runtime; measure each
whole job before release acceptance. Serving timeouts are unchanged.

On each host, an operator must privately provision mode0600
`/etc/organicseoops/app.env.prod` or `feedback.env.prod` before an authorized
release. The digest/sha-validated SSM command symlinks it to the ignored
versioned `backend/.env.prod` or `backend/.env.feedback.prod`, downloads the
reviewed bundle through the host role and executes the matching host release.
Both private env files must specify the same exact HTTPS `FRONTEND_ORIGIN` and
`API_ORIGIN`, `DJANGO_ALLOWED_HOSTS` with only their two hostnames and
`DJANGO_CSRF_TRUSTED_ORIGINS` with only the frontend origin; production-host
settings reject extra/wildcard hosts and origins.
Provision the app's retained PostgreSQL volume at `/mnt/organicseoops` with
UID70-owned `postgres/`; deploy the pinned Postgres image from ECR, and
confirm certs, ACL, current DB migration and rollback compatibility before
dispatching. `.github/workflows/backend-rollback.yml` takes an operator's
**previous checked bundle checksum and image digests** only after backup,
drain and compatibility confirmation; its app path skips `migrate` and uses
`--no-deps` so running PostgreSQL/Redis containers are neither pulled nor
restarted, then updates feedback after app health. Never claim a schema rollback from an
image rollback. Both workflows, IAM and shell remain unexecuted in AWS;
the local fake-AWS/Compose checks cannot verify real SSM, EBS or TLS.

D417 builds `deploy/proxy/Dockerfile` from the existing pinned Nginx1.30.5
Alpine-slim base with only fixed `pcre2=10.49-r0`. Local and CI builds include
the proxy; the immutable encrypted `organicseoops-proxy` ECR repository is
published by the exact repository grant and pulled only by the app host.
Release and compatible rollback explicitly pull its reviewed digest before
starting the proxy. Feedback requires no proxy image or proxy repository grant.
Old release bundles predate this proxy contract: record the reviewed bundle
version and compatible image set together for rollback. Native image scanning,
config/health/static smoke and hosted verification remain separate evidence.

The renderer scan excludes exactly two Python advisory IDs from a base-image
third-party SBOM **only if the running renderer has no msgpack or setuptools
distribution**; `deploy/checks/security.sh` enforces that absence before
using `trivy-rendererignore`. The Ubuntu GStreamer bad-plugin finding was
removed from the Chromium-only renderer image instead. Recheck the exception
whenever the pinned Playwright base image or renderer dependencies change.

### Prepared backups and restore evidence (P13-04)

The app instance profile alone may write/read `backups/*` in the private
versioned backup bucket and emit `OrganicSEOOps/Backup` metrics; the feedback
profile has neither permission. `postgres-backup.sh` runs only on the app host
through `organicseoops-backup.service`/`.timer` (daily 02:15 UTC plus a bounded
random delay). Install those reviewed units and a private mode0600
`/etc/organicseoops/backup.env` with only `BACKUP_BUCKET` and `AWS_REGION`
**after** authorized host provisioning; prepare root-owned mode0700
`/mnt/organicseoops/backup-staging` on the retained EBS mount. The service
uses the successful release's `/opt/organicseoops/current` link. Backup takes
a single healthy Postgres container, streams a custom-format dump to the
private mounted staging directory only when EBS has room for at least the
current database size plus 1GiB, verifies its archive TOC, writes an
AES256/SHA256-protected S3 object under one UTC-day key without overwrite,
emits success/failure and deletes the temporary file. An existing key or
uncertain upload outcome requires inspecting S3 checksum, timer state and
database recovery point before any retry. A leftover `backup.*.pgcustom`
after a host/process crash also blocks the next attempt until the operator
checks its outcome and securely resolves it; the timer must not silently
overwrite or abandon customer-bearing temporary data. Do not log/archive the
raw dump.
`backup-alarms-stack.json` requires an operator-owned SNS alert topic and
alarms on failure/missing daily backup and EC2 status. An alarm source template
does not establish real email/on-call delivery; test the topic/subscriber and
missing/failure transitions on authorized AWS.

The same template prepares a retained 30-day CloudWatch backend log group and
alarms for app/feedback service liveness, retained app EBS/feedback root disk,
host memory and enabled Search Console schedules that remain over two hours
past due. Install `organicseoops-service-check@.service`/`.timer` separately as
`@app` and `@feedback` with private mode0600
`/etc/organicseoops/monitoring.env` containing only `AWS_REGION`; each five-
minute probe checks only its own Compose project/services and publishes
bounded aggregate counts, never project IDs or customer data. On a healthy app
host the probe invokes the private `publish_ops_metrics` Django command for
five-minute job failures/lifecycle and attempted-provider failures/measured
duration. Unknown provider duration stays absent rather than becoming zero;
the same app-only aggregate reports customer deletion runs whose active-store
deadline has passed and deliberately closed organizations still missing a
deletion run after 30 days. Both proposed `OrganicSEOOps/Jobs` alarms breach
on a count of one and on missing app-host metric publication; they include
only an `Environment` dimension, never tenant/domain IDs. This does not detect
a trial/paid lapse that has no deletion run yet; operator reconciliation of
provider/trial source truth and hosted alarm delivery remain release evidence.
The operational window and metric names do not imply provider attribution or
complete customer coverage. A missing
PostgreSQL EBS mount fails the app heartbeat and raises the disk signal; the
feedback host has no Postgres/Beat expectation. `cloudwatch-agent.json` defines
host memory, root/EBS disk and Docker JSON stdout/stderr log collection for
the same private log group; install/start an agent using the distinct EC2 role
only during authorized hosting. Existing Django JSON request/job correlation
appears in these private logs; no raw dump, API token or customer export is
included in prepared alert dimensions. The overdue-schedule signal checks
**only enabled Search Console schedules** whose `next_run_at` is more than
two hours behind; disconnected/paused sources and blocked GA4 reporting are
not interpreted as zero/fresh data. Missing overdue-schedule metrics do not
imply success: separate missing-data-breaching service alarms cover a stopped
host/probe. Validate actual metric dimensions, agent IAM delivery and SNS
subscriber receipt on AWS before relying on any alarm.

To rehearse a restore **without production data**, start a new isolated
PostgreSQL/Redis target with an empty public schema and distinct project,
network, port and volume. `deploy/checks/restore_smoke.py --env-file
backend/.env.check-P13-04 --compose-override <reviewed-disposable-image-override>`
creates two synthetic Unicode users in a disposable Bookworm source, dumps
with `pg_dump -Fc`, proves a forced failed `pg_restore --single-transaction`
leaves the target empty, restores successfully and checks Django objects,
migrations, email uniqueness and sequences. It prints elapsed synthetic
rehearsal time; this does not measure production RPO/RTO. It refuses a
populated target or any project outside its small disposable allowlist. The
restored target retains **only synthetic** rows for explicit app health and
restart verification, then its containers and volumes must be removed.

For a **later separately authorized real restore**, record the latest
successful backup UTC key/checksum, source database and affected write window.
Drain the origin and stop app writers/Beat before recovering. Download the
private object into a restricted file on a *new* isolated target, verify its
S3 SHA256 checksum and `pg_restore --list`, and use single-transaction restore
into an empty database with a separately reviewed role/locale/image contract.
Check schema, counts, references, sequences, permissions, Unicode, migrations,
app health and exact backup timestamp; record actual data-loss interval and
wall-clock restore time before deciding any cutover. Never auto-restore over
a populated production database or assume an old image reverses schema.
Customer-bearing backups have a 30-day current-object/1-day noncurrent
version lifecycle (D098's maximum 35 days after active deletion), subject
to actual bucket policy/version/lifecycle and deletion checks at release.
RPO/RTO targets, hosted restore timing and alert ownership remain launch gates.

`DJANGO_DEBUG=1` is explicit local HTTP configuration. Cookie HTTPS flags and
redirects remain on by default in Django when debug is off. Production needs
reviewed TLS, hosts/proxy trust, secret delivery, Redis access controls, email,
staff MFA and the deployment gates before exposure.

Compose fixes DB/broker hosts to its private service names even if shell
environment variables were used for a different local cluster. For non-Docker
backend commands, export the actual socket/DB variables documented in
[backend/README.md](../backend/README.md); Django reads the exported environment.

### Private artifacts

Local Compose uses the project-scoped `artifact-data` volume; direct local/test
runs default to ignored `backend/private-artifacts/` and tests use Django's memory
storage. Internal save/read functions accept only JSON, CSV or plain text, generate
opaque safe keys, enforce an actual-byte10MiB default limit, check size before
opening and return generic storage errors. P02-03 adds internal exact persisted-project
namespace wrappers, but there is still no HTTP artifact route, model or signed-share
API; future callers must perform actor authorization before each read or delivery.

Production sets `ARTIFACT_STORAGE_BACKEND=s3`, `ARTIFACT_S3_BUCKET`, `AWS_REGION`
and an optional private prefix. Do not add static AWS keys: django-storages/boto3
uses the EC2 IAM role/default credential chain. Objects use private defaults,
authenticated five-minute URLs, no overwrite, private/no-store metadata and
server-side AES256 encryption. P13-01 must still verify a distinct private bucket,
Block Public Access, encryption, least-privilege prefix IAM, lifecycle/retention
and anonymous denial. Configuration and mocks are not deployed-S3 readiness.

## Isolated local development

`backend-dev.sh` always uses the explicit `compose.yaml` plus
`compose.development.yaml` files, fixed project `organicseoops-dev`, loopback port
`18000`, dedicated image tags and dedicated volumes. It never operates on the
legacy `organicseoops` project or temporary check projects.

Run the one-time setup from the project root:

```bash
./backend-dev.sh setup
```

Setup creates `backend/.env` with mode0600 and a blank-secret `backend/.env.prod`, builds
the backend/PostgreSQL/renderer development images, starts private PostgreSQL/Redis, applies
migrations explicitly and starts all ten services. If the environment file is
lost while development containers or volumes remain, the script refuses to
generate replacement credentials.

Normal commands reuse those images and persistent data:

The following is a command reference, not a sequence to run on every edit/session. Select only the operation required by the changed boundary under AGENTS.md D423/D425; full `test` is final validation, and migrations/restarts/rebuilds remain explicit.

```bash
./backend-dev.sh                 # same as: ./backend-dev.sh up
./backend-dev.sh status
./backend-dev.sh logs            # API logs; optional service names are accepted
./backend-dev.sh quickmanage check
./backend-dev.sh quickmanage makemigrations --check --dry-run
./backend-dev.sh quicktest jobs.tests.JobFoundationTests
./backend-dev.sh test
./backend-dev.sh manage check
./backend-dev.sh migrate
./backend-dev.sh makemigrations accounts --dry-run --verbosity 3
./backend-dev.sh restart-workers
./backend-dev.sh rebuild
./backend-dev.sh down             # keeps all named volumes
```

The API runs Django's development server and reloads ordinary edits under
`backend/config/`, `backend/accounts/` and `backend/manage.py`. The same paths are
mounted read-only into workers and Beat; restart them after their imported code
changes. `rebuild` is needed only when backend requirements or the Dockerfile
changes. Add a read-only mount to `compose.development.yaml` when a new Django app
directory is introduced. Migrations stay explicit and reviewed.
`makemigrations APP` gives only that app's migrations directory a temporary writable mount and
runs as the host UID/GID so generated migration files retain normal ownership.
At a session needing backend runtime, inspect `status` once and reuse healthy services; documentation-only and frontend-only work skips backend startup/status. Run
`up` once only when required containers are missing or stopped; diagnose unhealthy
services before restarting and do not retry startup in a loop. `quicktest` uses
`compose exec` plus Django `--keepdb` inside the running API container, takes a
non-blocking per-user lock shared by all wrapper-managed backend test paths, and
never starts services. The ordinary `manage test ... --noinput` path recreates
that database when needed; `test` remains the fresh acceptance path. `quickmanage`
uses the same running API without starting services for allowlisted read-only
checks and refuses state-changing migration variants. Leave the stack
running between sessions unless a task requires isolation, cleanup or a
configuration change.

Container services still use `postgres:5432` and `redis:6379`. The development
override publishes separate loopback-only ports15432/16379 for host Django; host
PostgreSQL on `127.0.0.1:5432` does not conflict. nginx publishes
`127.0.0.1:18000` when the full stack runs. For host-run Django on the Angular
proxy port, run `./backend-dev.sh down`, then `./backend-dev.sh infrastructure`,
then `.venv/bin/python manage.py runserver 127.0.0.1:18000` from `backend/`.

The Angular development server proxies `/api` and `/_allauth` to that endpoint so
browser sessions and CSRF remain same-origin at `http://127.0.0.1:4200`.

## Fresh installation startup

**D056: do not use this recipe to replace an existing Bookworm installation.**
Reconcile its containers/volumes and follow [the logical transition guide](postgres/README.md).
The startup guard below refuses a known legacy volume/container switch before
Compose can recreate PostgreSQL. It does not migrate or inspect database records.
For a genuinely fresh installation or an already verified new stack, from the
project root with a private `backend/.env`, stop on the first failure. Everyday
development uses the wrapper above; these base-image commands are for image/runtime
acceptance in a reconciled project:

```bash
docker compose --env-file backend/.env config --quiet &&
python3 deploy/checks/check_volume_transition.py &&
docker compose --env-file backend/.env build api postgres &&
docker compose --env-file backend/.env up -d --wait postgres redis &&
docker compose --env-file backend/.env run --rm --no-deps api python manage.py migrate --noinput &&
docker compose --env-file backend/.env up -d --no-build --wait
```

The API build supplies all six backend services; PostgreSQL has a separate small
nonroot image. Migrations are explicit and
must finish before starting application processes; workers/Beat/API never run
migrations on startup. Static files are collected during image build using
ephemeral build-only settings with no database connection. No runtime customer
uploads are included or served by WhiteNoise.

Then verify:

```bash
docker compose --env-file backend/.env ps
curl --fail http://127.0.0.1:18000/api/health/
docker compose --env-file backend/.env exec api python manage.py check
docker compose --env-file backend/.env exec api python manage.py migrate --check
docker compose --env-file backend/.env exec api python -c "import os; from redis import Redis; assert Redis.from_url(os.environ['CELERY_BROKER_URL'], socket_timeout=5, socket_connect_timeout=5).ping()"
docker compose --env-file backend/.env exec worker-default celery -A config inspect ping --timeout=5
backend/.venv/bin/python deploy/checks/compose_smoke.py
```

Check all four worker replies and exactly one Beat process. Visit `/admin/login/`
and inspect its static assets through the proxy. For a local staff account use
`./backend-dev.sh manage createsuperuser` interactively in the development stack.

```bash
docker compose --env-file backend/.env stop
docker compose --env-file backend/.env start
# To remove containers/network while keeping named data volumes:
docker compose --env-file backend/.env down
```

Ordinary stop/start/down must preserve named volumes. Do not add `--volumes` or
prune volumes during ordinary recovery. Changing `POSTGRES_PASSWORD` in `backend/.env`
does not rotate an already-initialized PostgreSQL role; use an explicit database
rotation procedure. After changing code, rebuild `api` and recreate backend
containers against the updated shared image. Reconcile interrupted migrations
with `showmigrations` before retrying.

The D056 acceptance run verified both builds, UID10001/read-only API runtime,
UID70 PostgreSQL, locked dependencies without runtime installer tooling, health,
private networking/worker queues, atomic logical restore and ordinary restart
persistence. The unchanged security gate passed. Synthetic users/markers were
removed, verification containers/networks cleaned up, and original development
IDs/images/start times checked unchanged. Remediation volumes remain for resume.

Historical verification environments below are evidence only; new local/production
environments use `backend/.env` / `backend/.env.prod`, and isolated checks use
`backend/.env.ci` or `backend/.env.check-TASK`. Do not replay legacy setup commands.

On this host, `/tmp/opencode/organicseoops-p01-04.env` belongs to the running legacy
development stack: **do not use the new startup recipe with it before migration**.
The prepared-image verification environment is instead
`/tmp/opencode/organicseoops-p01-05-remediation/remediation.env`, project
`organicseoops-remediation`, port18080. Its temporary Compose image override and
separate tags preserved the active developer image tag during checks. Reconcile
those files and volumes before resuming; pass the same env file to the startup
guard, Compose, runtime smoke and security scripts. Never regenerate a lost
password against a retained DB and assume it rotated. Temporary files can
disappear on reboot while Docker volumes persist.

`compose_smoke.py` is read-only apart from normal health/inspection traffic. It
verifies all ten running services, private DB/Redis attachment, one shared
nonroot backend image, four live queue bindings, writable singleton Beat and
proxy health/admin/static/404. It accepts development `max-age=0` caching when
DEBUG is on; DEBUG=False immutable caching is covered by the backend test and
local Gunicorn smoke. Its Redis version assertion now checks D086's selected
8.10.2 release. The unchanged vulnerability gate passed locally on current
images; hosted CI, actual legacy transition and production deployment remain
separate unfinished work.

## Non-Docker checks available now

From the project root:

```bash
/usr/bin/python3 deploy/checks/test_topology.py
```

This historical local command used system PyYAML 6.0.1; CI now pins PyYAML 6.0.3
in an isolated check-only virtualenv using `checks/requirements.txt`. It checks
source-level service separation, private ports/networks, volume definitions, one
scheduler and secret-free build inputs. It does not interpolate Compose variables,
validate Dockerfile execution or invoke Docker. See the
[CI/security guide](checks/README.md) for reproducible check setup and current
security findings. Neither parser is an application dependency.

The backend guide documents the 10-test Django suite, Celery memory-transport
checks, `collectstatic` and `checks/runtime_smoke.py`. The smoke runner starts and
stops a local Gunicorn process on an ephemeral loopback socket, checking actual
HTTP health/admin/static/404 with DEBUG disabled. A trusted loopback forwarded
HTTPS header exercises secure-request handling; this does not test TLS or nginx.
Memory transport checks verify routing/serialization, not real workers or Redis
delivery/reliability. Business tasks, durable jobs and budgets arrive in Phase 4.
