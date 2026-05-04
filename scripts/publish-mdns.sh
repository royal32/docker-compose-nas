#!/bin/bash

set -euo pipefail

log() {
  printf '[mdns] %s\n' "$1"
}

detect_name() {
  local name="${LOCAL_MDNS_HOSTNAME:-}"

  if [[ -z "$name" && -f /host/etc/hostname ]]; then
    name=$(cat /host/etc/hostname)
  fi

  name="${name%%.*}"
  name=$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]//g')

  if [[ -z "$name" || "$name" == "localhost" ]]; then
    return 1
  fi

  printf '%s.local' "$name"
}

detect_ip() {
  local ip="${MDNS_ADVERTISE_IP:-}"

  if [[ -n "$ip" ]]; then
    printf '%s' "$ip"
    return 0
  fi

  ip=$(ip route get 1.1.1.1 2>/dev/null | awk '
    {
      for (i = 1; i <= NF; i++) {
        if ($i == "src") {
          print $(i + 1)
          exit
        }
      }
    }
  ')

  if [[ -z "$ip" ]]; then
    ip=$(hostname -i 2>/dev/null | awk '{ print $1 }')
  fi

  [[ -n "$ip" ]] || return 1
  printf '%s' "$ip"
}

name=$(detect_name)
ip=$(detect_ip)

mkdir -p /run/dbus
rm -f /run/dbus/pid /run/dbus/dbus.pid
dbus-daemon --system --fork
avahi-daemon --no-chroot --daemonize

log "Advertising ${name} at ${ip}"
while true; do
  if avahi-resolve-host-name "$name" >/dev/null 2>&1; then
    log "${name} is already advertised on this network"
  else
    avahi-publish -a -R "$name" "$ip" || log "Advertisement failed; retrying"
  fi
  sleep 60
done
