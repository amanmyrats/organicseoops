# PostgreSQL image transition (D056)

The new image retains PostgreSQL 18.6, uses the pinned official Alpine3.24 base,
and starts directly as UID/GID70. The unnecessary gosu root-switch binary is
removed. New databases use UTF8 and PostgreSQL's builtin `C.UTF-8` locale provider.
This avoids inheriting the old Debian/gosu package findings; it does not change
the application schema or select a customer language.

**Existing Bookworm installations need a logical migration before upgrading.**
The user selected prepare-and-verify-only: the currently running development
stack and its database have not been stopped, exported, migrated or replaced.
Do not run the new fresh-install startup recipe against that installation until
its transition is authorized and prepared.

## Volume boundary

- Legacy physical volume: typically `organicseoops_postgres-data`, owned by the
  Bookworm image's postgres user and initialized with the libc locale provider.
- New physical volume: `${COMPOSE_PROJECT_NAME}_postgres-alpine-data`, owned by
  UID70 and initialized with the builtin locale provider.
- The Compose logical key remains `postgres-data`, but its explicit volume name
  is new. The old volume is not renamed, deleted, chowned or mounted in the new
  PostgreSQL image. A fresh volume alone does **not** migrate existing records.

Do not physically copy PGDATA, change its owner to force reuse, or merely refresh
the collation-version metadata. A logical restore rebuilds indexes under the
target provider. Collation-dependent ordering/uniqueness must be checked with
representative data; custom collations/extensions/roles need their own review.

## Prepare-only upgrade procedure

These are operator steps for a **later authorized migration**, not actions already
performed on the user's database. Keep backups private and outside the repository.

1. Inventory the old container/image ID, volume, database/owner, extensions and
   private environment. Record how to start the old stack for rollback. Keep its
   image and volume available; do not prune them.
2. Build the new API/PostgreSQL images. Prepare a **separate project/environment**
   for the target, with a different loopback proxy port and a new volume. Preserve
   required application secrets (including Django's signing key if preserving
   existing sessions); never print them. Do not start target API/workers/Beat yet.
3. After approval of a downtime window, stop source application writers (proxy,
   API, workers and Beat) while leaving old PostgreSQL available for the dump.
   Confirm no remaining application/manual process is writing.
4. Create a private, uniquely named custom-format dump using native `pg_dump`.
   Example shape, substituting reviewed identifiers and a new private file:

   ```sh
   umask 077
   docker exec OLD_POSTGRES pg_dump -Fc --no-owner --no-privileges \
     -U DATABASE_OWNER -d DATABASE_NAME > PRIVATE_BACKUP_FILE
   ```

   Check exit status, retain the checksum and inspect the archive table of
   contents with `pg_restore --list`. The scaffold has one application owner;
   deployments with additional roles/grants/tablespaces require separately
   captured and reviewed metadata, not an assumption that `--no-privileges`
   preserves their authorization model.
5. Start only target PostgreSQL/Redis. Verify the target project/volume, UID70,
   `datlocprovider='b'`, `datlocale='C.UTF-8'`, UTF8 encoding and an empty target
   application schema. Never overwrite a populated target without a separately
   reviewed recovery operation.
6. Restore the archive into the newly created database. Do not use `--create`
   from the old archive: that could recreate the old locale/provider settings.

   ```sh
   docker compose --env-file TARGET_ENV exec -T postgres \
     pg_restore --single-transaction --exit-on-error --no-owner --no-privileges \
     -U DATABASE_OWNER -d DATABASE_NAME < PRIVATE_BACKUP_FILE
   ```

7. Compare source/target records, permissions/relationships, migrations,
   sequences and representative Unicode values. Check normalized email
   uniqueness and any collation-dependent behavior. Run Django system/migration
   checks and tests before allowing writes. Apply reviewed application migrations
   if a future code revision requires them; this same-version rehearsal did not.
8. Start only the target application stack and verify admin/session recovery,
   worker queue bindings, health, static files and the security gate. Rehearse
   stop/start persistence. Cut over the intended loopback endpoint only after
   validation. Retain the old volume/image and private backup for an explicit
   rollback/retention decision.

Rollback before target writes can resume the old stack. Once target writes begin,
restoring the old snapshot alone would lose those changes; reconcile them under a
reviewed rollback plan rather than blindly switching volumes.

## Reproducible synthetic rehearsal

`deploy/checks/restore_smoke.py` uses native `pg_dump`/`pg_restore` and creates its
own temporary Bookworm source with synthetic data. It accepts only disposable
`organicseoops-ci`, `organicseoops-remediation` or `organicseoops-ci-atomic` target projects and refuses a
populated target schema. It never opens or exports the development database.

After creating an isolated check env and starting only its fresh target DB/Redis:

```sh
python3 deploy/checks/restore_smoke.py --env-file CHECK_ENV
```

It applies the actual Django migrations to its synthetic source, creates Unicode
users/group/permission fixtures, compares serialized data hashes after logical
restore, and verifies migration records, sequence allocation and normalized-email
uniqueness. It first forces a late index-creation error and verifies that the
single-transaction restore leaves no partial application objects, then retries
successfully. Its source container/UUID volume are removed; two inactive synthetic
users remain on the isolated target for persistence checks. Re-running against
that populated target intentionally fails instead of overwriting data.

The source uses the recorded old Bookworm image solely as an isolated compatibility
fixture, not as a remediated runtime. The full application security gate scans the
new stack. This local fixture exercise is not a production backup/RPO/RTO drill;
those remain P13-04 work.
