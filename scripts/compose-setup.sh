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

print_setup_complete_banner() {
  cat <<'EOF'
##############################################################################
##############################################################################
##                                                                          ##
##                           SETUP COMPLETE                                 ##
##                                                                          ##
##                 Docker Compose NAS is fully configured.                  ##
##                                                                          ##
##                  You can now open the configured services.                ##
##                                                                          ##
##############################################################################
EOF
}

strip_wrapping_quotes() {
  local value="$1"
  if [[ "$value" == \"*\" && "$value" == *\" ]]; then
    value="${value:1:${#value}-2}"
  fi
  printf '%s' "$value"
}

get_config_root() {
  local config_root="."
  local line

  if [[ -f "$ROOT_DIR/.env" ]]; then
    line=$(grep -E '^CONFIG_ROOT=' "$ROOT_DIR/.env" | tail -n 1 || true)
    if [[ -n "$line" ]]; then
      config_root=$(strip_wrapping_quotes "${line#*=}")
    fi
  fi

  if [[ "$config_root" = /* ]]; then
    printf '%s' "$config_root"
  else
    printf '%s/%s' "$ROOT_DIR" "$config_root"
  fi
}

repair_seerr_config_permissions() {
  local seerr_config_dir

  seerr_config_dir="$(get_config_root)/seerr"
  mkdir -p "$seerr_config_dir/logs"
  chmod -R a+rwX "$seerr_config_dir"
  log "Repaired Seerr config volume permissions"
}

clean_appledouble_files() {
  local config_root

  config_root="$(get_config_root)"
  find "$config_root" -name '._*' -delete 2>/dev/null || true
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
clean_appledouble_files
repair_seerr_config_permissions
wait_for_stack

log "Running first-run post-start configuration"
./scripts/update-config.sh
clean_appledouble_files
wait_for_stack

log "Automating app-to-app connections"
python3 ./scripts/configure-app-connections.py
clean_appledouble_files
wait_for_stack

log "Setup complete"
print_setup_complete_banner
