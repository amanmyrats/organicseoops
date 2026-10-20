#!/usr/bin/env bash
# Local backend commands (run from the project root):
# ./backend-dev.sh setup                         # first run: build, migrate, start
# ./backend-dev.sh                               # start/reuse full stack (same as up)
# ./backend-dev.sh up                            # start/reuse full stack
# ./backend-dev.sh infrastructure                # DB/Redis only, for host Django
# ./backend-dev.sh down                          # stop stack, keep data volumes
# ./backend-dev.sh down && ./backend-dev.sh up   # restart full stack
# ./backend-dev.sh status                        # container status
# ./backend-dev.sh logs                          # follow API logs
# ./backend-dev.sh logs worker-default           # follow a worker's logs
# ./backend-dev.sh manage check                  # run a Django command
# ./backend-dev.sh quickmanage check             # read-only command in running API
# ./backend-dev.sh manage test accounts.test_api --noinput  # focused tests
# ./backend-dev.sh quicktest accounts.test_api   # focused tests, reuse API/test DB
# ./backend-dev.sh test                          # full backend checks/tests
# ./backend-dev.sh makemigrations tenancy        # generate app migration
# ./backend-dev.sh migrate                       # apply migrations
# ./backend-dev.sh restart-workers               # reload Celery workers and Beat
# ./backend-dev.sh rebuild                       # rebuild image after dependency changes
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project=organicseoops-dev
proxy_port=18000
env_file="$root/backend/.env"
backend_services=(api proxy worker-default worker-ai worker-crawl worker-audit beat renderer)
worker_services=(worker-default worker-ai worker-crawl worker-audit beat renderer)

compose() {
  env \
    -u CRUX_ALERT_DELIVERY_ENABLED -u ALERT_DIGEST_DELIVERY_ENABLED -u WEEKLY_SUMMARY_DELIVERY_ENABLED -u PUBLIC_ANALYTICS_ENABLED -u PUBLIC_ANALYTICS_POLICY_FILE -u PUBLIC_ANALYTICS_POLICY_SHA256 -u PUBLIC_CONTACT_ENABLED -u PUBLIC_CONTACT_RETENTION_DAYS \
    -u COMPOSE_FILE -u COMPOSE_PROJECT_NAME -u PROXY_PORT \
    -u SELF_SERVICE_CLOSURE_ENABLED -u SELF_SERVICE_ACCOUNT_CLOSURE_ENABLED \
    -u CUSTOMER_EXPORT_COPY_POLICY_REFERENCE -u CUSTOMER_EXPORT_COPY_LIFETIME_DAYS \
    -u PERSONAL_IDENTITY_ERASURE_POLICY_REFERENCE -u PERSONAL_IDENTITY_TRIAL_RETENTION_DAYS -u PERSONAL_IDENTITY_RETENTION_KEY \
    -u DJANGO_SECRET_KEY -u DJANGO_DEBUG -u DJANGO_ALLOWED_HOSTS \
    -u DJANGO_CSRF_TRUSTED_ORIGINS -u FRONTEND_ORIGIN -u MFA_ENCRYPTION_KEYS -u PROVIDER_ENCRYPTION_KEYS -u PERFORMANCE_ENCRYPTION_KEYS -u PADDLE_ENCRYPTION_KEYS -u PADDLE_ENVIRONMENT -u PADDLE_CHECKOUT_URL -u OPENAI_API_KEY -u OPENAI_COMPATIBLE_API_KEY -u GOOGLE_OAUTH_CLIENT_ID -u GOOGLE_OAUTH_CLIENT_SECRET -u GOOGLE_OAUTH_REDIRECT_URI -u GOOGLE_OAUTH_ENCRYPTION_KEYS -u GOOGLE_ANALYTICS_REDIRECT_URI -u GOOGLE_ANALYTICS_ENCRYPTION_KEYS -u GOOGLE_PERFORMANCE_API_KEY -u EMAIL_BACKEND -u DJANGO_CACHE_URL \
    -u EMAIL_HOST -u EMAIL_PORT -u EMAIL_HOST_USER -u EMAIL_HOST_PASSWORD -u DEFAULT_FROM_EMAIL -u SES_FEEDBACK_QUEUE_URL -u SES_FEEDBACK_TOPIC_ARN \
    -u FEEDBACK_WORKER_HOST -u POSTGRES_SSLMODE -u POSTGRES_SSLROOTCERT -u REDIS_TLS_CA_FILE \
    -u POSTGRES_DB -u POSTGRES_USER -u POSTGRES_PASSWORD -u POSTGRES_HOST -u POSTGRES_PORT \
    -u CELERY_BROKER_URL -u LOG_LEVEL -u ARTIFACT_STORAGE_BACKEND \
    -u ARTIFACT_MAX_BYTES -u ARTIFACT_ALLOWED_CONTENT_TYPES \
    -u ARTIFACT_S3_BUCKET -u ARTIFACT_S3_PREFIX -u AWS_REGION \
    COMPOSE_PROJECT_NAME="$project" \
    PROXY_PORT="$proxy_port" \
    docker compose --project-name "$project" --env-file "$env_file" \
      -f "$root/compose.yaml" -f "$root/compose.development.yaml" "$@"
}

existing_state() {
  docker ps --all --quiet --filter "label=com.docker.compose.project=$project"
  docker volume ls --quiet --filter "label=com.docker.compose.project=$project"
  docker volume ls --quiet --filter "name=^${project}_"
}

ensure_env() {
  if [[ -f "$env_file" ]]; then
    return
  fi
  if [[ -n "$(existing_state)" ]]; then
    printf 'Development state exists but %s is missing; restore its credentials instead of regenerating them.\n' "$env_file" >&2
    exit 1
  fi
  python3 "$root/deploy/checks/create_check_env.py" "$env_file" \
    --project-name "$project" --proxy-port "$proxy_port" --profile development
}

require_env() {
  if [[ ! -f "$env_file" ]]; then
    printf 'Missing %s; run ./backend-dev.sh setup first.\n' "$env_file" >&2
    exit 1
  fi
}

preflight() {
  compose config --quiet
  env \
    -u CRUX_ALERT_DELIVERY_ENABLED -u ALERT_DIGEST_DELIVERY_ENABLED -u WEEKLY_SUMMARY_DELIVERY_ENABLED -u PUBLIC_ANALYTICS_ENABLED -u PUBLIC_ANALYTICS_POLICY_FILE -u PUBLIC_ANALYTICS_POLICY_SHA256 -u PUBLIC_CONTACT_ENABLED -u PUBLIC_CONTACT_RETENTION_DAYS \
    -u COMPOSE_FILE -u COMPOSE_PROJECT_NAME -u PROXY_PORT \
    -u SELF_SERVICE_CLOSURE_ENABLED -u SELF_SERVICE_ACCOUNT_CLOSURE_ENABLED \
    -u CUSTOMER_EXPORT_COPY_POLICY_REFERENCE -u CUSTOMER_EXPORT_COPY_LIFETIME_DAYS \
    -u PERSONAL_IDENTITY_ERASURE_POLICY_REFERENCE -u PERSONAL_IDENTITY_TRIAL_RETENTION_DAYS -u PERSONAL_IDENTITY_RETENTION_KEY \
    -u DJANGO_SECRET_KEY -u DJANGO_DEBUG -u DJANGO_ALLOWED_HOSTS \
    -u DJANGO_CSRF_TRUSTED_ORIGINS -u FRONTEND_ORIGIN -u MFA_ENCRYPTION_KEYS -u PROVIDER_ENCRYPTION_KEYS -u PERFORMANCE_ENCRYPTION_KEYS -u PADDLE_ENCRYPTION_KEYS -u PADDLE_ENVIRONMENT -u PADDLE_CHECKOUT_URL -u OPENAI_API_KEY -u OPENAI_COMPATIBLE_API_KEY -u GOOGLE_OAUTH_CLIENT_ID -u GOOGLE_OAUTH_CLIENT_SECRET -u GOOGLE_OAUTH_REDIRECT_URI -u GOOGLE_OAUTH_ENCRYPTION_KEYS -u GOOGLE_ANALYTICS_REDIRECT_URI -u GOOGLE_ANALYTICS_ENCRYPTION_KEYS -u GOOGLE_PERFORMANCE_API_KEY -u EMAIL_BACKEND -u DJANGO_CACHE_URL \
    -u EMAIL_HOST -u EMAIL_PORT -u EMAIL_HOST_USER -u EMAIL_HOST_PASSWORD -u DEFAULT_FROM_EMAIL -u SES_FEEDBACK_QUEUE_URL -u SES_FEEDBACK_TOPIC_ARN \
    -u FEEDBACK_WORKER_HOST -u POSTGRES_SSLMODE -u POSTGRES_SSLROOTCERT -u REDIS_TLS_CA_FILE \
    -u POSTGRES_DB -u POSTGRES_USER -u POSTGRES_PASSWORD -u POSTGRES_HOST -u POSTGRES_PORT \
    -u CELERY_BROKER_URL -u LOG_LEVEL -u ARTIFACT_STORAGE_BACKEND \
    -u ARTIFACT_MAX_BYTES -u ARTIFACT_ALLOWED_CONTENT_TYPES \
    -u ARTIFACT_S3_BUCKET -u ARTIFACT_S3_PREFIX -u AWS_REGION \
    COMPOSE_PROJECT_NAME="$project" PROXY_PORT="$proxy_port" \
    python3 "$root/deploy/checks/check_volume_transition.py" \
      --project-name "$project" --env-file "$env_file" \
      --compose-file "$root/compose.yaml" --compose-file "$root/compose.development.yaml"
}

start_infrastructure() {
  compose up -d --no-build --wait --wait-timeout 180 postgres redis
}

check_beat() {
  compose exec -T beat python -c \
    "import os, pathlib; os.kill(int(pathlib.Path('/tmp/celerybeat.pid').read_text().strip()), 0)"
}

require_running_api() {
  if [[ -z "$(compose ps --quiet api)" ]]; then
    printf 'Development API is not running; inspect ./backend-dev.sh status and service logs before starting or restarting it.\n' >&2
    exit 1
  fi
}

has_argument() {
  local expected="$1"
  shift
  local argument
  for argument in "$@"; do
    if [[ "$argument" == "$expected" ]]; then
      return 0
    fi
  done
  return 1
}

lock_test_database() {
  local lock_file="/tmp/organicseoops-${UID}-dev-test.lock"
  exec 9>>"$lock_file"
  if ! flock --nonblock 9; then
    printf 'Another backend test is using the shared test database; wait for it to finish instead of retrying in a loop.\n' >&2
    exit 1
  fi
}

case "${1:-up}" in
  infrastructure)
    require_env
    preflight
    start_infrastructure
    ;;
  setup)
    ensure_env
    if [[ ! -e "$root/backend/.env.prod" ]]; then
      python3 "$root/deploy/checks/create_check_env.py" "$root/backend/.env.prod" --profile production
    fi
    preflight
    compose build api postgres renderer proxy
    start_infrastructure
    compose run --rm --no-deps api python manage.py migrate --noinput
    compose up -d --no-build --wait --wait-timeout 180
    ;;
  up)
    require_env
    preflight
    compose up -d --no-build --wait --wait-timeout 180
    ;;
  down)
    require_env
    compose down
    ;;
  status)
    require_env
    compose ps
    ;;
  logs)
    require_env
    shift
    if (($# == 0)); then
      set -- api
    fi
    compose logs --follow "$@"
    ;;
  migrate)
    require_env
    preflight
    start_infrastructure
    compose run --rm --no-deps api python manage.py migrate --noinput
    ;;
  makemigrations)
    require_env
    preflight
    app="${2:-}"
    if [[ ! "$app" =~ ^[a-z][a-z0-9_]*$ || ! -d "$root/backend/$app" ]]; then
      printf 'Usage: %s makemigrations APP [OPTIONS...]\n' "$0" >&2
      exit 2
    fi
    shift 2
    start_infrastructure
    compose run --rm --no-deps --user "$(id -u):$(id -g)" \
      --volume "$root/backend/$app/migrations:/app/$app/migrations:rw" \
       api python manage.py makemigrations "$app" "$@"
    ;;
  quickmanage)
    require_env
    shift
    management_command="${1:-}"
    case "$management_command" in
      check|showmigrations)
        ;;
      makemigrations)
        if ! has_argument --check "$@" || ! has_argument --dry-run "$@"; then
          printf 'quickmanage makemigrations requires both --check and --dry-run.\n' >&2
          exit 2
        fi
        ;;
      migrate)
        if ! has_argument --check "$@"; then
          printf 'quickmanage migrate requires --check.\n' >&2
          exit 2
        fi
        ;;
      *)
        printf 'Usage: %s quickmanage {check|showmigrations [APP...]|makemigrations [APP...] --check --dry-run|migrate --check} [OPTIONS...]\n' "$0" >&2
        exit 2
        ;;
    esac
    require_running_api
    compose exec -T api python manage.py "$@"
    ;;
  quicktest)
    require_env
    shift
    if (($# == 0)) || [[ "$1" == -* ]]; then
      printf 'Usage: %s quicktest TEST_LABEL [TEST_LABEL...|OPTIONS...]\n' "$0" >&2
      exit 2
    fi
    require_running_api
    lock_test_database
    compose exec -T api python manage.py test "$@" --keepdb --noinput
    ;;
  test)
    require_env
    lock_test_database
    preflight
    start_infrastructure
    compose run --rm --no-deps api python manage.py check
    compose run --rm --no-deps api python manage.py makemigrations --check --dry-run
    compose run --rm --no-deps api python manage.py migrate --check
    compose run --rm --no-deps api python manage.py test accounts config tenancy jobs providers integrations --noinput
    ;;
  manage)
    require_env
    shift
    if [[ "${1:-}" == test ]]; then
      lock_test_database
    fi
    start_infrastructure
    compose run --rm --no-deps api python manage.py "$@"
    ;;
  restart-workers)
    require_env
    preflight
    compose up -d --no-build --no-deps --force-recreate --wait --wait-timeout 180 "${worker_services[@]}"
    check_beat
    ;;
  rebuild)
    require_env
    preflight
    compose build api renderer proxy
    compose up -d --no-build --no-deps --force-recreate --wait --wait-timeout 180 "${backend_services[@]}"
    check_beat
    ;;
  *)
    printf 'Usage: %s {setup|infrastructure|up|down|status|logs [SERVICE...]|migrate|makemigrations APP [OPTIONS...]|quickmanage COMMAND...|quicktest TEST_LABEL...|test|manage COMMAND...|restart-workers|rebuild}\n' "$0" >&2
    exit 2
    ;;
esac

if [[ "${1:-up}" == setup || "${1:-up}" == up ]]; then
  printf '\nBackend: http://127.0.0.1:%s/api/health/\n' "$proxy_port"
fi
