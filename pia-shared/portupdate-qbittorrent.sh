#!/bin/sh

set -eu

port_file=/pia-shared/port.dat
cookie_file=/tmp/qbit-portupdate-cookies.txt
qbit_url=http://127.0.0.1:8080

if [ ! -f "$port_file" ]; then
  echo "[pf] qBittorrent port update skipped: $port_file is missing"
  exit 0
fi

port="$(cat "$port_file")"
if [ -z "$port" ]; then
  echo "[pf] qBittorrent port update skipped: forwarded port is empty"
  exit 0
fi

for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS \
    -c "$cookie_file" \
    -b "$cookie_file" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    --data "username=${QBT_USER:-admin}&password=${QBT_PASS:-adminadmin}" \
    "$qbit_url/api/v2/auth/login" >/dev/null &&
    curl -fsS \
      -b "$cookie_file" \
      -H "Content-Type: application/x-www-form-urlencoded" \
      --data-urlencode "json={\"listen_port\":${port}}" \
      "$qbit_url/api/v2/app/setPreferences" >/dev/null; then
    echo "[pf] qBittorrent port updated successfully (${port})"
    exit 0
  fi

  echo "[pf] qBittorrent port update attempt ${attempt} failed; retrying..."
  sleep 3
done

echo "[pf] qBittorrent port update skipped: qBittorrent API was not ready"
exit 0
