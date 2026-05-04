#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

./setup-stack.sh --no-up --no-bootstrap --no-connections --no-wait --set USER_ID="${USER_ID:-1000}" --set GROUP_ID="${GROUP_ID:-1000}"
