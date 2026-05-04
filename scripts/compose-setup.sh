#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WAIT_TIMEOUT="${SETUP_WAIT_TIMEOUT:-300}"

log() {
  printf '[compose-setup] %s\n' "$1"
}

die() {
  printf '[compose-setup] error: %s\n' "$1" >&2
  exit 1
}

wait_for_stack() {
  local deadline
  local container_id
  local name
  local status_line
  local status_value
  local pending_count

  deadline=$((SECONDS + WAIT_TIMEOUT))

  while (( SECONDS < deadline )); do
    pending_count=0

    while IFS= read -r container_id; do
      [[ -n "$container_id" ]] || continue
      name=$(docker inspect --format '{{.Name}}' "$container_id" | sed 's|^/||')
      [[ "$name" == "stack-setup" ]] && continue
      [[ "$name" == "stack-bootstrap" ]] && continue

      status_line=$(docker inspect --format '{{.Name}} {{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id")
      status_value="${status_line##* }"

      case "$status_value" in
        healthy|running)
          ;;
        starting|created)
          pending_count=$((pending_count + 1))
          ;;
        *)
          die "Container status check failed: $status_line"
          ;;
      esac
    done < <(cd "$ROOT_DIR" && docker compose ps -q)

    if (( pending_count == 0 )); then
      log "Running compose services are ready"
      return 0
    fi

    sleep 5
  done

  die "Timed out waiting for compose services to become ready"
}

cd "$ROOT_DIR"
wait_for_stack

log "Running first-run post-start configuration"
./scripts/update-config.sh

log "Automating app-to-app connections"
python3 ./scripts/configure-app-connections.py

log "Setup complete"
