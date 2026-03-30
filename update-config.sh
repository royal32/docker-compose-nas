#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# See https://stackoverflow.com/a/44864004 for the sed GNU/BSD compatible hack

function update_arr_config {
  echo "Updating ${container} configuration..."
  until [ -f "${CONFIG_ROOT:-.}"/"$container"/config.xml ]; do sleep 1; done
  sed -i.bak "s/<UrlBase><\/UrlBase>/<UrlBase>\/$1<\/UrlBase>/" "${CONFIG_ROOT:-.}"/"$container"/config.xml && rm "${CONFIG_ROOT:-.}"/"$container"/config.xml.bak
  CONTAINER_NAME_UPPER=$(echo "$container" | tr '[:lower:]' '[:upper:]')
  sed -i.bak 's/^'"${CONTAINER_NAME_UPPER}"'_API_KEY=.*/'"${CONTAINER_NAME_UPPER}"'_API_KEY='"$(sed -n 's/.*<ApiKey>\(.*\)<\/ApiKey>.*/\1/p' "${CONFIG_ROOT:-.}"/"$container"/config.xml)"'/' .env && rm .env.bak
  echo "Update of ${container} configuration complete, restarting..."
  docker compose restart "$container"
}

function update_qbittorrent_config {
    echo "Updating ${container} configuration..."
    docker compose stop "$container"
    local qbittorrent_config="${CONFIG_ROOT:-.}"/"$container"/qBittorrent/qBittorrent.conf
    until [ -f "$qbittorrent_config" ]; do sleep 1; done

    if grep -q '^WebUI\\Password_PBKDF2=' "$qbittorrent_config"; then
      sed -i.bak 's|^WebUI\\Password_PBKDF2=.*|WebUI\\Password_PBKDF2="@ByteArray(ARQ77eY1NUZaQsuDHbIMCA==:0WMRkYTUWVT9wVvdDtHAjU9b3b7uB8NR1Gur2hmQCvCDpm39Q+PsJRJPaCU51dEiz+dTzh8qbPsL8WkFljQYFQ==)"|' "$qbittorrent_config"
    else
      local tmp_file
      tmp_file=$(mktemp)
      awk '
        /WebUI\\ServerDomains=\*/ && !inserted {
          print
          print "WebUI\\Password_PBKDF2=\"@ByteArray(ARQ77eY1NUZaQsuDHbIMCA==:0WMRkYTUWVT9wVvdDtHAjU9b3b7uB8NR1Gur2hmQCvCDpm39Q+PsJRJPaCU51dEiz+dTzh8qbPsL8WkFljQYFQ==)\""
          inserted=1
          next
        }
        { print }
        END {
          if (!inserted) {
            print "WebUI\\Password_PBKDF2=\"@ByteArray(ARQ77eY1NUZaQsuDHbIMCA==:0WMRkYTUWVT9wVvdDtHAjU9b3b7uB8NR1Gur2hmQCvCDpm39Q+PsJRJPaCU51dEiz+dTzh8qbPsL8WkFljQYFQ==)\""
          }
        }
      ' "$qbittorrent_config" > "$tmp_file"
      mv "$tmp_file" "$qbittorrent_config"
    fi

    rm -f "$qbittorrent_config".bak
    echo "Update of ${container} configuration complete, restarting..."
    docker compose start "$container"
}

function update_bazarr_config {
    echo "Updating ${container} configuration..."
    local bazarr_config="${CONFIG_ROOT:-.}"/"$container"/config/config/config.yaml
    until [ -f "$bazarr_config" ]; do sleep 1; done
    sed -i.bak "s|base_url: ''|base_url: '/$container'|" "$bazarr_config" && rm "$bazarr_config".bak
    sed -i.bak "s/use_radarr: false/use_radarr: true/" "$bazarr_config" && rm "$bazarr_config".bak
    sed -i.bak "s/use_sonarr: false/use_sonarr: true/" "$bazarr_config" && rm "$bazarr_config".bak
    until [ -f "${CONFIG_ROOT:-.}"/sonarr/config.xml ]; do sleep 1; done
    SONARR_API_KEY=$(sed -n 's/.*<ApiKey>\(.*\)<\/ApiKey>.*/\1/p' "${CONFIG_ROOT:-.}"/sonarr/config.xml)
    sed -i.bak \
      -e "/sonarr:/,/^radarr:/ s|apikey: .*|apikey: $SONARR_API_KEY|" \
      -e "/sonarr:/,/^radarr:/ s|base_url: .*|base_url: '/sonarr'|" \
      -e "/sonarr:/,/^radarr:/ s|ip: .*|ip: sonarr|" \
      "$bazarr_config" && rm "$bazarr_config".bak
    until [ -f "${CONFIG_ROOT:-.}"/radarr/config.xml ]; do sleep 1; done
    RADARR_API_KEY=$(sed -n 's/.*<ApiKey>\(.*\)<\/ApiKey>.*/\1/p' "${CONFIG_ROOT:-.}"/radarr/config.xml)
    sed -i.bak \
      -e "/radarr:/,/^sonarr:/ s|apikey: .*|apikey: $RADARR_API_KEY|" \
      -e "/radarr:/,/^sonarr:/ s|base_url: .*|base_url: '/radarr'|" \
      -e "/radarr:/,/^sonarr:/ s|ip: .*|ip: radarr|" \
      "$bazarr_config" && rm "$bazarr_config".bak
    sed -i.bak 's/^BAZARR_API_KEY=.*/BAZARR_API_KEY='"$(sed -n 's/.*apikey: \(.*\)*/\1/p' "$bazarr_config" | head -n 1)"'/' .env && rm .env.bak
    echo "Update of ${container} configuration complete, restarting..."
    docker compose restart "$container"
}

for container in $(docker compose ps --services --status running); do
  if [[ "$container" =~ ^(radarr|sonarr|lidarr|prowlarr)$ ]]; then
    update_arr_config "$container"
  elif [[ "$container" =~ ^(bazarr)$ ]]; then
    update_bazarr_config "$container"
  elif [[ "$container" =~ ^(qbittorrent)$ ]]; then
    update_qbittorrent_config "$container"
  fi
done
