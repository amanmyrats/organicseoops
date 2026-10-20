#!/usr/bin/env bash
# App-host-only daily retention pass; Django owns tenant gates and retry state.
set -euo pipefail
mountpoint -q /mnt/organicseoops || { printf 'Retained app mount unavailable\n' >&2; exit 1; }
api="$(docker ps -q --filter label=com.docker.compose.project=organicseoops-prod \
  --filter label=com.docker.compose.service=api)"
[[ "$api" =~ ^[a-f0-9]{12,64}$ ]] || { printf 'Exactly one app API required\n' >&2; exit 1; }
[[ "$(docker inspect --format '{{.State.Health.Status}}' "$api")" == healthy ]] || {
  printf 'App API unhealthy\n' >&2; exit 1;
}
docker exec "$api" python manage.py process_customer_deletions --execute --limit 10
