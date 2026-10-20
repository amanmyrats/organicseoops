#!/usr/bin/env bash
# App-host-only daily logical backup. No customer identifiers enter keys or metrics.
set -euo pipefail
umask 077

: "${BACKUP_BUCKET:?Select the private backup bucket}"
: "${AWS_REGION:?Select the bucket region}"
[[ "$BACKUP_BUCKET" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]] || exit 2
staging="${BACKUP_STAGING_DIR:-/mnt/organicseoops/backup-staging}"
mount="${BACKUP_EBS_MOUNT:-/mnt/organicseoops}"
[[ -d "$staging" ]] && mountpoint -q "$mount" &&
  [[ "$(realpath -e -- "$staging")" == "$(realpath -e -- "$mount")"/* ]] || {
  printf 'Backup staging must be on the retained EBS mount\n' >&2; exit 2;
}
exec 9>"$staging/.backup.lock"
flock -n 9 || { printf 'Backup is already running\n' >&2; exit 2; }
dump=""
metric() {
  aws cloudwatch put-metric-data --region "$AWS_REGION" --namespace OrganicSEOOps/Backup \
    --metric-data "[{\"MetricName\":\"DailySuccess\",\"Dimensions\":[{\"Name\":\"Environment\",\"Value\":\"production\"}],\"Value\":$1,\"Unit\":\"Count\"}]" >/dev/null
}
finish() {
  status=$?
  if (( status != 0 )); then metric 0 || true; fi
  if [[ -n "$dump" ]]; then rm -f -- "$dump"; fi
  exit "$status"
}
trap finish EXIT
leftovers=("$staging"/backup.*.pgcustom)
if [[ -e "${leftovers[0]}" || -L "${leftovers[0]}" ]]; then
  printf 'Unresolved private dump needs operator reconciliation before retry\n' >&2; exit 2
fi

containers="$(docker ps -q --filter label=com.docker.compose.project=organicseoops-prod \
  --filter label=com.docker.compose.service=postgres)"
[[ "$containers" =~ ^[a-f0-9]{12,64}$ ]] || { printf 'Expected exactly one production PostgreSQL container\n' >&2; exit 2; }
[[ "$(docker inspect --format '{{.State.Health.Status}}' "$containers")" == healthy ]] || exit 2
database_bytes="$(docker exec "$containers" sh -ec 'PGPASSWORD="$POSTGRES_PASSWORD" PGSSLMODE=require exec psql -h postgres -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT pg_database_size(current_database())"')"
available="$(df --output=avail -B1 "$staging")"
available="${available##*$'\n'}"
available="${available//[!0-9]/}"
[[ "$database_bytes" =~ ^[0-9]+$ && "$available" =~ ^[0-9]+$ ]] &&
  (( available > database_bytes + 1073741824 )) || {
  printf 'Insufficient retained EBS space for a private backup\n' >&2; exit 2;
}

dump="$(mktemp "$staging/backup.XXXXXXXX.pgcustom")"
docker exec "$containers" sh -ec 'PGPASSWORD="$POSTGRES_PASSWORD" PGSSLMODE=require exec pg_dump -h postgres -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner --no-privileges' > "$dump"
[[ -s "$dump" ]] || exit 2
docker exec -i "$containers" pg_restore --list < "$dump" >/dev/null
key="backups/$(date -u +%F).pgcustom"
aws s3api put-object --region "$AWS_REGION" --bucket "$BACKUP_BUCKET" --key "$key" \
  --body "$dump" --server-side-encryption AES256 --checksum-algorithm SHA256 \
  --if-none-match '*' >/dev/null
metric 1
