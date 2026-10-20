#!/usr/bin/env bash
# Exact-Compose-project liveness; only non-customer operational metrics leave host.
set -euo pipefail
role=${1:-}
case "$role" in
  app) services=(api proxy worker-ai worker-crawl worker-audit beat renderer postgres redis); disk_path=/mnt/organicseoops ;;
  feedback) services=(worker-default); disk_path=/ ;;
  *) printf 'Usage: %s app|feedback\n' "$0" >&2; exit 2 ;;
esac
: "${AWS_REGION:?Select the AWS region}"
healthy=1
disk_ready=1
api_container=""
if [[ "$role" == app ]] && ! mountpoint -q "$disk_path"; then healthy=0; disk_ready=0; fi
for service in "${services[@]}"; do
  container="$(docker ps -q --filter label=com.docker.compose.project=organicseoops-prod \
    --filter "label=com.docker.compose.service=$service")"
  if [[ ! "$container" =~ ^[a-f0-9]{12,64}$ ]]; then healthy=0; break; fi
  if [[ "$service" == api ]]; then api_container=$container; fi
  health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container")"
  if [[ "$health" != healthy && !( "$service" == beat && "$health" == none ) ]]; then
    healthy=0
    break
  fi
done
disk_used=100
if [[ "$disk_ready" == 1 ]]; then
  disk_used="$(df --output=pcent "$disk_path")"
  disk_used="${disk_used##*$'\n'}"
  disk_used="${disk_used//[!0-9]/}"
fi
[[ "$disk_used" =~ ^[0-9]{1,3}$ ]] || exit 2
total=0 available=0
while read -r name value _; do
  case "$name" in
    MemTotal:) total=$value ;;
    MemAvailable:) available=$value ;;
  esac
done < /proc/meminfo
(( total > 0 && available <= total )) || exit 2
memory_used=$((100 * (total - available) / total))
overdue=0
if [[ "$role" == app && "$healthy" == 1 ]]; then
  overdue="$(docker exec "$api_container" python manage.py shell -c 'from datetime import timedelta; from django.utils import timezone; from jobs.models import JobSchedule; print(JobSchedule.objects.filter(handler="sync_search_console", enabled=True, next_run_at__lt=timezone.now()-timedelta(hours=2)).count())')"
  [[ "$overdue" =~ ^[0-9]{1,8}$ ]] || exit 2
fi
aws cloudwatch put-metric-data --region "$AWS_REGION" --namespace OrganicSEOOps/Service \
  --metric-data "[{\"MetricName\":\"Healthy\",\"Dimensions\":[{\"Name\":\"HostRole\",\"Value\":\"$role\"}],\"Value\":$healthy,\"Unit\":\"Count\"},{\"MetricName\":\"DiskUsedPercent\",\"Dimensions\":[{\"Name\":\"HostRole\",\"Value\":\"$role\"}],\"Value\":$disk_used,\"Unit\":\"Percent\"},{\"MetricName\":\"MemUsedPercent\",\"Dimensions\":[{\"Name\":\"HostRole\",\"Value\":\"$role\"}],\"Value\":$memory_used,\"Unit\":\"Percent\"}]" >/dev/null
if [[ "$role" == app && "$healthy" == 1 ]]; then
  aws cloudwatch put-metric-data --region "$AWS_REGION" --namespace OrganicSEOOps/Service \
    --metric-data "[{\"MetricName\":\"OverdueSearchConsoleSchedules\",\"Dimensions\":[{\"Name\":\"HostRole\",\"Value\":\"app\"}],\"Value\":$overdue,\"Unit\":\"Count\"}]" >/dev/null
  docker exec "$api_container" python manage.py publish_ops_metrics
fi
[[ "$healthy" == 1 ]]
