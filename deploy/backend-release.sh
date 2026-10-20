#!/usr/bin/env bash
set -euo pipefail

role=${1:-}
mode=${2:-release}
[[ "$mode" == release || "$mode" == rollback ]] || { printf 'Mode must be release or rollback\n' >&2; exit 2; }
case "$role" in
  app) overlay=deploy/compose.production-app.yaml ;;
  feedback) overlay=deploy/compose.feedback-worker.yaml ;;
  *) printf 'Usage: BACKEND_IMAGE=<ECR digest> ENV_FILE=<private env file> %s app|feedback\n' "$0" >&2; exit 2 ;;
esac

: "${BACKEND_IMAGE:?Set the reviewed ECR image digest}"
: "${ENV_FILE:?Set the host-specific private env file}"
[[ "$BACKEND_IMAGE" =~ ^[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/[a-z0-9_/-]+@sha256:[a-f0-9]{64}$ ]] || {
  printf 'BACKEND_IMAGE must be an ECR image pinned by sha256 digest\n' >&2; exit 2;
}
[[ -f "$ENV_FILE" ]] || { printf 'Selected private env file is missing\n' >&2; exit 2; }

files=(--env-file "$ENV_FILE" -f compose.yaml)
if [[ "$role" == app ]]; then
  [[ "${BACKUP_VERIFIED:-}" == 1 && "${ORIGIN_DRAINED:-}" == 1 ]] || {
    printf 'Verify recoverable backup and drain the ALB origin before migration\n' >&2; exit 2;
  }
  if [[ "$mode" == rollback && "${SCHEMA_COMPATIBLE:-}" != 1 ]]; then
    printf 'Rollback requires verified compatibility with the current database schema\n' >&2; exit 2
  fi
  : "${RENDERER_IMAGE:?Set the reviewed renderer ECR image digest}"
  : "${POSTGRES_IMAGE:?Set the reviewed PostgreSQL ECR image digest}"
  : "${PROXY_IMAGE:?Set the reviewed proxy ECR image digest}"
  [[ "$RENDERER_IMAGE" =~ ^[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/[a-z0-9_/-]+@sha256:[a-f0-9]{64}$ ]] || {
    printf 'RENDERER_IMAGE must be an ECR image pinned by sha256 digest\n' >&2; exit 2;
  }
  [[ "$POSTGRES_IMAGE" =~ ^[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/[a-z0-9_/-]+@sha256:[a-f0-9]{64}$ ]] || {
    printf 'POSTGRES_IMAGE must be an ECR image pinned by sha256 digest\n' >&2; exit 2;
  }
  [[ "$PROXY_IMAGE" =~ ^[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/[a-z0-9_/-]+@sha256:[a-f0-9]{64}$ ]] || {
    printf 'PROXY_IMAGE must be an ECR image pinned by sha256 digest\n' >&2; exit 2;
  }
  export PRIVATE_POSTGRES_EBS_MOUNT="${PRIVATE_POSTGRES_EBS_MOUNT:-/mnt/organicseoops}"
  export PRIVATE_POSTGRES_DATA_DIR="${PRIVATE_POSTGRES_DATA_DIR:-$PRIVATE_POSTGRES_EBS_MOUNT/postgres}"
  [[ -d "$PRIVATE_POSTGRES_DATA_DIR" ]] &&
    mountpoint -q -- "$PRIVATE_POSTGRES_EBS_MOUNT" &&
    [[ "$(realpath -e -- "$PRIVATE_POSTGRES_DATA_DIR")" == "$(realpath -e -- "$PRIVATE_POSTGRES_EBS_MOUNT")"/* ]] &&
    [[ "$(stat -c %u -- "$PRIVATE_POSTGRES_DATA_DIR")" == 70 ]] || {
    printf 'PostgreSQL data directory must be UID70 on the retained EBS mount\n' >&2; exit 2;
  }
  files+=(-f deploy/compose.production-private.yaml)
fi
files+=(-f "$overlay" -f deploy/compose.release.yaml)

docker compose "${files[@]}" config --quiet
if [[ "$role" == feedback ]]; then
  docker compose "${files[@]}" pull worker-default
  docker compose "${files[@]}" up -d --no-deps --no-build --wait --wait-timeout 180 worker-default
else
  if [[ "$mode" == release ]]; then
    docker compose "${files[@]}" pull postgres
  fi
  docker compose "${files[@]}" pull api worker-ai worker-crawl worker-audit beat renderer proxy
  if [[ "$mode" == release ]]; then
    docker compose "${files[@]}" run --rm --no-deps api python manage.py migrate --noinput
  fi
  if [[ "$mode" == rollback ]]; then
    docker compose "${files[@]}" up -d --no-deps --no-build --wait --wait-timeout 180 api proxy worker-ai worker-crawl worker-audit beat renderer
  else
    docker compose "${files[@]}" up -d --no-build --wait --wait-timeout 180 postgres redis api proxy worker-ai worker-crawl worker-audit beat renderer
  fi
fi
