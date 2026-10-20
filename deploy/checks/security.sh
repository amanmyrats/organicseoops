#!/usr/bin/env bash
# Run from repository root after the stack is started, with its private env path.
set -euo pipefail

env_file="${1:-backend/.env}"
trivy='aquasec/trivy:0.74.0@sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969'
cache=(--mount 'type=volume,src=organicseoops-trivy-cache,dst=/root/.cache/trivy')
flags=(--scanners vuln --severity 'HIGH,CRITICAL' --exit-code 1 --no-progress --timeout 5m)
archive_dir="$(mktemp -d)"
trap 'rm -rf -- "$archive_dir"' EXIT
status=0

# Only the public dependency manifest is mounted, not credentials or customer data.
docker run --rm "${cache[@]}" \
  --mount "type=bind,src=${PWD}/backend/requirements.txt,dst=/scan/requirements.txt,readonly" \
  "$trivy" fs "${flags[@]}" /scan || status=1

# Scan the actual running image IDs, not mutable tags or a newly retagged image.
# Export archives so the scanner never receives the privileged Docker socket.
# Keep all scan reports even when an earlier vulnerability scan fails.
for service in api postgres redis proxy renderer; do
  container="$(docker compose --env-file "$env_file" ps -q "$service")"
  image="$(docker inspect --format '{{.Image}}' "$container")"
  printf 'Scanning %s image %s\n' "$service" "$image"
  docker image save --output "$archive_dir/image.tar" "$image"
  renderer_flags=()
  if [[ "$service" == renderer ]]; then
    docker exec "$container" python3 -c 'import importlib.metadata as m; m.version("playwright"); assert all(not any(d.metadata.get("Name", "").lower() == n for d in m.distributions()) for n in ("msgpack", "setuptools"))'
    renderer_flags=(--ignorefile /check/trivy-rendererignore)
  fi
  docker run --rm "${cache[@]}" \
    --mount "type=bind,src=${archive_dir},dst=/images,readonly" \
    --mount "type=bind,src=${PWD}/deploy/checks/trivy-rendererignore,dst=/check/trivy-rendererignore,readonly" \
    "$trivy" image --input /images/image.tar "${flags[@]}" "${renderer_flags[@]}" || status=1
done
exit "$status"
